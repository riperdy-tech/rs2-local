"""The queue, the run key, the 14-day refresh, run_day end to end, the journal, and crash recovery (SPEC_m3p sections 3, 4 and 6)."""
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

import monitor as M
from helpers import AAA, BBB, NOW, feed, filing, make_run, sources, trig, claim, tc, QUIET


def t_iso(hours):
    return M.iso(NOW + timedelta(hours=hours))


# ---------------------------------------------------------------- order and one entry per name

def test_queue_order_priority_then_trigger_time(root):
    mon = M.Monitor(root)
    mon.enqueue(dict(AAA, ticker="XA3"), [trig("a", 3, t_iso(-5))], NOW)
    mon.enqueue(dict(AAA, ticker="XA2"), [trig("b", 2, t_iso(-1))], NOW)
    mon.enqueue(dict(AAA, ticker="XA0late"), [trig("c", 0, t_iso(-1))], NOW)
    mon.enqueue(dict(AAA, ticker="XA0early"), [trig("d", 0, t_iso(-9))], NOW)
    mon.enqueue(dict(AAA, ticker="XA4"), [trig("e", 4, t_iso(-50), "refresh")], NOW)
    mon.enqueue(dict(AAA, ticker="XA1"), [trig("f", 1, t_iso(-2))], NOW)
    assert [e["ticker"] for e in mon.ordered()] == ["XA0early", "XA0late", "XA1", "XA2", "XA3", "XA4"]
    assert mon.next_entry()["ticker"] == "XA0early"


def test_one_entry_per_name_keeps_highest_priority_and_is_not_queued_twice(root):
    mon = M.Monitor(root)
    mon.enqueue(AAA, [trig("a", 3, t_iso(-5))], NOW)
    mon.enqueue(AAA, [trig("b", 2, t_iso(-4))], NOW)
    mon.enqueue(AAA, [trig("c", 0, t_iso(-1))], NOW)
    mon.enqueue(AAA, [trig("d", 3, t_iso(-9))], NOW)                       # a lower trigger never lowers the entry
    q = mon.ordered()
    assert len(q) == 1 and q[0]["priority"] == 0 and q[0]["trigger_time"] == t_iso(-1)
    assert sorted(q[0]["triggers"]) == ["a", "b", "c", "d"] and q[0]["packet_T"] == t_iso(-1)
    assert mon.enqueue(AAA, [trig("c", 0, t_iso(-1))], NOW) is None        # the same trigger again adds nothing
    lines = [l for l in mon.journal_lines() if l["kind"] == "queued"]
    assert [l["priority"] for l in lines] == [3, 2, 0]                       # a `queued` line when the entry is made or its priority rises
    assert len([l for l in mon.journal_lines() if l["kind"] == "discovered"]) == 4


def test_within_a_priority_the_entry_is_ordered_by_its_earliest_trigger_at_that_priority(root):
    mon = M.Monitor(root)
    mon.enqueue(AAA, [trig("a", 2, t_iso(-1)), trig("b", 2, t_iso(-6)), trig("c", 3, t_iso(-30))], NOW)
    assert mon.ordered()[0]["trigger_time"] == t_iso(-6)


# ---------------------------------------------------------------- the run key

def test_run_key_blocks_a_rerun(root, tmp_path):
    mon = M.Monitor(root)
    mon.enqueue(AAA, [trig("a", 0, "2026-10-29T10:00:00Z")], NOW)
    run = make_run(tmp_path, T="2026-10-30T01:00:00Z")
    man = json.loads((run / "manifest.json").read_text())
    key = M.run_key(AAA["cik"], man["packet"]["packet_sha256"], man["prompt_version"], man["contract"], man["builder_version"])
    assert not mon.already_ran(key)
    assert mon.resolve(run, now=NOW)["kind"] == "resolved"
    assert mon.already_ran(key) and mon.ordered() == []
    # the same evidence is never queued as new: a trigger carrying the key is refused, and a queued entry whose packet gives it is absorbed
    assert mon.enqueue(AAA, [trig("b", 0, "2026-10-29T11:00:00Z")], NOW, run_key_=key) is None
    assert mon.ordered() == []
    mon.enqueue(AAA, [trig("b", 0, "2026-10-29T11:00:00Z")], NOW)           # a different key (or none) is queued
    assert len(mon.ordered()) == 1
    assert mon.absorb("AAA", key, NOW)["ticker"] == "AAA" and mon.ordered() == []
    last = mon.journal_lines()[-1]
    assert last["kind"] == "queued" and last["outcome"] == "absorbed_run_key" and last["run_key"] == key
    # a different packet sha, prompt, contract or builder is a different key
    assert len({key, M.run_key(AAA["cik"], "other", "p", "c", "b"), M.run_key(AAA["cik"], man["packet"]["packet_sha256"], "p2", "c", "b")}) == 3


def test_a_trigger_already_handled_is_not_queued_again(root, tmp_path):
    mon = M.Monitor(root)
    mon.enqueue(AAA, [trig("a", 0, "2026-10-29T10:00:00Z")], NOW)
    mon.resolve(make_run(tmp_path), now=NOW)
    assert mon.enqueue(AAA, [trig("a", 0, "2026-10-29T10:00:00Z")], NOW) is None and mon.ordered() == []


# ---------------------------------------------------------------- the 14-day refresh (P4)

def mark_run(root, days_ago):
    mon = M.Monitor(root)
    s = mon._load()
    n = mon._name(s, "AAA", AAA["cik"], AAA["company"], NOW)
    n["last_run_at"] = M.iso(NOW - timedelta(days=days_ago))
    mon._commit(s)


def day(root, mon=None, **kw):
    mon = mon or M.Monitor(root)
    return mon.run_day({"F": ["AAA"]}, [], {}, {"AAA": AAA}, sources([]), NOW, **kw)


def test_refresh_only_after_14_days_without_a_run(root):
    for days_ago, queued in ((13, False), (14, True), (30, True)):
        r = root.parent / f"r{days_ago}"
        mark_run(r, days_ago)
        day(r)
        q = M.Monitor(r).ordered()
        assert bool(q) is queued, days_ago
        if queued:
            assert q[0]["priority"] == 4 and q[0]["triggers"][f"refresh:AAA:2026-10-29"]["kind"] == "refresh"


def test_refresh_for_a_name_never_run_and_not_while_queued(root):
    mon = M.Monitor(root)
    day(root, mon)
    assert [e["priority"] for e in mon.ordered()] == [4]
    day(root, mon)                                                           # already queued: not queued again
    assert len(mon.ordered()) == 1 and len([l for l in mon.journal_lines() if l["kind"] == "queued"]) == 1


def test_refresh_never_outranks_a_real_trigger_but_is_absorbed_by_it(root):
    mon = M.Monitor(root)
    mon.run_day({"F": ["AAA"]}, [], {}, {"AAA": AAA}, sources([filing("0000000001-26-000111", "8-K", "2026-10-28T20:00:00.000Z", "1.03")]), NOW)
    q = mon.ordered()
    assert len(q) == 1 and q[0]["priority"] == 0 and not any(t["kind"] == "refresh" for t in q[0]["triggers"].values())


# ---------------------------------------------------------------- run_day end to end

def test_run_day_end_to_end(root, fixture_json, fixture_text):
    sub = fixture_json("submissions_aaa.json")
    sub_beta = dict(sub, cik="0000000002")
    subs = {1: sub, 2: sub_beta}
    texts = {"0000000001-26-000009": fixture_text("text_8k_bankruptcy.txt")}
    src = M.Sources(submissions=lambda c: subs[int(c)], filing_text=lambda c, acc, doc, form: texts.get(acc, QUIET))
    tickers = {"AAA": AAA, "BBB": BBB, "XOLD": {"cik": 7, "company": "Oldtest Co"}}
    mon = M.Monitor(root)
    sleeps = []
    rep = mon.run_day({"F": ["AAA", "OPXA"]}, ["BBB", "OPXB"], {}, tickers, src, NOW, sleep=sleeps.append, batch=1, pause_s=600)
    assert rep["members"] == ["AAA", "BBB"] and rep["no_cik"] == [] and sleeps == [600]       # excluded names are not members; pacing
    q = {e["ticker"]: e for e in mon.ordered()}
    assert q["AAA"]["priority"] == 0 and q["BBB"]["priority"] == 1          # held: P0; newest book, not held: P1 (same triggers)
    assert sorted(q["AAA"]["triggers"]) == ["sec:0000000001-26-000006", "sec:0000000001-26-000007", "sec:0000000001-26-000008", "sec:0000000001-26-000009"]
    assert q["AAA"]["triggers"]["sec:0000000001-26-000009"]["hits"][0]["class"] == "C1"
    assert q["AAA"]["trigger_time"] == "2026-10-27T17:00:00Z"              # the NT 10-K, the earliest P0 trigger (13:00 read as Eastern wall clock: the later reading)
    # a second day finds nothing new and writes no new lines
    n_lines = len(mon.journal_lines())
    day2 = mon.run_day({"F": ["AAA", "OPXA"]}, ["BBB"], {}, tickers, src, NOW + timedelta(hours=1))
    assert all(v == [] for v in day2["new_triggers"].values()) and len(mon.journal_lines()) == n_lines
    # a name that leaves every group stays 30 days
    rep3 = mon.run_day({"F": ["AAA"]}, [], {}, tickers, src, NOW + timedelta(days=20))
    assert "BBB" in rep3["members"]
    assert "BBB" not in mon.run_day({"F": ["AAA"]}, [], {}, tickers, src, NOW + timedelta(days=51))["members"]


def test_a_member_without_a_cik_is_reported(root):
    rep = M.Monitor(root).run_day({"F": ["XZZZ"]}, [], {}, {}, sources([]), NOW)
    assert rep["no_cik"] == ["XZZZ"] and rep["gathered"] == 0


def test_journal_lines_name_the_prior_run_and_the_dated_evidence(root, tmp_path):
    mon = M.Monitor(root)
    mon.run_day({"F": ["AAA"]}, [], {}, {"AAA": AAA}, sources([filing("0000000001-26-000112", "8-K", "2026-10-28T20:00:00.000Z", "1.03")]), NOW)
    mon.resolve(make_run(tmp_path, run_no=1, tc_claims=[tc("p1", "unchanged"), tc("p2", "unchanged")]), now=NOW)
    kinds = [l["kind"] for l in mon.journal_lines()]
    assert kinds == ["discovered", "queued", "analysed", "resolved"]
    for l in mon.journal_lines():
        assert {"event_id", "t", "ticker", "cik", "prior_run", "evidence"} <= set(l)
    disc, queued, analysed, resolved = mon.journal_lines()
    assert disc["evidence"][0]["accession"] == "0000000001-26-000112" and disc["evidence"][0]["accepted_raw"] == "2026-10-28T20:00:00.000Z"
    assert disc["trigger"]["id"] == "sec:0000000001-26-000112" and disc["times"]["trigger_time"] == "2026-10-29T00:00:00Z"
    assert queued["priority"] == 0 and analysed["run_id"] == "AAA_1" and len(analysed["manifest_sha256"]) == 64
    assert resolved["compared_with_run"]["run_id"] == "PRIOR_RUN" and resolved["name_state"] == "thesis_intact"
    assert {e["accession"] for e in resolved["evidence"]} == {"0000000001-26-000002"}          # the cited, dated item


def test_news_is_journaled_as_secondary_and_queues_nothing(root, fixture_json):
    mon = M.Monitor(root)
    src = sources([], news=lambda c, t, d: fixture_json("news_aaa.json"))
    mon.run_day({"F": ["AAA"]}, [], {}, {"AAA": AAA}, src, NOW)
    news = [l for l in mon.journal_lines() if l["kind"] == "discovered" and l["secondary"]]
    assert len(news) == 1 and news[0]["queues_nothing"] and news[0]["evidence"][0]["label"] == "secondary"
    assert [e["priority"] for e in mon.ordered()] == [4]                     # only the never-run refresh is queued


# ---------------------------------------------------------------- the lock

def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_lock_takes_over_a_dead_pid_and_refuses_a_live_one(root):
    mon = M.Monitor(root)
    root.joinpath("state").mkdir(parents=True)
    mon.lock_path.write_text(str(dead_pid()))
    mon.enqueue(AAA, [trig("a", 0, t_iso(-1))], NOW)                         # took the dead holder's lock
    assert not mon.lock_path.exists()                                        # and released its own
    mon.lock_path.write_text(str(os.getpid()))                               # a live holder (this very process)
    with pytest.raises(M.LockHeld):
        mon.enqueue(AAA, [trig("b", 0, t_iso(-1))], NOW)
    assert mon.lock_path.read_text() == str(os.getpid())                     # a refusal leaves the live holder's lock alone
    mon.lock_path.write_text("")
    with pytest.raises(M.LockHeld):                                          # unnamed and fresh: waited on
        mon.enqueue(AAA, [trig("b", 0, t_iso(-1))], NOW)
    old = os.path.getmtime(mon.lock_path) - 3600
    os.utime(mon.lock_path, (old, old))
    mon.enqueue(AAA, [trig("b", 0, t_iso(-1))], NOW)                         # unnamed and old: its writer died
    assert "b" in mon.ordered()[0]["triggers"]


def test_pid_alive_does_not_kill_the_process_it_asks_about():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert M.pid_alive(p.pid) is True and p.poll() is None
    finally:
        p.kill()
        p.wait()
    assert M.pid_alive(p.pid) is False


# ---------------------------------------------------------------- crash recovery

DRIVER = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import monitor as M
from datetime import datetime, timezone
mode = sys.argv[3]
mon = M.Monitor(sys.argv[2])
if mode == "before_journal":
    mon._write_journal = lambda lines: os._exit(7)
elif mode == "mid_journal":
    orig = mon._write_journal
    def partial(lines):
        orig(lines[:1])
        os._exit(7)
    mon._write_journal = partial
now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
info = {"ticker": "AAA", "cik": 1, "company": "Alphatest Corp"}
trigs = [{"id": "sec:A1", "kind": "sec_filing", "priority": 0, "time": "2026-10-29T10:00:00Z", "reasons": [], "annotations": [], "accession": "A1"},
         {"id": "sec:A2", "kind": "sec_filing", "priority": 3, "time": "2026-10-29T11:00:00Z", "reasons": [], "annotations": [], "accession": "A2"}]
mon.enqueue(info, trigs, now)
'''


@pytest.mark.parametrize("mode,lines_in_journal", [("before_journal", 0), ("mid_journal", 1)])
def test_a_writer_killed_between_the_queue_write_and_the_journal_write(root, tmp_path, state_env, mode, lines_in_journal):
    script = tmp_path / "driver.py"
    script.write_text(DRIVER, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(Path(M.__file__).resolve().parent), str(root), mode], capture_output=True, text=True,
                       env={**os.environ, **state_env})
    assert r.returncode == 7, r.stderr
    mon = M.Monitor(root)
    core = json.loads(mon.core_path.read_text(encoding="utf-8"))
    assert sorted(core["queue"]["AAA"]["triggers"]) == ["sec:A1", "sec:A2"]        # the entry is in the queue: not lost
    assert len(core["outbox"]) == 3                                                   # and the lines it still owes the journal
    assert len(mon.journal_lines()) == lines_in_journal
    assert mon.lock_path.exists()                                                     # the killed writer left its lock behind
    # the next operation finishes the job (taking over the dead lock): each line exactly once
    mon.recover()
    lines = mon.journal_lines()
    assert [l["kind"] for l in lines] == ["discovered", "discovered", "queued"]
    assert len({l["event_id"] for l in lines}) == 3
    assert json.loads(mon.core_path.read_text(encoding="utf-8"))["outbox"] == []
    # the retry of the same work (the writer is run again) adds neither a queue entry nor a journal line
    assert mon.enqueue(AAA, [trig("sec:A1", 0, "2026-10-29T10:00:00Z")], NOW) is None
    mon.recover()
    assert len(mon.journal_lines()) == 3 and len(mon.ordered()) == 1


def test_a_second_recover_does_not_double_a_line(root):
    mon = M.Monitor(root)
    mon.enqueue(AAA, [trig("a", 0, t_iso(-1))], NOW)
    s = mon._load()
    s["outbox"] = list(mon.journal_lines())                                          # as if the clear step never ran
    M.write_json_atomic(mon.core_path, s)
    mon.recover()
    mon.recover()
    assert len(mon.journal_lines()) == 2 and mon._load()["outbox"] == []


def test_a_crash_between_the_queue_and_the_gather_record_loses_and_doubles_nothing(root, monkeypatch):
    rows = [filing("0000000001-26-000120", "8-K", "2026-10-28T20:00:00.000Z", "1.03")]
    mon = M.Monitor(root)
    real = M.write_json_atomic

    def dies_on_gather(path, obj):
        if str(path).split(os.sep)[-1].startswith("gather_"):
            raise KeyboardInterrupt("killed")
        return real(path, obj)
    monkeypatch.setattr(M, "write_json_atomic", dies_on_gather)
    with pytest.raises(KeyboardInterrupt):
        mon.run_day({"F": ["AAA"]}, [], {}, {"AAA": AAA}, sources(rows), NOW)
    monkeypatch.setattr(M, "write_json_atomic", real)
    assert len(mon.ordered()) == 1 and not (root / "state" / "gather_1.json").exists()
    n_lines = len(mon.journal_lines())
    assert n_lines >= 2
    mon2 = M.Monitor(root)
    mon2.run_day({"F": ["AAA"]}, [], {}, {"AAA": AAA}, sources(rows), NOW + timedelta(hours=1))      # the gather runs again and finds it again
    assert list(mon2.ordered()[0]["triggers"]).count("sec:0000000001-26-000120") == 1
    assert len([l for l in mon2.journal_lines() if l["kind"] == "discovered"]) == 1
    assert (root / "state" / "gather_1.json").exists()


def test_a_torn_last_journal_line_is_not_buried(root):
    mon = M.Monitor(root)
    mon.enqueue(AAA, [trig("a", 0, t_iso(-1))], NOW)
    with open(mon.journal_path, "ab") as f:
        f.write(b'{"kind": "disc')                                                   # a torn line
    mon.enqueue(AAA, [trig("b", 0, t_iso(-1))], NOW)
    raw = mon.journal_path.read_bytes().split(b"\n")
    assert raw[2] == b'{"kind": "disc'                                               # still its own line, not glued to the next
    assert [l["kind"] for l in mon.journal_lines()] == ["discovered", "queued", "discovered"]
