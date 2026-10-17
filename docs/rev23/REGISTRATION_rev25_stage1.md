# Registration: revision 25 Stage 1, the controlled diagnostic pilot. Written before any Stage 1 run.

- **The governing plan:** `PLAN_rev25_2026-10-16.md` v2–v6.
- **This file is the rubric** that `versions.stamp` hashes into every run's `versions.json`.
- **Rules:** nothing here changes after the first Stage 1 run. A later point from cross-check 21 or course gate 2 is advice for Stage 2,
  never applied to Stage 1's own scoring (plan v6).

## Purpose
Does revision 25 make Muse's forecasts coherent and auditable on companies never used to build it? And which arm, B (consensus visible
from pass 1) or C (consensus withheld until pass 2), goes into the paper book? **Not the purpose:** moving values toward the price, the
old formula or consensus.

## Design (plan v5)
- **Names:** CWEN, MSGE, MRP, EQNR, FTNT, LIND, LFST and STT. They were hash-drawn, one per sector (`scratch/rev23/stage1_names/`, rule
  `a17f0bb0…`, names `7bf54ef5…`).
- **Arms:** A `iii_no_p50` (revision 24 as it ran), B `r25_b`, C `r25_c`. Facts, evidence, model, server pins, sampling, context and
  budgets are identical.
- **Known differences, recorded:**
  - B and C may take one extra pass-2 desk run;
  - C's pass-1 pack and desk withhold consensus (`_withheld_elements.json`).
- **Seeds:** base 2501; repeats 2502 for CWEN and MSGE in B and C. **28 runs.**
- **Frozen before the runs:**
  - the rs2 tree `9ed16fc`;
  - the bridge and class tolerances (τ_m 0.03, τ_R 0.10, τ_b 0.01, τ_g 0.02);
  - this rubric;
  - the masking tooling (`pilot_r25`, with hashes as recorded at stage P).

## Failure classes (plan v4)
- **Model outcomes,** final and never re-run: a reason loop, an exhausted budget, an unresolved fail, `two_pass_breach`, a lost memo, a
  refused contract.
- **Defects,** re-run with the same seed only: a runner or desk exception, a server or pin failure, a missing or changed frozen artefact.

## The blind rubric (the coordinator, on masked memos plus `blind_traj` trajectories, all three arms pooled and shuffled)
**(c) Forecast coherence,** per memo. One label (coherent, questionable or incoherent) with a one-line reason.
- **coherent** needs all of these:
  - the memo's story matches the desk's derived path. That means the revenue, margin and normalization it describes, and for B and C
    the bridge table: R, m, E, N_0 and N_H;
  - each classification matches its cited evidence;
  - no input contradicts the filings or the research brief;
  - every bridge or class check that failed carries a reason that addresses the specific disagreement.
- **questionable,** one of these:
  - an unexplained break in the margin or growth path;
  - a classification whose evidence pointer is generic;
  - a long-run input whose rationale is not tied to the company's own facts;
  - a failed check whose reason is generic ("conservative", "management guidance") without the figure that resolves it;
  - terminal reinvestment above earnings without explanation.
- **incoherent,** any of these:
  - the trajectory contradicts the filings or the research brief on a material point;
  - an impossible quantity;
  - a figure the memo states for near-term or normalized earnings that contradicts the desk's derived E_1 or N_0 (B and C), or the
    filed figures (A), without an explanation;
  - terminal reinvestment above earnings for a business the memo calls mature or steady;
  - two or more questionable findings.

**(d) Outlier support,** per input outside the printed P10–P90 or flagged by the gate. The label for each:

| Label | Meaning |
|---|---|
| causal | a mechanism, contract or filed figure bearing on the level |
| related | about the company and the topic, but not the level |
| generic | none of the above |

**An unsupported outlier** is one with no causal citation.

**Blinding:**
- the (c) and (d) scores go into one file, whose sha256 is recorded in `PHASE_4_AMENDMENTS.md` before `key.json` is opened;
- the masking must show 0 residuals before scoring.

## Code-measured (from the verdict rows; no judgment)
- **Unresolved contradictions:** C or K fails without `reason_given` on the final run (plan v4).
- **Compliance per arm, with denominators:**
  - refused or malformed desk calls;
  - missing contract fields;
  - invalid labels;
  - two-pass breaches;
  - lost memos.
- **Citations:** candidates resolved against finals (`measures.crux_report`); directional verdicts on a verified crux.
- **Stability** on the repeat pairs (plan v6).
- **Process:** minutes, desk calls, reason requests per run, the C and K fails and reasons by check ID, and the change log size (B and C).
- **The known limitation, counted:** the number of consensus-figure mentions in each name's research brief and news. It shows how much
  consensus reached C's pass 1 through the evidence.

## Expansion criteria, in the chosen arm, 10 runs (plan v6)
| Criterion | Pass |
|---|---|
| Incoherent (c) | at most 1 of 10 |
| Unresolved contradiction | at most 1 of 10 |
| Unsupported outlier | at most 1 of 10 |
| Two-pass breach or lost memo, combined | at most 1 of 10 |
| Directional verdict on an unverified crux | 0 |
| Runs failing two or more of the rows above | 0 |
| Compliance, citation resolution and memo integrity against arm A | no worse than A by more than 1 run of 10 |
| Stability | per repeat pair: the same direction label and the two Base values within ±25%; at most one pair may miss |

## Arm selection (B or C), fixed now and never by value
1. **The arm that meets the expansion criteria.** If both do:
2. **the fewer runs failing any criterion;** then
3. **the lower severity sum** (incoherent 2, questionable 1); then
4. **the higher citation resolution rate;** then
5. **the better stability.**
6. **A full tie goes to C,** because it is the stronger test of Muse's own judgment.

**If neither passes:** the v3 kill rule applies, and the model test follows, never a revision 26 interface.

## Reported after unmasking, informationally, with no bar
Value ÷ price, label and change-log contents, per name and arm.

## Not covered
Real money; the level of the frozen tolerances (Stage 2's sealed names); the long-run accuracy of the forecasts (TRK-06, from the paper
book).
