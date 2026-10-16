"""Revision 24 step 2b, item 1 (BRIEF_R24_S2b_ranges_gate.md): tools/population_ranges.py, the population ranges of the long-run inputs, read from
fixture tables built here (the shape of priors_v5's tables.json, with numbers chosen so each answer is computed by hand): the vintage by date, the
cohort of each input by the rebuild's rules, the quantiles, the shrinking stratum, the fallbacks to pooled cells, the family rules, the company
record's features, and the section's text with P50 only on its flag. The parity with the rebuild's own valuation/priors.py is a script run in the
rebuild's interpreter (stocks-workspace/scratch/rev23/r24_s2b/), not a unit test."""
import json
import math
import statistics
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import population_ranges as pr  # noqa: E402

QK = ("p5", "p10", "p25", "p50", "p75", "p90", "p95")


def q(n, *vals):
    return dict(zip(QK, vals), n=n)


R_MID_POS = q(300, -2.0, -1.0, 0.0, 0.5, 1.0, 2.0, 3.0)        # the retained share R at k = 5 of the band mid_pos


def band(n, q5, n5=None, extra=()):
    rows = [{"k": k, "n": n, "median": 0.9 - 0.1 * k, "q": q(n, *[0.1 * k] * 7)} for k in range(1, 5)]
    rows.append({"k": 5, "n": n5 if n5 is not None else n, "median": q5["p50"], "q": q5})
    rows += [{"k": 6, "n": 60, "median": 0.3}, {"k": 7, "n": 5, "median": 0.2}] + list(extra)
    return {"n": n, "ks": rows}


def lvl(n, *groups):
    """A residual-by-level cell: its n and its groups (lower, upper, n, the seven quantiles P5..P95)."""
    return {"n": n, "groups": [{"band": [i, i], "lower": lo, "upper": hi, "n": gn, **dict(zip(QK, qs)), "merged": False}
                               for i, (lo, hi, gn, qs) in enumerate(groups)]}


def fixture_tables(**over):
    T = {
        "priors_version": "5", "vintage": 2025, "cut_date": "2026-01-01", "min_n": 50, "obs_sha256": "abc",
        "edges": {"growth": [-0.10, 0.0, 0.05, 0.10, 0.20, 0.40], "size_usd": [5e7, 2.5e8, 1e9, 5e9, 2e10]},
        "cyc_weights": {"adopted": False, "weights": [0.25] * 4},
        "margin_retention": {"cyc_cuts": [0.45, 0.60], "bands": {
            "low_pos": band(400, q(400, *[0.2] * 7)), "low_neg": band(400, q(400, *[0.3] * 7)),
            "mid_pos": band(1700, R_MID_POS, n5=300), "mid_neg": band(30, q(30, *[0.4] * 7)),
            "high_pos": band(400, q(400, *[0.5] * 7)), "high_neg": band(400, q(400, *[0.6] * 7)),
            "pooled_pos": band(3000, q(1000, *[0.7] * 7)), "pooled_neg": band(3000, q(1000, -1.0, -0.5, 0.0, 0.25, 0.5, 1.0, 1.5)),
            "pooled_all": band(6000, q(2000, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6))},
            # step 2c (ruling 1): the year-5 residual of the margin level by the current operating-margin band (stats.residual_by_level's shape)
            "residual_k5_by_level": {
                "mid_pos": lvl(300, (None, 0.12, 120, (-0.10, -0.06, -0.02, 0.0, 0.02, 0.05, 0.08)),
                               (0.12, None, 180, (-0.20, -0.12, -0.04, 0.01, 0.03, 0.06, 0.10))),
                "mid_neg": lvl(30, (None, None, 30, (-0.1,) * 7)),
                **{k: lvl(400, (None, None, 400, (-0.08, -0.05, -0.02, 0.0, 0.02, 0.04, 0.07))) for k in ("low_pos", "low_neg", "high_pos", "high_neg")},
                "pooled_pos": lvl(3000, (None, None, 3000, (-0.15, -0.10, -0.03, 0.0, 0.03, 0.07, 0.12))),
                "pooled_neg": lvl(3000, (None, None, 3000, (-0.14, -0.09, -0.03, 0.0, 0.02, 0.06, 0.11))),
                "pooled_all": lvl(6000, (None, None, 6000, (-0.12, -0.08, -0.02, 0.0, 0.02, 0.05, 0.09)))}},
        "normalization": {"cuts": [0.40, 0.50, 0.55, 0.65], "bands": [
            {"band": b, "score_median": 0.3 + 0.1 * b, "all": band(500, q(500, *[0.05 * (b + 1)] * 7))} for b in range(5)]},
        "growth_decay": {
            "operating": {"terminal_reference": {"value": 0.03}, "buckets": [
                {"bucket": [0, 1], "n_k1": 900, "ks": [{"k": k, "n": 600 - 50 * k, "raw_p25": -0.05, "raw_p50": 0.01 * k, "raw_p75": 0.08,
                                                       "n_ratio": 500, "ratio_median": 0.5, **({"ratio_q": q(500, -3, -2, -1, 0.3, 1, 2, 3)} if k <= 5 else {})}
                                                      for k in range(1, 11)]},
                {"bucket": [2, 6], "n_k1": 4000, "ks": [{"k": k, "n": 3000, "raw_p25": 0.0, "raw_p50": 0.05, "raw_p75": 0.12, "n_ratio": 2500,
                                                        "ratio_median": 0.4, **({"ratio_q": q(2500, *[0.1] * 7)} if k <= 5 else {})}
                                                       for k in range(1, 11)]}]},
            "commodity": {"terminal_reference": None, "buckets": []},
            "financial": {"terminal_reference": {"value": 0.09}, "buckets": [
                {"bucket": [0, 6], "n_k1": 300, "ks": [{"k": k, "n": 200, "raw_p25": 0.02, "raw_p50": 0.06, "raw_p75": 0.1, "n_ratio": 150,
                                                       "ratio_median": 0.2, **({"ratio_q": q(150, *[0.2] * 7)} if k <= 5 else {})}
                                                      for k in range(1, 11)]}]}},
        "terminal": {"K_eff": 10, "families": {
            "operating": {"all": {"with_delisted": q(10000, -0.25, -0.15, -0.03, 0.04, 0.12, 0.30, 0.55)},
                          "shrinking": {"with_delisted": q(440, -0.20, -0.14, -0.07, 0.005, 0.08, 0.22, 0.54)}},
            "commodity": {"all": {"with_delisted": q(260, -0.15, -0.09, -0.02, 0.03, 0.09, 0.22, 0.38)},
                          "shrinking": {"with_delisted": {"n": 0}}},
            "financial": {"all": {"with_delisted": q(1700, -0.04, -0.01, 0.03, 0.06, 0.11, 0.17, 0.22)}}}},
        "ronic": {"ic_growth_floor": 0.1, "roic_cuts": [0.04, 0.12], "families": {
            "operating": {"floored_all": q(8000, -0.9, -0.4, -0.07, 0.05, 0.2, 0.54, 0.95),
                          "bands": {"low": {"band": 0, **q(1600, -1.8, -0.8, -0.1, 0.09, 0.4, 1.3, 2.2)},
                                    "mid": {"band": 1, **q(2900, -0.5, -0.2, -0.03, 0.05, 0.15, 0.35, 0.55)},
                                    "high": {"band": 2, **q(40, -1.0, -0.5, -0.1, 0.04, 0.2, 0.49, 0.78)}}}}},
        # step 2c (ruling 6): the ROIC level path (stats.roic_level_tables' shape)
        "roic_level": {"min_abs_gap": 0.02, "reference_by_year": {"2023": 0.09, "2024": 0.10, "2025": 0.13},
                       "bands": {"pos": {"sign": 1, "n": 3000, "ks": [{"k": k, "n": 3000, "median": 0.9 - 0.1 * k} for k in range(1, 8)]},
                                 "neg": {"sign": -1, "n": 3000, "ks": [{"k": k, "n": 3000, "median": 0.95 - 0.07 * k} for k in range(1, 8)]},
                                 "all": {"sign": 0, "n": 6000, "ks": [{"k": k, "n": 6000, "median": 0.85 - 0.08 * k} for k in range(1, 8)]}},
                       "residual_k5_by_level": {
                           "pos": lvl(3000, (None, 0.20, 1500, (-0.12, -0.08, -0.03, 0.0, 0.03, 0.08, 0.13)),
                                      (0.20, None, 1500, (-0.40, -0.25, -0.08, -0.01, 0.07, 0.20, 0.35))),
                           "neg": lvl(3000, (None, None, 3000, (-0.20, -0.12, -0.04, 0.0, 0.03, 0.07, 0.10))),
                           "all": lvl(6000, (None, None, 6000, (-0.15, -0.10, -0.04, 0.0, 0.04, 0.10, 0.15)))}},
        "ronic_fade": {"reference": 0.076, "n_base": 24000, "ks": [{"k": k, "n": 20000 - 2000 * k, "median": 0.8 - 0.05 * k, "p25": 0.1, "p75": 1.3}
                                                                   for k in range(1, 8)] + [{"k": 8, "n": 20, "median": 0.1, "p25": 0.0, "p75": 0.2}]},
    }
    T.update(over)
    return T


def rec(**kw):
    base = {"family": "operating", "usd": True, "base_year": 2025, "rev": 2e9, "g_latest": 0.12, "g3": 0.15, "tg_latest": None, "tg3": None,
            "m": 0.15, "med8": 0.10, "n8": 8, "dev": 0.05, "trend8": 0.08, "cyc_score": 0.50, "cyc_components": None, "roic": 0.08,
            "em_trend": 0.08, "em_current": 0.12, "roic3": 0.25, "tax_t": 0.20, "tax_t_source": "the median effective rate of 8 fiscal years",
            "tax_t_stamps": [], "om_tc": 0.10, "om_basis": "without_amortization", "delta": -0.02,
            "delta_source": "the median of 8 fiscal years, FY2018-FY2025", "missing": []}
    base.update(kw)
    return base


# ---- the vintage --------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("T, V", [("2026-10-16", 2025), ("2026-01-01", 2025), ("2025-12-31", 2024), ("2017-03-01", 2016)])
def test_the_vintage_is_the_year_before_the_valuation_date(T, V):
    assert pr.vintage_for(T) == V


def test_the_tables_are_read_from_the_vintage_folder_and_a_missing_vintage_is_named(tmp_path):
    (tmp_path / "2025").mkdir()
    (tmp_path / "2025" / "tables.json").write_text(json.dumps(fixture_tables()), encoding="utf-8")
    got = pr.ranges_for(rec(), "2026-10-16", tdir=tmp_path)
    assert got["vintage"] == 2025 and got["cut_date"] == "2026-01-01" and got["inputs"]["long_run_margin"]["available"]
    assert pr.vintages_available(tmp_path) == [2025]
    none = pr.ranges_for(rec(), "2025-06-30", tdir=tmp_path)          # vintage 2024 is not on disk
    assert none["vintage"] == 2024 and all(not d["available"] for d in none["inputs"].values())
    assert set(none["inputs"]) == set(pr.INPUTS) and "no priors vintage 2024 on disk" in none["inputs"]["revenue_cagr_10y"]["reason"]


# ---- the long-run margin: the cohort and the levels ------------------------------------------------------------------------------------------





@pytest.mark.parametrize("kw, key, fallback", [
    ({"dev": 0.003, "m": 0.103}, "pooled_all", "within 0.5 points"),
    ({"cyc_score": None}, "pooled_pos", "no cyclicality score"),
    ({"med8": None, "dev": None}, "pooled_all", "fewer than 5 defined operating-margin years"),
    ({"dev": -0.05, "m": 0.05}, "pooled_neg", "band mid_neg has n=30 < 50"),      # mid_neg is thin: its pooled sign band
    ({"cyc_score": 0.60}, "high_pos", None),                                      # a score equal to a cut is in the upper band
    ({"cyc_score": 0.4499}, "low_pos", None),
])
def test_the_margin_cohort_fallbacks_are_the_rebuilds_and_are_listed(kw, key, fallback):
    d = pr.ranges_for(rec(**kw), "2026-10-16", tables=fixture_tables())["inputs"]["long_run_margin"]
    assert d["cohort"] == key
    if fallback:
        assert any(fallback in f for f in d["fallbacks"]), d["fallbacks"]
    else:
        assert d["fallbacks"] == []


def test_fitted_cyclicality_weights_are_used_only_when_the_vintage_adopted_them():
    comps = {"margin_volatility": 0.9, "reversal_frequency": 0.9, "autocorrelation": 0.9, "revenue_cyclicality": 0.9}
    T = fixture_tables(cyc_weights={"adopted": True, "weights": [0.1, 0.1, 0.1, 0.1]})
    d = pr.ranges_for(rec(cyc_score=0.9, cyc_components=comps), "2026-10-16", tables=T)["inputs"]["long_run_margin"]
    assert d["score"] == pytest.approx(0.36) and d["cohort"] == "low_pos" and d["score_basis"] == "fitted weights"
    d = pr.ranges_for(rec(cyc_score=0.9, cyc_components=comps), "2026-10-16", tables=fixture_tables())["inputs"]["long_run_margin"]
    assert d["score"] == 0.9 and d["cohort"] == "high_pos"






def test_a_financial_company_has_no_margin_range():
    got = pr.ranges_for(rec(family="financial", tg3=0.08), "2026-10-16", tables=fixture_tables())["inputs"]
    assert got["long_run_margin"]["available"] is False and "operating and commodity" in got["long_run_margin"]["reason"]
    assert got["terminal_ronic"]["available"] is False


# ---- growth of years 3-10 -----------------------------------------------------------------------------------------------------------------

def test_growth_is_read_by_the_bucket_of_the_three_year_cagr_else_the_latest_year():
    d = pr.ranges_for(rec(g3=0.15), "2026-10-16", tables=fixture_tables())["inputs"]["growth_years_3_10"]
    assert d["cohort"] == "operating:bucket_2-6" and d["growth_basis"] == "3-year revenue CAGR" and d["n"] == 4000
    assert sorted(d["by_k"]) == list(range(3, 11)) and d["by_k"][5] == {"n": 3000, "p25": 0.0, "p50": 0.05, "p75": 0.12}
    assert d["ratio_k"] == 5 and d["ratio"]["p90"] == 0.1 and d["terminal_reference"] == 0.03
    d = pr.ranges_for(rec(g3=None, g_latest=-0.05), "2026-10-16", tables=fixture_tables())["inputs"]["growth_years_3_10"]
    assert d["cohort"] == "operating:bucket_0-1" and d["growth_basis"] == "latest-year revenue growth"
    # a year with n < 50 is not printed (k = 10 holds n = 100 here, so every year from 3 is measured)
    assert d["by_k"][10]["n"] == 100 and d["ratio"]["p10"] == -2
    none = pr.ranges_for(rec(g3=None, g_latest=None), "2026-10-16", tables=fixture_tables())["inputs"]["growth_years_3_10"]
    assert none["available"] is False


def test_a_family_with_no_growth_table_reads_the_operating_familys_and_says_so():
    d = pr.ranges_for(rec(family="commodity"), "2026-10-16", tables=fixture_tables())["inputs"]["growth_years_3_10"]
    assert d["available"] and d["fallbacks"] == ["the family's growth_decay table is unmeasured: the operating family's table"]


def test_a_financial_reads_tangible_book_growth():
    d = pr.ranges_for(rec(family="financial", tg3=0.08), "2026-10-16", tables=fixture_tables())["inputs"]["growth_years_3_10"]
    assert d["available"] and d["what"] == "tangible book" and d["growth_basis"] == "3-year tangible-book CAGR" and d["terminal_reference"] == 0.09


# ---- the 10-year revenue CAGR (step 2c: the terminal table, never terminal_g's range): the family and the shrinking stratum ---------------------------------------------------------------------------------

def test_the_10_year_revenue_cagr_is_the_family_and_the_shrinking_stratum_when_the_revenue_trend_is_below_zero():
    T = fixture_tables()
    d = pr.ranges_for(rec(trend8=0.02), "2026-10-16", tables=T)["inputs"]["revenue_cagr_10y"]
    assert d["cohort"] == "operating:all:with_delisted" and d["n"] == 10000 and d["K"] == 10 and d["quantiles"]["p95"] == 0.55
    d = pr.ranges_for(rec(trend8=-0.03), "2026-10-16", tables=T)["inputs"]["revenue_cagr_10y"]
    assert d["cohort"] == "operating:shrinking:with_delisted" and d["n"] == 440 and d["quantiles"]["p50"] == 0.005
    assert "revenue trend was falling" in d["cohort_text"]
    d = pr.ranges_for(rec(trend8=0.0), "2026-10-16", tables=T)["inputs"]["revenue_cagr_10y"]
    assert d["stratum"] == "all"                                                     # 0 is not below 0
    d = pr.ranges_for(rec(trend8=None), "2026-10-16", tables=T)["inputs"]["revenue_cagr_10y"]
    assert d["stratum"] == "all" and "not measured" in d["fallbacks"][0]
    d = pr.ranges_for(rec(family="commodity", trend8=-0.03), "2026-10-16", tables=T)["inputs"]["revenue_cagr_10y"]
    assert d["stratum"] == "all" and d["n"] == 260 and "too few shrinking commodity companies (n=0)" in d["fallbacks"][0]


# ---- the return on new investment ---------------------------------------------------------------------------------------------------------





def test_a_family_the_tables_do_not_measure_gets_no_range():
    got = pr.ranges_for(rec(family="family_not_built"), "2026-10-16", tables=fixture_tables())
    assert all(not d["available"] and "family_not_built" in d["reason"] for d in got["inputs"].values())


# ---- the family rules ----------------------------------------------------------------------------------------------------------------------

ROWS = {y: {"revenue": 1e9 * (1 + 0.05 * (y - 2016)), "operating_income": 1e8, "total_assets": 2e9, "insurance_reserves": None} for y in range(2016, 2026)}


@pytest.mark.parametrize("sic, fam", [("3674", "operating"), ("1311", "commodity"), ("6022", "financial"), ("6282", "operating"),
                                      ("6798", "family_not_built"), ("4931", "family_not_built"), (None, "operating")])
def test_the_family_follows_the_sic_rules(sic, fam):
    assert pr.family_for(sic, ROWS)["family"] == fam


def test_insurance_reserves_make_a_financial_and_three_loss_years_a_pre_profit_company():
    rows = {y: dict(r) for y, r in ROWS.items()}
    rows[2025]["insurance_reserves"] = 3e8                 # 15% of total assets
    got = pr.family_for("3674", rows)
    assert got["family"] == "financial" and "15.0% of total assets" in got["reason"]
    rows = {y: dict(r, operating_income=(-1.0 if y >= 2023 else 1e8)) for y, r in ROWS.items()}
    got = pr.family_for("3674", rows)
    assert got["family"] == "family_not_built" and got["reason"].startswith("pre_profit: operating income <= 0 in 3 of the last 4")
    assert "lending_book_test_not_evaluated" in got["stamps"]


# ---- the company record --------------------------------------------------------------------------------------------------------------------

def _hist():
    margins = [0.10, 0.14, 0.09, 0.12, 0.08, 0.13, 0.11, 0.10, 0.16, 0.15]
    rows = {}
    for i, y in enumerate(range(2016, 2026)):
        rev = 1e9 * (1.06 ** i)
        rows[str(y)] = {"revenue": rev, "operating_income": rev * margins[i], "net_income": rev * margins[i] * 0.7, "amortization_intangibles": 0.0,
                        "pretax_income": rev * margins[i], "tax_provision": rev * margins[i] * 0.2, "equity": 5e8, "cash": 1e8, "st_investments": None,
                        "debt_lt_noncurrent": 2e8, "debt_current": 5e7, "short_term_borrowings_separate": None, "interest_expense": 1e7,
                        "goodwill": 0.0, "intangibles_ex_goodwill": 0.0, "preferred_equity": None}
    return rows, margins


def test_the_company_record_is_the_rebuilds_features_on_the_fiscal_year_rows():
    rows, margins = _hist()
    r = pr.company_record(rows, family="operating")
    assert r["base_year"] == 2025 and r["rev"] == pytest.approx(1e9 * 1.06 ** 9)
    assert r["g_latest"] == pytest.approx(0.06) and r["g3"] == pytest.approx(0.06)
    assert r["m"] == pytest.approx(0.15) and r["n8"] == 8
    assert r["med8"] == pytest.approx(statistics.median(margins[2:])) and r["dev"] == pytest.approx(0.15 - r["med8"])
    assert r["trend8"] == pytest.approx(math.log(1.06))                  # ln revenue is a straight line in the year
    # ROIC: NOPAT at the median tax rate (20%) over equity + debt - cash
    assert r["tax"] == pytest.approx(0.2) and r["roic"] == pytest.approx(rows["2025"]["operating_income"] * 0.8 / (5e8 + 2.5e8 - 1e8))
    # earnings margin X / revenue = net income / revenue (no amortization): 0.7 x the operating margin
    assert r["em_current"] == pytest.approx(0.7 * 0.15) and r["em_trend"] == pytest.approx(0.7 * statistics.median(margins[2:]))
    # the cyclicality score, by hand on the latest 10 margins (fewer than 12 held) and revenues
    s = statistics.pstdev(margins)
    mv = s / (s + abs(statistics.median(margins)))
    d = [b - a for a, b in zip(margins, margins[1:])]
    rf = sum(1 for a, b in zip(d, d[1:]) if a * b < 0) / (len(d) - 1)
    md = sum(d) / len(d)
    rho = sum((a - md) * (b - md) for a, b in zip(d, d[1:])) / sum((x - md) ** 2 for x in d)
    ac = (1 - max(-1.0, min(1.0, rho))) / 2
    # ln revenue is exactly linear: the residual is 0, so the revenue component is 0
    assert r["cyc_components"]["revenue_cyclicality"] == pytest.approx(0.0, abs=1e-12)
    assert r["cyc_score"] == pytest.approx((mv + rf + ac + 0.0) / 4) and r["cyc_years"] == 10


def test_a_record_too_short_for_the_cyclicality_score_says_why_and_a_cut_off_base_year_is_honoured():
    rows, _ = _hist()
    short = {y: r for y, r in rows.items() if int(y) >= 2021}
    r = pr.company_record(short, family="operating")
    assert r["cyc_score"] is None and any("fewer than 6 annual years" in m for m in r["missing"]) and r["med8"] == pytest.approx(statistics.median([0.13, 0.11, 0.10, 0.16, 0.15]))
    r = pr.company_record(rows, base_year=2022, family="operating")
    assert r["base_year"] == 2022 and r["m"] == pytest.approx(0.11)          # 2022 is the seventh year held


# ---- the section's text --------------------------------------------------------------------------------------------------------------------
