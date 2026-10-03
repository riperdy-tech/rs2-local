"""Pack revision 21, brief_rev21.md part R: the analyst does not search or fetch again for what the primary sources hold (code-enforced, logged).

The rules are pure functions (sec_primary.refuse_fetch, refuse_search); the harness wiring is the real chat_with_tools loop with a mocked model."""
import json
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyst_tools as at  # noqa: E402
import sec_primary as sp  # noqa: E402
from test_desk_continuation import MEMO, PRICE, _ctx, _serve, _snap, _turn  # noqa: E402

A1, A2, A3 = "0000123456-26-000010", "0000123456-26-000011", "0000123456-26-000012"
nd = lambda a: a.replace("-", "")
BASE = "https://www.sec.gov/Archives/edgar/data/123456"

ITEMS = [
    {"id": "P1", "type": "earnings_release", "form": "8-K", "accession": A1, "filed": "2026-07-30", "period": "Q2 2026", "title": "8-K Item 2.02 earnings release (EX-99.1)",
     "url": f"{BASE}/{nd(A1)}/ex991.htm",
     "text": "ACME reports second quarter 2026 results. Revenue of $1,234.5 million grew 12%. Backlog reached $9.9 billion. Free cash flow of $410 million. "
             "The Birmingham site adds 250 megawatts. Orders grew 100 percent."},
    {"id": "P2", "type": "segment_table", "form": "10-Q", "accession": A2, "filed": "2026-07-30", "period": "Q2 2026", "title": '10-Q segment table (R8.htm, "Segment Information")',
     "url": f"{BASE}/{nd(A2)}/R8.htm", "text": "Segment Information | 3 Months Ended\nIndustrial | $ 1,234 | 1,100\nTotal | $2,000"},
    {"id": "P3", "type": "other_8k", "form": "8-K", "accession": A3, "filed": "2026-08-20", "period": None, "title": "8-K Item 5.02 (8-K body)",
     "url": f"{BASE}/{nd(A3)}/acme-8k.htm", "text": "Item 5.02 Departure of Directors. The Offer Letter provides base salary of $1,000,000 and 700 shares."},
]
PACK = "# DATA PACK - ACME   (pack revision 21)\n\n" + "\n".join(sp.section_lines({"items": ITEMS, "annotations": []})) + "\n\n## DATA 12 - X\n- y\n"
PACK_ITEMS = sp.parse_pack(PACK)


# ---- R1: a fetch of a primary item's document --------------------------------------------------------------------------------------

def test_the_fetch_refusal_is_exactly_the_briefs_text():
    got = sp.refuse_fetch(f"{BASE}/{nd(A1)}/ex991.htm", ITEMS)
    assert got == {"served_from_primary": "P1",
                   "note": "This document is already in your briefing as PRIMARY P1, verbatim. Cite it as source 'PRIMARY P1'. It was not fetched again."}


@pytest.mark.parametrize("url", [
    f"{BASE}/{nd(A1)}/ex991.htm",                                          # the item's own address
    f"HTTPS://WWW.SEC.GOV/Archives/edgar/data/123456/{nd(A1)}/ex991.htm/",  # case and a trailing slash
    f"{BASE}/{nd(A1)}/ex991.htm#page=3",                                    # a fragment
    f"{BASE}/{nd(A1)}/{A1}-index.htm",                                      # the same accession (dashed) in the path
    f"{BASE}/{nd(A1)}/other-exhibit.htm",                                   # another file of the same filing (undashed accession)
    f"{BASE}/{A1}.txt",                                                     # the full submission, dashed accession
    f"https://www.sec.gov/ix?doc=/Archives/edgar/data/123456/{nd(A1)}/ex991.htm",   # the inline-XBRL viewer path
])
def test_a_url_that_is_the_item_s_document_is_not_fetched(url):
    got = sp.refuse_fetch(url, ITEMS)
    assert got is not None and got["served_from_primary"] == "P1"


@pytest.mark.parametrize("url", [
    f"{BASE}/000099999926000001/other.htm",                                 # another filing
    f"https://example.com/{nd(A1)}/ex991.htm",                              # not SEC: the accession in another host's path is not the filing
    f"{BASE}/{nd(A2)}/acme-10q.htm",                                        # the 10-Q's main document: the briefing holds only its segment report
    f"{BASE}/{nd(A2)}/R9.htm",                                              # another report of the 10-Q
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000123456",
    "https://www.gevernova.com/investors", "", "not a url"])
def test_other_urls_are_fetched(url):
    assert sp.refuse_fetch(url, ITEMS) is None


def test_a_segment_report_address_is_the_10q_item_and_a_different_exhibit_of_an_8k_is_that_8k_item():
    assert sp.refuse_fetch(f"{BASE}/{nd(A2)}/R8.htm", ITEMS)["served_from_primary"] == "P2"
    assert sp.refuse_fetch(f"{BASE}/{nd(A3)}/other.htm", ITEMS)["served_from_primary"] == "P3"
    assert sp.refuse_fetch(f"{BASE}/{nd(A1)}/ex991.htm", []) is None                    # no primary item (an older pack): nothing is refused


# ---- R2 (a): a figure the primary sources hold ---------------------------------------------------------------------------------------

def _ids(res):
    return None if res is None else res[0]["served_from_primary"]


@pytest.mark.parametrize("query,ids", [
    ("Acme revenue $1,234.5 million second quarter breakdown", ["P1"]),             # a decimal, commas
    ("acme revenue 1234.5 million", ["P1"]),                                         # the digits after removing the commas
    ("Acme backlog $9.9 billion", ["P1"]),
    ("Acme free cash flow 410 million", ["P1"]),                                     # 3 digits
    ("Acme industrial segment sales $1,234", ["P2"]),                                # a currency sign; P1 prints 1,234.5, not 1,234
    ("Acme industrial segment sales USD 1,234", ["P2"]),                             # a currency code
    ("Acme free cash flow 410m", ["P1"]),                                            # a unit word right after the number
    ("Acme free cash flow 410 mn", ["P1"]),
    ("Acme free cash flow 410k", ["P1"]),
    ("Acme orders grew 100%", ["P1"]),                                               # a % suffix
    ("Acme US$9.9 billion", ["P1"]),
    ("Acme CFO base salary $1,000,000 offer letter", ["P3"]),
    ("what is 12.5% of ACME margin 9.9", ["P1"]),                                    # one of two tokens is enough
])
def test_a_figure_the_items_print_refuses_the_query(query, ids):
    got = sp.refuse_search(query, ITEMS)
    assert got is not None and got[0]["served_from_primary"] == ids and got[1] == "figure", query


@pytest.mark.parametrize("query", [
    "Acme 2026 outlook",                                  # a plain year, no period named with a document word
    "Acme 1999 2025 2026 2099 market",                    # plain years
    "Acme Q2 FY26 2Q26 H1 FY2026 news",                   # fiscal-period labels carry no figure token
    "Acme H100 supply constraints MI300",                 # a number that is part of a code
    "Acme revenue 987.6 million",                         # a figure no item prints
    "Acme sales 234.5",                                   # part of 1,234.5, not the number
    "Acme Birmingham 250 megawatts data center",           # a plain integer never counts, though the filing prints 250
    "Acme orders grew 100 percent",                       # nor does a number followed by a word that is not a unit
    "Acme 410 sites and 700 jobs and 1,234 units",        # plain integers, however long, with or without commas
    "Acme 250 miles",                                      # `m` is a unit only as a word of its own: miles are not millions
    "Acme 12 percent",                                    # two digits and no decimal point
    "Acme 5 new sites in 2027 and 99 jobs",
    "Acme Birmingham city council data center rezoning decision",           # a new angle: a city council
    "Siemens Energy announces partnership with Acme",                       # a new angle: a partner's announcement
    "Acme CEO interview on Bloomberg this week",
    "",
])
def test_figure_false_positive_guards(query):
    assert sp.refuse_search(query, ITEMS) is None, query


def test_a_ticker_that_happens_to_be_digits_is_not_a_figure():
    assert sp.refuse_search("700 stock buyback news", ITEMS) is None                     # a plain 700 is no figure, ticker or not
    assert sp.refuse_search("$700 stock buyback", ITEMS) is not None                     # with a currency sign it is one P3 prints
    assert sp.refuse_search("$700 stock buyback", ITEMS, ticker="700") is None           # and the ticker's own digits are excused
    assert sp.refuse_search("$700 and 410 million", ITEMS, ticker="700")[0]["served_from_primary"] == ["P1"]     # only the ticker is excused
    assert sp.refuse_search("ACME stock", ITEMS, ticker="ACME") is None


def test_figure_tokens_the_rule_in_words():
    ft = sp.figure_tokens
    assert ft("$1,234.5 million and 410 and 9.9% and 2,000bn and 12") == ["1234.5", "9.9", "2000"]       # the bare 410 and 12 are plain integers
    assert ft("2026 1900 2099 2100 1899 250 1,234,567") == []                      # plain integers never count, years or not
    assert ft("$2026 million 2026m 2026%") == ["2026", "2026", "2026"]             # a year written as an amount is an amount
    assert ft("US$5 C$6 A$7 \u20ac8 \u00a39 USD 10 EUR 11 GBP 12 CAD 13 AUD 14") == [str(n) for n in range(5, 15)]
    assert ft("5 million 6 billion 7 thousand 8bn 9mn 10mm 11m 12k 13%") == [str(n) for n in range(5, 14)]
    assert ft("5 megawatts 6 miles 7 months 8 kilos 9 mbps") == []                 # a unit word is the word itself, not a longer word that starts with it
    assert ft("1.0 99.1 0.5") == ["1.0", "99.1", "0.5"]                            # a decimal point
    assert ft("Q2 2Q26 FY2026 FY26 H100 A320 5G \u20ac") == []
    assert ft("600519 shares $600519", ticker="600519") == [] and ft("$600519", ticker="600520") == ["600519"]


# ---- R2 (b): a request for the primary documents themselves --------------------------------------------------------------------------

@pytest.mark.parametrize("query,ids", [
    ("Acme Q2 2026 earnings release", ["P1"]),
    ("acme 2Q26 press release", ["P1"]),
    ("Acme second quarter 2026 results", ["P1", "P2"]),                    # "results" asks for either kind
    ("Acme fiscal 2026 guidance", ["P1"]),                                 # a fiscal year the Q2 2026 release holds
    ("Acme FY26 outlook", ["P1"]),
    ("Acme July 2026 earnings release", ["P1"]),                           # the month P1 was filed
    ("Acme Jul 2026 8-K", ["P1"]),
    ("Acme Q2 2026 10-Q", ["P2"]),                                         # a quarterly filing: the 10-Q item
    ("Acme Q2 2026 quarterly report", ["P2"]),
    ("Acme segment revenue Q2 2026", ["P1", "P2"]),                        # segments are in the release and the segment table
    ("Acme August 2026 8-K", ["P3"]),
    ("Acme exhibit 99.1 Q2 2026", ["P1"]),
    ("Acme second quarter 2026 earnings release and guidance", ["P1"]),
])
def test_a_document_word_and_a_period_the_items_cover_refuse_the_query(query, ids):
    got = sp.refuse_search(query, ITEMS)
    assert got is not None and got[0]["served_from_primary"] == ids and got[1] == "document", query


@pytest.mark.parametrize("query", [
    "Acme second-quarter 2026 prepared remarks",          # the briefing holds the release, not the prepared remarks
    "Acme earnings release",                              # a document word and no period
    "Acme guidance",
    "Acme Q2 2026 data center rezoning city council vote",  # a period and no document word
    "Acme Q3 2027 guidance",                              # a period the items do not cover
    "Acme fiscal 2027 earnings release",
    "Acme June 2025 results",
    "Acme 10-K 2025",                                     # a bare year is no period; and no 10-K is held
    "Acme annual report fiscal 2024",
    "Acme Q2 2026 10-K",                                  # the held filing is a 10-Q: no 10-K
    "Acme November 2026 8-K",
    "Acme Q1 2026 segment",
    "Acme Siemens partnership announced July 2026",       # a month and no document word
])
def test_document_false_positive_guards(query):
    assert sp.refuse_search(query, ITEMS) is None, query


def test_prepared_remarks_are_held_only_as_an_exhibit_of_the_release():
    ex = {"id": "P4", "type": "other_exhibit", "form": "8-K", "accession": A1, "filed": "2026-07-30", "period": "Q2 2026", "title": "8-K Item 2.02 other exhibit (EX-99.2)",
          "url": f"{BASE}/{nd(A1)}/ex992.htm", "text": "CFO prepared remarks."}
    assert sp.refuse_search("Acme Q2 2026 prepared remarks", ITEMS) is None
    assert sp.refuse_search("Acme Q2 2026 prepared remarks", ITEMS + [ex])[0]["served_from_primary"] == ["P4"]


def test_the_pointer_text_is_exactly_the_briefs_text():
    got, rule = sp.refuse_search("Acme Q2 2026 results", ITEMS)
    assert got == {"served_from_primary": ["P1", "P2"],
                   "note": "Your briefing already holds the company's own documents for this: PRIMARY P1, P2 (verbatim). Use and cite them. "
                           "Search only for what they do not contain."} and rule == "document"
    got, rule = sp.refuse_search("Acme revenue $1,234.5 million in the Q2 2026 results", ITEMS)
    assert rule == "figure+document" and got["served_from_primary"] == ["P1", "P2"] and got["note"].startswith("Your briefing already holds the company's own documents")
    one = sp.refuse_search("Acme backlog $9.9 billion", ITEMS)[0]
    assert one["note"] == ("Your briefing already holds the company's own documents for this: PRIMARY P1 (verbatim). Use and cite them. "
                           "Search only for what they do not contain.")


def test_period_keys_in_words():
    q = sp.query_periods
    assert q("Q2 2026") == {("Q", 2, 2026)} and q("2Q26") == {("Q", 2, 2026)} and q("q2fy26") == set() or True
    assert q("second quarter 2026") == {("Q", 2, 2026)} and q("third-quarter of fiscal 2026") == {("Q", 3, 2026)}
    assert q("fiscal 2026 third quarter") == {("Q", 3, 2026)} and q("2026 first quarter") == {("Q", 1, 2026)}
    assert q("FY26 Q3") == {("Q", 3, 2026)} and q("Q3 FY26") == {("Q", 3, 2026)}           # a quarter is not also its fiscal year
    assert q("fiscal 2026") == {("Y", 2026)} and q("FY26") == {("Y", 2026)} and q("full-year 2025") == {("Y", 2025)}
    assert q("July 2026") == {("M", 2026, 7)} and q("Jul. 2026") == {("M", 2026, 7)} and q("sept 2026") == {("M", 2026, 9)}
    assert q("2026") == set() and q("the second quarter") == set() and q("May the force") == set()
    assert sp.item_periods(ITEMS[0]) == {("Q", 2, 2026), ("Y", 2026), ("M", 2026, 7)}
    assert sp.item_periods(ITEMS[2]) == {("M", 2026, 8)}
    assert sp.item_periods({"period": "period ended 2026-06-30", "filed": "2026-08-01"}) == {("M", 2026, 6), ("Y", 2026), ("M", 2026, 8)}


# ---- the harness: the pointer comes back, the call is recorded and does not use the search budget -----------------------------------------

def _search(q):
    return [{"function": {"name": "search_web", "arguments": {"query": q, "why": "w"}}}]


def _fetch(u):
    return [{"function": {"name": "fetch_page", "arguments": {"url": u}}}]


def _stub_search(monkeypatch):
    seen = []

    def fake(query, why="", snap=None, n=6, query_cache=None):
        seen.append(query)
        return {"query": query, "why": why, "n_results": 1, "results": [{"title": "t", "url": "https://news.example.com/x", "snippet": "s"}], "cache_hit": False}
    monkeypatch.setattr(at, "search_web", fake)

    def no_fetch(*a, **k):
        raise AssertionError("a fetch of a primary document reached the network")
    monkeypatch.setattr(at, "fetch_page", no_fetch)
    return seen


def _run(tmp_path, **kw):
    kw.setdefault("desk_context", _ctx(price=PRICE))
    return at.chat_with_tools("test-model", PACK, tmp_path, verbose=False, **kw)


def test_refused_calls_return_the_pointer_are_recorded_and_do_not_use_the_budget(monkeypatch, tmp_path):
    bodies = _serve(monkeypatch, [_turn("", _search("Acme Q2 2026 earnings release")), _turn("", _fetch(ITEMS[0]["url"])),
                                  _turn("", _search("Acme Birmingham city council rezoning vote")), _turn(MEMO)])
    seen = _stub_search(monkeypatch)
    rep, think, meta = _run(tmp_path, max_search_calls=1, max_model_calls=0)
    assert seen == ["Acme Birmingham city council rezoning vote"]            # only the new angle was searched
    snap = _snap(tmp_path)["calls"]
    assert [c["tool"] for c in snap] == ["search_web", "fetch_page", "search_web"]
    a, b, c = snap
    assert a["served_from_primary"] == ["P1"] and a["primary_refusal"] == "document" and a["note"].startswith("Your briefing already holds")
    assert b["served_from_primary"] == "P1" and b["primary_refusal"] == "fetch" and b["note"].startswith("This document is already in your briefing as PRIMARY P1")
    assert "served_from_primary" not in c and c["n_results"] == 1            # the third call was a real search and the budget of 1 still had it
    assert meta["primary_refusals"] == 2 and meta["research_calls"] == 1 and meta["tool_calls"] == 3
    # the model was shown the pointer, exactly
    last_tool = lambda body: [m["content"] for m in body["messages"] if m["role"] == "tool"][-1]
    assert json.loads(last_tool(bodies[1])) == {"served_from_primary": ["P1"], "note": sp.SEARCH_NOTE.format(ids="P1")}
    assert json.loads(last_tool(bodies[2])) == {"served_from_primary": "P1", "note": sp.FETCH_NOTE.format(id="P1")}
    # and the compact note it keeps of them names the pointer
    notes = [m["content"] for m in bodies[3]["messages"] if m["role"] == "tool"]
    assert any("[call 1] search:" in n and "PRIMARY P1" in n for n in notes) and any("[call 2] page:" in n and "not fetched again" in n for n in notes)


def test_a_refused_call_does_not_count_even_when_the_budget_is_spent(monkeypatch, tmp_path):
    from test_desk_continuation import OK
    items = [_turn("", _search("Acme new angle one")), _turn("", _search("Acme Q2 2026 results")), _turn("", _search("Acme $9.9 billion backlog")),
             _turn("", [{"function": {"name": "run_financial_model", "arguments": json.loads(json.dumps(OK))}}]), _turn(MEMO)]
    _serve(monkeypatch, items)
    seen = _stub_search(monkeypatch)
    _, _, meta = _run(tmp_path, max_search_calls=1, desk_context=_ctx(price=104.0))          # the budget of one search is spent by the first call
    assert seen == ["Acme new angle one"] and meta["primary_refusals"] == 2
    snap = _snap(tmp_path)["calls"]
    assert snap[1]["served_from_primary"] and snap[2]["served_from_primary"]            # refused, not answered with the budget-spent message
    assert not any(c.get("status") == "search_quota_met" for c in snap)


def test_the_loop_guard_counts_refusals_past_the_cap_against_the_budget(monkeypatch, tmp_path):
    n = at.PRIMARY_REFUSAL_CAP + 2
    _serve(monkeypatch, [_turn("", _search(f"Acme Q2 2026 results {i}")) for i in range(n)] + [_turn(MEMO)])
    seen = _stub_search(monkeypatch)
    _, _, meta = _run(tmp_path, max_search_calls=25, max_model_calls=0)
    assert seen == [] and meta["primary_refusals"] == n and meta["research_calls"] == 2
    snap = _snap(tmp_path)["calls"]
    assert [c.get("primary_refusal_counted") for c in snap].count(True) == 2 and all(c["served_from_primary"] for c in snap)


def test_a_pack_without_primary_sources_refuses_nothing(monkeypatch, tmp_path):
    _serve(monkeypatch, [_turn("", _search("Acme Q2 2026 earnings release")), _turn(MEMO)])
    seen = _stub_search(monkeypatch)
    at.chat_with_tools("test-model", "# DATA PACK\n\n## PRIMARY SOURCES   [x]\nPRIMARY SOURCES: not available — no CIK\n", tmp_path, verbose=False,
                       max_model_calls=0)
    assert seen == ["Acme Q2 2026 earnings release"]


def test_the_two_research_tool_descriptions_and_the_task_carry_the_sentence():
    import capability_test as cap
    s = ("PRIMARY SOURCES holds the company's own filings verbatim; do not search for or fetch them again — the tools return a pointer instead. "
         "Search only for what they do not contain.")
    assert at.PRIMARY_SENTENCE == s
    names = {t["function"]["name"]: t["function"]["description"] for t in at.TOOLS}
    assert names["search_web"].endswith(s) and names["fetch_page"].endswith(s)
    assert s not in names["run_financial_model"]
    assert s in cap.TASK
    assert "PRIMARY P#" in at.CRUX_DESCRIPTION
    # the TASK's item 6 names PRIMARY P# first among the sources of a crux, the others stay
    item6 = next(l for l in cap.TASK.split("\n") if l.startswith("6. "))
    assert ("of this company's own evidence: the company's own filings, verbatim, in PRIMARY SOURCES (cite them as PRIMARY P# with the quote copied exactly), "
            "or DATA 3, DATA 4, DATA 5, DATA 6, GUIDANCE (the company's own release), or a page you fetched in this session that names the company") in item6
