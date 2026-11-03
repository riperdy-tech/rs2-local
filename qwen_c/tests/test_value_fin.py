"""WO_Q6 / F_SPEC_valuation_menu §2.3: the financial route (banks, insurers; O3 retained equity). The production path against simulated
truth (PREREG_q6_fin.json v1.0), and checks(route="financial") on canned prompt fin.v6 replies: every rule has a pass case and a fail
case on ROE or book growth."""
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from qwen_c import tasks
from qwen_c.value import checks, coe, desk, facts, forecast_fin, inputs, menu, run, task

HERE = Path(__file__).resolve().parent
ENDS = ["2020-12-31", "2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
R = 0.10
M = 1e6
PROV = {"rf": 0.05, "g_anchor": 0.04, "loading_adjusted": 1.0, "closure_erp": 0.05}


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
    "B1": ("release", "2026-02-01", "Book value per share is expected to grow 9% in 2026."),
    "B2": ("release", "2026-02-01", "Book value is expected to decline 2% in 2026 as capital is returned."),
    "B3": ("release", "2026-02-01", "Book value is expected to grow 12% in 2026 after the share offering."),
}
Y21, Y24, Y25 = "Y2021-12-31", "Y2024-12-31", "Y2025-12-31"


def ctx_of(r=R, **over):
    f = bank_facts()
    b = dict(inputs.base_financial(f), stub_days=0, g_anchor=0.04, **over)
    bar = forecast_fin.record_bar(b["record"]["roe"])
    pk = {"evidence": [{"fact_id": k, "kind": kd, "period": p, "text": t} for k, (kd, p, t) in ITEMS.items()]}
    return b, bar, task.evidence_ids(pk, forecast_fin.record_items(f, b), b, bar, r, PROV)


@pytest.fixture(scope="module")
def ctx():
    return ctx_of()


def clean():
    return {"task": "valuation_inputs_financial", "base": menu.neutral_base("financial"), "guidance": {}, "departures": [],
            "uncertain": ["normalized.roe", "long_run_roe"], "unknowns": ["capital ratios are not in the packet"]}


def depart(out, key, opt, driver=None, evidence=None, guidance=None):
    out["base"] = menu.set_option(out["base"], key, opt)
    if guidance:
        out["guidance"][key] = guidance
    if driver:
        out["departures"].append({"input": key, "driver": driver, "evidence": list(evidence)})
    return out


def grow(sid, sign="as_printed"):
    return {"evidence": sid, "metric": "book_growth", "sign": sign, "ordinal": 1}


def run_check(out, ctx, r=R, bar=None):
    b, bar0, ids = ctx
    return checks.check(out, ids, b, bar or bar0, r, ENDS, route="financial")


def reverted(res, key):
    return [x.split()[-1] for x in res["reverts"] if x.startswith(f"departure_reverted: {key} ")]


def test_clean_reply_is_ok_and_valued(ctx):
    res = run_check(clean(), ctx)
    assert res["status"] == "ok" and res["route"] == "financial" and "capital_constraint_not_modeled" in res["stamps"]
    assert res["values"]["bear"] <= res["values"]["base"] <= res["values"]["bull"]
    assert res["values"]["base"] == res["diagnostics"]["record_neutral"]["value"]


def test_reply_errors_on_the_financial_fields(ctx):
    out = clean()
    del out["base"]["roe"]
    assert "roe" in run_check(out, ctx)["errors"]
    out = depart(clean(), "roe.y1", "guidance")
    assert "roe.y1" in run_check(out, ctx)["errors"]
    out = depart(clean(), "book_growth.y1", "guidance", "guidance", ["B1.s1"], dict(grow("B1.s1"), metric="revenue_growth"))
    assert "guidance.book_growth.y1" in run_check(out, ctx)["errors"]


def test_the_example_shape_in_the_financial_prompt_passes_the_reply_rules(ctx):
    example = json.loads(re.search(r"```json\n(.*)\n```", task.INSTRUCTION_FIN, re.S).group(1))
    b, bar, ids = ctx
    ids = dict(ids, **{"P2.s4": {"fact_id": "P2", "kind": "annual_section", "period": "2025-12-31", "text": "x", "sentence": True}})
    assert checks.check(example, ids, b, bar, R, ENDS, route="financial")["status"] == "ok"


@pytest.mark.parametrize("evidence,rule", [(["A2.s1", "Q2.s1"], None), ([Y21, Y25], "V3"), (["R1.s1"], "V4")])
def test_V3_and_V4_on_an_roe_outside_the_record(ctx, evidence, rule):
    res = run_check(depart(clean(), "long_run_roe", ("p75", 1), "competition", evidence), ctx)            # 0.1145 > max 0.1049
    assert reverted(res, "long_run_roe") == ([rule] if rule else [])


def test_guided_book_growth_above_the_record_is_annotated_and_issuance_still_reverts(ctx):
    res = run_check(depart(clean(), "book_growth.y1", "guidance", "guidance", ["B1.s1"], grow("B1.s1")), ctx)
    assert reverted(res, "book_growth.y1") == []                                               # F_SPEC v1.2: guidance needs no V3g span
    assert any(a.startswith("guidance_outside_record: book_growth.y1") for a in res["annotations"])
    b, bar, ids = ctx
    rec = dict(b["record"], book_growth_max=0.5)                                                # no V3g: issuance decides
    res = checks.check(depart(clean(), "book_growth.y1", "guidance", "guidance", ["B3.s1"], grow("B3.s1")), ids, dict(b, record=rec),
                       bar, R, ENDS, route="financial")
    assert reverted(res, "book_growth.y1") == ["issuance"]


def test_release_needs_two_fiscal_years(ctx):
    out = depart(clean(), "book_growth.y1", "guidance", "guidance", ["B2.s1"], grow("B2.s1", "negative"))
    assert reverted(run_check(out, ctx), "book_growth.y1") == ["release"]
    out["departures"][0]["evidence"] = ["B2.s1", "A2.s1", "Q2.s1"]
    res = run_check(out, ctx)
    assert res["status"] == "ok" and res["numbers"]["book_growth.y1"] == pytest.approx(-0.02)


def test_long_run_roe_not_above_terminal_growth_reverts(ctx):
    b, bar, ids = ctx
    low = dict(bar, p25=0.03)
    res = run_check(depart(clean(), "long_run_roe", ("p25", 0), "competition", ["A2.s1", "Q2.s1"]), ctx, bar=low)
    assert reverted(res, "long_run_roe") == ["ronic_not_above_growth"] and res["status"] == "ok_with_reverts"


def test_V7_shrinking_book_is_annotated(ctx):
    out = depart(clean(), "book_growth.y1", "guidance", "guidance", ["B2.s1", "A2.s1", "Q2.s1"], grow("B2.s1", "negative"))
    out = depart(out, "book_growth.y2", "guidance", "guidance", ["B2.s1", "A2.s1", "Q2.s1"], grow("B2.s1", "negative"))
    assert any(a.startswith("V7 ") for a in run_check(out, ctx)["annotations"])


# ------------------------------------------------------------------ the runner routes the financial family
def test_prepare_routes_a_financial_to_the_book_equity_base(monkeypatch):
    monkeypatch.setattr(facts, "build", lambda *a, **k: bank_facts())
    monkeypatch.setattr(coe, "cost_of_equity", lambda *a, **k: (0.10, PROV))
    f, b, bar, record, r, p, fy_ends = run.prepare({"decision_time_utc": "2026-03-01T13:00:00Z"}, "1", "Banks", 1.0, online=False,
                                                   family="financial")
    assert b["route"] == "financial" and b["stub_days"] == 60 and b["g_anchor"] == 0.04
    assert record[-1]["fact_id"] == "Y2025-12-31" and "return on opening equity 10.5%" in record[-1]["text"]
    msg = task.messages({"evidence": []}, record, b, bar, r, p)[1]["content"]
    assert "TASK valuation_inputs_financial" in msg and "Filed return-on-equity record" in msg and "book_growth.y1, book_growth.y2" in msg


def test_an_unbuilt_family_is_still_refused_by_name():
    with pytest.raises(desk.DeskRefusal) as e:
        run.prepare({"decision_time_utc": "2026-10-30T13:00:00Z"}, "1", "REITs", 1.0, online=False, family="family_not_built")
    assert e.value.code == "family_not_routed"


PINNED_FIN = "39ddfe57c363a7b53b330c3b1170ea2ebf56dd951ca88ebbe4bfad563e861ecb"   # m3q.prompt.fin.v6


def test_the_financial_prompt_is_pinned_and_half_of_v5():
    b, bar, _ = ctx_of()
    pk = {"ticker": "T", "decision_time_utc": "2026-10-30T13:00:00Z", "cik": "1", "evidence": []}
    msg = task.user_message(pk, [], copy.deepcopy(b), bar, 0.1027, PROV)
    h = hashlib.sha256("\n".join([task.VALUATION_PROMPT_FIN_VERSION, tasks.SYSTEM, msg]).encode("utf-8")).hexdigest()
    assert h == PINNED_FIN, f"the financial prompt changed: bump VALUATION_PROMPT_FIN_VERSION and re-pin ({h})"
    assert task.VALUATION_PROMPT_FIN_VERSION == "m3q.prompt.fin.v6" and len(task.INSTRUCTION_FIN) <= 4184 / 2     # v5: 4,184 characters


def test_memo_renders_a_financial_result(ctx):
    from qwen_c.value import memo
    b, bar, _ = ctx
    out = depart(clean(), "roe.y1", "last", "record_persistence", [Y25, "A2.s1"])
    res = run_check(out, ctx)
    result = {"ticker": "TB", "T": "2026-03-01T13:00:00Z", "status": res["status"], "inputs": out, "checks": res, "values": res["values"],
              "cost_of_equity": R, "base": b, "stamps": b["stamps"]}
    text = memo.render(result)
    assert "- **roe.y1**: last, 0.1049 (record-neutral 0.1034), up; driver record_persistence" in text and "Tax" not in text
    assert "  - [A2.s1] Our return on equity in commercial lending was 14.0% for the year." in text
