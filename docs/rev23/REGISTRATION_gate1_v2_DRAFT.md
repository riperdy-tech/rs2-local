# Gate 1 registration, version 2 — APPROVED by the operator 2026-10-07

Written by the coordinator on 2026-10-07 after ChatGPT's review of cross-check 3. It supersedes
`REGISTRATION_gate1_DRAFT.md`; the reasons for each change are in `SPEC_rebuild.md` Addendum J. Nothing here has been
seen by a holdout result.

## 1. What is tested
The code-only engines: three families, the discount rate and the population priors. Every judgment input sits at the
prior's P50, with no AI. The value is the engine's median IV per share.

**The freeze file must exist before the run** (Addendum J 10). It names:
- the commit;
- the hashes of the point-in-time store and the price snapshot;
- the Damodaran files and the priors vintages;
- the SIC→industry crosswalk;
- the configuration, seeds and package versions.

## 2. Dates, universe and outcomes
- **Holdout:** month-end dates 2023-01-31 to 2024-12-31 (24 dates), inputs as known at 16:00 ET on each date. It
  runs once. No engine change may follow.
- **Development (engineering evidence only):** 2020-03-31 to 2021-12-31, plus 2022 for B4. Earlier dates lack the
  history the priors need.
- **Universe:**
  - an annual report accepted by 16:00 ET on the date;
  - a traded close (raw daily);
  - a built family;
  - market cap ≥ $300M;
  - the family and industry from the SIC as filed at T.
- **Outcome:** the 12-month total-return excess over SPY from the next session's open. Delistings are CRSP-style from
  SEC records, under three bounds (excluded, −100%, last close).

## 3. Bars

| Bar | Kind | Rule |
|---|---|---|
| B1, incremental information | **hard** | Pooled regression of the 12-month excess return on the percentile rank of IV ÷ price plus the ranks of earnings yield, FCF yield, gross profitability, return on capital and 12-1 momentum, with industry and date effects. The lower end of the one-sided 90% wild-cluster bootstrap interval (clustered by date) is > 0. Also reported: the share of positive monthly coefficients. |
| B2, economic usefulness | **hard** | The industry-neutral top-minus-bottom quintile spread of the engine's residual after the yardsticks is > 0. **Strong pass** at ≥ +3 pp. The raw spread is reported. |
| B3, level | **hard** | The universe median IV ÷ price lies within [0.67, 1.5]. Verdicts rely on the level. |
| B3, pathology | diagnostic | The extremes share (< 0.4× or > 2.5×), the family concentration of extremes, family medians, the IQR of ln(IV ÷ price). |
| B4, forecasts | **hard** | The P50 median absolute error is ≤ the naive baseline's for next-fiscal-year revenue growth and operating margin (operating and commodity) and for ROTE (financial). Reported: P10..P90 coverage and directional accuracy. |
| B5, stability | **hard** (direction) | B1 and B2 keep their sign under all three delisting bounds and with the top 1% of \|residual\| observations removed. Reported: a price-provider variant, ERP ± 1 pp, sector- and size-neutral versions. |

## 4. Outcome
- **PASS:** every hard bar passes under all three bounds. Muse work proceeds to gate 2.
- **FAIL:** a hard bar fails under all three bounds.
- **NOT DECIDED:** any hard bar straddles across the bounds. The operator decides, with the figures in front of them.

## 5. Choices for the operator to approve
1. The $300M floor.
2. Monthly dates for 2023–2024.
3. The one-sided 90% interval rule for B1.
4. B2: pass > 0, strong pass ≥ +3 pp.
5. The B3 level band [0.67, 1.5].
6. B4 against the naive baselines.
7. The B5 direction rules.

## 6. Approval record
The operator approved all seven choices on 2026-10-07, in their own words:
1. "yes only at least 300M"
2. "approve"
3. "keep 90%"
4. "approve"
5. "approve"
6. "approve"
7. "approve"

The bars are fixed from this point.
- **What still has to happen before the holdout runs** (it runs only on a freeze file under Addendum J 10):
  - development round 4 (the terminal-RONIC change, the decomposition, this machinery);
  - the downloads (D1–D5);
  - the point-in-time SIC crosswalk.
- **No bar may change after any holdout figure exists.**
- **Smaller companies (< $300M)** never count toward the result. At most they are shown in a side table, labelled.
