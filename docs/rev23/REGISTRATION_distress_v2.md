# Distress layer v2 registration — DRAFT, 2026-10-13: a survival model that earns its place

Recovery plan S6; remaining-work plan B5; definition of done D5. Written before any candidate is built or measured.

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
- the qualifying candidate with the lowest pooled Brier score, with ties going to the simpler one (C1 < C2 < C3);
- if none qualifies, C0 stays and the result is reported.

## 5. Validation of the selected candidate (read once; never used to change it)

**On development** (reported; returns are read here for the first time, after selection is fixed):
- the gate-1-style residual spread within each solvency tercile at 12 months, with and without the new layer, under the three exit
  bounds;
- the correlation of scores with and without the layer.

**On fresh dates, the decisive bars,** read when at least 30 distress events have accrued on fresh dates (expected around mid-2028;
reported quarterly before then, never acted on):
- AUC ≥ 0.70 and Brier ≤ C0's on the same dates;
- the least-solvent tercile's 12-month residual spread is ≥ 0 under the "excluded" and "last close" bounds (it no longer inverts).

## 6. What may never happen

- A candidate, feature, penalty or event definition chosen or changed after a development metric is seen.
- A return used in selection.
- A ticker-specific override.

A failure of the fresh bars leaves C0, or the selected candidate marked "not validated", in place, and is reported.

## 7. Integration

- **Unchanged formula:** value = mean IV × P(survive 12 months).
- **Publication:** the selected P(fail) is published in the verdict contract (v4) as `prob_fail_12m`, with its model version, and
  graded by TRK-06 (calibration of P(fail) against realised events).

## 8. Audit

- **An independent recomputation** of the walk-forward AUC and Brier score, with code importing nothing from the build.
- **A look-ahead check on labels and features:** every event used in a fit resolved before T, and every feature filed before T. The
  cut-proof method applies.

## 9. Approval record

Not yet approved. It is for the operator, and part of cross-check 9.
