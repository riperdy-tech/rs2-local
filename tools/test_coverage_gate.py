#!/usr/bin/env python3
"""Acceptance test for the data_health coverage gate.

A gate that cannot fail is worse than no gate: it reads as protection while protecting nothing.
This exercises the real audit_field_coverage against a TEMP baseline copy, so cache/field_coverage
.json is never touched, and asserts all three behaviours that matter:

  1. baseline matches reality              -> comparable, no regressions, CLEAR
  2. baseline claims coverage we lack      -> comparable, regressions found, BLOCK
  3. case 2 PLUS a churned live book       -> NOT COMPARABLE, no regressions, CLEAR

Case 3 is the false-trip guard and is the reason the population is recorded in the baseline at all.
Coverage percentages are only comparable across builds when measured over the same names, so adding
or dropping tickers must not block a sweep.

A note on why this file exists at all: the first version of case 2 inflated revenue, ocf and
pe_ratio — all already near 99% — through a min(100, v + 40) cap, so the constructed "drop" was
0.7 points, under the 10-point threshold. The test reported FAIL and the gate was innocent. The
targets are now chosen for real headroom, which is why the selection is computed rather than
hard-coded.

    python tools/test_coverage_gate.py          # exit 0 = all three pass
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import rs2_data          # noqa: E402
import data_health as dh  # noqa: E402


def main():
    live = dh.COVERAGE_BASELINE
    if not live.exists():
        print(f"SKIP — no baseline at {live}. Arm it first:\n"
              f"    python data_health.py --update-baseline")
        return 0
    real = json.loads(live.read_text(encoding="utf-8-sig"))
    if not real.get("tickers"):
        print("SKIP — baseline predates population recording. Re-arm with --update-baseline.")
        return 0

    hist = rs2_data.load_json(dh.SD / "fundamentals_history.json") or {}
    hist = hist.get("tickers") or hist
    tickers = dh.live_tickers()
    print(f"population: {len(tickers)} live names")

    tmpdir = Path(tempfile.mkdtemp(prefix="rs2_covgate_"))
    results = []

    def case(label, baseline_obj, expect_block):
        p = tmpdir / "baseline.json"
        p.write_text(json.dumps(baseline_obj), encoding="utf-8")
        dh.COVERAGE_BASELINE = p
        try:
            _dead, regressed, _cur, comparable = dh.audit_field_coverage(tickers, hist)
        finally:
            dh.COVERAGE_BASELINE = live
        blocked = len(regressed) > 0
        ok = blocked == expect_block
        print(f"\n{label}\n   comparable={comparable}  regressions={len(regressed)}  "
              f"gate={'BLOCK' if blocked else 'CLEAR'}  -> {'PASS' if ok else '*** FAIL ***'}")
        for r in regressed[:4]:
            print(f"      {r['field']:44s} {r['was']}% -> {r['now']}%  (drop {r['drop']})")
        results.append(ok)

    case("[1] baseline matches reality  (expect CLEAR)", real, expect_block=False)

    # Targets need headroom: setting a field already at 99% to 100% yields a 1pt drop, below the
    # threshold, and would test nothing.
    broken = json.loads(json.dumps(real))
    targets = [k for k, v in real["coverage"].items()
               if v < 100.0 - dh.REGRESS_PTS - 5][:3]
    if not targets:
        print("\nSKIP cases 2-3 — every field is within the threshold of 100%, so no regression "
              "can be constructed without inventing one.")
        return 0 if all(results) else 1
    for f in targets:
        broken["coverage"][f] = 100.0
    case(f"[2] baseline claims 100% on {', '.join(targets)}  (expect BLOCK)",
         broken, expect_block=True)

    churned = json.loads(json.dumps(broken))       # same fake regression...
    drop_n = max(1, int(len(real["tickers"]) * (dh.POP_DRIFT_MAX * 2)))
    churned["tickers"] = sorted(set(real["tickers"]) - set(real["tickers"][:drop_n]))
    case(f"[3] same regression, book churned by {drop_n} names  (expect CLEAR, not comparable)",
         churned, expect_block=False)

    ok = all(results)
    print("\nRESULT:", "ALL PASS — the gate can block, and will not false-trip on churn"
          if ok else "*** A CASE FAILED — the gate is not doing its job ***")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
