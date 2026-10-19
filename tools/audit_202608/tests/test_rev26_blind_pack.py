"""Revision 26 (BRIEF_R26_B_blind_pack.md, SPEC_rev26_staged_analyst.md section 5): the blind pack, the leak test, the operating-margin bar, the basis-corrected consensus.

1. The switch: the arm, its marker, its desk schema; PACK_REVISION and every other arm unchanged (byte identity against the commit before this work).
2. The source classes and the blind split (PackLines, tag, blind_split), the narrative filter and its drop list.
3. The leak test, including a seeded leak.
4. The operating-margin bar: the arithmetic, 0.0 as a value, a missing year stated and not filled, the X basis for the financial family.
5. The basis-corrected consensus: the ratio and the margins, both band edges, the analyst rule, the not-comparable branches, the bridge hook.
6. A built GEV r26 pack with consensus data: what the blind pack leaves out, what the full text keeps, the sidecar keys.
7. (opt-in, R26_FROZEN_NAMES=1) MSGE, TASK and DAC rebuilt from their frozen P1-P4 inputs: the blind pack passes the leak test.
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capability_test as cap  # noqa: E402
import pack_facts  # noqa: E402
import r26_blind as rb  # noqa: E402
from test_rev24_s2b_pack import built  # noqa: E402,F401  (the fixture: a built GEV pack)

R26_KEYS = ("r26_blind_drops", "op_margin_bar", "consensus_corrected", "r26_leak_audit", "r26_blind_source")

# sha256 of str(pack) and of the facts (without the five r26 keys and the version, which this revision added or moved) of build_pack("GEV") on the committed slice at 6bc2ad0, the
# commit before revision 26: every other arm's pack and facts are byte-identical after it (built at 6bc2ad0 and here, 2026-10-19)
LEGACY_6BC2AD0 = {
    None: ("71c5645034c5088945017bc8c413eddfc564fc36ff9a59c90cc9eb7d3c0e96f3", "505945cc1c1fd86e8307d5492c383526c97560ff1e34a898177396b733a34b87"),
    "rev22": ("1c4d2859f582e73e1df0e0452ee00ffebe5d638a2ddfbd91c1b1574b98ccfff9", "cd90547fd3444a13ac90a891fd4f80a417c9d7a3795f38a6cb2244bbed7736ef"),
    "iii_p50": ("221936accd4a01ec30e74c8f1550e3b69685448d1dc405f377c4e0fe805865e0", "e6fbf8be571e445d3131bf59a3765bd24915604020dcb8b32b79b433f6a4615a"),
    "iii_no_p50": ("71c5645034c5088945017bc8c413eddfc564fc36ff9a59c90cc9eb7d3c0e96f3", "6353968db7ed444a8676691346fc6d99278d5d2356dda90123a21feb32c548eb"),
    "r25_b": ("cbbad4de7b6d3c53376e2114289151b5069a6fe897c3acad913687394240d413", "5e0df906cc7419ae514abcc6579844d10ce731cdbb9989d1ee2d2a6fcfc31177"),
    "r25_c": ("cbbad4de7b6d3c53376e2114289151b5069a6fe897c3acad913687394240d413", "19cb347abe7cf57b3f087b56519c9502537eacf62136cd092863bf137e102b89"),
    "r25_sf": ("1804c5d8052db800e37d9f47cefe0326c41cf2237af3a05647d7ddc7d61f76a0", "16dd020568e308617ed1ac6469c0ba0336198beb9feb4563c6dc14e68dcf2a91"),
}


# ---- 1. the switch ------------------------------------------------------------------------------------------------------------------------------

def test_the_arm_its_marker_and_the_untouched_pack_revision():
    assert "r26" in cap.PILOT_ARMS and cap.R26_ARM == "r26" and cap.R26_REVISION == 27 and cap.R25_SF_REVISION == 26 and cap.PACK_REVISION == 24
    assert cap.pack_flags("r26") == ("r26", False)
    with pytest.raises(ValueError):
        cap.pack_flags("r26", ranges_show_p50=True)
    assert cap.task_for({"desk_schema": "25.2", "pilot_arm": "r26"}) is cap.TASK_SF
    with pytest.raises(ValueError, match="no point-in-time build"):
        cap.build_pack("GEV", pilot_arm="r26", asof="2026-01-02")


def test_every_other_arms_pack_and_facts_are_byte_identical_to_the_commit_before_revision_26(built, monkeypatch):
    monkeypatch.setattr(cap, "_one_off_us_gaap", lambda t: None)
    for arm, (pack_sha, facts_sha) in LEGACY_6BC2AD0.items():
        pk = built(pilot_arm=arm) if arm else built()
        facts = {k: v for k, v in pk.facts.items() if k not in R26_KEYS and k != "version"}
        assert all(pk.facts[k] is None for k in R26_KEYS), arm
        assert pk.full_text == "" and pk.facts["version"] == 12
        assert hashlib.sha256(str(pk).encode()).hexdigest() == pack_sha, arm
        assert hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest() == facts_sha, arm


# ---- 2. the source classes, the blind split, the narrative filter -----------------------------------------------------------------------------------

def test_pack_lines_record_a_class_and_a_section_for_every_element_and_print_as_a_plain_list():
    L = rb.PackLines(["# DATA PACK - T", ""])
    L.cls = rb.DERIVED
    L += ["## DATA A - ONE   [x]", "- a: 1", rb.tag(rb.PRICE, "- p: 2"), ""]
    L.cls = rb.NARRATIVE
    L.append("## DATA B - TWO")
    L.insert(2, "inserted")
    L.insert_block(1, ["## DATA Z - BLOCK   [y]", "- z", ""], rb.FILED)
    assert len(L.tags) == len(L) and "\n".join(L).count("\n") == len(L) - 1
    by_text = {str(x): t for x, t in zip(L, L.tags)}
    assert by_text["# DATA PACK - T"] == (rb.FILED, "", False)
    assert by_text["- a: 1"] == (rb.DERIVED, "DATA A - ONE", False)
    assert by_text["- p: 2"] == (rb.PRICE, "DATA A - ONE", False)
    assert by_text["## DATA B - TWO"] == (rb.NARRATIVE, "DATA B - TWO", True)
    assert by_text["- z"] == (rb.FILED, "DATA Z - BLOCK", False)
    assert L.section == "DATA B - TWO"           # insert_block leaves the current section alone


def test_the_blind_split_removes_the_removed_classes_by_class_and_never_by_text():
    L = rb.PackLines(["# DATA PACK - T   (pack revision 26)", ""])
    L.cls = rb.AGGREGATOR
    L += ["## DATA 2 - MARKET", rb.tag(rb.PRICE, "- Price: $12.34"), rb.tag(rb.MARKET_CAP, "- Market cap: $1.234B"), "- Shares outstanding: 100", ""]
    L.cls = rb.CONSENSUS
    L += ["## DATA 8 - CONSENSUS & MULTIPLES", "- estimates here: 5.67", ""]
    L.cls = rb.FILED
    # a filed line that happens to say "Price": the class keeps it, because the decision is the class
    L += ["## DATA 5 - FILED", "- Price index of inputs (a filed series name): 3.21", ""]
    L.cls = rb.PRICE_ACTION
    L += ["## DATA 2.5 - PRICE ACTION", "- 12-1 month return: +1.0%", ""]
    s = rb.blind_split(L)
    blind = s["blind_text"]
    assert "Price: $12.34" not in blind and "Market cap" not in blind and "DATA 8" not in blind and "DATA 2.5" not in blind
    assert "- Shares outstanding: 100" in blind and "- Price index of inputs (a filed series name): 3.21" in blind
    assert {r["cls"] for r in s["removed"]} == {rb.PRICE, rb.MARKET_CAP, rb.CONSENSUS, rb.PRICE_ACTION}
    assert "Price: $12.34" in s["full_text"] and "DATA 8" in s["full_text"]
    # the spans map every blind line to its class and section
    spans = s["spans"]
    lines = blind.split("\n")
    assert spans[-1]["end"] == len(lines) - 1 and spans[0]["start"] == 0
    cls_of = lambda i: next(sp["cls"] for sp in spans if sp["start"] <= i <= sp["end"])      # noqa: E731
    assert cls_of(lines.index("- Shares outstanding: 100")) == rb.AGGREGATOR


def test_a_section_whose_whole_body_was_removed_is_dropped_with_its_header_and_listed():
    L = rb.PackLines(["# DATA PACK - T", ""])
    L += ["## DATA WARNINGS   [x]", rb.tag(rb.MARKET_CAP, "- DATA WARNING shares_mismatch: implied shares 1.0"), ""]
    L += ["## DATA 1 - KEPT", "- k: 1", ""]
    s = rb.blind_split(L)
    assert "DATA WARNINGS" not in s["blind_text"] and "DATA 1 - KEPT" in s["blind_text"] and s["dropped_sections"] == ["DATA WARNINGS"]
    # a section that was empty in the full pack is not a removal
    E = rb.PackLines(["# t", "", "## DATA EMPTY", "", "## DATA 1", "- k"])
    assert "DATA EMPTY" in rb.blind_split(E)["blind_text"] and rb.blind_split(E)["dropped_sections"] == []


def test_a_blind_variant_replaces_an_element_in_the_blind_pack_and_records_what_it_left_out():
    L = rb.PackLines(["# t", "", "## DEFAULTS"])
    L.append(rb.tag(rb.DERIVED, "- long_run: cycle=no, e5=0.1, m5=7%, m_tc=5%", blind="- long_run: cycle=no, m_tc=5%", removed_text="e5=0.1, m5=0.07"))
    s = rb.blind_split(L)
    assert "m5" not in s["blind_text"] and "e5" not in s["blind_text"] and "m5=7%" in s["full_text"]
    assert s["removed"] == [{"cls": rb.CONSENSUS, "section": "DEFAULTS", "id": "defaults", "text": "e5=0.1, m5=0.07", "replaced_by_blind_variant": True}]


def test_the_narrative_filter_drops_a_sentence_that_names_a_removed_class_and_lists_it_with_its_source():
    text = ("The company opened a plant in Ohio. Analysts expect $1.20 EPS next year. Shares rose 5% on Monday. The consensus is $2.00. "
            "Its market cap is $5B. It is valued at 12x earnings. The price target was raised to $80. The firm hired a new CFO.")
    kept, drops = rb.filter_narrative(text, "RECENT COMPANY NEWS")
    assert kept == "The company opened a plant in Ohio. The firm hired a new CFO."
    assert [d["rule"] for d in drops] == ["analyst_estimate", "share_price", "consensus", "market_cap", "price_multiple", "price_target"]
    assert all(d["source"] == "RECENT COMPANY NEWS" and d["sentence"] for d in drops)
    # a line with no sentence left disappears, a blank line stays, a clean line is untouched
    kept, drops = rb.filter_narrative("Analysts disagree.\n\n- 2026-01-01 | bull | A plant opened.", "S")
    assert kept == "\n- 2026-01-01 | bull | A plant opened." and len(drops) == 1
    assert rb.names_removed_class("Revenue grew 5% on pricing power.") is None


def test_the_narrative_sources_are_filtered_by_class_and_the_drops_listed_in_the_split():
    L = rb.PackLines(["# t", ""])
    L.cls = rb.NARRATIVE
    L += ["## RECENT COMPANY NEWS   [x]", "- 2026-01-01 | wire | Plant opens. Analysts raised estimates.", "- Pure analyst chatter.", ""]
    s = rb.blind_split(L)
    assert "Plant opens." in s["blind_text"] and "analyst" not in s["blind_text"].lower().replace("analysts raised", "") and "chatter" not in s["blind_text"]
    assert [(d["source"], d["rule"]) for d in s["drops"]] == [("RECENT COMPANY NEWS", "analyst_estimate")] * 2


def test_every_line_carries_the_harnesss_section_id_and_a_partial_removal_keeps_the_id():
    L = rb.PackLines(["# DATA PACK - T", ""])
    L += ["## DATA 2 - MARKET   [x]", rb.tag(rb.PRICE, "- Price: $1.23"), "- Shares outstanding: 100", "",
          "## GUIDANCE & CONSENSUS   [y]", "text", "### DATA 6A - SUB", "- sub", "## PRIMARY SOURCES   [z]", "[P1] first filing", "body one", "[P2] second", "## Competitive Position & Moat", "brief text",
          "## DATA 8 - CONSENSUS & MULTIPLES", rb.tag(rb.CONSENSUS, "- c: 1.5")]
    assert rb.assign_ids(list(L)) == ["", "", "data-2", "data-2", "data-2", "data-2", "guidance-consensus", "guidance-consensus", "data-6a", "data-6a", "primary-sources",
                                     "primary-p1", "primary-p1", "primary-p2", "primary-p2", "primary-p2", "data-8", "data-8"]
    s = rb.blind_split(L)
    assert [sp["id"] for sp in s["spans"]][:2] == ["", "data-2"] and all("id" in sp for sp in s["spans"])
    assert s["partial_ids"] == ["data-2"] and s["removed_ids"] == ["data-8"]     # the price line left DATA 2, which keeps its id; DATA 8 lost its whole body
    assert "data-8" not in [sp["id"] for sp in s["spans"]]


# ---- 3. the leak test ---------------------------------------------------------------------------------------------------------------------------

def _facts_with(removed_lines, spans, **more):
    f = {"r26_blind_source": {"removed_lines": removed_lines, "spans": spans}}
    f.update(more)
    return f


def test_sig_forms_render_one_to_three_significant_digits():
    assert rb.sig_forms(79.5975) == ["80", "79.6"] and rb.sig_forms(0.0735) == ["0.07", "0.073", "0.0735"] and rb.sig_forms(1234.5) == ["1000", "1200", "1230"]
    assert rb.sig_forms(0.0) == [] and rb.sig_forms(-2.35) == ["2", "2.4", "2.35"]


def test_a_seeded_leak_fails_the_leak_test():
    removed = [{"cls": "price", "section": "DATA 2 - MARKET", "text": "- Price: $79.5975"}, {"cls": "consensus", "section": "DATA 8 - CONSENSUS & MULTIPLES", "text": "| current FY | $2.35 | 1.126B |"}]
    blind = "# t\n## DATA 5 - FILED\n| 2025 | 9.870 |\n## RECENT COMPANY NEWS\nThe company opened a plant in Ohio.\nA broker sees the stock reaching $79.6 soon."
    spans = [{"start": 0, "end": 0, "cls": "filed", "section": ""}, {"start": 1, "end": 2, "cls": "filed", "section": "DATA 5 - FILED"},
             {"start": 3, "end": 5, "cls": "narrative", "section": "RECENT COMPANY NEWS"}]
    a = rb.r26_leak_audit(blind, _facts_with(removed, spans))
    assert a["pass"] is False and len(a["leaks"]) == 1
    leak = a["leaks"][0]
    assert leak["token"] == "$79.6" and leak["class"] == "narrative" and leak["section"] == "RECENT COMPANY NEWS" and leak["line"] == 5
    # the same pack without the sentence passes
    clean = blind.rsplit("\n", 1)[0]
    assert rb.r26_leak_audit(clean, _facts_with(removed, spans[:2] + [{"start": 3, "end": 4, "cls": "narrative", "section": "RECENT COMPANY NEWS"}]))["pass"] is True


def test_a_removed_number_that_is_also_a_filed_fact_is_a_listed_exception_with_its_source():
    removed = [{"cls": "consensus", "section": "DATA 8 - CONSENSUS & MULTIPLES", "text": "| next FY | 1.23B | $5.60 |"}]
    blind = "# t\n## DATA 5 - FILED\n| FY2025 | 1.230 | 9.9 |\n## RECENT COMPANY NEWS\nRevenue was $1.2B in the year.\nThe stock hit $5.60 today."
    spans = [{"start": 0, "end": 0, "cls": "filed", "section": ""}, {"start": 1, "end": 2, "cls": "filed", "section": "DATA 5 - FILED"},
             {"start": 3, "end": 5, "cls": "narrative", "section": "RECENT COMPANY NEWS"}]
    a = rb.r26_leak_audit(blind, _facts_with(removed, spans))
    by = {(e["section"], e["form"]): e for e in a["exceptions"]}
    assert ("DATA 5 - FILED", "1.23") in by and by[("DATA 5 - FILED", "1.23")]["class"] == "filed"            # a hit on a filed line
    assert by[("RECENT COMPANY NEWS", "1.2")]["filed_source"] == "DATA 5 - FILED"                         # $1.2B is the filed 1.230 at two digits: named
    assert [x["token"] for x in a["leaks"]] == ["$5.60"] and a["pass"] is False                            # no filed number supports 5.6: a leak


def test_a_bare_integer_is_a_weak_match_and_never_fails_and_a_header_or_a_date_is_not_searched():
    removed = [{"cls": "consensus", "section": "DATA 8 - X", "text": "| growth | 12.4% | 8.0 |"}]
    blind = "# t\n## DATA 12 - WHAT WE DO NOT HOLD   [8.0]\nNews: it opened 12 stores on 2026-08-12.\nAnd 8 more."
    spans = [{"start": 0, "end": 3, "cls": "narrative", "section": "N"}]
    a = rb.r26_leak_audit(blind, _facts_with(removed, spans))
    assert a["pass"] is True and a["leaks"] == [] and a["weak_matches"] == 2


def test_removed_facts_count_only_their_removed_part_and_a_fraction_is_also_tried_as_a_percent():
    f = {"consensus_implied_value": 19.18, "levels": {"year1": 0.076}, "next_fy_revenue_growth": 0.064,
         "consensus_corrected": {"ratio": 0.7693, "ratio_band": [0.5, 2.0], "filed_eps": 1.4, "years": {"y1": {"x_margin": 0.0663}}},
         "long_run": {"e5": 0.121, "revenue_path": [1.183547, 1.236627], "x_L": 0.099},
         "price_implied_defaults": {"coe": {"value": 0.2186, "bound": {"low": 0.0447}}}}
    got = {n["origin"] for n in rb.removed_numbers(f)}
    assert {"fact:consensus_implied_value", "fact:levels.year1", "fact:next_fy_revenue_growth", "fact:consensus_corrected.ratio", "fact:consensus_corrected.years.y1.x_margin",
            "fact:long_run.e5", "fact:long_run.revenue_path[1:][0]", "fact:price_implied_defaults.coe.value"} <= got
    assert not any("ratio_band" in o or "filed_eps" in o or "x_L" in o or "bound" in o for o in got)
    assert not any(o == "fact:long_run.revenue_path[0]" for o in got)                                      # index 0 is the filed base year
    a = rb.r26_leak_audit("# t\nThe market expects 6.4% growth.", dict(f, r26_blind_source={"removed_lines": [], "spans": [{"start": 0, "end": 1, "cls": "narrative", "section": "N"}]}))
    assert [x["token"] for x in a["leaks"]] == ["6.4%"]                                                    # 0.064 as a percent


# ---- 4. the operating-margin bar ---------------------------------------------------------------------------------------------------------------

def _rows(spec):
    return {str(y): ({"revenue": r, "operating_income": oi} if r is not None or oi is not None else {}) for y, (r, oi) in spec.items()}


def test_the_bar_arithmetic_zero_is_a_value_and_a_missing_year_is_stated_and_not_filled():
    rows = _rows({2018: (100, 10), 2019: (100, 20), 2020: (100, 0), 2021: (100, None), 2022: (100, -10), 2023: (0, 5), 2024: (100, 30), 2025: (100, 40)})
    bar = rb.op_margin_bar(rows)
    assert bar["window"] == [2018, 2025] and bar["label"] == "filed operating margin, operating income / revenue" and bar["fields"] == ["operating_income", "revenue"]
    assert [(y["fy"], round(y["margin"], 6)) for y in bar["years"]] == [(2018, 0.1), (2019, 0.2), (2020, 0.0), (2022, -0.1), (2024, 0.3), (2025, 0.4)]
    assert [(m["fy"], m["why"]) for m in bar["missing"]] == [(2021, "operating_income not held"), (2023, "revenue not held or not positive")]
    # n = 6, sorted [-.1, 0, .1, .2, .3, .4]: linear interpolation at (n-1)q
    assert bar["n"] == 6 and bar["min"] == -0.1 and bar["max"] == 0.4 and bar["last"] == 0.4 and bar["last_year"] == 2025
    assert math.isclose(bar["p25"], 0.025) and math.isclose(bar["median"], 0.15) and math.isclose(bar["p75"], 0.275)
    # 0.0 is a value: a window whose only margin is 0.0 has statistics, all 0.0
    z = rb.op_margin_bar(_rows({2025: (100, 0)}))
    assert z["n"] == 1 and (z["min"], z["p25"], z["median"], z["p75"], z["max"], z["last"]) == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_the_bar_window_is_the_records_eight_years_and_last_is_the_latest_filed_year():
    rows = _rows({y: (100, y - 2000) for y in range(2010, 2026)})
    bar = rb.op_margin_bar(rows)
    assert bar["window"] == [2018, 2025] and bar["n"] == 8 and bar["min"] == 0.18 and bar["last"] == 0.25
    # the latest filed year has no operating income: last is stated as not held, never replaced by an earlier year
    rows["2025"] = {"revenue": 100, "operating_income": None}
    bar = rb.op_margin_bar(rows)
    assert bar["last"] is None and bar["last_year"] == 2025 and bar["n"] == 7 and any(m["fy"] == 2025 for m in bar["missing"])
    none = rb.op_margin_bar({})
    assert none["n"] == 0 and none["median"] is None and none["years"] == []


def test_the_x_basis_bar_for_the_financial_family_reads_the_x_margin_history():
    hist = {"base_year": 2025, "years": [{"fy": 2023, "x_margin": 0.05, "x_b": 0.5, "revenue_b": 10.0}, {"fy": 2024, "x_margin": 0.0, "x_b": 0.0, "revenue_b": 10.0},
                                         {"fy": 2025, "x_margin": 0.15, "x_b": 1.5, "revenue_b": 10.0}], "skipped": [{"fy": 2022, "why": "revenue not positive or net income missing"}]}
    bar = rb.x_margin_bar(hist)
    assert bar["basis"] == "x" and bar["window"] == [2018, 2025] and bar["n"] == 3 and bar["median"] == 0.05 and bar["min"] == 0.0 and bar["last"] == 0.15
    why = {m["fy"]: m["why"] for m in bar["missing"]}
    assert why[2022] == "revenue not positive or net income missing" and why[2018] == "no fiscal-year record held" and len(why) == 5
    assert rb.x_margin_bar(None)["n"] == 0


def test_the_bar_lines_print_the_label_the_years_the_missing_years_and_the_six_statistics_and_no_default():
    bar = rb.op_margin_bar(_rows({2024: (100, 10), 2025: (100, 20)}))
    text = "\n".join(rb.op_margin_bar_lines(bar, False))
    assert text.startswith("## DATA 5.1 - MARGIN HISTORY BAR") and "filed operating margin, operating income / revenue" in text
    assert "FY2024 10.0% | FY2025 20.0%" in text and "FY2018: not held" in text and "min 10.0% | p25 12.5% | median 15.0% | p75 17.5% | max 20.0% | last (FY2025) 20.0%" in text
    assert "no single line of it is the margin to use" in text and "default" in text
    assert "X basis" in "\n".join(rb.op_margin_bar_lines(rb.x_margin_bar({"base_year": 2025, "years": [{"fy": 2025, "x_margin": 0.1}], "skipped": []}), True))


# ---- 5. the basis-corrected consensus ------------------------------------------------------------------------------------------------------------

def _est(eps1=2.0, n1=5, eps2=3.0, n2=5, rev1=10e9, rev2=12e9):
    return {"0y": {"eps": {"avg": eps1, "analysts": n1}, "revenue": {"avg": rev1, "analysts": 5}},
            "+1y": {"eps": {"avg": eps2, "analysts": n2}, "revenue": {"avg": rev2, "analysts": 5}}}


def _cc(estimates=None, filed=1.5, vendor=2.0, shares=1e9, pi=1.0, **kw):
    return rb.consensus_corrected(_est() if estimates is None else estimates, filed, vendor, shares, pi, kw.pop("vendor_break", False), **kw)


def test_the_correction_scales_the_vendor_eps_by_the_base_year_ratio_and_converts_to_x_margins():
    c = _cc()
    assert c["consensus_not_comparable"] is False and c["reason"] is None and math.isclose(c["ratio"], 0.75)
    # y1: 2.0 x 0.75 = 1.5 per share x 1e9 shares over 10e9 revenue = 15%; y2: 3.0 x 0.75 = 2.25 x 1e9 / 12e9 = 18.75%
    assert math.isclose(c["x_margin"]["y1"], 0.15) and math.isclose(c["x_margin"]["y2"], 0.1875)
    assert c["years"]["y1"]["eps_corrected"] == 1.5 and c["years"]["y1"]["eps_vendor"] == 2.0 and c["years"]["y1"]["eps_analysts"] == 5
    assert c["ratio_band"] == [0.5, 2.0] and c["min_eps_analysts"] == 3 and c["filed_eps"] == 1.5 and c["vendor_eps"] == 2.0
    # the uncorrected consensus margin on the same arithmetic would be 20% and 25%: the correction moved it
    import x_margin_basis as xm
    raw = xm.consensus_margins(_est(), 1e9, 1.0)
    assert math.isclose(raw["y1"]["x_margin"], 0.2) and math.isclose(raw["y2"]["x_margin"], 0.25)


def test_the_consensus_revenue_is_attributed_by_pi_and_a_vendor_break_drops_year_two():
    c = _cc(pi=0.5)
    assert math.isclose(c["x_margin"]["y1"], 1.5e9 / 5e9)
    b = _cc(vendor_break=True)
    assert b["consensus_not_comparable"] is False and b["x_margin"]["y2"] is None and "not_comparable" in b["years"]["y2"]


def test_the_ratio_band_is_closed_at_both_edges_and_outside_it_is_not_comparable_with_the_reason_and_no_margin():
    for filed, ok in ((1.0, True), (4.0, True), (0.99, False), (4.02, False)):                   # vendor 2.0: ratios 0.5, 2.0, 0.495, 2.01
        c = _cc(filed=filed)
        assert c["consensus_not_comparable"] is (not ok), filed
        if not ok:
            assert "outside [0.5, 2]" in c["reason"] and c["x_margin"] == {"y1": None, "y2": None} and c["operating_basis"] == {"status": "not_computed"}
    z = _cc(filed=0.0)                                                                            # 0.0 is a value: ratio 0 is outside the band
    assert z["ratio"] == 0.0 and z["consensus_not_comparable"] is True and "0.000" in z["reason"]
    n = _cc(filed=-1.0)
    assert n["ratio"] == -0.5 and n["consensus_not_comparable"] is True


def test_fewer_than_three_eps_analysts_leaves_that_year_without_a_margin_and_both_years_makes_it_not_comparable():
    c = _cc(_est(n2=2))
    assert c["consensus_not_comparable"] is False and c["x_margin"]["y2"] is None and c["years"]["y2"] == {"not_comparable": "2 EPS analyst(s), fewer than 3"}
    assert c["x_margin"]["y1"] is not None
    assert _cc(_est(n2=3))["x_margin"]["y2"] is not None                                          # three is enough
    both = _cc(_est(n1=2, n2=1))
    assert both["consensus_not_comparable"] is True and "3 EPS analysts" in both["reason"] and both["x_margin"] == {"y1": None, "y2": None}


def test_the_other_not_comparable_branches_each_state_their_reason():
    assert "no consensus estimates" in rb.consensus_corrected(None, 1.0, 2.0, 1e9, 1.0, False)["reason"]
    assert "vendor's base-year EPS" in _cc(vendor=None)["reason"] and "vendor's base-year EPS" in _cc(vendor=0.0)["reason"]
    assert "filed base-year EPS" in _cc(filed=None)["reason"]
    assert "not shown to be on one basis" in _cc(vintage_aligned=False)["reason"] and "not shown to be on one basis" in _cc(shares_agree=False)["reason"]
    assert "not shown to be on one basis" in _cc(vintage_aligned=None)["reason"]


def test_the_operating_basis_equivalent_is_pending_until_the_bridge_inversion_exists_and_calls_it_when_it_does(monkeypatch):
    monkeypatch.setitem(sys.modules, "r26_forecast", None)                                        # not importable
    assert _cc()["operating_basis"] == {"status": "pending_bridge"}
    import types
    fake = types.ModuleType("r26_forecast")
    seen = []

    def invert_bridge(x_margin, year, facts, revenue=None):
        seen.append((x_margin, year, facts, revenue))
        return {"status": "ok", "op_margin": x_margin + 0.05}
    fake.invert_bridge = invert_bridge
    monkeypatch.setitem(sys.modules, "r26_forecast", fake)
    c = rb.consensus_corrected(_est(), 1.5, 2.0, 1e9, 1.0, False, bridge_facts={"k": 1}, base_year=2025)
    assert [(round(x, 4), y, f, r) for x, y, f, r in seen] == [(0.15, 1, {"k": 1}, 10.0), (0.1875, 2, {"k": 1}, 12.0)]   # path years; the consensus revenue in $B, the unit of the bridge facts
    assert c["operating_basis"]["status"] == "inverted" and math.isclose(c["operating_basis"]["values"]["y1"]["op_margin"], 0.2)
    # no base year: stated, not guessed
    assert rb.consensus_corrected(_est(), 1.5, 2.0, 1e9, 1.0, False)["operating_basis"] == {"status": "no_base_year"}


# ---- 6. a built GEV r26 pack with consensus data --------------------------------------------------------------------------------------------------

ENRICH = {
    "_ticker": "GEV", "_fetched_at": "2026-09-24T12:00:00",
    "estimates": {
        "0y": {"revenue": {"avg": 41.0e9, "low": 39.0e9, "high": 43.0e9, "analysts": 20, "growth": 0.077, "year_ago": 38.07e9},
               "eps": {"avg": 10.55, "low": 9.0, "high": 12.0, "analysts": 18, "growth": 0.31, "year_ago": 8.05},
               "eps_trend": {"current": 10.55, "d7": 10.5, "d30": 10.4, "d60": 10.1, "d90": 9.9},
               "eps_revisions": {"up7": 1, "up30": 12, "down7": 0, "down30": 2}},
        "+1y": {"revenue": {"avg": 45.5e9, "low": 42.0e9, "high": 48.0e9, "analysts": 19, "growth": 0.11},
                "eps": {"avg": 14.25, "low": 11.0, "high": 17.0, "analysts": 17, "growth": 0.35},
                "eps_trend": {"current": 14.25, "d7": 14.2, "d30": 14.0, "d60": 13.5, "d90": 13.1},
                "eps_revisions": {"up7": 2, "up30": 15, "down7": 0, "down30": 1}}},
    "analyst_target_low": 701.5, "analyst_target_mean": 902.25, "analyst_target_median": 905.0, "analyst_target_high": 1101.5,
    "fifty_two_week_low": 411.25, "fifty_two_week_high": 1011.5,
}


@pytest.fixture
def gev_r26(built, monkeypatch):
    import rs2_data
    orig = rs2_data.load_json

    def fake(p):
        s = str(p).replace("\\", "/")
        if s.endswith("/enrich/GEV.json"):
            return ENRICH
        return orig(p)

    monkeypatch.setattr(rs2_data, "load_json", fake)
    monkeypatch.setattr(cap, "_one_off_us_gaap", lambda t: None)
    return built(pilot_arm="r26"), built(pilot_arm="r25_sf")


LEFT_OUT = ("- Price: $", "- Market cap: ", "- CONSENSUS ESTIMATES", "- BASE-YEAR CHECK", "- [Arithmetic] BASE-YEAR CHECK", "- Next-FY EPS estimate trend", "- Estimate revisions",
            "- Analyst price targets", "- 52-week range", "- Trailing P/E", "## DATA 2.5", "## DATA 8.5", "- levels:", "- next_fy_revenue_growth:",
            "- consensus_data_status:", "- base_year_cap:", "- base_window:", "- x_margin_consensus_y1y2:", "- price:", "- consensus_implied_value:", "- price_implied:")


def test_the_built_blind_pack_leaves_out_the_removed_classes_and_the_full_text_keeps_them(gev_r26):
    pk, sf = gev_r26
    blind, full = str(pk), pk.full_text
    assert blind.split("\n", 1)[0] == "# DATA PACK - GEV   (pack revision 27)" and full.split("\n", 1)[0] == blind.split("\n", 1)[0]
    assert pk.facts["pilot_arm"] == "r26" and pk.facts["desk_schema"] == "25.2" and cap.task_for(pk.facts) is cap.TASK_SF
    sf_text = str(sf)
    assert "- CONSENSUS ESTIMATES" in sf_text and "- Price: $" in sf_text            # the same data, in the arm that prints it
    for prefix in LEFT_OUT:
        assert not any(ln.startswith(prefix) for ln in blind.split("\n")), prefix
    assert any(ln.startswith("- CONSENSUS ESTIMATES") for ln in full.split("\n")) and any(ln.startswith("- Price: $") for ln in full.split("\n"))
    # the long_run line prints without the consensus year-5 members, and its explanation does not describe them
    lr = next(ln for ln in blind.split("\n") if ln.startswith("- long_run:"))
    lr_full = next(ln for ln in full.split("\n") if ln.startswith("- long_run:"))
    assert "e5=" not in lr and "oe5=" not in lr and "m5=" not in lr and "consensus estimates of years 1-2" not in lr and "m_tc=" in lr
    assert "e5=" in lr_full and "m5=" in lr_full
    basis = next(ln for ln in blind.split("\n") if ln.startswith("- earnings_margin_basis:"))
    assert "m5" not in basis and "consensus" not in basis
    # nothing but the removals, the blind variants and DATA 5.1 separates the full text from the short-form pack
    assert [ln for ln in full.split("\n")[1:] if ln not in set(sf_text.split("\n"))][0].startswith("## DATA 5.1")
    assert sf_text.split("\n")[0].endswith("(pack revision 26)")             # the arm's marker differs from the short form's
    # DATA 8 keeps its ROE / gross margin / operating margin line, without the dividend yield (price-derived)
    roe = next(ln for ln in blind.split("\n") if ln.startswith("- Return on equity:"))
    assert "dividend yield" not in roe and "operating margin:" in roe
    assert "dividend yield" in next(ln for ln in full.split("\n") if ln.startswith("- Return on equity:"))
    assert any(r["cls"] == "multiple" and "dividend yield" in r["text"] for r in pk.facts["r26_blind_source"]["removed_lines"])
    # the full text still reads back to the facts, as the short-form pack does
    assert pack_facts.parity(pk.facts, pack_facts.from_text(full)) == []


def test_the_built_pack_carries_the_five_sidecar_keys_and_the_bar_and_the_correction(gev_r26):
    pk, _ = gev_r26
    f = pk.facts
    assert f["version"] == 12 and all(k in pack_facts.KEYS and k in pack_facts.SIDECAR_ONLY for k in R26_KEYS) and all(f[k] is not None for k in R26_KEYS)
    bar = f["op_margin_bar"]
    assert bar["basis"] == "operating" and bar["label"] == "filed operating margin, operating income / revenue" and bar["n"] >= 1
    sec = str(pk)[str(pk).index("## DATA 5.1"):]
    sec = sec[:sec.index("\n\n")]
    assert "filed operating margin, operating income / revenue" in sec and "last (FY" in sec
    # the bar is the filed rows: operating income / revenue for the last year
    import rs2_data
    last = bar["years"][-1]
    assert math.isclose(last["margin"], last["operating_income_b"] / last["revenue_b"]) and bar["last"] == last["margin"]
    cc = f["consensus_corrected"]
    assert cc["consensus_not_comparable"] in (True, False) and "operating_basis" in cc and (cc["ratio"] is None or isinstance(cc["ratio"], float))
    if not cc["consensus_not_comparable"]:
        assert cc["x_margin"]["y1"] is not None and cc["operating_basis"]["status"] in ("pending_bridge", "inverted")
    assert f["r26_leak_audit"]["pass"] is True and f["r26_leak_audit"]["n_removed_numbers"] > 0
    assert f["r26_leak_audit"] == rb.r26_leak_audit(str(pk), f)                                    # the stored result is the audit of the stored text and facts
    # the sidecar is JSON-clean
    json.dumps(f, default=str)
    src = f["r26_blind_source"]
    assert {r["cls"] for r in src["removed_lines"]} >= {"price", "market_cap", "consensus", "multiple", "price_target", "price_action"}
    assert src["spans"][0]["start"] == 0 and src["spans"][-1]["end"] == str(pk).count("\n")


def test_the_margin_bar_basis_follows_the_population_ranges_family_not_the_vendor_sector(gev_r26, monkeypatch):
    import population_ranges
    pk, _ = gev_r26
    assert pk.facts["population_ranges"]["family"] == "operating" and pk.facts["op_margin_bar"]["basis"] == "operating"
    # a vendor sector that says Financial Services (Gold.com: SIC 5051, operating) does not move the bar to the X basis
    monkeypatch.setattr(cap.consensus_reference, "FINANCIAL_SECTORS", ("Financial Services", "Real Estate", pk.facts.get("sector") or "Industrials", "Industrials"))
    op = cap.build_pack("GEV", pilot_arm="r26")
    assert op.facts["population_ranges"]["family"] == "operating" and op.facts["op_margin_bar"]["basis"] == "operating"
    # the family the resolver reads is financial: the bar is on the X basis, so the two agree
    monkeypatch.setattr(population_ranges, "family_for", lambda sic, rows, base_year=None: {"family": "financial", "reason": "test", "stamps": []})
    fin = cap.build_pack("GEV", pilot_arm="r26")
    assert fin.facts["op_margin_bar"]["basis"] == "x"
    import r26_stages
    assert r26_stages.resolve_family(fin.facts, fin.facts["op_margin_bar"]) == ("financial", None)


def test_a_seeded_leak_in_the_built_blind_pack_is_caught(gev_r26):
    pk, _ = gev_r26
    f = pk.facts
    price = float(next(r["text"] for r in f["r26_blind_source"]["removed_lines"] if r["cls"] == "price").split("$")[1].split()[0].rstrip(","))
    form = f"${round(price)}"             # the price to three significant digits, a form the test searches for
    seeded = str(pk) + f"\nA broker note puts the shares near {form} today."
    f2 = json.loads(json.dumps(f, default=str))
    f2["r26_blind_source"]["spans"].append({"start": str(pk).count("\n") + 1, "end": str(pk).count("\n") + 1, "cls": "narrative", "section": "RECENT COMPANY NEWS"})
    a = rb.r26_leak_audit(seeded, f2)
    assert a["pass"] is False and any(x["token"] == form for x in a["leaks"])


# ---- 7. the frozen names (opt-in: it rebuilds MSGE, TASK and DAC from the frozen P1-P4 inputs; it needs the machine's data and a few minutes) ----------------------

BUILD_SCRIPT = r'''
import json, sys, os
from pathlib import Path
env, T, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
sys.path[:0] = [str(env / "tools" / "audit_202608"), str(env / "tools"), str(env)]
import capability_test as cap
assert Path(cap.__file__).resolve().parents[2] == env.resolve()
q = json.load(open(sys.argv[4]))
pt = cap.build_pack(T, price_override={"price": q["price"], "asof": q["asof"]}, pilot_arm="r26")
out.write_text(json.dumps({"blind": str(pt), "full": pt.full_text, "facts": pt.facts}, default=str), encoding="utf-8")
'''


@pytest.mark.skipif(os.environ.get("R26_FROZEN_NAMES") != "1", reason="opt-in: R26_FROZEN_NAMES=1 (rebuilds three packs from the frozen pilot inputs)")
@pytest.mark.parametrize("name", ["MSGE", "TASK", "DAC"])
def test_the_blind_pack_of_a_frozen_name_has_no_removed_class_number(name, tmp_path):
    root = Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks"))
    pilot = root / "stocks-workspace" / "scratch" / "rev23" / "pilot_r25"
    tree, frozen = pilot / "tree_p4sf", pilot / "frozen_p4sf" / name
    if not (tree.is_dir() and frozen.is_dir()):
        pytest.skip("the frozen pilot trees are not on this machine")
    env = tmp_path / "env"
    shutil.copytree(tree, env, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    for mod in ("capability_test", "pack_facts", "r26_blind"):
        shutil.copyfile(HERE.parent / f"{mod}.py", env / "tools" / "audit_202608" / f"{mod}.py")
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    for sub in ("company_news", "catalyst_brief"):                   # the frozen run's date-keyed caches, read as today's
        for src in (env / "cache" / sub).glob(f"{name}_2026-10-17.json"):
            shutil.copyfile(src, src.with_name(f"{name}_{today}.json"))
    script, out = tmp_path / "build.py", tmp_path / "out.json"
    script.write_text(BUILD_SCRIPT, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(env), name, str(out), str(frozen / "quote.json")], capture_output=True, text=True, timeout=900, env=dict(os.environ, STOCKS_ROOT=str(root)))
    assert r.returncode == 0, r.stderr[-2000:]
    doc = json.loads(out.read_text(encoding="utf-8"))
    audit = doc["facts"]["r26_leak_audit"]
    assert audit["leaks"] == [] and audit["pass"] is True and audit["n_removed_numbers"] > 20
    blind = doc["blind"]
    for prefix in LEFT_OUT:
        assert not any(ln.startswith(prefix) for ln in blind.split("\n")), prefix
    assert len(blind) < len(doc["full"])
    print(name, "blind", len(blind), "full", len(doc["full"]), "exceptions", len(audit["exceptions"]), "weak", audit["weak_matches"], "drops", len(doc["facts"]["r26_blind_drops"]))
