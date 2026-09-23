#!/usr/bin/env python3
"""depth_triggers.py — deterministic re-run triggers for the depth-tier pipeline.

Operator-approved design (2026-08-21): DETECTION IS DETERMINISTIC, JUDGMENT IS THE MODEL'S.
Nothing here reads news or renders an opinion; it detects that something happened and queues the
name — the model then reads the actual material during its tool-enabled run.

Triggers, per name, measured against its NEWEST depth verdict (cache/depth_ledger.jsonl):
  8k         an 8-K was filed after the verdict date. Catches the SanDisk-investor-day class —
             capital-return changes, guidance, M&A, executive exits are all 8-K material events.
             Source: SEC submissions JSON per CIK (deterministic, free, cached daily).
  filing     a 10-Q / 10-K / 20-F / 40-F was filed after the verdict date — the quarterly baseline.
  move       today's price is >MOVE_PCT away from the price the verdict was struck at. Catches
             anything the market noticed, filed or not.
  pack       the verdict was produced on an older revision of the data pack, so the model was
             shown different (or wrongly declared) facts. Ranked with rotation, not with events.
  thesis_break   (P4.5/DEP-13) thesis_monitor.py found a checkable invalidation_rule currently
             satisfied against fresh data. Source: cache/depth_thesis.json.
  momentum_flip  (P4.5/DEP-13) a wait_for_momentum name's momentum_flip_condition is currently
             met. Source: cache/depth_thesis.json.
  earnings_window  (P4.10) the next earnings print is within EARNINGS_WINDOW_TRADING_DAYS.
             NON-queueable, like filing_pending — nothing new to read until the print lands; the
             `filing` trigger above covers the post-print re-run. Source: enrich/{T}.json.
  rotation   the verdict is older than ROTATION_DAYS — the staleness cap under everything else.

Priority contract (operator): triggered names run FIRST; baseline rotation only when no
triggered work remains. orchestrate_depth consumes trigger_map() for both membership and order.

SEC etiquette: submissions JSON is fetched at most once per UTC day per CIK
(cache/sec_submissions/), with a declared User-Agent, serially. ~172 small requests/day.
"""
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

import sys  # noqa: E402

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
import capability_test as cap  # noqa: E402  (PACK_REVISION — see the pack trigger below)
import rs2_data  # noqa: E402  (repo root on sys.path when imported by orchestrate_depth)
import depth_membership as mem  # noqa: E402  (boundary dwell clocks; see re-entry / exit-review)
import price_now  # noqa: E402  (live price capture; vendor quote is fallback — P1.5)

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
LEDGER = HERE / "cache" / "depth_ledger.jsonl"
SUB_CACHE = HERE / "cache" / "sec_submissions"
# P4.5/DEP-13: the thesis monitor's own output (thesis_monitor.py, owner). Read-only here.
THESIS_CACHE = HERE / "cache" / "depth_thesis.json"
# P4.10/DEP-02: enrich_ticker.py's on-demand output, which now also carries next_earnings_date.
ENRICH_DIR = Path(CONFIG["out_enrich_dir"])

MOVE_PCT = float(CONFIG.get("depth_move_trigger_pct", 8.0))
ROTATION_DAYS = float(CONFIG.get("depth_rotation_days", 90))
# P4.10 — the earnings_window trigger fires when the next print is within this many TRADING
# (weekday) days. Non-queueable (like filing_pending — see orchestrate_depth.build_queue's
# NON_QUEUEABLE set): it is visible in `why` but never by itself makes a name due, because the
# analyst has nothing new to read until the print actually lands — the existing `filing` trigger
# covers that post-print re-run.
EARNINGS_WINDOW_TRADING_DAYS = int(CONFIG.get("depth_earnings_window_trading_days", 5))
# Boundary-dwell constants (DEPTH_ORCHESTRATOR_CADENCE_20260825.md §4). Snapshot-days, not
# calendar days — one row per sweep, ~daily. All overridable in config.json.
ENTRY_DWELL = int(CONFIG.get("depth_entry_dwell_days", 5))
EXIT_REVIEW_DWELL = int(CONFIG.get("depth_exit_review_dwell_days", 3))
FRESHNESS_DAYS = float(CONFIG.get("depth_reentry_freshness_days", 21))
COOLDOWN_DAYS = float(CONFIG.get("depth_cooldown_days", 7))


def _verdict_age_days(verdict):
    try:
        return (datetime.now() - datetime.strptime(
            verdict.get("date", "1970-01-01"), "%Y-%m-%d")).days
    except ValueError:
        return 10 ** 6
UA = {"User-Agent": "RS2-Local research riperdy@gmail.com"}
BASELINE_FORMS = {"10-Q", "10-K", "10-K/A", "10-Q/A", "20-F", "40-F"}


def newest_verdicts():
    """{ticker: verdict} from the append-only ledger (newest wins)."""
    out = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                v = json.loads(line)
                out[v["ticker"]] = v
            except Exception:
                continue
    return out


# cik_map.json nests its tickers under a "map" key. A second copy of this reader lived here and
# read it flat, so it returned None for EVERY name; triggers_for() guards the whole SEC block with
# `if cik:`, so the 8-K and filing triggers could never fire. Now there is ONE reader, in
# capability_test, rather than two that can disagree.
_cik = cap.cik


def _submissions(cik):
    """SEC submissions JSON, cached per UTC day. None on any failure — a missing feed must
    degrade to 'no filing trigger today', never to a crash or a fabricated trigger."""
    SUB_CACHE.mkdir(parents=True, exist_ok=True)
    p = SUB_CACHE / f"CIK{cik}.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("_fetched_utc", "")[:10] == today:
                return d
        except Exception:
            pass
    try:
        req = urllib.request.Request(
            f"https://data.sec.gov/submissions/CIK{cik}.json", headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        d["_fetched_utc"] = datetime.now(timezone.utc).isoformat()
        p.write_text(json.dumps(d), encoding="utf-8")
        time.sleep(0.15)          # stay far under SEC's 10 req/s ceiling
        return d
    except Exception:
        return None


def _filings_since(cik, since_date):
    """[(form, date)] filed strictly after since_date (YYYY-MM-DD)."""
    d = _submissions(cik)
    if not d:
        return []
    rec = (d.get("filings") or {}).get("recent") or {}
    forms, dates = rec.get("form") or [], rec.get("filingDate") or []
    return [(f, dt) for f, dt in zip(forms, dates) if dt > since_date]


def _thesis_record(t):
    """{...} row for `t` from cache/depth_thesis.json (thesis_monitor.run()'s own output), or
    None — best-effort, like every other cached artifact this module reads: a missing/corrupt
    file degrades to 'no thesis trigger today', never a crash or a fabricated one."""
    doc = rs2_data.load_json(THESIS_CACHE) or {}
    return (doc.get("tickers") or {}).get(t)


def _trading_days_until(target_date_str, today=None):
    """Weekday count from `today` (exclusive) to `target_date_str` (YYYY-MM-DD, inclusive), or
    None if unparseable or already past. No market-holiday calendar — the same simplification
    ROTATION_DAYS/ENTRY_DWELL already accept elsewhere in this module (calendar/snapshot days,
    not exchange-calendar-exact); a 5-trading-day window does not need holiday precision."""
    if not target_date_str:
        return None
    try:
        target = datetime.strptime(str(target_date_str)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    today = today or datetime.now().date()
    if target < today:
        return None
    n, d = 0, today
    while d < target:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _price_now(t):
    """(price: float, source: str) or (None, None).
    Tries price_now.quote() first; falls back to financials/{t}.json vendor quote.
    """
    try:
        q = price_now.quote(t)
        if q and q.get("price") is not None:
            return float(q["price"]), q.get("source", "yfinance")
    except Exception:
        pass
    fin = rs2_data.load_json(SD / "financials" / f"{t}.json") or {}
    v = fin.get("Price")
    if isinstance(v, (int, float)):
        return float(v), "vendor_quote"
    return None, None


def triggers_for(t, verdict):
    """List of (kind, detail) for one name, judged against its newest verdict. A name with no
    verdict yet is the BASELINE case and returns [] — orchestrate_depth queues those as
    never-run, ahead of rotation but behind triggered work."""
    if not verdict:
        return []
    out = []
    vdate = verdict.get("date") or "1970-01-01"
    cik = _cik(t)
    if cik:
        fresh = _filings_since(cik, vdate)
        eightks = [dt for f, dt in fresh if f.startswith("8-K")]
        baseline = [(f, dt) for f, dt in fresh if f in BASELINE_FORMS]
        if eightks:
            out.append(("8k", f"8-K filed {max(eightks)}"))
        if baseline:
            f, dt = max(baseline, key=lambda x: x[1])
            # DEFER GATE (operator decision 2026-08-21, option A): a 10-Q/10-K trigger is
            # actionable only once OUR fundamentals reflect that filing - otherwise the run
            # would build its pack on tables one quarter stale (the cloud rebuild is weekly, so
            # the gap can reach 6 days). Test: fundamentals_ttm's own per-ticker 'filed' date
            # vs the SEC filing date. While behind, the trigger is reported as filing_pending -
            # visible in logs and status, deliberately NOT queueable. Names with no TTM record
            # (20-F/40-F filers) cannot be measured this way and pass through immediately:
            # their tables never update from 10-Qs, so deferring would defer forever, and the
            # tool-enabled run reads the filing itself.
            ttm = (rs2_data.load_json(SD / "fundamentals_ttm.json") or {}
                   ).get("tickers", {}).get(t) or {}
            ours = ttm.get("filed")
            if ours is None or ours >= dt:
                out.append(("filing", f"{f} filed {dt}"))
            else:
                out.append(("filing_pending", f"{f} filed {dt}; our tables at {ours} - "
                            f"deferred until the data lands"))
    # P4.10/DEP-02 — EARNINGS WINDOW. Non-queueable (like filing_pending above): the print has
    # not happened yet, so there is nothing new for the analyst to read; it exists to make the
    # upcoming print visible in logs/status. The `filing` trigger above already covers the
    # post-print re-run once the 10-Q/10-K actually lands. No CIK needed — sourced from
    # enrich/{T}.json (enrich_ticker.py's next_earnings_date), not the SEC submissions feed.
    en = rs2_data.load_json(ENRICH_DIR / f"{t}.json") or {}
    ned = en.get("next_earnings_date")
    td = _trading_days_until(ned)
    if td is not None and td <= EARNINGS_WINDOW_TRADING_DAYS:
        out.append(("earnings_window", f"next print {ned} ({td} trading day(s) out)"))
    p0 = verdict.get("price")
    p1, src = _price_now(t)
    if p0 and p1:
        mv = abs(p1 / p0 - 1) * 100
        if mv > MOVE_PCT:
            src_str = f" [{src}]" if src else ""
            out.append(("move", f"price moved {mv:.1f}% since verdict (${p0} -> ${p1}{src_str})"))
    # PACK REVISION. A verdict is only as good as the facts the model was shown, so when the pack
    # gains data or corrects a declaration, verdicts struck under the old one are superseded.
    # Without this the book splits: on 2026-08-24 the pack stopped falsely declaring that we hold
    # no SBC, no debt components and no investments, and the 32 names already analysed would have
    # kept a verdict formed while being told that data did not exist. Ranked with rotation, not
    # with events, so the baseline sweep still finishes first.
    if verdict.get("pack_revision", 1) < cap.PACK_REVISION:
        out.append(("pack", f"analysed on pack revision "
                            f"{verdict.get('pack_revision', 1)}; current is {cap.PACK_REVISION}"))
    # P4.5/DEP-13 — THESIS_BREAK and MOMENTUM_FLIP, read from thesis_monitor.py's own output
    # (cache/depth_thesis.json). Deterministic reads of an already-computed record — same
    # "detection is deterministic, judgment is the model's" split as every other trigger here;
    # the mechanical rule-check happened in thesis_monitor, this only surfaces its verdict.
    thesis = _thesis_record(t)
    if thesis:
        if thesis.get("thesis_status") == "breached":
            fired = [c.get("metric") for c in (thesis.get("checks") or [])
                     if c.get("breached") is True]
            out.append(("thesis_break", "invalidation rule breached: "
                        + (", ".join(fired) if fired else "see cache/depth_thesis.json")))
        if thesis.get("momentum_flip_met"):
            out.append(("momentum_flip", f"entry_timing flip condition met (was "
                        f"{verdict.get('entry_timing')}, now "
                        f"{thesis.get('entry_timing_now')})"))
    # PERSISTENT RE-ENTRY (#5) and EXIT-REVIEW (#7) — boundary-dwell triggers. Both DORMANT until
    # the membership log holds enough daily rows; each is guarded on its own dwell threshold, so a
    # thin log simply yields no boundary trigger, never a crash or a false one. Cooldown/freshness
    # keep them from firing more than once per crossing.
    rows = mem.snapshots_recorded()
    age = _verdict_age_days(verdict)
    # #5: name re-entered the boundary (was OUT earlier in the record, now IN past the entry dwell)
    # and its verdict is stale. dwell_in < rows proves it was not IN for the whole record = a real
    # re-entry, not a name that never left.
    if rows >= ENTRY_DWELL:
        din = mem.dwell_in(t)
        if 0 < din < rows and din >= ENTRY_DWELL and age > FRESHNESS_DAYS:
            out.append(("reentry", f"re-entered RN+WL, in {din}d; verdict {age}d old "
                                   f"(freshness {FRESHNESS_DAYS:.0f}d)"))
    # #7: name LEFT the boundary and stayed out past the exit-review dwell, AND we have a stake in
    # the answer — the verdict is a buy, or we hold it. Cooldown stops a name that dipped out days
    # after a fresh run from re-running on nothing new.
    if rows >= EXIT_REVIEW_DWELL:
        dout = mem.dwell_out(t)
        favorable = verdict.get("direction") == "undervalued"
        held = t.upper() in mem.held_names()
        if dout >= EXIT_REVIEW_DWELL and (favorable or held) and age >= COOLDOWN_DAYS:
            why = "held" if held else "undervalued verdict"
            out.append(("exit_review", f"out of RN+WL {dout}d, {why} — diligence re-run"))
    try:
        age = (datetime.now() - datetime.strptime(vdate, "%Y-%m-%d")).days
        if age > ROTATION_DAYS:
            out.append(("rotation", f"verdict {age}d old (cap {ROTATION_DAYS:.0f}d)"))
    except ValueError:
        pass
    return out


def trigger_map(tickers):
    """{ticker: [(kind, detail)]} for the book. Serial, cache-backed; ~1-2 min cold on 172
    names, seconds warm."""
    verdicts = newest_verdicts()
    return {t: triggers_for(t, verdicts.get(t)) for t in tickers}


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.path.insert(0, str(HERE))
    verdicts = newest_verdicts()
    book = sorted(verdicts) or ["GOOG", "PM"]
    for t in book:
        for kind, detail in triggers_for(t, verdicts.get(t)):
            print(f"{t:6s} {kind:9s} {detail}")
    print(f"checked {len(book)} name(s) with verdicts")
