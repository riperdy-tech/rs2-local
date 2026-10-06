"""Round 1 against round 2 of the gate-1 development run: one table, from the two reports' JSON (`gate1_report.build`'s output).

    python -m rebuild_harness.gate1_compare ROUND1_REPORT.json ROUND2_REPORT.json [--out file.md]

Round 1 was run on 16 dates 2019-03-31..2022-12-31 of the 24 it covered (2017-2018 held nothing) with the F4 rescale, a drawn terminal growth and incremental ROIC; round 2
(Addendum H) is the same harness on the re-dated set.  The two differ in dates for B1-B3 (round 1: all 16; round 2: the 12 to 2021-12-31), which the table states.
Everything is PROVISIONAL (raw monthly prices of today's listings, survivors only).  Nothing here forms a new figure: it reads two reports.
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


def rows(r1, r2):
    """[(label, round 1, round 2)] of strings."""
    u1, u2 = r1["gate1_universe_ge_300M"], r2["gate1_universe_ge_300M"]
    d1, d2 = r1["diagnostics"]["ge_300M"], r2["diagnostics"]["ge_300M"]
    out = []
    out.append(("valued name-dates, market cap >= $300M", _f(r1["n_valued_ge_300M"]), _f(r2["n_valued_ge_300M"])))
    out.append(("valued name-dates, all", _f(r1["n_valued"]), _f(r2["n_valued"])))
    out.append(("dates behind B1-B3 (returns)", str(len(_g(u1, "return_dates", default=[])) or _g(u1, "B1", "excluded", "n_dates")), str(len(_g(u2, "return_dates", default=[])) or _g(u2, "B1", "excluded", "n_dates"))))
    out.append(("dates behind B4", str(len(_g(u1, "b4_dates", default=[])) or "16"), str(len(_g(u2, "b4_dates", default=[])))))
    for fam in ("operating", "financial", "commodity"):
        a, b = d1["vp_by_family"].get(fam, {}), d2["vp_by_family"].get(fam, {})
        out.append((f"median IV / price, {fam}", _f(_g(a, "quantiles", "p50")), _f(_g(b, "quantiles", "p50"))))
        out.append((f"  n, {fam}", _f(a.get("n")), _f(b.get("n"))))
        out.append((f"  share non-positive IV, {fam}", _pct(a.get("share_nonpositive")), _pct(b.get("share_nonpositive"))))
        out.append((f"  share below 0.4x / above 2.5x, {fam}", f"{_pct(a.get('share_below_0_4'))} / {_pct(a.get('share_above_2_5'))}", f"{_pct(b.get('share_below_0_4'))} / {_pct(b.get('share_above_2_5'))}"))
    a, b = d1["vp_overall"], d2["vp_overall"]
    out.append(("median IV / price, all", _f(_g(a, "quantiles", "p50")), _f(_g(b, "quantiles", "p50"))))
    out.append(("IV / price P10 / P90, all", f"{_f(_g(a, 'quantiles', 'p10'))} / {_f(_g(a, 'quantiles', 'p90'))}", f"{_f(_g(b, 'quantiles', 'p10'))} / {_f(_g(b, 'quantiles', 'p90'))}"))
    s1, s2 = d1["structure"], d2["structure"]
    out.append(("invalid-draw share, median name", _pct(_g(s1, "invalid_draw_share", "p50")), _pct(_g(s2, "invalid_draw_share", "p50"))))
    out.append(("names (valued) with > 50% invalid draws", _pct(s1.get("share_names_over_half_draws_invalid")), _pct(s2.get("share_names_over_half_draws_invalid"))))
    out.append(("names (valued) with > 5% invalid draws", "n/a (no refusal rule)", _pct(s2.get("share_names_over_5pct_draws_invalid"))))
    out.append(("terminal-value share, median", _f(_g(d1, "tv_share", "all", "p50")), _f(_g(d2, "tv_share", "all", "p50"))))
    out.append(("model disagreement ln(primary/secondary), median operating", _f(_g(d1, "model_disagreement_by_family", "operating", "p50")), _f(_g(d2, "model_disagreement_by_family", "operating", "p50"))))
    out.append(("model disagreement, median financial", _f(_g(d1, "model_disagreement_by_family", "financial", "p50")), _f(_g(d2, "model_disagreement_by_family", "financial", "p50"))))
    out.append(("margin target P10..P90 width, median (operating, commodity)", _f(_g(s1, "margin_target_width_p10_p90", "p50")), _f(_g(s2, "margin_target_width_p10_p90", "p50"))))
    for b_ in ("excluded", "minus100", "last_close"):
        c1, c2 = u1["B1"][b_], u2["B1"][b_]
        out.append((f"B1 mean engine coefficient [90% lower, upper], bound {b_}", f"{_f(c1['mean_coef'], 4)} [{_f(c1['ci90'][0], 4)}, {_f(c1['ci90'][1], 4)}]", f"{_f(c2['mean_coef'], 4)} [{_f(c2['ci90'][0], 4)}, {_f(c2['ci90'][1], 4)}]"))
    out.append(("B1 status over the bounds", u1["B1_status_over_bounds"], u2["B1_status_over_bounds"]))
    for b_ in ("excluded", "minus100", "last_close"):
        c1, c2 = u1["B2"][b_], u2["B2"][b_]
        out.append((f"B2 neutral spread (residual), bound {b_}", f"{_f(c1['mean_spread'], 4)} ({_f(c1['mean_spread_residual'], 4)})", f"{_f(c2['mean_spread'], 4)} ({_f(c2['mean_spread_residual'], 4)})"))
    out.append(("B2 status over the bounds (bar +3 points)", u1["B2_status_over_bounds"], u2["B2_status_over_bounds"]))
    b31, b32 = u1["B3"], u2["B3"]
    out.append(("B3 share outside 0.4x-2.5x (bar <= 15%)", _pct(b31.get("share_extreme")), _pct(b32.get("share_extreme"))))
    out.append(("B3 family gaps in points (bar within 10)", json.dumps({k: round(v, 1) for k, v in (b31.get("family_gap_points") or {}).items()}), json.dumps({k: round(v, 1) for k, v in (b32.get("family_gap_points") or {}).items()})))
    out.append(("B3 IQR of ln(IV / price), positive IVs", _f(b31.get("iqr_ln_vp_positive_iv")), _f(b32.get("iqr_ln_vp_positive_iv"))))
    out.append(("B3(c)", f"{b31.get('c_status')} (round 1: comparator not computed)", f"{b32.get('c_status')} (floor {_f(b32.get('c_floor'), 2)})"))
    out.append(("B3 status", b31.get("status"), b32.get("status")))
    for k, lab in (("revenue_growth", "revenue growth"), ("operating_margin", "operating margin")):
        e1, n1 = _b4(u1, k, "median_abs_error_engine"), _b4(u1, k, "median_abs_error_naive")
        e2, n2 = _b4(u2, k, "median_abs_error_engine"), _b4(u2, k, "median_abs_error_naive")
        out.append((f"B4 {lab}: median abs error, engine vs naive", f"{_f(e1, 4)} vs {_f(n1, 4)}", f"{_f(e2, 4)} vs {_f(n2, 4)}"))
    out.append(("B4 status", _g(u1, "B4", "status"), _g(u2, "B4", "status")))
    c1, c2 = r1["coverage"], r2["coverage"]
    st1, st2 = c1["by_family_and_status"], c2["by_family_and_status"]
    for key in ("operating | valued", "financial | valued", "commodity | valued", "operating | refused", "financial | refused", "commodity | refused", "family_not_built | family_not_built"):
        out.append((f"name-dates {key} (all dates)", _f(st1.get(key, 0)), _f(st2.get(key, 0))))
    return out


def render(r1, r2) -> str:
    L = ["# Gate 1, development: round 1 against round 2 (PROVISIONAL)", "", "**" + r2["provisional"] + "**", "",
         "Round 1: report `gate1_dev/report_b` (commit 13d8c80 and the run's follow-ups). Round 2: Addendum H (H1-H9). Each figure is read from the two reports; the date sets differ as stated.", "",
         "| measure | round 1 | round 2 |", "|---|---|---|"]
    for lab, a, b in rows(r1, r2):
        L.append(f"| {lab} | {a} | {b} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("round1", type=Path)
    ap.add_argument("round2", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    text = render(json.loads(a.round1.read_text(encoding="utf-8")), json.loads(a.round2.read_text(encoding="utf-8")))
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
