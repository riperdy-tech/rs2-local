"""company_news relevance filters (2026-09-24): ticker-query rows must name the company;
mostly non-Latin rows are dropped."""
import json
from pathlib import Path

import company_news as cn


def test_name_token():
    assert cn._name_token("Lindblad Expeditions Holdings") == "Lindblad"
    assert cn._name_token("Advanced Micro Devices") == "Micro"
    assert cn._name_token("UGI") is None


def test_mostly_non_latin():
    assert cn._mostly_non_latin("DXC Engineering\u4e0eLOXO\u5408\u4f5c\u52a0\u901fL4\u7ea7\u81ea\u52a8\u9a7e\u9a76\u5546\u7528\u8f66\u90e8\u7f72")
    assert not cn._mostly_non_latin("DXC Technology ernennt Jonathan Nikols zum Pr\u00e4sidenten")


def test_ticker_query_rows_must_name_the_company(monkeypatch, tmp_path):
    def fake_query(url, q, timeout=60):
        if q.startswith('"'):
            # revision 17 (C2): the quoted-name query's rows are filtered too, so this one names the company
            return {"results": [{"url": "https://a.example/1", "title": "Lindblad buys White Desert",
                                 "content": "Lindblad Expeditions Holdings agreed to buy White Desert",
                                 "engine": "bing news"}]}
        return {"results": [
            {"url": "https://b.example/2", "title": "Linde Bangladesh Stock Price History",
             # revision 17 (C2): the snippet no longer carries "(LIND)": the ticker in parentheses is one of the
             # rule's finance patterns, so a row that prints it passes whatever company it is about
             "content": "Linde Bangladesh Ltd. trading summary", "engine": "bing news"},
            {"url": "https://c.example/3", "title": "LIND shares rise",
             "content": "Lindblad Expeditions rose 4%", "engine": "bing news"},
        ]}
    monkeypatch.setattr(cn, "_query_searxng", fake_query)
    out = cn._fetch_live("Lindblad Expeditions Holdings, Inc.", "LIND", searx_url="http://x",
                         cache_dir=tmp_path)
    titles = [r["title"] for r in out["rows"]]
    assert "Linde Bangladesh Stock Price History" not in titles
    assert "LIND shares rise" in titles and "Lindblad buys White Desert" in titles


# ---- revision 17, brief C2: a row must name the company ---------------------------------------------------------

FIVE_ROWS = json.loads((Path(__file__).resolve().parents[1] / "tools" / "audit_202608" / "tests" / "fixture_data"
                        / "company_news_FIVE_20260929.json").read_text(encoding="utf-8"))["rows"]


def _kept(clean, ticker, title, snippet="", excerpt=""):
    return cn.names_company(clean, ticker, title, snippet, excerpt)


def test_fives_saved_rows_none_of_which_names_five_below_are_all_removed():
    assert len(FIVE_ROWS) == 15
    diesel = [r for r in FIVE_ROWS if "diesel" in r["title"].lower()]
    assert len(diesel) == 1                                    # the Reuters story that reached FIVE's block
    for r in FIVE_ROWS:
        assert not _kept("Five Below", "FIVE", r["title"], r["snippet"]), r["title"]


def test_fives_rows_are_removed_from_both_queries_and_five_below_rows_are_kept(monkeypatch, tmp_path):
    five_below = [
        {"url": "https://a.example/1", "title": "Five Below stock jumps after earnings", "content": "", "engine": "bing news"},
        {"url": "https://a.example/2", "title": "Retailer lifts outlook", "content": "Five Below, Inc. raised guidance", "engine": "bing news"},
        {"url": "https://a.example/3", "title": "Discount chain shares gain", "content": "(NASDAQ: FIVE) closed higher", "engine": "bing news"},
    ]
    others = [{"url": r["url"], "title": r["title"], "content": r["snippet"], "engine": "reuters",
               "publishedDate": r["date"]} for r in FIVE_ROWS]

    def fake_query(url, q, timeout=60):
        # both queries return the unrelated Reuters rows; the quoted-name query is no longer exempt
        return {"results": others + (five_below if q.startswith('"') else [])}

    monkeypatch.setattr(cn, "_query_searxng", fake_query)
    monkeypatch.setattr(cn, "_read_article", lambda url, title, name: (None, None))
    out = cn._fetch_live("Five Below, Inc.", "FIVE", searx_url="http://x", cache_dir=tmp_path)
    titles = [r["title"] for r in out["rows"]]
    assert sorted(titles) == sorted(["Five Below stock jumps after earnings", "Retailer lifts outlook",
                                     "Discount chain shares gain"])
    assert not any("diesel" in t.lower() for t in titles)


def test_the_full_cleaned_name_is_a_phrase_matched_case_insensitively():
    assert _kept("Five Below", "FIVE", "five below opens 200 new stores")
    assert _kept("Five Below", "FIVE", "Retail", "Analysts say FIVE BELOW is gaining share")
    assert not _kept("Five Below", "FIVE", "Below average: five markets to watch")
    assert not _kept("Five Below", "FIVE", "Five stores opened below plan")           # the words apart are not the name
    assert _kept("Advanced Micro Devices", "AMD", "Advanced   Micro\nDevices unveils a chip")


def test_a_one_word_name_needs_a_finance_word_in_the_same_row():
    assert not _kept("Target", "TGT", "Target practice: the best bows of the year")
    assert not _kept("Target", "TGT", "Target opens a new store in Ohio", "The store opens Friday")
    for word in ("stock", "shares", "earnings", "revenue", "guidance", "quarter", "dividend", "analyst", "CEO",
                 "Inc", "Corp", "NYSE", "NASDAQ"):
        assert _kept("Target", "TGT", f"Target news: {word} update"), word
    assert _kept("Target", "TGT", "Target opens a new store in Ohio", "Analysts expect more openings")   # in the snippet
    assert _kept("Target", "TGT", "Target opens a new store", "", "The retailer's shares rose Friday.")    # in the excerpt
    assert not _kept("Target", "TGT", "Target opens a new store", "", "Stockholm hosts the fair; sharesies is an app.")


def test_the_ticker_counts_only_in_a_finance_pattern_and_in_exact_case():
    for text in ("$TGT jumps", "Retailer (TGT) rises", "NYSE: TGT rises", "NYSE:TGT rises", "NASDAQ: TGT rises",
                 "(Nasdaq: TGT) rises", "TGT stock rises", "TGT shares rise", "TGT stocks rise"):
        assert _kept("Target Corporation Holdings", "TGT", text), text
    for text in ("TGT rises", "tgt stock rises", "$tgt jumps", "TGTX stock rises", "XTGT stock rises",
                 "NYSE: TGTX rises", "TGT-Q stock rises", "the TGT team", "$TGTX"):
        assert not _kept("Target Corporation Holdings", "TGT", text), text
    assert _kept("Berkshire Hathaway", "BRK.B", "BRK.B stock rises")
    assert not _kept("Berkshire Hathaway", "BRK.B", "BRK-B shares rise and BRKXB stock too")


def test_invisible_characters_and_curly_apostrophes_do_not_hide_the_name():
    zw = chr(0x200B)
    assert _kept("Five Below", "FIVE", "Five" + zw + " Below shares rise")
    assert _kept("Kohl's", "KSS", "Kohl" + chr(0x2019) + "s reports earnings")


def test_lind_collisions_are_still_removed_and_lindblad_rows_kept():
    clean = "Lindblad Expeditions Holdings"
    assert not _kept(clean, "LIND", "Linde Bangladesh Stock Price History", "Linde Bangladesh Ltd. trading summary")
    assert _kept(clean, "LIND", "LIND shares rise", "Lindblad Expeditions rose 4%")
    assert _kept(clean, "LIND", "Lindblad Expeditions (LIND) buys White Desert")
    assert _kept(clean, "LIND", "Cruise line adds ships", "Lindblad Expeditions Holdings, Inc. said on Monday")


def test_a_cached_days_rows_are_held_to_the_same_rule_with_their_excerpt(monkeypatch, tmp_path):
    rows = [
        {"date": "2026-09-25", "source": "s", "title": "Retailer lifts outlook", "url": "https://a.example/1",
         "snippet": "", "excerpt": "Five Below, Inc. said on Thursday it raised its full-year outlook."},
        {"date": "2026-09-24", "source": "s", "title": "Global diesel shortage likely to last", "url": "https://a.example/2",
         "snippet": "A global diesel shortage fueled by wars"},
        {"date": "2026-09-23", "source": "s", "title": "Five Below stock falls", "url": "https://a.example/3", "snippet": ""},
    ]
    today = cn.datetime.now(cn.timezone.utc).strftime("%Y-%m-%d")
    (tmp_path / f"FIVE_{today}.json").write_text(
        json.dumps({"ticker": "FIVE", "company": "Five Below, Inc.", "date": today, "rows": rows,
                    "unresponsive_engines": [], "errors": [], "excerpts_read": True}), encoding="utf-8")
    monkeypatch.setattr(cn, "_query_searxng", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no search on a cached day")))
    out = cn._fetch_live("Five Below, Inc.", "FIVE", cache_dir=tmp_path)
    assert [r["title"] for r in out["rows"]] == ["Retailer lifts outlook", "Five Below stock falls"]
