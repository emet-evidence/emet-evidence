#!/usr/bin/env python3
"""Review orchestrator (methodology v0.71): status and next stage of a topic.

Stages are defined once in methodology/pipeline.json. A stage is "done" when all its outputs exist.
`next` shows the first stage not done: the command to run (script), or the instructions to launch the
agents (module, topic-specific instructions, profile models). The orchestrator does not launch the agents
itself: the main session launches them in separate contexts.

  python3 -m emet.orchestrate status <topic>
  python3 -m emet.orchestrate next <topic> [--profile rapid]

Duration and tokens per stage: wrap each stage in `scripts/run_log.py start|end <topic> <stage>`, then
`run_log.py report <topic>`; `next` refuses to continue if the profile budget is exceeded.
"""
import glob, json, sys
from pathlib import Path

from emet.workspace import ROOT, METHODOLOGY, config, search_folder, topic
METHOD = METHODOLOGY


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def profile(name):
    p = load(METHOD / 'profiles' / f'{name}.json')
    if 'inherits' in p:
        base = profile(p['inherits'])
        for k, v in p.items():
            base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
        p = base
    return p


def folders(subject):
    try:
        d = search_folder(subject).relative_to(ROOT).as_posix()
    except SystemExit:
        d = f'data/searches/{subject}-<date>'
    names = {'s': subject, 'D': d, 'S': f'{d}/screening'}
    # Workspace-specific outputs and commands (emet.json, topics/<id>.json): page data, publication, validation.
    cfg, outputs = config(), {}
    try:
        outputs = topic(subject).get('outputs', {})
    except SystemExit:
        pass
    names.update(page_data=outputs.get('data', '<outputs.data>'), page_references=outputs.get('references', '<outputs.references>'),
                 summary_sheet_outputs=cfg.get('outputs', {}).get('summary_sheet', '<outputs.summary_sheet>'))
    for key in ('publish', 'validate', 'summary_sheet'):
        names[key] = cfg.get('commands', {}).get(key, f'<commands.{key}>').format(**names)
    return names


def done(stage, names):
    outs = [o.format(**names) for o in stage['outputs']]
    return bool(outs) and all(glob.glob(str(ROOT / o)) for o in outs), outs


def get(d, dotted):
    for k in dotted.split('.'):
        d = d.get(k, {}) if isinstance(d, dict) else {}
    return d


def describe(stage, names, prof):
    lines = [f"[{stage['id']}] {stage['kind']} — module methodology/{stage['module']}"]
    if stage.get('run'):
        lines.append('  command: ' + stage['run'].format(**names))
    if stage.get('do'):
        lines.append('  to do:   ' + stage['do'].format(**names))
    if stage.get('profile_key'):
        lines.append(f"  models ({prof['profile']}): " + json.dumps(get(prof, stage['profile_key']), ensure_ascii=False))
    extra = sorted(p.name for p in (ROOT / 'data/protocols').glob(f"*-{names['s']}.md"))
    if stage['kind'] == 'agents' and extra:
        lines.append('  topic instructions: ' + ', '.join(extra))
    return '\n'.join(lines)


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('status', 'next'):
        sys.exit(__doc__)
    command, subject = sys.argv[1], sys.argv[2]
    prof = profile(sys.argv[sys.argv.index('--profile') + 1] if '--profile' in sys.argv else config().get('profile', 'rapid'))
    names = folders(subject)
    stages = load(METHOD / 'pipeline.json')['stages']
    meta = ROOT / f'data/runs/{subject}-run-metadata.json'
    budget = prof.get('budget', {}).get('max_output_tokens')
    if command == 'next' and meta.exists() and budget:
        used = load(meta).get('output_tokens_total', 0)
        if used > budget:
            print(f'BLOCKED: budget of profile {prof["profile"]} exceeded ({used:,} > {budget:,} output tokens). '
                  'Explicit decision required: raise the budget, change profile (and declare it), or abstain. No silent reduction.')
            return
        print(f'Budget: {used:,} / {budget:,} output tokens ({prof["profile"]})')
    for stage in stages:
        ok, outs = done(stage, names)
        if command == 'status':
            mark = 'done' if ok else ('to check' if not outs else 'to do')
            print(f"{mark:11} {stage['id']:20} {stage['kind']:15} {', '.join(outs)}")
        elif not ok:
            print(describe(stage, names, prof))
            if not outs:
                print('  (no file output: rerun the command to check)')
                continue
            return


if __name__ == '__main__':
    main()
