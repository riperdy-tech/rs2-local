#!/usr/bin/env python3
"""api_chat.py — OpenAI-compatible chat backend for RS2 (run_rs2.py --api).

Drop-in replacement for run_rs2.ollama_chat: same signature, same return (the assistant
text), so every stage / retry / final-assembly call routes here unchanged when --api is set.

Differences vs the local rs2-analyst handled HERE, not in run_rs2:
  * RS2.txt is BAKED into the local Ollama model as its system prompt (Modelfile); an API
    model has no such baking, so RS2.txt is loaded once and sent as the system message on
    every call — the stages assume the framework is already in the model's head.
  * `ctx`/`think` are Ollama-isms: API models manage their own context (ctx ignored) and
    reasoning models do their own thinking (think ignored; reasoning_content, if a provider
    returns it, is discarded — only the final answer text is used, matching Ollama's
    think-stripped output).

Key lives in RS2 Local/.secrets.json (gitignored) under config's api_key_name. Never logged.
CLI smoke test:  python api_llm/api_chat.py "Say OK."
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../RS2 Local/api_llm
ROOT = HERE.parent                              # .../RS2 Local
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
_SYSTEM = None
_KEY = None


def _system_prompt():
    global _SYSTEM
    if _SYSTEM is None:
        _SYSTEM = (ROOT / "RS2.txt").read_text(encoding="utf-8", errors="ignore")
    return _SYSTEM


def _api_key():
    global _KEY
    if _KEY is None:
        name = CONFIG.get("api_key_name", "LLM_API_KEY")
        try:
            _KEY = json.loads((ROOT / ".secrets.json").read_text(encoding="utf-8")).get(name)
        except Exception:
            _KEY = None
        if not _KEY:
            raise RuntimeError(
                f"API key '{name}' not found in {ROOT / '.secrets.json'} — add it there "
                "(the file is gitignored; never commit keys).")
    return _KEY


def _log_usage(usage):
    """Append one call's token usage to api_llm/usage_log.jsonl for per-ticker cost accounting.
    Ticker comes from the RS2_TICKER env var (set by the test driver); DeepSeek also reports
    prompt cache hit/miss splits, which price very differently."""
    try:
        rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "ticker": os.environ.get("RS2_TICKER", "?"), "model": CONFIG.get("model"),
               "prompt_tokens": usage.get("prompt_tokens"),
               "completion_tokens": usage.get("completion_tokens"),
               "cache_hit": usage.get("prompt_cache_hit_tokens"),
               "cache_miss": usage.get("prompt_cache_miss_tokens"),
               "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")}
        with open(HERE / "usage_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def api_chat(content, ctx=None, think=True, retries=2, temperature=None, timeout=600,
             max_tokens=None):
    """POST {base_url}/chat/completions with RS2.txt as system prompt. Returns assistant text."""
    body = json.dumps({
        "model": CONFIG["model"],
        "messages": [{"role": "system", "content": _system_prompt()},
                     {"role": "user", "content": content}],
        "temperature": CONFIG.get("temperature", 0.4) if temperature is None else temperature,
        "max_tokens": max_tokens or CONFIG.get("max_tokens", 8192),
        "stream": False,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {_api_key()}"}
    headers.update(CONFIG.get("extra_headers") or {})
    url = CONFIG["base_url"].rstrip("/") + "/chat/completions"
    last = None
    for attempt in range(max(retries, 1)):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            msg = (out.get("choices") or [{}])[0].get("message", {})
            text = msg.get("content") or ""
            if not text.strip():
                raise RuntimeError(f"empty completion (finish_reason="
                                   f"{(out.get('choices') or [{}])[0].get('finish_reason')})")
            _log_usage(out.get("usage") or {})
            return text
        except Exception as e:
            last = e
            wait = 8 * (attempt + 1)      # 429s / transient 5xx: brief backoff then retry
            print(f"   [api retry {attempt+1}/{retries} after {wait}s: {str(e)[:100]}]", flush=True)
            time.sleep(wait)
    raise last


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    prompt = " ".join(sys.argv[1:]) or "Reply with exactly: OK <your model name>"
    print(f"[api_chat] {CONFIG['base_url']}  model={CONFIG['model']}")
    print(api_chat(prompt, timeout=120)[:2000])
