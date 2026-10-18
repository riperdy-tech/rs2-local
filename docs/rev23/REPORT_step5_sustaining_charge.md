# Step 5 report: the sustaining charge s, tested in the harness

*2026-10-18. Step 5 of `PLAN_terminal_reinvestment.md` (operator: option 1, step 5 before the desk port). Offline. Code:
`scratch/rev23/terminal_d2/reference_d2.py`, `synthetic.py` (firm C3 added).*

## The question

D2 kept a sustaining rate s in the fade and terminal, Flow = X (1 − s)(1 − g/RONIC):
- **positive for depleting companies,** measured from reserve disclosures: S = (F&D cost per boe × production − DD&A) × (1 − δ);
- **negative for equity REITs,** from recurring capex: s = (recurring capex − D&A)/E (O6).

Step 5 was to measure s and pass C, C2 and H with it.

## Results

**1. The filed measure double counts on every steady history.** Firm A (no depletion, no escalation) has (capex − D&A)/E = 0.16, and
applying it gives −9.9%. That gap is the reinvestment that growth and inflation require, which g/RONIC on book capital already charges
(`REPORT_synthetic_baseline_terminal.md` finding 1). For the depleters measured at year 0, the F&D-based s is 0.068 (C) and 0.044 (C2).
That is the same inflation lag, because replacement cost had not yet started to escalate when the history was filed.

| Firm | s measured from the filings | D2 default, s = 0 | D2 default, with that s |
|---|---|---|---|
| A | 0.160 | +0.00% | **−9.90%** |
| C | 0.068 | +7.37% | +5.80% |
| C2 | 0.044 | +4.53% | +3.63% |
| H (recurring capex, negative s) | −0.053 | **+1.73%** | **+5.79%** |

For C and C2 the measured s shrinks the error only by offsetting another one (the fade shape below), and both still fail. For H it moves a
pass to a fail. **A sustaining charge measured from history is not a measurement of anything the formula does not already charge.**

**2. What C's error actually is.** C's replacement cost escalates 3% a year faster than its price for years 0–20. That is a forecast of
future cost, which no filed history at year 0 contains. Its error sits in the fade, where the desk moves the margin and RONIC linearly
while the true decline is shaped by the escalation and the 10-year asset life. Under O2c the analyst states that path:

| Firm | D2 default | levels to year 20 (cited path) | levels to year 30 |
|---|---|---|---|
| C | +7.37% | **+2.30%** | **+0.00%** |
| C2 (40% debt) | +4.53% | **+1.59%** | **+0.00%** |

C2 also confirms the δ treatment of the reinvestment term: levered, it is exact on the same path.

**3. The real depleter case: an impaired asset base (new firm C3).** Write-downs leave DD&A and book capital below replacement cost, so a
real treadmill follows until the reserves turn over. C3 is a flat-output depleter whose assets were written down 50% at year −1:
- capex/DD&A 2.06 at year 0 (EQNR: 1.42), falling to 1.14 over one reserve life;
- book return 44% at year 0, 21.8% in steady state.

| | Today's desk | D2 default (gap over F, s = 0) | D2, levels to year 10 / 14 / 20 |
|---|---|---|---|
| C3 | **+6.64%** | **−0.08%** | +0.30% / +0.10% / +0.10% |

D2 needs no s here. Years 1–5 carry the actual capex (O7), the year-5 gap fades over F, and RONIC moves from the inflated book return to its
steady level. Today's desk overvalues the impaired depleter, and D2 does not.

## Ruling (for the operator: O8)

**s is removed from the production formula** (s = 0 everywhere). In its place:

- **Depleting companies:** the treadmill is handled by the actual capex of years 1–5 (O7), the gap fading over F, and the return path. A
  forecast of escalating replacement cost is a cited investment-state path (O2c).
- **The reserve-table measure becomes a diagnostic:** F&D cost per boe against DD&A per boe, pooled over five years. A large gap draws a
  reason request: "replacement cost is X% above DD&A; state the capex path through the end of the gap, or say why it closes."
  - **Step 5's ASC 932 table parsing** (EQNR, SM, DEC) is no longer on the critical path. It becomes a diagnostic input, built when the
    diagnostic is wired, not before the port.
- **Equity REITs:** no s (O6's negative s is dropped). The book return on GAAP-depreciated capital already charges only the reinvestment
  equity and debt fund. Recurring capex against D&A becomes a diagnostic.
- **Miners (O4):** they need no separate rule, by the same logic. The flag-only status is removed.
- **Design D's ρ_sust residual:** stays a diagnostic (O1, unchanged).

**Why this is not over-fitting:** the ruling removes a parameter rather than adding one. It rests on an identity (firm A), not on the
table. The firms where s looked helpful (C, C2) are fixed instead by the analyst's stated path, which carries a citation.

## Effect on the plan

- **The reference now meets the registered criteria for every firm step 3 owns, with s = 0:** A, B (levels), B2, C, C2 (cited path), C3,
  D, E (levels), F, G, H, I.
- **Step 5 as planned** (measured s, ASC 932 parsing for EQNR, SM and DEC) reduces to wiring the diagnostics.
- **The desk port (step 3, part 2) can start once O8 is ruled.**
