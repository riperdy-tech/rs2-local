"""tests/test_price_override.py — C7 (Phase 1 approval review, §6).

consensus_valuation.main()'s --price parsing used to swallow a bad value (IndexError/ValueError)
and silently fall back to the vendor quote (fin.get("Price")). depth_pipeline passes its OWN
live price_now.quote() as --price specifically to OVERRIDE the vendor number, so a silent
fallback would value the ticker against a price nobody chose. It must fail loudly instead.

The bad --price is parsed and raises before any research/LLM work starts in main() — before
cap.build_pack() and every subprocess/model call — so calling main() directly here never
touches the network, a model, or cache/.
"""
import sys
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import consensus_valuation as cv


def test_bad_price_argument_fails_loudly(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "FLXS", "--price", "not-a-number"])
    with pytest.raises(ValueError):
        cv.main()
    assert "HARD FAIL" in capsys.readouterr().out


def test_missing_price_value_fails_loudly(monkeypatch, capsys):
    """--price with no value following it (IndexError) must also fail loudly, not fall back."""
    monkeypatch.setattr(sys, "argv", ["consensus_valuation.py", "FLXS", "--price"])
    with pytest.raises(IndexError):
        cv.main()
    assert "HARD FAIL" in capsys.readouterr().out


def test_good_price_argument_is_accepted(monkeypatch, tmp_path):
    """A parseable --price is used as-is — confirms the happy path is untouched by the fix.
    Stops main() right after parsing (no research/LLM work) by monkeypatching build_pack to
    raise, so this stays hermetic."""
    monkeypatch.setattr(sys, "argv",
                        ["consensus_valuation.py", "FLXS", "--price", "123.45", "--price-asof",
                         "2026-09-23"])
    seen = {}

    def fake_build_pack(t, price_override=None):
        seen["price_override"] = price_override
        raise RuntimeError("stopped before any LLM/network work")

    monkeypatch.setattr(cv.cap, "build_pack", fake_build_pack)
    with pytest.raises(RuntimeError, match="stopped before any LLM/network work"):
        cv.main()
    assert seen["price_override"] == {"price": 123.45, "asof": "2026-09-23"}
