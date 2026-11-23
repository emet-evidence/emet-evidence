"""Parsing of PubMed records and offline behaviour of the cache (no network)."""
import tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tests.helpers import ROOT  # noqa: F401  (adds the engine to sys.path)
from emet import pubmed_cache

XML = '''<PubmedArticle><MedlineCitation><PMID>123</PMID><Article><Journal><Title>J Test</Title>
<JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal><ArticleTitle>A fictitious trial.</ArticleTitle>
<Abstract><AbstractText Label="METHODS">Randomised.</AbstractText></Abstract>
<AuthorList><Author><LastName>Doe</LastName><ForeName>Jane</ForeName></Author></AuthorList>
<PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList></Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="pmc">PMC1</ArticleId><ArticleId IdType="doi">10.1/x</ArticleId></ArticleIdList></PubmedData></PubmedArticle>'''


class Record(unittest.TestCase):
    def test_fields_and_hash(self):
        r = pubmed_cache.record(ET.fromstring(XML), 'https://example.org')
        self.assertEqual((r['pmid'], r['title'], r['journal']), ('123', 'A fictitious trial.', 'J Test'))
        self.assertEqual(r['authors'][0]['family'], 'Doe')
        self.assertEqual(r['abstract'], [{'label': 'METHODS', 'text': 'Randomised.'}])
        self.assertEqual(r['identifiers'], {'pmc': 'PMC1', 'doi': '10.1/x'})
        self.assertEqual(len(r['raw_record_sha256']), 64)

    def test_offline_never_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / 'searches').mkdir()
            with self.assertRaises(RuntimeError):
                pubmed_cache.fetch_records(['123'], offline=True, data=data)


if __name__ == '__main__':
    unittest.main()
