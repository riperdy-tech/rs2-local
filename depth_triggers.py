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
  rotation   the verdict is older than ROTATION_DAYS — the staleness cap under everything else.

Priority contract (operator): triggered names run FIRST; baseline rotation only when no
triggered work remains. orchestrate_depth consumes trigger_map() for both membership and order.

SEC etiquette: submissions JSON is fetched at most once per UTC day per CIK
(cache/sec_submissions/), with a declared User-Agent, serially. ~172 small requests/day.
"""
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

import rs2_data  # noqa: E402  (repo root on sys.path when imported by orchestrate_depth)

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
LEDGER = HERE / "cache" / "depth_ledger.jsonl"
SUB_CACHE = HERE / "cache" / "sec_submissions"

MOVE_PCT = float(CONFIG.get("depth_move_trigger_pct", 8.0))
ROTATION_DAYS = float(CONFIG.get("depth_rotation_days", 90))
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


def _cik(t):
    cm = rs2_data.load_json(SD / "cik_map.json") or {}
    c = cm.get(t) or cm.get(t.upper())
    return str(c).zfill(10) if c else None


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


def _price_now(t):
    fin = rs2_data.load_json(SD / "financials" / f"{t}.json") or {}
    v = fin.get("Price")
    return float(v) if isinstance(v, (int, float)) else None


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
    p0, p1 = verdict.get("price"), _price_now(t)
    if p0 and p1:
        mv = abs(p1 / p0 - 1) * 100
        if mv > MOVE_PCT:
            out.append(("move", f"price moved {mv:.1f}% since verdict (${p0} -> ${p1})"))
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
