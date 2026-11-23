#!/usr/bin/env python3
"""Detection of possibly overlapping cohorts between included primary studies (roadmap 6.2.5), without a model.

For each pair of primary studies of a structured review, clues: shared authors (family name + initial, archived
PubMed records), same registry number cited in the source files, close years, identical sample sizes.
Pairs above the threshold are **candidates**, not established duplicates: they are written to the review's
`cohorts` (status `partial`) and must be resolved (by an agent or a human) before any summing of sample sizes
or meta-analysis.

  python3 -m emet.cohort_overlap <topic>
"""
import itertools, json, re, sys
from pathlib import Path

from emet.i18n import _
from emet.workspace import ROOT, search_folder
NCT = re.compile(r'NCT\d{8}|ISRCTN\d{6,}|ACTRN\d{10,}|DRKS\d{6,}|ChiCTR[\w-]+|KCT\d{6,}', re.I)


def authors(report):
    path = ROOT / f'data/articles/{report}.json'
    if not path.exists():
        return set()
    return {f"{a['family'].lower()} {a['given'][:1].lower()}" for a in json.loads(path.read_text())['authors'] if a.get('family')}


def registries(subject, reports):
    base = search_folder(subject) / 'screening/eligibility'
    found = set()
    for r in reports:
        if r.startswith('NCT'):
            found.add(r.upper())
        path = base / f"{r.replace(':', '_')}.txt"
        if path.exists():
            found |= {m.upper() for m in NCT.findall(path.read_text(encoding='utf-8'))}
    return found


def main(subject):
    path = ROOT / f'data/reviews/{subject}.json'
    review = json.loads(path.read_text(encoding='utf-8'))
    primary = [s for s in review['studies'] if s['kind'] == 'primary']
    info = {s['id']: {'authors': set().union(*(authors(r) for r in s['reports'])) if s['reports'] else set(),
                      'registries': registries(subject, s['reports'])} for s in primary}
    candidates = []
    for a, b in itertools.combinations(primary, 2):
        ia, ib = info[a['id']], info[b['id']]
        shared = sorted(ia['authors'] & ib['authors'])
        reg = sorted(ia['registries'] & ib['registries'])
        same_n = a['randomized'] and b['randomized'] and a['randomized']['n'] and a['randomized']['n'] == b['randomized']['n']
        close = a['year'] and b['year'] and abs(a['year'] - b['year']) <= 4
        score = (3 if reg else 0) + (2 if len(shared) >= 3 else 1 if len(shared) == 2 else 0) + (1 if same_n else 0) + (1 if close and shared else 0)
        if score >= 2:
            candidates.append({'studies': [a['id'], b['id']], 'labels': [a['label'], b['label']], 'score': score,
                               'shared_authors': shared, 'shared_registries': reg, 'same_randomized_n': bool(same_n),
                               'status': 'candidate', 'resolution': None})
    candidates.sort(key=lambda c: -c['score'])
    out = search_folder(subject) / 'screening/cohort-overlap.json'
    previous = {tuple(c['studies']): c for c in (json.loads(out.read_text())['items'] if out.exists() else [])}
    for c in candidates:  # keep the resolutions already made
        old = previous.get(tuple(c['studies']))
        if old and old.get('resolution'):
            c['status'], c['resolution'] = old['status'], old['resolution']
    review['cohorts'] = {'status': 'partial', 'items': candidates,
                         'note': _('{n} primary studies compared pairwise (shared authors, registries, sample sizes, years); {candidates} candidate '
                                   'pairs; the participant totals shown assume distinct cohorts as long as a pair is not resolved',
                                   n=len(primary), candidates=len(candidates))}
    out.write_text(json.dumps(review['cohorts'], ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for c in candidates:
        print(c['score'], ' / '.join(c['labels']), '| authors:', ', '.join(c['shared_authors'][:4]), '| registries:', ', '.join(c['shared_registries']))
    print(f'{subject}: {len(candidates)} candidate pair(s) among {len(primary)} primary studies')


if __name__ == '__main__':
    main(sys.argv[1])
