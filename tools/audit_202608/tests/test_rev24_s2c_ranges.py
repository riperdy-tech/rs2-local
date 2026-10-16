"""Revision 24 step 2c (BRIEF_R24_S2c_ranges_fix.md items 1-5; PHASE_4_AMENDMENTS.md "Revision 24 step 2b", rulings 1, 2, 5, 6 and 7): the rebuilt
population ranges, on the fixture tables of test_rev24_s2b_ranges.py (numbers chosen so every answer is computed by hand here).

- the long-run margin is the rebuild's margin_target: the operating margin level five years out, centred on the median-retention path at year 5 (the
  8-year median plus r_5 x the deviation; the commodity family's r_5 the normalization curve at its score), the spread the year-5 residual of the
  group of the cell holding the company's current operating margin, merged up and refused, named, under MIN_N; printed also in earnings-margin terms
  by the paired translation of cross-check 19 (ruling A), earnings_q = (1 - t) x OM_q + Delta, Delta the median of the record's m_t - (1 - tax_t) x OM_t;
- the translation's tax rate: the record's median effective rate, years failing net income + tax = pre-tax income skipped, 21% outside [0, 0.5];
  each year's own rate in Delta, 21% stamped per year;
- the ROIC level five years out (the rebuild's `ronic`), around the table's own population median of the latest complete fiscal year;
- the `terminal` table is the 10-year revenue CAGR; terminal_g has no population line; `ronic` and `ronic_fade` are not printed;
- an unmeasured family prints "no measured population for this family" per input.
The parity with valuation/priors.py on 30 real companies at 2 dates is scratch/rev23/r24_s2c/parity_population_ranges.py (a script, run in the
rebuild's interpreter)."""
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import population_ranges as pr  # noqa: E402
from test_rev24_s2b_ranges import QK, band, fixture_tables, lvl, q, rec  # noqa: E402

D = "2026-10-16"


def lrm(**kw):
    return pr.ranges_for(rec(**kw), D, tables=fixture_tables())["inputs"]["long_run_margin"]


def tab(T, **kw):
    return pr.ranges_for(rec(**kw), D, tables=T)["inputs"]


def approx_q(got, want):
    assert [got[k] for k in QK] == pytest.approx(list(want), abs=1e-12)


# ---- the long-run margin: margin_target ---------------------------------------------------------------------------------------------------

def test_the_margin_range_is_the_median_path_plus_the_residual_of_the_current_margin_band():
    d = lrm()
    # mid_pos: r_5 = the band's year-5 median 0.5; centre 10% + 0.5 x 5 points = 12.5%; the operating margin 15% is in the group [12%, open)
    assert d["available"] and d["cohort"] == "mid_pos" and d["residual_cell"] == "mid_pos" and d["n"] == 180 and d["n_cell"] == 300
    assert d["r5"] == 0.5 and d["r5_source"] == "band mid_pos curve" and d["level5_median"] == pytest.approx(0.125)
    approx_q(d["operating"], [0.125 + x for x in (-0.20, -0.12, -0.04, 0.01, 0.03, 0.06, 0.10)])
    assert d["level_band"]["lower"] == 0.12 and d["level_band"]["upper"] is None and d["fallbacks"] == []
    # cross-check 19 ruling A: earnings = (1 - t 20%) x operating + Delta (-2 points)
    approx_q(d["earnings"], [0.8 * (0.125 + x) - 0.02 for x in (-0.20, -0.12, -0.04, 0.01, 0.03, 0.06, 0.10)])
    assert d["earnings"]["p5"] == pytest.approx(-0.08) and d["earnings"]["p50"] == pytest.approx(0.088) and d["earnings"]["p95"] == pytest.approx(0.16)
    assert d["delta"] == -0.02 and d["tax_t"] == 0.20


def test_the_spread_is_the_group_holding_the_current_margin():
    d = lrm(m=0.11, dev=0.01)                         # 11% is below the 12% cut: the lower group
    assert d["n"] == 120 and d["level_band"]["upper"] == 0.12
    approx_q(d["operating"], [0.105 + x for x in (-0.10, -0.06, -0.02, 0.0, 0.02, 0.05, 0.08)])


def test_a_curve_measured_to_a_year_before_five_holds_its_last_value():
    T = fixture_tables()
    rows = T["margin_retention"]["bands"]["mid_pos"]["ks"]
    rows[2]["n"] = 10                                  # year 3 under MIN_N: the curve stops at year 2 (median 0.9 - 0.2), and holds it
    d = tab(T)["long_run_margin"]
    assert d["r5"] == pytest.approx(0.7) and d["level5_median"] == pytest.approx(0.10 + 0.7 * 0.05)


def test_a_retention_above_one_is_clipped_as_the_rebuild_clips_its_curve():
    T = fixture_tables()
    T["margin_retention"]["bands"]["mid_pos"]["ks"][4]["median"] = 1.4
    assert tab(T)["long_run_margin"]["r5"] == 1.0


def test_a_thin_residual_cell_is_merged_up_and_said_and_a_cell_thin_everywhere_is_refused_by_name():
    T = fixture_tables()
    T["margin_retention"]["residual_k5_by_level"]["mid_pos"]["n"] = 40
    d = tab(T)["long_run_margin"]
    assert d["residual_cell"] == "pooled_pos" and d["cohort"] == "mid_pos"
    assert "margin_target: residual cell of band mid_pos has n=40 < 50: merged up to pooled_pos (n=3000)" in d["fallbacks"]
    approx_q(d["operating"], [0.125 + x for x in (-0.15, -0.10, -0.03, 0.0, 0.03, 0.07, 0.12)])
    for k in ("pooled_pos", "pooled_all"):
        T["margin_retention"]["residual_k5_by_level"][k]["n"] = 40
    d = tab(T)["long_run_margin"]
    assert d["available"] is False
    assert d["reason"] == "margin_target: no residual cell with n >= 50 after the stated merges (mid_pos n=40; pooled_pos n=40; pooled_all n=40)"


def test_a_group_under_min_n_inside_a_large_cell_is_merged_to_the_next_cell():
    T = fixture_tables()
    T["margin_retention"]["residual_k5_by_level"]["mid_pos"]["groups"][1]["n"] = 49
    assert tab(T)["long_run_margin"]["residual_cell"] == "pooled_pos"


def test_no_current_margin_and_no_eight_year_median_follow_the_rebuild():
    d = lrm(m=None, dev=None)
    assert d["available"] is False and d["reason"] == "margin_target: no current operating margin to place in a level band"
    d = lrm(med8=None, dev=None)                     # centred on the margin held (priors.state_median), the pooled cell
    assert d["available"] and d["cohort"] == "pooled_all" and d["centre_basis"].startswith("base-year")
    approx_q(d["operating"], [0.15 + x for x in (-0.12, -0.08, -0.02, 0.0, 0.02, 0.05, 0.09)])
    assert d["earnings"]["p50"] == pytest.approx(0.8 * 0.15 - 0.02)          # the translation needs no 8-year median (ruling A)


def test_without_a_paired_gap_the_operating_range_stands_and_the_earnings_range_says_why():
    d = lrm(delta=None, delta_source="no fiscal year of FY2018-FY2025 with both an earnings margin and an operating margin")
    assert d["available"] and d["operating"]["p50"] == pytest.approx(0.135)
    assert d["earnings"] is None and "with both an earnings margin and an operating margin" in d["earnings_reason"]
    assert pr.gate_bounds({"inputs": {"long_run_margin": d}})["long_run_margin"] is None
    sec = pr.render_section({"vintage": 2025, "inputs": {"long_run_margin": d}}, True)
    assert "translated estimate from operating-margin tables, margin five years out): not available" in sec
    assert "- long_run_margin context (the operating margin five years out, the tables' unit): P10 0.5%" in sec


def _gap_rows(years):
    """{year: row}: revenue 100, operating income `oi`, pre-tax `pt`, tax `tx`, net income pt - tx (+ `ni_off`), no amortization."""
    out = {}
    for y, (oi, pt, tx, ni_off) in years.items():
        out[y] = {"revenue": 100.0, "operating_income": oi, "pretax_income": pt, "tax_provision": tx,
                  "net_income": (None if pt is None or tx is None else pt - tx + ni_off), "amortization_intangibles": 0.0}
    return out


def test_the_paired_gap_is_the_median_of_each_years_earnings_margin_less_its_after_tax_operating_margin():
    # three years: (operating 20, pre-tax 18, tax 4.5 -> m 13.5%, t 25%) gap 13.5 - 0.75 x 20 = -1.5 points; (10, 9, 1.8 -> 7.2%, 20%) gap -0.8;
    # (30, 25, 0 -> 25%, 0%) gap -5; median -1.5 points
    rows = _gap_rows({2023: (20.0, 18.0, 4.5, 0.0), 2024: (10.0, 9.0, 1.8, 0.0), 2025: (30.0, 25.0, 0.0, 0.0)})
    got = pr.paired_gap(rows, rows, 2025)
    assert got["delta"] == pytest.approx(-0.015) and got["delta_years"] == [2023, 2024, 2025] and got["delta_tax_fallback_years"] == []


def test_a_year_without_a_usable_tax_rate_takes_the_statutory_rate_in_the_paired_gap_and_is_named():
    # 2024's identity fails (net income 5 points off): its rate is 21%; m = (9 - 1.8 + 5) / 100 = 12.2%, gap 12.2 - 0.79 x 10 = 4.3 points
    rows = _gap_rows({2023: (20.0, 18.0, 4.5, 0.0), 2024: (10.0, 9.0, 1.8, 5.0), 2025: (30.0, 25.0, 0.0, 0.0)})
    got = pr.paired_gap(rows, rows, 2025)
    assert got["delta_tax_fallback_years"] == [2024] and "21% statutory in FY2024" in got["delta_source"]
    assert got["delta"] == pytest.approx(-0.015)                          # the median of -1.5, +4.3 and -5 points
    assert pr.year_tax({"pretax_income": 10.0, "tax_provision": 6.0, "net_income": 4.0}) == (0.21, "the rate 60.0% is outside [0%, 50%]")
    assert pr.paired_gap({}, {}, 2025)["delta"] is None


def test_a_commodity_company_is_centred_on_the_normalization_curve_at_its_score():
    d = lrm(family="commodity", cyc_score=0.45)
    # the quintile curves at year 5: 0.10 at score median 0.4 and 0.15 at 0.5; at 0.45, 0.125
    assert d["cohort"] == "mid_pos" and d["r5_source"] == "normalization curve of the cyclicality score" and d["r5"] == pytest.approx(0.125)
    assert d["operating"]["p50"] == pytest.approx(0.10 + 0.125 * 0.05 + 0.01)
    beyond = lrm(family="commodity", cyc_score=0.95)  # past the top band (0.7): its value, held flat
    assert beyond["r5"] == pytest.approx(0.25)
    none = lrm(family="commodity", cyc_score=None)     # no score: the band curve (pooled_pos, 0.7), as priors.py keeps it
    assert none["cohort"] == "pooled_pos" and none["r5"] == pytest.approx(0.7) and none["r5_source"] == "band pooled_pos curve"


# ---- the translation's tax rate (ruling 2) -------------------------------------------------------------------------------------------------

def _tax_rows(rates, fail=()):
    out = {}
    for i, t in enumerate(rates):
        y = 2018 + i
        pt = 100.0
        tx = None if t is None else t * pt
        ni = None if tx is None else pt - tx + (20.0 if y in fail else 0.0)
        out[y] = {"pretax_income": pt, "tax_provision": tx, "net_income": ni}
    return out


def test_the_tax_rate_is_the_records_median_and_years_failing_the_identity_are_not_read():
    got = pr.translation_tax(_tax_rows([0.20, 0.25, 0.10, 0.30, 0.22, 0.18, 0.21, 0.24]), 2025)
    assert got["tax_t"] == pytest.approx(0.215) and got["tax_t_stamps"] == [] and "8 fiscal years, FY2018-FY2025" in got["tax_t_source"]
    got = pr.translation_tax(_tax_rows([0.20, 0.25, 0.10, 0.30, 0.22, 0.18, 0.21, 0.24], fail=(2021,)), 2025)
    assert got["tax_t"] == pytest.approx(0.21) and 2021 not in got["tax_t_years"] and "FY2021 not read" in got["tax_t_source"]


def test_the_statutory_rate_stands_in_outside_zero_to_fifty_percent_or_with_no_year_and_is_stamped():
    got = pr.translation_tax(_tax_rows([0.6] * 8), 2025)
    assert got["tax_t"] == 0.21 and got["tax_t_stamps"] == ["tax_rate_statutory_fallback"] and "outside [0%, 50%]" in got["tax_t_source"]
    got = pr.translation_tax(_tax_rows([None] * 8), 2025)
    assert got["tax_t"] == 0.21 and got["tax_t_stamps"] == ["tax_rate_statutory_fallback"]
    got = pr.translation_tax(_tax_rows([0.0] * 8), 2025)     # 0.0 is a value: inside [0, 0.5]
    assert got["tax_t"] == 0.0 and got["tax_t_stamps"] == []


# ---- the ROIC level five years out (ruling 6) -----------------------------------------------------------------------------------------------

def test_the_roic_range_is_the_median_path_from_the_population_median_plus_the_residual_of_the_current_roic_band():
    d = tab(fixture_tables())["terminal_ronic"]
    # base FY 2025, vintage 2025: the reference year is 2024 (the vintage's own cut year holds early filers only), I = 10%; L0 25%, gap +15 points:
    # band pos, phi_5 = 0.9 - 0.5 = 0.4; centre 10% + 0.4 x 15 points = 16%; 25% is in the group [20%, open)
    assert d["available"] and d["band"] == "pos" and d["residual_cell"] == "pos" and d["reference"] == 0.10 and d["reference_year"] == 2024
    assert d["reference_stamps"] == ["roic_reference_population_median_not_industry", "roic_reference_year_2024_for_base_year_2025"]
    assert d["phi5"] == pytest.approx(0.4) and d["level5_median"] == pytest.approx(0.16) and d["n"] == 1500
    approx_q(d["quantiles"], [0.16 + x for x in (-0.40, -0.25, -0.08, -0.01, 0.07, 0.20, 0.35)])


@pytest.mark.parametrize("roic3, base_year, want_band, want_median", [
    (0.11, 2023, "pos", 0.09 + (0.9 - 0.5) * 0.02),          # base FY 2023: I = the 2023 median 9%; a gap of exactly 2 points is a direction
    (0.105, 2025, "all", 0.10 + (0.85 - 0.40) * 0.005),      # within 2 points of 10%: both sides pooled
    (0.05, 2025, "neg", 0.10 + (0.95 - 0.35) * -0.05),
])
def test_the_roic_band_is_the_sign_of_the_gap_beyond_two_points(roic3, base_year, want_band, want_median):
    d = tab(fixture_tables(), roic3=roic3, base_year=base_year)["terminal_ronic"]
    assert d["band"] == want_band and d["level5_median"] == pytest.approx(want_median)


def test_a_thin_roic_cell_merges_to_all_and_no_trailing_roic_or_reference_is_refused_by_name():
    T = fixture_tables()
    T["roic_level"]["residual_k5_by_level"]["pos"]["n"] = 40
    d = tab(T)["terminal_ronic"]
    assert d["residual_cell"] == "all" and "ronic: residual cell pos has n=40 < 50: merged to all (n=6000)" in d["fallbacks"]
    assert tab(fixture_tables(), roic3=None)["terminal_ronic"]["reason"].startswith("ronic: no trailing 3-year ROIC")
    T = fixture_tables()
    T["roic_level"]["reference_by_year"] = {"2025": 0.13}            # only the cut year: no complete year to read
    assert "no population median ROIC" in tab(T)["terminal_ronic"]["reason"]


def test_the_trailing_roic_is_the_mean_of_three_consecutive_defined_years():
    rows = {}
    for y, oi in zip(range(2019, 2026), (5, 6, 7, 8, 9, 10, 12)):
        rows[str(y)] = {"revenue": 100.0, "operating_income": float(oi), "pretax_income": float(oi), "tax_provision": 0.2 * oi, "net_income": 0.8 * oi,
                        "equity": 50.0, "cash": 10.0, "st_investments": None, "debt_lt_noncurrent": 20.0, "debt_current": None,
                        "short_term_borrowings_separate": None, "interest_expense": 1.0}
    r = pr.company_record(rows, family="operating")
    assert r["tax"] == pytest.approx(0.2) and r["roic3"] == pytest.approx((0.8 * (10 + 9 + 12) / 3) / 60.0)
    del rows["2024"]
    assert pr.company_record(rows, family="operating")["roic3"] is None      # a gap in the three years: none


# ---- the other lines and the section --------------------------------------------------------------------------------------------------------

def test_the_normalization_line_is_the_band_and_its_median_path_without_the_share_turned_into_levels():
    d = tab(fixture_tables(), cyc_score=0.52)["normalization"]
    assert d["available"] and d["band"] == 2 and d["n"] == 500 and d["retention_median"] == pytest.approx(0.15)
    assert d["op_median_path"] == pytest.approx(0.10 + 0.15 * 0.05) and "levels" not in d


def test_the_section_prints_the_rebuilt_lines_with_p50_only_on_its_flag():
    got = pr.ranges_for(rec(), D, tables=fixture_tables())
    no, yes = pr.render_section(got, False), pr.render_section(got, True)
    assert set(got["inputs"]) == set(pr.INPUTS) == {"long_run_margin", "normalization", "growth_years_3_10", "revenue_cagr_10y", "terminal_ronic"}
    assert "terminal_g population" not in yes and "ronic_fade" not in yes and "fade of the return" not in yes
    assert "- 10-year revenue CAGR (context for your growth path; it bounds the revenue growth to year 10 your inputs imply): " in yes
    assert "- terminal_ronic context (the return on invested capital five years out): " in yes
    lm = next(l for l in yes.split("\n") if l.startswith("- long_run_margin population"))
    assert lm.startswith("- long_run_margin population (translated estimate from operating-margin tables, margin five years out): ")
    assert "earnings margin: P10 -1.6%, P25 4.8%, P50 8.8%, P75 10.4%, P90 12.8%" in lm and "measured five years out" in lm
    ctx_line = next(l for l in yes.split("\n") if l.startswith("- long_run_margin context"))
    assert "(the operating margin five years out, the tables' unit): P10 0.5%, P25 8.5%, P50 13.5%, P75 15.5%, P90 18.5%" in ctx_line
    assert "t = 20.0%" in ctx_line and "Delta = -2.0%" in ctx_line and "om_tc 10.0%, m_tc 8.0%" in ctx_line
    assert " P50 " not in no and re.sub(r", P50 [^,|]+(?=, )| P50 [+-][\d.]+%", "", yes) == no


def test_an_unmeasured_family_prints_no_measured_population_per_input():
    nb = pr.render_section(pr.ranges_for(rec(family="family_not_built", family_reason="SIC 4932: regulated_utility_or_pipeline"), D,
                                         tables=fixture_tables()), True)
    lines = nb.split("\n")[1:]
    assert len(lines) == 5 and all("no measured population for this family" in l for l in lines) and "SIC 4932" in lines[0]
    assert "five years out" in lines[0] and "five years out" in lines[4]
    fin = pr.ranges_for(rec(family="financial", tg3=0.08), D, tables=fixture_tables())
    assert pr.family_unmeasured(fin, "long_run_margin") and pr.family_unmeasured(fin, "terminal_ronic")
    assert not pr.family_unmeasured(fin, "revenue_cagr_10y") and fin["inputs"]["revenue_cagr_10y"]["available"]


def test_the_gate_bounds_are_the_earnings_margin_the_revenue_cagr_and_the_roic_level_and_terminal_g_has_none():
    b = pr.gate_bounds(pr.ranges_for(rec(trend8=-0.03), D, tables=fixture_tables()))
    assert set(b) == {"long_run_margin", "revenue_cagr_10y", "terminal_ronic", "earnings_ratio_10y"}
    assert b["long_run_margin"]["p5"] == pytest.approx(-0.08) and b["long_run_margin"]["p95"] == pytest.approx(0.16)
    assert b["long_run_margin"]["p10"] == pytest.approx(-0.016) and b["long_run_margin"]["p90"] == pytest.approx(0.128)
    assert b["revenue_cagr_10y"]["p5"] == -0.20 and b["revenue_cagr_10y"]["K"] == 10
    assert b["terminal_ronic"]["p5"] == pytest.approx(-0.24) and b["terminal_ronic"]["p95"] == pytest.approx(0.51)
    assert b["earnings_ratio_10y"] is None

