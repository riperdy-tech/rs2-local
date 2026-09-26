"""tests/test_failfast_street.py — P4 Item 3: fail-fast on street range in measurement runs.

Tests that consensus_valuation.py with --failfast-street:
  - stops after sample 1 if sample 1 is below 0.5x discounted street low
  - stops after sample 1 if sample 1 is above 2.0x discounted street high
  - continues inside the band
  - continues when there is no band or the band is stale
  - does not fail fast when --failfast-street is not passed
And tests that dispersion_battery.py:
  - arm C resolves default model rs2-analyst-deep-mtp5-v31 without temperature override
  - passes --failfast-street to consensus_valuation.py
  - records failfast and research_calls, repeat_calls, desk_runs, desk_swing in summary
"""
import json
import sys
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent.parent / "tools"))

import consensus_valuation as cv  # noqa: E402
import dispersion_battery as db   # noqa: E402


def _make_memo(base_iv=120.0):
    return (
        "SECTION 0. EXECUTIVE VERDICT\n"
        + "\n".join(f"  detail line {n} of the institutional memorandum." for n in range(400))
        + "\nSECTION 12. MACHINE CONTRACT\n"
        "```json:underwriting\n"
        f'{{"base_iv": {base_iv}, "bull_iv": {round(base_iv*1.2, 2)}, "bear_iv": {round(base_iv*0.8, 2)}, '
        '"base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2, '
        '"conviction_score": 10, "business_quality_moat": 3, "kelly_fraction_pct": 2.0, '
        '"base_cf_used": 1.0, "base_cf_basis": "other"}\n'
        "```\n"
    )


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ollama_payload(content):
    return {
        "message": {"content": content},
        "done_reason": "stop",
        "eval_count": 500,
        "prompt_eval_count": 100,
    }


def _out_run_dir(out_dir, ticker="GEV"):
    dirs = list(out_dir.glob(f"{ticker}_*"))
    assert len(dirs) == 1, f"expected exactly one run dir, found {dirs}"
    return dirs[0]


def _setup_frozen_pack(tmp_path):
    frozen = tmp_path / "frozen_pack.md"
    frozen.write_text("# DATA PACK - GEV (frozen)\n\nTest pack content.\n", encoding="utf-8")
    return frozen


# ---- failfast street tests for consensus_valuation.py -----------------------------------------

def test_failfast_stops_after_sample_1_below_0_5x(monkeypatch, tmp_path):
    """When sample 1 IV < 0.5 * (band.low / 1.10), sampling stops and failfast record is written."""
    memo = _make_memo(base_iv=40.0)  # below 0.5 * (110 / 1.10) = 50.0
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(_ollama_payload(memo)))
    monkeypatch.setattr(cv.vb, "_consensus_band",
                        lambda ticker: {"low": 110.0, "high": 220.0, "stale": False})

    frozen = _setup_frozen_pack(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "3",
        "--pack-file", str(frozen), "--out-dir", str(out_dir), "--failfast-street"
    ])
    cv.main()

    d = _out_run_dir(out_dir)
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))

    assert doc["samples_run"] == 1
    assert doc["converged"] is False
    assert doc["verdict"] == "FAILFAST — sample 1 outside street range"
    assert "failfast" in doc
    ff = doc["failfast"]
    assert ff["sample"] == 1
    assert ff["iv"] == 40.0
    assert ff["street_low_disc"] == 100.0
    assert ff["street_high_disc"] == 200.0
    assert ff["ratio_to_low"] == 0.4
    assert ff["ratio_to_high"] == 0.2
    assert ff["rule"] == "sample 1 below 0.5x discounted street low or above 2x discounted street high"


def test_failfast_stops_after_sample_1_above_2_0x(monkeypatch, tmp_path):
    """When sample 1 IV > 2.0 * (band.high / 1.10), sampling stops and failfast record is written."""
    memo = _make_memo(base_iv=450.0)  # above 2.0 * (220 / 1.10) = 400.0
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(_ollama_payload(memo)))
    monkeypatch.setattr(cv.vb, "_consensus_band",
                        lambda ticker: {"low": 110.0, "high": 220.0, "stale": False})

    frozen = _setup_frozen_pack(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "3",
        "--pack-file", str(frozen), "--out-dir", str(out_dir), "--failfast-street"
    ])
    cv.main()

    d = _out_run_dir(out_dir)
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))

    assert doc["samples_run"] == 1
    assert doc["converged"] is False
    assert doc["verdict"] == "FAILFAST — sample 1 outside street range"
    assert "failfast" in doc
    ff = doc["failfast"]
    assert ff["sample"] == 1
    assert ff["iv"] == 450.0
    assert ff["street_low_disc"] == 100.0
    assert ff["street_high_disc"] == 200.0
    assert ff["ratio_to_low"] == 4.5
    assert ff["ratio_to_high"] == 2.25


def test_failfast_continues_inside_band(monkeypatch, tmp_path):
    """When sample 1 IV is inside [0.5 * lo_d, 2.0 * hi_d], sampling continues."""
    memo = _make_memo(base_iv=120.0)  # inside [50.0, 400.0]
    real = cv.extract_desk_snapshot_metrics

    def desk_backed(*a, **k):
        # the fake memo never calls the desk; a desk-less sample is not usable and cannot converge
        out = real(*a, **k)
        out.update(desk_calls=1, desk_iv_match=True)
        return out

    monkeypatch.setattr(cv, "extract_desk_snapshot_metrics", desk_backed)
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(_ollama_payload(memo)))
    monkeypatch.setattr(cv.vb, "_consensus_band",
                        lambda ticker: {"low": 110.0, "high": 220.0, "stale": False})

    frozen = _setup_frozen_pack(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "3",
        "--no-early-stop", "--pack-file", str(frozen), "--out-dir", str(out_dir),
        "--failfast-street"
    ])
    cv.main()

    d = _out_run_dir(out_dir)
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))

    assert doc["samples_run"] == 3
    assert "failfast" not in doc
    assert doc["converged"] is True
    assert doc["verdict"] == "CONVERGED"


def test_failfast_continues_when_no_band(monkeypatch, tmp_path):
    """When no analyst band exists, failfast is inactive and sampling continues."""
    memo = _make_memo(base_iv=40.0)
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(_ollama_payload(memo)))
    monkeypatch.setattr(cv.vb, "_consensus_band", lambda ticker: None)

    frozen = _setup_frozen_pack(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "3",
        "--no-early-stop", "--pack-file", str(frozen), "--out-dir", str(out_dir),
        "--failfast-street"
    ])
    cv.main()

    d = _out_run_dir(out_dir)
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))

    assert doc["samples_run"] == 3
    assert "failfast" not in doc


def test_failfast_continues_when_band_stale(monkeypatch, tmp_path):
    """When analyst band is stale, failfast is inactive and sampling continues."""
    memo = _make_memo(base_iv=40.0)
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(_ollama_payload(memo)))
    monkeypatch.setattr(cv.vb, "_consensus_band",
                        lambda ticker: {"low": 110.0, "high": 220.0, "stale": True})

    frozen = _setup_frozen_pack(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "3",
        "--no-early-stop", "--pack-file", str(frozen), "--out-dir", str(out_dir),
        "--failfast-street"
    ])
    cv.main()

    d = _out_run_dir(out_dir)
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))

    assert doc["samples_run"] == 3
    assert "failfast" not in doc


def test_failfast_not_active_when_flag_not_passed(monkeypatch, tmp_path):
    """When --failfast-street is not passed, sampling never fails fast even if IV is extreme."""
    memo = _make_memo(base_iv=40.0)
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResponse(_ollama_payload(memo)))
    monkeypatch.setattr(cv.vb, "_consensus_band",
                        lambda ticker: {"low": 110.0, "high": 220.0, "stale": False})

    frozen = _setup_frozen_pack(tmp_path)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "2",
        "--no-early-stop", "--pack-file", str(frozen), "--out-dir", str(out_dir)
    ])
    cv.main()

    d = _out_run_dir(out_dir)
    doc = json.loads((d / "consensus.json").read_text(encoding="utf-8"))

    assert doc["samples_run"] == 2
    assert "failfast" not in doc


# ---- dispersion_battery integration tests -----------------------------------------------------

def test_dispersion_battery_arm_c_defaults_and_failfast():
    """Battery arm C resolves default model rs2-analyst-deep-mtp5-v31 and passes --failfast-street."""
    cmd = db.consensus_command(
        name="AMD", samples=3, arm="C", temperature=None,
        pack_path=Path("p.md"), evidence_dir=Path("ev"), consensus_out=Path("out"),
        failfast_street=True
    )
    assert "--failfast-street" in cmd
    assert "--temperature" not in cmd
    i = cmd.index("--model")
    assert cmd[i + 1] == "rs2-analyst-deep-mtp5-v31"


def test_dispersion_battery_records_failfast_and_sample_metrics():
    """battery_summary.json records failfast per name and per-sample research and desk metrics."""
    doc = {
        "ticker": "AMD",
        "price": 600.0,
        "samples_run": 1,
        "pack_source": "frozen:p.md",
        "pack_sha256": "abc",
        "temperature": None,
        "spread_pct": None,
        "median_iv": 146.0,
        "converged": False,
        "failfast": {
            "sample": 1,
            "iv": 146.0,
            "street_low_disc": 350.0,
            "street_high_disc": 750.0,
            "ratio_to_low": 0.417,
            "ratio_to_high": 0.195,
            "rule": "sample 1 below 0.5x discounted street low or above 2x discounted street high",
        },
        "runs": [
            {
                "sample": 1, "iv": 146.0, "scorecard": {}, "plausible": True, "truncated": False,
                "secs": 25, "research_calls": 26, "repeat_calls": 8,
                "desk_runs": [146.0], "desk_swing": None,
            },
        ],
    }
    summary = db.summarize_run("AMD", doc)
    assert summary["failfast"] == doc["failfast"]
    assert len(summary["samples"]) == 1
    s = summary["samples"][0]
    assert s["research_calls"] == 26
    assert s["repeat_calls"] == 8
    assert s["desk_runs"] == [146.0]
    assert s["desk_swing"] is None
