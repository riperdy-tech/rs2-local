"""Tests of Addendum J11: the SIC -> Damodaran-industry crosswalk, the SIC as filed from the EDGAR headers, and the resolver the adapter uses.  Synthetic data; one test reads
the approved indname when it is on this machine."""
import csv
import json
from datetime import date

import pytest

from valuation import pit_adapter
from valuation import pit_data as pdm
from valuation import sic_crosswalk as sx
from valuation.common import DataNotPresent
from valuation.tests.test_gate1 import _store, _sic


def rows():
    r = []

    def add(sic, ind, n, country="United States", sector="S"):
        r.extend({"sic": sic, "industry": ind, "sector": sector + ind[:1], "country": country} for _ in range(n))
    add("3571", "Computers", 5)
    add("3571", "Electronics", 2)
    add("3572", "Computers", 3)
    add("3572", "Electronics", 3)                       # a tie: the name that sorts first
    add("3579", "Office", 4)
    add("3571", "Foreign Electronics", 50, country="China")    # not a US company: never counts
    add("36X1", "Bad", 1)                                # not a 4-digit SIC
    return r


def test_the_crosswalk_is_the_modal_industry_of_the_us_companies_of_a_sic_with_a_stated_tie_rule():
    cw = sx.build_crosswalk(rows())
    e = cw["by_sic4"]["3571"]
    assert e["industry"] == "Computers" and e["n"] == 5 and e["n_total"] == 7 and e["runner_up"] == "Electronics" and e["tie"] is False
    t = cw["by_sic4"]["3572"]
    assert t["industry"] == "Computers" and t["tie"] is True and t["share"] == 0.5                 # Computers < Electronics: the name that sorts first
    assert "Foreign Electronics" not in {v["industry"] for v in cw["by_sic4"].values()}           # US only
    assert cw["meta"]["us_rows_without_a_4_digit_sic_or_industry"] == 1 and cw["meta"]["us_rows"] == 5 + 2 + 3 + 3 + 4 + 1
    assert cw["industry_sector"]["Computers"] == "SC" and cw["industry_sector"]["Foreign Electronics"] == "SF"       # a sector belongs to the industry, any country


def test_a_sic_no_us_company_carries_falls_back_to_its_3_then_2_digit_prefix_and_says_so():
    c = sx.Crosswalk(sx.build_crosswalk(rows()))
    assert c.industry("3571")["level"] == 4 and c.industry("3571")["industry"] == "Computers"
    x = c.industry("3578")                                # no company: the 3-digit prefix 357 (Computers: 5 + 3, Electronics 2 + 3, Office 4) -> Computers 8
    assert x["industry"] == "Computers" and x["level"] == 3 and x["n"] == 8
    y = c.industry("3599")                                # prefix 359 empty -> 35 (all of the above)
    assert y["level"] == 2 and y["industry"] == "Computers"
    assert c.industry("9999") is None and c.industry("12") is None and c.industry(None) is None and c.industry("abcd") is None
    assert c.sector("Computers") == "SC" and c.sector(None) is None


def _headers_csv(tmp_path, lines):
    p = tmp_path / "headers.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cik", "accession", "form", "filed", "accepted_index", "accepted_header", "sic", "name", "status", "source"])
        for ln in lines:
            w.writerow(ln)
    return p


HDR = [
    ["0000000001", "A-1", "10-K", "2019-03-01", "2019-03-01T21:00:00.000Z", "20190301160000", "3571", "ACME", "ok", "hdr.sgml"],           # 16:00 EST: accepted at the decision time of 2019-03-01
    ["0000000001", "A-2", "10-K", "2020-03-01", "2020-03-01T22:30:00.000Z", "20200301173000", "7372", "ACME", "ok", "hdr.sgml"],           # after the decision time of 2020-03-01
    ["0000000002", "B-1", "10-K", "2019-05-01", "2019-05-01T10:00:00.000Z", "20190501060000", "", "NOSIC", "ok", "hdr.sgml"],             # no SIC in the header
    ["0000000003", "C-1", "10-K", "2019-05-02", "", "20190502060000", "6021", "BANK", "error", "hdr.sgml"],                                # a failed download row
    ["0000000004", "D-1", "10-K", "2021-01-02", "2021-01-02T12:00:00.000Z", "20210102070000", "1311", "OIL", "ok", "hdr.sgml"],
]


def test_the_headers_file_gives_the_sic_as_filed_at_the_decision_time_and_states_its_coverage(tmp_path):
    h = sx.HeadersFile(_headers_csv(tmp_path, HDR))
    assert h.n_rows == 5 and h.n_with_sic == 3 and h.newest_filed == "2021-01-02"
    assert h.coverage_through == date(2020, 12, 2) and h.covers("2020-12-02") and not h.covers("2020-12-03")          # the frontier minus 31 days
    assert h.headers._latest("0000000001", "2019-03-01", "sic")["sic"] == "3571"       # accepted at 16:00 ET exactly: eligible
    assert h.headers._latest("0000000001", "2019-02-28", "sic") is None                # not before it was filed
    assert h.headers._latest("0000000001", "2020-03-01", "sic")["sic"] == "3571"       # the 2020 header was accepted after 16:00 ET: invisible on that date
    assert h.headers._latest("0000000001", "2020-03-02", "sic")["sic"] == "7372"
    assert h.headers._latest("0000000002", "2020-01-01", "sic") is None and h.headers._latest("0000000003", "2020-01-01", "sic") is None
    assert len(h.sha256) == 64 and h.info()["coverage_through"] == "2020-12-02"
    gz = tmp_path / "h.csv.gz"
    import gzip
    gz.write_bytes(gzip.compress((tmp_path / "headers.csv").read_bytes()))
    assert sx.HeadersFile(gz).n_with_sic == 3


def _resolver(tmp_path, with_headers=True):
    cw = sx.Crosswalk(sx.build_crosswalk(rows() + [{"sic": "7372", "industry": "Software", "sector": "IT", "country": "United States"}] * 3))
    cur = _sic(tmp_path, cik=1, sic="3571", industry="Current2026Industry")
    return sx.SicResolver(cur, sx.HeadersFile(_headers_csv(tmp_path, HDR)) if with_headers else None, cw)


def test_the_resolver_uses_the_header_sic_where_the_file_covers_the_date_else_the_current_dated_record(tmp_path):
    r = _resolver(tmp_path)
    s = r("1", "2020-03-02")
    assert s.code == "7372" and s.point_in_time is True and "A-2" in s.source
    ind, stamp, det = r.industry_for("1", s)
    assert ind == "Software" and stamp.startswith("industry_from_sic_crosswalk") and det["level"] == 4
    late = r("1", "2022-06-30")                                      # after the coverage frontier: current-dated, stamped by the adapter
    assert late.point_in_time is False and late.code == "3571"
    assert r.industry_for("1", late)[0] == "Current2026Industry" and r.industry_for("1", late)[1] == "industry_current_dated"
    assert r("1", "2011-01-01").point_in_time is False                # covered date, no header yet: the current-dated record (J11), never nothing
    assert r("99", "2020-03-02") is None                              # unknown to both
    ind, stamp, det = r.industry_for("99", None)
    assert ind is None
    nohdr = _resolver(tmp_path / "x", with_headers=False) if (tmp_path / "x").mkdir() is None else None
    assert nohdr("1", "2020-03-02").point_in_time is False


def test_a_sic_as_filed_that_the_crosswalk_cannot_map_leaves_the_industry_unmapped_and_named(tmp_path):
    r = _resolver(tmp_path)
    rec = pdm.SicRecord("9999", "", "hdr", True)
    ind, stamp, det = r.industry_for("1", rec)
    assert ind is None and stamp.startswith("industry_unmapped") and det is None
    assert sx.SicResolver(r.current, None, None).industry_for("1", rec)[0] is None


def test_the_adapter_stamps_the_sic_as_filed_the_crosswalk_industry_and_the_sector(tmp_path):
    r = _resolver(tmp_path)
    store = _store(tmp_path)
    pit = pdm.PitData(store, sic_source=r, sic_history=r)
    a = pit_adapter.adapt(pit, 1, "2020-03-02")                      # the header of 2020-03-01 (accepted after 16:00 ET that day) is visible now: SIC 7372
    assert a.ok and "sic_as_filed_at_T" in a.stamps and a.company.sic.code == "7372" and a.company.sic.point_in_time is True
    assert a.industry == "Software" and any(s.startswith("industry_from_sic_crosswalk") for s in a.stamps) and "industry_current_dated" not in a.stamps
    assert a.sector == "IT"
    b = pit_adapter.adapt(pit, 1, "2021-06-30")                      # beyond the headers' coverage: current-dated and stamped
    assert b.ok and "sic_current_dated" in b.stamps and "industry_current_dated" in b.stamps and b.industry == "Current2026Industry" and b.company.sic.point_in_time is False
    a2 = pit_adapter.adapt(pit, 1, "2020-03-01")                     # the 2020 header was accepted after 16:00 ET on the 1st: the 2019 header's SIC stands
    assert a2.company.sic.code == "3571" and a2.company.sic.point_in_time is True and a2.industry == "Computers"


def test_a_fallback_level_is_stamped(tmp_path):
    cw = sx.Crosswalk(sx.build_crosswalk(rows()))
    cur = _sic(tmp_path, cik=1, sic="3571", industry="X")
    h = _headers_csv(tmp_path, [["0000000001", "A-1", "10-K", "2019-03-01", "2019-03-01T10:00:00.000Z", "20190301050000", "3578", "ACME", "ok", "hdr.sgml"],
                                ["0000000009", "Z-1", "10-K", "2020-12-30", "2020-12-30T10:00:00.000Z", "20201230050000", "3571", "Z", "ok", "hdr.sgml"]])
    r = sx.SicResolver(cur, sx.HeadersFile(h), cw)
    pit = pdm.PitData(_store(tmp_path / "s"), sic_source=r, sic_history=r)
    a = pit_adapter.adapt(pit, 1, "2019-12-31")
    assert a.industry == "Computers" and "industry_crosswalk_fallback_3_digit_prefix" in a.stamps


def test_build_file_never_overwrites_and_reads_the_approved_indname_when_present(tmp_path):
    root = None
    try:
        from valuation.discount_rate import default_root
        root = default_root()
    except DataNotPresent:
        pass
    if root is None or not (root / "datasets_indname.xls").exists():
        pytest.skip("the approved Damodaran indname is not on this machine")
    out = tmp_path / "xw.json"
    doc = sx.build_file(root, out)
    assert doc["meta"]["us_rows"] > 5000 and len(doc["meta"]["indname_xls_sha256"]) == 64 and doc["meta"]["n_sic4"] > 300
    cw = sx.Crosswalk.load(out)
    assert cw.industry("1311")["industry"] and cw.industry("6021")["industry"]
    with pytest.raises(FileExistsError):
        sx.build_file(root, out)
    with pytest.raises(DataNotPresent):
        sx.Crosswalk.load(tmp_path / "none.json")
