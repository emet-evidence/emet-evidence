# Module: GRADE

Agents: independent reviewers A and B (dual assessment kept whatever the profile, low cost), adjudication by Opus of the domains in disagreement. Topic-specific instructions: `data/protocols/grade-addendum-<topic>.md`.

General rules:
- One outcome (or claim) per row, defined in the protocol. Start high for randomised trials, low for observational studies (high if assessed with ROBINS-I/E, which then incorporate confounding into the risk of bias).
- The gauge displays the certainty of the main claim, equal to the lowest of the critical rows; the full table (domains, rationale, references) is in a collapsible section. Visible label: « Niveau de preuve (GRADE) » (level of evidence (GRADE)).
- Below the gauge: number of randomised trials included and of randomised participants (`randomized_trials`): every included human study assessed with RoB 2, and only those; a trial counts once whatever the number of publications; sample size = number randomised (full text > abstract > registry), failing that the number included or analysed, specified in `source`.
- Do not confuse absence of evidence with evidence of absence of effect. Avoid double downgrading for the same problem.


Inputs: the protocol of the question (`outcomes_grade`, `main_claim`), the adjudicated extraction `screening/extraction-final.json` (design, population, result, limitation, outcomes O1–O4, risk of bias per study), `screening/final.json` (flow, records not retrieved) and the registry records (NCT rows of `screening/titles.tsv`) for publication bias.

For each outcome O1–O4 of the protocol:
- contributing studies (id) and summary of the body of evidence ("4 before/after series, 11 patients at most");
- starting level: `"élevé"` (high) if the body of evidence rests on randomised trials, `"faible"` (low) for observational studies (high only if they were assessed with ROBINS-I/E and you explain it); animal or cell studies: start according to the design, then downgrade for indirectness;
- five domains, each rated 0, −1 or −2, with a one-sentence rationale: risk_of_bias, inconsistency, indirectness, imprecision, publication_bias;
- upgrades (observational studies only, and never if a domain has been downgraded for serious risk of bias): large_effect, dose_response, confounding (0, +1, +2);
- final certainty: `"élevé"` (high), `"modéré"` (moderate), `"faible"` (low), `"très faible"` (very low) (not below very low);
- GRADE statement in the workspace language (`language` in `emet.json`), wording adapted to the certainty; in French: (« … probablement … » (probably) for moderate; « … pourrait … » (may) for low; « Les données sont très incertaines : … » (the evidence is very uncertain) for very low).

Main claim (`main_claim`): certainty = the lowest among the `"critique"` (critical) outcomes; rationale of 2–3 sentences; references = 5 to 8 key studies.

For an aetiology question, judge the certainty of a CAUSAL LINK, not of an association.

JSON output:
```json
{"outcomes": [{"id": "O1", "label": "…", "importance": "critique", "evidence": "…", "references": ["id"], "start": "faible",
  "domains": {"risk_of_bias": {"rating": -1, "reason": "…"}, "inconsistency": {…}, "indirectness": {…}, "imprecision": {…}, "publication_bias": {…}},
  "upgrades": {"large_effect": {"rating": 0, "reason": "…"}, "dose_response": {…}, "confounding": {…}},
  "certainty": "très faible", "statement": "…"}],
 "main": {"claim": "…", "certainty": "très faible", "rationale": "…", "references": ["id"]}}
```
Do not read the HTML pages, `data/question-*.json`, `references*.json`, or the work of the other reviewer. No network.
