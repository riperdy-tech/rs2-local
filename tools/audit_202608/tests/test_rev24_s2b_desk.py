"""Revision 24 step 2b (BRIEF_R24_S2b_ranges_gate.md, its "Additions from step 2a"): the desk's part.

- Ruling 3 (PHASE_4_AMENDMENTS.md "Revision 24 step 2a"): with no year-5 revenue in the facts, m5 is the base fiscal year's filed earnings margin
  (the facts' long_run x_L), stamped m5_from_base_year, so the analyst's long_run_margin applies; a base-year margin that is not positive holds the
  margin with long_run_margin_not_applied_no_revenue and a reason. Tested on the 17 saved baseline packs that lack year-5 revenue.
- The long-run defaults withheld (the pilot arms iii; desk context long_run_defaults_withheld): no hold of years 1-2 at the consensus levels
  (LEVELS_HOLD_TOL off), no years-3-5 cap, no terminal_reason against a default, terminal_ronic required with no default, and band advice that
  does not call the scenario "the DEFAULTS"; without the flag (the rev22 arm) every one of them is as before.
- long_run_margin in the price-implied block; the implied trajectory the plausibility gate reads.
"""
import copy
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import consensus_reference as cr  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN  # noqa: E402

INF = math.inf
R, GT, FADE = 0.10, 0.03, 4
NO_REV5 = json.loads((HERE / "fixture_data" / "rev24_s2b" / "no_rev5_packs.json").read_text(encoding="utf-8"))["packs"]


def _ctx(**over):
    ctx = {"price": 1000.0, "shares_default_b": 1.0, "coe_anchor": R, "terminal_g_default": GT, "terminal_g_anchor": GT,
           "owner_earnings_default_b": 100.0, "terminal_ronic": INF, "long_run": {"e5": 100.0, "oe5": 100.0, "m5": 0.10, "r_tc": INF},
           "years35_cap": None}
    ctx.update(over)
    return ctx


def _sc(name, prob, g, **extra):
    d = {"name": name, "prob": prob, "base_cf": 100.0 / 1.05 ** 5, "explicit_growth": [g] * 5, "wacc": R, "terminal_g": GT, "fade_years": FADE}
    d.update(extra)
    return d


def _call(**over):
    p = dict(_ALL_REASONS_GIVEN, cash_flow_life="perpetual", cash_flow_life_reason="a perpetual franchise, 10-K 2025", fade_years=FADE,
             terminal_g=GT, sbc_treatment="deducted_in_cf", long_run_margin=0.08, terminal_ronic=0.15,
             scenarios=[_sc("Base", 0.5, 0.05), _sc("Bull", 0.25, 0.09, long_run_margin=0.12), _sc("Bear", 0.25, -0.02, long_run_margin=0.05)])
    p.update(over)
    return p


# ---- ruling 3: m5 from the base year ------------------------------------------------------------------------------------------------------

def test_with_no_year5_revenue_the_base_years_margin_is_m5_and_the_long_run_margin_applies():
    """A reference without a revenue path (e5, oe5, no m5) and no reference (the x_over_oe fallback): the base fiscal year's 12.5% is m5, the
    scenario's year-5 revenue is E5 / 12.5%, and the margin ratio is long_run_margin / 12.5% in every scenario."""
    for lr in ({"e5": 100.0, "oe5": 100.0, "m5": None, "r_tc": INF, "x_L": 0.125, "rev_L": 700.0},
               {"x_over_oe": 0.9, "r_tc": INF, "x_L": 0.125, "rev_L": 700.0}):
        res = fmt.execute_financial_model(_call(terminal_ronic=INF), _ctx(long_run=lr))      # an unlimited return: each long-run flow is earnings
        assert "error" not in res, res.get("error")
        for item, m in zip(res["scenario_dcfs"], (0.08, 0.12, 0.05)):
            d = item["dcf"]
            assert "m5_from_base_year" in d["stamps"] and "long_run_margin_not_applied_no_revenue" not in d["stamps"]
            assert d["long_run"]["m5_basis"] == "base_year" and d["long_run"]["margin_ratio"] == pytest.approx(m / 0.125, abs=1e-4)
            assert d["long_run"]["year5_earnings"] / d["long_run"]["year5_revenue"] == pytest.approx(0.125, abs=1e-4)
            # the margin reaches long_run_margin at the end of the fade: the last long-run flow (an unlimited return) is that year's earnings
            rev_n = d["long_run"]["year5_revenue"] * math.prod(1 + g for g in d["growth_rates_applied"][5:])
            assert d["projected_cfs"][-1] / rev_n == pytest.approx(m, abs=1e-4)


def test_a_base_year_margin_that_is_not_positive_holds_the_margin_with_a_reason():
    for x_L, why in ((-0.02, "filed earnings margin -2.00% is not positive"), (None, "no base fiscal year's filed earnings margin")):
        lr = {"e5": 100.0, "oe5": 100.0, "m5": None, "r_tc": INF, "x_L": x_L}
        res = fmt.execute_financial_model(_call(), _ctx(long_run=lr))
        d = res["scenario_dcfs"][0]["dcf"]
        assert "long_run_margin_not_applied_no_revenue" in d["stamps"] and "m5_from_base_year" not in d["stamps"]
        assert d["long_run"]["margin_ratio"] is None and why in d["long_run"]["margin_held_reason"]


def test_a_revenue_path_in_the_facts_is_still_the_m5_and_carries_no_base_year_stamp():
    res = fmt.execute_financial_model(_call(), _ctx(long_run={"e5": 100.0, "oe5": 100.0, "m5": 0.10, "r_tc": INF, "x_L": 0.125}))
    d = res["scenario_dcfs"][0]["dcf"]
    assert d["long_run"]["m5_basis"] == "facts" and "m5_from_base_year" not in d["stamps"] and d["long_run"]["margin_ratio"] == pytest.approx(0.8)


@pytest.mark.parametrize("t", sorted(NO_REV5))
def test_the_17_saved_packs_without_year5_revenue(t):
    """Each saved pack's own long_run facts (plus x_L): with a positive base-year margin the analyst's long_run_margin applies through it; with
    none, the margin is held and the desk says why. The base is the pack's owner-earnings default where it printed one."""
    pk = NO_REV5[t]
    lr = dict(pk["long_run"], x_L=pk["x_L"], rev_L=pk["rev_L"])
    lr = {k: (INF if v == "+inf" else -INF if v == "-inf" else v) for k, v in lr.items()}
    base = pk["owner_earnings_default_b"] if isinstance(pk["owner_earnings_default_b"], (int, float)) and pk["owner_earnings_default_b"] > 0 else 1.0
    tr = pk["terminal_ronic"]
    tr = INF if tr in ("+inf", "unlimited") else tr
    d = fmt.unbundled_dcf(base_cf=base, explicit_growth=[0.03] * 5, wacc=0.10, terminal_g=0.025, shares_diluted=1.0, fade_years=5,
                          sbc_treatment="deducted_in_cf", terminal_ronic=tr if isinstance(tr, (int, float)) else None, long_run=lr,
                          long_run_margin=0.10)
    assert "error" not in d, d
    if isinstance(pk["x_L"], (int, float)) and pk["x_L"] > 0:
        assert "m5_from_base_year" in d["stamps"], t
        assert d["long_run"]["margin_ratio"] == pytest.approx(0.10 / pk["x_L"], rel=1e-3), t
    else:
        assert "long_run_margin_not_applied_no_revenue" in d["stamps"] and d["long_run"]["margin_held_reason"], t


def test_the_saved_packs_split_as_measured():
    pos = sorted(t for t, p in NO_REV5.items() if isinstance(p["x_L"], (int, float)) and p["x_L"] > 0)
    assert len(NO_REV5) == 17 and len(pos) == 13
    assert sorted(set(NO_REV5) - set(pos)) == ["APA", "GTE", "NGVT", "NREF"]          # two losses, two with no base-year margin held


# ---- the long-run defaults withheld (the pilot arms iii) --------------------------------------------------------------------------------

LEVELS = {"year1": 110.0, "year2": 120.0, "bull2": 160.0, "bear2": 80.0}


def test_iii_holds_no_year_at_the_consensus_levels_while_the_rev22_desk_still_does():
    p = _call(guidance_deviation_reason=None)
    old = fmt.execute_financial_model(copy.deepcopy(p), _ctx(levels=LEVELS))
    assert "years12_held" in old and "years12_held_by_desk" in old["scenario_dcfs"][0]["dcf"]["stamps"]
    new = fmt.execute_financial_model(copy.deepcopy(p), _ctx(levels=LEVELS, long_run_defaults_withheld=True))
    assert "error" not in new and "years12_held" not in new and "years12_held_by_desk" not in new["scenario_dcfs"][0]["dcf"]["stamps"]
    assert new["scenario_dcfs"][0]["dcf"]["explicit_growth"] == [0.05] * 5


def test_iii_caps_no_year_3_to_5_while_the_rev22_desk_still_does():
    p = _call(guidance_deviation_reason=None)
    old = fmt.execute_financial_model(copy.deepcopy(p), _ctx(years35_cap=0.02))
    assert old["years35_cap"]["dcfs"][0]["applied_years35"] == [0.02, 0.02, 0.02]
    new = fmt.execute_financial_model(copy.deepcopy(p), _ctx(years35_cap=0.02, long_run_defaults_withheld=True))
    assert "years35_cap" not in new and new["scenario_dcfs"][0]["dcf"]["growth_rates_applied"][2:5] == [0.05] * 3


def test_iii_asks_no_terminal_reason_against_a_default():
    p = _call(terminal_reason=None, terminal_g=0.01, scenarios=[dict(s, terminal_g=0.01) for s in _call()["scenarios"]])
    old = fmt.execute_financial_model(copy.deepcopy(p), _ctx())
    assert old.get("validation_error") and "terminal_reason needed: Base terminal_g 1.00% is 2.00 points from terminal_g_default 3.00%" in old["error"]
    new = fmt.execute_financial_model(copy.deepcopy(p), _ctx(long_run_defaults_withheld=True))
    assert "error" not in new, new.get("error")
    # the terminal_ronic check alone (terminal_g at its default): 15% against an unlimited default
    q = _call(terminal_reason=None)
    assert "Base terminal_ronic 15.00% is infinitely from the DEFAULTS terminal_ronic unlimited" in fmt.execute_financial_model(copy.deepcopy(q), _ctx())["error"]
    assert "error" not in fmt.execute_financial_model(copy.deepcopy(q), _ctx(long_run_defaults_withheld=True))


def test_iii_requires_terminal_ronic_by_name_and_takes_no_default():
    p = _call()
    del p["terminal_ronic"]
    res = fmt.execute_financial_model(copy.deepcopy(p), _ctx(long_run_defaults_withheld=True))
    assert res["validation_error"] and res["missing"] == [
        "terminal_ronic (the return on new investment that pays for growth from year 6, a decimal such as 0.12: your judgment, with no default)"]
    p["scenarios"][1]["terminal_ronic"] = 0.2
    res = fmt.execute_financial_model(copy.deepcopy(p), _ctx(long_run_defaults_withheld=True))
    assert res["missing"][0].startswith("terminal_ronic for Base, Bear (the return")
    # the rev22 desk takes the facts' default, as before
    assert "error" not in fmt.execute_financial_model(copy.deepcopy(p), _ctx())
    # a finite life needs none
    fin = _call(cash_flow_life=20, fade_years=0, scenarios=[dict(s, fade_years=0) for s in _call()["scenarios"]])
    del fin["terminal_ronic"]
    assert "terminal_ronic" not in str(fmt.execute_financial_model(fin, _ctx(long_run_defaults_withheld=True)).get("error") or "")


def test_iii_band_advice_does_not_call_the_scenario_the_defaults():
    p = _call(bear_above_price_reason=None, scenario_deviation_reason=None)
    p["scenarios"][2]["explicit_growth"] = [80.0 / (100.0 / 1.05 ** 5) - 1.0, 0.0, 0.0, 0.0, 0.0]
    ctx = _ctx(levels=LEVELS, price=10.0)
    old = fmt.execute_financial_model(copy.deepcopy(p), ctx)
    new = fmt.execute_financial_model(copy.deepcopy(p), dict(ctx, long_run_defaults_withheld=True))
    assert "The DEFAULTS Bear for this name is" in old["error"]
    assert "The DEFAULTS Bear" not in new["error"] and "Your Bear with year 2 at the consensus bear2 level is" in new["error"]
    assert "keep the defaults" not in new["error"]


# ---- the price-implied long_run_margin and the implied trajectory ------------------------------------------------------------------------

def test_the_price_implied_block_holds_long_run_margin_and_its_value_reproduces_the_price():
    res = fmt.execute_financial_model(_call(), _ctx(price=900.0))
    blk = res["price_implied"]["long_run_margin"]
    assert blk["own"] == 0.08 and blk["reachable"] is True and blk["bound"]["low"] == 0.0
    again = fmt.execute_financial_model(_call(long_run_margin=blk["value"]), _ctx(price=900.0))
    assert again["scenario_dcfs"][0]["dcf"]["per_share_iv_raw"] == pytest.approx(900.0, abs=0.01)
    held = fmt.execute_financial_model(_call(), _ctx(long_run={"e5": 100.0, "oe5": 100.0, "m5": None, "r_tc": INF}))
    assert held["price_implied"]["long_run_margin"]["not_available"].startswith("the margin is held: the facts hold no year-5 revenue")
    assert "long_run_margin: " in "\n".join(fmt.price_implied_lines(res["price_implied"]))


def test_the_implied_trajectory_at_year_10_is_the_long_runs_own_arithmetic():
    lr = {"e5": 100.0, "oe5": 100.0, "m5": 0.10, "r_tc": INF, "x_L": 0.09, "rev_L": 600.0}
    for fade in (5, 3, 0, 8):
        d = fmt.unbundled_dcf(base_cf=100.0 / 1.05 ** 5, explicit_growth=[0.05] * 5, wacc=R, terminal_g=GT, shares_diluted=1.0, fade_years=fade,
                              sbc_treatment="deducted_in_cf", terminal_ronic=INF, long_run=lr, long_run_margin=0.08)
        im = d["implied"]
        e5 = d["long_run"]["year5_earnings"]
        g = [0.05 + (GT - 0.05) * (t - 5) / fade if (fade and t <= 5 + fade) else GT for t in range(6, 11)]
        k10 = 1 + (0.8 - 1) * min(1.0, 5 / fade) if fade else 0.8
        e10 = e5 * math.prod(1 + x for x in g) * k10
        assert im["year10_earnings"] == pytest.approx(e10, rel=1e-9), fade
        assert im["year10_margin"] == pytest.approx(0.10 * k10, rel=1e-9)
        assert im["revenue_cagr_10y"] == pytest.approx((e10 / (0.10 * k10) / 600.0) ** 0.1 - 1, rel=1e-9)
        assert im["earnings_ratio_10y"] == pytest.approx(e10 / (600.0 * 0.09), rel=1e-9)
        assert im["long_run_margin"] == 0.08 and im["terminal_g"] == GT and im["terminal_ronic"] == "unlimited" and im["not_computable"] == []
    # no revenue anywhere: the margin and revenue path are not computable, and the desk says why
    d = fmt.unbundled_dcf(base_cf=90.0, explicit_growth=[0.05] * 5, wacc=R, terminal_g=GT, shares_diluted=1.0, fade_years=5,
                          sbc_treatment="deducted_in_cf", terminal_ronic=0.2, long_run={"x_over_oe": 0.9}, long_run_margin=0.08)
    assert d["implied"]["revenue_cagr_10y"] is None and d["implied"]["long_run_margin"] is None
    assert "no year-5 revenue: the margin and revenue path are not known" in d["implied"]["not_computable"]
