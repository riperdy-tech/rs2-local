"""Backtest registration sections 6-8: a Look.  THE ONLY PLACE A RETURN IS BUILT.

  python -m backtest_phase2.run_look --look 1|2 --bt-root <SP\\backtest>

Refuses to run unless <bt-root>/AUTHORISED_LOOK_<n>.txt exists (look_gate.py); the gate is the first statement of main().  Look 1
computes every decisive and every report-only metric for the design dates (2016-2018), Look 2 for the validation dates
(2019-2023), once each.  `compute_look` is pure given the tables and the price book, so the tests drive it with synthetic ones.
"""
import argparse
import json
import math
import pickle
import socket
import sys
from pathlib import Path

import numpy as np

from . import metrics
from .common import DESIGN_YEARS, VALIDATION_YEARS, PriceBook, ym
from .look_gate import require_look

HORIZONS = (36, 12, 60)
HORIZON_12_FIRST_YEAR = 2017        # amendment A3: the 12-month report-only horizon covers 2017-2023 only


def _month_plus(year, months):
    idx = int(year) * 12 + 5 + months          # June is month index 5 within the year
    y, m0 = divmod(idx, 12)
    return f"{y:04d}-{m0 + 1:02d}"


def total_return(book, ticker, year, h):
    """AdjClose(T+h) / AdjClose(T) - 1, month-end to month-end; None when either bar is missing."""
    a0, a1 = book.adj_close(ticker, f"{year}-06"), book.adj_close(ticker, _month_plus(year, h))
    return None if a0 is None or a1 is None else a1 / a0 - 1.0


def paired(rows):
    """P(T): the names in U(T) with V_B > 0 and V_S > 0."""
    return [r for r in rows if r["in_U"] and r.get("V_B") is not None and r["V_B"] > 0 and r.get("V_S") is not None and r["V_S"] > 0]


def size_terciles(rows):
    caps = np.array([r["cap"] for r in rows], dtype=float)
    if len(caps) == 0:
        return []
    order = np.argsort(caps, kind="mergesort")
    t = np.empty(len(caps), dtype=int)
    t[order] = (np.arange(len(caps)) * 3) // len(caps)
    return list(t)


def date_table(rows, year, h, book):
    """The per-date arrays for horizon h on P(T) (names lacking a bar at T+h are dropped and counted)."""
    P = paired(rows)
    keep, rets = [], []
    for r in P:
        rt = total_return(book, r["ticker"], year, h)
        if rt is None:
            continue
        keep.append(r)
        rets.append(rt)
    spy = total_return(book, "SPY", year, h)
    return {"rows": keep, "r": np.array(rets, dtype=float), "r_spy": spy, "n_P": len(P), "n_missing_h": len(P) - len(keep)}


def compute_look(years, tables, book):
    """Every decisive and report-only metric for `years`.  tables: {year: [per-name dict]} with cik, ticker, price, cap, sector, in_U,
    V_B, V_S, V_a, V_b (per-share values or None) and oe_yield.  Returns a JSON-able dict (aggregates only: no company is named)."""
    out = {"years": list(years), "horizons": {}}
    for h in HORIZONS:
        ys = [y for y in years if book.adj_close("SPY", _month_plus(y, h)) is not None and (h != 12 or int(y) >= HORIZON_12_FIRST_YEAR)]
        if not ys:
            continue
        dts = {y: date_table(tables[y], y, h, book) for y in ys}
        arr = []
        comp = []
        for y in ys:
            d = dts[y]
            vp = lambda key: np.array([r[key] / r["price"] for r in d["rows"]], dtype=float)
            arr.append({"vp_B": vp("V_B"), "vp_S": vp("V_S"), "r": d["r"], "r_spy": d["r_spy"]})
            comp.append([r["cik"] for r in d["rows"]])
        per, agg = metrics.period_stats(arr)
        block = {"dates": ys, "n_P": [dts[y]["n_P"] for y in ys], "n_missing_h": [dts[y]["n_missing_h"] for y in ys],
                 "per_date": per, "agg": agg}
        if h == 36:
            block["bootstrap_90"] = metrics.cluster_bootstrap(arr, comp)
            rep = {}
            for name, key in (("naive", "oe_yield"), ("variant_a", "V_a"), ("variant_b", "V_b")):
                rhos, n_used, n_missing = [], [], []
                for y in ys:
                    d = dts[y]
                    use = [(r[key] / r["price"] if key != "oe_yield" else r[key], rt) for r, rt in zip(d["rows"], d["r"])
                           if r.get(key) is not None and (key == "oe_yield" or r[key] > 0)]
                    rhos.append(metrics.spearman([u[0] for u in use], [u[1] for u in use]) if use else float("nan"))
                    n_used.append(len(use))
                    n_missing.append(len(d["rows"]) - len(use))
                rep[name] = {"rho_per_date": rhos, "rho_mean": float(np.nanmean(rhos)), "n_used": n_used, "n_not_valued": n_missing}
            block["report_only_rho"] = rep
            block["quintile_excess"] = {arm: [metrics.quintile_excess(a["vp_" + arm], a["r"]) for a in arr] for arm in ("B", "S")}
            block["calibration"] = {arm: dict(zip(("lambda", "a", "vp_star", "n"),
                                                  metrics.calibration([a["vp_" + arm] for a in arr], [a["r"] for a in arr])))
                                    for arm in ("B", "S")}
            block["avoid_call_lift"] = {arm: [metrics.call_lift(a["vp_" + arm], a["r"], a["r_spy"], buy=False) for a in arr]
                                        for arm in ("B", "S")}
            by_sector, by_tercile = {}, {}
            for y, a in zip(ys, arr):
                rows = dts[y]["rows"]
                terc = size_terciles(rows)
                for grp, getter in ((by_sector, lambda i: rows[i].get("sector") or "unknown"), (by_tercile, lambda i: terc[i])):
                    keys = sorted({getter(i) for i in range(len(rows))}, key=str)
                    for k in keys:
                        ix = [i for i in range(len(rows)) if getter(i) == k]
                        if len(ix) < 10:
                            continue
                        rB = metrics.spearman(a["vp_B"][ix], a["r"][ix])
                        rS = metrics.spearman(a["vp_S"][ix], a["r"][ix])
                        grp.setdefault(str(k), []).append({"year": y, "n": len(ix), "rho_B": rB, "rho_S": rS, "dRho": rS - rB})
            block["by_sector"], block["by_size_tercile"] = by_sector, by_tercile
            # amendment A2 (report only): record depth, 5 or more revenue years in the 8-year window against fewer
            by_depth = {}
            for y, a in zip(ys, arr):
                rows = dts[y]["rows"]
                for label, test in (("5_or_more_revenue_years", lambda n: n >= 5), ("fewer_than_5_revenue_years", lambda n: n < 5)):
                    ix = [i for i, r in enumerate(rows) if r.get("rev_years") is not None and test(r["rev_years"])]
                    rB = metrics.spearman(a["vp_B"][ix], a["r"][ix]) if ix else float("nan")
                    rS = metrics.spearman(a["vp_S"][ix], a["r"][ix]) if ix else float("nan")
                    by_depth.setdefault(label, []).append({"year": y, "n": len(ix), "rho_B": rB, "rho_S": rS, "dRho": rS - rB})
            block["by_record_depth"] = by_depth
        out["horizons"][str(h)] = block
    return out


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(float(o))) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    return o


def load_tables(bt_root, years, skip_missing=False):
    """The pre-outcome per-name tables of the Look's dates.  A date the pre-outcome run did not value (no COE_mkt_B) has no table: that stops
    the Look unless the reviewer allows the date to be left out, in which case the omission is recorded in the result."""
    tables, missing = {}, []
    for y in years:
        p = Path(bt_root) / "out" / "prelook" / f"table_{y}.pkl"
        if not p.exists():
            missing.append(y)
            continue
        with open(p, "rb") as f:
            tables[y] = pickle.load(f)
    if missing and not skip_missing:
        raise FileNotFoundError(f"no pre-outcome table for {missing}: the date was not valued; pass --skip-missing-dates to leave it out")
    return tables, missing


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--look", type=int, required=True, choices=[1, 2])
    ap.add_argument("--bt-root", required=True, type=Path)
    ap.add_argument("--skip-missing-dates", action="store_true")
    a = ap.parse_args(argv)
    require_look(a.look, a.bt_root)               # the gate: nothing below runs without the reviewer's file
    years = DESIGN_YEARS if a.look == 1 else VALIDATION_YEARS
    book = PriceBook.load(a.bt_root / "prices" / "prices_monthly_raw.json")
    tables, missing = load_tables(a.bt_root, years, a.skip_missing_dates)
    years = tuple(y for y in years if y in tables)
    res = compute_look(years, tables, book)
    res["dates_not_run"] = missing
    outp = a.bt_root / "out" / f"look{a.look}_results.json"
    outp.write_text(json.dumps(_clean(res), indent=1), encoding="utf-8")
    print("wrote", outp)


if __name__ == "__main__":
    main()
