"""Revision 17, brief C8: the desk continuation.

A terminal turn (no tool call) while no desk run has covered Base, Bull and Bear and the desk is still open gets one
more turn on the desk alone, at the configured think level, instead of a memorandum (or a forced memorandum) that
cannot publish anything. Every session here is the real loop with a mocked `_post` (urlopen): no network, no model."""
import copy
import json
import sys
import urllib.error
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyst_tools as at  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import depth_pipeline as dp  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN, _ctx, _happy_params  # noqa: E402

MEMO = "# MEMO ONE\n" + "x" * 6000
MEMO2 = "# MEMO TWO\n" + "y" * 6000
PRICE = 50.0                                   # _ctx(price=50): the Bear of _happy_params is refused at this price

# the four forms of the model-visible text, written out (not built from the module's own constants)
_TAIL = (" Code takes every published value from your last complete desk run of Bear, Base and Bull; without one, "
         "nothing is published. Call run_financial_model now with the Bear, Base and Bull your analysis argues for; "
         "only run_financial_model is open now, and you have {left} of {cap} desk runs left. When the desk has "
         "returned a complete run, write the complete memorandum, SECTION 0 to SECTION 12, with SECTION 0, SECTION 4 "
         "and SECTION 12 taken from that run.")
_NO_CALL = "no desk-backed value: you have made no run_financial_model call."
_NO_RUN = "no desk-backed value: none of your run_financial_model calls returned a complete run of Bear, Base and Bull."
TEXT_MEMO_NO_CALL = "Your memorandum has " + _NO_CALL + _TAIL
TEXT_NO_MEMO_NO_CALL = "Your turn ended without the memorandum, and there is " + _NO_CALL + _TAIL
TEXT_MEMO_NO_RUN = "Your memorandum has " + _NO_RUN + _TAIL
TEXT_NO_MEMO_NO_RUN = "Your turn ended without the memorandum, and there is " + _NO_RUN + _TAIL
ONLY_DESK = "Only run_financial_model is open now."


# ---- the mocked model -------------------------------------------------------------------------------------------

class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self, n=-1):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _turn(content="", tool_calls=None, done="stop"):
    m = {"content": content, "thinking": "t"}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return {"message": m, "done_reason": done, "prompt_eval_count": 1000, "eval_count": 10,
            "eval_duration": 1_000_000_000}


def _call(name, args):
    return [{"function": {"name": name, "arguments": copy.deepcopy(args)}}]


def _desk(params):
    return _turn(tool_calls=_call("run_financial_model", params))


OK = _happy_params(**_ALL_REASONS_GIVEN)            # accepted: Base, Bull and Bear in one call
BLEND = {"mode": "blend", "legs": [{"name": "leg", "weight": 1.0, "per_share_iv": 100.0}]}   # accepted, no roles


def _refused(g=-0.02):
    """A call refused at PRICE (the Bear above the price), a different one for every g."""
    p = _happy_params()
    for sc in p["scenarios"]:
        if sc["name"] == "Bear":
            sc["explicit_growth"] = [0.0, 0.0, g, g, g]
    return p


def _serve(monkeypatch, items):
    """Serve `items` in order; a request beyond them is an error (the loop made a turn nobody scripted)."""
    bodies, queue = [], list(items)

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        assert queue, f"the loop made request {len(bodies)} and nothing was scripted for it"
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _Resp(item)

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    def no_network(*a, **k):
        raise AssertionError("a search reached the network")

    monkeypatch.setattr(at, "search_web", no_network)
    return bodies


def _run(tmp_path, **kw):
    kw.setdefault("desk_context", _ctx(price=PRICE))
    return at.chat_with_tools("test-model", "test-pack", tmp_path, verbose=False, **kw)


def _snap(tmp_path):
    return json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))


def _tool_names(body):
    return [t["function"]["name"] for t in body.get("tools") or []]


def _c8_text(body):
    """The user message the desk continuation added to this request, or None."""
    for m in body["messages"]:
        if m["role"] == "user" and "no desk-backed value" in (m["content"] or ""):
            return m["content"]
    return None


# ---- the four texts -----------------------------------------------------------------------------------------------

def test_the_four_texts_memorandum_or_none_and_no_call_or_no_complete_run(monkeypatch, tmp_path):
    # a memorandum, no desk call
    bodies = _serve(monkeypatch, [_turn(MEMO), _turn(MEMO2)])
    _run(tmp_path / "a")
    assert bodies[1]["messages"][-1] == {"role": "user", "content": TEXT_MEMO_NO_CALL.format(left=5, cap=5)}
    assert bodies[1]["messages"][-2] == {"role": "assistant", "content": MEMO}      # the turn's content, as sent
    # an empty turn, no desk call
    bodies = _serve(monkeypatch, [_turn(""), _turn(MEMO2)])
    _run(tmp_path / "b")
    assert bodies[1]["messages"][-1] == {"role": "user", "content": TEXT_NO_MEMO_NO_CALL.format(left=5, cap=5)}
    # a memorandum after a refused call: calls were made, none returned a complete run
    bodies = _serve(monkeypatch, [_desk(_refused()), _turn(MEMO), _turn(MEMO2)])
    _run(tmp_path / "c")
    assert bodies[2]["messages"][-1] == {"role": "user", "content": TEXT_MEMO_NO_RUN.format(left=5, cap=5)}
    # an empty turn after a refused call
    bodies = _serve(monkeypatch, [_desk(_refused()), _turn(""), _turn(MEMO2)])
    _run(tmp_path / "d")
    assert bodies[2]["messages"][-1] == {"role": "user", "content": TEXT_NO_MEMO_NO_RUN.format(left=5, cap=5)}


def test_left_counts_accepted_runs_only_and_the_cap_is_max_model_calls(monkeypatch, tmp_path):
    # (m) KMT s1's shape: two refused calls, then an empty stop turn. The refused calls use no run.
    bodies = _serve(monkeypatch, [_desk(_refused(-0.02)), _desk(_refused(-0.03)), _turn(""), _turn(MEMO2)])
    _run(tmp_path / "m")
    assert bodies[3]["messages"][-1] == {"role": "user", "content": TEXT_NO_MEMO_NO_RUN.format(left=5, cap=5)}
    # one accepted (incomplete) blend run and two refusals: 4 of 5 left
    bodies = _serve(monkeypatch, [_desk(BLEND), _desk(_refused(-0.02)), _desk(_refused(-0.03)), _turn(""), _turn(MEMO2)])
    _run(tmp_path / "m2")
    assert bodies[4]["messages"][-1] == {"role": "user", "content": TEXT_NO_MEMO_NO_RUN.format(left=4, cap=5)}
    bodies = _serve(monkeypatch, [_turn(MEMO), _turn(MEMO2)])
    _run(tmp_path / "m3", max_model_calls=3)
    assert "you have 3 of 3 desk runs left" in bodies[1]["messages"][-1]["content"]


# ---- a. a memorandum with no desk call ------------------------------------------------------------------------------

def test_a_memorandum_with_no_desk_call_gets_the_continuation_and_the_new_memorandum_replaces_it(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_turn(MEMO), _desk(OK), _turn(MEMO2)])
    report, _, meta = _run(tmp_path, think="medium")
    assert len(bodies) == 3
    assert report == MEMO2                                                         # the new memorandum replaces the first
    # the offered tools: the whole set before, the desk alone after
    assert len(_tool_names(bodies[0])) > 1 and "run_financial_model" in _tool_names(bodies[0])
    assert _tool_names(bodies[1]) == ["run_financial_model"] == _tool_names(bodies[2])
    assert _c8_text(bodies[0]) is None and _c8_text(bodies[1]) == TEXT_MEMO_NO_CALL.format(left=5, cap=5)
    cont = meta["continuation_for_desk"]
    snap = _snap(tmp_path)
    base_iv = next(s["dcf"]["per_share_iv"] for s in snap["calls"][0]["scenario_dcfs"] if s["name"] == "Base")
    assert cont == {"reason": "no_desk_call", "after": "memorandum", "turn": 1, "desk_calls_after": 1,
                    "complete_after": True, "base_over_reference": pytest.approx(base_iv / 100.0)}
    assert [t.get("continuation_for_desk") for t in meta["turns"]] == [None, True, None]   # the continued turn's next turn
    assert meta["failure"] is None


def test_the_desk_call_after_the_continuation_counts_as_a_desk_run_and_the_budget_is_untouched(monkeypatch, tmp_path):
    _serve(monkeypatch, [_turn(MEMO), _desk(OK), _turn(MEMO2)])
    _, _, meta = _run(tmp_path)
    assert meta["desk_runs"] and meta["desk_validation_errors"] == 0
    assert _snap(tmp_path)["calls"][0]["desk_budget"].startswith("1 of 5 desk runs used")      # C8 adds no run


# ---- b. after C8 the model writes a memorandum without calling the desk ---------------------------------------------

def test_no_second_continuation_when_the_model_writes_again_without_a_desk_call(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_turn(MEMO), _turn(MEMO2)])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 2 and report == MEMO2
    assert meta["continuation_for_desk"] == {"reason": "no_desk_call", "after": "memorandum", "turn": 1,
                                             "desk_calls_after": 0, "complete_after": False,
                                             "base_over_reference": None}
    assert sum(1 for b in bodies for m in b["messages"] if m["role"] == "user"
               and "no desk-backed value" in m["content"]) == 1
    assert at.desk_run_is_complete(_snap(tmp_path)["calls"]) is False


# ---- c. the desk is closed by its own budget ------------------------------------------------------------------------

def test_no_continuation_when_max_model_calls_is_reached(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(BLEND), _turn(MEMO)])
    report, _, meta = _run(tmp_path, max_model_calls=1)          # one accepted blend-mode call uses the only run
    assert len(bodies) == 2 and report == MEMO
    assert meta["continuation_for_desk"] is None and not any(t.get("continuation_for_desk") for t in meta["turns"])


# ---- d. the desk is closed by seven refusals ------------------------------------------------------------------------

def test_no_continuation_when_seven_refusals_closed_the_desk_and_the_forced_memorandum_follows(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(_refused(-0.01 * k)) for k in range(1, 8)] + [_turn(""), _turn(MEMO)])
    report, _, meta = _run(tmp_path)
    assert meta["desk_validation_errors"] == 7
    assert len(bodies) == 9 and report == MEMO
    assert meta["continuation_for_desk"] is None and _c8_text(bodies[-1]) is None
    assert meta["turns"][-1].get("forced_report") is True and "tools" not in bodies[-1]      # as today


# ---- e. a complete run exists ---------------------------------------------------------------------------------------

def test_a_complete_run_means_no_continuation_and_the_memorandum_stands(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO)])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 2 and report == MEMO and meta["continuation_for_desk"] is None


def test_scenario_wise_runs_that_together_cover_the_roles_are_a_complete_run():
    # contract_fill's rule is a union over completed calls; this is what the harness asks the same predicate
    calls = [{"tool": "run_financial_model", "params": {}, "scenario_dcfs": [
                {"name": "Base", "dcf": {"per_share_iv": 100.0}}]},
             {"tool": "run_financial_model", "params": {}, "scenario_dcfs": [
                {"name": "Bull", "dcf": {"per_share_iv": 130.0}}, {"name": "Bear", "dcf": {"per_share_iv": 70.0}}]}]
    assert at.desk_run_is_complete(calls) is True
    assert at.desk_run_is_complete(calls[:1]) is False
    refused = dict(calls[1], validation_error=True)
    assert at.desk_run_is_complete([calls[0], refused]) is False                 # a refusal's entries do not count
    assert at.desk_run_is_complete([calls[0], dict(calls[1], error="x")]) is False
    assert at.desk_run_is_complete([]) is False


# ---- f. a window retry and then C8 in one session -------------------------------------------------------------------

def test_a_window_retry_and_then_the_continuation_each_exactly_once(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_turn("", done="length"), _turn(MEMO), _desk(OK), _turn(MEMO2)])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 4 and report == MEMO2
    assert json.dumps(bodies).count(at.WINDOW_RETRY_PROMPT[:60]) == 3     # sent in requests 2, 3, 4: it stays in the history
    assert sum(1 for t in meta["turns"] if t.get("window_retry")) == 1
    assert sum(1 for t in meta["turns"] if t.get("continuation_for_desk")) == 1
    assert meta["turns"][1].get("window_retry") is True and meta["turns"][2].get("continuation_for_desk") is True
    assert meta["window_retry_used"] is True
    assert meta["continuation_for_desk"]["reason"] == "no_desk_call"
    assert meta["continuation_for_desk"]["after"] == "memorandum" and meta["continuation_for_desk"]["turn"] == 2
    assert meta["failure"] is None


# ---- g. the think level ---------------------------------------------------------------------------------------------

def test_every_turn_runs_at_the_configured_think_level_and_is_not_reduced_thinking(monkeypatch, tmp_path):
    for think in ("medium", "high"):
        bodies = _serve(monkeypatch, [_turn(""), _desk(OK), _turn(MEMO2)])
        _, _, meta = _run(tmp_path / think, think=think)
        assert [b["think"] for b in bodies] == [think] * 3
        assert [t["think"] for t in meta["turns"]] == [think] * 3
        assert meta["think_configured"] == think
        assert cv.rescue_status(meta)["reduced_thinking"] is False
    # the normal num_predict (49152 configured), capped only by the room rule every turn obeys: not the low-effort
    # 16,384 of the removed desk-only recovery
    assert {k: v for k, v in bodies[1]["options"].items() if k != "num_predict"} == \
           {k: v for k, v in bodies[0]["options"].items() if k != "num_predict"}
    t = meta["turns"][1]
    assert t["num_predict"] == max(1024, min(49152, 65536 - t["est_prompt_tokens"] - 2048))
    assert bodies[1]["options"]["num_predict"] == t["num_predict"]


# ---- h. the preview's shape: an empty stop turn with no desk call ---------------------------------------------------

def test_an_empty_stop_turn_gets_the_continuation_before_any_forced_memorandum(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_turn(""), _turn(""), _turn(MEMO)])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 3 and report == MEMO
    assert _c8_text(bodies[1]) == TEXT_NO_MEMO_NO_CALL.format(left=5, cap=5)
    assert "tools" not in bodies[2] and meta["turns"][2].get("forced_report") is True      # then the forced memorandum, as today
    assert meta["continuation_for_desk"]["after"] == "no_memorandum"
    assert meta["continuation_for_desk"]["complete_after"] is False        # the forced memorandum has no desk run behind it


def test_a_stub_after_the_continuation_is_forced_and_the_outcome_depends_on_a_complete_run(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_turn(""), _desk(OK), _turn(""), _turn(MEMO)])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 4 and report == MEMO and meta["turns"][3].get("forced_report") is True
    assert meta["continuation_for_desk"]["complete_after"] is True and meta["continuation_for_desk"]["desk_calls_after"] == 1
    assert at.desk_run_is_complete(_snap(tmp_path)["calls"]) is True


# ---- i. any other tool while restricted -----------------------------------------------------------------------------

def test_a_search_while_restricted_gets_the_error_and_counts_against_no_budget(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_turn(MEMO),
                                  _turn(tool_calls=_call("search_web", {"query": "anything at all", "why": "x"})),
                                  _turn(tool_calls=_call("fetch_page", {"url": "https://a.example/1"})),
                                  _desk(OK), _turn(MEMO2)])
    _, _, meta = _run(tmp_path, max_search_calls=1)
    calls = _snap(tmp_path)["calls"]
    assert [c["tool"] for c in calls] == ["search_web", "fetch_page", "run_financial_model"]
    assert calls[0]["error"] == ONLY_DESK and calls[1]["error"] == ONLY_DESK
    assert meta["research_calls"] == 0 and meta["repeat_calls"] == 0        # search_calls, research_calls unchanged
    assert json.loads(bodies[2]["messages"][-1]["content"]) == {"error": ONLY_DESK}
    assert meta["desk_runs"] and meta["continuation_for_desk"]["complete_after"] is True


# ---- j, k. never fires ----------------------------------------------------------------------------------------------

def test_discovery_mode_never_fires(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_turn(MEMO)])
    report, _, meta = _run(tmp_path, max_model_calls=0)
    assert len(bodies) == 1 and report == MEMO and meta["continuation_for_desk"] is None
    bodies = _serve(monkeypatch, [_turn(""), _turn(MEMO)])          # a stub in discovery mode is forced, as today
    _, _, meta = _run(tmp_path / "stub", max_model_calls=0)
    assert len(bodies) == 2 and meta["continuation_for_desk"] is None and meta["turns"][1].get("forced_report") is True


def test_a_server_error_terminal_turn_never_fires(monkeypatch, tmp_path):
    err500 = urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 500, "Internal Server Error", {}, None)
    # an accepted, incomplete run first, so the window retry (which needs no desk run) does not take the turn
    bodies = _serve(monkeypatch, [_desk(BLEND), err500, _turn(MEMO)])
    report, _, meta = _run(tmp_path)
    assert len(bodies) == 3 and report == MEMO
    assert meta["turns"][1].get("server_error") is True and meta["turns"][2].get("forced_report") is True
    assert meta["continuation_for_desk"] is None and _c8_text(bodies[2]) is None


def test_the_continuation_is_not_offered_when_the_desk_tool_is_not_among_the_tools(monkeypatch, tmp_path):
    # a caller-supplied tool list without the desk: nothing to ask for
    search_only = [t for t in at.TOOLS if t["function"]["name"] != "run_financial_model"]
    bodies = _serve(monkeypatch, [_turn(MEMO)])
    _, _, meta = _run(tmp_path, tools=search_only)
    assert len(bodies) == 1 and meta["continuation_for_desk"] is None


# ---- l. propagation ---------------------------------------------------------------------------------------------------

CONTINUATION = {"reason": "no_desk_call", "after": "memorandum", "turn": 1, "desk_calls_after": 1,
                "complete_after": True, "base_over_reference": 1.04}


def test_rescue_status_carries_the_record():
    assert cv.rescue_status({"turns": [{}], "continuation_for_desk": CONTINUATION})["continuation_for_desk"] == CONTINUATION
    assert cv.rescue_status({"turns": [{}]})["continuation_for_desk"] is None
    assert cv.rescue_status(None)["continuation_for_desk"] is None


def _run_record(**over):
    r = {"sample": 1, "iv": 100.0, "plausible": True, "truncated": False, "flags": [], "reasons": [],
         "reduced_thinking": False, "failed_reason": None, "basis": True, "desk_calls": 2}
    r.update(over)
    return r


def test_the_verdict_flag_is_added_when_a_usable_sample_used_the_continuation(monkeypatch):
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: None)

    def doc(*runs):
        return {"ticker": "ACME", "price": 90.0, "runs": list(runs), "n_basis": len(runs), "spread_pct": 3.0,
                "median_iv": 100.0, "iv_band_low": 98.0, "iv_band_high": 102.0, "samples_lost": 0}
    v = dp.band_verdict(doc(_run_record(continuation_for_desk=CONTINUATION),
                            _run_record(sample=2, iv=101.0)))
    assert "CONTINUATION_FOR_DESK" in v["flags"]
    v = dp.band_verdict(doc(_run_record(), _run_record(sample=2, iv=101.0)))
    assert "CONTINUATION_FOR_DESK" not in v["flags"]
    # a sample that used it and is not usable does not put the flag on the verdict
    v = dp.band_verdict(doc(_run_record(),
                            _run_record(sample=2, iv=101.0),
                            _run_record(sample=3, iv=None, plausible=False, basis=False,
                                        continuation_for_desk=CONTINUATION)))
    assert "CONTINUATION_FOR_DESK" not in v["flags"]


def _main_run(monkeypatch, tmp_path, turns):
    """cv.main() on one sample with the mocked model; returns the run record."""
    import test_review_fixes_2 as r2
    queue = list(turns)

    def fake_urlopen(req, timeout=None):
        assert queue, "an unscripted request"
        return _Resp(queue.pop(0))

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(at, "dispatch_tool", lambda name, args, **kw: r2.DESK_OK)
    pack = tmp_path / "_sim_pack.md"
    pack.write_text("SIM PACK\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "ZZSIM", "--tools", "--samples", "1", "--pack-file",
                                      str(pack), "--out-dir", str(tmp_path / "cons"), "--price", "400",
                                      "--no-research", "--think", "high"])
    cv.main()
    d = sorted((tmp_path / "cons").glob("ZZSIM_*"))[-1]
    return json.loads((d / "consensus.json").read_text(encoding="utf-8"))["runs"][0]


def test_the_run_record_and_the_sample_flag_when_the_continuation_delivers_a_desk_backed_sample(monkeypatch, tmp_path):
    import test_review_fixes_2 as r2
    run = _main_run(monkeypatch, tmp_path, [_turn(r2.MEMO), _desk({"price": 400.0}), _turn(r2.MEMO)])
    assert run["continuation_for_desk"]["reason"] == "no_desk_call" and run["continuation_for_desk"]["complete_after"] is True
    assert "first_attempt_continuation_for_desk" not in run            # only when the sample was retried
    assert "continuation_for_desk" in run["flags"] and "continuation_for_desk_failed" not in run["flags"]
    assert run["basis"] is True and cv.counts_as_result(run)


def test_the_sample_flag_when_the_continuation_fails_and_the_sample_stays_out_of_the_band(monkeypatch, tmp_path):
    import test_review_fixes_2 as r2
    run = _main_run(monkeypatch, tmp_path, [_turn(r2.MEMO), _turn(r2.MEMO)])
    assert run["continuation_for_desk"]["complete_after"] is False
    assert "continuation_for_desk_failed" in run["flags"] and "continuation_for_desk" not in run["flags"]
    assert "desk_not_used" in run["flags"] and run["basis"] is False      # counts_as_result is unchanged: still out of the band


def test_a_sample_retried_carries_the_first_attempts_record_too(monkeypatch, tmp_path):
    import test_review_fixes_2 as r2
    # attempt 1: empty report after a continuation that produced nothing; attempt 2 (whole-sample retry): a desk run
    run = _main_run(monkeypatch, tmp_path, [_turn(""), _turn(""), _turn(""),
                                            _desk({"price": 400.0}), _turn(r2.MEMO)])
    assert run["sample_retried"] is True
    assert run["first_attempt_continuation_for_desk"]["after"] == "no_memorandum"
    assert run["first_attempt_continuation_for_desk"]["complete_after"] is False
    assert run["continuation_for_desk"] is None                      # the retry's own record: it did not need the continuation


# ---- the census: the state the harness predicate looks for ------------------------------------------------------------

def test_the_predicate_reads_the_desk_state_alone():
    none_made = []
    refused = [{"tool": "run_financial_model", "validation_error": True, "error": "x"}] * 2
    assert at.desk_continuation_cause(none_made, 0, 0, 5) == "no_desk_call"
    assert at.desk_continuation_cause(refused, 0, 2, 5) == "no_complete_run"
    assert at.desk_continuation_cause(refused, 0, 7, 5) is None            # closed by refusals
    assert at.desk_continuation_cause(none_made, 5, 0, 5) is None          # closed by runs
    assert at.desk_continuation_cause(none_made, 0, 0, 0) is None          # discovery mode
    assert at.desk_continuation_cause(none_made, 4, 6, 5) == "no_desk_call"    # 6 refusals leave the desk open
