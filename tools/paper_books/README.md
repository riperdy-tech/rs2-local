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
