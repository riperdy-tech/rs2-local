"""The forensic run (SPEC_rebuild Addendum U, Stage 1): the frozen gate-1 pipeline over 60 month-ends 2020-01-31 .. 2024-12-31, with the holdout freeze's inputs, instrumented AROUND the engine.

    python -m rebuild_harness.forensics.run --out-dir OUT [--dates ...] [--workers 3]

What is the registered pipeline and what is added:
  * `gate1_run.prepare_date`, `l1_date` and `gate1.value_company` are called unchanged (the engine, the priors, the discount rate, the ERP rule, the seeds and the draws are the freeze's).  The
    record of a name is the registered record (`val`, `score`, `excess`, `bounds`, ...), plus:
  * horizons 3, 6, 12, 18, 24, 36 months wherever the outcome date is on or before OUTCOMES_END (prices to 2026-10-06), formed by the same `outcomes.horizon_outcomes` and
    `survivorship.Survivorship.outcome` code, so the three survivorship bounds are formed exactly as in gate 1;
  * `fx_out`: the first-reported fundamentals of the fiscal years after the base year (OUTCOME data; read only by forensic tests);
  * `fx`: the forensic analytics (`analytics.analyze`) of every valued name of market cap >= $300M.
  * no ERP-shift variants are run (they are B5 diagnostics of gate 1, not needed here).
No valuation date after 2024-12-31 is accepted (2025-01 .. 2025-09 is the next, untouched holdout).  Nothing is written under valuation/.  CPU only, no network (run_harness.block_network)."""
import argparse
import gzip
import json
import sys
import time
from collections import Counter
from datetime import date, datetime
from multiprocessing import Pool
from pathlib import Path

from valuation import discount_rate as vdr
from valuation import engine_financial, engine_operating, gate1
from valuation import sic_crosswalk as sx
from valuation.discount_rate import MriRiskFree
from rebuild_harness import delisting_inputs, gate1_run as g1r, holdout_inputs, survivorship
from . import analytics as A
from . import e5_v2 as E5

LAST_VALUATION_DATE = "2024-12-31"
OUTCOMES_END = date(2026, 10, 6)                         # the last price bar held
FX_HORIZONS = (3, 6, 12, 18, 24, 36)
KS_FX = 8
STOCKS = g1r.STOCKS
WORKSPACE = g1r.WORKSPACE
H = WORKSPACE / "scratch" / "rev23" / "gate1_holdout"
D = WORKSPACE / "data"
FREEZE_HEADERS = H / "run" / "headers_snapshot.csv"      # the file the freeze hashed (sha256 868d5a8e...)
FREEZE_SINCE = "2023-01-31"                               # the holdout's price-event window start (min of its dates)

_ORIG_ATTACH = g1r._attach_outcomes


def _attach_ext(rec, pit, cik, key, d, snap, horizons=g1r.HORIZONS, outcomes_end=g1r.OUTCOMES_END, survivor=None):
    """gate1_run's own `_attach_outcomes`, then the extended first-reported chain (OUTCOME data)."""
    _ORIG_ATTACH(rec, pit, cik, key, d, snap, horizons, outcomes_end, survivor=survivor)
    rec["fx_out"] = A.realised_chain(pit, cik, snap.L_fye, KS_FX)


def month_end_dates(first="2020-01-31", last=LAST_VALUATION_DATE):
    return [d for d in g1r.dev_dates() + holdout_inputs.holdout_dates() if first <= d <= last]


def ordered(dates):
    """Quarter-ends first, then the other months (so a partial run is still a balanced panel)."""
    first = [d for d in ("2024-12-31", "2023-03-31", "2020-03-31") if d in dates]       # a holdout date first: its records are compared with the stored holdout records
    q = [d for d in dates if int(d[5:7]) % 3 == 0 and d not in first]
    return first + q + [d for d in dates if d not in q and d not in first]


# ---- the worker -----------------------------------------------------------------------------------------------------------------------------

_FX = {}


def _set_delistings(src, events):
    src.delistings = events
    if hasattr(src, "daily"):
        src.daily.delistings = events


def _init(cfg):
    g1r._init(cfg)
    g1r._attach_outcomes = _attach_ext
    A.wrap_engines(gate1, engine_operating, engine_financial)
    _FX["events"] = {k: json.loads(Path(v).read_text(encoding="utf-8")) for k, v in cfg["price_events_by_window"].items()}
    _FX["cfg"] = cfg


def run_date_fx(d):
    """One valuation date: gate1_run's two passes with the analytics hooked into pass 2.  Writes records_{d}.jsonl.gz and context_{d}.json."""
    if d > LAST_VALUATION_DATE:
        raise RuntimeError(f"refused: {d} is after {LAST_VALUATION_DATE} (2025 is the untouched holdout)")
    pit, priors, rates, cfg = g1r._ENV["pit"], g1r._ENV["priors"], g1r._ENV["rates"], g1r._ENV["cfg"]
    out_dir = Path(cfg["out_dir"])
    if (out_dir / f"records_{d}.jsonl.gz").exists():
        return {"date": d, "skipped": "exists"}
    window = "holdout" if d >= "2023-01-01" else "dev"
    _set_delistings(pit.price_source, _FX["events"][window])
    rf = rates.rf(d)[0]
    t0 = time.time()
    recs, preps, ctx, _t0, t1 = g1r.prepare_date(d, cfg["ciks"])
    ce, _uni = g1r.l1_date(d, recs, preps, ctx, priors, rates, rf)
    t1b = time.time()
    pop = A.population_p50(recs, preps, ctx, priors, gate1.MCAP_FLOOR)
    t1c = time.time()
    counts = Counter()
    chain_ok = Counter()
    for rec in recs:
        if rec["status"] != "prepared":
            continue
        prep = preps[rec["cik"]]
        v = gate1.value_company(prep, ctx, priors, rates, rec["shares"], n_draws=cfg.get("n_draws", gate1.N_DRAWS))
        rec["val"] = v
        rec["stamps"] = sorted(set(rec["stamps"]) | set(v.get("stamps", [])))
        if v["status"] == "ok":
            rec["status"] = "valued"
            rec["score"]["gate1_engine"] = v["iv_ps"]["p50"] / rec["price"]
            if rec.get("mcap_group") == ">=300M":
                try:
                    rec["fx"] = A.analyze(A.CAP, rec, pop, rec["price"], rec["shares"])
                    chain_ok[str(rec["fx"].get("chain_matches_engine"))] += 1
                except Exception as e:                       # a failure of the instrumentation is stated on the record, never papered over
                    import traceback
                    rec["fx"] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
                    chain_ok["error"] += 1
                if cfg.get("e5_tables"):                     # Addendum AL.24: engine v2's oracle on the same information as v1's
                    try:
                        rec["e5"] = E5.values(A.CAP, rec, rec["shares"], _e5_table(cfg["e5_tables"], int(d[:4]) - 1), priors=priors)
                        if cfg.get("e5_dist"):               # AL.25 diagnostic: v2's full distribution beside v1's
                            v1eq = sorted((x[0] for x in A.CAP.draws), reverse=True)
                            rec["e5"]["v1_top1pct_share_of_mean"] = (sum(v1eq[:max(1, len(v1eq) // 100)]) / sum(v1eq)) if v1eq and sum(v1eq) > 0 else None
                            rec["e5"]["v1_top5pct_share_of_mean"] = (sum(v1eq[:max(1, len(v1eq) // 20)]) / sum(v1eq)) if v1eq and sum(v1eq) > 0 else None
                            if A.CAP.family == "operating" and A.CAP.draws:          # E8c (AL.27): v1's enterprise value P50 / P90 (explicit + terminal PV)
                                import numpy as _np
                                evs = _np.array([x[4] + x[1] for x in A.CAP.draws], dtype=float)
                                rec["e5"]["v1_ev_p50"], rec["e5"]["v1_ev_p90"] = float(_np.quantile(evs, 0.5)), float(_np.quantile(evs, 0.9))
                            rec["e5"]["v2_dist"] = E5.v2_distribution(A.CAP, _e5_table(cfg["e5_tables"], int(d[:4]) - 1), rec["shares"], priors=priors)
                            if cfg.get("e5_diag"):                   # AL.28 diagnostic only: option 1 applied on top (redundant once v2.0.2 is the engine)
                                gv = "growth" if A.CAP.family == "operating" else "tbvg"
                                rec["e5"]["v2_dist_winsor"] = E5.v2_distribution(A.CAP, _e5_table(cfg["e5_tables"], int(d[:4]) - 1), rec["shares"], winsor=gv, priors=priors)
                            if cfg.get("e5_tc_tables"):              # AL.29 diagnostic: fork 1's option, tails from the tag-consistent tables
                                tct = _e5_table(cfg["e5_tc_tables"], int(d[:4]) - 1)
                                if tct is not None:
                                    rec["e5"]["v2_dist_tctails"] = E5.v2_distribution(A.CAP, _e5_table(cfg["e5_tables"], int(d[:4]) - 1), rec["shares"], tc_table=tct, priors=priors)
                    except Exception as e:
                        import traceback
                        rec["e5"] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
        else:
            rec["status"], rec["reasons"] = "refused", list(v["reasons"])
        A.CAP.clear()
    for rec in recs:
        counts[rec["status"]] += 1
    summary = {"date": d, "rf": rf, "n_companies": len(cfg["ciks"]), "status": dict(counts), "seconds_pass1": t1 - t0, "seconds_erp": t1b - t1, "seconds_pop": t1c - t1b,
               "seconds_pass2": time.time() - t1c, "erp_basis": rates.erp_basis, "erp": (None if ce is None else ce.as_dict()), "chain_matches_engine": dict(chain_ok),
               "population_p50": {f: {k: list(v) for k, v in dd.items()} for f, dd in pop.items()}, "price_events_window": window}
    with gzip.open(out_dir / f"records_{d}.jsonl.gz.tmp", "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(g1r._clean(r)) + "\n")
    (out_dir / f"records_{d}.jsonl.gz.tmp").replace(out_dir / f"records_{d}.jsonl.gz")
    (out_dir / f"context_{d}.json").write_text(json.dumps(g1r._clean(summary), indent=1), encoding="utf-8")
    pit.drop_cache()
    return {k: summary[k] for k in ("date", "status", "seconds_pass1", "seconds_pass2", "chain_matches_engine")}


_E5_TABLES = {}


def _e5_table(root, vintage):
    """Engine v2's near-term table of `vintage` (AL.24: data/priors_v4_pit), loaded once per worker; None when it does not exist or is refused."""
    key = (str(root), vintage)                                       # keyed by folder too: the AL.29 diagnostic loads two table sets
    if key not in _E5_TABLES:
        from valuation import near_term as nt
        try:
            _E5_TABLES[key] = nt.load_table(root, vintage)
        except nt.NearTermRefusal:
            _E5_TABLES[key] = None
    return _E5_TABLES[key]


def _work(d):
    try:
        return run_date_fx(d)
    except Exception as e:
        import traceback
        return {"date": d, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def build_cfg(out_dir: Path, dates, limit_ciks=None, prices_daily=D / "prices_daily"):
    holdout_file = H / "gate1_freeze.json"
    fz = json.loads(holdout_file.read_text(encoding="utf-8"))
    ann = fz["annotations"]["run_arguments"]
    idm_path = Path(ann["id_map"])
    idm = json.loads(idm_path.read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    ciks = sorted(set(str(v).zfill(10) for v in idm.values()))
    if limit_ciks:
        ciks = ciks[:limit_ciks]
    rf_src = MriRiskFree()
    rf = {d: rf_src(d) for d in dates}
    idx = delisting_inputs.EventIndex(Path(ann["delisting_index"]))
    docs = delisting_inputs.DelistingDocs(Path(ann["delisting_docs"]))
    tk_of = {}
    for t, c in idm.items():
        tk_of.setdefault(str(c).zfill(10), []).append(t)
    tf = lambda c: tk_of.get(str(c).zfill(10), [])
    pe_by = {}
    reports = {}
    for window, since in (("holdout", FREEZE_SINCE), ("dev", "2020-01-31")):
        pe, rep = delisting_inputs.build_price_events(idx, docs, tf, since=since)
        p = out_dir / f"price_events_{window}.json"
        p.write_text(json.dumps(pe), encoding="utf-8")
        pe_by[window] = str(p)
        reports[window] = rep
    cfg = {"store": ann["store"], "id_map": ann["id_map"], "prices": ann["prices_monthly_fallback"], "sic": str(g1r.DEFAULT_SIC), "rf": rf, "ciks": ciks, "n_draws": gate1.N_DRAWS,
           "prices_daily": ann["prices_daily"], "price_stamp": g1r.DAILY_PRICE_STAMP, "strict_classification": True, "max_cached_tickers": 256,
           "price_events": pe_by["holdout"], "price_events_by_window": pe_by, "horizons": list(FX_HORIZONS), "outcomes_end": OUTCOMES_END.isoformat(),
           "return_dates_end": LAST_VALUATION_DATE, "out_dir": str(out_dir), "priors_dir": ann["priors_dir"], "invalid_draw_max": None, "headers": str(FREEZE_HEADERS),
           "crosswalk": ann["crosswalk"], "erp_shifts": [], "erp_basis": "engine_consistent", "prices_fallback": ann["prices_monthly_fallback"],
           "survivorship_cover": ann["survivorship_cover"], "delisting_index": ann["delisting_index"], "delisting_docs": ann["delisting_docs"]}
    return cfg, reports


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit-ciks", type=int)
    ap.add_argument("--priors-dir", type=Path, help="AK.51 item 1: the priors folder (default: gate 1's freeze, data/priors_v3)")
    ap.add_argument("--e5-tables", type=Path, help="Addendum AL.24: engine v2's near-term tables; adds rec['e5'] (the oracle on one information set)")
    ap.add_argument("--e5-dist", action="store_true", help="Addendum AL.25 diagnostic: also v2's full distribution per name (rec['e5']['v2_dist'])")
    ap.add_argument("--e5-diag", action="store_true", help="Addendum AL.28 diagnostic variants (not part of E8)")
    ap.add_argument("--e5-tc-tables", type=Path, help="Addendum AL.29 diagnostic: the tag-consistent near-term tables, for the tail-graft variant")
    a = ap.parse_args(argv)
    dates = ordered(a.dates or month_end_dates())
    bad = [d for d in dates if d > LAST_VALUATION_DATE]
    if bad:
        ap.error(f"refused: valuation dates after {LAST_VALUATION_DATE} are the untouched holdout: {bad}")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    cfg, reports = build_cfg(a.out_dir, dates, a.limit_ciks)
    if a.priors_dir:                                                # AK.51 item 1: the acceptance runs pin priors_v3_fy explicitly
        cfg["priors_dir"] = str(a.priors_dir)
    if a.e5_tables:
        cfg["e5_tables"] = str(a.e5_tables)
        (a.out_dir / "lineage.json").write_text(json.dumps(E5.lineage(cfg["priors_dir"], a.e5_tables, sorted({int(d[:4]) - 1 for d in dates}), g1r.REPO),
                                                           indent=1), encoding="utf-8")
    if a.e5_dist:
        cfg["e5_dist"] = True
    if a.e5_diag:
        cfg["e5_diag"] = True
    if a.e5_tc_tables:
        cfg["e5_tc_tables"] = str(a.e5_tc_tables)
    meta = {"started": datetime.now().isoformat(timespec="seconds"), "dates": dates, "workers": a.workers, "git_head": g1r.holdout._git(g1r.REPO, "rev-parse", "HEAD").decode().strip(),
            "engine_files_sha256": {p.relative_to(g1r.REPO).as_posix(): g1r.holdout.sha256_file(p) for p in g1r.GATE1_FILES}, "n_ciks": len(cfg["ciks"]),
            "price_event_reports": reports, "horizons": list(FX_HORIZONS), "outcomes_end": cfg["outcomes_end"], "freeze_sha256": g1r.sha256_file(H / "gate1_freeze.json")}
    (a.out_dir / "run_meta.json").write_text(json.dumps(g1r._clean(meta), indent=1, default=str), encoding="utf-8")
    t0 = time.time()
    with Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool:
        for s in pool.imap_unordered(_work, dates):
            print(datetime.now().strftime("%H:%M"), f"{time.time() - t0:.0f}s", json.dumps(g1r._clean(s))[:500], flush=True)
    print("done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
