"""company_news relevance filters (2026-09-24): ticker-query rows must name the company;
mostly non-Latin rows are dropped."""
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
            return {"results": [{"url": "https://a.example/1", "title": "Lindblad buys White Desert",
                                 "content": "", "engine": "bing news"}]}
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
