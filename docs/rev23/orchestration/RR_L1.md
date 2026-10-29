# RR_L1: GitHub Actions witness archive

**Result:** DONE.

## Changes

- Archive: `stocks-workspace/scratch/rev23/gh_witness_archive/` (68 MB). Per run it holds `run.json`, `jobs.json`,
  `logs.zip` and `logs_status.json`, plus `index.csv`, `runs_listing.json` and `SHA256SUMS.txt`. No repository was
  changed.
- **First pass, ChatGPT** (2026-10-29 00:00–00:14 KST): 74 saved, 284 expired, 2 invalid zips and 573 pending. It
  stopped there.
- **Second pass, Claude** (resumable, same folder format):
  - It retried the invalid zips and the pending runs.
  - It labels a run that has not finished as `NOT_COMPLETED`, not `LOGS_EXPIRED`.
  - It excludes its own stdout (`run_log.txt`) from the checksums.
- ChatGPT's original `archive_runs.py` was overwritten without being read first, so it is lost. The current script is
  Claude's.

## Results

| Measure | Value |
|---|---|
| Runs listed (`total_count`) | 933 |
| Index rows | 933 |
| `SAVED` | 648, created 2026-07-30T16:07:54Z to 2026-10-28T00:24:51Z |
| `LOGS_EXPIRED` | 284 (HTTP 410), all older than the saved range |
| `NOT_COMPLETED` | 1: run 40707381769, a Scheduled Data Fetch dispatched 2026-10-28T14:35Z. Its fetch job is `in_progress` on the self-hosted runner `rs2-pc`. |
| Runner types among saved runs | 636 GitHub-hosted, 12 self-hosted |
| Secret-pattern scan (`ghp_`, `github_pat_`, `gho_`, `AKIA`, `-----BEGIN`, `sk-`+20) | 0 matches in 648 log archives |

## Acceptance tests

| Test | Result |
|---|---|
| Rows equal `total_count` (933 = 933), and every row has a status | PASS |
| Run 40608600897 `logs.zip` SHA-256 = `6cd4b368…d50d3d` | PASS. It matches the two earlier downloads. |
| A truncated copy of a zip is reported invalid; the original is reported valid | PASS |
| `sha256sum -c SHA256SUMS.txt` | PASS, after the fix above. The first pass failed only on `run_log.txt`. |

## Not verified

- The runner-type split counts a run as self-hosted when its runner name does not start with "GitHub Actions".
  `jobs.json` labels are the authoritative field.
- Log retention is inferred, not confirmed: the oldest log still available is from 2026-07-30, about 90 days back.

## Requests

- **Operator:** none.
- **Recurring task:** this archive should be refreshed weekly, because logs keep expiring. Running the script again
  appends only the new runs.
