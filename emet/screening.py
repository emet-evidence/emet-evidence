#!/usr/bin/env python3
"""Dual agentic screening: build the deduplicated record set, fetch abstracts, compute agreement.

  python3 -m emet.screening records <subject>            # screening/records.json + titles.tsv
  python3 -m emet.screening abstracts <subject> <stage>  # abstracts of records kept at <stage> -> abstracts.tsv
  python3 -m emet.screening agreement <subject> <stage>  # kappa, disagreements -> <stage>-disagreements.tsv
  python3 -m emet.screening final <subject>              # final decisions and flow counts -> flow.json

Each screener writes screening/<stage>-A.json and <stage>-B.json: {"<id>": {"decision": "include"|"exclude", "code": "E1"...}}.
The arbiter writes screening/<stage>-arbitration.json for the disagreements only.
"""
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from emet.search_pubmed import titles as esummary_titles  # noqa: E402

from emet.i18n import _
from emet.workspace import ROOT, search_folder


def folder(subject):
    return search_folder(subject)


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=1) + '\n')


def norm(title):
    return re.sub(r'[^a-z0-9]', '', (title or '').lower())[:120]


def consensus_entries(path):
    if not path.exists():
        return []
    pattern = re.compile(r'^\[\d+\] \[(.+?)\]\((\S+?)\) \((.*?)\)\s*$', re.M)
    entries = []
    for title, url, meta in pattern.findall(path.read_text()):
        year = re.search(r'\b(19|20)\d{2}\b', meta)
        entries.append({'title': title, 'url': url, 'year': year.group() if year else ''})
    return entries


def records(subject):
    base = folder(subject)
    sources = {}
    pubmed_query, pubmed_snow = set(), set()
    for path in sorted(base.glob('*.json')):
        value = load(path)
        if isinstance(value, dict) and 'esearchresult' in value:
            pubmed_query |= set(value['esearchresult']['idlist'])
        elif path.name.startswith('snow'):
            for links in value.values():
                pubmed_snow |= set(links.get('pubmed_pubmed_refs', [])) | set(links.get('pubmed_pubmed_citedin', []))
    pubmed_snow -= pubmed_query
    sources[_('PubMed: queries')] = len(pubmed_query)
    sources[_('PubMed: references and citing articles')] = len(pubmed_snow)
    titles = esummary_titles(base, sorted(pubmed_query | pubmed_snow))
    pool = {}
    by_title = {}
    for pmid in sorted(pubmed_query | pubmed_snow, key=int):
        item = titles[pmid]
        pool[pmid] = {'id': pmid, 'title': item['title'], 'year': item['year'], 'journal': item['journal'], 'type': ', '.join(item['pubtype']),
                      'sources': ['pubmed-query' if pmid in pubmed_query else 'pubmed-snowball']}
        by_title.setdefault(norm(item['title']), pmid)
    # Europe PMC
    epmc_total, epmc_new = 0, 0
    for path in sorted(base.glob('europepmc-*.json')):
        for page in load(path)['pages']:
            for item in page['response'].get('resultList', {}).get('result', []):
                epmc_total += 1
                pmid = item.get('pmid')
                key = pmid if pmid in pool else by_title.get(norm(item.get('title')))
                if key:
                    pool[key]['sources'].append('europepmc')
                    continue
                epmc_new += 1
                key = pmid or f'EPMC:{item.get("source")}:{item.get("id")}'
                pool[key] = {'id': key, 'title': item.get('title', ''), 'year': item.get('pubYear', ''), 'journal': item.get('journalTitle', item.get('bookOrReportDetails', {}).get('publisher', '')),
                             'type': ', '.join(item.get('pubType', '').split('; ')) if isinstance(item.get('pubType'), str) else '', 'doi': item.get('doi', ''),
                             'sources': ['europepmc'], 'europepmc': {'source': item.get('source'), 'id': item.get('id')}}
                by_title.setdefault(norm(item.get('title')), key)
    sources['Europe PMC'] = epmc_total
    # ClinicalTrials.gov
    ct_total = 0
    for path in sorted(base.glob('ctgov-*.json')):
        for page in load(path)['pages']:
            for study in page['response'].get('studies', []):
                ct_total += 1
                protocol = study['protocolSection']
                ident = protocol['identificationModule']
                status = protocol.get('statusModule', {})
                interventions = [i.get('name', '') for i in protocol.get('armsInterventionsModule', {}).get('interventions', [])]
                outcomes = [o.get('measure', '') for o in protocol.get('outcomesModule', {}).get('primaryOutcomes', [])]
                pool[ident['nctId']] = {'id': ident['nctId'], 'title': ident.get('officialTitle') or ident.get('briefTitle', ''),
                                        'year': status.get('startDateStruct', {}).get('date', '')[:4], 'journal': 'ClinicalTrials.gov',
                                        'type': _('{type}; status {status}; results posted: {posted}', type=protocol.get('designModule', {}).get('studyType', ''),
                                                  status=status.get('overallStatus', ''), posted=_('yes') if study.get('hasResults') else _('no')),
                                        'detail': _('Interventions: {interventions} — primary outcomes: {outcomes}',
                                                    interventions=_('; ').join(interventions), outcomes=_('; ').join(outcomes)),
                                        'sources': ['clinicaltrials.gov']}
    sources['ClinicalTrials.gov'] = ct_total
    # Consensus
    cons = consensus_entries(base/'consensus.txt')
    cons_new = 0
    for entry in cons:
        key = by_title.get(norm(entry['title']))
        if key:
            pool[key]['sources'].append('consensus')
            continue
        cons_new += 1
        key = 'CONS:' + entry['url'].split('details/')[-1].split('/')[0]
        pool[key] = {'id': key, 'title': entry['title'], 'year': entry['year'], 'journal': '', 'type': '', 'url': entry['url'], 'sources': ['consensus']}
        by_title.setdefault(norm(entry['title']), key)
    sources['Consensus'] = len(cons)
    identified = sum(sources.values())
    summary = {'subject': subject, 'identified_by_source': sources, 'identified_total': identified, 'after_deduplication': len(pool),
               'duplicates_removed': identified - len(pool), 'europepmc_not_in_pubmed_set': epmc_new, 'consensus_not_matched': cons_new}
    save(base/'screening/records.json', {'summary': summary, 'records': list(pool.values())})
    with open(base/'screening/titles.tsv', 'w') as out:
        out.write('id\tyear\ttype\ttitle\tdetail\n')
        for item in pool.values():
            out.write('\t'.join(str(item.get(k, '')).replace('\t', ' ').replace('\n', ' ') for k in ('id', 'year', 'type', 'title', 'detail')) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def decisions(base, stage):
    a, b = load(base/f'screening/{stage}-A.json'), load(base/f'screening/{stage}-B.json')
    return a, b


def kappa(a, b, ids):
    """Cohen's kappa over the decision categories (include / exclude / not_retrieved)."""
    n = len(ids)
    agree = sum(a[i]['decision'] == b[i]['decision'] for i in ids)
    categories = {a[i]['decision'] for i in ids} | {b[i]['decision'] for i in ids}
    expected = sum((sum(a[i]['decision'] == c for i in ids) / n) * (sum(b[i]['decision'] == c for i in ids) / n) for c in categories)
    return agree / n, (agree / n - expected) / (1 - expected) if expected < 1 else 1.0


def stage_ids(base, stage):
    if stage == 'titles':
        return [r['id'] for r in load(base/'screening/records.json')['records']]
    if stage == 'fulltext':
        # Records added by the second retrieval round from the abstract stage were not assessed in round 1.
        return [i for i, v in load(base/'screening/eligibility/index.json').items() if v.get('origin') != 'round2-abstract']
    return list(load(base/'screening/abstracts.json'))


def resolved(base, stage):
    a, b = decisions(base, stage)
    arbitration = load(base/f'screening/{stage}-arbitration.json') if (base/f'screening/{stage}-arbitration.json').exists() else {}
    final = {}
    for i in stage_ids(base, stage):
        if a[i]['decision'] == b[i]['decision']:
            final[i] = {'decision': a[i]['decision'], 'code': a[i].get('code') or b[i].get('code'), 'by': _('agreement')}
        else:
            final[i] = {**arbitration[i], 'by': _('arbitration')}
    return final


def agreement(subject, stage):
    base = folder(subject)
    a, b = decisions(base, stage)
    ids = stage_ids(base, stage)
    missing = [i for i in ids if i not in a or i not in b]
    if missing:
        raise SystemExit(f'{len(missing)} missing decisions, e.g. {missing[:5]}')
    observed, k = kappa(a, b, ids)
    records = {r['id']: r for r in load(base/'screening/records.json')['records']}
    abstracts = load(base/'screening/abstracts.json') if stage != 'titles' else {}
    if stage == 'fulltext':
        records.update({i: {'title': v['title']} for i, v in load(base/'screening/eligibility/index.json').items()})
    with open(base/f'screening/{stage}-disagreements.tsv', 'w') as out:
        out.write('id\tA\tB\ttitle\tabstract\n')
        for i in ids:
            if a[i]['decision'] != b[i]['decision']:
                text = abstracts.get(i, {}).get('abstract', records[i].get('detail', ''))
                out.write('\t'.join([i, f"{a[i]['decision']} {a[i].get('code', '')}", f"{b[i]['decision']} {b[i].get('code', '')}", records[i]['title'], text.replace('\t', ' ').replace('\n', ' ')]) + '\n')
    stats = {'stage': stage, 'n': len(ids), 'agreement': round(observed, 4), 'kappa': round(k, 3),
             'disagreements': sum(a[i]['decision'] != b[i]['decision'] for i in ids),
             'A_include': sum(a[i]['decision'] == 'include' for i in ids), 'B_include': sum(b[i]['decision'] == 'include' for i in ids)}
    save(base/f'screening/{stage}-agreement.json', stats)
    print(json.dumps(stats, ensure_ascii=False))


def efetch_abstracts(pmids):
    out = {}
    for offset in range(0, len(pmids), 150):
        batch = pmids[offset:offset + 150]
        url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?' + urllib.parse.urlencode({'db': 'pubmed', 'id': ','.join(batch), 'retmode': 'xml'})
        for attempt in range(4):
            time.sleep(0.4 + 2 * attempt)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'EMET-Evidence/0.8'}), timeout=120) as response:
                    root = ET.fromstring(response.read())
                break
            except Exception:
                if attempt == 3:
                    raise
        for article in root.iter('PubmedArticle'):
            pmid = article.findtext('.//PMID')
            text = ' '.join(((a.get('Label') + ': ') if a.get('Label') else '') + ''.join(a.itertext()) for a in article.iter('AbstractText'))
            out[pmid] = text
    return out


def abstracts(subject, stage):
    base = folder(subject)
    kept = [i for i, d in resolved(base, stage).items() if d['decision'] == 'include']
    records = {r['id']: r for r in load(base/'screening/records.json')['records']}
    path = base/'screening/abstracts.json'
    cache = load(path) if path.exists() else {}
    pmids = [i for i in kept if i.isdigit() and i not in cache]
    fetched = efetch_abstracts(pmids) if pmids else {}
    for i in kept:
        if i in cache:
            continue
        r = records[i]
        text = fetched.get(i) if i.isdigit() else ''
        if i.startswith('EPMC:'):
            src, ident = r['europepmc']['source'], r['europepmc']['id']
            url = f'https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:{ident}%20AND%20SRC:{src}&resultType=core&format=json'
            result = [{}]
            for attempt in range(5):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'EMET-Evidence/0.8'}), timeout=90) as response:
                        result = json.loads(response.read()).get('resultList', {}).get('result', [{}])
                    break
                except Exception:
                    time.sleep(3 * (attempt + 1))
            text = (result[0] if result else {}).get('abstractText', '')
            time.sleep(0.3)
        if i.startswith('NCT'):
            text = r.get('detail', '')
        cache[i] = {'title': r['title'], 'year': r['year'], 'type': r.get('type', ''), 'abstract': re.sub(r'<[^>]+>', '', text or '')}
    cache = {i: cache[i] for i in kept}
    save(path, cache)
    with open(base/'screening/abstracts.tsv', 'w') as out:
        out.write('id\tyear\ttype\ttitle\tabstract\n')
        for i, item in cache.items():
            out.write('\t'.join(str(item[k]).replace('\t', ' ').replace('\n', ' ') for k in ('year', 'type', 'title', 'abstract')).join([i + '\t', '']) + '\n')
    print(f'{len(cache)} abstracts ({sum(1 for v in cache.values() if not v["abstract"])} without abstract) -> {path.relative_to(ROOT)}')


def final(subject):
    base = folder(subject)
    summary = load(base/'screening/records.json')['summary']
    titles, abstracts_stage, full = resolved(base, 'titles'), resolved(base, 'abstracts'), resolved(base, 'fulltext')
    # Second retrieval round (protocol deviation): its arbitrated decisions replace the first-round ones.
    round2 = load(base/'screening/round2-final.json') if (base/'screening/round2-final.json').exists() else {}
    for i, d in round2.items():
        decision = {k: d.get(k) for k in ('decision', 'code', 'basis', 'reason')} | {'by': _('round 2, {by}', by=d.get('by', _('arbitration')))}
        if i in full:
            full[i] = decision
        elif d['decision'] != 'exclude':
            abstracts_stage[i] = {'decision': 'include', 'code': None, 'by': decision['by']}
            full[i] = decision
        else:
            assert d['decision'] == 'exclude', f'{i}: inclusion at the abstract stage to be passed on to eligibility'
            abstracts_stage[i] = decision
    protocol = load(ROOT/'data/protocols'/f'{subject}.json')
    # Duplicates detected after eligibility (protocol deviation): excluded as E5, the kept record is named.
    for dev in protocol['deviations']:
        for i, kept in dev.get('late_duplicates', {}).items():
            assert full.get(i, {}).get('decision') == 'include' and full.get(kept, {}).get('decision') == 'include', i
            full[i] = {'decision': 'exclude', 'code': 'E5', 'basis': full[i].get('basis'),
                       'reason': _('Duplicate of {kept}, found after extraction', kept=kept), 'by': _('correction after extraction')}
    # Studies excluded after extraction (protocol deviation): no comparison usable for the question.
    for dev in protocol['deviations']:
        for i, rule in dev.get('late_exclusions', {}).items():
            assert full.get(i, {}).get('decision') == 'include', i
            full[i] = {'decision': 'exclude', 'code': rule['code'], 'basis': full[i].get('basis'), 'reason': rule['reason'], 'by': _('correction after extraction')}
    remap = {d['from']: d for d in protocol['deviations'] if d.get('from')}

    def code(i, d):
        rule = remap.get(d.get('code'))
        return rule['to'] if rule and i in rule['ids'] else d.get('code')

    def by_code(stage):
        counts = {}
        for i, d in stage.items():
            if d['decision'] == 'exclude':
                counts[code(i, d)] = counts.get(code(i, d), 0) + 1
        return dict(sorted(counts.items()))
    excluded_codes = by_code(abstracts_stage)
    index = load(base/'screening/eligibility/index.json')
    result = {'summary': summary,
              'titles': {'screened': len(titles), 'excluded': sum(d['decision'] == 'exclude' for d in titles.values()), **load(base/'screening/titles-agreement.json')},
              'abstracts': {'assessed': len(abstracts_stage), 'excluded': sum(d['decision'] == 'exclude' for d in abstracts_stage.values()),
                            'excluded_by_code': dict(sorted(excluded_codes.items())), **load(base/'screening/abstracts-agreement.json')},
              'fulltext': {'assessed': len(full), 'fulltext': sum(index[i]['access'] == 'texte intégral' for i in full),  # access level value (fulltext_stage)
                           'other_methods': sorted(i for i, v in index.items() if v.get('origin') and v['origin'] != 'round2-abstract'),
                           'not_retrieved': sum(d['decision'] == 'not_retrieved' for d in full.values()),
                           'excluded': sum(d['decision'] == 'exclude' for d in full.values()), 'excluded_by_code': by_code(full),
                           **load(base/'screening/fulltext-agreement.json')},
              'codes': {**protocol['exclusion_codes'], **{d['to']: d['label'] for d in remap.values()}},
              'included': sorted(i for i, d in full.items() if d['decision'] == 'include'),
              'not_retrieved': sorted(i for i, d in full.items() if d['decision'] == 'not_retrieved'),
              'decisions': {'titles': titles, 'abstracts': abstracts_stage, 'fulltext': full}}
    save(base/'screening/final.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'decisions'}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    command, subject = sys.argv[1], sys.argv[2]
    {'records': lambda: records(subject), 'abstracts': lambda: abstracts(subject, sys.argv[3]),
     'agreement': lambda: agreement(subject, sys.argv[3]), 'final': lambda: final(subject)}[command]()
