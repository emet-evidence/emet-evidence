#!/usr/bin/env python3
"""Unpaywall connector: locates open-access versions of the included studies read without full text.

The Unpaywall API requires a contact e-mail address: environment variable UNPAYWALL_EMAIL, or a line
`UNPAYWALL_EMAIL=...` in `.env.local` (not versioned, never exported). Raw responses are cached under
screening/eligibility/raw/unpaywall-<doi>.json. Writes screening/unpaywall.json: for each study, DOI, open-access
status, best location (PDF or page), licence, version (published, accepted, submitted).

  python3 -m emet.unpaywall <topic>

Does not download the PDFs: retrieving the text and re-reading it are separate steps (full text = new extraction
of the fields concerned, never a mere substitution).
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

from emet.workspace import ROOT, output_path, search_folder


def email():
    if os.environ.get('UNPAYWALL_EMAIL'):
        return os.environ['UNPAYWALL_EMAIL']
    env = ROOT / '.env.local'
    m = re.search(r'^UNPAYWALL_EMAIL=(\S+)', env.read_text(), re.M) if env.exists() else None
    if not m:
        sys.exit('UNPAYWALL_EMAIL missing (environment variable or .env.local)')
    return m.group(1)


def query(doi, raw, contact):
    path = raw / f'unpaywall-{re.sub(r"[^A-Za-z0-9]", "_", doi)}.json'
    if path.exists():
        return json.loads(path.read_text())
    url = f'https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?' + urllib.parse.urlencode({'email': contact})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'emet-evidence/0.1'}), timeout=30) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        data = {'error': e.code}
    path.write_text(json.dumps(data, ensure_ascii=False))
    time.sleep(0.2)
    return data


def main(subject):
    q = json.loads(output_path(subject, 'data').read_text())
    base = search_folder(subject) / 'screening'
    raw = base / 'eligibility/raw'
    contact = email()
    out = []
    for R, s in q['studies'].items():
        if s['access'] != 'résumé':  # access level value of the page data (abstract only)
            continue
        art = ROOT / f'data/articles/{s["pmid"]}.json'
        doi = json.loads(art.read_text())['identifiers'].get('doi') if art.exists() else None
        item = {'reference': R, 'pmid': s['pmid'], 'label': s['label'], 'doi': doi, 'is_oa': False}
        if doi:
            d = query(doi, raw, contact)
            best = d.get('best_oa_location') or {}
            item.update({'is_oa': bool(d.get('is_oa')), 'oa_status': d.get('oa_status'), 'url_for_pdf': best.get('url_for_pdf'),
                         'url': best.get('url'), 'license': best.get('license'), 'version': best.get('version'), 'host_type': best.get('host_type'),
                         'error': d.get('error')})
        out.append(item)
    (base / 'unpaywall.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    oa = [x for x in out if x['is_oa']]
    print(f'{subject}: {len(out)} studies read on abstract, {sum(1 for x in out if x["doi"])} with DOI, {len(oa)} open access '
          f'({sum(1 for x in oa if x.get("url_for_pdf"))} with PDF) -> unpaywall.json')
    for x in oa:
        print(f"  {x['reference']} {x['label']} | {x['oa_status']} {x['version']} {x['license']} | {x['url_for_pdf'] or x['url']}")


if __name__ == '__main__':
    main(sys.argv[1])
