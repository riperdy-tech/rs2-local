"""The code checks: quotes (the revision-21 normalisation), the hard-evidence rule, the schema, and the prompt-specific fields."""
import pytest

from valuation.muse import checkers as ck
from valuation.muse.checkers import Evidence

S = "Growth delivered: revenue growth in the latest fiscal year +4.2%; 3-year compound growth +6.7%."
D = ("The company has a signed supply agreement for 12 GW of capacity and a backlog of $4.2 billion. We expect demand for our products to remain strong. "
     "Management’s outlook: “stable” demand – no change.")
EV = Evidence({"S": S, "D": D, "R": "[R g1] Revenue growth in the next fiscal year (rate)"})


def entry(pct=50, width="normal", cits=None, reasons=("a reason",)):
    return {"percentile": pct, "width": width, "reasons": list(reasons),
            "citations": cits if cits is not None else [{"section": "S", "quote": "Growth delivered: revenue growth in the latest fiscal year"}]}


def codes(issues):
    return [i.code for i in issues]


# ---- quotes ------------------------------------------------------------------------------------------------------------------------------

def test_the_quote_rule_is_the_revision_21_crux_check_normalisation():
    import crux_check
    assert ck.normalise is crux_check.normalise


def test_a_quote_found_verbatim_passes_and_one_not_found_fails_with_a_message():
    assert ck.check_citation({"section": "S", "quote": "revenue growth in the latest fiscal year"}, EV, "c") is None
    iss = ck.check_citation({"section": "S", "quote": "revenue declined sharply in the latest year"}, EV, "c")
    assert iss.code == "quote" and "not found verbatim in section S" in iss.message and "ellipsis" in iss.message


def test_typographic_quotes_dashes_and_whitespace_are_normalised_but_case_is_not():
    assert ck.check_citation({"section": "D", "quote": "Management's  outlook:\n\"stable\" demand - no change"}, EV, "c") is None
    assert ck.check_citation({"section": "D", "quote": "MANAGEMENT'S OUTLOOK: \"STABLE\" DEMAND"}, EV, "c") is not None


def test_ellipsis_splices_are_not_found():
    assert ck.check_citation({"section": "D", "quote": "signed supply agreement ... backlog of $4.2 billion"}, EV, "c").code == "quote"


def test_quote_length_bounds():
    assert ck.check_citation({"section": "S", "quote": "revenue"}, EV, "c").code == "quote"
    assert ck.check_citation({"section": "S", "quote": "x" * 601}, EV, "c").code == "quote"


def test_a_section_the_prompt_did_not_show_cannot_be_cited():
    ev = Evidence({"S": S})
    iss = ck.check_citation({"section": "D", "quote": "signed supply agreement for 12 GW"}, ev, "c")
    assert iss.code == "section"


def test_a_pooled_pass1_quote_can_be_recited_where_the_section_is_not_shown():
    ev = Evidence({"S": S}, pool=[("D", "The company has a signed supply agreement for 12 GW of capacity and a backlog of $4.2 billion.")])
    assert ck.check_citation({"section": "D", "quote": "signed supply agreement for 12 GW of capacity"}, ev, "c") is None
    assert ck.check_citation({"section": "D", "quote": "we invented this sentence about capacity"}, ev, "c") is not None


def test_unknown_section_and_malformed_citation():
    assert ck.check_citation({"section": "Z", "quote": "revenue growth in the latest"}, EV, "c").code == "schema"
    assert ck.check_citation("not an object", EV, "c").code == "schema"


# ---- hard evidence -------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("quote,ok", [
    ("signed supply agreement for 12 GW of capacity", True),
    ("a backlog of $4.2 billion", True),
    ("We expect revenue of $10.5 billion in 2027", True),                    # a figure with a forward word
    ("management guided to 12% growth", True),
    ("We expect demand for our products to remain strong", False),         # a general outlook sentence
    ("Revenue was $1,234.5 million, up 8.1%", False),                       # a delivered figure without a commitment or guidance
    ("we expect growth in 2027", False),                                    # a bare year is not a figure
    ("capacity constraints may ease", False),                               # a weak word with no figure
    ("the company entered into a long-term contract with a customer", True),
])
def test_the_hard_evidence_rule(quote, ok):
    assert ck.qualifies(quote) is ok


def test_a_position_outside_p10_p90_needs_a_d_or_q_citation_that_qualifies():
    weak = entry(95)                                                          # only an S citation
    assert "hard_evidence" in codes(ck.check_entry("g1", weak, EV))
    general = entry(95, cits=[{"section": "D", "quote": "We expect demand for our products to remain strong"}])
    assert "hard_evidence" in codes(ck.check_entry("g1", general, EV))
    good = entry(95, cits=[{"section": "D", "quote": "signed supply agreement for 12 GW of capacity"}])
    assert ck.check_entry("g1", good, EV) == []
    assert ck.entry_has_hard_evidence(good, EV) and not ck.entry_has_hard_evidence(entry(60), EV)


def test_a_qualifying_quote_in_section_s_does_not_count_as_hard_evidence():
    ev = Evidence({"S": "backlog of $4.2 billion under contract", "D": D})
    e = entry(5, cits=[{"section": "S", "quote": "backlog of $4.2 billion under contract"}])
    assert "hard_evidence" in codes(ck.check_entry("g1", e, ev))


def test_the_band_edges_need_no_hard_evidence():
    assert ck.check_entry("g1", entry(10), EV) == [] and ck.check_entry("g1", entry(90), EV) == []
    assert "hard_evidence" in codes(ck.check_entry("g1", entry(9.9), EV)) and "hard_evidence" in codes(ck.check_entry("g1", entry(90.1), EV))


# ---- schema ------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    entry(4.9), entry(95.1), entry("50"), entry(True), entry(float("nan")), entry(50, width="huge"), entry(50, reasons=()), entry(50, cits=[]),
    entry(50, reasons=("",)), entry(50, reasons=("r",) * 7),
])
def test_schema_failures(bad):
    assert any(i.code == "schema" for i in ck.check_entry("g1", bad, EV))


def test_a_valid_entry_has_no_issues_and_missing_keys_fail():
    assert ck.check_entry("g1", entry(), EV) == []
    assert ck.check_entry("g1", {"percentile": 50}, EV)
    assert ck.check_entry("g1", "x", EV)


def test_parse_json():
    assert ck.parse_json('{"a": 1}') == ({"a": 1}, None)
    assert ck.parse_json('```json\n{"a": 1}\n```')[0] == {"a": 1}
    for bad in ("", "I think the answer is", "[1, 2]", '{"a": 1} trailing', None):
        obj, err = ck.parse_json(bad)
        assert obj is None and err


# ---- the prompts' own fields -----------------------------------------------------------------------------------------------------------

def test_p1_needs_input_entries_and_cited_bull_and_bear_cases():
    cit = {"section": "S", "quote": "revenue growth in the latest fiscal year"}
    obj = {"inputs": {"g1": entry(), "growth_persistence": entry()}, "bull_case": {"text": "Backlog supports growth.", "citation": cit},
           "bear_case": {"text": "Demand may soften.", "citation": cit}}
    ev = Evidence({"S": S, "D": D, "R": "[R g1] x [R growth_persistence] y"})
    assert ck.check_pass1("P1", obj, "operating", ["g1", "growth_persistence"], ev) == []
    miss = dict(obj, inputs={"g1": entry()})
    assert any("growth_persistence is missing" in i.message for i in ck.check_pass1("P1", miss, "operating", ["g1", "growth_persistence"], ev))
    extra = dict(obj, inputs={**obj["inputs"], "ronic": entry()})
    assert any("unexpected input" in i.message for i in ck.check_pass1("P1", extra, "operating", ["g1", "growth_persistence"], ev))
    two = dict(obj, bull_case={"text": "One. Two sentences here.", "citation": cit})
    assert any("one sentence" in i.message for i in ck.check_pass1("P1", two, "operating", ["g1", "growth_persistence"], ev))
    nocit = dict(obj, bear_case={"text": "Demand may soften."})
    assert ck.check_pass1("P1", nocit, "operating", ["g1", "growth_persistence"], ev)


def test_p2_character_must_be_named_and_cite_section_d():
    base = {"inputs": {"margin_target": entry(), "margin_retention": entry()}}
    ev = Evidence({"S": S, "D": D})
    names = ["margin_target", "margin_retention"]
    ok = dict(base, character={"value": "cyclical", "reasons": "swing", "citations": [{"section": "D", "quote": "signed supply agreement for 12 GW"}]})
    assert ck.check_pass1("P2", ok, "operating", names, ev) == []
    for bad in ({"value": "mixed", "reasons": "x", "citations": [{"section": "D", "quote": "signed supply agreement for 12 GW"}]},
                {"value": "cyclical", "reasons": "x", "citations": [{"section": "S", "quote": "revenue growth in the latest fiscal year"}]},
                {"value": "cyclical", "reasons": "x", "citations": []}):
        assert ck.check_pass1("P2", dict(base, character=bad), "operating", names, ev)
    assert ck.check_pass1("P2", base, "operating", names, ev)


def test_p4_needs_exactly_three_cited_risks_each_naming_an_input():
    ev = Evidence({"S": S, "D": D})
    cit = {"section": "S", "quote": "revenue growth in the latest fiscal year"}
    r = {"risk": "A risk.", "input": "g1", "citation": cit}
    ok = {"inputs": {"g_terminal": entry()}, "risks": [r, r, r]}
    assert ck.check_pass1("P4", ok, "operating", ["g_terminal"], ev) == []
    assert ck.check_pass1("P4", dict(ok, risks=[r, r]), "operating", ["g_terminal"], ev)
    assert ck.check_pass1("P4", dict(ok, risks=[r, r, dict(r, input="nope")]), "operating", ["g_terminal"], ev)
    assert ck.check_pass1("P4", dict(ok, risks=[r, r, dict(r, citation={"section": "S", "quote": "an invented sentence for the test"})]), "operating",
                          ["g_terminal"], ev)


def test_synthesis_needs_changes_and_coherence_and_changed_inputs_are_detected():
    ev = Evidence({"S": S, "R": "[R g1] x"})
    ok = {"inputs": {"g1": entry()}, "changes": [], "coherence": "fine"}
    assert ck.check_synthesis(ok, ["g1"], ev) == []
    assert ck.check_synthesis({"inputs": {"g1": entry()}}, ["g1"], ev)
    assert ck.changed_inputs({"g1": {"percentile": 60, "width": "normal"}, "g_terminal": {"percentile": 50, "width": "wide"}},
                             {"g1": {"percentile": 50, "width": "normal"}, "g_terminal": {"percentile": 50, "width": "wide"}}) == ["g1"]
