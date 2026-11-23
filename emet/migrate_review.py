#!/usr/bin/env python3
"""Migrate a v0.7 review to the versioned v0.8 exchange format (methodology/schemas/review.schema.json).

Reads existing files only (protocol, searches, selection decisions, arbitrated extraction, page JSON,
verifications, baseline cost) and invents nothing: missing data stays missing, with an explicit status
(`not_extracted`, `not_assessed`, `null`). Output: data/reviews/<topic>.json.

  python3 -m emet.migrate_review <topic>
"""
import json, subprocess, sys
from collections import Counter
from pathlib import Path

from emet.i18n import _
from emet.workspace import ROOT, config, effect_arms, output_path, search_folder
SCHEMA_VERSION = '0.8.0-draft.1'
# Keys of ACCESS and KIND are values of the v0.7 page data (studies[].access, studies[].kind), in French.
ACCESS = {'texte intégral': 'full_text', 'résumé': 'abstract', 'fiche de registre': 'registry'}
KIND = {'étude primaire': 'primary', 'revue systématique': 'systematic_review', 'fiche de registre': 'registry'}
DECISION = {'include': 'include', 'exclude': 'exclude'}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def protocol_commit(path):
    log = git('log', '--diff-filter=A', '--format=%H %cI', '--', path).splitlines()
    return dict(zip(('commit', 'committed_at'), log[-1].split())) if log else {'commit': None, 'committed_at': None}


def searches(base):
    out = []
    for path in sorted(base.glob('*.json')):
        d = load(path)
        if not isinstance(d, dict) or 'query' not in d:
            continue
        n = None
        if 'esearchresult' in d:
            n = int(d['esearchresult'].get('count', 0))
        elif 'hitCount' in d:
            n = d['hitCount']
        out.append({'id': path.stem, 'source': (d.get('header') or {}).get('type') if isinstance(d.get('header'), dict) else path.stem.split('-')[0],
                    'query': d['query'], 'retrieved_at': d.get('retrieved_at'), 'url': d.get('url'), 'n_results': n,
                    'file': path.relative_to(ROOT).as_posix()})
    if (base / 'consensus.txt').exists():
        out.append({'id': 'consensus', 'source': 'consensus', 'query': None, 'retrieved_at': None, 'url': None,
                    'n_results': None, 'file': (base / 'consensus.txt').relative_to(ROOT).as_posix(),
                    'note': _('query and date in the topic manifest; licence: answer not redistributable')})
    return out


def decisions(S, final):
    out = []
    prefilter = load(S / 'titles-prefilter.json') if (S / 'titles-prefilter.json').exists() else {}
    for rid, d in prefilter.items():
        out.append({'record': rid, 'stage': 'prefilter', 'reviewer': 'script', 'decision': 'deprioritize', 'code': d.get('code'), 'reason': d.get('by')})
    audit = {}
    for path in sorted(S.glob('prefilter-audit-out-*.json')):
        audit.update(load(path))
    for rid, d in audit.items():
        out.append({'record': rid, 'stage': 'prefilter-low-zone', 'reviewer': 'single', 'decision': d['decision'], 'code': d.get('code')})
    raw = {'titles': ('titles-grey-A.json', 'titles-grey-B.json'), 'abstracts': ('abstracts-A.json', 'abstracts-B.json'),
           'eligibility': ('fulltext-A.json', 'fulltext-B.json')}
    for stage, files in raw.items():
        for reviewer, name in zip('AB', files):
            if (S / name).exists():
                for rid, d in load(S / name).items():
                    out.append({'record': rid, 'stage': stage, 'reviewer': reviewer, 'decision': DECISION.get(d['decision'], d['decision']), 'code': d.get('code')})
    stage_name = {'titles': 'titles', 'abstracts': 'abstracts', 'fulltext': 'eligibility'}
    for stage, items in final['decisions'].items():
        for rid, d in items.items():
            by = 'script' if stage == 'titles' and rid in prefilter else d.get('by')
            out.append({'record': rid, 'stage': stage_name[stage], 'reviewer': 'resolved', 'decision': DECISION.get(d['decision'], d['decision']),
                        'code': d.get('code'), 'reason': by})
    # "Other methods" branch (citation iterations): pre-filter, dual reading of titles and abstracts.
    for path in sorted(S.glob('snow*-records.json')):
        n = path.name.split('-')[0]
        branch = load(path)
        for rid, d in branch['prefilter'].items():
            out.append({'record': rid, 'stage': 'prefilter', 'reviewer': 'script', 'decision': 'deprioritize', 'code': d.get('code'), 'reason': d.get('by')})
        for stage, prefix in (('titles', 'titles'), ('abstracts', 'abstracts')):
            a, b = (S / f'{prefix}-{n}-A.json', S / f'{prefix}-{n}-B.json')
            if not a.exists():
                continue
            a, b = load(a), load(b)
            for reviewer, items in (('A', a), ('B', b)):
                for rid, d in items.items():
                    out.append({'record': rid, 'stage': stage, 'reviewer': reviewer, 'decision': d['decision'], 'code': d.get('code')})
            for rid in a:
                da, db = a[rid], b.get(rid, {})
                if stage == 'titles':  # disagreement = passed on to abstracts (doubt = next stage)
                    dec = 'include' if 'include' in (da['decision'], db.get('decision')) else 'exclude'
                    reason = _('agreement') if da['decision'] == db.get('decision') else _('disagreement passed on to abstracts')
                else:
                    dec = da['decision'] if da['decision'] == db.get('decision') else 'undetermined'
                    reason = _('agreement') if dec != 'undetermined' else _('disagreement not arbitrated')
                out.append({'record': rid, 'stage': stage, 'reviewer': 'resolved', 'decision': dec, 'code': da.get('code') if dec == 'exclude' else None, 'reason': reason})
    # Records rescued from the low zone: dual abstract screening.
    rescued = {}
    for reviewer in 'AB':
        path = S / f'prefilter-rescued-{reviewer}.json'
        if path.exists():
            for rid, d in load(path).items():
                out.append({'record': rid, 'stage': 'abstracts', 'reviewer': reviewer, 'decision': d['decision'], 'code': d.get('code'), 'reason': _('rescued from the low zone')})
                rescued.setdefault(rid, []).append(d['decision'])
    for rid, ds in rescued.items():
        out.append({'record': rid, 'stage': 'abstracts', 'reviewer': 'resolved', 'decision': ds[0] if len(set(ds)) == 1 else 'undetermined', 'code': None, 'reason': _('rescued from the low zone')})
    # Final title-screening decision for the low-zone records of the iterations (single reading).
    resolved_titles = {d['record'] for d in out if d['stage'] == 'titles' and d['reviewer'] == 'resolved'}
    for rid, d in audit.items():
        if rid not in resolved_titles:
            out.append({'record': rid, 'stage': 'titles', 'reviewer': 'resolved', 'decision': 'include' if rid in rescued else 'exclude',
                        'code': d.get('code'), 'reason': _('low zone: single reading of title + abstract')})
    for rid in final.get('not_retrieved', []):
        out.append({'record': rid, 'stage': 'eligibility', 'reviewer': 'resolved', 'decision': 'not_retrieved', 'code': None})
    return out, len(audit)


def effect_estimates(S, subject):
    path = S / 'effects/effects-final.json'
    if not path.exists():
        return {'status': 'not_extracted', 'items': [], 'note': _('results extracted as free text (studies[].result of the page); structured extraction to be done')}
    items = load(path)
    return {'status': 'partial', 'items': items, 'arms': effect_arms(subject),
            'note': _('randomized trials only; reviewer A on all outcomes, reviewer B on the critical outcomes (O1, O2, O5), arbitration of '
                      'disagreements; effects calculated by script (Katz RR, mean difference), without pooling across studies')}


def interests(S):
    path = S / 'interests/interests-final.json'
    if not path.exists():
        return {'status': 'not_assessed', 'items': [], 'note': _('declarations of interest not assessed for this review')}
    data = load(path)
    return {'status': 'complete', 'items': data['items'], 'levels': data['levels'], 'entities': data['entities'],
            'window_months': data['window_months'], 'coverage': data['coverage'], 'corrections': data['corrections'],
            'review_declaration': data['review_declaration'],
            'correction_contact': (config().get('interests') or {}).get('correction_contact')}


def main(subject):
    protocol_path = f'data/protocols/{subject}.json'
    protocol = load(ROOT / protocol_path)
    base = search_folder(subject)
    S = base / 'screening'
    final = load(S / 'final.json')
    page = load(output_path(subject, 'data'))
    refs = load(output_path(subject, 'references'))
    records = load(S / 'records.json')['records']
    late = load(S / 'late-duplicates.json') if (S / 'late-duplicates.json').exists() else {}
    fulltext = set(page.get('fulltext_consulted', []))

    # Reports and studies: one study per page entry; late duplicates and the reports of the same trial
    # (randomized_trials) are linked to the kept study.
    trial_groups = {r: t for t in page['randomized_trials'] for r in t['references']}
    studies, reports = [], []
    for R, s in page['studies'].items():
        rid = refs.get(R)
        group = trial_groups.get(R)
        if group and group['references'][0] != R:
            continue  # secondary report of a trial already described
        study_reports = [refs[r] for r in (group['references'] if group else [R])]
        study_reports += [dup for dup, d in late.items() if d.get('kept') in study_reports]
        rob = page['risk_of_bias'].get(R, {})
        studies.append({'id': f'S-{rid}', 'label': s['label'], 'year': s['year'], 'design': s['design'],
                        'kind': KIND.get(s.get('kind'), 'unknown'), 'reports': study_reports, 'page_reference': R,
                        'rob_tool': rob.get('tool'), 'outcomes': s.get('outcomes', []),
                        'randomized': {'n': group['randomized'], 'source': group['source']} if group else None})
        for r in study_reports:
            if r in late:
                role, access = 'duplicate', 'unknown'
            else:
                role = 'primary_report' if r == rid else 'secondary_report'
                access = 'full_text' if R in fulltext else ACCESS.get(s.get('access'), 'unknown')
            reports.append({'id': r, 'study': f'S-{rid}', 'role': role, 'access': access})

    decs, low_zone = decisions(S, final)
    snow_titles = load(S / 'snow-titles.json') if (S / 'snow-titles.json').exists() else {}
    snow_records, other = [], {'identified': 0, 'deprioritized': 0, 'titles_dual': 0, 'abstracts_assessed': 0, 'reports_sought': 0}
    for path in sorted(S.glob('snow*-records.json')):
        n = path.name.split('-')[0]
        branch = load(path)
        tsv = {}
        if (S / f'titles-{n}.tsv').exists():
            for line in (S / f'titles-{n}.tsv').read_text(encoding='utf-8').splitlines()[1:]:
                cells = line.split('\t')
                tsv[cells[0]] = {'year': cells[1], 'type': cells[2], 'title': cells[3] if len(cells) > 3 else ''}
        for rid in branch['ids']:
            meta = tsv.get(rid) or snow_titles.get(rid) or {}
            snow_records.append({'id': rid, 'title': meta.get('title'), 'year': meta.get('year'), 'journal': None,
                                 'type': meta.get('type'), 'sources': [f'citations-{n}']})
        other['identified'] += len(branch['ids'])
        other['deprioritized'] += len(branch['prefilter'])
        other['titles_dual'] += len(branch['grey'])
        if (S / f'abstracts-{n}-A.json').exists():
            other['abstracts_assessed'] += len(load(S / f'abstracts-{n}-A.json'))
    other['reports_sought'] = len(final['fulltext'].get('other_methods', []))
    titles, abstracts, ft = final['titles'], final['abstracts'], final['fulltext']
    prefiltered = sum(1 for d in decs if d['stage'] == 'prefilter')
    flow = {
        'identified_by_source': final['summary']['identified_by_source'],
        'identified_total': final['summary']['identified_total'],
        'duplicates_removed': final['summary']['duplicates_removed'],
        'records_screened': titles['screened'],
        'records_deprioritized_by_prefilter': prefiltered,
        'records_low_zone_single_read': low_zone,
        'records_excluded_titles': titles['excluded'],
        'records_assessed_abstracts': abstracts['assessed'],
        'records_excluded_abstracts': abstracts['excluded'],
        'abstracts_excluded_by_code': abstracts.get('excluded_by_code', {}),
        'other_methods': {**other, 'note': _('iterations of references and citations, deduplicated against the main branch')},
        'reports_sought_from_databases': ft['assessed'] - other['reports_sought'],
        'reports_sought': ft['assessed'],
        'reports_not_retrieved': ft['not_retrieved'],
        'reports_assessed': ft['assessed'] - ft['not_retrieved'],
        'reports_excluded': ft['excluded'],
        'reports_excluded_by_code': ft.get('excluded_by_code', {}),
        'reports_included': len(final['included']),
        'studies_included': len(studies),
        'units': {'records': _('records after deduplication'), 'reports': _('reports or registry records assessed'), 'studies': _('unique studies')},
    }

    verification = ROOT / f'data/verification/{subject}'
    claims = load(verification / 'claims.json') if (verification / 'claims.json').exists() else []
    report = load(verification / 'report.json') if (verification / 'report.json').exists() else None
    if report and isinstance(report.get('verdicts'), dict):  # fixed order, independent of the run that wrote the report
        from emet.verify_claims import VERDICTS
        report['verdicts'] = {v: report['verdicts'][v] for v in (*VERDICTS, *sorted(set(report['verdicts']) - set(VERDICTS))) if v in report['verdicts']}
    baseline_path = ROOT / 'docs/emet/usage-baseline-v0.7.json'
    baseline = load(baseline_path)['by_subject'].get(subject) if baseline_path.exists() else None
    agreements = {st: load(S / f'{st}-agreement.json') for st in ('titles', 'abstracts', 'fulltext', 'rob') if (S / f'{st}-agreement.json').exists()}
    prefilter_audit = load(S / 'prefilter-audit.json') if (S / 'prefilter-audit.json').exists() else None
    if prefilter_audit:
        prefilter_audit = {k: v for k, v in prefilter_audit.items() if not k.endswith('_ids')}

    review = {
        'schema_version': SCHEMA_VERSION,
        'review': {'id': subject, 'title': protocol['title'], 'question': protocol['question'],
                   'methodology_version': '0.7', 'migrated_with_methodology': '0.71', 'review_depth': config().get('profile', 'rapid'),
                   'search_date': page['validation']['last_search'], 'public_status': 'AI-verified' if report and report.get('passed') is True else 'AI-generated'},
        'protocol': {'path': protocol_path, **protocol_commit(protocol_path), 'registered': protocol.get('registered'),
                     'status': protocol.get('status'), 'deviations': protocol.get('deviations', []),
                     'external_registration': None},
        'searches': searches(base),
        'records': [{'id': r['id'], 'title': r.get('title'), 'year': r.get('year'), 'journal': r.get('journal'),
                     'type': r.get('type'), 'sources': r.get('sources', [])} for r in records] + snow_records,
        'screening_decisions': decs,
        'reports': reports,
        'studies': studies,
        'cohorts': load(S / 'cohort-overlap.json') if (S / 'cohort-overlap.json').exists() else
                   {'status': 'not_assessed', 'items': [], 'note': _('cohort overlap not searched for in v0.7; only duplicate publications (E5) and the reports of the same trial are linked')},
        # 'critique' is the importance value of the protocol's outcomes (French data).
        'outcomes': [{'id': o['id'], 'label': o['label'], 'importance': 'critical' if o['importance'] == 'critique' else 'important'} for o in protocol['outcomes_grade']],
        'effect_estimates': effect_estimates(S, subject),
        'risk_of_bias': [{'study': next((st['id'] for st in studies if st['page_reference'] == R), None), 'page_reference': R, **v}
                         for R, v in page['risk_of_bias'].items()],
        'grade': page['grade'],
        'interests': interests(S),
        'claims': {'status': 'verified' if report and report.get('passed') is True else ('in_progress' if claims else 'not_started'),
                   'n_claims': len(claims), 'report': {k: report[k] for k in ('pairs', 'verdicts', 'passed') if k in report} if report else None},
        'flow': flow,
        'audit': {'agreement': agreements, 'prefilter': prefilter_audit,
                  'double_extraction': agreements.get('rob', {}).get('note')},
        'execution': {'models': page['method'].get('reviewer_models'), 'tokens': baseline,
                      'tokens_source': _('scripts/usage_baseline.py (transcripts, keyword attribution, approximate)') if baseline else None,
                      'cost_usd': None, 'duration_seconds': None},
    }
    out = ROOT / f'data/reviews/{subject}.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(review, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{out.relative_to(ROOT)}: {len(records)} records, {len(decs)} decisions, {len(reports)} reports, {len(studies)} studies')


if __name__ == '__main__':
    main(sys.argv[1])
