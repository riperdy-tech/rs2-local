"""ollama_raw.py - depth_provider "ollama_raw": our code renders Qwen's prompt and reads Qwen's tool calls (brief H).

Ollama stays the engine (same tag, its MTP speed-up, sampling, num_ctx, seed) but is used as plain text in, text out:
POST /api/generate with raw:true, no `tools` field and no `think` field. The tool block and the thinking switch are in the
model's official Jinja chat template (charters/chat_template_qwen38_v33.jinja, pinned by sha256 below, never edited), rendered
here with jinja2 the way Hugging Face's apply_chat_template does. The completion is read by qwen_tool_reader.

`chat(body, timeout, url)` takes the Ollama /api/chat body the harness builds and returns the "ollama" provider's result shape
(message.content / thinking / tool_calls and the timing counters) plus `provider`, `template_sha256`, `ollama_version`.
"""
import hashlib
import json
import urllib.request
from datetime import datetime
from pathlib import Path

import jinja2
import jinja2.ext
import jinja2.sandbox

import qwen_tool_reader

HERE = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = HERE / "charters" / "chat_template_qwen38_v33.jinja"
TEMPLATE_SHA256 = "12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce"
PROVIDER = "ollama_raw"
EFFORTS = ("high", "medium", "low")      # the harness's string think levels, passed to the template as reasoning_effort


class RawProviderError(Exception):
    """A refusal with a named cause (template drift, no system text). llm_provider raises it as HTTP 500."""

    def __init__(self, cause, detail=""):
        super().__init__(f"{cause} {detail}".strip())
        self.cause, self.detail = cause, detail


def _raise_exception(message):
    raise jinja2.exceptions.TemplateError(message)


def _tojson(x, ensure_ascii=False, indent=None, separators=None, sort_keys=False):
    """Hugging Face's tojson: json.dumps, not Jinja's HTML-escaping default."""
    return json.dumps(x, ensure_ascii=ensure_ascii, indent=indent, separators=separators, sort_keys=sort_keys)


def _strftime_now(fmt):
    return datetime.now().strftime(fmt)


_ENV = None


def template_text():
    """The pinned template; refuses a file that differs."""
    raw = Path(TEMPLATE_PATH).read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != TEMPLATE_SHA256:
        raise RawProviderError("template_changed", f"{TEMPLATE_PATH} sha256 {got} is not the pinned {TEMPLATE_SHA256}")
    return raw.decode("utf-8")


def _template():
    """The compiled template; the file is hashed on every call (a few KB) so an edit is caught, not trusted by name."""
    global _ENV
    src = template_text()
    if _ENV is None:
        _ENV = jinja2.sandbox.ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True,
                                                            extensions=[jinja2.ext.loopcontrols])
        _ENV.filters["tojson"] = _tojson
        _ENV.globals["raise_exception"] = _raise_exception
        _ENV.globals["strftime_now"] = _strftime_now
    return _ENV.from_string(src)


def think_kwargs(think):
    """The template variables for the harness's think setting. "high"/"medium"/"low" -> thinking on with that
    reasoning_effort (the template maps "high" to its xhigh); True -> thinking on, the template's default effort;
    False -> enable_thinking False; None (absent) -> neither variable, the template's own default (thinking on)."""
    if think is False:
        return {"enable_thinking": False}
    if think in EFFORTS:
        return {"enable_thinking": True, "reasoning_effort": think}
    if think is True:
        return {"enable_thinking": True}
    if think is None:
        return {}
    raise RawProviderError("bad_request", f"think must be true, false or one of {EFFORTS}, got {think!r}")


def thinking_open(think):
    """True when the generation prompt ends inside an open <think> block."""
    return think is not False


def template_messages(messages, system=None):
    """The harness's messages as the template reads them: the model's own `thinking` is its reasoning_content; tool-call
    arguments stay dicts; a system message is put first only when the harness sent none (Ollama /api/chat did that from the
    model's SYSTEM; /api/generate raw does not)."""
    out = []
    if system is not None and not any(isinstance(m, dict) and m.get("role") == "system" for m in messages):
        out.append({"role": "system", "content": system})
    for m in messages:
        m = dict(m)
        if m.get("role") == "assistant" and "reasoning_content" not in m and m.get("thinking"):
            m["reasoning_content"] = m["thinking"]
        out.append(m)
    return out


def render_prompt(messages, tools=None, think=None):
    kw = think_kwargs(think)
    try:
        return _template().render(messages=messages, tools=tools or None, add_generation_prompt=True, **kw)
    except jinja2.exceptions.TemplateError as e:
        raise RawProviderError("template_error", f"{type(e).__name__}: {e}") from e


def ollama_system_text(model):
    """The SYSTEM text of the model tag, read from its manifest's system layer blob (a file read; no model is loaded)."""
    import llm_provider as prov
    manifest = prov.ollama_manifest_path(model)
    try:
        layers = json.loads(manifest.read_text("utf-8")).get("layers") or []
        digest = next(l["digest"] for l in layers if str(l.get("mediaType", "")).endswith(".system"))
        blob = manifest.parents[4] / "blobs" / digest.replace(":", "-")
        return blob.read_text("utf-8")
    except (OSError, ValueError, StopIteration, KeyError) as e:
        raise RawProviderError("no_system", f"model {model!r}: system layer unreadable from {manifest}: "
                               f"{type(e).__name__}: {e}") from e


_VERSIONS = {}


def ollama_version(base):
    """GET /api/version, cached per process; None when it cannot be read (a stamp, never a failure)."""
    if base not in _VERSIONS:
        try:
            with urllib.request.urlopen(base + "/api/version", timeout=10) as r:
                _VERSIONS[base] = json.loads(r.read().decode()).get("version")
        except Exception:
            return None
    return _VERSIONS[base]


def build_request(body, system):
    """The /api/generate body: same model, options and keep_alive the "ollama" provider sends, the rendered prompt, raw:true,
    no tools and no think."""
    prompt = render_prompt(template_messages(body["messages"], system), body.get("tools"), body.get("think"))
    req = {"model": body["model"], "prompt": prompt, "raw": True, "stream": False, "options": body.get("options") or {}}
    if "keep_alive" in body:
        req["keep_alive"] = body["keep_alive"]
    return req


def to_chat_shape(resp, body, version=None):
    text = resp.get("response") or ""
    read = qwen_tool_reader.read_completion(text, body.get("tools"), thinking_open(body.get("think")))
    msg = {"role": "assistant", "content": read["content"]}
    if read["thinking"]:
        msg["thinking"] = read["thinking"]
    if read["tool_calls"]:
        msg["tool_calls"] = read["tool_calls"]
    out = {k: v for k, v in resp.items() if k not in ("response", "context", "thinking")}
    out["message"] = msg
    out.update({"provider": PROVIDER, "template_sha256": TEMPLATE_SHA256, "ollama_version": version})
    return out


def chat(body, timeout, url):
    """`url` is the "ollama" provider's /api/chat address; /api/generate and /api/version sit beside it."""
    if body.get("stream") is True:
        raise RawProviderError("bad_request", "stream=true is not supported; the harness sends stream=false")
    system = None if any(m.get("role") == "system" for m in body["messages"]) else ollama_system_text(body["model"])
    req = build_request(body, system)
    base = url.rsplit("/api/", 1)[0]
    http = urllib.request.Request(base + "/api/generate", data=json.dumps(req).encode(),
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(http, timeout=timeout) as r:
        resp = json.loads(r.read().decode())
    return to_chat_shape(resp, body, ollama_version(base))
