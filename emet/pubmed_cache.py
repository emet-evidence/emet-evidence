"""Local cache of PubMed records (EFetch) and Europe PMC open full texts, keyed by identifier.

Records are stored as data/articles/<PMID>.json (parsed fields, raw XML and its SHA-256); raw EFetch responses as
data/searches/efetch-<hash>.json; full texts as data/fulltext/<PMCID>.json. Failed full-text downloads are logged in
data/collection-errors.json and not retried unless refresh=True. The cache is the source of truth: once a record is
stored it is reused, and offline=True never touches the network.

  python3 -m emet.pubmed_cache <PMID> [<PMID> ...] [--fulltext] [--offline | --refresh]
  python3 -m emet.pubmed_cache --manifest data/sources-manifest.json [--fulltext]   # re-download a public package's sources
"""
import argparse, hashlib, json, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from emet import __version__
from emet.workspace import ROOT

DATA = ROOT / 'data'
EUTILS = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
USER_AGENT = f'EMET-Evidence/{__version__}'
ACCESS_NOTE = 'Record and abstract; a PMCID does not imply that the full text was read.'
FULLTEXT_NOTE = 'Archived text; archiving is not a validated full-text reading.'


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def request(url, user_agent=USER_AGENT):
    for attempt in range(3):
        time.sleep(0.4 + attempt)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': user_agent}), timeout=60) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise


def text(element):
    return ''.join(element.itertext()).strip() if element is not None else ''


def record(article, url, purpose='cache', access_note=ACCESS_NOTE):
    """Parsed PubMed record (PubmedArticle or PubmedBookArticle element), with its raw XML and hash."""
    citation = article.find('MedlineCitation')
    is_book = citation is None
    if is_book:
        citation = article.find('BookDocument')
    journal_article = citation if is_book else citation.find('Article')
    identifiers = {item.get('IdType'): text(item) for item in article.findall('./PubmedData/ArticleIdList/ArticleId')}
    raw_xml = ET.tostring(article, encoding='unicode')
    return {'schema_version': 1, 'pmid': text(citation.find('PMID')), 'retrieved_at': now(),
            'provenance': {'provider': 'NCBI PubMed EFetch', 'url': url, 'purpose': purpose},
            'title': text(journal_article.find('ArticleTitle')),
            'authors': [{'family': text(author.find('LastName')), 'given': text(author.find('ForeName')),
                         'collective': text(author.find('CollectiveName'))} for author in journal_article.findall('./AuthorList/Author')],
            'journal': text(journal_article.find('./Book/BookTitle' if is_book else './Journal/Title')),
            'record_type': article.tag,
            'publication_date': {child.tag: text(child) for child in journal_article.findall('./Book/PubDate/*' if is_book else './Journal/JournalIssue/PubDate/*')},
            'electronic_dates': [{child.tag: text(child) for child in date} for date in journal_article.findall('ArticleDate')],
            'abstract': [{'label': part.get('Label'), 'text': text(part)} for part in journal_article.findall('./Abstract/AbstractText')],
            'publication_types': [text(item) for item in journal_article.findall('./PublicationTypeList/PublicationType')],
            'identifiers': identifiers,
            'comments_corrections': [ET.tostring(item, encoding='unicode') for item in citation.findall('./CommentsCorrectionsList/CommentsCorrections')],
            'raw_record_xml': raw_xml, 'raw_record_sha256': hashlib.sha256(raw_xml.encode()).hexdigest(),
            'access_note': access_note}


def article_path(pmid, data=None):
    return (data or DATA) / 'articles' / f'{pmid}.json'


def restore_from_batches(data=None, **record_kw):
    """Rebuild missing data/articles/*.json from archived EFetch responses, without network."""
    data = data or DATA
    for batch_path in sorted((data / 'searches').glob('efetch-*.json')):
        batch = json.loads(batch_path.read_text())
        for article in ET.fromstring(batch['raw_response_xml']):
            if article.tag not in {'PubmedArticle', 'PubmedBookArticle'}:
                continue
            value = record(article, batch['url'], **record_kw)
            path = article_path(value['pmid'], data)
            if not path.exists():
                value['retrieved_at'] = batch['retrieved_at']
                save(path, value)


def fetch_records(pmids, refresh=False, offline=False, data=None, user_agent=USER_AGENT, **record_kw):
    """Make sure every PMID has a cached record. Returns the PMIDs downloaded; raises if some stay missing."""
    data = data or DATA
    pmids = sorted({p for p in pmids if str(p).isdigit()}, key=int)
    if not refresh:
        restore_from_batches(data, **record_kw)
    missing = [p for p in pmids if refresh or not article_path(p, data).exists()]
    if offline and missing:
        raise RuntimeError(f'records missing offline: {missing}')
    for offset in range(0, len(missing), 50):
        batch = missing[offset:offset + 50]
        url = EUTILS + 'efetch.fcgi?' + urllib.parse.urlencode({'db': 'pubmed', 'id': ','.join(batch), 'retmode': 'xml'})
        raw = request(url, user_agent)
        batch_id = hashlib.sha256(','.join(batch).encode()).hexdigest()[:12]
        save(data / 'searches' / f'efetch-{batch_id}.json', {'retrieved_at': now(), 'requested_pmids': batch, 'url': url,
             'raw_response_xml': raw.decode(), 'raw_response_sha256': hashlib.sha256(raw).hexdigest()})
        for article in ET.fromstring(raw):
            if article.tag in {'PubmedArticle', 'PubmedBookArticle'}:
                value = record(article, url, **record_kw)
                save(article_path(value['pmid'], data), value)
    absent = [p for p in pmids if not article_path(p, data).exists()]
    if absent:
        raise RuntimeError(f'EFetch omitted records: {absent}')
    return missing


def fetch_fulltexts(pmids, refresh=False, offline=False, data=None, user_agent=USER_AGENT, review_status=FULLTEXT_NOTE):
    """Archive the Europe PMC full text of records that have a PMCID. Failures are logged, not retried unless refresh.
    Returns the updated error list (also saved unless offline)."""
    data = data or DATA
    errors_path = data / 'collection-errors.json'
    errors = json.loads(errors_path.read_text()) if errors_path.exists() else []
    failed = {error['pmcid'] for error in errors}
    for pmid in pmids:
        if not str(pmid).isdigit():
            continue
        pmcid = json.loads(article_path(pmid, data).read_text())['identifiers'].get('pmc')
        if not pmcid or offline or ((data / 'fulltext' / f'{pmcid}.json').exists() and not refresh):
            continue
        if pmcid in failed and not refresh:
            continue
        url = f'https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML'
        errors = [error for error in errors if error['pmcid'] != pmcid]
        try:
            raw = request(url, user_agent)
            ET.fromstring(raw)
            save(data / 'fulltext' / f'{pmcid}.json', {'schema_version': 1, 'pmid': pmid, 'pmcid': pmcid, 'retrieved_at': now(), 'url': url,
                 'raw_xml': raw.decode(), 'sha256': hashlib.sha256(raw).hexdigest(), 'review_status': review_status})
        except Exception as error:
            errors.append({'pmid': pmid, 'pmcid': pmcid, 'url': url, 'error': str(error), 'at': now()})
    if not offline:
        save(errors_path, errors)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('pmids', nargs='*')
    parser.add_argument('--manifest', help='sources manifest of a public review package (items with pmid and sha256)')
    parser.add_argument('--fulltext', action='store_true', help='also archive Europe PMC open full texts')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    if args.offline and args.refresh:
        parser.error('--offline and --refresh are incompatible')
    pmids, expected = list(args.pmids), {}
    if args.manifest:
        for item in json.loads((ROOT / args.manifest).read_text())['items']:
            if item.get('pmid'):
                pmids.append(item['pmid'])
                if item.get('kind') == 'pubmed_record' and item.get('sha256'):
                    expected[item['pmid']] = item['sha256']
    downloaded = fetch_records(pmids, refresh=args.refresh, offline=args.offline)
    errors = fetch_fulltexts(pmids, refresh=args.refresh, offline=args.offline) if args.fulltext else []
    changed = [p for p, h in expected.items() if json.loads(article_path(p).read_text()).get('raw_record_sha256') != h]
    print(f'{len(set(pmids))} records cached; {len(downloaded)} downloaded; {len(errors)} full-text failures logged'
          + (f'; {len(changed)} record(s) differ from the manifest hash: {changed[:10]}' if changed else ''))


if __name__ == '__main__':
    main()
