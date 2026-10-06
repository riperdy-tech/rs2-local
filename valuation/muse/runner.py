"""runner.py - one chat call per prompt to an OpenAI-compatible llama.cpp server (Muse), the retry rule, and the record of every request and response.

SYSTEM MESSAGE = "Reasoning strength: xhigh\\n" + prompts/system.txt (the short text written for this layer). The prefix is Muse's reasoning-strength
switch, as in AT10b and charters/SYSTEM_muse_v33.txt; it is recorded per run. Lower settings are a later, measured experiment.

ONE CALL PER PROMPT, JSON ONLY. The request is {model, messages: [system, user], stream: false, max_tokens, seed?}. No sampling field is sent: as in
tools/audit_202608/llm_provider.py the pinned server decides sampling. The server's reasoning (`reasoning_content`) is kept in the saved response and
never parsed as the answer.

THE RETRY RULE (SPEC_muse_passes section 2). The answer is parsed (one JSON object) and handed to the caller's `validate(obj) -> [Issue]`. When it fails
(not JSON, cut off at max_tokens, or any Issue) ONE retry is made: the same request plus the assistant's answer plus a user message that lists the
checker's messages. If the retried answer still fails, the CallResult says so with the final issues; what to do next (the fallback: unanchored, the prior's
P50, width wide) is the caller's rule, applied per input in pipeline.py. A transport failure (no server, timeout, HTTP error, a response without
a message) is NOT a check failure: it raises MuseTransportError and the run stops; it is never turned into a fallback value.

EVERY REQUEST AND RESPONSE IS SAVED under the run directory: NN_<call>_a<attempt>_request.json and _response.json (the raw server JSON), calls.jsonl
(one summary line per attempt with the rendered prompt's sha256) and run_manifest.json (system text, prefix, template hashes, model, URL, limits).

The client is a tiny interface (`chat(request: dict) -> dict`); `OpenAICompatClient` is the real one and takes an injectable `urlopen`, so the tests use a
mock and no server is ever started by this module.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from .checkers import Issue, issues_message, parse_json
from .prompting import prompt_hashes, system_text

DEFAULT_URL = "http://127.0.0.1:8080"
REASONING_PREFIX = "Reasoning strength: xhigh\n"
DEFAULT_MAX_TOKENS = 32768
RUNNER_VERSION = "1"


class MuseTransportError(RuntimeError):
    """The server could not be reached or answered with something that is not a chat completion. Never a check failure, never a fallback."""


class OpenAICompatClient:
    """POST {base_url}/v1/chat/completions. `urlopen` is injectable (the tests pass a fake)."""

    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 3600.0, urlopen: Callable = urllib.request.urlopen):
        self.base_url, self.timeout, self._urlopen = base_url.rstrip("/"), timeout, urlopen

    def chat(self, request: dict) -> dict:
        data = json.dumps(request).encode("utf-8")
        req = urllib.request.Request(self.base_url + "/v1/chat/completions", data=data, headers={"Content-Type": "application/json"})
        try:
            with self._urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise MuseTransportError(f"HTTP {e.code} from {self.base_url}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, OSError) as e:
            raise MuseTransportError(f"cannot reach {self.base_url}: {e!r}") from e
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as e:
            raise MuseTransportError(f"the server's answer is not JSON: {raw[:200]!r}") from e


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass
class Attempt:
    n: int
    request_sha256: str
    content: str
    reasoning: Optional[str]
    finish_reason: Optional[str]
    usage: Optional[dict]
    seconds: float
    issues: List[Issue]


@dataclass
class CallResult:
    call_id: str
    obj: Optional[dict]                  # the final parsed object (None when it never parsed)
    issues: List[Issue]                  # the final issues ([] = the answer passed every check)
    attempts: List[Attempt] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.obj is not None and not self.issues

    @property
    def retried(self) -> bool:
        return len(self.attempts) > 1


class MuseRunner:
    def __init__(self, client, run_dir, *, model: str = "muse", max_tokens: int = DEFAULT_MAX_TOKENS, seed: Optional[int] = None,
                 base_url: str = DEFAULT_URL, system: Optional[str] = None):
        self.client, self.run_dir = client, Path(run_dir)
        self.model, self.max_tokens, self.seed, self.base_url = model, max_tokens, seed, base_url
        self.system_message = REASONING_PREFIX + (system if system is not None else system_text())
        self.seq = 0
        self.run_dir.mkdir(parents=True, exist_ok=True)

    # -- the record --
    def write_manifest(self, extra: Optional[dict] = None) -> dict:
        m = {"runner_version": RUNNER_VERSION, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": self.model,
             "base_url": self.base_url, "reasoning_prefix": REASONING_PREFIX, "system_message_sha256": sha256_text(self.system_message),
             "system_message": self.system_message, "max_tokens": self.max_tokens, "seed": self.seed, "prompt_hashes": prompt_hashes(),
             "sampling": "not sent: the pinned server decides sampling"}
        m.update(extra or {})
        (self.run_dir / "run_manifest.json").write_text(json.dumps(m, indent=1, default=str), encoding="utf-8")
        return m

    def _save(self, name: str, obj) -> None:
        (self.run_dir / name).write_text(json.dumps(obj, indent=1, default=str, ensure_ascii=False), encoding="utf-8")

    def _request(self, messages: Sequence[dict]) -> dict:
        req = {"model": self.model, "messages": list(messages), "stream": False, "max_tokens": self.max_tokens}
        if self.seed is not None:
            req["seed"] = self.seed
        return req

    def _ask(self, call_id: str, attempt_no: int, messages, rendered_sha: str):
        req = self._request(messages)
        self.seq += 1
        stem = f"{self.seq:02d}_{call_id}_a{attempt_no}"
        self._save(stem + "_request.json", req)
        t0 = time.time()
        resp = self.client.chat(req)
        secs = time.time() - t0
        self._save(stem + "_response.json", resp)
        try:
            ch = resp["choices"][0]
            msg = ch["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise MuseTransportError(f"the answer to {call_id} has no choices[0].message: {str(resp)[:200]}") from e
        content = msg.get("content")
        content = "" if content is None else str(content)
        with open(self.run_dir / "calls.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"call": call_id, "attempt": attempt_no, "file_stem": stem, "request_sha256": sha256_text(json.dumps(req, sort_keys=True)),
                                 "rendered_prompt_sha256": rendered_sha, "seconds": round(secs, 2), "finish_reason": ch.get("finish_reason"),
                                 "usage": resp.get("usage")}) + "\n")
        return content, msg.get("reasoning_content"), ch.get("finish_reason"), resp.get("usage"), secs

    def call(self, call_id: str, user_text: str, validate: Callable[[dict], List[Issue]]) -> CallResult:
        """One prompt: the answer, validated; one retry with the checker's message when it fails."""
        rendered_sha = sha256_text(user_text)
        messages = [{"role": "system", "content": self.system_message}, {"role": "user", "content": user_text}]
        result = CallResult(call_id, None, [])
        for n in (1, 2):
            content, reasoning, finish, usage, secs = self._ask(call_id, n, messages, rendered_sha)
            obj, err = parse_json(content)
            if err is None and finish == "length":
                obj, err = None, "the answer was cut off at the length limit; answer more briefly (fewer, shorter reasons) and finish the JSON"
            if err is not None:
                issues = [Issue("not_json", err)]
            else:
                issues = list(validate(obj))
            result.attempts.append(Attempt(n, sha256_text(json.dumps(self._request(messages), sort_keys=True)), content, reasoning, finish, usage, secs, issues))
            result.obj, result.issues = obj, issues
            if not issues:
                return result
            if n == 1:
                messages = messages + [{"role": "assistant", "content": content},
                                       {"role": "user", "content": "Your answer did not pass the code checks:\n" + issues_message(issues) +
                                        "\nReturn the complete corrected answer as one JSON object and nothing else."}]
        return result
