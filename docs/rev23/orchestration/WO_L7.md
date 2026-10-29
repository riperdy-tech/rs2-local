# WO_L7: Forward A0 ledger from witnessed runs

- **Milestone:** 3L, "Forward record" (the factor-only arm of 3S, started early).
- **Executor:** Claude.
- **Issued:** 2026-10-29. The rules below were fixed before any price was fetched.

## Goal

An append-only paper ledger of A0. A0 is the unchanged production screener: research_now, equal weight, monthly. Each
formation is tied to a GitHub run that passes the WO_L3 verifier. The ledger starts with the first month-end at which
the current dual-door engine was live. The first dual-door run was 35695758069, on 2026-09-22; before that the chain
ran the old `score_factors` engine, which is not A0.

## Rules (registered before any price was fetched)

- **Formation date T:** the last NYSE session of each month, from 2026-09-30 onward.
- **Fill session F:** the first NYSE session after T. Its open is 09:30 New York time.
- **Decision run:** the latest archived run whose log shows `score_factors_dual_door rc=0`, whose `updated_at` falls
  before F's open, and which passes the verifier (R1–R5). If the latest such run fails the verifier, stop and report.
  Do not fall back silently.
- **Book:** every ticker with `fct_band == research_now` in that run's output `factor_scores.json` blob, equal weight.
- **Entry and exit prices:**
  - Entry is the adjusted open at F. Exit is the adjusted open at the next formation's F.
  - The last formation is marked to the latest adjusted close and labelled `OPEN`.
  - Within a month, weights drift: buy and hold, so the period return is the mean of the name returns.
- **Missing entry bar:** the name is held as cash (return 0) and logged.
- **Missing exit bar:** the last available adjusted close is used and logged (`last_close` bound).
- **No silent reallocation.**
- **Turnover:** 0.5 × Σ|target − drifted|. The first formation enters from cash.
- **Costs:** turnover × round-trip cost, at 0, 20 and 60 bp.
- **Benchmark:** SPY, same windows, same price convention. An equal-weight universe benchmark is not computed and is
  reported as missing.
- **Two series:**
  - `A0` as published;
  - `A0_ex_operator` without SENEA, SENEB, MOV and MG (operator exclusion, 2026-10-28), equal weight over the rest.
- **Flags:**
  - non-common securities, for tickers whose `fct_veto_detail` / flags say so, or that look like preferreds;
  - the verifier's input issues (for example, no MRI snapshot in the tree).

## Prices

- Yahoo through `yfinance` (standing approval O5), `auto_adjust=True`.
- The raw download is saved with its SHA-256 and the UTC fetch time. That is an acquisition receipt, not proof of
  publication time.
- Prices are outcomes, observed after the decision. They do not need to be point-in-time.

## Scope

- **Create only** `stocks-workspace/scratch/rev23/m3l_forward/`.
- **No repository change. No broker. No KIS.**

## Acceptance

- Each formation row cites its run id, output commit, verifier verdict and book size.
- A rerun reproduces the stored formations exactly and appends only new ones. Mark-to-market snapshots are separate
  files.
- One recomputation by hand: one name's entry and current price, cross-checked against a second Yahoo request.
