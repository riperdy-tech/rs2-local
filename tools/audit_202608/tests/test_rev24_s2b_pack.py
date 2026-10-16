"""Revision 24 step 2b, the briefing (BRIEF_R24_S2b_ranges_gate.md items 2, 4 and 7, and the "Additions from step 2a"):

- the revision-24 pack (the pilot arms iii) prints no default for a long-run judgment: no terminal_g_default, terminal_ronic or price_implied line,
  no TERMINAL-GROWTH DEFAULT line in DATA 1.5, and the long_run line without the reference's margin rule (om_5, m_long, margin_ratio); the
  DEFAULTS text no longer says "the reference"; the consensus years 1-2 and next-FY revenue growth read as evidence;
- the POPULATION RANGES section follows DEFAULTS, with P50 only on its flag; the two iii arms differ only by P50;
- the rev22 arm is the revision-22 pack byte for byte on the three saved packs (and its TASK is revision 22's, git 412578d);
- the reference cannot be re-derived from the rebuilt text: no printed long-run default, and a desk call made of the printed defaults alone is
  refused until the analyst names its own long-run inputs;
- the facts, the parity, the desk context and the tools' text follow the arm.
"""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE.parent.parent), str(HERE.parent.parent.parent), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import analyst_tools as at  # noqa: E402
import capability_test as cap  # noqa: E402
import consensus_reference  # noqa: E402
import consensus_valuation as cv  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
import population_ranges as pr  # noqa: E402
import rs2_data  # noqa: E402
from test_rev24_stage_a_pack import REAL, _FENCE_RE, _WIN_RE, _num, _saved, rebuild_rev24  # noqa: E402
from test_rev24_s2b_ranges import fixture_tables  # noqa: E402

S2B = HERE / "fixture_data" / "rev24_s2b"
LONG_RUN_DEFAULT_LINES = ("- terminal_g_default: ", "- terminal_ronic: ", "- price_implied: ")
RULE_MEMBERS = ("om_5=", "m_long=", "margin_ratio=")


def rebuild_rev22(excerpt, saved_facts):
    """The saved excerpt as the rev22 arm prints it from its facts: the revision-22 marker, the reference's line kept, the BASE WINDOW CHECK
    re-rendered by the production window_line with the reference shown, and the DEFAULTS block rendered with nothing withheld."""
    facts = copy.deepcopy(saved_facts)
    out = []
    for line in excerpt.split("\n"):
        if line.startswith("# DATA PACK"):
            out.append(re.sub(r"\(pack revision \d+\)", "(pack revision 22)", line))
        elif line.startswith("- [Arithmetic] BASE WINDOW CHECK"):
            m = _WIN_RE.search(line)
            win = {"gap": int(m.group(1)) / 100.0, "quarters": int(m.group(4)), "expected_ttm": _num(m.group(5)) * 1e9, "flag": True,
                   "ttm_value": None, "ttm_levels": None}
            f = _FENCE_RE.search(line)
            if f:
                win.update(fence_side=f.group(1), fence=(_num(f.group(2)), _num(f.group(3))))
            out.append(consensus_reference.window_line(win, {"value": facts["consensus_implied_value"]}, _num(m.group(3)) * 1e9, m.group(2),
                                                       cap._bn, base_year_check="the BASE-YEAR CHECK shows" in line, reference_shown=True))
        elif line.startswith("## DEFAULTS"):
            out.append(pack_facts.render_defaults_block(facts))
            break
        else:
            out.append(line)
    return "\n".join(out) + "\n"


# ---- the rev22 arm: the control, byte for byte ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("t", REAL)
def test_the_rev22_arm_is_the_revision_22_pack_byte_for_byte_on_the_three_saved_packs(t):
    saved, excerpt = _saved(t)
    got = rebuild_rev22(excerpt, saved)
    # AMD's saved pack is revision 21: revision 22 changed no line of this excerpt, only the marker
    want = re.sub(r"\(pack revision 2[12]\)", "(pack revision 22)", excerpt, count=1)
    if t == "KSS":
        # revision 24 step 2d (cross-check 19, ruling 1): KSS's r_tc 5.63% is above 0 and below the cost of equity, so the desk now starts the fade at
        # it, and the DEFAULTS long_run clause says so - the one line of the control that changes with the correction (AMD's r_tc is above the cost
        # of equity, HRTG's unlimited: unchanged)
        old = ("starts at the cost of equity, coe_anchor (r_tc, your record's 8-year median return on tangible invested capital, is not above it "
               "or is not available), then fades to")
        assert want.count(old) == 1
        want = want.replace(old, "fades from r_tc (your record's 8-year median return on tangible invested capital) to")
    assert got == want
    assert "- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $" in got and "- consensus_implied_value: " in got
    for prefix in LONG_RUN_DEFAULT_LINES:
        assert prefix in got
    assert "## POPULATION RANGES" not in got


def test_the_rev22_arms_task_is_revision_22s_byte_for_byte():
    rev22 = (S2B / "task_rev22.txt").read_text(encoding="utf-8").replace("\r\n", "\n")     # git show 412578d's TASK
    assert cap.TASK_REV22 == rev22
    assert cap.task_for({"pilot_arm": "rev22"}) is cap.TASK_REV22
    for arm in (None, "iii_p50", "iii_no_p50"):
        assert cap.task_for({"pilot_arm": arm}) is cap.TASK
    assert "CONSENSUS-IMPLIED" not in cap.TASK


# ---- the iii arms: no long-run default ----------------------------------------------------------------------------------------------------

def _defaults(text):
    i = text.index("## DEFAULTS")
    j = text.find("\n\n## ", i)
    return text[i:] if j == -1 else text[i:j]


@pytest.mark.parametrize("t", REAL)
def test_the_revision_24_defaults_print_no_long_run_default_and_never_say_the_reference(t):
    saved, excerpt = _saved(t)
    text, facts = rebuild_rev24(excerpt, saved)
    block = _defaults(text)
    for prefix in LONG_RUN_DEFAULT_LINES:
        assert prefix not in block, (t, prefix)
    lr_line = next(l for l in block.split("\n") if l.startswith("- long_run: "))
    for m in RULE_MEMBERS:
        assert m not in lr_line, (t, m)
    assert "m_tc=" in lr_line and "om_trend=" in lr_line and "r_tc=" in lr_line and "m5=" in lr_line       # the record stays
    assert "you choose long_run_margin, fade_years, terminal_g and terminal_ronic (POPULATION RANGES)" in lr_line
    assert "moves all the way to om_trend" not in block
    # "the reference" is never said; reference_base_b is a key name
    assert re.findall(r"\breference\b(?!_base_b)", block.replace("reference_base_b", "")) == [], t
    lv = next(l for l in block.split("\n") if l.startswith("- levels: "))
    assert "| what analysts forecast: the consensus cash-flow levels of years 1 and 2" in lv and "not levels the desk holds" in lv
    assert "evidence, not a cap: the desk holds no year at it" in next(l for l in block.split("\n") if l.startswith("- next_fy_revenue_growth: "))
    # the facts keep every value, the parity check leaves the withheld ones out
    assert facts["terminal_g_default"] == saved["terminal_g_default"] and facts["terminal_ronic"] == saved["terminal_ronic"]
    assert pack_facts.parity(facts, pack_facts.from_text(text)) == []


@pytest.mark.parametrize("t", REAL)
def test_the_reference_cannot_be_rederived_from_the_rebuilt_text(t):
    """Additions from step 2a: the DEFAULTS long_run line printed the reference's long-run margin, ratio and OM_5 (HRTG within 0.01%, KSS exact).
    The rebuilt revision-24 text prints none of the reference's long-run inputs (in any print form) and no CONSENSUS-IMPLIED VALUE; read back, it
    gives no long-run default; and a desk call made of every printed default alone is refused, naming the long-run inputs the analyst must choose
    itself, so no desk run lands anywhere unless the analyst's own long-run inputs put it there."""
    saved, excerpt = _saved(t)
    text, facts = rebuild_rev24(excerpt, saved)
    civ = saved["consensus_implied_value"]
    lr = saved["long_run"]
    # the CIV in any print form, and the reference's margin rule; the terminal_g and terminal_ronic defaults are not printed as defaults (no line,
    # and the reader gives None, below), though their value can equal a printed fact: the macro growth anchor (a revenue trend above the anchor
    # is held at it: AMD, HRTG) or the record's r_tc (p = 1: AMD)
    forms = [f"{civ:,.2f}", f"{civ:.2f}", "terminal_g_default", "- terminal_ronic: "]
    for k in ("m_long", "om_5"):
        if isinstance(lr.get(k), float):
            forms.append(f"{k}={lr[k] * 100:.4f}%")
    if isinstance(lr.get("margin_ratio"), float):
        forms.append(f"{lr['margin_ratio']:.6f}")
    for s in forms:
        assert s not in _defaults(text), (t, s)
    assert "CONSENSUS-IMPLIED" not in text
    read = pack_facts.from_text(text)
    assert read["long_run_defaults_withheld"] is True
    assert all(read[k] is None for k in ("terminal_g_default", "terminal_ronic", "price_implied_defaults", "consensus_implied_value"))
    assert all(read["long_run"].get(m) is None for m in ("m_long", "margin_ratio", "om_5"))
    # a call of the printed defaults alone: base, rate, shares, years 1-2 at the printed levels, no long-run input
    ctx = cv.build_desk_context(read, saved["price_implied_price"], t, t, "2026-10-05")
    assert ctx["long_run_defaults_withheld"] is True and ctx["terminal_g_default"] is None and ctx["terminal_ronic"] is None
    lv, base = read["levels"], read["owner_earnings_default_b"]
    g = [lv["year1"] / base - 1.0, lv["year2"] / lv["year1"] - 1.0]
    call = {"cash_flow_life": "perpetual", "cash_flow_life_reason": "x", "sbc_treatment": "deducted_in_cf",
            "scenarios": [{"name": n, "prob": p, "base_cf": base, "explicit_growth": g, "wacc": read["coe_anchor"]}
                          for n, p in (("Base", 0.5), ("Bull", 0.25), ("Bear", 0.25))]}
    res = fmt.execute_financial_model(call, ctx)
    assert res["validation_error"] is True
    named = " ".join(res["missing"])
    for inp in ("long_run_margin", "terminal_ronic"):
        assert named.count(inp + " (") == 1, (t, inp, named)
    # with those two named but no terminal_g or fade: still refused (no silent default since Phase 4)
    res = fmt.execute_financial_model(dict(copy.deepcopy(call), long_run_margin=0.1, terminal_ronic=0.1), ctx)
    assert res["validation_error"] is True and "terminal_g" in res["error"] and "fade_years" in res["error"]


# ---- a built pack: both iii arms and the rev22 arm ----------------------------------------------------------------------------------------

@pytest.fixture
def built(screener_data_stub, monkeypatch, tmp_path):
    """build_pack("GEV") on the committed slice, with the population tables and the SIC file served from fixtures (no machine data)."""
    from test_pack_rev15 import _stub_and_freeze
    _stub_and_freeze(monkeypatch)
    import paths
    tdir, idir = tmp_path / "priors", tmp_path / "inputs"
    (tdir / "2025").mkdir(parents=True)
    (tdir / "2025" / "tables.json").write_text(json.dumps(fixture_tables()), encoding="utf-8")
    idir.mkdir()
    (idir / "sic_by_cik.json").write_text(json.dumps({"map": {"0001996810": {"sic": "3510", "industry": "Machinery"}}}), encoding="utf-8")
    real = paths.resolve
    monkeypatch.setattr(paths, "resolve", lambda key, *a, **k: tdir if key == "priors_dir" else idir if key == "priors_inputs_dir" else real(key, *a, **k))
    pr._TABLES.clear()
    monkeypatch.delitem(rs2_data.CONFIG, "pilot_arm", raising=False)
    monkeypatch.delitem(rs2_data.CONFIG, "ranges_show_p50", raising=False)
    # the frozen clock is 2026-09-27: vintage 2025
    return lambda **kw: cap.build_pack("GEV", include_research=False, **kw)


def test_the_built_iii_arms_differ_only_by_p50_and_print_the_ranges_after_defaults(built):
    p50, no = built(pilot_arm="iii_p50"), built(pilot_arm="iii_no_p50")
    a, b = str(p50), str(no)
    assert a.split("\n", 1)[0] == "# DATA PACK - GEV   (pack revision 24)"
    assert re.sub(r", P50 [^,|]+(?=, )| P50 [+-][\d.]+%", "", a) == b
    sec = a[a.index("## POPULATION RANGES"):]
    assert a.index("## DEFAULTS") < a.index("## POPULATION RANGES") and sec.count("\n## ") == 0
    assert "how companies like this one actually evolved; context for your choice, not a target." in sec and "vintage 2025" in sec
    assert " P50 " in sec and " P50 " not in b[b.index("## POPULATION RANGES"):]
    assert p50.facts["population_ranges"]["vintage"] == 2025 and p50.facts["population_ranges"]["family"] == "operating"
    assert p50.facts["ranges_show_p50"] is True and no.facts["ranges_show_p50"] is False and p50.facts["pilot_arm"] == "iii_p50"
    assert "TERMINAL-GROWTH DEFAULT" not in a
    for prefix in LONG_RUN_DEFAULT_LINES:
        assert prefix not in _defaults(a)
    assert "not used in the reference" not in a and "not used in the COE ANCHOR" in a
    for pk in (p50, no):
        assert pk.facts["long_run_defaults_withheld"] is True and pk.facts["reference_withheld"] is True
        assert pack_facts.parity(pk.facts, pack_facts.from_text(str(pk))) == []
        assert cv.build_desk_context(pk.facts, 100.0, "GEV", "GEV")["long_run_defaults_withheld"] is True
    # the default build (no arm) is the revision-24 pack with P50 off
    assert str(built()) == b and built().facts["pilot_arm"] is None


def test_the_built_rev22_arm_prints_the_revision_22_defaults_and_no_ranges(built):
    pk = built(pilot_arm="rev22")
    text = str(pk)
    assert text.split("\n", 1)[0] == "# DATA PACK - GEV   (pack revision 22)"
    assert "## POPULATION RANGES" not in text and "- terminal_g_default: " in text and "- price_implied: " in text
    assert "- consensus_implied_value: " in text and "not used in the reference" in text
    assert pk.facts["pilot_arm"] == "rev22" and pk.facts["long_run_defaults_withheld"] is None and pk.facts["reference_withheld"] is None
    assert pack_facts.parity(pk.facts, pack_facts.from_text(text)) == []
    assert cv.build_desk_context(pk.facts, 100.0, "GEV", "GEV")["long_run_defaults_withheld"] is None
    # the ranges are still computed, for the record (the rev22 arm prints none and the gate does not run on it)
    assert pk.facts["population_ranges"]["vintage"] == 2025


def test_the_built_pack_keeps_the_base_years_margin_and_revenue_for_the_desk(built):
    pk = built(pilot_arm="iii_no_p50")
    lr = pk.facts["long_run"]
    hist = json.loads((HERE / "fixture_data" / "fundamentals_history.json").read_text(encoding="utf-8"))["tickers"]["GEV"]
    base = max(int(y) for y in hist if str(y).isdigit())
    assert lr["rev_L"] == pytest.approx(hist[str(base)]["revenue"] / 1e9, rel=1e-6)
    assert "x_L" in lr and "rev_L=" not in str(pk) and "x_L=" not in str(pk)          # never printed


def test_a_table_that_cannot_be_read_is_stated_never_a_crash(built, monkeypatch):
    import paths
    real = paths.resolve

    def resolve(key, *a, **k):
        if key in ("priors_dir", "priors_inputs_dir"):
            raise FileNotFoundError(f"cannot locate {key!r}")
        return real(key, *a, **k)
    monkeypatch.setattr(paths, "resolve", resolve)
    pk = built(pilot_arm="iii_no_p50")
    assert pk.facts["population_ranges"]["inputs"] == {} and "could not be read" in pk.facts["population_ranges"]["unavailable"]
    assert "## POPULATION RANGES" in str(pk) and "- not available: the population tables could not be read" in str(pk)


# ---- the flags ------------------------------------------------------------------------------------------------------------------------------

def test_the_pack_flags_come_from_the_call_or_the_config_and_a_contradiction_is_refused(monkeypatch):
    monkeypatch.delitem(rs2_data.CONFIG, "pilot_arm", raising=False)
    monkeypatch.delitem(rs2_data.CONFIG, "ranges_show_p50", raising=False)
    assert cap.pack_flags() == (None, False)
    assert cap.pack_flags(ranges_show_p50=True) == (None, True)
    assert cap.pack_flags("iii_p50") == ("iii_p50", True) and cap.pack_flags("iii_no_p50") == ("iii_no_p50", False)
    assert cap.pack_flags("rev22") == ("rev22", None)
    monkeypatch.setitem(rs2_data.CONFIG, "pilot_arm", "iii_p50")
    assert cap.pack_flags() == ("iii_p50", True)
    monkeypatch.setitem(rs2_data.CONFIG, "ranges_show_p50", "yes")         # only a literal true shows P50
    with pytest.raises(ValueError):
        cap.pack_flags()
    with pytest.raises(ValueError):
        cap.pack_flags("iii_no_p50", ranges_show_p50=True)
    with pytest.raises(ValueError):
        cap.pack_flags("iii")


def test_the_repository_config_sets_no_arm():
    cfg = json.loads((HERE.parent.parent.parent / "config.json").read_text(encoding="utf-8-sig"))
    assert "pilot_arm" not in cfg and "ranges_show_p50" not in cfg


# ---- the tools' text -----------------------------------------------------------------------------------------------------------------------

def test_the_desk_text_follows_the_arm():
    assert at.tools_for(None) is at.TOOLS and at.tools_for({"long_run_defaults_withheld": None}) is at.TOOLS
    iii = next(t for t in at.tools_for({"long_run_defaults_withheld": True}) if t["function"]["name"] == "run_financial_model")["function"]
    old = next(t for t in at.TOOLS if t["function"]["name"] == "run_financial_model")["function"]
    assert "holds Base years 3-5" in old["description"] and "holds Base years 3-5" not in iii["description"]
    assert "have no default, and the desk holds and caps no year" in iii["description"]
    assert iii["parameters"]["properties"]["terminal_ronic"]["description"].startswith("Required for a perpetual cash_flow_life, with no default")
    assert "DEFAULTS terminal_ronic" not in json.dumps(iii)
    assert "held at it" not in iii["parameters"]["properties"]["explicit_growth"]["description"]
    # every other tool and property is unchanged
    assert [t["function"]["name"] for t in at.tools_for({"long_run_defaults_withheld": True})] == [t["function"]["name"] for t in at.TOOLS]
    assert iii["parameters"]["properties"]["long_run_margin"] == old["parameters"]["properties"]["long_run_margin"]
