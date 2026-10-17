# Brief D: revision 25, the coordinator's rulings on builders A and B

**Your workspace:**
- **Worktree:** `stocks-workspace/scratch/rev23/wt-rev25`, branch `review-2026-10/rev25-bridge`, head `6a718fb`. It merges the bridge
  (0.3–0.4), K1–K4 (0.5) and two-pass plus memo merge (0.6–0.7).

**Your limits:**
- commit by pathspec;
- never push, merge or deploy; no GPU; stub models only;
- never use a bare `git stash`.

**Read only:**
- `rs2-local/AGENTS.md`;
- the code by grep and section.

**Your report** is at most 40 lines. **Tests:** targeted only. The revision-25 test files must stay green: `test_rev25_bridge`,
`test_rev25_class_checks` and `test_rev25_two_pass`, 115 tests now.

## Rulings to implement
1. **The three labels are required under 25.1.**
   - `growth_trajectory`, `cycle_position` and `margin_persistence` are required on the Base, at the top level or in the scenario.
   - A missing one is refused by name (`missing`), in the existing pattern, so a label left out of the desk call can no longer overwrite the
     typed one with None.
   - Bull and Bear still inherit.
2. **The desk call is the labels' single owner under 25.1.**
   - Remove the three label fields from the 25.1 contract template in `TASK_REV25` and from `FORM_FIELDS_25`.
   - Remove any TASK wording that asks the analyst to repeat them.
   - The `*_evidence` fields stay in the contract.
   - Under 25.1, `contract_fill` takes the labels from the desk only.
3. **Arm C's pass 1 must not see consensus through the desk either.**
   - For `r25_c` in pass 1 only, the desk context withholds every consensus-derived member:
     - `levels`: the year-1 and year-2 levels and Bull/Bear year 2, so the bull2/bear2 deviation checks and their advice do not fire;
     - the reference figures (`reference_status` treated as not in force);
     - `long_run` `e5`, `oe5` and `m5`, so C5's X-basis facts drop `m5`;
     - `next_fy_revenue_growth`;
     - `price_implied`'s `year2_level`, reported as not applicable;
     - any refusal or advice text that quotes a consensus number.
   - **Pass 2 uses the full context.**
   - **Test:** a pass-1 `r25_c` desk result and its markdown contain none of the withheld values (grep the numbers), while the same call in
     pass 2, or in `r25_b`, does show them.
   - **Also withheld in pass 1 for `r25_c`:** the DATA 8 PEG line, which uses forward growth estimates.
   - **Kept:** trailing P/E, `reference_base_b` (a filed figure), `terminal_g_basis`, the working-capital text and `consensus_data_status`.
4. **No retry on a two-pass breach.** A `two_pass_breach:no_pass1` sample is not retried with a perturbed seed, because a breach is a result.
   Record it and move on.
5. **The memo merge applies to the r25 arms only.** Arm A must run revision 24 as it ran. Every other arm's memo handling is byte-identical
   to `4deab98`; test that.
6. **README:** add one short paragraph on the two-pass fields, the memo merge and the classification labels, beside the bridge section.

## Accepted, nothing to do
- The pass-1 end rule.
- The one extra pass-2 desk run when pass 1 spends the budget. It is identical across B and C and recorded as a known difference from
  arm A.
- The change-log scope.
- `TWO_PASS_TASK_PARAGRAPH` as written.
- The withheld-element list.
- News and research may quote consensus. That is a known limitation the Stage 1 registration counts.
- Freezing `_withheld_consensus.md` is the runner's job, not yours.

## Report
- commits;
- files;
- test counts;
- the list of withheld desk members, with the source line for each;
- ambiguities.
