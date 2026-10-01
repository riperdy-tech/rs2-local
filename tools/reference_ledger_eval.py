"""The frozen evaluation of the forward ledger (revision 18, brief section 5.2). REPORT ONLY.

Run once at 12 months and once at 36 months after acceptance, with the backtest's definitions
(registration d09bb4a4, sections 4.3 and 7; the metric functions below are copied verbatim from the backtest harness's
metrics.py at commit 40cb5cf, because nothing imports across branches). No design change may rest on its output in the first
12 months.

  python tools/reference_ledger_eval.py --ledger <reference_ledger.jsonl> --prices <prices.csv> --acceptance-date YYYY-MM-DD
        --horizon {12,36} [--asof YYYY-MM-DD] [--untouched-list <path>] [--out <result.json>]

prices.csv: columns date, ticker, adj_close (one row per ticker per trading day; SPY included). The file is read, never
fetched: this script touches no network. A total return is R(T, h) = AdjClose(T + h months) / AdjClose(T) - 1, the same for SPY;
an observation is the last one on or before the date, within MAX_PRICE_GAP_DAYS.

Cohort: every snapshot date T with acceptance <= T and T + h months <= asof (asof defaults to acceptance + h months). On
each such date, over the names whose reference is printed (status used or outside the fence) with V/P > 0 and a price at both
ends:
  * rho: the Spearman rank correlation (ties averaged) between V/P and R;
  * the average performer's V/P: the median V/P of the names whose R lies in the 40th to 60th percentile of R (inclusive),
    averaged over dates as exp(mean ln);
  * buy lift: the share of V/P >= 1.3 names that beat SPY, less the share of all that beat it, in points; avoid lift: V/P <= 0.7,
    on underperformance. A date with fewer than 30 calls is flagged thin and still counts; a date with no calls is left out of
    the average and counted.
Reported for all names and, when --untouched-list is given, split into the untouched names and the rest (the book). The
output carries aggregates only: no ticker is printed and none is written.
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


def load_prices(path):
    """{ticker: (sorted list of date ordinals, list of adj_close)} from a date,ticker,adj_close CSV. A row with no usable
    positive adj_close is skipped."""
    raw = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                d = date.fromisoformat(row["date"][:10])
                v = float(row["adj_close"])
            except (ValueError, KeyError, TypeError):
                continue
            if math.isfinite(v) and v > 0:
                raw.setdefault(row["ticker"].strip().upper(), {})[d.toordinal()] = v
    out = {}
    for t, byd in raw.items():
        ords = sorted(byd)
        out[t] = (ords, [byd[o] for o in ords])
    return out


def price_on_or_before(series, d):
    """The last adj_close dated on or before `d` and no more than MAX_PRICE_GAP_DAYS earlier; else None."""
    if series is None:
        return None
    ords, vals = series
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


def _date_block(rows, prices, d0, horizon):
    """The statistics of one snapshot date's cross-section `rows` (ledger rows of one date, already group-filtered)."""
    d1 = add_months(d0, horizon)
    spy = total_return(prices.get("SPY"), d0, d1)
    vp, r = [], []
    not_valued = no_price = 0
    for row in rows:
        v = row["vp"]
        if row["reference_status"] not in PRINTED or v is None or not v > 0:
            not_valued += 1
            continue
        ret = total_return(prices.get(row["ticker"]), d0, d1)
        if ret is None:
            no_price += 1
            continue
        vp.append(v)
        r.append(ret)
    out = {"date": d0.isoformat(), "end_date": d1.isoformat(), "rows": len(rows), "not_valued": not_valued,
           "no_price": no_price, "n": len(r), "spy_return": spy}
    if spy is None:
        out["spy_missing"] = True
        return out
    vp, r = np.array(vp, dtype=float), np.array(r, dtype=float)
    out["rho"] = spearman(vp, r)
    out["apv_median"] = apv_median(vp, r)
    out["buy_lift"], out["buy_calls"] = call_lift(vp, r, spy, buy=True)
    out["avoid_lift"], out["avoid_calls"] = call_lift(vp, r, spy, buy=False)
    out["buy_thin"] = out["buy_calls"] < THIN
    out["avoid_thin"] = out["avoid_calls"] < THIN
    out["median_vp"] = float(np.median(vp)) if len(vp) else float("nan")
    return out


def _aggregate(per):
    ok = [p for p in per if not p.get("spy_missing")]
    nan = float("nan")
    rhos = [p["rho"] for p in ok if p["rho"] == p["rho"]]
    blift = [p["buy_lift"] for p in ok if p["buy_lift"] == p["buy_lift"]]
    alift = [p["avoid_lift"] for p in ok if p["avoid_lift"] == p["avoid_lift"]]
    return {"dates": len(per), "dates_without_spy": len(per) - len(ok),
            "rho_mean": float(np.mean(rhos)) if rhos else nan, "dates_without_rho": len(ok) - len(rhos),
            "APV": apv([p["apv_median"] for p in ok]),
            "buy_lift_mean": float(np.mean(blift)) if blift else nan,
            "dates_without_buy_calls": sum(1 for p in ok if p["buy_lift"] != p["buy_lift"]),
            "buy_thin_dates": sum(1 for p in ok if p["buy_thin"]),
            "avoid_lift_mean": float(np.mean(alift)) if alift else nan,
            "dates_without_avoid_calls": sum(1 for p in ok if p["avoid_lift"] != p["avoid_lift"]),
            "avoid_thin_dates": sum(1 for p in ok if p["avoid_thin"])}


def evaluate(ledger_rows, prices, acceptance, horizon, asof=None, untouched=None):
    """The result dict (aggregates only). `ledger_rows` are validated ledger rows; `prices` is load_prices' mapping."""
    if horizon not in (12, 36):
        raise ValueError("the horizon is 12 or 36 months")
    asof = asof if asof is not None else add_months(acceptance, horizon)
    by_date = {}
    for r in ledger_rows:
        d = date.fromisoformat(r["date"])
        if d >= acceptance and add_months(d, horizon) <= asof:
            by_date.setdefault(d, []).append(r)
    groups = {"all": lambda t: True}
    if untouched is not None:
        groups["untouched"] = lambda t: t in untouched
        groups["book"] = lambda t: t not in untouched
    result = {"report_only": True, "note": "report only; no design change may rest on it in the first 12 months",
              "acceptance_date": acceptance.isoformat(), "asof": asof.isoformat(), "horizon_months": horizon,
              "snapshot_dates": [d.isoformat() for d in sorted(by_date)],
              "revisions": {}, "definitions": {"buy": BUY, "avoid": AVOID, "thin_below_calls": THIN,
                                               "max_price_gap_days": MAX_PRICE_GAP_DAYS, "printed_statuses": list(PRINTED)},
              "groups": {}}
    for rows in by_date.values():
        for r in rows:
            result["revisions"][str(r["revision"])] = result["revisions"].get(str(r["revision"]), 0) + 1
    for name, member in groups.items():
        per = [_date_block([r for r in by_date[d] if member(r["ticker"])], prices, d, horizon) for d in sorted(by_date)]
        per = [p for p in per if p["rows"] > 0]
        result["groups"][name] = {"aggregate": _aggregate(per), "per_date": per}
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
    ap.add_argument("--acceptance-date", required=True)
    ap.add_argument("--horizon", type=int, required=True, choices=(12, 36))
    ap.add_argument("--asof", default=None, help="evaluation date; default acceptance + horizon months")
    ap.add_argument("--untouched-list", default=None, help="split the result into the untouched names and the rest")
    ap.add_argument("--out", default=None, help="write the result here; refuses to overwrite (computed once per date)")
    args = ap.parse_args(argv)
    try:
        rows = rl.read_ledger(args.ledger)
        untouched = rl.load_untouched(args.untouched_list) if args.untouched_list else None
        res = evaluate(rows, load_prices(args.prices), date.fromisoformat(args.acceptance_date), args.horizon,
                       date.fromisoformat(args.asof) if args.asof else None, untouched)
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
