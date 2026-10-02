"""tests/test_time_travel_trial.py — Phase 4 E4.3: tools/time_travel_trial.py, the point-in-time
(time-travel) trial driver.

This script's own job is orchestration — building/reusing a point-in-time pack per name, fetching
its as-of price, constructing the consensus_valuation.py command line, skipping a name that is
already complete, and grading each result against realized price action. Everything that would
touch the network, Ollama, or the real screener/MRI data is stubbed: `capability_test.build_pack`,
`capability_test._asof_price_lookup`, `subprocess.run` and `grade_depth_verdicts.fetch_history`.
`depth_pipeline.band_verdict` is exercised for real (it is a pure function over an already-built
consensus.json dict — no I/O, no Ollama, no orchestration) so the direction/m/momentum_view/
entry_timing plumbing is proven end to end, not just assumed.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("crux_valid_everywhere")      # revision 19: these tests are about their own rule, not the crux

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

import time_travel_trial as ttt  # noqa: E402


class _Args:
    def __init__(self, samples=1, model="rs2-analyst-deep-mtp5-v31", dry_run=False):
        self.samples = samples
        self.model = model
        self.dry_run = dry_run


def _stub_build_pack(monkeypatch, calls=None):
    if calls is None:
        calls = []

    def fake_build_pack(name, asof=None):
        calls.append((name, asof))
        return f"# PACK {name} asof={asof}"
    monkeypatch.setattr(ttt.cap, "build_pack", fake_build_pack)
    monkeypatch.setattr(ttt.cap, "TASK", "TASK TEXT")
    return calls


def _stub_asof_price(monkeypatch, price=100.0, asof_str="2026-03-31", calls=None):
    if calls is None:
        calls = []

    def fake(t, asof_date, lookback_days=400):
        calls.append((t, asof_date))
        return {"price": price, "asof": asof_str, "series": {asof_str: price}}
    monkeypatch.setattr(ttt.cap, "_asof_price_lookup", fake)
    return calls


def _boom_subprocess(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess.run must not be called here")
    monkeypatch.setattr(ttt.subprocess, "run", boom)


def _write_consensus_json(run_dir, ticker="GEV", price=100.0, median_iv=120.0, samples_run=1,
                          generated_at="2026-03-31T00:00:00+00:00", momentum_view="confirming",
                          entry_timing="buy_now"):
    run_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "ticker": ticker, "price": price, "samples_run": samples_run,
        "generated_at": generated_at, "converged": True, "median_iv": median_iv,
        "median_mos_pct": round((median_iv / price - 1) * 100, 1),
        "spread_pct": 5.0, "tolerance_pct": 25.0,
        "scorecard": {"momentum_view": momentum_view, "entry_timing": entry_timing},
        "runs": [{"sample": i, "iv": median_iv, "plausible": True, "truncated": False,
                 "flags": []} for i in range(1, samples_run + 1)],
    }
    (run_dir / "consensus.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


# ---- consensus_command: the exact flags this harness needs -------------------------------------

def test_consensus_command_shape():
    cmd = ttt.consensus_command("GEV", 1, "rs2-analyst-deep-mtp5-v31", Path("p.md"),
                                Path("out"), 872.45, "2026-03-31")
    assert "--tools" not in cmd            # no literal flag exists; omitting it means tools off
    assert "--no-research" in cmd
    assert "--pack-file" in cmd and str(Path("p.md")) in cmd
    assert "--price" in cmd and "872.45" in cmd
    assert "--price-asof" in cmd and "2026-03-31" in cmd
    assert "--out-dir" in cmd and str(Path("out")) in cmd
    assert "--model" in cmd and "rs2-analyst-deep-mtp5-v31" in cmd
    assert "--samples" in cmd and "1" in cmd
    assert "--no-early-stop" in cmd


# ---- --dry-run: builds pack, fetches price, prints command, runs nothing -----------------------

def test_dry_run_builds_pack_and_fetches_price_without_subprocess(monkeypatch, tmp_path, capsys):
    _stub_build_pack(monkeypatch)
    _stub_asof_price(monkeypatch, price=872.45, asof_str="2026-03-31")
    _boom_subprocess(monkeypatch)

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "time_travel_trial.py", "--names", "GEV", "--asof", "2026-03-31",
        "--horizon-end", "2026-06-30", "--out", str(out_dir), "--dry-run"])
    ttt.main()

    pack_path = out_dir / "GEV" / "_pack.md"
    assert pack_path.exists()
    assert "PACK GEV asof=2026-03-31" in pack_path.read_text(encoding="utf-8")

    out = capsys.readouterr().out
    assert "consensus_valuation.py" in out
    assert "--price 872.45" in out
    assert "--no-research" in out

    summary = json.loads((out_dir / "trial_summary.json").read_text(encoding="utf-8"))
    assert summary["dry_run"] is True
    assert summary["results"][0]["asof_price"] == 872.45


def test_dry_run_never_reaches_the_model(monkeypatch, tmp_path):
    _stub_build_pack(monkeypatch)
    _stub_asof_price(monkeypatch)
    _boom_subprocess(monkeypatch)

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "time_travel_trial.py", "--names", "FIX,AMD", "--asof", "2026-03-31",
        "--horizon-end", "2026-06-30", "--out", str(out_dir), "--dry-run"])
    ttt.main()   # would raise via _boom_subprocess if it ever shelled out


def test_dry_run_skips_a_name_with_no_asof_price(monkeypatch, tmp_path):
    _stub_build_pack(monkeypatch)
    monkeypatch.setattr(ttt.cap, "_asof_price_lookup",
                        lambda t, asof_date, lookback_days=400: None)
    _boom_subprocess(monkeypatch)

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "time_travel_trial.py", "--names", "ZZZZ", "--asof", "2026-03-31",
        "--horizon-end", "2026-06-30", "--out", str(out_dir), "--dry-run"])
    ttt.main()

    summary = json.loads((out_dir / "trial_summary.json").read_text(encoding="utf-8"))
    assert summary["results"][0]["error"] == "no_asof_price"


# ---- validation ----------------------------------------------------------------------------

def test_main_refuses_a_horizon_end_not_after_asof(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", [
        "time_travel_trial.py", "--names", "GEV", "--asof", "2026-03-31",
        "--horizon-end", "2026-01-01", "--out", str(tmp_path / "out"), "--dry-run"])
    with pytest.raises(SystemExit):
        ttt.main()


def test_main_refuses_empty_names(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "time_travel_trial.py", "--names", " , ", "--asof", "2026-03-31",
        "--horizon-end", "2026-06-30", "--dry-run"])
    with pytest.raises(SystemExit):
        ttt.main()


# ---- pack reuse -----------------------------------------------------------------------------

def test_build_asof_pack_reuses_existing_file(tmp_path, monkeypatch):
    calls = _stub_build_pack(monkeypatch)
    pack_path = tmp_path / "GEV" / "_pack.md"

    text1, reused1 = ttt.build_asof_pack("GEV", date(2026, 3, 31), pack_path)
    assert reused1 is False
    assert calls == [("GEV", date(2026, 3, 31))]

    text2, reused2 = ttt.build_asof_pack("GEV", date(2026, 3, 31), pack_path)
    assert reused2 is True
    assert calls == [("GEV", date(2026, 3, 31))]   # build_pack NOT called a second time
    assert text1 == text2


def test_asof_pack_never_carries_the_research_addendum(tmp_path, monkeypatch):
    """The pack sent to the model must be TASK-only — no RESEARCH_ADDENDUM, since research/tools
    are off in the trial (no --tools is ever passed to consensus_valuation.py)."""
    monkeypatch.setattr(ttt.cap, "build_pack", lambda name, asof=None: "# PACK")
    monkeypatch.setattr(ttt.cap, "TASK", "TASK TEXT")
    monkeypatch.setattr(ttt.cap, "RESEARCH_ADDENDUM", "SHOULD NEVER APPEAR")
    pack_path = tmp_path / "GEV" / "_pack.md"
    text, _ = ttt.build_asof_pack("GEV", date(2026, 3, 31), pack_path)
    assert "SHOULD NEVER APPEAR" not in text


# ---- resumability ---------------------------------------------------------------------------

def test_run_name_skips_already_complete(monkeypatch, tmp_path):
    _stub_build_pack(monkeypatch)
    _stub_asof_price(monkeypatch)
    _boom_subprocess(monkeypatch)
    out_dir = tmp_path / "out"
    consensus_out = out_dir / "GEV" / "consensus"
    _write_consensus_json(consensus_out / "GEV_20260331_000000", samples_run=1)

    result = ttt.run_name("GEV", date(2026, 3, 31), _Args(samples=1), out_dir)
    assert result["samples_run"] == 1
    assert result["ticker"] == "GEV"


def test_run_name_reruns_when_prior_attempt_is_incomplete(monkeypatch, tmp_path):
    _stub_build_pack(monkeypatch)
    _stub_asof_price(monkeypatch)
    out_dir = tmp_path / "out"
    consensus_out = out_dir / "GEV" / "consensus"
    crashed = consensus_out / "GEV_20260331_000000"
    crashed.mkdir(parents=True)
    (crashed / "sample1.md").write_text("partial", encoding="utf-8")

    def fake_run(cmd, *a, **k):
        _write_consensus_json(consensus_out / "GEV_20260331_010000", samples_run=1,
                              generated_at="2026-03-31T01:00:00+00:00")

        class R:
            returncode = 0
        return R()
    monkeypatch.setattr(ttt.subprocess, "run", fake_run)

    result = ttt.run_name("GEV", date(2026, 3, 31), _Args(samples=1), out_dir)
    assert result["samples_run"] == 1


def test_run_name_reports_nonzero_subprocess_exit(monkeypatch, tmp_path):
    _stub_build_pack(monkeypatch)
    _stub_asof_price(monkeypatch)
    out_dir = tmp_path / "out"

    def fake_run(cmd, *a, **k):
        class R:
            returncode = 1
        return R()
    monkeypatch.setattr(ttt.subprocess, "run", fake_run)

    result = ttt.run_name("GEV", date(2026, 3, 31), _Args(samples=1), out_dir)
    assert result["error"] == "consensus subprocess exit 1"


# ---- grade_name: real depth_pipeline.band_verdict, fake price cache -----------------------------

def test_grade_name_undervalued_beats_iwm_is_a_hit():
    doc = {
        "ticker": "GEV", "price": 100.0, "median_iv": 130.0, "median_mos_pct": 30.0,
        "spread_pct": 5.0, "tolerance_pct": 25.0,
        "scorecard": {"momentum_view": "confirming", "entry_timing": "buy_now"},
        "runs": [{"iv": 128.0, "plausible": True, "truncated": False, "flags": []},
                {"iv": 132.0, "plausible": True, "truncated": False, "flags": []}],
    }
    price_cache = {
        "GEV": {"2026-03-31": 100.0, "2026-06-30": 130.0},
        "IWM": {"2026-03-31": 200.0, "2026-06-30": 210.0},
    }
    row = ttt.grade_name("GEV", "2026-03-31", "2026-06-30", price_cache, doc)
    assert row["direction"] == "undervalued"
    assert row["momentum_view"] == "confirming"
    assert row["entry_timing"] == "buy_now"
    assert row["return_pct"] == pytest.approx(30.0, abs=0.01)
    assert row["excess_vs_iwm_pct"] == pytest.approx(25.0, abs=0.01)   # 30% - IWM's 5%
    assert row["hit"] is True


def test_grade_name_overvalued_that_still_beats_iwm_is_a_miss():
    doc = {
        "ticker": "GEV", "price": 100.0, "median_iv": 60.0, "median_mos_pct": -40.0,
        "spread_pct": 5.0, "tolerance_pct": 25.0,
        "scorecard": {"momentum_view": "contradicting", "entry_timing": "avoid"},
        "runs": [{"iv": 58.0, "plausible": True, "truncated": False, "flags": []},
                {"iv": 62.0, "plausible": True, "truncated": False, "flags": []}],
    }
    price_cache = {
        "GEV": {"2026-03-31": 100.0, "2026-06-30": 120.0},
        "IWM": {"2026-03-31": 200.0, "2026-06-30": 205.0},
    }
    row = ttt.grade_name("GEV", "2026-03-31", "2026-06-30", price_cache, doc)
    assert row["direction"] == "overvalued"
    assert row["hit"] is False   # +20% return, +2.5% IWM: still beat the market -> a miss


def test_grade_name_hold_is_not_scored():
    doc = {
        "ticker": "GEV", "price": 100.0, "median_iv": 102.0, "median_mos_pct": 2.0,
        "spread_pct": 5.0, "tolerance_pct": 25.0,
        "scorecard": {"momentum_view": "neutral", "entry_timing": "wait_for_momentum"},
        "runs": [{"iv": 101.0, "plausible": True, "truncated": False, "flags": []},
                {"iv": 103.0, "plausible": True, "truncated": False, "flags": []}],
    }
    price_cache = {
        "GEV": {"2026-03-31": 100.0, "2026-06-30": 105.0},
        "IWM": {"2026-03-31": 200.0, "2026-06-30": 210.0},
    }
    row = ttt.grade_name("GEV", "2026-03-31", "2026-06-30", price_cache, doc)
    assert row["direction"] == "hold"
    assert row["hit"] is None


def test_grade_name_missing_price_data_leaves_return_none():
    doc = {
        "ticker": "ZZZZ", "price": 100.0, "median_iv": 130.0, "median_mos_pct": 30.0,
        "spread_pct": 5.0, "tolerance_pct": 25.0,
        "scorecard": {}, "runs": [{"iv": 130.0, "plausible": True, "truncated": False, "flags": []}],
    }
    price_cache = {"IWM": {"2026-03-31": 200.0, "2026-06-30": 210.0}}   # no ZZZZ series at all
    row = ttt.grade_name("ZZZZ", "2026-03-31", "2026-06-30", price_cache, doc)
    assert row["return_pct"] is None
    assert row["excess_vs_iwm_pct"] is None
    assert row["hit"] is None
    assert "position_basis" in row


def test_write_markdown_includes_position_basis(tmp_path):
    args = _Args()
    args.asof = "2026-03-31"
    args.horizon_end = "2026-06-30"
    rows = [{
        "ticker": "GEV", "direction": "undervalued", "base_iv": 130.0, "price_at_asof": 100.0,
        "mos_pct": 30.0, "momentum_view": "confirming", "entry_timing": "buy_now",
        "position_basis": "value", "return_pct": 30.0, "excess_vs_iwm_pct": 25.0, "hit": True,
    }]
    ttt.write_markdown(tmp_path, args, rows)
    md = (tmp_path / "trial_summary.md").read_text(encoding="utf-8")
    assert "position_basis" in md
    assert "| value |" in md

