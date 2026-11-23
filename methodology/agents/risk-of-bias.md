# Module: risk of bias

Assessed in the same pass as extraction (`extraction.md`, field `rob`), by the same reviewers and with the same coverage of dual assessment (profile). Agreement published (`rob-agreement.json`, kappa on the dually assessed sample).

## Tool by study design

| Study design | Tool |
|---|---|
| Randomised trial | RoB 2 (Cochrane) |
| Non-randomised intervention study | ROBINS-I |
| Exposure study (risk factors, aetiology) | ROBINS-E |
| Analytical cross-sectional study | JBI (analytical cross-sectional) |
| Case series, histological series | JBI (case series) |
| Case report | JBI (case report) |
| Animal study | SYRCLE |
| Systematic review | AMSTAR 2 (high / moderate / low / critically low confidence) |
| Mendelian randomisation | Instrumental assumptions (relevance, independence, exclusion restriction) and sensitivity analyses, according to STROBE-MR |
| Title only, registry record without results | `"Non évaluable"` (not assessable), empty domains |

## Rules

- Categories specific to each tool, without artificial mixing between tools.
- With the abstract only, most domains are `"non rapporté"` (not reported); the overall judgement takes this into account (often « Préoccupations » (some concerns) or "unclear") and the rationale says so. No false certainty when the full text is missing.
- Output per study: tool, domains (name, judgement), overall judgement written out in full, `level` (low | some | high | critical | unclear), rationale of 1 to 2 sentences.
- Display: tool and overall judgement in the table of studies, domain-level detail in a collapsible section; text or symbol in addition to colour.
