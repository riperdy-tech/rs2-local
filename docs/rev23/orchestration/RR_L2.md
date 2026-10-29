# RR_L2: Code consolidation inventory, 2026-10-29

**Result:** DONE. This is the inventory; the dispositions marked "L6" are audited in WO_L6.

## State of each repository

| Repository | Live checkout | Unpushed work from the 3K–3L period (since 2026-10-20) | Disposition |
|---|---|---|---|
| `screener-publish` | `main` = `origin/main` = `3094fc70` (clean) | none | Nothing to do. `3094` is the owner-approved atomic-pair fix (operator authorized, 10-28). |
| `stock-screener` | PC checkout on `claude/minus-two-percent-issue-w94rfr` @ `3b4e5bc`, stale against `origin/main` `3094fc70`. **Not a live path:** Actions run from GitHub, and publishing runs from `screener-publish`. | **26 commits** on `review-2026-10/m3l-mri-read-once` (worktree `stocks-workspace/scratch/rev23/m3l_source_owner_main_20261028`), on top of `3094`. 71 files, +8,313 lines. | **L6.** Split the branch into two parts, below. |
| `rs2-local` | `review-2026-09/phase-4` @ `e82a08b`. This is the live branch. It was reset on 10-29 (`RR_L2_partial_rs2_live_branch.md`). | **7 commits**, now on `review-2026-10/m3l-rs2-custody` (also on ChatGPT's `review-2026-10/m3l-rs2-refresh-lock` worktree, same tip `f2e8543`). 13 files, +1,353 lines. | **L6.** Same split. |
| `macro-regime-indicator` | — | none | Nothing to do. |
| `stock-screener-v3` | a git worktree of `stock-screener` (not a separate repository), on `fix/funnel-name-search` | covered by the `stock-screener` row | Nothing to do. |

## `stock-screener` 26-commit branch: the split

- **Production files changed (audit in L6):**
  - `score_factors_dual_door.py` (+112): opt-in read audit;
  - `mri_sync.py` (+12): read-once fix;
  - `tradability.py` (+8) and `depth_conviction.py` (+4): optional read callbacks;
  - `fetch_eps_trajectory.py` (+171): failure-cache fix;
  - `build_price_history.py` (+81) and `build_momentum_state.py` (+91): opt-in receipts;
  - `fetch_sec_data.py` (+16);
  - **`build_fundamentals_history.py` (+73): "gate historical fiscal anchors by original SEC report dates". This may
    change default output and needs a byte-level check;**
  - `AGENTS.md` (+14).
- **About 50 `scripts/m3l_*` and `scripts/test_m3l_*` investigation tools.** Several are specific to one name (QUAD,
  MG, NREF, the "remaining inline components"). **Proposed disposition:** do not merge them into the production
  `scripts/` folder. Archive them under `stocks-workspace/scratch/rev23/m3l_tools_archive/` as history. Investigation
  tools specific to a name do not belong in the engine (non-negotiable 2), and they would be noise in the scheduled
  repository.

## `rs2-local` 7 commits

`sec_primary.py` / `sec_guidance.py` (custody on by default), `rs2_data.py` (opt-in tracing), `capability_test.py`,
`common.py`, `consensus_valuation.py` (audit flags), plus the PIT preflight and source-cutoff gate tools and their
tests. Audit in L6. The question that decides it: should SEC custody be **on by default** (disk growth, and a new
fail-closed path on every SEC fetch), or opt-in?

## Older worktrees

There are 27 `stock-screener` and 110 `rs2-local` worktrees. Almost all belong to earlier Claude sessions
(`scratch/rev23/wt-*`, `pilot_r2*`, session scratchpads). They are history, and **no deletion is proposed**
(non-negotiable 9). Pruning them is an operator housekeeping decision, not part of 3L.
