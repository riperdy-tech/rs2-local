"""WO_NC5: the cloud read says why a thin profit record is thin, before the name is valued (why_losses.py, gemini_ondemand.analyze). Synthetic
data only; the model call is stubbed (runner.call)."""
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_ondemand as G  # noqa: E402
import qwen_ondemand as Q  # noqa: E402
import test_tax_range_report as TR  # noqa: E402
import qwen_site  # noqa: E402
import why_losses as W  # noqa: E402
from qwen_c import runner  # noqa: E402
from qwen_c.tests import test_value_tax_statutory as TS  # noqa: E402
from qwen_c.value import desk  # noqa: E402

TEXT = "Loss from discontinued operations was 120 million, after the segment was sold during the year."
REAL_REPORT = Q.report
PK = {"ticker": "TEST", "cik": "1", "decision_time_utc": "2026-11-18T00:00:00Z",
      "evidence": [{"fact_id": "F1", "kind": "statement", "title": "t", "form": "10-K", "period": "2025", "effective_at": "2026-01-01T00:00:00Z",
                    "source": None, "text": TEXT}]}
F = {"pretax_income": {"values": [{"end": "2024-12-31", "value": -5.0e6}, {"end": "2025-12-31", "value": -2.0e6}]}}


def answer(cause="divested_business", quote=TEXT[:46], i="F1"):
    return json.dumps({"cause": cause, "explanation": "The segment was sold.", "quotes": [{"id": i, "quote": quote}]})


def stub(monkeypatch, replies):
    """runner.call returns the replies in order (a str is a reply, a tuple is (kind, detail)); the messages sent are collected."""
    sent, it = [], iter(replies)

    def call(body, url, timeout):
        sent.append(body["messages"])
        r = next(it)
        if isinstance(r, tuple):
            return r[0], None, r[1]
        return "reply", {"message": {"role": "assistant", "content": r}, "done": True}, None
    monkeypatch.setattr(runner, "call", call)
    return sent


@pytest.mark.parametrize("cause,reason", [("divested_business", None), ("one_off_charges", None), ("financing_burden", None),
                                          ("operating_losses", "loss_record_operating"), ("cannot_tell", "loss_record_unexplained")])
def test_each_menu_choice_and_its_outcome(tmp_path, monkeypatch, cause, reason):
    sent = stub(monkeypatch, [answer(cause)])
    rec, why = W.ask(PK, F, tmp_path / "raw")
    assert why == reason and rec["cause"] == cause and rec["label"] == W.MENU[cause][0] and rec["version"] == W.WHY_LOSSES_VERSION
    assert rec["quotes"] == [{"id": "F1", "quote": TEXT[:46]}] and rec["explanation"] == "The segment was sold." and len(sent) == 1
    assert json.loads((tmp_path / "raw" / "attempt_1.json").read_text(encoding="utf-8"))["messages"] == sent[0]      # the raw prompt and reply are kept


def test_the_prompt_carries_the_evidence_the_pretax_years_and_the_three_rules(tmp_path, monkeypatch):
    sent = stub(monkeypatch, [answer()])
    W.ask(PK, F, tmp_path)
    user = sent[0][1]["content"]
    assert TEXT in user and "fiscal year ended 2024-12-31: -5,000,000" in user and "fiscal year ended 2025-12-31: -2,000,000" in user
    assert "Answer only from the evidence given" in user and "Quote verbatim" in user and "choose cannot_tell" in user


def test_an_unverified_quote_is_retried_once_then_is_no_call(tmp_path, monkeypatch):
    sent = stub(monkeypatch, [answer(quote="The segment was sold for a profit."), answer(i="F9")])
    rec, why = W.ask(PK, F, tmp_path)
    assert why == "loss_record_unexplained" and rec["cause"] is None and rec["quotes"] == [] and "no quote was found" in rec["failure"]
    assert len(sent) == 2 and "was not accepted: no quote was found" in sent[1][1]["content"]


def test_an_unverified_quote_then_a_verified_one_is_accepted(tmp_path, monkeypatch):
    stub(monkeypatch, [answer(quote="invented words"), answer("one_off_charges")])
    rec, why = W.ask(PK, F, tmp_path)
    assert why is None and rec["cause"] == "one_off_charges"


def test_malformed_json_and_an_unknown_cause_are_retried(tmp_path, monkeypatch):
    sent = stub(monkeypatch, ["not json at all", answer("because")])
    rec, why = W.ask(PK, F, tmp_path)
    assert why == "loss_record_unexplained" and "is not one of" in rec["failure"] and "not valid JSON" in sent[1][1]["content"]
    stub(monkeypatch, ["[1, 2]", answer("financing_burden")])
    assert W.ask(PK, F, tmp_path)[1] is None


def test_a_call_that_gets_no_reply_is_not_an_answer(tmp_path, monkeypatch):
    stub(monkeypatch, [("infra_fatal", "down")])
    with pytest.raises(RuntimeError, match="infra_fatal: down"):
        W.ask(PK, F, tmp_path)


# ---- analyze ---------------------------------------------------------------------------------------------------------------------------

def arrange(tmp_path, monkeypatch, fallback, replies=()):
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps(PK), encoding="utf-8")
    monkeypatch.setattr(G, "SITE", tmp_path / "site")
    monkeypatch.setattr(G, "LOG", tmp_path / "site" / "worker.log")
    monkeypatch.setattr(G, "ONDEMAND", tmp_path / "ondemand")
    monkeypatch.setattr(G.vrun, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(Q, "verified_commit", lambda: ("c", "r"))
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({"packet": str(packet), "packet_sha256": "x"})))
    monkeypatch.setitem(sys.modules, "formation_value", types.SimpleNamespace(stocks_rows=lambda c: {"TEST": {"sector": "Technology", "marketCap": 1e8}},
                                                                              name_family=lambda cik, T: {"family": "operating"}))
    monkeypatch.setattr(G.runner, "run", lambda p, seed: {"status": "ok"})
    b = {"tax_fallback": {"rate": 0.21}} if fallback else {}
    monkeypatch.setattr(G.vrun, "prepare", lambda *a, **k: (F, b, None, None, None, None, None))
    seeds = []
    monkeypatch.setattr(G.vrun, "value", lambda *a, **k: seeds.append(k["seed"]) or {"status": "ok", "seed": k["seed"]})
    reports = []
    monkeypatch.setattr(Q, "report", lambda t, s, T, q1, n, results, commit: reports.append(results) or {"ticker": t, "valued": True, "date": T})
    sent = stub(monkeypatch, list(replies))
    return seeds, reports, sent


def written(tmp_path):
    return json.loads((tmp_path / "ondemand" / "TEST.json").read_text(encoding="utf-8"))


def test_without_a_tax_fallback_no_question_is_asked_and_the_report_is_as_before(tmp_path, monkeypatch):
    seeds, reports, sent = arrange(tmp_path, monkeypatch, False)
    assert G.analyze("TEST", "list") == "ok"
    assert sent == [] and seeds == [1000, 3000] and list(reports[0]) == ["1000", "3000"]
    assert "loss_record" not in written(tmp_path)


def test_the_question_is_asked_once_for_the_two_seeds_and_a_valued_name_carries_the_record(tmp_path, monkeypatch):
    seeds, reports, sent = arrange(tmp_path, monkeypatch, True, [answer("one_off_charges")])
    G.analyze("TEST", "list")
    rep = written(tmp_path)
    assert len(sent) == 1 and seeds == [1000, 3000] and list(reports[0]) == ["1000", "3000"]
    assert set(rep["loss_record"]) == {"cause", "label", "explanation", "quotes", "version"} and rep["loss_record"]["cause"] == "one_off_charges"


@pytest.mark.parametrize("replies,reason", [([answer("operating_losses")], "loss_record_operating"), ([answer("cannot_tell")], "loss_record_unexplained"),
                                            (["bad", "bad"], "loss_record_unexplained")])
def test_a_no_call_outcome_skips_the_seeds_and_the_real_report_is_not_valued_with_the_reason(tmp_path, monkeypatch, replies, reason):
    seeds, reports, sent = arrange(tmp_path, monkeypatch, True, replies)
    monkeypatch.setattr(Q, "report", REAL_REPORT)
    G.analyze("TEST", "list")
    rep = written(tmp_path)
    assert seeds == [] and rep["valued"] is False and rep["no_value_reason"] == qwen_site.NO_VALUE[reason]
    assert rep["loss_record"]["version"] == W.WHY_LOSSES_VERSION and (rep["loss_record"]["cause"] is None) == (replies[0] == "bad")


def test_the_qwen_report_of_a_name_with_the_fallback_has_no_loss_record(tmp_path, monkeypatch):
    n, results, _ = TR.arrange(tmp_path, monkeypatch, TS.fb_facts())
    assert "loss_record" not in TR.report(n, results)


def test_a_refusal_of_prepare_asks_nothing(tmp_path, monkeypatch):
    seeds, reports, sent = arrange(tmp_path, monkeypatch, True)
    def refuse(*a, **k):
        raise desk.DeskRefusal("history_short", "x")
    monkeypatch.setattr(G.vrun, "prepare", refuse)
    G.analyze("TEST", "list")
    assert sent == [] and seeds == [1000, 3000]
