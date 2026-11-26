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
F2_TEXT = ("Cash held for customers was 2,500 thousand at year end. Restricted cash was $9.0 million. A loss on the sale of an investment of $1.2 million "
           "was recorded outside operating income. A gain on a legal settlement of 0.4 million was recorded outside operating income. "
           "A gain on the sale of a building of $50.0 million was recorded outside operating income.")
Q_CASH, Q_RESTRICTED, Q_LOSS, Q_GAIN, Q_BIG = ("Cash held for customers was 2,500 thousand", "Restricted cash was $9.0 million", "A loss on the sale of an investment of $1.2 million",
                                              "A gain on a legal settlement of 0.4 million", "A gain on the sale of a building of $50.0 million")
PK = {"contract": runner.PACKET_CONTRACT, "ticker": "TEST", "cik": "1", "decision_time_utc": "2026-11-18T00:00:00Z",
      "screener": {"commit": "abc"},
      "evidence": [{"fact_id": "F1", "kind": "annual_section", "title": "t", "form": "10-K", "period": "2025", "effective_at": "2026-01-01T00:00:00Z",
                    "source": None, "text": F1_TEXT},
                   {"fact_id": "F2", "kind": "annual_section", "title": "t2", "form": "10-K", "period": "2025", "effective_at": "2026-01-01T00:00:00Z",
                    "source": None, "text": F2_TEXT},
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
    o = {"situation": {"cyclical": "no", "margin_position": "The margin is steady.", "base_year_representative": "yes", "why": "A stable year.",
                       "tax_rate_representative": {"answer": "yes", "why": "The rate is the one filed."}, "debt_level_representative": {"answer": "yes", "why": "Debt is steady."}},
         "inputs": {"rev_growth": [0.05, 0.05, 0.04, 0.04, 0.03], "op_margin": [0.14, 0.14, 0.14, 0.14, 0.14], "long_run_op_margin": 0.13,
                    "terminal_growth": 0.03, "fade_years": 10, "return_on_new_investment_long_run": 0.15, "capex_to_revenue": 0.06},
         "ranges": {"long_run_op_margin": [0.10, 0.16], "rev_growth_y3": [0.02, 0.07], "terminal_growth": [0.02, 0.035]},
         "cash_not_free": None, "base_year_one_offs": None,
         "reasons": {k: {"why": f"Because of {k}.", "quotes": [{"id": "F1", "quote": QUOTE}]} for k in D.INPUT_KEYS},
         "biggest_risks": [{"risk": "Demand softens.", "input_hit": "op_margin", "bear_value": 0.12}], "confidence": "medium"}
    for path, v in over.items():                       # "inputs.fade_years": 30
        node = o
        *head, last = path.split(".")
        for h in head:
            node = node[h]
        node[last] = v
    return o


def cash(value=2500, scale="thousands", quote=Q_CASH, what="cash held for customers"):
    return {"value": value, "scale": scale, "what": what, "quotes": [{"id": "F2", "quote": quote}]}


def one_off(value, sign, quote, scale="millions", what="an item"):
    return {"value": value, "scale": scale, "sign": sign, "what": what, "quotes": [{"id": "F2", "quote": quote}]}


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
    f = facts or dict(C.facts(), eps_diluted=C.series([1.0] * 5))              # WO_UV2: with a filed EPS the share count is proven, so no stamp of an unproven count rides in the flags
    b = dict(inputs.base(f, market_cap=180e6, bill_rate=0.04), stub_days=0, g_anchor=0.03, bill_source="test")
    bar = forecast.record_bar(b["record"]["op_margin"])
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps(pk), encoding="utf-8")
    prepared = []
    monkeypatch.setattr(D.vrun, "prepare", lambda *a, **k: prepared.append(k) or (f, b, bar, forecast.record_items(f), C.R, dict(C.PROV), C.ENDS))
    monkeypatch.setattr(D.facts, "build", lambda *a, **k: f_all())
    monkeypatch.setattr(D, "code_capital_events", lambda *a, **k: {"found": False, "absent": "test: no filed data"})      # WO_NC10a: hermetic; the tests of the events set their own
    return packet, b, bar, stub(monkeypatch, list(replies)), prepared


def run(tmp_path, packet, seed=1000, family="operating", **k):
    return D.value(packet, "1", "Industrials", 180e6, family=family, analysis=AN, seed=seed, out_root=tmp_path / "runs", online=False, **k)


# ---- the prompt ---------------------------------------------------------------------------------------------------------------------

def test_the_prompt_text_is_pinned():
    """Changing what the model is told is a versioned decision (non-negotiable 7): re-pin this hash and bump DECIDED_VERSION together."""
    assert hashlib.sha256((D.SYSTEM + "\n" + D.BASE_RATES + "\n" + D.TASK).encode()).hexdigest() == "04802d490ef5677e7bc87f60802b28b42c292ca88cd7a08c0c5ceeae49f7bf3d"
    assert "1 in 4 chance of being undershot" in D.TASK and "1 in 4 chance of being overshot" in D.TASK and "Do not quote the PRIOR READ" in D.TASK
    assert D.METHOD == "decided.v1" and D.DECIDED_VERSION.startswith("decided.v3")        # WO_NC10a: the label stays, the prompt version moves
    assert "cash_not_free" in D.TASK and "base_year_one_offs" in D.TASK and "tax_rate_representative" in D.TASK and "debt_level_representative" in D.TASK
    assert "since_base_year" in D.TASK and "you neither leave an acquisition out of your inputs nor lower them for its cost" in D.TASK        # WO_NC10a


def test_the_message_carries_the_packet_masked_the_record_of_every_year_the_supported_read_and_the_base_rates(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()])
    run(tmp_path, packet)
    sysm, user = sent[0]
    assert sysm == {"role": "system", "content": D.SYSTEM} and len(sent[0]) == 2
    u = user["content"]
    assert F1_TEXT in u and "sector: Industrials" in u and "price: 12.5" not in u and "marketCap" not in u and "price as-of" not in u      # prices masked
    assert all(f"{e} | " in u for e in ENDS_ALL)                                                           # every filed year, not the base's five
    assert "2015-12-31 | $66.0 million | 0.1000 | 0.1000" in u and "2014-12-31 | $60.0 million | n/a | 0.1000" in u
    assert f"{menu.neutral_ronic(b, C.R):.4f}" in u and "Non-operating items that the valuation holds in dollars for ever" in u and f"{b['k0'] / 1e6:,.1f} million, of which interest on debt $1.0 million" in u
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
    assert set(d["diagnostics"]) == {"equity_value", "tv_share", "seam_ratio", "da_rule", "wedge_rate_5", "depreciation_kept_rate"}
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
    # WO_NC9a
    ("tax flag not an object", {"situation.tax_rate_representative": "yes"}, "situation.tax_rate_representative must be"),
    ("debt flag with a bad answer", {"situation.debt_level_representative": {"answer": "maybe", "why": "x"}}, "situation.debt_level_representative must be"),
    ("cash without a quote that exists", {"cash_not_free": cash(quote="Cash was invented")}, "cash_not_free has no quote found word for word"),
    ("cash digits not in the quote", {"cash_not_free": cash(value=3000)}, "cash_not_free: the number 3000 does not appear in any quote"),
    ("cash above the cash counted as excess", {"cash_not_free": cash(value=9.0, scale="millions", quote=Q_RESTRICTED)}, "cash_not_free 9,000,000 is not above 0 and at most the cash and short-term investments counted as excess (7,000,000)"),
    ("cash scale unknown", {"cash_not_free": cash(scale="lakhs")}, "cash_not_free.scale must be one of"),
    ("cash value zero", {"cash_not_free": cash(value=0)}, "cash_not_free.value must be a number above 0"),
    ("cash with no what", {"cash_not_free": dict(cash(), what="")}, "cash_not_free.what is missing"),
    ("one-off sign unknown", {"base_year_one_offs": [one_off(1.2, "loss", Q_LOSS)]}, "base_year_one_offs[0].sign must be one of charge, gain"),
    ("second one-off digits not in the quote", {"base_year_one_offs": [one_off(1.2, "charge", Q_LOSS), one_off(0.5, "gain", Q_GAIN)]}, "base_year_one_offs[1]: the number 0.5 does not appear"),
    ("one-off quote not found", {"base_year_one_offs": [one_off(1.2, "charge", "A loss of $1.2 million that is not there")]}, "base_year_one_offs[0] has no quote found word for word"),
    ("one-offs that leave no earnings base", {"base_year_one_offs": [one_off(50.0, "gain", Q_BIG)]}, "the adjustments leave no earnings base"),
    ("one-offs not a list", {"base_year_one_offs": {"value": 1}}, "base_year_one_offs must be null or a list"),
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


def test_a_base_stamp_of_a_reading_made_without_a_filed_figure_reaches_the_flags(tmp_path, monkeypatch):
    """WO_UV2: no filed EPS to prove the share count, and the readings of the stage-1 recovery, are stamps of the base that the run's flags repeat."""
    packet, b, *_ = arrange(tmp_path, monkeypatch, [reply()], facts=C.facts())                  # no filed EPS
    assert "shares_unreconciled_no_eps" in b["stamps"]
    fl = run(tmp_path, packet)["decided"]["flags"]
    assert fl == ["shares_unreconciled_no_eps", "quotes_verified: 7 of 7"]
    assert D.surfaced_stamps({"stamps": ["a", "working_capital_unclassified_balance_sheet", "preferred_balance_not_filed_taken_as_0:2025-12-31", "x:y"]}) == [
        "working_capital_unclassified_balance_sheet", "preferred_balance_not_filed_taken_as_0:2025-12-31"]


def test_the_stamps_of_figures_read_from_the_filings_inline_xbrl_reach_the_flags():
    """WO_UV3: which document and which tag or member a figure came from, and (WO_UV5) the IFRS interest expense used for an out-of-band finance-cost bundle, are shown on the site."""
    stamps = ["a", "ix_read:capex:0001-26-000010:x:PaymentsForVesselsUnderConstruction",
              "interest_ifrs_expense_for_finance_costs:refused=ifrs-full:FinanceCosts:used=ifrs-full:InterestExpense",
              "shares_from_ix_class_members:0001-26-000010:CommonStockMember", "shares_reconciled_with_class_eps", "shares_weighted_average_diluted"]
    assert D.surfaced_stamps({"stamps": stamps}) == stamps[1:5]


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


def test_a_name_with_no_route_reports_this_companys_own_reason(tmp_path, monkeypatch):      # 2026-11-25: the fixed "(real estate, pre-profit biotech)" line named kinds the company was not
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [])
    rs = {str(s): run(tmp_path, packet, seed=s, family="family_not_built") for s in (1000, 3000)}
    assert {r["reason"] for r in rs.values()} == {"family_not_routed"}
    why = "pre_profit: operating income <= 0 in 4 of the last 4 fiscal years"
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, {**N(packet), "family": "family_not_built", "family_reason": why}, rs, "c")
    assert rep["valued"] is False and rep["no_value_reason"] == "no valuation route yet for a company with no operating profit in 4 of its last 4 fiscal years"
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, {**N(packet), "family": "family_not_built"}, rs, "c")
    assert rep["no_value_reason"] == qwen_site.NO_VALUE["family_not_routed"]              # no reason on the name: the general line


def test_the_no_route_wording_covers_every_kind_the_classification_does_not_build():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "paper_books"))
    import value_family
    for _, kind in value_family._NOT_BUILT:
        assert qwen_site.not_routed(f"SIC 1: {kind}; family not built") == "no valuation route yet for " + qwen_site.NOT_BUILT_KIND[kind]
    reit = "SIC 7011: filed evidence of a real estate investment trust (real-estate schedule and balance-sheet property); family not built"
    assert qwen_site.not_routed(reit) == "no valuation route yet for a real estate company or trust"
    assert qwen_site.not_routed(None) == qwen_site.not_routed("something new") == qwen_site.NO_VALUE["family_not_routed"]


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


def test_value_meta_prefers_the_runs_of_the_reports_own_method(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ROOT", tmp_path)
    two_runs(tmp_path, monkeypatch, root=tmp_path / "cache" / "m3q_sonnet")
    menu = tmp_path / "cache" / "m3q" / "runs" / "TEST_20261118T000000Z_abc_1000"
    menu.mkdir(parents=True)
    (menu / "result.json").write_text(json.dumps({"status": "ok", "cost_of_equity": 0.5, "checks": {"prob": {"bear": 0.2, "base": 0.6, "bull": 0.2}}}), encoding="utf-8")
    rep = {"ticker": "TEST", "date": "2026-11-18T00:00:00Z"}
    assert G.value_meta(rep)[0] == 0.5                                                     # a menu report reads the menu run
    assert G.value_meta(dict(rep, decided={"method": "decided.v1"})) == (C.R, checks.PROB)  # a decided report reads its own runs


def test_pending_offer_reads_the_supported_pending_acquisition_of_the_company(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ROOT", tmp_path)
    d = tmp_path / "cache" / "m3m_x" / "runs" / "TEST_20261118T000000Z_abc_1"
    d.mkdir(parents=True)
    rep = {"ticker": "TEST", "date": "2026-11-18T00:00:00Z"}
    ev = {"claim": "c", "event_type": "acquisition_of_the_company", "status": "announced_pending", "occurred_on": "d", "support": "supported"}
    for claims, want in (([ev], {"claim": "c", "date": "d"}), ([dict(ev, status="occurred")], None), ([dict(ev, support="quote_not_found")], None),
                         ([dict(ev, event_type="other_material_event")], None), ([], None)):
        (d / "analysis.json").write_text(json.dumps({"tasks": {"material_events": {"claims": claims}}}), encoding="utf-8")
        assert G.pending_offer(rep) == want
    assert G.pending_offer(dict(rep, ticker="NONE")) is None


def test_a_name_goes_to_the_fallback_arm_only_when_the_home_allowance_is_low_and_the_fallbacks_is_not(monkeypatch):
    left = {"gemini": 0.5, "sonnet": 0.5}
    monkeypatch.setattr(G, "meter", lambda: {k: (left[G.ARM], None) for k in G.FLOORS})
    monkeypatch.setattr(G, "log", lambda msg: None)
    try:
        assert G.choose_arm("gemini") == "gemini" and G.ARM == "gemini"
        left["gemini"] = 0.0
        assert G.choose_arm("gemini") == "sonnet" and G.ARM == "sonnet" and G.GEM_MODEL == G.ARMS["sonnet"]["model"]
        left["sonnet"] = 0.0
        assert G.choose_arm("gemini") == "gemini" and G.ARM == "gemini" and G.LOCK.name == "worker.lock"      # both low: wait at home
        left["gemini"] = 0.5
        assert G.choose_arm("gemini") == "gemini"
        assert G.choose_arm("sonnet") == "sonnet"                 # an arm with no fallback stays itself
    finally:
        G.set_arm("gemini")


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


def test_decided_keeps_the_menu_for_a_family_not_routed(tmp_path, monkeypatch):      # WO_NC9b: the financial family is routed to decided_financial (test_decided_financial.py)
    for family in ("reit",):
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


# ---- WO_NC9a: cash that is not free, one-offs of the base year, two flags --------------------------------------------------------------------

def adj_run(tmp_path, monkeypatch, over, **k):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(**over)], **k)
    return run(tmp_path, packet), b, bar, sent


def hand_base(b, **upd):
    """The base with the adjusted fields written out by hand (fixture: tau 0.2, bill rate 0.04, base cash 7.0 million, x0 10.176 million, k0 3.28 million)."""
    return dict(b, **upd)


def test_cash_not_free_reduces_excess_cash_and_returns_its_interest_to_the_earnings_base_and_both_stay_consistent(tmp_path, monkeypatch):
    res, b, bar, sent = adj_run(tmp_path, monkeypatch, {"cash_not_free": cash()})
    assert res["status"] == "ok" and len(sent) == 1
    a = res["decided"]["adjustments"]
    # N = 2,500 thousand = 2.5e6; interest on it at the bill rate 0.04 = 1.0e5 (pretax); tau 0.2
    assert (b["excess_cash"], b["k0"], b["x0"], b["tau"], b["bill_rate"]) == (7.0e6, 3.28e6, 10.176e6, 0.2, 0.04)
    assert a["excess_cash_before"] == 7.0e6 and a["excess_cash_after"] == pytest.approx(4.5e6)
    assert a["k0_before"] == 3.28e6 and a["k0_after"] == pytest.approx(3.18e6) and a["k0_interest"] == b["k0_interest"] == 1.0e6
    assert a["x0_before"] == 10.176e6 and a["x0_after"] == pytest.approx(10.256e6) and a["cash_interest_returned"] == pytest.approx(1.0e5)
    assert a["cash_not_free"]["amount"] == 2.5e6 and a["cash_not_free"]["quotes"] == [{"id": "F2", "quote": Q_CASH}] and a["base_year_one_offs"] == []
    assert a["stamps"] == ["cash_not_free_taken_out_of_excess_cash", "interest_on_cash_not_free_returned_to_the_earnings_base", "ronic0_not_readjusted"]
    # the value is the desk's on the hand-adjusted copy; bear and bull the same copy
    hb = hand_base(b, excess_cash=4.5e6, k0=3.18e6, x0=10.256e6)
    inp, rng = reply()["inputs"], reply()["ranges"]
    assert res["values"]["base"] == pytest.approx(D.value_inputs(hb, C.R, inp)[0], rel=1e-12)
    assert res["values"]["bear"] == pytest.approx(D.value_inputs(hb, C.R, D.scenario_inputs(inp, rng, 0))[0], rel=1e-12)
    assert res["values"]["bull"] == pytest.approx(D.value_inputs(hb, C.R, D.scenario_inputs(inp, rng, 1))[0], rel=1e-12)
    assert res["values"]["base"] != D.value_inputs(b, C.R, inp)[0]
    # the pinned base is stored unchanged, the reference value is on the unadjusted base
    assert res["base"] == b and res["decided"]["value_at_old_defaults"] == D.old_defaults(b, bar, C.R)[0]
    # the bridge stays exact: the base-year operating margin bridges to the adjusted x0
    ab, adj = D.adjust_base(b, a["cash_not_free"], [])
    assert inputs.bridge_x_margin(ab, [b["op_margin0"]], [b["R0"]])[0] * b["R0"] == pytest.approx(ab["x0"], rel=1e-12) and ab["m0"] == pytest.approx(ab["x0"] / b["R0"])
    assert ab["cash_interest_pretax"] == pytest.approx(b["cash_interest_pretax"] - 1.0e5) and adj == a


def test_the_desk_value_moves_by_the_cash_taken_out_at_face_plus_the_earnings_change(tmp_path, monkeypatch):
    """Value per share = (equity + excess cash) / shares: removing N of cash lowers it by N / shares at face; the return of the interest to the earnings raises the equity."""
    res, b, bar, sent = adj_run(tmp_path, monkeypatch, {"cash_not_free": cash()})
    inp = reply()["inputs"]
    only_cash = D.value_inputs(hand_base(b, excess_cash=4.5e6), C.R, inp)[0]
    assert only_cash == pytest.approx(D.value_inputs(b, C.R, inp)[0] - 2.5e6 / b["shares"], rel=1e-12)
    assert res["values"]["base"] > only_cash                      # the interest on that cash is now earned in the operating base, not dropped


def test_base_year_one_offs_are_taken_out_of_the_held_constant_and_not_its_interest_part(tmp_path, monkeypatch):
    offs = [one_off(1.2, "charge", Q_LOSS), one_off(0.4, "gain", Q_GAIN)]
    res, b, bar, sent = adj_run(tmp_path, monkeypatch, {"base_year_one_offs": offs})
    a = res["decided"]["adjustments"]
    # charges 1.2e6 less gains 0.4e6 = 0.8e6 of pretax earnings put back: k0 3.28e6 - 0.8e6; x0 10.176e6 + 0.8e6 x 0.8; excess cash untouched
    assert res["status"] == "ok" and a["k0_before"] == 3.28e6 and a["k0_after"] == pytest.approx(2.48e6) and a["k0_interest"] == 1.0e6
    assert a["x0_after"] == pytest.approx(10.816e6) and a["excess_cash_after"] == a["excess_cash_before"] == 7.0e6 and a["cash_interest_returned"] == 0.0
    assert (a["one_offs_charge"], a["one_offs_gain"]) == (pytest.approx(1.2e6), pytest.approx(0.4e6)) and a["cash_not_free"] is None
    assert [(o["sign"], o["amount"]) for o in a["base_year_one_offs"]] == [("charge", pytest.approx(1.2e6)), ("gain", pytest.approx(0.4e6))]
    assert a["stamps"] == ["base_year_one_offs_taken_out_of_k0", "ronic0_not_readjusted"]
    hb = hand_base(b, k0=2.48e6, x0=10.816e6)
    assert res["values"]["base"] == pytest.approx(D.value_inputs(hb, C.R, reply()["inputs"])[0], rel=1e-12)
    ab, _ = D.adjust_base(b, None, [dict(o, sign=s) for o, s in zip(a["base_year_one_offs"], ("charge", "gain"))])
    assert inputs.bridge_x_margin(ab, [b["op_margin0"]], [b["R0"]])[0] * b["R0"] == pytest.approx(ab["x0"], rel=1e-12)


def test_removing_a_charge_raises_the_value_and_removing_a_gain_lowers_it(tmp_path, monkeypatch):
    base = D.value_inputs(arrange(tmp_path, monkeypatch)[1], C.R, reply()["inputs"])[0]
    up = adj_run(tmp_path, monkeypatch, {"base_year_one_offs": [one_off(1.2, "charge", Q_LOSS)]})[0]["values"]["base"]
    down = adj_run(tmp_path, monkeypatch, {"base_year_one_offs": [one_off(0.4, "gain", Q_GAIN)]})[0]["values"]["base"]
    assert up > base > down


def test_both_adjustments_together_add_up_on_the_one_copy(tmp_path, monkeypatch):
    offs = [one_off(1.2, "charge", Q_LOSS), one_off(0.4, "gain", Q_GAIN)]
    res, b, bar, sent = adj_run(tmp_path, monkeypatch, {"cash_not_free": cash(), "base_year_one_offs": offs})
    a = res["decided"]["adjustments"]
    assert a["k0_after"] == pytest.approx(3.28e6 - 1.0e5 - 0.8e6) and a["x0_after"] == pytest.approx(10.176e6 + 0.9e6 * 0.8) and a["excess_cash_after"] == pytest.approx(4.5e6)
    assert a["stamps"] == ["cash_not_free_taken_out_of_excess_cash", "interest_on_cash_not_free_returned_to_the_earnings_base", "base_year_one_offs_taken_out_of_k0", "ronic0_not_readjusted"]
    hb = hand_base(b, excess_cash=4.5e6, k0=2.38e6, x0=10.896e6)
    assert res["values"]["base"] == pytest.approx(D.value_inputs(hb, C.R, reply()["inputs"])[0], rel=1e-12)


def test_null_and_empty_adjustments_leave_the_base_and_the_values_exactly_as_they_were(tmp_path, monkeypatch):
    res, b, bar, sent = adj_run(tmp_path, monkeypatch, {})
    a = res["decided"]["adjustments"]
    assert a["cash_not_free"] is None and a["base_year_one_offs"] == [] and a["stamps"] == [] and a["k0_after"] == a["k0_before"] and a["excess_cash_after"] == a["excess_cash_before"]
    assert res["values"]["base"] == D.value_inputs(b, C.R, reply()["inputs"])[0]
    empty = adj_run(tmp_path, monkeypatch, {"base_year_one_offs": []})[0]
    assert empty["status"] == "ok" and empty["values"] == res["values"]


def test_a_reply_of_the_v1_shape_without_the_new_keys_is_invalid_then_repaired(tmp_path, monkeypatch):
    v1 = reply()
    for k in ("cash_not_free", "base_year_one_offs"):
        del v1[k]
    del v1["situation"]["tax_rate_representative"], v1["situation"]["debt_level_representative"]
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [v1, reply()])
    res = run(tmp_path, packet)
    msg = sent[1][3]["content"]
    assert res["status"] == "ok" and res["checked_attempt"] == 2
    assert all(x in msg for x in ("cash_not_free is missing", "base_year_one_offs is missing", "situation.tax_rate_representative must be", "situation.debt_level_representative must be"))
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [v1, v1])
    assert run(tmp_path, packet)["reason"] == "decision_invalid"


def test_a_cash_amount_equal_to_the_cash_counted_as_excess_is_allowed(tmp_path, monkeypatch):
    res, b, *_ = adj_run(tmp_path, monkeypatch, {"cash_not_free": cash(value=7.0, scale="millions", quote="Cash held for customers was 7.0 million")},
                         pk=dict(PK, evidence=[PK["evidence"][0], dict(PK["evidence"][1], text=F2_TEXT + " Cash held for customers was 7.0 million."), PK["evidence"][2]]))
    assert res["status"] == "ok" and res["decided"]["adjustments"]["excess_cash_after"] == 0.0


def test_the_tax_and_debt_flags_are_flags_and_move_no_number(tmp_path, monkeypatch):
    plain = adj_run(tmp_path, monkeypatch, {})[0]
    res = adj_run(tmp_path, monkeypatch, {"situation.tax_rate_representative": {"answer": "no", "why": "A one-time benefit lowered the rate."},
                                          "situation.debt_level_representative": {"answer": "unclear", "why": "Not stated."}})[0]
    fl = res["decided"]["flags"]
    assert "tax_rate_representative_no: A one-time benefit lowered the rate." in fl and not any(x.startswith("debt_level_representative") for x in fl)
    assert res["values"] == plain["values"] and res["decided"]["adjustments"] == plain["decided"]["adjustments"]
    res = adj_run(tmp_path, monkeypatch, {"situation.debt_level_representative": {"answer": "no", "why": "Debt was repaid after year end."}})[0]
    assert "debt_level_representative_no: Debt was repaid after year end." in res["decided"]["flags"] and res["values"] == plain["values"]
    assert plain["decided"]["flags"] == ["quotes_verified: 7 of 7"]


def test_the_second_tax_rate_uses_the_same_adjustments_on_its_own_base(tmp_path, monkeypatch):
    offs = [one_off(1.2, "charge", Q_LOSS)]
    res, b, bar, sent = adj_run(tmp_path, monkeypatch, {"cash_not_free": cash(), "base_year_one_offs": offs}, facts=TS.fb_facts())
    tr, a = res["tax_range"], res["decided"]["adjustments"]
    alt_b = D.vrun.alt_tax_base(TS.fb_facts(), b, 180e6)
    alt_adj, _ = D.adjust_base(alt_b, a["cash_not_free"], [dict(a["base_year_one_offs"][0])])
    assert tr["status_alt"] == "ok" and tr["values"] == res["values"] and tr["values_alt"]["base"] == D.value_inputs(alt_adj, C.R, reply()["inputs"])[0]
    assert alt_adj["tau"] == b["tax_fallback"]["rate_alt"] and alt_adj["k0"] == pytest.approx(alt_b["k0"] - 1.0e5 - 1.2e6)
    assert tr["values_alt"]["base"] != D.value_inputs(alt_b, C.R, reply()["inputs"])[0]


def test_the_report_carries_the_adjustments_of_each_run(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(cash_not_free=cash()), reply()])
    rs = {str(s): D.value(packet, "1", "Industrials", 180e6, family="operating", analysis=AN, seed=s, out_root=tmp_path / "runs", online=False) for s in (1000, 3000)}
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    runs = rep["decided"]["runs"]
    assert runs["1000"]["adjustments"]["excess_cash_after"] == pytest.approx(4.5e6) and runs["3000"]["adjustments"]["cash_not_free"] is None
    json.dumps(rep)


def test_the_overlay_row_keeps_only_the_marker_of_the_decided_method():
    import gemini_ondemand as G
    row = {"valued": True, "value_base": 0.0, "decided": {"method": "decided", "version": "decided.v1", "runs": {"1000": {"inputs": {}}}, "flags": []}}
    out = G.overlay_row(row)
    assert out["decided"] == {"method": "decided", "version": "decided.v1"} and out["value_base"] == 0.0
    assert "runs" in row["decided"]                                  # the report's own object is not touched
    plain = {"valued": True, "decided": None}
    assert G.overlay_row(plain) is plain


# ---- WO_NC10a: the capital events since the base year ------------------------------------------------------------------------------------

F3_TEXT = ("Cash paid for acquisitions, net of cash acquired, was $3.0 million. Repurchases of common stock were $500 thousand. Proceeds from the issuance of common stock "
           "were $0.1 million. A special dividend of $0.4 million was paid. Proceeds from the sale of a business were $0.2 million. There were 10,500,000 shares outstanding "
           "at June 30. Cash paid for acquisitions was $3.1 million in the release.")
QE = {"acquisitions_paid": "Cash paid for acquisitions, net of cash acquired, was $3.0 million", "buybacks_paid": "Repurchases of common stock were $500 thousand",
      "shares_issued_proceeds": "Proceeds from the issuance of common stock were $0.1 million", "special_distributions": "A special dividend of $0.4 million was paid",
      "disposals_received": "Proceeds from the sale of a business were $0.2 million", "shares_outstanding": "There were 10,500,000 shares outstanding"}
PKQ = dict(PK, evidence=PK["evidence"] + [{"fact_id": "F3", "kind": "quarterly_section", "title": "t3", "form": "10-Q", "period": "2026-06-30",
                                          "effective_at": "2026-08-01T00:00:00Z", "source": None, "text": F3_TEXT}])
Q3END = "2026-06-30"


def fig(key, value, scale="millions", quote=None):
    return {"value": value, "scale": scale, "quotes": [{"id": "F3", "quote": quote or QE[key]}]}


def since(**figs):
    """A since_base_year object: the keys given as (value, scale) or a ready object; the rest null."""
    o = {"interim_date": Q3END, **{k: None for k in D.SINCE_KEYS}}
    o.update({k: (fig(k, *v) if isinstance(v, tuple) else v) for k, v in figs.items()})
    return o


FULL = dict(acquisitions_paid=(3.0, "millions"), buybacks_paid=(500, "thousands"), shares_issued_proceeds=(0.1, "millions"), special_distributions=(0.4, "millions"),
            disposals_received=(0.2, "millions"), shares_outstanding=(10_500_000, "units"))


def xb(events=None, shares=10_500_000.0):
    """What facts.capital_events returns for a 10-Q of the year after the base year (events: {event: value}; an event not given is absent)."""
    ev = {k: None for k in ("acquisitions_paid", "buybacks_paid", "shares_issued_proceeds", "disposals_received")}
    ev.update({k: {"value": v, "tag": f"us-gaap:{k}", "accn": "0001-26-000002", "start": "2026-01-01", "end": Q3END, "form": "10-Q", "filed": "2026-08-05", "stamp": None}
               for k, v in (events or {}).items()})
    out = {"fy0": "2025-12-31", "found": True, "absent": None, "accn": "0001-26-000002", "form": "10-Q", "filed": "2026-08-05", "start": "2026-01-01", "end": Q3END,
           "quarter": 2, "events": ev, "absent_events": {k: "no year-to-date value" for k, v in ev.items() if v is None}, "shares_outstanding": None, "shares_absent": None}
    if shares is not None:
        out["shares_outstanding"] = {"value": shares, "tag": "dei:EntityCommonStockSharesOutstanding", "accn": "0001-26-000002", "end": "2026-07-24", "form": "10-Q", "filed": "2026-08-05"}
    return out


XB_ALL = {"acquisitions_paid": 3.0e6, "buybacks_paid": 0.5e6, "shares_issued_proceeds": 0.1e6, "disposals_received": 0.2e6}


def ev_run(tmp_path, monkeypatch, replies, code=None, pk=PKQ, **k):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, replies, pk=pk, **k)
    if code is not None:
        monkeypatch.setattr(D, "code_capital_events", lambda *a, **kw: code)
    return run(tmp_path, packet), b, bar, sent


def ce_of(res):
    return res["decided"]["adjustments"]["capital_events"]


def test_each_event_from_the_xbrl_is_taken_off_the_excess_cash_and_the_arithmetic_matches_a_hand_calculation(tmp_path, monkeypatch):
    res, b, bar, sent = ev_run(tmp_path, monkeypatch, [reply(since_base_year=since(special_distributions=(0.4, "millions")))], code=xb(XB_ALL, shares=10.0e6))
    assert res["status"] == "ok" and len(sent) == 1
    ce = ce_of(res)
    # 7.0 million of excess cash - 3.0 acquired - 0.5 bought back - 0.4 special + 0.1 issued + 0.2 sold = 3.4 million; shares 10.0 million: unchanged
    assert b["excess_cash"] == 7.0e6 and b["shares"] == 10.0e6
    assert ce["excess_cash_before"] == 7.0e6 and ce["excess_cash_after"] == pytest.approx(3.4e6) and ce["net_effect_on_excess_cash"] == pytest.approx(-3.6e6)
    assert res["decided"]["adjustments"]["excess_cash_after"] == pytest.approx(3.4e6) and res["decided"]["adjustments"]["excess_cash_before"] == 7.0e6
    f = ce["figures"]
    assert {k: v["source"] for k, v in f.items()} == {"acquisitions_paid": "xbrl", "buybacks_paid": "xbrl", "shares_issued_proceeds": "xbrl", "special_distributions": "read",
                                                     "disposals_received": "xbrl"}
    assert (f["acquisitions_paid"]["tag"], f["acquisitions_paid"]["accn"], f["acquisitions_paid"]["start"], f["acquisitions_paid"]["end"]) == \
        ("us-gaap:acquisitions_paid", "0001-26-000002", "2026-01-01", Q3END)
    assert f["special_distributions"]["amount"] == pytest.approx(0.4e6) and f["special_distributions"]["quotes"] == [{"id": "F3", "quote": QE["special_distributions"]}]
    assert ce["shares"] == {"before": 10.0e6, "interim": 10.0e6, "source": "xbrl", "replaced": False, "after": 10.0e6}
    hb = hand_base(b, excess_cash=3.4e6)
    inp, rng = reply()["inputs"], reply()["ranges"]
    assert res["values"]["base"] == pytest.approx(D.value_inputs(hb, C.R, inp)[0], rel=1e-12)
    assert res["values"]["bear"] == pytest.approx(D.value_inputs(hb, C.R, D.scenario_inputs(inp, rng, 0))[0], rel=1e-12)
    assert res["values"]["bull"] == pytest.approx(D.value_inputs(hb, C.R, D.scenario_inputs(inp, rng, 1))[0], rel=1e-12)
    assert res["values"]["base"] == pytest.approx(D.value_inputs(b, C.R, inp)[0] - 3.6e6 / b["shares"], rel=1e-12)       # value / share = (equity x factor + excess cash) / shares
    assert res["base"] == b and res["decided"]["value_at_old_defaults"] == D.old_defaults(b, bar, C.R)[0]                 # pinned base stored; the reference stays unadjusted
    ad = res["decided"]["adjustments"]
    assert ad["k0_after"] == b["k0"] and ad["x0_after"] == b["x0"]                                                       # no flow moved


def test_each_event_from_the_read_when_code_found_no_filing(tmp_path, monkeypatch):
    res, b, *_ = ev_run(tmp_path, monkeypatch, [reply(since_base_year=since(**FULL))])
    ce = ce_of(res)
    assert res["status"] == "ok" and all(v["source"] == "read" for v in ce["figures"].values()) and ce["interim_end"] == Q3END
    assert {k: v["amount"] for k, v in ce["figures"].items()} == pytest.approx({"acquisitions_paid": 3.0e6, "buybacks_paid": 0.5e6, "shares_issued_proceeds": 0.1e6,
                                                                                "special_distributions": 0.4e6, "disposals_received": 0.2e6})
    # v3.1: the read's 10.5 million shares (+5%) after net buybacks is more than the events explain: the read-only count is not used
    assert ce["excess_cash_after"] == pytest.approx(3.4e6) and ce["shares"]["source"] == "read" and ce["shares"]["replaced"] is False and ce["shares"]["after"] == b["shares"]
    assert res["values"]["base"] == pytest.approx(D.value_inputs(hand_base(b, excess_cash=3.4e6), C.R, reply()["inputs"])[0], rel=1e-12)
    assert "share_count_from_read_unexplained_base_count_kept" in ce["stamps"] and "shares_from_latest_interim" not in ce["stamps"]


def test_an_event_the_filings_do_not_state_is_taken_as_0_and_stamped_and_a_filed_zero_is_a_value(tmp_path, monkeypatch):
    res, b, *_ = ev_run(tmp_path, monkeypatch, [reply(since_base_year=since(acquisitions_paid=(3.0, "millions")))], code=xb({"buybacks_paid": 0.0}, shares=None))
    ce = ce_of(res)
    assert ce["figures"]["buybacks_paid"]["amount"] == 0.0 and ce["figures"]["buybacks_paid"]["source"] == "xbrl"
    assert [ce["figures"][k]["source"] for k in ("acquisitions_paid", "shares_issued_proceeds", "special_distributions", "disposals_received")] == ["read", "none", "none", "none"]
    assert set(ce["stamps"]) == {"shares_issued_proceeds_not_filed_taken_as_0", "special_distributions_not_filed_taken_as_0", "disposals_received_not_filed_taken_as_0",
                                 "shares_outstanding_at_interim_not_found_base_count_kept"}
    assert ce["excess_cash_after"] == pytest.approx(4.0e6) and ce["shares"]["replaced"] is False and set(ce["stamps"]) <= set(res["decided"]["flags"])


def test_a_read_that_omits_since_base_year_with_an_interim_in_the_packet_gets_one_repair_turn(tmp_path, monkeypatch):
    res, b, bar, sent = ev_run(tmp_path, monkeypatch, [reply(), reply(since_base_year=since(**FULL))])
    assert res["status"] == "ok" and res["checked_attempt"] == 2 and len(sent) == 2
    assert "since_base_year is null, but the evidence holds an interim report for the period ended 2026-06-30" in sent[1][3]["content"]
    assert ce_of(res)["excess_cash_after"] == pytest.approx(3.4e6)
    res2 = ev_run(tmp_path, monkeypatch, [reply(), reply(since_base_year=None)])[0]
    assert res2["status"] == "no_call" and res2["reason"] == "decision_invalid" and "since_base_year is null" in res2["detail"]


def test_a_six_k_interim_item_counts_as_an_interim_and_a_filing_before_the_base_year_end_does_not(tmp_path, monkeypatch):
    six = [dict(PKQ["evidence"][3], fact_id="F3", kind="six_k_interim", form="6-K")]
    assert D.interim_in_packet(dict(PK, evidence=PK["evidence"][:3] + six), "2025-12-31") == "2026-06-30"
    assert D.interim_in_packet(dict(PK, evidence=PK["evidence"][:3] + [dict(six[0], period="2025-09-30", form="10-Q", kind="quarterly_section")]), "2025-12-31") is None
    assert D.interim_in_packet(PK, "2025-12-31") is None
    res = ev_run(tmp_path, monkeypatch, [reply(), reply(since_base_year=since())], pk=dict(PK, evidence=PK["evidence"][:3] + six))[0]
    assert res["status"] == "ok" and res["checked_attempt"] == 2


def test_null_since_base_year_is_allowed_where_the_packet_holds_no_interim_and_the_value_is_v2s(tmp_path, monkeypatch):
    plain, b, bar, sent = ev_run(tmp_path, monkeypatch, [reply()], pk=PK)
    assert plain["status"] == "ok" and plain["checked_attempt"] == 1 and len(sent) == 1
    a = plain["decided"]["adjustments"]
    assert a["capital_events"] is None and a["stamps"] == [] and a["excess_cash_after"] == a["excess_cash_before"]
    assert plain["values"]["base"] == D.value_inputs(b, C.R, reply()["inputs"])[0] and plain["decided"]["flags"] == ["quotes_verified: 7 of 7"]
    explicit = ev_run(tmp_path, monkeypatch, [reply(since_base_year=None)], pk=PK)[0]
    assert explicit["values"] == plain["values"] and explicit["decided"]["adjustments"] == a
    # a name with a filed 10-Q but no interim item in the packet takes the events from the XBRL alone
    res = ev_run(tmp_path, monkeypatch, [reply()], code=xb(XB_ALL, shares=10.0e6), pk=PK)[0]
    assert res["status"] == "ok" and ce_of(res)["excess_cash_after"] == pytest.approx(7.0e6 - 3.0e6 - 0.5e6 + 0.1e6 + 0.2e6)


def test_code_wins_and_a_disagreement_over_2_percent_is_flagged(tmp_path, monkeypatch):
    sby = since(acquisitions_paid=(3.1, "millions", "Cash paid for acquisitions was $3.1 million"), buybacks_paid=(500, "thousands"), shares_outstanding=(10_500_000, "units"))
    res, b, *_ = ev_run(tmp_path, monkeypatch, [reply(since_base_year=sby)], code=xb({"acquisitions_paid": 3.2e6, "buybacks_paid": 0.5e6}, shares=10_500_000.0))
    ce = ce_of(res)
    # 3.1 against 3.2 is 3.1% of the xbrl figure and smaller: flagged, and the figure used is the xbrl one; 500 thousand against 500 thousand: no flag
    assert ce["figures"]["acquisitions_paid"]["amount"] == 3.2e6 and ce["figures"]["acquisitions_paid"]["read_amount"] == pytest.approx(3.1e6)
    assert ce["flags"][0] == "capital_event_read_differs_from_xbrl: acquisitions_paid xbrl 3,200,000, read 3,100,000" and not any("buybacks_paid" in x for x in ce["flags"])
    assert not any("shares_outstanding" in x for x in ce["flags"]) and ce["flags"][0] in res["decided"]["flags"]
    tol = ce_of(ev_run(tmp_path, monkeypatch, [reply(since_base_year=since(acquisitions_paid=(3.0, "millions"), shares_outstanding=(10_500_000, "units")))],
                       code=xb({"acquisitions_paid": 2.95e6}))[0])
    assert not any(x.startswith("capital_event_read_differs") for x in tol["flags"])                         # 1.7%: inside the 2%
    sh = ce_of(ev_run(tmp_path, monkeypatch, [reply(since_base_year=since(shares_outstanding=(10_500_000, "units")))], code=xb({}, shares=10_000_000.0))[0])
    assert any(x.startswith("capital_event_read_differs_from_xbrl: shares_outstanding") for x in sh["flags"]) and sh["shares"]["after"] == 10_000_000.0


def test_a_checked_read_figure_above_the_xbrl_one_is_used(tmp_path, monkeypatch):
    # v3.1: the business-combination tag filed at 0 while the cash-flow statement prints a payment for asset acquisitions; and a read above a nonzero tag
    zero = ce_of(ev_run(tmp_path, monkeypatch, [reply(since_base_year=since(acquisitions_paid=(3.1, "millions", "Cash paid for acquisitions was $3.1 million")))],
                        code=xb({"acquisitions_paid": 0.0}))[0])
    f = zero["figures"]["acquisitions_paid"]
    assert f["source"] == "read" and f["amount"] == pytest.approx(3.1e6) and f["xbrl_amount"] == 0.0 and f["read_above_xbrl"] is True
    assert zero["flags"][0] == "capital_event_read_differs_from_xbrl: acquisitions_paid xbrl 0, read 3,100,000"
    above = ce_of(ev_run(tmp_path, monkeypatch, [reply(since_base_year=since(acquisitions_paid=(3.1, "millions", "Cash paid for acquisitions was $3.1 million")))],
                         code=xb({"acquisitions_paid": 3.0e6}))[0])
    assert above["figures"]["acquisitions_paid"]["source"] == "read" and above["figures"]["acquisitions_paid"]["amount"] == pytest.approx(3.1e6)
    assert above["excess_cash_after"] == pytest.approx(above["excess_cash_before"] - 3.1e6)


def test_with_the_xbrl_there_a_read_figure_that_fails_its_check_is_dropped_not_repaired(tmp_path, monkeypatch):
    # v3.1: a quote whose digits are not in the filing; with the 10-Q's XBRL the run is ok in one turn, XBRL used, the drop stamped
    bad = since(acquisitions_paid=(9.9, "millions", "Cash paid for acquisitions was $3.1 million"))
    res, *_rest, sent = ev_run(tmp_path, monkeypatch, [reply(since_base_year=bad)], code=xb({"acquisitions_paid": 3.0e6}))
    ce = ce_of(res)
    assert res["status"] == "ok" and len(sent) == 1 and ce["figures"]["acquisitions_paid"] == dict(ce["figures"]["acquisitions_paid"], source="xbrl", amount=3.0e6)
    assert "acquisitions_paid_read_figure_failed_its_check_dropped" in ce["stamps"]
    # with no XBRL the same figure is a problem: a repair turn, and with no good reply, no value
    res2 = ev_run(tmp_path, monkeypatch, [reply(since_base_year=bad)] * 2, code={"found": False, "absent": "no 10-Q of year 1 effective at T"})[0]
    assert res2["status"] == "no_call" and "since_base_year.acquisitions_paid" in res2["detail"]


def test_a_cover_page_with_a_count_per_class_keeps_the_base_share_count(tmp_path, monkeypatch):
    code = dict(xb({}), shares_outstanding=None, shares_absent="the cover page of 0001-26-000002 gives 2 different counts (classes of stock): [1.0, 2.0]")
    ce = ce_of(ev_run(tmp_path, monkeypatch, [reply(since_base_year=since(shares_outstanding=(10_500_000, "units")))], code=code)[0])
    assert ce["shares"]["replaced"] is False and ce["shares"]["after"] == ce["shares"]["before"] and "shares_multi_class_base_count_kept" in ce["stamps"]


def test_the_interim_share_count_replaces_the_base_count_only_above_1_percent_and_is_stamped(tmp_path, monkeypatch):
    small = ce_of(ev_run(tmp_path, monkeypatch, [reply()], code=xb({}, shares=10.09e6), pk=PK)[0])
    assert small["shares"]["replaced"] is False and small["shares"]["after"] == 10.0e6 and "shares_from_latest_interim" not in small["stamps"]
    big, b, *_ = ev_run(tmp_path, monkeypatch, [reply()], code=xb({}, shares=10.2e6), pk=PK)
    ce = ce_of(big)
    assert ce["shares"]["replaced"] is True and ce["shares"]["after"] == 10.2e6 and "shares_from_latest_interim" in ce["stamps"]
    assert big["values"]["base"] == pytest.approx(D.value_inputs(hand_base(b, shares=10.2e6), C.R, reply()["inputs"])[0], rel=1e-12) and big["base"] == b


def test_a_share_count_change_the_events_do_not_explain_is_flagged_and_one_they_explain_is_not(tmp_path, monkeypatch):
    # price 12.5: 500 thousand bought back less 0.1 million issued is 0.4 million / (12.5 x 0.5 to 12.5 x 2) = 16,000 to 64,000 fewer shares; slack 1% of 10 million
    unexplained = ce_of(ev_run(tmp_path, monkeypatch, [reply()], code=xb(XB_ALL, shares=10.5e6), pk=PK)[0])
    assert any(x.startswith("share_count_change_unexplained: shares 10,000,000 to 10,500,000 (+500,000)") for x in unexplained["flags"])
    assert unexplained["shares"]["price_used"] == 12.5 and unexplained["shares"]["explained_range"] == pytest.approx([-64000.0, -16000.0])
    explained = ce_of(ev_run(tmp_path, monkeypatch, [reply()], code=xb({"buybacks_paid": 5.0e6, "shares_issued_proceeds": 0.1e6}, shares=9.6e6), pk=PK)[0])
    assert explained["shares"]["replaced"] is True and not any(x.startswith("share_count_change_unexplained") for x in explained["flags"])
    no_price = dict(PK, evidence=[PK["evidence"][0], PK["evidence"][1], dict(PK["evidence"][2], text="sector: Industrials\nrank: 3")])
    np_ = ce_of(ev_run(tmp_path, monkeypatch, [reply()], code=xb({}, shares=10.5e6), pk=no_price)[0])
    assert "share_change_not_assessed_no_price" in np_["stamps"] and not any(x.startswith("share_count_change") for x in np_["flags"])


def test_events_summing_to_5_percent_of_the_market_cap_are_flagged(tmp_path, monkeypatch):
    small = ce_of(ev_run(tmp_path, monkeypatch, [reply()], code=xb(XB_ALL, shares=10.0e6), pk=PK)[0])
    assert small["gross_events"] == pytest.approx(3.8e6) and not any(x.startswith("capital_events_over_5pct") for x in small["flags"])      # 2.1% of 180 million
    big = ev_run(tmp_path, monkeypatch, [reply()], code=xb({"acquisitions_paid": 9.0e6}, shares=10.0e6), pk=PK)[0]               # 5.0% exactly
    fl = ce_of(big)["flags"]
    assert fl == ["capital_events_over_5pct_of_market_cap: events sum to 9,000,000, 5.0% of the market cap 180,000,000"] and fl[0] in big["decided"]["flags"]
    assert big["decided"]["adjustments"]["excess_cash_after"] == pytest.approx(-2.0e6) and big["status"] == "ok"     # a purchase above the cash is a debt claim, not a refusal


@pytest.mark.parametrize("label,sby,expect", [
    ("digits not in the quote", since(acquisitions_paid=(3.5, "millions")), "the number 3.5 does not appear in any quote"),
    ("quote not in the item", since(acquisitions_paid=(3.0, "millions", "Cash paid for acquisitions was three million")), "no quote found word for word"),
    ("zero", since(acquisitions_paid=(0, "millions")), "value must be a number above 0"),
    ("bad scale", since(acquisitions_paid=(3.0, "lakhs")), "scale must be one of"),
    ("bad date", dict(since(), interim_date="June"), "interim_date must be a date"),
    ("date before the base year", dict(since(), interim_date="2025-06-30"), "is not after the base year"),
    ("not an object", "none", "since_base_year must be null or an object"),
    ("shares not in the quote", since(shares_outstanding=(10_400_000, "units")), "since_base_year.shares_outstanding: the number 10400000"),
])
def test_a_figure_that_fails_its_check_goes_to_the_repair_turn(tmp_path, monkeypatch, label, sby, expect):
    res, b, bar, sent = ev_run(tmp_path, monkeypatch, [reply(since_base_year=sby), reply(since_base_year=since(**FULL))])
    assert res["status"] == "ok" and res["checked_attempt"] == 2, label
    assert expect in sent[1][3]["content"], label


def test_a_disposal_is_the_other_sign_and_a_negative_filed_figure_is_stamped_not_clamped(tmp_path, monkeypatch):
    up = ce_of(ev_run(tmp_path, monkeypatch, [reply()], code=xb({"disposals_received": 2.0e6}, shares=10.0e6), pk=PK)[0])
    assert up["excess_cash_after"] == pytest.approx(9.0e6) and up["net_effect_on_excess_cash"] == pytest.approx(2.0e6)
    code = xb({"buybacks_paid": -1.0e6}, shares=10.0e6)
    code["events"]["buybacks_paid"]["stamp"] = "buybacks_paid_negative_as_filed"
    neg = ce_of(ev_run(tmp_path, monkeypatch, [reply()], code=code, pk=PK)[0])
    assert neg["figures"]["buybacks_paid"]["amount"] == -1.0e6 and "buybacks_paid: buybacks_paid_negative_as_filed" in neg["stamps"] and neg["excess_cash_after"] == pytest.approx(8.0e6)


def test_the_events_apply_on_the_same_copy_after_the_cash_not_free_step_and_with_the_one_offs(tmp_path, monkeypatch):
    res, b, *_ = ev_run(tmp_path, monkeypatch, [reply(cash_not_free=cash(), base_year_one_offs=[one_off(1.2, "charge", Q_LOSS)], since_base_year=since(**FULL))],
                        pk=dict(PKQ, evidence=[PKQ["evidence"][0], PKQ["evidence"][1], PKQ["evidence"][2], PKQ["evidence"][3]]))
    a = res["decided"]["adjustments"]
    # 7.0 - 2.5 (cash not free) - 3.0 - 0.5 - 0.4 + 0.1 + 0.2 = 0.9 million; k0 and x0 as in v2 for the cash and the charge; the read's 10.5 million
    # shares after net buybacks is more than the events explain, so the base count stays (v3.1)
    assert res["status"] == "ok" and a["excess_cash_after"] == pytest.approx(0.9e6) and a["capital_events"]["excess_cash_before"] == pytest.approx(4.5e6)
    assert a["k0_after"] == pytest.approx(3.28e6 - 1.0e5 - 1.2e6) and a["x0_after"] == pytest.approx(10.176e6 + 1.3e6 * 0.8)
    hb = hand_base(b, excess_cash=0.9e6, k0=3.28e6 - 1.3e6, x0=10.176e6 + 1.04e6)
    assert res["values"]["base"] == pytest.approx(D.value_inputs(hb, C.R, reply()["inputs"])[0], rel=1e-12)
    assert "share_count_from_read_unexplained_base_count_kept" in a["stamps"] and "cash_not_free_taken_out_of_excess_cash" in a["stamps"]


def test_the_second_tax_rate_carries_the_events(tmp_path, monkeypatch):
    res, b, *_ = ev_run(tmp_path, monkeypatch, [reply(since_base_year=since(**FULL))], facts=TS.fb_facts())
    tr = res["tax_range"]
    ev = D.resolve_events({"found": False}, D.read_events(res["inputs"], b, {"F3": F3_TEXT}, Q3END)[1], 180e6, 12.5)
    alt_b = D.vrun.alt_tax_base(TS.fb_facts(), b, 180e6)
    alt, _ = D.adjust_base(alt_b, None, [], ev)
    assert tr["status_alt"] == "ok" and tr["values_alt"]["base"] == D.value_inputs(alt, C.R, reply()["inputs"])[0]
    assert alt["excess_cash"] == pytest.approx(alt_b["excess_cash"] - 3.6e6) and alt["shares"] == alt_b["shares"]       # v3.1: the read-only count is unexplained
    assert tr["values_alt"]["base"] != D.value_inputs(alt_b, C.R, reply()["inputs"])[0]


def test_the_report_carries_the_capital_events_of_each_run(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(since_base_year=since(**FULL)), reply(since_base_year=since(**FULL))], pk=PKQ)
    rs = {str(s): D.value(packet, "1", "Industrials", 180e6, family="operating", analysis=AN, seed=s, out_root=tmp_path / "runs", online=False) for s in (1000, 3000)}
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    ce = rep["decided"]["runs"]["1000"]["adjustments"]["capital_events"]
    assert ce["excess_cash_after"] == pytest.approx(3.4e6) and ce["interim_end"] == Q3END
    json.dumps(rep)


def test_the_report_quotes_the_share_count_its_values_are_per(tmp_path, monkeypatch):
    # v3.1: the 10-Q's cover count (9.0 million against the base's 10.0) replaces the base count in the value; the report's filed_shares and equity
    # value are on that count, so the site's conversion to the quoted unit (equity value / quoted shares) is not made on a stale count
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), reply()], pk=PK)
    monkeypatch.setattr(D, "code_capital_events", lambda *a, **kw: xb({"buybacks_paid": 12.0e6}, shares=9.0e6))
    rs = {str(s): D.value(packet, "1", "Industrials", 180e6, family="operating", analysis=AN, seed=s, out_root=tmp_path / "runs", online=False) for s in (1000, 3000)}
    assert all(D.valued_shares(x) == 9.0e6 and x["base"]["shares"] == b["shares"] != 9.0e6 for x in rs.values())
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    assert rep["filed_shares"] == 9.0e6 and rep["equity_value"] == pytest.approx(rep["value_per_filed_share"]["base"] * 9.0e6, rel=1e-12)


def test_code_capital_events_reads_the_stored_facts_and_a_store_miss_is_not_found(monkeypatch):
    from datetime import datetime, timezone
    T = datetime(2026, 11, 18, tzinfo=timezone.utc)
    got = {}
    monkeypatch.setattr(D.facts, "fetch", lambda cik, t, online, root=None: got.update(cik=cik, online=online) or ({"facts": {}}, {"filings": {"recent": {}}}, {}))
    out = D.code_capital_events("1", T, "2025-12-31")
    assert got == {"cik": "1", "online": False} and out["found"] is False and out["absent"] == "no 10-Q of year 1 effective at T"

    def miss(*a, **k):
        raise D.sec_store.NotInStore("x")
    monkeypatch.setattr(D.facts, "fetch", miss)
    assert D.code_capital_events("1", T, "2025-12-31") == {"fy0": "2025-12-31", "found": False, "absent": "companyfacts_not_stored: NotInStore"}


def test_packet_price_reads_the_screener_row():
    assert D.packet_price(PK) == 12.5 and D.packet_price({"evidence": []}) is None


def test_interim_cash_flow_in_packet():
    """A figure absent because the interim's cash-flow statement is absent is flagged, not taken silently as a zero."""
    ev = lambda kind, period, text, form=None: {"kind": kind, "period": period, "text": text, "form": form}
    with_cf = {"evidence": [ev("six_k_interim", "2026-09-30", "Cash flows from investing activities | (1,000)")]}
    cut = {"evidence": [ev("six_k_interim", "2026-09-30", "Revenue rose; outlook updated")]}
    old = {"evidence": [ev("six_k_interim", "2025-09-30", "Cash flows from investing activities")]}
    assert D.interim_cash_flow_in_packet(with_cf, "2025-12-31")
    assert not D.interim_cash_flow_in_packet(cut, "2025-12-31")
    assert not D.interim_cash_flow_in_packet(old, "2025-12-31")


def test_a_wait_with_both_arms_low_ends_on_the_fallback_arm_once_its_allowance_is_back(monkeypatch):
    left = {"gemini": 0.0, "sonnet": 0.0}
    monkeypatch.setattr(G, "meter", lambda: {k: (left[G.ARM], None) for k in G.FLOORS})
    monkeypatch.setattr(G, "log", lambda msg: None)
    naps = []
    monkeypatch.setattr(G.time, "sleep", lambda s: (naps.append(s), left.update(sonnet=0.5)))      # the fallback's allowance resets during the wait
    try:
        m = G.wait_for_quota("gemini")
        assert G.ARM == "sonnet" and len(naps) == 1 and all(v[0] == 0.5 for v in m.values())
    finally:
        G.set_arm("gemini")


# ---- the request fits the reader's channel (2026-11-26) -------------------------------------------------------------------------------

def _build(p):
    return [{"role": "system", "content": "S" * 10}, {"role": "user", "content": "E" * 100 + "\nPRIOR\n" + p + "\nTASK"}]


def test_a_request_under_the_limit_or_with_no_limit_is_sent_whole(monkeypatch):
    prior = "- [t1] one\n- [t2] two"
    monkeypatch.setattr(runner, "PROMPT_BYTE_LIMIT", None, raising=False)
    assert D.fitted(_build, prior) == (_build(prior), 0, True)
    monkeypatch.setattr(runner, "PROMPT_BYTE_LIMIT", 10_000, raising=False)
    assert D.fitted(_build, prior) == (_build(prior), 0, True)


def test_a_request_over_the_limit_loses_the_last_notes_of_the_prior_read_and_keeps_its_task(monkeypatch):
    notes = [f"- [t{i}] note {i} " + "x" * 50 + "\nits second line" for i in range(10)]
    prior = "\n".join(notes)
    whole = sum(len(m["content"]) for m in _build(prior))
    monkeypatch.setattr(runner, "PROMPT_BYTE_LIMIT", whole - 100, raising=False)
    msgs, cut, fits = D.fitted(_build, prior)
    user = msgs[1]["content"]
    assert fits and 1 <= cut < 10 and sum(len(m["content"]) for m in msgs) <= whole - 100 and user.endswith("\nTASK")
    assert all(n in user for n in notes[:10 - cut]) and not any(n in user for n in notes[10 - cut:]) and D.LEFT_OUT.format(n=cut) in user     # whole notes go, the last ones first


def test_a_request_too_long_even_with_no_note_is_a_no_call_and_is_not_sent(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()])
    monkeypatch.setattr(runner, "PROMPT_BYTE_LIMIT", 500, raising=False)
    res = run(tmp_path, packet)
    assert res["status"] == "no_call" and res["reason"] == "request_too_long" and sent == [] and qwen_site.NO_VALUE["request_too_long"]


def test_the_notes_left_out_are_recorded_on_the_attempt(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), reply()])
    monkeypatch.setattr(runner, "PROMPT_BYTE_LIMIT", None, raising=False)
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and "prior_notes_left_out" not in res["attempts"][0]
    full = sum(len(m["content"].encode("utf-8")) for m in sent[0])
    monkeypatch.setattr(runner, "PROMPT_BYTE_LIMIT", full - 1, raising=False)
    res = run(tmp_path, packet, seed=3000)
    assert res["status"] == "ok" and res["attempts"][0]["prior_notes_left_out"] == 1 and D.LEFT_OUT.format(n=1) in sent[1][1]["content"]
