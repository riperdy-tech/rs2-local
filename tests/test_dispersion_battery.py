"""tests/test_dispersion_battery.py — P4.0b (PHASE_4_ANALYST.md, PHASE_4_AMENDMENTS.md A2/B6):
tools/dispersion_battery.py, the frozen-evidence dispersion battery driver.

This script's own job is orchestration — building/reusing a frozen pack and an evidence-store
directory per name, constructing the consensus_valuation.py command line, skipping a name that is
already complete, and aggregating battery_summary.json. consensus_valuation.py's own new options
(--pack-file, --evidence-store, --temperature, --no-early-stop, --out-dir) are exercised against a
fake Ollama client in tools/audit_202608/tests/test_frozen_evidence_battery_options.py; here
`capability_test.build_pack` and `subprocess.run` are stubbed instead, so nothing below reads real
screener data, spawns a real consensus_valuation.py subprocess, or touches the GPU/network/cache/.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import dispersion_battery as db  # noqa: E402


class _Args:
    """Minimal stand-in for the argparse.Namespace run_name() reads."""
    def __init__(self, arm="A", samples=3, temperature=None, dry_run=False,
                model="m", ctx=1000):
        self.arm = arm
        self.samples = samples
        self.temperature = temperature
        self.dry_run = dry_run
        self.model = model
        self.ctx = ctx


def _stub_build_pack(monkeypatch, calls=None):
    if calls is None:
        calls = []
    monkeypatch.setattr(db.cap, "build_pack", lambda name: (calls.append(name), f"# PACK {name}")[1])
    monkeypatch.setattr(db.cap, "TASK", "TASK TEXT")
    monkeypatch.setattr(db.cap, "RESEARCH_ADDENDUM", "ADDENDUM TEXT")
    return calls


# ---- consensus_command: arm -> temperature mapping, explicit override -------------------------

def test_consensus_command_arm_a_has_no_temperature_override():
    cmd = db.consensus_command("GEV", 3, "A", None, Path("p.md"), Path("ev"), Path("out"))
    assert "--temperature" not in cmd
    assert "--no-early-stop" in cmd
    assert "--tools" in cmd
    assert "--pack-file" in cmd and str(Path("p.md")) in cmd
    assert "--evidence-store" in cmd and str(Path("ev")) in cmd
    assert "--out-dir" in cmd and str(Path("out")) in cmd


def test_consensus_command_arm_b_defaults_to_0_3_temperature():
    cmd = db.consensus_command("GEV", 3, "B", None, Path("p.md"), Path("ev"), Path("out"))
    i = cmd.index("--temperature")
    assert cmd[i + 1] == "0.3"


def test_consensus_command_explicit_temperature_overrides_arm_default():
    cmd = db.consensus_command("GEV", 3, "A", 0.5, Path("p.md"), Path("ev"), Path("out"))
    i = cmd.index("--temperature")
    assert cmd[i + 1] == "0.5"


# ---- arm C refuses loudly (P4.6 not built in this phase) --------------------------------------

def test_main_refuses_arm_c(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv",
                        ["dispersion_battery.py", "--names", "GEV", "--samples", "1", "--arm", "C"])
    with pytest.raises(SystemExit):
        db.main()
    assert "HARD FAIL" in capsys.readouterr().out


# ---- --dry-run: builds pack + evidence dir, prints the command, runs nothing -------------------

def test_dry_run_builds_pack_and_evidence_dir_without_subprocess(monkeypatch, tmp_path, capsys):
    _stub_build_pack(monkeypatch)

    def boom(*a, **k):
        raise AssertionError("subprocess.run must not be called in --dry-run")
    monkeypatch.setattr(db.subprocess, "run", boom)

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "dispersion_battery.py", "--names", "GEV", "--samples", "1", "--arm", "A",
        "--out", str(out_dir), "--dry-run"])
    db.main()

    pack_path = out_dir / "GEV" / "_pack.md"
    assert pack_path.exists()
    assert "PACK GEV" in pack_path.read_text(encoding="utf-8")
    assert (out_dir / "GEV" / "_evidence").is_dir()

    out = capsys.readouterr().out
    assert "consensus_valuation.py" in out
    assert "--pack-file" in out
    assert "--evidence-store" in out
    assert not (out_dir / "battery_summary.json").exists()


def test_dry_run_never_touches_the_model(monkeypatch, tmp_path):
    """Hard rule: building a pack for the dry run is allowed only because build_pack makes no
    LLM call. Confirms dry-run truly never reaches subprocess.run/urlopen."""
    _stub_build_pack(monkeypatch)

    def boom_run(*a, **k):
        raise AssertionError("no subprocess in --dry-run")
    monkeypatch.setattr(db.subprocess, "run", boom_run)

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "dispersion_battery.py", "--names", "FIX,AMD", "--samples", "3", "--arm", "A",
        "--out", str(out_dir), "--dry-run"])
    db.main()  # would raise via boom_run if it ever shelled out


# ---- pack reuse: build_pack called once, then reused verbatim ---------------------------------

def test_build_frozen_pack_reuses_existing_file(tmp_path, monkeypatch):
    calls = _stub_build_pack(monkeypatch)
    pack_path = tmp_path / "GEV" / "_pack.md"

    text1, reused1 = db.build_frozen_pack("GEV", pack_path)
    assert reused1 is False
    assert calls == ["GEV"]

    text2, reused2 = db.build_frozen_pack("GEV", pack_path)
    assert reused2 is True
    assert calls == ["GEV"]          # build_pack NOT called a second time
    assert text1 == text2            # byte-identical reuse


# ---- resumability: a complete name+arm is skipped, an incomplete one is (re)run ---------------

def _write_consensus_json(run_dir, samples_run, generated_at="2026-01-01T00:00:00+00:00"):
    run_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "ticker": "GEV", "price": 100.0, "samples_run": samples_run, "spread_pct": 5.0,
        "generated_at": generated_at, "converged": True, "median_iv": 110.0,
        "pack_source": "frozen:x", "pack_sha256": "abc", "temperature": None,
        "runs": [{"sample": i, "iv": 100.0 + i, "scorecard": {}, "plausible": True,
                 "truncated": False, "secs": 5} for i in range(1, samples_run + 1)],
    }
    (run_dir / "consensus.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


def test_run_name_skips_already_complete(monkeypatch, tmp_path):
    _stub_build_pack(monkeypatch)
    out_dir = tmp_path / "out"
    consensus_out = out_dir / "GEV" / "arm_A"
    _write_consensus_json(consensus_out / "GEV_20260101_000000", samples_run=3)

    def boom(*a, **k):
        raise AssertionError("subprocess.run must not be called for an already-complete name")
    monkeypatch.setattr(db.subprocess, "run", boom)

    result = db.run_name("GEV", _Args(arm="A", samples=3), out_dir)
    assert result["samples_run"] == 3
    assert result["ticker"] == "GEV"


def test_run_name_reruns_when_prior_attempt_is_incomplete(monkeypatch, tmp_path):
    """A crashed attempt leaves no consensus.json (it is written only once a run completes) —
    an incomplete prior directory must not be mistaken for done."""
    _stub_build_pack(monkeypatch)
    out_dir = tmp_path / "out"
    consensus_out = out_dir / "GEV" / "arm_A"
    # simulate a crashed attempt: sample files exist, but no consensus.json
    crashed = consensus_out / "GEV_20260101_000000"
    crashed.mkdir(parents=True)
    (crashed / "sample1.md").write_text("partial", encoding="utf-8")

    def fake_run(cmd, *a, **k):
        run_dir = consensus_out / "GEV_20260102_000000"
        _write_consensus_json(run_dir, samples_run=3, generated_at="2026-01-02T00:00:00+00:00")

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(db.subprocess, "run", fake_run)
    result = db.run_name("GEV", _Args(arm="A", samples=3), out_dir)
    assert result["samples_run"] == 3


def test_run_name_reports_nonzero_subprocess_exit(monkeypatch, tmp_path):
    _stub_build_pack(monkeypatch)
    out_dir = tmp_path / "out"

    def fake_run(cmd, *a, **k):
        class R:
            returncode = 1
        return R()

    monkeypatch.setattr(db.subprocess, "run", fake_run)
    result = db.run_name("GEV", _Args(arm="A", samples=3), out_dir)
    assert "error" in result


# ---- sample_direction: pure, diagnostic-only three-way call -----------------------------------

@pytest.mark.parametrize("iv,price,expected", [
    (120.0, 100.0, "undervalued"),
    (80.0, 100.0, "overvalued"),
    (100.0, 100.0, "hold"),
    (None, 100.0, None),
    (100.0, None, None),
    (100.0, 0, None),
])
def test_sample_direction(iv, price, expected):
    assert db.sample_direction(iv, price) == expected


# ---- summarize_run: direction agreement + first-two-sample spread -----------------------------

def test_summarize_run_direction_disagreement_and_spread_first_two():
    doc = {
        "ticker": "GEV", "price": 100.0, "samples_run": 3,
        "pack_source": "frozen:x", "pack_sha256": "abc", "temperature": None,
        "spread_pct": 55.6, "median_iv": 120.0, "converged": False,
        "runs": [
            {"sample": 1, "iv": 120.0, "scorecard": {"bull_iv": 150, "bear_iv": 90},
             "plausible": True, "truncated": False, "secs": 10},
            {"sample": 2, "iv": 140.0, "scorecard": {}, "plausible": True, "truncated": False,
             "secs": 12},
            {"sample": 3, "iv": 90.0, "scorecard": {}, "plausible": True, "truncated": False,
             "secs": 11},
        ],
    }
    out = db.summarize_run("GEV", doc)
    assert out["directions"] == ["undervalued", "undervalued", "overvalued"]
    assert out["direction_agreement"] is False
    assert out["spread_pct_first_two"] == pytest.approx((140 / 120 - 1) * 100, abs=0.05)
    assert len(out["samples"]) == 3


def test_summarize_run_direction_agreement_true_when_all_samples_match():
    doc = {
        "ticker": "GEV", "price": 100.0, "samples_run": 2,
        "pack_source": "frozen:x", "pack_sha256": "abc", "temperature": None,
        "spread_pct": 5.0, "median_iv": 120.0, "converged": True,
        "runs": [
            {"sample": 1, "iv": 118.0, "scorecard": {}, "plausible": True, "truncated": False,
             "secs": 10},
            {"sample": 2, "iv": 122.0, "scorecard": {}, "plausible": True, "truncated": False,
             "secs": 11},
        ],
    }
    out = db.summarize_run("GEV", doc)
    assert out["direction_agreement"] is True
    assert out["spread_pct_first_two"] == pytest.approx((122 / 118 - 1) * 100, abs=0.05)


# ---- main(): overall battery_summary.json aggregation ------------------------------------------

def test_main_writes_battery_summary_with_overall_metrics(monkeypatch, tmp_path):
    def fake_run_name(name, args, out_root):
        if name == "AAA":
            return {"ticker": "AAA", "price": 100.0, "spread_pct_first_two": 10.0,
                    "direction_agreement": True, "directions": ["undervalued"] * 3,
                    "samples": [{"secs": 10}, {"secs": 12}, {"secs": 11}]}
        return {"ticker": "BBB", "price": 100.0, "spread_pct_first_two": 20.0,
                "direction_agreement": False, "directions": ["hold", "overvalued", "hold"],
                "samples": [{"secs": 20}, {"secs": 22}, {"secs": 21}]}

    monkeypatch.setattr(db, "run_name", fake_run_name)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "dispersion_battery.py", "--names", "AAA,BBB", "--samples", "3", "--arm", "A",
        "--out", str(out_dir)])
    db.main()

    summary = json.loads((out_dir / "battery_summary.json").read_text(encoding="utf-8"))
    assert summary["overall"]["n_names"] == 2
    assert summary["overall"]["share_spread_le_15pct_first_two_samples"] == 50.0
    assert summary["overall"]["share_all_samples_agree_on_direction"] == 50.0
    assert summary["overall"]["median_sample_time_s"] == pytest.approx(16.0, abs=0.01)


def test_main_skips_names_with_errors_in_overall_metrics(monkeypatch, tmp_path):
    def fake_run_name(name, args, out_root):
        if name == "AAA":
            return {"ticker": "AAA", "error": "consensus subprocess exit 5"}
        return {"ticker": "BBB", "price": 100.0, "spread_pct_first_two": 10.0,
                "direction_agreement": True, "directions": ["hold"] * 3,
                "samples": [{"secs": 10}]}

    monkeypatch.setattr(db, "run_name", fake_run_name)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "dispersion_battery.py", "--names", "AAA,BBB", "--samples", "3", "--arm", "A",
        "--out", str(out_dir)])
    db.main()

    summary = json.loads((out_dir / "battery_summary.json").read_text(encoding="utf-8"))
    assert summary["overall"]["n_names"] == 1
    assert summary["overall"]["share_spread_le_15pct_first_two_samples"] == 100.0
    assert summary["results"][0]["error"] == "consensus subprocess exit 5"
