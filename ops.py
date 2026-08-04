#!/usr/bin/env python3
"""
ops.py — shared ops primitives: Telegram alerts + a VERIFIED VRAM unload barrier.

STDLIB ONLY, on purpose: this is imported both by the main interpreter (run_rs2,
orchestrate) and by the research-venv interpreter (deep_research), which do not
share site-packages. Adding a third-party import here breaks deep_research.

Why the unload barrier exists (2026-08-04):
  rs2-analyst and rs2-research are BOTH ~23GB on a 24GB card, so they cannot
  co-reside. The old unload was POST keep_alive:0 followed by a blind
  time.sleep(2). Ollama's 200 means "your request finished", NOT "the VRAM is
  free" — it tears the llama-server subprocess down asynchronously, and
  destroying a 23GB CUDA context takes longer than 2s under load. The next
  load then raced the teardown and OOM'd:
      cudaMalloc failed: out of memory
      alloc_tensor_range: failed to allocate CUDA0 buffer of size 1043725952
  LDR swallowed that 500 and wrote it into research/{T}.md as if it were
  research (whole days of ~1.8KB briefs on 7/28, 7/29, 8/3, 8/4).
  wait_unloaded() replaces the guess with an observed fact: the model is gone
  from /api/ps AND the driver reports enough free VRAM.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


# ── Telegram ──────────────────────────────────────────────────────────────
def notify_telegram(text):
    """Best-effort ops alert via the same bot as the KIS trade digests. Reads
    telegram_bot_token / telegram_chat_id from .secrets.json; silent no-op if
    absent or failing — an alert path must never break a run."""
    try:
        sec = json.loads((HERE / ".secrets.json").read_text(encoding="utf-8"))
        tok, chat = sec.get("telegram_bot_token"), sec.get("telegram_chat_id")
        if not (tok and chat):
            return False
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            data=json.dumps({"chat_id": chat, "text": text[:3900]}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception:
        return False


# ── VRAM / Ollama state ───────────────────────────────────────────────────
def gpu_free_mb():
    """Free VRAM in MiB per the driver, or None if nvidia-smi is unavailable.
    None is 'unknown', never 'fine' — callers must not treat it as success."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20)
        if out.returncode != 0:
            return None
        return int(out.stdout.strip().splitlines()[0].strip())
    except Exception:
        return None


def ollama_loaded(endpoint):
    """Model names currently resident per /api/ps, or None if the call failed."""
    try:
        ps = endpoint.replace("/api/chat", "/api/ps").replace("/api/generate", "/api/ps")
        with urllib.request.urlopen(ps, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return [m.get("name") or m.get("model") or "" for m in (data.get("models") or [])]
    except Exception:
        return None


def _base(name):
    """'rs2-research' and 'rs2-research:latest' are the same resident model."""
    return (name or "").split(":")[0]


def wait_unloaded(endpoint, model, need_free_mb=20000, timeout_s=180, poll_s=2.0):
    """Force-unload `model` and BLOCK until the VRAM is provably free.

    Returns (ok, detail). ok=True only when the model is absent from /api/ps and
    (when the driver is readable) free VRAM >= need_free_mb. A timeout returns
    ok=False — the caller must treat that as a hard failure and NOT load the
    other model on top of it, which is the OOM this function exists to prevent.
    """
    if not model:
        return True, "no model"
    gen = endpoint.replace("/api/chat", "/api/generate")
    try:
        req = urllib.request.Request(
            gen, data=json.dumps({"model": model, "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        # Non-fatal on its own: the model may already be down, or ollama may be
        # restarting. The poll below is what actually decides.
        pass

    t0 = time.time()
    last = "no poll completed"
    while time.time() - t0 < timeout_s:
        loaded = ollama_loaded(endpoint)
        free = gpu_free_mb()
        resident = None if loaded is None else any(_base(n) == _base(model) for n in loaded)
        if resident is False and (free is None or free >= need_free_mb):
            return True, f"free in {time.time()-t0:.0f}s (free_vram={free}MB)"
        last = (f"resident={resident} free_vram={free}MB "
                f"need={need_free_mb}MB after {time.time()-t0:.0f}s")
        time.sleep(poll_s)
    return False, f"TIMEOUT after {timeout_s}s — {last}"


# ── error-signature detection ─────────────────────────────────────────────
# Ollama/llama-server failures come back as prose inside an otherwise-normal
# 200 response body from LDR, so they must be matched on content, not status.
_INFRA_SIGNATURES = (
    "status code: 500",
    "llama-server",
    "cudamalloc",
    "out of memory",
    "ggml_assert",
    "alloc_tensor_range",
    "failed to load clip model",
    "an error was encountered while running the model",
    "terminateprocess",
    "connection refused",
    "forcibly closed by the remote host",
    "model requires more system memory",
)


def infra_error(text):
    """Return the matched signature if `text` is an infra failure masquerading as
    content, else None. Deliberately narrow: a genuine 'no results found' summary
    is a legitimate (if thin) result and must NOT trip this."""
    s = (text or "").strip().lower()
    if not s:
        return None
    for sig in _INFRA_SIGNATURES:
        if sig in s:
            return sig
    if s.startswith("error:"):
        return "error-prefixed response"
    return None
