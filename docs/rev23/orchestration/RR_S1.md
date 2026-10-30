# RR_S1: the equal-weight universe benchmark U (builder report, 2026-10-30)

**Status:** built and tested on fixtures. No network, no GPU, no git change, no ledger or `inputs/` file touched. The live fetch has
not been run.

## Files

- `scratch/rev23/m3o/universe.py` (new): the universe record, the chunked yfinance fetch with a receipt, the loaders.
- `scratch/rev23/m3o/m3o_engine.py`: marks section only (`import universe`, `universe_period()`, the U block in `run()`, the marks
  comparison, a `--universe-dir` option). No action line, plan or rule changed.
- `scratch/rev23/m3o/tests/test_universe.py` (new): 19 tests. `tests/world.py` and the checked-in fixtures are unchanged.

## The universe field, and why

`stocks.json` carries **no investability flag**. Its `status` (Pass/Fail) is the legacy Tier 1 screen: 4 Pass of 6,966 rows at the
2026-09-30 commit, so it is not "investable". The screener's own eligibility is decided by the scorer
(`score_factors_dual_door.py`): not `NOT_TRADABLE`, a Tier 1 hygiene survivor, market cap >= 300M, price >= 3, ADV >= 250K, no
shell, forensic, insolvency, no-history or chronic-loss veto. It writes the verdict to `factor_scores.json` as `fct_veto` (null =
eligible; the file's `scored_count` is the number of nulls).

**Field used: `fct_veto is null` in `factor_scores.json` at the formation's `output_commit`, joined to the symbols (rows) of
`stocks.json` at the same commit.** Both come through `git show`. A ticker with no `fct_veto` key is not treated as eligible. This
is the same file the engine already reads for the A0 book, so no new filter is invented.

**2026-09-30 formation (commit `b9497efd`), read from the real blobs (git read only, nothing written):** stocks.json rows 6,966;
eligible 3,051 (all are in stocks.json); operator-excluded SENEA, SENEB, MOV, MG = 4; **universe 3,047**. 58 of the 60 A0 names
are in it (the other 2 are the excluded ones).

## Design, in short

- `universe.py fetch <T>` writes `universe_prices/universe_<T>.json` (ticker list, field, counts, sha256 of both blobs; written once,
  a differing rewrite raises) and `universe_<T>_<fetch>.csv` + `.receipt.json` (window = fill - 3 days to the last completed
  session, forward_ledger's rule; chunks of 200; the receipt lists names without bars).
- The engine reads those per formation. U is an equal-weight book on the universe, run through the engine's own `arm_step` /
  `monthly_step` / `period_record`: fill at the adjusted open, drift, exit at the next formation's fill open (open period marked at the
  last close), `fl.period_return` arithmetic, one-way turnover from drifted weights between consecutive universe books, costs 0/20/60.
  A name with no bar at the fill is held at 0% and counted (`n_with_price_at_fill`, `no_price_series`).
- Marks, per group: `series.U` (periods and summary as the arms), `U_coverage` (per period: names with a fill bar / universe),
  `comparisons.F_minus_U_gross` and `F_minus_U_net_20bp` (cumulative). Top level: `universe_records` (sha256, counts, field per T)
  and `universe_receipts`.
- Stop rule: the U values and `universe_records` are compared within 1e-6 like the other marks. `universe_receipts` is excluded from
  the comparison, as `price_receipt` is, so a new fetch of the same data does not stop; changed prices do.

## Tests

`python -m pytest tests -q` in `m3o/`: **73 passed** (the 54 existing + 19 new), one final run. They cover: the universe from a
fixture stocks.json with the flag; excluded names and counts; no-flag, vetoed and not-in-stocks names; a missing bar held as cash;
0.0 as a value; equal-weight drift and turnover against a hand calculation (three periods, 0/20/60 bp); `F_minus_U`; a rerun
appends nothing; a new receipt with the same prices does not stop and changed prices do; U does not change any action line or other
series; chunked fetch and receipt through an injected downloader (no network); the fetch command with a patched `git show`.

## Open choices (for the auditor)

1. **The universe field** (above). Alternative readings: all 6,966 rows (includes 374 NOT_TRADABLE and 3,278 hygiene failures, not
   investable), or `fct_band != vetoed` (identical to the null `fct_veto` test in the data). The `non_common_flagged_by_screener` flag
   on some A0 names is not used to trim U: the screener does not exclude those names from its universe.
2. **U is unavailable for a group, as a whole, if any formation of the group lacks a universe record or price receipt.** Its
   drift chain would be broken, so no partial U is shown. The marks then carry `U_unavailable` {formation, reason}.
3. **Each formation has its own price fetch.** Period i uses formation i's universe and its latest fetch. To value an earlier
   formation's exit at the next fill open, **re-run `fetch` for every formation of the group after each new fill** (a stale fetch
   gives `missing_exit_bar_last_close` events in `no_price_series`).
4. **U's last price date can differ from F's** (the marks file is named for F's). It is not hidden: `groups[g].U_asof_mismatch`
   shows both dates, and `F_minus_U` is still computed.
5. **Coverage counts the fill bar only.** A name with a fill bar but no exit bar uses its last close (as in forward_ledger), flagged
   in `no_price_series`.
6. **A marks file already stored for an as-of date, without U, stops the engine when U data is later added** (append-only). Fetch the
   universe before the first engine run for that formation.
7. **No U lines in the ledger files**: the brief limits the change to the marks.
8. **Run with the normal interpreter, not `python -I`**: `forward_ledger` needs the user-site `tzdata`, and `-I` hides it. (A
   pre-existing property of `forward_ledger.py`, not changed.)

## Not done

- The live fetch (Claude runs it: `python universe.py fetch 2026-09-30`, then `2026-10-30` once its fill has completed).
  About 3,047 names, 16 chunks; memory is one chunk of rows at a time plus the full row list (a few tens of MB).
- The spread-sensitivity row (the second half of WO_S1 in SPEC_m3s section 2) is outside this work order's text and was not built.
- A real-data end-to-end run of the engine with U (it needs the fetched prices).
