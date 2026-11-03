# tools/paper_books

The code-only paper books: the A0 forward ledger (`forward_ledger.py`), the GitHub run witness (`m3l_gh_run_witness.py`,
`check_new_runs.py`, `archive_runs.py`) and the 3O paper engine (`m3o_engine.py` with `universe.py`, `baseline_b.py`, `m3o_audit.py`).
Moved on 2026-11-03 from the untracked folder `stocks-workspace/scratch/rev23/` (`m3l_forward/`, `m3l_verifier/`,
`gh_witness_archive/archive_runs.py`, `m3n/baseline_b.py`, `m3o/`). Only paths changed; the arithmetic did not.

## Where things live

| What | Where | Resolved by |
| --- | --- | --- |
| Code and tests | here | the repository root |
| The books (formations, prices, marks, the engine ledger, its inputs maps, universe prices, verifier check records) | `<rs2_state_dir>/paper_books/` (private repo rs2-state) | `paths.py` `rs2_state_dir` |
| Operator exclusions | `<rs2_state_dir>/paper_books/operator_excluded.json` (missing: every script exits) | as above |
| PREREG_m3o.json, PREREG_m3n.json | byte copies in `<rs2_state_dir>/paper_books/prereg/` (they name tickers, so not here) | as above; PREREG_m3n is sha256-pinned in `baseline_b.py`, PREREG_m3o's sha256 is on every engine line and checked by the stop rule |
| GitHub run archive (raw logs, ~76 MB, grows) | `stocks-workspace/data/gh_witness_archive/`, not in git | `paths.py` `gh_witness_dir`, env `RS2_GH_WITNESS_DIR` |
| Screener git objects | the dedicated clone `screener-publish` | `paths.py` `screener_publish_repo` |

The engine's inputs maps (`m3o/inputs/formation_<T>.json`, written by WO_O2) still name their qwen_c packets and run folders by
absolute paths under `stocks-workspace/scratch/rev23/wt-m3o*`. They are data and were copied byte for byte: `run_dir` is part of every
stored qwen line, so rewriting it would stop the engine.

## Running

`run_monthly.py` does the whole month in order and logs to `cache/paper_books.log`; see its docstring. The task `RS2-Paper-Books`
(`register_paper_books_task.ps1`, through `run_paper_books_hidden.vbs`) runs it on days 1, 2 and 3 of each month at 08:00 KST.
It holds `cache/rs2_state.lock` (`state_lock.py`) for the whole run; `sync_state.py` takes the same lock and skips its hourly run
while it is held, because its `reset --hard @{u}` would otherwise drop an unpushed paper-books commit.

Tests: `"C:\Program Files\Python312\python.exe" -m pytest tools/paper_books/tests -q`. `tests/conftest.py` points the scripts at a
throwaway rs2-state with a synthetic exclusion list (OPXA..OPXD) and copies the two PREREG files from the real rs2-state.

## Monthly formation (the AI-book inputs map)

Each month-end formation `<T>` (the last NY session of the month) needs its inputs map `<books>/m3o/inputs/formation_<T>.json` before the
engine can run its qwen arm. It is produced from this repository's code (`qwen_c` runs from the repo root; no worktree). Steps, in order,
from the repo root (`py` = `"C:\Program Files\Python312\python.exe"`):

1. `py tools/paper_books/check_new_runs.py` (the monthly task already does this): archives and verifies the new screener runs.
2. `py tools/paper_books/formation_decide.py <T>`: the decision run by `forward_ledger`'s own rule; writes the map with every book name
   `to_build`. An existing map is never overwritten: the same decision prints `unchanged`, a different one stops (use step 6).
3. `py tools/paper_books/formation_packets.py <T>`: one `qwen_c.packet` per name (online SEC); a refusal sets `analysis_incomplete`. Resumable.
4. `tools\paper_books\register_formation_task.ps1 -Formation <T>` (PowerShell) registers `RS2-Formation-Runner`, which runs
   `formation_run.py <T>` through `formation_run_hidden.vbs` every 15 minutes (GPU; one run per name, resumable, one instance by
   `cache/paper_books/formation/runner.lock`). `finished_<T>.flag` in that folder marks the end; then remove the task with `-Remove`.
   Logs: `runner.out` and `runner.err` there.
4a. With step 4, from the 2026-11-30 formation: `tools\paper_books\register_formation_value_task.ps1 -Formation <T>` registers
   `RS2-Formation-Value`, which runs `formation_value.py <T>` through `formation_value_hidden.vbs` every 15 minutes (F10,
   F_SPEC_valuation_menu sections 7-8). Its first pass pins the MRI anchors as of the decision time into `<books>/m3o/value/anchors_<T>/`
   (the newest build, live or under MRI's `archive/`, built at or before T, sha256s in `manifest.json`); every pass waits until
   `finished_<T>.flag` exists, so no valuation takes a Q1 slot. Then each book name with a packet that is not operator-excluded gets
   `python -m qwen_c.value.run` at seeds 1000 and 3000 (family by `value_family.py`, sector and market cap from `stocks.json` at the
   output commit), indexed in `<books>/m3o/value/formation_<T>.json` (status, reason, result path and sha256, seconds; resumable).
   A crash, an engine_defect, an environment no_call or a code change mid-formation writes `value_STOP_<T>.flag` and the task stays
   idle until a human looks; `value_finished_<T>.flag` marks the end (then `-Remove`). Logs: `value.out`, `value.err`. Tests:
   `tests/test_formation_value.py`.
5. Before the fill open: `py tools/paper_books/formation_freeze.py <T>` copies the map to `formation_<T>.frozen.json` (refuses a second
   freeze), writes the one-line witness to `<books>/m3o/witness/formation_<T>.txt` and prints it. Publishing the witness (a public commit
   and push) is by hand, after a scan.
6. If a later verified run changes the decision before the fill open: `py tools/paper_books/formation_requeue.py <T>` moves the map aside as
   `formation_<T>_superseded_<run_id>.json` and rebuilds it (idempotent; run `check_new_runs.py` first).

The packet CLI reads the output commits through `paths.py` `screener_publish_repo` (the clone the verifier uses); the old scratch scripts
read the same git objects from the `stock-screener` development checkout. Tests: `tests/test_formation.py`.

## ENGINE_SHA256: a recorded version change

`m3o_engine.py` stamps `engine_sha256` (the sha256 of its own file) on every ledger line. The stop rule leaves `engine_version` and
`engine_sha256` out of its comparison (`_norm`), so the stamp records which file wrote a line; it is not checked against the current
file. Moving the engine changed its import lines, so its hash changed:

| | ENGINE_SHA256 | Lines |
| --- | --- | --- |
| scratch `rev23/m3o/m3o_engine.py` (to 2026-11-03) | `c453f6066a7d5e34d39da7766930d288229150f9db5ca5eff29360a1bda228f9` | all 1032 lines stored up to 2026-11-02 |
| `tools/paper_books/m3o_engine.py` (from 2026-11-03) | `0516e8e90f529084026ccaedc5ce04152cec6a80298c1f296cf3b9f6f5cda80b` | lines appended from here on |

This folder is `-text` in `.gitattributes`, so a checkout never converts line endings and the engine's bytes (and hash), the
fixtures and their sha256 receipts are the same on every machine. `ENGINE_VERSION` stays `m3o_engine.v2`. Proof that nothing else changed (2026-11-03): from the new location, on the books as copied
and the stored 2026-11-02 price fetch, the engine recomputed all 1032 stored lines (formations 2, factor 119, qwen 181, verification
180, actions 550) exactly equal apart from `engine_sha256`, and `marks/2026-11-02.json` exactly equal; `forward_ledger.py` recomputed
both stored formations and `mtm_2026-11-02.json` exactly equal (the computation clock aside).

## Removed on the move

`test_monthly_step_is_the_baselineA_function` imported `stocks-workspace/scratch/baselineA/m3_quarterly.py`, a cross-repository
import; it passed in scratch on 2026-11-03 and was dropped. The tests' operator-excluded ticker is now the synthetic `OPXA`, and the
fixtures in `tests/fixtures/` were regenerated with it (only that name, and the price receipt's sha256, changed).
