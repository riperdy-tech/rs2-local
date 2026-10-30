# WO_S1: the equal-weight universe benchmark for the 3O/3S marks (builder brief, 2026-10-30)

**Goal:** SPEC_m3s_paper_trial.md §0, item 3. At each formation, the screener's investable universe as published at the
decision commit, equal weight, with the same fill sessions, exit sessions and cost scenarios as the arms. It is reported
in the engine's marks beside SPY.

**Read first:**
- `SPEC_m3s_paper_trial.md`, `SPEC_m3o_integration.md` §6–7 and `AUDIT_O1.md`;
- `scratch/rev23/m3o/m3o_engine.py`;
- `scratch/rev23/m3l_forward/forward_ledger.py` (`fetch_prices`, `period_return`, the completed-session rule).

**Where:** `scratch/rev23/m3o/`: a new `universe.py`, and edits to `m3o_engine.py` limited to the marks.

**Do not:**
- change any action line or rule (B1, Q1, A1S, E1);
- touch the GPU, edit any git repository, read `.secrets.json` or `.env*`, or delete files;
- use the network in tests. The one live fetch is for Claude to run later.

## Definition

- **Universe at T:** the rows of `public/data/stocks.json` at the formation's `output_commit`, read through `git show`.
  Find the screener's own investable-universe flag (read `stocks.json` fields and the scorer's eligibility rules). Use
  what the screener uses for "investable"; do not invent a filter.
  - Report the field used and the count.
  - SENEA, SENEB, MOV and MG are excluded, with a count.
- **Prices:** `universe.py fetch <formation_T>` downloads adjusted open and close (yfinance, chunked, with a receipt
  like forward_ledger's) for the universe over the period, to `m3o/universe_prices/`. A name with no bar is held as cash
  at 0% and counted, as in forward_ledger.
- **Return:** equal weight at the fill open, drifted to the exit (or the mark), with the same `period_return`
  arithmetic.
  - **Turnover:** one-way from drifted weights, between consecutive universe books.
  - **Costs:** 0, 20 and 60 bp.
- **Marks:** each group gets a series `U` with the same period and summary fields as the arms, plus
  `U_coverage` (names with prices / universe). The comparisons `F_minus_U` (gross and net 20 bp) are added.
- **The stop rule** still holds: the marks are recomputed and compared. A new universe price receipt is an input.

## Tests (fixtures only)

- The universe is read from a fixture `stocks.json` with the flag.
- Excluded names.
- A missing bar is held as cash.
- Equal-weight drift and turnover against a hand calculation.
- `F_minus_U`.
- A rerun appends nothing.
- The existing 54 engine tests still pass.

## Report

`RR_S1.md` in the orchestration folder: the universe field used and why, files, the test count, and the open choices.
