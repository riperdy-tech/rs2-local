# Brief R24 step 2b: population ranges, per-dimension classification, three citation levels, the plausibility gate (Phase 4 revision 24 v2)

## Where and how
- **Repository:** rs2-local. **Worktree:** `scratch/rev23/wt-rev24`, branch `review-2026-10/rev24-muse`, **after step 2a is committed and audited**
  (the coordinator says when).
- **Limits:** no GPU, model or server; no push, merge or deploy; no deletes; no `.env*`; commit by pathspec; the 42 known failures plus the
  timing flake, no new failure; wait for more than 2.5 GB of free memory before the full suite.

## Read first
- `PHASE_4_REV24_MUSE.md` (v2), design points 1–7, and `PHASE_4_AMENDMENTS.md` "Revision 24" and "Revision 24 step 1".
- `rev23/defect_census.md`.
- **The population tables:** `C:\Users\riper\stocks\stocks-workspace\data\priors_v5\<vintage>\tables.json` (vintages 2012–2025; the vintage
  for a valuation date T is year(T) − 1). The keys used here are `edges`, `margin_retention`, `normalization`, `growth_decay`, `terminal`,
  `ronic` and `ronic_fade`.
- **Their definitions, in the rebuild code** (read-only, another worktree; never import it): `stocks-workspace/scratch/rev23/wt-v21`:
  - `valuation/priors.py` (`PopulationPriors`, `for_company`, the cohort assignment from `edges`, `cuts` and the bands);
  - `valuation/priors_build/` (how each table was measured, the survivorship and delisted handling, the point-in-time cut);
  - SPEC_rebuild addenda on the priors: `stocks-workspace/docs/review_2026-09-22/rev23/SPEC_rebuild.md` (search "priors", "margin_retention",
    "normalization", "survivorship").
- The pack builder, `tools/audit_202608/capability_test.py` (DEFAULTS through `pack_facts.py`, the TASK), Section 12 (`extract_scorecard`
  in `consensus_valuation.py`), and `tools/audit_202608/fiduciary_gate.py`.

## What to build
**1. `tools/population_ranges.py`, read-only over `tables.json`.** No import of the rebuild code: rs2's repository rules.
- `ranges_for(company_record, T)` → for each long-run input, the cohort, its definition, n, the vintage, and the quantiles P5, P10, P25, P50,
  P75, P90 and P95:
  - **long-run earnings margin**, from `margin_retention` (the retained share of the deviation from trend at its largest measured k), turned
    into this company's margin levels as `trend + R × (current − trend)` at each quantile of R; also `normalization` for the cyclicality band;
  - **growth for years 3–10**, from `growth_decay`, by growth band;
  - **terminal growth**, from `terminal` (the family, and `shrinking` when the record's revenue trend is below 0);
  - **return on new investment**, from `ronic` and `ronic_fade`.
- The cohort assignment must reproduce `PopulationPriors`' rules exactly. **Parity:** a script, not a unit test, comparing the cohort and the
  quantiles with `wt-v21`'s `valuation/priors.py` on 30 real companies at 2 dates, run in that worktree's own interpreter. Report it. A
  mismatch is listed, never hidden.

**2. The briefing.**
- A new **POPULATION RANGES** section after DEFAULTS. For each long-run input: the cohort (in words), n, the vintage, P10/P25/P75/P90, and
  **P50 only when `ranges_show_p50` is true** (a pack flag; the pilot runs both).
- One line states: "how companies like this one actually evolved; context for your choice, not a target."
- **Facts stay as defaults:** base earnings, D&A, capex, the record, the COE anchor, working-capital intensity, excess cash.
- **Long-run judgments get no default:**
  - `long_run_margin` (2a's input);
  - the years 3–5 growth path;
  - `fade_years`;
  - `terminal_g`;
  - `terminal_ronic`.

  Their DEFAULTS lines are removed, and the population ranges stand in their place.
- **Consensus years 1–2 are printed as evidence** ("what analysts forecast"), not as the desk's held levels. The desk's year-1–2 hold
  (`LEVELS_HOLD_TOL`) is **off**: the analyst sets the years 1–2 growth itself, and the consensus is the evidence.

**3. Section 12 contract additions** (the `extract_scorecard` whitelist, the medoid summary, the `band_verdict` copy, the contract;
non-negotiable 5):
- `near_term_earnings` and `normalized_earnings` (both decimals, $B), with `normalization_reason` (text);
- `margin_persistence` ∈ {structural, partly_structural, transient}, `cycle_position` ∈ {trough, mid, peak, not_cyclical}, and
  `growth_trajectory` ∈ {accelerating, steady, decelerating, shrinking}, each with `<name>_evidence` (a one-line pointer);
- `input_rationale`: for each long-run input, {value, within_p10_p90: bool, rationale, citation (when outside P10–P90)}.

**4. The TASK text** (briefing text, pack revision 24): replace the "start from the DEFAULTS" instruction for the long-run inputs with:
1. state your near-term and normalized earnings and the transition;
2. classify the three dimensions from the evidence;
3. choose each long-run input, using the POPULATION RANGES as context, not a target;
4. the citation levels:
   - **in range:** a concise rationale tied to the facts and the population;
   - **outside P10–P90:** a sourced, causal explanation of why this company differs;
   - **the buy or sell crux:** verified primary-source quotes (unchanged).

Never mention the CONSENSUS-IMPLIED VALUE.

**5. The plausibility gate** (new checks in `fiduciary_gate.py`, computed from the answer run's desk output and the ranges):
- **Mathematics:** `terminal_g < discount rate`, or **reject** (`terminal_growth_not_below_rate`).
- **Implied metrics:**
  - the long-run earnings margin;
  - the revenue CAGR to year 10;
  - the return on new investment at the terminal;
  - year-10 earnings ÷ base earnings;
  - terminal growth.

  Each is compared with its cohort's P5–P95.
- **Outside P5–P95:** with an `input_rationale` citation that resolves (a PRIMARY item or a filing quote that `crux_check`'s verifier
  accepts), it passes with the annotation `implausible_supported_<metric>`. Without one it is **rejected** (`implausible_unsupported_<metric>`,
  the verdict `not_usable` with that reason).
- **Never clamped,** and there are no other caps.

**6. The population-table audit, recorded in your reply:**
- survivorship: are delisted, acquired and distressed firms in the measurement? How many, and with what bounds?
- look-ahead: is every vintage built only from data before its cut date? Cite the rebuild's no-look-ahead proof and its tests.
- **Any gap is listed,** not fixed.

**7. Pilot arms:** a pack flag `pilot_arm` ∈ {rev22, iii_p50, iii_no_p50}. `rev22` reproduces the revision-22 pack byte for byte (the control);
the two `iii` arms differ **only** by P50.

## Tests
- The ranges reader against fixture tables: the cohort, the quantiles, the vintage by date, shrinking.
- **The briefing:** no long-run defaults; the ranges printed; P50 only on its flag; the `rev22` arm byte-identical to revision 22 on the 3 saved
  packs; consensus printed as evidence.
- **The Section 12 fields** reach the verdict row.
- **The gate:** a supported outlier passes annotated; an unsupported one is rejected by name; terminal growth at or above the rate is
  rejected; an in-range value passes.

## Deliverable
The commits, the suite counts, the parity report, the population-table audit, one rebuilt real pack's POPULATION RANGES section (both P50
arms) and its TASK text, and every judgement call or gap. Reply as text; decide nothing left open.

## Additions from step 2a (2026-10-16 08:21; `PHASE_4_AMENDMENTS.md` "Revision 24 step 2a")
- **Ruling 3:** when the facts hold no year-5 revenue, m5 = the base fiscal year's filed earnings margin, stamped `m5_from_base_year`, so
  `long_run_margin` applies. When the base margin is not positive, the margin is held with `long_run_margin_not_applied_no_revenue` and a
  reason. Test it on the 17 saved packs that lack year-5 revenue.
- **Close the 2a gaps:**
  - remove the DEFAULTS `long_run` line's long-run margin, ratio and OM_5. Then test that the CIV **cannot** be re-derived from the rebuilt
    text on the 3 saved packs, plus HRTG and KSS: a desk run at any printed defaults must not land within 5% of the CIV unless the analyst's
    own long-run inputs put it there;
  - update the DEFAULTS explanation text;
  - add `long_run_margin` to the price-implied block;
  - name `long_run_margin` in the TASK;
  - put `long_run_margin` (and every other long-run input the analyst chose) on the verdict row;
  - reword `excess_cash`, `coe_premium_source` and `working_capital` so they never say "the reference".
