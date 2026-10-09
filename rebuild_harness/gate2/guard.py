"""guard.py - the client wrappers around the Muse runner's `chat(request)` interface: the context guard and the timer.

CONTEXT GUARD.  The server runs with the registered 32768-token window, shared by the prompt and the answer (`-np 1`: one slot, the whole window).  The pipeline asks for
`max_tokens` per request; a request whose prompt plus that cap does not fit would be cut at the window's end ("length") or, on the retry (which repeats the prompt and the
answer), rejected by the server with HTTP 400.  The guard sends `min(max_tokens, window - estimated prompt tokens - margin)` instead, and refuses a request whose room
would be below a floor (an answer of fewer than FLOOR tokens cannot hold the JSON): that is a `ContextOverflow`, a terminal, recorded outcome of the company-date, not a
transport failure (retrying the same prompt cannot help).  The estimate is characters / 3.0 (conservative); the real prompt-token count of every response is saved by the
runner (`usage`), so the estimate can be calibrated.  The request file the runner saves holds the REQUESTED cap; what was SENT is in `guard.jsonl`.

TIMER.  Wall seconds spent in `chat` and the token usage, per company-date, for the time-per-company report.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from valuation.muse.runner import MuseTransportError

from . import config


OVERFLOW_PREFIX = "context_overflow:"


class ContextOverflow(MuseTransportError):
    """The prompt leaves no room for an answer in the window.  Subclass of the transport error so the pipeline stops the run cleanly; the replay runner tells it from an
    outage by its type and records it as the company-date's final status (`context_overflow`), never retrying it."""


def estimate_prompt_tokens(request: dict, chars_per_token: float = config.CHARS_PER_TOKEN) -> int:
    chars = sum(len(str(m.get("content") or "")) for m in request.get("messages", []))
    return int(chars / chars_per_token) + 1


class ContextGuardClient:
    def __init__(self, inner, *, window: int = config.CONTEXT, margin: int = config.CTX_MARGIN_TOKENS, floor: int = config.CTX_FLOOR_TOKENS,
                 chars_per_token: float = config.CHARS_PER_TOKEN, log_path: Optional[Path] = None):
        self.inner, self.window, self.margin, self.floor, self.cpt = inner, window, margin, floor, chars_per_token
        self.log_path = Path(log_path) if log_path is not None else None

    def _log(self, rec: dict) -> None:
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")

    def chat(self, request: dict) -> dict:
        est = estimate_prompt_tokens(request, self.cpt)
        room = self.window - est - self.margin
        asked = room if request.get("max_tokens") is None else int(request["max_tokens"])     # is None, never `or` (non-negotiable 4)
        if room < self.floor:
            self._log({"prompt_tokens_estimated": est, "window": self.window, "requested_max_tokens": asked, "sent": None, "refused": "context_overflow"})
            raise ContextOverflow(f"{OVERFLOW_PREFIX} the prompt is about {est} tokens of the {self.window}-token window: no room for an answer ({room} < {self.floor})")
        sent = min(asked, room)
        self._log({"prompt_tokens_estimated": est, "window": self.window, "requested_max_tokens": asked, "sent_max_tokens": sent, "lowered": sent < asked})
        return self.inner.chat(dict(request, max_tokens=sent))


class TimedClient:
    """Adds up the seconds and tokens of every `chat` call through it."""

    def __init__(self, inner, clock: Callable[[], float] = time.time):
        self.inner, self.clock = inner, clock
        self.seconds = 0.0
        self.n_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.n_length_cut = 0
        self.max_prompt_tokens = 0

    def chat(self, request: dict) -> dict:
        t0 = self.clock()
        try:
            resp = self.inner.chat(request)
        finally:
            self.seconds += self.clock() - t0
            self.n_calls += 1
        u = resp.get("usage") or {}
        self.prompt_tokens += int(u.get("prompt_tokens") or 0)
        self.completion_tokens += int(u.get("completion_tokens") or 0)
        self.max_prompt_tokens = max(self.max_prompt_tokens, int(u.get("prompt_tokens") or 0))
        try:
            if resp["choices"][0].get("finish_reason") == "length":
                self.n_length_cut += 1
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
        return resp

    def summary(self) -> dict:
        return {"model_seconds": round(self.seconds, 2), "n_calls": self.n_calls, "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "max_prompt_tokens": self.max_prompt_tokens, "n_length_cut": self.n_length_cut}
