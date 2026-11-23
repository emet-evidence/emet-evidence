"""The engine (emet/, methodology/) must stay independent of the site that consumes it (shoulder-surgery.eu)."""
import re, unittest

from tests.helpers import ROOT

SITE_TERMS = re.compile(r'shoulder|épaule|epaule|coiffe|rotator|cuff|immobilis|tabagisme|calcifiante|conflit|douleur|depilation|'
                        r'capsulite|acide-hyal|cigarette|reeducation|drchelli|validate_pilot|build_page|question-[a-z]', re.I)
# Remaining couplings, to be removed (docs/emet/separation-plan.md). The list may only shrink.
KNOWN = {
    'methodology/agents/screening.md': 1,           # pre-filter audit figures of the pilot review
}


class EngineBoundary(unittest.TestCase):
    def test_no_new_site_terms(self):
        files = [*ROOT.glob('emet/*.py'), *ROOT.glob('methodology/agents/*.md'), *ROOT.glob('methodology/profiles/*.json'),
                 *ROOT.glob('methodology/schemas/*.json'), ROOT / 'methodology/ORCHESTRATOR.md', ROOT / 'methodology/pipeline.json']
        counts = {}
        for path in files:
            n = len(SITE_TERMS.findall(path.read_text(encoding='utf-8')))
            if n:
                counts[path.relative_to(ROOT).as_posix()] = n
        for f, n in counts.items():
            self.assertLessEqual(n, KNOWN.get(f, 0), f'{f}: {n} site-specific term(s), allowed {KNOWN.get(f, 0)}')


if __name__ == '__main__':
    unittest.main()
