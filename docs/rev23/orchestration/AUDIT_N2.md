# AUDIT_N2: qwen_c v3 (2026-10-29)

Claude read the whole diff `bac4cf8..0afe377` (branch `review-2026-10/m3n`, 3 commits, 10 files) and reran the suite: **362 passed**.

**Verdict: APPROVED for N5**, with the conditions below.

## What was checked

**`tasks.py` and `contract.py`:**
- `material_events` is appended last, so the seed indexes of the existing tasks are unchanged.
- The prompt text matches WO_N2. The rendered reply shape lists the three fields.
- The v1 and v2 pins are unchanged, and a test asserts it.
- In the contract:
  - `EVENT_TYPES` has 12 entries and `EVENT_STATUSES` has 2;
  - shape errors work like `risk_type`;
  - an empty reply is still malformed;
  - no claims with one unknowns line is ok;
  - `CONTRACT` is `m3m.analysis.v2`;
  - no citation, quote or figure check changed.

**`packet.py`:**
- Item 1.02 is added, and the builder is v4.
- The archival regime refuses:
  - a verified record;
  - a commit after T;
  - a missing `stocks.json`;
  - a cik conflict.
- It records `regime`, `screener_commit_verified: false`, `commit_time_utc`, `verified_row: null` and `cik_source`.
- The verified regime refuses a `cik` argument and is otherwise unchanged.
- Under the archival regime, the factor blob and `cik_map` are pinned when present and null when absent. That is right: S0 reads only `stocks.json`, and the factor profile was audit-only.

**`replay.py`:** the regime is read from the packet; an archival CIK given as an argument is passed again.

**`runner.py`:**
- `--tasks` runs in `TASKS` order, and each task keeps its full-run seed.
- `--seed-base` is recorded as `options.seed_base`.
- `tasks_requested` is in both the manifest and `analysis.json`.
- A run with only `thesis_change` and no prior is `failed`, not complete.

## Conditions and findings

1. **The frame rule is the caller's job.**
   - **The gap:** the packet checks only that the commit is at or before T and has `stocks.json`. It does not check that the commit is the *last* commit touching `stocks.json` at or before T.
   - **The condition:** the N5 driver must assert `commit == frame_at(T)` from `m3n/frame.py`, computed on a **pinned ref** (`origin/main` of stock-screener, recorded by its sha), not on the checkout's HEAD. That checkout may sit on another session's branch.
2. **Replay rebuilds with the current builder only.**
   - On this branch the 3M packets (builder v3) report not identical. Their M-P4 evidence stays at `bac4cf8`.
   - **The rule from now on:** replay a packet with the code at its own `builder_code` commit.
3. **`find_prior` can pick a subset run as the prior.**
   - In production, a run that did not include `growth_thesis` and `risks` would make the next full run's `thesis_change` `prior_unusable`.
   - **Why it is harmless now:** the 3N runs use their own cache (`wt-m3n/cache/m3n`), apart from any production ledger.
   - **The fix, before qwen_c runs in production:** `find_prior` must skip ledger rows whose `tasks_requested` lacks both of those tasks.
4. **`T_before_filings_recent`** (the builder's own finding).
   - A large filer whose `filings.recent` (the last 1,000 filings) does not reach back to T is refused.
   - It is reported as a refusal and is never silently dropped. If it hits drawn events in N5, reading `filings.files` is the systemic fix.
5. **Going-concern text in the notes or the audit report is outside the packet** (the builder's own finding). This is expected, and the C2 `not_in_packet` count will measure it (SPEC §6.1, system recall against model recall).
