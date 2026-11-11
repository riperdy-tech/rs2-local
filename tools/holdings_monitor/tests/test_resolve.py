"""resolve(run_dir): name state, thesis points, the Q1 verdict with date verification, failed runs, sha mismatch, the carry rule (SPEC_m3p 4-5)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import monitor as M
from helpers import AAA, NOW, claim, make_run, tc, trig

T = "2026-10-30T01:00:00Z"
AFTER = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)


def queued(mon, when="2026-10-29T10:00:00Z", pr=0):
    mon.enqueue(AAA, [trig("sec:X", pr, when)], NOW)


# ---------------------------------------------------------------- an ok run

def test_resolve_an_ok_run_sets_state_points_and_clears_the_entry(root, tmp_path):
    mon = M.Monitor(root)
    queued(mon)
    run = make_run(tmp_path, tc_claims=[tc("p1", "unchanged"), tc("p2", "changed")], point_ids=("p1", "p2", "p3"))
    line = mon.resolve(run, now=AFTER)
    assert line["kind"] == "resolved" and line["name_state"] == "thesis_changed"
    assert line["points"] == {"p1": "unchanged", "p2": "changed", "p3": "unknown"}       # an unaddressed point is `unknown`, not `unchanged`
    assert line["q1"]["verdict"] == "none" and mon.ordered() == []
    s = mon._load()
    n = s["names"]["AAA"]
    assert n["last_good"]["run_id"] == "AAA_1" and len(n["last_good"]["analysis_sha256"]) == 64
    assert n["pending_review"] is False and n["stale_analysis"] is False and n["consecutive_unusable"] == 0
    assert mon.resolve(run, now=AFTER)["already_resolved"] is True                        # twice: nothing more is written
    assert [l["kind"] for l in mon.journal_lines()].count("resolved") == 1


def test_resolved_line_names_the_triggers_it_covered(root, tmp_path):
    mon = M.Monitor(root)
    mon.enqueue(AAA, [trig("sec:X", 0, "2026-10-29T10:00:00Z"), trig("late", 2, "2026-12-01T00:00:00Z", "news")], NOW)    # the second is after T
    line = mon.resolve(make_run(tmp_path, tc_claims=[tc("p1", "unchanged")]), now=AFTER)
    assert line["triggers"] == [{"id": "sec:X", "kind": "sec_filing", "priority": 0}]
    assert [l["triggers"] for l in mon.journal_lines() if l["kind"] == "resolved"] == [line["triggers"]]
    mon2 = M.Monitor(root / "empty")                                                    # no queue entry: an empty list
    assert mon2.resolve(make_run(tmp_path / "b", tc_claims=[tc("p1", "unchanged")]), now=AFTER)["triggers"] == []


def test_thesis_point_states_stay_distinct(root, tmp_path):
    mon = M.Monitor(root)
    claims = [tc("p1", "unchanged"), tc("p2", "unknown"), tc("p3", "unsupported"), tc("p4", "changed", support="quote_not_found"),
              tc("p5", "unchanged"), tc("p5", "changed")]
    line = mon.resolve(make_run(tmp_path, tc_claims=claims, point_ids=("p1", "p2", "p3", "p4", "p5", "p6")), now=AFTER)
    assert line["points"] == {"p1": "unchanged", "p2": "unknown", "p3": "unsupported", "p4": "unsupported",    # a failed-support claim is not read
                              "p5": "changed", "p6": "unknown"}
    assert line["name_state"] == "thesis_changed"


@pytest.mark.parametrize("claims,state,review", [
    ([tc("p1", "unchanged"), tc("p2", "unchanged")], "thesis_intact", False),
    ([tc("p1", "unknown"), tc("p2", "unsupported")], "thesis_intact", True),           # nothing established: the old state stands, the name is pending_review
])
def test_name_state_from_the_points(root, tmp_path, claims, state, review):
    line = M.Monitor(root).resolve(make_run(tmp_path, tc_claims=claims), now=AFTER)
    assert line["name_state"] == state and line["pending_review"] is review


def test_no_prior_means_the_recorded_thesis_stands(root, tmp_path):
    line = M.Monitor(root).resolve(make_run(tmp_path, tc_status="not_applicable_no_prior", prior=None), now=AFTER)
    assert line["name_state"] == "thesis_intact" and line["thesis_compare"] == "not_applicable" and line["compared_with_run"] is None


# ---------------------------------------------------------------- Q1 with the date verified against the cited items

def q1(mon, tmp_path, n, claims, **kw):
    return mon.resolve(make_run(tmp_path, run_no=n, me_claims=claims, **kw), now=AFTER)


def test_q1_occurred_with_a_printed_date_inside_180_days_acts(root, tmp_path):
    line = q1(M.Monitor(root), tmp_path, 1, [claim()])
    assert line["name_state"] == "event_found" and line["q1"]["verdict"] == "event_found"
    assert line["q1"]["claims"][0]["reason"] == "occurred_within_180d" and line["q1"]["claims"][0]["days_before_T"] == 122


def test_q1_date_forms_and_the_180_day_boundary(root, tmp_path):
    mon = M.Monitor(root)
    # T is 2026-10-30; 180 days before is 2026-05-03
    def run(n, said, printed):
        ev = [{"fact_id": "F1", "kind": "filing", "name": "8-K", "text": f"Event of {printed}.", "source": {"accession": "0000000001-26-000001"},
               "accepted_raw": None, "effective_at": None}]
        return q1(mon, tmp_path, n, [claim(occurred_on=said)], evidence=ev)["q1"]["claims"][0]
    assert run(1, "May 3, 2026", "May 3, 2026")["reason"] == "occurred_within_180d"          # day 180
    assert run(2, "May 2, 2026", "May 2, 2026")["reason"] == "occurred_outside_window"       # day 181
    assert run(3, "May 4, 2026", "May 4, 2026")["reason"] == "occurred_within_180d"          # day 179
    assert run(4, "Oct. 31, 2026", "Oct. 31, 2026")["reason"] == "occurred_on_after_T"
    assert run(5, "2026-08-01", "1 August 2026")["reason"] == "occurred_within_180d"         # ISO said, "D Month YYYY" printed: the same date
    assert run(6, "1 Aug 2026", "Aug. 1, 2026")["reason"] == "occurred_within_180d"
    assert run(7, "Sept 3, 2026", "2026-09-03")["reason"] == "occurred_within_180d"


def test_q1_undated_and_date_unsupported_escalate_and_do_not_act(root, tmp_path):
    mon = M.Monitor(root)
    for n, said in enumerate(("not stated", "", "Q2 2026", None), start=1):
        line = q1(mon, tmp_path, n, [claim(occurred_on=said)])
        assert line["q1"]["verdict"] == "escalation" and line["q1"]["claims"][0]["reason"] == "undated" and line["name_state"] != "event_found"
        assert line["pending_review"] is True and "q1_escalation:undated" in line["pending_reasons"]
    line = q1(mon, tmp_path, 9, [claim(occurred_on="June 29, 2026")])                      # F1 prints June 30, not June 29
    assert line["q1"]["claims"][0]["reason"] == "date_unsupported" and line["q1"]["verdict"] == "escalation"
    line = q1(mon, tmp_path, 10, [claim(occurred_on="June 30, 2026", fact_ids=("F2",))])   # printed in F1 only; the cited item is F2
    assert line["q1"]["claims"][0]["reason"] == "date_unsupported"


def test_q1_announced_pending_acts_without_a_date_and_other_claims_do_not(root, tmp_path):
    mon = M.Monitor(root)
    assert q1(mon, tmp_path, 1, [claim(status="announced_pending", occurred_on="not stated")])["q1"]["verdict"] == "event_found"
    line = q1(mon, tmp_path, 2, [claim(support="quote_not_found")])                         # unsupported critical claim: logged, does not act
    assert line["q1"]["verdict"] == "none" and line["q1"]["claims"][0]["reason"] == "unsupported_critical_claim"
    line = q1(mon, tmp_path, 3, [claim(event_type="material_impairment"), claim(event_type="other_material_event")])
    assert line["q1"]["verdict"] == "none" and line["q1"]["claims"] == []                  # not a C1-C8 type: not Q1's


# ---------------------------------------------------------------- failed runs, refusal, the carry rule

def test_failed_run_keeps_the_last_good_analysis_and_marks_pending_review(root, tmp_path):
    mon = M.Monitor(root)
    mon.resolve(make_run(tmp_path, run_no=1, tc_claims=[tc("p1", "changed")]), now=AFTER)
    good = mon._load()["names"]["AAA"]["last_good"]
    queued(mon, "2026-10-31T10:00:00Z")
    line = mon.resolve(make_run(tmp_path, run_no=2, T="2026-11-01T00:00:00Z", status="analysis_incomplete", finished="2026-11-01T01:00:00Z"),
                       now=AFTER + timedelta(days=2))
    assert line["kind"] == "failed" and line["cause"] == "run_status_analysis_incomplete" and line["kept_last_good_run"] == "AAA_1"
    n = mon._load()["names"]["AAA"]
    assert n["last_good"] == good and n["state"] == "thesis_changed" and n["pending_review"] is True and n["stale_analysis"] is False
    assert n["consecutive_unusable"] == 1
    assert line["retry_queued"] is True and line["entry_dropped"] is False
    e = mon.ordered()[0]
    assert e["attempts"] == 1 and list(e["triggers"]) == ["sec:X"]                           # the entry waits for its second attempt
    assert [l["outcome"] for l in mon.journal_lines() if l["kind"] == "queued" and "outcome" in l] == ["requeued_after_failed_run"]
    # the second failed attempt drops the entry (it was re-queued once); the evidence stays in the journal
    line2 = mon.resolve(make_run(tmp_path, run_no=3, T="2026-11-01T00:00:00Z", status="failed", finished="2026-11-01T05:00:00Z"),
                        now=AFTER + timedelta(days=2, hours=5))
    assert line2["entry_dropped"] is True and mon.ordered() == []
    assert mon._load()["names"]["AAA"]["last_good"] == good


def test_a_crashed_run_with_no_finished_at_is_a_failed_run(root, tmp_path):
    mon = M.Monitor(root)
    line = mon.resolve(make_run(tmp_path, status="running", finished=None), now=AFTER)
    assert line["kind"] == "failed" and line["cause"] == "crashed_no_finished_at"


def test_sha_mismatch_is_refused(root, tmp_path):
    mon = M.Monitor(root)
    mon.resolve(make_run(tmp_path, run_no=1, tc_claims=[tc("p1", "unchanged")]), now=AFTER)
    good = mon._load()["names"]["AAA"]["last_good"]
    queued(mon, "2026-10-31T10:00:00Z")
    bad = make_run(tmp_path, run_no=2, T="2026-11-01T00:00:00Z", finished="2026-11-01T01:00:00Z", me_claims=[claim()], tamper="analysis")
    with pytest.raises(M.ResolveRefused, match="analysis_sha256_mismatch"):
        mon.resolve(bad, now=AFTER + timedelta(days=2))
    n = mon._load()["names"]["AAA"]
    assert n["last_good"] == good and n["state"] == "thesis_intact" and n["pending_review"] is True        # the tampered analysis is not read
    last = mon.journal_lines()[-1]
    assert last["kind"] == "failed" and last["refused"] is True and last["cause"] == "analysis_sha256_mismatch"
    assert "AAA_2" not in {k for k, v in n["runs"].items() if v["outcome"] == "resolved"}
    with pytest.raises(M.ResolveRefused, match="packet_sha256_mismatch"):
        mon.resolve(make_run(tmp_path, run_no=3, T="2026-11-01T00:00:00Z", tamper="packet"), now=AFTER)
    with pytest.raises(M.ResolveRefused, match="manifest.json unreadable"):
        mon.resolve(tmp_path / "nowhere", now=AFTER)


def test_carry_limit_after_two_unusable_runs_in_a_row(root, tmp_path):
    mon = M.Monitor(root)
    mon.resolve(make_run(tmp_path, run_no=1, tc_claims=[tc("p1", "unchanged")]), now=AFTER)
    mon.resolve(make_run(tmp_path, run_no=2, status="failed", finished="2026-10-31T01:00:00Z"), now=AFTER + timedelta(days=1))
    n = mon._load()["names"]["AAA"]
    assert n["pending_review"] and not n["stale_analysis"]                                  # one failure: not stale
    mon.resolve(make_run(tmp_path, run_no=3, status="failed", finished="2026-10-31T02:00:00Z"), now=AFTER + timedelta(days=1, hours=1))
    n = mon._load()["names"]["AAA"]
    assert n["stale_analysis"] is True and n["consecutive_unusable"] == 2 and n["last_good"]["run_id"] == "AAA_1"
    # a good run in between breaks the streak
    mon2 = M.Monitor(root.parent / "m2")
    mon2.resolve(make_run(tmp_path, ticker="BBB", run_no=1, tc_claims=[tc("p1", "unchanged")]), now=AFTER)
    mon2.resolve(make_run(tmp_path, ticker="BBB", run_no=2, status="failed", finished="2026-10-31T01:00:00Z"), now=AFTER)
    mon2.resolve(make_run(tmp_path, ticker="BBB", run_no=3, tc_claims=[tc("p1", "unchanged")], finished="2026-10-31T02:00:00Z"), now=AFTER)
    mon2.resolve(make_run(tmp_path, ticker="BBB", run_no=4, status="failed", finished="2026-10-31T03:00:00Z"), now=AFTER)
    b = mon2._load()["names"]["BBB"]
    assert b["consecutive_unusable"] == 1 and not b["stale_analysis"]


def test_carry_limit_after_21_days(root, tmp_path):
    mon = M.Monitor(root)
    mon.resolve(make_run(tmp_path, run_no=1, T="2026-10-01T00:00:00Z", finished="2026-10-01T00:00:00Z", tc_claims=[tc("p1", "unchanged")]),
                now=datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc))
    mon.resolve(make_run(tmp_path, run_no=2, status="failed", T="2026-10-05T00:00:00Z", finished="2026-10-05T01:00:00Z"),
                now=datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc))
    for now, stale in ((datetime(2026, 10, 21, 23, 59, tzinfo=timezone.utc), False), (datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc), True)):
        mon.update_stale(now)
        assert mon._load()["names"]["AAA"]["stale_analysis"] is stale, now
    # a fresh good run clears it, and the flag shows on the report
    mon.resolve(make_run(tmp_path, run_no=3, T="2026-10-22T00:00:00Z", finished="2026-10-22T01:00:00Z", tc_claims=[tc("p1", "unchanged")]),
                now=datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc))
    n = mon._load()["names"]["AAA"]
    assert n["stale_analysis"] is False and n["pending_review"] is False and n["consecutive_unusable"] == 0
    rep = mon.report(datetime(2026, 10, 22, 3, 0, tzinfo=timezone.utc))
    assert rep["names"]["AAA"] == {"state": "thesis_intact", "pending_review": False, "stale_analysis": False, "last_run_at": "2026-10-22T02:00:00Z"}


def test_a_later_trigger_survives_a_run_that_did_not_cover_it(root, tmp_path):
    mon = M.Monitor(root)
    mon.enqueue(AAA, [trig("early", 3, "2026-10-29T10:00:00Z"), trig("late", 0, "2026-10-30T20:00:00Z")], NOW)
    mon.resolve(make_run(tmp_path, tc_claims=[tc("p1", "unchanged")]), now=AFTER)               # packet T 2026-10-30T01:00Z covers only `early`
    e = mon.ordered()[0]
    assert list(e["triggers"]) == ["late"] and e["priority"] == 0


def test_report_coverage_and_queue_age(root, tmp_path):
    mon = M.Monitor(root)
    mon.run_day({"F": ["AAA"]}, [], {}, {"AAA": AAA}, M.Sources(submissions=lambda c: {"cik": "0000000001", "filings": {"recent": {}}}), NOW)
    rep = mon.report(NOW + timedelta(hours=3))
    assert rep["monitored"] == 1 and rep["run_within_14_days"] == 0 and rep["queue_age_hours_by_priority"] == {"P4": [3.0]}
    mon.resolve(make_run(tmp_path, T=M.iso(NOW), tc_claims=[tc("p1", "unchanged")]), now=NOW + timedelta(hours=4))
    assert mon.report(NOW + timedelta(days=13))["run_within_14_days"] == 1
    assert mon.report(NOW + timedelta(days=15))["run_within_14_days"] == 0
