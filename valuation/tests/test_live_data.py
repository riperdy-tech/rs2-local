"""Plan D3: the live data layer's SEC refresh and the stale_inputs rule (no network: the fetch is injected)."""
import gzip
import json
from datetime import datetime, timezone

from valuation import live_data as ld
from valuation.pit_data import compact_company


def facts(filed="2026-08-05"):
    return {"cik": 1, "entityName": "Syn", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"end": "2025-12-31", "val": 100.0, "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-20", "accn": "a1"},
        {"end": "2026-06-30", "val": 55.0, "fy": 2026, "fp": "Q2", "form": "10-Q", "filed": filed, "accn": "a2"}]}}}}}


def test_refresh_compacts_through_the_replay_compactor_records_the_fetch_and_a_failure_keeps_the_previous_file(tmp_path):
    raw = json.dumps(facts()).encode()
    clock = lambda: datetime(2026, 10, 13, 6, 0, tzinfo=timezone.utc)
    got = []
    m = ld.refresh_companies(["1"], tmp_path / "store", tmp_path / "manifest.json", get=lambda u: got.append(u) or raw, now=clock)
    assert got == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"]
    e = m["0000000001"]
    assert e["latest_filed"] == "2026-08-05" and e["error"] is None and len(e["sha256"]) == 64
    with gzip.open(tmp_path / "store" / "0000000001.json.gz", "rt", encoding="utf-8") as f:
        assert json.load(f) == json.loads(json.dumps(compact_company(facts())))           # identical to the replay store's compaction
    def boom(u):
        raise OSError("SEC down")
    m2 = ld.refresh_companies(["1"], tmp_path / "store", tmp_path / "manifest.json", get=boom, now=clock)
    assert m2["0000000001"]["error"].startswith("OSError") and m2["0000000001"]["latest_filed"] == "2026-08-05"
    assert (tmp_path / "store" / "0000000001.json.gz").exists()                            # the previous file is kept, the failure recorded
    assert json.loads((tmp_path / "manifest.json").read_text())["0000000001"]["error"].startswith("OSError")


def test_stale_reasons_name_every_failure_and_a_fresh_company_has_none():
    man = {"0000000001": {"fetched_utc": "2026-10-13T06:00:00+00:00", "latest_filed": "2026-08-05", "error": None}}
    subs = {"filings": {"recent": {"form": ["8-K", "10-Q"], "filingDate": ["2026-09-01", "2026-08-05"]}}}
    assert ld.stale_reasons("1", "2026-10-13", man, subs, trading_days_since_spy=1, damodaran_asof="2026-10-01", priors_vintage=2025) == []
    behind = {"filings": {"recent": {"form": ["10-Q"], "filingDate": ["2026-10-10"]}}}
    r = ld.stale_reasons("1", "2026-10-16", man, behind, spy_last="2026-10-09", trading_days_since_spy=5, damodaran_asof="2026-08-01", priors_vintage=2024)
    assert len(r) == 5 and any("store is behind" in x for x in r) and any("fetched 3 days" in x for x in r)
    assert any("prices end 2026-10-09" in x for x in r) and any("Damodaran" in x for x in r) and any("priors vintage 2024" in x for x in r)
    assert ld.stale_reasons("2", "2026-10-13", man) == ["company facts never fetched"]
    failed = {"0000000001": dict(man["0000000001"], error="OSError: SEC down")}
    assert any("refresh failed" in x for x in ld.stale_reasons("1", "2026-10-13", failed))
