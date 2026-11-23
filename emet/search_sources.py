#!/usr/bin/env python3
"""Complementary sources for a question page: Europe PMC and ClinicalTrials.gov.

Raw responses (every page) are archived under data/searches/<folder>/ before use; existing files are
reused (cache-first). Pass --refresh to query again.

  python3 -m emet.search_sources europepmc <folder> <key> "<query>"
  python3 -m emet.search_sources ctgov <folder> <key> "<term>"
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import time
import urllib.parse
import urllib.request

from emet.workspace import ROOT
EPMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
CTGOV = 'https://clinicaltrials.gov/api/v2/studies'


def get(url):
    for attempt in range(6):
        time.sleep(0.5 + 3 * attempt)
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'EMET-Evidence/0.8'})
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read())
        except Exception:
            if attempt == 5:
                raise


def europepmc(query):
    pages, cursor = [], '*'
    while True:
        url = EPMC + '?' + urllib.parse.urlencode({'query': query, 'format': 'json', 'resultType': 'lite', 'pageSize': 1000, 'cursorMark': cursor})
        response = get(url)
        pages.append({'url': url, 'response': response})
        records = response.get('resultList', {}).get('result', [])
        if not records or response.get('nextCursorMark') in (None, cursor):
            return pages, int(response.get('hitCount', 0))
        cursor = response['nextCursorMark']


def ctgov(term):
    pages, token = [], None
    while True:
        params = {'query.term': term, 'pageSize': 1000, 'countTotal': 'true'}
        if token:
            params['pageToken'] = token
        url = CTGOV + '?' + urllib.parse.urlencode(params)
        response = get(url)
        pages.append({'url': url, 'response': response})
        token = response.get('nextPageToken')
        if not token:
            return pages, int(pages[0]['response'].get('totalCount', 0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', choices=['europepmc', 'ctgov'])
    parser.add_argument('folder')
    parser.add_argument('key')
    parser.add_argument('query')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    path = ROOT/'data/searches'/args.folder/f'{args.source}-{args.key}.json'
    if path.exists() and not args.refresh:
        value = json.loads(path.read_text())
    else:
        pages, count = (europepmc if args.source == 'europepmc' else ctgov)(args.query)
        value = {'source': args.source, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'query': args.query, 'count': count, 'pages': pages}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + '\n')
    records = sum(len(p['response'].get('resultList', {}).get('result', p['response'].get('studies', []))) for p in value['pages'])
    print(f'{path.relative_to(ROOT)}: {value["count"]} results announced, {records} archived')


if __name__ == '__main__':
    main()
