import hashlib, json, shutil, tempfile, unittest, zipfile
from pathlib import Path

from tests.helpers import ROOT, SCHEMA_PATH, fixture
from emet import render_p0

PAGE = {'studies': {'R1': {}, 'R2': {}}}
CODES = {'E1': 'Hors sujet : fictif', 'E2': 'Population : fictive', 'E4': 'Design : fictif'}


class OverallLevel(unittest.TestCase):
    def level(self, tool, overall, level='unclear'):
        return render_p0.overall_level({'tool': tool, 'overall': overall, 'level': level})

    def test_rob2(self):
        self.assertEqual(self.level('RoB 2', 'Faible'), 'low')
        self.assertEqual(self.level('RoB 2', 'Préoccupations'), 'some')
        self.assertEqual(self.level('RoB 2', 'Élevé'), 'high')

    def test_robins_i(self):
        self.assertEqual(self.level('ROBINS-I', 'Critique'), 'critical')
        self.assertEqual(self.level('ROBINS-I', 'Sérieux'), 'high')
        self.assertEqual(self.level('ROBINS-I', 'Modéré'), 'some')
        self.assertEqual(self.level('ROBINS-I', 'Faible'), 'low')

    def test_amstar2(self):
        self.assertEqual(self.level('AMSTAR 2', 'Critiquement faible'), 'critical')
        self.assertEqual(self.level('AMSTAR 2', 'Élevée'), 'low')
        self.assertEqual(self.level('AMSTAR 2', 'Modérée'), 'some')
        self.assertEqual(self.level('AMSTAR 2', 'Faible'), 'high')

    def test_amstar2_moderate_to_low_falls_back_to_level(self):
        self.assertEqual(self.level('AMSTAR 2', 'Modérée à faible', 'some'), 'some')
        self.assertEqual(self.level('AMSTAR 2', 'Modérée à faible', 'high'), 'high')

    def test_not_assessable_is_unclear(self):
        for tool in ('Non évaluable', 'RoB 2', 'AMSTAR 2'):
            self.assertEqual(self.level(tool, 'Non évaluable : registre sans résultats', 'low'), 'unclear')

    def test_unknown_tool_or_text_uses_level(self):
        self.assertEqual(self.level('JBI', 'Qualité correcte', 'some'), 'some')
        self.assertEqual(self.level('RoB 2', 'texte inattendu', 'high'), 'high')
        self.assertEqual(render_p0.overall_level({}), 'unclear')


class JudgementLevel(unittest.TestCase):
    def test_mapping(self):
        cases = {'faible': 'low', 'Oui': 'low', 'préoccupations': 'some', 'partiel': 'some', 'élevé': 'high',
                 'non rapporté': 'unclear', 'non': 'high', 'critique': 'critical', 'incertain': 'unclear',
                 '': 'unclear', None: 'unclear', 'autre': 'unclear'}
        for text, level in cases.items():
            with self.subTest(text=text):
                self.assertEqual(render_p0.judgement_level(text), level)

    def test_non_rapporte_is_not_high(self):
        # « non rapporté » commence par « non » : l'ordre des motifs doit le traiter avant.
        self.assertEqual(render_p0.judgement_level('Non rapporté'), 'unclear')


class PrismaCounts(unittest.TestCase):
    def test_fixture_counts(self):
        c = render_p0.prisma_counts(fixture())
        main, other = c['main'], c['other']
        self.assertEqual({k: v for k, v in main.items() if k != 'abstracts_codes'},
                         {'records': 8, 'prefiltered': 2, 'low_read': 2, 'low_kept': 1, 'titles_excluded': 2, 'abstracts': 6, 'abstracts_excluded': 2})
        self.assertEqual(dict(main['abstracts_codes']), {'E1': 1, 'E2': 1})
        self.assertEqual({k: v for k, v in other.items() if k != 'abstracts_codes'},
                         {'records': 4, 'prefiltered': 1, 'low_read': 1, 'low_kept': 0, 'titles_excluded': 2, 'abstracts': 2, 'abstracts_excluded': 1})
        self.assertEqual(dict(c['elig_codes']), {'E4': 1})
        self.assertEqual((c['linked'], c['secondary']), (1, 1))

    def test_branches_partition_records(self):
        r = fixture()
        main, other = render_p0.branches(r)
        self.assertFalse(main & other)
        self.assertEqual(main | other, {x['id'] for x in r['records']})

    def test_counts_match_flow(self):
        r = fixture(); c = render_p0.prisma_counts(r); f = r['flow']
        self.assertEqual(c['main']['records'] + c['other']['records'], f['records_screened'])
        self.assertEqual(c['main']['titles_excluded'] + c['other']['titles_excluded'], f['records_excluded_titles'])
        self.assertEqual(c['main']['abstracts'] + c['other']['abstracts'], f['records_assessed_abstracts'])
        self.assertEqual(c['main']['abstracts_excluded'] + c['other']['abstracts_excluded'], f['records_excluded_abstracts'])
        self.assertEqual(sum(c['elig_codes'].values()), f['reports_excluded'])


class Rendering(unittest.TestCase):
    def assertClean(self, html):
        self.assertNotIn('{{', html)
        self.assertNotIn('}}', html)

    def test_prisma_html(self):
        html = render_p0.prisma(fixture(), CODES, 'donnees/mini')
        self.assertClean(html)
        for strong, label in (('14', 'Notices identifiées'), ('2', 'Doublons retirés'), ('8', 'Notices triées'), ('4', 'Notices triées'),
                              ('5', 'Publications recherchées'), ('1', 'Non récupérées'), ('4', 'Éligibilité évaluée en double'),
                              ('3', 'Publications incluses'), ('2', 'Études uniques incluses')):
            with self.subTest(label=label, n=strong):
                self.assertIn(f'<strong>{strong}</strong><span>{label}</span>', html)
        self.assertIn('donnees/mini/prisma-incluses.csv', html)

    def test_study_explorer_html(self):
        html = render_p0.study_explorer(fixture(), PAGE, 'donnees/mini')
        self.assertClean(html)
        self.assertIn('2 études uniques', html)
        self.assertIn('Fictif · 2016', html)
        self.assertIn('data-rct="1"', html)
        self.assertIn('data-rct="0"', html)

    def test_rob_matrix_html(self):
        html = render_p0.rob_matrix(fixture(), PAGE)
        self.assertClean(html)
        self.assertIn('RoB 2 · 1 études', html)
        self.assertIn('ROBINS-I · 1 études', html)
        self.assertIn('Études non évaluables (fiches de registre sans résultats) : 0', html)

    def test_grade_summary_html(self):
        html = render_p0.grade_summary(fixture(), PAGE)
        self.assertClean(html)
        self.assertIn('p0-cert-faible', html)
        self.assertIn('<td>60</td>', html)  # participants randomisés de R1 seul (R2 non randomisé)


class ExportPackage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for rel in ('data/reviews', 'data/protocols', 'methodology/schemas', 'topics'):
            (self.tmp / rel).mkdir(parents=True)
        (self.tmp / 'topics/mini.json').write_text('{"id": "mini", "outputs": {"data": "data/question-mini.json"}}', encoding='utf-8')
        r = fixture()
        (self.tmp / 'data/reviews/mini.json').write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
        (self.tmp / 'data/question-mini.json').write_text(json.dumps(PAGE), encoding='utf-8')
        (self.tmp / 'data/protocols/mini.json').write_text('{"protocole": "fictif"}', encoding='utf-8')
        shutil.copy(SCHEMA_PATH, self.tmp / 'methodology/schemas/review.schema.json')
        original = render_p0.ROOT
        render_p0.ROOT = self.tmp
        self.addCleanup(setattr, render_p0, 'ROOT', original)
        self.out = render_p0.export_package('mini')

    def test_output_is_in_temp_dir(self):
        self.assertEqual(self.out, self.tmp / 'open-data' / 'mini')

    def test_manifest_hashes_match_files(self):
        manifest = json.loads((self.out / 'MANIFEST.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['review'], 'mini')
        self.assertIn('review.json', manifest['files'])
        self.assertNotIn('MANIFEST.json', manifest['files'])
        for name, meta in manifest['files'].items():
            data = (self.out / name).read_bytes()
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256(data).hexdigest(), meta['sha256'])
                self.assertEqual(len(data), meta['bytes'])

    def test_every_file_is_listed_and_zipped(self):
        manifest = json.loads((self.out / 'MANIFEST.json').read_text(encoding='utf-8'))
        written = {p.name for p in self.out.iterdir()} - {'MANIFEST.json', 'paquet-revue.zip'}
        self.assertEqual(written, set(manifest['files']))
        with zipfile.ZipFile(self.out / 'paquet-revue.zip') as z:
            self.assertEqual(set(z.namelist()), {f'mini/{n}' for n in written | {'MANIFEST.json'}})
            for name in written:
                self.assertEqual(z.read(f'mini/{name}'), (self.out / name).read_bytes())

    def test_exported_review_is_unchanged(self):
        exported = json.loads((self.out / 'review.json').read_text(encoding='utf-8'))
        self.assertEqual(exported, fixture())

    def test_included_list_has_expected_records(self):
        rows = (self.out / 'prisma-incluses.csv').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(rows) - 1, 3)  # M7, M8, C4
        self.assertEqual(len((self.out / 'selection.csv').read_text(encoding='utf-8').splitlines()) - 1, len(fixture()['screening_decisions']))


if __name__ == '__main__':
    unittest.main()
