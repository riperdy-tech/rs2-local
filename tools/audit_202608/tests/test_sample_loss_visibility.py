"""A sample that died must not look like a sample that was never needed.

THE DEFECT (found by fresh-context review of d36b9dd). `consensus_valuation` recorded
`samples_run = len(runs)` — the RECORDED count — and derived
`early_stop = adaptive and len(runs) == 2 and len(good) == 2`. That cannot tell apart:

    (a) adaptive loop stopped at n=2 because the pair agreed inside EARLY_TOL_PCT, and
    (b) the loop ran all 3 times and one sample raised before recording anything.

Both leave `len(runs) == 2`. So a LOST sample was published as a legitimate early stop, judged
against the tighter early bar (15% instead of 25%), given `size_hint: "full"`, and audited clean.
`depth_sanity` compounded it: `intended = doc.get("samples_run") or 3` makes `len(runs) <
intended` false by construction, so the level-2 FAIL written for exactly this case —
"EXPE published on ONE sample and the audit reported only the point band" — could never fire.

The fix separates three numbers that were being conflated:
  * `samples_intended`  — what the mode planned (always 3 in adaptive mode)
  * `samples_attempted` — iterations the loop actually entered
  * `samples_run`       — samples that produced a record
Loss is `samples_run < samples_attempted`. Comparing against `samples_intended` instead would
flag every legitimate early stop as a loss, which is the trap the first attempt fell into.
"""
import json

import pytest

from depth_pipeline import band_verdict
from tools.audit_202608.consensus_valuation import run_progress
import tools.audit_202608.depth_sanity as ds


# ---- the derivation -------------------------------------------------------------------------

def test_early_stop_comes_from_the_loop_not_from_the_recorded_count():
    """The whole defect in one assertion. 3 iterations entered, 2 recorded, no break -> loss."""
    p = run_progress(n_max=3, attempted=3, recorded=2, adaptive=True, broke_early=False)
    assert p["early_stop"] is False, "a lost sample must not be published as an early stop"
    assert p["samples_lost"] == 1


def test_a_real_early_stop_reports_no_loss():
    """2 entered, 2 recorded, loop broke because the pair agreed -> a legitimate early stop."""
    p = run_progress(n_max=3, attempted=2, recorded=2, adaptive=True, broke_early=True)
    assert p["early_stop"] is True
    assert p["samples_lost"] == 0
    assert p["samples_intended"] == 3, "the plan is still 3; only 2 were attempted"


def test_fixed_n_never_reports_an_early_stop():
    p = run_progress(n_max=3, attempted=3, recorded=3, adaptive=False, broke_early=False)
    assert p["early_stop"] is False
    assert p["samples_lost"] == 0


def test_progress_carries_every_field_the_consumers_read():
    p = run_progress(3, 3, 2, True, False)
    for field in ("samples_intended", "samples_attempted", "samples_run", "samples_lost",
                  "early_stop"):
        assert field in p, f"{field} missing - a consumer reads it by name"


# ---- consumer: the audit's level-2 FAIL ------------------------------------------------------

def _lost_sample_doc():
    """A 3-sample run in which sample 3 raised: 2 recorded, 3 attempted, no early stop."""
    return {
        "ticker": "LOST", "price": 100.0, "samples_intended": 3, "samples_attempted": 3,
        "samples_run": 2, "samples_lost": 1, "early_stop": False,
        "converged": True, "spread_pct": 8.0, "tolerance_pct": 25.0, "median_iv": 108.0,
        "runs": [
            {"sample": 1, "iv": 104.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 112.0, "plausible": True, "truncated": False},
        ],
    }


def _write_consensus(tmp_path, monkeypatch, doc):
    monkeypatch.setattr(ds, "CONS", tmp_path)
    (tmp_path / "consensus.json").write_text(json.dumps(doc), encoding="utf-8")


def _verdict():
    # "undervalued" is the coherent direction for base $108 > price $100; "hold" makes the audit
    # fail for an unrelated reason and would mask what these tests are measuring.
    return {"ticker": "LOST", "price": 100.0, "direction": "undervalued", "size_hint": "half",
            "iv_band_low": 104.0, "iv_band_high": 112.0, "n_basis": 2, "spread_pct": 8.0,
            "scorecard": {"median_iv": 108.0}}


def test_audit_fails_when_a_sample_was_lost(tmp_path, monkeypatch):
    _write_consensus(tmp_path, monkeypatch, _lost_sample_doc())
    level, lines = ds.audit("LOST", _verdict())
    assert level == 2, f"expected FAIL, got {level}:\n" + "\n".join(lines)
    assert any("produced ANY result" in l for l in lines), lines


def test_audit_does_not_cry_wolf_on_a_legitimate_early_stop(tmp_path, monkeypatch):
    """The control. If the fix flags real early stops too, it is worse than the bug."""
    doc = _lost_sample_doc()
    doc.update({"samples_attempted": 2, "samples_run": 2, "samples_lost": 0, "early_stop": True})
    _write_consensus(tmp_path, monkeypatch, doc)
    level, lines = ds.audit("LOST", _verdict())
    assert not any("produced ANY result" in l for l in lines), (
        "a real 2-sample early stop must not be reported as sample loss:\n" + "\n".join(lines))
    assert level < 2, lines


# ---- consumer: the pipeline's sizing penalty -------------------------------------------------

def test_size_is_capped_when_a_sample_was_lost():
    """Identical to the GTE shape that already passes, except the recorded count is honest.

    Before the fix this doc published `size_hint: "full"`, because the penalty was keyed on
    `samples_run == 3` and a lost sample makes `samples_run` 2 - the rule could not see the loss
    it exists to punish.
    """
    doc = {
        "ticker": "GTE", "price": 10.47, "samples_intended": 3, "samples_attempted": 3,
        "samples_run": 2, "samples_lost": 1, "early_stop": False,
        "converged": True, "spread_pct": 11.8, "median_iv": 13.2, "tolerance_pct": 25.0,
        "runs": [
            {"sample": 1, "iv": 12.49, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 13.96, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 13.2},
    }
    v = band_verdict(doc)
    assert v["size_hint"] != "full", f"lost sample must cap size, got {v['size_hint']!r}"
    assert "sample lost" in v.get("reason", "").lower()


def test_a_legitimate_early_stop_may_still_be_sized_full():
    """The control for the penalty: 2 attempted, 2 recorded, a real break -> no penalty."""
    doc = {
        "ticker": "CMPD", "price": 102.0, "samples_intended": 3, "samples_attempted": 2,
        "samples_run": 2, "samples_lost": 0, "early_stop": True,
        "converged": True, "spread_pct": 2.0, "median_iv": 99.0, "tolerance_pct": 25.0,
        "runs": [
            {"sample": 1, "iv": 98.0, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 100.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 99.0},
    }
    v = band_verdict(doc)
    assert "sample lost" not in v.get("reason", "").lower(), v.get("reason")
