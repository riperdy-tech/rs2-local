"""realised.py (J2-3): the same-filing realised year 1, on synthetic SEC companyfacts and submissions."""
import pytest

import realised as R

FY0, FY1 = "2024-12-31", "2025-12-31"
K0, K1, KA = "0000000001-25-000001", "0000000001-26-000002", "0000000001-26-000009"


def fact(start, end, val, accn, filed, form="10-K", fp="FY"):
    return {"start": start, "end": end, "val": val, "accn": accn, "filed": filed, "form": form, "fp": fp}


def cf(**tags):
    """cf(Revenues=[facts], ...) as SEC companyfacts, USD, us-gaap."""
    return {"facts": {"us-gaap": {t: {"units": {"USD": rows}} for t, rows in tags.items()}}}


def subs(*rows):
    """submissions with recent filings (form, accession, filingDate, reportDate)."""
    return {"filings": {"recent": {"form": [r[0] for r in rows], "accessionNumber": [r[1] for r in rows],
                                   "filingDate": [r[2] for r in rows], "reportDate": [r[3] for r in rows]}}}


SUBS = subs(("10-K", K0, "2025-02-20", FY0), ("10-Q", "Q", "2025-11-05", "2025-09-30"), ("10-K", K1, "2026-02-19", FY1))


def plain(r1=1100.0, r0_same=1000.0, r0_first=1000.0, oi1=110.0, oi0=90.0):
    return cf(Revenues=[fact("2024-01-01", FY0, r0_first, K0, "2025-02-20"), fact("2025-01-01", FY1, r1, K1, "2026-02-19"),
                        fact("2024-01-01", FY0, r0_same, K1, "2026-02-19")],
              OperatingIncomeLoss=[fact("2025-01-01", FY1, oi1, K1, "2026-02-19"), fact("2024-01-01", FY0, oi0, K1, "2026-02-19")])


def test_growth_and_margin_come_from_the_year1_filing_with_first_filed_beside_it():
    r = R.realised(plain(), SUBS, FY0)
    assert r["status"] == "ok" and r["year1"]["accession"] == K1 and r["year1"]["stamp"] is None
    assert r["growth_same"] == pytest.approx(0.10) and r["margin"] == pytest.approx(0.10)
    assert r["growth_first"] == pytest.approx(0.10) and r["base_move"] == pytest.approx(0.0) and r["restated_base"] is False
    assert r["first_filed"]["accession"] == K0 and r["revenue"]["tag"] == "Revenues"


def test_a_restated_base_is_measured_like_for_like_and_recorded():
    # a sold business re-reported: FY0 first filed at 1,250, printed at 1,000 in the FY1 10-K
    r = R.realised(plain(r0_first=1250.0), SUBS, FY0)
    assert r["growth_same"] == pytest.approx(0.10)                           # 1100 / 1000 - 1, never 1100 / 1250 - 1
    assert r["growth_first"] == pytest.approx(1100 / 1250 - 1)
    assert r["base_move"] == pytest.approx(1000 / 1250 - 1) and r["restated_base"] is True
    assert r["growth_gap_points"] == pytest.approx(0.10 - (1100 / 1250 - 1))
    small = R.realised(plain(r0_first=1003.0), SUBS, FY0)                    # 0.3%: inside RECAST_TOL, not a restatement
    assert small["restated_base"] is False and small["base_move"] == pytest.approx(1000 / 1003 - 1)


def test_the_year1_filing_follows_the_350_380_day_rule_and_the_cutoff():
    assert R.realised(plain(), subs(("10-K", K0, "2025-02-20", FY0)), FY0)["status"] == "no_year1_annual_filing"
    late = subs(("10-K", K1, "2026-11-02", FY1))
    assert R.realised(plain(), late, FY0)["status"] == "no_year1_annual_filing"             # filed after 2026-10-31
    assert R.realised(plain(), late, FY0, by="2026-11-30")["status"] == "ok"
    short = subs(("10-K", K1, "2026-02-19", "2025-12-10"))                                   # 344 days after FY0: a transition period
    assert R.year1_filing(short, FY0) is None
    weeks53 = subs(("10-K", K1, "2026-02-19", "2026-01-03"))                                 # 368 days: a 53-week year
    assert R.year1_filing(weeks53, FY0)["accession"] == K1


def test_the_original_annual_report_wins_and_an_amendment_alone_is_stamped():
    s = subs(("10-K/A", KA, "2026-01-30", FY1), ("10-K", K1, "2026-02-19", FY1))
    assert R.year1_filing(s, FY0)["accession"] == K1
    only = R.year1_filing(subs(("10-K/A", KA, "2026-03-30", FY1)), FY0)
    assert only["accession"] == KA and only["stamp"] == "year1_from_amendment"


def test_the_largest_revenue_tag_is_the_total_and_a_side_line_never_the_base():
    c = plain()
    c["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"] = {"units": {"USD": [
        fact("2025-01-01", FY1, 900.0, K1, "2026-02-19"), fact("2024-01-01", FY0, 850.0, K1, "2026-02-19")]}}
    r = R.realised(c, SUBS, FY0)
    assert r["revenue"]["tag"] == "Revenues" and r["growth_same"] == pytest.approx(0.10)
    assert r["scope"]["status"] == "dominance"


def test_no_pair_in_the_year1_filing_is_named_never_bridged_from_another_filing():
    c = cf(Revenues=[fact("2024-01-01", FY0, 1000.0, K0, "2025-02-20"), fact("2025-01-01", FY1, 1100.0, K1, "2026-02-19")])
    r = R.realised(c, SUBS, FY0)
    assert r["status"] == "no_same_filing_revenue_pair" and r["growth_same"] is None


def test_a_non_positive_comparative_has_no_growth():
    r = R.realised(plain(r0_same=0.0), SUBS, FY0)
    assert r["status"] == "base_not_positive" and r["growth_same"] is None and r["margin"] == pytest.approx(0.10)


def test_margin_absent_is_named():
    c = plain()
    del c["facts"]["us-gaap"]["OperatingIncomeLoss"]
    r = R.realised(c, SUBS, FY0)
    assert r["status"] == "ok" and r["margin"] is None and r["margin_absent"] == "no same-filing operating income pair"


def test_first_filed_on_another_tag_is_stamped():
    c = plain()
    c["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = [x for x in c["facts"]["us-gaap"]["Revenues"]["units"]["USD"] if x["accn"] != K0]
    c["facts"]["us-gaap"]["SalesRevenueNet"] = {"units": {"USD": [fact("2024-01-01", FY0, 1000.0, K0, "2025-02-20")]}}
    r = R.realised(c, SUBS, FY0)
    assert r["first_filed"]["tag"] == "SalesRevenueNet" and r["first_filed"]["stamp"] == "first_filed_tag_differs"
    assert r["growth_first"] == pytest.approx(0.10)


def test_a_quarterly_or_short_fact_never_serves_as_the_annual_leg():
    c = plain()
    c["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(fact("2025-10-01", FY1, 5000.0, K1, "2026-02-19", fp="Q4"))
    assert R.realised(c, SUBS, FY0)["growth_same"] == pytest.approx(0.10)


def test_revenue_scope_closure_and_closure_fail():
    c = plain()
    g = c["facts"]["us-gaap"]
    g["GrossProfit"] = {"units": {"USD": [fact("2025-01-01", FY1, 400.0, K1, "2026-02-19"), fact("2024-01-01", FY0, 350.0, K1, "2026-02-19")]}}
    g["CostOfRevenue"] = {"units": {"USD": [fact("2025-01-01", FY1, 700.0, K1, "2026-02-19"), fact("2024-01-01", FY0, 650.0, K1, "2026-02-19")]}}
    assert R.realised(c, SUBS, FY0)["scope"]["status"] == "closure"
    g["CostOfRevenue"]["units"]["USD"][0]["val"] = 300.0                    # GP + cost no longer equals revenue: a partial line
    assert R.realised(c, SUBS, FY0)["scope"]["status"] == "closure_fail"
    assert R.realised(plain(), SUBS, FY0)["scope"]["status"] == "unverified"
