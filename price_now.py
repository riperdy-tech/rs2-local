#!/usr/bin/env python3
"""price_now.py — Live quote capture via yfinance at verdict time (P1.5).

Refuses quotes older than 4 calendar days (weekend/holiday-aware staleness refusal).
Falls back from 5-day daily close history to fast_info.last_price when the newest history row
is unusable (see B4 below), stamped with that row's own session date; falls back to fast_info
with asof = now only when history gave no date at all. Returns None on any network failure or
unparseable quote.
"""
import math
from datetime import datetime, timezone
import yfinance as yf

MAX_STALENESS_DAYS = 4


def quote(ticker: str, now_dt: datetime | None = None) -> dict | None:
    """Fetch live quote for ticker.
    Returns: {'price': float, 'asof': str, 'source': str, 'asof_basis'?: str} or None.
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

    # 1. Try last daily close via history(period="5d"). The newest row can carry a NaN Close
    # (today's session, not settled yet) while still being the newest DATE yfinance lists.
    # B4 (Phase 1 approval review): the old code dropped NaN rows before looking at dates, so a
    # NaN newest bar silently fell through to the next-newest VALID close and reported it as
    # today's price — proof that a newer session exists (the NaN row itself) was discarded along
    # with it. Measured on 2026-09-23: yfinance's 09-22 bar was NaN for FLXS/GEV/AMD/ARX/ESEA, and
    # the old code used the 09-21 close instead, -3.6% to +2.8% off the true 09-22 close.
    # Never do that: if the newest row is NaN, or dated later than the newest row that DOES have
    # a usable close, refuse the stale close and fall through to fast_info instead, stamped with
    # the newest row's own session date (not "now").
    newest_session_date = None
    try:
        hist = tk.history(period="5d")
        if hist is not None and not hist.empty and "Close" in hist.columns:
            newest_idx = hist.index[-1]
            newest_dt = newest_idx.to_pydatetime() if hasattr(newest_idx, "to_pydatetime") else newest_idx
            newest_session_date = newest_dt.date() if hasattr(newest_dt, "date") else None
            newest_raw_close = hist["Close"].iloc[-1]
            newest_is_nan = newest_raw_close is None or (
                isinstance(newest_raw_close, float) and math.isnan(newest_raw_close))

            valid = hist.dropna(subset=["Close"])
            if not valid.empty:
                last_row = valid.iloc[-1]
                last_close = float(last_row["Close"])
                last_idx = valid.index[-1]
                dt = last_idx.to_pydatetime() if hasattr(last_idx, "to_pydatetime") else last_idx
                close_date = dt.date() if hasattr(dt, "date") else now_date

                newer_session_exists = newest_is_nan or (
                    newest_session_date is not None and newest_session_date > close_date)
                if not newer_session_exists:
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

    # 2. Fall back to fast_info.last_price. Stamped with the newest session date step 1 already
    # saw (the NaN/later-dated bar refused above) when there is one, else `now` when history gave
    # nothing at all to date it by. Either way this is a live, unsettled quote, not a verified
    # daily close — C9: always record asof_basis so a consumer can tell the two apart.
    try:
        fi = getattr(tk, "fast_info", None)
        if fi is not None:
            last_price = getattr(fi, "last_price", None)
            if last_price is not None:
                px = float(last_price)
                if not math.isnan(px) and px > 0:
                    asof_date = newest_session_date if newest_session_date is not None else now_date
                    return {
                        "price": round(px, 4),
                        "asof": asof_date.isoformat(),
                        "source": "yfinance_fast_info",
                        "asof_basis": "fast_info_unverified",
                    }
    except Exception:
        pass

    return None
