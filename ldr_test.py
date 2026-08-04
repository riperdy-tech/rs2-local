#!/usr/bin/env python3
"""One-off: prove LDR deep-research loop works headless (SearXNG + Ollama + full-page read)."""
import json, time
from pathlib import Path
from local_deep_research.api import quick_summary

SECR = json.loads((Path(__file__).resolve().parent / ".secrets.json").read_text())

overrides = {
    "llm.provider": "ollama",
    "llm.model": "rs2-analyst",
    "llm.ollama.url": "http://localhost:11434",
    "llm.ollama.enable_thinking": False,           # faster for the loop's many calls
    "search.tool": "searxng",                       # local, unlimited (Tavily reserved for quota)
    "search.engine.web.searxng.default_params.instance_url": "http://localhost:8888",
    "search.snippets_only": False,                  # READ full pages, not snippets
    "search.iterations": 2,
    "search.questions_per_iteration": 2,
    "search.max_results": 8,
}
q = "What are the main competitive threats to NVIDIA from custom AI chips (Google TPU, Amazon Trainium, Broadcom ASICs) in 2026?"
t0 = time.time()
res = quick_summary(q, settings_override=overrides)
print(f"\n=== done in {time.time()-t0:.0f}s ===")
print("keys:", list(res.keys()))
summ = res.get("summary", "")
print("summary chars:", len(summ))
print("findings/sources:", len(res.get("findings", []) or res.get("sources", []) or []))
print("\n--- SUMMARY (first 1200 chars) ---\n", summ[:1200])
