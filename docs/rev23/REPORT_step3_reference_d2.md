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

## Addendum (2026-10-18): the O2b reviews, and ChatGPT's mandatory condition tested

Gemini and ChatGPT both approve O2b. ChatGPT made one condition mandatory: firm E is not accepted on its total value alone; the annual
flows must show the holiday and the rebuild. **Tested: the condition fails O2b as worded.**

**Firm E with the gap fading over H = 3** (the O2b form both reviews specified; value −0.5%):

| Year | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|
| True flow | 0.220 | 0.229 | 0.215 | 0.101 | 0.107 | 0.115 | 0.122 | 0.130 | 0.138 | 0.201 |
| D2, gap over 3 years | 0.190 | 0.165 | 0.137 | 0.145 | 0.154 | 0.163 | 0.172 | 0.181 | 0.191 | 0.201 |

Years 6–8 are too low and the rebuild (years 9–14) too high: **the −0.5% is two wrong paths cancelling.** A gap that only declines
can end a holiday, but it cannot add the rebuild after it. ChatGPT's concern is confirmed.

**What does represent it: the levels leg extended through the end of the investment state.** The analyst's cited capex path runs to
year 5 + H, with H covering the whole state (holiday *and* rebuild). Through that year the flow is O7's levels formula; after it, the
funded path with no gap; the horizon is N = 5 + max(F, H) (ChatGPT's H > F rule, with no truncation). For E, H = 9 (the rebuild ends
in year 14):

| Year | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 18 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| True flow | 0.220 | 0.229 | 0.215 | 0.101 | 0.107 | 0.115 | 0.122 | 0.130 | 0.138 | 0.201 | 0.221 | 0.236 |
| D2, levels to year 14 | 0.224 | 0.237 | 0.226 | 0.114 | 0.120 | 0.126 | 0.133 | 0.141 | 0.148 | 0.203 | 0.245 | 0.267 |

The shape is right. **Value +3.03%: at the ±3% bar, not inside it, and not tuned to get there.** The residual has two named
sources:
- the pooled D&A ratio is inflated by the demand collapse in the base years. A roll-forward D&A rule does not help (+3.44%).
- after year 15 the true flows sit below the funded path, because the firm's 40-year asset life echoes the shock as uneven replacement
  capex for decades. No steady-state terminal represents that.

E is recorded as a borderline fail with its causes, not as a pass.

**Where each form belongs:**
- **No investment-state override:** the gap fades over F. This is O2 as approved, and it passes A, B2, D, G, H and I as reported above.
  Moving every firm to "no gap" (H = 0) is worse: H +5.4%, B2 −2.9%.
- **A cited state that ends, then returns to steady replacement:** a holiday followed by a rebuild, or a build-out followed by normal
  replacement. Use the levels leg through 5 + H with the analyst's capex path.
- **Not for long renewals** (firm B, a fleet replaced at once): levels through year 30 give −5.9%, because the pooled D&A ratio drifts
  over 25 years. A long F with the gap, −1.7% at F = 25, remains the treatment there.

**O2c, for the operator:** O2b's input H means *the years of the cited capex path beyond year 5*. That is, the levels leg is extended
through the end of the investment state, not a gap fade length. The default is H = 0 with the gap fading over F (O2, unchanged).
Cited and uncited handling is as O2b: an uncited path is used, stamped `investment_state_duration_uncited`, with a reason request.
There is no clamping, and the horizon extends when 5 + H > 5 + F. Gemini's diagnostic is kept: a negative ρ_5 faded over F > 5
draws `negative_reinvestment_faded_over_long_horizon`. The evidence must have been filed before the valuation date. The desk code tests
cited, uncited, malformed and missing H, and H > F.

**Firm C (ChatGPT's line):** its +12% was the 5-year gap fade, which is not used. At the default it is +5.3%, and its acceptance waits for
the measured s of step 5, as registered.

## Addendum 2 (2026-10-18): E's residual resolved by the D&A rule; τ·A across the horizon

ChatGPT's ruling: O2c approved as the specification. The port is held until E passes or a reviewed revision changes the criteria, and the
τ·A shield must be defined across an extended levels period. Both are done here.

**E's +3.03% split by source:** years 1–14 +0.027, years 15–20 +0.023, terminal +0.025 (truth 2.469). The first part was the D&A in the
reinvestment term: the pooled D&A/revenue ratio was inflated by the demand collapse, which hit revenue and not the asset base.

**Four D&A rules were tested, all reported** (no selection by outcome alone):

| Rule | How D&A_t is formed | Basis |
|---|---|---|
| pooled | pooled D&A / revenue × R_t | ties D&A to revenue, which is not its accounting driver |
| uniform | base D&A falls linearly to 0 over L = 2 net/D&A, plus capex/L | assumes uniform asset ages |
| ppe | pooled D&A / prior net PP&E × rolled-forward net PP&E | applies a rate on half-depreciated assets to new assets, about twice too fast |
| **vintages** | rebuild the base vintages from filed gross PP&E, net PP&E and D&A (L = prior gross / D&A; the geometric growth that reproduces net/gross), depreciate each vintage, and each year's capex over L from the next year | **the accounting identity itself: exact on any steady history** |

| Firm | Path | pooled | uniform | ppe | **vintages** |
|---|---|---|---|---|---|
| A | default | +0.00% | −2.40% | +0.00% | **+0.00%** |
| B | levels to year 30 (fleet renewal, cited) | −5.94% | −11.5% | +2.00% | **−2.91%** |
| B2 | default | −1.46% | | +0.69% | **−0.87%** |
| B2 | levels to year 8 | −1.90% | −3.61% | −0.31% | **−1.45%** |
| D | default | +0.00% | | +0.00% | **+0.00%** |
| E | levels to year 14 (holiday and rebuild, cited) | +3.03% | +1.34% | +0.45% | **+1.74%** |
| F | financial route | −1.19% | | −1.19% | **−1.19%** |
| G | default | −0.82% | −2.03% | −0.04% | **−2.71%** |
| H | default | +1.32% | | +2.21% | **+1.73%** |
| I | default | +0.00% | | +0.00% | **+0.00%, every period** |
| C / C2 | default (s is step 5) | +5.3% / +3.3% | | +8.4% / +5.1% | +7.4% / +4.5% |
| B | default, F = 25, no state override | −1.70% | | **+21.7%** | +4.78% |

**Ruling: the vintages rule.** It is chosen because it is the accounting identity, not because of the table. It is exact on every steady
history (A, D, I), and on the investment-state paths it reproduces the annual flows: E years 1–14 within ±0.001 of the truth, B years
1–30 exactly. Its errors are where the economics leave steady state (E's 40-year echo after year 15, B's terminal), and every registered
case passes on its intended path.
- **ppe is rejected:** B +21.7% on the default path.
- **pooled is kept only as the fallback:** gross PP&E is filed in companyfacts for 95 of the 139 non-financial names. The 44 without it
  (mostly IFRS filers, whose gross figure sits in the dimensioned PP&E note, and shippers) take pooled, stamped `da_vintages_no_gross_ppe`.
- **G at −2.71%** passes, but nearer the bar than under pooled. The pooled −0.82% hid an offset against the linear-fade error recorded in
  part 1 §4.

**B's two paths.** Under O2c, a fleet renewed at once is a cited investment state: the young fleet needs almost no replacement until the
ships near their life. Its route is therefore levels to the end of that state, −2.91%. The default path with a long F (+4.78%) is not the
route for B. The pack's F guidance sentence (part 1 §3) is replaced by the O2c guidance: state the investment-state path.

**τ·A across the horizon.** A_t is the filed five-year schedule. Beyond it, the filed "thereafter" balance runs off at the year-5 rate until
exhausted. τ·A_t is added in the levels leg, the fade and the transition alike, and it is carried outside the year-5 gap, so the
transition has no step. Firm D: +0.00% (−1.7% today, +0.2% in part 1 when the shield stopped at year 5).

**E's status: passes (+1.74%)** on a general rule fixed before E was re-run on it. The criterion is unchanged.

**Remaining before the desk port:** C and C2 wait for the measured s of step 5, as registered. With that, the reference meets the
registered criteria for every firm step 3 owns.
