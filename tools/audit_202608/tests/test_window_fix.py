"""Phase 4 window fix (joint ruling with Fable, 2026-09-26).

GPOR s2 (b): the first turn deliberated for 53,338 tokens, hit the 81,920-token window with no
tool call, and the forced report ran with no tools, so the base IV was computed by hand. Now a
tool turn that hits the window with no tool call, no report and no desk result yet gets one
desk-only recovery turn (think low, the frozen DESK_RECOVERY_PROMPT), one retry if the desk
rejects the call, then the forced report.

UGI s3 / LAMR s1 (b): essays of up to 30,523 characters in sector_multiple_band.metric stayed in
every later prompt and were echoed into every scenario, pushing Bear past the 12,000-character
tool-message cut. Desk string arguments are cut to 300 characters before dispatch, every
assistant tool call reaches the prompt with long strings shortened, the desk echoes 80
characters of the label, and a desk message leads with its summary.
"""
import json
import sys
import urllib.error
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import analyst_tools as at  # noqa: E402
import financial_model_tool as fmt  # noqa: E402

ESSAY = "MRI utilities trailing P/E band, context only. " * 650          # 30,550 characters
DESK_OK = {"scenario_dcfs": [{"name": n, "dcf": {"per_share_iv": iv, "per_share_iv_gordon": iv,
                                                  "terminal_method": "Gordon growth @ 3.8%"}}
                             for n, iv in (("Base", 409.92), ("Bull", 460.0), ("Bear", 299.0))],
           "reverse_dcf": {"implied_growth_next_5y_pct": 3.0},
           "kelly_sizing": {"quarter_kelly_pct": 20.98, "recommendation": "ALLOCATE"},
           "markdown_report": "### FINANCIAL MODELING DESK REPORT"}
MEMO = "SECTION 0. EXECUTIVE VERDICT\n" + "memo line\n" * 700 +"SECTION 12\n```json:underwriting\n{}\n```"


def _fake_ollama(monkeypatch, responses):
    bodies, queue = [], list(responses)

    class _R:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode()

        def read(self, n=-1):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _R(item)

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    return bodies


def _resp(content="", done="stop", prompt=1000, tool_calls=None):
    m = {"content": content, "thinking": "t"}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return {"message": m, "done_reason": done, "prompt_eval_count": prompt,
            "eval_count": 10, "eval_duration": 1_000_000_000}


def _desk_call(**args):
    return [{"function": {"name": "run_financial_model", "arguments": dict({"price": 156.22}, **args)}}]


def _dispatch(monkeypatch, results):
    seen, queue = [], list(results)

    def fake(name, args, snap=None, query_cache=None, url_cache=None, known_urls=None):
        seen.append((name, args))
        return queue.pop(0)

    monkeypatch.setattr(at, "dispatch_tool", fake)
    return seen


def _run(tmp_path, content="pack", **kw):
    return at.chat_with_tools("m", content, tmp_path, ctx=81920, verbose=False,
                              max_search_calls=kw.pop("max_search_calls", 25), **kw)


# ---- the full-thinking retry (operator ruling 2026-09-27) -----------------------------------

def test_the_retry_text_is_the_frozen_ruling():
    assert at.WINDOW_RETRY_PROMPT.startswith(
        "Your previous turn ran out of room deliberating before any tool call, "
        "and that reasoning is lost."
    )
    assert at.WINDOW_RETRY_PROMPT.endswith(
        "listing each change in 'Model revisions' with the evidence that moved it."
    )


def test_gpor_s2_shape_full_thinking_retry_then_normal_continuation(monkeypatch, tmp_path):
    # Test 1: GPOR s2 shape: turn 1 done_reason "length", no tool call -> the next request's last message is
    # WINDOW_RETRY_PROMPT, its think equals the configured level, its options equal the normal opts,
    # and it offers the normal tools; if that turn calls the desk, the run continues normally,
    # meta["window_retry_used"] is True, meta["failure"] is None, and that turn record has window_retry: True.
    bodies = _fake_ollama(monkeypatch, [
        _resp("", done="length", prompt=28581),                 # 53k of thinking, no call
        _resp("", prompt=28700, tool_calls=_desk_call()),      # retry turn calls the desk
        _resp(MEMO, prompt=31000),                              # normal report turn
    ])
    seen = _dispatch(monkeypatch, [DESK_OK])
    report, _, meta = _run(tmp_path, content="pack " * 18000)
    assert len(bodies) == 3
    retry_req = bodies[1]
    assert retry_req["messages"][-1] == {"role": "user", "content": at.WINDOW_RETRY_PROMPT}
    assert retry_req["think"] == "high"
    assert retry_req["options"] == bodies[0]["options"]
    normal_tool_names = [t["function"]["name"] for t in bodies[0]["tools"]]
    assert [t["function"]["name"] for t in retry_req["tools"]] == normal_tool_names
    assert [s[0] for s in seen] == ["run_financial_model"]
    assert report == MEMO
    assert meta["window_retry_used"] is True
    assert meta["failure"] is None
    assert meta["turns"][1].get("window_retry") is True


def test_twice_exhausted_ends_in_failure_and_empty_report(monkeypatch, tmp_path):
    # Test 2: Twice exhausted: the retry turn also ends length with no tool call -> no further request is made,
    # meta["failure"] == "window_exhausted_twice", the report is empty.
    bodies = _fake_ollama(monkeypatch, [
        _resp("", done="length"),
        _resp("", done="length"),
    ])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 2
    assert meta["failure"] == "window_exhausted_twice"
    assert meta["window_retry_used"] is True
    assert report == ""


def test_stub_after_desk_result_forced_report_and_non_deliverable_failure(monkeypatch, tmp_path):
    # Test 3: A stub after a desk result -> the forced report request has think equal to the configured level
    # and the normal num_predict; a non-deliverable forced report sets failure == "report_not_delivered".
    bodies = _fake_ollama(monkeypatch, [
        _resp("", tool_calls=_desk_call()),
        _resp("partial memo", done="length"),
        _resp("not deliverable memorandum without section 12 machine contract"),
    ])
    _dispatch(monkeypatch, [DESK_OK])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 3
    forced_req = bodies[2]
    assert "tools" not in forced_req
    assert forced_req["think"] == "high"
    assert forced_req["options"]["num_predict"] == bodies[0]["options"]["num_predict"]
    assert meta["failure"] == "report_not_delivered"
    assert meta["turns"][-1].get("forced_report") is True

    # And when deliverable: failure is None
    bodies2 = _fake_ollama(monkeypatch, [
        _resp("", tool_calls=_desk_call()),
        _resp("partial memo", done="length"),
        _resp(MEMO),
    ])
    _dispatch(monkeypatch, [DESK_OK])
    report2, _, meta2 = _run(tmp_path)
    assert report2 == MEMO
    assert meta2["failure"] is None


def test_a_sample_with_a_desk_result_goes_to_the_forced_report(monkeypatch, tmp_path):
    # GPOR s1 t10: three desk calls behind it, then a report turn cut at the window; the forced
    # report cited an earlier desk value. No window retry on the pack's defaults.
    bodies = _fake_ollama(monkeypatch, [_resp("", tool_calls=_desk_call()),
                                        _resp("partial memo", done="length"), _resp(MEMO)])
    _dispatch(monkeypatch, [DESK_OK])
    _, _, meta = _run(tmp_path)
    assert len(bodies) == 3 and not any(t.get("window_retry") for t in meta["turns"])
    assert at.WINDOW_RETRY_PROMPT not in json.dumps(bodies)
    assert meta["failure"] is None


def test_a_stub_that_stopped_normally_keeps_the_old_path(monkeypatch, tmp_path):
    # revision 17, brief C8: after a complete desk run (a stub with no desk run gets the desk continuation first)
    bodies = _fake_ollama(monkeypatch, [_resp("", tool_calls=_desk_call()), _resp("", done="stop"), _resp(MEMO)])
    _dispatch(monkeypatch, [DESK_OK])
    _, _, meta = _run(tmp_path)
    assert len(bodies) == 3 and meta["turns"][-1].get("forced_report") is True
    assert not any(t.get("window_retry") for t in meta["turns"])
    assert meta["failure"] is None


def test_every_turn_record_carries_think(monkeypatch, tmp_path):
    # Test 5: Every turn record carries think.
    bodies = _fake_ollama(monkeypatch, [
        _resp("", tool_calls=[{"function": {"name": "search_web", "arguments": {"query": "q"}}}]),
        _resp("", tool_calls=_desk_call()),
        _resp(MEMO),
    ])
    _dispatch(monkeypatch, [{"query": "q", "results": []}, DESK_OK])
    _, _, meta = _run(tmp_path, think="medium")
    assert len(meta["turns"]) == 3
    for t in meta["turns"]:
        assert "think" in t
        assert t["think"] == "medium"
    assert meta["think_configured"] == "medium"


def test_the_recovery_reaches_the_sample_record():
    import consensus_valuation as cv
    st = cv.rescue_status({"turns": [{}, {"desk_recovery": True}, {"window_retry": True}, {"forced_report": True}]})
    assert st["desk_recovery_used"] is True and st["window_retry_used"] is True and st["forced_report"] is True
    assert cv.rescue_status({"turns": [{}]})["window_retry_used"] is False


# ---- the essay ----------------------------------------------------------------------------------

def test_a_30k_metric_is_cut_before_dispatch_and_recorded(monkeypatch, tmp_path):
    _fake_ollama(monkeypatch, [
        _resp("", tool_calls=_desk_call(sector_multiple_band={"low": 12.0, "high": 23.1, "metric": ESSAY})),
        _resp(MEMO)])
    seen = _dispatch(monkeypatch, [DESK_OK])
    _run(tmp_path)
    assert len(seen[0][1]["sector_multiple_band"]["metric"]) == 300
    assert seen[0][1]["sector_multiple_band"]["high"] == 23.1
    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))
    assert snap["calls"][0]["arg_truncated"] == [{"field": "sector_multiple_band.metric",
                                                  "original_length": len(ESSAY)}]


def test_an_essay_in_turn_2_is_a_stub_in_the_prompt_of_turn_3(monkeypatch, tmp_path):
    bodies = _fake_ollama(monkeypatch, [
        _resp("", tool_calls=[{"function": {"name": "search_web", "arguments": {"query": "q"}}}]),
        _resp("", tool_calls=_desk_call(scenarios=[{"name": "Base", "sector_multiple_band": {"metric": ESSAY}}])),
        _resp(MEMO)])
    _dispatch(monkeypatch, [{"query": "q", "results": []}, DESK_OK])
    _run(tmp_path)
    prompt3 = json.dumps(bodies[2]["messages"])
    assert ESSAY[:1000] not in prompt3
    assert f"[{len(ESSAY) - 300} characters omitted]" in prompt3


def test_the_desk_echoes_a_short_label_and_judges_the_full_band():
    band = {"low": 10.0, "mid": 15.0, "high": 20.0, "metric": ESSAY}
    res = fmt.unbundled_dcf(base_cf=1.0, growth_rates=[0.05] * 5, wacc=0.09, terminal_g=0.03,
                            shares_diluted=1.0, fade_years=0, sbc_treatment="deducted_in_cf",
                            sector_multiple_band=band)
    assert res["sector_multiple_band"] == {"low": 10.0, "mid": 15.0, "high": 20.0, "metric": ESSAY[:80]}
    assert "multiple_in_band_gordon" in res
    assert len(band["metric"]) == len(ESSAY)                   # the caller's dict is not touched


# S3 A+B (brief §3.7): _desk_summary reads a scenario's probability from "prob" (the field the
# schema actually carries), not "probability".
def test_a_desk_message_leads_with_its_summary_and_records_a_cut():
    big = dict(DESK_OK, details_padding="x" * 20000)
    args = {"scenarios": [{"name": "Base", "prob": 0.5}, {"name": "Bull", "prob": 0.3},
                          {"name": "Bear", "prob": 0.2}]}
    content, cut = at.tool_message("run_financial_model", args, big)
    assert content.startswith('{"summary": {"scenarios": [{"name": "Base", "probability": 0.5, "per_share_iv": 409.92')
    assert '"name": "Bear", "probability": 0.2, "per_share_iv": 299.0' in content
    assert len(content) == 12000 and cut == {"chars": len(json.dumps({"summary": at._desk_summary(args, big),
                                                                         "markdown_report": big["markdown_report"],
                                                                         "details": {k: v for k, v in big.items() if k != "markdown_report"}})),
                                             "cut_at": 12000}
    assert at.tool_message("search_web", {}, {"query": "q", "results": []}) == ('{"query": "q", "results": []}', None)
    err = {"validation_error": True, "error": "x"}
    assert at.tool_message("run_financial_model", {}, err) == (json.dumps(err), None)


# ---- the report-room rule: page notes only, oldest first ----------------------------------------

def _history_with_pages():
    msgs, meta = [{"role": "user", "content": "pack"}], [None]
    for i, (name, args, result) in enumerate([
            ("fetch_page", {"url": "https://a.example/1"}, {"text": "A" * 3000}),
            ("search_web", {"query": "q"}, {"results": [{"title": "t", "url": "u", "snippet": "s" * 200}]}),
            ("fetch_page", {"url": "https://a.example/2"}, {"text": "B" * 3000}),
            ("run_financial_model", {"price": 1}, DESK_OK)], start=1):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]})
        meta.append(None)
        msgs.append({"role": "tool", "content": json.dumps(result)})
        meta.append({"name": name, "args": args, "result": result, "call_index": i})
    msgs.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_web", "arguments": {"query": "z"}}}]})
    meta.append(None)
    msgs.append({"role": "tool", "content": "{}"})
    meta.append({"name": "search_web", "args": {"query": "z"}, "result": {}, "call_index": 5})
    return msgs, meta


def test_page_notes_shrink_oldest_first_and_only_pages():
    msgs, meta = _history_with_pages()
    stats = {}
    out = at._compact_history(msgs, meta, shrink_page_chars=10, stats=stats)
    assert stats["page_notes_to_headers"] == 1
    assert out[2]["content"] == "[call 1] page: https://a.example/1 (read earlier)"
    assert out[6]["content"].startswith("[call 3] page: https://a.example/2 -> BBB")
    assert out[4]["content"].startswith('[call 2] search: "q" ->') and "sss" in out[4]["content"]
    assert out[8]["content"].startswith("[call 4] model:")
    stats = {}
    out = at._compact_history(msgs, meta, shrink_page_chars=10**6, stats=stats)
    assert stats["page_notes_to_headers"] == 2 and "sss" in out[4]["content"]
    assert at._compact_history(msgs, meta) == at._compact_history(msgs, meta, shrink_page_chars=0)


def test_the_loop_shrinks_pages_only_when_the_report_room_runs_short(monkeypatch, tmp_path):
    page = {"url": "https://a.example/1", "text": "A" * 3000}
    # revision 17, brief C8: the second call is a desk run (was a search), so the memorandum turn is not followed by
    # the desk continuation; the page notes and the shrink are what this test reads
    calls = [[{"function": {"name": "fetch_page", "arguments": {"url": "https://a.example/1"}}}],
             _desk_call()]

    def run(ctx):
        bodies = _fake_ollama(monkeypatch, [_resp("", tool_calls=calls[0], prompt=500),
                                            _resp("", tool_calls=calls[1], prompt=600),
                                            _resp(MEMO, prompt=700)])
        _dispatch(monkeypatch, [page, DESK_OK])
        _, _, meta = at.chat_with_tools("m", "pack", tmp_path, ctx=ctx, verbose=False)
        return bodies, meta

    bodies, meta = run(ctx=200000)                      # plenty of room: untouched
    assert "AAAA" in json.dumps(bodies[2]["messages"]) and not any(t.get("page_notes_to_headers") for t in meta["turns"])
    bodies, meta = run(ctx=at.REPORT_ROOM_TOKENS + 100)   # the next prompt would eat the report's room
    assert "(read earlier)" in json.dumps(bodies[2]["messages"])
    assert meta["turns"][2].get("page_notes_to_headers") == 1


# ---- window option A: the processing batch (2026-09-27) --------------------------------------

def test_num_batch_reaches_every_request_and_is_absent_by_default(monkeypatch, tmp_path):
    bodies = _fake_ollama(monkeypatch, [_resp("", done="length"), _resp("", done="length")])
    _run(tmp_path, num_batch=256)
    assert bodies and all(b["options"]["num_batch"] == 256 for b in bodies)
    bodies = _fake_ollama(monkeypatch, [_resp("", done="length"), _resp("", done="length")])
    _run(tmp_path)
    assert all("num_batch" not in b["options"] for b in bodies)


# ---- F1 server error (HTTP 5xx) handling -----------------------------------------------------

def test_f1_turn_1_raises_500_retries_and_continues(monkeypatch, tmp_path):
    # 1. turn 1 raises 500 with no tool call and no desk result -> the next request carries WINDOW_RETRY_PROMPT,
    # at the configured think level, and the run continues normally; the turn record has server_error: True, http_status: 500.
    err500 = urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 500, "Internal Server Error", {}, None)
    bodies = _fake_ollama(monkeypatch, [
        err500,
        _resp("", prompt=1000, tool_calls=_desk_call()),
        _resp(MEMO, prompt=1000),
    ])
    seen = _dispatch(monkeypatch, [DESK_OK])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 3
    retry_req = bodies[1]
    assert retry_req["messages"][-1] == {"role": "user", "content": at.WINDOW_RETRY_PROMPT}
    assert retry_req["think"] == "high"
    assert [s[0] for s in seen] == ["run_financial_model"]
    assert report == MEMO
    assert meta["turns"][0].get("server_error") is True
    assert meta["turns"][0].get("http_status") == 500
    assert meta["window_retry_used"] is True
    assert meta["failure"] is None


def test_f1_500_after_desk_result_forces_report(monkeypatch, tmp_path):
    # 2. a 500 after a desk result -> the next request is the forced report (no tools, configured think).
    err500 = urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 500, "Internal Server Error", {}, None)
    bodies = _fake_ollama(monkeypatch, [
        _resp("", tool_calls=_desk_call()),
        err500,
        _resp(MEMO),
    ])
    _dispatch(monkeypatch, [DESK_OK])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 3
    forced_req = bodies[2]
    assert "tools" not in forced_req
    assert forced_req["think"] == "high"
    assert report == MEMO
    assert meta["turns"][1].get("server_error") is True
    assert meta["turns"][1].get("http_status") == 500
    assert meta["turns"][2].get("forced_report") is True
    assert meta["failure"] is None


def test_f1_two_500s_stops_with_server_error_and_empty_report(monkeypatch, tmp_path):
    # 3. two 500s in one sample -> no third request is made; meta["failure"] == "server_error"; the report is empty.
    err500_1 = urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 500, "Internal Server Error", {}, None)
    err500_2 = urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 503, "Service Unavailable", {}, None)
    bodies = _fake_ollama(monkeypatch, [
        err500_1,
        err500_2,
    ])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 2
    assert meta["failure"] == "server_error"
    assert report == ""


def test_f1_non_5xx_httperror_still_raises(monkeypatch, tmp_path):
    # 4. a non-5xx HTTPError (e.g. 404) still raises.
    err404 = urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 404, "Not Found", {}, None)
    _fake_ollama(monkeypatch, [err404])
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _run(tmp_path)
    assert exc_info.value.code == 404


# ---- F2 window edge capping rule -------------------------------------------------------------

def test_f2_num_predict_capping_and_turn_record_keys(monkeypatch, tmp_path):
    # Tests: a request's num_predict equals min(configured, ctx - est - 2048) for a large prompt
    # and the configured value for a small one; the turn record carries both keys; never below 1024.

    # 1. Small prompt: num_predict equals configured value
    bodies1 = _fake_ollama(monkeypatch, [_resp(MEMO)])
    # revision 17, brief C8: max_model_calls=0 on these single-turn sessions (a memorandum with no desk run and the
    # desk open would be followed by a desk continuation turn); num_predict and the turn keys are mode-independent
    _, _, meta1 = at.chat_with_tools("m", "short", tmp_path, ctx=81920, num_predict=49152, verbose=False,
                                     max_model_calls=0)
    assert len(bodies1) == 1
    t0 = meta1["turns"][0]
    assert "est_prompt_tokens" in t0 and "num_predict" in t0
    assert t0["num_predict"] == 49152
    assert bodies1[0]["options"]["num_predict"] == 49152

    # 2. Large prompt: num_predict equals min(configured, ctx - est - 2048)
    large_prompt = "x" * 15000
    bodies2 = _fake_ollama(monkeypatch, [_resp(MEMO)])
    ctx2 = 10000
    _, _, meta2 = at.chat_with_tools("m", large_prompt, tmp_path, ctx=ctx2, num_predict=49152, verbose=False,
                                     max_model_calls=0)
    assert len(bodies2) == 1
    t1 = meta2["turns"][0]
    assert "est_prompt_tokens" in t1 and "num_predict" in t1
    expected_np2 = ctx2 - t1["est_prompt_tokens"] - 2048
    assert t1["num_predict"] == expected_np2
    assert bodies2[0]["options"]["num_predict"] == expected_np2

    # 3. Huge prompt: never below 1024
    huge_prompt = "x" * 60000
    bodies3 = _fake_ollama(monkeypatch, [_resp(MEMO)])
    ctx3 = 10000
    _, _, meta3 = at.chat_with_tools("m", huge_prompt, tmp_path, ctx=ctx3, num_predict=49152, verbose=False,
                                     max_model_calls=0)
    assert len(bodies3) == 1
    t2 = meta3["turns"][0]
    assert t2["num_predict"] == 1024
    assert bodies3[0]["options"]["num_predict"] == 1024

