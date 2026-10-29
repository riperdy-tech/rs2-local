# RR_L7: Forward A0 ledger, started 2026-10-29

**Result:** DONE. The machinery is built, and the first formation is recorded. It is still open; it closes at the
2026-11-02 open.

## Files

`stocks-workspace/scratch/rev23/m3l_forward/`:

- `forward_ledger.py`;
- `formations.jsonl` (append-only);
- `prices/<fetch>.csv` plus a receipt;
- `mtm_2026-10-27.json`;
- `prices/superseded/`: the first fetch, which contained intraday 10-28 prices (see "Defect found" below).

## Why the ledger starts at 2026-09-30

The archive scan of all 648 saved logs shows which engine each run used:

- the old `score_factors` engine ran until 2026-09-22 00:27Z (last run 35670131444);
- the dual-door engine has run from 2026-09-22 07:13Z (first run 35695758069).

A0 is the dual-door engine, so the first A0 month-end is 2026-09-30. The 09-01 decision came from the old engine. The
10-01 price refresh (36796400711) skipped scoring because the price overlay was aborted, so the 09-30 decision is the
data fetch at 18:21Z.

## Formation 2026-09-30

| Item | Value |
|---|---|
| Decision run | 36741386328 (Scheduled Data Fetch, two jobs). `updated_at` 18:21:02Z, which is before the 10-01 open. |
| Commits | `scoring_base` `2302a5d`, pushed by this run's fetch job. Output `b9497ef`. |
| Verifier | **PASS**: R1–R5, and the base is `pushed_by_this_run`. 163 nominees, all `PIT_PROSPECTIVE`. |
| Momentum | **preserved**: the data-fetch workflow commits it. |
| Input issue | **No MRI snapshot in the tree** on 09-30, so the scorer fell back to neutral quotas and the constant discount rate. Recorded. |
| Book | 60 research_now names, equal weight, entered at the 10-01 adjusted open |

## Marked at the 10-27 close (OPEN position; about four weeks; no inference possible)

| Series | n | Gross | Net at 20 bp | Note |
|---|---|---|---|---|
| A0 | 60 | +1.23% | +1.13% | One-way turnover 0.50, entering from cash |
| A0 without SENEA/SENEB | 58 | +1.66% | +1.56% | |
| SPY | — | +0.69% | | |

## Events and findings

- **TBPH:** Yahoo returns no data for 2026-09-28 to 10-28 ("possibly delisted"). Under the registered rule it is held
  as cash (0%). Its true path is unknown. If TBPH was taken over, the cash treatment understates its return; if it was
  delisted for distress, it overstates it. It needs an event source (3R), not a guess.
- **Screener defect in the 09-30 book (since fixed):** 9 of its 60 names are not common stocks:
  - four American Financial Group debentures (AFGB, AFGC, AFGD, AFGE);
  - five bank depositary or preferred issues (FCNCN, NTRSO, TCBIO, UMBFO, WTFCN).

  All carry a market cap of 0 in `stocks.json`. They averaged −3.0% against +1.98% for the other 51. The 10-28 book
  (62 names) contains none of them. A0 records what was published, so they stay in the ledger, with this note.
- **Defect found in the audit (fixed):** the first price fetch ran at 16:23Z on 10-28, during New York trading hours,
  so its "10-28 close" was intraday. The ledger now marks only completed sessions, after 16:15 New York time. The
  first fetch and its mark were superseded, and they are kept in `prices/superseded/`.

## Acceptance

| Test | Result |
|---|---|
| The formation cites run, commit, verifier and book | PASS |
| A rerun reproduced the stored formation exactly and appended nothing | PASS |
| Hand cross-check against a second Yahoo request: AMD 10-01 adjusted open 612.70 in both | PASS. The 10-28 values differed because 10-28 was intraday. That is the defect above. |

## Running it

- Rerun `forward_ledger.py` after each month-end fill: the next fill is 2026-11-02, which closes October and opens
  November. Interim marks can be run any day.
- A scheduled task is the operator's choice, because it is a standing configuration.
