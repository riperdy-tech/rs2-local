"""The gate-1 run on the DEVELOPMENT dates (registration REGISTRATION_gate1_DRAFT.md; brief T-integrate).  Code only: no GPU, no model, no server, no network.

    python -m rebuild_harness.gate1_run --out-dir OUT [--dates 2019-12-31 2021-06-30] [--workers 8] [--limit-ciks N]

For each valuation date (default: the 16 quarter-ends 2019-03-31 .. 2022-12-31, Addendum H6) and each company in the id map it writes one record: the status of the
company (valued, or the named reason it was not), the engine's value per share with its P10..P90, the secondary and the disagreement, the discount rate and
its sources, the inputs at the prior's quantiles, the price and market cap, the five yardsticks, the outcomes and the fundamental outcomes.  A date is two
passes (see valuation/gate1.py): prepare every company, measure the population context, value every company.

THE HOLDOUT LOCK comes first: `holdout.enforce` runs before any data is opened and refuses any 2023-2024 date unless a freeze file names this engine.  No
freeze file exists or is created here.

PRICES (Addendum H9).  The development price source is the operator-approved raw monthly pull of 2026-10-01 (`data/priors/_inputs/prices_monthly_raw.json`:
Yahoo month-end bars with `auto_adjust=False`: the split-adjusted Close, Adj Close, dividends and the split events; today's listings only).  The traded unadjusted
close is rebuilt as Close x the product of the splits dated later (MonthlyRawPriceSource).  Month-end, survivors only, spin-off adjustments (Yahoo folds them into
Close) are not undone, quality UNVERIFIED: every record is stamped `raw_monthly_2026-10-01_survivors` (PRICE_STAMP, with the file's sha256 in run_meta.json) and every
B1-B4 figure computed on it is PROVISIONAL.  (Addendum G's premise that only an adjusted file existed was wrong.)  The holdout needs raw daily closes (D5).
Valuation dates are calendar quarter-ends and the price of a date is its month's closing bar (the last weekday of the month).

The 16:00 ET acceptance rule is applied through the layer: with no acceptance timestamp in this build, a filing is eligible when filed on an earlier date
(a filing on the date itself is AMBIGUOUS and unused).
"""
import argparse
import gzip
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime
from multiprocessing import Pool
from pathlib import Path

from valuation import gate1, pit_adapter
from valuation import pit_data as pdm
from valuation.common import sha256_file
from valuation.discount_rate import DamodaranStore, MriRiskFree
from valuation.priors import PopulationPriors
from . import engines as eng_mod
from . import fundamentals, holdout, outcomes

HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
STOCKS = Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks"))
WORKSPACE = STOCKS / "stocks-workspace"
SMOKE = WORKSPACE / "scratch" / "rev23" / "harness_smoke"
INPUTS = WORKSPACE / "data" / "priors" / "_inputs"
DEFAULT_STORE = SMOKE / "store_all"
DEFAULT_IDMAP = SMOKE / "sample_id_map.json"
DEFAULT_PRICES = INPUTS / "prices_monthly_raw.json"
DEFAULT_SIC = INPUTS / "sic_by_cik.json"
HORIZONS = (3, 6, 12, 24, 36)
KS = (1, 2, 3)
PRICE_STAMP = "raw_monthly_2026-10-01_survivors"

GATE1_FILES = [REPO / "valuation" / n for n in ("common.py", "classification.py", "discount_rate.py", "engine_operating.py", "engine_financial.py",
                                                  "engine_commodity.py", "priors.py", "priors_interface.py", "pit_adapter.py", "gate1.py")]


@eng_mod.engine("gate1_engine", kind="value", files=GATE1_FILES)
def gate1_engine(ticker, asof, data_root):
    """Registered so the holdout lock has an identity to freeze.  The engine values a whole date (it needs the date's population context): use `run_date`."""
    raise RuntimeError("gate1_engine values a whole valuation date; run rebuild_harness.gate1_run")


DEV_FIRST_YEAR, DEV_LAST_YEAR = 2019, 2022
OUTCOMES_END = date(2022, 12, 31)       # Addendum H6: no price outcome is formed past this date, so none reaches the 2023-2024 holdout years


def dev_dates():
    """The 16 quarter-ends from 2019-03-31 to 2022-12-31 (Addendum H6): 2019-03-31 .. 2021-12-31 (12 dates) serve the return metrics, 2022 (4 dates) forecast quality
    (B4) only.  History starts with fiscal year 2009 and the priors need years behind and ahead, so 2017 and 2018 hold nothing to value."""
    out = []
    for y in range(DEV_FIRST_YEAR, DEV_LAST_YEAR + 1):
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            out.append(date(y, m, d).isoformat())
    return out


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o


# ---- the worker ----------------------------------------------------------------------------------------------------------------------

_ENV = {}


def _init(cfg):
    from . import run_harness
    run_harness.block_network()
    idm = json.loads(Path(cfg["id_map"]).read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    sic = pit_adapter.CurrentSicFile(cfg["sic"])
    src = pdm.MonthlyRawPriceSource.load(cfg["prices"])
    _ENV["pit"] = pdm.PitData(cfg["store"], price_source=src, id_map=idm, sic_source=sic)
    _ENV["priors"] = PopulationPriors(cfg.get("priors_dir"))
    _ENV["rates"] = gate1.Rates(DamodaranStore(), cfg["rf"])
    _ENV["cfg"] = cfg


def _best_ticker(pit, cik, d):
    """Of a company's tickers (share classes), the one with the largest market cap on the date (any with a price when none has a determinable cap)."""
    cands = pit.tickers_for(cik) or [None]
    mcs = [(t, pit.market_cap(cik, d, t)) for t in cands]
    mcs.sort(key=lambda x: (x[1]["market_cap"] is not None, x[1]["market_cap"] or 0.0, x[1]["price"] is not None), reverse=True)
    return mcs[0][0], mcs[0][1], len(cands) - 1


def months_after(d, h):
    y, m = divmod(pdm.to_date(d).month - 1 + h, 12)
    y += pdm.to_date(d).year
    return date(y, m + 1, 1)


def _attach_outcomes(rec, pit, cik, key, d, snap):
    hz = tuple(h for h in HORIZONS if months_after(d, h) <= OUTCOMES_END)            # only horizons that end inside the development years (Addendum H6)
    ho = outcomes.horizon_outcomes(pit, key, d, hz) if (key and hz) else {h: {"available": False, "status": outcomes.UNOBSERVABLE} for h in hz}
    rec["excess"], rec["ret"], rec["bounds"], rec["outcome_status"] = {}, {}, {}, {}
    for h, o in ho.items():
        rec["excess"][h], rec["ret"][h], rec["bounds"][h] = o.get("excess"), o.get("ret"), o.get("bounds")
        rec["outcome_status"][h] = o["status"]
    row = snap.row_L()
    yrs = snap.rows()
    prev = yrs.get(max((y for y in yrs if y < snap.L), default=-1))
    dct = snap.years[snap.L_fye].cells.get("debt_current")
    rec["base"] = fundamentals.measures(row, prev, dct.tag if dct is not None else None)
    fo = outcomes.fundamental_outcomes(pit, cik, snap.L_fye, KS)
    rec["out"] = {k: (v["measures"] if v else None) for k, v in fo.items()}


def run_date(d, ciks=None):
    """One valuation date: prepare, measure the population, value.  Returns (records, context summary)."""
    t0 = time.time()
    pit, priors, rates, cfg = _ENV["pit"], _ENV["priors"], _ENV["rates"], _ENV["cfg"]
    ciks = ciks if ciks is not None else cfg["ciks"]
    rf = rates.rf(d)[0]
    recs, preps = [], {}
    counts = Counter()
    prev = None
    for cik in ciks:
        if prev is not None:
            pit.evict(prev)
        prev = cik
        snap = pit.snapshot(cik, d)
        rec = {"date": d, "cik": cik, "ticker": None, "industry": None, "sector": None, "family": None, "status": None, "reasons": [], "stamps": [],
               "price_stamp": PRICE_STAMP, "price": None, "price_adj": None, "market_cap": None, "shares": None, "mcap_group": None,
               "price_quality": None, "price_flags": [], "base_fye": None, "base_age_months": None, "score": {}, "val": None}
        if snap is None or not snap.years:
            rec["status"], rec["reasons"] = "refused", ["no_annual_report_at_decision_time"]
            recs.append(rec)
            continue
        key, mc, n_dup = _best_ticker(pit, cik, d)
        rec["ticker"] = key
        comp = pit.company(cik)
        rec["name_current_dated"] = None if comp is None else comp.name         # the store's name is today's EDGAR name: for reading the diagnostics only
        rec["share_class_duplicates"] = n_dup
        rec["base_fye"] = snap.L_fye
        rec["base_age_months"] = (pdm.to_date(d) - pdm.to_date(snap.L_fye)).days / 30.4375
        rec["price"], rec["price_flags"], rec["price_quality"] = mc["price"], list(mc["flags"]), mc.get("price_quality")
        rec["market_cap"], rec["shares"] = mc["market_cap"], mc["shares"]
        if mc["price"] is None:
            rec["status"], rec["reasons"] = "refused", ["no_price: " + str(mc["reason"])]
            recs.append(rec)
            continue
        adj = pit.price_source.adj_close(key, d) if key else None
        rec["price_adj"] = None if adj is None else adj.price
        if mc["market_cap"] is None:
            rec["status"], rec["reasons"] = "refused", ["market_cap_unavailable: " + str(mc["reason"])]
            recs.append(rec)
            continue
        rec["mcap_group"] = ">=300M" if mc["market_cap"] >= gate1.MCAP_FLOOR else "<300M"
        ar = pit_adapter.adapt(pit, cik, d, ticker=key)
        prep = gate1.prepare(ar)
        rec["industry"] = rec["sector"] = ar.industry
        rec["family"] = prep["family"]
        rec["stamps"] = list(prep["stamps"])
        rec["provenance"] = prep["provenance"]
        rec["family_reason"], rec["conflicts"], rec["sic"] = prep.get("family_reason"), prep.get("conflicts"), prep.get("sic")
        rec["classification_tests"] = prep.get("classification_tests")
        if prep["status"] != "prepared":
            rec["status"], rec["reasons"] = prep["status"], list(prep["reasons"])
            recs.append(rec)
            continue
        # yardsticks and outcomes need the company's layer objects: now, while it is loaded
        for name in eng_mod.YARDSTICKS:
            r = eng_mod.REGISTRY[name](key or f"CIK{cik}", d, pit)
            rec["score"][name] = r.get("score")
        _attach_outcomes(rec, pit, cik, key, d, snap)
        rec["status"] = "prepared"
        preps[cik] = prep
        recs.append(rec)
    if prev is not None:
        pit.evict(prev)
    ctx = gate1.DateContext.build(d, rf, [p for p in preps.values()])
    t1 = time.time()
    for rec in recs:
        if rec["status"] != "prepared":
            continue
        prep = preps[rec["cik"]]
        v = gate1.value_company(prep, ctx, priors, rates, rec["shares"], n_draws=cfg.get("n_draws", gate1.N_DRAWS))
        rec["val"] = v
        rec["stamps"] = sorted(set(rec["stamps"]) | set(v.get("stamps", [])))
        if v["status"] == "ok":
            rec["status"] = "valued"
            p50 = v["iv_ps"]["p50"]
            rec["score"]["gate1_engine"] = p50 / rec["price"]
        else:
            rec["status"], rec["reasons"] = "refused", list(v["reasons"])
    for rec in recs:
        counts[rec["status"]] += 1
    summary = {"date": d, "rf": rf, "n_companies": len(ciks), "status": dict(counts), "seconds_pass1": t1 - t0, "seconds_pass2": time.time() - t1,
               "de_p95_pooled": ctx.de_p95_pooled, "spread_pooled": ctx.spread_pooled, "n_industries_de": len(ctx.de_p95), "n_industries_spread": len(ctx.spread)}
    out_dir = Path(cfg["out_dir"])
    with gzip.open(out_dir / f"records_{d}.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(_clean(r)) + "\n")
    (out_dir / f"context_{d}.json").write_text(json.dumps(_clean(summary), indent=1), encoding="utf-8")
    pit.drop_cache()
    return summary


def _work(d):
    try:
        return run_date(d)
    except Exception as e:                     # a worker failure is stated, never papered over
        import traceback
        return {"date": d, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit-ciks", type=int)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--id-map", type=Path, default=DEFAULT_IDMAP)
    ap.add_argument("--prices", type=Path, default=DEFAULT_PRICES)
    ap.add_argument("--sic", type=Path, default=DEFAULT_SIC)
    ap.add_argument("--n-draws", type=int, default=gate1.N_DRAWS)
    ap.add_argument("--priors-dir", type=Path, help="the priors vintages folder (default: valuation.priors_build.config.DATA_DIR)")
    ap.add_argument("--freeze", type=Path)
    a = ap.parse_args(argv)
    dates = a.dates or dev_dates()
    lock = holdout.enforce(dates, [gate1_engine], a.freeze)       # FIRST: before any data is opened
    a.out_dir.mkdir(parents=True, exist_ok=True)
    idm = json.loads(a.id_map.read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    ciks = sorted(set(str(v).zfill(10) for v in idm.values()))
    if a.limit_ciks:
        ciks = ciks[:a.limit_ciks]
    rf_src = MriRiskFree()
    rf = {d: rf_src(d) for d in dates}                              # the dated FRED series, read once in the parent
    cfg = {"store": str(a.store), "id_map": str(a.id_map), "prices": str(a.prices), "sic": str(a.sic), "rf": rf, "ciks": ciks, "n_draws": a.n_draws,
           "out_dir": str(a.out_dir), "priors_dir": str(a.priors_dir) if a.priors_dir else None}
    meta = {"started": datetime.now().isoformat(timespec="seconds"), "dates": dates, "lock": lock, "n_ciks": len(ciks), "workers": a.workers,
            "n_draws": a.n_draws, "gate1_version": gate1.GATE1_VERSION, "price_stamp": PRICE_STAMP, "price_file": str(a.prices),
            "price_file_sha256": sha256_file(a.prices), "price_file_meta": json.loads(a.prices.read_text(encoding="utf-8")).get("meta"),
            "priors_dir": str(a.priors_dir) if a.priors_dir else None,
            "git_head": holdout._git(REPO, "rev-parse", "HEAD").decode().strip(), "rf": {k: v[0] for k, v in rf.items()}}
    (a.out_dir / "run_meta.json").write_text(json.dumps(_clean(meta), indent=1), encoding="utf-8")
    t0 = time.time()
    with Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool:
        for s in pool.imap_unordered(_work, dates):
            print(datetime.now().strftime("%H:%M"), f"{time.time() - t0:.0f}s", json.dumps(_clean(s))[:400], flush=True)
    print("done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
