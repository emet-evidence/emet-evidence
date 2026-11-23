# Module: literature search

Execution: scripts (`python3 -m emet.search_pubmed`, `python3 -m emet.search_sources`, `python3 -m emet.pubmed_cache`), driven by the main session; Consensus through its connector. Output: `data/searches/<topic>-<date>/` (raw responses, `manifest.json`).

## Sources

- **PubMed** (E-utilities, no key): protocol queries, then iterative searching of references and citations (ELink `pubmed_pubmed_refs` / `pubmed_pubmed_citedin`, reference lists of full texts) until no new relevant study appears. Each iteration is documented.
- **Europe PMC** (REST API): PMC, preprints, part of the grey literature, conference abstracts.
- **ClinicalTrials.gov** (API v2) and, if accessible, WHO ICTRP: completed trials that are unpublished or without published results (GRADE "publication bias" domain, not evidence in themselves).
- **Consensus** (Semantic Scholar, OpenAlex): at least one search per topic. Free plan: first page only, up to 300 articles (each block of 100 counts as one search), quota not displayed. Hence a single broad natural-language search without filters, `page_size` 100 to 300, no test search; save the response in `consensus.txt`, then cross-match it by title; find each new article in PubMed or by DOI (neither DOI nor study type is provided). Quota exhausted: record it in the manifest.
- **Institutional guidelines** (HAS, NICE, AAOS…) when the question lends itself to it.
- Embase, Cochrane CENTRAL and Web of Science are not accessible: state this in the limitations, without presenting them as searched.

## Reproducibility

- Record the exact query, database, UTC date, publication date limit, sort order, pagination (all requested pages), returned identifiers and number of results.
- Cache-first: `python3 -m emet.pubmed_cache` does not rerun a search whose manifest exists; `--offline` fails if a record is missing; `--refresh` only for a deliberate update. Only one collector at a time.
- A collection failure (`data/collection-errors.json`) is never evidence of absence.
- Do not confuse results identified, records downloaded, abstracts read and full texts examined.
- Full texts: Europe PMC open access, then Unpaywall (`python3 -m emet.unpaywall`, contact e-mail in `UNPAYWALL_EMAIL` or `.env.local`, never versioned) for included studies read on the abstract; keep the rights statements; no circumvention of paywalls or of publishers' anti-bot protections (an open version that cannot be downloaded is flagged "manual retrieval"). A full text obtained after extraction requires a new extraction of the fields concerned. The presence of a text does not prove that it was read.

## Retractions

Dedicated PubMed query (`"Retracted Publication"[pt] OR "Retraction of Publication"[pt]` + topic terms), publication type and `RetractionIn` field of each identified study, Crossref (`updated-by` of type retraction), Retraction Watch. Each retracted article on the topic is cited in a dedicated section and in the timeline (distinct marker) with the retraction notice, the date and the reason (never guessed; "not accessible" otherwise). It is never used as evidence.
