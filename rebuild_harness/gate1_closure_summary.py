"""DIAGNOSTIC ONLY (round 3b): the closure-ERP tables, from a `gate1_closure` output folder and round 3's run folder.

    python -m rebuild_harness.gate1_closure_summary OUT --round3-run ROUND3_RUN

Writes OUT/closure_summary.json and OUT/closure_table.md: per date the Damodaran ERP, the common closure ERP and the per-family closure ERPs with the gaps, and per
date and family the engine's value-to-market-cap ratio (sum of median equity over sum of market caps, valued names of $300M or more of the variant itself) and the
median IV / price under round 3 (Damodaran), the common closure and the per-family closure.  PROVISIONAL like every development figure.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import gate1_metrics as gm
from .gate1_closure import FAMILIES


def _by_date_family(run_dir, dates):
    rows, _, _ = gm.load_run(run_dir, dates=set(dates))
    big = [r for r in rows if r["mcap_group"] == ">=300M" and r.get("vp") is not None and r.get("market_cap")]
    out = defaultdict(dict)
    for d in dates:
        for fam in ("all",) + FAMILIES:
            rs = [r for r in big if r["date"] == d and (fam == "all" or r["family"] == fam)]
            if not rs:
                out[d][fam] = None
                continue
            s_eq = sum(r["vp"] * r["market_cap"] for r in rs)
            s_mc = sum(r["market_cap"] for r in rs)
            out[d][fam] = {"n": len(rs), "sum_ratio": s_eq / s_mc, "median_vp": float(np.median([r["vp"] for r in rs]))}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--round3-run", required=True, type=Path)
    a = ap.parse_args(argv)
    infos = {}
    for p in sorted(a.out_dir.glob("closure_*.json")):
        if p.name == "closure_summary.json":
            continue
        i = json.loads(p.read_text(encoding="utf-8"))
        infos[i["date"]] = i
    dates = sorted(infos)
    r3 = _by_date_family(a.round3_run, dates)
    com = _by_date_family(a.out_dir / "common", dates)
    fam = _by_date_family(a.out_dir / "family", dates)
    summary = {"dates": dates, "per_date": {}, "provisional": gm.PROVISIONAL}
    L = ["# Round 3b: the closure ERP (DIAGNOSTIC ONLY, PROVISIONAL)", "", "**" + gm.PROVISIONAL + "**", "",
         "The closure ERP of a date: the single ERP scalar at which the sum of the engine's median equity values equals the sum of market caps over the names valued "
         "at the date with a market cap of $300M or more (round 3's valued set; point in time).  Per family: the same solve on each family's names alone.  ERPs in percent; "
         "the gap is closure minus Damodaran, in percentage points.", "",
         "| date | universe n | Damodaran | common closure | gap | operating (n) | gap | commodity (n) | gap | financial (n) | gap | sum ratio at Damodaran | residual at closure |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in dates:
        i = infos[d]
        s = i["solves"]
        e0 = i["erp_damodaran"]
        c = i["erp_common_closure"]
        cells = []
        for f in FAMILIES:
            sf = s[f]
            if sf.get("status") in ("ok", "exact", "max_evals"):
                cells += [f"{100 * sf['erp']:.2f} ({sf['n_names']})", f"{100 * (sf['erp'] - e0):+.2f}"]
            else:
                cells += [f"none: {sf.get('status')} ({sf.get('n_names')})", "n/a"]
        L.append(f"| {d} | {i['n_universe']} | {100 * e0:.2f} | {100 * c:.2f} | {100 * (c - e0):+.2f} | " + " | ".join(cells) +
                 f" | {s['all']['ratio_at_damodaran']:.3f} | {s['all']['g']:+.1e} |")
        summary["per_date"][d] = {"erp_damodaran": e0, "erp_common_closure": c, "gap": c - e0, "n_universe": i["n_universe"], "status_all": s["all"]["status"],
                                  "families": {f: {k: s[f].get(k) for k in ("status", "erp", "n_names", "ratio_at_damodaran", "g")} for f in FAMILIES},
                                  "sum_ratio_at_damodaran_by_family": {f: s[f].get("ratio_at_damodaran") for f in FAMILIES}}
    L += ["", "Means over the dates (percent): " + ", ".join(
        f"{lab} {100 * np.mean(v):.2f}" for lab, v in (
            ("Damodaran", [infos[d]["erp_damodaran"] for d in dates]), ("common closure", [infos[d]["erp_common_closure"] for d in dates]),
            *[(f"{f} closure", [infos[d]["solves"][f]["erp"] for d in dates if infos[d]["solves"][f].get("erp") is not None]) for f in FAMILIES])), ""]
    L += ["## The engine's value over market cap by family (sum of median equity / sum of market caps; median IV / price in brackets), valued names of $300M or more", "",
          "| date | family | n (round 3) | round 3, Damodaran | n | common closure | n | per-family closure |", "|---|---|---|---|---|---|---|---|"]

    def cell(x):
        return "n/a" if not x else f"{x['sum_ratio']:.3f} ({x['median_vp']:.2f})"
    for d in dates:
        for f in ("all",) + FAMILIES:
            a_, b_, c_ = r3[d].get(f), com[d].get(f), fam[d].get(f)
            L.append(f"| {d} | {f} | {a_['n'] if a_ else 0} | {cell(a_)} | {b_['n'] if b_ else 0} | {cell(b_)} | {c_['n'] if c_ else 0} | {cell(c_)} |")
            summary["per_date"][d].setdefault("value_over_cap", {})[f] = {"round3": a_, "common": b_, "family": c_}
    L += ["", "## Determinism check (the re-run at Damodaran's ERP against round 3's records)", ""]
    for d in dates:
        x = infos[d]["determinism_vs_round3"]
        L.append(f"- {d}: compared {x['n_compared_valued']} valued names (round 3 valued {x['n_valued_reference']}), status mismatches {x['status_mismatches']}, "
                 f"max relative difference of IV P50 {x['max_relative_difference_iv_p50']:.2e}")
    L += ["", "## Compute time (seconds per date: pass 1 / baseline re-run / solves / the two variant runs / total)", ""]
    for d in dates:
        s = infos[d]["seconds"]
        L.append(f"- {d}: {s['pass1']:.0f} / {s['baseline']:.0f} / {s['solve']:.0f} / {s['variants']:.0f} / {s['total']:.0f}")
    (a.out_dir / "closure_summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    (a.out_dir / "closure_table.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
