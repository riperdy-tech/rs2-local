"""Revision 19, Part A (the price-implied solver) and Part J (the own-structure reverse DCF on the same routine): bars P1 (a)-(f).

  (a) closed forms: the implied coe and terminal_g of a structure whose value is known in closed form;
  (b) substitution: for every input on synthetic Bases (a growth path, a hold, a years 3-5 cap, the firm frame, a finite life, working capital
      and excess cash on and off, RONIC +inf), substituting the returned value into unbundled_dcf reproduces the price within $0.01, unrounded;
  (c) reachability: not_reachable exactly when the price lies outside the values over the bound, at prices just inside and just outside both ends;
  (d) fade: the two bracketing integers' values straddle the price;
  (e) identity: the rebuilt Base equals the desk's unrounded value for runs with one to five explicit rates;
  (f) non-monotone: roots_on_grid above 1 and the root nearest the run's own value is chosen.
Part J: the same routine on the own-structure reverse DCF (closed form, substitution, reachability, the non-monotone case, no midpoint on an error).

Fixtures are synthetic (numbers written for the test, or the W9 fixture of test_rev17f_redesign).
"""
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import financial_model_tool as fmt  # noqa: E402
from test_rev17f_redesign import _w9_reference  # noqa: E402
from test_rev18_part1 import B, _desk_call, _desk_ctx  # noqa: E402

INF = math.inf
RF_EFF, GDP = 0.04, 0.0446


def _b(**over):
    """A synthetic Base as the solver takes it: five rates, a fade, no long-run facts (owner earnings carry the long run), equity frame."""
    b = {"cf": 1.0, "growth": [0.10, 0.09, 0.08, 0.07, 0.06], "fade": 5, "wacc": 0.09, "tg": 0.03, "shares": 1.0, "sbc": "deducted_in_cf",
         "sbc_dil": None, "frame": "equity", "net_debt": 0.0, "rate_type": None, "annuity": 0.0, "annuity_cap": None, "ronic": INF, "wc": None,
         "excess": None, "long_run": None, "finite": None}
    b.update(over)
    b["raw"] = fmt.unbundled_dcf(base_cf=b["cf"], explicit_growth=list(b["growth"]), wacc=b["wacc"], terminal_g=b["tg"], fade_years=b["fade"],
                                 terminal_ronic=b["ronic"], annuity_flow=b["annuity"], annuity_cap_rate=b["annuity_cap"], net_debt=b["net_debt"],
                                 shares_diluted=b["shares"], valuation_frame=b["frame"], rate_type=b["rate_type"], sbc_treatment=b["sbc"],
                                 sbc_dilution=b["sbc_dil"], finite_life_years=b["finite"], long_run=b["long_run"], working_capital=b["wc"],
                                 excess_cash=b["excess"], long_run_margin=b.get("lrm"))["per_share_iv_raw"]
    return b


def _value(b, *, rates=None, fade=None, wacc=None, tg=None, ronic=None, lrm=None):
    """The Base's unrounded value through unbundled_dcf, on its normalised five rates, with the named input moved: the test's own substitution."""
    r0, left = fmt._pi_normalise(b["growth"], b["tg"], b["fade"], b["finite"])
    first = fmt.unbundled_dcf(base_cf=b["cf"], explicit_growth=r0, wacc=b["wacc"], terminal_g=b["tg"], fade_years=left, terminal_ronic=b["ronic"],
                              annuity_flow=b["annuity"], annuity_cap_rate=b["annuity_cap"], net_debt=b["net_debt"], shares_diluted=b["shares"],
                              valuation_frame=b["frame"], rate_type=b["rate_type"], sbc_treatment=b["sbc"], sbc_dilution=b["sbc_dil"],
                              finite_life_years=b["finite"], long_run=b["long_run"], working_capital=b["wc"], excess_cash=b["excess"],
                              long_run_margin=b.get("lrm"))      # revision 24 step 2a: the Base's long_run_margin, as price_implied passes it
    applied = first.get("terminal_ronic")
    applied = INF if applied == "unlimited" else applied
    out = fmt.unbundled_dcf(base_cf=b["cf"], explicit_growth=r0 if rates is None else rates, wacc=b["wacc"] if wacc is None else wacc,
                            terminal_g=b["tg"] if tg is None else tg, fade_years=left if fade is None else fade,
                            terminal_ronic=applied if ronic is None else ronic, annuity_flow=b["annuity"], annuity_cap_rate=b["annuity_cap"],
                            net_debt=b["net_debt"], shares_diluted=b["shares"], valuation_frame=b["frame"], rate_type=b["rate_type"],
                            sbc_treatment=b["sbc"], sbc_dilution=b["sbc_dil"], finite_life_years=b["finite"], long_run=b["long_run"],
                            working_capital=b["wc"], excess_cash=b["excess"], long_run_margin=b.get("lrm") if lrm is None else lrm)
    assert "error" not in out, out
    return out["per_share_iv_raw"]


def _substitute(b, name, blk):
    """The Base's value with the solver's returned value substituted for the input `name`."""
    r0, left = fmt._pi_normalise(b["growth"], b["tg"], b["fade"], b["finite"])
    v = blk["value"]
    if name == "coe":
        return _value(b, wacc=v)
    if name == "terminal_g":
        return _value(b, tg=v)
    if name == "terminal_ronic":
        return _value(b, ronic=INF if v == "unlimited" else v)
    if name == "growth_years_3_5":
        d = blk["shift"]
        rates = r0[:2] + [g + d for g in r0[2:5]] + r0[5:]
        assert fmt._geo_mean_growth(rates[2:5]) == pytest.approx(v, abs=1e-12)
        return _value(b, rates=rates)
    if name == "year2_level":
        cf1 = b["cf"] * (1.0 + r0[0])
        return _value(b, rates=[r0[0], v / cf1 - 1.0] + r0[2:])
    if name == "long_run_margin":                       # revision 24 step 2b: the Base's long-run earnings margin
        return _value(b, lrm=v)
    raise AssertionError(name)


LEVELS = {"year1": 1.1, "year2": 1.2, "bull2": 1.6, "bear2": 0.8}


def _pi(b, price, **kw):
    kw.setdefault("rf_eff", RF_EFF)
    kw.setdefault("gdp_trend", GDP)
    kw.setdefault("levels", LEVELS)
    return fmt.price_implied(b, price, **kw)


# ---- (a) closed forms --------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("g,r,price", [(0.03, 0.09, 12.0), (0.02, 0.08, 20.0), (0.04, 0.10, 8.0)])
def test_the_implied_coe_is_cf1_over_price_plus_g(g, r, price):
    """Every year grows at g, fade 0, RONIC +inf, no working capital, roll-forward or cash: V = CF1 / (r - g), so the implied coe is CF1 / P + g."""
    cf = 1.0
    b = _b(cf=cf, growth=[g] * 5, tg=g, fade=0, wacc=r, ronic=INF)
    assert b["raw"] == pytest.approx(cf * (1 + g) / (r - g), abs=1e-9)             # the closed form itself
    blk = _pi(b, price)["coe"]
    assert blk["reachable"] and blk["value"] == pytest.approx(cf * (1 + g) / price + g, abs=1e-6)
    assert blk["base_at_value"] == pytest.approx(price, abs=0.0006) and blk["roots_on_grid"] == 1


@pytest.mark.parametrize("r,price", [(0.09, 17.0), (0.08, 18.0), (0.10, 12.0)])
def test_the_implied_terminal_g_is_the_root_of_the_closed_form(r, price):
    """Years 1-5 grow at 0, fade 0, RONIC +inf, no working capital, roll-forward or cash: P = PV(1-5) + CF5 (1 + g) / ((r - g)(1 + r)^5)."""
    cf = 1.0
    b = _b(cf=cf, growth=[0.0] * 5, tg=0.02, fade=0, wacc=r, ronic=INF)
    pv15 = sum(cf / (1 + r) ** t for t in range(1, 6))
    k = (price - pv15) * (1 + r) ** 5 / cf               # (1 + g) = K (r - g)
    g_closed = (k * r - 1.0) / (1.0 + k)
    assert 0.0 <= g_closed < min(GDP, r)
    blk = _pi(b, price)["terminal_g"]
    assert blk["reachable"] and blk["value"] == pytest.approx(g_closed, abs=1e-6)
    assert blk["base_at_value"] == pytest.approx(price, abs=0.0006)


# ---- (b) substitution ----------------------------------------------------------------------------------------------------------------

def _case_desk(**mods):
    """(call, ctx) on the W9 fixture, with the named modifications."""
    ref = _w9_reference()
    return ref, mods


def _spy(monkeypatch):
    seen = []
    real = fmt.price_implied

    def wrapped(b, price, **kw):
        out = real(b, price, **kw)
        seen.append((dict(b), price, kw, out))
        return out
    monkeypatch.setattr(fmt, "price_implied", wrapped)
    return seen


def _desk_run(monkeypatch, *, price_factor, call_mod=None, ctx_mod=None):
    """One desk call on the W9 fixture at price = price_factor x the Base's value; returns (result, (b, price, kw, price_implied))."""
    ref = _w9_reference()
    call, ctx = _desk_call(ref), _desk_ctx(ref, rf_eff=RF_EFF, nominal_gdp_trend=GDP, price=1e6)
    if ctx_mod:
        ctx_mod(ref, ctx)
    if call_mod:
        call_mod(ref, call)
    # a Bull and a Bear on the reference path, a little above and below it, so the scenario order holds whatever the Base was changed to
    n = len(call["scenarios"][0]["explicit_growth"])
    for sc, d in ((call["scenarios"][1], 0.03), (call["scenarios"][2], -0.03)):
        sc["explicit_growth"] = [g + d for g in ref["path"][:n]]
        if call["scenarios"][0].get("terminal_ronic") is not None:
            sc["terminal_ronic"] = call["scenarios"][0]["terminal_ronic"]
    probe = fmt.execute_financial_model(_copy(call), dict(ctx, price=1e6))
    assert "error" not in probe, probe.get("error")
    base_value = probe["scenario_dcfs"][0]["dcf"]["per_share_iv"]
    seen = _spy(monkeypatch)
    out = fmt.execute_financial_model(_copy(call), dict(ctx, price=round(base_value * price_factor, 2)))
    assert "error" not in out, out.get("error")
    assert len(seen) == 1
    return out, seen[0]


def _copy(x):
    import copy
    return copy.deepcopy(x)


def _c_wc_off(ref, ctx):
    ctx["working_capital"] = None


def _c_cash(ref, ctx):
    ctx["excess_cash"] = 1.0
    ctx["base_year_cash_and_investments_b"] = 1.5


def _c_levels_range(ref, ctx):
    lv = ctx["levels"]
    ctx["levels"] = dict(lv, bull2=lv["year2"] * 1.10, bear2=lv["year2"] * 0.90)


def _m_hold(ref, call):
    call["scenarios"][0]["explicit_growth"] = [ref["path"][0], ref["path"][1] + 0.20] + list(ref["path"][2:])
    call.pop("guidance_deviation_reason", None)


def _c_cap(ref, ctx):
    ctx["years35_cap"] = 0.03


def _m_cap(ref, call):
    call.pop("guidance_deviation_reason", None)


def _m_firm(ref, call):
    call.update(valuation_frame="firm", net_debt=0.004, interest_addback=0.002, wacc_reason="the anchor", net_debt_reason="d")
    for sc in call["scenarios"]:
        sc["wacc"] = sc["wacc"]          # the same rates; the firm frame pairs them with true_wacc
    call["rate_type"] = "true_wacc"


def _c_firm(ref, ctx):
    ctx["net_debt_default_b"] = 0.004


def _m_finite(ref, call):
    call["cash_flow_life"] = 15


def _m_inf(ref, call):
    call["scenarios"][0]["terminal_ronic"] = INF


def _m_few_rates(n):
    def mod(ref, call):
        for sc in call["scenarios"]:
            sc["explicit_growth"] = list(ref["path"][:n])
        call.pop("guidance_deviation_reason", None)
    return mod


CASES = {
    "growth_path": dict(),
    "working_capital_off": dict(ctx_mod=_c_wc_off),
    "excess_cash_on": dict(ctx_mod=_c_cash),
    "hold": dict(call_mod=_m_hold),
    "years35_cap": dict(call_mod=_m_cap, ctx_mod=_c_cap),
    "firm_frame": dict(call_mod=_m_firm, ctx_mod=_c_firm),
    "finite_life": dict(call_mod=_m_finite),
    "ronic_inf": dict(call_mod=_m_inf),
    "range_levels": dict(ctx_mod=_c_levels_range),
    "one_rate": dict(call_mod=_m_few_rates(1)),
    "two_rates": dict(call_mod=_m_few_rates(2)),
    "three_rates": dict(call_mod=_m_few_rates(3)),
    "four_rates": dict(call_mod=_m_few_rates(4)),
}
PRICE_FACTORS = (0.6, 0.85, 0.95, 1.04, 1.15, 1.7)


def test_substituting_the_returned_value_reproduces_the_price_for_every_input_on_every_synthetic_base(monkeypatch):
    reached = {n: 0 for n in fmt.PI_INPUTS}
    unreached = {n: 0 for n in fmt.PI_INPUTS}
    for case, kw in CASES.items():
        for pf in PRICE_FACTORS:
            out, (b, price, _kw, pi) = _desk_run(monkeypatch, price_factor=pf, **kw)
            assert "error" not in pi, (case, pf, pi)
            assert set(pi) == set(fmt.PI_INPUTS) and out["price_implied"] is pi
            for name in fmt.PI_INPUTS:
                blk = pi[name]
                if name == "fade_years":
                    continue                                                                    # (d) below
                if not blk["reachable"]:
                    unreached[name] += 1
                    assert blk["value"] is None and blk["base_at_value"] is None
                    continue
                reached[name] += 1
                got = _substitute(b, name, blk)
                assert abs(got - price) <= 0.01, (case, pf, name, got, price)
                assert abs(blk["base_at_value"] - price) <= 0.01
    for name, least in (("coe", 20), ("growth_years_3_5", 20), ("terminal_g", 3), ("terminal_ronic", 3), ("year2_level", 2), ("long_run_margin", 3)):
        assert reached[name] >= least, (name, reached, unreached)                       # the test is not vacuous for any input
    assert unreached["terminal_g"] > 0 and unreached["year2_level"] > 0                     # and it meets unreachable ones too


def test_the_hold_and_the_cap_are_in_the_base_the_solver_holds(monkeypatch):
    """The solver takes the Base as the desk applied it: the held years 1-2 and the capped years 3-5, not the model's own path."""
    out, (b, price, _kw, pi) = _desk_run(monkeypatch, price_factor=1.15, call_mod=_m_hold)
    base = out["scenario_dcfs"][0]["dcf"]
    assert base["years12_held"] is True
    assert b["growth"][:2] == pytest.approx(out["years12_held"]["dcfs"][0]["held_growth_years12"], abs=1e-4)
    assert pi["coe"]["own"] == pytest.approx(b["wacc"]) and b["raw"] == pytest.approx(base["per_share_iv_raw"], abs=1e-12)
    out, (b, price, _kw, pi) = _desk_run(monkeypatch, price_factor=1.15, call_mod=_m_cap, ctx_mod=_c_cap)
    assert out["years35_cap"]["dcfs"][0]["applied_years35"] == [0.03, 0.03, 0.03]
    assert max(b["growth"][2:5]) <= 0.03 + 1e-12
    assert pi["growth_years_3_5"]["own"] == pytest.approx(0.03, abs=1e-9)


def test_the_own_values_are_the_bases_applied_ones(monkeypatch):
    out, (b, price, _kw, pi) = _desk_run(monkeypatch, price_factor=1.15)
    five, left = fmt._pi_normalise(b["growth"], b["tg"], b["fade"], b["finite"])
    assert pi["coe"]["own"] == b["wacc"] and pi["terminal_g"]["own"] == b["tg"] and pi["fade_years"]["own"] == left
    assert pi["growth_years_3_5"]["own"] == pytest.approx(fmt._geo_mean_growth(five[2:5]), abs=1e-12)
    assert pi["terminal_ronic"]["own"] == out["scenario_dcfs"][0]["dcf"]["terminal_ronic"]
    assert pi["year2_level"]["own"] == pytest.approx(b["cf"] * (1 + five[0]) * (1 + five[1]), abs=1e-12)


def test_a_finite_life_base_has_no_terminal_ronic_and_the_rest_are_solved(monkeypatch):
    out, (b, price, _kw, pi) = _desk_run(monkeypatch, price_factor=1.15, call_mod=_m_finite)
    assert b["finite"] == 15
    assert pi["terminal_ronic"]["not_available"] == "not applicable (finite life)" and pi["terminal_ronic"]["reachable"] is False
    assert pi["coe"]["reachable"] is True
    assert abs(_substitute(b, "coe", pi["coe"]) - price) <= 0.01


def test_no_price_implied_for_a_refused_call_a_blend_call_or_a_bull_or_bear(monkeypatch):
    ref = _w9_reference()
    ctx = _desk_ctx(ref, rf_eff=RF_EFF, nominal_gdp_trend=GDP, price=50.0)
    refused = fmt.execute_financial_model(_desk_call(ref, cash_flow_life=None), ctx)
    assert refused.get("validation_error") and "price_implied" not in refused
    blend = fmt.execute_financial_model({"mode": "blend", "legs": [{"name": "a", "weight": 1.0, "iv": 10.0}]}, ctx)
    assert "price_implied" not in blend
    out = fmt.execute_financial_model(_desk_call(ref), dict(ctx, price=ref["value"]))
    assert "error" not in out and set(out["price_implied"]) == set(fmt.PI_INPUTS)
    # only the Base's block: a Bull or Bear entry carries none
    assert all("price_implied" not in sc["dcf"] for sc in out["scenario_dcfs"])


def test_a_top_level_single_dcf_counts_as_a_base(monkeypatch):
    ref = _w9_reference()
    call = _desk_call(ref)
    sc = call.pop("scenarios")[0]
    call.update(base_cf=sc["base_cf"], explicit_growth=sc["explicit_growth"], wacc=sc["wacc"])
    out = fmt.execute_financial_model(call, _desk_ctx(ref, rf_eff=RF_EFF, nominal_gdp_trend=GDP, price=ref["value"] * 1.1))
    assert "error" not in out and "price_implied" in out and out["price_implied"]["coe"]["reachable"]


def test_the_bounds_of_the_inputs_as_the_brief_sets_them():
    b = _b()
    pi = _pi(b, 20.0)
    assert pi["coe"]["bound"]["low"] == max(RF_EFF, b["tg"] + 0.0001) and pi["coe"]["bound"]["high"] == 0.25
    assert pi["terminal_g"]["bound"]["low"] == 0.0 and pi["terminal_g"]["bound"]["high"] == pytest.approx(min(GDP, b["wacc"]) - 0.000001)
    assert pi["terminal_ronic"]["bound"]["low"] == b["wacc"] and pi["terminal_ronic"]["bound"]["high"] == "unlimited"
    assert pi["fade_years"]["bound"]["low"] == 0 and pi["fade_years"]["bound"]["high"] == 60
    assert pi["year2_level"]["bound"]["low"] == LEVELS["bear2"] and pi["year2_level"]["bound"]["high"] == LEVELS["bull2"]
    # the growth bound: 1 + g + shift >= 0.001 for each of years 3-5, and a ceiling of 10 for the largest
    y35 = b["growth"][2:5]
    assert pi["growth_years_3_5"]["shift_bound"] == pytest.approx([(0.001 - 1.0) - min(y35), 10.0 - max(y35)])
    # without rf_eff, nominal_gdp_trend or a bull2/bear2 range the entry is not available, never replaced by another bound
    none = _pi(b, 20.0, rf_eff=None, gdp_trend=None, levels={"year1": 1.1, "year2": 1.2})
    assert none["coe"]["not_available"] == "rf_eff is not available"
    assert none["terminal_g"]["not_available"] == "nominal_gdp_trend is not available"
    assert none["year2_level"]["not_available"] == "the pack prints no bull2 and bear2 range"
    assert all(none[k]["reachable"] is False and none[k]["bound"]["low"] is None for k in ("coe", "terminal_g", "year2_level"))
    assert none["growth_years_3_5"]["reachable"] and none["fade_years"]["bound"]["high"] == 60


# ---- (c) reachability -----------------------------------------------------------------------------------------------------------------

def _grid_values(b, name, bound):
    """The values of the Base over the bound's 121-point grid, computed here independently of the solver."""
    r0, _left = fmt._pi_normalise(b["growth"], b["tg"], b["fade"], b["finite"])
    pts = fmt._linspace(bound["low"], bound["high"], 121) if name != "terminal_ronic" else fmt._linspace(0.0, 1.0, 121)
    out = []
    for s in pts:
        if name == "coe":
            out.append(_value(b, wacc=s))
        elif name == "terminal_g":
            out.append(_value(b, tg=s))
        elif name == "terminal_ronic":
            out.append(_value(b, ronic=INF if s == 0.0 else b["wacc"] / s))
        else:
            out.append(_value(b, rates=[r0[0], s / (b["cf"] * (1 + r0[0])) - 1.0] + r0[2:]))
    return out


@pytest.mark.parametrize("name", ["coe", "terminal_g", "terminal_ronic", "year2_level"])
def test_not_reachable_exactly_when_the_price_is_outside_the_values_over_the_bound(name):
    b = _b(growth=[0.12, 0.10, 0.08, 0.07, 0.06], tg=0.03, ronic=0.12, wacc=0.09)
    bd = _pi(b, 15.0)[name]["bound"]
    vals = _grid_values(b, name, bd)
    top, bottom = max(vals), min(vals)
    assert top > bottom
    eps = 0.01
    inside_top = _pi(b, top - eps)[name]
    inside_bottom = _pi(b, bottom + eps)[name]
    above = _pi(b, top + eps)[name]
    below = _pi(b, bottom - eps)[name]
    assert inside_top["reachable"] and inside_bottom["reachable"]
    assert not above["reachable"] and above["side"] == "above" and above["roots_on_grid"] == 0
    assert not below["reachable"] and below["side"] == "below" and below["roots_on_grid"] == 0
    # the bound and the values at its ends are recorded on the unreachable block
    assert above["bound"] == bd and above["value"] is None and above["base_at_value"] is None
    # and reachable inside, the substitution holds
    assert abs(_substitute(b, name, inside_top) - (top - eps)) <= 0.01
    assert abs(_substitute(b, name, inside_bottom) - (bottom + eps)) <= 0.01


def test_the_value_is_monotone_in_terminal_ronic_up_to_unlimited_and_the_solver_says_so():
    """Was `test_the_value_is_not_monotone_in_terminal_ronic_near_unlimited_and_the_solver_says_so`: +inf was its own case in the long run (the
    start held until the last fade year), so the value over [coe, +inf] was not monotone and a price just above the +inf end was reached at a
    finite return across a jump. Revision 24 step 2a (D4): an unlimited RONIC_T is the limit of a large finite one, the value rises to it, and a
    price just above the +inf end is not reachable, with no jump and no root."""
    b = _b(growth=[0.12, 0.10, 0.08, 0.07, 0.06], tg=0.03, ronic=0.12, wacc=0.09)
    bd = _pi(b, 15.0)["terminal_ronic"]["bound"]
    vals = [_value(b, ronic=x) for x in (0.09, 0.12, 0.2, 0.5, 1.0, 10.0, 1e6, INF)]
    assert all(y >= x for x, y in zip(vals, vals[1:])) and bd["value_high"] == pytest.approx(vals[-1], abs=1e-9)
    blk = _pi(b, bd["value_high"] + 0.01)["terminal_ronic"]
    assert not blk["reachable"] and blk["side"] == "above" and blk["roots_on_grid"] == 0 and blk["discontinuities"] == 0
    assert "discontinuity" not in blk["stamps"]


def test_a_value_at_the_end_of_the_bound_is_a_root_within_the_tolerance():
    b = _b(ronic=0.12)
    bd = _pi(b, 15.0)["coe"]["bound"]
    exact = _pi(b, bd["value_high"])["coe"]
    assert exact["reachable"] and exact["value"] == pytest.approx(bd["high"], abs=1e-9) and exact["bracket"][0] == exact["bracket"][1]


# ---- (d) the fade ---------------------------------------------------------------------------------------------------------------------

def test_the_two_bracketing_integers_straddle_the_price():
    b = _b(growth=[0.12, 0.10, 0.08, 0.07, 0.06], tg=0.03, ronic=0.15, wacc=0.09, fade=5)
    every = [_value(b, fade=n) for n in range(0, 61)]
    lo_v, hi_v = min(every), max(every)
    assert lo_v < b["raw"] < hi_v
    # the Base's own price is its own fade exactly (a point bracket); the others lie between two integers
    own = _pi(b, b["raw"])["fade_years"]
    assert own["reachable"] and own["bracket_years"] == [5, 5] and own["value"] == 5.0
    for price in (lo_v + 0.2 * (hi_v - lo_v), lo_v + 0.8 * (hi_v - lo_v)):
        blk = _pi(b, price)["fade_years"]
        assert blk["reachable"], price
        f0, f1 = blk["bracket_years"]
        v0, v1 = blk["bracket_values"]
        assert f1 == f0 + 1 and min(v0, v1) <= price <= max(v0, v1)
        assert v0 == pytest.approx(_value(b, fade=f0), abs=1e-9) and v1 == pytest.approx(_value(b, fade=f1), abs=1e-9)
        # the value reported: F + (P - v(F)) / (v(F + 1) - v(F))
        assert blk["value"] == pytest.approx(f0 + (price - v0) / (v1 - v0), abs=1e-9) and f0 <= blk["value"] <= f1
        assert blk["base_at_value"] == price and blk["bracket"] == [f0, f1]


def test_a_fade_that_hits_the_price_exactly_is_its_own_bracket():
    # revision 24 step 2a: an unlimited return (it was 15%; with the charge moving linearly in 1 / RONIC that Base's value peaks at a fade of 6, so
    # the price at 7 has a second, nearer root at 4.87; this test is about an exact integer hit, not about which of two roots is nearer)
    b = _b(ronic=INF)
    five, left = fmt._pi_normalise(b["growth"], b["tg"], b["fade"], None)
    price = _value(b, fade=7)
    blk = _pi(b, price)["fade_years"]
    assert blk["reachable"] and blk["value"] == 7.0 and blk["bracket_years"] == [7, 7]


# ---- (e) identity ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_the_rebuilt_base_reproduces_the_desks_unrounded_value_for_one_to_five_explicit_rates(n):
    rates = [0.11, 0.09, 0.07, 0.06, 0.05][:n]
    for fade in (0, 3, 5, 8):
        b = _b(growth=rates, fade=fade, ronic=0.12)
        r0, left = fmt._pi_normalise(rates, b["tg"], fade, None)
        assert len(r0) == 5 and left == (max(0, fade - (5 - n)) if n < 5 else fade)
        pi = _pi(b, b["raw"] * 1.2)
        assert "error" not in pi, (n, fade, pi)


def test_the_identity_check_refuses_a_base_that_does_not_reproduce_and_the_echo_would_not():
    b = _b(growth=[0.1234567, 0.0912345, 0.0801234, 0.0709876, 0.0605432], ronic=0.12)
    assert "error" not in _pi(b, b["raw"] * 1.2)
    # a Base value that is not the one its own arguments give (the harness would only meet this through a code defect): the block is an error
    broken = dict(b, raw=b["raw"] + 0.01)
    pi = _pi(broken, b["raw"] * 1.2)
    assert pi["error"] == "identity" and set(pi) >= {"error", "base_per_share_iv_raw", "rebuilt_per_share_iv_raw"}
    # the desk's 4-decimal echo of the applied rates is not the Base: rebuilding from it misses by more than the tolerance
    echo = [round(g, 4) for g in b["growth"]]
    off = fmt.unbundled_dcf(base_cf=b["cf"], explicit_growth=echo, wacc=b["wacc"], terminal_g=b["tg"], fade_years=b["fade"], shares_diluted=1.0,
                            sbc_treatment="deducted_in_cf", terminal_ronic=0.12)["per_share_iv_raw"]
    assert abs(off - b["raw"]) > fmt.IDENTITY_TOL


def test_a_finite_life_base_with_more_than_five_rates_keeps_them_and_still_rebuilds():
    b = _b(growth=[0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01], finite=10, fade=0, tg=0.0)
    r0, left = fmt._pi_normalise(b["growth"], b["tg"], b["fade"], b["finite"])
    assert r0 == b["growth"] and left == 0
    pi = _pi(b, b["raw"] * 0.9)
    assert "error" not in pi and pi["coe"]["reachable"]
    assert abs(_substitute(b, "coe", pi["coe"]) - b["raw"] * 0.9) <= 0.01


def test_the_unrounded_value_is_in_both_dcfs_and_every_rounded_key_is_as_it_was():
    perp = fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.1] * 5, wacc=0.09, terminal_g=0.03, shares_diluted=0.7, fade_years=5,
                             sbc_treatment="deducted_in_cf", terminal_ronic=0.12)
    fin = fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.1] * 5, wacc=0.09, terminal_g=0.03, shares_diluted=0.7, fade_years=5,
                            sbc_treatment="deducted_in_cf", finite_life_years=12)
    for r in (perp, fin):
        assert r["per_share_iv"] == round(r["per_share_iv_raw"], 2) and r["per_share_iv_raw"] != r["per_share_iv"]


# ---- (f) the solver on a non-monotone function ----------------------------------------------------------------------------------

def test_a_non_monotone_function_counts_its_roots_and_chooses_the_root_nearest_the_own_value():
    f = lambda s: (s - 1.0) * (s - 2.0) * (s - 3.0) * 7.0           # three roots, at 1, 2 and 3
    pts = [i * 0.05 for i in range(0, 81)]                           # 0 .. 4, on the grid at every root
    for s0, want in ((0.0, 1.0), (1.4, 1.0), (1.6, 2.0), (2.4, 2.0), (2.6, 3.0), (4.0, 3.0)):
        r = fmt.solve_nearest(f, pts, s0, all_roots=True)
        assert r["found"] and r["roots_on_grid"] == 3 and r["s"] == pytest.approx(want, abs=1e-6), (s0, r["s"])
        assert r["roots"] == pytest.approx([1.0, 2.0, 3.0], abs=1e-6)
    # a tie goes to the lower bracket
    tie = fmt.solve_nearest(lambda s: (s - 1.0) * (s - 3.0), [i * 0.5 for i in range(0, 9)], 2.0)
    assert tie["s"] == pytest.approx(1.0, abs=1e-6)
    # off the grid, between roots: the bracket's own distance decides
    r = fmt.solve_nearest(lambda s: math.sin(s), [i * 0.3 for i in range(0, 40)], 3.0)
    assert r["roots_on_grid"] == 4 and r["s"] == pytest.approx(math.pi, abs=1e-6)       # 0, pi, 2 pi and 3 pi are on [0, 11.7]


def test_a_non_monotone_input_is_stamped_in_the_block(monkeypatch):
    b = _b(growth=[0.12, 0.10, 0.08, 0.07, 0.06], ronic=0.12)
    real = fmt.unbundled_dcf

    def bent(**kw):
        r = real(**kw)
        if not r.get("error"):
            g = kw["terminal_g"]
            r = dict(r, per_share_iv_raw=r["per_share_iv_raw"] + 40.0 * math.sin(g * 400.0))     # a wiggle in terminal_g
        return r
    monkeypatch.setattr(fmt, "unbundled_dcf", bent)
    b["raw"] = bent(base_cf=b["cf"], explicit_growth=b["growth"], wacc=b["wacc"], terminal_g=b["tg"], fade_years=b["fade"], shares_diluted=1.0,
                    sbc_treatment="deducted_in_cf", terminal_ronic=0.12)["per_share_iv_raw"]
    blk = _pi(b, b["raw"])["terminal_g"]
    assert blk["roots_on_grid"] > 1 and "non_monotone" in blk["stamps"] and blk["reachable"]
    # the root nearest the own value: the own value itself is a root here
    assert blk["value"] == pytest.approx(b["tg"], abs=1e-6)


def test_solver_edge_cases():
    # an evaluation that fails is skipped, and a bracket needs two adjacent evaluated points
    f = lambda s: None if 1.0 < s < 2.0 else s - 1.5
    r = fmt.solve_nearest(f, [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0], 0.0)
    assert r["found"] is False or r["s"] is not None
    vals = [-1.0, None, 1.0]
    assert fmt._find_brackets(vals) == []
    assert fmt._find_brackets([-1.0, 1.0, 1.0, -1.0]) == [(0, 1), (2, 3)]
    assert fmt._find_brackets([-1.0, 0.0001, 0.0002, 1.0]) == [(1, 1)]
    # nothing is evaluated at all: no root and no side
    none = fmt.solve_nearest(lambda s: None, [0.0, 1.0, 2.0], 1.0)
    assert none["found"] is False and none["side"] is None and none["roots_on_grid"] == 0
    # a bisection that stops by iteration count still returns the best evaluated point
    steep = fmt.solve_nearest(lambda s: 1e9 * (s - 0.123456789012345), [0.0, 1.0], 0.5)
    assert steep["found"] and abs(steep["s"] - 0.123456789012345) < 1e-9


# ---- A5: the rendering ----------------------------------------------------------------------------------------------------------------

def test_the_model_sees_one_line_per_input_with_the_own_value_in_brackets():
    b = _b(growth=[0.12, 0.10, 0.08, 0.07, 0.06], ronic=0.12, tg=0.03, wacc=0.09)
    pi = _pi(b, b["raw"] * 1.25)
    lines = fmt.price_implied_lines(pi)
    assert [l.split(":")[0] for l in lines] == list(fmt.PI_INPUTS)
    by = {l.split(":")[0]: l for l in lines}
    assert by["coe"].endswith("[9.00%]") and by["coe"].startswith("coe: ") and "%" in by["coe"].split("[")[0]
    assert by["growth_years_3_5"].endswith("a year [+7.0% a year]") or " a year [" in by["growth_years_3_5"]
    assert by["terminal_ronic"].endswith("[12.0%]")
    nr = fmt.price_implied_lines(_pi(b, b["raw"] * 25.0))
    unreachable = [l for l in nr if "not reachable" in l]
    assert unreachable and all("(bound " in l and " to " in l and l.endswith("]") for l in unreachable)
    assert fmt.price_implied_lines({"error": "identity"}) == ["price_implied: not computed (identity)"]
    fin = fmt.price_implied_lines(_pi(_b(finite=12), 5.0))
    assert "terminal_ronic: not applicable (finite life)" in "\n".join(f.replace("not available, ", "") for f in fin)


# ---- Part J: the own-structure reverse DCF on the same routine -----------------------------------------------------------------------

def _rev(price, **kw):
    args = dict(current_price=price, shares_diluted=1.0, base_cf=1.0, wacc=0.09, terminal_g=0.03, fade_years=0, stage1_years=5, net_debt=0.0,
                valuation_frame="equity", terminal_ronic=INF)
    args.update(kw)
    return fmt.reverse_dcf_expectations_gap(**args)


def _own_value(g, **kw):
    args = dict(base_cf=1.0, explicit_growth=[g] * 5, wacc=0.09, terminal_g=0.03, shares_diluted=1.0, fade_years=0,
                sbc_treatment="deducted_in_cf", terminal_ronic=INF)
    args.update(kw)
    return fmt.unbundled_dcf(**args)["per_share_iv_raw"]


@pytest.mark.parametrize("g_star", [-0.30, -0.05, 0.0, 0.05, 0.12, 0.40, 1.5, 3.5])
def test_the_own_structure_solve_returns_the_growth_whose_value_is_the_price(g_star):
    price = _own_value(g_star)
    r = _rev(price)["own_structure"]
    assert r["reachable"] is True and r["side"] is None and r["roots_on_grid"] == 1 and r["stamps"] == []
    assert r["solved_growth_pct"] == pytest.approx(g_star * 100.0, abs=0.0051)            # the two-decimal rounding of the report
    assert r["implied_stage1_growth_pct"] == r["solved_growth_pct"]
    assert _rev(price)["implied_growth_next_5y_pct"] == r["solved_growth_pct"]


def test_a_low_priced_name_is_solved_on_the_unrounded_value():
    """The revision-18 solver read cents: on a name priced near $1.35 whose value moves $0.02 a point it missed by 0.13 pp."""
    kw = dict(base_cf=0.0036, shares_diluted=0.5, wacc=0.09, terminal_g=0.03, fade_years=5)
    g_star = 0.05
    price = fmt.unbundled_dcf(explicit_growth=[g_star] * 5, sbc_treatment="deducted_in_cf", terminal_ronic=0.12, **kw)["per_share_iv_raw"]
    assert price < 2.0
    res = fmt.reverse_dcf_expectations_gap(current_price=price, shares_diluted=0.5, base_cf=0.0036, wacc=0.09, terminal_g=0.03, fade_years=5,
                                           stage1_years=5, terminal_ronic=0.12)["own_structure"]
    assert res["solved_growth_pct"] == pytest.approx(5.0, abs=0.0051)


def test_the_own_structure_is_not_reachable_when_the_price_is_outside_its_values_and_says_which_side():
    above = _rev(_own_value(0.0) * 1e6)            # the price above every value the search reaches
    assert above["own_structure"]["reachable"] is False and above["own_structure"]["side"] == "above"
    assert above["implied_growth_next_5y_pct"] is None and above["own_structure"]["solved_growth_pct"] is None
    below = _rev(1e-6)
    assert below["own_structure"]["reachable"] is False and below["own_structure"]["side"] == "below"
    assert "expectations_gap_pts" not in _rev(_own_value(0.0) * 1e6, demonstrated_cagr_5y=5.0)
    # the upward expansion is kept: a growth of 700% is found
    assert _rev(_own_value(7.0))["own_structure"]["solved_growth_pct"] == pytest.approx(700.0, abs=0.0051)


def test_the_search_never_expands_below_minus_99_percent(monkeypatch):
    seen = []
    real = fmt.unbundled_dcf

    def spy(**kw):
        seen.append(kw["explicit_growth"][0])
        return real(**kw)
    monkeypatch.setattr(fmt, "unbundled_dcf", spy)
    _rev(0.0001)
    assert seen and min(seen) >= -0.99 - 1e-12


def test_a_non_monotone_own_structure_reports_its_roots_and_chooses_the_root_nearest_x0(monkeypatch):
    # a value that is not monotone in the constant growth: it crosses the price at three growths
    shape = lambda g: 100.0 + 60.0 * math.sin(3.0 * g)
    monkeypatch.setattr(fmt, "unbundled_dcf", lambda **kw: {"per_share_iv_raw": shape(kw["explicit_growth"][0]), "per_share_iv": 0.0})
    price = 100.0
    # sin(3g) = 0 at g = 0, pi/3 and 2 pi/3 on the grid [-0.99, 3] (the search grows hi from 2 to 3: the value at 2 is below the price)
    first = fmt.reverse_dcf_expectations_gap(current_price=price, shares_diluted=1.0, base_cf=1.0, wacc=0.09, terminal_g=0.03, x0=None)
    own = first["own_structure"]
    assert own["roots_on_grid"] == 3 and "multiple_roots" in own["stamps"]
    assert own["roots_pct"] == pytest.approx([0.0, 104.72, 209.44], abs=0.01)
    # x0 = 0 (none): the nearest root to 0 is 0 itself; x0 near the next root picks that one
    assert own["solved_growth_pct"] == pytest.approx(0.0, abs=0.01)
    near = fmt.reverse_dcf_expectations_gap(current_price=price, shares_diluted=1.0, base_cf=1.0, wacc=0.09, terminal_g=0.03, x0=math.pi / 3.0 + 0.05)
    assert near["own_structure"]["solved_growth_pct"] == pytest.approx(math.pi / 3.0 * 100.0, abs=0.01)
    assert near["own_structure"]["roots_pct"] == own["roots_pct"]
    far = fmt.reverse_dcf_expectations_gap(current_price=price, shares_diluted=1.0, base_cf=1.0, wacc=0.09, terminal_g=0.03, x0=2.0)
    assert far["own_structure"]["solved_growth_pct"] == pytest.approx(2.0 * math.pi / 3.0 * 100.0, abs=0.01)


def test_an_evaluation_error_is_never_a_silent_midpoint(monkeypatch):
    monkeypatch.setattr(fmt, "unbundled_dcf", lambda **kw: {"error": "boom", "validation_error": True})
    r = fmt.reverse_dcf_expectations_gap(current_price=50.0, shares_diluted=1.0, base_cf=1.0, wacc=0.09, terminal_g=0.03)
    own = r["own_structure"]
    assert own["reachable"] is False and own["solved_growth_pct"] is None and own["side"] is None and r["implied_growth_next_5y_pct"] is None
    # and the report prints it rather than formatting None
    md = fmt.format_model_results_markdown({"price": 50.0, "reverse_dcf": r})
    assert "**not reachable**" in md


def test_the_desk_passes_the_bases_year_1_growth_as_x0(monkeypatch):
    ref = _w9_reference()
    seen = {}
    real = fmt.reverse_dcf_expectations_gap

    def spy(**kw):
        seen.update(kw)
        return real(**kw)
    monkeypatch.setattr(fmt, "reverse_dcf_expectations_gap", spy)
    out = fmt.execute_financial_model(_desk_call(ref), _desk_ctx(ref, price=ref["value"] * 1.1, coe_anchor=0.09, terminal_g_anchor=0.0375))
    assert "error" not in out
    assert seen["x0"] == pytest.approx(ref["path"][0]) and "reachable" in out["reverse_dcf"]["own_structure"]


def test_the_desk_result_tells_the_model_when_the_own_growth_is_not_unique(monkeypatch):
    shape = lambda g: 100.0 + 60.0 * math.sin(3.0 * g)
    monkeypatch.setattr(fmt, "unbundled_dcf", lambda **kw: {"per_share_iv_raw": shape(kw["explicit_growth"][0]), "per_share_iv": 0.0})
    r = fmt.reverse_dcf_expectations_gap(current_price=100.0, shares_diluted=1.0, base_cf=1.0, wacc=0.09, terminal_g=0.03)
    md = fmt.format_model_results_markdown({"price": 100.0, "reverse_dcf": r})
    assert "Not unique: your structure's value equals today's price at" in md and "constant growths" in md


def _hand_block():
    bd = lambda lo, hi: {"low": lo, "high": hi, "value_low": None, "value_high": None}
    return {"coe": {"value": 0.098, "reachable": True, "own": 0.0735, "bound": bd(0.0501, 0.25)},
            "growth_years_3_5": {"value": -0.137, "reachable": True, "own": 0.03, "bound": bd(-0.99, 9.9)},
            "fade_years": {"value": None, "reachable": False, "own": 5, "bound": bd(0, 60)},
            "terminal_g": {"value": None, "reachable": False, "own": 0.0234, "bound": bd(0.0, 0.0446)},
            "terminal_ronic": {"value": 0.33, "reachable": True, "own": 0.12, "bound": bd(0.0735, "unlimited")},
            "year2_level": {"value": None, "reachable": False, "own": 0.332416, "bound": bd(None, None),
                            "not_available": "the pack prints no bull2 and bear2 range"}}


PINNED_LINES = [
    "coe: 9.80% [7.35%]",
    "growth_years_3_5: -13.7% a year [+3.0% a year]",
    "fade_years: not reachable (bound 0 years to 60 years) [5 years]",
    "terminal_g: not reachable (bound 0.00% to 4.46%) [2.34%]",
    "terminal_ronic: 33.0% [12.0%]",
    "year2_level: not available, the pack prints no bull2 and bear2 range [$0.332B]",
]


def test_the_rendering_of_the_price_implied_lines_is_pinned():
    assert fmt.price_implied_lines(_hand_block()) == PINNED_LINES
    unlimited = _hand_block()
    unlimited["terminal_ronic"] = {"value": "unlimited", "reachable": True, "own": "unlimited", "bound": {"low": 0.09, "high": "unlimited"}}
    assert fmt.price_implied_lines(unlimited)[4] == "terminal_ronic: unlimited [unlimited]"
    fade = _hand_block()
    fade["fade_years"] = {"value": 38.99475, "reachable": True, "own": 4, "bound": {"low": 0, "high": 60}}
    assert fmt.price_implied_lines(fade)[2] == "fade_years: 39.0 years [4 years]"
    finite = _hand_block()
    finite["terminal_ronic"] = {"value": None, "reachable": False, "own": None, "bound": {"low": None, "high": None},
                                "not_available": "not applicable (finite life)"}
    assert fmt.price_implied_lines(finite)[4] == "terminal_ronic: not available, not applicable (finite life)"


def test_the_compact_note_and_the_summary_carry_one_line_per_input():
    import analyst_tools as at
    result = {"price": 36.0, "scenario_dcfs": [{"name": "Base", "dcf": {"per_share_iv": 53.77}}], "price_implied": _hand_block()}
    note = at.compact_tool_note("run_financial_model", {}, result, 7)
    head, *lines = note.split("\n")
    assert head.startswith("[call 7] model: {") and lines == ["price_implied " + l for l in PINNED_LINES]
    assert at._desk_summary({}, result)["price_implied"] == PINNED_LINES
    # a call that carries none has no extra line; a refusal never does
    assert "\n" not in at.compact_tool_note("run_financial_model", {}, {"price": 36.0, "scenario_dcfs": []}, 8)
    assert at.compact_tool_note("run_financial_model", {}, {"error": "refused"}, 9) == '[call 9] model: {"error":"refused"}'
    # the full tool message leads with the summary, so a cut of the details never reaches the lines
    content, cut = at.tool_message("run_financial_model", {}, dict(result, markdown_report="x" * 20000), limit=5000)
    assert cut is not None and all(l in content for l in PINNED_LINES)


def test_the_compact_note_tells_the_model_when_the_own_growth_is_not_unique_or_not_reachable():
    import analyst_tools as at
    unique = {"own_structure": {"reachable": True, "roots_on_grid": 1, "roots_pct": [5.0]}, "implied_stage1_growth_pct": 5.0}
    many = {"own_structure": {"reachable": True, "roots_on_grid": 3, "roots_pct": [-12.0, 40.5, 133.0]}, "implied_stage1_growth_pct": 40.5}
    none = {"own_structure": {"reachable": False, "side": "above", "roots_on_grid": 0, "roots_pct": []}}
    note = lambda rd: at.compact_tool_note("run_financial_model", {}, {"price": 1.0, "reverse_dcf": rd}, 1)
    assert note(unique) == '[call 1] model: {"mode":"dcf","reverse_dcf":{"implied_stage1_growth_pct":5.0}}'
    assert '"own_growth_not_unique":true,"own_growth_roots_pct":[-12.0,40.5,133.0]' in note(many)
    assert '"implied_stage1_growth_pct":40.5' in note(many)
    assert '"own_structure":"not reachable"' in note(none) and "implied_stage1_growth_pct" not in note(none)
    assert at._desk_summary({}, {"reverse_dcf": many})["reverse_dcf"]["own_growth_roots_pct"] == [-12.0, 40.5, 133.0]


# ---- B-1 (the reviewer's evidence, SP/review_r19): a jump of the value is not a root --------------------------------------------------------------

def _ronic_ends(b):
    """(V at unlimited, V at the largest finite return the search reaches). Revision 24 step 2a (D4): the frozen arithmetic of revision 19 treated an
    unlimited return differently from a very large finite one, so the value jumped at +inf (the B-1 evidence); ronic_at now moves the charge
    1 / RONIC linearly, so an unlimited return is the limit of a large finite one and the two ends agree."""
    v_inf = _value(b, ronic=INF)
    v_big = _value(b, ronic=b["wacc"] * 1e9)
    assert abs(v_inf - v_big) < 1e-6
    return v_inf, v_big


@pytest.mark.parametrize("own_ronic", [INF, 0.12])
def test_a_price_near_the_unlimited_return_is_solved_at_its_root_with_no_jump(own_ronic):
    """Was `test_a_price_inside_the_unlimited_return_jump_is_solved_at_the_real_root_not_at_the_jump` (revision 24 step 2a, D4: there is no jump at
    unlimited any more). Own value unlimited and own value finite: a price just below the unlimited end is reached at a finite return, with one
    root and no discontinuity; a price just above it is not reachable, on the side above, with no discontinuity either."""
    b = _b(growth=[0.12, 0.10, 0.08, 0.07, 0.06], tg=0.03, ronic=own_ronic, wacc=0.09)
    v_inf, _ = _ronic_ends(b)
    blk = _pi(b, v_inf - 0.05)["terminal_ronic"]
    assert blk["reachable"] is True and blk["value"] != "unlimited" and blk["value"] < 100.0
    assert abs(_substitute(b, "terminal_ronic", blk) - (v_inf - 0.05)) <= 0.01
    assert blk["roots_on_grid"] == 1 and blk["discontinuities"] == 0 and blk["stamps"] == []
    above = _pi(b, v_inf + 0.01)["terminal_ronic"]
    assert above["reachable"] is False and above["side"] == "above" and above["discontinuities"] == 0 and above["stamps"] == []


def test_the_discontinuity_is_counted_apart_from_the_roots_and_the_roots_are_not_miscounted():
    """A price the unlimited end does not touch: one root, no jump. Revision 24 step 2a (D4): the self-made jump at +inf is gone, so no price
    across the whole range of terminal_ronic meets a discontinuity (the counting itself is tested on step functions below)."""
    b = _b(growth=[0.12, 0.10, 0.08, 0.07, 0.06], tg=0.03, ronic=0.12, wacc=0.09)
    plain = _pi(b, 20.0)["terminal_ronic"]
    assert plain["reachable"] and plain["roots_on_grid"] == 1 and plain["discontinuities"] == 0 and plain["stamps"] == []
    v_inf, _ = _ronic_ends(b)
    lo = _pi(b, 15.0)["terminal_ronic"]["bound"]["value_low"]
    for k in range(1, 10):
        blk = _pi(b, lo + (v_inf - lo) * k / 10.0)["terminal_ronic"]
        assert blk["reachable"] and blk["roots_on_grid"] == 1 and blk["discontinuities"] == 0


def test_solve_nearest_returns_not_reachable_when_every_bracket_is_a_jump():
    step = lambda s: -1.0 if s < 0.5 else 1.0                              # the value jumps over the price at 0.5 and nowhere crosses it
    res = fmt.solve_nearest(step, [k / 10.0 for k in range(11)], 0.2)
    assert res["found"] is False and res["s"] is None and res["roots_on_grid"] == 0 and res["discontinuities"] == 1 and res["side"] is None
    assert res["error"] is None and res["roots"] == []


def test_solve_nearest_takes_the_nearest_bracket_that_holds_a_root_and_counts_both_kinds():
    # f: a jump at 0.25 (-1 to +1), a real crossing at 0.575, a jump at 0.9 (-1 to +1)
    def f(s):
        if s < 0.25:
            return -1.0
        return 1.0 - (s - 0.25) * 2.0 / 0.65 if s <= 0.9 else 1.0
    grid = [k / 20.0 for k in range(21)]
    res = fmt.solve_nearest(f, grid, 0.25)                                  # own value on the first jump
    assert res["found"] and res["s"] == pytest.approx(0.575, abs=1e-6) and abs(res["f"]) <= fmt.SOLVER_RESIDUAL
    assert res["roots_on_grid"] == 1 and res["discontinuities"] == 2 and res["roots"] == pytest.approx([0.575], abs=1e-6)
    near_jump = fmt.solve_nearest(f, grid, 0.95)                            # own value beside the upper jump: the root is still the answer
    assert near_jump["found"] and near_jump["s"] == pytest.approx(0.575, abs=1e-6)


def test_a_residual_at_the_limit_is_a_root_and_one_just_above_is_a_jump():
    below = fmt.solve_nearest(lambda s: -0.0099 if s < 0.5 else 0.0099, [k / 10.0 for k in range(11)], 0.5)
    above = fmt.solve_nearest(lambda s: -0.0101 if s < 0.5 else 0.0101, [k / 10.0 for k in range(11)], 0.5)
    assert below["found"] and below["discontinuities"] == 0 and abs(below["f"]) <= 0.0099
    assert above["found"] is False and above["discontinuities"] == 1


def test_a_finite_life_staircase_residual_above_a_cent_is_no_root_and_below_a_cent_is():
    """The finite-life value rounds each year's PV to 0.0001 $B: a staircase whose steps are $1 on a 100,000-share name and $0.0001 on a 1B-share name."""
    for shares, step, reachable in ((1e-4, 1.0, False), (1.0, 1e-4, True)):
        b = _b(finite=10, shares=shares, ronic=None, growth=[0.1, 0.08, 0.06, 0.05, 0.04], wacc=0.1)
        levels = sorted({_value(b, wacc=0.1 + 1e-8 * k) for k in range(2000)}, reverse=True)
        assert levels[0] - levels[1] == pytest.approx(step, rel=1e-3)
        price = (levels[1] + levels[2]) / 2.0                              # half a step from both neighbouring levels
        blk = _pi(b, price)["coe"]
        assert blk["reachable"] is reachable
        if reachable:
            assert abs(blk["base_at_value"] - price) <= 0.01 and blk["discontinuities"] == 0
        else:
            assert blk["value"] is None and blk["discontinuities"] >= 1 and "discontinuity" in blk["stamps"] and blk["side"] is None
        exact = _pi(b, levels[2])["coe"]                                   # a price AT a level is reached whatever the step
        assert exact["reachable"] and abs(exact["base_at_value"] - levels[2]) <= 0.01


def test_the_own_structure_reverse_dcf_skips_a_jump_and_says_so_when_only_a_jump_is_left(monkeypatch):
    step = lambda g: 80.0 if g < 0.5 else 120.0                              # a jump over the price at g = 0.5, no crossing anywhere else
    monkeypatch.setattr(fmt, "unbundled_dcf", lambda **kw: {"per_share_iv_raw": step(kw["explicit_growth"][0]), "per_share_iv": 0.0})
    r = fmt.reverse_dcf_expectations_gap(current_price=100.0, shares_diluted=1.0, base_cf=1.0, wacc=0.09, terminal_g=0.03)
    own = r["own_structure"]
    assert own["reachable"] is False and own["solved_growth_pct"] is None and own["discontinuities"] == 1 and own["roots_on_grid"] == 0
    assert own["side"] is None and own["stamps"] == ["discontinuity"] and r["implied_growth_next_5y_pct"] is None
    md = fmt.format_model_results_markdown({"price": 100.0, "reverse_dcf": r})
    assert "**not reachable**" in md and "jumps past today's price" in md and "outside every value" not in md
    # the same function with a real crossing beside the jump: the crossing is the answer
    shape = lambda g: step(g) if g < 1.0 else 100.0 + (g - 1.5) * 40.0
    monkeypatch.setattr(fmt, "unbundled_dcf", lambda **kw: {"per_share_iv_raw": shape(kw["explicit_growth"][0]), "per_share_iv": 0.0})
    r2 = fmt.reverse_dcf_expectations_gap(current_price=100.0, shares_diluted=1.0, base_cf=1.0, wacc=0.09, terminal_g=0.03, x0=0.5)
    assert r2["own_structure"]["reachable"] and r2["own_structure"]["solved_growth_pct"] == pytest.approx(150.0, abs=0.01)
    assert r2["own_structure"]["discontinuities"] >= 1 and "discontinuity" in r2["own_structure"]["stamps"]
