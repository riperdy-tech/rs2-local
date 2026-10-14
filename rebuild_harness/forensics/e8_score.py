"""E8, engine v2's valuation-sanity check (SPEC_rebuild Addenda AL.27, AL.28, AL.29, AL.31): v2 against v1 on the same inputs, from forensic-run records
carrying `rec["e5"]` with `--e5-dist`.

    python -m rebuild_harness.forensics.e8_score RUN_DIR OUT.json [--sample forensic|gate2b] [--include-diagnostic-dates]

Per name: invalid draws (v2); the top-1% share of mean equity (v1, v2); EV P90/P50 (operating; financial: equity P90/P50, the floor being immaterial);
P50 equity v2/v1.  Bars, per family (operating, financial), pooled and in each valuation year:
  E8a  invalid draws = 0 in every name
  E8b  median top-1% share <= 2 x v1's median, and 90th percentile <= 2 x v1's 90th percentile
  E8c  median EV P90/P50 <= 2 x v1's median
  E8d  median of P50 v2/v1 in [0.5, 2.0]
The forensic sample's verdict EXCLUDES the two dates used to choose the interim (2021-06-30, 2024-06-30; AL.29); they are reported apart.
AL.31: the verdict is written to OUT.json and NOT printed; the console shows counts only, until cross-check 12's rulings are recorded."""
import gzip
import json
import math
import statistics
import sys
from pathlib import Path

DIAGNOSTIC_DATES = ("2021-06-30", "2024-06-30")
FAMILIES = ("operating", "financial")
MULT, BAND = 2.0, (0.5, 2.0)


def _q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    h = (len(xs) - 1) * p
    lo = int(math.floor(h))
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (h - lo)


def rows_of(run_dir):
    out = []
    for f in sorted(Path(run_dir).glob("records_*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                e, v = r.get("e5") or {}, r.get("val") or {}
                d2 = e.get("v2_dist") or {}
                if e.get("family") not in FAMILIES or d2.get("status") != "ok" or v.get("status") != "ok":
                    continue
                iv = v.get("iv_ps") or {}
                fam = e["family"]
                if fam == "operating":
                    ev1 = (e["v1_ev_p90"] / e["v1_ev_p50"]) if e.get("v1_ev_p50") and e["v1_ev_p50"] > 0 and e.get("v1_ev_p90") is not None else None
                    ev2 = (d2["ev_p90"] / d2["ev_p50"]) if d2.get("ev_p50") and d2["ev_p50"] > 0 and d2.get("ev_p90") is not None else None
                else:
                    ev1 = (iv["p90"] / iv["p50"]) if iv.get("p50") and iv["p50"] > 0 else None
                    ev2 = (d2["ps_p90"] / d2["ps_p50"]) if d2.get("ps_p50") and d2["ps_p50"] > 0 else None
                out.append({"date": r["date"], "year": r["date"][:4], "cik": r["cik"], "family": fam, "invalid": d2["n_invalid"],
                            "top1_v1": e.get("v1_top1pct_share_of_mean"), "top1_v2": d2.get("top1pct_share_of_mean"), "spread_v1": ev1, "spread_v2": ev2,
                            "p50_ratio": (d2["ps_p50"] / iv["p50"]) if iv.get("p50") and iv["p50"] > 0 and d2.get("ps_p50") is not None else None,
                            "mean_v2": d2.get("ps_mean"), "p50_v1": iv.get("p50"), "p50_v2": d2.get("ps_p50")})
    return out


def judge(rows) -> dict:
    g = lambda k: [x[k] for x in rows if x[k] is not None]
    t1, t2, s1, s2, r = g("top1_v1"), g("top1_v2"), g("spread_v1"), g("spread_v2"), g("p50_ratio")
    res = {"n": len(rows), "names_with_invalid": sum(1 for x in rows if x["invalid"] > 0),
           "top1_median_v1": _q(t1, .5), "top1_median_v2": _q(t2, .5), "top1_p90_v1": _q(t1, .9), "top1_p90_v2": _q(t2, .9),
           "spread_median_v1": _q(s1, .5), "spread_median_v2": _q(s2, .5), "p50_ratio_median": _q(r, .5)}
    ok = lambda a, b: a is not None and b is not None and a <= MULT * b
    res["E8a"] = res["names_with_invalid"] == 0
    res["E8b"] = ok(res["top1_median_v2"], res["top1_median_v1"]) and ok(res["top1_p90_v2"], res["top1_p90_v1"])
    res["E8c"] = ok(res["spread_median_v2"], res["spread_median_v1"])
    res["E8d"] = res["p50_ratio_median"] is not None and BAND[0] <= res["p50_ratio_median"] <= BAND[1]
    res["pass"] = all(res[k] for k in ("E8a", "E8b", "E8c", "E8d"))
    return res


def score(rows, include_diagnostic=False) -> dict:
    held = [x for x in rows if include_diagnostic or x["date"] not in DIAGNOSTIC_DATES]
    diag = [x for x in rows if x["date"] in DIAGNOSTIC_DATES]
    rep = {"held_out": {}, "diagnostic_dates_reported_apart": {}, "dates": sorted({x["date"] for x in held})}
    for fam in FAMILIES:
        sub = [x for x in held if x["family"] == fam]
        rep["held_out"][fam] = {"pooled": judge(sub), "by_year": {y: judge([x for x in sub if x["year"] == y]) for y in sorted({x["year"] for x in sub})}}
        rep["diagnostic_dates_reported_apart"][fam] = judge([x for x in diag if x["family"] == fam])
    rep["E8"] = "PASS" if all(v["pooled"]["pass"] and all(b["pass"] for b in v["by_year"].values()) for v in rep["held_out"].values()) else "FAIL"
    return rep


def main(argv=None):
    a = argv or sys.argv[1:]
    rows = rows_of(a[0])
    rep = score(rows, include_diagnostic="--include-diagnostic-dates" in a)
    rep["sample"] = a[a.index("--sample") + 1] if "--sample" in a else "forensic"
    Path(a[1]).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "held_out_dates": len(rep["dates"]), "written": a[1], "note": "verdict sealed until cross-check 12 is ruled (AL.31)"}))


if __name__ == "__main__":
    main()
