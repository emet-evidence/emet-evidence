# EMET Evidence — notes for Claude sessions

Open-source framework for autonomous, reproducible and auditable evidence synthesis (systematic reviews run by LLM agents orchestrating deterministic tools). Methodological lead: Dr Mikaël Chelli. Public repository: https://github.com/emet-evidence/emet-evidence.

## Settled decisions (do not reopen)

- Licences: code Apache 2.0 (`LICENSE`); methodology, documentation and data CC BY 4.0 (`LICENSE-CC-BY-4.0`). Copyright: "Mikaël Chelli and EMET Evidence contributors".
- The repository is public: never commit secrets, personal data, local absolute paths, or copyrighted third-party content (abstracts, full texts). Reference sources by identifier and hash (`sources-manifest.json`); short verbatim quotes in extraction data are allowed for verification.
- Language: code, comments, console messages, docs and `methodology/` in English (`methodology/` is the single reference version). Text shown to readers goes through `emet.i18n._()` with translations in `emet/locales/<lang>.json`; French must stay complete (`tests/test_i18n.py`).
- Some controlled values stored in existing data are still French (verdicts, GRADE levels, access levels, risk-of-bias judgements, eligibility-file headers). Keep them as is until a deliberate migration of code and data together.
- Honesty about validation: internal checks are not external validation. Never claim Cochrane-level performance, clinical validation or capabilities that are not implemented; the README states that no external scientific validation has been performed yet (planned v1.1).

## Architecture

- `emet/`: engine, Python ≥ 3.9 (CI on 3.10 and 3.12), standard library only. Modules run as `python3 -m emet.<module>`.
- `methodology/`: constitution (`METHODOLOGY.md`), orchestrator (`ORCHESTRATOR.md`, `pipeline.json`), agent modules (`agents/`), review-depth profiles (`profiles/`), review schema (`schemas/review.schema.json`, `$id` on emet-evidence.github.io). Shipped inside the wheel as `emet/methodology` (pyproject `force-include`); `emet.workspace.METHODOLOGY` resolves both layouts.
- Workspaces hold review data, never the engine: `emet.json` (name, profile, language, topics, `commands.publish` / `commands.validate` / `commands.summary_sheet`, `open_data_dir`, `claim_verification.skip_sections`) and `topics/<id>.json` (search folder, outputs, title pre-filter rules, compared arms `effects.arms`). Found via `EMET_WORKSPACE` or the nearest parent containing `emet.json`.
- `examples/shoulder-surgery/`: example workspace (immobilisation after rotator cuff repair). It is generated from the shoulder-surgery.eu repository (`scripts/sync_example.py` there): do not edit it by hand here.
- Tests: `python3 -m unittest discover -s tests` (no network; uses the example workspace). `tests/test_engine_boundary.py` forbids site- or specialty-specific terms in `emet/` and `methodology/` (the allowance list may only shrink).

## Relationship with shoulder-surgery.eu

shoulder-surgery.eu is the first application and a separate (private) project. It pins an exact engine commit in its `requirements-engine.txt` and changes version only when explicitly asked in a shoulder-surgery session. Changes made here therefore do not reach the site until that request: when a change matters for the site (methodology, rendering, data format), say so in the summary so it can be applied there (pin bump, re-run of affected review steps, update of the site's French public methodology).

## Working rules

- No fabricated data; missing stays explicitly missing; fail closed on critical checks.
- Every methodology change is recorded in `methodology/CHANGELOG.md` and describes only what is implemented.
- Any change to rendered output must keep the French rendering of existing reviews identical unless the change is intended — check by rendering the example review before and after.
- Version in `emet/__init__.py` (single source read by `pyproject.toml`); update `CITATION.cff` by hand when it changes.

## Open items

- Methodology review by the methodologist after the French → English translation: terminology choices (dual independent screening, adjudication, outcomes…); `ORCHESTRATOR.md` still calls the Exploratory / Enhanced / Maximum profiles "to be defined" although their files exist; output-language rules now refer to the workspace language.
- Normalise French controlled values into neutral codes with translated labels (with data migration).
- `fiche du registre` (written by `fulltext_stage`) vs `fiche de registre` (expected by `migrate_review`); `migrate_review`'s effects note hard-codes outcomes "(O1, O2, O5)" of the example review; the open-data README still points to `scripts/*.py` paths.
- First release v0.8.0 (tag, GitHub release, Zenodo DOI).
