"""daily_report.py - one Telegram message a day (operator, 2026-11-28): did every job run, how the AI book stands, what it bought and sold.

  python tools/site/daily_report.py send      the day's message (task RS2-Daily-Report, 14:00 local, after the site's post-close run)
  python tools/site/daily_report.py show      the same text printed, nothing sent, nothing recorded

JOBS. Every scheduled task of this workspace that is not disabled (names RS2-... and MRI-...) is read from the Windows scheduler: a last
run that ended in an error and a next run that is overdue are problems. A task that ends well may still have done nothing, so three results
are checked as well: the news watch's log has today's gather and act lines, the site worker's log has a line in the last hour, and on the
days after a US session (Tuesday to Saturday here) the site's paper ledgers were written today after noon. This message cannot be sent when
the computer is off: its absence is then the alert.

AI BOOK. Read from the live site's paper_ledgers.json (the publish clone's origin/main, fetched and read, never checked out): the ledger
`ai_book` of stock-screener's track_paper_portfolios.py, which is the only owner of the book. Its value is an index (100 at the start), so
profit and loss are per cent. Beside it stand the lines the operator reads it against (2026-11-27): 60/40, QQQ, SPY, IWM, DRAM, SOXL, over
the same sessions. 60/40 is 60% SPY and 40% AGG set back at every close, the same arithmetic as the site's lib/desk/nav.ts. The trades of
the newest session are named. A session already reported is not reported twice. Nothing here trades, and nothing here is advice."""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import gemini_ondemand as G  # noqa: E402
import news_watch  # noqa: E402
import paths  # noqa: E402

OWN_TASK = "RS2-Daily-Report"
TASK_PREFIXES = ("RS2-", "MRI-")
OK_RESULTS = {0, 267009, 267011}          # ended well; still running; never run yet
OVERDUE = timedelta(minutes=15)
WORKER_QUIET = timedelta(minutes=60)      # the worker's task starts every 15 minutes and logs each pass
LEDGER = "public/data/paper_ledgers.json"
BOOK = "ai_book"
LINES = ("60/40", "QQQ", "SPY", "IWM", "DRAM", "SOXL")
NAMES_SHOWN = 40
STATE = G.SITE / "daily_report.json"


# ---------------------------------------------------------------- jobs

def scheduled_tasks():
    """[{name, state, last, result, next}] of the workspace's tasks that are not disabled; times are local ISO strings or None."""
    ps = ("Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' } | ForEach-Object { $i = $_ | Get-ScheduledTaskInfo; "
          "[pscustomobject]@{ name = $_.TaskName; state = [string]$_.State; result = $i.LastTaskResult; "
          "last = $(if ($i.LastRunTime) { $i.LastRunTime.ToString('s') }); next = $(if ($i.NextRunTime) { $i.NextRunTime.ToString('s') }) } } "
          "| ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120, check=True).stdout
    rows = json.loads(out) if out.strip() else []
    rows = [rows] if isinstance(rows, dict) else rows
    return [r for r in rows if r["name"].startswith(TASK_PREFIXES) and r["name"] != OWN_TASK]


def task_problems(tasks, now):
    """One line for each task whose last run ended in an error or whose next run is overdue. A task that is running is neither."""
    out = []
    for t in sorted(tasks, key=lambda t: t["name"]):
        if t["state"] == "Running":
            continue
        if t["result"] not in OK_RESULTS:
            out.append(f"{t['name']}: last run ({t['last']}) ended with error code {t['result']}")
        elif t["next"] and datetime.fromisoformat(t["next"]) < now.replace(tzinfo=None) - OVERDUE:
            out.append(f"{t['name']}: did not start at {t['next']}")
    return out


def _stamps(path, since):
    """The log's lines stamped at or after `since` (lines start with a local ISO time)."""
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line[:19] >= since]


def result_problems(now, news_log, worker_log, ledger_written):
    """The three results a task's exit code does not show. `ledger_written`: the ledgers' last_updated (UTC ISO), or None when not read."""
    out, day = [], now.strftime("%Y-%m-%d")
    today = _stamps(news_log, day)
    if not any(" gather " in line for line in today) or not any(" act: " in line for line in today):
        out.append("news watch: today's log has no gather and act lines")
    if not _stamps(worker_log, (now - WORKER_QUIET).strftime("%Y-%m-%dT%H:%M:%S")):
        out.append("site worker: no log line in the last hour")
    if ledger_written is None:
        out.append("site: the paper ledgers could not be read")
    elif now.weekday() in (1, 2, 3, 4, 5):                      # Tuesday to Saturday here: the day after a US weekday
        noon = now.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        if datetime.fromisoformat(ledger_written.replace("Z", "+00:00")) < noon:
            out.append(f"site: the paper ledgers were not written after today's close run (last {ledger_written})")
    return out


# ---------------------------------------------------------------- the book

def read_ledgers():
    """The live site's paper ledgers, or None. The clone is fetched and read; its working files are not touched."""
    repo = paths.resolve("screener_publish_repo")
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, timeout=120)  # noqa: E731
    try:
        g("fetch", "origin", "main")
        return json.loads(g("show", f"origin/main:{LEDGER}").stdout.decode("utf-8"))
    except Exception:  # noqa: BLE001  the report says it could not be read
        return None


def sixty_forty(rows):
    """{date: value}: 60% SPY and 40% AGG set back at every close, 100 at the first day both have a close; a day missing either is skipped
    (as lib/desk/nav.ts sixtyForty in stock-screener)."""
    out, prev, value = {}, None, 100.0
    for r in rows:
        spy, agg = (r.get("benches") or {}).get("SPY"), (r.get("benches") or {}).get("AGG")
        if spy is None or agg is None:
            continue
        if prev:
            value *= 1 + 0.6 * (spy / prev[0] - 1) + 0.4 * (agg / prev[1] - 1)
        prev = (spy, agg)
        out[r["date"]] = value
    return out


def _pct(a, b):
    return None if a is None or b is None or b == 0 else (a / b - 1) * 100


def _f(x):
    return "n/a" if x is None else f"{x:+.2f}%"


def book_lines(book, last_reported=None):
    """(lines, session): the AI book's part of the message. session is the newest session's date, None when the book has no row yet."""
    nav = [r for r in (book or {}).get("nav_series") or [] if r.get("nav") is not None]
    if not nav:
        return ["AI BOOK: no row yet (it starts at the first close run after it was added)."], None
    first, last, prev = nav[0], nav[-1], (nav[-2] if len(nav) > 1 else None)
    session = last["date"]
    head = f"Value {last['nav']:.2f}: since start ({first['date']}) {_f(_pct(last['nav'], 100.0))}"
    if session == last_reported:
        return [f"AI BOOK: no new session since {session}. {head}."], session
    hold = (book.get("state") or {}).get("holdings") or {}
    cash = (book.get("state") or {}).get("cash")
    out = [f"AI BOOK, session {session} (day {len(nav)})",
           f"{head}; day {_f(_pct(last['nav'], prev['nav']) if prev else None)}",
           f"Holds {len(hold)} stocks" + ("" if cash is None else f", cash {cash / last['nav'] * 100:.1f}% of value")]
    mix = sixty_forty(nav)
    for name in LINES:
        v = (lambda r: mix.get(r["date"])) if name == "60/40" else (lambda r: (r.get("benches") or {}).get(name))
        out.append(f"  {name}: since start {_f(_pct(v(last), v(first)))}; day {_f(_pct(v(last), v(prev)) if prev else None)}")
    trades = [t for t in book.get("trades") or [] if t.get("date") == session]
    for side, word in (("buy", "Bought"), ("sell", "Sold")):
        names = sorted(t["ticker"] for t in trades if t.get("side") == side)
        more = f" and {len(names) - NAMES_SHOWN} more" if len(names) > NAMES_SHOWN else ""
        out.append(f"{word} ({len(names)}): " + (", ".join(names[:NAMES_SHOWN]) + more if names else "none"))
    marks = book.get("last_marks") or {}
    moves = sorted(((_pct(marks.get(t), h.get("entry_price")), t) for t, h in hold.items() if _pct(marks.get(t), h.get("entry_price")) is not None))
    if len(moves) >= 6 and any(m for m, _ in moves):
        out.append("Best since entry: " + ", ".join(f"{t} {_f(m)}" for m, t in reversed(moves[-3:])))
        out.append("Worst since entry: " + ", ".join(f"{t} {_f(m)}" for m, t in moves[:3]))
    return out, session


# ---------------------------------------------------------------- the message

def compose(now, tasks, ledgers, last_reported=None, news_log=None, worker_log=None):
    """(text, session). `tasks` None: the scheduler could not be read, which is itself a problem."""
    problems = ["the Windows scheduler could not be read"] if tasks is None else task_problems(tasks, now)
    problems += result_problems(now, news_log or news_watch.NEWS / "log", worker_log or G.LOG, (ledgers or {}).get("last_updated"))
    lines = [f"Daily report {now.strftime('%Y-%m-%d %H:%M')}"]
    if problems:
        lines += [f"JOBS: {len(problems)} PROBLEM{'S' if len(problems) > 1 else ''}"] + [f"- {p}" for p in problems]
    else:
        lines.append(f"JOBS: all ran ({len(tasks)} scheduled jobs, news watch, site worker, site close run).")
    book, session = book_lines(((ledgers or {}).get("ledgers") or {}).get(BOOK), last_reported)
    return "\n".join(lines + [""] + book), session


def main(send):
    now = datetime.now().astimezone()
    try:
        tasks = scheduled_tasks()
    except Exception:  # noqa: BLE001  said in the message
        tasks = None
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    text, session = compose(now, tasks, read_ledgers(), state.get("session"))
    print(text, flush=True)
    if send:
        ok = news_watch.notify_telegram(text)
        print("sent" if ok else "NOT SENT", flush=True)
        if ok:
            STATE.write_text(json.dumps({"session": session, "sent_at": now.isoformat(timespec="seconds")}), encoding="utf-8")
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("send", "show"):
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1] == "send"))
