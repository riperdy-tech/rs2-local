"""Revision 18, part 3 (the ledger's production wiring): a production snapshot row equals the pack's printed reference.

The ledger (tools/reference_ledger.py) takes `reference_inputs`, the closure accessor, the shared status rule, the fence and the
price as parameters; `production_adapters` wires them to production. Here a snapshot is taken on a temporary ledger (never the
live cache/) over the names the synthetic pack builds, and each row is held to what `build_pack` printed for the same name: the
value to the cent, the status, the cost of equity and the closure fields. The 291-name book run of the same check is in
rev18/wb_book_r18.py (reported with the part)."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import reference_ledger as rl  # noqa: E402
import rs2_data  # noqa: E402
from test_throughcycle_reference import _synthetic_pack  # noqa: E402


def _snapshot(tmp_path, monkeypatch, name="GEV", fence=None):
    import depth_membership
    monkeypatch.setattr(depth_membership, "_current_book", lambda factor_path=None: [name])
    wiring = rl.production_adapters(tmp_path, today=date(2026, 9, 27))
    if fence is not None:
        monkeypatch.setattr(cap, "_reference_outside_fence", fence)
    book = wiring.pop("book")
    ledger = tmp_path / "ledger" / "reference_ledger.jsonl"
    summary = rl.snapshot("2026-09-27", book, set(), ledger_path=ledger, **wiring)
    return summary, rl.read_ledger(ledger), ledger


@pytest.mark.parametrize("variant", [dict(), dict(untagged=["goodwill"], drop_goodwill=True), dict(untagged=["amortization_intangibles"]),
                                     dict(separate_borrowings=True, debt_tag="LongTermDebtCurrent")],
                         ids=["plain", "no-goodwill", "no-amortization", "borrowings"])
def test_a_production_snapshot_row_equals_the_packs_printed_reference_to_the_cent(screener_data_stub, monkeypatch, tmp_path, variant):
    pack = _synthetic_pack(monkeypatch, **variant)
    f = pack.facts
    assert f["reference_status"] == "used"
    summary, rows, ledger = _snapshot(tmp_path, monkeypatch)
    assert summary["errors"] == {} and summary["rows_appended"] == 1 and ledger.parent == tmp_path / "ledger"
    row = rows[0]
    assert row["reference_status"] == f["reference_status"] == "used"
    assert round(row["reference_value"], 2) == f["consensus_implied_value"]
    assert row["coe"] == f["coe_anchor"]
    assert row["revision"] == cap.PACK_REVISION == 20
    erp, asof, _ = rs2_data.reference_closure()
    assert row["closure_erp"] == erp and row["closure_asof"] == asof
    assert row["price"] is None or row["vp"] == pytest.approx(row["reference_value"] / row["price"])


def test_the_snapshot_status_is_the_packs_shared_rule_fence_included(screener_data_stub, monkeypatch, tmp_path):
    pack = _synthetic_pack(monkeypatch)
    assert rl.classify_status is not cr.classify_status
    assert [rl.classify_status(v, lambda: s) for v, s in ((None, "above"), (0.004, "above"), (5.0, None), (5.0, "above"), (5.0, "below"))] == [
        "not_available", "not_meaningful", "used", "outside_fence_above", "outside_fence_below"]
    # forced outside the fence: the ledger row says so, as the pack's status does
    fenced = pack.facts["consensus_implied_value"]
    _, rows, _ = _snapshot(tmp_path, monkeypatch, fence=lambda v, b: ("above", (1.0, fenced / 2)))
    assert rows[0]["reference_status"] == "outside_fence_above" and round(rows[0]["reference_value"], 2) == fenced


def test_without_a_usable_closure_premium_the_row_has_no_value_and_says_so(screener_data_stub, monkeypatch, tmp_path):
    _synthetic_pack(monkeypatch)
    monkeypatch.setattr(rs2_data, "reference_closure", lambda path=None: (None, None, "no_reference_closure_artifact(reference_closure.json)"))
    _, rows, _ = _snapshot(tmp_path, monkeypatch)
    r = rows[0]
    assert r["reference_value"] is None and r["reference_status"] == "not_available" and r["coe"] is None
    assert r["closure_erp"] is None and r["closure_asof"] is None and r["vp"] is None


def test_stale_consensus_builds_no_reference_as_in_the_pack(screener_data_stub, monkeypatch, tmp_path):
    _synthetic_pack(monkeypatch)
    real = rs2_data.load_json

    def aged(path):
        d = real(path)
        if str(path).endswith("GEV.json") and "enrich" in str(path) and isinstance(d, dict):
            return dict(d, _fetched_at="2026-06-01T12:00:00")
        return d
    monkeypatch.setattr(rs2_data, "load_json", aged)
    _, rows, _ = _snapshot(tmp_path, monkeypatch)
    assert rows[0]["reference_value"] is None and rows[0]["reference_status"] == "not_available"


def test_the_row_carries_the_published_verdict_in_the_ledgers_shape_the_price_date_and_one_runs_line(screener_data_stub, monkeypatch, tmp_path):
    _synthetic_pack(monkeypatch)
    (tmp_path / "cache").mkdir()
    overlay = {"tickers": {"GEV": {"ticker": "GEV", "direction": "undervalued", "date": "2026-09-18", "median_iv": 900.0,
                                   "pack_revision": 17, "scorecard": {"base_iv": 1037.88, "median_iv": 934.54}}}}
    (tmp_path / "cache" / "depth_overlay.json").write_text(json.dumps(overlay), encoding="utf-8")
    summary, rows, ledger = _snapshot(tmp_path, monkeypatch)
    row = rows[0]
    # revision 19 (brief E1): the verdict also carries direction_m, crux_valid, crux_inputs and the actionable reasons; a revision-17 overlay row has no crux
    assert row["verdict"] == {"label": "undervalued", "base_iv": 1037.88, "published_at": "2026-09-18", "pack_revision": 17, "direction_m": None,
                              "crux_valid": None, "crux_inputs": None, "actionable_reasons": None}
    fin = rs2_data.load_json(Path(rs2_data.CONFIG["screener_data_dir"]) / "financials" / "GEV.json") or {}
    expect = None if fin.get("Price") is None else str(fin.get("Data_Fetched_Date"))[:10]
    assert (row["price"] is None and row["price_date"] is None) or row["price_date"] == expect
    # one summary line per snapshot, beside the ledger, with counts by reason and no names
    runs = (ledger.parent / rl.RUNS_NAME).read_text(encoding="utf-8").splitlines()
    assert len(runs) == 1 and "GEV" not in runs[0] and json.loads(runs[0])["rows_appended"] == 1
    assert summary["errors"] == {}
