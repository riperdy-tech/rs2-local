#!/usr/bin/env python3
"""
enrich_ticker.py — on-demand yfinance enrichment (Bucket B of the plan).

Fetches the behavioral / positioning fields RS2 Layer 5.5 needs that the daily
screener does NOT capture (kept OUT of the heavy daily fetch_data.py — we only
analyze a handful of names, so we pull these per ticker, on demand):

  - Short interest: % of float, shares short, days-to-cover, MoM change
  - Ownership: institutional %, insider %
  - Options: nearest-expiry put/call OI ratio, put/call volume ratio,
             mean put IV vs call IV (skew), ATM IV
  - Macro: Dollar Index (DXY) level + 1-month direction (Layer 1)

Writes enrich/{TICKER}.json. Every field is sanity-ranged; bad/missing values
become null (RS2 then tags them [Unconfirmed]). Never fabricates.

CLI:  python enrich_ticker.py NVDA
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))


def _pct(x, lo=0.0, hi=200.0):
    """Coerce a yfinance ownership/float FRACTION to a percent, sanity-ranged.

    All three callers pass fields yfinance always returns as fractions
    (shortPercentOfFloat, heldPercentInstitutions, heldPercentInsiders), so the
    conversion is unconditional. The old `if -1.0 <= v <= 1.0` guard silently passed a
    fraction ABOVE 1.0 through unmultiplied — and institutional holdings routinely exceed
    float (13F double-count) — so CHEF's 1.0106 was stored as 1.01, a 100x understatement
    that then read as a perfectly legal percent. Measured 2026-08-13: 77 of 229 covered
    names were wrong this way, while DATA_DISCIPLINE tells the model these values are
    authoritative.

    hi is a UNIT guard, not a cap on reality: institutional % across 243 covered names
    tops out at 134.7 (p99 121.5, none above 150), whereas a percent-valued input would
    land at >=1000. Out of range returns None, so a bad unit reads as absent, never wrong.
    """
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    v *= 100.0
    if not (lo - 1e-9 <= v <= hi + 1e-9):
        return None
    return round(v, 2)


def _num(x, lo=None, hi=None, nd=4):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if lo is not None and v < lo:
        return None
    if hi is not None and v > hi:
        return None
    return round(v, nd)


def short_and_ownership(info):
    return {
        "short_pct_float": _pct(info.get("shortPercentOfFloat")),
        "shares_short": _num(info.get("sharesShort"), lo=0, nd=0),
        "shares_short_prior_month": _num(info.get("sharesShortPriorMonth"), lo=0, nd=0),
        "short_ratio_days_to_cover": _num(info.get("shortRatio"), lo=0, hi=1000, nd=2),
        "institutional_pct": _pct(info.get("heldPercentInstitutions")),
        "insider_pct": _pct(info.get("heldPercentInsiders")),
        "float_shares": _num(info.get("floatShares"), lo=0, nd=0),
        # price position — feeds the 'don't chase near 52-week high' brake (ChatGPT's literal rule)
        "fifty_two_week_high": _num(info.get("fiftyTwoWeekHigh"), lo=0, nd=2),
        "fifty_two_week_low": _num(info.get("fiftyTwoWeekLow"), lo=0, nd=2),
    }


def short_mom_change(d):
    cur, prior = d.get("shares_short"), d.get("shares_short_prior_month")
    if cur and prior and prior > 0:
        return round((cur - prior) / prior * 100.0, 1)
    return None


def options_skew(tk):
    out = {
        "options_expiry": None, "put_call_oi_ratio": None,
        "put_call_vol_ratio": None, "mean_put_iv": None, "mean_call_iv": None,
        "iv_skew_put_minus_call": None,
    }
    try:
        exps = tk.options
        if not exps:
            return out
        # Target ~30 DTE (skip 0DTE/weekly noise); fall back to nearest >=7d, else first.
        today = datetime.now().date()
        def dte(e):
            try:
                return (datetime.strptime(e, "%Y-%m-%d").date() - today).days
            except ValueError:
                return 9999
        usable = [e for e in exps if dte(e) >= 7]
        exp = min(usable, key=lambda e: abs(dte(e) - 30)) if usable else exps[0]
        out["options_expiry"] = exp
        out["options_dte"] = dte(exp)
        chain = tk.option_chain(exp)
        calls, puts = chain.calls, chain.puts
        c_oi, p_oi = calls["openInterest"].sum(), puts["openInterest"].sum()
        c_vol, p_vol = calls["volume"].sum(), puts["volume"].sum()
        if c_oi and c_oi > 0:
            out["put_call_oi_ratio"] = round(float(p_oi) / float(c_oi), 3)
        if c_vol and c_vol > 0:
            out["put_call_vol_ratio"] = round(float(p_vol) / float(c_vol), 3)
        civ = calls["impliedVolatility"].replace(0, float("nan")).mean()
        piv = puts["impliedVolatility"].replace(0, float("nan")).mean()
        out["mean_call_iv"] = _num(civ, lo=0, hi=10, nd=4)
        out["mean_put_iv"] = _num(piv, lo=0, hi=10, nd=4)
        if out["mean_call_iv"] is not None and out["mean_put_iv"] is not None:
            out["iv_skew_put_minus_call"] = round(out["mean_put_iv"] - out["mean_call_iv"], 4)
    except Exception as e:
        out["_options_error"] = str(e)[:160]
    return out


def dxy():
    out = {"dxy_level": None, "dxy_1mo_change_pct": None, "dxy_direction": None}
    try:
        h = yf.Ticker("DX-Y.NYB").history(period="1mo", interval="1d")
        if h is not None and len(h) >= 2:
            close = h["Close"].dropna()
            last, first = float(close.iloc[-1]), float(close.iloc[0])
            out["dxy_level"] = round(last, 2)
            if first:
                chg = (last - first) / first * 100.0
                out["dxy_1mo_change_pct"] = round(chg, 2)
                out["dxy_direction"] = "rising" if chg > 0.3 else "falling" if chg < -0.3 else "flat"
    except Exception as e:
        out["_dxy_error"] = str(e)[:160]
    return out


def analyst_targets(info):
    """Wall-Street consensus = the crowd's through-cycle fair value. The single most
    useful systematic anchor for cyclicals (closes the trough-vs-mid-cycle gap)."""
    return {
        "analyst_target_mean": _num(info.get("targetMeanPrice"), lo=0, nd=2),
        "analyst_target_low":  _num(info.get("targetLowPrice"), lo=0, nd=2),
        "analyst_target_high": _num(info.get("targetHighPrice"), lo=0, nd=2),
        "analyst_target_median": _num(info.get("targetMedianPrice"), lo=0, nd=2),
        "analyst_rec_mean": _num(info.get("recommendationMean"), lo=0, hi=5, nd=2),
        "analyst_count": _num(info.get("numberOfAnalystOpinions"), lo=0, nd=0),
    }


def enrich(ticker):
    t = ticker.upper()
    tk = yf.Ticker(t)
    try:
        info = tk.info or {}
    except Exception:
        info = {}
    data = {"_ticker": t, "_fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    data.update(short_and_ownership(info))
    data["short_mom_change_pct"] = short_mom_change(data)
    data.update(options_skew(tk))
    data.update(dxy())
    data.update(analyst_targets(info))
    return data


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: python enrich_ticker.py <TICKER>", file=sys.stderr)
        sys.exit(1)
    t = sys.argv[1].upper()
    out_dir = Path(CONFIG["out_enrich_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    data = enrich(t)
    path = out_dir / f"{t}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2))
    print(f"\n-> {path}", file=sys.stderr)
