"""Scripted title pre-filter, driven by the `prefilter` block of topics/<id>.json.

A record goes to dual reading (grey zone) when it comes from a source outside `screen_all_unless_only_from`, when it
was returned by one of the `specific_queries` (PubMed ESearch files of the search folder), or when its title matches
the first applicable `title_rules` entry. Rules are pattern names (case-insensitive regexes from `patterns`) combined
with {"all": [...]}, {"any": [...]} and {"not": ...}; an entry with `unless_source` applies only to records that do not
come from that source. Other records are excluded with the `exclusion` code and rationale.

  python3 -m emet.prefilter <topic>
"""
import re, sys

from emet.screening import folder, load, save
from emet.workspace import topic


def compile_rules(cfg):
    patterns = {k: re.compile(v, re.I) for k, v in cfg.get('patterns', {}).items()}

    def match(expr, title):
        if isinstance(expr, str):
            return bool(patterns[expr].search(title))
        if 'all' in expr:
            return all(match(e, title) for e in expr['all'])
        if 'any' in expr:
            return any(match(e, title) for e in expr['any'])
        if 'not' in expr:
            return not match(expr['not'], title)
        raise ValueError(f'invalid pre-filter rule {expr!r}')
    return patterns, match


def keeper(cfg, base):
    """Return keep(record) for a topic's pre-filter configuration and search folder."""
    _, match = compile_rules(cfg)
    always = set(cfg.get('screen_all_unless_only_from', []))
    specific = set()
    for q in cfg.get('specific_queries', []):
        specific |= set(load(base / f'{q}.json')['esearchresult']['idlist'])

    def keep(r):
        if set(r['sources']) - always or r['id'] in specific:
            return True
        title = r['title'] or ''
        for entry in cfg.get('title_rules', []):
            if entry.get('unless_source') and entry['unless_source'] in r['sources']:
                continue
            return match(entry['rule'], title)
        return False
    return keep


def exclusion(cfg, title):
    rule = cfg['exclusion']
    patterns, match = compile_rules(cfg)
    code = rule['code']
    for name, alt in rule.get('code_if_title_lacks', {}).items():
        if not match(name, title or ''):
            code = alt
    return {'decision': 'exclude', 'code': code, 'by': rule['by']}


def main(subject):
    cfg = topic(subject).get('prefilter')
    if not cfg:
        sys.exit(f'{subject}: no "prefilter" block in topics/{subject}.json')
    base = folder(subject)
    keep = keeper(cfg, base)
    grey, out = [], {}
    records = load(base / 'screening/records.json')['records']
    for r in records:
        if keep(r):
            grey.append(r['id'])
        else:
            out[r['id']] = exclusion(cfg, r['title'])
    save(base / 'screening/titles-prefilter.json', out)
    save(base / 'screening/titles-grey-ids.json', grey)
    by_id = {r['id']: r for r in records}
    chunks = cfg.get('reading_chunks', 4)
    for k in range(chunks):
        with open(base / f'screening/titles-chunk-{k + 1}.tsv', 'w') as f:
            f.write('id\tyear\ttype\ttitle\tdetail\n')
            for i in grey[k::chunks]:
                r = by_id[i]
                f.write('\t'.join(str(r.get(x, '')).replace('\t', ' ').replace('\n', ' ') for x in ('id', 'year', 'type', 'title', 'detail')) + '\n')
    print(f'{len(out)} excluded by the pre-filter, {len(grey)} in the grey zone (dual reading)')


if __name__ == '__main__':
    main(sys.argv[1])
