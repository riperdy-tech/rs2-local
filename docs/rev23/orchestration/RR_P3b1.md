# RR_P3b1: the 3P executor without the GPU (builder report, 2026-10-29)

**Result:** `python m3p_monitor.py run [--limit N] [--dry-run]` is written and tested with stubs only. One final run of
`python -m pytest -q tests` in `scratch/rev23/m3p`: **150 passed** (the 119 existing tests plus 31 new).

## Files (all under `scratch/rev23/m3p/`, plus this report)

- `m3p_monitor.py`: new executor section (`verified_commit`, `qwen_versions`, `qwen_build_packet`, `qwen_run`, `task_set`, `entry_T`,
  `unresolved_finished_run`, `run_pass`, `format_run`), one new method `Monitor.fail_entry`, the `run` subcommand in `main`, and one
  line in the module docstring. Nothing existing was changed.
- `tests/test_executor.py`: the 31 new tests.
- `tests/helpers.py`: `make_run` gained an optional `packet_sha` argument (default behaviour unchanged).

## Behaviour as built

Per entry, in order (priority, then trigger time; each entry at most once per pass):

1. T is the entry's `packet_T`, ISO Z, whole seconds. The newest `check_*.json` row with verdict PASS, pair PASS and
   `run_updated_at` <= T gives the commit and its check file. None gives `failed: no_verified_commit_at_T`.
2. The packet is built by `python -m qwen_c.packet --ticker X --T T --commit C --verified-record F --screener-repo <repo> --online`
   with `cwd` set to the worktree (`--worktree`, default `..\wt-m3o`). A refusal journals `failed` (cause `packet_refused`, the
   refusal text in `detail`).
3. The run key is built from the packet: (CIK, packet sha256, prompt, contract, builder). A key already run absorbs the entry.
4. A finished run with that same key that was never resolved is resolved instead of run again (a crash between run and resolve).
5. Otherwise `python -m qwen_c.runner <packet> --tasks material_events,thesis_change --seed-base 1000` (P0-P3), or the same without
   `--tasks` (P4, all tasks). The runner and the packet builder are injectable functions.
6. `resolve(run_dir)` (existing) reads the run. The `thesis_change` prior is whatever `find_prior` chose, read from the manifest's
   `prior_run`; the executor reports that run id in the pass row and does not recompute it.
7. `gpu_busy` stops the pass with no attempt counted and no journal line (nothing is dropped).

`--dry-run` takes no lock, runs no crash scan, builds and runs nothing, and writes nothing. I checked it against the real queue: it
listed the 5 live entries (HOG P1, MA P3, AMD/KSS/MU P4, all at commit `92592e2156`) and no file changed.

Mutation check: I broke nine lines one at a time (infra refusals, the `<=` at T, the absorb test, the recovery of an unresolved
run, T from the wrong field, the P4 task set, the crash scan, the lock, the once-per-pass rule). Each break failed at least one test.

## Open choices (please rule)

1. **T is `packet_T`, not `trigger_time`.** An entry's `packet_T` is the latest of its triggers' times; for a one-trigger entry it
   is that trigger's time. One run at that T covers all the entry's triggers (`resolve` retires triggers with time <= T). With
   `trigger_time` (the earliest top-priority trigger) a later P3 trigger in a P0 entry would be left for a second run.
2. **A check row without `run_updated_at` is not eligible.** Only the newest check file has the field, so a T before
   2026-10-29T01:13Z has no commit today. "Newest" means the latest `run_updated_at`, ties to the later check file name.
3. **The executor has its own lock, `state/executor.lock`** (same `take_lock` and `pid_alive`), not `monitor.lock`. A pass can last
   hours; holding `monitor.lock` that long would make the gather task fail with exit 3. `Monitor` still takes `monitor.lock` for each
   state change, so a gather and an executor can interleave safely. Easy to switch if you want the single lock.
4. **Infrastructure refusals are three, not one:** `gpu_busy`, `gpu_state_unreadable` and `model_show_failed` (the last two are
   Ollama down or unreadable; SPEC 5 says the queue waits). Any other runner refusal is a failed attempt (cause `runner_refused`).
5. **A runner that leaves no result (killed, traceback)** stops the pass and records nothing. The next pass starts with
   `crash_scan(run_root, now, min_age_hours=0)`. Under the executor lock no run of ours is in progress, so a `running` run without
   `finished_at` is dead. With the gather's 6-hour guard a retry could succeed first and the old crash would then mark a name with a
   fresh good analysis `pending_review`. **Consequence: nobody may start a qwen_c run by hand while the executor runs** (a benchmark
   must go through it or wait).
6. **The run key is predicted before the run.** Prompt and contract are read from the worktree's source text
   (`qwen_c/tasks.py` `PROMPT_VERSION`, `qwen_c/contract.py` `CONTRACT`; no import), the builder from the packet file. `resolve`
   still registers the manifest's own key; if the two differ the pass row carries `run_key_mismatch`. Read on the real worktree:
   `m3m.prompt.v3`, `m3m.analysis.v2`.
7. **A pre-run failure is the same `failed` step** via the new `Monitor.fail_entry`, with a synthetic run id
   `norun:<ticker>:<T>:<attempt>`. It does not set `last_run_at` (no run happened), so a P4 name that keeps being refused is
   re-triggered by the next refresh day, not hidden for 14 days.
8. **`--limit N` counts entries taken from the queue, of any outcome** (an absorbed or refused entry uses one). A failed entry is
   retried in the next pass, never twice in one.
9. **Exit codes of `run`:** 0 done, 2 versions unreadable, 3 another executor holds the lock, 4 pass stopped (infrastructure refusal or
   runner crash).
10. **`resolve` raising `ResolveRefused`** (sha mismatch) is noted in the pass row; the failed line is already written, and the pass
    goes on.
11. **The interpreter** is the fixed `C:\Program Files\Python312\python.exe` (as `o2_packets.py`), falling back to `sys.executable`.

## Not done

- No real packet build, qwen_c run, Ollama call or GPU use; no task registered (WO_P3b steps 2-4 are next).
- No independent re-check that the manifest's `prior_run` is the newest earlier full run (the WO says to read it, so I did).
- Formation runs (all tasks) are not queued by anything here; only P4 gets the full task set.

## Process notes

- Twice I wrote a file with a small Python script instead of the Write/Edit tools (the `main` edit in `m3p_monitor.py`, and two
  assertions in `tests/test_executor.py`). The content is in the files and the tests pass; this is a rule slip, not a state change.
- I ran `git status` once, read-only, to see whether the folder was a repository. No git state was changed.
- The only mutation-test copy of the module was restored byte for byte from a backup in the scratchpad; the final run above is on the
  restored file.
