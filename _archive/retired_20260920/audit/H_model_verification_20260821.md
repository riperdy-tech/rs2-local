# H — MODEL VERIFICATION AGAINST THE REBUILT PACK (2026-08-21)

First verification of Qwen3.8 (depth tier, `rs2-analyst-deep`, UD-Q5_K_M, think=high, ctx 65536)
against the pack rebuilt in `f521afc`. All runs seeded and reproducible. Successor to the
capability tests in `E_methodology_verdict_20260820.md`; unlike those, these runs used the
24-field / all-years pack with declared defects.

## Prerequisites landed first

- `ba1b61d` — `think:"max"` is invalid (template raises; `high` maps to `xhigh` and IS the
  maximum). Every run below uses `high`.
- `38761d7` — seeds threaded; determinism proven on the production model at the production
  window (T1: same seed byte-identical, seed+1 differs).

## GOOG — contamination test (single run + 3-sample consensus)

Single run (`ab_reports/capability_test/GOOG_20260820_223117_rs2-analyst-deep-high`, 1,374s):

| Check | Result |
|---|---|
| Catches contaminated TTM quarter | **PASS** — "TTM net income of $244.205B implies a 54.8% net margin, which is inconsistent with filed operating margin... therefore not used as the primary DCF earnings base." Unprompted. |
| Refuses misleading trailing P/E | **PASS** — "the 17.1x trailing P/E is therefore misleading" |
| Uses operating income | PASS |
| Uses working capital / ΔWC | PASS |
| Nulls as absent, not zero | PASS |
| Labels assumptions | PASS |
| Series-continuity warning | not triggered (GOOG has no basis break) — tested on PM below |

IV $310.20, no new buy, conviction 8/15, re-entry $260–280.

Consensus (`ab_reports/consensus/GOOG_20260821_011632`, 3 seeded samples, seed 1000+i):

- IVs **$333 / $373 / $300** — all pass the plausibility guard.
- **Median $316.50 vs price $343.54 → MoS −7.9%. Spread 11.0%** (tolerance 25%) — USABLE.
- Sample 2 hit the `num_predict` 49,152 cap and is FLAGGED as truncated, not silently kept.
- Convergence checked for the compensating-error signature that invalidated the old 14.8%
  "convergence": all three samples anchor on the same FILED base (TTM FCF $53.273B) with WACC
  8.5–9.0% and terminal growth 3.0–3.5%; the 11% spread comes from different growth paths.
  Shared facts, not one shared invented assumption. Genuine.

Reference points: caged pipeline published **$702.49** and **$64.30** (both wrong, opposite
directions); pre-pack free runs spanned **$161–$335 (2.08×)**; analyst-anchored reference ~$205.
The band is now $300–$373 around a $316.50 median. Above the $205 anchor — the model is more
constructive than the sell-side-derived benchmark; that disagreement is now legible and stable
instead of a 2× lottery.

## PM — series-continuity test (single run)

`ab_reports/capability_test/PM_20260821_024409_rs2-analyst-deep-high`, 1,383s. PM carries the
proven fake −64% revenue collapse (FY2015→16 excise-tax basis change, worked example in the pack).

| Check | Result |
|---|---|
| Recognises the basis change | **PASS** |
| Treats the step as artifact, not business event | **PASS** — report §Data discipline, verbatim: "FY2015 to FY2016 revenue step is treated as a reporting-basis change, not a business event, per the data-pack warning." |
| Builds trend on post-2016 basis only | PASS |
| Cites the actual figures | PASS |

Verdict: hold, no new buy, conviction 8/15. The warning block written into SECTION 0 of the pack
did exactly its job on the name it was written for.

## Honest limits

- n=3 consensus on one ticker + two single runs. Method-appropriateness evidence, not accuracy —
  **there is no accuracy oracle** (19 gradeable signal dates, one market episode).
- Sample 2's truncation means the output-budget question (49,152 `num_predict` vs 13-section
  contract) is still open for the depth tier.
- Production model (`rs2-analyst`, bare `{{ .Prompt }}` template) remains structurally unable to
  think; nothing here tests it. These results are the DEPTH tier's.
- PM continuity handling proves the model obeys a *declared* defect. Undeclared defects (the 21
  other basis-break names without provenance) remain invisible until the screener package's CH-6
  lands.

## What this buys

The three-layer design is now demonstrated end-to-end on real names: honest pack in, free
reasoning, guard judging output — refusing nothing here because nothing needed refusing, but
proven able to flag (truncation) and bound (plausibility, tolerance) the result.
