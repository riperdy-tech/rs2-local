# WO_P3a: wire the 3P monitor to real inputs, without the GPU (builder brief, 2026-10-29)

**Goal:** make `scratch/rev23/m3p/m3p_monitor.py` runnable for real, one gather pass at a time, and carry out the items
AUDIT_P2 carried. The GPU part (the model runs and the throughput benchmark) is WO_P3b, done later by Claude.

**Read first:** `SPEC_m3p_monitoring.md`, `RR_P2.md`, `AUDIT_P2.md`, `SPEC_m3o_integration.md` §6, `AUDIT_O1.md`, and
`m3p_monitor.py` itself.

**Where:** only `scratch/rev23/m3p/`. `m3o_engine.py` is read-only, and the monitor already imports it for Q1.

**Do not:**
- touch the GPU or Ollama;
- edit any git repository, read `.secrets.json` or `.env*`, or delete files;
- register or change any scheduled task. You may write the `.ps1` / `.vbs` / `.cmd` files, but not run the registrar.
- open `m3n\n5\runs*`, `m3n\n6\` or any `cache\*\runs\`.

**Network allowed:**
- SEC: standing approval. Use `sec_ua()` semantics: the contact comes from the `SEC_USER_AGENT` environment variable,
  and if it is unset you stop and report.
- The local SearXNG on port 8888, paced as in B2: 26 names per batch, 600 s apart.
- Yahoo through yfinance, for closes only.

## Items

1. **The monitored set from files.** `members()` gets its inputs from the 3O ledger (`m3o/ledger/actions.jsonl`: names
   each series holds after the newest formation; `formations.jsonl`), falling back to `m3l_forward/formations.jsonl` for
   the newest A0 book when the 3O ledger is empty. Today it is empty, so the fallback is what runs. CIKs come from the
   newest verified screener commit's `cik_map.json`, through `git show`, read-only.
2. **A price source.**
   - `prices(ticker)` uses yfinance daily adjusted closes over the last 130 sessions.
   - Only completed sessions count: after 16:15 New York, the rule `forward_ledger.last_completed_session` uses.
   - It records the source and quote dates.
3. **A command line:** `python m3p_monitor.py gather [--limit N] [--tickers A,B]` runs one gather pass. It writes state
   and journal and updates the queue, and prints a summary. `python m3p_monitor.py report` prints coverage and queue age.
4. **The crash scan:** a qwen_c run directory without a finished manifest (as `qwen_c.runner.read_ledger` reports
   `crashed`) is re-queued once.
   - Read the run root through a path argument.
   - Do not import from rs2-local. Reimplement the minimum, and note the copy in a comment.
5. **The scheduler files** (written, not registered): `run_gather.cmd`, `launch_gather.vbs`, `register_gather_task.ps1`,
   modelled on `scratch/rev23/m3o_run/`. Use `pid_alive`, never `os.kill(pid, 0)`.
6. **One live pass on 5 names** of the newest A0 book (not SENEA, SENEB, MOV or MG), once the tests pass. Paste the
   summary in the report. Expect a first gather to report only the last 7 days of filings (FIRST_GATHER_DAYS).

## Tests

The existing 83 must still pass, plus tests for items 1, 2 (completed-session rule, with an injected clock), 3 (with
injected sources) and 4. Network stays blocked in tests.

## Report

`RR_P3a.md` in the orchestration folder: the files, the test count from one final run, the live-pass summary, and every
open choice.
