"""M-CONTRACT: the validator and the support checks of m3m.analysis.v1 (SPEC_m3m_qwen_pipeline.md sections 5 and 7)."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from qwen_c import contract

FIX = Path(__file__).resolve().parent / "fixtures_b"
PACKET = json.loads((FIX / "packet_acme.json").read_text(encoding="utf-8"))
CASES = json.loads((FIX / "contract_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_contract_fixture(case):
    got = contract.check_task(case["task"], case["reply"], PACKET)
    assert got["status"] == case["status"], got["shape_errors"]
    if case["status"] == "malformed":
        assert got["shape_errors"] and got["claims"] == []
        return
    assert [c["support"] for c in got["claims"]] == case["supports"], [c["support_failures"] for c in got["claims"]]
    if "dropped" in case:
        assert sorted(got["dropped_fields"]) == sorted(case["dropped"])
    for c, model in zip(got["claims"], case["reply"]["claims"]):
        for k, v in c.items():                                   # model text is kept unedited, beside the checks
            if k not in ("support", "support_failures"):
                assert model[k] == v
        assert (c["support"] == "supported") == (c["support_failures"] == [])


def test_the_six_spec_fixtures_are_all_present():
    names = {c["name"] for c in CASES}
    assert {"supported_claims", "fabricated_quote", "number_off_by_scale", "unlisted_number", "unknown_fact_id", "missing_field"} <= names


def test_every_failure_is_recorded_and_support_is_the_first_in_order():
    claim = {"claim": "Backlog was $2.5 billion.", "fact_ids": ["P9", "P1"], "quotes": ["not in the text"], "numbers": ["$9.9 billion"],
             "confidence_basis": "x"}
    got = contract.check_claim(claim, contract.evidence_texts(PACKET), "ACME")
    checks = [f["check"] for f in got["support_failures"]]
    assert checks == ["unknown_fact_id", "quote_not_found", "number_not_found", "number_not_listed"]
    assert got["support"] == "unknown_fact_id"


def test_unknown_id_does_not_hide_the_checks_against_the_known_cited_items():
    claim = {"claim": "x", "fact_ids": ["P9", "P1"], "quotes": ["Our backlog was $2.5 billion at year end."], "numbers": ["$2.5 billion"],
             "confidence_basis": "x"}
    got = contract.check_claim(claim, contract.evidence_texts(PACKET), "ACME")
    assert [f["check"] for f in got["support_failures"]] == ["unknown_fact_id"]


def F(v, c="", u=""):
    return Decimal(v).normalize(), c, u


@pytest.mark.parametrize("want,text,found", [
    ("1.2 billion", "revenue of 1,200 million", True),          # the item states the value at that scale
    ("1.2 billion", "revenue of $1.2 billion", True),
    ("1.2 billion", "Total revenue | 1,200 | 1,100", False),     # a bare 1,200 is not 1.2 billion
    ("1.2 billion", "$ in Millions | Total revenue | 1,200", False),   # a scale only in a heading is not read
    ("1.2 billion", "revenue of 1.23 billion", False),
    ("1.2 billion", "a margin of 1.2%", False),
    ("1.2 billion", "a ratio of 1.2", False),
    ("1,200 thousand", "1.2 million", True),
    ("15.4%", "a margin of 15.4", False),
    ("15.4", "a margin of 15.4%", True),
    ("15.4 percent", "a margin of 15.4%", True),
    ("15.4%", "a margin of 15.4 per cent", True),
    ("$1.2 billion", "1.2 billion", False),                      # the currency is not printed there
    ("$1.2 billion", "US$1.2 billion", True),
    ("€1.2 billion", "$1.2 billion", False),
    ("1,200", "1,200.0", True),
    ("1,200", "12,000", False),
    ("1.5", "15", False),
    ("45", "Net income (loss) | (45) | 30", True),               # magnitudes are compared; the parentheses are not read
])
def test_the_number_rule(want, text, found):
    (w,) = contract.figures_of(want)
    assert contract.figure_found(w, contract.figures_of(text)) is found


def test_an_entry_with_no_number_or_two_numbers():
    items = {"P1": "Revenue was $1.2 billion in 2025."}
    base = {"claim": "x", "fact_ids": ["P1"], "quotes": [], "confidence_basis": "x"}
    assert contract.check_claim({**base, "numbers": ["about a billion"]}, items)["support"] == "number_not_found"
    assert contract.check_claim({**base, "numbers": ["$1.2 billion in 2025"]}, items)["support"] == "supported"
    assert contract.check_claim({**base, "numbers": ["$1.2 billion in 2026"]}, items)["support"] == "number_not_found"


def test_a_json_number_entry_is_read_in_plain_decimal_form():
    assert contract.entry_text(1200.0) == "1200.0" and contract.entry_text(1e-05) == "0.00001" and contract.entry_text(7) == "7"
    items = {"P1": "Revenue was 1,200 and the rate 0.00001."}
    base = {"claim": "x", "fact_ids": ["P1"], "quotes": [], "confidence_basis": "x"}
    assert contract.check_claim({**base, "numbers": [1200, 1e-05]}, items)["support"] == "supported"


def test_quote_normalisation_is_whitespace_and_quote_marks_only():
    t = "We sell “industrial pumps” to   utilities — and the company’s valves."
    assert contract.quote_found('We sell "industrial pumps" to utilities', [t])
    assert contract.quote_found("the company's valves.", [t])
    assert not contract.quote_found("we sell", [t])                                    # case is kept
    assert not contract.quote_found("utilities - and", [t])                            # dashes are kept
    assert not contract.quote_found("", [t]) and not contract.quote_found("   ", [t])  # an empty quote is never found


def test_the_ticker_is_not_a_figure_of_the_claim():
    items = {"P1": "Revenue was 1,200."}
    c = {"claim": "Shares of 6758 rose.", "fact_ids": ["P1"], "quotes": [], "numbers": [], "confidence_basis": "x"}
    assert contract.check_claim(c, items, "6758")["support"] == "supported"


def test_the_contract_owns_every_task_id_and_field_set():
    assert contract.CONTRACT == "m3m.analysis.v1"
    assert contract.TASK_IDS == ("business_model", "financial_health", "competitive_position", "growth_thesis", "risks",
                                 "thesis_change", "unresolved_questions")
    assert set(contract.TASK_EXTRA) <= set(contract.TASK_IDS)
    with pytest.raises(Exception):
        contract._type_ok("nope", 1)
    kept, errors, dropped = contract.validate("nope", {})
    assert kept is None and errors == ["unknown task id 'nope'"]
    kept, errors, dropped = contract.validate("risks", ["not", "an", "object"])
    assert errors and kept is None


def test_null_optional_fields_are_allowed_and_kept():
    c = {"claim": "x", "fact_ids": ["P1"], "quotes": [], "numbers": [], "confidence_basis": "x", "mechanism": None, "horizon": "1 year"}
    kept, errors, _ = contract.validate("business_model", {"task": "business_model", "claims": [c], "unknowns": []})
    assert errors == [] and kept["claims"][0]["mechanism"] is None and kept["claims"][0]["horizon"] == "1 year"
    kept, errors, _ = contract.validate("business_model", {"task": "business_model", "claims": [{**c, "counter": 3}], "unknowns": []})
    assert errors == ["claims[0].counter has a wrong type"]


@pytest.mark.parametrize("claim,numbers,want", [
    ("Revenue grew 12%", [], "number_not_listed"),           # audit 2026-10-29: a small unlisted figure was `supported`
    ("Revenue grew 15%", ["15%"], "number_not_found"),
    ("Revenue grew 12%", ["12%"], "supported"),
    ("It has 3 segments", [], "number_not_listed"),
    ("In fiscal 2025 revenue was 1,234 (table in millions)", ["1,234"], "supported"),   # a bare year need not be listed
    ("Cash was 2,034 (table in millions)", [], "number_not_listed"),      # audit 2026-10-29: a year-like amount is not exempt
    ("In fiscal 2031 revenue was 1,234", ["1,234"], "number_not_listed"),  # a year no cited item prints is not exempt
])
def test_every_claim_number_is_listed_and_found(claim, numbers, want):
    item = "Total revenue $ 1,234 in fiscal 2025, up 12% across 3 segments"
    c = {"claim": claim, "fact_ids": ["F1"], "quotes": [], "numbers": numbers, "confidence_basis": "stated"}
    assert contract.check_claim(c, {"F1": item}, "ACME")["support"] == want
