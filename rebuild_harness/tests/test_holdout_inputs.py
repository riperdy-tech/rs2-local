"""What a holdout run may read (Addenda L3, L4): the SIC as filed and nothing current-dated, daily prices only, D1 + D3 complete, one window per run; and the gate-1 run's wiring of them."""
import csv
import json
from argparse import Namespace

import pytest

from rebuild_harness import gate1_run, holdout, holdout_inputs as hi
from rebuild_harness.holdout import HoldoutRefused
from rebuild_harness.tests.test_delisting_inputs import CASH_8K, build, ev
from valuation import sic_crosswalk as sx

HEADERS = [["0000000001", "A-1", "10-K", "2022-03-01", "2022-03-01T21:00:00.000Z", "20220301160000", "3571", "ACME", "ok", "hdr.sgml"],
           ["0000000001", "A-2", "10-K", "2024-03-01", "2024-03-01T12:00:00.000Z", "20240301070000", "7372", "ACME", "ok", "hdr.sgml"],
           ["0000000002", "B-1", "10-K", "2025-06-30", "2025-06-30T12:00:00.000Z", "20250630070000", "1311", "OIL", "ok", "hdr.sgml"]]


def headers_csv(tmp_path, rows=HEADERS, name="headers.csv"):
    p = tmp_path / name
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cik", "accession", "form", "filed", "accepted_index", "accepted_header", "sic", "name", "status", "source"])
        w.writerows(rows)
    return p


def crosswalk(tmp_path):
    doc = sx.build_crosswalk([{"sic": "3571", "industry": "Computers", "sector": "Tech", "country": "United States"}, {"sic": "7372", "industry": "Software", "sector": "Tech", "country": "United States"}])
    p = tmp_path / "cw.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


class Current:
    """The current-dated record: it must never be consulted."""
    meta = {}

    def __call__(self, cik):
        raise AssertionError("the current-dated SIC was read in a holdout")

    def industry(self, cik):
        raise AssertionError("the current-dated industry was read in a holdout")


def strict(tmp_path):
    return hi.StrictSicResolver(sx.SicResolver(Current(), sx.HeadersFile(headers_csv(tmp_path)), sx.Crosswalk.load(crosswalk(tmp_path))))


def test_the_strict_resolver_returns_the_sic_as_filed_and_never_the_current_one(tmp_path):
    r = strict(tmp_path)
    s = r("0000000001", "2023-06-30")
    assert s.code == "3571" and s.point_in_time is True and "A-1" in s.source
    assert r("0000000001", "2024-06-28").code == "7372"                     # the header filed in 2024 is the SIC as filed from then on
    assert r("0000000001", "2022-02-28") is None                            # nothing filed yet: None, NOT the current-dated file (which would raise)
    ind, stamp, det = r.industry_for("0000000001", r("0000000001", "2023-06-30"))
    assert ind == "Computers" and "industry_from_sic_crosswalk" in stamp and det["level"] == 4
    ind, stamp, det = r.industry_for("0000000001", None)
    assert ind is None and stamp.startswith("industry_unmapped") and "Addendum L3" in stamp and det is None
    assert r.industry("0000000001") is None and r.sector_of("Computers") == "Tech"


def test_a_date_the_headers_do_not_cover_refuses_and_so_does_a_dateless_read(tmp_path):
    r = strict(tmp_path)                                                    # the newest filing is 2025-06-30: covered through 2025-05-30
    assert r("0000000001", "2024-12-31").code == "7372"
    with pytest.raises(HoldoutRefused, match="covers filings through 2025-05-30"):
        r("0000000001", "2025-06-30")
    with pytest.raises(HoldoutRefused, match="dateless"):
        r("0000000001")


def test_it_cannot_be_built_without_the_headers_and_the_crosswalk(tmp_path):
    with pytest.raises(HoldoutRefused, match="headers"):
        hi.StrictSicResolver(sx.SicResolver(Current(), None, sx.Crosswalk.load(crosswalk(tmp_path))))
    with pytest.raises(HoldoutRefused, match="crosswalk"):
        hi.StrictSicResolver(sx.SicResolver(Current(), sx.HeadersFile(headers_csv(tmp_path)), None))


def test_an_unfinished_headers_download_refuses_the_holdout_naming_the_first_uncovered_date(tmp_path):
    half = headers_csv(tmp_path, [HEADERS[0], ["0000000009", "Z-1", "10-K", "2023-09-15", "2023-09-15T12:00:00.000Z", "20230915070000", "1311", "Z", "ok", "hdr.sgml"]], "half.csv")
    h = sx.HeadersFile(half)                                                # covers through 2023-08-15
    with pytest.raises(HoldoutRefused, match=r"does not cover 17 of the holdout dates, from 2023-08-31"):
        hi.require_headers_cover(h, hi.holdout_dates())
    assert hi.require_headers_cover(sx.HeadersFile(headers_csv(tmp_path)), ["2023-01-31", "2024-12-31"])["coverage_through"] == "2025-05-30"


def test_the_holdout_dates_are_the_24_month_ends():
    d = hi.holdout_dates()
    assert len(d) == 24 and d[0] == "2023-01-31" and d[1] == "2023-02-28" and d[13] == "2024-02-29" and d[-1] == "2024-12-31"
    assert {holdout.classify(x) for x in d} == {"holdout"}


def args(tmp_path, **kw):
    d1_idx, d3_docs = build(tmp_path, [ev("0000000001", "acquisition_completed", "2023-06-01", "A-1", ["2.01"])], {("0000000001", "A-1"): CASH_8K})
    daily = tmp_path / "daily"
    daily.mkdir(exist_ok=True)
    (tmp_path / "monthly.json").write_text('{"prices": {}}', encoding="utf-8")
    cover = tmp_path / "cover"
    cover.mkdir(exist_ok=True)
    (cover / "cover.jsonl.gz").write_bytes(b"x")
    base = dict(prices_daily=daily, prices=tmp_path / "monthly.json", delisting_index=tmp_path / "d1", delisting_docs=tmp_path / "d3", headers=headers_csv(tmp_path), crosswalk=crosswalk(tmp_path),
                survivorship_cover=cover, erp_basis="engine_consistent", no_prices_fallback=False)
    base.update(kw)
    return Namespace(**base)


def test_a_complete_holdout_configuration_passes(tmp_path):
    out = hi.require_holdout_configuration(["2023-01-31", "2024-12-31"], args(tmp_path))
    assert out["delisting_docs"]["complete"] is True and out["headers"]["coverage_through"] == "2025-05-30"


@pytest.mark.parametrize("change,match", [
    ({"prices_daily": None}, "D5 daily raw closes"),
    ({"prices_daily": "nowhere"}, "does not exist"),
    ({"delisting_index": None}, "D1 event index"),
    ({"delisting_docs": "nowhere"}, "D3 documents"),
    ({"headers": None}, "D2 EDGAR headers"),
    ({"crosswalk": None}, "crosswalk"),
    ({"survivorship_cover": None}, "survivorship cover index"),
    ({"survivorship_cover": "nowhere"}, "survivorship cover index"),
    ({"erp_basis": "damodaran"}, "engine-consistent one"),
    ({"no_prices_fallback": True}, "monthly raw price file"),
    ({"prices": "nowhere.json"}, "monthly raw price file"),
])
def test_every_missing_holdout_input_is_refused_by_name(tmp_path, change, match):
    a = args(tmp_path)
    for k, v in change.items():
        setattr(a, k, v)
    with pytest.raises(HoldoutRefused, match=match):
        hi.require_holdout_configuration(["2023-01-31"], a)


def test_mixed_windows_and_incomplete_documents_and_uncovered_headers_are_refused(tmp_path):
    a = args(tmp_path)
    with pytest.raises(HoldoutRefused, match="only holdout dates"):
        hi.require_holdout_configuration(["2022-12-30", "2023-01-31"], a)
    with pytest.raises(HoldoutRefused, match="does not cover"):
        hi.require_headers_cover(sx.HeadersFile(a.headers), ["2025-06-30"])
    # D3 incomplete: an 8-K accession D1 asks for that is not in the manifest
    (tmp_path / "d3" / "_manifest.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(HoldoutRefused, match="delisting documents are incomplete"):
        hi.require_holdout_configuration(["2023-01-31"], a)


def test_the_gate1_run_names_the_daily_prices_and_d1_d3_in_the_freeze_and_the_stamp(tmp_path, monkeypatch):
    from valuation import discount_rate as vdr
    monkeypatch.setattr(vdr, "default_root", lambda: tmp_path)
    a = args(tmp_path, store=tmp_path, priors_dir=tmp_path, headers=None)
    fi = gate1_run.freeze_inputs(a)
    assert fi["prices"] == a.prices_daily and fi["delisting_index"] == a.delisting_index and fi["delisting_docs"] == a.delisting_docs
    assert fi["price_fallback"] == a.prices and fi["survivorship_cover"] == a.survivorship_cover                                 # Addendum M: the freeze names both
    assert gate1_run.freeze_inputs(Namespace(**dict(vars(a), no_prices_fallback=True)))["price_fallback"] is None
    assert fi["config"]["price_stamp"] == "raw_daily_D5_survivors" and fi["config"]["daily_entry_field"] == "open"
    assert fi["config"]["holdout_horizons"] == [12] and fi["config"]["holdout_outcomes_end"] == "2025-12-31" and fi["config"]["holdout_return_dates_end"] == "2024-12-31"
    a.prices_daily = None
    assert gate1_run.freeze_inputs(a)["prices"] == a.prices and gate1_run.freeze_inputs(a)["config"]["price_stamp"] == gate1_run.PRICE_STAMP and gate1_run.freeze_inputs(a)["price_fallback"] is None


def test_the_run_refuses_a_holdout_date_without_a_freeze_before_any_data_is_opened(tmp_path, monkeypatch):
    from valuation import discount_rate as vdr
    monkeypatch.setattr(vdr, "default_root", lambda: tmp_path)
    with pytest.raises(HoldoutRefused, match="no freeze file"):
        gate1_run.main(["--out-dir", str(tmp_path / "out"), "--dates", "2023-01-31", "--prices-daily", str(tmp_path), "--store", str(tmp_path), "--priors-dir", str(tmp_path)])
    assert not (tmp_path / "out").exists()


def test_a_company_with_no_header_is_unmapped_not_current_dated(tmp_path):
    r = strict(tmp_path)
    ind, stamp, _ = r.industry_for("0000000007", r("0000000007", "2023-06-30"))
    assert r("0000000007", "2023-06-30") is None and ind is None and stamp.startswith("industry_unmapped")


def test_readiness_names_what_is_missing_and_what_it_waits_for(tmp_path):
    a = args(tmp_path)
    (tmp_path / "daily" / "A.csv.gz").write_bytes(b"x")
    (tmp_path / "daily" / "manifest.csv").write_text("ticker,rows,first_date,last_date,status\n", encoding="utf-8")
    r = hi.readiness(a.prices_daily, a.delisting_index, a.delisting_docs, a.headers, a.crosswalk, dates=["2023-01-31", "2024-12-31"])
    assert r["ready"] is True and r["blockers"] == [] and all(c["ok"] for c in r["checks"].values())
    # the headers download has not reached the dates, and a D3 accession is not downloaded
    half = headers_csv(tmp_path, [HEADERS[0]], "half.csv")
    (tmp_path / "d3" / "_manifest.jsonl").write_text("", encoding="utf-8")
    r = hi.readiness(a.prices_daily, a.delisting_index, a.delisting_docs, half, a.crosswalk, dates=["2023-01-31", "2024-12-31"])
    assert r["ready"] is False and len(r["blockers"]) == 2
    assert any(b.startswith("D2_headers_sic_as_filed") and "2 of 2 holdout dates" in b and "from 2023-01-31" in b for b in r["blockers"])
    assert any(b.startswith("D3_delisting_docs") and "1 of 1 accessions" in b for b in r["blockers"])
    r = hi.readiness(tmp_path / "nowhere", tmp_path / "nowhere", tmp_path / "nowhere", tmp_path / "nowhere.csv", tmp_path / "nowhere.json", dates=["2023-01-31"])
    assert r["ready"] is False and len(r["blockers"]) == 4          # D3 is not judged when D1 is absent


def test_readiness_also_checks_the_cover_index_and_the_fallback_file_when_they_are_named(tmp_path):
    a = args(tmp_path)
    (tmp_path / "daily" / "A.csv.gz").write_bytes(b"x")
    (tmp_path / "daily" / "manifest.csv").write_text("ticker,rows,first_date,last_date,status\n", encoding="utf-8")
    ok = hi.readiness(a.prices_daily, a.delisting_index, a.delisting_docs, a.headers, a.crosswalk, dates=["2023-01-31", "2024-12-31"], survivorship_cover=a.survivorship_cover, prices_fallback=a.prices)
    assert ok["ready"] is True and ok["checks"]["survivorship_cover_index"]["ok"] and ok["checks"]["price_fallback_monthly_file"]["ok"]
    bad = hi.readiness(a.prices_daily, a.delisting_index, a.delisting_docs, a.headers, a.crosswalk, dates=["2023-01-31", "2024-12-31"], survivorship_cover=tmp_path / "nowhere", prices_fallback=tmp_path / "no.json")
    assert bad["ready"] is False and any(b.startswith("survivorship_cover_index") for b in bad["blockers"]) and any(b.startswith("price_fallback_monthly_file") for b in bad["blockers"])
