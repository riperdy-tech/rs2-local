"""P4.7/B2 — the adaptive 2-sample early stop also requires the bear-IV spread inside
BEAR_TOL_PCT and, when a valid prior base was supplied, the 2-sample median within 25% of it.

`early_stop_check` is a pure function (no I/O, no model, no printing) so these are unit tests
of the decision logic itself, not of consensus_valuation.main()'s subprocess/model plumbing.
"""
import pytest

from tools.audit_202608.consensus_valuation import (
    early_stop_check, BEAR_TOL_PCT, EARLY_TOL_PCT,
)


def _samples(iv_a, iv_b, bear_a=None, bear_b=None):
    return [
        {"sample": 1, "iv": iv_a, "scorecard": {"bear_iv": bear_a}},
        {"sample": 2, "iv": iv_b, "scorecard": {"bear_iv": bear_b}},
    ]


# ---- base spread alone (bear/prior absent -> those legs are inert) ------------------------

def test_stops_when_base_and_bear_spread_both_inside_bar():
    g2 = _samples(100.0, 105.0, bear_a=80.0, bear_b=82.0)
    d = early_stop_check(g2)
    assert d["stop"] is True
    assert d["bear_ok"] is True
    assert d["prior_ok"] is True   # no prior supplied -> vacuously satisfied


def test_does_not_stop_when_base_spread_exceeds_early_bar():
    # 100 -> 120 is 20%, past EARLY_TOL_PCT (15%).
    g2 = _samples(100.0, 120.0, bear_a=80.0, bear_b=82.0)
    d = early_stop_check(g2)
    assert d["sp2"] == pytest.approx(20.0)
    assert d["stop"] is False


# ---- bear-IV spread leg (P4.7 new) ---------------------------------------------------------

def test_does_not_stop_when_bear_spread_exceeds_bear_bar():
    # Base spread tight (5%), but bear IVs 50 vs 100 = 100% spread, past BEAR_TOL_PCT (40%).
    g2 = _samples(100.0, 105.0, bear_a=50.0, bear_b=100.0)
    d = early_stop_check(g2)
    assert d["sp2"] <= EARLY_TOL_PCT
    assert d["bear_sp2"] == pytest.approx(100.0)
    assert d["bear_ok"] is False
    assert d["stop"] is False


def test_stops_at_exactly_the_bear_bar_inclusive():
    # bear 100 -> 140 is exactly 40% == BEAR_TOL_PCT: the bar is inclusive (<=), matching the
    # base-spread leg's own <= EARLY_TOL_PCT.
    g2 = _samples(100.0, 105.0, bear_a=100.0, bear_b=140.0)
    d = early_stop_check(g2)
    assert d["bear_sp2"] == pytest.approx(40.0)
    assert d["bear_ok"] is True
    assert d["stop"] is True


def test_missing_bear_iv_on_either_sample_fails_closed_no_stop():
    # A missing bear_iv means the condition cannot be CONFIRMED true, so it escalates rather
    # than assuming the bar was met.
    g2 = _samples(100.0, 105.0, bear_a=80.0, bear_b=None)
    d = early_stop_check(g2)
    assert d["bear_sp2"] is None
    assert d["bear_ok"] is False
    assert d["stop"] is False


def test_missing_bear_iv_on_both_samples_fails_closed_no_stop():
    g2 = _samples(100.0, 105.0, bear_a=None, bear_b=None)
    d = early_stop_check(g2)
    assert d["bear_sp2"] is None
    assert d["bear_ok"] is False
    assert d["stop"] is False


# ---- prior-base leg (P4.7/B2 new) -----------------------------------------------------------

def test_stops_when_median_is_within_25pct_of_a_supplied_prior():
    g2 = _samples(100.0, 105.0, bear_a=80.0, bear_b=82.0)   # median 102.5
    d = early_stop_check(g2, prior_base=110.0)               # |102.5-110|/110 = 6.8%
    assert d["prior_delta_pct"] == pytest.approx(6.8, abs=0.1)
    assert d["prior_ok"] is True
    assert d["stop"] is True


def test_does_not_stop_when_median_moves_more_than_25pct_from_prior():
    g2 = _samples(100.0, 105.0, bear_a=80.0, bear_b=82.0)    # median 102.5
    d = early_stop_check(g2, prior_base=50.0)                 # |102.5-50|/50 = 105%
    assert d["prior_ok"] is False
    assert d["stop"] is False


def test_prior_bar_is_exactly_25pct_inclusive():
    # median 125, prior 100 -> exactly 25% -> inclusive.
    g2 = _samples(120.0, 130.0, bear_a=80.0, bear_b=82.0)
    d = early_stop_check(g2, prior_base=100.0)
    assert d["prior_delta_pct"] == pytest.approx(25.0)
    assert d["prior_ok"] is True
    assert d["stop"] is True


def test_no_prior_supplied_skips_the_prior_leg_entirely():
    g2 = _samples(100.0, 105.0, bear_a=80.0, bear_b=82.0)
    d = early_stop_check(g2, prior_base=None)
    assert d["prior_delta_pct"] is None
    assert d["prior_ok"] is True
    assert d["stop"] is True


def test_all_three_legs_must_agree_to_stop():
    # Base spread fine, bear spread fine, but prior moved too far -> no stop.
    g2 = _samples(100.0, 105.0, bear_a=80.0, bear_b=82.0)
    d = early_stop_check(g2, prior_base=10.0)
    assert d["sp2"] <= EARLY_TOL_PCT
    assert d["bear_ok"] is True
    assert d["prior_ok"] is False
    assert d["stop"] is False
