# Brief: revision 25, Stage 0.3, the bridge desk contract

**Worktree:** `stocks-workspace/scratch/rev23/wt-rev25`. **Branch:** `review-2026-10/rev25-bridge`, at `2b799bd`.

**Your limits:**
- commit there by pathspec;
- never push, merge or deploy;
- never edit `.env*` or any config;
- no GPU.

**Read first, and only these:**
- `stocks-workspace/docs/review_2026-09-22/rev23/SPEC_rev25_normalization_bridge.md`. **This is the spec;** where this brief and the spec
  differ, the spec wins.
- `rs2-local/AGENTS.md`.

**Token budget:** read the code by grep and by section, never a whole large file (`financial_model_tool.py` has 2,828 lines). Keep
your final report under 60 lines.

## What to build
1. **The switch** (single owner per field: add each new fact to its owner's list in `pack_facts.py`, or it is silently dropped):
   - a fact `desk_schema`, set to `"25.1"` for the new pilot arms `r25_b` and `r25_c`, and absent for every existing arm;
   - add both arms to `PILOT_ARMS` in `capability_test.py`;
   - for now B and C are identical. Their difference (consensus withheld until pass 2) is Stage 0.6; do not build it.
2. **The desk path** in `financial_model_tool.py`, active only when `desk_schema == "25.1"` and the scenario is perpetual and in the
   equity frame.
   - **The inputs:** `revenue_growth`, `earnings_margin`, `normalized_margin`, `normalization_horizon`, `normalized_revenue_base`
     (optional), `structural_growth` and `flags`.
   - **The arithmetic is exactly spec §4:**
     - κ = base_cf / (rev_L × x_L);
     - WC_t = nwc_intensity × (R_t − R_{t−1});
     - e5 = R_5 m_5 and g5 = R_5 / R_4 − 1;
     - margin_ratio = long_run_margin / m_5;
     - `consensus_reference.long_run_value` is called unchanged.
   - **Inheritance:** Bull and Bear inherit Base's normalization declarations unless they give their own.
   - **Missing path fields:** refused by name (`missing`), in the existing pattern.
   - **`growth_rates` or `explicit_growth` under 25.1:** refused, naming the new fields, so that there is only one path.
   - **The spec §4 non-applicable cases** keep revision 24's path, stamped `bridge_not_applied:<reason>`.
   - **The derived figures** go in `dcf_details["bridge"]`:
     - R, m, E, OE and WC for years 0–5;
     - κ;
     - m_t to 5+F;
     - N_0 and N_H;
     - the check results.

     The desk markdown report prints the same years 0–5 table and the check table.
3. **The checks** C1, C1b, C2, C3, C4 and C5: a new module `tools/audit_202608/bridge_checks.py`.
   - Pure functions, with no write path to any input. Each returns {id, status, declared, derived, horizon, tolerance}.
   - **The tolerances** live in one dict, `BRIDGE_TOLERANCES`, every value marked `UNCALIBRATED` in a comment. Use placeholders (τ_m 0.03,
     τ_R 0.10, τ_b 0.01). Stage 0.4 replaces them; nothing may read them from anywhere else.
   - **A fail becomes a reason request** through the existing `_need` / `_refusal` mechanism. The reason names are `bridge_C1_reason` and
     so on. With the reason given, the value computes and the check stays `fail`, annotated `reason_given`.
   - **Never** clamp, overwrite or re-label.
4. **The contract.**
   - Under 25.1, `near_term_earnings` (E_1, E_2) and `normalized_earnings` (N_0) are filled from the Base's bridge by `contract_fill`. A
     value the analyst typed is ignored and stamped `s12_figure_derived_under_25_1` when it differs.
   - **The new verdict-row fields** `bridge`, `bridge_checks` and `desk_schema` are added to their owner's schema. Find the owner of the
     S12 fields (`depth_pipeline.py` around line 728, and `consensus_valuation.py` around line 225) and follow it.
5. **The TASK.**
   - `TASK_REV25`, selected for packs with `desk_schema` 25.1 (see `task_for` around `capability_test.py:4294`).
   - It describes the new inputs and declarations, says the margin basis is the X basis, says operating margins are context, and says
     the two S12 figures are derived. It removes the instruction to type them.
   - Its `PACK_REVISION` is 25 for these packs only. Arms iii and rev22 stay as they are.
   - Keep the text minimal: no two-pass wording.

## Tests (the system Python per AGENTS.md)
- **Spec §8, all of it.** In particular: `long_run_value` is unchanged for equal inputs; each check has a pass, a fail and a
  not-computable case; and no check writes.
- **Arm A unchanged:** replay the 22 pilot desk calls through `execute_financial_model` with each run's own facts. The inputs are the last
  `run_financial_model` call holding `scenario_dcfs` in
  `stocks-workspace/scratch/rev23/pilot_r24/runs/*/*/*/sample1_research/_research_snapshot.json`, with `_pack_facts.json` beside it. Every
  Base `per_share_iv_raw` must equal the saved one exactly. The fixtures are read in place, never copied into the public repo; skip the
  test when they are absent.
- **A 25.1 worked case** on MU's facts with m_N 0.35 and H 10 (spec §7): C1 passes, C2 passes and N_0 is 46.6. With m_N 0.222, C1 fails
  and draws `bridge_C1_reason`.
- **The full suite:** the result must be 3,248 passed plus your new tests, with the same 42 known failures, compared by name against a
  `2b799bd` run.

## Do not build
- the two-pass protocol;
- withholding consensus;
- masking, the memo merge or crux reporting;
- calibrating thresholds;
- any change to the iii or rev22 arms' arithmetic or text.

## Report
- the commits;
- each file touched, with one line on why;
- the test counts;
- anything in the spec you found ambiguous, and how you resolved it, each marked for the coordinator's ruling.
