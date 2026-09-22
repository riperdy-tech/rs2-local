#!/usr/bin/env python3
"""valuation_matrix.py — deterministic re-validation of the INVERTED valuation (AUDIT.md).

Replaces the retired build_matrix.py (which parsed the old forward-DCF "Base IV / MoS" format,
and whose action column was garbled — AUDIT.md M5). For each validation name it prints:
  - the reverse-DCF BACKBONE (base_cf kind, implied vs demonstrated growth, expectations gap) —
    fully deterministic, no LLM, reproducible run-to-run;
  - the model STANCE / action from the latest report, if one exists;
  - the saved ChatGPT reference (MoS, action) for a sanity cross-check.

The headline signal is the GAP (expectations investing); it is NOT expected to equal ChatGPT's
forward MoS — the believability layer (LLM stance) bridges them. This tool's job is to prove the
backbone is sane/reproducible and to surface any anomaly, not to curve-fit to ChatGPT.

Usage: python valuation_matrix.py
"""
import json
import re
import sys
from pathlib import Path

import valuation_backbone as vb

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
GPT_DIR = HERE / "Chatgpt Reference data"
REP = HERE / "reports"
NAME2TICK = {"deere": "DE", "linde": "LIN", "nextera": "NEE", "costco": "COST"}
TICKERS = ("MSFT AMD META NFLX TSLA HD PG COST XOM FANG JPM V LLY MRNA CAT DE FCX LIN "
           "AMT O NEE CEG PLTR OKLO NVDA GOOG GEV").split()


def _num(s):
    if s is None:
        return None
    s = s.replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _first(pat, text):
    m = re.search(pat, text, re.I)
    return m.group(1).strip() if m else None


def gpt_ref():
    out = {}
    for p in GPT_DIR.glob("*.txt"):
        t = NAME2TICK.get(p.stem.lower(), p.stem.upper())
        txt = p.read_text(encoding="utf-8", errors="ignore")
        out[t] = {
            "mos": _num(_first(r"Margin of Safety[^\n|]*\|[^%\-+]*([\-+]?[0-9.]+)\s*%", txt)),
            "action": _first(r"Execution Opinion[^\n|]*\|\s*\*{0,2}([^\n|*]+)", txt),
        }
    return out


def latest_report(t):
    ds = sorted(REP.glob(f"{t}_*"), key=lambda p: p.stat().st_mtime)
    return ds[-1] if ds else None


def model_side(t):
    d = latest_report(t)
    if not d:
        return {}
    out = {"report": d.name}
    sij = d / "S3_valuation_inputs.json"
    if sij.exists():
        try:
            v = json.loads(sij.read_text(encoding="utf-8"))
            out["method"] = v.get("method")
            out["stance"] = v.get("stance")
            out["mos"] = v.get("mos_pct")
        except Exception:
            pass
    fnl = d / "FINAL.md"
    if fnl.exists():
        txt = fnl.read_text(encoding="utf-8", errors="ignore")
        seg = txt[txt.rfind("SECTION 12"):] if "SECTION 12" in txt else txt
        out["action"] = _first(r"Action[:\s*]*\*{0,2}([A-Za-z][A-Za-z /&]{2,40})", seg)
    return out


def main():
    gpt = gpt_ref()
    hdr = (f"{'T':5}{'base_cf_kind':>22}{'impl%':>7}{'demo%':>7}{'GAP':>6} | "
           f"{'model':>10}{'stance':>12} | {'GPT_MoS':>8}  GPT_action")
    print(hdr)
    print("-" * len(hdr))
    anomalies = []
    for t in TICKERS:
        b = vb.backbone(t)
        m = model_side(t)
        g = gpt.get(t, {})
        if b.get("ok") and b.get("method") == "financial_pb_roe":
            gap = b["expectations_gap_pts"]
            if not (-50 <= (gap if gap is not None else 0) <= 80):
                anomalies.append(f"{t}: ROE gap {gap} out of sane band")
            if b.get("justified_pb", 0) > 6:
                anomalies.append(f"{t}: justified P/B {b['justified_pb']} implausibly high (g near CoE?)")
            line = (f"{t:5}{'fin: ROE %.0f%%/impl %.0f%%'%(b['roe']*100,b['implied_roe']*100):>22}"
                    f"{b['current_pb']:>7.1f}{b['justified_pb']:>7.1f}{gap:>6.0f} | "
                    f"{str(m.get('method','-'))[:10]:>10}{str(m.get('stance','-'))[:12]:>12} | "
                    f"{(g.get('mos') if g.get('mos') is not None else float('nan')):>8.1f}  "
                    f"{str(g.get('action','-'))[:28]}")
        elif b.get("ok"):
            impl = b["implied_growth"] * 100
            demo = (b["hist_revenue_cagr_5y"] or 0) * 100
            gap = b["expectations_gap_pts"]
            kind = b["base_cf_kind"]
            if not (-50 <= (gap if gap is not None else 0) <= 80):
                anomalies.append(f"{t}: gap {gap} out of sane band")
            if b["implied_growth"] in (-0.5, 1.5):
                anomalies.append(f"{t}: implied growth hit solver bound ({b['implied_growth']})")
            line = (f"{t:5}{kind:>22}{impl:>7.1f}{demo:>7.1f}{gap:>6.0f} | "
                    f"{str(m.get('method','-'))[:10]:>10}{str(m.get('stance','-'))[:12]:>12} | "
                    f"{(g.get('mos') if g.get('mos') is not None else float('nan')):>8.1f}  "
                    f"{str(g.get('action','-'))[:28]}")
        else:
            line = (f"{t:5}{'NULL: '+str(b.get('reason','')):>22}{'':>7}{'':>7}{'':>6} | "
                    f"{str(m.get('method','-'))[:10]:>10}{str(m.get('mos','-'))[:12]:>12} | "
                    f"{(g.get('mos') if g.get('mos') is not None else float('nan')):>8.1f}  "
                    f"{str(g.get('action','-'))[:28]}")
        print(line)
    print()
    if anomalies:
        print("ANOMALIES:")
        for a in anomalies:
            print("  ! " + a)
    else:
        print("No backbone anomalies — all gaps in sane band, no solver-bound hits, nulls explicit.")


if __name__ == "__main__":
    main()
