#!/usr/bin/env python3
"""Validate a structured review (data/reviews/<topic>.json): schema, links between entities, PRISMA identities.

Minimal JSON Schema validator (type, required, properties, items, enum, local $ref), standard library only.
The integrity checks fail closed: every inconsistency is listed and the exit code is 1.

  python3 -m emet.check_review <topic>
"""
import json, sys
from collections import Counter
from pathlib import Path

from emet.workspace import ROOT, METHODOLOGY
TYPES = {'object': dict, 'array': list, 'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'null': type(None)}


def validate(value, schema, root, path='$', errors=None):
    errors = [] if errors is None else errors
    if '$ref' in schema:
        node = root
        for part in schema['$ref'].lstrip('#/').split('/'):
            node = node[part]
        return validate(value, node, root, path, errors)
    types = schema.get('type')
    if types:
        types = [types] if isinstance(types, str) else types
        ok = any(isinstance(value, TYPES[t]) and not (t == 'integer' and isinstance(value, bool)) for t in types)
        if not ok:
            errors.append(f'{path}: type {type(value).__name__}, expected {types}')
            return errors
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: value {value!r} not in {schema["enum"]}')
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                errors.append(f'{path}: missing required field "{key}"')
        for key, sub in schema.get('properties', {}).items():
            if key in value:
                validate(value[key], sub, root, f'{path}.{key}', errors)
    if isinstance(value, list) and 'items' in schema:
        for i, item in enumerate(value):
            validate(item, schema['items'], root, f'{path}[{i}]', errors)
            if len(errors) > 50:
                break
    return errors


def integrity(r):
    errors = []
    records = {x['id'] for x in r['records']}
    studies = {s['id'] for s in r['studies']}
    reports = {x['id']: x for x in r['reports']}
    outcomes = {o['id'] for o in r['outcomes']}
    dup = [k for k, n in Counter(x['id'] for x in r['records']).items() if n > 1]
    if dup:
        errors.append(f'duplicate records: {dup[:5]}')
    unknown = {d['record'] for d in r['screening_decisions']} - records
    if unknown:
        errors.append(f'{len(unknown)} decisions on unknown records: {sorted(unknown)[:5]}')
    for x in r['reports']:
        if x['study'] not in studies:
            errors.append(f'report {x["id"]} linked to an unknown study {x["study"]}')
    for s in r['studies']:
        for rep in s['reports']:
            if rep not in reports:
                errors.append(f'study {s["id"]}: report {rep} missing from reports')
        bad = [o for o in s['outcomes'] if o not in outcomes and o.rstrip('abc') not in outcomes]
        if bad:
            errors.append(f'study {s["id"]}: unknown outcomes {bad}')
    for x in r['risk_of_bias']:
        if x['study'] not in studies:
            errors.append(f'risk of bias linked to an unknown study ({x.get("page_reference")})')
    # Every deduplicated record has a final title-screening decision.
    titled = {d['record'] for d in r['screening_decisions'] if d['stage'] == 'titles' and d['reviewer'] == 'resolved'}
    if titled != records:
        errors.append(f'{len(records - titled)} records without a final title-screening decision')
    # No record set aside by the pre-filter without being read (v0.71).
    low = {d['record'] for d in r['screening_decisions'] if d['stage'] == 'prefilter'}
    read = {d['record'] for d in r['screening_decisions'] if d['stage'] == 'prefilter-low-zone'}
    if low - read:
        errors.append(f'{len(low - read)} records set aside by the pre-filter without being read: {sorted(low - read)[:5]}')
    # PRISMA identities.
    f = r['flow']
    checks = [
        ('identified − duplicates = records screened', f['identified_total'] - f['duplicates_removed'], f['records_screened']),
        ('records screened − excluded on title = abstracts assessed', f['records_screened'] - f['records_excluded_titles'], f['records_assessed_abstracts']),
        ('abstracts assessed − excluded = reports sought (databases)', f['records_assessed_abstracts'] - f['records_excluded_abstracts'], f.get('reports_sought_from_databases', f['reports_sought'])),
        ('databases + other methods = reports sought', f.get('reports_sought_from_databases', f['reports_sought']) + f.get('other_methods', {}).get('reports_sought', 0), f['reports_sought']),
        ('sought − not retrieved = assessed', f['reports_sought'] - f['reports_not_retrieved'], f['reports_assessed']),
        ('assessed − excluded = included', f['reports_assessed'] - f['reports_excluded'], f['reports_included']),
        ('sum of exclusion reasons (abstracts)', sum(f.get('abstracts_excluded_by_code', {}).values()), f['records_excluded_abstracts']),
        ('sum of exclusion reasons (full text)', sum(f.get('reports_excluded_by_code', {}).values()), f['reports_excluded']),
        ('sum of sources = identified', sum(f.get('identified_by_source', {}).values()), f['identified_total']),
        ('studies included = studies', f['studies_included'], len(r['studies'])),
    ]
    for label, got, expected in checks:
        if got != expected:
            errors.append(f'PRISMA: {label} ({got} ≠ {expected})')
    trials = [s for s in r['studies'] if s['randomized']]
    rob2 = {x['study'] for x in r['risk_of_bias'] if x['tool'] == 'RoB 2'}
    if {s['id'] for s in trials} != rob2:
        errors.append(f'randomized trials ≠ studies assessed with RoB 2 ({len(trials)} versus {len(rob2)})')
    return errors


def warnings(r):
    """Non-blocking inconsistencies to fix in the data: coded level ≠ written overall judgment."""
    from emet import render_p0
    return [f'risk of bias {x["page_reference"]} ({x["tool"]}): "{x["overall"]}" coded {x["level"]}, displayed {render_p0.overall_level(x)}'
            # 'Non évaluable' is a tool value of the review data (registry records without results).
            for x in r['risk_of_bias'] if x['tool'] != 'Non évaluable' and render_p0.overall_level(x) != x['level']]


def main(subject):
    schema = json.loads((METHODOLOGY / 'schemas/review.schema.json').read_text(encoding='utf-8'))
    review = json.loads((ROOT / f'data/reviews/{subject}.json').read_text(encoding='utf-8'))
    errors = validate(review, schema, schema)
    if not errors:  # the integrity checks assume a valid schema
        errors = integrity(review)
    for e in errors:
        print('ERROR', e)
    for w in warnings(review):
        print('WARNING', w)
    print(f'{subject}: {"OK" if not errors else f"{len(errors)} error(s)"} (schema {review.get("schema_version")})')
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main(sys.argv[1])
