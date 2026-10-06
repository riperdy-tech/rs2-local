"""DIAGNOSTIC ONLY (round 4, Addendum J1): the level decomposition.  Code only: no GPU, no model, no network.

    python -m rebuild_harness.gate1_decompose --out-dir OUT --priors-dir PRIORS --closure-dir ROUND3B [--reference-run ROUND4_RUN] [--dates ...] [--workers 8]

Starting from the round-4 engine (the registered engine as it stands: Damodaran's monthly ERP, terminal growth min(rf, 3.75%), terminal RONIC = WACC + kappa (I - WACC), the
measured growth persistence, the drawn year-5 margin level, reinvestment priced at the return on new capital, the measured prior widths) ONE component at a time is swapped to
a stated alternative (valuation/variants.py; the ERP swap is a swap of the `Rates` object, as in round 3b) and the value distribution of the SAME names is measured again.
Nothing here changes a default or a registered rule.

THE UNIVERSE of a date is fixed: the names the registered engine values at the date (invalid-draw share <= 5%) with a market cap of at least $300M.  Every variant values exactly
those names, with the H5 refusal switched off for the variant run (a name whose draws are all invalid is counted as lost), so that a change of the median is the component's
effect and not a change of who is in the sample.  The seeds, the draws' uniform numbers, the priors, the data and the cost of capital (except for the swapped component) are
the baseline's.

Variants (key: swap; families it applies to):
  a_erp_closure          the equity risk premium: Damodaran's monthly implied ERP -> round 3b's common closure ERP of the date (all)
  b_terminal_g_flat      terminal growth min(rf, 3.75%) -> 3.75% flat (all)
  c1_ronic_median        terminal return on new capital J3 -> the industry median floored at WACC, round 3's rule (operating, commodity); FINANCIAL ANALOGUE: kappa = 1
  c2_ronic_wacc          terminal return on new capital J3 -> WACC (operating, commodity); FINANCIAL ANALOGUE: kappa = 0 (no terminal excess)
  d_no_decay             measured growth decay -> g1 held 5 years, then linear fade to the measured last value (all)
  e_margin_held          drawn year-5 margin level -> the base-year margin held (operating, commodity); FINANCIAL ANALOGUE: the ROTE target = the base-year ROTE
  f_zero_reinvestment    growth reinvestment priced at the return on new capital -> zero (operating, commodity; no analogue for financials: their growth is funded by retention)
  g_half_width           every judgment input's distribution scaled by 0.5 about its P50 (all)
  h_no_normalization     commodity only: the measured normalization curve -> none (the drawn through-cycle margin level from year 1)

OUTPUT: OUT/decomp_{date}.json per date (the fixed universe and each variant's per-name compact result, the ERP series of the date), run_meta.json.  `gate1_decompose_summary` reads them.
"""
import argparse
import json
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

from valuation import gate1
from valuation import variants as V
from valuation.common import sha256_file
from valuation.discount_rate import MriRiskFree
from . import gate1_run as gr
from . import holdout
from .gate1_closure import ErpOverride

DEFAULT_DATES = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31", "2021-06-30", "2021-09-30", "2021-12-31",
                 "2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31"]
REGISTERED_INVALID_DRAW_MAX = gate1.INVALID_DRAW_MAX
ALL = ("operating", "commodity", "financial")
OPCOM = ("operating", "commodity")

# key, label, Variant, ERP swap?, families
VARIANTS = [
    ("a_erp_closure", "(a) ERP: Damodaran monthly -> round 3b closure", V.Variant(name="a_erp_closure"), True, ALL),
    ("b_terminal_g_flat", "(b) terminal g: min(rf, 3.75%) -> 3.75% flat", V.Variant(name="b_terminal_g_flat", terminal_g="flat"), False, ALL),
    ("c1_ronic_median", "(c) terminal RONIC: J3 -> industry median (round 3); financial: kappa 1", V.Variant(name="c1_ronic_median", terminal_ronic="industry_median"), False, ALL),
    ("c2_ronic_wacc", "(c) terminal RONIC: J3 -> WACC; financial: kappa 0", V.Variant(name="c2_ronic_wacc", terminal_ronic="wacc"), False, ALL),
    ("d_no_decay", "(d) growth persistence: measured decay -> g1 held 5 years, then fade", V.Variant(name="d_no_decay", growth_decay="none"), False, ALL),
    ("e_margin_held", "(e) margin: drawn year-5 level -> held at current; financial: ROTE held", V.Variant(name="e_margin_held", margin="held"), False, ALL),
    ("f_zero_reinvestment", "(f) reinvestment: RONIC-priced -> zero growth reinvestment", V.Variant(name="f_zero_reinvestment", reinvestment="zero"), False, OPCOM),
    ("g_half_width", "(g) priors width: measured -> half width", V.Variant(name="g_half_width", width=0.5), False, ALL),
    ("h_no_normalization", "(h) commodity: normalization curve -> none", V.Variant(name="h_no_normalization", margin="instant"), False, ("commodity",)),
]


def _read_closure(closure_dir, d):
    p = Path(closure_dir) / f"closure_{d}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get("erp_common_closure")


def _compact(v, price):
    """The few numbers of one valued name: [IV/price at the median, share of valid draws floored at zero, valid draws, draws, share of invalid draws]; None when not valued."""
    if v["status"] != "ok":
        return None
    return [v["iv_ps"]["p50"] / price, v.get("share_negative_equity"), v["n_valid"], v["n_draws"], 1.0 - v["n_valid"] / v["n_draws"]]


def decompose_date(d):
    t_start = time.time()
    cfg = gr._ENV["cfg"]
    out = Path(cfg["out_dir"])
    n_draws = cfg.get("n_draws", gate1.N_DRAWS)
    recs, preps, ctx, t0, t1 = gr.prepare_date(d, cfg["ciks"])
    priors, real_rates = gr._ENV["priors"], gr._ENV["rates"]
    erp_m = real_rates.erp(d)
    erp_a = real_rates.store.erp_provider(monthly=False)(d)
    erp_c = _read_closure(cfg["closure_dir"], d)
    gate1.INVALID_DRAW_MAX = REGISTERED_INVALID_DRAW_MAX
    universe, base = {}, {}
    for rec in recs:
        if rec["status"] != "prepared":
            continue
        v = gate1.value_company(preps[rec["cik"]], ctx, priors, real_rates, rec["shares"], n_draws=n_draws)
        if v["status"] == "ok" and rec["mcap_group"] == ">=300M":
            universe[rec["cik"]] = {"family": rec["family"], "price": rec["price"], "shares": rec["shares"], "mcap": rec["market_cap"], "industry": rec["industry"]}
            base[rec["cik"]] = _compact(v, rec["price"])
    t2 = time.time()
    ref_check = None
    if cfg.get("reference_run"):
        import gzip
        ref = {}
        with gzip.open(Path(cfg["reference_run"]) / f"records_{d}.jsonl.gz", "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r["status"] == "valued":
                    ref[r["cik"]] = r["val"]["iv_ps"]["p50"] / r["price"]
        diffs = [abs(base[c][0] - ref[c]) / max(abs(ref[c]), 1e-12) for c in base if c in ref]
        ref_check = {"n_compared": len(diffs), "n_universe": len(base), "n_universe_not_in_reference": sum(1 for c in base if c not in ref), "max_relative_difference": max(diffs) if diffs else None}
    results = {"base": base}
    ov = ErpOverride(real_rates, "closure ERP (diagnostic, round 3b)")
    gate1.INVALID_DRAW_MAX = 1.0                          # the universe is fixed: the registered refusal is off for the variant runs; a name with no valid draw is counted lost
    skipped = {}
    for key, label, variant, swap_erp, fams in VARIANTS:
        if swap_erp and erp_c is None:
            skipped[key] = "no round 3b closure ERP for this date"
            continue
        rates_ = ov if swap_erp else real_rates
        if swap_erp:
            ov.value = erp_c
        res = {}
        for cik, u in universe.items():
            if u["family"] not in fams:
                continue
            v = gate1.value_company(preps[cik], ctx, priors, rates_, u["shares"], n_draws=n_draws, variant=None if swap_erp else variant)
            res[cik] = _compact(v, u["price"])
        results[key] = res
        print(datetime.now().strftime("%H:%M"), d, key, f"{len(res)} names, lost {sum(1 for x in res.values() if x is None)}, {time.time() - t2:.0f}s", flush=True)
    info = {"date": d, "rf": ctx.rf, "erp": {"damodaran_monthly": erp_m[0], "monthly_row": (erp_m[2] or {}).get("row_date"), "monthly_source": (erp_m[2] or {}).get("source"),
                                              "damodaran_annual": erp_a[0], "annual_year_end": (erp_a[2] or {}).get("year_end"), "round3b_common_closure": erp_c},
            "n_universe": len(universe), "universe": universe, "variants": results, "skipped": skipped, "reference_check": ref_check,
            "labels": {k: l for k, l, *_ in VARIANTS}, "seconds": {"pass1": t1 - t0, "baseline": t2 - t1, "total": time.time() - t_start}}
    (out / f"decomp_{d}.json").write_text(json.dumps(gr._clean(info)), encoding="utf-8")
    gr._ENV["pit"].drop_cache()
    return {"date": d, "n_universe": len(universe), "erp": info["erp"], "reference_check": ref_check, "skipped": skipped, "seconds": info["seconds"]}


def _work(d):
    try:
        return decompose_date(d)
    except Exception as e:
        import traceback
        return {"date": d, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--priors-dir", required=True, type=Path)
    ap.add_argument("--closure-dir", required=True, type=Path, help="round 3b's folder (closure_{date}.json)")
    ap.add_argument("--reference-run", type=Path, help="the round-4 run folder whose records the baseline must reproduce (a determinism check)")
    ap.add_argument("--dates", nargs="*")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit-ciks", type=int)
    ap.add_argument("--store", type=Path, default=gr.DEFAULT_STORE)
    ap.add_argument("--id-map", type=Path, default=gr.DEFAULT_IDMAP)
    ap.add_argument("--prices", type=Path, default=gr.DEFAULT_PRICES)
    ap.add_argument("--sic", type=Path, default=gr.DEFAULT_SIC)
    ap.add_argument("--n-draws", type=int, default=gate1.N_DRAWS)
    a = ap.parse_args(argv)
    if a.workers > 8:
        raise SystemExit("at most 8 workers (the machine is shared)")
    dates = a.dates or DEFAULT_DATES
    lock = holdout.enforce(dates, [gr.gate1_engine], None)             # FIRST: before any data is opened
    a.out_dir.mkdir(parents=True, exist_ok=True)
    idm = json.loads(a.id_map.read_text(encoding="utf-8"))
    idm = idm.get("map", idm)
    ciks = sorted(set(str(v).zfill(10) for v in idm.values()))
    if a.limit_ciks:
        ciks = ciks[:a.limit_ciks]
    rf_src = MriRiskFree()
    rf = {d: rf_src(d) for d in dates}
    cfg = {"store": str(a.store), "id_map": str(a.id_map), "prices": str(a.prices), "sic": str(a.sic), "rf": rf, "ciks": ciks, "n_draws": a.n_draws, "out_dir": str(a.out_dir),
           "priors_dir": str(a.priors_dir), "invalid_draw_max": None, "closure_dir": str(a.closure_dir), "reference_run": str(a.reference_run) if a.reference_run else None}
    meta = {"DIAGNOSTIC_ONLY": "round 4 level decomposition (Addendum J1): one component swapped at a time; no default or registered rule is changed",
            "started": datetime.now().isoformat(timespec="seconds"), "dates": dates, "lock": lock, "n_ciks": len(ciks), "workers": a.workers, "n_draws": a.n_draws,
            "gate1_version": gate1.GATE1_VERSION, "price_stamp": gr.PRICE_STAMP, "price_file": str(a.prices), "price_file_sha256": sha256_file(a.prices),
            "priors_dir": str(a.priors_dir), "invalid_draw_max_registered": REGISTERED_INVALID_DRAW_MAX, "closure_dir": str(a.closure_dir),
            "reference_run": cfg["reference_run"], "git_head": holdout._git(gr.REPO, "rev-parse", "HEAD").decode().strip(), "rf": {k: v[0] for k, v in rf.items()},
            "variants": {k: {"label": l, "variant": v.__dict__, "erp_swap": s, "families": list(f)} for k, l, v, s, f in VARIANTS}}
    (a.out_dir / "run_meta.json").write_text(json.dumps(gr._clean(meta), indent=1), encoding="utf-8")
    t0 = time.time()
    with Pool(a.workers, initializer=gr._init, initargs=(cfg,)) as pool:
        for s in pool.imap_unordered(_work, dates):
            print(datetime.now().strftime("%H:%M"), f"{time.time() - t0:.0f}s", json.dumps(gr._clean(s))[:700], flush=True)
    print("done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
