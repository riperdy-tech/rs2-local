# Cross-check request 17: the paper book would be a bank portfolio. How should it pick names?

Written 2026-10-15 by the coordinator. **This document is self-contained.** Where an answer would rest on code you cannot see, say so rather than
assume. Critique freely: the coordinator rules on each point, and the operator decides. The decision is needed within hours, before the
paper book's first publication.

## 1. Background
- **The system.** A code valuation engine turns each company's point-in-time filings into a distribution of intrinsic value per share. The
  version in use, **v2.1**, **failed** its registered out-of-sample forecast screen (cross-check 15: on next-quarter growth and margin, worse
  than the trailing run-rate, no better than the population median, better than the old engine on growth). It is **not promoted**, and real
  money is barred.
- **The operator's decision:** let a **paper (no-money) book** trade v2.1's verdicts anyway, **labelled experimental and unpromoted**, as a
  diagnostic only. It can never promote v2.1. It is kept apart from the real-money mirror.
- **Every night** the engine values the whole universe (about 2,000 US companies with a market cap of at least $300M) at the latest close. Each
  valued company gets:
  - a median intrinsic value per share, and the ratio of that value to price;
  - a direction: **undervalued** if the price is below the value distribution's P10 and the median margin of safety clears a floor;
    **overvalued** if the price is above P90 and the margin clears the floor the other way; otherwise **hold**;
  - gate checks (stale inputs, implausible level, and others).

## 2. The approved paper rule (registered today, before any paper row was published)
- **Paper-tradeable:** the only gate objection is "unpromoted", and the discount rate is at least 2 points above terminal growth (a guard
  against a known discount-rate defect).
- **Holdings:** every **undervalued**, paper-tradeable company that the screener also ranks and does not veto, equally weighted (over at
  least 8 names). This is the same rule the system's production paper book uses.
- **Trading:**
  - the next US close after each night's run, at 25 bps a side;
  - a 12-month primary window against IWM (the Russell 2000 ETF);
  - "positive" only with a Newey–West t ≥ 2, otherwise inconclusive;
  - no promotion from paper results under any outcome.

## 3. What the first live night showed (2026-10-14, 2,030 companies)
- **Coverage:**
  - 1,255 valued;
  - abstentions: 441 the engine could not value, 200 in families not built (commodity and others), 131 without a recent 10-Q;
  - 100 blocked as stale by a data-window defect, now fixed;
  - 48 excluded by the discount-rate guard.
- **The level by family:**

  | Family | Valued | Median (value ÷ price) | Undervalued / hold / overvalued |
  |---|---|---|---|
  | Operating companies | 899 | **0.53** | 1 / 670 / 228 |
  | Financials (banks, insurers) | 356 | **1.49** | 128 / 184 / 44 |

- **Under the approved rule, the book would hold 122 names: 121 financials and 1 operating company.** Its returns would mostly measure financials
  against small caps, not whether the engine picks better stocks.
- **This level pattern has appeared before:**
  - in an earlier gate the engine's typical operating value was about 0.70× price;
  - an earlier sanity check found the financial engine's mean value at about 1.57× price.

  A discount-rate correction is being validated separately. The engine owner expects it to explain only part of the operating gap; the rest
  points to margins, reinvestment and the growth fade.

## 4. The options
- **A. Within-family selection.**
  - Within each family, rank the paper-tradeable valued companies by value ÷ price.
  - Hold the top 10% of each family (about 80 operating and 30 financial), equally weighted, so the family mix follows the universe.
  - Every other rule is kept.
  - It tests: within a family, do the names the engine rates cheapest outperform?
- **B. Keep the approved rule.** The book is about 121 banks. Monthly reports would state that it is a sector bet.
- **C. Both:** A as the main book and B as a second ledger for comparison.

## 5. Questions
1. **Which option, and why?** Is A's "top 10% within family by value ÷ price" the right statistic, against the margin of safety, the probability
   value exceeds price, a z-score within family, or a sector-neutral long/short? Is 10% the right cut, or should it be fixed-N, a quantile, or
   all names above the family median?
2. **Does family-relative ranking remove the level problem, or hide it?** Within the operating family the engine values almost everything
   below price. Are its relative ranks still informative when its absolute level is off by about 2×? What would show they are not?
3. **What else should the paper record carry** so a later reader can separate selection skill from level, sector and factor exposure? (For
   example, family, sector, size and value-factor exposures logged per position, and benchmarks per family.)
4. **Is a long-only book enough,** or should the diagnostic include the bottom decile (the engine's "most overvalued") as a short or comparison
   ledger, to measure the spread?
5. **Is changing the rule now, after seeing the first night's picks but before any return exists, sound practice?** Or does it open the door to
   rule-shopping? What safeguard would you require?
6. **Anything else** a careful reviewer would challenge before the first publication.

At the end, give: your choice (A, B, C or other) with the exact rule you would register, and the one safeguard you consider essential.
