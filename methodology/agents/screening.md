# Module: study selection

Agents: independent reviewers A and B at each stage, then an arbiter (`arbitration.md`). Models according to the profile. Topic-specific instructions: `data/protocols/screening-instructions-<topic>.md` and `eligibility-instructions-<topic>.md`. Files: `data/searches/<folder>/screening/`.

Each reviewer returns, for each record, `{"decision": "include"|"exclude", "code": "E1".."En"}` in a single JSON file written in one go. They read only the protocol, their instructions and their batch: no site pages, no work of the other reviewer, no network.

## 1. Deduplication (script)

`python3 -m emet.screening records`: identifiers, then normalised titles; provenance by source is kept.

## 2. Pre-filter: prioritisation, never exclusion (since v0.71)

`python3 -m emet.prefilter` applies a topic-specific keyword rule, published with the page:
- **grey zone** (the rule is met, or the record comes from a targeted query, from ClinicalTrials.gov or from Consensus): dual independent title screening;
- **low zone** (rule not met): screening by a single reviewer, the profile's low-cost model, on **title + abstract** (`python3 -m emet.prefilter_audit` retrieves the abstracts), with the abstract screening rules and "doubt = include". Every retained record joins dual abstract screening. The rule applies to each branch, including the records from the reference and citation iterations (`snowN-records.json`).

The keywords apply only to titles: applied to abstracts, they no longer discriminate (immobilisation audit: 1,867 records recovered out of 2,038). The report `prefilter-audit.json` (records reviewed, retained, eligible records lost) is published; it measures the sensitivity of the pre-filter.

Exposure questions (smoking, age, diabetes): the factor is often analysed among others without appearing in the title or the abstract. Multifactorial studies whose text is inaccessible and whose abstract does not mention the factor are classified as "not retrieved", never excluded, and the limitation is stated.

## 3. Title screening

Dual independent. Doubt = include. Disagreement: automatically passed on to abstract screening (or adjudicated, depending on the profile).

## 4. Abstract screening

Dual independent, with an exclusion code for each exclusion. Abstract missing or ambiguous but suggestive title: include (decision at eligibility). Disagreements adjudicated.

## 5. Eligibility

Dual independent, on the full text if accessible, otherwise on the abstract (flagged). Eligibility files prepared by `python3 -m emet.fulltext_stage` (header: `ID`, `TITRE` (title), `ANNÉE` (year), `TYPE`, `ACCÈS` (access), `PMCID`, `DOI`; these French labels are data values matched by the scripts); second retrieval round by `python3 -m emet.retrieval_round2`. Records that cannot be retrieved are counted separately ("not retrieved"). Publications of the same trial or of the same cohort are linked (code E5 for the duplicate, never counted twice).

## 6. Agreement and flow (script)

`python3 -m emet.screening agreement <topic> <stage>`: Cohen's kappa, observed agreement, disagreements, inclusions by A and by B. `python3 -m emet.screening final <topic>`: `final.json`, PRISMA-type flow computed from the decisions (sources, duplicates, titles, abstracts, eligibility, not retrieved, included, retracted). No number entered by hand; no "≈".
