# Module: declarations of interest

Aim: give readers transparent information on the funding of the included studies and on the interests declared by their authors, with the source of each item. The module does not judge whether a study is biased and does not assess the conduct of any author.

Script: `python3 -m emet.interests` (collection, identity criteria, checks of the agents' outputs, consolidation); stages `interests-*` of `pipeline.json`, after the review package (the included studies are then fixed). Files: `<search folder>/screening/interests/`.

## Vocabulary

- Terms used: **declaration of interest** (what an author or a study states), **link of interest** (a relationship between an author or a study and an entity, as stated in a source), **possible link of interest** (a link found in a source and attributed to an author of an included study, shown with its source).
- Terms never used, in any language, in the page, the data, the badges or the agents' outputs: "conflict", "undeclared", "omitted", "failed to disclose", "hidden", "concealed", "discrepancy", "inconsistency", or any wording that suggests a fault. Their equivalents in the workspace language are excluded in the same way. The page juxtaposes what each source states; it never comments on the difference between two sources. A script rejects these terms in every field written by the agents or the engine; verbatim quotations, source headings and the statements of the persons concerned are exempt, since they reproduce a source.
- This module names displayed labels in English; the implementation translates them into the workspace language (`language` in `emet.json`) through `emet.i18n._()`.

## Guiding rule: certainty before completeness

A possible link that is missed is preferable to an uncertain item shown about a named person. Every item displayed must rest on a source that can be opened by the reader, quoted verbatim and attributed to the author with the identity criteria below. Otherwise it is not displayed (it stays in the internal files with its reason). The absence of a badge therefore never means "no link of interest": the page says so.

## Relevant entities (protocol)

The protocol lists, before the search, the entities whose links are relevant to the question (`interest_entities`): manufacturers, distributors and owners of the products or techniques of the intervention and comparator arms (`effects.arms` of the topic), with their known names, subsidiaries and product brands as `aliases`. For a non-commercial intervention, the protocol says so and lists the entities marketing the products that the question compares, if any; an empty list is explicit (`[]`). Without this field the module stops. An entity added after the search (a product brand discovered in an included study) is recorded with date and reason, like a deviation.

```json
"interest_entities": [{"id": "E1", "name": "…", "aliases": ["subsidiary", "product brand"], "arms": ["intervention"], "products": ["…"]}]
```

## Level 1: declarations in the included studies (all profiles)

1. **Collection (script, `collect`)**: for each included study and each of its reports, the declaration statement of the PubMed record (`CoiStatement`), its grants (`GrantList`), the funders of the Crossref record, the sponsor and collaborators of the ClinicalTrials.gov record (registry numbers found in the reports), and the declaration and funding sections of the archived open-access full texts (Europe PMC). Each statement gets an identifier (`src-N`); responses are archived with date and SHA-256 hash. One file per study for the reviewers: `interests/studies/<study>.txt`.
2. **Extraction (agents)**: reviewer A on all studies, reviewer B on the dual-extraction share of the profile; they read the study file and the eligibility files of its reports (`screening/eligibility/<report>.txt`, which may contain the declaration, disclosure, funding or acknowledgement sections of the full text). For each item: author (as written), entity (as written), type of link, relevant entity of the protocol or `null`, the source (`src-N` or `eligibility:<report>`) and a short verbatim quotation.
3. **Checks (script, `check … studies`)**: every quotation found verbatim in its source, controlled values, relevant entities of the protocol, vocabulary. A and B are compared on the statuses, the relevant entities of the funders and the (author, relevant entity) pairs of the links; disagreeing studies go to the arbiter (`study-declarations-arbitration.json`, `arbitration.md`).

Statuses (neutral codes, labels translated): funding `reported | no_funding_declared | not_reported | not_accessible`; declaration `links_declared | no_link_declared | not_reported | not_accessible`. A study read on the abstract only usually has `not_accessible`: this is never written as "no link". Funder type: `industry | public | non_profit | institutional | other`. Type of link, as stated by the source: `employment | consultancy | speaker | advisory_board | royalties | research_support | equity | patent | travel_or_hospitality | material_support | other | unspecified`. No amount is extracted.

Output of A, B and the arbiter (`study-declarations-A.json`…), one entry per included study:

```json
{
 "<study id>": {
  "funding": {"status": "reported", "items": [{"name": "…", "type": "industry", "relevant_entity": "E1", "source": "src-3", "quote": "…"}]},
  "declaration": {"status": "links_declared", "source": "eligibility:<report>", "quote": "…",
                  "links": [{"author": "…", "entity": "…", "type": "consultancy", "relevant_entity": "E1", "source": "eligibility:<report>", "quote": "…"}]}
 }
}
```

## Level 2: declarations by the same authors in their other publications on the topic (all profiles)

Aim: show the links of interest that the authors of an included study declare in their other publications on the same topic. Restricting to the topic keeps the corpus specific and makes homonyms rare.

1. **Authors**: all authors of each included study that has a PubMed record (primary studies and systematic reviews), in every profile; name, initials, ORCID and affiliations as given in the record.
2. **Corpus (script, `authors`)**: for each author, a PubMed search combining the topic and the author: `(<topic>) AND "<Name Initials>"[au]`, restricted to the publication window. Topic: `interest_topic_query` of the protocol if given, otherwise the PubMed queries archived in the search folder. Window: 36 months before to 36 months after the publication of the included study (the ICMJE disclosure period), computed in months, or in whole years when a month is missing. Declarations are taken from the `CoiStatement` element and from the declaration sections of the archived open-access full texts. Raw responses are archived with date and SHA-256 hash (`author-corpus/`).
3. **Identity (fail closed)**: the author of the other publication is the same person only if the name form matches (same surname, compatible initials) **and** at least one of: identical ORCID; an institution in common with the author's affiliations in the included study; at least one co-author in common with the included study. Two different ORCIDs exclude the match. Otherwise the publication is counted as "identity not confirmed" and nothing is shown.
4. **Candidates**: only the declarations of a confirmed identity that name a relevant entity (name or alias, whole words) become candidates (`author-candidates.json`, batches `author-batches/batch-NN.json`). The counts of each filter are kept (`summary`).
5. **Assessment (agents)**: two independent reviewers read each candidate (statement, author, identity criteria, entities named) and decide whether the statement attributes a link with a relevant entity **to this author**: `possible_link` (with entity, relevant entity, type of link, verbatim quotation and reason) or `not_retained` (with reason). `check … authors` verifies every quotation and controlled value. A candidate is retained when both reviewers retain it with the same relevant entity and type; any other disagreement goes to the arbiter (`author-assessment-arbitration.json`), whose cautious decision is `not_retained`. With a profile without reviewer B (exploratory), reviewer A decides alone.

Output of A, B and the arbiter (`author-assessment-A.json`…):

```json
{"<candidate id>": {"decision": "possible_link", "entity": "…", "relevant_entity": "E1", "type": "speaker", "quote": "…", "reason": "…"}}
```

## Level 2b: official transparency registries (specified, not implemented)

Public registries of payments or links between companies and health professionals (Open Payments in the United States, Transparence Santé in France, Disclosure UK, national registries of other countries). The page will show only the existence of a link with a relevant entity, its type, its year and a link to the registry entry; **amounts are never written** on the page or in the data: the reader follows the link. Identity: name and, according to the registry, national identifier, specialty and town or institution compatible with the affiliation; otherwise not displayed. Each registry's terms of reuse are checked before it is connected. Coverage is uneven between countries: for each author, the page will state which registries could be consulted, and an author not covered by any registry will be shown as "not verifiable in a registry", never as "no link".

## Level 3: display

- **Consolidation (script, `final`)**: checks again all outputs, refuses to conclude while a disagreement is not adjudicated, applies the correction requests and writes `interests-final.json`; `python3 -m emet.migrate_review` copies it into the section `interests` of the exchange format, and `python3 -m emet.check_review` blocks publication if an included study has no entry, an item has no quotation or no source link, a badge does not match its items, a forbidden term appears, the correction channel is missing while items are displayed, or the declaration of the review is missing.
- **Badge** "possible link of interest" next to the study label in the engine's study tables (table of studies, risk of bias by domain, effects by study), and in the workspace's own tables through `render_p0.interest_badge`, when at least one displayed item concerns a relevant entity: funding by it, a link declared in the study, or a link declared in another publication. Text and symbol in addition to colour; the badge links to the study's row in the section below.
- **Section "Declarations of interest"** (`render_p0.interests_section`): one row per included study with its funding, its own declaration and the items from other publications, each with author, entity, type of link, source (title, year, link), location and verbatim quotation. Items are listed side by side, without comparison or comment. No amounts, no ranking of authors or studies.
- **Coverage note**: studies with an accessible declaration, authors searched, possible links found, studies with the badge, relevant entities, window, and the sentence that the absence of a badge does not mean the absence of a link of interest.
- Links with entities that are not relevant to the question are kept in the open data of the review (`declarations-interets.csv`) but carry no badge.
- **Use in the synthesis (not implemented)**: the stages run after GRADE, so the information does not yet feed a sensitivity analysis or the GRADE judgement. Planned: a sensitivity analysis comparing studies with and without a link with a relevant entity when the body of evidence allows it (at least two studies in each group for an outcome); no automatic GRADE downgrade.

## Declaration of interest of the review

Displayed by `render_p0.review_declaration` (« Validation » block, `writing.md`), with the same vocabulary:
- the links of interest of the methodological lead and of any person responsible for the review, as declared by them (`review_team` in `emet.json`: `name`, `family`, `given`, `orcid`, `role`, `declaration`, `declared_at`);
- the language models used (from `execution.models`);
- the included studies of which a member of `review_team` may be an author: matched by ORCID, then by name (surname and first initial) in the PubMed records of the included studies. The person concerned confirms (`author`) or rejects (`not_author`) each candidate in `interests/review-team-authorship.json` (`{"<study id>": {"<member name>": "author" | "not_author"}}`). Unlike level 2, the rule favours declaring: a candidate is shown until the person states that they are not the author.

## Correction requests

- The row of every study with displayed items carries a link to the workspace's correction channel (`interests.correction_contact` in `emet.json`: e-mail address or URL). Any person concerned can ask for an item to be corrected or removed.
- Requests are recorded in `interests/corrections.json`: `[{"date": "…", "item": "<item id>", "status": "under_examination | removed | confirmed", "reason": "…", "author_statement": "…"}]`. An item under examination or removed is not displayed. Examination rechecks the source and the identity attribution: an item whose source or attribution is not confirmed is removed; an item confirmed by its source can be accompanied, at the author's request, by their statement, and the author is directed to the source for correction there.
- The date, item, status and reason of each request are kept in the review's data, without the requester's contact details.

## Personal data

Items concern named persons: only the data needed for the display are kept (name as published, entity, type of link, date, source link, quotation). Nothing of this kind is committed to the engine repository; the data live in the workspace. Legal review of the processing (lawful basis, information of the persons, retention) is required before the first publication.
