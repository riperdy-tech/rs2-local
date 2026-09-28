"""tests for Item 2: RECENT COMPANY NEWS (company_news.py and capability_test.py)."""
import json
from datetime import date
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parents[2]

import company_news
import capability_test as cap


def _slice(pack, header, next_prefix="## "):
    i = pack.find("## " + header)
    assert i != -1, f"section {header!r} not found in pack"
    j = pack.find("\n" + next_prefix, i + 3)
    return pack[i:j if j != -1 else len(pack)]


def test_company_news_query_strings_and_params(tmp_path, monkeypatch):
    queries_made = []

    def fake_query(endpoint, query, timeout=60):
        queries_made.append(query)
        return {"results": [], "unresponsive_engines": []}

    monkeypatch.setattr(company_news, "_query_searxng", fake_query)
    # Enable calling live fetch implementation
    monkeypatch.setattr(company_news, "fetch", lambda c, t: company_news._fetch_live(c, t, cache_dir=tmp_path))

    res = company_news.fetch("Advanced Micro Devices, Inc.", "AMD")
    assert res["ticker"] == "AMD"
    assert len(queries_made) == 2
    assert queries_made[0] == '"Advanced Micro Devices"'
    assert queries_made[1] == "AMD stock"


def test_company_news_low_trust_drop_and_dedup(tmp_path, monkeypatch):
    sample_results = [
        {"url": "https://pitchgrade.com/news/1", "title": "Pitchgrade Article", "engine": "reuters", "publishedDate": "2026-09-20T00:00:00"},
        {"url": "https://reuters.com/article1", "title": "Good Reuters News", "engine": "reuters", "publishedDate": "2026-09-21T00:00:00", "content": "Snippet 1"},
        {"url": "https://reuters.com/article1/", "title": "Duplicate URL News", "engine": "reuters", "publishedDate": "2026-09-21T00:00:00"},
        {"url": "https://msn.com/article2", "title": "good reuters news", "engine": "bing news"},  # Duplicate lowercase title
        {"url": "https://fool.com/article3", "title": "Unique Motley Fool", "engine": "bing news", "content": "Snippet 3"},
    ]

    monkeypatch.setattr(company_news, "_query_searxng", lambda ep, q, timeout=60: {"results": sample_results})
    monkeypatch.setattr(company_news, "fetch", lambda c, t: company_news._fetch_live(c, t, cache_dir=tmp_path))

    res = company_news.fetch("AMD", "AMD")
    rows = res["rows"]
    assert len(rows) == 2
    urls = [r["url"] for r in rows]
    assert "https://reuters.com/article1" in urls
    assert "https://fool.com/article3" in urls
    assert "https://pitchgrade.com/news/1" not in urls


def test_company_news_ordering_and_15_cap(tmp_path, monkeypatch):
    # 10 dated articles and 10 undated articles
    sample_results = []
    for i in range(10):
        day = 10 + i
        sample_results.append({
            "url": f"https://reuters.com/art{i}",
            "title": f"Dated Title {i}",
            "engine": "reuters",
            "publishedDate": f"2026-09-{day}T00:00:00",
            "content": f"Content {i}",
        })
    for i in range(10):
        sample_results.append({
            "url": f"https://bing.com/undated{i}",
            "title": f"Undated Title {i}",
            "engine": "bing news",
            "publishedDate": None,
            "content": f"Undated Content {i}",
        })

    monkeypatch.setattr(company_news, "_query_searxng", lambda ep, q, timeout=60: {"results": sample_results})
    monkeypatch.setattr(company_news, "fetch", lambda c, t: company_news._fetch_live(c, t, cache_dir=tmp_path))

    res = company_news.fetch("AMD", "AMD")
    rows = res["rows"]
    # Must cap at 15
    assert len(rows) == 15
    # Dated rows first, sorted newest first
    assert rows[0]["date"] == "2026-09-19"
    assert rows[9]["date"] == "2026-09-10"
    # Followed by 5 undated rows in original order
    for j in range(10, 15):
        assert rows[j]["date"] is None
        assert rows[j]["title"] == f"Undated Title {j - 10}"


def test_company_news_cache_reuse(tmp_path, monkeypatch):
    call_count = 0

    def fake_query(ep, q, timeout=60):
        nonlocal call_count
        call_count += 1
        return {"results": [{"url": "https://reuters.com/one", "title": "One", "engine": "reuters"}]}

    monkeypatch.setattr(company_news, "_query_searxng", fake_query)
    monkeypatch.setattr(company_news, "fetch", lambda c, t: company_news._fetch_live(c, t, cache_dir=tmp_path))

    res1 = company_news.fetch("AMD", "AMD")
    assert call_count == 2  # Two queries for initial fetch
    assert len(res1["rows"]) == 1

    res2 = company_news.fetch("AMD", "AMD")
    assert call_count == 2  # Reused cache, no additional queries
    assert len(res2["rows"]) == 1


def test_company_news_failure_recorded_not_raised(tmp_path, monkeypatch):
    def fake_query(ep, q, timeout=60):
        raise RuntimeError("SearXNG connection refused")

    monkeypatch.setattr(company_news, "_query_searxng", fake_query)
    monkeypatch.setattr(company_news, "fetch", lambda c, t: company_news._fetch_live(c, t, cache_dir=tmp_path))

    res = company_news.fetch("AMD", "AMD")
    assert res["rows"] == []
    assert len(res["errors"]) > 0
    assert "SearXNG connection refused" in res["errors"][0]


def test_pack_recent_company_news_live_present_after_section_2_5(screener_data_stub, monkeypatch):
    sample_news = {
        "ticker": "AMD",
        "company": "Advanced Micro Devices",
        "date": "2026-09-24",
        "rows": [
            {
                "date": "2026-09-23",
                "source": "reuters, reuters.com",
                "title": "Meta's Muse rekindles fears over winners and losers",
                "url": "https://reuters.com/muse-ai",
                "snippet": "Meta launched Muse personal AI agent reviving chip thesis.",
            }
        ],
        "unresponsive_engines": [],
        "errors": [],
    }
    monkeypatch.setattr(company_news, "fetch", lambda c, t: sample_news)

    pack = cap.build_pack("AMD")
    # Verify section position: must appear after SECTION 2.5 and before SECTION 3
    idx_25 = pack.find("## DATA 2.5 - PRICE ACTION")
    idx_news = pack.find("## RECENT COMPANY NEWS")
    idx_3 = pack.find("## DATA 3 - TRAILING TWELVE MONTHS")
    assert idx_25 != -1 and idx_news != -1 and idx_3 != -1
    assert idx_25 < idx_news < idx_3

    sec_news = _slice(pack, "RECENT COMPANY NEWS")
    assert "SearXNG news search (Reuters, Bing News), last 30 days, fetched 2026-09-24" in sec_news
    assert "- The stock moved" in sec_news
    assert "in 1 month and" in sec_news
    # S3 C (brief §5.8, C1): this row has a snippet but no excerpt, so build_pack's default
    # (news_snippets=False) drops the snippet — the row prints its first four fields only.
    assert "- 2026-09-23 | reuters, reuters.com | Meta's Muse rekindles fears over winners and losers | https://reuters.com/muse-ai" in sec_news
    assert "Meta launched Muse personal AI agent reviving chip thesis." not in sec_news


def test_pack_recent_company_news_point_in_time_no_network(screener_data_stub, monkeypatch):
    called = False

    def fake_fetch(c, t):
        nonlocal called
        called = True
        return {"rows": []}

    monkeypatch.setattr(company_news, "fetch", fake_fetch)
    pack = cap.build_pack("AMD", asof=date(2026, 3, 31))

    assert not called, "company_news.fetch must not be called in point-in-time mode"
    sec_news = _slice(pack, "RECENT COMPANY NEWS")
    assert "not available (point-in-time) \u2014 the news search cannot be restricted to the briefing date" in sec_news
