"""warning_log.py - the warning log with prices (WO_HM3a; SPEC_holdings_monitor_v2 section 2.6). A measurement: it changes no book, no queue and nothing the model is told.

Every `resolved` journal line of the monitor becomes one `read` row, whether it warned or not: the reads with `warning_kind` null are the
comparison group (the same triggers queued them). Each row then gets a `fill` line for 1, 20 and 60 sessions after the close before the warning,
for the name and for SPY, as each horizon falls due.

    update(root, now, fetch, ledger)   add the rows not yet logged, then write every fill that is due. Returns a report.
    rows(root)                         the folded view: one dict per read, its fills under "fills": {"1", "20", "60"}
    summary(root)                      per warning kind and per horizon: counts, mean and median of the return minus SPY's
    python tools/holdings_monitor/warning_log.py update | summary [--root DIR]

FILE: <monitor root>/warnings/warning_log.jsonl, append-only, written only by `update`, no lock on the monitor's state. A line whose `event_id`
is already in the file is not written again; a torn last line is never buried.

SESSIONS come from SPY's bars, not from a holiday table. Base date d0 = the last SPY bar on or before the session before the warning; the
horizon date dk = the k-th SPY bar after d0, due once it is on or before the last completed session. All three closes of a fill (d0, d1, dk)
come from ONE fetch of the name, so one adjustment basis.

MISSING PRICES are annotated, never dropped: `ok` (bars on d0, d1, dk), `stale_bar` (the last bar on or before the date is used, dates in
used_d0 / used_d1 / used_dk), `no_price` (no bar in the 7 days up to d0, or none after it, and the horizon is more than 5 SPY bars past due; a delisted
name lands here and stays in every count). A fetch that raises writes nothing: the error is in the report and the fill is tried again.
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import monitor as M

HORIZONS = (1, 20, 60)
YARDSTICK = "SPY"
NO_PRICE_AFTER = 5                                            # DESIGN (the order's number): a fill with no bars is written as no_price once more than this many SPY bars past due
BACKFILL_DAYS = 7                                             # a fetch starts this many days before the base session, so a day without a bar (a holiday, a halt) still leaves a bar on or before it
KINDS = ("event_found", "news_event", "thesis_changed", None)


def log_path(root):
    return Path(root) / "warnings" / "warning_log.jsonl"


def _append(path, lines):
    """Append the lines whose event_id the file does not hold yet, each as one line, flushed and synced (the journal's rule)."""
    have = {l.get("event_id") for l in M._jsonl(path)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as f:
        if f.tell() > 0:
            with open(path, "rb") as r:
                r.seek(-1, os.SEEK_END)
                if r.read(1) != b"\n":
                    f.write(b"\n")                                    # never bury a torn last line mid-file
        for line in lines:
            if line["event_id"] in have:
                continue
            have.add(line["event_id"])
            f.write((json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())


def _bars(rows):
    """[(date, close)] -> sorted [(date, close)], one per date; a NaN close is dropped, 0.0 is kept."""
    kept = {M.as_date(d): float(c) for d, c in rows if M.is_number(c)}
    return sorted(kept.items())


def _at(bars, d):
    """(date, close) of the bar on d, else of the last bar before it; None when there is none."""
    before = [b for b in bars if b[0] <= d]
    return before[-1] if before else None


def _ret(c, base):
    return None if c is None or base is None or base == 0 else c / base - 1


def _read_row(line, held_by, led_T, now):
    return {"kind": "read", "event_id": "read:" + line["run_id"], "run_id": line["run_id"], "ticker": line["ticker"], "cik": line.get("cik"),
            "read_at": line["t"], "decision_time_utc": line["decision_time_utc"], "warning_kind": line.get("warning_kind"),
            "name_state": line.get("name_state"), "thesis_compare": line.get("thesis_compare"), "q1_verdict": (line.get("q1") or {}).get("verdict"),
            "triggers": line.get("triggers"), "held_by": held_by, "ledger_formation_T": led_T, "logged_at": M.iso(now)}


def _fill(row, k, d0, d1, dk, spy, fetch, now, overdue):
    """The fill line of one horizon, or None when the name has no usable bars yet. Raises what the fetch raises."""
    source, got = fetch(row["ticker"], d0 - timedelta(days=BACKFILL_DAYS), dk)
    bars = [b for b in _bars(got) if b[0] <= dk]
    base = _at(bars, d0)
    after = [b for b in bars if b[0] > d0]
    line = {"kind": "fill", "event_id": f"fill:{row['run_id']}:{k}", "run_id": row["run_id"], "ticker": row["ticker"], "k": k, "d0": d0.isoformat(),
            "d1": d1.isoformat(), "dk": dk.isoformat(), "c0": None, "c1": None, "ck": None, "ret_from_before": None, "ret_from_next_close": None,
            "spy_c0": spy[d0], "spy_c1": spy[d1], "spy_ck": spy[dk], "spy_ret_from_before": _ret(spy[dk], spy[d0]),
            "spy_ret_from_next_close": None if k == 1 else _ret(spy[dk], spy[d1]), "source": source, "fetched_utc": M.iso(now)}
    if base is None or not after:
        if not overdue:
            return None
        last = bars[-1] if bars else None
        return {**line, "status": "no_price", "last_bar_date": last[0].isoformat() if last else None, "last_bar_close": last[1] if last else None}
    p0, p1, pk = base, _at(bars, d1), _at(bars, dk)
    exact = (p0[0], p1[0], pk[0]) == (d0, d1, dk)
    line.update(status="ok" if exact else "stale_bar", c0=p0[1], c1=p1[1], ck=pk[1], ret_from_before=_ret(pk[1], p0[1]),
                ret_from_next_close=None if k == 1 else _ret(pk[1], p1[1]))
    if not exact:
        line.update(used_d0=p0[0].isoformat(), used_d1=p1[0].isoformat(), used_dk=pk[0].isoformat())
    return line


def update(root=M.MONITOR_ROOT, now=None, fetch=None, ledger=None):
    """Add a `read` line for every resolved journal line not yet logged, then write every fill that is due. Returns the report:
    {"rows_added", "fills_written": {k: {status: n}}, "not_yet_due", "no_bars_yet" (due, the name has no usable bars, still inside the wait),
    "errors": {ticker: message}, "ledger_error"}."""
    now = M.utc(now)
    fetch = fetch or M._yf_fetch
    path = log_path(root)
    report = {"rows_added": 0, "fills_written": {}, "not_yet_due": 0, "no_bars_yet": 0, "errors": {}, "ledger_error": None}
    logged = {l.get("run_id") for l in M._jsonl(path) if l.get("kind") == "read"}
    new = [l for l in M.Monitor(root).journal_lines() if l.get("kind") == "resolved" and l["run_id"] not in logged]
    if new:
        try:
            led = (ledger or M.ledger_inputs)()
            books, led_T = led["books"], led["ledger_formation_T"]
        except Exception as e:                                          # held_by stays null and the report says so
            books, led_T, report["ledger_error"] = None, None, f"{type(e).__name__}: {e}"
        _append(path, [_read_row(l, None if books is None else sorted(a for a, ts in books.items() if l["ticker"] in ts), led_T, now)
                       for l in new])
        report["rows_added"] = len(new)
    reads = [l for l in M._jsonl(path) if l.get("kind") == "read"]
    done = {l["event_id"] for l in M._jsonl(path) if l.get("kind") == "fill"}
    open_ = [(r, k) for r in reads for k in HORIZONS if f"fill:{r['run_id']}:{k}" not in done]
    if not open_:
        return report
    today = M.last_completed_session(now)
    base_sessions = {r["run_id"]: M.last_completed_session(M.parse_utc(r["decision_time_utc"])) for r, _ in open_}
    try:
        source, got = fetch(YARDSTICK, min(base_sessions.values()) - timedelta(days=BACKFILL_DAYS), today)
        spy_bars = [b for b in _bars(got) if b[0] <= today]
    except Exception as e:
        report["errors"][YARDSTICK] = f"{type(e).__name__}: {e}"
        return report
    spy, dates = dict(spy_bars), [d for d, _ in spy_bars]
    fills = []
    for r, k in open_:
        before = [i for i, d in enumerate(dates) if d <= base_sessions[r["run_id"]]]
        i0 = before[-1] if before else None
        if i0 is None or i0 + k >= len(dates):
            report["not_yet_due"] += 1                                  # the horizon's bar does not exist yet (or the yardstick has no bar before the warning)
            continue
        d0, d1, dk = dates[i0], dates[i0 + 1], dates[i0 + k]
        try:
            line = _fill(r, k, d0, d1, dk, spy, fetch, now, len(dates) - 1 - (i0 + k) > NO_PRICE_AFTER)
        except Exception as e:
            report["errors"][r["ticker"]] = f"{type(e).__name__}: {e}"
            continue
        if line is None:
            report["no_bars_yet"] += 1
            continue
        fills.append(line)
        by = report["fills_written"].setdefault(str(k), {})
        by[line["status"]] = by.get(line["status"], 0) + 1
    _append(path, fills)
    return report


def rows(root=M.MONITOR_ROOT):
    """One dict per read, with its fills under "fills": {"1": ..., "20": ..., "60": ...} (a horizon not yet filled is absent)."""
    lines = M._jsonl(log_path(root))
    out = {l["run_id"]: {**l, "fills": {}} for l in lines if l.get("kind") == "read"}
    for l in lines:
        if l.get("kind") == "fill" and l["run_id"] in out:
            out[l["run_id"]]["fills"][str(l["k"])] = l
    return list(out.values())


def summary(root=M.MONITOR_ROOT):
    """Per warning kind ("no_warning" for null) and per k: rows (reads of that kind), priced (fills ok or stale_bar), no_price, and the mean and
    median of the name's return minus SPY's over the priced fills (k = 1: from the close before; else from the next close)."""
    all_rows = rows(root)
    out = {}
    for kind in KINDS:
        mine = [r for r in all_rows if r.get("warning_kind") == kind]
        per_k = {}
        for k in HORIZONS:
            fills = [r["fills"][str(k)] for r in mine if str(k) in r["fills"]]
            priced = [f for f in fills if f["status"] in ("ok", "stale_bar")]
            key = "ret_from_before" if k == 1 else "ret_from_next_close"
            ex = [f[key] - f["spy_" + key] for f in priced if f[key] is not None and f["spy_" + key] is not None]
            per_k[str(k)] = {"rows": len(mine), "priced": len(priced), "no_price": sum(f["status"] == "no_price" for f in fills),
                             "excess_n": len(ex), "excess_mean": statistics.fmean(ex) if ex else None,
                             "excess_median": statistics.median(ex) if ex else None}
        out[kind or "no_warning"] = per_k
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python warning_log.py", description="The warning log with prices: update it, or print its summary.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, h in (("update", "log the new resolved reads and write the fills that are due (fetches prices)"), ("summary", "print the summary as JSON")):
        sub.add_parser(name, help=h).add_argument("--root", default=str(M.MONITOR_ROOT), help="the monitor's state folder")
    a = ap.parse_args(argv)
    if a.cmd == "update":
        print(json.dumps(update(a.root, datetime.now(timezone.utc)), indent=1, sort_keys=True))
    else:
        print(json.dumps(summary(a.root), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
