"""A refused name is retried the next day; an analysed one waits REFRESH_DAYS (qwen_ondemand.last_analysed / next_name)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qwen_ondemand as Q  # noqa: E402


def _report(site, t, date, ran):
    (site / "ondemand").mkdir(parents=True, exist_ok=True)
    (site / "ondemand" / f"{t}.json").write_text(json.dumps({"ticker": t, "date": date, "analysis": "complete" if ran else "not run"}),
                                                 encoding="utf-8")


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_refusal_retried_after_a_day_analysis_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "SITE", tmp_path)
    monkeypatch.setattr(Q, "QUEUE", tmp_path / "queue.jsonl")
    _report(tmp_path, "OLDREF", _iso(25), ran=False)    # refused 25 h ago: due again
    _report(tmp_path, "NEWREF", _iso(2), ran=False)     # refused 2 h ago: not yet
    _report(tmp_path, "DONE", _iso(25), ran=True)       # analysed 25 h ago: not due for 14 days
    monkeypatch.setattr(Q, "list_names", lambda: ["DONE", "NEWREF", "OLDREF"])
    assert Q.next_name() == ("OLDREF", "list", False)


def test_nothing_due(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "SITE", tmp_path)
    monkeypatch.setattr(Q, "QUEUE", tmp_path / "queue.jsonl")
    _report(tmp_path, "NEWREF", _iso(2), ran=False)
    monkeypatch.setattr(Q, "list_names", lambda: ["NEWREF"])
    assert Q.next_name() is None
