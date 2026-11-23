#!/usr/bin/env python3
"""Full-text eligibility stage: retrieve open full texts (Europe PMC) for records kept after abstracts.

  python3 -m emet.fulltext_stage <subject>

Writes screening/eligibility/<id>.txt (title, abstract, methods excerpt, full text when open access) and
screening/eligibility/index.json (access level per record). Raw Europe PMC XML is cached in
screening/eligibility/raw/ (cache-first). No paywall circumvention: closed articles stay at abstract level.
"""
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from emet.screening import folder, load, resolved, save  # noqa: E402

from emet.workspace import ROOT
UA = {'User-Agent': 'EMET-Evidence/0.8'}


def fetch(url, binary=False):
    for attempt in range(2):
        time.sleep(0.3 + attempt)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as response:
                data = response.read()
                return data if binary else json.loads(data)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if attempt == 1:
                return None
        except Exception:
            if attempt == 1:
                return None


def core(query):
    url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urllib.parse.urlencode({'query': query, 'resultType': 'core', 'format': 'json'})
    result = fetch(url) or {}
    items = result.get('resultList', {}).get('result', [])
    return items[0] if items else {}


def sections(xml):
    root = ET.fromstring(xml)
    body = root.find('.//body')
    if body is None:
        return '', ''
    parts, methods = [], []
    for sec in body.iter('sec'):
        if sec in list(body):
            title = (sec.findtext('title') or '').strip()
            text = re.sub(r'\s+', ' ', ' '.join(sec.itertext())).strip()
            parts.append(f'## {title}\n{text}')
            if re.search(r'method|material|patient|subject|design', title, re.I):
                methods.append(text)
    if not parts:
        parts = [re.sub(r'\s+', ' ', ' '.join(body.itertext()))]
    tables = []
    for wrap in root.iter('table-wrap'):
        label = wrap.findtext('label') or ''
        caption = re.sub(r'\s+', ' ', ' '.join(wrap.find('caption').itertext())) if wrap.find('caption') is not None else ''
        rows = [' | '.join(re.sub(r'\s+', ' ', ''.join(c.itertext())).strip() for c in tr) for tr in wrap.iter('tr')]
        tables.append(f'### {label} {caption}\n' + '\n'.join(rows))
    return '\n\n'.join(parts + tables), ' '.join(methods)


def main(subject):
    base = folder(subject)
    out = base/'screening/eligibility'
    (out/'raw').mkdir(parents=True, exist_ok=True)
    kept = [i for i, d in resolved(base, 'abstracts').items() if d['decision'] == 'include']
    abstracts = load(base/'screening/abstracts.json')
    records = {r['id']: r for r in load(base/'screening/records.json')['records']}
    index = {}
    for i in kept:
        meta_path = out/'raw'/f'{i.replace(":", "_")}.meta.json'
        if meta_path.exists():
            meta = load(meta_path)
        else:
            if i.isdigit():
                meta = core(f'EXT_ID:{i} AND SRC:MED')
            elif i.startswith('EPMC:'):
                src, ident = records[i]['europepmc']['source'], records[i]['europepmc']['id']
                meta = core(f'EXT_ID:{ident} AND SRC:{src}')
            elif i.startswith('CONS:'):
                title = re.sub(r'["\\]', ' ', abstracts[i]['title']).strip().rstrip('.')
                meta = core(f'TITLE:"{title}"')
                if meta and re.sub(r'[^a-z0-9]', '', meta.get('title', '').lower())[:80] != re.sub(r'[^a-z0-9]', '', title.lower())[:80]:
                    meta = {}
            else:
                meta = {}
            save(meta_path, meta)
        pmcid = meta.get('pmcid')
        # Access levels ('résumé', 'titre seulement', 'fiche du registre', 'texte intégral') and the field labels of the
        # eligibility file (TITRE, ANNÉE, ACCÈS, RÉSUMÉ…) are data values: matched by retrieval_round2, screening,
        # unpaywall and migrate_review, and present in the archived eligibility files.
        text, methods, access = '', '', 'résumé'
        if not abstracts[i]['abstract'] and not meta.get('abstractText'):
            access = 'titre seulement'
        if i.startswith('NCT'):
            access = 'fiche du registre'
        local = ROOT/'data/fulltext'/f'{pmcid}.json' if pmcid else None
        xml = None
        if local and local.exists():
            xml = load(local)['raw_xml']
        elif pmcid and meta.get('isOpenAccess') == 'Y' or (pmcid and meta.get('inEPMC') == 'Y'):
            raw = out/'raw'/f'{pmcid}.xml'
            if not raw.exists():
                data = fetch(f'https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML', binary=True)
                raw.write_bytes(data or b'')
            xml = raw.read_text() or None
        if xml:
            try:
                text, methods = sections(xml)
                access = 'texte intégral'
            except ET.ParseError:
                pass
        abstract = abstracts[i]['abstract'] or re.sub(r'<[^>]+>', '', meta.get('abstractText', ''))
        name = i.replace(':', '_')
        (out/f'{name}.txt').write_text(f'ID: {i}\nTITRE: {abstracts[i]["title"]}\nANNÉE: {abstracts[i]["year"]}\nTYPE: {abstracts[i]["type"]}\nACCÈS: {access}\nPMCID: {pmcid or ""}\nDOI: {meta.get("doi", records[i].get("doi", ""))}\n\nRÉSUMÉ:\n{abstract}\n\nMÉTHODES (extrait):\n{methods[:8000]}\n\nTEXTE INTÉGRAL:\n{text}\n')
        index[i] = {'file': f'{name}.txt', 'access': access, 'pmcid': pmcid, 'doi': meta.get('doi', ''), 'title': abstracts[i]['title'], 'year': abstracts[i]['year']}
    save(out/'index.json', index)
    counts = {}
    for v in index.values():
        counts[v['access']] = counts.get(v['access'], 0) + 1
    print(subject, len(index), counts)


if __name__ == '__main__':
    main(sys.argv[1])
