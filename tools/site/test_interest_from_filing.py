"""WO_NC8: where the tagged interest gives a cost of debt outside the band, the cloud read states the interest on borrowings from the filing
(interest_from_filing.py, inputs.base(interest_override=), gemini_ondemand.analyze). Synthetic data only; the model call is stubbed (runner.call)."""
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decided_value as D  # noqa: E402
import gemini_ondemand as G  # noqa: E402
import interest_from_filing as I  # noqa: E402
import qwen_ondemand as Q  # noqa: E402
import test_tax_range_report as TR  # noqa: E402
from qwen_c import runner  # noqa: E402
from qwen_c.tests import test_value_inputs as ti  # noqa: E402
from qwen_c.tests import test_value_tax_statutory as TS  # noqa: E402
from qwen_c.value import desk, inputs, run  # noqa: E402

TEXT = "Interest expense on borrowings was 90,827 for the year, excluding exchange differences and the accretion of concession liabilities."
QUOTE = "Interest expense on borrowings was 90,827"
PK = {"contract": runner.PACKET_CONTRACT, "ticker": "TEST", "cik": "1", "decision_time_utc": "2026-11-18T00:00:00Z",
      "evidence": [{"fact_id": "F1", "kind": "statement", "title": "t", "form": "20-F", "period": "2025", "effective_at": "2026-01-01T00:00:00Z",
                    "source": None, "text": TEXT}]}
FG = {"fy0": "2025-12-31", "tag": "ifrs-full:FinanceCosts", "interest": 243955000.0, "kd_interest": 243955000.0, "debt0": 1.1e9, "debt_prev": 1.16e9, "kd": 0.2146}


def answer(value=90827, scale="thousands", quote=QUOTE, i="F1", found=I.FOUND, what="Interest expense", why="The tag includes exchange differences."):
    return json.dumps({"found": found, "value": value, "scale": scale, "what": what, "why_tagged_figure_differs": why, "quotes": [{"id": i, "quote": quote}]})


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


# ---- the question and the checks -------------------------------------------------------------------------------------------------------

def test_found_and_verified_gives_the_override_in_units_and_the_record(tmp_path, monkeypatch):
    sent = stub(monkeypatch, [answer()])
    rec, ov = I.ask(PK, FG, tmp_path / "raw")
    assert ov == 90827e3 and len(sent) == 1
    assert rec == {"version": I.INTEREST_FROM_FILING_VERSION, "tagged_value": 243955000.0, "kd_tagged": 0.2146, "fy0": "2025-12-31", "status": "used", "value": 90827e3,
                   "printed": 90827, "scale": "thousands", "what": "Interest expense", "why": "The tag includes exchange differences.", "quote": QUOTE,
                   "quotes": [{"id": "F1", "quote": QUOTE}], "kd_used": None}
    assert json.loads((tmp_path / "raw" / "attempt_1.json").read_text(encoding="utf-8"))["messages"] == sent[0]      # the raw prompt and reply are kept


def test_the_prompt_carries_the_evidence_what_code_used_and_the_rules(tmp_path, monkeypatch):
    sent = stub(monkeypatch, [answer()])
    I.ask(PK, FG, tmp_path)
    assert sent[0][0] == {"role": "system", "content": I.SYSTEM}
    u = sent[0][1]["content"]
    assert TEXT in u and "ifrs-full:FinanceCosts: 243,955,000" in u and "1,100,000,000" in u and "1,160,000,000" in u and "21.46%" in u
    for rule in ("for the fiscal year ended 2025-12-31, and for that fiscal year only", "before the deduction", "Leave out exchange differences, fees, accretion on items that are not debt, and lease interest where the filing shows it apart",
                 "answer cannot_tell; do not estimate it and do not add figures up", "Quote verbatim", "the quote must contain the number you give"):
        assert rule in u
    assert "outside" not in u.split("WHAT CODE USED")[1].split("QUESTION")[0]            # the band is not shown to the read


def test_a_financing_arm_interest_added_by_code_is_said_so():
    assert "adds the interest of a financing arm" in I.figures_text(dict(FG, kd_interest=3.0e8)) and "adds the interest" not in I.figures_text(FG)


def test_cannot_tell_is_an_answer_it_is_not_retried_and_it_leaves_the_refusal(tmp_path, monkeypatch):
    sent = stub(monkeypatch, [json.dumps({"found": "cannot_tell", "why_tagged_figure_differs": "The packet does not show the line."})])
    rec, ov = I.ask(PK, FG, tmp_path)
    assert ov is None and len(sent) == 1 and rec["status"] == "cannot_tell" and rec["why"] == "The packet does not show the line." and "value" not in rec


def test_a_number_that_is_not_in_a_verified_quote_is_retried_once_then_the_refusal_stands(tmp_path, monkeypatch):
    sent = stub(monkeypatch, [answer(value=90000), answer(value=1)])
    rec, ov = I.ask(PK, FG, tmp_path)
    assert ov is None and rec["status"] == "unverified" and "does not appear in any quote" in rec["failure"] and "value" not in rec
    assert len(sent) == 2 and "was not accepted: the number 90000 does not appear" in sent[1][1]["content"]


def test_a_failed_check_then_a_good_reply_is_accepted(tmp_path, monkeypatch):
    stub(monkeypatch, [answer(quote="invented words"), answer()])
    rec, ov = I.ask(PK, FG, tmp_path)
    assert ov == 90827e3 and rec["status"] == "used"


@pytest.mark.parametrize("value,scale,quote,expect", [
    (90827, "thousands", "was 90,827 for", 90827e3),            # thousands separators in the quote are ignored
    ("90,827", "thousands", "was 90827 for", 90827e3),          # and in the value
    ("(90,827)", "thousands", "the line (90,827)", 90827e3),    # brackets are ignored
    (90827.0, "units", "was 90,827 for", 90827.0),
    (90.8, "millions", "was 90.80 million", 90.8e6),            # 90.80 is 90.8
    ("90.8", "millions", "was 90.8 million", 90.8e6),
    (1.2, "billions", "of $1.2 billion in", 1.2e9)])
def test_the_digit_rule_accepts_the_same_number_written_differently(value, scale, quote, expect):
    text = f"Context. {quote} and more."
    ans, problem = I.check(json.loads(answer(value=value, scale=scale, quote=quote)), {"F1": text})
    assert problem is None and ans["value"] == pytest.approx(expect, rel=1e-12)


@pytest.mark.parametrize("value", [827, 90, 9082, 90827000, 908.27, 0.0, -90827, True, "n/a", None])
def test_the_digit_rule_refuses_a_number_that_is_only_part_of_a_printed_one_or_is_not_a_positive_number(value):
    ans, problem = I.check(json.loads(answer(value=value, quote="was 90,827 for")), {"F1": "Context. was 90,827 for more."})
    assert ans is None and problem


@pytest.mark.parametrize("over,why", [({"scale": "lakhs"}, "scale"), ({"what": " "}, "what is missing"), ({"found": "maybe"}, "is not one of"),
                                      ({"why": ""}, "why_tagged_figure_differs is missing"), ({"quote": "text not in the item"}, "no quote was found"),
                                      ({"i": "F9"}, "no quote was found")])
def test_a_reply_that_breaks_the_shape_or_the_quote_rule_is_refused(over, why):
    ans, problem = I.check(json.loads(answer(**over)), {"F1": TEXT})
    assert ans is None and why in problem


def test_a_quote_without_the_number_is_not_enough_when_another_quote_carries_it():
    obj = json.loads(answer())
    obj["quotes"] = [{"id": "F1", "quote": "excluding exchange differences"}, {"id": "F1", "quote": QUOTE}]
    ans, problem = I.check(obj, {"F1": TEXT})
    assert problem is None and ans["quotes"][0]["quote"] == QUOTE and len(ans["quotes"]) == 2          # the first quote is one that carries the number


def test_malformed_json_is_retried_and_a_call_that_gets_no_reply_is_not_an_answer(tmp_path, monkeypatch):
    sent = stub(monkeypatch, ["not json", "[1]"])
    rec, ov = I.ask(PK, FG, tmp_path)
    assert ov is None and "not a JSON object" in rec["failure"] and "not valid JSON" in sent[1][1]["content"]
    stub(monkeypatch, [("infra_fatal", "down")])
    with pytest.raises(RuntimeError, match="infra_fatal: down"):
        I.ask(PK, FG, tmp_path)


# ---- inputs.base(interest_override=) ----------------------------------------------------------------------------------------------------

def refused_facts(**over):
    """The default facts with the base year's interest at 6 on debt of 20: a cost of debt of 30%."""
    return ti.facts(interest_expense=ti.series([1, 1, 1, 1, 6]), **over)


def test_the_default_base_is_unchanged_and_the_tagged_refusal_carries_the_figures():
    f = ti.facts()
    assert inputs.base(f, market_cap=180.0, bill_rate=ti.BILL, interest_override=None) == inputs.base(f, market_cap=180.0, bill_rate=ti.BILL)
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base(refused_facts(), market_cap=180.0, bill_rate=ti.BILL)
    assert e.value.code == "kd_out_of_band" and str(e.value).endswith("outside (0.01, 0.2)")
    assert e.value.figures == {"fy0": "2025-12-31", "tag": "T", "interest": 6, "kd_interest": 6, "debt0": 20, "debt_prev": 20, "debt_basis": "components", "kd": 0.3}


def test_the_override_changes_only_the_interest_dependent_fields():
    """The base with the override equals the base of facts that file the override as the base year's interest, but for the stamp and the record."""
    ov = 2.0
    b = inputs.base(refused_facts(), market_cap=180.0, bill_rate=ti.BILL, interest_override=ov)
    twin = inputs.base(ti.facts(interest_expense=ti.series([1, 1, 1, 1, ov])), market_cap=180.0, bill_rate=ti.BILL)
    assert b["kd"] == pytest.approx(0.1) and b["k0_interest"] == ov
    assert b["interest_from_filing"] == {"value": ov, "tagged_value": 6, "kd_used": pytest.approx(0.1)} and "interest_from_filing_text" in b["stamps"]
    assert sorted(b["stamps"]) == sorted(twin["stamps"] + ["interest_from_filing_text"])
    assert {k: v for k, v in b.items() if k not in ("stamps", "interest_from_filing")} == {k: v for k, v in twin.items() if k != "stamps"}
    plain = inputs.base(ti.facts(), market_cap=180.0, bill_rate=ti.BILL)                      # and not the tagged interest's base: the interest term differs
    assert plain["k0_interest"] == 1.0 and b["ronic0"] != plain["ronic0"] and b["k0_interest"] != plain["k0_interest"]


def test_the_band_still_applies_to_the_override_and_the_detail_says_so():
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base(refused_facts(), market_cap=180.0, bill_rate=ti.BILL, interest_override=10.0)
    assert e.value.code == "kd_out_of_band" and "also outside" in str(e.value) and e.value.figures["kd"] == 0.5
    with pytest.raises(desk.DeskRefusal) as e:
        inputs.base(ti.facts(), market_cap=180.0, bill_rate=ti.BILL, interest_override=0.1)      # a figure under the band's floor is refused too
    assert e.value.code == "kd_out_of_band"


def test_the_ifrs16_lease_and_the_financing_interest_additions_are_not_made_for_the_override():
    lease = dict(lease_interest_ifrs16=ti.series([0.5]), lease_liabilities_ifrs16=ti.series([4, 4, 4, 4, 4]))
    plain = inputs.base(ti.facts(**lease), market_cap=180.0, bill_rate=ti.BILL)
    assert "debt_includes_ifrs16_lease_liabilities" in plain["stamps"] and plain["debt0"] == 24
    b = inputs.base(ti.facts(**lease), market_cap=180.0, bill_rate=ti.BILL, interest_override=1.2)
    assert "debt_includes_ifrs16_lease_liabilities" not in b["stamps"] and b["debt0"] == 20 and b["kd"] == pytest.approx(1.2 / 20)
    fin = dict(interest_expense=ti.series([1, 1, 1, 1, 1], tag="InterestExpenseNonoperating"), financing_interest=ti.series([0.5]))
    assert "kd_includes_financing_interest" in inputs.base(ti.facts(**fin), market_cap=180.0, bill_rate=ti.BILL)["stamps"]
    b = inputs.base(ti.facts(**fin), market_cap=180.0, bill_rate=ti.BILL, interest_override=1.2)
    assert "kd_includes_financing_interest" not in b["stamps"] and b["kd"] == pytest.approx(1.2 / 20)


def test_the_value_at_the_second_tax_rate_carries_the_same_interest():
    f = TS.fb_inputs()
    f["interest_expense"] = ti.series([1, 1, 1, 1, 6])
    b = dict(inputs.base(f, market_cap=180.0, bill_rate=ti.BILL, interest_override=2.0), bill_source="t", stub_days=0, g_anchor=0.03)
    a = run.alt_tax_base(f, b, 180.0)
    assert a["interest_from_filing"] == b["interest_from_filing"] and a["kd"] == b["kd"] and a["tau"] != b["tau"]
    plain = dict(inputs.base(TS.fb_inputs(), market_cap=180.0, bill_rate=ti.BILL), bill_source="t", stub_days=0, g_anchor=0.03)
    assert "interest_from_filing" not in run.alt_tax_base(TS.fb_inputs(), plain, 180.0)


# ---- the pass-through ------------------------------------------------------------------------------------------------------------------

def test_vrun_value_and_decided_value_pass_the_override_to_prepare_and_the_report_does(tmp_path, monkeypatch):
    seen = []

    def refuse(*a, **k):
        seen.append(k.get("interest_override", "absent"))
        raise desk.DeskRefusal("kd_out_of_band", "x")
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps(PK), encoding="utf-8")
    monkeypatch.setattr(run, "prepare", refuse)
    assert run.value(packet, "1", "Technology", 1e8, family="operating", out_root=tmp_path / "a", interest_override=5.0)["reason"] == "kd_out_of_band"
    assert D.value(packet, "1", "Technology", 1e8, family="operating", out_root=tmp_path / "b", interest_override=5.0)["reason"] == "kd_out_of_band"
    run.value(packet, "1", "Technology", 1e8, family="operating", out_root=tmp_path / "c")
    assert seen == [5.0, 5.0, None]
    n, results, _ = TR.arrange(tmp_path, monkeypatch, TS.fb_facts())
    got = []
    monkeypatch.setattr(run, "prepare", lambda *a, **k: got.append(k.get("interest_override", "absent")) or (_ for _ in ()).throw(desk.DeskRefusal("x", "y")))
    for kw in ({"interest_override": 7.0}, {}):
        with pytest.raises(desk.DeskRefusal):
            Q.report("TEST", "list", "2026-11-18T00:00:00Z", {}, n, results, "c", **kw)
    assert got == [7.0, None]


# ---- analyze ---------------------------------------------------------------------------------------------------------------------------

def arrange(tmp_path, monkeypatch, replies=(), out_of_band_after=False, trigger=True, figures=True, code="kd_out_of_band", fallback=False):
    """gemini_ondemand.analyze with the packet builder, the valuation and the report stubbed: prepare refuses with kd_out_of_band until it gets an override."""
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
    calls = []

    def prepare(*a, **k):
        calls.append(k.get("interest_override", "absent"))
        if k.get("interest_override") is None and trigger or k.get("interest_override") is not None and out_of_band_after:
            e = desk.DeskRefusal(code, "kd = x")
            if figures:
                e.figures = dict(FG, kd=0.5 if k.get("interest_override") is not None else FG["kd"])
            raise e
        b = {"interest_from_filing": {"value": k["interest_override"], "tagged_value": 1, "kd_used": 0.0907}} if k.get("interest_override") is not None else {}
        if fallback:
            b["tax_fallback"] = {"rate": 0.21}
        return ({}, b, None, None, None, None, None)
    monkeypatch.setattr(G.vrun, "prepare", prepare)
    seen = []
    monkeypatch.setattr(G.vrun, "value", lambda *a, **k: seen.append(dict(k)) or {"status": "no_call" if trigger and "interest_override" not in k else "ok", "seed": k["seed"]})
    reports = []
    monkeypatch.setattr(Q, "report", lambda t, s, T, q1, n, results, commit, **k: reports.append(dict(k)) or {"ticker": t, "valued": True, "date": T})
    return calls, seen, reports, stub(monkeypatch, list(replies))


def written(tmp_path):
    return json.loads((tmp_path / "ondemand" / "TEST.json").read_text(encoding="utf-8"))


def test_found_and_in_band_the_override_goes_to_prepare_both_seeds_and_the_report_and_the_page_gets_the_record(tmp_path, monkeypatch):
    calls, seen, reports, sent = arrange(tmp_path, monkeypatch, [answer()])
    assert G.analyze("TEST", "list") == "ok"
    assert len(sent) == 1 and calls == ["absent", 90827e3] and [k["interest_override"] for k in seen] == [90827e3] * 2 and [k["seed"] for k in seen] == [1000, 3000]
    assert reports == [{"interest_override": 90827e3}]
    rec = written(tmp_path)["interest_from_filing"]
    assert rec["status"] == "used" and rec["value"] == 90827e3 and rec["scale"] == "thousands" and rec["quote"] == QUOTE and rec["what"] == "Interest expense"
    assert rec["tagged_value"] == 243955000.0 and rec["kd_tagged"] == 0.2146 and rec["kd_used"] == 0.0907


def test_found_but_still_out_of_band_the_refusal_stands_with_the_override_and_the_record_says_so(tmp_path, monkeypatch):
    calls, seen, reports, sent = arrange(tmp_path, monkeypatch, [answer()], out_of_band_after=True)
    G.analyze("TEST", "list")
    assert calls == ["absent", 90827e3] and [k["interest_override"] for k in seen] == [90827e3] * 2           # the seeds refuse again, with the filing's own figure in the detail
    rec = written(tmp_path)["interest_from_filing"]
    assert rec["status"] == "used" and rec["kd_tagged"] == 0.2146 and rec["kd_used"] == 0.5


@pytest.mark.parametrize("replies,status", [([json.dumps({"found": "cannot_tell", "why_tagged_figure_differs": "x"})], "cannot_tell"),
                                            ([answer(value=5), answer(value=6)], "unverified")])
def test_cannot_tell_and_an_unverified_number_leave_the_refusal_and_no_override_is_passed(tmp_path, monkeypatch, replies, status):
    calls, seen, reports, sent = arrange(tmp_path, monkeypatch, replies)
    G.analyze("TEST", "list")
    assert calls == ["absent"] and all("interest_override" not in k for k in seen) and reports == [{}] and len(seen) == 2
    rec = written(tmp_path)["interest_from_filing"]
    assert rec["status"] == status and "kd_used" not in rec


def test_the_decided_method_takes_the_override_too(tmp_path, monkeypatch):
    calls, _, reports, _ = arrange(tmp_path, monkeypatch, [answer()])
    monkeypatch.setattr(G, "VALUE_METHOD", "decided")
    monkeypatch.setattr(G.decided_value, "read_analysis", lambda q1: {})
    dseen = []
    monkeypatch.setattr(G.decided_value, "value", lambda *a, **k: dseen.append(dict(k)) or {"status": "ok"})
    G.analyze("TEST", "list")
    assert [k["interest_override"] for k in dseen] == [90827e3] * 2 and reports == [{"interest_override": 90827e3}]


@pytest.mark.parametrize("kw", [{"trigger": False}, {"code": "history_short"}, {"figures": False}])
def test_no_trigger_means_no_call_and_the_calls_are_exactly_as_before(tmp_path, monkeypatch, kw):
    calls, seen, reports, sent = arrange(tmp_path, monkeypatch, [], **kw)
    G.analyze("TEST", "list")
    assert sent == [] and calls == ["absent"] and all("interest_override" not in k for k in seen) and reports == [{}] and [k["seed"] for k in seen] == [1000, 3000]
    assert "interest_from_filing" not in written(tmp_path)


def test_with_an_override_a_tax_fallback_still_gets_its_loss_question(tmp_path, monkeypatch):
    calls, seen, reports, sent = arrange(tmp_path, monkeypatch, [answer(), json.dumps({"cause": "one_off_charges", "explanation": "x", "quotes": [{"id": "F1", "quote": TEXT[:30]}]})],
                                         fallback=True)
    G.analyze("TEST", "list")
    rep = written(tmp_path)
    assert len(sent) == 2 and rep["interest_from_filing"]["status"] == "used" and rep["loss_record"]["cause"] == "one_off_charges" and len(seen) == 2


def test_a_call_that_gets_no_reply_is_not_an_answer_in_analyze_either(tmp_path, monkeypatch):
    arrange(tmp_path, monkeypatch, [("infra_fatal", "down")])
    with pytest.raises(RuntimeError, match="infra_fatal"):
        G.analyze("TEST", "list")
