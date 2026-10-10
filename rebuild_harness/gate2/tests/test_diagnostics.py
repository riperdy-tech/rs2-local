"""Addenda AD R3/R8 and AE.1-AE.3: the reported diagnostics."""
import numpy as np
import pytest

from rebuild_harness.gate2 import diagnostics as dg


def world(n=80, p1_better=True, seed=0):
    rng = np.random.default_rng(seed)
    rows, outs = [], {}
    for c in range(n):
        for d in ("2025-10-31", "2025-12-31"):
            key = f"{d}_{c:010d}"
            y = rng.normal(0.05, 0.05)
            arm = lambda e: {"growth": {"p50": y + e}, "margin": {"p50": y + e}, "margin_base": 0.0}
            good, bad = rng.normal(0, 0.01), rng.normal(0, 0.08)
            rows.append({"key": key, "date": d, "cik": f"{c:010d}", "family": "operating", "decisions": [], "positions": {},
                         "muse_p1": arm(good if p1_better else bad), "code": arm(bad if p1_better else good), "muse": arm(good if p1_better else bad),
                         "persistence": arm(bad), "pop_median": arm(bad), "t4q": arm(bad)})
            outs[key] = {"quarters": {"q1": {"revenue_growth": y, "operating_margin_change": y}}}
    return rows, outs


def test_filing_skill_needs_pass1_to_beat_the_code_population_median_and_persistence():
    rows, outs = world(p1_better=True)
    for b in ("code", "pop_median", "persistence"):
        r = dg.compare(rows, outs, "muse_p1", b, "growth", draws=200)
        assert r["a_better"] is True and r["n"] == 160 and set(r["by_date"]) == {"2025-10-31", "2025-12-31"}
    rows, outs = world(p1_better=False)
    assert dg.compare(rows, outs, "muse_p1", "code", "growth", draws=200)["a_better"] is False


def test_compare_skips_missing_forecasts_and_wrong_families():
    rows, outs = world(n=5)
    rows[0]["code"]["growth"] = None
    rows[1]["family"] = "financial"
    r = dg.compare(rows, outs, "muse_p1", "code", "growth", draws=50)
    assert r["n"] == 8


def test_g4_strict_counts_toward_price_revisions_without_a_new_filing_quote():
    rows = [{"decisions": [{"proposed": True, "toward_price": True, "new_quote_from_filing": False, "accepted": False},
                           {"proposed": True, "toward_price": True, "new_quote_from_filing": True, "accepted": True},
                           {"proposed": True, "toward_price": False, "accepted": True}, {"proposed": False}]}]
    r = dg.r3c(rows)
    assert r["n_proposed"] == 3 and r["n_toward_without_new_filing_quote"] == 1 and r["share"] == pytest.approx(1 / 3) and r["passes"] is False
    assert dg.r3c([{"decisions": []}])["vacuous"] is True


def test_repeatability_reads_shifts_and_flags_multi_sampling():
    main = [{"key": "k", "positions": {"g1": {"percentile": 60, "width": "normal"}, "m": {"percentile": 40, "width": "normal"}}}]
    rep = [{"key": "k", "positions": {"g1": {"percentile": 60, "width": "normal"}, "m": {"percentile": 70, "width": "normal"}}}]
    r = dg.r8(main, rep)
    assert r["n_inputs"] == 2 and r["median_abs_shift"] == 15 and r["share_identical"] == 0.5 and r["multi_sample_required"] is True
