"""Localisation of the engine's user-facing text (emet/i18n.py, emet/locales/)."""
import ast, json, unittest

from tests.helpers import ROOT, WORKSPACE
from emet import i18n, render_p0
from emet.i18n import _, _p, fmt_number

LOCALES = ROOT / 'emet' / 'locales'


def message_ids():
    """Literal message ids of emet/*.py: _('…'), N_('…'), _p('context', '…') and the CSV columns of render_p0."""
    ids = {}
    for path in sorted(ROOT.glob('emet/*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            args = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None for a in node.args]
            name = node.func.id
            if name in ('_', 'N_') and args and args[0] is not None:
                found = [args[0]]
            elif name == '_p' and len(args) > 1 and None not in args[:2]:
                found = [f'{args[0]}|{args[1]}']
            elif name == 'columns' and path.name == 'render_p0.py':
                found = [f'csv|{a}' for a in args if a is not None]
            else:
                continue
            for msgid in found:
                ids.setdefault(msgid, f'{path.name}:{node.lineno}')
    return ids


class Language(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, None)

    def test_workspace_language(self):
        self.assertEqual(i18n.language(), json.loads((WORKSPACE / 'emet.json').read_text(encoding='utf-8')).get('language', 'en'))

    def test_override(self):
        i18n.set_language('en')
        self.assertEqual(i18n.language(), 'en')


class Translate(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, None)

    def test_fallback_to_msgid(self):
        i18n.set_language('fr')
        self.assertEqual(_('A message that no catalog contains'), 'A message that no catalog contains')
        i18n.set_language('xx')  # no catalog at all
        self.assertEqual(_('Overall'), 'Overall')

    def test_translation(self):
        i18n.set_language('fr')
        self.assertEqual(_('Overall'), 'Global')
        self.assertEqual(_p('source', 'All'), 'Toutes')
        self.assertEqual(_('All'), 'Tous')
        i18n.set_language('en')
        self.assertEqual(_p('source', 'All'), 'All')

    def test_placeholders(self):
        i18n.set_language('fr')
        self.assertEqual(_('{label}: {value}', label='Durée', value='3 s'), 'Durée : 3 s')
        self.assertEqual(_('{tool} · {n} studies', tool='RoB 2', n=4), 'RoB 2 · 4 études')
        i18n.set_language('en')
        self.assertEqual(_('{tool} · {n} studies', tool='RoB 2', n=4), 'RoB 2 · 4 studies')
        self.assertEqual(_('Not formatted {n}'), 'Not formatted {n}')


class Numbers(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, None)

    def test_french(self):
        i18n.set_language('fr')
        self.assertEqual(fmt_number(1234567), '1 234 567')
        self.assertEqual(fmt_number(12), '12')
        self.assertEqual(fmt_number(-0.5, 2), '−0,50')
        self.assertEqual(fmt_number(1234.5, 1), '1234,5')
        self.assertEqual(render_p0.fmt(4146), '4 146')
        self.assertEqual(render_p0.pct(1, 3), '33 %')

    def test_english(self):
        i18n.set_language('en')
        self.assertEqual(fmt_number(1234567), '1,234,567')
        self.assertEqual(fmt_number(-0.5, 2), '-0.50')
        self.assertEqual(render_p0.fmt(None), '—')
        self.assertEqual(render_p0.pct(1, 3), '33%')


class Catalogs(unittest.TestCase):
    def catalog(self, lang):
        return json.loads((LOCALES / f'{lang}.json').read_text(encoding='utf-8'))

    def test_every_message_is_translated_in_french(self):
        fr = self.catalog('fr')
        ids = message_ids()
        self.assertGreater(len(ids), 100)
        missing = {m: where for m, where in ids.items() if m not in fr}
        self.assertEqual(missing, {}, 'messages without a French translation (the French site would fall back to English)')

    def test_french_catalog_has_no_stale_entry(self):
        ids = message_ids()
        self.assertEqual([k for k in self.catalog('fr') if k != '_number' and k not in ids], [])

    def test_placeholders_match(self):
        import string
        fields = lambda s: sorted(f for _t, f, _s, _c in string.Formatter().parse(s) if f)
        for msgid, text in self.catalog('fr').items():
            if msgid == '_number':
                continue
            with self.subTest(msgid=msgid):
                self.assertEqual(fields(msgid.split('|', 1)[-1]) if '{' in msgid else [], fields(text) if '{' in text else [])

    def test_profile_descriptions_in_sync(self):
        # The profile descriptions are shown translated on the pages (render_p0.reproducibility).
        for path in sorted((ROOT / 'methodology' / 'profiles').glob('*.json')):
            with self.subTest(profile=path.stem):
                self.assertEqual(render_p0.PROFILE_DESCRIPTIONS.get(path.stem), json.loads(path.read_text(encoding='utf-8')).get('description'))

    def test_number_rules(self):
        for lang in ('en', 'fr'):
            with self.subTest(lang=lang):
                self.assertEqual(set(self.catalog(lang)['_number']), {'decimal', 'thousands', 'minus'})


class EnglishRendering(unittest.TestCase):
    def setUp(self):
        i18n.set_language('en')
        self.addCleanup(i18n.set_language, None)

    def test_prisma_and_script_in_english(self):
        from tests.helpers import fixture
        html = render_p0.prisma(fixture(), {'E1': 'Off topic: x'}, 'donnees/mini')
        self.assertIn('<strong>14</strong><span>Records identified</span>', html)
        self.assertNotIn('Notices', html)
        self.assertIn("' studies shown'", render_p0.SCRIPT)


if __name__ == '__main__':
    unittest.main()
