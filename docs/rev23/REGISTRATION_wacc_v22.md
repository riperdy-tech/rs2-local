# Registration: the corrected discount rate, engine v2.2 (DRAFT rev 2, fork 2, 2026-10-15)

**Status:** a draft for the operator, written before any number from the candidate exists.
- It answers fork 1's AK.86 item 3.
- **Revision 2** applies the rulings on cross-check 16 (Gemini, ChatGPT), recorded in SPEC_rebuild AL.54. Revision 1 (commit 547a536) is
  superseded.

## 1. The problem (SPEC_rebuild AL.51–AL.53)

Three mechanisms pull v1's and v2's WACC towards terminal growth g_T. Near it the terminal value explodes, and at WACC ≤ g_T every draw is
invalid.

1. **The effective cost of debt has no floor.** It is interest ÷ average debt: negative for MAN (−7.41%, netted interest), 0.41% for FOUR
   (convertibles), and below rf for 25–31% of operating names in 2022–23.
2. **D/E is book D/E.** Buybacks inflate it (PEP 2.41, MA 2.46), and Hamada is defined on market D/E.
3. **The engine-consistent ERP can be very low when rates are low** (2020-03-31: cost of equity about 1.4%).

**Size:**

| Sample | WACC ≤ g_T + 2 pts | WACC ≤ g_T |
|---|---|---|
| Forensic sample, operating, 2020–2024 | 6.4% | 0 |
| 07-31 census | 10.4% | 2 names (MAN, FOUR) |

`discount_rate.py` is a frozen gate-2 file. The fix is a new module, **`valuation/discount_rate_v2.py`, used only by engine v2.2.** v1, gate 2
and v2.1 stay byte-identical. The callers (the census harness, the live runner) build the discount rate through it for v2.2. Gate 1's
substitution of the industry D/E for an extreme book D/E is not used by v2.2: market D/E replaces it.

## 2. The candidate, fixed now (D)

### (a) Market-value weights (operating family)

- **D** = total debt including finance leases on the **latest balance sheet filed before T** (10-Q or 10-K, as-known).
- **E** = the price at T × the point-in-time share count.
- D/E_market = D ÷ E. Hamada relevers the industry's unlevered beta on D/E_market; the WACC weights are at market.
- **Refusals, each named:**
  - no price or no share count: `discount: no market capitalisation`;
  - no balance sheet before T.
- **Feasibility (checked before the build):** if the store cannot give the latest quarterly debt as known at T, the latest annual balance
  sheet is used and the row is flagged `debt_annual_only`. The share is reported.

### (b) Cost of debt: rf plus a point-in-time synthetic-rating spread (operating family)

- **Interest coverage** = operating income (EBIT, base fiscal year) ÷ **gross** interest expense (base fiscal year).
- **The rating table is point in time:** Damodaran's archived table of January of year(T) (`pc/archives/bondspreadsYY.xlsx`, one per January
  2014–2025; the live page for 2026). It is downloaded under the standing Damodaran approval and hashed in the manifest.
  - **One table for every operating company:** the large non-financial-firm thresholds. That avoids a $5B cliff and a second table of
    another vintage.
  - The rows (15 ratings from D to AAA) and their default spreads d_r are read from that January's file, never refit.
- **The spread at T:**
  - **Investment grade (AAA to BBB)** is interpolated between two market anchors, the last observations strictly before T:
    `s_r(T) = AAA10Y(T) + w_r · (BAA10Y(T) − AAA10Y(T))`, with `w_r = (d_r − d_AAA)/(d_BBB − d_AAA)` from the table.
  - **Below investment grade (BB+ to CCC) is additive over Baa:** `s_r(T) = BAA10Y(T) + (d_r − d_BBB)`, with d from the January table of
    year(T). It is not multiplicative, so a stressed Baa level is not amplified 17-fold.
  - **Distressed (CC, C and D, which includes EBIT ≤ 0):** the CCC spread, flagged `distressed_debt`. There is no extrapolation beyond CCC.
  - **Fallback without the second anchor** (if `AAA10Y` is not approved): `s_r(T) = BAA10Y(T) − (d_BBB − d_r)` for investment grade,
    floored at d_AAA.
- **k_d = rf_T + s_r(T).** By construction it is never below rf_T + s_AAA(T).
- **Interest-line handling:**
  - the gross interest expense where the filings carry a separate gross figure;
  - a net-of-interest-income figure is never used, and a negative value is never used;
  - **a materiality exception:** if D/(D+E_market) < 5%, a missing or unusable interest line does not refuse the valuation.
    k_d = rf_T + s_AAA(T), flagged `kd_immaterial_floor`. A 200-bp error in k_d then moves WACC by less than 8 bp after tax;
  - otherwise a missing reliable gross interest is **refused**, named.
- **Zero debt:** k_d is unused.

### (c) A minimum spread over terminal growth (both families)

- Operating: refuse if WACC − g_T < **2.0 points**.
- Financial: refuse if k_e − g_T < 2.0 points. The financial terminal value is `κ · max(ROTE_ind − k_e, 0) · TBV / (k_e − g_T)`, so the same
  denominator can explode.
- The rule applies **after** (a) and (b). It refuses and never adjusts; every refusal is named and kept in the measurement.

### (d) The financial family's cost of equity is unchanged

k_e = rf + the industry's levered beta × ERP, as today, with no Hamada relevering. Only rule (c) is new for financials.

### (e) Unchanged

rf, the betas, **the ERP**, the tax rate, g_T and everything else. **v2.2 = v2.1 with `discount_rate_v2`.**

Mechanism 3 is guarded here only by rule (c), which catches a collapse to within 2 points of g_T but not an ERP understated by less.
**A separate ERP registration is a condition for real money** (see section 4).

## 3. The test (fixed before any number exists)

**Point in time.** Every input is as known at T:
- the January table of year(T);
- `AAA10Y` and `BAA10Y` before T;
- prices and filings before T.

The 2020–2024 test is therefore a point-in-time test, not a retrospective one. FRED spread series are not revised in a way that matters;
that assumption is stated.

**Bars, unchanged:** E5 and E8 re-run in full on v2.2 on their registered samples (the forensic sample with priors_v5 + priors_v4_fy, and the
run-2 2026 contexts), against v1 as registered.

**Reported, not barred** (methods fixed now):
1. **v2.2 against v2.1:** E5 and E8 measures on the names both value.
2. **Cohort split (Gemini).** The "defect cohort" is v1 k_d < rf, or book D/E ≥ 1, or v1 WACC − g_T < 2 pts; the clean cohort is the rest.
   Both are reported for E5 (v2.2, v2.1, v1) and for E8's P50 ratio.
3. **Price perturbation (ChatGPT).**
   - With forecasts held fixed, each name is re-valued at the price × 0.8 and × 1.2.
   - Reported: the change in D/E_market, β_L, WACC, value and value/price.
   - Expected direction: with fixed k_d, a lower price raises D/(D+E) and lowers WACC whenever `s(1−t) < t·(rf + β_U·ERP)` (Gemini's
     algebra, verified), so the result is reported against that direction.
   - Also reported: the same names on the industry D/E as a target capital structure.
4. **Rate calibration (ChatGPT's accuracy question).**
   - Synthetic k_d is compared with the stated interest rate of debt the company itself issued in the 12 months before T. The source is the
     SEC XBRL `DebtInstrumentInterestRateStatedPercentage`, with the issuance dates of the instruments (standing SEC approval).
   - Reported: the median absolute error, the rank correlation, and coverage.
   - **Limits, stated:** stated coupons are only a partial proxy for yield, and only issuers are covered. Without broader market-yield
     data, accuracy is not claimed beyond this.
5. **Monotonicity (Gemini):** v2.2 WACC against realised 1-year volatility and against market D/E, rank correlations, beside v1's.
6. **Coverage:** refusals by reason, year and family, and the rows flagged `kd_immaterial_floor`, `distressed_debt` and
   `debt_annual_only`. Coverage is an operating condition.
7. **Tails:** the distributions of k_d, market against book D/E, WACC, WACC − g_T, the implied terminal multiple (1/(WACC − g_T)) and the
   terminal-value share.
8. **Sensitivities, none of which replaces a registered choice:**
   - the 2-point rule at 1.5 and 3.0;
   - the coverage from 3-year aggregate EBIT ÷ 3-year aggregate gross interest;
   - the investment-grade ladder without `AAA10Y` (the fallback).
9. **The ERP:** implied ERP and k_e − rf by rate regime (rf < 1.5%, 1.5–3%, > 3%), as the evidence base for the separate ERP registration.
10. **The 07-31 census:** all of the above that need no outcome.

**The identity check:** v2.2's year-1–3 forecasts equal v2.1's on every E8 name, since the discount rate does not enter them. Gate 2b's q1
bars carry over.

## 4. What adoption means

- **If E5 and E8 pass:** v2.2 is frozen and is a candidate for paper operation (the operator decides).
- **Real money additionally requires:**
  - the separate ERP registration;
  - an acceptable rate calibration (item 4) or an explicit operator acceptance of its limits;
  - an acceptable coverage share.
- **If either check fails:** diagnose; no bar changes; v2.1 stays. AK.83 stays open.

## 5. For the operator

1. **Approve the download of FRED `AAA10Y`** (Moody's Aaa − 10y, history since 1983) for the investment-grade anchor. Without it, the
   fallback ladder in (b) is used.
2. **The 2-point rule:** both reviewers support 2.0, applied after the corrections. Confirm.
3. **Interest lines:** both reviewers support gross interest where filed. Gemini adds the materiality exception below 5% debt weight, adopted
   in (b). Confirm.
4. **Approve the registration.**

No number from candidate D exists at the time of writing.
