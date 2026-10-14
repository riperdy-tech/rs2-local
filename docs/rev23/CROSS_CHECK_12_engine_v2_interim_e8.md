# Cross-check request 12: engine v2's interim fix, its new sanity check, and the data fixes. What is wrong?

## Background

You reviewed earlier cross-checks; your rulings are in SPEC_rebuild. This request covers fork 2's work since cross-check 10:

- the data-layer fixes;
- engine v2's point-in-time rebuild;
- a defect found in engine v2;
- the interim fix the operator chose;
- a new registered check, **E8**, and the method of the oracle check **E5**.

**Status: E8 and E5 have not been run on the interim engine (v2.0.2).** Their runs may compute, but the verdicts stay unopened until your
answers are ruled on (AL.31). That leaves room to change a bar or a method.

Two disclosures:
1. Diagnostic numbers for v2.0.1 exist on 2 of E8's 20 dates. They were run after E8's bars were fixed, and those 2 dates are excluded
   from E8's verdict (AL.28, AL.29).
2. The financial continuation was coded before its rule was written; the rule as built is in AL.28.

**How to answer:** critique freely; the coordinator decides. The most useful answer is a list of problems ranked by how much each could
hurt a real-money decision. Where a claim rests on code you cannot see, say so rather than assume.

## Documents

- **`SPEC_rebuild.md`:**
  - addenda AL.10–AL.12: engine v2's point-in-time tables;
  - AL.17, AL.18, AL.20, AL.21 and AL.32: the fiscal-year fix and its rebuild;
  - AL.22 and AL.23: the outcome definition;
  - AL.24: the E5 method;
  - AL.25–AL.31: the defect, v2.0.1, v2.0.2 and E8;
  - fork 1's AK.44, AK.45, AK.47 and AK.48: the rulings on earlier outside reviews of this work.
- `PROBLEM_REPORT_fiscal_year_mislabel.md` and `PROBLEM_REPORT_revenue_tag_seams.md`
- `REGISTRATION_engine_v2.md` (E1–E7) and `SPEC_engine_v2.md`
- the code: rs2-local `review-2026-10/gate2-run2`:
  - `valuation/near_term.py`, `engine_operating_v2.py`, `engine_financial_v2.py` (v2.0.2 at 53e7a59);
  - `rebuild_harness/forensics/e5_v2.py` and `e5_score.py`;
  - `valuation/pit_data.py` (the FY fix, 8155188 and 688281f).

## 1. The engine-v2 defect and the interim (most important)

### What was found (AL.25–AL.26)

**The defect.** v2's years 4 and later continue growth as `g_T + (g_3 − g_T)·d_t/d_3`. The measured decay curves `d` are non-monotone,
so `d_t/d_3` reached 2–158×. The financial chain did the same with `ρ_t/ρ_3`, and divided by the fade factor `φ_3`.

**The effect, on 600 companies at 2021-06-30:**
- P90/P50 of equity rose from v1's 2.7 to v2's 17.7 at the median company, and to 526 at the 90th-percentile company;
- 4.8% of draws were invalid.

### v2.0.1 (AL.27, AL.28)

**The rule:** every continuation ratio uses the curve's running minimum. So `1 ≥ λ_4 ≥ λ_5 ≥ … ≥ 0`, where `λ_t` is the multiplier on the
year-3 deviation. Tests cover zero and near-zero denominators, both signs, and a monotone curve, where v2.0.1 equals v2.0 and so v1.

**Result:** invalid draws fell to 0. But the top-1% share of the mean stayed high:
- 2021 operating: 0.242, against v1's 0.062;
- 2021 financial: 0.197, against v1's 0.023.

### Attribution (AL.28)

Collapsing one variable's residual spread at a time showed that **the growth residuals** (revenue growth; tangible-book growth) carry the
whole remaining tail. Margin and ROTE carry none of it.

A graft of tag-consistent tails onto the growth residuals left the tails as heavy (AL.29). So the extremes are real reported growth
(acquisitions, rebounds, share issuance), not measurement error.

### v2.0.2, the interim (AL.30, operator-confirmed in AL.31)

**What it does:** the growth residuals' P1 and P99 are set to P5 and P95 before the draw. It is labelled "interim: unmodelled financing
approximated by clipped growth tails". P10–P90 and every reported forecast are unchanged.

**Its effect on the 2 diagnostic dates:**
- the top-1% share is within 2× of v1's;
- means are 5–26% lower;
- P50 is unchanged.

**The end state** is financing-aware growth (a registration still to come): growth above reinvestment ÷ ROIC is charged with dilution at
the current price.

### Questions

- **Q1.** Is the running-minimum envelope the right repair of the continuation? Does it distort any case where a curve should legitimately
  rise (a recovery)?
- **Q2.** Is clipping the growth tails a defensible interim, given that it lowers mean_iv by 5–26% and so moves the verdict's direction and
  the H-S1 selection signal? Would you have chosen (b), a mean of draws capped at their own P99, instead? Or no interim, waiting for the
  financing-aware version?
- **Q3.** v2 still under-covers in shock years (E3 FAIL, accepted earlier), and the clip narrows the draws further in the tails. Is that a
  problem for gate 2b's calibration bar (B4)?
- **Q4.** Is the AL.28 attribution, made by collapsing one variable at a time, sound? Could an interaction (the copula across years 1–3)
  be mis-attributed?

## 2. E8, the valuation-sanity check (AL.27, AL.28, AL.29)

**Measures, per name** (v2 against v1, measured in the same run):
- invalid draws;
- the top-1% share of mean equity;
- EV P90/P50;
- P50 v2/v1.

**Bars, per family:**
- invalid draws = 0 in every name;
- the top-1% share: median ≤ 2× v1's, and 90th percentile ≤ 2× v1's;
- EV P90/P50: median ≤ 2× v1's;
- P50 v2/v1: median in [0.5, 2].

**Samples:**
- the 18 forensic quarter-ends not used to choose the interim (2020–2024; 2021-06-30 and 2024-06-30 excluded);
- gate 2's 2026 company-dates valued with the vintage-2025 tables.

Both samples must pass, pooled and in each year.

### Questions

- **Q5.** Are these bars the right test that mean_iv is not tail-dominated? Is a 2× multiple of v1 too loose, or too tight, given that v2
  draws its own measured residuals while v1 draws narrower priors?
- **Q6.** v1 is the reference only. Is anything missing that would catch a v2 that is "within 2× of v1" yet wrong, such as a test against
  realised value?
- **Q7.** Should E5 and E8 run on the original point-in-time tables (`priors_v4_pit`, as registered) or on the rebuilt `priors_v4_fy`
  (AL.32), which gate 2b is recommended to use?

## 3. E5, the oracle (AL.24)

**The method.** v2 and v1 are valued on the same realised information: years 1..min(K, 3) realised, and the long-run margin realised when
K ≥ 5. The score is ln(value/price). The statistic is the rank IC with 3-month excess return, residualised on five yardsticks and the Y1
controls, industry-demeaned.

**Bars:**
- v2 ≥ v1 − 0.02, pooled and in each year, under each bound;
- no family's sign inverted.

### Questions

- **Q8.** Is restricting both engines to k ≤ 3 the right fairness rule? Does it bias E5 toward passing?
- **Q9.** Is the 3-month horizon right for an oracle built from up to 5 years of realised fundamentals?

## 4. The data fixes and engine v2's rebuild

**Fiscal-year mislabels (AL.17, AL.18, AL.32).**
- **The defect:** a forward-dated fact relabelled about 0.5% of annual reports. The fix bounds a report's period by its filing date.
- **Checks:** 529 → 0 mislabels in the affected companies; 21/21 matches against SEC's "Period of Report".
- **The rebuild** shifts the priors only slightly. But the growth-decay curves at long horizons move by up to 1.0, so they are unstable.

**Engine v2's point-in-time tables (AL.10–AL.12).** Each vintage now reads only its own extraction. Before, it read later extractions
filtered by filing stamps, which leaked through the tag choice and the mislabels.

**The outcome definition (AL.22, AL.23).**
- **Measured:** first-filed growth misstates 4–6% of outcomes by more than 5 points, about 76% of them recasts.
- **Ruled by the operator:**
  - engine v2 keeps first-filed residual tables, which cover better and have equal P50 accuracy on tag-consistent outcomes;
  - gate 2b scores tag-consistent outcomes.

### Questions

- **Q10.** Is there any remaining look-ahead route in the per-vintage build, or in the filing-date bound on a report's period?
- **Q11.** Is keeping first-filed residual tables while scoring on tag-consistent outcomes coherent? Or does it bias gate 2b's B4
  calibration?
- **Q12.** The long-horizon decay curves are noisy enough that a few hundred corrected rows move them by up to 1.0. Should v1 and v2 use a
  monotone or smoothed estimator before gate 2b? Or is the v2.0.1 envelope enough?

## What is not asked here

- the gate-2 result (AK.35);
- the S5 fit;
- the downstream changes (cross-check 11).
