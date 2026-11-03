"""llm_provider.py — the one door every analyst-model call of the depth path goes through.

`chat(body, timeout)` takes the Ollama /api/chat body the harness builds and returns an Ollama-shaped response.

  depth_provider "ollama"    today's request, byte for byte: POST of json.dumps(body) to the local Ollama.
  depth_provider "ollama_raw" /api/generate raw: the chat template and the tool-call reader are ours (ollama_raw.py); see there.

2026-11-03: the "llamacpp" provider (the Muse / llama-server adapter) and its server lifecycle are archived under
_archive/retired_20261103/ (README_muse.md there). A config that still names it is refused, never served by another provider.
"""
import email.message
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

import rs2_data  # noqa: E402

# The address every call site hard-coded before this module existed (analyst_tools.OLLAMA and the literals in
# consensus_valuation.py). Kept as the one literal; analyst_tools.OLLAMA stays defined for the tests and tools that import it.
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
PROVIDERS = ("ollama", "ollama_raw")
ARCHIVED_PROVIDERS = ("llamacpp",)     # 2026-11-03: refused by name, see the module docstring


class ProviderError(Exception):
    """A failure with a name. Raised to the caller as HTTP 500 {"error": "<cause> <detail>", "cause": cause}."""

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


# ---------------------------------------------------------------- configuration

def _config():
    return rs2_data.CONFIG


def provider_name():
    """The configured provider; an unknown value is a configuration error, never a silent fallback."""
    p = _config().get("depth_provider", "ollama")
    if p in ARCHIVED_PROVIDERS:
        raise ValueError(f"depth_provider {p!r} is archived (2026-11-03, _archive/retired_20261103/); "
                         f"depth_provider must be one of {PROVIDERS}")
    if p not in PROVIDERS:
        raise ValueError(f"depth_provider must be one of {PROVIDERS}, got {p!r}")
    return p


# ---------------------------------------------------------------- the providers

def _ollama_chat(body, timeout):
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _ollama_raw_chat(body, timeout):
    """depth_provider "ollama_raw" (brief H): /api/generate raw, our template and our tool-call reader (ollama_raw.py). A refusal
    (template drift, no SYSTEM, a template error) is a named HTTP 500 (ProviderError via http_500)."""
    import ollama_raw
    try:
        return ollama_raw.chat(body, timeout, OLLAMA_URL)
    except ollama_raw.RawProviderError as e:
        raise http_500(ProviderError(e.cause, e.detail), OLLAMA_URL) from e


def chat(body, timeout):
    """The analyst-model call: an Ollama /api/chat body in, an Ollama-shaped response out."""
    provider = provider_name()
    if provider == "ollama":
        return _ollama_chat(body, timeout)
    return _ollama_raw_chat(body, timeout)


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
    """The `serving` object of a verdict row, read from the Ollama manifest (ollama_raw adds its template's sha256). An archived
    provider is refused, not labelled as Ollama."""
    if provider in ARCHIVED_PROVIDERS:
        raise ValueError(f"provider {provider!r} is archived (2026-11-03, _archive/retired_20261103/)")
    if provider == "ollama_raw":
        import ollama_raw
        return {**ollama_serving(model), "provider": "ollama_raw", "template_sha256": ollama_raw.TEMPLATE_SHA256}
    return ollama_serving(model)
