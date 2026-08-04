#!/usr/bin/env python3
"""signoff_rn.py — RS2 Local vs ChatGPT sign-off over the Research-Now reference set.

Replaces the stale signoff.py (which pointed at the old 24-name 'Chatgpt Reference data' dir).
Compares against the 67 hand-run ChatGPT RS2 analyses in
  'Chatgpt Analysis for RS2 Local Refinement/rs2_actual_deep_research_md/*.md'
on three axes: action family, conviction, and fair-value / margin-of-safety.

Three columns per name:
  GPT       — parsed from the ChatGPT markdown (SECTION 12 / SECTION 11 / SECTION 4).
  RS2 (old) — the latest reports/{T}_*/verdict.json as it stands (pre-fix baseline).
  RS2 (new) — DETERMINISTIC projection: the current consensus-fenced backbone + the don't-chase
              brake applied to the model's OWN raw action from the old verdict (holds the LLM output
              constant, so the delta is purely the engine change — no GPU re-run needed).

CLI:  python signoff_rn.py            # full table + aggregates
      python signoff_rn.py --brief    # aggregates only
"""
import json
import re
import statistics as S
import sys
from pathlib import Path

import valuation_backbone as vb
import run_rs2

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
MD = HERE / "Chatgpt Analysis for RS2 Local Refinement" / "rs2_actual_deep_research_md"
REP = HERE / "reports"


def _num(s):
    if s is None:
        return None
    s = re.sub(r"[,$%]", "", str(s)).strip()
    try:
        return float(s)
    except ValueError:
        return None


def family(s):
    s = (s or "").upper()
    if any(w in s for w in ("AVOID", "REDUCE", "SELL", "TRIM", "EXIT", "UNDERWEIGHT")):
        return "BEAR"
    if any(w in s for w in ("HOLD", "WAIT", "WATCHLIST", "MONITOR", "DO NOT CHASE", "PATIENT")):
        return "HOLD"
    if any(w in s for w in ("BUY", "ACCUMULAT", "SCALE", "ADD", "OVERWEIGHT", "STARTER", "INITIAT", "ENTER")):
        return "BULL"
    return "?"


def gpt_side(md):
    x = md.read_text(encoding="utf-8", errors="ignore")
    seg = x[x.rfind("SECTION 12"):] if "SECTION 12" in x else x

    def f(p, t=seg):
        m = re.search(p, t, re.I)
        return m.group(1).strip() if m else None
    action = (f(r"Final action[:\*\s]*([^\n\[]{2,70})") or f(r"Final opinion[:\*\s]*([^\n\[]{2,70})")
              or f(r"Final rating[:\*\s]*([^\n\[]{2,70})") or f(r"Final RS2 (?:opinion|rating)[:\*\s]*([^\n\[]{2,70})"))
    if not action:
        for ln in seg.splitlines()[1:]:
            ln = ln.strip(" *")
            if len(ln) > 8 and not ln.startswith("#") and "conviction" not in ln.lower():
                action = ln[:70]
                break
    conv = _num(f(r"Conviction[:\*\s]*([0-9.]+)\s*/\s*15"))
    fair = None
    for p in [r"Base intrinsic value[:\s]*\$?([0-9][0-9,]*\.?[0-9]*)",
              r"Base case[^$\n]{0,40}\$?([0-9][0-9,]*\.?[0-9]*)\s*/\s*share",
              r"Base[^$\n]{0,12}\$([0-9][0-9,]*\.?[0-9]*)\s*/\s*share",
              r"[Ee]xpected value[:\s]*\$?([0-9][0-9,]*\.?[0-9]*)\s*/\s*share"]:
        m = re.search(p, x)
        if m and _num(m.group(1)) and _num(m.group(1)) > 1:
            fair = _num(m.group(1))
            break
    gated = bool(re.search(r"do not chase|pullback|weakness|below \$|wait for|starter|not cheap|"
                           r"insufficient margin|patient", seg, re.I))
    return {"action": action, "conv": conv, "fair": fair, "gated": gated}


def old_verdict(t):
    for d in sorted(REP.glob(f"{t}_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        v = d / "verdict.json"
        if v.exists():
            try:
                return json.loads(v.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def projected(t, old):
    """Deterministic post-fix verdict: current fenced backbone + the don't-chase brake applied to the
    model's OWN raw action from the old verdict (raw_action if present, else the recorded action)."""
    b = vb.backbone(t)
    vr = {"price": b.get("price"), "consensus_median": b.get("consensus_median"),
          "consensus_low": b.get("consensus_low"),
          "realistic_mos_pct": b.get("realistic_mos_pct"), "mos_pct": b.get("mos_pct")}
    raw_a = old.get("raw_action") or old.get("action") or "BUY"
    raw_c = old.get("raw_conviction") or old.get("conviction")
    raw_w = old.get("recommended_weight_pct")
    a, c, w, et, tr, br = run_rs2._dont_chase_brake(raw_a, raw_c, raw_w, vr, t)
    return {"action": a, "conv": c, "mos": b.get("realistic_mos_pct"),
            "fair": b.get("fair_value"), "method": b.get("fair_value_method"),
            "entry": et, "trig": tr, "braked": br}


def main():
    brief = "--brief" in sys.argv
    names = [m.stem.split("_")[1] for m in sorted(MD.glob("*_RS2_actual_deep_research.md"))]
    md_by = {m.stem.split("_")[1]: m for m in MD.glob("*_RS2_actual_deep_research.md")}

    a_old = s_old = a_new = s_new = 0
    cdo = cno = 0.0; cd_n = 0
    blow_old = blow_new = 0
    conv_new_vals = []
    braked = 0
    if not brief:
        print(f"{'T':6}{'GPT':7}{'RS2old':7}{'RS2new':7} | {'oMoS':>7}{'nMoS':>7} "
              f"{'nConv':>6} {'entry':>16} | agree")
        print("-" * 92)
    for t in names:
        g = gpt_side(md_by[t])
        o = old_verdict(t)
        n = projected(t, o)
        gf, of, nf = family(g["action"]), family(o.get("action")), family(n["action"])
        if gf != "?" and of != "?":
            a_old += 1; s_old += (gf == of)
        if gf != "?" and nf != "?":
            a_new += 1; s_new += (gf == nf)
        if g["conv"] is not None and n["conv"] is not None:
            cd_n += 1; cno += abs(g["conv"] - n["conv"])
            if o.get("conviction") is not None:
                cdo += abs(g["conv"] - o["conviction"])
        if n["conv"] is not None:
            conv_new_vals.append(n["conv"])
        if o.get("mos_pct") is not None and abs(o["mos_pct"]) > 60:
            blow_old += 1
        if n["mos"] is not None and abs(n["mos"]) > 60:
            blow_new += 1
        if n["braked"]:
            braked += 1
        if not brief:
            mark = "OK" if (gf == nf and gf != "?") else ("~" if "?" in (gf, nf) else "DIFF")
            print(f"{t:6}{gf:7}{of:7}{nf:7} | {str(o.get('mos_pct')):>7}{str(n['mos']):>7} "
                  f"{str(n['conv']):>6} {str(n['entry']):>16} | {mark}")
    print()
    print(f"Action-family agreement vs ChatGPT:  OLD {s_old}/{a_old} = {100*s_old/a_old:.0f}%   "
          f"NEW {s_new}/{a_new} = {100*s_new/a_new:.0f}%")
    if cd_n:
        print(f"Mean |conviction Δ| vs ChatGPT:      OLD {cdo/cd_n:.2f}   NEW {cno/cd_n:.2f}  (n={cd_n})")
    if conv_new_vals:
        print(f"NEW conviction spread: min {min(conv_new_vals)} / median {S.median(conv_new_vals)} / "
              f"max {max(conv_new_vals)}  ({sum(c<=9.5 for c in conv_new_vals)} Medium≤9.5)")
    print(f"MoS blowups >60%:                    OLD {blow_old}   NEW {blow_new}")
    print(f"Don't-chase brake fired on:          {braked}/{len(names)} names")


if __name__ == "__main__":
    main()
