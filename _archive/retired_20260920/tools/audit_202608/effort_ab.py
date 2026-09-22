#!/usr/bin/env python3
"""effort_ab.py — does reasoning effort 'medium' hold the quality that 'xhigh' bought?

WHY THIS EXISTS. Ollama's "high" resolves to the Qwen3.8 template's **xhigh**, which is the
model's MAXIMUM and its own default; "medium" is the neutral rung that injects no reasoning
instruction at all. The depth tier has only ever run xhigh. Public benchmarks do not settle it:
the one effort-ladder review found medium -> xhigh worth +0.43 on a 0-10 substance scale against
0.18 noise, while xhigh costs 3-10x latency and tokens - and none of that measured long-context
numerical reasoning over a 16K fact pack, which is our actual task.

The repo's own prior A/B (QWEN38_AB_REPORT) found high effort cost 3.5x wall-clock for zero
verdict-direction changes - but it ran the RETIRED caged pipeline, so it cannot be cited for the
depth tier. Hence this: same names, same pack, same harness, effort as the only variable.

GRADED ON THE CHECKS THAT ALREADY DISCRIMINATE (audit/H_model_verification_20260821.md), not on
prose quality:
  GOOG - does it catch the contaminated TTM quarter unprompted (net income 54.8% of revenue,
         +297.9% YoY NI vs +24.2% revenue) and refuse to capitalise it?
  PM   - does it heed the series-continuity warning and treat the FY2015->16 revenue step as a
         reporting-basis change rather than a business event?
Both are failures the caged pipeline made and the depth tier caught at xhigh. If medium keeps
them, effort is a cost knob. If medium drops either, it is not.

  python tools/audit_202608/effort_ab.py --run      # run the medium arm (GPU, ~35 min/name)
  python tools/audit_202608/effort_ab.py            # grade whatever arms exist
"""
import io
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
OUT = HERE / "ab_reports" / "capability_test"

# Each check: (label, regex, must_be_present). Applied to report + thinking together, because a
# catch reasoned but not written up is still evidence the effort level found it.
#
# EVERY literal space in these patterns is normalised to a whitespace class below. Reports
# hard-wrap at ~78 columns, so "not a business event" arrives with a newline inside it - the
# first version of this grader scored PM 2/3 for a phrase the report states verbatim. A grader
# blind to line wrapping would have reported the medium arm as WORSE for a formatting artifact.
CHECKS = {
    "GOOG": [
        ("catches contaminated TTM quarter",
         r"297\.9|non-?operating|one-?off|54\.8%|unusually high relative", True),
        ("refuses to capitalise it as the DCF base",
         r"not used as the primary DCF|not the primary.{0,30}base|exclud\w+ from the (?:DCF|base)"
         r"|normali[sz]\w+ (?:the )?(?:earnings|base)", True),
        ("flags the trailing P/E as misleading",
         r"P/E is therefore misleading|misleading|distorted by", True),
        ("uses working capital", r"working capital", True),
    ],
    "PM": [
        ("recognises the basis change",
         r"reporting-?basis change|basis change|excise", True),
        ("treats the step as an artifact, not a business event",
         r"not a business event|rather than a business event|presentation change|reclassif", True),
        ("builds the trend on the post-2016 basis",
         r"(?:from|since|post-?)\s*(?:FY)?\s*2016", True),
    ],
}


def arms(ticker):
    """{label: dir} for every capability_test run of this ticker, newest per label."""
    out = {}
    for d in sorted(OUT.glob(f"{ticker}_*"), key=lambda p: p.name):
        if not (d / "REPORT.md").exists():
            continue
        parts = d.name.split("_")
        label = "_".join(parts[3:]) if len(parts) > 3 else "unlabelled"
        out[label] = d
    return out


def _flex(pat):
    """Literal spaces become a whitespace class so a hard-wrapped phrase still matches."""
    return pat.replace(" ", r"\s+")


def grade(d, ticker):
    rep = (d / "REPORT.md").read_text(encoding="utf-8", errors="replace")
    th = (d / "_thinking.md")
    both = rep + "\n" + (th.read_text(encoding="utf-8", errors="replace") if th.exists() else "")
    res = []
    for label, pat, want in CHECKS[ticker]:
        hit = bool(re.search(_flex(pat), both, re.I))
        res.append((label, hit == want))
    return res, len(rep), len(both) - len(rep)


def main():
    if "--run" in sys.argv:
        for t in ("GOOG", "PM"):
            print(f"\n=== medium arm: {t} ===", flush=True)
            subprocess.run([sys.executable, str(HERE / "tools" / "audit_202608" / "capability_test.py"),
                            t, "--model", "rs2-analyst-deep", "--think", "medium",
                            "--ctx", "81920", "--label", "deep-medium"])
    print(f"\n{'TICKER':7s} {'ARM':16s} {'PASS':>6s}  {'REPORT':>8s} {'THINK':>9s}   checks")
    print("-" * 100)
    for t in ("GOOG", "PM"):
        for label, d in arms(t).items():
            res, rlen, tlen = grade(d, t)
            ok = sum(1 for _, p in res if p)
            fails = [lb for lb, p in res if not p]
            print(f"{t:7s} {label:16s} {ok}/{len(res):>4}  {rlen:8,} {tlen:9,}   "
                  + ("all pass" if not fails else "MISS: " + "; ".join(fails)))
    print("\nA miss on GOOG's contamination catch or PM's basis-change catch means effort is NOT "
          "a free cost knob — those are the failures the caged pipeline made.")


if __name__ == "__main__":
    main()
