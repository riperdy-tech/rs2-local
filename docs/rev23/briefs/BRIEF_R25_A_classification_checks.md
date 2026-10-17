# Brief A: revision 25 Stage 0.5, the classification checks K1–K4

**Your workspace:**
- **Worktree:** create it with `git -C C:/Users/riper/stocks/rs2-local worktree add -b review-2026-10/rev25-k
  ../stocks-workspace/scratch/rev23/wt-r25-k 4deab98` and work only there.

**Your limits:**
- commit by pathspec;
- never push, merge or deploy; no GPU; never edit `.env*` or config;
- never use a bare `git stash`.

**Read only these:**
- `stocks-workspace/docs/review_2026-09-22/rev23/SPEC_rev25_normalization_bridge.md`: section "v1.2" (your spec), and section 5 and v1.1
  for the check shape;
- `rs2-local/AGENTS.md`.

**Read code by grep and section only.** Your report is at most 50 lines.

**Two parallel builders work on other branches. Avoid their areas:**
- builder B: `analyst_tools.py`'s loop, the pack builder's consensus sections, `contract_fill`'s change log, memo merging;
- builder C: the scratch pilot tooling.

You may touch `capability_test.py` (`TASK_REV25` only), `contract_fill.py` (the classification fill only), `bridge_checks.py`,
`financial_model_tool.py` and `analyst_tools.py` (`_tools_desk25` only). Keep each edit small and local; a coordinator merges.

## Build
1. **The checks.** `bridge_checks.py` gains K1–K4 exactly as spec v1.2.
   - `τ_g = 0.02` goes in `BRIDGE_TOLERANCES` as `tau_g`, commented as a registered prior, frozen.
   - K2 and K3 reuse `tau_m_y1_5`.
   - Pure functions, with the same result shape as C1–C5.
   - `run_checks` gains them, or a sibling `run_class_checks` does; say which.
2. **The desk** (`financial_model_tool.py`, desk schema 25.1 only).
   - `growth_trajectory` and `margin_persistence` join the normalization declarations, with the same inheritance as `cycle_position`.
   - Values are validated against their enums, with refusals by name in the existing pattern.
   - A failing K check draws `class_K<n>_reason` through `_need`. With the reason given, the value computes and the check stays `fail`,
     annotated `reason_given`.
   - The results go in `dcf["bridge"]["class_checks"]`, and the desk markdown prints them under the check table.
3. **The tool schema.** `_tools_desk25` offers `growth_trajectory`, `margin_persistence` and the four `class_K<n>_reason` fields.
4. **The contract.**
   - Under 25.1, `growth_trajectory`, `cycle_position` and `margin_persistence` on the verdict row are filled from the Base's desk
     declarations, the single owner.
   - A differing typed value is ignored and stamped `classification_from_desk_under_25_1`.
   - `class_checks` is added to the verdict-row owners, as `bridge_checks` was.
   - `TASK_REV25` says the three labels go in the desk call; the `*_evidence` fields stay in the contract.
5. **Leave alone:** revision 24 and rev22 arms, unchanged.

## Tests (system Python per AGENTS.md; targeted only, the coordinator runs the full suite after merging)
- **Each K rule:** pass and fail at its boundary (a tie passes, with an EPS allowance as in C1); K3 "not distinguishable"; K1 for MPWR's
  +50% then +45%, which is decelerating.
- **Spec v1.2's MU line:** MU's facts with "mid" fail K2.
- **No write path:** the checks never change a label (the inputs are compared before and after).
- **The arm A replay** in `test_rev25_bridge.py` still passes, as do all 62 bridge tests.

## Report
- commits;
- files, one line each;
- the counts of the targeted tests;
- ambiguities, each marked for a ruling.
