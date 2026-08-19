#!/usr/bin/env python3
"""P3 — the noise floor. How often does the SAME prompt give a DIFFERENT answer?

Every A/B in this project has been read without knowing this number, which makes all of them
uninterpretable. P1 saw 3 majority flips in 29 paired comparisons; whether that is an effect or
sampling noise cannot be decided without the floor.

METHOD. Take the regime vote — the only LLM call that can move a published valuation — and run it
REPEATS times on the IDENTICAL prompt, unchanged, same model, same options. Any variation is pure
sampling noise. Report, per ticker: the distribution of individual votes, and how often a
3-sample majority (production's actual rule) differs from the modal majority.

That last number is the one that matters: production takes a 3-sample majority, so the question is
not "do individual samples vary" but "does the DECISION vary". If it does, then a 3-flip result in
a 29-name A/B is inside the noise and P1's rejection is doubly safe.

  python tools/audit_202608/p3_noise_floor.py [--repeats 21] [TICKER ...]
"""
import io
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import common  # noqa: E402
common.enable_json_cache()
import run_rs2  # noqa: E402
import valuation_backbone as vb  # noqa: E402

OUT = HERE / "audit" / "C_experiments" / "p3_noise_floor.json"
LBL = {"current_earnings": "current earnings", "owner_earnings": "owner earnings",
       "midcycle": "mid-cycle"}


def one_vote(prompt, cells):
    try:
        out = run_rs2.ollama_chat(prompt, 8192, False, retries=1, timeout=300)
    except Exception:
        return None
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    c = run_rs2._REGIME_LABELS.get(str(j.get("basis", "")).strip().lower())
    return c if c in cells else None


def main():
    reps = int(sys.argv[sys.argv.index("--repeats") + 1]) if "--repeats" in sys.argv else 21
    tickers = [a.upper() for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()]
    if not tickers:
        tickers = ["COHR", "CASY", "KFY"]        # P1's three flippers — the exact contested cases
    rows, t0 = [], time.time()
    for t in tickers:
        bb = vb.backbone(t)
        cells = (bb.get("lattice") or {}).get("cells") or {}
        if len(cells) < 2:
            print(f"{t}: skip (1-cell lattice)")
            continue
        r = []
        for key in ("current_earnings", "owner_earnings", "midcycle"):
            c = cells.get(key)
            if c:
                r.append(f"* {LBL[key]}: base ${c['base_cf_b']:.2f}B -> price implies "
                         f"{c['implied_growth']*100:.1f}%/yr growth, margin of safety "
                         f"{c['mos_pct']:+.1f}%")
        prompt = run_rs2.REGIME_PROMPT.format(cells="\n".join(r),
                                              evidence=run_rs2._regime_evidence(t, bb))
        votes = []
        for i in range(reps):
            v = one_vote(prompt, cells)
            votes.append(v)
            print(f"  {t} {i+1}/{reps}: {v}", flush=True)
        good = [v for v in votes if v]
        cnt = Counter(good)
        # production rule: 3 consecutive samples, majority wins. Slide over the run.
        majs = []
        for i in range(0, len(good) - 2):
            w = good[i:i + 3]
            c = Counter(w).most_common(1)[0]
            majs.append(c[0] if c[1] >= 2 else None)
        mc = Counter(m for m in majs if m)
        modal = mc.most_common(1)[0][0] if mc else None
        unstable = sum(1 for m in majs if m != modal)
        rows.append({"ticker": t, "repeats": reps, "vote_distribution": dict(cnt),
                     "n_parsed": len(good),
                     "modal_3sample_majority": modal,
                     "n_3sample_windows": len(majs),
                     "n_windows_differing_from_modal": unstable,
                     "decision_instability_pct": round(100 * unstable / len(majs), 1) if majs else None})
        print(f"  -> {t}: votes {dict(cnt)} | 3-sample decision differs from modal in "
              f"{unstable}/{len(majs)} windows", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "probe": "P3 noise floor — identical prompt repeated",
        "elapsed_s": round(time.time() - t0), "rows": rows,
        "interpretation": ("If decision_instability_pct is materially above zero, a small number "
                           "of majority flips in any A/B of this call is inside the noise and "
                           "cannot be attributed to the change under test.")},
        indent=2), encoding="utf-8")
    print(f"\n[p3] -> {OUT}")


if __name__ == "__main__":
    main()
