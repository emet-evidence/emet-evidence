"""Locate the workspace an EMET command works on, and read its configuration.

A workspace is the project that consumes the engine: it holds `emet.json`, `topics/<id>.json` and the review data
(`data/`). The engine itself (code, `methodology/`, schemas, profiles) lives next to this package and never stores
review data. Resolution order: the EMET_WORKSPACE environment variable, then the nearest parent of the current
directory that contains `emet.json`, then the current directory.
"""
import json, os
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
# Installed package: methodology/ is shipped inside emet/ (pyproject force-include); source checkout: next to emet/.
_PACKAGED = Path(__file__).resolve().parent / 'methodology'
METHODOLOGY = _PACKAGED if _PACKAGED.is_dir() else ENGINE / 'methodology'
CONFIG = 'emet.json'


def find_root(start=None):
    env = os.environ.get('EMET_WORKSPACE')
    if env:
        return Path(env).resolve()
    here = Path(start or Path.cwd()).resolve()
    for p in (here, *here.parents):
        if (p / CONFIG).exists():
            return p
    return here


ROOT = find_root()


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def config(root=None):
    path = Path(root or ROOT) / CONFIG
    return _load(path) if path.exists() else {}


def topic_ids(root=None):
    """Topics in the order declared by emet.json, then any other topics/<id>.json."""
    root = Path(root or ROOT)
    declared = config(root).get('topics', [])
    found = sorted(p.stem for p in (root / 'topics').glob('*.json'))
    return declared + [t for t in found if t not in declared]


def topic(subject, root=None):
    path = Path(root or ROOT) / 'topics' / f'{subject}.json'
    if not path.exists():
        raise SystemExit(f'unknown topic {subject!r}: {path} not found')
    return _load(path)


def outputs(root=None):
    """Published outputs of each topic (page, data, references), with its search folder, in declared order."""
    root = Path(root or ROOT)
    out = {}
    for t in topic_ids(root):
        cfg = topic(t, root)
        if cfg.get('outputs'):
            out[t] = {**cfg['outputs'], 'searches': search_folder(t, root).relative_to(root).as_posix(), **cfg.get('site', {})}
    return out


DEFAULT_ARMS = {'intervention': {'key': 'intervention', 'label': 'intervention', 'short': 'intervention'},
                'comparator': {'key': 'comparator', 'label': 'comparator', 'short': 'comparator'}}


def effect_arms(subject, root=None):
    """Arms of the effect extraction of a topic (`effects.arms` of topics/<id>.json): keys used in the extraction files
    for the intervention and comparator groups, with their display labels."""
    try:
        arms = topic(subject, root).get('effects', {}).get('arms', {})
    except SystemExit:
        arms = {}
    return {k: {**DEFAULT_ARMS[k], **arms.get(k, {})} for k in DEFAULT_ARMS}


def output_path(subject, kind, root=None):
    """Path of a topic output declared in topics/<id>.json (`outputs.data`, `outputs.references`, `outputs.page`)."""
    root = Path(root or ROOT)
    path = topic(subject, root).get('outputs', {}).get(kind)
    if not path:
        raise SystemExit(f'{subject}: outputs.{kind} not declared in topics/{subject}.json')
    return root / path


def search_folder(subject, root=None):
    """data/searches/<folder> of a topic: declared in the topic file, else the latest <id>-<date> folder."""
    root = Path(root or ROOT)
    path = root / 'topics' / f'{subject}.json'
    if path.exists() and _load(path).get('search_folder'):
        return root / 'data/searches' / _load(path)['search_folder']
    found = sorted(root.glob(f'data/searches/{subject}-20*'))
    if not found:
        raise SystemExit(f'no search folder for topic {subject!r}')
    return found[-1]
