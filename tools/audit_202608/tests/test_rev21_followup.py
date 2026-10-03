"""Pack revision 21, brief_rev21.md part S: the one-turn crux follow-up, its record, and the memorandum-verdict flag.

After a sample's memorandum, when the answer run is directional (undervalued or overvalued by 10% or more) and `crux_check` says `missing`, the harness
sends exactly one follow-up message. Every session here is the real loop with a mocked model (no network, no model)."""
import copy
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyst_tools as at  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import contract_fill  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN, _ctx, _happy_params  # noqa: E402
from test_desk_continuation import MEMO, MEMO2, PRICE, _desk, _main_run, _serve, _snap, _tool_names, _turn  # noqa: E402
from test_rev21_refusals import PACK  # noqa: E402

OK = _happy_params(**_ALL_REASONS_GIVEN)           # Base $104.26 at the context's reference: +108% against PRICE 50, so undervalued
QUOTE = "Free cash flow of $410 million."
BASE_QUOTE = "Revenue of $1,234.5 million grew 12%. Backlog reached $9.9 billion."


def crux(src="PRIMARY P1", quote=BASE_QUOTE, inp="coe"):
    return [{"input": inp, "reason": "the company's own filing says otherwise, by about two points", "citations": [{"source": src, "date": "2026-07-30", "quote": quote}]}]


def with_crux(params=None, **kw):
    return dict(copy.deepcopy(params or OK), crux=crux(**kw))


def followup_text(base, price, side):
    x = f"{abs(base / price - 1) * 100:.0f}"
    return (f"Your Base sits {x}% {side} the price, but your answer run passed no crux, so the verdict is HOLD. If your evidence supports a disagreement "
            "with the price, call the desk once more with your answer-run inputs unchanged plus `crux` (input, reason, citations with quotes copied exactly; "
            "PRIMARY P# sources qualify). If it does not, reply HOLD and end SECTION 0 and SECTION 12 with HOLD.")


def _run(tmp_path, price=PRICE, **kw):
    kw.setdefault("desk_context", _ctx(price=price))
    return at.chat_with_tools("test-model", PACK, tmp_path, verbose=False, **kw)


def _answer(tmp_path):
    return contract_fill.answer_run(_snap(tmp_path)["calls"])


def _followup_message(body):
    for m in body["messages"]:
        if m["role"] == "user" and "your answer run passed no crux" in (m["content"] or ""):
            return m["content"]
    return None


# ---- when it fires ------------------------------------------------------------------------------------------------------------

def test_it_fires_once_on_a_directional_answer_run_with_no_crux_with_the_briefs_text(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO), _turn(MEMO2)])         # a fourth request would fail the loop
    rep, _, meta = _run(tmp_path)
    call, base, _ = _answer(tmp_path)
    assert 100 < base < 110
    assert _followup_message(bodies[1]) is None and _followup_message(bodies[2]) == followup_text(base, PRICE, "above")
    assert bodies[2]["messages"][-1] == {"role": "user", "content": followup_text(base, PRICE, "above")}
    assert bodies[2]["messages"][-2] == {"role": "assistant", "content": MEMO}      # the memorandum it follows, as the model wrote it
    assert _tool_names(bodies[2]) == ["run_financial_model"]                          # only the desk is open
    assert rep == MEMO2 and meta["crux_followup"] == {"fired": True, "outcome": "hold_confirmed"}
    assert len(bodies) == 3                                                           # exactly one follow-up


def test_overvalued_says_below(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO), _turn(MEMO2)])
    _run(tmp_path, price=200.0)
    base = _answer(tmp_path)[1]
    assert _followup_message(bodies[2]) == followup_text(base, 200.0, "below") and "below the price" in _followup_message(bodies[2])


def test_it_never_fires_on_hold(monkeypatch, tmp_path):
    _serve(monkeypatch, [_desk(OK), _turn(MEMO)])                                      # a second memo request would fail the loop
    rep, _, meta = _run(tmp_path, price=104.0)                                         # Base 104.26 is within 10% of the price
    assert rep == MEMO and meta["crux_followup"] == {"fired": False, "outcome": None}


def test_it_never_fires_when_the_answer_run_carries_a_crux_whatever_its_validity(monkeypatch, tmp_path):
    # a crux citing a source the pack does not hold is no_company_evidence: a failed crux, not a missing one
    _serve(monkeypatch, [_desk(with_crux(src="PRIMARY P9")), _turn(MEMO)])
    rep, _, meta = _run(tmp_path)
    assert rep == MEMO and meta["crux_followup"] == {"fired": False, "outcome": None}
    # a valid one
    _serve(monkeypatch, [_desk(with_crux()), _turn(MEMO)])
    assert _run(tmp_path / "b")[2]["crux_followup"] == {"fired": False, "outcome": None}
    # an input the desk cannot reach is not_reachable: no follow-up either (the crux is not missing)
    _serve(monkeypatch, [_desk(with_crux(inp="terminal_g")), _turn(MEMO)])
    assert _run(tmp_path / "c")[2]["crux_followup"] == {"fired": False, "outcome": None}


def test_the_state_function_reads_the_answer_run_alone():
    mk = lambda params, **res: {"tool": "run_financial_model", "call_index": 1, "params": params, **res}
    done = fmt.execute_financial_model(copy.deepcopy(OK), context=_ctx(price=50.0))
    call = mk(OK, **done)
    st = at.crux_followup_state([call], 50.0, "pack", {"company": "Acme", "ticker": "ACME"})
    assert st["direction"] == "undervalued" and st["answer_call_index"] == 1 and "crux" not in st["inputs"]
    assert at.crux_followup_state([call], 104.0, "pack") is None                                       # hold
    assert at.crux_followup_state([], 50.0, "pack") is None and at.crux_followup_state([{"tool": "search_web"}], 50.0, "pack") is None
    assert at.crux_followup_state([call], None, "pack") is None and at.crux_followup_state([call], 0, "pack") is None
    assert at.crux_followup_state([call], 50.0, "pack")["base"] == contract_fill.answer_run([call])[1]
    withcrux = mk(with_crux(), **done)
    assert at.crux_followup_state([withcrux], 50.0, PACK, {"company": "Acme", "ticker": "ACME"}) is None
    refused = mk(OK, error="x", validation_error=True)
    assert at.crux_followup_state([refused], 50.0, "pack") is None                                      # a refused call is no answer run
    old = copy.deepcopy(OK)
    del old["cash_flow_life"]
    assert at.crux_followup_state([mk(old, **done)], 50.0, "pack") is None                              # a pre-revision-15 call: never


def test_answer_run_is_the_rule_fill_applies():
    done = fmt.execute_financial_model(copy.deepcopy(OK), context=_ctx(price=50.0))
    other = fmt.execute_financial_model(copy.deepcopy(_happy_params(**_ALL_REASONS_GIVEN)), context=_ctx(price=50.0))
    calls = [{"tool": "run_financial_model", "call_index": 1, "params": OK, **done},
             {"tool": "run_financial_model", "call_index": 2, "params": OK, "error": "x", "validation_error": True},
             {"tool": "run_financial_model", "call_index": 3, "params": OK, **other},
             {"tool": "search_web", "call_index": 4}]
    filled, prov = contract_fill.fill(calls, {}, {"coe_anchor": 0.08}, 50.0)
    call, base, r15 = contract_fill.answer_run(calls)
    assert call["call_index"] == prov["answer_call_index"] == 3 and base == filled["base_iv"] and r15 is True
    # scenario-wise: no joint call, the last call that values a Base supplies it
    mk = lambda i, name, iv: {"tool": "run_financial_model", "call_index": i, "params": {"cash_flow_life": "perpetual"},
                              "scenario_dcfs": [{"name": name, "dcf": {"per_share_iv": iv}}]}
    sc_only = [mk(1, "Base", 90.0), mk(2, "Bull", 130.0), mk(3, "Base", 100.0)]
    fl2, prov2 = contract_fill.fill(sc_only, {}, {"coe_anchor": 0.08}, 50.0)
    c2, b2, r2 = contract_fill.answer_run(sc_only)
    assert prov2["mode"] == "scenario_wise" and c2["call_index"] == 3 and b2 == fl2["base_iv"] == 100.0 and r2 is True
    assert contract_fill.answer_run([]) == (None, None, False) and contract_fill.answer_run([mk(1, "Bull", 130.0)]) == (None, None, False)


# ---- what it comes to ----------------------------------------------------------------------------------------------------------

def test_crux_added_the_new_call_with_the_same_inputs_plus_a_crux_becomes_the_answer_run(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(with_crux()), _turn(MEMO2)])
    rep, _, meta = _run(tmp_path)
    snap = _snap(tmp_path)["calls"]
    assert meta["crux_followup"] == {"fired": True, "outcome": "crux_added"} and rep == MEMO2
    call, base, _ = contract_fill.answer_run(snap)
    assert call["call_index"] == 2 and call["params"]["crux"][0]["input"] == "coe" and not call.get("error")
    assert call["crux_citation_check"][0]["citations"] == [{"source": "PRIMARY P1", "class": "pack_company", "quote_found": True}]   # the new check reads the item
    # and the label code now sees a crux: the sample can stay undervalued
    filled, _ = contract_fill.fill(snap, {}, {"coe_anchor": 0.08}, PRICE, pack_text=PACK, company="Acme")
    assert filled["direction_m"] == "undervalued" and filled["crux_check"]["entries"][0]["citations"][0]["class"] == "pack_company"
    assert len(bodies) == 4                                                            # no second follow-up after the memorandum that follows it


def test_a_changed_input_is_refused_as_not_a_desk_run_and_the_sample_stays_at_its_answer_run(monkeypatch, tmp_path):
    changed = copy.deepcopy(OK)
    changed["scenarios"][0]["base_cf"] = 5.2
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(dict(changed, crux=crux())), _turn(MEMO2)])
    rep, _, meta = _run(tmp_path)
    snap = _snap(tmp_path)["calls"]
    refusal = snap[1]
    assert refusal["validation_error"] is True and refusal["error"].startswith("Not accepted as a desk run; it does not use one of your desk runs.")
    assert refusal["crux_followup_changed"] == ["Base.base_cf"] and "Base.base_cf" in refusal["error"]
    assert contract_fill.answer_run(snap)[0]["call_index"] == 1                          # the original answer run
    assert meta["crux_followup"] == {"fired": True, "outcome": "no_change"} and rep == MEMO2
    assert meta["desk_validation_errors"] == 1 and meta["desk_runs"] and len(meta["desk_runs"]) == 1       # the refusal used no desk run


def test_a_follow_up_call_with_the_same_inputs_and_no_crux_is_no_change(monkeypatch, tmp_path):
    _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(OK), _turn(MEMO2)])
    _, _, meta = _run(tmp_path)
    assert meta["crux_followup"] == {"fired": True, "outcome": "no_change"}


def test_the_follow_up_has_its_own_desk_run_when_the_desk_was_used_up(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(with_crux()), _turn(MEMO2)])
    _, _, meta = _run(tmp_path, max_model_calls=1)
    assert meta["crux_followup"]["outcome"] == "crux_added"
    results = [c for c in _snap(tmp_path)["calls"] if c["tool"] == "run_financial_model"]
    assert len(results) == 2 and "error" not in results[1]
    assert "desk_closed" in results[1]                                                   # and the desk is closed again after it: one follow-up run
    assert _tool_names(bodies[3]) == []


def test_only_one_desk_run_follows_the_message(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(with_crux()), _turn(MEMO2)])
    _run(tmp_path)
    assert _tool_names(bodies[3]) == []                                                  # after the follow-up's run the desk is closed


def test_a_bare_hold_reply_leaves_the_first_memorandum_standing(monkeypatch, tmp_path):
    _serve(monkeypatch, [_desk(OK), _turn(MEMO), _turn("HOLD")])                          # no forced-report request is scripted: it must not be made
    rep, _, meta = _run(tmp_path)
    assert rep == MEMO and meta["crux_followup"] == {"fired": True, "outcome": "hold_confirmed"} and meta["failure"] is None
    assert not any(t.get("forced_report") for t in meta["turns"])
    assert [t.get("crux_followup") for t in meta["turns"]].count(True) == 1               # the turn after the message is marked


def test_the_follow_up_does_not_fire_after_a_forced_report_or_with_the_desk_closed_by_refusals(monkeypatch, tmp_path):
    # the desk closed by seven refusals: the model cannot call it, so there is nothing to ask
    bad = copy.deepcopy(OK)
    del bad["cash_flow_life"]
    items = [_desk(OK)] + [_desk(bad) for _ in range(7)] + [_turn(MEMO)]
    _serve(monkeypatch, items)
    _, _, meta = _run(tmp_path)
    assert meta["crux_followup"] == {"fired": False, "outcome": None}


# ---- the desk's refusal -------------------------------------------------------------------------------------------------------

def _ref(**over):
    p = copy.deepcopy(OK)
    p.update(over)
    return p


def test_the_desk_compares_inputs_not_reasons_and_matches_scenarios_by_role():
    ref = _ref()
    f = fmt.followup_input_changes
    assert f(copy.deepcopy(OK), ref) == [] and f(dict(copy.deepcopy(OK), crux=crux()), ref) == []
    reasons = copy.deepcopy(OK)
    reasons["base_cf_reason"] = "a different sentence"
    reasons["terminal_reason"] = None
    assert f(reasons, ref) == []                                                           # reasons are text, not inputs
    alias = copy.deepcopy(OK)
    for sc in alias["scenarios"]:
        sc["growth_rates"] = sc.pop("explicit_growth")
    assert f(alias, ref) == []                                                             # growth_rates is explicit_growth
    renamed = copy.deepcopy(OK)
    renamed["scenarios"][0]["name"] = "Base case"
    renamed["scenarios"] = renamed["scenarios"][::-1]
    assert f(renamed, ref) == []                                                           # matched by role, not by order or name
    annotated = copy.deepcopy(OK)
    annotated["scenarios"][0]["iv"] = 104.26
    annotated["scenarios"][0]["dcf_details"] = {"x": 1}
    assert f(annotated, ref) == [] and f(ref, annotated) == []                             # what the desk annotated onto the answer call is not an input
    near = copy.deepcopy(OK)
    near["scenarios"][1]["wacc"] = 0.075 * (1 + 1e-12)
    assert f(near, ref) == []
    assert f(_ref(fade_years=3), ref) == ["fade_years"]
    assert f(_ref(terminal_g=0.031), ref) == ["terminal_g"]
    assert f(_ref(excess_cash=1.0), ref) == ["excess_cash"]
    assert f(_ref(cash_flow_life="perpetual"), _ref(cash_flow_life=20)) == ["cash_flow_life"]
    ch = copy.deepcopy(OK)
    ch["scenarios"][1]["explicit_growth"][2] = 0.06
    ch["scenarios"][2]["prob"] = 0.30
    assert f(ch, ref) == ["Bull.explicit_growth", "Bear.prob"] or sorted(f(ch, ref)) == ["Bear.prob", "Bull.explicit_growth"]
    dropped = copy.deepcopy(OK)
    dropped["scenarios"].pop()
    assert f(dropped, ref) == ["Bear.scenario"]


def test_the_desk_refuses_a_changed_input_only_when_the_context_names_an_answer_run():
    ctx = _ctx(price=50.0)
    changed = _ref(fade_years=2)
    assert "error" not in fmt.execute_financial_model(copy.deepcopy(changed), context=ctx)              # an ordinary call: no such rule
    res = fmt.execute_financial_model(copy.deepcopy(changed), context=dict(ctx, crux_followup_inputs=_ref()))
    assert res["validation_error"] is True and res["crux_followup_changed"] == ["fade_years"]
    assert res["error"].startswith("Not accepted as a desk run; it does not use one of your desk runs.") and res["missing"] == []
    ok = fmt.execute_financial_model(dict(copy.deepcopy(OK), crux=crux()), context=dict(ctx, crux_followup_inputs=copy.deepcopy(OK)))
    assert "error" not in ok and ok["crux_desk_check"][0]["input"] == "coe"
    # a malformed crux is still refused by the form check first
    bad = fmt.execute_financial_model(dict(copy.deepcopy(OK), crux=[{"input": "coe"}]), context=dict(ctx, crux_followup_inputs=copy.deepcopy(OK)))
    assert bad["validation_error"] is True and any("crux[1]" in m for m in bad["missing"])


# ---- the record and the memorandum flag ----------------------------------------------------------------------------------------

def test_the_record_is_on_every_sample_in_consensus_json_and_the_memo_flag_is_annotation_only(monkeypatch, tmp_path):
    import test_review_fixes_2 as r2
    for sub in "abc":
        (tmp_path / sub).mkdir()
    run = _main_run(monkeypatch, tmp_path / "a", [_turn(r2.MEMO), _desk({"price": 400.0}), _turn(r2.MEMO)])
    assert run["crux_followup"] == {"fired": False, "outcome": None}
    assert "memo_verdict_mismatch" not in run["flags"]                                    # r2's SECTION 0 states no verdict word
    contradicting = r2.MEMO.replace("SECTION 0. EXECUTIVE VERDICT", "SECTION 0. EXECUTIVE VERDICT\nVerdict: undervalued, by 40%.", 1)
    run2 = _main_run(monkeypatch, tmp_path / "b", [_turn(contradicting), _desk({"price": 400.0}), _turn(contradicting)])
    assert run2["scorecard"]["verdict_label"] == "hold" and "memo_verdict_mismatch" in run2["flags"]
    assert run2["basis"] is True and cv.counts_as_result(run2) and run2["plausible"] is True            # reported, never a gate
    agreeing = r2.MEMO.replace("SECTION 0. EXECUTIVE VERDICT", "SECTION 0. EXECUTIVE VERDICT\nVerdict: HOLD at $400.", 1)
    run3 = _main_run(monkeypatch, tmp_path / "c", [_turn(agreeing), _desk({"price": 400.0}), _turn(agreeing)])
    assert "memo_verdict_mismatch" not in run3["flags"]


@pytest.mark.parametrize("memo,word", [
    ("## SECTION 0. Overview\nVerdict: undervalued. Base $120.\n## SECTION 1. Macro\nhold", "undervalued"),
    ("SECTION 0\n**Verdict:** Overvalued (Base $80)\nSECTION 1", "overvalued"),
    ("SECTION 0. OVERVIEW\nMy verdict is HOLD; the stock is not overvalued.\nSECTION 1", "hold"),
    ("SECTION 0. Overview\nTicker ACME, price $100. The stock looks fairly valued.\nSECTION 1. x\nundervalued", "hold"),
    ("SECTION 0. Overview\nVerdict - fair.\nSECTION 1.", "hold"),
    ("SECTION 0. Overview\nNo word here.\nSECTION 1. x\nVerdict: undervalued", None),
    ("no sections at all, undervalued", None), ("", None), (None, None),
])
def test_memo_verdict_word(memo, word):
    assert cv.memo_verdict_word(memo) == word
