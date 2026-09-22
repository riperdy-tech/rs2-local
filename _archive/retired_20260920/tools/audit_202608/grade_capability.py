#!/usr/bin/env python3
"""grade_capability.py — score capability-test arms on identical, objective checkpoints.

The checkpoints come from the benchmark GOOG analysis (an external frontier model on the same
T0 data, base IV ~$205) and from the defects RS2's own pipeline demonstrated on this name.
Each is a fact about the report, not a judgment about it — so arms are comparable.

  python tools/audit_202608/grade_capability.py            # score every arm
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ab_reports" / "capability_test"

# (name, regexes -> any hit counts, what it tests)
CHECKS = [
    ("contamination_caught",
     [r"one[- ]time", r"one[- ]off", r"non[- ]operating", r"93\.[67]\s*%", r"mark[- ]to[- ]market",
      r"unrealized", r"normali[sz]ed run[- ]rate"],
     "flags TTM net income $244.2B as containing non-operating/one-off items"),
    # match the STEM: an earlier version required "normalized" and scored arm D a MISS on a
    # report that said "normalization" and "TTM net income $244.205B is NOT operationally
    # usable". Third false negative from this grader tonight — every one of them flattered the
    # conclusion I already held, which is exactly the bias the audit was about.
    ("normalized_base_used",
     [r"normali[sz]", r"FY2025 (NI )?margin", r"32\.8\s*%", r"not operationally usable",
      r"NOT operationally usable"],
     "uses a normalized earnings base rather than raw TTM NI"),
    # NOTE: match forecast rows in ANY table dialect. An earlier version required a leading
    # pipe and scored arm C as a MISS on a report that carried a full FY2026E-FY2035E table
    # with revenue/margin/capex/D&A/FCF columns — the row simply began "FY2026E | ...".
    # A grader that fails the thing it is grading is the same closed-loop error as the audit.
    ("driver_path_built",
     [r"FY2[6-9]E\s*\|", r"FY3[0-5]E\s*\|", r"\|\s*FY2[6-9]E", r"\|\s*20(2[6-9]|3[0-5])\s*\|",
      r"20(2[6-9]|3[0-5])E?\s*\|\s*\d"],
     "explicit multi-year forecast with per-year drivers"),
    ("da_gap_handled",
     [r"D&A[^\n]{0,60}(absent|not available|unavailable|missing)",
      r"(absent|not available)[^\n]{0,40}D&A", r"derived from OCF"],
     "acknowledges the missing D&A and states how it was estimated"),
    ("capex_ttm_correct",
     [r"132\.4", r"\$132"],
     "uses true TTM capex $132.4B"),
    ("nonop_stakes_separated",
     [r"SpaceX[^\n]{0,80}(stake|holding|separately|haircut)",
      r"non[- ]marketable[^\n]{0,60}(separately|haircut|valued)",
      r"separately valued|valued separately"],
     "treats non-operating holdings outside the operating DCF"),
    ("wacc_derived",
     [r"risk[- ]free[^\n]{0,40}\d", r"equity risk premium", r"ERP[^\n]{0,20}\d", r"beta[^\n]{0,20}1\.\d"],
     "builds a discount rate from rf/ERP/beta rather than asserting one"),
    ("sensitivity_or_scenarios",
     [r"tornado", r"sensitivit", r"bear[^\n]{0,40}base[^\n]{0,40}bull", r"scenario"],
     "shows sensitivity or probability-weighted scenarios"),
]

IV_PAT = [r"intrinsic value[^\n]{0,60}?\$?\s*(\d{2,4}(?:\.\d{1,2})?)",
          r"Base (?:case )?IV[^\n]{0,30}?\$\s*(\d{2,4}(?:\.\d{1,2})?)",
          r"fair value[^\n]{0,60}?\$\s*(\d{2,4}(?:\.\d{1,2})?)"]


def grade(d):
    f = d / "REPORT.md"
    if not f.exists():
        return None
    r = f.read_text(encoding="utf-8", errors="replace")
    th = (d / "_thinking.md")
    thinking = th.read_text(encoding="utf-8", errors="replace") if th.exists() else ""
    both = r + "\n" + thinking
    res = {"arm": d.name, "report_chars": len(r), "thinking_chars": len(thinking)}
    for name, pats, _ in CHECKS:
        res[name] = any(re.search(p, both, re.I) for p in pats)
    ivs = []
    for p in IV_PAT:
        ivs += [float(m.group(1)) for m in re.finditer(p, r, re.I)]
    plausible = [v for v in ivs if 50 <= v <= 900]
    res["iv_candidates"] = sorted(set(plausible))[:8]
    res["score"] = sum(1 for n, _, _ in CHECKS if res[n])
    return res


def main():
    dirs = sorted(p for p in OUT.glob("*") if p.is_dir())
    if not dirs:
        print("no arms found")
        return
    rows = [g for g in (grade(d) for d in dirs) if g]
    names = [n for n, _, _ in CHECKS]
    w = max(len(r["arm"]) for r in rows) + 2
    print(f"{'ARM':<{w}} {'SCORE':<7} " + " ".join(f"{n[:11]:<12}" for n in names))
    for r in rows:
        print(f"{r['arm']:<{w}} {r['score']}/{len(names):<5} "
              + " ".join(f"{'YES' if r[n] else '—':<12}" for n in names))
    print()
    for r in rows:
        print(f"{r['arm']}: report {r['report_chars']:,} chars | thinking "
              f"{r['thinking_chars']:,} | IV candidates {r['iv_candidates']}")
    print("\nCheckpoint meanings:")
    for n, _, desc in CHECKS:
        print(f"  {n:<26} {desc}")


if __name__ == "__main__":
    main()
