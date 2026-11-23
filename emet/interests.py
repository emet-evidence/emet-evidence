#!/usr/bin/env python3
"""Declarations of interest of the included studies and of their authors (methodology/agents/declarations-of-interest.md).

Scripts only (no model call): collection of the sources, search of the authors' other publications on the topic,
identity criteria, checks of the agents' outputs (verbatim quotations, controlled values, vocabulary) and
consolidation. Agents read the files written here and decide; their outputs are checked before use.

  python3 -m emet.interests collect <topic> [--offline]              # level 1: sources of each included study
  python3 -m emet.interests authors <topic> [--offline] [--refresh]  # level 2: candidates from other publications
  python3 -m emet.interests check <topic> studies|authors            # agents' outputs (exit 1 on error)
  python3 -m emet.interests final <topic>                            # interests-final.json (A/B, adjudication, corrections)

Files: <search folder>/screening/interests/. Raw responses are archived with date and SHA-256 hash; abstracts and
full texts are never copied there, only the declaration and funding statements.
"""
import hashlib, json, re, sys, time, unicodedata, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from emet import pubmed_cache
from emet.workspace import ROOT, config, search_folder

WINDOW_MONTHS = 36  # ICMJE disclosure period, before and after the included study
BATCH = 50
FUNDING_STATUS = ('reported', 'no_funding_declared', 'not_reported', 'not_accessible')
DECLARATION_STATUS = ('links_declared', 'no_link_declared', 'not_reported', 'not_accessible')
FUNDER_TYPES = ('industry', 'public', 'non_profit', 'institutional', 'other')
LINK_TYPES = ('employment', 'consultancy', 'speaker', 'advisory_board', 'royalties', 'research_support', 'equity', 'patent',
              'travel_or_hospitality', 'material_support', 'other', 'unspecified')
DECISIONS = ('possible_link', 'not_retained')
CORRECTION_STATUS = ('under_examination', 'removed', 'confirmed')
# Wording that suggests a fault, excluded from everything the agents or the engine write (not from verbatim quotations,
# which reproduce the source). English and French forms; `confli(?:c?t)` covers both languages.
FORBIDDEN = re.compile(r'\bconfli(?:c?t)|undeclared|non[- ]declared|\bomit|\bomission|failed to disclose|\bhidden|\bconceal|discrepan|'
                       r'inconsisten|non[- ]déclar|\bomis\b|\bomise|\bcaché|dissimul|divergen|incohéren', re.I)
# Fields copied from a source or written by the person concerned (section headings included).
VERBATIM_KEYS = {'quote', 'text', 'author', 'entity', 'name', 'sponsor', 'label', 'title', 'affiliations', 'url', 'location', 'author_statement'}
INSTITUTION = re.compile(r'univ|hospit|hôpital|klinik|clinic|institut|center|centre|college|school|faculty|ospedale|chu\b|medical', re.I)
ORCID = re.compile(r'\d{4}-\d{4}-\d{4}-\d{3}[\dX]')
MONTHS = {m: i for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}


def now():
    return datetime.now(timezone.utc).isoformat()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def folder(subject):
    return search_folder(subject) / 'screening' / 'interests'


def review_data(subject):
    return load(ROOT / f'data/reviews/{subject}.json')


def protocol(subject):
    return load(ROOT / f'data/protocols/{subject}.json')


def entities(subject):
    """Relevant entities of the protocol (`interest_entities`); the module cannot run without them (fail closed)."""
    found = protocol(subject).get('interest_entities')
    if not isinstance(found, list):
        raise SystemExit(f'{subject}: the protocol has no "interest_entities" list (agents/protocol.md); an empty list must be explicit')
    return found


# ---- Text helpers -----------------------------------------------------------------------------------------

def squash(text):
    text = unicodedata.normalize('NFKC', text or '')
    text = text.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"').replace('–', '-').replace('—', '-')
    return re.sub(r'\s+', ' ', text).strip().casefold()


def quoted(quote, source_text):
    """A quotation is accepted only if it is found verbatim (whitespace, case and typographic quotes aside)."""
    return bool(quote) and squash(quote) in squash(source_text)


def fold(name):
    return re.sub(r'[^a-z]', '', unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower())


def forbidden(value, path='$'):
    """Paths of the strings that contain fault-suggesting wording (verbatim fields excepted)."""
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in VERBATIM_KEYS and not (k == 'declaration' and isinstance(v, str)):  # a person's own declaration
                found += forbidden(v, f'{path}.{k}')
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found += forbidden(v, f'{path}[{i}]')
    elif isinstance(value, str) and FORBIDDEN.search(value):
        found.append(f'{path}: "{FORBIDDEN.search(value).group(0)}"')
    return found


def mentions(text, entity_list):
    """Ids of the relevant entities whose name or alias appears in `text` (word boundaries, case-insensitive)."""
    out = []
    for e in entity_list:
        names = [e.get('name', '')] + list(e.get('aliases', []))
        if any(n and re.search(r'(?<!\w)' + re.escape(n) + r'(?!\w)', text or '', re.I) for n in names):
            out.append(e['id'])
    return out


# ---- PubMed records ---------------------------------------------------------------------------------------

def _text(element):
    return re.sub(r'\s+', ' ', ''.join(element.itertext())).strip() if element is not None else ''


def pub_date(root):
    """(year, month or None) of publication: journal issue date, else the electronic date."""
    for path in ('.//Article/Journal/JournalIssue/PubDate', './/Book/PubDate', './/Article/ArticleDate'):
        node = root.find(path)
        if node is None:
            continue
        year = node.findtext('Year') or (re.match(r'\d{4}', node.findtext('MedlineDate') or '') or [None])[0]
        if not year:
            continue
        month = (node.findtext('Month') or '').strip().lower()
        month = int(month) if month.isdigit() else MONTHS.get(month[:3])
        return int(year), month
    return None, None


def details(pmid):
    """Authors (with ORCID and affiliations), declaration statement, grants, DOI and date of a cached PubMed record."""
    record = load(pubmed_cache.article_path(pmid))
    root = ET.fromstring(record['raw_record_xml'])
    authors = []
    for a in root.findall('.//AuthorList/Author'):
        if a.find('LastName') is None:
            continue
        orcid = next((ORCID.search(_text(i)).group(0) for i in a.findall('Identifier') if i.get('Source') == 'ORCID' and ORCID.search(_text(i))), None)
        authors.append({'family': _text(a.find('LastName')), 'given': _text(a.find('ForeName')), 'initials': _text(a.find('Initials')),
                        'orcid': orcid, 'affiliations': [_text(x) for x in a.findall('./AffiliationInfo/Affiliation')]})
    year, month = pub_date(root)
    return {'pmid': str(pmid), 'title': record.get('title'), 'authors': authors, 'coi': _text(root.find('.//CoiStatement')),
            'grants': [{'id': g.findtext('GrantID'), 'agency': g.findtext('Agency'), 'country': g.findtext('Country')} for g in root.findall('.//GrantList/Grant')],
            'doi': record.get('identifiers', {}).get('doi'), 'pmc': record.get('identifiers', {}).get('pmc'),
            'year': year, 'month': month, 'sha256': record.get('raw_record_sha256')}


def author_key(a):
    return f"{fold(a['family'])} {fold(a.get('initials') or a.get('given', '')[:1])}"


def same_name(a, b):
    """Same surname and compatible initials (one is a prefix of the other)."""
    if fold(a['family']) != fold(b['family']):
        return False
    ia, ib = fold(a.get('initials') or a.get('given', '')[:1]), fold(b.get('initials') or b.get('given', '')[:1])
    return bool(ia and ib) and (ia.startswith(ib) or ib.startswith(ia))


def institutions(a):
    return {squash(part) for aff in a.get('affiliations', []) for part in re.split(r'[,;]', aff) if INSTITUTION.search(part)}


def identity(author, study_authors, other, other_authors):
    """Identity criteria between an author of an included study and the same name in another record.
    Returns the criteria met (besides the name), or None when ORCIDs contradict each other."""
    if author.get('orcid') and other.get('orcid'):
        return ['orcid'] if author['orcid'] == other['orcid'] else None
    criteria = []
    if institutions(author) & institutions(other):
        criteria.append('institution')
    coauthors = {author_key(x) for x in study_authors if not same_name(x, author)}
    if coauthors & {author_key(x) for x in other_authors if not same_name(x, other)}:
        criteria.append('coauthor')
    return criteria


def months_between(a, b):
    """Months from date a to date b, or None; with a year-only date, whole years (precision stated by the caller)."""
    (ya, ma), (yb, mb) = a, b
    if ya is None or yb is None:
        return None
    if ma is None or mb is None:
        return (yb - ya) * 12
    return (yb - ya) * 12 + (mb - ma)


# ---- Network (archived, cache-first) ----------------------------------------------------------------------

def fetch_json(url, path, offline, refresh=False, data=None):
    """Archived JSON response at `path` (raw text, URL, date, SHA-256); None if offline and not archived, or on failure."""
    if path.exists() and not refresh:
        return json.loads(load(path)['raw'])
    if offline:
        return None
    try:
        time.sleep(0.4)
        req = urllib.request.Request(url, data=data, headers={'User-Agent': pubmed_cache.USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode()
    except Exception as error:
        save(path.with_suffix('.error.json'), {'url': url, 'error': str(error), 'at': now()})
        return None
    save(path, {'url': url, 'retrieved_at': now(), 'raw': raw, 'sha256': hashlib.sha256(raw.encode()).hexdigest()})
    return json.loads(raw)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def jats_declarations(pmcid):
    """Declaration and funding sections of an archived Europe PMC full text (data/fulltext/<PMCID>.json)."""
    path = ROOT / 'data/fulltext' / f'{pmcid}.json'
    if not pmcid or not path.exists():
        return []
    root = ET.fromstring(load(path)['raw_xml'])
    out = []
    for fn in root.iter('fn'):
        if (fn.get('fn-type') or '').lower() in ('coi-statement', 'conflict', 'competing-interests', 'financial-disclosure', 'supported-by'):
            out.append(('full text, ' + fn.get('fn-type'), _text(fn)))
    for sec in root.iter('sec'):
        title = sec.findtext('title') or ''
        if (sec.get('sec-type') or '').lower() == 'coi-statement' or re.search(r'competing|disclos|declaration|interest|funding', title, re.I):
            out.append((f'full text, {title or sec.get("sec-type")}', _text(sec)))
    for node in root.iter('funding-statement'):
        out.append(('full text, funding statement', _text(node)))
    return [(loc, txt) for loc, txt in out if txt]


# ---- Level 1: sources of each included study --------------------------------------------------------------

def registries(subject, reports):
    from emet.cohort_overlap import registries as found
    return sorted(found(subject, reports))


def collect(subject, offline=False):
    review, ents = review_data(subject), entities(subject)
    out_dir = folder(subject)
    pmids = [r for s in review['studies'] for r in s['reports'] if str(r).isdigit()]
    pubmed_cache.fetch_records(pmids, offline=offline)
    if not offline:
        pubmed_cache.fetch_fulltexts(pmids)
    sources = {}
    for s in review['studies']:
        items = []

        def add(kind, report, location, text, url, sha=None):
            if text:
                items.append({'id': f'src-{len(items) + 1}', 'kind': kind, 'report': report, 'location': location, 'text': text,
                              'url': url, 'sha256': sha or hashlib.sha256(text.encode()).hexdigest(),
                              'entities_mentioned': mentions(text, ents)})
        for r in s['reports']:
            if not str(r).isdigit():
                continue
            d = details(r)
            url = f'https://pubmed.ncbi.nlm.nih.gov/{r}/'
            add('pubmed_declaration', r, 'PubMed record, CoiStatement', d['coi'], url, d['sha256'])
            add('pubmed_grants', r, 'PubMed record, GrantList', '; '.join(' · '.join(x for x in (g['agency'], g['id'], g['country']) if x) for g in d['grants']), url, d['sha256'])
            for loc, txt in jats_declarations(d['pmc']):
                add('fulltext_declaration', r, loc, txt, f'https://europepmc.org/article/PMC/{d["pmc"]}')
            if d['doi']:
                doi = d['doi'].lower()
                msg = (fetch_json(f'https://api.crossref.org/works/{urllib.parse.quote(doi)}', out_dir / 'sources' / f'crossref-{digest(doi)}.json', offline) or {}).get('message', {})
                funders = [' · '.join(x for x in (f.get('name'), ', '.join(f.get('award', []))) if x) for f in msg.get('funder', [])]
                add('crossref_funders', r, 'Crossref record, funder', '; '.join(funders), f'https://doi.org/{doi}')
        for nct in registries(subject, s['reports']):
            if not nct.startswith('NCT'):
                continue
            data = fetch_json(f'https://clinicaltrials.gov/api/v2/studies/{nct}', out_dir / 'sources' / f'ctgov-{nct}.json', offline) or {}
            module = data.get('protocolSection', {}).get('sponsorCollaboratorsModule', {})
            parties = [f"lead sponsor: {module['leadSponsor']['name']} ({module['leadSponsor'].get('class', '')})"] if module.get('leadSponsor') else []
            parties += [f"collaborator: {c['name']} ({c.get('class', '')})" for c in module.get('collaborators', [])]
            add('registry_sponsor', nct, 'ClinicalTrials.gov, sponsor and collaborators', '; '.join(parties), f'https://clinicaltrials.gov/study/{nct}')
        sources[s['id']] = {'label': s['label'], 'reports': s['reports'], 'items': items}
        lines = [f"Study {s['id']} · {s['label']}", f"Reports: {', '.join(s['reports'])}",
                 'Relevant entities: ' + ('; '.join(f"{e['id']} {e['name']}" + (f" ({', '.join(e.get('aliases', []))})" if e.get('aliases') else '') for e in ents) or 'none'), '']
        lines += [f"### {i['id']} · {i['location']} · report {i['report']}\n{i['text']}\n" for i in items] or ['(no declaration or funding statement found in the archived records)']
        (out_dir / 'studies').mkdir(parents=True, exist_ok=True)
        (out_dir / 'studies' / f"{s['id'].replace(':', '_')}.txt").write_text('\n'.join(lines) + '\n', encoding='utf-8')
    save(out_dir / 'study-sources.json', {'generated_at': now(), 'offline': offline, 'entities': ents, 'studies': sources})
    print(f'{subject}: {len(sources)} studies, {sum(len(v["items"]) for v in sources.values())} source statements; files in {out_dir.relative_to(ROOT)}/studies/')


def source_text(subject, study, source_id, study_sources):
    """Text a level-1 quotation must be found in: a collected statement (src-N) or an eligibility file (eligibility:<report>)."""
    if source_id and source_id.startswith('eligibility:'):
        path = search_folder(subject) / 'screening/eligibility' / f"{source_id.split(':', 1)[1].replace(':', '_')}.txt"
        return path.read_text(encoding='utf-8') if path.exists() else ''
    return next((i['text'] for i in study_sources.get(study, {}).get('items', []) if i['id'] == source_id), '')


def check_studies(subject, data, ents, study_sources, studies):
    errors, ids = [], {e['id'] for e in ents}
    for sid in data:
        if sid not in studies:
            errors.append(f'{sid}: not an included study')
    for sid, entry in data.items():
        f, d = entry.get('funding', {}), entry.get('declaration', {})
        if f.get('status') not in FUNDING_STATUS:
            errors.append(f'{sid}: funding.status {f.get("status")!r}')
        if d.get('status') not in DECLARATION_STATUS:
            errors.append(f'{sid}: declaration.status {d.get("status")!r}')
        if d.get('status') in ('links_declared', 'no_link_declared') and not quoted(d.get('quote'), source_text(subject, sid, d.get('source'), study_sources)):
            errors.append(f'{sid}: declaration quote not found in {d.get("source")}')
        for kind, items in (('funding', f.get('items', [])), ('link', d.get('links', []))):
            for i, item in enumerate(items):
                if kind == 'funding' and item.get('type') not in FUNDER_TYPES:
                    errors.append(f'{sid}: funding[{i}].type {item.get("type")!r}')
                if kind == 'link' and item.get('type') not in LINK_TYPES:
                    errors.append(f'{sid}: links[{i}].type {item.get("type")!r}')
                if item.get('relevant_entity') is not None and item['relevant_entity'] not in ids:
                    errors.append(f'{sid}: {kind}[{i}] unknown relevant entity {item["relevant_entity"]!r}')
                if not quoted(item.get('quote'), source_text(subject, sid, item.get('source'), study_sources)):
                    errors.append(f'{sid}: {kind}[{i}] quote not found in {item.get("source")}')
        if d.get('status') == 'links_declared' and not d.get('links'):
            errors.append(f'{sid}: links_declared without links')
    return errors + forbidden(data)


# ---- Level 2: other publications of the same authors on the topic -----------------------------------------

def topic_query(subject):
    """Topic restriction: `interest_topic_query` of the protocol, else the PubMed queries archived in the search folder."""
    q = protocol(subject).get('interest_topic_query')
    if q:
        return q
    queries = []
    for path in sorted(search_folder(subject).glob('*.json')):
        d = load(path)
        if isinstance(d, dict) and 'esearchresult' in d and d.get('query'):
            queries.append(f"({d['query']})")
    if not queries:
        raise SystemExit(f'{subject}: no topic query (protocol "interest_topic_query" or archived PubMed searches)')
    return ' OR '.join(queries)


def esearch(term, path, offline, refresh):
    body = urllib.parse.urlencode({'db': 'pubmed', 'term': term, 'retmode': 'json', 'retmax': 9999}).encode()
    result = fetch_json(pubmed_cache.EUTILS + 'esearch.fcgi', path, offline, refresh, data=body)
    if result is None:
        return None
    r = result['esearchresult']
    if int(r['count']) > len(r['idlist']):
        raise RuntimeError(f'pagination required for {term[:80]}…')
    return r['idlist']


def window(year, month):
    lo, hi = year - WINDOW_MONTHS // 12, year + WINDOW_MONTHS // 12
    m = month or 1
    return f'{lo}/{m:02d}/01', f'{hi}/{(month or 12):02d}/28'


def authors_stage(subject, offline=False, refresh=False):
    review, ents = review_data(subject), entities(subject)
    out_dir = folder(subject)
    topic = topic_query(subject)
    studies = {}
    for s in review['studies']:
        pmids = [r for r in s['reports'] if str(r).isdigit()]
        if pmids:
            pubmed_cache.fetch_records(pmids, offline=offline)
            studies[s['id']] = [details(p) for p in pmids]
    summary = {'studies_with_record': len(studies), 'studies_without_record': len(review['studies']) - len(studies),
               'authors': 0, 'searches_not_collected': 0, 'other_publications': 0, 'outside_window': 0, 'no_declaration': 0,
               'identity_not_confirmed': 0, 'orcid_differs': 0, 'no_relevant_entity': 0, 'candidates': 0}
    candidates = []
    for sid, records in studies.items():
        primary = records[0]
        own = {r['pmid'] for r in records}
        study_authors = [a for r in records for a in r['authors']]
        seen = set()
        for author in primary['authors']:
            key = author_key(author)
            if key in seen:
                continue
            seen.add(key)
            summary['authors'] += 1
            if primary['year'] is None or not author['initials']:  # without date or initials the search is not specific enough
                summary['searches_not_collected'] += 1
                continue
            lo, hi = window(primary['year'], primary['month'])
            term = f'({topic}) AND "{author["family"]} {author["initials"]}"[au] AND ("{lo}"[dp] : "{hi}"[dp])'
            found = esearch(term, out_dir / 'author-corpus' / f'esearch-{digest(term)}.json', offline, refresh)
            if found is None:
                summary['searches_not_collected'] += 1
                continue
            others = [p for p in found if p not in own]
            if not others:
                continue
            try:
                pubmed_cache.fetch_records(others, offline=offline)
            except RuntimeError:
                others = [p for p in others if pubmed_cache.article_path(p).exists()]
            for pmid in others:
                summary['other_publications'] += 1
                other = details(pmid)
                delta = months_between((primary['year'], primary['month']), (other['year'], other['month']))
                if delta is None or abs(delta) > WINDOW_MONTHS:
                    summary['outside_window'] += 1
                    continue
                match = next((a for a in other['authors'] if same_name(a, author)), None)
                statements = ([('PubMed record, CoiStatement', other['coi'], f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/')] if other['coi'] else []) + \
                             [(loc, txt, f'https://europepmc.org/article/PMC/{other["pmc"]}') for loc, txt in jats_declarations(other['pmc'])]
                if not statements:
                    summary['no_declaration'] += 1
                    continue
                criteria = identity(author, study_authors, match, other['authors']) if match else []
                if criteria is None:
                    summary['orcid_differs'] += 1
                    continue
                if not criteria:
                    summary['identity_not_confirmed'] += 1
                    continue
                for loc, txt, url in statements:
                    found_entities = mentions(txt, ents)
                    if not found_entities:
                        summary['no_relevant_entity'] += 1
                        continue
                    cid = hashlib.sha1(f'{sid}|{key}|{pmid}|{loc}'.encode()).hexdigest()[:10]
                    candidates.append({'id': cid, 'study': sid, 'author': f'{author["family"]} {author["initials"]}', 'author_key': key,
                                       'identity': ['name'] + criteria, 'entities_mentioned': found_entities, 'months_from_study': delta,
                                       'date_precision': 'month' if primary['month'] and other['month'] else 'year',
                                       'source': {'pmid': pmid, 'title': other['title'], 'year': other['year'], 'location': loc, 'url': url, 'text': txt}})
    summary['candidates'] = len(candidates)
    batches = out_dir / 'author-batches'
    batches.mkdir(parents=True, exist_ok=True)
    for old in batches.glob('batch-*.json'):
        old.unlink()
    for n in range(0, len(candidates), BATCH):
        save(batches / f'batch-{n // BATCH + 1:02d}.json', candidates[n:n + BATCH])
    save(out_dir / 'author-candidates.json', {'generated_at': now(), 'offline': offline, 'topic_query': topic, 'window_months': WINDOW_MONTHS,
                                              'entities': ents, 'summary': summary, 'candidates': candidates})
    print(f'{subject}: ' + ', '.join(f'{k} {v}' for k, v in summary.items()))


def check_authors(data, candidates, ents):
    errors, ids = [], {e['id'] for e in ents}
    by_id = {c['id']: c for c in candidates}
    missing = sorted(set(by_id) - set(data))
    if missing:
        errors.append(f'{len(missing)} candidates without a decision: {missing[:5]}')
    for cid, d in data.items():
        c = by_id.get(cid)
        if not c:
            errors.append(f'{cid}: unknown candidate')
            continue
        if d.get('decision') not in DECISIONS:
            errors.append(f'{cid}: decision {d.get("decision")!r}')
        if not d.get('reason'):
            errors.append(f'{cid}: reason missing')
        if d.get('decision') == 'possible_link':
            if d.get('relevant_entity') not in ids:
                errors.append(f'{cid}: relevant entity {d.get("relevant_entity")!r}')
            if d.get('type') not in LINK_TYPES:
                errors.append(f'{cid}: type {d.get("type")!r}')
            if not quoted(d.get('quote'), c['source']['text']):
                errors.append(f'{cid}: quote not found in the source statement')
    return errors + forbidden(data)


# ---- Consolidation ----------------------------------------------------------------------------------------

def optional(path):
    return load(path) if path.exists() else None


def profile_single(key):
    """True if the profile has no reviewer B for this part of the module (exploratory profile)."""
    from emet.orchestrate import profile
    return profile(config().get('profile', 'rapid')).get('interests', {}).get(key, {}).get('B', 'x') is None


def l1_signature(entry):
    f, d = entry.get('funding', {}), entry.get('declaration', {})
    return (f.get('status'), d.get('status'), sorted({i.get('relevant_entity') for i in f.get('items', []) if i.get('relevant_entity')}),
            sorted({(fold(i.get('author', '')), i.get('relevant_entity')) for i in d.get('links', []) if i.get('relevant_entity')}))


def merge_studies(a, b, arbitration):
    final, pending = {}, []
    for sid, entry in a.items():
        if sid in arbitration:
            final[sid] = arbitration[sid]
        elif sid not in b:
            final[sid] = entry  # outside the dual coverage of the profile
        elif l1_signature(entry) == l1_signature(b[sid]):
            final[sid] = entry
        else:
            pending.append(sid)
    return final, pending


def merge_authors(a, b, arbitration, single):
    final, pending = {}, []
    for cid, da in a.items():
        if cid in arbitration:
            final[cid] = arbitration[cid]
            continue
        if single:
            final[cid] = da
            continue
        db = b.get(cid)
        if db is None:
            pending.append(cid)
        elif da['decision'] == db['decision'] and (da['decision'] == 'not_retained' or
                                                   (da.get('relevant_entity'), da.get('type')) == (db.get('relevant_entity'), db.get('type'))):
            final[cid] = da
        else:
            pending.append(cid)
    return final, pending


def team_authorship(review, team, decisions):
    """Included studies of which a member of the review team may be an author: ORCID, then name (surname + first initial)."""
    out = []
    for s in review['studies']:
        authors = [a for r in s['reports'] if str(r).isdigit() and pubmed_cache.article_path(r).exists() for a in details(r)['authors']]
        for m in team:
            family, given = m.get('family') or m['name'].split()[-1], m.get('given') or m['name'].split()[0]
            how = None
            if m.get('orcid') and any(a.get('orcid') == m['orcid'] for a in authors):
                how = 'orcid'
            elif any(fold(a['family']) == fold(family) and fold(a.get('initials') or a['given'][:1])[:1] == fold(given)[:1] for a in authors):
                how = 'name'
            if not how:
                continue
            decision = decisions.get(s['id'], {}).get(m['name'])
            if decision != 'not_author':
                out.append({'study': s['id'], 'label': s['label'], 'member': m['name'], 'matched_by': how,
                            'status': 'confirmed' if decision == 'author' else 'candidate'})
    return out


def visible(item_id, corrections):
    c = corrections.get(item_id)
    return not c or c['status'] == 'confirmed'


def badge(entry):
    """A study gets the badge when at least one visible item concerns a relevant entity of the protocol."""
    return any(i.get('relevant_entity') for i in entry['funding']['items'] + entry['declaration']['links'] + entry['other_publications'])


def final(subject):
    review, ents = review_data(subject), entities(subject)
    out_dir = folder(subject)
    study_sources = load(out_dir / 'study-sources.json')['studies']
    studies = {s['id']: s for s in review['studies']}
    errors = []
    a = optional(out_dir / 'study-declarations-A.json')
    if a is None:
        raise SystemExit(f'{subject}: study-declarations-A.json missing')
    b = optional(out_dir / 'study-declarations-B.json') or {}
    arb = optional(out_dir / 'study-declarations-arbitration.json') or {}
    for name, data in (('A', a), ('B', b), ('arbitration', arb)):
        errors += [f'study declarations {name}: {e}' for e in check_studies(subject, data, ents, study_sources, studies)]
    missing = sorted(set(studies) - set(a))
    if missing:
        errors.append(f'study declarations A: {len(missing)} studies without an entry: {missing[:5]}')
    l1, pending1 = merge_studies(a, b, arb)
    cand = optional(out_dir / 'author-candidates.json')
    if cand is None:
        raise SystemExit(f'{subject}: author-candidates.json missing (python3 -m emet.interests authors {subject})')
    by_id = {c['id']: c for c in cand['candidates']}
    aa = optional(out_dir / 'author-assessment-A.json') or ({} if not by_id else None)
    if aa is None:
        raise SystemExit(f'{subject}: author-assessment-A.json missing')
    ab = optional(out_dir / 'author-assessment-B.json') or {}
    aarb = optional(out_dir / 'author-assessment-arbitration.json') or {}
    for name, data in (('A', aa), ('B', ab)):
        errors += [f'author assessment {name}: {e}' for e in check_authors(data, cand['candidates'], ents)]
    errors += [f'author arbitration: {e}' for e in check_authors(aarb, cand['candidates'], ents) if 'without a decision' not in e]
    l2, pending2 = merge_authors(aa, ab, aarb, profile_single('author_declarations'))
    corrections_list = optional(out_dir / 'corrections.json') or []
    for c in corrections_list:
        if c.get('status') not in CORRECTION_STATUS:
            errors.append(f'correction {c.get("item")}: status {c.get("status")!r}')
    errors += forbidden(corrections_list, 'corrections')
    if pending1 or pending2:
        errors.append(f'disagreements to adjudicate: {len(pending1)} studies {pending1[:5]}, {len(pending2)} candidates {pending2[:5]} '
                      '(study-declarations-arbitration.json, author-assessment-arbitration.json)')
    if errors:
        for e in errors:
            print('ERROR', e)
        sys.exit(1)
    corrections = {c['item']: c for c in corrections_list}
    team = config().get('review_team') or []
    decisions = optional(out_dir / 'review-team-authorship.json') or {}
    items = []
    for sid, s in studies.items():
        e = l1[sid]
        src = {i['id']: i for i in study_sources.get(sid, {}).get('items', [])}

        def located(item, item_id):
            source = src.get(item.get('source'), {})
            return {**item, 'id': item_id, 'location': source.get('location', item.get('source')), 'url': source.get('url'),
                    'author_statement': (corrections.get(item_id) or {}).get('author_statement')}
        funding = [located(i, f'{sid}:funding:{n}') for n, i in enumerate(e['funding'].get('items', []))]
        links = [located(i, f'{sid}:link:{n}') for n, i in enumerate(e['declaration'].get('links', []))]
        other = []
        for cid, d in l2.items():
            c = by_id[cid]
            if c['study'] == sid and d['decision'] == 'possible_link' and visible(cid, corrections):
                other.append({'id': cid, 'author': c['author'], 'entity': d.get('entity') or next((x['name'] for x in ents if x['id'] == d['relevant_entity']), ''),
                              'relevant_entity': d['relevant_entity'], 'type': d['type'], 'quote': d['quote'], 'identity': c['identity'],
                              'months_from_study': c['months_from_study'], 'date_precision': c['date_precision'],
                              'source': {k: c['source'][k] for k in ('pmid', 'title', 'year', 'location', 'url')},
                              'author_statement': (corrections.get(cid) or {}).get('author_statement')})
        entry = {'study': sid, 'label': s['label'], 'page_reference': s.get('page_reference'),
                 'funding': {'status': e['funding']['status'], 'items': [i for i in funding if visible(i['id'], corrections)]},
                 'declaration': {'status': e['declaration']['status'], 'location': src.get(e['declaration'].get('source'), {}).get('location', e['declaration'].get('source')),
                                 'url': src.get(e['declaration'].get('source'), {}).get('url'), 'quote': e['declaration'].get('quote'),
                                 'links': [i for i in links if visible(i['id'], corrections)]},
                 'other_publications': sorted(other, key=lambda x: (x['author'], x['source']['year'] or 0))}
        entry['badge'] = badge(entry)
        items.append(entry)
    accessible = sum(1 for i in items if i['declaration']['status'] not in ('not_accessible', 'not_reported'))
    result = {'generated_at': now(), 'levels': ['study_declarations', 'author_publications'], 'entities': ents,
              'window_months': cand['window_months'], 'topic_query': cand['topic_query'],
              'coverage': {'studies': len(items), 'declaration_accessible': accessible, 'with_badge': sum(i['badge'] for i in items),
                           **{k: cand['summary'][k] for k in ('authors', 'searches_not_collected', 'other_publications', 'identity_not_confirmed', 'candidates')},
                           'possible_links': sum(len(i['other_publications']) for i in items)},
              'items': items,
              'corrections': [{k: c.get(k) for k in ('date', 'item', 'status', 'reason')} for c in corrections_list],
              'review_declaration': {'team': [{k: m.get(k) for k in ('name', 'role', 'orcid', 'declaration', 'declared_at')} for m in team],
                                     'coauthored_studies': team_authorship(review, team, decisions)}}
    save(out_dir / 'interests-final.json', result)
    print(f'{subject}: {len(items)} studies, {result["coverage"]["with_badge"]} with a badge, {result["coverage"]["possible_links"]} '
          f'possible links from other publications, {len(result["review_declaration"]["coauthored_studies"])} studies co-authored by the review team')


def main(argv):
    if len(argv) < 3 or argv[1] not in ('collect', 'authors', 'check', 'final'):
        sys.exit(__doc__)
    command, subject = argv[1], argv[2]
    offline, refresh = '--offline' in argv, '--refresh' in argv
    if command == 'collect':
        collect(subject, offline)
    elif command == 'authors':
        authors_stage(subject, offline, refresh)
    elif command == 'final':
        final(subject)
    else:
        part = argv[3] if len(argv) > 3 else ''
        out_dir, ents = folder(subject), entities(subject)
        errors = []
        if part == 'studies':
            sources = load(out_dir / 'study-sources.json')['studies']
            studies = {s['id'] for s in review_data(subject)['studies']}
            for name in ('A', 'B', 'arbitration'):
                data = optional(out_dir / f'study-declarations-{name}.json')
                if data is not None:
                    errors += [f'{name}: {e}' for e in check_studies(subject, data, ents, sources, studies)]
        elif part == 'authors':
            cand = load(out_dir / 'author-candidates.json')['candidates']
            for name in ('A', 'B'):
                data = optional(out_dir / f'author-assessment-{name}.json')
                if data is not None:
                    errors += [f'{name}: {e}' for e in check_authors(data, cand, ents)]
        else:
            sys.exit('check: studies | authors')
        for e in errors:
            print('ERROR', e)
        print(f'{subject} {part}: {"OK" if not errors else f"{len(errors)} error(s)"}')
        sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main(sys.argv)
