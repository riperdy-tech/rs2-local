"""Survival observations (Addendum V2): the point-in-time solvency items of every name of market cap (or, for the census, public float) of at least $300M at a quarter-end, WITHOUT valuing it.

    python -m rebuild_harness.stage2.obs --out-dir OUT --dates 2019-12-31 2019-09-30 ... [--workers 3] [--limit-ciks N]

It is the registered gate-1 pass 1 (`gate1_run.prepare_date`: the same companies, the same prices, the same strict SIC as filed, the same census of the companies that left, the same classification and the same
state) with the two things a survival model does not need switched off: the five yardsticks and the outcomes (no return, no fundamental outcome is formed).  For each prepared name of at least $300M the
record holds the items of `forensics.analytics.solvency_inputs` (the same function the forensic panel's `sv_*` columns come from).  Resumable: a date whose file exists is skipped.  CPU only, no network.

Training universe (stated): market cap >= $300M, because below it the price file holds survivors only and the census (the companies that left) exists only above the $300M public-float floor, so the failures
of smaller companies are not observable and a model trained on them would see almost no failures."""
import argparse
import gzip
import json
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

from valuation import gate1
from valuation.common import build_state
from valuation.discount_rate import MriRiskFree
from rebuild_harness import gate1_run as g1r
from rebuild_harness.forensics import analytics as A

WORKSPACE = g1r.WORKSPACE
D = WORKSPACE / "data"
H = WORKSPACE / "scratch" / "rev23" / "gate1_holdout"
FREEZE_HEADERS = H / "run" / "headers_snapshot.csv"
FLOOR = gate1.MCAP_FLOOR


def quarter_ends(first_year, last_year):
    return [g1r.month_end(y, m) for y in range(first_year, last_year + 1) for m in (3, 6, 9, 12)]


def build_cfg(out_dir: Path, dates, limit_ciks=None):
    fz = json.loads((H / "gate1_freeze.json").read_text(encoding="utf-8"))
    ann = fz["annotations"]["run_arguments"]
    idm = json.loads(Path(ann["id_map"]).read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    ciks = sorted(set(str(v).zfill(10) for v in idm.values()))
    if limit_ciks:
        ciks = ciks[:limit_ciks]
    rf_src = MriRiskFree()
    rf = {d: rf_src(d) for d in dates}
    return {"store": ann["store"], "id_map": ann["id_map"], "prices": ann["prices_monthly_fallback"], "sic": str(g1r.DEFAULT_SIC), "rf": rf, "ciks": ciks, "n_draws": gate1.N_DRAWS,
            "prices_daily": ann["prices_daily"], "price_stamp": g1r.DAILY_PRICE_STAMP, "strict_classification": True, "max_cached_tickers": 256, "price_events": None,
            "horizons": [], "outcomes_end": "2026-10-06", "return_dates_end": dates[-1] if dates else None, "out_dir": str(out_dir), "priors_dir": ann["priors_dir"], "invalid_draw_max": None,
            "headers": str(FREEZE_HEADERS), "crosswalk": ann["crosswalk"], "erp_shifts": [], "erp_basis": "engine_consistent", "prices_fallback": ann["prices_monthly_fallback"],
            "survivorship_cover": ann["survivorship_cover"], "delisting_index": ann["delisting_index"], "delisting_docs": ann["delisting_docs"]}


def _init(cfg):
    g1r._init(cfg)


def prepare_light(d, ciks):
    """`gate1_run.prepare_date` up to the classification and the state (the same companies in the same order, the same census, price, market capitalisation, adaptation and `gate1.prepare`), keeping
    nothing of a name but the row of the survival model: no yardstick, no outcome, no packed company, no population context.  Memory is then that of one company at a time."""
    pit, cfg = g1r._ENV["pit"], g1r._ENV["cfg"]
    surv = g1r._ENV.get("surv")
    census = surv.items_by_cik(d, pit, cfg.get("survivorship_horizon_months", 12)) if surv is not None else {}
    if census:
        have = set(ciks)
        ciks = list(ciks) + sorted(c for c in census if c not in have)
    rows, n_status = [], {}
    prev = None
    for cik in ciks:
        if prev is not None:
            pit.evict(prev)
        prev = cik
        status = _one(d, cik, pit, census, rows)
        n_status[status] = n_status.get(status, 0) + 1
    if prev is not None:
        pit.evict(prev)
    return rows, n_status


def _one(d, cik, pit, census, rows):
    snap = pit.snapshot(cik, d)
    if snap is None or not snap.years:
        return "refused:no_annual_report"
    key, mc, _n_dup = g1r._best_ticker(pit, cik, d)
    item = census.get(cik)
    price, market_cap, shares = mc["price"], mc["market_cap"], mc["shares"]
    is_census = price is None and item is not None
    if is_census:                                             # Addendum M2: the price proxy, public float / shares outstanding of the latest cover before T
        if item["price_proxy"] is None:
            return "refused:no_price_proxy"
        price, market_cap, shares = item["price_proxy"], item["public_float"], item["shares"]
    if price is None:
        return "refused:no_price"
    if market_cap is None:
        return "refused:market_cap_unavailable"
    ar = g1r.pit_adapter.adapt(pit, cik, d, ticker=key)
    prep = gate1.prepare(ar)
    if prep["status"] != "prepared":
        return prep["status"]
    if market_cap < FLOOR:
        return "prepared_below_floor"
    p = ar.company
    st = build_state(p)
    rows.append({"date": d, "cik": cik, "ticker": key, "family": prep["family"], "industry": ar.industry, "mcap": market_cap, "price": price, "census": is_census,
                 "base_age_months": (g1r.pdm.to_date(d) - g1r.pdm.to_date(snap.L_fye)).days / 30.4375, "sv": A.solvency_inputs(p, st)})
    return "prepared"


def obs_date(d):
    cfg = g1r._ENV["cfg"]
    out_dir = Path(cfg["out_dir"])
    path = out_dir / f"obs_{d}.jsonl.gz"
    if path.exists():
        return {"date": d, "skipped": "exists"}
    pit = g1r._ENV["pit"]
    t0 = time.time()
    rows, n_status = prepare_light(d, cfg["ciks"])
    tmp = out_dir / f"obs_{d}.jsonl.gz.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(g1r._clean(r)) + "\n")
    tmp.replace(path)
    pit.drop_cache()
    return {"date": d, "rows": len(rows), "status": n_status, "seconds": round(time.time() - t0)}


def _work(d):
    try:
        return obs_date(d)
    except Exception as e:
        import traceback
        return {"date": d, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--first-year", type=int, default=2015)
    ap.add_argument("--last-year", type=int, default=2019)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit-ciks", type=int)
    a = ap.parse_args(argv)
    dates = a.dates or quarter_ends(a.first_year, a.last_year)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    cfg = build_cfg(a.out_dir, dates, a.limit_ciks)
    t0 = time.time()
    with Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool:
        for s in pool.imap_unordered(_work, dates):
            print(datetime.now().strftime("%H:%M"), f"{time.time() - t0:.0f}s", json.dumps(s)[:600], flush=True)
    print("done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
