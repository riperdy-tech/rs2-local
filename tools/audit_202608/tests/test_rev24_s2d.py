"""Revision 24 step 2d (BRIEF_R24_S2d_ronic_diagnostics.md; PHASE_4_AMENDMENTS.md "Cross-check 19: replies and the coordinator's rulings" 1, 6
and 9, and "Revision 24 step 2c: built and audited"):

1. RONIC as stated (ruling 1): consensus_reference.long_run_value takes the start and terminal returns as given (no max(r, .)); a terminal return
   below r is stamped terminal_ronic_below_rate; at or below 0 the desk refuses the call by name; the start is the record's r_tc as measured when
   above 0 (ronic_start_below_rate below r), else the terminal return (ronic_start_from_terminal). Tests at e5 1.0, r 9%, terminal g 3%, fade 5,
   g5 3% and 10%, with hand-computed values.
2. Diagnostics, never gates (ruling 6): terminal_value_share and terminal_reinvestment_rate in the desk's implied block and on the sample record;
   earnings_ratio_10y stays reported and never rejects.
3. Census desk tests (ruling 9) on saved facts: Kohl's (a negative revenue trend: a positive terminal_g needs an outlier citation) and Heritage
   (a peak base: report only).
5. Working capital normalized at the base (the step-2c audit): revenue_t = consensus revenue_t x (oe_t / oe_0) / (ow_t / ow_0).
6. The tax label on the POPULATION RANGES supporting line.

Fixtures (fixture_data/rev24/): the saved KSS and HRTG pack facts (step 2a); KSS_population_ranges.json and HRTG_population_ranges.json, built for this
step by rs2's own population_ranges.ranges_for at 2026-10-06 on the screener-publish fundamentals_history rows cut at the saved packs' base fiscal
years, SIC from priors_inputs sic_by_cik.json, tables priors_v5 (their `fixture_provenance` says so); census_base_year.json, the base fiscal year's
filed earnings margin x_L and revenue rev_L (step 2b's unprinted long_run members, which these revision-21/22-era sidecars predate) from
throughcycle_record.analyse on the same rows, whose m_tc, R_tc, om_L and g_rev equal the saved facts'; KSS_primary_p1.md, the opening of the saved KSS
pack's PRIMARY SOURCES and its item P1 verbatim (rs2-local ab_reports/consensus/KSS_20261006_084156/_pack.md).
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
import consensus_valuation as cv  # noqa: E402
import fiduciary_gate as fg  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import population_ranges as pr  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN  # noqa: E402
from test_rev24_s2b_ranges import fixture_tables, rec  # noqa: E402
from test_rev24_s2c_desk import _arm  # noqa: E402
from test_rev24_stage_a_pack import _saved  # noqa: E402

INF = math.inf
REV24 = HERE / "fixture_data" / "rev24"

# =============================================================================================================================================
# 1. RONIC as stated (cross-check 19, ruling 1)
# =============================================================================================================================================
# e5 1.0, r 9%, terminal g 3%, fade 5, the same RONIC R from year 6 on (start and terminal).
# g5 = 3%: growth is 3% every year, so every flow and the terminal carry the factor (1 - 0.03 / R) on the unlimited case:
#   unlimited: sum_{t=6..10} 1.03^(t-5) / 1.09^t + 1.03^6 / 0.06 / 1.09^10 = 11.157155
#   R 4.5% (0.5r):   x (1 - 0.6667) = x 0.3333 =  3.719052
#   R 6.75% (0.75r): x (1 - 0.4444) = x 0.5556 =  6.198420
#   R 9% (r):        x (1 - 0.3333) = x 0.6667 =  7.438104   (cross-check 19's 7.4381: the old floor priced 4.5% and 6.75% at this value)
#   R 13.5% (1.5r):  x (1 - 0.2222) = x 0.7778 =  8.677788
# g5 = 10% (growth fading 10% -> 3% over years 6-10): 3.026536, 6.237182, 7.842505 (cross-check 19's 7.8425 at r), 9.447829, 12.658475.
# The terminal value at 4.5% is (1 - 0.03 / 0.045) / (1 - 0.03 / 0.09) = 0.3333 / 0.6667 = 0.5 of that at 9%: g5 3%: 6.633624 against 13.267248.
R9, GT, F = 0.09, 0.03, 5
GRID = (0.5 * R9, 0.75 * R9, R9, 1.5 * R9, INF)
HAND = {0.03: (3.719052, 6.198420, 7.438104, 8.677788, 11.157155), 0.10: (3.026536, 6.237182, 7.842505, 9.447829, 12.658475)}


def lrv(g5, ronic, gt=GT):
    return cr.long_run_value(1.0, g5, gt, R9, ronic, ronic, None, F)


@pytest.mark.parametrize("g5", [0.03, 0.10])
def test_the_value_rises_strictly_with_the_terminal_ronic_below_and_above_r_up_to_unlimited(g5):
    vals = [lrv(g5, x)["value"] for x in GRID]
    assert vals == pytest.approx(HAND[g5], abs=5e-7)
    assert all(b > a for a, b in zip(vals, vals[1:]))
    # the old floor: 4.5% and 6.75% were priced exactly as 9% - no longer
    assert vals[0] < vals[2] and vals[1] < vals[2]


def test_the_terminal_value_at_half_r_is_half_that_at_r():
    for g5 in (0.03, 0.10):
        lo, at = lrv(g5, 0.045), lrv(g5, 0.09)
        assert lo["e_terminal"] == pytest.approx(at["e_terminal"], rel=1e-15)        # the earnings do not depend on RONIC
        assert lo["tv"] == pytest.approx((1 / 3) / (2 / 3) * at["tv"], rel=1e-12)
    assert lrv(0.03, 0.045)["tv"] == pytest.approx(6.633624, abs=5e-7) and lrv(0.03, 0.09)["tv"] == pytest.approx(13.267248, abs=5e-7)


def test_at_zero_growth_every_ronic_gives_the_same_value():
    """g5 = terminal g = 0: no growth to pay for; value = 1 / (0.09 x 1.09^5) = 7.221460 whatever RONIC."""
    vals = [cr.long_run_value(1.0, 0.0, 0.0, R9, x, x, None, F)["value"] for x in GRID]
    assert vals == pytest.approx([1 / (0.09 * 1.09 ** 5)] * 5, rel=1e-12) and vals[0] == pytest.approx(7.221460, abs=5e-7)


@pytest.mark.parametrize("bad", [0.0, -0.05])
def test_a_ronic_at_or_below_zero_is_refused(bad):
    with pytest.raises(ValueError):
        cr.long_run_value(1.0, 0.03, GT, R9, 0.12, bad, None, F)
    with pytest.raises(ValueError):
        cr.long_run_returns(0.12, bad, R9)
    # the desk: unbundled_dcf refuses it by name, and execute_financial_model names it in `missing`
    d = fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.03] * 5, wacc=R9, terminal_g=GT, shares_diluted=1.0, fade_years=F,
                          sbc_treatment="deducted_in_cf", terminal_ronic=bad)
    assert d["validation_error"] is True and d["missing"][0].startswith("terminal_ronic (a positive number")
    p = dict(_ALL_REASONS_GIVEN, cash_flow_life="perpetual", cash_flow_life_reason="x", fade_years=F, terminal_g=GT, sbc_treatment="deducted_in_cf",
             long_run_margin=0.1, terminal_ronic=bad,
             scenarios=[{"name": n, "prob": pb, "base_cf": 1.0, "explicit_growth": [0.03] * 5, "wacc": R9}
                        for n, pb in (("Base", 0.5), ("Bull", 0.25), ("Bear", 0.25))])
    res = fmt.execute_financial_model(p, {"price": 10.0, "shares_default_b": 1.0, "coe_anchor": R9, "owner_earnings_default_b": 1.0})
    assert res["validation_error"] is True and any(m.startswith("terminal_ronic (a positive number") for m in res["missing"])
    # a scenario's own
    p2 = copy.deepcopy(p)
    p2["terminal_ronic"] = 0.12
    p2["scenarios"][2]["terminal_ronic"] = bad
    res = fmt.execute_financial_model(p2, {"price": 10.0, "shares_default_b": 1.0, "coe_anchor": R9, "owner_earnings_default_b": 1.0})
    assert any(m.startswith("terminal_ronic in Bear (a positive number") for m in res["missing"])


def test_the_start_return_and_the_stamps():
    assert cr.long_run_returns(0.20, 0.12, R9) == (0.20, [])
    assert cr.long_run_returns(0.05, 0.12, R9) == (0.05, ["ronic_start_below_rate"])
    assert cr.long_run_returns(INF, 0.05, R9) == (INF, ["terminal_ronic_below_rate"])
    for missing in (None, 0.0, -0.04, -INF, float("nan")):
        assert cr.long_run_returns(missing, 0.06, R9) == (0.06, ["terminal_ronic_below_rate", "ronic_start_from_terminal"])
    assert cr.long_run_returns(None, INF, R9) == (INF, ["ronic_start_from_terminal"])
    # the desk carries them on its output; the reference's go to the facts' stamps_full (consensus_reference.RONIC_STAMPS)
    d = fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.03] * 5, wacc=R9, terminal_g=GT, shares_diluted=1.0, fade_years=F,
                          sbc_treatment="deducted_in_cf", terminal_ronic=0.045, long_run={"r_tc": 0.05})
    assert [s for s in d["stamps"] if s in cr.RONIC_STAMPS] == ["terminal_ronic_below_rate", "ronic_start_below_rate"]
    assert d["ronic_start"] == 0.05 and d["terminal_ronic"] == 0.045


def test_the_price_implied_terminal_ronic_reaches_below_the_discount_rate():
    """The search runs from terminal_g (3%) to unlimited: a price below the value at RONIC = r, which the floor made unreachable, now has a root
    below r, and substituting it back gives the price."""
    base = dict(cf=1.0, growth=[0.05] * 5, fade=5, wacc=R9, tg=GT, shares=1.0, sbc="deducted_in_cf", sbc_dil=None, frame="equity", net_debt=0.0,
                rate_type=None, annuity=0.0, annuity_cap=None, ronic=0.12, wc=None, excess=None, long_run=None, finite=None)

    def v(ronic):
        return fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.05] * 5, wacc=R9, terminal_g=GT, shares_diluted=1.0, fade_years=5,
                                 sbc_treatment="deducted_in_cf", terminal_ronic=ronic)["per_share_iv_raw"]
    base["raw"] = v(0.12)
    price = (v(0.06) + v(0.07)) / 2                                  # between the values at 6% and 7%, below the value at r
    assert price < v(R9)
    blk = fmt.price_implied(base, price, rf_eff=0.04, gdp_trend=0.04)["terminal_ronic"]
    assert blk["bound"]["low"] == GT and blk["bound"]["high"] == "unlimited"
    assert blk["reachable"] and 0.06 < blk["value"] < 0.07
    assert v(blk["value"]) == pytest.approx(price, abs=1e-6)


# =============================================================================================================================================
# 2. Diagnostics, never gates (ruling 6)
# =============================================================================================================================================
# Synthetic S (test_rev24_desk_arithmetic): base_cf 1.0, no growth, r 10%, terminal g 3%, a one-year fade, no record.
#   unlimited: PV(years 1-5) 3.790787, flow6 1.03 (PV 0.581406), TV 1.03 x 1.03 / 0.07 = 15.155714 (PV / 1.1^6 = 8.555006); EV 12.927201;
#              terminal_value_share = 8.555006 / 12.927201 = 0.661783; reinvestment 0 (unlimited)
#   RONIC 15%: flow6 1.03 x 0.8 = 0.824 (PV 0.465127), TV 15.155714 x 0.8 = 12.124571 (PV 6.844004); EV 11.099918;
#              terminal_value_share = 6.844004 / 11.099918 = 0.616582; reinvestment 0.03 / 0.15 = 0.2

def _s(**kw):
    a = dict(base_cf=1.0, explicit_growth=[0.0] * 5, wacc=0.10, terminal_g=0.03, shares_diluted=1.0, fade_years=1, sbc_treatment="deducted_in_cf",
             terminal_ronic=INF)
    a.update(kw)
    return fmt.unbundled_dcf(**a)


def test_the_terminal_value_share_and_the_reinvestment_rate_by_hand():
    imp = _s()["implied"]
    assert imp["terminal_value_share"] == pytest.approx(0.661783, abs=5e-7) and imp["terminal_reinvestment_rate"] == 0.0
    imp = _s(terminal_ronic=0.15)["implied"]
    assert imp["terminal_value_share"] == pytest.approx(0.616582, abs=5e-7) and imp["terminal_reinvestment_rate"] == pytest.approx(0.2, rel=1e-15)
    # the share is the terminal value's present value over the enterprise value the desk reports
    d = _s(terminal_ronic=0.15)
    assert d["implied"]["terminal_value_share"] == pytest.approx(d["terminal_value_pv"] / d["enterprise_value"], abs=1e-3)
    # below g: the reinvestment exceeds the earnings (a rate above 1) - reported, never refused or clamped
    assert _s(terminal_ronic=0.02)["implied"]["terminal_reinvestment_rate"] == pytest.approx(1.5, rel=1e-15)


def test_the_diagnostics_ride_on_the_sample_record_and_never_gate():
    from test_rev24_s2b_gate import _fill
    filled, _ = _fill(0.12)
    assert filled["plausibility_gate"]["verdict"] == "pass"
    # the Base's own diagnostics (test_rev24_s2b_gate's answer call: terminal_g 3%, terminal_ronic 20%)
    assert filled["terminal_reinvestment_rate"] == pytest.approx(0.03 / 0.2, rel=1e-12)
    assert 0 < filled["terminal_value_share"] < 1
    # neither is a gate metric: the gate's metrics and reasons never name them
    assert not {"terminal_value_share", "terminal_reinvestment_rate"} & set(fg.PLAUSIBILITY_METRICS)
    assert cv.S12_SUMMARY_KEYS[-2:] == ("terminal_value_share", "terminal_reinvestment_rate")


def test_earnings_ratio_10y_is_reported_and_never_a_rejection_reason():
    """Year-10 earnings over base earnings has no cohort (ruling 6): an extreme ratio is annotated plausibility_not_measured and the verdict stands
    on the other metrics. The Base below grows 30% a year for five years (ratio far above any history) with every gated metric inside its range."""
    from test_rev24_s2b_gate import _ranges, _rationale
    lr = {"e5": 100.0, "oe5": 100.0, "m5": 0.10, "r_tc": INF, "x_L": 0.09, "rev_L": 600.0}
    d = fmt.unbundled_dcf(base_cf=100.0 / 1.05 ** 5, explicit_growth=[0.05] * 5, wacc=0.10, terminal_g=0.03, shares_diluted=1.0, fade_years=5,
                          sbc_treatment="deducted_in_cf", terminal_ronic=0.2, long_run=dict(lr, x_L=0.0005), long_run_margin=0.12)
    assert d["implied"]["earnings_ratio_10y"] > 100
    g = fg.plausibility_gate(d, _ranges(), _rationale(), "", growth_anchor=0.0375,
                             classifications={"margin_persistence": "structural", "cycle_position": "mid", "growth_trajectory": "steady"})
    assert g["metrics"]["earnings_ratio_10y"]["value"] == d["implied"]["earnings_ratio_10y"]
    assert g["metrics"]["earnings_ratio_10y"]["status"] == "not_measured" and "plausibility_not_measured:earnings_ratio_10y" in g["annotations"]
    assert not any("earnings_ratio" in r for r in g["reasons"])


# =============================================================================================================================================
# 3. Census desk tests on saved facts (ruling 9)
# =============================================================================================================================================

def _census(t):
    """The saved pack's facts as the iii arm's desk sees them, with the base fiscal year's x_L and rev_L (census_base_year.json), and its ranges."""
    saved, _ = _saved(t)
    f = _arm(saved, "iii_p50")
    br = json.loads((REV24 / "census_base_year.json").read_text(encoding="utf-8"))[t]
    f["long_run"] = dict(f["long_run"], x_L=br["x_L"], rev_L=br["rev_L"])
    ranges = json.loads((REV24 / f"{t}_population_ranges.json").read_text(encoding="utf-8"))
    return saved, f, ranges


def _call(f, tg, tr, lrm):
    return dict(_ALL_REASONS_GIVEN, cash_flow_life="perpetual", cash_flow_life_reason="x", sbc_treatment="deducted_in_cf", fade_years=5,
                terminal_g=tg, terminal_ronic=tr, long_run_margin=lrm,
                scenarios=[{"name": n, "prob": p, "base_cf": f["reference_base_b"], "explicit_growth": [x + d for x in f["reference_path"]],
                            "wacc": f["coe_anchor"]} for n, p, d in (("Base", 0.5, 0.0), ("Bull", 0.25, 0.03), ("Bear", 0.25, -0.03))])


def _base(t, f, saved, tg, tr, lrm):
    res = fmt.execute_financial_model(_call(f, tg, tr, lrm), cv.build_desk_context(f, saved["price_implied_price"], t, t, "2026-10-06"))
    assert "error" not in res, res.get("error")
    return next(s["dcf"] for s in res["scenario_dcfs"] if s["name"] == "Base")


def _rationale(cite=None):
    r = {k: {"value": None, "within_p10_p90": True, "rationale": "tied to the record", "citation": None}
         for k in ("long_run_margin", "growth_years_3_5", "fade_years", "terminal_g", "terminal_ronic")}
    if cite:
        r["terminal_g"].update(within_p10_p90=False, citation=cite)
    return r


KSS_QUOTE = ("Our second quarter results reflect the ongoing progress against our initiatives, leading to another improvement in our comparable "
             "sales trend.")
KSS_CLASSES = {"margin_persistence": "partly_structural", "cycle_position": "mid", "growth_trajectory": "decelerating"}


def test_kohls_negative_trend_makes_a_positive_terminal_g_an_outlier_rejected_without_a_citation():
    """KSS: the record's 8-year ln-revenue slope -3.20% (KSS_population_ranges.json revenue_trend8) - a shrinking business, so terminal_g 2.4%, below
    the 3.75% anchor, is an outlier (cross-check 19 ruling C). The call is otherwise in range: long_run_margin 2% (earnings P5 -19.9% .. P95 11.3%),
    terminal_ronic 10.08% (the cost of equity; ROIC P5 -13.4% .. P95 29.1%), the revenue CAGR to year 10 -0.46% (P5 -20.7% .. P95 54.3%).
    Without a citation: rejected implausible_unsupported_terminal_g. With one that resolves (PRIMARY P1, the CEO's sentence on the comparable-sales
    trend, found verbatim): it passes, annotated implausible_supported_terminal_g. The code checks the quote's existence and attachment only;
    whether it is causal for the level (the registered rubric: here "related") is the coordinator's reading in measure (d) (ruling 5)."""
    saved, f, ranges = _census("KSS")
    assert ranges["revenue_trend8"] == pytest.approx(-0.032028, abs=5e-7) and f["terminal_g_anchor"] == 0.0375
    b = _base("KSS", f, saved, 0.024, 0.1008, 0.02)
    assert "m5_from_base_year" in b["stamps"] and "ronic_start_below_rate" in b["stamps"]      # r_tc 5.63% < 10.08%: the start as measured
    pack = (REV24 / "KSS_primary_p1.md").read_text(encoding="utf-8")
    g = fg.plausibility_gate(b, ranges, _rationale(), pack, [], "Kohl's Corporation", "KSS", growth_anchor=f["terminal_g_anchor"],
                             classifications=KSS_CLASSES)
    assert g["verdict"] == "reject" and g["reasons"] == ["implausible_unsupported_terminal_g"]
    assert g["metrics"]["terminal_g"]["shrinking"] == ["the record's 8-year revenue trend -0.0320 is below 0"]
    assert {m: g["metrics"][m]["status"] for m in ("long_run_margin", "revenue_cagr_10y", "terminal_ronic")} == {
        "long_run_margin": "within", "revenue_cagr_10y": "within", "terminal_ronic": "within"}
    cite = {"source": "PRIMARY P1", "date": "2026-08-26", "quote": KSS_QUOTE}
    g = fg.plausibility_gate(b, ranges, _rationale(cite), pack, [], "Kohl's Corporation", "KSS", growth_anchor=f["terminal_g_anchor"],
                             classifications=KSS_CLASSES)
    assert g["verdict"] == "pass" and "implausible_supported_terminal_g" in g["annotations"] and g["metrics"]["terminal_g"]["status"] == "supported"
    # a quote not in the pack does not resolve
    bad = dict(cite, quote="Kohl's expects sales to grow faster than the economy for decades.")
    assert fg.plausibility_gate(b, ranges, _rationale(bad), pack, [], "Kohl's Corporation", "KSS", growth_anchor=f["terminal_g_anchor"],
                                classifications=KSS_CLASSES)["verdict"] == "reject"
    # 0 is an ordinary choice for a shrinking business
    b0 = _base("KSS", f, saved, 0.0, 0.1008, 0.02)
    assert fg.plausibility_gate(b0, ranges, _rationale(), pack, [], "Kohl's Corporation", "KSS", growth_anchor=f["terminal_g_anchor"],
                                classifications=KSS_CLASSES)["verdict"] == "pass"


def test_heritage_peak_base_what_the_gate_and_the_diagnostics_say():
    """Report only, no new rule (ruling 9). HRTG (SIC 6331, financial): base-year earnings margin x_L 23.64% against the 8-year median m_tc 6.82% (a
    peak; operating margin 32.3% against 10.4%). A call at the consensus levels (the reference's base and path, terminal_g at the 3.75% anchor,
    terminal_ronic unlimited as the record's, the margin held at the consensus year-5 margin 18.47%):
      - the gate passes: the margin and the return are not measured for a financial company (no_population_cohort), the revenue CAGR to year 10
        3.87% is inside P5 -4.0% .. P95 22.0%, terminal_g is at the anchor; nothing reads the peak;
      - the diagnostics: year-10 earnings 0.2288 over base earnings 0.2003 ($B) = 1.142 (reported, no cohort); terminal value share 0.614;
        reinvestment 0 (unlimited); value $112.46.
    The same call with the long-run margin at the 8-year median 6.82%: ratio 0.422, share 0.412, $61.91 - and the gate passes too."""
    saved, f, ranges = _census("HRTG")
    lr = f["long_run"]
    assert lr["x_L"] == pytest.approx(0.236356, abs=5e-7) and lr["m_tc"] == pytest.approx(0.068195, abs=5e-7)
    cls = {"margin_persistence": "transient", "cycle_position": "peak", "growth_trajectory": "decelerating"}
    out = {}
    for lrm in (lr["m5"], lr["m_tc"]):
        b = _base("HRTG", f, saved, f["terminal_g_default"], INF, lrm)
        g = fg.plausibility_gate(b, ranges, _rationale(), "", [], "Heritage Insurance", "HRTG", growth_anchor=f["terminal_g_anchor"], classifications=cls)
        out[lrm] = (b, g)
        assert g["verdict"] == "pass" and g["reasons"] == []
        assert "no_population_cohort" in g["annotations"] and g["metrics"]["revenue_cagr_10y"]["status"] == "within"
        assert g["metrics"]["long_run_margin"]["status"] == "not_measured" and g["metrics"]["terminal_ronic"]["status"] == "not_measured"
        assert b["implied"]["terminal_reinvestment_rate"] == 0.0
    b, _ = out[lr["m5"]]
    assert b["per_share_iv"] == 112.46 and b["implied"]["earnings_ratio_10y"] == pytest.approx(1.1425, abs=5e-5)
    assert b["implied"]["revenue_cagr_10y"] == pytest.approx(0.038717, abs=5e-7) and b["implied"]["terminal_value_share"] == pytest.approx(0.6135, abs=5e-5)
    b, _ = out[lr["m_tc"]]
    assert b["per_share_iv"] == 61.91 and b["implied"]["earnings_ratio_10y"] == pytest.approx(0.4218, abs=5e-5)
    assert b["implied"]["terminal_value_share"] == pytest.approx(0.4115, abs=5e-5)


# =============================================================================================================================================
# 5. Working capital normalized at the base (the step-2c audit)
# =============================================================================================================================================
# The consensus: revenue 100 growing 10% a year (110, 121, 133.1, 146.41, 161.051), owner earnings grown from a base of 10 at 10% (11, 12.1, ...),
# intensity 20%. revenue_t = consensus_t x (oe_t / base_cf) / (ow_t / 10). The desk reports the deductions at 4 decimals.
WC = {"intensity": 0.2, "revenue": [100.0, 110.0, 121.0, 133.1, 146.41, 161.051], "owner_earnings": [11.0, 12.1, 13.31, 14.641, 16.1051],
      "base_owner_earnings": 10.0}


def _wc(base, growth, wc=WC):
    return fmt.unbundled_dcf(base_cf=base, explicit_growth=[growth] * 5, wacc=0.10, terminal_g=0.03, shares_diluted=1.0, fade_years=5,
                             sbc_treatment="deducted_in_cf", terminal_ronic=0.15, working_capital=wc)


def test_a_base_40_percent_below_the_consensus_on_the_consensus_growth_deducts_exactly_the_consensus_schedule():
    """Base 6 (40% below 10), growth 10%: oe_t / 6 = ow_t / 10 = 1.1^t, so revenue_t is the consensus revenue and the deduction 20% of 10, 11,
    12.1, 13.31, 14.641 = 2.0, 2.2, 2.42, 2.662, 2.9282 - the consensus schedule. (Step 2c read revenue_1 = 110 x 6.6 / 11 = 66, a fall of 34, and
    released 6.8 in year 1.)"""
    d = _wc(6.0, 0.10)
    assert d["working_capital_deducted"] == pytest.approx([2.0, 2.2, 2.42, 2.662, 2.9282], abs=1e-12)
    assert _wc(10.0, 0.10)["working_capital_deducted"] == pytest.approx(d["working_capital_deducted"], abs=1e-12)
    assert "working_capital_release" not in d["stamps"] and "working_capital_own_path" in d["stamps"]


def test_faster_growth_deducts_more_and_a_slower_path_releases_stamped():
    """Base 6 at 20%: revenue_t = 100 x 1.2^t = 120, 144, 172.8, 207.36, 248.832: deductions 4.0, 4.8, 5.76, 6.912, 8.2944. Base 6 at -5%: revenue
    100 x 0.95^t = 95, 90.25, 85.7375, 81.450625, 77.37809375: deductions -1.0, -0.95, -0.9025, -0.857375, -0.81450625 (a release, stamped)."""
    fast = _wc(6.0, 0.20)
    assert fast["working_capital_deducted"] == pytest.approx([4.0, 4.8, 5.76, 6.912, 8.2944], abs=1e-12)
    slow = _wc(6.0, -0.05)
    assert slow["working_capital_deducted"] == pytest.approx([-1.0, -0.95, -0.9025, -0.857375, -0.81450625], abs=5e-5)    # the desk prints 4 decimals
    assert "working_capital_release" in slow["stamps"] and "working_capital_release" not in fast["stamps"]
    assert sum(fast["working_capital_deducted"]) > sum(_wc(6.0, 0.10)["working_capital_deducted"]) > 0 > sum(slow["working_capital_deducted"])
    # the flows are the owner earnings less the deductions: year 1 at -5%, 6 x 0.95 + 1.0 = 6.7
    assert slow["projected_cfs"][0] == pytest.approx(6.0 * 0.95 + 1.0, abs=1e-4)


def test_the_own_path_needs_its_base_and_the_desk_reads_it_from_long_run_oe_base():
    no_base = {k: v for k, v in WC.items() if k != "base_owner_earnings"}
    assert _wc(6.0, 0.10, no_base)["validation_error"] is True
    p = dict(_ALL_REASONS_GIVEN, cash_flow_life="perpetual", cash_flow_life_reason="x", sbc_treatment="deducted_in_cf", fade_years=5, terminal_g=0.03,
             terminal_ronic=0.15, long_run_margin=0.10,
             scenarios=[{"name": n, "prob": pb, "base_cf": 6.0, "explicit_growth": [g] * 5, "wacc": 0.10}
                        for n, pb, g in (("Base", 0.5, 0.10), ("Bull", 0.25, 0.20), ("Bear", 0.25, -0.05))])
    lr = {"nwc_intensity": 0.2, "revenue_path": WC["revenue"], "oe_path": WC["owner_earnings"], "oe_base": 10.0}
    ctx = {"price": 100.0, "shares_default_b": 1.0, "coe_anchor": 0.10, "owner_earnings_default_b": 6.0, "long_run": lr, "long_run_defaults_withheld": True}
    res = fmt.execute_financial_model(copy.deepcopy(p), ctx)
    got = {s["name"]: s["dcf"]["working_capital_deducted"] for s in res["scenario_dcfs"]}
    assert got["Base"] == pytest.approx([2.0, 2.2, 2.42, 2.662, 2.9282], abs=1e-12)
    assert got["Bear"] == pytest.approx([-1.0, -0.95, -0.9025, -0.857375, -0.81450625], abs=5e-5)    # the desk prints 4 decimals
    # a pack built before step 2d (no oe_base): no deduction, as with no revenue path
    res = fmt.execute_financial_model(copy.deepcopy(p), dict(ctx, long_run={k: v for k, v in lr.items() if k != "oe_base"}))
    assert all(s["dcf"]["working_capital_deducted"] is None for s in res["scenario_dcfs"])


def test_the_reference_names_the_base_its_owner_earnings_were_grown_from():
    assert cr.oe_base({"base_cf": 5.0e9, "levels": (6.0e9, 7.0e9)}) == 5.0e9                  # growth method: the base
    assert cr.oe_base({"base_cf": None, "levels": (6.0e9, 7.0e9)}) == 6.0e9                   # levels: the year-1 level (grown at 0 in year 1)
    assert cr.oe_base({"base_cf": None, "levels": None}) is None


# =============================================================================================================================================
# 6. The tax label (the step-2c audit, ruling 3)
# =============================================================================================================================================

def test_the_ranges_supporting_line_labels_t_as_the_translations_estimate():
    sec = pr.render_section(pr.ranges_for(rec(), "2026-10-16", tables=fixture_tables()), True)
    line = next(l for l in sec.splitlines() if l.startswith("- long_run_margin context"))
    assert ("t = 20.0%, the translation's rate, from the years whose net income + tax equals pre-tax income; an estimate, see DATA's tax note "
            "(the median effective rate of 8 fiscal years)") in line
    stat = pr.render_section(pr.ranges_for(rec(tax_t=0.21, tax_t_stamps=["tax_rate_statutory_fallback"],
                                                tax_t_source="21% statutory: no fiscal year passes the identity"), "2026-10-16",
                                            tables=fixture_tables()), True)
    line = next(l for l in stat.splitlines() if l.startswith("- long_run_margin context"))
    assert "t = 21.0%, the translation's rate; an estimate, see DATA's tax note (21% statutory: no fiscal year passes the identity)" in line
