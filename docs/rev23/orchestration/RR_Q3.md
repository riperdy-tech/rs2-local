# RR_Q3: the D2 fade-convention truth test (WO_Q3, SPEC_m3q §3), 2026-10-30

**Pre-registration:**
- `scratch/rev23/terminal_d2/PREREG_q3_fade.json` v1.0, sha256 `98fab6fc…cc3ef`;
- logged, then committed in stocks-workspace `318beef` before any M firm was simulated.

**Code:** `scratch/rev23/terminal_d2/q3_fade_truth.py`. **Output:** `q3_fade_truth.json`. Runtime 2 s, CPU only.

## 1. Result (primary: oracle path; error = D2 value / true value − 1)

| Firm | R (as built) | E (earnings growth) | C (capital stock) |
|---|---|---|---|
| A_compounder (control) | +0.00% | +0.00% | +0.00% |
| M1_pricing (margin up, no capital) | −0.14% | −6.00% | −0.21% |
| M2_invested (margin up, bought by 1.4× vintages) | −0.59% | −3.57% | −11.08% |
| M3_mixed (1.2× vintages) | −0.28% | −5.17% | −4.66% |
| M4_decline (margin down, no capital change) | −0.14% | +5.75% | −0.22% |
| M5_decline_invested (margin down, 0.7× vintages) | +0.35% | +2.15% | +5.11% |
| **Passes (±3%)** | **5/5, max 0.59%** | 1/5, max 6.00% | 2/5, max 11.08% |

**The secondary variant** (D2's linear interpolation, as production runs) gives the same picture:
- R: max 0.15%;
- E: max 6.00%;
- C: max 10.73%.

**By the registered rule, the ruling is R, the revenue convention, as built** (`consensus_reference.py:579-581` at
`1dcb3b2`). Per the operator's B1 ruling (2026-10-30, "decide by the truth test"), B1 is now settled as R.

## 2. Audit (done before accepting the result)

- **The capital really changes.** Capital per unit of revenue is 0.891 in every firm at year 0; at year 20 it is 1.208 in
  M2, 1.050 in M3 and 0.654 in M5, and unchanged at 0.891 in M1 and M4.
  - The steady-state return moves the same way: M1 0.141 → 0.184; M2 0.141 → 0.113; M5 0.184 → 0.223.
- **Flows, not only totals.** R's year-by-year fade flows are within 2.5% of the true flows in every firm (worst: M2, years
  9–12).
- **Why R works on bought margins.** Two pieces of approved D2 carry the extra capital:
  - the year-5 wedge w₅ (O2): 0.046 of revenue in M2, 0.023 in M3, −0.035 in M5, fading over F;
  - the lower or higher long-run return RONIC_T the analyst states.
  - The revenue convention itself charges only growth capital, which is right when the margin needs no new capital (M1,
    M4).
- **Why E fails:** it charges capital on margin growth even when no capital is needed (M1 −6.0%, M4 +5.8%).

## 3. Exploratory (post hoc; it does not change the ruling)

C was registered with the wedge common to all candidates. But C already counts the change in capital, so C with the wedge
double-counts. Rerun without the wedge (oracle path):

| Firm | R | E | C |
|---|---|---|---|
| M1 | −0.14% | −6.00% | −0.21% |
| M2 | +12.30% | +9.32% | +1.80% |
| M3 | +5.06% | +0.17% | +0.68% |
| M4 | −0.14% | +5.75% | −0.22% |
| M5 | −5.44% | −3.64% | −0.67% |

So **C without the wedge also passes all five** (max 1.8%). There are two internally consistent schemes:
- R with the wedge: built, approved (O2), max error 0.59%;
- C without the wedge: not built, max error 1.8%.

## 4. Limit (stated, not fixed: the pre-registration forbids changing firms after the run)

- In M2, M3 and M5 the investment programme starts at year 5. That is exactly where the wedge measures the gap between
  actual and implied reinvestment.
- An investment that starts later (inside the fade) would not appear in w₅. R would then miss it, while C would still see it
  through RONIC_T.
- The test therefore shows R with the wedge is right when the explicit years show the investment. It does not show this for
  a margin bought later.
- **Recommendation:** pre-register a v1.1 test with a late-start firm (investment from year 8) before 3Q's freeze, comparing
  R+wedge with C−wedge. If R+wedge fails it, the typed driver (X) of SPEC §3 is the fix: the analyst cites a later capital
  programme through the O2c investment-state path, which already exists for exactly this.
- Until then, D2 runs R. Names whose cited evidence describes a margin programme beyond year 5 carry the annotation
  `fade_margin_investment_after_year5`.

## 5. v1.1: a programme that starts inside the fade (PREREG_q3_fade_v1_1.json, sha256 `0476c4cc…0650`, committed `58628cc` before the run)

**Firm M6_late_invested:** firm A, with 1.4× vintages from year 8 and the margin following the new-technology share, so
0.25 → 0.30 over years 8–23. Analyst F = 18. Code: `q3_fade_late.py`; output `q3_fade_late.json`.

| Candidate | Oracle path | Desk path |
|---|---|---|
| R with the wedge (as built) | **+11.92%** | +12.72% |
| C without the wedge (reported only) | +2.38% | +2.94% |

- w₅ is 0 here: nothing is visible by year 5, so the wedge cannot help.
- **By the registered v1.1 rule:**
  - R stays the default.
  - A margin programme that starts after year 5 must enter through the O2c cited investment-state path.
  - WO_Q5 makes `fade_margin_investment_after_year5` a **contract rule**, not an annotation. A cited later programme with
    no O2c path is unsupported until repaired.

**Reading across v1.0 and v1.1:**
- C without the wedge is within ±3% on all six firms: max 2.4% on the oracle path, 2.9% on the desk path.
- R with the wedge is within ±3% on five of the six, and needs the analyst to cite later programmes.
- C was found post hoc, so it cannot be adopted on this evidence. Adopting it needs its own pre-registered test on firms not
  used here, with both schemes and the O2c route compared.
- That test is recommended for 3Q's WO_Q2 suite before E2. It costs a few CPU seconds.
- Until then, B1 = R plus the O2c contract rule.

## 6. v1.2: new firms (PREREG_q3_fade_v1_2.json, sha256 `e0cf67c5…a5d`, committed `dffca32` before the run)

Code: `q3_fade_new.py`; output `q3_fade_new.json`. Errors against the true value:

| Firm | R with the wedge, oracle (desk) | C without the wedge, oracle (desk) |
|---|---|---|
| N1_invested_y6 (1.3× vintages from year 6, life 20) | **+10.99%** (+11.62%) | **+3.34%** (+3.93%) |
| N2_decline_life10 (margin down, no capital) | −0.38% (−0.38%) | −0.19% (−0.19%) |
| N3_invested_y10 (1.5× vintages from year 10) | **+13.44%** (+14.59%) | +1.87% (+2.53%) |
| N4_growth_pricing (3% real growth, pricing) | −0.32% (−0.32%) | −0.24% (−0.24%) |
| N5_mixed_late (from year 7, part pricing) | **+7.02%** (+6.24%) | +0.77% (+0.34%) |
| **Passes (±3%)** | 2/5 | 4/5 |

**By the registered rule:** C does not pass all five (N1 at +3.34%), so **B1 = R stays**, with v1.1's O2c contract rule.

**What the evidence says, across v1.0–v1.2 (17 margin firms):**
- R with the wedge is right whenever the investment is visible in years 1–5, or the margin needs no capital.
- It overvalues by 7–13% whenever a margin is bought after year 5. The wedge is then zero, so nothing in the inputs carries
  the programme.
- C without the wedge infers the capital from the change in RONIC_T. It is within ±3% on 10 of 11 firms in total.
- **But** C relies on the analyst's RONIC_T already reflecting the later programme. That is the same information an O2c
  cited path carries, just entered through a single number instead of a cited capex path.

**Consequence for 3Q (WO_Q5):**
- `fade_margin_investment_after_year5` is a contract rule: a margin rise that the cited evidence ties to capital spent
  after year 5 needs the O2c path, or the input is unsupported.
- A margin rise above the record with no evidence of its source already fails V3.
- Whether to replace the wedge by C is left as an open design option, not a ruling. It needs an operator decision (O2 is
  approved) and a test where RONIC_T is the analyst's estimate, not the truth.
