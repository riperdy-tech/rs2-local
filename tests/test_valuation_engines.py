"""Tests of the valuation package's arithmetic, by hand-computed cases on synthetic fixtures (no network, no real company).

The census cases at the bottom are REGRESSION SANITY only: they check that a structural defect of the old reference cannot occur in
the new chain (no zero long-run margin from a margin translation, no forced positive perpetual growth). No constant anywhere is tuned
to make a named stock come out right, and no test names a stock's value.
"""
import math
from datetime import date

import pytest

from valuation import common, engine_commodity as com, engine_financial as fin, engine_operating as op
from valuation.common import (CompanyPIT, Curve, DrawInvalid, Filed, InputError, PITViolation, QuantileDist, SicInfo, build_state,
                              cyclicality_score, draw_inputs, equity_bridge, greenwald_maintenance_capex, simulate)
from valuation.discount_rate import DiscountRate
from valuation.priors_interface import PlaceholderPriors, PriorSet

REL = 1e-9


def disc(w=0.10, coe=0.12, asof="2025-06-30"):
    return DiscountRate(asof=asof, rf=0.04, erp=0.05, beta_unlevered=1.0, de_ratio=0.0, de_basis="book", tax=0.25, beta_levered=1.0,
                        coe=coe, kd_pretax=None, wacc=w, placeholder=True)


def op_state(ronic=0.12, **kw):
    """`ronic`: the company's trailing 3-year ROIC AND its industry's median (Addendum H3), so that a return on new capital equal to it is the same in every year
    and in perpetuity (max(I, WACC) = I for I >= WACC = 0.10): the hand computations below then do not depend on the ROIC path."""
    st = {"ticker": "SYN", "asof": "2025-06-30", "base_period": "2024-12-31", "revenue": 1000.0, "op_margin": 0.10, "tax_rate": 0.25,
          "roic3": ronic, "industry_roic": {"value": ronic, "n": 50, "basis": "industry"},
          "maint_gap_ratio": 0.0, "nwc_ratio": 0.10, "debt": 0.0, "finance_lease_liability": 0.0, "operating_lease_liability": 0.0,
          "nci": 0.0, "cash": 0.0, "st_investments": 0.0, "lt_investments": 0.0, "read_as_none": [], "missing": []}
    st.update(kw)
    return st


def with_context(pit_or_state, roic=0.12, rote=0.10):
    """The engines' state with the date's industry medians attached (what gate1.value_company does)."""
    st = build_state(pit_or_state) if not isinstance(pit_or_state, dict) else pit_or_state
    st["industry_roic"] = {"value": roic, "n": 50, "basis": "industry"}
    st["industry_rote"] = {"value": rote, "n": 50, "basis": "industry"}
    return st


def curves(g, m, r):
    return {"growth_decay": Curve(g), "margin_retention": Curve(m), "ronic_fade": Curve(r)}


# ---- the operating chain, hand computed -----------------------------------------------------------------------------------------------

def test_operating_chain_two_years_by_hand():
    st = op_state(ronic=0.15, debt=200.0, cash=50.0, nci=10.0, finance_lease_liability=20.0, lt_investments=30.0, operating_lease_liability=77.0)
    p = {"g1": 0.10, "g_terminal": 0.02, "margin_target": 0.20, "ronic": 0.15}
    r = op.operating_chain(st, p, curves([1.0, 0.0], [0.0, 0.0], [1.0, 1.0]), disc(), roll_forward=False, detail=True)
    # year 1: rev 1100, EBIT 220, NOPAT 165, reinvestment 100 x 0.20 x 0.75 / 0.15 = 100, FCFF 65
    y1, y2 = r["years"]
    assert y1["revenue"] == pytest.approx(1100.0)
    assert y1["nopat"] == pytest.approx(165.0)
    assert y1["growth_reinvestment"] == pytest.approx(100.0)
    assert y1["fcff"] == pytest.approx(65.0)
    # year 2: growth falls to g_T (decay 0): rev 1122, NOPAT 168.3, reinvestment 22, FCFF 146.3
    assert y2["growth"] == pytest.approx(0.02)
    assert y2["fcff"] == pytest.approx(146.3)
    # terminal: rev 1144.44, NOPAT 171.666, reinvestment 22.44, FCFF 149.226, TV = 149.226 / 0.08
    assert r["terminal_value"] == pytest.approx(149.226 / 0.08)
    ev = 65 / 1.1 + 146.3 / 1.21 + (149.226 / 0.08) / 1.21
    assert r["ev"] == pytest.approx(ev, rel=REL)
    assert r["tv_share"] == pytest.approx(((149.226 / 0.08) / 1.21) / ev, rel=REL)
    # the bridge: debt, finance lease, minority out; cash and non-operating assets in; operating leases NOT subtracted (cost is in EBIT)
    assert r["equity"] == pytest.approx(ev - 200 - 20 - 10 + 50 + 30, rel=REL)


def test_equity_bridge_lease_policy_and_cash_counted_once():
    st = op_state(debt=100.0, cash=40.0, st_investments=10.0, operating_lease_liability=60.0, nci=5.0)
    a = equity_bridge(1000.0, st)
    assert a["equity_value"] == pytest.approx(1000 - 100 - 5 + 40 + 10)
    b = equity_bridge(1000.0, st, operating_leases_in_cash_flow=False)
    assert b["equity_value"] == pytest.approx(1000 - 100 - 5 + 40 + 10 - 60)
    assert a["items"]["cash"] == 40.0 and a["items"]["short_term_investments"] == 10.0   # each once


def test_roll_forward_uses_cost_of_equity_over_the_years_since_base_year_end():
    st = op_state()
    p = {"g1": 0.05, "g_terminal": 0.02, "margin_target": 0.10, "ronic": 0.12}
    c = curves([1.0, 0.5, 0.0], [0.0] * 3, [1.0] * 3)
    base = op.operating_chain(st, p, c, disc(asof="2025-06-30"), roll_forward=False)
    rolled = op.operating_chain(st, p, c, disc(asof="2025-06-30"), roll_forward=True)
    yrs = (date(2025, 6, 30) - date(2024, 12, 31)).days / 365.25
    assert rolled["roll_forward_years"] == pytest.approx(yrs)
    assert rolled["equity"] == pytest.approx(base["equity"] * 1.12 ** yrs, rel=REL)


def test_negative_terminal_growth_and_working_capital_release_by_hand():
    st = op_state(ronic=0.15, nwc_ratio=0.10)
    p = {"g1": -0.05, "g_terminal": 0.02, "margin_target": 0.20, "ronic": 0.15}
    r = op.operating_chain(st, p, curves([1.0], [0.0], [1.0]), disc(), roll_forward=False, detail=True)
    y1 = r["years"][0]
    assert y1["growth"] == pytest.approx(-0.05)                        # decay 1: year 1 is g1
    assert y1["revenue"] == pytest.approx(950.0)
    assert y1["growth_reinvestment"] == pytest.approx(-5.0)           # (950 - 1000) x 0.10: a release
    assert y1["fcff"] == pytest.approx(142.5 + 5.0)
    # Addendum H2: the path is at -5% in its last explicit year, so -5% continues as terminal growth (the date's +2% is not used)
    assert r["terminal_growth"]["value"] == pytest.approx(-0.05) and "negative" in r["terminal_growth"]["basis"]
    # terminal: rev 902.5, NOPAT 135.375, release (902.5 - 950) x 0.10 = -4.75, FCFF 140.125, TV = 140.125 / (0.10 + 0.05)
    assert r["terminal_value"] == pytest.approx(140.125 / 0.15)
    assert r["terminal_reinvestment_rate"] < 0
    ev = 147.5 / 1.1 + (140.125 / 0.15) / 1.1
    assert r["ev"] == pytest.approx(ev, rel=REL)
    assert r["equity"] == pytest.approx(ev, rel=REL)
    # no floor: a more negative last-year rate is a different, still valid, value
    p2 = dict(p, g1=-0.12)
    assert op.operating_chain(st, p2, curves([1.0], [0.0], [1.0]), disc(), roll_forward=False)["ev"] > 0


def test_terminal_growth_is_the_lower_of_the_risk_free_rate_and_the_anchor_one_value_per_date():
    assert common.terminal_growth_rate(0.02) == 0.02 and common.terminal_growth_rate(0.0375) == 0.0375
    assert common.terminal_growth_rate(0.05) == common.TERMINAL_G_ANCHOR == 0.0375
    assert common.terminal_growth_rate(-0.002) == -0.002                # no floor
    assert common.terminal_growth_after(0.01, 0.0375)[0] == 0.0375 and common.terminal_growth_after(-0.03, 0.0375)[0] == -0.03
    assert common.terminal_growth_after(0.0, 0.0375)[0] == 0.0375       # zero growth is not negative


def test_a_positive_decay_path_ends_at_the_dates_terminal_growth_and_the_inputs_value_is_the_date_one():
    st = op_state()
    p = {"g1": 0.10, "g_terminal": 0.02, "margin_target": 0.10, "ronic": 0.12}
    r = op.operating_chain(st, p, curves([1.0, 0.5, 0.0], [0.0] * 3, [1.0] * 3), disc(), roll_forward=False, detail=True)
    assert r["years"][-1]["growth"] == pytest.approx(0.02) and r["terminal_growth"]["value"] == pytest.approx(0.02)
    assert "min(risk-free" in r["terminal_growth"]["basis"]


def test_terminal_growth_at_or_above_the_discount_rate_is_an_invalid_draw_not_a_repair():
    st = op_state()
    p = {"g1": 0.05, "g_terminal": 0.10, "margin_target": 0.10, "ronic": 0.12}
    with pytest.raises(DrawInvalid):
        op.operating_chain(st, p, curves([1.0], [0.0], [1.0]), disc(w=0.10))


def test_horizon_is_at_most_25_years():
    Curve([0.5] * 25)
    with pytest.raises(InputError):
        Curve([0.5] * 26)


def test_greenwald_maintenance_capex_and_the_state_gap_ratio():
    assert greenwald_maintenance_capex(100.0, 500.0, 1000.0, 900.0) == pytest.approx(50.0)    # growing: part of capex is growth
    assert greenwald_maintenance_capex(100.0, 500.0, 1000.0, 1100.0) == pytest.approx(150.0)  # shrinking: more than capex
    assert greenwald_maintenance_capex(100.0, None, 1000.0, 900.0) is None
    pit = _pit_from_rows({
        "2022-12-31": dict(revenue=900.0, operating_income=90.0, capex=80.0, ppe_net=450.0, da=60.0),
        "2023-12-31": dict(revenue=1000.0, operating_income=100.0, capex=100.0, ppe_net=500.0, da=70.0),
    }, asof="2025-01-01")
    st = build_state(pit)
    # maintenance 2023 = 100 - 0.5 x 100 = 50; gap = (50 - 70) / 1000 = -0.02 (raw, kept); the engine floors it at 0 and reports both
    assert st["maint_gap_ratio"] == pytest.approx(-0.02)
    st2 = op_state(maint_gap_ratio=-0.02)
    p = {"g1": 0.05, "g_terminal": 0.02, "margin_target": 0.10, "ronic": 0.12}
    c = curves([1.0, 0.0], [0.0, 0.0], [1.0, 1.0])
    floored = op.operating_chain(st2, p, c, disc(), roll_forward=False)
    assert floored["maint_gap_ratio_used"] == 0.0 and floored["maint_gap_ratio_raw"] == pytest.approx(-0.02)
    free = op.operating_chain(st2, p, c, disc(), roll_forward=False, maint_gap_floor=None)
    assert free["ev"] > floored["ev"]


def test_positive_maintenance_gap_reduces_fcff_by_gap_times_revenue():
    st = op_state(maint_gap_ratio=0.03)
    p = {"g1": 0.0, "g_terminal": 0.0, "margin_target": 0.10, "ronic": 0.12}
    r = op.operating_chain(st, p, curves([1.0], [0.0], [1.0]), disc(), roll_forward=False, detail=True)
    y = r["years"][0]
    assert y["maintenance_gap"] == pytest.approx(0.03 * 1000.0)
    assert y["fcff"] == pytest.approx(1000 * 0.10 * 0.75 - 0.0 - 30.0)


def test_no_margin_translation_the_margin_path_is_the_input_path():
    st = op_state(op_margin=0.30)
    p = {"g1": 0.0, "g_terminal": 0.0, "margin_target": 0.10, "ronic": 0.12}
    r = op.operating_chain(st, p, curves([1.0] * 3, [0.5, 0.25, 0.0], [1.0] * 3), disc(), roll_forward=False, detail=True)
    assert [y["margin"] for y in r["years"]] == pytest.approx([0.20, 0.15, 0.10])


# ---- distributions and sampling -----------------------------------------------------------------------------------------------------

def test_quantile_dist_knots_interpolation_tails_and_validation():
    d = QuantileDist({0.10: 1.0, 0.25: 2.0, 0.50: 3.0, 0.75: 5.0, 0.90: 9.0})
    assert d.ppf(0.5) == 3.0 and d.ppf(0.10) == 1.0 and d.ppf(0.90) == 9.0
    assert d.ppf(0.375) == pytest.approx(2.5)
    assert d.ppf(0.01) < 1.0 and d.ppf(0.99) > 9.0       # normal tails beyond the outer knots
    with pytest.raises(InputError):
        QuantileDist({0.10: 3.0, 0.50: 2.0, 0.90: 4.0})
    with pytest.raises(InputError):
        QuantileDist({0.50: 1.0})
    assert QuantileDist.point(2.0).ppf(0.001) == 2.0


def test_draws_are_seeded_and_the_copula_carries_correlation():
    dists = {"a": QuantileDist({0.1: -1.0, 0.5: 0.0, 0.9: 1.0}), "b": QuantileDist({0.1: -1.0, 0.5: 0.0, 0.9: 1.0})}
    x = draw_inputs(dists, 20, 7)
    assert x == draw_inputs(dists, 20, 7) and x != draw_inputs(dists, 20, 8)
    big = draw_inputs(dists, 4000, 1, corr={("a", "b"): 0.9})
    ma = sum(d["a"] for d in big) / len(big)
    mb = sum(d["b"] for d in big) / len(big)
    cov = sum((d["a"] - ma) * (d["b"] - mb) for d in big)
    va = sum((d["a"] - ma) ** 2 for d in big)
    vb = sum((d["b"] - mb) ** 2 for d in big)
    assert cov / math.sqrt(va * vb) > 0.8
    ind = draw_inputs(dists, 4000, 1)
    ma = sum(d["a"] for d in ind) / len(ind)
    mb = sum(d["b"] for d in ind) / len(ind)
    assert abs(sum((d["a"] - ma) * (d["b"] - mb) for d in ind) / len(ind)) < 0.05
    with pytest.raises(InputError):
        draw_inputs(dists, 5, 1, corr={("a", "b"): 1.5})


def test_simulate_counts_invalid_draws_by_reason_and_reports_percentiles():
    def chain(d):
        if d["x"] > 0.5:
            raise DrawInvalid("too big")
        return {"equity": d["x"], "ev": d["x"], "tv_share": 0.5}
    out = simulate(chain, {"x": QuantileDist({0.1: 0.0, 0.5: 0.4, 0.9: 1.0})}, 400, 3)
    assert out["n_valid"] + out["n_invalid"] == 400 and out["invalid_reasons"]["too big"] == out["n_invalid"] > 0
    assert out["equity"]["p10"] <= out["equity"]["p50"] <= out["equity"]["p90"]


def test_model_disagreement_is_the_log_ratio():
    d, why = common.model_disagreement(200.0, 100.0)
    assert d == pytest.approx(math.log(2.0)) and why is None
    d, why = common.model_disagreement(-1.0, 100.0)
    assert d is None and why


# ---- the financial engine ----------------------------------------------------------------------------------------------------------

def fin_state(**kw):
    st = {"ticker": "SYN", "asof": "2025-06-30", "base_period": "2024-12-31", "tbv": 1000.0, "rote_latest": 0.15, "periods": ["2024-12-31"],
          "tax_rate": 0.2, "read_as_none": [], "missing": [], "industry_rote": {"value": 0.10, "n": 50, "basis": "industry"}}
    st.update(kw)
    return st


def test_financial_excess_return_by_hand():
    st = fin_state()
    p = {"g1": 0.03, "g_terminal": 0.03, "rote_target": 0.15}
    c = {"growth_decay": Curve([1.0, 1.0]), "rote_retention": Curve([1.0, 1.0]), "excess_fade": Curve([1.0, 0.5])}
    r = fin.financial_chain(st, p, c, disc(coe=0.10), roll_forward=False, detail=True)
    y1, y2 = r["years"]
    assert y1["excess_return"] == pytest.approx(50.0)
    assert y2["excess_return"] == pytest.approx(0.025 * 1030.0)         # the excess over the industry median (0.10) is still half open in year 2
    # Addendum H3: in perpetuity the return is the industry median floored at the cost of equity: here 0.10 = COE, so no excess return after year N
    assert r["terminal_rote"] == pytest.approx(0.10)
    expected = 1000 + 50 / 1.1 + 25.75 / 1.21
    assert r["equity"] == pytest.approx(expected, rel=REL)
    assert r["price_to_tbv_implied"] == pytest.approx(expected / 1000.0)


def test_financial_terminal_excess_is_the_industry_median_excess_times_the_measured_long_run_retention():
    """Addendum I4: RI_{N+1} = kappa x max(I - COE, 0) x TBV_N, kappa = the plateau (the last value) of the measured retention curve; the explicit years still fade to I."""
    p = {"g1": 0.03, "g_terminal": 0.03, "rote_target": 0.14}
    # the target return is the industry median 0.14 (above COE 0.10) and stays there in the explicit years whatever the retention: RI_t = 0.04 x TBV_{t-1}
    st = fin_state(industry_rote={"value": 0.14, "n": 50, "basis": "industry"})
    tbv = [1000.0, 1030.0, 1060.9]
    pv = sum(0.04 * tbv[i] / 1.1 ** (i + 1) for i in range(3))
    for kappa in (0.5, 1.0, 0.0):
        c = {"growth_decay": Curve([1.0] * 3), "rote_retention": Curve([0.0] * 3), "excess_fade": Curve([0.9, 0.7, kappa])}
        r = fin.financial_chain(st, p, c, disc(coe=0.10), roll_forward=False, detail=True)
        assert [y["rote_after_fade"] for y in r["years"]] == pytest.approx([0.14] * 3)
        assert r["terminal_excess_retention"] == kappa and r["terminal_rote"] == pytest.approx(0.10 + kappa * 0.04)
        tv = kappa * 0.04 * 1092.727 / 0.07
        assert r["equity"] == pytest.approx(1000 + pv + tv / 1.1 ** 3, rel=1e-6)
    # kappa = 1 is the full median excess for ever (the round-2 reading); kappa = 0 leaves no terminal excess
    assert fin.financial_chain(st, p, {"growth_decay": Curve([1.0] * 3), "rote_retention": Curve([0.0] * 3), "excess_fade": Curve([0.9, 0.7, 0.0])}, disc(coe=0.10),
                               roll_forward=False)["pv_terminal_excess"] == 0.0
    # an industry median BELOW the cost of equity: the explicit years keep it, the perpetuity has no excess (floored at 0, never a negative excess for ever)
    c = {"growth_decay": Curve([1.0] * 3), "rote_retention": Curve([0.0] * 3), "excess_fade": Curve([0.0] * 3)}
    low = fin.financial_chain(fin_state(industry_rote={"value": 0.06, "n": 50, "basis": "industry"}), dict(p, rote_target=0.06), c, disc(coe=0.10), roll_forward=False, detail=True)
    assert [y["rote_after_fade"] for y in low["years"]] == pytest.approx([0.06] * 3) and low["terminal_rote"] == pytest.approx(0.10)
    assert low["pv_terminal_excess"] == 0.0


def test_the_priors_name_the_plateau_of_the_financial_excess_retention_at_its_longest_k_with_50_observations():
    from valuation.priors import PopulationPriors
    ks = [{"k": k, "n": n, "median": m} for k, n, m in ((1, 900, 0.80), (2, 700, 0.64), (3, 400, 0.52), (4, 120, 0.45), (5, 49, 0.99), (6, 30, 0.10), (7, 0, None))]
    from valuation.priors import _curve_from_rows
    cv = _curve_from_rows(ks, "median", "n", "excess_fade", "t", [])
    assert cv.values[-1] == pytest.approx(0.45) and cv.values[3] == pytest.approx(0.45)      # k = 4 is the longest with n >= 50: held beyond
    # a table that stops after k = 2 (n < 50 from k = 3) plateaus at k = 2
    assert _curve_from_rows(ks[:2] + [dict(ks[2], n=10)], "median", "n", "excess_fade", "t", []).values[-1] == pytest.approx(0.64)


def test_financial_full_fade_to_cost_of_equity_leaves_tangible_book():
    st = fin_state()
    p = {"g1": 0.03, "g_terminal": 0.03, "rote_target": 0.20}
    c = {"growth_decay": Curve([1.0] * 3), "rote_retention": Curve([0.0] * 3), "excess_fade": Curve([0.0] * 3)}
    r = fin.financial_chain(st, p, c, disc(coe=0.10), roll_forward=False)
    assert r["equity"] == pytest.approx(1000.0)


def test_financial_value_below_tbv_when_return_is_below_cost_of_equity():
    st = fin_state(rote_latest=0.05)
    p = {"g1": 0.02, "g_terminal": 0.02, "rote_target": 0.05}
    c = {"growth_decay": Curve([1.0] * 3), "rote_retention": Curve([1.0] * 3), "excess_fade": Curve([1.0] * 3)}
    assert fin.financial_chain(st, p, c, disc(coe=0.10), roll_forward=False)["equity"] < 1000.0


def test_financial_refuses_without_a_positive_tangible_book():
    assert fin.state_gaps(fin_state(tbv=-5.0))
    assert fin.state_gaps(fin_state(tbv=None))
    assert any("industry median return on tangible equity" in g for g in fin.state_gaps(fin_state(industry_rote=None)))
    assert not fin.state_gaps(fin_state())


def test_insurer_decomposition_keeps_the_catastrophe_year():
    pit = _pit_from_rows({f"20{y}-12-31": dict(revenue=1.0) for y in (21, 22, 23, 24)}, asof="2025-06-30")
    prem, clm, nii, dac = [100, 110, 120, 130], [60, 70, 120, 80], [10, 10, 12, 12], [20, 20, 22, 22]
    for name, vals in (("PremiumsEarnedNet", prem), ("PolicyholderBenefitsAndClaimsIncurredNet", clm), ("NetInvestmentIncome", nii),
                       ("DeferredPolicyAcquisitionCostAmortizationExpense", dac)):
        pit.concepts[name] = {f"20{y}-12-31": Filed(float(v), f"20{y}-12-31", f"20{y + 1}-02-20", "A", "10-K", name)
                              for y, v in zip((21, 22, 23, 24), vals)}
    d = fin.insurer_decomposition(pit, 0.2, 100.0)
    uw = [100 - 60 - 20, 110 - 70 - 20, 120 - 120 - 22, 130 - 80 - 22]        # 20, 20, -22, 28
    assert [r["underwriting_result_partial"] for r in d["years"]] == uw
    assert d["median_underwriting_result_partial"] == pytest.approx(20.0)      # the -22 catastrophe year is in the median
    assert d["median_net_investment_income"] == pytest.approx(11.0)
    assert d["implied_rote_from_medians_partial"] == pytest.approx((20 + 11) * 0.8 / 100.0)
    assert any("partial" in s for s in d["stamps"])


# ---- the commodity engine ----------------------------------------------------------------------------------------------------------

def test_cyclicality_score_by_hand_and_bounds():
    ms = {f"20{y:02d}-12-31": m for y, m in zip(range(10, 16), [0.10, 0.20, 0.10, 0.20, 0.10, 0.20])}
    rv = {k: 100.0 for k in ms}
    res, why = cyclicality_score(ms, rv)
    c = res["components"]
    assert c["margin_volatility"] == pytest.approx(0.05 / (0.05 + 0.15))
    assert c["reversal_frequency"] == pytest.approx(1.0)
    assert c["autocorrelation"] == pytest.approx((1 + 0.8) / 2)                # rho = -0.8 by hand
    assert c["revenue_cyclicality"] == 0.0
    assert res["score"] == pytest.approx((0.25 + 1.0 + 0.9 + 0.0) / 4)
    # a flat margin and smooth growth is not cyclical at all
    flat, _ = cyclicality_score({k: 0.15 for k in ms}, {k: 100.0 * 1.1 ** i for i, k in enumerate(ms)})
    assert flat["score"] == pytest.approx(0.0, abs=1e-9)
    assert cyclicality_score({k: 0.1 for k in list(ms)[:4]}, {k: 1.0 for k in list(ms)[:4]}) == (None, "fewer than 6 annual years held (margins 4, revenues 4)")


def test_commodity_normalization_starts_in_year_one_and_peak_hold_is_flagged():
    st = op_state(op_margin=0.30)
    # the margin level five years on (Addendum H1) at its median: through-cycle 0.10 + r_5 x (0.30 - 0.10) with the curve's value at year 5 (held) r_5 = 0.1
    p = {"g1": 0.0, "g_terminal": 0.0, "margin_target": 0.10 + 0.1 * 0.20, "ronic": 0.12}
    nc = Curve([0.6, 0.3, 0.1])
    r = op.operating_chain(st, p, {"growth_decay": Curve([1.0] * 3), "margin_retention": nc, "ronic_fade": Curve([1.0] * 3)}, disc(),
                           roll_forward=False, detail=True)
    assert r["years"][0]["margin"] == pytest.approx(0.10 + 0.20 * 0.6)         # year 1 is already normalized, not the 30% peak: on the curve
    assert r["years"][1]["margin"] == pytest.approx(0.10 + 0.20 * 0.3) and r["years"][2]["margin"] == pytest.approx(0.10 + 0.20 * 0.1)
    assert r["years"][0]["margin"] < 0.30


def _commodity_pit(asc932=None, sic="1311"):
    rows = {}
    for i, y in enumerate(range(2014, 2025)):
        m = 0.10 + (0.15 if y % 3 == 0 else 0.0) - (0.05 if y % 4 == 0 else 0.0)
        rev = 1000.0 + (200.0 if y % 3 == 0 else 0.0)
        rows[f"{y}-12-31"] = dict(revenue=rev, operating_income=m * rev, capex=90.0, ppe_net=800.0, da=80.0, cash=50.0, debt_lt_noncurrent=100.0,
                                  equity=900.0, equity_incl_nci=900.0, goodwill=0.0, intangibles_ex_goodwill=0.0, current_assets=300.0,
                                  current_liabilities=200.0, pretax_income=m * rev, tax_provision=0.2 * m * rev, net_income=0.8 * m * rev,
                                  total_assets=1500.0)
    pit = _pit_from_rows(rows, asof="2025-06-30", sic=sic)
    if asc932 is not None:
        n = "StandardizedMeasureOfDiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReserves"
        pit.concepts[n] = {"2024-12-31": Filed(asc932, "2024-12-31", "2025-02-20", "ACC", "10-K", n)}
    return pit


def test_commodity_secondary_asc932_when_tagged_else_stamped_tangible_book_proxy():
    pri = PlaceholderPriors(True)
    d = disc(asof="2025-06-30")
    with_sm = com.run(_commodity_pit(asc932=1500.0), pri, d, n_draws=200, state=with_context(_commodity_pit(asc932=1500.0)))
    assert with_sm["status"] == "ok" and with_sm["secondary"]["kind"] == "asc932_standardized_measure"
    assert with_sm["secondary"]["proxy"] is False
    st = build_state(_commodity_pit(asc932=1500.0))
    yrs = (date(2025, 6, 30) - date(2024, 12, 31)).days / 365.25
    assert with_sm["secondary"]["equity"] == pytest.approx((1500.0 - 100.0 + 50.0) * 1.12 ** yrs)
    no_sm = com.run(_commodity_pit(), pri, d, n_draws=200, state=with_context(_commodity_pit()))
    assert no_sm["secondary"]["kind"] == "tangible_book_proxy" and no_sm["secondary"]["proxy"] is True
    assert any("PROXY" in s for s in no_sm["secondary"]["stamps"])
    assert no_sm["secondary"]["equity"] == pytest.approx(st["tbv"] * 1.12 ** yrs)
    md = no_sm["model_disagreement"]
    assert md == pytest.approx(math.log(no_sm["distribution"]["equity"]["p50"] / no_sm["secondary"]["equity"]))
    assert no_sm["placeholder"] is True            # the flag travels with every placeholder-based result


def test_commodity_refuses_when_it_cannot_be_scored():
    pit = _pit_from_rows({f"{y}-12-31": dict(revenue=100.0, operating_income=10.0, capex=5.0, ppe_net=50.0, da=4.0, cash=5.0, current_assets=30.0,
                                             current_liabilities=20.0) for y in (2022, 2023, 2024)}, asof="2025-06-30", sic="1311")
    r = com.run(pit, PlaceholderPriors(True), disc(), n_draws=50)
    assert r["status"] == "refused" and any("cyclicality" in x for x in r["reasons"])


# ---- run() end to end on a synthetic operating company ----------------------------------------------------------------------------------

def _operating_pit(asof="2025-06-30"):
    rows = {}
    for y in range(2015, 2025):
        rev = 1000.0 * 1.06 ** (y - 2015)
        rows[f"{y}-12-31"] = dict(revenue=rev, operating_income=0.15 * rev, capex=0.05 * rev, ppe_net=0.3 * rev, da=0.04 * rev, cash=100.0,
                                  debt_lt_noncurrent=200.0, equity=1500.0, equity_incl_nci=1500.0, goodwill=100.0, intangibles_ex_goodwill=50.0,
                                  current_assets=0.4 * rev, current_liabilities=0.2 * rev, pretax_income=0.14 * rev, tax_provision=0.03 * rev,
                                  net_income=0.11 * rev, total_assets=2500.0, interest_expense=10.0)
    return _pit_from_rows(rows, asof=asof, sic="7372")


def test_operating_run_returns_a_distribution_with_secondary_and_disagreement():
    pit = _operating_pit()
    r = op.run(pit, PlaceholderPriors(True), disc(), n_draws=300, seed=5, state=with_context(pit))
    assert r["status"] == "ok" and r["family"] == "operating"
    d = r["distribution"]
    assert d["n_valid"] > 0 and d["equity"]["p10"] <= d["equity"]["p50"] <= d["equity"]["p90"]
    assert 0.0 < d["tv_share"]["p50"] < 1.5
    assert d["secondary_equity"] is not None and r["model_disagreement"] is not None
    assert "inputs drawn independently" in " ".join(r["notes"])
    assert r["placeholder"] is True and r["discount"]["placeholder"] is True
    assert r["base_period"] == "2024-12-31"
    again = op.run(pit, PlaceholderPriors(True), disc(), n_draws=300, seed=5, state=with_context(pit))
    assert again["distribution"]["equity"] == d["equity"]            # deterministic for a seed
    assert "years" in r["at_median_inputs"]


def test_operating_run_refuses_naming_the_gap():
    pit = _pit_from_rows({"2024-12-31": dict(revenue=100.0)}, asof="2025-06-30")
    r = op.run(pit, PlaceholderPriors(True), disc(), n_draws=20)
    assert r["status"] == "refused" and any("not available" in x for x in r["reasons"])


def test_placeholder_priors_need_the_explicit_flag():
    with pytest.raises(InputError):
        PlaceholderPriors(False)


# ---- regression sanity: census defect classes cannot occur in the new chain --------------------------------------------------------------

def test_sanity_no_zero_long_run_margin_from_an_operating_vs_earnings_gap():
    # LITE/LIND-like: a small operating margin with a large gap to earnings margin. The old additive translation drove the long-run margin to 0.
    # The new chain forecasts the operating margin directly: every year's margin stays at the input path and positive.
    st = op_state(op_margin=0.028)
    p = {"g1": 0.40, "g_terminal": 0.02, "margin_target": 0.028, "ronic": 0.12}
    r = op.operating_chain(st, p, curves([1.0, 0.8, 0.6, 0.4, 0.2, 0.0], [1.0] * 6, [1.0] * 6), disc(), roll_forward=False, detail=True)
    assert all(y["margin"] > 0 for y in r["years"])
    assert r["fcff_terminal_year"] > 0 and r["terminal_value"] > 0


def test_sanity_a_shrinking_company_is_not_given_positive_perpetual_growth():
    st = op_state(op_margin=0.05)
    shrink = {"g1": -0.04, "g_terminal": 0.0236, "margin_target": 0.05, "ronic": 0.10}
    st = op_state(ronic=0.10, op_margin=0.05)
    c = curves([1.0] * 5, [1.0] * 5, [1.0] * 5)
    a = op.operating_chain(st, shrink, c, disc(), roll_forward=False, detail=True)
    assert a["years"][-1]["growth"] == pytest.approx(-0.04)           # decay 1 holds g1 to the last explicit year
    assert a["terminal_growth"]["value"] == pytest.approx(-0.04)      # the negative rate continues; the date's positive value is NOT applied
    # whatever the date's value is, a path that ends negative gives the same terminal value
    b = op.operating_chain(st, dict(shrink, g_terminal=0.0), c, disc(), roll_forward=False)
    assert b["ev"] == pytest.approx(a["ev"], rel=REL)


def test_sanity_peak_margin_is_not_capitalized_when_the_normalization_curve_is_supplied():
    st = op_state(op_margin=0.40)
    p = {"g1": 0.0, "g_terminal": 0.0, "margin_target": 0.10, "ronic": 0.12}
    fast = op.operating_chain(st, p, curves([1.0] * 5, [0.5, 0.25, 0.1, 0.0, 0.0], [1.0] * 5), disc(), roll_forward=False)
    held = op.operating_chain(st, p, curves([1.0] * 5, [1.0] * 5, [1.0] * 5), disc(), roll_forward=False)
    assert fast["ev"] < held["ev"]


# ---- helpers building a synthetic CompanyPIT ----------------------------------------------------------------------------------------------

def _pit_from_rows(rows, asof, sic=None):
    """rows: {period_end: {field: value}}. Each period is filed 60 days after its end (before the valuation date it must be)."""
    from datetime import timedelta
    series, reports = {}, []
    for pe, row in rows.items():
        filed = (date.fromisoformat(pe) + timedelta(days=60)).isoformat()
        for k, v in row.items():
            series.setdefault(k, {})[pe] = Filed(float(v), pe, filed, f"ACC-{pe}", "10-K", k)
        reports.append((pe, filed, f"ACC-{pe}", "10-K"))
    return CompanyPIT("SYN", asof, series=series, annual_reports=sorted(reports), sic=SicInfo(sic, "", "test") if sic else None)


# ---- run() consistency and the financial run -----------------------------------------------------------------------------------------------

class _PointPriors:
    """Priors that put every input at a point: a run must then equal the deterministic chain on those inputs."""

    def __init__(self, family, inputs, cv):
        self.family, self.inputs, self.cv = family, inputs, cv

    def for_company(self, family, state, asof):
        return PriorSet(family, {k: QuantileDist.point(v) for k, v in self.inputs.items()}, self.cv, {}, "test points", placeholder=False)


def test_a_run_on_point_priors_equals_the_deterministic_chain():
    pit = _operating_pit()
    inputs = {"g1": 0.06, "g_terminal": 0.02, "margin_target": 0.15, "ronic": 0.12}
    cv = curves([1.0, 0.6, 0.3, 0.0], [0.5, 0.2, 0.0, 0.0], [1.0, 0.7, 0.4, 0.2])
    d = disc()
    st = with_context(pit)
    r = op.run(pit, _PointPriors("operating", inputs, cv), d, n_draws=30, state=st)
    # Addendum H2: the engine ignores a prior's terminal growth and takes min(risk-free rate at T, 3.75%) (disc() has rf 4%: the anchor binds)
    direct = op.operating_chain(st, dict(inputs, g_terminal=0.0375), cv, d)
    assert r["terminal_growth"]["base"] == 0.0375 and "g_terminal" not in r["inputs"]
    assert r["distribution"]["equity"]["p50"] == pytest.approx(direct["equity"], rel=REL)
    assert r["distribution"]["equity"]["p10"] == pytest.approx(direct["equity"], rel=REL)
    assert r["placeholder"] is True                    # the discount rate is a placeholder here: the flag follows it
    assert r["distribution"]["n_invalid"] == 0


def test_financial_run_end_to_end_with_secondary_and_flags():
    rows = {}
    for y in range(2015, 2025):
        rows[f"{y}-12-31"] = dict(revenue=500.0 + 10 * (y - 2015), net_income=100.0 + 5 * (y - 2015), equity=1000.0 + 50 * (y - 2015),
                                  equity_incl_nci=1000.0 + 50 * (y - 2015), goodwill=100.0, intangibles_ex_goodwill=0.0, total_assets=9000.0)
    pit = _pit_from_rows(rows, asof="2025-06-30", sic="6022")
    r = fin.run(pit, PlaceholderPriors(True), disc(coe=0.10), n_draws=200, seed=9, state=with_context(pit))
    assert r["status"] == "ok" and r["family"] == "financial" and r["placeholder"] is True
    assert r["distribution"]["secondary_equity"] is not None and r["model_disagreement"] is not None
    assert r["distribution"]["tv_share"]["p50"] is not None
    assert r["at_median_inputs"]["years"][0]["tbv_begin"] == pytest.approx(1450.0 - 100.0)
    assert r["insurer_decomposition"] is None


def test_build_state_refuses_a_pit_object_that_leaks():
    pit = _operating_pit()
    leaked = Filed(1.0, "2024-12-31", "2025-06-30", "X", "10-K", "revenue")     # filed on the valuation date
    pit.series["revenue"]["2024-12-31"] = leaked
    with pytest.raises(PITViolation):
        build_state(pit)


def test_stale_asc932_tag_is_not_used():
    pit = _commodity_pit()
    n = "StandardizedMeasureOfDiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReserves"
    pit.concepts[n] = {"2018-12-31": Filed(999.0, "2018-12-31", "2019-02-20", "OLD", "10-K", n)}
    r = com.run(pit, PlaceholderPriors(True), disc(), n_draws=100, state=with_context(pit))
    assert r["secondary"]["kind"] == "tangible_book_proxy" and any("stale" in s for s in r["secondary"]["stamps"])


def test_financial_terminal_growth_follows_the_same_rule_and_the_run_reports_it():
    st = fin_state(rote_latest=0.12)
    cv = {"growth_decay": Curve([1.0, 0.5]), "rote_retention": Curve([0.5, 0.5]), "excess_fade": Curve([1.0, 1.0])}
    up = fin.financial_chain(st, {"g1": 0.06, "g_terminal": 0.02, "rote_target": 0.12}, cv, disc(coe=0.10), roll_forward=False, detail=True)
    assert up["years"][-1]["growth"] == pytest.approx(0.04) or up["terminal_growth"]["value"] == pytest.approx(0.02)
    assert up["terminal_growth"]["value"] == pytest.approx(0.02) and "min(risk-free" in up["terminal_growth"]["basis"]
    down = fin.financial_chain(st, {"g1": -0.06, "g_terminal": 0.02, "rote_target": 0.12}, {"growth_decay": Curve([1.0, 1.0]), "rote_retention": Curve([0.5, 0.5]),
                                                                                         "excess_fade": Curve([1.0, 1.0])}, disc(coe=0.10), roll_forward=False)
    assert down["terminal_growth"]["value"] == pytest.approx(-0.06)
    rows = {f"{y}-12-31": dict(revenue=500.0 + 10 * (y - 2015), net_income=100.0 + 5 * (y - 2015), equity=1000.0 + 50 * (y - 2015),
                               equity_incl_nci=1000.0 + 50 * (y - 2015), goodwill=100.0, intangibles_ex_goodwill=0.0, total_assets=9000.0) for y in range(2015, 2025)}
    pit9 = _pit_from_rows(rows, asof="2025-06-30", sic="6022")
    r = fin.run(pit9, PlaceholderPriors(True), disc(coe=0.10), n_draws=50, seed=9, state=with_context(pit9))
    assert r["terminal_growth"]["base"] == 0.0375 and "g_terminal" not in r["inputs"]        # disc() has rf 4%: the anchor binds, the placeholder's own value is ignored


# ---- Addendum H3: the return on new capital -----------------------------------------------------------------------------------------------------

def _roic_pit():
    """Five fiscal years, tax 25%, operating income 100/120/140/160/180 on invested capital 1000 (equity 1100 + debt 200 - cash 300) in every year."""
    rows = {}
    for i, y in enumerate(range(2020, 2025)):
        oi = 100.0 + 20 * i
        rows[f"{y}-12-31"] = dict(revenue=1000.0, operating_income=oi, pretax_income=oi, tax_provision=0.25 * oi, equity=1100.0, debt_lt_noncurrent=200.0,
                                  cash=300.0, net_income=0.75 * oi, goodwill=100.0, intangibles_ex_goodwill=0.0, total_assets=2000.0,
                                  current_assets=400.0, current_liabilities=200.0, capex=50.0, ppe_net=500.0, da=40.0)
    return _pit_from_rows(rows, asof="2025-06-30")


def test_the_state_carries_the_trailing_3_year_roic_level_by_hand():
    st = build_state(_roic_pit())
    # NOPAT = EBIT x 0.75 over invested capital 1000 in each year; the trailing 3 years are 2022-2024: EBIT 140, 160, 180
    assert st["roic_series"]["2024-12-31"] == pytest.approx(180 * 0.75 / 1000.0)
    assert st["roic3"] == pytest.approx((140 + 160 + 180) / 3 * 0.75 / 1000.0)
    # a year without a defined ROIC inside the window leaves the level undefined (nothing is imputed)
    pit = _roic_pit()
    del pit.series["equity"]["2023-12-31"]
    assert build_state(pit)["roic3"] is None


def test_the_ronic_path_starts_at_the_own_roic_follows_the_retention_curve_and_ends_at_wacc_plus_kappa_times_the_industry_excess_floored_at_wacc():
    # L0 = 20%, the ROIC level five years on 12%, the retention of the excess [0.9, 0.8, 0.7, 0.6, 0.5]: w_t = (1 - v_t) / (1 - v_5) = 0.2, 0.4, 0.6, 0.8, 1
    st = op_state(ronic=0.20, nwc_ratio=0.0)
    st["industry_roic"] = {"value": 0.08, "n": 50, "basis": "industry"}          # below WACC (0.10): the formula would go below WACC, so the perpetuity return is WACC (flagged)
    p = {"g1": 0.10, "g_terminal": 0.02, "margin_target": 0.10, "ronic": 0.12}
    c = curves([1.0] * 6, [0.0] * 6, [0.9, 0.8, 0.7, 0.6, 0.5, 0.5])
    r = op.operating_chain(st, p, c, disc(w=0.10), roll_forward=False, detail=True)
    assert [y["ronic"] for y in r["years"]] == pytest.approx([0.20 + (0.12 - 0.20) * w for w in (0.2, 0.4, 0.6, 0.8, 1.0, 1.0)])
    assert r["ronic_terminal"] == pytest.approx(0.10) and r["ronic_terminal_floored_at_wacc"] is True and r["ronic_terminal_kappa"] == pytest.approx(0.5)
    # the median level five years on, I + phi_5 (L0 - I), reproduces the measured fade of the excess at every year (the same identity as the margin's)
    I, L0, phi = 0.08, 0.20, [0.9, 0.8, 0.7, 0.6, 0.5]
    L5 = I + phi[4] * (L0 - I)
    r2 = op.operating_chain(st, dict(p, ronic=L5), c, disc(w=0.10), roll_forward=False, detail=True)
    for t in range(5):
        assert r2["years"][t]["ronic"] == pytest.approx(I + phi[t] * (L0 - I))
    # an industry median above WACC: Addendum J3, WACC + kappa x (I - WACC) with kappa the plateau (the curve's last value, 0.5): 0.10 + 0.5 x 0.04 = 0.12, not the median 0.14
    st3 = op_state(ronic=0.20, nwc_ratio=0.0)
    st3["industry_roic"] = {"value": 0.14, "n": 50, "basis": "industry"}
    r3 = op.operating_chain(st3, p, c, disc(w=0.10), roll_forward=False)
    assert r3["ronic_terminal"] == pytest.approx(0.12) and r3["ronic_terminal_floored_at_wacc"] is False


def test_terminal_ronic_is_wacc_plus_kappa_times_the_industry_excess_and_prices_the_terminal_growth_by_hand():
    """Addendum J3.  kappa = 1 gives the industry median (the round-3 rule when it is above WACC), kappa = 0 gives WACC, in between the interpolation; the terminal growth
    reinvestment is priced at that return: TV = (NOPAT - g x revenue x m (1 - tax) / RONIC_TV) / (WACC - g)."""
    I, wacc, g = 0.16, 0.10, 0.02
    for kappa, want in ((1.0, 0.16), (0.0, 0.10), (0.25, 0.10 + 0.25 * 0.06)):
        st = op_state(ronic=I, nwc_ratio=0.0)
        r = op.operating_chain(st, {"g1": 0.0, "g_terminal": g, "margin_target": 0.10, "ronic": I}, curves([0.0], [0.0], [kappa]), disc(w=wacc), roll_forward=False)
        assert r["ronic_terminal"] == pytest.approx(want) and r["ronic_terminal_kappa"] == pytest.approx(kappa)
        rev_N = 1000.0 * 1.02                                  # the one explicit year grows at g_T (decay 0)
        rev_T = rev_N * 1.02
        nopat_T = 0.10 * rev_T * 0.75
        reinv = (rev_T - rev_N) * 0.10 * 0.75 / want
        assert r["terminal_value"] == pytest.approx((nopat_T - reinv) / (wacc - g), rel=REL)
    # the industry median at WACC exactly is not "below": no floor flag; below WACC the flag is set and the return is WACC whatever kappa is
    st = op_state(ronic=0.10, nwc_ratio=0.0)
    r = op.operating_chain(st, {"g1": 0.0, "g_terminal": g, "margin_target": 0.10, "ronic": 0.10}, curves([0.0], [0.0], [0.4]), disc(w=0.10), roll_forward=False)
    assert r["ronic_terminal"] == pytest.approx(0.10) and r["ronic_terminal_floored_at_wacc"] is False
    st = op_state(ronic=0.07, nwc_ratio=0.0)
    for kappa in (0.0, 0.4, 1.0):
        r = op.operating_chain(st, {"g1": 0.0, "g_terminal": g, "margin_target": 0.10, "ronic": 0.07}, curves([0.0], [0.0], [kappa]), disc(w=0.10), roll_forward=False)
        assert r["ronic_terminal"] == pytest.approx(0.10) and r["ronic_terminal_floored_at_wacc"] is (kappa > 0.0)      # kappa = 0: the formula IS WACC, nothing is floored


# ---- Addendum I2: economic states are valued, counted by rule; invalid is numerical impossibility only; equity per draw is floored at 0 -----------------------------

def test_a_draw_whose_return_on_new_capital_is_not_positive_gets_no_growth_after_year_5_and_is_valued_not_invalid():
    # 7 explicit years, growth persists at g1 = 10% (decay 1), the margin held at 10%, the ROIC level five years on is -2%: the path of the return on new capital is
    # 0.15 + (-0.02 - 0.15) t / 5 (linear: a retention curve that has closed nothing by year 5), 0.116, 0.082, 0.048, 0.014, -0.02, ...
    st = op_state(ronic=0.15, nwc_ratio=0.0)
    p = {"g1": 0.10, "g_terminal": 0.02, "margin_target": 0.10, "ronic": -0.02}
    r = op.operating_chain(st, p, curves([1.0] * 7, [0.0] * 7, [1.0] * 7), disc(), roll_forward=False, detail=True)
    y = r["years"]
    assert [round(x["growth"], 6) for x in y] == [0.10] * 5 + [0.0, 0.0]               # the near-term growth stands, no growth after year 5
    assert y[5]["revenue"] == pytest.approx(y[4]["revenue"]) and y[6]["revenue"] == pytest.approx(y[4]["revenue"])
    assert y[0]["growth_reinvestment"] == pytest.approx(100.0 * 0.10 * 0.75 / 0.116)  # priced where the path's return is positive
    assert y[4]["growth_reinvestment"] == 0.0                                           # year 5: the return is -2%, growth cannot be priced: none
    assert y[5]["growth_reinvestment"] == 0.0 and y[6]["growth_reinvestment"] == 0.0
    assert r["terminal_growth"]["value"] == 0.0 and "no growth" in r["terminal_growth"]["basis"]
    assert r["terminal_reinvestment_rate"] == 0.0
    rev5 = y[4]["revenue"]
    assert r["terminal_value"] == pytest.approx(rev5 * 0.10 * 0.75 / 0.10)             # NOPAT_5 / WACC: a perpetuity with no growth
    assert set(r["rules"]) == {op.RULE_NO_GROWTH, op.RULE_NO_GROWTH_RONIC, op.RULE_UNPRICED_EARLY}


def test_a_draw_whose_long_run_margin_is_not_positive_keeps_its_negative_nopat_and_is_floored_at_zero_equity():
    st = op_state(ronic=0.15, nwc_ratio=0.10, debt=500.0)
    p = {"g1": 0.05, "g_terminal": 0.02, "margin_target": -0.03, "ronic": 0.15}
    r = op.operating_chain(st, p, curves([1.0] * 7, [0.0] * 7, [1.0] * 7), disc(), roll_forward=False, detail=True)
    assert all(x["margin"] == pytest.approx(-0.03) or x["t"] < 5 for x in r["years"])
    assert all(x["nopat"] < 0 or x["t"] < 2 for x in r["years"])                        # the NOPAT path stands, negative: no tax shield is booked on losses
    assert r["years"][-1]["revenue"] == pytest.approx(r["years"][4]["revenue"])        # no growth after year 5
    assert r["terminal_value"] < 0 and r["ev"] < 0
    assert {op.RULE_NO_GROWTH, op.RULE_NO_GROWTH_MARGIN, common.EQUITY_FLOOR_RULE} <= set(r["rules"])
    assert r["equity"] == 0.0 and r["equity_unfloored"] < 0 and r["equity_at_base_year_end"] == 0.0     # limited liability: never below zero


def test_a_shrinking_path_keeps_shrinking_in_a_no_growth_draw():
    st = op_state(ronic=0.15, nwc_ratio=0.10)
    p = {"g1": -0.04, "g_terminal": 0.02, "margin_target": 0.10, "ronic": -0.01}
    r = op.operating_chain(st, p, curves([1.0] * 7, [0.0] * 7, [1.0] * 7), disc(), roll_forward=False, detail=True)
    assert all(x["growth"] == pytest.approx(-0.04) for x in r["years"])                # growth <= 0 is not capped: the release of working capital continues
    assert r["terminal_growth"]["value"] == pytest.approx(-0.04) and "negative" in r["terminal_growth"]["basis"]


def test_a_normal_draw_has_no_rule_and_an_unfloored_equity():
    st = op_state(ronic=0.15, nwc_ratio=0.10)
    r = op.operating_chain(st, {"g1": 0.05, "g_terminal": 0.02, "margin_target": 0.10, "ronic": 0.15}, curves([1.0, 0.5, 0.0], [0.0] * 3, [1.0] * 3), disc(), roll_forward=False)
    assert r["rules"] == [] and r["equity"] == r["equity_unfloored"] > 0


def test_invalid_stays_for_numerical_impossibility_only():
    st = op_state(ronic=0.15)
    # the date's terminal growth at or above WACC: invalid
    with pytest.raises(DrawInvalid):
        op.operating_chain(st, {"g1": 0.05, "g_terminal": 0.10, "margin_target": 0.10, "ronic": 0.15}, curves([1.0], [0.0], [1.0]), disc(w=0.10), roll_forward=False)
    # a no-growth draw's terminal growth of 0 at or above a non-positive WACC: invalid
    with pytest.raises(DrawInvalid):
        op.operating_chain(st, {"g1": 0.05, "g_terminal": -0.01, "margin_target": -0.05, "ronic": 0.15}, curves([1.0] * 7, [0.0] * 7, [1.0] * 7), disc(w=-0.005), roll_forward=False)


def test_simulate_counts_the_draws_each_rule_applied_to_and_the_floored_share():
    def chain(d):
        return {"equity": max(d["x"], 0.0), "ev": d["x"], "tv_share": 0.5, "rules": ([common.EQUITY_FLOOR_RULE] if d["x"] < 0 else []) + (["r"] if d["x"] < 0.5 else [])}
    out = simulate(chain, {"x": QuantileDist({0.1: -1.0, 0.5: 0.4, 0.9: 1.0})}, 400, 3)
    assert out["n_invalid"] == 0 and out["draw_rules"]["r"] > out["draw_rules"][common.EQUITY_FLOOR_RULE] > 0
    assert out["share_negative_equity"] == pytest.approx(out["draw_rules"][common.EQUITY_FLOOR_RULE] / out["n_valid"])
    assert out["equity"]["p5"] >= 0.0


def test_the_financial_equity_per_draw_is_floored_at_zero_too():
    st = fin_state(rote_latest=-1.0, industry_rote={"value": -1.0, "n": 50, "basis": "industry"})
    p = {"g1": 0.0, "g_terminal": 0.0, "rote_target": -1.0}
    c = {"growth_decay": Curve([1.0] * 3), "rote_retention": Curve([1.0] * 3), "excess_fade": Curve([1.0] * 3)}
    r = fin.financial_chain(st, p, c, disc(coe=0.10), roll_forward=False)
    assert r["equity"] == 0.0 and r["equity_unfloored"] < 0 and r["rules"] == [common.EQUITY_FLOOR_RULE]


def test_the_operating_engine_refuses_naming_a_missing_roic_or_industry_median():
    gaps = op.state_gaps(op_state(roic3=None))
    assert any("trailing 3-year ROIC" in g for g in gaps)
    assert any("industry median ROIC at T" in g for g in op.state_gaps(op_state(industry_roic=None)))
    assert not op.state_gaps(op_state())


# ---- Addendum J1: the DIAGNOSTIC one-component swaps (valuation/variants.py); the registered engine is untouched ---------------------------------------------------

from dataclasses import replace as _replace

from valuation import variants as V


def _fin_pit():
    rows = {f"{y}-12-31": dict(revenue=500.0 + 10 * (y - 2015), net_income=100.0 + 5 * (y - 2015), equity=1000.0 + 50 * (y - 2015),
                               equity_incl_nci=1000.0 + 50 * (y - 2015), goodwill=100.0, intangibles_ex_goodwill=0.0, total_assets=9000.0) for y in range(2015, 2025)}
    return _pit_from_rows(rows, asof="2025-06-30", sic="6022")


def _runs(variant):
    """(operating, commodity, financial) results of the three engines on placeholder priors with a given variant, same seed."""
    pri = PlaceholderPriors(True)
    o = _operating_pit()
    c = _commodity_pit()
    f = _fin_pit()
    return (op.run(o, pri, disc(), n_draws=300, seed=5, state=with_context(o), variant=variant),
            com.run(c, pri, disc(), n_draws=300, seed=5, state=with_context(c), variant=variant),
            fin.run(f, pri, disc(coe=0.10), n_draws=300, seed=5, state=with_context(f), variant=variant))


def test_a_neutral_variant_and_none_are_the_registered_engine_bit_for_bit():
    base = _runs(None)
    for variant in (V.Variant(), V.Variant(name="base")):
        assert variant.neutral
        got = _runs(variant)
        for a, b in zip(base, got):
            assert a["distribution"] == b["distribution"] and a["at_median_inputs"] == b["at_median_inputs"]
    assert all(r["status"] == "ok" for r in base)


def test_the_variant_validates_its_fields():
    for bad in ({"terminal_g": "x"}, {"terminal_ronic": "x"}, {"growth_decay": "x"}, {"margin": "x"}, {"reinvestment": "x"}, {"width": 0.0}, {"width": 1.5}):
        with pytest.raises(ValueError):
            V.Variant(**bad)


def test_terminal_g_flat_replaces_the_date_value_by_the_anchor_in_the_operating_and_financial_engines():
    d = _replace(disc(), rf=0.01)                                  # the rule gives min(1%, 3.75%) = 1%
    pri = PlaceholderPriors(True)
    o = _operating_pit()
    base = op.run(o, pri, d, n_draws=60, seed=5, state=with_context(o))
    flat = op.run(o, pri, d, n_draws=60, seed=5, state=with_context(o), variant=V.Variant(terminal_g="flat"))
    assert base["terminal_growth"]["base"] == pytest.approx(0.01) and flat["terminal_growth"]["base"] == pytest.approx(0.0375)
    f = _fin_pit()
    fb = fin.run(f, pri, _replace(d, coe=0.10), n_draws=60, seed=5, state=with_context(f))
    ff = fin.run(f, pri, _replace(d, coe=0.10), n_draws=60, seed=5, state=with_context(f), variant=V.Variant(terminal_g="flat"))
    assert fb["terminal_growth"]["base"] == pytest.approx(0.01) and ff["terminal_growth"]["base"] == pytest.approx(0.0375)


def test_terminal_ronic_variants_by_hand_operating_and_the_financial_analogue():
    st = op_state(ronic=0.16, nwc_ratio=0.0)
    p = {"g1": 0.0, "g_terminal": 0.02, "margin_target": 0.10, "ronic": 0.16}
    c = curves([0.0], [0.0], [0.25])
    j3 = op.operating_chain(st, p, c, disc(w=0.10), roll_forward=False)
    med = op.operating_chain(st, p, c, disc(w=0.10), roll_forward=False, variant=V.Variant(terminal_ronic="industry_median"))
    wac = op.operating_chain(st, p, c, disc(w=0.10), roll_forward=False, variant=V.Variant(terminal_ronic="wacc"))
    assert j3["ronic_terminal"] == pytest.approx(0.10 + 0.25 * 0.06) and med["ronic_terminal"] == pytest.approx(0.16) and wac["ronic_terminal"] == pytest.approx(0.10)
    assert wac["terminal_value"] < j3["terminal_value"] < med["terminal_value"]            # a lower return on new capital makes growth dearer
    st2 = op_state(ronic=0.07, nwc_ratio=0.0)                                                  # a median below WACC: round 3 floors it at WACC too
    assert op.operating_chain(st2, dict(p, ronic=0.07), c, disc(w=0.10), roll_forward=False,
                              variant=V.Variant(terminal_ronic="industry_median"))["ronic_terminal"] == pytest.approx(0.10)
    # financial analogue: kappa 1 = the full median excess, kappa 0 = none
    stf = fin_state(industry_rote={"value": 0.14, "n": 50, "basis": "industry"})
    cf = {"growth_decay": Curve([1.0, 1.0]), "rote_retention": Curve([1.0, 1.0]), "excess_fade": Curve([0.5, 0.5])}
    pf = {"g1": 0.03, "g_terminal": 0.03, "rote_target": 0.14}
    vals = {n: fin.financial_chain(stf, pf, cf, disc(coe=0.10), roll_forward=False, variant=V.Variant(terminal_ronic=n)) for n in ("j3", "industry_median", "wacc")}
    assert vals["j3"]["terminal_excess_retention"] == pytest.approx(0.5) and vals["industry_median"]["terminal_excess_retention"] == 1.0 and vals["wacc"]["terminal_excess_retention"] == 0.0
    assert vals["wacc"]["equity"] < vals["j3"]["equity"] < vals["industry_median"]["equity"]
    assert vals["wacc"]["terminal_rote"] == pytest.approx(0.10)                                # no terminal excess: the return is the cost of equity


def test_no_decay_holds_g1_for_five_years_then_fades_linearly_to_the_measured_last_value():
    c = Curve([1.0, 0.8, 0.6, 0.4, 0.2, 0.1, 0.1, 0.1, 0.1, 0.0], "g")
    nd = V.no_decay_curve(c)
    assert nd.values[:5] == [1.0] * 5 and nd.values[-1] == pytest.approx(0.0) and len(nd) == 10
    assert nd.values[5:] == pytest.approx([1.0 - 0.2 * k for k in range(1, 6)])                 # 0.8, 0.6, 0.4, 0.2, 0.0
    assert V.no_decay_curve(Curve([1.0, 0.5, 0.2])).values == [1.0, 1.0, 1.0]                     # a horizon of 5 or fewer holds g1 throughout
    assert all(a >= b for a, b in zip(nd.values, nd.values[1:]))
    st = op_state(ronic=0.12)
    p = {"g1": 0.10, "g_terminal": 0.02, "margin_target": 0.10, "ronic": 0.12}
    cs = {"growth_decay": Curve([1.0, 0.5, 0.0, 0.0, 0.0, 0.0]), "margin_retention": Curve([0.0] * 6), "ronic_fade": Curve([1.0] * 6)}
    base = op.operating_chain(st, p, cs, disc(), roll_forward=False, detail=True)
    nd_ = op.operating_chain(st, p, V.apply_to_curves(V.Variant(growth_decay="none"), cs), disc(), roll_forward=False, detail=True)
    assert [y["growth"] for y in nd_["years"]][:5] == pytest.approx([0.10] * 5) and nd_["ev"] > base["ev"]


def test_margin_held_pins_the_margin_at_the_base_year_in_every_engine_and_instant_is_commodity_only():
    pri = PlaceholderPriors(True)
    o = _operating_pit()
    st = with_context(o)
    held = op.run(o, pri, disc(), n_draws=100, seed=5, state=st, variant=V.Variant(margin="held"))
    assert all(y["margin"] == pytest.approx(st["op_margin"]) for y in held["at_median_inputs"]["years"])
    c = _commodity_pit()
    stc = with_context(c)
    held_c = com.run(c, pri, disc(), n_draws=100, seed=5, state=stc, variant=V.Variant(margin="held"))
    assert all(y["margin"] == pytest.approx(stc["op_margin"]) for y in held_c["at_median_inputs"]["years"])
    inst = com.run(c, pri, disc(), n_draws=100, seed=5, state=stc, variant=V.Variant(margin="instant"))
    base_c = com.run(c, pri, disc(), n_draws=100, seed=5, state=stc)
    m5 = base_c["inputs"]["margin_target"]["p50"]
    assert inst["at_median_inputs"]["years"][0]["margin"] == pytest.approx(m5) and base_c["at_median_inputs"]["years"][0]["margin"] != pytest.approx(m5)
    assert inst["normalization"]["retention_year_1"] == 0.0
    f = _fin_pit()
    stf = with_context(f)
    held_f = fin.run(f, pri, disc(coe=0.10), n_draws=100, seed=5, state=stf, variant=V.Variant(margin="held"))
    assert held_f["at_median_inputs"]["years"][0]["rote"] == pytest.approx(stf["rote_latest"])         # the ROTE target is the base-year ROTE: no normalization move


def test_zero_reinvestment_zeroes_growth_reinvestment_only_and_keeps_the_working_capital_release():
    st = op_state(ronic=0.15, nwc_ratio=0.10)
    p = {"g1": 0.10, "g_terminal": 0.02, "margin_target": 0.20, "ronic": 0.15}
    z = op.operating_chain(st, p, curves([1.0, 0.0], [0.0, 0.0], [1.0, 1.0]), disc(), roll_forward=False, detail=True, variant=V.Variant(reinvestment="zero"))
    assert [y["growth_reinvestment"] for y in z["years"]] == [0.0, 0.0] and z["terminal_reinvestment_rate"] == 0.0
    assert z["years"][0]["fcff"] == pytest.approx(z["years"][0]["nopat"])
    shrink = op.operating_chain(st, dict(p, g1=-0.05), curves([1.0], [0.0], [1.0]), disc(), roll_forward=False, detail=True, variant=V.Variant(reinvestment="zero"))
    assert shrink["years"][0]["growth_reinvestment"] == pytest.approx(-5.0)                    # (950 - 1000) x 0.10: the release stays
    base = op.operating_chain(st, p, curves([1.0, 0.0], [0.0, 0.0], [1.0, 1.0]), disc(), roll_forward=False)
    assert z["ev"] > base["ev"]


def test_half_width_keeps_every_p50_and_halves_the_distance_to_it():
    d = QuantileDist({0.05: -0.10, 0.10: -0.06, 0.25: -0.02, 0.50: 0.02, 0.75: 0.10, 0.90: 0.20, 0.95: 0.30})
    h = V.scaled_dist(d, 0.5)
    assert h.ppf(0.5) == d.ppf(0.5) and h.ppf(0.9) - h.ppf(0.1) == pytest.approx(0.5 * (d.ppf(0.9) - d.ppf(0.1))) and h.ppf(0.95) - 0.02 == pytest.approx(0.5 * (0.30 - 0.02))
    assert V.scaled_dist(d, 1.0) is d
    base = _runs(None)
    half = _runs(V.Variant(width=0.5))
    for a, b in zip(base, half):
        assert b["at_median_inputs"].get("equity") == a["at_median_inputs"].get("equity")        # the point values (every input at its P50) do not move
        wa = a["distribution"]["equity"]["p90"] - a["distribution"]["equity"]["p10"]
        wb = b["distribution"]["equity"]["p90"] - b["distribution"]["equity"]["p10"]
        assert wb < wa
