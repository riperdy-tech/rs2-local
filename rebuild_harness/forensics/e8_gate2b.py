"""E8's second sample (SPEC_rebuild Addendum AL.28 item 3): gate 2's company-dates of 2026 (2026-02-27, 2026-04-30, 2026-06-30), valued at T by v1 (the code arm
exactly as `valuation.muse.pipeline.run_company` runs it: the engine on the prior alone) and by engine v2 (its current chain version, the vintage-2025 near-term
table), on the SAME inputs.  No outcome, no price after T, no model.  Writes records in the forensic shape that `e8_score.rows_of` reads.

    python -m rebuild_harness.forensics.e8_gate2b SCRATCH_STATE_DIR OUT_DIR TABLES_DIR PRIORS_DIR [--limit N]
AK.51: PRIORS_DIR is pinned (priors_v3_fy for acceptance); a scratch copy that differs from run 2's aborts; a fingerprint difference aborts unless its key is in
FINGERPRINT_ALLOWED (the priors vintages, which differ by design when PRIORS_DIR is not run 2's).

Read-only towards gate 2 (fork 1's recipe, AK of 2026-10-14): RealEnv runs on a SCRATCH state_dir holding copies of run 2's ctx/context_<d>.pkl for the three dates and
its sample/ (copied here, hashes checked); submissions materialise in the scratch folder; fetch_documents=False.  The run's input fingerprint
(freeze/gate2_freeze.json) is compared with the current inputs first and every difference is reported.  Each record also states whether the rebuilt state's
base year differs from run 2's own result.json (the dev branch carries the FY fix, 688281f)."""
import gzip
import hashlib
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

RUN2 = Path(r"C:\Users\riper\stocks\stocks-workspace\data\gate2_run2")
DATES = ("2026-02-27", "2026-04-30", "2026-06-30")
FINGERPRINT_ALLOWED = ("priors_vintages",)                       # AK.51 item 2: the fiscal-year inputs; nothing else may differ from run 2's freeze


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare_scratch(state: Path) -> dict:
    """Copies (never moves) the files company_inputs reads; returns {file: sha256 equal}."""
    out = {}
    (state / "ctx").mkdir(parents=True, exist_ok=True)
    (state / "sample").mkdir(parents=True, exist_ok=True)
    for src, dst in [(RUN2 / "ctx" / f"context_{d}.pkl", state / "ctx" / f"context_{d}.pkl") for d in DATES] + \
                    [(RUN2 / "sample" / n, state / "sample" / n) for n in ("sample.json", "sample.json.sha256")]:
        if not dst.exists():
            shutil.copy2(src, dst)
        out[dst.name] = _sha(src) == _sha(dst)
    return out


def fingerprint_check() -> dict:
    from rebuild_harness.gate2 import freeze_content as fc
    frozen = json.loads((RUN2 / "freeze" / "gate2_freeze.json").read_text(encoding="utf-8"))["inputs"]["fingerprint"]
    now = fc.inputs_section().get("fingerprint", {})
    diffs = {}
    for k, v in frozen.items():
        if now.get(k) != v:
            diffs[k] = {"frozen": v, "now": now.get(k)}
    return diffs


def _with_draws(mod, call):
    """Run `call()` while recording each valid draw's result (the module's own simulate runs unchanged)."""
    kept = []
    orig = mod.simulate

    def sim(chain_fn, dists, n, sd, corr=None, price_per_share=None, sh=None):
        def wrapped(draw):
            out = chain_fn(draw)
            kept.append(out)
            return out
        return orig(wrapped, dists, n, sd, corr, price_per_share, sh)
    mod.simulate = sim
    try:
        return call(), kept
    finally:
        mod.simulate = orig


def main(argv=None):
    a = argv or sys.argv[1:]
    state, out_dir, tables, priors_dir = Path(a[0]), Path(a[1]), Path(a[2]), Path(a[3])
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
    out_dir.mkdir(parents=True, exist_ok=True)
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    meta = {"copies_equal": prepare_scratch(state), "fingerprint_differences": fingerprint_check()}
    if not all(meta["copies_equal"].values()):
        raise SystemExit(f"aborted (AK.51 item 2): a scratch copy differs from run 2's: {meta['copies_equal']}")
    bad = sorted(k for k in meta["fingerprint_differences"] if k not in FINGERPRINT_ALLOWED)
    if bad:
        raise SystemExit(f"aborted (AK.51 item 2): input fingerprint differences outside the allowlist: {bad}")
    from rebuild_harness.gate2 import env as env_mod, sample as sample_mod, config
    from valuation import engine_financial, engine_operating, near_term as nt
    from valuation.common import DataNotPresent, build_state
    from valuation.muse.mapping import MusePriors, per_share_summary, run_engine
    from . import e5_v2 as E5
    g = env_mod._g1r()
    ev = env_mod.RealEnv(state_dir=state, store=g.DEFAULT_STORE, id_map=g.DEFAULT_IDMAP, prices_daily=config.WORKSPACE / "data" / "prices_daily",
                         prices_monthly=g.DEFAULT_PRICES, headers=g.DEFAULT_HEADERS, crosswalk=g.DEFAULT_CROSSWALK, sic=g.DEFAULT_SIC, priors_dir=priors_dir,
                         strict_classification=False, submissions_zip=config.WORKSPACE / "data" / "sec_bulk" / "submissions.zip", fetch_documents=False)
    smp = sample_mod.load_verified(sample_mod.sample_path(state))
    jobs = sample_mod.jobs(smp, dates=DATES)
    run2_dir = {}                                                            # key -> run 2's latest attempt folder (progress.jsonl), for the base-year comparison
    for line in (RUN2 / "progress.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("masked") and r.get("run_dir"):
                run2_dir[r["key"]] = r["run_dir"]
    if limit:
        jobs = jobs[:limit]
    table = nt.load_table(tables, 2025)
    meta["lineage"] = E5.lineage(priors_dir, tables, [2025], Path(__file__).resolve().parents[2])
    counts = {"jobs": len(jobs), "refused_inputs": 0, "refused_discount_rate": 0, "not_built": 0, "v1_refused": 0, "base_year_differs_from_run2": 0, "written": 0}
    recs = {d: [] for d in DATES}
    for job in jobs:
        ci = ev.company_inputs(job)
        if not hasattr(ci, "pit"):
            counts["refused_inputs"] += 1
            continue
        if ci.family not in ("operating", "financial"):
            counts["not_built"] += 1
            continue
        st = build_state(ci.pit)
        st.update(ci.industry_context or {})
        ps = ci.priors.for_company(ci.family, st, ci.pit.asof)
        try:
            disc = ci.disc_factory(st)
        except DataNotPresent:                                               # the pipeline refuses here too ("discount rate: ..."), never values
            counts["refused_discount_rate"] += 1
            continue
        shares = st.get("shares_outstanding")
        mod = engine_operating if ci.family == "operating" else engine_financial
        res0, kept = _with_draws(mod, lambda: run_engine(ci.family, ci.pit, MusePriors(ps, ci.family, st, {}), disc, n_draws=2000, seed=ci.seed, corr=ci.corr, state=st))
        if res0.get("status") != "ok":
            counts["v1_refused"] += 1
            continue
        eqs = sorted((r["equity"] for r in kept), reverse=True)
        top = (sum(eqs[:max(1, len(eqs) // 100)]) / sum(eqs)) if eqs and sum(eqs) > 0 else None
        top5 = (sum(eqs[:max(1, len(eqs) // 20)]) / sum(eqs)) if eqs and sum(eqs) > 0 else None
        e5 = {"family": ci.family, "v1_top1pct_share_of_mean": top, "v1_top5pct_share_of_mean": top5}
        if ci.family == "operating":
            import numpy as np
            evs = np.array([r["ev"] for r in kept], dtype=float)
            e5["v1_ev_p50"], e5["v1_ev_p90"] = float(np.quantile(evs, 0.5)), float(np.quantile(evs, 0.9))
        cap = SimpleNamespace(family=ci.family, pit=ci.pit, ps=ps, disc=disc, st=st)
        e5["v2_dist"] = E5.v2_distribution(cap, table, shares, seed=ci.seed)
        key = f"{job['date']}_{job['cik']}"
        prior = (RUN2 / run2_dir[key] / "result.json") if key in run2_dir else None
        base_run2 = None
        if prior is not None and prior.exists():
            r2 = json.loads(prior.read_text(encoding="utf-8"))
            base_run2 = (((r2.get("code_only") or {}).get("result") or {}).get("base_period"))
        e5["base_period"], e5["base_period_run2"] = st.get("base_period"), base_run2
        if base_run2 is not None and base_run2 != st.get("base_period"):
            counts["base_year_differs_from_run2"] += 1
        recs[job["date"]].append({"date": job["date"], "cik": ci.cik, "ticker": ci.ticker, "status": "valued", "val": {"status": "ok", "iv_ps": per_share_summary(res0, shares)},
                                  "e5": e5})
        counts["written"] += 1
    for d, rows in recs.items():
        with gzip.open(out_dir / f"records_{d}.jsonl.gz", "wt", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, default=str) + "\n")
    meta["counts"] = counts
    (out_dir / "e8_gate2b_meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    print(json.dumps(meta, default=str)[:1500])


if __name__ == "__main__":
    main()
