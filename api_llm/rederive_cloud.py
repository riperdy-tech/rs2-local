#!/usr/bin/env python3
"""rederive_cloud.py - re-judge finished cloud-arm runs under the CURRENT guard. No API calls.

WHY. The 28-ticker flash sweep was judged by the pre-2026-08-24 guard, which DELETED samples
failing a calibrated threshold. The guard was redesigned that evening to ANNOTATE instead
(audit/N_guard_redesign_study_20260824.md), and the local arm's published verdicts were
re-derived accordingly by tools/audit_202608/rederive_verdicts.py. Until the cloud arm is
re-judged the same way, the two arms are graded by different judges and any comparison between
them measures the guard change as much as the models.

Every sample report is already on disk, so re-judging costs nothing: re-run extract_iv, the
current plausibility, and band_verdict over the saved text.

WRITES consensus_rederived.json / verdict_rederived.json BESIDE the originals. The originals are
never modified - they are the record of what was actually published at the time.

  python api_llm/rederive_cloud.py                  # every cloud run
  python api_llm/rederive_cloud.py AAPL ABNB        # named tickers only
"""
import json
import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "audit_202608"))

_STDOUT_KEEPALIVE = [sys.stdout]
import consensus_valuation as cv     # noqa: E402
_STDOUT_KEEPALIVE.append(sys.stdout)
import depth_pipeline as dp          # noqa: E402

OUT = HERE / "deep_api"


def rederive(d):
    """Re-judge one run directory. Returns (old_direction, new_direction, doc) or None."""
    src = d / "consensus.json"
    if not src.exists():
        return None
    doc = json.loads(src.read_text(encoding="utf-8"))
    t, price = doc["ticker"], doc.get("price")
    runs = []
    for r in doc.get("runs", []):
        rep_file = d / f"sample{r['sample']}.md"
        if not rep_file.exists():
            continue
        rep = rep_file.read_text(encoding="utf-8")
        ivs = cv.extract_iv(rep, price)
        iv = st.median(ivs) if ivs else None
        ok, why, flags = cv.plausibility(iv, price, t)
        nr = dict(r)
        nr.update({"iv": iv, "all_iv_mentions": sorted(set(ivs))[:8],
                   "plausible": ok, "reasons": why, "flags": flags})
        runs.append(nr)
    if not runs:
        return None
    good = [r for r in runs if r["iv"] and r["plausible"] and not r["truncated"]]
    ivs = [r["iv"] for r in good]
    spread = (max(ivs) / min(ivs) - 1) * 100 if len(ivs) >= 2 else None
    med = st.median(ivs) if ivs else None
    converged = bool(spread is not None and spread <= cv.TOL_PCT)
    new = dict(doc)
    new.update({"runs": runs, "n_plausible": len(good), "median_iv": med,
                "spread_pct": round(spread, 1) if spread is not None else None,
                "converged": converged,
                "verdict": ("USABLE - complete and converged" if converged and med else
                            "NOT USABLE - runs disagree beyond tolerance" if med and spread is not None else
                            "NOT USABLE - no usable sample"),
                "median_mos_pct": round((med / price - 1) * 100, 1) if med and price else None,
                "rederived_at": datetime.now(timezone.utc).isoformat(),
                "rederived_from": "consensus.json",
                "_rederive_note": "re-judged under the current guard (annotate, not delete); "
                                  "the original consensus.json is the as-published record"})
    (d / "consensus_rederived.json").write_text(json.dumps(new, indent=2), encoding="utf-8")
    v = dp.band_verdict(new)
    v.update({"consensus_dir": d.name, "arm": "cloud_api", "rederived": True})
    (d / "verdict_rederived.json").write_text(json.dumps(v, indent=2), encoding="utf-8")

    old_v = json.loads((d / "verdict_depth.json").read_text(encoding="utf-8")) \
        if (d / "verdict_depth.json").exists() else {}
    return old_v.get("direction"), v.get("direction"), new


def main():
    want = {a.upper() for a in sys.argv[1:] if not a.startswith("--")}
    dirs = sorted(p for p in OUT.glob("*_2026*") if p.is_dir())
    flips, done = [], 0
    print(f"{'DIR':30}{'OLD':12}{'NEW':12}{'SPREAD':>9}{'N':>3}  flags")
    for d in dirs:
        if want and d.name.split("_")[0] not in want:
            continue
        r = rederive(d)
        if not r:
            continue
        old, new, doc = r
        done += 1
        fl = sorted({f for x in doc["runs"] for f in x.get("flags", [])})
        mark = "" if old == new else "   <-- DIRECTION CHANGED"
        if old != new:
            flips.append((d.name, old, new))
        print(f"{d.name:30}{str(old):12}{str(new):12}{str(doc['spread_pct']):>9}"
              f"{doc['n_plausible']:>3}  {', '.join(fl)[:60]}{mark}")
    print(f"\n{done} runs re-judged | {len(flips)} direction changes")
    for n, o, w in flips:
        print(f"  {n}: {o} -> {w}")


if __name__ == "__main__":
    main()
