"""The Gemini list worker's verdict label and its refresh rule (gemini_ondemand.verdict / last_analysed)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_ondemand as G  # noqa: E402


PROB = {"bear": 0.25, "base": 0.5, "bull": 0.25}


def _row(price, bear=18.0, base=20.0, bull=22.0, valued=True, seeds=(20.0, 20.0)):
    return {"valued": valued, "value_bear": bear, "value_base": base, "value_bull": bull, "price_at_publish": price,
            "no_value_reason": "why", "value_per_filed_share": {"base": base},
            "seed_base": {str(1000 + 2000 * i): v for i, v in enumerate(seeds)}}


def test_alpha_is_the_claude_arms_formula():
    # value = price: the expected return is the required return, alpha 0; value 1.331 x price over 3 years at ke 0: 10 points
    assert abs(G.alpha_pts(10.0, 10.0, 0.09)) < 1e-9
    assert abs(G.alpha_pts(13.31, 10.0, 0.0) - 10.0) < 1e-9
    assert G.alpha_pts(0.0, 10.0, 0.09) == -100.0


def test_verdict_bands():
    ke = 0.10                                          # expected value 20 in every row below
    assert G.verdict(_row(20.5), ke, PROB)[0] == "AVOID"            # value under the price: alpha below zero
    assert G.verdict(_row(21.0), ke, PROB)[0] == "AVOID"
    assert G.verdict(_row(19.0), ke, PROB)[0] == "WATCH"            # above zero, under 4 points
    assert G.verdict(_row(17.0), ke, PROB)[0] == "BUY"              # (20/17)^(1/3) x 1.1 - 1.1 = 6.1 points
    v, why, a = G.verdict(_row(17.0, seeds=(20.0, 17.5)), ke, PROB)  # one run alone does not reach 4 points
    assert v == "WATCH" and "two runs" in why and a > 4


def test_verdict_no_call():
    assert G.verdict(_row(5.0, valued=False), 0.1, PROB)[:2] == ("NO_CALL", "why")
    assert G.verdict(_row(None), 0.1, PROB)[0] == "NO_CALL"
    assert G.verdict(_row(0.0), 0.1, PROB)[0] == "NO_CALL"          # a price of zero cannot be compared with
    assert G.verdict(_row(17.0), None, PROB)[0] == "NO_CALL"        # no required return on record
    assert G.verdict(_row(17.0), 0.1, None)[0] == "NO_CALL"


def test_refusal_is_retried_next_day(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ONDEMAND", tmp_path)
    iso = lambda h: (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat().replace("+00:00", "Z")  # noqa: E731
    for t, h, an in (("DONE", 25, "complete"), ("REFUSED", 25, "not run"), ("FRESHREF", 2, "not run")):
        (tmp_path / f"{t}.json").write_text(json.dumps({"ticker": t, "date": iso(h), "analysis": an}), encoding="utf-8")
    monkeypatch.setattr(G, "CLAIMS", tmp_path / "claims")
    monkeypatch.setattr(G, "queue_file", lambda: tmp_path / "no_queue.jsonl")
    monkeypatch.setattr(G.Q, "list_names", lambda: ["DONE", "FRESHREF", "REFUSED", "NEW"])
    assert G.next_name() == ("REFUSED", "list", False)


def test_two_arms_never_take_the_same_name(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ONDEMAND", tmp_path)
    monkeypatch.setattr(G, "CLAIMS", tmp_path / "claims")
    monkeypatch.setattr(G, "queue_file", lambda: tmp_path / "no_queue.jsonl")
    monkeypatch.setattr(G.Q, "list_names", lambda: ["A", "B", "C"])
    monkeypatch.setattr(G, "ARM", "gemini")
    assert G.next_name()[0] == "A"                      # gemini: from the top
    monkeypatch.setattr(G, "ARM", "opus")
    assert [G.next_name()[0], G.next_name()[0]] == ["C", "B"]   # opus: from the bottom, and never the claimed A
    assert G.next_name() is None


def test_a_request_comes_before_the_list_and_is_taken_once(tmp_path, monkeypatch):
    q = tmp_path / "queue.jsonl"
    q.write_text(json.dumps({"ticker": "ASKED", "source": "web", "requested_at": "2026-11-16T00:00:00Z"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(G, "ONDEMAND", tmp_path)
    monkeypatch.setattr(G, "CLAIMS", tmp_path / "claims")
    monkeypatch.setattr(G, "queue_file", lambda: q)
    monkeypatch.setattr(G.Q, "list_names", lambda: ["A"])
    assert G.next_name() == ("ASKED", "web", True)      # even though it is not on the list and has no age
    assert G.next_name() == ("A", "list", False)        # the other arm does not take the same request


def test_a_ticker_that_is_a_windows_device_name_gets_a_safe_file_name():
    assert G.site_stem("CON") == "CON_" and G.site_stem("nul") == "nul_" and G.site_stem("LPT1") == "LPT1_"
    assert G.site_stem("CONE") == "CONE" and G.site_stem("A") == "A"
