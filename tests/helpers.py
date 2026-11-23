"""Utilitaires communs aux tests (bibliothèque standard seule)."""
import copy, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Workspace used by tests that read review data: EMET_WORKSPACE, else this checkout if it is a workspace (emet.json),
# else the bundled example workspace of the public repository.
if not os.environ.get('EMET_WORKSPACE') and not (ROOT / 'emet.json').exists() and (ROOT / 'examples/shoulder-surgery/emet.json').exists():
    os.environ['EMET_WORKSPACE'] = str(ROOT / 'examples/shoulder-surgery')
WORKSPACE = Path(os.environ.get('EMET_WORKSPACE') or ROOT)
sys.path.insert(0, str(ROOT))
FIXTURE = ROOT / 'tests' / 'fixtures' / 'mini_review.json'
SCHEMA_PATH = ROOT / 'methodology' / 'schemas' / 'review.schema.json'


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def fixture():
    """Copie profonde et indépendante de la revue synthétique."""
    return copy.deepcopy(load_json(FIXTURE))
