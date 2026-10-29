# WO_P2: the 3P monitor, without the GPU (builder brief, 2026-10-29)

**Goal:** `m3p_monitor.py`. It covers SPEC_m3p_monitoring.md §§1–3, 5 and 6: the monitored set, the daily gather, the
deterministic triggers, the priority queue and the journal. §4's model runs are only queued here; executing them is
WO_P3.

**Read first:**
- `SPEC_m3p_monitoring.md`, `RR_P1.md` and `AUDIT_P1.md` (this folder);
- `SPEC_m3o_integration.md` §6, for the book files the monitored set comes from;
- `stocks-workspace/scratch/rev23/m3n/baseline_b.py`;
- read-only, the P6.6 leaf functions to copy: `git -C C:\Users\riper\stocks\rs2-local show 23e41c4:followup_gather.py`
  (`filing_texts`, `normalize_title`, `press_name`, `followup_news`, the seen-set pruning) and the B2 pacing that RR_P1
  cites.

**Where:** a new folder, `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3p\`. It holds `m3p_monitor.py`,
`tests/` and `fixtures/`; state goes in `m3p/state/` and the journal in `m3p/journal.jsonl`. Nothing else is edited.

**Do not:**
- use the network in tests. The code may have online functions, but tests use fixtures and injected fetchers, and you
  do not run them online.
- touch the GPU or Ollama, or edit any git repository;
- read `.secrets.json` or `.env*`. The SEC contact comes from the `SEC_USER_AGENT` environment variable, read at call
  time; if it is missing, refuse with a clear error.
- open `m3n\n5\runs*`, `m3n\n6\` or any `cache\*\runs\`.

## Behaviour

1. **`members(books, newest_book, restricted, today)`:** the §1 set, with each name's reason and the 30-day tail.
2. **The gather per name**, since its last gather (state kept per CIK):
   - SEC filings of the issuer's own CIK from its submissions JSON: form, items, accession, `acceptanceDateTime`,
     primary document. This includes NT 10-K and NT 10-Q, and 8-K items 1.02, 2.04 and 4.01.
   - closes, from an injected price source;
   - news, from an injected source, labelled `secondary`;
   - dedupe as §2.4: filings by accession; news by normalised title **and** URL. An undated row is never new at a
     name's first gather.
   - the cross-issuer guard of §2.5.
3. **Triggers** P0–P4, exactly as §3's table:
   - B-pattern hits come from `baseline_b.py`'s rules on the new filing texts;
   - the price trigger is 3 standard deviations of 60-day log returns, or 20% over 5 sessions. These are design values;
     the docstring must say so.
4. **The queue:**
   - priority first, then trigger time;
   - one entry per name, keeping its highest priority;
   - a run key (CIK, packet sha256, prompt, contract, builder) that has already run is never queued again;
   - the 14-day refresh (P4) only when the name has had no run for 14 days.
   - Persist the queue atomically (write tmp, then replace).
5. **The journal:** append-only lines `discovered`, `queued`, `analysed`, `resolved` and `failed`, with the fields §6
   names. A `resolved` line is written by `resolve(run_dir)`. It reads a qwen_c run's `manifest.json` and
   `analysis.json`, checks `analysis_sha256`, and sets:
   - the name state (§4);
   - the per-point `thesis_change` states;
   - the Q1 verdict, using SPEC_m3o's Q1, including verification of the stated date against the cited items;
   - `pending_review` and `stale_analysis` under the carry rule (§5).
6. **Recovery:**
   - a lock with dead-pid takeover (as `o2_run.py`);
   - a crash between a queue write and a journal write must not lose or duplicate an entry. Show this with a test that
     kills the writer between the two.

## Tests (fixtures only; `"C:\Program Files\Python312\python.exe" -m pytest tests -q` from `m3p/`)

Each priority's trigger; no trigger; the price trigger at its boundary; a duplicate filing and duplicate news are not
new; an undated row at the first gather; another issuer's filing is annotated; queue order and dedupe; the run key
blocks a rerun; the 14-day refresh; `resolve` on an ok run, a failed run (keeps the last good analysis, `pending_review`)
and a sha mismatch (refused); the carry limit after two failures and after 21 days; crash recovery; a missing
`SEC_USER_AGENT` is refused; a 0.0 close is a value.

## Report

`RR_P2.md` in this folder: the files, the test count from one final run, and every choice the brief left open.
