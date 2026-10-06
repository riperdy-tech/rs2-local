"""Build the gate-1 development report from a run folder: coverage, B1-B4 under the three bounds (PROVISIONAL), and the structural diagnostics.

    python -m rebuild_harness.gate1_report RUN_DIR [--out-dir OUT] [--resamples 2000] [--extremes-dates 2019-12-31 2021-12-31]

Writes gate1_dev_report.json and gate1_dev_report.md.  Reads records only; it forms no new return.  Every figure is PROVISIONAL (see gate1_metrics).
B1, B2 and B3 are on the dates to 2021-12-31 (Addendum H6), B4 on every date; the run's `run_meta.json` (commit, priors folder, price file hash) is copied into the report.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from . import gate1_metrics as gm
from . import gate1_v2 as v2m


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


def build(run_dir, resamples=2000, extremes_dates=("2019-12-31", "2021-12-31"), adjusted_proxy=None, v2=False, n_boot=v2m.N_BOOT):
    ran = []
    rows, counters, full = gm.load_run(run_dir, keep_all_for=tuple(extremes_dates), ran=ran)
    proxy_missing = None
    if adjusted_proxy is not None:
        proxy_missing = gm.apply_adjusted_proxy(rows, json.loads(Path(adjusted_proxy).read_text(encoding="utf-8")))
    big = [r for r in rows if r["mcap_group"] == ">=300M"]
    small = [r for r in rows if r["mcap_group"] == "<300M"]
    big_fresh = [r for r in big if not r["stale"]]
    meta_p = Path(run_dir) / "run_meta.json"
    rep = {"run_meta": json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else None, "provisional": gm.PROVISIONAL, "price_basis": "adjusted-only proxy (IV/price, earnings and FCF yields times Close/Adj Close)" if adjusted_proxy else "raw monthly pull of 2026-10-01 (Addendum H9): the traded close rebuilt from the split-adjusted Close and the split events; month-end, survivors only",
           "adjusted_proxy_rows_without_both_bars": proxy_missing, "run_dir": str(run_dir), "n_valued": len(rows), "n_valued_ge_300M": len(big), "n_valued_lt_300M": len(small),
           "coverage": gm.coverage_tables(counters), "per_date": per_date(rows)}
    if v2:
        # registration v2 (REGISTRATION_gate1_v2_DRAFT.md): the price-basis variant (B5, reported) is the adjusted-only proxy of the run's own price file, on copies of the rows
        rep["registration"] = "v2"
        pf = Path((rep["run_meta"] or {}).get("price_file") or "")
        proxy_rows = None
        if adjusted_proxy is None and pf.is_file():
            proxy_rows = [dict(r, score=dict(r["score"])) for r in big]
            rep["price_basis_variant_rows_without_both_bars"] = gm.apply_adjusted_proxy(proxy_rows, json.loads(pf.read_text(encoding="utf-8")))
        rep["gate1_universe_ge_300M"] = v2m.v2_bars(big, ">=300M", n_boot, price_basis_rows=proxy_rows)
        rep["sub_300M_reported_separately"] = v2m.v2_bars(small, "<300M", max(199, n_boot // 5), with_variants=False)
        rep["sensitivity_ge_300M_base_year_within_15_months"] = v2m.v2_bars(big_fresh, ">=300M, base year <= 15 months old", max(199, n_boot // 5), with_variants=False)
    else:
        rep["gate1_universe_ge_300M"] = gm.three_bounds(big, ">=300M", resamples, return_end=gm.RETURN_DATES_END)
        rep["sub_300M_reported_separately"] = gm.three_bounds(small, "<300M", resamples, return_end=gm.RETURN_DATES_END)
        rep["sensitivity_ge_300M_base_year_within_15_months"] = gm.three_bounds(big_fresh, ">=300M, base year <= 15 months old", resamples, return_end=gm.RETURN_DATES_END)
    for label, rs in (("ge_300M", big), ("lt_300M", small)):
        rep.setdefault("diagnostics", {})[label] = {
            "vp_overall": gm.distribution_block([r["vp"] for r in rs]), "vp_by_family": gm.vp_by(rs, lambda r: r["family"]),
            "vp_by_industry_n_ge_20": gm.vp_by(rs, lambda r: r["industry"] or "unmapped", 20),
            "vp_by_date": gm.vp_by(rs, lambda r: r["date"]), "extremes_by_family": gm.extremes_by_family(rs),
            "tv_share": gm.tv_share_distribution(rs), "model_disagreement_by_family": gm.disagreement_by_family(rs), "structure": gm.structure_stats(rs),
            "coe_by_family": gm.coe_by_family(rs), "draw_rules_valued_names": gm.draw_rule_stats(rs)}
    rep["prior_shapes_all_names_the_engine_ran_on"] = gm.prior_shape_stats(ran)
    rep["widths_by_level_band_all_names_the_engine_ran_on"] = gm.widths_by_level_band(ran)
    pdir = (rep["run_meta"] or {}).get("priors_dir")
    rep["priors_tables_by_level_band"] = gm.prior_table_widths(pdir) if pdir and Path(pdir).exists() else None
    rep["extremes_listings"] = {d: gm.extremes_listing(full[d], 30) for d in extremes_dates if d in full}
    return rep


def fmt(x, nd=3):
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def render(rep):
    rm = rep.get("run_meta") or {}
    L = ["# Gate 1, development run: report", "", "**" + rep["provisional"] + "**", "", f"Price basis: {rep['price_basis']}", "",
         f"Run: commit {rm.get('git_head')}, {len(rm.get('dates') or [])} dates, priors folder {rm.get('priors_dir') or 'default'}, price file sha256 {str(rm.get('price_file_sha256'))[:16]}, stamp {rm.get('price_stamp')}", "",
         f"Valued: {rep['n_valued']} (market cap >= $300M: {rep['n_valued_ge_300M']}; below: {rep['n_valued_lt_300M']})", ""]
    L += ["## Valued names and median IV / price by date", "", "| date | valued | >= $300M | median IV/price | share < 0.4x | share > 2.5x | median invalid-draw share | median COE |", "|---|---|---|---|---|---|---|---|"]
    for d, v in rep["per_date"].items():
        L.append(f"| {d} | {v['n_valued']} | {v['n_valued_ge_300M']} | {fmt(v['median_vp'])} | {fmt(v['share_below_0_4'])} | {fmt(v['share_above_2_5'])} | {fmt(v['median_invalid_share'])} | {fmt(v['median_coe'])} |")
    cov = rep["coverage"]
    L += ["", "## Coverage: refusals by reason (all dates)", ""] + [f"- {v}: {k}" for k, v in list(cov["refusals_by_reason"].items())[:40]]
    nb = {k: v for k, v in cov["refusals_by_reason"].items() if k.startswith("family_not_built")}
    L += ["", "## Scope: family_not_built by kind (name-dates, all dates; Addendum H4)", ""] + [f"- {v}: {k}" for k, v in nb.items()]
    L += ["", "## Invalid draws (Addendum H5): reasons, over every name the engine ran on", "", f"names the engine ran on: {cov.get('names_the_engine_ran_on')}", "",
          "by draws:"] + [f"- {v}: {k}" for k, v in cov.get("invalid_draw_reasons_by_draws", {}).items()] + ["", "by names (a name counts once per reason):"] + [
              f"- {v}: {k}" for k, v in cov.get("invalid_draw_reasons_by_names", {}).items()] + ["", "by family, in draws:"] + [
              f"- {v}: {k}" for k, v in cov.get("invalid_draw_reasons_by_family_and_draws", {}).items()]
    dr = cov.get("draw_rules") or {}
    L += ["", "## Draw rules (Addendum I2): valid draws each rule applied to, over every name the engine ran on", "",
          f"names by family: {dr.get('names_by_family')}; draws by family: {dr.get('draws_by_family')}", "", "| family and rule | draws | share of the family's draws | names | share of the family's names |", "|---|---|---|---|---|"]
    for k, v in (dr.get("draws_by_family_and_rule") or {}).items():
        L.append(f"| {k} | {v} | {fmt((dr.get('share_of_draws_by_family_and_rule') or {}).get(k), 4)} | {(dr.get('names_by_family_and_rule') or {}).get(k)} | "
                 f"{fmt((dr.get('share_of_names_by_family_and_rule') or {}).get(k), 3)} |")
    L += ["", "## Priors that refused an input for a cell under 50 (Addendum I5), named: name-dates", ""] + [f"- {v}: {k}" for k, v in (cov.get("priors_unavailable_named") or {}).items()]
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
        if rep.get("registration") == "v2":
            L += render_bars_v2(r, title)
            continue
        L += ["", f"## {title}", "", f"valued: {r['n_valued']}", ""]
        L.append("| bar | " + " | ".join(gm.BOUNDS) + " | status over bounds |")
        L.append("|---|---|---|---|---|")
        L.append("| B1 mean engine coefficient [90% lower, upper] | " + " | ".join(f"{fmt(r['B1'][b]['mean_coef'], 4)} [{fmt(r['B1'][b]['ci90'][0], 4)}, {fmt(r['B1'][b]['ci90'][1], 4)}] ({r['B1'][b]['n_dates']} dates)" for b in gm.BOUNDS) + f" | {r['B1_status_over_bounds']} |")
        L.append("| B2 neutral spread (residual) [90%] | " + " | ".join(f"{fmt(r['B2'][b]['mean_spread'], 4)} ({fmt(r['B2'][b]['mean_spread_residual'], 4)}) [{fmt(r['B2'][b]['ci90'][0], 4)}, {fmt(r['B2'][b]['ci90'][1], 4)}]" for b in gm.BOUNDS) + f" | {r['B2_status_over_bounds']} |")
        L.append(f"dates: B1, B2, B3 on {len(r.get('return_dates') or [])} dates ({(r.get('return_dates') or ['?'])[0]} .. {(r.get('return_dates') or ['?'])[-1]}); B4 on {len(r.get('b4_dates') or [])} dates "
                 f"({(r.get('b4_dates') or ['?'])[0]} .. {(r.get('b4_dates') or ['?'])[-1]}); valued name-dates on the return dates {r.get('n_valued_return_dates')}")
        ym = r["B1"]["excluded"].get("yardstick_missing_share") or {}
        L.append("yardstick coverage (share of B1 names imputed at the median rank): " + ", ".join(f"{k.replace('yardstick_', '')} {fmt(v)}" for k, v in ym.items()))
        b3 = r["B3"]
        if b3.get("n"):
            L += ["", f"B3: extremes {fmt(b3['share_extreme'])} (below 0.4x {fmt(b3['share_below_0_4'])}, above 2.5x {fmt(b3['share_above_2_5'])}; non-positive IV {fmt(b3['share_nonpositive_iv'])}); family gap in points {json.dumps(_clean(b3['family_gap_points']))}; IQR ln(IV/P) {fmt(b3['iqr_ln_vp_positive_iv'])} on {b3['n_positive_iv']} positive IVs (floor {b3['c_floor']}); (c) {b3['c_status']}; status {b3['status']}"]
        b3a = r.get("B3_all_dates") or {}
        if b3a.get("n"):
            L.append(f"B3 on every date: extremes {fmt(b3a['share_extreme'])} (below 0.4x {fmt(b3a['share_below_0_4'])}, above 2.5x {fmt(b3a['share_above_2_5'])}); family gap in points "
                     f"{json.dumps(_clean(b3a['family_gap_points']))}; IQR ln(IV/P) {fmt(b3a['iqr_ln_vp_positive_iv'])}; status {b3a['status']}")
        for key, lab in (("B4", "B4 (every date)"), ("B4_return_dates_only", "B4 (the return dates only)")):
            b4 = r[key]
            for k in ("revenue_growth", "operating_margin"):
                x = b4[k]
                if x["n"]:
                    L.append(f"{lab} {k}: n={x['n']}, median abs error engine {fmt(x['median_abs_error_engine'], 4)} vs naive {fmt(x['median_abs_error_naive'], 4)}; engine closer for {fmt(x['share_engine_closer'])} of names")
            L.append(f"{lab} status: {b4['status']}")
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
    L += ["", "## Diagnostics (>= $300M): cost of equity by family (Addendum I3: financials on the levered industry beta)", "", "```", json.dumps(_clean(d["coe_by_family"]), indent=1), "```"]
    L += ["", "## Diagnostics (>= $300M): draw rules over the valued names (floored equity, no-growth draws)", "", "```", json.dumps(_clean(d["draw_rules_valued_names"]), indent=1), "```"]
    L += ["", "## Prior widths by current level band, over every name the engine ran on (Addendum I1)", "", "```", json.dumps(_clean(rep["widths_by_level_band_all_names_the_engine_ran_on"]), indent=1), "```"]
    L += ["", "## The priors tables by level band (the folder the run read)", "", "```", json.dumps(_clean(rep.get("priors_tables_by_level_band")), indent=1), "```"]
    L += ["", "## Prior shapes over every name the engine ran on (valued or refused for invalid draws), by family", "", "```", json.dumps(_clean(rep["prior_shapes_all_names_the_engine_ran_on"]), indent=1), "```"]
    for dt, ex in rep["extremes_listings"].items():
        for side in ("top", "bottom"):
            L += ["", f"## {dt}: {side} 30 by IV / price (all valued names, both market-cap groups)", "",
                  "| ticker | industry | family | group | IV/P | IV/P at P50 inputs | secondary/P | TV share | invalid | COE | WACC | rev $M | margin | g latest | L0 (3y ROIC) | industry ROIC | terminal RONIC | g term | inputs P10/P50/P90 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for r in ex[side]:
                inp = "; ".join(f"{k} {fmt(v[0], 3)}/{fmt(v[1], 3)}/{fmt(v[2], 3)}" for k, v in r["inputs_p10_p50_p90"].items())
                L.append(f"| {r['ticker']} | {r['industry']} | {r['family']} | {r['mcap_group']} | {fmt(r['vp'], 2)} | {fmt(r['vp_point_p50_inputs'], 2)} | {fmt(r['secondary_vp'], 2)} | {fmt(r['tv_share_p50'], 2)} | {fmt(r['invalid_share'], 2)} | {fmt(r['coe'], 3)} | {fmt(r['wacc'], 3)} | {fmt((r['revenue'] or 0) / 1e6, 0)} | {fmt(r['op_margin'], 3)} | {fmt(r['growth_latest'], 3)} | {fmt(r.get('roic3') if r['family'] != 'financial' else r.get('rote3'), 3)} | {fmt(r.get('industry_roic') if r['family'] != 'financial' else r.get('industry_rote'), 3)} | {fmt(r.get('ronic_terminal') if r['family'] != 'financial' else r.get('rote_terminal'), 3)} | {fmt(r.get('g_term'), 4)} | {inp} |")
    return "\n".join(L) + "\n"


def _f(x, nd=4):
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def _p(x, nd=1):
    return "n/a" if x is None else f"{100 * x:.{nd}f}%"


def render_bars_v2(r, title):
    """The registration-v2 bars of one universe as markdown lines."""
    B = gm.BOUNDS
    L = ["", f"## {title} (registration v2)", "", f"valued name-dates: {r['n_valued']} (on the return dates {r['n_valued_return_dates']}); return dates {len(r['return_dates'])} "
         f"({(r['return_dates'] or ['?'])[0]} .. {(r['return_dates'] or ['?'])[-1]}); B4 dates {len(r['b4_dates'])}; wild-cluster bootstrap draws {r['n_boot']}", "",
         f"**Outcome (provisional): {r['outcome']}.** {r['outcome_rule']}", "", "| bar | " + " | ".join(B) + " | over the bounds |", "|---|" + "---|" * (len(B) + 1)]
    bb = r["by_bound"]
    st = r["bar_status_over_bounds"]
    L.append("| B1 incremental information | " + " | ".join(bb[b]["B1"]["status"] for b in B) + f" | {st['B1']} |")
    L.append("| B2 residual quintile spread | " + " | ".join(bb[b]["B2"]["status"] for b in B) + f" | {st['B2']} |")
    L.append("| B3 level | " + " | ".join(r["B3"]["status"] for _ in B) + f" | {st['B3']} |")
    L.append("| B4 forecasts | " + " | ".join(r["B4"]["status"] for _ in B) + f" | {st['B4']} |")
    L.append("| B5 stability (direction) | " + " | ".join(bb[b]["B5"]["status"] for b in B) + f" | {st['B5']} |")
    L += ["", "### B1: pooled regression, industry and date effects, wild-cluster bootstrap-t by date (one-sided 90% lower bound)", "",
          "| bound | coefficient | se (date-clustered) | one-sided 90% lower bound | bootstrap p (H0: <= 0) | positive monthly coefficients | mean monthly coefficient | n | dates |", "|---|---|---|---|---|---|---|---|---|"]
    for b in B:
        x = bb[b]["B1"]
        if x.get("n"):
            L.append(f"| {b} | {_f(x['beta'])} | {_f(x['se'])} | {_f(x['lower_90_one_sided'])} | {_f(x['p_one_sided'], 3)} | {_p(x['share_positive_monthly_coefficients'])} of {x['n_months']} | {_f(x['mean_monthly_coefficient'])} | {x['n']} | {x['n_clusters']} |")
        else:
            L.append(f"| {b} | not computed | | | | | | {x.get('n')} | |")
    L += ["", "### B2: industry-neutral top-minus-bottom quintile spread of the engine's residual after the yardsticks (pass > 0, strong pass >= +3 pp); the raw spread is reported", "",
          "| bound | residual spread | 90% interval over dates | raw spread | dates with a positive residual spread | status |", "|---|---|---|---|---|---|"]
    for b in B:
        x = bb[b]["B2"]
        L.append(f"| {b} | {_p(x['mean_spread_residual'], 2)} | [{_p(x['ci90_residual'][0], 2)}, {_p(x['ci90_residual'][1], 2)}] | {_p(x['mean_spread_raw'], 2)} | {_p(x['share_dates_positive_residual'])} | {x['status']} |")
    b3 = r["B3"]
    if b3.get("n"):
        d = b3["diagnostics"]
        L += ["", f"### B3: level. Universe median IV / price {_f(b3['median_vp'], 3)} against the band {b3['band']}: **{b3['status']}**", "",
              f"n = {b3['n']}; share of dates whose own median is inside the band {_p(b3['share_dates_median_in_band'])}; family medians {json.dumps(_clean(b3['family_medians']))}",
              f"Diagnostics (no bar): extremes {_p(d['share_extreme'])} (below 0.4x {_p(d['share_below_0_4'])}, above 2.5x {_p(d['share_above_2_5'])}; non-positive IV {_p(d['share_nonpositive_iv'])}); family gap in points "
              f"{json.dumps(_clean(d['family_gap_points']))}; IQR of ln(IV/price) {_f(d['iqr_ln_vp_positive_iv'], 3)} on {d['n_positive_iv']} positive IVs",
              "", "median IV / price by date: " + ", ".join(f"{k} {v:.2f}" for k, v in b3["median_vp_by_date"].items())]
    for key, lab in (("B4", "B4: forecasts, every development date"), ("B4_return_dates_only", "B4 on the return dates only")):
        b4 = r[key]
        L += ["", f"### {lab}: **{b4['status']}**", "", "| family and measure | n | dates | engine median abs. error | naive median abs. error | engine closer for | P10..P90 coverage (target 80%) | directional accuracy (n) | status |", "|---|---|---|---|---|---|---|---|---|"]
        for k, x in b4["by_family_measure"].items():
            if x["n"]:
                L.append(f"| {k} | {x['n']} | {x['n_dates']} | {_f(x['median_abs_error_engine'])} | {_f(x['median_abs_error_naive'])} | {_p(x['share_engine_closer'])} | {_p(x['coverage_p10_p90'])} | "
                         f"{_p(x['directional_accuracy'])} ({x['n_direction']}) | {x['status']} |")
            else:
                L.append(f"| {k} | 0 | | | | | | | not computed |")
    L += ["", "### B5: stability of direction (B1 and B2 positive under each bound and without the 1% of observations with the largest |residual|)", "", "| bound | " + " | ".join(
        ["B1 > 0", "B2 > 0", "B1 > 0 without top 1%", "B2 > 0 without top 1%"]) + " | removed | status |", "|---|---|---|---|---|---|---|"]
    for b in B:
        x = bb[b]["B5"]
        if x.get("direction_checks"):
            c = x["direction_checks"]
            L.append(f"| {b} | {c['B1_coefficient_positive']} | {c['B2_residual_spread_positive']} | {c['B1_coefficient_positive_without_top1pct_abs_resid']} | "
                     f"{c['B2_residual_spread_positive_without_top1pct_abs_resid']} | {x['without_top1pct_abs_resid']['n_removed']} | {x['status']} |")
    if bb[B[0]].get("variants_reported"):
        L += ["", "### B5 reported variants (no bar)", "", "| variant | bound | B1 coefficient | lower bound | B1 | B2 residual spread | B2 |", "|---|---|---|---|---|---|---|"]
        for b in B:
            for name, v in bb[b]["variants_reported"].items():
                v1, v2_ = v["B1"], v["B2"]
                L.append(f"| {name} | {b} | {_f(v1.get('beta'))} | {_f(v1.get('lower_90_one_sided'))} | {v1['status']} | {_p(v2_['mean_spread_residual'], 2)} | {v2_['status']} |")
    return L


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--extremes-dates", nargs="*", default=["2019-12-31", "2021-12-31"])
    ap.add_argument("--adjusted-proxy", type=Path, help="re-express the price-dependent scores on the adjusted-only proxy basis from this price file")
    ap.add_argument("--v2", action="store_true", help="registration v2 bars (REGISTRATION_gate1_v2_DRAFT.md) instead of the v1 bars")
    ap.add_argument("--n-boot", type=int, default=v2m.N_BOOT, help="wild-cluster bootstrap draws for B1 (registration v2)")
    a = ap.parse_args(argv)
    out = a.out_dir or a.run_dir
    out.mkdir(parents=True, exist_ok=True)
    rep = build(a.run_dir, a.resamples, tuple(a.extremes_dates), a.adjusted_proxy, v2=a.v2, n_boot=a.n_boot)
    (out / "gate1_dev_report.json").write_text(json.dumps(_clean(rep), indent=1), encoding="utf-8")
    (out / "gate1_dev_report.md").write_text(render(rep), encoding="utf-8")
    print("written", out)


if __name__ == "__main__":
    main()
