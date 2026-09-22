#!/usr/bin/env python3
"""signoff.py — thorough inverted-pipeline sign-off vs ChatGPT.
For each ChatGPT-reference name: backbone gap + model stance/action/conviction (from the latest
inverted FINAL.md) vs ChatGPT action/MoS/conviction. Coarse action-family agreement + conviction
delta, for a human verdict (NOT an auto-pass)."""
import json, re, sys
from pathlib import Path
import valuation_backbone as vb

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
GPT_DIR = HERE / "Chatgpt Reference data"
REP = HERE / "reports"
NAME2TICK = {"deere": "DE", "linde": "LIN", "nextera": "NEE", "costco": "COST"}
SET = ("MSFT AMD META NFLX TSLA HD PG COST XOM FANG JPM V LLY MRNA CAT DE FCX LIN "
       "AMT O NEE CEG PLTR OKLO").split()


def first(pat, text):
    m = re.search(pat, text, re.I)
    return m.group(1).strip() if m else None


def num(s):
    if s is None:
        return None
    s = re.sub(r"[,$%]", "", s).strip()
    try:
        return float(s)
    except ValueError:
        return None


def family(s):
    s = (s or "").upper()
    if any(w in s for w in ("AVOID", "REDUCE", "SELL", "TRIM", "EXIT")):
        return "BEAR"
    if "HOLD" in s or "WAIT" in s or "MONITOR" in s:
        return "HOLD"
    if any(w in s for w in ("BUY", "ACCUMULAT", "SCALE", "ADD", "OVERWEIGHT")):
        return "BULL"
    return "?"


def gpt_side(t):
    p = next((q for q in GPT_DIR.glob("*.txt")
              if NAME2TICK.get(q.stem.lower(), q.stem.upper()) == t), None)
    if not p:
        return {}
    x = p.read_text(encoding="utf-8", errors="ignore")
    return {"mos": num(first(r"Margin of Safety[^\n|]*\|[^%\-+]*([\-+]?[0-9.]+)\s*%", x)),
            "action": first(r"Execution Opinion[^\n|]*\|\s*\*{0,2}([^\n|*]+)", x),
            "conv": num(first(r"Conviction[^\n|]*\|[^0-9]*([0-9.]+)\s*(?:of|/)\s*15", x))}


def model_side(t):
    ds = sorted(REP.glob(f"{t}_*"), key=lambda p: p.stat().st_mtime)
    if not ds:
        return {}
    d = ds[-1]
    o = {}
    sij = d / "S3_valuation_inputs.json"
    if sij.exists():
        v = json.loads(sij.read_text(encoding="utf-8"))
        o["stance"] = v.get("stance") or v.get("method")
    f = d / "FINAL.md"
    if f.exists():
        x = f.read_text(encoding="utf-8", errors="ignore")
        seg = x[x.rfind("SECTION 12"):] if "SECTION 12" in x else x
        o["action"] = first(r"Action[:\s*]*\*{0,2}([A-Za-z][A-Za-z /&\-]{2,45})", seg)
        o["conv"] = num(first(r"Conviction[^\n0-9]*([0-9.]+)\s*/\s*15", seg))
    return o


def main():
    print(f"{'T':5}{'GAP':>5} {'mStance':>11} {'model_action':>22} {'mCv':>4} | "
          f"{'gpt_action':>22} {'gCv':>4} {'gMoS':>6} | fam")
    print("-" * 100)
    agree = same = nconv = convsum = 0
    for t in SET:
        b = vb.backbone(t)
        gap = b.get("expectations_gap_pts") if b.get("ok") else "null"
        m = model_side(t)
        g = gpt_side(t)
        mf, gf = family(m.get("action")), family(g.get("action"))
        fam_mark = "OK" if mf == gf and mf != "?" else ("~" if "?" in (mf, gf) else "DIFF")
        if mf != "?" and gf != "?":
            agree += 1
            if mf == gf:
                same += 1
        if m.get("conv") is not None and g.get("conv") is not None:
            nconv += 1
            convsum += abs(m["conv"] - g["conv"])
        print(f"{t:5}{str(gap):>5} {str(m.get('stance','-'))[:11]:>11} "
              f"{str(m.get('action','-'))[:22]:>22} {str(m.get('conv','-')):>4} | "
              f"{str(g.get('action','-'))[:22]:>22} {str(g.get('conv','-')):>4} "
              f"{str(g.get('mos','-')):>6} | {mf}/{gf} {fam_mark}")
    print()
    print(f"Action-family agreement: {same}/{agree} where both parsed "
          f"({100*same/agree:.0f}%)" if agree else "no parse")
    if nconv:
        print(f"Mean |conviction delta|: {convsum/nconv:.1f}/15 over {nconv} names")


if __name__ == "__main__":
    main()
