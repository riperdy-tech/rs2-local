"""Pass 2: the checks on P6's answer, the revision rule, and the anchoring metric."""
import pytest

from valuation.muse import redteam as rt
from valuation.muse.checkers import Evidence
from valuation.muse.mapping import Position

S = "Growth delivered: revenue growth in the latest fiscal year +4.2%; 3-year compound growth +6.7%."
D = ("The company has a signed supply agreement for 12 GW of capacity and a backlog of $4.2 billion. We expect demand for our products to remain strong. "
     "The company sells widgets to industrial customers.")
EV = Evidence({"S": S, "D": D, "R": "[R g1] Revenue growth in the next fiscal year (rate)"})
P1_ENTRY = {"percentile": 60, "width": "normal", "reasons": ["first reason", "second reason"],
            "citations": [{"section": "S", "quote": "revenue growth in the latest fiscal year"}]}
SEEN = rt.pass1_quote_set([P1_ENTRY])
P1 = Position(60.0, "normal")
HARD = {"section": "D", "quote": "signed supply agreement for 12 GW of capacity"}
NEW = {"section": "D", "quote": "The company sells widgets to industrial customers"}


def revise(pct=70, width="normal", new_quote=None, named_error=None, cits=None):
    return {"market_case": "the strongest case is the stated capacity", "decision": "revise", "percentile": pct, "width": width,
            "reasons": ["new reason"], "citations": cits if cits is not None else [{"section": "S", "quote": "3-year compound growth +6.7%"}],
            "new_quote": new_quote, "named_error": named_error}


def decide(p6, req=None, p1=P1):
    return rt.decide("g1", p1, P1_ENTRY, p6, req, EV, SEEN)


# ---- the revision rule --------------------------------------------------------------------------------------------------------------------

def test_keep_leaves_the_pass1_position():
    d = decide({"decision": "keep", "market_case": "x" * 30})
    assert not d["proposed"] and not d["accepted"] and d["position"] is P1


def test_a_revision_with_neither_a_new_quote_nor_a_named_error_is_refused_and_pass1_stands():
    d = decide(revise(70))
    assert d["proposed"] and not d["accepted"] and d["position"] is P1 and "refused" in d["reason"]
    assert not d["new_quote"] and not d["named_error"]


def test_a_new_quote_not_cited_in_pass1_accepts_the_revision():
    d = decide(revise(70, new_quote=NEW))
    assert d["accepted"] and d["new_quote"] and (d["position"].percentile, d["position"].source) == (70.0, "P6")
    assert "revision_evidence: new_quote" in d["position"].stamps


def test_a_quote_already_cited_in_pass1_is_not_new():
    for q in ("revenue growth in the latest fiscal year", "growth in the latest", "Growth delivered: revenue growth in the latest fiscal year +4.2%"):
        d = decide(revise(70, new_quote={"section": "S", "quote": q}))
        assert not d["new_quote"] and not d["accepted"], q


def test_a_named_error_in_a_pass1_reason_accepts_the_revision():
    d = decide(revise(40, named_error={"reason_index": 2, "why_wrong": "the second reason ignored the stated capacity"}))
    assert d["accepted"] and d["named_error"] and not d["new_quote"] and "revision_evidence: named_error" in d["position"].stamps


def test_a_revise_with_the_same_percentile_and_width_is_a_keep():
    d = decide(revise(60, "normal", new_quote=NEW))
    assert not d["proposed"] and d["position"] is P1


def test_a_width_only_change_needs_evidence_too():
    assert not decide(revise(60, "wide")).get("accepted")
    assert decide(revise(60, "wide", new_quote=NEW))["accepted"]


def test_toward_price_follows_the_required_percentile():
    req = {"status": "ok", "required_percentile": 85.0, "extraordinary": False}
    assert decide(revise(70, new_quote=NEW), req)["toward_price"] is True
    assert decide(revise(40, new_quote=NEW), req)["toward_price"] is False
    assert decide(revise(70, new_quote=NEW), None)["toward_price"] is None
    nr = {"status": "not_reachable", "nearest_percentile": 1.0, "extraordinary": True}
    assert decide(revise(40, new_quote=NEW), nr)["toward_price"] is True


def test_near_an_extraordinary_requirement_the_burden_is_hard_evidence():
    req = {"status": "ok", "required_percentile": 99.0, "extraordinary": True}
    weak = decide(revise(88, new_quote=NEW), req)                               # within 10 points of the (clamped) requirement, no hard evidence
    assert not weak["accepted"] and "extraordinary" in weak["reason"]
    strong = decide(revise(88, new_quote=HARD, cits=[HARD]), req)
    assert strong["accepted"]
    far = decide(revise(70, new_quote=NEW), req)                                 # not near: the ordinary rule
    assert far["accepted"]


# ---- the checks on the answer (the retry's checks) ----------------------------------------------------------------------------------------------

def v6(obj, inputs=("g1",)):
    return rt.validate_p6(obj, list(inputs), EV, {"g1": P1_ENTRY})


def test_a_well_formed_answer_passes():
    assert v6({"inputs": {"g1": revise(70, new_quote=NEW)}}) == []
    assert v6({"inputs": {"g1": {"market_case": "m" * 30, "decision": "keep"}}}) == []


def test_schema_quote_and_hard_evidence_failures_are_issues():
    bad = {"inputs": {"g1": {"decision": "keep", "market_case": "short"}}}
    assert any("market_case" in i.message for i in v6(bad))
    assert any("decision" in i.message for i in v6({"inputs": {"g1": {"market_case": "m" * 30, "decision": "maybe"}}}))
    assert any(i.code == "quote" for i in v6({"inputs": {"g1": revise(70, new_quote={"section": "D", "quote": "an invented sentence about capacity"})}}))
    assert any("named_error" in i.message for i in v6({"inputs": {"g1": revise(70, named_error={"reason_index": 3, "why_wrong": "x" * 30})}}))
    assert any("named_error" in i.message for i in v6({"inputs": {"g1": revise(70, named_error={"reason_index": 1, "why_wrong": "short"})}}))
    assert any(i.code == "hard_evidence" for i in v6({"inputs": {"g1": revise(95, new_quote=NEW, cits=[NEW])}}))
    assert v6({"inputs": {"g1": revise(95, new_quote=HARD, cits=[HARD])}}) == []
    assert any("missing" in i.message for i in v6({"inputs": {}}))
    assert any("unexpected" in i.message for i in v6({"inputs": {"g1": {"market_case": "m" * 30, "decision": "keep"}, "x": {}}}))


# ---- the anchoring metric --------------------------------------------------------------------------------------------------------------------

def rec(proposed, accepted, toward, new_quote=False, named=False, asof="2026-01-31"):
    return {"input": "g1", "proposed": proposed, "accepted": accepted, "toward_price": toward, "new_quote": new_quote, "named_error": named, "asof": asof}


def test_the_anchoring_metric():
    ds = [rec(False, False, None), rec(False, False, None),
          rec(True, True, True, new_quote=True),             # toward the price, with a new quote
          rec(True, False, True),                             # toward the price, no evidence at all: refused
          rec(True, True, True, named=True),                  # toward the price, named error only
          rec(True, True, False, new_quote=True)]             # away from the price
    m = rt.anchoring_metric(ds)
    assert (m["n_inputs"], m["n_proposed"], m["n_accepted"], m["n_refused"]) == (6, 4, 3, 1)
    assert m["n_toward_price"] == 3 and m["share_toward_price_of_proposed"] == pytest.approx(0.75)
    assert m["n_toward_price_without_new_quote"] == 2 and m["share_without_new_quote_among_toward"] == pytest.approx(2 / 3)
    assert m["n_toward_price_without_new_quote_or_named_error"] == 1 and m["share_without_new_quote_or_named_error_among_toward"] == pytest.approx(1 / 3)
    assert m["share_toward_price_of_accepted"] == pytest.approx(2 / 3)


def test_the_metric_is_none_not_zero_when_there_is_nothing_to_divide():
    m = rt.anchoring_metric([rec(False, False, None)])
    assert m["share_toward_price_of_proposed"] is None and m["share_without_new_quote_among_toward"] is None
    assert rt.anchoring_metric([])["n_inputs"] == 0


def test_the_metric_by_date():
    out = rt.anchoring_by_date([rec(True, True, True, new_quote=True, asof="2026-02-28"), rec(True, False, True, asof="2026-01-31"),
                                rec(False, False, None, asof="2026-01-31")])
    assert list(out) == ["2026-01-31", "2026-02-28"] and out["2026-01-31"]["n_inputs"] == 2 and out["2026-02-28"]["n_accepted"] == 1


# ---- Addendum AE.1: a move toward the price needs a new quote from the filings -----------------------------------------------------------------

def test_a_named_error_alone_cannot_move_a_position_toward_the_price():
    req = {"status": "ok", "required_percentile": 85.0, "extraordinary": False}
    ne = {"reason_index": 1, "why_wrong": "the first reason understated the growth the price implies"}
    d = decide(revise(70, named_error=ne), req)
    assert d["toward_price"] is True and not d["accepted"] and d["position"] is P1 and "Addendum AE.1" in d["reason"]
    assert decide(revise(70, new_quote=NEW), req)["accepted"]                          # a new filing quote still can
    assert decide(revise(40, named_error=ne), req)["accepted"]                          # away from the price: the registered rule


def test_a_toward_price_new_quote_must_come_from_a_filing_section():
    req = {"status": "ok", "required_percentile": 85.0, "extraordinary": False}
    s_quote = {"section": "S", "quote": "3-year compound growth +6.7%"}                  # new, but from the code-built state section
    d = decide(revise(70, new_quote=s_quote), req)
    assert d["new_quote"] and not d["new_quote_from_filing"] and not d["accepted"]
