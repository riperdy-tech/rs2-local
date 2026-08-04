#!/usr/bin/env python3
"""
compare_runs.py — extract the key verdict fields from RS2 FINAL.md reports so a
local run can be diffed against a ChatGPT baseline (validation Stage 5).

Pulls: archetype/engine, dominant regime, T0 price, intrinsic value, margin of
safety, conviction, action, top risk/catalyst — from the consolidated FINAL.md.
Heuristic regex extraction (the report is semi-structured text), tolerant of gaps.

CLI:
  python compare_runs.py reports/NVDA_*/FINAL.md
  python compare_runs.py reports/*/FINAL.md          # table of latest runs
"""
import glob
import re
import sys
from pathlib import Path

FIELDS = [
    ("archetype",  r"Archetype[:\s]*\*{0,2}\s*([A-F])\b(?:\s*\(([^)]+)\))?"),
    ("engine",     r"(?:Valuation Engine|Engine)[:\s]*\*{0,2}\s*((?:Blended\s+)?Engine\s*[0-9][^\n.|\[]*)"),
    ("regime",     r"(Goldilocks|Reflation|Stagflation|Recession)\b[^\n]*?(\d{1,3})%"),
    ("t0_price",   r"T0[^\n$]*\$([0-9][0-9,]*\.?[0-9]*)"),
    ("intrinsic",  r"(?:Intrinsic Value|IV)[^\n$]*\$([0-9][0-9,]*\.?[0-9]*)"),
    ("mos",        r"(?:Margin of Safety|MoS)[^\n%]*?([+-]?[0-9.]+)\s*%|([+-]?[0-9.]+)\s*%\s*MoS"),
    ("conviction", r"Conviction[:\s]*\*{0,2}\s*([^\n\[]+)"),
    ("action",     r"Action[:\s]*\*{0,2}\s*([A-Za-z][A-Za-z /&]+)"),
    ("top_risk",   r"(?:top[_ ]risk|Top Risk)[:\s]*\*{0,2}\s*([^\n\[]+)"),
    ("catalyst",   r"(?:top[_ ]catalyst|Top Catalyst|Catalyst)[:\s]*\*{0,2}\s*([^\n\[]+)"),
]


# For these, the authoritative value is in SECTION 12 (near the end) — take the last hit.
LAST_MATCH = {"action", "conviction"}


def extract(path):
    txt = Path(path).read_text(encoding="utf-8", errors="ignore")
    # Bias action/conviction to the final verdict block.
    tail = txt[txt.rfind("SECTION 12"):] if "SECTION 12" in txt else txt
    out = {}
    for name, pat in FIELDS:
        src = tail if name in LAST_MATCH else txt
        m = re.search(pat, src, re.IGNORECASE)
        if not m:
            out[name] = "—"
        elif name == "archetype":
            letter = m.group(1)
            paren = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            out[name] = f"{letter} ({paren})" if paren else letter
        elif name == "mos":
            g = next((x for x in m.groups() if x), None)
            out[name] = (g + "%") if g else "—"
        elif name == "regime":
            # dominant = highest-% of the four
            cands = re.findall(r"(Goldilocks|Reflation|Stagflation|Recession)\b[^\n]*?(\d{1,3})%", txt)
            if cands:
                top = max(cands, key=lambda c: int(c[1]))
                out[name] = f"{top[0]} {top[1]}%"
            else:
                out[name] = m.group(1)
        else:
            out[name] = m.group(1).strip()[:60]
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    paths = []
    for a in sys.argv[1:]:
        paths.extend(sorted(glob.glob(a)))
    if not paths:
        print("usage: python compare_runs.py reports/*/FINAL.md", file=sys.stderr)
        sys.exit(1)
    for p in paths:
        d = extract(p)
        tick = Path(p).parent.name
        print(f"\n=== {tick} ===")
        for k, _ in FIELDS:
            print(f"  {k:11}: {d[k]}")
