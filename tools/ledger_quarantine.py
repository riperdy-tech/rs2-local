#!/usr/bin/env python3
"""tools/ledger_quarantine.py — one-shot: move the seven test rows out of the production ledger.

Phase 1 (stocks-workspace/docs/review_2026-09-22/PHASE_1_INTEGRITY_HYGIENE.md), item P1.1.

cache/depth_ledger.jsonl carries seven rows that are not production verdicts: six single-sample
`mode: fixed_1` manual runs (`depth_pipeline.py --samples 1`, 2026-09-18: CAT, GEV, GOOG, NVDA, V,
XOM) and one manual `--tickers AMD` orchestrator run (2026-09-21) that predates the Charter v3.1
gates. This script backs up the ledger and depth_state.json, moves those seven rows to
cache/depth_test_ledger.jsonl with a quarantine stamp, drops the same tickers from
depth_state.json, and records two events in cache/depth_ledger_events.jsonl: the quarantine
itself, and a back-dated record of the 2026-09-18 Charter v3.1 reset that the events log never
captured at the time.

Run once, from the repo root:  python tools/ledger_quarantine.py
Does NOT publish. `rebuild_overlay()` is called and its count printed so the operator can see the
resulting LOCAL overlay size before deciding to publish it (a later phase item).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # repo root (this file lives in tools/)
CACHE = HERE / "cache"
LEDGER = CACHE / "depth_ledger.jsonl"
STATE = CACHE / "depth_state.json"
TEST_LEDGER = CACHE / "depth_test_ledger.jsonl"
EVENTS = CACHE / "depth_ledger_events.jsonl"

# The back-dated reset event's payload is historical provenance, not something this tool opens as
# a file - so it lives in data, not in code (tools/audit_202608/tests/test_archive_reference_census
# would otherwise read its archived-path literal as a live reference to an archived artifact).
EVENTS_DATA = Path(__file__).resolve().parent / "ledger_quarantine_events.json"

# (ticker, date) of every row being quarantined — the six n=1 manual runs and the manual AMD run.
QUARANTINE_KEYS = {
    ("CAT", "2026-09-18"), ("GEV", "2026-09-18"), ("GOOG", "2026-09-18"),
    ("NVDA", "2026-09-18"), ("V", "2026-09-18"), ("XOM", "2026-09-18"),
    ("AMD", "2026-09-21"),
}
QUARANTINE_REASON = ("manual/test runs (n=1 09-17 set; --tickers AMD 09-21), "
                      "operator ruling 2026-09-22")


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _backup(path: Path, ts_for_name: str) -> Path:
    """Copy `path` to a sibling `.bak_before_quarantine_<ts>` file and verify it reads back
    identically before returning. Raises if the backup cannot be verified."""
    backup_path = path.with_name(f"{path.name}.bak_before_quarantine_{ts_for_name}")
    original = path.read_bytes()
    backup_path.write_bytes(original)
    if backup_path.read_bytes() != original:
        raise IOError(f"backup verification failed: {backup_path} does not match {path}")
    return backup_path


def main() -> int:
    if not LEDGER.exists():
        print(f"error: {LEDGER} does not exist", file=sys.stderr)
        return 1
    if not STATE.exists():
        print(f"error: {STATE} does not exist", file=sys.stderr)
        return 1

    ts = _utc_ts()
    ts_for_name = ts.replace(":", "").replace("-", "")

    # 1. Back up ledger AND state before touching either, and prove the backups are readable.
    ledger_backup = _backup(LEDGER, ts_for_name)
    state_backup = _backup(STATE, ts_for_name)
    json.loads(state_backup.read_text(encoding="utf-8-sig"))  # readable JSON
    backed_up_lines = [ln for ln in ledger_backup.read_text(encoding="utf-8").splitlines()
                        if ln.strip()]
    for ln in backed_up_lines:
        json.loads(ln)  # readable JSONL, every line
    print(f"backup: {ledger_backup} ({len(backed_up_lines)} lines, verified readable)")
    print(f"backup: {state_backup} (verified readable)")

    # 2. Split the ledger: quarantined rows out, everything else stays.
    lines = [ln for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    kept_lines = []
    quarantined_rows = []
    for ln in lines:
        row = json.loads(ln)
        key = (row.get("ticker"), row.get("date"))
        if key in QUARANTINE_KEYS:
            quarantined_rows.append(row)
        else:
            kept_lines.append(ln)

    found_keys = {(r.get("ticker"), r.get("date")) for r in quarantined_rows}
    missing = QUARANTINE_KEYS - found_keys
    if missing:
        print(f"error: expected quarantine rows not found in ledger: {sorted(missing)}",
              file=sys.stderr)
        return 1

    before_count = len(lines)
    after_count = len(kept_lines)
    print(f"ledger rows before: {before_count}")
    print(f"ledger rows after:  {after_count}")
    print(f"quarantined ({len(quarantined_rows)}):")
    for r in quarantined_rows:
        print(f"  {r.get('ticker')} {r.get('date')} mode={r.get('mode')}")

    # 3. Append the quarantined rows (stamped) to the test ledger.
    with TEST_LEDGER.open("a", encoding="utf-8") as f:
        for row in quarantined_rows:
            stamped = dict(row)
            stamped["quarantined_at"] = ts
            stamped["quarantine_reason"] = QUARANTINE_REASON
            f.write(json.dumps(stamped) + "\n")

    # 4. Rewrite the production ledger without the quarantined rows.
    LEDGER.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")

    # 5. Remove the quarantined tickers from depth_state.json.
    state = json.loads(STATE.read_text(encoding="utf-8-sig"))
    removed_tickers = sorted({t for (t, _d) in QUARANTINE_KEYS if t in state})
    for t, _d in QUARANTINE_KEYS:
        state.pop(t, None)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(STATE)
    print(f"depth_state.json: removed {removed_tickers}")

    # 6. Record the two ledger events.
    quarantine_event = {
        "ts": ts,
        "action": "quarantine",
        "rows": [{"ticker": r.get("ticker"), "date": r.get("date")} for r in quarantined_rows],
        "reason": QUARANTINE_REASON,
    }
    reset_event = dict(json.loads(EVENTS_DATA.read_text(encoding="utf-8"))["reset_event"])
    reset_event["recorded_at"] = ts
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(quarantine_event) + "\n")
        f.write(json.dumps(reset_event) + "\n")
    print("event: " + json.dumps(quarantine_event))
    print("event: " + json.dumps(reset_event))

    # 7. Rebuild the local overlay (not published) and report its size.
    sys.path.insert(0, str(HERE))
    import orchestrate_depth  # noqa: E402
    count = orchestrate_depth.rebuild_overlay()
    print(f"rebuild_overlay(): {count} tickers")

    return 0


if __name__ == "__main__":
    sys.exit(main())
