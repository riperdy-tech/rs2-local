"""tests/test_depth_gates_v5.py — GATE_VERSION 5 and reason 16 (depleting producers).

Tests the fail-closed producer_class() helper, assess() gate reason 16,
and stamp_and_route() provenance stamping.
"""
import csv
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import depth_gates as dg
import depth_pipeline as dp


# ================================================================================================
# 1. producer_class tests
# ================================================================================================

def test_producer_class_gold_row(tmp_path):
    csv_file = tmp_path / "stocks.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Symbol", "Sector", "Industry"])
        writer.writerow(["GOLD", "Basic Materials", "Gold"])
    res = dg.producer_class("GOLD", csv_file, "stocks.csv@test1")
    assert res == {
        "status": "ok",
        "depleting": True,
        "sector": "Basic Materials",
        "industry": "Gold",
        "source": "stocks.csv@test1",
    }


def test_producer_class_oil_gas_midstream_row(tmp_path):
    csv_file = tmp_path / "stocks.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Symbol", "Sector", "Industry"])
        writer.writerow(["WMB", "Energy", "Oil & Gas Midstream"])
    res = dg.producer_class("WMB", csv_file, "stocks.csv@test2")
    assert res == {
        "status": "ok",
        "depleting": False,
        "sector": "Energy",
        "industry": "Oil & Gas Midstream",
        "source": "stocks.csv@test2",
    }


def test_producer_class_missing_ticker(tmp_path):
    csv_file = tmp_path / "stocks.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Symbol", "Sector", "Industry"])
        writer.writerow(["WMB", "Energy", "Oil & Gas Midstream"])
    res = dg.producer_class("NONEXISTENT", csv_file, "stocks.csv@test3")
    assert res == {
        "status": "unknown",
        "source": "stocks.csv@test3",
    }


def test_producer_class_empty_industry(tmp_path):
    csv_file = tmp_path / "stocks.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Symbol", "Sector", "Industry"])
        writer.writerow(["EMPTY", "Energy", ""])
    res = dg.producer_class("EMPTY", csv_file, "stocks.csv@test4")
    assert res == {
        "status": "unknown",
        "source": "stocks.csv@test4",
    }


def test_producer_class_missing_file(tmp_path):
    missing_file = tmp_path / "does_not_exist.csv"
    res = dg.producer_class("ANY", missing_file, "stocks.csv@test5")
    assert res["status"] == "unavailable"
    assert res["source"] == "stocks.csv@test5"
    assert "error" in res and res["error"]


def test_producer_class_without_industry_column(tmp_path):
    csv_file = tmp_path / "stocks.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Symbol", "Sector"])
        writer.writerow(["FOO", "Technology"])
    res = dg.producer_class("FOO", csv_file, "stocks.csv@test6")
    assert res["status"] == "unavailable"
    assert res["source"] == "stocks.csv@test6"
    assert "error" in res and res["error"]


def test_producer_class_case_insensitive_columns_and_ticker(tmp_path):
    csv_file = tmp_path / "stocks.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sYmBoL", "sEcToR", "iNdUsTrY"])
        writer.writerow(["fsm", "Basic Materials", "Silver"])
    res = dg.producer_class("FSM", csv_file, "stocks.csv@test7")
    assert res == {
        "status": "ok",
        "depleting": True,
        "sector": "Basic Materials",
        "industry": "Silver",
        "source": "stocks.csv@test7",
    }


# ================================================================================================
# 2. assess() and GATE_VERSION 5 / reason 16 tests
# ================================================================================================

def _base_v5_verdict(**over):
    base = {
        "direction": "hold",
        "gate_version": 5,
        "n_basis": 2,
        "fiduciary_verdict": "PASS",
        "kelly_fraction_pct": 0.0,
        "spread_pct": 5.0,
        "run_source": "orchestrator",
        "producer_class": {
            "status": "ok",
            "depleting": False,
            "sector": "Technology",
            "industry": "Software - Infrastructure",
            "source": "stocks.csv@test",
        },
    }
    base.update(over)
    return base


def test_assess_depleting_producer_unsupported():
    v = _base_v5_verdict(producer_class={
        "status": "ok",
        "depleting": True,
        "sector": "Basic Materials",
        "industry": "Gold",
        "source": "stocks.csv@test",
    })
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert "depleting_producer_unsupported" in reasons


def test_assess_producer_class_unavailable():
    v = _base_v5_verdict(producer_class={
        "status": "unavailable",
        "source": "stocks.csv@test",
        "error": "missing file",
    })
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert "depleting_producer_class_unavailable" in reasons


def test_assess_v5_row_without_stamp_fails_unavailable():
    v = _base_v5_verdict()
    del v["producer_class"]
    actionable, reasons = dg.assess(v)
    assert actionable is False
    assert "depleting_producer_class_unavailable" in reasons


def test_assess_producer_class_unknown_neither_reason():
    v = _base_v5_verdict(producer_class={
        "status": "unknown",
        "source": "stocks.csv@test",
    })
    actionable, reasons = dg.assess(v)
    assert actionable is True
    assert "depleting_producer_unsupported" not in reasons
    assert "depleting_producer_class_unavailable" not in reasons


def test_assess_not_depleting_neither_reason():
    v = _base_v5_verdict(producer_class={
        "status": "ok",
        "depleting": False,
        "sector": "Energy",
        "industry": "Oil & Gas Midstream",
        "source": "stocks.csv@test",
    })
    actionable, reasons = dg.assess(v)
    assert actionable is True
    assert reasons == []


# ================================================================================================
# 3. stamp_and_route tests
# ================================================================================================

def test_stamp_and_route_stamps_producer_class_and_unknown_flag(monkeypatch, tmp_path):
    csv_file = tmp_path / "stocks.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Symbol", "Sector", "Industry"])
        writer.writerow(["KNOWN", "Basic Materials", "Gold"])
    monkeypatch.setitem(dp.CONFIG, "screener_data_dir", str(tmp_path))
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))

    # Case 1: Known depleting ticker
    v1 = {"direction": "hold", "flags": []}
    dp.stamp_and_route(v1, "KNOWN", "orchestrator", screener_data_commit="sha123")
    assert v1["producer_class"] == {
        "status": "ok",
        "depleting": True,
        "sector": "Basic Materials",
        "industry": "Gold",
        "source": "stocks.csv@sha123",
    }
    assert "producer_class_unknown" not in v1["flags"]

    # Case 2: Unknown ticker -> adds producer_class_unknown flag
    v2 = {"direction": "hold", "flags": ["some_flag"]}
    dp.stamp_and_route(v2, "UNKNOWN_TICKER", "orchestrator", screener_data_commit=None)
    assert v2["producer_class"] == {
        "status": "unknown",
        "source": "stocks.csv@unknown",
    }
    assert "producer_class_unknown" in v2["flags"]
    assert "some_flag" in v2["flags"]
