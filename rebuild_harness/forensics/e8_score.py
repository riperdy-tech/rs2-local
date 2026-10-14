"""E8, engine v2's valuation-sanity check (SPEC_rebuild Addenda AL.27, AL.28, AL.29, AL.31; AK.51 items 1, 2, 6): v2 against v1 on the same inputs, from
forensic-run (or gate-2b harness) records carrying `rec["e5"]` with v2's distribution.

    python -m rebuild_harness.forensics.e8_score RUN_DIR OUT.json [--sample forensic|gate2b] [--expected-dates D1,D2,...] [--lineage LINEAGE.json]
                                                 [--include-diagnostic-dates]

Per name: invalid draws (v2); the top-1% and top-5% shares of mean equity (v1, v2); EV P90/P50 (operating; financial: equity P90/P50, the floor being
immaterial there); P50 equity v2/v1.  Bars, per family (operating, financial), pooled and in each valuation year:
  E8a   invalid draws = 0 in every name
  E8b   median top-1% share <= 2 x v1's median, and 90th percentile <= 2 x v1's 90th percentile
  E8b'  median top-5% share <= 2 x v1's median, and 90th percentile <= 2 x v1's 90th percentile (AK.51 item 6)
  E8c   median EV P90/P50 <= 2 x v1's median
  E8d   median of P50 v2/v1 in [0.5, 2.0]
FAILS CLOSED (AK.51 item 2): every in-scope name v1 valued is reconciled (valued by both, or excluded with its reason).  A v2 refusal with no named engine
reason, an instrumentation error, or an expected date without records fails E8.
The forensic sample's verdict EXCLUDES the two dates used to choose the interim (2021-06-30, 2024-06-30; AL.29); they are reported apart.
Reported diagnostics, not bars (AK.51): mean_iv / P50; the 90th percentile of equity P90/P50; the median mean_iv / price; the mean over dates of the
within-family rank correlation of v2's and v1's P50.
AL.31: the verdict is written to OUT.json and NOT printed; the console shows counts only."""
import gzip
import json
import math
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


def new_recon() -> dict:
    return {"attempted": 0, "both_valued": 0, "v2_refused_named": [], "v2_refused_unnamed": [], "instrumentation_errors": [], "continuation": {}}


def rows_of(run_dir, recon=None):
    out = []
    for f in sorted(Path(run_dir).glob("records_*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                e, v = r.get("e5"), r.get("val") or {}
                if e is None or r.get("status") != "valued" or v.get("status") != "ok":
                    continue                                           # not attempted by E8: v1 did not value it, or out of the >= $300M scope
                if "error" in e:
                    if recon is not None:
                        recon["attempted"] += 1
                        recon["instrumentation_errors"].append([r["date"], r["cik"], str(e["error"])[:160]])
                    continue
                fam = e.get("family")
                if fam not in FAMILIES:
                    continue                                           # commodity: out of scope (V3)
                d2 = e.get("v2_dist") or {}
                if recon is not None:
                    recon["attempted"] += 1
                if d2.get("status") != "ok":
                    if recon is not None:
                        why = list(d2.get("reasons") or ([d2["why"]] if d2.get("why") else []))
                        (recon["v2_refused_named"] if why else recon["v2_refused_unnamed"]).append([r["date"], r["cik"], why[:2]])
                    continue
                if recon is not None:
                    recon["both_valued"] += 1
                    c = d2.get("continuation")                         # v2.1 (AL.40-AL.43): which continuation each valued name used
                    kind = "not_recorded" if c is None else "K" if c.startswith("K:") else "family_pooled" if "family_pooled" in c else "measured"
                    recon["continuation"][kind] = recon["continuation"].get(kind, 0) + 1
                iv = v.get("iv_ps") or {}
                if fam == "operating":
                    ev1 = (e["v1_ev_p90"] / e["v1_ev_p50"]) if e.get("v1_ev_p50") and e["v1_ev_p50"] > 0 and e.get("v1_ev_p90") is not None else None
                    ev2 = (d2["ev_p90"] / d2["ev_p50"]) if d2.get("ev_p50") and d2["ev_p50"] > 0 and d2.get("ev_p90") is not None else None
                else:
                    ev1 = (iv["p90"] / iv["p50"]) if iv.get("p50") and iv["p50"] > 0 else None
                    ev2 = (d2["ps_p90"] / d2["ps_p50"]) if d2.get("ps_p50") and d2["ps_p50"] > 0 else None
                out.append({"date": r["date"], "year": r["date"][:4], "cik": r["cik"], "family": fam, "invalid": d2["n_invalid"],
                            "top1_v1": e.get("v1_top1pct_share_of_mean"), "top1_v2": d2.get("top1pct_share_of_mean"),
                            "top5_v1": e.get("v1_top5pct_share_of_mean"), "top5_v2": d2.get("top5pct_share_of_mean"),
                            "spread_v1": ev1, "spread_v2": ev2,
                            "p50_ratio": (d2["ps_p50"] / iv["p50"]) if iv.get("p50") and iv["p50"] > 0 and d2.get("ps_p50") is not None else None,
                            "eq_p90p50_v2": (d2["ps_p90"] / d2["ps_p50"]) if d2.get("ps_p50") and d2["ps_p50"] > 0 else None,
                            "mean_over_price_v2": (d2["ps_mean"] / r["price"]) if d2.get("ps_mean") is not None and r.get("price") else None,
                            "mean_v2": d2.get("ps_mean"), "p50_v1": iv.get("p50"), "p50_v2": d2.get("ps_p50")})
    return out


def judge(rows) -> dict:
    g = lambda k: [x[k] for x in rows if x[k] is not None]
    t1, t2, f1, f2, s1, s2, r = g("top1_v1"), g("top1_v2"), g("top5_v1"), g("top5_v2"), g("spread_v1"), g("spread_v2"), g("p50_ratio")
    res = {"n": len(rows), "names_with_invalid": sum(1 for x in rows if x["invalid"] > 0),
           "top1_median_v1": _q(t1, .5), "top1_median_v2": _q(t2, .5), "top1_p90_v1": _q(t1, .9), "top1_p90_v2": _q(t2, .9),
           "top5_median_v1": _q(f1, .5), "top5_median_v2": _q(f2, .5), "top5_p90_v1": _q(f1, .9), "top5_p90_v2": _q(f2, .9),
           "spread_median_v1": _q(s1, .5), "spread_median_v2": _q(s2, .5), "p50_ratio_median": _q(r, .5),
           "diag_mean_over_p50_median_v2": _q([x["mean_v2"] / x["p50_v2"] for x in rows if x["mean_v2"] is not None and x["p50_v2"]], .5),
           "diag_eq_p90p50_p90_v2": _q(g("eq_p90p50_v2"), .9), "diag_mean_over_price_median_v2": _q(g("mean_over_price_v2"), .5)}
    ok = lambda a, b: a is not None and b is not None and a <= MULT * b
    res["E8a"] = res["names_with_invalid"] == 0
    res["E8b"] = ok(res["top1_median_v2"], res["top1_median_v1"]) and ok(res["top1_p90_v2"], res["top1_p90_v1"])
    res["E8b_prime"] = ok(res["top5_median_v2"], res["top5_median_v1"]) and ok(res["top5_p90_v2"], res["top5_p90_v1"])
    res["E8c"] = ok(res["spread_median_v2"], res["spread_median_v1"])
    res["E8d"] = res["p50_ratio_median"] is not None and BAND[0] <= res["p50_ratio_median"] <= BAND[1]
    res["pass"] = bool(rows) and all(res[k] for k in ("E8a", "E8b", "E8b_prime", "E8c", "E8d"))
    return res


def _rank_corr(rows):
    """Diagnostic (AK.51): the mean over dates of the Spearman correlation of v2's and v1's P50 per share."""
    import numpy as np
    out = []
    for d in sorted({x["date"] for x in rows}):
        sub = [x for x in rows if x["date"] == d and x["p50_v1"] is not None and x["p50_v2"] is not None]
        if len(sub) >= 20:
            a = np.argsort(np.argsort([x["p50_v1"] for x in sub]))
            b = np.argsort(np.argsort([x["p50_v2"] for x in sub]))
            out.append(float(np.corrcoef(a, b)[0, 1]))
    return sum(out) / len(out) if out else None


def score(rows, include_diagnostic=False, expected_dates=None, recon=None) -> dict:
    held = [x for x in rows if include_diagnostic or x["date"] not in DIAGNOSTIC_DATES]
    diag = [x for x in rows if x["date"] in DIAGNOSTIC_DATES]
    rep = {"held_out": {}, "diagnostic_dates_reported_apart": {}, "dates": sorted({x["date"] for x in held})}
    for fam in FAMILIES:
        sub = [x for x in held if x["family"] == fam]
        rep["held_out"][fam] = {"pooled": judge(sub), "by_year": {y: judge([x for x in sub if x["year"] == y]) for y in sorted({x["year"] for x in sub})},
                                "diag_rank_corr_p50_v1_v2": _rank_corr(sub)}
        rep["diagnostic_dates_reported_apart"][fam] = judge([x for x in diag if x["family"] == fam])
    rep["missing_dates"] = sorted(set(expected_dates or []) - {x["date"] for x in rows})
    rep["reconciliation"] = recon
    rep["fails_closed"] = bool(rep["missing_dates"]) or bool(recon and (recon["v2_refused_unnamed"] or recon["instrumentation_errors"]))
    passes = all(v["pooled"]["pass"] and all(b["pass"] for b in v["by_year"].values()) for v in rep["held_out"].values())
    rep["E8"] = "PASS" if (passes and not rep["fails_closed"]) else "FAIL"
    return rep


def main(argv=None):
    a = argv or sys.argv[1:]
    recon = new_recon()
    rows = rows_of(a[0], recon)
    expected = a[a.index("--expected-dates") + 1].split(",") if "--expected-dates" in a else None
    rep = score(rows, include_diagnostic="--include-diagnostic-dates" in a, expected_dates=expected, recon=recon)
    rep["sample"] = a[a.index("--sample") + 1] if "--sample" in a else "forensic"
    rep["lineage"] = json.loads(Path(a[a.index("--lineage") + 1]).read_text(encoding="utf-8")) if "--lineage" in a else None
    Path(a[1]).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "held_out_dates": len(rep["dates"]), "attempted": recon["attempted"], "both_valued": recon["both_valued"],
                      "written": a[1], "note": "verdict sealed (AL.31)"}))


if __name__ == "__main__":
    main()
