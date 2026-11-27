"""news_watch.py - news on the analysed stocks, checked against what each stock's own analysis said matters (operator 2026-11-25;
stocks-workspace/docs/PLAN_news_monitor_redesign_2026-11-25.md).

    python tools/site/news_watch.py gather [--limit N]     # code only: the week's headlines of every analysed stock from SearXNG, new ones kept
    python tools/site/news_watch.py check  [--limit N]     # the reader: one small call a stock with new headlines
    python tools/site/news_watch.py act                    # serious warnings: one Telegram message; re-reads queued (capped a day)
    python tools/site/news_watch.py track                  # the closes before and 1, 20 and 60 sessions after every warning (a log; nothing acts on it)
    python tools/site/news_watch.py morning                # gather, check, act, track, then the site files are published
    python tools/site/news_watch.py status

THREE STEPS, CHEAPEST FIRST. (1) GATHER, code: for every stock with a report that was analysed (operator-excluded names left out), the
holdings monitor's news queries and filters (tools/holdings_monitor/monitor.py: NEWS_QUERIES, its low-trust list, the company named in
the headline or snippet). A headline or address seen on an earlier day is not new. A stock's first gather returns a week at once: only
what the search engine itself dates within FIRST_GATHER_HOURS is new, the rest is its baseline.
(2) CHECK, a model: the new headlines of one stock, with that stock's own points (the claims of its report's risks,
competitive_position and growth_thesis tasks, ids R1.., C1.., G1..), the events its report already knows and the warnings already raised.
It answers with the distinct events that touch a point or are a new serious matter. Code checks every answer: the items exist, the point
ids exist, and the quote is in the headline or snippet of the item it names; an answer that fails a check is kept in the day's check file
with its failure and raises nothing. What is critical is never a fixed list of event types (operator 2026-11-14: "it could be anything,
so it should be a variable thing"): it is what the stock's own analysis named, or what the reader calls a new serious matter.
(3) ACT, code: every checked event is a warning (warnings.jsonl, with the last close). The day's serious warnings go out in one Telegram
message. A serious warning queues its stock for a re-read in the worker's filing queue, at most REREADS_A_DAY stocks a day, a stock whose
company has filed since its report first. THE RE-READ (gemini_ondemand.analyze, a queue reason news:...): the reading is run on the SEC
packet plus the press reports of the stock's warnings as items of kind news (packet_with_news; qwen_c tells the reader they are press
reports and checks their quotes like any other); the valuation is run on the SEC packet alone and is given the reading without its
news-cited claims (without_news_claims), so the number moves only on filings. Monitoring never sells and moves no money (operator
2026-10-01).

HELD NAMES (operator 2026-11-27; stocks-workspace/docs/PLAN_held_names_monitor_2026-11-27.md). A stock is held when the published overlay
rates it BUY (held(): the AI book holds every such stock). For held names only, and by code alone (held_signals, between check and act):
an 8-K with a critical item filed since the stock's report is a SERIOUS warning, and a large price move is a warning that is not serious
(told and shown; it queues no re-read). In act() a held stock whose warning is worse or unclear is queued ahead of every other stock,
inside the same daily cap, and the message leads with held stocks. Every warning records whether the stock was held. The screener's AI
book does not enter a stock that is under review; a held stock stays.

THE READER is READER (environment NEWS_READER). "cloud" (the default) reads through the worker's own calls, BATCH stocks a call (the
call's fixed cost is shared; replay 2026-11-25: 8,560 tokens a stock-day against 19,640, the same answers): Gemini, or Claude Sonnet when
Gemini's allowance is under the worker's floor. "ollama:<model>" reads on this PC, one stock a call, and a stock it cannot read falls
back to the cloud. With no reader the stock-day stays unchecked and the next run takes it. Thinking is high on all.

ON THE SITE (gemini_ondemand.build calls for_site): a report carries `news`, its warnings of the last SHOW_DAYS days, and `under_review`,
its newest serious warning raised after the report was made. The value itself reads filings only, so news changes the flag at once and
the number when the company files and the stock is read again.

Everything is written under cache/gemini_site/news of this checkout: raw/<T>/<day>.json, seen/<T>.json, checks/<day>/<T>.json,
warnings.jsonl, track.json, state.json, usage.jsonl, log. The morning copies warnings.jsonl, track.json and state.json to the private
state repository (paper_books/news_watch), where sync_state backs them up.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "holdings_monitor"))
import gemini_ondemand as G  # noqa: E402
import monitor as M  # noqa: E402
import paths  # noqa: E402
import qwen_ondemand as Q  # noqa: E402

NEWS = G.SITE / "news"
RAW, SEEN, CHECKS = NEWS / "raw", NEWS / "seen", NEWS / "checks"
WARNINGS, STATE, USAGE, LOG, LOCK = NEWS / "warnings.jsonl", NEWS / "state.json", NEWS / "usage.jsonl", NEWS / "log", NEWS / "news.lock"
TRACK = NEWS / "track.json"
TRACK_SESSIONS = (1, 20, 60)        # closes logged this many sessions after a warning (the holdings monitor's warning log, SPEC v2)
READER = os.environ.get("NEWS_READER", "cloud")      # "cloud", or "ollama:<model>" (replay 2026-11-25: Qwen 14B is not adequate)
CLOUD_READERS = ("gemini", "sonnet")
OLLAMA_URL = "http://localhost:11434/api/chat"
NUM_CTX, NUM_PREDICT = 16384, 8192
BATCH = 5                         # stocks in one Gemini call
MAX_ROWS = 15                     # headlines handed to one check; the rest are counted in the check file (`rows_dropped`)
SEEN_KEEP_DAYS = 45
FIRST_GATHER_HOURS = 36           # a stock's first gather: only headlines the engine dates this recent are new; the rest are its baseline
KNOWN_WARNING_DAYS = 10           # a stock's own warnings of this many days are told to the reader as already known
SHOW_DAYS = 14                    # the site shows a stock's warnings of this many days
REVIEW_DAYS = 30                  # a serious warning older than this no longer marks the stock under review
REREADS_A_DAY = 3                 # operator 2026-11-25 (ruling R2): at most this many re-reads queued by news a day
# Held names (operator 2026-11-27, PLAN_held_names_monitor_2026-11-27, H1 to H5 as recommended). The items and the two price rules are the
# holdings monitor's, taken as they stand (M.P0_ITEMS, M.price_signal).
CRITICAL_ITEMS = {"1.02": "a material agreement was terminated", "1.03": "bankruptcy or receivership", "2.04": "a debt obligation was accelerated",
                  "2.06": "a material impairment", "3.01": "a notice of delisting or of a failed listing rule", "4.01": "the auditor changed",
                  "4.02": "earlier financial statements are not to be relied on"}
assert set(CRITICAL_ITEMS) == set(M.P0_ITEMS)
PRICE_MOVE_QUIET_DAYS = 7         # one warning a move: the 5-session rule fires again on each day of the same move. Replay 2026-11-27 on the 66 held
                                  # stocks, 12 months: 471 trigger days, 257 moves (about one a session day over the whole book); 13 critical 8-Ks
GATHER_BATCH, GATHER_PAUSE_S = 26, 300      # the B2 gather's pacing: SearXNG suspended an engine asked too fast (2026-10-02)
ARTICLE_MIN = 600                 # a fetched page shorter than this is not an article
EVIDENCE_ROWS, EVIDENCE_CHARS = 6, 6000     # press reports handed to a re-read, and the characters of an article kept (qwen_c.news_packet caps the total)
TELL_STOCKS = 20                  # stocks named in the day's Telegram message; the rest are counted
DOWN_AFTER = 5                   # the first this-many searches all failing ends the gather: the search engine is down
CHECK_KEEP_DAYS = 3               # a gathered stock-day no reader took within this many days is no longer checked (it is old news)
MARKER_TOUCH_S = 600
POINT_TASKS = (("R", "risks"), ("C", "competitive_position"), ("G", "growth_thesis"))

PROMPT = """Answer in one reply. Do not call any tool, do not search, do not read or write files.

You are checking today's news about {subject} against the points {whose} own analysis said matter.

{blocks}
For each company, find the distinct events its news items report that happened to THAT company and bear on its value:
- an event that touches one or more of the company's points (for better or worse), or
- a new serious matter the analysis did not name (anything: a lawsuit, a lost customer, a deal, a regulator, an accident).
Leave out: price moves, analyst ratings and targets, holdings changes by funds, generic market or sector commentary, lists and
rankings, an item about a different company, and an item that only retells an event the analysis already knows or a warning already raised.
Several items that report the same event are ONE event: list them all in "items".

Reply with JSON only, no other text:
{{"events": [{{"items": ["{ex}N3", "{ex}N5"], "touches": ["{ex}R2"], "new_matter": false, "direction": "worse", "serious": true,
  "why": "one plain sentence", "quote_item": "{ex}N3", "quote": "exact words copied from that item's headline or snippet"}}]}}
- "touches": point ids, or [] when "new_matter" is true.
- "direction": "worse", "better" or "unclear" for the company's value.
- "serious": true when the event is large enough that the analysis could reach a different conclusion on a point it touches, or is a
  new matter a careful owner of the stock would want analysed now. false for routine business news (a small contract, a product
  update, a conference, a routine quarterly comment).
- "quote": copied exactly, at least four words, from the headline or snippet of "quote_item".
An empty list is the right answer when nothing qualifies."""


def log(msg):
    NEWS.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _read(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def norm(s):
    return M.normalize_title(s)


def today_utc(now=None):
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the stocks and their points
def reports():
    """{ticker: report} of the stocks whose analysis ran and named at least one point; operator-excluded names are never watched."""
    excluded = set(Q.book_paths.operator_excluded())
    out = {}
    for p in sorted(G.ONDEMAND.glob("*.json")) if G.ONDEMAND.exists() else []:
        d = _read(p)
        if d and d.get("ticker") not in excluded and points(d):
            out[d["ticker"]] = d
    return out


def points(report):
    """[(id, claim)] of a report's own risks (R), competitive position (C) and growth conditions (G), in the report's order."""
    out = []
    for letter, task in POINT_TASKS:
        for i, c in enumerate((report.get("tasks") or {}).get(task) or [], 1):
            if isinstance(c, dict) and c.get("claim"):
                out.append((f"{letter}{i}", c["claim"]))
    return out


def known_events(report):
    return [c["claim"] for c in (report.get("tasks") or {}).get("material_events") or [] if isinstance(c, dict) and c.get("claim")]


def companies():
    return {t: r.get("name") for t, r in stock_rows().items()}


def warnings_log():
    return Q._jsonl(WARNINGS) if WARNINGS.exists() else []


# ---------------------------------------------------------------- 1. gather
_AGE = re.compile(r"^\s*(\d+)\s+(minute|min|hour|day)s?\s+ago\b", re.I)


def age_hours(source_line):
    """Hours since publication from a search row's own line ("23 hours ago | The Journal on MSN"), or None where it gives no age."""
    m = _AGE.match(str(source_line or ""))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return n / 60 if unit.startswith("min") else n * 24.0 if unit == "day" else float(n)


def search_news(company, ticker, day, endpoint=None, get_json=None, pause_s=1.0, sleep=time.sleep):
    """The week's news rows of one company from SearXNG: the holdings monitor's queries and filters (monitor.NEWS_QUERIES, its press name,
    the company's distinctive word in the headline or snippet, its low-trust list), one row a headline or address. Unlike
    monitor.searx_news a row keeps the engine's own line as `source` (publisher and age: what the reader was shown in the replay) and
    `age_hours` read from it. Rows {title, url, snippet, source, age_hours, found_by}. Raises when every query failed."""
    def default_get(url):
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    get = get_json or default_get
    press = M.press_name(company, ticker)
    pattern = M._word_pattern(M.name_token(press) or press)
    rows, by_key, errors = [], {}, []
    for i, (key, template, engines) in enumerate(M.NEWS_QUERIES):
        params = {"q": template.format(p=press), "time_range": "week", "format": "json"}
        params.update({"engines": engines} if engines else {"categories": "news"})
        if i:
            sleep(pause_s)
        try:
            data = get(f"{endpoint or M.SEARX_URL}/search?" + urllib.parse.urlencode(params))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{key}: {type(e).__name__}: {str(e)[:100]}")
            continue
        for res in data.get("results") or []:
            url = str(res.get("url") or "").strip()
            title = re.sub(r"\s+", " ", str(res.get("title") or "")).strip()[:150]
            content = re.sub(r"\s+", " ", str(res.get("content") or "")).strip()
            if not url or not title or any(bad in url for bad in M.LOW_TRUST) or not pattern.search(title + " " + content):
                continue
            k = (M.normalize_title(title), M.normalize_url(url))
            hit = by_key[k[0]] if k[0] in by_key else by_key.get(k[1])
            if hit is not None:
                if key not in hit["found_by"]:
                    hit["found_by"].append(key)
                continue
            line = str(res.get("metadata") or res.get("engine") or "")
            row = {"title": title, "url": url, "snippet": content[:420], "source": line[:120], "age_hours": age_hours(line), "found_by": [key]}
            by_key[k[0]] = by_key[k[1]] = row
            rows.append(row)
    if errors and len(errors) == len(M.NEWS_QUERIES):
        raise RuntimeError("every news query failed: " + "; ".join(errors[:2]))
    return rows


def new_rows(ticker, day, rows):
    """(the rows not seen on an earlier day, True when this is the stock's first gather). Updates the stock's seen file; a headline and an
    address are each a key, kept SEEN_KEEP_DAYS days. On a first gather a week of headlines comes back at once: only the rows the engine
    itself dates within FIRST_GATHER_HOURS are new, the rest are the baseline."""
    seen = _read(SEEN / f"{ticker}.json", None)
    first = seen is None
    seen = seen or {}
    cut = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=SEEN_KEEP_DAYS)).strftime("%Y-%m-%d")
    seen = {k: d for k, d in seen.items() if d >= cut}
    out = []
    for r in rows:
        keys = [k for k in ("t:" + norm(r["title"]), "u:" + M.normalize_url(r["url"])) if len(k) > 2]
        if any(seen.get(k, day) < day for k in keys):        # seen on an earlier day; a row of an earlier run of the same day is still today's
            continue
        if not any(k in seen for k in keys) and (not first or (r.get("age_hours") is not None and r["age_hours"] <= FIRST_GATHER_HOURS)):
            out.append(r)
        for k in keys:
            seen.setdefault(k, day)
    _write(SEEN / f"{ticker}.json", seen)
    return out, first


def gather(limit=None, search=None, now=None, sleep=time.sleep, marker=None):
    """One gather of every watched stock. A stock already gathered today is skipped (a rerun finishes a broken morning). A stock whose
    search fails is recorded with its error and counted; the run goes on. Returns {stocks, gathered, with_new, errors}."""
    search = search or search_news
    day = today_utc(now)
    names = sorted(reports())[:limit]
    comp = companies()
    out = {"day": day, "stocks": len(names), "gathered": 0, "with_new": 0, "errors": []}
    last_touch, done_in_batch = 0.0, 0
    for t in names:
        dest = RAW / t / f"{day}.json"
        if dest.exists() and not (_read(dest) or {}).get("error"):
            continue
        if marker is not None and time.time() - last_touch > MARKER_TOUCH_S:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(os.getpid()))
            last_touch = time.time()
        if done_in_batch == GATHER_BATCH:
            sleep(GATHER_PAUSE_S)
            done_in_batch = 0
        done_in_batch += 1
        try:
            rows = search(comp.get(t) or t, t, day)
        except Exception as e:  # noqa: BLE001  one stock's failed search is recorded and counted, never a reason to stop
            out["errors"].append(t)
            _write(dest, {"ticker": t, "day": day, "error": f"{type(e).__name__}: {str(e)[:200]}", "rows": []})
            if len(out["errors"]) == DOWN_AFTER and not out["gathered"]:      # the first stocks all failed: SearXNG is down, not these stocks
                out["errors"] = names
                log(f"gather {day}: stopped, the first {DOWN_AFTER} searches all failed ({str(e)[:120]})")
                return out
            continue
        fresh, first = new_rows(t, day, rows)
        _write(dest, {"ticker": t, "day": day, "company": comp.get(t), "found": len(rows), "first_gather": first, "rows": fresh})
        out["gathered"] += 1
        out["with_new"] += bool(fresh)
    log(f"gather {day}: {out['stocks']} stocks, {out['gathered']} gathered, {out['with_new']} with new headlines, {len(out['errors'])} errors")
    return out


# ---------------------------------------------------------------- 2. check
def block(ticker, company, report, day, rows, prior, prefix=""):
    pts = points(report)
    known = known_events(report) + [f"(warning already raised {w['day']}) {w['why']}" for w in prior]
    return (f"=== COMPANY {ticker}: {company}. The analysis is dated {str(report.get('date'))[:10]}. Today is {day}.\n"
            "POINTS THE ANALYSIS NAMED (R = a risk, C = competitive position, G = a condition of the growth case):\n"
            + ("\n".join(f"{prefix}{i}: {c}" for i, c in pts) or "(none)")
            + "\nEVENTS THE ANALYSIS ALREADY KNOWS, AND WARNINGS ALREADY RAISED:\n" + ("\n".join(f"- {e}" for e in known) or "(none)")
            + "\nNEWS ITEMS FIRST SEEN TODAY (headline, source, snippet; you have nothing else):\n"
            + "\n".join(f"{prefix}N{i}: {r['title']} | {r.get('source') or ''} | {r.get('snippet') or ''}"
                        for i, r in enumerate(rows, 1)) + "\n")


def prompt(jobs):
    """The message for one stock (ids N1, R2) or several (ids TICKER.N1, TICKER.R2). jobs: [(ticker, company, report, day, rows, prior)]."""
    many = len(jobs) > 1
    return PROMPT.format(subject="several companies, each on its own," if many else "one company", whose="each company's" if many else "its",
                         blocks="\n".join(block(*j, prefix=f"{j[0]}." if many else "") for j in jobs), ex=f"{jobs[0][0]}." if many else "")


def parse_reply(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d["events"] if isinstance(d, dict) and isinstance(d.get("events"), list) else None


def _row(ref, rows):
    m = re.fullmatch(r"N(\d+)", str(ref or ""))
    return rows[int(m.group(1)) - 1] if m and 1 <= int(m.group(1)) <= len(rows) else None


def checked_event(ev, rows, point_ids):
    """One reply event with code's checks on it. `ok` is True when every item exists, every point id exists, the event names a point or is
    a new matter, and the quote (four words or more) is in the headline or snippet of its quote_item. Nothing is corrected: a failed
    event is kept with `failed` saying why and raises no warning."""
    items = ev.get("items") if isinstance(ev.get("items"), list) else []
    touches = ev.get("touches") if isinstance(ev.get("touches"), list) else []
    found = [_row(i, rows) for i in items]
    qrow = _row(ev.get("quote_item"), rows)
    q = norm(ev.get("quote") or "")
    failed = []
    if not items or any(r is None for r in found):
        failed.append("item_unknown")
    if any(t not in point_ids for t in touches):
        failed.append("point_unknown")
    if not touches and ev.get("new_matter") is not True:
        failed.append("no_point_and_not_new")
    if qrow is None or ev.get("quote_item") not in items:
        failed.append("quote_item_unknown")
    elif len(q.split()) < 4 or q not in norm(qrow["title"] + " " + (qrow.get("snippet") or "")):
        failed.append("quote_not_in_item")
    return {"items": [str(i) for i in items], "touches": [str(t) for t in touches], "new_matter": ev.get("new_matter") is True,
            "direction": ev.get("direction") if ev.get("direction") in ("worse", "better", "unclear") else "unclear",
            "serious": ev.get("serious") is True, "why": str(ev.get("why") or "")[:400], "quote_item": ev.get("quote_item"),
            "quote": str(ev.get("quote") or "")[:400], "ok": not failed, "failed": failed,
            "headlines": [{"title": r["title"], "url": r["url"] if re.match(r"https?://", str(r["url"])) else "", "source": r.get("source")}
                          for r in found if r]}                       # the site links the address: only a web address is passed on


def split_batch(events, tickers):
    """{ticker: [event with its ids freed of the ticker]} of a several-stock reply; an event whose ids name another stock, or two, or a
    point of a stock other than its own, goes under "_mixed" and raises nothing."""
    out = {t: [] for t in tickers}
    out["_mixed"] = []
    for ev in events:
        ids = [str(x) for x in (ev.get("items") or []) + (ev.get("touches") or []) + [ev.get("quote_item")] if x is not None]
        owners = {i.rsplit(".", 1)[0] for i in ids if "." in i}
        if len(owners) != 1 or any("." not in i for i in ids) or next(iter(owners)) not in tickers:
            out["_mixed"].append(ev)
            continue
        t = next(iter(owners))
        cut = lambda x: str(x)[len(t) + 1:]  # noqa: E731
        out[t].append({**ev, "items": [cut(i) for i in ev.get("items") or []], "touches": [cut(i) for i in ev.get("touches") or []],
                       "quote_item": cut(ev.get("quote_item"))})
    return out


def _usage(rec):
    NEWS.mkdir(parents=True, exist_ok=True)
    with USAGE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": Q.now_z(), **rec}) + "\n")


def ask_ollama(model, text, label):
    body = {"model": model, "stream": False, "think": "high", "messages": [{"role": "user", "content": text}],
            "options": {"num_ctx": NUM_CTX, "num_predict": NUM_PREDICT, "seed": 1000}}
    t0 = time.time()
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        d = json.loads(r.read().decode("utf-8"))
    _usage({"reader": f"ollama:{model}", "label": label, "seconds": round(time.time() - t0, 1), "prompt_chars": len(text),
            "input_tokens": d.get("prompt_eval_count"), "output_tokens": d.get("eval_count"), "done_reason": d.get("done_reason")})
    if d.get("done_reason") != "stop":                     # a reply cut at num_predict is not an answer
        return None
    return (d.get("message") or {}).get("content")


def ask_cloud(arm, text, label):
    """One message to a cloud reader through the worker's own call (agy for Gemini, the Claude Code command line for Sonnet), high effort."""
    G.set_arm(arm)
    t0 = time.time()
    res, _ = (G._ask_claude if arm in G.CLAUDE_ARMS else G._ask_gemini)(text, 900)
    u = (res or {}).get("usage") or {}
    _usage({"reader": arm, "label": label, "seconds": round(time.time() - t0, 1), "prompt_chars": len(text), "status": (res or {}).get("status"), **u})
    return (res or {}).get("response") if res and res.get("status") == "SUCCESS" else None


def cloud_reader():
    """(name, ask(text, label)) of the first cloud reader whose allowance is above the worker's floors: Gemini, then Claude Sonnet (operator
    2026-11-21: the two are interchanged, never waited for); None when both are low."""
    for arm in CLOUD_READERS:
        G.set_arm(arm)
        if not G.quota_low():
            return arm, (lambda text, label, arm=arm: ask_cloud(arm, text, label))
    return None


def read_jobs(jobs, reader=None, ollama=None, cloud=None):
    """{ticker: (reader used, [raw event]) or None when no reader answered}. A local reader takes one stock a call; a stock it cannot read,
    and every stock when READER is "cloud", goes to the cloud reader that has room, BATCH stocks a call."""
    reader = READER if reader is None else reader
    ollama, cloud = ollama or ask_ollama, cloud or cloud_reader
    out, left = {}, list(jobs)
    if reader.startswith("ollama:"):
        model, left = reader.split(":", 1)[1], []
        for j in jobs:
            try:
                ev = parse_reply(ollama(model, prompt([j]), f"{j[0]}:{j[3]}"))
            except Exception as e:  # noqa: BLE001  Ollama not running, or the call failed: the stock falls back
                log(f"check {j[0]}: local reader failed ({type(e).__name__}: {str(e)[:120]})")
                ev = None
            if ev is None:
                left.append(j)
            else:
                out[j[0]] = (reader, ev)
    for i in range(0, len(left), BATCH):
        g = left[i:i + BATCH]
        got = cloud()                                      # asked before every call: an allowance that runs low mid-morning changes the reader
        if got is None:
            log(f"check: {len(left) - i} stocks left unchecked (no reader: Gemini's and Sonnet's allowances are under their floors)")
            break
        name, ask = got
        ev = parse_reply(ask(prompt(g), f"{g[0][3]}:{','.join(j[0] for j in g)}"))
        if ev is None:
            continue
        if len(g) == 1:
            out[g[0][0]] = (name, ev)
        else:
            per = split_batch(ev, [j[0] for j in g])
            if per["_mixed"]:
                log(f"check: {len(per['_mixed'])} events with mixed company ids dropped ({','.join(j[0] for j in g)})")
            for j in g:
                out[j[0]] = (name, per[j[0]])
    return {j[0]: out.get(j[0]) for j in jobs}


def warning_id(ticker, day, ev):
    return hashlib.sha1(f"{ticker}|{day}|{ev['headlines'][0]['title']}".encode("utf-8")).hexdigest()[:12]


def last_close(ticker, stocks=None):
    r = (stocks or {}).get(ticker) or {}
    v = r.get("price", r.get("close"))
    return v if isinstance(v, (int, float)) else None


def stock_rows():
    s = json.loads((paths.resolve("screener_data_dir") / "stocks.json").read_text(encoding="utf-8"))
    return {r["symbol"]: r for r in (s if isinstance(s, list) else s.get("stocks", s)) if isinstance(r, dict) and r.get("symbol")}


def company_line(ticker, name, stocks):
    """The company as the reader is told it: its name and, where the screener has them, its industry and sector, so a headline about
    another thing of the same name (a ticker that is also a word or an abbreviation) can be told apart."""
    r = stocks.get(ticker) or {}
    kind = ", ".join(str(r[k]) for k in ("industry", "sector") if r.get(k))
    return f"{name or ticker} ({kind})" if kind else str(name or ticker)


def check(limit=None, now=None, **readers):
    """Checks every gathered stock-day that has new headlines and no check file yet, the oldest day first, so a later day is told the
    warnings an earlier day raised. Writes the check file and appends one warning per event that passed code's checks. Returns {checked,
    warnings, serious, unread, calls, tokens}: the reader calls of this run and the tokens they used, from the usage file."""
    started = Q.now_z()
    reps = reports()
    mine = held(reps)
    log_rows = warnings_log()
    stocks = stock_rows()
    oldest = ((now or datetime.now(timezone.utc)) - timedelta(days=CHECK_KEEP_DAYS)).strftime("%Y-%m-%d")
    by_day = {}
    for d in sorted(RAW.glob("*/*.json")) if RAW.exists() else []:
        if d.stem < oldest:
            continue
        raw = _read(d) or {}
        t, day = raw.get("ticker"), raw.get("day")
        if not raw.get("rows") or raw.get("error") or t not in reps or (CHECKS / day / f"{t}.json").exists():
            continue
        by_day.setdefault(day, []).append(raw)
    out = {"checked": 0, "warnings": 0, "serious": 0, "unread": 0}
    left = limit
    for day in sorted(by_day):
        cut = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=KNOWN_WARNING_DAYS)).strftime("%Y-%m-%d")
        raws = by_day[day] if left is None else by_day[day][:left]
        left = None if left is None else left - len(raws)
        for i in range(0, len(raws), 20):                  # in slices, so a broken run keeps what it has read
            part = [(raw["ticker"], company_line(raw["ticker"], raw.get("company"), stocks), reps[raw["ticker"]], day, raw["rows"][:MAX_ROWS],
                     [w for w in log_rows if w["ticker"] == raw["ticker"] and cut <= w["day"] < day], len(raw["rows"]) - len(raw["rows"][:MAX_ROWS]))
                    for raw in raws[i:i + 20]]
            answers = read_jobs([j[:6] for j in part], **readers)
            for t, company, rep, day_, rows, prior, dropped in part:
                if answers.get(t) is None:
                    out["unread"] += 1
                    continue
                reader, raw_events = answers[t]
                ids = {i for i, _ in points(rep)}
                events = [checked_event(e, rows, ids) for e in raw_events if isinstance(e, dict)]
                _write(CHECKS / day / f"{t}.json", {"ticker": t, "day": day, "reader": reader, "report_date": rep.get("date"), "rows": len(rows),
                                                     "rows_dropped": dropped, "events": events})
                out["checked"] += 1
                claims = dict(points(rep))
                for e in (e for e in events if e["ok"]):
                    w = {"id": warning_id(t, day, e), "ticker": t, "day": day, "at": Q.now_z(), "reader": reader, "serious": e["serious"],
                         "direction": e["direction"], "new_matter": e["new_matter"], "why": e["why"], "quote": e["quote"],
                         "touches": [{"id": p, "claim": claims[p]} for p in e["touches"]],
                         "headline": e["headlines"][0]["title"], "url": e["headlines"][0]["url"], "source": e["headlines"][0].get("source"),
                         "outlets": len(e["headlines"]), "report_date": rep.get("date"), "close_at_warning": last_close(t, stocks),
                         "held": t in mine}
                    with WARNINGS.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(w, ensure_ascii=False) + "\n")
                    log_rows.append(w)
                    out["warnings"] += 1
                    out["serious"] += e["serious"]
        if left is not None and left <= 0:
            break
    used = [u for u in (json.loads(ln) for ln in USAGE.read_text(encoding="utf-8").splitlines() if ln.strip()) if u["at"] >= started] if USAGE.exists() else []
    # a Gemini row carries total_tokens; a Sonnet row carries only its parts (the 2026-11-27 morning's line counted 15 of 44 calls)
    out["calls"], out["tokens"] = len(used), sum(u.get("total_tokens") or sum(u.get(k) or 0 for k in ("input_tokens", "output_tokens", "thinking_tokens"))
                                                 for u in used)
    log(f"check: {out['checked']} stock-days checked, {out['warnings']} warnings ({out['serious']} serious), {out['unread']} left unread, "
        f"{out['calls']} reader calls, {out['tokens']} tokens")
    return out


# ---------------------------------------------------------------- held names: the set, and two signals code finds without a reader
def held(reps=None):
    """H1: the watched stocks the published overlay rates BUY, which is the AI book by construction (the screener's ledger `ai_book` holds
    every such stock). No overlay file: no stock is held. When real positions exist they are to be added here."""
    reps = reports() if reps is None else reps
    ov = (_read(G.OVERLAY, {}) or {}).get("tickers") or {}
    return {t for t, v in ov.items() if t in reps and isinstance(v, dict) and v.get("verdict") == "BUY" and v.get("analysis") != "not run"}


def code_warning(ticker, day, kind, key, serious, direction, why, headline, rep, stocks, url=None):
    """A warning code raised (kind `filing_event` or `price_move`), in the shape of a reader's warning; `reader` is "code", there is no quote."""
    return {"id": hashlib.sha1(f"{ticker}|{kind}|{key}".encode("utf-8")).hexdigest()[:12], "ticker": ticker, "day": day, "at": Q.now_z(),
            "reader": "code", "kind": kind, "held": True, "serious": serious, "direction": direction, "new_matter": True, "why": why, "quote": None,
            "touches": [], "headline": headline, "url": url, "source": "SEC" if kind == "filing_event" else None, "outlets": 0,
            "report_date": rep.get("date"), "close_at_warning": last_close(ticker, stocks)}


def critical_filings(ticker, since, now, get=None, ciks=None):
    """[(accession, form, items, cik)] of the stock's 8-Ks (and amendments) that carry a CRITICAL_ITEMS item and became effective after
    `since` and by `now`, oldest first; `items` the critical ones, sorted."""
    get = get or (lambda url: G.sec_store.get(url, online=True))
    cik = (G._ciks([ticker]) if ciks is None else ciks).get(ticker)
    if not cik:
        raise ValueError("no CIK in cik_map.json")
    out = []
    for r in G.P._filing_rows(json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))):
        items = sorted({i.strip() for i in str(r["items"] or "").split(",")} & set(CRITICAL_ITEMS))
        if r["form"] in G.P.EIGHT_K_FORMS and items and r["accepted"] is not None and since < r["effective"] <= now:
            out.append((r["effective"], r["accession"], r["form"], items, cik))
    return [x[1:] for x in sorted(out)]


def held_signals(now=None, filings=None, prices=None):
    """The two signals of the plan's C and D, for held names only; each new one is appended to the warnings log. Returns {held, filing_events,
    price_moves, errors}.
    C, a critical 8-K since the stock's report: a SERIOUS warning (direction unclear: code names the item, it does not judge it), so act()
    tells it and queues the re-read, which reads that filing (filed_since finds it).
    D, a large price move on the newest completed session (M.price_signal: 3 standard deviations of the 60 sessions before, or 20% over 5
    sessions): a warning that is NOT serious (H4: told and shown, no re-read by itself; with no filing and no news there is nothing new
    to read), and none within PRICE_MOVE_QUIET_DAYS days of the stock's last one. A stock whose list or prices cannot be read is logged
    and left for the next morning."""
    now = now or datetime.now(timezone.utc)
    filings, prices = filings or critical_filings, prices or M.yf_prices
    reps = reports()
    names = sorted(held(reps))
    log_rows = warnings_log()
    have = {w["id"] for w in log_rows}
    quiet = (now - timedelta(days=PRICE_MOVE_QUIET_DAYS)).strftime("%Y-%m-%d")
    moved = {w["ticker"] for w in log_rows if w.get("kind") == "price_move" and w["day"] > quiet}
    stocks = stock_rows()
    day = today_utc(now)
    out = {"held": len(names), "filing_events": [], "price_moves": [], "errors": []}
    new = []
    for t in names:
        rep = reps[t]
        try:
            for acc, form, items, cik in filings(t, G._dt(G.decision_time(rep)), now):
                what = "; ".join(f"item {i}, {CRITICAL_ITEMS[i]}" for i in items)
                w = code_warning(t, day, "filing_event", acc, True, "unclear", f"The company filed a form {form} with {what}. The analysis has not read it.",
                                 f"{form}: {what}", rep, stocks,
                                 url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=40")
                if w["id"] not in have:
                    new.append(w)
                    out["filing_events"].append(t)
        except Exception as e:  # noqa: BLE001
            out["errors"].append(t)
            log(f"held {t}: filings not read ({type(e).__name__}: {str(e)[:120]})")
        try:
            pr = prices(t, now)
            sig = M.price_signal([(c["date"], c["close"]) for c in pr["closes"]])
            if sig and sig["date"] == pr["expected_session"] and (sig["sigma_trigger"] or sig["move_trigger"]) and t not in moved:
                parts = ([f"{sig['z']:+.1f} standard deviations of the 60 sessions before in one session"] if sig["sigma_trigger"] and sig["z"] is not None else []) \
                    + ([f"{sig['move']:+.0%} over {M.PRICE_MOVE_SESSIONS} sessions"] if sig["move_trigger"] else [])
                move = sig["move"] if sig["move_trigger"] else sig["z"]
                w = code_warning(t, day, "price_move", sig["date"], False, "worse" if (move or 0) < 0 else "better",
                                 f"The price moved {' and '.join(parts) or 'sharply'} to the close of {sig['date']}. Code found it; no reader judged it.",
                                 f"Large price move to {sig['date']}", rep, stocks)
                if w["id"] not in have:
                    new.append(w)
                    out["price_moves"].append(t)
        except Exception as e:  # noqa: BLE001
            out["errors"].append(t)
            log(f"held {t}: prices not read ({type(e).__name__}: {str(e)[:120]})")
    if new:
        WARNINGS.parent.mkdir(parents=True, exist_ok=True)
        with WARNINGS.open("a", encoding="utf-8") as f:
            for w in new:
                f.write(json.dumps(w, ensure_ascii=False) + "\n")
    log(f"held: {out['held']} held names, critical filings {out['filing_events']}, price moves {out['price_moves']}, not read {sorted(set(out['errors']))}")
    return out


# ---------------------------------------------------------------- 3. act
def filed_since(ticker, since, now, get=None, ciks=None):
    """(form, accession) of the stock's newest 8-K, 6-K or periodic report that became effective after `since` and by `now`, or None. The
    packet builder reads these forms (qwen_c.packet), so a re-read after one of them has something new to read."""
    get = get or (lambda url: G.sec_store.get(url, online=True))
    cik = (G._ciks([ticker]) if ciks is None else ciks).get(ticker)
    if not cik:
        raise ValueError("no CIK in cik_map.json")
    forms = tuple(G.P.EIGHT_K_FORMS) + ("6-K",) + tuple(G.P.PERIODIC_FORMS)
    rows = [r for r in G.P._filing_rows(json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json")))
            if r["form"] in forms and r["accepted"] is not None and since < r["effective"] <= now]
    best = max(rows, key=lambda r: (r["effective"], r["accession"]), default=None)
    return None if best is None else (best["form"], best["accession"])


def act(now=None, notify=None, enqueue=None, filed=None):
    """What follows a serious warning (operator ruling R2, 2026-11-25). (a) Each is told once, the day's lot in one Telegram message.
    (b) Its stock is queued for a re-read, at most REREADS_A_DAY stocks a day: stocks whose company has filed since the report was made
    first (filed_since: that re-read has a filing to read as well), then the worst direction. The re-read's reading is given the press
    reports as evidence (packet_with_news); its valuation reads filings only. A stock over the day's cap is taken on a later day, for
    REVIEW_DAYS days; one whose report was made after the warning, or that is already in a queue, is settled. Returns {told, queued,
    over_cap}.
    Held names (operator 2026-11-27, H2): a held stock whose warning is worse or unclear is queued ahead of every other stock, inside the
    same cap. The message leads with held stocks, marked HELD, and also tells a held stock's large price move (not serious: no re-read)."""
    now = now or datetime.now(timezone.utc)
    st = _read(STATE, {}) or {}
    told, settled = set(st.get("told") or []), set(st.get("settled") or [])
    day = today_utc(now)
    since = (now - timedelta(days=REVIEW_DAYS)).strftime("%Y-%m-%d")
    serious = [w for w in warnings_log() if w["serious"] and w["day"] >= since]
    reps = reports()
    mine = held(reps)
    order = {"worse": 0, "unclear": 1, "better": 2}
    enqueue, filed = enqueue or enqueue_reread, filed or filed_since
    lead = {}                                              # one candidate a stock: its worst open warning
    for w in sorted((w for w in serious if w["id"] not in settled), key=lambda w: (order[w["direction"]], w["day"], w["ticker"])):
        rep = reps.get(w["ticker"])
        if rep is None or G.decision_time(rep) > w["at"]:           # no report to redo, or it was redone after the warning
            settled.add(w["id"])
        else:
            lead.setdefault(w["ticker"], w)
    hits = {}
    for t, w in lead.items():
        try:
            hits[t] = filed(t, G._dt(G.decision_time(reps[t])), now)
        except Exception as e:  # noqa: BLE001  the SEC list could not be read: the stock is ranked as one that has not filed
            log(f"act {t}: {type(e).__name__}: {str(e)[:120]}")
            hits[t] = None
    used = sum(1 for d in (st.get("queued_days") or []) if d == day)
    out = {"told": 0, "queued": [], "over_cap": []}
    for t, w in sorted(lead.items(), key=lambda kv: (not (kv[0] in mine and kv[1]["direction"] != "better"), hits[kv[0]] is None,
                                                     order[kv[1]["direction"]], kv[1]["day"], kv[0])):
        if used + len(out["queued"]) >= REREADS_A_DAY:
            out["over_cap"].append(t)
            continue
        if enqueue(w, hits[t]):
            out["queued"].append(t)
        settled.update(x["id"] for x in serious if x["ticker"] == t)          # queued now, or already in a queue
    moves = [w for w in warnings_log() if w.get("kind") == "price_move" and w["day"] >= since and w["ticker"] in mine]
    fresh = sorted((w for w in serious + moves if w["id"] not in told),
                   key=lambda w: (w["ticker"] not in mine, not w["serious"], order[w["direction"]], w["day"], w["ticker"]))
    if fresh:
        first = {}                                          # one line a stock: its first (worst) warning, and how many more it has
        for w in fresh:
            first.setdefault(w["ticker"], (w, sum(x["ticker"] == w["ticker"] for x in fresh) - 1))
        n_serious, n_held = sum(w["serious"] for w in fresh), sum(t in mine for t in first)
        lines = [f"News watch {day}: {n_serious} serious warnings on {len({w['ticker'] for w in fresh if w['serious']})} stocks"
                 + (f"; {n_held} held stocks in this message" if n_held else "")] + [
            ("HELD " if t in mine else "") + f"{t} ({w['direction']}): {w['headline']} | {w['why']}" + (f" (+{more} more)" if more else "")
            for t, (w, more) in list(first.items())[:TELL_STOCKS]]
        if len(first) > TELL_STOCKS:
            lines.append(f"and {len(first) - TELL_STOCKS} more stocks (all are on the site)")
        if out["queued"]:
            lines.append("Re-read queued, with the press reports as evidence: " + ", ".join(out["queued"]))
        if out["over_cap"]:
            lines.append(f"Over today's cap of {REREADS_A_DAY}, taken on a later day: " + ", ".join(out["over_cap"]))
        if (notify or notify_telegram)("\n".join(lines)):
            told.update(w["id"] for w in fresh)
            out["told"] = len(fresh)
    week = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    _write(STATE, {**st, "told": sorted(told)[-5000:], "settled": sorted(settled)[-5000:],
                   "queued_days": [d for d in (st.get("queued_days") or []) if d >= week] + [day] * len(out["queued"])})
    log(f"act: {len(lead)} stocks with an open serious warning, told {out['told']}, queued {out['queued']}, over cap {out['over_cap']}")
    return out


def enqueue_reread(w, hit):
    """The stock into the worker's filing queue with the reason news:<day>:<warning id>, and :<form>:<accession> where the company has filed
    since its report (next_name takes it after operator requests); False where it already waits in a queue."""
    f = G.filing_queue_file()
    if any(q["ticker"] == w["ticker"] for q in Q._jsonl(f) + Q._jsonl(G.queue_file())):
        return False
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ticker": w["ticker"], "source": "news", "reason": f"news:{w['day']}:{w['id']}" + (f":{hit[0]}:{hit[1]}" if hit else ""),
                             "queued_at": Q.now_z()}) + "\n")
    return True


def notify_telegram(text):
    """The operations bot of the repository's main working tree (ops.notify_telegram: best effort, False when it is not set up)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("rs2_ops", G._main_checkout() / "ops.py")
    ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
    return ops.notify_telegram(text)


# ---------------------------------------------------------------- the track record
def track(now=None, prices=None):
    """Every warning with the closes around it, in track.json {warning id: {ticker, day, serious, direction, before, at, after_1, after_20,
    after_60}}: `before` the last close before the warning's day, `at` the close of that day (the first session on or after it), then the
    closes TRACK_SESSIONS sessions later, each None until that session has closed. Prices are the holdings monitor's (yf_prices: adjusted
    daily closes of completed sessions). A stock whose prices cannot be read is left for the next run. Nothing acts on this file."""
    prices = prices or M.yf_prices
    done = _read(TRACK, {}) or {}
    open_rows = [w for w in warnings_log() if any(done.get(w["id"], {}).get(f"after_{n}") is None for n in TRACK_SESSIONS)]
    closes = {}
    for w in open_rows:
        t = w["ticker"]
        if t not in closes:
            try:
                closes[t] = [(c["date"], c["close"]) for c in prices(t, now)["closes"]]
            except Exception as e:  # noqa: BLE001
                log(f"track {t}: {type(e).__name__}: {str(e)[:120]}")
                closes[t] = None
        if not closes[t]:
            continue
        cs = closes[t]
        i = next((k for k, (d, _) in enumerate(cs) if d >= w["day"]), None)
        row = {"ticker": t, "day": w["day"], "serious": w["serious"], "direction": w["direction"], "held": w.get("held"), "kind": w.get("kind", "news"),
               "before": cs[i - 1][1] if i else (cs[-1][1] if i is None else None), "at": None if i is None else cs[i][1]}
        for n in TRACK_SESSIONS:
            row[f"after_{n}"] = cs[i + n][1] if i is not None and i + n < len(cs) else None
        done[w["id"]] = row
    _write(TRACK, done)
    log(f"track: {len(open_rows)} warnings open, {len(done)} logged")
    return done


# ---------------------------------------------------------------- the re-read: press reports as evidence of the reading
def is_article(page, headline):
    """True when a fetched page reads as the report itself: ARTICLE_MIN characters or more, and at least half of the headline's longer
    words in it. A shell page (a site's name and nothing else) or another page is not the report (first live re-read, 2026-11-26)."""
    text = norm(page or "")
    words = {w for w in norm(headline).split() if len(w) >= 4}
    return len(text) >= ARTICLE_MIN and bool(words) and sum(w in text for w in words) * 2 >= len(words)


def evidence_rows(ticker, T, fetch=None, log_rows=None):
    """The press reports a re-read of `ticker` at decision time T is given: the lead report of each of the stock's warnings of the last
    KNOWN_WARNING_DAYS days (serious first, then newest; one row an address; EVIDENCE_ROWS at most), in qwen_c.news_packet's row shape.
    The text is the headline and the snippet the check read, then the article (`fetch(url, title)`, the holdings monitor's page reader)
    where the page reads as the report (is_article), EVIDENCE_CHARS in all; `text_from` says which. Returns (rows, warning ids)."""
    fetch = fetch or M.online_article
    day_T = str(T)[:10]
    cut = (datetime.strptime(day_T, "%Y-%m-%d") - timedelta(days=KNOWN_WARNING_DAYS)).strftime("%Y-%m-%d")
    mine = [w for w in (warnings_log() if log_rows is None else log_rows)
            if w["ticker"] == ticker and cut <= w["day"] <= day_T and w.get("url") and w.get("kind", "news") == "news"]
    mine.sort(key=lambda w: w["day"], reverse=True)
    mine.sort(key=lambda w: not w["serious"])
    rows, ids, seen = [], [], set()
    for w in mine:
        if w["url"] in seen or len(rows) == EVIDENCE_ROWS:
            continue
        seen.add(w["url"])
        snippet = next((r.get("snippet") or "" for r in ((_read(RAW / ticker / f"{w['day']}.json") or {}).get("rows") or []) if r.get("url") == w["url"]), "")
        try:
            page = fetch(w["url"], w["headline"])
        except Exception as e:  # noqa: BLE001  an unreadable page is the snippet's case, never a reason to drop the report
            log(f"evidence {ticker}: page not read ({type(e).__name__}: {str(e)[:100]})")
            page = None
        head = f"{w['headline']}. {snippet}".strip()
        page = page.strip() if is_article(page, w["headline"]) else ""
        text = (head + "\n\n" + page)[:EVIDENCE_CHARS] if page else head     # the headline and snippet the check read always lead
        rows.append({"title": w["headline"], "url": w["url"], "publisher": urllib.parse.urlparse(str(w["url"])).netloc.lower().removeprefix("www.") or w.get("source"),
                     "date": w["day"], "found_by": ["news_watch"], "text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                     "text_from": "article" if page else "headline_and_snippet"})
        ids.append(w["id"])
    return rows, ids


def packet_with_news(ticker, packet_path, fetch=None):
    """(the packet the READING of a news re-read is run on, what was added) for a stock's SEC packet: the same packet with the press reports
    of its warnings as items of kind news (qwen_c.news_packet.add_news: ids N1.., their own text budget, the SEC items untouched), saved
    beside the SEC packets. The valuation is run on the SEC packet as before; it refuses a packet that holds news. With no report to add,
    or when the news packet is refused, this is (packet_path, None) and the re-read is an ordinary one."""
    from qwen_c import news_packet
    pk = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    rows, ids = evidence_rows(ticker, pk["decision_time_utc"], fetch)
    if not rows:
        return str(packet_path), None
    obj = {"ticker": ticker, "T": pk["decision_time_utc"], "rows": rows}
    raw = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
    f = NEWS / "evidence" / f"{ticker}_{G.runner.t_compact(pk['decision_time_utc'])}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(raw)
    try:
        out = news_packet.add_news(pk, obj, hashlib.sha256(raw).hexdigest())
        path = G.P.save(out, news_packet.NEWS_DIR)
    except Exception as e:  # noqa: BLE001  PacketRefused and PacketError: the re-read goes on without the news
        log(f"evidence {ticker}: news packet refused ({type(e).__name__}: {str(e)[:160]})")
        return str(packet_path), None
    return str(path), {"warnings": ids, "rows": out["news"]["rows_used"], "rows_left_out": out["news"]["rows_left_out"],
                       "text_from": [r["text_from"] for r in rows], "evidence_file": f.name}


def without_news_claims(analysis):
    """A reading with every claim that cites a news item (a fact id N<number>) left out: what the valuation is given as the earlier
    read, so that a press report never reaches the valuation, which reads filings only."""
    out = json.loads(json.dumps(analysis or {}))
    for t in (out.get("tasks") or {}).values():
        if isinstance(t, dict) and isinstance(t.get("claims"), list):
            t["claims"] = [c for c in t["claims"] if not any(re.fullmatch(r"N\d+", str(i)) for i in (c.get("fact_ids") or []))]
    return out


def backup(dest=None):
    """The record that cannot be made again (the warnings, the track record, what was told and queued) copied to the private state
    repository's paper_books/news_watch, which sync_state carries and commits. The gathered headlines and check files stay here."""
    import shutil
    dest = dest or Q.book_paths.books() / "news_watch"
    dest.mkdir(parents=True, exist_ok=True)
    done = []
    for f in (WARNINGS, TRACK, STATE):
        if f.exists():
            shutil.copyfile(f, dest / f.name)
            done.append(f.name)
    log(f"backup: {done} to {dest.name}")
    return done


# ---------------------------------------------------------------- the site's fields
def for_site(report, log_rows, now=None):
    """(news, under_review) of one report. news: the stock's warnings of the last SHOW_DAYS days, newest first. under_review: its newest
    serious warning of the last REVIEW_DAYS days raised after the report was made (after its packet's decision time), else None: the mark
    goes when the stock is read again, which act() does once the company has filed."""
    now = now or datetime.now(timezone.utc)
    day = lambda n: (now - timedelta(days=n)).strftime("%Y-%m-%d")  # noqa: E731
    mine = sorted((w for w in log_rows if w["ticker"] == report.get("ticker")), key=lambda w: (w["day"], w["at"]), reverse=True)
    show = [{k: w[k] for k in ("id", "day", "serious", "direction", "new_matter", "why", "quote", "touches", "headline", "url", "source", "outlets")}
            for w in mine if w["day"] >= day(SHOW_DAYS)]
    made = G.decision_time(report) if report.get("date") else ""
    review = next((w for w in mine if w["serious"] and w["day"] >= day(REVIEW_DAYS) and w["at"] > made), None)
    return show, (None if review is None else {"since": review["day"], "headline": review["headline"], "why": review["why"], "id": review["id"]})


# ---------------------------------------------------------------- the morning
def take_lock():
    import formation_run as FR
    if LOCK.exists():
        try:
            if FR.pid_alive(int(LOCK.read_text().strip())):
                return False
        except ValueError:
            pass
    NEWS.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))
    return True


def morning(limit=None):
    """gather, check, act, then the site files (the worker publishes too; the shared publish lock keeps the two apart). The marker keeps
    Docker (SearXNG) up while the gather runs (tools/b2_recall/docker_window.ps1 -Stop waits for it)."""
    if not take_lock():
        print("another news watch holds the lock", flush=True)
        return 0
    marker = G._main_checkout() / "cache" / "monitor_gather.running"
    try:
        try:
            g = gather(limit, marker=marker)
        finally:
            marker.unlink(missing_ok=True)
        check(limit)
        try:
            held_signals()
        except Exception as e:  # noqa: BLE001  the code signals are an addition: their failure stops neither the telling nor the re-reads
            log(f"held signals failed: {type(e).__name__}: {str(e)[:160]}")
        act()
        try:
            track()
            backup()
        except Exception as e:  # noqa: BLE001  the track record is a log and the backup a copy; their failure stops nothing
            log(f"track or backup failed: {type(e).__name__}: {str(e)[:160]}")
        try:
            G.publish()
        except (SystemExit, Exception) as e:  # noqa: BLE001  the worker's next publish carries the warnings
            log(f"publish failed: {e}")
        return 2 if g["stocks"] and len(g["errors"]) > g["stocks"] / 5 else 0      # a starved gather fails loudly
    finally:
        if LOCK.exists() and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()


def status():
    rows = warnings_log()
    days = sorted({p.stem for p in RAW.glob("*/*.json")}) if RAW.exists() else []
    print(f"reader {READER} | watched {len(reports())} | gather days {len(days)} (last {days[-1] if days else None}) | "
          f"warnings {len(rows)} ({sum(w['serious'] for w in rows)} serious)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("gather", "check", "act", "track", "backup", "morning", "status"))
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.cmd == "gather":
        r = gather(a.limit)
        sys.exit(2 if r["stocks"] and len(r["errors"]) > r["stocks"] / 5 else 0)
    elif a.cmd == "check":
        check(a.limit)
    elif a.cmd == "act":
        act()
    elif a.cmd == "track":
        track()
    elif a.cmd == "backup":
        backup()
    elif a.cmd == "morning":
        sys.exit(morning(a.limit))
    else:
        status()
