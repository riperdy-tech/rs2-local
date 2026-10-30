# RR_S2: regime tags, change-register segments and the monthly operating report (builder report, 2026-10-30)

**Status:** built and tested on fixtures. No network, no GPU, no git change, no ledger, `inputs/` or other repository file touched.
The `fetch` subcommand was not run, and `m3s_report.py` was not run on live inputs (the default qwen_c run root holds `runs/`, which this
work order did not open). `m3s/regime/vixcls.csv` does not exist yet: until `python m3s_report.py fetch` is run, every VIX quartile is
reported as missing.

## Files (all new, under `scratch/rev23/m3s/`)

- `m3s_report.py`: `python m3s_report.py [--asof YYYY-MM-DD]` writes `m3s/reports/<asof>.md` and `.json`; `python m3s_report.py fetch`
  downloads FRED `VIXCLS` (the only network use).
- `tests/conftest.py` (blocks the network), `tests/helpers.py` (fixture builders; marks summaries come from `m3o_engine.summarize`, so the
  marks format is the engine's own), `tests/test_report.py`.

## Tests

`python -m pytest tests -q -p no:cacheprovider` in `m3s/`: **35 passed**, one final run. They cover: each of the seven sections on fixture
marks, journal, register and VIX files; the parse of the real `CHANGE_REGISTER.md`; a segment split at a register row (hand-computed
cumulative); the "too few" rule (2 periods too few, 3 reported, the open period never counted); the insufficient-duration first line (in the
md and the json) and the met case; missing inputs reported as missing (no marks, no U, no journal, no state, no VIX, an unreadable manifest,
a missing field); `0.0` kept as a value (cost drag at 0 bp, SPY exactly 0.0 is `flat`, 0 events with a journal); the fetch with an injected
downloader; and an end-to-end `main()` that refuses to overwrite.

## How each section is built

1. **Operating period.** Formations, fills and marks from the newest marks file on or before `--asof`, and `ledger/formations.jsonl`. Outages:
   a scan of the runner logs (`m3o_run/o2/runner.out` and `.err` by default, `--log` to replace) for `STOP:`, `GPU busy`, `ollama is not
   reachable`, `another runner holds the lock`, tracebacks and non-zero exit codes; and the qwen_c run root (`ledger.jsonl` statuses plus
   `m3p_monitor.read_ledger`'s crash rule). Freshness: the marks' price date and receipt, the universe receipts, and each `current_date` of a
   `paper_ledgers.json`.
2. **Version segments.** The register table is parsed; the first ISO date of the "First formation it applies to" cell starts a segment. Each
   series is reported per segment (periods, cumulative gross, net 20 bp, SPY and excess, maximum drawdown).
3. **The series.** F, FB, FQ, FQ_decisions_only, F_ex_operator, U: gross and net at 0/20/60 bp, turnover, cost drag at 0/20/60, cash drag
   (pending, incomplete), maximum drawdown, SPY and U excess, per period and cumulative.
4. **Regime tags.** SPY sign, VIX quartile at the fill, 3P event count; reported by tag only with at least 3 closed periods.
5. **Qwen operations.** Per formation from `ledger/qwen.jsonl` and the run manifests.
6. **Monitoring.** `m3p_monitor.Monitor.report()` plus the journal's lifecycle counts.
7. **Minimum record.** Formations and SPY-down periods; the first line.

## Open choices (for the auditor)

1. **VIX quartile definition.** The value is the last `VIXCLS` observation strictly before the fill day. The boundaries are the 25th, 50th and
   75th percentiles (linear, `statistics.quantiles` inclusive) of observations in `[fill - 5 years, fill)`. Q1 is value <= the first
   boundary, and so on; Q4 is above the third. It is missing, with the reason, if there is no file, no observation, the last one is more than 7
   days old, or the window has fewer than 250 observations. The 7 days and 250 are design values.
2. **Event tag.** The spec says "the count of 3P events in the period". The count is the number of distinct (ticker, run) `resolved` lines
   with an `event_found` verdict (the `name_state`, or `q1.verdict`), dated by the run's `decision_time_utc` (else `finished_at`, else the line
   time), from the fill day to the day before the exit. The tag for "by tag" tables is two buckets, `0` and `>=1`. A missing journal, or one that
   begins after the period ends, gives a missing count, never 0. A journal that begins mid-period gives a count with a note.
3. **Open periods.** An open (marked, not exited) period is tagged and listed but is never counted in the by-tag means or in the SPY-down
   count, because its return is partial. It does count as a formation. Open choice for the auditor: a stricter reading would count closed
   periods only for the 12.
4. **Minimum record.** Formations are the `main` group's periods (the retrospective group is never counted or pooled with `main`). Down
   periods are closed periods with SPY <= -5% (exactly -5% counts). The first line is "insufficient duration: no skill statement" followed by
   the counts; with no marks file the formation count is missing and the first line still says insufficient duration, with the reason. When the
   record is met the first line says so and still states that the report makes no skill statement.
5. **Segments.** Every register row with a parsable date starts a segment for every series, whatever its scope. A row's scope text in
   parentheses, such as `(FQ)`, is shown but does not restrict the split. A row with no ISO date ("next formation") is listed as unparsed and
   starts no segment. The segment before the first row is labelled "before <date>". Segment figures are compounded from the period figures.
6. **"Ledger `current_date`".** The brief does not say which ledger. The 3O and A0 ledgers have no such field; `current_date` is a field of
   the screener's `paper_ledgers.json`. The report reads each ledger's `current_date` from that file (default
   `stock-screener/public/data/paper_ledgers.json`, `--paper-ledgers` to change it) and shows its age in days. The working-tree copy is
   currently dated 2026-09-22, so it will show old ledgers; the committed `origin/main` copy is newer and is not read (no git).
7. **GPU hours.** The sum of `finished_at - started_at` over the manifests that the ledger's qwen lines point at, deduplicated by run id. A
   run whose manifest is unreadable counts under "runs not timed"; if none is readable the figure is missing, not 0. It does not include a
   failed attempt that no qwen line names. `finished_at` and `started_at` are the runner's self-claims, and the latency column says so.
8. **State clock.** The monitor report is the state files as they are at run time, read at the end of the `--asof` day; only journal lines up to
   that day are counted. The marks used are the newest file on or before `--asof` (no look-ahead).
9. **No overwrite.** A report for an `--asof` that already has a file is refused unless `--overwrite` is given.
10. **Section isolation.** A section that raises is recorded in `errors` (json and the top of the md) and the other sections still print; the
    command then exits 1.
11. **Log patterns.** The log lines carry no clock, so a hit is dated by its own leading ISO date if it has one, else by the file's modification
    date, and labelled so. The patterns are in `LOG_PATTERNS`. No scheduled-task history is read (only logs that exist).
12. **Import of the monitor.** `m3p_monitor` is imported lazily (it imports `m3o_engine` and `baseline_b`). `sys.dont_write_bytecode` is set so
    no `__pycache__` is written in the sibling folders.

## Not done

- A live run on real inputs: no 3O ledger exists yet (`m3o/ledger/` is absent), so there are no marks to report.
- The spread-sensitivity row (SPEC_m3s item 4) and the GitHub witness (WO_S4) are outside this work order.
- No tests of the real qwen_c run root or real logs (fixtures only, by instruction).
