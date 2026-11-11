"""WO_HM2a: news as a trigger (found_by, the competition query, article text, the `news` trigger), the news file for the packet, the Q1 split
(press-report claims apart from Q1), and the interpreter. Stubs only: conftest blocks the network, no model runs."""
import copy
import hashlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import monitor as M
from helpers import AAA, NOW, claim, make_run, sources, tc
from test_executor import Rig

TEXT = "Alphatest Corp said a rival entered its market. " * 4


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def nrow(n, day="2026-10-28", found_by=("w_litigation",), title=None, **kw):
    return {"date": day, "source": "bing news", "title": title or f"Alphatest Corp story {n}", "url": f"https://news.example.com/{n}",
            "snippet": "Alphatest", "found_by": list(found_by), **kw}


def gather(rows, article, first=True, state=None, now=NOW):
    return M.gather_name(AAA, state, sources([], news=lambda c, t, d: rows) if article is None else
                         M.Sources(submissions=lambda c: {"cik": "0000000001", "filings": {"recent": {}}}, news=lambda c, t, d: rows, article=article),
                         now)


# ---------------------------------------------------------------- 1. which query found a row

def test_the_competition_query_is_built_like_the_others_and_category_keys_exclude_the_name_query():
    keys = [k for k, _, _ in M.NEWS_QUERIES]
    assert keys == ["w_name", "w_litigation", "w_regulatory", "w_policy", "w_contract", "w_competition"]
    _, template, engines = M.NEWS_QUERIES[-1]
    assert engines == "bing news" and template.startswith('"{p}" (')
    for word in ("competitor", "rival", "entrant", '"price cut"', '"market share"', "launches"):
        assert word in template
    assert M.CATEGORY_KEYS == frozenset(keys) - {"w_name"}


def test_a_row_returned_by_several_queries_is_one_row_with_every_key():
    a = {"url": "https://a.example.com/1", "title": "Alphatest Corp wins a deal", "content": "Alphatest", "publishedDate": "2026-10-28T10:00:00"}
    same_title_new_url = dict(a, url="https://b.example.com/9")
    same_url_new_title = dict(a, title="Alphatest Corp: the deal in detail")
    only_competition = {"url": "https://a.example.com/2", "title": "Alphatest Corp faces a rival", "content": "Alphatest"}
    by_query = [[a], [same_title_new_url], [], [same_url_new_title, a], [], [only_competition, a]]
    calls = []

    def get(url):
        calls.append(parse_qs(urlparse(url).query)["q"][0])
        return {"results": by_query[len(calls) - 1]}
    rows = M.searx_news("Alphatest Corp", "AAA", "2026-10-29", get_json=get, sleep=lambda s: None)
    assert len(calls) == 6 and "competitor" in calls[-1]
    assert [(r["title"], r["found_by"]) for r in rows] == [
        ("Alphatest Corp wins a deal", ["w_name", "w_litigation", "w_policy", "w_competition"]),
        ("Alphatest Corp faces a rival", ["w_competition"])]


def test_found_by_travels_to_the_gather_row_and_a_source_without_it_gives_an_empty_list():
    res, _ = gather([nrow(1, found_by=["w_name", "w_policy"]), {k: v for k, v in nrow(2).items() if k != "found_by"}], None)
    assert [r["found_by"] for r in res["news"]] == [["w_name", "w_policy"], []]


# ---------------------------------------------------------------- 2. article text

def test_text_is_fetched_for_at_most_five_new_rows_category_rows_first_then_newest():
    rows = [nrow(1, "2026-10-29", ["w_name"]), nrow(2, "2026-10-23", ["w_policy"]), nrow(3, "2026-10-27", ["w_name"]),
            nrow(4, "2026-10-26", ["w_contract"]), nrow(5, "2026-10-28", ["w_name"]), nrow(6, "2026-10-25", ["w_regulatory"]),
            nrow(7, "2026-10-24", ["w_name", "w_competition"])]
    asked = []
    res, _ = gather(rows, lambda url, title: asked.append(url.rsplit("/", 1)[1]) or TEXT)
    # category rows: 4 (10-26), 6 (10-25), 7 (10-24), 2 (10-23); then by date: 1 (10-29) -- five in all, 5 and 3 are not read
    assert asked == ["4", "6", "7", "2", "1"] and M.NEWS_TEXT_ROWS == 5
    assert [bool(r.get("text")) for r in res["news"]] == [True, True, False, True, False, True, True]
    assert res["errors"] == []


def test_the_text_is_cut_and_its_hash_length_and_source_recorded():
    full = "Alphatest Corp " + "x" * 9000
    res, g = gather([nrow(1)], lambda url, title: full)
    r = res["news"][0]
    assert r["text"] == full[:6000] and len(r["text"]) == M.NEWS_TEXT_CHARS == 6000
    assert r["text_sha256"] == sha(full[:6000]) and r["text_chars_full"] == len(full) and r["read_from"] == "https://news.example.com/1"
    assert g["news_rows"][r["key"]]["text_sha256"] == r["text_sha256"]


def test_a_failed_read_leaves_the_row_without_text_and_adds_an_error():
    def article(url, title):
        if url.endswith("/1"):
            raise OSError("connection reset")
        return None if url.endswith("/2") else "   "
    res, g = gather([nrow(1), nrow(2), nrow(3)], article)
    assert len(res["news"]) == 3 and not any("text" in r for r in res["news"])
    assert len(res["errors"]) == 3 and "OSError: connection reset" in res["errors"][0] and res["errors"][1].endswith("no text")
    assert g["news_rows"] == {}


def test_text_that_does_not_name_the_issuer_is_dropped_and_annotated_but_the_row_stays():
    res, g = gather([nrow(1), nrow(2)], lambda url, title: "A page about an unrelated company." if url.endswith("/1") else TEXT)
    first, second = res["news"]
    assert first["annotations"] == ["text_does_not_name_issuer"] and not any(k.startswith("text") for k in first)
    assert second["text"] == TEXT and list(g["news_rows"]) == [second["key"]]


def test_the_issuer_word_is_looked_for_in_the_kept_text_only():
    res, _ = gather([nrow(1)], lambda url, title: "x" * 6000 + " Alphatest")
    assert res["news"][0]["annotations"] == ["text_does_not_name_issuer"]


def test_no_article_source_is_recorded_in_the_errors_and_rows_still_report():
    res, g = M.gather_name(AAA, None, M.Sources(news=lambda c, t, d: [nrow(1)]), NOW)
    assert len(res["news"]) == 1 and "news text: no article source" in res["errors"] and g["news_rows"] == {}


def test_online_article_reads_through_the_main_reader(monkeypatch):
    seen = []

    def fetch_page(url, **kw):
        seen.append((url, kw))
        return {"url": url, "text": "  the page  "} if "ok" in url else {"url": url, "error": "fetch failed"}
    monkeypatch.setitem(sys.modules, "analyst_tools", types.SimpleNamespace(fetch_page=fetch_page))
    assert M.online_article("https://x.example.com/ok", "Headline") == "the page"
    assert seen[0][1]["known_urls"] == {"https://x.example.com/ok": "Headline"}
    assert M.online_article("https://x.example.com/bad", "Headline") is None


def test_live_sources_carry_the_article_reader():
    assert M.live_sources(NOW).article is M.online_article


# ---------------------------------------------------------------- 3. the news trigger

def with_text(r, text=TEXT, **over):
    return dict(r, text=text, text_sha256=sha(text), text_chars_full=len(text), read_from=r["url"], key="t:" + M.normalize_title(r["title"]), **over)


def result(rows):
    return {"filings": [], "news": rows, "price": None}


def test_one_news_trigger_per_gather_when_a_category_row_has_text():
    rows = [with_text(nrow(1)), with_text(nrow(2, found_by=["w_contract", "w_competition"])), with_text(nrow(3, found_by=["w_name"]))]
    for held in (True, False):
        (t,) = M.build_triggers(AAA, result(rows), held, NOW)
        assert (t["id"], t["kind"], t["priority"], t["time"]) == ("news:AAA:2026-10-29", "news", 3, "2026-10-29T12:00:00Z")
        assert [e["title"] for e in t["evidence"]] == ["Alphatest Corp story 1", "Alphatest Corp story 2"]
        assert t["evidence"][1] == {"key": rows[1]["key"], "title": "Alphatest Corp story 2", "date": "2026-10-28", "first_seen": None,
                                    "found_by": ["w_contract", "w_competition"]}
        assert t["reasons"] == ["news_w_competition", "news_w_contract", "news_w_litigation"]


def test_news_without_text_or_without_a_category_queues_nothing():
    assert M.build_triggers(AAA, result([nrow(1)]), True, NOW) == []                                   # category, no text
    assert M.build_triggers(AAA, result([with_text(nrow(1, found_by=["w_name"]))]), True, NOW) == []    # text, name query only
    assert M.build_triggers(AAA, result([with_text(nrow(1, found_by=[]))]), True, NOW) == []
    assert M.build_triggers(AAA, result([with_text(nrow(1), text="")]), True, NOW) == []


def test_run_day_queues_the_news_trigger_journals_it_and_a_second_gather_the_same_day_adds_nothing(root):
    mon = M.Monitor(root)
    src = M.Sources(submissions=lambda c: {"cik": "0000000001", "filings": {"recent": {}}}, news=lambda c, t, d: [nrow(1), nrow(2, found_by=["w_name"])],
                    article=lambda url, title: TEXT)
    rep = mon.run_day({"F": ["AAA"]}, [], {}, {"AAA": AAA}, src, NOW)
    assert rep["new_triggers"]["AAA"] == ["news:AAA:2026-10-29"]
    e = mon.ordered()[0]
    assert e["priority"] == 3 and list(e["triggers"]) == ["news:AAA:2026-10-29"]
    lines = mon.journal_lines()
    disc = [l for l in lines if l["kind"] == "discovered" and l["trigger"]]
    assert disc[0]["evidence"][0]["label"] == "secondary" and disc[0]["evidence"][0]["rows"][0]["found_by"] == ["w_litigation"]
    sec = [l for l in lines if l["kind"] == "discovered" and l["secondary"]]
    assert len(sec) == 1 and sec[0]["queues_nothing"] is False
    mon.run_day({"F": ["AAA"]}, [], {}, {"AAA": AAA}, src, NOW + timedelta(hours=1), first_since=NOW - timedelta(days=7))
    assert len(mon.ordered()[0]["triggers"]) == 1


# ---------------------------------------------------------------- 4. the news for the packet

def stored(mon, rows, cik=1):
    M.write_json_atomic(mon.state_dir / f"gather_{cik}.json", {"news_rows": {r["key"]: r for r in rows}})


def entry(mon, **kw):
    mon.enqueue(AAA, [{"id": "sec:1", "kind": "sec_filing", "priority": 3, "time": "2026-10-29T10:00:00Z", "reasons": [], "annotations": []}], NOW)
    return mon.ordered()[0]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_the_gather_record_keeps_only_rows_with_text_and_prunes_them_with_the_seen_set():
    _, g = gather([nrow(1), nrow(2)], lambda url, title: TEXT if url.endswith("/1") else None)
    assert [r["url"] for r in g["news_rows"].values()] == ["https://news.example.com/1"]
    _, g2 = M.gather_name(AAA, g, M.Sources(news=lambda c, t, d: [], article=lambda u, t: None), NOW + timedelta(days=44))
    assert len(g2["news_rows"]) == 1
    _, g3 = M.gather_name(AAA, g, M.Sources(news=lambda c, t, d: [], article=lambda u, t: None), NOW + timedelta(days=46))
    assert g3["news_rows"] == {} and g3["news_seen"] == {}


def test_the_news_file_holds_the_rows_of_the_seven_days_before_T_not_after_T_newest_first_at_most_eight(tmp_path):
    mon = M.Monitor(tmp_path / "m")
    e = entry(mon)
    rows = [with_text(nrow(i, f"2026-10-{18 + i:02d}")) for i in range(1, 13)]                # 10-19 .. 10-30
    rows.append(with_text(nrow(20, "2026-10-31")))                                           # after T
    rows.append(with_text(nrow(21, title="Alphatest undated"), date=None, first_seen="2026-10-30T09:30:00Z"))        # after T, by time
    rows.append(with_text(nrow(22, title="Alphatest undated early"), date=None, first_seen="2026-10-30T01:30:00Z"))
    rows.append(with_text(nrow(24, title="Alphatest undated the day before"), date=None, first_seen="2026-10-29T05:00:00Z"))
    rows.append(dict(nrow(23, "2026-10-29"), key="t:no text"))                                                      # no text
    stored(mon, rows)
    T = "2026-10-30T02:00:00Z"
    path, n = M.news_file_for(mon, e, T)
    assert path == mon.root / "news" / "AAA_20261030T020000Z.json" and n == 8 == M.NEWS_PACKET_ROWS
    got = read(path)
    assert got["ticker"] == "AAA" and got["T"] == T
    assert [r["title"] for r in got["rows"]][:2] == ["Alphatest undated early", "Alphatest Corp story 12"]
    # the window opens at 10-23T02:00, so 10-24 .. 10-30 are in (10-23 at 00:00 is out); nine rows qualify and the oldest, 10-24, is cut
    assert [r["date"] if "date" in r else r["first_seen"] for r in got["rows"]] == (
        ["2026-10-30T01:30:00Z", "2026-10-30", "2026-10-29T05:00:00Z"] + [f"2026-10-{d}" for d in range(29, 24, -1)])
    assert set(got["rows"][1]) == {"title", "url", "publisher", "date", "found_by", "text", "text_sha256"}
    assert set(got["rows"][0]) == {"title", "url", "publisher", "first_seen", "found_by", "text", "text_sha256"}
    assert got["rows"][1]["publisher"] == "news.example.com" and got["rows"][1]["text_sha256"] == sha(TEXT) and got["rows"][1]["found_by"] == ["w_litigation"]


def test_a_row_an_earlier_resolved_run_read_is_not_handed_over_again_and_a_later_row_of_that_day_is(tmp_path):
    mon = M.Monitor(tmp_path / "m")
    e = entry(mon)
    rows = [with_text(nrow(i, d)) for i, d in enumerate(["2026-10-22", "2026-10-23", "2026-10-25", "2026-10-29", "2026-10-29", "2026-10-30"], 1)]
    stored(mon, rows)
    T = "2026-10-30T12:00:00Z"
    _, n = M.news_file_for(mon, e, T)
    assert n == 4 and M.NEWS_PACKET_DAYS == 7                                  # from 10-23T12:00: 10-22 and 10-23 (00:00) are out
    s = mon._load()
    s["names"]["AAA"]["last_good"] = {"run_id": "R", "decision_time_utc": "2026-10-29T21:00:00Z"}          # a run on 10-29 read story 4 only
    s["names"]["AAA"]["news_packed"] = {"u:" + M.normalize_url("https://news.example.com/4"): "2026-10-29T21:10:00Z"}
    M.write_json_atomic(mon.core_path, s)
    path, n = M.news_file_for(mon, e, T)
    # story 5 carries the same date as that run and was not in its packet: it is still handed over; story 3 (10-25) was never read either
    assert [r["url"].rsplit("/", 1)[1] for r in read(path)["rows"]] == ["6", "5", "3"] and n == 3


def test_a_resolved_run_records_the_press_reports_it_read_and_a_failed_one_does_not(tmp_path):
    mon, line = resolved_line(tmp_path / "a", [FILING, NEWS_ITEM], [])
    assert line["kind"] == "resolved"
    assert list(mon._load()["names"]["AAA"]["news_packed"]) == ["u:" + M.normalize_url("https://news.example.com/1")]
    mon, line = resolved_line(tmp_path / "b", [FILING, NEWS_ITEM], [], status="incomplete")
    assert line["kind"] == "failed" and "news_packed" not in mon._load()["names"]["AAA"]
    mon, line = resolved_line(tmp_path / "c", [FILING], [])
    assert "news_packed" not in mon._load()["names"]["AAA"]


def test_an_entry_with_no_news_rows_builds_the_packet_as_before_and_one_with_rows_passes_the_file(tmp_path):
    rig = Rig(tmp_path)
    rig.queue(AAA, "a", 3, "2026-10-29T10:00:00Z")
    rig.go()
    assert rig.news_files == [None]
    path = rig.root / "news" / "AAA_20261029T100000Z.json"
    assert read(path) == {"ticker": "AAA", "T": "2026-10-29T10:00:00Z", "rows": []}                 # written, and not passed on
    rig2 = Rig(tmp_path / "two")
    rig2.queue(AAA, "a", 3, "2026-10-29T10:00:00Z")
    stored(rig2.mon, [with_text(nrow(1, "2026-10-28"))])
    rep = rig2.go()
    assert rig2.news_files == [str(rig2.root / "news" / "AAA_20261029T100000Z.json")] and rep["entries"][0]["news_rows"] == 1
    assert read(rig2.news_files[0])["rows"][0]["title"] == "Alphatest Corp story 1"


def test_a_dry_run_writes_no_news_file(tmp_path):
    rig = Rig(tmp_path)
    rig.queue(AAA, "a", 3, "2026-10-29T10:00:00Z")
    rig.go(dry_run=True)
    assert not (rig.root / "news").exists()


def test_the_packet_cli_gets_news_file_only_when_given(tmp_path, monkeypatch):
    seen = []
    pk = tmp_path / "p.json"
    pk.write_text(json.dumps({"builder_version": "v6"}), encoding="utf-8")
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or types.SimpleNamespace(
        returncode=0, stdout=json.dumps({"packet": str(pk), "packet_sha256": "abc"}), stderr=""))
    M.qwen_build_packet("AAA", "2026-10-29T10:00:00Z", "c", "ck.json", "r", tmp_path)
    M.qwen_build_packet("AAA", "2026-10-29T10:00:00Z", "c", "ck.json", "r", tmp_path, news_file="n.json")
    assert seen[0][-1] == "--online" and seen[1][-2:] == ["--news-file", "n.json"] and seen[1][:-2] == seen[0]


# ---------------------------------------------------------------- 5. the Q1 split

DATED = "On June 30, 2026 Alphatest Corp received a delisting notice."
NEWS_ITEM = {"fact_id": "N1", "kind": "news", "name": "news", "text": "Press: on August 14, 2026 Alphatest Corp was served a delisting notice.",
             "source": {"url": "https://news.example.com/1"}}
FILING = {"fact_id": "F1", "kind": "filing", "name": "8-K", "text": DATED, "source": {"accession": "0000000001-26-000001"}}
FILING_NO_DATE = {"fact_id": "F3", "kind": "filing", "name": "10-Q", "text": "Nothing dated here.", "source": {"accession": "0000000001-26-000003"}}


def analysis(*claims):
    return {"tasks": {"material_events": {"status": "ok", "claims": list(claims), "unknowns": []}}}


def old_q1_verdict(analysis_, packet, T_date):
    items = {e.get("fact_id"): e.get("text") or "" for e in packet.get("evidence") or []}
    q = M.m3o_engine.q1(analysis_, T_date, M.Q1_EVENT_CLASS, items)
    verdict = "event_found" if q["restricted"] else ("escalation" if q["escalations"] else "none")
    return {"verdict": verdict, "claims": q["claims"], "escalations": q["escalations"]}


def test_a_packet_with_no_news_items_gives_the_result_it_always_gave():
    T = datetime(2026, 10, 30).date()
    packets = [{"evidence": [FILING, FILING_NO_DATE]}, {"evidence": []}, {}]
    cases = [analysis(claim()), analysis(claim(support="unsupported")), analysis(claim(occurred_on=None)), analysis(claim(fact_ids=("F3",))),
             analysis(claim(status="announced_pending"), claim(event_type="other_event", fact_ids=())), analysis(claim(fact_ids=())),
             analysis(claim(occurred_on="June 30, 2020")), {"tasks": {}}, {}]
    for pk in packets:
        for a in cases:
            got = M.q1_verdict(copy.deepcopy(a), pk, T)
            assert got == old_q1_verdict(copy.deepcopy(a), pk, T) and "news_claims" not in got
            assert json.dumps(got, sort_keys=True) == json.dumps(old_q1_verdict(copy.deepcopy(a), pk, T), sort_keys=True)


def test_a_critical_claim_citing_only_news_is_a_news_event_not_a_q1_event():
    pk = {"evidence": [FILING, NEWS_ITEM]}
    a = analysis(claim(occurred_on="August 14, 2026", fact_ids=("N1",)))
    before = copy.deepcopy(a)
    q = M.q1_verdict(a, pk, datetime(2026, 10, 30).date())
    assert a == before                                                                    # the analysis is not changed
    assert q["verdict"] == "news_event" and q["claims"] == [] and q["escalations"] == []
    (c,) = q["news_claims"]
    assert c["news_ids"] == ["N1"] and c["class"] == "C4" and c["event_type"] == "delisting_notice" and c["acts_as_news_event"] is True


def test_a_date_printed_only_in_a_press_report_cannot_support_a_q1_date():
    pk = {"evidence": [FILING_NO_DATE, NEWS_ITEM]}
    q = M.q1_verdict(analysis(claim(occurred_on="August 14, 2026", fact_ids=("F3", "N1"))), pk, datetime(2026, 10, 30).date())
    assert q["verdict"] == "escalation" and q["claims"][0]["reason"] == "date_unsupported" and q["news_claims"] == []
    q = M.q1_verdict(analysis(claim(occurred_on="June 30, 2026", fact_ids=("F1", "N1"))), {"evidence": [FILING, NEWS_ITEM]}, datetime(2026, 10, 30).date())
    assert q["verdict"] == "event_found" and q["claims"][0]["acts"] is True              # the filing prints the date


def test_news_claims_that_do_not_make_a_news_event():
    T = datetime(2026, 10, 30).date()
    pk = {"evidence": [FILING, NEWS_ITEM]}
    q = M.q1_verdict(analysis(claim(support="unsupported", fact_ids=("N1",)), claim(event_type="routine_news", fact_ids=("N1",))), pk, T)
    assert q["verdict"] == "none" and [c["acts_as_news_event"] for c in q["news_claims"]] == [False]    # a non-Q1 event type is not listed
    q = M.q1_verdict(analysis(claim(fact_ids=("F1", "N1")), claim(event_type="going_concern_doubt", occurred_on="Aug 14, 2026", fact_ids=("N1",))), pk, T)
    assert q["verdict"] == "event_found" and len(q["claims"]) == 1 and len(q["news_claims"]) == 1       # Q1's own finding wins; the news claim is kept apart


NEWS_OLD = {"fact_id": "N2", "kind": "news", "name": "news", "source": {"url": "https://news.example.com/2"},
            "text": "Press: Alphatest Corp, which was served a delisting notice on March 3, 2024, opened a new plant."}


def test_a_press_report_that_retells_an_old_event_is_not_a_news_event_and_an_undated_one_is():
    T = datetime(2026, 10, 30).date()
    pk = {"evidence": [FILING, NEWS_ITEM, NEWS_OLD]}
    q = M.q1_verdict(analysis(claim(occurred_on="March 3, 2024", fact_ids=("N2",))), pk, T)
    assert q["verdict"] == "none" and q["news_claims"][0]["q1_reason"] == "occurred_outside_window" and q["news_claims"][0]["acts_as_news_event"] is False
    q = M.q1_verdict(analysis(claim(occurred_on="not stated", fact_ids=("N1",))), pk, T)
    assert q["verdict"] == "news_event" and q["news_claims"][0]["q1_reason"] == "undated" and q["escalations"] == []
    q = M.q1_verdict(analysis(claim(status="announced_pending", occurred_on="not stated", fact_ids=("N1",))), pk, T)
    assert q["verdict"] == "news_event" and q["news_claims"][0]["q1_reason"] == "announced_pending"
    assert M.NEWS_STALE_REASONS == {"occurred_outside_window", "occurred_on_after_T", "unknown_status"}


def test_a_claim_that_cites_nothing_in_the_packet_stays_with_q1_when_the_packet_has_news():
    T = datetime(2026, 10, 30).date()
    pk = {"evidence": [FILING, NEWS_ITEM]}
    for ids in ((), ("Z9",)):
        a = analysis(claim(fact_ids=ids))
        got = M.q1_verdict(copy.deepcopy(a), pk, T)
        assert got["news_claims"] == [] and {k: got[k] for k in ("verdict", "claims", "escalations")} == old_q1_verdict(a, pk, T)


def resolved_line(tmp_path, evidence, me_claims, tc_claims=None, **kw):
    d = make_run(tmp_path / "runs", me_claims=me_claims, tc_claims=tc_claims, evidence=evidence, **kw)
    mon = M.Monitor(tmp_path / "root")
    return mon, mon.resolve(d, NOW)


def test_the_resolved_line_carries_the_warning_kind_and_for_a_news_event_the_claims(tmp_path):
    ev = [FILING, NEWS_ITEM]
    mon, line = resolved_line(tmp_path / "a", ev, [claim(occurred_on="August 14, 2026", fact_ids=("N1",))])
    assert line["name_state"] == "news_event" and line["warning_kind"] == "news_event" and line["q1"]["verdict"] == "news_event"
    assert line["news_claims"][0]["news_ids"] == ["N1"] and mon._load()["names"]["AAA"]["q1"] == "news_event"
    assert [l["warning_kind"] for l in mon.journal_lines() if l["kind"] == "resolved"] == ["news_event"]
    _, line = resolved_line(tmp_path / "b", ev, [claim(fact_ids=("F1",))])
    assert line["name_state"] == "event_found" and line["warning_kind"] == "event_found" and "news_claims" not in line
    _, line = resolved_line(tmp_path / "c", ev, [], tc_claims=[tc("p1", "changed"), tc("p2", "unchanged")])
    assert line["name_state"] == "thesis_changed" and line["warning_kind"] == "thesis_changed"
    _, line = resolved_line(tmp_path / "d", ev, [], tc_claims=[tc("p1", "unchanged"), tc("p2", "unchanged")])
    assert line["name_state"] == "thesis_intact" and line["warning_kind"] is None
    _, line = resolved_line(tmp_path / "e", ev, [claim(occurred_on="August 14, 2026", fact_ids=("N1",))], tc_claims=[tc("p1", "changed")])
    assert line["warning_kind"] == "news_event" and line["name_state"] == "news_event"                 # event_found > news_event > thesis_changed


def test_a_run_without_news_items_resolves_with_the_state_it_always_had(tmp_path):
    _, line = resolved_line(tmp_path, None, [claim()])                                                 # make_run's own two filings
    assert line["name_state"] == "event_found" and line["warning_kind"] == "event_found" and "news_claims" not in line["q1"]


# ---------------------------------------------------------------- 6b. the record of a started run and 7. the interpreter

def test_start_records_are_kept_for_ninety_days(tmp_path):
    mon = M.Monitor(tmp_path / "m")
    mon.record_start("AAA", "a" * 64, "old", NOW - timedelta(days=100))
    mon.record_start("AAA", "b" * 64, "new", NOW)
    assert list(mon._load()["started"]) == ["new"] and mon._load()["started"]["new"]["started"] == "2026-10-29T12:00:00Z"


def test_the_subprocesses_use_this_interpreter_and_the_fixed_path_is_gone(tmp_path, monkeypatch):
    seen = []
    pk = tmp_path / "p.json"
    pk.write_text(json.dumps({"builder_version": "v6"}), encoding="utf-8")
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or types.SimpleNamespace(
        returncode=0, stdout=json.dumps({"packet": str(pk), "packet_sha256": "abc", "run_dir": "D"}), stderr=""))
    M.qwen_build_packet("AAA", "2026-10-29T10:00:00Z", "c", "ck.json", "r", tmp_path)
    M.qwen_run("p.json", None, 1000, tmp_path)
    assert [c[0] for c in seen] == [sys.executable, sys.executable]
    assert not hasattr(M, "PYTHON") and "Python312" not in Path(M.__file__).read_text(encoding="utf-8")
