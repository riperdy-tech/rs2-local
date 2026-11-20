"""WO_NC9 part B: the cloud read decides the valuation inputs of a bank or an insurer (decided_financial.py, the report row in qwen_ondemand.report, the
switch in gemini_ondemand.analyze, the shadow). Synthetic data only; the model call is stubbed (runner.call) and every run folder is a temp dir."""
import copy
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decided_financial as DF  # noqa: E402
import decided_shadow as S  # noqa: E402
import decided_value as D  # noqa: E402
import gemini_ondemand as G  # noqa: E402
import qwen_ondemand as Q  # noqa: E402
import qwen_site  # noqa: E402
import test_decided_shadow as TSH  # noqa: E402
import test_decided_value as T  # noqa: E402
from qwen_c.tests import test_value_fin as F  # noqa: E402
from qwen_c.value import checks, desk, forecast_fin, inputs, menu  # noqa: E402

R = F.R
QUOTE, PK = T.QUOTE, T.PK
UNSUPPORTED, AN = T.UNSUPPORTED, T.AN


def reply(**over):
    o = {"situation": {"institution": "bank", "roe_position": "The return is steady.", "base_year_representative": "yes", "capital_constrained": "no", "why": "A stable year."},
         "inputs": {"roe": [0.102, 0.102, 0.102, 0.102, 0.102], "book_growth": [0.05, 0.05, 0.05, 0.05, 0.05], "long_run_roe": 0.104, "terminal_growth": 0.03, "fade_years": 10},
         "ranges": {"long_run_roe": [0.09, 0.13], "book_growth_y3": [0.03, 0.07], "terminal_growth": [0.02, 0.035]},
         "reasons": {k: {"why": f"Because of {k}.", "quotes": [{"id": "F1", "quote": QUOTE}]} for k in DF.INPUT_KEYS},
         "biggest_risks": [{"risk": "Credit losses rise.", "input_hit": "roe", "bear_value": 0.08}], "confidence": "medium"}
    for path, v in over.items():                       # "inputs.fade_years": 30
        node = o
        *head, last = path.split(".")
        for h in head:
            node = node[h]
        node[last] = v
    return o


def arrange(tmp_path, monkeypatch, replies=(), facts=None, pk=PK):
    f = facts or dict(F.bank_facts(), eps_diluted={"values": [{"end": F.ENDS[-1], "value": 1.28, "tag": "T", "form": "10-K"}]})      # WO_UV2: a filed EPS proves the count, so no unproven-count stamp rides in the flags
    b = dict(inputs.base_financial(f), stub_days=0, g_anchor=0.04)
    bar = forecast_fin.record_bar(b["record"]["roe"])
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps(pk), encoding="utf-8")
    prepared = []
    monkeypatch.setattr(DF.vrun, "prepare", lambda *a, **k: prepared.append(k) or (f, b, bar, forecast_fin.record_items(f, b), R, dict(F.PROV), sorted(b["record"]["common_equity"])))
    return packet, b, bar, T.stub(monkeypatch, list(replies)), prepared


def run(tmp_path, packet, seed=1000, family="financial", **k):
    return DF.value(packet, "1", "Banks", 0.0, family=family, analysis=AN, seed=seed, out_root=tmp_path / "runs", online=False, **k)


# ---- the prompt ---------------------------------------------------------------------------------------------------------------------

def test_the_prompt_text_is_pinned():
    """Changing what the model is told is a versioned decision (non-negotiable 7): re-pin this hash and bump DECIDED_VERSION together."""
    assert hashlib.sha256((DF.SYSTEM + "\n" + DF.TASK).encode()).hexdigest() == "77fc56e81d40fec9ce26734d1273e656768329f942948d136220be020ef9740f"
    assert "1 in 4 chance of being undershot" in DF.TASK and "1 in 4 chance of being overshot" in DF.TASK and "Do not quote the PRIOR READ" in DF.TASK
    assert DF.METHOD == "decided.v1" == D.METHOD and DF.DECIDED_VERSION.startswith("decided.fin.v1") and DF.FAMILIES == ("financial",)


def test_the_message_carries_the_packet_masked_the_record_of_every_year_the_supported_read_and_the_task(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()])
    run(tmp_path, packet)
    sysm, user = sent[0]
    assert sysm == {"role": "system", "content": DF.SYSTEM} and len(sent[0]) == 2
    u = user["content"]
    assert T.F1_TEXT in u and "price: 12.5" not in u and "marketCap" not in u and "price as-of" not in u            # prices masked
    assert "BASE RATES" not in u                                                                                  # none is measured for returns on equity
    assert "2020-12-31 | $100.0 million | $0.0 million | $100.0 million | n/a | n/a | n/a" in u
    assert "2025-12-31 | $128.0 million | $0.0 million | $128.0 million | $12.8 million | 0.1049 | 0.0492" in u         # all six year ends of the base's record
    assert u.count(" | $") >= 6 and "growth of common equity" in u and "return on opening common equity" in u
    assert f"common equity at its end, which opens year 1, $128.0 million; income to common $12.8 million; return on opening common equity {b['roe0']:.4f}" in u
    assert f"median {bar['median']:.4f}, p75 {bar['p75']:.4f}, max {bar['max']:.4f}, last {bar['last']:.4f}" in u and f"Cost of equity r {R:.4f}" in u
    assert "A supported claim about the business. Mechanism: It sells things." in u and UNSUPPORTED not in u
    assert "PRIOR READ (another analyst's notes, unverified; not evidence, not to be quoted)" in u and u.rstrip().endswith('"confidence": "low|medium|high"}')


def test_a_preferred_stock_and_aoci_are_stated_in_the_record():
    pref = dict(F.bank_facts(), preferred_equity={"values": [{"end": e, "value": 10e6} for e in F.ENDS]}, preferred_dividends=F.series([0.5] * 5))
    b = dict(inputs.base_financial(pref), stub_days=0, g_anchor=0.04)
    bar = forecast_fin.record_bar(b["record"]["roe"])
    text, rec = DF.record_text(pref, b, bar, R, F.PROV)
    assert "Preferred stock is taken out of book equity (preferred_subtracted_at_carrying_value)" in text
    assert "2025-12-31 | $128.0 million | $10.0 million | $118.0 million |" in text and rec["roe"] == b["record"]["roe"]
    b2 = dict(b, stamps=b["stamps"] + ["aoci_in_book_not_separated:-0.050"])
    assert "its share of book equity -0.050" in DF.record_text(pref, b2, bar, R, F.PROV)[0]


# ---- the numeric route ----------------------------------------------------------------------------------------------------------------

def menu_inputs(b, bar, over=None):
    """(the menu's value, the numeric route's inputs) of the record-neutral financial reply, or of it with `over` (resolved numbers replaced)."""
    m = menu.menus(b, bar, R, "financial")
    nb = menu.neutral_base("financial", m)
    nums = menu.resolve(nb, {}, m, over)
    sc = menu.scenario(nb, nums, m)
    path, _ = forecast_fin.build_path(sc, bar)
    inp = forecast_fin.assemble(sc, b, bar, r=R)
    menu_value = forecast_fin.value(inp)["value_per_share"]
    return menu_value, {"roe": [y["roe"] for y in path], "book_growth": [y["book_growth"] for y in path], "long_run_roe": sc["long_run_roe"],
                        "terminal_growth": sc["terminal_g"], "fade_years": sc["fade_years"]}


@pytest.mark.parametrize("stub_days", [0, 200])
@pytest.mark.parametrize("over", [None, {"roe.y1": 0.13, "book_growth.y1": 0.08, "normalized.roe": 0.12, "terminal_g": 0.02, "fade_years": 15}])
def test_the_menus_own_numbers_through_the_numeric_route_give_the_menus_value(over, stub_days):
    f = F.bank_facts()
    b = dict(inputs.base_financial(f), stub_days=stub_days, g_anchor=0.04)
    bar = forecast_fin.record_bar(b["record"]["roe"])
    menu_value, inp = menu_inputs(b, bar, over)
    assert len(inp["roe"]) == len(inp["book_growth"]) == 5
    assert DF.value_inputs(b, R, inp)[0] == pytest.approx(menu_value, rel=1e-12)
    if over is None:
        assert DF.old_defaults(b, bar, R)[0] == pytest.approx(menu_value, rel=1e-12) and DF.old_defaults(b, bar, R)[0] == checks._neutral_fin(b, bar, R)[0]
        assert len(set(inp["roe"])) > 1 or inp["roe"][0] == bar["median"]                        # the neutral path is the record median


def test_the_numeric_route_runs_v1_and_the_desks_own_arithmetic_on_the_pinned_base(monkeypatch):
    b = dict(inputs.base_financial(F.bank_facts()), stub_days=0, g_anchor=0.04)
    inp = reply()["inputs"]
    seen = []
    real = checks._recompute_fin
    monkeypatch.setattr(DF.checks, "_recompute_fin", lambda *a, **k: seen.append(a) or real(*a, **k))
    v, res = DF.value_inputs(b, R, inp)
    assert seen and res["route"] == "financial" and v == res["value_per_share"]
    monkeypatch.setattr(DF.checks, "_recompute_fin", lambda *a, **k: (_ for _ in ()).throw(AssertionError("V1: broken")))
    with pytest.raises(AssertionError):
        DF.value_inputs(b, R, inp)


def test_the_book_path_starts_from_the_base_and_year_5s_growth_goes_to_the_desk():
    b = dict(inputs.base_financial(F.bank_facts()), stub_days=0, g_anchor=0.04)
    inp = reply(**{"inputs.book_growth": [0.10, 0.0, 0.0, 0.0, 0.0]})["inputs"]
    base = DF.value_inputs(b, R, inp)[0]
    assert DF.value_inputs(b, R, dict(inp, book_growth=[0.10, 0.0, 0.0, 0.0, 0.2]))[0] != base      # g5 is used (R_6 = R_5 (1 + g5))
    assert DF.value_inputs(b, R, dict(inp, book_growth=[0.10, 0.0, 0.0, 0.0, 0.0], roe=[0.2] * 5))[0] > base


# ---- one run ---------------------------------------------------------------------------------------------------------------------

def test_a_valid_reply_is_valued_at_base_bear_and_bull_and_nothing_the_read_gave_is_changed(tmp_path, monkeypatch):
    packet, b, bar, sent, prepared = arrange(tmp_path, monkeypatch, [reply()])
    res = run(tmp_path, packet)
    inp, rng = reply()["inputs"], reply()["ranges"]
    assert res["status"] == "ok" and len(sent) == 1 and res["versions"]["method"] == "decided.v1" and res["checks"]["prob"] == checks.PROB
    assert res["route"] == "financial" and res["decided"]["route"] == "financial" and res["family"] == "financial"
    assert res["cost_of_equity"] == R and res["base"] == b and res["seed"] == 1000 and res["checked_attempt"] == 1 and res["authority"] == "diagnostic_only"
    assert prepared[0]["family"] == "financial" and prepared[0]["online"] is False and "capital_constraint_not_modeled" in res["stamps"]
    v = res["values"]
    bear_in = dict(inp, book_growth=[g + (0.03 - 0.05) for g in inp["book_growth"]], long_run_roe=0.09, terminal_growth=0.02)      # the year-3 growth becomes the bound
    bull_in = dict(inp, book_growth=[g + (0.07 - 0.05) for g in inp["book_growth"]], long_run_roe=0.13, terminal_growth=0.035)
    assert v["base"] == DF.value_inputs(b, R, inp)[0] and v["bear"] == DF.value_inputs(b, R, bear_in)[0] and v["bull"] == DF.value_inputs(b, R, bull_in)[0]
    assert v["bear"] < v["base"] < v["bull"]
    d = res["decided"]
    assert d["inputs"] == inp and d["ranges"] == rng and res["inputs"] == reply() and d["scenarios"]["bear"]["book_growth"] == pytest.approx(bear_in["book_growth"])
    assert d["scenarios"]["bull"] == {"book_growth": pytest.approx(bull_in["book_growth"]), "long_run_roe": 0.13, "terminal_growth": 0.035}
    assert d["value_at_old_defaults"] == DF.old_defaults(b, bar, R)[0] and d["old_defaults_inputs"]
    assert d["reasons"]["fade_years"] == {"why": "Because of fade_years.", "quotes": [{"id": "F1", "quote": QUOTE}], "quotes_given": 1}
    assert "quotes_verified: 5 of 5" in d["flags"] and d["prior_read_claims"] == {"kept": 1, "dropped_unsupported": 1} and "tax_range" not in res
    assert set(d["diagnostics"]) == {"equity_value", "tv_share", "seam_ratio", "implied_pb"} and d["diagnostics"]["implied_pb"] == pytest.approx(v["base"] / (b["R1"] / b["shares"]))
    (path,) = (tmp_path / "runs").glob("TEST_20261118T000000Z_*_decided_1000/result.json")
    assert json.loads(path.read_text(encoding="utf-8"))["values"] == v and (path.parent / "raw" / "attempt_1.json").exists()


def test_a_range_equal_to_the_input_gives_one_value(tmp_path, monkeypatch):
    packet, *_ = arrange(tmp_path, monkeypatch, [reply(**{"ranges.long_run_roe": [0.104, 0.104], "ranges.book_growth_y3": [0.05, 0.05], "ranges.terminal_growth": [0.03, 0.03]})])
    v = run(tmp_path, packet)["values"]
    assert v["bear"] == v["base"] == v["bull"]


def test_the_quote_of_the_record_is_checked_word_for_word(tmp_path, monkeypatch):
    rec = {k: {"why": "x", "quotes": [{"id": "REC", "quote": f"Cost of equity r {R:.4f}"}]} for k in DF.INPUT_KEYS}
    packet, *_ = arrange(tmp_path, monkeypatch, [reply(reasons=rec)])
    assert run(tmp_path, packet)["status"] == "ok"
    bad = {k: {"why": "x", "quotes": [{"id": "REC", "quote": f"Cost of equity r {R + 0.01:.4f}"}]} for k in DF.INPUT_KEYS}
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(reasons=bad), reply()])
    assert run(tmp_path, packet)["checked_attempt"] == 2 and "reasons.roe has no quote found word for word" in sent[1][3]["content"]


PROBLEMS = [
    ("roe is four numbers", {"inputs.roe": [0.1] * 4}, "inputs.roe must be a list of 5 numbers"),
    ("roe 1.2", {"inputs.roe": [0.1, 1.2, 0.1, 0.1, 0.1]}, "roe 1.2 is outside (-1, 1)"),
    ("long-run roe 0", {"inputs.long_run_roe": 0.0, "ranges.long_run_roe": [0.0, 0.13]}, "long_run_roe 0.0 is outside (0, 1)"),
    ("long-run roe range end at 1", {"ranges.long_run_roe": [0.09, 1.0]}, "long_run_roe 1.0 is outside (0, 1)"),
    ("terminal growth not below r", {"inputs.terminal_growth": 0.11, "ranges.terminal_growth": [0.02, 0.115]}, "is not below the cost of equity"),
    ("terminal growth range end not below r", {"ranges.terminal_growth": [0.02, 0.10]}, "terminal_growth 0.1 is not below the cost of equity"),
    ("low above the input", {"ranges.long_run_roe": [0.12, 0.13]}, "must contain the input 0.104"),
    ("input above the high", {"ranges.book_growth_y3": [0.0, 0.03]}, "must contain the input 0.05"),
    ("unverified quote", {"reasons.roe.quotes": [{"id": "F1", "quote": "invented words"}]}, "reasons.roe has no quote found word for word"),
    ("quote of an item that does not exist", {"reasons.roe.quotes": [{"id": "F9", "quote": QUOTE}]}, "reasons.roe has no quote found"),
    ("quote of the prior read", {"reasons.roe.quotes": [{"id": "business_model", "quote": "A supported claim about the business."}]}, "reasons.roe has no quote"),
    ("no quote for the long-run growth", {"reasons.terminal_growth.quotes": []}, "reasons.terminal_growth has no quote"),
    ("a reason missing", {"reasons.fade_years": None}, "reasons.fade_years must be"),
    ("fade years 30", {"inputs.fade_years": 30}, "inputs.fade_years must be a whole number from 1 to 25"),
    ("fade years 7.5", {"inputs.fade_years": 7.5}, "whole number"),
    ("institution a hedge fund", {"situation.institution": "hedge fund"}, "situation.institution must be one of bank, insurer, other"),
    ("capital constraint maybe", {"situation.capital_constrained": "maybe"}, "situation.capital_constrained must be one of yes, no, unclear"),
    ("no roe_position", {"situation.roe_position": " "}, "situation.roe_position is missing"),
    ("confidence sure", {"confidence": "sure"}, "confidence must be one of low, medium, high"),
    ("growth below -1", {"inputs.book_growth": [-1.2, 0.05, 0.04, 0.04, 0.03]}, "is not above -1"),
    ("a low bound that takes a year's growth below -1", {"ranges.book_growth_y3": [-1.5, 0.07]}, "book_growth of the low case, year 1"),
    ("a boolean for a number", {"inputs.long_run_roe": True}, "inputs.long_run_roe must be a number"),
    ("risks hitting a key that is not an input", {"biggest_risks": [{"risk": "x", "input_hit": "op_margin", "bear_value": 1}]}, "biggest_risks must be"),
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


def test_growth_above_the_long_run_return_and_above_the_return_are_valued_and_flagged_not_refused(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(**{"inputs.long_run_roe": 0.02, "ranges.long_run_roe": [0.01, 0.13], "inputs.terminal_growth": 0.03})])
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and len(sent) == 1
    assert "growth_above_roe_in_the_long_run: terminal_growth 0.0300 against long_run_roe 0.0200" in res["decided"]["flags"]


def test_a_second_failure_is_decision_invalid_with_no_value(tmp_path, monkeypatch):
    bad = reply(**{"inputs.roe": [0.1, 1.2, 0.1, 0.1, 0.1]})
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [bad, reply(**{"reasons.roe.quotes": []})])
    res = run(tmp_path, packet)
    assert res["status"] == "no_call" and res["reason"] == "decision_invalid" and len(sent) == 2 and "values" not in res and "decided" not in res
    assert "reasons.roe has no quote" in res["detail"] and "outside (-1, 1)" not in res["detail"]       # the detail is the last attempt's
    assert len(res["attempts"]) == 2


def test_a_desk_refusal_goes_back_to_the_model_like_any_other_problem(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), reply()])
    real, n = DF.value_inputs, {"n": 0}

    def flaky(bb, r, inp):
        n["n"] += 1
        if n["n"] == 1:
            raise desk.DeskRefusal("input_invalid", "ROE_0 and ROE_T must be positive")
        return real(bb, r, inp)
    monkeypatch.setattr(DF, "value_inputs", flaky)
    res = run(tmp_path, packet)
    assert res["status"] == "ok" and len(sent) == 2 and "the desk could not value the base inputs: input_invalid: ROE_0 and ROE_T must be positive" in sent[1][3]["content"]


def test_an_engine_defect_is_recorded_not_raised_and_not_retried(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), reply()])
    monkeypatch.setattr(DF.checks, "_recompute_fin", lambda *a, **k: (_ for _ in ()).throw(AssertionError("V1: broken")))
    res = run(tmp_path, packet)
    assert res["status"] == "engine_defect" and res["reason"] == "engine_defect" and "V1: broken" in res["detail"] and len(sent) == 1 and "values" not in res


def test_a_call_that_gets_no_reply_raises_and_writes_no_result(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [("infra_fatal", "down")])
    with pytest.raises(RuntimeError, match="infra_fatal: down"):
        run(tmp_path, packet)
    assert not list((tmp_path / "runs").glob("**/result.json"))


# ---- refusals before any call: as the menu method ----------------------------------------------------------------------------------

def test_a_prepare_refusal_is_the_menu_methods_refusal_and_no_call_is_made(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply()])

    def refuse(*a, **k):
        raise desk.DeskRefusal("e0_not_positive", "E_0 is not positive")
    monkeypatch.setattr(DF.vrun, "prepare", refuse)
    res = run(tmp_path, packet)
    assert (res["status"], res["reason"]) == ("no_call", "e0_not_positive") and sent == [] and res["versions"]["method"] == "decided.v1" and res["route"] == "financial"


def test_a_packet_with_news_and_a_family_that_is_not_financial_are_refused_without_a_call(tmp_path, monkeypatch):
    news = copy.deepcopy(PK)
    news["evidence"].append({"fact_id": "N1", "kind": "news", "title": "t", "form": None, "period": None, "effective_at": None, "source": None, "text": "x"})
    packet, b, bar, sent, prepared = arrange(tmp_path, monkeypatch, [reply()], pk=news)
    assert run(tmp_path, packet)["reason"] == "news_items_not_valued"
    packet, b, bar, sent, prepared = arrange(tmp_path, monkeypatch, [reply()])
    for family in ("operating", "commodity", "reit"):
        res = run(tmp_path, packet, family=family)
        assert res["reason"] == "family_not_routed" and sent == [] and prepared == []


# ---- the flags -------------------------------------------------------------------------------------------------------------------------

def test_flags_are_stamps_not_clamps(tmp_path, monkeypatch):
    over = {"inputs.roe": [0.30, 0.102, 0.102, 0.102, 0.102], "inputs.long_run_roe": 0.02, "ranges.long_run_roe": [0.01, 0.13], "inputs.book_growth": [0.50, 0.05, 0.05, 0.05, 0.05],
            "situation.base_year_representative": "no", "confidence": "low", "reasons.roe.quotes": [{"id": "F1", "quote": QUOTE}, {"id": "F1", "quote": "not in the item"}]}
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(**over)])
    res = run(tmp_path, packet)
    fl = res["decided"]["flags"]
    assert res["status"] == "ok" and len(sent) == 1
    assert "roe_outside_filed_record: roe.y1 0.3000 (filed 0.1000 to 0.1049)" in fl and not any(x.startswith("roe_outside_filed_record: roe.y2") for x in fl)
    assert "roe_outside_filed_record: long_run_roe 0.0200 (filed 0.1000 to 0.1049)" in fl and any(x.startswith("book_growth_outside_filed_record: book_growth.y1 0.5000") for x in fl)
    assert any(x.startswith("growth_above_roe_in_the_long_run") for x in fl)
    assert "base_year_not_representative" in fl and "confidence_low" in fl and "quotes_verified: 5 of 6" in fl
    assert res["decided"]["inputs"]["roe"][0] == 0.30 and res["decided"]["reasons"]["roe"]["quotes"] == [{"id": "F1", "quote": QUOTE}]


def test_a_share_count_with_no_filed_eps_to_prove_it_shows_in_the_flags(tmp_path, monkeypatch):
    packet, *_ = arrange(tmp_path, monkeypatch, [reply()], facts=F.bank_facts())                  # WO_UV2: no filed EPS
    assert run(tmp_path, packet)["decided"]["flags"] == ["quotes_verified: 5 of 5", "shares_unreconciled_no_eps"]


def test_a_flag_free_reply_has_only_the_quote_count(tmp_path, monkeypatch):
    packet, *_ = arrange(tmp_path, monkeypatch, [reply()])
    assert run(tmp_path, packet)["decided"]["flags"] == ["quotes_verified: 5 of 5"]


def test_a_value_order_that_is_not_monotone_is_annotated(tmp_path, monkeypatch):
    """A long-run return under the cost of equity makes growth destroy value: the low growth case is worth more."""
    packet, *_ = arrange(tmp_path, monkeypatch, [reply(**{"inputs.long_run_roe": 0.06, "ranges.long_run_roe": [0.05, 0.07], "inputs.roe": [0.06] * 5})])
    res = run(tmp_path, packet)
    v = res["values"]
    assert res["status"] == "ok" and not v["bear"] <= v["base"] <= v["bull"] and any(f.startswith("scenario_order_not_monotone") for f in res["decided"]["flags"])


# ---- the two runs and the report ------------------------------------------------------------------------------------------------

def two_runs(tmp_path, monkeypatch, second=None):
    out = tmp_path / "runs"
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), second or reply(**{"inputs.long_run_roe": 0.12, "inputs.terminal_growth": 0.025})])
    return packet, b, {str(s): DF.value(packet, "1", "Banks", 0.0, family="financial", analysis=AN, seed=s, out_root=out, online=False) for s in (1000, 3000)}


def N(packet):
    return {"packet": str(packet), "cik": "1", "sector": "Banks", "market_cap": 0.0, "family": "financial"}


def test_the_report_row_is_the_mean_of_the_two_runs_each_runs_base_is_kept_and_the_gap_is_a_number(tmp_path, monkeypatch):
    packet, b, rs = two_runs(tmp_path, monkeypatch)
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    a, c = rs["1000"]["values"], rs["3000"]["values"]
    assert rep["valued"] and rep["valuation"] is None and rep["no_value_reason"] is None and rep["family"] == "financial"
    assert rep["value_per_filed_share"] == {k: (a[k] + c[k]) / 2 for k in ("bear", "base", "bull")}
    assert rep["seed_base"] == {"1000": a["base"], "3000": c["base"]} and rep["filed_shares"] == b["shares"]
    assert rep["equity_value"] == rep["value_per_filed_share"]["base"] * b["shares"] and rep["seeds_agree"] is True and "tax_range" not in rep
    d = rep["decided"]
    assert d["run_gap"] == pytest.approx(abs(a["base"] - c["base"]) / ((abs(a["base"]) + abs(c["base"])) / 2)) and 0 < d["run_gap"] < 1
    assert set(d) == {"version", "method", "route", "runs", "run_gap", "situation_unclear", "flags", "value_at_old_defaults", "old_defaults_inputs"}
    assert set(d["runs"]) == {"1000", "3000"} and d["runs"]["1000"]["values"] == a and d["runs"]["3000"]["inputs"]["long_run_roe"] == 0.12
    assert set(d["runs"]["1000"]) >= {"situation", "inputs", "ranges", "reasons", "risks", "confidence", "flags", "scenarios", "values"}
    assert d["situation_unclear"] is False and d["method"] == "decided.v1" and d["route"] == "financial" and d["flags"][0].startswith("run 1000: ")
    assert d["value_at_old_defaults"] == rs["1000"]["decided"]["value_at_old_defaults"]
    json.dumps(rep)                                                                      # the report is plain JSON


@pytest.mark.parametrize("key,other", [("institution", "insurer"), ("capital_constrained", "yes")])
def test_the_two_runs_disagreeing_on_the_institution_or_the_capital_constraint_is_stamped_situation_unclear(tmp_path, monkeypatch, key, other):
    packet, b, rs = two_runs(tmp_path, monkeypatch, second=reply(**{f"situation.{key}": other}))
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    assert rep["valued"] and rep["decided"]["situation_unclear"] is True and rep["decided"]["flags"][0] == "situation_unclear" and rep["seeds_agree"] is False


def test_there_is_no_value_from_one_run_alone_and_no_fallback_to_a_default(tmp_path, monkeypatch):
    bad = reply(**{"inputs.fade_years": 30})
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [reply(), bad, bad])
    r1, r2 = (DF.value(packet, "1", "Banks", 0.0, family="financial", analysis=AN, seed=s, out_root=tmp_path / "r2", online=False) for s in (1000, 3000))
    assert r1["status"] == "ok" and r2["reason"] == "decision_invalid" and DF.combine_runs({"1000": r1, "3000": r2}) == (False, {}) and DF.combine_runs({"1000": r1}) == (False, {})
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), {"1000": r1, "3000": r2}, "c")
    assert rep["valued"] is False and rep["no_value_reason"] == qwen_site.NO_VALUE["decision_invalid"] and "decided" not in rep and "value_per_filed_share" not in rep


def test_a_refused_name_reports_the_menu_reason(tmp_path, monkeypatch):
    packet, b, bar, sent, _ = arrange(tmp_path, monkeypatch, [])
    monkeypatch.setattr(DF.vrun, "prepare", lambda *a, **k: (_ for _ in ()).throw(desk.DeskRefusal("e0_not_positive", "x")))
    rs = {str(s): run(tmp_path, packet, seed=s) for s in (1000, 3000)}
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    assert rep["valued"] is False and rep["no_value_reason"] == qwen_site.NO_VALUE.get("e0_not_positive", "e0_not_positive") and sent == []


def test_an_operating_result_set_is_still_combined_by_decided_value(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(D, "combine_runs", lambda rs: called.append(1) or (False, {}))
    monkeypatch.setattr(DF, "combine_runs", lambda rs: called.append(2) or (False, {}))
    rs = {s: {"status": "ok", "versions": {"method": "decided.v1"}} for s in ("1000", "3000")}
    Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, {"packet": None, "cik": "1", "sector": "x", "market_cap": 0, "family": "operating"}, rs, "c")
    Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, {"packet": None, "cik": "1", "sector": "x", "market_cap": 0, "family": "financial"}, rs, "c")
    assert called == [1, 2]


def test_quote_units_and_the_verdict_read_the_financial_report(tmp_path, monkeypatch):
    packet, b, rs = two_runs(tmp_path, monkeypatch)
    rep = Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, N(packet), rs, "c")
    row = {k: v for k, v in rep.items() if k not in ("tasks", "valuation", "ticker", "authority")}
    old = rep["decided"]["value_at_old_defaults"]
    shares = rep["filed_shares"]
    qwen_site.quote_units({"TEST": (row, rep)}, {"TEST": {"price": 10.0, "marketCap": 10.0 * 2 * shares}})
    assert row["value_base"] == pytest.approx(rep["value_per_filed_share"]["base"] * 0.5) and row["decided"]["value_at_old_defaults_quoted"] == pytest.approx(old * 0.5)
    v, why, a = G.verdict(row, R, checks.PROB)
    assert v in ("BUY", "WATCH", "AVOID") and a is not None


# ---- the switch in gemini_ondemand.analyze and the shadow ---------------------------------------------------------------------------

def switch(tmp_path, monkeypatch, family):
    seeds, reports, calls = T.switch(tmp_path, monkeypatch, "decided", family)
    fin_calls = []
    monkeypatch.setattr(G.decided_financial, "value", lambda *a, **k: fin_calls.append((a, k)) or {"status": "ok", "seed": k["seed"]})
    return seeds, reports, calls, fin_calls


def test_decided_values_a_financial_name_with_decided_financial_for_both_seeds_and_no_operating_call(tmp_path, monkeypatch):
    seeds, reports, calls, fin = switch(tmp_path, monkeypatch, "financial")
    assert G.analyze("TEST", "list") == "ok"
    assert seeds == [] and calls == [] and [k["seed"] for _, k in fin] == [1000, 3000] and list(reports[0]) == ["1000", "3000"]
    a, k = fin[0]
    assert a[1:4] == ("1", "Technology", 1e8) and k["family"] == "financial" and k["analysis"] == {} and k["out_root"] == G.vrun.RUNS


def test_an_operating_name_still_goes_to_decided_value_and_the_menu_stays_the_default(tmp_path, monkeypatch):
    seeds, reports, calls, fin = switch(tmp_path, monkeypatch, "operating")
    G.analyze("TEST", "list")
    assert fin == [] and [k["seed"] for _, k in calls] == [1000, 3000] and seeds == []
    (tmp_path / "menu").mkdir()
    seeds, reports, calls, fin = switch(tmp_path / "menu", monkeypatch, "financial")
    monkeypatch.setattr(G, "VALUE_METHOD", "menu")
    G.analyze("TEST", "list")
    assert fin == [] and calls == [] and seeds == [1000, 3000]


def test_the_shadow_takes_a_stored_financial_name_and_values_it_with_decided_financial(tmp_path, monkeypatch):
    st = TSH.store_of(tmp_path)
    for name in ("SITE", "LOG", "AGY_CWD", "USAGE", "LOCK", "ARM", "GEM_MODEL", "FLOORS"):
        monkeypatch.setattr(G, name, getattr(G, name))
    f = F.bank_facts()
    b = dict(inputs.base_financial(f), stub_days=0, g_anchor=0.04)
    bar = forecast_fin.record_bar(b["record"]["roe"])
    sent = T.stub(monkeypatch, [reply(), reply(**{"inputs.long_run_roe": 0.12})])
    monkeypatch.setattr(DF.vrun, "prepare", lambda *a, **k: (f, b, bar, forecast_fin.record_items(f, b), R, dict(F.PROV), sorted(b["record"]["common_equity"])))
    monkeypatch.setattr(G, "FLOORS", TSH.FLOORS)
    monkeypatch.setattr(G, "set_arm", lambda arm: None)
    monkeypatch.setattr(G, "swap", lambda: None)
    monkeypatch.setattr(G, "meter", lambda: {k: (0.9, None) for k in TSH.FLOORS})
    monkeypatch.setattr(S, "screener_row", lambda commit, t: {"price": 10.0, "marketCap": 1.0e8, "sector": "Banks"})
    # the stored FIN name gets the stored read of TEST (its packet and analysis), as a financial report in the store
    d = st / "m3m_sonnet" / "runs" / f"FIN_20261118T000000Z_abc123_1"
    d.mkdir(parents=True)
    (d / "packet.json").write_text(json.dumps(dict(PK, ticker="FIN")), encoding="utf-8")
    (d / "analysis.json").write_text(json.dumps(AN), encoding="utf-8")
    assert [(r["ticker"], r["family"]) for r, _ in S.stored_names(st)] == [("FIN", "financial"), ("TEST", "operating")]
    out = tmp_path / "out"
    assert S.main(["--arm", "sonnet", "--store", str(st), "--out", str(out), "--tickers", "FIN"]) == 0 and len(sent) == 2
    names = sorted(p.parent.name for p in (out / "runs").glob("*/result.json"))
    assert len(names) == 2 and names[0].startswith("FIN_20261118T000000Z_")
    res = json.loads(next((out / "runs").glob("FIN_*_decided_1000/result.json")).read_text(encoding="utf-8"))
    assert res["status"] == "ok" and res["route"] == "financial"
    (row,) = json.loads((out / "shadow_table.json").read_text(encoding="utf-8"))
    assert row["ticker"] == "FIN" and row["family"] == "financial" and row["valued"] is True and 0 < row["run_gap"] < 1 and row["flags"][0].startswith("run 1000: ")
