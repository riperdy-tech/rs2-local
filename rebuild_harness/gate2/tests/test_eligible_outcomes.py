"""eligible_outcomes (AK.37 v2 / AK.49): a quarter's measures, its total-revenue verification, its public-availability exclusion and the register."""
import pytest

from rebuild_harness.gate2 import eligible_outcomes as eo


class FakeSrc:
    def __init__(self, facts, companyfacts=None, submissions=None):
        self._f, self._cf, self._s = facts, companyfacts or {}, submissions or {}

    def facts(self, cik):
        return self._f

    def companyfacts(self, cik):
        return self._cf

    def submissions(self, cik):
        return self._s


def _q(start, end, val, accn="A", filed="2025-11-05", form="10-Q"):
    return [start, end, val, accn, filed, form]


FACTS = {"us-gaap": {"Revenues": {"USD": [_q("2025-07-01", "2025-09-30", 110.0), _q("2024-07-01", "2024-09-30", 100.0)]},
                     "OperatingIncomeLoss": {"USD": [_q("2025-07-01", "2025-09-30", 11.0), _q("2024-07-01", "2024-09-30", 9.0)]}}}
ROW = {"key": "2025-10-31_0000000001", "cik": "0000000001", "family": "operating",
       "quarters": {"q1": {"accession": "A", "period_end": "2025-09-30", "filed": "2025-11-05"}}}


def _cf(rev, gp, cost):
    mk = lambda v: [{"start": "2025-07-01", "end": "2025-09-30", "val": v[0], "accn": "A", "filed": "2025-11-05", "form": "10-Q"},
                    {"start": "2024-07-01", "end": "2024-09-30", "val": v[1], "accn": "A", "filed": "2025-11-05", "form": "10-Q"}]
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": mk(rev)}}, "GrossProfit": {"units": {"USD": mk(gp)}},
                                  "CostOfRevenue": {"units": {"USD": mk(cost)}}}}}


def test_an_eligible_verified_quarter_keeps_its_same_filing_measures():
    reg = []
    out, d = eo.quarter(FakeSrc(FACTS, _cf((110, 100), (44, 40), (66, 60))), ROW, "q1", None, [], reg)
    assert out["revenue_growth"] == pytest.approx(0.10) and out["operating_margin_change"] == pytest.approx(0.10 - 0.09)
    assert d["scope"]["status"] == "closure" and d["eligibility"]["eligible"] and reg == []


def test_a_public_result_leaves_the_set_and_is_registered_with_its_source():
    sub = {"filings": {"recent": {"form": ["8-K"], "items": ["2.02"], "filingDate": ["2025-10-23"],
                                  "acceptanceDateTime": ["2025-10-23T20:00:00.000Z"], "accessionNumber": ["R"]}}}
    reg = []
    out, d = eo.quarter(FakeSrc(FACTS, _cf((110, 100), (44, 40), (66, 60)), sub), ROW, "q1", None, [], reg)
    assert out["revenue_growth"] is None and not d["eligibility"]["eligible"]
    assert len(reg) == 1 and "Item 2.02" in reg[0]["source"] and reg[0]["timestamp"] == "2025-10-23T20:00:00.000Z"


def test_a_closure_failure_abstains_the_revenue_measures_only():
    reg = []
    out, d = eo.quarter(FakeSrc(FACTS, _cf((110, 100), (20, 18), (30, 27))), ROW, "q1", None, [], reg)   # GP + cost is half of revenue
    assert d["scope"]["status"] == "closure_fail"
    assert out["revenue_growth"] is None and out["operating_margin_change"] is None
    assert [r["reason"].split(":")[0] for r in reg] == ["revenue is not verified total"]
