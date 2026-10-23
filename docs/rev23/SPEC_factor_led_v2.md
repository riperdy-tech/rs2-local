# SPEC v2 — Low-turnover factor paper baseline + bounded AI risk observation
**Date:** 2026-10-23 KST · **Status:** strategy direction approved by operator (paths 1+2); implementation rules are design proposals pending preregistered evidence and milestone review. **No live trading authority.**

## 0. Decision and evidence boundary
This document replaces the *proposal* in `SPEC_factor_led_v1.md`, without editing v1, in response to Baseline A. Source-of-truth measurements: `scratch/baselineA/REPORT_baselineA.md`; `scratch/rev23/pilot_r25/runs_p4r26/{3,4}/score.json`; `scratch/qwen_cutoff/REPORT_cutoff.md`; and `rev23/handoff_2026-10-23/`.

- **The screener is a factor exposure, not a proven alpha generator.** Baseline A (reconstructed 2017–2025) reports research_now +2.5 percentage points/year gross versus the eligible universe and **−0.1 points/year factor-controlled alpha**, ~3.2x/year one-way turnover, −38% maximum drawdown (universe −34%). The positive factor-controlled effect was concentrated in 2023–2024 (+13.4 points/year); 2017–2022 was −1.9 points/year. Overall +2.5 is not a causal increment or an expected return.
- **Historical reconstruction limitations:** no vintage EPS revisions (a live Door-1 input), approximate historical cost-of-equity anchors, present-day listing coverage with imperfect delisting bounds, imperfect historical classifications, and 2025 only 11 months. Alternative delisting treatments materially change conclusions. These deficiencies cannot be repaired by declaring a new weight or threshold. All new retrospective evidence remains exploratory unless a genuinely untouched date set is established.
- **Revision 26 is frozen** at pack revision 28 as paper-only / low confidence; blinded coherence 1/9 on iteration 3, 0/9 on iteration 4. The desk's kappa/year-6 cash-flow inconsistency remains. Old DCF valuations cannot change paper selection, weights, exits, or trade eligibility.
- **Monitoring is unproven:** previous Muse real-event strict recall 6/20 (target 18/20); Qwen monitoring has not been measured. Qwen training-knowledge boundary near April 2025; retrospective Qwen assessments must use decisions dated **2025-10-01 or later**, subject to source-time validation.
- **Goal:** first determine whether lower turnover makes a more usable *paper* factor exposure; independently test if Qwen detects incremental, verifiable risks and changed theses. Neither is assumed to outperform the market, nor is either a production cutover decision.

## 1. Authority and separation
| Component | Allowed in v2 | Not allowed |
|---|---|---|
| Deployed screener / PIT replay | Nomination data, original factor and door ranks, warning flags; paper baseline selection | Claim factor-controlled alpha without evidence; adjust live screener to fit a backtest |
| Python paper simulator | Explicit holdings, cash, mechanical rebalance, transaction costs, benchmark attribution and event log | Place broker orders, write production overlay, quietly remove unscorable names |
| Verified-event checker (future B) | Annotate known filings/market actions and propose an explicit **paper** restriction | Rely on filing form number alone, turn uncertain facts into automatic sales |
| Qwen 3.8 27B Q5_K_M (future C) | Inspect period-correct evidence; cite verbatim source/filing; flag risks, material changes and unresolved questions | Give buy/sell orders, override weights, veto by prose, value perpetual earnings |
| Valuation / D2 | Diagnostic only; show known defects and sensitivity limits | Influence capital allocation until independent prospective validation |
| Broker / cloud publisher | Remain untouched | Clear `KIS_HALT`, clear `DEPTH_PAUSED`, deploy or turn on tasks |

Every row of a prospective paper decision needs `asof`, source ids and acquisition timestamps, code revision, universe/rank version, reason for entry/hold/exit, before/after weights, cost, and `unverified` labels. Missing data becomes an explicit coverage failure; never treat numeric zero as missing. Old (rev26) verdicts are ignored, not promoted.

## 2. Paper factor variants (hypotheses, not chosen winners)
**A0 — fixed reference:** reproduce the unchanged production-screen replay used by Baseline A: monthly research_now, current Door 1/2 hysteresis and Door 3 policy, equal weight, next session adjusted-open fills, drifted weights, one-way turnover = 0.5 sum(abs(target − drift)), 0 / 20 / 60 bp round-trip cost scenarios. Compare at *the same months, universe, data snapshot and delisting treatment*; stop if A0 cannot be reproduced before making A1.

**A1 — one predeclared low-turnover candidate, paper only:**
1. Same investable universe, factor scores, Door 1/2/3, restrictions and ranking as A0. Do **not** retune factor coefficients, sector quotas or door mix.
2. First eligible month in replay: use the 2017-01 formation snapshot as the initial paper basket (do not backfill prior holdings). Then **rebalance at March, June, September and December month-end**, with orders at the next market session's adjusted open. At each intervening month, carry existing holdings and drifted weights forward; do not recreate an equal-weight book.
3. Target capacity = exactly the A0 research_now capacity for that formation date (normally ~50–60 including Door 3), not a synthetic static 50 if the original contract varies. Rank new entries using the A0-ranked shortlist; for incumbents, the proposed **wider retention band is rank ≤80 for Door 1/2**, with the original Door 3 eligibility/retention rules unchanged. A name above 80 may remain only until the next scheduled rebalance; no replacement fill without an explicit documented rule. Rank=80 is a *design parameter awaiting testing*, not an empirically proven optimum.
4. Retain eligible incumbents first; fill vacancies from highest-ranked unheld current nominees, never exceed current capacity. Reweight only at scheduled dates. If the source replay lacks **historical numeric rank** and door-specific eligibility, **stop A1 and repair/rebuild the PIT rank artifact** from the unchanged screener at T; do not infer rank from today's data or the band label.
5. At non-rebalance months, carry weights and record the contemporaneous ranks/warnings. **Do not apply any AI risk-based buy pause or historical hard-stop without independently time-stamped evidence coverage**; publish A1 as `factor_only` and separately record unavailable historical event handling.
6. Compare a **frozen A1**, not repeated parameter sweeps. Examine robustness by period and all three delisting treatments, not just the favourable 2023–2024 regime. No optimisation to a known result.

**Paper accounting:** dividends/splits via existing adjusted price conventions; name-level missing entry, stale series, suspensions, delistings, forced zero and cash retention all logged; event handling follows the *same* three Baseline A bounds. A missing future bar does **not** silently cause reallocation at a favourable price. Track cash drag, bid/ask/cost sensitivity and benchmark calendar alignment explicitly. This is a simulation contract, not an instruction to use a broker.

## 3. Mechanical risk and exits — future rung B
Build **event observability before event restriction**. A filing or notice is `verified` only when code resolves issuer identity, relevant event type, effective status/date, document accession or exchange notice, verbatim corroborating passage, publication timestamp ≤ decision time, and whether superseded/withdrawn. A form number or model summary by itself is never enough.

Candidate events for *registration and per-type corpus audit*:
- Pending fixed-price acquisition of the company: 8-K 1.01, 2.01, definitive merger filings/exhibits; distinguish buyer/target and pending/completed/cancelled; SEC or issuer release confirmation.
- Going concern: 10-K/10-Q auditor's opinion or explicit note; not merely the word “concern” in unrelated prose.
- Delisting/deregistration: 8-K 3.01 plus exchange announcement where possible; voluntary versus compliance notice is distinct.
- Restatement affecting factor inputs: 8-K 4.02, 10-K/A, 10-Q/A; confirm specific prior period and account.
- Trading halt: timestamped exchange halt/resumption notices; mark exchange-feed coverage gaps as unknown.
- Bankruptcy/restructuring: 8-K 1.03, court filing or legally effective notice; distinguish voluntary plan from proceedings.
- Dilutive reverse split: authoritative proxy/filing terms and actual issuance/dilution; **no numerical bound is approved yet**, so annotate only.

A confirmed paper event may yield `new_entry_restricted`, `pending_reunderwriting`, or `unresolved`, with a source and explicit expiry/resolution. No unverified observation silently ejects an incumbent; a verified restriction does not automatically sell. The deterministic exit policy for held names must be documented and validated separately, preserving risk limits and actual execution/corporate-action feasibility. If history of filings and timestamps is incomplete, report coverage by event type and refrain from a historical B return claim.

## 4. Qwen's narrow roles — future rung C, observation first
Model pinned to `rs2-analyst-deep-mtp5-v33` / Qwen 3.8 27B Q5_K_M, through the versioned `ollama_raw` interface, with **short dedicated SYSTEM instructions** for each task and logging of full version, hashes, prompt, output and model options. No revision-26 full DCF or mandatory investment committee memo.

- **Risk discovery:** for a PIT-ranked nominee, identify source-backed customer/concentration, debt/refinancing, accounting, guidance-withdrawal, regulatory, contractual and dilution risks the deterministic checker missed; describe mechanism, affected horizon, competing explanation and unknowns.
- **Change detection:** compare thesis/filing facts on T with **new evidence available by T**; label unchanged, changed, unknown or unsupported; cite source times and facts. This cannot force sale.
- **Focused verification:** one bounded follow-up on a specific material uncertainty. Output `confirmed`, `contradicted`, or `unresolved` only with cited text. No numeric impact except verified values copied to an owner-approved field.
- **Research/interpretation:** optional supporting work only after risks and change detection are measured; neither deserves investment authority by default.

An AI claim creates a **visible paper observation** only. A temporary new-buy pause is **disabled until** the event verification rate, false-positive cost, maximum pause duration, expiry and independent review are registered and measured. Even then a model's unsupported phrase cannot initiate it; a confirmed event routes to deterministic B, uncertain material claims to an escalation queue with no automatic change to portfolio return series. “No risk found” provides no positive conviction.

## 5. Test ladder and promotion rule
- **A0 versus A1:** same past dates and inputs, paired gross/net returns, vs equal-weight investable universe and SPY, maximum drawdown, volatility, factor-controlled result, one-way turnover, weighted costs. Any claim of skill needs valid factor controls and robustness; *lower turnover alone* may be a worthwhile operational baseline but is not alpha.
- **B versus A1:** only after complete event-time records, test incremental verified restrictions and false exclusions; an audit of missing sources comes first.
- **C versus B:** Qwen tested initially as a **shadow observer**, with both missed material events and wrongly flagged eventual winners counted. Use PIT evidence, model cutoff rule and prospective recordings; no paper-veto authority until incremental risk reduction beats B without undue missed winners.
- **D/E valuation:** deferred. No desk promotion while the year-6 / D2 semantics and other known model defects remain uncorrected, unreviewed and independently tested.

**Full methods, proposed acceptance thresholds, anti-leakage checks and stop conditions** are registered in `PROTOCOL_factor_ai_m2_2026-10-23.md`. A retrospective 2017–2025 replay is a *design diagnostic*, not an unseen validation set: the baseline was already read on 2026-10-23. No 2023–2024 or 12-name freeze-panel fitting, no use of CTVA/NHC/TTAM/CLDT holdout.

## 6. Sequence and decision gates
1. Confirm A0 checksum, universe and monthly row counts match Baseline A; confirm historical ranks and price-path mechanics. Fail closed with discrepancies.
2. Implement *isolated scratch* A1 replay and tests (monthly weight carry, rebalance gate, zero-cost equivalence, absent delisting bar, boundary ranks). Do not edit `screener-publish` or live screener.
3. Score the **single frozen A1 candidate** against A0 with predeclared measures; report missing history and robustness. Operator reviews the outcome before paper schedule.
4. Build issuer/event-date provenance registry; audit hard-stop classifications, coverage and false triggers before any B simulation.
5. Assemble retrospective **2025-10 onward** source-time-proven evaluation cohorts and begin prospective shadow log. If the eligible historical corpus is inadequate, report that and continue prospective observation; do not fill gaps with current web results.
6. Run a resource-limited Qwen smoke **only after independent cross-check** of the design, registry and evidence controls; evaluate risk/change detection on actual events, not old valuation holdout. Report failure/coverage before considering promotion.

**Operator decisions still reserved:** adopt A1 after measurement; exact B forced-exit policy and materiality; any C buy-pause duration and allowable verified-action list; D2 fade (reinvestment follows sales vs earnings growth) and D2 materiality; paper-to-real cutover. **Current approval covers the strategy and design work, not these trading rules.**

## 7. Source-of-truth and file locations
- Local canonical: `stocks-workspace/docs/review_2026-09-22/rev23/`; mirror: rs2 `docs/rev23/` on `docs/rev23-records`. This document never changes the live deployment repository.
- Replay: `stocks-workspace/scratch/baselineA/scripts/s5_backtest.py` currently rebuilds an equal-weight portfolio monthly; **it does not implement A1**. PIT input details and the three event-return bounds are documented in its header and `REPORT_baselineA.md`.
- Verification: `rs2-local/AGENTS.md` standard of proof and `stocks/AGENTS.md` ten non-negotiables apply. No deletion, secret edits, CI edits, model prompt revision or deployment occurs in this milestone.
