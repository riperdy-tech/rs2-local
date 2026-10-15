"""Revision 24, step 1: the arithmetic audit of the desk and the default generator (brief BRIEF_R24_S1_desk_arithmetic_audit.md).

An audit: these tests change no code. Each input of the long run is checked for its intended effect on cash flow and per-share value on a
synthetic company, with the expected numbers computed by hand (the comments) and asserted as plain arithmetic independent of the code under
test; then for monotonicity and the absence of sign flips over its realistic range. O2 (the operating-to-earnings margin translation,
rev23/defect_census.md) is reproduced on synthetic LITE-like and LIND-like companies and on the two saved baseline facts files
(fixture_data/rev24_desk_audit/, copied verbatim from rs2-local/ab_reports/consensus/{LITE_20261006_145640,LIND_20261006_133708}/_pack_facts.json).

Every defect found is stated as the property it violates, in a test marked xfail(strict=True) with the reason: the suite stays clean, and a fix
turns the test into an XPASS, which strict mode reports, so the marker is removed with the fix. The coordinator rules on every fix.

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


def test_with_a_reference_the_scenario_year5_earnings_move_one_for_one_with_its_owner_earnings():
    """_long_run_inputs: E5 = e5 (facts) + (OE5 - oe5 (facts)), an ADDITIVE translation. Facts e5 0.8, oe5 1.0, margin held: base 1.0 gives
    E5 0.8; base 2.0 gives E5 0.8 + 1.0 = 1.8, not 1.6. Value: 2 x PV15 + 1.8 x 1.03 / 0.07 / 1.1^5 = 7.581574 + 16.445545 = 24.027119."""
    lr = {"e5": 0.8, "oe5": 1.0, "margin_ratio": None}
    assert desk(base_cf=1.0, long_run=lr)["long_run"]["year5_earnings"] == pytest.approx(0.8)
    assert desk(base_cf=2.0, long_run=lr)["long_run"]["year5_earnings"] == pytest.approx(1.8)
    assert iv(base_cf=2.0, long_run=lr) == pytest.approx(2 * PV15_FLAT + 1.8 * LR_S / 1.0, rel=1e-12)


def test_without_a_reference_the_same_translation_is_proportional():
    """The fallback (no reference e5 in the facts): E5 = OE5 x x_over_oe, proportional. Base 2.0, x_over_oe 0.8: E5 = 1.6. The desk therefore
    translates owner earnings to earnings additively with a reference and proportionally without one (see the D3 xfail below)."""
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


# ---- the long-run margin (the facts' margin_ratio) ----------------------------------------------------------------------------

def test_the_long_run_margin_scales_the_long_run_linearly():
    """margin_ratio m with a one-year fade: k6 = m and k_end = m, so the long run is m x 9.136414. m = 0.5: 3.790787 + 4.568207 = 8.358994;
    m = 1.2: 3.790787 + 10.963697 = 14.754483. A higher long-run margin raises value."""
    lr = lambda m: {"e5": 1.0, "oe5": 1.0, "margin_ratio": m}  # noqa: E731
    assert iv(long_run=lr(0.5)) == pytest.approx(PV15_FLAT + 0.5 * LR_S, rel=1e-12)
    assert iv(long_run=lr(1.2)) == pytest.approx(PV15_FLAT + 1.2 * LR_S, rel=1e-12)


def test_the_long_run_margin_is_monotone_and_never_flips_the_sign_of_a_flow():
    """margin_ratio over 0 .. 1.5 with a five-year fade: value non-decreasing; every flow >= 0; at 0 the terminal value is 0, not negative."""
    vals = []
    for m in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5):
        r = desk(long_run={"e5": 1.0, "oe5": 1.0, "margin_ratio": m}, fade_years=5, terminal_ronic=0.20)
        assert all(cf >= 0 for cf in r["projected_cfs"])
        vals.append(r["per_share_iv_raw"])
    assert all(b > a for a, b in zip(vals, vals[1:]))
    assert desk(long_run={"e5": 1.0, "oe5": 1.0, "margin_ratio": 0.0}, fade_years=5)["terminal_value_nominal"] == 0


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


def test_ronic_is_monotone_over_its_finite_range_and_a_value_below_r_is_valued_at_r():
    """RONIC over r .. 10^6: value strictly rising (an unlimited RONIC is D4 below). Observation (documented design, `max(r, RONIC)`): a
    terminal_ronic below r is valued as r and the result echoes the input unchanged, with no stamp."""
    vals = [iv(terminal_ronic=x, fade_years=5, explicit_growth=[0.06] * 5) for x in (0.10, 0.12, 0.20, 0.50, 1.0, 10.0, 1e6)]
    assert all(b > a for a, b in zip(vals, vals[1:])) and min(vals) > 0
    low = desk(terminal_ronic=0.05, fade_years=5, explicit_growth=[0.06] * 5)
    assert low["per_share_iv_raw"] == pytest.approx(vals[0], rel=1e-12)
    assert low["terminal_ronic"] == 0.05 and not [s for s in low["stamps"] if "ronic" in s]


def test_the_record_return_sets_the_starting_ronic_of_the_fade():
    """_long_run_inputs: RONIC_0 = max(r, r_tc). r_tc 40% against 12%: a higher start, a higher value; r_tc below r: the start is r."""
    base = dict(fade_years=5, explicit_growth=[0.08] * 5, terminal_ronic=0.12)
    lo = desk(long_run={"e5": None, "r_tc": 0.05}, **base)
    hi = desk(long_run={"e5": None, "r_tc": 0.40}, **base)
    at_r = desk(long_run={"e5": None, "r_tc": 0.10}, **base)
    assert lo["ronic_start"] == 0.10 and hi["ronic_start"] == 0.40
    assert lo["per_share_iv_raw"] == pytest.approx(at_r["per_share_iv_raw"], rel=1e-12)
    assert hi["per_share_iv_raw"] > at_r["per_share_iv_raw"]


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
            "long_run": {"e5": lr["e5"] / B, "oe5": lr["oe5"] / B, "margin_ratio": r["margin_ratio"], "r_tc": rec["R_tc"],
                         "stub_months": stub},
            "working_capital": [x / B for x in r["wc"]] if r["wc"] else None, "excess_cash": excess}


def test_the_desk_on_the_defaults_is_the_default_generator_to_machine_precision():
    """The two paths share the long-run arithmetic (consensus_reference.long_run_value) and the desk inherits the generator's margin ratio:
    on full-precision facts the desk's value is the reference's (37.573360) to 1e-12."""
    r = ref()
    args, why = cr.defaults_desk_args(r, facts_of(r))
    assert why is None
    assert fmt.unbundled_dcf(**args)["per_share_iv_raw"] == pytest.approx(r["value"], rel=1e-12)
    assert round(r["value"], 4) == 37.5734


def test_the_generator_long_run_margin_by_hand():
    """margin_rule on REC with m5 = e5 / revenue5 = 12.9309%: OM_5 = 15% + (12.9309% - 12%) / 0.79 = 16.1784%; m_long = 12.9309% + 0.79 x
    (12% - 16.1784%) = 9.63%; ratio 0.744727."""
    r = ref()
    assert r["long_run"]["m5"] == pytest.approx(0.129309, abs=1e-6)
    assert r["om_5"] == pytest.approx(0.15 + (r["long_run"]["m5"] - 0.12) / 0.79, rel=1e-12)
    assert r["m_long"] == pytest.approx(0.0963, abs=1e-12) and r["margin_ratio"] == pytest.approx(0.0963 / r["long_run"]["m5"], rel=1e-12)


def test_the_generator_long_run_margin_rises_with_the_record_trend_and_plateaus_at_its_floor():
    """om_trend -5% .. 30%: value non-decreasing and positive; below 0 the target is floored at 0 and the value is flat (14.196165)."""
    vals = [ref(record=dict(REC, om_trend=t))["value"] for t in (-0.05, 0.0, 0.05, 0.10, 0.12, 0.15, 0.20, 0.30)]
    assert vals[0] == vals[1] and all(b > a for a, b in zip(vals[1:], vals[2:])) and all(v > 0 for v in vals)


def test_the_generator_terminal_growth_ronic_working_capital_and_rate_move_value_the_intended_way():
    tg = [ref(terminal_g=g)["value"] for g in (0.0, 0.02, 0.03, 0.0375, 0.05, 0.08)]
    ronic = [ref(record=dict(REC, R_tc=x, ronic_t=x))["value"] for x in (0.09, 0.12, 0.20, 0.50, INF)]
    nwc = [ref(record=dict(REC, nwc_intensity=n))["value"] for n in (-0.2, 0.0, 0.1, 0.3)]
    rate = [ref(coe=c, record=dict(REC, ronic_t=max(c, 0.15)))["value"] for c in (0.06, 0.08, 0.09, 0.11, 0.14)]
    assert all(b > a for a, b in zip(tg, tg[1:]))                    # 31.93 .. 94.07
    assert all(b > a for a, b in zip(ronic, ronic[1:]))
    assert all(b < a for a, b in zip(nwc, nwc[1:]))                  # 39.33 .. 36.40
    assert all(b < a for a, b in zip(rate, rate[1:]))                # 82.62 .. 20.61
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
    The earnings fade to zero over years 6-10 and the terminal value is 0. No stamp records either."""
    r, rec = lite_like()
    assert r["method"] == "levels" and r["long_run"]["m5"] == pytest.approx(18 * 0.1 / 7.0)
    assert r["om_5"] == pytest.approx(0.22 + (18 * 0.1 / 7.0 + 2.30) / 0.79, rel=1e-12)    # 3.456890
    assert r["om_5"] > 1.0
    assert r["m_long"] == 0.0 and r["margin_ratio"] == 0.0
    assert r["long_run"]["tv"] == 0.0 and r["long_run"]["earnings"][-1] == 0.0
    assert not [s for s in r["stamps"] if s.startswith("margin_rule")]


def test_o2_reproduced_lite_like_the_desk_inherits_the_zero_and_has_no_input_to_change_it():
    """The desk computes no margin of its own: on the generator's facts it reproduces the value and its terminal value is 0. Its tool schema has
    no long-run margin input (only the facts' margin_ratio reaches long_run_value), so no briefing text can move it; only base_cf, the growth
    rates, the fade, terminal_g, terminal_ronic, wacc, excess_cash and the share count reach the desk."""
    r, rec = lite_like()
    f = facts_of(r, rec=rec, coe=0.105, tg=0.0236, shares=0.1e9)
    args, why = cr.defaults_desk_args(r, f)
    d = fmt.unbundled_dcf(**args)
    assert d["per_share_iv_raw"] == pytest.approx(r["value"], rel=1e-12)
    assert d["terminal_value_nominal"] == 0 and d["long_run"]["margin_ratio"] == 0.0
    props = _desk_schema_properties()
    assert {"base_cf", "explicit_growth", "fade_years", "terminal_g", "terminal_ronic", "wacc", "excess_cash"} <= props
    assert not [p for p in props if "margin" in p or p == "long_run"]


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
    assert rule["m_long"] == 0.0 and rule["ratio"] == 0.0 and rule["stamps"] == []


def _saved(name):
    return json.loads((FIX / f"{name}_pack_facts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name, civ", [("LITE_20261006_145640", 271.20), ("LIND_20261006_133708", 9.53)])
def test_o2_reproduced_on_the_saved_facts_the_desk_on_the_defaults_returns_the_reference_with_a_zero_long_run_margin(name, civ):
    """The two saved baseline facts files (verbatim). The desk on their DEFAULTS returns the CONSENSUS-IMPLIED VALUE to the cent, with
    margin_ratio 0 and a terminal value of 0: everything after year 10 is worth nothing."""
    f = _saved(name)
    lr = f["long_run"]
    d = fmt.unbundled_dcf(base_cf=f["reference_base_b"], explicit_growth=f["reference_path"], wacc=f["coe_anchor"],
                          terminal_g=f["terminal_g_default"], shares_diluted=f["shares_default"] / 1e9, fade_years=5,
                          sbc_treatment="deducted_in_cf", terminal_ronic=f["terminal_ronic"], long_run=lr,
                          working_capital=f["working_capital"], excess_cash=f["excess_cash"])
    assert f["consensus_implied_value"] == civ and d["per_share_iv"] == civ
    assert lr["margin_ratio"] == 0.0 and lr["m_long"] == 0.0 and d["terminal_value_nominal"] == 0
    assert not [s for s in lr["stamps"] if s.startswith("margin_rule")]


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


@pytest.mark.xfail(strict=True, reason="O2 defect: margin_rule accepts an implied year-5 operating margin above 100% of revenue (LITE "
                                       "352.07%) without a stamp or a refusal; non-negotiable 3 asks for an annotation")
def test_o2_an_impossible_implied_operating_margin_is_annotated():
    r, _ = lite_like()
    assert r["om_5"] > 1.0
    assert [s for s in r["stamps"] if s.startswith("margin_rule")]


@pytest.mark.xfail(strict=True, reason="O2 defect: margin_rule clamps a negative long-run earnings margin to 0 (max(0, ...)) with no stamp, "
                                       "so the zeroed long run of LITE and LIND carries no annotation (their saved stamps are empty)")
def test_o2_a_long_run_margin_clamped_to_zero_is_stamped():
    rule = cr.margin_rule(lind_like(), 0.03)
    assert rule["m_long"] == 0.0
    assert rule["stamps"], "the clamp to zero must be annotated"


@pytest.mark.xfail(strict=True, reason="O2 defect: a non-operating one-off in the base year (x_L moves, om_L does not) moves the long-run "
                                       "earnings margin one for one: m_long = x_L + (1 - tax_L)(om_trend - om_L); the consensus year-5 margin "
                                       "does not enter it")
def test_o2_a_base_year_non_operating_one_off_does_not_set_the_long_run_margin():
    """Same operating record, same consensus (levels method: m5 = 25.714% comes from the vendor's EPS and does not hold the base year's one-off).
    Base year with and without a $7.4B non-operating loss (x_L -230% against +16.7%): the long-run margin should not differ. With a trend of 20%
    so that neither case is clamped: without the one-off m_long = 16.7% + 0.79 x (20% - 22%) = 15.12%; with it -231.6%, clamped to 0."""
    clean, _ = lite_like(x_L=0.167, om_trend=0.20)
    one_off, _ = lite_like(x_L=-2.30, om_trend=0.20)
    assert clean["m_long"] == pytest.approx(0.167 + 0.79 * (0.20 - 0.22), rel=1e-9)
    assert one_off["m_long"] == pytest.approx(clean["m_long"], rel=1e-6)


# =============================================================================================================================
# Part D - other arithmetic defects in the desk's own path.
# =============================================================================================================================

def _margin_lr(m):
    return {"e5": 1.0, "oe5": 1.0, "margin_ratio": m}


def test_d2_reproduced_a_fade_of_zero_drops_the_long_run_margin():
    """long_run_value: k_end = 1 when F = 0, so a fade of 0 values the long run at the year-5 margin whatever margin_ratio says, and the result
    still echoes the margin_ratio. S growing 3% a year, margin_ratio 0.5, g5 = gt = 3% (the fade changes no growth), RONIC unlimited:
    PV of years 1-5 = sum 1.03^t / 1.1^t = 4.122678; OE5 = 1.03^5 = 1.159274; F = 1: long run = 0.5 x 1.159274 x 1.03 / 0.07 / 1.1^5 =
    5.295804, value 9.418482; F = 0: 1.159274 x 1.03 / 0.07 / 1.1^5 = 10.591608, value 14.714286.
    On the saved LITE facts the same switch takes the DEFAULTS value from $173.38 (fade 1) to $768.81 (fade 0); the reference is $271.20 at 5."""
    base = dict(explicit_growth=[0.03] * 5, long_run=_margin_lr(0.5))
    f1, f0 = desk(fade_years=1, **base), desk(fade_years=0, **base)
    oe5 = 1.03 ** 5
    pv15 = sum(1.03 ** t / d for t, d in zip(range(1, 6), D5))
    assert f1["per_share_iv_raw"] == pytest.approx(pv15 + 0.5 * oe5 * 1.03 / 0.07 / 1.1 ** 5, rel=1e-12)
    assert f0["per_share_iv_raw"] == pytest.approx(pv15 + oe5 * 1.03 / 0.07 / 1.1 ** 5, rel=1e-12)
    assert f0["long_run"]["margin_ratio"] == 0.5


@pytest.mark.xfail(strict=True, reason="D2 defect: long_run_value sets k_end = 1 when the fade is 0 (fade_years=0, or explicit rates that use "
                                       "up the fade in _five_and_fade), so the facts' margin_ratio is silently dropped and the value jumps "
                                       "(saved LITE facts: $173.38 at fade 1, $768.81 at fade 0)")
def test_d2_the_long_run_margin_applies_whatever_the_fade_length():
    """With g5 = gt the fade moves no growth, so with a margin ratio below 1 a longer fade (a slower fall in margin) can only raise value,
    and a fade of 0 (the margin at its long-run level from year 6) must not be worth more than a fade of 1."""
    base = dict(explicit_growth=[0.03] * 5, long_run=_margin_lr(0.5))
    vals = [iv(fade_years=f, **base) for f in (0, 1, 2, 5)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))


@pytest.mark.xfail(strict=True, reason="D2 defect, the second route: two explicit rates with fade_years 3 leave no fade for the long run "
                                       "(_five_and_fade gives 0), so margin_ratio is ignored: the value with margin_ratio 0.5 equals the "
                                       "value with the margin held")
def test_d2_fewer_explicit_rates_do_not_drop_the_long_run_margin():
    a = iv(explicit_growth=[0.05, 0.05], fade_years=3, long_run=_margin_lr(0.5), terminal_ronic=0.20)
    b = iv(explicit_growth=[0.05, 0.05], fade_years=3, long_run=_margin_lr(None), terminal_ronic=0.20)
    assert a < b


@pytest.mark.xfail(strict=True, reason="D3 defect: with a reference, the desk translates a scenario's owner earnings to its year-5 earnings "
                                       "additively (E5 = e5 + OE5 - oe5), so a scenario with positive owner earnings can reach negative "
                                       "long-run earnings and a long run floored at 0 (long_run_floor); without a reference the same "
                                       "translation is proportional")
def test_d3_positive_scenario_owner_earnings_keep_positive_long_run_earnings():
    """Facts e5 0.6, oe5 1.0 (D&A above capex: earnings 60% of owner earnings). A Bear at 35% of the owner earnings: E5 = 0.6 + (0.35 - 1.0)
    = -0.05, so the long run is negative and floored; proportionally it would be 0.6 x 0.35 = 0.21. At 50%: E5 = 0.10, an 83% cut in earnings
    for a 50% cut in owner earnings."""
    r = desk(base_cf=0.35, long_run={"e5": 0.6, "oe5": 1.0, "margin_ratio": 1.0}, fade_years=5, terminal_ronic=0.20)
    assert r["long_run"]["year5_earnings"] > 0 and "long_run_floor" not in r["stamps"]


def test_d4_reproduced_an_unlimited_terminal_ronic_holds_the_starting_ronic_through_the_fade():
    """ronic_at: with an infinite end point the start holds until frac reaches 1, while any finite end point interpolates. long_run_value with
    e5 1.0, g5 = gt = 3%, r 10%, RONIC_0 = 10%, a two-year fade. Year 6 (frac 0.5): RONIC_T unlimited holds 10%, flow 1.03 x (1 - 0.03 / 0.10)
    = 0.721; RONIC_T 10^12 interpolates to 5 x 10^11, flow 1.03. Year 7 and the terminal are the same in both. Difference at year 0 =
    (1.03 - 0.721) / 1.1^6 = 0.174422: the unlimited return is worth less than a finite one."""
    unl = cr.long_run_value(1.0, 0.03, 0.03, 0.10, 0.10, INF, None, 2)
    fin = cr.long_run_value(1.0, 0.03, 0.03, 0.10, 0.10, 1e12, None, 2)
    assert unl["flows"][0] == pytest.approx(0.721, abs=1e-12) and fin["flows"][0] == pytest.approx(1.03, abs=1e-9)
    assert fin["value"] - unl["value"] == pytest.approx((1.03 - 0.721) / 1.1 ** 6, abs=1e-9)


@pytest.mark.xfail(strict=True, reason="D4 defect: ronic_at holds RONIC_0 for years 6..N-1 when RONIC_T is +inf, so an unlimited terminal "
                                       "return is worth less than a large finite one (desk S, RONIC_0 = r: $16.23 unlimited against $17.39 at "
                                       "10^6 and $16.82 at 100%); value is not monotone in terminal_ronic")
def test_d4_value_is_monotone_in_terminal_ronic_up_to_unlimited():
    vals = [iv(terminal_ronic=x, fade_years=5, explicit_growth=[0.06] * 5) for x in (0.50, 1.0, 1e6, INF)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))


@pytest.mark.xfail(strict=True, reason="D4 defect, its reach: price_implied searches terminal_ronic up to unlimited (u = r / RONIC = 0). With "
                                       "a finite RONIC_0 the value at the unlimited end ($17.00) is below the values just inside it, so the "
                                       "block prints a bound's high value below a root it reports as reachable, and stamps a discontinuity "
                                       "the desk's own rule creates")
def test_d4_the_price_implied_terminal_ronic_block_has_no_self_made_discontinuity():
    """A Base on S with growth 6% for five years, a five-year fade, terminal_ronic 15%, the record's r_tc 30% (RONIC_0 30%). Price $17.20."""
    lr = {"r_tc": 0.30}
    b = dict(cf=1.0, growth=[0.06] * 5, fade=5, wacc=0.10, tg=0.03, shares=1.0, sbc="deducted_in_cf", sbc_dil=None, frame="equity",
             net_debt=None, rate_type=None, annuity=0.0, annuity_cap=None, ronic=0.15, wc=None, excess=None, long_run=lr, finite=None)
    b["raw"] = iv(terminal_ronic=0.15, fade_years=5, explicit_growth=[0.06] * 5, long_run=lr)
    blk = fmt.price_implied(b, 17.20)["terminal_ronic"]
    assert blk["reachable"] and blk["base_at_value"] == pytest.approx(17.20, abs=1e-6)
    assert "discontinuity" not in blk["stamps"]
    assert blk["bound"]["value_high"] >= blk["base_at_value"]


def test_d2_reproduced_on_the_saved_lite_facts():
    """The saved LITE DEFAULTS through the desk at fade 0, 1 and 5: $768.81, $173.38, $271.20 (the CONSENSUS-IMPLIED VALUE). The fade of 0 is
    worth 2.8 times the reference because it drops the facts' margin_ratio 0."""
    f = _saved("LITE_20261006_145640")
    vals = {fy: fmt.unbundled_dcf(base_cf=f["reference_base_b"], explicit_growth=f["reference_path"], wacc=f["coe_anchor"],
                                  terminal_g=f["terminal_g_default"], shares_diluted=f["shares_default"] / 1e9, fade_years=fy,
                                  sbc_treatment="deducted_in_cf", terminal_ronic=f["terminal_ronic"], long_run=f["long_run"],
                                  working_capital=f["working_capital"], excess_cash=f["excess_cash"])["per_share_iv"] for fy in (0, 1, 5)}
    assert vals == {0: 768.81, 1: 173.38, 5: 271.20}


def test_the_desk_applies_the_reference_margin_ratio_to_the_scenario_own_year5_earnings():
    """_long_run_inputs passes the facts' margin_ratio unchanged; long_run_value multiplies the SCENARIO's E5 by it. So the long-run margin the
    desk values is ratio x the scenario's year-5 margin, not the record's trend level: a scenario at twice the owner earnings keeps the ratio
    0.5: E5 = 0.8 + (2.0 - 1.0) = 1.8, terminal value (one-year fade, RONIC unlimited) 0.5 x 1.8 x 1.03 x 1.03 / 0.07 = 13.64."""
    r = desk(base_cf=2.0, long_run={"e5": 0.8, "oe5": 1.0, "margin_ratio": 0.5})
    assert r["long_run"]["margin_ratio"] == 0.5 and r["long_run"]["year5_earnings"] == pytest.approx(1.8)
    assert r["terminal_value_nominal"] == pytest.approx(0.5 * 1.8 * 1.03 * 1.03 / 0.07, abs=0.005)
