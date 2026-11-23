# Contributing to EMET Evidence

Thank you for helping. A few rules keep the engine trustworthy:

1. **Tests first.** `python3 -m unittest discover -s tests` must pass, without network. New checks come with a test that fails when the check is removed (see the mutation tests in `tests/test_check_review.py`).
2. **Standard library only** for the engine (`emet/`), Python ≥ 3.9.
3. **Domain- and site-agnostic.** No specialty, topic or website logic in `emet/` or `methodology/`: it belongs in a workspace (`emet.json`, `topics/<id>.json`). `tests/test_engine_boundary.py` enforces it.
4. **English code, localised output.** Code, comments and messages in English; any text a reader sees goes through `emet.i18n._()` with its translations in `emet/locales/` (`tests/test_i18n.py` checks the French catalogue is complete).
5. **No fabricated data, no silent changes.** Never replace verified outputs with invented values; keep missing values explicitly missing.
6. **Methodology changes** (`methodology/`) are versioned in `methodology/CHANGELOG.md` and must describe only capabilities that are actually implemented.
7. **No copyrighted content**: no abstracts or full texts in commits; reference them by identifier and hash.

By contributing you agree that your code is licensed under Apache 2.0 and your methodology or documentation contributions under CC BY 4.0.
