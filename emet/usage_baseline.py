#!/usr/bin/env python3
"""Token baseline (EMET roadmap v0.8, section 11.3) rebuilt from Claude Code transcripts.

Reads every *.jsonl transcript of the project (main sessions and subagents), keeps one usage record per
API message (message.id, the transcript repeats it for each content block), and sums tokens by model,
by pipeline stage and by review subject. Stage and subject are inferred from the subagent's first prompt
(keywords); what cannot be attributed is reported as "unattributed", never guessed. Costs are not
computed: no price table is versioned in the repository, and an unknown cost is not a zero cost.

  python3 -m emet.usage_baseline [transcripts_dir] [--json out.json]
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

import os

from emet.workspace import ROOT, topic_ids

# Claude Code transcripts of the project: ~/.claude/projects/<repository path, "/" replaced by "-">, or CLAUDE_TRANSCRIPTS.
DEFAULT_DIR = Path(os.environ.get('CLAUDE_TRANSCRIPTS') or Path.home() / '.claude/projects' / str(ROOT).replace('/', '-'))
FIELDS = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')

# First match wins, checked against the subagent's first prompt. The French keywords (risque de biais, texte intégral,
# résumés, titres, recherche) match the prompts of the existing French-language transcripts.
STAGES = [
    ('claim-verification', r'claim-verification|verify_claims|data/verification'),
    ('page-writing', r'page-rewrite|rewrite-brief|gabarit|template|infographi|fiche'),
    ('grade', r'grade-instructions|grade-addendum|\bGRADE\b'),
    ('extraction-rob', r'extraction|risk of bias|risque de biais|RoB'),
    ('eligibility', r'eligibility|fulltext|texte intégral'),
    ('abstracts', r'abstracts?-|résumés'),
    ('titles', r'titles?-|titres'),
    ('search', r'search|recherche|esearch|consensus'),
]
SUBJECTS = topic_ids()


def first_prompt(path):
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get('type') == 'user':
                content = rec.get('message', {}).get('content')
                if isinstance(content, list):
                    content = ' '.join(c.get('text', '') for c in content if isinstance(c, dict))
                return content or ''
    return ''


def classify(prompt):
    stage = next((name for name, rx in STAGES if re.search(rx, prompt, re.I)), 'unattributed')
    hits = [s for s in SUBJECTS if s in prompt]
    subject = hits[0] if len(hits) == 1 else ('multiple' if hits else 'unattributed')
    return stage, subject


def usages(path):
    seen = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get('message') or {}
            if rec.get('type') != 'assistant' or 'usage' not in msg:
                continue
            seen[msg.get('id') or rec.get('uuid')] = (msg.get('model', 'unknown'), msg['usage'],
                                                       rec.get('timestamp', ''))
    return seen.values()


def add(bucket, usage):
    for k in FIELDS:
        bucket[k] += usage.get(k) or 0
    bucket['messages'] += 1


def main():
    argv = sys.argv[1:]
    out = None
    if '--json' in argv:
        i = argv.index('--json')
        out = argv[i + 1]
        del argv[i:i + 2]
    root = Path(argv[0]) if argv else DEFAULT_DIR
    new = lambda: defaultdict(int)
    by_model, by_stage, by_subject = defaultdict(new), defaultdict(new), defaultdict(new)
    total, dates, n_main, n_sub = new(), [], 0, 0
    for path in root.rglob('*.jsonl'):
        is_sub = 'subagents' in path.parts
        if is_sub:
            n_sub += 1
            stage, subject = classify(first_prompt(path))
        else:
            n_main += 1
            stage, subject = 'main-session (orchestration, writing)', 'unattributed'
        for model, usage, ts in usages(path):
            if model == '<synthetic>':
                continue
            for b in (total, by_model[model], by_stage[stage], by_subject[subject]):
                add(b, usage)
            if ts:
                dates.append(ts[:10])
    report = {'transcripts_dir': root.name, 'main_sessions': n_main, 'subagents': n_sub,
              'period': [min(dates), max(dates)] if dates else None, 'cost_usd': None,
              'total': total, 'by_model': by_model, 'by_stage': by_stage, 'by_subject': by_subject}
    if out:
        Path(out).write_text(json.dumps(report, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    fmt = lambda b: (f"{b['messages']:>7} msg  in {b['input_tokens']/1e6:8.2f}M  cache-write "
                     f"{b['cache_creation_input_tokens']/1e6:8.2f}M  cache-read {b['cache_read_input_tokens']/1e6:9.2f}M  "
                     f"out {b['output_tokens']/1e6:7.2f}M")
    print(f"{n_main} main sessions, {n_sub} subagents, period {report['period']}")
    print('TOTAL'.ljust(40), fmt(total))
    for title, group in (('model', by_model), ('stage', by_stage), ('subject', by_subject)):
        print(f'\n-- by {title}')
        for k, b in sorted(group.items(), key=lambda kv: -kv[1]['output_tokens']):
            print(k[:40].ljust(40), fmt(b))


if __name__ == '__main__':
    main()
