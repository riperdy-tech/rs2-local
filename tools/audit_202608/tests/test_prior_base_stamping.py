"""P4.7/B2 — consensus_valuation.py's `--prior-base` option: parsing, and doc["prior_base"]
stamping. Driven end to end against a fake Ollama client (same harness as
test_frozen_evidence_battery_options.py) so this exercises main()'s real argument parsing and
doc-assembly, not just the pure early_stop_check logic covered by test_early_stop_backstops.py.
"""
import json
import sys
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import consensus_valuation as cv  # noqa: E402


MEMO = (
    "SECTION 0. EXECUTIVE VERDICT\n"
    + "\n".join(f"  detail line {n} of the institutional memorandum." for n in range(400))
    + "\nSECTION 12. MACHINE CONTRACT\n"
    "```json:underwriting\n"
    '{"base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 90.0, "base_probability": 0.5, '
    '"bull_probability": 0.3, "bear_probability": 0.2, "conviction_score": 10, '
    '"business_quality_moat": 3, "kelly_fraction_pct": 2.0, '
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


@pytest.fixture
def fake_ollama(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return _FakeResponse({"message": {"content": MEMO}, "done_reason": "stop",
                              "eval_count": 500, "prompt_eval_count": 100})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def _out_run_dir(out_dir, ticker="GEV"):
    dirs = list(out_dir.glob(f"{ticker}_*"))
    assert len(dirs) == 1, f"expected exactly one run dir, found {dirs}"
    return dirs[0]


def _run(tmp_path, extra_args):
    frozen = tmp_path / "frozen_pack.md"
    frozen.write_text("# DATA PACK - GEV (frozen)\n\nFixed content.\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    sys.argv[:] = [
        "consensus_valuation.py", "GEV", "--price", "100", "--samples", "1",
        "--no-early-stop", "--pack-file", str(frozen), "--out-dir", str(out_dir),
    ] + extra_args
    cv.main()
    d = _out_run_dir(out_dir)
    return json.loads((d / "consensus.json").read_text(encoding="utf-8"))


# ---- parsing --------------------------------------------------------------------------------

def test_bad_prior_base_fails_loudly(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv",
                        ["consensus_valuation.py", "GEV", "--prior-base", "not-a-number"])
    with pytest.raises(ValueError):
        cv.main()
    assert "HARD FAIL" in capsys.readouterr().out


def test_missing_prior_base_value_fails_loudly(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "GEV", "--prior-base"])
    with pytest.raises(IndexError):
        cv.main()
    assert "HARD FAIL" in capsys.readouterr().out


# ---- stamping ---------------------------------------------------------------------------------

def test_prior_base_stamped_as_none_valid_when_not_supplied(
        tmp_path, monkeypatch, fake_ollama, screener_data_stub):
    doc = _run(tmp_path, [])
    assert doc["prior_base"] == "none_valid"


def test_prior_base_stamped_with_the_supplied_value(
        tmp_path, monkeypatch, fake_ollama, screener_data_stub):
    doc = _run(tmp_path, ["--prior-base", "934.535"])
    assert doc["prior_base"] == pytest.approx(934.535)
