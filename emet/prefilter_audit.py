#!/usr/bin/env python3
"""Sensitivity audit of the scripted title pre-filter (EMET v0.8, critical defect 1).

For every record excluded by `emet/prefilter.py`, fetch its abstract (PubMed EFetch, cached in
`screening/prefilter-audit-abstracts.json`) and apply the same subject rule to title + abstract.
Records whose abstract matches are "rescued": they must be screened by the agents before the
pre-filter can be said not to have lost eligible studies. Output: `screening/prefilter-audit.json`.

  python3 -m emet.prefilter_audit <topic>
"""
import re, sys
from pathlib import Path
from emet.screening import folder, load, save, efetch_abstracts  # noqa: E402
from emet.prefilter import compile_rules  # noqa: E402
from emet.workspace import topic  # noqa: E402


def matches(subject, text):
    """The topic's broadest title rule (last entry of `title_rules`), applied to title + abstract."""
    cfg = topic(subject)['prefilter']
    _, match = compile_rules(cfg)
    return match(cfg['title_rules'][-1]['rule'], text)


def fetch_titles(pmids):
    """PubMed titles (EFetch) of the records of the citation iterations, absent from records.json."""
    import urllib.parse, urllib.request, time, xml.etree.ElementTree as ET
    out = {}
    for offset in range(0, len(pmids), 150):
        url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?' + urllib.parse.urlencode({'db': 'pubmed', 'id': ','.join(pmids[offset:offset + 150]), 'retmode': 'xml'})
        time.sleep(0.4)
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'EMET-Evidence/0.8'}), timeout=120) as response:
            root = ET.fromstring(response.read())
        for article in root.iter('PubmedArticle'):
            out[article.findtext('.//PMID')] = {'title': ''.join(article.find('.//ArticleTitle').itertext()) if article.find('.//ArticleTitle') is not None else '',
                                                'year': article.findtext('.//PubDate/Year') or article.findtext('.//PubDate/MedlineDate') or ''}
    return out


def main(subject):
    base = folder(subject) / 'screening'
    excluded = dict(load(base / 'titles-prefilter.json'))
    records = {r['id']: r for r in load(base / 'records.json')['records']}
    # "Other methods" branch: citation iterations (snowN-records.json), same pre-filter.
    snow_ids = []
    for path in sorted(base.glob('snow*-records.json')):
        branch = load(path)
        for rid, d in branch['prefilter'].items():
            excluded[rid] = {**d, 'branch': path.name.split('-')[0]}
            snow_ids.append(rid)
    titles_path = base / 'snow-titles.json'
    snow_titles = load(titles_path) if titles_path.exists() else {}
    missing = [i for i in snow_ids if i not in snow_titles and i.isdigit()]
    if missing:
        snow_titles.update(fetch_titles(missing))
        save(titles_path, snow_titles)
    for i in snow_ids:
        records.setdefault(i, {'id': i, **snow_titles.get(i, {'title': '', 'year': ''})})
    cache_path = base / 'prefilter-audit-abstracts.json'
    cache = load(cache_path) if cache_path.exists() else {}
    todo = [i for i in excluded if i.isdigit() and i not in cache]
    if todo:
        cache.update(efetch_abstracts(todo))
        for i in todo:
            cache.setdefault(i, '')
        save(cache_path, cache)
    rescued, no_abstract, not_pubmed = [], [], []
    for i in excluded:
        if not i.isdigit():
            not_pubmed.append(i)
            continue
        abstract = re.sub(r'<[^>]+>', '', cache.get(i) or '')
        if not abstract:
            no_abstract.append(i)
        elif matches(subject, (records[i]['title'] or '') + ' ' + abstract):
            rescued.append(i)
    report = {'subject': subject, 'excluded_by_title_prefilter': len(excluded),
              'with_abstract': len(excluded) - len(no_abstract) - len(not_pubmed),
              'no_abstract': len(no_abstract), 'not_pubmed': len(not_pubmed),
              'rescued_by_abstract_rule': len(rescued), 'rescued_ids': rescued,
              'no_abstract_ids': no_abstract, 'not_pubmed_ids': not_pubmed}
    save(base / 'prefilter-audit.json', report)
    print({k: v for k, v in report.items() if not k.endswith('_ids')})


if __name__ == '__main__':
    main(sys.argv[1])
