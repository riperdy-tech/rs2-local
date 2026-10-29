# WO_L8: Impact measurement of ChatGPT's unmerged build_fundamentals_history change

- **Milestone:** 3L follow-up.
- **Purpose:** inform a ruling; this work order makes no change.
- **Executor:** Claude.
- **Issued:** 2026-10-29.

## Goal

Commit `f99cdda5` on `review-2026-10/m3l-mri-read-once` changes the **default output** of
`build_fundamentals_history.py`: an instant-tag cell with no raw candidate near the reference date becomes null (the
CMRE case). Measure what it changes:

1. the cells that change, by field and by ticker;
2. the factor stage, meaning which nominations and research_now names change.

## Method (read-only; outputs only in scratch)

| Side | Code | Data |
|---|---|---|
| **A** | `scripts/` at `3094fc70` (production) | `stocks.json` and `cik_map.json` from `origin/main` `e41974be`; `companyfacts.zip` at `stock-screener/companyfacts.zip` (local copy dated 2026-08-07, the same for both sides) |
| **B** | `scripts/` at the tip of `review-2026-10/m3l-mri-read-once` | as A |

- Run `build_fundamentals_history.py --zip <zip> --data-dir <scratch>/{A,B}` on each side.
- Compare the two `fundamentals_history.json` files cell by cell.
- **Factor stage:** run the scorer at `3094` on the `e41974be` inputs twice, replacing only `fundamentals_history.json`
  (and the battery, if it differs) with A and then with B. Then diff `nominated_tickers`, research_now and the vetoes.

## Scope

Create only `stocks-workspace/scratch/rev23/m3l_fh_impact/`. No repository change and no network (the CIK map is
supplied).

## Stop condition

If a full build takes longer than about 90 minutes, measure a random 1,000-ticker subset with a fixed seed, and say so.
