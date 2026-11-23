# EMET Evidence

**An open-source framework for autonomous, reproducible and auditable evidence synthesis.**

EMET Evidence orchestrates LLM agents and deterministic tools to produce systematic reviews: protocol, searches, dual screening, extraction, risk of bias, GRADE certainty, declarations of interest, claim verification and open data packages. Every number shown to a reader must be traceable to a source passage, every exclusion to a decision, and every critical check must pass before publication.

EMET (אמת) means *truth* in Hebrew.

> **Status: v0.8 (development).** The engine runs the reviews of its first real-world application, [shoulder-surgery.eu](https://shoulder-surgery.eu). Internal checks pass; external scientific validation (benchmarks against Cochrane reviews) is planned for v1.1 and has **not** been performed. Agreement between agents is not accuracy, and open-source code is not clinical validation.

## Principles

- **Full agentic, not full LLM.** Agents orchestrate deterministic tools and may abstain from publishing; LLM compute is reserved for scientific judgement.
- **Extract once, render everywhere.** Structured, verified, sourced data feeds every table, chart and report without new model calls.
- **Evidence before narrative.** The text derives from verified data; it is never the source of truth.
- **Independent verification.** Initial decisions are preserved before adjudication.
- **Fail closed.** A failed critical check or an exhausted budget blocks publication; limits are documented.
- **No silent exclusions, no manufactured precision.** Missing, not assessed, not applicable and uncertain are kept distinct.
- **Open by default.** Code, prompts, schemas, rules, configurations, tests and shareable data are published — never copyrighted full texts, secrets or personal data.

## What is in this repository

| Path | Content |
|---|---|
| `emet/` | The engine (Python ≥ 3.9, standard library only): search, screening, pre-filter, full-text retrieval, effects, cohort overlap, declarations of interest, source and claim verification, structured review migration and validation, P0 rendering, orchestrator, run logs, i18n |
| `methodology/` | The methodological constitution (`METHODOLOGY.md`), the orchestrator (`ORCHESTRATOR.md`, `pipeline.json`), one module per agent (`agents/`), review-depth profiles (`profiles/`), the review schema (`schemas/review.schema.json`) |
| `examples/shoulder-surgery/` | A real example workspace: the review *Should the shoulder be immobilised after rotator cuff repair?* (protocol, structured review, effects, open data package) |
| `tests/` | Deterministic tests (no network), including mutation tests of the integrity checks and a synthetic review |

## Quick start

```sh
git clone https://github.com/emet-evidence/emet-evidence && cd emet-evidence
python3 -m unittest discover -s tests                         # uses the example workspace
EMET_WORKSPACE=examples/shoulder-surgery python3 -m emet.check_review immobilisation
EMET_WORKSPACE=examples/shoulder-surgery python3 -m emet.orchestrate status immobilisation
```

Or install it in the project that publishes the reviews:

```sh
pip install "emet-evidence @ git+https://github.com/emet-evidence/emet-evidence@main"
```

## Workspaces

The engine never stores review data. A **workspace** — the project that publishes reviews — holds:

- `emet.json`: name, default review-depth profile, language, list of topics, and the workspace's own publication and validation commands (substituted in the pipeline as `{publish}` and `{validate}`); for the declarations of interest, the correction channel (`interests.correction_contact`) and the review team with its own declarations (`review_team`);
- `topics/<id>.json`: search folder, published outputs, scripted title pre-filter rules (patterns combined with `all` / `any` / `not`), names of the compared arms for effect extraction;
- `data/`: protocols, searches and screening decisions, cached records, structured reviews (`data/reviews/<id>.json`), run logs.

Commands find the workspace through `EMET_WORKSPACE`, or the nearest parent directory containing `emet.json`. See `examples/shoulder-surgery/`.

```sh
python3 -m emet.orchestrate next <topic>        # next step of a review, with its command or agent module
python3 -m emet.pubmed_cache --manifest data/sources-manifest.json --fulltext   # re-download non-redistributed sources
```

## Languages

The engine is written in English. Text shown to readers is localised through `emet/locales/<lang>.json` (French is complete). Some controlled values stored in existing data are still French and will be normalised.

## Roadmap

v0.8 structured & transparent → v0.9 modular & agentic → v1.0 quantitative synthesis (deterministic statistics, multiverse analysis) → v1.1 scientific validation (benchmark against Cochrane) → v2.0 living evidence.

## Licences

- Code: [Apache License 2.0](LICENSE).
- Methodology (`methodology/`), documentation and data (`examples/`): [CC BY 4.0](LICENSE-CC-BY-4.0).
- Third-party content is not redistributed: abstracts and full texts are listed in `sources-manifest.json` with their identifiers and hashes, to be re-downloaded from PubMed / Europe PMC. Short verbatim quotes in extraction data are kept for verification.

## Citing

See [`CITATION.cff`](CITATION.cff). Methodological lead: Dr Mikaël Chelli.

## Contributing

Issues and pull requests are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md). Report errors in published reviews through the issue tracker.
