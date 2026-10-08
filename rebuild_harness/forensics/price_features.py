"""Market features at each valuation date from the D5 daily files, for F4 (distance to default) and F5 (size, beta, liquidity): one pass over the ticker files, all dates at once.

    python -m rebuild_harness.forensics.price_features --out OUT.pkl [--tickers A B ...] [--dates ...]

For ticker i and date T (bars on or before T only; the decision is taken at the close of T):
  vol_1y     standard deviation of the daily log total-return (Adj Close) over the last 252 bars, annualised; needs >= 200 bars
  beta_1y    OLS slope of the ticker's daily total return on SPY's over the same 252-bar window (dates aligned); needs >= 200 common bars
  ret_1y     the 252-bar log total return (the drift of the naive distance to default)
  dvol_3m    the median over the last 63 bars of Close x Volume (both split-adjusted on the same basis, so the product is the traded dollar volume)
Nothing here is read by an engine.  CPU only, no network."""
import argparse
import gzip
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from rebuild_harness import holdout_inputs, gate1_run as g1r

D = g1r.WORKSPACE / "data" / "prices_daily"
WIN, MIN_OBS = 252, 200


def load(path):
    df = pd.read_csv(path, usecols=["Date", "Close", "Adj Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"].str[:10])
    df = df.dropna(subset=["Adj Close"])
    df = df[df["Adj Close"] > 0].drop_duplicates("Date").sort_values("Date").set_index("Date")
    return df


def features(df, spy_ret, dates):
    lr = np.log(df["Adj Close"]).diff()
    out = {}
    idx = df.index
    for d in dates:
        k = int(idx.searchsorted(pd.Timestamp(d), side="right"))
        if k < 2:
            continue
        if (pd.Timestamp(d) - idx[k - 1]).days > 5:
            continue
        sl = slice(max(0, k - WIN), k)
        r = lr.iloc[sl].dropna()
        row = {}
        if len(r) >= MIN_OBS:
            row["vol_1y"] = float(r.std(ddof=1) * np.sqrt(252))
            common = r.index.intersection(spy_ret.index)
            if len(common) >= MIN_OBS:
                x, y = spy_ret.loc[common].values, r.loc[common].values
                vx = x.var(ddof=1)
                row["beta_1y"] = float(np.cov(x, y, ddof=1)[0, 1] / vx) if vx > 0 else None
            if k - WIN - 1 >= 0:
                row["ret_1y"] = float(np.log(df["Adj Close"].iloc[k - 1] / df["Adj Close"].iloc[k - 1 - WIN]))
        dv = (df["Close"].iloc[max(0, k - 63):k] * df["Volume"].iloc[max(0, k - 63):k]).dropna()
        if len(dv) >= 40:
            row["dvol_3m"] = float(dv.median())
        if row:
            out[d] = row
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--dates", nargs="*")
    a = ap.parse_args(argv)
    from .run import month_end_dates
    dates = a.dates or month_end_dates()
    spy = load(D / "SPY.csv.gz")
    spy_ret = np.log(spy["Adj Close"]).diff().dropna()
    tickers = a.tickers or sorted(p.name[:-7] for p in D.iterdir() if p.name.endswith(".csv.gz"))
    res = {}
    for i, t in enumerate(tickers):
        try:
            f = features(load(D / f"{t}.csv.gz"), spy_ret, dates)
        except Exception:
            continue
        if f:
            res[t] = f
        if i % 1000 == 0:
            print(i, len(tickers), flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "wb") as fh:
        pickle.dump({"dates": dates, "features": res}, fh)
    print("written", a.out, len(res))


if __name__ == "__main__":
    main()
