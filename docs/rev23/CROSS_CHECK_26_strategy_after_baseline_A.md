# Cross-check 26 — Is the factor-only paper baseline + AI risk observer the right next experiment?
**Prepared 2026-10-23.** No results for new A1 or Qwen-C have been run or viewed at the time of this document. Strategy paths **1+2 together** were approved by the operator; this cross-check tests the protocol, not whether the operator should undo the approval. Reviewer: independent external analyst, no code edits or GPU test before a recorded ruling.

## Evidence already known (do not treat as unseen)
- Baseline A: research_now gross +2.5 pp/year versus eligible universe over reconstructed 2017–2025; +0.4 pp/year net at 60 bp round-trip; factor-controlled alpha −0.1 pp/year; ~3.2x/year one-way turnover; 2017–2022 factor alpha −1.9 pp/year, 2023–2024 +13.4 pp/year. Survivorship handling materially affects results; historical EPS revisions were unavailable and historical anchor was approximated.
- Frozen Qwen staged analyst revision 26: 1/9 coherent in iteration 3, 0/9 in iteration 4; kappa scales years 1–5 but not the year-6 terminal start, with material valuation sensitivity. No use for selection, weights or exits.
- Prior Muse monitor: 6 of 20 real critical events strictly caught, against 18/20 target; Qwen's event monitoring unmeasured. Qwen knowledge cutoff ~April 2025, thin leakage through Aug; retrospective evaluation must use post-cutoff dates and only contemporaneous material.
- KIS broker halted; analyst sweep paused. No live trading changes are contemplated.

## Design to review
1. **A0:** reproduce original month-end-ranked, next-session-entered, equal-weight monthly paper screener from the Baseline-A data and source code; compare all delisting bounds.
2. **A1:** same raw scores and eligible universe but quarter-end Mar/Jun/Sep/Dec rebalance, Jan-2017 bootstrap, retain ranked Door 1/2 incumbents through PIT rank 80 at a scheduled rebalance, Door-3 rules unchanged, drift positions across non-rebalance months. Start with ONE candidate, no threshold fitting to known 2023–24. Historical performance is exploratory. Reproduction and PIT rank availability are blocking.
3. **B:** source-verified corporate-event annotations/possible paper restrictions *only after* source coverage, timestamp, issuer/status matching and negative audit. A filing form number or AI prose is not a confirmed event. No automatic sale.
4. **C:** Qwen model under a tightly time-cut historical evidence packet after 2025-10, plus prospective observation; only risk discovery/change detection, verified quotes, no buy/sell or veto. Unresolved claims recorded; no pause until independently measured.
5. **Decision:** a documented operator review is required at the end of each milestone; nothing auto-promotes into live allocation.

## Questions requiring an explicit ruling
1. **A1 construction:** Is quarter-end with incumbent rank 80 a fair single test relative to monthly A0? Identify any survivorship/hysteresis/execution bias, unequal cash treatment or the need to pin exact rank semantics before simulation.
2. **Return accounting:** What is the strongest way to validate month-to-month weight drift, delisting bounds, missing adjusted opens, rebalances and total turnover? Does the three-bound comparison adequately prevent a falsely positive net-return result?
3. **Bar design:** Is annual one-way turnover ≤1.6, full-window and 2017–22 net return deterioration ≤1 pp/year, max drawdown deterioration ≤5 pp, and demonstrable cost savings a reasonable *operating* paper gate (not an alpha gate)? Which thresholds are arbitrary or too permissive, and what would you register instead **before seeing A1 results**?
4. **Baseline bias:** Since Baseline A was seen already and EPS-revision history is absent, what statements must remain “exploratory” even if A1 passes? Which future period or untouched dataset would provide an honest confirmation?
5. **Hard stops:** Which proposed events have poor machine-verifiable coverage (e.g. trading halts, reverse split dilution), what does an issuer/acquisition vs target error look like, and when must a hard-stop remain a human-reviewed flag?
6. **Qwen evaluation:** With about one year post-cutoff, how should a source-time-proven event/negative cohort be sampled without cherry-picking, and how should delayed detection, missed winners and unverifiable sources be scored? Can a 90% strict-recall safety requirement be meaningful on a 20-event sample?
7. **Risk authority:** Is the proposed “C shadow-only; no buy pause until independently proven” the safest incremental pathway? Where can AI's false-positive opportunity cost exceed its prevented-drawdown benefit?
8. **Practical feasibility:** Which existing Baseline-A artifacts actually contain historical numeric ranks and daily series needed for A1, and which data gaps must block rather than prompt a proxy?

## Required output
Return **GO / CHANGE / STOP** for *design validation work only*, with item-by-item rulings and the single most likely empirical failure. Separate proven source facts, assumptions and suggested engineering thresholds. Avoid recommending unregistered revisions based on 2023–24 returns. Point out contract contradictions and the smallest fixes. No code or production trading edits.

**Documents:** `SPEC_factor_led_v2.md`; `PROTOCOL_factor_ai_m2_2026-10-23.md`; `scratch/baselineA/REPORT_baselineA.md`; prior `SPEC_factor_led_v1.md`.
