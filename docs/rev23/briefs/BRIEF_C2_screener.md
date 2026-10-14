# Brief C2-screener: the screener reads verdict contract v4 (SPEC_rebuild AK.53)

## Where and how
- **Repository:** `C:\Users\riper\stocks\stock-screener`. Create the worktree
  `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-c2-screener` on a **new branch `review-2026-10/c2-screener`** from
  `origin/main`:

  ```
  git -C C:\Users\riper\stocks\stock-screener fetch origin
  git -C ... worktree add <path> -b review-2026-10/c2-screener origin/main
  ```
- **Work only there.**
  - **NEVER push.** A push to this repository can trigger a Vercel deploy, and deploying is the operator's decision alone.
  - Never touch `screener-publish`, the main checkout or other worktrees.
  - Commit by pathspec with messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:** the repository's own (`npm test` and the type check, plus the Python tests if the Python scripts change). Record the counts
  before and after.
- **Read first:**
  - `C:\Users\riper\stocks\AGENTS.md` and the repository's `AGENTS.md`;
  - the contract: `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\rev23\SPEC_verdict_contract_v4.md`, sections 1–4, 7 and
    10.

## What to build (contract section 10, the screener rows)
1. **`apply_llm_overlay` (SCR-04)** reads v4 overlay rows: `direction`, `actionable`, `size_hint`, `m`, `entry_timing`, as today.
   - New fields are additive.
   - Absent v3 fields (`conviction`, Kelly) are handled as **absent, never zero** (non-negotiable 4).
   - Branch on `scheme == "core_v4"`. v3 rows behave exactly as today.
   - Find the live implementation first; the repository's `AGENTS.md` says which copies are live.
2. **The paper book's `rn_depth` targets (TRK-03):** the predicate is unchanged (undervalued and actionable). Make sure v4 rows flow
   through it, with `size_hint` honoured as today.
3. **TRK-06 grading:** observable grades only, on v4 rows:
   - coverage of `forecast_years` against realised fundamentals;
   - calibration of `prob_fail_12m` against realised distress exits.

   `prob_value_above_price` is NOT graded as a calibration.
4. **The site desk:**
   - shows the quantiles, `prob_value_above_price`, "no view: <reason>" for an abstention, and the flags
     (`value_distribution_model_implied`, `joint_tail_undercoverage`, `distress_model_not_validated`) as plain-language notes;
   - shows consensus marked display-only;
   - drops conviction and moat for v4 rows.

   Keep the changes minimal and in the existing style.
5. **The O8 test:** no module except the site's display reads `consensus_display`.
6. **Contract tests** with v4 fixture rows (the same cases as the rs2 brief, built from the contract's field list) through every consumer
   above. v3 fixtures produce unchanged output.

## Deliverable
The branch with its commits (**not pushed**), and a report file
`C:\Users\riper\stocks\stocks-workspace\scratch\rev23\c2_screener_REPORT.md` holding:
- the changes, file by file;
- the test counts;
- every open question where the contract was silent.

Decide nothing the contract leaves open; list it.
