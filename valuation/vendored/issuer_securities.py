"""issuer_securities.py — which universe tickers under one SEC CIK are the issuer's common stock.

SEC's company_tickers.json lists every exchange-listed security of an issuer (preferreds,
baby bonds, SPAC units, mandatory-convertible units, ...) under the issuer's CIK, so
cik_map.json gives all of them the common stock's CIK. Anything that attaches the issuer's
SEC data (shares, per-share figures, history, metrics) to a ticker must attach it to the
common tickers only.

The rule, in one place:
  * the common tickers under a CIK are the universe tickers mapped to it whose vendor
    marketCap (stocks.json) is a number > 0 (0, None and missing all mean "no vendor market cap");
  * a CIK with no such ticker offers no evidence to choose, so all its tickers count as common;
  * a non-common security is a universe ticker under a CIK that has at least one common ticker,
    while it has no vendor market cap itself.
Real dual-class common stock (GOOG/GOOGL, FOX/FOXA, ...) always carries its own vendor market
cap, so both classes stay common. A ticker with no CIK is never touched.

Pure functions: callers pass the ticker -> CIK map and the stocks.json rows.
"""

from typing import Any, Dict, Iterable, List


def _has_vendor_market_cap(stock: Dict[str, Any]) -> bool:
    mcap = stock.get("marketCap")
    return isinstance(mcap, (int, float)) and not isinstance(mcap, bool) and mcap > 0


def common_tickers_by_cik(ticker_to_cik: Dict[str, str], stocks: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    """{cik: sorted common tickers} for every CIK that has a universe ticker mapped to it."""
    by_cik: Dict[str, Dict[str, bool]] = {}
    for s in stocks:
        sym = s.get("symbol")
        cik = ticker_to_cik.get(sym) if sym else None
        if cik is None:
            continue
        by_cik.setdefault(cik, {})[sym] = _has_vendor_market_cap(s)
    result = {}
    for cik, tickers in by_cik.items():
        with_mcap = [t for t, has in tickers.items() if has]
        result[cik] = sorted(with_mcap if with_mcap else tickers)
    return result


def non_common_securities(ticker_to_cik: Dict[str, str], stocks: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{ticker: {"cik": cik, "common": [sorted common tickers]}} for every non-common security."""
    stocks = list(stocks)
    common = common_tickers_by_cik(ticker_to_cik, stocks)
    result = {}
    for s in stocks:
        sym = s.get("symbol")
        cik = ticker_to_cik.get(sym) if sym else None
        if cik is not None and sym not in common[cik]:
            result[sym] = {"cik": cik, "common": common[cik]}
    return result
