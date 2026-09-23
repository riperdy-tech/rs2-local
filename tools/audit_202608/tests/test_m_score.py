"""P4.3 — `m` = (median_iv - price) / ((iv_band_high - iv_band_low) / 2).

The price's position within the plausible-IV band, in half-widths. Pure function
(`depth_pipeline.compute_m`) plus its wiring into `band_verdict`. None when the band half-width
is 0 (a single converged point) or any input is missing — never a fabricated 0.0.
"""
import pytest

import depth_pipeline as dp
from depth_pipeline import band_verdict, compute_m


# ---- compute_m: pure, no I/O -------------------------------------------------------------

def test_m_zero_when_price_at_median():
    assert compute_m(median_iv=100.0, price=100.0, iv_band_low=80.0, iv_band_high=120.0) == 0.0


def test_m_positive_when_price_below_median_undervalued_direction():
    # median 100, band [80, 120] -> half-width 20. Price 80 (band low) -> m = (100-80)/20 = 1.0
    assert compute_m(100.0, 80.0, 80.0, 120.0) == pytest.approx(1.0)


def test_m_negative_when_price_above_median():
    # Price 120 (band high) -> m = (100-120)/20 = -1.0
    assert compute_m(100.0, 120.0, 80.0, 120.0) == pytest.approx(-1.0)


def test_m_none_when_half_width_is_zero():
    # A single converged point: iv_band_low == iv_band_high -> half-width 0, undefined, not 0.
    assert compute_m(100.0, 90.0, 100.0, 100.0) is None


def test_m_none_on_missing_inputs():
    assert compute_m(None, 100.0, 80.0, 120.0) is None
    assert compute_m(100.0, None, 80.0, 120.0) is None
    assert compute_m(100.0, 100.0, None, 120.0) is None
    assert compute_m(100.0, 100.0, 80.0, None) is None


def test_m_handles_zero_price_as_a_value_not_an_absence():
    # 0.0 is a value, never `or`-defaulted; price=0.0 must still compute, not be treated as absent.
    assert compute_m(100.0, 0.0, 80.0, 120.0) == pytest.approx(5.0)


# ---- band_verdict wiring ------------------------------------------------------------------

def _doc(price, ivs, median_iv=None):
    runs = [{"sample": i + 1, "iv": iv, "plausible": True, "truncated": False}
            for i, iv in enumerate(ivs)]
    return {"ticker": "MSCR", "price": price, "samples_run": len(ivs), "converged": True,
            "spread_pct": 2.0, "median_iv": median_iv if median_iv is not None else ivs[len(ivs) // 2],
            "runs": runs, "scorecard": {"base_iv": ivs[0]}}


def test_band_verdict_stamps_m(monkeypatch):
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: None)
    v = band_verdict(_doc(100.0, [112.0, 115.0], median_iv=113.5))
    assert v["m"] == pytest.approx((113.5 - 100.0) / ((115.0 - 112.0) / 2))


def test_band_verdict_m_is_none_on_not_usable():
    v = band_verdict({"ticker": "MSCR", "price": 100.0, "runs": []})
    assert v["direction"] == "NOT_USABLE"
    assert v["m"] is None


def test_band_verdict_m_is_none_for_single_sample(monkeypatch):
    monkeypatch.setattr(dp, "_prior_verdict", lambda t, l: None)
    v = band_verdict(_doc(100.0, [110.0], median_iv=110.0))
    # A single plausible sample: iv_band_low == iv_band_high -> half-width 0 -> m is None.
    assert v["iv_band_low"] == v["iv_band_high"]
    assert v["m"] is None
