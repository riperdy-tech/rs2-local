# WO_O1: the 3O paper decision engine (builder brief, 2026-10-29)

**Goal:** `m3o_engine.py`, which applies SPEC_m3o_integration.md and PREREG_m3o.json to recorded inputs and writes
the append-only ledger of SPEC_m3o §6. It also builds the F-A1 book (SPEC_m3o §2, WO_O4 folded in).

**Read first (same folder unless named):** `SPEC_m3o_integration.md`, `PREREG_m3o.json`; `RR_L7.md` and
`stocks-workspace/scratch/rev23/m3l_forward/forward_ledger.py` (A0 formations, prices, the session calendar, the
append-only stop rule); `stocks-workspace/scratch/rev23/m3n/baseline_b.py`; `PROTOCOL_factor_ai_m2_2026-10-23.md` §3
and `stocks-workspace/scratch/baselineA/m3_quarterly.py` + `m3_test_quarterly.py` (the frozen A1 book logic: port
it, do not change it); `rs2-local` qwen_c's `analysis.json` / `manifest.json` shapes (read
`stocks-workspace/scratch/rev23/wt-m3n-v6/qwen_c/runner.py` and `contract.py`, read-only).

**Where:** new folder `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3o\` (`m3o_engine.py`, `tests/`,
`fixtures/`). Nothing else is edited. `m3l_forward/` is read only.

**Do not:** use the network; touch the GPU or Ollama; edit any git repository; read or print `.secrets.json` or
`.env*`; open any file under `scratch/rev23/m3n/n5/runs*`, `m3n/n6/` or a qwen_c `cache/*/runs/` directory (model output
is out of scope: build and test on fixtures you write).

## Inputs the engine reads

1. `m3l_forward/formations.jsonl` (A0 formations) and `m3l_forward/prices/*.csv` (the latest fetch receipt).
2. The A0 run's `public/data/factor_scores.json` at the formation's `output_commit`, through
   `git -C C:\Users\riper\stocks\stock-screener show <commit>:public/data/factor_scores.json` (ranks, doors, band,
   flags; find the fields A1 needs and say which you used).
3. Per formation, a map `m3o/inputs/formation_<T>.json` written by WO_O2:
   `{"formation_T", "decision_time_utc", "builder_version", "names": {ticker: {"packet": path, "run_dir": path or null,
   "attempts": int}}}`. The engine reads `run_dir/manifest.json` and `run_dir/analysis.json`, checks
   `analysis_sha256` in the manifest against the file, and refuses a mismatch.
4. B hits: `baseline_b.py`'s functions on each name's packet (import it from its folder, as the 3N tools do).

## What it computes

- Per formation and name: the `factor`, `qwen`, `verification` and `actions` lines of SPEC_m3o §6, for arms F, FB, FQ
  and F-A1, with rule ids `B1`, `Q1`, `A1S`, `E1`, and the labels of PREREG `labels`.
- Q1 exactly as PREREG: critical event types, `support == "supported"`, `announced_pending` or `occurred` within 180
  days before T, missing `occurred_on` acts and is flagged `undated`. A non-date `occurred_on` (for example
  "not stated") counts as missing. An unsupported critical claim is logged and does not act.
- B1: a hit counts only if its item's SEC acceptance is within 180 days before T. Find where the packet records an
  item's acceptance and say so; if an item has none, the hit does not act and is logged `b_hit_undated`.
- `analysis_pending` uses the manifest's `finished_at` (a self-claim clock: label it so) against the fill open.
- Marks: per arm, period and cumulative gross/net (0/20/60 bp round trip), one-way turnover from drifted pre-trade
  weights, cost drag, cash drag (pending, incomplete), maximum drawdown, SPY. The F series must equal
  forward_ledger.py's output for the same formations and prices; a test shows it.
- Stop rule: if a stored ledger line differs from its recomputation, stop with the line named (as forward_ledger.py).

## Tests (fixtures only; `"C:\Program Files\Python312\python.exe" -m pytest tests -q` from `m3o/`)

Restricted new entry is redistributed; restricted incumbent is held with `pending_reunderwriting`; exit only when
A0 drops a name; the 180-day boundary (179, 180, 181 days) for Q1 and B1; `undated`; an unsupported critical claim
does not act; a non-critical event type does not act; pending slot is cash, then entered at the first open after
`finished_at`; incomplete slot is cash to the next formation; operator-excluded tickers in FB/FQ/F-A1; a 0.0 return
and a 0.0 weight are values; a missing price is held as cash and flagged `no_price_series`; an analysis sha mismatch is
refused; F equals forward_ledger.py; A1: quarterly-only trades, drift in a skipped month, rank 80 vs 81 retention,
Door 3 rules as m3_quarterly, capacity = A0's; a rerun appends nothing; a changed stored line stops.

## Report

`RR_O1.md` in this folder: files, the factor_scores fields used, where packet acceptance was found, every choice the
brief did not settle, and the test count. Commit nothing (the folder is not a git repository).

## Amendment, 2026-10-29 (CROSS_CHECK_O_RULINGS; sent to the builder by message)

- **F-A1 is dropped.** Keep book accounting that can rebalance quarterly, carry drifted weights, cash, missing prices and
  costs, tested on fixtures. Run no A1 book and port no rank-80 rule.
- **Q1 `occurred`:** a parsed date that is printed in a cited item, or `undated` / `date_unsupported`. Both of those are
  `escalation` and do not act.
- **`FQ_decisions_only`** analysis series.
- **Start:** FB, FQ and the matched F start at 2026-10-30 from cash; a `retrospective` map is a separate one-period
  series.
- **Code revisions:** the qwen_c commit and builder_code on every Qwen-derived line, plus the engine's sha256.
- **B1** is called a text rule.
- **`partial_analysis`** flag.
- **The map's per-name `state` field** classifies pending versus incomplete.
