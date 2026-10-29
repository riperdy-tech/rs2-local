# WO_P1: read-only inventory for 3P monitoring (2026-10-29)

**Goal:** settle SPEC_m3p_monitoring.md §0 and §9 with facts. **Read-only:** no edit, no git change, no network, no
GPU, no `.secrets.json` / `.env*`. Do not open `scratch\rev23\m3n\n5\runs*`, `m3n\n6\` or any `cache\*\runs\`.

## Questions (answer each with file:line evidence)

1. **What of PHASE_6_FOLLOWUP P6.5–P6.9 exists, and on which rs2-local branch or commit?**
   - Files: `followup_gather.py`, `watch_items.py`, `followup_news`, `followup_lock.py`, `followup_read.py`,
     `depth_triggers.py`, `thesis_monitor.py`.
   - Is it on the live branch the scheduled tasks use? (`git -C C:\Users\riper\stocks\rs2-local branch -a --contains <commit>`, `git log`)
2. **Can the SEC gather and the news gather run apart from the depth pipeline?**
   - As a library call for a list of (ticker, CIK);
   - without reading a depth verdict, `consensus_dir` or `_pack.md`;
   - without writing `depth_followup_state.json`, `depth_watch.json`, `depth_thesis.json`, the overlay or anything
     under `cache/` that the depth pipeline reads;
   - and under `cache/DEPTH_PAUSED`.

   Name each coupling that blocks this.
3. **News.** Which source does `company_news.fetch` use? Is SearXNG on port 8888 required? What dates does a row carry,
   and how is the seen-set kept?
4. **qwen_c runtimes,** from records only:
   - `stocks-workspace\docs\review_2026-09-22\rev23\orchestration\RR_M-LIVE.md`;
   - `scratch\rev23\m3n\n5\runs.jsonl`: read only its `task`, `kind` and `seconds` fields.

   Give the seconds per run for the full seven-task run, for `material_events` alone and for `risks` alone, as
   median / p90 / max.
5. **Is any scheduled task** (Windows Task Scheduler names starting `RS2`) currently set to run follow-up or depth code?
   - Read with `schtasks /query /fo LIST` or PowerShell `Get-ScheduledTask`. Read only.
   - Give the name, state and action.

## Report

`RR_P1.md` in this folder: one section per question, file:line citations, and a one-line recommendation for SPEC_m3p
§0's "to be decided" row (reuse as a data source / write a small qwen_c-side gather), with the reason.
