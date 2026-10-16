"""Revision 18, part 1 (brief rev18 design, sections 1.1-1.5 and 1.7): the engine of the tested design in production.

  - returns: RONIC_0 = max(r, R_tc), RONIC_T = r + p x max(0, R_tc - r), +inf for +inf, no blend and no caps (also in
    test_throughcycle_record.py and test_rev17f_redesign.py);
  - margins: the trend level a + b x L of the record, full reversion, the cells gone (also in test_rev17f_redesign.py);
  - cash at face for non-financial companies: `cash_term`, `build(cash=...)`, `rs2_data.bill_rate_mean`, the pack's facts;
  - the base-year cap no longer acts;
  - the analyst-target fence prints, flags and never withholds: every consumer reads the status;
  - the desk adds the excess cash per share and equals the reference to the cent.

Fixtures are synthetic (numbers written for the test) except where a comment says otherwise.
"""
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
import rs2_data  # noqa: E402
import throughcycle_record as tc  # noqa: E402
from test_throughcycle_record import R, history, row  # noqa: E402
from test_throughcycle_reference import (COE, EST, GA, MEDIAN5, NI_BASE, OE_BASE, REDUCTION, REV_BASE, SHARES,  # noqa: E402
                                         _margin_record, _synthetic_pack, ref_long_run_margin)

REAL_BILL_RATE_MEAN = rs2_data.bill_rate_mean       # captured at import, before the suite's autouse stub (conftest) is applied
B = 1e9
INF = math.inf
X_BASE = NI_BASE + 0.05 * B * 0.75           # X of the base year: net income + amortization x (1 - 25%)


def _cash(c, y=0.04, tax=0.25):
    """A cash term that applies: cash c, bill rate y, tax rate `tax`."""
    return {"applies": True, "financial": False, "cash": c, "interest": c * y * (1.0 - tax), "stamps": []}


def _build(record, cash=None, base_cf=OE_BASE, base_ni=X_BASE, **kw):
    args = dict(base_ni=base_ni, base_revenue=REV_BASE, stub_months=8.5, anchor=GA)
    args.update(kw)
    return cr.build(base_cf, EST, COE, GA, SHARES, MEDIAN5, record=record, cash=cash, **args)


# ---- 1.2: the trend level -------------------------------------------------------------------------------------------------

def _harness_trend_level(rows, rec, L, untagged=()):
    """The backtest harness's own computation (arms.trend_level at rs2-local 40cb5cf), written out here: the Theil-Sen slope
    b of the (year, margin) series `analyse` chose, a = median(margin_y - b x y), T_L = a + b x L."""
    fns = {"with_amortization": lambda r_: tc.operating_margin(r_, untagged), "without_amortization": tc.operating_margin_plain,
           "pretax_with_amortization": lambda r_: tc.pretax_margin(r_, untagged),
           "pretax_without_amortization": tc.pretax_margin_plain}
    nrows = tc.normalise_rows(rows)
    pts = [(y, fns[rec["om_basis"]](nrows[y])) for y in rec["om_years"]]
    b = tc.theil_sen(pts)
    a = tc.median([v - b * y for y, v in pts])
    return a + b * L


def test_the_trend_level_is_the_theil_sen_line_of_the_chosen_series_at_the_base_year_by_hand():
    # margins 10%, 12%, 14%, 16%, 18%, 20%, 22%, 24% in 2018-2025: an exact line, slope 0.02 a year, T_L = 24% at 2025
    rows = history(2014, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, oi=(100.0 + 20.0 * (y - 2018)) if y >= 2018 else 100.0,
                                              amort=0.0))
    rec = tc.analyse(rows, R)
    assert rec["om_years"] == list(range(2018, 2026))
    assert rec["om_trend"] == pytest.approx(0.24, abs=1e-12)
    # the median and the shape stay as annotations: the median of 10..24% is 17%
    assert rec["om_tc"] == pytest.approx(0.17) and rec["om_shape"] in ("swing", "trend")
    # a noisy series: the line is a + b x L with b the median pairwise slope and a the median intercept, by hand
    oi = {2018: 100.0, 2019: 110.0, 2020: 90.0, 2021: 120.0, 2022: 100.0, 2023: 90.0, 2024: 100.0, 2025: 200.0}
    noisy = tc.analyse(history(2014, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, oi=oi.get(y, 100.0), amort=0.0)), R)
    pts = [(y, oi[y] / 1000.0) for y in range(2018, 2026)]
    slopes = sorted((pts[j][1] - pts[i][1]) / (pts[j][0] - pts[i][0]) for i in range(8) for j in range(i + 1, 8))
    b = (slopes[13] + slopes[14]) / 2.0                              # 28 pairwise slopes: the median is the mean of the 14th and 15th
    ints = sorted(v - b * y for y, v in pts)
    a = (ints[3] + ints[4]) / 2.0
    assert noisy["om_trend"] == pytest.approx(a + b * 2025, abs=1e-12)


@pytest.mark.parametrize("variant", ["strict", "plain_fallback", "pretax", "gap_year"])
def test_the_trend_level_equals_the_backtest_harness_computation_on_every_series_basis(variant):
    if variant == "strict":
        rows = history(2014, 2025, lambda y: row(y, revenue=1000.0 + 20 * (y - 2014), ni=100.0, oi=140.0 - 3.0 * (y - 2014) + (y % 3) * 7,
                                                  amort=15.0))
    elif variant == "plain_fallback":
        rows = history(2014, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, oi=100.0 + 5.0 * (y % 4),
                                                  amort=(None if y in (2019, 2020, 2021, 2022) else 20.0)))
    elif variant == "pretax":
        rows = history(2014, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, oi=None, pretax=90.0 + 4.0 * (y % 5), amort=10.0))
    else:
        rows = history(2014, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, oi=100.0 + (y - 2014) * 4.0,
                                                  amort=(None if y == 2021 else 20.0)))
    rec = tc.analyse(rows, R)
    assert rec["om_trend"] is not None
    assert rec["om_trend"] == _harness_trend_level(rows, rec, rec["base_year"])


def test_a_record_without_a_margin_series_has_no_trend_level():
    rows = history(2014, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, oi=None, pretax=None))
    rec = tc.analyse(rows, R)
    assert rec["om_trend"] is None and "margin_record_not_available" in rec["stamps"]
    assert tc.analyse({}, R)["om_trend"] is None


# ---- 1.3: cash at face ----------------------------------------------------------------------------------------------------

def test_cash_term_for_a_non_financial_company_by_hand():
    r_ = {"cash": 1.5 * B, "st_investments": 0.5 * B, "pretax_income": 1.0 * B, "tax_provision": 0.2 * B}
    c = cr.cash_term(r_, 0.04, "Industrials")
    assert c["applies"] is True and c["financial"] is False and c["stamps"] == []
    assert c["cash"] == 2.0 * B                                                  # cash + short-term investments
    assert c["interest"] == pytest.approx(2.0 * B * 0.04 * (1 - 0.2))            # C_L x y_L x (1 - tax_L)
    # a null short-term investment figure counts 0; a filed 0.0 cash is a value, not an absence
    assert cr.cash_term(dict(r_, st_investments=None), 0.04, "Technology")["cash"] == 1.5 * B
    zero = cr.cash_term({"cash": 0.0, "st_investments": None}, 0.04, "Technology")
    assert zero["applies"] is True and zero["cash"] == 0.0 and zero["interest"] == 0.0
    # the tax rate is throughcycle_record.tax_rate: 21% when it cannot be computed
    assert cr.cash_term({"cash": 1.0 * B}, 0.05, "Energy")["interest"] == pytest.approx(1.0 * B * 0.05 * (1 - tc.TAX_DEFAULT))
    # a bill rate of 0.0 is a value: the interest is 0, the cash term applies
    assert cr.cash_term(r_, 0.0, "Industrials")["applies"] is True and cr.cash_term(r_, 0.0, "Industrials")["interest"] == 0.0


def test_no_cash_term_for_financial_sectors_or_when_the_inputs_are_missing_and_each_says_why():
    r_ = {"cash": 1.0 * B}
    for sector in ("Financial Services", "Real Estate"):
        c = cr.cash_term(r_, 0.04, sector)
        assert c == {"applies": False, "financial": True, "cash": 0.0, "interest": 0.0, "stamps": []}
    assert cr.cash_term({"cash": None}, 0.04, "Industrials") == {
        "applies": False, "financial": False, "cash": None, "interest": 0.0, "stamps": ["cash_term_not_available"]}
    assert cr.cash_term({}, 0.04, "Industrials")["stamps"] == ["cash_term_not_available"]
    no_rate = cr.cash_term(r_, None, "Industrials")
    assert no_rate["applies"] is False and no_rate["stamps"] == ["cash_term_not_available_no_bill_rate"]
    # a missing cash is reported before a missing rate, as the backtest harness does
    assert cr.cash_term({}, None, "Industrials")["stamps"] == ["cash_term_not_available"]
    # an unknown sector is not financial
    assert cr.cash_term(r_, 0.04, "Unknown")["applies"] is True


def test_the_growth_method_takes_the_after_tax_interest_out_of_the_base_and_x_and_adds_the_cash_at_face():
    c, i = 2.0 * B, 0.06 * B
    cash = {"applies": True, "financial": False, "cash": c, "interest": i, "stamps": []}
    rec = _margin_record(x_L=X_BASE / REV_BASE)
    with_cash = _build(rec, cash)
    # the same build on the operating inputs, with x_L restated as (X_L - i_L) / revenue_L, plus the cash per share, unrolled
    manual = _build(dict(rec, x_L=(X_BASE - i) / REV_BASE), None, base_cf=OE_BASE - i, base_ni=X_BASE - i)
    assert with_cash["value"] == pytest.approx(manual["value"] + c / SHARES, abs=1e-9)
    assert with_cash["base_cf"] == pytest.approx(OE_BASE - i) and with_cash["cash"] == c and with_cash["interest_removed"] == i
    assert with_cash["earnings"][0] == pytest.approx((X_BASE - i) * 1.125)
    assert with_cash["levels"][0] == pytest.approx((OE_BASE - i) * 1.125)
    assert with_cash["method"] == "growth" and "operating_base_not_positive" not in with_cash["stamps"]
    # the x_L restatement is what stops the margin rule from adding the interest back (and counting the cash twice)
    unrestated = _build(rec, None, base_cf=OE_BASE - i, base_ni=X_BASE - i)
    assert abs(unrestated["value"] - manual["value"]) > 1e-3 and unrestated["m_long"] != manual["m_long"]
    # the caller's record is not changed
    assert rec["x_L"] == X_BASE / REV_BASE


def test_a_cash_term_that_does_not_apply_changes_nothing_but_the_stamp():
    plain = _build(_margin_record(x_L=X_BASE / REV_BASE))
    for cash in ({"applies": False, "financial": True, "cash": 0.0, "interest": 0.0, "stamps": []},
                 {"applies": False, "financial": False, "cash": None, "interest": 0.0,
                  "stamps": ["cash_term_not_available_no_bill_rate"]}):
        got = _build(_margin_record(x_L=X_BASE / REV_BASE), cash)
        assert got["value"] == plain["value"] and got["cash"] is None and got["interest_removed"] is None
        assert got["stamps"] == cash["stamps"] + plain["stamps"]
    # a cash term of 0.0 that applies is a cash term: nothing is removed and nothing added
    zero = _build(_margin_record(x_L=X_BASE / REV_BASE), _cash(0.0))
    assert zero["value"] == plain["value"] and zero["cash"] == 0.0 and zero["interest_removed"] == 0.0


def test_the_levels_method_takes_the_interest_out_of_both_levels_and_both_earnings_levels():
    est = {"0y": {"revenue": {"avg": 10.8 * B, "analysts": 20}, "eps": {"avg": 2.2, "analysts": 20, "growth": 3.0, "year_ago": 0.4}},
           "+1y": {"revenue": {"avg": 11.6 * B, "analysts": 20, "growth": 0.0741}, "eps": {"avg": 3.0, "analysts": 20, "growth": 0.36}}}
    c, i = 1.0 * B, 0.04 * B
    cash = {"applies": True, "financial": False, "cash": c, "interest": i, "stamps": []}
    kw = dict(da=0.5 * B, capex=0.4 * B, base_ni=X_BASE, base_revenue=REV_BASE, stub_months=8.5)
    plain = cr.build(OE_BASE, est, COE, GA, SHARES, MEDIAN5, record=REDUCTION, **kw)
    got = cr.build(OE_BASE, est, COE, GA, SHARES, MEDIAN5, record=REDUCTION, cash=cash, **kw)
    assert plain["method"] == got["method"] == "levels" and "levels_eps_basis" in got["stamps"]
    assert got["levels"] == pytest.approx((plain["levels"][0] - i, plain["levels"][1] - i))
    assert got["earnings"][:2] == pytest.approx([2.2 * SHARES - i, 3.0 * SHARES - i])
    # years 3-5 grow from the reduced year 2 on both series
    assert got["earnings"][2] / got["earnings"][1] == pytest.approx(plain["earnings"][2] / plain["earnings"][1])
    assert got["value"] < plain["value"] + c / SHARES                       # the interest comes off the long run, the cash is added


def test_when_the_operating_base_is_not_positive_after_the_interest_the_value_is_the_cash_per_share():
    c = 3.0 * B
    # the owner-earnings base: OE - i <= 0
    cash = {"applies": True, "financial": False, "cash": c, "interest": OE_BASE, "stamps": []}
    got = _build(_margin_record(), cash)
    assert got["value"] == pytest.approx(c / SHARES) and got["method"] == "cash_only"
    assert "operating_base_not_positive" in got["stamps"] and got["levels"] is None and got["path"] is None
    # X - i <= 0 while OE - i > 0
    cash = {"applies": True, "financial": False, "cash": c, "interest": 0.6 * B, "stamps": []}
    got = _build(_margin_record(), cash, base_cf=1.1 * B, base_ni=0.5 * B)
    assert got["value"] == pytest.approx(c / SHARES) and "operating_base_not_positive" in got["stamps"]
    # zero cash that applies: the value is 0.0, a value (not an absence)
    zero = {"applies": True, "financial": False, "cash": 0.0, "interest": 0.0, "stamps": []}
    got = _build(_margin_record(), zero, base_cf=1.1 * B, base_ni=-0.1 * B)
    assert got["value"] == 0.0 and got["method"] == "cash_only"
    # a company with no consensus at all has no reference to be worth only its cash
    nothing = cr.build(OE_BASE, None, COE, GA, SHARES, MEDIAN5, record=_margin_record(), base_ni=X_BASE, base_revenue=REV_BASE,
                       cash={"applies": True, "financial": False, "cash": c, "interest": OE_BASE, "stamps": []})
    assert nothing["value"] is None and nothing["method"] is None and nothing["reason"].startswith("no consensus estimates")
    # the pack line says why
    line = cr.pack_line(dict(_build(_margin_record(), _cash(3.0 * B, y=1.0, tax=0.0), base_cf=0.5 * B, base_ni=0.5 * B)),
                        0.5 * B, COE, GA, lambda v: f"{v / B:.3f}", anchor=GA)
    assert "CONSENSUS-IMPLIED VALUE (reference, not a forecast): $" in line and "operating_base_not_positive" in line
    assert "the operating business is valued at zero and the value is the excess cash 3.000 at face" in line
    # the levels method: year 2 no longer positive after the interest
    est = {"0y": {"revenue": {"avg": 10.8 * B, "analysts": 20}, "eps": {"avg": 2.2, "analysts": 20, "growth": 3.0, "year_ago": 0.4}},
           "+1y": {"revenue": {"avg": 11.6 * B, "analysts": 20, "growth": 0.0741}, "eps": {"avg": 3.0, "analysts": 20, "growth": 0.36}}}
    big = {"applies": True, "financial": False, "cash": c, "interest": 3.0 * SHARES, "stamps": []}
    lv = cr.build(OE_BASE, est, COE, GA, SHARES, MEDIAN5, da=0.5 * B, capex=0.5 * B, record=REDUCTION, base_ni=X_BASE,
                  base_revenue=REV_BASE, cash=big)
    assert lv["method"] == "cash_only" and lv["value"] == pytest.approx(c / SHARES)
    # a year-2 flow that was not positive before the interest keeps its own reason, not this one
    neg = cr.build(OE_BASE, est, COE, GA, SHARES, MEDIAN5, da=0.0, capex=4.0 * SHARES, record=REDUCTION, base_ni=X_BASE,
                   base_revenue=REV_BASE, cash=_cash(c))
    assert neg["value"] is None and neg["reason"].endswith("next-FY cash flow from EPS levels is not positive")
    assert "operating_base_not_positive" not in neg["stamps"]


def _turnaround_estimates():
    """A turnaround: the vendor's year-ago EPS is a loss, positive consensus EPS levels for the next two years."""
    return {"0y": {"revenue": {"avg": 10.8 * B, "analysts": 20}, "eps": {"avg": 2.2, "analysts": 20, "growth": 3.0, "year_ago": -0.5}},
            "+1y": {"revenue": {"avg": 11.6 * B, "analysts": 20, "growth": 0.0741}, "eps": {"avg": 3.0, "analysts": 20, "growth": 0.36}}}


def test_a_turnaround_is_valued_on_the_levels_method_not_on_its_cash_alone():
    """Amendment 1: the growth method's cash-only test (OE - i <= 0, or X - i <= 0) applies only to a name the growth method
    values. A loss year (X < 0) with positive consensus EPS levels goes to the levels method and is tested on its year-2 level
    after the interest; part 1 first applied the growth test to it and returned the cash alone."""
    c = 3.0 * B
    cash = {"applies": True, "financial": False, "cash": c, "interest": 0.12 * B, "stamps": []}
    kw = dict(da=0.5 * B, capex=0.4 * B, base_revenue=REV_BASE, stub_months=8.5)
    # a loss year: X < 0 while the owner-earnings base is positive (D&A above capex), and an owner-earnings base below zero
    for base_cf, base_ni in ((0.3 * B, -0.2 * B), (-0.1 * B, -0.2 * B)):
        got = cr.build(base_cf, _turnaround_estimates(), COE, GA, SHARES, MEDIAN5, record=REDUCTION, base_ni=base_ni, cash=cash, **kw)
        assert got["method"] == "levels" and "operating_base_not_positive" not in got["stamps"], got["stamps"]
        assert got["value"] > c / SHARES + 1.0                           # the levels' operating value on top of the cash
        assert got["levels"][1] == pytest.approx(3.0 * SHARES + 0.1 * B - 0.12 * B)
    # the levels branch's own check is unchanged: a year-2 level that is not positive after the interest is cash only
    big = dict(cash, interest=3.0 * SHARES + 0.2 * B)
    only = cr.build(0.3 * B, _turnaround_estimates(), COE, GA, SHARES, MEDIAN5, record=REDUCTION, base_ni=-0.2 * B, cash=big, **kw)
    assert only["method"] == "cash_only" and only["value"] == pytest.approx(c / SHARES)
    # a name valued by the growth method keeps the growth test
    growth = _build(_margin_record(), dict(cash, interest=OE_BASE))
    assert growth["method"] == "cash_only"


def test_a_levels_name_prints_its_year_1_owner_earnings_level_after_the_cash_term_as_reference_base_b(screener_data_stub, monkeypatch):
    import test_throughcycle_reference as ttr
    est = json.loads(json.dumps(ttr.EST))
    est["0y"]["eps"]["growth"] = 3.0                                   # unusable growth: the levels method values the name
    monkeypatch.setattr(ttr, "EST", est)
    calls = []
    real = cr.build
    monkeypatch.setattr(cr, "build", lambda *a, **k: (calls.append(real(*a, **k)), calls[-1])[1])
    pack = _pack_with_bill_rate(monkeypatch, 0.04)
    ref = calls[-1]
    assert ref["method"] == "levels" and ref["base_cf"] is None
    assert pack.facts["reference_base_b"] == pack_facts.q_b(ref["flows"][0] / B)
    assert pack_facts.from_text(str(pack))["reference_base_b"] == pack.facts["reference_base_b"]


def test_the_return_record_reads_r_tc_and_the_margin_record_reads_om_trend_not_the_removed_members():
    # a record that still carries the revision-17 members: they are not read
    old = dict(REDUCTION, R_tc=0.20, r_blend=0.99, ronic_t=0.13, om_tc=0.50, om_trend=0.06, om_L=0.17, x_L=0.12, tax_L=0.25,
               om_shape="swing", margin_cell="peak_swing", margin_fraction=0.5, retention=0.1)
    new = dict(old)
    for k in ("r_blend", "margin_cell", "margin_fraction", "retention"):
        new.pop(k)
    a, b = _build(old), _build(new)
    assert a["value"] == b["value"] and a["ronic0"] == 0.20


# ---- 1.4: the base-year cap -----------------------------------------------------------------------------------------------

def test_the_base_year_cap_has_no_action_in_the_pack_the_facts_or_the_verdict_stamp(screener_data_stub, monkeypatch):
    called = []
    monkeypatch.setattr(cr, "base_year_cap", lambda *a: called.append(a))
    pack = _synthetic_pack(monkeypatch)
    text = str(pack)
    assert called == [] and pack.facts["base_year_cap"] is None
    assert "BASE-YEAR CAP" not in text and "base_year_cap" not in text.split("## DEFAULTS", 1)[1] and "base-year cap removed" not in text
    assert "BASE-YEAR CHECK" in text                                                  # the check stays, as information
    flags, stamps = cv.scenario_checks(Path("nowhere"), {"base_iv": 100.0}, None, text, 100.0, facts=pack.facts)
    assert stamps["base_year_capped"] is None
    ref_stamps = cr.build(OE_BASE, EST, COE, GA, SHARES, MEDIAN5, record=REDUCTION, base_ni=NI_BASE, base_revenue=REV_BASE)["stamps"]
    assert "base_year_capped" not in ref_stamps


# ---- 1.5: the fence prints, flags and never withholds -----------------------------------------------------------------------

def test_reference_in_force_reads_the_status_and_treats_none_as_in_force():
    assert cr.reference_in_force("used") and cr.reference_in_force(None) and cr.reference_in_force("not_available")
    assert cr.reference_in_force("not_meaningful")
    assert not cr.reference_in_force("outside_fence_above") and not cr.reference_in_force("outside_fence_below")


def _desk_call(ref, **over):
    """A three-scenario desk call on the W9 fixture's own inputs (every reason given)."""
    from test_rev17f_redesign import W9_FY_BASE, _w9_reference
    base = W9_FY_BASE / B
    sc = lambda name, prob, w: {"name": name, "prob": prob, "base_cf": base, "explicit_growth": list(ref["path"]), "wacc": w}
    call = {"scenarios": [sc("Base", 0.4, COE), sc("Bull", 0.3, COE - 0.0005), sc("Bear", 0.3, COE + 0.0005)],
            "terminal_g": GA, "fade_years": 5, "sbc_treatment": "deducted_in_cf", "cash_flow_life": "perpetual",
            "cash_flow_life_reason": "d", "base_cf_reason": "d", "scenario_deviation_reason": "d",
            "bull_below_price_reason": "d", "bear_above_price_reason": "d", "terminal_reason": "d", "coe_adjustment_reason": "d",
            "shares_reason": "d", "long_run_margin": ref_long_run_margin(ref)}
    call.update(over)
    return call


def _desk_ctx(ref, **over):
    from test_rev17f_redesign import W9_CASH_BASIS, W9_FY_BASE
    lv, lr = ref["levels"], ref["long_run"]
    ctx = {"price": 1e6, "shares_default_b": 0.05, "coe_anchor": COE, "terminal_g_default": GA, "terminal_g_anchor": GA,
           "owner_earnings_default_b": W9_FY_BASE / B, "cash_basis_b": W9_CASH_BASIS / B, "reference_base_b": W9_FY_BASE / B,
           "levels": {"year1": lv[0] / B, "year2": lv[1] / B}, "terminal_ronic": ref["terminal_ronic"],
           "long_run": {"e5": lr["e5"] / B, "oe5": lr["oe5"] / B, "m5": lr["m5"], "margin_ratio": ref["margin_ratio"],
                        "r_tc": 0.15, "stub_months": 8.5, "revenue_path": ([x / B for x in ref["revenue"]] if ref.get("revenue") else None),
                              "oe_path": ([x / B for x in ref["oe_path"]] if ref.get("revenue") else None), "oe_base": (cr.oe_base(ref) / B if ref.get("revenue") else None), "nwc_intensity": ref["nwc_intensity"]},  # step 2c: the consensus revenue path and its owner earnings (the desk's own-path working capital); step 2d: their base
           "working_capital": [x / B for x in ref["wc"]]}
    ctx.update(over)
    return ctx


def test_the_desk_applies_the_reference_band_only_when_the_status_is_in_force():
    from test_rev17f_redesign import _w9_reference
    ref = _w9_reference()
    value = ref["value"]
    far = value * 3.0                                    # a reference three times the desk's own value: outside 0.75-1.33
    call = _desk_call(ref)
    call.pop("terminal_reason")
    # the default call is far from this "reference": with the status used the desk asks for guidance_deviation_reason
    used = fmt.execute_financial_model(call, _desk_ctx(ref, consensus_implied_value=far, reference_status="used"))
    assert "guidance_deviation_reason" in used["error"]
    for status in (None,):                                # an older facts dict with no status reads as in force
        out = fmt.execute_financial_model(call, _desk_ctx(ref, consensus_implied_value=far, reference_status=status))
        assert "guidance_deviation_reason" in out["error"]
    # outside the fence: the number is printed and flagged, and the desk neither asks for a reason nor adds a refusal
    for status in ("outside_fence_above", "outside_fence_below"):
        out = fmt.execute_financial_model(call, _desk_ctx(ref, consensus_implied_value=far, reference_status=status))
        assert "error" not in out, out.get("error")
        assert out["scenario_dcfs"][0]["dcf"]["per_share_iv"] == pytest.approx(value, abs=0.0051)
    # the unit-error note reads "the reference else today's price": an outside-fence reference is not the reference
    wild = _desk_ctx(ref, consensus_implied_value=value * 500.0, reference_status="outside_fence_above", price=1e6)
    assert "error" not in fmt.execute_financial_model(call, wild)


def test_the_levels_hold_and_the_bull_bear_bands_apply_whatever_the_reference_status():
    """Revision 18 gated the levels by the reference's status; revision 19 (AT10 fix item 2) does not: the printed levels are the pack's
    consensus cash flows, not the reference's value (test_rev19_part_f.py has the per-status tests)."""
    from test_rev17f_redesign import _w9_reference
    ref = _w9_reference()
    path = list(ref["path"])
    path[1] = path[1] + 0.20                                  # a Base year 2 far above the printed level
    call = _desk_call(ref)
    call["scenarios"][0]["explicit_growth"] = path                                    # Base: year 2 far above the level
    call["scenarios"][1]["explicit_growth"] = path[:1] + [path[1] + 0.10] + path[2:]   # Bull: higher still
    call.pop("guidance_deviation_reason", None)
    used = fmt.execute_financial_model(call, _desk_ctx(ref, reference_status="used"))
    assert "error" not in used and used["years12_held"]["dcfs"][0]["name"] == "Base"
    outside = fmt.execute_financial_model(call, _desk_ctx(ref, reference_status="outside_fence_above"))
    assert "error" not in outside and outside["years12_held"]["dcfs"][0]["name"] == "Base"      # the hold fires outside the fence too (revision 19)
    assert (outside["scenario_dcfs"][0]["dcf"]["per_share_iv"] == used["scenario_dcfs"][0]["dcf"]["per_share_iv"])
    # the Bull/Bear year-2 bound (scenario_deviation_reason) is a band too
    call.pop("scenario_deviation_reason")
    lv = {"year1": ref["levels"][0] / B, "year2": ref["levels"][1] / B, "bull2": ref["levels"][1] / B, "bear2": ref["levels"][1] / B}
    needs = fmt.execute_financial_model(call, _desk_ctx(ref, levels=lv, reference_status="used"))
    assert "scenario_deviation_reason" in needs.get("error", "")
    assert "scenario_deviation_reason" in fmt.execute_financial_model(
        call, _desk_ctx(ref, levels=lv, reference_status="outside_fence_below")).get("error", "")      # revision 19: R11 applies outside the fence too


def test_the_harness_flag_and_the_stamps_read_the_status():
    import consensus_reference
    facts = dict(pack_facts.empty(), consensus_implied_value=100.0, reference_status="used")
    sc = {"base_iv": 40.0, "stage1_growth_path": [0.1] * 5, "guidance_deviation_reason": None}
    flags = lambda f: cv.check_sample_harness_rules(sc, 90.0, desk_info={"desk_per_share_ivs": [40.0]}, enrich_data={},
                                                    facts=f)[2]
    assert "base_far_from_consensus_implied" in flags(facts)
    for status in ("outside_fence_above", "outside_fence_below"):
        assert "base_far_from_consensus_implied" not in flags(dict(facts, reference_status=status))
    assert consensus_reference.FAR_LOW == 0.75
    # base_to_civ is an annotation: it is stamped whatever the status, next to consensus_reference_status
    ratios = cv.consensus_ratios({"base_iv": 40.0}, None, None, facts=dict(facts, reference_status="outside_fence_above"))
    assert ratios["base_to_civ"] == 0.4 and ratios["consensus_implied_value"] == 100.0
    _, stamps = cv.scenario_checks(Path("nowhere"), {"base_iv": 40.0}, None, "", 90.0, facts=dict(facts, reference_status="outside_fence_below"))
    assert stamps["consensus_reference_status"] == "outside_fence_below"


def test_pack_reference_returns_the_reference_in_force_only():
    block = lambda status, civ: ("# DATA PACK - X   (pack revision 17)\n\n" +
                                 pack_facts.render_defaults_block(dict(pack_facts.empty(), consensus_implied_value=civ,
                                                                       reference_status=status)))
    assert cv._pack_reference(block("used", 120.0))[0] == 120.0
    assert cv._pack_reference(block("outside_fence_above", 460.0))[0] is None
    assert pack_facts.from_text(block("outside_fence_above", 460.0))["consensus_implied_value"] == 460.0    # the facts keep it


def test_the_defaults_line_says_a_value_outside_the_fence_is_a_level_check_only():
    f = dict(pack_facts.empty(), consensus_implied_value=460.0, reference_status="outside_fence_above")
    line = next(l for l in pack_facts.render_defaults_block(f).splitlines() if l.startswith("- consensus_implied_value:"))
    assert line.startswith("- consensus_implied_value: 460.00 | outside the street-target fence") and "level check only" in line
    assert "needs guidance_deviation_reason" not in line
    used = next(l for l in pack_facts.render_defaults_block(dict(f, reference_status="used")).splitlines()
                if l.startswith("- consensus_implied_value:"))
    assert "needs guidance_deviation_reason" in used and "level check" not in used


# ---- 1.7: the desk adds the cash and equals the reference ---------------------------------------------------------------------

def _dcf(excess_cash=None, frame="equity", net_debt=None, **kw):
    args = dict(base_cf=1.0, explicit_growth=[0.08] * 5, wacc=0.09, terminal_g=0.03, shares_diluted=0.5, fade_years=5,
                sbc_treatment="deducted_in_cf", valuation_frame=frame, net_debt=net_debt, terminal_ronic=INF)
    args.update(kw)
    return fmt.unbundled_dcf(excess_cash=excess_cash, **args)


def test_the_desk_adds_excess_cash_per_share_in_the_equity_frame_only():
    plain = _dcf()
    withc = _dcf(excess_cash=2.0)                                   # $2B on 0.5B shares: $4 a share
    assert withc["per_share_iv"] == pytest.approx(plain["per_share_iv"] + 4.0, abs=0.0051)
    assert withc["excess_cash"] == 2.0 and plain["excess_cash"] == 0.0
    assert withc["equity_value"] == pytest.approx(plain["equity_value"] + 2.0, abs=0.0051)
    assert _dcf(excess_cash=0.0)["per_share_iv"] == plain["per_share_iv"]
    # the firm frame's net debt already nets the cash: nothing is added
    firm = _dcf(frame="firm", net_debt=0.5, rate_type="TRUE_WACC", wacc=0.09)
    firm_c = _dcf(excess_cash=2.0, frame="firm", net_debt=0.5, rate_type="TRUE_WACC", wacc=0.09)
    assert firm_c["per_share_iv"] == firm["per_share_iv"] and firm_c["excess_cash"] == 0.0
    # a finite cash-flow life: the same cash at face
    fin = fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.08] * 5, wacc=0.09, terminal_g=0.03, shares_diluted=0.5, fade_years=5,
                            sbc_treatment="deducted_in_cf", finite_life_years=10, excess_cash=2.0)
    fin0 = fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.08] * 5, wacc=0.09, terminal_g=0.03, shares_diluted=0.5, fade_years=5,
                             sbc_treatment="deducted_in_cf", finite_life_years=10)
    assert fin["per_share_iv"] == pytest.approx(fin0["per_share_iv"] + 4.0, abs=0.0051)
    # the cash is divided by the shares the DCF uses (dilution included)
    dil = fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.08] * 5, wacc=0.09, terminal_g=0.03, shares_diluted=0.5, fade_years=5,
                            sbc_treatment="dilution", sbc_dilution=0.10, terminal_ronic=INF, excess_cash=2.0)
    dil0 = fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.08] * 5, wacc=0.09, terminal_g=0.03, shares_diluted=0.5, fade_years=5,
                             sbc_treatment="dilution", sbc_dilution=0.10, terminal_ronic=INF)
    # (the unrounded values: two values rounded to the cent can differ by up to a cent more than the cash; revision 24 step 2d changed the value
    # here - the fade now starts at the unlimited terminal return - and the rounded check no longer held by chance)
    assert dil["per_share_iv_raw"] == pytest.approx(dil0["per_share_iv_raw"] + 2.0 / 0.55, abs=1e-9)


def test_the_desk_reads_excess_cash_from_the_context_and_a_departure_needs_a_reason():
    from test_rev17f_redesign import _w9_reference
    ref = _w9_reference()
    base = fmt.execute_financial_model(_desk_call(ref), _desk_ctx(ref))
    assert "error" not in base
    with_default = fmt.execute_financial_model(_desk_call(ref), _desk_ctx(ref, excess_cash=1.0))
    assert with_default["scenario_dcfs"][0]["dcf"]["per_share_iv"] == pytest.approx(
        base["scenario_dcfs"][0]["dcf"]["per_share_iv"] + 1.0 / 0.05, abs=0.0051)
    # every scenario carries it
    assert all(abs(a["dcf"]["per_share_iv"] - b["dcf"]["per_share_iv"] - 20.0) <= 0.0051
               for a, b in zip(with_default["scenario_dcfs"], base["scenario_dcfs"]))
    # the DEFAULTS amount passed back (to the printed precision) needs no reason
    same = fmt.execute_financial_model(_desk_call(ref, excess_cash=1.0000004), _desk_ctx(ref, excess_cash=1.0))
    assert "error" not in same
    # a different amount does
    other = fmt.execute_financial_model(_desk_call(ref, excess_cash=0.4), _desk_ctx(ref, excess_cash=1.0))
    assert "excess_cash_reason needed" in other["error"]
    ok = fmt.execute_financial_model(_desk_call(ref, excess_cash=0.4, excess_cash_reason="cash held abroad, per the 2026-08 10-Q"),
                                     _desk_ctx(ref, excess_cash=1.0))
    assert "error" not in ok
    assert ok["scenario_dcfs"][0]["dcf"]["per_share_iv"] == pytest.approx(base["scenario_dcfs"][0]["dcf"]["per_share_iv"] + 8.0, abs=0.0051)
    # no DEFAULTS amount (None) counts as 0 (revision 19, AT10 fix item 3: with no fact it is also the bound, so an amount above it is refused
    # whatever the reason; R15 still reads a negative amount as a departure)
    assert "no reason allows it" in fmt.execute_financial_model(_desk_call(ref, excess_cash=0.5), _desk_ctx(ref))["error"]
    assert "excess_cash_reason needed" in fmt.execute_financial_model(_desk_call(ref, excess_cash=-0.5), _desk_ctx(ref))["error"]


def test_the_desk_equals_the_reference_to_the_cent_with_a_cash_term_on_a_seeded_sweep():
    """The revision-17 sweep (test_throughcycle_reference), with a cash term: random estimates, records, rates and stubs on both
    reference methods; the desk, given the reference's own base, flows, long run and the DEFAULTS excess cash, returns the
    reference's per-share value to the cent every time."""
    import random
    rng = random.Random(20261001)
    checked = cash_only = 0
    for case in range(300):
        coe = rng.uniform(0.06, 0.12)
        gt = rng.uniform(0.01, min(0.04, coe - 0.02))
        shares = rng.uniform(20e6, 900e6)
        rev0 = rng.uniform(1.0, 30.0) * B
        ni0 = rev0 * rng.uniform(0.03, 0.2)
        oe0 = ni0 * rng.uniform(0.6, 1.4)
        growth_ok = rng.random() < 0.7
        c1, c2 = rng.uniform(-0.2, 0.5), rng.uniform(-0.1, 0.3)
        eps0 = ni0 / shares
        est = {"0y": {"revenue": {"avg": rev0 * (1 + rng.uniform(-0.05, 0.15)), "analysts": 12, "growth": 0.05, "year_ago": rev0},
                      "eps": {"avg": eps0 * (1 + c1), "analysts": 12, "growth": c1 if growth_ok else 3.0, "year_ago": eps0}},
               "+1y": {"revenue": {"avg": rev0 * (1 + rng.uniform(0.0, 0.3)), "analysts": 12, "growth": rng.uniform(-0.05, 0.25)},
                       "eps": {"avg": eps0 * (1 + c1) * (1 + c2), "analysts": 12, "growth": c2}}}
        record = {"R_tc": rng.choice([INF, rng.uniform(0.02, 0.4), None]),
                  "nwc_intensity": rng.choice([None, rng.uniform(-0.15, 0.4)]), "stamps": []}
        trend = rng.choice([None, rng.uniform(-0.03, 0.3)])
        record.update(om_trend=trend, om_L=None if trend is None else rng.uniform(0.02, 0.3),
                      x_L=rng.choice([None, rng.uniform(0.02, 0.25)]), tax_L=rng.uniform(0.0, 0.35))
        record["ronic_t"] = (INF if record["R_tc"] == INF else coe if record["R_tc"] is None
                             else coe + rng.random() * max(0.0, record["R_tc"] - coe))
        stub = rng.choice([None, rng.uniform(0.5, 14.0)])
        da = rng.uniform(0.2, 1.2) * oe0 if not growth_ok else None
        capex = da * rng.uniform(0.5, 1.5) if da is not None else None
        cash_c = rng.uniform(0.0, 4.0) * oe0
        cash = _cash(cash_c, y=rng.uniform(0.0, 0.06), tax=record["tax_L"])
        ref = cr.build(oe0, est, coe, gt, shares, rng.uniform(0.02, 0.1), record=record, base_ni=ni0, base_revenue=rev0,
                       stub_months=stub, da=da, capex=capex, cash=cash)
        if ref["value"] is None or ref["levels"] is None:
            continue
        if ref["method"] == "cash_only":
            cash_only += 1
            continue
        lr = ref["long_run"]
        facts = {"terminal_ronic": ref["terminal_ronic"],
                 "long_run": {"e5": lr["e5"] / B, "oe5": lr["oe5"] / B, "m5": lr["m5"], "margin_ratio": ref["margin_ratio"],
                              "r_tc": record["R_tc"], "stub_months": stub, "revenue_path": ([x / B for x in ref["revenue"]] if ref.get("revenue") else None),
                              "oe_path": ([x / B for x in ref["oe_path"]] if ref.get("revenue") else None), "oe_base": (cr.oe_base(ref) / B if ref.get("revenue") else None), "nwc_intensity": ref["nwc_intensity"]},  # step 2c: the consensus revenue path and its owner earnings (the desk's own-path working capital); step 2d: their base
                 "working_capital": [x / B for x in ref["wc"]] if ref["wc"] else None}
        lv = ref["levels"]
        if ref["base_cf"] is not None:
            base, path = ref["base_cf"] / B, ref["path"]
        else:
            # revision 24 step 2d: a levels name is valued on the pack's own convention (consensus_reference.defaults_desk_args): its base is the
            # year-1 level grown at 0 in year 1, the base its oe_path pairs with (oe_base), at which the desk normalizes working capital's revenue path
            base = lv[0] / B
            path = [0.0, lv[1] / lv[0] - 1] + ref["path"][2:]
        sc = lambda name, prob, w: {"name": name, "prob": prob, "base_cf": base, "explicit_growth": list(path), "wacc": w}
        call = {"scenarios": [sc("Base", 0.4, coe), sc("Bull", 0.3, coe - 0.0005), sc("Bear", 0.3, coe + 0.0005)],
                "terminal_g": gt, "fade_years": 5, "sbc_treatment": "deducted_in_cf", "cash_flow_life": "perpetual",
                "cash_flow_life_reason": "t", "base_cf_reason": "t", "scenario_deviation_reason": "t",
                "bull_below_price_reason": "t", "bear_above_price_reason": "t", "terminal_reason": "t",
                "coe_adjustment_reason": "t", "long_run_margin": ref_long_run_margin(ref)}
        ctx = {"price": 1e-3, "shares_default_b": shares / B, "coe_anchor": coe, "terminal_g_default": gt,
               "owner_earnings_default_b": base, "levels": {"year1": lv[0] / B, "year2": lv[1] / B},
               "terminal_ronic": facts["terminal_ronic"], "long_run": facts["long_run"],
               "working_capital": facts["working_capital"], "cash_basis_b": None, "excess_cash": cash_c / B}
        out = fmt.execute_financial_model(call, ctx)
        if "error" in out:
            out = {"scenario_dcfs": [{"dcf": fmt.unbundled_dcf(
                base_cf=base, explicit_growth=path, wacc=coe, terminal_g=gt, shares_diluted=shares / B, fade_years=5,
                sbc_treatment="deducted_in_cf", terminal_ronic=facts["terminal_ronic"], long_run=facts["long_run"],
                working_capital=facts["working_capital"], excess_cash=cash_c / B, long_run_margin=ref_long_run_margin(ref))}]}
        desk = out["scenario_dcfs"][0]["dcf"]["per_share_iv"]
        assert abs(desk - ref["value"]) <= 0.0051, (case, desk, ref["value"], record, stub)
        checked += 1
    assert checked >= 200 and cash_only >= 0


# ---- rs2_data.bill_rate_mean ----------------------------------------------------------------------------------------------

def _fred_store(tmp_path, rows):
    """A stand-in for MRI's raw FRED store: data/raw/fred/raw_observations.parquet with series_id, date (text) and value."""
    import duckdb
    d = tmp_path / "mri" / "data" / "raw" / "fred"
    d.mkdir(parents=True)
    src = tmp_path / "obs.json"
    src.write_text(json.dumps([{"series_id": s, "date": dt, "value": v} for s, dt, v in rows]), encoding="utf-8")
    con = duckdb.connect()
    con.execute(f"COPY (SELECT series_id, date, value FROM read_json_auto('{src.as_posix()}')) TO '{(d / 'raw_observations.parquet').as_posix()}' "
                f"(FORMAT PARQUET)")
    con.close()
    return tmp_path / "mri"


def test_bill_rate_mean_is_the_dtb3_mean_over_the_window_as_a_fraction(tmp_path, monkeypatch):
    monkeypatch.setattr(rs2_data, "bill_rate_mean", REAL_BILL_RATE_MEAN)       # the real function, not the suite's default stub
    rows = [("DTB3", "2024-12-31", 9.0),            # on the start date: outside (start, end]
            ("DTB3", "2025-01-02", 4.0), ("DTB3", "2025-06-30", 5.0), ("DTB3", "2025-12-31", 3.0),   # inside; end is included
            ("DTB3", "2026-01-02", 8.0),            # after the end
            ("DGS10", "2025-06-30", 40.0)]          # another series
    mri = _fred_store(tmp_path, rows)
    monkeypatch.setenv("MRI_DIR", str(mri))
    rate, why = rs2_data.bill_rate_mean("2024-12-31", "2025-12-31")
    assert rate == pytest.approx((4.0 + 5.0 + 3.0) / 3 / 100.0) and "3 observations" in why
    # dates as date objects
    from datetime import date
    assert rs2_data.bill_rate_mean(date(2024, 12, 31), date(2025, 12, 31))[0] == pytest.approx(rate)
    # a window with no observation: no rate, with the reason
    none, why = rs2_data.bill_rate_mean("2020-01-01", "2020-12-31")
    assert none is None and "no_DTB3_observations" in why
    # a 0.0 bill rate is a value
    (tmp_path / "z").mkdir()
    monkeypatch.setenv("MRI_DIR", str(_fred_store(tmp_path / "z", [("DTB3", "2025-03-03", 0.0)])))
    assert rs2_data.bill_rate_mean("2025-01-01", "2025-12-31")[0] == 0.0
    # no store: no rate, with the reason
    monkeypatch.setenv("MRI_DIR", str(tmp_path / "nowhere"))
    none, why = rs2_data.bill_rate_mean("2025-01-01", "2025-12-31")
    assert none is None and why.startswith("no_raw_observations_parquet")


# ---- the pack: the cash term reaches the facts, the reference and the desk ---------------------------------------------------------

def _pack_with_bill_rate(monkeypatch, rate, sector="Industrials"):
    monkeypatch.setattr(rs2_data, "bill_rate_mean", lambda start, end: (rate, "stub") if rate is not None else (None, "stub: none"))
    real_lookup = rs2_data.sector_lookup
    monkeypatch.setattr(rs2_data, "sector_lookup", lambda t: (sector, real_lookup(t)[1]))
    pack = _synthetic_pack(monkeypatch)
    return pack


def test_the_pack_computes_excess_cash_prints_it_and_takes_the_interest_out_of_the_default_and_the_reference(screener_data_stub, monkeypatch):
    without = _pack_with_bill_rate(monkeypatch, None)
    with_cash = _pack_with_bill_rate(monkeypatch, 0.04)
    f0, f1 = without.facts, with_cash.facts
    # the synthetic base year 2025 (test_throughcycle_reference._cycle_history): cash 10% of 8.0B x 1.03^11 of revenue, no
    # short-term investments, tax 25% of pre-tax income
    c_l = 8.0 * B * 1.03 ** 11 * 0.10
    i_l = c_l * 0.04 * (1 - 0.25)
    assert f1["excess_cash"] == pack_facts.q_b(c_l / B) and f0["excess_cash"] is None
    assert "cash_term_not_available_no_bill_rate" in f0["long_run"]["stamps"]
    assert not any(s.startswith("cash_term") for s in f1["long_run"]["stamps"])
    # the Base's owner-earnings default and the reference's base lose the after-tax interest
    assert f1["owner_earnings_default_b"] == pytest.approx(f0["owner_earnings_default_b"] - i_l / B, abs=0.0011)
    assert f1["reference_base_b"] == pytest.approx(f0["reference_base_b"] - i_l / B, abs=1e-6)
    # the reference's value: the operating value plus the cash at face
    assert f1["reference_status"] == "used" and f0["reference_status"] == "used"
    t0, t1 = str(without), str(with_cash)
    assert "- excess_cash: not available | " in t0 and f"- excess_cash: {c_l / B:.6f} | " in t1
    assert pack_facts.parity(f1, pack_facts.from_text(t1)) == [] and pack_facts.from_text(t1)["excess_cash"] == f1["excess_cash"]
    # the desk, on the printed facts, equals the reference to the cent with the cash added per share
    parsed = pack_facts.from_text(t1)
    assert parsed["owner_earnings_default_b"] == f1["owner_earnings_default_b"]


def test_a_financial_company_has_no_cash_term_and_excess_cash_is_zero(screener_data_stub, monkeypatch):
    plain = _pack_with_bill_rate(monkeypatch, None, sector="Financial Services")
    fin = _pack_with_bill_rate(monkeypatch, 0.04, sector="Financial Services")
    assert fin.facts["excess_cash"] == 0.0 and plain.facts["excess_cash"] == 0.0
    assert not any(s.startswith("cash_term") for s in fin.facts["long_run"]["stamps"])
    assert fin.facts["reference_base_b"] == plain.facts["reference_base_b"]
    assert fin.facts["consensus_implied_value"] == plain.facts["consensus_implied_value"]
    assert "- excess_cash: 0.000000 | " in str(fin)


def test_the_desk_on_the_packs_printed_facts_equals_the_reference_with_the_cash_to_the_cent(screener_data_stub, monkeypatch):
    calls = []
    real = cr.build
    monkeypatch.setattr(cr, "build", lambda *a, **k: (calls.append(real(*a, **k)), calls[-1])[1])
    pack = _pack_with_bill_rate(monkeypatch, 0.04)
    ref = calls[-1]
    c_l = 8.0 * B * 1.03 ** 11 * 0.10
    assert ref["cash"] == pytest.approx(c_l) and ref["interest_removed"] == pytest.approx(c_l * 0.04 * 0.75)
    text = str(pack)
    parsed = pack_facts.from_text(text)
    lv, base = ref["levels"], ref["base_cf"] / B
    ctx = {"price": 1e6, "shares_default_b": parsed["shares_default"] / B, "coe_anchor": parsed["coe_anchor"],
           "terminal_g_default": parsed["terminal_g_default"], "terminal_g_anchor": parsed["terminal_g_anchor"],
           "owner_earnings_default_b": base, "levels": {"year1": lv[0] / B, "year2": lv[1] / B},
           "terminal_ronic": parsed["terminal_ronic"], "long_run": parsed["long_run"],
           "working_capital": parsed["working_capital"], "cash_basis_b": parsed["cash_basis_b"],
           "reference_base_b": parsed["reference_base_b"], "excess_cash": parsed["excess_cash"],
           "reference_status": parsed["reference_status"]}
    sc = lambda name, prob, w: {"name": name, "prob": prob, "base_cf": base, "explicit_growth": list(ref["path"]), "wacc": w}
    reasons = {k: "diagnostic" for k in ("cash_flow_life_reason", "base_cf_reason", "scenario_deviation_reason",
                                         "bull_below_price_reason", "bear_above_price_reason", "terminal_reason",
                                         "coe_adjustment_reason", "shares_reason")}
    call = dict(reasons, scenarios=[sc("Base", 0.4, parsed["coe_anchor"]), sc("Bull", 0.3, parsed["coe_anchor"] - 0.0005),
                                    sc("Bear", 0.3, parsed["coe_anchor"] + 0.0005)],
                terminal_g=parsed["terminal_g_default"], fade_years=5, sbc_treatment="deducted_in_cf", cash_flow_life="perpetual",
                long_run_margin=ref_long_run_margin(ref))
    out = fmt.execute_financial_model(call, ctx)
    assert "error" not in out, out.get("error")
    dcf = out["scenario_dcfs"][0]["dcf"]
    assert dcf["excess_cash"] == round(parsed["excess_cash"], 4)
    assert abs(dcf["per_share_iv"] - ref["value"]) <= 0.0051, (dcf["per_share_iv"], ref["value"])


# ---- the reduction: the part-1 switches reproduce revision 16's arithmetic ------------------------------------------------------

def test_with_the_part_1_switches_on_the_engine_is_revision_16s_arithmetic_to_the_cent():
    """Returns +inf, margin rule off, working capital off, cash off, X = owner earnings and revision 16's terminal growth: the
    value equals revision 16's `reference_value` (kept in the module for this test) on the growth method. The book-wide
    reduction against revision 16's own `build` runs in a separate process (rev18/reduction_worker.py)."""
    switches = {"R_tc": INF, "ronic_t": INF, "om_trend": None, "om_L": None, "nwc_intensity": None, "stamps": []}
    ref = cr.build(OE_BASE, EST, COE, GA, SHARES, MEDIAN5, record=switches, base_ni=OE_BASE, base_revenue=REV_BASE,
                   stub_months=8.5, cash=None)
    path = cr.reference_path(EST["0y"]["eps"]["growth"], EST["+1y"]["eps"]["growth"], EST["+1y"]["revenue"]["growth"], MEDIAN5)
    old = cr.reference_value(OE_BASE, path, COE, GA, SHARES) * (1 + COE) ** (8.5 / 12)
    assert ref["value"] == pytest.approx(old, abs=1e-9) and round(ref["value"], 2) == round(old, 2)
    assert ref["stamps"] == ["working_capital_not_available"] and ref["margin_ratio"] is None and ref["wc"] is None
