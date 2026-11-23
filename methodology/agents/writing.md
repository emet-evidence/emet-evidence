# Module: writing the page and the summary sheet

Agent: main session (Opus) or a dedicated writer, after adjudicated GRADE. Contract: the page must pass the workspace's publication and validation commands (`commands.publish`, `commands.validate` in `emet.json`), then claim verification (`claim-verification.md`).

## Inputs (read-only)

Protocol; in `screening/`: `final.json`, `extraction-final.json`, `grade-final.json`, `eligibility/<id>.txt`; records `data/articles/<PMID>.json`.

## Outputs

1. `data/references-<page>.json`: R1…Rn in order of appearance; value = PMID, or a text identifier described in `static_references`.
2. `data/question-<page>.json`: `question`, `status`, `fulltext_consulted`, `studies` (taken from the adjudicated extraction: text may be shortened, figures never modified, provenance kept), `risk_of_bias`, `grade` (identifiers converted to R, `main.claim` = claim of the protocol), `randomized_trials`, `tables` (each included study in at least one table), `timeline` (8 to 14 milestones from the included studies + retractions), `retracted`, `retraction_search`, `method` (`sources`, `limits`, `reviewer_models`), `validation` (`methodology`, `last_search`, `watch`, `status` = `AI-generated` | `AI-verified`), `static_references`, `context_references`. No `flow` or `gauge` (calculated).
3. HTML template of the page and infographic (`graphic-<page>.html`), references `[[R..]]` (or `[[@PMID]]` in the source templates).

## Writing rules

- Rule no. 1. All included studies are cited, and nothing else (except retracted studies and documentation).
- Short answer first, directly on the question; then organisation by protocol outcome. Wording aligned with the certainty: « … probablement … » (probably; moderate), « … pourrait … » (may; low), « Les données sont très incertaines : … » (the evidence is very uncertain; very low).
- Each medical claim (summary, caption, infographic, FAQ) carries its reference right after the passage it supports. A reference only counts for the claim it supports. Translated passages are paraphrases.
- Distinguish paraphrase of the authors' conclusions from critical appraisal; do not count reviews as independent confirmations without checking the overlap of their studies.
- Tables of studies: study/year, design, population/sample size, result, limitation, risk of bias (tool and overall judgement; domains in a collapsible section). Two rows visible, button « Voir les N autres études » (see the N other studies) (everything displayed when printed and without JavaScript).
- Collapsible box « Aller plus loin » (going further) per sub-question, without hiding the essential answer.
- Infographic « Comprendre les preuves » (understanding the evidence) in four steps: what is observed (solid), then what is missing (« Il faudrait » (what would be needed), « Sens inverse possible » (possible reverse direction), « Associé, pas causal » (associated, not causal), shown dotted), without asserting anything unsourced.
- Timeline: milestones of the cited body of evidence, discordant and non-significant studies kept, retractions with a distinct marker, date convention stated; no narrative of continuous progress.
- Section « Comment cette page a été préparée » (how this page was prepared): protocol (date, commit, PICO, criteria, deviations), flow diagram, kappas, models, limitations (databases not searched, dual review by agents and not by humans, share read on the abstract only, records not retrieved, pre-filter report).
- Address: one page per question, thematic folder, file name made of keywords in the workspace language (`language` in `emet.json`), without accents; HTML title starting with the keywords.
- Colour code = categories of studies, not scientific value; text or shape in addition to colour; mobile, keyboard and print.
- Simple and precise medical language, in the workspace language (`language` in `emet.json`).

## Summary sheet (fiche; mandatory for each published page)

`infographies/<slug>.html` (same slug as the page), A4, one page, fixed structure: question, short answer, GRADE gauge of the main claim, four cards « Ce que montrent les études » (what the studies show) (place of evidence, key figure, finding, GRADE of the outcome), diagram of the main limitation, three unknowns, method in figures, out of scope, QR code (`<meta name="fiche-url">`). All figures come from the page and its JSON. Start from an existing sheet and from `infographies/fiche.css`; render with the workspace's summary-sheet command (`commands.summary_sheet` in `emet.json`, e.g. `.venv/bin/python scripts/render_fiche.py <slug>`; fails if the content overflows) and review the PNG. To be redone at each update of the page.

## « Validation » block

Methodological responsibility, public status (`AI-generated` / `AI-verified`), date of the last search, monitoring (every 12 months, or sooner if a relevant trial is published). No reviewer name is added without their written consent; no page-by-page human review is claimed. Unavailable fields (declarations of interests, reporting channel) are not displayed as "to be completed".
