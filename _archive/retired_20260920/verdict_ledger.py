#!/usr/bin/env python3
"""verdict_ledger.py — append-only point-in-time ledger of every RS2 verdict.

Closes the validation gap the 2026-08-09 audit found: the engine emits a dated verdict
for every analyzed name (reports/{T}_{ts}/verdict.json) but nothing ever graded those
predictions against subsequent prices. This script syncs every bundle's verdict into
one jsonl ledger that the screener's outcome machinery can grade
(scripts/grade_rs2_verdicts.py in the Stock Screener repo).

Honesty rules baked in:
- APPEND-ONLY, keyed by bundle name. A row, once written, is never rewritten or removed
  — if a bundle is later quarantined or repatched, the ledger still remembers what the
  system said at the time. No silent survivorship.
- The signal date comes from the BUNDLE DIRECTORY NAME ({T}_{YYYYMMDD}_{HHMMSS}), never
  from verdict.json's `date` field: repatch_verdicts.py replays emit_verdict in place,
  which stamps `date` with the repatch day (489 of 1,606 bundles measured 2026-08-09).
  Rows where the two disagree carry `repatched: true` — their action/brake fields are
  the corrected deterministic layer replayed over the original LLM text, not strictly
  point-in-time.
- `research_cited` applies the handoff's citation test (a `- https?://` source line in
  the bundle's research.md) so fabricated-research-era verdicts can be sliced out.
  Validated 2026-08-09: all 215 post-fix bundles (Aug 7-9) pass; POWL's clean re-research
  carries 43 source lines; the POWL fabrication carried zero.

Usage:
    python verdict_ledger.py          # sync new bundles into the ledger, print summary
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
REPORTS = Path(CONFIG["out_reports_dir"])
LEDGER = Path(CONFIG["screener_data_dir"]) / "rs2_verdict_log.jsonl"

DIRNAME_RE = re.compile(r"^([A-Za-z0-9.\-]+)_(\d{8})_(\d{6})$")
CITED_RE = re.compile(r"^- https?://", re.M)


def _action_family(s):
    """Mirror of run_rs2._action_family — keep in sync (not imported: run_rs2 pulls the
    whole pipeline's dependencies in at import time; the ledger must stay stdlib-only)."""
    s = (s or "").upper()
    if any(w in s for w in ("AVOID", "REDUCE", "SELL", "TRIM", "EXIT", "UNDERWEIGHT")):
        return "BEAR"
    if "HOLD" in s or "WAIT" in s or "WATCHLIST" in s or "MONITOR" in s or "DO NOT CHASE" in s:
        return "HOLD"
    if any(w in s for w in ("BUY", "ACCUMULAT", "SCALE", "ADD", "OVERWEIGHT", "STARTER", "INITIAT", "ENTER")):
        return "BULL"
    return "?"


def existing_keys():
    keys = set()
    if not LEDGER.exists():
        return keys
    with LEDGER.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                keys.add(json.loads(line).get("report"))
            except json.JSONDecodeError:
                continue
    return keys


def row_from_bundle(d):
    m = DIRNAME_RE.match(d.name)
    vpath = d / "verdict.json"
    if not m or not vpath.exists():
        return None
    try:
        v = json.loads(vpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ymd, hms = m.group(2), m.group(3)
    pit_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
    rpath = d / "research.md"
    if rpath.exists():
        try:
            research_cited = bool(CITED_RE.search(rpath.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            research_cited = None
    else:
        research_cited = None
    action = v.get("action")
    raw_action = v.get("raw_action")
    return {
        "report": d.name,
        "ticker": (v.get("ticker") or m.group(1)).upper(),
        "date": pit_date,
        "time": f"{hms[:2]}:{hms[2:4]}:{hms[4:]}",
        "action": action, "action_family": _action_family(action),
        "raw_action": raw_action, "raw_action_family": _action_family(raw_action),
        "conviction": v.get("conviction"), "conviction_scale": v.get("conviction_scale"),
        "recommended_weight_pct": v.get("recommended_weight_pct"),
        "entry_timing": v.get("entry_timing"), "pullback_trigger": v.get("pullback_trigger"),
        "brake_applied": v.get("brake_applied"),
        "stance_score": v.get("stance_score"), "thesis_break": v.get("thesis_break"),
        "exit_review": bool(v.get("exit_review")),
        "stance": v.get("stance"), "stance_model": v.get("stance_model"),
        "expectations_gap_pts": v.get("expectations_gap_pts"),
        "fair_value": v.get("fair_value"), "mos_pct": v.get("mos_pct"),
        "realistic_mos_pct": v.get("realistic_mos_pct"),
        "fair_value_method": v.get("fair_value_method"),
        "price": v.get("price"), "band_at_analysis": v.get("band_at_analysis"),
        "verdict_date_field": v.get("date"),
        "repatched": bool(v.get("date") and v["date"] != pit_date),
        "research_cited": research_cited,
        "logged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def sync():
    """Scan reports/ and append any bundle not yet in the ledger. Returns summary dict."""
    seen = existing_keys()
    new_rows = []
    scanned = 0
    for d in sorted(REPORTS.glob("*_*")):
        if not d.is_dir() or d.name in seen:
            continue
        scanned += 1
        row = row_from_bundle(d)
        if row:
            new_rows.append(row)
    new_rows.sort(key=lambda r: (r["date"], r["report"]))
    if new_rows:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in new_rows))
    return {"appended": len(new_rows), "already_ledgered": len(seen),
            "scanned_new_dirs": scanned, "ledger": str(LEDGER)}


def main():
    s = sync()
    total = s["appended"] + s["already_ledgered"]
    print(f"verdict ledger: +{s['appended']} appended ({s['already_ledgered']} already present, "
          f"{total} total) -> {s['ledger']}")
    if s["scanned_new_dirs"] > s["appended"]:
        print(f"  note: {s['scanned_new_dirs'] - s['appended']} new dir(s) skipped "
              f"(no parseable verdict.json — partial/failed runs)")


if __name__ == "__main__":
    main()
