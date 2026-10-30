# WO_S2: regime tags, change-register segments and the monthly operating report (builder brief, 2026-10-30)

**Goal:** SPEC_m3s_paper_trial.md §0, items 5, 6 and 7 (WO_S2 and WO_S3 there): one command,
`python m3s_report.py [--asof YYYY-MM-DD]`, that writes `m3s/reports/<asof>.md` and `.json`.

**Read first:**
- `SPEC_m3s_paper_trial.md`, `CHANGE_REGISTER.md`, `SPEC_m3o_integration.md` §6–7, `AUDIT_O1.md`, `AUDIT_S1.md` and
  `SPEC_m3p_monitoring.md` §6–7;
- `scratch/rev23/m3o/m3o_engine.py` (the marks format);
- `scratch/rev23/m3p/m3p_monitor.py` (the journal format and `report()`).

**Where:** a new folder, `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3s\`. Everything else is read-only.

**Do not:**
- use the network in tests. Regime data, below, is read from a local file that the report's `fetch` subcommand
  downloads; do not run that fetch yourself.
- touch the GPU, edit any git repository, read `.secrets.json` or `.env*`, or delete files.

## The report, in this order

1. **Operating period:** formations, fills and marks covered; outages from logs (the engine's stop messages, qwen_c
   runs `failed` or `crashed`, scheduled-task failures if a log exists); data freshness (price receipt dates, ledger
   `current_date`).
2. **Version segments:** from `CHANGE_REGISTER.md` (parse its table). Each series is reported per segment between the
   rows' "first formation" values.
3. **The series:** F, FB, FQ, FQ_decisions_only, F_ex_operator and U (when present), from the newest marks file. Gross
   and net returns at 0/20/60 bp, turnover, cost drag, cash drag, maximum drawdown, and SPY and U excess, per period and
   cumulative.
4. **Regime tags per period:**
   - SPY return sign;
   - VIX quartile at the fill: the quartile boundaries of FRED `VIXCLS` over the prior 5 years, read from
     `m3s/regime/vixcls.csv`, which `m3s_report.py fetch` downloads from `https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS`;
   - the count of 3P events in the period, from the journal's `resolved` lines with an `event_found` verdict.

   Report by tag only when a tag has at least 3 periods; otherwise "too few".
5. **Qwen operations:** per formation, the analyses complete, pending, incomplete and `partial_analysis`, the
   T-to-completion latency (median and max) and GPU hours (sum of run durations), from the engine's qwen lines and the
   run manifests' timestamps (read-only).
6. **Monitoring:** `m3p_monitor.report()` output (coverage, queue age), plus the journal's lifecycle counts.
7. **The minimum record** (SPEC_m3s §0, item 8): monthly formations and periods with SPY ≤ −5%. Below 12 formations
   or 0 down periods, the report says **"insufficient duration: no skill statement"** in its first line.

## Tests (fixtures only)

- Each section on fixture marks, journal, register and VIX files.
- The "too few" rule.
- The insufficient-duration first line.
- A segment split at a register row.
- Missing inputs are reported as missing, never as zero.

## Report

`RR_S2.md` in the orchestration folder: the files, the test count from one final run, and the open choices.
