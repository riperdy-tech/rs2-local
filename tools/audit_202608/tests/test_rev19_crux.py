"""Revision 19, Part B (the crux) and bars P2: crux_check, the desk's form check (B2), the desk's own check (B3), the tool layer's citation check (B4),
the schema (B1) and the contract fill (B6).

Fixtures are synthetic: a hand-written pack, snapshot calls and price-implied blocks. No model, no network.
"""
import copy
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyst_tools as at  # noqa: E402
import contract_fill  # noqa: E402
import crux_check as cc  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
from test_desk_checks import _ALL_REASONS_GIVEN, _ctx, _happy_params  # noqa: E402

@pytest.fixture(autouse=True)
def _no_crux_followup(monkeypatch):
    """Revision 21: these sessions script every model turn and their desk runs are directional with no crux, which now earns the one crux follow-up
    (tests/test_rev21_followup.py proves it). They test other behaviour, so the follow-up is switched off here."""
    monkeypatch.setattr(at, "crux_followup_state", lambda *a, **k: None)


TICKER, COMPANY = "TST", "Testco Inc."
Q_CAPEX = "Management expects fiscal 2026 capital expenditure of about $1.1 billion, the lowest since 2021."       # GUIDANCE
Q_DATA5 = "Capital expenditure fell to $0.9 billion as the Phoenix expansion finished in fiscal 2025."              # DATA 5
Q_DATA6A = "Inventory days rose from 61 to 74 over the three years to fiscal 2025."                                  # DATA 6, in its DATA 6A part
Q_DATA3 = "Revenue of $4.20 billion grew 12% year over year in the trailing twelve months."                          # DATA 3
Q_DATA8 = "Analysts expect revenue growth of 14 percent next year per the consensus line shown here."                # DATA 8, context
Q_BRIEF = "Backlog is $9.0B, per a brief that is another model's claim and not company evidence."                    # research-brief row
Q_NEWS = "Testco said on Tuesday that its Phoenix plant will reach full output in the second quarter of 2027."       # a fetched page
PACK = "\n".join([
    "# DATA PACK - TST   (pack revision 19)", "",
    "## DATA 0 - HOW TO READ THIS PACK", "Nothing here is company evidence.", "",
    "## DATA 3 - TRAILING TWELVE MONTHS   [Filed - SEC 10-Q derived]", Q_DATA3, "",
    "## DATA 4 - QUARTERLY   [Filed - 10-Q]", "Quarterly revenue rose in each of the last four quarters of the filing.", "",
    "## DATA 5 - FISCAL-YEAR INCOME & CASH FLOW   [Filed]", Q_DATA5, "",
    "## GROWTH BASE RATES   [Measured]", "A generic line.", "",
    "## DATA 6 - FISCAL-YEAR BALANCE SHEET & CAPITAL STRUCTURE   [Filed]", "The balance sheet is shown by part below.", "",
    "### DATA 6A - WORKING CAPITAL & OPERATING ASSETS   [$B]", Q_DATA6A, "",
    "### DATA 6B - CAPITAL STRUCTURE", "Debt is shown in full.", "",
    "## DATA 7 - FILING-DERIVED QUALITY MEASURES", "Earnings quality is measured on the filed values of the fiscal year.", "",
    "## DATA 8 - CONSENSUS & MULTIPLES   [Aggregator]", Q_DATA8, "",
    "## GUIDANCE & CONSENSUS   [company's own earnings release from SEC EDGAR, then research-brief claims]",
    "COMPANY'S OWN WORDS " + chr(0x2014) + " latest earnings release (SEC 8-K Item 2.02, filed 2026-08-05, https://example.com/8k). The company's statement:",
    Q_CAPEX, "",
    "Research-brief rows (claims by another model, check before relying):", Q_BRIEF, "",
    "## DATA 11 - DEEP RESEARCH BRIEF   [Written by another model, not verified]", "## DATA 3 - a heading inside the brief", "A line in the brief.", "",
    "## DEFAULTS   [each desk input takes this value unless you pass another]", "- coe_anchor: 7.35% | the Base discount rate",
])
URL = "https://www.example.com/news/phoenix"
PAGE_TEXT = "Testco shares rose after earnings. " + Q_NEWS
OTHER_URL = "https://www.other.org/story"
OTHER_TEXT = "Cart makers saw demand rise across the industrial sector this quarter, one analyst said."
FACTS = {"coe_anchor": 0.0735, "terminal_g_default": 0.0234, "terminal_ronic": 0.12, "levels": {"year2": 0.5},
         "reference_path": [0.10, 0.09, 0.03, 0.03, 0.03], "shares_outstanding": 1e9}
PRICE = 100.0


def _blk(value, own, reachable=True, **extra):
    d = {"value": value if reachable else None, "reachable": reachable, "own": own,
         "bound": {"low": None, "high": None, "value_low": None, "value_high": None}, "side": None if reachable else "above",
         "base_at_value": PRICE if reachable else None, "roots_on_grid": 1 if reachable else 0, "bracket": None, "stamps": []}
    d.update(extra)
    return d


def _pi(**over):
    pi = {"coe": _blk(0.098, 0.0801), "growth_years_3_5": _blk(-0.137, 0.03, own_path=[0.03, 0.03, 0.03], shift=-0.167),
          "fade_years": _blk(12.3, 5, bracket_years=[12, 13]), "terminal_g": _blk(None, 0.0234, reachable=False),
          "terminal_ronic": _blk(0.3, 0.12), "year2_level": _blk(0.45, 0.5)}
    pi.update(over)
    return pi


def _cit(source, quote, date="2026-09-30"):
    return {"source": source, "date": date, "quote": quote}


def _entry(input_="coe", citations=None, reason="Why the value differs, by how much."):
    return {"input": input_, "reason": reason, "citations": citations if citations is not None else [_cit("GUIDANCE", Q_CAPEX)]}


def _fetch(url=URL, text=PAGE_TEXT, served=None, **extra):
    c = {"tool": "fetch_page", "call_index": 1, "params": {"url": url}, "url": served or url, "text": text}
    c.update(extra)
    return c


def _answer(base_iv=120.0, crux=None, pi=None, index=3):
    sc = [{"name": "Base", "dcf": {"per_share_iv": base_iv}}, {"name": "Bull", "dcf": {"per_share_iv": base_iv * 1.3}},
          {"name": "Bear", "dcf": {"per_share_iv": base_iv * 0.7}}]
    params = {"cash_flow_life": "perpetual", "scenarios": [{"name": n, "prob": p} for n, p in (("Base", 0.5), ("Bull", 0.25), ("Bear", 0.25))]}
    if crux is not None:
        params["crux"] = crux
    return {"tool": "run_financial_model", "call_index": index, "params": params, "scenario_dcfs": sc,
            "price_implied": _pi() if pi is None else pi, "kelly_sizing": {"quarter_kelly_pct": 5.0}}


def _fill(crux, base_iv=120.0, pi=None, calls_extra=(), price=PRICE, facts=FACTS):
    calls = list(calls_extra) + [_answer(base_iv, crux, pi)]
    filled, prov = contract_fill.fill(calls, {}, facts, price, ticker=TICKER, pack_text=PACK, company=COMPANY)
    return filled, prov


# ---- normalise, pack_sources, fetched_texts ------------------------------------------------------------------------------------------

def test_normalise_nfkc_quotes_dashes_zero_width_whitespace():
    raw = "  The “company”’s   plan — and–more" + chr(0x200B) + " stays" + chr(0xA0) + "" + chr(0xA0) + " as\n\tfiled ﬁ "
    assert cc.normalise(raw) == "The \"company\"'s plan - and-more stays as filed fi"
    assert cc.normalise(None) == "" and cc.normalise("") == ""
    assert cc.normalise("a" + chr(0x2060) + "b" + chr(0x200C) + "c" + chr(0x200D) + "d" + chr(0xFEFF) + "e") == "abcde"
    assert cc.normalise("‘x’ ‚y‛ „z‟") == "'x' 'y' \"z\""
    # case is kept: matching is case-sensitive
    assert cc.normalise("Capital Expenditure") != cc.normalise("capital expenditure")


def test_pack_sources_boundaries():
    s = cc.pack_sources(PACK)
    assert set(s) == {"DATA 3", "DATA 4", "DATA 5", "DATA 6", "GUIDANCE"}
    assert Q_DATA3 in s["DATA 3"] and Q_DATA5 not in s["DATA 3"] and "DATA 4" not in s["DATA 3"].splitlines()[0]
    assert Q_DATA5 in s["DATA 5"] and "GROWTH BASE RATES" not in s["DATA 5"]                 # to the next "## " header
    assert Q_DATA6A in s["DATA 6"] and "Debt is shown in full." in s["DATA 6"] and "FILING-DERIVED" not in s["DATA 6"]   # 6A-6C are DATA 6
    assert Q_CAPEX in s["GUIDANCE"] and s["GUIDANCE"].startswith("COMPANY'S OWN WORDS")
    assert Q_BRIEF not in s["GUIDANCE"] and "Research-brief rows" not in s["GUIDANCE"]     # exclusive of the research-brief rows
    assert Q_DATA8 not in "".join(s.values())                                                # context is never a source
    # a heading inside the research brief that reads like DATA 3 is not the section
    assert "a heading inside the brief" not in s["DATA 3"]
    # a stale release carries a prefix on its line and is still the company's part
    stale = PACK.replace("COMPANY'S OWN WORDS", "STALE (130 days) " + chr(0x2014) + " COMPANY'S OWN WORDS")
    assert Q_CAPEX in cc.pack_sources(stale)["GUIDANCE"]
    assert cc.pack_sources(None) == {} and cc.pack_sources("no sections") == {}
    assert "GUIDANCE" not in cc.pack_sources(PACK.replace("COMPANY'S OWN WORDS", "THE COMPANY'S WORDS"))


def test_fetched_texts_concatenate_in_call_order_skip_errors_and_normalise_urls():
    calls = [_fetch(URL + "/", "part one. "), _fetch(URL, "part two.", served=URL + "?x=1"), _fetch(OTHER_URL, "boom", error="404"),
             {"tool": "search_web", "text": "not a page"}, _fetch(OTHER_URL, "refused", refused="a PDF"),
             _fetch("https://WWW.Example.com/news/phoenix", "part three."),
             {"tool": "fetch_page", "params": {"url": "https://x.org/r"}, "result": {"url": "https://x.org/r", "text": "from a result"}}]
    got = cc.fetched_texts(calls)
    assert got["https://www.example.com/news/phoenix"] == "part one. \npart two.\npart three."
    assert got["https://www.example.com/news/phoenix?x=1"] == "part two."                 # also under the URL it was served from
    assert OTHER_URL not in got and cc.fetched_texts(None) == {} and got["https://x.org/r"] == "from a result"
    # a fetched page that served no text is still a fetched page
    assert cc.fetched_texts([{"tool": "fetch_page", "params": {"url": URL}, "note": "already read"}]) == {"https://www.example.com/news/phoenix": ""}


# ---- the contract fill: every branch of 1.3 and 1.4 --------------------------------------------------------------------------------

def test_a_valid_crux_in_each_direction_keeps_the_direction():
    for base, want in ((120.0, "undervalued"), (80.0, "overvalued")):
        filled, _ = _fill([_entry()], base_iv=base)
        assert filled["verdict_label"] == filled["direction_m"] == want
        chk = filled["crux_check"]
        assert chk["valid"] is True and chk["reason"] is None and chk["stamps"] == []
        (e,) = chk["entries"]
        assert e == {"input": "coe", "own": 0.0801, "implied": 0.098, "reachable": True, "at_default": False, "valid": True,
                     "reason": None, "citations": [{"source": "GUIDANCE", "class": "pack_company", "quote_found": True}]}
        assert filled["crux"] == [_entry()] and filled["price_implied"]["coe"]["value"] == 0.098


def test_each_pack_source_is_company_evidence_and_the_quote_is_checked_in_its_own_section():
    for src, q in (("GUIDANCE", Q_CAPEX), ("DATA 5", Q_DATA5), ("DATA 3", Q_DATA3), ("DATA 6", Q_DATA6A), ("DATA 6A", Q_DATA6A), ("DATA 6B", Q_DATA6A)):
        filled, _ = _fill([_entry("terminal_ronic", [_cit(src, q)])])
        assert filled["crux_check"]["valid"] is True, (src, filled["crux_check"])
        assert filled["crux_check"]["entries"][0]["citations"][0]["class"] == "pack_company"
    # the same quote cited against the wrong section is not found there
    filled, _ = _fill([_entry("terminal_ronic", [_cit("DATA 3", Q_DATA5)])])
    assert filled["crux_check"]["reason"] == "quote_not_found" and filled["verdict_label"] == "hold"


def test_missing_gives_hold_stamped_no_valid_crux_missing_and_direction_m_is_kept():
    for crux in (None, [], "a prose crux", {}):
        filled, _ = _fill(crux)
        assert filled["verdict_label"] == "hold" and filled["direction_m"] == "undervalued"
        assert filled["crux_check"] == {"valid": False, "reason": "missing", "entries": [], "stamps": ["no_valid_crux:missing"]}
    filled, _ = _fill(None, base_iv=80.0)
    assert (filled["verdict_label"], filled["direction_m"]) == ("hold", "overvalued")


def test_not_judgment_not_reachable_no_company_evidence_quote_not_found():
    cases = {
        "not_judgment": _entry("revenue_growth"),
        "not_reachable": _entry("terminal_g"),
        "no_company_evidence": _entry("coe", [_cit("DATA 8", Q_DATA8)]),
        "quote_not_found": _entry("coe", [_cit("GUIDANCE", "Management expects nothing of the kind in fiscal 2026 at all.")]),
    }
    for reason, entry in cases.items():
        filled, _ = _fill([entry])
        assert filled["crux_check"]["reason"] == reason and filled["crux_check"]["valid"] is False, reason
        assert filled["verdict_label"] == "hold" and filled["direction_m"] == "undervalued"
        assert filled["crux_check"]["stamps"] == [f"no_valid_crux:{reason}"]
        assert filled["crux_check"]["entries"][0]["valid"] is False and filled["crux_check"]["entries"][0]["reason"] == reason


def test_no_company_evidence_in_each_of_its_three_shapes():
    # (i) generic sources only: the DEFAULTS, a research-brief row, the consensus section, an invented section
    for src, q in (("DEFAULTS", "- coe_anchor: 7.35% | the Base discount rate"), ("GUIDANCE & CONSENSUS", Q_BRIEF), ("DATA 8", Q_DATA8),
                   ("DATA 11", "A line in the brief."), ("DATA 7", "Earnings quality is measured on the filed values of the fiscal year."),
                   ("the annual report", "Anything at all, long enough to pass the form check of thirty chars")):
        filled, _ = _fill([_entry("coe", [_cit(src, q)])])
        assert filled["crux_check"]["reason"] == "no_company_evidence", src
        assert filled["crux_check"]["entries"][0]["citations"][0] == {"source": src, "class": "generic", "quote_found": None}
    # (ii) a URL not fetched in this sample
    filled, _ = _fill([_entry("coe", [_cit(URL, Q_NEWS)])])
    assert filled["crux_check"]["reason"] == "no_company_evidence"
    assert filled["crux_check"]["entries"][0]["citations"][0] == {"source": URL, "class": "unknown_source", "quote_found": None}
    # (iii) a fetched page that does not name the company
    filled, _ = _fill([_entry("coe", [_cit(OTHER_URL, OTHER_TEXT)])], calls_extra=[_fetch(OTHER_URL, OTHER_TEXT)])
    assert filled["crux_check"]["reason"] == "no_company_evidence"
    assert filled["crux_check"]["entries"][0]["citations"][0] == {"source": OTHER_URL, "class": "generic", "quote_found": None}
    # a fetched page that errored is not a fetched page
    filled, _ = _fill([_entry("coe", [_cit(URL, Q_NEWS)])], calls_extra=[_fetch(URL, PAGE_TEXT, error="404")])
    assert filled["crux_check"]["entries"][0]["citations"][0]["class"] == "unknown_source"


def test_a_fetched_page_that_names_the_company_is_company_evidence_and_its_quote_is_checked_in_what_the_model_was_shown():
    page = [_fetch(URL, PAGE_TEXT)]
    filled, _ = _fill([_entry("coe", [_cit(URL, Q_NEWS)])], calls_extra=page)
    assert filled["crux_check"]["valid"] is True and filled["verdict_label"] == "undervalued"
    assert filled["crux_check"]["entries"][0]["citations"][0] == {"source": URL, "class": "fetched_page_naming_company", "quote_found": True}
    # the URL is matched after normalisation (host case, trailing slash)
    filled, _ = _fill([_entry("coe", [_cit("https://WWW.example.com/news/phoenix/", Q_NEWS)])], calls_extra=page)
    assert filled["crux_check"]["valid"] is True
    # a quote the page does not hold is not found
    filled, _ = _fill([_entry("coe", [_cit(URL, "Testco said it will close the Phoenix plant in the second quarter of 2027.")])], calls_extra=page)
    assert filled["crux_check"]["reason"] == "quote_not_found"
    assert filled["crux_check"]["entries"][0]["citations"][0]["quote_found"] is False
    # only what the model was shown: a quote from a part it never fetched is not found
    parts = [_fetch(URL, PAGE_TEXT, params={"url": URL, "part": 1})]
    filled, _ = _fill([_entry("coe", [_cit(URL, "A sentence from part two of the page that was never served to the model.")])], calls_extra=parts)
    assert filled["crux_check"]["reason"] == "quote_not_found"
    # the page's text is the concatenation of every record of that URL
    two = [_fetch(URL, PAGE_TEXT, params={"url": URL}), _fetch(URL, "Second part: Testco will add a third line in 2028, the company said.")]
    filled, _ = _fill([_entry("coe", [_cit(URL, "Second part: Testco will add a third line in 2028, the company said.")])], calls_extra=two)
    assert filled["crux_check"]["valid"] is True
    # the ticker in a finance pattern names the company too (the news filter's rule)
    tick = [_fetch(OTHER_URL, "NYSE: TST shares were up on the Tuesday session as the quarter closed for the firm.")]
    filled, _ = _fill([_entry("coe", [_cit(OTHER_URL, "NYSE: TST shares were up on the Tuesday session as the quarter closed for the firm.")])], calls_extra=tick)
    assert filled["crux_check"]["valid"] is True


def test_one_company_citation_with_its_quote_found_is_enough_beside_context_and_a_failed_quote():
    entry = _entry("coe", [_cit("DATA 8", Q_DATA8), _cit("GUIDANCE", "This sentence is not in the release at all, but is long enough."), _cit("DATA 5", Q_DATA5)])
    filled, _ = _fill([entry])
    assert filled["crux_check"]["valid"] is True
    assert [c["class"] for c in filled["crux_check"]["entries"][0]["citations"]] == ["generic", "pack_company", "pack_company"]
    assert [c["quote_found"] for c in filled["crux_check"]["entries"][0]["citations"]] == [None, False, True]


def test_verbatim_means_the_normalised_quote_in_the_normalised_text_and_case_matters():
    curly = "Management expects fiscal 2026 capital expenditure of about $1.1 billion,  the lowest since 2021."
    filled, _ = _fill([_entry("coe", [_cit("GUIDANCE", curly.replace("Management", "Management\n"))])])
    assert filled["crux_check"]["valid"] is True                                              # whitespace runs collapse
    dashed = Q_DATA6A.replace("rose from 61 to 74", "rose from 61 — to 74".replace(" — ", " - "))
    assert cc._found("The “goal” — reached", "The \"goal\" - reached")
    assert not cc._found("capital expenditure of about $1.1 billion", "Capital expenditure of about $1.1 billion")
    assert cc._found("expenditure fell", "Capital  expenditure" + chr(0x200B) + " fell to $0.9 billion")
    assert not cc._found("", "any text") and not cc._found(None, "any text")
    assert dashed != Q_DATA6A


def test_a_valid_crux_at_its_default_is_directional_and_stamped_crux_at_default():
    filled, _ = _fill([_entry("coe", [_cit("GUIDANCE", Q_CAPEX)])], pi=_pi(coe=_blk(0.0735, 0.0735)))          # own at the coe anchor
    assert filled["verdict_label"] == "undervalued" and filled["crux_check"]["valid"] is True
    assert filled["crux_check"]["entries"][0]["at_default"] is True and filled["crux_check"]["stamps"] == ["crux_at_default"]
    # a departure is not at its default
    filled, _ = _fill([_entry("coe")], pi=_pi(coe=_blk(0.098, 0.0801)))
    assert filled["crux_check"]["entries"][0]["at_default"] is False and filled["crux_check"]["stamps"] == []
    # no stamp when the label is a hold within the band
    filled, _ = _fill([_entry("coe")], base_iv=105.0, pi=_pi(coe=_blk(0.0735, 0.0735)))
    assert filled["verdict_label"] == filled["direction_m"] == "hold" and filled["crux_check"]["stamps"] == []


@pytest.mark.parametrize("name,own,own_path,facts_over,want", [
    ("coe", 0.0740, None, {}, True), ("coe", 0.0741, None, {}, False), ("coe", None, None, {}, False), ("coe", 0.0735, None, {"coe_anchor": None}, False),
    ("growth_years_3_5", 0.03, [0.0304, 0.0296, 0.03], {}, True), ("growth_years_3_5", 0.03, [0.0306, 0.03, 0.03], {}, False),
    ("growth_years_3_5", 0.03, None, {}, False), ("growth_years_3_5", 0.03, [0.03, 0.03, 0.03], {"reference_path": None}, False),
    ("fade_years", 5, None, {}, True), ("fade_years", 4, None, {}, False), ("fade_years", 6, None, {}, False),
    ("terminal_g", 0.0235, None, {}, True), ("terminal_g", 0.0236, None, {}, False),
    ("terminal_ronic", 0.1201, None, {}, True), ("terminal_ronic", 0.1202, None, {}, False), ("terminal_ronic", "unlimited", None, {}, False),
    ("terminal_ronic", "unlimited", None, {"terminal_ronic": math.inf}, True), ("terminal_ronic", 0.12, None, {"terminal_ronic": math.inf}, False),
    ("year2_level", 0.5024, None, {}, True), ("year2_level", 0.5026, None, {}, False), ("year2_level", 0.5, None, {"levels": {}}, False),
])
def test_at_its_default_for_each_input(name, own, own_path, facts_over, want):
    assert cc.at_default(name, own, dict(FACTS, **facts_over), own_path) is want


def test_a_crux_with_two_entries_one_invalid_is_invalid_with_the_first_failure():
    filled, _ = _fill([_entry("coe"), _entry("terminal_g")])
    assert filled["crux_check"]["valid"] is False and filled["crux_check"]["reason"] == "not_reachable"
    assert [e["valid"] for e in filled["crux_check"]["entries"]] == [True, False]
    assert filled["verdict_label"] == "hold" and filled["crux_check"]["stamps"] == ["no_valid_crux:not_reachable"]
    # entries are checked in order: the first failure found is the crux's reason, v1 then v2 then v3 within an entry
    filled, _ = _fill([_entry("coe", [_cit("DATA 8", Q_DATA8)]), _entry("terminal_g"), _entry("nope")])
    assert filled["crux_check"]["reason"] == "no_company_evidence"
    assert [e["reason"] for e in filled["crux_check"]["entries"]] == ["no_company_evidence", "not_reachable", "not_judgment"]
    filled, _ = _fill([_entry("nope", [_cit("DATA 8", Q_DATA8)])])
    assert filled["crux_check"]["reason"] == "not_judgment"
    filled, _ = _fill([_entry("terminal_g", [_cit("DATA 8", Q_DATA8)])])
    assert filled["crux_check"]["reason"] == "not_reachable"                                     # v2 before v3
    filled, _ = _fill([_entry("coe"), _entry("terminal_ronic"), _entry("year2_level")])
    assert filled["crux_check"]["valid"] is True and len(filled["crux_check"]["entries"]) == 3


def test_a_sample_within_ten_percent_is_hold_with_no_stamp_and_direction_m_is_stamped_every_time():
    for base in (109.99, 100.0, 90.01):
        filled, _ = _fill([_entry()], base_iv=base)
        assert filled["verdict_label"] == "hold" and filled["direction_m"] == "hold" and filled["crux_check"]["stamps"] == []
        filled, _ = _fill(None, base_iv=base)
        assert filled["direction_m"] == "hold" and filled["crux_check"]["stamps"] == []
    for base, dm in ((110.01, "undervalued"), (89.99, "overvalued")):
        for crux in (None, [_entry()]):
            filled, _ = _fill(crux, base_iv=base)
            assert filled["direction_m"] == dm


def test_the_price_implied_block_of_an_error_or_a_missing_block_makes_every_input_unreachable():
    for pi in ({"error": "identity"}, None):
        calls = [_answer(120.0, [_entry()], pi)]
        calls[0]["price_implied"] = pi
        filled, _ = contract_fill.fill(calls, {}, FACTS, PRICE, ticker=TICKER, pack_text=PACK, company=COMPANY)
        assert filled["crux_check"]["reason"] == "not_reachable" and filled["verdict_label"] == "hold"


def test_a_frozen_older_pack_gets_the_same_rule_and_a_pack_free_fill_has_no_company_evidence():
    # no pack text at all (a caller that did not pass one): no company evidence is found, never a pass
    calls = [_answer(120.0, [_entry()])]
    filled, _ = contract_fill.fill(calls, {}, FACTS, PRICE, ticker=TICKER)
    assert filled["verdict_label"] == "hold" and filled["crux_check"]["reason"] == "quote_not_found"
    # a pack with no sections the check knows
    filled, _ = contract_fill.fill(calls, {}, FACTS, PRICE, ticker=TICKER, pack_text="# DATA PACK - OLD   (pack revision 14)\n## SECTION 3 - X\nline")
    assert filled["verdict_label"] == "hold"


def test_the_crux_and_the_block_are_copied_from_the_answer_call_not_another_call():
    older = _answer(120.0, [_entry("terminal_ronic")], _pi(), index=1)
    newest = _answer(120.0, [_entry("coe")], _pi(coe=_blk(0.111, 0.0735)), index=2)
    filled, prov = contract_fill.fill([older, newest], {}, FACTS, PRICE, ticker=TICKER, pack_text=PACK, company=COMPANY)
    assert prov["answer_call_index"] == 2 and filled["crux"][0]["input"] == "coe" and filled["price_implied"]["coe"]["value"] == 0.111


def test_no_base_no_crux_fields():
    filled, prov = contract_fill.fill([], {}, FACTS, PRICE, ticker=TICKER, pack_text=PACK, company=COMPANY)
    assert not any(k in filled for k in contract_fill.REVISION_19) and set(contract_fill.REVISION_19) <= set(prov["unfilled"])


# ---- the verdict-side owners (E): every new field reaches the medoid summary -----------------------------------------------------------

def test_the_medoid_summary_carries_the_crux_fields():
    import consensus_valuation as cv
    filled, _ = _fill([_entry()])
    card = dict({"base_iv": 120.0, "bull_iv": 150.0, "bear_iv": 90.0, "business_quality_moat": 3.0}, **filled)
    run = {"sample": 1, "iv": 120.0, "scorecard": card, "plausible": True, "flags": [], "truncated": False, "failed_reason": None, "desk_calls": 1,
           "desk_iv_match": True, "reduced_thinking": False, "basis": True}
    medoid, summary = cv.select_medoid_scorecard([run], PRICE)
    for k in contract_fill.REVISION_19:
        assert k in summary, k
    assert summary["direction_m"] == "undervalued" and summary["crux"] == filled["crux"] and summary["crux_check"]["valid"] is True
    assert summary["price_implied"] == filled["price_implied"]
    # the empty path carries the keys as None
    _, empty = cv.select_medoid_scorecard([], PRICE)
    assert all(empty[k] is None for k in contract_fill.REVISION_19)


# ---- B1: the schema ---------------------------------------------------------------------------------------------------------------------

CRUX_DESCRIPTION = (
    "Your stated disagreement with today's price, needed for a verdict of undervalued or overvalued (TASK item 6): one "
    "to three of the desk's judgment inputs (coe, growth_years_3_5, fade_years, terminal_g, terminal_ronic, "
    "year2_level) on which your evidence says the price is wrong. For each: input; reason (why this company's value of "
    "it differs from what the price implies, and by how much); citations, one to five of {source, date, quote}: source "
    "is PRIMARY P# (an item of PRIMARY SOURCES: the company's own filings, verbatim), DATA 3, DATA 4, DATA 5, DATA 6, "
    "GUIDANCE (the company's own release), or the exact URL of a page you fetched in "
    "this session that names the company; date is YYYY-MM-DD; quote is 30 to 600 characters copied exactly from that "
    "source. Code fills in your value and the price-implied value from this run. Leave crux out when you have no such "
    "disagreement: the verdict is then HOLD.")


def _tool():
    return next(t for t in at.TOOLS if t["function"]["name"] == "run_financial_model")["function"]


def test_the_schema_has_the_crux_argument_verbatim_and_the_price_implied_sentence():
    f = _tool()
    p = f["parameters"]["properties"]["crux"]
    assert p["description"] == CRUX_DESCRIPTION and p["type"] == "array" and p["minItems"] == 1 and p["maxItems"] == 3
    item = p["items"]
    assert item["type"] == "object" and item["required"] == ["input", "reason", "citations"]
    # revision 24 step 2b: long_run_margin joined the judgment inputs
    assert item["properties"]["input"] == {"type": "string", "enum": ["coe", "growth_years_3_5", "fade_years", "terminal_g", "terminal_ronic", "year2_level",
                                                                      "long_run_margin"]}
    assert item["properties"]["reason"] == {"type": "string"}
    cit = item["properties"]["citations"]
    assert cit["type"] == "array" and cit["minItems"] == 1 and cit["maxItems"] == 5
    assert cit["items"]["required"] == ["source", "date", "quote"] and set(cit["items"]["properties"]) == {"source", "date", "quote"}
    assert "crux" not in f["parameters"]["required"]                                         # a crux is optional: none means HOLD
    assert ("On every run the desk also returns price_implied: for each judgment input, the value at which the Base would equal today's price "
            "with your other inputs unchanged, or not reachable inside its bound.") in f["description"]
    assert tuple(item["properties"]["input"]["enum"]) == cc.J == fmt.PI_INPUTS


# ---- B2: the desk's form check ----------------------------------------------------------------------------------------------------------

CTX = dict(_ctx(price=50.0), rf_eff=0.04, nominal_gdp_trend=0.0446, run_date="2026-10-02", ticker=TICKER, company=COMPANY)
GOOD_CRUX = [{"input": "coe", "reason": "Because of this, by that much.", "citations": [{"source": "DATA 5", "date": "2026-09-30", "quote": Q_DATA5}]}]


def _desk(crux, **over):
    p = _happy_params(**_ALL_REASONS_GIVEN)
    if crux is not None:
        p["crux"] = crux
    p.update(over)
    return fmt.execute_financial_model(p, dict(CTX))


def test_a_call_without_a_crux_is_never_refused_for_it_and_a_well_formed_one_is_accepted():
    out = _desk(None)
    assert "error" not in out and "crux_desk_check" not in out and "price_implied" in out
    out = _desk(GOOD_CRUX)
    assert "error" not in out and out["crux_desk_check"][0]["input"] == "coe"


def _variants():
    good = GOOD_CRUX[0]
    cit = good["citations"][0]
    mk = lambda **k: [dict(good, **k)]
    ck = lambda **k: [dict(good, citations=[dict(cit, **k)])]
    return {
        "not a list": ("crux", "a prose crux"), "a dict": ("crux", {"input": "coe"}), "empty": ("crux", []),
        "four entries": ("crux", [good, good, good, good]), "an entry that is not an object": ("crux[1]", ["coe"]),
        "input not in J": ("crux[1].input", mk(input="revenue")), "input absent": ("crux[1].input", [{k: v for k, v in good.items() if k != "input"}]),
        "reason absent": ("crux[1].reason", [{k: v for k, v in good.items() if k != "reason"}]), "reason empty": ("crux[1].reason", mk(reason="  ")),
        "reason none": ("crux[1].reason", mk(reason="None")), "reason null": ("crux[1].reason", mk(reason="null")),
        "citations absent": ("crux[1].citations", [{k: v for k, v in good.items() if k != "citations"}]),
        "citations empty": ("crux[1].citations", mk(citations=[])), "citations not a list": ("crux[1].citations", mk(citations="DATA 5")),
        "six citations": ("crux[1].citations", mk(citations=[cit] * 6)), "a citation that is not an object": ("crux[1].citations[1]", mk(citations=["DATA 5"])),
        "source empty": ("crux[1].citations[1].source", ck(source=" ")), "source absent": ("crux[1].citations[1].source", mk(citations=[{"date": "2026-09-30", "quote": Q_DATA5}])),
        "date format": ("crux[1].citations[1].date", ck(date="30 Sep 2026")), "date short": ("crux[1].citations[1].date", ck(date="2026-9-30")),
        "date absent": ("crux[1].citations[1].date", mk(citations=[{"source": "DATA 5", "quote": Q_DATA5}])),
        "date after the run": ("crux[1].citations[1].date", ck(date="2026-10-03")),
        "quote 29 characters": ("crux[1].citations[1].quote", ck(quote="x" * 29)), "quote 601 characters": ("crux[1].citations[1].quote", ck(quote="x" * 601)),
        "quote short after normalising": ("crux[1].citations[1].quote", ck(quote="word " + " " * 100 + " end")), "quote absent": ("crux[1].citations[1].quote", mk(citations=[{"source": "DATA 5", "date": "2026-09-30"}])),
        "quote not a string": ("crux[1].citations[1].quote", ck(quote=12345678901234567890123456789012345)),
    }


@pytest.mark.parametrize("label", list(_variants()))
def test_every_form_refusal_is_a_missing_entry_that_uses_no_desk_run(label):
    where, crux = _variants()[label]
    out = _desk(crux)
    assert out["validation_error"] is True and out["needs_reasons"] == [] and any(m.startswith(where) for m in out["missing"]), (label, out["missing"])
    assert "Not accepted as a desk run; it does not use one of your desk runs." in out["error"] and "missing " in out["error"]
    assert "scenario_dcfs" not in out and "price_implied" not in out


def test_the_boundaries_of_the_form_check_are_inclusive():
    cit = GOOD_CRUX[0]["citations"][0]
    for q in ("x" * 30, "x" * 600, "  " + "y" * 30 + "  ", "z" * 20 + " " * 40 + "z" * 10):
        assert "error" not in _desk([dict(GOOD_CRUX[0], citations=[dict(cit, quote=q)])]), len(q)
    assert "error" not in _desk([dict(GOOD_CRUX[0], citations=[dict(cit, date="2026-10-02")])])                  # the run's date itself
    assert "error" not in _desk([GOOD_CRUX[0]] * 3) and "error" not in _desk([dict(GOOD_CRUX[0], citations=[cit] * 5)])
    # the date is read against the run's date; without one in the context, today's
    out = fmt.execute_financial_model(dict(_happy_params(**_ALL_REASONS_GIVEN), crux=[dict(GOOD_CRUX[0], citations=[dict(cit, date="2099-01-01")])]),
                                      {k: v for k, v in CTX.items() if k != "run_date"})
    assert "is after the run's date" in out["error"]


def test_a_crux_with_a_non_judgment_input_or_an_unreachable_one_is_not_refused_by_the_desk_but_shown_to_the_model():
    """No other crux check refuses: validity is crux_check's, outside the desk (B2)."""
    out = _desk([dict(GOOD_CRUX[0], input="terminal_g")])
    assert "error" not in out
    (d,) = out["crux_desk_check"]
    assert d["input"] == "terminal_g" and d["judgment_input"] is True and d["reachable"] is out["price_implied"]["terminal_g"]["reachable"]


# ---- B3 and B4: what the model is shown -----------------------------------------------------------------------------------------------

def test_the_desks_own_check_per_entry_and_its_rendering():
    out = _desk([GOOD_CRUX[0], dict(GOOD_CRUX[0], input="terminal_g"), dict(GOOD_CRUX[0], input="year2_level")])
    items = out["crux_desk_check"]
    assert [i["input"] for i in items] == ["coe", "terminal_g", "year2_level"] and all(i["judgment_input"] for i in items)
    pi = out["price_implied"]
    assert [i["reachable"] for i in items] == [pi[k]["reachable"] for k in ("coe", "terminal_g", "year2_level")]
    lines = fmt.crux_desk_check_lines(items)
    assert lines[0].startswith("crux[1] coe: judgment input, reachable: price-implied ") and "[yours 8.00%]" in lines[0]
    hand = [{"input": "revenue", "judgment_input": False, "reachable": None, "price_implied": None, "own": None},
            {"input": "terminal_g", "judgment_input": True, "reachable": False, "price_implied": None, "own": 0.0234},
            {"input": "coe", "judgment_input": True, "reachable": True, "price_implied": 0.098, "own": 0.0735}]
    assert fmt.crux_desk_check_lines(hand) == [
        "crux[1] revenue: not a judgment input (v1 fails)",
        "crux[2] terminal_g: the price-implied value is not reachable inside its bound (v2 fails)",
        "crux[3] coe: judgment input, reachable: price-implied 9.80% [yours 7.35%]",
        "Your crux as submitted is NOT valid: a crux is valid only when every entry is, and crux[1] revenue, crux[2] terminal_g fail. "
        "Without a valid crux the verdict is HOLD. Drop or replace the failing entries in your next desk call, or report HOLD."]
    assert fmt.crux_desk_check_lines(None) == []
    # 2026-10-18: one failing entry fails the whole crux, said plainly (the restoration's TASK and GOLD memos misread a partial pass)
    one = fmt.crux_desk_check_lines(hand[1:])
    assert one[-1].startswith("Your crux as submitted is NOT valid") and "crux[1] terminal_g fails" in one[-1]


def test_the_citation_check_and_its_rendering():
    crux = [_entry("coe", [_cit("GUIDANCE", Q_CAPEX), _cit("DATA 5", "This line is not printed in the filed years section."), _cit("DATA 8", Q_DATA8)]),
            _entry("fade_years", [_cit(URL, Q_NEWS), _cit(OTHER_URL, OTHER_TEXT), _cit("https://never.fetched/x", "A quote from a page that was not fetched.")])]
    calls = [_fetch(URL, PAGE_TEXT), _fetch(OTHER_URL, OTHER_TEXT)]
    got = at.crux_citation_check(crux, PACK, calls, {"company": COMPANY, "ticker": TICKER})
    assert [(g["input"], [(c["class"], c["quote_found"]) for c in g["citations"]]) for g in got] == [
        ("coe", [("pack_company", True), ("pack_company", False), ("generic", None)]),
        ("fade_years", [("fetched_page_naming_company", True), ("generic", None), ("unknown_source", None)])]
    assert at.crux_citation_lines(got) == [
        "crux[1] coe citation 1 (GUIDANCE): the company's own filing or release in the pack, quote found",
        "crux[1] coe citation 2 (DATA 5): the company's own filing or release in the pack, quote NOT found",
        "crux[1] coe citation 3 (DATA 8): context, not company evidence",
        f"crux[2] fade_years citation 1 ({URL}): a page you fetched that names the company, quote found",
        f"crux[2] fade_years citation 2 ({OTHER_URL}): context, not company evidence",
        "crux[2] fade_years citation 3 (https://never.fetched/x): a page you have not fetched in this session, not evidence"]
    # without the company and ticker no page names the company
    none = at.crux_citation_check(crux, PACK, calls, {})
    assert none[1]["citations"][0]["class"] == "generic"


def test_the_summary_and_the_compact_note_carry_the_crux_lines():
    result = {"price": 50.0, "scenario_dcfs": [{"name": "Base", "dcf": {"per_share_iv": 60.0}}], "price_implied": _pi(),
              "crux_desk_check": [{"input": "coe", "judgment_input": True, "reachable": True, "price_implied": 0.098, "own": 0.0735}],
              "crux_citation_check": [{"input": "coe", "citations": [{"source": "GUIDANCE", "class": "pack_company", "quote_found": True}]}]}
    want = ["crux[1] coe: judgment input, reachable: price-implied 9.80% [yours 7.35%]",
            "Every entry is a reachable judgment input. That is not yet a valid crux: each entry's quotes are verified separately, "
            "and one entry whose quotes do not resolve makes the whole crux invalid.",
            "crux[1] coe citation 1 (GUIDANCE): the company's own filing or release in the pack, quote found"]
    assert at._desk_summary({}, result)["crux_check"] == want
    note = at.compact_tool_note("run_financial_model", {}, result, 4)
    assert note.split("\n")[-3:] == want and "price_implied coe: 9.80% [8.01%]" in note
    assert "crux_check" not in at._desk_summary({}, {"price": 50.0, "scenario_dcfs": []})


# ---- B4 in the loop: the check runs after an accepted desk call on the pack and the pages fetched so far -----------------------------------

def test_the_loop_appends_the_citation_check_to_an_accepted_desk_result(monkeypatch, tmp_path):
    from test_desk_continuation import _desk as desk_turn, _serve, _snap, _turn, _call
    bodies = _serve(monkeypatch, [_turn(tool_calls=_call("fetch_page", {"url": URL})), desk_turn(dict(_happy_params(**_ALL_REASONS_GIVEN), crux=[
        {"input": "coe", "reason": "r", "citations": [{"source": URL, "date": "2026-10-01", "quote": Q_NEWS},
                                                       {"source": "GUIDANCE", "date": "2026-10-01", "quote": Q_CAPEX}]}])), _turn("# MEMO\n" + "x" * 6000)])
    monkeypatch.setattr(at, "fetch_page", lambda url, snap=None, **k: {"url": url, "text": PAGE_TEXT, "chars": len(PAGE_TEXT), "parts": 1})
    ctx = dict(CTX)
    at.chat_with_tools("test-model", PACK, tmp_path, verbose=False, desk_context=ctx)
    snap = _snap(tmp_path)
    desk = next(c for c in snap["calls"] if c["tool"] == "run_financial_model")
    assert "error" not in desk and desk["price_implied"]["coe"]["reachable"] in (True, False)
    assert desk["crux_citation_check"] == [{"input": "coe", "citations": [
        {"source": URL, "class": "fetched_page_naming_company", "quote_found": True},
        {"source": "GUIDANCE", "class": "pack_company", "quote_found": True}]}]
    assert desk["crux_desk_check"][0]["input"] == "coe"
    # the model's next request carries the lines in the tool message it was shown
    last_tool_msg = [m for m in bodies[2]["messages"] if m["role"] == "tool"][-1]["content"]
    assert "citation 1" in last_tool_msg and "a page you fetched that names the company, quote found" in last_tool_msg


def test_a_refused_call_or_one_without_a_crux_gets_no_citation_check(monkeypatch, tmp_path):
    from test_desk_continuation import _desk as desk_turn, _serve, _snap, _turn
    _serve(monkeypatch, [desk_turn(_happy_params(**_ALL_REASONS_GIVEN)), _turn("# MEMO\n" + "x" * 6000)])
    at.chat_with_tools("test-model", PACK, tmp_path / "a", verbose=False, desk_context=dict(CTX))
    assert "crux_citation_check" not in next(c for c in _snap(tmp_path / "a")["calls"] if c["tool"] == "run_financial_model")
    _serve(monkeypatch, [desk_turn(dict(_happy_params(**_ALL_REASONS_GIVEN), crux="prose")), _turn("# MEMO\n" + "x" * 6000), _turn("# MEMO2\n" + "x" * 6000)])
    at.chat_with_tools("test-model", PACK, tmp_path / "b", verbose=False, desk_context=dict(CTX))
    refused = next(c for c in _snap(tmp_path / "b")["calls"] if c["tool"] == "run_financial_model")
    assert refused["validation_error"] is True and "crux_citation_check" not in refused


# ---- the form owner and the fill agree -------------------------------------------------------------------------------------------------

def test_form_problems_is_empty_for_an_absent_or_well_formed_crux():
    assert cc.form_problems(None, "2026-10-02") == [] and cc.form_problems(GOOD_CRUX, "2026-10-02") == []
    assert cc.form_problems(GOOD_CRUX, None) == []
    assert cc.REASONS == ("missing", "not_judgment", "not_reachable", "no_company_evidence", "quote_not_found")
