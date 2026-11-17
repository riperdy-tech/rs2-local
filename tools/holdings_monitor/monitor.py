"""monitor.py - the 3P thesis monitor without the GPU (WO_P2; SPEC_m3p_monitoring.md sections 1-3, 5 and 6).

Paper only. Monitoring never sells. This file decides WHAT to analyse and in WHAT ORDER, and it records what came back. It
never runs a model: a queue entry waits for WO_P3, and `resolve(run_dir)` reads a finished qwen_c run afterwards.

    members(books, newest_book, restricted, today, last_seen)   the monitored set (SPEC 1), with the 30-day tail
    gather_name(...)                                            one name's gather since its last gather (SPEC 2), no writes
    price_signal(closes)                                        the price trigger
    Monitor(root).run_day(...)                                  members -> gather -> triggers -> queue -> 14-day refresh
    Monitor(root).resolve(run_dir)                              a finished run -> name state, thesis points, Q1 verdict, carry rule
    Monitor(root).report(now)                                   coverage, queue age, and the pending_review / stale_analysis flags
    run_pass(root, ...)                                         WO_P3b1: the executor. Queue entries in order -> packet -> qwen_c -> resolve
                                                                (`python tools/holdings_monitor/monitor.py run [--limit N] [--dry-run]`; tested with stubs only)

DESIGN VALUES (not tuned; SPEC section 9 says so): the price trigger is a one-session log return of at least 3 standard deviations of
the 60 daily log returns before it, or a move of at least 20% over 5 sessions. The 14-day refresh, the 21-day and two-run carry
limit and the 30-day tail are the spec's own numbers.

FILES (all under the monitor's root, `<rs2_state_dir>/paper_books/monitor/` by default: tools/paper_books/book_paths.py)
    state/monitor.json         the one core record: queue, name states, run keys, the monitored set's last-seen dates and the OUTBOX
    state/gather_<CIK>.json    one gather record per CIK (seen filings and headlines, news rows with article text, closes), committed after its triggers are queued
    news/<ticker>_<T>.json     the news rows one packet is built with (written by the executor, passed to the packet builder as --news-file)
    state/monitor.lock         single instance; a lock whose pid is dead is taken over
    journal.jsonl              append-only, one line per lifecycle step: discovered, queued, analysed, resolved, failed

CRASH SAFETY. Every change to the core record that has journal lines is ONE atomic write (tmp + replace) that also carries the lines in
`outbox`. Writing the outbox to the journal and then clearing it are the later steps. Each journal line has an `event_id`; a line whose
id is already in the journal is not written again. So a crash anywhere replays the outbox once: no entry is lost and no line is doubled.
The gather record of a name is committed only AFTER its triggers are in the queue; a crash between the two re-finds the same filings,
and the same trigger id is absorbed (a trigger already in the queue, or already handled, adds nothing).
"""
import argparse
import ctypes
import hashlib
import html
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                                                # the rs2-local repo root (the qwen_c run worktree)
sys.path.insert(0, str(HERE.parent / "paper_books"))
import book_paths  # noqa: E402  (where the books live: paths.py rs2_state_dir)
import baseline_b  # noqa: E402  (the 3N deterministic rules; PREREG sha checked inside)

MONITOR_ROOT = book_paths.books() / "monitor"                         # state, journal and locks: data in rs2-state, not in this repository

# ---------------------------------------------------------------- constants (the spec's numbers unless marked DESIGN)

EXCLUDED = frozenset(book_paths.operator_excluded())          # operator exclusion: never monitored (data in rs2-state, never code)
TAIL_DAYS = 30                                                # SPEC 1: a name leaves 30 days after it leaves every group
REFRESH_DAYS = 14                                             # SPEC 3 P4 / ruling 3
STALE_DAYS = 21                                               # SPEC 5 carry limit (ruling 6)
MAX_UNUSABLE = 2                                              # SPEC 5: two unusable runs in a row
MAX_ATTEMPTS = 2                                              # a failed run's entry is run once more (SPEC 5), then dropped
FIRST_GATHER_DAYS = 7                                         # DESIGN: a name's first gather reports filings accepted this recently
BATCH, PAUSE_S = 26, 600                                      # B2's pacing (RR_P1): names per batch, seconds between batches
SEEN_KEEP_DAYS = 45                                           # P6.6 seen-set pruning
HANDLED_KEEP_DAYS = 90
KEEP_CLOSES = 130
PRICE_SIGMAS = 3.0                                            # DESIGN
PRICE_SIGMA_WINDOW = 60                                       # DESIGN: daily log returns before the latest session
PRICE_MOVE = 0.20                                             # DESIGN
PRICE_MOVE_SESSIONS = 5                                       # DESIGN
FILING_TEXT_CHARS = 3_000_000
HEAD_CHARS = 3000
CRASH_MIN_AGE_HOURS = 6                                       # DESIGN: a `running` run younger than this is in progress, not crashed (a full run takes about 12 minutes)
NEWS_TEXT_ROWS = 5                                            # DESIGN: new news rows whose article text is fetched per gather (category-found rows first, then newest)
NEWS_TEXT_CHARS = 6_000                                       # DESIGN: characters of article text kept on a row
NEWS_PACKET_ROWS = 8                                          # DESIGN: news rows handed to one packet (newest first)
NEWS_PACKET_DAYS = 7                                          # DESIGN: a packet takes news from this many days before T
NEWS_STALE_REASONS = frozenset({"occurred_outside_window", "occurred_on_after_T", "unknown_status"})   # DESIGN: m3o_engine.q1 reasons that keep a press-report claim from acting

P0_ITEMS = frozenset({"1.02", "1.03", "2.04", "2.06", "3.01", "4.01", "4.02"})
EARNINGS_ITEMS = frozenset({"2.02"})
PERIODIC = frozenset({"10-K", "10-Q", "20-F", "40-F"})        # 20-F / 40-F: annual reports of foreign filers, read as a 10-K (open choice)
ITEM_FORMS = frozenset({"8-K", "6-K"})
# PREREG_m3o.json rules.Q1.event_types, copied (a test compares this with the file)
Q1_EVENT_CLASS = {"bankruptcy_or_restructuring": "C1", "going_concern_doubt": "C2", "restatement_or_non_reliance": "C3",
                  "delisting_notice": "C4", "acquisition_of_the_company": "C5", "contract_loss": "C6",
                  "guidance_withdrawal": "C7", "debt_default_or_acceleration": "C8"}

NY = ZoneInfo("America/New_York")
SEC_BASE = "https://data.sec.gov"
WWW_SEC = "https://www.sec.gov"
SEARX_URL = "http://localhost:8888"


class MonitorError(Exception):
    pass


class SecContactMissing(MonitorError):
    """SEC_USER_AGENT is not set to a name and an email: nothing is sent to SEC."""


class LockHeld(MonitorError):
    pass


class ResolveRefused(MonitorError):
    pass


# ---------------------------------------------------------------- small helpers

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def utc(dt=None):
    dt = dt or datetime.now(timezone.utc)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def iso(dt):
    return utc(dt).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s):
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def accepted_at(value):
    """SEC acceptanceDateTime as UTC, read as qwen_c packet.py and m3o_engine read it: a Z-labelled clock has been seen both as UTC and as
    Eastern wall clock mislabelled Z, so the LATER reading is used; a naive clock is Eastern. A copy of that rule (no cross-import)."""
    if not isinstance(value, str) or not value:
        raise ValueError("acceptanceDateTime missing")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=NY).astimezone(timezone.utc)
    as_utc = dt.astimezone(timezone.utc)
    as_wall = dt.replace(tzinfo=None).replace(tzinfo=NY).astimezone(timezone.utc)
    return max(as_utc, as_wall)


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def write_json_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


# ---------------------------------------------------------------- text leaf functions copied from P6.6 (followup_gather.py @ 23e41c4)

_PRESS_TAIL = frozenset({"and", "&", "the", "inc", "corp", "corporation", "co", "company", "companies", "plc", "ltd", "llc", "lp", "sa",
                         "nv", "ag", "se", "holdings", "holding", "group", "limited", "sab", "de", "cv"})
_GENERIC_NAME_WORDS = {
    "advanced", "american", "united", "general", "first", "national", "international", "global", "holdings", "holding", "group",
    "technology", "technologies", "systems", "energy", "mining", "resources", "company", "corporation", "the", "and", "new", "north",
    "south", "east", "west"}
LOW_TRUST = ("pitchgrade.com", "stocksentinel", "zacks.com/stock/chart", "marketbeat.com", "simplywall.st",
             "investing.com/news/stock-market-news")
NEWS_QUERIES = (
    ("w_name", '"{p}"', None),
    ("w_litigation", '"{p}" (court OR judge OR jury OR ruling OR settlement OR fine)', "bing news"),
    ("w_regulatory", '"{p}" (approval OR approves OR regulator OR FDA OR clearance OR rejected)', "bing news"),
    ("w_policy", '"{p}" (government OR tariff OR license OR licence OR subsidy OR ban)', "bing news"),
    ("w_contract", '"{p}" (contract OR awarded OR agreement OR deal)', "bing news"),
    ("w_competition", '"{p}" (competitor OR rival OR entrant OR "price cut" OR "market share" OR launches)', "bing news"),
)
CATEGORY_KEYS = frozenset(key for key, _, _ in NEWS_QUERIES if key != "w_name")   # a row found by any of these is a category row


def normalize_title(title):
    """The key a headline is compared on: NFKC, lower case, non-alphanumerics -> one space, stripped."""
    return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", str(title)).lower()).strip()


def normalize_url(url):
    """Scheme and host lower case, trailing slash stripped (catalyst_research.normalize_url)."""
    if not url:
        return ""
    try:
        p = urllib.parse.urlparse(str(url).strip())
        return urllib.parse.urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.params, p.query, p.fragment))
    except ValueError:
        return str(url).strip().rstrip("/")


def clean_company_name(company, ticker):
    s = str(company or "").strip()
    cleaned = re.sub(r",?\s*(?:Inc\.?|Corp\.?|Corporation|Co\.?|Company|LLC|Plc|Ltd\.?)\s*$", "", s, flags=re.I).strip()
    return cleaned if cleaned else (s or str(ticker).upper())


def name_token(clean_company):
    """The first distinctive word of the company name (>= 4 letters, not generic)."""
    for w in re.findall(r"[A-Za-z][A-Za-z&'-]+", clean_company or ""):
        if len(w) >= 4 and w.lower() not in _GENERIC_NAME_WORDS:
            return w
    return None


def press_name(company, ticker):
    """The name the press uses for a company (followup_gather.press_name): the cleaned name less trailing legal and generic words."""
    cleaned = clean_company_name(company, ticker)
    words = re.sub(r"(?i)\.com$", "", cleaned).replace(",", " ").split()
    while len(words) > 1 and words[-1].replace(".", "").lower() in _PRESS_TAIL:
        words.pop()
    press = " ".join(words)
    return press if name_token(press) else cleaned


def distinctive_word(company, ticker):
    press = press_name(company, ticker)
    return name_token(press) or press


def _word_pattern(word):
    return re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)", re.I)


def clean_html(raw):
    """sec_guidance._clean_html: scripts, styles, comments and tags removed, entities unescaped, whitespace collapsed."""
    text = re.sub(r"(?is)<script\b.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- the online SEC / SearXNG functions (never called by the tests)

def sec_headers():
    """The User-Agent SEC requires, from the SEC_USER_AGENT environment variable, read now. Refuses when it is unset or has no email."""
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in ua:
        raise SecContactMissing("SEC_USER_AGENT must be set to your name and email (e.g. 'Jane Doe jane@example.com'); "
                                "SEC refuses requests without a contact and nothing was sent")
    return {"User-Agent": ua}


def sec_get(url):
    """One document from EDGAR: the declared User-Agent, a 60 s timeout, a pause after (SEC asks for under 10 requests a second)."""
    req = urllib.request.Request(url, headers=sec_headers())
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", "replace")
    time.sleep(0.2)
    return raw


def online_submissions(cik):
    return json.loads(sec_get(f"{SEC_BASE}/submissions/CIK{int(cik):010d}.json"))


def online_filing_text(cik, accession, primary_document=None, form=None):
    """The readable text of one filing from its full submission .txt (followup_gather.filing_texts): the main document of the form's
    family, and for 8-K / 6-K every EX-99* exhibit, cleaned and joined. None when the fetch fails or nothing is readable."""
    sec_headers()                                                       # refuse before anything else
    url = f"{WWW_SEC}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}.txt"
    try:
        raw = sec_get(url)
    except SecContactMissing:
        raise
    except Exception:  # noqa: BLE001 - a failed fetch is an annotation, not a crash
        return None
    docs = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", raw, flags=re.DOTALL | re.IGNORECASE) or re.split(r"(?i)<DOCUMENT>", raw)[1:]
    base = (form or "").upper().removesuffix("/A")
    main, exhibits = None, []
    for doc in docs:
        m = re.search(r"<TYPE>\s*([^\r\n<]+)", doc, flags=re.IGNORECASE)
        if not m:
            continue
        kind = m.group(1).strip().upper()
        body = re.search(r"<TEXT>(.*?)</TEXT>", doc, flags=re.DOTALL | re.IGNORECASE)
        text = clean_html(body.group(1) if body else doc)
        if main is None and (kind.removesuffix("/A") == base or (not base and kind in ITEM_FORMS | PERIODIC)):
            main = text
        elif kind.startswith("EX-99") and base in ITEM_FORMS:
            exhibits.append(text)
    joined = "\n\n".join(t for t in ([main] if main else []) + exhibits if t)
    return joined[:FILING_TEXT_CHARS] if joined else None


def online_article(url, title):
    """The plain text of one news page through the reader `main` already owns (analyst_tools.fetch_page, as company_news._read_article calls
    it: the headline is the known title, so a blocked page falls back to a free copy), or None when the page is unreadable. The whole page
    text comes back (the caller keeps NEWS_TEXT_CHARS of it)."""
    sys.path.insert(0, str(ROOT / "tools" / "audit_202608"))
    import analyst_tools
    res = analyst_tools.fetch_page(url, cap=FILING_TEXT_CHARS, known_urls={url: title})
    if not isinstance(res, dict) or res.get("error"):
        return None
    text = str(res.get("text") or "").strip()
    return text or None


def searx_news(company, ticker, today, endpoint=SEARX_URL, get_json=None, pause_s=1.0, sleep=time.sleep):
    """The news of the last week from SearXNG (followup_news, P6.6): the NEWS_QUERIES, rows with a title and address, the issuer's distinctive
    word in title or text, low-trust addresses dropped. Rows {date, source, title, url, snippet, found_by}; a row several queries returned
    is one row and `found_by` lists every NEWS_QUERIES key that returned it. Raises on a total failure."""
    def default_get(url):
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    get = get_json or default_get
    press = press_name(company, ticker)
    pattern = _word_pattern(name_token(press) or press)
    rows, by_key, errors = [], {}, []
    for i, (key, template, engines) in enumerate(NEWS_QUERIES):
        params = {"q": template.format(p=press), "time_range": "week", "format": "json"}
        params.update({"engines": engines} if engines else {"categories": "news"})
        if i:
            sleep(pause_s)
        try:
            data = get(f"{endpoint}/search?" + urllib.parse.urlencode(params))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{key}: {type(e).__name__}: {str(e)[:100]}")
            continue
        for res in data.get("results") or []:
            url = str(res.get("url") or "").strip()
            title = re.sub(r"\s+", " ", str(res.get("title") or "")).strip()[:150]
            content = re.sub(r"\s+", " ", str(res.get("content") or "")).strip()
            if not url or not title or any(bad in url for bad in LOW_TRUST) or not pattern.search(title + " " + content):
                continue
            k = (normalize_title(title), normalize_url(url))
            hit = by_key[k[0]] if k[0] in by_key else by_key.get(k[1])
            if hit is not None:
                if key not in hit["found_by"]:
                    hit["found_by"].append(key)
                continue
            m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(res.get("publishedDate") or "").strip())
            row = {"date": m.group(1) if m else None, "source": str(res.get("engine") or ""), "title": title, "url": url,
                   "snippet": content[:420], "found_by": [key]}
            by_key[k[0]] = by_key[k[1]] = row
            rows.append(row)
    if errors and len(errors) == len(NEWS_QUERIES):
        raise MonitorError("every news query failed: " + "; ".join(errors[:2]))
    return rows


def load_ticker_map(path):
    """{ticker: {"cik", "company"}} from SEC's company_tickers.json ({"0": {"cik_str", "ticker", "title"}, ...})."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {v["ticker"].upper(): {"cik": int(v["cik_str"]), "company": v["title"]} for v in raw.values()}


def newest_book_from_formations(path):
    """(formation_T, [tickers]) of the newest line of m3l_forward/formations.jsonl."""
    best = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if best is None or rec["formation_T"] > best["formation_T"]:
                best = rec
    if best is None:
        raise MonitorError(f"{path} holds no formation")
    return best["formation_T"], list(best["book"])


# ---------------------------------------------------------------- 1. the monitored set

def members(books, newest_book, restricted, today, last_seen=None):
    """The monitored set of SPEC 1 and each name's reasons: (members, last_seen).

    books        {arm: [tickers]}  the names each SPEC_m3o arm (F, FB, FQ, ...) holds now
    newest_book  [tickers]         the newest A0 book
    restricted   {ticker: rule} or [tickers]   the names restricted (B1 / Q1) at the newest formation
    today        a date
    last_seen    {ticker: ISO date} the last day each name was in one of the three groups (returned updated; pass the stored one)

    A name that leaves every group stays a member for TAIL_DAYS (30) days (open choice: the 30th day after is still in, the 31st is out).
    Tickers in EXCLUDED are never members. members[ticker] = {"reasons": [...], "held": bool, "tail": bool, "last_in": ISO date}.
    """
    today = as_date(today)
    last_seen = dict(last_seen or {})
    reasons = {}
    for arm, names in sorted((books or {}).items()):
        for t in names or []:
            reasons.setdefault(t, set()).add(f"held:{arm}")
    for t in newest_book or []:
        reasons.setdefault(t, set()).add("newest_book")
    rmap = restricted if isinstance(restricted, dict) else {t: "restricted" for t in restricted or []}
    for t, rule in rmap.items():
        reasons.setdefault(t, set()).add(f"restricted:{rule}")
    out = {}
    for t, why in reasons.items():
        if t in EXCLUDED:
            continue
        last_seen[t] = today.isoformat()
        out[t] = {"reasons": sorted(why), "held": any(r.startswith("held:") for r in why), "tail": False, "last_in": today.isoformat()}
    for t in list(last_seen):
        if t in EXCLUDED:
            del last_seen[t]
        elif t not in out:
            days = (today - as_date(last_seen[t])).days
            if days <= TAIL_DAYS:
                out[t] = {"reasons": ["tail"], "held": False, "tail": True, "last_in": last_seen[t]}
            else:
                del last_seen[t]
    return out, last_seen


# ---------------------------------------------------------------- 2. the gather (pure: reads its inputs, writes nothing)

@dataclass
class Sources:
    """The injected data sources. submissions(cik) -> SEC submissions JSON; filing_text(cik, accession, primary_document, form) -> str or
    None; prices(ticker) -> {"source", "quote_date", "closes": [{"date", "close"}]}; news(company, ticker, today) -> [row];
    article(url, title) -> the plain text of the page, or None. None means the source is not used (and that is recorded in the gather's
    errors)."""
    submissions: object = None
    filing_text: object = None
    prices: object = None
    news: object = None
    article: object = None


def parse_submissions(sub, cik):
    """The filings of the issuer's own CIK from its submissions JSON (filings.recent). Refuses a feed for another CIK."""
    got = str(sub.get("cik", "")).lstrip("0")
    if got != str(int(cik)):
        raise MonitorError(f"submissions feed is for CIK {got or '?'}, not {int(cik)}: not ingested")
    rec = (sub.get("filings") or {}).get("recent") or {}
    cols = {k: rec.get(k) or [] for k in ("accessionNumber", "form", "filingDate", "acceptanceDateTime", "primaryDocument", "items",
                                          "reportDate")}
    out = []
    for i, acc in enumerate(cols["accessionNumber"]):
        def col(k, i=i):
            v = cols[k]
            return v[i] if i < len(v) else None
        raw, items = col("acceptanceDateTime"), col("items") or ""
        try:
            acc_utc = accepted_at(raw)
        except (ValueError, TypeError):
            acc_utc = None
        out.append({"accession": acc, "form": col("form") or "", "filing_date": col("filingDate"), "accepted_raw": raw,
                    "accepted_utc": iso(acc_utc) if acc_utc else None, "primary_document": col("primaryDocument"),
                    "items": [x.strip() for x in str(items).split(",") if x.strip()], "report_date": col("reportDate")})
    return out


def collected(form):
    """Whether the form is gathered: 8-K and 6-K, 10-K, 10-Q, 20-F, 40-F, their amendments, and every NT notice (SPEC 2.1)."""
    base = form.upper().removesuffix("/A")
    return base in ITEM_FORMS or base in PERIODIC or base.startswith("NT ")


def filing_level(f, hits):
    """(level, reasons) of one new filing: 0 critical, 2 periodic or earnings, 3 other. The priority a name gets from the level depends on
    whether it is held (priority_for)."""
    form = f["form"].upper()
    base = form.removesuffix("/A")
    items = set(f["items"])
    why = []
    if base.startswith("NT "):
        why.append("nt_filing")
    if base in ITEM_FORMS:
        why += [f"item_{i}" for i in sorted(items & P0_ITEMS)]
    if hits:
        why.append("b_pattern:" + "+".join(sorted({h["class"] for h in hits})))
    if why:
        return 0, why
    if base == "8-K" and items & EARNINGS_ITEMS:
        return 2, ["item_2.02"]
    if base in PERIODIC and form == base:
        return 2, [f"new_{base}"]
    if base in PERIODIC:
        return 3, [f"amendment_{form}"]
    return 3, [f"other_{form}"]


def priority_for(level, held):
    """SPEC 3: a held name takes its level (P0 / P2 / P3); a monitored name not held takes P1 for a critical level and P3 otherwise
    (open choice: the spec gives P1 only the P0 triggers; an earnings or periodic filing of a name not held is P3)."""
    if held:
        return level
    return 1 if level == 0 else 3


def price_signal(closes):
    """The price trigger on a list of (ISO date, close) pairs, or None when there are too few closes. A close of 0.0 is a value.
    {"date", "sigma_trigger", "z", "move_trigger", "move", "notes"}: the latest session's log return against 3 standard deviations of the
    60 daily log returns before it; the move over 5 sessions against 20%. DESIGN values."""
    pts = sorted(((str(d)[:10], float(c)) for d, c in closes if is_number(c)), key=lambda x: x[0])
    if len(pts) < 2:
        return None
    last_date, last = pts[-1]
    notes = []
    sig = {"date": last_date, "sigma_trigger": False, "z": None, "move_trigger": False, "move": None, "notes": notes}
    window = pts[-(PRICE_SIGMA_WINDOW + 2):-1]
    if len(window) == PRICE_SIGMA_WINDOW + 1 and pts[-2][1] > 0 and last > 0 and all(c > 0 for _, c in window):
        rets = [math.log(window[i][1] / window[i - 1][1]) for i in range(1, len(window))]
        sd = statistics.stdev(rets)
        r = math.log(last / pts[-2][1])
        if sd > 0:
            sig["z"] = r / sd
            sig["sigma_trigger"] = round(abs(r), 12) >= round(PRICE_SIGMAS * sd, 12) and r != 0
        else:
            sig["z"] = None
            sig["sigma_trigger"] = r != 0
            notes.append("zero_sigma_any_move_counts")
    elif len(window) < PRICE_SIGMA_WINDOW + 1:
        notes.append("sigma_needs_more_history")
    else:
        notes.append("sigma_not_computable_nonpositive_close")
    if len(pts) > PRICE_MOVE_SESSIONS:
        base = pts[-1 - PRICE_MOVE_SESSIONS][1]
        if base > 0:
            sig["move"] = (last - base) / base
            sig["move_trigger"] = round(abs(last - base), 12) >= round(PRICE_MOVE * base, 12)
        else:
            notes.append("move_not_computable_zero_base")
    return sig


def _stamp(t):
    return t.strftime("%Y-%m-%d")


def gather_name(info, gstate, src, now, peers=None, first_since=None):
    """One name's gather since its last gather. Writes nothing: (result, new_gstate).

    info    {"ticker", "cik", "company"}
    gstate  the stored record of this CIK, or None at the name's first gather
    peers   {ticker: company} of the other monitored names, for the cross-issuer annotation
    first_since  at a first gather, filings accepted before this are recorded as seen and not reported (default now - 7 days)
    result  {"filings": [new filing dicts with "hits", "annotations", "level"], "news": [new rows; those whose article was read also carry
             "text", "text_sha256", "text_chars_full", "read_from"], "news_dropped_no_issuer_word": n,
             "news_seen_not_reported": n, "price": signal or None, "price_source", "errors": [...], "first": bool}
    A source that fails leaves its part of the stored record untouched, so it is tried again at the next gather.
    """
    now = utc(now)
    ticker, cik, company = info["ticker"], int(info["cik"]), info.get("company") or info["ticker"]
    first = gstate is None
    g = json.loads(json.dumps(gstate)) if gstate else {"cik": cik, "ticker": ticker, "first_gather": iso(now), "filings_seen": {},
                                                       "news_seen": {}, "closes": {}, "price_checked": None, "price_fired": None}
    g.update(ticker=ticker, cik=cik, last_gather=iso(now))
    since = utc(first_since) if first_since is not None else now - timedelta(days=FIRST_GATHER_DAYS)
    # "first" is decided per source (cross-check 2026-11-16, S4): a source that failed at the name's first gather has seen nothing,
    # so its next gather is still its first and reports only the recent days, not the whole feed as new.
    sec_first, news_first = first or not g["filings_seen"], first or not g["news_seen"]
    res = {"filings": [], "news": [], "news_dropped_no_issuer_word": 0, "news_seen_not_reported": 0, "price": None, "price_source": None,
           "errors": [], "first": first}
    token = distinctive_word(company, ticker)
    pat = _word_pattern(token)

    # SEC
    if src.submissions is None:
        res["errors"].append("sec: no submissions source")
    else:
        try:
            filings = parse_submissions(src.submissions(cik), cik)
        except SecContactMissing:
            raise
        except Exception as e:  # noqa: BLE001
            filings = None
            res["errors"].append(f"sec: {type(e).__name__}: {str(e)[:160]}")
        if filings is not None:
            seen = g["filings_seen"]
            for f in filings:
                if f["accession"] in seen:
                    continue
                seen[f["accession"]] = f["accepted_utc"]
                if not collected(f["form"]):
                    continue
                if sec_first and (f["accepted_utc"] is None or parse_utc(f["accepted_utc"]) < since):
                    continue
                f = dict(f, annotations=[])
                if f["accepted_utc"] is None:
                    f["annotations"].append("acceptance_time_missing")
                text = None
                if src.filing_text is not None:
                    try:
                        text = src.filing_text(cik, f["accession"], f["primary_document"], f["form"])
                    except SecContactMissing:
                        raise
                    except Exception as e:  # noqa: BLE001
                        res["errors"].append(f"text {f['accession']}: {type(e).__name__}: {str(e)[:120]}")
                if text is None:
                    f["annotations"].append("text_unavailable_b_patterns_not_evaluated")
                    f["hits"] = []
                else:
                    f["hits"] = baseline_b.hits({"evidence": [{"fact_id": f["accession"], "kind": "filing", "text": text,
                                                               "source": {"accession": f["accession"]}}]})
                    head = text[:HEAD_CHARS]
                    if not pat.search(head):
                        others = sorted(t for t, c in (peers or {}).items()
                                        if t != ticker and _word_pattern(distinctive_word(c or t, t)).search(head))
                        f["annotations"].append("names_other_issuer:" + ",".join(others) if others else "issuer_not_named_in_filing_head")
                f["level"], f["level_reasons"] = filing_level(f, f["hits"])
                res["filings"].append(f)
            res["filings"].sort(key=lambda f: (f["accepted_utc"] or "", f["accession"]))

    # news (secondary)
    if src.news is not None:
        try:
            rows = list(src.news(company, ticker, _stamp(now)) or [])
        except Exception as e:  # noqa: BLE001
            rows = None
            res["errors"].append(f"news: {type(e).__name__}: {str(e)[:160]}")
        if rows is not None:
            seen = g["news_seen"]
            for row in rows:
                tkey, ukey = "t:" + normalize_title(row.get("title") or ""), "u:" + normalize_url(row.get("url") or "")
                if tkey == "t:" and ukey == "u:":
                    continue
                if not pat.search((row.get("title") or "") + " " + (row.get("snippet") or "")):
                    res["news_dropped_no_issuer_word"] += 1
                    continue
                if tkey in seen or ukey in seen:
                    continue                                                  # new only if neither its title nor its address was seen
                seen[tkey] = seen[ukey] = _stamp(now)
                day = str(row.get("date") or "")[:10]
                if news_first and not day:
                    res["news_seen_not_reported"] += 1                         # an undated headline is never new at a first gather
                    continue
                if news_first and day < _stamp(since):
                    res["news_seen_not_reported"] += 1
                    continue
                r = {k: row.get(k) for k in ("title", "url", "source", "snippet")}
                r.update(label="secondary", key=tkey, found_by=list(row.get("found_by") or []))
                if day:
                    r["date"] = day
                else:
                    r["first_seen"] = iso(now)
                res["news"].append(r)
            if res["news"]:
                if src.article is None:
                    res["errors"].append("news text: no article source")
                else:
                    # article text for a few new rows: category-found rows first, then the newest (a stable sort, so ties keep their order)
                    pick = sorted(res["news"], key=lambda r: str(r.get("date") or r["first_seen"])[:10], reverse=True)
                    pick = sorted(pick, key=lambda r: not (CATEGORY_KEYS & set(r["found_by"])))[:NEWS_TEXT_ROWS]
                    for r in pick:
                        try:
                            text = src.article(r["url"], r["title"])
                        except Exception as e:  # noqa: BLE001
                            res["errors"].append(f"article {r['url']}: {type(e).__name__}: {str(e)[:120]}")
                            continue
                        if not (text and str(text).strip()):
                            res["errors"].append(f"article {r['url']}: no text")
                            continue
                        kept = str(text)[:NEWS_TEXT_CHARS]
                        if not pat.search(kept):
                            r["annotations"] = ["text_does_not_name_issuer"]      # annotate: the row stays, its text is dropped
                            continue
                        r.update(text=kept, text_sha256=sha256_bytes(kept.encode("utf-8")), text_chars_full=len(str(text)), read_from=r["url"])
        cutoff = _stamp(now - timedelta(days=SEEN_KEEP_DAYS))
        g["news_seen"] = {k: d for k, d in g["news_seen"].items() if d >= cutoff}
        if rows is not None:
            kept_rows = g.setdefault("news_rows", {})                          # the rows with text, for the packet; pruned with the seen-set
            kept_rows.update({r["key"]: r for r in res["news"] if r.get("text")})
            g["news_rows"] = {k: r for k, r in kept_rows.items() if k in g["news_seen"]}

    # prices
    if src.prices is not None:
        try:
            p = src.prices(ticker)
        except Exception as e:  # noqa: BLE001
            p = None
            res["errors"].append(f"prices: {type(e).__name__}: {str(e)[:160]}")
        if p is not None:
            res["price_source"] = {"source": p.get("source"), "quote_date": p.get("quote_date"),
                                   **{k: p[k] for k in ("expected_session", "fetched_utc") if k in p}}
            closes = g["closes"]
            for row in p.get("closes") or []:
                if is_number(row.get("close")):
                    closes[str(row["date"])[:10]] = float(row["close"])          # 0.0 is a close
                else:
                    res["errors"].append(f"prices: close of {row.get('date')} is not a number and was skipped")
            for d in sorted(closes)[:-KEEP_CLOSES]:
                del closes[d]
            sig = price_signal(sorted(closes.items()))
            if sig is not None and sig["date"] != g["price_checked"]:
                g["price_checked"] = sig["date"]
                recent = sorted(closes)[-1 - PRICE_MOVE_SESSIONS:-1]
                if (sig["sigma_trigger"] or sig["move_trigger"]) and g["price_fired"] in recent:
                    sig["notes"].append("suppressed_fired_within_5_sessions")
                    sig["suppressed"] = True
                elif sig["sigma_trigger"] or sig["move_trigger"]:
                    g["price_fired"] = sig["date"]
                res["price"] = sig
    return res, g


def usable_incomplete(man):
    """A run that ended `analysis_incomplete` with material_events answered is read, as the formation runner reads it
    (formation_run.py: me_ok): the event question is the monitor's first question, and a retry replays the same packet and seeds
    (cross-check 2026-11-16, S2). A thesis_change left incomplete is then `unresolved`, never `intact` (see _resolved)."""
    return man.get("status") == "analysis_incomplete" and "material_events" not in (man.get("incomplete_tasks") or {})


def filing_effective(accepted_utc):
    """The time from which the packet builder admits a filing accepted at `accepted_utc`: qwen_c.packet.effective_at, the single
    owner of that rule (the open of the first full NYSE session after the acceptance's Eastern date; one more at or after 17:30 ET).
    A filing trigger carries THIS time, not its acceptance: a packet built at the acceptance time excludes the very filing that
    queued it (cross-check 2026-11-16, B1: on the first real read the newest trigger filing sat in the packet's `excluded` and its
    trigger was still retired as covered)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from qwen_c import packet
    return iso(packet.effective_at(parse_utc(accepted_utc)))


def build_triggers(info, res, held, now):
    """The triggers one gather produced (SPEC 3): filings by level, the price move (P3), and news (P3, SPEC v2 2.1): at most one `news`
    trigger per gather, when a new row was found by a category query (CATEGORY_KEYS) AND its article text was read. News without text
    queues nothing."""
    out = []
    for f in res["filings"]:
        out.append({"id": f"sec:{f['accession']}", "kind": "sec_filing", "priority": priority_for(f["level"], held),
                    "time": filing_effective(f["accepted_utc"]) if f["accepted_utc"] else iso(now), "reasons": f["level_reasons"],
                    "form": f["form"], "items": f["items"],
                    "accession": f["accession"], "accepted_raw": f["accepted_raw"], "filing_date": f["filing_date"],
                    "primary_document": f["primary_document"], "hits": f["hits"], "annotations": f["annotations"]})
    cat = [r for r in res["news"] if CATEGORY_KEYS & set(r.get("found_by") or []) and r.get("text")]
    if cat:
        out.append({"id": f"news:{info['ticker']}:{_stamp(now)}", "kind": "news", "priority": 3, "time": iso(now),
                    "reasons": ["news_" + k for k in sorted(CATEGORY_KEYS & {k for r in cat for k in r["found_by"]})], "annotations": [],
                    "evidence": [{"key": r["key"], "title": r["title"], "date": r.get("date"), "first_seen": r.get("first_seen"),
                                  "found_by": r["found_by"]} for r in cat]})
    sig = res["price"]
    if sig and not sig.get("suppressed") and (sig["sigma_trigger"] or sig["move_trigger"]):
        why = (["sigma_%.1f" % PRICE_SIGMAS] if sig["sigma_trigger"] else []) + (["move_%d%%_%dd" % (PRICE_MOVE * 100, PRICE_MOVE_SESSIONS)]
                                                                                 if sig["move_trigger"] else [])
        out.append({"id": f"price:{info['ticker']}:{sig['date']}", "kind": "price", "priority": 3, "time": f"{sig['date']}T21:00:00Z",
                    "reasons": why, "source": res["price_source"], "z": sig["z"], "move": sig["move"], "annotations": sig["notes"]})
    return out


# ---------------------------------------------------------------- Q1 (SPEC_m3o 3.2): one owner, m3o_engine.q1

import m3o_engine  # noqa: E402  (the single owner of Q1; a second copy here disagreed on dates without a comma - AUDIT_P2)


def q1_verdict(analysis, packet, T_date):
    """The Q1 verdict of a run's material_events task, by m3o_engine.q1: {"verdict": "event_found" | "news_event" | "escalation" | "none",
    "claims": [...], "escalations": [...]}. A claim acts when it is critical, supported, and announced_pending or occurred with a date printed
    in a cited item within 180 days before T; an undated or date_unsupported claim is an escalation that does not act.

    A packet item of kind `news` is secondary (a press report), and m3o_engine.q1 does not tell it from a filing. When the packet has news
    items, q1 is given only the claims that cite at least one primary item and only the primary items' text (so a date printed only in a
    press report cannot support a Q1 date). The claims left out are those that cite a news item and no primary item (a claim citing
    nothing in the packet stays with Q1, as before). They are listed apart as `news_claims`, each with its cited news ids and `q1_reason`:
    what the same owner, m3o_engine.q1, says of it when read against the news items' text. A supported one makes the verdict `news_event`
    when Q1 itself found no event, unless its own printed date puts the event more than 180 days before T or after T (NEWS_STALE_REASONS:
    a press report of this week that retells an old event is not a new one; an undated one acts, DESIGN, to be read against the recall
    replay). A packet with no news items is read exactly as before, and its result has no `news_claims`."""
    evidence = packet.get("evidence") or []
    news_ids = {e.get("fact_id") for e in evidence if e.get("kind") == "news"}
    if not news_ids:
        items = {e.get("fact_id"): e.get("text") or "" for e in evidence}
        q = m3o_engine.q1(analysis, as_date(T_date), Q1_EVENT_CLASS, items)
        verdict = "event_found" if q["restricted"] else ("escalation" if q["escalations"] else "none")
        return {"verdict": verdict, "claims": q["claims"], "escalations": q["escalations"]}
    primary = {e.get("fact_id"): e.get("text") or "" for e in evidence if e.get("kind") != "news"}
    news_text = {e.get("fact_id"): e.get("text") or "" for e in evidence if e.get("kind") == "news"}
    me = (analysis.get("tasks") or {}).get("material_events") or {}
    claims = me.get("claims") or []
    is_apart = [any(f in news_ids for f in c.get("fact_ids") or []) and not any(f in primary for f in c.get("fact_ids") or []) for c in claims]
    kept = [c for c, a in zip(claims, is_apart) if not a]
    apart = [c for c, a in zip(claims, is_apart) if a]
    tasks = analysis.get("tasks") or {}
    q = m3o_engine.q1({**analysis, "tasks": {**tasks, "material_events": {**me, "claims": kept}}}, as_date(T_date), Q1_EVENT_CLASS, primary)
    qn = m3o_engine.q1({**analysis, "tasks": {**tasks, "material_events": {**me, "claims": apart}}}, as_date(T_date), Q1_EVENT_CLASS, news_text)
    news_claims = [{"class": e["class"], "event_type": e["event_type"], "support": e["support"], "status": e["status"],
                    "occurred_on": e["occurred_on"], "fact_ids": e["fact_ids"],
                    "news_ids": [f for f in e["fact_ids"] or [] if f in news_ids], "claim": e["claim"], "q1_reason": e["reason"],
                    "acts_as_news_event": e["support"] == "supported" and e["reason"] not in NEWS_STALE_REASONS} for e in qn["claims"]]
    if q["restricted"]:
        verdict = "event_found"
    elif any(c["acts_as_news_event"] for c in news_claims):
        verdict = "news_event"
    else:
        verdict = "escalation" if q["escalations"] else "none"
    return {"verdict": verdict, "claims": q["claims"], "escalations": q["escalations"], "news_claims": news_claims}


# ---------------------------------------------------------------- thesis points

POINT_ORDER = ("changed", "unsupported", "unknown", "unchanged")        # which state wins when a point has several claims


def point_states(analysis, manifest):
    """None when thesis_change was not run; else {"status", "points": {point: {"state", "n_claims", "n_supported"}}}. A point only a
    failed-support claim addresses is `unsupported`; a point no claim addresses is `unknown`. The four states stay distinct."""
    tc = (analysis.get("tasks") or {}).get("thesis_change")
    if tc is None:
        return None
    if tc.get("status") != "ok":
        return {"status": tc.get("status"), "points": {}}
    ids = list(((manifest.get("prior_run") or {}).get("point_ids")) or [])
    seen, points = {}, {}
    for c in tc.get("claims") or []:
        p = c.get("point")
        seen.setdefault(p, []).append(c)
    for p in list(dict.fromkeys(ids + list(tc.get("points_not_addressed") or []) + list(seen))):
        cl = seen.get(p, [])
        good = [c.get("change_type") for c in cl if c.get("support") == "supported"]
        state = next((s for s in POINT_ORDER if s in good), None) or ("unsupported" if cl else "unknown")
        points[p] = {"state": state, "n_claims": len(cl), "n_supported": len(good)}
    return {"status": "ok", "points": points}


# ---------------------------------------------------------------- locking

def pid_alive(pid):
    """Whether a process with this pid is running. (Not os.kill(pid, 0): on Windows that TERMINATES the process.)"""
    if os.name == "nt":
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k.OpenProcess(0x1000, False, int(pid))                         # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5                            # access denied: it exists
        code = ctypes.c_uint32()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259                              # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


UNNAMED_LOCK_SECONDS = 600


def take_lock(path):
    """Create the lock file holding our pid. A lock whose pid is dead is taken over; one whose pid is alive raises LockHeld. A lock naming
    no readable pid is waited on until it is 10 minutes old (its writer died between creating and writing it)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pid = None
            if pid is not None and pid_alive(pid):
                raise LockHeld(f"{path} is held by running pid {pid}")
            if pid is None:
                try:
                    age = time.time() - path.stat().st_mtime
                except OSError:
                    continue
                if age < UNNAMED_LOCK_SECONDS:
                    raise LockHeld(f"{path} names no pid yet ({age:.0f} s old)")
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return
    raise LockHeld(f"{path}: could not be taken")


def release_lock(path):
    try:
        if int(Path(path).read_text(encoding="utf-8").strip()) == os.getpid():
            Path(path).unlink()
    except (ValueError, OSError):
        pass


# ---------------------------------------------------------------- the monitor

def select_names(order, tickers, only=None, limit=None):
    """(todo, alias, not_members): which members one gather pass visits. Members sharing a CIK (a common and its preferred, say) are
    gathered once, under the first by ticker; the others are `alias` {ticker: principal}, because the filings and the gather record belong
    to the CIK. `only` keeps those members; `limit` keeps the first N; `not_members` are the `only` tickers that are not members."""
    by_cik = {}
    for t in order:
        if t in tickers:
            by_cik.setdefault(int(tickers[t]["cik"]), []).append(t)
    alias = {t: names[0] for names in by_cik.values() for t in names[1:]}
    todo = [t for t in order if t in tickers and t not in alias]
    not_members = []
    if only is not None:
        only = list(dict.fromkeys(only))
        not_members = [t for t in only if t not in order]
        todo = [t for t in todo if t in only]
    if limit is not None:
        todo = todo[:int(limit)]
    return todo, alias, not_members


def run_key(cik, packet_sha256, prompt, contract, builder):
    """The run key of SPEC 4: (CIK, packet sha256, prompt, contract, builder), as one string."""
    return "|".join([str(int(cik)) if str(cik).isdigit() else str(cik), str(packet_sha256), str(prompt), str(contract), str(builder)])


def _event_id(*parts):
    return sha256_bytes(json.dumps(parts, sort_keys=True, default=str).encode("utf-8"))[:24]


class Monitor:
    def __init__(self, root=MONITOR_ROOT):
        self.root = Path(root)
        self.state_dir = self.root / "state"
        self.core_path = self.state_dir / "monitor.json"
        self.lock_path = self.state_dir / "monitor.lock"
        self.journal_path = self.root / "journal.jsonl"
        self._held = 0

    # -- plumbing
    @contextmanager
    def locked(self):
        if not self._held:
            take_lock(self.lock_path)
        self._held += 1
        try:
            yield
        finally:
            self._held -= 1
            if not self._held:
                release_lock(self.lock_path)

    def _load(self):
        s = read_json(self.core_path, None)
        if s is None:
            s = {"version": 1, "queue": {}, "names": {}, "ran_keys": {}, "last_seen": {}, "ciks": {}, "outbox": [], "started": {}}
        return s

    def _commit(self, s):
        """One atomic write of the core record (with its outbox), then the journal, then the cleared outbox."""
        write_json_atomic(self.core_path, s)
        self._flush(s)

    def _flush(self, s):
        if not s["outbox"]:
            return
        self._write_journal(s["outbox"])
        s["outbox"] = []
        write_json_atomic(self.core_path, s)

    def journal_lines(self):
        out = []
        if self.journal_path.exists():
            for line in self.journal_path.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue                                              # a torn line is skipped, never repaired in place
        return out

    def _write_journal(self, lines):
        """Append the lines whose event_id the journal does not hold yet, each as one line, flushed and synced."""
        have = {l.get("event_id") for l in self.journal_lines()}
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_path, "ab") as f:
            if f.tell() > 0:
                with open(self.journal_path, "rb") as r:
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

    def recover(self):
        """Finish an interrupted write: the outbox goes to the journal (once) and is cleared."""
        with self.locked():
            s = self._load()
            self._flush(s)
            return s

    def _name(self, s, ticker, cik=None, company=None, now=None):
        n = s["names"].get(ticker)
        if n is None:
            n = {"ticker": ticker, "cik": cik, "company": company, "first_seen": iso(now) if now else None, "monitored": False,
                 "state": None, "pending_review": False, "pending_reasons": [], "stale_analysis": False, "consecutive_unusable": 0,
                 "last_good": None, "last_good_at": None, "last_run_at": None, "points": {}, "q1": None, "handled": {}, "runs": {}}
            s["names"][ticker] = n
        if cik is not None:
            n["cik"] = int(cik)
        if company:
            n["company"] = company
        return n

    def _emit(self, s, kind, ticker, now, event_id, evidence=None, **fields):
        """Add a journal line to the outbox. Every line names the earlier thesis run and the dated evidence it was compared against."""
        n = s["names"].get(ticker) or {}
        lg = n.get("last_good")
        s["outbox"].append({"kind": kind, "event_id": event_id, "t": iso(now), "ticker": ticker, "cik": n.get("cik"),
                            "prior_run": ({"run_id": lg["run_id"], "decision_time_utc": lg.get("decision_time_utc")} if lg else None),
                            "evidence": evidence if evidence is not None else [], **fields})

    # -- the queue
    @staticmethod
    def _derive(entry):
        trig = list(entry["triggers"].values())
        pr = min(t["priority"] for t in trig)
        entry["priority"] = pr
        entry["trigger_time"] = min(t["time"] for t in trig if t["priority"] == pr)
        entry["packet_T"] = max(t["time"] for t in trig)

    def ordered(self, s=None):
        """The queue in order: priority first, then trigger time (then ticker, for a stable order)."""
        s = s or self._load()
        return sorted(s["queue"].values(), key=lambda e: (e["priority"], e["trigger_time"], e["ticker"]))

    def next_entry(self):
        q = self.ordered()
        return q[0] if q else None

    def already_ran(self, key):
        return key in self._load()["ran_keys"]

    def _add_triggers(self, s, info, triggers, now, run_key_=None):
        """Put triggers into the name's one queue entry (created if absent). Returns the entry, or None when nothing was added. A trigger
        already in the entry or already handled adds nothing; a run key that already ran adds nothing."""
        ticker = info["ticker"]
        n = self._name(s, ticker, info.get("cik"), info.get("company"), now)
        if run_key_ is not None and run_key_ in s["ran_keys"]:
            return None
        entry = s["queue"].get(ticker)
        new = [t for t in triggers if t["id"] not in n["handled"] and not (entry and t["id"] in entry["triggers"])]
        if not new:
            return None
        before = entry["priority"] if entry else None
        if entry is None:
            entry = {"ticker": ticker, "cik": n["cik"], "company": n["company"], "triggers": {}, "attempts": 0, "queued_at": iso(now)}
            s["queue"][ticker] = entry
        for t in new:
            entry["triggers"][t["id"]] = t
            self._emit(s, "discovered", ticker, now, "discovered:" + _event_id(ticker, t["id"]),
                       evidence=[_evidence(t)], trigger=t, source_ids=[t.get("accession") or t["id"]],
                       times={"trigger_time": t["time"], "detected_at": iso(now)},
                       secondary=False)
        self._derive(entry)
        if before is None or entry["priority"] != before:
            self._emit(s, "queued", ticker, now, "queued:" + _event_id(ticker, entry["priority"], sorted(entry["triggers"])),
                       evidence=[_evidence(t) for t in entry["triggers"].values()], priority=entry["priority"],
                       trigger_time=entry["trigger_time"], packet_T=entry["packet_T"], triggers=sorted(entry["triggers"]))
        return entry

    def enqueue(self, info, triggers, now, run_key_=None):
        """Queue triggers for a name (the public form of the above): returns the entry, or None when nothing was new or the run key already ran."""
        with self.locked():
            s = self._load()
            self._flush(s)
            entry = self._add_triggers(s, info, triggers, now, run_key_)
            self._commit(s)
            return entry

    def absorb(self, ticker, key, now):
        """The entry's packet has a run key that already ran: the entry is removed and the journal says so (a `queued` line, outcome absorbed)."""
        with self.locked():
            s = self._load()
            self._flush(s)
            entry = s["queue"].pop(ticker, None)
            if entry is None:
                return None
            n = s["names"].get(ticker)
            for tid in entry["triggers"]:
                n["handled"][tid] = iso(now)
            self._emit(s, "queued", ticker, now, "absorbed:" + _event_id(ticker, key, sorted(entry["triggers"])),
                       evidence=[_evidence(t) for t in entry["triggers"].values()], priority=entry["priority"],
                       outcome="absorbed_run_key", run_key=key, run_id=s["ran_keys"].get(key, {}).get("run_id"))
            self._commit(s)
            return entry

    def fail_entry(self, ticker, T, cause, detail, now):
        """A queue entry's attempt that ended before any run existed (no verified commit at T, a refused packet, a refused runner): the same
        `failed` step as a failed run (WO_P3b1). The last good analysis is kept, the name is pending_review, the entry is retried once and
        then dropped, and the carry rule counts it. Returns the `failed` journal line. A synthetic run id `norun:<ticker>:<T>:<attempt>`
        stands in for the run in the line and in the name's record."""
        with self.locked():
            s = self._load()
            self._flush(s)
            n, e = s["names"].get(ticker), s["queue"].get(ticker)
            if n is None or e is None:
                raise MonitorError(f"{ticker}: no queue entry to fail")
            common = {"run_id": f"norun:{ticker}:{T}:{e['attempts'] + 1}", "run_dir": None, "manifest_sha256": None, "run_key": None,
                      "decision_time_utc": T, "status": "not_run", "finished_at": None, "detail": detail}
            line = self._failed(s, n, ticker, now, common, cause, False, self._covered(s, ticker, T), {})
            self._update_stale(s, now)
            self._commit(s)
            return line

    def record_start(self, ticker, packet_sha256, key, started):
        """The executor records a run it is about to start: {ticker, packet_sha256, run_key, started}, kept HANDLED_KEEP_DAYS. The crash scan marks
        as crashed only a run directory that matches such a record (ticker and packet sha256); every other `running` directory in the run
        root belongs to another writer."""
        started = utc(started)
        with self.locked():
            s = self._load()
            self._flush(s)
            cutoff = iso(started - timedelta(days=HANDLED_KEEP_DAYS))
            s["started"] = {k: v for k, v in (s.get("started") or {}).items() if v["started"] >= cutoff}
            s["started"][key] = {"ticker": ticker, "packet_sha256": packet_sha256, "run_key": key, "started": iso(started)}
            self._commit(s)

    def _refresh_due(self, s, info, now):
        """The P4 trigger of a name with no run for 14 days (a name never run is due at once), unless it is already queued."""
        if info["ticker"] in s["queue"]:
            return []
        n = s["names"].get(info["ticker"])
        last = n.get("last_run_at") if n else None
        if last is not None and (now - parse_utc(last)) < timedelta(days=REFRESH_DAYS):
            return []
        return [{"id": f"refresh:{info['ticker']}:{_stamp(now)}", "kind": "refresh", "priority": 4, "time": iso(now),
                 "reasons": ["no_run_for_%d_days" % REFRESH_DAYS if last else "never_run"], "annotations": [], "last_run_at": last}]

    # -- the daily run
    def run_day(self, books, newest_book, restricted, tickers, sources, now, peers=None, first_since=None, sleep=time.sleep,
                batch=BATCH, pause_s=PAUSE_S, only=None, limit=None):
        """members -> per-name gather -> triggers -> queue (with journal) -> gather record -> 14-day refresh -> stale flags.

        tickers  {ticker: {"cik", "company"}}; a member with no entry here is reported in `no_cik`, not dropped silently.
        only, limit  gather only these members / only the first `limit` (see select_names). The monitored set itself is unchanged.
        Returns a report dict. A refusal to send SEC a contact-less request (SecContactMissing) propagates."""
        now = utc(now)
        with self.locked():
            s = self._load()
            self._flush(s)
            mem, s["last_seen"] = members(books, newest_book, restricted, now.date(), s["last_seen"])
            for n in s["names"].values():
                n["monitored"] = False
            report = {"members": sorted(mem), "no_cik": [], "errors": {}, "new_triggers": {}, "news": {}, "gathered": 0, "shared_cik": {},
                      "filings": {}, "first_gather": {}, "price_source": {}, "price_signal": {}, "not_members": [], "news_seen_not_reported": {}}
            order = sorted(mem)
            todo, alias, report["not_members"] = select_names(order, tickers, only, limit)
            report["shared_cik"] = alias
            for t in order:
                if t not in tickers:
                    report["no_cik"].append(t)
                    continue
                if t in alias:
                    continue                                              # gathered once, under the CIK's first member
                info = {"ticker": t, "cik": tickers[t]["cik"], "company": tickers[t].get("company")}
                self._name(s, t, info["cik"], info["company"], now)["monitored"] = True
            self._commit(s)
            peer_map = peers if peers is not None else {t: tickers[t].get("company") or t for t in order if t in tickers}
            done = 0
            for t in todo:
                if done and done % batch == 0:
                    sleep(pause_s)
                done += 1
                info = {"ticker": t, "cik": tickers[t]["cik"], "company": tickers[t].get("company")}
                gpath = self.state_dir / f"gather_{int(info['cik'])}.json"
                res, g = gather_name(info, read_json(gpath, None), sources, now, peer_map, first_since)
                if res["errors"]:
                    report["errors"][t] = res["errors"]
                trig = build_triggers(info, res, mem[t]["held"], now)
                s = self._load()
                self._add_triggers(s, info, trig, now)
                if res["news"] or res["news_dropped_no_issuer_word"]:
                    self._emit(s, "discovered", t, now, "discovered:" + _event_id(t, "news", _stamp(now), sorted(r["key"] for r in res["news"])),
                               evidence=[{"kind": "news", "label": "secondary", "date": r.get("date"), "first_seen": r.get("first_seen"),
                                          "title": r["title"], "url": r["url"]} for r in res["news"][:50]],
                               trigger=None, secondary=True, n_news=len(res["news"]), queues_nothing=not any(x["kind"] == "news" for x in trig),
                               news_dropped_no_issuer_word=res["news_dropped_no_issuer_word"],
                               source_ids=[r["key"] for r in res["news"][:50]], times={"detected_at": iso(now)})
                self._commit(s)                                           # the queue and the journal first ...
                write_json_atomic(gpath, g)                               # ... the gather record after
                report["gathered"] += 1
                report["new_triggers"][t] = [x["id"] for x in trig]
                report["news"][t] = len(res["news"])
                report["filings"][t] = len(res["filings"])
                report["news_seen_not_reported"][t] = res["news_seen_not_reported"]
                report["first_gather"][t] = res["first"]
                report["price_source"][t] = res["price_source"]
                report["price_signal"][t] = ({k: res["price"][k] for k in ("date", "sigma_trigger", "move_trigger", "z", "move")}
                                             if res["price"] else None)
            s = self._load()
            for t in todo:
                if t in tickers:
                    info = {"ticker": t, "cik": tickers[t]["cik"], "company": tickers[t].get("company")}
                    self._add_triggers(s, info, self._refresh_due(s, info, now), now)
            self._update_stale(s, now)
            self._commit(s)
            return report

    # -- carry rule
    @staticmethod
    def _update_stale(s, now):
        """SPEC 5 / ruling 6: stale_analysis after two unusable runs in a row, or when the last good analysis is 21 days old."""
        for n in s["names"].values():
            base = n.get("last_good_at") or n.get("first_seen")
            old = base is not None and (now - parse_utc(base)) >= timedelta(days=STALE_DAYS)
            n["stale_analysis"] = n["consecutive_unusable"] >= MAX_UNUSABLE or old

    def update_stale(self, now):
        with self.locked():
            s = self._load()
            self._flush(s)
            self._update_stale(s, utc(now))
            self._commit(s)

    # -- resolve
    def resolve(self, run_dir, now=None):
        """Read one finished qwen_c run and set the name's state. Returns the journal line it wrote (`resolved` or `failed`).

        - An unfinished run (no finished_at, i.e. a crash) or one whose status is not `complete` is a failed run: the last good analysis is
          kept, the name is `pending_review`, the entry gets one more attempt (two in all) and is then dropped, and the carry rule counts it.
        - A sha mismatch (analysis.json against the manifest's analysis_sha256, or packet.json against its file_sha256) is REFUSED:
          a `failed` line (refused) is written, the counters move as for a failed run, nothing else changes, and ResolveRefused is raised.
        - Resolving the same run twice writes nothing the second time."""
        now = utc(now)
        run_dir = Path(run_dir)
        try:
            man_bytes = (run_dir / "manifest.json").read_bytes()
            man = json.loads(man_bytes)
            ticker, run_id = man["ticker"], man["run_id"]
        except (OSError, ValueError, KeyError) as e:
            raise ResolveRefused(f"{run_dir}: manifest.json unreadable ({type(e).__name__}: {e}); nothing recorded") from e
        with self.locked():
            s = self._load()
            self._flush(s)
            n = self._name(s, ticker, now=now)
            if run_id in n["runs"]:
                return {"already_resolved": True, **n["runs"][run_id]}
            T = man.get("decision_time_utc")
            man_sha = sha256_bytes(man_bytes)
            pk = man.get("packet") or {}
            key = run_key(n["cik"] if n["cik"] is not None else ticker, pk.get("packet_sha256"), man.get("prompt_version"), man.get("contract"),
                          man.get("builder_version"))
            common = {"run_id": run_id, "run_dir": str(run_dir), "manifest_sha256": man_sha, "run_key": key, "decision_time_utc": T,
                      "status": man.get("status"), "finished_at": man.get("finished_at")}
            prior = man.get("prior_run") or None
            cause, refused, analysis, packet = None, False, None, None
            if not man.get("finished_at"):
                cause = "crashed_no_finished_at"
            elif man.get("status") != "complete" and not usable_incomplete(man):
                cause = f"run_status_{man.get('status')}"
            else:
                try:
                    ab = (run_dir / "analysis.json").read_bytes()
                    if sha256_bytes(ab) != man.get("analysis_sha256"):
                        cause, refused = "analysis_sha256_mismatch", True
                    else:
                        analysis = json.loads(ab)
                    pb = (run_dir / "packet.json").read_bytes()
                    if sha256_bytes(pb) != pk.get("file_sha256"):
                        cause, refused, analysis = "packet_sha256_mismatch", True, None
                    else:
                        packet = json.loads(pb)
                except (OSError, ValueError) as e:
                    cause, refused, analysis = f"records_unreadable:{type(e).__name__}", True, None
            self._emit(s, "analysed", ticker, now, "analysed:" + _event_id(ticker, run_id), evidence=[], run_id=run_id,
                       manifest_sha256=man_sha, analysis_sha256=man.get("analysis_sha256"), run_key=key, status=man.get("status"),
                       finished_at=man.get("finished_at"), prior_run_in_manifest=_prior_ref(prior))
            n["last_run_at"] = iso(now)
            covered = self._covered(s, ticker, T)
            if analysis is None:
                line = self._failed(s, n, ticker, now, common, cause, refused, covered, man)
                self._update_stale(s, now)
                self._commit(s)
                if refused:
                    raise ResolveRefused(f"{run_dir}: {cause}; a failed line was written and the last good analysis is kept")
                return line
            line = self._resolved(s, n, ticker, now, common, analysis, packet, man, covered, prior)
            self._update_stale(s, now)
            self._commit(s)
            return line

    @staticmethod
    def _covered(s, ticker, T):
        """The ids of the queue entry's triggers that a run at packet time T covers."""
        e = s["queue"].get(ticker)
        return [tid for tid, t in e["triggers"].items() if T and t["time"] <= T] if e else []

    def _retire(self, s, ticker, ids, now, cause=None):
        e = s["queue"].get(ticker)
        n = s["names"][ticker]
        for tid in ids:
            e["triggers"].pop(tid, None)
            n["handled"][tid] = iso(now)
        cutoff = iso(now - timedelta(days=HANDLED_KEEP_DAYS))
        n["handled"] = {k: v for k, v in n["handled"].items() if v >= cutoff}
        if e["triggers"]:
            e["attempts"] = 0
            self._derive(e)
        else:
            del s["queue"][ticker]

    def _failed(self, s, n, ticker, now, common, cause, refused, covered, man):
        n["consecutive_unusable"] += 1
        n["pending_review"] = True
        n["pending_reasons"] = sorted(set(n["pending_reasons"]) | {cause})
        e = s["queue"].get(ticker)
        retry = dropped = False
        if e and covered:
            e["attempts"] += 1
            if e["attempts"] >= MAX_ATTEMPTS:
                dropped = True
                self._retire(s, ticker, covered, now)
            else:
                retry = True
                self._emit(s, "queued", ticker, now, "requeued:" + _event_id(ticker, common["run_id"]), priority=e["priority"],
                           outcome="requeued_after_failed_run", run_id=common["run_id"], attempts=e["attempts"],
                           trigger_time=e["trigger_time"], triggers=sorted(e["triggers"]))
        line = {"cause": cause, "refused": refused, "retry_queued": retry, "entry_dropped": dropped, "incomplete_tasks": man.get("incomplete_tasks"),
                "kept_last_good_run": (n["last_good"] or {}).get("run_id"), "pending_review": True,
                "consecutive_unusable": n["consecutive_unusable"], **common}
        self._emit(s, "failed", ticker, now, "failed:" + _event_id(ticker, common["run_id"]), evidence=[], **line)
        n["runs"][common["run_id"]] = {"outcome": "failed", **{k: line[k] for k in ("cause", "refused")}}
        return {"kind": "failed", **line}

    def _resolved(self, s, n, ticker, now, common, analysis, packet, man, covered, prior):
        T = common["decision_time_utc"]
        q1 = q1_verdict(analysis, packet, parse_utc(T).date())
        tp = point_states(analysis, man)
        reasons = []
        if tp is not None and tp["status"] == "ok":
            states = [p["state"] for p in tp["points"].values()]
            n["points"] = {k: v["state"] for k, v in tp["points"].items()}
            compare = "changed" if "changed" in states else ("unchanged" if "unchanged" in states else "unresolved")
        elif tp is not None:                                              # not_applicable_no_prior: nothing to compare, the recorded thesis stands
            compare = "not_applicable"
        else:
            compare = "not_run"
        if "thesis_change" in (man.get("incomplete_tasks") or {}):      # asked and not answered: the recorded thesis is neither confirmed nor changed
            compare = "unresolved"
        if q1["verdict"] == "event_found":
            state = "event_found"
        elif q1["verdict"] == "news_event":
            state = "news_event"
        elif compare == "changed":
            state = "thesis_changed"
        elif compare in ("unchanged", "not_applicable"):
            state = "thesis_intact"
        elif compare == "not_run":
            state = n["state"] or "thesis_intact"                          # a run without thesis_change leaves the thesis state as it was
        else:
            state, reasons = (n["state"] or "thesis_intact"), ["thesis_unresolved"]
        if q1["escalations"]:
            reasons.append("q1_escalation:" + "+".join(sorted({e["reason"] for e in q1["escalations"]})))
        n.update(state=state, q1=q1["verdict"], consecutive_unusable=0, pending_review=bool(reasons), pending_reasons=reasons,
                 last_good_at=common["finished_at"] or iso(now),
                 last_good={"run_id": common["run_id"], "decision_time_utc": T, "finished_at": common["finished_at"],
                            "manifest_sha256": common["manifest_sha256"], "analysis_sha256": man.get("analysis_sha256")})
        queued = ((s["queue"].get(ticker) or {}).get("triggers")) or {}      # the triggers this read covered, taken before _retire removes them
        covered_triggers = [{"id": tid, "kind": queued[tid].get("kind"), "priority": queued[tid].get("priority")} for tid in covered if tid in queued]
        if covered:
            self._retire(s, ticker, covered, now)
        s["ran_keys"][common["run_key"]] = {"run_id": common["run_id"], "ticker": ticker, "t": iso(now)}
        read_news = ["u:" + normalize_url(str((e.get("source") or {}).get("url") or "")) for e in packet.get("evidence") or [] if e.get("kind") == "news"]
        if read_news:                                                      # the press reports this resolved run read are not handed to a later packet (news_file_for)
            cutoff = iso(now - timedelta(days=SEEN_KEEP_DAYS))
            n["news_packed"] = {**{k: v for k, v in (n.get("news_packed") or {}).items() if v >= cutoff}, **{k: iso(now) for k in read_news}}
        cited = {fid for task in ("thesis_change", "material_events") for c in (analysis.get("tasks") or {}).get(task, {}).get("claims") or []
                 for fid in c.get("fact_ids") or []}
        ev = [{"fact_id": e["fact_id"], "accession": (e.get("source") or {}).get("accession"), "accepted_raw": e.get("accepted_raw"),
               "effective_at": e.get("effective_at"), "name": e.get("name")}
              for e in packet.get("evidence") or [] if e.get("fact_id") in cited]
        warning_kind = (q1["verdict"] if q1["verdict"] in ("event_found", "news_event") else ("thesis_changed" if compare == "changed" else None))
        # Two annotations on an event warning (first live morning, 2026-11-17: three of four warnings rested on events months old,
        # one on the filing that queued the read). They gate nothing. `warning_new_events`: the acting claims whose event (type and
        # date) this name was not warned about before. `warning_cites_trigger`: an acting claim cites an item of a filing that
        # queued this read (None when no filing trigger was covered).
        new_events = cites_trigger = None
        if warning_kind == "event_found":
            acting = [c for c in q1.get("claims") or [] if c.get("acts")]
            keys = [f"{c.get('event_type')}|{c.get('occurred_on')}" for c in acting]
            before = set(n.get("warned_events") or [])
            new_events = len({k for k in keys if k not in before})
            n["warned_events"] = sorted(before | set(keys))
            trig_acc = {t["id"].split(":", 1)[1] for t in covered_triggers if t.get("kind") == "sec_filing"}
            if trig_acc:
                acc_of = {e.get("fact_id"): (e.get("source") or {}).get("accession") for e in packet.get("evidence") or []}
                cites_trigger = any(acc_of.get(fid) in trig_acc for c in acting for fid in c.get("fact_ids") or [])
        line = {"name_state": state, "warning_kind": warning_kind, "warning_new_events": new_events, "warning_cites_trigger": cites_trigger,
                "pending_review": n["pending_review"], "pending_reasons": reasons,
                "thesis_compare": compare, "points": {k: v["state"] for k, v in (tp or {}).get("points", {}).items()},
                "thesis_change_status": (tp or {}).get("status"), "q1": q1, "compared_with_run": _prior_ref(prior),
                "triggers": covered_triggers, **common}
        if warning_kind == "news_event":
            line["news_claims"] = [c for c in q1["news_claims"] if c["acts_as_news_event"]]
        self._emit(s, "resolved", ticker, now, "resolved:" + _event_id(ticker, common["run_id"]), evidence=ev, **line)
        n["runs"][common["run_id"]] = {"outcome": "resolved", "name_state": state}
        return {"kind": "resolved", **line}

    # -- the crash scan
    def crash_scan(self, run_root, now, min_age_hours=CRASH_MIN_AGE_HOURS):
        """Find qwen_c runs of known names that crashed (read_ledger's `crashed`, and older than min_age_hours so a run in progress is left
        alone), record each as a `failed` run through resolve(), and make sure the name is queued for one more run. Each crashed run is
        handled once: a second scan finds it recorded and does nothing.

        Only a run the monitor itself started is ever marked: its manifest must name the ticker and packet sha256 of a record the executor
        made before starting it (record_start). A formation run, the site worker or the cohort run also write in this run root; any other
        `running` directory (and any directory with no readable manifest, which names no ticker) is left alone and not counted.

        The re-queue is the retry resolve() already gives an entry that covers the crashed run. A name with no such entry gets a P2 trigger
        `rerun:<run_id>` at the crashed run's decision time, with its attempts preset so that a second failure drops it (once, not forever)."""
        now = utc(now)
        run_root = Path(run_root)
        out = {"crashed": [], "requeued": [], "dropped": [], "already_recorded": [], "too_recent": [], "not_monitored": []}
        started = list((self._load().get("started") or {}).values())
        for r in read_ledger(run_root):
            if r.get("status") != "crashed" or not any(v["ticker"] == r.get("ticker") and v["packet_sha256"] == r.get("packet_sha256")
                                                      for v in started):
                continue
            run_id, d = r["run_id"], run_root / "runs" / r["run_id"]
            out["crashed"].append(run_id)
            try:
                mt = (d / "manifest.json").stat().st_mtime if (d / "manifest.json").exists() else d.stat().st_mtime
                age_h = (now - datetime.fromtimestamp(mt, timezone.utc)).total_seconds() / 3600
            except OSError:
                age_h = None
            if age_h is not None and age_h < min_age_hours:
                out["too_recent"].append(run_id)
                continue
            ticker = r["ticker"]
            n = self._load()["names"].get(ticker)
            if n is None:
                out["not_monitored"].append(run_id)
                continue
            line = self.resolve(d, now)
            if line.get("already_resolved"):
                out["already_recorded"].append(run_id)
            elif line["entry_dropped"]:
                out["dropped"].append(run_id)
            elif line["retry_queued"]:
                out["requeued"].append(run_id)
            else:
                trig = {"id": f"rerun:{run_id}", "kind": "rerun_after_crash", "priority": 2, "time": r.get("T") or iso(now),
                        "reasons": ["crashed_run"], "annotations": [], "crashed_run": run_id}
                with self.locked():
                    s = self._load()
                    self._flush(s)
                    entry = self._add_triggers(s, {"ticker": ticker, "cik": n["cik"], "company": n["company"]}, [trig], now)
                    if entry is not None:
                        entry["attempts"] = max(entry["attempts"], MAX_ATTEMPTS - 1)
                    self._commit(s)
                out["requeued"].append(run_id)
        return out

    # -- reports
    def report(self, now):
        """SPEC 7 coverage and queue age, and the flags every report must show (pending_review, stale_analysis)."""
        now = utc(now)
        s = self._load()
        mon = [n for n in s["names"].values() if n["monitored"]]
        cov = [n for n in mon if n["last_run_at"] and (now - parse_utc(n["last_run_at"])) <= timedelta(days=REFRESH_DAYS)]
        age = {}
        for e in s["queue"].values():
            age.setdefault(e["priority"], []).append(round((now - parse_utc(e["trigger_time"])).total_seconds() / 3600, 2))
        return {"monitored": len(mon), "run_within_14_days": len(cov), "queue_age_hours_by_priority": {f"P{k}": sorted(v) for k, v in sorted(age.items())},
                "queue": [{"ticker": e["ticker"], "priority": e["priority"], "trigger_time": e["trigger_time"]} for e in self.ordered(s)],
                "names": {t: {"state": n["state"], "pending_review": n["pending_review"], "stale_analysis": n["stale_analysis"],
                              "last_run_at": n["last_run_at"]} for t, n in sorted(s["names"].items())}}


def _evidence(t):
    return {"id": t["id"], "kind": t["kind"], "time": t["time"], "accession": t.get("accession"), "form": t.get("form"),
            "items": t.get("items"), "accepted_raw": t.get("accepted_raw"),
            "label": "primary" if t["kind"] == "sec_filing" else ("secondary" if t["kind"] == "news" else t["kind"]),
            **({"rows": t.get("evidence")} if t["kind"] == "news" else {})}


def _prior_ref(prior):
    return {"run_id": prior.get("run_id"), "decision_time_utc": prior.get("decision_time_utc")} if prior else None


def resolve(run_dir, root=MONITOR_ROOT, now=None):
    """resolve(run_dir): Monitor(root).resolve(run_dir)."""
    return Monitor(root).resolve(run_dir, now)


# ================================================================ WO_P3a: the real inputs, a price source, the command line

FORWARD_DIR = book_paths.books() / "m3l_forward"
LEDGER_DIR = book_paths.books() / "m3o" / "ledger"
SCREENER_REPO = book_paths.screener_repo()
CIK_MAP_PATH = "public/data/cik_map.json"
HELD_ACTIONS = frozenset({"hold", "enter", "enter_after_pending"})    # m3o_engine action names: the arm holds the name after the formation
LEDGER_LINE_KINDS = frozenset({"at_fill_open", "pending_resolution"})

# forward_ledger.py NYSE_HOLIDAYS, copied (it ends at 2027-01-01: a later holiday looks like a session; the price source then says
# quote_date < expected_session and the gather records the lag)
NYSE_HOLIDAYS = {date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
                 date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25), date(2027, 1, 1)}


def _jsonl(path):
    """The parseable lines of a jsonl file; [] when it is absent. A torn line is skipped."""
    out = []
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


# ---------------------------------------------------------------- item 1: the monitored set from files

def verified_formations(forward_dir):
    """The formations of m3l_forward/formations.jsonl whose verifier verdict is PASS, oldest first."""
    rows = [r for r in _jsonl(Path(forward_dir) / "formations.jsonl") if (r.get("verifier") or {}).get("verdict") == "PASS"]
    return sorted(rows, key=lambda r: r["formation_T"])


def ledger_inputs(ledger_dir=LEDGER_DIR, forward_dir=FORWARD_DIR):
    """The inputs of members() from files (SPEC 1).

    The newest A0 book is always the newest line of m3l_forward/formations.jsonl. If the 3O ledger (ledger/formations.jsonl) holds a
    formation, the newest one's `actions.jsonl` lines give what each series holds after it: a name is held by an arm when its last
    at_fill_open / pending_resolution line for that arm is `hold`, `enter` or `enter_after_pending`; a name is restricted when that line
    names a B1 / Q1 cause (or is a Q1 `new_entry_restricted`). With an empty or absent ledger there are no books and no restrictions, and
    the source says `m3l_forward_fallback`.
    Returns {"source", "formation_T", "ledger_formation_T", "books", "newest_book", "restricted"}."""
    fwd = _jsonl(Path(forward_dir) / "formations.jsonl")
    if not fwd:
        raise MonitorError(f"{Path(forward_dir) / 'formations.jsonl'} holds no formation")
    newest = max(fwd, key=lambda r: r["formation_T"])
    out = {"source": "m3l_forward_fallback", "formation_T": newest["formation_T"], "ledger_formation_T": None, "books": {},
           "newest_book": list(newest["book"]), "restricted": {}}
    forms = _jsonl(Path(ledger_dir) / "formations.jsonl")
    if not forms:
        return out
    led_T = max(f["formation_T"] for f in forms)
    last = {}                                                           # (arm, ticker) -> the last line, in file order
    for line in _jsonl(Path(ledger_dir) / "actions.jsonl"):
        if line.get("formation_T") == led_T and line.get("kind") in LEDGER_LINE_KINDS and line.get("arm") and line.get("ticker"):
            last[(line["arm"], line["ticker"])] = line
    books, restricted = {}, {}
    for (arm, t), line in sorted(last.items()):
        if line.get("action") in HELD_ACTIONS:
            books.setdefault(arm, []).append(t)
        causes = line.get("causes") or ([line.get("rule")] if line.get("action") == "new_entry_restricted" and line.get("rule") else [])
        if causes:
            restricted[t] = "+".join(sorted(set(causes) | set(filter(None, restricted.get(t, "").split("+")))))
    books.pop("FV", None)                                               # FV's book is not the newest formation's lines (below)
    fv_book = _fv_book(Path(ledger_dir) / "actions.jsonl")
    if fv_book is not None:
        books["FV"] = fv_book
    out.update(source="m3o_ledger", ledger_formation_T=led_T, books=dict(sorted(books.items())), restricted=restricted)
    return out


def _fv_book(actions_path):
    """The names paper book FV holds now (WO_TB2b part 1): those with an `enter` or `hold` at_fill_open line at the latest formation that has
    FV at_fill_open lines (FV may have skipped the newest formation, or not be priced at it yet), less every name with a between_formations line
    at that formation whose exit was applied. None when FV has no at_fill_open line anywhere."""
    lines = [l for l in _jsonl(actions_path) if l.get("arm") == "FV"]
    fills = [l for l in lines if l.get("kind") == "at_fill_open" and l.get("ticker")]
    if not fills:
        return None
    last = max(l["formation_T"] for l in fills)
    gone = {l["ticker"] for l in lines if l.get("kind") == "between_formations" and l.get("formation_T") == last
            and (l.get("exit") or {}).get("applied") is True}
    return sorted({l["ticker"] for l in fills if l["formation_T"] == last and l.get("action") in ("enter", "hold")} - gone)


def default_git_show(repo, commit, path):
    """`git -C repo show commit:path`, read-only. Raises MonitorError naming the commit and path on failure."""
    r = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], capture_output=True)
    if r.returncode != 0:
        raise MonitorError(f"git show {commit}:{path} in {repo} failed: {r.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return r.stdout


def cik_map_for(forward_dir=FORWARD_DIR, repo=SCREENER_REPO, git_show=None):
    """({ticker: int CIK}, commit): cik_map.json of the newest verified (verifier PASS) formation's output commit, through git show."""
    ver = verified_formations(forward_dir)
    if not ver:
        raise MonitorError("no verified formation in m3l_forward/formations.jsonl: no commit to read cik_map.json from")
    commit = ver[-1]["output_commit"]
    raw = (git_show or default_git_show)(repo, commit, CIK_MAP_PATH)
    m = json.loads(raw)
    m = m.get("map", m)
    return {str(t).upper(): int(c) for t, c in m.items()}, commit


# ---------------------------------------------------------------- item 2: a price source

def is_session(d):
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def last_completed_session(now=None):
    """The latest session whose 16:00 New York close has passed (forward_ledger.last_completed_session, with the clock injectable): today
    only after 16:15 New York, else the previous session. An open session's close is still moving, so it never counts."""
    now_ny = utc(now).astimezone(NY)
    d = now_ny.date()
    while not is_session(d) or (d == now_ny.date() and now_ny.time() < dtime(16, 15)):
        d -= timedelta(days=1)
    return d


def _yf_fetch(ticker, start, end):
    """(source, [(date, close)]) from yfinance: adjusted daily closes from start to end inclusive."""
    import yfinance as yf
    df = yf.Ticker(ticker).history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=True, actions=False)
    rows = [(idx.date(), float(c)) for idx, c in df["Close"].items()] if len(df) else []
    return f"yfinance {yf.__version__} Ticker.history auto_adjust=True", rows


def yf_prices(ticker, now=None, fetch=None, sessions=KEEP_CLOSES):
    """The price source of the gather: daily adjusted closes, the last `sessions` (130) completed sessions, as
    {"source", "quote_date", "expected_session", "fetched_utc", "closes": [{"date", "close"}]}.

    Only completed sessions count (last_completed_session): a bar dated after it is dropped. A NaN close is dropped; 0.0 is a close.
    `quote_date` is the date of the newest close actually returned; `expected_session` is the session that should have been last, so a
    lagging quote shows as quote_date < expected_session. `fetch(ticker, start, end) -> (source, [(date, close)])` is injectable."""
    now = utc(now)
    end = last_completed_session(now)
    start = end - timedelta(days=int(sessions * 1.6) + 14)
    source, rows = (fetch or _yf_fetch)(ticker, start, end)
    kept = {}
    for d, c in rows:
        d = as_date(d)
        if d <= end and is_number(c):
            kept[d] = float(c)
    pts = sorted(kept.items())[-sessions:]
    if not pts:
        raise MonitorError(f"{ticker}: no completed-session close between {start} and {end}")
    return {"source": source, "quote_date": pts[-1][0].isoformat(), "expected_session": end.isoformat(), "fetched_utc": iso(now),
            "closes": [{"date": d.isoformat(), "close": c} for d, c in pts]}


# ---------------------------------------------------------------- item 4: the crash rule (reads a run root given as a path)

def read_ledger(root):
    """The `crashed` runs of a qwen_c run root: a COPY of the crash rule of qwen_c.runner.read_ledger (rs2-local is not imported).
    `root` holds ledger.jsonl and runs/<run_id>/manifest.json. A run directory the ledger does not list is `crashed` when its manifest is
    missing or unreadable, or says `running` with no finished_at. Rows: {"run_id", "status": "crashed", "ticker", "T", "packet_sha256"}
    (ticker, T and packet_sha256 are absent when the manifest cannot be read). Other runs are not reported."""
    root = Path(root)
    seen = {r.get("run_id") for r in _jsonl(root / "ledger.jsonl")}
    out = []
    runs = root / "runs"
    for d in sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []:
        if d.name in seen:
            continue
        try:
            man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out.append({"run_id": d.name, "status": "crashed", "cause": "manifest.json missing or unreadable"})
            continue
        if man.get("status") == "running" and not man.get("finished_at"):
            out.append({"run_id": d.name, "status": "crashed", "ticker": man.get("ticker"), "T": man.get("decision_time_utc"),
                        "packet_sha256": (man.get("packet") or {}).get("packet_sha256")})
    return out


# ---------------------------------------------------------------- item 3: one gather pass and the command line

def live_sources(now):
    """The real sources: SEC submissions (one fetch per CIK per pass, kept), filing text, yfinance closes, SearXNG news, article text."""
    cache = {}

    def submissions(cik):
        if int(cik) not in cache:
            cache[int(cik)] = online_submissions(cik)
        return cache[int(cik)]

    def prices(ticker):
        time.sleep(0.5)                                                 # Yahoo is not hammered
        return yf_prices(ticker, now)
    return Sources(submissions=submissions, filing_text=online_filing_text, prices=prices,
                   news=lambda company, ticker, today: searx_news(company, ticker, date.fromisoformat(today)), article=online_article)


def resolve_companies(todo, tickers, submissions):
    """Fill tickers[t]["company"] for the names about to be gathered from the `name` of their SEC submissions feed (the screener's
    cik_map has no company names). A feed that fails leaves the company unset; the gather then reports the same failure itself."""
    for t in todo:
        try:
            tickers[t]["company"] = submissions(tickers[t]["cik"]).get("name") or tickers[t].get("company")
        except SecContactMissing:
            raise
        except Exception:  # noqa: BLE001
            pass


def gather_pass(root, now, sources, *, limit=None, only=None, ledger_dir=LEDGER_DIR, forward_dir=FORWARD_DIR, repo=SCREENER_REPO,
                git_show=None, run_root=None, sleep=time.sleep, batch=BATCH, pause_s=PAUSE_S):
    """One gather pass (SPEC 2) over the monitored set read from files. Returns a summary dict (printed by `gather`).

    Reads the 3O ledger (or the m3l_forward fallback) and cik_map.json through git show, gathers each selected member through `sources`,
    queues triggers, writes state and journal, and, when `run_root` is given, scans it for crashed runs. This function sends no request
    except through `sources`."""
    now = utc(now)
    inp = ledger_inputs(ledger_dir, forward_dir)
    cik_map, commit = cik_map_for(forward_dir, repo, git_show)
    tickers = {t: {"cik": c, "company": None} for t, c in cik_map.items()}
    mon = Monitor(root)
    mem, _ = members(inp["books"], inp["newest_book"], inp["restricted"], now.date(), mon._load()["last_seen"])
    todo, _, _ = select_names(sorted(mem), tickers, only, limit)
    if sources.submissions is not None:
        resolve_companies(todo, tickers, sources.submissions)
    rep = mon.run_day(inp["books"], inp["newest_book"], inp["restricted"], tickers, sources, now, sleep=sleep, batch=batch, pause_s=pause_s,
                      only=only, limit=limit)
    rep.update(inputs_source=inp["source"], formation_T=inp["formation_T"], ledger_formation_T=inp["ledger_formation_T"], cik_map_commit=commit)
    if run_root is not None:
        rep["crash_scan"] = mon.crash_scan(run_root, now)
    rep["queue_size"] = len(mon.report(now)["queue"])
    return rep


def format_gather(rep):
    """The printed summary of a gather pass."""
    lines = [f"gather: inputs {rep['inputs_source']} (formation {rep['formation_T']}; ledger formation {rep['ledger_formation_T']}), "
             f"cik_map from {rep['cik_map_commit'][:10]}",
             f"members {len(rep['members'])}, gathered {rep['gathered']}, no_cik {rep['no_cik']}, shared_cik {rep['shared_cik']}, "
             f"not_members {rep['not_members']}, queue size {rep['queue_size']}"]
    for t in sorted(rep["new_triggers"]):
        ps = rep["price_source"].get(t) or {}
        lines.append(f"  {t}: first_gather={rep['first_gather'][t]} filings={rep['filings'][t]} triggers={rep['new_triggers'][t]} "
                     f"news={rep['news'][t]} (first-gather rows seen, not reported: {rep['news_seen_not_reported'][t]}) close={ps.get('quote_date')}/{ps.get('expected_session')} price_signal={rep['price_signal'].get(t)}")
    for t, errs in sorted(rep["errors"].items()):
        lines.append(f"  errors {t}: {errs}")
    if "crash_scan" in rep:
        lines.append(f"crash scan: {rep['crash_scan']}")
    return "\n".join(lines)


def format_report(r):
    """The printed `report`: coverage, queue age, queue, flags."""
    lines = [f"monitored {r['monitored']}, run within 14 days {r['run_within_14_days']}",
             f"queue age (hours) by priority: {r['queue_age_hours_by_priority']}"]
    lines += [f"  queue P{e['priority']} {e['ticker']} {e['trigger_time']}" for e in r["queue"]]
    flagged = {t: n for t, n in r["names"].items() if n["pending_review"] or n["stale_analysis"]}
    lines.append(f"pending_review / stale_analysis: {flagged}")
    return "\n".join(lines)


# ================================================================ WO_P3b1: the executor (queue entry -> packet -> qwen_c -> resolve)

WORKTREE = ROOT                                                         # the qwen_c run worktree: this repository (main's qwen_c)
CHECKS_DIR = book_paths.books() / "m3l_verifier" / "out"                # where tools/paper_books/check_new_runs.py writes check_*.json
SEED_BASE = 1000
MONITOR_TASKS = "material_events,thesis_change"                         # P0-P3 (SPEC 4); P4 runs every task (the runner's default)
INFRA_REFUSALS = ("gpu_busy", "gpu_state_unreadable", "model_show_failed")   # the queue waits and no attempt is counted (SPEC 5)
PACKET_TIMEOUT_S = 1800


# A packet build that failed on the network: the SEC store's fetch error, a timeout, a connection error. On the first live night
# seven list analyses were refused on SEC 503 answers; counted as attempts, two such days would drop a queued trigger.
TRANSPORT_MARKS = ("FetchFailed", "timed out", "URLError", "ConnectionError", "ConnectionResetError", "TimeoutError")


class PacketRefused(MonitorError):
    """The packet builder refused (or failed to build) a packet; the text is the refusal."""


def verified_commit(checks_dir, T):
    """The newest screener commit that `check_*.json` rows mark verdict PASS and pair PASS with run_updated_at <= T (the row's GitHub clock;
    a row without one cannot be placed before T and is not eligible), with its check file: {"commit", "check_file", "run_updated_at",
    "run_id"} or None. Newest = the latest run_updated_at; a tie goes to the later check file name."""
    T = parse_utc(T)
    best = None
    for p in sorted(Path(checks_dir).glob("check_*.json")):
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict) or r.get("verdict") != "PASS" or r.get("pair") != "PASS":
                continue
            commit, upd = r.get("output_commit"), r.get("run_updated_at")
            if not commit or not upd:
                continue
            try:
                u = parse_utc(upd)
            except (ValueError, TypeError):
                continue
            if u <= T and (best is None or (u, p.name) > best[0]):
                best = ((u, p.name), {"commit": commit, "check_file": str(p), "run_updated_at": iso(u), "run_id": r.get("run_id")})
    return best[1] if best else None


def qwen_versions(worktree):
    """(prompt_version, contract) of the qwen_c in `worktree`, read from the source text (no import: nothing of qwen_c is executed)."""
    out = []
    for rel, name in (("qwen_c/tasks.py", "PROMPT_VERSION"), ("qwen_c/contract.py", "CONTRACT")):
        try:
            text = (Path(worktree) / rel).read_text(encoding="utf-8")
        except OSError as e:
            raise MonitorError(f"{Path(worktree) / rel}: unreadable ({e})") from e
        m = re.search(r"^%s\s*=\s*[\"']([^\"']+)[\"']" % name, text, flags=re.M)
        if not m:
            raise MonitorError(f"{Path(worktree) / rel}: no {name} found")
        out.append(m.group(1))
    return tuple(out)


def _json_tail(text):
    return json.loads(text[text.index("{"):])


def qwen_build_packet(ticker, T, commit, verified_record, screener_repo, cwd, news_file=None):
    """Build one verified-regime packet through the qwen_c CLI, run in the run worktree (as o2_packets.py does):
    {"packet", "packet_sha256", "builder_version", "annotations"}. Raises PacketRefused with the refusal text.
    With `news_file` (news_file_for) the packet is built by `qwen_c.news_packet --news-file` (the SEC packet plus the press reports; its
    own module, because editing packet.py would move the sha256 of every packet); without it the command is as it was before news."""
    cmd = [sys.executable, "-m", "qwen_c.packet" if news_file is None else "qwen_c.news_packet", "--ticker", ticker, "--T", T, "--commit", commit,
           "--verified-record", str(verified_record), "--screener-repo", str(screener_repo), "--online"]
    if news_file is not None:
        cmd += ["--news-file", str(news_file)]
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=PACKET_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        raise PacketRefused(f"packet build timed out after {PACKET_TIMEOUT_S} s") from e
    try:
        if r.returncode != 0:
            raise ValueError("exit code %s" % r.returncode)
        out = _json_tail(r.stdout)
        path = Path(out["packet"])
        path = path if path.is_absolute() else Path(cwd) / path
        pk = json.loads(path.read_text(encoding="utf-8"))
        return {"packet": str(path), "packet_sha256": out["packet_sha256"], "builder_version": pk["builder_version"],
                "annotations": out.get("annotations") or []}
    except (ValueError, KeyError, OSError) as e:
        raise PacketRefused(((r.stderr or r.stdout or "").strip()[-600:]) or f"{type(e).__name__}: {e}") from e


def qwen_run(packet, tasks, seed_base, cwd):
    """One qwen_c run through the CLI, in the run worktree: `<packet> [--tasks a,b] --seed-base N`. Returns the runner's result
    ({"run_dir", "status", ...}), {"refused": text} when the runner refused to start (exit 2), or {"crashed": text} when it left no result."""
    cmd = [sys.executable, "-m", "qwen_c.runner", str(packet)]
    if tasks:
        cmd += ["--tasks", tasks]
    cmd += ["--seed-base", str(seed_base)]
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 2:
        return {"refused": (r.stderr or "").strip().removeprefix("refused:").strip()}
    try:
        res = _json_tail(r.stdout)
        if res.get("run_dir"):
            return res
    except ValueError:
        pass
    return {"crashed": f"exit code {r.returncode}: {((r.stderr or r.stdout or '').strip()[-400:])}"}


def task_set(priority):
    """The tasks of an entry: material_events and thesis_change for P0-P3, every task (None: the runner's default) for P4."""
    return None if priority >= 4 else MONITOR_TASKS


def entry_T(entry):
    """The packet's decision time: the entry's packet_T (the latest of its triggers' effective times, so one run covers all of them; for
    an entry with one trigger it is that trigger's time), ISO Z, whole seconds."""
    return iso(parse_utc(entry["packet_T"]))


def unresolved_finished_run(run_root, name_rec, ticker, packet_sha256, prompt, contract, builder):
    """The newest finished run in `run_root` with this exact run key that the monitor has not resolved (a crash between the run and its
    resolve), or None. A run with no finished_at is not one (it is `crashed`; the crash scan records it)."""
    best = None
    runs = Path(run_root) / "runs"
    for d in sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []:
        try:
            man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (man.get("ticker") != ticker or not man.get("finished_at") or man.get("run_id") in (name_rec or {}).get("runs", {})
                or (man.get("packet") or {}).get("packet_sha256") != packet_sha256 or man.get("prompt_version") != prompt
                or man.get("contract") != contract or man.get("builder_version") != builder):
            continue
        if best is None or (man["finished_at"], d.name) > best[0]:
            best = ((man["finished_at"], d.name), d)
    return best[1] if best else None


def _news_moment(row):
    """When a stored news row happened: its date at 00:00 UTC, or its first-seen time; None when it has neither."""
    if row.get("date"):
        return datetime.combine(as_date(row["date"]), dtime(0, 0), tzinfo=timezone.utc)
    return parse_utc(row["first_seen"]) if row.get("first_seen") else None


def news_file_for(mon, entry, T):
    """Write `<root>/news/<ticker>_<T compact>.json` for a queue entry about to be packed and return (path, number of rows).

    The rows are the name's stored news rows that have article text, were not in the packet of an earlier resolved run of the name
    (`news_packed`, by address: Monitor._resolved), and whose date (or first-seen time) is within NEWS_PACKET_DAYS before T and not after
    T, newest first, at most NEWS_PACKET_ROWS. A dated row counts as 00:00 UTC of its date, so "after the last run" cannot be told by time
    for a row published later on the day of that run; the record of what was read can. The file is written even when it holds no row; the
    caller passes it to the packet builder only when it does."""
    ticker = entry["ticker"]
    n = mon._load()["names"].get(ticker) or {}
    packed = n.get("news_packed") or {}
    t_dt = parse_utc(T)
    stored = ((read_json(mon.state_dir / f"gather_{int(entry['cik'])}.json", None) or {}).get("news_rows") or {}).values()
    take = []
    for r in stored:
        at = _news_moment(r)
        if not r.get("text") or at is None or at > t_dt or "u:" + normalize_url(r.get("url") or "") in packed:
            continue
        if at >= t_dt - timedelta(days=NEWS_PACKET_DAYS):
            take.append((at, r))
    take.sort(key=lambda x: x[0], reverse=True)
    rows = []
    for _, r in take[:NEWS_PACKET_ROWS]:
        when = {"date": r["date"]} if r.get("date") else {"first_seen": r["first_seen"]}
        rows.append({"title": r["title"], "url": r["url"], "publisher": urllib.parse.urlparse(str(r["url"])).netloc.lower().removeprefix("www.") or r.get("source"),
                     **when, "found_by": r.get("found_by") or [], "text": r["text"], "text_sha256": r["text_sha256"]})
    path = mon.root / "news" / f"{ticker}_{T.replace('-', '').replace(':', '')}.json"
    write_json_atomic(path, {"ticker": ticker, "T": T, "rows": rows})
    return path, len(rows)


FOREIGN_VRAM_MIB = 2000                                               # as the site worker's (tools/site/qwen_ondemand.py)


def gpu_free():
    """(True, None) or (False, why): no other job holds the card. More than FOREIGN_VRAM_MIB in use while Ollama has no model loaded is
    another program's memory (cross-check 2026-11-16, S7); a model Ollama has loaded is the runner's own test (gpu_busy)."""
    try:
        used = int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True,
                                  text=True, timeout=20).stdout.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return False, "nvidia-smi unreadable"
    if used <= FOREIGN_VRAM_MIB:
        return True, None
    try:
        with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=10) as r:
            loaded = json.loads(r.read().decode("utf-8", "replace")).get("models") or []
    except Exception as e:  # noqa: BLE001  Ollama unreadable with the card in use: not ours to take
        return False, f"{used} MiB in use and Ollama unreadable ({type(e).__name__})"
    return (True, None) if loaded else (False, f"{used} MiB in use with no Ollama model loaded (another job holds the card)")


def run_pass(root, *, worktree=WORKTREE, checks_dir=CHECKS_DIR, screener_repo=SCREENER_REPO, limit=None, dry_run=False, build=None,
             runner=None, versions=None, clock=None, seed_base=SEED_BASE, crash_scan=True, waiting=None, max_minutes=None, gpu=None):
    """One executor pass (WO_P3b1): the queue's entries in order (priority, then trigger time), at most `limit`, each at most once.

    For an entry: T = its packet_T; the newest verified commit at or before T (none: `failed`, no_verified_commit_at_T); the packet through
    `build` (a refusal: `failed`, the refusal's text); the run key from the packet (a key already run: the entry is absorbed and nothing
    runs); a finished run with that key that was never resolved is resolved instead of run again; otherwise `runner` runs qwen_c and
    resolve() reads the run. A runner refusal that is the infrastructure (gpu_busy, Ollama unreadable) stops the pass and counts no attempt.
    Injectable: build(ticker, T, commit, verified_record, screener_repo, cwd[, news_file=path]) -> {"packet", "packet_sha256",
    "builder_version", ...} or raises PacketRefused (`news_file` is passed only when the entry has news rows, see news_file_for);
    runner(packet, tasks, seed_base, cwd) -> {"run_dir", ...} | {"refused": text} | {"crashed": text};
    versions(worktree) -> (prompt_version, contract); clock() -> aware datetime.

    One instance: state/executor.lock (take_lock; a dead pid is taken over). dry_run takes no lock and changes nothing. Returns
    {"dry_run", "stopped", "entries": [...], "crash_scan"}."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    mon = Monitor(root)
    rep = {"dry_run": bool(dry_run), "stopped": None, "entries": [], "crash_scan": None}
    if dry_run:
        for e in mon.ordered()[:int(limit) if limit is not None else None]:
            T = entry_T(e)
            c = verified_commit(checks_dir, T)
            rep["entries"].append({"ticker": e["ticker"], "priority": e["priority"], "T": T, "commit": c["commit"] if c else None,
                                   "check_file": c["check_file"] if c else None, "tasks": task_set(e["priority"]) or "all"})
        return rep
    build, runner, versions = build or qwen_build_packet, runner or qwen_run, versions or qwen_versions
    if waiting is None:                                # the formation runner's own test of "a formation has Q1 work left" (its owner)
        import formation_run
        waiting = formation_run.formation_waiting
    gpu = gpu or gpu_free
    lock = mon.state_dir / "executor.lock"
    take_lock(lock)
    try:
        prompt, contract = versions(worktree)
        run_root = Path(worktree) / "cache" / "m3m"
        if crash_scan:
            # Under the executor lock no qwen_c run of ours is in progress, so a `running` run with no finished_at is dead: record it now
            # (min age 0) rather than after the gather's 6 hours, or a later scan would mark a name pending_review over a newer good run.
            rep["crash_scan"] = mon.crash_scan(run_root, clock(), min_age_hours=0)
        visited, began, transport = [], utc(clock()), 0
        while limit is None or len(visited) < int(limit):
            e = next((x for x in mon.ordered() if x["ticker"] not in visited), None)
            if e is None:
                break
            if max_minutes is not None and (utc(clock()) - began).total_seconds() >= float(max_minutes) * 60:
                rep["stopped"] = f"max_minutes: {max_minutes:g} reached, {len(mon.ordered()) - len(visited)} entries wait"
                break                              # the pass's time budget: no new entry is started; what is left stays queued
            t = e["ticker"]
            visited.append(t)
            T, tasks, now = entry_T(e), task_set(e["priority"]), clock()
            row = {"ticker": t, "priority": e["priority"], "T": T, "tasks": tasks or "all", "outcome": None}
            rep["entries"].append(row)
            if parse_utc(T) > utc(now):            # its newest trigger is not effective yet (a filing waits for the next open): the
                row["outcome"] = "waiting:not_effective_before_T"      # entry stays queued and no attempt is counted
                continue
            if waiting():                          # a formation has names left to read: its fill has a deadline, a monitor read does
                rep["stopped"] = "formation_waiting"                   # not (cross-check 2026-11-16, B2). The pass ends; nothing is
                row["outcome"] = "stopped:formation_waiting"           # counted against the entry.
                break
            ok, why = gpu()
            if not ok:                             # another job has the card: the pass ends, nothing is counted
                rep["stopped"] = "gpu_foreign: " + str(why)
                row["outcome"] = "stopped:gpu_foreign"
                break
            c = verified_commit(checks_dir, T)
            if c is None:
                mon.fail_entry(t, T, "no_verified_commit_at_T", "no check_*.json row is PASS with pair PASS and run_updated_at <= T", now)
                row["outcome"] = "failed:no_verified_commit_at_T"
                continue
            row.update(commit=c["commit"], check_file=c["check_file"])
            news_path, row["news_rows"] = news_file_for(mon, e, T)
            try:
                pk = build(t, T, c["commit"], c["check_file"], screener_repo, worktree,
                           **({"news_file": str(news_path)} if row["news_rows"] else {}))
            except PacketRefused as ex:
                if any(k in str(ex) for k in TRANSPORT_MARKS):            # the network, not the name (cross-check 2026-11-16, S3): the
                    row["outcome"] = "waiting:packet_transport"            # entry stays queued and no attempt is counted; three in a
                    transport += 1                                         # row and the pass ends (the network is down)
                    if transport >= 3:
                        rep["stopped"] = "packet_transport: " + str(ex)[-200:]
                        break
                    continue
                mon.fail_entry(t, T, "packet_refused", str(ex), now)
                row["outcome"] = "failed:packet_refused"
                continue
            transport = 0
            key = run_key(e["cik"], pk["packet_sha256"], prompt, contract, pk["builder_version"])
            row["run_key"] = key
            if mon.already_ran(key):
                mon.absorb(t, key, now)
                row["outcome"] = "absorbed"
                continue
            run_dir = unresolved_finished_run(run_root, mon._load()["names"].get(t), t, pk["packet_sha256"], prompt, contract,
                                              pk["builder_version"])
            if run_dir is not None:
                row["recovered_run"] = str(run_dir)                       # finished before a crash, never resolved: resolve it, do not run again
            else:
                mon.record_start(t, pk["packet_sha256"], key, now)       # the crash scan marks only runs the monitor recorded here
                res = runner(pk["packet"], tasks, seed_base, worktree)
                if res.get("refused") is not None:
                    why = str(res["refused"])
                    if why.startswith(INFRA_REFUSALS):
                        rep["stopped"] = why
                        row["outcome"] = "stopped:" + why.split(":")[0]
                        break
                    mon.fail_entry(t, T, "runner_refused", why, now)
                    row["outcome"] = "failed:runner_refused"
                    continue
                if res.get("run_dir") is None:
                    rep["stopped"] = "runner_crashed: " + str(res.get("crashed"))
                    row["outcome"] = "stopped:runner_crashed"
                    break                                                 # no result: the next pass's crash scan records the run
                run_dir = res["run_dir"]
            try:
                line = mon.resolve(run_dir, clock())
            except ResolveRefused as ex:
                row["outcome"] = f"resolve_refused:{ex}"
                continue
            row.update(outcome=line["kind"], run_id=line.get("run_id"), name_state=line.get("name_state"), cause=line.get("cause"),
                       prior_run=(line.get("compared_with_run") or {}).get("run_id") if line["kind"] == "resolved" else None)
            if line.get("run_key") != key:
                row["run_key_mismatch"] = line.get("run_key")             # the key predicted from the packet and the source text is not the manifest's
        return rep
    finally:
        release_lock(lock)


def format_run(rep):
    """The printed summary of an executor pass (or of a dry run)."""
    lines = [("dry run: nothing is built, run or written" if rep["dry_run"] else "run pass") + f", {len(rep['entries'])} entr"
             + ("y" if len(rep["entries"]) == 1 else "ies")]
    for e in rep["entries"]:
        lines.append(f"  P{e['priority']} {e['ticker']} T={e['T']} commit={(e.get('commit') or 'none')[:10]} tasks={e['tasks']}"
                     + (f" -> {e['outcome']}" if e.get("outcome") else ""))
    if rep.get("crash_scan"):
        lines.append(f"crash scan: {rep['crash_scan']}")
    if rep["stopped"]:
        lines.append(f"stopped: {rep['stopped']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python monitor.py", description="3P thesis monitor: one gather pass, one run pass, or a report. Paper only.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gather", help="run one gather pass (SEC, closes, news) and queue the triggers")
    g.add_argument("--limit", type=int, help="gather only the first N members (sorted by ticker)")
    g.add_argument("--tickers", help="comma list: gather only these members")
    g.add_argument("--run-root", help="a qwen_c run root (holds ledger.jsonl and runs/): scan it for crashed runs after the gather")
    g.add_argument("--ledger-dir", default=str(LEDGER_DIR))
    g.add_argument("--forward-dir", default=str(FORWARD_DIR))
    g.add_argument("--screener-repo", default=str(SCREENER_REPO))
    r = sub.add_parser("report", help="print coverage and queue age")
    x = sub.add_parser("run", help="run the queue's entries in priority order: packet, qwen_c, resolve (needs the GPU)")
    x.add_argument("--limit", type=int, help="take at most N entries from the queue in this pass")
    x.add_argument("--max-minutes", type=float, help="start no new entry once the pass has run this long (the entries left stay queued)")
    x.add_argument("--dry-run", action="store_true", help="print what would run (ticker, priority, T, commit, tasks) and change nothing")
    x.add_argument("--worktree", default=str(WORKTREE), help="the qwen_c run worktree (default: this repository's root)")
    x.add_argument("--checks-dir", default=str(CHECKS_DIR), help="the folder of check_*.json verifier records")
    x.add_argument("--screener-repo", default=str(SCREENER_REPO))
    for p in (g, r, x):
        p.add_argument("--root", default=str(MONITOR_ROOT), help="the monitor's state folder (default: <rs2_state_dir>/paper_books/monitor)")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    if a.cmd == "run":
        try:
            rep = run_pass(a.root, worktree=a.worktree, checks_dir=a.checks_dir, screener_repo=a.screener_repo, limit=a.limit, dry_run=a.dry_run, max_minutes=a.max_minutes)
        except LockHeld as e:
            print(f"stopped: {e}", file=sys.stderr)
            return 3
        except MonitorError as e:
            print(f"stopped: {e}", file=sys.stderr)
            return 2
        print(format_run(rep))
        return 4 if rep["stopped"] else 0
    if a.cmd == "report":
        print(format_report(Monitor(a.root).report(now)))
        return 0
    try:
        sec_headers()                                                   # refuse before anything else when there is no SEC contact
    except SecContactMissing as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 2
    only = [t.strip().upper() for t in a.tickers.split(",") if t.strip()] if a.tickers else None
    try:
        rep = gather_pass(a.root, now, live_sources(now), limit=a.limit, only=only, ledger_dir=a.ledger_dir, forward_dir=a.forward_dir,
                          repo=a.screener_repo, run_root=a.run_root)
    except LockHeld as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 3
    print(format_gather(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
