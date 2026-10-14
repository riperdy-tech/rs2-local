"""same_filing (AK.27-AK.31, AK.37): one-filing outcomes and the forecast-eligibility rules, on synthetic facts built like the real cases."""
import pytest

from rebuild_harness.gate2 import same_filing as sf


def row(start, end, val, accn, filed, form="10-Q"):
    return [start, end, val, accn, filed, form]


def facts(**tags):
    """facts(Revenues={"USD": [rows]}, ...) as the store's {taxo: {tag: {unit: rows}}}."""
    return {"us-gaap": tags}


def test_the_ladder_is_the_extractors():
    from valuation.pit_data import quarter_fields
    q = quarter_fields()
    for f in ("revenue", "operating_income", "net_income"):
        assert sf.LADDER[f] == list(q[f][1]), f


def test_a_recast_is_measured_like_for_like_not_against_the_first_filed_prior():
    # Dollar Tree shape: last year's quarter first filed at 7,378.8 (with the sold business), re-reported at 4,068.6 in this year's 10-Q
    f = facts(Revenues={"USD": [row("2024-05-05", "2024-08-03", 7378.8e6, "A-24", "2024-09-04"),
                                row("2025-05-04", "2025-08-02", 4570.4e6, "A-25", "2025-09-03"),
                                row("2024-05-05", "2024-08-03", 4068.6e6, "A-25", "2025-09-03")]})
    m = sf.quarter_measures(f, "A-25", "2025-08-02", "operating", None)
    assert m["status"] == "ok" and m["kinds"]["revenue"] == "reported_3m"
    assert m["revenue_growth"] == pytest.approx(4570.4 / 4068.6 - 1)          # +12.3%, not 4570.4/7378.8 - 1 = -38%


def test_several_revenue_tags_in_one_filing_take_the_largest_current_value_within_one_unit():
    f = facts(Revenues={"USD": [row("2025-01-01", "2025-03-31", 70e6, "B", "2025-05-01"), row("2024-01-01", "2024-03-31", 2.4e6, "B", "2025-05-01")]},
              RevenueFromContractWithCustomerExcludingAssessedTax={
                  "USD": [row("2025-01-01", "2025-03-31", 1400e6, "B", "2025-05-01"), row("2024-01-01", "2024-03-31", 1300e6, "B", "2025-05-01")],
                  "CNY": [row("2025-01-01", "2025-03-31", 9900e6, "B", "2025-05-01"), row("2024-01-01", "2024-03-31", 9000e6, "B", "2025-05-01")]})
    m = sf.quarter_measures(f, "B", "2025-03-31", "operating", None)
    assert m["revenue_growth"] == pytest.approx(1400 / 1300 - 1)              # the total, in USD; never the 70M side line, never the CNY figure
    assert m["tags"]["revenue"].endswith("RevenueFromContractWithCustomerExcludingAssessedTax/USD")
    assert m["revenue_tags"]["disagree_over_1pt"] is True


def test_a_derived_q4_needs_one_tag_across_both_filings_and_no_recast_between_them():
    fy = [row("2025-01-01", "2025-12-31", 400e6, "K", "2026-02-20", "10-K"), row("2024-01-01", "2024-12-31", 360e6, "K", "2026-02-20", "10-K"),
          row("2024-01-01", "2024-12-31", 360e6, "K0", "2025-02-20", "10-K")]
    nine = [row("2025-01-01", "2025-09-30", 290e6, "Q", "2025-11-05"), row("2024-01-01", "2024-09-30", 265e6, "Q", "2025-11-05")]
    m = sf.quarter_measures(facts(Revenues={"USD": fy + nine}), "K", "2025-12-31", "operating", None)
    assert m["kinds"]["revenue"] == "derived_q4" and m["revenue_growth"] == pytest.approx(110 / 95 - 1)
    recast = [r if r[3] != "K0" else row("2024-01-01", "2024-12-31", 500e6, "K0", "2025-02-20", "10-K") for r in fy]   # prior year first filed at 500
    m2 = sf.quarter_measures(facts(Revenues={"USD": recast + nine}), "K", "2025-12-31", "operating", None)
    assert m2["revenue_growth"] is None and m2["status"] == "no_same_filing_pair"   # a recast between the filings: listed, never guessed


def test_a_bank_without_a_revenue_line_still_measures_its_rote():
    f = facts(NetIncomeLoss={"USD": [row("2025-07-01", "2025-09-30", 12e6, "N", "2025-11-07"), row("2024-07-01", "2024-09-30", 10e6, "N", "2025-11-07")]})
    m = sf.quarter_measures(f, "N", "2025-09-30", "financial", 400e6)
    assert m["status"] == "ok" and m["revenue_growth"] is None
    assert m["rote_change_annualised_on_tbv_at_T"] == pytest.approx(4 * 2e6 / 400e6)


def test_the_annual_target_uses_the_year1_reports_own_comparative():
    f = facts(Revenues={"USD": [row("2024-01-01", "2024-12-31", 900e6, "Y0", "2025-02-20", "10-K"),
                                row("2025-01-01", "2025-12-31", 1100e6, "Y1", "2026-02-20", "10-K"),
                                row("2024-01-01", "2024-12-31", 1000e6, "Y1", "2026-02-20", "10-K")]},
              OperatingIncomeLoss={"USD": [row("2025-01-01", "2025-12-31", 110e6, "Y1", "2026-02-20", "10-K"),
                                           row("2024-01-01", "2024-12-31", 90e6, "Y1", "2026-02-20", "10-K")]})
    m = sf.annual_measures(f, "2026-02-20", "2025-12-31", "2024-12-31")
    assert m["revenue_growth"] == pytest.approx(0.10) and m["operating_margin_change"] == pytest.approx(0.10 - 0.09)


def test_a_quarter_is_not_a_forecast_when_its_release_was_in_the_pack_or_it_is_stale():
    ents = [{"form": "8-K", "kind": "earnings_release", "filed": "2025-10-29"}, {"form": "10-Q", "filed": "2025-08-01"}]
    e = sf.quarter_eligibility(ents, "2025-09-27", "2025-10-31")
    assert not e["eligible"] and "earnings release" in e["reasons"][0]
    assert sf.quarter_eligibility(ents, "2025-12-31", "2025-10-31")["eligible"]                 # the quarter after T: a forecast
    assert not sf.quarter_eligibility([], "2025-01-03", "2025-10-31")["eligible"]               # ended 301 days before T


def test_a_fiscal_year_is_not_a_forecast_when_its_results_were_public_at_T():
    rel = [{"form": "8-K", "kind": "earnings_release", "filed": "2026-01-27", "period": "Q4 2025"}]
    assert not sf.year_eligibility(rel, "2025-12-31", "2026-02-27")["eligible"]
    tenk = [{"form": "10-K", "filed": "2026-02-27", "period": "fiscal year ended 2025-12-31"}]
    assert not sf.year_eligibility(tenk, "2025-12-31", "2026-02-27")["eligible"]
    assert not sf.year_eligibility([], "2025-12-31", "2026-02-27", year1_filed="2026-02-27")["eligible"]   # filed on T
    assert sf.year_eligibility([], "2025-12-31", "2025-10-31", year1_filed="2026-02-20")["eligible"]


def test_on_a_tie_this_year_the_larger_prior_wins_so_a_sub_line_never_becomes_the_base():
    # CIK 1831915 shape (AK.41): both tags 193.0M this year; last year `Revenues` is a 2.96M sub-line, the contract tag the 164.0M total
    f = facts(Revenues={"USD": [row("2023-01-01", "2023-12-31", 193.015e6, "K", "2024-03-01", "10-K"), row("2022-01-01", "2022-12-31", 2.963e6, "K", "2024-03-01", "10-K")]},
              RevenueFromContractWithCustomerExcludingAssessedTax={
                  "USD": [row("2023-01-01", "2023-12-31", 193.015e6, "K", "2024-03-01", "10-K"), row("2022-01-01", "2022-12-31", 164.036e6, "K", "2024-03-01", "10-K")]})
    m = sf.annual_measures(f, "2024-03-01", "2023-12-31", "2022-12-31")
    assert m["revenue_growth"] == pytest.approx(193.015 / 164.036 - 1)        # +17.7%, not +6,414%


def _cf(**tags):
    return {"facts": {"us-gaap": {t: {"units": {"USD": [dict(start=s, end=e, val=v, accn=a, filed=f, form=fm) for s, e, v, a, f, fm in rows]}}
                                  for t, rows in tags.items()}}}


def test_revenue_scope_closure_verifies_a_total_and_flags_a_partial_line():
    q = ("2025-07-01", "2025-09-30"), ("2024-07-01", "2024-09-30")
    rev = [(q[0][0], q[0][1], 100.0, "X", "2025-11-01", "10-Q"), (q[1][0], q[1][1], 90.0, "X", "2025-11-01", "10-Q")]
    gp = [(q[0][0], q[0][1], 40.0, "X", "2025-11-01", "10-Q"), (q[1][0], q[1][1], 35.0, "X", "2025-11-01", "10-Q")]
    cost = [(q[0][0], q[0][1], 60.0, "X", "2025-11-01", "10-Q"), (q[1][0], q[1][1], 55.0, "X", "2025-11-01", "10-Q")]
    ok = sf.revenue_scope(_cf(Revenues=rev, GrossProfit=gp, CostOfRevenue=cost), "Revenues", "USD", 1, "X", "2025-09-30", "reported_3m")
    assert ok["status"] == "closure"
    part = [(r[0], r[1], r[2] * 0.3, r[3], r[4], r[5]) for r in rev]                 # a line, not the total: GP + cost no longer adds up
    assert sf.revenue_scope(_cf(Revenues=part, GrossProfit=gp, CostOfRevenue=cost), "Revenues", "USD", 1, "X", "2025-09-30", "reported_3m")["status"] == "closure_fail"
    assert sf.revenue_scope(_cf(Revenues=rev), "Revenues", "USD", 1, "X", "2025-09-30", "reported_3m")["status"] == "unverified"
    assert sf.revenue_scope({}, "Revenues", "USD", 2, "X", "2025-09-30", "reported_3m")["status"] == "dominance"


def test_item_202_public_uses_the_acceptance_time_against_the_16_00_et_cutoff():
    sub = {"filings": {"recent": {"form": ["8-K", "8-K", "10-Q"], "items": ["2.02,9.01", "5.02", ""],
                                  "filingDate": ["2025-10-29", "2025-10-30", "2025-11-04"],
                                  "acceptanceDateTime": ["2025-10-29T20:05:00.000Z", "2025-10-30T12:00:00.000Z", "2025-11-04T16:00:00.000Z"],
                                  "accessionNumber": ["A", "B", "C"]}}}
    hit = sf.item_202_public(sub, "2025-09-27", "2025-10-31")
    assert hit and hit["accession"] == "A"                                     # a results 8-K, accepted before T
    assert sf.item_202_public(sub, "2025-09-27", "2025-10-29") is None         # accepted 16:05 ET on T: after the cutoff
    assert sf.item_202_public(sub, "2025-12-31", "2026-01-15") is None         # nothing filed after that quarter's end
