"""Backtest registration section 4.7: the as-of-T equity aggregate, with the rules of MRI's scripts/build_equity_aggregate.py.

The rules (re-stated here because nothing may be imported across repositories; `test_aggregate_rules.py` reproduces MRI's
own aggregate from today's inputs to check the restatement):
  1. USD reporters only (screener FX flag None) with a positive market cap;
  2. share classes collapsed by company, the largest market cap kept (ties: the first in sorted ticker order);
  3. owner earnings (NI + D&A - capex) of the latest fiscal year > 0, and revenue growth: the CAGR over up to 6 fiscal
     years (at least 4 points), clamped to [-5%, 35%].
Market caps are the caller's (cap(T) of 4.3).
"""
MIN_GROWTH, MAX_GROWTH = -0.05, 0.35
MIN_CONSTITUENTS = 30
MIN_COVERAGE_SHARE = 0.60


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def owner_earnings_latest(fiscal_years, latest):
    rec = (fiscal_years or {}).get(latest)
    if not isinstance(rec, dict):
        return None
    ni, da, capex = rec.get("net_income"), rec.get("da"), rec.get("capex")
    if not all(_num(v) for v in (ni, da, capex)):
        return None
    return float(ni) + float(da) - float(capex)


def revenue_cagr(fiscal_years, max_years=6):
    years = sorted(int(y) for y in (fiscal_years or {}) if str(y).isdigit())
    points = []
    for year in years:
        value = (fiscal_years.get(str(year)) or {}).get("revenue")
        if _num(value) and value > 0:
            points.append((year, float(value)))
    if len(points) < 4:
        return None
    (y0, v0), (y1, v1) = points[max(0, len(points) - max_years)], points[-1]
    if y1 <= y0 or v0 <= 0:
        return None
    return (v1 / v0) ** (1 / (y1 - y0)) - 1


def build_aggregate(items, as_of=None):
    """items: dicts {ticker, cik, market_cap, rows} for every ticker that is a USD reporter with a market cap, in any order.
    Returns (aggregate dict in MRI's schema, stats).  Constituents carry the company id `cik` (never a ticker)."""
    universe = []
    for it in sorted(items, key=lambda x: x["ticker"]):
        cap = it["market_cap"]
        if not _num(cap) or cap <= 0:
            continue
        years = it["rows"] or {}
        latest = max(years) if years else None
        if latest is None:
            continue
        universe.append({"ticker": it["ticker"], "market_cap": float(cap), "cash_flow": owner_earnings_latest(years, latest),
                         "growth": revenue_cagr(years), "fiscal_year": latest, "cik": str(it.get("cik") or "")})
    total_cap_all = sum(u["market_cap"] for u in universe)
    by_key, class_collapsed = {}, 0
    for u in universe:
        key = u["cik"] or f"ticker:{u['ticker']}"
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = u
        else:
            class_collapsed += 1
            if u["market_cap"] > cur["market_cap"]:
                by_key[key] = u
    collapsed = list(by_key.values())
    total_cap_collapsed = sum(u["market_cap"] for u in collapsed)
    constituents = []
    lost = {"owner_earnings_missing": 0.0, "owner_earnings_not_positive": 0.0, "revenue_growth_missing": 0.0}
    for u in collapsed:
        if u["cash_flow"] is None:
            lost["owner_earnings_missing"] += u["market_cap"]
            continue
        if u["cash_flow"] <= 0:
            lost["owner_earnings_not_positive"] += u["market_cap"]
            continue
        if u["growth"] is None:
            lost["revenue_growth_missing"] += u["market_cap"]
            continue
        constituents.append({"cik": u["cik"] or u["ticker"], "ticker_key": u["ticker"], "cash_flow": round(u["cash_flow"], 2),
                             "market_cap": round(u["market_cap"], 2),
                             "growth": round(min(max(u["growth"], MIN_GROWTH), MAX_GROWTH), 6)})
    constituents.sort(key=lambda c: -c["market_cap"])
    usable_cap = sum(c["market_cap"] for c in constituents)
    coverage = (usable_cap / total_cap_collapsed) if total_cap_collapsed else 0.0
    stats = {"names_with_market_cap": len(universe), "share_classes_collapsed": class_collapsed,
             "corpus_market_cap_usd_t": round(total_cap_all / 1e12, 4), "collapsed_market_cap_usd_t": round(total_cap_collapsed / 1e12, 4),
             "constituents": len(constituents), "constituent_market_cap_usd_t": round(usable_cap / 1e12, 4),
             "coverage_share": round(coverage, 4),
             "cap_share_lost": {k: round(v / total_cap_collapsed, 4) if total_cap_collapsed else None for k, v in lost.items()}}
    agg = {"asof": as_of, "source": "backtest harness, registration 4.7", "basis": "universe", "growth": None,
           "coverage_share": round(coverage, 4), "constituents": constituents, "universe_stats": stats}
    return agg, stats
