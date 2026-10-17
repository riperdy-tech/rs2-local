# Step 1 report: synthetic companies, and today's desk on them

*2026-10-18. Step 1 of `PLAN_terminal_reinvestment.md`. No GPU. Harness: `scratch/rev23/terminal_d2/synthetic.py`; rows:
`synthetic_baseline.json`. Desk: `financial_model_tool.unbundled_dcf` at rev25-bridge `9ed16fc`, read only.*

## The harness

- **Simulation:** each firm is simulated year by year from its own economics. Capacity is bought in vintages at a current unit cost,
  depreciated straight line, and retired after its life. The simulation also carries working capital, tax, a debt policy (none, or a
  constant share of book capital), acquired-intangible amortization and recurring capex. Accounts and cash flows are consistent by
  construction: the self-test checks the capital roll-forward and the steady-state growth identity.
- **Warm-up:** 120 years, with starting vintages shaped to the warm-up's own growth, so year 0 has a realistic vintage mix and no
  replacement echo.
- **True value:** the present value at r of the firm's own equity cash flows (FCFE, net borrowing included) over 300 years, plus a Gordon
  tail.
- **The ideal analyst:** the desk gets the true owner-earnings growth of years 1–5, the true working-capital changes, the true year-5
  earnings and owner earnings, and the true steady-state growth, return on capital and earnings margin. r_tc is the year-0 ROIC; the fade
  runs until the firm reaches steady state (10 years; 25 for C; 15 for E). Any error is the desk's method, not judgment.

## Baseline: today's desk

| Firm | Economics | True | Desk | Error | PV years 1–5, true / desk | PV fade, true / desk | PV terminal, true / desk | Year-6/5 flow, desk / true |
|---|---|---|---|---|---|---|---|---|
| A | compounder: 1% real growth, 2.5% inflation, no debt | 1.717 | 1.717 | **+0.0%** | 0.390 / 0.390 | 0.534 / 0.534 | 0.793 / 0.790 | 1.04 / 1.04 |
| B | shipowner doubling its fleet in years 1–3 | 5.769 | refused | — | owner earnings negative in years 1–3 | | | |
| B2 | shipowner adding 12% in years 1–3 | 4.987 | 4.855 | −2.7% | 0.808 / 0.808 | 2.000 / 1.846 | 2.180 / 2.200 | 0.94 / 1.03 |
| C | depleter: flat output, replacement cost rising 3%/yr faster than price for 20 years | 2.231 | 2.434 | **+9.1%** | 0.845 / 0.845 | 1.160 / 1.439 | 0.226 / 0.150 | 1.31 / 0.99 |
| D | A plus acquired-intangible amortization (4% of revenue, years −5..9) | 1.777 | 1.747 | −1.7% | 0.429 / 0.429 | 0.555 / 0.536 | 0.793 / 0.780 | 0.97 / 1.03 |
| E | venue owner, 40% spare capacity, no capex in years 0–7 | 2.469 | 2.389 | −3.2% | 0.750 / 0.750 | 0.918 / 0.882 | 0.801 / 0.760 | **0.59** / 1.04 |
| F | insurer: ROE 12%, book equity growing 8% then 3.5% | 112.3 | 133.8 | **+19.2%** | 11.6 / 34.7 | 32.2 / 33.4 | 68.5 / 65.7 | 0.44 / 1.20 |
| G | utility: rate base +3.5% real, 50% debt | 0.258 | refused | — | owner earnings negative every year | | | |
| H | REIT: buildings never retire, 40-year accounting depreciation, debt-funded acquisitions | 10.70 | 9.83 | **−8.0%** | 1.58 / 1.02 | 2.97 / 3.20 | 6.14 / 5.61 | 2.15 / 1.04 |

## What it shows

1. **The harness is sound, and the value-driver form is exact when its inputs are consistent.** Firm A matches to 0.0%, with ROIC on
   historical-cost book capital and 2.5% inflation, so historical-cost D&A understates replacement cost. The inflation lag is fully charged
   by g/RONIC. This confirms the plan's rejection of Gemini's separate inflation-lag charge (§2 row 11).
2. **The desk refuses firms whose owner earnings dip below zero (B, G).** Owner earnings are grown at rates, and a rate on a negative base
   means nothing. A fleet programme (B) and every growing utility (G) are refused outright, even with perfect inputs. The census counts 28
   such names in the book. O5 alone does not cure G: with half its reinvestment debt-funded, its equity flows are still negative in years 0–3, and so are its
   true flows (the utility raises equity while it grows). Both B and G need the explicit years stated as flows, not as growth rates (O7 below).
3. **Insurer (F): +19.2%, all of it in years 1–5.** The desk deducts no retained capital there (11.6 true, 34.7 desk); the fade and the
   terminal are close. This is O3, quantified.
4. **Depleter (C): +9.1% even with perfect steady-state inputs.** The error sits in the fade (1.44 against 1.16). There the desk grows
   earnings at the owner-earnings growth of year 5 and moves RONIC linearly, while the true treadmill keeps escalating. The terminal is
   0.15 against 0.23; the two errors do not cancel, but they offset. A measured s (step 5) must be tested on C for both parts.
5. **REIT (H): −8.0%.** Two causes. Years 1–5 miss the debt-funded share of acquisitions (O5), and the terminal on GAAP earnings understates
   (the negative s of O6).
6. **Capex holiday (E):** the desk's year-6 step is 0.59 against a true 1.04, the MSGE pattern (0.42 live). The value error is small
   (−3.2%) only because the holiday ends inside the fade.
7. **Acquirer (D): −1.7%.** The desk's earnings basis X (net income before acquired-intangible amortization) drops amortization's tax shield
   in the fade years before the amortization ends. Small and correct in sign; recorded, no change proposed.

## Acceptance targets for steps 3–5 (±3% of the true value)

- **Step 3 (D2 seam and δ):** A stays at 0.0% to 1e-9 on the regression path, and A, B2, D and E are within ±3%. G is tested with δ in the
  fade and terminal; it values only once O7 is ruled.
- **Step 4 (financial route):** F within ±3%.
- **Step 5 (measured s):** C and H within ±3%.
- **B and G:** stay refused until O7 is ruled. Recorded as a known coverage hole, not a pass.

## O7, for the operator

**Explicit years as flows.** Today the analyst states owner-earnings growth rates for years 1–5. A company whose owner earnings cross
zero cannot be expressed that way, and the desk refuses it. That covers a capex programme, a growing utility before O5, and the 28 census
names with non-positive five-year owner earnings. The fix would let the explicit years be stated as levels (revenue, margin and capex, or
owner earnings directly), as the rev25 bridge already does for revenue and margin. It changes the rev25 explicit years, which were
registered recently. It needs a ruling, and is not part of this fix by default.
