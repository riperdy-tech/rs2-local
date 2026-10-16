# Registration: the revision-24 Muse pilot (blinded six-stock ablation). Written before any pilot run.

**Status:** registered 2026-10-16 by the coordinator, under the operator's approval of the sequence ("yes to both, go ahead";
`PHASE_4_AMENDMENTS.md` "Revision 24", step 3). Fixed from now; a change is a dated amendment made before the affected run.

## Purpose
To find failures early, not to prove reliability. Does Muse, in the revision-24 design, choose its long-run inputs for defensible,
company-specific reasons, without copying a midpoint, a boundary or a formula, and does it stay coherent and stable? There are **no
valuation-to-price targets.**

## Design
- **Names (6):**
  - UGI, MPWR, MU and LAMR (AT10c);
  - **AMD**, the census's growth case (formula reference 0.45× price);
  - **CMRE**, the census's cyclical case (shipping, formula reference 2.01×, analyst 3.71×).
- **Arms (3), built from the same facts, the same research brief and one shared evidence store per name:**
  - `rev22`: the revision-22 briefing, the control;
  - `iii_p50`: revision 24 with P50 printed in the ranges;
  - `iii_no_p50`: the same, with P50 omitted.
- **Samples:** 1 per name and arm, seed base 2401. Repeats on **MU** and **AMD** for both `iii` arms, seed base 2402. That is 22 runs in all.
- **Model:** Muse Glimmer through `llamacpp`, with the pins in `config.json`, in a detached pilot tree at the audited revision-24 head.
  `depth_provider` is set **only in the pilot tree**.
- **Research:** one deep-research run per name before any arm, the brief frozen; the evidence store is shared by the arms.
- **The run order:** names in the order above. Within a name the arms rotate by name index, so no arm always goes first.
- **Blinding:** the coordinator's plausibility review (point c) reads each `iii` memo with the price, the reference, every value per share
  and the label masked by a script. The scores are written and hashed before unmasking.

## Measures (each reported separately; none combined into one score)
**(a) Clustering and presentation sensitivity** (the `iii` arms):
- For each chosen long-run input (`long_run_margin`, the years 3–5 growth, `fade_years`, `terminal_g`, `terminal_ronic`), its percentile
  within the cohort's printed distribution.
- **Rates:**
  - at P50 (within 0.5 percentile points);
  - at a printed quantile (P10, P25, P75, P90, within 0.5 points);
  - outside P10–P90.
- `iii_p50` against `iii_no_p50`.
- The spread of chosen percentiles across names (a constant percentile whatever the company is a red flag).

**(b) Stability** (the repeats): the base IV spread, label agreement, and the per-input difference between seeds.

**(c) Cash-flow plausibility** (blind, the coordinator), per memo:
- Is the implied trajectory (years 1–10 earnings, margin, growth, reinvestment) economically coherent with the company's filings and the
  research brief?
- Are the three classifications (margin persistence, cycle position, growth trajectory) consistent with the evidence it cites?

Each is scored coherent / questionable / incoherent, with a one-line reason.

**(d) Evidence:**
- outlier citations resolve, and are causal rather than generic;
- crux validity (revision 21's checks I1–I8);
- the plausibility-gate outcomes;
- the crux-form failures (Muse's known weakness in AT10b) and crux follow-up firings.

## Process measures
Minutes per run; desk calls; refusals; server errors; plausibility-gate flags.

## Reported after unmasking, informationally
For each name and arm: the final value ÷ price, the formula reference ÷ price, and the label. **No bar is set on them.**

## Reading
- **Expansion is recommended** when (c) has no incoherent memo in the `iii` arms, (d) has no unverified crux and no unsupported outlier
  accepted, and (a) shows no systematic copying (not most inputs at P50, nor at one boundary, across names).
- **Otherwise the report names the failure,** and the next step is the operator's.
- The P50 choice between the arms is made on (a) and (c).
