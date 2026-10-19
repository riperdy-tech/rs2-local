"""Rulings on cross-check 23 (2026-10-19), items 1-15 of "Accepted (R26-F, rs2)": one test group per item, all with stub providers (no GPU, no Ollama, no network)."""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AUDIT_DIR = TESTS_DIR.parent
for p in (str(AUDIT_DIR), str(AUDIT_DIR.parents[1]), str(AUDIT_DIR.parent), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import llm_provider as prov  # noqa: E402
import r26_blind as blind  # noqa: E402
import r26_forecast as rf  # noqa: E402
import r26_late as late  # noqa: E402
import r26_stages as r26  # noqa: E402
from test_r26_forecast import DBAR, DFACTS, DOSSIER, desk_forecast, desk_inputs, forecast  # noqa: E402
from test_r26_stage1 import PACK, PAGE_URL, Script, _fact, call  # noqa: E402
from test_r26_stages24 import (THREE, ROWS, FETCH, PRICE, QUOTE, crux_args, dossier, fcast, memo_step, revision, run_stages, sub, valuation)  # noqa: E402


def probs(obj, dos=DOSSIER):
    return {(p["field"], p["problem"]) for p in rf.validate_forecast(obj, dos)}


# ---------------------------------------------------------------- 1. the frame is equity only

def test_item1_the_frame_is_equity_only():
    assert rf.FRAMES == ("equity",)
    assert ("frame", "not_one_of_equity") in probs(forecast(frame="firm"))
    assert late.forecast_properties()["frame"]["enum"] == ["equity"]
    assert late.revision_tool()["function"]["parameters"]["properties"]["frame"]["enum"] == ["equity"]
    assert not re.search(r"\bfirm\b", late.STAGE2_TASK) and "always equity" in late.STAGE2_TASK
    assert not re.search(r"\bfirm\b", json.dumps(late.SUBMIT_FORECAST_TOOL))


# ---------------------------------------------------------------- 2. unusable facts are never shown; every cited id is usable

def _unusable_dossier():
    d = dossier()
    d["facts"].append({"fact_id": "F9", "source": "page:x", "quote": "SECRETQUOTE 41.7", "entity": "SECRETENTITY", "metric": "SECRETMETRIC", "period": "p", "value": 41.7,
                       "unit": "u", "basis": "filed_gaap", "duration_years": None, "usable": False, "unusable_reason": "metric_not_near_quote: secretmetric, secretword"})
    return d


def test_item2_stages_see_only_a_count_and_reason_codes_of_the_unusable_facts():
    d = _unusable_dossier()
    d["facts"].append({"fact_id": "F10", "usable": False, "unusable_reason": "malformed: quote must be a non-empty string", "metric": "MALMETRIC"})
    d["facts"].append({"fact_id": "F11", "usable": False, "unusable_reason": "association_uncertain: value_not_in_quote", "unusable_code": "association_uncertain"})
    txt = late.render_dossier(d)
    for secret in ("SECRETQUOTE", "SECRETMETRIC", "SECRETENTITY", "41.7", "secretword", "MALMETRIC", "[F9]", "[F3]", "quote not found in its source"):
        assert secret not in txt, secret
    assert "UNUSABLE FACTS: 4 (not shown; they cannot be cited). Reason codes: association_uncertain 1, malformed 1, metric_not_near_quote 1, quote_not_found 1" in txt
    assert "[F1] XYZ" in txt
    assert late.render_dossier({"facts": [{"fact_id": "F1", "usable": True, "entity": "E", "metric": "m", "period": "p", "value": 1.0, "unit": "", "basis": "n/a", "quote": "q"}]}
                               ).endswith("UNUSABLE FACTS: none")
    for reason, code in (("source not resolved", "source_not_resolved"), ("quote not found in its source (page 'u' was not fetched)", "quote_not_found"),
                         ("metric_not_near_quote: a, b", "metric_not_near_quote"), ("malformed: x", "malformed"), ("association_uncertain: y", "association_uncertain")):
        assert late.reason_code({"unusable_reason": reason}) == code


def test_item2_every_cited_fact_must_be_usable_and_the_long_run_cites_or_says_why_not():
    f = forecast()
    f["scenarios"]["Base"]["normalized"]["fact_ids"] = ["F3"]
    f["scenarios"]["Bull"]["long_run_fact_ids"] = ["F3"]
    p = probs(f)
    assert ("Base.normalized.fact_ids", "fact_id_not_usable") in p and ("Bull.long_run_fact_ids", "fact_id_not_usable") in p
    f = forecast()
    f["scenarios"]["Base"]["near_term"]["fact_ids"] = []
    f["scenarios"]["Base"]["normalized"]["fact_ids"] = []
    assert {("Base.near_term.fact_ids", "fact_ids_empty"), ("Base.normalized.fact_ids", "fact_ids_empty")} <= probs(f)
    f = forecast()
    del f["scenarios"]["Base"]["long_run_fact_ids"]
    assert ("Base.long_run_fact_ids", "needs_fact_ids_or_no_duration_matched_evidence_with_a_reason") in probs(f)
    f["scenarios"]["Base"]["no_duration_matched_evidence"] = "no filing speaks for ten years"
    assert rf.validate_forecast(f, DOSSIER) == []
    f["scenarios"]["Base"]["no_duration_matched_evidence"] = "  "
    assert ("Base.no_duration_matched_evidence", "missing_text") in probs(f)
    f["scenarios"]["Base"]["long_run_fact_ids"] = []
    assert ("Base.no_duration_matched_evidence", "missing_text") in probs(f)
    f["scenarios"]["Base"]["no_duration_matched_evidence"] = "none speaks for the long run"
    assert rf.validate_forecast(f, DOSSIER) == []                                       # an empty list plus the explicit statement
    assert rf.validate_forecast(forecast()) == []                                       # no dossier: nothing to check the ids against
    fl = late.validate_labels({"scenarios": {"Base": {k: {"label": list(late.LABEL_ENUMS[k])[0], "fact_ids": ["F3"]} for k in late.LABEL_ENUMS}}}, DOSSIER)
    assert {x["problem"] for x in fl} == {"fact_id_not_usable"}


def test_item2_a_failed_cite_gets_the_one_repair_and_a_second_failure_drops_the_sample(tmp_path, monkeypatch):
    bad = fcast()
    bad["scenarios"]["Bear"]["normalized"]["fact_ids"] = ["F3"]
    script, fc, _, _ = run_stages(tmp_path, monkeypatch, [sub(bad), sub(bad), sub(fcast()), sub(fcast())], stages=(2,))
    assert fc["samples"][0]["status"] == "forecast_invalid" and fc["samples"][0]["problems"][0]["problem"] == "fact_id_not_usable" and fc["samples"][1]["status"] == "valued"


def test_item2_the_ledger_records_a_reason_code_for_each_unusable_fact():
    ev = r26.Evidence(PACK, {})
    led = r26.Ledger(ev, "XYZ Corp", "XYZ")
    led.register({"facts": [_fact(fact_id="A", source="pack:primary-p1", quote="Net income was $5 million.", value=5.0, entity="XYZ", metric="net income"),
                            _fact(fact_id="B", source="pack:primary-p1", quote="Nothing like this is in the filing at all", value=None),
                            _fact(fact_id="C", source="page:https://never.test/", quote="anything", value=None),
                            _fact(fact_id="D", source="pack:primary-p1", quote="Net income was $5 million.", value=9.0, entity="XYZ", metric="net income"),
                            {"fact_id": "E"}]})
    codes = {f["fact_id"]: f.get("unusable_code") for f in led.facts}
    assert codes == {"A": None, "B": "quote_not_found", "C": "source_not_resolved", "D": "association_uncertain", "E": "malformed"}


# ---------------------------------------------------------------- 3. the leak audit reaches the summary and the facts stage 2 sees

REMOVED_LINES = {"removed_lines": [
    {"cls": "price_target", "section": "DATA 8", "id": "data-8", "text": "- Analyst price target: $555"},
    {"cls": "consensus", "section": "DATA 8", "id": "data-8", "text": "- CONSENSUS EPS next FY: 77.7"},
    {"cls": "price", "section": "DATA 2", "id": "data-2", "text": "- Price: $400.00 (2026-10-16)"}],
    "spans": [{"start": 0, "end": 1, "cls": "filed", "section": "DATA 5", "id": "data-5"}, {"start": 2, "end": 3, "cls": "narrative", "section": "DATA 11", "id": "data-11"},
              {"start": 4, "end": 5, "cls": "aggregator", "section": "DATA 4", "id": "data-4"}, {"start": 6, "end": 8, "cls": "derived", "section": "DEFAULTS", "id": "defaults"}]}
BLIND = "## DATA 5 - FILINGS\nRevenue was $555 million in FY2025.\n## DATA 11 - BRIEF\nA long narrative about the business.\n## DATA 4 - VENDOR\nVendor beta 1.2\n## DEFAULTS\nrf 4.0%\n\n"


def _fact_d(i, quote, usable=True, metric="revenue", **kw):
    d = {"fact_id": f"F{i}", "source": "pack:data-5", "quote": quote, "entity": "XYZ", "metric": metric, "period": "FY2025", "value": None, "unit": "", "basis": "filed_gaap",
         "duration_years": None, "usable": usable, "unusable_reason": None}
    d.update(kw)
    return d


def test_item3_the_summary_is_filtered_by_sentence_and_the_drops_are_listed():
    d = {"summary": "XYZ makes widgets. Analysts expect growth next year. The stock could reach $555 soon. Revenue was $555 million in FY2025. Margins are 31.2% of sales.",
         "facts": []}
    facts = {"r26_blind_source": REMOVED_LINES}
    view, audit = blind.stage2_dossier_view(d, BLIND, facts)
    assert view["summary"] == "XYZ makes widgets. The stock could reach $555 soon. Revenue was $555 million in FY2025. Margins are 31.2% of sales."
    # $555 is also a filed number (the blind pack's DATA 5 line): a listed exception to the number test, so those sentences stay
    assert audit["summary_drops"] == [{"source": "dossier:summary", "rule": "analyst_estimate", "sentence": "Analysts expect growth next year."}]


def test_item3_a_number_that_only_a_removed_line_holds_drops_the_sentence_and_withholds_the_fact():
    removed_only = {"r26_blind_source": {"removed_lines": [{"cls": "consensus", "section": "DATA 8", "id": "data-8", "text": "- CONSENSUS EPS next FY: 77.7"}], "spans": REMOVED_LINES["spans"]}}
    d = {"summary": "Earnings of 77.7 per share are expected. The company has 12 vessels.",
         "facts": [_fact_d(1, "Revenue was $555 million in FY2025."), _fact_d(2, "Management cites EPS of 77.7 for the year."),
                   _fact_d(3, "Analysts raised their price target."), _fact_d(4, "The street consensus is 5.", usable=True),
                   _fact_d(5, "Revenue rose.", metric="share price"), _fact_d(6, "Unusable thing", usable=False)]}
    view, audit = blind.stage2_dossier_view(d, BLIND, removed_only)
    assert view["summary"] == "The company has 12 vessels." and audit["summary_drops"][0]["rule"].startswith("removed_class_number:")
    kept = [f["fact_id"] for f in view["facts"]]
    assert kept == ["F1", "F6"] and view["withheld_from_stage2"] == 4                         # the unusable F6 is not judged: it is never shown anyway
    why = {x["fact_id"]: x["rule"] for x in audit["facts_withheld"]}
    assert why["F2"].startswith("quote:removed_class_number:") and why["F3"].startswith("quote:") and why["F5"].startswith("metric:")
    txt = late.render_dossier(view)
    assert "FACTS WITHHELD FROM THIS STAGE: 4" in txt and "77.7" not in txt and "[F3]" not in txt
    assert d["facts"][1]["fact_id"] == "F2" and d["summary"].startswith("Earnings of 77.7")                      # the input is not changed
    assert blind.text_leaks(txt, BLIND, removed_only) == [] and blind.text_leaks("EPS 77.7", BLIND, removed_only)[0]["form"] == "77.7"


def test_item3_without_the_facts_only_the_sentence_rule_runs_and_it_says_so():
    view, audit = blind.stage2_dossier_view({"summary": "Analysts like it. Fine.", "facts": []})
    assert view["summary"] == "Fine." and "number_audit_not_run" in audit["stamps"]


def test_item3_stage_2_is_given_the_audited_view_and_cannot_cite_a_withheld_fact(tmp_path, monkeypatch):
    d = dossier()
    d["summary"] = "XYZ makes things. Analysts are bullish."
    d["facts"].append(_fact_d(7, "Analysts set a price target of 12 dollars.", source="pack:data-5"))
    facts = {"r26_blind_source": REMOVED_LINES}
    f = fcast()
    f["scenarios"]["Base"]["near_term"]["fact_ids"] = ["F7"]
    script = Script(sub(f), sub(fcast()), sub(fcast()), sub(fcast()))
    monkeypatch.setattr(prov, "chat", script)
    fc = r26.run_stage2(run_dir=tmp_path, model="m", blind_pack=BLIND, dossier=d, op_margin_bar=DBAR, valuation=valuation(), seed=1, verbose=False, facts=facts)
    text = script.bodies[0]["messages"][0]["content"]
    assert "Analysts are bullish" not in text and "price target of 12" not in text and "FACTS WITHHELD FROM THIS STAGE: 1" in text and "XYZ makes things." in text
    s1 = fc["samples"][0]
    assert s1["repair_used"] and s1["problem_history"][0][0]["problem"] == "fact_id_not_in_dossier"
    aud = fc["stage2_inputs_audit"]
    assert [x["fact_id"] for x in aud["dossier_view"]["facts_withheld"]] == ["F7"] and aud["dossier_view"]["summary_drops"][0]["sentence"] == "Analysts are bullish."
    assert aud["dossier_leaks_after_filter"] == [] and json.loads((tmp_path / "forecasts.json").read_text("utf-8"))["stage2_inputs_audit"]["pack"]["lines_in"] > 0


def test_item3_the_leak_audit_of_the_blind_pack_is_unchanged_by_the_refactor():
    facts = {"r26_blind_source": {"removed_lines": REMOVED_LINES["removed_lines"], "spans": REMOVED_LINES["spans"]}}
    a = blind.r26_leak_audit("## DATA 5 - FILINGS\nRevenue was $555 million in FY2025.\n## DATA 11 - BRIEF\nA narrative with 77.7 in it.", facts)
    assert [x["form"] for x in a["leaks"]] == ["77.7"] and a["exceptions"] and a["exceptions"][0]["form"] == "555"


# ---------------------------------------------------------------- 4. stage 2 reads the filed-data lines only

def test_item4_the_pack_is_cut_to_its_filed_and_derived_lines():
    text, rep = blind.filed_only_pack(BLIND, REMOVED_LINES["spans"])
    assert "Revenue was $555 million" in text and "rf 4.0%" in text and "## DATA 5" in text and "## DEFAULTS" in text
    for gone in ("narrative about the business", "## DATA 11", "Vendor beta", "## DATA 4"):
        assert gone not in text, gone
    assert rep["dropped_by_class"] == {"narrative": 2, "aggregator": 2} and set(rep["sections_cut"]) == {"DATA 11 - BRIEF", "DATA 4 - VENDOR"}
    assert "\n\n\n" not in text and rep["lines_in"] == 10 and rep["lines_kept"] == len(text.split("\n"))
    t2, _ = blind.filed_only_pack("a\nb", [])                                           # no span covers a line: its class is unknown and it is cut
    assert t2 == ""


def test_item4_stage_2_receives_the_cut_pack_and_stamps_when_it_cannot(tmp_path, monkeypatch):
    script = Script(sub(fcast()), sub(fcast()), sub(fcast()))
    monkeypatch.setattr(prov, "chat", script)
    fc = r26.run_stage2(run_dir=tmp_path, model="m", blind_pack=BLIND, dossier=dossier(), op_margin_bar=DBAR, valuation=valuation(), seed=1, verbose=False,
                        facts={"r26_blind_source": REMOVED_LINES})
    t = script.bodies[0]["messages"][0]["content"]
    assert t.startswith("## DATA 5 - FILINGS") and "narrative about the business" not in t and "Vendor beta" not in t and "stage2_pack_not_filtered:no_spans" not in fc["stamps"]
    script = Script(sub(fcast()), sub(fcast()), sub(fcast()))
    monkeypatch.setattr(prov, "chat", script)
    fc2 = r26.run_stage2(run_dir=tmp_path / "b", model="m", blind_pack=BLIND, dossier=dossier(), op_margin_bar=DBAR, valuation=valuation(), seed=1, verbose=False)
    assert "stage2_pack_not_filtered:no_spans" in fc2["stamps"] and "narrative about the business" in script.bodies[0]["messages"][0]["content"]


# ---------------------------------------------------------------- 5. stronger fact association

def _chk(quote, value, metric, source_text=None, entity="Danaos", src="page:https://x.test/a"):
    f = _fact(quote=quote, value=value, metric=metric, entity=entity, source=src)
    return r26.check_fact(f, source_text if source_text is not None else f"Danaos {metric} notes. " + quote)


@pytest.mark.parametrize("quote,value,metric,ok", [
    ("Operating revenues increased by $12.2 million, to $274.4 million in the quarter.", 274.4, "operating revenues", True),
    ("Operating revenues increased by $12.2 million, to $274.4 million in the quarter.", 274.4, "net income", False),               # the nearest term is revenue
    ("Q2 net income $151.8M, H1 net income $292.2M, H1 adj EBITDA $367.4M; TCE ~$35.5k/day", 367.4, "adjusted EBITDA", True),
    ("Q2 net income $151.8M, H1 net income $292.2M, H1 adj EBITDA $367.4M; TCE ~$35.5k/day", 367.4, "net income", False),
    ("Q2 net income $151.8M, H1 net income $292.2M, H1 adj EBITDA $367.4M; TCE ~$35.5k/day", 35500, "TCE per day", True),
    ("Revenue growth of 12.5% in the year", 12.5, "revenue growth", True),
    ("Revenue growth of 12.5% in the year", 12.5, "revenue", False),                                                               # the value is a growth rate
    ("The board declared a quarterly dividend of $1.00 per share.", 1.0, "quarterly dividend", True),                                  # "per share" qualifies, it is no metric
    ("The fleet totals 75 vessels.", 75, "fleet size", True),
    ("The company reported a figure of 41.7 for the period.", 41.7, "operating income", False),                                         # no vocabulary term near the value
    ("The company reported net income of 41.7. Revenue was flat.", 41.7, "net income", True),                                          # the sentence is the value's own
    ("Revenue was flat. The company reported 41.7 for the period.", 41.7, "revenue", False),                                           # revenue is in the other sentence
    ("Net income was $5 million", 9.0, "net income", False),                                                                           # the value is not in the quote
    ("Net income was $5 million", 5.0, "something unlisted", False),                                                                   # the metric names no vocabulary term
])
def test_item5_prose_the_registered_metric_is_the_nearest_metric_term_to_the_value(quote, value, metric, ok):
    r = _chk(quote, value, metric)
    assert r["usable"] is ok, (r["association_status"], r["association_detail"])
    if not ok:
        assert r["unusable_code"] == "association_uncertain" and r["unusable_reason"].startswith("association_uncertain: ") and r["proximity_status"] == "near"


def test_item5_a_fact_with_no_value_has_nothing_to_associate():
    r = _chk("The fleet is chartered through 2029.", None, "operating revenues", "Danaos operating revenues. The fleet is chartered through 2029.")
    assert r["usable"] and r["association_status"] == "no_value"


def test_item5_the_vocabulary_is_one_generic_list():
    assert [t[0] for t in r26.metric_terms("Operating income and net income, free cash flow, capex and the order book")] == [
        "operating_income", "net_income", "free_cash_flow", "capex", "backlog"]
    assert [t[0] for t in r26.metric_terms("income tax and EBITDA margin")] == ["tax", "ebitda_margin"]
    assert r26.metric_terms("nothing relevant here at all") == []
    assert "operating_income" in r26.METRIC_VOCABULARY and all(isinstance(v, tuple) for v in r26.METRIC_VOCABULARY.values())
    assert r26.sentence_spans("Revenue was $5.2 billion. Net income rose.") == [(0, 25), (26, 42)]


TABLE = ("## DATA 5 - DANAOS FISCAL YEARS\n| FY | revenue | operating income | net income |\n| --- | --- | --- | --- |\n| 2018 | 0.459 | -0.012 | -0.033 |\n| 2019 | 0.447 | 0.201 | 0.131 |\n\n"
         "Other text follows here.")
ROW = "| 2019 | 0.447 | 0.201 | 0.131 |"


@pytest.mark.parametrize("value,metric,ok", [(0.201, "operating income", True), (0.131, "net income", True), (0.447, "revenue", True), (0.201, "net income", False),
                                             (0.131, "operating income", False), (0.447, "net income", False)])
def test_item5_table_the_header_cell_of_the_values_column_must_name_the_metric(value, metric, ok):
    r = _chk(ROW, value, metric, TABLE, src="pack:data-5")
    assert r["table"] is True and r["usable"] is ok, (r["association_status"], r["association_detail"])
    assert (r["association_status"] == "associated_by_table_header_and_row_label") is ok


def test_item5_a_table_adds_its_header_row_and_row_label_to_the_proximity_window():
    src = "| Metrics for the year | Segment | Total |\n" + "| --- | --- | --- |\n" + "| Net income | 100 | $292,236 |\n"
    r = _chk("| Net income | 100 | $292,236 |", 292236, "net income", src, entity="Danaos")
    assert r["table"]
    assert r["missing_words"] == ["danaos"] and not r["usable"]                           # the entity is in neither the window nor the header
    r2 = _chk("| Net income | 100 | $292,236 |", 292236, "net income", src.replace("Metrics for the year", "Danaos metrics"), entity="Danaos")
    assert r2["usable"] and r2["missing_words"] == []                                      # the header row is part of the window
    ctx = r26.table_context(src, *r26.find_quote(src, "| Net income | 100 | $292,236 |")[0])
    assert ctx["row_label"] == "Net income" and ctx["header_row"].startswith("| Metrics for the year")
    assert r26.table_context("Prose line with a single | pipe only.", 5, 10) is None


def test_item5_a_search_result_line_is_not_a_table_and_a_filing_table_with_padded_cells_uses_the_window_rule():
    snippet = "Danaos Q2 | https://x.test/q2 | Operating revenues increased to $274.4 million in the quarter."
    r = _chk("Operating revenues increased to $274.4 million in the quarter.", 274.4, "operating revenues", snippet, src="query:Q1")
    assert r["usable"] and r["table"] is False
    padded = "| Interest expense | ​ | ​ | (19,986) | ​ | — |\n"
    r2 = _chk("Interest expense | ​ | ​ | (19,986)", -19986, "interest expense", "Danaos\n" + padded, entity="Danaos", src="pack:primary-p1")
    assert r2["table"] and r2["usable"]


def test_item5_the_dossier_carries_the_association_statuses(tmp_path):
    ev = r26.Evidence(PACK, {})
    led = r26.Ledger(ev, "XYZ Corp", "XYZ")
    out = led.register({"facts": [_fact(fact_id="D", source="pack:primary-p1", quote="Net income was $5 million.", value=9.0, entity="XYZ", metric="net income")]})
    f = led.facts[0]
    assert f["statuses"]["association_status"] == "association_uncertain" and f["statuses"]["association_detail"] == "value_not_in_quote" and f["usable"] is False
    assert "association_uncertain: value_not_in_quote" in out["registered"][0]["status"]
    assert "association_uncertain" in r26.STAGE1_TASK and "nearest" in r26.STAGE1_TASK and "nearest" in json.dumps(r26.REGISTER_FACTS_TOOL)


# ---------------------------------------------------------------- 6. domain checks

@pytest.mark.parametrize("mut,field,problem", [
    (lambda f: f["scenarios"]["Base"].__setitem__("prob", 1.2), "Base.prob", "probability_outside_0_1"),
    (lambda f: f["scenarios"]["Base"].__setitem__("prob", -0.1), "Base.prob", "probability_outside_0_1"),
    (lambda f: f["scenarios"]["Bear"].__setitem__("prob", 0.35), "scenarios", "probabilities_do_not_sum_to_1"),
    (lambda f: f["scenarios"]["Base"]["near_term"].__setitem__("rev_growth", [0.1, -1.2]), "Base.near_term.rev_growth", "revenue_would_be_negative"),
    (lambda f: f["scenarios"]["Base"]["normalized"].__setitem__("rev_growth", -1.5), "Base.normalized.rev_growth", "revenue_would_be_negative"),
    (lambda f: f.__setitem__("discount_rate", 0.03), "Base.terminal_g", "terminal_g_not_below_discount_rate"),
    (lambda f: f["scenarios"]["Bull"].__setitem__("terminal_g", 0.10), "Bull.terminal_g", "terminal_g_not_below_discount_rate"),
    (lambda f: f["scenarios"]["Base"].__setitem__("terminal_ronic", 0.0), "Base.terminal_ronic", "terminal_ronic_not_positive"),
    (lambda f: f["scenarios"]["Base"].__setitem__("terminal_ronic", -0.05), "Base.terminal_ronic", "terminal_ronic_not_positive"),
])
def test_item6_each_domain_check_is_named(mut, field, problem):
    f = forecast()
    mut(f)
    assert (field, problem) in probs(f), probs(f)


def test_item6_the_edges_that_are_valid():
    f = forecast()
    f["scenarios"]["Base"]["near_term"]["rev_growth"] = [-1.0, 0.0]                      # revenue falling to zero is not negative; 0.0 is a value
    f["scenarios"]["Base"]["prob"], f["scenarios"]["Bull"]["prob"], f["scenarios"]["Bear"]["prob"] = 0.505, 0.25, 0.25            # sum 1.005 is within 0.01
    assert rf.validate_forecast(f, DOSSIER) == []
    f["scenarios"]["Base"]["prob"] = 0.52                                                  # sum 1.02 is not
    assert ("scenarios", "probabilities_do_not_sum_to_1") in probs(f)
    g = forecast(discount_rate=0.0301)
    assert rf.validate_forecast(g, DOSSIER) == []                                          # just above terminal_g
    g = forecast(discount_rate=0.03)
    assert ("Base.terminal_g", "terminal_g_not_below_discount_rate") in probs(g)


def test_item6_a_domain_failure_gets_the_one_repair_and_the_message_says_so(tmp_path, monkeypatch):
    bad = fcast()
    bad["scenarios"]["Base"]["terminal_ronic"] = -0.1
    script, fc, _, _ = run_stages(tmp_path, monkeypatch, [sub(bad), sub(fcast()), sub(fcast()), sub(fcast())], stages=(2,))
    assert fc["samples"][0]["repair_used"] and fc["samples"][0]["status"] == "valued"
    msg = [m["content"] for m in script.bodies[1]["messages"] if m["role"] == "tool"][0]
    assert "terminal_ronic_not_positive" in msg and "domain rules" in msg and "Structure only" not in msg


# ---------------------------------------------------------------- 7. stage-2 acceptance is idempotent

def _two_in_one_turn(a, b):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "submit_forecast", "arguments": a}}, {"function": {"name": "submit_forecast", "arguments": b}}]}


def test_item7_a_second_submit_in_the_turn_after_acceptance_changes_nothing(tmp_path, monkeypatch):
    _, fc, _, _ = run_stages(tmp_path, monkeypatch, [_two_in_one_turn(fcast(0.40), fcast(0.45)), sub(fcast(0.41)), sub(fcast(0.39))], stages=(2,))
    s = fc["samples"][0]
    assert s["status"] == "valued" and s["submissions"] == 1 and s["repair_used"] is False and s["ignored_submissions"] == 1
    assert s["forecast"]["scenarios"]["Base"]["near_term"]["op_margin"] == [0.40, 0.40]
    assert fc["samples"][1]["ignored_submissions"] == 0


def test_item7_an_invalid_first_call_then_a_valid_one_in_the_turn_is_the_one_repair_and_nothing_after_it_counts(tmp_path, monkeypatch):
    bad = fcast()
    del bad["scenarios"]["Bull"]
    three = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "submit_forecast", "arguments": a}} for a in (bad, fcast(0.40), fcast(0.50))]}
    _, fc, _, _ = run_stages(tmp_path, monkeypatch, [three, sub(fcast()), sub(fcast())], stages=(2,))
    s = fc["samples"][0]
    assert s["status"] == "valued" and s["submissions"] == 2 and s["repair_used"] and s["ignored_submissions"] == 1 and s["forecast"]["scenarios"]["Base"]["near_term"]["op_margin"] == [0.40, 0.40]


def test_item7_after_the_second_failure_a_later_valid_call_does_not_revive_the_sample(tmp_path, monkeypatch):
    bad = fcast()
    del bad["scenarios"]["Bull"]
    three = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "submit_forecast", "arguments": a}} for a in (bad, bad, fcast())]}
    _, fc, _, _ = run_stages(tmp_path, monkeypatch, [three, sub(fcast()), sub(fcast())], stages=(2,))
    s = fc["samples"][0]
    assert s["status"] == "forecast_invalid" and s["forecast"] is None and s["submissions"] == 2 and s["ignored_submissions"] == 1


# ---------------------------------------------------------------- 8. the tax rate: raw and applied

def test_item8_the_raw_and_the_applied_tax_rate_are_recorded_and_a_clipped_rate_is_stamped():
    row = {"pretax_income": 100e9, "tax_provision": 52e9, "operating_income": 20e9, "revenue": 200e9}
    bf = r26.bridge_facts_from_row(row)
    assert bf["tax_rate"] == 0.35 and bf["tax_rate_raw"] == pytest.approx(0.52) and bf["stamps"] == ["tax_rate_clipped"]
    neg = r26.bridge_facts_from_row(dict(row, tax_provision=-3e9))
    assert neg["tax_rate"] == 0.0 and neg["tax_rate_raw"] == pytest.approx(-0.03) and neg["stamps"] == ["tax_rate_clipped"]
    ok = r26.bridge_facts_from_row(dict(row, tax_provision=21e9))
    assert ok["tax_rate"] == ok["tax_rate_raw"] == pytest.approx(0.21) and ok["stamps"] == []
    none = r26.bridge_facts_from_row(dict(row, pretax_income=-1e9))
    assert none["tax_rate"] is None and none["tax_rate_raw"] is None and none["stamps"] == []


def test_item8_the_bridge_shows_both_rates_and_says_clipped_instead_of_measured():
    path = rf.build_path(desk_forecast()["scenarios"]["Base"], DBAR, 100.0)
    clipped = rf.bridge_to_x(path, dict(DFACTS, tax_rate=0.35, tax_rate_raw=0.52))
    assert clipped["status"] == "ok" and rf.TAX_CLIPPED_STAMP in clipped["stamps"] and rf.CALIBRATED_STAMP in clipped["stamps"]
    row = clipped["rows"][0]
    assert row["tax_rate"] == 0.35 and row["tax_rate_raw"] == pytest.approx(0.52) and row["tax_rate_clipped"] is True
    assert "tax_rate_clipped: measured 0.5200, applied 0.3500" in " ".join(clipped["assumptions"]) and "tax_rate_measured" not in clipped["assumptions"]
    plain = rf.bridge_to_x(path, dict(DFACTS, tax_rate=0.25, tax_rate_raw=0.25))
    assert plain["assumptions"][-1] == "tax_rate_measured" and rf.TAX_CLIPPED_STAMP not in plain["stamps"] and plain["rows"][0]["tax_rate_clipped"] is False
    assert "tax_rate_raw" not in rf.bridge_to_x(path, DFACTS)["rows"][0]                        # a caller that gave no raw rate gets the old row
    vf = rf.value_forecast(desk_forecast(), DBAR, 100.0, dict(DFACTS, tax_rate=0.35, tax_rate_raw=0.52), **desk_inputs())
    assert "measured 52.0%, clipped" in late.render_bridge_table(vf)


# ---------------------------------------------------------------- 9. the crux cites fact ids

def test_item9_code_pulls_the_source_the_date_and_the_verbatim_quote_from_the_fact():
    d = dossier()
    d["facts"][0].update(source="pack:primary-p1", quote="Operating revenues increased by $12.2 million in the quarter.")
    crux = [{"input": "coe", "reason": "r", "citations": [{"fact_id": "F1"}, {"fact_id": "F4"}]}]
    resolved, problems = r26.resolve_crux_citations(crux, d, "2026-10-19", PACK)
    assert problems == [] and crux[0]["citations"] == [{"fact_id": "F1"}, {"fact_id": "F4"}]            # the model's crux is not changed
    c1, c4 = resolved[0]["citations"]
    assert c1 == {"fact_id": "F1", "source": "pack:primary-p1", "date": c1["date"], "quote": "Operating revenues increased by $12.2 million in the quarter."}
    assert c1["date"] <= "2026-10-19" and re.match(r"^\d{4}-\d{2}-\d{2}$", c1["date"])
    assert c4 == {"fact_id": "F4", "source": f"page:{PAGE_URL}", "date": "2026-10-19", "quote": QUOTE}


def test_item9_a_filing_s_citation_carries_its_filed_date():
    from sec_primary import parse_pack
    pack = PACK.replace("[P1] 6-K earnings release, filed 2026-08-04", "[P1] 6-K earnings release, filed 2026-08-04, accession 0001-26-000001, period 2026-06-30, https://sec.gov/x")
    items = parse_pack(pack)
    assert items and items[0]["filed"] == "2026-08-04"
    d = dossier()
    d["facts"][0].update(source=f"pack:primary-p{items[0]['id'][1:]}", quote="Operating revenues increased by $12.2 million in the quarter.")
    crux = [{"input": "coe", "reason": "r", "citations": [{"fact_id": "F1"}]}]
    assert r26.resolve_crux_citations(crux, d, "2099-01-01", pack)[0][0]["citations"][0]["date"] == "2026-08-04"
    assert r26.resolve_crux_citations(crux, d, "2026-01-01", pack)[0][0]["citations"][0]["date"] == "2026-01-01"                                                                  # never later than the run's date


@pytest.mark.parametrize("cit,needle", [({"fact_id": "F3"}, "is not one"), ({"fact_id": "F99"}, "is not one"), ({"fact_id": "F6"}, "needs 30 to 600"), ({}, "is not one"),
                                        ({"source": "pack:data-5", "date": "2026-01-01", "quote": "x" * 40}, "is not one")])
def test_item9_a_citation_must_name_a_usable_fact_with_a_citable_quote(cit, needle):
    resolved, problems = r26.resolve_crux_citations([{"input": "coe", "reason": "r", "citations": [cit]}], dossier(), "2026-10-19", "")
    assert len(problems) == 1 and problems[0].startswith("crux[1].citations[1].fact_id") and needle in problems[0]
    assert resolved[0]["citations"][0] == cit                                                          # left unresolved


def test_item9_the_stage_3_tool_and_task_ask_for_fact_ids_only(tmp_path, monkeypatch):
    props = late.STATE_CRUX_TOOL["function"]["parameters"]["properties"]["crux"]["items"]["properties"]["citations"]["items"]
    assert list(props["properties"]) == ["fact_id"] and props["required"] == ["fact_id"]
    assert "{fact_id}" in late.stage3_task(None, "2026-10-19") and "You do not type a source, a date or a quote" in late.stage3_task(None, "2026-10-19")
    script, _, rv, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step()])
    c = rv["crux"]
    assert c["stated"][0]["citations"] == [{"fact_id": "F4"}] and c["resolved"][0]["citations"][0]["quote"] == QUOTE and c["translated"][0]["citations"][0]["source"] == PAGE_URL
    assert c["valid"] is True and c["check"]["entries"][0]["citations"][0]["quote_found"] is True
    assert '"fact_id": "F4"' in script.bodies[-1]["messages"][0]["content"] and QUOTE in script.bodies[-1]["messages"][0]["content"]       # stage 4 reads the resolved crux


def test_item9_a_free_text_citation_is_a_form_problem_once_then_invalid(tmp_path, monkeypatch):
    old = crux_args("keep", citations=[{"source": f"page:{PAGE_URL}", "date": "2026-08-04", "quote": QUOTE}])
    script, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [old, old, memo_step()])
    msg = [m["content"] for m in script.bodies[4]["messages"] if m["role"] == "tool"][0]
    assert "malformed" in msg and "fact_id" in msg and rv["crux"]["state"] == "form_failed" and rv["no_call"]
    assert "crux[1].citations[1].source" not in msg                         # the form check does not repeat what the fact-id check already said


# ---------------------------------------------------------------- 10. the TASK wording

def test_item10_the_stage_2_wording():
    t = late.STAGE2_TASK
    assert "A worked example, for illustration only" in t and "delta_pts 2.5" in t and "twelve and a half percent" in t and "write 2.5 for two and a half points" in t
    assert "company-adjusted or non-GAAP fact tells you the direction of a change; it never sets the level of a margin" in t
    assert "year-N mid-cycle margin" in t and "post-year-5 terminal margin" in t
    props = late.scenario_schema()["properties"]
    assert "mid-cycle" in props["normalized"]["properties"]["year"]["description"] and "post-year-5 terminal margin" in props["long_run_margin_op"]["description"]
    assert not re.search(r"\$\s?\d|\d+(\.\d+)?%", t)


def test_item10_the_stage_3_wording():
    t = late.stage3_task(None, "2026-10-19")
    assert "Keep is the default" in t and "Revise only when a dossier fact shows that the forecast contains an error of fact" in t and "a difference from the price or the consensus is never a reason" in t
    assert "You see its numbers, the ids of the facts it cited and its classification labels" in t and "never the level of a margin" in t
    assert "error of fact" in late.revision_tool()["function"]["description"]
    fc = fcast()
    shown = late.render_forecast_numbers(r26.numbers_only(fc))
    assert "facts F1" in shown and "margin persistence structural (facts F1)" in shown and "REASON-MARKER" not in shown


def test_item10_stage_3_sees_cited_ids_and_labels_but_no_prose_even_the_no_duration_sentence():
    fc = fcast()
    del fc["scenarios"]["Base"]["long_run_fact_ids"]
    fc["scenarios"]["Base"]["no_duration_matched_evidence"] = "PROSE-MARKER nothing speaks for ten years"
    shown = late.render_forecast_numbers(r26.numbers_only(fc))
    assert "PROSE-MARKER" not in shown and "no fact matches the duration of the long run" in shown
    assert fc["scenarios"]["Base"]["no_duration_matched_evidence"].startswith("PROSE")             # the input is not changed


# ---------------------------------------------------------------- 11. delta_pts scale

@pytest.mark.parametrize("d,sus", [(0.0, False), (0.02, True), (0.049, True), (0.05, False), (-0.03, True), (2.5, False), (-4.0, False), (50.0, False), (50.01, True), (-120.0, True),
                                   (float("nan"), False), (None, False)])
def test_item11_delta_pts_scale_suspect(d, sus):
    assert rf.delta_pts_scale_suspect(d) is sus


def test_item11_the_stamp_rides_the_path_the_sample_and_a_revision(tmp_path, monkeypatch):
    sc = copy.deepcopy(desk_forecast()["scenarios"]["Base"])
    sc["normalized"]["delta_pts"] = 0.02
    assert rf.DELTA_SCALE_STAMP in rf.build_path(sc, DBAR, 100.0)["stamps"]
    sc["normalized"]["delta_pts"] = 0.0
    assert rf.DELTA_SCALE_STAMP not in rf.build_path(sc, DBAR, 100.0)["stamps"]
    odd = fcast()
    odd["scenarios"]["Bull"]["normalized"]["delta_pts"] = 80.0
    _, fc, rv, _ = run_stages(tmp_path, monkeypatch, [sub(odd), sub(fcast()), sub(fcast()), crux_args("revise"), revision(0.42), memo_step()])
    assert fc["samples"][0]["stamps"] == ["delta_pts_scale_suspect:Bull"] and fc["samples"][1]["stamps"] == [] and fc["samples"][0]["status"] == "valued"        # annotated, still valued


# ---------------------------------------------------------------- 12. the pull record

def test_item12_the_pull_record_covers_every_input_and_the_base_value():
    pre, post = fcast(0.40), fcast(0.40)
    post["discount_rate"] = 0.09
    post["scenarios"]["Base"]["near_term"]["op_margin"] = [0.42, 0.40]
    post["scenarios"]["Base"]["terminal_g"] = 0.02
    post["scenarios"]["Bull"]["terminal_ronic"] = 0.20
    post["scenarios"]["Bear"]["long_run_margin_op"] = 0.30
    post["scenarios"]["Bear"]["fade_years"] = 6
    cview = {"status": "ok", "years": {1: {"op": 0.45}, 2: {"op": 0.46}}}
    items = r26.pull_record(pre, post, DBAR, cview, 400.0, 380.0)
    by = {(i["scenario"], i["item"]): i for i in items}
    names = {"op_margin_y1", "op_margin_y2", "normalized_margin", "long_run_margin_op", "fade_years", "terminal_g", "terminal_ronic"}
    assert set(by) == {(s, n) for s in ("Base", "Bull", "Bear") for n in names} | {("All", "discount_rate"), ("Base", "base_value")}
    assert sorted(k for k, i in by.items() if i["changed"]) == sorted([("All", "discount_rate"), ("Base", "op_margin_y1"), ("Base", "terminal_g"), ("Bull", "terminal_ronic"),
                                                                       ("Bear", "long_run_margin_op"), ("Bear", "fade_years"), ("Base", "base_value")])
    assert by[("Base", "op_margin_y1")]["pull_ratio"] == pytest.approx(0.4) and by[("Base", "op_margin_y1")]["consensus"] == 0.45
    assert by[("Base", "op_margin_y2")]["pull_ratio"] == 0.0 and by[("Base", "op_margin_y2")]["changed"] is False            # 0.0 is a value
    assert by[("Base", "terminal_g")]["consensus"] is None and by[("Base", "terminal_g")]["pull_ratio"] is None
    assert (by[("Base", "base_value")]["pre"], by[("Base", "base_value")]["post"]) == (400.0, 380.0) and by[("All", "discount_rate")]["scenario"] == "All"
    assert not any(i["item"] == "base_value" for i in r26.pull_record(pre, post, DBAR, cview))


def test_item12_a_revision_records_the_base_value_pre_and_post(tmp_path, monkeypatch):
    _, _, rv, _ = run_stages(tmp_path, monkeypatch, THREE + [crux_args("revise"), revision(0.42), memo_step()], cc=None)
    bv = next(i for i in rv["pull"] if i["item"] == "base_value")
    assert bv["pre"] == pytest.approx(rv["pre"]["base_value"]) and bv["post"] == pytest.approx(rv["post"]["base_value"]) and bv["changed"] is True


# ---------------------------------------------------------------- 13. the memo's prose numbers

FACTS_FOR_MEMO = [{"fact_id": "F1", "value": 4.7, "quote": "Backlog of $3.1 billion runs for 4.7 years; margin 31.2%.", "usable": True},
                  {"fact_id": "F2", "value": 12, "quote": "twelve ships", "usable": True}]
PROSE_ROWS = ROWS + [{"label": "Margin of safety", "value": 0.0239, "kind": "pct", "group": "V"}, {"label": "Discount rate", "value": 0.088, "kind": "pct", "group": "V"}]


def _prose(memo, facts=FACTS_FOR_MEMO, cited=()):
    v = late.verify_memo("SECTION 0\nVerdict: hold\nSECTION 1\n" + memo, PROSE_ROWS, facts, cited)
    return v, [d["memo"] for d in v["details"] if d["flag"] == "memo_prose_number_mismatch"]


@pytest.mark.parametrize("memo,bad", [
    ("The margin of safety is thin at 2.4% and the discount rate 8.8% looks fair.", []),                  # table numbers, in prose
    ("The company trades well above 400 dollars ($400.00).", []),
    ("The cushion is 239 bps over the price.", []),                                                          # basis points of a table percentage
    ("Free cash flow could rise 17.3% a year.", ["17.3%"]),
    ("It earns $777 million.", ["$777"]),
    ("Leverage is 2.5x.", ["2.5x"]),
    ("It beat the plan by 80 bps.", ["80 bps"]),
    ("Up since 2019 and in FY2026 (2026-10-19), on 12 ships, in Q3.", []),                                  # years, dates and counts carry no mark
    ("The backlog of $3.1 billion (F1) runs 4.7 years at a 31.2% margin.", []),                             # the numbers of a fact the memo names
    ("The backlog of $3.1 billion runs long.", ["$3.1"]),                                                    # F1 is neither cited nor named
    ("The backlog is $3,100 million.", ["$3,100"]),                                                          # F1 not named: nothing allows it
    ("As F1 says, backlog was $3,100 million.", []),                                                         # the unit word is not read: 3.1 billion is 3,100 million
])
def test_item13_prose_numbers_must_be_the_tables_or_a_named_fact_s(memo, bad):
    v, got = _prose(memo)
    assert got == bad and ((v["annotations"] == ["memo_prose_number_mismatch"]) is bool(bad)) and v["flags"] == []


def test_item13_cited_facts_count_without_being_named_and_a_labelled_mismatch_is_not_reported_twice():
    v, got = _prose("The backlog is $3.1 billion.", cited=["F1"])
    assert got == []
    v, got = _prose("Base value per share: $999.99 and Price: $400.")
    assert v["flags"] == ["memo_number_mismatch"] and got == [] and v["annotations"] == []                  # gated by the label check, not re-read as prose
    v, got = _prose("Base value per share: $409.61 but also $55.5 elsewhere.")
    assert v["flags"] == [] and got == ["$55.5"]


def test_item13_the_prose_flag_reports_and_does_not_gate(tmp_path, monkeypatch):
    add = lambda memo: memo + "\nThe business earns 17.3% on capital and $777 million of cash."
    _, _, _, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step(mutate=add)])
    assert "memo_prose_number_mismatch" in fi["flags"] and fi["verifier"]["annotations"] == ["memo_prose_number_mismatch"] and fi["verifier"]["flags"] == []
    assert "memo_prose_number_mismatch" not in fi["non_actionable_reasons"] and "memo_prose_number_mismatch" not in fi["verdict"]["r26"]["non_actionable_reasons"]
    assert {d["memo"] for d in fi["verifier"]["details"]} == {"17.3%", "$777"} and all("context" in d for d in fi["verifier"]["details"])
    _, _, _, fi2 = run_stages(tmp_path / "b", monkeypatch, THREE + [crux_args("keep"), memo_step()])
    assert fi2["verifier"]["annotations"] == [] and "memo_prose_number_mismatch" not in fi2["flags"]               # a memo that copies the table is clean


def test_item13_the_labelled_mismatches_still_gate():
    v = late.verify_memo("SECTION 0\nVerdict: hold\nSECTION 1\nBase value per share: $1.00", ROWS, [], ())
    assert v["flags"] == ["memo_number_mismatch"] and v["annotations"] == []


# ---------------------------------------------------------------- 14. unfilled contract numbers

def test_item14_unfilled_contract_numbers_make_a_result_non_actionable(tmp_path, monkeypatch):
    _, _, _, fi = run_stages(tmp_path, monkeypatch, THREE + [crux_args("keep"), memo_step()])
    r = fi["verdict"]["r26"]
    assert r["contract_unfilled"] == ["conviction_score", "business_quality_moat", "reentry_tranches"]
    assert fi["actionable"] is False and r["actionable"] is False and fi["non_actionable_reasons"] == ["contract_fields_unfilled"]
    assert fi["flags"] == []                                              # a reason, not a flag
    for k in r["contract_unfilled"]:
        assert fi["verdict"].get(k) is None


# ---------------------------------------------------------------- 15. early_fade_stress

def test_item15_a_beyond_year_5_alternative_is_an_early_fade_stress():
    f = desk_forecast()
    f["scenarios"]["Base"]["normalized"]["fact_ids"] = ["F1"]
    f["scenarios"]["Base"]["long_run_fact_ids"] = ["F4"]
    d = {"facts": DOSSIER["facts"] + [{"fact_id": "F4", "duration_years": 7.5, "usable": True}, {"fact_id": "F5", "duration_years": 5.0, "usable": True}]}
    alts = rf.alt_paths(f, d, DBAR, 100.0, DFACTS, **desk_inputs())
    assert [(a["fact_id"], a["label"]) for a in alts] == [("F1", "alt_path_after_evidence_expiry"), ("F4", "early_fade_stress")]
    assert "evidence_outlasts_explicit_years" in alts[1]["stamps"] and alts[1]["value"] is not None
    f["scenarios"]["Base"]["long_run_fact_ids"] = ["F5"]
    assert rf.alt_paths(f, d, DBAR, 100.0, DFACTS, **desk_inputs())[-1]["label"] == "alt_path_after_evidence_expiry"                  # exactly 5 years is within the explicit years
    txt = late.render_diagnostics({"alt_paths": alts, "stamps": []})
    assert "Early-fade stress: the evidence of F4 speaks for 7.5 years, beyond the five explicit years" in txt and "If the evidence of F1 (speaks for 4.7 years) expires" in txt
    assert "This is a stress; it replaces nothing." in txt
