# Gate 1b registration: the revised code engine on the untouched 2025 holdout

Written by the coordinator on 2026-10-09 ~08:15, under the operator's overnight mandate ("don't wait for my approval,
take your best judgement"). Written before any development result of the Addendum V engine exists and before any 2025
valuation date has been run or looked at.

## 1. What is tested
- **The engine:** the frozen engine (engine files identical to `c7d7a4f`) with the Addendum V changes:
  - V1, the value is the mean of the IV draws;
  - V2, survival-weighted, with P(fail) from a point-in-time logistic model on solvency variables trained on D1
    distress exits resolved before T;
  - V3, the commodity family is out of scope;
  - V4, ranks within industry for the verdict quintiles.
- **Precondition:** the holdout runs only if the development pass rule of Addendum V holds on 2020–2024. If it does
  not, this registration is never run.
- **The freeze:** a new freeze file names the code commit, every input hash (as `gate1_freeze.json` does), and the
  fitted survival-model coefficients per date.

## 2. Dates, universe, outcomes
- **Dates:** the 9 month-ends 2025-01-31, 2025-02-28, 2025-03-31, 2025-04-30, 2025-05-30, 2025-06-30, 2025-07-31,
  2025-08-29 and 2025-09-30. Inputs as known at 16:00 ET on each date. Run once.
- **Universe:** as gate 1 (≥ $300M, strict SIC as filed, a built family), with commodity now out of scope.
- **Returns:** the 12-month excess return over SPY from the next session's open, prices to 2026-10-06. The 2025-09-30
  date's window ends about 2026-10-01. Survivorship: the three bounds of Addenda M, N and P.
- **Fundamentals:** fiscal-year 2025 revenue growth and operating margin (ROTE for financials), first reported.

## 3. Bars
These bars are deliberately honest about power. Nine overlapping monthly dates in one regime cannot prove
significance on their own (ChatGPT and Gemini, cross-check 4). The holdout tests the direction; forward scoring
continues afterwards.

| Bar | Kind | Rule |
|---|---|---|
| H1, incremental information | **hard** | The pooled B1 coefficient (12-month excess return on the value ÷ price rank plus the five yardsticks, with industry and date effects) is > 0 under all three bounds. The one-sided 90% wild-cluster lower bound is reported; above 0 is a **strong pass**. |
| H2, economic size | **hard** | The industry-neutral residual top-minus-bottom quintile spread is > 0 under all three bounds. Strong pass at ≥ +3 pp. |
| H3, forecasts | **hard** | The engine's P50 median absolute error is ≤ the naive baseline's for next-fiscal-year revenue growth and operating margin (operating family). Financial ROTE is reported (in gate 1 it was a 0.0002 near-tie, which carries no information either way). |
| H4, robustness | reported | Median-statistic and Damodaran-ERP variants, with and without the survival layer, the dispersion guard, family and sub-period splits. |
| H5, level | diagnostic | Median value ÷ price, extremes and family medians (Addendum U 11). |

## 4. Outcome
- **PASS:** H1, H2 and H3 all pass under all three bounds. The code engine becomes the base for gate 2 (Muse), and
  live forward scoring starts.
- **FAIL:** a hard bar fails under all three bounds.
- **NOT DECIDED:** any hard bar straddles across the bounds. The operator decides, with the figures.
