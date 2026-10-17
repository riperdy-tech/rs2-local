# Step 3, part 1: the D2 reference implementation in the harness

*2026-10-18. `PLAN_terminal_reinvestment.md` §3a and its amendment. Offline; nothing in rs2-local imported or changed. Code:
`scratch/rev23/terminal_d2/reference_d2.py` (D2 as specified, read in its docstring); rows: `reference_d2.json`.*

## The inputs the reference uses

- **Code-measured:** five-year pooled ratios to revenue (capex, D&A excluding lease depreciation and acquired amortization, lease
  principal, lease depreciation); working-capital intensity; the return on capital on the pack's basis (after lease interest, on capital
  less lease liabilities); δ = the firm's debt policy.
- **The ideal analyst's:** the true revenue and margin path for years 1–5; the capex path (mode 1, the true path, as a cited plan would
  state it, or mode 3, no override); the steady-state growth, return and margin; the fade length.

## Results (error against the true value)

| Firm | Today's desk | D2, true capex path, pooled D&A | D2, true capex, vintage D&A (P1 fallback) | D2, no capex override |
|---|---|---|---|---|
| A compounder | +0.0% | **+0.0%** | +0.0% | +0.0% |
| B fleet doubling | refused | −8.9% | +8.1% | +62.3% |
| B2 fleet +12% | −2.7% | **−1.5%** | +0.9% | +8.4% |
| C depleter | +9.1% | +5.3% (needs s, step 5) | +7.6% | +17.6% |
| C2 levered depleter | −5.0% | +3.3% (needs s, step 5) | +4.7% | +10.5% |
| D acquirer | −1.7% | **+0.2%** | +0.2% | +0.2% |
| E capex holiday | −3.2% | +11.6% | +11.0% | +3.9% |
| I lessee | +3.0% (offsetting) | **+0.0%, every period** | +0.0% | +0.0% |
| F insurer (financial route) | +19.2% | **−1.2%** | — | — |
| G utility | refused | **−0.8%** | +1.9% | +32.3% |
| H REIT (s = 0) | −8.0% | **+1.3%** | +2.0% | +10.0% |

**What passes on the specification as written:** A, B2, D, I (in every period), F, G and H. The tax shield τ·A fixes D's −1.7%. O5
and the lease terms fix H without any s. The no-override column shows why the capex override exists: the pooled history is wrong for any
company whose capex is about to change.

## What it settles

1. **P1: pooled D&A stays; the vintage rule is rejected.** It is never needed to pass and it overshoots: B is +8.1% at F = 10, and grows to
   +27% as F lengthens, against the pooled rule's convergence (below). It double-counts depreciation that the revenue-scaled ratio already
   carries once revenue follows the new assets.
2. **The year-5 gap's fade length (O2) fails firm E.** Fading over the analyst's F credits E's capex holiday for 15 years, while E's real
   holiday ends in year 8 and a heavy rebuild follows: +11.6%. No fixed length works for all firms:

   | Gap fades over | B | B2 | C | C2 | D | E | G | H |
   |---|---|---|---|---|---|---|---|---|
   | F (approved O2) | −8.9% | −1.5% | +5.3% | +3.3% | +0.2% | **+11.6%** | −0.8% | +1.3% |
   | 5 years (Gemini) | −14.3% | −2.2% | **+12.0%** | +7.2% | −0.5% | +1.8% | −0.2% | +3.5% |
   | 0 (jump at year 6) | −19.6% | −2.9% | +14.1% | +8.5% | −1.2% | −3.0% | +0.3% | +5.4% |

   **The right length is when the company's year-5 investment state ends,** a company fact. For E, capacity fills in year 8, three years
   after year 5: with the gap fading over 3 years E is **−0.5%**. With 2 years it is −1.8%, with 4 years +0.6%. That is a well-defined
   judgment input. It is the analyst's, cited: the year a holiday ends (capacity filled), or a build-out completes, from the filing's
   capacity, fleet or project disclosures. The default is F, so every other firm is unchanged. **This reopens O2 (decision below).**
3. **B (the fleet doubling) passes only with a fade that spans the fleet's life.** After the fleet is renewed, almost no replacement is
   needed for two decades, and a 10-year fade cannot see that. With F = 25 (the ship life) the pooled rule gives −1.7%; F = 30 gives
   −0.1%. F is already the analyst's input. The pack's guidance on F gains one sentence: after an asset renewal, the fade spans the
   renewed assets' life. That is pack text (PACK_REVISION, under the standing approval: versioned and recorded).
4. **G passes on value but not period by period.** Fade PV is 0.076 against 0.098, terminal 0.179 against 0.162. The desk's growth fades
   linearly, while the utility's rate base grows at a step (3.5% real to year 10, then 0.5%). This is a limit of the linear fade shape, not
   of D2. It is recorded, and no change is proposed: a stepped fade would be a new input with no case beyond G.
5. **H passes without the negative s of O6** (+1.3%). The book return on GAAP-depreciated capital is high, so the growth charge is already
   small. Step 5 will test whether a measured recurring-capex s improves or worsens H. If it worsens it, O6's s is dropped for REITs that
   do not need it, by evidence, not by assumption.

## For the operator

**O2b.** The year-5 gap fades over **the years until the company's year-5 investment state ends**: a holiday ends when capacity is
filled, a build-out when it completes. The analyst states it with a citation. The default is the fade length F (the approved O2), and an
uncited value is used, stamped `capex_state_uncited`, with a reason request. Evidence: firm E goes from +11.6% to −0.5%, and no other firm
changes.
