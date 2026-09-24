"""E11: the pack reads the top company stories itself (operator, 2026-09-25). Before this the
news section held headlines only; the story behind them reached the analyst only when the
discovery run happened to search for it."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

import company_news  # noqa: E402

YAHOO = ("Lindblad Expeditions (LIND) Buys White Desert Control Oops, something went wrong Skip to "
         "navigation Skip to main content Skip to right column U.S. markets closed US Markets Europe "
         "Markets. Jeff Lewis Mon, September 21, 2026 3 min read LIND Lindblad Expeditions Holdings, Inc. "
         "announced on September 15 that it had acquired 60% of White Desert Antarctica and its new "
         "aviation travel business Echo Charlie, adding high-end Antarctic land travel to its fleet. "
         "The deal expands the company's reach into ultra-premium expedition travel.")


def test_excerpt_skips_page_furniture_and_starts_at_the_lede():
    ex = company_news._excerpt(YAHOO, "Lindblad Expeditions (LIND) Buys White Desert Control", "Lindblad")
    assert ex.startswith("Jeff Lewis") or ex.startswith("LIND Lindblad") or "announced on September 15" in ex[:200]
    assert "Skip to" not in ex and "went wrong" not in ex


def test_excerpt_rejects_unrelated_text_and_subscription_walls():
    other = ("The weather in Seoul was mild this week with light rain expected across the region on "
             "Thursday and Friday, forecasters said, and temperatures will stay seasonal.")
    assert company_news._excerpt(other, "Lindblad Expeditions buys White Desert", "Lindblad") is None
    wall = ("You don't have any Active Subscription. Subscribe now to read Lindblad Expeditions "
            "Holdings news and every premium story, editorial and opinion on our platform today.")
    assert company_news._excerpt(wall, "Lindblad Expeditions buys White Desert", "Lindblad") is None


def test_the_top_stories_are_read_once_and_cached(tmp_path, monkeypatch):
    rows = [{"date": f"2026-09-2{i}", "source": "x", "title": f"Lindblad story {i}", "url": f"https://x.com/{i}",
             "snippet": ""} for i in range(7)]
    monkeypatch.setattr(company_news, "_query_searxng",
                        lambda ep, q, timeout=60: {"results": [{"url": r["url"], "title": r["title"],
                                                                 "publishedDate": r["date"], "engine": "bing news"}
                                                                for r in rows]})
    calls = []
    monkeypatch.setattr(company_news, "_read_article",
                        lambda url, title, name: (calls.append(url) or (f"text of {title}", url + "/copy")))
    out = company_news._fetch_live("Lindblad Expeditions Holdings, Inc.", "LIND", cache_dir=tmp_path)
    assert len(calls) == company_news.READ_TOP == 5
    assert out["excerpts_read"] and out["rows"][0]["excerpt"].startswith("text of") and "read_from" in out["rows"][0]
    company_news._fetch_live("Lindblad Expeditions Holdings, Inc.", "LIND", cache_dir=tmp_path)
    assert len(calls) == 5                      # the cached day is not read again
    cached = json.loads(next(tmp_path.glob("LIND_*.json")).read_text(encoding="utf-8"))
    assert cached["excerpts_read"] is True


def test_the_pack_prints_the_excerpt_under_its_headline(screener_data_stub, monkeypatch):
    import capability_test as cap
    news = {"ticker": "GEV", "company": "GE Vernova", "date": "2026-09-25", "errors": [], "unresponsive_engines": [],
            "rows": [{"date": "2026-09-24", "source": "reuters, reuters.com", "title": "GE Vernova wins order",
                      "url": "https://www.reuters.com/x", "snippet": "s",
                      "excerpt": "GE Vernova said on Thursday it won a 2 GW gas turbine order from a utility.",
                      "read_from": "https://www.aol.com/articles/ge-vernova-order"}]}
    monkeypatch.setattr(company_news, "fetch", lambda c, t: news)
    pack = str(cap.build_pack("GEV"))
    assert "- 2026-09-24 | reuters, reuters.com | GE Vernova wins order |" in pack
    assert "  > read from aol.com: GE Vernova said on Thursday it won a 2 GW gas turbine order" in pack


def test_non_english_pages_do_not_become_excerpts():
    de = ("Die UGI-Aktie steigt nach der Kaufempfehlung von Jefferies deutlich an, und die Anleger freuen sich "
          "über die neue Dividendenstärke des Versorgers, der in sechzehn Ländern Flüssiggas verkauft und "
          "seine Bilanz weiter stärkt.")
    assert company_news._excerpt(de, "Jefferies upgrades UGI to buy from hold", "UGI Aktie") is None
    en = ("Jefferies upgraded UGI Corporation to buy from hold on Tuesday, saying the gas utility's "
          "balance sheet repair and its steady dividend make the shares attractive at the current price, "
          "and it set a price target of $43 for the stock.")
    assert company_news._excerpt(en, "Jefferies upgrades UGI to buy from hold", "UGI") is not None



def test_a_multi_company_headline_cannot_bring_another_companys_paragraph():
    """Fable pre-(b) F2: LIND's news carried Royal Caribbean's fleet paragraph from a roundup."""
    title = "Analysts Conflicted on These Consumer Cyclical Names: Royal Caribbean (RCL), On Holding (ONON)"
    rcl = ("The company operates cruises under the Royal Caribbean International, Celebrity Cruises, and "
           "Silversea Cruises brands, which comprise a range of itineraries across the world's oceans.")
    assert company_news._excerpt(rcl, title, "Lindblad") is None
    lind = ("Lindblad Expeditions said on Tuesday it completed the acquisition of White Desert Antarctica, "
            "adding luxury Antarctic camps and flights to its expedition travel portfolio.")
    assert company_news._excerpt(lind, "Lindblad buys White Desert", "Lindblad") is not None
