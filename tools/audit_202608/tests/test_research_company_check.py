import json
import pytest
from pathlib import Path
from tools.audit_202608.research_brief_guard import check_research_brief
from tools.audit_202608.consensus_valuation import snapshot_research_brief
import depth_pipeline as dp


def test_check_research_brief_valid():
    # Apple: Ticker AAPL, Sector Technology, Industry Consumer Electronics
    brief = """# DEEP RESEARCH BRIEF — Apple Inc. (AAPL)
Apple Inc. is a global leader in consumer electronics and technology.
The iPhone ecosystem demonstrates durable competitive advantages.
"""
    ok, reason = check_research_brief("AAPL", brief_text=brief, company_name="Apple Inc.", sector="Technology", industry="Consumer Electronics")
    assert ok is True
    assert reason is None


def test_check_research_brief_missing_company():
    # Brief about Microsoft, evaluated for Apple
    brief = """# DEEP RESEARCH BRIEF — Microsoft Corporation (MSFT)
Microsoft Corporation is a leader in software and cloud infrastructure.
Azure and Windows drive strong revenue.
"""
    ok, reason = check_research_brief("AAPL", brief_text=brief, company_name="Apple Inc.", sector="Technology", industry="Consumer Electronics")
    assert ok is False
    assert "does not contain ticker 'AAPL' or company name" in reason


def test_check_research_brief_wrong_industry_sector():
    # CART (Instacart) evaluated against industrial carts brief
    # CART: Sector Consumer Defensive, Industry Grocery Stores
    brief = """# DEEP RESEARCH BRIEF — CART
The market for heavy-duty steel utility carts and warehouse equipment is growing.
Material handling carts with durable caster wheels dominate factory floors.
"""
    ok, reason = check_research_brief("CART", brief_text=brief, company_name="Maplebear Inc.", sector="Consumer Defensive", industry="Grocery Stores")
    assert ok is False
    assert "does not contain sector" in reason or "industry" in reason


def test_snapshot_research_brief_refuses_invalid_brief(tmp_path, monkeypatch):
    import rs2_data
    r_dir = tmp_path / "research"
    r_dir.mkdir()
    brief_file = r_dir / "CART.md"
    # Wrong brief for CART (steel carts, no grocery/defensive words)
    brief_file.write_text("# CART\nIndustrial steel carts with rubber wheels for warehouses.\n", encoding="utf-8")

    run_dir = tmp_path / "run_cart"
    run_dir.mkdir()

    monkeypatch.setitem(rs2_data.CONFIG, "out_research_dir", str(r_dir))
    monkeypatch.setattr(rs2_data, "resolve_name", lambda t: "Maplebear Inc.")
    monkeypatch.setattr(rs2_data, "sector_lookup", lambda t: ("Consumer Defensive", "Grocery Stores"))

    res = snapshot_research_brief("CART", run_dir, validate=True)
    assert res.wrong_company is True
    # The brief must NOT be snapshotted as valid
    assert not (run_dir / "_research_brief.md").exists()


def test_snapshot_research_brief_accepts_valid_brief(tmp_path, monkeypatch):
    import rs2_data
    r_dir = tmp_path / "research"
    r_dir.mkdir()
    brief_file = r_dir / "CART.md"
    brief_file.write_text("# Instacart (CART)\nOnline grocery delivery platform in consumer defensive sector.\n", encoding="utf-8")

    run_dir = tmp_path / "run_cart"
    run_dir.mkdir()

    monkeypatch.setitem(rs2_data.CONFIG, "out_research_dir", str(r_dir))
    monkeypatch.setattr(rs2_data, "resolve_name", lambda t: "Maplebear Inc. d/b/a Instacart")
    monkeypatch.setattr(rs2_data, "sector_lookup", lambda t: ("Consumer Defensive", "Grocery Stores"))

    res = snapshot_research_brief("CART", run_dir, validate=True)
    assert res.wrong_company is False
    assert (run_dir / "_research_brief.md").exists()
    assert (run_dir / "_research_brief.md").read_text(encoding="utf-8") == brief_file.read_text(encoding="utf-8")


def test_run_research_retries_with_force_and_falls_back_to_no_research(monkeypatch, tmp_path):
    # Mock research invocation in depth_pipeline
    calls = []
    def fake_invoke(t, name, rv, force=False):
        calls.append({"ticker": t, "force": force})

    monkeypatch.setattr(dp, "_invoke_deep_research", fake_invoke)
    monkeypatch.setattr(dp.ops, "wait_unloaded", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(dp, "_research_brief_provenance", lambda t: (None, None))
    monkeypatch.setitem(dp.CONFIG, "research_venv_python", str(Path(__file__)))  # exists

    # First attempt fails check, second attempt (--force) also fails check
    check_results = [
        (False, "missing company"),  # after first invoke
        (False, "still missing company"),  # after second invoke (--force)
    ]
    def fake_check(t):
        return check_results.pop(0)

    monkeypatch.setattr(dp, "check_research_brief", fake_check)

    ok = dp.run_research("FAKE")
    assert ok is False  # proceeds with --no-research semantics
    assert len(calls) == 2
    assert calls[0]["force"] is False
    assert calls[1]["force"] is True


def test_run_research_succeeds_on_force_retry(monkeypatch, tmp_path):
    calls = []
    def fake_invoke(t, name, rv, force=False):
        calls.append({"ticker": t, "force": force})

    monkeypatch.setattr(dp, "_invoke_deep_research", fake_invoke)
    monkeypatch.setattr(dp.ops, "wait_unloaded", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(dp, "_research_brief_provenance", lambda t: (None, None))
    monkeypatch.setitem(dp.CONFIG, "research_venv_python", str(Path(__file__)))

    # First attempt fails check, second attempt (--force) succeeds
    check_results = [
        (False, "missing sector"),
        (True, None),
    ]
    def fake_check(t):
        return check_results.pop(0)

    monkeypatch.setattr(dp, "check_research_brief", fake_check)

    ok = dp.run_research("FAKE")
    assert ok is True
    assert len(calls) == 2
    assert calls[0]["force"] is False
    assert calls[1]["force"] is True
