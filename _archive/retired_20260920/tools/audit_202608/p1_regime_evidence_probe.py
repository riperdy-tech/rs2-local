#!/usr/bin/env python3
"""P1 — does un-gating the basis-decision evidence change the basis decision?

THE DEFECT (run_rs2.py:938-945). One line decides what the earnings-basis vote is allowed to see:

    ni, da, cx, ocf = (rec.get("net_income"), rec.get("da"), rec.get("capex"), rec.get("ocf"))
    if None not in (ni, da, cx):        # <-- a missing D&A blanks the WHOLE cash-flow block

A null D&A therefore suppresses net income, D&A, capex, operating cash flow AND free cash flow
together. The prompt still asks the model to decide "whether the capex is converting" — with no
capex, no OCF and no FCF in front of it.

WHY IT MATTERS MORE THAN QUANTIZATION OR SAMPLING. Published fair value is deterministic
(run_rs2.py:1896 calls it "never a model number") and rule 15 forbids the report printing a
different one. The ONLY LLM call that can move a published valuation is regime_decide, which RS2's
own comments value at ~80 points of margin of safety. On the names below, that call runs blind.

GOOG is the worked example: its TTM record has no `da`, so the pack withheld TTM net income
$244.21B against operating cash flow $185.68B — the most direct one-off tell available, already on
disk — and all three samples voted current_earnings citing the contaminated quarter itself.

DESIGN. Paired, same ticker, same cells, same sampling, same model: OLD pack (production
_regime_evidence) vs NEW pack (identical except each available cash-flow field prints
independently). Nothing else differs, so a flip is attributable.

PRE-REGISTERED DECISION RULE — fixed before the run, per CLAUDE.md §0:
  * JUSTIFIED  if >=1 majority basis flips AND every flip runs TOWARD the withheld evidence
                (i.e. away from current_earnings on names where NI > OCF).
  * REJECTED   if flips are bidirectional, or if flips occur on names where the withheld
                evidence does not support them.
  * INCONCLUSIVE if no majority changes at all — the gate is then a latent defect, not a live one.

  python tools/audit_202608/p1_regime_evidence_probe.py [--samples 3] [--limit N]
"""
import io
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import run_rs2  # noqa: E402
import valuation_backbone as vb  # noqa: E402

OUT = HERE / "audit" / "C_experiments" / "p1_regime_evidence.json"


def new_evidence(t, bb):
    """production pack, with the cash-flow block un-gated: each field prints if present."""
    base = run_rs2._regime_evidence(t, bb)
    rec = (vb._ttm_record(t) or {}).get("fields") or {}
    ni, da, cx, ocf = (rec.get(k) for k in ("net_income", "da", "capex", "ocf"))
    if not rec or (None not in (ni, da, cx)):
        return base, False          # gate did not fire; pack already complete
    parts = []
    if ni is not None:
        parts.append(f"net income ${ni/1e9:.1f}B")
    if da is not None:
        parts.append(f"D&A ${da/1e9:.1f}B")
    else:
        parts.append("D&A NOT REPORTED in our extract")
    if cx is not None:
        parts.append(f"capex ${cx/1e9:.1f}B")
    if ocf is not None:
        parts.append(f"operating cash flow ${ocf/1e9:.1f}B")
    if ocf is not None and cx is not None:
        parts.append(f"free cash flow ${(ocf-cx)/1e9:+.1f}B")
    lines = ["TTM: " + ", ".join(parts)]
    if ni is not None and ocf is not None:
        gap = ni - ocf
        lines.append(f"  -> net income {'EXCEEDS' if gap > 0 else 'is below'} operating cash flow "
                     f"by ${abs(gap)/1e9:.1f}B. Earnings above cash generation can indicate "
                     f"non-operating or non-cash income in the reported figure.")
    if cx is not None and da is not None and da:
        lines.append(f"  -> capex is {cx/da:.1f}x D&A")
    elif cx is not None and ocf:
        lines.append(f"  -> capex absorbs {100*cx/ocf:.0f}% of operating cash flow")
    ins = "\n".join(lines)
    marker = "Delivered growth"
    return (base.replace(marker, ins + "\n" + marker, 1) if marker in base
            else base + "\n" + ins), True


def vote(t, bb, evidence, samples):
    cells = (bb.get("lattice") or {}).get("cells") or {}
    # label back-map: the prompt names bases the way _REGIME_LABELS parses them back
    LBL = {"current_earnings": "current earnings", "owner_earnings": "owner earnings",
           "midcycle": "mid-cycle"}
    rows = []
    for key in ("current_earnings", "owner_earnings", "midcycle"):
        c = cells.get(key)
        if c:
            rows.append(f"* {LBL[key]}: base ${c['base_cf_b']:.2f}B "
                        f"-> price implies {c['implied_growth']*100:.1f}%/yr growth, margin of "
                        f"safety {c['mos_pct']:+.1f}%")
    if not rows:
        return None, []
    prompt = run_rs2.REGIME_PROMPT.format(cells="\n".join(rows), evidence=evidence)
    votes, why = [], []
    for _ in range(samples):
        try:
            out = run_rs2.ollama_chat(prompt, 8192, False, retries=1, timeout=300)
        except Exception as e:
            why.append(f"error: {str(e)[:80]}")
            continue
        import re
        m = re.search(r"\{.*\}", out or "", re.S)
        if not m:
            why.append("unparseable")
            continue
        try:
            j = json.loads(m.group(0))
        except json.JSONDecodeError:
            why.append("bad json")
            continue
        cell = run_rs2._REGIME_LABELS.get(str(j.get("basis", "")).strip().lower())
        if cell in cells:
            votes.append(cell)
            why.append(str(j.get("reasons", ""))[:220])
    maj = max(set(votes), key=votes.count) if votes else None
    if votes and votes.count(maj) * 2 <= len(votes):
        maj = None       # no majority
    return maj, why


def main():
    samples = int(sys.argv[sys.argv.index("--samples") + 1]) if "--samples" in sys.argv else 3
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    st = json.loads((HERE / "cache" / "analysis_state.json").read_text(encoding="utf-8-sig"))

    targets = []
    for t in sorted(st):
        try:
            bb = vb.backbone(t)
        except Exception:
            continue
        if not bb.get("ok"):
            continue
        cells = (bb.get("lattice") or {}).get("cells") or {}
        if len(cells) < 2:
            continue                      # no real choice to make
        _, fired = new_evidence(t, bb)
        if fired:
            targets.append((t, bb))
    if limit:
        targets = targets[:limit]
    print(f"[p1] {len(targets)} contested names whose cash-flow block is gated off: "
          f"{[t for t, _ in targets]}", flush=True)

    rows, t0 = [], time.time()
    for i, (t, bb) in enumerate(targets, 1):
        old_pack = run_rs2._regime_evidence(t, bb)
        new_pack, _ = new_evidence(t, bb)
        o_maj, o_why = vote(t, bb, old_pack, samples)
        n_maj, n_why = vote(t, bb, new_pack, samples)
        rec = (vb._ttm_record(t) or {}).get("fields") or {}
        ni, ocf = rec.get("net_income"), rec.get("ocf")
        rows.append({"ticker": t, "old_majority": o_maj, "new_majority": n_maj,
                     "flipped": o_maj != n_maj,
                     "ni_gt_ocf": bool(ni and ocf and ni > ocf),
                     "ni_b": round(ni/1e9, 1) if ni else None,
                     "ocf_b": round(ocf/1e9, 1) if ocf else None,
                     "old_reasons": o_why[:1], "new_reasons": n_why[:1]})
        print(f"[p1] {i}/{len(targets)} {t}: {o_maj} -> {n_maj}"
              + ("  *** FLIP ***" if o_maj != n_maj else ""), flush=True)

    flips = [r for r in rows if r["flipped"]]
    toward = [r for r in flips if r["ni_gt_ocf"] and r["old_majority"] == "current_earnings"]
    if not flips:
        verdict = "INCONCLUSIVE — gate is a latent defect on this book, not a live one"
    elif len(toward) == len(flips):
        verdict = "JUSTIFIED — every flip ran toward the withheld evidence"
    else:
        verdict = "REJECTED — flips were bidirectional or unsupported by the withheld evidence"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "probe": "P1 regime-evidence un-gating", "samples_per_arm": samples,
        "n_targets": len(rows), "n_flips": len(flips),
        "n_flips_toward_withheld_evidence": len(toward),
        "verdict": verdict, "elapsed_s": round(time.time() - t0),
        "rows": rows}, indent=2), encoding="utf-8")
    print(f"\n[p1] {len(flips)}/{len(rows)} majorities flipped | {verdict}")
    print(f"[p1] -> {OUT}")


if __name__ == "__main__":
    main()
