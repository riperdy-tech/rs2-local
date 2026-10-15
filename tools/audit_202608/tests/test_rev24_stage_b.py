"""Pack revision 24 (PHASE_4_REV24_MUSE.md R24.2, brief BRIEF_R24_2_reference_after_commit.md): stage B, the reference shown once after the analyst
commits, and its code-enforced guardrails G1-G5.

Every session here is the real chat_with_tools loop with a mocked model (no network, no model): stage A is a desk run and a memorandum on a pack
that did not print the CONSENSUS-IMPLIED VALUE (CIV); the harness then sends REFERENCE_REVEAL once and judges the reply."""
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
from test_desk_continuation import MEMO, MEMO2, PRICE, _desk, _serve, _snap, _tool_names, _turn  # noqa: E402
from test_rev21_followup import BASE_QUOTE, crux, followup_text  # noqa: E402
from test_rev21_refusals import PACK  # noqa: E402

CIV = 100.0                     # the desk context's reference; stage A's Base is 104.26 (test_desk_checks._happy_params)
LINE = ("- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $100.00 per share, the analysts' own earnings path at our discount "
        "rate — context | base: owner earnings 5.000 | cash-flow growth years 1-5: +5.0% / +5.0% / +2.0% / +2.0% / +2.0% | discounted at the COE "
        "ANCHOR 8.00%")
INPUTS = ("base: owner earnings 5.000 | cash-flow growth years 1-5: +5.0% / +5.0% / +2.0% / +2.0% / +2.0% | discounted at the COE ANCHOR 8.00%")
REVEAL = {"civ": CIV, "status": "used", "line": LINE}
A_ANSWER = dict(_happy_params(**_ALL_REASONS_GIVEN), crux=crux())       # undervalued at PRICE 50 with a valid crux: no crux follow-up
NEW_QUOTE = "ACME reports second quarter 2026 results."                  # PRIMARY P1, never used in stage A (40 characters)
NEW_QUOTE_2 = "The Birmingham site adds 250 megawatts."                  # PRIMARY P1, never used in stage A (39 characters)


@pytest.fixture(autouse=True)
def _reveal_on(monkeypatch):
    """Revision 24 step 2a: stage B is off by default (config `reference_reveal`, absent = false); its code and these tests are kept and run with
    the flag on. test_rev24_s2a.py proves the default pipeline never fires it."""
    import rs2_data
    monkeypatch.setitem(rs2_data.CONFIG, "reference_reveal", True)


def reveal_text(base):
    return ("For comparison only: the CONSENSUS-IMPLIED VALUE (what Wall Street's forecasts imply through a fixed formula) is $100.00 per share; its "
            f"inputs: {INPUTS}. Your Base is ${base:,.2f}. Reply KEEP if your valuation stands. You may revise only an input for which you have "
            "evidence you did not use before: call the desk once with your answer-run inputs, changing only those inputs, and add "
            "`reference_revision`: a list of {input, old, new, citation: {source, quote}}. The source must be a PRIMARY P# item or a filing quoted "
            "exactly. The reference itself is never a reason.")


def _run(tmp_path, reveal=REVEAL, price=PRICE, **kw):
    kw.setdefault("desk_context", _ctx(price=price, reference_withheld=True, company="Acme", ticker="ACME"))
    return at.chat_with_tools("test-model", PACK, tmp_path, verbose=False, reference_reveal=reveal, **kw)


def revised(changes, entries):
    """stage A's answer run with `changes` {(role, key): value} applied and reference_revision `entries`."""
    p = copy.deepcopy(A_ANSWER)
    for (role, key), v in changes.items():
        next(s for s in p["scenarios"] if s["name"] == role)[key] = v
    p["reference_revision"] = entries
    return p


def entry(inp, old, new, quote=NEW_QUOTE, source="PRIMARY P1"):
    return {"input": inp, "old": str(old), "new": str(new), "citation": {"source": source, "quote": quote}}


def _reveal_message(body):
    return next((m["content"] for m in body["messages"] if m["role"] == "user" and m["content"].startswith("For comparison only:")), None)


def _base_of(params, price=PRICE):
    stage_b = {"reference_revision_inputs": copy.deepcopy(A_ANSWER)} if "reference_revision" in params else {}
    res = fmt.execute_financial_model(copy.deepcopy(params), context=_ctx(price=price, reference_withheld=True, **stage_b))
    return next(s["dcf"]["per_share_iv"] for s in res["scenario_dcfs"] if s["name"] == "Base")


BASE_A = _base_of(A_ANSWER)


# ---- the message, and when it fires ---------------------------------------------------------------------------------------------

def test_stage_b_fires_once_after_the_memorandum_with_the_briefs_text(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(A_ANSWER), _turn(MEMO), _turn("KEEP")])       # a fourth request would fail the loop
    rep, _, meta = _run(tmp_path)
    assert 104 < BASE_A < 105 and meta["base_iv_stage_a"] == BASE_A == meta["base_iv_final"]
    assert _reveal_message(bodies[1]) is None and _reveal_message(bodies[2]) == reveal_text(BASE_A)
    assert bodies[2]["messages"][-1] == {"role": "user", "content": reveal_text(BASE_A)}
    assert bodies[2]["messages"][-2] == {"role": "assistant", "content": MEMO}        # the memorandum it follows
    assert _tool_names(bodies[2]) == ["run_financial_model"]                          # only the desk is open
    desk = next(t for t in bodies[2]["tools"] if t["function"]["name"] == "run_financial_model")
    assert "reference_revision" in desk["function"]["parameters"]["properties"]       # accepted only now
    assert all("reference_revision" not in t["function"]["parameters"]["properties"] for t in bodies[0]["tools"]
               if t["function"]["name"] == "run_financial_model")                     # not in stage A
    assert rep == MEMO and len(bodies) == 3
    assert meta["reference_revision"] == {"fired": True, "outcome": "keep", "guard_failed": None, "changed_inputs": [], "toward_civ": None,
                                          "civ": CIV, "base_over_civ_a": round(BASE_A / CIV, 3), "base_over_civ_final": round(BASE_A / CIV, 3)}
    assert [t.get("stage_b") for t in meta["turns"]] == [None, None, True]
    saved = (tmp_path / "_reference_reveal.md").read_text(encoding="utf-8")            # the full stage-B reply in the run folder
    assert reveal_text(BASE_A) in saved and "### Text\n\nKEEP\n" in saved and '"outcome": "keep"' in saved


def test_the_message_names_the_inputs_the_pack_line_held_after_its_value_clause():
    assert at.reference_reveal_inputs(LINE) == INPUTS
    assert at.reference_reveal_inputs("- CONSENSUS-IMPLIED VALUE: not meaningful — x") == "CONSENSUS-IMPLIED VALUE: not meaningful — x"
    assert at.reference_reveal_message(1234.5, "i", 99.0).startswith(
        "For comparison only: the CONSENSUS-IMPLIED VALUE (what Wall Street's forecasts imply through a fixed formula) is $1,234.50 per share; "
        "its inputs: i. Your Base is $99.00.")


@pytest.mark.parametrize("status,civ", [("not_available", None), ("not_meaningful", None), ("outside_fence_above", 460.0)])
def test_it_never_fires_without_a_reference_in_force_and_the_record_says_not_available(monkeypatch, tmp_path, status, civ):
    bodies = _serve(monkeypatch, [_desk(A_ANSWER), _turn(MEMO)])                       # a reveal request would fail the loop
    rep, _, meta = _run(tmp_path, reveal={"civ": civ, "status": status, "line": "- x"})
    assert rep == MEMO and len(bodies) == 2
    assert meta["reference_revision"]["fired"] is False and meta["reference_revision"]["outcome"] == "not_available"
    assert meta["base_iv_stage_a"] == meta["base_iv_final"] == BASE_A


def test_it_never_fires_on_an_older_pack(monkeypatch, tmp_path):
    _serve(monkeypatch, [_desk(A_ANSWER), _turn(MEMO)])
    rep, _, meta = _run(tmp_path, reveal=None)
    assert rep == MEMO and meta["reference_revision"]["fired"] is False and meta["reference_revision"]["outcome"] is None


def test_it_never_fires_on_a_stub(monkeypatch, tmp_path):
    # the memorandum is a stub: the forced-report turn delivers it, and no reveal follows
    bodies = _serve(monkeypatch, [_desk(A_ANSWER), _turn("ok"), _turn(MEMO)])
    rep, _, meta = _run(tmp_path)
    assert rep == MEMO and len(bodies) == 3 and _reveal_message(bodies[2]) is None
    assert meta["reference_revision"] == at.reference_revision_not_fired(REVEAL)
    assert meta["reference_revision"]["fired"] is False and meta["reference_revision"]["outcome"] is None


def test_it_never_fires_after_a_server_error(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(A_ANSWER), _turn(MEMO, done="server_error")])
    rep, _, meta = _run(tmp_path)
    assert all(_reveal_message(b) is None for b in bodies)
    assert meta["reference_revision"]["fired"] is False and meta["reference_revision"]["outcome"] is None


def test_it_never_fires_on_a_failed_sample(monkeypatch, tmp_path):
    # the memorandum is a stub and the forced report too: the sample fails (report_not_delivered) and no reveal follows
    bodies = _serve(monkeypatch, [_desk(A_ANSWER), _turn("ok"), _turn("ok")])
    rep, _, meta = _run(tmp_path)
    assert meta["failure"] == "report_not_delivered" and len(bodies) == 3 and all(_reveal_message(b) is None for b in bodies)
    assert meta["reference_revision"]["fired"] is False and meta["reference_revision"]["outcome"] is None


def test_the_crux_follow_up_still_works_and_runs_before_stage_b(monkeypatch, tmp_path):
    no_crux = _happy_params(**_ALL_REASONS_GIVEN)                                      # directional, no crux: the follow-up fires first
    bodies = _serve(monkeypatch, [_desk(no_crux), _turn(MEMO), _desk(dict(copy.deepcopy(no_crux), crux=crux())), _turn(MEMO2), _turn("KEEP")])
    rep, _, meta = _run(tmp_path)
    fu = next(m["content"] for m in bodies[2]["messages"] if m["role"] == "user" and "your answer run passed no crux" in m["content"])
    assert fu == followup_text(BASE_A, PRICE, "above") and _reveal_message(bodies[2]) is None
    assert _reveal_message(bodies[4]) == reveal_text(BASE_A)                          # after the follow-up's memorandum
    assert bodies[4]["messages"][-2] == {"role": "assistant", "content": MEMO2}
    assert meta["crux_followup"] == {"fired": True, "outcome": "crux_added"}
    assert meta["reference_revision"]["outcome"] == "keep" and rep == MEMO2
    assert contract_fill.answer_run(_snap(tmp_path)["calls"])[0]["call_index"] == 2    # the follow-up's run stays the answer run


def test_a_bare_hold_to_the_crux_follow_up_leaves_the_first_memorandum_as_stage_a(monkeypatch, tmp_path):
    no_crux = _happy_params(**_ALL_REASONS_GIVEN)
    bodies = _serve(monkeypatch, [_desk(no_crux), _turn(MEMO), _turn("HOLD"), _turn("KEEP")])
    rep, _, meta = _run(tmp_path)
    assert _reveal_message(bodies[3]) == reveal_text(BASE_A) and rep == MEMO
    assert meta["crux_followup"]["outcome"] == "hold_confirmed" and meta["reference_revision"]["outcome"] == "keep"


# ---- desk support ----------------------------------------------------------------------------------------------------------

def test_the_desk_refuses_reference_revision_in_stage_a():
    p = dict(copy.deepcopy(A_ANSWER), reference_revision=[entry("Base.wacc", 0.08, 0.0825)])
    res = fmt.execute_financial_model(p, context=_ctx(price=PRICE, reference_withheld=True))
    assert res["validation_error"] is True and res["reference_revision_refused"] == "not_stage_b"
    assert res["error"].startswith("Not accepted as a desk run; it does not use one of your desk runs. reference_revision is accepted only")


def test_the_desk_refuses_an_unlisted_change_in_stage_b():
    ctx = _ctx(price=PRICE, reference_withheld=True, reference_revision_inputs=copy.deepcopy(A_ANSWER))
    p = revised({("Base", "wacc"): 0.0825, ("Base", "base_cf"): 5.1}, [entry("Base.wacc", 0.08, 0.0825)])
    res = fmt.execute_financial_model(p, context=ctx)
    assert res["validation_error"] is True and res["reference_revision_unlisted"] == ["Base.base_cf"]
    assert "not listed: Base.base_cf" in res["error"] and "reply KEEP without calling the desk" in res["error"]
    ok = fmt.execute_financial_model(revised({("Base", "wacc"): 0.0825}, [entry("base.WACC", 0.08, 0.0825)]), context=ctx)
    assert "error" not in ok                                                            # listed (the name's case does not matter)


def test_one_extra_desk_run_when_the_desk_was_used_up_and_then_the_desk_closes(monkeypatch, tmp_path):
    p = revised({("Base", "wacc"): 0.0825}, [entry("Base.wacc", 0.08, 0.0825)])
    bodies = _serve(monkeypatch, [_desk(A_ANSWER), _turn(MEMO), _desk(p), _turn("Revised.")])
    _, _, meta = _run(tmp_path, max_model_calls=1)
    runs = [c for c in _snap(tmp_path)["calls"] if c["tool"] == "run_financial_model"]
    assert len(runs) == 2 and "error" not in runs[1] and "desk_closed" in runs[1]
    assert _tool_names(bodies[3]) == []                                                 # one stage-B run, then no tool
    assert meta["reference_revision"]["outcome"] == "revised_accepted"


# ---- the guardrails, each with a fake model transcript ----------------------------------------------------------------------

def _stage_b(monkeypatch, tmp_path, reply_turns):
    bodies = _serve(monkeypatch, [_desk(A_ANSWER), _turn(MEMO)] + reply_turns)
    rep, _, meta = _run(tmp_path)
    snap = _snap(tmp_path)["calls"]
    return rep, meta, snap, bodies


def test_g_accepted_a_new_cited_input_becomes_the_answer_run(monkeypatch, tmp_path):
    p = revised({("Base", "wacc"): 0.0825}, [entry("Base.wacc", 0.08, 0.0825)])
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [_desk(p), _turn(MEMO2)])
    rr = meta["reference_revision"]
    base_b = _base_of(p)
    assert rr["outcome"] == "revised_accepted" and rr["guard_failed"] is None and rr["changed_inputs"] == ["Base.wacc"]
    assert rr["toward_civ"] is True and rr["base_over_civ_final"] == round(base_b / CIV, 3) and base_b < BASE_A
    assert meta["base_iv_stage_a"] == BASE_A and meta["base_iv_final"] == base_b
    call, base, _ = contract_fill.answer_run(snap)
    assert call["call_index"] == 2 and base == base_b and "reference_revision_rejected" not in call
    assert rep == MEMO2                                                                # its reply is itself a memorandum


def test_g_accepted_with_a_short_reply_keeps_the_stage_a_memorandum_text(monkeypatch, tmp_path):
    p = revised({("Base", "wacc"): 0.0825}, [entry("Base.wacc", 0.08, 0.0825)])
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [_desk(p), _turn("Revised as cited.")])
    assert meta["reference_revision"]["outcome"] == "revised_accepted" and rep == MEMO
    assert contract_fill.answer_run(snap)[0]["call_index"] == 2                         # the values are the revised run's


def _assert_rejected(meta, snap, rep, guard):
    rr = meta["reference_revision"]
    assert rr["outcome"] == "revised_rejected" and rr["guard_failed"] == at.REFERENCE_REVISION_GUARDS[guard]
    call, base, _ = contract_fill.answer_run(snap)
    assert call["call_index"] == 1 and base == BASE_A == meta["base_iv_final"]          # stage A's answer run stands
    rejected = [c for c in snap if c.get("reference_revision_rejected")]
    assert rep == MEMO
    return rr, rejected


def test_g1_rejected_for_no_verified_citation(monkeypatch, tmp_path):
    p = revised({("Base", "wacc"): 0.0825}, [entry("Base.wacc", 0.08, 0.0825, source="PRIMARY P9")])
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [_desk(p), _turn("Revised.")])
    rr, rejected = _assert_rejected(meta, snap, rep, "G1")
    assert [c["call_index"] for c in rejected] == [2] and rejected[0]["reference_revision_rejected"] == "reference_revision_citation_unverified"
    # a quote the source does not hold, and a quote too short to be evidence, fail it too
    clean = {k: v for k, v in snap[1].items() if k != "reference_revision_rejected"}
    for bad in (entry("Base.wacc", 0.08, 0.0825, quote="ACME reports third quarter 2026 results."),
                entry("Base.wacc", 0.08, 0.0825, quote="Orders grew 100 percent.")):
        rec, _ = at.reference_revision_outcome([dict(clean, params=dict(clean["params"], reference_revision=[bad]))], "", BASE_A, CIV,
                                               A_ANSWER, PACK, snap, {"company": "Acme", "ticker": "ACME"}, at.stage_a_corpus(snap[:1], [MEMO]))
        assert rec["guard_failed"] == "reference_revision_citation_unverified"


def test_g2_rejected_for_a_quote_stage_a_already_used(monkeypatch, tmp_path):
    p = revised({("Base", "wacc"): 0.0825}, [entry("Base.wacc", 0.08, 0.0825, quote=BASE_QUOTE)])      # stage A's crux quoted it
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [_desk(p), _turn("Revised.")])
    _assert_rejected(meta, snap, rep, "G2")
    # a quote stage A's memorandum carried is not new either
    p2 = revised({("Base", "wacc"): 0.0825}, [entry("Base.wacc", 0.08, 0.0825)])
    call2 = dict({k: v for k, v in snap[1].items() if k != "reference_revision_rejected"}, params=p2)
    rec, _ = at.reference_revision_outcome([call2], "", BASE_A, CIV, A_ANSWER, PACK, snap, {"company": "Acme", "ticker": "ACME"},
                                           at.stage_a_corpus([], ["memo text ... " + NEW_QUOTE]))
    assert rec["guard_failed"] == "reference_revision_quote_not_new"


def test_g3_a_toward_civ_move_over_10pct_with_one_uncited_input_is_rejected(monkeypatch, tmp_path):
    changes = {("Base", "wacc"): 0.085, ("Base", "base_cf"): 4.9}
    p = revised(changes, [entry("Base.wacc", 0.08, 0.085), entry("Base.base_cf", 5.0, 4.9, source="PRIMARY P9")])
    base_b = _base_of(p)
    move = abs(base_b - BASE_A) / BASE_A
    assert 0.10 < move < 0.25 and (base_b - BASE_A) * (CIV - BASE_A) > 0               # toward the CIV, by more than 10% and less than 25%
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [_desk(p), _turn("Revised.")])
    rr, _ = _assert_rejected(meta, snap, rep, "G3")
    assert rr["toward_civ"] is True and rr["changed_inputs"] == ["Base.base_cf", "Base.wacc"]


def test_g4_a_revision_over_25pct_is_rejected_and_the_name_is_flagged_for_a_rerun(monkeypatch, tmp_path):
    # the Bear moves with the Base so that Bear <= Base <= Bull still holds (the desk refuses any other order)
    p = revised({("Base", "wacc"): 0.11, ("Bear", "wacc"): 0.12},
                [entry("Base.wacc", 0.08, 0.11), entry("Bear.wacc", 0.10, 0.12, quote=NEW_QUOTE_2)])
    base_b = _base_of(p)
    assert abs(base_b - BASE_A) / BASE_A > 0.25
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [_desk(p), _turn("Revised.")])
    rr, _ = _assert_rejected(meta, snap, rep, "G4")
    assert rr["guard_failed"] == "reference_revision_too_large" and rr["base_over_civ_final"] == round(base_b / CIV, 3)


def test_g4_holds_either_way_an_upward_move_over_25pct_too(monkeypatch, tmp_path):
    p = revised({("Base", "wacc"): 0.068, ("Bull", "wacc"): 0.06},
                [entry("Base.wacc", 0.08, 0.068), entry("Bull.wacc", 0.075, 0.06, quote=NEW_QUOTE_2)])
    assert (_base_of(p) - BASE_A) / BASE_A > 0.25
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [_desk(p), _turn("Revised.")])
    rr, _ = _assert_rejected(meta, snap, rep, "G4")
    assert rr["toward_civ"] is False


@pytest.mark.parametrize("reply", [
    [_turn("My valuation should be $120 because the reference is higher.")],                 # prose arguing a new number
    [_desk(revised({("Base", "wacc"): 0.0825}, None)), _turn("Revised.")],                   # a missing list (refused: the change is unlisted)
    [_desk(copy.deepcopy(A_ANSWER)), _turn("Same inputs.")],                                 # a run with no list and no change
    [_desk(revised({}, [entry("Base.wacc", 0.08, 0.08)])), _turn("Listed, unchanged.")],     # a list that changes nothing
    [_desk(revised({("Base", "wacc"): 0.0825}, [{"input": "Base.wacc", "new": "0.0825"}])), _turn("x")],   # an entry without old or citation
])
def test_g5_malformed_means_stage_a_stands(monkeypatch, tmp_path, reply):
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, reply)
    rr = meta["reference_revision"]
    assert rr["outcome"] == "revised_rejected" and rr["guard_failed"] == "reference_revision_malformed"
    assert contract_fill.answer_run(snap)[0]["call_index"] == 1 and meta["base_iv_final"] == BASE_A and rep == MEMO


def test_g5_two_accepted_stage_b_runs_are_malformed():
    p = revised({("Base", "wacc"): 0.0825}, [entry("Base.wacc", 0.08, 0.0825)])
    done = fmt.execute_financial_model(copy.deepcopy(p), context=_ctx(price=PRICE, reference_withheld=True,
                                                                     reference_revision_inputs=copy.deepcopy(A_ANSWER)))
    two = [{"tool": "run_financial_model", "call_index": i, "params": p, **done} for i in (2, 3)]
    rec, call = at.reference_revision_outcome(two, "", BASE_A, CIV, A_ANSWER, PACK, two, {"company": "Acme", "ticker": "ACME"}, "")
    assert rec["guard_failed"] == "reference_revision_malformed" and call["call_index"] == 3


def test_a_second_stage_b_call_is_closed_by_the_desk(monkeypatch, tmp_path):
    p = revised({("Base", "wacc"): 0.0825}, [entry("Base.wacc", 0.08, 0.0825)])
    rep, meta, snap, bodies = _stage_b(monkeypatch, tmp_path, [_desk(p), _turn("Revised.")])
    assert _tool_names(bodies[3]) == []                                                 # no second desk call is offered


@pytest.mark.parametrize("reply", ["KEEP", "**KEEP** - my valuation stands.", "keep"])
def test_keep_keeps(monkeypatch, tmp_path, reply):
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [_turn(reply)])
    assert meta["reference_revision"]["outcome"] == "keep" and rep == MEMO and meta["base_iv_final"] == BASE_A


def test_a_refused_stage_b_call_then_keep_keeps(monkeypatch, tmp_path):
    p = revised({("Base", "wacc"): 0.0825, ("Base", "base_cf"): 5.1}, [entry("Base.wacc", 0.08, 0.0825)])      # Base.base_cf unlisted
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [_desk(p), _turn("KEEP")])
    assert snap[1]["reference_revision_unlisted"] == ["Base.base_cf"] and meta["reference_revision"]["outcome"] == "keep"


def test_a_server_error_in_stage_b_leaves_stage_a_standing(monkeypatch, tmp_path):
    import urllib.error
    err = urllib.error.HTTPError("http://x", 500, "boom", {}, None)
    rep, meta, snap, _ = _stage_b(monkeypatch, tmp_path, [err])
    # the error is a reply with no content: the end of stage B with no run to judge; stage A stands and the sample is not failed
    assert rep == MEMO and meta["failure"] is None and meta["reference_revision"]["fired"] is True
    assert meta["reference_revision"]["outcome"] is None and meta["base_iv_final"] == BASE_A


def test_a_second_server_error_of_the_session_in_stage_b_does_not_fail_the_sample(monkeypatch, tmp_path):
    import urllib.error
    err = urllib.error.HTTPError("http://x", 500, "boom", {}, None)
    # the first error is stage A's first turn (the window retry absorbs it); the second is stage B's
    bodies = _serve(monkeypatch, [err, _desk(A_ANSWER), _turn(MEMO), err])
    rep, _, meta = _run(tmp_path)
    assert _reveal_message(bodies[3]) == reveal_text(BASE_A)
    assert rep == MEMO and meta["failure"] is None and meta["reference_revision"]["outcome"] is None


# ---- the record reaches the verdict row -------------------------------------------------------------------------------------

def test_the_record_fields_are_whitelisted_and_reach_the_verdict_row():
    import depth_pipeline as dp
    card = cv.extract_scorecard("no contract", 50.0)
    assert {"base_iv_stage_a", "base_iv_final", "reference_revision"} <= set(card)
    rr = {"fired": True, "outcome": "revised_accepted", "guard_failed": None, "changed_inputs": ["Base.wacc"], "toward_civ": True, "civ": 100.0,
          "base_over_civ_a": 1.043, "base_over_civ_final": 1.0}
    sc = {"base_iv": 100.0, "bull_iv": 130.0, "bear_iv": 60.0, "base_probability": 0.34, "bull_probability": 0.33, "bear_probability": 0.33,
          "conviction_score": 8.0, "business_quality_moat": 3.0, "desk_calls": 2, "desk_iv_match": True,
          "base_iv_stage_a": 104.26, "base_iv_final": 100.0, "reference_revision": rr}
    runs = [{"sample": 1, "iv": 100.0, "scorecard": sc, "plausible": True, "flags": [], "basis": True}]
    card, summary = cv.select_medoid_scorecard(runs, 50.0, 25.0)
    assert summary["base_iv_stage_a"] == 104.26 and summary["base_iv_final"] == 100.0 and summary["reference_revision"] == rr
    v = dp.band_verdict({"ticker": "ACME", "price": 50.0, "runs": runs, "scorecard": summary, "median_iv": 100.0, "spread_pct": 0.0})
    assert v["base_iv_stage_a"] == 104.26 and v["base_iv_final"] == 100.0 and v["reference_revision"] == rr


def test_the_run_record_carries_stage_b_through_consensus_valuation_main(monkeypatch, tmp_path):
    """cv.main() on one frozen withheld-reference pack (its sidecar holds the CIV), mocked model: stage B fires, the reply is KEEP, and the sample's
    scorecard carries the record and both Bases; the reveal is built from the sidecar, never the text."""
    import pack_facts
    import test_review_fixes_2 as r2
    from test_desk_continuation import _main_run
    facts = dict(pack_facts.empty(), reference_withheld=True, consensus_implied_value=380.0, reference_status="used",
                 reference_line="- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $380.00 per share, x | base: owner earnings 1.000")
    pack_facts.write_sidecar(tmp_path, facts)
    run = _main_run(monkeypatch, tmp_path, [_desk({"price": 400.0}), _turn(r2.MEMO), _turn("KEEP")])
    sc = run["scorecard"]
    assert sc["reference_revision"]["fired"] is True and sc["reference_revision"]["outcome"] == "keep" and sc["reference_revision"]["civ"] == 380.0
    assert sc["base_iv_stage_a"] == sc["base_iv_final"] == 409.92 == sc["base_iv"]
    d = sorted((tmp_path / "cons").glob("ZZSIM_*"))[-1]
    saved = (d / "sample1_research" / "_reference_reveal.md").read_text(encoding="utf-8")
    assert "is $380.00 per share; its inputs: base: owner earnings 1.000. Your Base is $409.92." in saved


def test_the_g4_flag_rides_on_the_sample(monkeypatch, tmp_path):
    """A rejected over-25% revision flags the sample `reference_revision_too_large` (flagged for a re-run, not patched)."""
    import pack_facts
    import test_review_fixes_2 as r2
    from test_desk_continuation import _main_run
    facts = dict(pack_facts.empty(), reference_withheld=True, consensus_implied_value=380.0, reference_status="used", reference_line="- x | y")
    pack_facts.write_sidecar(tmp_path, facts)
    big = {"scenario_dcfs": [{"name": n, "dcf": {"per_share_iv": iv}} for n, iv in (("Base", 200.0), ("Bull", 260.0), ("Bear", 150.0))]}
    served = iter([r2.DESK_OK, big])
    monkeypatch.setattr(at, "dispatch_tool", lambda name, args, **kw: next(served))
    revision = {"price": 400.0, "base_cf": 2.0, "reference_revision": [entry("base_cf", None, 2.0)]}
    queue = [_desk({"price": 400.0}), _turn(r2.MEMO), _desk(revision), _turn("Revised.")]
    import urllib.request
    from test_desk_continuation import _Resp
    fake = lambda req, timeout=None: _Resp(queue.pop(0))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr(at.urllib.request, "urlopen", fake)
    pack = tmp_path / "_sim_pack.md"
    pack.write_text("SIM PACK\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "ZZSIM", "--tools", "--samples", "1", "--pack-file", str(pack), "--out-dir",
                                      str(tmp_path / "cons"), "--price", "400", "--no-research", "--think", "high"])
    cv.main()
    d = sorted((tmp_path / "cons").glob("ZZSIM_*"))[-1]
    run = json.loads((d / "consensus.json").read_text(encoding="utf-8"))["runs"][0]
    assert run["scorecard"]["reference_revision"]["guard_failed"] == "reference_revision_too_large"
    assert "reference_revision_too_large" in run["flags"] and run["scorecard"]["base_iv"] == 409.92 == run["scorecard"]["base_iv_final"]
