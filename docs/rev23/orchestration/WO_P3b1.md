# WO_P3b1: the 3P executor, without the GPU (builder brief, 2026-10-29)

**Goal:** step 1 of WO_P3b. Add the command `python m3p_monitor.py run [--limit N] [--dry-run]` to
`scratch/rev23/m3p/m3p_monitor.py`. It takes queue entries in priority order and, for each:
1. builds its packet;
2. runs qwen_c;
3. resolves the run into the journal.

It is tested with stubs only. No GPU, no Ollama.

**Read first:** `WO_P3b.md`, `SPEC_m3p_monitoring.md` v1 (§4, §5), `AUDIT_P2.md`, `AUDIT_P3a.md`, `m3p_monitor.py`, and
`scratch/rev23/m3o_run/o2_packets.py` (how a verified-regime packet is built through the qwen_c CLI).

**Where:** only `scratch/rev23/m3p/`.

**Do not:**
- run qwen_c for real, call Ollama or touch the GPU;
- use the network in tests;
- register any task;
- edit any git repository, read `.secrets.json` or `.env*`, or delete files;
- use `os.kill(pid, 0)`.

## Behaviour

1. **Packet.**
   - **T** is the trigger's effective time: the packet acceptance rule decides eligibility, so T is the trigger time,
     ISO Z, whole seconds.
   - **The screener commit** is the newest commit that `m3l_verifier/out/check_*.json` rows mark verdict PASS and pair
     PASS with `run_updated_at` ≤ T, together with its check file.
   - **The build:** `python -m qwen_c.packet --ticker X --T T --commit C --verified-record F --screener-repo <stock-screener> --online`,
     with `cwd` set to the run worktree (an argument, default `..\wt-m3o`).
   - **A refusal** journals `failed` with the refusal, and the carry rule applies.
2. **Run key:** computed from the built packet. A key already run absorbs the entry (`absorb`) and does not run.
3. **Run:** `python -m qwen_c.runner <packet> --tasks material_events,thesis_change --seed-base 1000` for P0–P3; all
   tasks for P4.
   - The runner is invoked through an injectable function, so tests stub it.
   - `gpu_busy` stops the pass without counting an attempt.
4. **Resolve:** `resolve(run_dir)` (existing). It checks that the `thesis_change` prior is the newest earlier full run.
   That is `find_prior`'s rule, so read the manifest's `prior_run`.
5. **One instance:** the existing lock.
6. **`--dry-run`** prints what would run (ticker, priority, T, commit, task set) and changes nothing.

## Tests (stubbed packet CLI and runner)

- Priority order.
- The commit chosen at T (newest verified commit at or before T; none gives `failed: no_verified_commit_at_T`).
- A packet refusal.
- Run-key absorb.
- `gpu_busy` stops the pass with no attempt counted.
- An ok run resolves.
- A failed run keeps the last good analysis and marks `pending_review`.
- The two-failure carry rule.
- `--dry-run` writes nothing.
- The P4 task set is all tasks.
- A crash between run and resolve is recovered (the crash scan re-queues, and the run key prevents a second run when
  the first finished).

## Report

`RR_P3b1.md` in the orchestration folder: the files, the test count from one final run, and the open choices.
