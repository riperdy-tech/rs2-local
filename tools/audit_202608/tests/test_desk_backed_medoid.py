import pytest
from tools.audit_202608.consensus_valuation import (
    select_medoid_scorecard,
    extract_desk_snapshot_metrics,
)
from tools.audit_202608.depth_sanity import audit


def test_desk_not_used_and_iv_not_desk_backed_flags():
    # 0 desk calls
    m0 = extract_desk_snapshot_metrics([], base_iv=100.0)
    assert m0["desk_calls"] == 0
    assert m0["desk_iv_match"] is False

    # Desk calls present, but base_iv does not match any desk IV
    calls = [
        {
            "tool": "run_financial_model",
            "result": {
                "dcf_model": {"per_share_iv": 80.0}
            }
        }
    ]
    m1 = extract_desk_snapshot_metrics(calls, base_iv=100.0)
    assert m1["desk_calls"] == 1
    assert m1["desk_iv_match"] is False


def test_select_medoid_excludes_flagged_samples_when_clean_sample_exists():
    price = 100.0
    runs = [
        {
            "sample": 1, "iv": 100.0, "plausible": True, "truncated": False,
            "flags": ["desk_not_used", "iv_not_desk_backed"],
            "scorecard": {
                "base_iv": 100.0, "bull_iv": 130.0, "bear_iv": 80.0,
                "business_quality_moat": 3.0,
                "desk_calls": 0,
                "desk_iv_match": False,
            }
        },
        {
            "sample": 2, "iv": 105.0, "plausible": True, "truncated": False,
            "flags": [],
            "scorecard": {
                "base_iv": 105.0, "bull_iv": 135.0, "bear_iv": 85.0,
                "business_quality_moat": 3.0,
                "desk_calls": 1,
                "desk_iv_match": True,
            }
        }
    ]
    # Sample 1 is exactly at median IV 102.5 / 100.0 center, but flagged desk_not_used.
    # Because Sample 2 is clean, Sample 1 is excluded and Sample 2 is selected.
    medoid, summary = select_medoid_scorecard(runs, price)
    assert summary["medoid_sample"] == 2
    assert medoid["base_iv"] == 105.0


def test_no_desk_backed_sample_means_no_basis():
    # Phase 4 (b) GPOR joint review: a sample whose base IV no desk call produced is not a basis
    # sample. The old fallback picked a medoid among hand-computed samples; now there is none, and
    # the verdict has no basis (non-actionable through the existing single/no-sample gates).
    price = 100.0
    runs = [
        {
            "sample": 1, "iv": 100.0, "plausible": True, "truncated": False,
            "flags": ["desk_not_used"],
            "scorecard": {
                "base_iv": 100.0, "bull_iv": 130.0, "bear_iv": 80.0,
                "business_quality_moat": 3.0,
                "desk_calls": 0,
                "desk_iv_match": False,
            }
        },
        {
            "sample": 2, "iv": 105.0, "plausible": True, "truncated": False,
            "flags": ["desk_not_used"],
            "scorecard": {
                "base_iv": 105.0, "bull_iv": 135.0, "bear_iv": 85.0,
                "business_quality_moat": 3.0,
                "desk_calls": 0,
                "desk_iv_match": False,
            }
        }
    ]
    medoid, summary = select_medoid_scorecard(runs, price)
    assert summary["medoid_sample"] is None and summary["n_basis"] == 0 and medoid == {}


def test_a_desk_less_sample_leaves_the_band_and_the_spread():
    # GPOR (b): s1 $409.92 desk-backed, s2 $425.00 with zero tool calls -> one basis sample
    runs = [
        {"sample": 1, "iv": 409.92, "plausible": True, "truncated": False, "flags": [],
         "scorecard": {"base_iv": 409.92, "bull_iv": 584.0, "bear_iv": 299.0, "business_quality_moat": 3.0,
                       "desk_calls": 4, "desk_iv_match": True}},
        {"sample": 2, "iv": 425.0, "plausible": True, "truncated": False,
         "flags": ["desk_not_used", "iv_not_desk_backed"],
         "scorecard": {"base_iv": 425.0, "bull_iv": 600.0, "bear_iv": 310.0, "business_quality_moat": 3.0,
                       "desk_calls": 0, "desk_iv_match": False}},
    ]
    medoid, summary = select_medoid_scorecard(runs, 156.22)
    assert summary["n_basis"] == 1 and summary["medoid_sample"] == 1 and medoid["base_iv"] == 409.92
    assert summary["spread_pct"] is None and summary["iv_band_high"] == 409.92


def test_depth_sanity_warns_on_flagged_sample(tmp_path, monkeypatch):
    import tools.audit_202608.depth_sanity as ds
    monkeypatch.setattr(ds, "CONS", tmp_path)

    run_dir = tmp_path / "TEST_20260924_000000"
    run_dir.mkdir(parents=True)
    doc = {
        "ticker": "TEST",
        "price": 100.0,
        "runs": [
            {
                "sample": 1, "iv": 100.0, "plausible": True, "truncated": False,
                "flags": ["desk_not_used", "iv_not_desk_backed"]
            },
            {
                "sample": 2, "iv": 105.0, "plausible": True, "truncated": False,
                "flags": []
            }
        ]
    }
    (run_dir / "consensus.json").write_text(__import__("json").dumps(doc), encoding="utf-8")
    (run_dir / "sample1.md").write_text("A" * 6000, encoding="utf-8")
    (run_dir / "sample2.md").write_text("B" * 6000, encoding="utf-8")

    verdict = {
        "ticker": "TEST",
        "price": 100.0,
        "direction": "undervalued",
        "iv_band_low": 100.0,
        "iv_band_high": 105.0,
        "median_iv": 102.5,
        "n_basis": 2,
        "spread_pct": 5.0,
        "size_hint": "half",
        "consensus_dir": run_dir.name,
        "run_source": "orchestrator",
        "early_stop": True,
    }

    level, lines = audit("TEST", verdict)
    assert level >= 1
    assert any("desk verification flag" in line and "desk_not_used" in line for line in lines)
