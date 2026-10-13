# Distress layer v2 registration — DRAFT v2, 2026-10-13 17:45: a survival model that earns its place

Recovery plan S6; remaining-work plan B5; definition of done D5. Written before any candidate is built or measured.

**Revision v2 (SPEC_rebuild AK.19, after the ChatGPT and Gemini reviews of cross-check 9):**
- the complexity order is corrected, and a more complex candidate must beat a simpler one by a paired bound (section 4);
- the fresh-date read becomes two-stage, set by precision (section 5): monitoring from 30 independent events, a decisive read at 100;
- a calibration bar is added, because D5 requires it;
- what is in force before and after the read is stated (section 6);
- integration follows the verdict contract v4 mixture (section 7);
- a 36-month diagnostic is added.

## 1. What exists, and why it is not enough

The current layer (Stage 2 V2, Addendum V):
- **Formula:** value = mean IV × P(survive 12 months), with equity recovery 0 on failure.
- **Model:** P(fail) is a logistic model on six point-in-time solvency variables: current ratio, net debt ÷ EBITDA, interest
  coverage, the operating-cash-flow sign, cash runway, and the naive distance to default from daily prices.
- **Training:** walk-forward on D1 bankruptcy and distress-exit events within 12 months, using only events resolved before T.

**The measured weaknesses:**
- **AUC 0.65.**
- **Its scores correlate 0.9999 with the value ranking without it**, so it barely moves anything (Addendum W).
- **The least-solvent tercile of the engine's ranking still inverts:** −9.4 at 12 months (Addendum U F4).

D5 requires that the least-solvent tercile does not invert and that the default model is calibrated.

## 2. The candidates (fixed now; nothing is added after a result exists)

| # | Candidate | Features (all point in time, filed before 16:00 ET on T; prices up to T) |
|---|---|---|
| C0 | the current layer | as above (the baseline) |
| C1 | richer solvency | C0's plus: the 3-year change in interest coverage; Altman's components (working capital ÷ assets, retained earnings ÷ assets, EBIT ÷ assets, market equity ÷ liabilities, sales ÷ assets); Ohlson's components (log size, liabilities ÷ assets, working capital ÷ assets, current liabilities ÷ current assets, liabilities > assets, net income ÷ assets, funds from operations ÷ liabilities, two years of losses, the net-income change); the debt-maturity wall (debt due within 24 months ÷ cash plus 12-month operating cash flow), **only if the point-in-time store holds the maturity tags for at least 60% of the panel; otherwise dropped before any fit, and stated** |
| C2 | market-based | C0's plus the Merton distance to default (the iterative KMV-style solution with 12-month daily equity volatility), replacing the naive version |
| C3 | combined | C1 ∪ C2 |
| C4 | Muse's distress flags | going-concern language, covenant breach, liquidity warnings: **registered now as a later candidate**, testable only on dates after Muse's knowledge cutoff, under its own registration |

**Model class:** logistic regression on standardised features (fitted on each training window), with an L2 penalty fixed at λ = 1.
- No hyper-parameter is tuned.
- Missing features are imputed with the training window's median plus a missing indicator, and stated.
- One model class for all candidates, so the comparison is of information, not of flexibility.

## 3. Labels and data

- **Events:** the D1 event index (Addendum P4, all events), first qualifying exit after T within 12 months: bankruptcy, liquidation,
  or a distress delisting (exchange non-compliance Form 25 / Form 15 after distress), by `delistings.classify_exit_events`, unchanged.
  An acquisition is not a distress event; the census bound (Addendum Y2) is reported beside it.
- **Development panel:** quarter-end origins 2012–2024, all built-family companies of market cap ≥ $300M at T. Expanding window: a fit
  at T uses only origins whose 12-month outcome was resolved before T.
- **Fresh panel:** month-ends from 2026-07-31 on, never used for any fit, selection or development decision.

## 4. Selection on development (forecast accuracy only; no return is read)

**The metrics,** walk-forward out of sample, by year and pooled:
- AUC;
- Brier score;
- the calibration intercept and slope (logistic recalibration of the predictions).

**A candidate qualifies when all three hold:**
1. AUC ≥ C0's + 0.05, pooled, and ≥ C0's in at least 70% of the evaluable years (a year is evaluable when its training window holds at least 30 resolved events);
2. Brier ≤ C0's, the paired difference's one-sided 90% bootstrap upper bound (resampling years) < 0;
3. calibration slope within 0.8–1.2 and intercept within ±0.3.

**The selected candidate:**
- **Complexity order,** by feature count: C2 < C1 < C3. C2 replaces one of C0's six features; C1 adds about sixteen.
- **Start with the simplest qualifying candidate.** A more complex qualifying candidate replaces it only if their paired Brier difference
  has a one-sided 90% bootstrap upper bound < 0 (resampling years, 2,000 resamples, seed 20261013). The comparison is made in the order
  above. A small pooled difference never decides it.
- If none qualifies, C0 stays and the result is reported.

**Reported, never used in selection:** the same walk-forward AUC and Brier score on a 36-month label (first qualifying exit within 36
months). It shows whether a 12-month model ranks the failures of months 13–36 (Gemini's debt-maturity-wall point). A longer horizon in
the valuation is a later version under its own registration.

## 5. Validation of the selected candidate (read once; never used to change it)

**On development** (reported; returns are read here for the first time, after selection is fixed):
- the gate-1-style residual spread within each solvency tercile at 12 months, with and without the new layer, under the three exit
  bounds;
- the correlation of scores with and without the layer.

**The residual spread, defined.** Gate 1b's H2 statistic (REGISTRATION_gate1b.md): the industry-neutral top-minus-bottom quintile
spread of the 12-month excess return residualised on the five yardsticks with industry and date effects.
- **Here, it is computed within each solvency tercile.** The terciles are formed by C0's P(fail) at T, so membership does not depend
  on the candidate.
- **The ranking variable is `log(mean_iv / price)`:** survival-adjusted under the layer being tested, and unadjusted for the
  comparison.

**Counting fresh events.** An independent event is one company's first qualifying exit. It is counted once, although it appears in up
to 12 monthly origins.

**Uncertainty.** Every fresh-date interval below is a block bootstrap by calendar quarter of origin (2,000 resamples, seed 20261013), so
events sharing a period are resampled together. Every comparison with C0 is paired on the same company-dates.

**Stage 1, monitoring:** from 30 independent fresh events, every quarter. Reported:
- AUC, Brier and the calibration measures, with their intervals;
- the tercile spreads.

No decision is ever taken at this stage, whatever the numbers.

**Stage 2, the decisive read.** Once, at the first quarter-end with **at least 100 independent fresh events** and at least 24 origin
months with matured 12-month outcomes. Like the old 30-event read, this count is expected to take years; the date is recorded at
approval and is never a reason to read early. All of these must hold:
1. **Ranking:** AUC ≥ 0.70, **and** the paired AUC difference against C0 has a one-sided 90% lower bound > 0.
2. **Accuracy:** the paired Brier difference against C0 has a one-sided 90% upper bound < 0.
3. **Calibration** (D5):
   - the calibration slope is within 0.7–1.3;
   - observed ÷ predicted events are within 0.75–1.33 overall;
   - observed ÷ predicted events are within 0.67–1.5 in the top decile of predicted P(fail).
4. **No inversion:** the least-solvent tercile's residual spread is ≥ 0 under the "excluded" and "last close" bounds.

**Precision.** If the AUC interval is wider than 0.15, the read is **inconclusive** and is treated as not validated. A second and final
read is then made at 150 independent events. No other look is ever decisive.

## 6. What may never happen

- A candidate, feature, penalty or event definition chosen or changed after a development metric is seen.
- A return used in selection.
- A ticker-specific override.

**What is in force, fixed now:**
- **Before the decisive read:** the development-selected candidate (or C0 if none qualified), flagged `distress_model_not_validated` on
  every verdict (contract v4 section 8). The flag annotates and never blocks.
- **After a pass:** the selected candidate, without the flag.
- **After a failure or an inconclusive final read:** whichever of C0 and the candidate had the lower fresh Brier score, by this rule
  fixed now, still flagged. A new version is opened under its own registration and its own fresh panel.

A failed candidate is never relabelled as passing, and no candidate, feature or bar is changed after a fresh result is seen.

## 7. Integration

- **Unchanged formula for the mean:** value = mean IV × P(survive 12 months).
- **As a distribution:** the verdict contract v4 section 2a mixture: value 0 with probability P(fail), the going-concern distribution
  otherwise. Its quantiles, its `prob_value_above_price` and its mean all come from that one mixture.
- **Publication:**
  - the P(fail) in force is published in the verdict contract v4 as `prob_fail_12m`;
  - its model and hash are published as `versions.distress_model`;
  - it is graded by TRK-06 against realised exits.

## 8. Audit

- **An independent recomputation** of the walk-forward AUC and Brier score, with code importing nothing from the build.
- **A look-ahead check on labels and features:** every event used in a fit resolved before T, and every feature filed before T. The
  cut-proof method applies.

## 9. Approval record

Not yet approved. It is for the operator. Cross-check 9 was answered by ChatGPT and Gemini, and the rulings are in SPEC_rebuild
AK.19.
