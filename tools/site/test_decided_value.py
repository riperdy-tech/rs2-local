"""WO_NC7: the cloud read decides the valuation inputs, code pins the facts, checks the reply and values it (decided_value.py, the report row in
qwen_ondemand.report, the switch in gemini_ondemand.analyze). Synthetic data only; the model call is stubbed (runner.call) and every run
folder is a temp dir."""
import copy
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decided_value as D  # noqa: E402
import gemini_ondemand as G  # noqa: E402
import qwen_ondemand as Q  # noqa: E402
import qwen_site  # noqa: E402
from qwen_c import runner  # noqa: E402
from qwen_c.tests import test_value_checks as C  # noqa: E402
from qwen_c.tests import test_value_tax_statutory as TS  # noqa: E402
from qwen_c.value import checks, desk, forecast, inputs, menu  # noqa: E402

F1_TEXT = "Revenue grew steadily over the last five years and margins were stable. The company expects demand to stay firm."
QUOTE = "Revenue grew steadily over the last five years"
PK = {"contract": runner.PACKET_CONTRACT, "ticker": "TEST", "cik": "1", "decision_time_utc": "2026-11-18T00:00:00Z",
      "screener": {"commit": "abc"},
      "evidence": [{"fact_id": "F1", "kind": "annual_section", "title": "t", "form": "10-K", "period": "2025", "effective_at": "2026-01-01T00:00:00Z",
                    "source": None, "text": F1_TEXT},
                   {"fact_id": "S0", "kind": "screener_row", "title": "row", "form": None, "period": None, "effective_at": None, "source": None,
                    "text": "sector: Industrials\nprice: 12.5\nmarketCap: 1000000\nprice as-of: 2026-11-17\nrank: 3"}]}
UNSUPPORTED = "An unsupported claim that must not reach the prompt."
AN = {"tasks": {"business_model": {"claims": [{"claim": "A supported claim about the business.", "support": "supported", "mechanism": "It sells things."},
                                              {"claim": UNSUPPORTED, "support": "unsupported"}]}}}
ENDS_ALL = [f"{y}-12-31" for y in range(2014, 2026)]


def f_all():
    """Twelve filed fiscal years of revenue and operating income (the prompt's record shows all of them, the base only five)."""
    rev = [60, 66, 62, 70, 75, 72, 80, 85, 83, 90, 94, 100]
    oi = [0.10 * x for x in rev[:-5]] + [0.15 * x for x in rev[-5:]]
    mk = lambda vals: {"values": [{"end": e, "value": v * 1e6} for e, v in zip(ENDS_ALL, vals)]}  # noqa: E731
    return {"revenue": mk(rev), "operating_income": mk(oi)}


def reply(**over):
    o = {"situation": {"cyclical": "no", "margin_position": "The margin is steady.", "base_year_representative": "yes", "why": "A stable year."},
         "inputs": {"rev_growth": [0.05, 0.05, 0.04, 0.04, 0.03], "op_margin": [0.14, 0.14, 0.14, 0.14, 0.14], "long_run_op_margin": 0.13,
                    "terminal_growth": 0.03, "fade_years": 10, "return_on_new_investment_long_run": 0.15, "capex_to_revenue": 0.06},
         "ranges": {"long_run_op_margin": [0.10, 0.16], "rev_growth_y3": [0.02, 0.07], "terminal_growth": [0.02, 0.035]},
         "reasons": {k: {"why": f"Because of {k}.", "quotes": [{"id": "F1", "quote": QUOTE}]} for k in D.INPUT_KEYS},
         "biggest_risks": [{"risk": "Demand softens.", "input_hit": "op_margin", "bear_value": 0.12}], "confidence": "medium"}
    for path, v in over.items():                       # "inputs.fade_years": 30
        node = o
        *head, last = path.split(".")
        for h in head:
            node = node[h]
        node[last] = v
    return o


def stub(monkeypatch, replies):
    """runner.call returns the replies in order (a dict or str is a reply, a tuple is (kind, detail)); the message lists sent are collected."""
    sent, it = [], iter(replies)

    def call(body, url, timeout):
        sent.append(body["messages"])
        r = next(it)
        if isinstance(r, tuple):
            return r[0], None, r[1]
        return "reply", {"message": {"role": "assistant", "content": r if isinstance(r, str) else json.dumps(r)}, "done": True, "eval_count": 7}, None
    monkeypatch.setattr(runner, "call", call)
    return sent


def arrange(tmp_path, monkeypatch, replies=(), facts=None, pk=PK):
    f = facts or C.facts()
    b = dict(inputs.base(f, market_cap=180e6, bill_rate=0.04), stub_days=0, g_anchor=0.03, bill_source="test")
    bar = forecast.record_bar(b["record"]["op_margin"])
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps(pk), encoding="utf-8")
    prepared = []
    monkeypatch.setattr(D.vrun, "prepare", lambda *a, **k: prepared.append(k) or (f, b, bar, forecast.record_items(f), C.R, dict(C.PROV), C.ENDS))
    monkeypatch.setattr(D.facts, "build", lambda *a, **k: f_all())
    return packet, b, bar, stub(monkeypatch, list(replies)), prepared


def run(tmp_path, packet, seed=1000, family="operating", **k):
    return D.value(packet, "1", "Industrials", 180e6, family=family, analysis=AN, seed=seed, out_root=tmp_path / "runs", online=False, **k)


# ---- the prompt ---------------------------------------------------------------------------------------------------------------------

def test_the_prompt_text_is_pinned():
    """Changing what the model is told is a versioned decision (non-negotiable 7): re-pin this hash and bump DECIDED_VERSION together."""
    assert hashlib.sha256((D.SYSTEM + "\n" + D.BASE_RATES + "\n" + D.TASK).encode()).hexdigest() == "37561520f8b7a799cb755851bc9fe3017b4e2c64945753d2db73ecffe6c2951e"
    assert "1 in 4 chance of being undershot" in D.TASK and "1 in 4 chance of being overshot" in D.TASK and "Do not quote the PRIOR READ" in D.TASK
    assert D.METHOD == "decided.v1" and D.DECIDED_VERSION.startswith("decided.v1")


def test_the_message_carries_the_packet_masked_the_record_of_every_year_the_supported_read_and_the_base_rates(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()])
    run(tmp_path, packet)
    sysm, user = sent[0]
    assert sysm == {"role": "system", "content": D.SYSTEM} and len(sent[0]) == 2
    u = user["content"]
    assert F1_TEXT in u and "sector: Industrials" in u and "price: 12.5" not in u and "marketCap" not in u and "price as-of" not in u      # prices masked
    assert all(f"{e} | " in u for e in ENDS_ALL)                                                           # every filed year, not the base's five
    assert "2015-12-31 | $66.0 million | 0.1000 | 0.1000" in u and "2014-12-31 | $60.0 million | n/a | 0.1000" in u
    assert "A supported claim about the business. Mechanism: It sells things." in u and UNSUPPORTED not in u
    assert "PRIOR READ (another analyst's notes, unverified; not evidence, not to be quoted)" in u and "BASE RATES" in u and u.rstrip().endswith('"confidence": "low|medium|high"}')
    assert f"Return on new investment at which growth adds no value (code, after the company's leverage): {menu.neutral_ronic(b, C.R):.4f}" in u
    assert f"Cost of equity r {C.R:.4f}" in u


def test_a_record_with_no_operating_income_uses_pretax_plus_interest_and_says_so(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()])
    monkeypatch.setattr(D.facts, "build", lambda *a, **k: {"revenue": f_all()["revenue"], "pretax_income": {"values": [{"end": "2025-12-31", "value": 5e6}]},
                                                             "interest_expense": {"values": [{"end": "2025-12-31", "value": 1e6}]}})
    run(tmp_path, packet)
    u = sent[0][1]["content"]
    assert "(pretax income + interest expense) / revenue, no operating income being filed" in u and "2025-12-31 | $100.0 million | 0.0638 | 0.0600" in u


# ---- the numeric route ----------------------------------------------------------------------------------------------------------------

def test_the_menus_own_numbers_through_the_numeric_route_give_the_menus_value():
    f = C.facts()
    b = dict(inputs.base(f, market_cap=180e6, bill_rate=0.04), stub_days=0, g_anchor=0.03)
    bar = forecast.record_bar(b["record"]["op_margin"])
    m = menu.menus(b, bar, C.R, "operating")
    nb = menu.neutral_base("operating", m)
    sc = menu.scenario(nb, menu.resolve(nb, {}, m), m)
    path, _ = forecast.build_path(sc, bar, b["R0"])
    menu_value = desk.value_operating(forecast.assemble(sc, b, bar, r=C.R))["value_per_share"]
    inp = {"rev_growth": [y["rev_growth"] for y in path], "op_margin": [y["op_margin"] for y in path], "long_run_op_margin": sc["long_run_op_margin"],
           "terminal_growth": sc["terminal_g"], "fade_years": sc["fade_years"], "return_on_new_investment_long_run": sc["terminal_ronic"],
           "capex_to_revenue": b["c_ratio"]}
    assert D.value_inputs(b, C.R, inp)[0] == pytest.approx(menu_value, rel=1e-12)
    assert D.old_defaults(b, bar, C.R)[0] == pytest.approx(checks._neutral_op(b, bar, C.R)[0], rel=1e-12)
    assert D.old_defaults(b, bar, C.R)[0] == pytest.approx(menu_value, rel=1e-9)             # the old defaults' value is this record-neutral reply's


# ---- one run ---------------------------------------------------------------------------------------------------------------------

def test_a_valid_reply_is_valued_at_base_bear_and_bull_and_nothing_the_read_gave_is_changed(tmp_path, monkeypatch):
    packet, b, bar, sent, prepared = arrange(tmp_path, monkeypatch, [reply()])
    res = run(tmp_path, packet)
    inp, rng = reply()["inputs"], reply()["ranges"]
    assert res["status"] == "ok" and len(sent) == 1 and res["versions"]["method"] == "decided.v1" and res["checks"]["prob"] == checks.PROB
    assert res["cost_of_equity"] == C.R and res["base"] == b and res["seed"] == 1000 and res["checked_attempt"] == 1 and res["authority"] == "diagnostic_only"
    assert prepared[0]["family"] == "operating" and prepared[0]["online"] is False
    v = res["values"]
    bear_in = dict(inp, rev_growth=[g + (0.02 - 0.04) for g in inp["rev_growth"]], long_run_op_margin=0.10, terminal_growth=0.02)      # the year-3 growth becomes the bound
    bull_in = dict(inp, rev_growth=[g + (0.07 - 0.04) for g in inp["rev_growth"]], long_run_op_margin=0.16, terminal_growth=0.035)
    assert v["base"] == D.value_inputs(b, C.R, inp)[0] and v["bear"] == D.value_inputs(b, C.R, bear_in)[0] and v["bull"] == D.value_inputs(b, C.R, bull_in)[0]
    assert v["bear"] < v["base"] < v["bull"]
    d = res["decided"]
    assert d["inputs"] == inp and d["ranges"] == rng and res["inputs"] == reply() and d["scenarios"]["bear"]["rev_growth"] == pytest.approx(bear_in["rev_growth"])
    assert d["scenarios"]["bull"] == {"rev_growth": pytest.approx(bull_in["rev_growth"]), "long_run_op_margin": 0.16, "terminal_growth": 0.035}
    assert d["value_at_old_defaults"] == D.old_defaults(b, bar, C.R)[0] and d["old_defaults_inputs"]
    assert d["reasons"]["fade_years"] == {"why": "Because of fade_years.", "quotes": [{"id": "F1", "quote": QUOTE}], "quotes_given": 1}
    assert "quotes_verified: 7 of 7" in d["flags"] and d["prior_read_claims"] == {"kept": 1, "dropped_unsupported": 1} and "tax_range" not in res
    assert set(d["diagnostics"]) == {"equity_value", "tv_share", "seam_ratio", "da_rule", "wedge_rate_5"}
    (path,) = (tmp_path / "runs").glob("TEST_20261118T000000Z_*_decided_1000/result.json")
    assert json.loads(path.read_text(encoding="utf-8"))["values"] == v and (path.parent / "raw" / "attempt_1.json").exists()


def test_a_range_equal_to_the_input_gives_one_value(tmp_path, monkeypatch):
    packet, *_ = arrange(tmp_path, monkeypatch, [reply(**{"ranges.long_run_op_margin": [0.13, 0.13], "ranges.rev_growth_y3": [0.04, 0.04], "ranges.terminal_growth": [0.03, 0.03]})])
    v = run(tmp_path, packet)["values"]
    assert v["bear"] == v["base"] == v["bull"]


def test_the_quote_of_the_record_and_of_an_item_are_checked_word_for_word(tmp_path, monkeypatch):
    rec = {k: {"why": "x", "quotes": [{"id": "REC", "quote": f"Cost of equity r {C.R:.4f}"}]} for k in D.INPUT_KEYS}
    packet, *_ = arrange(tmp_path, monkeypatch, [reply(reasons=rec)])
    assert run(tmp_path, packet)["status"] == "ok"


PROBLEMS = [
    ("rev_growth is four numbers", {"inputs.rev_growth": [0.05] * 4}, "inputs.rev_growth must be a list of 5 numbers"),
    ("margin 1.2", {"inputs.op_margin": [0.14, 1.2, 0.14, 0.14, 0.14]}, "op_margin 1.2 is outside (-1, 1)"),
    ("long-run margin range end at 1", {"ranges.long_run_op_margin": [0.10, 1.0]}, "long_run_op_margin 1.0 is outside (-1, 1)"),
    ("terminal growth not below r", {"inputs.terminal_growth": 0.09, "ranges.terminal_growth": [0.02, 0.095]}, "is not below the cost of equity"),
    ("terminal growth range end not below r", {"ranges.terminal_growth": [0.02, 0.09]}, "terminal_growth 0.09 is not below the cost of equity"),
    ("return equal to growth", {"inputs.return_on_new_investment_long_run": 0.03}, "is not above terminal_growth 0.03"),
    ("return not above the growth range's high", {"inputs.return_on_new_investment_long_run": 0.033}, "is not above terminal_growth 0.035"),
    ("return not positive", {"inputs.return_on_new_investment_long_run": 0.0}, "is not above 0"),
    ("low above the input", {"ranges.long_run_op_margin": [0.14, 0.16]}, "must contain the input 0.13"),
    ("input above the high", {"ranges.rev_growth_y3": [0.0, 0.03]}, "must contain the input 0.04"),
    ("unverified quote", {"reasons.op_margin.quotes": [{"id": "F1", "quote": "invented words"}]}, "reasons.op_margin has no quote found word for word"),
    ("quote of an item that does not exist", {"reasons.op_margin.quotes": [{"id": "F9", "quote": QUOTE}]}, "reasons.op_margin has no quote found"),
    ("quote of the prior read", {"reasons.op_margin.quotes": [{"id": "business_model", "quote": "A supported claim about the business."}]}, "reasons.op_margin has no quote"),
    ("no quote for a long-run growth", {"reasons.terminal_growth.quotes": []}, "reasons.terminal_growth has no quote"),
    ("a reason missing", {"reasons.capex_to_revenue": None}, "reasons.capex_to_revenue must be"),
    ("fade years 30", {"inputs.fade_years": 30}, "inputs.fade_years must be a whole number from 1 to 25"),
    ("fade years 7.5", {"inputs.fade_years": 7.5}, "whole number"),
    ("cyclical maybe", {"situation.cyclical": "maybe"}, "situation.cyclical must be one of yes, no, unclear"),
    ("confidence sure", {"confidence": "sure"}, "confidence must be one of low, medium, high"),
    ("growth below -1", {"inputs.rev_growth": [-1.2, 0.05, 0.04, 0.04, 0.03]}, "is not above -1"),
    ("a low bound that takes a year's growth below -1", {"ranges.rev_growth_y3": [-1.5, 0.07]}, "rev_growth of the low case, year 1"),
    ("a boolean for a number", {"inputs.capex_to_revenue": True}, "inputs.capex_to_revenue must be a number"),
    ("risks without a risk", {"biggest_risks": [{"input_hit": "op_margin"}]}, "biggest_risks must be"),
    ("not JSON", "not json at all", "not valid JSON"),
    ("a list", [1, 2], "the reply is not a JSON object"),
]


@pytest.mark.parametrize("label,over,expect", PROBLEMS, ids=[p[0] for p in PROBLEMS])
def test_a_failed_check_gets_one_repair_turn_naming_the_problem_and_a_valid_second_reply_is_valued(tmp_path, monkeypatch, label, over, expect):
    bad = over if isinstance(over, (str, list)) else reply(**over)
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [bad, reply()])
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and res["checked_attempt"] == 2 and len(sent) == 2 and sent[1][:2] == sent[0]
    assert [m["role"] for m in sent[1]] == ["system", "user", "assistant", "user"]
    assert expect in sent[1][3]["content"] and sent[1][2]["content"] == (bad if isinstance(bad, str) else json.dumps(bad))
    assert res["attempts"][0]["outcome"] == "invalid" and expect in "; ".join(res["attempts"][0]["problems"]) and res["attempts"][1]["outcome"] == "ok"


def test_a_second_failure_is_decision_invalid_with_no_value(tmp_path, monkeypatch):
    bad = reply(**{"inputs.op_margin": [0.14, 1.2, 0.14, 0.14, 0.14]})
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [bad, reply(**{"reasons.op_margin.quotes": []})])
    res = run(tmp_path, packet)
    assert res["status"] == "no_call" and res["reason"] == "decision_invalid" and len(sent) == 2 and "values" not in res and "decided" not in res
    assert "reasons.op_margin has no quote" in res["detail"] and "outside (-1, 1)" not in res["detail"]       # the detail is the last attempt's
    assert qwen_site.NO_VALUE["decision_invalid"] and len(res["attempts"]) == 2


def test_a_desk_refusal_goes_back_to_the_model_like_any_other_problem(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), reply()])
    real, n = D.value_inputs, {"n": 0}

    def flaky(bb, r, inp):
        n["n"] += 1
        if n["n"] == 1:
            raise desk.DeskRefusal("ronic_not_above_growth", "the long-run equity return does not exceed g_T")
        return real(bb, r, inp)
    monkeypatch.setattr(D, "value_inputs", flaky)
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and len(sent) == 2 and "the desk could not value the base inputs: ronic_not_above_growth" in sent[1][3]["content"]


def test_an_engine_defect_is_recorded_not_raised_and_not_retried(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), reply()])
    monkeypatch.setattr(D.checks, "_recompute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("V1: broken")))
    res = run(tmp_path, packet)
    assert res["status"] == "engine_defect" and res["reason"] == "engine_defect" and "V1: broken" in res["detail"] and len(sent) == 1 and "values" not in res


def test_a_call_that_gets_no_reply_raises_and_writes_no_result(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [("infra_fatal", "down")])
    with pytest.raises(RuntimeError, match="infra_fatal: down"):
        run(tmp_path, packet)
    assert not list((tmp_path / "runs").glob("**/result.json"))
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(**{"inputs.fade_years": 30}), ("timeout", "slow")])
    with pytest.raises(RuntimeError, match="timeout: slow"):                       # the repair turn's call too
        run(tmp_path, packet)


# ---- refusals before any call: as the menu method ----------------------------------------------------------------------------------

def test_a_prepare_refusal_is_the_menu_methods_refusal_and_no_call_is_made(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()])

    def refuse(*a, **k):
        raise desk.DeskRefusal("tax_unavailable", "no usable tax rate")
    monkeypatch.setattr(D.vrun, "prepare", refuse)
    res = run(tmp_path, packet)
    assert (res["status"], res["reason"]) == ("no_call", "tax_unavailable") and sent == [] and res["versions"]["method"] == "decided.v1"


def test_a_packet_with_news_and_a_family_that_is_not_routed_are_refused_without_a_call(tmp_path, monkeypatch):
    news = copy.deepcopy(PK)
    news["evidence"].append({"fact_id": "N1", "kind": "news", "title": "t", "form": None, "period": None, "effective_at": None, "source": None, "text": "x"})
    packet, b, bar, sent, prepared = arrange(tmp_path, monkeypatch, [reply()], pk=news)
    assert run(tmp_path, packet)["reason"] == "news_items_not_valued"
    packet, b, bar, sent, prepared = arrange(tmp_path, monkeypatch, [reply()])
    res = run(tmp_path, packet, family="financial")
    assert res["reason"] == "family_not_routed" and sent == [] and prepared == []
    assert D.FAMILIES == ("operating", "commodity")


def test_the_commodity_family_is_valued(tmp_path, monkeypatch):
    packet, *_ = arrange(tmp_path, monkeypatch, [reply()])
    assert run(tmp_path, packet, family="commodity")["status"] == "ok"


# ---- the flags -------------------------------------------------------------------------------------------------------------------------

def test_flags_are_stamps_not_clamps(tmp_path, monkeypatch):
    over = {"inputs.op_margin": [0.30, 0.14, 0.14, 0.14, 0.14], "inputs.long_run_op_margin": 0.02, "ranges.long_run_op_margin": [0.01, 0.16],
            "inputs.rev_growth": [0.50, 0.05, 0.04, 0.04, 0.03], "situation.base_year_representative": "no", "confidence": "low",
            "reasons.op_margin.quotes": [{"id": "F1", "quote": QUOTE}, {"id": "F1", "quote": "not in the item"}]}
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(**over, **{"inputs.return_on_new_investment_long_run": 0.99})])
    res = run(tmp_path, packet)
    fl = res["decided"]["flags"]
    assert res["status"] == "ok" and len(sent) == 1
    assert "margin_outside_filed_record: op_margin.y1 0.3000 (filed 0.1000 to 0.1500)" in fl and not any(x.startswith("margin_outside_filed_record: op_margin.y2") for x in fl)
    assert "margin_outside_filed_record: long_run_op_margin 0.0200 (filed 0.1000 to 0.1500)" in fl and any(x.startswith("growth_outside_filed_record: rev_growth.y1 0.5000") for x in fl)
    assert f"return_above_base_year: long-run 0.9900 against the base year's {b['ronic0']:.4f}" in fl
    assert "base_year_not_representative" in fl and "confidence_low" in fl and "quotes_verified: 7 of 8" in fl
    assert res["decided"]["inputs"]["op_margin"][0] == 0.30 and res["decided"]["reasons"]["op_margin"]["quotes"] == [{"id": "F1", "quote": QUOTE}]


def test_a_flag_free_reply_has_only_the_quote_count(tmp_path, monkeypatch):
    packet, *_ = arrange(tmp_path, monkeypatch, [reply()])
    assert run(tmp_path, packet)["decided"]["flags"] == ["quotes_verified: 7 of 7"]


def test_a_value_order_that_is_not_monotone_is_annotated(tmp_path, monkeypatch):
    """A return on new investment under the cost of equity makes growth destroy value: the low growth case is worth more."""
    packet, *_ = arrange(tmp_path, monkeypatch, [reply(**{"inputs.return_on_new_investment_long_run": 0.05})])
    res = run(tmp_path, packet)
    v = res["values"]
    assert res["status"] == "ok" and (v["bear"] <= v["base"] <= v["bull"]) == (not any(f.startswith("scenario_order_not_monotone") for f in res["decided"]["flags"]))


# ---- the statutory tax fallback ----------------------------------------------------------------------------------------------------

def test_a_tax_fallback_carries_the_value_at_the_second_rate_per_run(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()], facts=TS.fb_facts())
    res = run(tmp_path, packet)
    tr = res["tax_range"]
    assert b["tax_fallback"] and tr["rate"] == b["tax_fallback"]["rate"] and tr["rate_alt"] == b["tax_fallback"]["rate_alt"] and tr["status_alt"] == "ok"
    assert tr["values"] == res["values"] and set(tr["values_alt"]) == {"bear", "base", "bull"} and tr["values_alt"]["base"] < tr["values"]["base"]
    alt_b = D.vrun.alt_tax_base(TS.fb_facts(), b, 180e6)
    assert tr["values_alt"]["base"] == D.value_inputs(alt_b, C.R, reply()["inputs"])[0]


def test_a_second_rate_that_cannot_be_made_leaves_the_first_values(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()], facts=TS.fb_facts())
    monkeypatch.setattr(D.vrun, "alt_tax_base", lambda *a: (_ for _ in ()).throw(desk.DeskRefusal("e0_not_positive", "no earnings base")))
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and res["tax_range"]["values_alt"] is None and "e0_not_positive" in res["tax_range"]["status_alt"] and res["values"]["base"]


# ---- the two runs and the report ------------------------------------------------------------------------------------------------

def two_runs(tmp_path, monkeypatch, second=None, facts=None, root=None):
    """The two seeds' results (the second reply differs a little, as two samples do), valued on one packet."""
    out = (root or tmp_path) / "runs"
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), second or reply(**{"inputs.long_run_op_margin": 0.12, "inputs.terminal_growth": 0.025})], facts=facts)
    return packet, b, {str(s): D.value(packet, "1", "Industrials", 180e6, family="operating", analysis=AN, seed=s, out_root=out, online=False) for s in (1000, 3000)}


def N(packet):
    return {"packet": str(packet), "cik": "1", "sector": "Industrials", "market_cap": 180e6, "family": "operating"}


def test_the_report_row_is_the_mean_of_the_two_runs_each_runs_base_is_kept_and_the_gap_is_a_number(tmp_path, monkeypatch):
    packet, b, rs = two_runs(tmp_path, monkeypatch)
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    a, c = rs["1000"]["values"], rs["3000"]["values"]
    assert rep["valued"] and rep["valuation"] is None and rep["no_value_reason"] is None and rep["family"] == "operating"
    assert rep["value_per_filed_share"] == {k: (a[k] + c[k]) / 2 for k in ("bear", "base", "bull")}
    assert rep["seed_base"] == {"1000": a["base"], "3000": c["base"]} and rep["filed_shares"] == b["shares"]
    assert rep["equity_value"] == rep["value_per_filed_share"]["base"] * b["shares"] and rep["seeds_agree"] is True and "tax_range" not in rep
    d = rep["decided"]
    assert d["run_gap"] == pytest.approx(abs(a["base"] - c["base"]) / ((abs(a["base"]) + abs(c["base"])) / 2)) and 0 < d["run_gap"] < 1
    assert set(d) == {"version", "method", "runs", "run_gap", "situation_unclear", "flags", "value_at_old_defaults", "old_defaults_inputs"}
    assert set(d["runs"]) == {"1000", "3000"} and d["runs"]["1000"]["values"] == a and d["runs"]["3000"]["inputs"]["long_run_op_margin"] == 0.12
    assert set(d["runs"]["1000"]) >= {"situation", "inputs", "ranges", "reasons", "risks", "confidence", "flags", "scenarios", "values"}
    assert d["situation_unclear"] is False and d["method"] == "decided.v1" and d["flags"][0].startswith("run 1000: ")
    assert d["value_at_old_defaults"] == rs["1000"]["decided"]["value_at_old_defaults"]
    json.dumps(rep)                                                                      # the report is plain JSON


def test_the_two_runs_disagreeing_on_cyclical_is_stamped_situation_unclear(tmp_path, monkeypatch):
    packet, b, rs = two_runs(tmp_path, monkeypatch, second=reply(**{"situation.cyclical": "yes"}))
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    assert rep["decided"]["situation_unclear"] is True and rep["decided"]["flags"][0] == "situation_unclear" and rep["seeds_agree"] is False
    packet, b, rs = two_runs(tmp_path, monkeypatch, second=reply(**{"situation.cyclical": "unclear"}))
    assert D.combine_runs(rs)[1]["decided"]["situation_unclear"] is True                  # unclear against no is a disagreement


def test_there_is_no_value_from_one_run_alone_and_no_fallback_to_a_default(tmp_path, monkeypatch):
    bad = reply(**{"inputs.fade_years": 30})
    packet, b, rs = two_runs(tmp_path, monkeypatch, second=None)
    # the second seed's two attempts both invalid
    packet2, b2, bar2, sent, _ = arrange(tmp_path, monkeypatch, [reply(), bad, bad])
    r1 = D.value(packet2, "1", "Industrials", 180e6, family="operating", analysis=AN, seed=1000, out_root=tmp_path / "r2", online=False)
    r2 = D.value(packet2, "1", "Industrials", 180e6, family="operating", analysis=AN, seed=3000, out_root=tmp_path / "r2", online=False)
    assert r1["status"] == "ok" and r2["reason"] == "decision_invalid" and D.combine_runs({"1000": r1, "3000": r2}) == (False, {})
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet2), {"1000": r1, "3000": r2}, "c")
    assert rep["valued"] is False and rep["no_value_reason"] == qwen_site.NO_VALUE["decision_invalid"] and "decided" not in rep and "value_per_filed_share" not in rep
    assert D.combine_runs({"1000": r1}) == (False, {})


def test_a_refused_name_reports_the_menu_reason(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [])
    monkeypatch.setattr(D.vrun, "prepare", lambda *a, **k: (_ for _ in ()).throw(desk.DeskRefusal("tax_unavailable", "x")))
    rs = {str(s): run(tmp_path, packet, seed=s) for s in (1000, 3000)}
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    assert rep["valued"] is False and rep["no_value_reason"] == qwen_site.NO_VALUE["tax_unavailable"] and sent == []


def test_a_tax_fallback_report_carries_the_mean_second_rate_values_and_the_label(tmp_path, monkeypatch):
    packet, b, rs = two_runs(tmp_path, monkeypatch, facts=TS.fb_facts())
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    tr = rep["tax_range"]
    a1, a3 = rs["1000"]["tax_range"]["values_alt"], rs["3000"]["tax_range"]["values_alt"]
    assert tr["label"] == Q.TAX_RANGE_LABEL and tr["rate"] == b["tax_fallback"]["rate"] and tr["rate_alt"] == b["tax_fallback"]["rate_alt"] and tr["status_alt"] == "ok"
    assert tr["value_per_filed_share_alt"] == {k: (a1[k] + a3[k]) / 2 for k in ("bear", "base", "bull")}
    assert tr["seed_base_alt"] == {"1000": a1["base"], "3000": a3["base"]} and tr["equity_value_alt"] == tr["value_per_filed_share_alt"]["base"] * b["shares"]


def test_quote_units_puts_the_reference_value_in_the_unit_that_trades_and_the_verdict_reads_the_report(tmp_path, monkeypatch):
    packet, b, rs = two_runs(tmp_path, monkeypatch)
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    row = {k: v for k, v in rep.items() if k not in ("tasks", "valuation", "ticker", "authority")}
    old = rep["decided"]["value_at_old_defaults"]
    shares = rep["filed_shares"]
    qwen_site.quote_units({"TEST": (row, rep)}, {"TEST": {"price": 10.0, "marketCap": 10.0 * 2 * shares}})       # two quoted shares per filed share: k = 1/2
    assert row["value_base"] == pytest.approx(rep["value_per_filed_share"]["base"] * 0.5) and row["decided"]["value_at_old_defaults_quoted"] == pytest.approx(old * 0.5)
    assert rep["decided"] == row["decided"] and row["decided"]["value_at_old_defaults"] == old
    ke, prob = C.R, checks.PROB
    v, why, a = G.verdict(row, ke, prob)                                                  # the unchanged rule reads value_*, seed_base and value_per_filed_share
    assert v in ("BUY", "WATCH", "AVOID") and a is not None
    plain = {k: v for k, v in rep.items() if k != "decided"}
    qwen_site.quote_units({"TEST": (dict(plain), dict(plain))}, {"TEST": {"price": 10.0, "marketCap": 10.0 * shares}})      # a menu row has no decided: untouched


def test_value_meta_finds_the_decided_runs_result(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ROOT", tmp_path)
    packet, b, rs = two_runs(tmp_path, monkeypatch, root=tmp_path / "cache" / "m3q")
    out = tmp_path / "cache" / "m3q" / "runs"
    assert list(out.glob("TEST_20261118T000000Z_*_decided_1000/result.json"))
    assert G.value_meta({"ticker": "TEST", "date": "2026-11-18T00:00:00Z"}) == (C.R, checks.PROB)


# ---- the switch in gemini_ondemand.analyze ---------------------------------------------------------------------------------------

def switch(tmp_path, monkeypatch, method, family="operating"):
    import test_why_losses as TW
    seeds, reports, sent = TW.arrange(tmp_path, monkeypatch, False)
    monkeypatch.setitem(sys.modules, "formation_value", types.SimpleNamespace(stocks_rows=lambda c: {"TEST": {"sector": "Technology", "marketCap": 1e8}},
                                                                              name_family=lambda cik, T: {"family": family}))
    decided_calls = []
    monkeypatch.setattr(G.decided_value, "value", lambda *a, **k: decided_calls.append((a, k)) or {"status": "ok", "seed": k["seed"]})
    monkeypatch.setattr(G, "VALUE_METHOD", method)
    return seeds, reports, decided_calls


def test_the_default_is_the_menu_and_the_decided_step_is_never_reached(tmp_path, monkeypatch):
    seeds, reports, calls = switch(tmp_path, monkeypatch, "menu")
    assert G.analyze("TEST", "list") == "ok"
    assert seeds == [1000, 3000] and calls == [] and list(reports[0]) == ["1000", "3000"]


def test_decided_values_an_operating_name_with_the_decided_step_in_place_of_the_menu_for_both_seeds(tmp_path, monkeypatch):
    seeds, reports, calls = switch(tmp_path, monkeypatch, "decided")
    assert G.analyze("TEST", "list") == "ok"
    assert seeds == [] and [k["seed"] for _, k in calls] == [1000, 3000] and list(reports[0]) == ["1000", "3000"]
    a, k = calls[0]
    assert a[1:4] == ("1", "Technology", 1e8) and k["family"] == "operating" and k["analysis"] == {} and k["out_root"] == G.vrun.RUNS


def test_decided_keeps_the_menu_for_the_financial_family_and_for_a_family_not_routed(tmp_path, monkeypatch):
    for family in ("financial", "reit"):
        (tmp_path / family).mkdir()
        seeds, reports, calls = switch(tmp_path / family, monkeypatch, "decided", family)
        G.analyze("TEST", "list")
        assert seeds == [1000, 3000] and calls == []


def test_an_unknown_method_is_refused_before_a_name_is_claimed(monkeypatch):
    monkeypatch.setattr(G, "VALUE_METHOD", "free")
    with pytest.raises(ValueError, match="not one of"):
        G.decided()
    monkeypatch.setattr(G, "take_lock", lambda: (_ for _ in ()).throw(AssertionError("claimed a name")))
    with pytest.raises(ValueError):
        G.work(1, False)
    monkeypatch.setattr(G, "VALUE_METHOD", "decided")
    assert G.decided() is True
