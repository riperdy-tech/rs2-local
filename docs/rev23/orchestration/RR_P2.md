# RR_P2: the 3P monitor without the GPU (2026-10-29)

Work order: `WO_P2.md`. Built by a Claude subagent. Only `scratch/rev23/m3p/` was written, plus this file. No network, GPU, Ollama or git
change; `.secrets.json`, `.env*`, `n5\runs*`, `n6\` and `cache\*\runs\` were not opened.

## Files

All under `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3p\`:

- `m3p_monitor.py`: the module (about 1,300 lines, no new dependency).
- `tests\conftest.py` (blocks `urlopen` and sockets in every test, clears `SEC_USER_AGENT`), `tests\helpers.py`,
  `tests\test_gather_triggers.py`, `tests\test_queue_journal.py`, `tests\test_resolve.py`.
- `fixtures\`: `submissions_acme.json`, `news_acme.json`, and four filing texts.
- State and journal are created on first use: `state\monitor.json`, `state\gather_<CIK>.json`, `state\monitor.lock`, `journal.jsonl`.

**Tests:** one final run on the final code, `"C:\Program Files\Python312\python.exe" -m pytest tests -q` from `m3p\`: **83 passed**.
I also broke six lines of the module one at a time (event-id dedupe, tail boundary, sigma boundary, carry rule, analysis sha check,
outbox flush) and each break made a test fail, then restored the module and reran.

## What it does

- `members(books, newest_book, restricted, today, last_seen)` returns `(members, last_seen)`: reasons per name, `held`, `tail`.
- `gather_name(info, gstate, sources, now)` is pure and returns `(result, new_gstate)`. Sources are injected (`Sources`).
  `build_triggers` turns the result into P0-P3 triggers.
- `Monitor(root)`:
  - `run_day` runs members, gather, triggers, queue, journal, gather record, the 14-day refresh and the stale flags, with B2's
    pacing (26 names, 600 s, `sleep` injected).
  - `enqueue`, `absorb`, `ordered`, `next_entry`, `already_ran`, `recover`, `update_stale` and `report` are the rest of the surface.
- `resolve(run_dir)` (module function, or `Monitor.resolve`) reads a qwen_c run, checks the shas, writes `analysed` then `resolved` or
  `failed`, sets the name state, the thesis-point states, the Q1 verdict, and `pending_review` / `stale_analysis`.
- Online functions, never run here: `sec_headers` (the only reader of `SEC_USER_AGENT`, at call time, refuses without a name and email),
  `online_submissions`, `online_filing_text` (copies `filing_texts`), `searx_news` (copies `followup_news`, five queries), `load_ticker_map`
  (SEC `company_tickers.json`), `newest_book_from_formations`.
- Crash safety (design in the module docstring): one atomic write of `monitor.json` carries the journal lines in an `outbox`; the journal
  skips an `event_id` it already holds; a gather record is written only after its triggers are queued. The test kills a writer with
  `os._exit` before the journal write and in the middle of it, then recovers and retries: one entry, each line once. A second test kills the
  `run_day` between the queue write and the gather record.

## Choices the brief left open (each one is for a ruling if you disagree)

1. **`members` takes plain data**, not file paths: `books` is `{arm: [tickers]}`, `restricted` is `{ticker: rule}` or a list. SPEC_m3o §6's
   ledger files are not parsed, because `m3o_engine.py` was still being written by another builder. Wiring them is WO_P3. Only
   `formations.jsonl` (stable) has a reader. A name's 30-day tail is kept in `state.last_seen`; the 30th day after is still in, the 31st out.
2. **Held vs not held.** A held name takes its level (P0, P2, P3). A monitored name not held takes P1 for a critical level and **P3 for an
   earnings or periodic filing** (the spec gives P1 only the P0 triggers). Restricted-only and tail names count as not held.
3. **Which filings.** Every other 8-K (not only the six listed items) is P3; a 10-K/10-Q amendment is P3; 6-K has no items, so P3; 8-K/A uses
   the item rules; any form starting `NT ` counts as an NT notice. **20-F and 40-F are read as a 10-K** (P2), which the spec does not list.
4. **News queues nothing in v1.** It is gathered, deduped, labelled `secondary`, and journaled as one `discovered` line per name per gather
   (`secondary: true`, `queues_nothing: true`, at most 50 items). The spec says news "may queue" but gives it no priority, and about 50
   rows a name a day would starve the GPU at any priority. A one-line change gives it P3 or P4 if you rule so.
5. **News dedupe is OR**: a row is a repeat if its normalised title **or** its normalised URL was seen (stricter than P6.6's title only).
   Seen keys are pruned at 45 days. A row without the issuer's distinctive word is dropped and counted (`news_dropped_no_issuer_word`).
6. **First gather.** Filings accepted before `now - 7 days` (or `first_since`) are recorded as seen and not reported. After that a filing is
   new if its accession is not in the seen set, whatever its date. Undated news at a first gather is seen, not new; so is dated news before
   the window.
7. **Acceptance time** uses the packet.py / m3o_engine rule (the later of the Z-labelled reading and the Eastern wall-clock reading). A
   filing accepted 20:00Z therefore has trigger time 00:00Z the next day, so a packet at that time always includes it. The cost is up to
   about 4 hours on ordering and `packet_T`.
8. **Price trigger.** The latest session's log return against 3 sample standard deviations of the 60 daily log returns **before** it
   (needs 62 closes); or `|close - close[5 sessions back]| >= 20%`. `>=` at both boundaries (compared after rounding to 12 decimals).
   A zero standard deviation counts any nonzero move. A non-positive close in the window means sigma is not computable (said in
   `notes`); the 5-session test still runs, and a 0.0 close is a value (a fall to 0.0 is a -100% move). It fires once: a second fire within
   5 sessions is suppressed and recorded. Trigger time is the quote date at 21:00Z. Always P3, held or not. The docstring says the values
   are design values.
9. **Cross-issuer guard on filings:** the feed's `cik` must equal the requested CIK, else nothing is ingested. A filing whose text head
   (3,000 characters) lacks the issuer's distinctive word is annotated `issuer_not_named_in_filing_head`, or `names_other_issuer:<tickers>`
   when it names another monitored issuer. It still triggers. A failed text fetch is annotated `text_unavailable_b_patterns_not_evaluated`
   and the filing is still seen (no retry).
10. **Queue entry.** One per name: `priority` = lowest number among its triggers; `trigger_time` = earliest trigger **at that priority**;
    `packet_T` = latest trigger time (WO_P3 should build the packet at this time). A trigger already handled (resolved, or dropped after
    its second failure) is never re-added.
11. **Run key.** Known only after a packet exists, so `enqueue(..., run_key_=)` refuses a key that already ran, and `absorb(ticker, key)`
    removes an entry whose packet gives such a key (one `queued` line, `outcome: absorbed_run_key`). **Only a usable (complete, verified) run
    registers its key**; a failed run does not, so its one retry is not blocked.
12. **Failed runs.** Not `complete`, or no `finished_at` (a crash): `failed` line, last good analysis kept, `pending_review`, one more
    attempt (the entry stays, `queued` line `requeued_after_failed_run`), dropped at the second failure (the evidence stays in the
    journal). `analysis_incomplete` counts as unusable (unlike SPEC_m3o's `partial_analysis`).
13. **Refusal.** A sha mismatch (analysis.json against `analysis_sha256`, or packet.json against `packet.file_sha256`) writes a `failed`
    line (`refused: true`), counts as one unusable run, then raises `ResolveRefused`. An unreadable manifest raises with nothing recorded.
    Resolving the same run twice writes nothing.
14. **Name state** (from the last good run only): `event_found` if Q1 acts; else `thesis_changed` if any point is `changed`; else
    `thesis_intact` if at least one point is `unchanged`, or thesis_change is `not_applicable_no_prior`. If every point is `unknown` or
    `unsupported`, the old state stands and the name is `pending_review` (`thesis_unresolved`). A run without thesis_change leaves the thesis
    state alone. A point addressed only by claims whose `support` is not `supported` is `unsupported`; a point no claim addresses is
    `unknown`; with several supported claims the order is changed, unsupported, unknown, unchanged.
15. **Q1** is SPEC_m3o §3.2 with the date verified against the cited items (four date forms). The event-type map is copied from
    PREREG_m3o and a test compares it with the file. `undated` and `date_unsupported` do not act; they mark the name `pending_review`
    (`q1_escalation:...`) and are listed in the `resolved` line. **They are not auto-queued**: a rerun on the same evidence would only hit
    the run key, so the next trigger or refresh carries them.
16. **Carry rule.** `consecutive_unusable >= 2`, or `now - last_good_at >= 21 days` (a name with no good run counts from first seen).
    `last_good_at` is the manifest's `finished_at`. It is recomputed in `resolve`, `run_day` and `update_stale`.
17. **14-day refresh.** A name with no run for 14 days (`last_run_at` is set by `resolve`; a name never run is due at once) gets a P4 trigger
    `refresh:<ticker>:<date>` unless it already has an entry. Tail names are included.
18. **Lock.** Atomic `O_EXCL` create, pid inside, dead-pid takeover. A lock naming no pid is waited on for 10 minutes, then taken over.

## Defect found in passing (not mine to edit)

`scratch\rev23\m3o_run\o2_run.py` `take_lock()` checks the holder with `os.kill(pid, 0)`. **On Windows that call terminates the process**
(any signal other than the console-control events goes to `TerminateProcess`), so a second `o2_run.py` launch would kill the running
holder instead of declining. `m3p_monitor.pid_alive` uses `OpenProcess` / `GetExitCodeProcess` instead (test
`test_pid_alive_does_not_kill_the_process_it_asks_about`). The same line is in `n5_run.py` if it was copied from there; I did not check.

## Not done

- No price source is wired: prices are injected only (no Yahoo function, by the brief). WO_P3 needs one.
- No command line or scheduled task: `run_day` and `resolve` are library calls, so WO_P3 owns the wiring, the `read_ledger` crash scan and
  packet building.
- Section 7's measures are only partly there: `report()` gives coverage and queue age; missed events, false alarms, reanalysis delay and GPU
  throughput need the truth review and real runs.
- Nothing was run online: the four online functions were tested only with a faked `urlopen` and an injected JSON getter.
