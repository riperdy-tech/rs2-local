# RS2 Control Tower — Operator Runbook

Admin site: https://www.stockpeak.net/admin (GitHub sign-in, riperdy-tech only)

## Architecture (one paragraph)
The PC pushes a heartbeat + rhythm snapshot to Supabase every 5 min
(`RS2-Control-Agent` → `control_agent.py`) and backs depth state up to the
private `rs2-state` repo hourly (`sync_state.py`). The `/admin` site reads the
heartbeat, the committed freshness stamps, and the GitHub Actions API; its
buttons either dispatch whitelisted workflows (GH_PAT) or enqueue PC commands
in Supabase `control_commands`, which the agent executes within ~5 min. When
the PC is off: SDF falls back to the GitHub cron backstop (existing,
freshness-gated), and the depth sweep falls back to
`depth-cloud-backstop.yml` in rs2-local — the CONTINUITY arm: DeepSeek serves
the SAME trigger queue the PC would (`orchestrate_depth.build_queue`, cadence
spec §8), state seeded from rs2-state and handed back, 4h ladder, gated on
heartbeat >90 min dead, off-peak only, fail-closed when the heartbeat is
unreadable. On-demand `/analyze` requests queue in
Supabase `ondemand_queue` and drain when the PC's Telegram-bot bridge returns.

## PC-off playbook (PC won't power on)
0. (2026-09-01) Fastest path: press "☁ PC is off — run everything from cloud"
   at the top of /admin. One press = cloud data fetch now + KIS sync now (if
   the US session is open; every repo-var gate still governs) + depth backstop
   (its preflight decides). Optional — the cron ladders below cover PC-off
   days automatically even if you never press it.
1. Open /admin. Expect: "RS2 PC" card stale after 15 min, dead after 60.
2. Do nothing for SDF/KIS/price/weekly — cloud-native or auto-backstopped.
   SDF + KIS each run a BACKSTOP LADDER of crons (SDF 9:35/11:35/13:35/16:35,
   KIS 9:25/11:25/13:25/16:25/18:25 UTC weekdays); GitHub delivers crons
   0-9h late, so whichever arrival lands in-window does the job and the rest
   no-op (target-anchored freshness / synced-today dedupe / market gate).
3. Depth: nothing to do — the continuity ladder (10:05/14:05/18:05/22:05 UTC,
   DeepSeek OFF-PEAK ONLY: a peak-hour arrival, Mon-Fri 01-04/06-10 UTC,
   skips and force cannot override) serves the PC's own trigger queue in the
   PC's own priority order, max 6 names per run, 3 at a time: ~$0.11 per
   name, ~45 min per run (measured 2026-09-07 sequential: 128 min for 6).
   "⚠ Depth cloud backstop" (confirm dialog) runs one such pass now. Cloud
   verdicts count exactly like local ones (operator 2026-09-07); `arm:
   cloud_api` is provenance only, and the newest verdict for a name wins.
4. On-demand /analyze: requests keep queueing on /ondemand and drain when the
   PC returns. The Telegram bot is down too; alerts still arrive from cloud
   workflows.
5. KIS emergency: "HALT KIS trading" sets repo var `KIS_HALT=true`
   (pre-provisioned; the sync workflow refuses to trade while true).

## PC-return playbook
1. Power on + **log in** (all tasks are interactive-logon; a logged-out PC
   counts as "off" to the tower). Agent resumes within 5 min; card goes green.
2. The next agent pass (or `python sync_state.py`) imports any cloud
   `cloud_pending/depth_ledger_delta.jsonl` rows into the local ledger and
   truncates the delta, merges the cloud's membership days into
   `cache\depth_membership.jsonl` (local row wins on a shared date) and takes
   the cloud's newer `depth_state.json` records (retry budget). Verify: tail
   `cache\depth_ledger.jsonl` for `"arm": "cloud_api"`; the sync message
   reads `import N cloud rows, merge N cloud membership day(s), take N cloud
   state row(s)`.
3. Nothing else to reconcile: cloud verdicts return to the local arm on the
   usual triggers (8-K, filings, 8% move, pack revision, 90d rotation).

## Manual command equivalents (no admin site needed)
```
Data fetch (cloud):  gh workflow run schedule-data-fetch.yml -R riperdy-tech/stock-screener -f runner=ubuntu-latest
Depth backstop:      gh workflow run depth-cloud-backstop.yml -R riperdy-tech/rs2-local -f force=true
Halt KIS:            gh variable set KIS_HALT -R riperdy-tech/stock-screener --body true
PC depth pause/run:  create/delete cache\DEPTH_PAUSED, or schtasks /run /tn RS2-Depth-Orchestrator
```

## Known limits & sharp edges
- **Interactive-logon tasks:** logout silently stops the heartbeat, the bot
  bridge, and all local rhythms — the tower correctly reads this as "PC off".
- **Cloud depth verdicts run on thinner inputs:** no local research brief
  (`research_brief_age_days: null`), best-effort SearXNG, no sec_facts
  verification. Operator decision 2026-09-07: their RESULTS are treated as
  equivalent to local ones — the newest verdict wins regardless of arm.
- **`generated_at` is naive Taipei by convention:** the backstop workflow pins
  `TZ=Asia/Taipei` on the driver step so a cloud-written overlay stamps the same
  clock the PC does (without it every consumer reads the overlay 8h older).
- **`CROSS_REPO_PAT` (rs2-local secrets) is the gh CLI's oauth token** —
  running `gh auth logout` on the PC revokes it and breaks the backstop's
  checkouts. Re-set the secret after any gh re-auth.
- **Backstop refuses to run when the heartbeat is unreadable** (Supabase
  outage): it Telegram-alerts and waits. If the PC is truly dead too, dispatch
  with `force=true`.
- **The cloud arm shares the PC's retry budget:** `depth_state.json` is seeded
  from and handed back to rs2-state, so a name DeepSeek fails twice is skipped
  by the PC too until its record is cleared (same `MAX_RETRIES=2` rule).
- One operator account (riperdy-tech) is the only admin; sessions last 30
  days; rotating `ADMIN_GITHUB_LOGIN` or `ADMIN_SESSION_SECRET` in Vercel
  revokes them.
- KIS pointer state (2026-08-31): `KIS_LEDGER=rn_depth`, `KIS_ENV=real`,
  `KIS_AUTO_EXECUTE=true`, `KIS_HALT=false`. The dashboard shows these
  read-only; only `KIS_HALT` is writable from the tower.
- Logs `cache\control_agent_task.log` / `sdf_dispatch.log` / delta files have
  no rotation — prune occasionally.
