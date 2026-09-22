#!/usr/bin/env python3
"""run_battery_6.py — Benchmark battery across 6 diverse corporate finance archetypes.

Runs 1 deep institutional underwriting sample with up to 50 tool calls for:
1. GEV  - Industrials / Installed Base Capital Equipment
2. GOOG - Communication Services / Tech Platform Compounder
3. CAT  - Industrials / Cyclical Heavy Equipment
4. NVDA - Technology / Bottleneck Semiconductor Monopoly
5. V    - Financial Services / Tollbooth Payment Rail
6. XOM  - Energy / Upstream Commodity Cyclical
"""

import io
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
OUT = HERE / "ab_reports" / "consensus"
TICKERS = ["GEV", "GOOG", "CAT", "NVDA", "V", "XOM"]

def get_latest_run(ticker):
    dirs = sorted([d for d in OUT.glob(f"{ticker}_*") if d.is_dir()], key=lambda x: x.name)
    if not dirs:
        return None
    latest = dirs[-1]
    cj = latest / "consensus.json"
    if cj.exists():
        try:
            return json.loads(cj.read_text(encoding="utf-8")), latest
        except Exception:
            return None, latest
    return None, latest

def update_summary_md(results):
    lines = [
        "# Institutional Underwriting Ledger: 6-Ticker Benchmark Battery",
        f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*",
        "",
        "| # | Ticker | Price T0 | Base IV | Bull IV | Bear IV | MoS % | Moat (1-5) | Conviction (/15) | Kelly % | Payoff Skew | Runtime (min) | Status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for idx, r in enumerate(results, 1):
        t = r["ticker"]
        px = f"${r['price']:,.2f}" if r.get("price") else "N/A"
        b_iv = f"${r['base_iv']:,.2f}" if r.get("base_iv") else "N/A"
        bu_iv = f"${r['bull_iv']:,.2f}" if r.get("bull_iv") else "N/A"
        br_iv = f"${r['bear_iv']:,.2f}" if r.get("bear_iv") else "N/A"
        mos = f"{r['mos_pct']:+.1f}%" if r.get("mos_pct") is not None else "N/A"
        moat = f"{r['moat']:.1f}" if r.get("moat") is not None else "N/A"
        conv = f"{r['conviction']:.1f}" if r.get("conviction") is not None else "N/A"
        kelly = f"{r['kelly']:.1f}%" if r.get("kelly") is not None else "N/A"
        skew = f"{r['skew']:.2f}" if r.get("skew") is not None else "N/A"
        mins = f"{r['duration_secs']/60:.1f}" if r.get("duration_secs") else "N/A"
        status = r["status"]
        lines.append(f"| {idx} | **{t}** | {px} | {b_iv} | {bu_iv} | {br_iv} | {mos} | {moat} | {conv} | {kelly} | {skew} | {mins} | {status} |")
    
    lines.append("")
    lines.append("## Detailed Run Logs & Artifacts")
    for r in results:
        t = r["ticker"]
        d_path = r.get("run_dir", "")
        lines.append(f"### {t} - Underwriting Snapshot")
        lines.append(f"- **Directory**: `{d_path}`")
        if r.get("invalidation_trigger"):
            lines.append(f"- **Thesis Invalidation Trigger**: {r['invalidation_trigger']}")
        if r.get("starter_tranche") or r.get("core_tranche"):
            lines.append(f"- **Re-entry Tranches**: Starter $\\le ${r.get('starter_tranche')}, Core $\\le ${r.get('core_tranche')}")
        lines.append("")

    (OUT / "BATTERY_6_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")

def main():
    print(f"================================================================================")
    print(f"Starting 6-Ticker Underwriting Benchmark Battery")
    print(f"Tickers: {', '.join(TICKERS)}")
    print(f"Max Tools: 50 | Model: rs2-analyst-deep-mtp5 | Think: high")
    print(f"================================================================================\n", flush=True)

    results = []

    for t in TICKERS:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] >>> RUNNING BENCHMARK: {t} <<<", flush=True)
        t0 = time.time()
        cmd = [
            sys.executable,
            str(HERE / "tools" / "audit_202608" / "consensus_valuation.py"),
            t,
            "--samples", "1",
            "--tools",
            "--model", "rs2-analyst-deep-mtp5"
        ]
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            sys.stdout.write(f"  [{t}] {line}")
            sys.stdout.flush()
        proc.wait()
        
        duration = time.time() - t0
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Finished {t} in {duration/60:.1f} minutes (exit code {proc.returncode})", flush=True)
        
        doc, run_dir = get_latest_run(t)
        if doc:
            card = doc.get("scorecard") or {}
            runs = doc.get("runs") or [{}]
            run0 = runs[0] if runs else {}
            sc = run0.get("scorecard") or {}
            
            res = {
                "ticker": t,
                "price": doc.get("price"),
                "base_iv": doc.get("median_iv"),
                "bull_iv": sc.get("bull_iv"),
                "bear_iv": sc.get("bear_iv"),
                "mos_pct": doc.get("median_mos_pct"),
                "moat": sc.get("business_quality_moat"),
                "conviction": sc.get("conviction_score"),
                "kelly": sc.get("kelly_fraction_pct"),
                "skew": sc.get("asymmetric_payoff_skew"),
                "duration_secs": round(duration),
                "status": "COMPLETED" if proc.returncode == 0 else "ERROR",
                "run_dir": str(run_dir),
                "invalidation_trigger": sc.get("thesis_invalidation_trigger"),
                "starter_tranche": (sc.get("reentry_tranches") or {}).get("tranche_1_starter"),
                "core_tranche": (sc.get("reentry_tranches") or {}).get("tranche_2_core")
            }
        else:
            res = {
                "ticker": t,
                "status": "FAILED",
                "duration_secs": round(duration),
                "run_dir": str(run_dir)
            }
        results.append(res)
        update_summary_md(results)
        print(f"Updated BATTERY_6_SUMMARY.md with {len(results)}/6 tickers.", flush=True)

    print("\n================================================================================")
    print("ALL 6 BENCHMARKS COMPLETE. See ab_reports/consensus/BATTERY_6_SUMMARY.md")
    print("================================================================================", flush=True)

if __name__ == "__main__":
    main()
