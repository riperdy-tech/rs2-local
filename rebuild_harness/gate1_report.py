"""Build the gate-1 development report from a run folder: coverage, B1-B4 under the three bounds (PROVISIONAL), and the structural diagnostics.

    python -m rebuild_harness.gate1_report RUN_DIR [--out-dir OUT] [--resamples 2000] [--extremes-dates 2019-12-31 2022-06-30]

Writes gate1_dev_report.json and gate1_dev_report.md.  Reads records only; it forms no new return.  Every figure is PROVISIONAL (see gate1_metrics).
"""
import argparse
import json
from pathlib import Path

import numpy as np

from . import gate1_metrics as gm


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        o = o.item()
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o


def per_date(rows):
    out = {}
    for d, rs in gm.by_date(rows).items():
        vp = [r["vp"] for r in rs if r.get("vp") is not None]
        out[d] = {"n_valued": len(rs), "n_valued_ge_300M": sum(1 for r in rs if r["mcap_group"] == ">=300M"),
                  "median_vp": float(np.median(vp)) if vp else None, "share_below_0_4": float(np.mean([v < 0.4 for v in vp])) if vp else None,
                  "share_above_2_5": float(np.mean([v > 2.5 for v in vp])) if vp else None,
                  "median_invalid_share": float(np.median([r["invalid_share"] for r in rs])) if rs else None,
                  "median_coe": float(np.median([r["disc"]["coe"] for r in rs if r.get("disc")])) if rs else None}
    return out


def build(run_dir, resamples=2000, extremes_dates=("2019-12-31", "2022-06-30"), adjusted_proxy=None):
    rows, counters, full = gm.load_run(run_dir, keep_all_for=tuple(extremes_dates))
    proxy_missing = None
    if adjusted_proxy is not None:
        proxy_missing = gm.apply_adjusted_proxy(rows, json.loads(Path(adjusted_proxy).read_text(encoding="utf-8")))
    big = [r for r in rows if r["mcap_group"] == ">=300M"]
    small = [r for r in rows if r["mcap_group"] == "<300M"]
    big_fresh = [r for r in big if not r["stale"]]
    rep = {"provisional": gm.PROVISIONAL, "price_basis": "adjusted-only proxy (IV/price, earnings and FCF yields times Close/Adj Close)" if adjusted_proxy else "run basis: traded close rebuilt from the split-adjusted Close and the split events",
           "adjusted_proxy_rows_without_both_bars": proxy_missing, "run_dir": str(run_dir), "n_valued": len(rows), "n_valued_ge_300M": len(big), "n_valued_lt_300M": len(small),
           "coverage": gm.coverage_tables(counters), "per_date": per_date(rows)}
    rep["gate1_universe_ge_300M"] = gm.three_bounds(big, ">=300M", resamples)
    rep["sub_300M_reported_separately"] = gm.three_bounds(small, "<300M", resamples)
    rep["sensitivity_ge_300M_base_year_within_15_months"] = gm.three_bounds(big_fresh, ">=300M, base year <= 15 months old", resamples)
    for label, rs in (("ge_300M", big), ("lt_300M", small)):
        rep.setdefault("diagnostics", {})[label] = {
            "vp_overall": gm.distribution_block([r["vp"] for r in rs]), "vp_by_family": gm.vp_by(rs, lambda r: r["family"]),
            "vp_by_industry_n_ge_20": gm.vp_by(rs, lambda r: r["industry"] or "unmapped", 20),
            "vp_by_date": gm.vp_by(rs, lambda r: r["date"]), "extremes_by_family": gm.extremes_by_family(rs),
            "tv_share": gm.tv_share_distribution(rs), "model_disagreement_by_family": gm.disagreement_by_family(rs), "structure": gm.structure_stats(rs)}
    rep["extremes_listings"] = {d: gm.extremes_listing(full[d], 30) for d in extremes_dates if d in full}
    return rep


def fmt(x, nd=3):
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def render(rep):
    L = ["# Gate 1, development run: report", "", "**" + rep["provisional"] + "**", "", f"Price basis: {rep['price_basis']}", "",
         f"Valued: {rep['n_valued']} (market cap >= $300M: {rep['n_valued_ge_300M']}; below: {rep['n_valued_lt_300M']})", ""]
    L += ["## Valued names and median IV / price by date", "", "| date | valued | >= $300M | median IV/price | share < 0.4x | share > 2.5x | median invalid-draw share | median COE |", "|---|---|---|---|---|---|---|---|"]
    for d, v in rep["per_date"].items():
        L.append(f"| {d} | {v['n_valued']} | {v['n_valued_ge_300M']} | {fmt(v['median_vp'])} | {fmt(v['share_below_0_4'])} | {fmt(v['share_above_2_5'])} | {fmt(v['median_invalid_share'])} | {fmt(v['median_coe'])} |")
    cov = rep["coverage"]
    L += ["", "## Coverage: refusals by reason (all dates)", ""] + [f"- {v}: {k}" for k, v in list(cov["refusals_by_reason"].items())[:40]]
    L += ["", "## Coverage: by family and status", ""] + [f"- {k}: {v}" for k, v in cov["by_family_and_status"].items()]
    L += ["", "## Coverage: per date status", ""] + [f"- {d}: {v}" for d, v in cov["per_date_status"].items()]
    L += ["", "## Coverage: family and status by date", ""] + [f"- {d}: {v}" for d, v in cov["family_and_status_by_date"].items()]
    top = list(cov["refusals_by_reason"])[:10]
    L += ["", "## Coverage: the ten most frequent refusal reasons by date", "", "| date | " + " | ".join(t[:38] for t in top) + " |", "|---|" + "---|" * len(top)]
    for d, rs in cov["refusals_by_date_and_reason"].items():
        L.append(f"| {d} | " + " | ".join(str(rs.get(t, 0)) for t in top) + " |")
    for key, title in (("gate1_universe_ge_300M", "B1-B4, universe: market cap >= $300M"), ("sub_300M_reported_separately", "B1-B4, sub-$300M group (separate)"),
                       ("sensitivity_ge_300M_base_year_within_15_months", "Sensitivity: >= $300M with a base year at most 15 months old")):
        r = rep[key]
        L += ["", f"## {title}", "", f"valued: {r['n_valued']}", ""]
        L.append("| bar | " + " | ".join(gm.BOUNDS) + " | status over bounds |")
        L.append("|---|---|---|---|---|")
        L.append("| B1 mean engine coefficient [90% lower, upper] | " + " | ".join(f"{fmt(r['B1'][b]['mean_coef'], 4)} [{fmt(r['B1'][b]['ci90'][0], 4)}, {fmt(r['B1'][b]['ci90'][1], 4)}] ({r['B1'][b]['n_dates']} dates)" for b in gm.BOUNDS) + f" | {r['B1_status_over_bounds']} |")
        L.append("| B2 neutral spread (residual) [90%] | " + " | ".join(f"{fmt(r['B2'][b]['mean_spread'], 4)} ({fmt(r['B2'][b]['mean_spread_residual'], 4)}) [{fmt(r['B2'][b]['ci90'][0], 4)}, {fmt(r['B2'][b]['ci90'][1], 4)}]" for b in gm.BOUNDS) + f" | {r['B2_status_over_bounds']} |")
        b3 = r["B3"]
        if b3.get("n"):
            L += ["", f"B3: extremes {fmt(b3['share_extreme'])} (below 0.4x {fmt(b3['share_below_0_4'])}, above 2.5x {fmt(b3['share_above_2_5'])}; non-positive IV {fmt(b3['share_nonpositive_iv'])}); family gap in points {json.dumps(_clean(b3['family_gap_points']))}; IQR ln(IV/P) {fmt(b3['iqr_ln_vp_positive_iv'])} on {b3['n_positive_iv']} positive IVs; (c) {b3['c_status']}; status {b3['status']}"]
        b4 = r["B4"]
        for k in ("revenue_growth", "operating_margin"):
            x = b4[k]
            if x["n"]:
                L.append(f"B4 {k}: n={x['n']}, median abs error engine {fmt(x['median_abs_error_engine'], 4)} vs naive {fmt(x['median_abs_error_naive'], 4)}; engine closer for {fmt(x['share_engine_closer'])} of names")
        L.append(f"B4 status: {b4['status']}")
    lab = "ge_300M"
    d = rep["diagnostics"][lab]
    L += ["", "## Diagnostics (>= $300M): IV / price by family", ""]
    for f, v in d["vp_by_family"].items():
        q = v.get("quantiles", {})
        L.append(f"- {f}: n={v['n']}, p10 {fmt(q.get('p10'))}, p50 {fmt(q.get('p50'))}, p90 {fmt(q.get('p90'))}; below 0.4x {fmt(v.get('share_below_0_4'))}; above 2.5x {fmt(v.get('share_above_2_5'))}; non-positive {fmt(v.get('share_nonpositive'))}")
    L += ["", "## Diagnostics (>= $300M): IV / price by industry (n >= 20)", ""]
    for f, v in d["vp_by_industry_n_ge_20"].items():
        q = v.get("quantiles", {})
        L.append(f"- {f}: n={v['n']}, p25 {fmt(q.get('p25'))}, p50 {fmt(q.get('p50'))}, p75 {fmt(q.get('p75'))}; below 0.4x {fmt(v.get('share_below_0_4'))}; above 2.5x {fmt(v.get('share_above_2_5'))}")
    L += ["", "## Diagnostics (>= $300M): extremes by family", "", "```", json.dumps(_clean(d["extremes_by_family"]), indent=1), "```"]
    L += ["", "## Diagnostics (>= $300M): terminal-value share", "", "```", json.dumps(_clean(d["tv_share"]), indent=1), "```"]
    L += ["", "## Diagnostics (>= $300M): model disagreement by family (ln primary / secondary)", "", "```", json.dumps(_clean(d["model_disagreement_by_family"]), indent=1), "```"]
    L += ["", "## Diagnostics (>= $300M): structure", "", "```", json.dumps(_clean(d["structure"]), indent=1), "```"]
    for dt, ex in rep["extremes_listings"].items():
        for side in ("top", "bottom"):
            L += ["", f"## {dt}: {side} 30 by IV / price (all valued names, both market-cap groups)", "",
                  "| ticker | industry | family | group | IV/P | IV/P at P50 inputs | secondary/P | TV share | invalid | COE | WACC | rev $M | margin | g latest | inputs P10/P50/P90 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for r in ex[side]:
                inp = "; ".join(f"{k} {fmt(v[0], 3)}/{fmt(v[1], 3)}/{fmt(v[2], 3)}" for k, v in r["inputs_p10_p50_p90"].items())
                L.append(f"| {r['ticker']} | {r['industry']} | {r['family']} | {r['mcap_group']} | {fmt(r['vp'], 2)} | {fmt(r['vp_point_p50_inputs'], 2)} | {fmt(r['secondary_vp'], 2)} | {fmt(r['tv_share_p50'], 2)} | {fmt(r['invalid_share'], 2)} | {fmt(r['coe'], 3)} | {fmt(r['wacc'], 3)} | {fmt((r['revenue'] or 0) / 1e6, 0)} | {fmt(r['op_margin'], 3)} | {fmt(r['growth_latest'], 3)} | {inp} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--extremes-dates", nargs="*", default=["2019-12-31", "2022-06-30"])
    ap.add_argument("--adjusted-proxy", type=Path, help="re-express the price-dependent scores on the adjusted-only proxy basis from this price file")
    a = ap.parse_args(argv)
    out = a.out_dir or a.run_dir
    out.mkdir(parents=True, exist_ok=True)
    rep = build(a.run_dir, a.resamples, tuple(a.extremes_dates), a.adjusted_proxy)
    (out / "gate1_dev_report.json").write_text(json.dumps(_clean(rep), indent=1), encoding="utf-8")
    (out / "gate1_dev_report.md").write_text(render(rep), encoding="utf-8")
    print("written", out)


if __name__ == "__main__":
    main()
