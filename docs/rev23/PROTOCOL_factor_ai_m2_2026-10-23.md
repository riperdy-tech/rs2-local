# Milestone-2 pre-analysis protocol: low-turnover A1 and AI risk/change-detection C
**Registered:** 2026-10-23 KST · **Owner:** coordinator · **Operator direction:** paper-only path 1 + path 2 · **Status:** written before running A1 or Qwen-C on new cohorts; historically explored 2017–2025 data **is NOT a blind holdout**.

Linked design: `SPEC_factor_led_v2.md`. This protocol may be amended **only before** looking at affected experiment's results, with a numbered amendment, reason, timestamp and an explicit disclosure of any previously seen results.

## 1. Existing evidence disclosed before registration
Baseline A already reported research_now gross +2.5 pp/year vs eligible universe, +0.4 pp/year net at a 60 bp round-trip scenario, −0.1 pp/year factor-controlled alpha, ~3.2 one-way turns/year and −38% max drawdown (2017–2025 aggregate); 2017–2022 weak, 2023–2024 unusually strong. Survivorship bound alters outcomes. Readers found iteration-3 1/9 and iteration-4 0/9 coherent. Qwen cutoff near 2025-04; Muse monitor strictly caught 6/20 real events. **The new thresholds below are not untouched, statistically guaranteed discovery criteria.**

## 2. A0 reproducibility gate (required before A1)
- Inputs: unchanged production screener algorithm from `screener-publish/scripts/score_factors_dual_door.py` at pinned git SHA; `scratch/baselineA/data/` PIT fundamentals/price/replay files; include per-input hashes and source-vintage timestamps.
- **Recompute the A0 Baseline A report from the original inputs**, recording month count, universe and portfolio counts, entry and ending dates, annualised return, trading costs, turnover, max drawdown, SPY and universe series, and factor-model coefficients for each delisting bound. Compare full monthly arrays, not merely rounded aggregate numbers. Halt A1 if source inputs are missing, inconsistent, modified, or if >1e-8 difference exists in identical pure arithmetic; output a reproducibility report with smallest differing month.
- A0 script currently forms fresh monthly equal weights. A1 requires a distinct **persistent book accounting** function; copying A0's `series()` as-is would produce an invalid quarterly replay.

## 3. A1 single candidate and operating specification
- One candidate only: quarter-end Mar/Jun/Sep/Dec holdings refresh, initial Jan-2017 snapshot, unchanged production rank/doors, existing Door-3 rules, incumbent Door-1/2 retention through PIT rank 80, no rank/sector-rule tuning. Equal weight at formation, otherwise drifted weights. Next-market-session adjusted-open execution.
- Event/filing restrictions *not* included in A1 performance: `factor_only` label, without pretending missing historic event feeds were clean. Named stops for no available rank, price, position, filing-vintage, holdings or share split where required. All omitted names/counts tabulated.
- Months with a stopped trading series use `excluded`, `minus100`, and `last_close` bounds exactly as Baseline A; use the same corporate-action, commission and censused-delist conventions for A0 and A1.
- Compare equal-weight investable universe, SPY, **A0**, characteristic matching, Fama–MacBeth and time-series factor controls. Report gross, 20bp and 60bp round-trip cost settings; no-cost calculations show turnover impact separately. Include 2017–2022, 2023–2024, 2025 (11 eligible months), whole period, and year-by-year. Positive result in 2023–2024 alone is insufficient.
- Exact per-month state required: observation date, eligible universe/hash, rank, held/entered/exited, cash, start/end weights, target weights, order turnover, per-order cost, source vintage, end price/corporate action and reason code. Turnover is measured with *drifted pre-trade* weights and includes forced exits. Zero and missing are distinct.

## 4. A1 evaluation bars — operating suitability, not alpha
A1 can be proposed for **prospective paper observation** only if it meets *all* of these preset review bars on each of the three historical delisting treatments (or is honestly marked indeterminate due to missing coverage):
1. **Operational:** zero look-ahead or accounting invariant failures; identical replay produces identical holdings/returns; delisting name counts and calendar coverage reported. Any silent dropped name or failed price arithmetic stops.
2. **Turnover:** annual one-way turnover ≤ **1.6x** (half the 3.2x Baseline A benchmark). This is a **cost-control goal chosen before A1 measurement**, not a statistically validated parameter.
3. **Cost benefit:** (A1 gross minus A1 net) at 60bp ≤ (A0 gross minus A0 net) at 60bp, with a nonzero reduction. Report the absolute annualised drag in bp. This verifies that the quarter rule actually saves expenses.
4. **Return/risk:** A1 net-60bp annualised excess over A0 net-60bp ≥ **−1.0 percentage point**, and maximum drawdown is **no more than 5 percentage points deeper** than A0, across the full window and **the 2017–2022 window**. These are **tolerance budgets**, not evidence of causal superior returns.
5. **Benchmarks:** report net excess to both universe and SPY, and the independent factor-controlled estimates and confidence bands. None may be omitted; the strategy must not be advertised as alpha-generating absent robust positive factor-controlled alpha (prospective confirmation needed). If point estimates differ radically across bounds, mark `robustness_failed` regardless of 2–4.

If A1 passes this engineering gate it remains **paper-only**. If it fails, return a measured report and do not modify buffer 80/weights until a new preregistered design, with a new independent evaluation window, is justified. Since the baseline period has already been viewed, approval for any eventual deployment needs prospective data beyond this replay.

## 5. Deterministic B: event and source-observability audit first
Candidate event classes: fixed-price target acquisition, going concern, exchange delisting/deregistration, material restatement, exchange halt, formal bankruptcy/restructuring, dilutive reverse split. The form/keyword is a **retrieval hint**, not sufficient verification. A registered review of issuer identity, filing/exchange source, event status, public datetime, effective datetime and whether withdrawn/cancelled is required.

Create two independent counts: `eligible_snapshot_count` (every PIT candidate) and `verified_event_opportunity_count` (every independently discovered confirmed event), including instances the proposed checker misses. Before any simulated B return:
- Publish event-coverage denominator by type and date; count unavailable source dates/issuer mappings explicitly rather than assigning `no_event`.
- Dual-adjudicate a time-stratified, randomly drawn audit sample of negatives as well as positives; record false restrictions, false omissions, withdrawn or superseded events and severity.
- Report B alongside A1 on identical price universe/time/cost, with **false exclusions/missed winners and delayed-buy opportunity cost**, not just prevented drawdowns. Do not treat retrospective B benefit as conclusive given the snapshot and selection biases.
- No forced deterministic sale rule is accepted until operator reviews the simulated event-by-event consequences and explicit source coverage. Until then verified events produce paper restriction proposals/flags only.

## 6. Qwen C: contamination-proof study and label protocol
**Core role:** risk discovery and change detection, initially **shadow observations only**. No reruns of Revision 26 valuation, no use of the 12-name scoring panel to design an algorithm, no untouched valuation holdout used.

**Cohort and information:**
- Retrospective formation dates: no earlier than **2025-10-01**. For each monthly screener nomination/held name, data available as of the decision's **actual market/time cut** only. Reconstruct pack from archived filings/news with publication and acquisition timestamps ≤ T. Prohibit today's web search, current prices/filings, hindsight summaries, labels or future outcomes in the prompt or retrieval.
- Retrospective `eligible` requires proven source-time provenance and unchanged frozen model/config; if no dated, replayable sources exist, classify `not_testable`. Missing sources **cannot be replaced with current search results**. Report selection bias and remaining window length.
- Prospective paper snapshots: freeze the input packet and reference facts before model invocation, record monotonic run id, timestamps, hashes, output, and any attempted missing-source fallback. Continue sequential observations without changing tasks to match an early outcome.
- **Ground-truth register:** independent reviewer searches future verified events and negative/control dates across the *same candidate universe*, not only model-flagged cases. Events: documented guidance withdrawal, bankruptcy, delisting, restatement, liquidity/contract rupture, large regulatory action and explicitly timestamped thesis breaks. Define timing and causal relevance per event. Distinguish `confirmed critical`, `confirmed noncritical`, `non-event`, `unknown`, and `insufficient evidence` before reading model outputs in the blind review.
- Model output JSON per name: `asof`, `entity_id`, `risk_type`, `change_type`, `claim`, `mechanism`, `fact_ids`, `quote`, `source_asof`, `urgency`, `confidence_basis`, `unknowns`, `follow_up`. Reviewer checks exact quote and issuer; new fields must have a schema owner. Unsupported claims remain visible and are never turned into `verified` silently.
- Comparison: B source checker with the **same event corpus and data budget**, naive news/keyword control and Qwen-C. Report time-to-detection versus public event, recall, precision, false-positive rate per 100 candidates and per name-month, missing evidence coverage, missed critical events, wrongly restricted eventual strong performers, and compute/GPU usage. Stratify event type and listing/cap buckets. Report cases individually.

**Before C can request authority (not a current implementation target):** at least **20 independently labelled critical real-event opportunities**, a prespecified precision/recall confidence interval, prospective monitoring covering enough calendar states, and demonstrated improvement on a corresponding B baseline. The **90% strict recall (18/20)** in Phase 6 is the reference safety bar, *not* something 20 cherry-picked cases can establish statistically; show binomial interval and all false positives. Any missed bankruptcy/restatement or source-leak invalidates automatic use regardless of aggregate score. If only 5 cases exist, say 5 and stay in observation. All model-selection or threshold changes require a new dataset/window rather than retuning on the same cases.

## 7. Stop / release matrix
| Stop condition | Immediate outcome | Can continue safely? |
|---|---|---|
| A0 not reproduced or PIT numeric ranks absent | No A1 metrics; report missing input/bug with exact date/field | Fix replay in scratch with tests; do not impute |
| A1 accounting or time leakage | Mark run invalid, no performance claim | Fix and rerun only mechanical tests on existing data; declare prior view |
| A1 metric bars fail | No paper approval, preserve full comparison | Method review / new pre-registration, no parameter search |
| B lacks timestamped filings or ground truth | No event restriction simulation or promotion | Source coverage audit and prospective recording |
| C source after T, prompt contamination, incomplete cohort | Reject affected replay and record cause | Only verifiable PIT cases; default prospective |
| Qwen reports unsupported finding | Visible `unsupported`, no veto/pause/sale | Reviewer/source check |
| Broker pause state, GPU contention or network failure | Do not restart/schedule trading or GPU work by assumption | Offline paper/doc work only |

## 8. Next milestone execution plan (no tests claimed yet)
1. Pin/read A0 input hashes and SHA; make a read-only source-coverage census of PIT rank and delist field availability; save before coding.
2. Add a separately named scratch A1 simulator and deterministic fixtures: 2017 start, quarter boundary, weights drift in a skipped month, rank 80, missing rank, delisted stock, an all-cash edge case, `0.0` field, no lookahead and three bounds; run baseline reproduction test and a full paired replay.
3. Write A0/A1 report with every gate above, **including failed ones**; stop for operator review when finished.
4. Parallel no-GPU work: draft event-specific provenance/label schema and audit source coverage; **no Qwen inference yet** until cross-check of the comparison plan and PIT pack hygiene.
5. Cross-check document `CROSS_CHECK_26_strategy_after_baseline_A.md` should be reviewed before any substantive Qwen GPU cohort.

**No production config, CI/deploy config, broker halt, live screener, rev26 pack, real-money portfolio, model tag, scheduled task, or valuation-holdout is changed by this protocol.**
