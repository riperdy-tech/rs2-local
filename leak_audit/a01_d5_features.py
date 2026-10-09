"""Checks 1, 2 (price side), 8, and the market features for check 9/10: an INDEPENDENT reading of the D5 daily files (pandas, not the loader) for every name-date of the in-scope panel.

For each (date, ticker) of the registered universe it computes
  * p_ind      the traded close at T, rebuilt as Yahoo Close(T) x the product of EVERY split ratio with an ex-date after T (no "RAW event" classification)
  * p_month    the same from the monthly raw file (a separate Yahoo pull, 2026-10-01): Close(month) x the product of the monthly split ratios of later months
  * split events: all with ex-date in (T-1y, T+1y], and after T; the continuity test of the adjusted Close across each post-T ex-date (is the Close really adjusted?)
  * the outcome, independently: entry = next session's Open x (Adj Close / Close) of that bar; exit = Adj Close of the last bar on or before T + 12 months (gap <= 5 days);
    excess = ret - SPY ret on the same dates  -> compared with the stored x12 (observed names)
  * market features known at T (bars <= T only): ret_1m (21 sessions), vol_1y, idio_vol_1y and beta_1y against SPY, pre-period excess return T-12m -> T (the placebo of check 10b), 1/price
Reads only.  One process.
"""
import json
import math
from datetime import date

import numpy as np
import pandas as pd

from leak_audit import lib

SPY = None


def add_months(d: date, n: int) -> date:
    import calendar
    idx = d.year * 12 + (d.month - 1) + n
    y, m0 = divmod(idx, 12)
    return date(y, m0 + 1, min(d.day, calendar.monthrange(y, m0 + 1)[1]))


def load_bars(tk):
    p = lib.D5 / f"{tk}.csv.gz"
    if not p.is_file():
        return None
    df = pd.read_csv(p, usecols=["Date", "Open", "Close", "Adj Close", "Volume", "Stock Splits"])
    df["Date"] = pd.to_datetime(df["Date"].str[:10])
    return df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)


def bar_on_or_before(df, d, gap=5):
    i = int(df["Date"].searchsorted(pd.Timestamp(d), side="right")) - 1
    if i < 0:
        return None
    if (pd.Timestamp(d) - df["Date"].iat[i]).days > gap:
        return None
    return i


def next_bar(df, d, gap=5):
    i = int(df["Date"].searchsorted(pd.Timestamp(d), side="right"))
    if i >= len(df) or (df["Date"].iat[i] - pd.Timestamp(d)).days > gap:
        return None
    return i


def main():
    panel = lib.load_panel()
    panel = panel[panel["family"] != "commodity"].copy()
    panel = panel[~panel["survivor"].astype(bool)]                    # the census names are priced by a proxy: no D5 file
    mon = json.load(open(lib.WS / "data" / "priors" / "_inputs" / "prices_monthly_raw.json"))["prices"]
    spy = load_bars("SPY")
    spy_ret = spy.set_index("Date")["Adj Close"].pct_change()
    out = []
    tickers = sorted(set(panel["ticker"].dropna()))
    byt = {t: g for t, g in panel.groupby("ticker")}
    for n, tk in enumerate(tickers):
        df = load_bars(tk)
        g = byt[tk]
        if df is None:
            for _, r in g.iterrows():
                out.append({"date": r["date"], "cik": r["cik"], "ticker": tk, "no_d5": True})
            continue
        splits = df.loc[(df["Stock Splits"].fillna(0) != 0), ["Date", "Stock Splits"]]
        splits = [(pd.Timestamp(a).date(), float(b)) for a, b in zip(splits["Date"], splits["Stock Splits"])]
        ret = df.set_index("Date")["Adj Close"].pct_change()
        mrow = mon.get(tk) or {}
        for _, r in g.iterrows():
            T = date.fromisoformat(r["date"])
            o = {"date": r["date"], "cik": r["cik"], "ticker": tk, "no_d5": False}
            i = bar_on_or_before(df, T)
            if i is None:
                o["no_bar"] = True
                out.append(o)
                continue
            later = [(d, s) for d, s in splits if d > T]
            prod_later = float(np.prod([s for _d, s in later])) if later else 1.0
            c = float(df["Close"].iat[i])
            o["bar_gap"] = (pd.Timestamp(T) - df["Date"].iat[i]).days
            o["close_T"] = c
            o["p_ind"] = c * prod_later
            o["n_later_splits"] = len(later)
            o["later_prod"] = prod_later
            o["later_splits"] = [(d.isoformat(), s) for d, s in later]
            # splits in the window T-1y .. T+1y (any ratio)
            win = [(d, s) for d, s in splits if add_months(T, -12) < d <= add_months(T, 12)]
            o["n_split_win"] = len(win)
            o["n_split_win_ge1p5"] = sum(1 for _d, s in win if abs(math.log(s)) >= math.log(1.5))
            o["splits_win"] = [(d.isoformat(), s) for d, s in win]
            # continuity of the adjusted Close across each post-T ex-date within the data: log(Cadj_post / Cadj_pre) should be small if Yahoo adjusted the earlier bars
            cont = []
            for d, s in later:
                j = int(df["Date"].searchsorted(pd.Timestamp(d), side="left"))
                if j <= 0 or j >= len(df):
                    continue
                pre, post = float(df["Close"].iat[j - 1]), float(df["Close"].iat[j])
                if pre > 0 and post > 0:
                    cont.append((d.isoformat(), s, math.log(post / pre)))
            o["cont"] = cont
            # monthly pull
            mk = f"{T.year}-{T.month:02d}"
            mb = mrow.get(mk)
            if mb is not None and mb[0] is not None and mb[0] == mb[0]:
                pm = float(mb[0])
                for mm, v in mrow.items():
                    if mm > mk and v[3] not in (0, 0.0, None) and v[3] == v[3]:
                        pm *= float(v[3])
                o["p_month"] = pm
            # outcome, independently
            ent = next_bar(df, T)
            if ent is not None:
                op, cl, ad = float(df["Open"].iat[ent]), float(df["Close"].iat[ent]), float(df["Adj Close"].iat[ent])
                o["entry_date"] = df["Date"].iat[ent].date().isoformat()
                o["entry_px"] = op * ad / cl if (cl > 0 and ad > 0 and op > 0) else np.nan
                d1 = add_months(T, 12)
                k = bar_on_or_before(df, d1)
                if k is not None and df["Date"].iat[k].date() > T:
                    o["exit_date"] = df["Date"].iat[k].date().isoformat()
                    o["exit_px"] = float(df["Adj Close"].iat[k])
                    # SPY on the same convention
                    se, sx = next_bar(spy, T), bar_on_or_before(spy, d1)
                    if se is not None and sx is not None:
                        so = float(spy["Open"].iat[se] * spy["Adj Close"].iat[se] / spy["Close"].iat[se])
                        sxx = float(spy["Adj Close"].iat[sx])
                        o["ret12_ind"] = o["exit_px"] / o["entry_px"] - 1.0
                        o["spy12_ind"] = sxx / so - 1.0
                        o["x12_ind"] = o["ret12_ind"] - o["spy12_ind"]
            # features known at T
            if i >= 260:
                w = ret.iloc[i - 251:i + 1]
                m = spy_ret.reindex(w.index)
                ok = w.notna() & m.notna()
                if ok.sum() >= 200:
                    x, y = m[ok].to_numpy(), w[ok].to_numpy()
                    b = float(np.cov(x, y)[0, 1] / np.var(x, ddof=1))
                    res = y - (y.mean() + b * (x - x.mean()))
                    o["vol_1y"], o["beta_1y"], o["idio_vol_1y"] = float(np.std(y, ddof=1)), b, float(np.std(res, ddof=1))
                j = i - 21
                o["ret_1m"] = float(df["Adj Close"].iat[i] / df["Adj Close"].iat[j] - 1.0)
                # pre-period: T-12m -> T
                kb = bar_on_or_before(df, add_months(T, -12))
                sb = bar_on_or_before(spy, add_months(T, -12))
                si = bar_on_or_before(spy, T)
                if kb is not None and sb is not None and si is not None:
                    o["pre12"] = float(df["Adj Close"].iat[i] / df["Adj Close"].iat[kb] - 1.0)
                    o["pre12_spy"] = float(spy["Adj Close"].iat[si] / spy["Adj Close"].iat[sb] - 1.0)
                    o["pre12_x"] = o["pre12"] - o["pre12_spy"]
                dv = (df["Close"] * df["Volume"]).iloc[max(0, i - 62):i + 1]
                o["dvol_3m"] = float(dv.mean())
            out.append(o)
        if n % 200 == 0:
            print(n, len(tickers), flush=True)
    res = pd.DataFrame(out)
    res.to_pickle(lib.OUT / "a01_d5_features.pkl")
    print(res.shape, res["no_d5"].sum())


if __name__ == "__main__":
    lib.OUT.mkdir(parents=True, exist_ok=True)
    main()
