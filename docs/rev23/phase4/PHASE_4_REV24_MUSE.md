# Phase 4, revision 24 (v2): Muse as the analyst; no reference anchor; facts and population ranges

**Status:** v2 work order, 2026-10-16. It replaces v1 (`db634f8`). The rulings are in `PHASE_4_AMENDMENTS.md`, "Revision 24", from
cross-check 18 and the operator's "yes to both, go ahead".

## The frame
- **This is Phase 4, finished:** the frozen analyst (revision 21 `f5a540c`, revision 22 `412578d`, branch `review-2026-09/phase-4`), with Muse
  Glimmer as the model. It keeps research, PRIMARY SOURCES, search refusals, the crux rule, the desk and the gates.
- **Build branch:** `review-2026-10/rev24-muse` (worktree `scratch/rev23/wt-rev24`).
- **Not touched:** production (`DEPTH_PAUSED`, `KIS_HALT`), the screener, and the code-baseline paper books.

## The problem (`rev23/defect_census.md`; the R24.2 finding)
- **The baseline's skew:** growth stocks at 0.2–0.45× price, cyclicals and insurers at 2–3.7×.
- **The analyst started from the briefing's DEFAULTS,** and the defaults **are** the reference formula's inputs, so run unchanged they
  reproduce the reference to the cent.
- **The long-run defaults carry the formula's defects:**
  - margins forced back to their history (O1);
  - the margin translation (O2);
  - terminal growth from the company's record (O3);
  - normalization switched off, so peak earnings last forever (U1, U4, U5);
  - shrinking companies growing (U2);
  - owner earnings overstated for under-investors (U3).

## The design (modified option iii)
1. **The reference is never shown to the analyst.** The CONSENSUS-IMPLIED VALUE, its fence, its window quote, its DEFAULTS lines and the R10
   gate are all off. **Stage B, the reveal, is not used.** The code stays behind a flag that is off and tested off. The reference is computed
   and logged as a benchmark only.
2. **Facts stay as defaults.** Filed facts (base earnings, D&A, capex, the record), the discount-rate anchor and the arithmetic conventions
   stay as defaults: they are not judgments.
3. **Long-run judgments get population ranges instead of formula defaults.** For each long-run input (the long-run margin, the growth fade
   and its length, terminal growth, the return on new investment), the briefing prints the population distribution for the company's cohort,
   from rev23 `priors_v5` at the right point-in-time vintage:
   - `margin_retention`;
   - `normalization` (by cyclicality);
   - `growth_decay`;
   - `terminal` (including shrinking firms);
   - `ronic` and `ronic_fade`.

   Each comes with the cohort's definition and n. **P50 shown or omitted is a pilot arm,** not decided yet.
4. **Consensus years 1–2 are evidence, not fixed inputs.** The analyst states its near-term earnings, then its **normalized mid-cycle
   earnings**, and the transition between them with a reason.
5. **Per-dimension classifications in Section 12,** each from the evidence and none forced:
   - `margin_persistence` (structural / partly / transient);
   - `cycle_position` (trough / mid / peak / not cyclical);
   - `growth_trajectory` (accelerating / steady / decelerating / shrinking).

   Each has a one-line evidence pointer.
6. **Three levels of citation:**
   - an in-range input: a concise rationale tied to the facts and the population;
   - an input outside the cohort's P10–P90: a sourced, causal explanation of why this company differs;
   - the buy or sell crux: verified primary-source quotes (revision 21, unchanged).
7. **The plausibility gate** (fiduciary gate, new checks) on the **whole implied trajectory:**
   - **Mathematics:** terminal growth below the discount rate. A violation is rejected.
   - **Flagged when outside the population's P5–P95** for the cohort:
     - the implied long-run margin;
     - the implied revenue CAGR to year 10;
     - the implied return on new investment;
     - the implied earnings ÷ base;
     - terminal growth.
   - **A flag with an outlier-level citation passes, annotated. A flag without one is rejected** (`implausible_unsupported_<metric>`, named).
   - **Never clamped,** and there are no hard caps.

## The sequence
| Step | What | Check |
|---|---|---|
| 1 | **Arithmetic audit** of the desk and the default generator: the operating-to-earnings margin translation traced end to end; a unit test per input proving its intended effect on cash flow; O2's translation behaviour reproduced or cleared | Tests; the coordinator reads the trace |
| 2 | **Build modified (iii):** stage A as built (`600be12`) with the remaining leaks closed (the TTM window value, the lines naming the reference); stage B off; points 2–7 above; an audit of the population tables for survivorship and look-ahead | The suite (42 known failures, no new); the coordinator reads a rebuilt real pack |
| 3 | **Blinded six-stock ablation pilot** on Muse, one sample per arm. Names: UGI, MPWR, MU, LAMR (AT10c) and two census extremes (one growth, one cyclical). Arms: the revision-22 briefing; (iii) with P50; (iii) without P50. Each input vector frozen before valuation | — |
| 4 | **Evaluation on four separate dimensions,** with no valuation-to-price target: (a) clustering at the midpoint or a boundary, and sensitivity to harmless presentation changes; (b) run-to-run stability (a second sample on 2 names); (c) cash-flow plausibility, judged by the coordinator without the price or the reference; (d) evidence for outliers and the crux | A plain report to the operator before expanding |
| 5 | Expand to more names and categories | — |
| 6 | The live paper record, graded by TRK-06 at 30/60/91 days | — |

## Time
- **Muse:** about 30–50 minutes per name per sample. The pilot is 6 names × 3 arms plus 2 repeat samples, about 12–15 GPU-hours.
- **Build:** about 1 day for step 1; about 2 days for step 2.
