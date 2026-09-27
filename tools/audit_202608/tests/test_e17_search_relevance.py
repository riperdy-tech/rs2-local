"""E17 A2 search relevance tests."""
import gzip
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import analyst_tools as at


class _FakeResp(io.BytesIO):
    def __init__(self, obj):
        super().__init__(json.dumps(obj).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_related_to_query_hand_cases():
    q = "Amphenol APH stock news guidance late September 2026"
    bing_results = [
        {"title": "Search - Microsoft Bing", "url": "https://www.bing.com/", "snippet": ""},
        {"title": "Bing", "url": "https://www.bing.com/webhp", "snippet": ""},
        {"title": "Bing", "url": "https://www.bing.com/set/homepage", "snippet": ""},
    ]
    for r in bing_results:
        assert at.related_to_query(q, r) is False

    google_news_result = {
        "title": "Amphenol raises 2026 sales guidance amid strong demand",
        "url": "https://news.google.com/stories/12345",
        "snippet": "Amphenol reported higher third quarter revenue and updated outlook.",
    }
    assert at.related_to_query(q, google_news_result) is True

    # Query with no content word returns None
    assert at.related_to_query("2026 Q2", {"title": "Company results", "url": "https://example.com", "snippet": ""}) is None


def test_search_web_12_mocked_results(monkeypatch):
    results_12 = [
        {"title": f"Amphenol Story {i}", "url": f"https://source{i}.com/a", "content": "Amphenol connector news"}
        for i in range(5)
    ] + [
        {"title": f"Unrelated {i}", "url": f"https://other{i}.com/b", "content": "vacation weather"}
        for i in range(6)
    ] + [
        {"title": "Low trust Amphenol", "url": "https://simplywall.st/amphenol", "content": "Amphenol question"}
    ]

    monkeypatch.setattr(at.urllib.request, "urlopen",
                        lambda req, *a, **k: _FakeResp({"results": results_12, "unresponsive_engines": ["bing"]}))

    res = at.search_web("Amphenol connector news", "test why", snap=[], query_cache={})

    # serves the 5 in order
    assert len(res["results"]) == 5
    assert res["n_results"] == 5
    for i, r in enumerate(res["results"]):
        assert r["title"] == f"Amphenol Story {i}"
        assert r["url"] == f"https://source{i}.com/a"

    # set_aside.count = 6 with their hosts
    sa = res.get("set_aside")
    assert sa is not None
    assert sa["count"] == 6
    assert len(sa["hosts"]) == 6
    for i in range(6):
        assert f"other{i}.com" in sa["hosts"]

    # _audit_results has 12 entries
    audit = res.get("_audit_results")
    assert audit is not None
    assert len(audit) == 12

    # no _audit key in the tool message
    msg, cut = at.tool_message("search_web", {"query": "Amphenol connector news"}, res)
    parsed = json.loads(msg)
    assert not any(k.startswith("_audit") for k in parsed)


def test_search_web_9_related_serves_first_6(monkeypatch):
    r9 = [{"title": f"Amphenol news {i}", "url": f"https://ex{i}.com/a", "content": "Amphenol connector"} for i in range(9)]
    monkeypatch.setattr(at.urllib.request, "urlopen",
                        lambda req, *a, **k: _FakeResp({"results": r9}))

    res = at.search_web("Amphenol news", "test why", snap=[], query_cache={})
    assert len(res["results"]) == 6
    assert res["n_results"] == 6
    assert "set_aside" not in res


def test_search_web_0_related_serves_none_and_sets_aside_all(monkeypatch):
    r0 = [{"title": f"Unrelated {i}", "url": f"https://ex{i}.com/a", "content": "vacation weather"} for i in range(8)]
    monkeypatch.setattr(at.urllib.request, "urlopen",
                        lambda req, *a, **k: _FakeResp({"results": r0}))

    res = at.search_web("Amphenol news", "test why", snap=[], query_cache={})
    assert len(res["results"]) == 0
    assert res["n_results"] == 0
    assert res["set_aside"]["count"] == 8


def test_search_web_no_content_word_serves_first_6(monkeypatch):
    r_nc = [{"title": f"Story {i}", "url": f"https://ex{i}.com/a", "content": "something"} for i in range(8)]
    monkeypatch.setattr(at.urllib.request, "urlopen",
                        lambda req, *a, **k: _FakeResp({"results": r_nc}))

    res = at.search_web("2026 Q2", "test why", snap=[], query_cache={})
    assert len(res["results"]) == 6
    assert res["n_results"] == 6
    assert "set_aside" not in res


def test_search_corpus_counts():
    corpus_path = Path(__file__).resolve().parent / "fixture_data" / "e17" / "search_corpus.json.gz"
    with gzip.open(corpus_path, "rt", encoding="utf-8") as f:
        corpus = json.load(f)

    # valuation: 212 queries, 1,272 results, 790 related, 482 set aside, 1 query with none related
    v_queries = corpus["groups"]["valuation"]
    assert len(v_queries) == 212
    v_total_r = sum(len(q["r"]) for q in v_queries)
    assert v_total_r == 1272
    v_rel = 0
    v_set_aside = 0
    v_none_rel = 0
    for q in v_queries:
        q_rel = 0
        for item in q["r"]:
            t, u, s = item
            if at.related_to_query(q["q"], {"title": t, "url": u, "snippet": s}):
                v_rel += 1
                q_rel += 1
            else:
                v_set_aside += 1
        if q_rel == 0:
            v_none_rel += 1

    assert v_rel == 790
    assert v_set_aside == 482
    assert v_none_rel == 1

    v_exp = corpus["expected"]["valuation"]
    assert v_exp["queries"] == 212
    assert v_exp["results"] == 1272
    assert v_exp["related"] == 790
    assert v_exp["set_aside"] == 482
    assert v_exp["queries_with_no_related_result"] == 1

    # discovery: 225 queries, 1,350 results, 891 related, 459 set aside, 0 queries with none related
    d_queries = corpus["groups"]["discovery"]
    assert len(d_queries) == 225
    d_total_r = sum(len(q["r"]) for q in d_queries)
    assert d_total_r == 1350
    d_rel = 0
    d_set_aside = 0
    d_none_rel = 0
    for q in d_queries:
        q_rel = 0
        for item in q["r"]:
            t, u, s = item
            if at.related_to_query(q["q"], {"title": t, "url": u, "snippet": s}):
                d_rel += 1
                q_rel += 1
            else:
                d_set_aside += 1
        if q_rel == 0:
            d_none_rel += 1

    assert d_rel == 891
    assert d_set_aside == 459
    assert d_none_rel == 0

    d_exp = corpus["expected"]["discovery"]
    assert d_exp["queries"] == 225
    assert d_exp["results"] == 1350
    assert d_exp["related"] == 891
    assert d_exp["set_aside"] == 459
    assert d_exp["queries_with_no_related_result"] == 0


def test_hand_labels():
    hand_path = Path(__file__).resolve().parent / "fixture_data" / "e17" / "hand_labels.json"
    data = json.loads(hand_path.read_text(encoding="utf-8"))
    items = data["items"]
    assert len(items) == 90

    off_set_aside = 0
    kept_on = 0
    kept_weak = 0
    kept_off = 0

    for item in items:
        q = item["q"]
        res = {"title": item["title"], "url": item["url"], "snippet": item["snippet"]}
        rule_rel = at.related_to_query(q, res)
        assert rule_rel == item["rule_related"]
        if not rule_rel:
            assert item["label"] == "off"
            off_set_aside += 1
        else:
            if item["label"] == "on":
                kept_on += 1
            elif item["label"] == "weak":
                kept_weak += 1
            elif item["label"] == "off":
                kept_off += 1

    assert off_set_aside == 45
    assert kept_on == 35
    assert kept_weak == 6
    assert kept_off == 4
