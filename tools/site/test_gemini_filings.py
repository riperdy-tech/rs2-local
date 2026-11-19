"""WO_NC10 part B: every filing re-values the name. based_on, the filing trigger, the queue order, the release cap passed by the cloud
worker. Synthetic submissions lists; no network, no model."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_ondemand as G  # noqa: E402

P = G.P
DECISION = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
KEYS = ("accessionNumber", "form", "filingDate", "acceptanceDateTime", "reportDate", "items", "primaryDocument")


def subs(*rows):
    """(accession, form, accepted, report date, items) newest first, as SEC lists them."""
    full = [(a, f, acc[:10], acc, rd, items, "d.htm") for a, f, acc, rd, items in rows]
    return json.dumps({"filings": {"recent": {k: [r[i] for r in full] for i, k in enumerate(KEYS)}}}).encode()


def hit(*rows, since=DECISION, now=NOW):
    return G.triggering_filing(subs(*rows), since, now)


@pytest.mark.parametrize("form", ["10-Q", "10-K", "20-F", "40-F"])
def test_a_periodic_report_after_the_decision_triggers(form):
    assert hit(("A-1", form, "2026-11-05T14:00:00.000Z", "2026-09-30", "")) == (form, "A-1")


def test_a_six_k_triggers_only_as_an_interim_report():
    assert hit(("A-6", "6-K", "2026-11-05T14:00:00.000Z", "2026-09-30", "")) == ("6-K", "A-6")           # period ended 36 days before
    assert hit(("A-6", "6-K", "2026-11-05T14:00:00.000Z", "2026-11-05", "")) is None                     # an event notice: 0 days
    assert hit(("A-6", "6-K", "2026-11-05T14:00:00.000Z", "2026-10-30", "")) is None                     # 6 days: under SIX_K_PERIODIC_DAYS
    assert hit(("A-6", "6-K", "2026-11-05T14:00:00.000Z", "2026-10-29", "")) == ("6-K", "A-6")           # 7 days: an interim report
    assert hit(("A-6", "6-K", "2026-11-05T14:00:00.000Z", None, "")) is None                             # no period of report: never periodic
    assert P.SIX_K_PERIODIC_DAYS == 7


def test_an_eight_k_triggers_only_with_item_2_02():
    assert hit(("A-8", "8-K", "2026-11-05T14:00:00.000Z", "2026-11-05", "2.02,9.01")) == ("8-K", "A-8")
    assert hit(("A-8", "8-K", "2026-11-05T14:00:00.000Z", "2026-11-05", "8.01,9.01")) is None
    assert hit(("A-8", "8-K", "2026-11-05T14:00:00.000Z", "2026-11-05", "5.02")) is None


def test_other_forms_never_trigger():
    for form in ("10-Q/A", "10-K/A", "4", "SC 13G", "S-8", "DEF 14A"):
        assert hit(("A-X", form, "2026-11-05T14:00:00.000Z", "2026-09-30", "2.02")) is None


def test_a_filing_before_the_decision_time_does_not_trigger_and_one_in_the_packet_is_not_new():
    assert hit(("A-1", "10-Q", "2026-08-05T20:00:00.000Z", "2026-06-30", "")) is None                    # accepted and effective before T
    # accepted the day of T but effective at the next open (after T): left out of that packet, so new
    assert hit(("A-1", "10-Q", "2026-08-10T12:00:00.000Z", "2026-06-30", "")) == ("10-Q", "A-1")
    # a packet decided at the filing's own effective time holds it: not new
    since = datetime(2026, 8, 11, 13, 30, tzinfo=timezone.utc)
    assert hit(("A-1", "10-Q", "2026-08-10T12:00:00.000Z", "2026-06-30", ""), since=since) is None


def test_a_filing_not_yet_effective_waits_for_the_check_after_it_is():
    row = ("A-1", "10-Q", "2026-11-20T11:00:00.000Z", "2026-09-30", "")
    assert hit(row) is None and hit(row, now=datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)) == ("10-Q", "A-1")


def test_the_newest_filing_names_the_reason():
    assert hit(("A-8", "8-K", "2026-11-12T14:00:00.000Z", "2026-11-12", "2.02"), ("A-1", "10-Q", "2026-11-05T14:00:00.000Z", "2026-09-30", "")) == ("8-K", "A-8")


# ---- report: based_on -------------------------------------------------------------------------------------------------------------

def item(kind, form, acc, accepted, period=None):
    return {"kind": kind, "form": form, "period": period, "accepted_raw": accepted, "source": {"accession": acc}}


def test_based_on_is_the_newest_periodic_or_interim_filing_of_the_packet():
    pk = {"decision_time_utc": "2026-11-19T00:00:00Z", "evidence": [
        {"kind": "screener_row", "form": None, "accepted_raw": None, "source": {"git_commit": "c"}},
        item("statement", "10-Q", "A-Q", "2026-08-05T20:00:00.000Z", "2026-06-30"), item("annual_section", "10-K", "A-K", "2026-02-20T21:00:00.000Z", "2025-12-31"),
        item("release", "8-K", "A-R", "2026-11-01T20:00:00.000Z")]}
    b = G.based_on(pk)
    assert (b["form"], b["accession"], b["period"], b["accepted"], b["decision_time"]) == ("10-Q", "A-Q", "2026-06-30", "2026-08-05T20:00:00.000Z", "2026-11-19T00:00:00Z")
    assert b["accepted_utc"].startswith("2026-08-0")
    pk["evidence"].append(item("six_k_interim", "6-K", "A-6", "2026-10-30T10:00:00.000Z", "2026-09-30"))
    assert G.based_on(pk)["accession"] == "A-6"                                                          # an interim 6-K is newer than the 10-Q
    assert G.based_on({"decision_time_utc": "z", "evidence": []}) == {"form": None, "accession": None, "period": None, "accepted": None,
                                                                      "accepted_utc": None, "decision_time": "z"}


# ---- queue ------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "SITE", tmp_path / "site")
    monkeypatch.setattr(G, "LOG", tmp_path / "site" / "worker.log")
    monkeypatch.setattr(G, "ONDEMAND", tmp_path / "ondemand")
    monkeypatch.setattr(G, "CLAIMS", tmp_path / "claims")
    monkeypatch.setattr(G, "FILING_CHECK_STATE", tmp_path / "site" / "filing_check.json")
    monkeypatch.setattr(G, "queue_file", lambda: tmp_path / "q" / "queue.jsonl")
    monkeypatch.setattr(G, "ARM", "gemini")
    monkeypatch.setattr(G.Q, "list_names", lambda: ["A", "B", "C", "D"])
    (tmp_path / "q").mkdir()
    (tmp_path / "ondemand").mkdir()
    return tmp_path


def report(site, t, date, based=None, analysis="complete"):
    (site / "ondemand" / f"{t}.json").write_text(json.dumps({"ticker": t, "date": date, "analysis": analysis, "based_on": based}), encoding="utf-8")


def test_queue_order_is_operator_requests_then_filings_then_the_list(site):
    (site / "q" / "queue.jsonl").write_text(json.dumps({"ticker": "D", "source": "web", "requested_at": "2026-11-20T00:00:00Z"}) + "\n", encoding="utf-8")
    assert G.enqueue_filing("C", "10-Q", "A-1") and G.enqueue_filing("B", "8-K", "A-2")
    assert G.next_name() == ("D", "web", True)
    assert G.next_name() == ("C", "new_filing:10-Q:A-1", "filing")           # then the filings, oldest first
    assert G.next_name() == ("B", "new_filing:8-K:A-2", "filing")
    assert G.next_name() == ("A", "list", False)                             # then the list


def test_one_queue_entry_per_name_and_none_behind_an_operator_request(site):
    assert G.enqueue_filing("C", "10-Q", "A-1") and not G.enqueue_filing("C", "8-K", "A-2")
    [q] = [json.loads(x) for x in G.filing_queue_file().read_text(encoding="utf-8").splitlines()]
    assert q["reason"] == "new_filing:10-Q:A-1" and q["ticker"] == "C"
    (site / "q" / "queue.jsonl").write_text(json.dumps({"ticker": "A", "source": "web", "requested_at": "z"}) + "\n", encoding="utf-8")
    assert not G.enqueue_filing("A", "10-K", "A-3")


def test_the_qwen_worker_never_sees_the_filing_queue(site):
    G.enqueue_filing("C", "10-Q", "A-1")
    assert G.filing_queue_file() != G.queue_file() and G.Q._jsonl(G.queue_file()) == []


def test_an_entry_for_a_name_analysed_since_it_was_queued_is_dropped(site):
    G.enqueue_filing("C", "10-Q", "A-1")
    report(site, "C", "2999-01-01T00:00:00Z")                               # re-valued after the entry was queued
    assert G.next_name() == ("A", "list", False) and G.Q._jsonl(G.filing_queue_file()) == []


# ---- check_filings ----------------------------------------------------------------------------------------------------------------

def test_check_filings_queues_stale_names_only_and_survives_a_failed_read(site):
    old = "2026-08-10T20:00:00Z"
    report(site, "A", old, {"decision_time": old})                           # a 10-Q since
    report(site, "B", old, {"decision_time": old})                           # nothing since
    report(site, "C", old)                                                   # its list cannot be read
    report(site, "D", old, analysis="not run")                               # a refused name is watched too: the report's date is the time
    lists = {"1": subs(("N-1", "10-Q", "2026-11-05T14:00:00.000Z", "2026-09-30", "")),
             "2": subs(("O-1", "10-Q", "2026-08-05T20:00:00.000Z", "2026-06-30", "")),
             "3": b"not json",
             "4": subs(("N-4", "8-K", "2026-11-06T14:00:00.000Z", "2026-11-06", "2.02"))}
    urls = []

    def get(url):
        urls.append(url)
        return lists[url[-6]]

    ciks = {"A": "0000000001", "B": "0000000002", "C": "0000000003", "D": "0000000004"}
    out = G.check_filings(get=get, now=NOW, ciks=ciks)
    assert out["queued"] == ["A", "D"] and out["errors"] == ["C"] and out["checked"] == 3 and out["stale"] == 2
    assert all(u.startswith("https://data.sec.gov/submissions/CIK") for u in urls)
    reasons = {q["ticker"]: q["reason"] for q in G.Q._jsonl(G.filing_queue_file())}
    assert reasons == {"A": "new_filing:10-Q:N-1", "D": "new_filing:8-K:N-4"}
    again = G.check_filings(get=get, now=NOW, ciks=ciks)                    # a second check adds nothing: one entry per name
    assert again["queued"] == [] and len(G.Q._jsonl(G.filing_queue_file())) == 2


def test_a_name_without_a_cik_is_an_error_not_a_stop(site):
    report(site, "A", "2026-08-10T20:00:00Z")
    out = G.check_filings(get=lambda url: b"", now=NOW, ciks={})
    assert out["errors"] == ["A"] and out["queued"] == []


def test_the_check_before_a_name_runs_at_most_every_two_hours(site, monkeypatch):
    calls = []
    monkeypatch.setattr(G, "check_filings", lambda: calls.append(1) or G.FILING_CHECK_STATE.parent.mkdir(exist_ok=True) or G.FILING_CHECK_STATE.write_text(json.dumps({"at": G.Q.now_z()}), encoding="utf-8"))
    G.maybe_check_filings()
    G.maybe_check_filings()
    assert calls == [1]
    monkeypatch.setattr(G, "check_filings", lambda: (_ for _ in ()).throw(RuntimeError("sec down")))
    G.FILING_CHECK_STATE.parent.mkdir(exist_ok=True)
    G.FILING_CHECK_STATE.write_text(json.dumps({"at": "2000-01-01T00:00:00Z"}), encoding="utf-8")
    G.maybe_check_filings()                                                  # a failed check is logged, never raised


# ---- the cloud worker's packet ----------------------------------------------------------------------------------------------------

def test_the_cloud_worker_builds_its_packet_with_the_larger_release_cap(site, monkeypatch):
    seen = []

    class R:
        returncode, stdout, stderr = 1, "", "refused for the test"

    monkeypatch.setattr(G.Q, "verified_commit", lambda: ("c", "r"))
    monkeypatch.setattr(G.Q.book_paths, "screener_repo", lambda: site)
    monkeypatch.setattr(G.subprocess, "run", lambda args, **k: seen.append(args) or R())
    assert G.analyze("A", "new_filing:10-Q:A-1") == "refused"
    args = seen[0]
    assert args[args.index("--release-cap") + 1] == "60000" and G.CLOUD_RELEASE_CAP == 60_000 and P.RELEASE_CAP == 14_000
    rep = json.loads((site / "ondemand" / "A.json").read_text(encoding="utf-8"))
    assert rep["source"] == "new filing (new_filing:10-Q:A-1)" and rep["based_on"] is None
