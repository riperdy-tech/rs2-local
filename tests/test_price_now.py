"""tests/test_price_now.py — P1.5 Live price at verdict time.

Verifies:
1. price_now.quote(ticker):
   - Fresh close (<= 4 calendar days) -> used
   - Stale close (> 4 calendar days) -> refused (None)
   - Fallback to fast_info when history empty
   - Network failure -> None
2. capability_test.build_pack(t, price_override=...):
   - Prints live quote beside vendor quote and date
   - Defaults to vendor quote when override is None
3. depth_pipeline:
   - Hard fails with exit 8 when live price is unavailable
   - Verdict gets price, price_asof, price_source from quote
4. orchestrate_depth rc map:
   - 8 maps to "price_unavailable"
5. depth_triggers._price_now:
   - Uses price_now.quote() with vendor quote as recorded fallback
"""
import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))

_ORIG_STDOUT = sys.stdout
import orchestrate_depth as od
import depth_pipeline as dp
import depth_triggers as dt
import price_now
import capability_test as cap
_WRAPPER_KEEPALIVE = sys.stdout
sys.stdout = _ORIG_STDOUT


class DummyFastInfo:
    def __init__(self, last_price=105.0):
        self.last_price = last_price


def _install_fake_yfinance(monkeypatch, ticker_factory):
    """B5 (Phase 1 approval review): price_now.quote() now does `import yfinance as yf`
    INSIDE the function (lazy — so importing price_now never needs yfinance installed, which
    the cloud continuity runner does not have). There is no more module-level `price_now.yf`
    attribute to monkeypatch, so install the fake Ticker factory into sys.modules instead; the
    lazy import picks up this module without a real yfinance import."""
    fake = types.ModuleType("yfinance")
    fake.Ticker = ticker_factory
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def test_quote_fresh_history(monkeypatch):
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    dates = pd.to_datetime(["2026-09-21", "2026-09-22"])
    hist = pd.DataFrame({"Close": [100.0, 102.5]}, index=dates)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    _install_fake_yfinance(monkeypatch, lambda t: mock_ticker)

    q = price_now.quote("AAPL", now_dt=now)
    assert q is not None
    assert q["price"] == 102.5
    assert q["asof"] == "2026-09-22"
    assert q["source"] == "yfinance"


def test_quote_stale_history_refused(monkeypatch):
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    # 5 calendar days old (> 4 days max staleness)
    dates = pd.to_datetime(["2026-09-17", "2026-09-18"])
    hist = pd.DataFrame({"Close": [100.0, 102.5]}, index=dates)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    mock_ticker.fast_info = None
    _install_fake_yfinance(monkeypatch, lambda t: mock_ticker)

    q = price_now.quote("AAPL", now_dt=now)
    assert q is None


def test_quote_fallback_to_fast_info(monkeypatch):
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_ticker.fast_info = DummyFastInfo(last_price=155.75)
    _install_fake_yfinance(monkeypatch, lambda t: mock_ticker)

    q = price_now.quote("AAPL", now_dt=now)
    assert q is not None
    assert q["price"] == 155.75
    assert q["asof"] == "2026-09-23"
    assert q["source"] == "yfinance_fast_info"


def test_quote_newest_bar_nan_falls_back_to_fast_info(monkeypatch):
    """B4/C9 (Phase 1 approval review): today's shape — yfinance's newest bar (09-22) is NaN
    while an older bar (09-21) has a valid close. The old code dropped the NaN row and silently
    reported the 09-21 close as current. It must now refuse that stale close and fall back to
    fast_info, stamped with the NEWEST row's own session date (09-22), not `now` (09-23) and
    not the older valid close's date."""
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    dates = pd.to_datetime(["2026-09-21", "2026-09-22"])
    hist = pd.DataFrame({"Close": [100.0, float("nan")]}, index=dates)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    mock_ticker.fast_info = DummyFastInfo(last_price=104.16)
    _install_fake_yfinance(monkeypatch, lambda t: mock_ticker)

    q = price_now.quote("AAPL", now_dt=now)
    assert q is not None
    assert q["price"] == 104.16
    assert q["source"] == "yfinance_fast_info"
    assert q["asof"] == "2026-09-22"          # the NaN bar's own session date
    assert q["asof"] != "2026-09-21"          # never the older valid close's date
    assert q["asof_basis"] == "fast_info_unverified"


def test_quote_newest_bar_nan_refuses_without_fast_info(monkeypatch):
    """Same NaN-newest-bar shape, but no fast_info available: refuse rather than fall back to
    the stale 09-21 close."""
    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    dates = pd.to_datetime(["2026-09-21", "2026-09-22"])
    hist = pd.DataFrame({"Close": [100.0, float("nan")]}, index=dates)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    mock_ticker.fast_info = None
    _install_fake_yfinance(monkeypatch, lambda t: mock_ticker)

    assert price_now.quote("AAPL", now_dt=now) is None


def test_quote_network_failure_returns_none(monkeypatch):
    def _raise(t):
        raise ConnectionError("no network")

    _install_fake_yfinance(monkeypatch, _raise)
    assert price_now.quote("AAPL") is None


def test_build_pack_prints_live_quote_beside_vendor():
    # Calling build_pack with price_override
    pack = cap.build_pack("GEV", price_override={"price": 285.50, "asof": "2026-09-23"})
    assert "- Price: $285.5 [live quote, as of 2026-09-23]" in pack
    assert "[vendor quote:" in pack

    # Calling build_pack without price_override uses vendor quote only
    pack_default = cap.build_pack("GEV")
    assert "[live quote" not in pack_default
    assert "- Price: $" in pack_default


def test_depth_triggers_price_now_uses_quote(monkeypatch):
    monkeypatch.setattr(price_now, "quote", lambda t: {"price": 120.0, "asof": "2026-09-23", "source": "yfinance"})
    px, src = dt._price_now("AAPL")
    assert px == 120.0
    assert src == "yfinance"


def test_depth_triggers_price_now_fallback_to_vendor(monkeypatch):
    monkeypatch.setattr(price_now, "quote", lambda t: None)
    px, src = dt._price_now("AAPL")
    assert px is not None
    assert src == "vendor_quote"


def test_depth_triggers_records_source_in_detail(monkeypatch):
    monkeypatch.setattr(price_now, "quote", lambda t: {"price": 150.0, "asof": "2026-09-23", "source": "yfinance"})
    verdict = {"price": 100.0, "date": "2026-09-10"}
    trigs = dt.triggers_for("AAPL", verdict)
    move_trigs = [detail for kind, detail in trigs if kind == "move"]
    assert len(move_trigs) == 1
    assert "[yfinance]" in move_trigs[0]
    assert "$100.0 -> $150.0" in move_trigs[0]


def test_orchestrator_rc_map_has_price_unavailable(monkeypatch):
    # In orchestrate_depth.run_one, exit code 8 maps to price_unavailable
    # We can test the rc mapping directly
    mock_proc = MagicMock()
    mock_proc.wait.return_value = 8
    monkeypatch.setattr(od.subprocess, "Popen", lambda *args, **kw: mock_proc)
    ok, why = od.run_one("AAPL")
    assert not ok
    assert why == "price_unavailable"


def test_depth_pipeline_main_exits_8_on_none_price(monkeypatch, capsys):
    monkeypatch.setattr(price_now, "quote", lambda t: None)
    monkeypatch.setattr(sys, "argv", ["depth_pipeline.py", "AAPL"])

    with pytest.raises(SystemExit) as exc:
        dp.main()
    assert exc.value.code == 8
    captured = capsys.readouterr()
    assert "::HARD FAIL:: live price unavailable" in captured.out


def test_stamp_and_route_records_live_price_fields(tmp_path, monkeypatch):
    monkeypatch.setitem(dp.CONFIG, "out_research_dir", str(tmp_path))
    v = {"ticker": "AAPL", "price": 100.0, "date": "2026-09-23", "direction": "hold"}
    quote = {"price": 115.5, "asof": "2026-09-23", "source": "yfinance"}
    dp.stamp_and_route(v, "AAPL", "orchestrator", quote=quote)
    assert v["price"] == 115.5
    assert v["price_asof"] == "2026-09-23"
    assert v["price_source"] == "yfinance"
    assert "price_asof_reason" not in v
