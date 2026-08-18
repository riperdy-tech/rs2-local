"""C7 — Stage consumption and runtime share.

Over post-CONTEXT_ERA report bundles (>= 20260813_160000) that produced a verdict:
  - per-stage runtime proxy from file mtime deltas (S1 timed from _fed_data.md)
  - per-stage output size
  - echo share: fraction of each stage's word-8-grams that reappear in FINAL.md
    (how much of the stage's text materially reaches the final document)

Mechanical consumers are static facts from code, recorded here for the report:
  S1 -> _archetype() -> routing.json (cyclicality basis disclosure)
  S3 -> STANCE/ENGINE JSON -> valuation_result()
  S4 -> scenario probs -> stored, CONSUMED BY NOTHING (grep-verified)
  S5 -> conviction /15 -> SECTION 12 parse
  S6 -> none (context only)
  S2 -> none (context only)
"""
import re
from pathlib import Path

import common

common.enable_json_cache()
import rs2_data  # noqa: E402

STAGES = ["S1_macro_classify.md", "S2_quality.md", "S3_valuation.md",
          "S4_scenarios.md", "S5_conviction.md", "S6_redteam_audit.md"]
ERA = "20260813_160000"


def ngrams(text, n=8):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def main():
    rep = Path(rs2_data.CONFIG["out_reports_dir"])
    dirs = sorted(d for d in rep.glob("*_*") if d.is_dir()
                  and d.name.rsplit("_", 2)[-2] + "_" + d.name.rsplit("_", 2)[-1] >= ERA
                  and (d / "verdict.json").exists() and (d / "FINAL.md").exists()
                  and all((d / s).exists() for s in STAGES))
    per_stage = {s: {"secs": [], "bytes": [], "echo": []} for s in STAGES}
    final_secs = []
    n_used = 0
    for d in dirs:
        try:
            fed = (d / "_fed_data.md")
            anchor = fed.stat().st_mtime if fed.exists() else None
            final_txt = (d / "FINAL.md").read_text(encoding="utf-8", errors="replace")
            final_grams = ngrams(final_txt)
            prev = anchor
            ok = True
            stage_rows = []
            for s in STAGES:
                st = (d / s).stat()
                txt = (d / s).read_text(encoding="utf-8", errors="replace")
                g = ngrams(txt)
                echo = (len(g & final_grams) / len(g)) if g else None
                secs = (st.st_mtime - prev) if prev is not None else None
                if secs is not None and (secs <= 0 or secs > 3600):
                    ok = False
                stage_rows.append((s, secs, st.st_size, echo))
                prev = st.st_mtime
            fmt = (d / "FINAL.md").stat().st_mtime
            fsecs = fmt - prev if prev else None
            if not ok:
                continue
            n_used += 1
            for s, secs, size, echo in stage_rows:
                if secs is not None:
                    per_stage[s]["secs"].append(secs)
                per_stage[s]["bytes"].append(size)
                if echo is not None:
                    per_stage[s]["echo"].append(round(echo, 3))
            if fsecs and 0 < fsecs < 3600:
                final_secs.append(fsecs)
        except Exception:
            continue

    def med(v):
        v = sorted(v)
        return round(v[len(v) // 2], 1) if v else None

    stage_summary = {}
    total_med = sum(med(per_stage[s]["secs"]) or 0 for s in STAGES) + (med(final_secs) or 0)
    for s in STAGES:
        m = med(per_stage[s]["secs"])
        stage_summary[s] = {
            "median_secs": m,
            "runtime_share_pct": round(100 * m / total_med, 1) if (m and total_med) else None,
            "median_bytes": med(per_stage[s]["bytes"]),
            "median_echo_to_final": med(per_stage[s]["echo"]),
        }
    common.save("c7_stage_trace", {
        "n_bundles_scanned": len(dirs), "n_bundles_clean_timing": n_used,
        "stages": stage_summary,
        "final_assembly_median_secs": med(final_secs),
        "mechanical_consumers": {
            "S1": "routing.json cyclicality disclosure (_archetype)",
            "S2": "none - context only",
            "S3": "stance/engine JSON -> valuation_result()",
            "S4": "scenario probs stored at run_rs2.py:2454 - read by nothing (grep-verified)",
            "S5": "conviction /15 parsed from SECTION 12",
            "S6": "none - context only",
        },
    })


if __name__ == "__main__":
    main()
