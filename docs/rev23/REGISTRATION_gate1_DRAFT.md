# SUPERSEDED by REGISTRATION_gate1_v2_DRAFT.md (approved 2026-10-07) — Gate 1 registration (DRAFT, for the operator's approval): do the code engines add information?

Written by the coordinator (Opus 5.5, main session) on 2026-10-07, before any engine has been run on any historical
date. Implements `SPEC_rebuild.md` section 6 under Addenda A–D. Nothing here has been seen by a result.

## 1. What is tested
- **The engines:** the three family engines (operating, financial, commodity/asset-heavy), the discount-rate module
  and the population priors, all code with no AI, frozen at a named commit before the holdout run.
- **Each stock's input:** the engine's own mechanical inputs, the prior's P50 for every judgment input. The value is
  the engine's median IV.

## 2. Dates and universe
- **Development:** quarter-end dates from 2019-03-31 to 2021-12-31 for return metrics, plus 2022 for forecast quality only (Addendum H6; the priors cannot serve 2017–2018). The coordinator may study
  these results and fix structural defects. Every change is logged with its structural reason, and no change may name
  a stock.
- **Holdout:** quarter-end dates from 2023-03-31 to 2024-12-31 (8 dates).
  - It runs once, on a freeze file naming the engine commit and module hashes.
  - No engine change may follow from it (Addendum C 11).
- **Universe per date:**
  - every company with an annual report accepted by 16:00 ET on the date;
  - a traded close on the date;
  - a family that is built;
  - a market cap of at least $300M at that close. Smaller names carry too much data noise for a first gate;
    they are reported separately, never pooled.
- Counts per date, per family and per exclusion reason are reported.

## 3. Outcomes
- **Primary:** the 12-month total-return excess over SPY from the next session's open after the date.
- **Also reported:** 3, 6 and 24 months where elapsed.
- **Forecast outcomes:** next fiscal year's revenue and operating margin, first reported after the date.
- **Delistings:** CRSP-style events from SEC records (Addendum D). Every return figure is computed three ways:
  - unobservable delistings excluded;
  - unobservable delistings at −100%;
  - unobservable delistings at the last close.

  A bar that passes in one and fails in another is **not decided**.

## 4. Yardsticks (same stocks, same dates)
1. Earnings yield (trailing net income ÷ market cap).
2. FCF yield.
3. Gross profitability (gross profit ÷ assets).
4. Return on capital.
5. Momentum (12-1 months).
6. ~~The old engine~~: dropped (Addendum H7). Its anchors are not stored before 2026-05, so it cannot be computed
   point in time. A missing yardstick is imputed at the cross-sectional median rank, with an indicator.

## 5. Bars on the holdout (all must pass)

**B1, incremental information.**
- **Test:** per-date cross-sectional regressions of the 12-month excess return on the percentile rank of the
  engine's IV ÷ price and the percentile ranks of all six yardsticks, sector-neutral (industry fixed effects).
- **Bar:** the mean engine coefficient across the 8 dates (Fama–MacBeth) must be positive, and the lower end of its
  90% interval (a bootstrap over date blocks) must be above zero.

**B2, economic size.**
- **Test:** the sector-neutral spread of 12-month excess return between the top and bottom quintile of IV ÷ price.
- **Bar:** a mean of at least +3 percentage points.
- **Also:** the same spread on the engine's residual after the six yardsticks must be positive.

**B3, no structural distortion.**
- (a) At most 15% of stocks are below 0.4× or above 2.5× their price.
- (b) Each family's share of those extremes is within 10 percentage points of its share of the universe, so the
  extremes do not sort by type.
- (c) The interquartile range of ln(IV ÷ price) is at least 0.30 (Addendum H7). The engine must not collapse
  everything toward the price.

**B4, forecast quality.** The median absolute error of the engine's P50 for next-fiscal-year revenue growth and
operating margin must not exceed the naive baseline's (trailing 3-year revenue CAGR; margin held).

## 6. Outcome
- **PASS:** B1–B4 all pass in all three survivorship bounds. Muse work proceeds to gate 2.
- **FAIL:** any bar fails in all three bounds. Muse GPU work does not start. The coordinator finds the next structural
  cause; a new development round needs a new holdout, named before it starts.
- **NOT DECIDED:** any bar straddles across the bounds. The operator decides what follows, with the figures.

## 7. Choices to approve (updated 2026-10-07 after development round 1)
1. The $300M market-cap floor.
2. Quarter-end dates.
3. The +3 pp quintile-spread bar.
4. The 15% extremes cap.
5. The 10-point family-share band.
6. The B3(c) spread floor: IQR of ln(IV ÷ price) ≥ 0.30 (replaces "half the old engine's", Addendum H7).
7. The development dates, re-dated by Addendum H6: 2019-03-31 to 2021-12-31 for return metrics, plus 2022 for forecast
   quality only, so development outcomes never reach the 2023–2024 holdout years.

These are stated conventions, not fitted values. The operator may change any of them before approval, never after a
result.
