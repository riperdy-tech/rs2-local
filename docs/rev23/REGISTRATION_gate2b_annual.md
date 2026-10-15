# Registration: gate 2b, annual (track 1). Engine v2.1's fiscal-year-1 forecasts at 2026-07-31, scored on the year they forecast.

**Status:** APPROVED by the operator 2026-10-15 13:52 (AK.88). Formerly a draft for the operator's approval (SPEC_rebuild AK.86, cross-check 15). Written on 2026-10-15, before any outcome it scores
exists: every scored fiscal year ends after 2026-07-31, and its annual report is filed in 2027.

## 1. Why, and what it is not
- **Why.** Gate 2b v3 (AK.82) **failed** as a quarterly proxy screen. That failure stands permanently and is reported beside this test.
  Both outside reviewers asked for a test of the quantity the engine actually forecasts: fiscal year 1.
- **What it is not.** It does not re-score, reinterpret or replace gate 2b v3. It is not a return test. A pass is **necessary, not
  sufficient**, for any promotion. Promotion stays the operator's decision, alongside the WACC correction (AK.86 3), the fiscal-year-2
  calibration, and D1–D10.

## 2. The sample and the forecasts (all frozen, AK.80–AK.81)
- **The sample:** the 1,189 companies of the frozen 07-31 census, sample sha256 `f2e47988627ef9e37499a11e4269e4f20b685e3f4792a88bc4ff8c71b2455113`.
- **The forecasts:** the records already written by `gate2b.value` at `284bfe1` under freeze `2908cf71…`:
  - V2 (v2.1) and CODE (v1) fiscal-year-1 P10, P50 and P90 for growth, margin and ROTE;
  - the base year, base levels and base accession.
- **The baselines:** the 07-31 baselines file. PERSIST is the trailing-four-quarter run-rate known at T; POPMED is its median per family over
  the universe file.
- **No valuation is re-run and no forecast is changed.**

## 3. The target
- **Fiscal year 1:** the fiscal year immediately after the base year known at T, by the company's own fiscal calendar.
- **Prospective only:** fiscal year 1 is scored only when its **period end falls after T**. A fiscal year 1 ending on or before T (some
  non-calendar years) is excluded, and counted by family.
- **Measured from the first-filed annual report for that fiscal year**, by the outcome definition of record:
  - **growth and margin change:** `same_filing.annual_measures` (one filing's own comparative columns; revenue verified as total);
  - **ROTE change:** year-1 ROTE minus base ROTE by `build_state`'s definition, **with a denominator guard** (AK.86, the q1 ROTE defect).
    Excluded and counted: base or year-1 tangible equity ≤ 0, or |ROTE| > 1.0 in either year.
- **The scoring date is 2027-04-15**, after the 10-K deadline and its 15-day extension for fiscal years ending 2026-12-31.
  - A fiscal year 1 not first-filed by then is missing by the fiscal calendar, and reported by family.
  - There is one scoring and no re-scoring.
- **Public availability:** an annual result is excluded when public before T through an 8-K with Item 2.02 or 7.01, or the annual report
  itself. None is expected, given the prospective rule.

## 4. The bars (each decided bar must pass)
- **The statistic and inference are gate 2b v3's:**
  - per bar, the median of d = |A − y| − |B − y|;
  - A beats B when the median is < 0 and the one-sided 90% upper end is < 0 under **both** the SIC-2 industry-cluster bootstrap (industries
    with fewer than 5 pooled per family) and the company bootstrap;
  - 2,000 draws, seed 20261013.
- **B2:** V2 beats PERSIST and POPMED on annual growth and margin change; V2 beats PERSIST on the ROTE change.
- **B3:** V2 beats CODE on all three.
- **B4a, coverage:** V2's fiscal-year-1 P10–P90 covers 80% ± 7 of outcomes for each measure, with neither tail holding more than 15%.
- **B4b, sharpness:** the paired median interval score at α = 0.2 (V2 against CODE) is ≤ 0.
- **Minimum paired n:** 200 for each operating measure, 100 for ROTE. Below it, the bar is NOT DECIDED.
- **The verdict:** FAIL if any decided bar fails; else NOT DECIDED if any bar lacks its sample; else PASS.
- **Reported, not bars** (pre-registered diagnostics, cross-check 15):
  - MAE and the upper-tail loss (P90 of |error|) per arm;
  - errors by forecast gap (V2 − PERSIST), size tercile, family, SIC-2 and filing delay;
  - the discount-spread decile;
  - the selection reconciliation of scored against census;
  - the 07-31 q1 FAIL beside it.

## 5. Audit before any report
- the coordinator's independent recomputation (`independent_g2b.py`, extended for the annual target);
- look-ahead: every outcome first filed after T;
- the register of exclusions with SEC timestamps;
- a 20-outcome hand check against the filed 10-Ks;
- the reconciliation of the census to the scored sample.
