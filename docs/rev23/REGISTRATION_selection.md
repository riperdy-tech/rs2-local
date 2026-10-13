# Selection and sizing registration — DRAFT v2, 2026-10-11 11:17: does the promoted core pick stocks beyond standard factors, on fresh dates?

**Drafting history.** Draft v1 was written on 2026-10-10 18:30. Draft v2 (this text) applies the coordinator's rulings
on cross-check 8 (Addendum AH of `SPEC_rebuild.md`). Both were written while:
- no gate-2 outcome had been read;
- this project had computed no return after 2026-06-30 for any selection purpose.

Recovery plan S8; definition of done D9 (Addendum Z 10, unchanged). The rules for every return result apply: the
Addendum Y1 controls, the Y2 bounds, the Z 4 exits, and AA by-date reporting.

**Status:** a draft for the operator's approval. It may change only before the first confirmatory return exists. Any
later change is a new version and restarts its count (section 7).

## 1. What is evaluated, and on which dates

**The core** is the one gate 2b promotes (SYSTEM, or V2 by its own scorecard), identified by its freeze hash.

**Confirmatory dates** are every month-end **after the gate-2b promotion decision is recorded** (earliest
2027-04-30).
- The core must be chosen before its evaluated return period begins.
- Gate 2b chooses a core from those companies' fiscal-2026 results. Returns over the same months move on those very
  results. So any date whose return window overlaps the choice would test a core partly chosen by its own outcome.

**Exploratory dates** run from 2026-07-31 up to the promotion decision.
- They are computed as of each date with the candidate core, and reported.
- They never count toward any bar, and they never choose or tune anything.

**Universe per date:** the gate universe of that date: market cap at least $300M, a built family, an annual report
before T, and a traded price at T.
- Every company in it is valued. Where GPU time makes that infeasible, a seeded random draw of at least 300 companies
  is used, with the seed set to the date written yyyymmdd.
- Abstentions (unbuilt families, refusals, integrity failures) are recorded with their reason and excluded from
  ranking. They are never valued by a fallback.

**Returns:** excess over SPY from the next session's open, at 1, 3 and 6 months.
- The Z 4 exit rule applies: unobservable exits are excluded from the main result and shown in a sensitivity.
- Each return is reported under the three delisting bounds.

## 2. Hypotheses: tested in a fixed sequence

The order follows the records. Addendum AA left the expectation gap as the open stock-selection question. Static
IV ÷ price was found to be mostly value and size (Addenda Y and AA).

| Order | # | Signal | Exact construction |
|---|---|---|---|
| 1 (primary) | H-S2 | Expectation gap | Per engine input i in {g1, margin target} (operating) or {g1, ROTE target} (financial): `gap_i = q_i − u_i`. q_i is the percentile of the core's year-1 P50 for input i within the population prior Muse is shown. u_i is the reverse valuation's price-implied percentile (`valuation/muse/reverse.py`), set to 1 or 99 when "not_reachable" in that direction. Signal = the mean of the available gap_i. With one gap available, that gap is used and flagged; with none, the company abstains. The signal is ranked within family. |
| 2 | H-S1 | Model value | `log(mean_iv / price)`, using the survival-adjusted, model-implied value distribution of the verdict contract v4 (section 2a); the distribution is not claimed to be calibrated (AK.21: a dated correction before any selection data exist; it was "log(expected IV ÷ price), using the calibrated IV distribution"). Ranked within industry (SIC 2-digit; industries with fewer than 5 companies are pooled within their family), then residualised cross-sectionally on book ÷ price and log market cap, and the residual ranked. Ties take the average rank. |
| 3 | H-S3 | With entry timing | H-S1 restricted to names whose SCR-10 trend state is not "down". Tested only if the operator adopts O3 before the first confirmatory date; otherwise it is dropped from the sequence. |

**Testing rule:**
- H-S2 is tested first.
- Each later hypothesis is tested only if every earlier one passed S1.
- The sequence stops at the first failure.
- The fixed sequence controls the family-wise error at each step's level, so no further correction applies.
- One-month and six-month results are descriptive and create no route to success.

## 3. Statistics

**Information,** per hypothesis, at 3 months:
- **The monthly factor-adjusted rank IC:** the Spearman correlation between the signal and the residual excess return.
- **The controls are the expanded specification:**
  - **Y1 / Z 3 core:** book ÷ price, log size, 12-1 momentum, 1-month reversal, beta, idiosyncratic volatility,
    liquidity, 1/price (an artefact control, Addendum Z 8) and industry.
  - **Added:** earnings yield, FCF yield, gross profitability and ROIC, all point in time from the panel.
- The core-only specification is reported beside it, with coefficient stability and variance-inflation diagnostics.
- **Inference:** the mean IC over dates, with a Newey–West t-statistic at 2 lags.

**Money:**
- **Signal test:** the long-minus-short top and bottom quintile portfolio, equal-weighted, rebalanced monthly. It
  has no turnover cap. Costs are charged on actual turnover:
  - 30 bp a side;
  - 60 bp a side for names in the bottom quintile of 3-month average dollar volume;
  - shorts also pay a borrow cost of 100 bp a year, or 500 bp a year for the bottom liquidity quintile.
- **Alpha:** from a time-series regression on market, size, value, momentum, reversal and low-volatility factors,
  built in house from the point-in-time panel. Newey–West t at 2 lags.
- **Sizing test,** run only for the hypothesis that passed:
  - long only, against SPY;
  - weights proportional to (signal percentile − 0.5) for names in the top half, so sizing uses the same signal that
    passed;
  - a name enters at the top quintile and is held until it falls below the median;
  - caps of 5% a name and 25% an industry; the excess after the caps is redistributed pro rata among uncapped names,
    and the remainder held in cash;
  - turnover capped at 30% a month, cutting the smallest trades first;
  - the existing drawdown governor, applied unchanged after the caps;
  - the same cost schedule as the signal test.

**Always reported:**
- results by date;
- crisis months flagged: SPY's 21-session realised volatility annualised above 35% at the month-end, computed from
  `prices_daily`;
- turnover;
- the average-input control (Y3);
- the census and acquisition bound (Y2);
- the result without each family in turn.

## 4. Bars

| Bar | Rule |
|---|---|
| S1, information | For the hypothesis in turn: mean 3-month rank IC > 0 with t ≥ 2.0, under the expanded controls, over at least 36 confirmatory dates. |
| S2, money (D9) | For a hypothesis that passed S1: long-short factor alpha > 0 with t ≥ 2.0, net of the cost schedule, under each exit treatment, over the same dates. It must stay positive with crisis months excluded. |
| S3, company-specific value | The IC of the passing hypothesis exceeds the average-input control's, paired by date, with a mean difference > 0. |
| S4, shadow operations (a prerequisite, not evidence) | Over the same dates, the frozen shadow book (S10) has a complete ledger: every intended and executed trade, the price used, the cost charged, rejected trades with a reason, daily weights, corporate actions applied, and a monthly reconciliation of positions and value against the price data with no unexplained difference. |

**t ≥ 2.0 is a deliberate stringency choice.** It is one-sided p ≤ about 0.027 at 36 dates, and it is the Addendum
Z 10 bar. It is not presented as a Bonferroni threshold. With the fixed sequence, no other multiplicity adjustment
applies.

**Interim readings** are reported each quarter from the 12th confirmatory date. They inform the operator and never
re-tune a rule or stop it early for success. A rule may be stopped early for harm only under this rule: the running
long-short net return is below −10% cumulative, and the operator decides. The decision is recorded with its numbers.

**Effective sample.** Overlapping 3-month windows make the 36 monthly dates worth about 12 independent periods. The
report states this beside every t-statistic.

## 5. What the bars do not authorise

A pass of S1–S4 establishes D9's evidence. It does not by itself authorise real money (S11, the operator).

A pass here also does not license the signal for the verdict contract until S7 adopts it.

## 6. Operator decisions this depends on

- **O1:** whether D9 stays as written, or a staged capital ramp is added.
  - Under the confirmatory start of section 1, the earliest D9 read is about 2030-07 (36 dates from 2027-04 plus 3
    months).
  - A small real-money pilot during accrual is a risk decision for the operator, never evidence for D9.
- **O3:** the two-axis entry timing, which decides whether H-S3 is in the sequence.

## 7. Versions

Each frozen core version accrues its own count. These changes create a new version and restart the count at zero:
- any change to the core, the calibration, a w, a signal construction, the universe rule, the cost schedule or the
  sizing rule.

Evidence across versions is never pooled into one claim.

## 8. Approval record

Approved by the operator on 2026-10-11 12:33 KST ("approve 1-4, keep D9 as written, adopt O3"). The bars are fixed from this point. D9 kept as written (O1). O3 adopted: H-S3 is in the sequence, third.
