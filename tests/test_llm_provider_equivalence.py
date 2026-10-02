"""Muse integration, M8 item 1: the provider's translation equals the pinned Phase 7 adapter's.

tests/fixtures/ollama2llamacpp.py is a byte copy of SP/p7_serving/ollama2llamacpp.py (sha256 2d57497f...), loaded here and
nowhere else. For a generated table of Ollama bodies the provider's OpenAI payload must equal the adapter's `to_openai`
output (equal keys in equal order, equal values); for a table of llama-server replies the provider's Ollama dict must equal
the adapter's `to_ollama` output (except `engine`); `classify_http_error` must give the same cause for every code and body
P7's step-0 tests used. The ported functions are also compared as source text, so "line for line" is checked, not claimed."""
import copy
import hashlib
import importlib.util
import inspect
import itertools
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llamacpp_fakes import completion, tool_call, timings, overflow_body  # noqa: E402,F401
import llm_provider as prov  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ollama2llamacpp.py"
ADAPTER_SHA256 = "2d57497f56440378ccfdafb27eb2a09342b83686b19515a3306f8fa60785ceca"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("_p7_adapter_fixture", FIXTURE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ad = _load_adapter()


def test_the_fixture_is_the_pinned_adapter_byte_for_byte():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == ADAPTER_SHA256


def test_the_fixture_is_imported_only_by_tests():
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(["git", "grep", "--untracked", "-l", "-E", r"^\s*(import|from)\s+ollama2llamacpp",
                          "--", "*.py"], cwd=root, capture_output=True, text=True).stdout.split()
    offenders = [p for p in out if not (p.startswith("tests/") or "/tests/" in p)]
    assert offenders == [], offenders


# ------------------------------------------------------------------ constants and the ported source

@pytest.mark.parametrize("name", ["STRIPPED_SAMPLING_FIELDS", "KEPT_OPTIONS", "FINISH_TO_DONE", "REASONING_MARKERS"])
def test_constants_equal_the_adapters(name):
    assert getattr(prov, name) == getattr(ad, name)


@pytest.mark.parametrize("fn", ["to_openai", "to_ollama", "_tool_calls", "has_reasoning_markers", "classify_http_error",
                                "call_upstream", "read_system", "sha256_bytes"])
def test_ported_function_source_is_the_adapters_line_for_line(fn):
    mine = inspect.getsource(getattr(prov, fn))
    # the class is renamed; the article in one docstring follows ("an AdapterError" -> "a ProviderError")
    theirs = inspect.getsource(getattr(ad, fn)).replace("an AdapterError", "a ProviderError").replace("AdapterError", "ProviderError")
    assert mine == theirs


# ------------------------------------------------------------------ requests

SAMPLING = {"temperature": 0.6, "top_p": 0.8, "top_k": 20, "min_p": 0.05, "presence_penalty": 0.05}
OTHER = {"num_ctx": 98304, "num_batch": 256, "repeat_penalty": 1.05, "draft_num_predict": 4, "frequency_penalty": 0.1}
OPTIONS = [
    None,
    {},
    {"num_predict": 64, "seed": 7},
    {"num_predict": 0, "seed": 0},                                   # 0 is a value
    {**SAMPLING},
    {**OTHER},
    {**SAMPLING, **OTHER, "num_predict": 65536, "seed": 1001},
    {"temperature": 0, "top_k": 0, "presence_penalty": 0.0, "min_p": 0.0, "seed": 0},
    {"num_predict": 128, "something_new": True},
]
TOOLS = [{"type": "function", "function": {"name": "search_web", "parameters": {"type": "object"}}}]
THINKS = [("absent", None), ("false", False), ("high", "high"), ("none-string", "none")]

SYSTEM_MSG = {"role": "system", "content": "own system \r\n text "}
USER = {"role": "user", "content": "go"}
MESSAGE_SETS = {
    "user_only": [USER],
    "system_then_user": [SYSTEM_MSG, USER],
    "user_then_system": [USER, SYSTEM_MSG],
    "empty": [],
    "none_content": [{"role": "user", "content": None}, {"role": "user"}],
    "unknown_role": [{"role": "developer", "content": "d"}, {"content": "no role"}],
    "calls_dict_args_no_ids_results_in_order": [
        USER,
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_web", "arguments": {"query": "a"}}},
                                                           {"function": {"name": "fetch_page", "arguments": {"url": "b"}}}]},
        {"role": "tool", "content": "result A"}, {"role": "tool", "content": "result B"}],
    "calls_string_args_with_ids_results_by_id": [
        USER,
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "explicit_1", "function": {"name": "search_web", "arguments": "{\"query\": \"c\"}"}},
            {"id": "explicit_2", "function": {"name": "search_web", "arguments": {"query": "d"}}}]},
        {"role": "tool", "content": "result D", "tool_call_id": "explicit_2"},
        {"role": "tool", "content": "result C", "tool_call_id": "explicit_1"}],
    "results_by_tool_name_out_of_order": [
        USER,
        {"role": "assistant", "content": "", "tool_calls": [{"id": "id_s", "function": {"name": "search_web", "arguments": {}}},
                                                           {"id": "id_f", "function": {"name": "fetch_page", "arguments": {}}}]},
        {"role": "tool", "content": "page", "tool_name": "fetch_page"},
        {"role": "tool", "content": "hits", "name": "search_web"}],
    "orphan_results": [USER, {"role": "tool", "content": "stray"}, {"role": "tool", "content": "stray 2", "tool_name": "x"}],
    "more_results_than_calls": [
        USER, {"role": "assistant", "content": "", "tool_calls": [tool_call("search_web", {"query": "a"}, "k1")]},
        {"role": "tool", "content": "one"}, {"role": "tool", "content": "two"}],
    "tool_call_id_none_and_function_missing": [
        USER, {"role": "assistant", "content": "x", "tool_calls": [{"id": "z"}, {"function": {}}]},
        {"role": "tool", "content": "r", "tool_call_id": None}],
    "assistant_thinking_is_not_forwarded": [
        USER, {"role": "assistant", "content": "answer", "thinking": "private reasoning"}, {"role": "user", "content": "next"}],
    "calls_then_second_round": [
        USER,
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_web", "arguments": {"q": 1}}}]},
        {"role": "tool", "content": "r1"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "run_financial_model", "arguments": "{}"}}]},
        {"role": "tool", "content": "r2", "tool_name": "run_financial_model"}],
}


def _bodies():
    for (mname, msgs), opts, (tname, tools), (kname, think), has_model in itertools.product(
            MESSAGE_SETS.items(), OPTIONS, [("no_tools", None), ("tools", TOOLS), ("empty_tools", [])],
            THINKS, (True, False)):
        body = {"stream": False, "messages": copy.deepcopy(msgs)}
        if has_model:
            body["model"] = "muse-tag"
        if think is not None or kname == "false":
            body["think"] = think
        if tools is not None:
            body["tools"] = copy.deepcopy(tools)
        if opts is not None:
            body["options"] = copy.deepcopy(opts)
        yield f"{mname}|{opts and sorted(opts)}|{tname}|think={kname}|model={has_model}", body


BODIES = list(_bodies())


def test_the_table_covers_the_brief():
    assert len(BODIES) > 1500
    kinds = {n.split("|")[0] for n, _ in BODIES}
    assert {"calls_dict_args_no_ids_results_in_order", "calls_string_args_with_ids_results_by_id",
            "results_by_tool_name_out_of_order", "orphan_results", "system_then_user", "user_only"} <= kinds


@pytest.mark.parametrize("system", [None, "SYSTEM TEXT\r\nwith ═ chars \n"], ids=["no_system_text", "system_text"])
def test_to_openai_equals_the_adapters_for_every_body(system):
    for name, body in BODIES:
        mine_req, mine_info = prov.to_openai(copy.deepcopy(body), system)
        theirs_req, theirs_info = ad.to_openai(copy.deepcopy(body), system)
        # equal keys in equal order and equal values: the serialisations are identical strings
        assert json.dumps(mine_req) == json.dumps(theirs_req), name
        assert mine_info == theirs_info, name
        assert list(mine_info) == list(theirs_info), name


@pytest.mark.parametrize("bad", [None, [], "x", 5, {"messages": "nope"}, {"messages": None}, {"stream": True, "messages": []},
                                 {"messages": [1]}, {"messages": ["a"]}, {"messages": [USER, None]}])
def test_to_openai_refuses_a_malformed_body_with_the_adapters_cause_and_detail(bad):
    with pytest.raises(ad.AdapterError) as a:
        ad.to_openai(copy.deepcopy(bad))
    with pytest.raises(prov.ProviderError) as p:
        prov.to_openai(copy.deepcopy(bad))
    assert (p.value.cause, p.value.detail, str(p.value)) == (a.value.cause, a.value.detail, str(a.value))


def test_sampling_is_never_forwarded_and_seed_and_num_predict_are_kept():
    body = {"model": "m", "messages": [USER], "think": "high",
            "options": {**SAMPLING, **OTHER, "seed": 1001, "num_predict": 65536}}
    req, info = prov.to_openai(body)
    for k in ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "repeat_penalty", "frequency_penalty",
              "num_ctx", "num_batch", "draft_num_predict", "think", "cache_prompt"):
        assert k not in req
    assert req["seed"] == 1001 and req["max_tokens"] == 65536 and req["stream"] is False
    assert info["sampling_stripped"] == SAMPLING
    assert info["ignored_options"] == ["draft_num_predict", "frequency_penalty", "num_batch", "num_ctx", "repeat_penalty", "think"]


def test_an_assistant_messages_thinking_is_never_sent():
    req, _ = prov.to_openai({"messages": [USER, {"role": "assistant", "content": "a", "thinking": "T"},
                                          {"role": "user", "content": "b"}]})
    assert "T" not in json.dumps(req) and all("thinking" not in m for m in req["messages"])


# ------------------------------------------------------------------ responses

CALLS = [tool_call("search_web", '{"query": "q1"}', "call_a"), tool_call("fetch_page", '{"url": "u"}', "call_b")]


def _responses():
    t_ok = timings()
    t_zero = {"prompt_ms": 0.0, "predicted_ms": 0.0, "predicted_n": 0, "prompt_n": 0}
    yield "text", completion("the memo")
    for fin in ("stop", "length", "tool_calls", None, "content_filter", "weird"):
        yield f"finish={fin}", completion("x", finish=fin, tool_calls=CALLS if fin == "tool_calls" else None)
    yield "reasoning_present", completion("Final.", reasoning="step by step")
    yield "reasoning_empty_string", completion("Final.", reasoning="")
    yield "reasoning_absent", completion("Final.")
    for mk in ("<think>hmm</think>answer", "<|channel|>analysis<|message|>hmm<|end|>", "answer<|start|>assistant",
               "[THINK]x[/THINK]", "<|return|>", "<|constrain|>"):
        yield f"marker={mk[:12]}", completion(mk)
    yield "marker_in_reasoning_only", completion("clean", reasoning="<think>fine here</think>")
    args = {"dict": {"price": 1.5}, "empty_string": "", "blank": "   ", "none": None, "valid_string": '{"a": 1}',
            "invalid_string": '{"a": ', "list_string": "[1, 2]", "list": [1, 2], "int": 7, "string_number": "5", "false": False}
    for k, a in args.items():
        yield f"args={k}", completion("", finish="tool_calls", tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "f", "arguments": a}}])
    yield "args_missing", completion("", finish="tool_calls", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "f"}}])
    yield "call_without_id_and_without_function", completion("", finish="tool_calls", tool_calls=[
        {"type": "function", "function": {"name": "f", "arguments": "{}"}}, {"id": "", "function": None}, {}])
    yield "several_calls", completion("", finish="tool_calls", tool_calls=CALLS + [
        {"function": {"name": "run_financial_model", "arguments": {"price": 1.5}}}])
    yield "tool_calls_with_finish_stop", completion("t", finish="stop", tool_calls=CALLS)
    yield "timings_missing", completion("x", tim=None)
    yield "timings_zero", completion("x", tim=t_zero)
    yield "timings_ok", completion("x", tim=t_ok)
    yield "timings_no_draft", completion("x", tim={"prompt_ms": 10.0, "predicted_ms": 20.0, "predicted_n": 3})
    yield "timings_empty_dict", completion("x", tim={})
    yield "usage_missing", {"choices": [{"finish_reason": "stop", "message": {"content": "x"}}]}
    yield "content_none", {"choices": [{"finish_reason": "stop", "message": {"content": None}}], "usage": {}}
    yield "message_extra_keys", {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "x", "refusal": None}}]}
    for bad in ({}, {"choices": []}, {"choices": [{"finish_reason": "stop"}]}, {"choices": [None]}, [], "str", None,
                {"choices": "x"}, {"choices": [{"finish_reason": "stop", "message": "str"}]}):
        yield f"bad={json.dumps(bad)[:40]}", bad


RESPONSES = list(_responses())


@pytest.mark.parametrize("secs", [0.0, 2.5])
def test_to_ollama_equals_the_adapters_for_every_reply_except_engine(secs):
    for name, resp in RESPONSES:
        info_m, info_t = {"sampling_stripped": {"temperature": 0.6}, "ignored_options": []}, \
            {"sampling_stripped": {"temperature": 0.6}, "ignored_options": []}
        eng_m, eng_t = {"who": "provider"}, {"who": "adapter"}
        try:
            theirs = ad.to_ollama(copy.deepcopy(resp), "tag", secs, eng_t, info_t)
        except ad.AdapterError as e:
            with pytest.raises(prov.ProviderError) as p:
                prov.to_ollama(copy.deepcopy(resp), "tag", secs, eng_m, info_m)
            assert (p.value.cause, p.value.detail) == (e.cause, e.detail), name
            continue
        mine = prov.to_ollama(copy.deepcopy(resp), "tag", secs, eng_m, info_m)
        assert mine["engine"] is eng_m and theirs["engine"] is eng_t
        mine.pop("engine"), theirs.pop("engine")
        assert json.dumps(mine) == json.dumps(theirs), name           # equal keys, equal order, equal values
        assert info_m == info_t, name


def test_the_table_covers_the_brief_for_responses():
    names = {n for n, _ in RESPONSES}
    assert {"finish=stop", "finish=length", "finish=tool_calls", "finish=content_filter", "reasoning_present", "reasoning_absent",
            "args=dict", "args=valid_string", "args=invalid_string", "args=list", "timings_missing"} <= names
    assert sum(1 for n in names if n.startswith("marker=")) >= 5


@pytest.mark.parametrize("text", ["", "plain", "<think>", "x</think>y", "<|channel|>", "a<|message|>b", "[THINK]", "[/THINK]",
                                  "<|end|>", "think", "<THINK>"])
def test_reasoning_marker_detection_equals_the_adapters(text):
    assert prov.has_reasoning_markers(text) == ad.has_reasoning_markers(text)


# ------------------------------------------------------------------ errors

ERROR_CODES = [200, 201, 301, 302, 400, 401, 403, 404, 408, 413, 422, 429, 499, 500, 501, 502, 503, 504]
ERROR_BODIES = [
    json.dumps(overflow_body()).encode(),                                                                  # exceed_context_size_error
    json.dumps({"error": {"code": 400, "message": "request (101000 tokens) exceeds the available context size "
                                                  "(98304 tokens), try increasing it", "type": "exceed_context_size_error",
                          "n_prompt_tokens": 101000, "n_ctx": 98304}}).encode(),
    json.dumps({"error": {"code": 400, "type": "exceed_context_size_error", "message": "m"}}).encode(),   # no counts
    json.dumps({"error": {"code": 400, "message": "the request exceeds the available context size (10 tokens)"}}).encode(),
    json.dumps({"error": {"code": 404, "message": "nope", "type": "invalid_request_error"}}).encode(),
    json.dumps({"error": {"code": 503, "message": "Loading model"}}).encode(),
    json.dumps({"error": "x"}).encode(), json.dumps({"error": None}).encode(), json.dumps({"error": {}}).encode(),
    json.dumps({}).encode(), json.dumps([]).encode(), json.dumps("a string").encode(),
    b"<html>not json</html>", b"", b"zzz", b"\xff\xfe not utf-8", json.dumps({"error": {"message": "x" * 900}}).encode(),
]


def test_classify_http_error_equals_the_adapters_for_every_code_and_body():
    n = 0
    for code in ERROR_CODES:
        for raw in ERROR_BODIES:
            a, p = ad.classify_http_error(code, raw), prov.classify_http_error(code, raw)
            assert (p.cause, p.detail, str(p)) == (a.cause, a.detail, str(a)), (code, raw[:40])
            n += 1
    assert n == len(ERROR_CODES) * len(ERROR_BODIES)


@pytest.mark.parametrize("code,raw,cause", [
    (400, json.dumps(overflow_body()).encode(), "context_overflow"),
    (400, b'{"error": {"message": "the request exceeds the available context size (10 tokens)"}}', "context_overflow"),
    (404, b'{"error": {"message": "nope"}}', "upstream_4xx"), (429, b"{}", "upstream_4xx"),
    (500, b"{}", "upstream_5xx"), (503, b'{"error": {"message": "Loading model"}}', "upstream_5xx"),
    (302, b"{}", "upstream_http_unexpected"),
])
def test_the_causes_p7s_step0_tests_expect(code, raw, cause):
    assert prov.classify_http_error(code, raw).cause == cause
