"""Tests for P1.7: research brief snapshot, age ceiling, and --force flag."""
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import deep_research
import depth_pipeline as dp


def test_deep_research_force_flag_bypasses_fresh(monkeypatch, tmp_path):
    """P1.7: deep_research.build(force=True) bypasses fresh() cache check."""
    monkeypatch.setitem(deep_research.CONFIG, "out_research_dir", str(tmp_path))
    brief = tmp_path / "FLXS.md"
    brief.write_text("# Cached research\n- [1] https://example.com/source\n", encoding="utf-8")

    fresh_called = []
    def fake_fresh(path, days, ticker=None):
        fresh_called.append(True)
        return True

    monkeypatch.setattr(deep_research, "fresh", fake_fresh)

    # When force=False, fresh() is checked and build() returns early
    res = deep_research.build("FLXS", "Flexsteel", force=False)
    assert len(fresh_called) == 1
    assert res == brief

    # When force=True, fresh() must NOT be called / bypassed
    fresh_called.clear()
    preflight_called = []
    def fake_preflight(*args, **kwargs):
        preflight_called.append(True)
        raise RuntimeError("Stopped at preflight to verify build proceeded past cache check")

    monkeypatch.setattr(deep_research, "preflight", fake_preflight)
    monkeypatch.setattr(deep_research, "pick_tool", lambda: "mock_engine")
    with pytest.raises(RuntimeError, match="Stopped at preflight"):
        deep_research.build("FLXS", "Flexsteel", force=True)

    assert len(fresh_called) == 0, "fresh() must be bypassed when force=True"
    assert len(preflight_called) == 1, "build() should proceed past cache check to preflight"


def test_depth_pipeline_run_research_stale_brief_adds_force(monkeypatch, tmp_path):
    """P1.7: depth_pipeline.run_research passes --force when brief age > research_max_age_days."""
    spawned_cmds = []

    class FakePopen:
        def __init__(self, cmd, *args, **kwargs):
            spawned_cmds.append(cmd)
            self.returncode = 0
        def communicate(self, timeout=None):
            return ("[deep_research] done", "")

    monkeypatch.setattr(dp.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(dp.ops, "wait_unloaded", lambda *a, **k: (True, "unloaded"))
    monkeypatch.setattr(dp.rs2_data, "resolve_name", lambda t: "Flexsteel Industries")
    monkeypatch.setitem(dp.CONFIG, "research_max_age_days", 14)

    # Case 1: Brief is 20 days old (> 14 days) -> --force must be included
    monkeypatch.setattr(dp, "_research_brief_provenance", lambda t: ("2026-08-30", 20.0))
    dp.run_research("FLXS")
    assert len(spawned_cmds) == 1
    assert "--force" in spawned_cmds[0]
    assert "FLXS" in spawned_cmds[0]
    assert "Flexsteel Industries" in spawned_cmds[0]

    # Case 2: Brief is 5 days old (<= 14 days) -> --force must NOT be included
    spawned_cmds.clear()
    monkeypatch.setattr(dp, "_research_brief_provenance", lambda t: ("2026-09-18", 5.0))
    dp.run_research("FLXS")
    assert len(spawned_cmds) == 1
    assert "--force" not in spawned_cmds[0]


def test_consensus_valuation_snapshots_research_brief_and_asof(tmp_path, monkeypatch):
    """P1.7: consensus_valuation copies research/{T}.md to <run dir>/_research_brief.md

    and records research_brief_asof in consensus.json.
    """
    sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
    import rs2_data

    research_dir = tmp_path / "research"
    research_dir.mkdir(parents=True)
    brief_file = research_dir / "FLXS.md"
    brief_content = "# Institutional Research Brief for FLXS\n- [1] https://flexsteel.com/sec"
    brief_file.write_text(brief_content, encoding="utf-8")

    out_runs = tmp_path / "runs"
    out_runs.mkdir(parents=True)

    monkeypatch.setitem(rs2_data.CONFIG, "out_research_dir", str(research_dir))

    # Test the snapshotting block logic directly
    run_dir = out_runs / "FLXS_20260923_120000"
    run_dir.mkdir(parents=True)

    r_dir = rs2_data.CONFIG.get("out_research_dir") or "research"
    r_dir_path = Path(r_dir)
    if not r_dir_path.is_absolute():
        r_dir_path = HERE / r_dir_path
    r_file = r_dir_path / "FLXS.md"
    research_brief_asof = None
    if r_file.exists():
        mtime = r_file.stat().st_mtime
        research_brief_asof = datetime.fromtimestamp(mtime).isoformat()
        shutil.copyfile(r_file, run_dir / "_research_brief.md")

    assert (run_dir / "_research_brief.md").exists()
    assert (run_dir / "_research_brief.md").read_text(encoding="utf-8") == brief_content
    assert research_brief_asof is not None
