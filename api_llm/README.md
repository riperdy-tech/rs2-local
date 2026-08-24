# api_llm — cloud-LLM A/B backend for RS2

Run the EXACT same RS2 pipeline (same prompts, same staged S1→S6 flow, same deterministic
valuation backbone + don't-chase brake) but with a cloud model over an OpenAI-compatible
API instead of the local Ollama `rs2-analyst`.

## Setup (one time)
1. Add your key to `RS2 Local/.secrets.json` (NOT here, NOT in config.json):
   ```json
   { "LLM_API_KEY": "sk-..." }
   ```
2. Edit `api_llm/config.json`:
   - `base_url` — any OpenAI-compatible endpoint. Default OpenRouter (one key, any model:
     GPT / Claude / DeepSeek / Qwen / Llama...). Also works: api.openai.com/v1,
     api.deepseek.com/v1, api.groq.com/openai/v1, etc.
   - `model` — provider's model id, e.g. `deepseek/deepseek-chat-v3`, `openai/gpt-4o`.
3. Smoke test:  `python api_llm/api_chat.py`  → should print `OK <model>`.

## Run
```
python run_rs2.py NVDA --api                # full pipeline on the cloud model
python run_rs2.py NVDA --api --valonly      # fast valuation-only pass
```

## What changes vs local (and what doesn't)
- RS2.txt is sent as the system prompt on every call (locally it's baked into the
  Ollama Modelfile).
- Reports are ISOLATED to `api_llm/reports/{T}_{ts}/` — the orchestrator/overlay
  aggregate only the main `reports/`, so API test verdicts can NEVER leak to the website.
- No VRAM management for the analyst (nothing loaded); deep research still runs the
  LOCAL rs2-research model via LDR (pass `--no-research` to skip if the brief is cached
  or you want a pure-API run).
- Everything else identical: fed data blocks, staged prompts, valuation backbone,
  stance parsing, brake, verdict.json schema — so reports are directly comparable
  against `reports/` and `fable_runs/`.

## Comparing results
The output tree matches the local one (S1..S6.md, FINAL.md, verdict.json), so any
comparison tooling can be pointed at `api_llm/reports` instead of `reports`.

---

# deep_api_run.py — the depth tier on a cloud model

`api_chat.py` above backs the OLD `run_rs2.py --api` pipeline. `deep_api_run.py` is separate: it
runs the CURRENT depth tier (`depth_pipeline.py` -> `consensus_valuation.py`) logic on a cloud
model. It exists because the depth pipeline is Ollama-native and, by standing operator order, the
local engine is never modified — so the cloud path lives in its own file and imports the engine
read-only (`cv.extract_iv`, `cv.plausibility`, `dp.band_verdict`, `at.TOOLS`).

It writes only under `api_llm/deep_api/`. It never appends to `cache/depth_ledger.jsonl`,
`cache/depth_overlay.json` or `reports/`, so a cloud verdict can never reach the live site.

## Two modes

```
python api_llm/deep_api_run.py JKHY --dir JKHY_20260824_114148   # replay (A/B)
python api_llm/deep_api_run.py NVDA --fresh                      # fallback (local box down)
bash api_llm/deep_api_batch.sh queue.txt 3                       # many, 3 at a time
```

**Replay** re-runs a ticker the local tier already finished, on that run's frozen `_pack.md` —
byte-identical input to both models, so a difference in verdict is a difference in model.

**Fallback** (`--fresh`) builds the pack from current data with the same `capability_test`
builder, for a name the local tier has not done. Use when Ollama is down or the GPU is busy.

## What a --fresh verdict is not

A `--fresh` run is NOT equivalent to a local depth verdict, for reasons that are structural:

- SECTION 11 of the pack is a research brief written by the LOCAL `rs2-research` model through
  LDR. With the local box down it cannot be refreshed. The run uses whatever `research/{T}.md`
  holds and prints its age; if absent, the pack has no SECTION 11. The model's own search tools
  (~14 queries per sample) only partly cover the gap.
- The search tools call the LOCAL SearXNG. If it is unreachable `search_web` returns an error to
  the model instead of failing the run, so a run can silently degrade to no-research. `--fresh`
  probes it first and says so.
- Every output carries `pack_source`, `research_brief_age_days` and `searxng_up`, so a verdict
  produced under degraded conditions stays identifiable afterwards.

## Mirrored vs deliberately not mirrored

Mirrored from the local tier: 3 samples, tools available (the model decides whether to call
them), the same SearXNG, the same 12-call research budget and forced-conclusion prompt, the same
IV extraction, plausibility guard and band-direction verdict rule.

Not mirrored, each for a measured reason (DeepSeek API docs, checked 2026-08-24):

- `temperature` / `top_p` / `top_k` / penalties are NOT sent. DeepSeek's thinking mode does not
  support them — they are silently ignored, so porting Qwen's 0.6/0.95/20 thinking profile would
  be a no-op dressed up as a mirror. Each model runs at its own vendor defaults.
- `seed` is NOT sent (undocumented). Local seeds 1000+i, so its three samples are one frozen,
  reproducible realization; the cloud's three are independent draws. **Cloud `spread_pct` is
  therefore not comparable like-for-like with local's.**
- `reasoning_effort: "high"` is DeepSeek's scale. Qwen's `high` maps through its template to
  `xhigh`, Qwen's maximum; DeepSeek has a further `max` above `high`. Comparable in intent only.
- With tools in play, DeepSeek requires `reasoning_content` to be echoed back on every
  subsequent request or it returns 400. Ollama has no such rule.

## Measured, 28 tickers, 2026-08-24

79% direction agreement with the local arm (22/28), 5.7x faster, $4.98 total. Full write-up:
`DEEPSEEK_V4_FLASH_AB_20260824.md`. Neither arm is graded against outcomes yet.
