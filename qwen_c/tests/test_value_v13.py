"""SPEC_prompt_v13 / checks v18 / menu v7: a guidance entry's period, and the annotation-only `found` list."""
import copy

import pytest

from qwen_c.value import checks, menu, task
from qwen_c.tests import test_value_checks as OP
from qwen_c.tests.test_value_checks import clean, ctx, depart, run   # noqa: F401  (ctx is a fixture)

G1 = {"evidence": "G1.s1", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}   # 5% in 2026
G2 = {"evidence": "G2.s1", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}   # 10% in 2026


def guided(entry):
    return depart(clean(), "rev_growth.y1", "guidance", "guidance", [entry["evidence"]], dict(entry))


def test_versions_and_the_financial_text_is_unchanged():
    assert task.VALUATION_PROMPT_VERSION == "m3q.prompt.v13" and checks.CHECKS_VERSION == "m3q.checks.v18"
    assert menu.MENU_VERSION.startswith("m3q.menu.v7") or menu.MENU_VERSION == "m3q.menu.v7"
    assert "found" not in task.INSTRUCTION_FIN and "period" not in task.INSTRUCTION_FIN
    assert "found" in task.INSTRUCTION and "half or quarter" in task.INSTRUCTION


def test_a_missing_period_checks_exactly_as_v12(ctx):
    res = run(ctx, guided(G1))
    assert res["status"] == "ok" and res["numbers"]["rev_growth.y1"] == pytest.approx(0.05)
    assert res["found"] == [] and res["found_chosen"] is None


def test_period_year_reads_and_half_or_quarter_reverts(ctx):
    year = run(ctx, guided(dict(G1, period="year")))
    assert year["status"] == "ok" and year["numbers"]["rev_growth.y1"] == pytest.approx(0.05)
    for p in ("half", "quarter"):
        res = run(ctx, guided(dict(G1, period=p)))
        assert res["status"] == "ok_with_reverts", res.get("errors")
        assert f"guidance_unreadable: rev_growth.y1 the sentence guides a {p}, not a fiscal year" in res["reverts"]
        assert res["options"]["rev_growth.y1"] != "guidance"
        assert res["numbers"]["rev_growth.y1"] == run(ctx, clean())["numbers"]["rev_growth.y1"]


def test_an_invalid_period_is_a_reply_error(ctx):
    res = run(ctx, guided(dict(G1, period="month")))
    assert res["status"] == "reply_invalid" and "guidance.rev_growth.y1" in res["errors"]


def test_found_is_read_like_the_chosen_guidance_and_names_the_chosen_sentence(ctx):
    out = guided(dict(G1, period="year"))
    out["found"] = [dict(G2, period="year"), dict(G1, period="year"), dict(G1, period="quarter")]
    res = run(ctx, out)
    assert res["status"] == "ok"
    nums = [(r["index"], r["number"], r["why"]) for r in res["found"]]
    assert nums[0][:2] == (0, pytest.approx(0.10)) and nums[1][:2] == (1, pytest.approx(0.05))
    assert nums[2] == (2, None, "the sentence guides a quarter, not a fiscal year")
    assert res["found_chosen"] == 1 and res["found"][0]["period_of_evidence"] == "2026-02-01"


def test_found_on_a_name_that_keeps_the_pace_is_listed_and_moves_nothing(ctx):
    plain = run(ctx, clean())
    out = clean()
    out["found"] = [dict(G2, period="year")]
    res = run(ctx, out)
    assert res["found"][0]["number"] == pytest.approx(0.10) and res["found_chosen"] is None
    assert "found_missing_chosen" not in res["annotations"]
    assert res["numbers"] == plain["numbers"] and res["values"] == plain["values"] and res["status"] == plain["status"]


def test_a_malformed_found_never_fails_the_reply_nor_moves_a_number(ctx):
    plain = run(ctx, guided(G1))
    for bad in ("G1.s1", [{"evidence": "nope", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}],
                [{"evidence": "G1.s1", "metric": "op_margin", "sign": "as_printed", "ordinal": 1}], [3], [dict(G1, period="month")]):
        out = guided(G1)
        out["found"] = copy.deepcopy(bad)
        res = run(ctx, out)
        assert res["status"] == plain["status"] and res["numbers"] == plain["numbers"] and res["values"] == plain["values"]
        assert any(a.startswith("found_malformed") for a in res["annotations"]), bad
        assert res["found"] == []


def test_a_chosen_sentence_missing_from_found_is_annotated(ctx):
    out = guided(G1)
    out["found"] = [dict(G2, period="year")]
    assert "found_missing_chosen" in run(ctx, out)["annotations"]


def test_the_period_rule_applies_to_every_guided_key(ctx):
    c2 = {"evidence": "C2.s1", "metric": "capex_level", "sign": "as_printed", "ordinal": 1, "period": "quarter"}
    out = depart(clean(), "capex", "guidance", "guidance", ["C2.s1"], c2)
    res = run(ctx, out)
    assert "guidance_unreadable: capex the sentence guides a quarter, not a fiscal year" in res["reverts"]


def test_the_financial_route_has_no_found(ctx):
    from qwen_c.tests import test_value_fin as FIN
    b, bar, ids = FIN.ctx_of()
    out = FIN.clean()
    out["found"] = [dict(G1, period="year")]
    res = checks.check(out, ids, b, bar, OP.R, OP.ENDS, route="financial")
    assert "found" not in res and not any(a.startswith("found_") for a in res["annotations"])
