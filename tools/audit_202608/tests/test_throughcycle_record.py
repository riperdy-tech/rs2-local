"""Revision 17 (brief B section 1, tests 1; brief B2 fixes F1-F5): the company's own record, on synthetic histories.

tools/throughcycle_record.py is pure: fiscal-year rows in, a dict out. Every row below is a fixture
written for the test (not a real company's filing). Money is in plain numbers (dollars).
"""
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE / "tools"))

import throughcycle_record as tc  # noqa: E402

INF = math.inf
R = 0.09          # the cost-of-equity anchor these histories are measured against


def row(year, revenue=1000.0, ni=100.0, equity=500.0, goodwill=0.0, intangibles=0.0, amort=0.0,
        pretax=None, tax=None, ca=None, cl=None, cash=0.0, sti=None, lti=None, dc=None, stb=None,
        lt_nc=None, lt=None, interest=None):
    d = {"revenue": revenue, "net_income": ni, "equity": equity, "goodwill": goodwill,
         "intangibles_ex_goodwill": intangibles, "amortization_intangibles": amort,
         "pretax_income": pretax, "tax_provision": tax, "current_assets": ca, "current_liabilities": cl,
         "cash": cash, "st_investments": sti, "lt_investments": lti, "debt_current": dc,
         "short_term_borrowings_separate": stb, "debt_lt_noncurrent": lt_nc, "lt_debt": lt,
         "interest_expense": interest}
    return d


def history(first, last, make):
    return {y: make(y) for y in range(first, last + 1)}


# ---- the pieces ---------------------------------------------------------------------------------

def test_median_accepts_infinities_and_returns_none_when_the_middle_is_undefined():
    assert tc.median([3.0, 1.0, 2.0]) == 2.0
    assert tc.median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert tc.median([INF, INF, 1.0]) == INF
    assert tc.median([-INF, 1.0, 5.0]) == 1.0
    assert tc.median([-INF, -INF, 1.0, INF]) == -INF            # the two middle values are -inf and 1.0: -inf
    assert tc.median([1.0, 2.0, INF, INF]) == INF               # 2.0 and inf: inf
    assert tc.median([-INF, -INF, INF, INF]) is None            # -inf and +inf: no median
    assert tc.median([]) is None


def test_theil_sen_is_the_median_of_pairwise_slopes_and_shrugs_off_an_outlier():
    pts = [(2018, 1.0), (2019, 2.0), (2020, 3.0), (2021, 4.0), (2022, 5.0), (2023, 6.0), (2024, 7.0), (2025, 100.0)]
    assert tc.theil_sen(pts) == pytest.approx(1.0)              # OLS would say ~ 12
    assert tc.theil_sen([(2020, 1.0)]) is None
    # an exact exponential: the slope of ln is the log growth
    g = 0.05
    exp_pts = [(y, math.log(100.0) + g * (y - 2018)) for y in range(2018, 2026)]
    assert tc.theil_sen(exp_pts) == pytest.approx(g)


def test_tax_rate_is_clipped_and_defaults_when_it_cannot_be_computed():
    assert tc.tax_rate({"pretax_income": 100.0, "tax_provision": 25.0}) == 0.25
    assert tc.tax_rate({"pretax_income": 100.0, "tax_provision": 60.0}) == tc.TAX_MAX      # clipped to 0.35
    assert tc.tax_rate({"pretax_income": 100.0, "tax_provision": -10.0}) == 0.0            # clipped to 0
    assert tc.tax_rate({"pretax_income": 0.0, "tax_provision": 5.0}) == tc.TAX_DEFAULT      # not computable
    assert tc.tax_rate({"pretax_income": None, "tax_provision": 5.0}) == tc.TAX_DEFAULT
    assert tc.tax_rate({}) == 0.21


def test_tangible_equity_untagged_counts_zero_and_a_null_in_a_tagged_series_subtracts_only_what_is_known():
    r0 = {"equity": 100.0, "goodwill": 30.0, "intangibles_ex_goodwill": 10.0}
    assert tc.tangible_equity(r0) == 60.0 and tc.tangible_equity_detail(r0) == (60.0, False)
    # untagged: 0, not a gap
    assert tc.tangible_equity_detail(dict(r0, goodwill=None), untagged=("goodwill",)) == (90.0, False)
    assert tc.tangible_equity_detail(dict(r0, intangibles_ex_goodwill=None),
                                     untagged=("intangibles_ex_goodwill",)) == (70.0, False)
    # F3: a null in a series the filer tags is a partial year, not a missing one: only the known one is subtracted
    assert tc.tangible_equity_detail(dict(r0, goodwill=None)) == (90.0, True)
    assert tc.tangible_equity_detail(dict(r0, intangibles_ex_goodwill=None)) == (70.0, True)
    assert tc.tangible_equity_detail(dict(r0, goodwill=None, intangibles_ex_goodwill=None)) == (100.0, True)
    assert tc.tangible_equity_detail(dict(r0, equity=None)) == (None, False)
    assert tc.tangible_equity(dict(r0, goodwill=0.0)) == 90.0                                   # a filed zero is a value


def test_adjusted_earnings_adds_back_amortization_after_tax_and_a_gap_uses_net_income():
    r0 = {"net_income": 100.0, "amortization_intangibles": 20.0, "pretax_income": 100.0, "tax_provision": 25.0}
    assert tc.adjusted_earnings(r0) == pytest.approx(100.0 + 20.0 * 0.75)
    assert tc.earnings_detail(r0)[1] is False
    # untagged amortization counts 0
    assert tc.earnings_detail(dict(r0, amortization_intangibles=None), untagged=("amortization_intangibles",)) == (100.0, False)
    # F1/F3: a null in a tagged series uses net income for that year and is a gap (no longer a missing year)
    assert tc.earnings_detail(dict(r0, amortization_intangibles=None)) == (100.0, True)
    assert tc.adjusted_earnings(dict(r0, net_income=None)) is None
    # a filed zero amortization is a value: X is net income and nothing is stamped
    assert tc.earnings_detail(dict(r0, amortization_intangibles=0.0)) == (100.0, False)


def test_short_term_debt_is_subtracted_once_and_separate_borrowings_add_only_for_a_current_portion_tag():
    # F4: equal within 0.5% is the same debt, whatever the tag
    assert tc.short_term_debt({"debt_current": 20.0, "short_term_borrowings_separate": 20.0}) == 20.0
    assert tc.short_term_debt({"debt_current": 20.0, "short_term_borrowings_separate": 20.09},
                              dc_tag="LongTermDebtCurrent") == 20.0
    assert tc.short_term_debt({"debt_current": 20.0, "short_term_borrowings_separate": 20.0},
                              dc_tag="ShortTermBorrowings") == 20.0
    # different, and the debt_current tag is a current-portion-of-long-term-debt tag: the two are added
    for tag in sorted(tc.CURRENT_PORTION_TAGS):
        assert tc.short_term_debt({"debt_current": 20.0, "short_term_borrowings_separate": 10.0}, dc_tag=tag) == 30.0
    # different but debt_current is the short-term borrowings tag (or another): debt_current alone
    assert tc.short_term_debt({"debt_current": 20.0, "short_term_borrowings_separate": 10.0},
                              dc_tag="ShortTermBorrowings") == 20.0
    # without provenance: debt_current alone
    assert tc.short_term_debt({"debt_current": 20.0, "short_term_borrowings_separate": 10.0}) == 20.0
    # no debt_current: the separate borrowings alone; nothing held is 0
    assert tc.short_term_debt({"debt_current": None, "short_term_borrowings_separate": 10.0}, dc_tag="LongTermDebtCurrent") == 10.0
    assert tc.short_term_debt({}) == 0.0
    assert tc.short_term_debt({"debt_current": 0.0, "short_term_borrowings_separate": 0.0}) == 0.0   # 0.0 is a value


def test_resolve_run_tags_reads_provenance_runs():
    tags = ["ShortTermBorrowings", "LongTermDebtCurrent", "Other"]
    runs = [[2014, 0, "p"], [2019, 1, "p"]]
    assert tc.resolve_run_tags(runs, tags, [2012, 2014, 2018, 2019, 2025]) == {
        2014: "ShortTermBorrowings", 2018: "ShortTermBorrowings", 2019: "LongTermDebtCurrent", 2025: "LongTermDebtCurrent"}
    assert tc.resolve_run_tags(None, tags, [2020]) == {} and tc.resolve_run_tags(runs, None, [2020]) == {}
    assert tc.resolve_run_tags([[2014, 7, "p"]], tags, [2020]) == {}       # an index the tag list does not hold


def test_net_working_capital_needs_the_core_lines_and_zeroes_the_optional_ones():
    r0 = {"current_assets": 500.0, "cash": 100.0, "current_liabilities": 300.0}
    assert tc.net_working_capital(r0) == 400.0 - 300.0
    full = dict(r0, st_investments=50.0, debt_current=20.0, short_term_borrowings_separate=10.0)
    # F4: debt_current once (no provenance), both when the tag is a current-portion tag
    assert tc.net_working_capital(full) == (500.0 - 100.0 - 50.0) - (300.0 - 20.0)
    assert tc.net_working_capital(full, "LongTermDebtCurrent") == (500.0 - 100.0 - 50.0) - (300.0 - 20.0 - 10.0)
    assert tc.net_working_capital(full, "ShortTermBorrowings") == (500.0 - 100.0 - 50.0) - (300.0 - 20.0)
    same = dict(r0, debt_current=20.0, short_term_borrowings_separate=20.0)
    assert tc.net_working_capital(same, "LongTermDebtCurrent") == 400.0 - (300.0 - 20.0)       # subtracts once
    for missing in ("current_assets", "cash", "current_liabilities"):
        assert tc.net_working_capital(dict(r0, **{missing: None})) is None


def test_invested_capital_is_tangible_equity_plus_debt_less_cash_and_investments():
    r0 = row(2025, equity=500.0, goodwill=100.0, intangibles=50.0, cash=80.0, sti=20.0, lti=30.0,
             lt_nc=200.0, dc=40.0)
    assert tc.invested_capital(r0) == (500.0 - 150.0) + 200.0 + 40.0 - 80.0 - 20.0 - 30.0
    # long-term debt: the noncurrent line, else the total long-term debt line
    assert tc.invested_capital(row(2025, equity=500.0, lt=300.0)) == 800.0
    assert tc.invested_capital(row(2025, equity=500.0, lt_nc=0.0, lt=300.0)) == 500.0          # 0.0 is a value
    # short-term debt once (F4)
    both = row(2025, equity=500.0, dc=20.0, stb=20.0)
    assert tc.invested_capital(both, dc_tag="LongTermDebtCurrent") == 520.0
    assert tc.invested_capital(row(2025, equity=500.0, dc=20.0, stb=10.0), dc_tag="LongTermDebtCurrent") == 530.0
    # equity or cash missing: no invested capital
    assert tc.invested_capital(row(2025, equity=None)) is None and tc.invested_capital(row(2025, cash=None)) is None


# ---- histories ---------------------------------------------------------------------------------

def test_a_steady_compounder_has_p_one_no_cycle_and_a_return_above_the_cost_of_equity():
    # net income 100 -> 100 * 1.06^n on equity that grows a little slower: R stays near 20-25% every year
    rows = history(2014, 2025, lambda y: row(y, revenue=1000.0 * 1.06 ** (y - 2014), ni=100.0 * 1.06 ** (y - 2014),
                                              equity=400.0 * 1.05 ** (y - 2014)))
    rec = tc.analyse(rows, R)
    assert rec["base_year"] == 2025 and rec["window"] == [2018, 2025]
    assert rec["p"] == 1.0 and len(rec["p_years"]) == 8
    assert rec["R_tc"] > 0.20 and all(v > R for y, v in rec["R"].items() if y >= 2015)
    assert rec["ronic_t"] == pytest.approx(R + 1.0 * (rec["R_tc"] - R))
    assert rec["cycle"] is False and rec["cycle_year"] is None and rec["cycle_years"] == []
    assert rec["cycle_tested"] == 11
    assert rec["m_tc"] == pytest.approx(0.10) and rec["stamps"] == []
    assert rec["g_rev"] == pytest.approx(math.log(1.06))
    assert rec["g_rev_years"] == list(range(2018, 2026))


def test_a_cyclical_record_shows_the_cycle_years_and_its_median_margin():
    # earnings and revenue swing together: 150 on 1000 in the good years, 20 on 700 in the bad ones
    swing = {2014: 150, 2015: 150, 2016: 20, 2017: 20, 2018: 150, 2019: 150, 2020: 20, 2021: 150,
             2022: 150, 2023: 150, 2024: 20, 2025: 20}
    rows = history(2014, 2025, lambda y: row(y, revenue=(1000.0 if swing[y] == 150 else 700.0), ni=float(swing[y]),
                                              equity=500.0))
    rec = tc.analyse(rows, R)
    assert rec["cycle"] is True
    assert rec["cycle_years"] == [2016, 2020, 2024] and rec["cycle_year"] == 2024     # a fall from a good year into a bad one
    # the window 2018-2025: X / revenue is 0.15 in five years and 20/700 in three -> median 0.15
    assert rec["m_tc"] == pytest.approx(0.15)
    # the return series sets R_tc, p and RONIC_T; it no longer decides the cycle
    assert rec["p"] == 5 / 8 and rec["p_years"] == [2018, 2019, 2021, 2022, 2023]
    assert rec["R_tc"] == pytest.approx(150.0 / 500.0)               # median of five 0.30 and three 0.04
    assert rec["ronic_t"] == pytest.approx(R + 5 / 8 * (0.30 - R))


def test_a_loss_year_with_rising_revenue_is_not_a_cycle():
    # an impairment year: earnings collapse, revenue keeps growing (F5)
    rows = history(2014, 2025, lambda y: row(y, revenue=1000.0 + 50.0 * (y - 2014), ni=(-300.0 if y == 2022 else 100.0)))
    rec = tc.analyse(rows, R)
    assert rec["cycle"] is False and rec["cycle_years"] == []
    assert rec["cycle_tested"] == 11


def test_a_thirty_percent_revenue_fall_with_earnings_down_sixty_percent_is_a_cycle_and_a_two_percent_fall_is_not():
    def make(rev_2022):
        return history(2014, 2025, lambda y: row(y, revenue=(rev_2022 if y == 2022 else 1000.0),
                                                  ni=(40.0 if y == 2022 else 100.0)))
    rec = tc.analyse(make(700.0), R)
    assert rec["cycle"] is True and rec["cycle_years"] == [2022] and rec["cycle_year"] == 2022
    # the bounce back is not a cycle year (revenue and earnings rose)
    assert tc.analyse(make(980.0), R)["cycle"] is False                 # revenue -2%: no cycle
    # earnings down only 30% on a 30% revenue fall: less than a third
    rows = history(2014, 2025, lambda y: row(y, revenue=(700.0 if y == 2022 else 1000.0), ni=(70.0 if y == 2022 else 100.0)))
    assert tc.analyse(rows, R)["cycle"] is False


def test_the_cycle_thresholds_are_inclusive_and_need_a_positive_prior_year():
    # revenue exactly -5% and X exactly down a third in 2022 only: a cycle year
    rows = history(2014, 2025, lambda y: row(y, revenue=(950.0 if y == 2022 else 1000.0), ni=(100.0 if y == 2022 else 150.0)))
    rec = tc.analyse(rows, R)
    assert rec["cycle_years"] == [2022] and rec["cycle"] is True
    # a loss year (revenue flat) followed by a deeper loss on a 50% revenue fall: the prior year's X is not
    # positive, so there is no fall from a positive base to measure
    rows = history(2014, 2025, lambda y: row(y, revenue=(500.0 if y == 2022 else 1000.0),
                                              ni=(-90.0 if y == 2022 else (-20.0 if y == 2021 else 100.0))))
    rec = tc.analyse(rows, R)
    assert rec["cycle_years"] == [] and rec["cycle"] is False


def test_the_cycle_is_none_when_no_year_could_be_tested():
    assert tc.analyse({2025: row(2025)}, R)["cycle"] is None
    rows = {y: row(y, revenue=None) for y in range(2020, 2026)}
    rec = tc.analyse(rows, R)
    assert rec["cycle"] is None and rec["cycle_tested"] == 0


def test_the_cycle_uses_x_not_net_income():
    # net income falls by more than a third, but X (amortization added back after tax) falls by less
    def make(y):
        ni = 60.0 if y == 2022 else 100.0
        return row(y, revenue=(700.0 if y == 2022 else 1000.0), ni=ni, amort=200.0, pretax=100.0, tax=0.0)
    rec = tc.analyse(history(2014, 2025, make), R)
    # X = NI + 200: 300 -> 260 is down 13%: not a cycle although net income fell 40%
    assert rec["cycle"] is False


def test_a_year_below_the_cost_of_equity_before_any_year_above_it_no_longer_decides_the_cycle():
    # returns high then low (or low then high) with flat revenue: no revenue fall, so no cycle either way
    rows = history(2014, 2025, lambda y: row(y, ni=(20.0 if y < 2020 else 150.0), equity=500.0))
    assert tc.analyse(rows, R)["cycle"] is False
    rows = history(2014, 2025, lambda y: row(y, ni=(150.0 if y < 2020 else 20.0), equity=500.0))
    assert tc.analyse(rows, R)["cycle"] is False


def test_invested_capital_at_or_below_zero_gives_infinite_returns_and_a_median_of_inf():
    # goodwill and intangibles exceed equity, no debt: invested capital is negative every year, earnings are positive
    rows = history(2014, 2025, lambda y: row(y, ni=100.0, equity=200.0, goodwill=250.0, intangibles=50.0))
    rec = tc.analyse(rows, R)
    assert all(v == INF for v in rec["R"].values())
    assert rec["R_tc"] == INF and rec["p"] == 1.0 and rec["ronic_t"] == INF
    # with losses on non-positive invested capital every year the return is -inf and RONIC_T is the cost of equity
    losing = history(2014, 2025, lambda y: row(y, ni=-10.0, equity=200.0, goodwill=250.0, intangibles=50.0))
    rec = tc.analyse(losing, R)
    assert all(v == -INF for v in rec["R"].values())
    assert rec["R_tc"] == -INF and rec["p"] == 0.0 and rec["ronic_t"] == R


def test_a_levered_record_with_near_zero_tangible_equity_gets_a_finite_return_on_invested_capital():
    # F2: tangible equity 10, long-term debt 990: the capital that earns the return is 1000, not 10
    rows = history(2014, 2025, lambda y: row(y, ni=100.0, equity=600.0, goodwill=590.0, lt_nc=990.0, interest=50.0))
    rec = tc.analyse(rows, R)
    t = tc.TAX_DEFAULT
    expected = (100.0 + 50.0 * (1.0 - t)) / 1000.0
    assert rec["R_tc"] == pytest.approx(expected) and all(v == pytest.approx(expected) for v in rec["R"].values())
    assert rec["R_tc"] < 1.0                                            # tangible equity alone would have said 10.0


def test_a_net_cash_records_return_rises_when_cash_is_removed_from_the_capital():
    no_cash = tc.analyse(history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, cash=0.0)), R)
    cash = tc.analyse(history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, cash=200.0)), R)
    assert no_cash["R_tc"] == pytest.approx(0.20) and cash["R_tc"] == pytest.approx(100.0 / 300.0)
    both = tc.analyse(history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, cash=100.0, sti=50.0, lti=50.0)), R)
    assert both["R_tc"] == pytest.approx(100.0 / 300.0)                # short- and long-term investments come out too


def test_the_return_divides_by_the_average_of_this_and_last_years_capital_or_this_years_alone():
    rows = {y: row(y, ni=100.0, equity=(400.0 if y == 2024 else 600.0)) for y in range(2018, 2026)}
    rec = tc.analyse(rows, R)
    assert rec["R"][2024] == pytest.approx(100.0 / ((600.0 + 400.0) / 2.0))     # 2023 was 600, 2024 is 400
    assert rec["R"][2025] == pytest.approx(100.0 / ((400.0 + 600.0) / 2.0))
    assert rec["R"][2018] == pytest.approx(100.0 / 600.0)                       # no prior year: this year's alone
    # a prior year whose capital is not positive is dropped from the average
    odd = {y: row(y, ni=100.0, equity=(-50.0 if y == 2024 else 600.0)) for y in range(2018, 2026)}
    assert tc.analyse(odd, R)["R"][2025] == pytest.approx(100.0 / 600.0)
    assert tc.analyse(odd, R)["R"][2024] == INF                                 # non-positive capital, positive profit


def test_a_year_without_cash_has_no_invested_capital_and_is_missing_from_the_returns():
    rows = {y: row(y, ni=100.0, equity=500.0, cash=(None if y == 2022 else 0.0)) for y in range(2014, 2026)}
    rec = tc.analyse(rows, R)
    assert rec["R"][2022] is None and 2022 not in rec["r_years"] and len(rec["r_years"]) == 7
    assert rec["R"][2023] == pytest.approx(100.0 / 500.0)               # the prior year's capital is missing: this year's alone


def test_partial_goodwill_years_keep_the_record_and_are_stamped():
    # F3: goodwill is tagged in the series but null in 2022 (nothing known to subtract)
    gap = history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, goodwill=(None if y == 2022 else 0.0)))
    rec = tc.analyse(gap, R)
    assert rec["R"][2022] == pytest.approx(100.0 / 500.0) and len(rec["r_years"]) == 8
    assert rec["tangible_equity_partial_years"] == [2022] and "tangible_equity_partial:2022" in rec["stamps"]
    assert "record_not_available" not in rec["stamps"]
    # a whole series that is null but not marked untagged is partial in every year, and still a record
    every = tc.analyse(history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, goodwill=None)), R)
    assert every["R_tc"] == pytest.approx(0.20) and len(every["r_years"]) == 8
    assert every["tangible_equity_partial_years"] == list(range(2014, 2026))
    # a series the marker lists is a filer that never tags it: counts 0 and is not stamped
    marked = tc.analyse(history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, goodwill=None)), R,
                        untagged_fields=["goodwill"])
    assert marked["R_tc"] == pytest.approx(0.20) and marked["tangible_equity_partial_years"] == []
    assert marked["untagged_fields"] == ["goodwill"] and marked["stamps"] == []
    # only the known component is subtracted in a partial year
    part = history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, goodwill=(None if y == 2025 else 100.0),
                                              intangibles=50.0))
    assert tc.analyse(part, R)["R"][2025] == pytest.approx(100.0 / ((350.0 + 450.0) / 2.0))   # 2024: 500-100-50; 2025: 500-50 (goodwill unknown)


def test_an_amortization_gap_uses_net_income_for_that_year_and_is_stamped():
    amort = history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, amort=(None if y == 2020 else 10.0),
                                              pretax=100.0, tax=25.0))
    rec = tc.analyse(amort, R)
    assert rec["R"][2020] == pytest.approx(100.0 / 500.0) and rec["R"][2019] == pytest.approx(107.5 / 500.0)
    assert rec["amortization_gap_years"] == [2020] and "amortization_gap:2020" in rec["stamps"]
    marked = tc.analyse(amort, R, untagged_fields=["amortization_intangibles"])
    assert marked["R"][2020] == pytest.approx(100.0 / 500.0) and marked["amortization_gap_years"] == []
    assert marked["stamps"] == []


def test_a_record_with_large_amortization_has_x_above_net_income_by_the_after_tax_charge():
    # F1: an HAE-shaped record: net income 100, acquired-intangible amortization 60, tax 25%
    rows = history(2014, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, equity=500.0, amort=60.0, pretax=100.0, tax=25.0))
    rec = tc.analyse(rows, R)
    assert tc.adjusted_earnings(rows[2025]) == pytest.approx(100.0 + 60.0 * 0.75)
    assert rec["m_tc"] == pytest.approx((100.0 + 45.0) / 1000.0)        # the margin of X, not of net income
    plain = tc.analyse(history(2014, 2025, lambda y: row(y, revenue=1000.0, ni=100.0, equity=500.0)), R)
    assert plain["m_tc"] == pytest.approx(0.10)
    # the return numerator carries the same add-back
    assert rec["R_tc"] == pytest.approx(145.0 / 500.0)


def test_interest_is_added_back_after_tax_and_a_null_interest_counts_zero():
    with_int = tc.analyse(history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, interest=40.0,
                                                             pretax=100.0, tax=25.0)), R)
    assert with_int["R_tc"] == pytest.approx((100.0 + 40.0 * 0.75) / 500.0)
    none_int = tc.analyse(history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, interest=None)), R)
    assert none_int["R_tc"] == pytest.approx(0.20)


def test_a_short_record_gives_none_paths_and_stamps():
    rows = history(2024, 2025, lambda y: row(y, ni=100.0, equity=500.0))
    rec = tc.analyse(rows, R)
    assert rec["R_tc"] is None and rec["m_tc"] is None and rec["g_rev"] is None and rec["nwc_intensity"] is None
    assert rec["cycle"] is False and "record_not_available" in rec["stamps"]
    assert rec["ronic_t"] == R                                          # the record does not show a return: the cost of equity
    # three defined return years are enough for R_tc, five are needed for the others
    rows = history(2023, 2025, lambda y: row(y, ni=100.0, equity=500.0, ca=400.0, cl=200.0, cash=50.0))
    rec = tc.analyse(rows, R)
    assert rec["R_tc"] is not None and rec["m_tc"] is None and rec["g_rev"] is None and rec["nwc_intensity"] is None
    assert tc.analyse({}, R)["stamps"] == ["record_not_available"]


def test_the_cycle_looks_at_the_latest_twelve_held_years_even_across_a_gap():
    # 2016 is not held: the twelve held years up to 2025 reach back to 2013, not 2014
    rows = {y: row(y, revenue=(1000.0 if y <= 2012 else 700.0), ni=(150.0 if y <= 2012 else 60.0))
            for y in range(2010, 2026) if y != 2016}
    rec = tc.analyse(rows, R)
    assert rec["cycle_years"] == [2013] and rec["cycle"] is True and rec["cycle_year"] == 2013


def test_the_window_is_the_eight_years_up_to_the_base_year_and_the_cycle_looks_back_twelve():
    def fall_in(y0):
        return history(2010, 2025, lambda y: row(y, revenue=(1000.0 if y < y0 else 700.0), ni=(150.0 if y < y0 else 60.0)))
    rec = tc.analyse(fall_in(2013), R, base_year=2025)
    assert rec["window"] == [2018, 2025]
    assert rec["cycle"] is False and rec["cycle_years"] == []          # 2013's fall is outside the 12-year look-back
    assert tc.analyse(fall_in(2014), R)["cycle_years"] == [2014]
    # base_year cuts later years off
    cut = tc.analyse(fall_in(2014), R, base_year=2021)
    assert cut["base_year"] == 2021 and cut["window"] == [2014, 2021]


def test_working_capital_intensity_is_the_median_of_nwc_over_revenue_with_short_term_debt_once():
    rows = history(2018, 2025, lambda y: row(y, revenue=1000.0, ca=500.0, cash=100.0, cl=250.0, sti=20.0, dc=10.0, stb=5.0))
    rec = tc.analyse(rows, R)
    nwc = (500.0 - 100.0 - 20.0) - (250.0 - 10.0)                     # F4 without provenance: debt_current alone
    assert rec["nwc_intensity"] == pytest.approx(nwc / 1000.0) and len(rec["nwc_years"]) == 8
    add = tc.analyse(rows, R, debt_current_tags={y: "LongTermDebtCurrent" for y in range(2018, 2026)})
    assert add["nwc_intensity"] == pytest.approx(((500.0 - 100.0 - 20.0) - (250.0 - 15.0)) / 1000.0)
    other = tc.analyse(rows, R, debt_current_tags={y: "ShortTermBorrowings" for y in range(2018, 2026)})
    assert other["nwc_intensity"] == pytest.approx(nwc / 1000.0)
    # an unclassified balance sheet (no current assets) gets no working-capital line
    bare = history(2018, 2025, lambda y: row(y, revenue=1000.0))
    assert tc.analyse(bare, R)["nwc_intensity"] is None
    # four years of it are too few
    four = {y: (rows[y] if y >= 2022 else row(y, revenue=1000.0)) for y in range(2018, 2026)}
    assert tc.analyse(four, R)["nwc_intensity"] is None


def test_the_debt_current_tag_reaches_the_invested_capital_of_the_return():
    rows = history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, dc=200.0, stb=100.0))
    plain = tc.analyse(rows, R)
    assert plain["R_tc"] == pytest.approx(100.0 / 700.0)
    added = tc.analyse(rows, R, debt_current_tags={y: "LongTermDebtCurrent" for y in range(2014, 2026)})
    assert added["R_tc"] == pytest.approx(100.0 / 800.0)
    same = history(2014, 2025, lambda y: row(y, ni=100.0, equity=500.0, dc=200.0, stb=200.0))
    assert tc.analyse(same, R, debt_current_tags={y: "LongTermDebtCurrent" for y in range(2014, 2026)})["R_tc"] \
        == pytest.approx(100.0 / 700.0)


def test_the_growth_of_revenue_uses_years_with_revenue_only():
    revs = {2018: 100.0, 2019: 110.0, 2020: None, 2021: 133.1, 2022: 146.41, 2023: 161.051, 2024: 177.1561, 2025: 194.87171}
    rows = {y: row(y, revenue=v) for y, v in revs.items()}
    rec = tc.analyse(rows, R)
    assert rec["g_rev_years"] == [2018, 2019, 2021, 2022, 2023, 2024, 2025]
    assert rec["g_rev"] == pytest.approx(math.log(1.1), rel=1e-6)
    few = {y: row(y, revenue=(100.0 if y > 2021 else None)) for y in range(2018, 2026)}
    assert tc.analyse(few, R)["g_rev"] is None


def test_year_keys_may_be_strings_and_non_year_keys_are_ignored():
    rows = {str(y): row(y) for y in range(2018, 2026)}
    rows["untagged_fields"] = ["goodwill"]
    rec = tc.analyse(rows, R)
    assert rec["base_year"] == 2025 and len(rec["r_years"]) == 8


def test_without_a_cost_of_equity_only_the_statistics_that_do_not_need_it_are_returned():
    rows = history(2014, 2025, lambda y: row(y))
    rec = tc.analyse(rows, None)
    assert rec["R_tc"] is not None and rec["m_tc"] == pytest.approx(0.10)
    assert rec["p"] is None and rec["ronic_t"] is None
    assert rec["cycle"] is False                                        # the cycle test does not use the cost of equity
