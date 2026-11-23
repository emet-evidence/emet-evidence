"""Declarations of interest (emet/interests.py): identity criteria, checks, consolidation, rendering. Synthetic data, no network."""
import contextlib, hashlib, io, json, re, shutil, tempfile, unittest
from pathlib import Path

from tests.helpers import fixture
from emet import check_review, cohort_overlap, i18n, interests, pubmed_cache, render_p0, workspace

ENTITIES = [{'id': 'E1', 'name': 'Acme Medical', 'aliases': ['AcmeFix']}]


def author_xml(family, given, initials, affiliation='', orcid=None):
    ident = f'<Identifier Source="ORCID">https://orcid.org/{orcid}</Identifier>' if orcid else ''
    aff = f'<AffiliationInfo><Affiliation>{affiliation}</Affiliation></AffiliationInfo>' if affiliation else ''
    return f'<Author><LastName>{family}</LastName><ForeName>{given}</ForeName><Initials>{initials}</Initials>{ident}{aff}</Author>'


def record(pmid, authors, year, month='Mar', coi='', grants=''):
    xml = (f'<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article><Journal><JournalIssue><PubDate><Year>{year}</Year><Month>{month}</Month>'
           f'</PubDate></JournalIssue></Journal><ArticleTitle>Article {pmid}</ArticleTitle><AuthorList>{"".join(authors)}</AuthorList>'
           f'{grants}</Article>{f"<CoiStatement>{coi}</CoiStatement>" if coi else ""}</MedlineCitation>'
           f'<PubmedData><ArticleIdList><ArticleId IdType="pubmed">{pmid}</ArticleId></ArticleIdList></PubmedData></PubmedArticle>')
    return {'pmid': pmid, 'title': f'Article {pmid}', 'authors': [], 'identifiers': {'pubmed': pmid},
            'raw_record_xml': xml, 'raw_record_sha256': hashlib.sha256(xml.encode()).hexdigest()}


DUPONT = author_xml('Dupont', 'Jean', 'J', 'Department of Surgery, University of Somewhere, Somewhere')
MARTIN = author_xml('Martin', 'Anne', 'A', 'Clinic X')


class Helpers(unittest.TestCase):
    def test_same_name(self):
        a = {'family': 'Dupont', 'initials': 'JP', 'given': 'Jean'}
        self.assertTrue(interests.same_name(a, {'family': 'DUPONT', 'initials': 'J', 'given': ''}))
        self.assertFalse(interests.same_name(a, {'family': 'Dupont', 'initials': 'M', 'given': ''}))
        self.assertTrue(interests.same_name({'family': 'Müller', 'initials': 'K'}, {'family': 'Muller', 'initials': 'K'}))

    def test_identity_criteria(self):
        me = {'family': 'Dupont', 'initials': 'J', 'orcid': None, 'affiliations': ['University of Somewhere, Somewhere']}
        study = [me, {'family': 'Martin', 'initials': 'A'}]
        other = {'family': 'Dupont', 'initials': 'J', 'orcid': None, 'affiliations': ['University of Somewhere']}
        self.assertEqual(interests.identity(me, study, other, [other, {'family': 'Martin', 'initials': 'A'}]), ['institution', 'coauthor'])
        stranger = {'family': 'Dupont', 'initials': 'J', 'orcid': None, 'affiliations': ['Another Hospital']}
        self.assertEqual(interests.identity(me, study, stranger, [stranger]), [])
        self.assertIsNone(interests.identity({**me, 'orcid': '0000-0001-0000-0001'}, study, {**other, 'orcid': '0000-0001-0000-0002'}, [other]))
        self.assertEqual(interests.identity({**me, 'orcid': '0000-0001-0000-0001'}, study, {**stranger, 'orcid': '0000-0001-0000-0001'}, [stranger]), ['orcid'])

    def test_months_between(self):
        self.assertEqual(interests.months_between((2018, 3), (2020, 1)), 22)
        self.assertEqual(interests.months_between((2018, None), (2016, 5)), -24)
        self.assertIsNone(interests.months_between((None, None), (2016, 5)))

    def test_mentions_whole_words_and_aliases(self):
        self.assertEqual(interests.mentions('Consultant for ACME MEDICAL Inc.', ENTITIES), ['E1'])
        self.assertEqual(interests.mentions('Speaker for AcmeFix', ENTITIES), ['E1'])
        self.assertEqual(interests.mentions('Acme Medicalis', ENTITIES), [])

    def test_quoted(self):
        self.assertTrue(interests.quoted('received  fees from Acme', 'Dr X received fees from ACME.'))
        self.assertTrue(interests.quoted('author’s fees', "the author's fees"))
        self.assertFalse(interests.quoted('received grants', 'Dr X received fees'))
        self.assertFalse(interests.quoted('', 'anything'))

    def test_forbidden_wording(self):
        self.assertEqual(interests.forbidden({'quote': 'No conflict of interest', 'location': 'Conflicts of interest'}), [])
        self.assertEqual(len(interests.forbidden({'reason': 'the link was omitted from the study'})), 1)
        self.assertEqual(len(interests.forbidden({'reason': 'un lien non déclaré'})), 1)
        self.assertEqual(len(interests.forbidden({'reason': 'Conflit possible'})), 1)
        self.assertEqual(interests.forbidden({'team': [{'declaration': 'No conflict of interest.'}]}), [])

    def test_pubmed_details(self):
        rec = record('1', [DUPONT], 2019, coi='JD is a consultant for Acme Medical.',
                     grants='<GrantList><Grant><GrantID>R01</GrantID><Agency>NIH</Agency><Country>United States</Country></Grant></GrantList>')
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'articles').mkdir()
        (tmp / 'articles/1.json').write_text(json.dumps(rec))
        original = pubmed_cache.DATA
        pubmed_cache.DATA = tmp
        self.addCleanup(setattr, pubmed_cache, 'DATA', original)
        d = interests.details('1')
        self.assertEqual((d['year'], d['month']), (2019, 3))
        self.assertEqual(d['coi'], 'JD is a consultant for Acme Medical.')
        self.assertEqual(d['grants'], [{'id': 'R01', 'agency': 'NIH', 'country': 'United States'}])
        self.assertEqual(d['authors'][0]['affiliations'], ['Department of Surgery, University of Somewhere, Somewhere'])


class Merge(unittest.TestCase):
    def entry(self, status='links_declared', entity='E1'):
        return {'funding': {'status': 'not_reported', 'items': []},
                'declaration': {'status': status, 'links': [{'author': 'J Dupont', 'relevant_entity': entity}] if status == 'links_declared' else []}}

    def test_studies_outside_dual_coverage_take_a(self):
        final, pending = interests.merge_studies({'S1': self.entry(), 'S2': self.entry()}, {'S1': self.entry()}, {})
        self.assertEqual((sorted(final), pending), (['S1', 'S2'], []))

    def test_studies_disagreement_needs_arbitration(self):
        a, b = {'S1': self.entry()}, {'S1': self.entry('no_link_declared')}
        self.assertEqual(interests.merge_studies(a, b, {})[1], ['S1'])
        final, pending = interests.merge_studies(a, b, {'S1': b['S1']})
        self.assertEqual((final['S1']['declaration']['status'], pending), ('no_link_declared', []))

    def test_authors_need_both_reviewers(self):
        keep = {'decision': 'possible_link', 'relevant_entity': 'E1', 'type': 'speaker'}
        drop = {'decision': 'not_retained'}
        self.assertEqual(interests.merge_authors({'c1': keep}, {'c1': dict(keep)}, {}, False), ({'c1': keep}, []))
        self.assertEqual(interests.merge_authors({'c1': keep}, {'c1': {**keep, 'type': 'consultancy'}}, {}, False)[1], ['c1'])
        self.assertEqual(interests.merge_authors({'c1': keep}, {}, {}, False)[1], ['c1'])
        self.assertEqual(interests.merge_authors({'c1': keep}, {'c1': drop}, {'c1': drop}, False)[0], {'c1': drop})
        self.assertEqual(interests.merge_authors({'c1': keep}, {}, {}, True)[0], {'c1': keep})


class Workspace(unittest.TestCase):
    """collect → authors → final on a temporary workspace, offline."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        t = self.tmp
        for rel in ('data/reviews', 'data/protocols', 'data/articles', 'data/searches/mini-2026-01-01/screening/eligibility', 'topics'):
            (t / rel).mkdir(parents=True)
        (t / 'emet.json').write_text(json.dumps({'profile': 'rapid', 'topics': ['mini'], 'interests': {'correction_contact': 'corrections@example.org'},
                                                 'review_team': [{'name': 'Anne Martin', 'role': 'methodological lead', 'declaration': 'No link of interest.'}]}))
        (t / 'topics/mini.json').write_text(json.dumps({'id': 'mini', 'search_folder': 'mini-2026-01-01'}))
        (t / 'data/protocols/mini.json').write_text(json.dumps({'interest_entities': ENTITIES, 'interest_topic_query': 'topic'}))
        review = {'studies': [{'id': 'S-1', 'label': 'Dupont · 2019', 'reports': ['1'], 'page_reference': 'R1'},
                              {'id': 'S-2', 'label': 'Martin · 2018', 'reports': ['2'], 'page_reference': 'R2'}]}
        (t / 'data/reviews/mini.json').write_text(json.dumps(review))
        records = [record('1', [DUPONT, MARTIN], 2019, coi='The authors declare no link of interest.'),
                   record('2', [MARTIN], 2018),
                   # other publications of J Dupont on the topic: same institution / different ORCID / outside the window
                   record('10', [author_xml('Dupont', 'Jean', 'J', 'University of Somewhere'), author_xml('Roux', 'P', 'P')], 2020,
                          coi='J. Dupont received speaker fees from Acme Medical. P. Roux has nothing to disclose.'),
                   record('11', [author_xml('Dupont', 'Jules', 'J', 'Another Hospital')], 2020, coi='Consultant for Acme Medical.'),
                   record('12', [author_xml('Dupont', 'Jean', 'J', 'University of Somewhere')], 2010, coi='Consultant for Acme Medical.')]
        for r in records:
            (t / f'data/articles/{r["pmid"]}.json').write_text(json.dumps(r))
        self.patch(workspace, 'ROOT', t)
        self.patch(interests, 'ROOT', t)
        self.patch(cohort_overlap, 'ROOT', t)
        self.patch(pubmed_cache, 'DATA', t / 'data')
        self.patch(interests, 'esearch', lambda term, path, offline, refresh: ['1', '10', '11', '12'] if 'Dupont' in term else ['2'])
        self.dir = t / 'data/searches/mini-2026-01-01/screening/interests'
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, original)

    def write(self, name, value):
        (self.dir / name).write_text(json.dumps(value))

    def run_until_candidates(self):
        interests.collect('mini', offline=True)
        interests.authors_stage('mini', offline=True)
        return json.loads((self.dir / 'author-candidates.json').read_text())

    def test_collect_writes_sources(self):
        interests.collect('mini', offline=True)
        sources = json.loads((self.dir / 'study-sources.json').read_text())['studies']
        self.assertEqual(sources['S-1']['items'][0]['text'], 'The authors declare no link of interest.')
        self.assertEqual(sources['S-2']['items'], [])
        self.assertIn('src-1', (self.dir / 'studies/S-1.txt').read_text())

    def test_candidates_need_identity_and_window(self):
        cand = self.run_until_candidates()
        self.assertEqual([c['source']['pmid'] for c in cand['candidates']], ['10'])
        c = cand['candidates'][0]
        self.assertEqual((c['study'], c['identity'], c['entities_mentioned'], c['months_from_study']), ('S-1', ['name', 'institution'], ['E1'], 12))
        s = cand['summary']
        self.assertEqual((s['identity_not_confirmed'], s['outside_window'], s['candidates']), (1, 1, 1))

    def test_final_badge_and_review(self):
        cid = self.run_until_candidates()['candidates'][0]['id']
        l1 = {'S-1': {'funding': {'status': 'not_reported', 'items': []},
                      'declaration': {'status': 'no_link_declared', 'source': 'src-1', 'quote': 'declare no link of interest', 'links': []}},
              'S-2': {'funding': {'status': 'not_accessible', 'items': []}, 'declaration': {'status': 'not_accessible', 'links': []}}}
        self.write('study-declarations-A.json', l1)
        keep = {'decision': 'possible_link', 'entity': 'Acme Medical', 'relevant_entity': 'E1', 'type': 'speaker',
                'quote': 'J. Dupont received speaker fees from Acme Medical', 'reason': 'the statement names J. Dupont'}
        self.write('author-assessment-A.json', {cid: keep})
        self.write('author-assessment-B.json', {cid: dict(keep)})
        interests.final('mini')
        out = json.loads((self.dir / 'interests-final.json').read_text())
        by = {i['study']: i for i in out['items']}
        self.assertTrue(by['S-1']['badge'])
        self.assertFalse(by['S-2']['badge'])
        self.assertEqual(by['S-1']['other_publications'][0]['source']['url'], 'https://pubmed.ncbi.nlm.nih.gov/10/')
        self.assertEqual(out['review_declaration']['coauthored_studies'],
                         [{'study': 'S-1', 'label': 'Dupont · 2019', 'member': 'Anne Martin', 'matched_by': 'name', 'status': 'candidate'},
                          {'study': 'S-2', 'label': 'Martin · 2018', 'member': 'Anne Martin', 'matched_by': 'name', 'status': 'candidate'}])
        # A correction request under examination hides the item, and the badge with it.
        self.write('corrections.json', [{'date': '2026-01-02', 'item': cid, 'status': 'under_examination', 'reason': 'request received'}])
        self.write('review-team-authorship.json', {'S-2': {'Anne Martin': 'not_author'}})
        interests.final('mini')
        out = json.loads((self.dir / 'interests-final.json').read_text())
        self.assertFalse(out['items'][0]['badge'])
        self.assertEqual([s['study'] for s in out['review_declaration']['coauthored_studies']], ['S-1'])

    def test_final_fails_closed(self):
        cid = self.run_until_candidates()['candidates'][0]['id']
        self.write('study-declarations-A.json', {'S-1': {'funding': {'status': 'not_reported', 'items': []},
                                                         'declaration': {'status': 'no_link_declared', 'source': 'src-1', 'quote': 'a quotation that is not in the source', 'links': []}}})
        keep = {'decision': 'possible_link', 'entity': 'Acme', 'relevant_entity': 'E1', 'type': 'speaker', 'quote': 'speaker fees from Acme Medical', 'reason': 'omitted from the study'}
        self.write('author-assessment-A.json', {cid: keep})
        self.write('author-assessment-B.json', {cid: {'decision': 'not_retained', 'reason': 'another author'}})
        with self.assertRaises(SystemExit):
            interests.final('mini')
        self.assertFalse((self.dir / 'interests-final.json').exists())


def with_interests(badge=True):
    r = fixture()
    sid = r['studies'][0]['id']
    other = [{'id': 'c1', 'author': 'Dupont J', 'entity': 'Acme Medical', 'relevant_entity': 'E1', 'type': 'speaker',
              'quote': 'received speaker fees from Acme Medical', 'source': {'pmid': '10', 'title': 'Article 10', 'year': 2020, 'location': 'PubMed record, CoiStatement',
                                                                             'url': 'https://pubmed.ncbi.nlm.nih.gov/10/'}}] if badge else []
    items = [{'study': s['id'], 'label': s['label'], 'page_reference': s['page_reference'],
              'funding': {'status': 'not_reported', 'items': []}, 'declaration': {'status': 'not_accessible', 'links': []},
              'other_publications': other if s['id'] == sid else [], 'badge': bool(other) and s['id'] == sid} for s in r['studies']]
    r['interests'] = {'status': 'complete', 'items': items, 'entities': ENTITIES, 'window_months': 36,
                      'coverage': {'studies': len(items), 'declaration_accessible': 0, 'authors': 3, 'possible_links': len(other), 'with_badge': int(bool(other))},
                      'corrections': [], 'correction_contact': 'corrections@example.org',
                      'review_declaration': {'team': [{'name': 'Anne Martin', 'declaration': 'No link of interest.'}], 'coauthored_studies': []}}
    return r, sid


class Rendering(unittest.TestCase):
    def setUp(self):
        i18n.set_language('fr')
        self.addCleanup(i18n.set_language, None)

    def test_no_interests_no_badge(self):
        r = fixture()
        self.assertEqual(render_p0.interest_badge(r, r['studies'][0]['id']), '')
        self.assertNotIn('p0-interest', render_p0.study_explorer(r, {'studies': {'R1': {}, 'R2': {}}}, 'base'))
        self.assertIn('Non recherché pour cette revue.', render_p0.interests_section(r))
        self.assertEqual(render_p0.review_declaration(r), '')

    def test_badge_in_tables_and_section(self):
        r, sid = with_interests()
        html = render_p0.study_explorer(r, {'studies': {'R1': {}, 'R2': {}}}, 'base')
        self.assertEqual(html.count('lien d&#x27;intérêts possible') + html.count("lien d'intérêts possible"), 1)
        self.assertIn(f'href="#interets-{sid}"', html)
        section = render_p0.interests_section(r)
        self.assertIn(f'id="interets-{sid}"', section)
        self.assertIn('https://pubmed.ncbi.nlm.nih.gov/10/', section)
        self.assertIn('mailto:corrections@example.org', section)
        self.assertIn('Déclaration d', render_p0.review_declaration(r))
        self.assertIsNone(interests.FORBIDDEN.search(re.sub(r'<[^>]+>', ' ', section)))


class CheckReview(unittest.TestCase):
    def test_consistent_interests_pass(self):
        r, _sid = with_interests()
        self.assertEqual(check_review.interests_integrity(r, {s['id'] for s in r['studies']}), [])

    def test_errors(self):
        r, _sid = with_interests()
        r['interests']['items'][0]['badge'] = False
        r['interests']['correction_contact'] = None
        r['interests']['items'][0]['other_publications'][0]['quote'] = ''
        r['interests']['review_declaration']['team'] = []
        r['interests']['note'] = 'a hidden link'
        errors = check_review.interests_integrity(r, {s['id'] for s in r['studies']})
        for text in ('badge inconsistent', 'without a quotation', 'correction channel', 'declaration of interest of the review', 'wording'):
            self.assertTrue(any(text in e for e in errors), text)

    def test_schema(self):
        r, _sid = with_interests()
        schema = json.loads((Path(__file__).resolve().parent.parent / 'methodology/schemas/review.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(check_review.validate(r, schema, schema), [])
        r['interests']['items'][0]['declaration']['status'] = 'undeclared'
        self.assertTrue(check_review.validate(r, schema, schema))


if __name__ == '__main__':
    unittest.main()
