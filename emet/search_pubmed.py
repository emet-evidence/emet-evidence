#!/usr/bin/env python3
"""Reproducible PubMed searches for a question page: ESearch, ELink snowballing, ESummary titles.

Every raw response is archived under data/searches/<folder>/ before use. Existing files are reused
(cache-first); pass --refresh to query again.

  python3 -m emet.search_pubmed esearch <folder> <key> "<query>"
  python3 -m emet.search_pubmed elink <folder> <file> <pmid> [<pmid> ...]
  python3 -m emet.search_pubmed titles <folder> <pmid> [<pmid> ...]   # ESummary, cached in titles.json
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import time
import urllib.parse
import urllib.request

from emet.workspace import ROOT
EUTILS = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'


def now():
    return datetime.now(timezone.utc).isoformat()


def get(endpoint, params):
    url = EUTILS + endpoint + '?' + urllib.parse.urlencode(params)
    for attempt in range(4):
        time.sleep(0.4 + 2 * attempt)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'EMET-Evidence/0.8'}), timeout=90) as response:
                return url, json.loads(response.read())
        except Exception:
            if attempt == 3:
                raise


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + '\n')


def esearch(folder, key, query, refresh):
    path = folder / f'{key}.json'
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    url, response = get('esearch.fcgi', {'db': 'pubmed', 'term': query, 'retmode': 'json', 'retmax': 9999})
    result = response['esearchresult']
    if int(result['count']) > len(result['idlist']):
        raise RuntimeError('Pagination required')
    value = {'retrieved_at': now(), 'query': query, 'url': url, **response}
    save(path, value)
    return value


def elink(folder, name, pmids, refresh):
    path = folder / f'{name}.json'
    links = json.loads(path.read_text()) if path.exists() else {}
    for pmid in pmids:
        if pmid in links and not refresh:
            continue
        _, response = get('elink.fcgi', {'dbfrom': 'pubmed', 'db': 'pubmed', 'id': pmid, 'retmode': 'json',
                                         'linkname': 'pubmed_pubmed_refs,pubmed_pubmed_citedin', 'cmd': 'neighbor'})
        found = {'pubmed_pubmed_refs': [], 'pubmed_pubmed_citedin': [], 'retrieved_at': now()}
        for linkset in response.get('linksets', []):
            for db in linkset.get('linksetdbs', []):
                if db['linkname'] in found:
                    found[db['linkname']] = db['links']
        links[pmid] = found
        save(path, links)
    return links


def titles(folder, pmids):
    path = folder / 'titles.json'
    cache = json.loads(path.read_text()) if path.exists() else {}
    missing = [pmid for pmid in dict.fromkeys(pmids) if pmid not in cache]
    for offset in range(0, len(missing), 200):
        batch = missing[offset:offset + 200]
        _, response = get('esummary.fcgi', {'db': 'pubmed', 'id': ','.join(batch), 'retmode': 'json'})
        for pmid in batch:
            item = response.get('result', {}).get(pmid, {})
            cache[pmid] = {'title': item.get('title', ''), 'year': item.get('pubdate', '')[:4],
                           'journal': item.get('source', ''), 'pubtype': item.get('pubtype', []),
                           'first_author': (item.get('authors') or [{}])[0].get('name', ''), 'retrieved_at': now()}
        save(path, cache)
    return cache


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['esearch', 'elink', 'titles'])
    parser.add_argument('folder')
    parser.add_argument('rest', nargs='+')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    folder = ROOT / 'data' / 'searches' / args.folder
    if args.command == 'esearch':
        value = esearch(folder, args.rest[0], args.rest[1], args.refresh)
        print(args.rest[0], value['esearchresult']['count'])
    elif args.command == 'elink':
        links = elink(folder, args.rest[0], args.rest[1:], args.refresh)
        print(args.rest[0], len(links), 'seeds')
    else:
        print(len(titles(folder, args.rest)), 'titles cached')


if __name__ == '__main__':
    main()
