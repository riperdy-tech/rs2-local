# Where we are: one page (2026-10-15, corrected 2026-10-16)

> **Correction, 2026-10-16.** The first version of this page described the project as "a system that values US stocks from their SEC
> filings" with a code engine at its core. That is not the operator's design. It described the drift that AK.52's option A introduced
> without saying it removed the AI analyst (see AK.93, the correction of record). This version follows the system map
> (`docs/system-map/01_BIG_PICTURE.md`, `03_RS2_DEPTH.md`). The code engine's findings are kept below, as the comparison baseline.

## What the project is
- **The screener nominates the book:** research_now plus the watchlist, 159 names today.
- **The local AI analyst (Muse Glimmer) analyses each nominated stock.** It reads:
  - a prepared briefing: filed facts, the record, the market and the macro regime;
  - a deep-research brief and a discovery run of recent news;
  - its own searches of primary sources.

  It forms the judgment on each stock: what the business earns now, what it earns in the long run, and why.
- **Code does the arithmetic and the guards:** the valuation desk, the crux check, the integrity marks and the fiduciary gate.
- **Real money follows a proven record,** by the operator's decision. It has been halted since 2026-09-22 (`KIS_HALT`), after the old system
  bought ARX without an endorsement.

## Where the work is: Phase 4 (making the AI analyst work properly)
- **Phases 0–3 of the 2026-09-22 review are closed** (`STATUS.md`). Phase 5 waits for graded evidence. Phase 6's cutover and baseline wait
  for Phase 4. Phase 4 is the work now.
- **The analyst design is frozen** at revision 21/22 (AT10c passed on Qwen). Muse replaces Qwen as the model.
- **On Muse,** AT10b failed: the crux form and label splits.
- **The census of the old briefing** (`defect_census.md`) found the analyst copying the briefing's DEFAULTS, which reproduce the reference
  formula to the cent, including its defects: growth stocks valued low, cyclicals and insurers high.
- **Revision 24** (`PHASE_4_REV24_MUSE.md`, approved "yes to both, go ahead"):
  - the reference is never shown;
  - facts stay as defaults;
  - long-run judgments get population ranges, not formula defaults;
  - per-dimension classifications and three citation levels;
  - a plausibility gate that annotates or rejects, never clamps.
- **Status, 2026-10-16:**
  - the desk arithmetic is audited and fixed (step 1, step 2a);
  - the ranges and the gate are being built (step 2b);
  - the blinded six-stock Muse pilot is registered (`REGISTRATION_rev24_pilot.md`) and its runner is being built.

## The comparison baseline (the code engine v2.1)
- **What runs:** nightly, on about 2,000 companies, paper only, in three ledgers (`rn_v4`, `rn_v4_low`, `rn_v4_abs`) that real money refuses.
- **Its findings stand:**
  - it loses to a simple run-rate on year-1 forecasts (gate 2b, 07-31);
  - operating companies are valued at about 0.5× price and banks at about 1.5×;
  - the cost of debt is unfloored (the v2.2 candidate);
  - the bank ROTE outcome is unstable.
- **Its role:** something the analyst's live paper record is compared against. It is not the system.

## What happens next
| When | What |
|---|---|
| Now | Step 2b audited; the pilot runner built and audited; research and discovery for the six pilot names |
| Then | The pilot (22 Muse runs, about 12–15 GPU hours), read by the coordinator on four dimensions, with a plain report to the operator before expanding |
| After a good pilot | Expansion to more names; then the analyst on the screener's book, paper only, graded by TRK-06 at 30/60/91/182/365 days |
| After a proven record | Real money, by the operator's decision, with a small start and the ability to roll back |

## What is not at risk
`KIS_HALT` stays on and `DEPTH_PAUSED` is set. Nothing from this work can place a real trade. Every pilot and paper run writes only to test or
paper ledgers.
