"""Muse integration, M2.2 and M8 item 3: under depth_provider "ollama" every analyst-model call site sends today's request
byte for byte: the same URL, the same body bytes, the same headers, the same timeout, one urlopen call, nothing else.

"Today's" is what the code at 9ba5cba sent: urllib.request.Request("http://127.0.0.1:11434/api/chat",
data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}) followed by
urllib.request.urlopen(req, timeout=<the call site's timeout>) and json.loads(r.read().decode()). The expectations below are
written out here, not read from the provider. The call sites are the five of brief M2.4 that are on the depth path:

  analyst_tools._post (the tools path: samples and discovery)       caller timeout, 14,400 s by default, 1,800 s from discovery
  catalyst_research._llm_fix_json                                    900 s
  consensus_valuation.continue_report                                1,800 s
  consensus_valuation.main, the no-tools path                        7,200 s
  consensus_valuation.main, the no-tools path's empty-report retry   7,200 s

(capability_test.py:3993 is a standalone CLI, not on the depth path, and is unchanged.)"""
import ast
import inspect
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
REPO = AUDIT_DIR.parents[1]                   # the repository root
for p in (str(AUDIT_DIR), str(REPO), str(REPO / "tests"), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import analyst_tools as at  # noqa: E402
import capability_test as cap  # noqa: E402
import catalyst_research as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import llm_provider as prov  # noqa: E402
import pack_facts  # noqa: E402
import rs2_data  # noqa: E402
from test_consensus_anchor_gate import _DUMMY_PACK, _SAMPLE_MEMO  # noqa: E402

_REAL_LLM_FIX_JSON = cr._llm_fix_json      # the suite's autouse fixture replaces it per test with a stub that refuses

TODAYS_URL = "http://127.0.0.1:11434/api/chat"
TODAYS_HEADERS = {"Content-type": "application/json"}      # what urllib stores for {"Content-Type": "application/json"}
REPORT = "y" * 6000


class _Resp:
    def __init__(self, raw):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._raw


class Spy:
    """Stands in for urllib.request.urlopen and records exactly how it was called."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, req, *args, **kwargs):
        self.calls.append({"url": req.full_url, "data": req.data, "headers": dict(req.header_items()),
                           "method": req.get_method(), "args": args, "kwargs": kwargs})
        r = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(r, BaseException):
            raise r
        return _Resp(r if isinstance(r, bytes) else json.dumps(r, ensure_ascii=False).encode("utf-8"))


@pytest.fixture
def ollama(monkeypatch):
    """depth_provider "ollama" and a way to install the urlopen spy."""
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "ollama")

    def install(*replies):
        spy = Spy(*replies)
        monkeypatch.setattr(urllib.request, "urlopen", spy)
        return spy
    return install


def assert_todays_request(call, body, timeout):
    """One urlopen call: today's URL, bytes, headers, method and keyword timeout, nothing else."""
    assert call["url"] == TODAYS_URL
    assert call["data"] == json.dumps(body).encode()
    assert call["headers"] == TODAYS_HEADERS
    assert call["method"] == "POST"
    assert call["args"] == () and call["kwargs"] == {"timeout": timeout}


# ------------------------------------------------------------------ the provider itself

def test_the_ollama_provider_returns_what_json_loads_of_the_decoded_body_returns(ollama):
    reply = {"message": {"role": "assistant", "content": "café ═ “quoted”"}, "done": True, "eval_count": 3}
    spy = ollama(reply)
    body = {"model": "m", "stream": False, "messages": [{"role": "user", "content": "héllo ═"}], "options": {"seed": 0}}
    assert prov.chat(body, 55) == reply
    assert len(spy.calls) == 1
    assert_todays_request(spy.calls[0], body, 55)
    assert spy.calls[0]["data"] == json.dumps(body).encode()       # ensure_ascii and the default separators, as today
    assert b"\\u00e9" in spy.calls[0]["data"]


def test_an_http_error_from_ollama_propagates_unchanged(ollama):
    err = urllib.error.HTTPError(TODAYS_URL, 500, "Internal Server Error", {}, None)
    ollama(err)
    with pytest.raises(urllib.error.HTTPError) as e:
        prov.chat({"messages": []}, 10)
    assert e.value is err and not hasattr(e.value, "cause")


@pytest.mark.parametrize("exc", [TimeoutError("timed out"), urllib.error.URLError("refused"), ConnectionResetError("reset"),
                                 OSError("x")])
def test_any_other_failure_propagates_unchanged(ollama, exc):
    ollama(exc)
    with pytest.raises(type(exc)) as e:
        prov.chat({"messages": []}, 10)
    assert e.value is exc


def test_under_ollama_the_provider_makes_no_other_call_and_reads_no_engine_file(ollama, monkeypatch, tmp_path):
    spy = ollama({"message": {"content": "x"}})
    monkeypatch.setattr(prov, "ENGINE_DIR", tmp_path / "does_not_exist")
    monkeypatch.setattr(prov, "pid_alive", lambda pid: pytest.fail("pid_alive called under ollama"))
    monkeypatch.setattr(prov, "health_ok", lambda *a, **k: pytest.fail("/health probed under ollama"))
    prov.chat({"messages": []}, 10)
    assert len(spy.calls) == 1 and spy.calls[0]["url"] == TODAYS_URL


def test_the_default_provider_is_ollama_and_so_is_the_production_config():
    cfg = json.loads((REPO / "config.json").read_text(encoding="utf-8"))
    assert cfg["depth_provider"] == "ollama" and cfg["depth_model"] == "rs2-analyst-deep-mtp5-v33"


def test_analyst_tools_still_defines_OLLAMA_for_the_tests_and_tools_that_import_it():
    assert at.OLLAMA == TODAYS_URL == prov.OLLAMA_URL


# ------------------------------------------------------------------ site 1: analyst_tools._post

def test_post_the_tools_path_sends_todays_request_with_the_default_14400s(ollama, tmp_path):
    spy = ollama({"message": {"role": "assistant", "content": REPORT}, "done_reason": "stop", "eval_count": 5,
                  "prompt_eval_count": 50, "prompt_eval_duration": 1000, "eval_duration": 2000})
    # max_model_calls=0 is the discovery mode: no desk, so the desk continuation (C8) does not add a second turn
    rep, think, meta = at.chat_with_tools("m", "PACK", tmp_path / "s", think=False, verbose=False, max_model_calls=0)
    assert rep == REPORT and meta["failure"] is None
    assert len(spy.calls) == 1
    body = json.loads(spy.calls[0]["data"])
    assert inspect.signature(at.chat_with_tools).parameters["timeout"].default == 14400
    assert body["model"] == "m" and body["stream"] is False and body["think"] is False
    assert body["messages"] == [{"role": "user", "content": "PACK"}] and "tools" in body
    assert_todays_request(spy.calls[0], body, 14400)


def test_post_passes_the_callers_timeout_through(ollama, tmp_path):
    spy = ollama({"message": {"content": REPORT}, "done_reason": "stop"})
    at.chat_with_tools("m", "PACK", tmp_path / "s", think=False, verbose=False, timeout=1800, max_model_calls=0)
    assert_todays_request(spy.calls[0], json.loads(spy.calls[0]["data"]), 1800)


def test_post_handles_an_ollama_http_500_exactly_as_before(ollama, tmp_path):
    err = urllib.error.HTTPError(TODAYS_URL, 500, "Internal Server Error", {}, None)
    ollama(err)
    rep, think, meta = at.chat_with_tools("m", "PACK", tmp_path / "s", think=False, verbose=False)
    assert meta["failure"] == "server_error" and rep == ""
    assert [t.get("http_status") for t in meta["turns"]] == [500, 500]
    assert all("server_error_cause" not in t for t in meta["turns"])          # an Ollama 500 carries no cause


def test_post_re_raises_a_non_500_http_error(ollama, tmp_path):
    ollama(urllib.error.HTTPError(TODAYS_URL, 404, "Not Found", {}, None))
    with pytest.raises(urllib.error.HTTPError) as e:
        at.chat_with_tools("m", "PACK", tmp_path / "s", think=False, verbose=False)
    assert e.value.code == 404


def test_the_discovery_and_sample_call_sites_pass_the_timeouts_the_brief_lists():
    """catalyst_research.run -> chat_with_tools(timeout=1800); consensus_valuation's two chat_with_tools calls leave the
    default 14400 (the tools path)."""
    def timeouts(module):
        tree = ast.parse(inspect.getsource(module))
        out = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "chat_with_tools":
                out.append({k.arg: ast.literal_eval(k.value) for k in n.keywords if k.arg == "timeout"})
        return out
    assert timeouts(cr) == [{"timeout": 1800}]
    assert timeouts(cv) == [{}, {}]


# ------------------------------------------------------------------ site 2: catalyst_research._llm_fix_json

def test_llm_fix_json_sends_todays_request_with_900s(ollama, monkeypatch):
    monkeypatch.setattr(cr, "_llm_fix_json", _REAL_LLM_FIX_JSON)
    spy = ollama({"message": {"content": "```json\n{\"a\": 1}\n```"}})
    out = cr._llm_fix_json("m", "{bad", "err")
    assert out == '{"a": 1}'
    expected = {"model": "m", "stream": False, "think": False,
                "options": {"num_ctx": 32768, "num_predict": 12288, "temperature": 0},
                "messages": [{"role": "user", "content": (
                    "The JSON below does not parse (err). Return the same content as valid JSON: fix only the syntax "
                    "(brackets, commas, quotes inside strings - escape them), change no wording, add or drop nothing. "
                    "Output only the JSON.\n\n{bad")}]}
    assert len(spy.calls) == 1
    assert_todays_request(spy.calls[0], expected, 900)


# ------------------------------------------------------------------ site 3: consensus_valuation.continue_report

def test_continue_report_sends_todays_request_with_1800s(ollama):
    spy = ollama({"message": {"content": "continued", "thinking": "t"}, "done_reason": "stop", "eval_count": 7})
    partial = "partial memorandum " * 20
    out = cv.continue_report(model="m", pack="PACK", partial_report=partial, ctx=98304, seed=1101, think="high",
                             draft_num_predict=4, temperature=None, num_batch=256)
    assert out == ("continued", "t", {"done_reason": "stop", "generated_tokens": 7})
    assert inspect.signature(cv.continue_report).parameters["timeout"].default == 1800
    body = json.loads(spy.calls[0]["data"])
    expected = {"model": "m", "stream": False, "think": "high",
                "messages": [{"role": "user", "content": "PACK"}, {"role": "assistant", "content": partial},
                             body["messages"][2]],
                "options": {"num_ctx": 98304, "num_batch": 256, "num_predict": 32768, "temperature": 0.6,
                            "repeat_penalty": 1.05, "presence_penalty": 0.05, "seed": 1101, "draft_num_predict": 4}}
    assert body == expected and list(body["options"]) == list(expected["options"])
    assert body["messages"][2]["content"].startswith("Your institutional memorandum was truncated")
    assert_todays_request(spy.calls[0], expected, 1800)


def test_continue_report_reports_a_failure_exactly_as_before(ollama):
    ollama(urllib.error.HTTPError(TODAYS_URL, 500, "Internal Server Error", {}, None))
    out = cv.continue_report(model="m", pack="PACK", partial_report="p" * 300, ctx=98304)
    assert out == ("", "", {"done_reason": "error", "error": "HTTP Error 500: Internal Server Error"})


# ------------------------------------------------------------------ sites 4 and 5: the no-tools path and its retry

def _blocked_sockets(monkeypatch):
    class BlockedSocket(socket.socket):
        def __init__(self, *a, **k):
            raise RuntimeError("socket access blocked in test")
    monkeypatch.setattr(socket, "socket", BlockedSocket)


def _run_no_tools(monkeypatch, tmp_path, capsys, replies, extra=()):
    spy = Spy(*replies)
    monkeypatch.setattr(urllib.request, "urlopen", spy)
    _blocked_sockets(monkeypatch)
    frozen = tmp_path / "frozen"
    frozen.mkdir(parents=True)
    pack_file = frozen / "_pack.md"
    pack_file.write_text(_DUMMY_PACK, encoding="utf-8")
    facts = pack_facts.from_text(_DUMMY_PACK)
    facts["source"] = "build"
    facts["consensus_data_status"] = "enrich_missing"
    pack_facts.write_sidecar(frozen, facts)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--model", "m", "--ctx", "98304", "--price", "100",
                                      "--samples", "1", "--no-early-stop", "--pack-file", str(pack_file),
                                      "--out-dir", str(out_dir), *extra])
    cv.main()
    capsys.readouterr()
    return spy, out_dir


def test_the_no_tools_path_sends_todays_request_with_7200s(monkeypatch, tmp_path, capsys, screener_data_stub):
    spy, out_dir = _run_no_tools(monkeypatch, tmp_path, capsys,
                                 [{"message": {"content": _SAMPLE_MEMO}, "done_reason": "stop", "eval_count": 500,
                                   "prompt_eval_count": 100}])
    assert len(spy.calls) == 1
    pack = json.loads(spy.calls[0]["data"])["messages"][0]["content"]
    assert pack == _DUMMY_PACK
    expected = {"model": "m", "stream": False, "think": "high", "messages": [{"role": "user", "content": pack}],
                "options": {"num_ctx": 98304, "num_predict": cv.NUM_PREDICT, "repeat_penalty": 1.05,
                            "presence_penalty": 0.05, "seed": 1001}}
    assert_todays_request(spy.calls[0], expected, 7200)
    assert list(out_dir.glob("GEV_*/consensus.json"))


def test_the_empty_report_retry_sends_todays_request_with_a_perturbed_seed_and_7200s(monkeypatch, tmp_path, capsys,
                                                                                    screener_data_stub):
    spy, out_dir = _run_no_tools(monkeypatch, tmp_path, capsys,
                                 [{"message": {"content": ""}, "done_reason": "stop", "eval_count": 9},
                                  {"message": {"content": _SAMPLE_MEMO}, "done_reason": "stop", "eval_count": 500,
                                   "prompt_eval_count": 100}])
    assert len(spy.calls) == 2
    pack = json.loads(spy.calls[0]["data"])["messages"][0]["content"]
    base = {"model": "m", "stream": False, "think": "high", "messages": [{"role": "user", "content": pack}],
            "options": {"num_ctx": 98304, "num_predict": cv.NUM_PREDICT, "repeat_penalty": 1.05, "presence_penalty": 0.05,
                        "seed": 1001}}
    assert_todays_request(spy.calls[0], base, 7200)
    retry = json.loads(json.dumps(base))
    retry["options"]["seed"] = 1001 + 50000                      # the retry's perturbed seed, as today
    assert_todays_request(spy.calls[1], retry, 7200)


def test_the_no_tools_path_keeps_its_optional_options_in_todays_order(monkeypatch, tmp_path, capsys, screener_data_stub):
    spy, _ = _run_no_tools(monkeypatch, tmp_path, capsys,
                           [{"message": {"content": _SAMPLE_MEMO}, "done_reason": "stop", "eval_count": 5}],
                           extra=("--num-batch", "256", "--draft-num-predict", "4", "--temperature", "0.3"))
    opts = json.loads(spy.calls[0]["data"])["options"]
    assert list(opts) == ["num_ctx", "num_batch", "num_predict", "repeat_penalty", "presence_penalty", "seed",
                          "draft_num_predict", "temperature"]
    assert opts["num_batch"] == 256 and opts["draft_num_predict"] == 4 and opts["temperature"] == 0.3
