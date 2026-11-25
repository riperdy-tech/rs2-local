"""news_watch: the gather's new-headline rule, the reader's prompt and the code checks on its answer, the several-stock split, the
warnings, the re-read cap, the site fields. Synthetic rows and replies; no network, no model."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import news_watch as N  # noqa: E402

DAY = "2026-11-25"
NOW = datetime(2026, 11, 25, 21, 0, tzinfo=timezone.utc)


def claim(s):
    return {"claim": s, "support": "supported"}


def report(ticker="AAA", date="2026-11-10T00:00:00Z", accepted="2026-11-05T21:00:00Z"):
    return {"ticker": ticker, "date": date, "based_on": {"accepted_utc": accepted, "decision_time": date},
            "tasks": {"risks": [claim("Loss of the largest customer would cut revenue."), claim("A patent suit is pending.")],
                      "competitive_position": [claim("Two rivals are adding capacity.")],
                      "growth_thesis": [claim("The new plant must open in 2027.")],
                      "material_events": [claim("The company agreed to buy a smaller rival.")]}}


def row(title, snippet="", url=None):
    return {"title": title, "snippet": snippet, "url": url or "https://news.example/" + title.replace(" ", "-").lower(), "source": "wire",
            "date": DAY, "found_by": ["w_name"]}


ROWS = [row("Alpha Corp loses its largest customer to a rival", "Alpha Corp said its largest customer will not renew its supply contract."),
        row("Alpha Corp largest customer walks away", "The customer accounted for a fifth of Alpha Corp revenue."),
        row("Alpha Corp shares fall 9 percent")]
POINT_IDS = {"R1", "R2", "C1", "G1"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name, sub in (("NEWS", ""), ("RAW", "raw"), ("SEEN", "seen"), ("CHECKS", "checks"), ("WARNINGS", "warnings.jsonl"),
                      ("STATE", "state.json"), ("USAGE", "usage.jsonl"), ("LOG", "log"), ("TRACK", "track.json")):
        monkeypatch.setattr(N, name, tmp_path / sub if sub else tmp_path)
    monkeypatch.setattr(N, "reports", lambda: {"AAA": report()})
    monkeypatch.setattr(N, "companies", lambda: {"AAA": "Alpha Corp"})
    monkeypatch.setattr(N, "last_close", lambda t, stocks=None: 12.5)
    monkeypatch.setattr(N.paths, "resolve", lambda key: tmp_path / "screener")
    (tmp_path / "screener").mkdir()
    (tmp_path / "screener" / "stocks.json").write_text(json.dumps(
        [{"symbol": "AAA", "name": "Alpha Corp", "industry": "Steel", "sector": "Basic Materials", "price": 12.5}]), encoding="utf-8")
    return tmp_path


def event(**k):
    return {"items": ["N1", "N2"], "touches": ["R1"], "new_matter": False, "direction": "worse", "serious": True,
            "why": "The largest customer will not renew.", "quote_item": "N1", "quote": "largest customer will not renew its supply contract", **k}


# ------------------------------------------------------------ gather
def test_a_first_gather_is_the_baseline_and_a_later_day_keeps_only_what_is_new(home):
    assert N.new_rows("AAA", "2026-11-24", ROWS[:1]) == ([], True)
    assert N.new_rows("AAA", DAY, ROWS) == (ROWS[1:], False)
    assert N.new_rows("AAA", "2026-11-26", ROWS) == ([], False)


def test_the_same_headline_at_another_address_is_not_new(home):
    N.new_rows("AAA", "2026-11-24", ROWS[:1])
    assert N.new_rows("AAA", DAY, [row(ROWS[0]["title"].upper() + "!", url="https://other.example/x")])[0] == []


def test_seen_keys_are_dropped_after_the_keep_window(home):
    N.new_rows("AAA", "2026-09-01", ROWS[:1])
    assert N.new_rows("AAA", DAY, ROWS[:1])[0] == ROWS[:1]


def test_gather_writes_one_file_a_stock_and_counts_a_failed_search(home, monkeypatch):
    monkeypatch.setattr(N, "reports", lambda: {"AAA": report(), "BBB": report("BBB")})

    def search(company, ticker, day):
        if ticker == "BBB":
            raise RuntimeError("every news query failed")
        return ROWS
    out = N.gather(search=search, now=NOW, sleep=lambda s: None)
    assert (out["gathered"], out["errors"], out["with_new"]) == (1, ["BBB"], 0)          # a first gather is not "new"
    assert json.loads((home / "raw" / "AAA" / f"{DAY}.json").read_text(encoding="utf-8")) == {
        "ticker": "AAA", "day": DAY, "company": "Alpha Corp", "found": 3, "first_gather": True, "rows": []}
    assert "error" in json.loads((home / "raw" / "BBB" / f"{DAY}.json").read_text(encoding="utf-8"))
    again = N.gather(search=lambda c, t, d: ROWS, now=NOW, sleep=lambda s: None)          # a rerun takes only the stock that failed
    assert again["gathered"] == 1


def test_gather_pauses_between_batches_and_keeps_the_docker_marker(home, monkeypatch):
    monkeypatch.setattr(N, "reports", lambda: {f"T{i:02d}": report(f"T{i:02d}") for i in range(N.GATHER_BATCH + 1)})
    monkeypatch.setattr(N, "companies", lambda: {})
    slept = []
    N.gather(search=lambda c, t, d: [], now=NOW, sleep=slept.append, marker=home / "cache" / "monitor_gather.running")
    assert slept == [N.GATHER_PAUSE_S] and (home / "cache" / "monitor_gather.running").exists()


# ------------------------------------------------------------ the prompt and the checks on a reply
def test_the_prompt_carries_the_stocks_own_points_its_known_events_and_earlier_warnings():
    p = N.prompt([("AAA", "Alpha Corp", report(), DAY, ROWS, [{"day": "2026-11-20", "why": "A plant fire stopped output."}])])
    for s in ("R1: Loss of the largest customer", "R2: A patent suit", "C1: Two rivals", "G1: The new plant", "- The company agreed to buy",
              "(warning already raised 2026-11-20) A plant fire stopped output.", "N1: Alpha Corp loses its largest customer", '"N3"',
              "one company"):
        assert s in p
    assert "AAA.R1" not in p


def test_a_several_stock_prompt_names_every_id_by_its_stock():
    p = N.prompt([("AAA", "Alpha Corp", report(), DAY, ROWS, []), ("BBB", "Beta Inc", report("BBB"), DAY, ROWS[:1], [])])
    assert "AAA.R1: Loss" in p and "BBB.N1: Alpha" in p and '"AAA.N3"' in p and "several companies" in p


def test_an_event_passes_when_its_items_points_and_quote_are_real():
    e = N.checked_event(event(), ROWS, POINT_IDS)
    assert e["ok"] and e["failed"] == [] and [h["title"] for h in e["headlines"]] == [ROWS[0]["title"], ROWS[1]["title"]]


@pytest.mark.parametrize("change, why", [
    ({"quote": "largest customer has cancelled every order"}, "quote_not_in_item"),
    ({"quote": "largest customer"}, "quote_not_in_item"),                                 # under four words
    ({"quote_item": "N2"}, "quote_not_in_item"),                                          # the words are another item's
    ({"quote_item": "N3"}, "quote_item_unknown"),                                         # not one of the event's items
    ({"items": ["N1", "N9"]}, "item_unknown"),
    ({"touches": ["R7"]}, "point_unknown"),
    ({"touches": []}, "no_point_and_not_new"),
])
def test_an_event_that_fails_a_check_is_kept_with_its_reason(change, why):
    e = N.checked_event(event(**change), ROWS, POINT_IDS)
    assert not e["ok"] and why in e["failed"]


def test_a_new_matter_needs_no_point():
    assert N.checked_event(event(touches=[], new_matter=True), ROWS, {"R1"})["ok"]


def test_a_reply_is_parsed_from_json_with_text_around_it_and_refused_otherwise():
    assert N.parse_reply('Here:\n{"events": []}\n') == []
    assert N.parse_reply("nothing") is None and N.parse_reply('{"items": []}') is None


def test_a_several_stock_reply_is_split_and_a_mixed_event_is_set_aside():
    ev = [{"items": ["AAA.N1"], "touches": ["AAA.R1"], "quote_item": "AAA.N1"},
          {"items": ["BBB.N1"], "touches": ["AAA.R1"], "quote_item": "BBB.N1"},            # another stock's point
          {"items": ["N1"], "touches": [], "quote_item": "N1"},                            # no stock named
          {"items": ["CCC.N1"], "touches": [], "quote_item": "CCC.N1"}]                    # a stock that was not asked
    per = N.split_batch(ev, ["AAA", "BBB"])
    assert per["AAA"] == [{"items": ["N1"], "touches": ["R1"], "quote_item": "N1"}] and per["BBB"] == [] and len(per["_mixed"]) == 3


def test_a_ticker_with_a_dot_keeps_its_ids():
    per = N.split_batch([{"items": ["AB.C.N2"], "touches": ["AB.C.R1"], "quote_item": "AB.C.N2"}], ["AB.C"])
    assert per["AB.C"] == [{"items": ["N2"], "touches": ["R1"], "quote_item": "N2"}]


# ------------------------------------------------------------ readers
def jobs(*tickers):
    return [(t, t, report(t), DAY, ROWS, []) for t in tickers]


def never(*a, **k):
    pytest.fail("not expected to be called")


def test_the_local_reader_takes_one_stock_a_call(home):
    calls = []

    def ollama(model, text, label):
        calls.append(label)
        return '{"events": []}'
    out = N.read_jobs(jobs("AAA", "BBB"), reader="ollama:m", ollama=ollama, cloud=never)
    assert calls == [f"AAA:{DAY}", f"BBB:{DAY}"] and out == {"AAA": ("ollama:m", []), "BBB": ("ollama:m", [])}


def test_a_stock_the_local_reader_cannot_read_goes_to_gemini_in_batches(home):
    def ollama(model, text, label):
        raise OSError("connection refused")
    sent = []

    def gemini(text, label):
        sent.append(label)
        return json.dumps({"events": [{"items": ["AAA.N1"], "touches": ["AAA.R1"], "quote_item": "AAA.N1"}]})
    out = N.read_jobs(jobs("AAA", "BBB"), reader="ollama:m", ollama=ollama, cloud=lambda: ("gemini", gemini))
    assert sent == [f"{DAY}:AAA,BBB"] and out["AAA"][0] == "gemini" and len(out["AAA"][1]) == 1 and out["BBB"] == ("gemini", [])


def test_no_reader_leaves_the_stock_unread(home):
    assert N.read_jobs(jobs("AAA"), reader="cloud", cloud=lambda: None) == {"AAA": None}


# ------------------------------------------------------------ check, act, the site
def gathered(home, day=DAY, rows=ROWS, first=False):
    N._write(home / "raw" / "AAA" / f"{day}.json", {"ticker": "AAA", "day": day, "company": "Alpha Corp", "first_gather": first, "rows": rows})


def test_check_writes_the_check_file_and_one_warning_an_event(home):
    gathered(home)
    reply = json.dumps({"events": [event(), event(items=["N3"], quote_item="N3", quote="no such words in the item")]})
    out = N.check(now=NOW, reader="ollama:m", ollama=lambda m, text, label: reply)
    assert out == {"checked": 1, "warnings": 1, "serious": 1, "unread": 0}
    w = N.warnings_log()[0]
    assert (w["ticker"], w["day"], w["outlets"], w["touches"][0]["id"], w["close_at_warning"]) == ("AAA", DAY, 2, "R1", 12.5)
    assert w["touches"][0]["claim"].startswith("Loss of the largest customer")
    assert [e["ok"] for e in json.loads((home / "checks" / DAY / "AAA.json").read_text(encoding="utf-8"))["events"]] == [True, False]
    assert N.check(now=NOW, reader="ollama:m", ollama=never)["checked"] == 0


def test_an_unread_stock_raises_nothing_and_is_taken_again(home):
    gathered(home)
    out = N.check(now=NOW, reader="cloud", cloud=lambda: ("gemini", lambda text, label: None))
    assert out["unread"] == 1 and not (home / "checks" / DAY / "AAA.json").exists()      # the next run takes it again


def warn(home, ticker, wid, day=DAY, serious=True, direction="worse"):
    with (home / "warnings.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": wid, "ticker": ticker, "day": day, "at": f"{day}T21:30:00Z", "serious": serious, "direction": direction,
                            "new_matter": False, "why": "why " + wid, "quote": "q", "touches": [], "headline": "headline " + wid,
                            "url": "u", "source": "s", "outlets": 1}) + "\n")


def acting(home, monkeypatch, tickers):
    monkeypatch.setattr(N, "reports", lambda: {t: report(t) for t in tickers})


HIT = ("8-K", "0001-26-000001")


def test_act_tells_once_and_queues_a_stock_only_after_a_new_filing(home, monkeypatch):
    acting(home, monkeypatch, ["AAA", "BBB"])
    warn(home, "AAA", "a1")
    warn(home, "BBB", "b1")
    warn(home, "BBB", "b2", serious=False)
    queued, told = [], []

    def enqueue(w, hit):
        queued.append((w["ticker"], hit))
        return True

    def notify(text):
        told.append(text)
        return True
    out = N.act(now=NOW, notify=notify, enqueue=enqueue, filed=lambda t, since, now: HIT if t == "BBB" else None)
    assert queued == [("BBB", HIT)] and out["waiting"] == ["AAA"] and out["told"] == 2 and len(told) == 1
    assert "Waiting for a filing: AAA" in told[0] and "why b2" not in told[0]
    out = N.act(now=NOW, notify=never, enqueue=enqueue, filed=lambda t, since, now: HIT)       # the next run: AAA has filed; nothing is told twice
    assert queued[-1] == ("AAA", HIT) and out["queued"] == ["AAA"] and out["told"] == 0
    assert N.act(now=NOW, notify=never, enqueue=never, filed=never)["queued"] == []           # both settled


def test_act_queues_up_to_the_cap_worst_first(home, monkeypatch):
    acting(home, monkeypatch, ["AAA", "BBB", "CCC", "DDD", "EEE"])
    for t, wid, d in (("AAA", "a1", "better"), ("BBB", "b1", "worse"), ("CCC", "c1", "worse"), ("DDD", "d1", "unclear"), ("EEE", "e1", "worse")):
        warn(home, t, wid, direction=d)
    queued = []

    def enqueue(w, hit):
        queued.append(w["ticker"])
        return True
    out = N.act(now=NOW, notify=lambda text: True, enqueue=enqueue, filed=lambda t, since, now: HIT)
    assert queued == ["BBB", "CCC", "EEE"] and out["over_cap"] == ["DDD", "AAA"]
    later = datetime(2026, 11, 26, 21, 0, tzinfo=timezone.utc)
    assert N.act(now=later, notify=never, enqueue=enqueue, filed=lambda t, since, now: HIT)["queued"] == ["DDD", "AAA"]     # the next day takes the rest


def test_a_stock_already_queued_is_settled_and_does_not_use_the_cap(home, monkeypatch):
    acting(home, monkeypatch, ["AAA", "BBB", "CCC", "DDD"])
    for t in ("AAA", "BBB", "CCC", "DDD"):
        warn(home, t, t.lower())
    out = N.act(now=NOW, notify=lambda text: True, enqueue=lambda w, hit: w["ticker"] != "AAA", filed=lambda t, since, now: HIT)
    assert out["queued"] == ["BBB", "CCC", "DDD"] and out["over_cap"] == []
    assert N.act(now=NOW, notify=never, enqueue=never, filed=never)["waiting"] == []


def test_a_report_made_after_the_warning_settles_it_and_an_unreadable_sec_list_waits(home, monkeypatch):
    monkeypatch.setattr(N, "reports", lambda: {"AAA": report(date="2026-11-26T00:00:00Z"), "BBB": report("BBB")})
    warn(home, "AAA", "a1")
    warn(home, "BBB", "b1")
    warn(home, "CCC", "c1")                                       # no report any more

    def filed(t, since, now):
        raise OSError("SEC unreachable")
    out = N.act(now=NOW, notify=lambda text: True, enqueue=never, filed=filed)
    assert out["waiting"] == ["BBB"] and out["queued"] == []
    assert sorted(json.loads((home / "state.json").read_text(encoding="utf-8"))["settled"]) == ["a1", "c1"]


def test_filed_since_takes_the_newest_event_or_periodic_filing_after_the_report(home):
    keys = ("accessionNumber", "form", "filingDate", "acceptanceDateTime", "reportDate", "items", "primaryDocument")
    rows = [("A-3", "4", "2026-11-20", "2026-11-20T14:00:00.000Z", "", "", "d.htm"),
            ("A-2", "8-K", "2026-11-18", "2026-11-18T14:00:00.000Z", "", "8.01", "d.htm"),
            ("A-1", "8-K", "2026-11-01", "2026-11-01T14:00:00.000Z", "", "1.01", "d.htm")]
    subs = json.dumps({"filings": {"recent": {k: [r[i] for r in rows] for i, k in enumerate(keys)}}}).encode()
    since = datetime(2026, 11, 10, tzinfo=timezone.utc)
    assert N.filed_since("AAA", since, NOW, get=lambda url: subs, ciks={"AAA": "0000000001"}) == ("8-K", "A-2")
    assert N.filed_since("AAA", datetime(2026, 11, 22, tzinfo=timezone.utc), NOW, get=lambda url: subs, ciks={"AAA": "0000000001"}) is None
    with pytest.raises(ValueError):
        N.filed_since("AAA", since, NOW, get=lambda url: subs, ciks={})


def test_the_site_shows_recent_warnings_and_marks_a_serious_one_raised_after_the_report(home):
    warn(home, "AAA", "old", day="2026-11-01")                   # outside the show window, and before the report was made
    warn(home, "AAA", "note", day="2026-11-20", serious=False)
    warn(home, "AAA", "new", day="2026-11-24")
    warn(home, "BBB", "other")
    news, review = N.for_site(report(), N.warnings_log(), now=NOW)
    assert [w["id"] for w in news] == ["new", "note"] and review["id"] == "new" and review["since"] == "2026-11-24"
    again = report(date="2026-11-25T00:00:00Z")                  # read again after the warning: no longer under review, the news still shown
    assert N.for_site(again, N.warnings_log(), now=NOW) == (news, None)
    assert N.for_site(report("ZZZ"), N.warnings_log(), now=NOW) == ([], None)


def test_the_track_record_logs_the_closes_around_a_warning_as_they_come(home):
    warn(home, "AAA", "w1", day="2026-11-24")
    warn(home, "BBB", "w2", day="2026-11-24")
    days = ["2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25"]

    def prices(ticker, now):
        if ticker == "BBB":
            raise RuntimeError("no completed-session close")
        return {"closes": [{"date": d, "close": 10.0 + k} for k, d in enumerate(days)]}
    out = N.track(now=NOW, prices=prices)
    assert out == {"w1": {"ticker": "AAA", "day": "2026-11-24", "serious": True, "direction": "worse", "before": 11.0, "at": 12.0,
                          "after_1": 13.0, "after_20": None, "after_60": None}}          # the stock with no prices waits for the next run
    days += [f"2026-12-{d:02d}" for d in range(1, 21)]
    assert N.track(now=NOW, prices=prices)["w1"]["after_20"] == 10.0 + 22


def test_the_cloud_reader_is_gemini_then_sonnet_then_none(home, monkeypatch):
    low = {"gemini": True, "sonnet": False}
    arm = []
    monkeypatch.setattr(N.G, "set_arm", arm.append)
    monkeypatch.setattr(N.G, "quota_low", lambda: low[arm[-1]])
    assert N.cloud_reader()[0] == "sonnet"
    low["gemini"] = False
    assert N.cloud_reader()[0] == "gemini"
    low.update(gemini=True, sonnet=True)
    assert N.cloud_reader() is None


def test_on_a_first_gather_only_headlines_the_engine_dates_as_recent_are_new(home):
    rows = [dict(ROWS[0], age_hours=5.0), dict(ROWS[1], age_hours=72.0), dict(ROWS[2], age_hours=None)]
    assert N.new_rows("AAA", DAY, rows) == (rows[:1], True)
    assert N.new_rows("AAA", "2026-11-26", rows) == ([], False)            # the baseline rows are seen, not new the day after


@pytest.mark.parametrize("line, hours", [("23 hours ago | The Journal on MSN", 23.0), ("40 minutes ago | Wire", 40 / 60), ("1 day ago | X", 24.0),
                                         ("3 days ago | X", 72.0), ("The Journal", None), ("", None), (None, None)])
def test_the_age_of_a_headline_is_read_from_the_engines_own_line(line, hours):
    assert N.age_hours(line) == hours


def test_search_keeps_one_row_a_headline_with_the_publisher_line_and_drops_other_companies(home):
    asked = []

    def get(url):
        asked.append(url)
        return {"results": [
            {"url": "https://a.example/1", "title": "Alpha Corp wins a contract", "content": "x", "metadata": "2 hours ago | Daily Wire", "engine": "bing news"},
            {"url": "https://b.example/2", "title": "ALPHA CORP wins a contract!", "content": "x", "metadata": "3 hours ago | Other"},
            {"url": "https://c.example/3", "title": "Beta Inc opens a plant", "content": "nothing on the company", "metadata": "1 hour ago | Wire"},
            {"url": "https://marketbeat.com/x", "title": "Alpha Corp rating", "content": "", "metadata": "1 hour ago | MB"}]}
    rows = N.search_news("Alpha Corp", "AAA", DAY, get_json=get, sleep=lambda s: None)
    assert len(asked) == len(N.M.NEWS_QUERIES) and len(rows) == 1
    assert rows[0]["source"] == "2 hours ago | Daily Wire" and rows[0]["age_hours"] == 2.0 and len(rows[0]["found_by"]) == len(N.M.NEWS_QUERIES)

    def down(url):
        raise OSError("refused")
    with pytest.raises(RuntimeError):
        N.search_news("Alpha Corp", "AAA", DAY, get_json=down, sleep=lambda s: None)


def test_a_stock_day_no_reader_took_for_days_is_no_longer_checked(home):
    gathered(home, day="2026-11-20")
    assert N.check(now=NOW, reader="cloud", cloud=never)["checked"] == 0


def test_the_gather_stops_when_the_first_searches_all_fail(home, monkeypatch):
    monkeypatch.setattr(N, "reports", lambda: {f"T{i:02d}": report(f"T{i:02d}") for i in range(40)})
    calls = []

    def down(company, ticker, day):
        calls.append(ticker)
        raise RuntimeError("every news query failed")
    out = N.gather(search=down, now=NOW, sleep=never)
    assert len(calls) == N.DOWN_AFTER and len(out["errors"]) == 40 and out["gathered"] == 0


def test_the_reader_is_told_the_industry_and_a_later_day_is_told_the_earlier_days_warning(home):
    gathered(home, day="2026-11-24", rows=ROWS[:1])
    gathered(home, rows=ROWS[1:])
    seen = []

    def ollama(model, text, label):
        seen.append(text)
        return json.dumps({"events": [event(items=["N1"])]}) if label.endswith("2026-11-24") else '{"events": []}'
    assert N.check(now=NOW, reader="ollama:m", ollama=ollama)["warnings"] == 1
    assert "COMPANY AAA: Alpha Corp (Steel, Basic Materials)." in seen[0] and "Today is 2026-11-24" in seen[0]
    assert "(warning already raised 2026-11-24) The largest customer will not renew." in seen[1] and "(warning already raised" not in seen[0]


def test_a_company_with_no_industry_on_file_is_named_alone():
    assert N.company_line("ZZZ", "Zed Inc", {}) == "Zed Inc" and N.company_line("ZZZ", None, {}) == "ZZZ"


def test_the_backup_copies_the_record_and_nothing_else(home):
    warn(home, "AAA", "w1")
    (home / "state.json").write_text("{}", encoding="utf-8")
    (home / "usage.jsonl").write_text("{}", encoding="utf-8")
    assert N.backup(dest=home / "state_repo" / "news_watch") == ["warnings.jsonl", "state.json"]
    assert sorted(p.name for p in (home / "state_repo" / "news_watch").iterdir()) == ["state.json", "warnings.jsonl"]
