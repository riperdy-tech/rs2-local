"""Pack revision 21, the coordinator's review rulings: a fetch of a cut item is allowed, the latest annual report's segment table, foreign filers, the figure rule.
(The figure rule's own cases are in test_rev21_refusals.py.) Fixtures only."""
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
from test_rev21_primary import ACC_10Q, ACC_8K1, ACC_REL, BASE, CIK, FakeSEC, STANDARD_ROWS, acc_url, release_html, standard_files, sub_txt  # noqa: E402

ACC_10K = "0000123456-25-000020"
ACC_20F = "0000123456-26-000030"


def periodic_files(acc, fy, label="Segment Information", rfile="R8.htm", quarter=None):
    focus = quarter or "FY"
    return {
        acc_url(acc, "FilingSummary.xml"): f"<FilingSummary><Report><HtmlFileName>R1.htm</HtmlFileName><ShortName>COVER</ShortName></Report><Report><HtmlFileName>{rfile}</HtmlFileName><ShortName>{label}</ShortName></Report></FilingSummary>",
        acc_url(acc, "R1.htm"): ("<DOCUMENT>\n<TYPE>XML\n<TEXT>\n<html><body><table><tr><td>Document Fiscal Period Focus</td><td>" + focus + "</td></tr>"
                                 "<tr><td>Document Fiscal Year Focus</td><td>" + str(fy) + "</td></tr></table></body></html>\n</TEXT>\n</DOCUMENT>"),
        acc_url(acc, rfile): ("<DOCUMENT>\n<TYPE>XML\n<TEXT>\n<html><body><table class=\"report\"><tr><th>" + label + "</th><th>12 Months Ended</th></tr>"
                              "<tr><td>Utilities</td><td>$ 4,321</td></tr><tr><td>AmeriGas Propane</td><td>$ 2,468</td></tr></table></body></html>\n</TEXT>\n</DOCUMENT>"),
    }


def with_annual(monkeypatch, rows_extra=(), files_extra=None):
    rows = list(STANDARD_ROWS) + [("10-K", "2025-11-20", "2025-09-30", "", ACC_10K)] + list(rows_extra)
    f = standard_files()
    f.update(periodic_files(ACC_10K, 2025))
    f.update(files_extra or {})
    return FakeSEC(monkeypatch, rows, f)


# ---- ruling 1: a fetch of a document cut to its cap is allowed ---------------------------------------------------------------------

def _item(id_, text, **kw):
    return dict({"id": id_, "type": "earnings_release", "form": "8-K", "accession": "0000123456-26-000010", "filed": "2026-07-30", "period": "Q2 2026",
                 "title": "8-K Item 2.02 earnings release (EX-99.1)", "url": f"{BASE}/000012345626000010/ex991.htm", "text": text}, **kw)


CUT = "start of a long release\n[… 9,412 characters omitted …]\nthe guidance paragraph"


def test_a_complete_item_refuses_the_fetch_and_a_cut_item_allows_it():
    done, cut = _item("P1", "the whole release"), _item("P1", CUT)
    assert sp.is_truncated(cut) and not sp.is_truncated(done)
    assert sp.refuse_fetch(done["url"], [done])["served_from_primary"] == "P1"
    assert sp.refuse_fetch(cut["url"], [cut]) is None
    assert sp.fetch_hint(cut["url"], [cut]) == {"partly_from_primary": "P1", "primary_note": "This document is partly in your briefing as PRIMARY P1; the rest is fetched."}
    assert sp.fetch_hint(done["url"], [done]) is None and sp.fetch_hint("https://example.com/x", [cut]) is None
    # by accession too: another file of a cut 8-K filing is fetched and says so; of a complete one it is refused
    other = f"{BASE}/000012345626000010/other.htm"
    assert sp.refuse_fetch(other, [cut]) is None and sp.fetch_hint(other, [cut])["partly_from_primary"] == "P1"
    assert sp.refuse_fetch(other, [done])["served_from_primary"] == "P1"


def test_a_marker_in_a_built_item_makes_it_cut_and_a_short_one_complete(monkeypatch):
    f = standard_files()
    f[acc_url(ACC_REL)] = sub_txt([("EX-99.1", "ex991.htm", release_html(n_filler=80)), ("EX-99.2", "ex992.htm", "<html><body><p>Short remarks.</p></body></html>")])
    FakeSEC(monkeypatch, STANDARD_ROWS, f)
    its = sp.build(CIK, "2026-09-01")["items"]
    assert sp.is_truncated(its[0]) and not sp.is_truncated(its[1])
    assert sp.refuse_fetch(its[0]["url"], its) is None and sp.refuse_fetch(its[1]["url"], its)["served_from_primary"] == "P2"


def _fetch_session(monkeypatch, tmp_path, items, url):
    pack = "# P\n\n" + "\n".join(sp.section_lines({"items": items, "annotations": []})) + "\n\n## DATA 12 - X\n"
    calls = []

    def fake_fetch(u, snap=None, cap=9000, url_cache=None, known_urls=None, _fallback=True):
        calls.append(u)
        return {"url": u, "part": 1, "parts": 1, "chars": 11, "text": "release text", "cache_hit": False}
    _serve(monkeypatch, [_turn("", [{"function": {"name": "fetch_page", "arguments": {"url": url}}}]), _turn(MEMO)])
    monkeypatch.setattr(at, "fetch_page", fake_fetch)
    rep, _, meta = at.chat_with_tools("m", pack, tmp_path, verbose=False, max_model_calls=0, desk_context=_ctx(price=PRICE))
    return calls, _snap(tmp_path)["calls"][0], meta


def test_the_harness_fetches_a_cut_item_and_the_result_says_partly_in_the_briefing(monkeypatch, tmp_path):
    cut = _item("P1", CUT)
    calls, rec, meta = _fetch_session(monkeypatch, tmp_path, [cut], cut["url"])
    assert calls == [cut["url"]] and rec["text"] == "release text" and meta["primary_refusals"] == 0 and meta["research_calls"] == 1     # a real fetch, on the budget
    assert rec["partly_from_primary"] == "P1" and rec["primary_note"] == "This document is partly in your briefing as PRIMARY P1; the rest is fetched."
    assert "served_from_primary" not in rec                                                    # a fetch, not a refusal


def test_the_harness_still_refuses_the_fetch_of_a_complete_item(monkeypatch, tmp_path):
    done = _item("P1", "the whole release")
    calls, rec, meta = _fetch_session(monkeypatch, tmp_path, [done], done["url"])
    assert calls == [] and rec["served_from_primary"] == "P1" and meta["primary_refusals"] == 1 and meta["research_calls"] == 0


# ---- ruling 2: the latest annual report's segment table ---------------------------------------------------------------------------

def test_a_10q_is_followed_by_the_latest_10k_segment_report_as_its_own_item(monkeypatch):
    with_annual(monkeypatch)
    res = sp.build(CIK, "2026-09-01")
    assert [i["type"] for i in res["items"]] == ["earnings_release", "other_exhibit", "segment_table", "segment_annual", "other_8k", "other_8k"]
    seg, ann = res["items"][2], res["items"][3]
    assert seg["form"] == "10-Q" and ann["form"] == "10-K" and ann["accession"] == ACC_10K and ann["filed"] == "2025-11-20" and ann["period"] == "FY 2025"
    assert ann["title"] == '10-K annual segment table (R8.htm, "Segment Information")' and ann["url"] == acc_url(ACC_10K, "R8.htm")
    assert ann["text"].startswith("Segment Information | 12 Months Ended\nUtilities | $ 4,321\nAmeriGas Propane | $ 2,468") and len(ann["text"]) <= sp.SEGMENT_CAP
    assert [i["id"] for i in res["items"]] == [f"P{n}" for n in range(1, 7)]
    # the pack text and its parse keep the type
    parsed = sp.parse_pack("\n".join(sp.section_lines(res)))
    assert [i["type"] for i in parsed] == [i["type"] for i in res["items"]] and parsed[3]["title"] == ann["title"]
    assert [f["type"] for f in sp.facts_items(res["items"])][3] == "segment_annual"


def test_the_annual_item_is_matched_only_by_its_own_address_and_by_a_document_word_and_its_fiscal_year(monkeypatch):
    with_annual(monkeypatch)
    items = sp.build(CIK, "2026-09-01")["items"]
    ann = items[3]
    assert sp.refuse_fetch(ann["url"], items)["served_from_primary"] == ann["id"]
    assert sp.refuse_fetch(acc_url(ACC_10K, "acme-10k.htm"), items) is None                 # the 10-K's other pages are not in the briefing
    assert sp.refuse_fetch(acc_url(ACC_10K, "R9.htm"), items) is None
    got = sp.refuse_search("UGI-like FY2025 10-K segment revenue AmeriGas Propane", items)
    assert got is not None and got[0]["served_from_primary"] == [ann["id"]] and got[1] == "document"
    assert sp.refuse_search("Acme fiscal 2025 annual report", items)[0]["served_from_primary"] == [ann["id"]]
    assert sp.refuse_search("Acme 10-K 2025 segment revenue", items) is None              # a bare year is no period
    assert sp.refuse_search("Acme FY2024 10-K segment revenue", items) is None            # a year the item does not cover
    # the quarterly report is the 10-Q item, not the annual one
    assert sp.refuse_search("Acme Q2 2026 quarterly report", items)[0]["served_from_primary"] == [items[2]["id"]]


def test_no_annual_item_when_the_latest_periodic_filing_is_a_10k_or_there_is_no_10k(monkeypatch):
    rows = [r for r in STANDARD_ROWS if r[0] != "10-Q"] + [("10-K", "2026-07-30", "2026-06-30", "", ACC_10Q)]
    f = standard_files()
    f.update(periodic_files(ACC_10Q, 2026))
    FakeSEC(monkeypatch, rows, f)
    res = sp.build(CIK, "2026-09-01")
    assert [i["type"] for i in res["items"]].count("segment_annual") == 0 and [i["type"] for i in res["items"]].count("segment_table") == 1
    FakeSEC(monkeypatch, STANDARD_ROWS, standard_files())                                  # a 10-Q and no 10-K
    res = sp.build(CIK, "2026-09-01")
    assert not any(i["type"] == "segment_annual" for i in res["items"]) and any("No 10-K, 20-F or 40-F on or before 2026-09-01" in a for a in res["annotations"])


def test_an_annual_report_without_a_segment_report_is_annotated(monkeypatch):
    f = standard_files()
    f.update(periodic_files(ACC_10K, 2025, label="Leases", rfile="R3.htm"))
    FakeSEC(monkeypatch, list(STANDARD_ROWS) + [("10-K", "2025-11-20", "2025-09-30", "", ACC_10K)], f)
    res = sp.build(CIK, "2026-09-01")
    assert not any(i["type"] == "segment_annual" for i in res["items"])
    assert any(ACC_10K in a and "annual segment table is not filed as a separate report" in a for a in res["annotations"])


def test_the_annual_item_is_cut_first_under_the_total_cap():
    mk = lambda id_, typ, filed, n: {"id": id_, "type": typ, "title": f"{typ} {filed}", "accession": "a", "filed": filed, "text": "q" * n}
    items = [mk("P1", "earnings_release", "2026-07-30", 14000), mk("P2", "segment_table", "2026-07-30", 6000), mk("P3", "segment_annual", "2025-11-20", 6000),
             mk("P4", "other_8k", "2026-08-20", 2500), mk("P5", "other_8k", "2026-08-10", 2500)]       # 31,000
    out = sp._trim(items, [])
    assert [len(i["text"]) for i in out] == [14000, 6000, 5000, 2500, 2500]                          # the annual table gave up the 1,000 over the cap
    items = [mk("P1", "earnings_release", "2026-07-30", 14000), mk("P2", "other_exhibit", "2026-07-30", 6000), mk("P3", "segment_table", "2026-07-30", 6000),
             mk("P4", "segment_annual", "2025-11-20", 700), mk("P5", "other_8k", "2026-08-10", 4000)]     # 30,700: the annual table cannot give 700 and stay 600
    out = sp._trim(items, [])
    assert [i["id"] for i in out] == ["P1", "P2", "P3", "P5"] and sum(len(i["text"]) for i in out) <= sp.TOTAL_CAP


# ---- ruling 3: foreign filers --------------------------------------------------------------------------------------------------------

def six(acc, body, ex_type="EX-99.1", desc="Press release", fname="ex.htm"):
    return sub_txt([("6-K", "main.htm", "<html><body><p>Form 6-K report of foreign private issuer</p></body></html>"), (ex_type, fname, body)]).replace(
        f"<FILENAME>{fname}\n<DESCRIPTION>d", f"<FILENAME>{fname}\n<DESCRIPTION>{desc}")


def foreign_setup(monkeypatch, extra_rows=(), extra_files=None):
    A = lambda n: f"0000123456-26-0001{n:02d}"
    rows = [("6-K", "2026-08-20", "2026-08-20", "", A(1)), ("6-K", "2026-08-10", "2026-08-10", "", A(2)), ("6-K", "2026-07-01", "2026-07-01", "", A(3)),
            ("6-K", "2026-04-10", "2026-04-10", "", A(4)), ("20-F", "2026-03-20", "2025-12-31", "", ACC_20F)] + list(extra_rows)
    files = {
        acc_url(A(1)): six(A(1), "<html><body><p>Notice of annual general meeting and appointment of a director.</p></body></html>"),
        acc_url(A(2)): six(A(2), "<html><body><p>Foreign Co Reports Second Quarter 2026 Results</p><p>Revenue grew 12% and net income rose.</p></body></html>"),
        acc_url(A(3)): six(A(3), "<html><body><p>Foreign Co announces a share buyback programme.</p></body></html>"),
        acc_url(A(4)): six(A(4), "<html><body><p>Foreign Co Reports First Quarter 2026 Results</p></body></html>"),
    }
    files.update(periodic_files(ACC_20F, 2025))
    files.update(extra_files or {})
    FakeSEC(monkeypatch, rows, files)
    return A


def test_a_foreign_filers_newest_6k_results_release_takes_p1s_place_its_20f_the_segment_report_and_other_6ks_fill_the_rest(monkeypatch):
    A = foreign_setup(monkeypatch)
    res = sp.build(CIK, "2026-09-01")
    assert res["reason"] is None
    types = [(i["id"], i["type"], i["form"], i["accession"]) for i in res["items"]]
    assert types == [("P1", "earnings_release", "6-K", A(2)), ("P2", "segment_table", "20-F", ACC_20F), ("P3", "other_8k", "6-K", A(1)), ("P4", "other_8k", "6-K", A(3))]
    p1 = res["items"][0]
    assert p1["title"] == "6-K earnings release (EX-99.1)" and p1["period"] == "Q2 2026" and "Revenue grew 12%" in p1["text"] and p1["filed"] == "2026-08-10"
    assert res["items"][1]["title"].startswith("20-F segment table (R8.htm") and res["items"][1]["period"] == "FY 2025"
    assert res["items"][2]["title"] == "6-K (EX-99.1)" and res["items"][2]["period"] is None                 # no item list for a 6-K
    # the older 6-K (April, over 120 days) is not an "other recent filing"; the release's own 6-K is not one either
    assert A(4) not in [i["accession"] for i in res["items"]]
    # the type survives the pack text
    assert [i["type"] for i in sp.parse_pack("\n".join(sp.section_lines(res)))] == [t[1] for t in types]


def test_the_6k_rule_in_words_results_or_earnings_and_a_quarter_half_year_or_year_word_case_insensitively(monkeypatch):
    cases = [("Interim RESULTS for the half-year ended 30 June 2026", True), ("earnings for the SECOND QUARTER", True), ("Annual results 2025", True),
             ("Q3 earnings call details", True), ("Results of the extraordinary general meeting", False), ("Appointment of a director this year", False),
             ("Quarterly dividend declared", False), ("Full-year outlook unchanged", False)]
    for k, (head, ok) in enumerate(cases):
        A = f"0000123456-26-0009{k:02d}"                                                       # an accession is cached for good: one per case
        FakeSEC(monkeypatch, [("6-K", "2026-08-10", "", "", A)], {acc_url(A): six(A, f"<html><body><p>{head}</p></body></html>")})
        got = sp.build(CIK, "2026-09-01")
        assert [i["type"] for i in got["items"]][:1] == (["earnings_release"] if ok else ["other_8k"]), head
    # the description counts as the title; a body with no exhibit is looked at too
    A = "0000123456-26-000951"
    FakeSEC(monkeypatch, [("6-K", "2026-08-10", "", "", A)], {acc_url(A): six(A, "<html><body><p>See attached.</p></body></html>", desc="Second quarter 2026 results")})
    assert sp.build(CIK, "2026-09-01")["items"][0]["type"] == "earnings_release"
    A = "0000123456-26-000950"
    only_body = sub_txt([("6-K", "main.htm", "<html><body><p>Foreign Co interim results for the six months ended June 30</p></body></html>")])
    FakeSEC(monkeypatch, [("6-K", "2026-08-10", "", "", A)], {acc_url(A): only_body})
    assert sp.build(CIK, "2026-09-01")["items"][0]["title"] == "6-K earnings release (6-K body)"


def test_the_6k_scan_is_the_newest_twelve_of_the_last_400_days_and_a_us_filer_is_untouched(monkeypatch):
    A = lambda n: f"0000123456-26-0002{n:02d}"
    rows = [("6-K", f"2026-08-{28 - n:02d}", "", "", A(n)) for n in range(14)]
    files = {acc_url(A(n)): six(A(n), "<html><body><p>Foreign Co announces nothing in particular.</p></body></html>") for n in range(14)}
    files[acc_url(A(12))] = six(A(12), "<html><body><p>Foreign Co Reports Second Quarter Results</p></body></html>")       # the 13th: not looked at
    fk = FakeSEC(monkeypatch, rows, files)
    res = sp.build(CIK, "2026-09-01")
    assert not any(i["type"] == "earnings_release" for i in res["items"]) and any("No 8-K Item 2.02 earnings release or 6-K results release" in a for a in res["annotations"])
    assert sum(1 for u in fk.requests if u.endswith(".txt")) == sp.SCAN_6K + 0 or sum(1 for u in fk.requests if u.endswith(".txt")) >= sp.SCAN_6K
    # a 6-K older than 400 days is not looked at
    A0 = "0000123456-25-000001"
    fk = FakeSEC(monkeypatch, [("6-K", "2025-01-10", "", "", A0)], {acc_url(A0): six(A0, "<html><body><p>Foreign Co Reports Second Quarter Results</p></body></html>")})
    assert sp.build(CIK, "2026-09-01")["items"] == [] and not fk.requests
    # a name with an 8-K Item 2.02 takes the 8-K path; its 6-Ks are not read
    fk = FakeSEC(monkeypatch, list(STANDARD_ROWS) + [("6-K", "2026-08-25", "", "", A(0))], dict(standard_files(), **{acc_url(A(0)): six(A(0), "<html><body><p>x</p></body></html>")}))
    res = sp.build(CIK, "2026-09-01")
    assert res["items"][0]["form"] == "8-K" and not any(i["form"] == "6-K" for i in res["items"]) and not any(u == acc_url(A(0)) for u in fk.requests)


def test_a_6k_and_a_20f_are_the_kinds_the_refusal_rules_read(monkeypatch):
    foreign_setup(monkeypatch)
    items = sp.build(CIK, "2026-09-01")["items"]
    assert sp.refuse_search("Foreign Co Q2 2026 earnings release", items)[0]["served_from_primary"] == ["P1"]                       # a 6-K is a release
    assert sp.refuse_search("Foreign Co fiscal 2025 annual report segment", items)[0]["served_from_primary"] == ["P2"]              # a 20-F is the annual report
    assert sp.refuse_fetch(items[0]["url"], items)["served_from_primary"] == "P1"
    assert sp.refuse_fetch(items[1]["url"], items)["served_from_primary"] == "P2"
    assert sp.refuse_fetch(acc_url(ACC_20F, "foreign-20f.htm"), items) is None
    assert sp.refuse_fetch(acc_url("0000123456-26-000102", "other.htm"), items)["served_from_primary"] == "P1"       # another file of the release's 6-K


def test_the_module_text_states_the_rules_in_words():
    doc = sp.__doc__
    for phrase in ("FOREIGN FILER", "results or earnings", "quarter, half-year or year word", "annual segment table", "20-F", "40-F", "a plain integer",
                   "never counts", "COMPLETE primary item", "partly in the briefing", "distinctive in", "Same form"):
        assert phrase in doc.replace("A plain", "a plain"), phrase


# ---- review 2: a 6-K about a meeting is never a results release -------------------------------------------------------------------------------

@pytest.mark.parametrize("head,desc,release", [
    ("Results of the Annual General Meeting 2026 held for the year", "Press release", False),
    ("Notice of Extraordinary General Meeting to approve the full year dividend", "Press release", False),
    ("Voting results of the AGM: results for each resolution of the year", "Press release", False),
    ("Foreign Co announces the EGM results for the year", "Press release", False),
    ("Results of the vote at the special meeting of shareholders, annual report approved", "Press release", False),
    ("Results of voting for the half-year resolutions", "Press release", False),
    ("Notice of the 2026 annual meeting of shareholders and annual results", "Press release", False),
    ("Second quarter 2026 results are attached.", "Results of the Annual General Meeting", False),            # the description counts as the title
    ("Foreign Co Reports Second Quarter 2026 Results", "Press release", True),
    ("Foreign Co Reports Second Quarter 2026 Results " + "x" * 600 + " annual general meeting follows", "Press release", True),   # past 600 characters
    ("Foreign Co half-year results: meet management on the conference call", "Press release", True),
])
def test_a_6k_about_a_meeting_is_never_a_results_release(monkeypatch, head, desc, release):
    A = f"0000123456-26-{abs(hash(head)) % 900000 + 1000:06d}"
    FakeSEC(monkeypatch, [("6-K", "2026-08-10", "", "", A)], {acc_url(A): six(A, f"<html><body><p>{head}</p></body></html>", desc=desc)})
    got = sp.build(CIK, "2026-09-01")
    assert got["items"][0]["type"] == ("earnings_release" if release else "other_8k"), head
    if not release:
        assert any("No 8-K Item 2.02 earnings release or 6-K results release" in a for a in got["annotations"])


def test_the_meeting_rule_in_words_is_in_the_module_text():
    assert "NOT about a meeting" in sp.__doc__ and "AGM or EGM" in sp.__doc__ and "results of a vote" in sp.__doc__
    assert sp.MEETING_WORDS.search("Annual and Special General Meeting") and sp.MEETING_WORDS.search("results of the vote") and not sp.MEETING_WORDS.search("Quarterly results")
