# 07. Open items and next steps

## 1. The immediate next step
Get the operator's strategic decision (file 02 §4). Until then, do only housekeeping (§4 below). Do not start GPU runs, do not touch the holdout.

## 2. Next steps per path (as the coordinator would do them)

### Path 1: cheap factor fund (deliberate)
1. Rewrite `SPEC_factor_led_v1.md` → v2 in light of baseline A: the screener is a **factor tilt**, not a stock picker; reframe it as "a low-cost
   factor exposure" with explicit expectations (roughly market-like, factor-premium-dependent returns).
2. Design a **low-turnover variant** (quarterly rebalance, wider bands, buffer rules) and measure it with the baseline-A pipeline
   (`scratch/baselineA/scripts/s5_backtest.py`), registering bars first (e.g. net-of-cost excess vs universe and vs SPY, drawdown, turnover).
3. Define the **verified hard-stop list** (spec §2.1: pending fixed-price acquisition, going concern, delisting notice, restatement, halt,
   bankruptcy, dilutive reverse split) and how code confirms each from filings (8-K items, 6-K, filing index; `sec_guidance.py`/`sec_primary.py` exist).
4. Paper book with the new rules; exits deterministic (spec §4).

### Path 2: search for an AI edge first
1. Pick the AI rungs to test: C (risk investigation with escalation) and change detection (job 3).
2. Build a post-cutoff test set: dates from **2025-10 onward** (Qwen cutoff ≈ mid-April 2025), names from the screener's nominations at those dates,
   outcomes = later drawdowns / deal breaks / restatements / guidance cuts. Register bars before running (include false exclusions and missed winners).
3. Prospective paper observation alongside (the history window is about one year).
4. Measure Qwen monitoring on real events (Phase 6 test B equivalent) before relying on it.

### Path 3: screener research
Decompose the 2023-24 result (door contributions, momentum vs value, turnover), with care not to fit one period (register before looking at 2025).

### The coordinator's recommendation: Path 1 + Path 2 together (see file 02).

## 3. Decisions needed from the operator
- **The strategy** (file 02 §4).
- **The D2 fade convention** (blocks a proper fix of the kappa / year-6 desk defect): during the fade after year 5, when the margin moves, is the
  reinvestment charge driven by **revenue growth** (capital tied to sales) or **earnings growth** (capital tied to profit)? The two differ by about ±20%
  in value in the controlled examples (`PLAN_terminal_reinvestment.md`, cross-check 21 rulings, "Fade growth convention (ChatGPT, major)").
  Until then `cash_scaling_out_of_band` marks affected verdicts non-actionable.
- **Materiality threshold** for D2 inputs (deferred by the operator until recovery is done).
- Whether to run the cross-check on the factor-led spec (after v2).
- The **Shadow V4** folder and the rn_v4 paper books (left in place, "leave it for now").
- Whether to keep the `RS2-P4-R26-*` tasks (they are idle) or retire them.

## 4. Housekeeping still to do (no decisions needed)
- Update `STATUS.md` (Phase 4 section) with: the freeze (rev 26 @ pack 28, paper-only low confidence), iterations 3-4, the engine measurement,
  baseline A, the cutoff, the factor-led draft, and the pending decision. Archive the current section first as `reports/STATUS_PHASE4_HISTORY_<date>.md`.
- Update the Claude memory (if you are Claude): a memory for the freeze and the baseline-A finding; update `rev23-handoff.md` to point at this handoff.
- `design.py`'s `P4_R26_HOLDOUT_REGISTERED` is stale (lists KOF, DAR, VSNT, CTVA); `_draw.json` is authoritative (CTVA, NHC, TTAM, CLDT). Fix only
  if the pilot is used again.
- The `discount_rate_set_to_anchor` stamp fires on a floating-point difference (0.0927 vs 0.092699…) when the rate did not change; cosmetic.

## 5. Deferred engineering list (recorded in SPEC §10 E and the plan log)
- Stage-1 context overflow (KOF): an output cap per turn (`num_predict = min(12-16k, window − prompt − 2k)`), salvage of complete facts from a length-cut
  call, one recovery turn, the correct stop label (`context_exhausted`).
- The proximity rule rejecting facts on the company's own name ("gold", "integer", "inbev").
- Withdrawn-guidance and buyout-scope tags on stage-1 facts (ITGR cited withdrawn guidance).
- A semantic memo entailment check (memo claims against the dossier).
- Driver-level reverse stress tests for path-dominated names (ChatGPT): solve for the contract-realization or post-expiry earnings the price requires.
- D2 validation of DAC and MCY; financial companies on an equity (retained-equity / ROE) route; a proper terminal state for decliners.
- A scenario-coherence diagnostic (Base/Bull/Bear probabilities and tails).
- The masker can still leak price-like prose without trigger words (market cap with shares, annualised dividends); readers noted it; low risk.
- ChatGPT's "revision-28 roadmap" (sensitivity-first, targeted research, typed driver claims with "unresolved", decision robustness, deterministic memo
  tables) — superseded in priority by the factor-led direction but still the best idea for any future valuation-centred analyst.

## 6. Things NOT to do
- Do not run the holdout on the frozen design (it has failed the bar; the holdout is for a design worth testing).
- Do not lift `KIS_HALT` or `DEPTH_PAUSED`; do not merge anything to rs2 `main` or deploy.
- Do not re-iterate revision 26 against the same 12 names to chase a pass (the operator's time box and ChatGPT's warning: no benchmark optimization).
- Do not let an unvalidated valuation or AI opinion gate or size trades.
