import unittest

from tests.helpers import ROOT, SCHEMA_PATH, WORKSPACE, fixture, load_json  # noqa: F401  (adds the engine to sys.path)
from emet import check_review


def run_checks(review):
    """Même enchaînement que check_review.main ; un plantage d'intégrité compte comme une erreur détectée."""
    schema = load_json(SCHEMA_PATH)
    errors = check_review.validate(review, schema, schema)
    try:
        errors += check_review.integrity(review)
    except (KeyError, TypeError) as exc:
        errors.append(f'plantage des contrôles : {exc!r}')
    return errors


class Baseline(unittest.TestCase):
    def test_fixture_passes(self):
        self.assertEqual(run_checks(fixture()), [])

    def test_fixture_has_no_warnings(self):
        self.assertEqual(check_review.warnings(fixture()), [])

    def test_real_pilot_passes(self):
        path = WORKSPACE / 'data' / 'reviews' / 'immobilisation.json'
        if not path.exists():
            self.skipTest('data/reviews/immobilisation.json absent')
        self.assertEqual(run_checks(load_json(path)), [])


class Mutations(unittest.TestCase):
    """Chaque garde-fou doit se déclencher quand la donnée est corrompue."""

    def assertDetected(self, review, fragment=None):
        errors = run_checks(review)
        self.assertTrue(errors, 'mutation non détectée')
        if fragment:
            self.assertTrue(any(fragment in e for e in errors), f'« {fragment} » absent de {errors}')
        return errors

    # -- identités PRISMA
    def test_reports_excluded_plus_one(self):
        r = fixture(); r['flow']['reports_excluded'] += 1
        self.assertDetected(r, 'PRISMA')

    def test_each_numeric_flow_field_is_guarded(self):
        for key in ('identified_total', 'duplicates_removed', 'records_screened', 'records_excluded_titles', 'records_assessed_abstracts',
                    'records_excluded_abstracts', 'reports_sought', 'reports_not_retrieved', 'reports_assessed', 'reports_included', 'studies_included'):
            with self.subTest(key=key):
                r = fixture(); r['flow'][key] += 1
                self.assertDetected(r, 'PRISMA')

    def test_abstract_code_sum_mismatch(self):
        r = fixture(); r['flow']['abstracts_excluded_by_code']['E1'] += 1
        self.assertDetected(r, 'exclusion reasons (abstracts)')

    def test_report_code_sum_mismatch(self):
        r = fixture(); r['flow']['reports_excluded_by_code']['E4'] = 2
        self.assertDetected(r, 'exclusion reasons (full text)')

    def test_source_sum_mismatch(self):
        r = fixture(); r['flow']['identified_by_source']['Base fictive'] -= 1
        self.assertDetected(r, 'sources')

    def test_studies_included_differs_from_studies(self):
        r = fixture(); r['studies'].pop(); r['risk_of_bias'].pop(); r['reports'].pop()
        self.assertDetected(r, 'studies included')

    # -- liens entre entités
    def test_duplicate_record_id(self):
        r = fixture(); r['records'].append(dict(r['records'][0]))
        self.assertDetected(r, 'duplicate')

    def test_decision_on_unknown_record(self):
        r = fixture(); r['screening_decisions'].append({'record': 'ZZZ', 'stage': 'titles', 'reviewer': 'A', 'decision': 'include'})
        self.assertDetected(r, 'unknown records')

    def test_report_linked_to_unknown_study(self):
        r = fixture(); r['reports'][0]['study'] = 'S-INCONNUE'
        self.assertDetected(r, 'unknown study')

    def test_study_lists_missing_report(self):
        r = fixture(); r['studies'][0]['reports'].append('R-ABSENT')
        self.assertDetected(r, 'missing from reports')

    def test_study_unknown_outcome(self):
        r = fixture(); r['studies'][0]['outcomes'].append('O99')
        self.assertDetected(r, 'unknown outcomes')

    def test_rob_on_unknown_study(self):
        r = fixture(); r['risk_of_bias'][0]['study'] = 'S-INCONNUE'
        self.assertDetected(r, 'unknown study')

    def test_record_without_final_title_decision(self):
        r = fixture()
        r['screening_decisions'] = [d for d in r['screening_decisions'] if not (d['record'] == 'M8' and d['stage'] == 'titles' and d['reviewer'] == 'resolved')]
        self.assertDetected(r, 'without a final title-screening decision')

    # -- pré-filtre
    def test_prefilter_without_low_zone_read(self):
        r = fixture()
        r['screening_decisions'] = [d for d in r['screening_decisions'] if not (d['record'] == 'M1' and d['stage'] == 'prefilter-low-zone')]
        self.assertDetected(r, 'without being read')

    def test_every_prefiltered_record_needs_a_read(self):
        for rec in sorted({d['record'] for d in fixture()['screening_decisions'] if d['stage'] == 'prefilter'}):
            with self.subTest(record=rec):
                r = fixture()
                r['screening_decisions'] = [d for d in r['screening_decisions'] if not (d['record'] == rec and d['stage'] == 'prefilter-low-zone')]
                self.assertDetected(r, 'without being read')

    # -- essais randomisés ↔ RoB 2
    def test_rct_without_rob2(self):
        r = fixture(); r['risk_of_bias'][0]['tool'] = 'Non évaluable'
        self.assertDetected(r, 'RoB 2')

    def test_rob2_study_not_randomized(self):
        r = fixture(); r['studies'][0]['randomized'] = None
        self.assertDetected(r, 'RoB 2')

    def test_non_randomized_study_assessed_with_rob2(self):
        r = fixture(); r['risk_of_bias'][1]['tool'] = 'RoB 2'
        self.assertDetected(r, 'RoB 2')

    # -- schéma
    def test_wrong_enum_decision(self):
        r = fixture(); r['screening_decisions'][0]['decision'] = 'maybe'
        self.assertDetected(r, 'not in')

    def test_wrong_enum_stage_and_level(self):
        r = fixture(); r['screening_decisions'][0]['stage'] = 'nope'
        self.assertDetected(r, 'not in')
        r = fixture(); r['risk_of_bias'][0]['level'] = 'medium'
        self.assertDetected(r, 'not in')

    def test_wrong_schema_version(self):
        r = fixture(); r['schema_version'] = '9.9'
        self.assertDetected(r, 'not in')

    def test_missing_required_field(self):
        r = fixture(); del r['studies'][0]['label']
        self.assertDetected(r, 'missing required field "label"')

    def test_missing_required_top_level(self):
        r = fixture(); del r['grade']
        self.assertDetected(r, 'missing required field "grade"')

    def test_wrong_type(self):
        r = fixture(); r['studies'][0]['year'] = 'deux mille seize'
        self.assertDetected(r, 'type str')

    def test_bool_is_not_integer(self):
        r = fixture(); r['searches'][0]['n_results'] = True
        self.assertDetected(r, 'type bool')

    def test_wrong_type_array(self):
        r = fixture(); r['records'] = {}
        self.assertDetected(r, 'type dict')


if __name__ == '__main__':
    unittest.main()
