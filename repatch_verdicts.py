#!/usr/bin/env python3
"""repatch_verdicts.py — Path A: deterministic re-patch of every existing verdict.json.

Applies the CORRECTED valuation (forward-anchored, consensus-fenced fair value) + the don't-chase
brake to the reports we ALREADY have, WITHOUT re-running the LLM. For each ticker's latest report:
  1. load the saved S3 val_res (keeps the model's stance) and refresh its valuation fields from the
     current valuation_backbone (fixes the trailing-CAGR blowups);
  2. re-run run_rs2.emit_verdict against the existing FINAL.md text -> rewrites verdict.json with the
     new fenced value + brake (graduated on MoS / consensus / 52wk-high) + new fields.

This is the minutes-long 'lower bound' pass (action/conviction ride the OLD-prompt FINAL text; the
brake still downgrades over-bullish BUYs). The full-LLM re-run (orchestrate.py) supersedes it later.

CLI:  python repatch_verdicts.py            # patch all
      python repatch_verdicts.py EXEL MEDP  # patch a subset
"""
import json
import sys
from pathlib import Path

import run_rs2
import valuation_backbone as vb

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
REPORTS = Path(CONFIG["out_reports_dir"])

VAL_REFRESH = ("fair_value", "mos_pct", "realistic_mos_pct", "fair_value_method",
               "consensus_low", "consensus_median", "consensus_high", "consensus_stale",
               "forward_growth", "expectations_gap_pts")


def latest_dir(t):
    ds = sorted(REPORTS.glob(f"{t}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for d in ds:
        if (d / "FINAL.md").exists():
            return d
    return None


def tickers_with_reports():
    seen = set()
    for d in sorted(REPORTS.glob("*_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        name = d.name.split("_")[0]
        if name and name not in seen and (d / "FINAL.md").exists():
            seen.add(name)
    return sorted(seen)


def repatch(t):
    d = latest_dir(t)
    if not d:
        return None
    b = vb.backbone(t)
    # start from the saved val_res (has the model's stance/method); else reconstruct from backbone
    vr = None
    sij = d / "S3_valuation_inputs.json"
    if sij.exists():
        try:
            vr = json.loads(sij.read_text(encoding="utf-8"))
        except Exception:
            vr = None
    if vr is None:
        vr = {"method": b.get("method") if b.get("ok") else "unvalued", "ticker": t,
              "price": b.get("price"), "stance": None}
    # refresh the deterministic valuation fields from the corrected backbone
    if b.get("ok"):
        for k in VAL_REFRESH:
            if k in b:
                vr[k] = b.get(k)
        if b.get("method") == "financial_pb_roe":
            vr["roe_gap_pts"] = b.get("expectations_gap_pts")
    price = vr.get("price") or b.get("price")
    final = (d / "FINAL.md").read_text(encoding="utf-8", errors="ignore")
    before = json.loads((d / "verdict.json").read_text(encoding="utf-8")) if (d / "verdict.json").exists() else {}
    v = run_rs2.emit_verdict(d, t, price, vr, final)
    return before, v


def main():
    args = [a.upper() for a in sys.argv[1:]]
    names = args or tickers_with_reports()
    blow_before = blow_after = braked = done = 0
    for t in names:
        r = repatch(t)
        if not r:
            print(f"{t}: no report/FINAL — skipped")
            continue
        before, v = r
        done += 1
        # INVARIANT, not a threshold. The old check counted |MoS| > 60%, which meant something
        # when fair value was the analyst median for 87% of names and MoS clustered at +2.5%.
        # With the stability fence the engine publishes its OWN value (median -38%, p10 -77%), so
        # 60% is ordinary and the counter cried wolf on 67 healthy names. What IS still a
        # malfunction is |MoS| beyond MOS_EXTREME_MAX — the fence rejects those outright, so this
        # should always be ZERO. A non-zero count means the fence failed, which is worth knowing.
        if before.get("mos_pct") is not None and abs(before["mos_pct"]) > vb.MOS_EXTREME_MAX * 100:
            blow_before += 1
        if v.get("mos_pct") is not None and abs(v["mos_pct"]) > vb.MOS_EXTREME_MAX * 100:
            blow_after += 1
        if v.get("brake_applied"):
            braked += 1
    print(f"\nRepatched {done} verdicts. MoS blowups>60%: {blow_before} -> {blow_after}. "
          f"Brake fired: {braked}.")


if __name__ == "__main__":
    main()
