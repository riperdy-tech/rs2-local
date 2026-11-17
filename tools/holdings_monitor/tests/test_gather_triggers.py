"""Members, the per-name gather, and the deterministic triggers P0-P4 (SPEC_m3p sections 1-3)."""
import copy
import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

import monitor as M
from helpers import AAA, BBB, NOW, closes_series, feed, filing, price_source, sources, QUIET


# ---------------------------------------------------------------- members

def test_members_reasons_tail_and_exclusions():
    books = {"F": ["AAA", "OPXA", "OPXC"], "FQ": ["AAA"]}
    mem, seen = M.members(books, ["XNEW", "OPXB"], {"XRST": "Q1"}, date(2026, 10, 30))
    assert sorted(mem) == ["AAA", "XNEW", "XRST"]                      # OPXA, OPXB and OPXC never monitored
    assert mem["AAA"]["reasons"] == ["held:F", "held:FQ"] and mem["AAA"]["held"]
    assert mem["XNEW"]["reasons"] == ["newest_book"] and not mem["XNEW"]["held"]
    assert mem["XRST"]["reasons"] == ["restricted:Q1"]
    assert set(seen) == {"AAA", "XNEW", "XRST"}


def test_members_tail_is_30_days():
    _, seen = M.members({"F": ["XOLD"]}, [], {}, date(2026, 10, 1))
    for days, inside in ((1, True), (30, True), (31, False)):
        mem, kept = M.members({}, [], {}, date(2026, 10, 1) + timedelta(days=days), dict(seen))
        assert ("XOLD" in mem) is inside, days
        assert mem.get("XOLD", {}).get("tail", True) is True
        assert ("XOLD" in kept) is inside
    again, _ = M.members({"F": ["XOLD"]}, [], {}, date(2026, 11, 20), dict(seen))     # back in a group: no longer a tail name
    assert again["XOLD"]["tail"] is False


def test_members_restricted_as_list():
    mem, _ = M.members({}, [], ["X"], date(2026, 10, 30))
    assert mem["X"]["reasons"] == ["restricted:restricted"]


# ---------------------------------------------------------------- one name's gather: each priority

def run_gather(rows, held, texts=None, gstate=None, prices=None, news=None, now=NOW, first_since=None):
    res, g = M.gather_name(AAA, gstate, sources(rows, texts, prices, news), now, first_since=first_since)
    return res, g, M.build_triggers(AAA, res, held, now)


NEW = "2026-10-28T20:00:00.000Z"


@pytest.mark.parametrize("form,items,held,priority", [
    ("8-K", "1.03", True, 0), ("8-K", "1.02", True, 0), ("8-K", "2.04", True, 0), ("8-K", "2.06", True, 0), ("8-K", "3.01", True, 0),
    ("8-K", "4.01", True, 0), ("8-K", "4.02", True, 0), ("NT 10-K", "", True, 0), ("NT 10-Q", "", True, 0),
    ("8-K", "1.03", False, 1), ("NT 10-Q", "", False, 1),                      # P1: a name of the newest book not yet held
    ("10-K", "", True, 2), ("10-Q", "", True, 2), ("8-K", "2.02,9.01", True, 2),
    ("8-K", "5.02", True, 3), ("8-K", "1.01", True, 3), ("8-K", "9.01", True, 3), ("6-K", "", True, 3), ("10-Q/A", "", True, 3),
    ("10-Q", "", False, 3), ("8-K", "2.02", False, 3),
])
def test_filing_priorities(form, items, held, priority):
    res, _, trig = run_gather([filing("0000000001-26-000100", form, NEW, items)], held)
    assert [t["priority"] for t in trig] == [priority]
    assert trig[0]["accession"] == "0000000001-26-000100" and trig[0]["accepted_raw"] == NEW


def test_b_pattern_hit_on_a_new_filing_is_p0_for_a_held_name_and_p1_otherwise():
    acc = "0000000001-26-000101"
    texts = {acc: "ALPHATEST CORP Item 7.01. Alphatest Corp today withdrew its full-year guidance."}
    for held, want in ((True, 0), (False, 1)):
        res, _, trig = run_gather([filing(acc, "8-K", NEW, "7.01")], held, texts)
        assert [t["priority"] for t in trig] == [want]
        assert [h["class"] for h in trig[0]["hits"]] == ["C7"] and trig[0]["reasons"] == ["b_pattern:C7"]


def test_b_pattern_on_a_new_10q_going_concern():
    acc = "0000000001-26-000102"
    texts = {acc: "Alphatest Corp: there is substantial doubt about the Company's ability to continue as a going concern."}
    _, _, trig = run_gather([filing(acc, "10-Q", NEW)], True, texts)
    assert trig[0]["priority"] == 0 and trig[0]["hits"][0]["class"] == "C2"


def test_no_trigger_when_nothing_is_new_or_collected():
    rows = [filing("0000000001-26-000103", "SC 13G", NEW), filing("0000000001-26-000104", "4", NEW)]
    res, _, trig = run_gather(rows, True)
    assert res["filings"] == [] and trig == []


def test_text_unavailable_is_annotated_not_silent():
    s = sources([filing("0000000001-26-000105", "8-K", NEW, "5.02")])
    s.filing_text = lambda *a: None
    res, _ = M.gather_name(AAA, None, s, NOW)
    assert "text_unavailable_b_patterns_not_evaluated" in res["filings"][0]["annotations"]


# ---------------------------------------------------------------- the price trigger and its boundary

A = 0.01
SD3 = 3 * A * math.sqrt(60 / 59)             # three sample standard deviations of 60 alternating +A / -A log returns


def test_price_trigger_sigma_boundary():
    below = M.price_signal([(r["date"], r["close"]) for r in closes_series(62, a=A, last_r=SD3 * 0.999)])
    at = M.price_signal([(r["date"], r["close"]) for r in closes_series(62, a=A, last_r=SD3)])
    above = M.price_signal([(r["date"], r["close"]) for r in closes_series(62, a=A, last_r=SD3 * 1.001)])
    down = M.price_signal([(r["date"], r["close"]) for r in closes_series(62, a=A, last_r=-SD3 * 1.001)])
    assert [below["sigma_trigger"], at["sigma_trigger"], above["sigma_trigger"], down["sigma_trigger"]] == [False, True, True, True]
    assert not any(x["move_trigger"] for x in (below, at, above))      # 3% is far from 20%
    assert at["z"] == pytest.approx(3.0, abs=1e-6)


def test_price_trigger_needs_history_for_sigma():
    s = M.price_signal([(r["date"], r["close"]) for r in closes_series(30, a=A, last_r=0.5 * A * 10)])
    assert s["sigma_trigger"] is False and "sigma_needs_more_history" in s["notes"]


def test_price_trigger_20_percent_in_5_sessions_boundary():
    def sig(last):
        rows = [("2026-10-%02d" % d, 100.0) for d in range(20, 25)] + [("2026-10-25", last)]
        return M.price_signal(rows)
    assert sig(119.99)["move_trigger"] is False
    assert sig(120.0)["move_trigger"] is True and sig(120.0)["move"] == pytest.approx(0.2)
    assert sig(80.0)["move_trigger"] is True and sig(80.01)["move_trigger"] is False
    # five sessions back means the close five sessions before the latest, not four
    rows = [("2026-10-%02d" % d, c) for d, c in zip(range(20, 26), [100.0, 100.0, 100.0, 100.0, 100.0, 119.0])]
    assert M.price_signal(rows)["move_trigger"] is False


def test_a_zero_close_is_a_value():
    rows = [("2026-10-%02d" % d, 100.0) for d in range(20, 25)] + [("2026-10-25", 0.0)]
    sig = M.price_signal(rows)
    assert sig["move_trigger"] is True and sig["move"] == pytest.approx(-1.0)          # not dropped as missing
    res, g = M.gather_name(AAA, None, sources([], prices=price_source([{"date": d, "close": c} for d, c in rows])), NOW)
    assert g["closes"]["2026-10-25"] == 0.0 and res["price"]["move_trigger"] is True
    assert [t["priority"] for t in M.build_triggers(AAA, res, True, NOW)] == [3]
    # a zero close inside the sigma window: sigma is not computable, and that is said
    ser = [(r["date"], r["close"]) for r in closes_series(62, a=A)]
    ser[10] = (ser[10][0], 0.0)
    assert "sigma_not_computable_nonpositive_close" in M.price_signal(ser)["notes"]


def test_price_trigger_is_p3_even_for_a_held_name_and_fires_once_per_move():
    rows = closes_series(62, a=A, last_r=0.5)
    res, g, trig = run_gather([], True, prices=price_source(rows))
    assert [(t["kind"], t["priority"]) for t in trig] == [("price", 3)]
    assert trig[0]["id"] == f"price:AAA:{rows[-1]['date']}" and trig[0]["time"].endswith("T21:00:00Z")
    # the same quote date again: nothing; the next session at the same elevated level: suppressed, not a second trigger
    res2, g2 = M.gather_name(AAA, g, sources([], prices=price_source(rows)), NOW)
    assert res2["price"] is None
    nxt = rows + [{"date": (date.fromisoformat(rows[-1]["date"]) + timedelta(days=1)).isoformat(), "close": rows[-1]["close"] * 1.001}]
    res3, _ = M.gather_name(AAA, g2, sources([], prices=price_source(nxt)), NOW)
    assert res3["price"].get("suppressed") and M.build_triggers(AAA, res3, True, NOW) == []


def test_flat_prices_no_trigger():
    res, _, trig = run_gather([], True, prices=price_source(closes_series(70, a=A)))
    assert trig == []


# ---------------------------------------------------------------- dedupe

def test_duplicate_filing_is_not_new_and_first_gather_window(fixture_json):
    sub = fixture_json("submissions_aaa.json")
    s = sources(sub=sub)
    res, g = M.gather_name(AAA, None, s, NOW)
    got = [(f["accession"], f["form"]) for f in res["filings"]]
    # the 8-K of 2026-05-02 is older than the first-gather window: recorded as seen, not reported; SC 13G is not a collected form
    assert got == [("0000000001-26-000006", "8-K"), ("0000000001-26-000007", "10-Q"), ("0000000001-26-000008", "NT 10-K"),
                   ("0000000001-26-000009", "8-K")]
    assert "0000000001-26-000004" in g["filings_seen"] and "0000000001-26-000005" in g["filings_seen"]
    res2, g2 = M.gather_name(AAA, g, s, NOW + timedelta(days=1))
    assert res2["filings"] == []
    sub2 = copy.deepcopy(sub)
    new = {"accessionNumber": "0000000001-26-000010", "form": "8-K", "filingDate": "2026-10-29", "acceptanceDateTime": "2026-10-29T10:00:00.000Z",
           "primaryDocument": "n.htm", "items": "5.02", "reportDate": ""}
    for k, col in sub2["filings"]["recent"].items():
        col.insert(0, new[k])
    res3, _ = M.gather_name(AAA, g2, sources(sub=sub2), NOW + timedelta(days=1))
    assert [f["accession"] for f in res3["filings"]] == ["0000000001-26-000010"]       # only the new accession


def test_first_since_overrides_the_window(fixture_json):
    res, _ = M.gather_name(AAA, None, sources(sub=fixture_json("submissions_aaa.json")), NOW, first_since=datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc))
    assert [f["accession"] for f in res["filings"]] == ["0000000001-26-000008", "0000000001-26-000009"]


def test_duplicate_news_by_title_or_url_is_not_new(fixture_json):
    rows = fixture_json("news_aaa.json")
    src = lambda c, t, today: rows
    res, g = M.gather_name(AAA, None, sources([], news=src), NOW)
    assert [r["title"] for r in res["news"]] == ["Alphatest Corp cuts 5% of staff"]
    assert res["news_dropped_no_issuer_word"] == 1 and res["news_seen_not_reported"] == 1      # the weather row; the undated row
    assert all(r["label"] == "secondary" for r in res["news"])
    # the same story again: not new. The same title under a new address: not new. The same address under a new title: not new.
    again = rows + [dict(rows[0], url="https://other.example.com/x"), dict(rows[0], title="Different words: Alphatest trims staff")]
    res2, g2 = M.gather_name(AAA, g, sources([], news=lambda c, t, d: again), NOW + timedelta(days=1))
    assert res2["news"] == []              # the undated row was seen at the first gather; the others repeat a title or an address
    # a normalised-equal title (case, punctuation) is the same headline
    res3, _ = M.gather_name(AAA, g2, sources([], news=lambda c, t, d: [dict(rows[0], title="ALPHATEST CORP cuts 5% of staff!!", url="https://n.example.com/y")]),
                            NOW + timedelta(days=2))
    assert res3["news"] == []


def test_undated_news_is_not_new_at_the_first_gather_but_is_new_later(fixture_json):
    rows = fixture_json("news_aaa.json")
    res, g = M.gather_name(AAA, None, sources([], news=lambda c, t, d: [rows[1]]), NOW)
    assert res["news"] == [] and res["news_seen_not_reported"] == 1
    fresh = dict(rows[1], title="Alphatest faces a second dispute", url="https://news.example.com/two")
    res2, _ = M.gather_name(AAA, g, sources([], news=lambda c, t, d: [rows[1], fresh]), NOW + timedelta(days=1))
    assert [r["title"] for r in res2["news"]] == ["Alphatest faces a second dispute"]        # the old undated one stays seen
    assert res2["news"][0]["first_seen"] == "2026-10-30T12:00:00Z" and "date" not in res2["news"][0]


def test_news_never_queues_anything():
    res, _ = M.gather_name(AAA, None, sources([], news=lambda c, t, d: [{"date": "2026-10-29", "title": "Alphatest Corp collapses", "url": "https://x.example.com/a",
                                                                         "snippet": "Alphatest"}]), NOW)
    assert len(res["news"]) == 1 and M.build_triggers(AAA, res, True, NOW) == []


def test_old_seen_news_is_forgotten_after_45_days():
    row = {"date": "2026-10-29", "title": "Alphatest Corp story", "url": "https://x.example.com/s", "snippet": ""}
    _, g = M.gather_name(AAA, None, sources([], news=lambda c, t, d: [row]), NOW)
    _, g2 = M.gather_name(AAA, g, sources([], news=lambda c, t, d: []), NOW + timedelta(days=46))
    assert g2["news_seen"] == {}


# ---------------------------------------------------------------- cross-issuer guard

def test_foreign_cik_feed_is_not_ingested():
    s = sources(sub=feed(9, [filing("0000009-26-000001", "8-K", NEW, "1.03")]))
    res, g = M.gather_name(AAA, None, s, NOW)
    assert res["filings"] == [] and any("not ingested" in e for e in res["errors"]) and g["filings_seen"] == {}


def test_filing_naming_another_issuer_is_annotated_not_dropped(fixture_text):
    acc = "0000000001-26-000106"
    s = sources([filing(acc, "8-K", NEW, "8.01")], texts={acc: fixture_text("text_8k_other_issuer.txt")})
    res, _ = M.gather_name(AAA, None, s, NOW, peers={"BBB": "Betatest Inc", "AAA": "Alphatest Corp"})
    assert len(res["filings"]) == 1 and res["filings"][0]["annotations"] == ["names_other_issuer:BBB"]
    trig = M.build_triggers(AAA, res, True, NOW)
    assert trig[0]["annotations"] == ["names_other_issuer:BBB"] and trig[0]["priority"] == 3
    res2, _ = M.gather_name(AAA, None, s, NOW)                                      # no peers known: still annotated
    assert res2["filings"][0]["annotations"] == ["issuer_not_named_in_filing_head"]


def test_news_must_name_the_issuer(fixture_json):
    res, _ = M.gather_name(AAA, None, sources([], news=lambda c, t, d: fixture_json("news_aaa.json")), NOW)
    assert "Weather turns cold in Ohio" not in [r["title"] for r in res["news"]] and res["news_dropped_no_issuer_word"] == 1


def test_a_failing_source_leaves_its_state_alone_and_is_reported():
    s = sources([filing("0000000001-26-000107", "8-K", NEW, "1.03")])
    s.submissions = lambda c: (_ for _ in ()).throw(OSError("down"))
    res, g = M.gather_name(AAA, None, s, NOW)
    assert res["filings"] == [] and g["filings_seen"] == {} and any(e.startswith("sec: OSError") for e in res["errors"])


# ---------------------------------------------------------------- SEC contact

def test_missing_sec_user_agent_is_refused_and_nothing_is_sent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(M.SecContactMissing, match="SEC_USER_AGENT"):
        M.sec_headers()
    with pytest.raises(M.SecContactMissing):
        M.online_submissions(1)                      # would have raised AssertionError("network") had it reached urlopen
    with pytest.raises(M.SecContactMissing):
        M.online_filing_text(1, "0000000001-26-000001")
    s = M.Sources(submissions=M.online_submissions)
    with pytest.raises(M.SecContactMissing):               # a gather does not swallow the refusal as an ordinary source error
        M.gather_name(AAA, None, s, NOW)
    monkeypatch.setenv("SEC_USER_AGENT", "no contact here")
    with pytest.raises(M.SecContactMissing):
        M.sec_headers()
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane@example.com")
    assert M.sec_headers() == {"User-Agent": "Jane Doe jane@example.com"}


def test_online_functions_read_the_contact_at_call_time(monkeypatch):
    seen = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"cik": "0000000001", "filings": {"recent": {}}}'

    def fake(req, timeout=0):
        seen["ua"] = req.headers.get("User-agent")
        return R()
    monkeypatch.setattr(M.urllib.request, "urlopen", fake)
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane@example.com")
    assert M.online_submissions(1)["cik"] == "0000000001" and seen["ua"] == "Jane Doe jane@example.com"


def test_searx_news_filters_and_dedupes_with_an_injected_getter():
    data = {"results": [
        {"url": "https://a.example.com/1", "title": "Alphatest Corp wins a deal", "content": "Alphatest", "publishedDate": "2026-10-28T10:00:00", "engine": "bing news"},
        {"url": "https://a.example.com/1", "title": "Alphatest Corp wins a deal", "content": "Alphatest", "engine": "bing news"},
        {"url": "https://marketbeat.com/x", "title": "Alphatest Corp rating", "content": "Alphatest"},
        {"url": "https://a.example.com/2", "title": "Unrelated", "content": "nothing"}]}
    rows = M.searx_news("Alphatest Corp", "AAA", "2026-10-29", get_json=lambda u: data, sleep=lambda s: None)
    assert [(r["title"], r["date"]) for r in rows] == [("Alphatest Corp wins a deal", "2026-10-28")]
    with pytest.raises(M.MonitorError):
        M.searx_news("Alphatest Corp", "AAA", "2026-10-29", get_json=lambda u: (_ for _ in ()).throw(OSError("x")), sleep=lambda s: None)


def test_q1_event_map_equals_prereg_m3o():
    prereg = json.loads(M.book_paths.prereg("PREREG_m3o.json").read_text(encoding="utf-8"))
    assert {v: k for k, v in prereg["rules"]["Q1"]["event_types"].items()} == M.Q1_EVENT_CLASS


def test_a_source_that_failed_at_the_first_gather_is_still_first_at_the_next():
    # cross-check 2026-11-16, S4: the SEC feed failed on day one, so the stored record has seen no filing; on day two an old filing
    # in the feed is recorded as seen and NOT reported, exactly as at a first gather
    old = filing("0000000001-26-000201", "8-K", "2026-06-01T10:00:00.000Z", "1.03")
    fresh, _ = M.gather_name(AAA, None, sources([old]), NOW)
    assert fresh["filings"] == []                                         # the reference: a true first gather skips it
    g0 = {"cik": int(AAA["cik"]), "ticker": AAA["ticker"], "first_gather": "2026-10-28T12:00:00Z", "filings_seen": {}, "news_seen": {},
          "closes": {}, "price_checked": None, "price_fired": None}
    res, g = M.gather_name(AAA, g0, sources([old]), NOW)
    assert res["first"] is False and res["filings"] == [] and "0000000001-26-000201" in g["filings_seen"]
    res2, _ = M.gather_name(AAA, g, sources([old, filing("0000000001-26-000202", "8-K", NEW, "1.03")]), NOW)
    assert [f["accession"] for f in res2["filings"]] == ["0000000001-26-000202"]      # afterwards only what is new
