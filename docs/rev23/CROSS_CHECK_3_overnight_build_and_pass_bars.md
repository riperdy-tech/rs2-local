# Cross-check request 3: the rebuilt valuation engine, its first development results, and the pass bars

You reviewed this project twice before: the rebuild's architecture, then its point-in-time data rules. This document
reports what was built overnight on 2026-10-07, what the first development runs showed, and the decisions still open.
The main one is the **pass bars** for the frozen test. You cannot see code or data, so everything you need is here.
Critique freely: the coordinator decides, and your input is weighed on its merits.

## 1. Reminder: the system and the goal
- **The pipeline:**
  1. A screener nominates 150–300 US stocks.
  2. A local 30B language model ("Muse") on one 24 GB GPU judges each company's prospects.
  3. Python computes intrinsic value.
- **The goal:** values good enough to drive real-money purchases. Real-money execution stays off until a validation
  chain passes.
- **Earlier failure:** the old design valued every company with one owner-earnings DCF, and the AI copied that
  formula's output. Values split by company type: growth stocks at 0.2–0.45× their price, cyclicals and insurers at
  2–3.7×.

## 2. What was decided after your two reviews (and where the coordinator overruled)
- **Adopted:**
  - **Families:** valuation families instead of one DCF; for now operating (a layered DCF), financial (excess return on
    tangible book) and commodity/asset-heavy (mid-cycle cash flows from year 1), each with a secondary cross-check whose
    disagreement is recorded.
  - **Discount rate:** Damodaran industry betas, relevered by each company's own debt (Hamada), with Damodaran's
    implied ERP, both dated (no look-ahead).
  - **Priors:** population distributions per input, built only from data known at the valuation date (expanding
    window).
  - **The AI's role:** it is price-blind first (places the company inside population distributions with quoted
    evidence), then a red-team pass that sees the price.
  - **Point in time:** inputs are the latest filing known at 16:00 ET on the date (amendments included); outcomes are
    the first value reported afterwards.
  - **Delistings:** valued at what holders actually received.
  - **Consensus estimates:** removed from the core, live and test alike.
  - **Validation:** forecast accuracy plus returns.
- **Overruled:**
  - **Name masking (Gemini):** not adopted, because it would make the test differ from live use. A small control
    measures name bias instead.
  - **A paid price database:** rejected by the operator. Free SEC and Yahoo data are used, and delisting effects are
    reported under three bounds (excluded, −100%, last close). A test straddling its bar is "not decided".
  - **Live web research:** taken out of the core too, by the coordinator, for the same reason as consensus. It returns
    later as a separately measured add-on.

## 3. What was built overnight (all code, no AI run yet)
1. **A point-in-time data layer** on raw SEC XBRL "companyfacts".
   - It runs the screener's own production extractor, unchanged, on each filing as it was knowable, and reproduces
     the screener's published values to 99.96%.
   - Every value carries its filing and a provenance state.
   - Measured on 2010–2022, as-known values against first-filed:

     | Field | Cells that differ |
     |---|---|
     | Revenue | 9.5% |
     | Operating income | 11.9% |

     So restatement leakage would have been real.
2. **The three family engines and the discount rate.** Values come out as distributions (P10..P90) from 2,000 draws
   per company.
3. **Population priors:** dated vintages from 2012 to 2025 over all 20,175 SEC filers, delisted ones included.
   - **The no-look-ahead proof:** changing every later-filed fact changes nothing.
   - **Walk-forward:** the prior's median for next-year revenue growth beats a trailing 3-year-CAGR baseline in every
     year from 2015 to 2025 (median absolute error 6–18% against 7–20%).
   - **Measured shapes:**
     - positive margin deviations persist (about 0.8–0.9 of the gap still open after 3 years);
     - negative ones in cyclical firms revert (0.1–0.3 left);
     - excess return on capital keeps about 25–40% of its gap in the long run.
4. **The validation harness:**
   - yardsticks: earnings yield, FCF yield, gross profitability, return on capital, momentum;
   - three survivorship bounds;
   - a locked 2023–2024 holdout that refuses to run without a freeze file naming the exact code commit, and refuses a
     second run.
5. **The Muse layer:**
   - five short price-blind prompts, then a red-team prompt;
   - code checks: every quote must be found verbatim in the company's documents; a placement outside the population's
     P10..P90 needs "hard evidence" (a contract, backlog, or a figure with guidance); quoting the population prior
     itself is refused as circular;
   - a scripted leakage audit.

   It is tested with a mock model only. No GPU has been used.

## 4. Development results (code only, no AI; development dates only; PROVISIONAL)
**Why provisional:** prices come from a month-end file of today's listings, so survivors only. Real daily prices are
being downloaded now.

**The bars** (detailed in section 6):
- **B1:** incremental rank information.
- **B2:** the quintile spread.
- **B3:** extremes and distortion.
- **B4:** forecast accuracy.

| | Round 1 | Round 3 (after two rounds of structural fixes) |
|---|---|---|
| Valued company-dates (≥ $300M) | 20,774 | 11,838 |
| Median IV ÷ price: operating / financial / commodity | 0.14 / 1.30 / −0.08 | 0.50 / 1.54 / 0.19 |
| Share outside 0.4×–2.5× price | 70.9% | 43.0% |
| B1 mean coefficient (90% interval) | −0.042 [−0.098, +0.013] fail | +0.081 [+0.024, +0.126] pass |
| B2 sector-neutral top-minus-bottom quintile, 12-month excess return | +1.96 pp fail | +6.75 pp pass (residual after yardsticks +3.9 pp) |
| B3 | fail | fail |
| B4 forecast error, revenue growth (engine against naive) | 0.094 against 0.104, pass | 0.114 against 0.126, pass |

**The structural fixes between rounds**, none tuned to a stock or to returns:
1. **Margin path:** the margin level five years out is drawn from its measured distribution, replacing a wrong
   rescaling rule of the coordinator's own that made margins swing ±50 points.
2. **Terminal growth:** min(risk-free rate, 3.75%), the Damodaran convention, instead of companies' realized growth.
3. **Return on new capital:** the company's own ROIC level fading to its industry median, with a terminal floor at
   WACC, instead of noisy incremental ROIC.
4. **Scope:** pre-profit companies and regulated utilities are "family not built", like REITs; they need survival and
   rate-base models.
5. **Uncertainty bands:** measured by each company's own margin and return level.
6. **Limited liability:** equity per draw is floored at 0, and loss-making draws stop growing.
7. **Financials:** the levered industry beta (no Hamada), and the excess return fades to its measured long-run level.

**Data limit:** XBRL history starts in 2009, and the priors need at least five later years. So the development period
that can actually be valued is **8 quarter-end dates, 2020-03-31 to 2021-12-31** (plus 2022 for forecast accuracy).
This is thin, and COVID-era.

## 5. The open question about levels (the coordinator's current hypothesis)
- **The pattern:** values still lean low (operating median 0.50× price). The ranking works (B1 and B2), but the level
  does not.
- **The hypothesis:** Damodaran's implied ERP is solved from the index price assuming analysts' (optimistic) growth.
  Our engine's cash flows follow population base rates, which fade growth much faster. Pairing a premium implied
  under optimistic growth with conservative cash flows undervalues systematically. This is the same inconsistency an
  earlier review found in this project's old macro model.
- **The diagnostic running now:** per date, the "closure ERP", the single premium at which our engine values the
  whole ≥ $300M universe at its market cap (point in time), and the diagnostics under it, plus a per-family version
  to show what a common scalar cannot fix.
- **The decision it feeds:** use an engine-consistent premium per date, or keep Damodaran's.
  - **For:** a single scalar per date shifts levels, not ranks. B1 and B2 are unchanged, and values become internally
    consistent.
  - **Against** (your earlier concern): the result becomes market-consistent rather than absolute intrinsic value,
    calibrated on the market we try to beat.

## 6. The pass bars for the frozen 2023–2024 test (operator decision; please critique)
- **Run conditions:** the holdout runs once, on frozen code. Quarter-end dates 2023-03-31 to 2024-12-31. A 12-month
  excess return over SPY from the next session's open.
- **Universe:** companies with an annual report accepted by 16:00 ET on the date, a traded close, a built family, and
  market cap ≥ $300M.
- **Values:** code-only engine values; Muse is tested later, at gate 2.
- **Every return bar** is computed under three survivorship bounds. Pass in all three = pass; fail in all three =
  fail; anything else = not decided.

| Bar | Rule |
|---|---|
| B1, incremental information | Per date, regress the 12-month excess return on the percentile rank of IV ÷ price plus the ranks of five yardsticks (earnings yield, FCF yield, gross profitability, return on capital, 12-1 momentum), with industry fixed effects. The mean engine coefficient across the 8 dates must be positive, with the lower end of its 90% date-block bootstrap interval above zero. |
| B2, economic size | The industry-neutral top-minus-bottom quintile spread of 12-month excess return ≥ +3 pp, and the same spread on the engine's residual after the yardsticks > 0. |
| B3(a) | At most 15% of stocks below 0.4× or above 2.5× their price. |
| B3(b) | Each family's share of those extremes within ±10 points of its universe share. |
| B3(c) | IQR of ln(IV ÷ price) ≥ 0.30 (values must not all collapse onto the price). |
| B4, forecast quality | The median absolute error of the engine's P50 for next-fiscal-year revenue growth and operating margin ≤ the naive baseline's (trailing 3-year revenue CAGR; margin held). |

**Choices the operator must fix before the run:**
1. the $300M floor;
2. quarter-end dates;
3. the +3 pp bar;
4. the 15% extremes cap;
5. the ±10-point family band;
6. the 0.30 spread floor;
7. development dates 2020–2021 (2019 cannot be valued for lack of history) plus 2022 for B4 only.

**Things the coordinator is unsure of:**
- **B3(a) at 15%** may be unreachable for an honest valuer: in round 3 it is 43%. Is 15% right, or is it a level bar
  that a market-consistent premium (section 5) would satisfy mechanically, and should it therefore be weighed
  differently?
- **8 holdout dates are few;** the 90% interval on B1 will be wide. Is "lower bound > 0" too strict or too loose at
  n = 8 dates?
- **Survivors in development:** outcomes overlap nothing in the holdout, but the development dates are all survivors.
  Should development figures count for anything?

## 7. Questions for you
1. Is the ERP hypothesis in section 5 right? Should the engine use a premium implied by its own cash flows on the
   whole market at each date, or keep Damodaran's? If Damodaran's, what is the principled fix for the
   optimistic-growth mismatch?
2. Are the pass bars in section 6 right? For each, say keep, change (to what, and why) or drop. Especially B3(a), the
   +3 pp B2 bar, and B1's interval rule with only 8 dates.
3. Are the structural fixes in section 4 sound, or do any of them hide a bias?
   - **Limited liability:** about 30% of operating draws and 50% of commodity draws are floored at zero equity or
     stop growing.
   - **Scope:** pre-profit and regulated companies are excluded.
4. With development limited to 8 dates (2020–2021, COVID), is that enough to freeze the engine before the holdout?
   What would you do instead?
5. Anything that, in your view, would make the holdout result untrustworthy even if it passes?
