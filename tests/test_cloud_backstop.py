import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api_llm"))
import cloud_backstop  # noqa: E402

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _row(minutes_ago: float, suffix: str = "+00:00"):
    ts = NOW - timedelta(minutes=minutes_ago)
    return [{"updated_at": ts.isoformat().replace("+00:00", suffix)}]





def test_compute_delta_only_new_lines():
    before = ['{"run": 1}', '{"run": 2}']
    after = ['{"run": 1}', '{"run": 2}', '{"run": 3}']
    assert cloud_backstop.compute_delta(before, after) == ['{"run": 3}']



def test_overlay_count_fail_closed(tmp_path):
    ok = tmp_path / "ok.json"
    ok.write_text('{"tickers": {"A": {}, "B": {}}}', encoding="utf-8")
    assert cloud_backstop._overlay_count(ok) == 2
    assert cloud_backstop._overlay_count(tmp_path / "missing.json") == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert cloud_backstop._overlay_count(bad) == 0
    nokey = tmp_path / "nokey.json"
    nokey.write_text('{"generated_at": "x"}', encoding="utf-8")
    assert cloud_backstop._overlay_count(nokey) == 0


# ---- publish-time PC-alive interlock (TOCTOU re-check) -----------------------

def test_hb_age_min_math():
    assert cloud_backstop._hb_age_min(_row(45), NOW) == 45
    assert cloud_backstop._hb_age_min(_row(600), NOW) == 600
    # Supabase may hand back a Z suffix
    assert cloud_backstop._hb_age_min(_row(30, "Z"), NOW) == 30


def test_hb_age_min_empty_rows_is_absent_not_error():
    assert cloud_backstop._hb_age_min([], NOW) is None


def test_recheck_alive_dead_boundary(monkeypatch):
    real = cloud_backstop._hb_age_min
    # freeze "now" at NOW so the 90-min boundary is exact
    monkeypatch.setattr(cloud_backstop, "_hb_age_min", lambda rows, now: real(rows, NOW))

    def fetch(rows):
        monkeypatch.setattr(cloud_backstop, "_fetch_hb_rows", lambda: rows)

    fetch(_row(89))
    assert cloud_backstop._pc_alive_recheck() == "alive"
    fetch(_row(90))
    assert cloud_backstop._pc_alive_recheck() == "dead"
    fetch(_row(5000))
    assert cloud_backstop._pc_alive_recheck() == "dead"
    fetch([])
    assert cloud_backstop._pc_alive_recheck() == "dead", "readable-but-absent = dead"


def test_recheck_unreadable_on_fetch_failure(monkeypatch):
    def boom():
        raise OSError("supabase unreachable")
    monkeypatch.setattr(cloud_backstop, "_fetch_hb_rows", boom)
    assert cloud_backstop._pc_alive_recheck() == "unreadable"


def test_recheck_unreadable_on_malformed_row(monkeypatch):
    monkeypatch.setattr(cloud_backstop, "_fetch_hb_rows", lambda: [{"updated_at": "not-a-date"}])
    assert cloud_backstop._pc_alive_recheck() == "unreadable"
    monkeypatch.setattr(cloud_backstop, "_fetch_hb_rows", lambda: [{}])
    assert cloud_backstop._pc_alive_recheck() == "unreadable"


# ── off-peak billing gate (operator 2026-09-07: never pay DeepSeek peak rates) ──
from deepseek_offpeak import off_peak, run_window_ok  # noqa: E402


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_off_peak_weekday_windows():
    thu = 3  # 2026-09-03 is a Thursday
    assert not off_peak(_utc(2026, 9, thu, 1))      # 01:00 peak opens
    assert not off_peak(_utc(2026, 9, thu, 3, 59))
    assert off_peak(_utc(2026, 9, thu, 4))          # 04:00 gap
    assert off_peak(_utc(2026, 9, thu, 5, 59))
    assert not off_peak(_utc(2026, 9, thu, 6))      # second peak block
    assert not off_peak(_utc(2026, 9, thu, 9, 59))
    assert off_peak(_utc(2026, 9, thu, 10))         # long off-peak stretch
    assert off_peak(_utc(2026, 9, thu, 0, 59))


def test_off_peak_weekend_always():
    assert off_peak(_utc(2026, 9, 5, 7))   # Saturday inside a weekday peak hour
    assert off_peak(_utc(2026, 9, 6, 2))   # Sunday


def test_run_window_rejects_the_two_real_runs_that_were_billed_at_peak():
    # 2026-09-03 07:50 UTC (Thu): the actual Sep 3 backstop start — peak.
    assert not run_window_ok(_utc(2026, 9, 3, 7, 50), 2700)
    # 2026-09-05 07:27 UTC (Sat): the Sep 5 start — off-peak, allowed.
    assert run_window_ok(_utc(2026, 9, 5, 7, 27), 2700)


def test_run_window_needs_the_whole_ticker_inside_off_peak():
    # 00:30 Thu + 45 min crosses into the 01:00 peak -> refuse
    assert not run_window_ok(_utc(2026, 9, 3, 0, 30), 2700)
    # 00:14 + 45 min ends 00:59 -> ok
    assert run_window_ok(_utc(2026, 9, 3, 0, 14), 2700)
    # 05:30 + 45 min crosses 06:00 -> refuse; 04:05 + 45 min -> ok (the 2h gap)
    assert not run_window_ok(_utc(2026, 9, 3, 5, 30), 2700)
    assert run_window_ok(_utc(2026, 9, 3, 4, 5), 2700)


def test_run_window_new_cron_survives_nine_hours_of_drift():
    # cron 10:05 UTC; GitHub has delivered crons 0-9h late -> every arrival ok
    for drift_h in range(0, 10):
        assert run_window_ok(_utc(2026, 9, 3, 10, 5) + timedelta(hours=drift_h), 2700)
    # and a full 6-ticker worst case (6 x 45 min) fits even from the latest arrival
    assert run_window_ok(_utc(2026, 9, 3, 19, 5), 6 * 2700)


def test_ladder_every_arrival_fits_one_ticker_and_the_last_rung_defers_into_peak():
    # cron 10:05/14:05/18:05/22:05 UTC, weekday (2026-09-03 Thu)
    for hh in (10, 14, 18, 22):
        assert run_window_ok(_utc(2026, 9, 3, hh, 5), 2700)
    # 22:05 + 6 x 45 min would end 02:35 — crosses the 01:00 peak: the driver's per-ticker
    # re-check defers the tail. Ticker 3 starts 23:35 and ends 00:20 (ok); ticker 4 would start
    # 00:20 and end 01:05, inside the peak -> the first one refused.
    assert run_window_ok(_utc(2026, 9, 3, 22, 5) + timedelta(seconds=2 * 2700), 2700)
    assert not run_window_ok(_utc(2026, 9, 3, 22, 5) + timedelta(seconds=3 * 2700), 2700)
    # a 22:05 rung drifted 3h lands at 01:05 = peak -> preflight skips (no billing)
    assert not run_window_ok(_utc(2026, 9, 4, 1, 5), 2700)


# ── state handback to rs2-state (continuity: PC + next cloud run continue from it) ──

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def _state_repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    clone = tmp_path / "rs2-state"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    _git(clone, "commit", "--allow-empty", "-m", "init")
    _git(clone, "push", "-u", "origin", "HEAD")
    return clone


def _local_state(tmp_path, monkeypatch, membership, state):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "depth_membership.jsonl").write_text(membership, encoding="utf-8")
    (cache / "depth_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(cloud_backstop, "MEMBERSHIP", cache / "depth_membership.jsonl")
    monkeypatch.setattr(cloud_backstop, "STATE", cache / "depth_state.json")


def test_handback_pushes_delta_membership_and_state(tmp_path, monkeypatch):
    clone = _state_repo(tmp_path)
    mem = '{"date": "2026-09-06", "in": ["AAA"]}\n{"date": "2026-09-07", "in": ["AAA", "BBB"]}\n'
    st = {"AAA": {"ok": True, "date": "2026-09-07 18:30", "arm": "cloud_api"}}
    _local_state(tmp_path, monkeypatch, mem, st)
    err = cloud_backstop._handback_state(clone, ['{"ticker": "AAA", "arm": "cloud_api"}'],
                                         "2026-09-07 10:30:00Z")
    assert err == ""
    # everything reached the REMOTE, not just the working tree
    def show(f):
        return _git(clone, "show", f"@{{u}}:{f}")
    assert show("cloud_pending/depth_ledger_delta.jsonl") == '{"ticker": "AAA", "arm": "cloud_api"}\n'
    assert show("cache/depth_membership.jsonl") == mem
    assert json.loads(show("cache/depth_state.json")) == st
    assert "cloud continuity 2026-09-07 10:30:00Z" in _git(clone, "log", "--oneline")


def test_handback_appends_to_an_existing_delta(tmp_path, monkeypatch):
    clone = _state_repo(tmp_path)
    (clone / "cloud_pending").mkdir()
    (clone / "cloud_pending" / "depth_ledger_delta.jsonl").write_text('{"r": 1}\n', encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-m", "prior cloud run"); _git(clone, "push")
    _local_state(tmp_path, monkeypatch, "", {})
    assert cloud_backstop._handback_state(clone, ['{"r": 2}'], "ts") == ""
    assert _git(clone, "show", "@{u}:cloud_pending/depth_ledger_delta.jsonl") == '{"r": 1}\n{"r": 2}\n'


def test_handback_no_change_makes_no_commit(tmp_path, monkeypatch):
    clone = _state_repo(tmp_path)
    (clone / "cache").mkdir()
    (clone / "cache" / "depth_membership.jsonl").write_text("same\n", encoding="utf-8")
    (clone / "cache" / "depth_state.json").write_text("{}", encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-m", "seed"); _git(clone, "push")
    _local_state(tmp_path, monkeypatch, "same\n", {})
    before = _git(clone, "rev-parse", "HEAD")
    assert cloud_backstop._handback_state(clone, [], "ts") == ""
    assert _git(clone, "rev-parse", "HEAD") == before


def test_handback_reports_a_failed_push(tmp_path, monkeypatch):
    clone = _state_repo(tmp_path)
    _local_state(tmp_path, monkeypatch, "row\n", {})
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))
    err = cloud_backstop._handback_state(clone, [], "ts")
    assert err.startswith("rs2-state 'pull --rebase' FAILED") or err.startswith("rs2-state 'push' FAILED")
