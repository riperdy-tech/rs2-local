#!/usr/bin/env python3
"""run_lever2_ab_test.py — A/B benchmark testing Lever 2 (think: high vs medium) on GEV.

Both arms run with Levers 1 & 4 active:
- Lever 1: MAX_TOOL_CALLS = 25 with keyword deduplication
- Lever 4: Rule 6 Scratchpad isolation, anti-anchoring, and Table <-> JSON parity

Arm A: think = "high" (xhigh profile, adaptive 2-escalate)
Arm B: think = "medium" (neutral profile, adaptive 2-escalate)
"""

import io
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
OUT = HERE / "ab_reports" / "consensus"

def get_latest_run(ticker, min_ts):
    dirs = sorted([d for d in OUT.glob(f"{ticker}_*") if d.is_dir()], key=lambda x: x.name)
    candidates = [d for d in dirs if d.name >= f"{ticker}_{min_ts}"]
    if not candidates:
        return None, None
    latest = candidates[-1]
    cj = latest / "consensus.json"
    if cj.exists():
        try:
            return json.loads(cj.read_text(encoding="utf-8")), latest
        except Exception:
            return None, latest
    return None, latest

def audit_report_integrity(run_dir):
    """Audits Levers 1 & 4 in the generated report files."""
    flaws = []
    dedup_events = 0
    parity_ok = True
    
    # Check tool snapshot for deduplication
    for snap_file in run_dir.glob("*_research/_research_snapshot.json"):
        try:
            data = json.loads(snap_file.read_text(encoding="utf-8"))
            for entry in data:
                if entry.get("dedup"):
                    dedup_events += 1
        except Exception:
            pass

    # Check reports for scratchpad leaks and Table <-> JSON parity
    for md_file in [f for f in run_dir.glob("sample*.md") if not f.name.endswith("_thinking.md")]:
        content = md_file.read_text(encoding="utf-8", errors="replace")
        # Check for scratchpad leak phrases
        leak_matches = re.findall(r"(?:wait[ —-]+this is lower|let me recheck|this is still too low|let me recalibrate)", content, re.I)
        if leak_matches:
            flaws.append(f"Scratchpad leak detected in {md_file.name}: {leak_matches}")
        
        # Check Table vs JSON parity
        jm = re.search(r"```json:underwriting\s*(\{.*?\})\s*```", content, re.DOTALL)
        if jm:
            try:
                card = json.loads(jm.group(1))
                json_base = card.get("base_iv")
                json_bear = card.get("bear_iv")
                # Find Section 4 table lines
                tbl_m = re.search(r"\|\s*\*\*Base\*\*\s*\|.*?\|\s*\$?([\d,]+(?:\.\d+)?)\s*\|", content, re.I)
                if tbl_m:
                    tbl_base = float(tbl_m.group(1).replace(",", ""))
                    if abs(tbl_base - json_base) > 0.01:
                        parity_ok = False
                        flaws.append(f"Base IV mismatch in {md_file.name}: Table ${tbl_base} vs JSON ${json_base}")
            except Exception:
                pass

    return {
        "dedup_events": dedup_events,
        "scratchpad_clean": len(flaws) == 0,
        "parity_ok": parity_ok,
        "flaws": flaws
    }

def update_summary(results):
    lines = [
        "# Lever 2 A/B Benchmark: Reasoning Effort on GEV (high vs. medium)",
        f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*",
        "",
        "| Arm | Think Setting | Samples Run | Converged? | Spread % | Median Base IV | Bull IV | Bear IV | MoS % | Avg Secs/Sample | Total Mins | Dedup Hits | Leaks Clean? | Parity? |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        b_iv = f"${r['base_iv']:,.2f}" if r.get("base_iv") else "N/A"
        bu_iv = f"${r['bull_iv']:,.2f}" if r.get("bull_iv") else "N/A"
        br_iv = f"${r['bear_iv']:,.2f}" if r.get("bear_iv") else "N/A"
        mos = f"{r['mos']:+.1f}%" if r.get("mos") is not None else "N/A"
        sp = f"{r['spread']:.1f}%" if isinstance(r.get("spread"), (int, float)) else str(r.get("spread", "N/A"))
        lines.append(
            f"| **{r['arm']}** | `{r['think']}` | {r['samples']} | {r['converged']} | "
            f"{sp} | {b_iv} | {bu_iv} | {br_iv} | "
            f"{mos} | {r.get('secs_per_sample', 0)}s | {r['total_mins']:.1f}m | "
            f"{r['dedup_hits']} | {'YES' if r['clean'] else 'NO'} | {'YES' if r['parity'] else 'NO'} |"
        )
    lines.append("")
    lines.append("## Observations & Decision Analysis")
    for r in results:
        lines.append(f"### {r['arm']} (`think: {r['think']}`)")
        lines.append(f"- **Directory**: `{r.get('dir')}`")
        lines.append(f"- **Verdict**: {r.get('verdict')}")
        if r.get("flaws"):
            lines.append(f"- **Integrity Flaws**: {', '.join(r['flaws'])}")
        lines.append("")

    (OUT / "LEVER2_AB_GEV_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")

def run_arm(arm_name, think_level):
    print(f"\n================================================================================", flush=True)
    print(f"STARTING {arm_name}: think = '{think_level}' (adaptive 2-escalate)", flush=True)
    print(f"================================================================================\n", flush=True)

    t_start = datetime.now().strftime("%Y%m%d_%H%M%S")
    t0 = time.time()

    cmd = [
        sys.executable,
        str(HERE / "tools" / "audit_202608" / "consensus_valuation.py"),
        "GEV",
        "--tools",
        "--think", think_level,
        "--model", "rs2-analyst-deep-mtp5"
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        sys.stdout.write(f"  [{think_level}] {line}")
        sys.stdout.flush()
    proc.wait()

    duration = time.time() - t0
    doc, run_dir = get_latest_run("GEV", t_start)
    
    if not doc:
        return {
            "arm": arm_name, "think": think_level, "samples": 0, "converged": False,
            "spread": "N/A", "base_iv": 0, "bull_iv": 0, "bear_iv": 0, "mos": 0,
            "secs_per_sample": 0, "total_mins": duration / 60, "dedup_hits": 0,
            "clean": False, "parity": False, "verdict": "FAILED", "dir": str(run_dir), "flaws": ["No consensus doc"]
        }

    audit = audit_report_integrity(run_dir)
    card = doc.get("scorecard") or {}
    runs = doc.get("runs") or []
    n_samples = len(runs)
    avg_secs = round(sum(r.get("secs", 0) for r in runs) / max(1, n_samples))

    return {
        "arm": arm_name,
        "think": think_level,
        "samples": n_samples,
        "converged": doc.get("converged", False),
        "spread": doc.get("spread_pct", "N/A"),
        "base_iv": doc.get("median_iv", 0),
        "bull_iv": card.get("iv_band_high", 0),
        "bear_iv": card.get("iv_band_low", 0),
        "mos": doc.get("median_mos_pct", 0),
        "secs_per_sample": avg_secs,
        "total_mins": duration / 60,
        "dedup_hits": audit["dedup_events"],
        "clean": audit["scratchpad_clean"],
        "parity": audit["parity_ok"],
        "verdict": doc.get("verdict"),
        "dir": str(run_dir),
        "flaws": audit["flaws"]
    }

def main():
    results = []
    
    # Arm A: think = "high"
    res_a = run_arm("Arm A (Baseline)", "high")
    results.append(res_a)
    update_summary(results)

    # Arm B: think = "medium"
    res_b = run_arm("Arm B (Candidate)", "medium")
    results.append(res_b)
    update_summary(results)

    print("\n================================================================================", flush=True)
    print("LEVER 2 A/B BENCHMARK COMPLETE. See ab_reports/consensus/LEVER2_AB_GEV_SUMMARY.md", flush=True)
    print("================================================================================\n", flush=True)

if __name__ == "__main__":
    main()
