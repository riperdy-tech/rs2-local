"""DIAGNOSTIC ONLY (round 3b): the "closure ERP" of a valuation date, and the gate-1 engine re-run on it.  Code only: no GPU, no model, no network.

    python -m rebuild_harness.gate1_closure --out-dir OUT --reference-run ROUND3_RUN [--dates ...] [--workers 12]

THE HYPOTHESIS (Addendum I, round-3 results): Damodaran's implied ERP is solved from the index price with analysts' consensus growth, while the engines' cash flows
follow population base rates that fade growth far faster, so the pairing undervalues systematically.  This script measures it.  NOTHING HERE CHANGES AN ENGINE
DEFAULT OR A REGISTERED RULE: the engine, the priors, the data and the draws are exactly round 3's; only the equity risk premium that `valuation.gate1.Rates.erp`
hands to the discount rate is replaced, by an override object that exists only in this process.  Every record is stamped with its variant and the ERP applied.

THE CLOSURE ERP of a date.  The universe is the names valued at the date by the registered engine (round 3's rule: invalid-draw share <= 5%) with a market cap of
at least $300M.  The closure ERP is the single scalar for which the sum of the engine's median equity values (the P50 of the draw distribution times the share
count) over the universe equals the sum of the market caps (price x shares at T), everything else held: the same prepared companies, the same population context,
the same priors and seeds, the same risk-free rate, betas, book D/E and cost of debt.  Solved by bisection on the ERP: the bracket is found by doubling steps from the
Damodaran ERP, then halved until it is narrower than `--tol` (default 0.5 bp), the answer being the bracket end with the smaller residual.  During the solve the H5
refusal (invalid-draw share) is off for the universe's names (the universe is fixed; a name that all its draws invalidate contributes nothing and is counted);
the variant runs below apply the registered rule in full.  The per-family closure is the same solve on each family's names alone.

OUTPUT: OUT/common/ (records, the engine re-run at each date's common closure ERP), OUT/family/ (each family at its own closure ERP), OUT/closure_{date}.json
(the solves: every iterate, the sums, the counts, the determinism check against round 3), and OUT/closure_table.md / closure_summary.json (see `summarize`).
Each of common/ and family/ is a run folder `gate1_report` reads.
"""
import argparse
import copy
import gzip
import json
import time
from collections import Counter
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

from valuation import gate1
from valuation.common import sha256_file
from valuation.discount_rate import DamodaranStore, MriRiskFree
from . import gate1_run as gr
from . import holdout

DEFAULT_DATES = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31", "2021-06-30", "2021-09-30", "2021-12-31",
                 "2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31"]
REGISTERED_INVALID_DRAW_MAX = gate1.INVALID_DRAW_MAX        # read at import, before anything changes it
VARIANT_COMMON = "closure_erp_common_DIAGNOSTIC"
VARIANT_FAMILY = "closure_erp_by_family_DIAGNOSTIC"
FAMILIES = ("operating", "commodity", "financial")
STEP0, ERP_FLOOR, ERP_CAP = 0.015, 0.0005, 0.60


class ErpOverride:
    """Wraps a `Rates`: everything delegates except `erp`, which returns the scalar set in `.value` (a closure ERP, labelled as such)."""

    def __init__(self, base, label):
        self._base = base
        self._label = label
        self.value = None

    def __getattr__(self, name):
        return getattr(self._base, name)

    def erp(self, asof):
        if self.value is None:
            raise RuntimeError("ErpOverride.value is not set")
        return self.value, self._label, {"file_sha256": None, "closure_diagnostic": True}


def bisect_closure(f, erp0, g0, tol, step0=STEP0, floor=ERP_FLOOR, cap=ERP_CAP, max_evals=60):
    """Solve g(erp) = 0 where g = sum(engine equity) / sum(market cap) - 1 is decreasing in the ERP.  `f(erp)` returns (g, info).  g0 is g at `erp0` (known).
    Returns {"status", "erp", "g", "trace"}.  The bracket is found by doubling steps from erp0, then bisected until hi - lo <= tol."""
    trace = [{"phase": "start", "erp": erp0, "g": g0}]
    n = 0

    def ev(x, phase):
        nonlocal n
        g, info = f(x)
        n += 1
        trace.append({"phase": phase, "erp": x, "g": g, **info})
        return g

    if g0 == 0:
        return {"status": "exact", "erp": erp0, "g": 0.0, "trace": trace}
    step = step0
    if g0 > 0:                                     # the engine values the universe above its price: the ERP must rise
        lo, glo = erp0, g0
        while True:
            hi = min(lo + step, cap)
            ghi = ev(hi, "bracket_up")
            if ghi <= 0:
                break
            if hi >= cap:
                return {"status": "no_root_below_cap", "erp": hi, "g": ghi, "trace": trace}
            lo, glo = hi, ghi
            step *= 2
    else:                                          # the engine values the universe below its price: the ERP must fall
        hi, ghi = erp0, g0
        while True:
            lo = max(hi - step, floor)
            glo = ev(lo, "bracket_down")
            if glo >= 0:
                break
            if lo <= floor:
                return {"status": "no_root_above_floor", "erp": lo, "g": glo, "trace": trace}
            hi, ghi = lo, glo
            step *= 2
    while hi - lo > tol and n < max_evals:
        mid = 0.5 * (lo + hi)
        gm_ = ev(mid, "bisect")
        if gm_ > 0:
            lo, glo = mid, gm_
        else:
            hi, ghi = mid, gm_
    best = (lo, glo) if abs(glo) <= abs(ghi) else (hi, ghi)
    return {"status": "ok" if hi - lo <= tol else "max_evals", "erp": best[0], "g": best[1], "bracket": [lo, hi], "trace": trace}


# ---- the worker ----------------------------------------------------------------------------------------------------------------------

def _read_reference(path, d):
    """{cik: (iv_p50_per_share, status)} from round 3's records of the date, for the determinism check."""
    out = {}
    with gzip.open(Path(path) / f"records_{d}.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            v = r.get("val") or {}
            out[r["cik"]] = ((v.get("iv_ps") or {}).get("p50") if r["status"] == "valued" else None, r["status"], r.get("market_cap"))
    return out


def _value_records(recs, preps, ctx, priors, rates, n_draws, erp_of, variant, erp_label):
    """Pass 2 exactly as `gate1_run.run_date` does it, with the ERP set per company by `erp_of(family)` (None: the real Rates, Damodaran)."""
    for rec in recs:
        if rec["status"] != "prepared":
            continue
        prep = preps[rec["cik"]]
        if erp_of is not None:
            rates.value = erp_of(prep["family"])
        v = gate1.value_company(prep, ctx, priors, rates, rec["shares"], n_draws=n_draws)
        rec["val"] = v
        rec["stamps"] = sorted(set(rec["stamps"]) | set(v.get("stamps", [])))
        if erp_of is not None:
            rec["stamps"] = sorted(set(rec["stamps"]) | {f"erp_closure_diagnostic: {erp_label} (variant {variant}); Damodaran's ERP is NOT used"})
            rec["variant"], rec["erp_applied"] = variant, rates.value
        if v["status"] == "ok":
            rec["status"] = "valued"
            rec["score"]["gate1_engine"] = v["iv_ps"]["p50"] / rec["price"]
        else:
            rec["status"], rec["reasons"] = "refused", list(v["reasons"])


def _write(out_dir, d, recs, summary):
    out_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_dir / f"records_{d}.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(gr._clean(r)) + "\n")
    (out_dir / f"context_{d}.json").write_text(json.dumps(gr._clean(summary), indent=1), encoding="utf-8")


def _log(d, msg):
    print(datetime.now().strftime("%H:%M"), d, msg, flush=True)


def closure_date(d):
    t_start = time.time()
    cfg = gr._ENV["cfg"]
    out = Path(cfg["out_dir"])
    n_draws = cfg.get("n_draws", gate1.N_DRAWS)
    recs, preps, ctx, t0, t1 = gr.prepare_date(d, cfg["ciks"])
    _log(d, f"pass 1 done {t1 - t0:.0f}s")
    priors, real_rates = gr._ENV["priors"], gr._ENV["rates"]
    damo = real_rates.erp(d)
    erp_d = damo[0]
    gate1.INVALID_DRAW_MAX = REGISTERED_INVALID_DRAW_MAX
    base = [copy.deepcopy(r) for r in recs]                       # the baseline: round 3's rule at Damodaran's ERP (a re-run: the determinism check)
    _value_records(base, preps, ctx, priors, real_rates, n_draws, None, None, None)
    t2 = time.time()
    _log(d, f"baseline re-run done {t2 - t1:.0f}s")
    ref = _read_reference(cfg["reference_run"], d)
    n_ref_valued = sum(1 for v in ref.values() if v[1] == "valued")
    mism, maxrel, n_cmp = 0, 0.0, 0
    for r in base:
        rv = ref.get(r["cik"])
        if rv is None:
            mism += 1
            continue
        if (r["status"] == "valued") != (rv[1] == "valued"):
            mism += 1
        elif r["status"] == "valued":
            n_cmp += 1
            maxrel = max(maxrel, abs(r["val"]["iv_ps"]["p50"] - rv[0]) / max(abs(rv[0]), 1e-12))
    universe = [r for r in base if r["status"] == "valued" and r["mcap_group"] == ">=300M"]
    uni = {r["cik"]: {"family": r["family"], "mcap": r["market_cap"], "shares": r["shares"], "eq0": r["val"]["iv_ps"]["p50"] * r["shares"]} for r in universe}
    del base

    ov = ErpOverride(real_rates, "closure ERP (diagnostic, round 3b)")
    gate1.INVALID_DRAW_MAX = 1.0                                   # the solve: the universe is fixed; the registered refusal is applied in the variant runs below

    def sums(ciks, erp):
        ov.value = erp
        s_eq = s_mc = 0.0
        n_ok = n_lost = 0
        for c in ciks:
            u = uni[c]
            s_mc += u["mcap"]
            v = gate1.value_company(preps[c], ctx, priors, ov, u["shares"], n_draws=n_draws)
            if v["status"] == "ok":
                s_eq += v["iv_ps"]["p50"] * u["shares"]
                n_ok += 1
            else:
                n_lost += 1
        return s_eq, s_mc, n_ok, n_lost

    def solve(ciks, label):
        s_eq0 = sum(uni[c]["eq0"] for c in ciks)
        s_mc0 = sum(uni[c]["mcap"] for c in ciks)
        g0 = s_eq0 / s_mc0 - 1.0

        def f(erp):
            s_eq, s_mc, n_ok, n_lost = sums(ciks, erp)
            return s_eq / s_mc - 1.0, {"sum_equity": s_eq, "sum_mcap": s_mc, "n_ok": n_ok, "n_lost": n_lost}
        ts = time.time()
        res = bisect_closure(f, erp_d, g0, cfg["tol"])
        _log(d, f"solve {label}: {res['status']} erp {res['erp']:.5f} (Damodaran {erp_d:.4f}), {len(ciks)} names, {time.time() - ts:.0f}s")
        res.update({"label": label, "n_names": len(ciks), "sum_mcap": s_mc0, "sum_equity_at_damodaran": s_eq0, "ratio_at_damodaran": s_eq0 / s_mc0, "seconds": time.time() - ts})
        return res

    solves = {"all": solve(list(uni), "all")}
    for fam in FAMILIES:
        ciks = [c for c in uni if uni[c]["family"] == fam]
        solves[fam] = solve(ciks, fam) if ciks else {"status": "no_names", "label": fam, "n_names": 0}
    t3 = time.time()

    gate1.INVALID_DRAW_MAX = REGISTERED_INVALID_DRAW_MAX if cfg.get("invalid_draw_max") is None else cfg["invalid_draw_max"]
    common_erp = solves["all"]["erp"]
    fam_erp = {f: (solves[f]["erp"] if solves[f].get("status") in ("ok", "exact", "max_evals") else erp_d) for f in FAMILIES}
    fam_used_damodaran = [f for f in FAMILIES if solves[f].get("status") not in ("ok", "exact", "max_evals")]
    for name, fn, variant, sub in (("common", lambda fam: common_erp, VARIANT_COMMON, "common"), ("family", lambda fam: fam_erp[fam], VARIANT_FAMILY, "family")):
        vr = [copy.deepcopy(r) for r in recs]
        _value_records(vr, preps, ctx, priors, ov, n_draws, fn, variant, name)
        counts = Counter(r["status"] for r in vr)
        summary = {"date": d, "variant": variant, "rf": ctx.rf, "n_companies": len(cfg["ciks"]), "status": dict(counts), "erp_damodaran": erp_d, "erp_common_closure": common_erp,
                   "erp_by_family": fam_erp, "seconds_pass1": t1 - t0}
        _write(out / sub, d, vr, summary)
        del vr
    info = {"date": d, "erp_damodaran": erp_d, "erp_damodaran_source": damo[1], "rf": ctx.rf, "n_universe": len(uni), "solves": solves, "erp_common_closure": common_erp,
            "erp_by_family_used": fam_erp, "families_that_kept_damodaran_for_lack_of_a_root": fam_used_damodaran,
            "determinism_vs_round3": {"n_compared_valued": n_cmp, "n_valued_reference": n_ref_valued, "status_mismatches": mism, "max_relative_difference_iv_p50": maxrel},
            "seconds": {"pass1": t1 - t0, "baseline": t2 - t1, "solve": t3 - t2, "variants": time.time() - t3, "total": time.time() - t_start}}
    (out / f"closure_{d}.json").write_text(json.dumps(gr._clean(info), indent=1), encoding="utf-8")
    gr._ENV["pit"].drop_cache()
    return {k: info[k] for k in ("date", "erp_damodaran", "erp_common_closure", "erp_by_family_used", "n_universe", "determinism_vs_round3", "seconds")}


def _work(d):
    try:
        return closure_date(d)
    except Exception as e:
        import traceback
        return {"date": d, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--reference-run", required=True, type=Path, help="round 3's run folder (records), for the determinism check and nothing else")
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit-ciks", type=int)
    ap.add_argument("--tol", type=float, default=5e-5, help="bisection stops when the bracket is narrower than this (an ERP fraction; default 0.5 bp)")
    ap.add_argument("--store", type=Path, default=gr.DEFAULT_STORE)
    ap.add_argument("--id-map", type=Path, default=gr.DEFAULT_IDMAP)
    ap.add_argument("--prices", type=Path, default=gr.DEFAULT_PRICES)
    ap.add_argument("--sic", type=Path, default=gr.DEFAULT_SIC)
    ap.add_argument("--n-draws", type=int, default=gate1.N_DRAWS)
    ap.add_argument("--priors-dir", type=Path, required=True)
    ap.add_argument("--freeze", type=Path)
    a = ap.parse_args(argv)
    dates = a.dates or DEFAULT_DATES
    lock = holdout.enforce(dates, [gr.gate1_engine], a.freeze)       # FIRST: before any data is opened
    a.out_dir.mkdir(parents=True, exist_ok=True)
    idm = json.loads(a.id_map.read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    ciks = sorted(set(str(v).zfill(10) for v in idm.values()))
    if a.limit_ciks:
        ciks = ciks[:a.limit_ciks]
    rf_src = MriRiskFree()
    rf = {d: rf_src(d) for d in dates}
    cfg = {"store": str(a.store), "id_map": str(a.id_map), "prices": str(a.prices), "sic": str(a.sic), "rf": rf, "ciks": ciks, "n_draws": a.n_draws, "out_dir": str(a.out_dir),
           "priors_dir": str(a.priors_dir), "invalid_draw_max": None, "reference_run": str(a.reference_run), "tol": a.tol}
    meta = {"DIAGNOSTIC_ONLY": "round 3b: the engine re-run with the equity risk premium replaced by the closure ERP; no default or registered rule is changed",
            "started": datetime.now().isoformat(timespec="seconds"), "dates": dates, "lock": lock, "n_ciks": len(ciks), "workers": a.workers, "n_draws": a.n_draws,
            "gate1_version": gate1.GATE1_VERSION, "price_stamp": gr.PRICE_STAMP, "price_file": str(a.prices), "price_file_sha256": sha256_file(a.prices),
            "price_file_meta": json.loads(a.prices.read_text(encoding="utf-8")).get("meta"), "priors_dir": str(a.priors_dir),
            "invalid_draw_max": REGISTERED_INVALID_DRAW_MAX, "invalid_draw_max_is_the_registered_rule": True, "reference_run": str(a.reference_run), "tol": a.tol,
            "git_head": holdout._git(gr.REPO, "rev-parse", "HEAD").decode().strip(), "rf": {k: v[0] for k, v in rf.items()},
            "variants": {"common": VARIANT_COMMON, "family": VARIANT_FAMILY}}
    (a.out_dir / "run_meta.json").write_text(json.dumps(gr._clean(meta), indent=1), encoding="utf-8")
    for sub in ("common", "family"):
        (a.out_dir / sub).mkdir(exist_ok=True)
        (a.out_dir / sub / "run_meta.json").write_text(json.dumps(gr._clean(dict(meta, variant=meta["variants"][sub])), indent=1), encoding="utf-8")
    t0 = time.time()
    with Pool(a.workers, initializer=gr._init, initargs=(cfg,)) as pool:
        for s in pool.imap_unordered(_work, dates):
            print(datetime.now().strftime("%H:%M"), f"{time.time() - t0:.0f}s", json.dumps(gr._clean(s))[:600], flush=True)
    print("done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
