#!/usr/bin/env python3
"""sample_count_replay.py — what would 2 samples have decided, on the runs we already paid for?

QUESTION (operator, 2026-08-23): the depth tier runs 3 seeded samples at ~36-43 min each. Would
2 samples, escalating to a 3rd only when they disagree, have reached the same VERDICT? That is a
time-vs-accuracy trade and it is answerable without a single new GPU-hour, because every
consensus run already stored its per-sample IV, plausibility, truncation flag and wall-clock.

METHOD, and why it is trustworthy:
  1. REPRODUCE FIRST. The band-direction rule is re-implemented here and replayed over the FULL
     sample set of every archived run. It must reproduce the stored verdict_depth.json exactly.
     Any mismatch and the tool reports its own failure and refuses to show counterfactuals — a
     counterfactual from a rule that cannot reproduce the past is worthless.
  2. Only then replay the adaptive 2-escalate rule (consensus_valuation.py's EARLY_TOL_PCT /
     TOL_PCT) over samples 1-2 of the same runs, and diff the DIRECTION — the field the verdict
     actually publishes. Median IV moving is not a failure; direction flipping is.
  3. Sweep the early-stop bar so the threshold is chosen from measurement, not from taste.

WHAT THIS CANNOT TELL YOU: sample ordering. Early-stop uses samples 1 and 2 as drawn, so the
counterfactual inherits whatever those two seeds gave. It measures the rule on the draws we have,
which is the same population production would face.

  python tools/audit_202608/sample_count_replay.py
  python tools/audit_202608/sample_count_replay.py --dir ab_reports/consensus
"""
import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]

EARLY_TOL_PCT = 15.0        # consensus_valuation.py — 2-sample early-stop bar
TOL_PCT = 25.0              # consensus_valuation.py — 3-sample tolerance
SIZE_BUCKETS = ((15.0, "full"), (30.0, "half"), (10**9, "quarter"))   # depth_pipeline.py


def usable(r):
    return bool(r.get("iv")) and r.get("plausible") and not r.get("truncated")


def verdict_from(runs, price, early_stop):
    """depth_pipeline.band_verdict, re-implemented over an arbitrary sample subset."""
    ivs = sorted(r["iv"] for r in runs if usable(r))
    if not ivs or not price:
        return {"direction": "NOT_USABLE", "size_hint": None, "n_basis": 0,
                "low": None, "high": None, "median": None, "spread": None}
    spread = (max(ivs) / min(ivs) - 1) * 100 if len(ivs) >= 2 else None
    d = ("overvalued" if price > ivs[-1] else
         "undervalued" if price < ivs[0] else "hold")
    size = next(lbl for cap, lbl in SIZE_BUCKETS if (spread or 0.0) <= cap)
    if len(ivs) == 1:
        size = "quarter"
    return {"direction": d, "size_hint": size, "n_basis": len(ivs),
            "low": ivs[0], "high": ivs[-1], "median": st.median(ivs), "spread": spread,
            "converged": spread is not None and spread <= (EARLY_TOL_PCT if early_stop else TOL_PCT)}


def adaptive_replay(runs, price, bar):
    """consensus_valuation's adaptive 2-escalate, replayed. Returns (verdict, n_samples_used)."""
    first2 = [r for r in runs if r["sample"] <= 2]
    g2 = [r for r in first2 if usable(r)]
    if len(g2) == 2:
        sp2 = (max(r["iv"] for r in g2) / min(r["iv"] for r in g2) - 1) * 100
        if sp2 <= bar:
            return verdict_from(first2, price, early_stop=True), 2
    return verdict_from(runs, price, early_stop=False), len([r for r in runs])


def main():
    root = HERE / (sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv
                   else "ab_reports/consensus")
    docs = []
    for f in sorted(root.glob("*/consensus.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  skip {f.parent.name}: unreadable ({str(e)[:60]})")
            continue
        vf = f.parent / "verdict_depth.json"
        doc["_stored"] = json.loads(vf.read_text(encoding="utf-8")) if vf.exists() else None
        doc["_dir"] = f.parent.name
        docs.append(doc)
    if not docs:
        print(f"No consensus runs under {root}. Nothing to replay.")
        return 1

    # ---- STEP 1: prove the rule reproduces production ----------------------------------------
    checked = mismatch = 0
    for doc in docs:
        s = doc.get("_stored")
        if not s or s.get("direction") == "NOT_USABLE":
            continue
        mine = verdict_from(doc["runs"], doc.get("price"), early_stop=doc.get("early_stop", False))
        checked += 1
        if (mine["direction"] != s.get("direction") or mine["n_basis"] != s.get("n_basis")
                or mine["low"] != s.get("iv_band_low") or mine["high"] != s.get("iv_band_high")):
            mismatch += 1
            print(f"  MISMATCH {doc['_dir']}: replay {mine['direction']}/n={mine['n_basis']}/"
                  f"${mine['low']}-{mine['high']} vs stored {s.get('direction')}/"
                  f"n={s.get('n_basis')}/${s.get('iv_band_low')}-{s.get('iv_band_high')}")
    print(f"[reproduction] {checked - mismatch}/{checked} archived verdicts reproduced exactly")
    if mismatch:
        print("REFUSING to report counterfactuals — the replayed rule does not reproduce "
              "production. Fix the rule first.")
        return 2
    if checked == 0:
        print("WARNING: no verdict_depth.json alongside any consensus.json — the rule is "
              "UNVERIFIED against production. Counterfactuals below are indicative only.")

    # ---- STEP 2: the 3-vs-2 diff at the shipped bar ------------------------------------------
    three = [(d, verdict_from(d["runs"], d.get("price"), early_stop=False)) for d in docs]
    print(f"\n[corpus] {len(docs)} archived consensus runs")
    n3 = sum(1 for d, _ in three if len(d["runs"]) >= 3)
    print(f"  runs with 3 samples on record: {n3}  (only these can answer the question)")
    secs = [r.get("secs") for d, _ in three for r in d["runs"] if r.get("secs")]
    if secs:
        print(f"  per-sample wall clock: median {st.median(secs):,.0f}s  "
              f"min {min(secs):,.0f}s  max {max(secs):,.0f}s")

    # ---- STEP 3: sweep the early bar ---------------------------------------------------------
    print(f"\n{'bar%':>5} {'early-stopped':>14} {'dir flips':>10} {'size flips':>11} "
          f"{'samples saved':>14} {'GPU-h saved':>12}")
    for bar in (5.0, 10.0, 15.0, 20.0, 25.0):
        stopped = flips = sflips = saved_n = 0
        saved_s = 0.0
        for d, v3 in three:
            if len(d["runs"]) < 3:
                continue
            v2, n = adaptive_replay(d["runs"], d.get("price"), bar)
            if n == 2:
                stopped += 1
                saved_n += 1
                s3 = next((r.get("secs") or 0 for r in d["runs"] if r["sample"] == 3), 0)
                saved_s += s3
                if v2["direction"] != v3["direction"]:
                    flips += 1
                if v2["size_hint"] != v3["size_hint"]:
                    sflips += 1
        print(f"{bar:5.0f} {stopped:>8}/{n3:<5} {flips:>10} {sflips:>11} "
              f"{saved_n:>14} {saved_s/3600:>12.1f}")

    # ---- STEP 4: name every case where the direction would have changed ----------------------
    print(f"\n[detail @ shipped bar {EARLY_TOL_PCT:.0f}%]")
    for d, v3 in three:
        if len(d["runs"]) < 3:
            continue
        v2, n = adaptive_replay(d["runs"], d.get("price"), EARLY_TOL_PCT)
        tag = "EARLY-STOP" if n == 2 else "escalated"
        flag = "  <<< DIRECTION FLIP" if (n == 2 and v2["direction"] != v3["direction"]) else ""
        med2 = f"${v2['median']:,.2f}" if v2["median"] else "-"
        med3 = f"${v3['median']:,.2f}" if v3["median"] else "-"
        dm = (f"{(v2['median']/v3['median']-1)*100:+.1f}%"
              if v2["median"] and v3["median"] else "-")
        print(f"  {d['ticker']:6} {tag:11} 3-sample {v3['direction']:12} {med3:>11} | "
              f"2-sample {v2['direction']:12} {med2:>11} ({dm} median){flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
