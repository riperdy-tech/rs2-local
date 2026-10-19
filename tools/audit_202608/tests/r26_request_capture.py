"""Shared by test_r26_logging.py and the one-off that produced fixture_data/r26_request_bytes_6bc2ad0.json: the bytes ollama_raw.chat POSTs for
a fixed set of bodies. The fixture was produced by the code of commit 6bc2ad0 (before the turn log existed); the test recomputes the capture
with the logging switched on and off and demands the same bytes."""
import hashlib
import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
for p in (str(AUDIT_DIR), str(AUDIT_DIR.parents[1]), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import test_ollama_raw as t  # noqa: E402
import ollama_raw as raw  # noqa: E402

OPTS = {"num_ctx": 98304, "num_predict": 32768, "seed": 7, "temperature": 0.6, "repeat_penalty": 1.05, "presence_penalty": 0.05}
BODIES = {
    "tools_high_with_system": {"model": "m", "stream": False, "think": "high", "messages": t.FIXTURE_MESSAGES, "tools": t.TOOLS, "options": OPTS},
    "think_off_keep_alive": {"model": "m", "stream": False, "think": False, "keep_alive": "30m",
                             "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], "options": {"seed": 1}},
    "model_system_injected": {"model": "m", "stream": False, "think": "medium", "tools": t.TOOLS,
                              "messages": [{"role": "user", "content": "U"}, {"role": "assistant", "content": "", "thinking": "t",
                                                                               "tool_calls": [{"function": {"name": "web_search", "arguments": {"query": "q"}}}]},
                                           {"role": "tool", "content": "r"}], "options": OPTS},
}


class _Resp:
    def __init__(self, obj):
        self._b = json.dumps(obj).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def capture(monkeypatch):
    """{name: {"bytes": n, "sha256": hex}} of each POST body ollama_raw.chat sends, with a fake urlopen and a fixed model SYSTEM text."""
    import urllib.request
    seen = []

    def fake_urlopen(req, timeout=None):
        if req.full_url.endswith("/api/version"):
            return _Resp({"version": "0.40.3"})
        seen.append(req.data)
        return _Resp({"response": "ok", "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(raw, "ollama_system_text", lambda model: "MODEL SYSTEM TEXT")
    monkeypatch.setattr(raw, "_VERSIONS", {})
    out = {}
    for name, body in BODIES.items():
        seen.clear()
        raw.chat(json.loads(json.dumps(body)), 30, "http://127.0.0.1:1/api/chat")
        (data,) = seen
        out[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return out
