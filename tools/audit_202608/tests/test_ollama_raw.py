"""Brief H: depth_provider "ollama_raw" - the reader, the renderer (golden prompt) and the provider (stub HTTP server).

No GPU, no Ollama: the provider test talks to a stub server on an ephemeral local port."""
import hashlib
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
REPO = AUDIT_DIR.parents[1]
for p in (str(AUDIT_DIR), str(REPO), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ollama_raw as raw  # noqa: E402
import qwen_tool_reader as rd  # noqa: E402
import llm_provider as prov  # noqa: E402
import rs2_data  # noqa: E402

GOLDEN = TESTS_DIR / "fixture_data" / "ollama_raw_golden_prompt.txt"

SCENARIO_ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "probability": {"type": "number"},
        "explicit_growth": {"type": "array", "items": {"type": "number"}},
        "revenue_growth": {"type": "array", "items": {"type": "number"}},
        "earnings_margin": {"type": "array", "items": {"type": "number"}},
    },
    "required": ["name", "probability", "explicit_growth"],
}
TOOLS = [
    {"type": "function", "function": {
        "name": "run_financial_model", "description": "Run the DCF desk.",
        "parameters": {"type": "object", "properties": {
            "ticker": {"type": "string"},
            "scenarios": {"type": "array", "items": SCENARIO_ITEM},
            "years": {"type": "integer"},
            "flag": {"type": "boolean"},
            "ratio": {"type": "number"},
            "meta": {"type": "object"},
        }, "required": ["ticker", "scenarios"]}}},
    {"type": "function", "function": {
        "name": "web_search", "description": "Search.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]
SCENARIOS = [
    {"name": "bear", "probability": 0.25, "explicit_growth": [0.05, 0.04, 0.03], "revenue_growth": [0.04, 0.03],
     "earnings_margin": [0.1, 0.09]},
    {"name": "base", "probability": 0.5, "explicit_growth": [0.1, 0.09, 0.08], "revenue_growth": [0.08, 0.07],
     "earnings_margin": [0.15, 0.16]},
    {"name": "bull", "probability": 0.25, "explicit_growth": [0.2, 0.18, 0.15], "revenue_growth": [0.15, 0.14],
     "earnings_margin": [0.2, 0.22]},
]


def call_xml(name, params):
    s = f"<tool_call>\n<function={name}>\n"
    for k, v in params:
        s += f"<parameter={k}>\n{v}\n</parameter>\n"
    return s + "</function>\n</tool_call>"


# ---------------------------------------------------------------- the reader

def test_nested_arrays_inside_an_array_of_objects_round_trip_exactly():
    text = "thinking here\n</think>\n\n" + call_xml("run_financial_model", [
        ("ticker", "XYZ"), ("scenarios", json.dumps(SCENARIOS, indent=2)), ("years", "10")])
    r = rd.read_completion(text, TOOLS)
    assert r["thinking"] == "thinking here" and r["content"] == ""
    (c,) = r["tool_calls"]
    assert c == {"function": {"name": "run_financial_model",
                              "arguments": {"ticker": "XYZ", "scenarios": SCENARIOS, "years": 10}}}
    assert all("revenue_growth" in s and "earnings_margin" in s for s in c["function"]["arguments"]["scenarios"])


def test_two_tool_calls_in_one_turn_and_content_before_them():
    text = ("t\n</think>\n\nLet me look.\n\n" + call_xml("web_search", [("query", "a")]) + "\n"
            + call_xml("web_search", [("query", "b")]))
    r = rd.read_completion(text, TOOLS)
    assert r["content"] == "Let me look."
    assert [c["function"]["arguments"] for c in r["tool_calls"]] == [{"query": "a"}, {"query": "b"}]


def test_a_string_parameter_with_newlines_and_angle_brackets_is_kept_verbatim():
    value = "line one\n\nif a < b and c > d:\n  <b>bold</b> & <function=x> text\n  "
    text = "</think>\n" + call_xml("web_search", [("query", value)])
    (c,) = rd.read_completion(text, TOOLS)["tool_calls"]
    assert c["function"]["arguments"]["query"] == value


@pytest.mark.parametrize("tail", [
    "<tool_call>\n<function=web_search>\n<parameter=query>\nabc",                                   # truncated mid-value
    "<tool_call>\n<function=web_search>\n<parameter=query>\nabc\n</parameter>\n</function>",         # no </tool_call>
    "<tool_call>\n<function=web_search>\n<parameter=query>\nabc\n</parameter>\n</tool_call>",        # no </function>
    "<tool_call>\n<function=web_search>\nstray text\n</function>\n</tool_call>",                     # text where a parameter goes
    "<tool_call>\n{\"name\": \"web_search\"}\n</tool_call>",                                        # not the XML form
    "<function=web_search>\n<parameter=query>\nabc\n</parameter>\n</function>",                      # no <tool_call> wrapper
])
def test_malformed_markup_makes_no_call_and_stays_in_content(tail):
    r = rd.read_completion("t\n</think>\n\nbefore " + tail, TOOLS)
    assert r["tool_calls"] == [] and r["content"] == "before " + tail.strip()


def test_one_bad_call_voids_a_well_formed_sibling_in_the_same_turn():
    good = call_xml("web_search", [("query", "a")])
    r = rd.read_completion("</think>\n" + good + "\n<tool_call>\n<function=web_search>\n<parameter=query>\nz", TOOLS)
    assert r["tool_calls"] == [] and good in r["content"]


def test_a_turn_with_only_thinking_is_all_thinking():
    r = rd.read_completion("  still deliberating, cut off by num_predict ", TOOLS)
    assert r == {"content": "", "thinking": "still deliberating, cut off by num_predict", "tool_calls": []}


def test_thinking_off_the_whole_completion_is_content():
    r = rd.read_completion("The answer.\n\n" + call_xml("web_search", [("query", "q")]), TOOLS, thinking_open=False)
    assert r["thinking"] == "" and r["content"] == "The answer." and len(r["tool_calls"]) == 1


def test_numbers_above_int64_are_not_clamped():
    big = 10 ** 30 + 7
    text = "</think>\n" + call_xml("run_financial_model", [("ticker", "X"), ("years", str(big)), ("ratio", str(big)),
                                                           ("scenarios", "[]")])
    a = rd.read_completion(text, TOOLS)["tool_calls"][0]["function"]["arguments"]
    assert a["years"] == big and isinstance(a["years"], int) and a["ratio"] == big and a["scenarios"] == []
    assert rd.convert_value("\n-9223372036854775809\n", {"type": "integer"}) == -9223372036854775809


def test_value_conversion_by_top_level_schema_type():
    c = rd.convert_value
    assert c("\n3.50\n", {"type": "number"}) == 3.5 and c("2", {"type": "number"}) == 2
    assert c("\ntrue\n", {"type": "boolean"}) is True and c("False", {"type": "boolean"}) is False
    assert c("maybe", {"type": "boolean"}) == "maybe"
    assert c("\n{\"a\": [1, {\"b\": []}]}\n", {"type": "object"}) == {"a": [1, {"b": []}]}
    assert c("\n[1, 2\n", {"type": "array"}) == "[1, 2"                 # unparseable stays the raw string
    assert c("{\"a\": 1}", {"type": "array"}) == "{\"a\": 1}"            # parses, but not an array
    assert c("not a number", {"type": "integer"}) == "not a number"
    assert c("\n\n007\n\n", {"type": "string"}) == "\n007\n"             # one newline each side only
    assert c("12", None) == "12" and c("12", {}) == "12"                  # undeclared parameter: string
    assert c("[1]", {"type": ["null", "array"]}) == [1]
    assert c("nan", {"type": "number"}) == "nan"


def test_zero_and_false_and_empty_values_survive():
    text = "</think>\n" + call_xml("run_financial_model", [("ticker", "X"), ("years", "0"), ("flag", "false"),
                                                           ("ratio", "0.0"), ("scenarios", "[]")])
    a = rd.read_completion(text, TOOLS)["tool_calls"][0]["function"]["arguments"]
    assert a["years"] == 0 and a["flag"] is False and a["ratio"] == 0.0 and a["scenarios"] == []


# ---------------------------------------------------------------- the renderer

FIXTURE_MESSAGES = [
    {"role": "system", "content": "You are the underwriter."},
    {"role": "user", "content": "Value XYZ."},
    {"role": "assistant", "content": "Searching.", "thinking": "I should search first.",
     "tool_calls": [{"function": {"name": "web_search", "arguments": {"query": "XYZ 10-K <risk> & more"}}},
                    {"function": {"name": "run_financial_model",
                                  "arguments": {"ticker": "XYZ", "scenarios": SCENARIOS[:1], "years": 5, "flag": False}}}]},
    {"role": "tool", "content": "result one"},
    {"role": "tool", "content": "result two"},
    {"role": "user", "content": "Now the memorandum."},
]


def test_the_rendered_prompt_matches_the_golden_file():
    got = raw.render_prompt(raw.template_messages(FIXTURE_MESSAGES), TOOLS, "high")
    if not GOLDEN.exists():                      # first run writes it; the file is then reviewed and committed
        GOLDEN.write_bytes(got.encode("utf-8"))
    assert got == GOLDEN.read_bytes().decode("utf-8")


def test_the_tool_block_carries_the_full_nested_schema():
    got = raw.render_prompt(raw.template_messages(FIXTURE_MESSAGES), TOOLS, "high")
    line = next(l for l in got.splitlines() if l.startswith('{"type": "function", "function": {"name": "run_financial_model"'))
    assert json.loads(line) == TOOLS[0]
    items = json.loads(line)["function"]["parameters"]["properties"]["scenarios"]["items"]
    assert items["properties"]["revenue_growth"] == {"type": "array", "items": {"type": "number"}}
    assert "<|im_start|>assistant\n<think>\n" in got and "tojson" not in got


def test_tojson_is_json_dumps_not_the_html_escaping_default():
    tools = [{"type": "function", "function": {"name": "t", "description": "a < b & é", "parameters": {"type": "object"}}}]
    got = raw.render_prompt([{"role": "user", "content": "x"}], tools, True)
    assert 'a < b & é' in got and "\\u003c" not in got


def test_the_think_flags_change_only_the_expected_suffix_and_effort_line():
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    on_high = raw.render_prompt(msgs, None, "high")
    on_true = raw.render_prompt(msgs, None, True)
    on_none = raw.render_prompt(msgs, None, None)
    off = raw.render_prompt(msgs, None, False)
    low = raw.render_prompt(msgs, None, "low")
    assert on_high == on_true == on_none                     # "high" is the template's xhigh, its default
    assert on_high.endswith("<|im_start|>assistant\n<think>\n")
    assert off.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert off.replace("<think>\n\n</think>\n\n", "<think>\n") .endswith(on_high[-len("<|im_start|>assistant\n<think>\n"):])
    assert "Reasoning effort is set to xhigh" in on_high and "Reasoning effort" not in off
    assert "Reasoning effort is set to low" in low
    body = lambda s: s.split("<|im_end|>\n<|im_start|>user", 1)[1]    # noqa: E731
    assert body(on_high) == body(off).replace("<think>\n\n</think>\n\n", "<think>\n")
    assert raw.think_kwargs("high") == {"enable_thinking": True, "reasoning_effort": "high"}
    assert raw.think_kwargs(False) == {"enable_thinking": False} and raw.think_kwargs(None) == {}
    with pytest.raises(raw.RawProviderError):
        raw.think_kwargs("extreme")


def test_a_changed_template_is_refused(monkeypatch, tmp_path):
    p = tmp_path / "t.jinja"
    p.write_bytes(raw.TEMPLATE_PATH.read_bytes() + b" ")
    monkeypatch.setattr(raw, "TEMPLATE_PATH", p)
    with pytest.raises(raw.RawProviderError) as e:
        raw.render_prompt([{"role": "user", "content": "x"}])
    assert e.value.cause == "template_changed"


def test_the_committed_template_is_the_pinned_bytes():
    assert hashlib.sha256(raw.TEMPLATE_PATH.read_bytes()).hexdigest() == raw.TEMPLATE_SHA256


def test_system_is_added_only_when_the_harness_sent_none():
    m = raw.template_messages([{"role": "user", "content": "u"}], "SYS")
    assert m[0] == {"role": "system", "content": "SYS"} and len(m) == 2
    assert raw.template_messages(FIXTURE_MESSAGES, "SYS")[0]["content"] == "You are the underwriter."


def test_the_models_system_text_is_read_from_its_manifest_blob(monkeypatch, tmp_path):
    base = tmp_path / "models"
    man = base / "manifests" / "registry.ollama.ai" / "library" / "tagx" / "v1"
    man.parent.mkdir(parents=True)
    (base / "blobs").mkdir()
    (base / "blobs" / "sha256-abc").write_bytes("SYSTEM TEXT é".encode())
    man.write_text(json.dumps({"layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:no"},
                                          {"mediaType": "application/vnd.ollama.image.system", "digest": "sha256:abc"}]}))
    monkeypatch.setenv("OLLAMA_MODELS", str(base))
    assert raw.ollama_system_text("tagx:v1") == "SYSTEM TEXT é"
    with pytest.raises(raw.RawProviderError) as e:
        raw.ollama_system_text("missing:v1")
    assert e.value.cause == "no_system"


# ---------------------------------------------------------------- the provider

class _Stub(BaseHTTPRequestHandler):
    seen = []
    reply = {}

    def log_message(self, *a):
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        _Stub.seen.append(("GET", self.path, None, dict(self.headers)))
        self._send({"version": "0.40.3"})

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        _Stub.seen.append(("POST", self.path, self.rfile.read(n), dict(self.headers)))
        self._send(_Stub.reply)


@pytest.fixture
def stub(monkeypatch):
    _Stub.seen = []
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/api/chat"
    monkeypatch.setattr(prov, "OLLAMA_URL", url)
    monkeypatch.setattr(raw, "_VERSIONS", {})
    monkeypatch.setitem(rs2_data.CONFIG, "depth_provider", "ollama_raw")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # the suite's autouse fixture blocks urlopen
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: opener.open(req, timeout=timeout))
    yield _Stub
    srv.shutdown()
    srv.server_close()


def test_ollama_raw_posts_generate_raw_without_tools_or_think_and_returns_the_ollama_shape(stub):
    completion = ("reasoning\n</think>\n\nSearching.\n\n" + call_xml("run_financial_model", [
        ("ticker", "XYZ"), ("scenarios", json.dumps(SCENARIOS)), ("years", "10")]))
    stub.reply = {"model": "m", "created_at": "t", "response": completion, "done": True, "done_reason": "stop",
                  "context": [1, 2], "total_duration": 5, "load_duration": 1, "prompt_eval_count": 100,
                  "prompt_eval_duration": 2, "eval_count": 50, "eval_duration": 3}
    opts = {"num_ctx": 98304, "num_predict": 32768, "seed": 7, "temperature": 0.6, "draft_num_predict": 4}
    body = {"model": "m", "stream": False, "think": "high", "messages": FIXTURE_MESSAGES, "tools": TOOLS, "options": opts}
    out = prov.chat(body, 30)
    posts = [s for s in stub.seen if s[0] == "POST"]
    assert len(posts) == 1 and posts[0][1] == "/api/generate"
    sent = json.loads(posts[0][2])
    assert sent["raw"] is True and sent["stream"] is False and sent["model"] == "m" and sent["options"] == opts
    assert "tools" not in sent and "think" not in sent and "messages" not in sent and "keep_alive" not in sent
    assert sent["prompt"] == raw.render_prompt(raw.template_messages(FIXTURE_MESSAGES), TOOLS, "high")
    assert out["message"] == {"role": "assistant", "content": "Searching.", "thinking": "reasoning",
                              "tool_calls": [{"function": {"name": "run_financial_model", "arguments": {
                                  "ticker": "XYZ", "scenarios": SCENARIOS, "years": 10}}}]}
    assert out["done"] is True and out["done_reason"] == "stop"
    assert (out["eval_count"], out["prompt_eval_count"], out["eval_duration"], out["load_duration"]) == (50, 100, 3, 1)
    assert out["provider"] == "ollama_raw" and out["template_sha256"] == raw.TEMPLATE_SHA256
    assert out["ollama_version"] == "0.40.3" and "response" not in out and "context" not in out


def test_ollama_raw_passes_keep_alive_and_think_off_changes_only_the_prompt(stub):
    stub.reply = {"response": "plain answer", "done": True, "done_reason": "length"}
    body = {"model": "m", "stream": False, "think": False, "keep_alive": "30m",
            "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], "options": {"seed": 1}}
    out = prov.chat(body, 30)
    sent = json.loads([s for s in stub.seen if s[0] == "POST"][0][2])
    assert sent["keep_alive"] == "30m" and sent["prompt"].endswith("<think>\n\n</think>\n\n")
    assert out["message"] == {"role": "assistant", "content": "plain answer"} and out["done_reason"] == "length"


def test_ollama_raw_refusals_are_named_http_500s(stub, monkeypatch, tmp_path):
    import urllib.error
    monkeypatch.setattr(raw, "TEMPLATE_PATH", tmp_path / "missing.jinja")
    body = {"model": "m", "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]}
    with pytest.raises(FileNotFoundError):                  # no template file at all is an environment error, unmasked
        prov.chat(body, 5)
    p = tmp_path / "t.jinja"
    p.write_text("changed")
    monkeypatch.setattr(raw, "TEMPLATE_PATH", p)
    with pytest.raises(urllib.error.HTTPError) as e:
        prov.chat(body, 5)
    assert e.value.code == 500 and e.value.cause == "template_changed"
    assert not [s for s in stub.seen if s[0] == "POST"]


def test_provider_names_and_serving_block():
    assert prov.PROVIDERS == ("ollama", "llamacpp", "ollama_raw")
    sb = prov.serving_block("ollama_raw", "no-such-model")
    assert sb["provider"] == "ollama_raw" and sb["template_sha256"] == raw.TEMPLATE_SHA256
    assert prov.serving_block("ollama", "no-such-model")["provider"] == "ollama"


def test_ollama_raw_names_a_context_overflow_instead_of_a_silent_front_truncation(stub):
    import urllib.error
    body = {"model": "m", "stream": False, "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
            "options": {"num_ctx": 98304, "num_predict": 32768, "seed": 1}}
    stub.reply = {"response": "x", "done": True, "done_reason": "stop", "prompt_eval_count": 98304 - 32768 + 1}
    with pytest.raises(urllib.error.HTTPError) as e:
        prov.chat(body, 30)
    assert e.value.code == 500 and e.value.cause == "context_overflow"
    stub.reply = dict(stub.reply, prompt_eval_count=98304 - 32768)                       # exactly full is inside
    assert prov.chat(body, 30)["done_reason"] == "stop"
    assert raw.context_overflow_guard({"prompt_eval_count": 90000}, {"num_ctx": 98304}) is None          # no output limit: only the prompt is counted
    assert raw.context_overflow_guard({}, {"num_ctx": 10, "num_predict": 99}) is None                 # no count in the reply: nothing to check
    with pytest.raises(raw.RawProviderError) as e2:
        raw.context_overflow_guard({"prompt_eval_count": 0}, {"num_ctx": 100, "num_predict": 101})     # 0 tokens is a value: 0 + 101 > 100
    assert e2.value.cause == "context_overflow"
