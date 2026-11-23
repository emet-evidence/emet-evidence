#!/usr/bin/env python3
"""Stage 1 of source verification: checks every provenance number against the archived text.

For each study of a page, every number of `provenance[].value` must appear in the archived text of the
source (eligibility file, PubMed record, PMC full text). A value calculated by the extractor (derived
percentage, sum…) must carry `"derived": "<calculation>"`: its operands are then searched for in the
source instead. If the entry carries a `quote` (exact quotation of the passage, in English), the quote
must be found as is in the source. A number written differently in the source ("a patient", "stage III",
"no subjects") carries `"source_form": "<exact form>"`; a number read in another archived source carries
`"source_id"`.

Usage: verify_sources.py [page …] [--report]
Output: list of numbers not found; exit code 1 if there are any (blocks publication).
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import html
import json
from pathlib import Path
import re
import sys

from emet.workspace import ROOT, outputs

PAGES = outputs()

# Thousands separators: "21,341", "21 341", "21 341".
THOUSANDS = re.compile(r'(?<=\d)[,    ](?=\d{3}(?!\d))')
NUMBER = re.compile(r'(?<![\d.])\d+(?:\.\d+)?')
# Years, 95% CI, outcome (O1…), table and reference numbers: not data. The French forms (« IC à 95 % »,
# « tableau 2 ») match the provenance values written in French in the page data.
IGNORED = re.compile(r'IC (?:à )?95 ?%|95 ?% ?CI|\b[ORDE]\d+\b|tableau \d+|table \d+', re.I)


def canonical(token):
    try:
        value = Decimal(token).normalize()
    except InvalidOperation:
        return token
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def normalise(text):
    text = html.unescape(re.sub(r'</?[A-Za-z][\w:-]*(?:\s[^<>]*)?/?>', ' ', text))
    text = text.replace('−', '-').replace('·', '.')
    text = re.sub(r'(?<![\d])\.(\d)', r'0.\1', text)          # "P = .001" → 0.001
    text = THOUSANDS.sub('', text)
    text = re.sub(r'(?<=\d),(?=\d)', '.', text)               # decimal comma
    return text


def numbers(text):
    """Provenance value written in French: space = thousands, comma = decimal."""
    text = html.unescape(IGNORED.sub(' ', text)).replace('−', '-')
    text = re.sub(r'(?<=\d)[    ](?=\d{3}(?!\d))', '', text)
    text = re.sub(r'(?<=\d),(?=\d)', '.', text)
    text = re.sub(r'(?<![\d])\.(\d)', r'0.\1', text)
    return [canonical(n) for n in NUMBER.findall(text)]


def readings(text):
    """Possible readings of a provenance value ("3,430" written the English way: 3.43 or 3430)."""
    first = numbers(text)
    alternative = numbers(re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', text))
    return first, alternative


def present(number, found):
    """Number present as is, as proportion ↔ percentage (0.092 ↔ 9.2%), or as a rounding of a source decimal."""
    if number in found:
        return True
    value = Decimal(number)
    if any(canonical(str(v)) in found for v in (value / 100, value * 100)):
        return True
    decimals = len(number.split('.')[1]) if '.' in number else 0
    if not decimals:  # never round an integer
        return False
    step = Decimal(1).scaleb(-decimals)
    return any(Decimal(n).quantize(step, rounding=ROUND_HALF_UP) == value
               for n in found if '.' in n and len(n.split('.')[1]) > decimals)


def source_numbers(raw):
    """Numbers of the source under every convention: thousands comma (English), decimal comma
    (European sources, "-0,215"), raw digit sequences ("F(1,212)"), numbers written in words."""
    text = normalise(raw)
    found = {canonical(n) for n in NUMBER.findall(text)}
    european = html.unescape(raw).replace('\u2212', '-')
    european = re.sub(r'(?<=\d),(?=\d)', '.', european)
    found |= {canonical(n) for n in NUMBER.findall(european)}
    found |= {canonical(n) for n in re.findall(r'\d+', raw)}
    return found | word_numbers(raw)


ARITHMETIC = re.compile(r'^[\d\s.,+\-\u2212×x*/()]+$')


def evaluate(expression):
    """Evaluates a declared calculation ("9903 - 13", "100 − 64", "171/206"); None if it is not purely arithmetic."""
    expression = expression.split('=')[0].strip()
    if not ARITHMETIC.match(expression) or not re.search(r'\d', expression):
        return None
    python = re.sub(r'(?<=\d)[\u00a0\u202f\u2009 ](?=\d{3}(?!\d))', '', expression)
    python = python.replace(',', '.').replace('\u2212', '-').replace('×', '*').replace('x', '*')
    try:
        return Decimal(str(eval(python, {'__builtins__': {}})))  # noqa: S307 — expression filtered by ARITHMETIC
    except Exception:
        return None


UNITS = {w: i for i, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen '
                                     'fifteen sixteen seventeen eighteen nineteen'.split())}
TENS = {w: 10 * i for i, w in enumerate('twenty thirty forty fifty sixty seventy eighty ninety'.split(), 2)}
SCALES = {'hundred': 100, 'thousand': 1000}
WORD = re.compile(r'\b(?:(?:%s)(?:fold)?\b(?:[\s-]+(?:and[\s-]+)?)?)+' % '|'.join(sorted([*TENS, *UNITS, *SCALES], key=len, reverse=True)), re.I)


def word_numbers(text):
    """Numbers written in words in the source ("Thirty consecutive patients", "eighty-two")."""
    values = set()
    for match in WORD.finditer(text):
        total = current = 0
        for word in re.findall(r'[a-z]+', match.group().lower()):
            if word in UNITS:
                current += UNITS[word]
            elif word in TENS:
                current += TENS[word]
            elif word == 'hundred':
                current = max(current, 1) * 100
            elif word == 'thousand':
                total += max(current, 1) * 1000
                current = 0
        values.add(str(total + current))
    return values


def registry_record(nct):
    """ClinicalTrials.gov record archived during the search (API v2 responses of each folder)."""
    def walk(node):
        if isinstance(node, dict):
            if node.get('protocolSection', {}).get('identificationModule', {}).get('nctId') == nct:
                return node
            nodes = node.values()
        elif isinstance(node, list):
            nodes = node
        elif isinstance(node, str) and nct in node and node.lstrip().startswith('{'):
            try:
                return walk(json.loads(node))
            except ValueError:
                return None
        else:
            return None
        for child in nodes:
            found = walk(child)
            if found:
                return found
    for path in (ROOT/'data/searches').glob('*/ctgov*.json'):
        if nct in path.read_text():
            record = walk(json.loads(path.read_text()))
            if record:
                return json.dumps(record, ensure_ascii=False)
    return ''


def source_text(identifier, searches):
    """All the archived text available for a source (PMID, CONS:…, EPMC:…, NCT… identifier)."""
    parts = []
    stem = identifier.replace(':', '_')
    for path in sorted([*(ROOT/'data/searches').glob(f'*/screening/eligibility/{stem}.txt'), *(ROOT/'data/searches').glob(f'*/screening/eligibility/{stem}-*.txt')]):
        parts.append(path.read_text())
    article = ROOT/f'data/articles/{identifier}.json'
    if article.exists():
        record = json.loads(article.read_text())
        parts.append(record.get('title', '') + '\n' + json.dumps(record.get('abstract', ''), ensure_ascii=False))
        pmcid = (record.get('identifiers') or {}).get('pmc') or (record.get('identifiers') or {}).get('pmcid')
        if pmcid and (ROOT/f'data/fulltext/{pmcid}.json').exists():
            parts.append(json.loads((ROOT/f'data/fulltext/{pmcid}.json').read_text())['raw_xml'])
    if identifier.startswith('NCT'):
        parts.append(registry_record(identifier))
    return '\n'.join(parts)


def check_page(name):
    config = PAGES[name]
    data = json.loads((ROOT/config['data']).read_text())
    reference_map = json.loads((ROOT/config['references']).read_text())
    problems, checked, derived, missing_source = [], 0, 0, []
    for reference, study in data['studies'].items():
        identifier = reference_map[reference]
        raw = source_text(identifier, config['searches'])
        if not raw.strip():
            missing_source.append(f'{reference} ({identifier})')
            continue
        found = source_numbers(raw)
        flat = re.sub(r'\s+', ' ', normalise(raw)).lower()
        for item in study['provenance']:
            if item.get('quote'):
                quote = re.sub(r'\s+', ' ', normalise(item['quote'])).lower()
                if quote not in flat:
                    problems.append(f'{reference} ({identifier}): quote not found "{item["quote"][:80]}"')
            if item.get('source_id'):
                # Number read in another archived source (twin publication, linked record).
                other = source_text(item['source_id'], None)
                item_found, item_flat = source_numbers(other), re.sub(r'\s+', ' ', normalise(other)).lower()
            else:
                item_found, item_flat = found, flat
            if item.get('source_form'):
                # Number written in words or in Roman numerals in the source: the form must be found there word for word.
                checked += 1
                form = re.sub(r'\s+', ' ', normalise(item['source_form'])).lower()
                if form not in item_flat:
                    problems.append(f'{reference} ({identifier}): form "{item["source_form"]}" not found in the source')
                continue
            calculation = item.get('derived')
            if not calculation and re.search(r'calcul', f"{item.get('what', '')} {item.get('location', '')}", re.I) and re.search(r'\d', item.get('what', '')):
                # Old format: the calculation is described in "what" (French word « calcul »); its operands appear there.
                calculation = item.get('what', '')
            if calculation:
                derived += 1
                operands = numbers(calculation)
                absent = [n for n in operands if n != '100' and not present(n, item_found)]
                if not operands:
                    problems.append(f'{reference} ({identifier}): calculation without verifiable operands "{calculation}"')
                elif absent:
                    problems.append(f'{reference} ({identifier}): operands {absent} of the calculation "{calculation}" missing from the source')
                elif item.get('derived'):
                    result = evaluate(item['derived'])
                    target = numbers(item['value'])
                    if result is not None and target and abs(result - Decimal(target[0])) > Decimal('0.051') * max(1, abs(result)) / 10:
                        problems.append(f'{reference} ({identifier}): calculation "{item["derived"]}" = {result:.4g}, declared value {item["value"]}')
                continue
            # Explicit calculation in "what" ("23 + 60", "100 − 64"): its operands are also accepted.
            arithmetic = re.findall(r'\d+(?:[.,]\d+)?\s*[+\u2212×/-]\s*\d+(?:[.,]\d+)?(?:\s*[+\u2212×/-]\s*\d+(?:[.,]\d+)?)*', item.get('what', ''))
            operands_ok = arithmetic and all(n == '100' or present(n, item_found) for expr in arithmetic for n in numbers(expr))
            first, alternative = readings(item['value'])
            if not all(present(n, item_found) for n in first) and all(present(n, item_found) for n in alternative):
                first = alternative
            for number in first:
                checked += 1
                if not present(number, item_found) and not operands_ok:
                    problems.append(f'{reference} ({identifier}): "{item["value"]}" ({item.get("what", "")}, {item.get("location", "")}) — {number} missing from the source')
    return problems, checked, derived, missing_source


def main():
    names = [a for a in sys.argv[1:] if not a.startswith('--')] or list(PAGES)
    report = {}
    failed = False
    for name in names:
        problems, checked, derived, missing_source = check_page(name)
        report[name] = {'checked': checked, 'derived': derived, 'not_found': problems, 'no_archived_source': missing_source}
        status = 'OK' if not problems and not missing_source else 'FAILED'
        failed |= status == 'FAILED'
        print(f'{status} {name}: {checked} numbers checked against the source, {derived} calculated, '
              f'{len(problems)} not found, {len(missing_source)} sources not archived')
        for line in problems[:200]:
            print('   ', line)
        for line in missing_source:
            print('    source not archived:', line)
    if '--report' in sys.argv:
        out = ROOT/'data/verification/stage1.json'
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
