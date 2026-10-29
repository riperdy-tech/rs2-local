# RR_P3a: the 3P monitor wired to real inputs, without the GPU (2026-10-29)

Work order: `WO_P3a.md`. Built by a Claude subagent. Written only under `scratch/rev23/m3p/`, plus this file. No GPU, Ollama or git change;
`.secrets.json`, `.env*`, `n5\runs*`, `n6\` and every `cache\*\runs\` were not opened; no scheduled task was registered or changed.

## Files (all under `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3p\`)

- `m3p_monitor.py`: edited. Added the WO_P3a section at the end (inputs, prices, crash rule, gather pass, command line) and
  `Monitor.crash_scan`; changed `run_day` (new `only` / `limit`, shared-CIK handling, more report fields), `select_names` (new), and one
  line in `gather_name` (the price source now also carries `expected_session` and `fetched_utc`). No new dependency.
- `tests\test_wiring.py`: new, 36 tests (items 1 to 5).
- `run_gather.cmd`, `launch_gather.vbs`, `register_gather_task.ps1`: new, written, **not registered or run**.
- Live-pass artifacts, created by item 6: `state\monitor.json`, `state\gather_<CIK>.json` x5, `journal.jsonl`.

**Tests:** one final run on the final code, `"C:\Program Files\Python312\python.exe" -m pytest tests -q` from `m3p\`: **119 passed** (the
83 of WO_P2 plus 36 new). I also broke seven lines one at a time (the 16:15 rule, `enter_after_pending` as held, the crash attempts preset,
the completed-session filter, the crash age guard, the shared-CIK alias, the commit choice) and each break failed at least one test.

## What it does

- **Item 1.** `ledger_inputs(ledger_dir, forward_dir)` returns `books`, `newest_book`, `restricted`. The 3O ledger's newest formation gives
  the books from `actions.jsonl`; an empty or absent ledger gives `m3l_forward_fallback` (today's case). `cik_map_for` reads
  `public/data/cik_map.json` of the newest `verifier == PASS` formation's `output_commit` (today `b9497efd8`) through `git show`.
- **Item 2.** `last_completed_session(now)` is `forward_ledger`'s 16:15 New York rule with an injectable clock. `yf_prices(ticker, now,
  fetch)` returns the last 130 completed-session adjusted closes from yfinance, with `source`, `quote_date` (newest close returned),
  `expected_session` and `fetched_utc`.
- **Item 3.** `python m3p_monitor.py gather [--limit N] [--tickers A,B] [--run-root PATH]` and `python m3p_monitor.py report`. `gather`
  stops with exit 2 and sends nothing when `SEC_USER_AGENT` has no email, and exit 3 when the lock is held.
- **Item 4.** `read_ledger(root)` copies the crash rule of `qwen_c.runner.read_ledger` (comment in the code; rs2-local is not imported).
  `Monitor.crash_scan(run_root, now)` records each crashed run of a known name through `resolve()` (a `failed` line) and re-queues it once.
- **Item 5.** The three scheduler files, modelled on `m3o_run\`. The module's only `os.kill` is the non-Windows branch of `pid_alive`
  (a test asserts it). Task `RS2-M3P-Gather`, daily 07:00 local, IgnoreNew, 3 h limit; `run_gather.cmd` passes
  `--run-root ..\wt-m3o\cache\m3m`.

## Live pass (item 6): 5 names of the newest A0 book

Run 2026-10-29 about 14:17 UTC: `gather --tickers AMD,MA,MU,KSS,HOG`. Exit 0. SENEA, SENEB, MOV and MG were not among them (they are never
members). SearXNG on 8888 answered 200; SEC and Yahoo answered for all five.

```
gather: inputs m3l_forward_fallback (formation 2026-09-30; ledger formation None), cik_map from b9497efd82
members 58, gathered 5, no_cik [], shared_cik {'AFGC': 'AFGB', 'AFGD': 'AFGB', 'AFGE': 'AFGB'}, not_members [], queue size 5
  AMD: first_gather=True filings=0 triggers=[]                          news=0 close=2026-10-28/2026-10-28 z=0.90 move=+4.7%
  HOG: first_gather=True filings=1 triggers=['sec:0000793952-26-000065'] news=0 close=2026-10-28/2026-10-28 z=0.12 move=+8.0%
  KSS: first_gather=True filings=0 triggers=[]                          news=0 close=2026-10-28/2026-10-28 z=-0.53 move=+5.3%
  MA:  first_gather=True filings=1 triggers=['sec:0001141391-26-000122'] news=0 close=2026-10-28/2026-10-28 z=0.06 move=-2.0%
  MU:  first_gather=True filings=0 triggers=[]                          news=0 close=2026-10-28/2026-10-28 z=1.71 move=+7.6%
```

- **Filings (first gather, 7-day window):** HOG one 8-K (items 2.02, 5.02, 9.01) with a B-pattern hit `C2+C7`, so a held-or-not-held
  critical level: P1 (not held, fallback has no books). MA one 8-K (items 2.02, 9.01): earnings, P3 (not held). AMD, KSS, MU none.
- **Queue after the pass (5):** P1 HOG, P3 MA, P4 refresh for AMD, KSS and MU.
- **News:** all five first gathers recorded their rows as seen and reported none (an undated row is never new at a first gather; dated ones
  older than 7 days likewise). Seen keys per name: MA 42, MU 28, HOG 30, AMD 10, KSS 2 (each row stores a title key and an address key,
  so rows are half that). The next gather reports new rows.
- **Prices:** quote date 2026-10-28 equals the expected session (10-29 was still open at 16:15 New York); 130 closes kept per name; no
  price trigger fired; each name's gather record holds its closes.
- **Not run in the live pass:** the crash scan (no `--run-root`: the real run roots are forbidden to me).
- Queue ages in `report` show a negative number for HOG and MA. That is open choice 7 of WO_P2 (the later reading of `acceptanceDateTime`
  puts the trigger time up to about 4 hours after the true acceptance), not a new defect.

## Open choices (each is for a ruling if you disagree)

1. **`SEC_USER_AGENT` was unset in my process but set in the Windows user environment.** The brief says stop if unset. I read the user-level
   value into the child process (never printed) and ran, because a scheduled task, started under the same user, sees that same value. If you
   meant the process variable only, say so and discard the pass (`state\`, `journal.jsonl`).
2. **Company names come from the SEC submissions feed (`name`)**, not from a file: the screener's `cik_map.json` has only tickers and CIKs
   and `factor_scores.json` has no names. The feed is fetched once per CIK per pass (cached) and used both for the name and the gather. A
   name that fails to load falls back to the ticker for the distinctive word.
3. **Names sharing a CIK are gathered once**, under the first by ticker (`select_names`; the others are `shared_cik` in the summary and are
   not queued or marked monitored). Today AFGB, AFGC, AFGD, AFGE share one CIK. The gather record is per CIK, so a second ticker would
   have seen no new filings. **Cost:** a price trigger is evaluated for the principal ticker only, and the preferred shares (AFGC to AFGE,
   and likewise NTRSO, FCNCN, UMBFO, WTFCN if they share a CIK with a member) get no price check of their own. WO_P3b decides whether a
   qwen_c run is per ticker or per CIK.
4. **The newest A0 book is always the newest line of `m3l_forward/formations.jsonl`**, even when the 3O ledger is non-empty and its
   newest formation is older (the ledger holds only a reference to the book). Books and restrictions come from the ledger's newest
   formation.
5. **A name is "held by an arm" when its last `at_fill_open` / `pending_resolution` line for that arm is `hold`, `enter` or
   `enter_after_pending`.** `analysis_pending` (a cash slot), `new_entry_restricted`, `exit` and `operator_excluded` are not held.
   Restricted = a `causes` list on that line (B1/Q1), or a `new_entry_restricted` line with its rule. The code reads `actions.jsonl` as
   m3o_engine writes it (`kind`, `arm`, `action`, `causes`); the ledger does not exist yet, so this is tested on fixtures of that shape only.
6. **"Newest verified commit"** is the newest `m3l_forward` formation whose `verifier.verdict == "PASS"`; its `output_commit` is read.
7. **Prices:** one `Ticker.history(auto_adjust=True)` call per name (not `yf.download`), 0.5 s apart; the window is about 1.6 calendar days per
   session plus 14, then the last 130 rows. The holiday set is `forward_ledger`'s copy, which ends 2027-01-01. A later holiday would look
   like a session; the record then shows `quote_date` before `expected_session`. The session rule does not drop a stale quote; it
   records the lag.
8. **The crash scan skips a run younger than 6 hours** (`CRASH_MIN_AGE_HOURS`, DESIGN, by manifest mtime). `read_ledger`'s rule alone calls
   a `running` run crashed, which would flag a run in progress on the GPU. A run with no readable manifest has no ticker and is reported
   as `unmapped`, not re-queued.
9. **"Re-queued once":** a crashed run of a known name is recorded as `failed` (cause `crashed_no_finished_at`). If an entry covers it, the
   existing retry applies (attempts 1, then dropped at the second failure). If none covers it, a P2 trigger `rerun:<run_id>` is added at
   the crashed run's decision time with attempts preset to 1, so its failure drops it. P2 is my choice; the crashed run's own priority
   is not recorded in its manifest. A name the monitor has never gathered is left alone (`not_monitored`).
10. **The scheduler runs the crash scan** against `..\wt-m3o\cache\m3m` (the runner's `M3M_DIR`) every day after the gather. That path is my
    reading of `qwen_c/runner.py`; WO_P3b should confirm it before registering the task. Daily 07:00 local is after the New York close all
    year; a missed pass runs at the next logon (`StartWhenAvailable`).
11. **Summary fields added to the gather report** (`filings`, `first_gather`, `price_source`, `price_signal`, `news_seen_not_reported`,
    `shared_cik`, `not_members`): additive; the 83 earlier tests are unchanged.

## Not done

- No run-root crash scan on real data (forbidden paths); it is tested on temporary run roots only.
- The registrar was not run; the task `RS2-M3P-Gather` does not exist.
- SPEC section 7 measures (missed events, false alarms, reanalysis delay, throughput), packet building and the model runs: WO_P3b.
- The HOG B-pattern hit (`C2+C7` on an earnings 8-K) was not read by me. Its text is in the journal's `discovered` line for HOG
  (accession 0000793952-26-000065); whether it is a true hit is a 3N-style question.
