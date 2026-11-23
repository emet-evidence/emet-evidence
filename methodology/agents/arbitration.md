# Module: adjudication

Agent: arbiter separate from reviewers A and B (model according to the profile; Opus for GRADE and contentious cases). Topic-specific instructions: `data/protocols/extraction-arbitration-<topic>.md` where applicable.

- The arbiter sees only the items in disagreement (records, extraction fields, GRADE domains), the two decisions and the source. Not the whole extraction form when only one field differs.
- The arbiter decides according to the protocol and the source, never by majority or by preference for one reviewer. If the source does not allow a decision: cautious decision (include at screening; `"non rapporté"` (not reported) in extraction; lowest certainty in GRADE) and justification.
- Output: one `*-arbitration*.json` file; the raw decisions of A and B are never modified.
- Disagreements, their number and the adjudication are kept for the audit report (kappa, agreement).
