# Cross-check request 5: what we learned after the failed gate, and an audit that cut the result down

You reviewed the gate-1 failure (cross-check 4). This reports what was done since, including a result that first looked
strong and then shrank under an adversarial audit. Everything you need is here. Critique freely; the coordinator
decides.

## 1. Reminder
- **The goal:** a local AI analyst (Muse Glimmer 30B, one 24 GB GPU) whose stock valuations are good enough for real
  money. Python computes values; the AI places each company's inputs inside population distributions, with quoted
  evidence from its filings.
- **The code-only engine:** three valuation families, population priors measured point in time, Damodaran betas,
  2,000 Monte Carlo draws per company.
- **Gate 1 (2023–2024):** failed. The value ÷ price ranking added nothing beyond five yardsticks (earnings yield, FCF
  yield, gross profitability, return on capital, 12-1 momentum). Revenue forecasts beat a naive baseline.

## 2. Stage 1 forensics, adopted from your reviews (20 quarter-ends, 2020–2024, about 25,000 company-dates, no engine change)
- **Oracle valuation.** The same engine fed the fundamentals that actually happened (first reported), with no price,
  ranked returns strongly: residual spread +16 pp a year at 12 months. The engine's own P50 inputs gave about 0.
  **The mapping from forecasts to value keeps the signal; the inputs are the problem.**
- **The engine's forecasts predict realized fundamentals** far beyond what the price implies. Regression slopes: growth
  1.01 against 0.07; margin 0.70 against 0.17.
- **The statistic mattered.** Ranking by the **mean** of the 2,000 draws instead of the median gave residual spread +7.5
  pp against +1.2 pp, and survived size, beta, volatility, liquidity and leverage controls. (Equity is a
  limited-liability, convex claim, so its price compares with an expectation, not a median.)
- **Distress:** the least solvent tercile's ranking inverts.
- **Commodity:** its ranking is inverted even under the oracle, a structural defect.
- **Horizon:** the signal grows with horizon (36-month spread +11 pp, on about 5 independent windows).
- **Small effects:** ranking within family or industry is a small gain; capping the terminal value changes little.

## 3. Stage 2 and the new untouched test (gate 1b)
- **Changes:**
  - value = the mean of the draws;
  - a point-in-time survival layer (a logistic model of distress exits; it turned out weak, AUC 0.65);
  - the commodity family out of scope.
- **Development check, set before running:** pass in both 2020–2022 and 2023–2024, under all three survivorship
  bounds. **It passed.**
- **The holdout:** 9 month-ends, 2025-01 to 2025-09, run once, every input hashed.

| Bar | Result |
|---|---|
| H1 | incremental coefficient +0.21 (lower bound +0.15) under all bounds |
| H2 | residual top-minus-bottom quintile spread about +8 pp a year under all bounds |
| H3 | revenue forecasts beat naive (0.054 against 0.067); **operating-margin forecasts were worse than "margin held"** (0.022 against 0.019) |

- **Registered outcome: FAIL**, on H3.

## 4. The adversarial audit of that holdout (CPU, about 30 minutes, 12 checks)
- **No look-ahead leak.**
  - Clean: price basis around splits, share counts, every input filed before 16:00 ET on the date (300 company-dates,
    74,000 inputs), survival labels before the date, priors cut-offs, ERP and beta dates, outcome alignment, and
    placebos (shuffled scores sit below the real result in every draw).
- **Inflated by about half.**
  - Companies that later left the market were priced from a stale cover-page public float, a median 13 months old and
    about 0.84× the traded price.
  - 167 resolved takeovers averaged +42% and sit mostly in the top score quintile.
  - Without these companies: H1 +0.12, H2 about +4 pp.
- **Mostly style, not engine skill.**
  - Ranking by 1/price alone gives about +7 pp; by book ÷ price, +17 pp.
  - Adding book ÷ price, size, volatility, beta, liquidity, 1-month reversal and 1/price to the yardsticks takes 2025
    incremental information to about zero.
  - **The same engine run at population-median inputs** (no company-specific forecast) ranked better (+12.6 pp) than
    with company-specific inputs (+8.2 pp).
- **Development (2020–2024) did survive those full controls:** coefficient +0.05 to +0.09, all lower bounds positive;
  spread +3 to +7 pp.
- **The coordinator's correction:** the registered bars controlled for only five yardsticks. They credited common value
  and size exposure as engine information. Future bars will control for book ÷ price, size, volatility, reversal and
  1/price, and will report an "average-input" control that company-specific forecasts must beat.

## 5. What is running now
- **Gate 2:** 600 company-dates (5 month-ends from 2025-10 to 2026-06, all after Muse's training cutoff), Muse against
  code paired, about 4 GPU-days.
- **The approved bars:**

  | Bar | Kind | Rule |
  |---|---|---|
  | G1 | hard | Muse beats the code engine on next-quarter revenue growth and operating-margin changes (year on year), one-sided 90% |
  | G2 | hard, direction only | Muse's rank IC with 3-month excess return beats the code's |
  | G4 | hard | Fewer than 10% of red-team revisions move toward the price without new evidence |
  | G5 | hard | Integrity |
  | G3, G6 | reported | Calibration; a name-masking control |

- The audit's controls will be reported beside G2, without changing the approved bars.

## 6. Questions
1. Is the audit's reading right: no leak, an inflated result, mostly value and size style in 2025, some real
   information in 2020–2024? What would you check that it did not?
2. **"Population-median inputs beat company-specific inputs."** What does that say about the priors, the code's
   forecasts, or the design? Should company-specific inputs be shrunk toward the population, with the weight measured?
3. The engine forecasts revenue well but margins worse than persistence. What principled change would fix margin
   forecasting? Is it a job for the AI layer, as the coordinator argues?
4. Given that the 2025 edge is mostly style, is continuing gate 2 (Muse against code) still the right experiment? What
   should it report so that a "Muse wins" result cannot also be a style artefact?
5. What evidence, and how much, would you need before calling this system's stock-picking skill real enough for small
   real-money positions? Be concrete: periods, controls, effect sizes.
6. Is ranking on a valuation still the right product? Or should the system become a forecasting engine (fundamentals
   better than the market implies) feeding a factor-aware portfolio, with the valuation as one input?
