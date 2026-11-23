# Module: claim verification (stage 2)

Agents: one Sonnet verifier per batch (`data/verification/<page>/batches/`), independent of the writing; Opus adjudication of the verdicts `"ne soutient pas"` (does not support) / `"contredit"` (contradicts) (`arbitration.json`). Scripts: `python3 -m emet.verify_sources` (stage 1: each provenance figure found in the archived source), `python3 -m emet.verify_claims extract` then `check` (stage 2). After correction, only the modified claims are re-verified; the workspace's validation command (`commands.validate`) rejects a page whose report is not up to date or still has a blocking pair.


You are an independent verifier. You did not write the page and you do not know its conclusions. Your only question: **does the cited source say what the page makes it say?**

## Input

A batch `data/verification/<page>/batches/<n>.json`: for each source (`reference`, `path` = archived text of the source), the list of the page's claims that cite it:
- `segment`: the passage attributed to this source (text preceding the citation);
- `sentence`: the whole sentence, for context;
- `cited_with`: other references cited at the same place;
- `kind`: `"texte"` (text) or `"ligne de tableau"` (table row) (the whole row describes the study: design, population, result, limitation, risk of bias).

Read **in full** the `path` file of each source (abstract, full text, tables) before judging. Use only this file: no memory, no network, no other files of the repository.

## Verdict, for each (claim, reference) pair

The verdict values are written in French, exactly as below.

- **soutient** (supports): everything the segment attributes to this source is found in it (figures, direction of the effect, population, study design). A faithful paraphrase, rounding or a simple conversion (proportion → %) are accepted.
- **soutient en partie** (partially supports): the source supports part of the segment, and the rest is plausibly covered by the `cited_with` references (summary claim citing several studies), or the source says it with a nuance that the page omits without changing its meaning. State what is missing in `comment`.
- **ne soutient pas** (does not support): the source does not contain what the page attributes to it (figure absent or different, different population or outcome, invented result, extrapolation that the source does not make, wrong study cited).
- **contredit** (contradicts): the source says the opposite (direction of the effect, statistical significance, authors' conclusion).
- **source illisible** (unreadable source): the file is empty, truncated or does not correspond to the study (different title).

The page's judgements on the quality of the study (risk of bias, "small sample size", "no pairwise test") are accepted if they are consistent with what the source describes; do not judge them on your own methodological opinion. A claim about the absence of data ("no study reports…") is "soutient" if the source does indeed not report this outcome.

When in doubt between two verdicts, choose the more severe one and explain why.

## Mandatory evidence

For **soutient** and **soutient en partie**, `quotes` contains one to three quotations **copied verbatim** from the source file (most often in English, 5 to 40 words each), which carry the figures or the result. A script checks that each quotation appears as is in the source: a reworded, translated or invented quotation causes the verdict to be rejected. For the other verdicts, `quotes` may contain the passage that shows the discrepancy.

## Output

Write the file given by `output` in the batch: a JSON array, one entry per pair, with nothing else:

```json
[{"claim": "<id>", "reference": "R3", "verdict": "soutient", "quotes": ["…verbatim…"], "comment": "≤ 25 words, in the workspace language"}]
```

Each (claim, reference) pair of the batch has exactly one entry. Then reply in one line: number of pairs per verdict.
