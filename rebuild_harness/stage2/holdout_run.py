"""The gate-1b holdout run (REGISTRATION_gate1b.md): the frozen engine on the nine month-ends 2025-01-31 .. 2025-09-30, ONCE, with the forensic instrumentation (the draws' summary, the solvency items) so that
the Addendum-V layers can be formed from the records.

    python -m rebuild_harness.stage2.holdout_run --freeze FREEZE.json --out-dir OUT [--workers 2]

What it is: `gate1_run.prepare_date`, `l1_date` and `gate1.value_company` unchanged (the engine, priors vintage = year - 1 = 2024, the engine-consistent premium, the seeds and the draws are the freeze's), the
D5 daily raw prices with the monthly fallback, the strict SIC as filed, the census of the companies that left (the cover index) with the three survivorship bounds, 12-month outcomes from the next session's
open to 2026-10-06, and the first-reported fundamentals of the following fiscal years.  Added to each valued name of at least $300M: the forensic analytics (`forensics.analytics.analyze`), and the draw
summary under Damodaran's own equity premium (H4's variant).

THE LOCK.  Before anything is opened: the freeze file must exist, name this repository's HEAD as its code commit, list the engine files with the hashes they have on disk, and record the survival
coefficients of every date; the ledger next to it (`holdout_runs.jsonl`) must hold no earlier run of this freeze.  A line is appended when the run starts.  A resumable crash (a date whose records file is
missing) is re-run by calling again with `--resume`; a date whose records file exists is never run twice.
Nothing is written under valuation/.  CPU only, no network."""
import argparse
import gzip
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from multiprocessing import Pool
from pathlib import Path

from valuation import engine_financial, engine_operating, gate1
from valuation import discount_rate as vdr
from valuation.discount_rate import MriRiskFree
from rebuild_harness import delisting_inputs, gate1_run as g1r, holdout
from rebuild_harness.forensics import analytics as A

DATES = ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30", "2025-05-30", "2025-06-30", "2025-07-31", "2025-08-29", "2025-09-30"]
OUTCOMES_END = date(2026, 10, 6)
HORIZONS = (12,)                                        # the registered outcome; no other horizon is formed
KS_FX = 8
LEDGER_NAME = "holdout_runs.jsonl"
_ORIG_ATTACH = g1r._attach_outcomes
_ST = {}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def _attach_ext(rec, pit, cik, key, d, snap, horizons=g1r.HORIZONS, outcomes_end=g1r.OUTCOMES_END, survivor=None):
    _ORIG_ATTACH(rec, pit, cik, key, d, snap, horizons, outcomes_end, survivor=survivor)
    rec["fx_out"] = A.realised_chain(pit, cik, snap.L_fye, KS_FX)


def check_lock(freeze_path: Path, out_dir: Path, resume: bool) -> dict:
    """Refuse unless the freeze names this repository's HEAD and the engine files as they are, carries the survival coefficients of all nine dates, and the ledger holds no earlier run."""
    fz = json.loads(freeze_path.read_text(encoding="utf-8"))
    root = g1r.REPO
    head = holdout._git(root, "rev-parse", "HEAD").decode().strip()
    if fz["contents"]["code_commit"] != head:
        raise holdout.HoldoutRefused(f"the freeze names code commit {fz['contents']['code_commit']}, this repository is at {head}")
    ent = fz["engines"]["gate1_engine"]
    for rel, want in ent["files"].items():
        have = holdout.sha256_file(root / rel)
        if have != want:
            raise holdout.HoldoutRefused(f"{rel} has sha256 {have}, the freeze says {want}: the engine changed after the freeze")
    sc = (fz.get("stage2") or {}).get("survival_coefficients") or {}
    miss = [d for d in DATES if d not in sc]
    if miss:
        raise holdout.HoldoutRefused(f"the freeze lacks the survival coefficients of {miss}")
    ledger = freeze_path.with_name(LEDGER_NAME)
    fsha = holdout.sha256_file(freeze_path)
    seen = []
    if ledger.is_file():
        seen = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
    if any(j["freeze_sha256"] == fsha for j in seen) and not resume:
        raise holdout.HoldoutRefused("this freeze has already been run (the holdout is run once): refused; --resume only completes the dates whose records are missing")
    return {"freeze": fz, "freeze_sha256": fsha, "ledger": ledger, "already_started": any(j["freeze_sha256"] == fsha for j in seen)}


def build_cfg(freeze: dict, out_dir: Path):
    ann = freeze["annotations"]["run_arguments"]
    idm = json.loads(Path(ann["id_map"]).read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    ciks = sorted(set(str(v).zfill(10) for v in idm.values()))
    rf_src = MriRiskFree()
    rf = {d: rf_src(d) for d in DATES}
    idx = delisting_inputs.EventIndex(Path(ann["delisting_index"]))
    docs = delisting_inputs.DelistingDocs(Path(ann["delisting_docs"]))
    tk_of = {}
    for t, c in idm.items():
        tk_of.setdefault(str(c).zfill(10), []).append(t)
    pe, rep = delisting_inputs.build_price_events(idx, docs, lambda c: tk_of.get(str(c).zfill(10), []), since=DATES[0])
    p = out_dir / "price_events.json"
    p.write_text(json.dumps(pe), encoding="utf-8")
    headers_copy = out_dir / "headers_snapshot.csv"
    if not headers_copy.exists():
        headers_copy.write_bytes(Path(ann["headers"]).read_bytes())
    cfg = {"store": ann["store"], "id_map": ann["id_map"], "prices": ann["prices_monthly_fallback"], "sic": str(g1r.DEFAULT_SIC), "rf": rf, "ciks": ciks, "n_draws": gate1.N_DRAWS,
           "prices_daily": ann["prices_daily"], "price_stamp": g1r.DAILY_PRICE_STAMP, "strict_classification": True, "max_cached_tickers": 256, "price_events": str(p),
           "horizons": list(HORIZONS), "outcomes_end": OUTCOMES_END.isoformat(), "return_dates_end": DATES[-1], "out_dir": str(out_dir), "priors_dir": ann["priors_dir"], "invalid_draw_max": None,
           "headers": str(headers_copy), "crosswalk": ann["crosswalk"], "erp_shifts": [], "erp_basis": "engine_consistent", "prices_fallback": ann["prices_monthly_fallback"],
           "survivorship_cover": ann["survivorship_cover"], "delisting_index": ann["delisting_index"], "delisting_docs": ann["delisting_docs"]}
    return cfg, rep


def _init(cfg):
    g1r._init(cfg)
    g1r._attach_outcomes = _attach_ext
    A.wrap_engines(gate1, engine_operating, engine_financial)


def run_date(d):
    """One date: gate1_run's two passes with the analytics hooked into pass 2, then the draw summary under Damodaran's own premium for the names of at least $300M."""
    if d not in DATES:
        raise RuntimeError(f"refused: {d} is not one of the registered holdout dates")
    pit, priors, rates, cfg = g1r._ENV["pit"], g1r._ENV["priors"], g1r._ENV["rates"], g1r._ENV["cfg"]
    out_dir = Path(cfg["out_dir"])
    if (out_dir / f"records_{d}.jsonl.gz").exists():
        return {"date": d, "skipped": "exists"}
    pe = json.loads(Path(cfg["price_events"]).read_text(encoding="utf-8"))
    src = pit.price_source
    src.delistings = pe
    if hasattr(src, "daily"):
        src.daily.delistings = pe
    rf = rates.rf(d)[0]
    t0 = time.time()
    recs, preps, ctx, _t0, t1 = g1r.prepare_date(d, cfg["ciks"])
    ce, _uni = g1r.l1_date(d, recs, preps, ctx, priors, rates, rf)
    t1b = time.time()
    pop = A.population_p50(recs, preps, ctx, priors, gate1.MCAP_FLOOR)
    t1c = time.time()
    counts, chain_ok = Counter(), Counter()
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
                except Exception as e:
                    import traceback
                    rec["fx"] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
                    chain_ok["error"] += 1
        else:
            rec["status"], rec["reasons"] = "refused", list(v["reasons"])
        A.CAP.clear()
    t2 = time.time()
    dam = g1r.DamodaranErp(rates)                                           # H4: the same names and draws under Damodaran's own premium (the sensitivity of Addendum M)
    for rec in recs:
        if rec["status"] != "valued" or rec.get("mcap_group") != ">=300M":
            continue
        va = gate1.value_company(preps[rec["cik"]], ctx, priors, dam, rec["shares"], n_draws=cfg.get("n_draws", gate1.N_DRAWS))
        rec["fx_dam"] = A.draw_summary(A.CAP.draws, rec["shares"], rec["price"]) if va["status"] == "ok" else None
        A.CAP.clear()
    for rec in recs:
        counts[rec["status"]] += 1
    summary = {"date": d, "rf": rf, "n_companies": len(cfg["ciks"]), "status": dict(counts), "seconds_pass1": t1 - t0, "seconds_erp": t1b - t1, "seconds_pop": t1c - t1b, "seconds_pass2": t2 - t1c,
               "seconds_damodaran_variant": time.time() - t2, "erp_basis": rates.erp_basis, "erp": (None if ce is None else ce.as_dict()), "chain_matches_engine": dict(chain_ok),
               "population_p50": {f: {k: list(v) for k, v in dd.items()} for f, dd in pop.items()}}
    with gzip.open(out_dir / f"records_{d}.jsonl.gz.tmp", "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(g1r._clean(r)) + "\n")
    (out_dir / f"records_{d}.jsonl.gz.tmp").replace(out_dir / f"records_{d}.jsonl.gz")
    (out_dir / f"context_{d}.json").write_text(json.dumps(g1r._clean(summary), indent=1), encoding="utf-8")
    pit.drop_cache()
    return {k: summary[k] for k in ("date", "status", "seconds_pass1", "seconds_pass2", "chain_matches_engine")}


def _work(d):
    try:
        return run_date(d)
    except Exception as e:
        import traceback
        return {"date": d, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args(argv)
    lock = check_lock(a.freeze, a.out_dir, a.resume)                    # FIRST: before any data is opened
    a.out_dir.mkdir(parents=True, exist_ok=True)
    cfg, rep = build_cfg(lock["freeze"], a.out_dir)
    if not lock["already_started"]:
        with open(lock["ledger"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"freeze_sha256": lock["freeze_sha256"], "engine": "gate1_engine", "dates": DATES, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
    meta = {"started": datetime.now().isoformat(timespec="seconds"), "dates": DATES, "workers": a.workers, "git_head": holdout._git(g1r.REPO, "rev-parse", "HEAD").decode().strip(),
            "engine_files_sha256": {p.relative_to(g1r.REPO).as_posix(): holdout.sha256_file(p) for p in g1r.GATE1_FILES}, "n_ciks": len(cfg["ciks"]), "price_event_report": rep,
            "horizons": list(HORIZONS), "outcomes_end": cfg["outcomes_end"], "freeze_sha256": lock["freeze_sha256"], "resume": a.resume}
    (a.out_dir / ("run_meta_resume.json" if a.resume else "run_meta.json")).write_text(json.dumps(g1r._clean(meta), indent=1, default=str), encoding="utf-8")
    todo = [d for d in DATES if not (a.out_dir / f"records_{d}.jsonl.gz").exists()]
    t0 = time.time()
    with Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool:
        for s in pool.imap_unordered(_work, todo):
            print(datetime.now().strftime("%H:%M"), f"{time.time() - t0:.0f}s", json.dumps(g1r._clean(s))[:500], flush=True)
    print("done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
