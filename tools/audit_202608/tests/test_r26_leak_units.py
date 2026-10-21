"""Revision 26, P5 blind-pack leak audit, coordinator rulings of 2026-10-19: (1) the narrative filter drops a sentence that names analyst ratings, price targets, the Street,
estimate revisions or the share price's move; (2) the leak audit compares a number with a removed number only when their unit class and scale agree."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import r26_blind as rb  # noqa: E402

DROPPED = [
    "2026-09-23 | bull | Investor Day; stock -1.46% on the day — muted reaction (estimates: no immediate raise; next-FY EPS subsequently revised down from $4.99 to $4.91 (0 up / 6 down in last 30 days))",
    "Utility earnings call: fresh Buy ratings (Scotiabank, Jefferies PT $52) followed the print.",
    "Morgan Stanley upgraded the name to Overweight.", "The broker downgraded it after the quarter.", "Barclays initiated coverage with an Underweight rating.",
    "Several firms initiate coverage next month.", "A Hold rating was kept.", "Sell ratings outnumber Buy ratings.", "The price objective is unchanged.", "The target price rose.",
    "Street expectations are lower.", "Sell-side estimates moved.", "The Street was surprised.", "EPS revisions turned negative.", "Estimates were revised up last week.",
    "Shares rose 3% after the call.", "The stock +2.24% Oct 15.", "BUD fell -3.64% on 3.2M shares that day.", "There were 5 up / 2 down in 30 days.",
]
KEPT = [
    "Revenue rose 5% on higher volumes.", "Net income fell to $3.2 million in the quarter.", "The company holds 12 patents.", "Management expects capex of $5.5B.",
    "The plant was upgraded by the contractor's crew.".replace("upgraded", "expanded"), "Mining costs rose 4% on diesel.", "A buyback of $1B was authorised.",
]


@pytest.mark.parametrize("sentence", DROPPED)
def test_a_sentence_naming_analyst_views_or_the_share_price_move_is_dropped(sentence):
    kept, drops = rb.filter_narrative(sentence, "CATALYST BRIEF")
    assert drops and kept.strip() == "", (sentence, kept)


@pytest.mark.parametrize("sentence", KEPT)
def test_a_filed_style_fundamental_sentence_is_kept(sentence):
    kept, drops = rb.filter_narrative(sentence, "CATALYST BRIEF")
    assert not drops and kept == sentence


def test_only_the_offending_sentence_of_a_line_goes():
    kept, drops = rb.filter_narrative("Capex was cut to $3.6B. Jefferies put the PT at $52. Brand spend rises.", "X")
    assert kept == "Capex was cut to $3.6B. Brand spend rises." and len(drops) == 1 and drops[0]["rule"] == "analyst_view"


def _audit(blind, removed_lines=(), facts=None):
    n = len(blind.split("\n"))
    f = dict(facts or {})
    f["r26_blind_source"] = {"removed_lines": [{"cls": "consensus", "section": "DATA 8 - CONSENSUS & MULTIPLES", "text": t} for t in removed_lines],
                             "spans": [{"start": 0, "end": n, "cls": "narrative", "section": "CATALYST BRIEF"}]}
    return rb.r26_leak_audit(blind, f)


def test_unit_class_of_a_printed_number():
    uc = rb.unit_class
    assert [uc(t) for t in ("$2.50", "+$2.5M", "$8.3B", "23%", "23.081x", "0.444", "$11.6 million", "$2 billion", "5K")] == ["$", "M", "B", "%", "x", "bare", "M", "B", "K"]


def test_false_positive_pacs_millions_against_a_per_share_eps():
    a = _audit("# t\n- 2026-10-05 | bull | Omega 8-K filed: contract worth +$2.5M a year", ["| EPS next FY | $2.50 | $2.45 |"],
               {"x_margin_consensus_y1y2": {"y1": {"eps_avg": 2.5}}})
    assert a["pass"] is True and a["leaks"] == []


def test_false_positive_gold_millions_against_a_multiple():
    a = _audit("# t\n- Open question: a charge of $11.6 million in the quarter", ["| EV/EBITDA | 11.6x |"])
    assert a["pass"] is True


def test_false_positive_hnrg_beta_against_a_billions_amount():
    a = _audit("# t\n- Beta: 0.444   [Aggregator]", ["| market cap | $0.444B |"])
    assert a["pass"] is True


def test_false_positive_hnrg_percent_against_a_multiple():
    a = _audit("# t\n- Mix: 23% of sales came from the segment", ["| EV/EBITDA | 23.081x |"])
    assert a["pass"] is True


def test_false_positive_gold_billions_against_a_fraction_fact():
    # long_run.e5 = 0.08317: as $B it is 0.083, as a percent 8.3 - never "$8.3B"
    a = _audit("# t\n- Open questions: does the model hold up with $8.3B of sales", [], {"long_run": {"e5": 0.08317}})
    assert a["pass"] is True
    # e5 is a dollar amount ($B): since 2026-10-21 it is never matched as a percent (DAR's insider 1.18% against oe_path 1.18); a margin fact still is
    assert _audit("# t\n- Growth of 8.3% a year", [], {"long_run": {"e5": 0.08317}})["pass"] is True
    b = _audit("# t\n- Growth of 8.3% a year", [], {"long_run": {"m5": 0.08317}})                         # the fraction x 100 as a percent is still a leak
    assert [x["token"] for x in b["leaks"]] == ["8.3%"]


@pytest.mark.parametrize("removed, text, token", [
    ("| EPS next FY | $2.50 |", "- the street model has $2.50 for next year", "$2.50"),                    # per-share dollars
    ("| EPS next FY | $2.50 |", "- the model has 2.50 for next year", "2.50"),                            # the same figure with no mark
    ("| revenue | $2.5M |", "- sales of +$2.5M a year", "+$2.5M"),                                          # millions
    ("| revenue | $2.5 million |", "- sales of $2.5M a year", "$2.5M"),                                    # the word and the letter are one class
    ("| revenue | $8.3B |", "- sales of $8.3B a year", "$8.3B"),                                           # billions
    ("| growth | 12.4% |", "- growth of 12.4% a year", "12.4%"),                                           # percent
    ("| EV/EBITDA | 11.6x |", "- trades near 11.6x", "11.6x"),                                             # multiple
    ("| beta-like | 0.444 |", "- a figure of 0.444 here", "0.444"),                                       # bare number
])
def test_a_seeded_real_leak_is_caught_in_every_unit_class(removed, text, token):
    a = _audit("# t\n" + text, [removed])
    assert a["pass"] is False and [x["token"] for x in a["leaks"]] == [token]


@pytest.mark.parametrize("fact, text, token", [
    ({"consensus_implied_value": 19.18}, "- worth $19.18 a share", "$19.18"),
    ({"consensus_implied_value": 19.18}, "- a multiple of 19.2x", "19.2x"),
    ({"next_fy_revenue_growth": 0.064}, "- growth of 6.4%", "6.4%"),
    ({"long_run": {"e5": 1.236627}}, "- earnings of $1.24B", "$1.24B"),                               # a $B fact
    ({"long_run": {"e5": 1.236627}}, "- earnings of $1,240M", "$1,240M"),                              # the same fact shown in millions
])
def test_a_seeded_real_leak_of_a_fact_is_caught(fact, text, token):
    a = _audit("# t\n" + text, [], fact)
    assert a["pass"] is False and token in [x["token"] for x in a["leaks"]]


def test_the_stage2_text_check_is_unit_aware_too():
    facts = {"r26_blind_source": {"removed_lines": [{"cls": "consensus", "section": "D8", "text": "| EPS | $2.50 |"}], "spans": [{"start": 0, "end": 1, "cls": "narrative", "section": "N"}]}}
    assert rb.text_leaks("a contract of +$2.5M", "# t\nx", facts) == []
    assert [x["token"] for x in rb.text_leaks("EPS of $2.50", "# t\nx", facts)] == ["$2.50"]


def test_a_narrative_number_equal_to_the_filed_eps_is_a_listed_exception_and_a_different_vendor_eps_is_a_leak():
    facts = {"consensus_corrected": {"vendor_eps": 2.32, "filed_eps": 2.3244444444444445}}
    a = _audit("# t\n- earnings of $2.32 per diluted share (reported in 2025)", [], facts)
    assert a["pass"] is True and a["leaks"] == [] and a["exceptions"][0]["filed_source"] == "filed_eps fact"
    b = _audit("# t\n- earnings of $2.61 per diluted share", [], {"consensus_corrected": {"vendor_eps": 2.61, "filed_eps": 2.3244444444444445}})
    assert b["pass"] is False and [x["token"] for x in b["leaks"]] == ["$2.61"]
    assert rb.text_leaks("EPS $2.32", "# t\nx", dict(facts, r26_blind_source={"removed_lines": [], "spans": []})) == []


@pytest.mark.parametrize("sentence", [
    "PTC Therapeutics was last at USD 59.24 on Nasdaq", "The stock closed at $82.59 on Friday.", "Shares traded at US$12.30 after the call.", "BUD is trading at $80.1.",
    "A price of $45.10 was quoted.", "The name changed hands at $59.24 on the NYSE American.",
])
def test_a_sentence_stating_the_share_price_is_dropped(sentence):
    kept, drops = rb.filter_narrative(sentence, "CATALYST BRIEF")
    assert drops and kept.strip() == ""


def test_usd_before_a_number_is_the_dollar_unit_class_and_a_price_leak_is_caught():
    assert rb.unit_class("USD 59.24") == "$" and rb.unit_class("US$59.24") == "$" and rb.unit_class("USD 2.5M") == "M"
    a = _audit("# t\nPTC Therapeutics sits at USD 59.24 today", ["| price | $59.24 |"])
    assert a["pass"] is False and [x["token"] for x in a["leaks"]] == ["USD 59.24"]
    b = _audit("# t\nA charge of USD 59.24 million", ["| price | $59.24 |"])
    assert b["pass"] is True
