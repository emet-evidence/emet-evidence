import unittest

from tests.helpers import ROOT, load_json
from emet import orchestrate


class Profiles(unittest.TestCase):
    def test_rapid_has_no_inheritance(self):
        self.assertNotIn('inherits', orchestrate.profile('rapid'))

    def test_standard_inherits_rapid(self):
        rapid, standard = orchestrate.profile('rapid'), orchestrate.profile('standard')
        self.assertEqual(rapid['extraction']['double_extraction_coverage'], 0.2)
        self.assertEqual(standard['extraction']['double_extraction_coverage'], 1.0)
        # clé non redéfinie par standard : héritée telle quelle de rapid
        self.assertEqual(standard['search'], rapid['search'])
        self.assertEqual(standard['non_disableable_checks'], rapid['non_disableable_checks'])
        self.assertEqual(standard['screening']['low_zone_reader'], rapid['screening']['low_zone_reader'])
        # fusion récursive d'un niveau : « always_double » de rapid survit dans extraction
        self.assertEqual(standard['extraction']['always_double'], rapid['extraction']['always_double'])
        self.assertEqual(standard['extraction']['B'], 'sonnet')

    def test_profile_does_not_mutate_between_calls(self):
        orchestrate.profile('standard')
        self.assertEqual(orchestrate.profile('rapid')['extraction']['double_extraction_coverage'], 0.2)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.stages = load_json(ROOT / 'methodology' / 'pipeline.json')['stages']

    def test_stage_ids_unique(self):
        ids = [s['id'] for s in self.stages]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_stage_has_module_kind_outputs(self):
        for s in self.stages:
            with self.subTest(stage=s.get('id')):
                for key in ('id', 'module', 'kind', 'outputs'):
                    self.assertIn(key, s)
                self.assertIsInstance(s['outputs'], list)

    def test_modules_exist(self):
        for s in self.stages:
            with self.subTest(stage=s['id']):
                self.assertTrue((ROOT / 'methodology' / s['module'].split('#')[0]).exists())

    def test_output_placeholders_are_known(self):
        names = orchestrate.folders('sujet')
        for s in self.stages:
            for o in s['outputs']:
                with self.subTest(stage=s['id'], output=o):
                    o.format(**names)  # KeyError si un champ inconnu


if __name__ == '__main__':
    unittest.main()
