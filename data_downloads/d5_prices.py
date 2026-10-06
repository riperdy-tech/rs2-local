"""D5: Yahoo daily prices (auto_adjust=False, actions=True) 2008-01-01..today for the harness price universe.

Universe = union of: screener-publish cik_map.json tickers (the harness id map), stock-screener backtest_prices.json
tickers, data/priors/_inputs/prices_monthly_raw.json (prices + empty_tickers), plus SPY.
Output: data/prices_daily/<TICKER>.csv.gz (Date,Open,High,Low,Close,Adj Close,Volume,Dividends,Stock Splits),
progress in data/prices_daily/_logs/results.jsonl (append-only; resume skips ok/empty), manifest.csv at the end.
Pass 2 (--retry-empty) retries empties once, with a '.'->'-' variant where relevant.
"""
import argparse, csv, gzip, io, json, threading, time, sys, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
import yfinance as yf
from sec_common import DATA, PRICES, RateLimiter, check_disk, make_logger, free_gb

ap = argparse.ArgumentParser()
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--rate", type=float, default=4.0)
ap.add_argument("--retry-empty", action="store_true")
ap.add_argument("--limit", type=int, default=0)
a = ap.parse_args()

log = make_logger(PRICES / "_logs" / "d5_prices.log")
RES = PRICES / "_logs" / "results.jsonl"
START, END = "2008-01-01", (dt.date.today() + dt.timedelta(days=1)).isoformat()


def universe():
    m = json.load(open(r"C:\Users\riper\stocks\screener-publish\public\data\cik_map.json", encoding="utf-8-sig"))["map"]
    p = json.load(open(r"C:\Users\riper\stocks\stock-screener\public\data\backtest_prices.json", encoding="utf-8"))["prices"]
    r = json.load(open(DATA / "priors" / "_inputs" / "prices_monthly_raw.json"))
    first = sorted(set(p) | set(r["prices"]) | {"SPY"})
    rest = sorted((set(m) | set(r["empty_tickers"])) - set(first))
    return first + rest


def yahoo_symbol(t):
    return t  # Yahoo's own spellings (BRK-B, AUB-PA) already use '-' in the source maps


def fetch(sym):
    df = yf.Ticker(sym).history(start=START, end=END, auto_adjust=False, actions=True, raise_errors=False)
    return df


lock = threading.Lock()
limiter = RateLimiter(a.rate)
pause_until = [0.0]
done = {}
if RES.exists():
    for line in open(RES, encoding="utf-8"):
        try:
            r = json.loads(line); done[r["ticker"]] = r
        except Exception:
            pass


def record(r):
    with lock:
        done[r["ticker"]] = r
        with open(RES, "a", encoding="utf-8") as f:
            f.write(json.dumps(r) + "\n")


def work(t):
    for attempt in range(6):
        w = pause_until[0] - time.time()
        if w > 0:
            time.sleep(w)
        limiter.wait()
        try:
            df = fetch(yahoo_symbol(t))
            if df is None or len(df) == 0:
                if a.retry_empty and "." in t:
                    df = fetch(t.replace(".", "-"))
            if df is None or len(df) == 0:
                return record({"ticker": t, "status": "empty", "rows": 0, "attempt": attempt, "pass": 2 if a.retry_empty else 1})
            idx = df.index
            try:
                idx = idx.tz_localize(None)
            except Exception:
                pass
            df = df.copy()
            df.index = pd.to_datetime(idx).strftime("%Y-%m-%d")
            df.index.name = "Date"
            cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
            df = df[[c for c in cols if c in df.columns]]
            safe = t.replace("/", "_")
            tmp = PRICES / f"{safe}.csv.gz.tmp"
            with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
                df.to_csv(f, float_format="%.10g")
            tmp.replace(PRICES / f"{safe}.csv.gz")
            return record({"ticker": t, "status": "ok", "rows": int(len(df)), "first": df.index[0], "last": df.index[-1],
                           "pass": 2 if a.retry_empty else 1})
        except Exception as e:
            msg = repr(e)
            if "RateLimit" in msg or "Too Many" in msg or "429" in msg:
                pause_until[0] = time.time() + 60 * (attempt + 1)
                log(f"rate limited at {t}; pausing {60*(attempt+1)}s")
            else:
                time.sleep(2 * (attempt + 1))
    return record({"ticker": t, "status": "error", "rows": 0, "pass": 2 if a.retry_empty else 1})


def main():
    uni = universe()
    log(f"universe {len(uni)}; already recorded {len(done)}")
    if a.retry_empty:
        todo = [t for t in uni if done.get(t, {}).get("status") in ("empty", "error") and done[t].get("pass") != 2]
    else:
        todo = [t for t in uni if t not in done]
    if a.limit:
        todo = todo[:a.limit]
    log(f"to do {len(todo)}")
    n = 0; t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for _ in ex.map(work, todo):
            n += 1
            if n % 200 == 0:
                g = check_disk()
                c = {}
                for r in done.values():
                    c[r["status"]] = c.get(r["status"], 0) + 1
                log(f"{n}/{len(todo)}  {n/(time.time()-t0):.1f}/s  {c}  free {g:.0f} GB")
    # manifest
    rows = []
    for t in uni:
        r = done.get(t, {"status": "not_attempted", "rows": 0})
        rows.append([t, r.get("rows", 0), r.get("first", ""), r.get("last", ""), r["status"]])
    with open(PRICES / "manifest.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["ticker", "rows", "first_date", "last_date", "status"]); w.writerows(rows)
    c = {}
    for r in rows:
        c[r[4]] = c.get(r[4], 0) + 1
    log(f"DONE {c}")


main()
