# 05. Every result, with numbers

## 1. Stage 1 (frozen dossiers, 12 names)

| Name | Minutes | Facts | Usable | Ended |
|---|---|---|---|---|
| MSGE | 66.5 | 197 | 94 | done |
| TASK | 67.7 | 139 | 96 | done |
| PACS | 92.4 | 136 | 104 | done |
| DAC | 63.4 | 85 | 40 | done |
| BUD | 40.5 | 107 | 62 | done |
| GOLD | 46.9 | 111 | 65 | done |
| MCY | 37.1 | 75 | 55 | done |
| LPG | 40.1 | 73 | 25 | done |
| ITGR | 72.4 | 102 | 41 | done |
| KOF | 79.6 | 34 | 26 | **INCOMPLETE** (context overflow at turn 20: 42,663 prompt + 53,460 output tokens of a 98,304 window; 130k of 145k characters were thinking; the cut call held 39 facts, 38 complete) |
| DAR | 42.0 | 92 | 48 | done (re-researched after the Wi-Fi fix) |
| VSNT | 82.5 | 159 | 71 | done |

About half the registered facts fail verification; most failures are the proximity rule (`metric_not_near_quote`), and many trip on the company's
own name ("gold", "integer", "inbev" treated as metric words). Research gaps (topics NOT RESEARCHED): BUD 1, MCY 1, VSNT 1 (DAR 0 after re-research).

## 2. Iteration 2 (pack revision 26, 9 of 12 names; stopped on KOF) — FAIL
Coherent **0/7**; incoherent 1 (ITGR: memo invented an "MRI business with an installed-base service annuity"); median spread 17.6%; unanimous
direction 6/7 (one BUD sample in the 10% hold band); pull 0.000; memo verdict mismatches 0. Spread >20%: GOLD 82.8%, MCY 43.0%, ITGR 32.9%.
Values (Base): MSGE 35.51/39.37/39.90 vs 79.60; TASK 20.54-22.25 vs 8.22; DAC 474-545 vs 158.17; BUD 86.47-102.98 vs 82.59; GOLD 65.54/75.17/127.78
vs 39.35; MCY 173.88-264.36 vs 102.80; ITGR 63.72-94.61 vs 126.70. Every name was questionable on criterion 4 ("duration": evidence that speaks for
perpetuity), which led to the rubric amendment.

**S3 spread attribution on iteration 2 (real desk):** GOLD: near-term years 1-2 (only-G spread 28%) and long-run margin (25%); MCY: long-run margin (19%);
ITGR: normalized state (11%) and discount rate (18%); BUD: terminal return (21%). The discount rate explains only ITGR.

## 3. Iteration 3 (pack revision 27, all 12; old charter still in SYSTEM) — FAIL

| Name | Verdict | Base values | Price | Spread | Flags |
|---|---|---|---|---|---|
| MSGE | over | 41.90/39.23/38.24 | 79.60 | 9.3% | none (memo clean; coherent on all 4 criteria) |
| TASK | under | 19.51/17.69/18.96 | 8.22 | 9.6% | path_dominated; memo cited 3 ids not in dossier (G42b, L15, L17) |
| PACS | data no-call | | 46.91 | | base_cf_unavailable |
| DAC | under | 458.77/540.79/488.69 | 158.17 | 16.8% | path_dominated |
| BUD | under | 93.76/103.02/87.59 | 82.59 | 16.5% | memo unknown fact id |
| GOLD | under | 207.60/149.70/77.38 | 39.35 | 87.0% | spread |
| MCY | under | 236.50/254.92/191.77 | 102.80 | 26.7% | spread |
| LPG | data no-call | | 53.60 | | bridge_unavailable |
| ITGR | over | 79.58/95.80/78.40 | 126.70 | 21.9% | spread |
| KOF | data no-call | | 118.28 | | shares_unavailable |
| DAR | under | 142.44/218.04/238.84 | 59.41 | 44.2% | beyond reach; memo_number_mismatch |
| VSNT | under | 132.65/134.45/145.30 | 31.62 | 9.4% | beyond reach |

Scorecard: all 12 results; loops 0; **incoherent 0**; **coherent 1/9** (MSGE); median spread 16.8%; direction 8/9; pull n/a (no unverified revision);
memo verdict mismatches 0. Readers agreed 34/36; DAC c2 and ITGR c2 adjudicated questionable. Recurring faults: normalized premiums argued from a
half-year / one peak year / a figure not in the dossier; adjusted-basis facts defending GAAP margins; memo prose contradicting inputs; the memo arguing
the analyst's own growth label after code replaced it. Canary: zero pull on all 4 names.

## 4. Iteration 4 (pack revision 28: stage SYSTEM messages; the only change) — FAIL

| Name | Base values | Spread | Notes |
|---|---|---|---|
| MSGE | 36.92/36.71/34.25 | 7.3% | |
| TASK | 17.76/18.63/17.32 | 7.4% | memo_number_mismatch (verifier false positive, fixed post-freeze) |
| DAC | 501.50/469.24/444.53 | 12.1% | path_dominated |
| BUD | 104.55/91.87/89.27 | 16.6% | memo unknown fact id |
| GOLD | 63.20/43.75/99.25 | 87.8% | |
| MCY | 227.24/213.46/258.96 | 20.0% | |
| ITGR | 75.75/79.35/82.36 | 8.3% | memo_number_mismatch (false positive) |
| DAR | 214.78/264.40/180.91 | 38.9% | beyond reach |
| VSNT | 142.94/114.27/106.34 | 32.0% | beyond reach |

Scorecard: incoherent 0; **coherent 0/9**; median spread 16.6%; direction 8/9. Readers agreed 28/36; 8 adjudicated (`runs_p4r26/4/adjudication.json`).
Side by side with iteration 3: stage-2 prompt tokens 1.07M → 0.92M (−14%); stage-3/4 output −38%/−25%; runtime 392 → 368 min; unknown fact ids 4 → 2;
GOLD Base/price 3.8× → 1.6×, VSNT 4.25× → 3.6×. MSGE lost "coherent" by setting a 14.0% margin above its record maximum 13.5% and calling it supported.
Verified: stage-2 SYSTEM hash `5151fc13…` = the new stage text (old charter `ff033c25…`); MSGE stage-2 prompt 34,605 → 20,349 tokens. Canary: zero pull.
**Reading (no winner on score, per Amendment 3):** the charter was a real defect, removed on its merits; it was not the coherence problem.

## 5. Value/price pattern
Iteration 3 median Base/price: MSGE 0.49, ITGR 0.63, BUD 1.14, MCY 2.30, TASK 2.31, DAC 3.09, DAR 3.67, GOLD 3.80, VSNT 4.25. Seven of nine
"undervalued", five by 2-5×.

## 6. Verifier false positive (found 10-23)
The frozen table prints 5.25% as "5.2%" (Python's round-half-even on an exact binary half) while the verifier rounded it half-up to 5.3 and flagged a
memo that copied the table. Fixed in `c255803` (the verifier accepts the printed form).

## 7. Offline engine measurement (iteration 3 frozen forecasts; every stored median Base value reproduced exactly)
Files: `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\handoff_artifacts_2026-10-23\engine_measurement_defects\` (measure.py, probe.py,
results.json; copied from the session scratchpad, which is temporary).
- **Where kappa enters:** `r26_stages.py:1119` base_cf = facts["owner_earnings_default_b"]; `financial_model_tool.py:2111-2112` (`_bridge_build`, 25.2)
  `kappa = base_cf / (rev_L * x_L)` and `oe_t = kappa * R_t * m_t` for years 1-5; `:585` the same; **`:597-606` the long run starts from
  `e5 = R5 * m5` WITHOUT kappa** → a cash-flow jump at year 6 (DAR 4.99 → 0.85; MCY 1.34 → 0.54; MSGE 0.18 → 0.064; DAC 0.43 → 0.54 upward).
- kappa per name: MSGE 1.31, TASK 0.94, DAC 0.64, BUD 1.19, GOLD 1.02, MCY 1.75, ITGR 1.06, **DAR 4.53**, VSNT 0.97.
- **kappa = 1:** DAR −48% (3.67× → 1.89× price), MCY −16%, DAC +11%, others within 6%.
- **Tax floor 21%/25% (DAR raw −15.3% clipped to 0):** DAR −18%/−21%; MSGE (raw 38.1% clipped to 35%) +4-6%.
- **VSNT terminal growth 0 / −2% (shrinking every Base year):** −3% / −6.5%.
- All on DAR: 1.21-1.26× price. **After all fixes the big gaps remain:** DAC 3.1×, GOLD 3.1×, VSNT 4.2×, TASK 2.1×, MCY 1.6×: they come from the
  forecasts (DAR's 21% year-1 margin vs a filed 4.5%; VSNT 20%+ margins while shrinking; GOLD's growth), not the desk.

## 8. Baseline A: the screener alone, point in time (10-23)
Report: `C:\Users\riper\stocks\stocks-workspace\scratch\baselineA\REPORT_baselineA.md`; data `scratch\baselineA\data\s5_yahoo.json` (main), `s5_sic.json`
(SIC check), `s5_census.json` (survivorship sensitivity); scripts `scratch\baselineA\scripts\s1_prices.py`..`s5_backtest.py`, `probe_pit.py`.
- Method: the production `score_factors_dual_door.py` (screener-publish copy = origin/main) run unmodified at each month-end on point-in-time inputs
  (gate-1 harness fundamentals filed before T; D5 daily bars ≤ T); EPS revisions not reproducible (no history); cost-of-equity anchor approximated;
  survivorship handled in a sensitivity run with the harness census (three bounds).
- research_now (~58 names) vs the investable universe, annualised: **2017-22 excess −1.2% (factor alpha −1.9%)**; **2023-24 +14.4% (factor alpha +13.4%,
  t 3.2)**; 2025 (11 m) +2.2%; **all 9 years +2.5% (t 1.0), factor alpha −0.1%**. Net 60 bp: +0.4%. Turnover ≈3.2×/yr. Return 12.8% vs universe 10.3%
  vs SPY 15.0%; Sharpe 0.56 vs 0.44; max drawdown −38% vs −34%.
- Three bounds (whole window): excluded +3.1% excess / −0.0 alpha; −100% bound +7.9% / +7.1 alpha (t 2.5, a stress case); last close +4.2% / +0.9.
- Reading: a factor tilt (momentum, value, short-term reversal), not a stock picker; edge only in 2023-24; fails `SPEC_rebuild` Addendum Z 10's bar.
  Spot-checked by the coordinator against `s5_yahoo.json` (2017-22 excess −1.23%, turnover 3.28).

## 9. Earlier measurements that shape the picture (from before this window; verify in `SPEC_rebuild.md`)
- Gate 1 holdout (2023-24, frozen engine `c7d7a4f`): B1/B2 failed under all three bounds (residual spread −1.1/−4.6/−2.9%); B3 level passed (0.70×);
  B4 failed only on financial ROTE by 0.0002; B5 failed.
- Gate 1b (2025, revised engine: mean of draws, survival layer, commodity out): H1/H2 strong pass, H3 fail (margins); audit: edge mostly value/size,
  ≈0 incremental in 2025; almost entirely from four 2020 COVID dates; ≈0 across 2022-2025.
- Forecast study (Addendum AB): code revenue forecasts no better than the population median; margins a small edge through 2024, worse in 2025; ROTE a
  real edge.
- Muse gate 2: run 1 invalid (format failures), run 2 completed; gate 2b registered (scoring 2027-04-15).

## 10. Qwen 3.8 knowledge cutoff (10-23)
Report `C:\Users\riper\stocks\stocks-workspace\scratch\qwen_cutoff\REPORT_cutoff.md` (+ raw Q/A JSON). Estimate **mid-April 2025** (band 2025-02..06):
~85% correct through 2024-12; thinning to early April 2025 (DeepSeek, Stargate, Carney, 9 April tariff pause known); nothing from 21 April 2025
(believes Pope Francis alive); no genuine knowledge from 2025-10 (calls it "the future"); self-reports unreliable. AI rungs: historical tests only on
dates from 2025-10; 2025-05..09 only with a leakage caveat.

## 11. Monitoring evidence (Phase 6, Muse Glimmer; from STATUS.md and `PHASE_6_FOLLOWUP.md`)
Test A (constructed thesis breaks, 73 cases): 0 of 36 breaks missed, 1 false alarm of 37 (fixed). Test B (real past events): **6/20 strictly (8/20 on
manual review) vs an 18/20 target** (operator: non-blocking; B2 retest gathers news daily via task `RS2-B2-Gather-P6`). Test C (shadow week): day 1 ok,
day 2 void, paused. Qwen's monitoring has never been measured.
