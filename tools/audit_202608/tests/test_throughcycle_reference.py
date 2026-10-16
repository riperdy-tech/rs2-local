"""Revision 17 (brief B sections 2, 3, 4 and tests 2-4): the reference's long run, the terminal-growth
default, the base-year cap, the desk that must agree with the reference to the cent, and the Base years 1-2
the desk holds at the printed levels.

Fixtures are synthetic (numbers written for the test) except where a comment says a figure comes from a
recorded run (EZPW's revision-14 Base, LAMR's base-year gap).
"""
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))

import consensus_reference as cr  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
import throughcycle_record as tc  # noqa: E402

B = 1e9
INF = math.inf
# a record that reduces the long run to revision 16's arithmetic: unlimited returns, no cycle, no working capital
REDUCTION = {"R_tc": INF, "r_blend": INF, "ronic_t": INF, "cycle": False, "m_tc": None, "nwc_intensity": None, "stamps": []}

EST = {
    "0y": {"revenue": {"avg": 10.8 * B, "low": 10.5 * B, "high": 11.0 * B, "analysts": 20, "growth": 0.08,
                       "year_ago": 10.0 * B},
           "eps": {"avg": 2.7, "low": 2.6, "high": 2.8, "analysts": 20, "growth": 0.125, "year_ago": 2.4}},
    "+1y": {"revenue": {"avg": 11.6 * B, "low": 11.2 * B, "high": 12.0 * B, "analysts": 20, "growth": 0.0741,
                        "year_ago": 10.8 * B},
            "eps": {"avg": 3.0, "low": 2.8, "high": 3.2, "analysts": 20, "growth": 0.1111, "year_ago": 2.7}},
}
SHARES = 500e6
COE, GA, MEDIAN5 = 0.09, 0.0375, 0.05
OE_BASE = 1.1 * B          # FY net income 1.2B + D&A 0.5B - capex 0.6B
NI_BASE = 1.2 * B          # filed: 2.4 x 500M shares, the vendor's year-ago EPS exactly
REV_BASE = 10.0 * B


def _cycle_history(op_margins=None):
    """Twelve years: high-margin and low-margin runs on flat equity, with demand downturns (revenue down more than
    5% and earnings down more than a third) in 2016 and 2020, so the record shows a cycle and a median margin above
    the latest years'. Operating income (brief F1's operating-margin record) is 1.4 times the net margin less the
    acquired-intangible amortization the row tags, so (operating income + amortization) / revenue is 1.4 x the net
    margin; `op_margins` ({year: that margin}) overrides it."""
    swing = {2014: 15, 2015: 15, 2016: 2, 2017: 2, 2018: 14, 2019: 14, 2020: 3, 2021: 13, 2022: 13, 2023: 12,
             2024: 12, 2025: 12}
    level = {2016: 0.88, 2017: 0.88, 2020: 0.85}
    rows = {}
    for y in range(2014, 2026):
        rev = 8.0 * B * 1.03 ** (y - 2014) * level.get(y, 1.0)
        om = (op_margins or {}).get(y, swing[y] / 100.0 * 1.4)
        rows[y] = {"revenue": rev, "net_income": rev * swing[y] / 100.0, "equity": 6.0 * B, "goodwill": 0.5 * B,
                   "intangibles_ex_goodwill": 0.5 * B, "amortization_intangibles": 0.05 * B,
                   "operating_income": rev * om - 0.05 * B,
                   "pretax_income": rev * swing[y] / 80.0, "tax_provision": rev * swing[y] / 80.0 * 0.25,
                   "current_assets": rev * 0.35, "cash": rev * 0.10, "current_liabilities": rev * 0.20,
                   "st_investments": 0.0, "debt_current": rev * 0.02, "short_term_borrowings_separate": 0.0}
    return rows


def _build(record, **kw):
    args = dict(base_ni=NI_BASE, base_revenue=REV_BASE, stub_months=8.5, anchor=GA)
    args.update(kw)
    return cr.build(OE_BASE, EST, COE, GA, SHARES, MEDIAN5, record=record, **args)


# ---- test 2: the reduction ----------------------------------------------------------------------

def test_the_reference_reduces_to_revision_16_to_the_cent_on_the_growth_method():
    # OE = NI (D&A = capex), no cycle, no working capital, RONIC_T = +inf, the same terminal growth
    ref = cr.build(OE_BASE, EST, COE, GA, SHARES, MEDIAN5, record=REDUCTION, base_ni=OE_BASE, base_revenue=REV_BASE,
                   stub_months=8.5)
    path = cr.reference_path(EST["0y"]["eps"]["growth"], EST["+1y"]["eps"]["growth"],
                            EST["+1y"]["revenue"]["growth"], MEDIAN5)
    old = cr.reference_value(OE_BASE, path, COE, GA, SHARES) * (1 + COE) ** (8.5 / 12)
    assert ref["method"] == "growth" and ref["long_run_path"] == "revenue"
    assert ref["stamps"] == ["working_capital_not_available"]          # no classified balance sheet: no deduction, stamped
    assert round(ref["value"], 2) == round(old, 2)
    assert ref["value"] == pytest.approx(old, rel=1e-12)
    # and on the fallback path (no vendor revenue), where the long run follows owner earnings
    no_rev = {k: dict(v, revenue={"analysts": 0}) for k, v in EST.items()}
    ref2 = cr.build(OE_BASE, no_rev, COE, GA, SHARES, MEDIAN5, record=REDUCTION, base_ni=OE_BASE,
                    base_revenue=REV_BASE, stub_months=8.5)
    path2 = cr.reference_path(no_rev["0y"]["eps"]["growth"], no_rev["+1y"]["eps"]["growth"], None, MEDIAN5)
    old2 = cr.reference_value(OE_BASE, path2, COE, GA, SHARES) * (1 + COE) ** (8.5 / 12)
    assert ref2["long_run_path"] == "owner_earnings_ratio"
    assert round(ref2["value"], 2) == round(old2, 2)


def test_the_reference_reduces_to_revision_16_to_the_cent_on_the_levels_method():
    # a trough: consensus EPS growth is unusable, the EPS levels carry years 1-2 (MU / LIND in revision 16)
    est = {"0y": {"revenue": {"avg": 10.8 * B, "analysts": 20}, "eps": {"avg": 2.2, "analysts": 20, "growth": 3.0,
                                                                     "year_ago": 0.4}},
           "+1y": {"revenue": {"avg": 11.6 * B, "analysts": 20, "growth": 0.0741},
                   "eps": {"avg": 3.0, "analysts": 20, "growth": 0.36}}}
    da, capex = 0.5 * B, 0.6 * B
    ref = cr.build(OE_BASE, est, COE, GA, SHARES, MEDIAN5, da=da, capex=capex, stub_months=None,
                   record=REDUCTION, base_ni=NI_BASE, base_revenue=REV_BASE)
    assert ref["method"] == "levels"
    flows = (2.2 * SHARES + da - capex, 3.0 * SHARES + da - capex)
    old = cr.reference_value_levels(flows[0], flows[1], cr._years35(0.0741, MEDIAN5), COE, GA, SHARES)
    # net income differs from owner earnings by D&A - capex here, so the reduction needs D&A = capex
    ref_eq = cr.build(OE_BASE, est, COE, GA, SHARES, MEDIAN5, da=0.5 * B, capex=0.5 * B, record=REDUCTION,
                      base_ni=NI_BASE, base_revenue=REV_BASE)
    flows_eq = (2.2 * SHARES, 3.0 * SHARES)
    old_eq = cr.reference_value_levels(flows_eq[0], flows_eq[1], cr._years35(0.0741, MEDIAN5), COE, GA, SHARES)
    assert round(ref_eq["value"], 2) == round(old_eq, 2)
    assert ref["value"] is not None and old is not None       # the unequal D&A / capex case still values


# ---- the long run -------------------------------------------------------------------------------

def test_long_run_value_closed_forms():
    r, g, gt, e5 = 0.10, 0.06, 0.03, 100.0
    # F = 0: no long-run years; the terminal is the value-driver form at year 5
    lr = cr.long_run_value(e5, g, gt, r, 0.15, 0.15, None, 0)
    tv = e5 * (1 + gt) * (1 - gt / 0.15) / (r - gt)
    assert lr["flows"] == [] and lr["tv"] == pytest.approx(tv) and lr["tv_pv"] == pytest.approx(tv / 1.1 ** 5)
    assert lr["value"] == lr["value_raw"] == pytest.approx(tv / 1.1 ** 5) and lr["floor"] is False
    # RONIC = the cost of equity: growth adds no value, the terminal is E_{N+1} / r
    lr = cr.long_run_value(e5, g, gt, r, r, r, None, 5)
    assert lr["tv"] == pytest.approx(lr["e_terminal"] / r)
    # RONIC below the cost of equity is charged at the cost of equity (max(r, RONIC))
    low = cr.long_run_value(e5, g, gt, r, 0.05, 0.05, None, 5)
    assert low["value"] == pytest.approx(lr["value"])
    # an infinite RONIC charges nothing: the terminal is Gordon on the earnings
    inf = cr.long_run_value(e5, g, gt, r, INF, INF, None, 5)
    assert inf["tv"] == pytest.approx(inf["e_terminal"] / (r - gt))
    assert all(f == pytest.approx(e) for f, e in zip(inf["flows"], inf["earnings"]))
    # growth fades linearly from g to gt over the five years and the reinvestment charge 1 / RONIC runs linearly from start to end
    # (revision 24 step 2a, D4: it was RONIC itself)
    lr5 = cr.long_run_value(e5, g, gt, r, 0.20, 0.12, None, 5)
    assert lr5["growth"] == pytest.approx([g + (gt - g) * i / 5 for i in range(1, 6)])
    assert lr5["ronic"] == pytest.approx([1 / (1 / 0.20 + (1 / 0.12 - 1 / 0.20) * i / 5) for i in range(1, 6)])
    # the cash flow of year t pays for the growth of year t+1 (g_{N+1} = terminal g)
    e = lr5["earnings"]
    g_next = lr5["growth"][1:] + [gt]
    assert lr5["flows"] == pytest.approx([e[i] * (1 - g_next[i] / max(r, lr5["ronic"][i])) for i in range(5)])
    # a cycle margin ratio scales the earnings toward it, reaching it in the last year
    cyc = cr.long_run_value(e5, g, gt, r, 0.15, 0.15, 0.5, 5)
    assert cyc["margin_factor"] == pytest.approx([1 + (0.5 - 1) * i / 5 for i in range(1, 6)])
    assert cyc["e_terminal"] == pytest.approx(e5 * math.prod(1 + x for x in cyc["growth"]) * 0.5 * (1 + gt))
    # not defined when the rate does not clear terminal growth
    assert cr.long_run_value(e5, g, 0.10, 0.10, 0.15, 0.15, None, 5) is None


def test_an_infinite_start_or_end_moves_the_charge_linearly():
    """Was `test_an_infinite_start_holds_until_the_last_fade_year`. Revision 24 step 2a (D4): ronic_at moves 1 / RONIC linearly, an unlimited
    return being a charge of 0, so an infinite start or end no longer holds the start until the last fade year."""
    assert cr.ronic_at(INF, 0.12, 0.5) == pytest.approx(0.24) and cr.ronic_at(INF, 0.12, 1.0) == 0.12      # 1 / RONIC = 0.5 x 1 / 0.12
    assert cr.ronic_at(0.2, INF, 0.5) == pytest.approx(0.4) and cr.ronic_at(INF, INF, 0.5) == INF           # 1 / RONIC = 0.5 x 1 / 0.2
    assert cr.ronic_at(0.2, 0.1, 0.0) == 0.2 and cr.ronic_at(0.2, 0.1, 0.5) == pytest.approx(1 / 7.5)       # (5 + 10) / 2 = 7.5


def test_a_negative_long_run_value_is_floored_at_zero_and_stamped():
    lr = cr.long_run_value(-100.0, 0.05, 0.03, 0.10, 0.12, 0.12, None, 5)
    assert lr["floor"] is True and lr["value_raw"] < 0 and lr["value"] == 0.0
    # in the reference: a net income path that is negative values the first five years only
    est = {"0y": dict(EST["0y"]), "+1y": dict(EST["+1y"])}
    ref = cr.build(OE_BASE, est, COE, GA, SHARES, MEDIAN5, record=REDUCTION, base_ni=-0.5 * B, base_revenue=REV_BASE)
    assert "long_run_floor" in ref["stamps"] and ref["long_run"]["floor"] is True
    only_years_1_5 = sum(cf / (1 + COE) ** (t + 1) for t, cf in enumerate(cr._compound(OE_BASE, ref["path"]))) / SHARES
    assert ref["value"] == pytest.approx(only_years_1_5)


def test_the_earnings_and_revenue_paths_and_the_working_capital_deduction():
    rec = dict(REDUCTION, nwc_intensity=0.10)
    ref = _build(rec)
    ni, rev, wc = ref["earnings"], ref["revenue"], ref["wc"]
    assert ni[0] == pytest.approx(NI_BASE * (1 + 0.125)) and ni[1] == pytest.approx(NI_BASE * 1.125 * 1.1111)
    assert rev[:3] == [REV_BASE, 10.8 * B, 11.6 * B]                    # base year filed, then the vendor's averages
    g35 = ref["path"][2:]
    assert rev[3:] == pytest.approx([11.6 * B * (1 + g35[0]), 11.6 * B * (1 + g35[0]) * (1 + g35[1]),
                                     11.6 * B * (1 + g35[0]) * (1 + g35[1]) * (1 + g35[2])])
    # years 3-5: net income and revenue grow at the same rate, so the year-2 margin is held
    assert ni[4] / rev[5] == pytest.approx(ni[1] / rev[2])
    assert wc == pytest.approx([0.10 * (rev[t] - rev[t - 1]) for t in range(1, 6)])
    without = _build(dict(REDUCTION, nwc_intensity=None))
    assert without["wc"] is None and "working_capital_not_available" in without["stamps"]
    assert without["value"] > ref["value"]                             # the deduction lowers the value


# brief F2, revision 18: the operating-margin record the reference's margin rule reads (om_trend, om_L, x_L, tax_L; om_tc and
# om_shape are annotations); the fixture's consensus year-5 earnings margin m5 is about 12.9%, and an X margin of 12% at the
# base year puts OM_5 near 18.3%
def _margin_record(**kw):
    return dict(REDUCTION, **dict(dict(om_tc=0.06, om_trend=0.06, om_L=0.17, om_shape="trend", x_L=0.12, tax_L=0.25), **kw))


def test_the_margin_rule_moves_the_margin_all_the_way_to_the_trend_level_and_lowers_a_peak_value():
    """Revision 18: the margin moves all the way to max(0, the record's trend level) by year 10, whatever the shape of the
    record's history (no cells, no fractions)."""
    m5 = (NI_BASE * 1.125 * 1.1111) / (11.6 * B)                         # about 0.1294
    flat = _build(REDUCTION)                                             # no operating-margin record: the margin is held
    assert flat["long_run"]["margin_ratio"] is None and "margin_cell" not in flat and "margin_fraction" not in flat
    peak = _build(_margin_record())                                      # OM_5 = 0.17 + (m5 - 0.12) / 0.75, above the trend level 0.06
    om_5 = 0.17 + (m5 - 0.12) / 0.75
    assert peak["om_5"] == pytest.approx(om_5)
    m_long = m5 + 0.75 * (0.06 - om_5)
    assert peak["m_long"] == pytest.approx(m_long) and peak["margin_ratio"] == pytest.approx(m_long / m5)
    assert peak["long_run"]["margin_ratio"] == peak["margin_ratio"]
    assert peak["value"] < flat["value"]                                 # moving toward a lower trend level lowers the value
    trough = _build(_margin_record(om_trend=0.30))
    assert trough["margin_ratio"] > 1
    assert trough["value"] > flat["value"]                               # and toward a higher one raises it
    # a record without a trend level (short record) changes nothing, and says so
    short = _build(dict(REDUCTION, om_trend=None, om_L=None, stamps=["operating_margin_record_not_available"]))
    assert short["value"] == flat["value"] and short["margin_ratio"] is None
    assert "operating_margin_record_not_available" in short["stamps"]


def test_without_a_revenue_path_the_long_run_takes_earnings_from_owner_earnings():
    no_rev = {k: dict(v, revenue={"analysts": 0}) for k, v in EST.items()}
    ref = cr.build(OE_BASE, no_rev, COE, GA, SHARES, MEDIAN5, record=dict(REDUCTION, cycle=True, m_tc=0.01,
                                                                      nwc_intensity=0.2),
                   base_ni=NI_BASE, base_revenue=REV_BASE)
    assert ref["long_run_path"] == "owner_earnings_ratio" and ref["revenue"] is None and ref["wc"] is None
    assert ref["long_run"]["e5"] == pytest.approx(ref["earnings"][4])   # E_t = OE_t x (NI_5 / OE_5)
    assert ref["long_run"]["margin_ratio"] is None                     # no revenue path: no cycle margin, no working capital
    # a year-5 net income that is not positive has no earnings to carry: not available, with the reason
    dead = cr.build(OE_BASE, no_rev, COE, GA, SHARES, MEDIAN5, record=REDUCTION, base_ni=-1.0 * B)
    assert dead["value"] is None and "year-5 earnings or owner earnings is not positive" in dead["reason"]
    # vendor revenue that is not on the filed basis (the vintage test failed) is not combined with the filed revenue
    blocked = _build(REDUCTION, levels_block="the vendor's year-ago revenue does not match")
    assert blocked["long_run_path"] == "owner_earnings_ratio" and blocked["value"] is not None


def test_a_missing_record_is_stamped_and_grows_at_the_cost_of_equity():
    ref = _build(None)
    assert "record_not_available" in ref["stamps"] and ref["terminal_ronic"] == COE and ref["ronic0"] == COE
    inf = _build(REDUCTION)
    assert ref["value"] < inf["value"]
    stamped = _build(dict(REDUCTION, R_tc=None, r_blend=None, ronic_t=COE, stamps=["record_not_available"]))
    assert "record_not_available" in stamped["stamps"] and stamped["ronic0"] == COE


# ---- section 2a: the base-year cap ---------------------------------------------------------------

def test_the_growth_methods_earnings_start_from_x_and_the_levels_method_is_stamped():
    """Brief B2 F1: the earnings path's base is X (net income before acquired-intangible amortization). Revision 18: the
    base-year cap no longer acts."""
    amort_after_tax = 0.05 * B * 0.75
    x_base = NI_BASE + amort_after_tax
    plain = _build(REDUCTION)
    on_x = _build(REDUCTION, base_ni=x_base)
    assert on_x["earnings"][0] == pytest.approx(x_base * 1.125) and plain["earnings"][0] == pytest.approx(NI_BASE * 1.125)
    assert on_x["long_run"]["e5"] / plain["long_run"]["e5"] == pytest.approx(x_base / NI_BASE)
    assert on_x["value"] > plain["value"]                              # the add-back is a real, larger long-run earnings base
    import inspect
    assert "base_cap" not in inspect.signature(cr.build).parameters and "base_year_capped" not in on_x["stamps"]
    # the levels method takes the vendor's EPS times shares whatever X is, and says the basis is unknown
    est = {"0y": {"revenue": {"avg": 10.8 * B, "analysts": 20}, "eps": {"avg": 2.2, "analysts": 20, "growth": 3.0,
                                                                     "year_ago": 0.4}},
           "+1y": {"revenue": {"avg": 11.6 * B, "analysts": 20, "growth": 0.0741},
                   "eps": {"avg": 3.0, "analysts": 20, "growth": 0.36}}}
    lv = cr.build(OE_BASE, est, COE, GA, SHARES, MEDIAN5, da=0.5 * B, capex=0.5 * B, record=REDUCTION,
                  base_ni=x_base, base_revenue=REV_BASE)
    assert lv["method"] == "levels" and "levels_eps_basis" in lv["stamps"]
    assert lv["earnings"][:2] == pytest.approx([2.2 * SHARES, 3.0 * SHARES])
    assert "levels_eps_basis" not in plain["stamps"]


def test_the_base_year_cap_removes_a_gain_and_never_raises_a_base():
    cap = cr.base_year_cap(587e6, 101.5e6, 5.08)                      # LAMR: filed $5.78 against the vendor's $5.08
    assert cap["eps_filed"] == pytest.approx(587e6 / 101.5e6) and cap["eps_vendor"] == 5.08
    assert cap["ni_capped"] == pytest.approx(5.08 * 101.5e6)
    assert cap["removed"] == pytest.approx(587e6 - 5.08 * 101.5e6)
    assert cr.base_year_cap(587e6, 101.5e6, 5.78) is None              # equal
    assert cr.base_year_cap(587e6, 101.5e6, 5.68) is None              # within the 2%: 5.78 / 5.68 = +1.8%
    assert cr.base_year_cap(587e6, 101.5e6, 5.60) is not None          # 5.78 / 5.60 = +3.2%
    assert cr.base_year_cap(400e6, 101.5e6, 5.08) is None              # filed EPS below the vendor's: kept (E10)
    assert cr.base_year_cap(587e6, 0.0, 5.08) is None and cr.base_year_cap(587e6, 101.5e6, 0.0) is None
    assert cr.base_year_cap(None, 101.5e6, 5.08) is None


def test_the_base_year_cap_no_longer_acts_on_the_lamr_case():
    """LAMR (revision 14): consensus +19.4% ran from an adjusted $5.08 against a filed $5.78 that held the Vistar gain.
    Revision 17 capped the base at the vendor's EPS; revision 18 removed the cap's action: `build` takes no cap, the base is
    the filed one and no stamp or pack sentence names a cap (`base_year_cap` itself stays, unused)."""
    filed_sh, filed_ni, ya = 101.5e6, 587e6, 5.08
    est = {"0y": {"revenue": {"avg": 2.3 * B, "analysts": 8, "year_ago": 2.1 * B},
                  "eps": {"avg": 5.08 * 1.194, "analysts": 8, "growth": 0.194, "year_ago": ya}},
           "+1y": {"revenue": {"avg": 2.4 * B, "analysts": 8, "growth": 0.043},
                   "eps": {"avg": 6.9, "analysts": 8, "growth": 0.1375, "year_ago": 5.08 * 1.194}}}
    cap = cr.base_year_cap(filed_ni, filed_sh, ya)                 # the function stays and still measures the gap
    assert cap is not None and cap["removed"] > 0
    oe = 694e6
    plain = cr.build(oe, est, 0.0848, 0.0375, filed_sh, 0.05, record=REDUCTION, base_ni=filed_ni,
                     base_revenue=2.1 * B)
    consensus_eps_1 = 5.08 * 1.194
    assert abs(plain["earnings"][0] / (consensus_eps_1 * filed_sh) - 1) > 0.10       # the filed base: +14% above consensus
    assert plain["base_cf"] == pytest.approx(oe) and "base_year_capped" not in plain["stamps"]
    assert "base_year_cap" not in plain
    line = cr.pack_line(plain, oe, 0.0848, 0.0375, lambda v: f"{v / 1e9:.3f}", anchor=0.0375)
    assert "base-year cap" not in line and "base: owner earnings 0.694" in line


# ---- section 3: the terminal-growth default -------------------------------------------------------

def test_terminal_growth_is_the_revenue_trend_held_between_breakeven_and_the_anchor():
    assert cr.terminal_growth_default(0.0375, 0.0234, 0.031, 0.02, 0.05) == (0.031, "revenue_trend", None)
    assert cr.terminal_growth_default(0.0375, 0.0234, 0.05, 0.02, 0.05)[0] == 0.0375        # held at the anchor
    assert cr.terminal_growth_default(0.0375, 0.0234, 0.01, 0.02, 0.05)[0] == 0.0234        # floored at breakeven
    assert cr.terminal_growth_default(0.0375, 0.0234, -0.02, 0.02, 0.05)[0] == 0.0234
    # no trend (a short record): the revision-16 rule, stamped as the consensus fallback
    val, basis, reason = cr.terminal_growth_default(0.0375, 0.0234, None, 0.009, 0.043)
    assert (val, basis) == (0.0234, "consensus_fallback") and reason == "next-FY consensus revenue growth (0.9%) is below the anchor"
    assert cr.terminal_growth_default(0.0375, 0.0234, None, None, 0.043)[:2] == (0.0375, "consensus_fallback")
    # no breakeven: the revision-16 rule too (it says the floor is not available)
    val, basis, reason = cr.terminal_growth_default(0.0375, None, 0.03, 0.009, 0.043)
    assert (val, basis) == (0.0375, "consensus_fallback") and "not available" in reason
    assert cr.terminal_growth_default(None, 0.0234, 0.03, 0.009, 0.043) == (None, None, None)


# ---- test 3: the desk equals the reference -------------------------------------------------------

def ref_long_run_margin(ref):
    """Revision 24 step 2a: the desk input that reproduces a reference's own long run, its margin rule's m_long; where the rule held the margin
    (no ratio), the year-5 margin m5; with no revenue path (m5 None) the desk cannot apply a long_run_margin and holds the margin, so any number
    (0.10) gives the reference's long run. The desk takes long_run_margin from the analyst; this is the reference's choice, for parity."""
    lr = ref.get("long_run") or {}
    if ref.get("m_long") is not None:
        return ref["m_long"]
    return lr["m5"] if lr.get("m5") is not None else 0.10


def _facts_for(ref, record, gt, quantize):
    """The pack's facts for a reference, as capability_test builds them; quantize=True prints them at the
    DEFAULTS block's precision and reads them back, the way the desk receives them from a sidecar or text."""
    f = pack_facts.empty()
    lr_raw = {"cycle": record["cycle"], "cycle_year": record.get("cycle_year"), "m_tc": record["m_tc"],
              "m_years": [2018, 2025, 8], "r_tc": record["R_tc"], "r_years": [2018, 2025, 8], "p": record.get("p"),
              "r_blend": record["r_blend"], "margin_ratio": ref["margin_ratio"],
              "g_rev": None, "g_rev_years": None, "terminal_g_basis": "revenue_trend",
              "nwc_intensity": record["nwc_intensity"], "nwc_years": [2018, 2025, 8],
              "stamps": list(record.get("stamps") or []), "stub_months": ref["stub_months"],
              "ni_over_oe": NI_BASE / OE_BASE,
              "e5": ref["long_run"]["e5"] / B, "oe5": ref["long_run"]["oe5"] / B, "m5": ref["long_run"]["m5"]}
    if quantize:
        f["terminal_ronic"] = pack_facts.q_rate(ref["terminal_ronic"])
        f["long_run"] = pack_facts.quantize_long_run(lr_raw)
        f["working_capital"] = [pack_facts.q_b(x / B) for x in ref["wc"]] if ref["wc"] else None
        f["coe_anchor"], f["terminal_g_default"] = pack_facts.q_rate(COE), pack_facts.q_rate(gt)
        block = pack_facts.render_defaults_block(f)
        return pack_facts.from_text("# DATA PACK - X   (pack revision 17)\n\n" + block)
    f["terminal_ronic"] = ref["terminal_ronic"]
    f["long_run"] = {k: (v if not isinstance(v, float) else v) for k, v in lr_raw.items()}
    f["working_capital"] = [x / B for x in ref["wc"]] if ref["wc"] else None
    f["coe_anchor"], f["terminal_g_default"] = COE, gt
    return f


def _desk_default_base(ref, facts, coe, gt, shares_default):
    """The desk's value for the reference's own inputs: its base, its growth path and the DEFAULTS' rate, terminal
    growth and share count."""
    lv = ref["levels"]
    ctx = {"price": 300.0, "shares_default_b": shares_default / B, "coe_anchor": facts["coe_anchor"],
           "terminal_g_default": facts["terminal_g_default"], "terminal_g_anchor": GA,
           "owner_earnings_default_b": ref["base_cf"] / B,
           "levels": {"year1": lv[0] / B, "year2": lv[1] / B},
           "terminal_ronic": facts["terminal_ronic"], "long_run": facts["long_run"],
           "working_capital": facts["working_capital"], "cash_basis_b": None}
    sc = lambda name, prob: {"name": name, "prob": prob, "base_cf": ref["base_cf"] / B,
                             "explicit_growth": list(ref["path"]), "wacc": coe}
    call = {"scenarios": [sc("Base", 0.5), sc("Bull", 0.25), sc("Bear", 0.25)], "terminal_g": gt,
            "fade_years": 5, "sbc_treatment": "deducted_in_cf", "cash_flow_life": "perpetual",
            "cash_flow_life_reason": "test", "bull_below_price_reason": "test", "bear_above_price_reason": "test",
            "long_run_margin": ref_long_run_margin(ref)}
    out = fmt.execute_financial_model(call, ctx)
    assert "error" not in out, out.get("error")
    return out["scenario_dcfs"][0]["dcf"]


@pytest.mark.parametrize("record_kw", [
    dict(),                                                         # steady: unlimited returns, no margin move, no working capital
    dict(R_tc=0.18, r_blend=0.18, ronic_t=0.135, nwc_intensity=0.06),               # finite return, working capital
    dict(R_tc=0.18, r_blend=0.18, ronic_t=0.135, nwc_intensity=0.06,
         om_trend=0.075, om_L=0.17, om_shape="swing", x_L=0.12, tax_L=0.25),        # and a margin peak (trend level below year 5)
    dict(R_tc=INF, r_blend=INF, ronic_t=INF, nwc_intensity=-0.02,
         om_trend=0.30, om_L=0.17, om_shape="trend", x_L=0.12, tax_L=0.25),         # unlimited returns, margin trough
    dict(R_tc=0.18, r_blend=0.18, ronic_t=0.135, nwc_intensity=0.06,
         om_trend=-0.02, om_L=0.05, om_shape="trend", x_L=None, tax_L=0.21),        # a loss trend level, filed anchor
], ids=["unlimited", "funded-wc", "peak-margin", "inf-trough", "loss-record"])
def test_the_desk_equals_the_reference_on_the_reference_own_inputs(record_kw):
    record = dict(REDUCTION, **record_kw)
    gt = 0.0325
    ref = cr.build(OE_BASE, EST, COE, gt, SHARES, MEDIAN5, record=record, base_ni=NI_BASE, base_revenue=REV_BASE,
                   stub_months=8.5, anchor=GA)
    assert ref["value"] is not None
    exact = _desk_default_base(ref, _facts_for(ref, record, gt, quantize=False), COE, gt, SHARES)
    # identical inputs at full precision: the same number (the desk rounds its output to the cent)
    assert exact["per_share_iv"] == round(ref["value"], 2)
    # the facts as the DEFAULTS block prints them: within a cent
    printed = _desk_default_base(ref, _facts_for(ref, record, gt, quantize=True), COE, gt, SHARES)
    assert abs(printed["per_share_iv"] - ref["value"]) <= 0.01 + 1e-9, (printed["per_share_iv"], ref["value"])
    if record_kw.get("nwc_intensity") is not None:
        assert "working_capital_deducted" in exact["stamps"]


def _synthetic_pack(monkeypatch, untagged=(), drop_goodwill=False, debt_tag=None, separate_borrowings=False,
                    op_margins=None, enrich_override=None, no_marker=False, pilot_arm=None):
    """build_pack("GEV") on the synthetic twelve-year history and estimates above (no network, clock frozen)."""
    import capability_test as cap
    import rs2_data
    from datetime import datetime as _real

    class _Frozen(_real):
        @classmethod
        def now(cls, tz=None):
            return _real(2026, 9, 27, 12, 0, 0)
    for mod in (cap, rs2_data):
        monkeypatch.setattr(mod, "datetime", _Frozen, raising=False)
    monkeypatch.setattr(cap.company_news, "fetch", lambda company, t: {"date": "2026-09-27", "rows": [],
                                                                       "unresponsive_engines": [], "errors": ["s"]})
    monkeypatch.setattr(cap.sec_guidance, "latest_earnings_release", lambda *a, **k: None)
    monkeypatch.setattr(cap.world_news, "digest", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "industry_taxonomy", None)
    # the corpus-wide base rates are measured from the whole screener history; a small table stands in
    row = {"n": 100, "p50": 5.0, "p90": 15.0, "share_ge_10": 20.0, "share_ge_20": 5.0, "share_ge_30": 1.0}
    monkeypatch.setattr(cap.base_rates, "base_rate_table", lambda *a, **k: ("$1-10B", {5: dict(row), 10: dict(row)}))
    monkeypatch.setattr(cap.growth_persistence, "persistence_for_growth", lambda *a, **k: (None, None))

    hist = _cycle_history(op_margins)
    hist[2025] = dict(hist[2025], revenue=10.0 * B, net_income=1.2 * B, da=0.5 * B, capex=0.6 * B,
                      shares_diluted=500e6, ocf=1.5 * B, sbc=0.1 * B,
                      operating_income=10.0 * B * (op_margins or {}).get(2025, 0.12 * 1.4) - 0.05 * B)
    for y in range(2014, 2025):
        hist[y] = dict(hist[y], da=0.5 * B, capex=0.6 * B, shares_diluted=500e6)
    if drop_goodwill:
        for y in hist:
            hist[y] = dict(hist[y], goodwill=None)
    if separate_borrowings:                      # short-term borrowings that differ from debt_current (2% of revenue)
        for y in hist:
            hist[y] = dict(hist[y], short_term_borrowings_separate=hist[y]["revenue"] * 0.01)
    prov = {"untagged_fields": {} if no_marker else {"GEV": list(untagged)}}      # no_marker: the extractor never processed GEV
    if debt_tag is not None:                     # brief A's provenance: the tag debt_current resolved from
        prov.update({"_tags": [debt_tag], "runs": {"GEV": {"debt_current": [[2010, 0, "p"]]}}})
    doc = {"tickers": {"GEV": {str(y): r for y, r in hist.items()}}, "provenance": prov}
    enrich = {"_ticker": "GEV", "_fetched_at": "2026-09-26T12:00:00", "estimates": EST}
    if enrich_override is not None:
        enrich = enrich_override
    orig = rs2_data.load_json

    def load(path):
        name = str(path)
        if name.endswith("fundamentals_history.json"):
            return doc
        if name.endswith("GEV.json") and "enrich" in name:
            return enrich
        return orig(path)
    monkeypatch.setattr(rs2_data, "load_json", load)
    return cap.build_pack("GEV", include_research=False, pilot_arm=pilot_arm)


def test_the_pack_builds_the_record_the_facts_and_the_lines_and_the_desk_follows_them(screener_data_stub, monkeypatch):
    """The synthetic history, estimates and the pack's own build_pack: the facts that come out (record, working
    capital, terminal growth default, long run) round-trip through the DEFAULTS block and drive the desk to the pack's
    CONSENSUS-IMPLIED VALUE."""
    pack = _synthetic_pack(monkeypatch)
    f = pack.facts
    assert pack_facts.parity(f, pack_facts.from_text(str(pack))) == []
    lr = f["long_run"]
    # the record came from the twelve rows above: a cycle, a median margin, working capital, a revenue trend
    assert lr["cycle"] is True and lr["cycle_years"] == [2016, 2020] and lr["cycle_year"] == 2020
    assert lr["m_tc"] is not None and lr["r_years"] == [2018, 2025, 8]
    assert f["terminal_ronic"] is not None and lr["terminal_g_basis"] == "revenue_trend"
    text = str(pack)
    assert "TERMINAL-GROWTH DEFAULT for this name" in text and "from your own revenue trend FY2018-FY2025" in text
    assert "Default exit multiple" not in text
    civ_line = next((l for l in text.splitlines() if "CONSENSUS-IMPLIED VALUE" in l), None)
    assert f["reference_status"] == "used" and f["consensus_implied_value"] is not None, civ_line
    assert lr["e5"] is not None and lr["oe5"] is not None and f["working_capital"] is not None
    ref_line = next(l for l in text.splitlines() if "CONSENSUS-IMPLIED VALUE (reference" in l)
    assert "from year 6 growth is paid for at the return on new investment your record supports: " in ref_line
    assert "working capital deducted in years 1-5" in ref_line
    lv = f["levels"]
    g35 = cr._years35(f["next_fy_revenue_growth"], 0.05)
    base = f["owner_earnings_default_b"]
    ctx = {"price": 300.0, "shares_default_b": f["shares_default"] / B, "coe_anchor": f["coe_anchor"],
           "terminal_g_default": f["terminal_g_default"], "terminal_g_anchor": f["terminal_g_anchor"],
           "owner_earnings_default_b": base, "levels": lv, "terminal_ronic": f["terminal_ronic"], "long_run": lr,
           "working_capital": f["working_capital"], "cash_basis_b": f["cash_basis_b"]}
    # the Base as the DEFAULTS describe it: the default base, years 1-2 that reach the levels, years 3-5 from
    # next-FY revenue growth (the desk holds years 1-2 at the levels whatever base is given)
    g1, g2 = lv["year1"] / base - 1, lv["year2"] / lv["year1"] - 1
    sc = lambda name, prob: {"name": name, "prob": prob, "base_cf": base, "explicit_growth": [g1, g2] + g35,
                             "wacc": f["coe_anchor"]}
    call = {"scenarios": [sc("Base", 0.5), sc("Bull", 0.25), sc("Bear", 0.25)], "terminal_g": f["terminal_g_default"],
            "fade_years": 5, "sbc_treatment": "deducted_in_cf", "cash_flow_life": "perpetual",
            "cash_flow_life_reason": "test", "bull_below_price_reason": "test", "bear_above_price_reason": "test",
            "base_cf_reason": "test",
            # revision 24 step 2a: the reference's own long-run margin (the DEFAULTS long_run's m_long; m5 where the rule held the margin)
            "long_run_margin": lr["m_long"] if lr.get("m_long") is not None else (lr.get("m5") if lr.get("m5") is not None else 0.10)}
    out = fmt.execute_financial_model(call, ctx)
    assert "error" not in out, out.get("error")
    base_dcf = out["scenario_dcfs"][0]["dcf"]
    assert "working_capital_deducted" in base_dcf["stamps"] and base_dcf["valued_at"].endswith("rolled forward")
    # the model's inputs are printed at three decimals of $B and 0.1% of growth, so this is a consistency check
    # of the chain (record -> facts -> DEFAULTS -> desk), not the to-the-cent identity the test above pins
    assert abs(base_dcf["per_share_iv"] / f["consensus_implied_value"] - 1) < 0.02, (base_dcf["per_share_iv"],
                                                                                    f["consensus_implied_value"])


def test_the_untagged_marker_decides_whether_a_missing_goodwill_series_is_none_held_or_partial(screener_data_stub, monkeypatch):
    """Brief A's provenance marker (untagged_fields): goodwill absent in every year and listed there counts as 0 and is
    not stamped; absent and not listed is a partial year (F3): only the intangibles that are known are subtracted, the
    record stays, and the years are stamped tangible_equity_partial."""
    untagged = _synthetic_pack(monkeypatch, untagged=["goodwill"], drop_goodwill=True).facts
    assert untagged["long_run"]["r_years"] == [2018, 2025, 8] and untagged["long_run"]["r_tc"] is not None
    assert not any(st.startswith("tangible_equity_partial") for st in untagged["long_run"]["stamps"])
    gap = _synthetic_pack(monkeypatch, drop_goodwill=True).facts
    assert gap["long_run"]["r_years"] == [2018, 2025, 8] and gap["long_run"]["r_tc"] == untagged["long_run"]["r_tc"]
    # revision 17 (brief C7): the DEFAULTS stamp lists the eight window years (2018-2025) as a range; the facts keep the full list
    assert "tangible_equity_partial:2018-2025" in gap["long_run"]["stamps"]
    assert "tangible_equity_partial:2014/2015/2016/2017/2018/2019/2020/2021/2022/2023/2024/2025" in gap["long_run"]["stamps_full"]
    assert "record_not_available" not in gap["long_run"]["stamps"]
    assert gap["terminal_ronic"] == untagged["terminal_ronic"]           # the record is the same: nothing is lost to the gap


def test_the_packs_long_run_earnings_are_x_of_the_base_year(screener_data_stub, monkeypatch):
    """Brief B2 F1 through build_pack: the synthetic base year holds net income 1.2B and acquired-intangible
    amortization 0.05B at a 25% tax rate, so X is 1.2375B; a filer that never tags the amortization has X = net income."""
    tagged = _synthetic_pack(monkeypatch).facts["long_run"]
    untagged = _synthetic_pack(monkeypatch, untagged=["amortization_intangibles"]).facts["long_run"]
    assert tagged["e5"] / untagged["e5"] == pytest.approx((1.2 + 0.05 * 0.75) / 1.2, rel=1e-5)
    assert not any(st.startswith("amortization_gap") for st in tagged["stamps"])


def test_the_packs_working_capital_subtracts_short_term_debt_once_unless_the_tag_is_a_current_portion(screener_data_stub, monkeypatch):
    """Brief B2 F4 through build_pack: separate short-term borrowings (1% of revenue) that differ from debt_current (2%)
    are added to the debt only when provenance says debt_current is a current-portion-of-long-term-debt tag."""
    none = _synthetic_pack(monkeypatch, separate_borrowings=True).facts["long_run"]["nwc_intensity"]
    short = _synthetic_pack(monkeypatch, separate_borrowings=True, debt_tag="ShortTermBorrowings").facts["long_run"]["nwc_intensity"]
    added = _synthetic_pack(monkeypatch, separate_borrowings=True, debt_tag="LongTermDebtCurrent").facts["long_run"]["nwc_intensity"]
    assert none == short                                                  # no provenance, or a short-term borrowings tag: debt_current alone
    assert added - none == pytest.approx(0.01, abs=2e-6)                  # the current-portion tag adds the borrowings: NWC / revenue up 1%


def test_the_three_new_history_fields_are_reviewed_so_the_pack_does_not_warn_about_them():
    """Brief A adds goodwill, intangibles_ex_goodwill and amortization_intangibles to every history row; the pack reads
    them through the record, so its UNREVIEWED FIELDS sensor must not announce them (an unknown field still is)."""
    import capability_test as cap
    hist = {"2025": {"revenue": 1.0, "goodwill": 1.0, "intangibles_ex_goodwill": 2.0, "amortization_intangibles": 3.0,
                     "a_field_nobody_reviewed": 4.0}}
    assert cap._unreviewed_history_fields(hist) == ["a_field_nobody_reviewed"]


def test_the_desk_equals_the_reference_on_random_inputs_to_the_cent():
    """A seeded sweep: random estimates, records (unlimited or finite returns, cycles, working capital of either sign),
    rates, terminal growth and stubs, on both reference methods. The desk, given the reference's own flows (at full
    precision), returns the reference's per-share value to the cent every time."""
    import random
    rng = random.Random(20260930)
    checked = 0
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
        est = {"0y": {"revenue": {"avg": rev0 * (1 + rng.uniform(-0.05, 0.15)), "analysts": 12, "growth": 0.05,
                                  "year_ago": rev0},
                      "eps": {"avg": eps0 * (1 + c1), "analysts": 12, "growth": c1 if growth_ok else 3.0,
                              "year_ago": eps0}},
               "+1y": {"revenue": {"avg": rev0 * (1 + rng.uniform(0.0, 0.3)), "analysts": 12,
                                   "growth": rng.uniform(-0.05, 0.25)},
                       "eps": {"avg": eps0 * (1 + c1) * (1 + c2), "analysts": 12, "growth": c2}}}
        record = {"R_tc": rng.choice([INF, rng.uniform(0.02, 0.4), None]),
                  "nwc_intensity": rng.choice([None, rng.uniform(-0.15, 0.4)]), "stamps": []}
        record["r_blend"] = record["R_tc"]
        # the margin rule's inputs: a record with an operating-margin median (a profit, a loss or none), the base year's
        # operating margin and, sometimes, its earnings margin
        record.update(om_tc=rng.choice([None, rng.uniform(-0.03, 0.3)]), om_L=rng.uniform(0.02, 0.3),
                      om_shape=rng.choice(["swing", "trend"]), x_L=rng.choice([None, rng.uniform(0.02, 0.25)]),
                      tax_L=rng.uniform(0.0, 0.35))
        if record["om_tc"] is None:
            record["om_L"] = None
        record["ronic_t"] = (INF if record["R_tc"] == INF else coe if record["R_tc"] is None
                             else coe + rng.random() * max(0.0, record["R_tc"] - coe))
        stub = rng.choice([None, rng.uniform(0.5, 14.0)])
        da = rng.uniform(0.2, 1.2) * oe0 if not growth_ok else None
        ref = cr.build(oe0, est, coe, gt, shares, rng.uniform(0.02, 0.1), record=record, base_ni=ni0, base_revenue=rev0,
                       stub_months=stub, da=da, capex=(da * rng.uniform(0.5, 1.5) if da is not None else None))
        if ref["value"] is None or ref["levels"] is None:
            continue
        lr = ref["long_run"]
        facts = {"terminal_ronic": ref["terminal_ronic"],
                 "long_run": {"e5": lr["e5"] / B, "oe5": lr["oe5"] / B, "m5": lr["m5"], "margin_ratio": ref["margin_ratio"],
                              "r_blend": record["r_blend"], "r_tc": record["R_tc"], "stub_months": stub},
                 "working_capital": [x / B for x in ref["wc"]] if ref["wc"] else None}
        lv = ref["levels"]
        if ref["base_cf"] is not None:
            base, path = ref["base_cf"] / B, ref["path"]
        else:
            base = oe0 / B
            path = [lv[0] / B / base - 1, lv[1] / lv[0] - 1] + ref["path"][2:]
        sc = lambda name, prob, w: {"name": name, "prob": prob, "base_cf": base, "explicit_growth": list(path), "wacc": w}
        call = {"scenarios": [sc("Base", 0.4, coe), sc("Bull", 0.3, coe - 0.0005), sc("Bear", 0.3, coe + 0.0005)],
                "terminal_g": gt, "fade_years": 5, "sbc_treatment": "deducted_in_cf", "cash_flow_life": "perpetual",
                "cash_flow_life_reason": "t", "base_cf_reason": "t", "scenario_deviation_reason": "t",
                "bull_below_price_reason": "t", "bear_above_price_reason": "t", "terminal_reason": "t",
                "coe_adjustment_reason": "t", "long_run_margin": ref_long_run_margin(ref)}
        ctx = {"price": 1e-3, "shares_default_b": shares / B, "coe_anchor": coe, "terminal_g_default": gt,
               "owner_earnings_default_b": base, "levels": {"year1": lv[0] / B, "year2": lv[1] / B},
               "terminal_ronic": facts["terminal_ronic"], "long_run": facts["long_run"],
               "working_capital": facts["working_capital"], "cash_basis_b": None}
        out = fmt.execute_financial_model(call, ctx)
        if "error" in out:
            # a stand-in Bull/Bear this sweep builds can break the scenario order or a price check; the Base is what is
            # under test, so value it alone through the same function
            out = {"scenario_dcfs": [{"dcf": fmt.unbundled_dcf(
                base_cf=base, explicit_growth=path, wacc=coe, terminal_g=gt, shares_diluted=shares / B, fade_years=5,
                sbc_treatment="deducted_in_cf", terminal_ronic=facts["terminal_ronic"], long_run=facts["long_run"],
                working_capital=facts["working_capital"], long_run_margin=ref_long_run_margin(ref))}]}
        desk = out["scenario_dcfs"][0]["dcf"]["per_share_iv"]
        assert abs(desk - ref["value"]) <= 0.0051, (case, desk, ref["value"], record, stub)
        checked += 1
    assert checked >= 200
