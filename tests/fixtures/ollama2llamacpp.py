"""Hardened Ollama /api/chat -> llama.cpp llama-server adapter (Phase 7 serving validation, step 0).

Accepts Ollama's POST /api/chat (stream=false) and forwards it to llama-server's OpenAI-compatible
/v1/chat/completions, translating the reply back. Replaces the exploratory 2026-09-30 adapter, whose
failure paths were undefined. What is defined here:

1. Upstream timeout (default 3600 s, below the harness's 7200 s (no-tools path) and 14400 s (tools path)
   request timeouts; the harness's 1800 s continue_report call, used only after a truncated report, times out
   on its own first). The timeout is urllib's socket timeout, i.e. the wait for
   the response: for a non-streaming request that is the whole generation. On expiry: HTTP 500
   {"error": "upstream_timeout ..."}.
2. Error mapping. The harness handles only HTTP >= 500, so EVERY failure is HTTP 500 with a named cause
   (`cause` key, and the error text starts with it): upstream_timeout, connection_refused, connection_reset,
   upstream_connection_error, context_overflow (llama-server's 400 exceed_context_size_error, with the
   server's message), upstream_4xx, upstream_5xx, upstream_http_unexpected, upstream_bad_json,
   upstream_bad_response, unmapped_finish_reason, bad_request_json, bad_request, adapter_exception. A handler
   exception no longer kills the thread: it is logged with its traceback and answered as adapter_exception.
3. Sampling. temperature, top_p, top_k, min_p, presence_penalty are NEVER forwarded (the server's own settings
   apply). seed and max_tokens (= num_predict) are kept. The stripped fields and their values are recorded in
   the response (`sampling_stripped`) and in the log.
4. Reasoning: message.reasoning_content -> message.thinking. A reply whose content still carries reasoning
   markers gets `reasoning_in_content: true`. The server must run with `--reasoning-format deepseek`.
5. Provenance: every successful response carries `engine` (endpoint, llama.cpp build, model and drafter
   sha256, spec settings, server command-line sha256, adapter and SYSTEM sha256) and per-turn `draft_n` and
   `draft_n_accepted` from llama-server's timings.
6. SYSTEM: the pinned text (read as bytes, decoded UTF-8, no newline translation) is injected when the request
   has no system message; a request's own system message passes through unchanged.

Usage:
  python ollama2llamacpp.py --port 11500 --upstream http://127.0.0.1:8080 --engine-json ARM.json \
      --log-file adapter.jsonl [--system-file SYSTEM.txt] [--upstream-timeout 3600]
GET /adapter/status returns {"in_flight", "oldest_in_flight_s", "served", "errors"} (used by the crash test).
"""
import argparse
import hashlib
import http.client
import json
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_UPSTREAM_TIMEOUT_S = 3600
STRIPPED_SAMPLING_FIELDS = ("temperature", "top_p", "top_k", "min_p", "presence_penalty")
KEPT_OPTIONS = ("num_predict", "seed")
FINISH_TO_DONE = {"stop": "stop", "length": "length", "tool_calls": "stop"}
REASONING_MARKERS = ("<think>", "</think>", "<|channel|>", "<|message|>", "<|start|>", "<|end|>",
                     "<|return|>", "<|constrain|>", "[THINK]", "[/THINK]")
ENGINE_REQUIRED_KEYS = ("endpoint", "llamacpp_build", "model_sha256", "drafter_sha256", "spec",
                        "server_cmdline_sha256")


class AdapterError(Exception):
    """A failure with a name. Always answered as HTTP 500 {"error": "<cause> <detail>", "cause": cause}."""

    def __init__(self, cause, detail=""):
        super().__init__(f"{cause} {detail}".strip())
        self.cause = cause
        self.detail = detail


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def read_system(path):
    """The pinned SYSTEM exactly as stored: bytes, UTF-8, no newline translation. Returns (text, sha256)."""
    raw = open(path, "rb").read()
    return raw.decode("utf-8"), sha256_bytes(raw)


# ---------------------------------------------------------------- request: Ollama -> OpenAI

def to_openai(body, system=None):
    """(OpenAI request dict, info dict). Raises AdapterError('bad_request') on a malformed body."""
    if not isinstance(body, dict):
        raise AdapterError("bad_request", "body is not a JSON object")
    if body.get("stream") is True:
        raise AdapterError("bad_request", "stream=true is not supported; the harness sends stream=false")
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise AdapterError("bad_request", "messages is not a list")
    msgs, pending = [], []
    info = {"system_injected": False, "orphan_tool_results": 0}
    if system is not None and not any(isinstance(m, dict) and m.get("role") == "system" for m in messages):
        msgs.append({"role": "system", "content": system})
        info["system_injected"] = True
    for m in messages:
        if not isinstance(m, dict):
            raise AdapterError("bad_request", "a message is not a JSON object")
        role = m.get("role")
        if role == "assistant":
            out = {"role": "assistant", "content": m.get("content") or ""}
            tcs = []
            for i, tc in enumerate(m.get("tool_calls") or []):
                fn = tc.get("function", {})
                cid = tc.get("id") or f"call_{len(msgs)}_{i}"
                args = fn.get("arguments", {})
                tcs.append({"id": cid, "type": "function",
                            "function": {"name": fn.get("name"),
                                         "arguments": args if isinstance(args, str) else json.dumps(args)}})
            if tcs:
                out["tool_calls"] = tcs
                pending = [(t["id"], t["function"]["name"]) for t in tcs]
            msgs.append(out)
        elif role == "tool":
            cid = m.get("tool_call_id")
            if cid is not None:
                pending = [p for p in pending if p[0] != cid]
            else:
                tname = m.get("tool_name") or m.get("name")
                hit = next((p for p in pending if tname and p[1] == tname), None) if tname else None
                if hit is None and pending:
                    hit = pending[0]
                if hit is not None:
                    pending.remove(hit)
                    cid = hit[0]
                else:
                    cid = f"call_orphan_{len(msgs)}"
                    info["orphan_tool_results"] += 1
            msgs.append({"role": "tool", "tool_call_id": cid, "content": m.get("content") or ""})
        else:
            msgs.append({"role": role, "content": m.get("content") or ""})
    opts = body.get("options") or {}
    req = {"model": body.get("model", "x"), "messages": msgs, "stream": False}
    if body.get("tools"):
        req["tools"] = body["tools"]
    if "num_predict" in opts:
        req["max_tokens"] = opts["num_predict"]
    if "seed" in opts:
        req["seed"] = opts["seed"]
    info["sampling_stripped"] = {k: opts[k] for k in STRIPPED_SAMPLING_FIELDS if k in opts}
    info["ignored_options"] = sorted(set(opts) - set(KEPT_OPTIONS) - set(STRIPPED_SAMPLING_FIELDS)) \
        + (["think"] if "think" in body else [])
    return req, info


# ---------------------------------------------------------------- response: OpenAI -> Ollama

def has_reasoning_markers(text):
    return any(mk in text for mk in REASONING_MARKERS)


def _tool_calls(raw_calls, info):
    out = []
    for i, tc in enumerate(raw_calls or []):
        fn = tc.get("function") or {}
        a = fn.get("arguments")
        if isinstance(a, str):
            if not a.strip():
                a = {}
            else:
                try:
                    parsed = json.loads(a)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    a = parsed
                else:
                    info["unparsed_tool_args"] += 1
                    a = {"_raw": a}
        elif a is None:
            a = {}
        elif not isinstance(a, dict):
            info["unparsed_tool_args"] += 1
            a = {"_raw": a}
        cid = tc.get("id")
        out.append({"id": cid if cid else f"call_resp_{i}", "function": {"name": fn.get("name"), "arguments": a}})
    return out


def to_ollama(resp, model, secs, engine, info):
    """Translate llama-server's reply. Raises AdapterError for a reply that cannot be mapped faithfully."""
    if not isinstance(resp, dict) or not isinstance(resp.get("choices"), list) or not resp["choices"]:
        raise AdapterError("upstream_bad_response", "reply has no choices: " + json.dumps(resp)[:300])
    ch = resp["choices"][0]
    m = ch.get("message") if isinstance(ch, dict) else None
    if not isinstance(m, dict):
        raise AdapterError("upstream_bad_response", "choice has no message: " + json.dumps(ch)[:300])
    fin = ch.get("finish_reason")
    if fin not in FINISH_TO_DONE:
        raise AdapterError("unmapped_finish_reason", f"finish_reason={fin!r}")
    info["unparsed_tool_args"] = 0
    tcs = _tool_calls(m.get("tool_calls"), info)
    content = m.get("content") or ""
    msg = {"role": "assistant", "content": content}
    if m.get("reasoning_content"):
        msg["thinking"] = m["reasoning_content"]
    if tcs:
        msg["tool_calls"] = tcs
    u = resp.get("usage") or {}
    t = resp.get("timings") or {}
    predicted_ms, prompt_ms = t.get("predicted_ms"), t.get("prompt_ms")
    info["timings_missing"] = predicted_ms is None
    eval_ms = secs * 1000 if predicted_ms is None else predicted_ms
    info["reasoning_in_content"] = has_reasoning_markers(content)
    return {"model": model, "message": msg, "done": True,
            "done_reason": FINISH_TO_DONE[fin],
            "eval_count": u.get("completion_tokens"), "prompt_eval_count": u.get("prompt_tokens"),
            "eval_duration": int(eval_ms * 1e6),
            "prompt_eval_duration": int((0 if prompt_ms is None else prompt_ms) * 1e6),
            "total_duration": int(secs * 1e9),
            "draft_n": t.get("draft_n"), "draft_n_accepted": t.get("draft_n_accepted"),
            "reasoning_in_content": info["reasoning_in_content"],
            "sampling_stripped": info["sampling_stripped"],
            "engine": engine}


# ---------------------------------------------------------------- upstream call and error table

def classify_http_error(code, raw):
    text = raw.decode("utf-8", "replace")
    err_type, message = None, text
    try:
        j = json.loads(text)
    except ValueError:
        j = None
    if isinstance(j, dict) and isinstance(j.get("error"), dict):
        err_type = j["error"].get("type")
        message = j["error"].get("message") or text
        if err_type == "exceed_context_size_error":
            extra = {k: j["error"][k] for k in ("n_prompt_tokens", "n_ctx") if k in j["error"]}
            return AdapterError("context_overflow", f"{message} {json.dumps(extra) if extra else ''}".strip())
    elif isinstance(j, dict) and isinstance(j.get("error"), str):
        message = j["error"]
    if code == 400 and "exceeds the available context size" in message:
        return AdapterError("context_overflow", message)
    if 400 <= code < 500:
        return AdapterError("upstream_4xx", f"HTTP {code}: {message[:500]}")
    if code >= 500:
        return AdapterError("upstream_5xx", f"HTTP {code}: {message[:500]}")
    return AdapterError("upstream_http_unexpected", f"HTTP {code}: {message[:500]}")


def call_upstream(url, payload, timeout):
    """(parsed JSON, seconds). Every failure is an AdapterError with a name."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise classify_http_error(e.code, e.read()) from e
    except TimeoutError as e:
        raise AdapterError("upstream_timeout", f"after {timeout}s waiting for llama-server") from e
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise AdapterError("upstream_timeout", f"after {timeout}s connecting to llama-server") from e
        if isinstance(reason, ConnectionRefusedError):
            raise AdapterError("connection_refused", f"{url}: {reason}") from e
        if isinstance(reason, ConnectionError):
            raise AdapterError("connection_reset", f"{url}: {reason}") from e
        raise AdapterError("upstream_connection_error", f"{url}: {reason!r}") from e
    except ConnectionRefusedError as e:
        raise AdapterError("connection_refused", f"{url}: {e}") from e
    except (ConnectionError, http.client.HTTPException) as e:
        raise AdapterError("connection_reset", f"{url}: {type(e).__name__}: {e}") from e
    secs = time.time() - t0
    try:
        return json.loads(raw.decode("utf-8")), secs
    except ValueError as e:
        raise AdapterError("upstream_bad_json", f"{e}; first bytes: {raw[:200]!r}") from e


# ---------------------------------------------------------------- server

class Adapter:
    """Configuration plus counters shared by the handler threads."""

    def __init__(self, upstream, timeout=DEFAULT_UPSTREAM_TIMEOUT_S, system=None, engine=None, log_path=None):
        self.up_url = upstream.rstrip("/") + "/v1/chat/completions"
        self.timeout = timeout
        self.system = system
        self.engine = engine or {}
        self.log_path = log_path
        self.lock = threading.Lock()
        self.in_flight = {}
        self.served = 0
        self.errors = 0
        self._next_id = 0

    def begin(self):
        with self.lock:
            self._next_id += 1
            rid = self._next_id
            self.in_flight[rid] = time.time()
        return rid

    def end(self, rid, ok):
        with self.lock:
            self.in_flight.pop(rid, None)
            self.served += 1
            self.errors += 0 if ok else 1

    def status(self):
        with self.lock:
            now = time.time()
            oldest = max((now - t for t in self.in_flight.values()), default=0.0)
            return {"in_flight": len(self.in_flight), "oldest_in_flight_s": round(oldest, 2),
                    "served": self.served, "errors": self.errors}

    def log(self, rec):
        if not self.log_path:
            return
        with self.lock, open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")


def make_handler(adapter):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, out):
            data = json.dumps(out).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/adapter/status":
                self._send(200, adapter.status())
            else:
                self._send(404, {"error": f"unsupported_path {self.path}", "cause": "unsupported_path"})

        def do_POST(self):
            t0 = time.time()
            rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "path": self.path, "arm": adapter.engine.get("arm")}
            rid = adapter.begin()
            ok = False
            try:
                code, out = self._handle(rec)
                ok = code == 200
            except AdapterError as e:
                code, out = 500, {"error": f"{e.cause} {e.detail}".strip(), "cause": e.cause}
            except Exception as e:  # a named 500 instead of a dead thread and a dropped connection
                code, out = 500, {"error": f"adapter_exception {type(e).__name__}: {e}", "cause": "adapter_exception"}
                rec["traceback"] = traceback.format_exc()
            rec.update({"wall_s": round(time.time() - t0, 3), "http_status": code})
            if code != 200:
                rec["cause"], rec["error"] = out["cause"], out["error"][:600]
            adapter.end(rid, ok)
            adapter.log(rec)      # logged before the reply is written, so a kill right after the reply loses nothing
            try:
                self._send(code, out)
            except (BrokenPipeError, ConnectionError) as e:
                adapter.log({"ts": rec["ts"], "arm": rec["arm"], "event": "client_gone", "http_status": code,
                             "client_gone": f"{type(e).__name__}: {e}"})

        def _handle(self, rec):
            if self.path != "/api/chat":
                raise AdapterError("unsupported_path", self.path)
            n = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError as e:
                raise AdapterError("bad_request_json", str(e)) from e
            req, info = to_openai(body, adapter.system)
            rec.update({k: info[k] for k in ("system_injected", "orphan_tool_results", "sampling_stripped",
                                             "ignored_options")})
            resp, secs = call_upstream(adapter.up_url, req, adapter.timeout)
            out = to_ollama(resp, body.get("model"), secs, adapter.engine, info)
            t = resp.get("timings") or {}
            pps = t.get("predicted_per_second")
            if pps is None and t.get("predicted_n") is not None and t.get("predicted_ms"):
                pps = t["predicted_n"] / t["predicted_ms"] * 1000
            rec.update({"done_reason": out["done_reason"], "prompt_tokens": out["prompt_eval_count"],
                        "completion_tokens": out["eval_count"], "tok_s": None if pps is None else round(pps, 2),
                        "draft_n": out["draft_n"], "draft_n_accepted": out["draft_n_accepted"],
                        "n_tool_calls": len(out["message"].get("tool_calls") or []),
                        "unparsed_tool_args": info["unparsed_tool_args"],
                        "reasoning_in_content": info["reasoning_in_content"],
                        "timings_missing": info["timings_missing"]})
            return 200, out

        def log_message(self, *a):
            pass

    return H


def make_server(adapter, port, host="127.0.0.1"):
    srv = ThreadingHTTPServer((host, port), make_handler(adapter))
    srv.daemon_threads = True
    return srv


def load_engine(path, adapter_sha256, system_sha256, timeout):
    engine = json.load(open(path, encoding="utf-8"))
    missing = [k for k in ENGINE_REQUIRED_KEYS if k not in engine]
    if missing:
        raise SystemExit(f"engine json {path} is missing keys: {missing}")
    engine = dict(engine, adapter_sha256=adapter_sha256, system_sha256=system_sha256, upstream_timeout_s=timeout)
    return engine


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--upstream", required=True, help="llama-server base URL, e.g. http://127.0.0.1:8080")
    ap.add_argument("--engine-json", required=True)
    ap.add_argument("--log-file", required=True)
    ap.add_argument("--system-file")
    ap.add_argument("--upstream-timeout", type=float, default=DEFAULT_UPSTREAM_TIMEOUT_S)
    a = ap.parse_args(argv)
    system, system_sha = (read_system(a.system_file) if a.system_file else (None, None))
    engine = load_engine(a.engine_json, sha256_file(__file__), system_sha, a.upstream_timeout)
    adapter = Adapter(a.upstream, a.upstream_timeout, system, engine, a.log_file)
    srv = make_server(adapter, a.port)
    print(f"adapter listening on 127.0.0.1:{a.port} -> {adapter.up_url} timeout={a.upstream_timeout}s "
          f"system_sha256={system_sha}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
