"""Run the validation harness: valuation dates x companies x engines -> scores, outcomes, metrics.

    python -m rebuild_harness.run_harness --store-dir D --zip companyfacts.zip --id-map cik_map.json --prices prices.json --price-format monthly_raw
        --dates 2018-06-29 2020-06-30 --engines yardstick_earnings_yield ... --out-dir OUT [--freeze FREEZE.json] [--coverage-only]

Order of events (nothing is read before the lock has answered): the holdout lock; per date the universe and the point-in-time scores; the outcomes; the
metrics.  `coverage_only` scores every engine and checks only that the outcome bars EXIST - it forms no return and no fundamental outcome, and writes
counts, never a metric.  No network, no model, no GPU.

Annotate, never silently gate: the one filter, a base year older than `max_base_age_months` (15), is a visible parameter and its count is reported.
"""
import argparse
import gzip
import json
import socket
from collections import Counter, defaultdict
from pathlib import Path

from valuation.pit_data import PitData, MonthlyRawPriceSource, AdjustedOnlyMonthlySource, to_date
from . import engines as eng_mod
from . import fundamentals, holdout, metrics, outcomes


class _Blocked(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("Socket access blocked: the harness is offline")


def block_network():
    socket.socket = _Blocked


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o


def resolve_engines(engines):
    out = []
    for e in engines:
        if isinstance(e, str):
            if e not in eng_mod.REGISTRY:
                raise KeyError(f"unknown engine {e!r}; registered: {sorted(eng_mod.REGISTRY)}")
            e = eng_mod.REGISTRY[e]
        out.append(e)
    return out


def run(dates, ciks, engines, pit, out_dir, labels=None, family_fn=None, horizons=outcomes.HORIZONS, freeze_path=None, coverage_only=False,
        max_base_age_months=15, yardsticks=eng_mod.YARDSTICKS, ks=(1, 2, 3), allow_rerun=False, n_resamples=metrics.N_RESAMPLES,
        progress=None):
    """Run the harness; returns {"coverage": ..., "summary": ... or None, "records": n}.  See the module docstring."""
    dates = [str(d)[:10] for d in dates]
    engs = resolve_engines(engines)
    lock = holdout.enforce(dates, engs, freeze_path, allow_rerun=allow_rerun)           # first: before any data is opened
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = labels or {}
    names = [e.engine_name for e in engs]
    value_engines = [e.engine_name for e in engs if getattr(e, "engine_kind", "yardstick") == "value"]
    ys = [y for y in yardsticks if y in names]
    records, cov = [], {"mode": "coverage_only" if coverage_only else "full", "lock": lock, "price_basis": getattr(pit.price_source, "basis", None),
                        "max_base_age_months": max_base_age_months, "dates": {}}
    for d in dates:
        c = cov["dates"][d] = {"window": lock["windows"][d], "companies_offered": len(ciks), "engine_reasons": {n: Counter() for n in names},
                               "engine_scored": Counter(), "outcome_available": defaultdict(Counter), "fund_outcome_available": Counter(),
                               "price_flags": Counter(), "share_basis": Counter()}
        keep, why = pit.universe(d, ciks)
        c["universe_reasons"] = dict(why)
        c["with_annual_report"] = len(keep)
        c["excluded_stale_base_year"] = 0
        c["no_price_key_or_close"] = 0
        n_rec = 0
        for cik in keep:
            snap = pit.snapshot(cik, d)
            age = (to_date(d) - to_date(snap.L_fye)).days / 30.4375 if snap and snap.L_fye else None
            if age is None or age > max_base_age_months:
                c["excluded_stale_base_year"] += 1
                continue
            # a company with several tickers (share classes) is one row: the ticker with the largest market cap on the date (any with a price
            # if none has a determinable cap); the others are counted
            cands = pit.tickers_for(cik) or [None]
            mcs = [(t, pit.market_cap(cik, d, t)) for t in cands]
            mcs.sort(key=lambda x: (x[1]["market_cap"] is not None, x[1]["market_cap"] or 0.0, x[1]["price"] is not None), reverse=True)
            key, mc = mcs[0]
            c["share_class_duplicates"] = c.get("share_class_duplicates", 0) + (len(cands) - 1)
            for f in mc["flags"]:
                c["price_flags"][f] += 1
            if mc["price"] is None:
                c["no_price_key_or_close"] += 1
                continue
            c["share_basis"]["market_cap_ok" if mc["market_cap"] is not None else "market_cap_" + str(mc["reason"])] += 1
            rec = {"date": d, "cik": cik, "ticker": key, "sector": (labels.get(cik) or {}).get("sector"), "family": None, "price": mc["price"],
                   "market_cap": mc["market_cap"], "score": {}, "vp": {}, "excess": {}, "ret": {}, "base": None, "out": {}, "forecasts": {},
                   "stamps": {}}
            fam = None
            for e in engs:
                r = e(key or f"CIK{cik}", d, pit)
                sc = r.get("score")
                vps = r.get("value_per_share")
                if sc is None and vps is not None:
                    sc = vps / mc["price"]
                rec["score"][e.engine_name] = sc
                rec["vp"][e.engine_name] = (vps / mc["price"]) if (vps is not None and vps > 0 and mc["price"] > 0) else None
                if r.get("forecasts"):
                    rec["forecasts"][e.engine_name] = r["forecasts"]
                if r.get("stamps"):
                    rec["stamps"][e.engine_name] = r["stamps"]
                fam = fam or r.get("family")
                if sc is None:
                    c["engine_reasons"][e.engine_name][r.get("reason") or "none"] += 1
                else:
                    c["engine_scored"][e.engine_name] += 1
            rec["family"] = fam or (family_fn(cik, d) if family_fn else None) or (labels.get(cik) or {}).get("family") or "unclassified"
            ho = outcomes.horizon_outcomes(pit, key, d, horizons, coverage_only=coverage_only) if key else {h: {"available": False} for h in horizons}
            for h, o in ho.items():
                c["outcome_available"][str(h)]["available" if o["available"] else "missing"] += 1
                if not coverage_only:
                    rec["excess"][h], rec["ret"][h] = o.get("excess"), o.get("ret")
            if not coverage_only:
                row, prev = snap.row_L(), None
                yrs = snap.rows()
                prev = yrs.get(max((y for y in yrs if y < snap.L), default=-1))
                dct = snap.years[snap.L_fye].cells.get("debt_current")
                rec["base"] = fundamentals.measures(row, prev, dct.tag if dct is not None else None)
                fo = outcomes.fundamental_outcomes(pit, cik, snap.L_fye, ks)
                for k, v in fo.items():
                    rec["out"][k] = v["measures"] if v else None
                    c["fund_outcome_available"][str(k)] += int(v is not None)
            else:
                fo = outcomes.fundamental_outcomes(pit, cik, snap.L_fye, ks)
                for k, v in fo.items():
                    c["fund_outcome_available"][str(k)] += int(v is not None)
            records.append(rec)
            n_rec += 1
        c["records"] = n_rec
        pit.drop_cache()
        if progress:
            progress(d, c)
    cov = _clean(json.loads(json.dumps(cov, default=lambda o: dict(o) if isinstance(o, Counter) else str(o))))
    (out_dir / "coverage.json").write_text(json.dumps(cov, indent=1), encoding="utf-8")
    summary = None
    if not coverage_only:
        with gzip.open(out_dir / "records.jsonl.gz", "wt", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(_clean(r)) + "\n")
        summary = metrics.summarize(records, names, ys, horizons, value_engines=value_engines, ks=ks, n_resamples=n_resamples)
        (out_dir / "summary.json").write_text(json.dumps(_clean(summary), indent=1), encoding="utf-8")
    return {"coverage": cov, "summary": summary, "records": len(records)}


def _load_json(p):
    with open(p, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def main(argv=None):
    block_network()
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-dir", required=True, type=Path)
    ap.add_argument("--zip", type=Path)
    ap.add_argument("--id-map", required=True, type=Path, help="ticker -> CIK ({'map': {...}} or a flat mapping)")
    ap.add_argument("--prices", required=True, type=Path)
    ap.add_argument("--price-format", choices=["monthly_raw", "adjusted_proxy"], default="monthly_raw")
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--ciks", type=Path, help="JSON list of CIKs (default: every ticker in the id map)")
    ap.add_argument("--engines", nargs="+", default=list(eng_mod.YARDSTICKS))
    ap.add_argument("--labels", type=Path, help="JSON {cik: {sector, family}}")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--freeze", type=Path)
    ap.add_argument("--coverage-only", action="store_true")
    ap.add_argument("--max-base-age-months", type=float, default=15)
    a = ap.parse_args(argv)
    raw = _load_json(a.id_map)
    idm = raw.get("map", raw)
    src = (MonthlyRawPriceSource if a.price_format == "monthly_raw" else AdjustedOnlyMonthlySource).load(a.prices)
    pit = PitData(a.store_dir, zip_path=a.zip, price_source=src, id_map=idm)
    ciks = _load_json(a.ciks) if a.ciks else sorted(set(pit.id_map.values()))
    labels = _load_json(a.labels) if a.labels else None
    res = run(a.dates, ciks, a.engines, pit, a.out_dir, labels=labels, freeze_path=a.freeze, coverage_only=a.coverage_only,
              max_base_age_months=a.max_base_age_months)
    print("records", res["records"])


if __name__ == "__main__":
    main()
