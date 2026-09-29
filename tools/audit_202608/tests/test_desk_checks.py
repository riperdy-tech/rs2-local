"""tools/audit_202608/tests/test_desk_checks.py — S3 3.4/3.5/3.6/3.7: the desk's own refusals
before computing (V1-V7) and its reason checks after computing (R1-R14), the end-value leg
(terminal_leg) and the refusal format (section 6 item 2).
"""
import io
import json
from pathlib import Path
import sys

import pytest

_HERE = Path(__file__).resolve().parent.parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO))

import analyst_tools as at
import financial_model_tool as fmt
from financial_model_tool import execute_financial_model, unbundled_dcf


# ---------------------------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------------------------

def _ctx(**over):
    base = {
        "price": 100.0,
        "shares_default_b": 1.0,
        "coe_anchor": 0.08,
        "terminal_g_default": 0.03,
        "terminal_g_anchor": 0.03,
        "base_rate_table": {"p50": 5.0, "p90": 15.0, "share_ge_10": 20.0, "share_ge_20": 10.0, "share_ge_30": 5.0},
        "revenue_cagr_5y_pct": 9.0,
        "net_debt_default_b": 0.5,
        "interest_expense_latest_b": 0.02,
        "owner_earnings_default_b": 5.0,
        "base_window": {},
        "consensus_implied_value": 100.0,
        # calibrated to the Base/Bull/Bear scenarios in _happy_params: their own year-2 cash
        # flows land exactly on these levels (see calibration below).
        "levels": {"year1": 5.25, "year2": 5.5125, "bull2": 5.99995, "bear2": 5.0},
        "years35_cap": None,
    }
    base.update(over)
    return base


def _sc(name, base_cf=5.0, growth=(0.05, 0.05, 0.02, 0.02, 0.02), wacc=0.08, terminal_g=0.03,
        fade_years=0, prob=0.34, **extra):
    d = {"name": name, "prob": prob, "base_cf": base_cf, "explicit_growth": list(growth),
         "wacc": wacc, "terminal_g": terminal_g, "fade_years": fade_years}
    d.update(extra)
    return d


def _happy_params(**over):
    """A call that satisfies every V and R check against _ctx(). Calibrated directly against
    unbundled_dcf (base_cf=5.0, shares=1.0): Base $104.26 (rate/terminal_g at the defaults, year-2
    cash flow 5.5125 = the DEFAULTS year-2 level, value 1.0426x the $100 reference), Bull $135.91
    (year-2 5.99995 ~= bull2), Bear $61.56 (year-2 5.0 = bear2); Bear <= Base <= Bull and both
    Bull and Bear are on the price's own side (Bull above, Bear below)."""
    params = {
        "cash_flow_life": "perpetual",
        "cash_flow_life_reason": "the business has no finite reserve or licence term",
        "fade_years": 0,
        "terminal_g": 0.03,
        "sbc_treatment": "deducted_in_cf",
        "scenarios": [
            _sc("Base", base_cf=5.0, growth=(0.05, 0.05, 0.02, 0.02, 0.02), wacc=0.08, terminal_g=0.03, prob=0.34),
            _sc("Bull", base_cf=5.0, growth=(0.10, 0.0909, 0.05, 0.05, 0.05), wacc=0.075, terminal_g=0.03, prob=0.33),
            _sc("Bear", base_cf=5.0, growth=(0.0, 0.0, -0.02, -0.02, -0.02), wacc=0.10, terminal_g=0.03, prob=0.33),
        ],
    }
    params.update(over)
    return params


def test_happy_path_no_refusal():
    res = execute_financial_model(_happy_params(), context=_ctx())
    assert "error" not in res
    assert "scenario_dcfs" in res
    for sc in res["scenario_dcfs"]:
        assert "per_share_iv" not in sc["dcf"] or sc["dcf"]["per_share_iv"] is not None


# ---------------------------------------------------------------------------------------------
# V1: cash_flow_life
# ---------------------------------------------------------------------------------------------

def test_v1_cash_flow_life_absent():
    p = _happy_params()
    del p["cash_flow_life"]
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert "cash_flow_life" in res["missing"]


def test_v1_cash_flow_life_invalid_string():
    p = _happy_params(cash_flow_life="sometimes")
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert "cash_flow_life" in res["missing"]


def test_v1_cash_flow_life_out_of_range():
    p = _happy_params(cash_flow_life=61)
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert "cash_flow_life" in res["missing"]


def test_v1_cash_flow_life_valid_perpetual_and_int():
    for val in ("perpetual", 1, 60, "15"):
        p = _happy_params(cash_flow_life=val)
        res = execute_financial_model(p, context=_ctx())
        assert "cash_flow_life" not in (res.get("missing") or []), f"cash_flow_life={val!r} wrongly refused"


# ---------------------------------------------------------------------------------------------
# V2: cash_flow_life_reason
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("val", [None, "", "null", "NONE", "  "])
def test_v2_cash_flow_life_reason_not_given(val):
    p = _happy_params()
    if val is None:
        del p["cash_flow_life_reason"]
    else:
        p["cash_flow_life_reason"] = val
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert "cash_flow_life_reason" in res["missing"]


# ---------------------------------------------------------------------------------------------
# V3: finite_life_years leaves the schema
# ---------------------------------------------------------------------------------------------

def test_v3_top_level_finite_life_years_refused():
    p = _happy_params(finite_life_years=15)
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert any("finite_life_years" in m for m in res["missing"])


def test_v3_scenario_finite_life_years_refused():
    p = _happy_params()
    p["scenarios"][0]["finite_life_years"] = 15
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert any("finite_life_years" in m for m in res["missing"])


def _bare_ctx(**over):
    """A minimal context (every deviation check skipped: no anchors, no reference, price near
    zero so no scenario can be "below/above" it) isolating a single mechanism under test."""
    base = {"price": 0.01, "shares_default_b": 1.0, "coe_anchor": None, "terminal_g_default": None,
            "terminal_g_anchor": None, "base_rate_table": None, "revenue_cagr_5y_pct": None,
            "net_debt_default_b": None, "interest_expense_latest_b": None,
            "owner_earnings_default_b": None, "base_window": {}, "consensus_implied_value": None,
            "levels": {}, "years35_cap": None}
    base.update(over)
    return base


_ALL_REASONS_GIVEN = {
    "base_cf_reason": "dated evidence, 2026-09-01 10-K",
    "guidance_deviation_reason": "dated evidence, 2026-09-01 10-K",
    "scenario_deviation_reason": "dated evidence, 2026-09-01 10-K",
    "terminal_reason": "dated evidence, 2026-09-01 10-K",
    "coe_adjustment_reason": "dated evidence, 2026-09-01 10-K",
    "shares_reason": "dated evidence, 2026-09-01 10-K",
    "net_debt_reason": "dated evidence, 2026-09-01 10-K",
    "bull_below_price_reason": "dated evidence, 2026-09-01 10-K",
    "bear_above_price_reason": "dated evidence, 2026-09-01 10-K",
}


def test_v3_finite_cash_flow_life_reaches_every_scenario_and_top_level():
    """Isolates V3's mechanical wiring: a bare context plus every reason argument pre-supplied,
    so no R-check can fire regardless of what a 10-year truncation does to the published values."""
    p = _happy_params(cash_flow_life=10, **_ALL_REASONS_GIVEN)
    p["fade_years"] = 0
    for sc in p["scenarios"]:
        sc["fade_years"] = 0
    res = execute_financial_model(p, context=_bare_ctx())
    assert "error" not in res
    for sc in res["scenario_dcfs"]:
        assert sc["dcf"]["finite_life_years"] == 10
        assert "terminal_leg" not in sc["dcf"]


# ---------------------------------------------------------------------------------------------
# V4: terminal_leg
# ---------------------------------------------------------------------------------------------

def test_v4_terminal_leg_invalid_value():
    p = _happy_params()
    p["scenarios"][0]["terminal_leg"] = "sideways"
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert any("terminal_leg" in m for m in res["missing"])


def test_v4_exit_leg_without_exit_multiple_refused():
    p = _happy_params()
    p["scenarios"][0]["terminal_leg"] = "exit"
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert any("terminal_leg" in m for m in res["missing"])


def test_v4_exit_leg_with_scenario_level_multiple_accepted():
    p = _happy_params()
    p["scenarios"][0]["terminal_leg"] = "exit"
    p["scenarios"][0]["terminal_exit_multiple"] = 20.0
    res = execute_financial_model(p, context=_ctx())
    assert "error" not in res
    assert res["scenario_dcfs"][0]["dcf"]["terminal_leg"] == "exit"


def test_v4_terminal_leg_with_finite_life_refused():
    p = _happy_params(cash_flow_life=10)
    p["scenarios"][0]["terminal_leg"] = "gordon"
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert any("terminal_leg" in m for m in res["missing"])


# ---------------------------------------------------------------------------------------------
# V5: prob
# ---------------------------------------------------------------------------------------------

def test_v5_negative_prob_refused():
    p = _happy_params()
    p["scenarios"][0]["prob"] = -0.1
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert any("prob" in m for m in res["missing"])


@pytest.mark.parametrize("total,ok", [(0.99, True), (1.01, True), (0.989, False), (1.011, False)])
def test_v5_probability_sum_edges(total, ok):
    p = _happy_params()
    # three scenarios sum to `total`: split evenly with a residual on Bear
    p["scenarios"][0]["prob"] = total / 3
    p["scenarios"][1]["prob"] = total / 3
    p["scenarios"][2]["prob"] = total - 2 * (total / 3)
    res = execute_financial_model(p, context=_ctx())
    if ok:
        assert not (res.get("validation_error") and any("prob" in m for m in res.get("missing", [])))
    else:
        assert res["validation_error"] is True
        assert any("prob" in m for m in res["missing"])


def test_v5_sum_not_checked_without_all_three_roles():
    """Revision 16: a call without all three roles is refused for the missing role, and only for that:
    the probability sum is not checked (0.1 + 0.1 would otherwise have been refused for it)."""
    p = _happy_params()
    p["scenarios"] = [p["scenarios"][0], p["scenarios"][1]]  # Base + Bull only
    p["scenarios"][0]["prob"] = 0.1
    p["scenarios"][1]["prob"] = 0.1
    res = execute_financial_model(p, context=_ctx())
    assert res["validation_error"] is True
    assert len(res["missing"]) == 1 and "no Bear entry" in res["missing"][0]
    assert "prob" not in res["error"] and "must sum" not in res["error"]


# ---------------------------------------------------------------------------------------------
# V6: required inputs, context shares default
# ---------------------------------------------------------------------------------------------

def test_v6_shares_default_from_context_when_omitted():
    p = _happy_params(**_ALL_REASONS_GIVEN)
    res = execute_financial_model(p, context=_bare_ctx(shares_default_b=2.5))
    assert "error" not in res
    for sc in res["scenario_dcfs"]:
        assert sc["dcf"]["shares_diluted"] == pytest.approx(2.5)


def test_v6_shares_missing_everywhere_refused():
    p = _happy_params()
    res = execute_financial_model(p, context=_ctx(shares_default_b=None))
    assert res.get("validation_error") is True
    assert any("shares_diluted" in m for m in res.get("missing", []))


def test_v6_zero_share_count_from_facts_gives_none_default():
    """desk_context is built with `is not None and > 0`, never `or` — a 0 count yields None."""
    ctx = _ctx(shares_default_b=None)
    p = _happy_params()
    res = execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True


# ---------------------------------------------------------------------------------------------
# V7: every other unbundled_dcf/blend error becomes a refusal
# ---------------------------------------------------------------------------------------------

def test_v7_wacc_not_greater_than_terminal_g_refused():
    p = _happy_params()
    p["scenarios"][0]["wacc"] = 0.02
    p["scenarios"][0]["terminal_g"] = 0.03
    res = execute_financial_model(p, context=_ctx())
    assert res.get("validation_error") is True


def test_v7_no_refused_call_advances_model_calls(monkeypatch, tmp_path):
    """analyst_tools.chat_with_tools: 6 refused revision-15 calls do not consume the 5-run budget,
    and the 7th refused call closes the desk (3.7's accounting, unchanged plumbing)."""
    class _FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    turns = []
    for _ in range(7):
        turns.append({"message": {"content": "", "tool_calls": [
            {"function": {"name": "run_financial_model", "arguments": {
                "base_cf": 1.0, "explicit_growth": [0.05], "wacc": 0.08, "terminal_g": 0.03,
                "fade_years": 0, "sbc_treatment": "deducted_in_cf",
                # cash_flow_life / cash_flow_life_reason deliberately absent -> V1/V2 refusal
            }}}
        ]}, "done_reason": "stop", "eval_count": 10, "eval_duration": 100_000_000})
    turns.append({"message": {"content": "# MEMO\n" + "x" * 6000, "tool_calls": []},
                  "done_reason": "stop", "eval_count": 500, "eval_duration": 1_000_000_000})

    idx = [0]

    def fake_urlopen(req, timeout=None):
        i = idx[0]
        idx[0] += 1
        payload = turns[min(i, len(turns) - 1)]
        return _FakeResp(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    rep, think, meta = at.chat_with_tools("test-model", "test-pack", tmp_path, verbose=False,
                                          desk_context={"price": 100.0})

    snap = json.loads((tmp_path / "_research_snapshot.json").read_text(encoding="utf-8"))["calls"]
    assert len(snap) == 7
    for c in snap[:6]:
        res = c.get("result") or c
        assert res.get("validation_error") is True
        assert "Not accepted as a desk run; it does not use one of your desk runs." in res.get("error", "")
    assert meta["desk_validation_errors"] == 7
    # None of the 7 consumed a desk run: model_calls stayed at 0.
    assert all("desk_budget" not in c or c["desk_budget"].startswith("0 of") for c in snap[:6])


# ---------------------------------------------------------------------------------------------
# Refusal format (3.7)
# ---------------------------------------------------------------------------------------------

def test_refusal_format():
    p = _happy_params()
    del p["cash_flow_life"]
    res = execute_financial_model(p, context=_ctx())
    assert res["error"].startswith("Not accepted as a desk run; it does not use one of your desk runs.")
    assert res["error"].endswith("Call again with the same inputs and these reasons, or change an input with dated evidence.")
    assert res["validation_error"] is True
    assert isinstance(res["missing"], list)
    assert isinstance(res["needs_reasons"], list)


def test_refusal_carries_no_per_share_values_except_r12():
    p = _happy_params()
    del p["cash_flow_life"]
    res = execute_financial_model(p, context=_ctx())
    assert "scenario_dcfs" not in res
    assert "dcf_model" not in res
    assert "kelly_sizing" not in res


# ---------------------------------------------------------------------------------------------
# Price (context override, refusal when missing)
# ---------------------------------------------------------------------------------------------

def test_context_price_overrides_model_price():
    p = _happy_params(price=9999.0)
    res = execute_financial_model(p, context=_ctx(price=100.0))
    assert res["price"] == 100.0
    assert "today's price is supplied by the harness: 100.0" in res["price_note"]


def test_missing_context_price_refused():
    p = _happy_params()
    res = execute_financial_model(p, context=_ctx(price=None))
    assert res.get("validation_error") is True
    assert "price (harness)" in res.get("missing", [])


# ---------------------------------------------------------------------------------------------
# R1: shares vs shares_default_b
# ---------------------------------------------------------------------------------------------

def test_r1_shares_at_1pct_ok_and_beyond_refused():
    ctx = _ctx(shares_default_b=1.0)
    p = _happy_params()
    p["scenarios"][0]["shares_diluted"] = 1.01  # exactly 1%
    res = execute_financial_model(p, context=ctx)
    assert "error" not in res

    p2 = _happy_params()
    p2["scenarios"][0]["shares_diluted"] = 1.011  # just beyond 1%
    res2 = execute_financial_model(p2, context=ctx)
    assert res2.get("validation_error") is True
    assert any(n["reason"] == "shares_reason" for n in res2["needs_reasons"])


def test_r1_shares_reason_given_avoids_refusal():
    ctx = _ctx(shares_default_b=1.0)
    p = _happy_params(shares_reason="convertible notes, in the money since 2026-06-30 10-Q")
    p["scenarios"][0]["shares_diluted"] = 1.05
    res = execute_financial_model(p, context=ctx)
    assert "error" not in res


# ---------------------------------------------------------------------------------------------
# R2: base_cf vs owner_earnings_default_b
# ---------------------------------------------------------------------------------------------

def test_r2_base_cf_at_2pct_ok_and_beyond_refused():
    ctx = _ctx(owner_earnings_default_b=5.0)
    p = _happy_params()
    p["scenarios"][0]["base_cf"] = 5.1   # exactly 2%
    res = execute_financial_model(p, context=ctx)
    assert "error" not in res

    p2 = _happy_params()
    p2["scenarios"][0]["base_cf"] = 5.15   # well beyond 2%
    res2 = execute_financial_model(p2, context=ctx)
    assert res2.get("validation_error") is True
    assert any(n["reason"] == "base_cf_reason" for n in res2["needs_reasons"])


def test_r2_owner_earnings_default_none_always_needs_reason():
    ctx = _ctx(owner_earnings_default_b=None)
    p = _happy_params()
    res = execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True
    assert any(n["reason"] == "base_cf_reason" for n in res["needs_reasons"])


# ---------------------------------------------------------------------------------------------
# R3: base_window printed
# ---------------------------------------------------------------------------------------------

def test_r3_base_window_needs_base_cf_reason():
    ctx = _ctx(base_window={"gap": 0.2, "ttm_value": None, "ttm_year2": None})
    p = _happy_params()
    res = execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True
    assert any(n["reason"] == "base_cf_reason" for n in res["needs_reasons"])


# ---------------------------------------------------------------------------------------------
# R4: Base rate vs coe_anchor
# ---------------------------------------------------------------------------------------------

def test_r4_rate_at_150bp_ok_and_beyond_refused():
    ctx = _ctx(coe_anchor=0.08)
    p = _happy_params()
    p["scenarios"][0]["wacc"] = 0.095  # 1.5 pts
    res = execute_financial_model(p, context=ctx)
    assert "error" not in res

    p2 = _happy_params()
    p2["scenarios"][0]["wacc"] = 0.0951  # just beyond
    res2 = execute_financial_model(p2, context=ctx)
    assert res2.get("validation_error") is True
    assert any(n["reason"] == "coe_adjustment_reason" for n in res2["needs_reasons"])


def test_r4_skipped_when_anchor_none():
    ctx = _ctx(coe_anchor=None)
    p = _happy_params()
    p["scenarios"][0]["wacc"] = 0.30
    res = execute_financial_model(p, context=ctx)
    assert not (res.get("validation_error") and any(n["reason"] == "coe_adjustment_reason" for n in res.get("needs_reasons", [])))


# ---------------------------------------------------------------------------------------------
# R5 / R6: terminal_g and exit-implied terminal g vs terminal_g_default
# ---------------------------------------------------------------------------------------------

def test_r5_terminal_g_at_50bp_ok_and_beyond_refused():
    ctx = _ctx(terminal_g_default=0.03)
    p = _happy_params()
    p["scenarios"][0]["terminal_g"] = 0.035  # 0.5 pts
    res = execute_financial_model(p, context=ctx)
    assert "error" not in res

    p2 = _happy_params()
    p2["scenarios"][0]["terminal_g"] = 0.0351
    res2 = execute_financial_model(p2, context=ctx)
    assert res2.get("validation_error") is True
    assert any(n["reason"] == "terminal_reason" for n in res2["needs_reasons"])


def test_r6_exit_implied_terminal_g_beyond_default_refused():
    ctx = _ctx(terminal_g_default=0.03)
    p = _happy_params()
    p["scenarios"][0]["terminal_leg"] = "exit"
    p["scenarios"][0]["terminal_exit_multiple"] = 40.0   # far from default multiple
    res = execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True
    assert any(n["reason"] == "terminal_reason" for n in res["needs_reasons"])


# ---------------------------------------------------------------------------------------------
# R7 / R8: firm frame interest_addback, wacc_reason
# ---------------------------------------------------------------------------------------------

def _firm_params(**over):
    p = _happy_params(**over)
    for sc in p["scenarios"]:
        sc["valuation_frame"] = "firm"
        sc["net_debt"] = 0.5
    return p


def test_r7_missing_interest_addback_refused():
    p = _firm_params(wacc_reason="COE ANCHOR 8%, cost of debt 4%, tax 21%, weights 80/20")
    res = execute_financial_model(p, context=_ctx())
    assert res.get("validation_error") is True
    assert any(n["reason"] == "interest_addback" for n in res["needs_reasons"])


def test_r8_missing_wacc_reason_refused():
    p = _firm_params(interest_addback=0.05)
    res = execute_financial_model(p, context=_ctx())
    assert res.get("validation_error") is True
    assert any(n["reason"] == "wacc_reason" for n in res["needs_reasons"])


def test_r7_r8_satisfied_no_refusal():
    p = _firm_params(interest_addback=0.05,
                     wacc_reason="COE ANCHOR 8%, cost of debt 4%, tax 21%, weights 80/20")
    res = execute_financial_model(p, context=_ctx(net_debt_default_b=0.5))
    assert "error" not in res


# ---------------------------------------------------------------------------------------------
# R9: firm frame net_debt off default
# ---------------------------------------------------------------------------------------------

def test_r9_net_debt_off_default_refused():
    p = _firm_params(interest_addback=0.05,
                     wacc_reason="COE ANCHOR 8%, cost of debt 4%, tax 21%, weights 80/20")
    for sc in p["scenarios"]:
        sc["net_debt"] = 2.0   # far from default 0.5
    res = execute_financial_model(p, context=_ctx(net_debt_default_b=0.5))
    assert res.get("validation_error") is True
    assert any(n["reason"] == "net_debt_reason" for n in res["needs_reasons"])


# ---------------------------------------------------------------------------------------------
# R10: Base vs the reference window
# ---------------------------------------------------------------------------------------------

def test_r10_year2_far_from_level_refused():
    ctx = _ctx(levels={"year1": 1.05, "year2": 1.1025, "bull2": 1.2, "bear2": 1.0})
    p = _happy_params()
    p["scenarios"][0]["explicit_growth"] = [0.5, 0.5, 0.02, 0.02, 0.02]   # year2 way above the level
    res = execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True
    assert any(n["reason"] == "guidance_deviation_reason" for n in res["needs_reasons"])


def test_r10_value_outside_far_band_refused():
    ctx = _ctx(consensus_implied_value=100.0)
    p = _happy_params()
    for sc in p["scenarios"]:
        if sc["name"] == "Base":
            sc["wacc"] = 0.30   # crushes the Base value far below the reference
    res = execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True
    assert any(n["reason"] == "guidance_deviation_reason" for n in res["needs_reasons"])


def test_r10_reason_given_avoids_refusal():
    ctx = _ctx()
    p = _happy_params(guidance_deviation_reason="TTM basis, 2026-08-01 10-Q, more representative")
    p["scenarios"][0]["explicit_growth"] = [0.5, 0.5, 0.02, 0.02, 0.02]
    res = execute_financial_model(p, context=ctx)
    assert not (res.get("validation_error") and any(n["reason"] == "guidance_deviation_reason" for n in res.get("needs_reasons", [])))


# ---------------------------------------------------------------------------------------------
# R11: Bull/Bear year-2 vs DEFAULTS levels
# ---------------------------------------------------------------------------------------------

def test_r11_bull_year2_far_from_level_refused():
    ctx = _ctx(levels={"year1": 1.05, "year2": 1.1025, "bull2": 1.2, "bear2": 1.0})
    p = _happy_params()
    for sc in p["scenarios"]:
        if sc["name"] == "Bull":
            sc["explicit_growth"] = [1.0, 1.0, 0.05, 0.05, 0.05]   # year2 far above bull2
    res = execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True
    assert any(n["reason"] == "scenario_deviation_reason" for n in res["needs_reasons"])


def test_r11_skipped_when_level_not_printed():
    ctx = _ctx(levels={"year1": 1.05, "year2": 1.1025})   # no bull2/bear2
    p = _happy_params()
    for sc in p["scenarios"]:
        if sc["name"] == "Bull":
            sc["explicit_growth"] = [1.0, 1.0, 0.05, 0.05, 0.05]
    res = execute_financial_model(p, context=ctx)
    assert not (res.get("validation_error") and any(n["reason"] == "scenario_deviation_reason" for n in res.get("needs_reasons", [])))


# ---------------------------------------------------------------------------------------------
# R12: scenario order
# ---------------------------------------------------------------------------------------------

def test_r12_order_violation_refused_with_order_key():
    p = _happy_params()
    # Force Bear above Base by flattening its decline and raising its rate advantage.
    for sc in p["scenarios"]:
        if sc["name"] == "Bear":
            sc["explicit_growth"] = [0.3, 0.3, 0.1, 0.1, 0.1]
            sc["wacc"] = 0.06
    res = execute_financial_model(p, context=_ctx())
    if res.get("validation_error"):
        assert "order" in res
        assert set(res["order"].keys()) == {"bear", "base", "bull"}


# ---------------------------------------------------------------------------------------------
# R13 / R14: Bull below price / Bear above price
# ---------------------------------------------------------------------------------------------

def test_r13_bull_below_price_refused():
    ctx = _ctx(price=10000.0)
    p = _happy_params()
    res = execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True
    assert any(n["reason"] == "bull_below_price_reason" for n in res["needs_reasons"])


def test_r13_reason_given_avoids_refusal():
    ctx = _ctx(price=10000.0)
    p = _happy_params(bull_below_price_reason="the market prices a buyout that will not close, 2026-09-01")
    res = execute_financial_model(p, context=ctx)
    assert not (res.get("validation_error") and any(n["reason"] == "bull_below_price_reason" for n in res.get("needs_reasons", [])))


def test_r14_bear_above_price_refused():
    ctx = _ctx(price=0.01)
    p = _happy_params()
    res = execute_financial_model(p, context=ctx)
    assert res.get("validation_error") is True
    assert any(n["reason"] == "bear_above_price_reason" for n in res["needs_reasons"])


# ---------------------------------------------------------------------------------------------
# terminal_leg / end-value leg (3.6)
# ---------------------------------------------------------------------------------------------

def test_terminal_leg_default_exit_when_multiple_given():
    r = unbundled_dcf(base_cf=1.0, explicit_growth=[0.05] * 5, wacc=0.08, terminal_g=0.03,
                      terminal_exit_multiple=20.0, shares_diluted=1.0, fade_years=0,
                      sbc_treatment="deducted_in_cf")
    assert r["terminal_leg"] == "exit"
    assert r["per_share_iv"] == r["per_share_iv_exit"]


def test_terminal_leg_gordon_when_requested():
    r = unbundled_dcf(base_cf=1.0, explicit_growth=[0.05] * 5, wacc=0.08, terminal_g=0.03,
                      terminal_exit_multiple=20.0, shares_diluted=1.0, fade_years=0,
                      sbc_treatment="deducted_in_cf", terminal_leg="gordon")
    assert r["terminal_leg"] == "gordon"
    assert r["per_share_iv"] == r["per_share_iv_gordon"]


def test_terminal_leg_gordon_only_without_exit_multiple():
    r = unbundled_dcf(base_cf=1.0, explicit_growth=[0.05] * 5, wacc=0.08, terminal_g=0.03,
                      shares_diluted=1.0, fade_years=0, sbc_treatment="deducted_in_cf")
    assert r["terminal_leg"] == "gordon"


def test_finite_life_has_no_terminal_leg_key():
    r = unbundled_dcf(base_cf=1.0, explicit_growth=[0.05] * 5, wacc=0.08, terminal_g=0.03,
                      shares_diluted=1.0, fade_years=0, sbc_treatment="deducted_in_cf",
                      finite_life_years=10)
    assert "terminal_leg" not in r


def test_kelly_follows_published_legs_ugi_like():
    """UGI s1-like case: Gordon Bear chosen with an exit multiple passed. Kelly and payoff_skew
    must use the published (Gordon) value, not the exit leg (codefill_golden.json: typed 15.5
    against the desk's 24.75)."""
    ctx = _ctx()
    p = _happy_params()
    for sc in p["scenarios"]:
        if sc["name"] == "Bear":
            sc["terminal_exit_multiple"] = 25.0
            sc["terminal_leg"] = "gordon"
    res = execute_financial_model(p, context=ctx)
    if "error" in res:
        pytest.fail(f"scenario construction hit a reason check: {res.get('missing') or res.get('needs_reasons')}")  # reviewer: fail, never skip
    bear = next(s for s in res["scenario_dcfs"] if s["name"] == "Bear")
    assert bear["dcf"]["terminal_leg"] == "gordon"
    assert bear["dcf"]["per_share_iv"] == bear["dcf"]["per_share_iv_gordon"]
    assert bear["dcf"]["per_share_iv"] != bear["dcf"]["per_share_iv_exit"]
    # The scenario dict Kelly consumes ("iv") must equal the published (Gordon) value.
    bear_param = next(s for s in p["scenarios"] if s["name"] == "Bear")
    assert bear_param["iv"] == bear["dcf"]["per_share_iv"]


# ---------------------------------------------------------------------------------------------
# Reverse DCF: uses the Base when Bear is listed first
# ---------------------------------------------------------------------------------------------

def test_reverse_dcf_uses_base_when_bear_listed_first():
    ctx = _ctx()
    p = _happy_params()
    p["scenarios"] = list(reversed(p["scenarios"]))  # Bear, Bull, Base
    assert p["scenarios"][0]["name"] == "Bear"
    res = execute_financial_model(p, context=ctx)
    assert "error" not in res
    base_sc = next(s for s in p["scenarios"] if s["name"] == "Base")
    rev = res.get("reverse_dcf") or {}
    assert not rev.get("skipped")
    # Recompute the reverse DCF directly off the Base scenario's own inputs and compare.
    expect = fmt.reverse_dcf_expectations_gap(
        current_price=100.0, shares_diluted=1.0, base_cf=base_sc["base_cf"], wacc=base_sc["wacc"],
        terminal_g=base_sc["terminal_g"], fade_years=0, stage1_years=5,
    )
    assert rev["implied_growth_next_5y_pct"] == pytest.approx(expect["implied_growth_next_5y_pct"], abs=0.05)


# ---------------------------------------------------------------------------------------------
# Sector band leaves the schema
# ---------------------------------------------------------------------------------------------

def test_sector_multiple_band_not_passed_through():
    p = _happy_params()
    p["sector_multiple_band"] = {"low": 10, "mid": 15, "high": 20, "metric": "EV/FCF"}
    res = execute_financial_model(p, context=_ctx())
    if "error" in res:
        pytest.fail(f"hit an unrelated reason check: {res.get('missing') or res.get('needs_reasons')}")  # reviewer: fail, never skip
    for sc in res["scenario_dcfs"]:
        assert "sector_multiple_band" not in sc["dcf"]
        assert "multiple_in_band_gordon" not in sc["dcf"]


# ---------------------------------------------------------------------------------------------
# Revision 16 (brief_rev16.md): exactly three scenarios, one unit for share counts, and a refusal
# that names the share unit
# ---------------------------------------------------------------------------------------------

_NO_DESK_RUN = ("scenario_dcfs", "dcf_model", "kelly_sizing", "payoff_skew", "reverse_dcf")


def _assert_refused_for_scenarios(res):
    """A refusal that produced no desk run: none of the result sections a run writes is present."""
    assert res["validation_error"] is True
    assert res["needs_reasons"] == []
    assert not [k for k in _NO_DESK_RUN if k in res]


def test_rev16_a_two_scenario_call_is_refused():
    """Bull and Bear as scenarios with the Base as top-level inputs, probabilities summing to 0.55: the
    call the desk used to accept, sizing Kelly on two outcomes."""
    p = _happy_params(base_cf=5.0, explicit_growth=[0.05, 0.05, 0.02, 0.02, 0.02], wacc=0.08)
    p["scenarios"] = [dict(sc, prob=prob) for sc, prob in zip(p["scenarios"][1:], (0.30, 0.25))]
    assert [sc["name"] for sc in p["scenarios"]] == ["Bull", "Bear"]
    assert sum(sc["prob"] for sc in p["scenarios"]) == pytest.approx(0.55)
    res = execute_financial_model(p, context=_ctx())
    _assert_refused_for_scenarios(res)
    assert "no Base entry" in res["error"]
    assert "no Bull entry" not in res["error"] and "no Bear entry" not in res["error"]


@pytest.mark.parametrize("keep", [("Base",), ("Bull",), ("Bear",), ("Base", "Bull"), ("Base", "Bear")])
def test_rev16_a_call_missing_a_role_is_refused_naming_each_missing_role(keep):
    p = _happy_params()
    p["scenarios"] = [sc for sc in p["scenarios"] if sc["name"] in keep]
    res = execute_financial_model(p, context=_ctx())
    _assert_refused_for_scenarios(res)
    for role in ("Base", "Bull", "Bear"):
        assert (f"no {role} entry" in res["error"]) == (role not in keep)


def test_rev16_a_call_with_two_bases_is_refused_naming_the_duplicated_role():
    p = _happy_params()
    p["scenarios"].append(_sc("Downside", prob=0.0))          # a name without "bull" or "bear" is Base
    res = execute_financial_model(p, context=_ctx())
    _assert_refused_for_scenarios(res)
    assert "2 Base entries (Base, Downside)" in res["error"]
    assert "no Bull entry" not in res["error"] and "no Bear entry" not in res["error"]


def test_rev16_two_bulls_and_two_bears_are_refused_too():
    p = _happy_params()
    p["scenarios"] += [_sc("Bull 2", prob=0.0), _sc("Bear 2", prob=0.0)]
    res = execute_financial_model(p, context=_ctx())
    _assert_refused_for_scenarios(res)
    assert "2 Bull entries (Bull, Bull 2)" in res["error"] and "2 Bear entries (Bear, Bear 2)" in res["error"]


def test_rev16_a_three_scenario_call_is_unchanged():
    """The calibrated call of _happy_params (Base $104.26, Bull $135.91, Bear $61.56): accepted, every value and
    the Kelly and payoff sections as before. A name carries its role by "bull" or "bear"; any other name is Base."""
    for names in (("Base", "Bull", "Bear"), ("Central case", "Bull case", "Bear case")):
        p = _happy_params()
        for sc, nm in zip(p["scenarios"], names):
            sc["name"] = nm
        res = execute_financial_model(p, context=_ctx())
        assert "error" not in res, res.get("error")
        assert [s["dcf"]["per_share_iv"] for s in res["scenario_dcfs"]] == [104.26, 135.91, 61.56]
        assert "kelly_sizing" in res and "payoff_skew" in res and "reverse_dcf" in res


def test_rev16_a_call_without_scenarios_is_unchanged():
    """A top-level call: the single DCF at the same value as the calibrated Base, no Kelly (it needs
    scenarios), and an empty scenarios list is the same call."""
    top = dict(base_cf=5.0, explicit_growth=[0.05, 0.05, 0.02, 0.02, 0.02], wacc=0.08)
    p = _happy_params(**top)
    del p["scenarios"]
    res = execute_financial_model(p, context=_ctx())
    assert "error" not in res, res.get("error")
    assert res["dcf_model"]["per_share_iv"] == 104.26
    assert "scenario_dcfs" not in res and "kelly_sizing" not in res
    assert "reverse_dcf" in res
    assert execute_financial_model(_happy_params(scenarios=[], **top), context=_ctx()) == res


_K = 0.083371        # EZPW's diluted count in billions: 83,371,000 shares


def _scaled(**over):
    """_happy_params and _ctx() for a company of _K billion shares: every cash flow and level times _K, so the
    values per share are the ones _happy_params is calibrated to; the share count is whatever `over` gives."""
    ctx = _ctx(shares_default_b=_K, owner_earnings_default_b=5.0 * _K,
               levels={k: v * _K for k, v in _ctx()["levels"].items()})
    p = _happy_params(**over)
    for sc in p["scenarios"]:
        sc["base_cf"] = 5.0 * _K
    return p, ctx


def test_rev16_a_whole_share_count_and_its_billions_value_agree_to_the_cent():
    """83,371,000 and 0.083371 (EZPW 1, calls 9 and 11 of the revision-15 run): the same desk output, whole
    result, at the top level and in the scenarios, and the values per share are the calibrated ones."""
    p_raw, ctx = _scaled(shares_diluted=83_371_000)
    p_b, _ = _scaled(shares_diluted=_K)
    p_sc_raw, _ = _scaled()
    for sc in p_sc_raw["scenarios"]:
        sc["shares_diluted"] = 83_371_000
    p_sc_b, _ = _scaled()
    for sc in p_sc_b["scenarios"]:
        sc["shares_diluted"] = _K
    res_b = execute_financial_model(p_b, context=ctx)
    assert "error" not in res_b, res_b.get("error")
    assert [s["dcf"]["per_share_iv"] for s in res_b["scenario_dcfs"]] == [104.26, 135.91, 61.56]
    for p in (p_raw, p_sc_raw, p_sc_b):
        assert execute_financial_model(p, context=ctx) == res_b


@pytest.mark.parametrize("bad", ["79,364,362", "lots", 0, -1.0])
def test_rev16_a_share_count_it_cannot_use_is_refused_not_replaced_by_the_default(bad):
    p, ctx = _scaled(shares_diluted=bad)
    res = execute_financial_model(p, context=ctx)
    assert res["validation_error"] is True
    assert any("shares_diluted" in m for m in res["missing"])
    assert "scenario_dcfs" not in res


@pytest.mark.parametrize("shares", [83.371, 0.000083371])
def test_rev16_a_refusal_for_a_base_far_from_the_reference_names_the_share_unit(shares):
    """Millions given where billions are meant (a Base 1000x too low) and the reverse (1000x too high): the
    refusal says the likely cause is the share unit, gives the ratio to the reference and the pack's count,
    and, like every refusal but the order one (S3 3.5), carries neither the Base value nor the reference."""
    p, ctx = _scaled(shares_diluted=shares)
    ctx["consensus_implied_value"] = 87.65                       # a reference no other figure in the text can equal
    res = execute_financial_model(p, context=ctx)
    assert res["validation_error"] is True
    assert "share unit" in res["error"]
    assert "never thousands or millions" in res["error"]
    assert "the pack's default is 83,371,000, or 0.083371 in billions" in res["error"]
    # the Base value the same call has once every reason is given (the refusal itself carries none)
    reasons = dict(shares_reason="t", guidance_deviation_reason="t", bull_below_price_reason="t",
                   bear_above_price_reason="t")
    p_ok, _ = _scaled(shares_diluted=shares, **reasons)
    accepted = execute_financial_model(p_ok, context=ctx)
    assert "error" not in accepted, accepted.get("error")
    base_value = next(s["dcf"]["per_share_iv"] for s in accepted["scenario_dcfs"] if s["name"] == "Base")
    assert f"the Base value is {base_value / 87.65:.4f}x the reference," in res["error"]
    assert f"{base_value:.2f}" not in res["error"] and str(base_value) not in res["error"]
    assert "87.65" not in res["error"] and "reference price" not in res["error"]


def test_rev16_a_refusal_for_another_reason_does_not_name_the_share_unit():
    """A Base a fifth of the reference is a valuation difference, not a unit error."""
    p = _happy_params()
    for sc in p["scenarios"]:
        if sc["name"] == "Base":
            sc["wacc"] = 0.30
    res = execute_financial_model(p, context=_ctx(consensus_implied_value=100.0))
    assert res["validation_error"] is True and res["needs_reasons"]
    assert "share unit" not in res["error"]


# ---------------------------------------------------------------------------------------------
# Revision 16, incomplete entries: three entries are not three roles when one cannot be valued
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["Base", "Bull", "Bear"])
@pytest.mark.parametrize("field", ["base_cf", "explicit_growth", "wacc"])
def test_rev16_an_entry_missing_a_field_is_refused_naming_the_role_and_the_field(role, field):
    """The desk used to skip an entry without base_cf, explicit_growth or wacc: a three-entry call then valued
    two roles and Kelly sized outcomes whose probabilities did not sum to 1."""
    p = _happy_params()
    entry = next(sc for sc in p["scenarios"] if sc["name"] == role)
    del entry[field]
    res = execute_financial_model(p, context=_ctx())
    _assert_refused_for_scenarios(res)
    assert f"the {role} entry ({role}) lacks {field}" in res["error"]
    assert not [m for m in res["missing"] if role not in m]           # only that entry is named


def test_rev16_the_0_67_probability_case_is_refused():
    """Bear cannot be valued (no wacc), so the two entries the old desk computed carry 0.34 + 0.33 = 0.67
    of the probability; the call is refused and no Kelly size is made."""
    p = _happy_params()
    del next(sc for sc in p["scenarios"] if sc["name"] == "Bear")["wacc"]
    assert sum(sc["prob"] for sc in p["scenarios"] if sc["name"] != "Bear") == pytest.approx(0.67)
    res = execute_financial_model(p, context=_ctx())
    _assert_refused_for_scenarios(res)
    assert "kelly_sizing" not in res and "the Bear entry (Bear) lacks wacc" in res["error"]


def test_rev16_an_entry_missing_several_fields_names_all_of_them():
    p = _happy_params()
    for k in ("base_cf", "explicit_growth", "wacc"):
        del p["scenarios"][1][k]
    res = execute_financial_model(p, context=_ctx())
    _assert_refused_for_scenarios(res)
    assert "the Bull entry (Bull) lacks base_cf, explicit_growth, wacc" in res["error"]


@pytest.mark.parametrize("empty", [[], None])
def test_rev16_an_entry_with_no_growth_path_is_refused(empty):
    p = _happy_params()
    p["scenarios"][2]["explicit_growth"] = empty
    res = execute_financial_model(p, context=_ctx())
    _assert_refused_for_scenarios(res)
    assert "the Bear entry (Bear) lacks explicit_growth" in res["error"]


def test_rev16_the_aliases_growth_rates_and_discount_rate_still_complete_an_entry():
    """explicit_growth / growth_rates and wacc / discount_rate are the same inputs: an entry using the alias
    is complete and the call is the calibrated one."""
    p = _happy_params()
    for sc in p["scenarios"]:
        sc["growth_rates"] = sc.pop("explicit_growth")
        sc["discount_rate"] = sc.pop("wacc")
    res = execute_financial_model(p, context=_ctx())
    assert "error" not in res, res.get("error")
    assert [s["dcf"]["per_share_iv"] for s in res["scenario_dcfs"]] == [104.26, 135.91, 61.56]


@pytest.mark.parametrize("field", ["terminal_g", "fade_years"])
def test_rev16_an_entry_the_dcf_cannot_value_is_refused_naming_it_and_the_field(field):
    """The other inputs an entry needs come from the entry or the top level; with neither, the DCF's own input
    check refuses the call (it always did) and names the entry and the field. No desk run is made."""
    p = _happy_params()
    del next(sc for sc in p["scenarios"] if sc["name"] == "Bear")[field]
    del p[field]
    res = execute_financial_model(p, context=_ctx())
    _assert_refused_for_scenarios(res)
    assert f"Bear: missing required inputs: {field}" in res["error"]
