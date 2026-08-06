#!/usr/bin/env python3
"""research_health.py — aggregate health check for the research leg. Stdlib only.

WHY THIS EXISTS
The per-ticker guards in deep_research.py fail LOUDLY but INDIVIDUALLY: a ticker whose
search leg dies aborts and retries on its own. Nothing aggregates. That is how a 100%
SearXNG zero-source rate ran for weeks unnoticed — the signal was in
reports/_orchestrate.log 2,710 times and no one was summing it.

This is the seatbelt for a long run: it answers "is the search leg actually working
RIGHT NOW, across tickers" in one call, and alerts once instead of per-ticker.

  python research_health.py                 # report on the whole log + brief corpus
  python research_health.py --since-hours 6 # just this run
  python research_health.py --alert         # Telegram if a threshold is breached
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import ops

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

# A healthy engine returns sources on nearly every subquery. Tavily historically sat at
# 9% zero-source (thin results are legitimate); SearXNG sat at 100% while broken. 25%
# separates "the web had little to say" from "this engine is not returning sources".
ZERO_SOURCE_ALERT_PCT = 25
CITED = re.compile(r"^- https?://", re.M)
DONE = re.compile(r"\[deep_research\] (\w+) '(.+?)' done via (\w+) in \d+s "
                  r"\((\d+) chars, (\d+) sources\)")
STAMP = re.compile(r"^\[orch (\d{2}):(\d{2}):(\d{2})\]")


def scan_log(path, since_hours=None):
    """Zero-source rate per engine from the orchestrate log."""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {}, f"log unreadable: {e}"
    if since_hours:
        # the log has no dates, only [orch HH:MM:SS] — take the tail slice by line count
        # rather than pretend to parse a timestamp we cannot anchor to a day.
        lines = txt.splitlines()
        txt = "\n".join(lines[-4000:])
    by = {}
    for _t, _topic, eng, chars, srcs in DONE.findall(txt):
        d = by.setdefault(eng, {"n": 0, "zero": 0, "chars_when_zero": []})
        d["n"] += 1
        if srcs == "0":
            d["zero"] += 1
            d["chars_when_zero"].append(int(chars))
    return by, None


def scan_briefs(d):
    """Uncited briefs currently on disk (these are re-researched, but a rising count
    means the search leg is failing right now)."""
    out = {"total": 0, "uncited": 0, "uncited_recent": 0}
    now = time.time()
    for f in Path(d).glob("*.md"):
        out["total"] += 1
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if not CITED.search(t):
            out["uncited"] += 1
            if (now - f.stat().st_mtime) < 86400:
                out["uncited_recent"] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-hours", type=float, default=None)
    ap.add_argument("--alert", action="store_true", help="Telegram on threshold breach")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    log = Path(CONFIG["out_reports_dir"]) / "_orchestrate.log"
    by, err = scan_log(log, a.since_hours)
    briefs = scan_briefs(CONFIG["out_research_dir"])

    problems = []
    lines = ["RESEARCH HEALTH", f"  log: {log.name}" + (f" (tail slice)" if a.since_hours else "")]
    if err:
        problems.append(err)
        lines.append(f"  !! {err}")
    for eng, d in sorted(by.items()):
        pct = round(100 * d["zero"] / d["n"]) if d["n"] else 0
        flag = ""
        if d["n"] >= 8 and pct >= ZERO_SOURCE_ALERT_PCT:
            flag = "   <== ALERT"
            problems.append(f"{eng}: {pct}% of {d['n']} subqueries returned ZERO sources")
        lines.append(f"  {eng:8s} subqueries={d['n']:5d}  zero-source={d['zero']:5d} ({pct:3d}%){flag}")
    if not by:
        lines.append("  (no completed subqueries found in log)")

    lines.append(f"  briefs on disk: {briefs['total']}  uncited={briefs['uncited']}"
                 f"  uncited in last 24h={briefs['uncited_recent']}")
    if briefs["uncited_recent"] >= 5:
        problems.append(f"{briefs['uncited_recent']} briefs written in the last 24h are uncited")

    if not a.quiet:
        print("\n".join(lines))

    if problems:
        msg = "[RS2 ops] research_health: " + "; ".join(problems[:4])
        if not a.quiet:
            print(f"\nPROBLEMS ({len(problems)}):")
            for p in problems:
                print(f"  - {p}")
        if a.alert:
            ops.notify_telegram(msg)
            print("[alert] Telegram sent")
        return 1
    if not a.quiet:
        print("\nOK — search leg is returning sources.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
