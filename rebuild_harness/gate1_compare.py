"""The gate-1 development rounds side by side: one table, from the rounds' report JSON (`gate1_report.build`'s output).

    python -m rebuild_harness.gate1_compare REPORT1.json REPORT2.json [REPORT3.json ...] [--labels "round 1" "round 2" ...] [--out file.md]

Round 1 was run on 16 dates 2019-03-31..2022-12-31 of the 24 it covered (2017-2018 held nothing) with the F4 rescale, a drawn terminal growth and incremental ROIC; round 2
(Addendum H) is the same harness on the re-dated set; round 3 (Addendum I) adds the level-band spreads, the draw rules, the levered financial beta, the financial terminal
retention and MIN_N.  The rounds differ in dates for B1-B3 (round 1: all 16; later rounds: the 12 to 2021-12-31), which the table states.
Everything is PROVISIONAL (raw monthly prices of today's listings, survivors only).  Nothing here forms a new figure: it reads the reports.
"""
import argparse
import json
from pathlib import Path


def _g(d, *path, default=None):
    for p in path:
        if d is None:
            return default
        d = d.get(p) if isinstance(d, dict) else None
    return default if d is None else d


def _f(x, nd=3):
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _b4(block, k, field):
    return _g(block, "B4", k, field)


def cells(r) -> list:
    """[(label, value as a string)] of one report, in table order."""
    u = r["gate1_universe_ge_300M"]
    d = r["diagnostics"]["ge_300M"]
    out = []
    out.append(("valued name-dates, market cap >= $300M", _f(r["n_valued_ge_300M"])))
    out.append(("valued name-dates, all", _f(r["n_valued"])))
    out.append(("dates behind B1-B3 (returns)", str(len(_g(u, "return_dates", default=[])) or _g(u, "B1", "excluded", "n_dates"))))
    out.append(("dates behind B4", str(len(_g(u, "b4_dates", default=[])) or "16")))
    for fam in ("operating", "financial", "commodity"):
        a = d["vp_by_family"].get(fam, {})
        out.append((f"median IV / price, {fam}", _f(_g(a, "quantiles", "p50"))))
        out.append((f"  n, {fam}", _f(a.get("n"))))
        out.append((f"  share non-positive IV, {fam}", _pct(a.get("share_nonpositive"))))
        out.append((f"  share below 0.4x / above 2.5x, {fam}", f"{_pct(a.get('share_below_0_4'))} / {_pct(a.get('share_above_2_5'))}"))
    a = d["vp_overall"]
    out.append(("median IV / price, all", _f(_g(a, "quantiles", "p50"))))
    out.append(("IV / price P10 / P90, all", f"{_f(_g(a, 'quantiles', 'p10'))} / {_f(_g(a, 'quantiles', 'p90'))}"))
    s = d["structure"]
    out.append(("invalid-draw share, median name", _pct(_g(s, "invalid_draw_share", "p50"))))
    out.append(("names (valued) with > 50% invalid draws", _pct(s.get("share_names_over_half_draws_invalid"))))
    out.append(("names (valued) with > 5% invalid draws", _pct(s.get("share_names_over_5pct_draws_invalid"))))
    out.append(("terminal-value share, median", _f(_g(d, "tv_share", "all", "p50"))))
    out.append(("model disagreement ln(primary/secondary), median operating", _f(_g(d, "model_disagreement_by_family", "operating", "p50"))))
    out.append(("model disagreement, median financial", _f(_g(d, "model_disagreement_by_family", "financial", "p50"))))
    out.append(("margin target P10..P90 width, median (operating, commodity)", _f(_g(s, "margin_target_width_p10_p90", "p50"))))
    out.append(("ROIC level five years on P10..P90 width, median (operating, commodity)", _f(_g(s, "ronic_level5_width_p10_p90", "p50"))))
    cf = d.get("coe_by_family") or {}
    for fam in ("operating", "financial", "commodity"):
        out.append((f"median cost of equity, {fam}", _f(_g(cf, fam, "coe", "p50"))))
    out.append(("median levered beta used, financial", _f(_g(cf, "financial", "beta_levered", "p50"))))
    out.append(("financial terminal ROTE at P50 inputs, median", _f(_g(s, "financial_terminal_rote_at_p50_inputs", "p50"))))
    out.append(("financial terminal excess retention, median (round 3 on)", _f(_g(s, "financial_terminal_excess_retention", "p50"))))
    dr = (r.get("coverage") or {}).get("draw_rules") or {}
    for fam in ("operating", "commodity", "financial"):
        out.append((f"share of draws with no growth after year 5, {fam} (round 3 on)", _pct(_g(dr, "share_of_draws_by_family_and_rule", f"{fam} | no_growth_after_year_5"))))
        out.append((f"share of draws floored at zero equity, {fam} (round 3 on)", _pct(_g(dr, "share_of_draws_by_family_and_rule", f"{fam} | equity_floored_at_zero (limited liability)"))))
    for b_ in ("excluded", "minus100", "last_close"):
        c = u["B1"][b_]
        out.append((f"B1 mean engine coefficient [90% lower, upper], bound {b_}", f"{_f(c['mean_coef'], 4)} [{_f(c['ci90'][0], 4)}, {_f(c['ci90'][1], 4)}]"))
    out.append(("B1 status over the bounds", u["B1_status_over_bounds"]))
    for b_ in ("excluded", "minus100", "last_close"):
        c = u["B2"][b_]
        out.append((f"B2 neutral spread (residual), bound {b_}", f"{_f(c['mean_spread'], 4)} ({_f(c['mean_spread_residual'], 4)})"))
    out.append(("B2 status over the bounds (bar +3 points)", u["B2_status_over_bounds"]))
    b3 = u["B3"]
    out.append(("B3 share outside 0.4x-2.5x (bar <= 15%)", _pct(b3.get("share_extreme"))))
    out.append(("B3 family gaps in points (bar within 10)", json.dumps({k: round(v, 1) for k, v in (b3.get("family_gap_points") or {}).items()})))
    out.append(("B3 IQR of ln(IV / price), positive IVs", _f(b3.get("iqr_ln_vp_positive_iv"))))
    out.append(("B3(c)", f"{b3.get('c_status')} (floor {_f(b3.get('c_floor'), 2)})" if b3.get("c_floor") is not None else f"{b3.get('c_status')} (comparator not computed)"))
    out.append(("B3 status", b3.get("status")))
    for k, lab in (("revenue_growth", "revenue growth"), ("operating_margin", "operating margin")):
        e, n = _b4(u, k, "median_abs_error_engine"), _b4(u, k, "median_abs_error_naive")
        out.append((f"B4 {lab}: median abs error, engine vs naive", f"{_f(e, 4)} vs {_f(n, 4)}"))
    out.append(("B4 n (revenue growth)", _f(_b4(u, "revenue_growth", "n"))))
    out.append(("B4 status", _g(u, "B4", "status")))
    st = r["coverage"]["by_family_and_status"]
    for key in ("operating | valued", "financial | valued", "commodity | valued", "operating | refused", "financial | refused", "commodity | refused", "family_not_built | family_not_built"):
        out.append((f"name-dates {key.replace(' | ', ', ')} (all dates)", _f(st.get(key, 0))))
    return out


def rows_n(reports) -> list:
    """[(label, v1, v2, ...)] for any number of reports (rows are matched by label; a measure a round does not have reads n/a)."""
    per = [dict(cells(r)) for r in reports]
    labels = []
    for r in reports:
        for lab, _ in cells(r):
            if lab not in labels:
                labels.append(lab)
    return [(lab, *[p.get(lab, "n/a") for p in per]) for lab in labels]


def rows(r1, r2):
    return rows_n([r1, r2])


def render_n(reports, names) -> str:
    L = ["# Gate 1, development: the rounds side by side (PROVISIONAL)", "", "**" + reports[-1]["provisional"] + "**", "",
         "Round 1: report `gate1_dev/report_b` (commit 13d8c80 and the run's follow-ups). Round 2: Addendum H (H1-H9), report `gate1_dev/round2/report_a`. Round 3: Addendum I "
         "(I1-I6). Each figure is read from the reports; the date sets differ as stated.", "",
         "| measure | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for row in rows_n(reports):
        L.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(L) + "\n"


def render(r1, r2) -> str:
    return render_n([r1, r2], ["round 1", "round 2"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", type=Path)
    ap.add_argument("--labels", nargs="*")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    names = a.labels or [f"round {i + 1}" for i in range(len(a.reports))]
    if len(names) != len(a.reports):
        raise SystemExit("one label per report")
    text = render_n([json.loads(p.read_text(encoding="utf-8")) for p in a.reports], names)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
