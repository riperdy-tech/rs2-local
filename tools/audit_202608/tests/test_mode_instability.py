"""Mode-instability detector.

Measured 2026-09-20. GEV's median IV moved 934.535 -> 517.745 between two runs on the SAME
`pack_revision` at the same price ($951.04), while each run's INTERNAL spread stayed tight
(24.9% and 13.2%) and `converged` was true both times. The consensus architecture scores
within-run spread, which cannot see a shift of the level itself: run 13:57 published CONVERGED
on samples {1037.88, 831.19} and run 18:40 published CONVERGED on {485.72, 549.77}. Nothing in
the depth path compared a verdict to its predecessor, so a 2-run early stop at EARLY_TOL_PCT
can certify one mode of a bistable distribution and no consumer can tell.

This detector is an ANNOTATION. It must never move `direction`, `size_hint`, or drop a sample:
the 2026-08-24 guard redesign established that a threshold which deletes a sample destroys the
very quantity used to express doubt.
"""
import json

import pytest

import depth_pipeline as dp


# ---- iv_instability: pure, no I/O ------------------------------------------------------

def test_flags_the_measured_gev_move():
    r = dp.iv_instability(517.745, 934.535)
    assert r["unstable"] is True
    assert r["delta_pct"] == pytest.approx(-44.6, abs=0.1)
    assert r["prior_iv"] == 934.535
    assert r["current_iv"] == 517.745


def test_quiet_when_the_move_is_inside_tolerance():
    r = dp.iv_instability(105.0, 100.0)
    assert r["unstable"] is False
    assert r["delta_pct"] == pytest.approx(5.0, abs=0.1)


def test_tolerance_bar_is_exclusive():
    # Exactly at the bar is not a move PAST it.
    assert dp.iv_instability(125.0, 100.0)["unstable"] is False
    assert dp.iv_instability(125.1, 100.0)["unstable"] is True


def test_flags_a_downward_move_symmetrically():
    # A collapse and a blow-off are both instability. 70/100 is -30%, past the 25% bar; the
    # exactly-at-the-bar case is pinned separately in test_tolerance_bar_is_exclusive.
    r = dp.iv_instability(70.0, 100.0)
    assert r["unstable"] is True
    assert r["delta_pct"] == pytest.approx(-30.0, abs=0.1)


def test_no_prior_is_not_instability():
    # First-ever analysis of a name: absence of a predecessor is not evidence of a move.
    assert dp.iv_instability(100.0, None) is None
    assert dp.iv_instability(None, 100.0) is None
    assert dp.iv_instability(100.0, 0.0) is None
    assert dp.iv_instability(0.0, 100.0) is None


# ---- _prior_verdict: reads a ledger, tolerates anything ---------------------------------

def _write(tmp_path, rows, name="ledger.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def test_prior_verdict_takes_the_newest_row_for_that_ticker(tmp_path):
    p = _write(tmp_path, [
        {"ticker": "INSTAB", "base_iv": 100.0, "date": "2026-01-01"},
        {"ticker": "OTHER", "base_iv": 999.0, "date": "2026-02-01"},
        {"ticker": "INSTAB", "base_iv": 190.0, "date": "2026-03-01"},
    ])
    assert dp._prior_verdict("INSTAB", (p,))["base_iv"] == 190.0


def test_prior_verdict_skips_malformed_lines_without_raising(tmp_path):
    # Includes the torn-last-line shape a partially written ledger leaves behind.
    p = tmp_path / "ledger.jsonl"
    p.write_text('{"ticker": "INSTAB", "base_iv": 100.0}\nNOT JSON AT ALL\n'
                 '{"ticker": "INSTAB", "base_iv": 150.0}\n{"ticker": "INSTAB", "base_i',
                 encoding="utf-8")
    assert dp._prior_verdict("INSTAB", (p,))["base_iv"] == 150.0


def test_prior_verdict_is_none_when_the_ticker_is_absent(tmp_path):
    p = _write(tmp_path, [{"ticker": "OTHER", "base_iv": 100.0}])
    assert dp._prior_verdict("INSTAB", (p,)) is None


def test_prior_verdict_is_none_when_no_ledger_exists(tmp_path):
    assert dp._prior_verdict("INSTAB", (tmp_path / "nope.jsonl",)) is None


def test_prior_verdict_prefers_the_newest_date_across_ledgers(tmp_path):
    # A name can sit in BOTH the book ledger and the on-demand ledger. The predecessor is the
    # newest row by date, not the first ledger that happens to mention it - taking the book row
    # when a one-shot ran last week would compare against a stale level and flag a false move.
    main = _write(tmp_path, [{"ticker": "INSTAB", "base_iv": 100.0, "date": "2026-01-01"}],
                  "main.jsonl")
    od = _write(tmp_path, [{"ticker": "INSTAB", "base_iv": 200.0, "date": "2026-05-01"}], "od.jsonl")
    assert dp._prior_verdict("INSTAB", (main, od))["base_iv"] == 200.0


def test_prior_verdict_ignores_an_older_row_in_a_later_ledger(tmp_path):
    main = _write(tmp_path, [{"ticker": "INSTAB", "base_iv": 100.0, "date": "2026-06-01"}],
                  "main.jsonl")
    od = _write(tmp_path, [{"ticker": "INSTAB", "base_iv": 200.0, "date": "2026-05-01"}], "od.jsonl")
    assert dp._prior_verdict("INSTAB", (main, od))["base_iv"] == 100.0


def test_prior_verdict_never_raises_on_an_unreadable_path(tmp_path):
    # A directory in place of a file, and a path that does not exist.
    assert dp._prior_verdict("INSTAB", (tmp_path,)) is None
    assert dp._prior_verdict("INSTAB", (tmp_path / "absent.jsonl",)) is None


# ---- band_verdict integration ----------------------------------------------------------

def _doc(iv, price=100.0):
    return {
        "ticker": "INSTAB", "price": price, "samples_run": 2, "converged": True,
        "spread_pct": 2.0, "median_iv": iv, "early_stop": True,
        "runs": [{"sample": 1, "iv": iv, "plausible": True, "truncated": False},
                 {"sample": 2, "iv": iv, "plausible": True, "truncated": False}],
        "scorecard": {"base_iv": iv},
    }


def test_band_verdict_flags_instability(monkeypatch):
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: {"ticker": t, "base_iv": 190.0})
    v = dp.band_verdict(_doc(100.0))
    assert v["instability"]["unstable"] is True
    assert v["instability"]["prior_iv"] == 190.0
    assert "MODE_INSTABILITY" in v["flags"]
    assert "instability" in (v.get("reason") or "").lower()


def test_band_verdict_is_silent_when_the_level_held(monkeypatch):
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: {"ticker": t, "base_iv": 101.0})
    v = dp.band_verdict(_doc(100.0))
    assert v["instability"]["unstable"] is False
    assert "MODE_INSTABILITY" not in (v.get("flags") or [])


def test_band_verdict_direction_and_size_are_unaffected_by_a_prior(monkeypatch):
    # The detector ANNOTATES. If a prior exists, nothing but the flags/reason may change.
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: None)
    first = dp.band_verdict(_doc(100.0))
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: {"ticker": "INSTAB", "base_iv": 190.0})
    moved = dp.band_verdict(_doc(100.0))
    assert first["instability"] is None
    assert moved["direction"] == first["direction"]
    assert moved["size_hint"] == first["size_hint"]
    assert moved["kelly_fraction_pct"] == first["kelly_fraction_pct"]


def test_band_verdict_tolerates_a_legacy_prior_row(monkeypatch):
    # A previous code version published no `base_iv`; contract_base falls back to median_iv.
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: {"ticker": "INSTAB", "median_iv": 190.0})
    v = dp.band_verdict(_doc(100.0))
    assert v["instability"]["prior_iv"] == 190.0
    assert v["instability"]["unstable"] is True


def test_band_verdict_compares_like_for_like_from_a_ledger_shaped_prior(monkeypatch):
    # A LEDGER ROW IS A VERDICT, not a scorecard: its contract base is nested under `scorecard`,
    # and its top-level `median_iv` is the cross-sample DISPERSION statistic. Measured against
    # the real GEV row (2026-09-20: top-level base_iv absent, median_iv 517.745, scorecard
    # base_iv 549.77) reading the top level made the detector compare this run's BASE against
    # the prior's MEDIAN - two different quantities - and report 0.0% on a run that had in fact
    # moved 44.6%. Same IV as the prior base must therefore read as NO move.
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: {
        "ticker": "INSTAB", "median_iv": 190.0, "date": "2026-09-20",
        "scorecard": {"base_iv": 100.0},
    })
    v = dp.band_verdict(_doc(100.0))
    assert v["instability"]["prior_iv"] == 100.0
    assert v["instability"]["unstable"] is False


def test_band_verdict_uses_the_scorecard_base_when_it_differs_from_the_median(monkeypatch):
    # GEV's real shape: base 549.77, median 517.745. A rerun at the prior's MEDIAN is a -5.8%
    # move against the prior BASE, which is inside tolerance - it is only "no move" against the
    # base, and it is a 0.0% move against the median, so the two readings must not be confused.
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: {
        "ticker": "INSTAB", "median_iv": 517.745,
        "scorecard": {"base_iv": 549.77},
    })
    v = dp.band_verdict(_doc(517.745))
    assert v["instability"]["prior_iv"] == 549.77
    assert v["instability"]["delta_pct"] == pytest.approx(-5.8, abs=0.1)
    assert v["instability"]["unstable"] is False


def test_band_verdict_tolerates_an_empty_prior_row(monkeypatch):
    # A row with neither base_iv nor median_iv carries no level to compare.
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: {"ticker": "INSTAB"})
    v = dp.band_verdict(_doc(100.0))
    assert v["instability"] is None
    assert "MODE_INSTABILITY" not in (v.get("flags") or [])
