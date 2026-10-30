# AUDIT_P3b1: the 3P executor, without the GPU (2026-10-29)

**Verdict: APPROVED, with two operating rules added to WO_P3b.**
- **Code:** `m3p_monitor.py` gains `run_pass`, `verified_commit`, packet build and run helpers, `fail_entry`, and the
  `run` command.
- **Tests:** 150 passed, rerun by me (119 before, 31 new). The builder broke nine lines one at a time, and each break
  failed a test.
- **Dry run on the real queue:** HOG P1, MA P3, and AMD, KSS and MU at P4, all at verified commit `92592e2156`. Nothing
  was written.

## Checked

- **`verified_commit`:** the newest PASS/PASS row with a GitHub `run_updated_at` ≤ T. A row without that clock is not
  eligible. That is right: only GitHub's clock may place a commit before T.
- **Run key:** predicted before the run from the worktree's prompt and contract versions. A mismatch with the manifest
  is flagged.
- **Ollama down or GPU state unreadable:** the pass stops with no attempt counted (SPEC_m3p §5).

## Operating rules (added to WO_P3b)

1. **Never run the executor while a formation run (WO_O2 or WO_O3) uses the same run root.** After a lost result, the
   executor's crash scan runs with no minimum age. It would take an in-progress formation run for a crash and re-queue
   it. The GPU schedule already runs them in sequence; this makes the rule explicit.
2. **Run `check_new_runs.py` before each executor pass.** Otherwise `verified_commit` stays on the last checked commit
   (`92592e21`, 10-29), and the packets age.

## Open choices (RR_P3b1): all accepted

- T is the latest trigger time of the entry.
- A separate `executor.lock`.
- A pre-run failure gets a synthetic run id.
- `--limit` counts entries taken from the queue.
