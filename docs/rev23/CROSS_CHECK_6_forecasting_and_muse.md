# Cross-check request 6: the code has no company-specific skill; Muse's first run broke on formatting

You reviewed the audit of the 2025 result (cross-check 5) and recommended: finish gate 2 as a diagnostic, shrink
company-specific forecasts toward the population, rebuild the margin baseline, and run extra audits. This reports
what those produced. Everything you need is here. Critique freely; the coordinator decides.

## 1. Reminder
- **The goal:** a local AI analyst (Muse Glimmer 30B, one 24 GB GPU) whose company analysis is good enough for real
  money. Python computes values; the AI places each company's inputs inside population distributions, quoting its
  filings.
- **Data:** point-in-time, audited clean of look-ahead.
- **The value ÷ price ranking:** its 2025 "edge" turned out to be mostly value and size style (cross-check 5).

## 2. The extra audits you asked for (main universe = companies with an observed traded price; 2025 holdout and 2020–2024 development)
- **Takeover lottery:** confirmed for companies that later left the market, and absent in the main universe. Removing
  every M&A-flagged name leaves the main residual spread at +2.8 to +5.5 pp (beyond the five registered yardsticks).
- **Turnover and costs (30 bp a trade):**
  - 2025: no gross spread to net; a 12-month cohort nets −1.0 pp.
  - 2020–2024: +8.8 pp gross becomes +7.6 pp net.
- **Factor regression** (in-house market, size, value, momentum, reversal, low-volatility factors) of the engine's
  monthly long-short:

  | Period | R² | Value loading | Alpha |
  |---|---|---|---|
  | 2020–2024 | 0.62 | +0.44 (t 5.5) | +4.2%/yr gross, Newey–West t 2.35 (OLS 1.45); net of costs +2.9%, t 1.63 |
  | 2025 (9 months) | 0.95 | correlation with value 0.94 | about 0 |

- **The coordinator's own recheck, a new finding.** By date, the engine's incremental coefficient (beyond the five
  yardsticks, industry effects; book ÷ price and size added in brackets):

  | Dates | Coefficient |
  |---|---|
  | 2020 (4 dates) | 1.11, 0.85, 0.85, 0.27 (0.89, 0.83, 0.79, 0.27) |
  | 2021 | about 0.1 |
  | **2022–2024 (12 dates)** | **0.02 (0.01)** |
  | 2025 | about 0.02 |

  The development "survives the controls" result is the 2020 COVID crash and rebound. **Across 21 of the 29 dates there
  is no information beyond value and size.**

## 3. The forecast study (walk-forward, origins 2016–2024, forecast loss only, nothing after 2024 read)
- **Revenue growth:** the code's state-conditioned forecast is **no better than the plain population median.** It wins
  4 of 8 years, with a pooled gain under 1%. The earlier "beats naive" was only against trailing growth, which is about
  4 times worse. Years 2–3: the population median is better than the code.
- **Operating margin:** the code's mean-reversion path beats "margin held" by about 4% (median) to 6–8% (trimmed MAE)
  through 2024, mostly by reverting extreme margins. In the 2025 holdout it was **worse** than "margin held" (0.0221
  against 0.0189).
- **ROTE (banks and insurers):** the code beats persistence by 11–19%. An empirical-Bayes blend toward the population,
  w about 0.75, adds about 3%. The only clear company-specific contribution.
- **Operating-leverage decomposition** (fixed and variable costs; Gemini's suggestion): **does not beat persistence**,
  even given the realized revenue. Rejected.
- **Calibration:** the code's P10–P90 bands cover 71% of outcomes in year 1, 33% in year 2 and 9% in year 3 (target
  80%). Badly under-dispersed, which distorts a mean-of-draws value.
- **Shrinkage weights measured:**
  - revenue growth year 1: w about 0.5, immaterial;
  - years 2–3: w = 0, the population median;
  - ROTE: w about 0.75.

  The empirical-Bayes estimates run too high for growth.
- The coordinator audited it independently: leak cut clean, and the key numbers reproduce.

## 4. Gate 2 (Muse against code), run 1 paused after 42 companies, on a format defect
At the operator's request the coordinator inspected Muse's **behaviour** (not its accuracy; no outcome was read) on
the 38 companies with Muse results:

| Prompt | Valid after its retry |
|---|---|
| P1 (revenue runway) | 3 of 38 |
| P2 (margins) | 5 of 38 |
| P5 (synthesis) | 5 of 33 |

- **Inputs that fell back to the population prior (unanchored):**

  | Input | Unanchored |
  |---|---|
  | Growth | 26 of 38 |
  | Margin | 17 of 30 |

- **Causes:** invalid JSON in long answers; extra fields nested in the wrong place; document labels "D1"/"D4" where
  the checker expected "D".
- **Effect:** for about two-thirds of the growth and margin inputs, "Muse" equalled the code, so the test would have
  compared the code with itself.
- **The fix, in progress:**
  - schema-constrained decoding (llama.cpp JSON-schema output), which guarantees valid JSON;
  - the checker accepts subsection labels;
  - a fresh restart on the same sample, with a behaviour gate before the full run: at least 90% of calls parse first
    time, at most 5% of inputs unanchored, P5 succeeds at least 90%.
- **Red-team behaviour** (a model behaviour, left untouched for G4 to measure): 13 revisions proposed, all accepted.
  **11 of the 13 moved toward the market price,** 12 justified by a "named error in my earlier reasoning" rather than a
  new quote from the filings. That looks like anchoring on price.

## 5. Where this leaves the project
- **Established:** clean point-in-time data; a margin-reversion baseline slightly better than persistence (unstable);
  ROTE forecasts with real skill.
- **Not established:** any company-specific revenue forecasting skill in the code; any stock-selection information
  beyond value and size outside 2020.
- **Muse is now the only route to company-specific skill.** Its first run was invalid for engineering reasons, and its
  red-team pass shows a pull toward the price.

## 6. Questions
1. Do you agree that the code's state-conditioned priors carry no company-specific revenue information? Should the
   engine simply use population medians for growth (and margin reversion as measured), so that every
   company-specific deviation must come from evidence (Muse)?
2. Is schema-constrained decoding the right fix for the format failures, and does it risk degrading a 30B model's
   reasoning, since constrained grammars can hurt answer quality? Would you separate "reason freely in text, then
   extract to JSON in a second constrained call"?
3. Red team: 11 of 13 revisions moved toward the price on a "named error". Is the revision rule too loose? Should a
   revision toward the price require a new filing quote (hard evidence)? Is changing it now (before any outcome is
   read) legitimate, or does it compromise gate 2?
4. Given that revenue skill must now come from Muse, how should gate 2's G1 be judged? Muse against the code (whose
   growth equals the population median), or explicitly Muse against the population median and persistence?
5. ROTE is the only input with clear skill, and financials are about 22% of the universe. Is a financial-only system
   (banks and insurers) a sensible interim product to test?
6. What would you do next that this plan is missing?
