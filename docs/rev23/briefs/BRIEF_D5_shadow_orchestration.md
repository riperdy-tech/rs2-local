# Brief D5: the nightly shadow run of engine v2 (SPEC_rebuild AK.66; plan D5)

## The goal
Paper (shadow) operation of SYSTEM = engine v2 by the end of October 2026: every night, value the whole gate universe at the latest US close
through the live runner (D4), append the rows to a **shadow ledger**, and build a **shadow overlay**. Nothing is published and nothing reaches
real money. Publishing and the switch of the production ledger are the **cutover**, which the operator approves separately (D6). Until then
the old analyst stays paused (`DEPTH_PAUSED`) and `KIS_HALT` stays true.

## Where and how
- **Repository:** `C:\Users\riper\stocks\rs2-local`. Create the worktree `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-d5-shadow` on a
  **new branch `review-2026-10/d5-shadow` from `review-2026-10/d4-live-runner` (`b78aff0` or later)**, then merge
  `review-2026-10/c2-rs2` (`8d26a31`) into it locally, so the gate, fiduciary v4 and the overlay branch are present. Resolve any conflict and
  report it. Work only there.
- **Your limits:**
  - Never touch other checkouts or worktrees, `cache/` of the main rs2-local checkout, or any scheduled task.
  - Never register or start a scheduled task, never push, merge or deploy, never call `publish_overlay`, never write
    `cache/depth_ledger.jsonl` or `cache/depth_overlay.json`.
  - Never edit `.env*` or secrets.
  - Commit by pathspec, with messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest valuation rebuild_harness tests/test_contract_v4.py -q`, plus your own. Record the
  counts before and after.
- **Memory:** about 12 GB and often near full. Before any run heavier than a unit test, wait until free physical memory exceeds 2.5 GB.
- **Read first:**
  - `C:\Users\riper\stocks\AGENTS.md` and the repository's `AGENTS.md`;
  - `SPEC_verdict_contract_v4.md` (all of it, including the errata section 13);
  - `SPEC_rebuild.md` AK.52–AK.66;
  - `scratch/rev23/d4_REPORT.md`, `scratch/rev23/c2_rs2_REPORT.md`;
  - the code: `valuation/live_runner.py`, `valuation/live_data.py`, `rebuild_harness/gate2/env.py` (`prepare_dates`),
    `rebuild_harness/gate2/score_day.py` (`refresh`, the companyfacts snapshot), `orchestrate_depth.py` (`rebuild_overlay`,
    `publish_overlay`, the locks and `DEPTH_PAUSED`), `tools/grade_depth_verdicts.py`.

## What to build: `shadow_v4.py` (repository root) and its tests
**One nightly command,** `python shadow_v4.py [--asof YYYY-MM-DD] [--dry-run]`, that runs these steps in order and stops, failing closed, at the
first step that cannot complete. Each step writes its own log line and result to `cache/shadow_v4/runs/<asof>/status.json`.

1. **Preflight (OPS-09):**
   - **The freeze:** the engine freeze manifest (`stocks-workspace/scratch/rev23/engine_v2_audit/freeze/ENGINE_V2_0_3_FREEZE.json`, its path a
     config key) exists. Every engine-file sha256 it lists equals the file in this tree, and every priors and near-term table it lists
     matches by sha256. The engine version, draws, seed rule and flags are read from it, never hard-coded. Until it exists, the job refuses
     (a rehearsal stand-in manifest marked `"rehearsal": true` is allowed only with `--dry-run`).
   - **Pause markers (ruled, AK.66):** this job stops, exiting 0 with "paused", on its own marker `cache/SHADOW_V4_PAUSED`. It does **not**
     stop on `DEPTH_PAUSED`, which pauses the old GPU analyst; the shadow is CPU only and must run while the old analyst is paused.
     `KIS_HALT` is read and reported, never changed.
   - **Resources:** free memory and free disk (≥ 20 GB) are checked. Any other lock of the old orchestrator (`LOCK`, the publish lock) is
     reported, never taken.
2. **`asof`:** the latest US trading day whose close is in `data/prices_daily/SPY.csv.gz`, or `--asof`. A date already run (its final ledger
   rows exist) is refused unless `--rerun-id` is given.
3. **Data refresh** (standing approval O5: SEC, Yahoo, Damodaran):
   - **SEC submissions:** download `submissions.zip` into a new dated folder under `data/sec_bulk/` (write-once, sha256 recorded), at most once
     per day.
   - **SEC companyfacts:** a **weekly** bulk snapshot through `score_day.refresh` (write-once; on the first run after Saturday), plus a
     **daily** per-company refresh through `live_data.refresh_companies` for every company of the universe with a 10-Q, 10-K or 8-K accepted
     after the snapshot's date. The daily files form a **live overlay store**, read in place of the snapshot for those companies. State in
     the report how the point-in-time layer guarantees that nothing accepted after `asof` is used.
   - **Prices:** daily closes for every universe ticker, appended to `data/prices_daily` without rewriting earlier rows; the fetcher is Yahoo
     (O5). Any ticker whose fetch fails stays stale, and the runner's `stale_inputs` then refuses it. Nothing is filled in.
   - **Damodaran:** monthly, through the existing reader's source. A failed fetch keeps the last file, and the staleness rule decides.
   - **Disk:** never delete anything. Report the growth per week.
4. **Context:** `env.prepare_dates([asof], state_dir=cache/shadow_v4/state, workers=1, ...)` with the registered gate-2 configuration and the
   freeze's priors folder.
5. **The census:** every company of `universe_<asof>.json` (commodity included as the runner handles it) through `live_runner.run`.
   - `run_source` "orchestrator" (ruled, AK.66). The shadow is the production behaviour simulated, so the gate must judge its rows exactly
     as it will after cutover. The shadow is separated by its ledger and overlay paths, never by `run_source`;
   - `--prior-rows` = the shadow ledger;
   - output in `cache/shadow_v4/runs/<asof>/`, with the partial file kept;
   - the `level_reference` computed in-run.
   - Report the wall time per company and in total. **If a full pass takes more than 3 hours, stop and report:** the coordinator then rules
     between a nightly subset and a different level-reference rule.
6. **The shadow ledger:** append the final rows to `cache/shadow_v4/shadow_ledger.jsonl` (append-only; one line per row; the run id and
   `asof` on each).
7. **The shadow overlay:** `rebuild_overlay`'s logic run on the shadow ledger, written to `cache/shadow_v4/shadow_overlay.json`. Factor out
   a function with the ledger and output paths as parameters if needed, without changing the production call's behaviour (its
   byte-identity test must stay green). **No publish.**
8. **The grader (weekly):** `grade_depth_verdicts` on the shadow ledger to `cache/shadow_v4/outcomes.json`. The distress grading stays
   unavailable until the event index records `resolved_through` (AK.64 R1).
9. **The summary:** one markdown file per night, covering the counts by status and abstention code, the gate reasons by count, the stale
   inputs by reason, the level reference per family, and the run time.

**The scheduled task:** write `register_shadow_v4_task.ps1` and a hidden `.vbs` launcher (memory: long runs outside Claude) that would run
`shadow_v4.py` daily at 07:30 KST, with paths derived from the repository root. **Do not register it**; the coordinator does, after audit.

## Fail-closed tests (plan Q12)
Each must refuse with a named reason, never fall back:
- SEC down;
- the companyfacts snapshot fails mid-download (the `.part` file never becomes the zip);
- one ticker's price fetch fails;
- Damodaran stale;
- the freeze manifest missing or a hash mismatch;
- a rerun of the same `asof`;
- memory low (waits, then refuses after a timeout);
- a crash mid-census (the partial file is kept, the ledger is untouched, and a rerun takes a new run id);
- the PC was off for 3 days (the next run values only the latest `asof`, stated, with no backfill).

## Rehearsal
`--dry-run` end to end at **asof 2026-06-30** on a **subset of 40 companies**:
- inputs: scratch copies of gate 2's `ctx` and store, the stand-in manifest, **no network**;
- output: a scratch folder only.

Then one **live** dry run at the latest `asof`, again on 40 companies, with the real network refresh restricted to those 40 companies (the
weekly bulk snapshot is **not** downloaded in the rehearsal). Report both.

## Deliverable
The branch with its commits, and a reply (not a file) holding:
- the changes;
- the test counts before and after;
- both rehearsal summaries;
- the per-company time;
- every judgement call or gap.

Decide nothing the contract or this brief leaves open; list it.
