#!/usr/bin/env python3
"""price_now.py — Live quote capture via yfinance at verdict time (P1.5).

Refuses quotes older than 4 calendar days (weekend/holiday-aware staleness refusal).
Falls back from 5-day daily close history to fast_info.last_price with asof = now.
Returns None on any network failure or unparseable quote.
"""
import math
from datetime import datetime, timezone
import yfinance as yf

MAX_STALENESS_DAYS = 4


def quote(ticker: str, now_dt: datetime | None = None) -> dict | None:
    """Fetch live quote for ticker.
    Returns: {'price': float, 'asof': str, 'source': str} or None.
    """
    if not ticker:
        return None
    t = str(ticker).strip().upper()
    now = now_dt if now_dt is not None else datetime.now(timezone.utc)
    now_date = now.date()

    try:
        tk = yf.Ticker(t)
    except Exception:
        return None

    # 1. Try last daily close via history(period="5d")
    try:
        hist = tk.history(period="5d")
        if hist is not None and not hist.empty and "Close" in hist.columns:
            valid = hist.dropna(subset=["Close"])
            if not valid.empty:
                last_row = valid.iloc[-1]
                last_close = float(last_row["Close"])
                last_idx = valid.index[-1]
                dt = last_idx.to_pydatetime() if hasattr(last_idx, "to_pydatetime") else last_idx
                close_date = dt.date() if hasattr(dt, "date") else now_date
                age_days = (now_date - close_date).days
                if age_days < 0:
                    age_days = 0
                if age_days > MAX_STALENESS_DAYS:
                    return None  # staleness refusal
                if not math.isnan(last_close) and last_close > 0:
                    return {
                        "price": round(last_close, 4),
                        "asof": close_date.isoformat(),
                        "source": "yfinance",
                    }
    except Exception:
        pass

    # 2. Fall back to fast_info.last_price with asof = now
    try:
        fi = getattr(tk, "fast_info", None)
        if fi is not None:
            last_price = getattr(fi, "last_price", None)
            if last_price is not None:
                px = float(last_price)
                if not math.isnan(px) and px > 0:
                    return {
                        "price": round(px, 4),
                        "asof": now_date.isoformat(),
                        "source": "yfinance_fast_info",
                    }
    except Exception:
        pass

    return None
