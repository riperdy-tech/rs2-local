"""P4.7/B2 — depth_pipeline.main() passes consensus_valuation `--prior-base` (via
run_consensus's `prior_base` kwarg) ONLY when the prior ledger row is depth_gates.analyst_valid.
No prior, or a prior that is not analyst_valid, must result in prior_base=None — never a guess.

Runs depth_pipeline.main() end to end, exactly like
tests/test_depth_pipeline_routing.py::test_main_manual_invocation_only_grows_test_ledger, with
every subprocess/GPU-touching seam stubbed. What's checked here is NEW: the value passed into
run_consensus's `prior_base` argument.
"""
import json
import sys
from pathlib import Path

import pytest

# depth_pipeline re-wraps sys.stdout at import (utf-8 console on Windows); keep the wrapper alive
# under pytest capture, same dance as test_depth_pipeline_routing.py.
_ORIG_STDOUT = sys.stdout
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import depth_pipeline as dp  # noqa: E402
import depth_gates  # noqa: E402
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


def _drive_main(tmp_path, monkeypatch, prior_row):
    """Runs dp.main() for ticker PRIOR with a single prior ledger row (or None), and returns the
    prior_base value run_consensus was actually called with."""
    monkeypatch.delenv("RS2_RUN_SOURCE", raising=False)
    monkeypatch.delenv("RS2_SCREENER_DATA_COMMIT", raising=False)
    monkeypatch.setattr(sys, "argv", ["depth_pipeline.py", "PRIOR"])
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path / "research"))
    monkeypatch.setattr(dp.screener_refresh, "refresh_screener_data", lambda: (True, "deadbeef"))

    ledger = tmp_path / "depth_ledger.jsonl"
    od_ledger = tmp_path / "depth_ondemand_ledger.jsonl"
    test_ledger = tmp_path / "depth_test_ledger.jsonl"
    if prior_row is not None:
        ledger.write_text(json.dumps(prior_row) + "\n", encoding="utf-8")
    monkeypatch.setattr(dp, "LEDGER", ledger)
    monkeypatch.setattr(dp, "TEST_LEDGER", test_ledger)
    monkeypatch.setattr(dp, "OD_LEDGER", od_ledger)

    quote = {"price": 100.0, "asof": "2026-09-23", "source": "yfinance"}
    monkeypatch.setattr(dp.price_now, "quote", lambda t: quote)
    monkeypatch.setattr(dp, "run_research", lambda t: None)   # -> consensus_no_research branch

    seen = {}
    consensus_dir = tmp_path / "PRIOR_20260923_120000"
    consensus_dir.mkdir()
    doc = {"ticker": "PRIOR", "price": 100.0}

    def fake_run_consensus(t, samples=None, price_quote=None, no_research=False, prior_base=None):
        seen["prior_base"] = prior_base
        return consensus_dir, doc

    monkeypatch.setattr(dp, "run_consensus", fake_run_consensus)
    monkeypatch.setattr(dp, "band_verdict", lambda doc: {
        "ticker": "PRIOR", "price": 100.0, "date": "2026-09-23", "direction": "hold"})
    monkeypatch.setattr(dp, "audit_verdict", lambda t, ledger: None)
    monkeypatch.setattr(dp.ops, "notify_telegram", lambda msg: None)

    dp.main()
    return seen["prior_base"]


def test_no_prior_row_means_prior_base_is_none(tmp_path, monkeypatch):
    assert _drive_main(tmp_path, monkeypatch, prior_row=None) is None


def test_prior_row_not_analyst_valid_means_prior_base_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(depth_gates, "FIRST_VALID_PACK_REVISION", None)  # nothing is valid yet
    prior_row = {"ticker": "PRIOR", "date": "2026-09-01", "pack_revision": 5,
                "gate_version": depth_gates.GATE_VERSION, "scorecard": {"base_iv": 934.535}}
    assert _drive_main(tmp_path, monkeypatch, prior_row) is None


def test_analyst_valid_prior_supplies_its_contract_base(tmp_path, monkeypatch):
    monkeypatch.setattr(depth_gates, "FIRST_VALID_PACK_REVISION", 5)
    prior_row = {"ticker": "PRIOR", "date": "2026-09-01", "pack_revision": 5,
                "gate_version": depth_gates.GATE_VERSION, "scorecard": {"base_iv": 934.535}}
    assert _drive_main(tmp_path, monkeypatch, prior_row) == pytest.approx(934.535)


def test_analyst_valid_prior_below_the_ruled_floor_supplies_none(tmp_path, monkeypatch):
    monkeypatch.setattr(depth_gates, "FIRST_VALID_PACK_REVISION", 5)
    prior_row = {"ticker": "PRIOR", "date": "2026-09-01", "pack_revision": 4,   # < floor
                "gate_version": depth_gates.GATE_VERSION, "scorecard": {"base_iv": 934.535}}
    assert _drive_main(tmp_path, monkeypatch, prior_row) is None


def test_analyst_valid_prior_falls_back_to_top_level_median_iv(tmp_path, monkeypatch):
    # A row with no scorecard at all: contract_base falls back to the legacy top-level fields.
    monkeypatch.setattr(depth_gates, "FIRST_VALID_PACK_REVISION", 5)
    prior_row = {"ticker": "PRIOR", "date": "2026-09-01", "pack_revision": 5,
                "gate_version": depth_gates.GATE_VERSION, "median_iv": 517.745}
    assert _drive_main(tmp_path, monkeypatch, prior_row) == pytest.approx(517.745)
