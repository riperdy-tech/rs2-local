# REQUEST — single-ticker fundamentals refresh from live SEC companyfacts

From: RS2 Local session, 2026-08-21. Self-contained. Follow-up to
`SCREENER_EXTRACTOR_PACKAGE_20260820.md` (CH-1..9, shipped as `fc8acbd05a`).

## The gap this closes

The fundamentals files rebuild weekly (Sunday cron, fresh bulk `companyfacts.zip`). A company
filing a 10-Q mid-week therefore sits up to 6 days in SEC's data but not in ours. RS2's depth
pipeline detects the filing the same day (SEC submissions feed, polled daily per CIK) and now
**defers** the re-run until the tables catch up — correct but up to ~7 days late. This request is
the same-day-AND-correct version.

## What is requested

A single-ticker refresh mode in `scripts/build_fundamentals_history.py` (or a thin sibling
script) that:

1. **Fetches one company live**: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
   — identical structure to one member of the bulk zip, always current, a few hundred KB.
   Declared User-Agent, nothing else special.
2. **Runs the existing extraction for that one ticker** — `extract_history` and the TTM /
   quarterly / battery builders, exactly as the weekly build does. No new extraction logic; the
   whole point is that the numbers are byte-identical to what the next Sunday build would
   produce for that ticker from the same facts.
3. **Patches that ticker's rows in place** in `fundamentals_history.json`, `fundamentals_ttm.json`,
   `fundamentals_quarterly.json`, `fundamentals_battery.json` — atomically (tmp + replace), all
   other tickers byte-untouched.
4. **CLI**: something like
   `python scripts/build_fundamentals_history.py --refresh-one TICKER`
   Exit 0 = rows updated; non-zero = fetch/extract failure, files untouched.

The `--tickers`/`--limit` SUBSET machinery already isolates single-ticker extraction — the
missing halves are the live per-CIK fetch (instead of the local zip) and the in-place patch
(instead of writing `*.SUBSET.json`).

## Constraints that matter

- **LOCAL-ONLY mutation. Never commit the patched files.** The provenance rule stands: data
  files on git come only from the cloud's own fresh-zip rebuild. This mode exists so a LOCAL
  consumer (RS2's depth pipeline) can run same-day; Sunday's rebuild then reproduces the same
  rows from the same facts and the patch dissolves.
- **Determinism check**: after a patch, the ticker's rows must equal what a full rebuild from a
  fresh zip would produce for that ticker. Cheap acceptance test: run `--refresh-one` on a name
  with NO new filing — every file must come out byte-identical to before.
- **Provenance fields (CH-6) must ride along** — the patched rows need the same `_provenance`
  treatment as bulk-built rows, or the basis-break detector goes blind on exactly the
  freshest names.
- SEC etiquette: one request per invocation, declared UA. RS2 triggers at most a handful of
  names per day.

## How RS2 will use it

`depth_pipeline.py` pre-step, only when the defer gate reports `filing_pending`:
run `--refresh-one T`, on exit 0 proceed with the analysis same-day; on failure, leave the
defer gate in place (correct-but-later). RS2 wires this on its side once the flag exists.
