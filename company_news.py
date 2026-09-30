#!/usr/bin/env python3
"""company_news.py — fetch recent company news via SearXNG news category (Reuters, Bing News).

Item 2 of Phase 4 Amendments (E8 design):
- Two SearXNG queries: (1) "<company>", (2) "<TICKER> stock"
- categories="news", time_range="month", format="json", timeout=60s
- Drops LOW_TRUST URLs
- Drops rows that do not name the company (`names_company`, revision 17 brief C2): the cleaned company name as a
  phrase (a one-word name only with a finance word in the same row), or the ticker in a finance pattern
- De-duplicates by URL and identical lower-cased title
- Orders rows with publishedDate first (newest first), then undated in order returned. Keeps 15.
- Caches to cache/company_news/<TICKER>_<YYYY-MM-DD>.json and reuses same day.
- Never raises; records errors and unresponsive_engines.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

import rs2_data

CACHE_DIR = HERE / "cache" / "company_news"
SEARX_DEFAULT = "http://localhost:8888"
UA = {"User-Agent": "Mozilla/5.0 (RS2 analyst research)"}

LOW_TRUST = (
    "pitchgrade.com",
    "stocksentinel",
    "zacks.com/stock/chart",
    "marketbeat.com",
    "simplywall.st",
    "investing.com/news/stock-market-news",
    "benzinga.com/insights",
)


def _parse_date(pub_date):
    if not pub_date:
        return None
    s = str(pub_date).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def _format_source(engine, url):
    eng = str(engine or "").strip()
    domain = ""
    if url:
        try:
            domain = urllib.parse.urlparse(url).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
        except Exception:
            domain = ""
    if eng and domain:
        return f"{eng}, {domain}"
    return eng or domain or "unknown"


def _clean_company_name(company, ticker):
    s = str(company or "").strip()
    cleaned = re.sub(
        r",?\s*(?:Inc\.?|Corp\.?|Corporation|Co\.?|Company|LLC|Plc|Ltd\.?)\s*$",
        "",
        s,
        flags=re.I,
    ).strip()
    return cleaned if cleaned else (s or str(ticker).upper())


_GENERIC_NAME_WORDS = {
    "advanced", "american", "united", "general", "first", "national", "international", "global",
    "holdings", "holding", "group", "technology", "technologies", "systems", "energy", "mining",
    "resources", "company", "corporation", "the", "and", "new", "north", "south", "east", "west",
}


def _name_token(clean_company):
    """The first distinctive word of the company name (>= 4 letters, not generic), e.g.
    'Lindblad Expeditions Holdings' -> 'Lindblad', 'Advanced Micro Devices' -> 'Micro'."""
    for w in re.findall(r"[A-Za-z][A-Za-z&'-]+", clean_company or ""):
        if len(w) >= 4 and w.lower() not in _GENERIC_NAME_WORDS:
            return w
    return None


# Revision 17, brief C2: FIVE's block carried a Reuters diesel story because "Five" is an ordinary word and the
# rows of the quoted-name query were not filtered at all. One rule now applies to every row, from both queries.
_FINANCE_WORD = re.compile(
    r"(?<![A-Za-z0-9])(?:stocks?|shares|earnings|revenues?|guidance|quarters?|quarterly|dividends?|analysts?|"
    r"CEO|Inc|Corp|NYSE|NASDAQ)(?![A-Za-z0-9])", re.I)
_INVISIBLE = re.compile("[\N{ZERO WIDTH SPACE}-\N{ZERO WIDTH JOINER}\N{WORD JOINER}\N{ZERO WIDTH NO-BREAK SPACE}]")


def _plain(text):
    """Row text as matched: invisible characters (Reuters snippets carry them) removed, curly apostrophes straight."""
    return _INVISIBLE.sub("", str(text or "")).replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")


def names_company(clean_company, ticker, *parts):
    """True when the row (its title, snippet and excerpt when read: `parts`) names the company.

    a. the full cleaned company name as a phrase, case-insensitive; when the cleaned name is one word, only
       together with a finance word in the same row (a one-word name is usually an ordinary word); or
    b. the ticker, exact case, in a finance pattern: $T, (T), NYSE: T, NASDAQ: T, T stock, T shares.
    """
    text = _plain(" ".join(str(p) for p in parts if p))
    words = _plain(clean_company).split()
    if words:
        phrase = r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(w) for w in words) + r"(?![A-Za-z0-9])"
        if re.search(phrase, text, re.I) and (len(words) > 1 or _FINANCE_WORD.search(text)):
            return True
    t = re.escape(str(ticker).strip())
    end = r"(?![A-Za-z0-9])"
    return bool(re.search(
        rf"\${t}{end}|\({t}\)|\b(?i:NYSE|NASDAQ):\s?{t}{end}|(?<![A-Za-z0-9.]){t}\s+(?i:stocks?|shares){end}",
        text))


def _mostly_non_latin(text):
    """True when more than 30% of the letters are outside the Latin script blocks (CJK, Cyrillic,
    Arabic, ...): the analyst reads English, and those rows were unrelated noise when measured."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for c in letters if ord(c) > 0x024F)
    return non_latin / len(letters) > 0.30


def _query_searxng(searx_url, query, timeout=60):
    params = {
        "q": query,
        "categories": "news",
        "time_range": "month",
        "format": "json",
    }
    url = f"{searx_url}/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


READ_TOP = 5          # the most recent stories whose opening text goes into the pack (E11)
EXCERPT_CHARS = 600


# Page furniture that fetch_page's tag stripping leaves in (Yahoo, newswires, publisher banners)
_FURNITURE = ("skip to", "something went wrong", "sign in", "subscribe", "cookie", "accessibility statement",
              "advertiser disclosure", "preferred source", "all rights reserved", "javascript",
              "return to homepage", "top stories")
_SENTENCE = re.compile(r"(?:^|(?<=[.!?]) )([A-Z0-9\"\u201c'][^.!?]{40,500}[.!?])")


def _excerpt(text, title, name_token, chars=EXCERPT_CHARS):
    """About `chars` characters from the story's lede: the first real sentence (12+ words) that
    names the company or shares two words with the headline. Page furniture before it (Yahoo
    opens with "Oops, something went wrong / Skip to navigation...") has no such sentence. None
    when no sentence qualifies or the text is a subscription wall."""
    try:
        sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
        import analyst_tools
    except Exception:
        return None
    t = re.sub(r"\s+", " ", text or "").strip()
    want = analyst_tools._title_tokens(title)
    name = (name_token or "").lower()
    # Fable pre-(b) F2: two headline words were enough, so a multi-company headline let a Royal
    # Caribbean paragraph into LIND's news. The two-word rule now applies only when the headline
    # itself names the company; otherwise the sentence must.
    headline_names_it = bool(name) and re.search(rf"\b{re.escape(name)}", (title or "").lower()) is not None
    for m in _SENTENCE.finditer(t):
        sent = m.group(1)
        if len(sent.split()) < 12 or any(j in sent.lower() for j in _FURNITURE):
            continue
        names_it = bool(name) and re.search(rf"\b{re.escape(name)}", sent.lower()) is not None
        if names_it or (headline_names_it and len(want & analyst_tools._title_tokens(sent)) >= 2):
            ex = t[m.start(1):m.start(1) + chars].strip()
            if len(ex) >= 150 and not analyst_tools._looks_paywalled(ex) and _mostly_english(ex):
                return ex
            return None
    return None


_EN_COMMON = set("the and of to in is for on with that as by at from are was it this be has have will "
                 "its an or said which their".split())


def _mostly_english(text):
    """The analyst reads English. German and Indonesian pages pass the Latin-script filter; they
    fail this one (UGI, 2026-09-25: ad-hoc-news.de and a jawapos.com food-tourism page)."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    return len(words) >= 20 and sum(w in _EN_COMMON for w in words) / len(words) >= 0.12


def _read_article(url, title, name_token):
    """(excerpt, url actually read) for one story, or (None, None). analyst_tools.fetch_page with
    the headline as the known title, so a blocked page falls back to a legitimate free copy."""
    try:
        sys.path.insert(0, str(HERE / "tools" / "audit_202608"))
        import analyst_tools
        res = analyst_tools.fetch_page(url, known_urls={url: title})
    except Exception:
        return None, None
    if not isinstance(res, dict) or res.get("error"):
        return None, None
    ex = _excerpt(res.get("text"), title, name_token)
    return (ex, res.get("url") or url) if ex else (None, None)


def _add_excerpts(out, name_token):
    """Read the READ_TOP most recent rows in place; marks the result so a cached day is read once."""
    for r in (out.get("rows") or [])[:READ_TOP]:
        if r.get("excerpt"):
            continue
        ex, src = _read_article(r.get("url") or "", r.get("title") or "", name_token or out.get("ticker"))
        if ex:
            r["excerpt"], r["read_from"] = ex, src
    out["excerpts_read"] = True
    return out


def _fetch_live(company, ticker, searx_url=None, cache_dir=None, timeout=60):
    t = str(ticker).upper()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cdir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    cache_file = cdir / f"{t}_{today}.json"

    clean_comp = _clean_company_name(company, t)
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            cached["rows"] = [r for r in cached.get("rows") or []
                              if names_company(clean_comp, t, r.get("title"), r.get("snippet"), r.get("excerpt"))]
            if not cached.get("excerpts_read") and READ_TOP:
                cached = _add_excerpts(cached, _name_token(clean_comp))
                cache_file.write_text(json.dumps(cached, indent=2), encoding="utf-8")
            return cached
        except Exception:
            pass

    queries = [f'"{clean_comp}"', f"{t} stock"]

    endpoint = searx_url or rs2_data.CONFIG.get("searxng_url", SEARX_DEFAULT)
    raw_results = []
    unresponsive_engines = []
    errors = []

    for qi, q in enumerate(queries):
        try:
            data = _query_searxng(endpoint, q, timeout=timeout)
            raw_results.extend({**r, "_query_index": qi} for r in (data.get("results") or []))
            for eng in data.get("unresponsive_engines") or []:
                if eng not in unresponsive_engines:
                    unresponsive_engines.append(eng)
        except Exception as e:
            err_msg = str(e)[:160]
            if err_msg not in errors:
                errors.append(err_msg)

    seen_urls = set()
    seen_titles = set()
    raw_rows = []
    name_token = _name_token(clean_comp)

    for res in raw_results:
        u = str(res.get("url") or "").strip()
        if not u or any(bad in u for bad in LOW_TRUST):
            continue
        title = re.sub(r"\s+", " ", str(res.get("title") or "")).strip()[:150]
        if not title:
            continue
        if _mostly_non_latin(title):
            continue
        snippet = re.sub(r"\s+", " ", str(res.get("content") or "")).strip()[:220]
        if not names_company(clean_comp, t, title, snippet):
            # both queries match ticker collisions and ordinary words (LIND -> Linde Bangladesh, FIVE ->
            # "five drafting tips"); a row must name the company, on the text the analyst is shown.
            continue
        norm_url = u.lower().rstrip("/")
        norm_title = title.lower()
        if norm_url in seen_urls or norm_title in seen_titles:
            continue
        seen_urls.add(norm_url)
        seen_titles.add(norm_title)

        date_str = _parse_date(res.get("publishedDate"))
        source_str = _format_source(res.get("engine"), u)

        raw_rows.append({
            "date": date_str,
            "source": source_str,
            "title": title,
            "url": u,
            "snippet": snippet,
        })

    dated = [r for r in raw_rows if r["date"] is not None]
    undated = [r for r in raw_rows if r["date"] is None]
    dated.sort(key=lambda r: r["date"], reverse=True)
    rows = (dated + undated)[:15]

    out = {
        "ticker": t,
        "company": company,
        "date": today,
        "rows": rows,
        "unresponsive_engines": unresponsive_engines,
        "errors": errors,
    }
    if READ_TOP:
        _add_excerpts(out, name_token)

    try:
        cdir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(out, indent=2), encoding="utf-8")
    except Exception:
        pass

    return out


def fetch(company, ticker):
    """Fetch recent company news for ticker and company name. Never raises."""
    return _fetch_live(company, ticker)
