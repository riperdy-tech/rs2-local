"""Tests of the valuation package's arithmetic, by hand-computed cases on synthetic fixtures (no network, no real company).

The census cases at the bottom are REGRESSION SANITY only: they check that a structural defect of the old reference cannot occur in
the new chain (no zero long-run margin from a margin translation, no forced positive perpetual growth). No constant anywhere is tuned
to make a named stock come out right, and no test names a stock's value.
"""
import json
import math
from datetime import date
from pathlib import Path

import pytest

from valuation import common, classification as cl, engine_commodity as com, engine_financial as fin, engine_operating as op
from valuation.common import (CompanyPIT, Curve, DrawInvalid, Filed, InputError, PITViolation, QuantileDist, SicInfo, build_state,
                              cyclicality_score, draw_inputs, equity_bridge, greenwald_maintenance_capex, simulate)
from valuation.discount_rate import DiscountRate, cost_of_equity, relever_beta, wacc
from valuation.priors_interface import PlaceholderPriors, PriorSet

REL = 1e-9


def disc(w=0.10, coe=0.12, asof="2025-06-30"):
    return DiscountRate(asof=asof, rf=0.04, erp=0.05, beta_unlevered=1.0, de_ratio=0.0, de_basis="book", tax=0.25, beta_levered=1.0,
                        coe=coe, kd_pretax=None, wacc=w, placeholder=True)


def op_state(**kw):
    st = {"ticker": "SYN", "asof": "2025-06-30", "base_period": "2024-12-31", "revenue": 1000.0, "op_margin": 0.10, "tax_rate": 0.25,
          "maint_gap_ratio": 0.0, "nwc_ratio": 0.10, "debt": 0.0, "finance_lease_liability": 0.0, "operating_lease_liability": 0.0,
          "nci": 0.0, "cash": 0.0, "st_investments": 0.0, "lt_investments": 0.0, "read_as_none": [], "missing": []}
    st.update(kw)
    return st


def curves(g, m, r):
    return {"growth_decay": Curve(g), "margin_retention": Curve(m), "ronic_fade": Curve(r)}


# ---- the operating chain, hand computed -----------------------------------------------------------------------------------------------

def test_operating_chain_two_years_by_hand():
    st = op_state(debt=200.0, cash=50.0, nci=10.0, finance_lease_liability=20.0, lt_investments=30.0, operating_lease_liability=77.0)
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
    st = op_state(nwc_ratio=0.10)
    p = {"g1": -0.05, "g_terminal": -0.02, "margin_target": 0.20, "ronic": 0.15}
    r = op.operating_chain(st, p, curves([1.0], [0.0], [1.0]), disc(), roll_forward=False, detail=True)
    y1 = r["years"][0]
    assert y1["revenue"] == pytest.approx(950.0)
    assert y1["growth_reinvestment"] == pytest.approx(-5.0)           # (950 - 1000) x 0.10: a release
    assert y1["fcff"] == pytest.approx(142.5 + 5.0)
    # terminal: rev 931, NOPAT 139.65, release (931 - 950) x 0.10 = -1.9, FCFF 141.55, TV = 141.55 / (0.10 + 0.02)
    assert r["terminal_value"] == pytest.approx(141.55 / 0.12)
    assert r["terminal_reinvestment_rate"] < 0
    ev = 147.5 / 1.1 + (141.55 / 0.12) / 1.1
    assert r["ev"] == pytest.approx(ev, rel=REL)
    assert r["equity"] == pytest.approx(ev, rel=REL)
    # no floor: a more negative terminal growth is a (weakly) different, still valid, value
    p2 = dict(p, g_terminal=-0.10)
    assert op.operating_chain(st, p2, curves([1.0], [0.0], [1.0]), disc(), roll_forward=False)["ev"] > 0


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
          "tax_rate": 0.2, "read_as_none": [], "missing": []}
    st.update(kw)
    return st


def test_financial_excess_return_by_hand():
    st = fin_state()
    p = {"g1": 0.03, "g_terminal": 0.03, "rote_target": 0.15}
    c = {"growth_decay": Curve([1.0, 1.0]), "rote_retention": Curve([1.0, 1.0]), "excess_fade": Curve([1.0, 0.5])}
    r = fin.financial_chain(st, p, c, disc(coe=0.10), roll_forward=False, detail=True)
    y1, y2 = r["years"]
    assert y1["excess_return"] == pytest.approx(50.0)
    assert y2["excess_return"] == pytest.approx(0.025 * 1030.0)
    tv = 0.025 * 1060.9 / 0.07
    expected = 1000 + 50 / 1.1 + 25.75 / 1.21 + tv / 1.21
    assert r["equity"] == pytest.approx(expected, rel=REL)
    assert r["price_to_tbv_implied"] == pytest.approx(expected / 1000.0)


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
    p = {"g1": 0.0, "g_terminal": 0.0, "margin_target": 0.10, "ronic": 0.12}
    nc = Curve([0.6, 0.3, 0.1])
    r = op.operating_chain(st, p, {"growth_decay": Curve([1.0] * 3), "margin_retention": nc, "ronic_fade": Curve([1.0] * 3)}, disc(),
                           roll_forward=False, detail=True)
    assert r["years"][0]["margin"] == pytest.approx(0.10 + 0.20 * 0.6)         # year 1 is already normalized, not the 30% peak
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
    with_sm = com.run(_commodity_pit(asc932=1500.0), pri, d, n_draws=200)
    assert with_sm["status"] == "ok" and with_sm["secondary"]["kind"] == "asc932_standardized_measure"
    assert with_sm["secondary"]["proxy"] is False
    st = build_state(_commodity_pit(asc932=1500.0))
    yrs = (date(2025, 6, 30) - date(2024, 12, 31)).days / 365.25
    assert with_sm["secondary"]["equity"] == pytest.approx((1500.0 - 100.0 + 50.0) * 1.12 ** yrs)
    no_sm = com.run(_commodity_pit(), pri, d, n_draws=200)
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
    r = op.run(pit, PlaceholderPriors(True), disc(), n_draws=300, seed=5)
    assert r["status"] == "ok" and r["family"] == "operating"
    d = r["distribution"]
    assert d["n_valid"] > 0 and d["equity"]["p10"] <= d["equity"]["p50"] <= d["equity"]["p90"]
    assert 0.0 < d["tv_share"]["p50"] < 1.5
    assert d["secondary_equity"] is not None and r["model_disagreement"] is not None
    assert "inputs drawn independently" in " ".join(r["notes"])
    assert r["placeholder"] is True and r["discount"]["placeholder"] is True
    assert r["base_period"] == "2024-12-31"
    again = op.run(pit, PlaceholderPriors(True), disc(), n_draws=300, seed=5)
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
    shrink = {"g1": -0.04, "g_terminal": -0.02, "margin_target": 0.05, "ronic": 0.10}
    grow = dict(shrink, g_terminal=0.0236)
    c = curves([1.0] * 5, [1.0] * 5, [1.0] * 5)
    a = op.operating_chain(st, shrink, c, disc(), roll_forward=False, detail=True)
    b = op.operating_chain(st, grow, c, disc(), roll_forward=False)
    assert a["years"][-1]["growth"] == pytest.approx(-0.02 + (-0.04 + 0.02) * 1.0)    # decay 1 holds g1; the engine takes the supplied curve
    assert a["ev"] < b["ev"]
    # the chain imposes no floor: whatever terminal growth the (population) prior supplies is what is used
    low = op.operating_chain(st, dict(shrink, g_terminal=-0.08), c, disc(), roll_forward=False)
    assert low["terminal_value"] < a["terminal_value"]


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
    r = op.run(pit, _PointPriors("operating", inputs, cv), d, n_draws=30)
    st = build_state(pit)
    direct = op.operating_chain(st, inputs, cv, d)
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
    r = fin.run(pit, PlaceholderPriors(True), disc(coe=0.10), n_draws=200, seed=9)
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
