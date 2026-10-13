# Engine v2 validation registration — DRAFT, 2026-10-11 13:38

Written with `SPEC_engine_v2.md`, before any v2 table, forecast or value exists. Recovery plan S4.

**What these checks are.** They are engineering checks on development data (origins up to 2024-06-30, outcomes filed
before 2025-01-01). They establish that v2 is built as specified, calibrated where it was measured, and still maps
fundamentals to value. **They are not a performance claim.** v2's out-of-sample test is gate 2b (V2 arm and B1–B4) and
then the shadow record (S10).

## 1. Checks, all of which must pass

| # | Check | Rule |
|---|---|---|
| E1 | **Implementation identity** | On the forecast study's panel (`scratch/rev23/forecast_study/out/panel.pkl`), v2's `forecast_p50_rule` equals the section-2 formula recomputed by the coordinator's independent script (no import from `valuation`), to 1e-9, on at least 99.5% of rows with every input present. Every disagreeing row is listed and explained. |
| E2 | **The study reproduced** | On the same panel, the walk-forward MAE of v2's rule forecasts equals the study's corresponding candidate within 0.0005: b-blend at w = 0.5 for growth k = 1; i for growth k = 2, 3; ii_curve for the margin; the 0.75 blend on ii_curve for ROTE; ii for tangible-book growth. |
| E3 | **Calibration, walk-forward** | Origins 2016–2024, each origin using only its own vintage's tables. For every family × variable × k = 1, 2, 3 with at least 300 outcomes: P10–P90 coverage between 75% and 85%; neither tail above 15%; coverage by origin year reported. At least 7 of the 9 origin years must lie within 70–90%. |
| E4 | **Sharpness** | On the same set, the interval score at α = 0.2 of v2's distribution is reported beside v1's for every cell. v2 must not lose on more than one third of the cells. A band that covers by widening fails here. |
| E5 | **The oracle** (Addendum V method) | v2 valued at realised fundamentals across the gate-1 development dates 2020–2024, with the Y1 controls. Its rank IC with 3-month excess return is at least v1's oracle IC − 0.02, pooled and by year. No family's sort is inverted. |
| E6 | **No look-ahead** | The cut proof (spec section 6.2) passes for every new table of every vintage 2016–2025. The audit trail records, for each table, the latest outcome filing used, and none reaches its cut. |
| E7 | **Isolation** | The diff of `c7d7a4f`'s engine files is empty. The v1 suites are unchanged. The v2 suites pass. Engine v1 run on the gate-1 development dates reproduces its stored results exactly. |

## 2. Reported, not bars

- **Level:** the median v2 IV ÷ price against v1's, by family and year, on the gate-1 development dates. A shift
  outside 0.5–2× is investigated and explained before S5.
- **Median bias by cell:** the residual medians that section 3 keeps.
- **Refusals:** new refusals against v1 (an undersized cell or a missing `i_k`), with their counts and reasons.
- **The 2025 holdout,** reported once and never used to change v2: its coverage and errors at k = 1 for the margin,
  where AB 2 found the code worse than persistence in 2025.

## 3. Outcome

- **Pass:** E1–E7 hold. v2 is frozen, with its commit and table hashes recorded, and becomes the V2 arm and S5's
  prior.
- **Fail:**
  - The failed check is diagnosed.
  - A fix is a new version (v2.1) with a dated note in this file.
  - E3–E5 are re-run in full. A calibration fix may change only the residual-cell rule, never the section-2 weights,
    and the reason is recorded.
- **What may never happen:** a weight chosen by E3 or E5 results.

## 4. Approval record

Approved by the operator on 2026-10-11 21:04 KST ("approve the engine-v2 spec and registration"). Fixed from this point; cross-check 9 may still raise points, ruled on before the build.
