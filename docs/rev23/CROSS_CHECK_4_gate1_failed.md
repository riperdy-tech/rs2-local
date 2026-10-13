# Cross-check request 4: the code-only engine failed its frozen test. What next?

You reviewed this project three times: the architecture, the point-in-time data rules, and the pass bars. This is the
result of the frozen test you helped design, and the decision it forces. Everything you need is below.

## 1. Reminder
- **The goal:** a local AI analyst (Muse Glimmer 30B on one 24 GB GPU) whose intrinsic values are good enough for
  real-money stock selection. The AI chooses inputs and Python computes.
- **Gate 1:** before any AI work, the code-only engine had to show it adds information beyond simple yardsticks.
  - **The engine:** three valuation families (operating layered DCF, financial excess return on tangible book,
    commodity mid-cycle). It uses population priors measured point in time, Damodaran betas relevered by each company's
    debt, and an "engine-consistent" equity risk premium: Damodaran's monthly implied ERP, adjusted by the change his
    own model gives when his analysts' 5-year growth is replaced by the engine's population growth.
  - **The value:** the median of 2,000 Monte Carlo draws, every judgment input at its prior P50.
- **The bars,** registered and approved before the run:

  | Bar | Rule |
  |---|---|
  | B1 | Pooled regression of 12-month excess return on the rank of IV ÷ price plus five yardsticks (earnings yield, FCF yield, gross profitability, return on capital, 12-1 momentum), with industry and date effects. The one-sided 90% wild-cluster lower bound must be > 0. |
  | B2 | The residual top-minus-bottom quintile spread must be > 0. |
  | B3 | The universe median IV ÷ price must lie in [0.67, 1.5]. |
  | B4 | The P50 forecast must beat the naive baseline. |
  | B5 | Directions must hold under all three survivorship bounds and with the top 1% of residuals removed. |

- **The test:** 24 month-ends, 2023-01 to 2024-12, run once, with every input hashed in a freeze file.
- **Survivorship:** companies that later delisted were found from SEC records. They were priced from cover-page public
  float, and their outcomes were taken three ways: excluded, −100% for distress exits, and last close.

## 2. Development evidence before the freeze (2020–2021 only; earlier dates lacked the history the priors need)
On 24 development month-ends:
- **B1:** +0.082, lower bound +0.051.
- **B2:** residual spread +3.4% (a strong pass).
- **B4:** passed.
- **B3:** failed at first (median 0.54× price). It passed only after the engine-consistent ERP brought it to 0.62×;
  it still failed in development.

## 3. The frozen test result: FAIL

| Bar | Excluded | −100% | Last close |
|---|---|---|---|
| B1 coefficient (lower bound) | +0.005 (−0.020) | −0.026 (−0.048) | −0.022 (−0.043) |
| B2 residual spread | −1.14% | −4.58% | −2.86% |
| B3 level | 0.70 pass | 0.70 pass | 0.70 pass |
| B4 | revenue growth error 0.070 against naive 0.095 (operating), 0.122 against 0.246 (commodity); margin passes; financial ROTE 0.0378 against 0.0376 fails | — | — |
| B5 | fails | fails | fails |

**Other figures:**
- 31,903 company-dates at $300M or more.
- 41.7% of stocks fall outside 0.4×–2.5× their price.
- Family medians:

  | Family | Median IV ÷ price |
  |---|---|
  | Operating | 0.55 |
  | Financial | 1.67 |
  | Commodity | 0.47 |

- The engine's ranking failed under ERP ±1 pp, under Damodaran's own ERP, and sector-neutral. Size-neutral B2 was
  +0.75% with exclusion only.

## 4. The coordinator's reading
1. **The engine forecasts fundamentals much better than naive** (revenue growth error about 25% lower), but its value ÷
   price ranking added nothing beyond the five yardsticks in 2023–2024. Development's edge was one regime (the 2021
   value rebound); 2023–2024 was a strong growth-over-value regime.
2. **The survivorship bounds made it worse** (−4.6% at −100%): companies that later failed sat in the cheap quintile.
   The engine has no view of distress, the classic value trap.
3. **The level is now right** (0.70×).
4. **Beating naive is not beating the price.** The market prices consensus-like expectations. An engine better than
   naive but no better than consensus has no edge in returns.

## 5. The options
- **A. A new code round, then a new holdout.**
  - Name a new holdout now: month-ends 2025-01 to 2025-09, with 12-month outcomes through 2026-09, which exist.
  - 2020–2024 becomes development, since 2023–2024 is spent.
  - Investigate structural causes: a distress and solvency layer (probability of failure for levered, cash-burning
    names), and how forecasts map to value (a terminal value carrying about 60% of value; the median of draws).
  - Muse waits.
- **B. Run gate 2 (Muse against code, paired) now anyway,** as a diagnostic. Muse's job (reading filings for
  distress, moats, one-offs) is exactly what the code lacks. Cost: 5–7 GPU-days, and only 3–6 months of outcomes are
  available, so it has low power.
- **C. Conclude** that a filings-only intrinsic-value engine, as built, has no edge over simple factors, and redesign.
  For example, judge the system on forecasting fundamentals better than the market's implied expectations (reverse
  DCF) rather than on beating yardsticks.

## 6. Questions
1. Is the reading in section 4 right? What else could explain development passing and the holdout failing?
2. Which option (A, B, C, or another), and why?
3. If A: which structural changes are principled rather than fitted to the failure? How do we avoid "fixing" the
   engine toward 2023–2024 (which is now development)?
4. Is the new holdout (2025-01 to 2025-09, 9 month-ends, 12-month outcomes) big enough to decide anything? If not, what
   is?
5. Given that the code forecasts fundamentals well but its value does not predict returns, is "intrinsic value ÷
   price" the right output for this system at all? What would you build instead to make money from better forecasts?
