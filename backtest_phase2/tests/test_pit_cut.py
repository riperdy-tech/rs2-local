"""C6 / C1: the point-in-time cut.  No fact filed after T survives; the facts filed on T do; a fact with no filing date is dropped."""
import json
import os
import socket
import zipfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def cut():
    saved = (socket.socket, socket.getaddrinfo, socket.create_connection)
    from backtest_phase2.pit_build import cut_zips          # importing blocks the socket module; restore it for the rest of the session
    socket.socket, socket.getaddrinfo, socket.create_connection = saved
    return cut_zips


def fact(val, end, filed, form="10-K", start=None, accn="a"):
    d = {"end": end, "val": val, "accn": accn, "form": form, "filed": filed}
    if start:
        d["start"] = start
    return d


def company():
    return {"cik": 1234, "entityName": "X", "facts": {
        "us-gaap": {
            "Revenues": {"units": {"USD": [
                fact(100, "2015-12-31", "2016-02-20", start="2015-01-01"),
                fact(110, "2016-12-31", "2017-02-20", start="2016-01-01"),                 # filed after T
                fact(105, "2015-12-31", "2016-06-30", form="10-K/A", start="2015-01-01"),  # filed ON T: kept
                {"end": "2014-12-31", "val": 90, "accn": "b", "form": "10-K", "start": "2014-01-01"}]}},   # no filing date: dropped
            "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
                fact(10, "2015-12-31", "2016-02-20", start="2015-01-01"),
                fact(12, "2016-12-31", "2017-02-20", start="2016-01-01")]}},
            "OnlyLater": {"units": {"USD": [fact(1, "2016-12-31", "2017-02-20", start="2016-01-01")]}}},
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            fact(10, "2016-01-31", "2016-02-20"),
            fact(11, "2016-04-30", "2016-05-10", form="10-Q"),
            fact(5, "2016-04-30", "2016-05-10", form="10-Q"),                              # a second class, same filing
            fact(13, "2016-07-31", "2016-08-10", form="10-Q")]}}}}}


def test_nothing_filed_after_T_survives_and_T_itself_is_kept(cut):
    filt, side, (kept, dropped, no_filed) = cut.cut_member(company(), "2016-06-30")
    rev = filt["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    assert [v["val"] for v in rev] == [100, 105]
    assert all(v["filed"] <= "2016-06-30" for b in filt["facts"].values() for c in b.values() for u in c["units"].values() for v in u)
    assert "OnlyLater" not in filt["facts"]["us-gaap"]                                    # a concept with no fact left is removed
    assert no_filed == 1 and dropped == 1 + 1 + 1 + 1 + 1                                 # rev late, no-date, shares late, OnlyLater, cover late
    assert kept == 2 + 1 + 3


def test_side_file_cover_page_and_share_filing_dates(cut):
    _filt, side, _ = cut.cut_member(company(), "2016-06-30")
    assert side["k10"] is True
    assert sorted(e[1] for e in side["cover"]) == [5, 11]                                  # every entry of the latest cover filing on or before T
    assert all(e[4] == "2016-05-10" for e in side["cover"])
    assert side["dil"] == [["WeightedAverageNumberOfDilutedSharesOutstanding", "2015-01-01", "2015-12-31", 10, "2016-02-20", "10-K"]]


def test_a_company_with_no_10k_by_T_is_not_a_10k_filer(cut):
    obj = {"cik": 5, "facts": {"us-gaap": {"Revenues": {"units": {"USD": [fact(1, "2016-03-31", "2016-05-01", form="10-Q", start="2016-01-01")]}}}}}
    _f, side, _ = cut.cut_member(obj, "2016-06-30")
    assert side is None or side["k10"] is False          # no side record at all means: no 10-K, no cover, no annual share count


def test_zip_writer_round_trips_and_the_extractor_can_read_it(cut, tmp_path):
    import zlib
    w = cut.RawZipWriter(tmp_path / "t.zip")
    payloads = {"CIK0000000001.json": json.dumps({"a": 1}).encode(), "CIK0000000002.json": json.dumps({"b": [1, 2, 3]}).encode() * 50}
    for name, data in payloads.items():
        co = zlib.compressobj(6, zlib.DEFLATED, -15)
        comp = co.compress(data) + co.flush()
        w.add(name, comp, zlib.crc32(data) & 0xFFFFFFFF, len(data))
    w.close()
    z = zipfile.ZipFile(tmp_path / "t.zip")
    assert z.testzip() is None
    assert sorted(z.namelist()) == sorted(payloads)
    for name, data in payloads.items():
        assert z.read(name) == data


REAL = Path(os.environ.get("BACKTEST_ROOT", r"C:/Users/riper/AppData/Local/Temp/claude/C--Users-riper-stocks/d3013e2d-dbcb-4c2e-be4e-49617528a6b8/scratchpad/backtest")) / "pit" / "cut"


@pytest.mark.skipif(not (REAL / "cut_2016-06-30.zip").exists(), reason="the cut-down zips are not on this machine")
@pytest.mark.parametrize("T", ["2016-06-30", "2020-06-30"])
def test_real_cut_zip_holds_no_fact_filed_after_T_in_a_sample(T):
    z = zipfile.ZipFile(REAL / f"cut_{T}.zip")
    names = z.namelist()
    step = max(1, len(names) // 150)
    n_facts = 0
    for n in names[::step]:
        d = json.loads(z.read(n))
        for b in d["facts"].values():
            for c in b.values():
                for u in c["units"].values():
                    for v in u:
                        n_facts += 1
                        assert v["filed"] <= T
    assert n_facts > 1000
