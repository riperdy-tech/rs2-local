"""Revision 25 short form (BRIEF_SF_short_form.md): desk schema 25.2 and the pilot arm r25_sf.

1. The switch: the arm, its revision marker, its desk schema, its TASK; every other arm unchanged.
2. The pack additions: the earnings-margin basis in plain words, x_margin_history (with and without one-offs), x_margin_consensus_y1y2, printed beside long_run and
   kept in the facts; the one-off add-back (x_margin_basis).
3. The desk (25.2): the two lists are accepted; the normalization block, the labels, every C and K check and every reason request are absent; the arithmetic is the
   25.1 bridge's path arithmetic.
4. The basis flag: inside and outside the registered band [0.67, 1.5], no consensus, 0.0 kept as a value, an annotation that changes nothing.
5. The contract fill and the verdict row for a 25.2 run.
"""
import copy
import json
import math
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import analyst_tools as at  # noqa: E402
import bridge_checks as bc  # noqa: E402
import capability_test as cap  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import contract_fill as cf  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
import x_margin_basis as xm  # noqa: E402
from test_rev24_s2b_pack import built  # noqa: E402,F401  (the fixture: a built GEV pack)
from test_rev25_bridge import BASE_CF, LABELS, NORM, _call, _ctx, _dcf, _run, _sc  # noqa: E402

CONS = {"y1": {"x_margin": 0.30}, "y2": {"x_margin": 0.30}}
NEW_KEYS = ("x_margin_history", "x_margin_consensus_y1y2")
R26_KEYS = ("r26_blind_drops", "op_margin_bar", "consensus_corrected", "r26_leak_audit", "r26_blind_source")      # revision 26: None on every other arm
DEFAULT_LINES = ("- earnings_margin_basis:", "- x_margin_history:", "- x_margin_consensus_y1y2:")


def _ctx252(cons=CONS, **over):
    return _ctx(desk_schema="25.2", x_margin_consensus_y1y2=cons, **over)


def _call252(**over):
    """Three scenarios with the two lists only (no normalization, no labels)."""
    scs = [_sc("Base", 0.5), _sc("Bull", 0.25, earnings_margin=[0.31] * 5, long_run_margin=0.31),
           _sc("Bear", 0.25, revenue_growth=[0.06] * 5, earnings_margin=[0.29] * 5, long_run_margin=0.29)]
    return _call(scs, **over)


def _run252(call=None, ctx=None):
    return _run(call or _call252(), ctx or _ctx252())


# ---- 1. the switch --------------------------------------------------------------------------------------------------------------------------

def test_the_short_form_arm_is_a_pilot_arm_outside_the_two_pass_arms():
    assert "r25_sf" in cap.PILOT_ARMS and cap.R25_SF_ARM == "r25_sf" and cap.R25_SF_ARM not in cap.R25_ARMS
    assert (cap.R25_SF_REVISION, cap.DESK_SCHEMA_252, cap.PACK_REVISION) == (26, "25.2", 24)       # PACK_REVISION is not bumped: no book name re-triggers
    assert cap.pack_flags("r25_sf") == ("r25_sf", False)
    with pytest.raises(ValueError):
        cap.pack_flags("r25_sf", ranges_show_p50=True)
    assert cv.two_pass_setup({"pilot_arm": "r25_sf"}) is None                                         # a single pass: the protocol never opens
    assert cv.two_pass_setup({"pilot_arm": "r25_b"}) == {"arm": "r25_b", "withheld_block": None}


def test_the_new_facts_belong_to_pack_facts_and_are_sidecar_only():
    for k in NEW_KEYS:
        assert k in pack_facts.KEYS and k in pack_facts.SIDECAR_ONLY and pack_facts.empty()[k] is None
    assert pack_facts.parity({k: {"a": 1} for k in NEW_KEYS}, {k: None for k in NEW_KEYS}) == []       # a text read gives None; parity leaves them out


def test_the_short_form_task_changes_item_3_only_and_carries_no_normalization_or_second_pass():
    t = cap.TASK_SF
    assert cap.task_for({"desk_schema": "25.2"}) is t and cap.task_for({"desk_schema": "25.1"}) is cap.TASK_REV25 and cap.task_for({}) is cap.TASK
    for word in ("revenue_growth", "earnings_margin", "earnings_margin_basis", "x_margin_history", "x_margin_consensus_y1y2", "0.67 to 1.5", "as information",
                 "your declared revenue path from the filed base year"):
        assert word in t
    assert xm.BASIS_WORDS[0].upper() + xm.BASIS_WORDS[1:] in t
    for gone in ("normalized_margin", "normalization_horizon", "structural_growth", "normalized_revenue_base", "bridge_C1_reason", "class_K1_reason", "cycle_evidence_",
                 "reconciliation_reasons", "pass 1", "two passes", "Operating margins (om_tc"):
        assert gone not in t, gone
    # the revision-24 written-report items are kept exactly
    contract = t[t.index("```json:underwriting"):]
    for f in ("near_term_earnings", "normalized_earnings", "normalization_reason", "margin_persistence", "cycle_position", "growth_trajectory"):
        assert f'"{f}"' in contract
    assert contract == cap.TASK[cap.TASK.index("```json:underwriting"):]
    assert "   a. State your near-term earnings" in t and "   b. Classify three dimensions" in t
    assert "and pass all three in the desk call" not in t                                              # the labels are not the desk call's
    # item 3 differs from the revision-24 TASK in exactly the three registered passages
    rebuilt = (cap.TASK.replace("the growth of that cash flow (not revenue) for years 1-5 in Base, Bull and Bear;",
                                "the revenue growth and the earnings margin of years 1-5 in Base, Bull and Bear (the two lists, below);")
               .replace("the revenue being the consensus revenue path scaled year by year by that scenario's owner earnings over the consensus owner earnings, unless",
                        "the revenue being your declared revenue path from the filed base year, unless")
               .replace("   - Growth: your years 1-2 are your own;", cap.SF_BASIS_PARAGRAPH + "   - Growth: your years 1-2 are your own;"))
    assert rebuilt == t


def test_the_instruction_three_field_list_for_a_revision_26_pack_is_the_revision_24_one():
    assert cap.FORM_FIELDS_III != cap.FORM_FIELDS_25                                                    # the 25.1 contract drops the five typed fields; 25.2 keeps them
    src = Path(cv.__file__).read_text(encoding="utf-8")
    assert "cap.R25_SF_REVISION" in src and "cap.FORM_FIELDS_III" in src


# ---- 2. the pack: a built GEV pack -------------------------------------------------------------------------------------------------------------

def _body(text):
    return text.split("\n", 1)[1]


def test_a_built_short_form_pack_is_the_revision_24_pack_with_three_defaults_lines(built, monkeypatch):
    monkeypatch.setattr(cap, "_one_off_us_gaap", lambda t: None)
    a, sf = built(pilot_arm="iii_no_p50"), built(pilot_arm="r25_sf")
    assert str(sf).split("\n", 1)[0] == "# DATA PACK - GEV   (pack revision 26)" and str(a).split("\n", 1)[0] == "# DATA PACK - GEV   (pack revision 24)"
    assert sf.facts["desk_schema"] == "25.2" and sf.facts["pilot_arm"] == "r25_sf" and sf.facts["ranges_show_p50"] is False
    assert cap.task_for(sf.facts) is cap.TASK_SF and cap.task_for(a.facts) is cap.TASK
    new_lines = pack_facts.render_x_margin_lines(sf.facts)
    assert [ln.split(":")[0] for ln in new_lines] == [d.rstrip(":") for d in DEFAULT_LINES]
    assert all(ln in str(sf) for ln in new_lines) and not any(d in str(a) for d in DEFAULT_LINES)         # no other arm prints them
    # the 25.2 pack differs from the arm-A pack by its marker and exactly those lines, which sit right after long_run
    assert pack_facts.insert_x_margin_lines(str(a), sf.facts) == str(sf).replace("(pack revision 26)", "(pack revision 24)", 1)
    lines = str(sf).split("\n")
    i = next(k for k, ln in enumerate(lines) if ln.startswith("- long_run:"))
    assert lines[i + 1:i + 4] == new_lines
    assert pack_facts.parity(sf.facts, pack_facts.from_text(str(sf))) == []                             # the text still reads back to the facts
    # the facts differ from arm A's in pilot_arm, desk_schema and the two new facts alone
    differs = sorted(k for k in sf.facts if sf.facts[k] != a.facts.get(k))
    assert differs == sorted(["pilot_arm", "desk_schema", *NEW_KEYS])
    assert sf.facts["x_margin_history"]["sec_facts_held"] is False and "one_off_lines_not_held" in sf.facts["x_margin_history"]["stamps"]
    ctx = cv.build_desk_context(sf.facts, 100.0, "GEV", "GEV")
    assert ctx["desk_schema"] == "25.2" and ctx["x_margin_consensus_y1y2"] == sf.facts["x_margin_consensus_y1y2"]
    assert "x_margin_consensus_y1y2" not in cv.build_desk_context(a.facts, 100.0, "GEV", "GEV")           # every other context is as it was


# sha256 of str(pack) and of the facts (without the two new keys, which every pack now carries as None) of build_pack("GEV") on the committed slice at 8e2cb8a, the commit before the
# short form: every other arm's pack is byte-identical after it (computed by building the same fixture at 8e2cb8a and here)
LEGACY_8E2CB8A = {
    None: ("71c5645034c5088945017bc8c413eddfc564fc36ff9a59c90cc9eb7d3c0e96f3", "158886954045418b117fc13aa0e2eb79e16b6acc5547f00982220dd43d7ee6f7"),
    "rev22": ("1c4d2859f582e73e1df0e0452ee00ffebe5d638a2ddfbd91c1b1574b98ccfff9", "89cfe6cb5c66a0120654aa186ee3c5cbe4823ff52125c6140ee7165a42cb3a16"),
    "iii_p50": ("221936accd4a01ec30e74c8f1550e3b69685448d1dc405f377c4e0fe805865e0", "085d6953882893f935ef893dcc8c94dff5caec552ad9ff5b4955816745929d0a"),
    "iii_no_p50": ("71c5645034c5088945017bc8c413eddfc564fc36ff9a59c90cc9eb7d3c0e96f3", "daa94f178051533cd5c4afc99959d972bf4ae60e764d364d63d28ad51599cf4e"),
    "r25_b": ("cbbad4de7b6d3c53376e2114289151b5069a6fe897c3acad913687394240d413", "4b930893eaf359e2526ee8fae1d72e84f85420b8b883da83a3ebc23b2e6f657d"),
    "r25_c": ("cbbad4de7b6d3c53376e2114289151b5069a6fe897c3acad913687394240d413", "7688228f47e65f64280d1163017617aae4537fc92580f1ca76e242b06efee9fc"),
}


def test_every_other_arms_pack_and_facts_are_byte_identical_to_the_commit_before_the_short_form(built):
    import hashlib
    for arm, (pack_sha, facts_sha) in LEGACY_8E2CB8A.items():
        pk = built(pilot_arm=arm) if arm else built()
        facts = {k: v for k, v in pk.facts.items() if k not in NEW_KEYS + R26_KEYS}
        facts["version"] = 11          # revision 26 bumped FACTS_VERSION 11 -> 12 and added five None keys (R26_KEYS); the pinned hashes are of the version-11 facts
        assert all(pk.facts[k] is None for k in R26_KEYS)
        assert pk.facts["x_margin_history"] is None and pk.facts["x_margin_consensus_y1y2"] is None
        assert hashlib.sha256(str(pk).encode()).hexdigest() == pack_sha, arm
        assert hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest() == facts_sha, arm


def test_the_x_margin_lines_render_nothing_for_any_other_pack():
    for facts in ({}, {"desk_schema": None}, {"desk_schema": "25.1"}):
        assert pack_facts.render_x_margin_lines(facts) == []
    with pytest.raises(ValueError, match="not a desk-schema 25.2"):
        pack_facts.insert_x_margin_lines("## DEFAULTS\n- long_run: x | y", {})


def test_insert_refuses_a_block_that_cannot_take_the_lines():
    facts = {"desk_schema": "25.2", "x_margin_history": None, "x_margin_consensus_y1y2": None}
    ok = "# DATA PACK - T   (pack revision 24)\n## DEFAULTS   [x]\n- a: 1 | e\n- long_run: x | y\n- b: 2 | e\n\n## NEXT"
    out = pack_facts.insert_x_margin_lines(ok, facts)
    assert out.index("- long_run:") < out.index("- earnings_margin_basis:") < out.index("- b: 2")
    with pytest.raises(ValueError, match="already holds"):
        pack_facts.insert_x_margin_lines(out, facts)
    with pytest.raises(ValueError, match="no DEFAULTS"):
        pack_facts.insert_x_margin_lines("# t\n- long_run: x | y", facts)
    with pytest.raises(ValueError, match="long_run lines, not 1"):
        pack_facts.insert_x_margin_lines(ok.replace("- long_run: x | y\n", ""), facts)


# ---- 2b. the one-off add-back and the history -----------------------------------------------------------------------------------------------------

def _row(rev, ni, amort=None, pretax=None, tax=None):
    return {"revenue": rev, "net_income": ni, "amortization_intangibles": amort, "pretax_income": pretax, "tax_provision": tax}


def _line(val, end="2024-12-31", form="10-K", filed="2025-02-20", start="2024-01-01"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed, "accn": "0000000000-25-000001", "fp": "FY"}


def _gaap(**tags):
    d = {"Revenues": {"units": {"USD": [_line(1e9)]}}}              # an annual row of any tag: the file speaks for that year
    d.update({k: {"units": {"USD": v if isinstance(v, list) else [v]}} for k, v in tags.items()})
    return d


ROWS = {2024: _row(1e9, 100e6, amort=20e6, pretax=125e6, tax=25e6)}       # tax rate 20%: X = 100 + 20 x 0.8 = 116 -> 11.6%
ENDS = {"2024": "2024-12-31"}


def test_the_one_off_add_back_is_after_tax_at_the_records_rate_and_counts_a_group_once():
    us = _gaap(GoodwillImpairmentLoss=_line(50e6), AssetImpairmentCharges=_line(80e6), ImpairmentOfLongLivedAssetsHeldForUse=_line(80e6), RestructuringCharges=_line(10e6))
    h = xm.history(ROWS, [], ENDS, us)
    y = h["years"][0]
    assert y["fy"] == 2024 and y["x_margin"] == pytest.approx(0.116) and y["tax_rate"] == pytest.approx(0.20)
    assert y["impairment_b"] == pytest.approx(0.080) and y["restructuring_b"] == pytest.approx(0.010)          # the largest line of the impairment group, not 50 + 80 + 80
    assert y["one_offs_after_tax_b"] == pytest.approx(0.072)
    assert y["x_margin_ex_one_offs"] == pytest.approx((116e6 + 72e6) / 1e9) and y["one_offs_status"] == "filed"
    counted = {ln["tag"] for ln in y["one_off_lines"] if ln["counted"]}
    assert counted == {"AssetImpairmentCharges", "RestructuringCharges"} or counted == {"ImpairmentOfLongLivedAssetsHeldForUse", "RestructuringCharges"}
    listed = {ln["tag"]: ln for ln in y["one_off_lines"]}
    assert set(listed) == {"GoodwillImpairmentLoss", "AssetImpairmentCharges", "ImpairmentOfLongLivedAssetsHeldForUse", "RestructuringCharges"}
    assert all(ln["form"] == "10-K" and ln["filed"] == "2025-02-20" and ln["accn"] for ln in listed.values())          # each line carries its source
    assert listed["GoodwillImpairmentLoss"]["counted"] is False and "largest line" in listed["GoodwillImpairmentLoss"]["note"]


def test_a_restated_line_replaces_the_first_filing_and_a_foreign_filers_annual_form_counts():
    us = _gaap(RestructuringCharges=[_line(5e6, filed="2025-02-20"), _line(7e6, filed="2026-02-20")], GoodwillImpairmentLoss=_line(30e6, form="20-F"))
    y = xm.history(ROWS, [], ENDS, us)["years"][0]
    assert y["restructuring_b"] == pytest.approx(0.007) and y["impairment_b"] == pytest.approx(0.030)
    q = _gaap(RestructuringCharges=[_line(9e6, form="10-Q", start="2024-10-01", end="2024-12-31")])              # a quarter is not an annual line
    assert xm.history(ROWS, [], ENDS, q)["years"][0]["one_offs_status"] == "none_filed"


def test_none_filed_not_held_and_a_year_the_file_does_not_cover_are_three_different_statements():
    none = xm.history(ROWS, [], ENDS, _gaap())["years"][0]
    assert none["one_offs_status"] == "none_filed" and none["x_margin_ex_one_offs"] == none["x_margin"] and none["one_off_lines"] == []
    held_not = xm.history(ROWS, [], ENDS, None)
    assert held_not["years"][0]["one_offs_status"] == "not_held" and held_not["sec_facts_held"] is False and "one_off_lines_not_held" in held_not["stamps"]
    uncovered = xm.history({2025: _row(1e9, 100e6)}, [], {"2025": "2025-12-31"}, _gaap())["years"][0]         # the file has no annual row ending 2025-12-31
    assert uncovered["one_offs_status"] == "not_held"
    assert xm.history(ROWS, [], {}, _gaap())["years"][0]["one_offs_status"] == "not_held"                       # no period end for the year


def test_zero_is_a_value_in_the_history_and_a_non_positive_line_is_listed_never_counted():
    us = _gaap(GoodwillImpairmentLoss=_line(0), ImpairmentOfLongLivedAssetsToBeDisposedOf=_line(-210715000))
    y = xm.history(ROWS, [], ENDS, us)["years"][0]
    assert y["one_offs_status"] == "none_filed" and y["impairment_b"] == 0.0 and y["x_margin_ex_one_offs"] == y["x_margin"]
    assert {ln["tag"]: ln["value_b"] for ln in y["one_off_lines"]} == {"GoodwillImpairmentLoss": 0.0, "ImpairmentOfLongLivedAssetsToBeDisposedOf": -0.210715}
    assert all(ln["counted"] is False for ln in y["one_off_lines"])
    zero = xm.history({2024: _row(1e9, 0.0)}, [], ENDS, _gaap())["years"][0]
    assert zero["x_margin"] == 0.0 and zero["x_margin_ex_one_offs"] == 0.0                                      # a margin of 0.0 is kept, not skipped
    loss = xm.history({2024: _row(1e9, -50e6)}, [], ENDS, _gaap(AssetImpairmentCharges=_line(40e6)))["years"][0]
    assert loss["x_margin"] == pytest.approx(-0.05) and loss["x_margin_ex_one_offs"] == pytest.approx(-0.05 + 0.04 * (1 - 0.21))     # the default tax rate 0.21 when none computes


def test_the_history_follows_the_records_x_arithmetic_and_its_window():
    import throughcycle_record as tcr
    rows = {y: _row(1e9 + 1e7 * y, 50e6 + 1e6 * y, amort=10e6, pretax=70e6, tax=14e6) for y in range(2014, 2025)}
    h = xm.history(rows, [], {}, None)
    assert [y["fy"] for y in h["years"]] == list(range(2017, 2025))                                             # L-7..L, the record's window
    for y in h["years"]:
        x, gap = tcr.earnings_detail(rows[y["fy"]], ())
        assert y["x_margin"] == x / rows[y["fy"]]["revenue"] and gap is False
    rec = tcr.analyse(rows, 0.09)
    assert sorted(y["fy"] for y in h["years"]) == rec["m_years"] and rec["m_tc"] == pytest.approx(tcr.median([y["x_margin"] for y in h["years"]]))
    gap = xm.history({2024: _row(1e9, 100e6, amort=None)}, [], ENDS, None)                                      # a tagged filer's missing amortization: net income alone, stamped
    assert gap["years"][0]["amortization_gap"] is True and "amortization_gap:2024" in gap["stamps"]
    assert xm.history({2024: _row(1e9, 100e6, amort=None)}, ["amortization_intangibles"], ENDS, None)["years"][0]["amortization_gap"] is False
    assert xm.history({}, [], {}, None)["stamps"] == ["x_margin_history_no_rows"] and xm.history({}, [], {}, None)["years"] == []


def test_the_defaults_text_states_each_year_with_its_sources_and_says_where_none_are_filed():
    us = _gaap(AssetImpairmentCharges=_line(80e6), RestructuringCharges=_line(10e6))
    hist = xm.history({2024: ROWS[2024], 2023: _row(1e9, 90e6, pretax=110e6, tax=22e6)}, [], {"2024": "2024-12-31", "2023": "2023-12-31"}, us)
    facts = {"desk_schema": "25.2", "x_margin_history": hist, "x_margin_consensus_y1y2": {"y1": {"x_margin": 0.11}, "y2": None, "stamps": [], "reason": None}}
    lines = pack_facts.render_x_margin_lines(facts)
    hist_line = next(ln for ln in lines if ln.startswith("- x_margin_history:"))
    assert "FY2024 11.6% as filed (filed one-offs after tax at 20.0% are 7.2 margin points" in hist_line and "the margin excluding those lines is 18.8%" in hist_line
    assert "AssetImpairmentCharges, 10-K filed 2025-02-20" in hist_line and "RestructuringCharges, 10-K filed 2025-02-20" in hist_line
    assert "normal" not in hist_line.lower() and "present in 1 of the last 2 years" in hist_line
    assert "FY2023 9.0% as filed" in hist_line and "not held for this year" in hist_line               # the 2023 year end is not covered by the file's 2024 rows
    assert hist_line.count(" | ") == 1                                                                   # the value never holds the reader's separator
    basis = lines[0]
    assert xm.BASIS_WORDS in basis and basis.startswith("- earnings_margin_basis: the X basis | ")
    assert "- x_margin_consensus_y1y2: y1=11.0%, y2=none | " in "\n".join(lines)
    none_filed = pack_facts.render_x_margin_lines(dict(facts, x_margin_history=xm.history(ROWS, [], ENDS, _gaap())))
    assert "no impairment or restructuring line filed" in none_filed[1]
    nocons = pack_facts.render_x_margin_lines(dict(facts, x_margin_consensus_y1y2={"y1": None, "y2": None, "reason": "no consensus estimates"}))
    assert nocons[2].startswith("- x_margin_consensus_y1y2: not available | no consensus margin: no consensus estimates") and "consensus_margin_check_unavailable" in nocons[2]


# ---- 2c. the consensus-implied margin -------------------------------------------------------------------------------------------------------------

EST = {"0y": {"eps": {"avg": 2.76, "analysts": 2}, "revenue": {"avg": 1.126e9, "analysts": 9}},
       "+1y": {"eps": {"avg": 2.90, "analysts": 2}, "revenue": {"avg": 1.178e9, "analysts": 10}}}


def test_the_consensus_margin_is_eps_times_shares_over_revenue_for_years_1_and_2():
    c = xm.consensus_margins(EST, 47305234.0)
    assert c["y1"]["x_margin"] == pytest.approx(2.76 * 47305234.0 / 1.126e9) and c["y2"]["x_margin"] == pytest.approx(2.90 * 47305234.0 / 1.178e9)
    assert c["y1"]["x_earnings_b"] == pytest.approx(2.76 * 47305234.0 / 1e9) and c["y1"]["revenue_b"] == pytest.approx(1.126) and c["reason"] is None
    half = xm.consensus_margins(EST, 47305234.0, pi=0.5)                                                 # revenue on the common shares' share, as the reference attributes it
    assert half["y1"]["x_margin"] == pytest.approx(2 * c["y1"]["x_margin"]) and half["y1"]["revenue_b"] == pytest.approx(0.563)
    broke = xm.consensus_margins(EST, 47305234.0, vendor_break=True)                                    # the next-FY revenue is dropped on a vendor basis break
    assert broke["y1"] is not None and broke["y2"] is None and "consensus_y2_revenue_dropped_vendor_basis_break" in broke["stamps"]


def test_the_consensus_margin_is_absent_not_invented_and_a_zero_eps_is_a_value():
    for est, shares in ((None, 1e6), ({}, 1e6), (EST, None), (EST, 0), (EST, -5)):
        c = xm.consensus_margins(est, shares)
        assert c["y1"] is None and c["y2"] is None and c["reason"]
    noan = copy.deepcopy(EST)
    noan["0y"]["eps"]["analysts"] = 0
    c = xm.consensus_margins(noan, 1e6)
    assert c["y1"] is None and c["y2"] is not None and "consensus_y1_no_eps" in c["stamps"] and c["reason"] is None
    zero = copy.deepcopy(EST)
    zero["0y"]["eps"]["avg"] = 0.0
    assert xm.consensus_margins(zero, 1e6)["y1"]["x_margin"] == 0.0                                     # 0.0 is a value, not an absence


# ---- 3. the desk: the two lists, nothing else ---------------------------------------------------------------------------------------------------

def test_the_two_lists_are_accepted_and_no_check_a_normalization_or_a_label_exists():
    res = _run252()
    assert "error" not in res, res.get("error")
    for role in ("base", "bull", "bear"):
        d = _dcf(res, role)
        b = d["bridge"]
        assert b["applied"] is True and "desk_schema_25_2" in d["stamps"] and "desk_schema_25_1" not in d["stamps"]
        for gone in ("checks", "class_checks", "n0", "nh"):
            assert gone not in b, gone
        assert set(b["declared"]) == {"revenue_growth", "earnings_margin", "long_run_margin", "inherited"} and b["declared"]["inherited"] == []
        assert "margin_basis" in b
    assert res.get("needs_reasons") in (None, []) and "validation_error" not in res


def test_no_c_or_k_check_runs_under_25_2_and_both_run_under_25_1(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a bridge check ran")
    monkeypatch.setattr(bc, "run_checks", boom)
    monkeypatch.setattr(bc, "run_class_checks", boom)
    for name in ("check_c1", "check_c2", "check_c3", "check_c4", "check_c5", "check_k1", "check_k2", "check_k3", "check_k4"):
        monkeypatch.setattr(bc, name, boom)
    assert "error" not in _run252()
    with pytest.raises(AssertionError, match="a bridge check ran"):
        _run(_call(), _ctx())                                                                           # the 25.1 desk still runs them


def test_the_25_2_arithmetic_is_the_25_1_bridges_path_arithmetic():
    r25 = _run252(ctx=_ctx252())
    r251 = _run(_call(), _ctx())
    for role in ("base", "bull", "bear"):
        a, b = _dcf(r25, role), _dcf(r251, role)
        assert a["per_share_iv_raw"] == b["per_share_iv_raw"] and a["projected_cfs"] == b["projected_cfs"]
        assert a["bridge"]["earnings"] == b["bridge"]["earnings"] and a["bridge"]["owner_earnings"] == b["bridge"]["owner_earnings"]
        assert a["bridge"]["working_capital"] == b["bridge"]["working_capital"] and a["bridge"]["margin_path"] == b["bridge"]["margin_path"]
        assert [s for s in a["stamps"] if s != "desk_schema_25_2"] == [s for s in b["stamps"] if s != "desk_schema_25_1"]


def test_a_25_1_result_is_as_it_was():
    res = _run(_call(), _ctx())
    assert "margin_basis" not in res and "consensus_margin_divergence" not in res
    for role in ("base", "bull", "bear"):
        b = _dcf(res, role)["bridge"]
        assert "margin_basis" not in b and "desk_schema_25_1" in _dcf(res, role)["stamps"]
    assert "Information, not a request" not in fmt.format_model_results_markdown(res)


def test_the_tool_schema_of_25_2_holds_the_two_lists_and_none_of_the_removed_fields():
    tools = at.tools_for({"desk_schema": "25.2", "long_run_defaults_withheld": True})
    fn = next(t["function"] for t in tools if t["function"]["name"] == "run_financial_model")
    top, item = fn["parameters"]["properties"], fn["parameters"]["properties"]["scenarios"]["items"]["properties"]
    assert "revenue_growth" in item and "earnings_margin" in item and "growth_rates" not in top and "growth_rates" not in item
    assert "not the operating margin" in item["earnings_margin"]["description"] and "the desk refuses it" in item["explicit_growth"]["description"]
    removed = ("normalized_margin", "normalization_horizon", "normalized_revenue_base", "structural_growth", "flags", "cycle_position", "growth_trajectory",
               "margin_persistence", "cycle_evidence") + tuple(f"bridge_C{c}_reason" for c in ("1", "1b", "2", "3", "4", "5")) \
        + tuple(f"class_K{k}_reason" for k in ("1", "2", "3", "4"))
    for name in removed:
        assert name not in top and name not in item, name
    t251 = next(t["function"] for t in at.tools_for({"desk_schema": "25.1", "long_run_defaults_withheld": True}) if t["function"]["name"] == "run_financial_model")
    assert "normalized_margin" in t251["parameters"]["properties"]                                      # 25.1 still has them
    assert at.tools_for({"long_run_defaults_withheld": True}) is not None and at.tools_for(None) is at.TOOLS


def test_the_lists_are_required_in_every_scenario_and_named_in_the_refusal():
    call = _call252()
    del call["scenarios"][1]["earnings_margin"]                                                          # Bull: no margins of its own
    del call["scenarios"][0]["revenue_growth"]                                                           # Base: no revenue path
    res = _run252(call)
    assert res["validation_error"] is True
    text = " ".join(res["missing"])
    assert "revenue_growth for Base" in text and "earnings_margin for Bull" in text                        # nothing is inherited from the Base under 25.2
    assert "earnings_margin for Base" not in text


def test_explicit_growth_is_refused_for_a_bridged_scenario_and_accepted_where_the_lists_do_not_apply():
    call = _call252()
    call["scenarios"][0]["explicit_growth"] = [0.1] * 5
    res = _run252(call)
    assert res["validation_error"] is True and any("explicit_growth in Base" in m and "25.2" in m for m in res["missing"])
    finite = _call252(cash_flow_life=10)
    for sc in finite["scenarios"]:
        sc.pop("revenue_growth"), sc.pop("earnings_margin")
        sc["explicit_growth"] = [0.05] * 5
    res = _run252(finite)
    assert "error" not in res, res.get("error")
    b = _dcf(res, "base")["bridge"]
    assert b == {"applied": False, "reason": "finite_life"} and "bridge_not_applied:finite_life" in res["desk_stamps"]      # no labels recorded: they are the written contract's
    assert res["margin_basis"]["status"] == "consensus_margin_check_unavailable" and "consensus_margin_check_unavailable" not in res["desk_stamps"]


# ---- 4. the basis flag -----------------------------------------------------------------------------------------------------------------------------

def _flag_run(declared_y1_y2, cons=CONS):
    """The Base declares the given years 1-2 margins; Bull and Bear keep their order around it (Bear <= Base <= Bull is the desk's rule)."""
    call = _call252()
    base, bull, bear = call["scenarios"]
    base["earnings_margin"] = list(declared_y1_y2) + base["earnings_margin"][2:]
    bull["earnings_margin"] = [m + 0.02 for m in base["earnings_margin"]]
    bear["earnings_margin"] = [m - 0.03 for m in base["earnings_margin"]]
    return _run252(call, _ctx252(cons))


def test_inside_the_band_nothing_is_flagged_and_the_edges_are_inside():
    res = _flag_run([0.30, 0.30])
    assert "consensus_margin_divergence" not in res and res["margin_basis"]["status"] == "checked" and res["margin_basis"]["consensus_margin_divergence"] == []
    assert "consensus_margin_divergence" not in res.get("desk_stamps", [])
    lo, hi = x_lo_hi = (0.67, 1.5)
    assert tuple(res["margin_basis"]["band"]) == x_lo_hi == xm.BASIS_BAND
    edge = _flag_run([0.30 * lo, 0.30 * hi])                                                              # a ratio equal to a band edge is inside
    assert edge["margin_basis"]["scenarios"]["Base"]["gaps"] == []


@pytest.mark.parametrize("declared,year,ratio", [([0.19, 0.30], 1, 0.19 / 0.30), ([0.30, 0.46], 2, 0.46 / 0.30), ([0.0, 0.30], 1, 0.0), ([-0.02, 0.30], 1, -0.02 / 0.30)])
def test_outside_the_band_the_result_carries_the_gap_with_its_values(declared, year, ratio):
    res = _flag_run(declared)
    gaps = [g for g in res["consensus_margin_divergence"] if g["scenario"] == "Base"]
    assert len(gaps) == 1 and gaps[0]["year"] == year and gaps[0]["ratio"] == pytest.approx(ratio) and gaps[0]["consensus"] == 0.30
    assert gaps[0]["declared"] == declared[year - 1] and "consensus_margin_divergence" in res["desk_stamps"]
    assert res["margin_basis"]["scenarios"]["Base"]["gaps"] == [{k: gaps[0][k] for k in ("year", "declared", "consensus", "ratio")}]
    assert _dcf(res, "base")["bridge"]["declared"]["earnings_margin"][year - 1] == declared[year - 1]    # 0.0 and a negative margin stay as declared


def test_the_gap_is_an_annotation_that_changes_nothing_and_is_stated_once_as_information():
    low = {"y1": {"x_margin": 0.10}, "y2": {"x_margin": 0.10}}              # the lists below declare 0.29-0.32: three times the consensus, in every scenario
    flagged = _run252(_call252(), _ctx252(cons=low))
    quiet = _run252(_call252(), _ctx252())
    nocons = _run252(_call252(), _ctx252(cons=None))
    ivs = lambda r: [i["dcf"]["per_share_iv_raw"] for i in r["scenario_dcfs"]]
    assert flagged["consensus_margin_divergence"] and "consensus_margin_divergence" not in quiet and ivs(flagged) == ivs(quiet) == ivs(nocons)       # the flag moves no value
    assert flagged["consensus_margin_divergence"] != [] and len(flagged["consensus_margin_divergence"]) == 6                                       # 3 scenarios x 2 years
    for res in (flagged, quiet, nocons):
        assert res.get("needs_reasons") in (None, []) and "validation_error" not in res                  # never a request, never a refusal
    md = fmt.format_model_results_markdown(flagged)
    assert md.count("Information, not a request") == 1 and "consensus_margin_divergence" in md and "valued your lists as declared" in md      # six gaps, one statement
    assert "Information, not a request" not in fmt.format_model_results_markdown(quiet)
    assert "Information, not a request" not in fmt.format_model_results_markdown(nocons)


def test_no_consensus_is_stated_and_a_nonpositive_consensus_is_not_compared():
    for cons in (None, {}, {"y1": None, "y2": None}):
        res = _run252(_call252(), _ctx252(cons=cons))
        assert res["margin_basis"]["status"] == "consensus_margin_check_unavailable" and "consensus_margin_check_unavailable" in res["desk_stamps"]
        assert "consensus_margin_divergence" not in res and res["margin_basis"]["consensus_margin_divergence"] == []
    ctx = _ctx252()
    del ctx["x_margin_consensus_y1y2"]                                                                   # a context built without the key (an older pack) is no consensus too
    assert _run252(_call252(), ctx)["margin_basis"]["status"] == "consensus_margin_check_unavailable"
    neg = _run252(_call252(), _ctx252(cons={"y1": {"x_margin": -0.05}, "y2": {"x_margin": 0.0}}))
    assert neg["margin_basis"]["status"] == "consensus_margin_check_unavailable" and neg["margin_basis"]["consensus_margin_divergence"] == []
    half = _run252(_call252(), _ctx252(cons={"y1": {"x_margin": 0.30}, "y2": None}))
    assert half["margin_basis"]["status"] == "checked" and list(half["margin_basis"]["scenarios"]["Base"]["years"]) == ["1"]


def test_a_divergence_needs_the_ratio_outside_the_band_and_more_than_three_margin_points():
    cons = {"y1": {"x_margin": 0.04}, "y2": {"x_margin": 0.04}}
    r = xm.basis_check([0.02, 0.0661], cons)            # ratio 0.5 and 4 points off; ratio 1.65 and 2.61 points off
    assert r["years"]["1"]["outside_band"] is False and r["years"]["1"]["abs_gap"] == pytest.approx(0.02)      # outside the band but only 2 points: not a divergence
    assert r["years"]["2"]["outside_band"] is False and r["gaps"] == []                                          # 1.65x but 2.61 points
    r = xm.basis_check([0.0, 0.08], cons)               # 0.0 is a value: ratio 0, 4 points off; 2.0x and 4 points off
    assert [g["year"] for g in r["gaps"]] == [1, 2] and r["years"]["1"]["declared"] == 0.0
    assert xm.basis_check([0.07, 0.0], {"y1": {"x_margin": 0.04}, "y2": {"x_margin": 0.04}})["gaps"][0]["year"] == 2     # 0.07/0.04 = 1.75 but exactly 3 points: not above 3
    assert [g["year"] for g in xm.basis_check([0.0701, 0.04], cons)["gaps"]] == [1]                                   # 3.01 points


def test_basis_check_is_pure_and_reads_two_years():
    r = xm.basis_check([0.2, 0.2, 9, 9, 9], {"y1": {"x_margin": 0.3}, "y2": {"x_margin": 0.1}})
    assert r["years"]["1"]["ratio"] == pytest.approx(2 / 3) and r["years"]["1"]["outside_band"] is True        # 0.667 < 0.67
    assert r["years"]["2"]["ratio"] == pytest.approx(2.0) and [g["year"] for g in r["gaps"]] == [1, 2]
    assert xm.basis_check(None, {"y1": {"x_margin": 0.3}})["years"]["1"]["note"] == "no declared margin"


# ---- 5. the contract fill and the verdict row --------------------------------------------------------------------------------------------------------

def _answer_call(res, call):
    return {"call_index": 1, "params": call, "result": res, "body": res}


def test_the_fill_of_a_25_2_run_carries_the_path_the_schema_and_the_flag_and_derives_nothing_else():
    assert set(cf.FILLED_252) == set(cf.FILLED) | {"bridge", "desk_schema", "consensus_margin_divergence", "post_contract_diagnostics"}
    for gone in ("bridge_checks", "class_checks", "near_term_earnings", "normalized_earnings", "growth_trajectory", "cycle_position", "margin_persistence",
                 "pass1_inputs", "change_log"):
        assert gone not in cf.FILLED_252
    assert "consensus_margin_divergence" in cv.S12_SUMMARY_KEYS and cv.S12_SUMMARY_KEYS[-2:] == ("terminal_value_share", "terminal_reinvestment_rate")
    res = _flag_run([0.10, 0.30])
    src = {role: (None, {"dcf": _dcf(res, role)}) for role in cf.ROLES}
    out, prov = {}, {"stamps": []}
    cf._fill_bridge_252(out, prov, src)
    assert out["desk_schema"] == "25.2" and out["bridge"] is _dcf(res, "base")["bridge"] and "checks" not in out["bridge"]
    base_gaps = [g for g in out["consensus_margin_divergence"] if g["scenario"] == "base"]
    assert len(base_gaps) == 1 and base_gaps[0]["year"] == 1 and base_gaps[0]["declared"] == 0.10 and base_gaps[0]["consensus"] == 0.30
    assert "s12_figures_typed_desk_schema_25_2" in prov["stamps"]
    none = _run252(_call252(), _ctx252(cons=None))
    out2, prov2 = {}, {"stamps": []}
    cf._fill_bridge_252(out2, prov2, {role: (None, {"dcf": _dcf(none, role)}) for role in cf.ROLES})
    assert out2["consensus_margin_divergence"] is None and "consensus_margin_check_unavailable" in prov2["stamps"]
    inside = _run252(_call252(), _ctx252())
    out3, prov3 = {}, {"stamps": []}
    cf._fill_bridge_252(out3, prov3, {role: (None, {"dcf": _dcf(inside, role)}) for role in cf.ROLES})
    assert out3["consensus_margin_divergence"] == [] and prov3["stamps"] == ["s12_figures_typed_desk_schema_25_2", "flat_margin_path"]      # the default Bull and Bear lists are flat (cross-check 21)


def test_the_verdict_row_carries_the_flag_beside_the_other_scorecard_keys():
    src = (HERE.parent.parent.parent / "depth_pipeline.py").read_text(encoding="utf-8")
    assert re.search(r'"desk_schema", "consensus_margin_divergence",', src)


# ---- 6. cross-check 21: the recurring one-off rule and the post-contract diagnostics -----------------------------------------------------------------

def _recurring_rows(years_with_charge):
    rows, us = {}, _gaap()
    us["Revenues"] = {"units": {"USD": [_line(1e9, end=f"{y}-12-31", start=f"{y}-01-01") for y in range(2020, 2025)]}}         # the file covers every year
    for y in range(2020, 2025):
        rows[y] = _row(1e9, 100e6, amort=20e6, pretax=125e6, tax=25e6)
        if y in years_with_charge:
            us["RestructuringCharges"] = {"units": {"USD": us.get("RestructuringCharges", {}).get("units", {}).get("USD", []) + [_line(10e6, end=f"{y}-12-31", start=f"{y}-01-01")]}}
    return rows, {str(y): f"{y}-12-31" for y in rows}, us


def test_a_charge_in_three_of_the_last_five_years_is_recurring_and_no_series_without_it_is_printed():
    rows, ends, us = _recurring_rows({2022, 2023, 2024})
    h = xm.history(rows, [], ends, us)
    assert h["one_off_frequency"] == {"k": 3, "n": 5} and h["recurring"] is True and h["ex_one_offs_printed"] is False
    assert "recurring_restructuring_or_impairment" in h["stamps"]
    assert h["years"][-1]["one_off_margin_points"] == pytest.approx(0.008)                                  # 10e6 x (1 - 0.2) / 1e9, in margin points
    text = pack_facts.render_x_margin_lines({"desk_schema": "25.2", "x_margin_history": h, "x_margin_consensus_y1y2": None})[1]
    assert "present in 3 of the last 5 years" in text and "excluding those lines" not in text and "so no series without it is printed" in text
    assert "FY2024 11.6% as filed" in text and "0.8 margin points" in text and "normal" not in text.lower().replace("normalization", "")
    rows, ends, us = _recurring_rows({2023, 2024})
    h2 = xm.history(rows, [], ends, us)
    assert h2["one_off_frequency"] == {"k": 2, "n": 5} and h2["recurring"] is False and h2["ex_one_offs_printed"] is True
    assert "recurring_restructuring_or_impairment" not in h2["stamps"]
    assert "the margin excluding those lines is 12.4%" in pack_facts.render_x_margin_lines({"desk_schema": "25.2", "x_margin_history": h2, "x_margin_consensus_y1y2": None})[1]
    assert xm.history(rows, [], ends, None)["one_off_frequency"] == {"k": 0, "n": 5}                         # not held is not "filed"


def test_normalized_vs_path_gap_and_flat_margin_path():
    d = xm.post_contract_diagnostics({"base": [0.10] * 5, "bull": [0.12, 0.13, 0.14, 0.15, 0.16], "bear": [0.08, 0.0805, 0.081, 0.0815, 0.0819]}, 0.10, 6.0, 100.0)
    assert d["normalized_vs_path_gap"]["gap"] == pytest.approx(0.04) and d["normalized_vs_path_gap"]["normalized_margin_implied"] == pytest.approx(0.06)
    assert d["flat_margin_path"] == ["base"]                                            # spreads 0.0, 0.04 and 0.0019: only the first is within 0.1 margin point
    assert xm.post_contract_diagnostics({"b": [0.1, 0.1005, 0.1, 0.1, 0.101]}, 0.10, 10.0, 100.0)["flat_margin_path"] == ["b"]      # a spread of exactly 0.1 point is flat
    assert xm.post_contract_diagnostics({}, 0.10, 7.0, 100.0)["normalized_vs_path_gap"] is None               # exactly 3 points: not above
    assert xm.post_contract_diagnostics({}, 0.10, 6.99, 100.0)["normalized_vs_path_gap"] is not None
    assert xm.post_contract_diagnostics({}, 0.10, 0.0, 100.0)["normalized_vs_path_gap"]["normalized_margin_implied"] == 0.0     # 0.0 is a value
    nothing = xm.post_contract_diagnostics({"x": None}, None, "n/a", 100.0)
    assert nothing == {"normalized_vs_path_gap": None, "flat_margin_path": []}                                # no number, no diagnostic


def test_the_fill_stamps_the_post_contract_diagnostics_from_the_contract_after_the_desk_run():
    call = _call252()
    call["scenarios"][0]["earnings_margin"] = [0.30] * 5
    for sc in call["scenarios"][1:]:
        sc["earnings_margin"] = [0.31, 0.32, 0.33, 0.34, 0.35] if sc["name"] == "Bull" else [0.28, 0.285, 0.29, 0.295, 0.30]
    res = _run252(call)
    assert "error" not in res, res.get("error")
    src = {role: (None, {"dcf": _dcf(res, role)}) for role in cf.ROLES}
    out, prov = {}, {"stamps": []}
    cf._fill_bridge_252(out, prov, src, {"normalized_earnings": 15.0})              # R_0 = 100: 15% against the path's 30%
    d = out["post_contract_diagnostics"]
    assert d["normalized_vs_path_gap"]["gap"] == pytest.approx(0.15) and d["flat_margin_path"] == ["base"]
    assert "normalized_vs_path_gap" in prov["stamps"] and "flat_margin_path" in prov["stamps"]
    out2, prov2 = {}, {"stamps": []}
    cf._fill_bridge_252(out2, prov2, src, {"normalized_earnings": 30.0})
    assert out2["post_contract_diagnostics"]["normalized_vs_path_gap"] is None and "normalized_vs_path_gap" not in prov2["stamps"]
    out3, prov3 = {}, {"stamps": []}
    cf._fill_bridge_252(out3, prov3, src, None)                                      # no contract: no diagnostic, no pass
    assert out3["post_contract_diagnostics"]["normalized_vs_path_gap"] is None
    assert "post_contract_diagnostics" in cv.S12_SUMMARY_KEYS
