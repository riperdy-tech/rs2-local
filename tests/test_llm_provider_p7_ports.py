"""Muse integration, M8 item 2: every step-0 test of P7 (SP/p7_serving/tests/test_adapter.py), ported to the provider.

The adapter answered over HTTP; the provider raises urllib.error.HTTPError(500) with the same JSON body, so `env.post` returns
the (status, body) pair the adapter's tests saw and the assertions are the P7 assertions. Each test keeps its P7 name (prefix
`test_`), so the correspondence can be checked by name.

What P7's file tested that has no counterpart here, and why:
  test_status_endpoint_counts_in_flight_and_errors      the adapter's /adapter/status endpoint; the provider is a library call
  test_log_records_every_request_with_the_arm           the adapter's jsonl log; the provider answers in the response
  test_load_engine_requires_the_provenance_keys         the adapter's --engine-json file; here engine.json is checked before every
                                                        request (tests/test_llm_provider_server_identity.py)
  test_bad_request_json_and_shape (JSON part)           the provider receives a dict, not bytes; the shape part is ported
  test_unsupported_path_is_named                        the adapter's HTTP paths; the provider has one entry point
  test_pinned_system_file_is_the_modelfile_system_verbatim   tests/test_muse_system.py (the v33 file; the v32 construction too)
  test_no_system_file_means_no_injection               the adapter's SYSTEM was optional; the provider's is mandatory and pinned

P7's second step-0 file, test_harness_step0.py, tested the harness patches and the crash behaviour of the chain. Its tests live
where the code they test does:
  turn_metrics / chat_with_tools engine and draft fields, the mid-sample engine change     tools/audit_202608/tests/test_llm_provider_provenance.py
  the forced length turn (one window retry), upstream reset, overflow, "adapter down"      tools/audit_202608/tests/test_llm_provider_window_and_retries.py
  D2: killing llama-server mid-generation, recovery after a restart                        tests/test_llamacpp_server.py
  D2: killing the adapter                                                                  no counterpart: there is no adapter process
  --seed-base, the CLI against the mock, crash_test.judge / rescore                        revision 19's G2, and P7's run scripts (not rs2 code)
Where a P7 assertion read the adapter's log (`timings_missing`, `unparsed_tool_args`, `n_tool_calls`, `ignored_options`,
`sampling_stripped`), it reads the response here (ignored_options and sampling_stripped), or the translated reply."""
import json
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llamacpp_fakes import chat_body, completion, fake_llama, muse_env  # noqa: E402,F401
import llm_provider as prov  # noqa: E402


# ------------------------------------------------------------------ mapping of a good reply

def test_text_reply_maps_usage_timings_and_engine(muse_env):
    muse_env.fake.script = [("json", 200, completion("the memo", usage=(1234, 56)))]
    code, out = muse_env.post(chat_body())
    assert code == 200 and out["done"] is True, out
    assert out["message"] == {"role": "assistant", "content": "the memo"}
    assert out["done_reason"] == "stop"
    assert out["prompt_eval_count"] == 1234 and out["eval_count"] == 56
    assert out["eval_duration"] == 400_000_000 and out["prompt_eval_duration"] == 500_000_000
    assert out["draft_n"] == 30 and out["draft_n_accepted"] == 21
    assert out["reasoning_in_content"] is False
    engine = json.loads(muse_env.engine_file.read_text(encoding="utf-8"))
    assert out["engine"] == engine
    for k in ("endpoint", "build", "model_sha256", "drafter_sha256", "spec", "server_cmdline_sha256"):
        assert out["engine"][k] == engine[k]


def test_zero_timing_is_a_value_not_an_absence(muse_env):
    t = {"prompt_ms": 0.0, "predicted_ms": 0.0, "predicted_n": 0, "prompt_n": 0}
    muse_env.fake.script = [("json", 200, completion("x", tim=t))]
    code, out = muse_env.post(chat_body())
    assert out["eval_duration"] == 0 and out["prompt_eval_duration"] == 0
    assert out["draft_n"] is None and out["draft_n_accepted"] is None   # a plain server reports no draft counters


def test_missing_timings_fall_back_to_wall_clock(muse_env):
    muse_env.fake.script = [("json", 200, completion("x", tim=None))]
    code, out = muse_env.post(chat_body())
    assert code == 200 and out["eval_duration"] > 0


@pytest.mark.parametrize("finish,done", [("stop", "stop"), ("length", "length"), ("tool_calls", "stop")])
def test_finish_reason_maps_to_done_reason(muse_env, finish, done):
    tcs = [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}] if finish == "tool_calls" else None
    muse_env.fake.script = [("json", 200, completion("", finish=finish, tool_calls=tcs))]
    code, out = muse_env.post(chat_body())
    assert code == 200 and out["done_reason"] == done


@pytest.mark.parametrize("finish", [None, "content_filter", "weird"])
def test_unmapped_finish_reason_is_a_named_500(muse_env, finish):
    muse_env.fake.script = [("json", 200, completion("x", finish=finish))]
    code, out = muse_env.post(chat_body())
    assert code == 500 and out["cause"] == "unmapped_finish_reason" and out["error"].startswith("unmapped_finish_reason")


# ------------------------------------------------------------------ tool calls

def test_reply_tool_calls_several_ids_and_string_arguments_become_dicts(muse_env):
    tcs = [{"id": "call_a", "type": "function", "function": {"name": "search_web", "arguments": '{"query": "q1"}'}},
           {"id": "call_b", "type": "function", "function": {"name": "fetch_page", "arguments": '{"url": "u"}'}},
           {"type": "function", "function": {"name": "run_financial_model", "arguments": {"price": 1.5}}},
           {"id": "call_e", "type": "function", "function": {"name": "noargs", "arguments": ""}}]
    muse_env.fake.script = [("json", 200, completion("", finish="tool_calls", tool_calls=tcs))]
    code, out = muse_env.post(chat_body())
    got = out["message"]["tool_calls"]
    assert [c["id"] for c in got[:2]] == ["call_a", "call_b"] and got[2]["id"] and got[2]["id"] != "call_a"
    assert got[0]["function"] == {"name": "search_web", "arguments": {"query": "q1"}}
    assert got[1]["function"]["arguments"] == {"url": "u"}
    assert got[2]["function"]["arguments"] == {"price": 1.5}
    assert got[3]["function"]["arguments"] == {}
    assert len({c["id"] for c in got}) == 4


def test_unparseable_tool_arguments_keep_raw_and_are_counted(muse_env):
    tcs = [{"id": "c", "type": "function", "function": {"name": "f", "arguments": '{"a": '}},
           {"id": "d", "type": "function", "function": {"name": "f", "arguments": "[1, 2]"}}]
    muse_env.fake.script = [("json", 200, completion("", finish="tool_calls", tool_calls=tcs))]
    code, out = muse_env.post(chat_body())
    args = [c["function"]["arguments"] for c in out["message"]["tool_calls"]]
    assert args == [{"_raw": '{"a": '}, {"_raw": "[1, 2]"}]                 # the harness's `_raw` test (registration I7) reads this


def test_request_tool_history_ids_arguments_and_results_are_matched(muse_env):
    """Assistant turn with two calls (no ids, dict arguments) followed by two tool results: each result carries
    the id of its call, in order; a second assistant turn with an explicit id is matched by that id."""
    muse_env.fake.script = [("json", 200, completion("ok"))]
    msgs = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "search_web", "arguments": {"query": "a"}}},
                {"function": {"name": "fetch_page", "arguments": {"url": "b"}}}]},
            {"role": "tool", "content": "result A"},
            {"role": "tool", "content": "result B"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "explicit_1", "function": {"name": "search_web", "arguments": "{\"query\": \"c\"}"}},
                {"id": "explicit_2", "function": {"name": "search_web", "arguments": {"query": "d"}}}]},
            {"role": "tool", "content": "result D", "tool_call_id": "explicit_2"},
            {"role": "tool", "content": "result C", "tool_call_id": "explicit_1"}]
    tools = [{"type": "function", "function": {"name": "search_web", "parameters": {}}}]
    code, out = muse_env.post(chat_body(messages=msgs, tools=tools))
    assert code == 200
    sent = muse_env.fake.requests[0]
    assert sent["tools"] == tools
    m = sent["messages"][1:]                       # [0] is the injected SYSTEM
    a1 = m[1]["tool_calls"]
    assert [t["type"] for t in a1] == ["function", "function"]
    assert len({t["id"] for t in a1}) == 2
    assert json.loads(a1[0]["function"]["arguments"]) == {"query": "a"}
    assert json.loads(a1[1]["function"]["arguments"]) == {"url": "b"}
    assert (m[2]["tool_call_id"], m[2]["content"]) == (a1[0]["id"], "result A")
    assert (m[3]["tool_call_id"], m[3]["content"]) == (a1[1]["id"], "result B")
    assert m[4]["tool_calls"][0]["id"] == "explicit_1"
    assert json.loads(m[4]["tool_calls"][0]["function"]["arguments"]) == {"query": "c"}
    assert (m[5]["tool_call_id"], m[5]["content"]) == ("explicit_2", "result D")
    assert (m[6]["tool_call_id"], m[6]["content"]) == ("explicit_1", "result C")


def test_tool_results_matched_by_tool_name_when_out_of_order(muse_env):
    muse_env.fake.script = [("json", 200, completion("ok"))]
    msgs = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "id_s", "function": {"name": "search_web", "arguments": {}}},
                {"id": "id_f", "function": {"name": "fetch_page", "arguments": {}}}]},
            {"role": "tool", "content": "page", "tool_name": "fetch_page"},
            {"role": "tool", "content": "hits", "tool_name": "search_web"}]
    muse_env.post(chat_body(messages=msgs))
    m = muse_env.fake.requests[0]["messages"][1:]
    assert (m[2]["tool_call_id"], m[3]["tool_call_id"]) == ("id_f", "id_s")


def test_orphan_tool_result_is_counted_not_dropped(muse_env):
    muse_env.fake.script = [("json", 200, completion("ok"))]
    muse_env.post(chat_body(messages=[{"role": "user", "content": "x"}, {"role": "tool", "content": "stray"}]))
    assert muse_env.fake.requests[0]["messages"][2]["tool_call_id"].startswith("call_orphan")


# ------------------------------------------------------------------ the error table (every failure is HTTP 500)

def _assert_named_500(res, cause):
    code, out = res
    assert code == 500, out
    assert out["cause"] == cause
    assert out["error"].startswith(cause)
    return out


def test_error_context_overflow_carries_the_servers_message(muse_env):
    body = {"error": {"code": 400, "type": "exceed_context_size_error", "n_prompt_tokens": 101000, "n_ctx": 98304,
                      "message": "request (101000 tokens) exceeds the available context size (98304 tokens), try increasing it"}}
    muse_env.fake.script = [("json", 400, body)]
    out = _assert_named_500(muse_env.post(chat_body()), "context_overflow")
    assert "exceeds the available context size (98304 tokens)" in out["error"]
    assert "101000" in out["error"]


def test_error_context_overflow_recognised_from_the_message_alone(muse_env):
    muse_env.fake.script = [("json", 400, {"error": {"code": 400, "message": "the request exceeds the available context size (10 tokens)"}})]
    _assert_named_500(muse_env.post(chat_body()), "context_overflow")


@pytest.mark.parametrize("code", [400, 404, 422, 429])
def test_error_other_4xx(muse_env, code):
    muse_env.fake.script = [("json", code, {"error": {"code": code, "message": "nope", "type": "invalid_request_error"}})]
    out = _assert_named_500(muse_env.post(chat_body()), "upstream_4xx")
    assert f"HTTP {code}" in out["error"] and "nope" in out["error"]


@pytest.mark.parametrize("code", [500, 503])
def test_error_upstream_5xx(muse_env, code):
    muse_env.fake.script = [("json", code, {"error": {"code": code, "message": "Loading model"}})]
    out = _assert_named_500(muse_env.post(chat_body()), "upstream_5xx")
    assert f"HTTP {code}" in out["error"]


def test_error_unparseable_json(muse_env):
    muse_env.fake.script = [("raw", 200, b"<html>not json</html>")]
    _assert_named_500(muse_env.post(chat_body()), "upstream_bad_json")


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"finish_reason": "stop"}]}, []])
def test_error_reply_that_is_json_but_not_a_completion(muse_env, payload):
    muse_env.fake.script = [("json", 200, payload)]
    _assert_named_500(muse_env.post(chat_body()), "upstream_bad_response")


def test_error_connection_refused(muse_env, monkeypatch):
    """Nothing listens on the port. The pre-request health check would refuse first (`engine_not_ready`); it is bypassed here
    so the upstream call itself meets the closed port, which is what a server that dies between the check and the request does."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()
    muse_env.cfg["port"] = dead_port
    muse_env.write_engine()
    monkeypatch.setattr(prov, "health_ok", lambda cfg, timeout=5: True)
    out = _assert_named_500(muse_env.post(chat_body()), "connection_refused")
    assert f"127.0.0.1:{dead_port}" in out["error"]


def test_error_connection_reset(muse_env):
    muse_env.fake.script = [("reset",)]
    _assert_named_500(muse_env.post(chat_body()), "connection_reset")


def test_error_upstream_timeout_is_below_the_harness_and_named(muse_env):
    muse_env.cfg["upstream_timeout_s"] = 0.5
    muse_env.fake.script = [("sleep", 3, completion("late"))]
    t0 = time.time()
    out = _assert_named_500(muse_env.post(chat_body(), timeout=30), "upstream_timeout")
    assert time.time() - t0 < 2.5
    assert "0.5s" in out["error"]


def test_default_timeout_is_below_the_harness_request_timeouts():
    import rs2_data
    assert rs2_data.CONFIG["llamacpp"]["upstream_timeout_s"] == 3600
    assert rs2_data.CONFIG["llamacpp"]["upstream_timeout_s"] < 7200   # chat_with_tools uses 14400, the no-tools path 7200


def test_handler_exception_becomes_a_500_and_the_next_request_is_served(muse_env, monkeypatch):
    muse_env.fake.script = [("json", 200, completion("fine"))]
    real = prov.to_openai
    calls = []

    def boom(body, system=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("synthetic handler bug")
        return real(body, system)
    monkeypatch.setattr(prov, "to_openai", boom)
    out = _assert_named_500(muse_env.post(chat_body()), "adapter_exception")
    assert "RuntimeError: synthetic handler bug" in out["error"]
    code, out2 = muse_env.post(chat_body())
    assert code == 200 and out2["message"]["content"] == "fine"


def test_bad_request_shape(muse_env):
    _assert_named_500(muse_env.post({"messages": "nope"}), "bad_request")
    _assert_named_500(muse_env.post(chat_body(stream=True)), "bad_request")
    assert muse_env.fake.requests == []                                 # refused before anything was sent to the server


def test_every_upstream_failure_is_http_500_never_another_status(muse_env):
    seen = set()
    for beh in [("json", 400, {"error": "x"}), ("json", 401, {}), ("json", 404, {}), ("json", 503, {}),
                ("json", 302, {}), ("raw", 200, b"zzz"), ("reset",)]:
        muse_env.fake.script = [beh]
        muse_env.fake.requests.clear()
        code, out = muse_env.post(chat_body())
        seen.add(code)
        assert "cause" in out
    assert seen == {500}


# ------------------------------------------------------------------ sampling

def test_sampling_fields_are_stripped_and_recorded_seed_and_max_tokens_kept(muse_env):
    muse_env.fake.script = [("json", 200, completion("ok"))]
    opts = {"temperature": 0.6, "top_p": 0.8, "top_k": 20, "min_p": 0.05, "presence_penalty": 0.05, "seed": 1001,
            "num_predict": 65536, "num_ctx": 98304, "num_batch": 256, "repeat_penalty": 1.05, "draft_num_predict": 4}
    code, out = muse_env.post(chat_body(options=opts, think=False))
    sent = muse_env.fake.requests[0]
    for k in ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "repeat_penalty", "frequency_penalty"):
        assert k not in sent
    assert sent["seed"] == 1001 and sent["max_tokens"] == 65536 and sent["stream"] is False
    assert out["sampling_stripped"] == {"temperature": 0.6, "top_p": 0.8, "top_k": 20, "min_p": 0.05,
                                        "presence_penalty": 0.05}
    assert out["ignored_options"] == ["draft_num_predict", "num_batch", "num_ctx", "repeat_penalty", "think"]


def test_zero_valued_sampling_fields_are_still_stripped_and_recorded(muse_env):
    muse_env.fake.script = [("json", 200, completion("ok"))]
    code, out = muse_env.post(chat_body(options={"temperature": 0, "top_k": 0, "presence_penalty": 0.0, "seed": 0}))
    sent = muse_env.fake.requests[0]
    assert "temperature" not in sent and "top_k" not in sent and "presence_penalty" not in sent
    assert sent["seed"] == 0
    assert out["sampling_stripped"] == {"temperature": 0, "top_k": 0, "presence_penalty": 0.0}


def test_no_options_means_nothing_stripped(muse_env):
    muse_env.fake.script = [("json", 200, completion("ok"))]
    b = chat_body()
    del b["options"]
    code, out = muse_env.post(b)
    assert out["sampling_stripped"] == {} and "max_tokens" not in muse_env.fake.requests[0]


# ------------------------------------------------------------------ system injection

SYSTEM_TEXT = "Reasoning strength: xhigh\n═══ ■ CHARTER \r\n  trailing spaces  \n\n"


def _own_system_file(muse_env, tmp_path):
    p = tmp_path / "sys.txt"
    p.write_bytes(SYSTEM_TEXT.encode("utf-8"))
    muse_env.cfg["system_file"] = str(p)
    muse_env.cfg["system_sha256"] = prov.sha256_bytes(SYSTEM_TEXT.encode("utf-8"))
    muse_env.write_engine()
    return p


def test_system_injected_byte_for_byte_when_absent(muse_env, tmp_path):
    p = _own_system_file(muse_env, tmp_path)
    text, sha = prov.read_system(p)
    assert text == SYSTEM_TEXT and "\r\n" in text            # no newline translation on read
    assert sha == prov.sha256_bytes(SYSTEM_TEXT.encode("utf-8"))
    muse_env.fake.script = [("json", 200, completion("ok"))]
    code, out = muse_env.post(chat_body(messages=[{"role": "user", "content": "u"}]))
    m = muse_env.fake.requests[0]["messages"]
    assert [x["role"] for x in m] == ["system", "user"]
    assert m[0]["content"] == SYSTEM_TEXT and m[0]["content"].encode("utf-8") == SYSTEM_TEXT.encode("utf-8")
    assert out["system_injected"] is True


def test_requests_own_system_message_passes_through_unchanged(muse_env, tmp_path):
    _own_system_file(muse_env, tmp_path)
    muse_env.fake.script = [("json", 200, completion("ok"))]
    own = "  my own system \n"
    code, out = muse_env.post(chat_body(messages=[{"role": "system", "content": own}, {"role": "user", "content": "u"}]))
    m = muse_env.fake.requests[0]["messages"]
    assert [x["role"] for x in m] == ["system", "user"] and m[0]["content"] == own
    assert out["system_injected"] is False


# ------------------------------------------------------------------ reasoning

def test_reasoning_content_maps_to_thinking_and_is_not_flagged(muse_env):
    muse_env.fake.script = [("json", 200, completion("Final answer.", reasoning="step by step"))]
    code, out = muse_env.post(chat_body())
    assert out["message"]["thinking"] == "step by step" and out["message"]["content"] == "Final answer."
    assert out["reasoning_in_content"] is False


@pytest.mark.parametrize("content", ["<think>hmm</think>answer", "<|channel|>analysis<|message|>hmm<|end|>",
                                     "answer<|start|>assistant", "[THINK]x[/THINK]"])
def test_reasoning_markers_in_content_are_flagged(muse_env, content):
    muse_env.fake.script = [("json", 200, completion(content))]
    code, out = muse_env.post(chat_body())
    assert code == 200 and out["reasoning_in_content"] is True


def test_no_thinking_key_when_the_server_returns_none(muse_env):
    muse_env.fake.script = [("json", 200, completion("plain"))]
    code, out = muse_env.post(chat_body())
    assert "thinking" not in out["message"]


# ------------------------------------------------------------------ what the provider never sends

def test_cache_prompt_is_never_sent_and_the_request_has_exactly_the_adapters_keys(muse_env):
    muse_env.fake.script = [("json", 200, completion("ok"))]
    muse_env.post(chat_body(tools=[{"type": "function", "function": {"name": "f"}}],
                            options={"num_predict": 8, "seed": 3, "temperature": 0.6}))
    sent = muse_env.fake.requests[0]
    assert "cache_prompt" not in sent
    assert list(sent) == ["model", "messages", "stream", "tools", "max_tokens", "seed"]
