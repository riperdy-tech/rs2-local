#!/usr/bin/env python3
"""company_news.py — fetch recent company news via SearXNG news category (Reuters, Bing News).

Item 2 of Phase 4 Amendments (E8 design):
- Two SearXNG queries: (1) "<company>", (2) "<TICKER> stock"
- categories="news", time_range="month", format="json", timeout=60s
- Drops LOW_TRUST URLs
- De-duplicates by URL and identical lower-cased title
- Orders rows with publishedDate first (newest first), then undated in order returned. Keeps 15.
- Caches to cache/company_news/<TICKER>_<YYYY-MM-DD>.json and reuses same day.
- Never raises; records errors and unresponsive_engines.
"""
import json
import re
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


def _fetch_live(company, ticker, searx_url=None, cache_dir=None, timeout=60):
    t = str(ticker).upper()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cdir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    cache_file = cdir / f"{t}_{today}.json"

    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    clean_comp = _clean_company_name(company, t)
    queries = [f'"{clean_comp}"', f"{t} stock"]

    endpoint = searx_url or rs2_data.CONFIG.get("searxng_url", SEARX_DEFAULT)
    raw_results = []
    unresponsive_engines = []
    errors = []

    for q in queries:
        try:
            data = _query_searxng(endpoint, q, timeout=timeout)
            raw_results.extend(data.get("results") or [])
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

    for res in raw_results:
        u = str(res.get("url") or "").strip()
        if not u or any(bad in u for bad in LOW_TRUST):
            continue
        title = re.sub(r"\s+", " ", str(res.get("title") or "")).strip()[:150]
        if not title:
            continue
        norm_url = u.lower().rstrip("/")
        norm_title = title.lower()
        if norm_url in seen_urls or norm_title in seen_titles:
            continue
        seen_urls.add(norm_url)
        seen_titles.add(norm_title)

        date_str = _parse_date(res.get("publishedDate"))
        source_str = _format_source(res.get("engine"), u)
        snippet = re.sub(r"\s+", " ", str(res.get("content") or "")).strip()[:220]

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

    try:
        cdir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(out, indent=2), encoding="utf-8")
    except Exception:
        pass

    return out


def fetch(company, ticker):
    """Fetch recent company news for ticker and company name. Never raises."""
    return _fetch_live(company, ticker)
