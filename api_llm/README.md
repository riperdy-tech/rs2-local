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
