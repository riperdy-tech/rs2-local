# RR_L2 (partial): unaudited commits moved off the live rs2-local branch, 2026-10-29

**Result:** DONE for this item. The rest of the WO-L2 inventory is still open.

## Finding

The main `rs2-local` checkout runs from `review-2026-09/phase-4`, and the scheduled tasks run from it. ChatGPT made 7
commits directly on that branch on 2026-10-28, between 12:00 and 13:44 KST: `91cf48e`, `53b5aab`, `9ad6f6c`,
`270bf98`, `b38ac9b`, `5e3585e` and `f2e8543`. They were never pushed or audited.

Not all of the changes are opt-in:

- `sec_primary._http_get` now writes every SEC response to `cache/sec_primary/original_custody/`.
- It raises an error when a response is not HTTP 200, when a response is larger than 25 MB, or when that write fails.

`sec_guidance.py` and `rs2_data.py` also changed. `depth_triggers.py` imports `sec_guidance`, and RS2-B2-Gather-P6 was
due at 06:00 KST on 10-29.

## Action (operator: "fix", 2026-10-29)

- `git branch review-2026-10/m3l-rs2-custody f2e8543` keeps all 7 commits.
- `git reset --keep e82a08b` returns the live branch to its 10-06 state, the code that ran until 10-28 midday. There were
  no tracked local changes, and untracked files are untouched.
- The custody files already written under `cache/sec_primary/original_custody/` are left in place.

## Verification

- `import sec_primary, sec_guidance, depth_triggers` succeeds.
- The suite (`tests tools/audit_202608/tests`, system Python 3.12) gave 712 passed and 1 error in its first pass. The
  error was in `test_llm_provider_server_identity`, and that file passes 49/49 when rerun alone, so the failure is
  flaky. A full rerun is in progress, with its result to follow in `AUDIT_L2`.

## Disposition

The 7 commits are now an unaudited branch. They are audited as part of WO-L6. Only code that passes that audit is
merged, and only through a branch, never by committing to the live tree.

## Suite follow-up (2026-10-29)

- The full suite at `e82a08b` gives 2,948 passed and 42 failed. One of the 42 (`test_pack_rev15.py::test_discovery_slices_byte_identical_to_revision_14`) passes in a clean worktree, so it depends on untracked local files.
- In two clean worktrees, `e82a08b` and `f2e8543` fail the **same 41 tests**, so the failures predate the reset and
  are not caused by ChatGPT's commits.
- **Cause:** the tests read the live enrichment and closure caches, which are stale while `DEPTH_PAUSED` is on. The
  reference and cost-of-equity lines report `not_available`.
- They should be moved to fixtures in 3M.
