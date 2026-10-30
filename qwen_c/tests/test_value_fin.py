"""WO_Q6: the financial route (banks, insurers, mortgage REITs; O3 retained equity). The production path against simulated truth
(PREREG_q6_fin.json v1.0), and checks(route="financial") on canned valuation_inputs_financial outputs: every check has a pass case and
a fail case on ROE or book growth."""
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from qwen_c import tasks
from qwen_c.value import checks, coe, desk, facts, forecast_fin, inputs, run, task

HERE = Path(__file__).resolve().parent
ENDS = ["2020-12-31", "2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
R = 0.10
M = 1e6


# ------------------------------------------------------------------ the production path against truth
@pytest.mark.parametrize("name", ["F_insurer", "F2_bank", "F3_grower"])
def test_production_path_reproduces_truth(name):
    # PREREG_q6_fin v1.1: an ideal analyst reproduces the simulator within 0.01% (CROSS_CHECK_Q3 3: F3_grower has g4 != g5, ROE_5 != ROE_T)
    c = json.loads((HERE / "fixtures_value" / "fin_truth.json").read_text(encoding="utf-8"))[name]
    b = dict(inputs.base_financial(c["facts"]), stub_days=0)
    bar = forecast_fin.record_bar(b["record"]["roe"])
    inp = forecast_fin.assemble(c["scenario"], b, bar, r=c["r"])
    v = forecast_fin.value(inp)
    assert abs(v["value_per_share"] / c["truth"] - 1) <= 0.0001
    checks._recompute_fin(inp, v)                                         # V1 over every flow and the equity value (finding 8)


def test_rollforward_and_the_book_path():
    c = json.loads((HERE / "fixtures_value" / "fin_truth.json").read_text(encoding="utf-8"))["F2_bank"]
    b = dict(inputs.base_financial(c["facts"]), stub_days=0)
    bar = forecast_fin.record_bar(b["record"]["roe"])
    inp = forecast_fin.assemble(c["scenario"], b, bar, r=c["r"])
    assert inp["revenue"][1] == b["R1"] and inp["revenue"][2] == pytest.approx(b["R1"] * 1.06) and inp["driver"] == "book"
    v0 = forecast_fin.value(inp)
    v1 = forecast_fin.value(dict(inp, stub_days=365))
    assert v1["value_per_share"] == pytest.approx(v0["value_per_share"] * (1 + c["r"]))
    with pytest.raises(desk.DeskRefusal):
        forecast_fin.value(dict(inp, stub_days=900))


# ------------------------------------------------------------------ checks on a canned bank
def series(vals):
    return {"values": [{"end": e, "value": v * M, "tag": "T", "form": "10-K", "accn": f"0001-{e[2:4]}-000010"}
                       for e, v in zip(ENDS[-len(vals):], vals)]}


def bank_facts():
    return {"equity": series([100, 105, 110, 116, 122, 128]), "net_income": series([10, 10.5, 11.5, 12.0, 12.8]),
            "diluted_shares": series([10, 10, 10, 10, 10, 10]), "_absent": {}, "_stale": {}}


ITEMS = {
    "A1": ("annual_section", "2024-12-31", "Our loan contracts run for ten years and renew at expiry. We expect deposits and loans to grow "
                                           "with the economy. Inflation is expected to average 3% a year."),
    "A2": ("annual_section", "2024-12-31", "Our return on equity in commercial lending was 14.0% for the year."),
    "Q2": ("quarterly_section", "2025-09-30", "Return on equity in commercial lending was 14.2% in the quarter."),
    "R1": ("release", "2026-02-01", "Adjusted return on tangible equity was 12.0% for the year."),
}
Y21, Y24, Y25 = "Y2021-12-31", "Y2024-12-31", "Y2025-12-31"
ROE21, ROE25 = "return on opening equity 10.0%", "return on opening equity 10.5%"


@pytest.fixture(scope="module")
def ctx():
    f = bank_facts()
    b = dict(inputs.base_financial(f), stub_days=0, g_anchor=0.04)
    bar = forecast_fin.record_bar(b["record"]["roe"])
    items = {i["fact_id"]: i for i in forecast_fin.record_items(f, b)}
    items.update({k: {"fact_id": k, "kind": kd, "period": p, "text": t} for k, (kd, p, t) in ITEMS.items()})
    return b, bar, items


def reason(inp, claim, ids, quotes, numbers=()):
    return {"input": inp, "claim": claim, "fact_ids": list(ids), "quotes": list(quotes), "numbers": list(numbers), "confidence_basis": "filed"}


def clean():
    return {"task": "valuation_inputs_financial",
            "base": {"book_growth": [0.05, 0.05], "roe": [0.104, 0.104],
                     "normalized": {"year": 3, "baseline": "median", "delta_pts": 0.0, "book_growth": 0.05},
                     "transition": "linear", "transition_year": None, "fade_years": 10, "long_run_roe": 0.103, "terminal_g": 0.03},
            "bear": {"roe": [0.10, 0.10]}, "bull": {"roe": [0.1045, 0.1045]},
            "prob": {"bear": 0.25, "base": 0.5, "bull": 0.25},
            "reasons": [
                reason("base.book_growth", "Book equity grew from $122.0 million to $128.0 million in the last filed year.", [Y24, Y25],
                       ["book equity at year end $122.0 million", "book equity at year end $128.0 million"], ["$122.0 million", "$128.0 million"]),
                reason("base.roe", "The filed return on opening equity was 10.5% in the last year.", [Y25], [ROE25], ["10.5%"]),
                reason("base.normalized", "The return on opening equity moved from 10.0% to 10.5% over the filed years; it normalizes at the median.",
                       [Y21, Y25], [ROE21, ROE25], ["10.0%", "10.5%"]),
                reason("base.long_run_roe", "Over the filed years the return on opening equity stayed between 10.0% and 10.5%, a durable return.",
                       [Y21, Y25], [ROE21, ROE25], ["10.0%", "10.5%"]),
                reason("base.fade_years", "Loan contracts run for ten years, which supports a ten-year fade.", ["A1"],
                       ["Our loan contracts run for ten years"]),
                reason("base.terminal_g", "The company expects deposits and loans to grow with the economy.", ["A1"],
                       ["We expect deposits and loans to grow with the economy"]),
                reason("bear.roe", "In a weaker year the return could fall back to the 10.0% of the earliest filed year.", [Y21], [ROE21],
                       ["10.0%"]),
                reason("bull.roe", "The latest filed return on opening equity of 10.5% can hold.", [Y25], [ROE25], ["10.5%"]),
            ]}


def run_check(out, ctx):
    b, bar, items = ctx
    return checks.check(out, items, "TB", set(), b, bar, R, ENDS, route="financial")


def test_clean_reply_is_ok_and_valued(ctx):
    res = run_check(clean(), ctx)
    assert res["status"] == "ok", res["unsupported"]
    assert res["route"] == "financial" and "capital_constraint_not_modeled" in res["stamps"]
    assert res["values"]["bear"] <= res["values"]["base"] <= res["values"]["bull"]


def test_shape_refuses_missing_and_operating_fields(ctx):
    out = clean()
    del out["base"]["roe"]
    assert run_check(out, ctx)["status"] == "invalid"
    out = clean()
    out["bull"] = {"op_margin": [0.2, 0.2]}
    assert run_check(out, ctx)["status"] == "invalid"


def test_the_example_shape_in_the_financial_prompt_is_itself_valid():
    example = json.loads(re.search(r"```json\n(.*)\n```", task.INSTRUCTION_FIN, re.S).group(1))
    assert checks.shape_fin(example, 0.1027) == []


def _with(out, inp, new):
    out["reasons"] = [x for x in out["reasons"] if x["input"] != inp] + new
    return out


def test_V3_roe_outside_the_record_needs_two_fiscal_years(ctx):
    out = clean()
    out["base"]["long_run_roe"] = 0.14
    res = run_check(out, ctx)
    assert any("V3" in w for w in res["unsupported"].get("base.long_run_roe", []))
    out = _with(clean(), "base.long_run_roe", [reason(
        "base.long_run_roe", "Commercial lending earned a return on equity of 14.0% for the year and 14.2% in the quarter.",
        ["A2", "Q2"], ["return on equity in commercial lending was 14.0%", "Return on equity in commercial lending was 14.2%"],
        ["14.0%", "14.2%"])])
    out["base"]["long_run_roe"] = 0.14
    assert "base.long_run_roe" not in run_check(out, ctx)["unsupported"]


def test_V4_an_roe_reason_needs_a_filed_basis(ctx):
    out = _with(clean(), "base.roe", [reason("base.roe", "Adjusted return on tangible equity was 12.0% for the year.", ["R1"],
                                             ["Adjusted return on tangible equity was 12.0%"], ["12.0%"])])
    assert any("V4" in w for w in run_check(out, ctx)["unsupported"].get("base.roe", []))


def test_V7_shrinking_book_needs_a_return_to_growth_reason(ctx):
    def shrinking(claim, quote):
        out = _with(clean(), "base.terminal_g", [reason("base.terminal_g", claim, ["A1"], [quote])])
        out["base"]["book_growth"] = [-0.02, -0.03]
        out["base"]["normalized"]["book_growth"] = -0.01
        return run_check(out, ctx)
    bad = shrinking("Inflation is expected to average 3% a year.", "Inflation is expected to average 3% a year")
    assert any("V7" in w for w in bad["unsupported"].get("base.terminal_g", []))
    good = shrinking("The company expects deposits and loans to grow with the economy.",
                     "We expect deposits and loans to grow with the economy")
    assert not any("V7" in w for w in good["unsupported"].get("base.terminal_g", []))


def test_V9_a_bull_roe_below_base_needs_its_own_supported_reason(ctx):
    out = clean()
    out["bull"] = {"roe": [0.10, 0.10]}
    out["reasons"] = [x for x in out["reasons"] if x["input"] != "bull.roe"]
    assert any("V9" in w for w in run_check(out, ctx)["unsupported"].get("bull.roe", []))
    out["reasons"].append(reason("bull.roe", "Even in the bull case the return may be the 10.0% of the earliest filed year.", [Y21], [ROE21],
                                 ["10.0%"]))
    assert not any("V9" in w for w in run_check(out, ctx)["unsupported"].get("bull.roe", []))


def test_V10_a_reason_contradicting_its_roe(ctx):
    out = _with(clean(), "base.normalized", [reason(
        "base.normalized", "The return on opening equity moved from 10.0% to 10.5%; it normalizes above the median.", [Y21, Y25],
        [ROE21, ROE25], ["10.0%", "10.5%"])])
    assert any("V10" in w for w in run_check(out, ctx)["unsupported"].get("base.normalized", []))


def test_long_run_roe_must_exceed_terminal_growth(ctx):
    out = clean()
    out["base"]["long_run_roe"] = 0.025
    assert any("not above terminal_g" in w for w in run_check(out, ctx)["unsupported"].get("base.long_run_roe", []))


def test_V3g_book_growth_above_the_record_needs_two_fiscal_years(ctx):
    out = clean()
    out["base"]["book_growth"] = [0.09, 0.09]
    assert any("V3g" in w for w in run_check(out, ctx)["unsupported"].get("base.book_growth", []))


def test_the_operating_keyword_rule_does_not_refuse_a_financial_reason(ctx):
    # "normalizes" with no operating word (margin, cost): the financial classes decide
    res = run_check(clean(), ctx)
    assert "base.normalized" not in res["unsupported"]


# ------------------------------------------------------------------ the runner routes the financial family
def test_prepare_routes_a_financial_to_the_book_equity_base(monkeypatch):
    monkeypatch.setattr(facts, "build", lambda *a, **k: bank_facts())
    prov = {"rf": 0.05, "g_anchor": 0.04, "loading_adjusted": 1.0, "closure_erp": 0.05}
    monkeypatch.setattr(coe, "cost_of_equity", lambda *a, **k: (0.10, prov))
    f, b, bar, record, r, p, fy_ends = run.prepare({"decision_time_utc": "2026-03-01T13:00:00Z"}, "1", "Banks", 1.0, online=False,
                                                   family="financial")
    assert b["route"] == "financial" and b["stub_days"] == 60 and b["g_anchor"] == 0.04
    assert record[-1]["fact_id"] == "Y2025-12-31" and "return on opening equity 10.5%" in record[-1]["text"]
    msg = task.messages({"evidence": []}, record, b, bar, r, p)[1]["content"]
    assert "TASK valuation_inputs_financial" in msg and "Filed return-on-equity record" in msg


def test_an_unbuilt_family_is_still_refused_by_name():
    with pytest.raises(desk.DeskRefusal) as e:
        run.prepare({"decision_time_utc": "2026-10-30T13:00:00Z"}, "1", "REITs", 1.0, online=False, family="family_not_built")
    assert e.value.code == "family_not_routed"


PINNED_FIN = "8ba2b4c0966ba877d4eb2a97716b26da9e0104de3661433b0d0850438a69976b"   # m3q.prompt.fin.v4


def test_the_financial_prompt_is_pinned_and_the_operating_one_untouched():
    b = {"route": "financial", "fy0": "2025-12-31", "R1": 128e6, "e0": 12.8e6, "record": {"book_growth_max": 0.0545, "book_growth_min": 0.0476}}
    bar = {"min": 0.10, "p25": 0.10, "median": 0.1034, "p75": 0.1045, "max": 0.1049, "last": 0.1049}
    prov = {"rf": 0.0505, "g_anchor": 0.0375, "loading_adjusted": 1.25, "closure_erp": 0.0417}
    pk = {"ticker": "T", "decision_time_utc": "2026-10-30T13:00:00Z", "cik": "1", "evidence": []}
    msg = task.user_message(pk, [], copy.deepcopy(b), bar, 0.1027, prov)
    h = hashlib.sha256("\n".join([task.VALUATION_PROMPT_FIN_VERSION, tasks.SYSTEM, msg]).encode("utf-8")).hexdigest()
    assert h == PINNED_FIN, f"the financial prompt changed: bump VALUATION_PROMPT_FIN_VERSION and re-pin ({h})"


def test_memo_renders_a_financial_result(ctx):
    from qwen_c.value import memo
    b, bar, items = ctx
    out = clean()
    res = run_check(out, ctx)
    result = {"ticker": "TB", "T": "2026-03-01T13:00:00Z", "status": res["status"], "inputs": out, "checks": res,
              "values": res["values"], "cost_of_equity": R, "base": b}
    text = memo.render(result, checks.reasons_by_input(out, items, "TB", set(), ENDS, route="financial"))
    assert "Return on equity, years 1-2 | 10.4%, 10.4%" in text and "Tax" not in text
