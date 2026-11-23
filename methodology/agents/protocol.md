# Module: protocol

Agent: main session (Opus), before any search. Output: `data/protocols/<topic>.json`, committed **alone** before the first query. The timestamped Git commit serves as registration; an independent public registration (OSF, PROSPERO if eligible) is planned for v0.8.

## Mandatory content

- `id`, `title` (the question as displayed), `question` (full PICO/PECO wording), `category`, `registered` (date), `methodology_version`, `review_depth` (profile from `../profiles/`).
- `pico`: population, intervention or exposure, comparator, outcomes, time points. Distinguish the clinical situations that rule no. 1 separates (tendon not operated on / pre- / postoperative; injection route; single or repeated injection; native tear, re-tear, reoperation, infection, pain).
- Inclusion criteria and **exclusion codes** E1…En, with their label.
- Sources and search limits; planned queries.
- Selection method (reference to the profile), risk-of-bias tools by study design.
- `outcomes_grade`: outcomes rated with GRADE (id, label, importance `"critique"` (critical) or `"important"`; these values stay in French, see `METHODOLOGY.md`); `main_claim`: main claim of the gauge.
- Synthesis rules (narrative, no pooling unless a statistical protocol is planned).
- `interest_entities`: entities whose links of interest are relevant to the question (manufacturers, distributors and owners of the products or techniques of the compared arms, with their aliases), or an explicit empty list; optionally `interest_topic_query`, the PubMed query that defines the topic for the other publications of the authors (`declarations-of-interest.md`).
- `deviations`: empty at registration.

## Deviations

Any change after the first query is a deviation: add an entry to `deviations` (date, description, reason) without rewriting the initial version. The page displays date, commit, PICO, criteria and deviations. A protocol written after the search is flagged as "retrospective".

## Topic instructions

The protocol comes with topic-specific instructions, in `data/protocols/`: `screening-instructions-<topic>.md` (title and abstract screening rules, with the codes), `eligibility-instructions-<topic>.md`, `extraction-addendum-<topic>.md` (specific fields), `grade-addendum-<topic>.md`. They complement the modules without contradicting them and are committed before the stage they govern.
