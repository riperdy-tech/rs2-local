"""The Gemini list worker's verdict label and its refresh rule (gemini_ondemand.verdict / last_analysed)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_ondemand as G  # noqa: E402


def _row(price, bear=10.0, base=20.0, valued=True):
    return {"valued": valued, "value_bear": bear, "value_base": base, "price_at_publish": price, "no_value_reason": "why"}


def test_verdict_bands():
    assert G.verdict(_row(9.99))[0] == "BUY"
    assert G.verdict(_row(10.0))[0] == "WATCH"       # at the bear value: not below it
    assert G.verdict(_row(20.0))[0] == "WATCH"       # at the base value: not above it
    assert G.verdict(_row(20.01))[0] == "AVOID"
    assert G.verdict(_row(0.0))[0] == "BUY"          # 0.0 is a price, not an absence


def test_verdict_no_call():
    assert G.verdict(_row(5.0, valued=False)) == ("NO_CALL", "why")
    assert G.verdict(_row(None))[0] == "NO_CALL"
    assert G.verdict(_row(5.0, bear=30.0))[0] == "NO_CALL"   # bear above base: no label is read from it


def test_refusal_is_retried_next_day(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ONDEMAND", tmp_path)
    iso = lambda h: (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat().replace("+00:00", "Z")  # noqa: E731
    for t, h, an in (("DONE", 25, "complete"), ("REFUSED", 25, "not run"), ("FRESHREF", 2, "not run")):
        (tmp_path / f"{t}.json").write_text(json.dumps({"ticker": t, "date": iso(h), "analysis": an}), encoding="utf-8")
    monkeypatch.setattr(G, "CLAIMS", tmp_path / "claims")
    monkeypatch.setattr(G.Q, "list_names", lambda: ["DONE", "FRESHREF", "REFUSED", "NEW"])
    assert G.next_name() == "REFUSED"


def test_two_arms_never_take_the_same_name(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ONDEMAND", tmp_path)
    monkeypatch.setattr(G, "CLAIMS", tmp_path / "claims")
    monkeypatch.setattr(G.Q, "list_names", lambda: ["A", "B", "C"])
    monkeypatch.setattr(G, "ARM", "gemini")
    assert G.next_name() == "A"                      # gemini: from the top
    monkeypatch.setattr(G, "ARM", "opus")
    assert [G.next_name(), G.next_name()] == ["C", "B"]   # opus: from the bottom, and never the claimed A
    assert G.next_name() is None
