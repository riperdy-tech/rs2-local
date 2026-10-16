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

## Amendments (each dated, made before any pilot run)
**Amendment 1, 2026-10-16 10:20.** UGI (utility) and LAMR (REIT) are in families the population tables do not measure (step 2b; ruling 7), so
their `iii_p50` and `iii_no_p50` packs are byte-identical and two runs at the same seed would duplicate each other.
- For these two names, the `iii_no_p50` slot runs `iii_p50` at seed base 2402 instead, a stability repeat counted under (b).
- The run count stays 22. (b) now covers MU, AMD, UGI and LAMR. (a) and the P50 comparison cover MPWR, MU, AMD and CMRE.
- Stage R refuses when stage P finds this assumption false: ranges printed for UGI or LAMR, or none for another name.

**Amendment 2, 2026-10-16 10:20.** Measure (d) named "revision 21's checks I1–I8". The AT10b/AT10c scorer and AT10b's base registration (its
section 7, the definitions of I1 and I3–I7) no longer exist on disk. They lived in a session scratchpad that has been cleaned. (d) is
therefore:
- **computed:**
  - the run's own `crux_check` verdict and stamps per sample;
  - the crux follow-up firings;
  - the plausibility-gate outcomes, with the resolution of each outlier citation;
  - `pack_revision`, provider and model tag (I2);
- **read by the coordinator:** I8's revision-21 mechanics (served-from-primary refusals, follow-up conditions, PRIMARY citations resolving),
  in every memo read under (c).

I1 and I3–I7 are not rebuilt for a failure-finding pilot. This is recorded as a reduction of (d) from the registration's text.

**Amendment 3, 2026-10-16 10:35 (cross-check 19, ruling 8; supersedes amendment 1's use of the slots).**
- UGI and LAMR run `rev22` and `iii_p50` only (seed base 2401); stage R still refuses unless stage P built identical iii packs for them and
  printed no range.
- Their two freed slots run `iii_no_p50` at seed base 2402 for **MPWR** and **CMRE**.
- **Repeats:** MU and AMD in both iii arms; MPWR and CMRE in `iii_no_p50`. 22 runs. (b) covers the four names with ranges.

**Amendment 4, 2026-10-16 10:35 (cross-check 19, ruling 10): the rubrics, fixed before any run.**
- **(c) Cash-flow plausibility,** per masked iii memo:
  - **coherent:** the years 1–10 trajectory (earnings, margin, growth, reinvestment) follows from the stated near-term earnings, normalized
    earnings and transition; each classification matches its cited evidence; no input contradicts the filings or the research brief.
  - **questionable,** one of:
    - an unexplained break in the margin or growth path;
    - a classification whose evidence pointer is generic or does not address it;
    - a long-run input whose rationale is not tied to the company's own facts.
  - **incoherent,** any of:
    - the trajectory contradicts the filings or the research brief on a material point (for example margin persistence "transient" with a
      long-run margin at or above the current peak, or a "shrinking" trajectory with growth above the cohort median);
    - an impossible quantity (a margin above 100%, negative revenue);
    - near-term or normalized earnings that contradict filed figures without an explanation;
    - two or more "questionable" findings.
- **(d) Outlier-citation relevance,** each citation supporting an input outside P10–P90 or a gate outlier:
  - **causal:** the quote states a mechanism, a contract or a filed figure that bears directly on the input's level;
  - **related:** it is about the company and the topic, but not the level;
  - **generic:** boilerplate or unrelated.

  Only "causal" counts as support in the report. A gate pass resting on a related or generic citation is reported as a gate failure of
  relevance.
- **(a) Systematic copying** in an iii arm, across the names with ranges. Any one of these is systematic copying:
  - **P50 copying** (`iii_p50`): more than half of the chosen inputs that have a printed P50 lie within 0.5 percentile points of P50;
  - **boundary copying:** more than half of the chosen inputs lie within 0.5 points of the same printed quantile;
  - **constancy:** for any one input, the chosen percentile spans less than 5 points across all the names.
- **Blinding:** the (c) and (d) scores are written to one file, and its sha256 is recorded in `PHASE_4_AMENDMENTS.md` before the key is opened.
- **Compliance, per arm with denominators** (cross-check 19, ruling 12):
  - malformed or refused desk calls;
  - missing Section 12 fields;
  - invalid classifications;
  - citations lost or unresolved;
  - crux-form failures.
- **Not covered, stated:** the shrinking-retailer and peak-insurer failure modes. They are tested at the desk (step 2d), not in the pilot.

**Amendment 5, 2026-10-16 12:05 (cross-check 19 follow-up).**
- **(c) rubric:** a perpetual trajectory whose terminal reinvestment exceeds earnings (terminal_g above 0 and above terminal RONIC,
  annotated `terminal_reinvestment_above_earnings`) is **questionable** unless the memo explains it, and **incoherent** for a business the memo
  calls mature or steady.
- **(d):** the gate's annotation-only checks (the long-run margin against the five-year margin range; the terminal RONIC against the
  five-year ROIC range) are reported with their citation relevance, like the rejections.
