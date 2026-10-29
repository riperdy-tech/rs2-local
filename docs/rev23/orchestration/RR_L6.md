# RR_L6: Small owner fixes, and the disposition of ChatGPT's unpushed code (2026-10-29)

**Result:** DONE for the 3L-relevant fixes. The rest is held, with reasons.

## Branch

- `stock-screener` branch `review-2026-10/3l-fixes`, worktree `stocks-workspace/scratch/rev23/wt-3l-fixes`.
- Based on `origin/main` `3094fc70`. **Local only, not pushed.**

| Commit | Change | Tests |
|---|---|---|
| `b10079fb` | `mri_sync.py`: one read of each MRI file owns the snapshot bytes, the date and the digest. The commit is ChatGPT's `22317406`, taken unchanged after a line audit. | its 6 tests pass |
| `a8d9e2d4` | `fetch_eps_trajectory.py`, 3 rules: (1) an all-null row is not a cache hit; (2) a failure keeps the previous row; (3) an attempt counts against `--max-calls` before the call. These are the same rules as ChatGPT's `6ea8cb2c`, without its ~150 lines of opt-in audit code. Measured at `3094`: 110 of the 624 rows are all-null, and 56 have been stuck since 2026-05-25. | new `test_eps_failure_cache.py`, 4 tests: 3 failed before the fix, all 4 pass after |
| `e0f8d768` | `tradability.scan` counts days unlisted from the **UTC** date, not the machine's local date. This fixes both callers (tier-1 filter and scorer) at their single owner. Cloud runs are unchanged; PC runs now match them. Found by the PC-run replay (RR_L4 addendum 2). | new test; mutation-checked (it fails with the old line); 707 passed, 3 skipped |
| `df6b4ecb` | **CI, needs operator approval:** `price-refresh.yml` also commits `daily_closes.json` and `momentum_state.json`, the same as `schedule-data-fetch.yml`. This unblocks gate L-P4F. | — |

**Suite:**
- `scripts/test_*.py`: 696 passed, 3 skipped at `3094`. 706 passed, 3 skipped on the branch: the +10 are the 6 MRI
  tests and the 4 EPS tests.
- `rs2-local` was not touched by this branch.

## Not taken (held, unmerged)

| Item | Reason |
|---|---|
| `build_fundamentals_history.py` from ChatGPT's branch | It changes **default output**: an instant field with no candidate near the reference date is nulled (the CMRE case). That is an engine change outside 3L, its effect on the published fundamentals is unmeasured, and it imports an m3l audit tool at module load. It needs its own impact measurement (cells nulled, nominations changed) before any ruling. |
| Opt-in read audits in the scorer, the builders and EPS | Not needed for the 3L gates, because the witness rules of W.4 suffice. Revisit when the plan's "recommended" workflow read audit is approved. |
| About 50 `scripts/m3l_*` investigation tools, several specific to one name | They do not belong in the production `scripts/` folder (non-negotiable 2). Archiving them to `stocks-workspace/scratch` is proposed. |
| `rs2-local` `review-2026-10/m3l-rs2-custody` (7 commits) | Its pack-read tracing belongs to 3M (the Qwen pack replay moved there). SEC custody is **on by default** and fails closed on every SEC fetch. Proposed rework: make it opt-in or non-fatal before any merge. Ruling at 3M. |
| The SEC later-date rule (GSAT/PNRG) | It applies only in the SEC acceptance tooling (`m3l_sec_pit_asof.py`), not in production. The verifier does not need it, because the SEC leg is bounded by the platform. Recorded as policy in PLAN §3L. |
| Price `snapshot_date` taken from file mtime | `price_history` lists carry no dates, so there is no quote date in the file to use. The verifier annotates `undated_series` instead. Fixing it means adding dates to the series, a schema change, which is deferred. |

## Requests to the operator

1. Approve pushing `review-2026-10/3l-fixes` to `stock-screener` `main`. It is four commits, and one of them is a CI
   change.
2. After the push, the next scheduled price refresh is replayed (re-running L4) for gate L-P4F.
