"""WO_P3a: the monitored set from files (item 1), the price source (2), the command line and one gather pass (3), the crash scan (4).
No network (conftest), no git: git show is injected."""
import json
import os
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import monitor as M
from helpers import AAA, BBB, NOW, QUIET, feed, filing, make_run, sources, trig


# ---------------------------------------------------------------- fixtures

def formation(T, book, commit="c" * 40, verdict="PASS"):
    return {"book": book, "formation_T": T, "output_commit": commit, "verifier": {"verdict": verdict}, "decision_time_utc": T + "T18:00:00Z"}


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def act(T, arm, t, action, kind="at_fill_open", causes=None, rule="A0"):
    line = {"formation_T": T, "arm": arm, "ticker": t, "action": action, "kind": kind, "rule": rule}
    if causes:
        line["causes"] = causes
    return line


@pytest.fixture
def dirs(tmp_path):
    fwd, led = tmp_path / "fwd", tmp_path / "ledger"
    write_jsonl(fwd / "formations.jsonl", [formation("2026-09-30", ["XOLA"], "a" * 40), formation("2026-10-30", ["AAA", "BBB", "OPXA"], "b" * 40)])
    return fwd, led


def cik_json(**m):
    return json.dumps({"fetched_at": "x", "map": {k: f"{v:010d}" for k, v in m.items()}}).encode()


# ---------------------------------------------------------------- item 1: the monitored set from files

def test_empty_ledger_falls_back_to_the_newest_a0_book(dirs):
    fwd, led = dirs
    inp = M.ledger_inputs(led, fwd)
    assert inp["source"] == "m3l_forward_fallback" and inp["formation_T"] == "2026-10-30" and inp["ledger_formation_T"] is None
    assert inp["newest_book"] == ["AAA", "BBB", "OPXA"] and inp["books"] == {} and inp["restricted"] == {}
    write_jsonl(led / "formations.jsonl", [])                              # an existing but empty ledger is the same
    assert M.ledger_inputs(led, fwd)["source"] == "m3l_forward_fallback"


def test_ledger_books_and_restrictions_come_from_the_newest_formation(dirs):
    fwd, led = dirs
    write_jsonl(led / "formations.jsonl", [{"formation_T": "2026-09-30"}, {"formation_T": "2026-10-30"}])
    T, old = "2026-10-30", "2026-09-30"
    write_jsonl(led / "actions.jsonl", [
        act(old, "F", "XOLA", "hold"),                                      # an older formation is ignored
        act(T, "F", "AAA", "enter"), act(T, "F", "BBB", "enter"),
        act(T, "FB", "AAA", "enter"), act(T, "FB", "BBB", "new_entry_restricted", causes=["B1"], rule="E1"),
        act(T, "FQ", "AAA", "hold", causes=["Q1"], rule="E1"),            # a restricted incumbent is held
        act(T, "FQ", "BBB", "analysis_pending"),                           # a cash slot is not held ...
        act(T, "FQ", "BBB", "enter_after_pending", kind="pending_resolution"),   # ... until its late line says it entered
        {**act(T, "FQ", "AAA", "escalation", kind="escalation"), "kind": "escalation"},   # not a holding line
        act(T, "FQ_decisions_only", "XGON", "exit", rule="E1"),
    ])
    inp = M.ledger_inputs(led, fwd)
    assert inp["source"] == "m3o_ledger" and inp["ledger_formation_T"] == T
    assert inp["books"] == {"F": ["AAA", "BBB"], "FB": ["AAA"], "FQ": ["AAA", "BBB"]}
    assert inp["restricted"] == {"BBB": "B1", "AAA": "Q1"}
    mem, _ = M.members(inp["books"], inp["newest_book"], inp["restricted"], date(2026, 10, 31))
    assert set(mem) == {"AAA", "BBB"} and "OPXA" not in mem and mem["AAA"]["held"]


def test_a_late_q1_restriction_marks_the_name_restricted(dirs):
    fwd, led = dirs
    write_jsonl(led / "formations.jsonl", [{"formation_T": "2026-10-30"}])
    write_jsonl(led / "actions.jsonl", [act("2026-10-30", "FQ", "BBB", "analysis_pending"),
                                        act("2026-10-30", "FQ", "BBB", "new_entry_restricted", kind="pending_resolution", rule="Q1")])
    inp = M.ledger_inputs(led, fwd)
    assert inp["books"] == {} and inp["restricted"] == {"BBB": "Q1"}


def fv_exit(T, t, applied):
    return {**act(T, "FV", t, "exit", kind="between_formations", rule="V2"), "exit": {"applied": applied}}


def test_fv_book_is_the_latest_formation_with_fv_lines_when_the_newest_has_none(dirs):
    fwd, led = dirs
    write_jsonl(led / "formations.jsonl", [{"formation_T": "2026-11-30"}, {"formation_T": "2026-12-31"}])
    write_jsonl(led / "actions.jsonl", [
        act("2026-11-30", "FV", "XOLA", "enter"), act("2026-11-30", "FV", "AAA", "enter"),
        act("2026-12-31", "F", "BBB", "enter"), act("2026-12-31", "FQ", "BBB", "enter"),        # FV skipped (or is not priced at) the newest formation
    ])
    inp = M.ledger_inputs(led, fwd)
    assert inp["ledger_formation_T"] == "2026-12-31" and inp["books"] == {"F": ["BBB"], "FQ": ["BBB"], "FV": ["AAA", "XOLA"]}
    write_jsonl(led / "actions.jsonl", [act("2026-12-31", "FV", "AAA", "enter"), act("2026-11-30", "FV", "XOLA", "enter")])     # the latest FV formation wins
    assert M.ledger_inputs(led, fwd)["books"] == {"FV": ["AAA"]}


def test_fv_book_loses_a_name_with_an_applied_exit_but_not_a_superseded_one(dirs):
    fwd, led = dirs
    write_jsonl(led / "formations.jsonl", [{"formation_T": "2026-11-30"}])
    T = "2026-11-30"
    write_jsonl(led / "actions.jsonl", [
        act(T, "FV", "AAA", "enter"), act(T, "FV", "BBB", "hold"), act(T, "FV", "XOLA", "enter"), act(T, "FV", "XGON", "exit"),
        act(T, "FV", "NEWB", "not_entered"), act(T, "FV", "AAA", "enter_after_pending", kind="pending_resolution"),   # FV reads enter / hold only
        fv_exit(T, "AAA", True), fv_exit(T, "BBB", False),
        fv_exit("2026-10-31", "XOLA", True),                                # an applied exit under another formation does not touch this one
    ])
    assert M.ledger_inputs(led, fwd)["books"] == {"FV": ["BBB", "XOLA"]}
    write_jsonl(led / "actions.jsonl", [act(T, "FV", "AAA", "enter"), fv_exit(T, "AAA", True)])
    assert M.ledger_inputs(led, fwd)["books"] == {"FV": []}                 # sold: FV holds nothing, the key stays (an FV line exists)


def test_the_other_arms_are_read_as_before_when_fv_is_present(dirs):
    fwd, led = dirs
    write_jsonl(led / "formations.jsonl", [{"formation_T": "2026-10-30"}])
    T = "2026-10-30"
    write_jsonl(led / "actions.jsonl", [act(T, "F", "AAA", "enter"), act(T, "FQ", "BBB", "enter_after_pending", kind="pending_resolution"),
                                        act(T, "FV", "AAA", "enter", causes=["Q1"]), fv_exit(T, "AAA", True)])
    inp = M.ledger_inputs(led, fwd)
    assert inp["books"] == {"F": ["AAA"], "FQ": ["BBB"], "FV": []} and inp["restricted"] == {"AAA": "Q1"}
    write_jsonl(led / "actions.jsonl", [act(T, "F", "AAA", "enter")])        # no FV line anywhere: no FV key
    assert M.ledger_inputs(led, fwd)["books"] == {"F": ["AAA"]}


def test_no_forward_formation_is_an_error(tmp_path):
    with pytest.raises(M.MonitorError):
        M.ledger_inputs(tmp_path / "l", tmp_path / "f")


def test_cik_map_comes_from_the_newest_verified_commit_through_git_show(dirs):
    fwd, led = dirs
    write_jsonl(fwd / "formations.jsonl", [formation("2026-09-30", ["XA"], "a" * 40), formation("2026-10-30", ["XA"], "b" * 40),
                                           formation("2026-11-30", ["XA"], "c" * 40, verdict="FAIL")])
    calls = []

    def git_show(repo, commit, path):
        calls.append((str(repo), commit, path))
        return cik_json(aaa=1, EEE=8)
    m, commit = M.cik_map_for(fwd, Path("repo"), git_show)
    assert commit == "b" * 40 and calls == [("repo", "b" * 40, "public/data/cik_map.json")]
    assert m == {"AAA": 1, "EEE": 8}                              # upper-cased tickers, integer CIKs
    write_jsonl(fwd / "formations.jsonl", [formation("2026-11-30", ["XA"], "c" * 40, verdict="FAIL")])
    with pytest.raises(M.MonitorError):
        M.cik_map_for(fwd, Path("repo"), git_show)


def test_default_git_show_runs_a_read_only_git_show(monkeypatch):
    seen = {}

    def fake_run(cmd, capture_output):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, b"{}", b"")
    monkeypatch.setattr(M.subprocess, "run", fake_run)
    assert M.default_git_show("R", "abc", "p/x.json") == b"{}"
    assert seen["cmd"] == ["git", "-C", "R", "show", "abc:p/x.json"]
    monkeypatch.setattr(M.subprocess, "run", lambda cmd, capture_output: subprocess.CompletedProcess(cmd, 128, b"", b"bad object"))
    with pytest.raises(M.MonitorError, match="bad object"):
        M.default_git_show("R", "abc", "p/x.json")


# ---------------------------------------------------------------- item 2: the price source

def ny(y, m, d, hh, mm):
    from zoneinfo import ZoneInfo
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


@pytest.mark.parametrize("clock,expected", [
    (ny(2026, 10, 29, 15, 59), date(2026, 10, 28)),     # Thursday before the close: Wednesday
    (ny(2026, 10, 29, 16, 14), date(2026, 10, 28)),     # 16:14 is still not complete
    (ny(2026, 10, 29, 16, 15), date(2026, 10, 29)),     # 16:15 is
    (ny(2026, 10, 29, 23, 0), date(2026, 10, 29)),
    (ny(2026, 10, 31, 12, 0), date(2026, 10, 30)),      # Saturday: Friday
    (ny(2026, 11, 2, 9, 0), date(2026, 10, 30)),        # Monday morning: Friday
    (ny(2026, 11, 26, 18, 0), date(2026, 11, 25)),      # Thanksgiving is not a session
    (ny(2026, 11, 27, 9, 0), date(2026, 11, 25)),
])
def test_last_completed_session_uses_the_16_15_new_york_rule(clock, expected):
    assert M.last_completed_session(clock) == expected


def bars(first, n, start=100.0):
    return [(first + timedelta(days=i), start + i) for i in range(n)]


def test_prices_keep_only_completed_sessions_and_record_source_and_dates():
    now = ny(2026, 10, 29, 12, 0)                                           # session 10-29 is open
    rows = bars(date(2026, 10, 20), 10)                                     # 10-20 ... 10-29 (the last one is today's open bar)
    seen = {}

    def fetch(t, start, end):
        seen.update(t=t, start=start, end=end)
        return "fake 1.0", rows
    p = M.yf_prices("AAA", now, fetch)
    assert seen["t"] == "AAA" and seen["end"] == date(2026, 10, 28)
    assert p["source"] == "fake 1.0" and p["quote_date"] == "2026-10-28" and p["expected_session"] == "2026-10-28"
    assert p["fetched_utc"] == M.iso(now) and p["closes"][-1] == {"date": "2026-10-28", "close": 108.0}
    assert all(c["date"] <= "2026-10-28" for c in p["closes"])
    after = M.yf_prices("AAA", ny(2026, 10, 29, 16, 15), fetch)            # after 16:15 the 10-29 bar counts
    assert after["quote_date"] == "2026-10-29" and after["closes"][-1]["close"] == 109.0


def test_prices_keep_the_last_130_sessions_zero_is_a_close_nan_is_not():
    now = ny(2026, 10, 30, 17, 0)
    rows = bars(date(2026, 3, 1), 200)
    rows[-1] = (rows[-1][0], 0.0)                                           # a close of 0.0
    rows[-2] = (rows[-2][0], float("nan"))                                  # a missing one
    p = M.yf_prices("AAA", now, lambda t, s, e: ("fake", rows))
    assert len(p["closes"]) == 130 and p["closes"][-1]["close"] == 0.0
    assert p["closes"][-1]["date"] == "2026-09-16"                          # the last bar is 2026-03-01 + 199 days; the NaN bar before it is dropped
    assert all(c["close"] == c["close"] for c in p["closes"]) and len(p["closes"]) == len({c["date"] for c in p["closes"]})


def test_a_lagging_quote_shows_quote_date_before_expected_session():
    p = M.yf_prices("AAA", ny(2026, 10, 30, 17, 0), lambda t, s, e: ("fake", bars(date(2026, 10, 20), 5)))   # newest bar 10-24
    assert p["quote_date"] == "2026-10-24" and p["expected_session"] == "2026-10-30"


def test_no_close_at_all_is_an_error():
    with pytest.raises(M.MonitorError):
        M.yf_prices("AAA", NOW, lambda t, s, e: ("fake", []))
    with pytest.raises(M.MonitorError):
        M.yf_prices("AAA", NOW, lambda t, s, e: ("fake", [(date(2026, 10, 29), 5.0)]))     # only the open session


def test_gather_records_the_price_source_and_dates():
    p = M.yf_prices("AAA", ny(2026, 10, 30, 17, 0), lambda t, s, e: ("fake", bars(date(2026, 10, 1), 30)))
    res, g = M.gather_name(AAA, None, sources([], prices=lambda t: p), NOW)
    assert res["price_source"] == {"source": "fake", "quote_date": "2026-10-30", "expected_session": "2026-10-30", "fetched_utc": p["fetched_utc"]}


# ---------------------------------------------------------------- item 3: select_names, one gather pass, the command line

TICKS = {"AAA": {"cik": 1, "company": "Alphatest Corp"}, "BBB": {"cik": 2, "company": "Betatest Inc"},
         "BBC": {"cik": 2, "company": "Betatest Inc"}, "CCC": {"cik": 6, "company": "Gammatest Corp"}}


def test_select_names_limit_only_and_shared_cik():
    order = ["AAA", "BBB", "BBC", "CCC", "XNCK"]
    assert M.select_names(order, TICKS) == (["AAA", "BBB", "CCC"], {"BBC": "BBB"}, [])
    assert M.select_names(order, TICKS, limit=2)[0] == ["AAA", "BBB"]
    assert M.select_names(order, TICKS, only=["CCC", "AAA", "OPXA"])[0] == ["AAA", "CCC"]
    assert M.select_names(order, TICKS, only=["CCC", "OPXA"])[2] == ["OPXA"]
    assert M.select_names(order, TICKS, only=["BBC"])[0] == []             # an alias is gathered under its principal
    assert M.select_names(order, TICKS, only=["CCC", "AAA"], limit=1)[0] == ["AAA"]


def pass_env(tmp_path, book=("AAA", "BBB", "BBC", "OPXA"), cik_map=None):
    fwd, led = tmp_path / "fwd", tmp_path / "ledger"
    write_jsonl(fwd / "formations.jsonl", [formation("2026-10-30", list(book), "b" * 40)])
    cm = cik_map or {"AAA": 1, "BBB": 2, "BBC": 2, "OPXA": 5}
    return dict(ledger_dir=led, forward_dir=fwd, repo=Path("repo"), git_show=lambda r, c, p: cik_json(**cm))


def src_by_cik(rows_by_cik, names=None, prices=None):
    names = names or {}
    calls = []

    def subs(cik):
        calls.append(int(cik))
        d = feed(cik, rows_by_cik.get(int(cik), []))
        d["name"] = names.get(int(cik), "Name Corp")
        return d
    return M.Sources(submissions=subs, filing_text=lambda c, a, d, f: QUIET, prices=prices), calls


def test_gather_pass_reads_files_gathers_and_summarises(tmp_path):
    env = pass_env(tmp_path)
    src, calls = src_by_cik({1: [filing("0000000001-26-000900", "8-K", "2026-10-28T20:00:00.000Z", "1.03")]},
                            names={1: "Alphatest Corp", 2: "Betatest Inc"})
    rep = M.gather_pass(tmp_path / "root", NOW, src, **env)
    assert rep["inputs_source"] == "m3l_forward_fallback" and rep["formation_T"] == "2026-10-30" and rep["cik_map_commit"] == "b" * 40
    assert rep["members"] == ["AAA", "BBB", "BBC"]                       # OPXA is operator-excluded
    assert rep["shared_cik"] == {"BBC": "BBB"} and rep["gathered"] == 2
    assert sorted(calls) == [1, 1, 2, 2]                  # one fetch for the company name, one for the gather
    assert rep["new_triggers"]["AAA"] == ["sec:0000000001-26-000900"]
    mon = M.Monitor(tmp_path / "root")
    q = {e["ticker"]: e for e in mon.ordered()}
    assert q["AAA"]["priority"] == 1                                       # not held (the fallback has no books): critical -> P1
    assert "BBB" in q and q["BBB"]["priority"] == 4                       # never run: the 14-day refresh
    assert "BBC" not in q                                                  # the alias is not queued twice
    text = M.format_gather(rep)
    assert "gathered 2" in text and "AAA" in text and "shared_cik" in text
    assert "AAA" in M.format_report(mon.report(NOW))


def test_company_names_come_from_the_submissions_feed(tmp_path):
    env = pass_env(tmp_path)
    src, _ = src_by_cik({}, names={1: "Alphatest Corp"})
    M.gather_pass(tmp_path / "root", NOW, src, only=["AAA"], **env)
    assert M.Monitor(tmp_path / "root")._load()["names"]["AAA"]["company"] == "Alphatest Corp"


def test_gather_pass_limit_and_tickers_leave_the_rest_untouched(tmp_path):
    env = pass_env(tmp_path)
    src, _ = src_by_cik({})
    rep = M.gather_pass(tmp_path / "root", NOW, src, limit=1, **env)
    assert rep["gathered"] == 1 and list(rep["new_triggers"]) == ["AAA"]
    assert [e["ticker"] for e in M.Monitor(tmp_path / "root").ordered()] == ["AAA"]
    rep2 = M.gather_pass(tmp_path / "root", NOW + timedelta(hours=1), src, only=["BBB", "OPXA"], **env)
    assert list(rep2["new_triggers"]) == ["BBB"] and rep2["not_members"] == ["OPXA"]
    assert [e["ticker"] for e in M.Monitor(tmp_path / "root").ordered()] == ["AAA", "BBB"]    # only the gathered names got a refresh


def test_gather_pass_writes_state_and_journal_and_a_second_pass_adds_nothing(tmp_path):
    env = pass_env(tmp_path)
    src, _ = src_by_cik({1: [filing("0000000001-26-000901", "8-K", "2026-10-28T20:00:00.000Z", "1.03")]})
    M.gather_pass(tmp_path / "root", NOW, src, only=["AAA"], **env)
    mon = M.Monitor(tmp_path / "root")
    n1 = len(mon.journal_lines())
    assert (tmp_path / "root" / "state" / "gather_1.json").exists() and n1 >= 2
    rep = M.gather_pass(tmp_path / "root", NOW + timedelta(hours=2), src, only=["AAA"], **env)
    assert rep["new_triggers"]["AAA"] == [] and len(mon.journal_lines()) == n1


def test_gather_pass_with_a_run_root_scans_it_for_crashes(tmp_path):
    env = pass_env(tmp_path)
    src, _ = src_by_cik({})
    runs = tmp_path / "rr"
    rep = M.gather_pass(tmp_path / "root", NOW, src, only=["AAA"], run_root=runs, **env)
    assert rep["crash_scan"]["crashed"] == []


def test_a_name_without_a_cik_is_reported_not_dropped(tmp_path):
    env = pass_env(tmp_path, cik_map={"AAA": 1})
    src, _ = src_by_cik({})
    rep = M.gather_pass(tmp_path / "root", NOW, src, **env)
    assert rep["no_cik"] == ["BBB", "BBC"] and rep["gathered"] == 1


def test_cli_without_sec_contact_stops_before_anything(tmp_path, capsys, monkeypatch):
    called = []
    monkeypatch.setattr(M, "gather_pass", lambda *a, **k: called.append(1))
    assert M.main(["gather", "--root", str(tmp_path / "r")]) == 2
    assert not called and "SEC_USER_AGENT" in capsys.readouterr().err and not (tmp_path / "r").exists()


def test_cli_gather_with_injected_sources_prints_the_summary(tmp_path, capsys, monkeypatch):
    env = pass_env(tmp_path)
    src, _ = src_by_cik({})
    monkeypatch.setenv("SEC_USER_AGENT", "Test Builder test@example.com")
    monkeypatch.setattr(M, "live_sources", lambda now: src)
    monkeypatch.setattr(M, "default_git_show", env["git_show"])
    rc = M.main(["gather", "--root", str(tmp_path / "root"), "--ledger-dir", str(env["ledger_dir"]), "--forward-dir", str(env["forward_dir"]),
                 "--screener-repo", "repo", "--tickers", "aaa, beta", "--limit", "1"])
    out = capsys.readouterr().out
    assert rc == 0 and "gathered 1" in out and "AAA" in out
    assert M.main(["report", "--root", str(tmp_path / "root")]) == 0
    assert "monitored" in capsys.readouterr().out


def test_cli_stops_when_the_lock_is_held(tmp_path, capsys, monkeypatch):
    env = pass_env(tmp_path)
    monkeypatch.setenv("SEC_USER_AGENT", "Test Builder test@example.com")
    monkeypatch.setattr(M, "live_sources", lambda now: src_by_cik({})[0])
    monkeypatch.setattr(M, "default_git_show", env["git_show"])
    (tmp_path / "root" / "state").mkdir(parents=True)
    (tmp_path / "root" / "state" / "monitor.lock").write_text(str(os.getpid()))
    rc = M.main(["gather", "--root", str(tmp_path / "root"), "--ledger-dir", str(env["ledger_dir"]), "--forward-dir", str(env["forward_dir"])])
    assert rc == 3 and "held" in capsys.readouterr().err


def test_live_sources_are_wired_to_the_online_functions(monkeypatch):
    monkeypatch.setattr(M, "online_submissions", lambda cik: {"cik": cik})
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    monkeypatch.setattr(M, "_yf_fetch", lambda t, s, e: ("fake", bars(date(2026, 10, 1), 20)))
    src = M.live_sources(ny(2026, 10, 30, 17, 0))
    assert src.submissions(5) == {"cik": 5} and src.filing_text is M.online_filing_text
    assert src.prices("AAA")["source"] == "fake"
    seen = []
    monkeypatch.setattr(M, "searx_news", lambda c, t, d: seen.append((c, t, d)) or [])
    src.news("Alphatest", "AAA", "2026-10-30")
    assert seen == [("Alphatest", "AAA", date(2026, 10, 30))]


# ---------------------------------------------------------------- item 4: the crash scan

OLD = NOW - timedelta(days=2)


def age(path, when=OLD):
    ts = when.timestamp()
    for p in [path, *Path(path).rglob("*")]:
        os.utime(p, (ts, ts))


def crashed_run(run_root, ticker="AAA", n=1, T="2026-10-30T01:00:00Z", old=True):
    d = make_run(run_root / "runs", ticker=ticker, run_no=n, T=T, status="running", finished=None, tc_claims=None)
    if old:
        age(d)
    return d


def started_by(mon, run_dir, key="k"):
    """The executor's record (Monitor.record_start) of the run that wrote `run_dir`: its ticker and packet sha256 from the manifest."""
    man = json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))
    mon.record_start(man["ticker"], man["packet"]["packet_sha256"], key, NOW - timedelta(days=3))


def known_monitor(root, entry_time="2026-10-29T10:00:00Z"):
    mon = M.Monitor(root)
    mon.enqueue(AAA, [trig("sec:t1", 3, entry_time)], NOW - timedelta(days=3))
    return mon


def test_read_ledger_reports_only_crashed_runs(tmp_path):
    rr = tmp_path / "rr"
    listed = make_run(rr / "runs", run_no=1)                                  # complete and listed in the ledger
    write_jsonl(rr / "ledger.jsonl", [{"run_id": listed.name, "status": "complete"}])
    (rr / "ledger.jsonl").write_text((rr / "ledger.jsonl").read_text() + '{"run_id": "to', encoding="utf-8")      # a torn last line
    make_run(rr / "runs", run_no=2)                                           # complete, not listed: not crashed
    crashed_run(rr, n=3)                                                      # running, no finished_at
    (rr / "runs" / "AAA_9").mkdir()                                          # no manifest at all
    (rr / "runs" / "AAA_8").mkdir()
    (rr / "runs" / "AAA_8" / "manifest.json").write_text("{not json", encoding="utf-8")
    rows = M.read_ledger(rr)
    assert sorted(r["run_id"] for r in rows) == ["AAA_3", "AAA_8", "AAA_9"] and all(r["status"] == "crashed" for r in rows)
    r3 = next(r for r in rows if r["run_id"] == "AAA_3")
    assert r3["ticker"] == "AAA" and r3["T"] == "2026-10-30T01:00:00Z"
    assert "ticker" not in next(r for r in rows if r["run_id"] == "AAA_9")
    assert M.read_ledger(tmp_path / "nothing") == []


def test_a_crashed_run_is_requeued_once_through_the_retry_and_dropped_after_the_second(tmp_path):
    rr = tmp_path / "rr"
    mon = known_monitor(tmp_path / "root")
    started_by(mon, crashed_run(rr, n=1))
    out = mon.crash_scan(rr, NOW)
    assert out["crashed"] == ["AAA_1"] and out["requeued"] == ["AAA_1"] and out["dropped"] == []
    assert mon.ordered()[0]["attempts"] == 1
    kinds = [(l["kind"], l.get("cause") or l.get("outcome")) for l in mon.journal_lines() if l["kind"] in ("failed", "queued")]
    assert ("failed", "crashed_no_finished_at") in kinds and ("queued", "requeued_after_failed_run") in kinds
    again = mon.crash_scan(rr, NOW + timedelta(hours=1))                      # the same crash is not handled twice
    assert again["already_recorded"] == ["AAA_1"] and again["requeued"] == [] and mon.ordered()[0]["attempts"] == 1
    crashed_run(rr, n=2)                                                      # the retry crashes too
    out2 = mon.crash_scan(rr, NOW + timedelta(hours=2))
    assert out2["dropped"] == ["AAA_2"] and out2["requeued"] == [] and mon.ordered() == []
    assert mon._load()["names"]["AAA"]["pending_review"] is True


def test_a_crashed_run_with_no_covering_entry_gets_one_rerun_trigger(tmp_path):
    rr = tmp_path / "rr"
    mon = known_monitor(tmp_path / "root", entry_time="2026-10-31T00:00:00Z")    # the only trigger is later than the crashed run's T
    started_by(mon, crashed_run(rr, n=1, T="2026-10-30T01:00:00Z"))
    out = mon.crash_scan(rr, NOW)
    assert out["requeued"] == ["AAA_1"]
    e = mon.ordered()[0]
    assert "rerun:AAA_1" in e["triggers"] and e["priority"] == 2 and e["attempts"] == 1
    assert e["triggers"]["rerun:AAA_1"]["time"] == "2026-10-30T01:00:00Z"
    crashed_run(rr, n=2, T="2026-10-30T01:00:00Z")                            # the rerun crashes: dropped, not requeued again
    out2 = mon.crash_scan(rr, NOW + timedelta(hours=1))
    assert out2["dropped"] == ["AAA_2"] and "rerun:AAA_1" not in (mon.ordered()[0]["triggers"] if mon.ordered() else {})


def test_a_name_with_no_queue_entry_at_all_gets_the_rerun_trigger(tmp_path):
    rr = tmp_path / "rr"
    mon = M.Monitor(tmp_path / "root")
    mon.enqueue(AAA, [trig("sec:t1", 3, "2026-10-29T10:00:00Z")], NOW - timedelta(days=3))
    s = mon._load()
    s["queue"].clear()                                                        # the name is known, nothing is queued
    M.write_json_atomic(mon.core_path, s)
    started_by(mon, crashed_run(rr, n=1))
    assert mon.crash_scan(rr, NOW)["requeued"] == ["AAA_1"]
    assert [e["ticker"] for e in mon.ordered()] == ["AAA"] and mon.ordered()[0]["priority"] == 2


def test_the_scan_leaves_alone_a_young_run_an_unknown_name_and_an_unreadable_manifest(tmp_path):
    rr = tmp_path / "rr"
    mon = known_monitor(tmp_path / "root")
    started_by(mon, crashed_run(rr, n=1, old=False))                          # written just now: in progress
    started_by(mon, crashed_run(rr, ticker="XZZZ", n=2), key="k2")            # a name the monitor has never seen
    (rr / "runs" / "XD_3").mkdir(parents=True)
    age(rr / "runs" / "XD_3")
    before = json.dumps(mon._load(), sort_keys=True)
    out = mon.crash_scan(rr, datetime.now(timezone.utc))
    assert out["too_recent"] == ["AAA_1"] and out["not_monitored"] == ["XZZZ_2"]
    assert out["crashed"] == ["AAA_1", "XZZZ_2"]                              # the unreadable manifest names no ticker: not ours, not counted
    assert json.dumps(mon._load(), sort_keys=True) == before and out["requeued"] == []


def test_a_foreign_running_run_in_the_root_is_left_alone_and_not_counted(tmp_path):
    rr = tmp_path / "rr"
    mon = known_monitor(tmp_path / "root")
    crashed_run(rr, n=1)                                                      # a known name, old, `running`, but no record: another writer's
    foreign = crashed_run(rr, n=2)
    mon.record_start("AAA", "0" * 64, "k", NOW - timedelta(days=3))           # the monitor's own record is for a different packet
    before = json.dumps(mon._load(), sort_keys=True)
    out = mon.crash_scan(rr, NOW)
    assert out == {"crashed": [], "requeued": [], "dropped": [], "already_recorded": [], "too_recent": [], "not_monitored": []}
    assert json.dumps(mon._load(), sort_keys=True) == before and not [l for l in mon.journal_lines() if l["kind"] == "failed"]
    assert foreign.exists() and mon.ordered()[0]["attempts"] == 0
    started_by(mon, foreign, key="k2")                                        # once the monitor has recorded that packet, the run is its own
    assert mon.crash_scan(rr, NOW)["crashed"] == ["AAA_1", "AAA_2"]


def test_the_executor_records_a_run_before_it_starts_it(tmp_path):
    from test_executor import Rig
    rig = Rig(tmp_path)
    rig.queue(AAA, "a", 3, "2026-10-29T10:00:00Z")
    seen, run = {}, rig.runner

    def runner(packet, tasks, seed, cwd):
        seen["at_start"] = rig.state()["started"]
        return run(packet, tasks, seed, cwd)
    rig.runner = runner
    rig.go()
    (rec,) = seen["at_start"].values()                                       # the record existed when the runner was called
    assert rec["ticker"] == "AAA" and len(rec["packet_sha256"]) == 64 and rec["started"] == "2026-10-30T03:00:00Z" and rec["run_key"] in seen["at_start"]
    rig.runs.mkdir(parents=True, exist_ok=True)
    foreign = crashed_run(rig.wt / "cache" / "m3m", ticker="BBB", n=7)       # another writer's run in the same root, `running` for two days
    out = M.Monitor(rig.root).crash_scan(rig.wt / "cache" / "m3m", NOW)
    assert out["crashed"] == [] and foreign.exists()


# ---------------------------------------------------------------- item 5: nothing in the module calls os.kill on Windows

def test_nothing_in_the_module_calls_os_kill_on_windows():
    src = Path(M.__file__).read_text(encoding="utf-8")
    calls = [l for l in src.splitlines() if l.strip().startswith("os.kill(")]
    assert calls == ["        os.kill(int(pid), 0)"]                           # the one call is the non-Windows branch of pid_alive
