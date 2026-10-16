"""Revision 24, step 1: the arithmetic audit of the desk and the default generator (brief BRIEF_R24_S1_desk_arithmetic_audit.md).

An audit: these tests change no code. Each input of the long run is checked for its intended effect on cash flow and per-share value on a
synthetic company, with the expected numbers computed by hand (the comments) and asserted as plain arithmetic independent of the code under
test; then for monotonicity and the absence of sign flips over its realistic range. O2 (the operating-to-earnings margin translation,
rev23/defect_census.md) is reproduced on synthetic LITE-like and LIND-like companies and on the two saved baseline facts files
(fixture_data/rev24_desk_audit/, copied verbatim from rs2-local/ab_reports/consensus/{LITE_20261006_145640,LIND_20261006_133708}/_pack_facts.json).

Every defect found is stated as the property it violates, in a test marked xfail(strict=True) with the reason: the suite stays clean, and a fix
turns the test into an XPASS, which strict mode reports, so the marker is removed with the fix. The coordinator rules on every fix.

Revision 24 step 2a (brief BRIEF_R24_S2a_desk_fixes.md, the coordinator's rulings 1-6) fixed them: the desk takes the analyst's long_run_margin
(the facts' margin_ratio no longer reaches it), D2, D3 and D4 are fixed, and a terminal_ronic below r and the margin rule's out-of-range and clamp
are stamped. The eight markers are removed; a test that used the facts' margin_ratio now passes the same ratio as a long_run_margin over the
scenario's year-5 earnings margin, and the tests that reproduced a defect are restated as the fixed behaviour (each says so).

Two units: the desk (financial_model_tool.unbundled_dcf) takes $B and billions of shares; the default generator (consensus_reference.build)
takes dollars and shares.
"""
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import analyst_tools as at  # noqa: E402
import consensus_reference as cr  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
from test_throughcycle_reference import COE, EST, GA, MEDIAN5  # noqa: E402

B = 1e9
INF = math.inf
FIX = HERE / "fixture_data" / "rev24_desk_audit"
D5 = [1.1 ** t for t in range(1, 6)]        # discount factors at r = 10%: 1.1, 1.21, 1.331, 1.4641, 1.61051
PV15_FLAT = sum(1 / d for d in D5)          # 0.909091 + 0.826446 + 0.751315 + 0.683013 + 0.620921 = 3.790787


# =============================================================================================================================
# Part A - the desk. Synthetic company S: base_cf $1.0B, 1.0B shares, r = 10%, terminal growth 3%, a one-year fade, no record
# facts (long_run None, so year-5 earnings = year-5 owner earnings, stamp long_run_on_owner_earnings), RONIC unlimited unless set.
# =============================================================================================================================

def desk(**kw):
    a = dict(base_cf=1.0, explicit_growth=[0.0] * 5, wacc=0.10, terminal_g=0.03, shares_diluted=1.0, fade_years=1,
             sbc_treatment="deducted_in_cf", terminal_ronic=INF)
    a.update(kw)
    res = fmt.unbundled_dcf(**a)
    assert not res.get("error"), res
    return res


def iv(**kw):
    return desk(**kw)["per_share_iv_raw"]


# S by hand. Years 1-5: 1.0 each, PV 3.790787. Year 6: g6 = g5 + (gt - g5) x 1/1 = 3%, E6 = 1.03, RONIC unlimited so the flow is 1.03,
# PV 1.03 / 1.1^6 = 0.581406. Terminal at year 6: E7 (1 - 0) / (r - g) = 1.03 x 1.03 / 0.07 = 15.155714, PV / 1.1^6 = 8.555008.
# Long run = 1.03 / 0.07 / 1.1^5 = 9.136414 (the Gordon value of E6 at year 5). Value = 3.790787 + 9.136414 = 12.927201.
LR_S = 1.03 / 0.07 / 1.1 ** 5
VALUE_S = PV15_FLAT + LR_S


def test_s_by_hand_years_1_to_5_the_year_6_flow_and_the_terminal():
    res = desk()
    assert res["projected_cfs"] == [1.0, 1.0, 1.0, 1.0, 1.0, 1.03]
    assert res["per_share_iv_raw"] == pytest.approx(VALUE_S, rel=1e-12)              # 12.927201
    assert res["terminal_value_nominal"] == pytest.approx(1.03 * 1.03 / 0.07, abs=0.005)  # 15.16
    assert "long_run_on_owner_earnings" in res["stamps"]


# ---- base earnings ----------------------------------------------------------------------------------------------------------

def test_base_earnings_scale_every_flow_and_the_value_one_for_one_without_a_reference():
    """Doubling base_cf doubles every flow and the value: 2 x 12.927201 = 25.854401 (the long run takes E5 = OE5 here)."""
    assert iv(base_cf=2.0) == pytest.approx(2 * VALUE_S, rel=1e-12)
    vals = [iv(base_cf=b) for b in (0.1, 0.5, 1.0, 2.0, 5.0)]
    assert all(v > 0 for v in vals) and vals == sorted(vals)


def test_with_a_reference_the_scenario_year5_earnings_scale_with_its_owner_earnings():
    """Restated by revision 24 step 2a (D3; it reproduced the additive E5 = e5 + (OE5 - oe5), which gave 1.8 below). _long_run_inputs:
    E5 = e5 (facts) x OE5 / oe5 (facts), PROPORTIONAL. Facts e5 0.8, oe5 1.0, margin held: base 1.0 gives E5 0.8; base 2.0 gives E5 1.6.
    Value: 2 x PV15 + 1.6 x 1.03 / 0.07 / 1.1^5 = 7.581574 + 14.618262 = 22.199836."""
    lr = {"e5": 0.8, "oe5": 1.0}
    assert desk(base_cf=1.0, long_run=lr)["long_run"]["year5_earnings"] == pytest.approx(0.8)
    assert desk(base_cf=2.0, long_run=lr)["long_run"]["year5_earnings"] == pytest.approx(1.6)
    assert iv(base_cf=2.0, long_run=lr) == pytest.approx(2 * PV15_FLAT + 1.6 * LR_S / 1.0, rel=1e-12)


def test_without_a_reference_the_same_translation_is_proportional():
    """The fallback (no reference e5 in the facts): E5 = OE5 x x_over_oe, proportional. Base 2.0, x_over_oe 0.8: E5 = 1.6. Since revision 24
    step 2a the translation with a reference is proportional too (the D3 test below)."""
    r = desk(base_cf=2.0, long_run={"x_over_oe": 0.8})
    assert r["long_run"]["year5_earnings"] == pytest.approx(1.6) and "long_run_base_ratio_x" in r["stamps"]


# ---- years 1-2 and years 3-5 growth -----------------------------------------------------------------------------------------

def test_year1_growth_lifts_every_later_flow_and_the_long_run_by_the_same_factor():
    """Year-1 growth 10%: flows 1.1 in every year and E5 1.1, so value = 1.1 x 12.927201 = 14.219921."""
    r = desk(explicit_growth=[0.10, 0, 0, 0, 0])
    assert r["projected_cfs"][:5] == [1.1] * 5
    assert r["per_share_iv_raw"] == pytest.approx(1.1 * VALUE_S, rel=1e-12)


def test_year3_growth_leaves_years_1_2_and_lifts_years_3_on():
    """Year-3 growth 10%: years 1-2 stay 1.0 (PV 0.909091 + 0.826446 = 1.735537); years 3-5 and the long run x 1.1:
    1.1 x (0.751315 + 0.683013 + 0.620921 + 9.136414) = 12.310830; value 14.046367."""
    r = desk(explicit_growth=[0, 0, 0.10, 0, 0])
    assert r["projected_cfs"][:5] == pytest.approx([1.0, 1.0, 1.1, 1.1, 1.1])
    expect = 1 / 1.1 + 1 / 1.21 + 1.1 * (1 / 1.331 + 1 / 1.4641 + 1 / 1.61051 + LR_S)
    assert r["per_share_iv_raw"] == pytest.approx(expect, rel=1e-12)


@pytest.mark.parametrize("slot", [0, 1, 2, 3, 4])
def test_each_explicit_growth_rate_raises_value_monotonically_with_no_sign_flip(slot):
    """Over -20% .. +60% for one year at a time (RONIC 25% > r): value rises strictly and stays positive."""
    vals = []
    for g in (-0.20, -0.05, 0.0, 0.10, 0.30, 0.60):
        path = [0.05] * 5
        path[slot] = g
        vals.append(iv(explicit_growth=path, terminal_ronic=0.25, fade_years=5))
    assert all(v > 0 for v in vals) and all(b > a for a, b in zip(vals, vals[1:]))


# ---- the long-run margin (revision 24 step 2a: the analyst's long_run_margin; it was the facts' margin_ratio) --------------------------
# S's facts: e5 = oe5 = 1.0 and m5 = 10%, so the facts' year-5 revenue is 10.0 and S's year-5 earnings margin is 10%: long_run_margin = m x 10%
# gives the margin ratio m.
LR_M = {"e5": 1.0, "oe5": 1.0, "m5": 0.10}


def test_the_long_run_margin_scales_the_long_run_linearly():
    """long_run_margin 5% (ratio 0.5) and 12% (ratio 1.2) with a one-year fade: k6 = k_end = ratio, so the long run is ratio x 9.136414.
    0.5: 3.790787 + 4.568207 = 8.358994; 1.2: 3.790787 + 10.963697 = 14.754483. A higher long-run margin raises value."""
    assert iv(long_run=LR_M, long_run_margin=0.05) == pytest.approx(PV15_FLAT + 0.5 * LR_S, rel=1e-12)
    assert iv(long_run=LR_M, long_run_margin=0.12) == pytest.approx(PV15_FLAT + 1.2 * LR_S, rel=1e-12)


def test_the_long_run_margin_is_monotone_and_never_flips_the_sign_of_a_flow():
    """long_run_margin over 0% .. 15% (ratio 0 .. 1.5) with a five-year fade: value rising; every flow >= 0; at 0 the terminal value is 0, not
    negative."""
    vals = []
    for m in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5):
        r = desk(long_run=LR_M, long_run_margin=m * 0.10, fade_years=5, terminal_ronic=0.20)
        assert all(cf >= 0 for cf in r["projected_cfs"])
        vals.append(r["per_share_iv_raw"])
    assert all(b > a for a, b in zip(vals, vals[1:]))
    assert desk(long_run=LR_M, long_run_margin=0.0, fade_years=5)["terminal_value_nominal"] == 0


# ---- terminal growth --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("gt, expect_lr", [
    (0.02, 1.02 / 0.08 / 1.1 ** 5),     # 7.916747
    (0.03, 1.03 / 0.07 / 1.1 ** 5),     # 9.136414
    (0.05, 1.05 / 0.05 / 1.1 ** 5),     # 13.039348
])
def test_terminal_growth_below_the_discount_rate_raises_value_when_new_investment_is_free(gt, expect_lr):
    """RONIC unlimited, one-year fade: long run = (1 + gt) / (r - gt) / 1.1^5."""
    assert iv(terminal_g=gt) == pytest.approx(PV15_FLAT + expect_lr, rel=1e-12)


@pytest.mark.parametrize("fade, g5, gt", [(1, 0.0, 0.03), (5, 0.08, 0.02), (5, 0.08, 0.06), (10, 0.15, 0.04), (3, -0.02, 0.03)])
def test_at_ronic_equal_to_r_growth_after_year_6_adds_nothing(fade, g5, gt):
    """The value-driver identity, derived by hand: with RONIC = r and the margin held, flow_t = E_t - (E_{t+1} - E_t) / r, so the discounted sum
    telescopes and the long run at year 5 is exactly E6 / r, whatever the fade and the terminal growth. E6 = OE5 (1 + g6), g6 = g5 + (gt - g5)
    / F. Example (5, 8%, 2%): OE5 = 1.08^5 = 1.469328, g6 = 6.8%, long run at t0 = 1.469328 x 1.068 / 0.10 / 1.61051 = 9.743761."""
    path = [g5] * 5
    oe = [1.0 * (1 + g5) ** t for t in range(1, 6)]
    g6 = g5 + (gt - g5) / fade
    expect = sum(cf / d for cf, d in zip(oe, D5)) + oe[4] * (1 + g6) / 0.10 / 1.1 ** 5
    assert iv(explicit_growth=path, terminal_g=gt, fade_years=fade, terminal_ronic=0.10) == pytest.approx(expect, rel=1e-12)


def test_terminal_growth_is_monotone_over_its_range_and_refused_at_or_above_r():
    """RONIC 20% > r: value strictly rising for gt in -2% .. 9%, all positive; gt = r is refused, never valued."""
    vals = [iv(terminal_g=g, terminal_ronic=0.20, fade_years=5, explicit_growth=[0.05] * 5)
            for g in (-0.02, 0.0, 0.0236, 0.0375, 0.05, 0.07, 0.09)]
    assert all(v > 0 for v in vals) and all(b > a for a, b in zip(vals, vals[1:]))
    res = fmt.unbundled_dcf(base_cf=1.0, explicit_growth=[0.0] * 5, wacc=0.10, terminal_g=0.10, shares_diluted=1.0, fade_years=1,
                            sbc_treatment="deducted_in_cf")
    assert res.get("validation_error")


# ---- the return on new investment ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("ronic, factor", [(0.15, 1 - 0.03 / 0.15), (0.30, 1 - 0.03 / 0.30), (INF, 1.0)])
def test_a_higher_ronic_lowers_the_reinvestment_charge(ronic, factor):
    """One-year fade: flow6 = E6 (1 - g7 / RONIC) = 1.03 x (1 - 0.03 / RONIC): 0.824 at 15%, 0.927 at 30%, 1.03 unlimited; the long run
    = 9.136414 x (1 - 0.03 / RONIC): 7.309131, 8.222772, 9.136414."""
    r = desk(terminal_ronic=ronic)
    assert r["projected_cfs"][5] == pytest.approx(1.03 * factor, abs=1e-4)
    assert r["per_share_iv_raw"] == pytest.approx(PV15_FLAT + LR_S * factor, rel=1e-12)


def test_ronic_is_monotone_and_a_value_below_r_is_valued_as_stated():
    """RONIC over 5% .. 10^6: value strictly rising (an unlimited RONIC is D4 below). Was `..._a_value_below_r_is_valued_at_r` (step 2a's
    ruling 5: max(r, RONIC), stamped `terminal_ronic_floored_at_r`). Revision 24 step 2d (cross-check 19, ruling 1): a terminal_ronic below r is
    valued as stated, stamped `terminal_ronic_below_rate`. S by hand at 5% (one-year fade, no record, so the fade starts at the terminal return,
    stamped `ronic_start_from_terminal`): flow6 = 1.03 x (1 - 0.03 / 0.05) = 0.412; the long run = 9.136414 x 0.4 = 3.654566; value = 3.790787 +
    3.654566 = 7.445353; at r, 3.790787 + 9.136414 x 0.7 = 10.186277."""
    vals = [iv(terminal_ronic=x, fade_years=5, explicit_growth=[0.06] * 5) for x in (0.05, 0.075, 0.10, 0.12, 0.20, 0.50, 1.0, 10.0, 1e6)]
    assert all(b > a for a, b in zip(vals, vals[1:])) and min(vals) > 0
    low = desk(terminal_ronic=0.05)
    assert low["per_share_iv_raw"] == pytest.approx(PV15_FLAT + LR_S * (1 - 0.03 / 0.05), rel=1e-12)          # 7.445353
    assert desk(terminal_ronic=0.10)["per_share_iv_raw"] == pytest.approx(PV15_FLAT + LR_S * (1 - 0.03 / 0.10), rel=1e-12)   # 10.186277
    assert low["terminal_ronic"] == 0.05
    assert [s for s in low["stamps"] if "ronic" in s] == ["terminal_ronic_below_rate", "ronic_start_from_terminal"]
    assert "terminal_ronic_below_rate" not in desk(terminal_ronic=0.10, fade_years=5, explicit_growth=[0.06] * 5)["stamps"]
    # with a record start above r, a terminal_ronic below r is worth less than one at r (it was exactly the value at r)
    rec = {"r_tc": 0.30}
    at_r = iv(terminal_ronic=0.10, fade_years=5, explicit_growth=[0.06] * 5, long_run=rec)
    assert iv(terminal_ronic=0.05, fade_years=5, explicit_growth=[0.06] * 5, long_run=rec) < at_r


def test_the_record_return_sets_the_starting_ronic_of_the_fade():
    """_long_run_inputs: RONIC_0 = r_tc as measured when above 0 (revision 24 step 2d, cross-check 19 ruling 1; it was max(r, r_tc)). r_tc 40%
    against 12%: a higher start, a higher value; r_tc 5%, below r: the start is 5%, stamped `ronic_start_below_rate`, and the value is below the
    value at a start of r; r_tc at or below 0: the start is the terminal return, stamped `ronic_start_from_terminal`."""
    base = dict(fade_years=5, explicit_growth=[0.08] * 5, terminal_ronic=0.12)
    lo = desk(long_run={"e5": None, "r_tc": 0.05}, **base)
    hi = desk(long_run={"e5": None, "r_tc": 0.40}, **base)
    at_r = desk(long_run={"e5": None, "r_tc": 0.10}, **base)
    neg = desk(long_run={"e5": None, "r_tc": -0.05}, **base)
    flat = desk(long_run={"e5": None, "r_tc": 0.12}, **base)
    assert lo["ronic_start"] == 0.05 and hi["ronic_start"] == 0.40 and neg["ronic_start"] == 0.12
    assert "ronic_start_below_rate" in lo["stamps"] and "ronic_start_below_rate" not in at_r["stamps"]
    assert "ronic_start_from_terminal" in neg["stamps"]
    assert lo["per_share_iv_raw"] < at_r["per_share_iv_raw"] < hi["per_share_iv_raw"]
    assert neg["per_share_iv_raw"] == pytest.approx(flat["per_share_iv_raw"], rel=1e-12)       # the fade starts at the terminal 12%


# ---- working capital --------------------------------------------------------------------------------------------------------

def test_more_working_capital_lowers_the_year_1_to_5_flows_and_nothing_after():
    """working_capital 0.1 a year: flows 0.9 in years 1-5, PV lower by 0.1 x 3.790787 = 0.379079; the long run unchanged; value 12.548122."""
    r = desk(working_capital=[0.1] * 5)
    assert r["projected_cfs"] == pytest.approx([0.9] * 5 + [1.03])
    assert r["per_share_iv_raw"] == pytest.approx(VALUE_S - 0.1 * PV15_FLAT, rel=1e-12)
    vals = [iv(working_capital=[w] * 5) for w in (-0.2, 0.0, 0.1, 0.3, 0.6)]
    assert all(b < a for a, b in zip(vals, vals[1:])) and all(v > 0 for v in vals)


# ---- excess cash and the roll-forward ------------------------------------------------------------------------------------------

def test_excess_cash_adds_at_face_per_share_and_is_not_rolled_forward():
    """Stub 6 months: the operating value rolls by 1.1^0.5 = 1.048809 to 13.558162; cash $2.0B on 1.0B shares adds exactly 2.00: 15.558162."""
    r = desk(excess_cash=2.0, long_run={"stub_months": 6.0})
    assert r["per_share_iv_raw"] == pytest.approx(VALUE_S * 1.1 ** 0.5 + 2.0, rel=1e-12)
    assert iv(excess_cash=2.0) - iv() == pytest.approx(2.0, abs=1e-12)


# ---- the discount rate ------------------------------------------------------------------------------------------------------

def test_the_discount_rate_lowers_value_monotonically_over_its_range():
    """r over 6% .. 16% with RONIC 18% and the record start r_tc 25%: value strictly falling, all positive (the roll-forward rises with r but
    by far less)."""
    vals = [iv(wacc=w, terminal_ronic=0.18, fade_years=5, explicit_growth=[0.06] * 5,
               long_run={"r_tc": 0.25, "stub_months": 9.0}) for w in (0.06, 0.08, 0.10, 0.12, 0.14, 0.16)]
    assert all(v > 0 for v in vals) and all(b < a for a, b in zip(vals, vals[1:]))


# ---- the fade ---------------------------------------------------------------------------------------------------------------

def test_a_longer_fade_raises_value_when_growth_fades_down_and_lowers_it_when_growth_fades_up():
    """RONIC 25% > r. g5 12% above gt 3%: more years of higher growth, value rises with the fade. g5 -2% below gt: value falls."""
    up = [iv(explicit_growth=[0.12] * 5, terminal_ronic=0.25, fade_years=f) for f in (1, 3, 5, 8, 12)]
    down = [iv(explicit_growth=[-0.02] * 5, terminal_ronic=0.25, fade_years=f) for f in (1, 3, 5, 8, 12)]
    assert all(b > a for a, b in zip(up, up[1:])) and all(b < a for a, b in zip(down, down[1:]))


# =============================================================================================================================
# Part B - the default generator (consensus_reference.build) on the shared synthetic company of test_throughcycle_reference (EST: base
# owner earnings $1.1B, X $1.2B, revenue $10B, 500M shares, coe 9%, anchor 3.75%), with a record of its own.
# =============================================================================================================================

REC = {"R_tc": 0.20, "ronic_t": 0.15, "om_trend": 0.12, "om_L": 0.15, "om_tc": 0.13, "om_shape": "trend",
       "om_basis": "with_amortization", "x_L": 0.12, "tax_L": 0.21, "nwc_intensity": 0.10, "stamps": []}


def ref(**kw):
    a = dict(base_cf=1.1 * B, estimates=EST, coe=COE, terminal_g=GA, shares=500e6, median_5y=MEDIAN5, record=REC, base_ni=1.2 * B,
             base_revenue=10 * B, anchor=GA)
    a.update(kw)
    out = cr.build(**a)
    assert out["value"] is not None, out
    return out


def facts_of(r, rec=REC, coe=COE, tg=GA, shares=500e6, stub=None, excess=None):
    """The facts the pack derives from a reference, at full precision (the pack quantizes them; test_rev19 proves that to the cent)."""
    lr = r["long_run"]
    return {"coe_anchor": coe, "terminal_g_default": tg, "shares_default": shares, "terminal_ronic": rec["ronic_t"],
            "long_run": {"e5": lr["e5"] / B, "oe5": lr["oe5"] / B, "m5": lr["m5"], "margin_ratio": r["margin_ratio"], "r_tc": rec["R_tc"],
                         "stub_months": stub},
            "working_capital": [x / B for x in r["wc"]] if r["wc"] else None, "excess_cash": excess}


def test_the_desk_on_the_defaults_is_the_default_generator_to_machine_precision():
    """The two paths share the long-run arithmetic (consensus_reference.long_run_value). Restated by revision 24 step 2a (ruling 1): the desk no
    longer inherits the generator's margin ratio (defaults_desk_args drops it and the desk does not read it); given the generator's own long-run
    margin m_long as its long_run_margin, the desk's value on full-precision facts is the reference's to 1e-12 (m_long / (e5 / revenue_5) is the
    generator's ratio). Without one, the DEFAULTS run holds the year-5 margin. 37.544753 is the reference after D4 (ronic_at moves the charge
    1 / RONIC linearly from RONIC_0 20% to RONIC_T 15%, a lower return in years 6-9 than the old linear move in RONIC, which gave 37.573360)."""
    r = ref()
    args, why = cr.defaults_desk_args(r, facts_of(r))
    assert why is None and "margin_ratio" not in args["long_run"]
    held = fmt.unbundled_dcf(**args)
    assert held["long_run"]["margin_ratio"] is None and held["per_share_iv_raw"] > r["value"]          # the generator's ratio 0.744727 < 1
    assert fmt.unbundled_dcf(**args, long_run_margin=r["m_long"])["per_share_iv_raw"] == pytest.approx(r["value"], rel=1e-12)
    assert round(r["value"], 6) == 37.544753


def test_the_generator_long_run_margin_by_hand():
    """margin_rule on REC with m5 = e5 / revenue5 = 12.9309%: OM_5 = 15% + (12.9309% - 12%) / 0.79 = 16.1784%; m_long = 12.9309% + 0.79 x
    (12% - 16.1784%) = 9.63%; ratio 0.744727."""
    r = ref()
    assert r["long_run"]["m5"] == pytest.approx(0.129309, abs=1e-6)
    assert r["om_5"] == pytest.approx(0.15 + (r["long_run"]["m5"] - 0.12) / 0.79, rel=1e-12)
    assert r["m_long"] == pytest.approx(0.0963, abs=1e-12) and r["margin_ratio"] == pytest.approx(0.0963 / r["long_run"]["m5"], rel=1e-12)


def test_the_generator_long_run_margin_rises_with_the_record_trend_and_plateaus_at_its_floor():
    """om_trend -5% .. 30%: value non-decreasing and positive; below 0 the target is floored at 0 and the value is flat (14.179302;
    14.196165 before revision 24 step 2a's D4 change to ronic_at)."""
    vals = [ref(record=dict(REC, om_trend=t))["value"] for t in (-0.05, 0.0, 0.05, 0.10, 0.12, 0.15, 0.20, 0.30)]
    assert vals[0] == vals[1] and all(b > a for a, b in zip(vals[1:], vals[2:])) and all(v > 0 for v in vals)


def test_the_generator_terminal_growth_ronic_working_capital_and_rate_move_value_the_intended_way():
    tg = [ref(terminal_g=g)["value"] for g in (0.0, 0.02, 0.03, 0.0375, 0.05, 0.08)]
    ronic = [ref(record=dict(REC, R_tc=x, ronic_t=x))["value"] for x in (0.09, 0.12, 0.20, 0.50, INF)]
    nwc = [ref(record=dict(REC, nwc_intensity=n))["value"] for n in (-0.2, 0.0, 0.1, 0.3)]
    rate = [ref(coe=c, record=dict(REC, ronic_t=max(c, 0.15)))["value"] for c in (0.06, 0.08, 0.09, 0.11, 0.14)]
    assert all(b > a for a, b in zip(tg, tg[1:]))                    # 31.92 .. 94.02 (31.93 .. 94.07 before the D4 change)
    assert all(b > a for a, b in zip(ronic, ronic[1:]))
    assert all(b < a for a, b in zip(nwc, nwc[1:]))                  # 39.30 .. 36.37 (39.33 .. 36.40)
    assert all(b < a for a, b in zip(rate, rate[1:]))                # 82.59 .. 20.59 (82.62 .. 20.61)
    assert min(tg + ronic + nwc + rate) > 0


def test_the_generator_working_capital_is_intensity_times_the_revenue_change():
    """wc_t = nwc x (rev_t - rev_{t-1}): years 1-2 from the vendor's revenue, 10.0 -> 10.8 -> 11.6: 0.10 x 0.8B = $80M each."""
    r = ref()
    assert r["wc"][:2] == pytest.approx([80e6, 80e6])
    assert r["wc"] == pytest.approx([0.10 * (r["revenue"][t] - r["revenue"][t - 1]) for t in range(1, 6)])


def test_the_generator_cash_term_adds_cash_at_face_and_takes_its_interest_out_of_earnings():
    """Cash $2B at a 4% bill rate, tax 21%: i_L = 2B x 0.04 x 0.79 = $63.2M. Value = the value on base_cf - i_L and X - i_L (x_L recomputed
    the same way) + $2B / 500M = + $4.00 a share."""
    row = {"cash": 2 * B, "st_investments": None, "pretax_income": 100.0, "tax_provision": 21.0}
    cash = cr.cash_term(row, 0.04, "Technology")
    assert cash["interest"] == pytest.approx(63.2e6)
    with_cash = ref(cash=cash)["value"]
    i = 63.2e6
    no_cash = ref(base_cf=1.1 * B - i, base_ni=1.2 * B - i, record=dict(REC, x_L=(1.2 * B - i) / (10 * B)))["value"]
    assert with_cash == pytest.approx(no_cash + 4.0, rel=1e-12)


# =============================================================================================================================
# Part C - O2: the operating-to-earnings margin translation.
# =============================================================================================================================

def test_o2_the_consensus_year5_margin_cancels_out_of_the_long_run_margin():
    """By hand from margin_rule: m_long = m5 + (1-t)(target - OM_5) with OM_5 = om_L + (m5 - x_L)/(1-t)
    = m5 + (1-t) target - (1-t) om_L - m5 + x_L = x_L + (1 - tax_L)(target - om_L).
    The consensus year-5 margin m5 does not enter the long-run LEVEL; it enters only the ratio m_long / m5 the desk applies. The level is the
    base year's filed earnings margin x_L shifted by the operating-margin change from the base year to the trend: whatever the base year's
    earnings margin holds that its operating margin does not (interest, a non-operating gain or loss, a one-off) is carried forever, in margin
    points."""
    rec = {"om_trend": 0.12, "om_L": 0.15, "x_L": 0.12, "tax_L": 0.21}
    for m5 in (0.05, 0.10, 0.129309, 0.20, 0.30):
        rule = cr.margin_rule(rec, m5)
        assert rule["m_long"] == pytest.approx(0.12 + 0.79 * (0.12 - 0.15), abs=1e-12)     # 9.63% for every m5


def lite_like(x_L=-2.30, om_trend=0.044):
    """LITE-like (levels method; the base year's EPS base is negative). Base year: revenue $3.0B, operating margin 22% (om_L), net income
    -$6.9B from a $7.4B non-operating loss, so the filed earnings margin x_L = -230%. Consensus EPS $10 then $18 on 0.1B shares, revenue $4.5B
    then $7.0B: m5 = 18 x 0.1 / 7.0 = 25.714% (the vendor's EPS basis, `levels_eps_basis`). Trend operating margin 4.4%."""
    est = {"0y": {"revenue": {"avg": 4.5 * B, "analysts": 10, "growth": 0.5, "year_ago": 3.0 * B},
                  "eps": {"avg": 10.0, "low": 9.0, "high": 11.0, "analysts": 10, "growth": None, "year_ago": -69.35}},
           "+1y": {"revenue": {"avg": 7.0 * B, "analysts": 10, "growth": 0.5556, "year_ago": 4.5 * B},
                   "eps": {"avg": 18.0, "low": 15.0, "high": 21.0, "analysts": 10, "growth": 0.8, "year_ago": 10.0}}}
    rec = {"R_tc": INF, "ronic_t": INF, "om_trend": om_trend, "om_L": 0.22, "om_tc": 0.09, "om_shape": "swing",
           "om_basis": "with_amortization", "x_L": x_L, "tax_L": 0.21, "nwc_intensity": 0.15, "stamps": []}
    r = cr.build(base_cf=-7.1 * B, estimates=est, coe=0.105, terminal_g=0.0236, shares=0.1e9, median_5y=0.056, da=0.265 * B,
                 capex=0.451 * B, record=rec, base_ni=-6.9 * B, base_revenue=3.0 * B, anchor=0.0375)
    return r, rec


def test_o2_reproduced_lite_like_an_impossible_operating_margin_and_a_zero_long_run_margin():
    """OM_5 = 22% + (25.714% + 230%) / 0.79 = 345.69% of revenue. m_long = max(0, -230% + 0.79 x (4.4% - 22%)) = max(0, -243.9%) = 0.
    The generator's earnings fade to zero over years 6-10 and its terminal value is 0. Revision 24 step 2a (ruling 5): the benchmark stamps
    both (it stamped neither); no `margin_rule_` stamp, so neither reaches the pack's printed stamps."""
    r, rec = lite_like()
    assert r["method"] == "levels" and r["long_run"]["m5"] == pytest.approx(18 * 0.1 / 7.0)
    assert r["om_5"] == pytest.approx(0.22 + (18 * 0.1 / 7.0 + 2.30) / 0.79, rel=1e-12)    # 3.456890
    assert r["om_5"] > 1.0
    assert r["m_long"] == 0.0 and r["margin_ratio"] == 0.0
    assert r["long_run"]["tv"] == 0.0 and r["long_run"]["earnings"][-1] == 0.0
    assert {"implied_operating_margin_out_of_range", "long_run_margin_clamped_to_zero"} <= set(r["stamps"])
    assert not [s for s in r["stamps"] if s.startswith("margin_rule")]


def test_o2_lite_like_the_desk_no_longer_inherits_the_zero_and_takes_the_analysts_long_run_margin():
    """Restated by revision 24 step 2a (ruling 1; it reproduced a desk that took the generator's margin_ratio 0 and had no input to change it).
    On the generator's facts, without a long_run_margin the desk holds the year-5 margin and its terminal value is positive; given the
    generator's m_long (0) it returns the generator's value with a terminal value of 0 (the shared arithmetic); given an analyst-style 15% it
    has a positive long run. The tool schema now has long_run_margin."""
    r, rec = lite_like()
    f = facts_of(r, rec=rec, coe=0.105, tg=0.0236, shares=0.1e9)
    args, why = cr.defaults_desk_args(r, f)
    held = fmt.unbundled_dcf(**args)
    assert held["long_run"]["margin_ratio"] is None and held["terminal_value_nominal"] > 0
    zero = fmt.unbundled_dcf(**args, long_run_margin=r["m_long"])
    assert zero["per_share_iv_raw"] == pytest.approx(r["value"], rel=1e-12) and zero["terminal_value_nominal"] == 0
    analyst = fmt.unbundled_dcf(**args, long_run_margin=0.15)
    assert analyst["terminal_value_nominal"] > 0 and analyst["per_share_iv_raw"] > r["value"]
    assert analyst["long_run"]["margin_ratio"] == pytest.approx(0.15 / r["long_run"]["m5"], abs=5e-5)
    props = _desk_schema_properties()
    assert {"base_cf", "explicit_growth", "fade_years", "terminal_g", "terminal_ronic", "wacc", "excess_cash", "long_run_margin"} <= props


def _desk_schema_properties():
    """Every property name anywhere in the run_financial_model tool's parameter schema (analyst_tools.TOOLS)."""
    out = set()
    for t in at.TOOLS:
        fn = t["function"]
        if fn["name"] == "run_financial_model":
            stack = [fn.get("parameters", {})]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    out.update((node.get("properties") or {}).keys())
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
    assert out, "the desk tool's schema was not found"
    return out


def lind_like(om_trend=0.12):
    """LIND-like (the gap between the operating and the earnings margin is larger than the earnings margin): om_L 15%, x_L 2%, tax 21%, so
    the base year's wedge om_L - x_L / (1 - tax_L) = 15% - 2.53% = 12.47 points (interest, amortization); consensus m5 3%, trend 12%."""
    return {"om_trend": om_trend, "om_L": 0.15, "x_L": 0.02, "tax_L": 0.21}


def test_o2_reproduced_lind_like_a_modest_operating_margin_fall_zeroes_the_earnings():
    """OM_5 = 15% + (3% - 2%) / 0.79 = 16.266%; the operating margin falls to 12% (-26% relative); m_long = max(0, 2% + 0.79 x (12% - 15%))
    = max(0, -0.37%) = 0. A proportional rule (m5 x 12% / 16.266%) would keep 2.21%. The additive rule is right only if the 12.47-point wedge
    is a fixed cost in margin points forever; it is one base year's wedge."""
    rule = cr.margin_rule(lind_like(), 0.03)
    assert rule["om_5"] == pytest.approx(0.15 + 0.01 / 0.79, rel=1e-12)
    assert rule["m_long"] == 0.0 and rule["ratio"] == 0.0 and rule["stamps"] == ["long_run_margin_clamped_to_zero"]    # revision 24 step 2a


def _saved(name):
    return json.loads((FIX / f"{name}_pack_facts.json").read_text(encoding="utf-8"))


def _saved_desk(f, fade_years=5, **kw):
    """The desk on a saved facts file's DEFAULTS (the reference's base, path, rate, terminal growth, return, working capital and cash)."""
    return fmt.unbundled_dcf(base_cf=f["reference_base_b"], explicit_growth=f["reference_path"], wacc=f["coe_anchor"],
                             terminal_g=f["terminal_g_default"], shares_diluted=f["shares_default"] / 1e9, fade_years=fade_years,
                             sbc_treatment="deducted_in_cf", terminal_ronic=f["terminal_ronic"], long_run=f["long_run"],
                             working_capital=f["working_capital"], excess_cash=f["excess_cash"], **kw)


@pytest.mark.parametrize("name, civ", [("LITE_20261006_145640", 271.20), ("LIND_20261006_133708", 9.53)])
def test_o2_reproduced_on_the_saved_facts_the_desk_on_the_defaults_returns_the_reference_with_a_zero_long_run_margin(name, civ):
    """The two saved baseline facts files (verbatim). Restated by revision 24 step 2a (ruling 1): the desk no longer reads the facts'
    margin_ratio 0; given the generator's own m_long (0) as its long_run_margin, the desk on their DEFAULTS still returns the
    CONSENSUS-IMPLIED VALUE to the cent with a terminal value of 0 (everything after year 10 worth nothing): the arithmetic is shared, and the
    zero is the generator's margin, not the desk's."""
    f = _saved(name)
    lr = f["long_run"]
    d = _saved_desk(f, long_run_margin=lr["m_long"])
    assert f["consensus_implied_value"] == civ and d["per_share_iv"] == civ
    assert lr["margin_ratio"] == 0.0 and lr["m_long"] == 0.0 and d["terminal_value_nominal"] == 0
    assert not [s for s in lr["stamps"] if s.startswith("margin_rule")]
    assert _saved_desk(f)["long_run"]["margin_ratio"] is None                     # the facts' margin_ratio 0 does not reach the desk


@pytest.mark.parametrize("name, margin, value, tv", [("LITE_20261006_145640", 0.15, 594.32, 60.93), ("LIND_20261006_133708", 0.04, 14.72, 0.71)])
def test_the_saved_facts_with_an_analyst_style_long_run_margin_have_a_positive_long_run(name, margin, value, tv):
    """Revision 24 step 2a (ruling 6): LITE and LIND on their saved DEFAULTS with an analyst-style long_run_margin (15% and 4%): a positive
    long run. LITE's year-5 earnings margin 31.58% (e5 6.812241 / revenue 21.5712) moves to 15% (ratio 0.475) by year 10: $594.32, terminal
    value $60.93B (the reference: $271.20 with a terminal value of 0). LIND's 2.76% moves up to 4% (ratio 1.4473): $14.72, terminal value $0.71B
    (the reference: $9.53, 0). At the end of the fade the earnings margin is the long_run_margin."""
    f = _saved(name)
    d = _saved_desk(f, long_run_margin=margin)
    assert d["per_share_iv"] == value and d["terminal_value_nominal"] == tv and d["terminal_value_nominal"] > 0
    lr = f["long_run"]
    assert d["long_run"]["margin_ratio"] == pytest.approx(margin / lr["m5"], abs=1e-4)   # the Base is on the facts' own path: E5 / revenue_5 = m5
    assert d["per_share_iv"] > f["consensus_implied_value"]


@pytest.mark.parametrize("name", ["LITE_20261006_145640", "LIND_20261006_133708"])
@pytest.mark.parametrize("tax_L", [0.0, 0.10, 0.21, 0.35])
def test_o2_reproduced_on_the_saved_facts_for_every_admissible_tax_rate(name, tax_L):
    """The facts carry om_L, om_5, m5 and om_trend, not x_L or tax_L. For any tax_L in [0, 35%] (throughcycle_record.TAX_MAX), x_L =
    m5 - (om_5 - om_L)(1 - tax_L) reproduces om_5 exactly, and m_long = x_L + (1 - tax_L)(om_trend - om_L) < 0 is clamped to 0.
    LITE: om_5 352.07%, x_L between -298.6% (tax 0) and -183.0% (tax 35%), the base year's -$6.94B net income on $3.01B revenue.
    LIND: om_5 13.87%, x_L between -4.87% and -2.20%, a loss year. The zero does not depend on the unknown tax rate."""
    lr = _saved(name)["long_run"]
    x_L = lr["m5"] - (lr["om_5"] - lr["om_L"]) * (1 - tax_L)
    rule = cr.margin_rule({"om_trend": lr["om_trend"], "om_L": lr["om_L"], "x_L": x_L, "tax_L": tax_L, "om_basis": lr["om_basis"]}, lr["m5"])
    assert rule["om_5"] == pytest.approx(lr["om_5"], abs=1e-9)
    assert x_L + (1 - tax_L) * (lr["om_trend"] - lr["om_L"]) < 0
    assert rule["m_long"] == 0.0 and rule["ratio"] == 0.0


def test_o2_an_impossible_implied_operating_margin_is_annotated():
    """Was a strict xfail (O2a). Revision 24 step 2a (ruling 5): the benchmark stamps an implied year-5 operating margin outside [-50%, 100%]
    `implied_operating_margin_out_of_range` (the brief's name; the audit's `margin_rule` prefix would have printed it in the pack's DEFAULTS
    stamps, and the stamp is benchmark only). An in-range one is not stamped."""
    r, _ = lite_like()
    assert r["om_5"] > 1.0
    assert "implied_operating_margin_out_of_range" in r["stamps"] and "implied_operating_margin_out_of_range" in r["margin"]["stamps"]
    assert "implied_operating_margin_out_of_range" not in cr.margin_rule(lind_like(), 0.03)["stamps"]       # OM_5 16.27%
    low = cr.margin_rule({"om_trend": 0.05, "om_L": -0.40, "x_L": -0.80, "tax_L": 0.0}, 0.05)                 # OM_5 = -40% + 85% = 45%: in range
    assert "implied_operating_margin_out_of_range" not in low["stamps"]
    below = cr.margin_rule({"om_trend": 0.05, "om_L": -0.60, "x_L": 0.05, "tax_L": 0.0}, 0.04)                 # OM_5 -61%: a loss, stamped
    assert below["om_5"] == pytest.approx(-0.61) and "implied_operating_margin_out_of_range" in below["stamps"]


def test_o2_a_long_run_margin_clamped_to_zero_is_stamped():
    """Was a strict xfail (O2b). Revision 24 step 2a (ruling 5): the clamp of a negative long-run earnings margin to 0 is stamped
    `long_run_margin_clamped_to_zero` (benchmark only); a margin at or above 0 is not."""
    rule = cr.margin_rule(lind_like(), 0.03)
    assert rule["m_long"] == 0.0
    assert rule["stamps"] == ["long_run_margin_clamped_to_zero"], "the clamp to zero must be annotated"
    assert cr.margin_rule(lind_like(om_trend=0.20), 0.03)["stamps"] == []


def test_o2_a_base_year_non_operating_one_off_does_not_set_the_long_run_margin():
    """Was a strict xfail (O2c). Same operating record, same consensus (levels method: m5 = 25.714% comes from the vendor's EPS and does not hold
    the base year's one-off). Base year with and without a $7.4B non-operating loss (x_L -230% against +16.7%), trend 20%. Revision 24 step 2a
    (ruling 1): the long-run margin that values the company is the analyst's long_run_margin, which no base-year figure sets, so the desk on
    either case's facts with the same long_run_margin gives the same value and the same long-run margin. The generator's m_long (the logged
    benchmark only) still carries the one-off, x_L + (1 - tax_L)(om_trend - om_L): 15.12% without it, -231.6% clamped to 0 (stamped) with it."""
    clean, crec = lite_like(x_L=0.167, om_trend=0.20)
    one_off, orec = lite_like(x_L=-2.30, om_trend=0.20)
    assert clean["m_long"] == pytest.approx(0.167 + 0.79 * (0.20 - 0.22), rel=1e-9)
    assert one_off["m_long"] == 0.0 and "long_run_margin_clamped_to_zero" in one_off["stamps"]       # the benchmark keeps the defect, stamped
    runs = []
    for r, rec in ((clean, crec), (one_off, orec)):
        args, why = cr.defaults_desk_args(r, facts_of(r, rec=rec, coe=0.105, tg=0.0236, shares=0.1e9))
        assert why is None
        runs.append(fmt.unbundled_dcf(**args, long_run_margin=0.15))
    assert runs[0]["per_share_iv_raw"] == pytest.approx(runs[1]["per_share_iv_raw"], rel=1e-12)
    assert runs[0]["long_run"]["margin_ratio"] == runs[1]["long_run"]["margin_ratio"] and runs[0]["terminal_value_nominal"] > 0


# =============================================================================================================================
# Part D - other arithmetic defects in the desk's own path.
# =============================================================================================================================

def _margin_lr(m):
    """The desk arguments that give the margin ratio m on S growing 3% a year (revision 24 step 2a: a long_run_margin, where the audit passed
    the facts' margin_ratio): facts e5 = oe5 = 1.03^5 and m5 10%, so S's year-5 earnings margin is 10% and long_run_margin = m x 10%; m None
    passes no long_run_margin (the margin held)."""
    return {"long_run": {"e5": 1.03 ** 5, "oe5": 1.03 ** 5, "m5": 0.10}, "long_run_margin": None if m is None else m * 0.10}


def test_d2_reproduced_a_fade_of_zero_drops_the_long_run_margin():
    """Restated by revision 24 step 2a (D2; it reproduced k_end = 1 at F = 0, which valued the long run at the year-5 margin, 14.714286). S
    growing 3% a year, margin ratio 0.5, g5 = gt = 3% (the fade changes no growth), RONIC unlimited: PV of years 1-5 = sum 1.03^t / 1.1^t =
    4.122678; OE5 = 1.03^5 = 1.159274; F = 1: long run = 0.5 x 1.159274 x 1.03 / 0.07 / 1.1^5 = 5.295804, value 9.418482; F = 0 now applies the
    ratio in the terminal year: the same 9.418482 (with g6 = gt and the ratio reached in year 6, a one-year fade is the terminal year)."""
    f1 = desk(fade_years=1, explicit_growth=[0.03] * 5, **_margin_lr(0.5))
    f0 = desk(fade_years=0, explicit_growth=[0.03] * 5, **_margin_lr(0.5))
    oe5 = 1.03 ** 5
    pv15 = sum(1.03 ** t / d for t, d in zip(range(1, 6), D5))
    assert f1["per_share_iv_raw"] == pytest.approx(pv15 + 0.5 * oe5 * 1.03 / 0.07 / 1.1 ** 5, rel=1e-12)
    assert f0["per_share_iv_raw"] == pytest.approx(pv15 + 0.5 * oe5 * 1.03 / 0.07 / 1.1 ** 5, rel=1e-12)
    assert f0["long_run"]["margin_ratio"] == 0.5


def test_d2_the_long_run_margin_applies_whatever_the_fade_length():
    """Was a strict xfail (D2). With g5 = gt the fade moves no growth, so with a margin ratio below 1 a longer fade (a slower fall in margin) can
    only raise value, and a fade of 0 (the margin at its long-run level from the terminal year) must not be worth more than a fade of 1."""
    vals = [iv(fade_years=f, explicit_growth=[0.03] * 5, **_margin_lr(0.5)) for f in (0, 1, 2, 5)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))


def test_d2_fewer_explicit_rates_do_not_drop_the_long_run_margin():
    """Was a strict xfail (D2, the second route): two explicit rates with fade_years 3 leave no fade for the long run (_five_and_fade gives
    0); the margin ratio now still applies, in the terminal year."""
    a = iv(explicit_growth=[0.05, 0.05], fade_years=3, terminal_ronic=0.20, **_margin_lr(0.5))
    b = iv(explicit_growth=[0.05, 0.05], fade_years=3, terminal_ronic=0.20, **_margin_lr(None))
    assert a < b


def test_d3_positive_scenario_owner_earnings_keep_positive_long_run_earnings():
    """Was a strict xfail (D3). Facts e5 0.6, oe5 1.0 (D&A above capex: earnings 60% of owner earnings). A Bear at 35% of the owner earnings:
    additively E5 = 0.6 + (0.35 - 1.0) = -0.05, a negative long run floored at 0; proportionally (revision 24 step 2a) E5 = 0.6 x 0.35 = 0.21."""
    r = desk(base_cf=0.35, long_run={"e5": 0.6, "oe5": 1.0}, fade_years=5, terminal_ronic=0.20)
    assert r["long_run"]["year5_earnings"] == pytest.approx(0.21, abs=5e-5)
    assert r["long_run"]["year5_earnings"] > 0 and "long_run_floor" not in r["stamps"]


def test_d4_reproduced_an_unlimited_terminal_ronic_holds_the_starting_ronic_through_the_fade():
    """Restated by revision 24 step 2a (D4; it reproduced the start held until frac 1, a year-6 flow of 0.721 unlimited against 1.03 at 10^12).
    ronic_at now moves the charge 1 / RONIC linearly, an unlimited return being a charge of 0. long_run_value with e5 1.0, g5 = gt = 3%, r 10%,
    RONIC_0 = 10%, a two-year fade. Year 6 (frac 0.5): 1 / RONIC = 0.5 x 10 = 5, RONIC 20%, flow 1.03 x (1 - 0.03 / 0.20) = 0.8755 whether RONIC_T
    is unlimited or 10^12; year 7 and the terminal charge nothing: the unlimited return is the limit of a large finite one."""
    unl = cr.long_run_value(1.0, 0.03, 0.03, 0.10, 0.10, INF, None, 2)
    fin = cr.long_run_value(1.0, 0.03, 0.03, 0.10, 0.10, 1e12, None, 2)
    assert unl["flows"][0] == pytest.approx(0.8755, abs=1e-12) and fin["flows"][0] == pytest.approx(0.8755, abs=1e-9)
    assert unl["flows"][1] == pytest.approx(1.03 ** 2, abs=1e-12)
    assert fin["value"] - unl["value"] == pytest.approx(0.0, abs=1e-9)
    assert cr.ronic_at(0.10, INF, 0.25) == pytest.approx(1 / 7.5) and cr.ronic_at(0.10, INF, 0.75) == pytest.approx(0.40)


def test_d4_value_is_monotone_in_terminal_ronic_up_to_unlimited():
    """Was a strict xfail (D4): $16.23 unlimited against $17.39 at 10^6. Now monotone, and unlimited is the limit (equal to 10^6 within half a
    cent)."""
    vals = [iv(terminal_ronic=x, fade_years=5, explicit_growth=[0.06] * 5) for x in (0.50, 1.0, 1e6, INF)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))
    assert vals[3] - vals[2] < 0.005


def test_d4_the_price_implied_terminal_ronic_block_has_no_self_made_discontinuity():
    """Was a strict xfail (D4, its reach). A Base on S with growth 6% for five years, a five-year fade, terminal_ronic 15%, the record's r_tc 30%
    (RONIC_0 30%). The price is $17.00 (the audit's $17.20 lay inside the jump the old rule made; the value now rises continuously to $17.17 at
    unlimited, so $17.20 is above the bound and $17.00 is reachable)."""
    lr = {"r_tc": 0.30}
    b = dict(cf=1.0, growth=[0.06] * 5, fade=5, wacc=0.10, tg=0.03, shares=1.0, sbc="deducted_in_cf", sbc_dil=None, frame="equity",
             net_debt=None, rate_type=None, annuity=0.0, annuity_cap=None, ronic=0.15, wc=None, excess=None, long_run=lr, finite=None)
    b["raw"] = iv(terminal_ronic=0.15, fade_years=5, explicit_growth=[0.06] * 5, long_run=lr)
    blk = fmt.price_implied(b, 17.00)["terminal_ronic"]
    assert blk["reachable"] and blk["base_at_value"] == pytest.approx(17.00, abs=1e-6)
    assert "discontinuity" not in blk["stamps"] and blk["discontinuities"] == 0 and blk["roots_on_grid"] == 1
    assert blk["bound"]["value_high"] >= blk["base_at_value"]
    above = fmt.price_implied(b, 17.20)["terminal_ronic"]
    assert not above["reachable"] and above["side"] == "above" and "discontinuity" not in above["stamps"]


def test_d2_reproduced_on_the_saved_lite_facts():
    """Restated by revision 24 step 2a (D2; it reproduced $768.81 at fade 0). The saved LITE DEFAULTS through the desk with the generator's
    m_long (0) as the long_run_margin, at fade 0, 1 and 5: $173.38, $173.38, $271.20 (the CONSENSUS-IMPLIED VALUE). A fade of 0 now applies the
    zero margin in the terminal year, as a fade of 1 does in year 6 (g6 = terminal growth either way)."""
    f = _saved("LITE_20261006_145640")
    vals = {fy: _saved_desk(f, fade_years=fy, long_run_margin=f["long_run"]["m_long"])["per_share_iv"] for fy in (0, 1, 5)}
    assert vals == {0: 173.38, 1: 173.38, 5: 271.20}


def test_the_desk_applies_the_analysts_long_run_margin_to_the_scenarios_own_year5_earnings_margin():
    """Restated by revision 24 step 2a (ruling 1; it was the facts' margin_ratio applied to an additive E5). Facts e5 0.8, oe5 1.0, m5 8%: the
    facts' year-5 revenue is 10.0. A scenario at twice the owner earnings has E5 = 1.6 (D3) on a year-5 revenue of 20.0 (scaled as its
    earnings are), so its year-5 earnings margin is 8% and long_run_margin 4% gives the ratio 0.5 in it as in a scenario at the facts' own
    owner earnings: the margin moves proportionally in every scenario. Terminal value (one-year fade, RONIC unlimited) 0.5 x 1.6 x 1.03 x 1.03
    / 0.07 = 4% x 20.0 x 1.03 x 1.03 / 0.07 = 12.12, twice the 6.06 of the scenario at the facts' own owner earnings."""
    lr = {"e5": 0.8, "oe5": 1.0, "m5": 0.08}
    r = desk(base_cf=2.0, long_run=lr, long_run_margin=0.04)
    assert r["long_run"]["margin_ratio"] == 0.5 and r["long_run"]["year5_earnings"] == pytest.approx(1.6)
    assert r["long_run"]["year5_revenue"] == 20.0 and r["long_run"]["long_run_margin"] == 0.04
    assert r["terminal_value_nominal"] == pytest.approx(0.04 * 20.0 * 1.03 * 1.03 / 0.07, abs=0.005)
    own = desk(base_cf=1.0, long_run=lr, long_run_margin=0.04)
    assert own["long_run"]["margin_ratio"] == 0.5 and own["long_run"]["year5_revenue"] == 10.0
    assert own["terminal_value_nominal"] == pytest.approx(r["terminal_value_nominal"] / 2, abs=0.005)
