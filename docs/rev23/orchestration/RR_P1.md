# RR_P1: read-only inventory for 3P monitoring (2026-10-29)

Work order: `WO_P1.md`. Read-only: no file was edited except this one, no git state changed, no network call, no GPU,
no Ollama call, no `.secrets.json` or `.env*`. `n5\runs*` (other than the three fields of `runs.jsonl` the brief allows),
`n6\` and every `cache\*\runs\` were not opened. Scheduled tasks were queried only.

**Citation key.** Paths are in `C:\Users\riper\stocks\rs2-local` unless stated. `p6` means branch
`review-2026-09/phase-6-on-rev21` at `91f35c0` (read with `git show`; no checkout). `live` means the branch checked out in
rs2-local, `review-2026-09/phase-4` at `5b9ccf5` (HEAD, 2026-10-29 14:48 +0900). Line numbers are those of the file at that
commit.

## Q1. What of P6.5–P6.9 exists, and where

**Answer: all of it is built, none of it is on the live branch, and none of it is on `main`, `m3m-qwen` or `m3n`.**

Branches that hold it (`git branch -a --contains`):
- `review-2026-09/phase-6-followup` at `23e41c4`: the original build, on the revision-16 line.
- `review-2026-09/phase-6-fix-source`: same tip, `23e41c4`.
- `review-2026-09/phase-6-on-rev21` at `91f35c0`: the build merged onto revision 21 (`c5b2681` merge, then `91f35c0` "point the
  follow-up endpoint at llm_provider"). PHASE_6_FOLLOWUP.md §header names this branch as "what goes live".
- Not on `main` (`b2f1cd6`, 2026-09-20), `review-2026-09/phase-4` (live), `review-2026-10/m3m-qwen` (`bac4cf8`),
  `review-2026-10/m3n` (`626e086`) or `review-2026-10/rebuild-int`. `git merge-base --is-ancestor 91f35c0 <b>` is false for
  each of `main`, `m3n` and `phase-4`. The merge-base of live and p6 is `f5a540c` (revision 21); live is 7 commits ahead of it,
  p6 is 26 ahead.
- Screener side (P6.8): `d132fb6868` is on stock-screener branch `review-2026-09/phase-6-followup` only.

Per piece (files present at p6, absent on live unless stated; `git ls-tree` and `git diff --shortstat live p6`):

| Item | File | At p6 | On live |
|---|---|---|---|
| P6.5 numeric monitor | `thesis_monitor.py` | +719/−136 lines against live (unit readings, `metric_not_shown`, `rule_unit_impossible`) | older version: `run()` at `thesis_monitor.py:286`, no `metric_not_shown` or `rule_unit` |
| P6.6 gather | `followup_gather.py` (1,030 lines; `followup_news()` is a function inside it at `:536`, not a separate module) | present | absent |
| P6.6 watch items | `watch_items.py` (355 lines) | present | absent |
| P6.6 lock | `followup_lock.py` (204 lines) | present | absent |
| P6.7 daily read | `followup_read.py` (1,666 lines), `followup_server.py` (182), `tools/make_followup_model.py` (175) | present | absent |
| P6.8 states | `depth_gates.py`: `holding_state :382`, `is_candidate :406`, `direction_at :503` | +161 lines | absent |
| P6.9 schedule | `depth_triggers.py` (+253/−72), `orchestrate_depth.py` (+696/−95), `depth_membership.py`, `sync_state.py` | present | older versions; live `depth_triggers.py` has `newest_verdicts :86` and `_filings_since :109` (form and date only) and no `filings_since_detail` |
| Tests | `tests/test_followup_{gather,read,drain,schedule,server}.py`, `test_make_followup_model.py`, `test_watch_items.py`, `test_thesis_monitor_p65.py`, `test_thesis_triggers.py`, `tools/audit_202608/tests/test_rev21_followup.py` | present | absent |

Production state confirms it never went live: `cache/` in rs2-local holds `depth_ledger.jsonl`, `depth_thesis.json` and
`DEPTH_PAUSED`, and holds no `depth_followup_state.json`, `depth_watch.json` or `followup_*` (directory listing).
`cache/DEPTH_PAUSED` reads "operator 2026-10-06: baseline paused after the valuation review".

**Port hazard found in passing (live branch):** `5b9ccf5` replaced the module constant `sec_guidance.UA` with a function
`sec_ua()` (`sec_guidance.py:23-31`) that raises unless env `SEC_USER_AGENT` contains "@". The p6 code still reads the old
constant: `followup_gather.py:265` (`headers=sec_guidance.UA`) and `depth_triggers.py:104` (`UA = sec_guidance.UA`). Merging p6
onto live as it stands would fail at import in `depth_triggers`. Any 3P code that fetches SEC text must call `sec_ua()` and
needs `SEC_USER_AGENT` set in the process environment.

## Q2. Can the SEC gather and the news gather run apart from the depth pipeline?

**Answer: not as a library call for a list of (ticker, CIK). Pieces of it can be called that way; `followup_gather.run()` cannot,
without a cloned tree. It does run under `DEPTH_PAUSED`. Couplings, each with its evidence:**

Requested property, then verdict:
1. *Library call for a list of (ticker, CIK):* **No.** `run(scope=None, now=None)` takes tickers only (`followup_gather.py:980`;
   `scope` = `{held, candidates, price}`, `:742-749`). The CIK is looked up inside, by `depth_triggers._cik(t)` (`:702`) =
   `capability_test.cik`, which reads the screener's `cik_map.json` (`tools/audit_202608/capability_test.py:472-482`).
   Leaf functions do take a CIK: `depth_triggers.filings_since_detail(cik, since_date)` (`depth_triggers.py:169`),
   `filing_texts(cik, accession)` (`followup_gather.py:272`), `followup_news(company, ticker, today)` (`:536`),
   `company_news.fetch(company, ticker)` (`company_news.py:394`).
2. *Without a depth verdict, `consensus_dir` or `_pack.md`:* **No** for `run()`; yes for the leaf functions.
   - **Verdict (ledger):** `run()` starts from `depth_triggers.newest_verdicts()` (`:991`), which reads `cache/depth_ledger.jsonl`
     (`depth_triggers.py:69,108-118`). `_select` drops any name with no verdict or no `consensus_dir` (`followup_gather.py:762-768`).
   - **Verdict date as the window:** SEC uses `v.get("date")` as `since_date` (`:456,460`), strictly after, at day granularity;
     news drops rows dated on or before it (`:632,641-644`). There is no "since the name's last gather" window apart from the
     per-accession `filings_seen` list (`:466`).
   - **`consensus_dir` as the record key:** state is keyed and reset by it (`:416-436`, `:807`).
   - **`_pack.md`:** optional. `pack_headlines` reads it to seed the seen-set (`:199-222,694`); absence is tolerated and logged
     ("every headline of the first fetch will read as new", `:696`).
   - **Held set:** `depth_membership.held_names()` reads `paper_ledgers.json` `rn_depth` holdings (`:991`; `depth_membership.py:166-179`).
     `scope` overrides it.
   - **Price crossing:** `_price_check` calls `depth_gates.direction_at(c, v)` on the verdict's band (`:384`), run for every
     selected name (`:722`). Without a band it has nothing to compare.
   - **`depth_thesis.json`:** read (`:993`) for `thesis_breach` events (`:665-685`); a missing file is tolerated (`:776-782`).
   - **Consensus memos:** `watch_items.build` reads `ab_reports/consensus/<dir>/consensus.json` and `sample*.md`
     (`watch_items.py:39,235-241`).
3. *Without writing depth state:* **No**, by default. Fixed paths under the module's own directory (`HERE`, `:106`), no override
   by environment or argument (`:121-127`):
   - `cache/depth_followup_state.json`, written on every run (`_commit`, `:863-886`);
   - `cache/followup_inbox/{T}/{date}.json` (`:874-878`);
   - `cache/depth_watch.json`, via `_watch_lists` (`:957-977`, called at `:1009`; no switch to skip it);
   - `cache/followup.lock` (`followup_lock.py:44`);
   - `cache/followup_filings/`, `cache/followup_news/` (`:123-125`).
   - It does not write `depth_thesis.json` (it only reads it), and does not write the overlay or the ledger.
   - **Two shared caches the depth pipeline also reads:**
     - `cache/sec_submissions/CIK*.json` (`sec_guidance.py:18,36-55`: per-UTC-day cache, written on a miss);
     - `cache/company_news/{T}_{date}.json` (`company_news.py:36,281-283,385-389`, same-day reuse). The depth pack builder
       imports `company_news` (`capability_test.py:51`), so a gather that runs first fixes the pack's news for that day.
   - **Proven isolation route:** run it from a separate tree. `b2_day.py` does this: a detached worktree whose own ledger
     holds the 104 verdicts and whose own `ab_reports/consensus` holds copies of their directories (`b2_day.py:62-82`; its
     docstring says it "writes only that tree's cache/: nothing reaches the live store"). Every `cache/` path above then lives
     in that tree. The screener data directory (`rs2_data.CONFIG["screener_data_dir"]`, `followup_gather.py:121`) is shared and
     read-only.
4. *Under `cache/DEPTH_PAUSED`:* **Yes.** None of `followup_gather.py`, `followup_read.py`, `followup_lock.py`,
   `watch_items.py`, `thesis_monitor.py`, `depth_triggers.py` mentions `DEPTH_PAUSED` or `PAUSED` (`git grep`, no match).
   The pause is enforced only in `orchestrate_depth.py` (`--monitor` refuses when paused, `:1390-1394`; the `--gather` bypass
   for a store copy, `:1317-1323`; the sweep, `:1522-1559`). A direct `followup_gather.run()` ignores the file. The B2 task does
   exactly this while `DEPTH_PAUSED` is present.

**Other couplings that matter for reuse:**
- **Import weight.** `followup_gather` imports `depth_triggers` (`:114`), which imports `capability_test` (`depth_triggers.py:61`),
  a 4,180-line module that itself imports the whole pack stack (`capability_test.py:31-57`); it also imports `thesis_monitor`,
  `watch_items`, `catalyst_research`. Importing it pulls in the analyst pack builder.
- **`sec_guidance.UA` removed on live** (Q1 hazard above).
- **Floor does not match SPEC_m3p §3.** Critical items are `{1.03, 2.06, 3.01, 4.02, 5.01}` (`followup_gather.py:134`); the spec's
  P0 set is `{1.02, 1.03, 2.04, 2.06, 3.01, 4.01, 4.02}` (SPEC §3). 1.02, 2.04 and 4.01 are missing; 5.01 is extra. Forms kept:
  8-K, 8-K/A, 6-K, 6-K/A, plus 10-Q, 10-K, 10-K/A, 10-Q/A, 20-F, 40-F (`depth_triggers.py:105`; filter at `followup_gather.py:482`).
  **NT 10-K and NT 10-Q are dropped** (`elif form not in LISTED_FORMS: continue`), and the spec lists NT filings as P0.
- **No acceptance time.** `filings_since_detail` returns form, date, items, accession and primary_document only
  (`depth_triggers.py:169-190`); `acceptanceDateTime` is in the submissions feed but is not carried, and SPEC §2.1 and §7 need it.
- **Cross-issuer guard exists for news only** (`followup_gather.py:518-533`: the issuer's distinctive word must be in title or text).
  SEC items come only from the supplied CIK (`:460`).
- **Operational facts from the running B2 gather** (task `RS2-B2-Gather-P6`, log `…\scratchpad\b2\days.log`): 25 daily gathers
  since 2026-10-03, 104 names in 4 batches of 26 with 600 s pauses (`b2_day.py:BATCH, PAUSE_S`), 102 batches logged; batch
  time median 649 s, p90 855 s, one outlier of 5,013 s; per-batch `errors 0` throughout; one batch killed on 10-14
  (exit 1073807364). The pauses exist because an unpaced 104-name run got SearXNG's Reuters engine suspended
  (PHASE_6_FOLLOWUP §7 handover item 8; `followup_gather.py:136-140`).

## Q3. News

- **Source:** `company_news.fetch` (`company_news.py:394`) calls `_fetch_live` (`:280`). It sends two queries, `"<clean company>"` and
  `<TICKER> stock` (`:302`), to SearXNG, category `news`, `time_range=month`, `format=json` (`_query_searxng`, `:188-196`).
  No other source. The pack text names "Reuters, Bing News" (`:2`).
- **SearXNG on port 8888 is required.** The endpoint is `rs2_data.CONFIG["searxng_url"]`, default `http://localhost:8888`
  (`:37,304`; `config.json:36`). On failure the function does not raise: it records the error and returns zero rows (`:307-317`).
  `followup_news` has no fallback either: with no `searxng_url` each query gets the error "no searxng_url in the config"
  (`followup_gather.py:561-563`). Port 8888 is listening now (`netstat`, PID 15924; no query was sent).
- **Extra queries in the gather.** After `company_news.fetch`, `followup_news` sends five week-window queries (`NEWS_QUERIES`,
  `followup_gather.py:141-147`; name alone on the news category, four category queries to Bing News only) and merges rows
  not already present by title or address (`:623-630`).
- **Dates on a row.** `date` is `publishedDate` cut to `YYYY-MM-DD`, or `None` (`company_news.py:51-56,364`); other fields
  `source`, `title` (150 chars), `url`, `snippet`; the top five rows also get `excerpt` and `read_from` from a page fetch
  (`READ_TOP = 5`, `:201,253-277`). Sorted dated-first, newest first, cut at 15 (`:368-369`). An undated row in the gather inbox
  carries `first_seen` (the gather timestamp) instead of `date` (`followup_gather.py:645-652`). Per PHASE_6_FOLLOWUP §2, 23% of
  rows were dated.
- **Seen-set.** Kept in `cache/depth_followup_state.json`, per ticker: `seen_headlines` (normalised title: NFKC, lower case,
  non-alphanumerics to a space; `normalize_title`, `:169-171`) and `seen_dates` (first-seen day) (`:404`; `_news_step`
  `:631-640`). Seeded from the verdict's `_pack.md` headlines (`:694-698`). Pruned 45 days after first seen
  (`SEEN_KEEP_DAYS`, `:157`; `_prune_seen`, `:824-843`). Rules: a new row dated on or before the verdict date is recorded as
  seen and not reported (`:641-644`); an undated row at a name's first gather is recorded and not reported (`:645-647`).
  **Difference from SPEC §2.4:** the spec says "normalised title plus URL"; the code's seen-set is the normalised title only. URL is
  used to merge duplicates within one run (`:626-629`), not across days.
- **Role.** Rows get `found_by` tags (`:653-655`); nothing in the gather treats news as a primary-filing witness. Consistent with
  SPEC §2.3 (news may queue, cannot act alone).

## Q4. qwen_c runtimes (records only)

Sources: `RR_M-LIVE.md:7,38` and `AUDIT_M5.md:10` for whole runs; `scratch\rev23\m3n\n5\runs.jsonl` (fields `task`, `kind`,
`seconds` only) for single tasks. Run at 2026-10-29 ~22:36 local, **134 rows and still growing** (task `RS2-M3N-DEV-Runner` is
Running), so the figures are provisional. Percentiles use linear interpolation. No row was missing `seconds`.

**Single-task runs (3N DEV, Ollama tag `rs2-analyst-deep-mtp5-v33`):**

| Task (kind) | n | median s | p90 s | max s |
|---|---|---|---|---|
| `material_events`, all kinds | 90 | 140.9 | 210.1 | 467.7 |
| – T1 | 34 | 133.4 | 206.0 | 437.5 |
| – T2 | 34 | 150.9 | 211.6 | 467.7 |
| – control | 22 | 133.0 | 171.7 | 209.1 (min 14.0) |
| `risks`, all kinds | 44 | 138.3 | 244.7 | 475.7 |
| – T0 | 22 | 169.2 | 246.6 | 475.7 |
| – control | 22 | 117.2 | 188.7 | 333.5 |

**Full runs: median, p90 and max cannot be computed from the permitted records.** What the records give:
- M-LIVE (`RR_M-LIVE.md:7`): 6 runs, 02:51:20–04:02:10 UTC, 70 min 50 s in all, i.e. a mean of **708 s (11.8 min) per run**.
  Per-task times 78–204 s (`:38`). The MA smoke run took "about 12 minutes", tasks 86–182 s (`AUDIT_M5.md:10`).
- These were **six-task runs**: with no prior run `thesis_change` is `not_applicable_no_prior` and is not sent
  (`SPEC_m3m_qwen_pipeline.md:121-130`; `RR_M-LIVE.md:34`). **No record holds a timed seven-task run**, and no record times
  `thesis_change` alone. Per-run totals sit in each run's `manifest.json`, under the `cache\*\runs\` directories the brief
  excludes.
- Planning value until WO_P3 measures it: a full run with a prior is about 12 min plus one task (about 2–3 min), so
  **about 14–15 min, an estimate, not a measurement**. A P0–P3 run (`material_events` plus `thesis_change`) is about 5 min by the
  same arithmetic.

## Q5. Scheduled tasks (Task Scheduler names starting `RS2`; `Get-ScheduledTask`, read only)

Tasks that run or can run follow-up or depth code:

| Name | State | Action | Notes |
|---|---|---|---|
| `RS2-B2-Gather-P6` | **Ready**, daily 06:00 +09:00, last 2026-10-29 06:00, result 0 | `python -u …\scratchpad\b2\b2_day.py` (a Claude session's temp scratchpad) | **Runs follow-up code now**: `followup_gather.run` on the detached worktree `rs2-B2` at `7c63a63`, 104 names, no GPU, writes only that tree's `cache/`. Lives in a temp scratchpad directory (see memory "Long runs outside Claude"). |
| `RS2-Shadow-Week-P6C` | Disabled; last run 2026-10-05 07:30 | `python -u …\scratchpad\shadow\shadow_day.py` | Follow-up shadow week (acceptance C). Its script was not found on disk (`shadow\shadow_day.py` missing). |
| `RS2-Depth-Orchestrator` | **Disabled**; daily 03:00 every 4 h, last 2026-09-19, result 3221225786 | `cmd /c python rs2-local\orchestrate_depth.py >> cache\depth_orchestrate_task.log` | Runs the live checkout (`phase-4`), which has no follow-up code. The shown "Next run" for disabled tasks is not real. |
| `RS2-Orchestrator` | Disabled; last 2026-09-20 | `…\Downloads\RS2 Local\orchestrate.py` | Old pipeline copy. |
| `RS2-Control-Agent` | Ready, every 5 min, last 22:34 | `wscript run_control_agent_hidden.vbs` → `control_agent.py` | Status and command agent; can start `RS2-Depth-Orchestrator` by `schtasks /run` (`control_agent.py:130`) but does not run follow-up code itself. |
| `RS2-M3N-DEV-Runner` | **Running** | `wscript scratch\rev23\m3n\launch_n5.vbs` → `n5_run.py` | qwen_c 3N DEV runs, GPU in use. Not follow-up, not the depth orchestrator. |
| `RS2-P4-R26-AMEND1`, `-IT3`, `-ITER`, `-PREP`, `-SMOKE`, `-STAGE1` | Ready | `launch_p4r26.vbs <kind>` (revision-26 depth pilot, `pilot_r25\tree_p4r26`) | AMEND1 one-shot dated 2026-10-21 (last result 8); IT3 trigger dated 2027-01-01; the others have no trigger. Exit flags in `logs_p4r26\` also block re-runs (`launch_p4r26.vbs`). |
| `RS2-P4-BRIDGE`, `RS2-P4-SF`, `RS2-Gate2-AB/-MilestoneReview/-PostMasked/-Rehearsal/-Repeat/-Replay` | Disabled | scratch launchers for earlier pilots and gates | Depth-analyst experiment code; disabled. |
| `RS2-KIS-Dispatch`, `RS2-SDF-Dispatch` | Ready | `gh workflow run kis-sync.yml / schedule-data-fetch.yml -R riperdy-tech/stock-screener` | GitHub dispatch only, no rs2 code. |
| `RS2-Telegram-Bot` | Ready, at logon, last result 1 | `telegram_status_bot.py` | Status bot. |

No task named `RS2-Thesis-Monitor` exists (PHASE_6_FOLLOWUP §7 says it would be registered at go-live); the registrar script is
`register_monitor_task.ps1`. So **no scheduled task currently runs depth-orchestrator code (disabled), and the one that runs
follow-up code is the B2 gather on a scratch worktree.**

## Recommendation for SPEC_m3p §0, "SEC gather, news gather, seen-sets" row

**Write a small qwen_c-side gather; do not reuse P6.6 as a data source.** Reason: `followup_gather.run()` cannot run clean apart
from depth. It needs a depth ledger verdict and `consensus_dir` per name (`:991,762-768`), always writes
`depth_followup_state.json`, the inbox and `depth_watch.json` into a fixed `HERE/cache` (`:121-127,863-886,1009`), shares two
caches with the depth pack, imports the whole pack stack, is on no live branch, would fail on live at `sec_guidance.UA`
(`:265`; `depth_triggers.py:104`), and also misses what 3P needs (NT filings, items 1.02/2.04/4.01, acceptance time, a
last-gather window, title-plus-URL dedupe). It does run under `DEPTH_PAUSED` (it never checks it), and the B2 run is evidence
it is sound (25 days, 0 errors), but that runs on a cloned tree with a copied ledger. Copy the proven pieces into the new gather
rather than import them: `filing_texts` (`:272-315`), `normalize_title`, `press_name`, `followup_news` and its Bing-only category
queries (`:141-147,490-601`), the seen-set prune (`:824-843`), and the B2 pacing (26 names per batch, 600 s pause; SearXNG Reuters
was suspended once by unpaced load). Take the SEC contact from `sec_ua()`. Keep the new gather's files under an `m3p/` directory
of its own.

## Open items this inventory did not settle

- Per-run totals (median, p90, max) for qwen_c full runs: needs the manifests (excluded) or the WO_P3 benchmark.
- Whether `RS2-B2-Gather-P6` should be treated as a live witness feed for 3P or retired once B2 closes; its worktree and script are in
  a Claude temp directory.
