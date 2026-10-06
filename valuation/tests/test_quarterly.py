"""Quarterly facts of the shared layer: 10-Q values, YTD differences, 10-K-derived fourth quarters, eligibility and provenance."""
import json

from valuation import pit_data as pdm
from valuation.pit_data import PitData, PitQuarterSource
from valuation.tests import synth
from valuation.tests.synth import duration_fact as df


def world(tmp_path, restate_q1=None, extra=()):
    """A December-year company, FY2019: revenue Q1 25, Q2 27 (6M 52), Q3 30 (9M 82), FY 110 -> Q4 28; ocf is year-to-date only: 10, 22, 30, FY 45.
    The Q1 comparative columns of 2018 ride in the 2019 10-Qs; `restate_q1` restates Q1-2019 in the Q2 10-Q's comparative column."""
    f = []
    f += [df("Revenues", "2019-01-01", "2019-03-31", 25.0, "q1", "2019-05-01"), df("NetCashProvidedByUsedInOperatingActivities", "2019-01-01", "2019-03-31", 10.0, "q1", "2019-05-01"),
          df("Revenues", "2018-01-01", "2018-03-31", 20.0, "q1", "2019-05-01")]
    f += [df("Revenues", "2019-04-01", "2019-06-30", 27.0, "q2", "2019-08-01"), df("Revenues", "2019-01-01", "2019-06-30", 52.0, "q2", "2019-08-01"),
          df("NetCashProvidedByUsedInOperatingActivities", "2019-01-01", "2019-06-30", 22.0, "q2", "2019-08-01"),
          df("Revenues", "2018-04-01", "2018-06-30", 21.0, "q2", "2019-08-01")]
    if restate_q1 is not None:
        f += [df("Revenues", "2019-01-01", "2019-03-31", restate_q1, "q2", "2019-08-01")]
    f += [df("Revenues", "2019-07-01", "2019-09-30", 30.0, "q3", "2019-11-01"), df("Revenues", "2019-01-01", "2019-09-30", 82.0, "q3", "2019-11-01"),
          df("NetCashProvidedByUsedInOperatingActivities", "2019-01-01", "2019-09-30", 30.0, "q3", "2019-11-01")]
    f += synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 110.0, "NetCashProvidedByUsedInOperatingActivities": 45.0, "Assets": 200.0}, accn="k19")
    f += list(extra)
    synth.write_company(tmp_path / "store", 1, f)
    return PitData(tmp_path / "store", id_map={"AAA": "1"})


def by(recs, field, end):
    return [r for r in recs if r["field"] == field and r["period_end"] == end]


def test_reported_three_month_values_ytd_differences_and_the_derived_fourth_quarter(tmp_path):
    pit = world(tmp_path)
    recs = pit.quarterly("1", "2020-03-02")["records"]
    q = lambda f, e: by(recs, f, e)[0]
    assert q("revenue", "2019-03-31")["value"] == 25.0 and q("revenue", "2019-03-31")["kind"] == "reported_3m"
    assert q("revenue", "2019-06-30")["value"] == 27.0 and q("revenue", "2019-09-30")["value"] == 30.0
    r4 = q("revenue", "2019-12-31")
    assert r4["value"] == 110.0 - 82.0 and r4["kind"] == "derived_q4" and sorted(r4["sources"]) == ["k19", "q3"] and r4["filed"] == "2020-03-01"
    assert r4["period_start"] == "2019-09-30"
    # cash flow is year-to-date only: Q1 is the 3-month figure, Q2 and Q3 are differences, Q4 is the year less nine months
    assert [q("ocf", e)["value"] for e in ("2019-03-31", "2019-06-30", "2019-09-30", "2019-12-31")] == [10.0, 12.0, 8.0, 15.0]
    assert [q("ocf", e)["kind"] for e in ("2019-03-31", "2019-06-30", "2019-09-30", "2019-12-31")] == [
        "reported_3m", "derived_ytd_difference", "derived_ytd_difference", "derived_q4"]
    assert all({"cik", "tag", "unit", "period_start", "period_end", "value", "kind", "form", "filed", "accepted_at", "accession", "amended", "fy", "fp",
                "sources", "first_value", "state"} <= set(r) for r in recs)


def test_the_fourth_quarter_does_not_exist_before_the_10k_is_eligible_and_balances_are_quarter_ends(tmp_path):
    pit = world(tmp_path)
    assert not by(pit.quarterly("1", "2020-03-01")["records"], "revenue", "2019-12-31")          # the 10-K was filed that day: not before the date
    assert by(pit.quarterly("1", "2020-03-02")["records"], "revenue", "2019-12-31")
    assert [r["period_end"] for r in pit.quarterly("1", "2019-09-01")["records"] if r["field"] == "revenue" and r["kind"] == "reported_3m"] == [
        "2018-03-31", "2018-06-30", "2019-03-31", "2019-06-30"]


def test_a_quarter_accepted_after_16_00_eastern_on_the_date_is_not_known(tmp_path):
    pit = world(tmp_path)
    subs = tmp_path / "subs"
    subs.mkdir()
    (subs / "CIK0000000001.json").write_text(json.dumps({"filings": {"recent": {"accessionNumber": ["q2"], "acceptanceDateTime": ["2019-08-01T21:30:00.000Z"]}}}),
                                              encoding="utf-8")
    p2 = PitData(tmp_path / "store", acceptance_source=pdm.SubmissionsAcceptance(subs))
    ends = lambda pit_, d: {r["period_end"] for r in pit_.quarterly("1", d, ["revenue"])["records"] if r["kind"] == "reported_3m" and r["period_end"] >= "2019-06-30"}
    assert "2019-06-30" not in ends(p2, "2019-08-01")                         # accepted at 17:30 EDT... after the 16:00 cutoff of that day
    assert "2019-06-30" in ends(p2, "2019-08-02")
    assert "2019-06-30" not in ends(pit, "2019-08-01")                         # no timestamp, filed on the date: ambiguous, not used


def test_a_restated_comparative_is_the_value_known_and_marks_the_quarter_restated(tmp_path):
    pit = world(tmp_path, restate_q1=24.0)
    known = by(pit.quarterly("1", "2019-09-01")["records"], "revenue", "2019-03-31")[0]
    assert known["value"] == 24.0 and known["first_value"] == 25.0 and known["state"] == "RESTATED" and known["accession"] == "q2"
    early = by(pit.quarterly("1", "2019-06-01")["records"], "revenue", "2019-03-31")[0]
    assert early["value"] == 25.0 and early["state"] == "PIT_VALID"
    first = by(pit.quarterly("1", "2019-09-01", mode="first_filed")["records"], "revenue", "2019-03-31")[0]
    assert first["value"] == 25.0


def test_quarterly_rows_have_the_shape_of_the_stopgap_and_a_quarter_source_replaces_it(tmp_path):
    pit = world(tmp_path)
    rows = pit.quarterly_rows("1", "2019-09-01", ("revenue",))
    assert [r["period_end"] for r in rows] == ["2018-03-31", "2018-06-30", "2019-03-31", "2019-06-30"]
    r = rows[-1]
    assert set(r) >= {"period_end", "filed", "accession", "accepted_at", "values", "prior_year"} and r["values"] == {"revenue": 27.0}
    assert r["prior_year"] == {"revenue": 21.0} and rows[-2]["prior_year"] == {"revenue": 20.0} and r["accession"] == "q2" and r["filed"] == "2019-08-01"
    src = PitQuarterSource(pit, fields=("revenue",), max_quarters=2)
    assert [x["period_end"] for x in src.quarters("1", "2020-03-02")] == ["2019-09-30", "2019-12-31"]
    assert src.quarters("1", "2020-03-02")[-1]["kinds"] == {"revenue": "derived_q4"}


def test_a_store_without_quarterly_facts_says_so(tmp_path):
    synth.write_company(tmp_path / "store", 1, synth.annual_report("2019-12-31", "2020-03-01", {"Revenues": 1.0}))
    import gzip
    p = tmp_path / "store" / "0000000001.json.gz"
    doc = json.load(gzip.open(p, "rt", encoding="utf-8"))
    del doc["qfacts"]
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(doc, f)
    got = PitData(tmp_path / "store").quarterly("1", "2021-01-01")
    assert got["records"] == [] and got["notes"] == ["store_has_no_quarterly_facts_rebuild_it"]
    assert PitData(tmp_path / "store").quarterly("999", "2021-01-01")["notes"] == ["company_not_in_store"]


def test_compaction_keeps_ten_q_facts_only_for_the_quarter_tags():
    obj = {"cik": 1, "entityName": "x", "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [{"start": "2019-01-01", "end": "2019-03-31", "val": 25, "accn": "q1", "filed": "2019-05-01", "form": "10-Q", "fy": 2019, "fp": "Q1"}]}},
        "SomeOtherConcept": {"units": {"USD": [{"start": "2019-01-01", "end": "2019-03-31", "val": 1, "accn": "q1", "filed": "2019-05-01", "form": "10-Q"}]}}}}}
    doc = pdm.compact_company(obj)
    assert list(doc["qfacts"]["us-gaap"]) == ["Revenues"] and doc["qfacts"]["us-gaap"]["Revenues"]["USD"][0][6:] == [2019, "Q1"]
    assert "us-gaap" not in doc["facts"]                                    # a 10-Q fact never enters the annual store
