"""C9 — Do S4's scenario probabilities contain information worth wiring in?

Reads the stored scenario_probs from every report bundle's S3_valuation_inputs.json,
measures (a) how templated the emissions are, (b) whether the bull-bear tilt ranks realized
30d excess returns at all, overall and within MoS terciles, (c) redundancy with conviction.
Run after the audit's initial publication in answer to "should S4 be wired instead of
removed?" — result: mostly templated (6 triples = 82% of emissions), weak incremental
information (tilt vs excess rho ~ +0.14 overall, ~0 in the cheap tercile), partially
redundant with conviction (rho +0.32). Strengthens the R1 remove path.
"""
import collections
import json
from pathlib import Path

import common

common.enable_json_cache()
import rs2_data  # noqa: E402


def main():
    rep = Path(rs2_data.CONFIG["out_reports_dir"])
    rows = {}
    for d in rep.glob("*_*"):
        f = d / "S3_valuation_inputs.json"
        if not f.exists():
            continue
        v = rs2_data.load_json(f) or {}
        p = v.get("scenario_probs")
        if isinstance(p, dict) and all(k in p for k in ("bear", "base", "bull")):
            rows[d.name] = {"bear": p["bear"], "base": p["base"], "bull": p["bull"]}

    triples = collections.Counter(
        (round(r["bear"], 2), round(r["base"], 2), round(r["bull"], 2)) for r in rows.values())
    top6 = triples.most_common(6)
    tilts = sorted(r["bull"] - r["bear"] for r in rows.values())
    n = len(tilts)

    ledger = {}
    for line in (common.SD / "rs2_verdict_log.jsonl").read_text(encoding="utf-8").strip().splitlines():
        try:
            r = json.loads(line)
            ledger[r.get("report")] = r
        except Exception:
            pass
    graded = (rs2_data.load_json(common.SD / "rs2_verdict_outcomes.json") or {}).get("graded") or []
    joined = []
    for g in graded:
        if g.get("horizon_days") != 30 or g.get("exit_review"):
            continue
        r = rows.get(g.get("report"))
        if not r or g.get("excess_iwm_pct") is None:
            continue
        led = ledger.get(g.get("report")) or {}
        joined.append({"tilt": r["bull"] - r["bear"], "excess": g["excess_iwm_pct"],
                       "mos": led.get("realistic_mos_pct"), "conv": g.get("conviction")})

    have = sorted((j for j in joined if j["mos"] is not None), key=lambda j: j["mos"])
    k = len(have) // 3
    terciles = {}
    for i, name in enumerate(("mos_low", "mos_mid", "mos_high")):
        seg = have[i * k:(i + 1) * k] if i < 2 else have[2 * k:]
        rho, nn = common.spearman([j["tilt"] for j in seg], [j["excess"] for j in seg])
        terciles[name] = {"rho": rho, "n": nn}

    rho_all, n_all = common.spearman([j["tilt"] for j in joined], [j["excess"] for j in joined])
    rho_conv, n_conv = common.spearman([j["conv"] for j in joined], [j["tilt"] for j in joined])
    common.save("c9_s4_information", {
        "n_bundles_with_probs": len(rows),
        "top6_triples": [{"probs": list(t), "count": c} for t, c in top6],
        "top6_share": round(sum(c for _, c in top6) / len(rows), 3) if rows else None,
        "tilt_percentiles": {p: round(tilts[min(n - 1, n * p // 100)], 2)
                             for p in (10, 25, 50, 75, 90)} if n else {},
        "spearman_tilt_vs_30d_excess": {"rho": rho_all, "n": n_all},
        "spearman_tilt_within_mos_terciles": terciles,
        "spearman_tilt_vs_conviction": {"rho": rho_conv, "n": n_conv},
        "caveat": "Descriptive correlations (short history); the templating measurement is not "
                  "outcome-dependent and stands on its own.",
    })


if __name__ == "__main__":
    main()
