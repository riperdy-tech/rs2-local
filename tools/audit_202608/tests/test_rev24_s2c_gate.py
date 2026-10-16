"""Revision 24 step 2c (BRIEF_R24_S2c_ranges_fix.md items 3, 5, 6 and 9; PHASE_4_AMENDMENTS.md "Revision 24 step 2b" rulings 5, 7, 8 and 18; the
coordinator's additions; cross-check 19 rulings B and C): the plausibility gate.

- terminal_g has no population range: above the pack's printed growth anchor (terminal_g_anchor) it is an outlier needing an outlier-level citation;
  for a shrinking business (the record's 8-year revenue trend below 0, or growth_trajectory classified shrinking) so is any terminal_g above 0;
- the long-run margin outside its year-5 range is annotated, never rejected;
- a family the tables do not measure is annotated no_population_cohort, and the mathematics and the anchor still run;
- a citation resolves by crux_check's own acceptance rule (one copy, crux_check.evidence_failure): PRIMARY P#, DATA 3-6, GUIDANCE, or a page fetched
  in the session that names the company, the quote found; and the TASK states exactly those sources for item 3d and item 6;
- the three classifications are checked; within_p10_p90 is computed by code, a mismatch annotated, and the citation level follows the code.
"""
import math
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capability_test as cap  # noqa: E402
import crux_check  # noqa: E402
import fiduciary_gate as fg  # noqa: E402
import population_ranges as pr  # noqa: E402
from test_rev24_s2b_gate import PACK, QUOTE, R, _base_dcf, _rationale  # noqa: E402
from test_rev24_s2b_ranges import fixture_tables, rec  # noqa: E402

ANCHOR = 0.0375
CITE = {"source": "DATA 5", "date": "2026-09-01", "quote": QUOTE}
GOOD = {"margin_persistence": "structural", "cycle_position": "mid", "growth_trajectory": "steady"}


def _ranges(**kw):
    return pr.ranges_for(rec(**kw), "2026-10-16", tables=fixture_tables())


def gate(dcf, ranges=None, rationale=None, classifications=None, **kw):
    return fg.plausibility_gate(dcf, ranges if ranges is not None else _ranges(), rationale if rationale is not None else _rationale(), PACK,
                                growth_anchor=kw.pop("anchor", ANCHOR), classifications=classifications or GOOD, **kw)


# ---- terminal_g: the anchor (ruling 5) and the shrinking rule (cross-check 19, ruling C) ------------------------------------------------

def test_terminal_g_above_the_printed_growth_anchor_is_an_outlier_needing_a_citation():
    g = gate(_base_dcf(tg=0.045))
    assert g["verdict"] == "reject" and g["reasons"] == ["implausible_unsupported_terminal_g"] and g["metrics"]["terminal_g"]["anchor"] == ANCHOR
    g = gate(_base_dcf(tg=0.045), rationale=_rationale(CITE, on="terminal_g"))
    assert g["verdict"] == "pass" and "implausible_supported_terminal_g" in g["annotations"]
    g = gate(_base_dcf(tg=ANCHOR))                                               # at the anchor: an ordinary choice
    assert g["verdict"] == "pass" and g["metrics"]["terminal_g"]["status"] == "within"
    assert g["within_p10_p90"]["terminal_g"]["computed"] is True and g["within_p10_p90"]["terminal_g"]["citation_level"] == "in_range"


def test_no_printed_anchor_is_annotated_and_never_rejects():
    g = gate(_base_dcf(tg=0.06), anchor=None)
    assert g["verdict"] == "pass" and "terminal_g_anchor_not_available" in g["annotations"] and g["metrics"]["terminal_g"]["status"] == "not_measured"


def test_a_shrinking_record_makes_any_positive_terminal_g_an_outlier():
    """Cross-check 19, ruling C, on a synthetic shrinking record (8-year ln-revenue slope -3%) with terminal_g 2.4%, below the anchor."""
    shrinking = _ranges(trend8=-0.03)
    assert shrinking["revenue_trend8"] == -0.03
    g = gate(_base_dcf(tg=0.024), ranges=shrinking)
    assert g["verdict"] == "reject" and g["reasons"] == ["implausible_unsupported_terminal_g"]
    assert g["metrics"]["terminal_g"]["shrinking"] == ["the record's 8-year revenue trend -0.0300 is below 0"]
    assert g["within_p10_p90"]["terminal_g"]["computed"] is False and "outlier_citation_missing:terminal_g" in g["annotations"]
    g = gate(_base_dcf(tg=0.024), ranges=shrinking, rationale=_rationale(CITE, on="terminal_g"))
    assert g["verdict"] == "pass" and "implausible_supported_terminal_g" in g["annotations"]
    for tg in (0.0, -0.01):                                                      # 0 and below are ordinary for a shrinking business
        assert gate(_base_dcf(tg=tg), ranges=shrinking)["metrics"]["terminal_g"]["status"] == "within"
    # the same with no anchor printed: the shrinking rule still runs
    assert gate(_base_dcf(tg=0.024), ranges=shrinking, anchor=None)["reasons"] == ["implausible_unsupported_terminal_g"]


def test_a_shrinking_classification_makes_any_positive_terminal_g_an_outlier_too():
    growing = _ranges(trend8=0.05)
    assert gate(_base_dcf(tg=0.024), ranges=growing)["verdict"] == "pass"
    g = gate(_base_dcf(tg=0.024), ranges=growing, classifications=dict(GOOD, growth_trajectory=" Shrinking "))
    assert g["reasons"] == ["implausible_unsupported_terminal_g"] and g["metrics"]["terminal_g"]["shrinking"] == ["growth_trajectory is classified shrinking"]


def test_terminal_growth_at_or_above_the_rate_is_rejected_whatever_else():
    g = gate(dict(_base_dcf(), terminal_g=R), anchor=None)                        # a desk output carrying it (the desk itself refuses it)
    assert "terminal_growth_not_below_rate" in g["reasons"]


# ---- the long-run margin (cross-check 19, ruling B) -----------------------------------------------------------------------------------------

def test_the_long_run_margin_outside_its_year_5_range_is_annotated_and_never_rejects():
    g = gate(_base_dcf(lrm=0.35))
    assert g["verdict"] == "pass" and "long_run_margin_outside_year5_range_unsupported" in g["annotations"]
    assert not any("long_run_margin" in r for r in g["reasons"])
    g = gate(_base_dcf(lrm=0.35), rationale=_rationale(CITE))
    assert "implausible_supported_long_run_margin" in g["annotations"] and "long_run_margin_outside_year5_range_unsupported" not in g["annotations"]


# ---- an unmeasured family (ruling 7) --------------------------------------------------------------------------------------------------------

def test_an_unmeasured_family_is_annotated_and_the_mathematics_and_the_anchor_still_run():
    nb = _ranges(family="family_not_built")
    g = gate(_base_dcf(), ranges=nb)
    assert g["verdict"] == "pass" and "no_population_cohort" in g["annotations"]
    assert gate(_base_dcf(tg=0.045), ranges=nb)["reasons"] == ["implausible_unsupported_terminal_g"]
    assert "terminal_growth_not_below_rate" in gate(dict(_base_dcf(), terminal_g=R), ranges=nb)["reasons"]
    fin = _ranges(family="financial", tg3=0.08)                                  # the financial margin and ROIC are unmeasured; the revenue CAGR is
    g = gate(_base_dcf(), ranges=fin)
    assert "no_population_cohort" in g["annotations"] and g["metrics"]["revenue_cagr_10y"]["status"] != "not_measured"
    # an input the tables refuse for a reason other than the family is not a missing cohort
    ok = _ranges(roic3=None)
    assert "no_population_cohort" not in gate(_base_dcf(), ranges=ok)["annotations"]


# ---- citations: crux_check's one acceptance rule (ruling 8) --------------------------------------------------------------------------------

FETCHED = "https://news.example.com/test-co-plant"
PAGE = "Test Co said its new plant runs at full capacity through 2028, and its backlog reached a record level this quarter."
CALLS = [{"tool": "fetch_page", "params": {"url": FETCHED}, "result": {"url": FETCHED, "text": PAGE}}]


@pytest.mark.parametrize("cit, ok", [
    ({"source": "DATA 5", "date": "2026-09-01", "quote": QUOTE}, True),                                       # pack_company, quote found
    ({"source": FETCHED, "date": "2026-09-01", "quote": "its new plant runs at full capacity through 2028"}, True),   # a fetched page naming it
    ({"source": FETCHED, "date": "2026-09-01", "quote": "a sentence the page does not hold, long enough"}, False),     # quote_not_found
    ({"source": "https://elsewhere.example.com/x", "date": "2026-09-01", "quote": QUOTE}, False),               # not fetched: unknown_source
    ({"source": "DEFAULTS", "date": "2026-09-01", "quote": QUOTE}, False),                                     # context, never evidence
])
def test_the_gate_accepts_exactly_what_the_crux_accepts(cit, ok):
    resolved, recs = fg.citation_resolves([cit], PACK, CALLS, "Test Co", "TEST")
    assert resolved is ok
    # the crux's own verdict on the same citation records: the same rule (crux_check.evidence_failure), one copy
    assert (crux_check.evidence_failure(recs) is None) is ok
    entry = {"input": "terminal_ronic", "reason": "x", "citations": [cit]}
    chk = crux_check.check([entry], {"terminal_ronic": {"reachable": True, "own": 0.2, "value": 0.1}}, PACK, CALLS, "Test Co", "TEST", {})
    assert chk["valid"] is ok


def test_the_task_states_exactly_the_sources_the_gate_and_the_crux_accept():
    """The coordinator's addition to ruling 8: TASK item 3d names the outlier citation sources in the same words as item 6 (the crux), and they are
    exactly crux_check's company evidence: the pack sources (PRIMARY P#, DATA 3-6, GUIDANCE: class pack_company) and a page fetched in the session
    that names the company (fetched_page_naming_company) - no more, no less."""
    t = cap.TASK
    d = t[t.index("   d. Support each choice"):t.index("   - Growth:")]
    six = t[t.index("6. The desk also returns price_implied"):t.index("7. Timing")]
    assert cap.EVIDENCE_SOURCES in d and cap.EVIDENCE_SOURCES in six
    assert "PRIMARY SOURCES, DATA 3-6 or GUIDANCE" not in t
    named_pack = re.findall(r"DATA \d", cap.EVIDENCE_SOURCES) + re.findall(r"GUIDANCE", cap.EVIDENCE_SOURCES)
    assert sorted(set(named_pack)) == sorted(crux_check.PACK_SOURCES)
    assert "PRIMARY P#" in cap.EVIDENCE_SOURCES and "a page you fetched in this session that names the company" in cap.EVIDENCE_SOURCES
    assert crux_check.COMPANY_EVIDENCE == ("pack_company", "fetched_page_naming_company")
    # the contract's citation template offers the same sources
    tmpl = re.search(r'"source": "<(PRIMARY P# \| DATA 3[^>]*)>"', t).group(1)
    assert tmpl == "PRIMARY P# | DATA 3 | DATA 4 | DATA 5 | DATA 6 | GUIDANCE | the URL of a page you fetched in this session that names the company"
    # and every source the template names is one the classifier accepts as company evidence
    for src in ("DATA 3", "DATA 4", "DATA 5", "DATA 6", "GUIDANCE"):
        assert crux_check._pack_source_name(src) in crux_check.PACK_SOURCES


# ---- classifications and within_p10_p90 (ruling 18) ----------------------------------------------------------------------------------------

def test_an_invalid_classification_is_annotated_by_name():
    g = gate(_base_dcf(), classifications={"margin_persistence": "Partly_Structural", "cycle_position": "recovery", "growth_trajectory": None})
    assert "invalid_classification_cycle_position" in g["annotations"] and "invalid_classification_growth_trajectory" in g["annotations"]
    assert "invalid_classification_margin_persistence" not in g["annotations"] and g["verdict"] == "pass"
    assert g["classifications"]["cycle_position"] == {"value": "recovery", "valid": False}


def test_within_p10_p90_is_computed_from_the_printed_range_the_declaration_is_kept_and_the_level_follows_the_code():
    # the fixture's earnings-margin P10-P90 is -1.6% to 12.8%: 15% is outside, the analyst declared it inside
    ir = _rationale()
    g = gate(_base_dcf(lrm=0.15), rationale=ir)
    w = g["within_p10_p90"]["long_run_margin"]
    assert w["declared"] is True and w["computed"] is False and w["citation_level"] == "outlier" and w["citation_resolves"] is False
    assert "within_p10_p90_mismatch:long_run_margin" in g["annotations"] and "outlier_citation_missing:long_run_margin" in g["annotations"]
    assert ir["long_run_margin"]["within_p10_p90"] is True                      # kept as declared
    # with the outlier's citation: the level is met, the mismatch still recorded
    ir = _rationale(CITE)
    ir["long_run_margin"]["within_p10_p90"] = True
    g = gate(_base_dcf(lrm=0.15), rationale=ir)
    assert g["within_p10_p90"]["long_run_margin"]["citation_resolves"] is True and "outlier_citation_missing:long_run_margin" not in g["annotations"]
    # an input with no printed P10-P90 (the growth path, the fade) takes the in-range rationale
    assert g["within_p10_p90"]["growth_years_3_5"]["computed"] is None and g["within_p10_p90"]["growth_years_3_5"]["citation_level"] == "in_range"
    # the ROIC level's P10-P90 (-9% to 36%): unlimited is outside it
    g = gate(_base_dcf(ronic=math.inf))
    assert g["within_p10_p90"]["terminal_ronic"]["computed"] is False


def test_the_new_annotations_ride_as_verdict_flags():
    import depth_pipeline as dp
    import consensus_valuation as cv
    from test_rev24_s2b_gate import S12, _fill
    filled, _ = _fill(0.15, typed_over={"cycle_position": "recovery"})
    sc = dict(S12, input_rationale=_rationale(), cycle_position="recovery", **filled)
    runs = [{"sample": 1, "iv": sc["base_iv"], "plausible": True, "basis": True, "scorecard": sc, "flags": []}]
    _, summary = cv.select_medoid_scorecard(runs, 500.0)
    v = dp.band_verdict({"ticker": "TEST", "price": 500.0, "runs": runs, "scorecard": summary, "median_iv": sc["base_iv"], "spread_pct": None})
    for f in ("invalid_classification_cycle_position", "within_p10_p90_mismatch:long_run_margin", "outlier_citation_missing:long_run_margin"):
        assert f in v["flags"], f
    assert v["direction"] != "NOT_USABLE"
