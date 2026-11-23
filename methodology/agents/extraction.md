# Module: data extraction

Agents: reviewer A (all included studies); independent reviewer B on the share defined by the profile (`double_extraction_coverage`, plus the studies of the critical outcomes); adjudication of disagreeing fields only (`arbitration.md`). Risk of bias is assessed in the same pass (`risk-of-bias.md`). Topic-specific instructions: `data/protocols/extraction-addendum-<topic>.md`.

Additional requirements:
- For each study: population, sample size, protocol, product/dose if verified, site, number and dates of injections or interventions, comparator, primary outcome, method of measurement, follow-up, absolute numbers, available estimates and confidence intervals. Note adjustments and biases (indication, selection, measurement, loss to follow-up, power). Check the tables in the full text before any secondary analysis not described in the abstract.
- Distinguish the number of studies in a review from the number of patients.
- Search for corrections, retractions and more recent publications of the same study.


For EACH file listed in your batch (folder `screening/eligibility/` of the question), read everything available: abstract, methods, results, full-text tables. The `ACCÈS` (access) field of the header says what is available. Do not guess anything: a figure absent from the source is not extracted.

Write in the workspace language (`language` in `emet.json`), short sentences, medical register. One entry per study, key = value of the "ID:" line.

```json
{
 "<id>": {
  "label": "First author · year",
  "year": 2014,
  "design": "study design in a few words (e.g. « Essai randomisé », « Cas-témoins sur base de données », « Rat », « Ténocytes humains en culture »)",
  "population": "population, sample sizes, product/dose/route if relevant, measurement time point (1 sentence)",
  "result": "main result FOR THE PROTOCOL QUESTION, with absolute numbers, estimates and CIs if available (1–2 sentences)",
  "limitation": "main limitation for the question (1 sentence)",
  "outcomes": ["O1"],
  "randomized": "randomised trials (RoB 2) only: {\"n\": randomised participants (integer), \"source\": \"location and quotation of the sample size\", \"same_trial_as\": identifier of another publication of the same trial or null}; omit for other designs",
  "provenance": [
   {"value": "11", "what": "patients biopsiés", "location": "texte intégral, Méthodes, § Patients" , "access": "texte intégral"},
   {"value": "1,42", "what": "OR", "location": "résumé", "access": "résumé", "quote": "odds ratio 1.42 (95% CI 1.10-1.83)"},
   {"value": "9890", "what": "participants analysés", "location": "texte intégral, Méthodes", "access": "texte intégral", "derived": "9903 - 13"},
   {"value": "1", "what": "patient", "location": "résumé", "access": "résumé", "source_form": "biopsies of a patient"}
  ],
  "rob": {
   "tool": "RoB 2 | ROBINS-I | ROBINS-E | JBI analytical cross-sectional | JBI case series | JBI case report | SYRCLE | AMSTAR 2 | Randomisation mendélienne (STROBE-MR) | Non évaluable",
   "domains": [{"name": "Processus de randomisation", "judgement": "faible | préoccupations | élevé | critique | non rapporté | oui | non | incertain"}],
   "overall": "overall judgement written out in full (e.g. « Risque élevé », « Préoccupations », « Risque faible », « Confiance critiquement faible » for AMSTAR 2)",
   "level": "low | some | high | critical | unclear",
   "rationale": "1–2 sentences: what drives the overall judgement"
  }
 }
}
```

French values in the example, written as is (output in French; some are matched by the scripts): `access` `"texte intégral"` (full text) and `"résumé"` (abstract); tool `"Randomisation mendélienne (STROBE-MR)"` (Mendelian randomisation) and `"Non évaluable"` (not assessable); domain judgements `"faible"` (low), `"préoccupations"` (some concerns), `"élevé"` (high), `"critique"` (critical), `"non rapporté"` (not reported), `"oui"` (yes), `"non"` (no), `"incertain"` (unclear); overall judgements « Risque élevé » (high risk), « Préoccupations » (some concerns), « Risque faible » (low risk), « Confiance critiquement faible » (critically low confidence); domain « Processus de randomisation » (randomisation process); designs « Essai randomisé » (randomised trial), « Cas-témoins sur base de données » (database case-control study), « Ténocytes humains en culture » (cultured human tenocytes).

Rules:
- Every number written in population, result or limitation (sample size, age, dose, time point, percentage, OR, CI, p…) must have an entry in `provenance` with the exact location (section, table, figure) and the actual access level. Numbers written in words also count: write them in digits.
- A script (`python3 -m emet.verify_sources`) looks for each figure of `value` in the archived text of the source; a figure that cannot be found blocks publication. Therefore: `value` reproduces the figure as it appears in the source (rounding allowed, French decimal comma allowed); a **computed** figure (sum, difference, recalculated percentage) carries `"derived": "<pure arithmetic calculation with the figures of the source>"` (e.g. `"9903 - 13"`); a figure written in words or otherwise in the source ("a patient", "stage III", "no subjects") carries `"source_form": "<exact passage of the source>"`. `quote` (optional, recommended for the main result): passage copied verbatim from the source, checked by the script.
- Tools: choose according to the study design (see the protocol, field `risk_of_bias`). Domains of the tool: RoB 2 (5 domains), ROBINS-I (7), ROBINS-E (7), SYRCLE (10, grouped if necessary), AMSTAR 2 (critical domains), JBI (items of the corresponding checklist, grouped into 4–8 rows), Mendelian randomisation (relevance, independence, exclusion restriction, sensitivity analyses).
- With the abstract only, most domains are `"non rapporté"` (not reported): the overall judgement takes this into account (often « Préoccupations » or "unclear") and the rationale says so.
- Title only or registry record without results: `"tool": "Non évaluable"`, empty domains, and say so.
- Do not read the HTML pages, `data/question-*.json`, `references*.json`, `manifest.json`, or the files of the other reviewers. No network.
