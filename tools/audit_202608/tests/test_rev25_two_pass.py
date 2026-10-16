"""Revision 25, Stages 0.6 and 0.7: the two-pass protocol (arms r25_b and r25_c) and the memorandum merge after a crux follow-up.

Every session here is the real loop with a mocked `urlopen` (no network, no model). The tests:
  - the gate: pass 2 cannot open without a complete pass-1 run, and the sample is stamped as a breach;
  - the arms differ only by the consensus block in the pass-2 message, byte for byte;
  - arm C's pass-1 pack holds none of the withheld elements (the values are searched for, not only the headers);
  - the change log is computed from the desk inputs, with no model text involved;
  - the memorandum merge keeps a section answered "unchanged from prior" and replaces one given real content;
  - the other arms' prompts are unchanged.
"""
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyst_tools as at  # noqa: E402
import capability_test as cap  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import contract_fill  # noqa: E402
from test_desk_continuation import MEMO, MEMO2, OK, _desk, _run, _serve, _snap, _turn  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN, _happy_params  # noqa: E402

FIX = Path(__file__).parent / "fixture_data" / "rev24"
BLOCK = cap.split_consensus((FIX / "AMD_data8_defaults.md").read_text(encoding="utf-8"))[1]


@pytest.fixture(autouse=True)
def _no_crux_followup(monkeypatch):
    """These sessions script every model turn and their desk runs are directional with no crux, which earns the one crux follow-up
    (tests/test_rev21_followup.py); the merge tests turn it on themselves."""
    monkeypatch.setattr(at, "crux_followup_state", lambda *a, **k: None)


def _changed(**kw):
    """OK with the Base's growth changed (a different input in pass 2)."""
    p = copy.deepcopy(OK)
    for sc in p["scenarios"]:
        if sc["name"] == "Base":
            sc.update(kw)
    return p


def _two_pass_session(monkeypatch, tmp_path, arm, block=None):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(_changed(explicit_growth=[0.05] * 5)), _turn(MEMO2)])
    rep, _t, meta = _run(tmp_path, two_pass={"arm": arm, "withheld_block": block})
    return bodies, rep, meta


# ---- the gate ----------------------------------------------------------------------------------------------------

def test_pass_2_does_not_open_without_a_complete_pass_1_run_and_the_breach_is_stamped(monkeypatch, tmp_path):
    # a memorandum and no desk call: the desk continuation (C8) gives one more turn, which is again no desk call
    bodies = _serve(monkeypatch, [_turn(MEMO), _turn(MEMO2)])
    rep, _t, meta = _run(tmp_path, two_pass={"arm": "r25_b", "withheld_block": None})
    assert meta["two_pass"]["pass2_opened"] is False
    assert meta["two_pass"]["breach"] == at.TWO_PASS_BREACH == "two_pass_breach:no_pass1"
    assert meta["failure"] == "two_pass_breach:no_pass1"
    for b in bodies:                                                    # the pass-2 message was never sent
        assert not any(m["role"] == "user" and (m["content"] or "").startswith(at.TWO_PASS_MESSAGE) for m in b["messages"])
    assert at.two_pass_may_open([]) is False


def test_the_gate_reads_pass_1_runs_only():
    done = {"tool": "run_financial_model", "params": {}, "result": {}}
    # a complete run that belongs to pass 2 does not open pass 2
    snap = [dict(done, **{"pass": 2})]
    assert at.two_pass_may_open(snap) is False


def test_a_two_pass_session_without_a_desk_or_with_the_wrong_arm_is_refused(monkeypatch, tmp_path):
    _serve(monkeypatch, [])
    with pytest.raises(ValueError):
        _run(tmp_path / "a", two_pass={"arm": "iii_p50", "withheld_block": None})
    with pytest.raises(ValueError):
        _run(tmp_path / "b", two_pass={"arm": "r25_c", "withheld_block": None})          # arm C needs its block
    with pytest.raises(ValueError):
        _run(tmp_path / "c", two_pass={"arm": "r25_b", "withheld_block": BLOCK})         # arm B has none
    with pytest.raises(ValueError):
        _run(tmp_path / "d", two_pass={"arm": "r25_b", "withheld_block": None}, max_model_calls=0)


def test_pass_2_opens_after_a_complete_run_and_every_call_carries_its_pass(monkeypatch, tmp_path):
    bodies, rep, meta = _two_pass_session(monkeypatch, tmp_path, "r25_b")
    assert meta["two_pass"]["pass2_opened"] is True and meta["two_pass"]["breach"] is None and meta["failure"] is None
    snap = _snap(tmp_path)["calls"]
    assert [c["pass"] for c in snap if c["tool"] == "run_financial_model"] == [1, 2]
    assert meta["two_pass"]["pass1_call_index"] == snap[0]["call_index"]
    assert [t["pass"] for t in meta["turns"]] == [1, 1, 2, 2]
    assert meta["turns"][2]["pass2_first_turn"] is True
    assert rep == MEMO2


def test_a_desk_used_up_in_pass_1_still_gives_pass_2_one_run(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(_changed(explicit_growth=[0.04] * 5)), _turn(MEMO2)])
    _run(tmp_path, two_pass={"arm": "r25_b", "withheld_block": None}, max_model_calls=1)
    names = [t["function"]["name"] for t in bodies[2].get("tools") or []]
    assert "run_financial_model" in names                                # open in pass 2, though the one run was used in pass 1


# ---- the arms differ only by the consensus block ----------------------------------------------------------------

def test_the_pass_2_messages_of_the_two_arms_differ_only_by_the_consensus_block(monkeypatch, tmp_path):
    bodies_b, _r, _m = _two_pass_session(monkeypatch, tmp_path / "b", "r25_b")
    bodies_c, _r, _m = _two_pass_session(monkeypatch, tmp_path / "c", "r25_c", BLOCK)
    msg_b = bodies_b[2]["messages"][-1]
    msg_c = bodies_c[2]["messages"][-1]
    assert msg_b == {"role": "user", "content": "Pass 2: reconcile your preliminary forecast with everything in the pack."}
    assert msg_c["role"] == "user" and msg_c["content"].encode() == (msg_b["content"] + "\n\n" + BLOCK).encode()
    assert msg_c["content"].replace("\n\n" + BLOCK, "") == msg_b["content"]
    # everything else sent to the model in pass 2 is the same: the history before the message (except the pass-1 desk result, which arm C's desk
    # computed without the consensus-derived members: ruling 3), the options, the tools
    nontool = lambda ms: [m for m in ms if m["role"] != "tool"]                      # noqa: E731
    assert nontool(bodies_b[2]["messages"][:-1]) == nontool(bodies_c[2]["messages"][:-1])
    assert bodies_b[2]["options"] == bodies_c[2]["options"] and bodies_b[2].get("tools") == bodies_c[2].get("tools")
    # and so is the first request of pass 1 (nothing of the desk has been seen yet)
    assert bodies_b[0] == bodies_c[0]


def test_meta_records_whether_consensus_was_shown_in_pass_1(monkeypatch, tmp_path):
    _b, _r, meta_b = _two_pass_session(monkeypatch, tmp_path / "b", "r25_b")
    _b, _r, meta_c = _two_pass_session(monkeypatch, tmp_path / "c", "r25_c", BLOCK)
    assert meta_b["two_pass"]["consensus_shown_pass1"] is True and meta_b["two_pass"]["arm"] == "r25_b"
    assert meta_c["two_pass"]["consensus_shown_pass1"] is False and meta_c["two_pass"]["arm"] == "r25_c"
    assert cv.two_pass_setup({"pilot_arm": "r25_c"}, BLOCK) == {"arm": "r25_c", "withheld_block": BLOCK}
    assert cv.two_pass_setup({"pilot_arm": "r25_b"}, BLOCK) == {"arm": "r25_b", "withheld_block": None}
    for arm in (None, "rev22", "iii_p50", "iii_no_p50"):
        assert cv.two_pass_setup({"pilot_arm": arm}, BLOCK) is None


# ---- the withheld elements ---------------------------------------------------------------------------------------

def _fixture(t="AMD"):
    """(text, facts) of a saved name's DATA 8 and DEFAULTS as a revision-24 or later pack prints them (the production DEFAULTS renderer on the facts)."""
    from test_rev24_stage_a_pack import _saved, rebuild_rev24
    facts, excerpt = _saved(t)
    return rebuild_rev24(excerpt, facts)


@pytest.mark.parametrize("t", ["AMD", "HRTG", "KSS"])
def test_no_withheld_number_of_the_facts_survives_in_the_pass_1_pack(t):
    text, facts = _fixture(t)
    p1, block, elements = cap.split_consensus(text)
    assert elements
    lv = facts.get("levels") or {}
    for k in ("year1", "year2", "bull2", "bear2"):
        if isinstance(lv.get(k), (int, float)):
            assert f"{lv[k]:.3f}" not in p1, (t, k)
            assert f"{lv[k]:.3f}" in block
    lr = facts.get("long_run") or {}
    for k in ("e5", "oe5"):
        if isinstance(lr.get(k), (int, float)):
            assert f"{lr[k]:.6f}" not in p1, (t, k)
    if isinstance(facts.get("next_fy_revenue_growth"), (int, float)):
        assert f"{facts['next_fy_revenue_growth'] * 100:+.1f}%" not in p1
    assert "year1=" not in p1 and "- next_fy_revenue_growth:" not in p1.replace("- DEFAULTS next_fy_revenue_growth:", "")
    assert "e5=withheld_until_pass_2" in p1 or lr.get("e5") is None


def test_arm_c_pass_1_pack_holds_none_of_the_withheld_values():
    text, facts = _fixture()
    p1, block, elements = cap.split_consensus(text)
    must_go = [
        "$88.235B", "$50.941B", "$61.257B", "$118.112B", "$48.339B", "+47.1%", "+73.2%", "+81.7%", "+105.7%",   # the table
        "$15.58", "$9.60", "$20.25", "$7.58",                                                                   # EPS
        "$4.17",                                                                                                # the base-year check's year-ago EPS
        "$15.33", "$13.92", "$13.18", "+18.3% in 90 days",                                                      # the estimate trend
        "3 up / 1 down", "1 up / 0 down",                                                                       # the revisions
        "619.51", "616.0", "1250.0", "365.0",                                                                   # the street targets
        "year1=10.452", "21.496", "27.934", "13.243",                                                           # levels
        "52.716357", "48.867917", "26.2812%",                                                                   # long_run e5, oe5, m5
    ]
    for v in must_go:
        assert v not in p1, v
        assert v in block, v
    # the facts' own numbers, as DEFAULTS prints them
    for k in ("year1", "year2", "bull2", "bear2"):
        assert f"{facts['levels'][k]:.3f}" not in p1
    assert f"{facts['long_run']['e5']:.6f}" not in p1 and f"{facts['long_run']['oe5']:.6f}" not in p1
    # everything else is the pack's, line for line: filed facts, guidance, the rest of long_run, the other DEFAULTS
    kept_lines = p1.split("\n")
    for ln in text.split("\n"):
        if ln in kept_lines:
            continue
        assert any(e["text"].find(ln) >= 0 for e in elements) or ln.startswith("- long_run:") or ln.startswith("- levels:") \
            or ln.startswith("- next_fy_revenue_growth:") or ln.startswith("- Trailing P/E:"), ln[:80]
    for needle in ("m_tc=15.0000%", "r_tc=55.4197%", "owner_earnings_default_b: 7.148", "reference_base_b: 5.752244", "years35_p90: 30.1%",
                   "- 52-week range", "Trailing P/E"):
        if needle in text:
            assert needle in p1, needle
    assert {e["element"] for e in elements} >= {"DATA 8 consensus estimates table", "DATA 8 analyst price targets", "DEFAULTS levels",
                                                "DEFAULTS next_fy_revenue_growth", "DEFAULTS long_run members e5, oe5, m5"}
    assert all(e["source_line"] >= 1 and e["section"] for e in elements)


def test_the_split_is_a_no_op_on_a_pack_without_estimates_and_the_block_is_verbatim():
    plain = "## DATA 8 - CONSENSUS & MULTIPLES   [x]\n- CONSENSUS ESTIMATES: not available — stale (> 45 days)\n- 52-week range: 1 - 2\n"
    p1, block, elements = cap.split_consensus(plain)
    assert (p1, block, elements) == (plain, "", [])
    text, _f = _fixture()
    _p, block, elements = cap.split_consensus(text)
    for e in elements:
        for ln in e["text"].split("\n"):
            assert ln in block


def test_a_real_pack_of_arm_c_splits_and_the_facts_sidecar_is_whole(screener_data_stub, monkeypatch):
    import rs2_data
    from test_consensus_reference import AMD_EST
    orig = rs2_data.load_json
    en = {"_ticker": "GEV", "_fetched_at": "2026-09-24T12:00:00", "estimates": AMD_EST}
    monkeypatch.setattr(rs2_data, "load_json", lambda p: en if str(p).endswith("GEV.json") and "enrich" in str(p) else orig(p))
    built = cap.build_pack("GEV", pilot_arm="r25_c")
    p1, block, elements = cap.split_consensus(built)
    assert elements
    assert "$15.57" not in p1 and "$15.57" in block               # next-FY EPS of the fixture's DATA 8 table
    assert "CONSENSUS ESTIMATES   [yfinance" not in p1
    assert p1.splitlines()[0].endswith("(pack revision 25)")
    assert built.facts["next_fy_revenue_growth"] is not None      # the facts keep their values (the desk reads them)


# ---- the change log ----------------------------------------------------------------------------------------------

def test_the_change_log_is_computed_from_the_inputs_alone(monkeypatch, tmp_path):
    _b, rep, meta = _two_pass_session(monkeypatch, tmp_path, "r25_b")
    calls = _snap(tmp_path)["calls"]
    p1 = contract_fill.pass1_run(calls)
    assert p1["pass"] == 1 and p1["call_index"] == meta["two_pass"]["pass1_call_index"]
    log = contract_fill.change_log(contract_fill.run_inputs(p1), contract_fill.run_inputs(contract_fill.answer_run(calls)[0]))
    base_before = next(sc for sc in OK["scenarios"] if sc["name"] == "Base")["explicit_growth"]
    assert log == [{"input": "Base.explicit_growth", "pass1": base_before, "final": [0.05] * 5}]
    # no model text is read: reasons and the crux are not inputs, a changed reason changes nothing
    a, b = copy.deepcopy(p1), copy.deepcopy(p1)
    b["params"]["base_cf_reason"] = "a different reason entirely"
    b["params"]["crux"] = [{"input": "coe", "reason": "x", "citations": []}]
    assert contract_fill.change_log(contract_fill.run_inputs(a), contract_fill.run_inputs(b)) == []
    # the model's memo text is not an argument of any of these functions
    import inspect
    for fn in (contract_fill.run_inputs, contract_fill.change_log, contract_fill.pass1_run):
        assert not {"memo", "report", "text", "reasons"} & set(inspect.signature(fn).parameters)


def test_change_log_cases():
    f = contract_fill.change_log
    assert f({"a": 1}, {"a": 1.0}) == []                                   # 1 and 1.0 are the same input
    assert f({"a": 0.0}, {"a": None}) == [{"input": "a", "pass1": 0.0, "final": None}]      # 0.0 is a value
    assert f({"a": 1}, {}) == [{"input": "a", "pass1": 1, "final": None}]  # dropped
    assert f({}, {"b": [1, 2]}) == [{"input": "b", "pass1": None, "final": [1, 2]}]
    assert f({"a": True}, {"a": 1}) == [{"input": "a", "pass1": True, "final": 1}]        # a bool is not a number
    assert f({"l": [1, 2]}, {"l": [1, 3]}) == [{"input": "l", "pass1": [1, 2], "final": [1, 3]}]


def test_fill_gives_pass1_inputs_and_the_change_log_and_none_without_a_pass_1(monkeypatch, tmp_path):
    _two_pass_session(monkeypatch, tmp_path, "r25_b")
    calls = _snap(tmp_path)["calls"]
    facts = {"desk_schema": "25.1"}
    out = {}
    p1 = contract_fill.pass1_run(calls)
    assert "pass1_inputs" in contract_fill.FILLED_25 and "change_log" in contract_fill.FILLED_25
    assert "pass1_inputs" not in contract_fill.FILLED and "change_log" not in contract_fill.FILLED      # every other arm's fill is as it was
    # a sample whose calls carry no pass stamp (not the protocol) has no pass-1 run
    assert contract_fill.pass1_run([{k: v for k, v in c.items() if k != "pass"} for c in calls]) is None
    assert p1 is not None


# ---- the memorandum merge ----------------------------------------------------------------------------------------

def _memo(sections, contract=None, pre="MEMORANDUM\n"):
    body = pre + "".join(f"## SECTION {n} - {t}\n{txt}\n" for n, t, txt in sections)
    return body + (f"```json:underwriting\n{json.dumps(contract)}\n```\n" if contract is not None else "")


ANSWER = _memo([(0, "Verdict", "The verdict is HOLD. " + "a" * 400), (3, "Thesis", "The thesis in full. " + "b" * 400),
                (12, "Contract", "see the block " + "c" * 300)], contract={"x": 1, "y": 2})


def test_a_section_given_unchanged_from_prior_keeps_the_prior_section():
    reply = _memo([(0, "Verdict", "unchanged from prior"), (3, "Thesis", "Same as above.")], contract={"x": 1})
    merged, rec = at.merge_memo(ANSWER, reply)
    assert rec["sections"] == {"0": "kept", "3": "kept", "12": "kept"}
    assert "The verdict is HOLD." in merged and "The thesis in full." in merged and "unchanged" not in merged
    assert rec["contract"] == "answer" and '"y": 2' in merged             # the follow-up's contract lacks the answer's keys: not complete


def test_a_section_with_real_content_replaces_the_prior_one_and_a_complete_contract_is_taken():
    new3 = "The crux is the margin. " + "n" * 300
    reply = _memo([(0, "Verdict", "unchanged"), (3, "Thesis", new3)], contract={"x": 5, "y": 6, "z": 7})
    merged, rec = at.merge_memo(ANSWER, reply)
    assert rec["sections"]["3"] == "replaced" and rec["sections"]["0"] == "kept" and rec["sections"]["12"] == "kept"
    assert new3 in merged and "The thesis in full." not in merged and "The verdict is HOLD." in merged
    assert rec["contract"] == "followup" and '"z": 7' in merged and '"x": 1' not in merged
    assert merged.count("```json:underwriting") == 1


def test_placeholder_rule():
    ph = at.memo_section_is_placeholder
    assert ph("## SECTION 3 - Thesis\n") and ph("## SECTION 3 - Thesis\n   \n\t")              # empty
    for phrase in at.MEMO_PLACEHOLDER_PHRASES:
        assert ph(f"## SECTION 3 - Thesis\n{phrase.capitalize()} from the prior version.")
    assert not ph("## SECTION 3 - Thesis\nA short but real sentence about the margin.")          # short, no phrase
    long_real = "## SECTION 3 - Thesis\nUnchanged from prior in tone, but " + "the margin argument is new. " * 12
    assert len(long_real) >= at.MEMO_PLACEHOLDER_MAX and not ph(long_real)                       # a phrase in 200 characters or more is real
    assert not ph("## SECTION 3 - Thesis\n" + "x" * 250)


def test_a_new_section_is_added_and_a_bare_hold_reply_changes_nothing():
    reply = _memo([(7, "Extra", "A section the first memorandum did not have. " + "e" * 300)])
    merged, rec = at.merge_memo(ANSWER, reply)
    assert rec["sections"]["7"] == "added" and "A section the first memorandum" in merged
    merged2, rec2 = at.merge_memo(ANSWER, "HOLD")
    assert rec2["sections"] == {"0": "kept", "3": "kept", "12": "kept"} and rec2["contract"] == "answer"
    assert merged2.count("The thesis in full.") == 1 and '"y": 2' in merged2


def test_an_unsectioned_full_reply_stands_and_an_unsectioned_answer_is_not_lost():
    full = "A whole memorandum without section headings. " + "w" * 6000
    merged, rec = at.merge_memo(ANSWER, full)
    assert merged == full and rec["mode"] == "followup_unsectioned"
    merged, rec = at.merge_memo("An answer with no headings", "unchanged")
    assert merged == "An answer with no headings" and rec["mode"] == "answer_unsectioned"


def test_the_merge_in_the_loop_keeps_the_memorandum_the_pilot_lost(monkeypatch, tmp_path):
    """The crux follow-up's reply says 'unchanged from prior' in every section: the final memorandum is the answer memorandum."""
    monkeypatch.setattr(at, "crux_followup_state", lambda *a, **k: {"direction": "undervalued", "base": 80.0, "price": 50.0,
                                                                    "answer_call_index": 1, "inputs": {}})
    answer = ANSWER + "p" * 5000                                                         # a deliverable memorandum (5,000 characters or more)
    reply = _memo([(0, "Verdict", "unchanged from prior"), (3, "Thesis", "same as above"), (12, "Contract", "no change")])
    _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(_changed(explicit_growth=[0.05] * 5)), _turn(answer), _turn(reply)])
    rep, _t, meta = _run(tmp_path, two_pass={"arm": "r25_b", "withheld_block": None})
    assert meta["crux_followup"]["fired"] is True
    assert meta["memo_merge"]["mode"] == "merged"
    assert meta["memo_merge"]["sections"] == {"0": "kept", "3": "kept", "12": "kept"}
    assert "The verdict is HOLD." in rep and "The thesis in full." in rep and "no change" not in rep and meta["failure"] is None


def test_the_merge_in_the_loop_replaces_a_section_given_real_content(monkeypatch, tmp_path):
    monkeypatch.setattr(at, "crux_followup_state", lambda *a, **k: {"direction": "undervalued", "base": 80.0, "price": 50.0,
                                                                    "answer_call_index": 1, "inputs": {}})
    answer = ANSWER + "p" * 5000
    new0 = "The verdict is now UNDERVALUED on the margin crux. " + "q" * 300
    reply = _memo([(0, "Verdict", new0), (3, "Thesis", "unchanged")])
    _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(_changed(explicit_growth=[0.05] * 5)), _turn(answer), _turn(reply)])
    rep, _t, meta = _run(tmp_path, two_pass={"arm": "r25_b", "withheld_block": None})
    assert meta["memo_merge"]["sections"]["0"] == "replaced" and meta["memo_merge"]["sections"]["3"] == "kept"
    assert new0 in rep and "The thesis in full." in rep


# ---- every other arm is unchanged ------------------------------------------------------------------------------

def _h(x):
    return hashlib.sha256(x.encode()).hexdigest()


def test_the_other_arms_prompts_are_byte_for_byte_what_they_were():
    """sha256 of the prompts at 4deab98 (before this change). TASK_REV25 and FORM_FIELDS_25 are the only prompt texts this stage changes."""
    assert _h(cap.TASK) == "5e2cc4b6873898121123ccf669ad377721bbf4c2bcb22c7bffd20a0ed13a5119"
    assert _h(cap.TASK_REV22) == "414a4fd72ee6e5b7af4eda667f06427863da5a033f88d956042db53e855e5d3d"
    assert _h(repr(cap.FORM_FIELDS)) == "ff721ba7bbc4bcf1399569b37ec97776768548d2b68e72d221061cbf47ee03a4"
    assert _h(repr(cap.FORM_FIELDS_III)) == "368746c614b2397d37ad80dc6431f6485a992e138a23b6a2072b67ed46a479a7"
    assert cap.task_for({"pilot_arm": "rev22"}) is cap.TASK_REV22
    assert cap.task_for({"pilot_arm": "iii_p50"}) is cap.TASK and cap.task_for({"pilot_arm": "iii_no_p50"}) is cap.TASK
    assert cap.task_for({"desk_schema": "25.1", "pilot_arm": "r25_c"}) is cap.TASK_REV25 is cap.task_for({"desk_schema": "25.1", "pilot_arm": "r25_b"})
    assert "reconciliation_reasons" in cap.TASK_REV25 and "reconciliation_reasons" not in cap.TASK and "reconciliation_reasons" not in cap.TASK_REV22
    assert "reconciliation_reasons" in cap.FORM_FIELDS_25 and "reconciliation_reasons" not in cap.FORM_FIELDS_III


def test_a_session_without_two_pass_is_as_it_was(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO)])
    rep, _t, meta = _run(tmp_path)
    assert "two_pass" not in meta and "memo_merge" not in meta and rep == MEMO
    assert all("pass" not in c for c in _snap(tmp_path)["calls"]) and all("pass" not in t for t in meta["turns"])
    assert len(bodies) == 2


def test_the_verdict_row_carries_the_new_fields():
    for k in ("pass1_inputs", "change_log", "reconciliation_reasons", "two_pass_arm", "consensus_shown_pass1", "memo_merge"):
        assert k in cv.S12_SUMMARY_KEYS, k
    card = cv.extract_scorecard('```json:underwriting\n{"base_iv": 10, "reconciliation_reasons": [{"input": "Base.explicit_growth", "reason": "r"}]}\n```', 10.0)
    assert card["reconciliation_reasons"] == [{"input": "Base.explicit_growth", "reason": "r"}]
    import depth_pipeline
    src = Path(depth_pipeline.__file__).read_text(encoding="utf-8")
    for k in ("pass1_inputs", "change_log", "reconciliation_reasons", "two_pass_arm", "consensus_shown_pass1", "memo_merge"):
        assert f'"{k}"' in src, k


def test_the_merge_is_for_the_r25_arms_only_arm_a_keeps_the_follow_up_reply_as_it_ran(monkeypatch, tmp_path):
    """Without `two_pass` (arm A and every other arm) the follow-up's reply is the final memorandum, as at 4deab98."""
    monkeypatch.setattr(at, "crux_followup_state", lambda *a, **k: {"direction": "undervalued", "base": 80.0, "price": 50.0,
                                                                    "answer_call_index": 1, "inputs": {}})
    answer = ANSWER + "p" * 5000
    reply = _memo([(0, "Verdict", "The verdict is now BUY. " + "z" * 5200), (3, "Thesis", "unchanged"), (12, "Contract", "no change")])
    _serve(monkeypatch, [_desk(OK), _turn(answer), _turn(reply)])
    rep, _t, meta = _run(tmp_path)
    assert meta["crux_followup"]["fired"] is True and "memo_merge" not in meta
    assert rep == reply and "The thesis in full." not in rep                 # no section of the first memorandum is carried over



def test_a_two_pass_breach_is_not_retried_with_a_perturbed_seed():
    """The empty-report retry (consensus_valuation.main, seed + 50000) is skipped for a sample stamped two_pass_breach:no_pass1."""
    assert cv.is_two_pass_breach({"two_pass": {"breach": at.TWO_PASS_BREACH}}) is True
    assert cv.is_two_pass_breach({"two_pass": {"breach": None}}) is False
    assert cv.is_two_pass_breach({"two_pass": None}) is False and cv.is_two_pass_breach({}) is False and cv.is_two_pass_breach(None) is False
    src = Path(cv.__file__).read_text(encoding="utf-8")
    assert 'elif not (rep or "").strip() and use_tools and not is_two_pass_breach(meta):' in src


# ---- ruling 3: arm C's pass 1 sees no consensus through the desk either ----------------------------------------------------------------------

from test_rev25_bridge import LR as _LR, NORM as _NORM, _call as _b_call, _ctx as _b_ctx, _sc as _b_sc  # noqa: E402

_LEVELS = {"year1": 31.337, "year2": 33.771, "bull2": 38.842, "bear2": 28.119}
_WITHHELD_NUMBERS = ("38.842", "28.119", "31.337", "33.771", "77.654", "41.2345", "29.8765", "0.3457", "0.34567", "x the reference", "bull2 level")


def _consensus_ctx():
    lr = dict(_LR, om_tc=0.41, om_L=0.42, om_trend=0.43, e5=41.2345, oe5=29.8765, m5=0.34567)       # m5 is the nearest X-basis fact to a 0.41 margin
    return _b_ctx(levels=dict(_LEVELS), consensus_implied_value=77.654, reference_status="used", years35_cap=0.0731, long_run=lr)


def _bridge_call():
    base = _b_sc("Base", 0.5, **dict(_NORM, normalized_margin=0.41, long_run_margin=0.41, earnings_margin=[0.41] * 5))
    call = _b_call([base, _b_sc("Bull", 0.25, earnings_margin=[0.42] * 5, long_run_margin=0.42),
                    _b_sc("Bear", 0.25, revenue_growth=[0.06] * 5, earnings_margin=[0.40] * 5, long_run_margin=0.40)])
    for k in ("scenario_deviation_reason", "guidance_deviation_reason", "bridge_C5_reason"):
        call.pop(k, None)
    return call


def _desk_text(call, ctx):
    """Everything the model is shown for one desk call: the refusal or the accepted result, whole, and its markdown."""
    res = fmt_execute(call, ctx)
    return json.dumps(res) + "\n" + str(res.get("markdown_report") or ""), res


def fmt_execute(call, ctx):
    import financial_model_tool
    return financial_model_tool.execute_financial_model(copy.deepcopy(call), ctx)


def test_the_pass_1_context_of_arm_c_drops_every_consensus_member_and_the_original_is_untouched():
    ctx = _consensus_ctx()
    before = copy.deepcopy(ctx)
    p1 = at.pass1_desk_context(ctx)
    assert ctx == before                                                           # pass 2 builds from the full one
    assert p1["levels"] is None and p1["years35_cap"] is None and p1["consensus_implied_value"] is None
    import consensus_reference
    assert not consensus_reference.reference_in_force(p1["reference_status"])
    assert not {"e5", "oe5", "m5"} & set(p1["long_run"]) and {"x_L", "rev_L", "m_tc", "nwc_intensity"} <= set(p1["long_run"])
    kept = ("reference_base_b", "owner_earnings_default_b", "terminal_g_anchor", "price", "coe_anchor", "desk_schema")
    assert all(p1.get(k) == ctx.get(k) for k in kept)
    assert at.pass1_desk_context(None) is None


def test_a_pass_1_desk_result_of_arm_c_and_its_markdown_hold_none_of_the_withheld_numbers():
    ctx = _consensus_ctx()
    full, res_full = _desk_text(_bridge_call(), ctx)
    p1, res_p1 = _desk_text(_bridge_call(), at.pass1_desk_context(ctx))
    # the full context quotes the levels, the reference ratio and the m5 of the basis question (the refusal); with its reasons given, the run is accepted
    assert ("28.119" in full or "38.842" in full) and "x the reference" in full and "0.3457" in full and res_full["validation_error"] is True
    given = dict(_bridge_call(), scenario_deviation_reason="dated, 10-K 2026", guidance_deviation_reason="dated, 10-K 2026",
                 bridge_C5_reason="dated, 10-K 2026")
    full2, res_full2 = _desk_text(given, ctx)
    assert "error" not in res_full2, res_full2.get("error")
    assert "0.3457" in full2                                                       # C5 names m5 as the nearest X-basis fact
    p1_2, res_p1_2 = _desk_text(given, at.pass1_desk_context(ctx))
    assert "error" not in res_p1_2, res_p1_2.get("error")
    for text in (p1, p1_2):
        for n in _WITHHELD_NUMBERS:
            assert n not in text, n
    assert [n["reason"] for n in res_full["needs_reasons"]].count("scenario_deviation_reason") == 1                 # the full context asks for these
    assert {n["reason"] for n in res_p1["needs_reasons"]} == {"bridge_C5_reason"}          # no deviation check fires without the levels and the reference
    yl = res_p1_2["price_implied"]["year2_level"]
    assert yl["value"] is None and "not applicable" in yl["not_available"]


def _spy_dispatch(monkeypatch):
    seen = []
    real = at.dispatch_tool

    def spy(name, args, **kw):
        if name == "run_financial_model":
            seen.append(kw.get("desk_context"))
        return real(name, args, **kw)
    monkeypatch.setattr(at, "dispatch_tool", spy)
    return seen


def _loop(monkeypatch, tmp_path, arm, block=None):
    bodies = _serve(monkeypatch, [_desk(OK), _turn(MEMO), _desk(_changed(explicit_growth=[0.05] * 5)), _turn(MEMO2)])
    seen = _spy_dispatch(monkeypatch)
    ctx = _ctx_full()
    _run(tmp_path, two_pass={"arm": arm, "withheld_block": block}, desk_context=ctx)
    return seen, ctx, bodies


def _ctx_full():
    from test_desk_continuation import PRICE
    from test_desk_checks import _ctx as desk_ctx
    return desk_ctx(price=PRICE, long_run=dict(_LR, e5=41.2345, oe5=29.8765, m5=0.34567), reference_status="used", years35_cap=0.0731)


def test_the_loop_gives_arm_c_the_withheld_context_in_pass_1_only_and_arm_b_the_full_one(monkeypatch, tmp_path):
    seen, ctx, _b = _loop(monkeypatch, tmp_path / "c", "r25_c", BLOCK)
    assert len(seen) == 2
    assert seen[0]["levels"] is None and seen[0]["years35_cap"] is None and "m5" not in seen[0]["long_run"]       # pass 1
    assert seen[1]["levels"] == ctx["levels"] and seen[1]["long_run"]["m5"] == 0.34567 and seen[1]["years35_cap"] == 0.0731     # pass 2
    seen_b, ctx_b, _b = _loop(monkeypatch, tmp_path / "b", "r25_b")
    assert len(seen_b) == 2 and all(c["levels"] == ctx_b["levels"] and c["long_run"]["m5"] == 0.34567 for c in seen_b)


def test_the_same_call_in_arm_b_or_pass_2_shows_what_arm_c_pass_1_does_not():
    """A call whose Base and Bull years 1-2 sit off the printed levels: the full context holds the Base at them and refuses the Bull, quoting the levels;
    arm C's pass 1 neither holds, refuses nor quotes."""
    moved = copy.deepcopy(OK)
    moved.pop("scenario_deviation_reason", None)
    moved.pop("guidance_deviation_reason", None)
    ctx = _ctx_full()
    ctx["levels"] = {"year1": 5.31234, "year2": 6.64321, "bull2": 7.77711, "bear2": 4.44447}          # numbers that occur nowhere else in the result
    full = json.dumps(fmt_execute(moved, ctx))
    p1 = json.dumps(fmt_execute(moved, at.pass1_desk_context(ctx)))
    assert "7.7771" in full
    for n in ("7.7771", "5.3123", "6.6432", "4.4445", "7.77711", "6.64321", "4.44447"):
        assert n not in p1, n


def test_the_peg_member_of_the_multiples_line_is_withheld_in_pass_1_and_the_trailing_pe_is_kept():
    text = ("## DATA 8 - CONSENSUS & MULTIPLES   [Aggregator, 3d]\n"
            "- Trailing P/E: 24.5   |   P/B: 6.1   |   PEG: 1.87   [trailing; the vendor does not state the period]\n"
            "- Return on equity: 0.2\n")
    p1, block, elements = cap.split_consensus(text)
    assert "PEG: 1.87" not in p1 and "1.87" not in p1 and "PEG: withheld_until_pass_2" in p1
    assert "Trailing P/E: 24.5" in p1 and "P/B: 6.1" in p1 and "[trailing; the vendor does not state the period]" in p1
    assert "- PEG: 1.87" in block and [e["element"] for e in elements] == ["DATA 8 PEG (forward growth estimates)"]
    assert elements[0]["source_line"] == 2
