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
    got = contract.check_task(case["task"], case["reply"], PACKET, *([case["point_ids"]] if "point_ids" in case else []))
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
    ("1.2 billion", "revenue of $1.2 billion", True),           # AUDIT_M5: no wanted currency matches a printed one (tables print "$ 1,234")
    ("$1.2 billion", "revenue of $1,200 million", True),
    ("$1.2 billion", "revenue of $0.0012 trillion", True),       # ruling 1.1: tn converts with k / m / bn
    ("1.2 billion", "Total revenue | 1,200 | 1,100", False),     # a bare 1,200 is not 1.2 billion
    ("1.2 billion", "$ in Millions | Total revenue | 1,200", False),   # a scale only in a heading is not read
    ("1.2 billion", "revenue of 1.23 billion", False),
    ("1.2 billion", "a margin of 1.2%", False),
    ("1.2 billion", "a ratio of 1.2", False),
    ("1,200 thousand", "1.2 million", True),
    ("15.4%", "a margin of 15.4", False),
    ("15.4", "a margin of 15.4%", False),                        # ruling 1.1: a bare figure matches only a bare figure
    ("15.4", "a ratio of 15.4x", False),
    ("15.4", "a price of $15.4", True),                          # AUDIT_M5: as above; the units must still be equal
    ("15.4", "a ratio of 15.4", True),
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
    item = "Total revenue 1,234 in fiscal 2025, up 12% across 3 segments"
    c = {"claim": claim, "fact_ids": ["F1"], "quotes": [], "numbers": numbers, "confidence_basis": "stated"}
    assert contract.check_claim(c, {"F1": item}, "ACME")["support"] == want


# ---------------------------------------------------------------- WO_M4: the CROSS_CHECK_M rulings, each failing input of the reply

def _chk(items, claim, numbers, fact_ids=("F1",), ticker=None):
    c = {"claim": claim, "fact_ids": list(fact_ids), "quotes": [], "numbers": numbers, "confidence_basis": "x"}
    return contract.check_claim(c, items, ticker)["support"]


@pytest.mark.parametrize("items,claim,numbers,fact,want", [
    # 1.1 A: trillion against million
    ({"F1": "Cash was $10.6 million."}, "Cash was $10.6 trillion.", ["$10.6 trillion"], "F1", "number_not_found"),
    # 1.1 B: a plural scale word and a multiple against a percent
    ({"P1": "Operating margin was 12.5%."}, "Debt is 12.5 billions (12.5x EBITDA).", ["12.5 billions", "12.5x"], "P1",
     "number_not_found"),
    # 1.1 reverse, MA P1: "$10.6T" is a trillion, not a bare $10.6
    ({"P1": "gross dollar volume of $10.6T"}, "Diluted EPS was $10.60", ["$10.60"], "P1", "number_not_found"),
    ({"P1": "gross dollar volume of $10.6T"}, "GDV was $10,600 billion", ["$10,600 billion"], "P1", "supported"),
    ({"P1": "up 50 bps and 1.5 percentage points"}, "Margin rose 50 basis points", ["50 bps"], "P1", "supported"),
    ({"P1": "up 50 bps and 1.5 percentage points"}, "Margin rose 50%", ["50%"], "P1", "number_not_found"),
    ({"P1": "up 50 bps and 1.5 percentage points"}, "Share rose 1.5 ppt", ["1.5 ppt"], "P1", "supported"),
    ({"P1": "up 50 bps and 1.5 percentage points"}, "Share rose 1.5%", ["1.5%"], "P1", "number_not_found"),
    # 1.2 A: a number after "." is read on the claim side
    ({"F1": "Revenue increased."}, "Revenue grew approx.99%.", [], "F1", "number_not_listed"),
    # 1.2 B: ISO currency codes glued to the number
    ({"F1": "Revenue increased."}, "Debt is CHF990m (JPY50bn).", [], "F1", "number_not_listed"),
    ({"F1": "Debt is CHF990m."}, "Debt is CHF990m.", ["CHF990m"], "F1", "supported"),
    ({"F1": "Debt is $990m."}, "Debt is CHF990m.", ["CHF990m"], "F1", "number_not_found"),
    # 1.2 C: "est.$999 million" keeps its currency, and a euro figure is not a dollar figure
    ({"F1": "Debt was €999 million."}, "Debt was est.$999 million", ["est.$999 million"], "F1", "number_not_found"),
    # a number glued to letters is still not a figure
    ({"F1": "Revenue increased."}, "H100 demand in Q3 FY26 per F1", [], "F1", "supported"),
    # 1.3: a range's lower bound takes the upper bound's unit, in claims and items alike
    ({"P1": "Operates in 8 countries with a 10% tax rate."}, "Guidance is 8-10% revenue growth.", ["8-10%"], "P1", "number_not_found"),
    ({"P1": "Operates in 8 countries with a 10% tax rate."}, "Guidance is 8 to 10% revenue growth.", ["8%", "10%"], "P1",
     "number_not_found"),
    ({"P1": "Revenue guidance of $4.60-$4.64 billion."}, "Low-end revenue guidance is $4.60 billion", ["$4.60 billion"], "P1",
     "supported"),
    ({"P1": "Growth of 8–10% is expected."}, "Growth is 8%", ["8%"], "P1", "supported"),
    # 1.4: an omission marker is not a figure (either spelling of the ellipsis)
    ({"P1": "Business text [… 65,074 characters omitted …]"}, "Mastercard has 65,074 employees.", ["65,074"], "P1", "number_not_found"),
    ({"P1": "Business text [... 65,074 characters omitted ...]"}, "It has 65,074 employees.", ["65,074"], "P1", "number_not_found"),
    # 1.5: the year exemption needs a 4-digit token, a year word and a cited item printing it
    ({"P1": "In 2025, demand softened."}, "The company closed 2,025 stores.", [], "P1", "number_not_listed"),
    ({"P1": "In 2025, demand softened."}, "The company closed 2025 stores.", [], "P1", "number_not_listed"),
    ({"P1": "In 2025, demand softened."}, "In 2025 the company closed 2025 stores.", [], "P1", "number_not_listed"),
    ({"P1": "In 2025, demand softened."}, "In 2025 demand softened.", [], "P1", "supported"),
    ({"P1": "In 2025, demand softened."}, "Demand softened in mid-2025 and in Q3 2025.", [], "P1", "supported"),
    ({"P1": "Revenue was $2,025 million."}, "In 2025 demand softened.", [], "P1", "number_not_listed"),
    ({"P1": "It sold 2,025 units."}, "In 2025 demand softened.", [], "P1", "number_not_listed"),
])
def test_cross_check_m_q1_failing_inputs(items, claim, numbers, fact, want):
    assert _chk(items, claim, numbers, (fact,)) == want


def test_the_reader_reads_each_unit_and_currency():
    f = contract.figures_of
    assert f("$10.6T") == {(Decimal("10.6"), "$", "tn")} and f("10.6 T") == {(Decimal("10.6"), "", "")}
    assert f("12.5 billions, 3 thousands, 2 trillions") == {(Decimal("12.5"), "", "bn"), (Decimal("3"), "", "k"), (Decimal("2"), "", "tn")}
    assert f("15.4x and 2×") == {(Decimal("15.4"), "", "x"), (Decimal("2"), "", "x")}
    assert f("RMB 5bn, CNY 5bn, HK$5bn, US$5bn, USD 5bn") == {(Decimal(5), "CNY", "bn"), (Decimal(5), "HK$", "bn"), (Decimal(5), "$", "bn")}
    assert f("we try 5 ways") == {(Decimal(5), "", "")}                       # codes are read in capitals only
    assert f("approx.99%") == set() and f("approx.99%", claim_side=True) == {(Decimal(99), "", "%")}
    assert f("1.2.3", claim_side=True) == {(Decimal("1.2"), "", "")}          # a number inside a number is not read


def test_an_empty_reply_is_malformed():
    got = contract.check_task("business_model", {"task": "business_model", "claims": [], "unknowns": []}, PACKET)
    assert got["status"] == "malformed" and got["shape_errors"] == ["the reply has no claims and no unknowns"]
    got = contract.check_task("business_model", {"task": "business_model", "claims": [], "unknowns": ["no segment data"]}, PACKET)
    assert got["status"] == "ok"


def _tc(point, **kw):
    return {"claim": "Second-quarter revenue was $310.5 million.", "fact_ids": ["P2"], "quotes": [], "numbers": ["$310.5 million"],
            "confidence_basis": "x", "point": point, "change_type": "unchanged", **kw}


def test_thesis_change_points_are_checked_and_unaddressed_points_recorded():
    reply = {"task": "thesis_change", "claims": [_tc("FAKE99")], "unknowns": []}
    got = contract.check_task("thesis_change", reply, PACKET, ["G1", "R1"])
    assert got["status"] == "malformed" and "claims[0].point 'FAKE99' is not one of the earlier points (G1, R1)" in got["shape_errors"]
    got = contract.check_task("thesis_change", {**reply, "claims": [_tc("G1")]}, PACKET)      # no points given: every point is unknown
    assert got["status"] == "malformed"
    got = contract.check_task("thesis_change", {**reply, "claims": [_tc("R1")]}, PACKET, ["G1", "R1", "G3"])
    assert got["status"] == "ok" and got["points_not_addressed"] == ["G1", "G3"]
    got = contract.check_task("thesis_change", {**reply, "claims": [], "unknowns": ["nothing newer"]}, PACKET, ["G1"])
    assert got["status"] == "ok" and got["points_not_addressed"] == ["G1"]
    assert "points_not_addressed" not in contract.check_task("risks", {"task": "risks", "claims": [], "unknowns": ["x"]}, PACKET)


def test_a_currency_word_and_a_printed_date():
    # AUDIT_M5 (smoke run MA, 2026-10-29)
    item = "June 30, 2026 | Cash and cash equivalents | $ 11,291 | Debt EUR 1.2 billion"
    c = {"fact_ids": ["F1"], "quotes": [], "confidence_basis": "stated"}
    chk = lambda claim, numbers: contract.check_claim({**c, "claim": claim, "numbers": numbers}, {"F1": item}, "MA")["support"]
    assert chk("At June 30, 2026, cash was 11,291 (table in millions)", ["11,291"]) == "supported"
    assert chk("At June 30, 2027, cash was 11,291", ["11,291"]) == "number_not_listed"          # a date no cited item prints
    assert chk("Debt was 1.2 billion dollars", ["1.2 billion dollars"]) == "number_not_found"     # "dollars" is $, the item prints EUR
    assert chk("Cash was $11,291 million", ["$11,291"]) == "number_not_listed"                  # scale drift stays unsupported


STMT = ("Consolidated Statements of Operations - USD ($) shares in Millions, $ in Millions | 3 Months Ended\n"
        "Jun. 30, 2026 | Jun. 30, 2025\n"
        "Cash and cash equivalents | $ 11,291 | $ 10,566\n"
        "Class A treasury stock, at cost, 536 and 518 shares, respectively | (92,226) | (83,224)\n"
        "Basic Earnings per Share (in dollars per share) | $ 4.98 | $ 4.08\n"
        "Basic weighted-average shares outstanding (in shares) | 882 | 908\n"
        "Effective tax rate (in percent) | 17 | 18")


def test_statement_heading():
    # THE STATEMENT RULE (M-LIVE 2026-10-29)
    assert contract.statement_heading(STMT) == ("$", "m", "m")
    assert contract.statement_heading("Consolidated Balance Sheets - USD ($) $ in Thousands | Dec. 31, 2025") == ("$", "k", "")
    assert contract.statement_heading("Balance Sheets - USD ($) | Dec. 31, 2025") == ("$", "", "")
    assert contract.statement_heading("Item 1. Business\nWe sell - USD ($) in Millions") is None


def test_the_statement_rule():
    # M-LIVE 2026-10-29: the heading's currency and scale are read row by row, never in a row label or a period cell
    c = {"fact_ids": ["F1"], "quotes": [], "confidence_basis": "stated"}

    def chk(claim, numbers, statements=("F1",)):
        return contract.check_claim({**c, "claim": claim, "numbers": numbers}, {"F1": STMT}, "MA", statements)["support"]

    assert chk("Cash was $11,291 million", ["$11,291 million"]) == "supported"
    assert chk("Cash was $11.291 billion", ["$11.291 billion"]) == "supported"
    assert chk("Cash was 11,291 million", ["11,291 million"]) == "supported"
    assert chk("Cash was $11,291 (table in millions)", ["$11,291"]) == "supported"
    assert chk("Cash was $11,291 billion", ["$11,291 billion"]) == "number_not_found"
    assert chk("Cash was $11,291 thousand", ["$11,291 thousand"]) == "number_not_found"
    assert chk("Cash was $11,291 million", ["$11,291 million"], statements=()) == "number_not_found"   # not a statement: no heading
    assert chk("Treasury stock was $92,226 million", ["(92,226)"]) == "supported"
    assert chk("Treasury stock covered 536 million shares", ["536 million"]) == "number_not_found"     # a row label is not scaled
    assert chk("Basic EPS was $4.98", ["$4.98"]) == "supported"
    assert chk("Basic EPS was $4.98 million", ["$4.98 million"]) == "number_not_found"                 # a per-share row takes no scale
    assert chk("Basic shares were 882 million", ["882 million"]) == "supported"
    assert chk("Basic shares were $882 million", ["$882 million"]) == "number_not_found"               # a share row takes no currency
    assert chk("The tax rate was 17 million", ["17 million"]) == "number_not_found"                    # another "(in ...)" takes nothing
    assert chk("Revenue was $2,026 million", ["$2,026 million"]) == "number_not_found"                 # a period cell takes nothing


def test_a_listed_statement_cell_lists_its_readings():
    # M-LIVE 2026-10-29 (MA financial_health): the model lists the cell as printed and writes the declared scale in the claim
    c = {"fact_ids": ["F1"], "quotes": [], "confidence_basis": "stated"}
    chk = lambda claim, numbers: contract.check_claim({**c, "claim": claim, "numbers": numbers}, {"F1": STMT}, "MA", ("F1",))["support"]
    assert chk("Cash was $11,291 million at June 30, 2026", ["$ 11,291"]) == "supported"
    assert chk("Cash was $11,291 billion at June 30, 2026", ["$ 11,291"]) == "number_not_listed"
    assert chk("Cash was $11,291 million", ["11,291 thousand"]) == "number_not_found"


def test_dates_in_either_order_and_month_form():
    # M-LIVE 2026-10-29: R-file column heads print "Jun. 30, 2026"; CMRE claims wrote "31 Dec 2025"
    item = "Balance Sheets - USD ($) $ in Thousands | Dec. 31, 2025 | Dec. 31, 2024\nCash | $ 519,847 | $ 656,880"
    c = {"fact_ids": ["F1"], "quotes": [], "confidence_basis": "stated"}
    chk = lambda claim: contract.check_claim({**c, "claim": claim, "numbers": ["$519,847"]}, {"F1": item}, "CMRE", ("F1",))["support"]
    assert chk("Cash was $519,847 (table in thousands) at 31 Dec 2025") == "supported"
    assert chk("Cash was $519,847 (table in thousands) at December 31, 2025") == "supported"
    assert chk("Cash was $519,847 (table in thousands) at 31 December 2025") == "supported"
    assert chk("Cash was $519,847 (table in thousands) at 30 Dec 2025") == "number_not_listed"          # a date no item prints
