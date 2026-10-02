"""Revision 18, amendment 2 follow-up (finding 6): the ledger's production wiring.

  - `inputs_fn` asks rs2_data.enrich_fetch_error BEFORE it reads `estimates`: the error record of a failed vendor fetch has no estimates
    and used to read as "no coverage", a not_available row recording a vendor outage as a fact about the company. Now the name gets no
    row and is counted by reason (EnrichFetchFailed), like every name whose computation fails;
  - the street-target fence reads valuation_backbone's own root (`valuation_backbone.HERE`), which differs from `--data-root`: with a
    data root other than the repository the estimates came from one place and the fence from another. Each fence call now runs with
    that root set to the run's data root (and restores it).
"""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_test as cap  # noqa: E402,F401
import reference_ledger as rl  # noqa: E402
import valuation_backbone as vb  # noqa: E402
from test_rev18_ledger_parity import _snapshot  # noqa: E402
from test_throughcycle_reference import _synthetic_pack  # noqa: E402


def _err(code=401, where="info"):
    return {"_ticker": "GEV", "_fetched_at": "2026-09-26T12:00:00", "_status": "error", "_error": {"http_status": code, "where": where}}


def test_a_failed_fetch_gives_no_row_and_is_counted_by_reason_never_a_not_available_row(screener_data_stub, monkeypatch, tmp_path):
    _synthetic_pack(monkeypatch)
    import rs2_data
    # the error record is what the ledger's enrich file holds for the name
    orig = rs2_data.load_json
    monkeypatch.setattr(rs2_data, "load_json", lambda p: _err(500, "estimates") if str(p).endswith("GEV.json") and "enrich" in str(p) else orig(p))
    summary, rows, ledger = _snapshot(tmp_path, monkeypatch)
    assert rows == [] and summary["rows_appended"] == 0
    assert summary["errors"] == {"EnrichFetchFailed": 1}
    assert "HTTP 500 at estimates" in summary["error_samples_book_only"][0]


def test_no_coverage_is_still_a_row_with_no_reference(screener_data_stub, monkeypatch, tmp_path):
    import rs2_data
    _synthetic_pack(monkeypatch)
    orig = rs2_data.load_json
    nocov = {"_ticker": "GEV", "_fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "estimates": None}
    monkeypatch.setattr(rs2_data, "load_json", lambda p: nocov if str(p).endswith("GEV.json") and "enrich" in str(p) else orig(p))
    summary, rows, _ = _snapshot(tmp_path, monkeypatch)
    assert summary["errors"] == {} and len(rows) == 1
    assert rows[0]["reference_status"] == "not_available" and rows[0]["reference_value"] is None


def _targets_root(tmp_path, name="ZZQ"):
    (tmp_path / "enrich").mkdir(parents=True, exist_ok=True)
    import json
    rec = {"_ticker": name, "_fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "analyst_target_low": 10.0,
           "analyst_target_median": 15.0, "analyst_target_high": 20.0, "analyst_count": 9}
    (tmp_path / "enrich" / f"{name}.json").write_text(json.dumps(rec), encoding="utf-8")
    return tmp_path


def test_the_fence_reads_the_runs_data_root_not_the_backbones_own(monkeypatch, tmp_path):
    import depth_membership
    monkeypatch.setattr(depth_membership, "_current_book", lambda factor_path=None: [])
    other = tmp_path / "repo_like"
    other.mkdir()
    monkeypatch.setattr(vb, "HERE", other)                              # the module's own root: no enrich file for the name
    root = _targets_root(tmp_path / "data_root")
    wiring = rl.production_adapters(root, today=date(2026, 9, 27))
    fence = wiring["fence_fn"]
    # the band is [10, 20]; the fence 0.5 x 10 / 1.1 = 4.55 to 2 x 20 / 1.1 = 36.36 (the pack's own rule)
    assert fence(100.0, "ZZQ") == "above" and fence(2.0, "ZZQ") == "below" and fence(20.0, "ZZQ") is None
    assert vb.HERE == other                                             # the module's root is put back
    # a name with no enrich file under the data root has no band: nothing is fenced
    assert fence(100.0, "NOFILE") is None and vb.HERE == other


def test_the_fence_restores_the_root_even_when_the_band_cannot_be_read(monkeypatch, tmp_path):
    import depth_membership
    monkeypatch.setattr(depth_membership, "_current_book", lambda factor_path=None: [])
    sentinel = tmp_path / "sentinel"
    monkeypatch.setattr(vb, "HERE", sentinel)
    wiring = rl.production_adapters(tmp_path / "empty_root", today=date(2026, 9, 27))
    assert wiring["fence_fn"](5.0, "ZZQ") is None and vb.HERE == sentinel
