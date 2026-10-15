# Cross-check request 16: fixing the discount rate (engine v2.2). Is the proposed design right, and how should three open choices be settled?

Written 2026-10-15 13:57 by fork 2, the session that owns the valuation engine. **This document is self-contained:** every number, rule and
definition you need is inline. Where an answer would rest on code or data you cannot see, say so rather than assume.

## Background

**The system.** A valuation engine turns a company's filed fundamentals into a distribution of intrinsic value per share. It is a
discounted-cash-flow model (operating companies) or a residual-income model (financial companies), run as 2,000 Monte Carlo draws. Real
money will eventually depend on it. Every change is therefore registered before any result exists, outside reviews are read and ruled on,
and the operator approves.

**Where things stand:**
- **Engine v2.1 is frozen.** It is used for paper trading, labelled experimental and unpromoted.
- **v2.1 failed its last out-of-sample test** (gate 2b, a next-quarter forecast test). That failure concerns the year-1 forecast centre, not
  the discount rate, and is being worked on separately.
- **Cross-check 15** (you may have seen it) asked about that failure. **Both reviewers also flagged the discount-rate defect described
  below** and proposed the same "combined stack" fix. This request is the registration of that fix, before it is built.

**How the discount rate enters a valuation.** For an operating company the engine discounts free cash flow at the WACC:

  WACC = E/(D+E) · k_e + D/(D+E) · k_d · (1 − t)

- `k_e = rf + β_L · ERP`, where β_L is the industry's unlevered beta relevered by Hamada: `β_L = β_U · (1 + (1 − t) · D/E)`.
- The terminal value is `FCF_{N+1} / (WACC − g_T)`, with terminal growth `g_T = min(rf, 3.75%)`.
- When WACC approaches g_T, the terminal value explodes. At **WACC ≤ g_T** the engine rejects every draw as invalid.
- A financial company is discounted at `k_e`, not the WACC.

## 1. The defect (measured)

Three mechanisms pull the current WACC towards g_T.

1. **The cost of debt has no floor.**
   - `k_d` is the company's effective rate: interest expense ÷ average debt (including finance leases), from its filings.
   - It can be **negative** (ManpowerGroup at 2026-07-31: −7.41%, an interest line reported net of interest income), **near zero** (Shift4:
     0.41%, from low-coupon convertible notes), or **below the risk-free rate** whenever debt was fixed before rates rose.
2. **The weights use book D/E, not market D/E.**
   - Buybacks shrink book equity, so book D/E overstates leverage: PepsiCo 2.41, Mastercard 2.46.
   - Most of the WACC's weight then sits on the after-tax cost of debt, and β_L is relevered on a D/E that Hamada's formula does not define
     (it is defined on market D/E).
   - The current module even warns: "D/E is the book (filed) ratio, not the market ratio".
3. **The equity premium can be very low when rates are low.** At 2020-03-31, several companies with normal debt costs had a WACC of about
   1.4–1.5%, because the engine's implied equity risk premium was small that quarter and rf was 0.7%.

**How often**, among operating companies with a cost of debt:

| | Historical test sample (20 quarter-ends, 2020–2024) | The 2026-07-31 census |
|---|---|---|
| Companies | 17,769 | 733 |
| k_d < 0 | 0.1% | 0.8% |
| k_d < rf | 15.4% (2022: 25%; 2023: 31%) | 11.9% |
| WACC ≤ g_T + 1 point | 2.5% | 1.4% |
| WACC ≤ g_T + 2 points | 6.4% (2024: 10.4%) | **10.4%** |
| WACC ≤ g_T (no valuation possible) | 0 | 2 (MAN, FOUR) |

Examples at the census date (g_T = 3.75%, because rf = 4.68%):

| Company | k_d | Book D/E | WACC |
|---|---|---|---|
| MAN | −7.41% | 0.80 | 2.41% |
| FOUR | 0.41% | 3.15 | 2.38% |
| PEP | 2.40% | 2.41 | 4.17% |
| MA | 3.65% | 2.46 | 4.34% |

**A constraint on the fix.** The current discount-rate module is one of the frozen files of an earlier test, so it cannot be edited. The fix
is a new module, used only by the next engine version (v2.2); v1 and v2.1 stay byte-identical.

## 2. The proposed design (the registration, in full)

**(a) Market-value weights.**
- D/E_market = (debt including finance leases, from the latest annual balance sheet) ÷ (market capitalisation at T: the price at T × the
  point-in-time share count).
- Hamada relevers the industry's unlevered beta on D/E_market. The WACC weights are at market.
- **No market capitalisation** (no price or no share count): the valuation is refused, with a named reason.

**(b) The cost of debt: the risk-free rate plus a synthetic-rating spread.**
- **Interest coverage** = operating income (EBIT, latest fiscal year) ÷ gross interest expense (same year).
- **Rating from coverage** by Damodaran's published coverage-to-rating table, with separate thresholds for large companies (market cap ≥ $5B)
  and small ones. The thresholds are fixed constants copied from the table, with the version recorded, and never refit. EBIT ≤ 0 gives
  the lowest rating.
- **The spread at T, point in time, by a one-anchor ladder:** spread(rating, T) = Moody's Baa minus the 10-year Treasury (FRED `BAA10Y`, the
  last observation before T) × r(rating). r is a fixed ladder: Damodaran's default spread for the rating ÷ his spread for BBB/Baa2, from the
  same table.
  - **Why one anchor.** We checked the alternatives. The ICE BofA option-adjusted spreads by rating bucket on FRED (and the high-yield OAS
    we already store) start only on **2023-05-15**, because of ICE's licence on FRED's history. The test needs 2020–2024. `BAA10Y` runs from
    1986, and our macro store already holds it point in time.
- **k_d = rf_T + spread(rating, T),** never below rf_T + spread(AAA, T).
- **Malformed inputs are refused, never floored silently:**
  - debt > 0 with no interest expense;
  - interest expense < 0;
  - an interest line tagged as net of interest income.
- **Zero debt:** k_d is unused (weight 0).

**(c) A minimum spread over terminal growth.**
- Operating: if **WACC − g_T < 2.0 points**, the valuation is refused, with a named reason.
- Financial: the same rule on k_e − g_T.
- The rule refuses and never adjusts. The measurement keeps every company as a named refusal.

**(d) Unchanged:** rf, the industry unlevered betas, the implied ERP (mechanism 3 is guarded only by rule c), the tax rate, g_T, and
everything else in the engine.

**The test** (fixed before any number exists):
- The engine's two registered acceptance checks are re-run in full on v2.2, **bars unchanged**:
  - **E5:** the rank correlation of value/price, valued on realised fundamentals, with 3-month excess returns, controlled for value, size,
    volatility, momentum and price. It must be at least v1's − 0.02, pooled and in every year.
  - **E8:** valuation sanity against v1: invalid draws, tail concentration of the mean, the P90/P50 spread, and the P50 level ratio within
    [0.5, 2].
- **Reported, not barred:**
  - refusals by reason, year and family (their share is a coverage condition for real money);
  - the distributions of k_d, market against book D/E, WACC and WACC − g_T;
  - v2.2 against v2.1;
  - the 2-point rule at 1.5 and 3.0 as a sensitivity.
- **An identity check:** year-1–3 forecasts are unchanged, since the discount rate does not enter them.
- **Adoption:** if E5 and E8 pass, v2.2 is frozen; moving paper trading to it is the operator's decision. If either fails, v2.1 stays and
  the defect stays open as a condition for real money.

## 3. The three choices the operator has asked you about

1. **The spread source.**
   - **Option A:** Baa alone, the one-anchor ladder above.
   - **Option B:** add Moody's Aaa minus the 10-year Treasury (FRED `AAA10Y`, history since 1983) as a second anchor, interpolating the
     investment-grade ladder between Aaa and Baa.
   - B needs a new download outside the operator's standing approvals.
   - Is the second anchor worth it? Is a fixed-ratio ladder off one anchor a sound way to make rating spreads point in time, or does it
     distort high-yield spreads, whose ratio to Baa widens in stress?
2. **The minimum gap.** Refuse when WACC − g_T < 2.0 points?
   - Too low leaves explosive terminal values; too high refuses real, low-risk companies.
   - About 10% of operating companies sit within 2 points today. That is mainly a symptom of mechanisms 1 and 2, which (a) and (b) should
     remove.
   - What value, and should it apply before or after the corrected k_d and weights (as proposed: after)?
3. **Companies whose interest line is reported net of interest income.**
   - **Option A:** refuse them.
   - **Option B:** use gross interest expense where the filings carry a separate gross figure, and refuse only when they do not.
   - The share affected will be measured before the build.
   - Is refusal too costly in coverage? Is the net figure ever usable?

## 4. Questions (most important first)

1. **Is the combined stack the right fix,** or does any part of it (market weights, synthetic-rating k_d, the minimum spread) introduce its
   own bias? For example:
   - market weights make WACC move with the share price, so a falling price raises D/E, raises β_L and lowers the value: a
     reflexive loop;
   - a synthetic rating from one year's coverage is noisy for cyclical companies.
2. **The coverage-to-rating mapping:** is Damodaran's table, fixed from today's version, acceptable for 2020–2024 valuations, or is that a
   form of look-ahead? The thresholds are stable but were published later. Should EBIT be a multi-year average, to reduce cyclicality?
3. **Mechanism 3 (a low implied ERP when rates are low)** is left to the minimum-spread rule. Is that enough, or should the ERP itself have a
   floor, under its own registration?
4. **The financial family:** is applying the minimum-spread rule to k_e − g_T right, given that those companies are valued by residual
   income?
5. **The test:** E5 and E8 compare v2.2 with v1, whose discount rate still has the defect, so a difference may reflect v1's errors. Is
   v1 still the right comparator, or should the bars also hold against v2.1? And is anything missing that would show the corrected rate is
   *more accurate*, not just different?
6. **The three choices in section 3:** what would you choose, and why?

**How to answer:** critique freely; the coordinator rules on each point, and the operator decides. The most useful answer is a list of
problems ranked by how much each could hurt a real-money decision, then your answer to each question.
