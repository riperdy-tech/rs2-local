"""WO_Q5b: qwen_c/value/run.py end to end with the model call faked (no GPU, no network): one clean reply; a failing reply repaired
on the second turn; a refusal before any call; everything kept under the run directory."""
import json

import pytest

from qwen_c import runner
from qwen_c.tests import test_value_checks as C
from qwen_c.value import desk, forecast, inputs, run


@pytest.fixture
def setup(tmp_path, monkeypatch):
    f = C.facts()
    b = dict(inputs.base(f, market_cap=180e6, bill_rate=0.04), stub_days=0)
    bar = forecast.record_bar(b["record"]["op_margin"])
    record = forecast.record_items(f)
    prov = {"rf": 0.0505, "g_anchor": 0.0375, "loading_adjusted": 1.25, "closure_erp": 0.0417}
    monkeypatch.setattr(run, "prepare", lambda *a, **k: (f, b, bar, record, C.R, prov, C.ENDS))
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


def test_clean_reply_is_ok_in_one_call(setup, monkeypatch):
    p, out = setup
    seen = []
    monkeypatch.setattr(runner, "call", fake([C.clean()], seen))
    res = run.value(p, "1", "Technology", 180e6, family="operating", out_root=out, url="http://x")
    assert res["status"] == "ok" and len(seen) == 1 and res["authority"] == "diagnostic_only"
    assert res["values"]["bear"] <= res["values"]["base"] <= res["values"]["bull"]
    assert seen[0]["messages"][0]["content"] is runner.tasks.SYSTEM
    d = next(out.iterdir())
    assert json.loads((d / "result.json").read_text(encoding="utf-8"))["status"] == "ok" and (d / "raw" / "attempt_1.json").exists()


def test_failing_reply_gets_one_repair_turn_with_the_failures(setup, monkeypatch):
    p, out = setup
    bad = C.without(C.clean(), "base.op_margin")
    bad["reasons"].append(C.reason("base.op_margin", "Adjusted EBITDA margin was 25.0% for the year.", ["R1"],
                                   ["Adjusted EBITDA margin was 25.0%"], ["25.0%"]))
    seen = []
    monkeypatch.setattr(runner, "call", fake([bad, C.clean()], seen))
    res = run.value(p, "1", "Technology", 180e6, family="operating", out_root=out, url="http://x")
    assert res["status"] == "ok" and [a["status"] for a in res["attempts"]] == ["valuation_incomplete", "ok"]
    repair = seen[1]["messages"][-1]["content"]
    assert "V4" in repair and seen[1]["options"]["seed"] == runner.SEED_BASE + run.REPAIR_SEED_OFFSET


def test_still_failing_after_repair_is_incomplete_and_still_valued(setup, monkeypatch):
    p, out = setup
    bad = C.clean()
    bad["base"]["margin_source"] = "investment_after_year5"
    monkeypatch.setattr(runner, "call", fake([bad, bad], []))
    res = run.value(p, "1", "Technology", 180e6, family="operating", out_root=out, url="http://x")
    assert res["status"] == "valuation_incomplete" and "base" in res["values"] and len(res["attempts"]) == 2


def test_refusal_before_any_call_is_a_no_call(setup, monkeypatch):
    p, out = setup
    def refuse(*a, **k):
        raise desk.DeskRefusal("tax_unavailable", "no rate")
    monkeypatch.setattr(run, "prepare", refuse)
    seen = []
    monkeypatch.setattr(runner, "call", fake([], seen))
    res = run.value(p, "1", "Technology", 180e6, family="operating", out_root=out, url="http://x")
    assert res["status"] == "no_call" and res["reason"] == "tax_unavailable" and not seen


def test_financial_family_is_refused_by_name():
    with pytest.raises(desk.DeskRefusal) as e:
        run.prepare({"decision_time_utc": "2026-10-30T13:00:00Z"}, "1", "Banks", 1.0, online=False, family="financial")
    assert e.value.code == "family_not_routed"


def test_memo_prints_code_numbers_and_only_supported_reasons(setup, monkeypatch):
    from qwen_c.value import checks, memo
    p, out = setup
    bad = C.clean()
    bad["reasons"].append(C.reason("base.rev_growth", "Revenue will double.", ["G1"], ["revenue will double"], []))
    monkeypatch.setattr(runner, "call", fake([bad], []))
    res = run.value(p, "1", "Technology", 180e6, family="operating", out_root=out, url="http://x")
    pk = json.loads(p.read_text(encoding="utf-8"))
    items = {e["fact_id"]: e for e in pk["evidence"]}
    items.update({i["fact_id"]: i for i in forecast.record_items(C.facts())})
    text = memo.render(res, checks.reasons_by_input(res["inputs"], items, "TEST", set(), C.ENDS))
    assert "diagnostic only" in text and f"{res['values']['base']:,.2f}" in text
    assert "Revenue will double" not in text and "The company expects revenue growth of 5% in 2026." in text


def test_engine_defect_is_recorded_not_raised(setup, monkeypatch):
    from qwen_c.value import checks
    p, out = setup
    monkeypatch.setattr(runner, "call", fake([C.clean()], []))
    def boom(*a, **k):
        raise AssertionError("V1: injected")
    monkeypatch.setattr(checks, "check", boom)
    res = run.value(p, "1", "Technology", 180e6, family="operating", out_root=out, url="http://x")
    assert res["status"] == "engine_defect" and (next(out.iterdir()) / "result.json").exists()
