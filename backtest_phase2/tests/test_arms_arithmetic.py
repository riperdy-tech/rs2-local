"""C6: the arm arithmetic, on synthetic companies with hand-computed answers.  The revisions' code runs in worker processes
(one revision per process); the pure glue in arms.py is tested directly."""
import hashlib
import math
import subprocess

import pytest

from backtest_phase2 import arms
from backtest_phase2.tests import helpers as h


def blob_sha256(rev, path):
    data = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=h.HARNESS_ROOT, check=True, capture_output=True).stdout
    return hashlib.sha256(data).hexdigest()


def lf_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(bytes([13, 10]), bytes([10]))).hexdigest()


def candidate_call(run, **kw):
    sw = kw.pop("switches", None)
    job = {"type": "call", "fn": "candidate_value", "kwargs": kw}
    if sw is not None:
        job["switches"] = sw
    return run("candidate", job)["result"]


# ---- the two revisions never share a process -------------------------------------------------------------------------

def test_revisions_load_in_separate_processes(run):
    b = run("baseline", {"type": "probe"})
    c = run("candidate", {"type": "probe"})
    assert b["modules_loaded"] == ["consensus_reference"]                 # no throughcycle_record in the baseline process
    assert not b["identity"]["has_long_run_value"] and b["identity"]["throughcycle_record"] is None
    assert c["modules_loaded"] == ["consensus_reference", "throughcycle_record"]
    assert c["identity"]["has_long_run_value"]
    assert b["identity"]["consensus_reference"] != c["identity"]["consensus_reference"]
    # each process loaded exactly the registered revision's file, byte for byte
    # (the working copy may carry CRLF line endings under core.autocrlf: the comparison is on LF-normalised bytes against the git blob)
    assert lf_sha256(b["identity"]["consensus_reference"]) == blob_sha256(h.BASELINE_REV, "tools/consensus_reference.py")
    assert lf_sha256(c["identity"]["consensus_reference"]) == blob_sha256(h.CANDIDATE_REV, "tools/consensus_reference.py")
    assert lf_sha256(c["identity"]["throughcycle_record"]) == blob_sha256(h.CANDIDATE_REV, "tools/throughcycle_record.py")
    assert b["identity"]["consensus_reference_sha256"] != c["identity"]["consensus_reference_sha256"]


def test_calibration_file_is_the_s1_file_in_the_candidate_process_only(run, s1_file):
    c = run("candidate", {"type": "probe"})
    assert c["identity"]["calibration_file"] == s1_file
    b = run("baseline", {"type": "probe"})
    assert "calibration_file" not in b["identity"]


def test_s1_calibration_every_rate_is_one(run):
    r = run("candidate", {"type": "call", "fn": "trend_level", "kwargs": {"rows": h.company(), "L": 2020, "coe": 0.09,
                                                                        "untagged": ["goodwill", "intangibles_ex_goodwill", "amortization_intangibles"]}})
    assert r["identity"]["calibration_sha256"]
    import json
    doc = json.loads(open(r["identity"]["calibration_file"], encoding="utf-8").read())
    assert all(c["f"] == 1.0 for c in doc["cells"].values()) and set(doc["cells"]) == {"peak_swing", "peak_trend", "trough_swing", "trough_trend", "loss"}
    assert doc["w8"] == 1.0 and all(c["cap"] == 1.0 for c in doc["retention_caps"].values())


# ---- the baseline: hand arithmetic -----------------------------------------------------------------------------------

def flat_rows(ni=100.0, da=30.0, capex=20.0, shares=10.0):
    return {"2020": {"revenue": 1000.0, "net_income": ni, "da": da, "capex": capex, "shares_diluted": shares}}


def test_baseline_perpetuity_value_zero_growth_is_a_value_not_an_absence(run):
    # m = 0.0 and terminal growth 0.0: every year's cash flow is OE = 100 + 30 - 20 = 110, so the value is 110 / 0.10 / 10 shares
    nm = {"cik": "1", "rows": flat_rows(), "L": 2020, "stub_months": 0.0, "shares": 10.0, "m": 0.0}
    r = run("baseline", {"type": "call", "fn": "baseline_value", "kwargs": {"nm": nm, "coe": 0.10, "terminal_g": 0.0}})["result"]
    assert r["reason"] is None
    assert r["value"] == pytest.approx(110.0 / 0.10 / 10.0, rel=1e-12)


def test_baseline_rolls_forward_from_fiscal_year_end_at_the_cost_of_equity(run):
    nm = {"cik": "1", "rows": flat_rows(), "L": 2020, "stub_months": 6.0, "shares": 10.0, "m": 0.0}
    r = run("baseline", {"type": "call", "fn": "baseline_value", "kwargs": {"nm": nm, "coe": 0.10, "terminal_g": 0.0}})["result"]
    assert r["value"] == pytest.approx(110.0 / 0.10 / 10.0 * 1.10 ** 0.5, rel=1e-12)


@pytest.mark.parametrize("rows,m,shares,coe,tg,reason", [
    ({"2020": {"revenue": 1000.0, "net_income": 100.0, "da": 30.0, "capex": 20.0}}, None, 10.0, 0.10, 0.03, "m_missing"),
    ({"2020": {"revenue": 1000.0, "net_income": 100.0, "da": 30.0, "capex": 20.0}}, 0.05, None, 0.10, 0.03, "shares_missing"),
    ({"2020": {"revenue": 1000.0, "net_income": 100.0, "da": 30.0, "capex": None}}, 0.05, 10.0, 0.10, 0.03, "owner_earnings_missing"),
    ({"2020": {"revenue": 1000.0, "net_income": 10.0, "da": 5.0, "capex": 20.0}}, 0.05, 10.0, 0.10, 0.03, "owner_earnings_not_positive"),
    ({"2020": {"revenue": 1000.0, "net_income": -5.0, "da": 30.0, "capex": 10.0}}, 0.05, 10.0, 0.10, 0.03, "eps_base_not_positive"),
    ({"2020": {"revenue": 1000.0, "net_income": 100.0, "da": 30.0, "capex": 20.0}}, 0.05, 10.0, 0.03, 0.03, "coe_not_above_terminal_growth"),
])
def test_baseline_failures_are_counted_by_reason_never_defaulted(run, rows, m, shares, coe, tg, reason):
    nm = {"cik": "1", "rows": rows, "L": 2020, "stub_months": 0.0, "shares": shares, "m": m}
    r = run("baseline", {"type": "call", "fn": "baseline_value", "kwargs": {"nm": nm, "coe": coe, "terminal_g": tg}})["result"]
    assert r["value"] is None and r["reason"] == reason


# ---- the low-rate floor (4.4) and the rates --------------------------------------------------------------------------

@pytest.mark.parametrize("rf,gA,expect", [(0.0066, 0.0325, 0.0325), (0.0381, 0.035, 0.0381), (0.0325, 0.0325, 0.0325), (-0.002, 0.03, 0.03),
                                          (0.0, 0.0, 0.0)])
def test_low_rate_floor_is_the_larger_of_the_yield_and_growth(rf, gA, expect):
    assert arms.rf_effective(rf, gA) == expect


def test_cost_of_equity_and_premium_definitions():
    rf_eff = arms.rf_effective(0.0066, 0.0325)
    erp_B = arms.erp_from_market(0.0936, rf_eff)
    assert erp_B == pytest.approx(0.0936 - 0.0325)
    assert arms.coe_of(1.0, rf_eff, erp_B) == pytest.approx(0.0936)                 # a loading of 1 earns the market rate
    assert arms.coe_of(0.67 * 0.5 + 0.33, rf_eff, erp_B) == pytest.approx(0.0325 + 0.665 * (0.0936 - 0.0325))
    assert arms.adjusted_loading(1.0) == pytest.approx(1.0) and arms.adjusted_loading(0.0) == 0.33


# ---- the candidate: returns override (3.2.1) -------------------------------------------------------------------------

@pytest.mark.parametrize("r_tc,p,coe,blend,ronic_t", [
    (0.20, 0.5, 0.10, 0.20, 0.15),                  # r + p (R_tc - r)
    (0.20, 1.0, 0.10, 0.20, 0.20),
    (0.05, 0.75, 0.10, 0.05, 0.10),                 # below the cost of equity: max(0, .) = 0, so RONIC_T = r
    (math.inf, 0.5, 0.10, math.inf, math.inf),
    (-math.inf, 0.0, 0.10, -math.inf, 0.10),
    (None, None, 0.10, None, None),                 # no record: both left None (RONIC_T = r and the stamp follow in build)
])
def test_returns_override_hand_values(r_tc, p, coe, blend, ronic_t):
    rec = arms.returns_override({"R_tc": r_tc, "p": p, "r_blend": 99.0, "ronic_t": 99.0}, coe)
    assert rec["r_blend"] == blend
    if ronic_t is not None and math.isfinite(ronic_t):
        assert rec["ronic_t"] == pytest.approx(ronic_t)
    else:
        assert rec["ronic_t"] == ronic_t


def test_returns_override_reaches_build_uncapped_and_unblended(run):
    # constant return on tangible capital well above the cost of equity: the override uses the uncapped median and p
    rows = h.company(years=range(2010, 2021), margin=0.30, equity_frac=0.1)
    nm = h.nm_of(rows)
    r = candidate_call(run, nm=nm, coe=0.09, gA=0.03, pi=0.02)
    assert r["reason"] is None
    assert r["R_tc"] is not None and r["R_tc"] > 1.0                      # above revision 17's cap of 1.0: it is not capped here
    assert r["build"]["terminal_ronic"] == pytest.approx(0.09 + r["p"] * max(0.0, r["R_tc"] - 0.09))
    assert r["build"]["ronic0"] == pytest.approx(max(0.09, r["R_tc"]))


def test_returns_override_changes_the_value_against_revision_17_as_committed(run):
    rows = h.company(years=range(2010, 2021), margin=0.30, equity_frac=0.1)
    nm = h.nm_of(rows)
    own = candidate_call(run, nm=nm, coe=0.09, gA=0.03, pi=0.02, switches={"returns": "rtc", "margin": "none", "cash": False})
    r17 = candidate_call(run, nm=nm, coe=0.09, gA=0.03, pi=0.02, switches={"returns": "analyse", "margin": "none", "cash": False})
    assert own["build"]["terminal_ronic"] != pytest.approx(r17["build"]["terminal_ronic"])


# ---- the candidate: the trend level (3.2.2) --------------------------------------------------------------------------

UNTAGGED = ["goodwill", "intangibles_ex_goodwill", "amortization_intangibles"]


def margin_rows(margins, years):
    rows = h.company(years=years)
    for y, om in zip(years, margins):
        rev = rows[str(y)]["revenue"]
        rows[str(y)]["operating_income"] = om * rev
    return rows


def test_trend_level_is_the_fitted_line_at_the_base_year(run):
    years = list(range(2010, 2021))
    rows = margin_rows([0.10 + 0.01 * (y - 2010) for y in years], years)
    r = run("candidate", {"type": "call", "fn": "trend_level", "kwargs": {"rows": rows, "L": 2020, "coe": 0.09, "untagged": UNTAGGED}})["result"]
    assert r["om_years"] == list(range(2013, 2021))                              # the eight-year window
    assert r["T_L"] == pytest.approx(0.20, abs=1e-12)                            # a + b L: the line's level in 2020
    assert r["om_tc"] == pytest.approx(0.165)                                    # the median it replaces: 0.13..0.20 -> 0.165


def test_trend_level_theil_sen_ignores_one_outlier_year(run):
    years = list(range(2010, 2021))
    margins = [0.10 + 0.01 * (y - 2010) for y in years]
    margins[years.index(2016)] = 0.90
    rows = margin_rows(margins, years)
    r = run("candidate", {"type": "call", "fn": "trend_level", "kwargs": {"rows": rows, "L": 2020, "coe": 0.09, "untagged": UNTAGGED}})["result"]
    assert r["T_L"] == pytest.approx(0.20, abs=1e-12)                            # the robust line still passes through the clean years


def test_trend_level_with_no_trend_is_the_median(run):
    years = list(range(2010, 2021))
    margins = [0.12, 0.16, 0.12, 0.16, 0.12, 0.16, 0.12, 0.16, 0.12, 0.16, 0.12]
    rows = margin_rows(margins, years)
    r = run("candidate", {"type": "call", "fn": "trend_level", "kwargs": {"rows": rows, "L": 2020, "coe": 0.09, "untagged": UNTAGGED}})["result"]
    assert abs(r["T_L"] - r["om_tc"]) < 0.03                                      # no trend: the level is near the median


def test_trend_level_reaches_the_long_run_margin_in_full(run):
    years = list(range(2010, 2021))
    rows = margin_rows([0.10 + 0.01 * (y - 2010) for y in years], years)
    nm = h.nm_of(rows)
    r = candidate_call(run, nm=nm, coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf", "cash": False})
    x_L = r_x_L = None
    row = rows["2020"]
    tax = row["tax_provision"] / row["pretax_income"]
    x_L = row["net_income"] / row["revenue"]
    om_L = row["operating_income"] / row["revenue"]
    # fraction 1.0: OM_long = T_L, so m_long = m5 + (1 - tax) (T_L - OM_5) with m5 = x_L (the synthetic path keeps the margin) and OM_5 = om_L
    assert r["trend_level"] == pytest.approx(0.20, abs=1e-12)
    assert r["build"]["margin_fraction"] == 1.0
    assert r["build"]["m_long"] == pytest.approx(x_L + (1 - tax) * (r["trend_level"] - om_L), rel=1e-9)


def test_loss_record_target_is_zero_with_full_reversion(run):
    years = list(range(2010, 2021))
    rows = margin_rows([-0.05 - 0.002 * (y - 2010) for y in years], years)
    for y in years:
        rows[str(y)]["net_income"] = 40.0 * (1 + 0.01 * (y - 2010))              # a positive earnings base with a losing operating record
        rows[str(y)]["pretax_income"] = 50.0
        rows[str(y)]["tax_provision"] = 10.0
    nm = h.nm_of(rows)
    r = candidate_call(run, nm=nm, coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf", "cash": False})
    if r["build"]["margin_cell"] is not None:                                      # margin_rule only applies when the year-5 margin is a profit
        assert r["build"]["margin_cell"] in ("loss", "peak_trend", "peak_swing", "trough_trend", "trough_swing")
        assert r["build"]["margin_fraction"] == 1.0


# ---- the candidate: cash at face (3.2.3) ------------------------------------------------------------------------------

def cash_pair(cash=500.0, y=0.02):
    """Two companies with the same operating business; A also holds cash that earns y after tax, inside net income."""
    a = h.company(cash=cash, interest=y)
    b = h.company(cash=0.0, interest=0.0)
    return a, b


def test_cash_is_added_at_face_and_interest_is_not_counted_twice(run):
    a, b = cash_pair()
    kw = dict(coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf", "cash": True})
    va = candidate_call(run, nm=h.nm_of(a, y_L=0.02), **kw)
    vb = candidate_call(run, nm=h.nm_of(b, y_L=0.02), **kw)
    assert va["reason"] is None and vb["reason"] is None
    assert va["cash"] == 500.0 and va["interest_removed"] == pytest.approx(500.0 * 0.02 * 0.75)
    assert vb["cash"] == 0.0
    # the same operating business: A is worth B plus its cash per share, to rounding
    assert va["value"] - vb["value"] == pytest.approx(500.0 / 100.0, rel=1e-9)


def test_without_the_x_override_the_interest_would_be_counted_twice(run):
    a, b = cash_pair()
    kw = dict(coe=0.09, gA=0.03, pi=0.02)
    vb = candidate_call(run, nm=h.nm_of(b, y_L=0.02), switches={"returns": "inf", "cash": True}, **kw)
    va_off = candidate_call(run, nm=h.nm_of(a, y_L=0.02), switches={"returns": "inf", "cash": True, "x_l_override": False}, **kw)
    # margin_rule then reads the removed interest as a fall of the operating margin and adds it back in the long run:
    assert abs((va_off["value"] - vb["value"]) - 5.0) > 0.01


def test_financials_and_real_estate_get_no_cash_term(run):
    a, _ = cash_pair()
    for sector in ("Financial Services", "Real Estate"):
        r = candidate_call(run, nm=h.nm_of(a, y_L=0.02, sector=sector), coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf"})
        assert r["cash"] == 0.0 and r["interest_removed"] == 0.0
    r = candidate_call(run, nm=h.nm_of(a, y_L=0.02, sector="Unknown"), coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf"})
    assert r["cash"] == 500.0                                                    # any other label, including an unknown one, is non-financial


def test_null_cash_means_no_cash_term_and_is_stamped(run):
    a, _ = cash_pair()
    for row in a.values():
        row["cash"] = None
    r = candidate_call(run, nm=h.nm_of(a, y_L=0.02), coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf"})
    assert r["cash"] == 0.0 and "cash_term_not_available" in r["stamps"]


def test_null_short_term_investments_count_zero_and_present_ones_add(run):
    a, _ = cash_pair()
    r0 = candidate_call(run, nm=h.nm_of(a, y_L=0.02), coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf"})
    a["2020"]["st_investments"] = 200.0
    r1 = candidate_call(run, nm=h.nm_of(a, y_L=0.02), coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf"})
    assert r0["cash"] == 500.0 and r1["cash"] == 700.0


def test_operating_base_not_positive_values_the_company_at_its_cash(run):
    # the interest on 5,000 of cash exceeds the whole owner-earnings base: nothing operating is left to value
    a = h.company(cash=5000.0, interest=0.04, margin=0.0)
    r = candidate_call(run, nm=h.nm_of(a, y_L=0.04), coe=0.09, gA=0.03, pi=0.02)
    assert r["operating_base_not_positive"] is True
    assert "operating_base_not_positive" in r["stamps"]
    assert r["value"] == pytest.approx(5000.0 / 100.0)                           # C_L / shares, and it counts as a value


def test_zero_cash_is_a_value_and_changes_nothing(run):
    b = h.company(cash=0.0)
    with_cash_term = candidate_call(run, nm=h.nm_of(b, y_L=0.02), coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf"})
    without = candidate_call(run, nm=h.nm_of(b, y_L=0.02), coe=0.09, gA=0.03, pi=0.02, switches={"returns": "inf", "cash": False})
    assert with_cash_term["value"] == pytest.approx(without["value"], rel=1e-12)
    assert with_cash_term["cash"] == 0.0


# ---- terminal growth (3.2.4) ------------------------------------------------------------------------------------------

def test_candidate_terminal_growth_is_the_revenue_trend_held_between_breakeven_and_the_anchor(run):
    rows = h.company(growth=0.05)
    r = candidate_call(run, nm=h.nm_of(rows), coe=0.09, gA=0.035, pi=0.02, switches={"returns": "inf", "cash": False})
    assert r["terminal_g"] == pytest.approx(0.035)                                # the 5% trend (4.9% in logs) is above the anchor: capped at gA
    r = candidate_call(run, nm=h.nm_of(h.company(growth=0.01)), coe=0.09, gA=0.035, pi=0.02, switches={"returns": "inf", "cash": False})
    assert r["terminal_g"] == pytest.approx(0.02)                                 # trend 1% is below breakeven inflation: floored at pi
    r = candidate_call(run, nm=h.nm_of(h.company(growth=0.03)), coe=0.09, gA=0.035, pi=0.02, switches={"returns": "inf", "cash": False})
    assert r["terminal_g"] == pytest.approx(math.log(1.03), abs=1e-9)             # the Theil-Sen slope of ln revenue: between pi and gA, held as is


# ---- the reduction (C3), on a synthetic company ------------------------------------------------------------------------

def test_reduction_candidate_equals_baseline_to_the_cent(run):
    rows = h.company(growth=0.06, margin=0.2, amort=0.0)
    nm = h.nm_of(rows, m=0.06, stub=7.0, y_L=0.01)
    b = run("baseline", {"type": "call", "fn": "baseline_value", "kwargs": {"nm": nm, "coe": 0.09, "terminal_g": 0.03}})["result"]
    red = {"returns": "inf", "margin": "none", "cash": False, "working_capital": False, "terminal": "gA", "earnings_base": "OE"}
    c = candidate_call(run, nm=nm, coe=0.09, gA=0.03, pi=0.02, switches=red)
    assert b["value"] is not None and c["value"] is not None
    assert round(b["value"], 2) == round(c["value"], 2)
    assert c["value"] == pytest.approx(b["value"], rel=1e-9)


def test_the_reduction_needs_the_earnings_base_set_to_owner_earnings(run):
    # with X as the base the years-6+ cash flows grow net income, not owner earnings: the identity does not hold without the switch
    rows = h.company(growth=0.06, margin=0.2)
    nm = h.nm_of(rows, m=0.06, stub=7.0, y_L=0.01)
    b = run("baseline", {"type": "call", "fn": "baseline_value", "kwargs": {"nm": nm, "coe": 0.09, "terminal_g": 0.03}})["result"]
    red_x = {"returns": "inf", "margin": "none", "cash": False, "working_capital": False, "terminal": "gA", "earnings_base": "X"}
    c = candidate_call(run, nm=nm, coe=0.09, gA=0.03, pi=0.02, switches=red_x)
    assert abs(c["value"] - b["value"]) > 0.01


# ---- the long-run floor and the failures of the candidate ---------------------------------------------------------------

def test_candidate_failures_are_counted_by_reason(run):
    base = h.company()
    nm = h.nm_of(base, m=None)
    assert candidate_call(run, nm=nm, coe=0.09, gA=0.03, pi=0.02)["reason"] == "m_missing"
    nm = h.nm_of(base, shares=None)
    assert candidate_call(run, nm=nm, coe=0.09, gA=0.03, pi=0.02)["reason"] == "shares_missing"
    nm = h.nm_of(base)
    assert candidate_call(run, nm=nm, coe=0.03, gA=0.03, pi=0.02, switches={"cash": False})["reason"] == "coe_not_above_terminal_growth"


def test_owner_earnings_treats_zero_as_a_value():
    assert arms.owner_earnings({"net_income": 10.0, "da": 0.0, "capex": 0.0}) == 10.0
    assert arms.owner_earnings({"net_income": 0.0, "da": 0.0, "capex": 0.0}) == 0.0
    assert arms.owner_earnings({"net_income": 10.0, "da": None, "capex": 0.0}) is None


def test_synthetic_estimates_follow_4_6():
    est = arms.synthetic_estimates(1000.0, 80.0, 10.0, 0.07)
    assert est["0y"]["eps"] == {"growth": 0.07, "year_ago": 8.0, "analysts": 1}
    assert est["+1y"]["eps"]["growth"] == 0.07 and est["+1y"]["eps"]["analysts"] == 1
    assert est["0y"]["revenue"]["avg"] == pytest.approx(1070.0) and est["+1y"]["revenue"]["avg"] == pytest.approx(1000.0 * 1.07 ** 2)
    assert est["0y"]["revenue"]["growth"] == 0.07 and est["+1y"]["revenue"]["growth"] == 0.07 and est["0y"]["revenue"]["analysts"] == 1
    assert "high" not in est["+1y"]["eps"] and "low" not in est["+1y"]["eps"]            # no range


def test_synthetic_estimates_zero_growth_is_a_value():
    est = arms.synthetic_estimates(1000.0, 80.0, 10.0, 0.0)
    assert est["0y"]["eps"]["growth"] == 0.0 and est["0y"]["revenue"]["avg"] == 1000.0
