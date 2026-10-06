"""report.py - PRIORS_REPORT.md from the vintages' tables.json (the report is generated, never typed: every number in it is a table cell).

    python -m valuation.priors_build.report [out_path]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from valuation.priors_build import config as C
from valuation.priors_build.report_head import HEAD

GROWTH_LABELS = ["<-10%", "-10..0%", "0..5%", "5..10%", "10..20%", "20..40%", ">40%"]
SIZE_LABELS = ["<$50M", "$50-250M", "$250M-1B", "$1-5B", "$5-20B", ">$20B"]
ROTE_LABELS = ["<=0%", "0..5%", "5..10%", "10..15%", ">15%"]
FCF_G = ["<=0%", "0..10%", "10..25%", ">25%"]
TERC = ["low", "mid", "high"]


def f(x, d=3, pct=False):
    if x is None:
        return "-"
    return f"{x * 100:.1f}%" if pct else f"{x:.{d}f}"


def qline(q, pct=True, d=3):
    if not q or q.get("n", 0) == 0:
        return "n=0"
    return " / ".join(f(q.get(f"p{p}"), d, pct) for p in ("5", "10", "25", "50", "75", "90", "95")) + f"  (n={q['n']})"


def rev_line(q):
    return " / ".join(f"{q[f'p{p}'] / 1e6:,.1f}M" for p in ("5", "10", "25", "50", "75", "90", "95")) + f"  (n={q['n']})"


def rng_label(r, labels):
    return labels[r[0]] if r[0] == r[1] else f"{labels[r[0]]} .. {labels[r[1]]}"


def md_table(header, rows):
    out = ["", "| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def vintage_section(y):
    T = json.loads((C.vintage_dir(y) / "tables.json").read_text(encoding="utf-8"))
    L = [f"## Vintage {y}  (cut {T['cut_date']}, serves valuation dates in {y + 1})", ""]
    L.append(f"obs sha256 `{T['obs_sha256'][:16]}`, store `{T['store_fingerprint_sha256'][:16]}`, tables sha256 "
             f"`{(C.vintage_dir(y) / 'tables.sha256').read_text().strip()[:16]}`; {T['observations']:,} company-years; quantiles are P5 / P10 / P25 / P50 / P75 / P90 / P95.")
    P = T["population"]
    L += ["", f"### State at the cut ({P['companies_current_at_cut']:,} companies with a fiscal year ending within 15 months; families {P['family_counts']})", ""]
    rows = [[n, (qline(P[k], pct=pct, d=3) if k != "revenue" else rev_line(P[k]))] for n, k, pct in (
        ("revenue (USD)", "revenue", False), ("growth, latest year", "growth_latest", True), ("growth, 3-year CAGR", "growth_3y_cagr", True),
        ("operating margin", "operating_margin", True), ("margin minus its 8-year median", "margin_dev_from_8y_median", True),
        ("cyclicality score", "cyclicality_score", False), ("ROIC", "roic", True), ("ROTE", "rote", True))]
    L += md_table(["state variable", "quantiles"], rows)
    L += ["", f"cyclicality terciles {[round(x, 3) for x in T['cuts']['cyc_terciles']]}, quintiles {[round(x, 3) for x in T['cuts']['cyc_quintiles']]}; "
          f"ROIC terciles {[round(x, 3) for x in T['cuts']['roic_terciles']]} (measured in this vintage).", ""]
    # g1
    L += ["### g1: next-year growth by growth delivered (size pooled; the full size x growth cells are in tables.json)", ""]
    for fam in ("operating", "commodity", "financial"):
        for basis in ("g3", "latest"):
            g = T["g1"][fam][basis]
            L.append("")
            L.append(f"**{fam}, growth delivered = {'3-year CAGR' if basis == 'g3' else 'latest year'}"
                     f"{' (tangible book)' if fam == 'financial' else ''}** - {len(g['cells'])} size x growth cells "
                     f"({sum(1 for c in g['cells'] if c['merged_rows'] or c['merged_cols'])} merged, {sum(1 for c in g['cells'] if c['thin'])} still thin)")
            rows = []
            for c in g["size_pooled_cells"]:
                rows.append([rng_label(c["col"], GROWTH_LABELS) + (" (merged)" if c["merged_cols"] else ""), c["n"], qline(c).split("  (n")[0],
                             f(c.get("baseline_growth_median"), pct=True), f(c.get("baseline_medae"), pct=True), f(c.get("cell_median_medae"), pct=True)])
            L += md_table(["growth delivered", "n", "g1 quantiles", "baseline g1 (median)", "baseline median abs err", "cell-median median abs err"], rows)
            L.append("")
    # decay
    L += ["### growth_decay: median ratio (g_k - T) / (g_1 - T) by growth delivered (3-year CAGR)", ""]
    for fam in ("operating", "financial"):
        d = T["growth_decay"][fam]
        if not d.get("terminal_reference"):
            L.append(f"{fam}: no terminal reference (no horizon with 500 observations)")
            continue
        L.append(f"**{fam}**: T = {f(d['terminal_reference']['value'], pct=True)} (year-alone growth at k = {d['terminal_reference']['horizon_k']}).  Cells: ratio, n of the ratio.")
        rows = []
        for b in d["buckets"]:
            rows.append([rng_label(b["bucket"], GROWTH_LABELS) + (" (merged)" if b["merged"] else ""), b["n_k1"]] +
                        [(f"{k['ratio_median']:.2f} ({k['n_ratio']})" if k.get("ratio_median") is not None else "-") for k in b["ks"]])
        L += md_table(["bucket", "n k=1"] + [f"k={k}" for k in range(1, 11)], rows)
        L.append("")
        rows = []
        for b in d["buckets"]:
            rows.append([rng_label(b["bucket"], GROWTH_LABELS)] + [(f"{k['raw_p50'] * 100:.0f}% [{k['raw_p25'] * 100:.0f}, {k['raw_p75'] * 100:.0f}]" if k.get("raw_p50") is not None else "-") for k in b["ks"]])
        L.append(f"raw paths ({fam}): median year-alone growth [P25, P75]")
        L += md_table(["bucket"] + [f"k={k}" for k in range(1, 11)], rows)
        L.append("")
    # margin retention
    m = T["margin_retention"]
    L += ["### margin_retention (A2 on the point-in-time layer): median fraction of the deviation still open, [P25, P75], n",
          "", f"Record rule >= 5 margin years in t-7..t; |dev| >= 0.5 points; {m['filter']['obs_used']:,} observations used of {m['filter']['obs_with_record']:,} with a record; "
          f"{m['filter']['excluded_small_dev']:,} had |dev| < 0.5 points; {f(m['filter']['share_abs_margin_gt_100pct'], pct=True)} have |margin| > 100% (kept, flagged).", ""]
    rows = []
    for key, bd in m["bands"].items():
        rows.append([key, bd["n"]] + [(f"{r['median']:.2f} [{r['p25']:.2f}, {r['p75']:.2f}] n={r['n']}" if r.get("median") is not None else f"- n={r['n']}") for r in bd["ks"]])
    L += md_table(["band", "n obs"] + [f"k={k}" for k in range(1, 8)], rows)
    L += ["", "level 5 years on, about the median-retention path (the spread behind `margin_target`): residual quantiles", ""]
    L += md_table(["band", "residual quantiles (margin points as fractions)"], [[k, qline(v, pct=True)] for k, v in m["residual_k5"].items()])
    nb = T["normalization"]
    L += ["", "**normalization_curve(score)**: median ratio by score quintile (signs pooled)", ""]
    rows = []
    for b in nb["bands"]:
        a = b["all"]
        rows.append([f"Q{b['band'] + 1}", f(b["score_median"]), a["n"]] + [(f"{r['median']:.2f}" if r.get("median") is not None else "-") for r in a["ks"]])
    L += md_table(["quintile", "median score", "n"] + [f"k={k}" for k in range(1, 8)], rows)
    # ronic
    R = T["ronic"]
    L += ["", f"### ronic: 3-year change in NOPAT / change in invested capital (defined where capital grew by >= {int(R['ic_growth_floor'] * 100)}% of its base)", ""]
    rows = []
    for fam, fo in R["families"].items():
        rows.append([fam, "all (floored)", qline(fo["floored_all"])])
        rows.append([fam, "all (no floor, dIC > 0)", qline(fo["unfloored"])])
        for b, bd in fo["bands"].items():
            rows.append([fam, f"ROIC {b}", qline(bd)])
    L += md_table(["family", "band", "quantiles"], rows)
    for nm, key in (("ronic_fade (proxy: retention of ROIC's excess over the population median ROIC)", "ronic_fade"), ("excess_fade, financial (proxy, ROTE)", "excess_fade_financial")):
        rf = T.get(key)
        if rf:
            L += ["", f"{nm}: reference {f(rf['reference'], pct=True)}, n base {rf['n_base']}: " +
                  ", ".join(f"k={r['k']}: {r['median']:.2f} (n={r['n']})" for r in rf["ks"] if r.get("median") is not None)]
    # terminal
    Tm = T["terminal"]
    L += ["", f"### g_terminal: annualised revenue growth over K_eff = {Tm['K_eff']} years (complete observations by k: {Tm['complete_obs_by_k']})", ""]
    rows = []
    for fam, strata in Tm["families"].items():
        for sname in ("all", "shrinking", "not_shrinking"):
            s = strata.get(sname)
            if not s:
                continue
            rows.append([fam, sname, qline(s["complete"]), qline(s["with_delisted"]), qline(s["without_ceased"]), s["truncated_added"],
                         f(s["share_of_complete_from_companies_that_later_ceased"], pct=True)])
    L += md_table(["family", "stratum", "complete (survived to K)", "with delisted (known at the cut; truncated horizon >= 3)", "without companies that later ceased",
                   "truncated added", "share of complete from later-ceased"], rows)
    L += ["", "revenue-trend persistence of shrinking companies (trailing 8-year slope of ln revenue < 0): forward CAGR over k years", ""]
    rows = []
    for fam, so in Tm["shrinking"].items():
        for k, v in so["ks"].items():
            rows.append([fam, k, so["n_shrinking_obs"], qline(v["complete"]), qline(v["without_ceased"])])
    L += md_table(["family", "k", "shrinking obs", "complete", "without later-ceased"], rows)
    # financial
    rr = T["rote_retention"]
    L += ["", f"### Financial family: rote_retention (A2 on ROTE), {rr['obs_used']:,} observations", ""]
    rows = [[k, bd["n"]] + [(f"{r['median']:.2f} [{r['p25']:.2f}, {r['p75']:.2f}] n={r['n']}" if r.get("median") is not None else f"- n={r['n']}") for r in bd["ks"]] for k, bd in rr["bands"].items()]
    L += md_table(["band", "n obs"] + [f"k={k}" for k in range(1, 8)], rows)
    L += ["", "rote_target residual (level 5 years on about the median path): " + "; ".join(f"{k}: {qline(v)}" for k, v in rr["residual_k5"].items())]
    # references
    E = T["ev_fcf"]
    L += ["", f"### ev_fcf_multiple: EV / FCFF1 at the observation-date price (survivors with a price: {E['n']:,} observations; "
          f"FCFF1 not positive {E['fcff1_not_positive']:,}, EV not positive {E['ev_not_positive']:,})", ""]
    if E.get("cells"):
        rows = [[rng_label(c["row"], FCF_G) + (" (m)" if c["merged_rows"] else ""), rng_label(c["col"], TERC) + (" (m)" if c["merged_cols"] else ""), c["n"],
                 qline(c, pct=False, d=1).split("  (n")[0]] for c in E["cells"]]
        L += md_table(["realised next-year growth", "ROIC tercile", "n", "EV/FCFF1 quantiles"], rows)
        L.append(f"pooled: {qline(E['pooled'], pct=False, d=1)}")
    else:
        L.append("no cells (no price panel or no observations)")
    Pt = T["ptbv"]
    L += ["", f"### ptbv_of_rote: price / tangible book by ROTE (financials, survivors with a price: {Pt['n']:,})", ""]
    rows = [[rng_label(g["bucket"], ROTE_LABELS) + (" (m)" if g["merged"] else ""), g["n"], f(g.get("rote_median"), pct=True), qline(g, pct=False, d=2).split("  (n")[0]] for g in Pt["groups"]]
    L += md_table(["ROTE bin", "n", "median ROTE", "P/TBV quantiles"], rows) if rows else ["none"]
    # correlation
    Co = T["correlation"]
    L += ["", "### Input correlations (Spearman, and the Gaussian-copula r that reproduces it; pairwise-complete n)", ""]
    rows = []
    for fam, co in Co.items():
        for k, v in co["pairs"].items():
            rows.append([fam, k, f(v["spearman"], 2), f(v["copula_r"], 2), v["n"]])
    L += md_table(["family", "pair", "Spearman", "copula r", "n"], rows)
    # weights
    w = T["cyc_weights"]
    L += ["", "### Cyclicality-score weights (NNLS on development years)", "",
          f"fit data: base and outcome years <= {w['max_year']}; {w['rows']:,} rows ({w['obs']:,} observations x k = 1..5); loss: {w['loss']}.  Cross-fit: {w['cross_fit_rule']}."]
    if w.get("fitted_weights"):
        cf = w["cross_fit"]
        L.append(f"fitted weights (margin volatility, reversal frequency, autocorrelation, revenue cyclicality) = {[round(x, 3) for x in w['fitted_weights']]}; "
                 f"cross-fitted MSE ({cf['folds']} folds, {cf['rows_scored']:,} rows): " + ", ".join(f"{k} {v:.4f}" for k, v in cf["mse"].items()) +
                 f".  **Adopted: {w['adopted']}** - {w['reason']}.")
    else:
        L.append(f"no fit: {w.get('reason')}.  Equal weights kept.")
    # survivorship
    s = T["survivorship"]
    L += ["", "### Survivorship (hindsight label `ceased` = no periodic filing in the 18 months before the newest filing in the archive; reporting only, no prior reads it)", ""]
    rows = [["all family observations", s["all_family_obs"]["n"], f(s["all_family_obs"]["share_later_ceased"], pct=True), f(s["all_family_obs"]["share_ceased_before_cut"], pct=True)],
            ["with next year known (k=1)", s["k1_known"]["n"], f(s["k1_known"]["share_later_ceased"], pct=True), f(s["k1_known"]["share_ceased_before_cut"], pct=True)]]
    for k, v in s["by_family"].items():
        rows.append([f"family {k}", v["n"], f(v["share_later_ceased"], pct=True), f(v["share_ceased_before_cut"], pct=True)])
    for k, v in s["by_size"].items():
        rows.append([f"size {SIZE_LABELS[int(k)]}", v["n"], f(v["share_later_ceased"], pct=True), f(v["share_ceased_before_cut"], pct=True)])
    rows.append(["non-USD reporters", s["non_usd"]["n"], f(s["non_usd"]["share_later_ceased"], pct=True), f(s["non_usd"]["share_ceased_before_cut"], pct=True)])
    L += md_table(["population", "observations", "share from companies that later ceased", "share from companies that had ceased before the cut"], rows)
    L.append(f"\ncompanies with observations {s['companies']['with_obs']:,}; later ceased {s['companies']['later_ceased']:,}; ceased before the cut {s['companies']['ceased_before_cut']:,}.")
    if "by_basis" in s:
        L.append("family basis: " + ", ".join(f"{k}: {v['n']:,} obs, {f(v['share_later_ceased'], pct=True)} later ceased" for k, v in s["by_basis"].items()))
    # baseline
    b = T["baseline"]
    L += ["", "### The mechanical baseline (growth year 1 = trailing 3-year CAGR, margin held) beside the measured prior (in sample, median absolute error)", ""]
    g = b["g1"]
    L.append(f"g1: baseline {f(g['baseline_medae'], pct=True)} (median error {f(g['baseline_median_error'], pct=True)}) against the population median's {f(g['population_median_medae'], pct=True)} "
             f"on {g['n']:,} observations.")
    rows = [[k, v["n"], f(v["baseline_held_medae"], pct=True), f(v["median_path_medae"], pct=True)] for k, v in b["margin"].items()]
    L += md_table(["k", "n", "margin held: median abs err", "A2 median path: median abs err"], rows)
    L.append("")
    return L


def main(out):
    L = ["# PRIORS_REPORT: population priors at T (T-priors)", "",
         "Generated by `valuation/priors_build/report.py` from the vintages' `tables.json`; nothing in this file is typed by hand except the section texts.", ""]
    L += [HEAD.rstrip(), ""]
    wf = C.DATA_DIR / "walkforward.json"
    if wf.exists():
        W = json.loads(wf.read_text(encoding="utf-8"))
        L += ["## Walk-forward check: vintage Y-1 applied to the outcomes that became known in Y (true forecasts), against the mechanical baseline", "",
              "g1 is the operating family's size x growth cell (3-year-CAGR basis) against the trailing 3-year CAGR; margin is the A2 median path of the cyclicality band x sign "
              "against the margin held.  Median absolute errors; 'in P10..P90' / 'in P25..P75' are the shares of outcomes inside the cell's interval (nominal 80% / 50%).", ""]
        rows = []
        for y, v in W.items():
            g, m1, m3 = v.get("g1"), v.get("margin_k1"), v.get("margin_k3")
            rows.append([y, g["n"] if g else "-", f(g["baseline_medae"], pct=True) if g else "-", f(g["prior_p50_medae"], pct=True) if g else "-",
                         f(g["in_p10_p90"], pct=True) if g else "-", f(g["in_p25_p75"], pct=True) if g else "-",
                         (f"{m1['n']}: {f(m1['held_medae'], pct=True)} vs {f(m1['a2_path_medae'], pct=True)}" if m1 else "-"),
                         (f"{m3['n']}: {f(m3['held_medae'], pct=True)} vs {f(m3['a2_path_medae'], pct=True)}" if m3 else "-")])
        L += md_table(["year", "g1 n", "baseline med. abs err", "prior P50 med. abs err", "in P10..P90", "in P25..P75", "margin k=1: n: held vs path", "margin k=3: n: held vs path"], rows)
        L.append("")
    for y in C.REPORT_VINTAGES:
        L += vintage_section(y)
    Path(out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", out, len(L), "lines")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(C.DATA_DIR / "PRIORS_REPORT.md"))
