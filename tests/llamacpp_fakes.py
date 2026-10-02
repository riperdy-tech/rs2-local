"""Test doubles for the llamacpp provider and its server lifecycle (Muse integration, M8). CPU only: no GPU, no model, no
network beyond 127.0.0.1.

FakeLlama      an in-process OpenAI-compatible HTTP server that answers like llama-server b11272: the response shape
               (id, object, usage, timings with draft_n / draft_n_accepted), the 400 `exceed_context_size_error` for a
               prompt over the window, 503 while "loading", and a connection reset.
muse_env       a fixture: FakeLlama + the config and engine.json that make `llm_provider` see a live, pinned server.
"""
import copy
import json
import os
import select
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "audit_202608"))

import rs2_data  # noqa: E402
import llm_provider  # noqa: E402

# The suite's autouse fixtures replace the shared `urllib.request.urlopen` with a function that raises "Network disabled in
# tests" (conftest.py, _isolate_sec_guidance_in_tests). The fakes below are real loopback HTTP servers, so tests that talk to
# them put this opener back: it is built from urllib's own handlers (no proxies), independent of that module attribute.
_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def loopback_urlopen(url, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, **kw):
    if kw:
        raise TypeError(f"loopback_urlopen takes no {sorted(kw)}")
    return _LOOPBACK_OPENER.open(url, data, timeout)


REAL_SYSTEM_FILE = ROOT / "charters" / "SYSTEM_muse_v33.txt"
SPEC = {"type": "draft-dflash", "n_max": 15, "ngld": 99}


def timings(prompt_n=100, predicted_n=20, draft_n=30, draft_n_accepted=21, prompt_ms=500.0, predicted_ms=400.0):
    """llama-server's `timings` block (b11272 with a drafter)."""
    return {"cache_n": 0, "prompt_n": prompt_n, "prompt_ms": prompt_ms,
            "prompt_per_token_ms": prompt_ms / prompt_n if prompt_n else 0.0,
            "prompt_per_second": prompt_n / prompt_ms * 1000 if prompt_ms else 0.0,
            "predicted_n": predicted_n, "predicted_ms": predicted_ms,
            "predicted_per_token_ms": predicted_ms / predicted_n if predicted_n else 0.0,
            "predicted_per_second": predicted_n / predicted_ms * 1000 if predicted_ms else 0.0,
            "draft_n": draft_n, "draft_n_accepted": draft_n_accepted}


def completion(content="hello", finish="stop", tool_calls=None, reasoning=None, usage=(100, 20), tim="default", model="muse"):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    out = {"choices": [{"finish_reason": finish, "index": 0, "message": msg}], "created": 1790000000, "model": model,
           "system_fingerprint": "b11272-fake", "object": "chat.completion",
           "usage": {"completion_tokens": usage[1], "prompt_tokens": usage[0], "total_tokens": sum(usage)},
           "id": "chatcmpl-fake"}
    if tim == "default":
        out["timings"] = timings(prompt_n=usage[0], predicted_n=usage[1])
    elif tim is not None:
        out["timings"] = tim
    return out


def overflow_body(n_prompt=101391, n_ctx=98304):
    """What llama-server answers (HTTP 400) to a prompt over its window (P7 part C2)."""
    return {"error": {"code": 400, "type": "exceed_context_size_error", "n_prompt_tokens": n_prompt, "n_ctx": n_ctx,
                      "message": f"request ({n_prompt} tokens) exceeds the available context size ({n_ctx} tokens), "
                                 "try increasing it"}}


def tool_call(name="search_web", args='{"query": "q"}', cid="call_1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}


class FakeLlama:
    """`script` is a list of behaviours consumed in order (the last repeats): ("json", status, obj), ("raw", status,
    bytes), ("sleep", seconds, obj), ("watch", seconds, obj), ("reset",) or a callable(request_body) returning one of those.
    "watch" is "sleep" that notices the client closing the connection (llama-server stops a request whose client went away):
    it sets `client_closed_at` (seconds after the request arrived) and answers nothing. `health` is the
    (status, obj) GET /health answers, or a callable() returning it; `health_delay` delays that answer."""

    def __init__(self):
        self.requests = []
        self.health_calls = 0
        self.script = []
        self.client_closed_at = None
        self.health = (200, {"status": "ok"})
        self.health_delay = 0.0
        outer = self

        class H(BaseHTTPRequestHandler):
            def _send(self, status, data):
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            def do_GET(self):
                if self.path == "/health":
                    outer.health_calls += 1
                    time.sleep(outer.health_delay)
                    st, obj = outer.health() if callable(outer.health) else outer.health
                    self._send(st, json.dumps(obj).encode())
                else:
                    self._send(404, b"{}")

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n))
                outer.requests.append(body)
                beh = outer.script[min(len(outer.requests) - 1, len(outer.script) - 1)]
                if callable(beh):
                    beh = beh(body)
                kind = beh[0]
                if kind == "reset":
                    self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    self.connection.close()
                    return
                if kind == "watch":
                    t0 = time.time()
                    while time.time() - t0 < beh[1]:
                        r, _, _ = select.select([self.connection], [], [], 0.02)
                        if r:
                            try:
                                gone = self.connection.recv(1, socket.MSG_PEEK) == b""
                            except OSError:
                                gone = True
                            if gone:
                                outer.client_closed_at = time.time() - t0
                                return
                    kind, beh = "json", ("json", 200, beh[2])
                if kind == "sleep":
                    time.sleep(beh[1])
                    kind, beh = "json", ("json", 200, beh[2])
                self._send(beh[1], beh[2] if kind == "raw" else json.dumps(beh[2]).encode())

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def engine_record(cfg, **over):
    """The engine.json M3 writes, built here from the config's pins (independent of llamacpp_server)."""
    rec = {"pid": os.getpid(), "endpoint": f"http://{cfg['host']}:{cfg['port']}", "build": cfg["build"],
           "build_manifest_sha256": cfg["build_manifest_sha256"], "model_sha256": cfg["model_sha256"],
           "drafter_sha256": cfg["drafter_sha256"], "spec": dict(SPEC),
           "server_cmdline_sha256": cfg["server_cmdline_sha256"], "system_sha256": cfg["system_sha256"],
           "provider_sha256": llm_provider.provider_sha256(), "reasoning_format": "deepseek",
           "vram_loaded_mib": 21937, "started_at": "2026-10-02T13:00:00"}
    rec.update(over)
    return rec


class MuseEnv:
    def __init__(self, fake, cfg, engine_dir):
        self.fake, self.cfg, self.engine_dir = fake, cfg, engine_dir

    @property
    def engine_file(self):
        return self.engine_dir / llm_provider.ENGINE_FILE

    def write_engine(self, **over):
        self.engine_dir.mkdir(parents=True, exist_ok=True)
        self.engine_file.write_text(json.dumps(engine_record(self.cfg, **over), indent=2), encoding="utf-8")

    def post(self, body, timeout=30):
        """(HTTP status, body) of llm_provider.chat, the way the adapter's HTTP answer looked."""
        try:
            return 200, llm_provider.chat(body, timeout)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


def chat_body(**over):
    b = {"model": "muse-glimmer-30b-ud-q5km-dflash2-n15-charter-v3.3", "stream": False,
         "messages": [{"role": "user", "content": "hi"}], "options": {"num_predict": 64, "seed": 7}}
    b.update(over)
    return b


@pytest.fixture
def fake_llama(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", loopback_urlopen)
    f = FakeLlama()
    yield f
    f.close()


@pytest.fixture
def muse_env(tmp_path, monkeypatch, fake_llama):
    """The provider sees a live, pinned, healthy server: config says llamacpp, engine.json matches it, this process's PID
    stands for llama-server's, and the fake answers /health with 200."""
    cfg = copy.deepcopy(rs2_data.CONFIG["llamacpp"])
    cfg["port"] = fake_llama.port
    cfg["system_file"] = str(REAL_SYSTEM_FILE)           # absolute: HERE / absolute is the absolute path
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "llamacpp")
    monkeypatch.setitem(rs2_data.CONFIG, "depth_model", cfg["model_tag"])
    monkeypatch.setitem(rs2_data.CONFIG, "llamacpp", cfg)
    engine_dir = tmp_path / "cache_llamacpp"
    monkeypatch.setattr(llm_provider, "ENGINE_DIR", engine_dir)
    env = MuseEnv(fake_llama, cfg, engine_dir)
    env.write_engine()
    return env
