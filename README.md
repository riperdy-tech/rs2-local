# RS2 Local — running the v2.0 analysis engine on local Qwen3

Goal: make a **24GB RTX 3090 + Ollama** run `RS2.txt` (17-layer investment
engine) as close to a frontier model (Opus) as the hardware allows.

## What was built

| Artifact | Purpose |
|---|---|
| `RS2-Analyst.Modelfile` | Bakes `RS2.txt` as the system prompt + tuned sampling params + thinking. |
| `rs2-analyst` (Ollama model) | The configured analyst. `ollama run rs2-analyst`. |
| `Run-RS2.ps1` | Staged pipeline runner — the main fidelity lever. |
| `data/TEMPLATE.md` | Manual fallback (only if you bypass the data pipeline). |
| `reports/` | Per-run output (one file per stage + `FINAL.md`). |

## Data sourcing pipeline (Phase 2 — the real way to run it)

RS2 forbids the model from recalling financials from memory. Instead of manual
entry, the Python pipeline feeds it **verified, sourced data** from three buckets:

| Bucket | Source | Files | RS2 layers |
|---|---|---|---|
| **A — Screener (daily)** | `…\Stock Screener\Stock Screener\public\data\` | `financials/{T}.json`, `reverse_scores.json`, `overlay_signals.json`, `eps_trajectory.json`, `analyst_coverage.json`, `fundamentals_history.json`, `macro_state.json` | L0–L5 financials, valuation backbone, macro (valuation_models.json no longer fed — replaced by the in-process `valuation_backbone.py`) |
| **B — yfinance (on demand)** | `enrich_ticker.py` → `enrich/{T}.json` | short interest, institutional/insider %, options skew/IV, DXY | L5.5 behavioral, L1 DXY |
| **C — AgentWebSearch (live)** | `research_agent.py` → `research/{T}.md` | news, catalysts, short-seller/activist, regulatory, competitive — **real Chrome, no API keys, source-cited** | L3.5, L7, L9 |

Components:
| File | Role |
|---|---|
| `config.json` | All paths + ctx/model settings (single source of truth). |
| `rs2_data.py` | Port of the screener's `lib/prompt-builder.ts` — assembles the verified-data context (empty-safe; tags gaps "not provided"). |
| `enrich_ticker.py` | Bucket B fetcher (`python enrich_ticker.py NVDA`). |
| `research_agent.py` | Bucket C — runs under the AgentWebSearch venv; deterministic, source-cited brief (no LLM-fabricated links). |
| `run_rs2.py` | **Orchestrator** — acquires B+C, assembles data, drives the 6-stage + final pipeline over Ollama REST. |

### Run it
```bash
# one-time: AgentWebSearch (real Chrome web search, no API keys)
cd AgentWebSearch-MCP && python -m venv venv
./venv/Scripts/python -m pip install -r requirements.txt
./venv/Scripts/python -c "import chrome_launcher as c; [c.start_chrome(p) for p in ('google','brave')]"

# full analysis (fetches enrich + research, then runs the engine)
python run_rs2.py NVDA
python run_rs2.py NVDA --no-research      # skip web (screener+enrich only)
python run_rs2.py NVDA --no-enrich --no-research   # reuse cached data
# -> reports/NVDA_<ts>/S1..S6.md + FINAL.md + _fed_data.md
```

### Context budget (revised)
Real payload (RS2.txt ~5.2k tok + fed data ~4k + accumulating stages) overflows
16384, so **stages run at 24576**, and **final assembly at 32768** with a *slim
verified anchor* (not the full research brief — stages already consumed it) so the
13-section report generates without truncating. Set in `config.json`.

### Regime safety
The Macro Regime Indicator's `current_regime.json` can be `synthetic_sample`
(future-dated). `rs2_data.py` only uses its regime probabilities when the file is
fresh (`regime_max_age_days`); otherwise it feeds the **real** `macro_state.json`
(FRED) and the model derives the 4-regime distribution itself.

## Deterministic valuation engine (the MoS fix)

A 3B-active MoE cannot reliably chain a 10-year DCF in-prompt — it shortcuts to
`fwd-EPS × P/E` or botches cycle-normalization (we saw MoS of −171% and −885%). So
valuation is split: **the LLM picks assumptions, Python does the math.**

| File | Role |
|---|---|
| `valuation_engine.py` | Deterministic IV/MoS/CI (port of screener `lib/dcf.ts`). Engines 1–5, scenario weighting, input clamps, unit-scale sanity. |
| `valuation_io.py` | Extract the LLM's fenced ```json assumptions (repair retry). |
| `run_rs2.py` (S3/S4) | S3 → LLM emits `valuation_inputs` JSON (engine, growth/wacc/terminal per scenario, or engine-2 EPS / engine-3 segments); Python computes per-scenario IV. S4 → LLM emits `scenario_probs`; Python computes expected price + MoS + CIs. S5/S6/final consume the computed numbers verbatim. |

Guardrails:
- **Units in billions** (money & shares cancel to $/share — no scale slips).
- `net_cash`/`shares` from fed data (authoritative); **`base_cf` bounded** to
  `[0.5×FCF, owner-earnings≈OCF−½·capex]` so the model can normalize a capex-trough
  FCF up (e.g. GOOG $73B→$119B) but never run away.
- **compute → check → revise**: if scenario IVs are non-monotonic or |MoS|>70%, re-prompt
  the model once with the bad result. (This rescued GEV from −885% → −15%.)

Result vs a frontier model (ChatGPT): **NVDA $186.69 / GPT $186 · GOOG $308 / $347 ·
GEV $900 / $768** — all actions in the HOLD family, MoS sane and reproducible. The
chosen assumptions are saved to `reports/{T}_{ts}/S3_valuation_inputs.json` for audit.

## Why two parts, not one prompt

`qwen3.6:35b-a3b` is a **Mixture-of-Experts**: 36B total but only ~3B params
active per token. It is fast, but per-token reasoning ≈ a small model. Opus
holds all 17 layers + self-critique in one pass; a 3B-active expert will
**drift, skip layers, and hallucinate numbers** if you paste the whole engine
and say "analyze TSLA."

So fidelity = **(1) tune + bake the prompt** *and* **(2) decompose** the
engine into stages, feeding each stage the prior outputs. Decomposition is the
bigger win — it keeps the small active expert on-rails the way a big model's
working memory does for free.

## Tuned parameters (and why)

| Param | Default | Set to | Reason |
|---|---|---|---|
| `temperature` | 1.0 | **0.4** | Numeric discipline, not creativity. |
| `presence_penalty` | 1.5 | **0.1** | 1.5 punishes repeating the `[Actual]`/`[Estimate]` tags & fixed section headers RS2 *requires*. |
| `top_p` | 0.95 | **0.9** | Tighter sampling. |
| `repeat_penalty` | 1.0 | **1.05** | Mild anti-loop. |
| `num_ctx` | — | **16384** | 100% GPU, no CPU spill, ~36% faster gen. Final-assembly stage overrides to 24576 (needs room for all prior stages). |
| thinking | — | **on** | Qwen3 reasoning mode; big quality gain on multi-step logic. |

Tune in `RS2-Analyst.Modelfile`, then rebuild:
```
ollama create rs2-analyst -f RS2-Analyst.Modelfile
```

## Usage

Full staged analysis (recommended):
```powershell
# 1. copy template, fill in real numbers
Copy-Item .\data\TEMPLATE.md .\data\TSLA.md   # then edit TSLA.md

# 2. run the pipeline
.\Run-RS2.ps1 -Ticker TSLA -DataFile .\data\TSLA.md
# -> reports\TSLA_<timestamp>\S1..S6 + FINAL.md
```

Quick single question (no pipeline):
```
ollama run rs2-analyst
>>> Run LAYER 0 only for NVDA. Stop after Layer 0.
```

Flags: `-NoThink` (faster, lower quality), `-Model <name>`, `-StageCtx <n>`
(default 16384, 100% GPU), `-FinalCtx <n>` (default 24576, assembly stage).

### Measured: 16384 vs 24576 (qwen3.6:35b-a3b, RTX 3090)

| | 16384 | 24576 |
|---|---|---|
| GPU split | 100% GPU | 96% / 4% CPU |
| Gen speed | 121.8 tok/s | 89.8 tok/s (−36%) |
| Prompt eval | 2534 tok/s | 1753 tok/s |

So stages run at 16384 (fast, full GPU); only final assembly pays the 24576
cost because it must hold all six prior stage outputs (~15.6k tokens).

## The data problem (still open)

The engine needs real numbers (price, financials, filings). Options, in order
of reliability:
1. **Manual** — fill `data/<TICKER>.md`. Most reliable; you control sourcing.
2. **Script-fed** — a fetcher (e.g. Python `yfinance`) writes the data sheet,
   then the pipeline runs. Less work per analysis, more setup.
3. **Hybrid** — script pulls market/financials, you add qualitative items.

Without data the model still runs but tags everything `[Unconfirmed]` /
`[Assumption]` and `Model Confidence` drops — exactly as RS2 mandates.

## Known limits vs Opus

- No live data / web — must be fed (above).
- 3B-active reasoning < frontier on the hardest quant chains; decomposition
  narrows but doesn't close the gap.
- Base-rate / historical figures come from the model's training memory — verify
  before trusting them in a real decision.
