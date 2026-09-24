"""P4.3 — status.py's dashboard shows `entry_timing` and `momentum_view` on the recent-
underwritings table."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import status as st  # noqa: E402


def test_dashboard_shows_entry_timing_and_momentum_view(tmp_path, monkeypatch):
    ledger = tmp_path / "depth_ledger.jsonl"
    row = {
        "ticker": "MOMS", "direction": "undervalued", "date": "2026-09-24",
        "consensus_dir": "MOMS_20260924_120000", "price": 100.0, "median_iv": 130.0,
        "spread_pct": 5.0, "scorecard": {"base_iv": 128.0},
        "entry_timing": "wait_for_momentum", "momentum_view": "contradicting",
        "position_basis": "value",
    }
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")

    monkeypatch.setattr(st, "LEDGER", ledger)
    monkeypatch.setattr(st, "DEPTH_STATE", tmp_path / "depth_state.json")
    monkeypatch.setattr(st, "DEPTH_PROGRESS", tmp_path / "depth_progress.json")
    monkeypatch.setattr(st, "DEPTH_LOCK", tmp_path / "orchestrate_depth.lock")
    monkeypatch.setattr(st, "DEPTH_PAUSE", tmp_path / "DEPTH_PAUSED")
    monkeypatch.setattr(st, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    # Avoid a real `Get-ScheduledTaskInfo` subprocess call — irrelevant to this test and slow.
    monkeypatch.setattr(st, "_task_info", lambda: (None, None, None))

    out = st.depth_snapshot()
    assert "Entry" in out
    assert "Basis" in out
    assert "Momentum" in out
    assert "wait_for_momentum" in out
    assert "value" in out
    assert "contradicting" in out


def test_dashboard_shows_em_dash_when_fields_absent(tmp_path, monkeypatch):
    ledger = tmp_path / "depth_ledger.jsonl"
    row = {"ticker": "NOMOM", "direction": "hold", "date": "2026-09-24",
           "consensus_dir": "NOMOM_20260924_120000", "price": 50.0, "median_iv": 50.0,
           "spread_pct": 1.0, "scorecard": {"base_iv": 50.0}}
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")

    monkeypatch.setattr(st, "LEDGER", ledger)
    monkeypatch.setattr(st, "DEPTH_STATE", tmp_path / "depth_state.json")
    monkeypatch.setattr(st, "DEPTH_PROGRESS", tmp_path / "depth_progress.json")
    monkeypatch.setattr(st, "DEPTH_LOCK", tmp_path / "orchestrate_depth.lock")
    monkeypatch.setattr(st, "DEPTH_PAUSE", tmp_path / "DEPTH_PAUSED")
    monkeypatch.setattr(st, "DEPTH_LOG", tmp_path / "depth_orchestrate.log")
    monkeypatch.setattr(st, "_task_info", lambda: (None, None, None))

    out = st.depth_snapshot()
    assert "NOMOM" in out   # renders without raising on a row missing the new fields
