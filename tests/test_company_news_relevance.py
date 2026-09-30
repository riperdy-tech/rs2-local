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
             "content": "Linde Bangladesh (LIND)", "engine": "bing news"},
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
    # revision 17, brief C2b: "Retailer lifts outlook" names Five Below only in its snippet, so its headline does not
    # name the company: it is dropped and counted (it was kept by brief C's rule)
    assert sorted(titles) == sorted(["Five Below stock jumps after earnings", "Discount chain shares gain"])
    assert not any("diesel" in t.lower() for t in titles)
    assert out["rows_not_naming"] == 16          # the 15 unrelated rows (both queries return them: counted once) + 1


def test_the_full_cleaned_name_is_a_phrase_in_the_headline_each_word_starting_with_a_capital():
    # revision 17, brief C2b: was "five below opens 200 new stores" (lower case, kept) and a headline "Retail" with the
    # name in the snippet (kept); the case rule and the headline rule now drop both
    assert not _kept("Five Below", "FIVE", "five below opens 200 new stores")
    assert not _kept("Five Below", "FIVE", "Temperatures fall to five below zero")
    assert _kept("Five Below", "FIVE", "FIVE BELOW opens 200 stores")
    assert _kept("Five Below", "FIVE", "Five Below opens 200 new stores")
    assert not _kept("Five Below", "FIVE", "Retail", "Analysts say FIVE BELOW is gaining share")
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
    for text in ("$TGT jumps", "NYSE: TGT rises", "NYSE:TGT rises", "NASDAQ: TGT rises",
                 "(Nasdaq: TGT) rises", "TGT stock rises", "TGT shares rise", "TGT stocks rise"):
        assert _kept("Target Corporation Holdings", "TGT", text), text
    # revision 17, brief C2b: "Retailer (TGT) rises" was kept (the bare "(T)" pattern); it names any company that
    # prints the ticker in parentheses, so it no longer counts
    for text in ("Retailer (TGT) rises", "TGT rises", "tgt stock rises", "$tgt jumps", "TGTX stock rises",
                 "XTGT stock rises", "NYSE: TGTX rises", "TGT-Q stock rises", "the TGT team", "$TGTX"):
        assert not _kept("Target Corporation Holdings", "TGT", text), text
    assert _kept("Berkshire Hathaway", "BRK.B", "BRK.B stock rises")
    assert not _kept("Berkshire Hathaway", "BRK.B", "BRK-B shares rise and BRKXB stock too")


def test_invisible_characters_and_curly_apostrophes_do_not_hide_the_name():
    zw = chr(0x200B)
    assert _kept("Five Below", "FIVE", "Five" + zw + " Below shares rise")
    assert _kept("Kohl's", "KSS", "Kohl" + chr(0x2019) + "s reports earnings")


def test_lind_collisions_are_still_removed_and_lindblad_rows_kept():
    clean = "Lindblad Expeditions Holdings"
    assert not _kept(clean, "LIND", "Linde Bangladesh Stock Price History", "Linde Bangladesh (LIND)")   # the original fixture
    assert not _kept(clean, "LIND", "Linde Bangladesh Stock Price History", "Linde Bangladesh Ltd. trading summary")
    assert _kept(clean, "LIND", "LIND shares rise", "Lindblad Expeditions rose 4%")
    assert _kept(clean, "LIND", "LIND shares rise")                                                  # rule 5: token + finance word
    assert _kept(clean, "LIND", "Lindblad Expeditions (LIND) buys White Desert")
    # revision 17, brief C2b: the headline must name the company; a snippet that does is not enough
    assert not _kept(clean, "LIND", "Cruise line adds ships", "Lindblad Expeditions Holdings, Inc. said on Monday")
    # rule 4: the headline has the first word of the name and the body has the whole name
    assert _kept(clean, "LIND", "Lindblad buys White Desert", "Lindblad Expeditions Holdings agreed to buy White Desert")
    assert not _kept(clean, "LIND", "Lindblad buys White Desert")


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
    # revision 17, brief C2b: the first row names Five Below in its excerpt only, so it is dropped and counted
    assert [r["title"] for r in out["rows"]] == ["Five Below stock falls"]
    assert out["rows_not_naming"] == 2


# ---- revision 17, brief C2b: the headline must name the company ------------------------------------------------------

FX = Path(__file__).resolve().parents[1] / "tools" / "audit_202608" / "tests" / "fixture_data"


def _saved(ticker):
    d = json.loads((FX / f"company_news_{ticker}_20260929.json").read_text(encoding="utf-8"))
    clean = cn._clean_company_name(d["company"], d["ticker"])
    return d["rows"], [r for r in d["rows"]
                       if cn.names_company(clean, d["ticker"], r.get("title"), r.get("snippet"), r.get("excerpt"))]


def test_the_six_saved_final_test_caches_row_by_row():
    dropped_prefixes = {
        "FIVE": None,                                                        # none of the 15 names Five Below
        "HAE": (),                                                           # the German 52-week-high and Vivasure rows stay
        "KALU": ("Best Income Stocks to Buy for September 22nd",
                 "This aluminum stock is bound to bounce back, UBS says"),  # neither headline names the company
        "KMT": (),
        "NUE": ("Nucor tem fornecedores",),                                  # the Portuguese supplier row: nothing confirms it
        "PIPR": ("Meta taps MongoDB", "Grail rallies", "Polymarket taps", "Chime shares jump",
                 "Aon strikes $17 billion"),                                 # the five analyst-quote rows
    }
    counts = {"FIVE": (15, 0), "HAE": (8, 8), "KALU": (8, 6), "KMT": (11, 11), "NUE": (15, 14), "PIPR": (14, 9)}
    total = 0
    for tk, prefixes in dropped_prefixes.items():
        rows, got = _saved(tk)
        assert (len(rows), len(got)) == counts[tk], tk
        total += len(got)
        if prefixes is not None:
            dropped = [r["title"] for r in rows if r not in got]
            assert len(dropped) == len(prefixes), (tk, dropped)
            assert all(any(t.startswith(p) for p in prefixes) for t in dropped), (tk, dropped)
    assert total == 48                                                       # of 71
    titles = {r["title"] for r in _saved("PIPR")[1]}
    assert any(t.startswith("Piper Sandler ouvre un nouveau bureau") for t in titles)   # the French Paris-office row is kept
    assert any(r["title"].startswith("Haemonetics Aktie") for r in _saved("HAE")[1])    # HAE's German 52-week-high row


def test_the_legal_suffix_is_cleaned_from_the_match_name():
    assert cn._match_name("Piper Sandler Companies") == "Piper Sandler"
    assert cn._match_name("The Kroger Co.") == "Kroger"
    assert cn._match_name("Foo Holdings, Inc.") == "Foo"
    assert cn._match_name("Foo & Co") == "Foo"
    assert cn._match_name("Group") == "Group"                                # never empties the name
    assert cn._match_name("Berkshire Hathaway") == "Berkshire Hathaway"


def test_synthetic_naming_cases():
    cases = [
        ("Lindblad Expeditions Holdings", "LIND", "Linde Bangladesh Stock Price History", "Linde Bangladesh (LIND)", False),
        ("Lindblad Expeditions Holdings", "LIND", "LIND shares rise", "", True),
        ("Lindblad Expeditions Holdings", "LIND", "Lindblad buys White Desert", "Lindblad Expeditions Holdings agreed to buy White Desert", True),
        ("Lindblad Expeditions Holdings", "LIND", "Lindblad buys White Desert", "", False),
        ("Lindblad Expeditions Holdings", "LIND", "Lindblad Expeditions (LIND) buys White Desert", "", True),
        ("Five Below", "FIVE", "Five Below stock jumps after earnings", "", True),
        ("Five Below", "FIVE", "Discount chain shares gain", "(NASDAQ: FIVE) closed higher", True),
        ("Five Below", "FIVE", "Retailer lifts outlook", "Five Below, Inc. raised guidance", False),
        ("Five Below", "FIVE", "Temperatures fall to five below zero", "", False),
        ("Five Below", "FIVE", "Five drafting tips for franchise agreements", "", False),
        ("Five Below", "FIVE", "FIVE BELOW opens 200 stores", "", True),
        ("Target", "TGT", "Target practice: the best bows of the year", "", False),
        ("Target", "TGT", "Target opens a new store in Ohio", "The store opens Friday", False),
        ("Target", "TGT", "Target opens a new store in Ohio", "Target said the store opens Friday", True),
        ("Target", "TGT", "Target shares rise", "", True),
        ("Piper Sandler Companies", "PIPR", "Aon strikes $17 billion deal for rival USI", "Piper Sandler analysts said the sale", False),
        ("Piper Sandler Companies", "PIPR", "Piper Sandler ouvre un nouveau bureau \u00e0 Paris", "", True),
        ("Kaiser Aluminum", "KALU", "Kaiser Permanente nurses strike", "", False),
        ("Kaiser Aluminum", "KALU", "Kaiser (KALU) Upgraded to Strong Buy", "", True),
        ("Abcd Widgets", "A", "A global diesel shortage", "", False),
        ("Berkshire Hathaway", "BRK.B", "BRK.B stock rises", "", True),
        ("Berkshire Hathaway", "BRK.B", "BRK-B shares rise and BRKXB stock too", "", False),
        ("Target Corporation Holdings", "TGT", "Retailer (TGT) rises", "", False),
        ("Target Corporation Holdings", "TGT", "TGT rises", "", False),
        ("Target Corporation Holdings", "TGT", "TGT-Q stock rises", "", False),
    ]
    for clean, tk, title, snippet, expected in cases:
        assert _kept(clean, tk, title, snippet) is expected, (clean, tk, title, snippet)


def test_rule_forms_one_word_confirmations_and_tickers():
    assert _kept("Target", "TGT", "Target opens a new store", "Target Corporation said on Friday")   # N + legal word in B
    assert _kept("Target", "TGT", "Target opens a new store", "Retailer Target (TGT) said on Friday")  # N (T)
    assert _kept("Target", "TGT", "Target opens a new store (NYSE: TGT)")                               # rule 2 in H
    assert not _kept("Target", "TGT", "Target opens a new store", "The TGT ticker")                    # T in the body alone
    assert _kept("Ørsted", "ORSTED", "Ørsted shares rise")                                             # a non-ASCII capital
    assert not _kept("Ørsted", "ORSTED", "ørsted shares rise")
    assert not _kept("Abcd Widgets", "AB", "AB stock rises")                # a two-character ticker never counts under rule 5
    assert _kept("Abcd Widgets", "ABC", "ABC stock rises")
    assert not _kept("Abcd Widgets", "ABC", "ABC.com stock rises")           # ".letter" after the ticker


def test_rows_not_naming_is_counted_saved_and_added_to_on_a_cached_day(monkeypatch, tmp_path):
    def fake_query(url, q, timeout=60):
        return {"results": [
            {"url": "https://a.example/1", "title": "Five Below shares rise", "content": "", "engine": "bing news"},
            {"url": "https://a.example/2", "title": "Global diesel shortage", "content": "x", "engine": "reuters"},
            {"url": "https://a.example/2/", "title": "Global diesel shortage again", "content": "x", "engine": "reuters"},
            {"url": "https://a.example/3", "title": "Five drafting tips", "content": "", "engine": "reuters"},
            {"url": "https://marketbeat.com/4", "title": "Low trust row", "content": "", "engine": "reuters"},
            {"url": "https://a.example/5", "title": "\u4e0e\u5408\u4f5c\u52a0\u901f\u7ea7\u81ea\u52a8\u9a7e\u9a76", "content": "", "engine": "reuters"},
        ]}
    monkeypatch.setattr(cn, "_query_searxng", fake_query)
    out = cn._fetch_live("Five Below, Inc.", "FIVE", searx_url="http://x", cache_dir=tmp_path)
    assert [r["title"] for r in out["rows"]] == ["Five Below shares rise"]
    # counted: the two diesel rows (one url) and the drafting-tips row; not the low-trust or the non-Latin row
    assert out["rows_not_naming"] == 2
    today = cn.datetime.now(cn.timezone.utc).strftime("%Y-%m-%d")
    saved = json.loads((tmp_path / f"FIVE_{today}.json").read_text(encoding="utf-8"))
    assert saved["rows_not_naming"] == 2
    # a cached day re-filtered adds the rows it drops to the count already saved
    saved["rows"].append({"date": "2026-09-25", "source": "s", "title": "Another diesel row", "url": "https://a.example/9",
                          "snippet": ""})
    (tmp_path / f"FIVE_{today}.json").write_text(json.dumps(saved), encoding="utf-8")
    monkeypatch.setattr(cn, "_query_searxng", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no search on a cached day")))
    again = cn._fetch_live("Five Below, Inc.", "FIVE", searx_url="http://x", cache_dir=tmp_path)
    assert [r["title"] for r in again["rows"]] == ["Five Below shares rise"]
    assert again["rows_not_naming"] == 3
