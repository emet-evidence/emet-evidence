# Module: structured extraction of effects

Agents: reviewer A (all studies of the batch, all protocol outcomes); independent reviewer B on the critical outcomes (profile); adjudication of disagreeing fields only. Script: `python3 -m emet.effects` (check of quotations, A/B comparison, deterministic calculations, forest plot without pooling).

Aim: make each numerical result usable by a calculation, without inventing anything. The agent **copies**; it does not calculate (relative effects, differences and intervals are calculated by script).

## Inputs

The protocol (`data/protocols/<topic>.json`: outcomes O1…On, comparison), the list of the batch (study, publications, expected outcomes) and the source files `screening/eligibility/<publication>.txt` (`ACCÈS` (access) header: `résumé` (abstract), `texte intégral` (full text), registry record). Read each file in full. Nothing else: no pages, no page JSON, no network.

## Output: a JSON array, one entry per result (study × outcome × time point × measure)

```json
[{
 "study": "S-22287641",
 "report": "22287641",
 "outcome": "O1",
 "measure_label": "défaut de cicatrisation à l'IRM",
 "timepoint": "12 mois",
 "timepoint_months": 12,
 "unit": "patients",
 "type": "dichotomous | continuous | reported_effect | narrative",
 "groups": {
  "<intervention>": {"label": "label of the arm in the source", "n": 56, "events": null, "mean": null, "sd": null, "median": null, "iqr": null},
  "<comparator>": {"label": "label of the arm in the source", "n": 49, "events": null, "mean": null, "sd": null, "median": null, "iqr": null}
 },
 "reported_effect": {"measure": "OR | RR | HR | MD | SMD | null", "value": null, "ci_low": null, "ci_high": null, "p": "0,429", "favours": null},
 "percentages_only": {"<intervention>": "12 %", "<comparator>": "18 %"},
 "higher_is_better": null,
 "location": "résumé, Résultats",
 "access": "résumé | texte intégral | registre",
 "quote": "passage copied verbatim from the file, which carries the figures",
 "notes": "≤ 25 words: discrepancies, per-protocol analysis, numbers analysed different from numbers randomised…"
}]
```

French values in the example, written as is: `access` `"résumé"` (abstract), `"texte intégral"` (full text), `"registre"` (registry); `measure_label` « défaut de cicatrisation à l'IRM » (healing failure on MRI), `timepoint` « 12 mois » (12 months), `location` « résumé, Résultats » (abstract, Results) are examples of French free text.

## Rules

- `<intervention>` and `<comparator>`: keys of the two arms declared in `effects.arms` of the topic file (`topics/<topic>.json`: `key`, `label`, `short`), with the definition of each arm given by the protocol (for example: which arm counts as the intervention when two durations are compared). Without a declaration: `intervention` and `comparator`. Effects are calculated as intervention versus comparator.
- Copy numbers as they appear (comma or point as in the source). `null` if absent: never derive a sample size from a percentage, nor a standard deviation from an interval.
- `n` = number **analysed** for this outcome and this time point if given, otherwise the number randomised in the arm, with a note.
- Dichotomous: `events` and `n` per arm. If only percentages are given, put them in `percentages_only` and leave `events` as `null`.
- Continuous: `mean` and `sd` (or `median` and `iqr` as text); specify the scale in `measure_label` (Constant, ASES, EVA 0-10 (VAS), degrees of elevation…) and `higher_is_better` (true / false / null if unknown).
- Effect reported by the authors (OR, adjusted difference…): `reported_effect`, with the direction (`favours`: key of the favoured arm, or null).
- Result without a usable figure ("no significant difference"): `type` = "narrative", `quote` mandatory.
- `quote`: 5 to 60 words copied **character for character** from the file; a script checks that they appear in it. An entry without a verifiable quotation is rejected.
- One time point per entry; keep the time points of the outcome (latest measured re-tear; function at 12 months or more and at last follow-up; range of motion in the short term and at 12 months).
- Data from a registry record without results produce no entry.
- Write the requested file in one go.
