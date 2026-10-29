# WO_L1: Archive the GitHub Actions witness records

- **Milestone and gate:** 3L, gate L-ARCH (PLAN Section W and §3L).
- **Issued:** 2026-10-28 by Claude (orchestrator). **Urgent.** GitHub deletes run logs after about 90 days, so the oldest logs disappear daily.

## Goal

Preserve, as files in the project folder, GitHub's server-side records of every Actions run of
`riperdy-tech/stock-screener` that still has logs. Those records are the independent witness for `PIT_PROSPECTIVE` and
for the forward record (WO-L7). Nothing is analysed in this work order; it is preservation only.

## Inputs

- Repository `riperdy-tech/stock-screener`.
- The `gh` CLI on the PC, already signed in as riperdy-tech. **Use `gh` on the PC only.** Your own web-fetch tools are
  anonymous and get HTTP 403 on the log endpoints.
- About 650 runs were created from 2026-07-30 onward (933 runs in total): Scheduled Data Fetch, Post-Close Price Refresh,
  KIS Portfolio Sync, Paradigm Weekly Analyst Coverage and others.
- The example to follow is `stocks-workspace/scratch/rev23/gh_run_witness_40608600897/`.

## Scope

- **Create only** `stocks-workspace/scratch/rev23/gh_witness_archive/` and the files inside it, plus your script
  `stocks-workspace/scratch/rev23/gh_witness_archive/archive_runs.py`.
- **Edit nothing else.** No repository changes, no commits, no pushes.
- **Allowed operations:** read-only `gh api` / `gh run` calls and local file writes inside that folder. No other network
  access.
- **Excluded:** never call any endpoint that re-runs, cancels or deletes a run. KIS workflow logs are archived like any
  other run, but you must not open, print or quote any token- or account-like value from them in your report.

## Steps

1. List every run with pagination: `gh api --paginate "repos/riperdy-tech/stock-screener/actions/runs?per_page=100"`.
   Save the full listing as `runs_listing.json`.
2. For each run, oldest first (the oldest expire first), save:
   - `<run_id>/run.json`, from `gh api repos/riperdy-tech/stock-screener/actions/runs/<id>`;
   - `<run_id>/jobs.json`, from `.../runs/<id>/jobs` (with `--paginate`);
   - `<run_id>/logs.zip`, from `.../runs/<id>/logs`. If this returns 404 or 410, record it as `LOGS_EXPIRED`. Any other
     error is recorded with its HTTP status. Do not retry a failure more than twice.
3. Make the script resumable: skip a run whose three files already exist and whose `logs.zip` is a valid zip. Keep
   calls at no more than about 2 per second.
4. Write `index.csv` with these columns: `run_id, workflow_name, event, head_sha, created_at, updated_at, conclusion,
   logs_status, logs_zip_bytes, logs_zip_sha256, runner_names` (`runner_names` comes from `jobs.json`).
5. Write `SHA256SUMS.txt` covering every saved file.
6. Scan the extracted log text for `ghp_`, `github_pat_`, `gho_`, `AKIA`, `-----BEGIN` and `sk-` followed by 20 or more
   alphanumerics. Report **only the count of matches and the run ids**, never the matched text.

## Acceptance tests (Claude will rerun them)

- The number of rows in `index.csv` equals `total_count` from the listing, and every row has a `logs_status`.
- Run 40608600897 is present, and its `logs.zip` SHA-256 equals `6cd4b3680b428afbf931e85507e89421499046da86fc63e904579ba99fa50d3d`.
- **Negative control:** one deliberately truncated copy of a zip (made in a temporary folder, then deleted) is reported
  as invalid by the script's validity check.
- `sha256sum -c SHA256SUMS.txt` passes.

## Budget and stop conditions

- At most 2 approaches.
- If rate limits stop progress, save what you have, report the last run id archived, and stop. Claude can resume it.
- If the archive passes 1 GB, stop and report the size.

## Deliverable

`stocks-workspace/docs/review_2026-09-22/rev23/orchestration/RR_L1.md`, following PLAN W.7: counts by `logs_status`,
the oldest run that still has logs, the total size, and the results of the secret-pattern scan.
