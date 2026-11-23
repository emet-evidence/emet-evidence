#!/usr/bin/env python3
"""Run log of a review (EMET v0.8, §5.5–5.6): duration and tokens per stage, measured during the work.

The orchestrator marks the start and end of each stage; `report` assigns to the stages the API responses
recorded in the Claude Code transcripts whose timestamp falls within the stage window and whose session
(subagent) mentions the topic, or that come from the main session. The profile budget is checked: an overrun
is reported and blocks the next stage (`orchestrate.py next`), without silently reducing the profile.

  python3 -m emet.run_log start <topic> extraction [--profile rapid]
  python3 -m emet.run_log end <topic> extraction
  python3 -m emet.run_log report <topic>
"""
import json, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from emet import usage_baseline as ub

from emet.i18n import _
from emet.workspace import ROOT, METHODOLOGY
RUNS = ROOT / 'data/runs'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def log(subject, event, stage, profile=None):
    RUNS.mkdir(parents=True, exist_ok=True)
    entry = {'at': now(), 'event': event, 'stage': stage}
    if profile:
        entry['profile'] = profile
    with open(RUNS / f'{subject}.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    print(json.dumps(entry, ensure_ascii=False))


def windows(subject):
    path = RUNS / f'{subject}.jsonl'
    if not path.exists():
        return [], None
    events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    open_, out, profile = {}, [], None
    for e in events:
        profile = e.get('profile', profile)
        if e['event'] == 'start':
            open_[e['stage']] = e['at']
        elif e['event'] == 'end' and e['stage'] in open_:
            out.append((e['stage'], open_.pop(e['stage']), e['at']))
    out += [(stage, start, None) for stage, start in open_.items()]
    return out, profile


def report(subject, transcripts=ub.DEFAULT_DIR):
    wins, profile = windows(subject)
    stages = {}
    for stage, start, end in wins:
        s = stages.setdefault(stage, {'windows': [], 'duration_seconds': 0, 'tokens': defaultdict(lambda: defaultdict(int))})
        s['windows'].append([start, end])
        if end:
            s['duration_seconds'] += int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    for path in Path(transcripts).rglob('*.jsonl'):
        is_sub = 'subagents' in path.parts
        if is_sub and subject not in ub.first_prompt(path):
            continue
        for model, usage, ts in ub.usages(path):
            if not ts or model == '<synthetic>':
                continue
            t = datetime.fromisoformat(ts.replace('Z', '+00:00')).isoformat(timespec='seconds')
            for stage, start, end in wins:
                if start <= t and (end is None or t <= end):
                    bucket = stages[stage]['tokens'][model]
                    for k in ub.FIELDS:
                        bucket[k] += usage.get(k) or 0
                    bucket['messages'] += 1
                    bucket['subagent_messages' if is_sub else 'main_messages'] += 1
                    break
    budget = None
    if profile:
        budget = json.loads((METHODOLOGY / f'profiles/{profile}.json').read_text(encoding='utf-8')).get('budget', {}).get('max_output_tokens')
    total_out = sum(b['output_tokens'] for s in stages.values() for b in s['tokens'].values())
    meta = {'subject': subject, 'profile': profile, 'generated_at': now(),
            'method': _('start/end windows of the log; API responses of the transcripts timestamped within the window (subagents mentioning the topic, and main session)'),
            'stages': {k: {'windows': v['windows'], 'duration_seconds': v['duration_seconds'], 'tokens': {m: dict(b) for m, b in v['tokens'].items()}}
                       for k, v in stages.items()},
            'output_tokens_total': total_out, 'budget_max_output_tokens': budget,
            'over_budget': bool(budget and total_out > budget), 'cost_usd': None}
    out = RUNS / f'{subject}-run-metadata.json'
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{out.relative_to(ROOT)}: {len(stages)} stages, {total_out:,} output tokens' + (' — BUDGET EXCEEDED' if meta['over_budget'] else ''))
    return meta


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    profile = sys.argv[sys.argv.index('--profile') + 1] if '--profile' in sys.argv else None
    if profile:
        args.remove(profile)
    if len(args) >= 3 and args[0] in ('start', 'end'):
        log(args[1], args[0], args[2], profile)
    elif len(args) == 2 and args[0] == 'report':
        report(args[1])
    else:
        sys.exit(__doc__)
