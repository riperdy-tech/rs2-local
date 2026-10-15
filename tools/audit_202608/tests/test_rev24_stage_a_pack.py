"""Pack revision 24 (PHASE_4_REV24_MUSE.md R24.2, brief BRIEF_R24_2_reference_after_commit.md): stage A, the pack without the reference.

The CONSENSUS-IMPLIED VALUE (CIV) and everything derived from it (its FAR band and the E15 fence text) are not printed; the facts and the sidecar
still hold the value, the status and the omitted line, for stage B and the records. The desk's R10 gate is off and its unit note compares with the
price. A replay takes the CIV from the facts or the sidecar, never from text.

The three real packs are saved baseline packs (pack revisions 21 and 22, 2026-10-05/06): their sidecar facts and the DATA 8 and DEFAULTS sections,
re-built at revision 24 from their facts by the production renderers (`pack_facts.render_defaults_block`, `consensus_reference.window_line`).
"""
import copy
import json
import re
from pathlib import Path

import pytest

import capability_test as cap
import consensus_reference
import consensus_valuation as cv
import financial_model_tool as fmt
import pack_facts

REV24 = Path(__file__).parent / "fixture_data" / "rev24"
REAL = ("AMD", "KSS", "HRTG")       # a growth name, a retailer, an insurer whose BASE WINDOW CHECK printed the fence side
_WIN_RE = re.compile(r"base_window_gap ([+-]?\d+)% \| TTM owner earnings \(through ([\d-]+)\) (-?[\d.,]+) \| the fiscal-year base grown by "
                     r"the consensus current-FY EPS growth for (\d+) quarter\(s\) between them is (-?[\d.,]+)")
_FENCE_RE = re.compile(r"lands (above|below) the street fence \[\$([\d,.]+), \$([\d,.]+)\]")


def _saved(t):
    facts = json.loads((REV24 / f"{t}_pack_facts.json").read_text(encoding="utf-8"))
    for k in pack_facts.KEYS:                       # an older sidecar reads a key it lacks as None (read_sidecar's rule)
        facts.setdefault(k, None)
    return facts, (REV24 / f"{t}_data8_defaults.md").read_text(encoding="utf-8")


def _num(s):
    return float(s.replace(",", ""))


def rebuild_rev24(excerpt, saved_facts):
    """(text, facts) of the saved excerpt as build_pack prints it at revision 24, from its facts: the first line's marker is 24; the reference's
    line is not printed and goes to facts["reference_line"] (build_pack's revision-24 step); the BASE WINDOW CHECK is re-rendered by the production
    window_line without the reference from the numbers the saved line printed; the DEFAULTS block is the production renderer's on the facts."""
    facts = dict(copy.deepcopy(saved_facts), reference_withheld=True)
    out = []
    for line in excerpt.split("\n"):
        if line.startswith("# DATA PACK"):
            out.append(re.sub(r"\(pack revision \d+\)", "(pack revision 24)", line))
        elif line.startswith("- [Arithmetic] CONSENSUS-IMPLIED VALUE") or line.startswith("- CONSENSUS-IMPLIED VALUE"):
            facts["reference_line"] = line
        elif line.startswith("- [Arithmetic] BASE WINDOW CHECK"):
            m = _WIN_RE.search(line)
            win = {"gap": int(m.group(1)) / 100.0, "quarters": int(m.group(4)), "expected_ttm": _num(m.group(5)) * 1e9, "flag": True,
                   "ttm_value": None, "ttm_levels": None}
            f = _FENCE_RE.search(line)
            if f:
                win.update(fence_side=f.group(1), fence=(_num(f.group(2)), _num(f.group(3))))
            out.append(consensus_reference.window_line(win, {"value": facts["consensus_implied_value"]}, _num(m.group(3)) * 1e9, m.group(2),
                                                       cap._bn, base_year_check="the BASE-YEAR CHECK shows" in line, reference_shown=False))
        elif line.startswith("## DEFAULTS"):
            out.append(pack_facts.render_defaults_block(facts, withhold_reference=True))
            break
        else:
            out.append(line)
    return "\n".join(out) + "\n", facts


def _band_texts(civ):
    lo, hi = civ * consensus_reference.FAR_LOW, civ * consensus_reference.FAR_HIGH
    return [f"{civ:,.2f}", f"{lo:,.2f}", f"{hi:,.2f}", f"{consensus_reference.FAR_LOW:g}-{consensus_reference.FAR_HIGH:g}"]


@pytest.mark.parametrize("t", REAL)
def test_the_stage_a_pack_of_a_real_saved_pack_has_no_civ_band_or_fence_while_the_facts_hold_it(t):
    saved, excerpt = _saved(t)
    civ = saved["consensus_implied_value"]
    assert saved["reference_status"] == "used" and isinstance(civ, float) and civ > 0
    # the saved (revision 21/22) excerpt printed it: the check below is not vacuous
    assert any(s in excerpt for s in _band_texts(civ)[:1]) and "consensus_implied_value:" in excerpt
    text, facts = rebuild_rev24(excerpt, saved)
    for s in _band_texts(civ):
        assert s not in text, (t, s)
    for s in ("CONSENSUS-IMPLIED VALUE (reference", "- CONSENSUS-IMPLIED VALUE", "consensus_implied_value:", "reference_status:",
              "street-target fence", "street fence", "the CONSENSUS-IMPLIED VALUE above", "level check only"):
        assert s not in text, (t, s)
    # the facts still hold the value, the status and the omitted line
    assert facts["consensus_implied_value"] == civ and facts["reference_status"] == "used"
    assert facts["reference_line"].startswith("- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $")
    # kept unchanged: the consensus levels and the filed base
    lv = facts["levels"]
    assert f"- levels: year1={lv['year1']:.3f}, year2={lv['year2']:.3f}" in text
    assert f"- reference_base_b: {facts['reference_base_b']:,.6f}" in text


def test_the_hrtg_window_check_keeps_its_rest_without_the_civ_quote_and_the_fence_side():
    saved, excerpt = _saved("HRTG")
    old = next(l for l in excerpt.split("\n") if l.startswith("- [Arithmetic] BASE WINDOW CHECK"))
    assert "lands above the street fence" in old and "(the CONSENSUS-IMPLIED VALUE above)" in old
    text, _ = rebuild_rev24(excerpt, saved)
    new = next(l for l in text.split("\n") if l.startswith("- [Arithmetic] BASE WINDOW CHECK"))
    assert new == ("- [Arithmetic] BASE WINDOW CHECK: base_window_gap +21% | TTM owner earnings (through 2026-06-30) 0.221 | the fiscal-year "
                   "base grown by the consensus current-FY EPS growth for 2 quarter(s) between them is 0.182 (one of the two windows holds "
                   "items the other does not: a one-off gain or charge, a capex swing) | the BASE-YEAR CHECK shows the analysts' own year-ago "
                   "EPS against the filed year")


def test_window_line_keeps_the_ttm_clauses_it_was_not_asked_to_drop():
    win = {"gap": 0.30, "quarters": 2, "expected_ttm": 1e9, "flag": True, "ttm_value": 50.0, "ttm_levels": (1e9, 2e9)}
    shown = consensus_reference.window_line(win, {"value": 40.0}, 1.3e9, "2026-06-30", cap._bn)
    hidden = consensus_reference.window_line(win, {"value": 40.0}, 1.3e9, "2026-06-30", cap._bn, reference_shown=False)
    assert "$40.00 (the CONSENSUS-IMPLIED VALUE above)" in shown and "$40.00" not in hidden
    # revision 24 step 2a (the leak R24.2 reported as a gap): the TTM window's value, the reference times 1 + gap, is no longer printed; its year-2
    # level stays (the shown line still carries both)
    assert "on the TTM window the consensus path is worth $50.00 per share" in shown
    assert "$50.00" not in hidden and "consensus path" not in hidden
    assert "on the TTM window the year-2 cash-flow level is 2.000" in hidden
    neg = dict(win, ttm_value=None, ttm_levels=None)
    assert "the TTM window's owner earnings are not positive" in consensus_reference.window_line(
        neg, {"value": 40.0}, -1e8, "2026-06-30", cap._bn, reference_shown=False)


@pytest.mark.parametrize("t", REAL)
def test_replay_parity_takes_the_civ_from_the_facts_not_the_text(t, tmp_path):
    saved, excerpt = _saved(t)
    text, facts = rebuild_rev24(excerpt, saved)
    parsed = pack_facts.from_text(text)
    assert parsed["source"] == "defaults_block" and parsed["reference_withheld"] is True
    assert parsed["consensus_implied_value"] is None and parsed["reference_status"] is None     # never from text
    assert pack_facts.parity(facts, parsed) == []
    # the replay reads the sidecar: the CIV and its status come back from it, and the desk context a replay builds equals the fresh run's
    pack_facts.write_sidecar(tmp_path, facts)
    side = pack_facts.read_sidecar(tmp_path)
    assert side["consensus_implied_value"] == saved["consensus_implied_value"] and side["reference_status"] == "used"
    assert side["reference_line"] == facts["reference_line"]
    price = saved["price_implied_price"]
    assert cv.build_desk_context(side, price, t, t, "2026-10-05") == cv.build_desk_context(facts, price, t, t, "2026-10-05")


def test_a_revision_23_block_still_reads_the_civ_from_text_and_parity_still_compares_it():
    saved, excerpt = _saved("AMD")
    old = pack_facts.render_defaults_block(saved)
    text = "# DATA PACK - AMD   (pack revision 23)\n\n" + old + "\n"
    parsed = pack_facts.from_text(text)
    assert parsed["consensus_implied_value"] == saved["consensus_implied_value"] and parsed["reference_status"] == "used"
    assert parsed["reference_withheld"] is None
    assert pack_facts.parity(dict(saved, consensus_implied_value=1.0), parsed) == ["consensus_implied_value"]


def test_a_withheld_block_missing_the_civ_lines_does_not_raise_but_an_older_one_does():
    saved, _ = _saved("AMD")
    block = pack_facts.render_defaults_block(saved, withhold_reference=True)
    assert "consensus_implied_value" not in block and "reference_status" not in block
    pack_facts.from_text("# DATA PACK - AMD   (pack revision 24)\n\n" + block + "\n")
    with pytest.raises(ValueError):
        pack_facts.from_text("# DATA PACK - AMD   (pack revision 22)\n\n" + block + "\n")


def test_build_pack_prints_no_reference_and_keeps_it_in_the_facts(screener_data_stub, monkeypatch):
    """The production path on the committed GEV slice with consensus estimates: DATA 8 prints no reference line, DEFAULTS no CIV or status line,
    the TASK no longer names the CIV as context, and the facts carry the reference, its status, its line and the withheld flag."""
    import rs2_data
    from test_consensus_reference import AMD_EST
    orig = rs2_data.load_json
    en = {"_ticker": "GEV", "_fetched_at": "2026-09-24T12:00:00", "estimates": AMD_EST}
    monkeypatch.setattr(rs2_data, "load_json", lambda p: en if str(p).endswith("GEV.json") and "enrich" in str(p) else orig(p))
    built = cap.build_pack("GEV")
    text = str(built)
    f = built.facts
    assert text.splitlines()[0].endswith("(pack revision 24)")
    assert f["reference_withheld"] is True and isinstance(f["reference_line"], str)
    assert "CONSENSUS-IMPLIED VALUE (reference" not in text and "- CONSENSUS-IMPLIED VALUE" not in text
    assert "- consensus_implied_value:" not in text and "- reference_status:" not in text
    if isinstance(f["consensus_implied_value"], float):
        for s in _band_texts(f["consensus_implied_value"])[:3]:
            assert f"${s}" not in text and f"({s}" not in text
    assert "the CONSENSUS-IMPLIED VALUE, the sector bands" not in cap.TASK and "the macro anchors, the sector bands" in cap.TASK
    assert pack_facts.parity(f, pack_facts.from_text(text)) == []


def _desk_args(f, base_cf, wacc_shift=0.0):
    sc = lambda n, p, dv: {"name": n, "prob": p, "base_cf": base_cf, "explicit_growth": f["reference_path"], "wacc": f["coe_anchor"] + dv,
                           "terminal_g": f["terminal_g_default"], "fade_years": 5}
    reasons = {k: "dated evidence 2026-10-01" for k in ("base_cf_reason", "scenario_deviation_reason", "bull_below_price_reason",
                                                         "bear_above_price_reason", "terminal_reason", "coe_adjustment_reason")}
    # revision 24 step 2a: long_run_margin is required; the reference's own m_long keeps these Bases on the reference's arithmetic
    return dict(reasons, cash_flow_life="perpetual", cash_flow_life_reason="perpetual business", sbc_treatment="deducted_in_cf",
                fade_years=5, terminal_g=f["terminal_g_default"], long_run_margin=f["long_run"]["m_long"],
                scenarios=[sc("Base", 0.5, wacc_shift), sc("Bull", 0.25, wacc_shift - 0.01), sc("Bear", 0.25, wacc_shift + 0.01)])


def test_r10_does_not_fire_in_stage_a_and_fires_on_an_older_pack():
    saved, _ = _saved("AMD")
    price = saved["price_implied_price"]
    # a Base far below the reference: the defaults at a discount rate 4 points higher (the desk holds years 1-2 at the levels, so the base alone
    # would not move the value)
    args = _desk_args(saved, saved["reference_base_b"], wacc_shift=0.04)
    old_ctx = cv.build_desk_context(saved, price, "AMD", "AMD", "2026-10-05")              # revision 22 sidecar: reference_withheld None
    assert old_ctx["reference_withheld"] is None
    old = fmt.execute_financial_model(copy.deepcopy(args), old_ctx)
    assert old.get("validation_error") and "guidance_deviation_reason needed: the Base value is" in old["error"]
    new_ctx = cv.build_desk_context(dict(saved, reference_withheld=True), price, "AMD", "AMD", "2026-10-05")
    new = fmt.execute_financial_model(copy.deepcopy(args), new_ctx)
    assert "guidance_deviation_reason needed: the Base value is" not in str(new.get("error") or "")
    assert not new.get("validation_error"), new.get("error")


def test_the_unit_note_compares_with_the_price_in_stage_a():
    saved, _ = _saved("AMD")
    price = saved["price_implied_price"]
    civ = saved["consensus_implied_value"]
    ctx = cv.build_desk_context(dict(saved, reference_withheld=True), price, "AMD", "AMD", "2026-10-05")
    args = _desk_args(saved, saved["reference_base_b"])
    for sc in args["scenarios"]:
        sc["shares_diluted"] = saved["shares_default"] * 1000.0          # a count in the wrong unit: values 1/1000 of the price
    res = fmt.execute_financial_model(args, ctx)
    m = re.search(r"the Base value is ([\d.]+)x the price, too far", res.get("error") or "")     # revision 24 step 2a: it named "the reference"
    assert m, res.get("error")
    base = civ / 1000.0                                                     # the defaults' Base on 1000x the shares (the excess cash too)
    assert abs(float(m.group(1)) - base / price) < 0.0002                  # the ratio is against today's price ...
    assert abs(float(m.group(1)) - base / civ) > 0.0002                    # ... not against the reference


def test_the_desk_schema_no_longer_names_the_reference_band():
    import analyst_tools
    desk = next(t for t in analyst_tools.TOOLS if t["function"]["name"] == "run_financial_model")
    gdr = desk["function"]["parameters"]["properties"]["guidance_deviation_reason"]["description"]
    assert "0.75-1.33" not in gdr and "reference" not in gdr
    assert "year-2 cash flow more than 5% from the DEFAULTS year-2 level" in gdr and "Base years 3-5 above next-FY revenue growth" in gdr


def test_pack_revision_24_and_its_history_line():
    assert cap.PACK_REVISION == 24
    src = Path(cap.__file__).read_text(encoding="utf-8")
    assert ("# Revision 24 (PHASE_4_REV24_MUSE.md R24.2): the CONSENSUS-IMPLIED VALUE is shown only after the analyst commits (stage A without it, "
            "stage B\n#   reveal with code-enforced revision guardrails); the R10 gate is off.") in src
