# Orchestrator

Version 0.76. The main session (Opus) conducts a review by following `pipeline.json`, the single source of the stages. The orchestrator (`python3 -m emet.orchestrate`) gives its status and the next action:

```sh
python3 -m emet.orchestrate status <topic>
python3 -m emet.orchestrate next <topic> [--profile rapid|standard]
```

A stage is done when all its outputs exist. Stages without a file output (checks) are verified by rerunning their command.

## Roles

| Role | Who | What it does |
|---|---|---|
| Orchestrator | Main session | Reads `next`, runs the scripts, prepares the batches, launches the agents, checks their outputs, commits. Writes the protocol and the page. Never does a reviewer's work itself. |
| Reviewers A and B | Subagents, separate contexts | One module (`agents/*.md`) + the topic instructions + their batch. File reading and writing only, no network. One output file per batch, written in one go. |
| Arbiter | Separate subagent | `agents/arbitration.md`, on disagreements only. |
| Verifier | Subagent | `agents/claim-verification.md`, without knowing the page's conclusions. |
| Scripts | Python, standard library | Collection, deduplication, kappa, flow, provenance, rendering, validation. No model call. |

## Stages

| # | Stage | Type | Module | Main outputs |
|---|---|---|---|---|
| 1 | protocol | session | `agents/protocol.md` | `data/protocols/<topic>.json` (committed alone) |
| 2 | search | scripts + session | `agents/search.md` | raw responses, `consensus.txt` |
| 3 | dedup | script | `agents/screening.md` §1 | `records.json` |
| 4 | prefilter | script | §2 | grey zone / low zone |
| 5 | prefilter-low-zone | agents (single reviewer) | §2 | `prefilter-audit.json` |
| 6 | titles | agents A/B | §3 | `titles-grey-A/B.json` |
| 7 | titles-agreement | script | §6 | `titles-agreement.json` |
| 8 | abstracts | agents A/B + arbiter | §4 | `abstracts-*.json` |
| 9 | eligibility | agents A/B + arbiter | §5 | `fulltext-*.json` |
| 10 | flow | script | §6 | `final.json` |
| 11 | extraction (+ risk of bias) | agents A, partial B, arbiter | `agents/extraction.md`, `agents/risk-of-bias.md` | `extraction-final.json` |
| 12 | grade | agents A/B + arbiter | `agents/grade.md` | `grade-final.json` |
| 13 | writing | session | `agents/writing.md` | `data/question-<topic>.json`, template |
| 14 | verify-sources | script | `agents/claim-verification.md` | — |
| 15 | verify-claims | agents + arbiter | `agents/claim-verification.md` | `data/verification/<topic>/report.json` |
| 16 | validate | script | `METHODOLOGY.md` | — |
| 17 | fiche | session | `agents/writing.md` | PDF, PNG |
| 18 | review-package | script | `schemas/review.schema.json` | `data/reviews/<topic>.json` (`python3 -m emet.migrate_review`, `python3 -m emet.check_review`) |
| 19 | interests-collect | script | `agents/declarations-of-interest.md` | `interests/study-sources.json`, `interests/studies/*.txt` |
| 20 | interests-studies | agents A, partial B, arbiter | `agents/declarations-of-interest.md` | `interests/study-declarations-*.json` |
| 21 | interests-authors-collect | script | `agents/declarations-of-interest.md` | `interests/author-candidates.json`, `interests/author-batches/` |
| 22 | interests-authors | agents A/B + arbiter | `agents/declarations-of-interest.md` | `interests/author-assessment-*.json` |
| 23 | interests-final | script | `agents/declarations-of-interest.md` | `interests/interests-final.json`, section `interests` of `data/reviews/<topic>.json` |
| 24 | run-metadata | script | `METHODOLOGY.md` | tokens per stage |

## Launching agents

- Standard brief: "Working directory … Read `methodology/agents/<module>.md`, `data/protocols/<topic>.json` and `<topic instructions>`. Process the batch `<file>`, reading it in full. Write `<output>` in a single write. Read and Write only; no other file." The model comes from the profile (`profiles/<profile>.json`).
- Batches of about 100 records (screening) or about 10 studies (extraction); at most 20 agents in parallel; stages pipelined rather than run in waves.
- After each batch: check by script that every record has a decision (none lost, none extra) before the next stage.
- A departure from the workflow (stage skipped, rule modified) is a protocol deviation: it is recorded.

## Profiles

`profiles/rapid.json` (rapid profile, chosen by the workspace in `emet.json`: double extraction on 20% + critical outcomes) and `profiles/standard.json` (exhaustive dual independent screening and dual extraction). The Exploratory, Enhanced and Maximum profiles of the roadmap remain to be defined. Scripted checks cannot be disabled.
