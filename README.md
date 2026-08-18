# RS2 Local

Local LLM equity-analysis engine. Runs the RS2 framework (expectations investing) over the
screener's research_now / watchlist book on a local Ollama model, publishes verdicts to the
screener site overlay, and keeps an append-only, graded track record.

**Rewritten 2026-08-19** to match the code (the previous README described the retired
pre-inversion architecture). If this document and the code disagree, the code wins — and per
`CLAUDE.md` §0, fix the document in the same change.

## Architecture in one paragraph

Valuation is **deterministic Python**; the LLM never supplies a number for a DCF-able name.
`valuation_backbone.py` solves the growth the market price implies (reverse DCF on blended
owner earnings, two-stage 5+5, sector cost-of-equity table) and compares it to demonstrated
growth — the **expectations gap** is the headline signal, ranked cross-sectionally against
the book (`cache/mos_distribution.json`). The LLM contributes judgment: an achievability
stance, an earnings-basis choice on contested names, conviction, and prose. Verdicts pass a
deterministic don't-chase brake, then a two-tier audit (deterministic reproducibility +
AI contradiction audit) before anything publishes.

## Two levels

| Level | Entry point | What it does |
|---|---|---|
| Sweep | `orchestrate.py` | queue by band/cadence → data-health gate → MoS calibration → per-ticker runs → overlay/publish/ledger → git push. **Never run directly** — a bare run pushes to the live site; use `tools/run_batch.py` (forces `--no-push`, lock guard, git-SHA receipt). |
| Per ticker | `run_rs2.py` | enrich (yfinance) → OpenBB cache → deep research (`deep_research.py`, LDR + SearXNG/keyed search) → backbone (+ LLM regime decision when the lattice is contested) → 5 LLM stages → final assembly → `verdict.json` (+ brake, quality/solvency tripwires) → sanity → tier-1 → tier-2 audits. |

Scheduling: Windows task "RS2-Orchestrator" (`register_orchestrator_task.ps1`). Pause with
`cache/PAUSED`; monitor with `status.py` / `telegram_status_bot.py`.

## LLM stages

Each stage's user message = [fed data from `rs2_data.build_data_context`] + [prior-stage
carry] + [stage task]; the RS2 engine spec (`RS2.txt`) is baked into the model.

- **S1** classification / macro / base rates (archetype routes cyclicality via `routing.json`)
- **S2** business quality / moat / adjusted financials
- **S3** expectations test — emits the stance JSON (or Engine 2/4/5 inputs for names the
  backbone can't value); the engine then writes the authoritative VALUATION RESULT block
- **S5** scenarios (Layers 4/4.5, prose only — the structured S4 stage was retired 2026-08-19
  after audit C7/C9 measured its output dead and 82% template) + conviction / behavioral /
  portfolio / Kelly
- **S6** red team / pre-mortem / 37-point audit
- **Final assembly** consolidates Sections 0–12 under the field-ownership contract; the
  engine prefixes `FINAL.md` with an engine-typed valuation header.

Models: `rs2-analyst` (Qwen3.8-27B MTP tag, thinking off — migrated 2026-08-19 after the A/B
battery; see `RS2-Analyst-38.Modelfile` and `api_llm/` for the harness) and `rs2-research`
(`qwen3:14b`, clean of the analyst system prompt, for `deep_research.py`).

## Valuation routes

reverse-DCF on blended owner earnings (default) · mid-cycle for cyclical sectors · FFO for
REITs · justified P/B-ROE for banks/insurers and regulated utilities · rNPV (Engine 5) for
pre-revenue biotech · Engine 4/2 fallbacks. Contested lattices (≥30pts MoS spread across
earnings bases) get a 3-sample LLM majority vote on the basis *before* stages run.

Deterministic tripwires (audit 2026-08): earnings-quality battery (F-score, accruals,
Beneish M, issuance — from the screener's `fundamentals_battery.json`) and solvency
(coverage, net-debt/OCF) surface in the prompt and in `verdict.json`; they gate nothing.

## Data

- **Bucket A** — screener repo (git-pulled): SEC `fundamentals_history/_ttm/_quarterly`,
  `financials/{T}.json`, factor/reverse scores, macro; plus the Macro Regime Indicator.
- **Bucket B** — `enrich_ticker.py` (yfinance behavioral) and `openbb_data.py` caches.
- **Bucket C** — `deep_research.py` → cited `research/{T}.md` (SearXNG first, then
  Tavily/Brave/Serper metered by `quota.py`).
- **Bucket D** — the engine's own graded track record (`outcome_feedback.py`).

Corpus integrity is a blocking sweep gate: `data_health.py --gate-live`.

## Outputs

`reports/{T}_{ts}/` bundles → overlay `public/data/llm_overlay.json` (audit-clean only) →
full-text site bundles (`publish_reports.py`) → append-only `rs2_verdict_log.jsonl` ledger →
graded weekly by the screener's `grade_rs2_verdicts.py` (30/91/182/365d vs IWM/SPY/QQQ).

## Where the truth lives

- `CLAUDE.md` — standard of proof (read it first)
- `audit/VALUATION_AUDIT_202608.md` — 2026-08 methodology audit: measured findings,
  effort×value chart, adopted plan (Option 2), standing STOP flags (FX, historical SBC, ΔWC)
- `AUDIT.md`, `SESSION_HANDOFF_*.md` — dated reviews and operational handoffs
- `PLAN_FX_INGESTION_20260814.md` — open FX plan for 20-F filers
