"""tools/audit_202608/tests/test_contract_fill_rev15.py — S3 3.8: the fill for revision-15 answer
runs (section 6 item 3).

A call is a revision-15 call when its params carry "cash_flow_life" (3.8). These tests build
synthetic desk calls directly (as test_contract_fill.py does) rather than replaying real
snapshots, since no revision-15 recorded run exists yet (Package C, out of scope, has not shipped
and PACK_REVISION stays 14).
"""
from pathlib import Path
import sys

import pytest

_HERE = Path(__file__).resolve().parent.parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO))

import contract_fill


def _r15_call(scenarios, top_params=None, call_index=1):
    """A revision-15-shaped run_financial_model call: top-level params carry cash_flow_life (the
    r15 marker) plus whatever reasons/interest_addback the test wants; each scenario's dcf carries
    per_share_iv, terminal_leg and (for a finite life) finite_life_years."""
    top_params = dict(top_params or {})
    top_params.setdefault("cash_flow_life", "perpetual")
    p_scs, sc_dcfs = [], []
    for sc in scenarios:
        name = sc["name"]
        p_scs.append({"name": name, "prob": sc.get("prob", 0.5), "base_cf": sc.get("base_cf"),
                      "shares_diluted": sc.get("shares_diluted")})
        d = {"per_share_iv": sc["per_share_iv"]}
        if sc.get("terminal_leg") is not None:
            d["terminal_leg"] = sc["terminal_leg"]
        if sc.get("finite_life_years") is not None:
            d["finite_life_years"] = sc["finite_life_years"]
        if sc.get("shares_diluted") is not None:
            d["shares_diluted"] = sc["shares_diluted"]
        sc_dcfs.append({"name": name, "dcf": d})
    return {
        "tool": "run_financial_model",
        "call_index": call_index,
        "params": {**top_params, "scenarios": p_scs},
        "result": {"scenario_dcfs": sc_dcfs},
        "error": None,
        "validation_error": None,
    }


BASE = {"name": "Base", "prob": 0.5, "base_cf": 1.0, "per_share_iv": 100.0}
BULL = {"name": "Bull", "prob": 0.25, "base_cf": 1.1, "per_share_iv": 150.0}
BEAR = {"name": "Bear", "prob": 0.25, "base_cf": 0.9, "per_share_iv": 70.0}


def test_r15_call_detection_by_cash_flow_life_key():
    call = _r15_call([BASE, BULL, BEAR])
    assert "cash_flow_life" in call["params"]
    filled, prov = contract_fill.fill([call], {}, {}, 90.0)
    assert prov["mode"] == "joint"
    # base_cf_basis, interest_addback and the 11 reasons now appear (filled, even if None) —
    # proof the r15 branch fired, not the older S2 branch.
    assert "base_cf_basis" in filled
    assert "interest_addback" in filled
    for r in contract_fill.REASONS_11:
        assert r in filled


def test_r15_copies_cash_flow_life_and_reason_and_reasons_given():
    top_params = {
        "cash_flow_life": 15,
        "cash_flow_life_reason": "filed reserves 100mmboe over 10mmboe/yr production, 2026-09-01 10-K",
        "base_cf_reason": "TTM basis is more representative, 2026-08-01 10-Q",
        "terminal_reason": None,     # not given
        "shares_reason": "null",     # counts as not given (3.3)
        "wacc_reason": "  ",         # blank counts as not given
        "interest_addback": 0.05,
    }
    call = _r15_call([BASE, BULL, BEAR], top_params=top_params)
    filled, prov = contract_fill.fill([call], {}, {}, 90.0)
    assert filled["cash_flow_life"] == 15
    assert filled["cash_flow_life_reason"] == top_params["cash_flow_life_reason"]
    assert filled["base_cf_reason"] == top_params["base_cf_reason"]
    assert filled["terminal_reason"] is None
    assert filled["shares_reason"] is None
    assert filled["wacc_reason"] is None
    assert filled["interest_addback"] == pytest.approx(0.05)
    # Untouched reasons are also filled as None (all 11 always appear).
    for r in ("scenario_deviation_reason", "coe_adjustment_reason", "net_debt_reason",
              "bull_below_price_reason", "bear_above_price_reason"):
        assert filled[r] is None


def test_r15_cash_flow_life_normalized_from_string():
    call = _r15_call([BASE, BULL, BEAR], top_params={"cash_flow_life": "12"})
    filled, _ = contract_fill.fill([call], {}, {}, 90.0)
    assert filled["cash_flow_life"] == 12


def test_r15_leg_from_terminal_leg_gordon_no_typed_value_consulted():
    base = dict(BASE, terminal_leg="gordon", per_share_iv=42.0)
    call = _r15_call([base, BULL, BEAR])
    # A wildly different typed base_iv must NOT steer the picked value (3.8: "There is no typed
    # value to consult").
    typed = {"base_iv": 999.0}
    filled, prov = contract_fill.fill([call], typed, {}, 90.0)
    assert filled["base_iv"] == pytest.approx(42.0)
    assert prov["legs"]["base"] == "gordon"


def test_r15_leg_from_terminal_leg_exit():
    base = dict(BASE, terminal_leg="exit", per_share_iv=55.0)
    call = _r15_call([base, BULL, BEAR])
    filled, prov = contract_fill.fill([call], {}, {}, 90.0)
    assert filled["base_iv"] == pytest.approx(55.0)
    assert prov["legs"]["base"] == "exit"


def test_r15_leg_finite_life():
    base = dict(BASE, finite_life_years=15, per_share_iv=33.0)
    bull = dict(BULL, finite_life_years=15)
    bear = dict(BEAR, finite_life_years=15)
    call = _r15_call([base, bull, bear], top_params={"cash_flow_life": 15})
    filled, prov = contract_fill.fill([call], {}, {}, 40.0)
    assert prov["legs"]["base"] == "finite_life"
    assert filled["terminal_method"] == "finite_life"
    assert filled["terminal_multiple_or_g"] is None
    assert filled["cash_flow_life"] == 15


def test_r15_scenario_wise_reasons_come_from_the_base_supplying_call():
    """Scenario-wise mode: the copied fields come from the call that supplied the Base, per 3.8."""
    base_call = _r15_call([BASE], top_params={"cash_flow_life": "perpetual",
                                              "base_cf_reason": "from the base call"}, call_index=1)
    bull_call = _r15_call([BULL], top_params={"cash_flow_life": "perpetual",
                                              "base_cf_reason": "from the bull call, ignored"}, call_index=2)
    bear_call = _r15_call([BEAR], top_params={"cash_flow_life": "perpetual"}, call_index=3)
    filled, prov = contract_fill.fill([base_call, bull_call, bear_call], {}, {}, 90.0)
    assert prov["mode"] == "scenario_wise"
    assert filled["base_cf_reason"] == "from the base call"


def test_older_call_unaffected_new_fields_stay_unfilled():
    """A call with no cash_flow_life key is S2's rule unchanged: the new fields are not filled."""
    p_scs = [{"name": "Base", "prob": 1.0, "base_cf": 1.0}]
    sc_dcfs = [{"name": "Base", "dcf": {"per_share_iv": 20.0, "per_share_iv_gordon": 20.0}}]
    call = {"tool": "run_financial_model", "call_index": 1,
            "params": {"scenarios": p_scs}, "result": {"scenario_dcfs": sc_dcfs},
            "error": None, "validation_error": None}
    filled, prov = contract_fill.fill([call], {}, {}, 90.0)
    assert "base_cf_basis" not in filled
    assert "interest_addback" not in filled
    for r in contract_fill.REASONS_11:
        assert r not in filled
        assert r in prov["unfilled"]


# ---------------------------------------------------------------------------------------------
# base_cf_basis (3.8)
# ---------------------------------------------------------------------------------------------

def test_base_cf_basis_owner_earnings_default_within_2pct():
    base = dict(BASE, base_cf=1.0, per_share_iv=100.0)
    call = _r15_call([base, BULL, BEAR])
    facts = {"owner_earnings_default_b": 1.015}   # 1.5% away, within 2%
    filled, _ = contract_fill.fill([call], {}, facts, 90.0)
    assert filled["base_cf_basis"] == "owner_earnings_default"


def test_base_cf_basis_other_when_no_ticker_and_no_match():
    base = dict(BASE, base_cf=1.0, per_share_iv=100.0)
    call = _r15_call([base, BULL, BEAR])
    facts = {"owner_earnings_default_b": 5.0}   # far away
    filled, _ = contract_fill.fill([call], {}, facts, 90.0)
    assert filled["base_cf_basis"] == "other"


def test_base_cf_basis_other_when_owner_earnings_default_missing_and_no_ticker():
    base = dict(BASE, base_cf=1.0, per_share_iv=100.0)
    call = _r15_call([base, BULL, BEAR])
    filled, _ = contract_fill.fill([call], {}, {}, 90.0)
    assert filled["base_cf_basis"] == "other"


def test_base_cf_basis_latest_fy_multi_year_avg_ttm_fcf(monkeypatch):
    import consensus_valuation as cv

    base = dict(BASE, base_cf=1.0, per_share_iv=100.0)
    call = _r15_call([base, BULL, BEAR])
    facts = {"owner_earnings_default_b": 5.0}   # far from 1.0, forces the candidate search

    # latest_fy match
    monkeypatch.setattr(cv, "owner_cf_by_year", lambda t: {2024: 3.0, 2025: 1.02})
    monkeypatch.setattr(cv, "ttm_fcf_by_ticker", lambda t: None)
    filled, _ = contract_fill.fill([call], {}, facts, 90.0, ticker="XYZ")
    assert filled["base_cf_basis"] == "latest_fy"

    # multi_year_avg match: avg of (0.95, 1.05) = 1.00, exact match (0%); latest_fy (2025) = 1.05
    # is farther (5%) but still in tolerance, so the nearer one (the average) wins.
    monkeypatch.setattr(cv, "owner_cf_by_year", lambda t: {2024: 0.95, 2025: 1.05})
    filled, _ = contract_fill.fill([call], {}, facts, 90.0, ticker="XYZ")
    assert filled["base_cf_basis"] == "multi_year_avg"

    # ttm_fcf match, no owner_cf_by_year candidates at all
    monkeypatch.setattr(cv, "owner_cf_by_year", lambda t: {})
    monkeypatch.setattr(cv, "ttm_fcf_by_ticker", lambda t: 1.01)
    filled, _ = contract_fill.fill([call], {}, facts, 90.0, ticker="XYZ")
    assert filled["base_cf_basis"] == "ttm_fcf"


def test_base_cf_basis_other_when_ticker_but_no_candidate_within_tolerance(monkeypatch):
    import consensus_valuation as cv
    base = dict(BASE, base_cf=1.0, per_share_iv=100.0)
    call = _r15_call([base, BULL, BEAR])
    facts = {"owner_earnings_default_b": 5.0}
    monkeypatch.setattr(cv, "owner_cf_by_year", lambda t: {2025: 10.0})
    monkeypatch.setattr(cv, "ttm_fcf_by_ticker", lambda t: 20.0)
    filled, _ = contract_fill.fill([call], {}, facts, 90.0, ticker="XYZ")
    assert filled["base_cf_basis"] == "other"


# ---------------------------------------------------------------------------------------------
# shares_basis (3.8, replaces S2 R7's rule for revision-15 runs)
# ---------------------------------------------------------------------------------------------

def test_shares_basis_default_within_1pct_of_shares_default():
    base = dict(BASE, shares_diluted=1.0)
    bull = dict(BULL, shares_diluted=1.005)
    bear = dict(BEAR, shares_diluted=1.0)
    call = _r15_call([base, bull, bear])
    facts = {"shares_default": 1.0e9}
    filled, _ = contract_fill.fill([call], {}, facts, 90.0)
    assert filled["shares_basis"] == "default"


def test_shares_basis_falls_back_to_s2b_vendor_match():
    base = dict(BASE, shares_diluted=2.0)
    bull = dict(BULL, shares_diluted=2.0)
    bear = dict(BEAR, shares_diluted=2.0)
    call = _r15_call([base, bull, bear])
    facts = {"shares_default": 1.0e9, "shares_outstanding": 2.0e9}   # departs from default
    filled, _ = contract_fill.fill([call], {}, facts, 90.0)
    assert filled["shares_basis"] == "vendor"


def test_shares_basis_other_when_nothing_matches():
    base = dict(BASE, shares_diluted=9.0)
    bull = dict(BULL, shares_diluted=9.0)
    bear = dict(BEAR, shares_diluted=9.0)
    call = _r15_call([base, bull, bear])
    facts = {"shares_default": 1.0e9, "shares_outstanding": 2.0e9}
    filled, _ = contract_fill.fill([call], {}, facts, 90.0)
    assert filled["shares_basis"] == "other"
