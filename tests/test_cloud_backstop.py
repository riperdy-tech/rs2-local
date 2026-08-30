import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api_llm"))
import cloud_backstop  # noqa: E402


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
