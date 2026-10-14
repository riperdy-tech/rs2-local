# Brief C2-rs2: `depth_gates` and the fiduciary gate for verdict contract v4 (SPEC_rebuild AK.53)

## Where and how
- **Repository:** `C:\Users\riper\stocks\rs2-local`. Create the worktree
  `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-c2-rs2` on a **new branch `review-2026-10/c2-rs2`** from
  `origin/review-2026-10/gate2-run2`:

  ```
  git -C C:\Users\riper\stocks\rs2-local worktree add <path> -b review-2026-10/c2-rs2 origin/review-2026-10/gate2-run2
  ```
- **Work only in that worktree.**
  - Never touch `C:\Users\riper\stocks\rs2-local`'s own checkout, `wt-gate2-dev` or `wt-gate2-run2`.
  - Never push, merge or deploy.
  - Commit by pathspec (`git commit -- <paths>`) with clear messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest tests tools/audit_202608/tests -q`, plus the module tests you add. Record the
  pass and fail counts before and after. Known pre-existing failures must stay identical; list them.
- **Read first:**
  - `C:\Users\riper\stocks\AGENTS.md` and the repository's `AGENTS.md` (the non-negotiables: annotate, never silently gate; `0.0` is a
    value, so never use `or` to default a number; one owner per field);
  - the contract: `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\rev23\SPEC_verdict_contract_v4.md` (approved, v2, with
    the AK.21 `joint_tail_undercoverage` flag).

## What to build
1. **`depth_gates.assess` gets a v4 branch** for `scheme == "core_v4"` (contract section 8). It returns every applicable reason and never
   mutates or drops a row; `gate_version` is 3.
   - **Reasons:**
     - `not_usable`;
     - the abstention's own code;
     - `integrity_fail`, `unanchored_high`, `implausible_level`, `extraordinary_without_evidence`, `instability`, `stale_inputs`,
       `pre_valid_analyst`, `non_production_row`.
   - **Non-blocking flags:** `distress_model_not_validated`, `value_distribution_model_implied`, `joint_tail_undercoverage`.
   - **SYSTEM is engine v2 alone (AK.52).** A v4 row may carry `muse_used: false`. Reasons that need Muse output (`unanchored_high`,
     `extraordinary_without_evidence`, the citation part of `integrity_fail`) then return **not applicable**, stated in the output (for
     example `not_applicable: ["unanchored_high", ...]`). They must never silently pass or fail.
   - **v1–v3 rows** produce exactly today's output, byte for byte.
2. **`fiduciary_gate` gets a v4 branch** (contract section 9):
   - quantile monotonicity;
   - the non-negative edge (`undervalued` needs `prob_value_above_price > 0.5` and `median_mos >= 0.10`; the mirror for `overvalued`);
   - checkable invalidation (at least one financial and one price/momentum rule);
   - versions complete.

   A failure is `not_usable`.
3. **The overlay writer** (in `orchestrate_depth.py` or wherever the depth overlay rows are built) carries the v4 fields additively. It
   publishes only through `screener-publish`; never change that path.
4. **Contract tests:**
   - **Fixture v4 rows,** built by hand from the contract's field list: one undervalued and actionable; one with each blocking reason;
     an abstention (each of the four codes); an engine-v2-only row (`muse_used: false`); a survival-adjusted row with `prob_fail_12m`
     of at least 0.10 (P10 = 0, so it cannot be undervalued).
   - **The checks:** they pass through `assess`, `fiduciary_gate` and the overlay writer. Property tests: the direction is consistent
     with the band and the MoS floor; `size_hint` is the minimum bucket; an abstention is never actionable.
   - **The single-owner test** of the contract (section 11): every v4 field has exactly one producer.

## Deliverable
The branch with its commits, and a report file
`C:\Users\riper\stocks\stocks-workspace\scratch\rev23\c2_rs2_REPORT.md` holding:
- what changed, file by file;
- the test counts before and after;
- every judgement call you made where the contract was silent.

Do not decide anything the contract leaves open; list it instead.
