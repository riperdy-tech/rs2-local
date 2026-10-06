"""Backtest registration 7.2: the survivorship census per date.

10-K filers with revenue of at least $100M at L(T) (registration 4.2) but no price at T, as a count and a revenue share.
The population is every company in the SEC archive: the companies behind the screener's tickers (extractor run on the cut zip, one
company per CIK) and the rest (the census run: the same unchanged extractor on pseudo-tickers, one per remaining company).  The
167 untouched names and their companies are in neither.  Counts only; no company is named.

A company is "priced at T" when at least one of its tickers has a bar for Y-06 in the approved price download.  The rest are split by why:
  yahoo_no_data           a ticker of the company is one of the 116 the download returned nothing for ("no longer served by Yahoo")
  ticker_without_bar_at_T the price file holds a ticker of the company but no bar for Y-06
  ticker_not_in_price_file  the screener lists a ticker the price file does not hold
  no_screener_ticker      no ticker of the company is in the screener's list (delisted before it, or never listed)
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

from .common import PriceBook, is_num, parse_date
from .pit_data import REVENUE_FLOOR, base_year


def _qualifies(rows, pe, side, T):
    """Revenue at L if the company is a 10-K filer with an L and revenue >= $100M, else None."""
    if not (side or {}).get("k10"):
        return None
    L, _fye, why = base_year(rows, pe, T)
    if L is None:
        return None
    rev = rows[str(L)].get("revenue")
    return float(rev) if is_num(rev) and rev >= REVENUE_FLOOR else None


def census_date(year, T, labels, book, main_hist, main_prov, census_hist, census_prov, side):
    T = parse_date(T)
    Tm = f"{year}-06"
    companies = defaultdict(lambda: {"tickers": [], "rows": None, "pe": None})
    for t in sorted(labels):
        cik = labels[t].get("cik")
        if cik is None:
            continue
        c = companies[cik]
        c["tickers"].append(t)
        if c["rows"] is None and t in main_hist:
            c["rows"], c["pe"] = main_hist[t], (main_prov.get("period_end") or {}).get(t)
    for pseudo, rows in census_hist.items():
        cik = pseudo[1:]
        c = companies[cik]
        c["rows"], c["pe"] = rows, (census_prov.get("period_end") or {}).get(pseudo)
    out = Counter()
    revenue = Counter()
    for cik, c in companies.items():
        if c["rows"] is None:
            continue
        rev = _qualifies(c["rows"], c["pe"], side.get(cik), T)
        if rev is None:
            continue
        out["qualifying"] += 1
        revenue["qualifying"] += rev
        tickers = c["tickers"]
        if any(book.has_bar(t, Tm) for t in tickers):
            key = "priced"
        elif not tickers:
            key = "no_screener_ticker"
        elif any(t in book.empty for t in tickers):
            key = "yahoo_no_data"
        elif any(book.has_ticker(t) for t in tickers):
            key = "ticker_without_bar_at_T"
        else:
            key = "ticker_not_in_price_file"
        out[key] += 1
        revenue[key] += rev
    unpriced = out["qualifying"] - out["priced"]
    rev_unpriced = revenue["qualifying"] - revenue["priced"]
    return {"qualifying_10k_filers_revenue_ge_100M": out["qualifying"], "priced_at_T": out["priced"], "no_price_at_T": unpriced,
            "revenue_share_without_price": (rev_unpriced / revenue["qualifying"]) if revenue["qualifying"] else None,
            "by_reason": {k: {"count": out[k], "revenue_share": revenue[k] / revenue["qualifying"]}
                          for k in ("yahoo_no_data", "ticker_without_bar_at_T", "ticker_not_in_price_file", "no_screener_ticker")}}


def run(bt_root, years):
    bt_root = Path(bt_root)
    book = PriceBook.load(bt_root / "prices" / "prices_monthly_raw.json")
    labels = json.loads((bt_root / "pit" / "universe" / "labels.json").read_text(encoding="utf-8"))
    anchors = json.loads((bt_root / "mri" / "pit_anchors.json").read_text(encoding="utf-8"))["dates"]
    res = {}
    for y in years:
        T = anchors[y]["T"]
        main = json.loads((bt_root / "pit" / f"H_{y}" / "fundamentals_history.json").read_text(encoding="utf-8"))
        cen = json.loads((bt_root / "pit" / f"Hc_{y}" / "fundamentals_history.json").read_text(encoding="utf-8"))
        side = json.loads((bt_root / "pit" / "cut" / f"side_{T}.json").read_text(encoding="utf-8"))
        res[y] = census_date(y, T, labels, book, main["tickers"], main["provenance"], cen["tickers"], cen["provenance"], side)
        print(y, res[y]["qualifying_10k_filers_revenue_ge_100M"], res[y]["no_price_at_T"], flush=True)
    (bt_root / "out" / "prelook" / "census.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    import argparse
    from .common import DATES
    ap = argparse.ArgumentParser()
    ap.add_argument("--bt-root", required=True, type=Path)
    ap.add_argument("--years", nargs="*", default=list(DATES))
    a = ap.parse_args()
    run(a.bt_root, a.years)
