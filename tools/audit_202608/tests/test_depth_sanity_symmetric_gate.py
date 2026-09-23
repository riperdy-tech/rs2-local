"""depth_sanity.py — P1.8: the non-convergence gate audit is symmetric (FAILs an overvalued call
under high dispersion exactly like an undervalued one), and WARNs when run_source is missing.
"""
from tools.audit_202608.depth_sanity import audit


def _verdict(direction, spread_pct, **over):
    v = {"ticker": "SYM", "price": 100.0, "direction": direction,
         "iv_band_low": 60.0, "iv_band_high": 140.0, "n_basis": 2,
         "spread_pct": spread_pct, "run_source": "orchestrator"}
    v.update(over)
    return v


# ---- symmetric FAIL on high dispersion ------------------------------------------------------

def test_fails_undervalued_call_under_high_dispersion():
    level, lines = audit("SYM", _verdict("undervalued", 158.6))
    assert level == 2
    assert any("dispersion" in l.lower() for l in lines)


def test_fails_overvalued_call_under_high_dispersion():
    """Before P1.8 only 'undervalued' was checked — an overvalued call at the same spread
    published clean. The gate exists because the model's draws disagree too much to commit
    capital either direction, so this must fail exactly like the undervalued case."""
    level, lines = audit("SYM", _verdict("overvalued", 158.6))
    assert level == 2
    assert any("dispersion" in l.lower() for l in lines)


def test_fails_overvalued_call_carrying_the_quarantine_flag():
    v = _verdict("overvalued", 30.0, flags=["HIGH_DISPERSION_QUARANTINE"])
    level, lines = audit("SYM", v)
    assert level == 2
    assert any("HIGH_DISPERSION_QUARANTINE" in l for l in lines)


def test_hold_under_high_dispersion_does_not_fail_the_dispersion_check():
    """'hold' commits no capital either direction — the gate has nothing to catch here."""
    level, lines = audit("SYM", _verdict("hold", 158.6))
    assert not any("violates non-convergence gate" in l for l in lines)


# ---- WARN when run_source is missing (P1.2 rows only) -----------------------------------------

def test_warns_when_run_source_missing():
    v = _verdict("hold", 5.0)
    del v["run_source"]
    level, lines = audit("SYM", v)
    assert level >= 1
    assert any("run_source" in l for l in lines)


def test_no_run_source_warning_when_present():
    v = _verdict("hold", 5.0)
    level, lines = audit("SYM", v)
    assert not any("run_source" in l for l in lines)
