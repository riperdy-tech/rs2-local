"""WO_P3b1: the executor (`run_pass`, `python monitor.py run`), tested with a stubbed packet CLI and a stubbed qwen_c runner.

Nothing here starts qwen_c, Ollama or a GPU, and conftest blocks the network. The stub runner writes qwen_c-shaped run directories with
helpers.make_run; the stub packet builder hashes (ticker, T, commit) into a packet sha.
"""
import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import monitor as M
from helpers import AAA, BBB, NOW, make_run, tc, trig

PROMPT, CONTRACT, BUILT = "m3m.prompt.v3", "m3m.analysis.v2", "v6"
AFTER = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)
CCC = {"ticker": "CCC", "cik": 3, "company": "Gammatest Co"}
DDD = {"ticker": "DDD", "cik": 4, "company": "Deltatest Co"}
EARLY, MID = "2026-10-29T10:00:00Z", "2026-10-29T11:00:00Z"


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def write_checks(folder, files):
    """files: {file name: [rows]} -> the folder of check_*.json records."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, rows in files.items():
        (folder / name).write_text(json.dumps(rows), encoding="utf-8")
    return folder


def check_row(commit, updated="2026-10-28T00:00:00Z", verdict="PASS", pair="PASS", run_id="1"):
    r = {"run_id": run_id, "verdict": verdict, "pair": pair, "output_commit": commit}
    if updated:
        r["run_updated_at"] = updated
    return r


class Rig:
    """A monitor root, a fake worktree with a run root, a checks folder, and the stub build / runner with a script of outcomes per ticker."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.root, self.wt = tmp_path / "m3p", tmp_path / "wt"
        self.runs = self.wt / "cache" / "m3m" / "runs"
        self.runs.mkdir(parents=True)
        self.checks = write_checks(tmp_path / "checks", {"check_20261028T000000Z.json": [check_row("c0ffee")]})
        self.mon = M.Monitor(self.root)
        self.build_calls, self.run_calls, self.script, self.fixed_sha, self.refuse, self.n = [], [], {}, {}, {}, 0
        self.packets = {}
        self.news_files = []

    def queue(self, info, tid="sec:1", pr=3, time=EARLY, kind="sec_filing"):
        self.mon.enqueue(info, [trig(tid, pr, time, kind)], NOW)

    def build(self, ticker, T, commit, record, repo, cwd, news_file=None):
        self.build_calls.append((ticker, T, commit, record, str(repo), str(cwd)))
        self.news_files.append(news_file)
        if ticker in self.refuse:
            raise M.PacketRefused(self.refuse[ticker])
        s = self.fixed_sha.get(ticker) or sha(f"{ticker}|{T}|{commit}")
        path = f"packets/{ticker}_{T}.json"
        self.packets[path] = (ticker, T, s)
        return {"packet": path, "packet_sha256": s, "builder_version": BUILT, "annotations": []}

    def runner(self, packet, tasks, seed_base, cwd):
        ticker, T, s = self.packets[packet]
        self.run_calls.append((ticker, tasks, seed_base, str(cwd)))
        what = (self.script.get(ticker) or ["ok"]).pop(0) if self.script.get(ticker) else "ok"
        if what in ("gpu_busy", "gpu_state_unreadable", "model_show_failed"):
            return {"refused": f"{what}: stub"}
        if what == "refused_other":
            return {"refused": "packet has no evidence items"}
        self.n += 1
        if what == "crash_mid":
            d = make_run(self.runs, ticker=ticker, run_no=self.n, T=T, status="running", finished=None, packet_sha=s)
            old = datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc).timestamp()
            os.utime(d / "manifest.json", (old, old))
            return {"crashed": "exit code 1: killed"}
        d = make_run(self.runs, ticker=ticker, run_no=self.n, T=T, packet_sha=s,
                     **({"status": "failed", "finished": "2026-10-30T02:00:00Z"} if what == "failed"
                        else {"tc_claims": [tc("p1", "unchanged"), tc("p2", "unchanged")]}))
        return {"run_dir": str(d), "status": "complete" if what == "ok" else "failed"}

    def go(self, **kw):
        kw = {"worktree": self.wt, "checks_dir": self.checks, "screener_repo": "screener", "build": self.build, "runner": self.runner,
              "versions": lambda wt: (PROMPT, CONTRACT), "clock": lambda: AFTER, "waiting": lambda: False, **kw}
        return M.run_pass(self.root, **kw)

    def kinds(self, ticker=None):
        return [l["kind"] for l in self.mon.journal_lines() if ticker in (None, l["ticker"])]

    def state(self):
        return self.mon._load()


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


# ---------------------------------------------------------------- order

def test_entries_run_in_priority_then_trigger_time_order(rig):
    rig.queue(AAA, "a", 3, EARLY)
    rig.queue(BBB, "b", 0, MID)
    rig.queue(CCC, "g", 2, "2026-10-29T09:00:00Z")
    rig.queue(DDD, "d", 0, "2026-10-29T10:30:00Z")
    rep = rig.go()
    assert [r[0] for r in rig.run_calls] == ["DDD", "BBB", "CCC", "AAA"]
    assert [e["ticker"] for e in rep["entries"]] == ["DDD", "BBB", "CCC", "AAA"] and rep["stopped"] is None
    assert rig.mon.ordered() == []


def test_limit_takes_the_first_n_and_an_entry_is_taken_once_per_pass(rig):
    rig.queue(AAA, "a", 0, EARLY)
    rig.queue(BBB, "b", 2, EARLY)
    rig.script["AAA"] = ["failed"]
    rig.go(limit=1)
    assert [r[0] for r in rig.run_calls] == ["AAA"] and "BBB" in rig.state()["queue"]
    rig.go()                                                              # AAA failed once and is retried; BBB runs; neither twice in a pass
    assert sorted(r[0] for r in rig.run_calls) == ["AAA", "AAA", "BBB"]


# ---------------------------------------------------------------- the commit at T

def test_the_commit_is_the_newest_verified_one_at_or_before_T(tmp_path):
    f1 = write_checks(tmp_path / "ck", {
        "check_20261020T000000Z.json": [check_row("aaa", "2026-10-20T10:00:00Z"), check_row("bbb", "2026-10-25T10:00:00Z"),
                                        check_row("ddd", "2026-10-26T10:00:00Z", pair="FAIL")],
        "check_20261027T000000Z.json": [check_row("ccc", "2026-10-27T10:00:00Z"), check_row("eee", "2026-10-26T12:00:00Z", verdict="FAIL"),
                                        check_row("fff", None), check_row("", "2026-10-26T13:00:00Z")]})
    got = lambda T: M.verified_commit(f1, T)
    assert got("2026-10-26T00:00:00Z")["commit"] == "bbb" and got("2026-10-26T00:00:00Z")["check_file"] == str(f1 / "check_20261020T000000Z.json")
    assert got("2026-10-25T10:00:00Z")["commit"] == "bbb"                      # at T: eligible
    assert got("2026-10-25T09:59:59Z")["commit"] == "aaa"                      # a second before: not
    assert got("2026-11-01T00:00:00Z")["commit"] == "ccc" and got("2026-11-01T00:00:00Z")["check_file"].endswith("check_20261027T000000Z.json")
    assert got("2026-10-19T00:00:00Z") is None
    assert M.verified_commit(tmp_path / "nowhere", "2026-11-01T00:00:00Z") is None


def test_the_packet_is_built_at_T_with_that_commit_and_check_file(rig):
    write_checks(rig.checks, {"check_20261029T000000Z.json": [check_row("newer", "2026-10-29T10:30:00Z")]})
    rig.queue(AAA, "a", 3, MID)                                           # T = 11:00: `newer` (10:30) is the newest at or before it
    rig.go()
    t, T, commit, record, repo, cwd = rig.build_calls[0]
    assert (t, T, commit) == ("AAA", MID, "newer") and record.endswith("check_20261029T000000Z.json") and repo == "screener" and cwd == str(rig.wt)


def test_T_is_the_latest_trigger_time_of_the_entry_whole_seconds_z(rig):
    rig.mon.enqueue(AAA, [trig("a", 0, "2026-10-29T10:00:00+00:00"), trig("b", 3, "2026-10-29T10:45:30Z")], NOW)
    rig.go()
    assert rig.build_calls[0][1] == "2026-10-29T10:45:30Z" and rig.mon.ordered() == []   # one run at that T covers both triggers


def test_no_verified_commit_at_T_is_a_failed_step_and_nothing_is_built_or_run(rig):
    rig.queue(AAA, "a", 3, "2026-10-27T00:00:00Z")                        # the only PASS row is of 10-28
    rep = rig.go()
    assert rig.build_calls == [] and rig.run_calls == [] and rep["entries"][0]["outcome"] == "failed:no_verified_commit_at_T"
    f = [l for l in rig.mon.journal_lines() if l["kind"] == "failed"][0]
    assert f["cause"] == "no_verified_commit_at_T" and f["status"] == "not_run" and f["run_id"].startswith("norun:AAA:")
    n = rig.state()["names"]["AAA"]
    assert n["pending_review"] is True and n["consecutive_unusable"] == 1 and rig.state()["queue"]["AAA"]["attempts"] == 1


# ---------------------------------------------------------------- refusals and the carry rule

def test_a_packet_refusal_journals_failed_with_the_refusal_and_runs_nothing(rig):
    rig.queue(AAA)
    rig.refuse["AAA"] = "frame_commit_after_T: the commit is later than T"
    rep = rig.go()
    assert rig.run_calls == [] and rep["entries"][0]["outcome"] == "failed:packet_refused"
    f = [l for l in rig.mon.journal_lines() if l["kind"] == "failed"][0]
    assert f["cause"] == "packet_refused" and "frame_commit_after_T" in f["detail"] and f["retry_queued"] is True and f["entry_dropped"] is False
    assert rig.state()["names"]["AAA"]["pending_reasons"] == ["packet_refused"]


def test_two_refusals_in_a_row_drop_the_entry_and_make_the_name_stale(rig):
    rig.queue(AAA)
    rig.refuse["AAA"] = "refused"
    rig.go()
    assert not rig.state()["names"]["AAA"]["stale_analysis"] and "AAA" in rig.state()["queue"]
    rig.go()
    s = rig.state()
    assert "AAA" not in s["queue"] and s["names"]["AAA"]["stale_analysis"] is True and s["names"]["AAA"]["consecutive_unusable"] == 2
    fails = [l for l in rig.mon.journal_lines() if l["kind"] == "failed"]
    assert len(fails) == 2 and len({l["event_id"] for l in fails}) == 2 and fails[1]["entry_dropped"] is True
    rig.go()                                                               # nothing is left to take
    assert rig.build_calls and len(rig.build_calls) == 2


def test_a_runner_refusal_that_is_not_the_infrastructure_is_a_failed_attempt(rig):
    rig.queue(AAA)
    rig.script["AAA"] = ["refused_other"]
    rep = rig.go()
    assert rep["stopped"] is None and rep["entries"][0]["outcome"] == "failed:runner_refused"
    assert rig.state()["queue"]["AAA"]["attempts"] == 1 and rig.state()["names"]["AAA"]["pending_review"] is True


# ---------------------------------------------------------------- the run key

def test_a_run_key_already_run_absorbs_the_entry_and_does_not_run(rig):
    rig.fixed_sha["AAA"] = sha("same evidence")
    rig.queue(AAA, "sec:1", 3, EARLY)
    rig.go()
    assert len(rig.run_calls) == 1
    rig.queue(AAA, "sec:2", 3, MID)                                       # a new trigger, the same packet bytes
    rep = rig.go()
    assert len(rig.run_calls) == 1 and rep["entries"][0]["outcome"] == "absorbed"
    assert rig.mon.ordered() == [] and "sec:2" in rig.state()["names"]["AAA"]["handled"]
    q = [l for l in rig.mon.journal_lines() if l.get("outcome") == "absorbed_run_key"]
    assert len(q) == 1 and q[0]["run_key"] == rep["entries"][0]["run_key"] and q[0]["run_id"] == "AAA_1"


# ---------------------------------------------------------------- the GPU

@pytest.mark.parametrize("why", ["gpu_busy", "gpu_state_unreadable", "model_show_failed"])
def test_gpu_busy_stops_the_pass_and_counts_no_attempt(rig, why):
    rig.queue(AAA, "a", 0, EARLY)
    rig.queue(BBB, "b", 2, EARLY)
    rig.script["AAA"] = [why]
    rep = rig.go()
    assert rep["stopped"].startswith(why) and [r[0] for r in rig.run_calls] == ["AAA"] and [c[0] for c in rig.build_calls] == ["AAA"]
    s = rig.state()
    assert s["queue"]["AAA"]["attempts"] == 0 and s["names"]["AAA"]["consecutive_unusable"] == 0 and not s["names"]["AAA"]["pending_review"]
    assert set(rig.kinds()) <= {"discovered", "queued"}                    # no failed, no analysed: nothing was lost or counted
    rig.go()                                                               # the card is free: both run, in order
    assert [r[0] for r in rig.run_calls] == ["AAA", "AAA", "BBB"] and rig.mon.ordered() == []


# ---------------------------------------------------------------- ok, failed, tasks

def test_an_ok_run_resolves_and_calls_the_runner_with_the_right_arguments(rig):
    rig.queue(AAA, "a", 2, EARLY)
    rep = rig.go()
    assert rig.run_calls == [("AAA", "material_events,thesis_change", 1000, str(rig.wt))]
    row = rep["entries"][0]
    assert row["outcome"] == "resolved" and row["name_state"] == "thesis_intact" and row["prior_run"] == "PRIOR_RUN" and "run_key_mismatch" not in row
    assert row["run_key"] == M.run_key(AAA["cik"], rig.packets[next(iter(rig.packets))][2], PROMPT, CONTRACT, BUILT)
    assert [k for k in rig.kinds("AAA")] == ["discovered", "queued", "analysed", "resolved"]
    s = rig.state()
    assert row["run_key"] in s["ran_keys"] and s["names"]["AAA"]["last_good"]["run_id"] == "AAA_1" and rig.mon.ordered() == []


def test_a_failed_run_keeps_the_last_good_analysis_and_marks_pending_review(rig):
    rig.queue(AAA, "a", 3, EARLY)
    rig.go()
    good = rig.state()["names"]["AAA"]["last_good"]
    rig.queue(AAA, "b", 3, MID)
    rig.script["AAA"] = ["failed"]
    rep = rig.go()
    assert rep["entries"][0]["outcome"] == "failed"
    n = rig.state()["names"]["AAA"]
    assert n["last_good"] == good and n["pending_review"] is True and n["consecutive_unusable"] == 1 and "AAA" in rig.state()["queue"]
    assert rig.kinds("AAA")[-3:] == ["analysed", "queued", "failed"]


def test_the_two_failure_carry_rule(rig):
    rig.queue(AAA, "a", 3, EARLY)
    rig.script["AAA"] = ["failed", "failed"]
    rig.go()
    s = rig.state()
    assert s["queue"]["AAA"]["attempts"] == 1 and s["names"]["AAA"]["pending_review"] and not s["names"]["AAA"]["stale_analysis"]
    rig.go()
    s = rig.state()
    assert "AAA" not in s["queue"] and s["names"]["AAA"]["consecutive_unusable"] == 2 and s["names"]["AAA"]["stale_analysis"] is True
    assert len(rig.run_calls) == 2 and sum(1 for l in rig.mon.journal_lines() if l["kind"] == "failed") == 2


def test_a_good_run_between_failures_clears_the_streak(rig):
    rig.queue(AAA, "a", 3, EARLY)
    rig.script["AAA"] = ["failed", "ok"]
    rig.go()
    rig.go()
    n = rig.state()["names"]["AAA"]
    assert n["consecutive_unusable"] == 0 and n["pending_review"] is False and n["stale_analysis"] is False and rig.mon.ordered() == []


def test_p4_runs_every_task_and_p0_to_p3_run_two(rig):
    rig.queue(AAA, "refresh:AAA:x", 4, EARLY, kind="refresh")
    rig.queue(BBB, "b", 3, EARLY)
    rig.mon.enqueue(BBB, [trig("refresh:BBB:x", 4, MID, "refresh")], NOW)  # P4 joins a P3 entry: the entry is P3
    rep = rig.go()
    by = {r[0]: r[1] for r in rig.run_calls}
    assert by["AAA"] is None and by["BBB"] == "material_events,thesis_change"
    assert {e["ticker"]: e["tasks"] for e in rep["entries"]} == {"AAA": "all", "BBB": "material_events,thesis_change"}


# ---------------------------------------------------------------- dry run

def snapshot(*folders):
    out = {}
    for f in folders:
        for p in sorted(f.rglob("*")):
            if p.is_file():
                out[str(p)] = p.read_bytes()
    return out


def boom(*a, **k):
    raise AssertionError("a dry run built or ran something")


def test_dry_run_prints_the_plan_and_writes_nothing(rig, capsys):
    rig.queue(AAA, "a", 3, EARLY)
    rig.queue(BBB, "b", 0, MID)
    rig.queue(CCC, "g", 4, EARLY, kind="refresh")
    before = snapshot(rig.tmp)
    rep = M.run_pass(rig.root, worktree=rig.wt, checks_dir=rig.checks, dry_run=True, build=boom, runner=boom, versions=boom, limit=2)
    assert snapshot(rig.tmp) == before and not (rig.root / "state" / "executor.lock").exists()
    assert [(e["ticker"], e["priority"], e["T"], e["commit"], e["tasks"]) for e in rep["entries"]] == [
        ("BBB", 0, MID, "c0ffee", "material_events,thesis_change"), ("AAA", 3, EARLY, "c0ffee", "material_events,thesis_change")]
    rc = M.main(["run", "--dry-run", "--root", str(rig.root), "--worktree", str(rig.wt), "--checks-dir", str(rig.checks)])
    out = capsys.readouterr().out
    assert rc == 0 and "dry run" in out and "P0 BBB" in out and "P4 CCC" in out and "tasks=all" in out and "commit=c0ffee" in out
    assert snapshot(rig.tmp) == before


def test_dry_run_on_a_root_that_does_not_exist_creates_nothing(tmp_path):
    assert M.run_pass(tmp_path / "nowhere", dry_run=True, checks_dir=tmp_path)["entries"] == [] and not (tmp_path / "nowhere").exists()


# ---------------------------------------------------------------- a crash between run and resolve

def test_a_run_that_finished_before_a_crash_is_resolved_not_run_again(rig, monkeypatch):
    rig.queue(AAA, "a", 3, EARLY)
    with monkeypatch.context() as m:
        def power_cut(self, run_dir, now=None):
            raise RuntimeError("power cut between the run and its resolve")
        m.setattr(M.Monitor, "resolve", power_cut)
        with pytest.raises(RuntimeError, match="power cut"):
            rig.go()
    assert len(rig.run_calls) == 1 and "AAA" in rig.state()["queue"] and not (rig.root / "state" / "executor.lock").exists()
    assert rig.state()["ran_keys"] == {} and "resolved" not in rig.kinds()
    rep = rig.go()
    assert len(rig.run_calls) == 1                                          # the first run had finished: its key prevents a second run
    row = rep["entries"][0]
    assert row["outcome"] == "resolved" and row["recovered_run"].endswith("AAA_1") and rig.mon.ordered() == []
    assert row["run_key"] in rig.state()["ran_keys"] and rig.kinds().count("resolved") == 1
    rig.go()
    assert len(rig.run_calls) == 1                                          # and a pass over the empty queue does nothing


def test_a_run_killed_mid_way_is_found_by_the_crash_scan_and_requeued(rig):
    rig.queue(AAA, "a", 3, EARLY)
    rig.script["AAA"] = ["crash_mid", "ok"]
    rep = rig.go()
    assert rep["stopped"].startswith("runner_crashed") and "failed" not in rig.kinds()      # no result: nothing is recorded yet
    assert rig.state()["queue"]["AAA"]["attempts"] == 0
    rep = rig.go()
    assert rep["crash_scan"]["crashed"] == ["AAA_1"] and rep["crash_scan"]["requeued"] == ["AAA_1"]
    kinds = rig.kinds("AAA")
    assert kinds.index("failed") < kinds.index("resolved") and len(rig.run_calls) == 2
    f = [l for l in rig.mon.journal_lines() if l["kind"] == "failed"][0]
    assert f["cause"] == "crashed_no_finished_at" and f["retry_queued"] is True
    n = rig.state()["names"]["AAA"]
    assert n["consecutive_unusable"] == 0 and n["pending_review"] is False and rig.mon.ordered() == []
    rig.go()                                                                # a third pass finds the crashed run recorded, and nothing more
    assert len(rig.run_calls) == 2


# ---------------------------------------------------------------- one instance

def test_one_instance_at_a_time(rig):
    rig.queue(AAA)
    lock = rig.root / "state" / "executor.lock"
    M.take_lock(lock)                                                       # this process holds it: pid_alive says so
    with pytest.raises(M.LockHeld):
        rig.go()
    assert rig.run_calls == [] and lock.exists()
    M.release_lock(lock)
    rig.go()
    assert len(rig.run_calls) == 1 and not lock.exists()


def test_a_dead_pid_lock_is_taken_over(rig):
    rig.queue(AAA)
    lock = rig.root / "state" / "executor.lock"
    lock.write_text("4294967", encoding="utf-8")
    rig.go()
    assert len(rig.run_calls) == 1 and not lock.exists()


def test_unreadable_versions_stop_before_anything_and_release_the_lock(rig):
    rig.queue(AAA)
    def bad(wt):
        raise M.MonitorError("no PROMPT_VERSION")
    with pytest.raises(M.MonitorError):
        rig.go(versions=bad)
    assert rig.build_calls == [] and not (rig.root / "state" / "executor.lock").exists()


# ---------------------------------------------------------------- the real command lines (subprocess stubbed)

class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_the_packet_cli_is_called_in_the_worktree_with_the_documented_arguments(tmp_path, monkeypatch):
    pk = tmp_path / "packet.json"
    pk.write_text(json.dumps({"builder_version": "v6"}), encoding="utf-8")
    seen = []
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **kw: seen.append((cmd, kw)) or FakeProc(
        0, "note\n" + json.dumps({"packet": str(pk), "packet_sha256": "abc", "annotations": ["x"]}), ""))
    got = M.qwen_build_packet("AAA", "2026-10-29T10:00:00Z", "deadbeef", "ck.json", "C:/screener", tmp_path)
    cmd, kw = seen[0]
    assert cmd[1:] == ["-m", "qwen_c.packet", "--ticker", "AAA", "--T", "2026-10-29T10:00:00Z", "--commit", "deadbeef", "--verified-record",
                       "ck.json", "--screener-repo", "C:/screener", "--online"] and kw["cwd"] == str(tmp_path)
    assert got == {"packet": str(pk), "packet_sha256": "abc", "builder_version": "v6", "annotations": ["x"]}


def test_a_packet_cli_failure_is_a_refusal_with_its_text(tmp_path, monkeypatch):
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **kw: FakeProc(1, "", "Traceback ...\nPacketRefused: frame_commit_after_T"))
    with pytest.raises(M.PacketRefused, match="frame_commit_after_T"):
        M.qwen_build_packet("AAA", "2026-10-29T10:00:00Z", "c", "ck.json", "r", tmp_path)
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **kw: FakeProc(0, "not json", ""))
    with pytest.raises(M.PacketRefused):
        M.qwen_build_packet("AAA", "2026-10-29T10:00:00Z", "c", "ck.json", "r", tmp_path)

    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(M.subprocess, "run", hang)
    with pytest.raises(M.PacketRefused, match="timed out"):
        M.qwen_build_packet("AAA", "2026-10-29T10:00:00Z", "c", "ck.json", "r", tmp_path)


def test_the_runner_cli_arguments_and_results(tmp_path, monkeypatch):
    seen = []
    reply = {"v": FakeProc(1, json.dumps({"run_dir": "D", "status": "analysis_incomplete"}), "")}
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **kw: seen.append((cmd, kw)) or reply["v"])
    assert M.qwen_run("pk.json", "material_events,thesis_change", 1000, tmp_path)["run_dir"] == "D"
    assert seen[0][0][1:] == ["-m", "qwen_c.runner", "pk.json", "--tasks", "material_events,thesis_change", "--seed-base", "1000"]
    assert seen[0][1]["cwd"] == str(tmp_path)
    M.qwen_run("pk.json", None, 1000, tmp_path)
    assert seen[1][0][1:] == ["-m", "qwen_c.runner", "pk.json", "--seed-base", "1000"]                  # P4: no --tasks, all of them
    reply["v"] = FakeProc(2, "", "refused: gpu_busy: another model is loaded on the Ollama server: x\n")
    assert M.qwen_run("pk.json", None, 1000, tmp_path) == {"refused": "gpu_busy: another model is loaded on the Ollama server: x"}
    reply["v"] = FakeProc(1, "", "Traceback")
    assert "crashed" in M.qwen_run("pk.json", None, 1000, tmp_path)


def test_qwen_versions_are_read_from_the_source_text(tmp_path):
    (tmp_path / "qwen_c").mkdir()
    (tmp_path / "qwen_c" / "tasks.py").write_text('import x\nPROMPT_VERSION = "m3m.prompt.v9"   # note\n', encoding="utf-8")
    (tmp_path / "qwen_c" / "contract.py").write_text('# CONTRACT = "no"\nCONTRACT = "m3m.analysis.v7"  # y\n', encoding="utf-8")
    assert M.qwen_versions(tmp_path) == ("m3m.prompt.v9", "m3m.analysis.v7")
    (tmp_path / "qwen_c" / "contract.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(M.MonitorError, match="CONTRACT"):
        M.qwen_versions(tmp_path)
    with pytest.raises(M.MonitorError):
        M.qwen_versions(tmp_path / "nowhere")


# ---------------------------------------------------------------- the command

def test_cli_run_uses_the_defaults_of_the_module_and_maps_the_exit_codes(rig, capsys, monkeypatch):
    rig.queue(AAA, "a", 0, EARLY)
    monkeypatch.setattr(M, "qwen_build_packet", rig.build)
    monkeypatch.setattr(M, "qwen_run", rig.runner)
    monkeypatch.setattr(M, "qwen_versions", lambda wt: (PROMPT, CONTRACT))
    args = ["run", "--root", str(rig.root), "--worktree", str(rig.wt), "--checks-dir", str(rig.checks), "--screener-repo", "screener"]
    rig.script["AAA"] = ["gpu_busy"]
    assert M.main(args) == 4 and "stopped: gpu_busy" in capsys.readouterr().out
    assert M.main(args + ["--limit", "1"]) == 0 and "resolved" in capsys.readouterr().out
    M.take_lock(rig.root / "state" / "executor.lock")
    assert M.main(args) == 3 and "held" in capsys.readouterr().err
    M.release_lock(rig.root / "state" / "executor.lock")


def test_the_default_worktree_is_the_repository_root():
    assert M.WORKTREE == M.ROOT == Path(__file__).resolve().parents[3] and M.SEED_BASE == 1000


# ---------------------------------------------------------------- a filing trigger and its effective time (cross-check 2026-11-16, B1)

def test_a_filing_trigger_carries_the_time_the_builder_admits_the_filing():
    # accepted Friday 2026-11-13 21:05:56 ET (02:05:56Z on the 14th), after 17:30 ET: effective at Tuesday's open, as qwen_c.packet says
    from qwen_c import packet
    acc = "2026-11-14T02:05:56Z"
    assert M.filing_effective(acc) == "2026-11-17T14:30:00Z" == M.iso(packet.effective_at(M.parse_utc(acc)))
    res = {"filings": [{"accession": "0000000001-26-000001", "accepted_utc": acc, "accepted_raw": "2026-11-13T21:05:56.000Z", "level": 0,
                        "level_reasons": ["x"], "form": "8-K", "items": "1.01", "filing_date": "2026-11-13", "primary_document": "a.htm",
                        "hits": [], "annotations": []}], "news": [], "price": None}
    (t,) = M.build_triggers(AAA, res, True, NOW)
    assert t["time"] == "2026-11-17T14:30:00Z" and t["accepted_raw"] == "2026-11-13T21:05:56.000Z"


def test_an_entry_whose_trigger_is_not_effective_yet_waits_and_counts_no_attempt(rig):
    later = "2026-10-30T13:30:00Z"                                        # after the pass's clock (AFTER, 03:00Z)
    rig.queue(AAA, "a", 0, later)
    rig.queue(BBB, "b", 3, EARLY)
    rep = rig.go()
    assert [r[0] for r in rig.run_calls] == ["BBB"] and rig.build_calls[0][0] == "BBB"
    assert {e["ticker"]: e["outcome"] for e in rep["entries"]}["AAA"] == "waiting:not_effective_before_T"
    q = rig.state()["queue"]
    assert "AAA" in q and not q["AAA"].get("attempts") and "failed" not in rig.kinds("AAA")
    rig.go(clock=lambda: datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc))      # after its time: it runs, at its own T
    assert [r[0] for r in rig.run_calls] == ["BBB", "AAA"] and rig.build_calls[-1][1] == later


def test_the_pass_yields_to_a_formation_and_counts_no_attempt(rig):
    rig.queue(AAA, "a", 0, EARLY)
    rig.queue(BBB, "b", 3, EARLY)
    rep = rig.go(waiting=lambda: True)                                    # cross-check 2026-11-16, B2
    assert rep["stopped"] == "formation_waiting" and rig.run_calls == [] and rig.build_calls == []
    assert [e["outcome"] for e in rep["entries"]] == ["stopped:formation_waiting"]
    q = rig.state()["queue"]
    assert set(q) == {"AAA", "BBB"} and not q["AAA"].get("attempts") and "failed" not in rig.kinds()
    rig.go()                                                              # the formation is done: both run
    assert [r[0] for r in rig.run_calls] == ["AAA", "BBB"]


def test_a_pass_starts_no_new_entry_after_its_time_budget(rig):
    rig.queue(AAA, "a", 0, EARLY)
    rig.queue(BBB, "b", 3, EARLY)
    def clock():                                                          # 31 minutes pass while the first entry runs
        return AFTER + timedelta(minutes=31 if rig.run_calls else 0)
    rep = rig.go(clock=clock, max_minutes=30, crash_scan=False)
    assert [r[0] for r in rig.run_calls] == ["AAA"] and rep["stopped"].startswith("max_minutes")
    assert "BBB" in rig.state()["queue"] and not rig.state()["queue"]["BBB"].get("attempts")
