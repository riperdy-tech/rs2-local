"""The level-decomposition table of round 4 (Addendum J1) from the `decomp_{date}.json` files `gate1_decompose` writes.  DIAGNOSTIC: no bar, no return.

    python -m rebuild_harness.gate1_decompose_summary RUN_DIR [--out-dir OUT]

Per family (and for all names) and per variant, over the fixed universe of the dates: the median IV / price, its change against the baseline (the variant's median minus the
baseline's, and the median of the paired per-name differences), the share of non-positive IV (IV / price <= 0), the share outside 0.4x-2.5x (non-positive included), the share of
draws floored at zero equity (pooled over the valid draws of the names), and the names lost (every draw invalid) and the share of names with more than 5% of their draws
invalid.  Two blocks: every date, and the return dates only (2020-03-31 .. 2021-12-31).  Also the ERP series by date.
"""
import argparse
import json
from pathlib import Path

import numpy as np

RETURN_END = "2021-12-31"
FAMILIES = ("operating", "commodity", "financial", "all")
LOW, HIGH = 0.4, 2.5


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


def load(run_dir):
    out = {}
    for p in sorted(Path(run_dir).glob("decomp_*.json")):
        j = json.loads(p.read_text(encoding="utf-8"))
        out[j["date"]] = j
    return out


def _stats(items):
    """items: list of (vp, neg_eq_share, n_valid, n_draws, invalid_share) of the names valued by a variant."""
    if not items:
        return {"n": 0}
    vp = np.array([x[0] for x in items], dtype=float)
    nv = np.array([x[2] for x in items], dtype=float)
    ne = np.array([(0.0 if x[1] is None else x[1]) for x in items], dtype=float)
    inv = np.array([x[4] for x in items], dtype=float)
    return {"n": int(len(vp)), "median_vp": float(np.median(vp)), "share_nonpositive_iv": float((vp <= 0).mean()),
            "share_outside_0_4_2_5": float(((vp < LOW) | (vp > HIGH)).mean()), "share_below_0_4": float((vp < LOW).mean()), "share_above_2_5": float((vp > HIGH).mean()),
            "share_draws_floored_at_zero": float((ne * nv).sum() / nv.sum()) if nv.sum() > 0 else None,
            "share_names_over_5pct_invalid_draws": float((inv > 0.05).mean()), "median_invalid_share": float(np.median(inv))}


def summarize(decomp, dates=None):
    """{variant: {family: stats + deltas}} over the dates (default: every date in `decomp`)."""
    dates = [d for d in sorted(decomp) if dates is None or d in dates]
    keys = ["base"] + [k for k in decomp[dates[0]]["labels"]]
    out = {}
    for k in keys:
        out[k] = {}
        for fam in FAMILIES:
            items, base_items, paired = [], [], []
            n_lost = n_in = 0
            for d in dates:
                j = decomp[d]
                res = j["variants"].get(k)
                if res is None:
                    continue
                for cik, x in res.items():
                    if fam != "all" and j["universe"][cik]["family"] != fam:
                        continue
                    n_in += 1
                    b = j["variants"]["base"].get(cik)
                    if x is None:
                        n_lost += 1
                        continue
                    items.append(x)
                    if b is not None:
                        base_items.append(b)
                        paired.append(x[0] - b[0])
            st = _stats(items)
            st["n_lost"], st["n_in_universe"] = n_lost, n_in
            if k != "base" and items:
                # the baseline over the SAME names the variant covers (a family-restricted variant covers fewer names)
                bst = _stats(base_items)
                st["baseline_median_vp_same_names"] = bst.get("median_vp")
                st["delta_median_vp"] = (st["median_vp"] - bst["median_vp"]) if bst.get("n") else None
                st["median_paired_difference_vp"] = float(np.median(paired)) if paired else None
                for m in ("share_nonpositive_iv", "share_outside_0_4_2_5", "share_draws_floored_at_zero"):
                    st["delta_" + m] = (st[m] - bst[m]) if (bst.get("n") and st.get(m) is not None and bst.get(m) is not None) else None
            out[k][fam] = st
    return out


def fp(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def render(decomp, title="Level decomposition (Addendum J1)"):
    dates = sorted(decomp)
    ret = [d for d in dates if d <= RETURN_END]
    L = [f"# {title}", "", "**DIAGNOSTIC ONLY. PROVISIONAL: raw month-end prices of today's listings (Addendum H9), survivors only. No default or registered rule is changed by anything here.**", "",
         f"Dates ({len(dates)}): {', '.join(dates)}", ""]
    L += ["## The equity risk premium by date", "", "| date | monthly row | Damodaran monthly (used) | Damodaran annual (round 3) | round 3b common closure | universe names |", "|---|---|---|---|---|---|"]
    for d in dates:
        e = decomp[d]["erp"]
        L.append(f"| {d} | {e.get('monthly_row')} | {pct(e['damodaran_monthly'])} | {pct(e['damodaran_annual'])} | {pct(e['round3b_common_closure'])} | {decomp[d]['n_universe']} |")
    ref = [(d, decomp[d].get("reference_check")) for d in dates if decomp[d].get("reference_check")]
    if ref:
        L += ["", "Baseline against the round-4 run (determinism): " + "; ".join(f"{d}: {r['n_compared']}/{r['n_universe']} compared, max relative difference {r['max_relative_difference']}" for d, r in ref)]
    for label, ds in (("every date", None), (f"return dates only (to {RETURN_END}; {len(ret)} dates)", ret)):
        if ds is not None and not ds:
            continue
        S = summarize(decomp, ds)
        L += ["", f"## Median IV / price and its change, by family: {label}", "",
              "Each variant on the fixed universe (names valued by the registered engine, market cap >= $300M); change = the variant's median minus the baseline's on the same names.", ""]
        for fam in FAMILIES:
            b = S["base"][fam]
            if not b.get("n"):
                continue
            L += [f"### {fam} (baseline: n {b['n']}, median {fp(b['median_vp'])}, non-positive {pct(b['share_nonpositive_iv'])}, outside 0.4x-2.5x {pct(b['share_outside_0_4_2_5'])}, "
                  f"zero-floored draws {pct(b['share_draws_floored_at_zero'])})", "",
                  "| variant | n | median IV/P | change in median | paired median change | non-positive IV | outside 0.4x-2.5x | zero-floored draws | lost | names > 5% invalid draws |", "|---|---|---|---|---|---|---|---|---|---|"]
            for k, lab in decomp[dates[0]]["labels"].items():
                s = S[k][fam]
                if not s.get("n"):
                    L.append(f"| {lab} | 0 | n/a | n/a | n/a | n/a | n/a | n/a | {s.get('n_lost', 0)} | n/a |")
                    continue
                L.append(f"| {lab} | {s['n']} | {fp(s['median_vp'])} | {fp(s.get('delta_median_vp'))} | {fp(s.get('median_paired_difference_vp'))} | "
                         f"{pct(s['share_nonpositive_iv'])} ({fp(100 * s['delta_share_nonpositive_iv'], 1) if s.get('delta_share_nonpositive_iv') is not None else 'n/a'} pp) | "
                         f"{pct(s['share_outside_0_4_2_5'])} ({fp(100 * s['delta_share_outside_0_4_2_5'], 1) if s.get('delta_share_outside_0_4_2_5') is not None else 'n/a'} pp) | "
                         f"{pct(s['share_draws_floored_at_zero'])} ({fp(100 * s['delta_share_draws_floored_at_zero'], 1) if s.get('delta_share_draws_floored_at_zero') is not None else 'n/a'} pp) | "
                         f"{s['n_lost']} | {pct(s['share_names_over_5pct_invalid_draws'])} |")
            L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out-dir", type=Path)
    a = ap.parse_args(argv)
    out = a.out_dir or a.run_dir
    out.mkdir(parents=True, exist_ok=True)
    decomp = load(a.run_dir)
    if not decomp:
        raise SystemExit(f"no decomp_*.json in {a.run_dir}")
    dates = sorted(decomp)
    res = {"dates": dates, "all_dates": summarize(decomp), "return_dates": summarize(decomp, [d for d in dates if d <= RETURN_END]),
           "erp": {d: decomp[d]["erp"] for d in dates}, "labels": decomp[dates[0]]["labels"]}
    (out / "decomposition.json").write_text(json.dumps(_clean(res), indent=1), encoding="utf-8")
    (out / "decomposition.md").write_text(render(decomp), encoding="utf-8")
    print("written", out)


if __name__ == "__main__":
    main()
