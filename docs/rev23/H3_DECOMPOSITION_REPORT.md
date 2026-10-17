# Revision 25 Stage 0.1: the H3 decomposition of the 22 pilot Base values (2026-10-16)

## Provenance
**The files**, all in `stocks-workspace/scratch/rev23/pilot_r24/h3/`:
- `DEFINITIONS.md`, sha256 `f03988ff…`, written and hashed at 19:54 before anything was computed;
- `recompute.py`, the independent code: it imports nothing from rs2;
- `table.py`;
- `h3_results.json`;
- `H3_TABLE.md`, the full tables.

**Reproduction:**
- **All 22 Base values reproduced.** The largest difference is 3.4e-13 dollars per share.
- No growth was changed by a cap or hold.
- Shares, cash, working capital and the roll-forward agree with the saved `dcf_details` to their printed precision.

**Deviation 1.**
- **The defect:** the S-rejoin and P-rejoin rule as written ("one equal rate over years 3–5") moves year-5 growth, which is where the fade
  starts. At zero change it therefore failed to reproduce the saved value, by up to $2.76.
- **The fix:** the gap to the saved path closes geometrically in year 3 (OE3 × ratio^0.5), and years 4–5 are the saved values. At zero
  change this reproduces exactly, and g5 is unchanged.
- **Why it is not results-driven:** the defect was found by the reproduction check, before any result was read.
- **The record:** the original rule's numbers are kept in the JSON as `rejoin_v1`.

## Mechanical results
**The value split.** Years 1–2 flows are 3–15% of the Base value and years 3–5 are 7–23%. The fade is 16–37% and the terminal value
36–58%. Cash is 0–16%, CMRE's being the largest.

**The sensitivity per +1 pt of g1 or g2, in two cases:**
- **persist** (later rates held, so the level carries forward): the change is 0.41–1.08% of the value. UGI's g1 is the highest, and MU's
  g1 the lowest because its year-1 growth is +134%.
- **rejoin** (the level rejoins the saved path by year 4): the change is 0.03–0.16% of the value, roughly a tenth of persist.

**What this means:** years 1–2 matter almost only through the level they hand to later years. The desk's rules make year-5 earnings
proportional to year-5 owner earnings, and the margin target is a ratio from that level. So years 1–2 set the scale of the whole long run.

## Reconciled counterfactuals: the change in Base value, persist / rejoin
**Consensus years 1–2:**
- **within ±2% under persist in 16 of 22 runs**, so the near-term path is in practice the consensus path;
- the exceptions:
  - AMD s2402 and rev22: +34% and +32%, analyst below consensus;
  - LAMR (both arms): about +20%;
  - MPWR iii_p50: −31%, analyst above consensus;
  - AMD s2401: +6%.

**The analyst's stated figures:**
- **MU (4 of 4), the stated figures honoured from year 2:** −43% to −47% read as owner earnings, −57% to −60% read as earnings. The
  stated year-1 figure is about consensus (146 against 145.9), but the stated "normalized" 80–90 is not on the path. Under rejoin the
  change is only −5% to −11%: what costs the value is a normalization that persists.
- **The metric ambiguity alone moves the value greatly:**
  - CMRE: +87% read as owner earnings, −1% read as earnings;
  - UGI: +107% against +10%;
  - MPWR s2401: +28% against −3%.

  That is the H1 finding expressed in value: until 0.2 defines the metric, the stated figures cannot be checked against the path.

**The trend:**
- **trailing (the 5-year revenue CAGR) against through-cycle** (trend revenue at the through-cycle margin):
  - MU: −30% against −82% under persist;
  - AMD: −22% to −43% against −51% to −64%;
  - MPWR: +2% to −24% against −24% to −48%;
  - LAMR, CMRE and UGI: within ±11%, except CMRE trailing at +37%.
- **Under rejoin** every trend counterfactual is within −18% to +4%.
- **The reviewer's warning holds:** at MU's cyclical peak the trailing trend reads −30% where through-cycle reads −82%.

## What H3 answers, and what it does not
**It answers:**
- **The value is set by the level carried out of years 1–2,** not by years 1–2 cash flows, which are at most 15% of it.
- In most runs that level is consensus.
- **MU:** if its stated normalization were carried into the path, the value would roughly halve. That is consistent with MU being a
  candidate contradiction.

**It does not answer:**
- **It does not prove MU contradictory.** By the plan's primary check, the margin path, MU's margin does fall from about 71% at year 5 to
  the analyst's 35% at year 10. The open question for 0.2 is the horizon and the level: 35% at year 10 against a stated reversion "toward
  the historical 24%".
- **No threshold is chosen from these numbers.** Thresholds are Stage 0.4.

**The input to 0.2:**
- the bridge must define the metric (owner earnings or earnings) and the horizon of "normalized";
- it must state whether a near-term level persists or rejoins;
- the persist-versus-rejoin gap is the size of what that choice decides.
