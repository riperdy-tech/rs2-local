"""Items 2 and 3, step 1: for every non-census (date, ticker) of the holdout and development panels, from the D5 daily files (pandas, independent of the harness loader):
  P0..P3   the adjusted OPEN of the first session after each of the next four month-ends S0 = T, S1, S2, S3 (S_k = end of the calendar month k months after T); this is the registered entry convention
           (next session's Open x Adj/Close) applied at every rebalance, so monthly returns r_j = P_j / P_{j-1} - 1 tile the calendar with no gap or overlap;
  end_date, last_adj   the last bar of the series and its adjusted close (a delisting inside the horizon is handled by the caller: 'excluded' / 'last_close' / 'minus100')
  features known at T (bars <= T only): ret_1m (21 sessions), mom_12_1 (21 -> 252 sessions back), vol_1y (std of the last 252 daily returns, >= 200 obs), dvol_3m
SPY gets the same P_k.  Output leak_audit_z/z05_prices.pkl."""
import calendar
import time
from datetime import date

import numpy as np
import pandas as pd

from leak_audit import lib, libz

t0 = time.time()
H = lib.load_panel()                                   # ALL families (the factor universe includes the commodity family)
D = pd.read_pickle(libz.DEV_PANEL)
rows = pd.concat([H.assign(panel="hold"), D.assign(panel="dev")], ignore_index=True)
rows = rows[~rows.survivor.astype(bool)]
print("name-dates", len(rows), "ticker NaN:", int(rows.ticker.isna().sum()))


def eom(y, m):
    return date(y, m, calendar.monthrange(y, m)[1])


def month_ends(T: date, n=4):
    out = []
    for k in range(n):
        idx = T.year * 12 + (T.month - 1) + k
        y, m0 = divmod(idx, 12)
        out.append(eom(y, m0 + 1))
    return out


def load(tk):
    df = pd.read_csv(lib.D5 / f"{tk}.csv.gz", usecols=["Date", "Open", "Close", "Adj Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"].str[:10])
    df = df.dropna(subset=["Date"]).sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
    return df


def next_open(df, dts, d, gap=7):
    i = int(np.searchsorted(dts, np.datetime64(d), side="right"))
    if i >= len(df) or (dts[i] - np.datetime64(d)) / np.timedelta64(1, "D") > gap:
        return np.nan
    op, cl, ad = df["Open"].iat[i], df["Close"].iat[i], df["Adj Close"].iat[i]
    return float(op * ad / cl) if (op > 0 and cl > 0 and ad > 0) else np.nan


def feats(df, dts, T):
    i = int(np.searchsorted(dts, np.datetime64(T), side="right")) - 1
    o = {"ret_1m": np.nan, "mom_12_1": np.nan, "vol_1y": np.nan, "dvol_3m": np.nan, "bar_gap": np.nan}
    if i < 0:
        return o
    o["bar_gap"] = (np.datetime64(T) - dts[i]) / np.timedelta64(1, "D")
    ad = df["Adj Close"].to_numpy(dtype=float)
    if i >= 252 and o["bar_gap"] <= 5:
        o["ret_1m"] = ad[i] / ad[i - 21] - 1.0
        o["mom_12_1"] = ad[i - 21] / ad[i - 252] - 1.0
        w = ad[i - 251:i + 1]
        r = w[1:] / w[:-1] - 1.0
        r = r[np.isfinite(r)]
        if len(r) >= 200:
            o["vol_1y"] = float(np.std(r, ddof=1))
        dv = (df["Close"] * df["Volume"]).iloc[max(0, i - 62):i + 1]
        o["dvol_3m"] = float(dv.mean())
    return o


out = []
for tk, g in list(rows.groupby("ticker")) + [("SPY", None)]:
    df = load(tk)
    dts = df["Date"].to_numpy()
    last = df["Date"].iat[-1]
    last_adj = float(df["Adj Close"].iat[-1])
    first = df["Date"].iat[0]
    if g is None:
        # SPY on every month-end 2019-12 .. 2026-01
        for y in range(2019, 2027):
            for m in range(1, 13):
                S = eom(y, m)
                out.append({"ticker": "SPY", "S": S.isoformat(), "P": next_open(df, dts, S)})
        continue
    for _, r in g.iterrows():
        T = date.fromisoformat(r["date"])
        o = {"date": r["date"], "cik": r["cik"], "ticker": tk, "panel": r["panel"], "end_date": last.date().isoformat(), "last_adj": last_adj, "first_date": first.date().isoformat()}
        for k, S in enumerate(month_ends(T)):
            o[f"P{k}"] = next_open(df, dts, S)
        o.update(feats(df, dts, T))
        out.append(o)
res = pd.DataFrame(out)
spy = res[res.ticker == "SPY"][["S", "P"]].reset_index(drop=True)
res = res[res.ticker != "SPY"]
res.to_pickle(libz.OUT / "z05_prices.pkl")
spy.to_pickle(libz.OUT / "z05_spy.pkl")
print(res.shape, spy.shape, time.time() - t0)
print(res[["P0", "P1", "P2", "P3", "ret_1m", "mom_12_1", "vol_1y"]].isna().groupby(res.panel).mean())
