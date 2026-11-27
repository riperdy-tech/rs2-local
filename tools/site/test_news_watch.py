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
REAL_HELD = N.held
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
    monkeypatch.setattr(N, "held", lambda reps=None: set())           # no stock is held unless a test says so (holding)
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
    assert out == {"checked": 1, "warnings": 1, "serious": 1, "unread": 0, "calls": 0, "tokens": 0}     # the test reader writes no usage row
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


def test_act_tells_once_and_queues_the_stock_that_has_filed_first(home, monkeypatch):
    acting(home, monkeypatch, ["AAA", "BBB", "CCC", "DDD"])
    for t in ("AAA", "BBB", "CCC", "DDD"):
        warn(home, t, t.lower() + "1")
    warn(home, "BBB", "b2", serious=False)
    queued, told = [], []

    def enqueue(w, hit):
        queued.append((w["ticker"], hit))
        return True

    def notify(text):
        told.append(text)
        return True
    out = N.act(now=NOW, notify=notify, enqueue=enqueue, filed=lambda t, since, now: HIT if t == "DDD" else None)
    assert queued == [("DDD", HIT), ("AAA", None), ("BBB", None)] and out["over_cap"] == ["CCC"] and out["told"] == 4 and len(told) == 1
    assert "why b2" not in told[0] and "Over today's cap of 3, taken on a later day: CCC" in told[0]
    later = datetime(2026, 11, 26, 21, 0, tzinfo=timezone.utc)
    assert N.act(now=later, notify=never, enqueue=enqueue, filed=lambda t, since, now: None)["queued"] == ["CCC"]      # nothing is told twice
    assert N.act(now=later, notify=never, enqueue=never, filed=never)["queued"] == []           # all settled


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
    assert N.act(now=NOW, notify=never, enqueue=never, filed=never)["queued"] == []


def test_a_report_made_after_the_warning_settles_it_and_an_unreadable_sec_list_still_queues(home, monkeypatch):
    monkeypatch.setattr(N, "reports", lambda: {"AAA": report(date="2026-11-26T00:00:00Z"), "BBB": report("BBB")})
    warn(home, "AAA", "a1")
    warn(home, "BBB", "b1")
    warn(home, "CCC", "c1")                                       # no report any more
    queued = []

    def filed(t, since, now):
        raise OSError("SEC unreachable")

    def enqueue(w, hit):
        queued.append((w["ticker"], hit))
        return True
    out = N.act(now=NOW, notify=lambda text: True, enqueue=enqueue, filed=filed)
    assert out["queued"] == ["BBB"] and queued == [("BBB", None)]
    assert sorted(json.loads((home / "state.json").read_text(encoding="utf-8"))["settled"]) == ["a1", "b1", "c1"]


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
    assert out == {"w1": {"ticker": "AAA", "day": "2026-11-24", "serious": True, "direction": "worse", "held": None, "kind": "news",
                          "before": 11.0, "at": 12.0, "after_1": 13.0, "after_20": None, "after_60": None}}   # the stock with no prices waits for the next run
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


# ------------------------------------------------------------ the re-read with press reports
def test_the_evidence_of_a_re_read_is_the_lead_report_of_each_warning_serious_first(home):
    warn(home, "AAA", "note", day="2026-11-24", serious=False)
    warn(home, "AAA", "s1", day="2026-11-23")
    warn(home, "AAA", "old", day="2026-11-01")
    warn(home, "BBB", "other")
    rows_log = N.warnings_log()
    for w in rows_log:
        w["url"] = "https://news.example/" + w["id"]
    N._write(home / "raw" / "AAA" / "2026-11-24.json", {"rows": [{"url": "https://news.example/note", "snippet": "The snippet the check read."}]})

    def fetch(url, title):
        if url.endswith("s1"):
            return "  The whole article under the headline s1. " + "x" * 9000
        raise OSError("blocked")
    rows, ids = N.evidence_rows("AAA", "2026-11-25T21:00:00Z", fetch=fetch, log_rows=rows_log)
    assert ids == ["s1", "note"]
    assert rows[0]["text_from"] == "article" and len(rows[0]["text"]) == N.EVIDENCE_CHARS and rows[0]["date"] == "2026-11-23"
    assert rows[0]["text"].startswith("headline s1.\n\nThe whole article")
    assert rows[1]["text"] == "headline note. The snippet the check read." and rows[1]["text_from"] == "headline_and_snippet"
    assert rows[1]["publisher"] == "news.example" and all(N.hashlib.sha256(r["text"].encode("utf-8")).hexdigest() == r["text_sha256"] for r in rows)


def test_the_valuation_is_given_the_reading_without_its_news_cited_claims():
    an = {"status": "ok", "tasks": {"material_events": {"claims": [{"claim": "from a filing", "fact_ids": ["P1"]},
                                                                  {"claim": "from the press", "fact_ids": ["N1"]},
                                                                  {"claim": "both", "fact_ids": ["F2", "N3"]}]},
                                    "risks": {"claims": [{"claim": "no ids"}]}, "thesis_change": None}}
    out = N.without_news_claims(an)
    assert [c["claim"] for c in out["tasks"]["material_events"]["claims"]] == ["from a filing"]
    assert out["tasks"]["risks"]["claims"] == [{"claim": "no ids"}] and len(an["tasks"]["material_events"]["claims"]) == 3
    assert N.without_news_claims(None) == {}


def test_a_shell_page_or_another_page_is_not_the_article():
    headline = "Alpha Corp loses its largest customer to a rival"
    assert not N.is_article("MSN", headline) and not N.is_article(None, headline)
    assert not N.is_article("Cookie settings and navigation. " * 60, headline)
    assert N.is_article("Alpha Corp said its largest customer left for a rival. " + "More of the report. " * 40, headline)


# ------------------------------------------------------------ held names (PLAN_held_names_monitor_2026-11-27)
def holding(monkeypatch, *tickers):
    monkeypatch.setattr(N, "held", lambda reps=None: set(tickers))


def test_held_is_the_watched_stocks_the_published_overlay_rates_buy(home, monkeypatch):
    monkeypatch.setattr(N, "held", REAL_HELD)
    monkeypatch.setattr(N.G, "OVERLAY", home / "overlay.json")
    reps = {t: report(t) for t in ("AAA", "BBB", "CCC")}
    assert N.held(reps) == set()                                                           # no overlay file: nothing is held
    N._write(home / "overlay.json", {"tickers": {"AAA": {"verdict": "BUY", "analysis": "complete"}, "BBB": {"verdict": "WATCH", "analysis": "complete"},
                                                 "CCC": {"verdict": "BUY", "analysis": "not run"}, "ZZZ": {"verdict": "BUY", "analysis": "complete"}}})
    assert N.held(reps) == {"AAA"}                                                         # not WATCH, not a stock never analysed, not an unwatched stock


def test_a_held_stock_whose_warning_is_worse_or_unclear_is_queued_first_inside_the_same_cap(home, monkeypatch):
    acting(home, monkeypatch, ["AAA", "BBB", "CCC", "DDD", "EEE"])
    holding(monkeypatch, "BBB", "CCC", "DDD")
    for t, wid, d in (("AAA", "a1", "worse"), ("BBB", "b1", "worse"), ("CCC", "c1", "better"), ("DDD", "d1", "unclear"), ("EEE", "e1", "worse")):
        warn(home, t, wid, direction=d)
    queued, told = [], []

    def enqueue(w, hit):
        queued.append(w["ticker"])
        return True
    out = N.act(now=NOW, notify=lambda text: told.append(text) or True, enqueue=enqueue, filed=lambda t, since, now: HIT if t == "AAA" else None)
    # held and not better first (BBB worse, DDD unclear), then the others as before: the one that has filed, then worst first
    assert queued == ["BBB", "DDD", "AAA"] and out["over_cap"] == ["EEE", "CCC"] and len(queued) == N.REREADS_A_DAY
    lines = told[0].splitlines()
    assert lines[0] == f"News watch {DAY}: 5 serious warnings on 5 stocks; 3 held stocks in this message"
    assert [ln.split(" (")[0] for ln in lines[1:6]] == ["HELD BBB", "HELD DDD", "HELD CCC", "AAA", "EEE"]


def test_with_no_held_stock_the_order_and_the_message_are_as_before(home, monkeypatch):
    acting(home, monkeypatch, ["AAA", "BBB"])
    warn(home, "AAA", "a1", direction="unclear")
    warn(home, "BBB", "b1")
    told = []
    out = N.act(now=NOW, notify=lambda text: told.append(text) or True, enqueue=lambda w, hit: True, filed=lambda t, since, now: None)
    assert out["queued"] == ["BBB", "AAA"] and told[0].splitlines()[0] == f"News watch {DAY}: 2 serious warnings on 2 stocks" and "HELD" not in told[0]


def code_warn(home, ticker, kind, key, serious, direction):
    w = N.code_warning(ticker, DAY, kind, key, serious, direction, "why " + key, "headline " + key, report(ticker), None)
    with (home / "warnings.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(w) + "\n")
    return w


def test_a_held_stocks_price_move_is_told_once_and_queues_no_re_read(home, monkeypatch):
    acting(home, monkeypatch, ["AAA", "BBB"])
    holding(monkeypatch, "AAA")
    code_warn(home, "AAA", "price_move", "2026-11-24", False, "worse")
    code_warn(home, "BBB", "price_move", "2026-11-24", False, "worse")           # no longer held: not told
    told = []
    out = N.act(now=NOW, notify=lambda text: told.append(text) or True, enqueue=never, filed=never)
    assert out == {"told": 1, "queued": [], "over_cap": []}
    assert told[0].splitlines()[:2] == [f"News watch {DAY}: 0 serious warnings on 0 stocks; 1 held stocks in this message",
                                        "HELD AAA (worse): headline 2026-11-24 | why 2026-11-24"]
    assert N.act(now=NOW, notify=never, enqueue=never, filed=never)["told"] == 0
    news, review = N.for_site(report(), N.warnings_log(), now=NOW)
    assert [w["serious"] for w in news] == [False] and review is None                # shown on the stock's page, the stock is not under review


def test_critical_filings_are_the_8_ks_with_a_critical_item_since_the_report(home):
    keys = ("accessionNumber", "form", "filingDate", "acceptanceDateTime", "reportDate", "items", "primaryDocument")
    rows = [("A-6", "10-Q", "2026-11-21", "2026-11-21T14:00:00.000Z", "", "", "d.htm"),
            ("A-5", "8-K/A", "2026-11-20", "2026-11-20T14:00:00.000Z", "", "1.03", "d.htm"),
            ("A-4", "8-K", "2026-11-18", "2026-11-18T14:00:00.000Z", "", "4.02,2.06,9.01", "d.htm"),
            ("A-3", "8-K", "2026-11-17", "2026-11-17T14:00:00.000Z", "", "2.02,9.01", "d.htm"),
            ("A-2", "8-K", "2026-11-16", "2026-11-16T14:00:00.000Z", "", "", "d.htm"),
            ("A-1", "8-K", "2026-11-01", "2026-11-01T14:00:00.000Z", "", "3.01", "d.htm")]
    subs = json.dumps({"filings": {"recent": {k: [r[i] for r in rows] for i, k in enumerate(keys)}}}).encode()
    since = datetime(2026, 11, 10, tzinfo=timezone.utc)
    got = N.critical_filings("AAA", since, NOW, get=lambda url: subs, ciks={"AAA": "0000000001"})
    assert got == [("A-4", "8-K", ["2.06", "4.02"], "0000000001"), ("A-5", "8-K/A", ["1.03"], "0000000001")]      # oldest first; earnings, no item, before the report: none
    assert N.critical_filings("AAA", datetime(2026, 11, 24, tzinfo=timezone.utc), NOW, get=lambda url: subs, ciks={"AAA": "0000000001"}) == []
    with pytest.raises(ValueError):
        N.critical_filings("AAA", since, NOW, get=lambda url: subs, ciks={})
    assert set(N.CRITICAL_ITEMS) == set(N.M.P0_ITEMS)


def closes(last, n=70):
    from datetime import date, timedelta
    d0 = date(2026, 8, 1)
    pts = [{"date": (d0 + timedelta(days=k)).isoformat(), "close": 100.0 + (0.5 if k % 2 else -0.5)} for k in range(n)]
    pts.append({"date": (d0 + timedelta(days=n)).isoformat(), "close": last})
    return pts


def test_held_signals_raise_a_serious_warning_for_a_critical_filing_and_a_plain_one_for_a_price_move(home, monkeypatch):
    acting(home, monkeypatch, ["AAA", "BBB"])
    holding(monkeypatch, "AAA")
    asked = []

    def filings(t, since, now):
        asked.append(t)
        return [("A-4", "8-K", ["2.06", "4.02"], "0000000001")]

    def prices(t, now):
        c = closes(75.0)
        return {"closes": c, "expected_session": c[-1]["date"]}
    out = N.held_signals(now=NOW, filings=filings, prices=prices)
    assert asked == ["AAA"] and out == {"held": 1, "filing_events": ["AAA"], "price_moves": ["AAA"], "errors": []}       # the stock not held is not looked at
    f, m = N.warnings_log()
    assert (f["kind"], f["serious"], f["direction"], f["reader"], f["held"], f["quote"], f["touches"]) == ("filing_event", True, "unclear", "code", True, None, [])
    assert "item 2.06, a material impairment; item 4.02, earlier financial statements are not to be relied on" in f["why"] and "CIK=0000000001" in f["url"]
    assert (m["kind"], m["serious"], m["direction"], m["url"]) == ("price_move", False, "worse", None) and "-25% over 5 sessions" in m["why"]
    assert N.held_signals(now=NOW, filings=filings, prices=prices)["filing_events"] == [] and len(N.warnings_log()) == 2      # nothing is raised twice
    # the serious one is told and queued as any serious warning; the re-read's press reports do not take a code warning
    queued = []
    N.act(now=NOW, notify=lambda text: True, enqueue=lambda w, hit: queued.append((w["ticker"], w["kind"])) or True, filed=lambda t, since, now: HIT)
    assert queued == [("AAA", "filing_event")]
    assert N.evidence_rows("AAA", "2026-11-25T21:00:00Z", fetch=never, log_rows=N.warnings_log()) == ([], [])


def test_a_quiet_price_a_lagging_quote_and_an_unreadable_source_raise_nothing(home, monkeypatch):
    holding(monkeypatch, "AAA")
    none = lambda t, since, now: []                                                  # noqa: E731
    quiet = closes(100.5)
    assert N.held_signals(now=NOW, filings=none, prices=lambda t, now: {"closes": quiet, "expected_session": quiet[-1]["date"]})["price_moves"] == []
    lag = closes(75.0)
    assert N.held_signals(now=NOW, filings=none, prices=lambda t, now: {"closes": lag, "expected_session": "2026-12-31"})["price_moves"] == []

    def broken(*a):
        raise OSError("unreachable")
    out = N.held_signals(now=NOW, filings=broken, prices=broken)
    assert out["errors"] == ["AAA", "AAA"] and N.warnings_log() == []


def test_a_readers_warning_says_whether_the_stock_was_held_and_the_record_keeps_it(home, monkeypatch):
    gathered(home)
    holding(monkeypatch, "AAA")
    N.check(now=NOW, reader="ollama:m", ollama=lambda m, text, label: json.dumps({"events": [event()]}))
    w = N.warnings_log()[0]
    assert w["held"] is True
    days = ["2026-11-24", "2026-11-25", "2026-11-26"]
    row = N.track(now=NOW, prices=lambda t, now: {"closes": [{"date": d, "close": 10.0 + k} for k, d in enumerate(days)]})[w["id"]]
    assert row["held"] is True and row["kind"] == "news"


def test_the_checks_token_count_takes_a_row_that_carries_only_its_parts(home):
    gathered(home)

    def reader(m, text, label):
        with N.USAGE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": "9999-01-01T00:00:00Z", "reader": "sonnet", "input_tokens": 100, "output_tokens": 20, "thinking_tokens": 5}) + "\n")
            f.write(json.dumps({"at": "9999-01-01T00:00:00Z", "reader": "gemini", "total_tokens": 1000, "input_tokens": 900}) + "\n")
        return json.dumps({"events": []})
    out = N.check(now=NOW, reader="ollama:m", ollama=reader)
    assert (out["calls"], out["tokens"]) == (2, 1125)


def test_one_move_is_told_once_and_a_later_move_again(home, monkeypatch):
    from datetime import timedelta
    holding(monkeypatch, "AAA")
    none = lambda t, since, now: []                                                  # noqa: E731

    def prices(last):
        c = closes(75.0)
        c[-1]["date"] = last
        return lambda t, now: {"closes": c, "expected_session": last}
    assert N.held_signals(now=NOW, filings=none, prices=prices("2026-11-25"))["price_moves"] == ["AAA"]
    assert N.held_signals(now=NOW + timedelta(days=1), filings=none, prices=prices("2026-11-26"))["price_moves"] == []      # the same move, the next session
    assert N.held_signals(now=NOW + timedelta(days=6), filings=none, prices=prices("2026-12-01"))["price_moves"] == []
    assert N.held_signals(now=NOW + timedelta(days=7), filings=none, prices=prices("2026-12-02"))["price_moves"] == ["AAA"]
