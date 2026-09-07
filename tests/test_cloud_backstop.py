import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api_llm"))
import cloud_backstop  # noqa: E402

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _row(minutes_ago: float, suffix: str = "+00:00"):
    ts = NOW - timedelta(minutes=minutes_ago)
    return [{"updated_at": ts.isoformat().replace("+00:00", suffix)}]


def test_newest_dates_takes_max():
    rows = [
        {"ticker": "AAA", "date": "2026-08-01"},
        {"ticker": "AAA", "date": "2026-08-20"},
        {"ticker": "BBB", "date": "2026-07-15"},
    ]
    assert cloud_backstop.newest_dates(rows) == {"AAA": "2026-08-20", "BBB": "2026-07-15"}


def test_select_due_oldest_first_never_ledgered_wins():
    book = {"AAA", "BBB", "CCC", "DDD"}
    rows = [
        {"ticker": "AAA", "date": "2026-08-20"},
        {"ticker": "BBB", "date": "2026-06-01"},
        {"ticker": "CCC", "date": "2026-07-01"},
    ]
    # DDD has no verdict at all -> first; then oldest dates ascending
    assert cloud_backstop.select_due(book, rows, 3) == ["DDD", "BBB", "CCC"]


def test_select_due_respects_n():
    book = {"AAA", "BBB"}
    assert len(cloud_backstop.select_due(book, [], 1)) == 1


def test_compute_delta_only_new_lines():
    before = ['{"run": 1}', '{"run": 2}']
    after = ['{"run": 1}', '{"run": 2}', '{"run": 3}']
    assert cloud_backstop.compute_delta(before, after) == ['{"run": 3}']


def test_publishable_book_drops_protected_local():
    book = {"AAA", "BBB", "CCC", "DDD"}
    rows = [
        {"ticker": "AAA", "date": "2026-08-01", "arm": "cloud_api"},
        {"ticker": "AAA", "date": "2026-08-20"},                      # newest local
        {"ticker": "BBB", "date": "2026-06-01", "arm": "cloud_api"},  # newest cloud
        {"ticker": "CCC", "date": "2026-07-01"},                      # local only
    ]
    # AAA/CCC protected (newest row local), BBB publishable, DDD never ledgered
    assert cloud_backstop.publishable_book(book, rows) == {"BBB", "DDD"}


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
