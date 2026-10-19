"""Brief R26-A1, SPEC revision 26 section 0: the per-turn log of the ollama_raw provider. No GPU, no Ollama: urlopen is a fake."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
for p in (str(AUDIT_DIR), str(AUDIT_DIR.parents[1]), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ollama_raw as raw  # noqa: E402
import turn_log  # noqa: E402
import r26_request_capture as cap  # noqa: E402
import rs2_data  # noqa: E402

FIXTURE = TESTS_DIR / "fixture_data" / "r26_request_bytes_6bc2ad0.json"
URL = "http://127.0.0.1:1/api/chat"


def _fake(monkeypatch, reply, seen):
    import urllib.request

    def fake_urlopen(req, timeout=None):
        if req.full_url.endswith("/api/version"):
            return cap._Resp({"version": "0.40.3"})
        seen.append(req.data)
        return cap._Resp(reply)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(raw, "_VERSIONS", {})


REPLY = {"response": "thinking text\n</think>\n\nanswer", "done": True, "done_reason": "stop", "prompt_eval_count": 1234, "eval_count": 56}
BODY = {"model": "m", "stream": False, "think": "high", "options": {"num_ctx": 98304, "num_predict": 4096, "seed": 11, "temperature": 0.6},
        "messages": [{"role": "user", "content": "U"}]}


def test_each_turn_is_logged_with_the_prompt_hash_the_raw_completion_and_the_counters(monkeypatch, tmp_path):
    seen = []
    _fake(monkeypatch, REPLY, seen)
    monkeypatch.setattr(raw, "ollama_system_text", lambda model: "MODEL SYSTEM TEXT")
    with turn_log.logging_to(tmp_path / "turns", "stage1"):
        raw.chat(json.loads(json.dumps(BODY)), 30, URL)
        raw.chat(json.loads(json.dumps(BODY)), 30, URL)
    with turn_log.logging_to(tmp_path / "turns", "stage2"):
        raw.chat(json.loads(json.dumps(BODY)), 30, URL)
    names = sorted(p.name for p in (tmp_path / "turns").iterdir())
    assert names == ["run_hashes.json", "stage1_1.json", "stage1_2.json", "stage2_1.json"]
    rec = json.loads((tmp_path / "turns" / "stage1_2.json").read_text("utf-8"))
    sent = json.loads(seen[1])
    assert rec["stage"] == "stage1" and rec["n"] == 2 and rec["model"] == "m"
    assert rec["prompt_sha256"] == hashlib.sha256(sent["prompt"].encode("utf-8")).hexdigest()
    assert rec["system_sha256"] == hashlib.sha256(b"MODEL SYSTEM TEXT").hexdigest()
    assert rec["template_sha256"] == raw.TEMPLATE_SHA256
    assert rec["completion"] == {"response": REPLY["response"]}
    assert (rec["prompt_eval_count"], rec["eval_count"], rec["done_reason"], rec["seed"]) == (1234, 56, "stop", 11)
    assert rec["options"] == BODY["options"]
    hashes = json.loads((tmp_path / "turns" / "run_hashes.json").read_text("utf-8"))
    assert hashes == {"system_sha256": rec["system_sha256"], "template_sha256": raw.TEMPLATE_SHA256, "model": "m"}


def test_a_system_message_of_the_body_is_the_system_hashed_and_a_thinking_field_is_kept(monkeypatch, tmp_path):
    seen = []
    _fake(monkeypatch, dict(REPLY, thinking="side channel"), seen)
    body = dict(BODY, messages=[{"role": "system", "content": "S1"}, {"role": "user", "content": "U"}])
    with turn_log.logging_to(tmp_path, "main"):
        raw.chat(body, 30, URL)
    rec = json.loads((tmp_path / "main_1.json").read_text("utf-8"))
    assert rec["system_sha256"] == hashlib.sha256(b"S1").hexdigest()
    assert rec["completion"] == {"response": REPLY["response"], "thinking": "side channel"}


def test_a_changed_system_is_visible_in_the_run_hashes(monkeypatch, tmp_path):
    seen = []
    _fake(monkeypatch, REPLY, seen)
    with turn_log.logging_to(tmp_path, "main"):
        raw.chat(dict(BODY, messages=[{"role": "system", "content": "A"}, {"role": "user", "content": "U"}]), 30, URL)
        raw.chat(dict(BODY, messages=[{"role": "system", "content": "B"}, {"role": "user", "content": "U"}]), 30, URL)
    h = json.loads((tmp_path / "run_hashes.json").read_text("utf-8"))
    assert h["system_sha256"] == hashlib.sha256(b"A").hexdigest() and h["changes"][0]["system_sha256"] == hashlib.sha256(b"B").hexdigest()


def test_nothing_is_written_outside_a_logging_block(monkeypatch, tmp_path):
    seen = []
    _fake(monkeypatch, REPLY, seen)
    monkeypatch.setattr(raw, "ollama_system_text", lambda model: "S")
    raw.chat(json.loads(json.dumps(BODY)), 30, URL)
    assert turn_log.active() is None and list(tmp_path.iterdir()) == []


def test_a_failed_log_write_never_fails_the_turn(monkeypatch, tmp_path, capsys):
    seen = []
    _fake(monkeypatch, REPLY, seen)
    monkeypatch.setattr(raw, "ollama_system_text", lambda model: "S")
    blocker = tmp_path / "turns"
    blocker.write_text("a file where the folder should be")
    with turn_log.logging_to(blocker, "main"):
        out = raw.chat(json.loads(json.dumps(BODY)), 30, URL)
    assert out["message"]["content"] == "answer" and "could not write the turn log" in capsys.readouterr().err


def test_the_completion_that_trips_the_overflow_guard_is_still_logged(monkeypatch, tmp_path):
    seen = []
    _fake(monkeypatch, dict(REPLY, prompt_eval_count=98304, eval_count=10), seen)
    monkeypatch.setattr(raw, "ollama_system_text", lambda model: "S")
    with turn_log.logging_to(tmp_path, "main"), pytest.raises(raw.RawProviderError):
        raw.chat(json.loads(json.dumps(BODY)), 30, URL)
    assert (tmp_path / "main_1.json").exists()


def test_logging_does_not_change_a_single_request_byte(monkeypatch, tmp_path):
    """The bytes POSTed for three fixed bodies equal the capture of the code before the log existed (commit 6bc2ad0), with the log off and on."""
    want = json.loads(FIXTURE.read_text("utf-8"))
    assert cap.capture(monkeypatch) == want
    with turn_log.logging_to(tmp_path / "turns", "stage1"):
        assert cap.capture(monkeypatch) == want
    assert len(list((tmp_path / "turns").glob("stage1_*.json"))) == len(want)


def test_chat_with_tools_logs_its_turns_under_the_ollama_raw_provider_and_only_then(monkeypatch, tmp_path):
    import analyst_tools as at
    import llm_provider as prov
    seen = []
    report = "findings\n```json:catalysts\n[]\n```"
    _fake(monkeypatch, {"response": "think\n</think>\n\n" + report, "done": True, "done_reason": "stop", "prompt_eval_count": 50, "eval_count": 9}, seen)
    monkeypatch.setattr(raw, "ollama_system_text", lambda model: "S")
    monkeypatch.setattr(prov, "OLLAMA_URL", URL)
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "ollama_raw")
    rep, _think, _meta = at.chat_with_tools("m", "the pack", tmp_path / "s1", think="high", ctx=8192, num_predict=2048, seed=3, max_model_calls=0, verbose=False)
    assert "json:catalysts" in rep
    rec = json.loads((tmp_path / "s1" / "turns" / "main_1.json").read_text("utf-8"))
    assert rec["seed"] == 3 and rec["completion"]["response"].endswith(report)
    assert (tmp_path / "s1" / "turns" / "run_hashes.json").exists()
