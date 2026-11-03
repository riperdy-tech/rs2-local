"""WO_Q5b / F_SPEC_valuation_menu §4-§5 (F7): qwen_c/value/run.py end to end with the model call faked (no GPU, no network): a clean
reply; reply errors repaired on the second turn; reply errors that remain; a revert that is not sent back; a refusal before any call;
memo.md written beside result.json."""
import copy
import json

import pytest

from qwen_c import runner
from qwen_c.tests import test_value_checks as C
from qwen_c.value import desk, forecast, inputs, run


@pytest.fixture
def setup(tmp_path, monkeypatch):
    f = C.facts()
    b = dict(inputs.base(f, market_cap=180e6, bill_rate=0.04), stub_days=0, g_anchor=0.03)
    bar = forecast.record_bar(b["record"]["op_margin"])
    record = forecast.record_items(f)
    monkeypatch.setattr(run, "prepare", lambda *a, **k: (f, b, bar, record, C.R, C.PROV, C.ENDS))
    pk = {"contract": runner.PACKET_CONTRACT, "ticker": "TEST", "decision_time_utc": "2026-10-30T13:00:00Z",
          "evidence": [{"fact_id": k, "kind": kd, "period": per, "text": t} for k, (kd, per, t) in C.ITEMS.items()]}
    p = tmp_path / "packet.json"
    p.write_text(json.dumps(pk), encoding="utf-8")
    return p, tmp_path / "runs"


def fake(replies, seen):
    def call(body, url, timeout):
        seen.append(body)
        obj = replies[len(seen) - 1]
        return "reply", {"message": {"content": "```json\n" + json.dumps(obj) + "\n```"}, "prompt_eval_count": 1000, "eval_count": 500,
                         "done": True}, None
    return call


def value(p, out):
    return run.value(p, "1", "Technology", 180e6, family="operating", out_root=out, url="http://x")


def guided():
    g = {"evidence": "G1.s1", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}
    return C.depart(C.clean(), "rev_growth.y1", "guidance", "guidance", ["G1.s1"], g)


def test_clean_reply_is_ok_in_one_call_and_writes_the_memo(setup, monkeypatch):
    p, out = setup
    seen = []
    monkeypatch.setattr(runner, "call", fake([guided()], seen))
    res = value(p, out)
    assert res["status"] == "ok" and len(seen) == 1 and res["authority"] == "diagnostic_only"
    assert res["values"]["bear"] <= res["values"]["base"] <= res["values"]["bull"]
    assert seen[0]["messages"][0]["content"] is runner.tasks.SYSTEM and "<1> The company expects" in seen[0]["messages"][1]["content"]
    assert {"sentences", "menu", "memo", "prompt", "checks", "forecast", "inputs"} <= set(res["versions"])
    d = next(out.iterdir())
    assert json.loads((d / "result.json").read_text(encoding="utf-8"))["status"] == "ok" and (d / "raw" / "attempt_1.json").exists()
    memo = (d / "memo.md").read_text(encoding="utf-8")
    assert "diagnostic only" in memo and f"{res['values']['base']:,.2f}" in memo
    assert "- **rev_growth.y1**: guidance, 0.0500 (record-neutral 0.0300), up; driver guidance" in memo
    assert "  - [G1.s1] The company expects revenue growth of 5% in 2026." in memo
    assert memo.rstrip().endswith("- the order book is not disclosed")                     # the unknowns, unedited, last


def test_reply_errors_get_one_repair_turn_listing_them_by_key(setup, monkeypatch):
    p, out = setup
    bad = C.clean()
    bad["base"]["op_margin"]["y1"] = "last"                                                  # a departure without its entry
    seen = []
    monkeypatch.setattr(runner, "call", fake([bad, guided()], seen))
    res = value(p, out)
    assert res["status"] == "ok" and [a["status"] for a in res["attempts"]] == ["reply_invalid", "ok"]
    repair = seen[1]["messages"][-1]["content"]
    assert "- op_margin.y1: departs (0.1600 against the neutral 0.1556) and needs a departures entry" in repair
    assert seen[1]["options"]["seed"] == runner.SEED_BASE + run.REPAIR_SEED_OFFSET


def test_reply_errors_after_the_repair_are_reply_invalid_with_no_value(setup, monkeypatch):
    p, out = setup
    bad = C.clean()
    bad["uncertain"] = []
    monkeypatch.setattr(runner, "call", fake([bad, bad], []))
    res = value(p, out)
    assert res["status"] == "reply_invalid" and not res["values"] and len(res["attempts"]) == 2
    assert "uncertain" in (next(out.iterdir()) / "memo.md").read_text(encoding="utf-8")


def test_a_revert_is_valued_and_never_sent_back(setup, monkeypatch):
    p, out = setup
    seen = []
    monkeypatch.setattr(runner, "call", fake([C.depart(C.clean(), "op_margin.y1", "last", "pricing", ["R1.s1"])], seen))
    res = value(p, out)
    assert res["status"] == "ok_with_reverts" and len(seen) == 1 and res["checks"]["reverts"] == ["departure_reverted: op_margin.y1 V4"]
    assert "departure_reverted: op_margin.y1 V4" in (next(out.iterdir()) / "memo.md").read_text(encoding="utf-8")


def test_refusal_before_any_call_is_a_no_call_with_its_memo(setup, monkeypatch):
    p, out = setup
    def refuse(*a, **k):
        raise desk.DeskRefusal("tax_unavailable", "no rate")
    monkeypatch.setattr(run, "prepare", refuse)
    seen = []
    monkeypatch.setattr(runner, "call", fake([], seen))
    res = value(p, out)
    assert res["status"] == "no_call" and res["reason"] == "tax_unavailable" and not seen
    assert "tax_unavailable: tax_unavailable: no rate" in (next(out.iterdir()) / "memo.md").read_text(encoding="utf-8")


def test_engine_defect_is_recorded_not_raised(setup, monkeypatch):
    from qwen_c.value import checks
    p, out = setup
    monkeypatch.setattr(runner, "call", fake([C.clean()], []))
    def boom(*a, **k):
        raise AssertionError("V1: injected")
    monkeypatch.setattr(checks, "check", boom)
    res = value(p, out)
    assert res["status"] == "engine_defect" and (next(out.iterdir()) / "result.json").exists()
