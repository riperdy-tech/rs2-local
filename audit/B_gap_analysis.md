# Phase B — Bidirectional Gap Analysis: RS2 vs the Institutional Checklist

Audit date 2026-08-18. Every claim carries file:line evidence from this repo (or the screener
repo, marked `[screener]`). Checklist item numbers reference `A_institutional_checklist.md`.

## B.1 Scorecard against the MUST-HAVEs

| # | Checklist item | RS2 status | Evidence |
|---|---|---|---|
| 1.1 | Defensible discount rate | **FAIL (level), PASS (consistency)** | Rate is a hard-coded 11-row sector table 7–11% (`valuation_backbone.py:179-188`), a mirror of the screener's config, never re-derived. No rf/ERP/beta anywhere. The levered-flow↔market-cap frame IS consistent and the label misnomer is documented (`valuation_backbone.py:174-179`). The book's own implied rate (~11.8%) is measured offline in `tools/implied_erp.py` and wired to nothing. A 2pt rate change moves median book MoS from −38.9% to −13.5% (`valuation_backbone.py:961-968`) — the rate sets the level of everything. |
| 1.2 | Terminal-value discipline | **PARTIAL** | Terminal g fixed 2.5% (`valuation_backbone.py:168`) — inside the 2–3% norm. But: no TV-share-of-PV telemetry, no exit-multiple cross-check, no mid-cycle normalization of the terminal flow for non-cyclicals. TV share is never computed anywhere. |
| 1.3 | Correct cash-flow definition | **PARTIAL, honestly disclosed** | `base_cf` = 50/50 blend of latest owner earnings and revenue×median margin (`valuation_backbone.py:700-732`), empirically chosen (n=4,104, blend err 2.78 vs 3.10pts). But: **total** capex, not maintenance capex — the AMZN problem is documented as the central unresolved issue (`valuation_backbone.py:529-537`) and delegated to the lattice + LLM basis vote rather than estimated (Greenwald PPE/sales method not attempted). **No ΔWC term** (Buffett's own definition includes it). **SBC never deducted** — displayed to the LLM only (`rs2_data.py:532`); zero hits in valuation code. Owner earnings on the live book capitalizes ~53% of TTM NI (`valuation_backbone.py:528-548`) — a structural conservative bias the MoS percentile ranking then absorbs. |
| 1.4 | Earnings-quality screen | **FAIL — and the fix is nearly free** | Zero accrual/F-score/M-score code in RS2 Local (grep-verified). The screener already builds `public/data/fundamentals_battery.json` with `f_score`, `accruals_ratio`, `m_score`, `net_issuance_1y/3y` per ticker (`[screener] build_fundamentals_history.py:612-747`, file declared at `:18-19,52`). RS2's data loader (`rs2_data.build_data_context`) never opens it. RS2 capitalizes NI-derived flows with no check that cash backs the earnings. |
| 1.5 | Balance-sheet / solvency gate | **FAIL** | No leverage, coverage, liquidity, or distress check in any valuation or verdict path. `interest_expense`, `total_liabilities`, `current_liabilities`, `lt_debt` (outside biotech rNPV), `inventory`, `receivables` are ingested and unused. A leveraged name and an unleveraged name with the same base_cf get identical fair values and identical brake treatment. |
| 1.6 | Second valuation lens | **PARTIAL** | Analyst consensus is used as a malfunction fence and snap target (`valuation_backbone.py:1129-1170`). CORRECTION during this audit: the "~78% consensus_snap" note at `run_rs2.py:1154-1156` describes the pre-2026-08-13 fence; **measured today (C1 baseline replay) only 4 of 155 reverse-DCF names snap to consensus** — the published fair value is now genuinely the engine's own DCF for 97% of the book, with consensus as a true malfunction fence. That makes the *absence of any second lens* sharper, not softer: no peer-multiple cross-check exists; EV/Sales, EV/GP, EV/EBIT are pass-through display strings (`rs2_data.py:556-560`), and consensus no longer implicitly served as one. |
| 1.7 | Model–company fit | **PASS** | Routing: P/B-ROE for banks/insurers (`valuation_backbone.py:1029-1031`), regulated utilities at 7% CoE (`:1035-1037`), rNPV for pre-revenue biotech (`:843-882`), mid-cycle for cyclicals (`:678-684`), FFO for REITs (`:657-663`), Engine 2/4 fallbacks. This is genuinely institutional-shaped. AFFO (FFO − maintenance capex) not used for REITs — minor. |
| 1.8 | Sensitivity awareness | **PARTIAL** | `fv_sensitivity_pts` computed (`valuation_backbone.py:1136-1144`) but deliberately retired as a gate; it is telemetry that nothing downstream reads. No rate-sensitivity or TV-sensitivity per name. |

## B.2 Scorecard against the GOOD-TO-HAVEs

| # | Item | Status | Evidence |
|---|---|---|---|
| 2.1 | Full expectations decomposition | **PARTIAL** | Price-implied growth solved properly (`valuation_backbone.py:326-350`); gap-vs-delivered/persistence comparison exists. But expectations are a single growth scalar — no driver split (growth vs margin vs reinvestment), and horizon/CAP is fixed 5+5 for every name (`:168-169`) where market-implied CAP varies 5–15y. |
| 2.2 | Growth base rates | **PASS — ahead of most institutions** | `GROWTH_PERSISTENCE` empirical fade table, n=3,115 ticker-years (`valuation_backbone.py:36-62`). Gap: silent below the 15% delivered floor. |
| 2.3 | Scenario-weighted value | **FAIL (worse than absent: pure cost)** | S4 runs every ticker, probabilities parsed and stored (`run_rs2.py:2452-2454`) and **consumed by nothing** (grep: only write + validator). One of six LLM stages produces a dead output while still costing its share of ~9-10 min/ticker. |
| 2.4 | Quantified quality/ROIC | **FAIL** | Moat scoring is entirely LLM prose (S2 prompt, `run_rs2.py:73-77`). No computed ROIC or ROIC−CoE spread despite all inputs being ingested (`operating_income`, `total_assets`, `equity`, tax fields). Conviction's "Business Quality" component has no numeric anchor. |
| 2.5 | Fractional Kelly | **PARTIAL** | S5 prompt asks for Kelly (`run_rs2.py:123-145`); no fraction/correlation discipline; the deterministic brake caps weight at 5%/3% anyway (`run_rs2.py:1177,1196`), which is the de-facto (sane) sizing rule. Kelly language is decoration on top of a cap system. |
| 2.6 | Outcome feedback | **PASS — ahead of most institutions** | Verdict ledger (append-only, point-in-time keyed, repatch-aware) + grader with benchmark-matched horizons, name-weighted stats, honest no-significance disclaimer (`[screener] grade_rs2_verdicts.py:262-303`) + track record injected into prompts (`outcome_feedback.py`). |

## B.3 SITUATIONAL items vs the actual book

- **FX for 20-F filers — OPEN, known.** `PLAN_FX_INGESTION_20260814.md` on record; BWMX still overlay-excluded; TSM FY-anchor-only. Population is in the live book today.
- **Dilution — FAIL outside biotech.** rNPV models financing dilution (`valuation_backbone.py:843-882`); nothing else does. `net_issuance_1y/3y` already computed upstream in the battery file — unread.
- **Normalized taxes — ABSENT.** `tax_provision`/`pretax_income` ingested, unused. Low materiality for a gap-ranking engine; matters for Engine 2 normalized-EPS names.
- **Country risk — ABSENT.** EM-exposed names (TIGO, VTEX, BWMX) discounted at the same sector rate as domestics.

## B.4 Present but NOT earning its keep (candidates for removal or wiring)

1. **S4 scenario stage output** — dead (B.2 §2.3). Either wire probabilities into an expected-value/range that the verdict consumes, or fold the scenario ask into another stage and drop the call.
2. **14 of 24 ingested fundamental fields** never touch a computation (`total_assets`, `total_liabilities`, `current_assets`, `current_liabilities`, `inventory`, `receivables`, `retained_earnings`, `sga`, `gross_profit`, `interest_expense`, `pretax_income`, `tax_provision`, `ppe_net`, `operating_income`) — they cost prompt tokens every stage as display text. Several become *useful* under 1.5/2.4 adds; the rest are candidates to trim from the prompt.
3. **Stale absolute-15% strings** in live prompts: `run_rs2.py:92, 501, 1826` still tell the model "MoS thin (<15%) ⇒ do-not-chase", contradicting the percentile ENTRY DISCIPLINE line built in `rs2_data.py:94-125`. The model receives both rules simultaneously.
4. **Stale brake docstring** — `run_rs2.py:1113-1121` describes the retired absolute 15/25% tiers; implementation is percentile (`:1129-1151`). Doc-only, but it is the exact pattern CLAUDE.md's incident note warns about.
5. **`fv_sensitivity_pts`** — computed, surfaced, read by nothing (`valuation_backbone.py:1136-1144, 1211`).
6. **Orphaned modules**: `research_agent.py`, `AgentWebSearch-MCP/`, `Run-RS2.ps1`, `data/TEMPLATE.md`; stale claims in `README.md` (pre-inversion architecture, wrong model, wrong ctx sizes, no orchestrator) and in module docstrings `run_rs2.py:5-7`, `rs2_data.py:20`. `RS2.txt` / `RS2 engine.txt` byte-identical duplicates.
7. **Stage-consumption question (open until C7):** which S1–S6 prose actually changes `verdict.json` vs is carried into FINAL.md as narrative. S3 (stance JSON), S4 (probs — dead), S5 (conviction number), SECTION 12 (parsed) have mechanical consumers; S1's archetype routes cyclicality (`routing.json`); S2 and S6 have **no mechanical consumer** — their value is entirely via context carried into later stages and the final text. C7 measures their marginal effect footprint.

## B.5 What RS2 has that most institutional processes DON'T (credit where due)

1. **Data-corruption gating as a blocking sweep gate** (`data_health.py --gate-live`, ~1000× SEC scale-slip detection, cross-source share checks) — most shops discover these in post-mortems.
2. **Cross-sectional MoS calibration** (`build_mos_distribution`, 3-day freshness, refuses stale fallback) — a principled answer to the level-vs-rank problem that most DCF shops ignore.
3. **Deterministic don't-chase brake with an expectations override** (`run_rs2.py:1112-1197`) — behavioral discipline most human processes only aspire to.
4. **Two-tier post-run audit** (deterministic reproducibility + AI contradiction audit with variance logging).
5. **Point-in-time verdict ledger + benchmark-matched grader with honesty controls** — genuine quant hygiene.
6. **Empirical parameter provenance** — base_cf blend, growth-persistence table, stance thresholds, brake tiers all carry measured justifications in comments. Rare anywhere.

## B.6 Synthesis — the shape of the gap

RS2 is a well-built **ranking** engine wearing the vocabulary of a **valuation** engine. Its
deliberate strengths (determinism, calibration, corruption defense) are real and ahead of
practice. Its gaps cluster into exactly three institutional themes:

1. **The level problem** — discount rate (1.1), terminal discipline (1.2), and flow definition
   (1.3: SBC/ΔWC/maintenance-capex) all push the *level* of fair value around by tens of points;
   the system compensates by ranking. That is defensible if and only if the errors are roughly
   cross-sectionally uniform — which C1–C3 will measure. If they are not uniform (e.g., SBC
   omission flatters tech; single-rate flatters high-beta), the *ranking itself* is distorted.
2. **The survivorship/quality problem** — nothing stops earnings-quality or solvency failures
   from reaching BULL verdicts (1.4, 1.5). The inputs to fix this already exist upstream
   (`fundamentals_battery.json`) or in ingested-unused fields. C4/C5 will measure how many
   current BULLs are affected.
3. **The dead-weight problem** — one LLM stage's structured output, 14 prompt fields, three
   contradictory prompt strings, and several orphans cost every single run and return nothing
   (B.4). Removal is pure win; C7 quantifies the runtime share.
