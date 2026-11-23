#!/usr/bin/env python3
"""Structured effects (module methodology/agents/effect-extraction.md): checks, A/B comparison, calculations.

  python3 -m emet.effects check <topic>     # word-for-word quotes, fields, numbers present in the quote
  python3 -m emet.effects compare <topic>   # A versus B on the double-extracted outcomes -> effects-disagreements.json
  python3 -m emet.effects final <topic>     # A + arbitration -> effects-final.json, calculated effects (RR, MD, 95% CI)

Deterministic calculations, no pooling across studies: relative risk (Katz method, 0.5 correction when an arm
has 0 events), mean difference (normal CI). Nothing is calculated when a value is missing.
"""
import json, math, re, sys, unicodedata
from pathlib import Path

from emet.i18n import _
from emet.workspace import ROOT, effect_arms, search_folder
FIELDS = ('n', 'events', 'mean', 'sd')


def folder(subject):
    return search_folder(subject) / 'screening/effects'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def norm(text):
    text = unicodedata.normalize('NFKC', text or '').replace(' ', ' ').replace(' ', ' ').replace('\xa0', ' ')
    text = re.sub(r'[‐-―−]', '-', text)
    text = text.replace('’', "'").replace('“', '"').replace('”', '"')
    return re.sub(r'\s+', ' ', text).strip().lower()


def num(x):
    if x is None or x == '':
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r'-?\d+(?:[.,]\d+)?', str(x).replace(' ', '').replace(' ', ''))
    return float(m.group().replace(',', '.')) if m else None


def entries(base, reviewer):
    out = []
    for path in sorted(base.glob(f'effects-{reviewer}-*.json')):
        for e in load(path):
            e = {k: v for k, v in e.items() if not k.startswith('_')}
            e['_file'] = path.name
            out.append(e)
    return out


def sources(base, subject):
    lots = {}
    for path in base.glob('lot-*.json'):
        for s in load(path)['studies']:
            lots.setdefault(s['study'], set()).update(s['sources'])
    return {k: ' '.join(norm((ROOT / f).read_text(encoding='utf-8')) for f in v) for k, v in lots.items()}


def check(subject, quiet=False):
    base = folder(subject)
    src = sources(base, subject)
    problems, warnings = [], []
    for who in 'AB':
        for i, e in enumerate(entries(base, who)):
            tag = f'{who} {e.get("study")} {e.get("outcome")} {e.get("timepoint")} ({e["_file"]})'
            text = src.get(e.get('study'), '')
            q = norm(e.get('quote'))
            if not q or q not in text:
                problems.append(f'{tag}: quote not found in the source')
                continue
            for arm, g in (e.get('groups') or {}).items():
                for f in ('n', 'events', 'mean', 'sd'):
                    v = (g or {}).get(f)
                    if v is not None and num(v) is not None:
                        s = str(v).replace('.', ',') if isinstance(v, float) else str(v)
                        if not (re.search(rf'(?<![\d.,]){re.escape(str(v))}(?![\d])', text) or s in text or str(v).replace(',', '.') in text):
                            warnings.append(f'{tag}: {arm}.{f} = {v} not found in digits (written in words?)')
    if not quiet:
        for p in problems:
            print('PROBLEM', p)
        for w in sorted(set(warnings)):
            print('WARNING', w)
        print(f'{subject}: {sum(len(entries(base, w)) for w in "AB")} entries, {len(problems)} problem(s)')
    return problems


def key(e):
    return (e.get('study'), e.get('outcome'), e.get('timepoint_months'), norm(e.get('measure_label'))[:12])


def compare(subject):
    base = folder(subject)
    A, B = entries(base, 'A'), entries(base, 'B')
    doubled = {(e['study'], e['outcome']) for e in B}
    disagreements, matched = [], 0
    for b in B:
        cands = [a for a in A if a.get('study') == b.get('study') and a.get('outcome') == b.get('outcome') and a.get('timepoint_months') == b.get('timepoint_months')]
        best = None
        for a in cands:
            if norm(a.get('measure_label'))[:6] == norm(b.get('measure_label'))[:6]:
                best = a
                break
        best = best or (cands[0] if len(cands) == 1 else None)
        if not best:
            disagreements.append({'study': b['study'], 'outcome': b['outcome'], 'timepoint': b.get('timepoint'), 'issue': _('entry of B without a match in A'), 'B': b})
            continue
        matched += 1
        diffs = []
        for arm in arm_keys(subject):
            for f in FIELDS:
                va, vb = num(((best.get('groups') or {}).get(arm) or {}).get(f)), num(((b.get('groups') or {}).get(arm) or {}).get(f))
                if va != vb:
                    diffs.append(_('{field}: A {a} / B {b}', field=f'{arm}.{f}', a=va, b=vb))
        if diffs:
            disagreements.append({'study': b['study'], 'outcome': b['outcome'], 'timepoint': b.get('timepoint'), 'measure': b.get('measure_label'),
                                  'issue': _('; ').join(diffs), 'A': best, 'B': b})
    for a in A:
        if (a['study'], a['outcome']) in doubled and not any(b['study'] == a['study'] and b['outcome'] == a['outcome'] and b.get('timepoint_months') == a.get('timepoint_months') for b in B):
            disagreements.append({'study': a['study'], 'outcome': a['outcome'], 'timepoint': a.get('timepoint'), 'issue': _('entry of A without a match in B'), 'A': a})
    for d in disagreements:
        for k in ('A', 'B'):
            if k in d:
                d[k] = {x: y for x, y in d[k].items() if x != '_file'}
    (base / 'effects-disagreements.json').write_text(json.dumps(disagreements, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{subject}: {len(B)} B entries, {matched} matched, {len(disagreements)} disagreement(s) -> effects-disagreements.json')


def rr(e1, n1, e0, n0):
    if None in (e1, n1, e0, n0) or n1 <= 0 or n0 <= 0:
        return None
    if e1 == 0 and e0 == 0:
        return None
    if e1 == 0 or e0 == 0:
        e1, n1, e0, n0 = e1 + .5, n1 + 1, e0 + .5, n0 + 1
    r = (e1 / n1) / (e0 / n0)
    se = math.sqrt(1 / e1 - 1 / n1 + 1 / e0 - 1 / n0)
    return {'measure': 'RR', 'value': r, 'ci_low': math.exp(math.log(r) - 1.96 * se), 'ci_high': math.exp(math.log(r) + 1.96 * se)}


def md(m1, s1, n1, m0, s0, n0):
    if None in (m1, s1, n1, m0, s0, n0) or n1 <= 0 or n0 <= 0:
        return None
    d = m1 - m0
    se = math.sqrt(s1 ** 2 / n1 + s0 ** 2 / n0)
    return {'measure': 'MD', 'value': d, 'ci_low': d - 1.96 * se, 'ci_high': d + 1.96 * se}


def arm_keys(subject):
    arms = effect_arms(subject)
    return arms['intervention']['key'], arms['comparator']['key']


def computed(e, keys=('intervention', 'comparator')):
    """RR or MD of the intervention arm against the comparator arm (keys: arm names used in the extraction files)."""
    g = e.get('groups') or {}
    a, b = g.get(keys[0]) or {}, g.get(keys[1]) or {}
    if e.get('type') == 'dichotomous':
        return rr(num(a.get('events')), num(a.get('n')), num(b.get('events')), num(b.get('n')))
    if e.get('type') == 'continuous':
        return md(num(a.get('mean')), num(a.get('sd')), num(a.get('n')), num(b.get('mean')), num(b.get('sd')), num(b.get('n')))
    return None


def flag_p(e):
    """Flags a calculated effect inconsistent with the p value reported by the authors (often: n analysed ≠ n used)."""
    c, p = e.get('computed'), num((e.get('reported_effect') or {}).get('p'))
    if not c or p is None or '<' in str((e.get('reported_effect') or {}).get('p')):
        return
    null = 1 if c['measure'] == 'RR' else 0
    excludes = c['ci_low'] > null or c['ci_high'] < null
    if excludes != (p < 0.05):
        c['warning'] = _('inconsistent with the reported p = {p} (analysed sample sizes probably different): interpret with caution', p=e['reported_effect']['p'])


def final(subject):
    base = folder(subject)
    keys = arm_keys(subject)
    A = entries(base, 'A')
    arb_path = base / 'effects-arbitration.json'
    arbitration = load(arb_path) if arb_path.exists() else []
    out = []
    for a in A:
        e = {k: v for k, v in a.items() if k != '_file'}
        for d in arbitration:
            if d.get('study') == e['study'] and d.get('outcome') == e['outcome'] and d.get('timepoint_months', e.get('timepoint_months')) == e.get('timepoint_months') \
                    and norm(d.get('measure_label', e.get('measure_label')))[:6] == norm(e.get('measure_label'))[:6]:
                if d.get('drop'):
                    e = None
                    break
                for arm, fields in (d.get('groups') or {}).items():
                    e.setdefault('groups', {}).setdefault(arm, {}).update(fields)
                e['arbitration'] = d.get('reason')
        if e is None:
            continue
        e['computed'] = computed(e, keys)
        flag_p(e)
        out.append(e)
    for d in arbitration:
        if d.get('add'):
            e = d['add']
            e['computed'] = computed(e, keys)
            e['arbitration'] = d.get('reason')
            out.append(e)
    (base / 'effects-final.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    n = sum(1 for e in out if e['computed'])
    print(f'{subject}: {len(out)} results, {n} calculated effects -> effects-final.json')


if __name__ == '__main__':
    {'check': check, 'compare': compare, 'final': final}[sys.argv[1]](sys.argv[2])
