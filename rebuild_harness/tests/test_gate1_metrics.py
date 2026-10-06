"""Tests of the gate-1 metrics B1-B4 and the diagnostics on synthetic records (no file, no price, no network)."""
import math
import random

import numpy as np
import pytest

from rebuild_harness import gate1_metrics as gm

ENG = gm.ENGINE


def rec(date, i, vp, excess, industry="I1", family="operating", ys=None, bounds=None, group=">=300M", g1=None, g_naive=None, m1=None, m0=None, out=None):
    ys = ys if ys is not None else {y: 0.0 for y in gm.YARDSTICKS}
    return {"date": date, "cik": str(i), "industry": industry, "family": family, "status": "valued", "mcap_group": group, "vp": vp,
            "score": dict({ENG: vp}, **ys), "excess": {12: excess}, "bounds": ({12: bounds} if bounds is not None else {}), "g1_p50": g1, "g_naive": g_naive,
            "m1_p50": m1, "m0": m0, "base": {"revenue": 100.0}, "out1": out, "stale": False}


def population(date, n=120, slope=0.5, seed=1, noise=0.05, industries=("I1", "I2", "I3")):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        vp = math.exp(rng.gauss(0, 0.5))
        ys = {y: rng.random() for y in gm.YARDSTICKS}
        rows.append(rec(date, f"{date}-{i}", vp, slope * (vp - 1.0) + rng.gauss(0, noise), industry=industries[i % len(industries)], ys=ys))
    return rows


# ---- B1 -------------------------------------------------------------------------------------------------------------------------------------

def test_b1_finds_the_engine_coefficient_and_passes_with_a_positive_signal():
    rows = population("d1") + population("d2", seed=2) + population("d3", seed=3) + population("d4", seed=4)
    r = gm.b1(gm.by_date(rows), "excluded", n_resamples=200)
    assert r["status"] == "pass" and r["mean_coef"] > 0.1 and r["ci90"][0] > 0 and r["n_dates"] == 4


def test_b1_fails_when_the_signal_is_reversed_and_is_not_computed_without_dates():
    rows = []
    for k in range(4):
        rows += population(f"d{k}", seed=10 + k, slope=-0.5)
    assert gm.b1(gm.by_date(rows), "excluded", n_resamples=200)["status"] == "fail"
    few = population("d1", n=10)
    assert gm.b1(gm.by_date(few), "excluded", n_resamples=50)["status"] == "not computed"


def test_b1_uses_the_survivorship_bound_of_the_return():
    rows = []
    for k in range(3):
        for r in population(f"d{k}", seed=20 + k):
            r["bounds"] = {12: {"excluded": r["excess"][12], "minus100": -1.0, "last_close": r["excess"][12]}}
            rows.append(r)
    ex = gm.b1(gm.by_date(rows), "excluded", n_resamples=100)["mean_coef"]
    m100 = gm.b1(gm.by_date(rows), "minus100", n_resamples=100)["mean_coef"]
    assert ex > 0.1 and abs(m100) < 1e-9                                                  # every return -100%: no cross-sectional information


def test_b1_industry_fixed_effects_remove_an_industry_level_effect():
    rng = random.Random(5)
    rows = []
    for k in range(3):
        for i in range(150):
            ind = ("A", "B", "C")[i % 3]
            vp = math.exp(rng.gauss(0, 0.3)) * {"A": 0.5, "B": 1.0, "C": 2.0}[ind]          # the industry sets the level of value / price ...
            ex = {"A": -0.2, "B": 0.0, "C": 0.2}[ind] + rng.gauss(0, 0.05)                  # ... and of the return, with no within-industry relation
            rows.append(rec(f"d{k}", f"{k}-{i}", vp, ex, industry=ind, ys={y: rng.random() for y in gm.YARDSTICKS}))
    assert abs(gm.b1(gm.by_date(rows), "excluded", n_resamples=100)["mean_coef"]) < 0.05


# ---- B2 -------------------------------------------------------------------------------------------------------------------------------------

def test_b2_neutral_spread_is_positive_and_large_for_a_strong_signal():
    rows = []
    for k in range(3):
        rows += population(f"d{k}", n=150, seed=30 + k, slope=0.5)
    r = gm.b2(gm.by_date(rows), "excluded", n_resamples=100)
    assert r["status"] == "pass" and r["mean_spread"] > 0.2 and r["mean_spread_residual"] > 0


def test_b2_bar_is_three_points_and_the_residual_must_be_positive():
    rows = []
    for k in range(3):
        rows += population(f"d{k}", n=150, seed=40 + k, slope=0.001, noise=0.05)
    r = gm.b2(gm.by_date(rows), "excluded", n_resamples=100)
    assert r["mean_spread"] < gm.B2_BAR and r["status"] == "fail"


# ---- B3 -------------------------------------------------------------------------------------------------------------------------------------

def test_b3_extremes_and_family_sorting():
    rows = [rec("d", i, 1.0, 0.0, family="operating") for i in range(80)] + [rec("d", 100 + i, 1.0, 0.0, family="financial") for i in range(20)]
    ok = gm.b3(rows)
    assert ok["share_extreme"] == 0.0 and ok["a_ok"] and ok["b_ok"] and ok["c_status"] == "fail"      # every value / price is 1.0: no spread, below the 0.30 floor
    rows = [rec("d", i, 0.2 if i < 20 else 1.0, 0.0, family="financial" if i < 20 else "operating") for i in range(100)]   # every extreme is financial
    b = gm.b3(rows)
    assert b["share_below_0_4"] == pytest.approx(0.2) and not b["a_ok"]
    assert b["family_share_extremes"]["financial"] == 1.0 and b["family_gap_points"]["financial"] == pytest.approx(80.0) and not b["b_ok"]
    assert b["status"] == "fail" and b["c_status"] == "fail"                                  # 80% of the names sit at 1.0: the IQR of ln(IV/price) is 0


def test_b3_counts_a_non_positive_value_as_below_the_floor_and_reports_the_iqr_on_positive_values():
    rows = [rec("d", i, v, 0.0) for i, v in enumerate([-1.0, 0.0, 0.5, 1.0, 2.0, 3.0])]
    b = gm.b3(rows)
    assert b["share_below_0_4"] == pytest.approx(2 / 6) and b["share_nonpositive_iv"] == pytest.approx(2 / 6) and b["n_positive_iv"] == 4


def test_b3_c_is_an_absolute_floor_on_the_iqr_of_ln_iv_over_price():
    assert gm.B3C_FLOOR == 0.30
    # ln(vp) uniform on [-x, x]: IQR = x; a population with an IQR of 0.2 fails, one of 0.4 passes (no old engine is involved)
    narrow = [rec("d", i, math.exp(0.2 * (i - 50) / 50), 0.0) for i in range(101)]
    wide = [rec("d", i, math.exp(0.4 * (i - 50) / 50), 0.0) for i in range(101)]
    assert gm.b3(narrow)["c_status"] == "fail" and gm.b3(narrow)["status"] == "fail" and gm.b3(narrow)["iqr_ln_vp_positive_iv"] == pytest.approx(0.2, abs=0.01)
    assert gm.b3(wide)["c_status"] == "pass" and gm.b3(wide)["status"] == "pass" and gm.b3(wide)["c_floor"] == 0.30
    assert gm.b3([rec("d", i, -1.0, 0.0) for i in range(10)])["c_status"] == "not computed"             # no positive IV: no IQR


# ---- B4 -------------------------------------------------------------------------------------------------------------------------------------

def test_b4_median_absolute_errors_against_the_naive_baseline():
    rows = []
    for i in range(40):
        actual_g, actual_m = 0.10, 0.20
        rows.append(rec("d", i, 1.0, 0.0, g1=0.09, g_naive=0.20, m1=0.19, m0=0.30, out={"revenue": 100.0 * (1 + actual_g), "operating_margin": actual_m}))
    r = gm.b4(rows)
    assert r["status"] == "pass" and r["revenue_growth"]["median_abs_error_engine"] == pytest.approx(0.01)
    assert r["revenue_growth"]["median_abs_error_naive"] == pytest.approx(0.10) and r["operating_margin"]["share_engine_closer"] == 1.0
    worse = [rec("d", i, 1.0, 0.0, g1=0.30, g_naive=0.10, m1=0.19, m0=0.20, out={"revenue": 110.0, "operating_margin": 0.20}) for i in range(10)]
    assert gm.b4(worse)["status"] == "fail"
    fin = [rec("d", i, 1.0, 0.0, family="financial", g1=0.1, g_naive=0.1, m1=0.1, m0=0.1, out={"revenue": 110.0, "operating_margin": 0.2}) for i in range(10)]
    assert gm.b4(fin)["status"] == "not computed"                                          # the financial engine has no revenue or margin forecast


# ---- the bars over the bounds and the diagnostics ------------------------------------------------------------------------------------------------

def test_three_bounds_reports_not_decided_when_the_bounds_straddle():
    rows = []
    for k in range(3):
        for r in population(f"d{k}", n=150, seed=50 + k):
            r["bounds"] = {12: {"excluded": r["excess"][12], "minus100": -r["excess"][12], "last_close": r["excess"][12]}}      # one bound reverses the signal
            rows.append(r)
    res = gm.three_bounds(rows, "t", n_resamples=100)
    assert res["B1_status_over_bounds"] == "not decided" and res["provisional"].startswith("PROVISIONAL")
    assert set(res["B1"]) == set(gm.BOUNDS) and "B1_rank_dependent_variant" in res


def test_diagnostics_shapes():
    rows = []
    for i in range(60):
        r = rec("d", i, math.exp(random.Random(i).gauss(0, 1)), 0.0, family=("operating", "financial", "commodity")[i % 3], industry=("A", "B")[i % 2])
        r.update({"tv_share": 0.3 + 0.01 * (i % 10), "tv_share_point": 0.5, "md": -0.5 + 0.1 * (i % 5) if i % 7 else None, "invalid_share": 0.5, "vp_point": r["vp"] * 2,
                  "vp_p10": r["vp"] / 2, "vp_p90": r["vp"] * 2, "secondary_vp": r["vp"] * 1.5, "disc": {"coe": 0.08, "wacc": 0.07},
                  "inputs": {"ronic": {"p10": 0.0, "p50": 0.05, "p90": 0.15}, "g1": {"p10": 0.0, "p50": 0.05, "p90": 0.1}, "margin_target": {"p10": 0.0, "p50": 0.1, "p90": 0.3}},
                  "returns": {"roic3": 0.2, "industry_roic": {"value": 0.05, "n": 30, "basis": "industry"}, "ronic_terminal_at_p50_inputs": 0.07, "rote3": None,
                              "industry_rote": None, "rote_terminal_at_p50_inputs": None}, "prior_meta": {
                      "fallbacks": ["g_terminal: pooled"], "margin_target": {"r5": 0.6, "level5_median": 0.12, "centre_8y_median": 0.10}},
                  "margin_path": {"shape": "curve", "clipped": False}, "terminal_year": {"margin": 0.1},
                  "g_term": {"base": 0.02, "at_p50_inputs": {"value": 0.02, "basis": "min(risk-free rate at T, 3.75% anchor)"}}})
        r["m0"] = 0.12
        rows.append(r)
    by_fam = gm.vp_by(rows, lambda r: r["family"])
    assert set(by_fam) == {"operating", "financial", "commodity"} and by_fam["operating"]["n"] == 20
    ex = gm.extremes_by_family(rows)
    assert ex["below_0_4"]["n"] + 0 == sum(v["n"] for v in ex["below_0_4"]["by_family"].values())
    assert gm.tv_share_distribution(rows)["all"]["n"] == 60
    assert gm.disagreement_by_family(rows)["operating"]["n"] > 0
    st = gm.structure_stats(rows)
    assert st["share_ronic_p50_below_wacc"] == 1.0 and st["terminal_growth_date_value"]["p50"] == 0.02 and st["share_terminal_growth_from_negative_decay_path"] == 0.0 and st["margin_level5_r5"]["p50"] == 0.6 and st["ronic_level5_width_p10_p90"]["p50"] == pytest.approx(0.15)         and st["share_terminal_ronic_floored_at_wacc"] == 1.0 and st["industry_median_roic"]["p50"] == 0.05 and st["own_trailing_roic3"]["p50"] == 0.2 and st["margin_path_linear_share"] == 0.0
    assert st["share_names_over_half_draws_invalid"] == 0.0 and st["ratio_distribution_median_to_point_inputs"]["p50"] == pytest.approx(0.5)


def test_compact_and_load_run_round_trip(tmp_path):
    import gzip
    import json
    recs = [{"date": "2021-06-30", "cik": "1", "ticker": "AAA", "industry": "A", "family": "operating", "status": "valued", "reasons": [], "price": 10.0,
             "market_cap": 1e9, "mcap_group": ">=300M", "base_age_months": 5.0, "score": {ENG: 2.0}, "excess": {"12": 0.1}, "bounds": {"12": {"excluded": 0.1, "minus100": 0.1, "last_close": 0.1}},
             "base": {"revenue": 100.0}, "out": {"1": {"revenue": 110.0, "operating_margin": 0.2}}, "stamps": ["s"],
             "val": {"iv_ps": {"p10": 5.0, "p25": 10.0, "p50": 20.0, "p75": 30.0, "p90": 40.0}, "iv_point_p50_inputs_ps": 15.0, "secondary_ps": 18.0, "model_disagreement": 0.1,
                     "tv_share_p50": 0.4, "n_valid": 1000, "n_draws": 2000, "forecast": {"year1_growth_point": 0.1, "year1_margin_point": 0.2}, "state": {"op_margin": 0.2},
                     "prior_meta": {"mechanical_baseline_g1": 0.05}, "discount": {"coe": 0.08, "wacc": 0.07}, "inputs": {}}},
            {"date": "2021-06-30", "cik": "2", "ticker": "BBB", "family": "operating", "status": "refused", "reasons": ["not available: operating_income"], "price": 5.0}]
    with gzip.open(tmp_path / "records_2021-06-30.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    rows, counters, full = gm.load_run(tmp_path, keep_all_for=("2021-06-30",))
    assert len(rows) == 1 and rows[0]["vp"] == 2.0 and rows[0]["excess"] == {12: 0.1} and rows[0]["invalid_share"] == 0.5 and len(full["2021-06-30"]) == 1
    cov = gm.coverage_tables(counters)
    assert cov["per_date_status"]["2021-06-30"] == {"valued": 1, "refused": 1} and "not available: operating_income" in cov["refusals_by_reason"]


def test_adjusted_proxy_basis_rescales_only_the_price_level_scores():
    prices = {"prices": {"AAA": {"2021-06": [100.0, 80.0, 0.0, 0.0]}, "BBB": {"2021-06": [50.0, 50.0, 0.0, 0.0]}}}
    a = rec("2021-06-30", 1, 1.0, 0.0, ys={y: 1.0 for y in gm.YARDSTICKS})
    a.update(ticker="AAA", vp_p10=0.5, vp_p90=2.0, vp_point=1.2, secondary_vp=0.9)
    b = rec("2021-06-30", 2, 2.0, 0.0, ys={y: 1.0 for y in gm.YARDSTICKS})
    b.update(ticker="BBB", vp_p10=1.0, vp_p90=3.0, vp_point=None, secondary_vp=None)
    c = rec("2021-06-30", 3, 3.0, 0.0)
    c.update(ticker="CCC", vp_p10=None, vp_p90=None, vp_point=None, secondary_vp=None)
    missing = gm.apply_adjusted_proxy([a, b, c], prices)
    assert missing == 1 and a["vp"] == pytest.approx(1.25) and a["vp_p10"] == pytest.approx(0.625) and a["vp_point"] == pytest.approx(1.5)
    assert a["score"][ENG] == pytest.approx(1.25) and a["score"]["yardstick_earnings_yield"] == pytest.approx(1.25) and a["score"]["yardstick_fcf_yield"] == pytest.approx(1.25)
    assert a["score"]["yardstick_momentum_12_1"] == 1.0 and a["score"]["yardstick_return_on_capital"] == 1.0         # no price level in them
    assert b["vp"] == 2.0 and c["vp"] == 3.0                                                                             # f = 1 for BBB; CCC has no bar: left on the run's basis


def test_family_not_built_reasons_are_counted_by_kind():
    assert gm._reason_class("SIC 4911: regulated_utility_or_pipeline; family not built (SPEC 2)") == "family_not_built: regulated_utility_or_pipeline"
    assert gm._reason_class("SIC 6798: reit_or_real_estate; family not built (SPEC 2)") == "family_not_built: reit_or_real_estate"
    assert gm._reason_class("pre_profit: operating income <= 0 in 3 of the last 4 fiscal years known at the date; needs a survival and option model; family not built (Addendum H4)") == "family_not_built: pre_profit"


def test_returns_use_the_dates_to_the_end_of_2021_and_forecast_quality_every_date():
    rows = []
    for k, d in enumerate(["2021-06-30", "2021-09-30", "2021-12-31", "2022-03-31", "2022-06-30"]):
        for r in population(d, n=120, seed=60 + k):
            r["g1_p50"], r["g_naive"], r["m1_p50"], r["m0"], r["out1"] = 0.1, 0.1, 0.1, 0.1, {"revenue": 110.0, "operating_margin": 0.1}
            rows.append(r)
    res = gm.three_bounds(rows, "t", n_resamples=50, return_end="2021-12-31")
    assert res["return_dates"] == ["2021-06-30", "2021-09-30", "2021-12-31"] and res["B1"]["excluded"]["n_dates"] == 3 and res["B2"]["excluded"]["n_dates"] == 3
    assert len(res["b4_dates"]) == 5 and res["B4"]["revenue_growth"]["n"] == 600 and res["B4_return_dates_only"]["revenue_growth"]["n"] == 360
    assert res["B3"]["n"] == 360 and res["B3_all_dates"]["n"] == 600
    every = gm.three_bounds(rows, "t", n_resamples=50)
    assert every["B1"]["excluded"]["n_dates"] == 5


def test_a_name_missing_a_yardstick_stays_at_the_median_rank_with_an_indicator_and_the_coverage_is_reported():
    rows = population("d1", n=120, seed=71)
    for r in rows[::4]:                                                    # a quarter of the names lack gross profitability
        r["score"][gm.YARDSTICKS[2]] = None
    for r in rows[1::10]:
        r["score"][gm.YARDSTICKS[0]] = None
    pairs = gm._usable(rows, "excluded")
    assert len(pairs) == 120                                              # nobody is dropped for a missing yardstick
    cols, inds, miss = gm.yardstick_design([p[0] for p in pairs], gm.YARDSTICKS)
    assert miss[gm.YARDSTICKS[2]] == 30 and miss[gm.YARDSTICKS[0]] == 12 and miss[gm.YARDSTICKS[1]] == 0
    assert len(inds) == 2 and [int(i.sum()) for i in inds] == [12, 30]       # indicators only for the yardsticks with a missing value on the date
    c2 = cols[2]
    assert all(c2[i] == 0.5 for i in range(0, 120, 4))                        # the median rank
    have = [c2[i] for i in range(120) if i % 4]
    assert len(set(have)) == len(have) and min(have) > 0 and max(have) < 1
    res = gm.b1(gm.by_date(rows), "excluded", n_resamples=50)
    assert res["by_date"]["d1"]["n"] == 120 and res["yardstick_missing_share"][gm.YARDSTICKS[2]] == pytest.approx(0.25)
    assert res["yardstick_missing_share"][gm.YARDSTICKS[1]] == 0.0
    sp = gm.b2(gm.by_date(rows), "excluded", n_resamples=50)
    assert sp["by_date"]["d1"]["n"] == 120



def test_the_run_stamps_the_raw_monthly_source_and_the_report_says_so():
    from rebuild_harness import gate1_run, gate1_report
    assert gate1_run.PRICE_STAMP == "raw_monthly_2026-10-01_survivors" and "adjusted_proxy" not in gate1_run.PRICE_STAMP
    assert "raw month-end" in gm.PROVISIONAL and gm.PROVISIONAL.startswith("PROVISIONAL") and "Addendum H9" in gm.PROVISIONAL
