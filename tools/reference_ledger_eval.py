"""The frozen evaluation of the forward ledger (revision 18, brief section 5.2). REPORT ONLY.

Run once at 12 months and once at 36 months after acceptance, with the backtest's definitions
(registration d09bb4a4, sections 4.3 and 7; the metric functions below are copied verbatim from the backtest harness's
metrics.py at commit 40cb5cf, because nothing imports across branches). No design change may rest on its output in the first
12 months.

  python tools/reference_ledger_eval.py --ledger <reference_ledger.jsonl> --prices <prices.csv> --prices-sha256 <hex>
        --acceptance-date YYYY-MM-DD --horizon {12,36} [--asof YYYY-MM-DD] [--revision 18] [--untouched-list <path>]
        [--out <result.json>]

prices.csv (a hashed file, refused unless its sha256 is --prices-sha256): columns date, ticker, close, adj_close, dividends,
stock_splits - what Yahoo's history gives through yfinance with auto_adjust=False and actions=True (the unadjusted Close, the
Adj Close, the dividends and the splits), one row per ticker per trading day, SPY included. It is fetched ONCE per evaluation
date, by the operator, with the operator's permission; this script reads it and never fetches: it touches no network.
A total return is R(T, h) = AdjClose(T + h months) / AdjClose(T) - 1, the same for SPY; an observation is the last close on or
before the date, within MAX_PRICE_GAP_DAYS (7), else missing. A name with no price at T is left out and counted. A name with a
price at T and none at T + h is NOT dropped: each statistic is reported three ways - the names with both prices only (the
"excluded" arm), and with those names counted as a total loss (R = -100%, the "low" bound) or as exactly SPY's return (excess
0%, the "high" bound). The file's close is used for one check only: a ledger row whose price differs from the file's close on its
price_date by more than PRICE_CHECK_PCT is counted (price_mismatch), never dropped. yfinance's Close is adjusted for SPLITS (not for
dividends) as of the day it was fetched, while the ledger's price is the quote of its own day: the check therefore multiplies the file's
close by the product of the `stock_splits` ratios of the splits dated AFTER the price's date (a 4-for-1 is 4.0, a 1-for-10 reverse
split 0.1; a zero or empty cell is no split), so a split between the snapshot and the fetch is not counted as a mismatch.

Cohort: every snapshot date T with acceptance <= T and T + h months <= asof (asof defaults to acceptance + h months), and
only the rows of the pre-registered revision (--revision, default 18); the rows of any other revision are reported separately
under "other_revisions" and never mixed in. On each such date, over the names whose reference is printed (status used or
outside the fence) with V/P > 0 and a price at the start:
  * rho: the Spearman rank correlation (ties averaged) between V/P and R;
  * the average performer's V/P: the median V/P of the names whose R lies in the 40th to 60th percentile of R (inclusive),
    averaged over dates as exp(mean ln);
  * buy lift: the share of V/P >= 1.3 names that beat SPY, less the share of all that beat it, in points; avoid lift: V/P <= 0.7,
    on underperformance. A date with fewer than 30 calls is flagged thin and still counts; a date with no calls is left out of
    the average and counted.
Reported for all names and, when --untouched-list is given, split into the untouched names and the rest (the book; the list is
never in the ledger). Each is also split by status - the names whose reference is "used" and those outside the fence - in
"status_split". The output carries aggregates only: no ticker is printed and none is written.
"""
from __future__ import annotations

import argparse
import bisect
import calendar
import csv
import hashlib
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference_ledger as rl  # noqa: E402

BUY, AVOID = 1.3, 0.7
THIN = 30
MAX_PRICE_GAP_DAYS = 7
PRINTED = ("used", "outside_fence_above", "outside_fence_below")
REVISION = 18
PRICE_CHECK_PCT = 2.0
STATUS_SPLIT = {"used": ("used",), "outside_fence": ("outside_fence_above", "outside_fence_below")}


# ---- the backtest's metrics (verbatim from backtest_phase2/metrics.py @ 40cb5cf) ------------------------------------

def rankdata_avg(x):
    """Ranks 1..n, ties given the average of the ranks they span."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    xs = x[order]
    i = 0
    n = len(x)
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if len(x) < 3:
        return float("nan")
    rx, ry = rankdata_avg(x), rankdata_avg(y)
    sx, sy = rx.std(), ry.std()
    if sx == 0.0 or sy == 0.0:
        return float("nan")
    return float(((rx - rx.mean()) * (ry - ry.mean())).mean() / (sx * sy))


def apv_median(vp, r, lo=40.0, hi=60.0):
    """The median V/P among the names whose R lies between the lo-th and hi-th percentile of R (inclusive).  nan when none."""
    vp, r = np.asarray(vp, dtype=float), np.asarray(r, dtype=float)
    if len(r) == 0:
        return float("nan")
    p_lo, p_hi = np.percentile(r, [lo, hi])
    sel = (r >= p_lo) & (r <= p_hi)
    return float(np.median(vp[sel])) if sel.any() else float("nan")


def apv(medians):
    """APV = exp(mean over dates of ln(median)); dates with an undefined or non-positive median are left out."""
    m = [x for x in medians if x == x and x > 0]
    return float(math.exp(sum(math.log(x) for x in m) / len(m))) if m else float("nan")


def call_lift(vp, r, r_spy, buy=True):
    """(lift in points, number of calls).  buy: V/P >= 1.3 and the share that beat SPY, less the share of all names that beat it;
    avoid: V/P <= 0.7 and the share that underperformed SPY, less the share of all names that did.  nan when there are no calls."""
    vp, r = np.asarray(vp, dtype=float), np.asarray(r, dtype=float)
    hit = (r > r_spy) if buy else (r < r_spy)
    calls = (vp >= BUY) if buy else (vp <= AVOID)
    n = int(calls.sum())
    if n == 0 or len(r) == 0:
        return float("nan"), n
    return float((hit[calls].mean() - hit.mean()) * 100.0), n


# ---- prices and returns ---------------------------------------------------------------------------------------------

def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def load_prices(path, expect_sha256):
    """{ticker: (sorted list of date ordinals, list of adj_close, dict ordinal -> close, dict ordinal -> split ratio)} from a hashed
    date,ticker,close,adj_close,dividends,stock_splits CSV. Refuses (ValueError) a file whose sha256 differs from
    `expect_sha256`, or one with no adj_close or stock_splits column. A row with no usable positive adj_close is skipped; the close
    (yfinance's: adjusted for splits, not for dividends) is kept where it is a positive number, and a positive `stock_splits` cell is
    kept as that date's split ratio (the price check reads both; the total returns read adj_close, which contains them). The dividends
    column is carried for the operator's audit and is not read."""
    if hashlib.sha256(Path(path).read_bytes()).hexdigest().lower() != str(expect_sha256).strip().lower():
        raise ValueError("the prices file's sha256 differs from the expected value; it is not used")
    raw, closes, splits = {}, {}, {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        if not rd.fieldnames or any(c not in rd.fieldnames for c in ("date", "ticker", "adj_close", "stock_splits")):
            raise ValueError("the prices file needs the columns date, ticker, adj_close and stock_splits (and close, dividends)")
        for row in rd:
            try:
                d = date.fromisoformat(row["date"][:10])
                v = float(row["adj_close"])
            except (ValueError, KeyError, TypeError):
                continue
            if math.isfinite(v) and v > 0:
                t = row["ticker"].strip().upper()
                raw.setdefault(t, {})[d.toordinal()] = v
                try:
                    c = float(row.get("close"))
                except (ValueError, TypeError):
                    c = None
                if c is not None and math.isfinite(c) and c > 0:
                    closes.setdefault(t, {})[d.toordinal()] = c
                try:
                    sp = float(row.get("stock_splits"))
                except (ValueError, TypeError):
                    sp = None
                if sp is not None and math.isfinite(sp) and sp > 0:
                    splits.setdefault(t, {})[d.toordinal()] = sp
    out = {}
    for t, byd in raw.items():
        ords = sorted(byd)
        out[t] = (ords, [byd[o] for o in ords], closes.get(t, {}), splits.get(t, {}))
    return out


def split_factor_after(series, d):
    """The product of the split ratios of the splits dated after `d` (a split on `d` itself is already in that day's quote): the factor
    that takes a split-adjusted close of `d` back to the price quoted on `d`. 1.0 when there is none."""
    f = 1.0
    for o, ratio in series[3].items():
        if o > d.toordinal():
            f *= ratio
    return f


def price_on_or_before(series, d):
    """The last adj_close dated on or before `d` and no more than MAX_PRICE_GAP_DAYS earlier; else None."""
    if series is None:
        return None
    ords, vals = series[0], series[1]
    i = bisect.bisect_right(ords, d.toordinal()) - 1
    if i < 0 or d.toordinal() - ords[i] > MAX_PRICE_GAP_DAYS:
        return None
    return vals[i]


def total_return(series, d0, d1):
    a, b = price_on_or_before(series, d0), price_on_or_before(series, d1)
    return None if (a is None or b is None) else b / a - 1.0


# ---- the evaluation -------------------------------------------------------------------------------------------------

def _clean(x):
    """JSON-safe: nan and infinity become null; numpy scalars become Python numbers."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        x = x.item()
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


ARMS = ("excluded", "low", "high")


def _stats(vp, r, spy):
    """The date's statistics over the call lists `vp` (V/P) and `r` (total returns), against SPY's return `spy`."""
    vp, r = np.array(vp, dtype=float), np.array(r, dtype=float)
    out = {"n": int(len(r)), "rho": spearman(vp, r), "apv_median": apv_median(vp, r)}
    out["buy_lift"], out["buy_calls"] = call_lift(vp, r, spy, buy=True)
    out["avoid_lift"], out["avoid_calls"] = call_lift(vp, r, spy, buy=False)
    out["buy_thin"] = out["buy_calls"] < THIN
    out["avoid_thin"] = out["avoid_calls"] < THIN
    out["median_vp"] = float(np.median(vp)) if len(vp) else float("nan")
    return out


def _date_block(rows, prices, d0, horizon, statuses=PRINTED):
    """The statistics of one snapshot date's cross-section `rows` (ledger rows of one date, already group- and
    revision-filtered), over the names whose status is in `statuses`. Three arms: "excluded" (a name with no price at T + h is
    left out), "low" (it is counted at R = -100%) and "high" (it is counted at the return of SPY, 0% excess)."""
    d1 = add_months(d0, horizon)
    spy = total_return(prices.get("SPY"), d0, d1)
    vp, r, lost_vp = [], [], []
    not_valued = no_price_start = checked = mismatch = 0
    for row in rows:
        if row["price"] is not None and row["price_date"] is not None:
            series = prices.get(row["ticker"])
            pd0 = date.fromisoformat(row["price_date"])
            c = series[2].get(pd0.toordinal()) if series is not None else None
            if c is not None:
                checked += 1
                mismatch += int(abs(row["price"] / (c * split_factor_after(series, pd0)) - 1.0) * 100.0 > PRICE_CHECK_PCT)
        v = row["vp"]
        if row["reference_status"] not in statuses or v is None or not v > 0:
            not_valued += 1
            continue
        series = prices.get(row["ticker"])
        a, b = price_on_or_before(series, d0), price_on_or_before(series, d1)
        if a is None:
            no_price_start += 1
            continue
        if b is None:
            lost_vp.append(v)
            continue
        vp.append(v)
        r.append(b / a - 1.0)
    out = {"date": d0.isoformat(), "end_date": d1.isoformat(), "rows": len(rows), "not_valued": not_valued,
           "no_price_at_start": no_price_start, "no_price_at_end": len(lost_vp), "spy_return": spy,
           "price_checked": checked, "price_mismatch": mismatch}
    if spy is None:
        out["spy_missing"] = True
        return out
    out["excluded"] = _stats(vp, r, spy)
    out["low"] = _stats(vp + lost_vp, r + [-1.0] * len(lost_vp), spy)
    out["high"] = _stats(vp + lost_vp, r + [spy] * len(lost_vp), spy)
    return out


def _aggregate_arm(ok, arm):
    nan = float("nan")
    rhos = [p[arm]["rho"] for p in ok if p[arm]["rho"] == p[arm]["rho"]]
    blift = [p[arm]["buy_lift"] for p in ok if p[arm]["buy_lift"] == p[arm]["buy_lift"]]
    alift = [p[arm]["avoid_lift"] for p in ok if p[arm]["avoid_lift"] == p[arm]["avoid_lift"]]
    return {"rho_mean": float(np.mean(rhos)) if rhos else nan, "dates_without_rho": len(ok) - len(rhos),
            "APV": apv([p[arm]["apv_median"] for p in ok]),
            "buy_lift_mean": float(np.mean(blift)) if blift else nan,
            "dates_without_buy_calls": sum(1 for p in ok if p[arm]["buy_lift"] != p[arm]["buy_lift"]),
            "buy_thin_dates": sum(1 for p in ok if p[arm]["buy_thin"]),
            "avoid_lift_mean": float(np.mean(alift)) if alift else nan,
            "dates_without_avoid_calls": sum(1 for p in ok if p[arm]["avoid_lift"] != p[arm]["avoid_lift"]),
            "avoid_thin_dates": sum(1 for p in ok if p[arm]["avoid_thin"])}


def _aggregate(per):
    ok = [p for p in per if not p.get("spy_missing")]
    return {"dates": len(per), "dates_without_spy": len(per) - len(ok),
            "names_valued_at_start": sum(p["excluded"]["n"] + p["no_price_at_end"] for p in ok),
            "names_without_end_price": sum(p["no_price_at_end"] for p in ok),
            "names_without_start_price": sum(p["no_price_at_start"] for p in ok),
            "price_checked": sum(p["price_checked"] for p in per), "price_mismatch": sum(p["price_mismatch"] for p in per),
            **{arm: _aggregate_arm(ok, arm) for arm in ARMS}}


def _evaluate_rows(by_date, prices, horizon, untouched, with_dates=True):
    groups = {"all": lambda t: True}
    if untouched is not None:
        groups["untouched"] = lambda t: t in untouched
        groups["book"] = lambda t: t not in untouched
    res = {"groups": {}, "status_split": {}}
    for name, member in groups.items():
        sub = {d: [r for r in rows if member(r["ticker"])] for d, rows in by_date.items()}
        per = [p for p in (_date_block(sub[d], prices, d, horizon) for d in sorted(sub)) if p["rows"] > 0]
        res["groups"][name] = {"aggregate": _aggregate(per)}
        if with_dates:
            res["groups"][name]["per_date"] = per
        split = {}
        for label, statuses in STATUS_SPLIT.items():
            sper = [p for p in (_date_block(sub[d], prices, d, horizon, statuses) for d in sorted(sub)) if p["rows"] > 0]
            split[label] = {"rows": sum(1 for d in sub for r in sub[d] if r["reference_status"] in statuses),
                            "aggregate": _aggregate(sper)}
        res["status_split"][name] = split
    return res


def evaluate(ledger_rows, prices, acceptance, horizon, asof=None, untouched=None, revision=REVISION):
    """The result dict (aggregates only). `ledger_rows` are validated ledger rows; `prices` is load_prices' mapping. The cohort
    is the rows of `revision`; rows of any other revision are evaluated apart, under "other_revisions", never mixed in."""
    if horizon not in (12, 36):
        raise ValueError("the horizon is 12 or 36 months")
    asof = asof if asof is not None else add_months(acceptance, horizon)
    by_rev = {}
    for r in ledger_rows:
        d = date.fromisoformat(r["date"])
        if d >= acceptance and add_months(d, horizon) <= asof:
            by_rev.setdefault(r["revision"], {}).setdefault(d, []).append(r)
    mine = by_rev.get(revision, {})
    result = {"report_only": True, "note": "report only; no design change may rest on it in the first 12 months",
              "acceptance_date": acceptance.isoformat(), "asof": asof.isoformat(), "horizon_months": horizon,
              "revision": revision, "snapshot_dates": [d.isoformat() for d in sorted(mine)],
              "revisions": {str(k): sum(len(v) for v in by.values()) for k, by in sorted(by_rev.items())},
              "definitions": {"buy": BUY, "avoid": AVOID, "thin_below_calls": THIN, "max_price_gap_days": MAX_PRICE_GAP_DAYS,
                              "printed_statuses": list(PRINTED), "status_split": {k: list(v) for k, v in STATUS_SPLIT.items()},
                              "arms": {"excluded": "a name with no price at T + h is left out",
                                       "low": "it is counted at a return of -100%",
                                       "high": "it is counted at the return of SPY (0% excess)"}}}
    result.update(_evaluate_rows(mine, prices, horizon, untouched))
    result["other_revisions"] = {
        str(k): {"snapshot_dates": [d.isoformat() for d in sorted(by)], **_evaluate_rows(by, prices, horizon, untouched, False)}
        for k, by in sorted(by_rev.items()) if k != revision}
    return _clean(result)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Frozen forward-ledger evaluation (brief section 5.2). Report only. Offline.")
    ap.add_argument("--ledger", default=str(rl.DEFAULT_LEDGER))
    ap.add_argument("--prices", required=True)
    ap.add_argument("--prices-sha256", required=True, help="the prices file's sha256; the file is refused without a match")
    ap.add_argument("--revision", type=int, default=REVISION, help="the pack revision whose rows are evaluated (default 18)")
    ap.add_argument("--acceptance-date", required=True)
    ap.add_argument("--horizon", type=int, required=True, choices=(12, 36))
    ap.add_argument("--asof", default=None, help="evaluation date; default acceptance + horizon months")
    ap.add_argument("--untouched-list", default=None, help="split the result into the untouched names and the rest")
    ap.add_argument("--out", default=None, help="write the result here; refuses to overwrite (computed once per date)")
    args = ap.parse_args(argv)
    try:
        rows = rl.read_ledger(args.ledger)
        untouched = rl.load_untouched(args.untouched_list) if args.untouched_list else None
        res = evaluate(rows, load_prices(args.prices, args.prices_sha256), date.fromisoformat(args.acceptance_date),
                       args.horizon, date.fromisoformat(args.asof) if args.asof else None, untouched, args.revision)
    except (rl.LedgerSchemaError, FileNotFoundError, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    res["inputs"] = {"ledger_sha256": _sha256(args.ledger), "prices_sha256": _sha256(args.prices)}
    text = json.dumps(res, indent=1, allow_nan=False)
    if args.out:
        try:
            with open(args.out, "x", encoding="utf-8") as f:
                f.write(text + "\n")
        except FileExistsError:
            print(f"refused: {args.out} already exists (the evaluation is computed once per date)", file=sys.stderr)
            return 2
    print(text)
    return 0 if res["snapshot_dates"] else 3


if __name__ == "__main__":
    sys.exit(main())
