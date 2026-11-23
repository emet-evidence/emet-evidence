"""Localisation of the user-facing text rendered by the engine.

Messages are written in English in the code: the English text is the message id. Catalogs in `emet/locales/<lang>.json`
map a message id to its translation; a message missing from the catalog falls back to the English id. A message that
depends on context (same English text, different translations) is looked up as `"<context>|<msgid>"` (see `_p`).
The special `_number` entry of a catalog gives the decimal separator, thousands separator and minus sign of the
language.

The language is the `language` key of the workspace's emet.json (default English), or the one set by `set_language`.
"""
import json
from pathlib import Path

from emet import workspace

LOCALES = Path(__file__).resolve().parent / 'locales'
NUMBER = {'decimal': '.', 'thousands': ',', 'minus': '-'}

_state = {'override': None, 'configured': None}
_catalogs = {}


def set_language(lang):
    """Force the language (None returns to the workspace configuration)."""
    _state['override'] = lang


def language():
    if _state['override']:
        return _state['override']
    if _state['configured'] is None:
        _state['configured'] = workspace.config().get('language', 'en')
    return _state['configured']


def catalog(lang=None):
    lang = lang or language()
    if lang not in _catalogs:
        path = LOCALES / f'{lang}.json'
        _catalogs[lang] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return _catalogs[lang]


def _format(text, kw):
    return text.format(**kw) if kw else text


def _(msgid, **kw):
    """Translation of `msgid` in the current language (the English msgid itself if missing), formatted with `kw`."""
    return _format(catalog().get(msgid, msgid), kw)


def _p(context, msgid, **kw):
    """Same as `_`, for a message whose translation depends on `context` (catalog key `"<context>|<msgid>"`)."""
    return _format(catalog().get(f'{context}|{msgid}', msgid), kw)


def N_(msgid):
    """Marks a message for translation without translating it (module-level tables); translate it with `_` at use."""
    return msgid


def number_rule(lang=None):
    return {**NUMBER, **catalog(lang).get('_number', {})}


def fmt_number(value, decimals=None):
    """Number in the conventions of the current language: integers with thousands separators, or `decimals` digits
    after the decimal separator (without grouping)."""
    rule = number_rule()
    text = f'{value:,}' if decimals is None else f'{value:.{decimals}f}'
    return text.translate(str.maketrans({',': rule['thousands'], '.': rule['decimal'], '-': rule['minus']}))
