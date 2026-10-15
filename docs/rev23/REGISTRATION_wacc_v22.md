# Registration: the corrected discount rate, engine v2.2 (DRAFT, fork 2, 2026-10-15)

**Status:** a draft for the operator, written before any number from the candidate exists. It answers fork 1's AK.86 item 3, which adopts
both outside reviewers' "combined stack" from cross-check 15.

## 1. The problem (SPEC_rebuild AL.51–AL.53)

Three mechanisms pull v1's and v2's WACC towards terminal growth g_T. There, the terminal value explodes, and at WACC ≤ g_T every draw is
invalid.

1. **The cost of debt has no floor.** `kd_effective` is interest expense divided by average debt. It can be:
   - negative (MAN: −7.41%, interest netted against income);
   - near zero (FOUR's 0.41% convertibles);
   - below rf whenever debt was fixed before rates rose (2022: 25% of operating names; 2023: 31%).
2. **D/E is the book ratio.** Buybacks shrink book equity, so book D/E overstates leverage (PEP 2.41, MA 2.46). Most of WACC's weight then
   sits on the after-tax cost of debt. Hamada's relevering is defined on market D/E; the module warns but proceeds.
3. **The equity premium can be very low when rates are low** (2020-03-31: cost of equity about 1.4%, through the engine-consistent ERP).

**Size:**

| Sample | WACC ≤ g_T + 2 pts | WACC ≤ g_T |
|---|---|---|
| Forensic sample, operating, 2020–2024 | 6.4% (2024: 10.4%) | 0 |
| 07-31 census | 10.4% | 2 names (MAN, FOUR) |

`discount_rate.py` is one of gate 2's frozen files (`gate1_run.GATE1_FILES`), so the fix is a **new module, `valuation/discount_rate_v2.py`,
used only by engine v2.2.** v1, gate 2 and v2.1 stay byte-identical.

## 2. The candidate, fixed now (D)

**(a) Market-value weights.**
- D/E_market = (debt including finance leases, at the base balance sheet) ÷ (market capitalisation at T: the price at T × the point-in-time
  share count, the engine's own `price_per_share` × `shares_outstanding`).
- Hamada relevers the industry's unlevered beta on D/E_market. WACC weights are E/(D+E) and D/(D+E) at market.
- **No market capitalisation** (no price or no share count): the valuation is **refused**, named `discount: no market capitalisation`.

**(b) Cost of debt: rf plus a synthetic-rating spread.**
- **Interest coverage:** operating income (EBIT, base year) ÷ gross interest expense (base year).
- **Rating from coverage:** Damodaran's coverage-to-rating table, with separate thresholds for large companies (market capitalisation of at
  least $5B) and small ones. The thresholds are fixed constants in the module, copied from Damodaran's published table (version and date
  recorded), and never refit.
- **EBIT ≤ 0:** the lowest rating (D), by the table.
- **The spread at T, point in time: a one-anchor ladder.**
  - **Checked 2026-10-15** (MRI `raw_observations`):
    - Moody's Baa − 10y (`BAA10Y`) runs from 1986-01-02 to today;
    - the ICE BofA HY OAS (`BAMLH0A0HYM2`) starts only on **2023-05-15**: ICE's licence limits history on FRED, and the rating-bucket ICE
      series on FRED are limited the same way.
    - So no ICE-based source can be tested on the 2020–2024 dates.
  - **The rule:** spread(rating, T) = `BAA10Y` at T (the last observation strictly before T) × r(rating), where r is a fixed ratio
    ladder: Damodaran's published default spread for the rating ÷ his spread for Baa2/BBB, from the same table as the thresholds.
  - The ladder keeps the table's relative credit premia. The level moves with the market every day through Baa.
- **kd = rf_T + spread, never below rf_T + spread(Aaa/AAA, T).**
- **Malformed inputs are refused, not floored:**
  - debt > 0 with no interest expense;
  - interest expense < 0;
  - an interest line tagged net of interest income (`kd_basis` "net ...");
  - each named.
- **Debt = 0:** kd is unused (weight 0).

**(c) A minimum spread over terminal growth.**
- Operating: WACC − g_T ≥ **2.0 points**, else the valuation is **refused**, named `discount: WACC within 2.0 points of terminal growth`.
- Financial: the same rule on the cost of equity minus g_T, since the financial engine discounts at the cost of equity.
- The rule refuses, it never adjusts: the measurement keeps every row as a named refusal.

**(d) Unchanged:** rf, the industry unlevered betas, the engine-consistent ERP (mechanism 3 is guarded only by (c)), the tax rate, and g_T.
**v2.2 = v2.1 with `discount_rate_v2`.** Nothing else changes.

## 3. The test (fixed before any number exists)

**E5 and E8 re-run in full on v2.2,** on their registered samples: the 20 forensic dates, acceptance configuration (priors_v5 +
priors_v4_fy), and the run-2 2026 contexts. The **bars are unchanged.** v1 stays the comparator as registered.

**Reported, not barred:**
- refusals by reason (no market cap; malformed interest; the 2-point rule), by year and family. Their share is a coverage condition for
  real money;
- the distributions of kd, D/E market against book, WACC and WACC − g_T: v2.2 against v2.1;
- v2.2 against v2.1 on E5 (the IC) and E8 (the value distribution), on the names both value;
- **the 2-point rule's sensitivity:** refusals and E5/E8 at 1.5 and 3.0 points. Reported only; the registered value is 2.0;
- the 07-31 census: the same distributions (fork 1's discount dump plus a v2.2 re-run), with no outcome read.

**The identity check:** v2.2's year-1–3 forecasts (the near-term draws and their P50s) are identical to v2.1's, because the discount rate
does not enter them. Checked on every E8 name, like `years13_identical`. Gate 2b's q1 bars therefore carry over unchanged.

## 4. What adoption means

- **If E5 and E8 pass:** v2.2 is frozen (manifest as for v2.1). Moving paper rows from v2.1 to v2.2 is the operator's decision. The rn_v4
  paper exclusion rule (WACC − g_T < 2 points, AK.86) becomes redundant on v2.2 rows, which are refused instead.
- **If either fails:** the failed check is diagnosed; no bar changes; v2.1 stays. The discount-rate defect remains an open real-money
  condition (AK.83).

## 5. For the operator

1. **The spread source:** the `BAA10Y` one-anchor ladder (section 2b) is the only point-in-time source with 2020–2024 history in hand. An
   alternative needing a download is FRED's Moody's `AAA10Y` (history since 1983) as a second anchor, interpolating the investment-grade
   ladder between Aaa and Baa. Say whether to add it.
2. **The 2-point threshold:** confirm 2.0, or set another value now. It cannot be changed after scoring.
3. **Refusing net-interest filers:** confirm refusal, or allow "gross interest where the store has it, else refuse". The share affected is
   measured before the build and reported to you first.

No number from candidate D exists at the time of writing.
