#!/usr/bin/env python3
"""
openbb_data.py — analyst-grade financial data via OpenBB free providers.
Runs in SYSTEM python (where openbb is installed). Pulls data the screener/yfinance-enrich
don't have, then formats a block for the RS2 pipeline:
  - analyst consensus price targets (yfinance)
  - institutional 13F holdings (SEC)
  - insider trading net activity (SEC)
  - key valuation/quality metrics (yfinance)
  - latest earnings-call transcript excerpt (FMP, quota-guarded — management's own words)

Cached per ticker (cache/openbb_{T}.json, TTL openbb_cache_days). yfinance load is tiny
(few analyzed tickers, cached) — never the daily 8k-ticker scan.

CLI:  python openbb_data.py NVDA
"""
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
import quota

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
CACHE = HERE / "cache"; CACHE.mkdir(exist_ok=True)
TTL_DAYS = CONFIG.get("openbb_cache_days", 1)


def _obb():
    from openbb import obb
    fmp = quota.key("FMP_API_KEY")
    if fmp:
        try: obb.user.credentials.fmp_api_key = fmp
        except Exception: pass
    return obb


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        return ("ERR:" + str(e)[:80]) if default is None else default


def _forward_growth(t):
    """Forward analyst growth (fraction/yr) from yfinance's free estimate tables
    (revenue_estimate / earnings_estimate / growth_estimates — the Yahoo analysis page).
    Returns {eps_cagr, revenue_cagr, source} — any field may be None.

    REWRITTEN 2026-07-11: the original OpenBB route NEVER returned data (0/224 caches) —
    obb forward_eps rejects provider='yfinance', forward_sales doesn't exist in this openbb
    version, and FMP's forward_eps is premium-gated. Fair values silently rode the
    PEG-implied fallback the whole time. yfinance's own tables are free and populated.
    Horizon: prefer the long-term (LTG/+5y) growth when present (matches the DCF's 5yr
    stage-1), else next-FY (+1y); the backbone still caps at FWD_GROWTH_CEIL."""
    out = {"eps_cagr": None, "revenue_cagr": None, "source": None}

    def _cell(df, row, col):
        try:
            v = df.loc[row, col]
            v = float(v)
            return v if (v == v and abs(v) < 5) else None   # NaN/absurd guard
        except Exception:
            return None

    def _first(df, col, rows=("LTG", "+5y", "+1y", "0y")):
        if df is None:
            return None
        for r in rows:
            v = _cell(df, r, col)
            if v is not None:
                return v
        return None

    try:
        import yfinance as yf
        tk = yf.Ticker(t)
        rev = _safe(lambda: tk.revenue_estimate, {})
        eps = _safe(lambda: tk.earnings_estimate, {})
        gro = _safe(lambda: tk.growth_estimates, {})
        rev = rev if hasattr(rev, "loc") else None
        eps = eps if hasattr(eps, "loc") else None
        gro = gro if hasattr(gro, "loc") else None
        r = _first(rev, "growth", rows=("+1y", "0y"))        # revenue tables carry no LTG
        e = _first(eps, "growth", rows=("+1y", "0y"))
        if e is None and gro is not None:
            for col in ("stockTrend", "stock"):              # column name varies by yfinance version
                e = _first(gro, col)
                if e is not None:
                    break
        if e is not None or r is not None:
            out.update(eps_cagr=e, revenue_cagr=r, source="yfinance_estimates")
    except Exception:
        pass
    return out


def _transcript_defeatbeta(t):
    """Latest earnings-call transcript via the defeatbeta HF dataset (free, no quota,
    remote-DuckDB column-pruned reads — NOT a bulk download). Returns the same shape the
    FMP path produced ({quarter, year, excerpt}) or None so the caller can fall back.
    The package prints an emoji banner at import; force UTF-8 stdout first or a cp1252
    console kills the import."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from defeatbeta_api.data.ticker import Ticker as _DbTicker
    tr = _DbTicker(t).earning_call_transcripts()
    lst = tr.get_transcripts_list()
    if lst is None or len(lst) == 0:
        return None
    last = lst.sort_values("report_date").iloc[-1]     # newest by calendar date (fiscal-year numbering varies by company)
    fy, fq = int(last["fiscal_year"]), int(last["fiscal_quarter"])
    df = tr.get_transcript(fy, fq)
    if df is None or len(df) == 0:
        return None
    txt = "\n".join(f"{r.speaker}: {r.content}" for r in df.itertuples(index=False))
    return {"quarter": fq, "year": fy, "excerpt": txt[:2500], "source": "defeatbeta"}


def fetch(ticker):
    """Pull the analyst-grade fields; return a dict (cached)."""
    t = ticker.upper()
    cf = CACHE / f"openbb_{t}.json"
    if cf.exists() and (time.time() - cf.stat().st_mtime) / 86400 <= TTL_DAYS:
        return json.loads(cf.read_text(encoding="utf-8"))

    obb = _obb()
    d = {"_ticker": t, "_fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    # analyst consensus targets (yfinance, free)
    def consensus():
        r = obb.equity.estimates.consensus(t, provider="yfinance").results[0]
        return {k: getattr(r, k, None) for k in
                ("target_consensus", "target_high", "target_low", "target_median",
                 "recommendation", "number_of_analysts")}
    d["analyst_consensus"] = _safe(consensus, {})

    # institutional 13F (SEC, free) — count + top holders
    def inst():
        rows = obb.equity.ownership.form_13f(t, provider="sec").results
        return {"records": len(rows)}
    d["institutional_13f"] = _safe(inst, {})

    # insider trades (SEC, free) — net buy/sell of recent
    def insiders():
        rows = obb.equity.ownership.insider_trading(t, provider="sec").results[:40]
        buys = sum(1 for r in rows if str(getattr(r, "acquisition_or_disposition", "")).upper().startswith("A"))
        sells = sum(1 for r in rows if str(getattr(r, "acquisition_or_disposition", "")).upper().startswith("D"))
        return {"recent_count": len(rows), "buys": buys, "sells": sells}
    d["insider_activity"] = _safe(insiders, {})

    # key metrics (yfinance, free)
    def metrics():
        r = obb.equity.fundamental.metrics(t, provider="yfinance").results[0]
        return {k: getattr(r, k, None) for k in
                ("pe_ratio", "peg_ratio", "price_to_sales", "price_to_book",
                 "return_on_equity", "gross_margin", "operating_margin", "dividend_yield")}
    d["metrics"] = _safe(metrics, {})

    # FORWARD analyst growth — the fresh, correct input for fair value (trailing 5y CAGR
    # over-extrapolates post-IPO / hyper-ramp names). yfinance free estimate tables (see
    # _forward_growth for why the old OpenBB route was dead). Consumed by
    # valuation_backbone._forward_growth (which also falls back to PEG-implied from metrics).
    d["forward_growth"] = _safe(lambda: _forward_growth(t), {})

    # earnings transcript — latest quarter management commentary.
    # defeatbeta first (free HF dataset, full speaker-attributed transcript, no quota);
    # FMP only as a quota-guarded fallback when defeatbeta has nothing for the name.
    d["transcript_excerpt"] = _safe(lambda: _transcript_defeatbeta(t), None)
    if not isinstance(d["transcript_excerpt"], dict):
        d["transcript_excerpt"] = None
    if d["transcript_excerpt"] is None and quota.key("FMP_API_KEY") and quota.remaining("fmp") > 2:
        def transcript():
            r = obb.equity.fundamental.transcript(t, provider="fmp").results
            if not r:
                return None
            latest = r[-1]
            txt = getattr(latest, "content", "") or ""
            return {"quarter": getattr(latest, "quarter", None), "year": getattr(latest, "year", None),
                    "excerpt": txt[:2500], "source": "fmp"}
        d["transcript_excerpt"] = _safe(transcript, None)
        quota.bump("fmp", 1)

    cf.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return d


def format_block(ticker):
    d = fetch(ticker)
    L = ["## ANALYST-GRADE DATA (OpenBB — SEC / consensus / FMP)", ""]
    c = d.get("analyst_consensus") or {}
    if isinstance(c, dict) and c.get("target_consensus"):
        L.append(f"- Analyst price target [Estimate]: consensus ${c.get('target_consensus')} "
                 f"(low ${c.get('target_low')} / high ${c.get('target_high')}), "
                 f"{c.get('number_of_analysts') or '?'} analysts, rec '{c.get('recommendation')}'.")
    ins = d.get("insider_activity") or {}
    if isinstance(ins, dict) and ins.get("recent_count"):
        L.append(f"- Insider activity (SEC, recent {ins['recent_count']}): {ins.get('buys',0)} acquisitions vs "
                 f"{ins.get('sells',0)} dispositions.")
    inst = d.get("institutional_13f") or {}
    if isinstance(inst, dict) and inst.get("records"):
        L.append(f"- Institutional 13F filings on record: {inst['records']}.")
    m = d.get("metrics") or {}
    if isinstance(m, dict) and any(m.values()):
        L.append(f"- Key metrics [Actual]: P/E {m.get('pe_ratio')}, P/S {m.get('price_to_sales')}, "
                 f"P/B {m.get('price_to_book')}, ROE {m.get('return_on_equity')}, PEG {m.get('peg_ratio')}, "
                 f"op margin {m.get('operating_margin')}, div yield {m.get('dividend_yield')}.")
    fg = d.get("forward_growth") or {}
    if isinstance(fg, dict) and (fg.get("eps_cagr") is not None or fg.get("revenue_cagr") is not None):
        parts = []
        if fg.get("revenue_cagr") is not None: parts.append(f"revenue {fg['revenue_cagr']*100:+.1f}%/yr")
        if fg.get("eps_cagr") is not None: parts.append(f"EPS {fg['eps_cagr']*100:+.1f}%/yr")
        L.append(f"- FORWARD analyst growth [Estimate]: {', '.join(parts)} "
                 f"(source {fg.get('source')}) — the consensus expectation for the next 1-3yr.")
    tr = d.get("transcript_excerpt")
    if isinstance(tr, dict) and tr.get("excerpt"):
        L.append(f"\n- Latest earnings-call transcript ({tr.get('source', 'fmp')}, Q{tr.get('quarter')} {tr.get('year')}) — "
                 f"management commentary excerpt:\n  > " + tr["excerpt"].replace("\n", " ")[:1500])
    if len(L) <= 2:
        return ""
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: python openbb_data.py <TICKER>", file=sys.stderr); sys.exit(1)
    print(format_block(sys.argv[1].upper()))
