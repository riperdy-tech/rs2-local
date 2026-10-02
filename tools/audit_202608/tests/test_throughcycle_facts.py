"""Revision 17 (brief B section 5): the four new pack facts (terminal_ronic, long_run, working_capital,
base_year_cap) parse and write both ways, at the precision the DEFAULTS block prints."""
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools"))

import pack_facts  # noqa: E402

RAW_LR = {"cycle": True, "cycle_year": 2021, "cycle_years": [2016, 2021], "e5": 1.2345678, "oe5": 1.0000004, "m5": 0.12345678,
          "m_tc": 0.0999999, "m_years": [2018, 2025, 8], "r_tc": 0.26146391, "r_years": [2018, 2025, 8],
          "p": 0.875, "g_rev": 0.0295591, "g_rev_years": [2018, 2025, 8], "terminal_g_basis": "revenue_trend",
          "ni_over_oe": 1.14421234, "nwc_intensity": -0.0234567, "nwc_years": [2019, 2025, 7],
          "stub_months": 8.87061234, "stamps": ["record_not_available", "long_run_floor"]}


def _facts(**over):
    f = pack_facts.empty()
    f.update(coe_anchor=0.0898, terminal_g_default=0.0296, terminal_g_anchor=0.0375,
             terminal_ronic=pack_facts.q_rate(0.24000636), long_run=pack_facts.quantize_long_run(RAW_LR),
             working_capital=[pack_facts.q_b(x) for x in (0.0560004, 0.05599, 0.0536464, 0.05, 0.0457943)],
             base_year_cap=pack_facts.quantize_base_year_cap(
                 {"removed": 71724612.26, "ni_filed": 587e6, "ni_capped": 515.27e6, "eps_filed": 5.78,
                  "eps_vendor": 5.08}))
    f.update(over)
    return f


def _text(f, revision=17):
    return f"# DATA PACK - X   (pack revision {revision})\n\n" + pack_facts.render_defaults_block(f)


def test_version_six_and_the_four_keys_are_in_the_empty_object():
    e = pack_facts.empty()
    assert e["version"] == 7                           # revision 18 (brief 1.7): FACTS_VERSION 5 -> 6; revision 19 (brief D4): 6 -> 7
    assert e["terminal_ronic"] is None and e["long_run"] == {} and e["working_capital"] is None
    assert e["base_year_cap"] is None


def test_quantizers_round_to_the_printed_precision_and_pass_infinity():
    assert pack_facts.q_b(1.23456789) == 1.234568
    assert pack_facts.q_rate(0.115732149) == pytest.approx(0.115732) and pack_facts.q_rate(math.inf) == math.inf
    assert pack_facts.q_months(8.87061234) == 8.8706
    lr = pack_facts.quantize_long_run(RAW_LR)
    assert lr["e5"] == 1.234568 and lr["m5"] == pytest.approx(0.123457) and lr["stub_months"] == 8.8706
    assert lr["r_years"] == [2018, 2025, 8] and lr["stamps"] == ["record_not_available", "long_run_floor"]
    assert lr["cycle_years"] == [2016, 2021]
    assert pack_facts.quantize_long_run({}) == {} and pack_facts.quantize_long_run(None) == {}
    lr_none = pack_facts.quantize_long_run({"cycle": None})
    assert lr_none["cycle"] is None and lr_none["e5"] is None and lr_none["stamps"] == []


def test_the_facts_round_trip_through_the_defaults_block_exactly():
    f = _facts()
    g = pack_facts.from_text(_text(f))
    assert pack_facts.parity(f, g) == []
    assert g["long_run"]["nwc_intensity"] == pytest.approx(-0.023457)          # signed rates survive
    assert g["working_capital"] == f["working_capital"] and len(g["working_capital"]) == 5
    assert g["base_year_cap"]["removed"] == pytest.approx(0.071725)
    assert g["source"] == "defaults_block" and g["version"] == 7


def test_infinite_returns_and_unlimited_terminal_round_trip_and_the_sidecar_holds_them(tmp_path):
    lr = dict(RAW_LR, r_tc=math.inf)
    f = _facts(long_run=pack_facts.quantize_long_run(lr), terminal_ronic=math.inf)
    block = pack_facts.render_defaults_block(f)
    assert "- terminal_ronic: unlimited |" in block and "r_tc=+inf" in block
    g = pack_facts.from_text(_text(f))
    assert g["terminal_ronic"] == math.inf and g["long_run"]["r_tc"] == math.inf
    assert pack_facts.parity(f, g) == []
    lr = dict(RAW_LR, r_tc=-math.inf)
    f2 = _facts(long_run=pack_facts.quantize_long_run(lr))
    assert pack_facts.from_text(_text(f2))["long_run"]["r_tc"] == -math.inf
    # the sidecar (python json) keeps the infinity and reads it back
    pack_facts.write_sidecar(tmp_path, f)
    back = pack_facts.read_sidecar(tmp_path)
    assert back["terminal_ronic"] == math.inf and back["long_run"]["r_tc"] == math.inf
    assert back["base_year_cap"] == f["base_year_cap"] and back["working_capital"] == f["working_capital"]


def test_no_cap_no_line_and_an_empty_record_prints_not_available():
    f = _facts(base_year_cap=None, long_run={}, working_capital=None, terminal_ronic=None)
    block = pack_facts.render_defaults_block(f)
    assert "- base_year_cap:" not in block                                # printed only when applied
    for key in ("terminal_ronic", "long_run", "working_capital"):
        assert f"- {key}: not available |" in block
    g = pack_facts.from_text(_text(f))
    assert g["base_year_cap"] is None and g["long_run"] == {} and g["working_capital"] is None and g["terminal_ronic"] is None
    assert pack_facts.parity(f, g) == []


def test_a_revision_17_block_missing_a_line_is_an_error_but_older_blocks_read_without_the_new_keys():
    f = _facts()
    text = _text(f)
    for key in ("terminal_ronic", "long_run", "working_capital"):
        cut = "\n".join(l for l in text.splitlines() if not l.startswith(f"- {key}:"))
        with pytest.raises(ValueError, match=key):
            pack_facts.from_text(cut)
        older = cut.replace("(pack revision 17)", "(pack revision 16)")
        assert pack_facts.from_text(older)["version"] == 7                # a revision-16 block has none of them
    older = "\n".join(l for l in text.splitlines()
                      if not l.startswith(("- terminal_ronic:", "- long_run:", "- working_capital:", "- base_year_cap:")))
    g = pack_facts.from_text(older.replace("(pack revision 17)", "(pack revision 15)"))
    assert g["terminal_ronic"] is None and g["long_run"] == {} and g["working_capital"] is None and g["base_year_cap"] is None


def test_a_malformed_long_run_is_an_error_not_a_guess():
    f = _facts()
    text = _text(f).replace("m_years=2018-2025:8", "m_years=eight")
    with pytest.raises(ValueError, match="m_years"):
        pack_facts.from_text(text)
    text = _text(f).replace(", stub_months=8.8706", "")
    with pytest.raises(ValueError, match="stub_months"):
        pack_facts.from_text(text)


def test_the_sentences_carry_the_basis_and_the_reason_field():
    f = _facts()
    block = pack_facts.render_defaults_block(f)
    line = {l.split(":", 1)[0][2:]: l for l in block.splitlines() if l.startswith("- ")}
    assert "from your own revenue trend FY2018-FY2025: 2.96%/yr, held between breakeven inflation and the anchor" in line["terminal_g_default"]
    assert "more than 0.5 points away needs terminal_reason" in line["terminal_g_default"]
    assert "a Base terminal_ronic more than 2 points away needs terminal_reason" in line["terminal_ronic"]
    assert "the desk holds the Base's years 1-2 at year1 and year2 unless you pass guidance_deviation_reason" in line["levels"]
    assert "2.96%" not in line["levels"] and "not available" not in line["working_capital"].split(" | ")[0]
    assert "removed ($B)" in line["base_year_cap"]
    # each new line is one sentence: no sentence-ending full stop inside its explanation
    for key in ("terminal_ronic", "working_capital", "base_year_cap", "terminal_g_default"):
        explanation = line[key].split(" | ", 1)[1]
        assert ". " not in explanation, key
    # brief B2 F6: the long_run explanation is two sentences, nothing more (brief F4 rewrote the first: the margin rule
    # and the return now drive the long run; revision 18: the return is R_tc, the margin moves all the way to om_trend)
    assert line["long_run"].split(" | ", 1)[1] == (
        "The desk values years 6 on from X_5 (earnings before acquired-intangible amortization), pays for growth at a "
        "return that fades from r_tc (your record's 8-year median return on tangible invested capital) to "
        "terminal_ronic, and moves the margin from m5 to m_long by year 10 "
        "(margin_ratio = m_long / m5; none means the margin is held): om_5, the operating margin the consensus implies "
        "at year 5, moves all the way to om_trend, the trend level of your record's 8-year operating margin (to zero "
        "for a loss record). The members are the record behind it.")
    assert "cycle_years=2016;2021," in line["long_run"] and "cycle_year=2021," in line["long_run"]
    # the return the record measures is named for what it is
    ok = _facts(long_run=pack_facts.quantize_long_run(dict(RAW_LR, stamps=[])))
    assert "r_tc, your record's median return on tangible invested capital" in [
        l for l in pack_facts.render_defaults_block(ok).splitlines() if l.startswith("- terminal_ronic")][0]
    # with no revenue trend the default says which rule it came from
    fb = _facts(long_run=pack_facts.quantize_long_run(dict(RAW_LR, terminal_g_basis="consensus_fallback", g_rev=None,
                                                          g_rev_years=None)))
    assert "the next-FY consensus revenue growth rule" in [l for l in pack_facts.render_defaults_block(fb).splitlines()
                                                          if l.startswith("- terminal_g_default")][0]
    # with no record, terminal_ronic says why it is the cost of equity
    nr = _facts(long_run=pack_facts.quantize_long_run(dict(RAW_LR, stamps=["record_not_available"])))
    assert "so it is the cost of equity and growth adds no value" in [
        l for l in pack_facts.render_defaults_block(nr).splitlines() if l.startswith("- terminal_ronic")][0]


def test_the_defaults_block_no_longer_carries_a_default_exit_multiple_line():
    block = pack_facts.render_defaults_block(_facts())
    assert "default_exit_multiple" not in block and "exit multiple" not in block.lower()
    with pytest.raises(TypeError):
        pack_facts.render_defaults_block(_facts(), default_exit_multiple=19.8)


# ---- the long_run text says where the desk starts the return on new investment (revision 18 follow-up, finding 16) --------------------------

FADES = "pays for growth at a return that fades from r_tc (your record's 8-year median return on tangible invested capital) to terminal_ronic,"
STARTS = ("pays for growth at a return that starts at the cost of equity, coe_anchor (r_tc, your record's 8-year median return on tangible "
          "invested capital, is not above it or is not available), then fades to terminal_ronic,")


def _long_run_line(r_tc, coe=0.0898):
    f = _facts(coe_anchor=coe, long_run=pack_facts.quantize_long_run(dict(RAW_LR, r_tc=r_tc, stamps=[])))
    return [l for l in pack_facts.render_defaults_block(f).splitlines() if l.startswith("- long_run")][0]


@pytest.mark.parametrize("r_tc,starts_at_r_tc", [
    (0.26, True), (0.0899, True), (math.inf, True),                       # above the cost of equity (+inf included): the return starts at r_tc
    (0.0898, False), (0.05, False), (-0.04, False), (-math.inf, False), (None, False),   # not above it, -inf, or none: it starts at the cost of equity
])
def test_the_long_run_text_names_where_the_return_starts_as_the_desk_starts_it(r_tc, starts_at_r_tc):
    line = _long_run_line(r_tc)
    assert (FADES in line) is starts_at_r_tc and (STARTS in line) is (not starts_at_r_tc)
    # the claim is the desk's arithmetic: ronic0 = max(cost of equity, r_tc), the cost of equity where r_tc is none or not above it
    import financial_model_tool as fmt
    coe = 0.0898
    lr = {"e5": 1.0, "oe5": 1.0, "r_tc": r_tc}
    _e5, _mr, ronic0, _rt, _st = fmt._long_run_inputs(lr, 1.0, 0.1, coe)
    assert (ronic0 > coe) is starts_at_r_tc and (ronic0 == r_tc if starts_at_r_tc else ronic0 == coe)


def test_the_long_run_text_is_the_old_one_where_r_tc_is_above_the_cost_of_equity_and_everything_else_is_untouched():
    above = _long_run_line(0.26)
    below = _long_run_line(-0.04)
    assert FADES in above and STARTS in below
    # only the one clause differs between the two cases
    assert above.split(" | ", 1)[1].replace(FADES, "<C>") == below.split(" | ", 1)[1].replace(STARTS, "<C>")
