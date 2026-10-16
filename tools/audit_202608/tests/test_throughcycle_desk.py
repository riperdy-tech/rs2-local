"""Revision 17 (brief B section 4, tests 3-5): the desk's funded long run, the Base years 1-2 held at the
fiscal-year levels, the working-capital deduction, the valuation date, the fallbacks when the pack carries no
reference, the firm frame, and the sbc_dilution unit rule."""
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))

import consensus_reference as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
from financial_model_tool import execute_financial_model, format_model_results_markdown, unbundled_dcf  # noqa: E402

INF = math.inf

# EZPW's revision-14 Base, from the recorded run (a4_replay_out\EZPW_20260927_191240, base sample 1): a TTM base
# of $0.148B with the full current-year growth. The pack's fiscal-year levels were $0.147B and $0.160B.
EZPW_BASE_CF = 0.148
EZPW_PATH = [0.08, 0.09, 0.082, 0.069, 0.056]
EZPW_CTX = {"price": 31.16, "shares_default_b": 0.061443, "coe_anchor": 0.0891, "terminal_g_default": 0.0375,
            "terminal_g_anchor": 0.0375, "owner_earnings_default_b": 0.148,
            "levels": {"year1": 0.147, "year2": 0.160, "bull2": 0.164, "bear2": 0.159},
            "years35_cap": 0.095}


def _three(base_path, **base_extra):
    def sc(name, prob, path, cf=EZPW_BASE_CF, wacc=0.0891):
        return {"name": name, "prob": prob, "base_cf": cf, "explicit_growth": path, "wacc": wacc}
    base = sc("Base", 0.45, base_path)
    base.update(base_extra)
    return [base, sc("Bull", 0.25, [0.10, 0.15, 0.14, 0.12, 0.10]),
            sc("Bear", 0.30, [0.02, -0.08, -0.05, 0.02, 0.0375], wacc=0.1041)]


def _call(scenarios, **over):
    # revision 24 step 2a: long_run_margin is required; EZPW_CTX carries no long-run facts, so it holds the margin and changes no value here
    p = {"scenarios": scenarios, "terminal_g": 0.0375, "fade_years": 5, "sbc_treatment": "deducted_in_cf",
         "cash_flow_life": "perpetual", "cash_flow_life_reason": "test", "shares_diluted": 0.061443, "long_run_margin": 0.08}
    p.update(over)
    return p


def _direct(path, ronic=None, **kw):
    args = dict(base_cf=EZPW_BASE_CF, explicit_growth=path, wacc=0.0891, terminal_g=0.0375, shares_diluted=0.061443,
                fade_years=5, sbc_treatment="deducted_in_cf")
    args.update(kw)
    return unbundled_dcf(terminal_ronic=ronic, **args)


# ---- test 4: the levels hold ------------------------------------------------------------------------

def test_ezpws_revision_14_base_is_held_to_the_levels():
    res = execute_financial_model(_call(_three(EZPW_PATH)), dict(EZPW_CTX))
    assert "error" not in res, res.get("error")
    base = res["scenario_dcfs"][0]["dcf"]
    y2_requested = EZPW_BASE_CF * 1.08 * 1.09
    assert abs(y2_requested / 0.160 - 1) > 0.05                    # the recorded Base sat 8.9% above the level
    g1, g2 = 0.147 / 0.148 - 1, 0.160 / 0.147 - 1
    assert base["years12_held"] is True and "years12_held_by_desk" in base["stamps"]
    assert base["explicit_growth"] == [round(g1, 4), round(g2, 4), 0.082, 0.069, 0.056]     # years 3-5 kept
    # the held Base's flows reach the levels exactly
    assert base["growth_rates_applied"][:2] == [round(g1, 4), round(g2, 4)]
    assert base["projected_cfs"][0] == pytest.approx(0.147, abs=1e-4) and base["projected_cfs"][1] == pytest.approx(0.160, abs=1e-4)
    # and its value is the value of that path, computed directly
    held = _direct([g1, g2, 0.082, 0.069, 0.056])
    assert base["per_share_iv"] == held["per_share_iv"]
    note = res["years12_held"]["dcfs"][0]
    assert note["requested_per_share_iv"] == _direct(EZPW_PATH)["per_share_iv"]
    assert note["applied_per_share_iv"] == base["per_share_iv"] < note["requested_per_share_iv"]
    assert res["years12_held"]["reason_field"] == "guidance_deviation_reason"
    assert res["years12_held"]["levels"] == {"year1": 0.147, "year2": 0.160}
    # the desk's text names the held values and the reason field that keeps the model's own path
    md = format_model_results_markdown(res)
    assert "Base years 1-2 held at the fiscal-year consensus cash-flow levels (year 1 $0.147B, year 2 $0.16B" in md
    assert "run the desk again with guidance_deviation_reason" in md and "cannot be your base_iv" in md


def test_the_same_call_with_guidance_deviation_reason_keeps_its_own_path():
    res = execute_financial_model(_call(_three(EZPW_PATH), guidance_deviation_reason="the June guidance raised growth (8-K, 2026-06-12)"),
                                  dict(EZPW_CTX))
    assert "error" not in res, res.get("error")
    base = res["scenario_dcfs"][0]["dcf"]
    assert "years12_held" not in base and "years12_held" not in res
    assert "years12_held_by_desk" not in base["stamps"]
    assert base["explicit_growth"] == EZPW_PATH
    assert base["per_share_iv"] == _direct(EZPW_PATH)["per_share_iv"]


def test_a_base_within_five_percent_of_the_level_is_not_held_and_bull_and_bear_are_never_held():
    near = [0.147 / 0.148 - 1, 0.160 / 0.147 * 1.04 - 1, 0.082, 0.069, 0.056]          # year 2 is 4% above the level
    res = execute_financial_model(_call(_three(near)), dict(EZPW_CTX))
    assert "error" not in res and "years12_held" not in res
    just_over = [0.147 / 0.148 - 1, 0.160 / 0.147 * 1.0501 - 1, 0.082, 0.069, 0.056]
    res = execute_financial_model(_call(_three(just_over)), dict(EZPW_CTX))
    assert res["years12_held"]["dcfs"][0]["name"] == "Base"
    assert [d["name"] for d in res["years12_held"]["dcfs"]] == ["Base"]                  # Bull and Bear are not held
    # Bull and Bear keep their own 15% scenario_deviation_reason check
    far_bull = _three(EZPW_PATH)
    far_bull[1]["explicit_growth"] = [0.30, 0.30, 0.10, 0.10, 0.10]
    res = execute_financial_model(_call(far_bull), dict(EZPW_CTX))
    assert res["validation_error"] is True
    assert any(n["reason"] == "scenario_deviation_reason" for n in res["needs_reasons"])


def test_the_base_year_two_check_no_longer_refuses_the_base():
    """Revision 16 refused a Base year 2 more than 15% from the level and asked for guidance_deviation_reason;
    revision 17 holds it instead, so the same call is accepted."""
    far = [0.30, 0.30, 0.05, 0.05, 0.05]
    res = execute_financial_model(_call(_three(far)), dict(EZPW_CTX))
    assert "error" not in res, res.get("error")
    assert res["years12_held"]["dcfs"][0]["requested_gap_pct"] > 15


def test_the_held_base_uses_a_shorter_list_the_same_way():
    # two rates and a fade: the path the desk applies (fade included) keeps its years 3-5
    res = execute_financial_model(_call(_three([0.08, 0.09]), fade_years=5), dict(EZPW_CTX, years35_cap=None))
    assert "error" not in res, res.get("error")
    base = res["scenario_dcfs"][0]["dcf"]
    assert base["years12_held"] is True and len(base["explicit_growth"]) == 5


# ---- section 4d/4e: working capital and the long run -------------------------------------------------

# brief F3: the facts carry the reference's margin_ratio (m_long / m5 = 0.06 / 0.10); the desk computes none, and since revision 24 step 2a
# it does not read it either (the analyst's long_run_margin moves the margin)
LR_FACTS = {"e5": 0.30, "oe5": 0.28, "m5": 0.10, "margin_ratio": 0.6, "r_tc": 0.20, "stub_months": 8.5}
WC = [0.004, 0.005, 0.006, 0.005, 0.004]


def _dcf_ctx(**over):
    ctx = {"price": 31.16, "shares_default_b": 0.061443, "terminal_ronic": 0.135, "owner_earnings_default_b": 0.148}
    ctx.update(over)
    return ctx


# revision 24 step 2c (ruling 12 of step 2b): the desk deducts working capital on each scenario's own revenue path, from the long_run facts' intensity,
# consensus revenue path and its owner earnings. This consensus path is built so that a scenario on the Base's own owner-earnings path (EZPW_PATH from
# EZPW_BASE_CF) deducts exactly WC; a scenario on another path deducts NWC x the change in revenue_t x its owner earnings_t / OE_REF_t.
# Revision 24 step 2d: normalized at the base, revenue_t x (its owner earnings_t / its base_cf) / (OE_REF_t / EZPW_BASE_CF), the consensus base
# (long_run oe_base); on the EZPW path from EZPW_BASE_CF the factor is 1, so the Base and the 2c expectations of the Bull and Bear are unchanged.
NWC = 0.05
OE_REF = [EZPW_BASE_CF * math.prod(1.0 + g for g in EZPW_PATH[:t + 1]) for t in range(5)]
REV_REF = [2.0] + [2.0 + sum(WC[:t + 1]) / NWC for t in range(5)]


def _wc_lr():
    return {"nwc_intensity": NWC, "revenue_path": REV_REF, "oe_path": OE_REF, "oe_base": EZPW_BASE_CF}


def _own_wc(path, cf=None):
    cf = EZPW_BASE_CF if cf is None else cf
    oe = [cf * math.prod(1.0 + g for g in path[:t + 1]) for t in range(5)]
    rev = [REV_REF[0]] + [REV_REF[t + 1] * (oe[t] / cf) / (OE_REF[t] / EZPW_BASE_CF) for t in range(5)]
    return [NWC * (rev[t + 1] - rev[t]) for t in range(5)]


def test_working_capital_is_deducted_in_years_1_to_5_from_every_scenario_unless_the_base_carries_it():
    plain = _direct(EZPW_PATH, ronic=0.135)
    with_wc = _direct(EZPW_PATH, ronic=0.135, working_capital=WC)
    assert with_wc["per_share_iv"] < plain["per_share_iv"]
    assert with_wc["projected_cfs"][:5] == pytest.approx([a - b for a, b in zip(plain["projected_cfs"][:5], WC)], abs=1e-4)
    assert with_wc["working_capital_deducted"] == WC and plain["working_capital_deducted"] is None
    # through the call (revision 24 step 2c, ruling 12): each scenario deducts on its own revenue path - the Base, on the consensus owner earnings,
    # exactly the consensus schedule; the faster Bull more and the slower Bear less; never one schedule for all. The Base is skipped when within 2%
    # of cash_basis_b
    scs = _three(EZPW_PATH)
    res = execute_financial_model(_call(scs, guidance_deviation_reason="x"), _dcf_ctx(long_run=_wc_lr(), cash_basis_b=None))
    got = {i["name"]: i["dcf"]["working_capital_deducted"] for i in res["scenario_dcfs"]}
    assert got["Base"] == pytest.approx(WC, abs=1e-4)
    assert got["Bull"] == pytest.approx(_own_wc(scs[1]["explicit_growth"]), abs=1e-4)
    assert got["Bear"] == pytest.approx(_own_wc(scs[2]["explicit_growth"]), abs=1e-4)
    assert sum(got["Bull"]) > sum(got["Base"]) > sum(got["Bear"])
    # (brief F6: a base within 2% of an owner-earnings figure is owner earnings, so the DEFAULTS owner earnings sit away)
    res = execute_financial_model(_call(_three(EZPW_PATH), guidance_deviation_reason="x", base_cf_reason="x"),
                                  _dcf_ctx(long_run=_wc_lr(), cash_basis_b=0.1485, owner_earnings_default_b=0.20))
    for item in res["scenario_dcfs"]:                       # every scenario starts from 0.148, within 2% of 0.1485
        assert item["dcf"]["working_capital_deducted"] is None and "wc_in_base" in item["dcf"]["stamps"]


def test_wc_in_base_is_per_scenario_on_its_own_base_cf():
    scs = _three(EZPW_PATH)
    scs[2]["base_cf"] = 0.10                                            # the Bear starts from a lower base
    res = execute_financial_model(_call(scs, guidance_deviation_reason="x", scenario_deviation_reason="x",
                                        base_cf_reason="x"),
                                  _dcf_ctx(long_run=_wc_lr(), cash_basis_b=0.148, owner_earnings_default_b=0.20))
    base, bull, bear = (i["dcf"] for i in res["scenario_dcfs"])
    assert "wc_in_base" in base["stamps"] and "wc_in_base" in bull["stamps"] and "wc_in_base" not in bear["stamps"]
    assert bear["working_capital_deducted"] == pytest.approx(_own_wc(scs[2]["explicit_growth"], cf=0.10), abs=1e-4)      # its own path


def test_the_long_run_takes_the_scenarios_own_growth_terminal_g_and_terminal_ronic():
    base = _direct(EZPW_PATH, ronic=0.135, long_run={"r_tc": 0.20})
    hi = _direct(EZPW_PATH, ronic=0.25, long_run={"r_tc": 0.20})
    assert hi["per_share_iv"] > base["per_share_iv"]                 # a higher return on new investment is worth more
    # terminal_g and fade_years reach it
    assert _direct(EZPW_PATH, ronic=0.135, terminal_g=0.03)["per_share_iv"] != base["per_share_iv"]
    assert _direct(EZPW_PATH, ronic=0.135, fade_years=3)["long_run"]["years"] == 8
    # a scenario's terminal_ronic (through the call) is its own
    scs = _three(EZPW_PATH)
    scs[2]["terminal_ronic"] = 0.05
    res = execute_financial_model(_call(scs, guidance_deviation_reason="x"), dict(EZPW_CTX, terminal_ronic=0.135, **{"years35_cap": None}))
    bear = res["scenario_dcfs"][2]["dcf"]
    assert bear["terminal_ronic"] == 0.05 and res["scenario_dcfs"][0]["dcf"]["terminal_ronic"] == 0.135


def test_the_scenarios_year_5_earnings_scale_with_its_owner_earnings():
    """Revision 24 step 2a (D3): E5 = e5 x OE5 / oe5, proportional (it was e5 + (OE5 - oe5), one for one)."""
    lr = {"e5": 0.30, "oe5": 0.28, "m5": None}
    low = _direct(EZPW_PATH, ronic=0.135, long_run=lr, base_cf=EZPW_BASE_CF)
    higher = _direct(EZPW_PATH, ronic=0.135, long_run=lr, base_cf=EZPW_BASE_CF * 1.10)
    e5_low, e5_high = low["long_run"]["year5_earnings"], higher["long_run"]["year5_earnings"]
    oe5_low = EZPW_BASE_CF * math.prod(1 + g for g in EZPW_PATH)
    assert e5_low == pytest.approx(0.30 * oe5_low / 0.28, abs=1e-4)
    assert e5_high == pytest.approx(e5_low * 1.10, abs=1e-4)


def test_the_desk_applies_the_analysts_long_run_margin_and_not_the_facts_margin_ratio():
    """Was `test_the_desk_applies_the_facts_margin_ratio_and_computes_none_itself` (brief F3: the reference's margin_ratio from the facts).
    Revision 24 step 2a (ruling 1): the desk reads no margin_ratio from the facts and computes none from m_tc and the cycle flag; the margin moves
    to the analyst's long_run_margin, the ratio being long_run_margin / (E5 / R5): the facts' year-5 revenue e5 / m5 = 3.0, scaled like the
    earnings by the scenario's OE5 / oe5, so E5 / R5 = m5 = 10% and long_run_margin 6% gives the ratio 0.6."""
    flat = _direct(EZPW_PATH, ronic=0.135, long_run=dict(LR_FACTS, margin_ratio=None))
    facts_ratio = _direct(EZPW_PATH, ronic=0.135, long_run=LR_FACTS)
    # an older block (m_tc and cycle, no margin_ratio) holds the margin too
    older = _direct(EZPW_PATH, ronic=0.135, long_run={"e5": 0.30, "oe5": 0.28, "m5": 0.10, "m_tc": 0.06, "cycle": True,
                                                       "r_tc": 0.20, "stub_months": 8.5})
    assert older["long_run"]["margin_ratio"] is None and older["per_share_iv"] == flat["per_share_iv"]
    assert facts_ratio["long_run"]["margin_ratio"] is None and facts_ratio["per_share_iv"] == flat["per_share_iv"]
    cyc = _direct(EZPW_PATH, ronic=0.135, long_run=LR_FACTS, long_run_margin=0.06)
    oe5 = EZPW_BASE_CF * math.prod(1 + g for g in EZPW_PATH)
    assert cyc["long_run"]["year5_revenue"] == pytest.approx(3.0 * oe5 / 0.28, abs=1e-4) and cyc["long_run"]["margin_ratio"] == pytest.approx(0.6)
    assert cyc["per_share_iv"] < flat["per_share_iv"]
    # fewer fade years reach the long-run margin sooner, with the same ratio
    fast = _direct(EZPW_PATH, ronic=0.135, long_run=LR_FACTS, long_run_margin=0.06, fade_years=2)
    assert fast["long_run"]["margin_ratio"] == cyc["long_run"]["margin_ratio"] and fast["per_share_iv"] < cyc["per_share_iv"]


def test_a_negative_long_run_is_floored_and_stamped():
    lr = {"e5": -5.0, "oe5": 0.28, "m5": None}
    res = _direct(EZPW_PATH, ronic=0.135, long_run=lr)
    assert "long_run_floor" in res["stamps"] and res["long_run"]["floored"] is True
    assert res["terminal_value_pv"] == 0 and len(res["projected_cfs"]) == 5
    years_1_5 = sum(cf / 1.0891 ** (t + 1) for t, cf in enumerate(res["projected_cfs"]))
    assert res["per_share_iv"] == pytest.approx(years_1_5 / 0.061443, abs=0.02)


# ---- no reference in the facts (no consensus): a labelled fallback, never a refusal ------------------

def test_without_a_reference_the_long_run_uses_the_base_windows_net_income_ratio():
    with_ratio = _direct(EZPW_PATH, ronic=0.135, long_run={"ni_over_oe": 0.9})
    assert "long_run_base_ratio_ni" in with_ratio["stamps"]          # revision 17 (brief C7): was long_run_base_ratio
    oe5 = EZPW_BASE_CF * math.prod(1 + g for g in EZPW_PATH)
    assert with_ratio["long_run"]["year5_earnings"] == pytest.approx(0.9 * oe5, abs=1e-4)


def test_without_a_ratio_either_it_uses_owner_earnings_as_earnings_and_says_so():
    res = _direct(EZPW_PATH, ronic=0.135, long_run={"ni_over_oe": None})
    assert "long_run_on_owner_earnings" in res["stamps"]
    assert not any(s.startswith("long_run_base_ratio") for s in res["stamps"])
    oe5 = EZPW_BASE_CF * math.prod(1 + g for g in EZPW_PATH)
    assert res["long_run"]["year5_earnings"] == pytest.approx(oe5, abs=1e-4)
    # a non-positive ratio is no ratio; a call with no facts at all is not refused
    assert "long_run_on_owner_earnings" in _direct(EZPW_PATH, ronic=0.135, long_run={"ni_over_oe": -0.2})["stamps"]
    res = execute_financial_model(_call(_three(EZPW_PATH), guidance_deviation_reason="x", base_cf_reason="x"),
                                  {"price": 31.16, "shares_default_b": 0.061443})
    assert "error" not in res, res.get("error")


def test_no_terminal_ronic_anywhere_grows_at_the_cost_of_equity_and_is_stamped():
    res = _direct(EZPW_PATH, ronic=None)
    assert "terminal_ronic_at_cost_of_equity" in res["stamps"] and res["terminal_ronic"] == 0.0891
    unlimited = _direct(EZPW_PATH, ronic=INF, long_run={"r_tc": INF})
    assert unlimited["terminal_ronic"] == "unlimited" and unlimited["per_share_iv"] > res["per_share_iv"]


# ---- 4f: the valuation date -------------------------------------------------------------------------

def test_the_desk_values_at_the_base_fiscal_year_end_and_rolls_forward_by_the_stub():
    at_ye = _direct(EZPW_PATH, ronic=0.135, long_run={"stub_months": None})
    rolled = _direct(EZPW_PATH, ronic=0.135, long_run={"stub_months": 8.5})
    assert at_ye["valued_at"] == "base fiscal year end" and rolled["valued_at"] == "base fiscal year end, rolled forward"
    assert rolled["enterprise_value"] / at_ye["enterprise_value"] == pytest.approx(1.0891 ** (8.5 / 12), rel=1e-2)   # $B, 2 decimals
    assert rolled["roll_forward_factor"] == pytest.approx(1.0891 ** (8.5 / 12), abs=1e-6)
    assert rolled["per_share_iv"] == pytest.approx(at_ye["per_share_iv"] * 1.0891 ** (8.5 / 12), abs=0.02)


# ---- 4g/4h: finite life and the firm frame -----------------------------------------------------------

def test_a_finite_life_keeps_todays_owner_earnings_path_with_no_working_capital_roll_or_terminal():
    res = _direct(EZPW_PATH, ronic=0.135, finite_life_years=8, working_capital=WC,
                  long_run=dict(LR_FACTS))
    assert res["stamps"] == ["finite_life_owner_earnings"] and res["terminal_value_pv"] == 0
    assert "working_capital_deducted" not in res and len(res["projected_cfs"]) == 8
    plain = _direct(EZPW_PATH, finite_life_years=8)
    assert res["per_share_iv"] == plain["per_share_iv"]


def test_the_firm_frame_applies_the_same_long_run_and_stays_gated_by_wacc_reason():
    kw = dict(valuation_frame="firm", net_debt=-0.05)
    firm = _direct(EZPW_PATH, ronic=0.135, long_run=LR_FACTS, working_capital=WC, **kw)
    equity = _direct(EZPW_PATH, ronic=0.135, long_run=LR_FACTS, working_capital=WC)
    assert "error" not in firm and firm["enterprise_value"] == equity["enterprise_value"]
    assert firm["equity_value"] == pytest.approx(firm["enterprise_value"] + 0.05, abs=0.02)
    res = execute_financial_model(_call(_three(EZPW_PATH), valuation_frame="firm", net_debt=-0.05,
                                        guidance_deviation_reason="x", interest_addback=0.01),
                                  dict(EZPW_CTX, net_debt_default_b=-0.05))
    assert res["validation_error"] is True and any(n["reason"] == "wacc_reason" for n in res["needs_reasons"])


# ---- 4a: the exit multiple and the terminal leg are gone ---------------------------------------------

def test_exit_multiple_and_terminal_leg_are_refused_as_removed_fields_with_a_clear_message():
    for field, value in (("terminal_exit_multiple", 18.0), ("terminal_leg", "exit")):
        scs = _three(EZPW_PATH)
        scs[0][field] = value
        res = execute_financial_model(_call(scs, guidance_deviation_reason="x"), dict(EZPW_CTX))
        assert res["validation_error"] is True and "scenario_dcfs" not in res
        assert any(field in m and "removed in revision 17" in m and "terminal_ronic" in m for m in res["missing"])
        top = _call(_three(EZPW_PATH), guidance_deviation_reason="x", **{field: value})
        assert any(field in m for m in execute_financial_model(top, dict(EZPW_CTX))["missing"])


@pytest.mark.parametrize("bad", ["0.12", True, float("nan"), [0.1]])
def test_a_terminal_ronic_the_desk_cannot_read_is_refused_not_replaced_by_the_default(bad):
    scs = _three(EZPW_PATH)
    scs[0]["terminal_ronic"] = bad
    res = execute_financial_model(_call(scs, guidance_deviation_reason="x"), dict(EZPW_CTX))
    assert res["validation_error"] is True and "scenario_dcfs" not in res
    assert any("terminal_ronic in Base" in m and "a number" in m for m in res["missing"])
    top = execute_financial_model(_call(_three(EZPW_PATH), guidance_deviation_reason="x", terminal_ronic=bad), dict(EZPW_CTX))
    assert any(m.startswith("terminal_ronic (a number") for m in top["missing"])


def test_more_than_five_explicit_rates_are_refused_for_a_perpetual_value():
    res = _direct([0.05] * 6)
    assert res["validation_error"] is True and "years 1-5" in res["error"] and "terminal_ronic" in res["error"]
    assert "error" not in _direct([0.05] * 6, finite_life_years=10)      # a finite life keeps its own path


def test_fewer_than_five_rates_continue_the_old_three_stage_fade():
    # revision 16's path for 2 rates and a 5-year fade: years 3-7 fade from 0.10 to the terminal 0.04
    res = _direct([0.10, 0.10], ronic=INF, long_run={"r_tc": INF}, terminal_g=0.04, fade_years=5)
    fade = [0.10 + (0.04 - 0.10) * i / 5 for i in range(1, 6)]
    assert res["growth_rates_applied"] == pytest.approx([0.10, 0.10] + [round(g, 4) for g in fade], abs=1e-4)
    cf, pv = 0.148, 0.0
    for t, g in enumerate([0.10, 0.10] + fade, start=1):
        cf *= 1 + g
        pv += cf / 1.0891 ** t
    pv += cf * 1.04 / (0.0891 - 0.04) / 1.0891 ** 7
    assert res["per_share_iv"] == pytest.approx(pv / 0.061443, abs=0.02)


# ---- 4i: the sbc_dilution unit rule -------------------------------------------------------------------

@pytest.mark.parametrize("value, new_shares", [(0.02, 0.061443 * 0.02), (5_000_000, 0.005), (1_000_000, 0.001)])
def test_sbc_dilution_is_a_fraction_below_1_or_a_whole_count_of_new_shares(value, new_shares):
    res = _direct(EZPW_PATH, ronic=0.135, sbc_treatment="add_back_dilution", sbc_dilution=value)
    assert "error" not in res, res.get("error")
    assert res["shares_diluted"] == round(0.061443 + new_shares, 4)


@pytest.mark.parametrize("value", [2.5, 1.0, 999_999])
def test_sbc_dilution_between_1_and_1_000_000_is_refused_with_the_rule_in_the_message(value):
    res = _direct(EZPW_PATH, ronic=0.135, sbc_treatment="add_back_dilution", sbc_dilution=value)
    assert res["validation_error"] is True
    assert res["error"] == "sbc_dilution is a fraction below 1 (0.02 = 2%) or a whole number of new shares"
    # through the call the refusal reaches the model as a refused desk run
    out = execute_financial_model(_call(_three(EZPW_PATH), sbc_treatment="add_back_dilution", sbc_dilution=value,
                                        guidance_deviation_reason="x"), dict(EZPW_CTX))
    assert out["validation_error"] is True and "sbc_dilution is a fraction below 1" in out["error"]


# ---- the harness reads what the desk applied -----------------------------------------------------------

def test_the_harness_matches_a_held_base_to_the_path_the_desk_valued():
    """A Base the desk held at the levels was valued on the desk's path: the matched inputs (and the contract's
    stage1_growth_path, which contract_fill reads from the same echo) carry that path, not the requested one."""
    params = _call(_three(EZPW_PATH))
    res = execute_financial_model(params, dict(EZPW_CTX))
    base = res["scenario_dcfs"][0]["dcf"]
    assert base["years12_held"] is True and base["explicit_growth"] != EZPW_PATH
    call = {"tool": "run_financial_model", "params": params, "result": res}
    info = cv.extract_desk_snapshot_metrics(snapshot=[call], base_iv=base["per_share_iv"], coe_used=0.0891,
                                            ticker="EZPW", facts={"shares_outstanding": 61443377.0})
    assert info["desk_iv_match"] is True
    assert info["desk_matched_inputs"]["stage1_growth_path"] == base["explicit_growth"]
    assert info["desk_years35_capped"] is False          # a held Base is not a years-3-5 cap
    import contract_fill
    filled, _ = contract_fill.fill([dict(call, call_index=1)], {}, {"shares_outstanding": 61443377.0}, 31.16)
    assert filled["stage1_growth_path"] == base["explicit_growth"] and filled["base_iv"] == base["per_share_iv"]
