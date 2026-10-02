"""llm_provider.py — the one door every analyst-model call of the depth path goes through.

`chat(body, timeout)` takes the Ollama /api/chat body the harness builds and returns an Ollama-shaped response.

  depth_provider "ollama"    today's request, byte for byte: POST of json.dumps(body) to the local Ollama.
  depth_provider "llamacpp"  the validated Phase 7 adapter (ollama2llamacpp.py, sha256 2d57497f...), in process:
                             translate to llama-server's OpenAI endpoint and back, with the adapter's constants, error
                             table, sampling rule, reasoning rule and SYSTEM injection. The llama-server process itself
                             is owned by llamacpp_server.py, which writes cache/llamacpp/engine.json; this module reads
                             that file before every request and refuses (HTTP 500 `engine_not_ready`) without a live,
                             pinned, healthy server.

A failure under "llamacpp" raises urllib.error.HTTPError with code 500 and the JSON body
{"error": "<cause> <detail>", "cause": "<cause>"} - exactly what the adapter answered over HTTP - so every caller's
existing HTTP >= 500 path runs unchanged. The one exception is the caller's own timeout firing first, which raises
the TimeoutError urllib would have raised at the caller (the adapter topology: the harness's timeout sat outside the
adapter's).

The translation functions below are the adapter's, ported line for line (tests/fixtures/ollama2llamacpp.py is the
byte copy the tests compare them with). Do not "improve" them: the P7 validation covers exactly this behaviour.
"""
import email.message
import hashlib
import http.client
import io
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

import rs2_data  # noqa: E402

# The address every call site hard-coded before this module existed (analyst_tools.OLLAMA and the literals in
# consensus_valuation.py). Kept as the one literal; analyst_tools.OLLAMA stays defined for the tests and tools that import it.
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
PROVIDERS = ("ollama", "llamacpp")

ENGINE_DIR = HERE / "cache" / "llamacpp"           # tests point this at a temporary folder
ENGINE_FILE = "engine.json"
HEALTH_TIMEOUT_S = 5

STRIPPED_SAMPLING_FIELDS = ("temperature", "top_p", "top_k", "min_p", "presence_penalty")
KEPT_OPTIONS = ("num_predict", "seed")
FINISH_TO_DONE = {"stop": "stop", "length": "length", "tool_calls": "stop"}
REASONING_MARKERS = ("<think>", "</think>", "<|channel|>", "<|message|>", "<|start|>", "<|end|>",
                     "<|return|>", "<|constrain|>", "[THINK]", "[/THINK]")

# What llamacpp_server.start() launches, as the pins M3 writes into engine.json (the command line is hashed as a whole;
# these three are the readable parts of it).
SPEC = {"type": "draft-dflash", "n_max": 15, "ngld": 99}
REASONING_FORMAT = "deepseek"
# The serving block of a verdict row under llamacpp (brief M6), read from the engine record that answered.
SERVING_KEYS_LLAMACPP = ("build", "build_manifest_sha256", "model_sha256", "drafter_sha256", "server_cmdline_sha256",
                         "system_sha256", "provider_sha256")


class ProviderError(Exception):
    """A failure with a name. Under llamacpp always raised to the caller as HTTP 500 {"error": "<cause> <detail>", "cause": cause}."""

    def __init__(self, cause, detail=""):
        super().__init__(f"{cause} {detail}".strip())
        self.cause = cause
        self.detail = detail


class ProviderHTTPError(urllib.error.HTTPError):
    """The HTTP 500 a caller sees. A real urllib.error.HTTPError (callers catch that class); `cause` is also an attribute."""

    cause = None


def http_500(err, url=""):
    """The HTTPError the adapter's HTTP answer would have become: code 500, JSON body {"error", "cause"}."""
    body = json.dumps({"error": f"{err.cause} {err.detail}".strip(), "cause": err.cause}).encode()
    e = ProviderHTTPError(url, 500, "Internal Server Error", email.message.Message(), io.BytesIO(body))
    e.cause = err.cause
    return e


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def provider_sha256():
    """sha256 of this file: what engine.json records as `provider_sha256` and the registration pins."""
    return sha256_file(Path(__file__))


def read_system(path):
    """The pinned SYSTEM exactly as stored: bytes, UTF-8, no newline translation. Returns (text, sha256)."""
    raw = open(path, "rb").read()
    return raw.decode("utf-8"), sha256_bytes(raw)


# ---------------------------------------------------------------- request: Ollama -> OpenAI

def to_openai(body, system=None):
    """(OpenAI request dict, info dict). Raises ProviderError('bad_request') on a malformed body."""
    if not isinstance(body, dict):
        raise ProviderError("bad_request", "body is not a JSON object")
    if body.get("stream") is True:
        raise ProviderError("bad_request", "stream=true is not supported; the harness sends stream=false")
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise ProviderError("bad_request", "messages is not a list")
    msgs, pending = [], []
    info = {"system_injected": False, "orphan_tool_results": 0}
    if system is not None and not any(isinstance(m, dict) and m.get("role") == "system" for m in messages):
        msgs.append({"role": "system", "content": system})
        info["system_injected"] = True
    for m in messages:
        if not isinstance(m, dict):
            raise ProviderError("bad_request", "a message is not a JSON object")
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
    """Translate llama-server's reply. Raises ProviderError for a reply that cannot be mapped faithfully."""
    if not isinstance(resp, dict) or not isinstance(resp.get("choices"), list) or not resp["choices"]:
        raise ProviderError("upstream_bad_response", "reply has no choices: " + json.dumps(resp)[:300])
    ch = resp["choices"][0]
    m = ch.get("message") if isinstance(ch, dict) else None
    if not isinstance(m, dict):
        raise ProviderError("upstream_bad_response", "choice has no message: " + json.dumps(ch)[:300])
    fin = ch.get("finish_reason")
    if fin not in FINISH_TO_DONE:
        raise ProviderError("unmapped_finish_reason", f"finish_reason={fin!r}")
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
            return ProviderError("context_overflow", f"{message} {json.dumps(extra) if extra else ''}".strip())
    elif isinstance(j, dict) and isinstance(j.get("error"), str):
        message = j["error"]
    if code == 400 and "exceeds the available context size" in message:
        return ProviderError("context_overflow", message)
    if 400 <= code < 500:
        return ProviderError("upstream_4xx", f"HTTP {code}: {message[:500]}")
    if code >= 500:
        return ProviderError("upstream_5xx", f"HTTP {code}: {message[:500]}")
    return ProviderError("upstream_http_unexpected", f"HTTP {code}: {message[:500]}")


def call_upstream(url, payload, timeout):
    """(parsed JSON, seconds). Every failure is a ProviderError with a name."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise classify_http_error(e.code, e.read()) from e
    except TimeoutError as e:
        raise ProviderError("upstream_timeout", f"after {timeout}s waiting for llama-server") from e
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise ProviderError("upstream_timeout", f"after {timeout}s connecting to llama-server") from e
        if isinstance(reason, ConnectionRefusedError):
            raise ProviderError("connection_refused", f"{url}: {reason}") from e
        if isinstance(reason, ConnectionError):
            raise ProviderError("connection_reset", f"{url}: {reason}") from e
        raise ProviderError("upstream_connection_error", f"{url}: {reason!r}") from e
    except ConnectionRefusedError as e:
        raise ProviderError("connection_refused", f"{url}: {e}") from e
    except (ConnectionError, http.client.HTTPException) as e:
        raise ProviderError("connection_reset", f"{url}: {type(e).__name__}: {e}") from e
    secs = time.time() - t0
    try:
        return json.loads(raw.decode("utf-8")), secs
    except ValueError as e:
        raise ProviderError("upstream_bad_json", f"{e}; first bytes: {raw[:200]!r}") from e


# ---------------------------------------------------------------- configuration and the server's identity

def _config():
    return rs2_data.CONFIG


def provider_name():
    """The configured provider; an unknown value is a configuration error, never a silent fallback."""
    p = _config().get("depth_provider", "ollama")
    if p not in PROVIDERS:
        raise ValueError(f"depth_provider must be one of {PROVIDERS}, got {p!r}")
    return p


def llamacpp_settings():
    cfg = _config().get("llamacpp")
    if not isinstance(cfg, dict):
        raise ProviderError("engine_not_ready", "config.json has no llamacpp block")
    return cfg


def endpoint(cfg):
    return f"http://{cfg['host']}:{cfg['port']}"


def engine_path():
    return Path(ENGINE_DIR) / ENGINE_FILE


def pid_alive(pid):
    """True when a process with this PID is running. NOT os.kill(pid, 0): on Windows os.kill terminates the process."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code)):
                return False
            return code.value == 259                     # STILL_ACTIVE
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def health_ok(cfg, timeout=None):
    """True when GET /health answers 200 within `timeout` seconds (default HEALTH_TIMEOUT_S)."""
    timeout = HEALTH_TIMEOUT_S if timeout is None else timeout
    try:
        with urllib.request.urlopen(endpoint(cfg) + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def read_engine():
    """engine.json as a dict, or ProviderError('engine_not_ready') when it is missing or unreadable."""
    p = engine_path()
    try:
        eng = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProviderError("engine_not_ready", f"{p} does not exist: llamacpp_server.start() has not run") from None
    except (OSError, ValueError) as e:
        raise ProviderError("engine_not_ready", f"{p} is unreadable: {type(e).__name__}: {e}") from e
    if not isinstance(eng, dict):
        raise ProviderError("engine_not_ready", f"{p} is not a JSON object")
    return eng


def engine_pin_problems(engine, cfg):
    """What differs between engine.json and the config's pins, as a list of readable lines (empty: they agree)."""
    bad = []
    want = {"build": cfg.get("build"), "build_manifest_sha256": cfg.get("build_manifest_sha256"),
            "model_sha256": cfg.get("model_sha256"), "drafter_sha256": cfg.get("drafter_sha256"),
            "server_cmdline_sha256": cfg.get("server_cmdline_sha256"), "system_sha256": cfg.get("system_sha256"),
            "provider_sha256": provider_sha256(), "spec": SPEC, "reasoning_format": REASONING_FORMAT,
            "endpoint": endpoint(cfg)}
    for k, v in want.items():
        if engine.get(k) != v:
            bad.append(f"{k}: engine.json has {engine.get(k)!r}, expected {v!r}")
    return bad


_SYSTEM_CACHE = {}


def system_text(cfg):
    """(SYSTEM text, sha256) of the configured system_file, which must hash to the pinned `system_sha256`."""
    path = HERE / cfg["system_file"]
    try:
        st = path.stat()
    except OSError as e:
        raise ProviderError("engine_not_ready", f"system_file {path}: {type(e).__name__}: {e}") from e
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _SYSTEM_CACHE:
        _SYSTEM_CACHE.clear()
        _SYSTEM_CACHE[key] = read_system(path)
    text, sha = _SYSTEM_CACHE[key]
    if sha != cfg.get("system_sha256"):
        raise ProviderError("engine_not_ready", f"system_file {path} hashes to {sha}, pinned {cfg.get('system_sha256')}")
    return text, sha


def check_engine_ready(cfg):
    """The engine record of a live, pinned, healthy server, else ProviderError('engine_not_ready').
    Checked before every request: the file exists, its PID is alive, its pins equal the config's, /health answers 200
    within 5 s, and the config's depth_model is the llamacpp model_tag."""
    depth_model = _config().get("depth_model")
    if depth_model != cfg.get("model_tag"):
        raise ProviderError("engine_not_ready", f"depth_model {depth_model!r} is not llamacpp.model_tag {cfg.get('model_tag')!r}")
    engine = read_engine()
    if not pid_alive(engine.get("pid")):
        raise ProviderError("engine_not_ready", f"llama-server PID {engine.get('pid')!r} from engine.json is not alive")
    bad = engine_pin_problems(engine, cfg)
    if bad:
        raise ProviderError("engine_not_ready", "engine.json differs from config: " + "; ".join(bad))
    if not health_ok(cfg):
        raise ProviderError("engine_not_ready", f"GET {endpoint(cfg)}/health did not answer 200 within {HEALTH_TIMEOUT_S}s")
    return engine


# ---------------------------------------------------------------- the two providers

def _ollama_chat(body, timeout):
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _llamacpp_chat(body, timeout):
    url = None
    try:
        cfg = llamacpp_settings()
        url = endpoint(cfg) + "/v1/chat/completions"
        engine = check_engine_ready(cfg)
        system, _sha = system_text(cfg)
        req, info = to_openai(body, system)
        if body.get("model") != cfg.get("model_tag"):                       # C4: each request names the pinned model
            raise ProviderError("engine_not_ready", f"request model {body.get('model')!r} is not llamacpp.model_tag "
                                f"{cfg.get('model_tag')!r}")
        up_timeout = min(timeout, cfg["upstream_timeout_s"])
        try:
            resp, secs = call_upstream(url, req, up_timeout)
        except ProviderError as e:
            if e.cause == "upstream_timeout" and timeout < cfg["upstream_timeout_s"]:
                # the caller's own timeout was the smaller: the TimeoutError urllib raises at the caller
                raise TimeoutError("timed out") from e
            raise
        out = to_ollama(resp, body.get("model"), secs, engine, info)
        out["ignored_options"] = info["ignored_options"]
        out["system_injected"] = info["system_injected"]
        return out
    except ProviderError as e:
        raise http_500(e, url or "") from e
    except TimeoutError:
        raise
    except urllib.error.HTTPError:
        raise
    except Exception as e:  # a named 500 instead of an unnamed failure, as the adapter did
        raise http_500(ProviderError("adapter_exception", f"{type(e).__name__}: {e}"), url or "") from e


def chat(body, timeout):
    """The analyst-model call: an Ollama /api/chat body in, an Ollama-shaped response out."""
    provider = provider_name()
    if provider == "ollama":
        return _ollama_chat(body, timeout)
    return _llamacpp_chat(body, timeout)


# ---------------------------------------------------------------- provenance

def ollama_manifest_path(model):
    base = os.environ.get("OLLAMA_MODELS") or str(Path.home() / ".ollama" / "models")
    name, _, tag = (model or "").partition(":")
    return Path(base) / "manifests" / "registry.ollama.ai" / "library" / name / (tag or "latest")


def ollama_serving(model):
    """{provider, model, manifest_sha256, system_layer_digest}, read from the Ollama manifest file as AT10's run script
    did (a file read; no model is loaded). A manifest that cannot be read gives None for the two digests."""
    out = {"provider": "ollama", "model": model, "manifest_sha256": None, "system_layer_digest": None}
    p = ollama_manifest_path(model)
    try:
        raw = p.read_bytes()
        out["manifest_sha256"] = sha256_bytes(raw)
        layers = json.loads(raw.decode("utf-8")).get("layers") or []
        out["system_layer_digest"] = next((l.get("digest") for l in layers
                                           if str(l.get("mediaType", "")).endswith(".system")), None)
    except (OSError, ValueError, AttributeError):
        pass
    return out


def turns_provenance(turns):
    """Per-sample provenance from the per-turn records of a tools session: the engine of the first turn that has one, whether
    every turn's engine equals it, and the draft counters summed. {} when no turn carries an engine record, so an Ollama
    sample's record is unchanged."""
    engines = [t["engine"] for t in turns if t.get("engine") is not None]
    if not engines:
        return {}
    drafted = [t["draft_n"] for t in turns if t.get("draft_n") is not None]
    accepted = [t["draft_n_accepted"] for t in turns if t.get("draft_n_accepted") is not None]
    return {"engine": engines[0], "engine_consistent": all(e == engines[0] for e in engines),
            "draft_n": sum(drafted) if drafted else None, "draft_n_accepted": sum(accepted) if accepted else None}


def run_row_provenance(meta, resp=None):
    """The same four fields for a `runs` row of consensus.json: from the tools session's meta, or (no-tools path) from the
    provider's own response. {} when the serving path reported no engine."""
    meta = meta or {}
    if meta.get("engine") is not None:
        return {k: meta.get(k) for k in ("engine", "engine_consistent", "draft_n", "draft_n_accepted")}
    if isinstance(resp, dict) and resp.get("engine") is not None:
        return {"engine": resp["engine"], "engine_consistent": True, "draft_n": resp.get("draft_n"),
                "draft_n_accepted": resp.get("draft_n_accepted")}
    return {}


def doc_provenance(runs):
    """The run-level fields of consensus.json: `provider` always, `engine` (of the first sample that has one) when the serving
    path reported one."""
    out = {"provider": provider_name()}
    engine = next((r["engine"] for r in runs if r.get("engine") is not None), None)
    if engine is not None:
        out["engine"] = engine
    return out


def serving_block(provider, model, engine=None):
    """The `serving` object of a verdict row. Under llamacpp it is read from the engine record that answered (None for a
    field the record lacks: a gap stays visible); under ollama from the Ollama manifest."""
    if provider == "llamacpp":
        eng = engine if isinstance(engine, dict) else {}
        return {"provider": "llamacpp", **{k: eng.get(k) for k in SERVING_KEYS_LLAMACPP}}
    return ollama_serving(model)
