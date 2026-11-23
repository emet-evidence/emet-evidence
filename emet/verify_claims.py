#!/usr/bin/env python3
"""Stage 2 of source verification: is each cited claim supported by its source?

Subcommands:
  extract <page>   splits the page into cited claims (sentence segment + references) and prepares
                   verification batches (each source read once per batch) for the (claim, reference)
                   pairs without a valid verdict only.
  check <page>     checks the verdicts returned by the verifier agents: every favourable verdict must
                   quote word for word a passage of the archived source (otherwise it is rejected);
                   writes the report and lists the pairs to arbitrate. Exit code 1 if the page is not validated.

Files (data/verification/<page>/):
  claims.json       extracted claims (id = hash of the segment, the sentence and the references);
  batches/<n>.json  batches to verify; verdicts/<n>.json  raw verdicts of the agents;
  arbitration.json  arbitration decisions on the blocking pairs; report.json  final report.
Agent instructions: data/protocols/claim-verification-instructions.md.
"""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

from emet.i18n import _
from emet.workspace import ROOT, config, outputs

PAGES = outputs()
from emet.verify_sources import normalise, source_text  # noqa: E402

BLOCKS = {'p', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'figcaption', 'caption', 'dd', 'dt', 'blockquote', 'td', 'th'}
# Page sections not subject to verification (emet.json, claim_verification.skip_sections): bibliography, data.
SKIPPED_SECTIONS = set(config().get('claim_verification', {}).get('skip_sections', ['sources']))
# Verdict names written by the verifier agents in verdicts/<n>.json (methodology/agents/claim-verification.md):
# data values, kept as is. Fixed order of the reports.
VERDICTS = ('soutient', 'soutient en partie', 'ne soutient pas', 'contredit', 'source illisible')
FAVOURABLE = {'soutient', 'soutient en partie'}
BLOCKING = {'ne soutient pas', 'contredit', 'source illisible'}
VALID = 'valid'  # pair_status of a valid verdict (internal, never written)
BATCH_SOURCES = 6
CACHE = ROOT/'data/verification/.sources'


class Claims(HTMLParser):
    """Text stream per block, with citation markers; ignores the bibliography."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.text, self.refs = [], [], []
        self.section, self.depth, self.skip_depth = None, 0, None
        self.in_cite = False
        self.row_ref = None
        self.stack = []

    def flush(self):
        text = ''.join(self.text)
        if re.search(r'\[\[R\d+\]\]', text) or self.row_ref:
            self.blocks.append({'section': self.section, 'text': re.sub(r'\s+', ' ', text).strip(), 'row': self.row_ref})
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section':
            self.section = attrs.get('id', self.section)
        if self.skip_depth is not None:
            self.stack.append(tag)
            return
        if tag == 'section' and attrs.get('id') in SKIPPED_SECTIONS:
            self.skip_depth = len(self.stack)
        self.stack.append(tag)
        if tag in ('script', 'style'):
            self.skip_depth = len(self.stack) - 1
        if tag == 'tr':
            self.flush()
            self.row_ref = attrs.get('data-study')
            return
        if self.row_ref:  # study row: a single block until </tr>, cells and lists separated
            self.text.append(' | ' if tag in ('td', 'th') else ' ' if tag in BLOCKS or tag == 'br' else '')
        elif tag in BLOCKS:
            self.flush()
        href = attrs.get('href', '')
        if tag == 'a' and re.fullmatch(r'#R\d+', href) and not self.row_ref:
            self.text.append(f' [[{href[1:]}]] ')
            self.in_cite = True

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()
        if self.skip_depth is not None:
            if len(self.stack) <= self.skip_depth:
                self.skip_depth = None
            return
        if tag == 'a':
            self.in_cite = False
        if tag == 'tr':
            self.flush()
            self.row_ref = None
        elif tag in BLOCKS and not self.row_ref:
            self.flush()

    def handle_data(self, data):
        if self.skip_depth is None and not self.in_cite:
            self.text.append(data)


SENTENCE_END = re.compile(r'(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ«(])')
MARKERS = re.compile(r'(?:\s*\[\[R\d+\]\])+')


def claim_id(segment, sentence, references):
    return hashlib.sha1(f'{segment}\x1f{sentence}\x1f{",".join(references)}'.encode()).hexdigest()[:12]


def extract_claims(page_html):
    parser = Claims()
    parser.feed(page_html)
    parser.flush()
    claims = []
    for block in parser.blocks:
        if block['row']:
            # Row of a study table: the whole row is attributed to the row's study. The claim kinds ('ligne de tableau',
            # 'texte') are data values named in the agent instructions (methodology/agents/claim-verification.md).
            text = re.sub(r'\s*\[\[R\d+\]\]', '', block['text']).strip(' |')
            claims.append({'section': block['section'], 'kind': 'ligne de tableau', 'segment': text, 'sentence': text,
                           'references': [block['row']]})
            continue
        # A citation covers all the text before it since the previous citation of the same block
        # (several sentences if the reference is only cited at the end of a paragraph or cell).
        text = block['text']
        whole = MARKERS.sub('', text).strip()
        start = 0
        for match in MARKERS.finditer(text):
            segment = text[start:match.start()].strip(' ;,:.')
            references = re.findall(r'R\d+', match.group())
            if not re.search(r'\w', segment):  # citation at the start of the block: the whole block
                segment = whole
            sentences = SENTENCE_END.split(text[:match.start()])
            context = sentences[-1].strip() if sentences else segment
            if len(context) < 40 or context == segment:
                context = whole
            claims.append({'section': block['section'], 'kind': 'texte', 'segment': segment, 'sentence': context,
                           'references': references})
            start = match.end()
    for claim in claims:
        claim['id'] = claim_id(claim['segment'], claim['sentence'], claim['references'])
    unique = {}
    for claim in claims:
        unique.setdefault(claim['id'], claim)
    return list(unique.values())


def paths(name):
    folder = ROOT/'data/verification'/name
    return {'folder': folder, 'claims': folder/'claims.json', 'batches': folder/'batches', 'verdicts': folder/'verdicts',
            'arbitration': folder/'arbitration.json', 'report': folder/'report.json'}


def page_context(name):
    config = PAGES[name]
    data = json.loads((ROOT/config['data']).read_text())
    reference_map = json.loads((ROOT/config['references']).read_text())
    page = (ROOT/config['page']).read_text()
    return config, data, reference_map, page


def cached_source(identifier):
    """Archived text of a source, written to a local (unversioned) cache that the agent reads."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE/(re.sub(r'[^\w.-]', '_', identifier) + '.txt')
    if not path.exists():
        path.write_text(source_text(identifier, None))
    return path


def load_verdicts(p):
    verdicts = {}
    for path in sorted(p['verdicts'].glob('*.json')) if p['verdicts'].exists() else []:
        for item in json.loads(path.read_text()):
            verdicts[(item['claim'], item['reference'])] = item | {'file': path.name}
    return verdicts


def quote_found(quote, source):
    squash = lambda text: re.sub(r'[^\w%.,<>=±-]+', ' ', normalise(text)).lower().strip()  # noqa: E731
    return bool(quote.strip()) and squash(quote) in squash(source)


def pair_status(item, source):
    """Validates a raw verdict: known verdict; every favourable verdict rests on exact quotes. Returns VALID or the problem."""
    if item.get('verdict') not in VERDICTS:
        return _('invalid verdict')
    if item['verdict'] in FAVOURABLE:
        quotes = item.get('quotes') or []
        if not quotes:
            return _('missing quote')
        missing = [q for q in quotes if not quote_found(q, source)]
        if missing:
            return _('quote not found in the source')
    return VALID


def extract(name):
    p = paths(name)
    config, data, reference_map, page = page_context(name)
    static = set(data.get('static_references', {})) - set(data['studies'])
    context = set(data.get('context_references', []))
    claims = extract_claims(page)
    p['folder'].mkdir(parents=True, exist_ok=True)
    p['claims'].write_text(json.dumps(claims, ensure_ascii=False, indent=1))
    verdicts = load_verdicts(p)
    todo, excluded = {}, 0
    for claim in claims:
        for reference in claim['references']:
            if reference in context or (reference in static and reference_map.get(reference) in ('static', None)):
                excluded += 1  # methodological documentation: not a source of evidence
                continue
            known = verdicts.get((claim['id'], reference))
            source = source_text(reference_map[reference], None)
            if known and pair_status(known, source) == VALID:
                continue
            todo.setdefault(reference, []).append(claim)
    if p['batches'].exists():
        for old in p['batches'].glob('*.json'):
            old.unlink()
    p['batches'].mkdir(exist_ok=True)
    references = sorted(todo, key=lambda r: int(r[1:]))
    batches = [references[i:i + BATCH_SOURCES] for i in range(0, len(references), BATCH_SOURCES)]
    stamp = len(list(p['verdicts'].glob('*.json'))) if p['verdicts'].exists() else 0
    for number, group in enumerate(batches, 1):
        batch = {'page': name, 'question': data['question'] if isinstance(data['question'], str) else data['question'].get('text', ''),
                 'output': str((p['verdicts']/f'{stamp + number:03d}.json').relative_to(ROOT)), 'sources': []}
        for reference in group:
            identifier = reference_map[reference]
            batch['sources'].append({'reference': reference, 'identifier': identifier,
                                     'path': str(cached_source(identifier).relative_to(ROOT)),
                                     'claims': [{'claim': c['id'], 'kind': c['kind'], 'segment': c['segment'], 'sentence': c['sentence'],
                                                 'cited_with': [r for r in c['references'] if r != reference]} for c in todo[reference]]})
        (p['batches']/f'{number:03d}.json').write_text(json.dumps(batch, ensure_ascii=False, indent=1))
    pairs = sum(len(v) for v in todo.values())
    print(f'{name}: {len(claims)} cited claims, {pairs} pairs to verify in {len(batches)} batches '
          f'({excluded} documentation citations excluded) → {p["batches"].relative_to(ROOT)}')


def check(name, quiet=False):
    p = paths(name)
    config, data, reference_map, page = page_context(name)
    static = set(data.get('static_references', {})) - set(data['studies'])
    context = set(data.get('context_references', []))
    current = {c['id']: c for c in extract_claims(page)}
    verdicts = load_verdicts(p)
    arbitration = json.loads(p['arbitration'].read_text()) if p['arbitration'].exists() else {}
    counts = {v: 0 for v in VERDICTS}
    missing, invalid, blocking, partial, sources = [], [], [], [], {}
    for claim in current.values():
        for reference in claim['references']:
            if reference in context or (reference in static and reference_map.get(reference) in ('static', None)):
                continue
            key = (claim['id'], reference)
            if reference not in sources:
                sources[reference] = source_text(reference_map[reference], None)
            item = verdicts.get(key)
            if not item:
                missing.append(key)
                continue
            status = pair_status(item, sources[reference])
            if status != VALID:
                invalid.append({'claim': claim['id'], 'reference': reference, 'problem': status, 'file': item['file']})
                continue
            counts[item['verdict']] += 1
            entry = {'claim': claim['id'], 'reference': reference, 'section': claim['section'], 'segment': claim['segment'],
                     'verdict': item['verdict'], 'comment': item.get('comment', '')}
            if item['verdict'] in BLOCKING:
                decision = arbitration.get(f'{claim["id"]}|{reference}')
                entry['arbitration'] = decision
                if not decision or decision.get('decision') != 'faux positif':  # arbitration value (data)
                    blocking.append(entry)
            elif item['verdict'] == 'soutient en partie':
                partial.append(entry)
    stale = sorted({c for c, _ref in verdicts} - set(current))
    passed = not missing and not invalid and not blocking
    report = {'page': name, 'claims': len(current), 'pairs': sum(counts.values()) + len(missing) + len(invalid),
              'verdicts': counts, 'missing': len(missing), 'invalid': invalid, 'blocking': blocking,
              'partial': partial, 'arbitrated': len(arbitration), 'stale_verdicts': len(stale), 'passed': passed}
    p['folder'].mkdir(parents=True, exist_ok=True)
    p['report'].write_text(json.dumps(report, ensure_ascii=False, indent=1))
    if not quiet:
        print(f'{"OK" if passed else "FAILED"} {name}: {len(current)} claims, {report["pairs"]} pairs; '
              + ', '.join(f'{k} {v}' for k, v in counts.items() if v)
              + f'; without verdict {len(missing)}, rejected verdicts {len(invalid)}, blocking not arbitrated {len(blocking)}')
        for entry in blocking:
            print(f'    [{entry["verdict"]}] {entry["reference"]} "{entry["segment"][:140]}" — {entry["comment"][:160]}')
        for entry in invalid[:20]:
            print(f'    [rejected: {entry["problem"]}] {entry["reference"]} {entry["claim"]} ({entry["file"]})')
    return passed


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('extract', 'check'):
        print(__doc__)
        sys.exit(2)
    names = list(PAGES) if sys.argv[2] == 'all' else sys.argv[2:]
    ok = True
    for name in names:
        if sys.argv[1] == 'extract':
            extract(name)
        else:
            ok &= check(name)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
