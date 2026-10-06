"""Round 4 against round 3 (and round 3b), on the SAME dates: the level diagnostics of two run folders side by side, and the registration-v2 bars B1-B3 of round 3 for reference.

    python -m rebuild_harness.gate1_compare_v2 --out OUT.md --run LABEL=RUN_DIR [--run ...] [--dates D ...] [--n-boot 499] [--bars LABEL ...]

Every run folder is read with the same loader and the same functions, restricted to the same `--dates` (default: the 12 quarter-ends 2020-03-31 .. 2022-12-31 that rounds 3 and 3b
used), so a difference is the engine's.  Names: market cap >= $300M.  DIAGNOSTIC and PROVISIONAL (raw month-end prices, survivors only).  `--bars LABEL` also computes the
registration-v2 bars B1, B2, B3 of that run on those dates (B4 needs forecast quantiles that older rounds did not store).
"""
import argparse
import json
from pathlib import Path

import numpy as np

from . import gate1_metrics as gm
from . import gate1_v2 as v2

QUARTER_ENDS = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31", "2021-06-30", "2021-09-30", "2021-12-31",
                "2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31"]


def _load(run_dir, dates):
    rows, counters, _ = gm.load_run(run_dir, dates=set(dates))
    return [r for r in rows if r["mcap_group"] == ">=300M"], counters


def summarize(rows):
    out = {"n": len(rows)}
    for fam in ("operating", "commodity", "financial", "all"):
        rs = [r for r in rows if fam == "all" or r["family"] == fam]
        vp = np.array([r["vp"] for r in rs if r.get("vp") is not None], dtype=float)
        if not len(vp):
            out[fam] = {"n": 0}
            continue
        nv = np.array([r["n_draws"] * (1.0 - r["invalid_share"]) for r in rs], dtype=float)
        ne = np.array([(r.get("neg_eq_share") or 0.0) for r in rs], dtype=float)
        tv = [r["tv_share"] for r in rs if r.get("tv_share") is not None]
        coe = [r["disc"]["coe"] for r in rs if r.get("disc")]
        erp = [r["disc"]["erp"] for r in rs if r.get("disc")]
        rt = [x["ronic_terminal_at_p50_inputs"] for x in (r.get("returns") or {} for r in rs) if x.get("ronic_terminal_at_p50_inputs") is not None]
        out[fam] = {"n": int(len(vp)), "median_vp": float(np.median(vp)), "p10": float(np.percentile(vp, 10)), "p90": float(np.percentile(vp, 90)), "share_nonpositive": float((vp <= 0).mean()),
                    "share_outside_0_4_2_5": float(((vp < 0.4) | (vp > 2.5)).mean()), "share_below_0_4": float((vp < 0.4).mean()), "share_above_2_5": float((vp > 2.5).mean()),
                    "share_draws_floored_at_zero": float((ne * nv).sum() / nv.sum()) if nv.sum() else None, "median_tv_share": float(np.median(tv)) if tv else None,
                    "median_coe": float(np.median(coe)) if coe else None, "median_erp": float(np.median(erp)) if erp else None,
                    "median_terminal_ronic_at_p50_inputs": float(np.median(rt)) if rt else None}
    return out


def by_date_median(rows):
    out = {}
    for d, rs in gm.by_date(rows).items():
        out[d] = float(np.median([r["vp"] for r in rs if r.get("vp") is not None]))
    return out


def fp(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def render(labels, S, dates, M, bars):
    L = ["# Round 4 against earlier rounds, on the same dates (DIAGNOSTIC, PROVISIONAL)", "", "**PROVISIONAL: raw month-end prices of today's listings (Addendum H9), survivors only; counts toward no gate.**", "",
         f"Dates ({len(dates)}): {', '.join(dates)}; names: market cap >= $300M; the same loader and functions for every run.", ""]
    head = "| measure | " + " | ".join(labels) + " |"
    sep = "|---|" + "---|" * len(labels)
    L += [head, sep]
    L.append("| valued name-dates | " + " | ".join(str(S[l]["n"]) for l in labels) + " |")
    for fam in ("all", "operating", "commodity", "financial"):
        L.append(f"| **{fam}** n | " + " | ".join(str(S[l][fam].get("n")) for l in labels) + " |")
        for key, nm, f in (("median_vp", "median IV / price", fp), ("share_nonpositive", "share non-positive IV", pct), ("share_outside_0_4_2_5", "share outside 0.4x-2.5x", pct),
                           ("share_below_0_4", "  below 0.4x", pct), ("share_above_2_5", "  above 2.5x", pct), ("share_draws_floored_at_zero", "share of draws floored at zero", pct),
                           ("median_tv_share", "median terminal-value share", fp), ("median_coe", "median cost of equity", lambda x: fp(x, 4)), ("median_erp", "median ERP", lambda x: fp(x, 4)),
                           ("median_terminal_ronic_at_p50_inputs", "median terminal RONIC at P50 inputs", lambda x: fp(x, 4))):
            if fam == "financial" and key == "median_terminal_ronic_at_p50_inputs":
                continue
            L.append(f"| {nm} ({fam}) | " + " | ".join(f(S[l][fam].get(key)) for l in labels) + " |")
    L += ["", "## Median IV / price by date", "", head, sep]
    for d in dates:
        L.append(f"| {d} | " + " | ".join(fp(M[l].get(d), 3) for l in labels) + " |")
    for l, b in bars.items():
        L += ["", f"## {l}: registration-v2 bars B1-B3 on these dates (B4 needs the forecast quantiles stored from round 4 on: see the run's report)", "", f"outcome fields: B1 {b['bar_status_over_bounds']['B1']}, B2 {b['bar_status_over_bounds']['B2']}, B3 {b['bar_status_over_bounds']['B3']}", "",
              "| bound | B1 coefficient | lower bound | positive months | B2 residual spread | B2 raw spread |", "|---|---|---|---|---|---|"]
        for bd in gm.BOUNDS:
            x, y = b["by_bound"][bd]["B1"], b["by_bound"][bd]["B2"]
            L.append(f"| {bd} | {fp(x.get('beta'), 4)} | {fp(x.get('lower_90_one_sided'), 4)} | {pct(x.get('share_positive_monthly_coefficients'))} | {pct(y['mean_spread_residual'])} | {pct(y['mean_spread_raw'])} |")
        L.append(f"B3: median IV / price {fp(b['B3'].get('median_vp'))} (band [0.67, 1.5]): {b['B3']['status']}")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--run", action="append", required=True, help="LABEL=RUN_DIR")
    ap.add_argument("--dates", nargs="*", default=QUARTER_ENDS)
    ap.add_argument("--bars", action="append", default=[], help="LABELs whose registration-v2 bars B1-B3 are computed on the dates")
    ap.add_argument("--n-boot", type=int, default=499)
    a = ap.parse_args(argv)
    S, M, bars, labels = {}, {}, {}, []
    for spec in a.run:
        label, path = spec.split("=", 1)
        rows, _ = _load(path, a.dates)
        labels.append(label)
        S[label], M[label] = summarize(rows), by_date_median(rows)
        if label in a.bars:
            bars[label] = v2.v2_bars(rows, ">=300M", a.n_boot, with_variants=False)
    a.out.write_text(render(labels, S, a.dates, M, bars), encoding="utf-8")
    a.out.with_suffix(".json").write_text(json.dumps({"summaries": S, "median_by_date": M, "dates": a.dates}, indent=1, default=float), encoding="utf-8")
    print("written", a.out)


if __name__ == "__main__":
    main()
