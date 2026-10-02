"""Muse integration, M5: the window, the timeouts and the retries, as P7 validated them, through the real harness loop
(analyst_tools.chat_with_tools and consensus_valuation.main) and an in-process fake llama-server. CPU only.

  a prompt over the window   400 exceed_context_size_error -> provider HTTP 500 `context_overflow` -> the harness counts a
                             server_error (two end the sample), and the turn record carries the cause
  a turn at num_predict      done_reason "length" -> the window retry fires once (P7 C3)
  a killed server            connection_reset / engine_not_ready as HTTP 500, recorded, fast (P7 D2)
  the other retries          empty-report retry (+50,000), truncated-report continuation, desk continuation (C8): unchanged
  the caller's timeout       fires first as TimeoutError, and the server's request is stopped (the connection is closed)"""
import json
import sys
import time
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
REPO = AUDIT_DIR.parents[1]
for p in (str(AUDIT_DIR), str(REPO), str(REPO / "tests"), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import analyst_tools as at  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import pack_facts  # noqa: E402
from llamacpp_fakes import completion, fake_llama, muse_env, overflow_body, tool_call  # noqa: E402,F401
from test_consensus_anchor_gate import _DUMMY_PACK, _SAMPLE_MEMO  # noqa: E402

REPORT = "y" * 6000


@pytest.fixture
def run(muse_env, monkeypatch, tmp_path):
    monkeypatch.setattr(at, "search_web", lambda *a, **k: {"results": [], "n_results": 0, "query": "q"})

    def go(**kw):
        kw.setdefault("think", "high")
        kw.setdefault("verbose", False)
        return at.chat_with_tools(muse_env.cfg["model_tag"], "PACK", tmp_path / "s", **kw)
    return go


# ------------------------------------------------------------------ a prompt over the window (P7 C2)

def test_a_prompt_over_the_window_is_a_recorded_server_error_with_its_cause_and_the_next_request_succeeds(muse_env, run):
    muse_env.fake.script = [("json", 400, overflow_body()), ("json", 200, completion(REPORT))]
    t0 = time.time()
    rep, think, meta = run()
    assert time.time() - t0 < 60                                                   # P7 C2: within 60 s
    first, second = meta["turns"][:2]
    assert first["server_error"] is True and first["http_status"] == 500 and first["server_error_cause"] == "context_overflow"
    assert first["done_reason"] == "server_error" and first["gen_tokens"] is None
    assert second.get("window_retry") is True and "server_error_cause" not in second
    assert rep == REPORT and meta["failure"] is None


def test_two_refusals_end_the_sample_as_a_server_error_with_the_cause_on_both_turns(muse_env, run):
    muse_env.fake.script = [("json", 400, overflow_body())]
    rep, think, meta = run()
    assert meta["failure"] == "server_error" and rep == ""
    assert [t["server_error_cause"] for t in meta["turns"]] == ["context_overflow", "context_overflow"]
    assert [t["http_status"] for t in meta["turns"]] == [500, 500]
    assert len(muse_env.fake.requests) == 2


def test_the_refusal_carries_the_servers_counts_in_the_http_error_body(muse_env):
    import urllib.error
    import llm_provider as prov
    muse_env.fake.script = [("json", 400, overflow_body(101391, 98304))]
    with pytest.raises(urllib.error.HTTPError) as e:
        prov.chat({"model": "m", "messages": [{"role": "user", "content": "x"}]}, 30)
    err = json.loads(e.value.read())["error"]
    assert err.startswith("context_overflow request (101391 tokens) exceeds the available context size (98304 tokens)")
    assert '"n_prompt_tokens": 101391' in err and '"n_ctx": 98304' in err


# ------------------------------------------------------------------ a turn at num_predict (P7 C3)

def test_a_turn_that_reaches_num_predict_triggers_exactly_one_window_retry(muse_env, run):
    muse_env.fake.script = [("json", 200, completion("", finish="length", usage=(24000, 1024)))]
    rep, think, meta = run(ctx=98304, num_predict=64)
    turns = meta["turns"]
    assert len(turns) == 2 and len(muse_env.fake.requests) == 2
    assert turns[0]["done_reason"] == "length" and turns[0]["n_tool_calls"] == 0 and not turns[0].get("window_retry")
    assert turns[1]["window_retry"] is True
    assert meta["window_retry_used"] is True and meta["failure"] == "window_exhausted_twice"
    assert muse_env.fake.requests[0]["max_tokens"] == 1024                      # the harness floors num_predict at 1024


def test_a_window_retry_that_delivers_is_a_normal_sample(muse_env, run):
    muse_env.fake.script = [("json", 200, completion("", finish="length", usage=(24000, 1024))),
                            ("json", 200, completion(REPORT, usage=(25000, 3000)))]
    rep, think, meta = run(ctx=98304, num_predict=64)
    assert rep == REPORT and meta["failure"] is None and meta["window_retry_used"] is True
    assert [t["done_reason"] for t in meta["turns"][:2]] == ["length", "stop"]
    assert meta["turns"][1]["window_retry"] is True              # (a third turn is the desk continuation, C8: no desk run yet)


# ------------------------------------------------------------------ a killed or absent server (P7 D2)

def test_a_connection_reset_is_a_recorded_server_error_twice_and_fast(muse_env, run):
    muse_env.fake.script = [("reset",)]
    t0 = time.time()
    rep, think, meta = run()
    assert time.time() - t0 < 15
    assert meta["failure"] == "server_error" and rep == ""
    assert [t["server_error_cause"] for t in meta["turns"]] == ["connection_reset", "connection_reset"]


def test_a_server_that_is_gone_is_engine_not_ready_and_nothing_is_sent(muse_env, run):
    muse_env.fake.close()
    t0 = time.time()
    rep, think, meta = run()
    assert time.time() - t0 < 15
    assert meta["failure"] == "server_error"
    assert [t["server_error_cause"] for t in meta["turns"]] == ["engine_not_ready", "engine_not_ready"]
    assert muse_env.fake.requests == []


def test_a_missing_engine_file_is_engine_not_ready_in_the_harness(muse_env, run):
    muse_env.engine_file.unlink()
    rep, think, meta = run()
    assert meta["failure"] == "server_error" and meta["turns"][0]["server_error_cause"] == "engine_not_ready"


def test_the_server_coming_back_lets_the_next_request_complete(muse_env, run):
    muse_env.fake.script = [("reset",), ("json", 200, completion(REPORT))]
    rep, think, meta = run(max_model_calls=0)                  # the reset is turn 1; the window retry is answered
    assert rep == REPORT and meta["failure"] is None
    assert meta["turns"][0]["server_error_cause"] == "connection_reset"


# ------------------------------------------------------------------ the caller's timeout

def test_a_caller_timeout_is_the_timeout_urllib_raises_at_the_caller_and_the_servers_request_is_stopped(muse_env, run):
    muse_env.fake.script = [("watch", 5, completion("late"))]
    t0 = time.time()
    with pytest.raises(TimeoutError):
        run(timeout=0.5)
    assert time.time() - t0 < 3
    deadline = time.time() + 3
    while muse_env.fake.client_closed_at is None and time.time() < deadline:
        time.sleep(0.02)
    assert muse_env.fake.client_closed_at is not None, "the provider must close the connection when the caller's timeout fires"
    assert muse_env.fake.client_closed_at < 3


# ------------------------------------------------------------------ the other retries are unchanged

def test_the_desk_continuation_fires_once_through_the_provider(muse_env, run):
    memo = "# MEMO\n" + "x" * 6000
    muse_env.fake.script = [("json", 200, completion(memo)), ("json", 200, completion(memo + " again"))]
    rep, think, meta = run()                                   # the desk is open and no desk run exists
    assert len(muse_env.fake.requests) == 2
    assert meta["continuation_for_desk"] is not None
    last_user = muse_env.fake.requests[1]["messages"][-1]
    assert last_user["role"] == "user" and last_user["content"].startswith(("Your memorandum has", "Your turn ended without"))
    assert [t.get("continuation_for_desk") for t in meta["turns"]] == [None, True]
    tools_sent = [t["function"]["name"] for t in muse_env.fake.requests[1]["tools"]]
    assert tools_sent == ["run_financial_model"]               # only the desk is open


def _run_cv_no_tools(muse_env, monkeypatch, tmp_path, capsys, extra=()):
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    pack_file = frozen / "_pack.md"
    pack_file.write_text(_DUMMY_PACK, encoding="utf-8")
    facts = pack_facts.from_text(_DUMMY_PACK)
    facts["source"] = "build"
    facts["consensus_data_status"] = "enrich_missing"
    pack_facts.write_sidecar(frozen, facts)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--model", muse_env.cfg["model_tag"], "--ctx", "98304",
                                      "--price", "100", "--samples", "1", "--no-early-stop", "--pack-file", str(pack_file),
                                      "--out-dir", str(out_dir), *extra])
    cv.main()
    return capsys.readouterr().out, out_dir


def test_the_truncated_report_continuation_goes_through_the_provider(muse_env, monkeypatch, tmp_path, capsys,
                                                                     screener_data_stub):
    partial = "# MEMO\n" + "z" * 3000
    muse_env.fake.script = [("json", 200, completion(partial, finish="length", usage=(30000, 65536))),
                            ("json", 200, completion(_SAMPLE_MEMO, usage=(40000, 4000)))]
    out, out_dir = _run_cv_no_tools(muse_env, monkeypatch, tmp_path, capsys)
    assert "TRUNCATED mid-report" in out
    first, cont = muse_env.fake.requests
    roles = [m["role"] for m in cont["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert cont["messages"][2]["content"] == partial and cont["messages"][3]["content"].startswith("Your institutional memorandum was truncated")
    assert cont["max_tokens"] == 32768 and cont["seed"] == 1000 + 1 + 100             # continue_report's seed, as today
    assert first["seed"] == 1001 and first["max_tokens"] == cv.NUM_PREDICT


def test_a_refused_sample_in_the_no_tools_path_is_a_failed_sample_not_a_crash(muse_env, monkeypatch, tmp_path, capsys,
                                                                             screener_data_stub):
    muse_env.engine_file.unlink()
    out, out_dir = _run_cv_no_tools(muse_env, monkeypatch, tmp_path, capsys)
    assert "sample 1: FAILED" in out and "HTTP Error 500" in out
    assert muse_env.fake.requests == []
