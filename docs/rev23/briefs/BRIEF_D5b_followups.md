# Brief D5b: the follow-ups to the nightly shadow run (SPEC_rebuild AK.69)

## Where and how
- **Repository:** rs2-local. Work in the **existing** worktree `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-d5-shadow` on branch
  `review-2026-10/d5-shadow`, continuing from `2dfdfee`. The first builder has finished and nobody else uses this worktree.
- **The limits are those of `BRIEF_D5_shadow_orchestration.md`,** all of which still apply:
  - never publish, push, merge, deploy, or register or start a task;
  - never write production `cache/depth_ledger.jsonl` or `cache/depth_overlay.json`;
  - never touch other worktrees;
  - never edit `.env*`;
  - never delete files;
  - commit by pathspec, ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - wait for more than 2.5 GB of free memory before any run heavier than a unit test.
- **Read first:**
  - `BRIEF_D5_shadow_orchestration.md` (same folder);
  - `scratch/rev23/d5_REPORT.md` (what was built and what blocked it);
  - SPEC_rebuild **AK.69** (the rulings you implement);
  - `SPEC_verdict_contract_v4.md` section 13;
  - the code on the branch: `shadow_v4.py`, `valuation/live_runner.py`, `valuation/live_data.py`, `rebuild_harness/gate2/env.py`,
    `rebuild_harness/holdout_inputs.py`.

## What to change (AK.69 rulings 1–7)
1. **Live classification:**
   - `shadow_v4` prepares a live `asof` with `strict_classification=False`, only when the SEC records were fetched within 3 weekdays of
     `asof`. Otherwise it refuses with a named reason.
   - Every row records its classification source (as filed, or current at `asof`). Find where the source is known and carry it to the row
     as `classification_source`, which the single-owner table adds.
   - Replays (`--asof` in the past beyond 3 weekdays) and every gate-2/2b path keep strict classification. Test both.
2. **Facts freshness:**
   - `live_data.stale_reasons` gains a mode (keep the default unchanged for its existing callers). In it, the age limit applies to the
     company's **submissions read**, not to the facts fetch: fresh when the submissions were read within 2 days and SEC lists no 10-Q or
     10-K accepted after the store's latest filing for that company.
   - `shadow_v4` uses that mode.
3. **Its own price folder:** `cache/shadow_v4/prices_daily`, seeded from `data/prices_daily` by hard link with copy-on-write before any
   append. Show by test that the shared folder's bytes and mtimes are unchanged after a refresh.
4. **SEC through the daily index:**
   - `submissions.zip` is downloaded **weekly**, alongside the companyfacts snapshot.
   - **Daily:** read EDGAR's daily form index for each business day since the last run
     (`https://www.sec.gov/Archives/edgar/daily-index/<year>/QTR<n>/form.<yyyymmdd>.idx`, rs2's User-Agent and throttle). Fetch
     per-company submissions and facts only for the universe companies it lists.
   - A missing index day (a holiday) is recorded, never a failure. An index that fails to download refuses the run.
   - Report the expected disk use per week.
5. **A company's own price age:** in the runner, a valued row whose company close is more than `PRICE_MAX_TRADING_DAYS` (3) weekdays before
   `asof` gets the `stale_inputs` reason "price: last close <date>, <n> weekdays old". Test it, including that SPY's check is unchanged.
6. **Tickers:**
   - Every job carries its id-map ticker, and a row refused before its inputs keeps it.
   - The grader skips a v4 row without a ticker, never failing, and lists it.
   - The overlay never merges two rows under a null key.
7. **The census limit** is 6 hours (a config key). Use 2 workers when free memory exceeds 5 GB, and otherwise 1. If the existing runner
   cannot run 2 workers safely, say so and keep 1.

## Rehearsals
1. **Rehearsal 1 again** (06-30 dry run, 40 companies, no network): confirm nothing changed except the intended fields.
2. **The live dry run again** at the latest `asof`, on 40 companies, with the daily index and per-company refresh but **no** weekly bulk
   download. It must now pass the context step and produce rows. Report:
   - the rows' gate reasons;
   - the stale reasons by count;
   - the classification sources;
   - the time per company.

## Deliverable
Reply as text (no report file):
- the commits;
- the test counts before and after;
- both rehearsal summaries;
- the time per company;
- every judgement call or gap.

Decide nothing left open; list it.
