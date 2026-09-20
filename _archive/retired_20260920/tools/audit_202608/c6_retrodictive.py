"""C6 — Do the published signals rank realized outcomes? (DESCRIPTIVE ONLY)

Joins the verdict ledger (mos_pct / expectations gap / conviction at verdict time) with the
grader's realized excess returns (rs2_verdict_outcomes.json, benchmark IWM) by report id.
Spearman rank correlations at 30d and 91d horizons, all-rows and per-ticker-median (repeat
verdicts on one name are correlated).

CAVEAT carried from the grader itself: weeks of history, no significance testing - these are
descriptive numbers, not evidence of edge. The experiment answers "is the sign plausible and
worth protecting", never "is there proven alpha".
"""
import json

import common

common.enable_json_cache()
import rs2_data  # noqa: E402


def main():
    ledger = {}
    path = common.SD / "rs2_verdict_log.jsonl"
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        ledger[r.get("report")] = r

    out_doc = rs2_data.load_json(common.SD / "rs2_verdict_outcomes.json") or {}
    graded = out_doc.get("graded") or []

    res = {"benchmark": out_doc.get("benchmark_primary"), "horizons": {}}
    for h in (30, 91):
        rows = []
        for g in graded:
            if g.get("horizon_days") != h or g.get("exit_review"):
                continue
            led = ledger.get(g.get("report")) or {}
            ex = g.get("excess_iwm_pct")
            if ex is None:
                continue
            rows.append({"ticker": g.get("ticker"), "excess": ex,
                         "mos": led.get("realistic_mos_pct", led.get("mos_pct")),
                         "gap": led.get("expectations_gap_pts"),
                         "conviction": g.get("conviction"),
                         "family": g.get("action_family")})
        if not rows:
            continue

        def sp(key, sample):
            return common.spearman([r[key] for r in sample], [r["excess"] for r in sample])

        # per-ticker median (dedup correlated repeats)
        byt = {}
        for r in rows:
            byt.setdefault(r["ticker"], []).append(r)

        def med(vals):
            vals = sorted(v for v in vals if v is not None)
            return vals[len(vals) // 2] if vals else None

        dedup = [{k: med([r[k] for r in rs]) for k in ("excess", "mos", "gap", "conviction")}
                 for rs in byt.values()]

        fam_excess = {}
        for r in rows:
            fam_excess.setdefault(r["family"], []).append(r["excess"])
        fam_stats = {f: {"n": len(v), "mean_excess": round(sum(v) / len(v), 2),
                         "median_excess": round(med(v), 2)}
                     for f, v in sorted(fam_excess.items())}

        def pack(rho_n):
            rho, n = rho_n
            return {"rho": rho, "n": n}

        res["horizons"][str(h)] = {
            "n_rows": len(rows), "n_names": len(byt),
            "spearman_all_rows": {"mos_vs_excess": pack(sp("mos", rows)),
                                  "gap_vs_excess": pack(sp("gap", rows)),
                                  "conviction_vs_excess": pack(sp("conviction", rows))},
            "spearman_per_ticker_median": {"mos_vs_excess": pack(sp("mos", dedup)),
                                           "gap_vs_excess": pack(sp("gap", dedup)),
                                           "conviction_vs_excess": pack(sp("conviction", dedup))},
            "excess_by_action_family": fam_stats,
        }
    res["caveat"] = ("Descriptive only. Short history, correlated repeat verdicts, no "
                     "significance testing (mirrors the grader's own disclaimer).")
    common.save("c6_retrodictive", res)


if __name__ == "__main__":
    main()
