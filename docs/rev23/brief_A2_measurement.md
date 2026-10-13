# Coding brief: revision 23, A2 measurement and the data readiness of the January-2026 trial (no GPU, no model)

Written by the coordinator (Opus 5.5, main session) on 2026-10-06. Read `defect_census.md` and
`CROSS_CHECK_for_external_reviewers.md` in this folder first: they give the context. This brief covers only work
whose result does not depend on the external cross-check.

## Rules
- Work in a new detached worktree of rs2-local at its current HEAD, under
  `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\` (not %TEMP%).
  - The live tree `C:\Users\riper\stocks\rs2-local` is production; never edit it.
  - Never touch `cache/DEPTH_PAUSED`.
- **Out of bounds:**
  - no GPU and no model;
  - no deletion;
  - no edits to `.env*` or secrets;
  - no change to production behaviour (this is measurement only; new scripts and outputs go under
    `scratch/rev23/`).
- Read-only access to the screener data through the repository's peer resolver (`scripts/peer_paths.py` in
  stock-screener, `paths.py` in rs2-local). Never hard-code a sibling path.
- Use `is None`, not `or`, for numeric defaults: 0.0 is a value.
- **Never look at stock returns or valuations in this task.** A2 measures how fundamentals behave, not what pays.

## Task 1: A2, how fast margins and revenue trends revert (population base rates)

**Data:** the screener's `fundamentals_history.json` (~6,900 companies, fiscal years ~2014–2025, filed values).
Margin series:
- use the same series and the same functions as `tools/throughcycle_record.py` (`operating_margin`, `pretax_margin`
  and the fallback rule `analyse` uses);
- classify each company-year's trailing 8-year margin series as **cyclical** or **secular** with the record's own
  crossing rule (`OM_SWING_CROSSINGS`).

**Measure:**
1. **Margin reversion.**
   - For every company-year t that has at least 8 prior years of the series, compute:
     - **d_t**, the margin at t minus the median of years t−7..t;
     - for k = 1..7 where available, **d_{t+k}**, measured against the same median (fixed at t).
   - Report the median and interquartile range of d_{t+k}/d_t, by k, split by:
     - cyclical or secular;
     - sign of d_t;
     - |d_t| bucket (< 2 points, 2–5 points, > 5 points).
   - Exclude |d_t| below 0.5 points, where the ratio is unstable, and report how many rows that excluded.
2. **Revenue-decline persistence.**
   - For company-years whose trailing 8-year revenue trend (Theil–Sen slope of log revenue) is negative, report the
     distribution of the revenue growth rate over the next 1..7 years. Bucket by the trailing trend: 0 to −2%,
     −2 to −5%, below −5%.
3. **Revenue-growth decay.**
   - Check what `growth_persistence.py` and `base_rates.py` already provide. Report whether they give, for a company
     growing at rate g in year t, the distribution of growth in years t+1..t+10 by size bucket.
   - If they do not go beyond 5 years, extend the same method to 10 years and report it.
4. **Point-in-time versions:** produce every table also as measured on fiscal years ≤ 2016 only, and on fiscal years
   ≤ 2024 only. The backtest and the January-2026 trial must use tables built only from data before their dates.

**Report:**
- the tables, as JSON plus a readable `A2_tables.md`;
- row counts per cell;
- every exclusion counted;
- any cell with fewer than 50 rows flagged.

No rule is chosen in this task. The coordinator reads the tables and writes the rule.

## Task 2: data readiness for a point-in-time trial as of 2026-01-02

Check, and report with counts, whether `capability_test.build_pack(T, include_research=False, asof="2026-01-02")`
can be built for the current nomination universe. Use the stocks of `queue.json` in
`C:\Users\riper\stocks\stocks-workspace\scratch\baseline-2026-10\` (the `book` list, read-only).

For each stock:
1. whether the pack builds without error;
2. whether its newest filing used is dated on or before 2026-01-02 (no leakage);
3. whether a 2026-01-02 price, or the last trading day before it, exists;
4. which sections say "not available", and why (consensus, primary sources, news, the reference);
5. whether a total-return price, dividends included, exists for 2026-01-02 → the latest date, for the stock and for
   the S&P 500 (SPY). Name the source used.

Cap the run at the whole list, one stock at a time. Respect SEC's 10 requests per second and use the existing user
agent and caches.

- **Report:** counts per item; the list of stocks that fail and why; every place where the point-in-time pack could
  leak information dated after 2026-01-02.
- **Leakage check:** grep each pack for any date later than 2026-01-02 and report every hit.

## Deliverable
`C:\Users\riper\stocks\stocks-workspace\scratch\rev23\REPORT_A2_readiness.md`:
- what was run;
- the outputs;
- deviations ("none" only if true);
- questions.

Run `date '+%H:%M'` before writing any timestamp.
