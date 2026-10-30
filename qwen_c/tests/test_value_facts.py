"""WO_Q4 (SPEC_m3q §2): qwen_c/value/facts.py, point-in-time annual figures from companyfacts, on hand-built SEC documents."""
from datetime import datetime, timezone

from qwen_c.value import facts

T = datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc)


def subs():
    rows = [("0001-26-000010", "10-K", "2026-02-20", "2026-02-20T16:05:00.000Z"),     # effective 2026-02-23: eligible
            ("0001-26-000099", "10-K/A", "2026-03-10", "2026-03-10T16:05:00.000Z"),   # after T: not eligible
            ("0001-25-000010", "10-K", "2025-02-21", "2025-02-21T16:05:00.000Z"),
            ("0001-26-000050", "10-K/A", "2026-02-27", "2026-02-27T22:40:00.000Z")]   # after 17:30 ET Friday: effective Tue 03-03, after T
    cols = list(zip(*rows))
    return {"filings": {"recent": {"accessionNumber": list(cols[0]), "form": list(cols[1]), "filingDate": list(cols[2]),
                                   "acceptanceDateTime": list(cols[3])}}}


def fy(end, val, accn, form="10-K", filed="2026-02-20", fp="FY"):
    """A full-year fact ending `end` (a 365-day duration)."""
    return {"start": f"{int(end[:4]) - 1}{end[4:]}", "end": end, "val": val, "accn": accn, "form": form, "filed": filed, "fp": fp}


def cf(revenue_rows, extra=None):
    f = {"us-gaap": {"Revenues": {"units": {"USD": revenue_rows}}}}
    if extra:
        f["us-gaap"].update(extra)
    return {"facts": f}


def test_latest_eligible_filing_wins_and_later_restatement_is_ignored():
    rows = [fy("2025-12-31", 100.0, "0001-26-000010"), fy("2025-12-31", 90.0, "0001-26-000099", form="10-K/A", filed="2026-03-10"),
            fy("2024-12-31", 80.0, "0001-25-000010", filed="2025-02-21"), fy("2024-12-31", 82.0, "0001-26-000010")]
    out = facts.annual_facts(cf(rows), subs(), T)
    vals = {v["end"]: v["value"] for v in out["revenue"]["values"]}
    assert vals == {"2024-12-31": 82.0, "2025-12-31": 100.0}


def test_after_hours_amendment_effective_after_T_is_excluded():
    rows = [fy("2025-12-31", 100.0, "0001-26-000010"), fy("2025-12-31", 101.0, "0001-26-000050", form="10-K/A", filed="2026-02-27")]
    assert facts.annual_facts(cf(rows), subs(), T)["revenue"]["values"][-1]["value"] == 100.0


def test_quarterly_and_short_duration_facts_are_not_annual():
    rows = [fy("2025-12-31", 100.0, "0001-26-000010"),
            {"start": "2025-10-01", "end": "2025-12-31", "val": 30.0, "accn": "0001-26-000010", "form": "10-K", "filed": "2026-02-20", "fp": "FY"},
            {"start": "2025-01-01", "end": "2025-09-30", "val": 70.0, "accn": "0001-26-000010", "form": "10-Q", "filed": "2025-11-01", "fp": "Q3"}]
    vals = facts.annual_facts(cf(rows), subs(), T)["revenue"]["values"]
    assert [(v["end"], v["value"]) for v in vals] == [("2025-12-31", 100.0)]


def test_old_accession_outside_recent_counts_by_filed_date_and_is_stamped():
    rows = [fy("2019-12-31", 50.0, "0001-20-000001", filed="2020-02-25"), fy("2026-01-31", 9.0, "0001-26-777777", filed="2026-03-01")]
    vals = facts.annual_facts(cf(rows), subs(), T)["revenue"]["values"]
    assert [(v["end"], v["stamp"]) for v in vals] == [("2019-12-31", "acceptance_by_filed_date")]


def test_zero_is_a_value_and_missing_concepts_are_named():
    rows = [fy("2025-12-31", 0.0, "0001-26-000010")]
    out = facts.annual_facts(cf(rows), subs(), T)
    assert out["revenue"]["values"][0]["value"] == 0.0
    assert out["_absent"]["capex"].startswith("no eligible annual fact")


def test_a_tag_switch_keeps_one_series_by_priority_per_year():
    old_tag = {"SalesRevenueNet": {"units": {"USD": [fy("2024-12-31", 80.0, "0001-25-000010", filed="2025-02-21"),
                                                    fy("2025-12-31", 99.0, "0001-26-000010")]}}}
    new_tag = {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [fy("2025-12-31", 100.0, "0001-26-000010")]}}}
    out = facts.annual_facts({"facts": {"us-gaap": {**old_tag, **new_tag}}}, subs(), T)
    assert [(v["end"], v["value"], v["tag"]) for v in out["revenue"]["values"]] == [
        ("2024-12-31", 80.0, "SalesRevenueNet"), ("2025-12-31", 100.0, "RevenueFromContractWithCustomerExcludingAssessedTax")]


def test_profitloss_net_income_is_less_nci_and_a_stale_concept_is_named():
    g = {"Revenues": {"units": {"USD": [fy("2024-12-31", 80.0, "0001-25-000010", filed="2025-02-21"), fy("2025-12-31", 100.0, "0001-26-000010")]}},
         "NetIncomeLoss": {"units": {"USD": [fy("2024-12-31", 8.0, "0001-25-000010", filed="2025-02-21")]}},
         "ProfitLoss": {"units": {"USD": [fy("2024-12-31", 8.5, "0001-25-000010", filed="2025-02-21"), fy("2025-12-31", 11.0, "0001-26-000010")]}},
         "NetIncomeLossAttributableToNoncontrollingInterest": {"units": {"USD": [fy("2025-12-31", 1.0, "0001-26-000010")]}},
         "EarningsPerShareDiluted": {"units": {"USD/shares": [fy("2025-12-31", 2.0, "0001-26-000010")]}},
         "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [fy("2024-12-31", 5.0, "0001-25-000010", filed="2025-02-21"),
                                                                                  fy("2025-12-31", 5.0, "0001-26-000010")]}},
         "AssetsCurrent": {"units": {"USD": [{"end": "2024-12-31", "val": 5.0, "accn": "0001-25-000010", "form": "10-K", "filed": "2025-02-21"}]}}}
    out = facts.annual_facts({"facts": {"us-gaap": g}}, subs(), T)
    assert [(v["value"], v["tag"], v["stamp"]) for v in out["net_income"]["values"]] == [
        (8.0, "NetIncomeLoss", None), (10.0, "ProfitLoss", "profitloss_less_nci")]
    assert out["_stale"] == {"assets_current": "2024-12-31"}


def test_profitloss_already_attributable_is_kept_and_unreconciled_is_stamped():
    base = {"Revenues": {"units": {"USD": [fy("2025-12-31", 100.0, "0001-26-000010")]}},
            "ProfitLoss": {"units": {"USD": [fy("2025-12-31", 10.0, "0001-26-000010")]}},
            "NetIncomeLossAttributableToNoncontrollingInterest": {"units": {"USD": [fy("2025-12-31", 0.5, "0001-26-000010")]}},
            "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [fy("2025-12-31", 5.0, "0001-26-000010")]}}}
    kept = dict(base, EarningsPerShareDiluted={"units": {"USD/shares": [fy("2025-12-31", 2.0, "0001-26-000010")]}})
    v = facts.annual_facts({"facts": {"us-gaap": kept}}, subs(), T)["net_income"]["values"][0]
    assert (v["value"], v["stamp"]) == (10.0, "profitloss_as_attributable")
    v = facts.annual_facts({"facts": {"us-gaap": base}}, subs(), T)["net_income"]["values"][0]
    assert (v["value"], v["stamp"]) == (10.0, "profitloss_basis_unverified")


def test_instants_take_fiscal_year_end_balances_only():
    cash = {"CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        {"end": "2025-12-31", "val": 5.0, "accn": "0001-26-000010", "form": "10-K", "filed": "2026-02-20", "fp": "FY"},
        {"end": "2025-09-30", "val": 4.0, "accn": "0001-25-000777", "form": "10-Q", "filed": "2025-11-01", "fp": "Q3"}]}}}
    out = facts.annual_facts(cf([fy("2025-12-31", 100.0, "0001-26-000010")], cash), subs(), T)
    assert [(v["end"], v["value"]) for v in out["cash"]["values"]] == [("2025-12-31", 5.0)]


def test_urls():
    assert facts.companyfacts_url(320193) == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    assert facts.submissions_url("0000320193") == "https://data.sec.gov/submissions/CIK0000320193.json"


def test_latest_filing_first_then_tag_priority():
    # an older filing's high-priority tag loses to the latest filing's lower-priority tag for the same year (ruling 28)
    g = {"OperatingIncomeLoss": {"units": {"USD": [fy("2024-12-31", 10.0, "0001-25-000010", filed="2025-02-21")]}}}
    i = {"ProfitLossFromOperatingActivities": {"units": {"USD": [fy("2024-12-31", 11.0, "0001-26-000010")]}}}
    out = facts.annual_facts({"facts": {"us-gaap": g, "ifrs-full": i}}, subs(), T)
    assert out["operating_income"]["values"][0]["value"] == 11.0


def test_revenue_takes_the_total_line_within_a_filing():
    g = {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [fy("2025-12-31", 936.0, "0001-26-000010")]}},
         "Revenues": {"units": {"USD": [fy("2025-12-31", 10645.0, "0001-26-000010")]}}}
    v = facts.annual_facts({"facts": {"us-gaap": g}}, subs(), T)["revenue"]["values"][0]
    assert (v["value"], v["tag"], v["stamp"]) == (10645.0, "Revenues", "revenue_largest_of_tags")


def test_latest_annual_period_from_the_submissions():
    s = subs()
    s["filings"]["recent"]["reportDate"] = ["2025-12-31", "2025-12-31", "2024-12-31", "2025-12-31"]
    assert facts.latest_annual_period(s, T) == "2025-12-31"


def test_companyfacts_is_refetched_online():
    from qwen_c import sec_store
    assert facts.companyfacts_url(1).startswith(sec_store.MUTABLE_PREFIXES)
