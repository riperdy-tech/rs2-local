"""The runner: system prefix, request shape, the one retry with the checker's message, the record on disk, transport failures. Mock client only: no server."""
import io
import json
import urllib.error

import pytest

from valuation.muse import prompting, runner as rn
from valuation.muse.checkers import Issue
from valuation.muse.runner import MuseRunner, MuseTransportError, OpenAICompatClient


class Seq:
    """A client that answers from a list of (content, finish_reason)."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def chat(self, request):
        self.requests.append(json.loads(json.dumps(request)))
        c = self.answers.pop(0)
        content, finish = c if isinstance(c, tuple) else (c, "stop")
        return {"choices": [{"message": {"content": content, "reasoning_content": "thinking"}, "finish_reason": finish}], "usage": {"total_tokens": 3}}


def ok_validator(obj):
    return [] if obj.get("a") == 1 else [Issue("schema", "a must be 1")]


def test_system_message_is_the_xhigh_prefix_plus_the_short_system_text(tmp_path):
    r = MuseRunner(Seq('{"a": 1}'), tmp_path)
    assert r.system_message.startswith("Reasoning strength: xhigh\n")
    assert r.system_message == "Reasoning strength: xhigh\n" + prompting.system_text()
    assert len(prompting.system_text()) < 1500                               # short
    r.call("X", "hello", ok_validator)
    req = r.client.requests[0]
    assert [m["role"] for m in req["messages"]] == ["system", "user"] and req["messages"][1]["content"] == "hello"
    assert req["stream"] is False and req["max_tokens"] == rn.DEFAULT_MAX_TOKENS and req["model"] == "muse"
    assert not {"temperature", "top_p", "top_k", "min_p"} & set(req)         # the pinned server decides sampling
    assert "seed" not in req
    assert MuseRunner(Seq('{"a": 1}'), tmp_path, seed=7)._request([])["seed"] == 7


def test_a_passing_answer_makes_one_call(tmp_path):
    c = Seq('{"a": 1}')
    res = MuseRunner(c, tmp_path).call("P1", "u", ok_validator)
    assert res.ok and not res.retried and len(c.requests) == 1 and res.obj == {"a": 1}


def test_a_failing_answer_is_retried_once_with_the_checkers_message(tmp_path):
    c = Seq('{"a": 2}', '{"a": 1}')
    res = MuseRunner(c, tmp_path).call("P1", "u", ok_validator)
    assert res.ok and res.retried and len(c.requests) == 2
    m = c.requests[1]["messages"]
    assert [x["role"] for x in m] == ["system", "user", "assistant", "user"]
    assert m[2]["content"] == '{"a": 2}' and "a must be 1" in m[3]["content"] and "one JSON object" in m[3]["content"]


def test_two_failures_end_with_the_final_issues_and_no_third_call(tmp_path):
    c = Seq('{"a": 2}', '{"a": 3}', '{"a": 1}')
    res = MuseRunner(c, tmp_path).call("P1", "u", ok_validator)
    assert not res.ok and len(c.requests) == 2 and res.issues[0].message == "a must be 1" and res.obj == {"a": 3}


def test_not_json_and_a_cut_off_answer_are_check_failures(tmp_path):
    res = MuseRunner(Seq("Sure, here you go", "still not json"), tmp_path).call("P1", "u", ok_validator)
    assert res.obj is None and res.issues[0].code == "not_json"
    c = Seq(('{"a": 1}', "length"), '{"a": 1}')
    res = MuseRunner(c, tmp_path).call("P1", "u", ok_validator)
    assert res.ok and "cut off" in c.requests[1]["messages"][3]["content"]


def test_every_request_and_response_is_saved_with_the_prompt_hashes(tmp_path):
    r = MuseRunner(Seq('{"a": 2}', '{"a": 1}', '{"a": 1}'), tmp_path / "run")
    m = r.write_manifest({"ticker": "SYN"})
    r.call("P1", "first prompt", ok_validator)
    r.call("P2", "second prompt", ok_validator)
    names = sorted(p.name for p in (tmp_path / "run").iterdir())
    assert names == ["01_P1_a1_request.json", "01_P1_a1_response.json", "02_P1_a2_request.json", "02_P1_a2_response.json", "03_P2_a1_request.json",
                     "03_P2_a1_response.json", "calls.jsonl", "run_manifest.json"]
    saved = json.loads((tmp_path / "run" / "01_P1_a1_response.json").read_text())
    assert saved["choices"][0]["message"]["reasoning_content"] == "thinking"          # the server's reasoning is kept, never parsed as the answer
    lines = [json.loads(l) for l in (tmp_path / "run" / "calls.jsonl").read_text().splitlines()]
    assert [(l["call"], l["attempt"]) for l in lines] == [("P1", 1), ("P1", 2), ("P2", 1)] and all(len(l["rendered_prompt_sha256"]) == 64 for l in lines)
    man = json.loads((tmp_path / "run" / "run_manifest.json").read_text())
    assert man["ticker"] == "SYN" and man["reasoning_prefix"] == "Reasoning strength: xhigh\n" and man["prompt_hashes"] == m["prompt_hashes"]
    assert {"P1.txt", "P2.txt", "P3.txt", "P4.txt", "P5.txt", "P6.txt", "system.txt", "inputs.json", "prompt_set"} <= set(man["prompt_hashes"])
    assert len(man["system_message_sha256"]) == 64 and man["base_url"] == "http://127.0.0.1:8080"


def test_prompt_hashes_are_the_files_sha256_and_change_with_the_wording(tmp_path, monkeypatch):
    import hashlib
    h = prompting.prompt_hashes()
    assert h["P1.txt"] == hashlib.sha256((prompting.PROMPT_DIR / "P1.txt").read_bytes().replace(b"
", b"
")).hexdigest()
    d = tmp_path / "prompts"
    d.mkdir()
    for p in prompting.PROMPT_DIR.iterdir():
        (d / p.name).write_bytes(p.read_bytes())
    (d / "P1.txt").write_bytes((d / "P1.txt").read_bytes() + b"\nextra\n")
    monkeypatch.setattr(prompting, "PROMPT_DIR", d)
    h2 = prompting.prompt_hashes()
    assert h2["P1.txt"] != h["P1.txt"] and h2["prompt_set"] != h["prompt_set"] and h2["P2.txt"] == h["P2.txt"]


def test_a_response_without_a_message_is_a_transport_error(tmp_path):
    class Bad:
        def chat(self, req):
            return {"error": "boom"}
    with pytest.raises(MuseTransportError):
        MuseRunner(Bad(), tmp_path).call("P1", "u", ok_validator)


# ---- the real client with a fake urlopen: no network, no server -------------------------------------------------------------------------------

class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_client_posts_to_the_openai_endpoint_of_the_default_url():
    seen = {}

    def fake(req, timeout):
        seen["url"], seen["body"], seen["timeout"] = req.full_url, json.loads(req.data), timeout
        return FakeResp(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())
    c = OpenAICompatClient(urlopen=fake)
    assert c.chat({"messages": []})["choices"][0]["message"]["content"] == "{}"
    assert seen["url"] == "http://127.0.0.1:8080/v1/chat/completions" and seen["body"] == {"messages": []}
    assert OpenAICompatClient("http://10.0.0.5:9000/", urlopen=fake).base_url == "http://10.0.0.5:9000"


@pytest.mark.parametrize("exc", [urllib.error.URLError("refused"), ConnectionRefusedError("x"), TimeoutError("slow"),
                                 urllib.error.HTTPError("u", 500, "err", {}, io.BytesIO(b"oops"))])
def test_server_failures_are_transport_errors(exc):
    def fake(req, timeout):
        raise exc
    with pytest.raises(MuseTransportError):
        OpenAICompatClient(urlopen=fake).chat({})


def test_a_non_json_body_is_a_transport_error():
    with pytest.raises(MuseTransportError):
        OpenAICompatClient(urlopen=lambda req, timeout: FakeResp(b"<html>")).chat({})
