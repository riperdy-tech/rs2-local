"""Revision 25 Stage 0.5: the classification checks K1-K4 (SPEC_rev25_normalization_bridge.md v1.2), the desk's use of them, the tool schema,
the TASK and the contract fill. Helpers are test_rev25_bridge's."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyst_tools as at  # noqa: E402
import bridge_checks as bc  # noqa: E402
import capability_test as cap  # noqa: E402
import contract_fill as cf  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
from test_rev25_bridge import NORM, R_, _call, _dcf, _run, _sc, _snapshot_call  # noqa: E402

TG, TM = bc.BRIDGE_TOLERANCES["tau_g"], bc.BRIDGE_TOLERANCES["tau_m_y1_5"]


def _rev(g):
    r = [100.0]
    for x in g:
        r.append(r[-1] * (1 + x))
    return r


def test_tau_g_is_registered_at_0_02_and_k2_k3_reuse_tau_m():
    assert TG == 0.02 and TM == 0.03


# ---- K1
@pytest.mark.parametrize("label,g,want", [
    ("accelerating", [0.05, 0.05, 0.07, 0.09, 0.09], "pass"),     # delta +0.04
    ("accelerating", [0.05, 0.05, 0.06, 0.06, 0.06], "fail"),     # delta +0.01
    ("decelerating", [0.09, 0.09, 0.07, 0.05, 0.05], "pass"),     # delta -0.04
    ("decelerating", [0.06, 0.06, 0.06, 0.05, 0.05], "fail"),     # delta -0.01
    ("steady", [0.06, 0.06, 0.06, 0.07, 0.07], "pass"),
    ("steady", [0.05, 0.05, 0.06, 0.09, 0.09], "fail"),
    ("shrinking", [-0.02] * 5, "pass"),
    ("shrinking", [0.01] * 5, "fail"),
])
def test_k1_rule(label, g, want):
    r = bc.check_k1(label, _rev(g))
    assert r["id"] == "K1" and r["status"] == want and set(r) >= {"declared", "derived", "horizon", "tolerance"}


def test_k1_mpwr_falling_growth_is_decelerating_not_accelerating():
    rev = _rev([0.50, 0.45, 0.45, 0.45, 0.45])           # +50% then +45%: decelerating whatever the level
    assert bc.check_k1("decelerating", rev)["status"] == "pass"
    assert bc.check_k1("accelerating", rev)["status"] == "fail"
    assert bc.check_k1("steady", rev)["status"] == "fail"       # delta -0.025 is beyond tau_g


def test_k1_boundary_tie_passes_and_the_directions_need_strictly_beyond_it():
    up = _rev([0.10, 0.10, 0.10, 0.12, 0.12])
    assert bc.check_k1("steady", up)["status"] == "pass"
    assert bc.check_k1("accelerating", up)["status"] == "fail"
    down = _rev([0.12, 0.12, 0.10, 0.10, 0.10])
    assert bc.check_k1("steady", down)["status"] == "pass"
    assert bc.check_k1("decelerating", down)["status"] == "fail"


def test_k1_not_computable():
    assert bc.check_k1(None, _rev([0.05] * 5))["status"] == "not_computable"
    assert bc.check_k1("steady", [1, 2])["status"] == "not_computable"


# ---- K2
def test_k2_rule_and_boundaries():
    m_tc = 0.25
    assert bc.check_k2("peak", m_tc + TM, m_tc)["status"] == "pass"            # a tie passes
    assert bc.check_k2("peak", m_tc + TM - 0.001, m_tc)["status"] == "fail"
    assert bc.check_k2("trough", m_tc - TM, m_tc)["status"] == "pass"
    assert bc.check_k2("trough", m_tc - TM + 0.001, m_tc)["status"] == "fail"
    assert bc.check_k2("mid", m_tc + TM, m_tc)["status"] == "pass"
    assert bc.check_k2("mid", m_tc - TM, m_tc)["status"] == "pass"
    assert bc.check_k2("mid", m_tc + TM + 0.001, m_tc)["status"] == "fail"
    assert bc.check_k2("not_cyclical", 0.6, m_tc)["status"] == "not_computable"
    assert bc.check_k2("peak", None, m_tc)["status"] == "not_computable"
    assert bc.check_k2(None, 0.3, m_tc)["status"] == "not_computable"


def test_k2_mu_mid_fails_and_peak_passes():
    assert bc.check_k2("mid", 0.638, 0.222)["status"] == "fail"           # spec v1.2's labelled case
    assert bc.check_k2("peak", 0.638, 0.222)["status"] == "pass"


# ---- K3
def test_k3_structural_transient_partly_and_the_boundaries():
    m0, mtc = 0.40, 0.20
    assert bc.check_k3("structural", 0.38, m0, mtc)["status"] == "pass"
    assert bc.check_k3("structural", 0.20, m0, mtc)["status"] == "fail"
    assert bc.check_k3("structural", 0.30 + TM / 2, m0, mtc)["status"] == "pass"     # tie: |L-m0| = |L-mtc| + tau_m
    assert bc.check_k3("transient", 0.21, m0, mtc)["status"] == "pass"
    assert bc.check_k3("transient", 0.40, m0, mtc)["status"] == "fail"
    assert bc.check_k3("transient", 0.30 - TM / 2, m0, mtc)["status"] == "pass"      # tie
    assert bc.check_k3("partly_structural", 0.30, m0, mtc)["status"] == "pass"
    assert bc.check_k3("partly_structural", 0.40 + TM, m0, mtc)["status"] == "pass"  # tau_m allowed at each end
    assert bc.check_k3("partly_structural", 0.40 + TM + 0.001, m0, mtc)["status"] == "fail"
    assert bc.check_k3("partly_structural", 0.20 - TM, m0, mtc)["status"] == "pass"
    assert bc.check_k3("partly_structural", 0.20 - TM - 0.001, m0, mtc)["status"] == "fail"
    assert bc.check_k3(None, 0.30, m0, mtc)["status"] == "not_computable"
    assert bc.check_k3("structural", None, m0, mtc)["status"] == "not_computable"


def test_k3_not_distinguishable_when_today_is_near_the_record():
    for lab, L in (("structural", 0.9), ("transient", 0.0), ("partly_structural", 0.9)):
        r = bc.check_k3(lab, L, 0.25 + TM, 0.25)                               # |m0 - mtc| = tau_m, a tie, so not distinguishable
        assert r["status"] == "pass" and "not distinguishable" in r["note"]
    assert "not distinguishable" not in bc.check_k3("structural", 0.38, 0.40, 0.20)["note"]


# ---- K4
def test_k4_reports_each_breach_separately():
    assert bc.check_k4("shrinking", -0.01, -0.03)["status"] == "pass"
    assert bc.check_k4("shrinking", 0.0, -0.03)["status"] == "pass"            # terminal_g <= 0: a tie passes
    r = bc.check_k4("shrinking", 0.02, 0.01)
    assert r["status"] == "fail" and len(r["derived"]["breaches"]) == 2
    r = bc.check_k4("shrinking", 0.02, -0.03)
    assert r["status"] == "fail" and len(r["derived"]["breaches"]) == 1 and "terminal_g" in r["derived"]["breaches"][0]
    r = bc.check_k4("shrinking", -0.01, 0.0)                                  # structural_growth must be strictly below 0
    assert r["status"] == "fail" and len(r["derived"]["breaches"]) == 1
    assert bc.check_k4("steady", 0.03, 0.03)["status"] == "not_computable"


def test_the_class_checks_never_change_an_input():
    kw = dict(growth_trajectory="shrinking", cycle_position="mid", margin_persistence="structural", revenue=_rev([0.1] * 5),
              long_run_margin=0.3, m_0=0.6, m_tc=0.2, terminal_g=0.03, g_S=0.02)
    before = copy.deepcopy(kw)
    out = bc.run_class_checks(**kw)
    assert kw == before and [c["id"] for c in out] == ["K1", "K2", "K3", "K4"]
    assert [c["status"] for c in out] == ["fail", "fail", "fail", "fail"]


# ---- the desk (the fixture Base: x_L 0.30, m_tc 0.25, revenue growth 10/8/6/5/4%, long_run_margin 0.30, terminal_g 0.03)
def _norm(**x):
    return dict(NORM, **x)


def test_the_desk_declares_and_reports_the_class_checks_on_the_base_only():
    call = _call([_sc("Base", 0.5, **_norm(growth_trajectory="decelerating", cycle_position="peak", margin_persistence="structural")),
                  _sc("Bull", 0.25), _sc("Bear", 0.25)])
    res = _run(call)
    assert "error" not in res, res.get("error")
    b = _dcf(res, "base")["bridge"]
    cc = {c["id"]: c for c in b["class_checks"]}
    assert set(cc) == {"K1", "K2", "K3", "K4"} and [cc[k]["status"] for k in ("K1", "K2", "K3")] == ["pass"] * 3
    assert cc["K4"]["status"] == "not_computable"
    assert "class_checks" not in _dcf(res, "bull")["bridge"]
    assert "classification checks" in fmt.format_model_results_markdown(res)


def test_top_level_labels_are_inherited_by_bull_and_bear_like_cycle_position():
    res = _run(_call(growth_trajectory="decelerating", margin_persistence="structural"))
    assert "error" not in res, res.get("error")
    bull = _dcf(res, "bull")["bridge"]["declared"]
    assert bull["growth_trajectory"] == "decelerating" and "growth_trajectory" in bull["inherited"] and "margin_persistence" in bull["inherited"]
    assert [c["id"] for c in _dcf(res, "base")["bridge"]["class_checks"]] == ["K1", "K2", "K3", "K4"]


def test_a_value_outside_its_enum_is_refused_by_name():
    for field, bad in (("growth_trajectory", "growing"), ("cycle_position", "top"), ("margin_persistence", "permanent")):
        res = _run(_call([_sc("Base", 0.5, **_norm(**{field: bad})), _sc("Bull", 0.25), _sc("Bear", 0.25)]))
        assert field in json.dumps(res), field
        assert res.get("error") or res.get("validation_error") or res.get("missing"), field


def test_a_failed_k_check_draws_its_reason_and_with_it_the_value_computes_and_stays_fail():
    call = _call([_sc("Base", 0.5, **_norm(growth_trajectory="shrinking")), _sc("Bull", 0.25), _sc("Bear", 0.25)])
    res = _run(call)
    names = {n["reason"] for n in res["needs_reasons"]}
    assert res["validation_error"] is True and {"class_K1_reason", "class_K4_reason"} <= names
    res2 = _run(dict(call, class_K1_reason="x, 10-K 2025", class_K4_reason="y, 10-K 2025"))
    assert "error" not in res2, res2.get("error")
    b = _dcf(res2, "base")["bridge"]
    cc = {c["id"]: c for c in b["class_checks"]}
    assert cc["K1"]["status"] == "fail" and cc["K1"]["reason_given"] is True and cc["K4"]["status"] == "fail"
    assert b["declared"]["growth_trajectory"] == "shrinking"                  # never re-labelled


def test_a_pack_without_desk_schema_ignores_the_labels():
    res = fmt.execute_financial_model(copy.deepcopy(_call(growth_trajectory="bogus")), {"price": 50.0})
    assert "class_checks" not in json.dumps(res)


# ---- the tool schema, the task, the contract
def test_the_25_1_tools_offer_the_labels_and_the_four_reasons():
    t = next(x for x in at.tools_for({"desk_schema": "25.1"}) if x["function"]["name"] == "run_financial_model")
    props = t["function"]["parameters"]["properties"]
    item = props["scenarios"]["items"]["properties"]
    for k in ("growth_trajectory", "margin_persistence", "cycle_position"):
        assert k in props and k in item
    for k in ("class_K1_reason", "class_K2_reason", "class_K3_reason", "class_K4_reason"):
        assert k in props


def test_the_r25_task_puts_the_labels_in_the_desk_call_and_leaves_evidence_in_the_contract():
    assert "pass them in the desk call" in cap.TASK_REV25 and "class_K1_reason" in cap.TASK_REV25
    assert "growth_trajectory_evidence" in cap.TASK_REV25
    assert "For a cyclical business also pass cycle_evidence." in cap.TASK_REV25
    assert "pass them in the desk call" not in cap.TASK


def test_the_fill_takes_the_labels_from_the_desk_and_stamps_a_differing_typed_value():
    call = _call([_sc("Base", 0.5, **_norm(growth_trajectory="decelerating", cycle_position="peak", margin_persistence="structural")),
                  _sc("Bull", 0.25), _sc("Bear", 0.25)])
    res = _run(call)
    assert "error" not in res, res.get("error")
    facts = {"desk_schema": "25.1", "coe_anchor": R_, "shares_outstanding": 1.0, "long_run_defaults_withheld": True}
    snap = [_snapshot_call(res, call)]
    filled, prov = cf.fill(snap, {}, facts, 50.0)
    assert (filled["growth_trajectory"], filled["cycle_position"], filled["margin_persistence"]) == ("decelerating", "peak", "structural")
    assert [c["id"] for c in filled["class_checks"]] == ["K1", "K2", "K3", "K4"] and "classification_from_desk_under_25_1" not in prov["stamps"]
    same = {"growth_trajectory": "Decelerating", "cycle_position": "peak", "margin_persistence": "structural"}
    assert "classification_from_desk_under_25_1" not in cf.fill(snap, same, facts, 50.0)[1]["stamps"]
    filled2, prov2 = cf.fill(snap, dict(same, cycle_position="mid"), facts, 50.0)
    assert filled2["cycle_position"] == "peak" and prov2["stamps"].count("classification_from_desk_under_25_1") == 1


def test_the_verdict_row_owners_carry_class_checks():
    import consensus_valuation as cv
    import depth_pipeline
    assert "class_checks" in cv.S12_SUMMARY_KEYS and "class_checks" in cf.FILLED_25 and "class_checks" not in cf.FILLED
    assert '"class_checks"' in Path(depth_pipeline.__file__).read_text(encoding="utf-8")
