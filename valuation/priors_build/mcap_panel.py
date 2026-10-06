"""mcap_panel.py - market capitalisation at the observation date of every fiscal year, for the two valuation references (EV / FCFF1, P / TBV).

For each (cik, fiscal year t) with a ticker the raw monthly price download holds, the layer's `market_cap(cik, obs_date)` is read: the TRADED
unadjusted month-end close times the share count on the same basis (cover count, else diluted weighted average, put on the price's basis by the
split events), the state of the company AS KNOWN at the observation date.  The observation date is the first month-end session strictly after
the filing of year t's annual report, so the price is one the market could have paid after the filing (it never contains an outcome).

Only the raw monthly price download the operator approved (prices_monthly_raw.json, 2014-01 to 2026-09, survivors only: 5,192 tickers) is used; there is no
price for a company that has delisted, so these references are measured on SURVIVORS and the report says so.  A company with several tickers
(share classes) is read at the ticker with the largest market capitalisation, flagged `multi_ticker`.
No network, no download.
"""
import argparse
import gzip
import json
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from valuation.pit_data import PitData, MonthlyRawPriceSource
from valuation.priors_build import config as C
from valuation.priors_build.obs import obs_date

_PIT = None
_TICKERS = None


def _init():
    global _PIT, _TICKERS
    src = MonthlyRawPriceSource.load(C.RAW_PRICES)
    m = json.load(open(C.CIK_MAP, encoding="utf-8-sig"))["map"]
    tick = defaultdict(list)
    for t, c in m.items():
        if src.has_key(t):
            tick[str(c).zfill(10)].append(t)
    _TICKERS = dict(tick)
    _PIT = PitData(C.STORE_DIR, price_source=src, id_map={t: c for c, ts in _TICKERS.items() for t in ts})


def _work(ciks):
    out = []
    for cik in ciks:
        tks = _TICKERS[cik]
        c = _PIT.company(cik)
        if c is None:
            continue
        # every fiscal year of the company (first-filed, no cutoff): only to learn the year ends and own-filing dates; the market cap itself is read
        # as known at the observation date
        fys = c.fiscal_years(None, "first_filed")
        for fye, fy in fys.items():
            d = obs_date(fy.exists_from)
            if d.year < 2014:
                continue
            best = None
            for t in tks:
                r = _PIT.market_cap(cik, d, t)
                if best is None or (r["market_cap"] is not None and (best["market_cap"] is None or r["market_cap"] > best["market_cap"])):
                    best = r
                    best["ticker"] = t
            best["flags"] = list(best["flags"]) + (["multi_ticker"] if len(tks) > 1 else [])
            out.append({"cik": cik, "fye": fye, "obs_date": d.isoformat(), "ticker": best["ticker"], "price": best["price"], "shares": best["shares"],
                        "shares_basis": best["shares_basis"], "market_cap": best["market_cap"], "reason": best["reason"], "quality": best["price_quality"],
                        "flags": "|".join(best["flags"]), "provenance_state": best["provenance_state"]})
        _PIT.drop_cache()
    return out


def build(workers, limit=None):
    t0 = time.time()
    _init()
    ciks = sorted(_TICKERS)
    ciks = [c for c in ciks if (C.STORE_DIR / f"{c}.json.gz").exists()]
    if limit:
        ciks = ciks[:limit]
    with Pool(workers, initializer=_init) as p:
        parts = p.map(_work, [ciks[i:i + 40] for i in range(0, len(ciks), 40)])
    df = pd.DataFrame([r for part in parts for r in part])
    path = C.INPUTS_DIR / ("mcap_panel.csv.gz" if not limit else "mcap_panel_try.csv.gz")
    df.to_csv(path, index=False, compression="gzip", float_format="%.10g")
    meta = {"rows": int(len(df)), "ciks": int(df["cik"].nunique()), "market_cap_defined": int(df["market_cap"].notna().sum()),
            "reasons": dict(Counter(df["reason"].fillna("ok"))), "seconds": round(time.time() - t0), "prices": str(C.RAW_PRICES)}
    (C.INPUTS_DIR / "mcap_panel_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    print(build(a.workers, a.limit))
