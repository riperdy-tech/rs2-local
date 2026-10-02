"""Revision 19, Part D: the text the model sees (brief_rev19.md D1-D4) and its facts.

  D1 the reference line's anchor sentence, verbatim, the label unchanged;
  D2 the TASK (the Level-anchor bullet deleted, item 5 shorter, item 6 the price_implied and crux paragraph, the closing paragraph);
  D3 the DEFAULTS `price_implied` line (verbatim explanation, the "not available -" cases), and the one production construction of the DEFAULTS run;
  D4 FACTS_VERSION 7: the new keys, the parity of the printed ones, `rs2_data.anchor_nominal_gdp_trend`.
Fixtures are synthetic (the W9 fixture of test_rev17f_redesign and the synthetic twelve-year pack of test_throughcycle_reference).
"""
import json
import math
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
import pi_text  # noqa: E402
import rs2_data  # noqa: E402
from test_rev18_part1 import B, _pack_with_bill_rate  # noqa: E402
from test_rev17f_redesign import _w9_reference  # noqa: E402

D1 = ("— context, never the reason for a call: the same generic rules for every company; it values the average stock close to its price but "
      "carries little information about any one stock (on 2019–2023 point-in-time data, a stock it valued at twice its price went on to earn "
      "only about 3% more over three years than one it valued at its price).")

ITEM6 = ("6. The desk also returns price_implied: for each judgment input (coe, growth_years_3_5, fade_years, terminal_g, terminal_ronic, year2_level), "
         "the value at which your Base would equal today's price with your other inputs unchanged, or \"not reachable\" when no value inside the input's "
         "bound does it. DEFAULTS prints the same at the default inputs. A verdict of undervalued or overvalued needs a stated disagreement with the price: "
         "in your answer run, pass crux, naming one to three of those inputs where your evidence says the price is wrong, each with your reason and at "
         "least one citation {source, date, quote} of this company's own evidence: DATA 3, DATA 4, DATA 5, DATA 6, GUIDANCE (the company's own release), "
         "or a page you fetched in this session that names the company, with the quote copied exactly. Code fills in your value and the price-implied "
         "value from that run. DEFAULTS, the base rates, the macro anchors, the CONSENSUS-IMPLIED VALUE, the sector bands, the consensus rows, the news "
         "list and the research briefs are context and never support a crux. Without a valid crux your verdict is HOLD, wherever your Base sits. "
         "Disagreeing with the analysts' targets is allowed when your evidence supports it. In SECTION 3, state each crux (the input, your number, the "
         "number the price implies, and the dated evidence) and argue the size of the disagreement, not only its sign. Also report the neutral reverse "
         "DCF's implied 10-year growth and the base-rate band it falls in. SECTION 0 and SECTION 12 state the verdict this item gives; where the system "
         "text says otherwise, this TASK takes precedence.")

PI_EXPLANATION = ("at the DEFAULTS, the value of each judgment input at which the Base equals today's price, the other inputs held; the desk returns "
                  "the same for your own inputs on every run; a verdict of undervalued or overvalued needs a crux on one of them (TASK item 6)")
CASH_EXPLANATION = ("the base fiscal year's cash and short-term investments as filed; the desk refuses an excess_cash above it (cash after the valuation "
                    "date is already in the cash flows)")


# ---- D1 -----------------------------------------------------------------------------------------------------------------------------------

def test_the_anchor_sentence_is_the_brief_verbatim_and_the_label_stays():
    assert cr.ANCHOR_ROLE == D1
    ref = _w9_reference()
    line = cr.pack_line(ref, 0.09394, 0.09, 0.0375, lambda v: f"{v / B:.3f}", anchor=0.0375)
    assert "[Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $" in line
    assert f"per share, the analysts' own earnings path at our discount rate {D1} | " in line
    # the parsers' regex still reads the value, and the retired sentence is gone
    assert pack_facts._CIV_RE.search(line).group(1).replace(",", "") == f"{ref['value']:.2f}"
    assert "a calibrated level anchor" not in line and "not a buy signal" not in line and "beat the S&P" not in line
    only = cr.pack_line(dict(ref, method="cash_only", cash=3.0 * B, interest_removed=1.0 * B), 0.09394, 0.09, 0.0375, lambda v: f"{v / B:.3f}", anchor=0.0375)
    assert D1 in only


# ---- D2 -----------------------------------------------------------------------------------------------------------------------------------

def test_the_task_changes_are_exactly_the_briefs():
    t = cap.TASK
    assert "Level anchor" not in t and "level of your Base" not in t and "earns no credit" not in t                      # (a) the bullet is gone
    assert ("Changing an input because you dislike the resulting value is forbidden; the harness records every run.\n6. ") in t   # (b)
    assert "moving any input toward today's price" not in t
    assert ITEM6 in t and "\n" + ITEM6 + "\n7. Timing:" in t                                                                      # (c)
    assert "The desk also returns the reverse DCF" not in t
    assert "valuation inputs, reasons or crux: code takes them from your last complete desk run of Bear, Base and Bull." in t   # (d)
    assert "verdict label, valuation inputs or reasons" not in t
    # the neighbours are untouched
    assert "   - Valuation date: " in t and "\n   - Frame: every flow in this pack" in t
    assert t.count("\n5. Run Bear, Base and Bull together in one call.") == 1


def test_item_6_names_the_same_six_inputs_as_the_crux_schema_and_the_validity_owner():
    names = re.search(r"judgment input \(([^)]*)\)", cap.TASK).group(1).split(", ")
    import crux_check
    assert tuple(names) == crux_check.J == fmt.PI_INPUTS == pi_text.INPUTS


# ---- D3: the DEFAULTS lines -----------------------------------------------------------------------------------------------------------

def _line(text, key):
    return next(l for l in text.splitlines() if l.startswith(f"- {key}: "))


def test_the_price_implied_line_and_the_cash_line_carry_the_briefs_text():
    text = pack_facts.render_defaults_block(pack_facts.empty())
    assert _line(text, "price_implied") == f"- price_implied: not available | {PI_EXPLANATION}"
    assert _line(text, "base_year_cash_and_investments_b") == f"- base_year_cash_and_investments_b: not available | {CASH_EXPLANATION}"
    assert _line(text, "excess_cash").endswith("a different amount needs excess_cash_reason; the desk refuses an amount above base_year_cash_and_investments_b")
    # where the DEFAULTS has no run, the value says why
    facts = dict(pack_facts.empty(), price_implied_defaults={"not_available": "the reference is cash-only: there is no operating business to value"})
    line = _line(pack_facts.render_defaults_block(facts), "price_implied")
    assert line == f"- price_implied: not available — the reference is cash-only: there is no operating business to value | {PI_EXPLANATION}"
    assert pack_facts.from_text("# DATA PACK - X   (pack revision 19)\n\n" + pack_facts.render_defaults_block(facts))["price_implied_defaults"] == facts["price_implied_defaults"]


def test_the_line_value_round_trips_for_every_shape_of_an_entry():
    nb = lambda lo, hi: {"low": lo, "high": hi}
    block = {"coe": {"value": pi_text.quantize("coe", 0.098), "reachable": True, "bound": nb(None, None), "not_available": None},
             "growth_years_3_5": {"value": pi_text.quantize("growth_years_3_5", -0.137), "reachable": True, "bound": nb(None, None), "not_available": None},
             "fade_years": {"value": None, "reachable": False, "bound": nb(0.0, 60.0), "not_available": None},
             "terminal_g": {"value": None, "reachable": False, "bound": nb(0.0, pi_text.quantize("terminal_g", 0.0446)), "not_available": None},
             "terminal_ronic": {"value": pi_text.quantize("terminal_ronic", 0.33), "reachable": True, "bound": nb(None, None), "not_available": None},
             "year2_level": {"value": None, "reachable": False, "bound": nb(None, None), "not_available": "the pack prints no bull2 and bear2 range"}}
    text = pi_text.render_line_value(block)
    assert text == ("coe=9.80%; growth_years_3_5=-13.7% a year; fade_years=not reachable (0 years to 60 years); terminal_g=not reachable "
                    "(0.00% to 4.46%); terminal_ronic=33.0%; year2_level=not available (the pack prints no bull2 and bear2 range)")
    assert pi_text.parse_line_value(text) == block
    # +inf is its own word, both as a value and as the end of a bound
    inf = dict(block, terminal_ronic={"value": None, "reachable": False, "bound": nb(0.09, math.inf), "not_available": None})
    assert pi_text.render_line_value(inf).count("terminal_ronic=not reachable (9.0% to unlimited)") == 1
    assert pi_text.parse_line_value(pi_text.render_line_value(inf)) == inf
    for bad in ("coe=9.80%", "coe=9.80%; growth_years_3_5=x", "nope=1", "coe 9.80%"):
        with pytest.raises(ValueError):
            pi_text.parse_line_value(bad)
    assert pi_text.render_line_value(None) == "not available" and pi_text.parse_line_value("not available") is None


def test_quantizing_a_block_gives_what_its_text_reads_back_as():
    ref = _w9_reference()
    args, why = cr.defaults_desk_args(ref, _w9_facts(ref))
    assert why is None
    block = pi_text.quantize_block(fmt.defaults_price_implied(args, ref["value"] * 1.2, rf_eff=0.04, gdp_trend=0.0446, levels={"bear2": 0.1, "bull2": 0.2}))
    assert set(block) == set(pi_text.INPUTS)
    assert pi_text.parse_line_value(pi_text.render_line_value(block)) == block
    assert pi_text.quantize_block({"error": "identity"}) == {"not_available": "the price-implied solver failed its identity check"}
    assert pi_text.quantize_block(None) is None


# ---- D3: the production construction of the DEFAULTS run --------------------------------------------------------------------------------

def _w9_facts(ref, **over):
    lr = ref["long_run"]
    f = dict(pack_facts.empty(), coe_anchor=0.09, terminal_g_default=0.0375, shares_default=50e6, terminal_ronic=ref["terminal_ronic"],
             long_run={"e5": lr["e5"] / B, "oe5": lr["oe5"] / B, "m5": lr["m5"], "margin_ratio": ref["margin_ratio"], "r_tc": 0.15, "stub_months": 8.5},
             working_capital=[x / B for x in ref["wc"]], excess_cash=None)
    f.update(over)
    return f


def test_the_defaults_run_equals_the_reference_to_the_cent_and_desk_parity_s_construction():
    ref = _w9_reference()
    args, why = cr.defaults_desk_args(ref, _w9_facts(ref))
    assert why is None and args["fade_years"] == cr.FADE_YEARS == 5 and args["sbc_treatment"] == "deducted_in_cf"
    assert args["base_cf"] == ref["base_cf"] / B and args["explicit_growth"] == list(ref["path"])
    assert args["wacc"] == 0.09 and args["terminal_g"] == 0.0375 and args["shares_diluted"] == 0.05
    res = fmt.unbundled_dcf(**args)
    assert abs(res["per_share_iv_raw"] - ref["value"]) < 0.005                                      # the desk equals the reference (AT1a's bar)
    # the same value through the desk with the facts' context, as desk_parity does it
    from test_rev18_part1 import _desk_call, _desk_ctx
    out = fmt.execute_financial_model(_desk_call(ref), _desk_ctx(ref, price=1e6))
    assert abs(out["scenario_dcfs"][0]["dcf"]["per_share_iv"] - res["per_share_iv"]) <= 0.0051


def test_a_levels_name_starts_from_the_year_1_level_with_year_1_growth_zero():
    ref = dict(_w9_reference(), base_cf=None, method="levels", flows=(100e6, 112e6))
    ref["levels"] = (100e6, 112e6)
    args, why = cr.defaults_desk_args(ref, _w9_facts(ref))
    assert why is None and args["base_cf"] == 0.1
    assert args["explicit_growth"][0] == 0.0 and args["explicit_growth"][1] == pytest.approx(0.12) and args["explicit_growth"][2:] == list(ref["path"][2:])


@pytest.mark.parametrize("what,why_part", [("not_available", "no consensus reference"), ("cash_only", "cash-only"), ("non_positive", "not positive"),
                                           ("missing_input", "does not print every default input")])
def test_no_defaults_run_and_the_reason(what, why_part):
    ref = _w9_reference()
    facts = _w9_facts(ref)
    if what == "not_available":
        ref = dict(ref, value=None)
    elif what == "cash_only":
        ref = dict(ref, method="cash_only")
    elif what == "non_positive":
        ref = dict(ref, base_cf=-1.0)
    else:
        facts = dict(facts, coe_anchor=None)
    args, why = cr.defaults_desk_args(ref, facts)
    assert args is None and why_part in why


def test_the_rest_of_the_facts_pass_through_without_an_or_default():
    ref = _w9_reference()
    f = _w9_facts(ref, excess_cash=0.0, terminal_ronic=math.inf, working_capital=None)
    args, _ = cr.defaults_desk_args(ref, f)
    assert args["excess_cash"] == 0.0 and args["terminal_ronic"] == math.inf and args["working_capital"] is None


# ---- D3, D4 in a built pack ---------------------------------------------------------------------------------------------------------------

def test_a_built_pack_prints_the_defaults_price_implied_and_its_facts_equal_the_text(screener_data_stub, monkeypatch):
    pack = _pack_with_bill_rate(monkeypatch, 0.04)
    f = pack.facts
    assert f["version"] == 8 == pack_facts.FACTS_VERSION
    block = f["price_implied_defaults"]
    assert set(block) == set(pi_text.INPUTS) and f["price_implied_price"] > 0 and len(f["reference_path"]) == 5
    assert f["rf_eff"] is not None and f["nominal_gdp_trend"] == rs2_data.anchor_nominal_gdp_trend()[0]
    text = str(pack)
    parsed = pack_facts.from_text(text)
    assert parsed["price_implied_defaults"] == block and pack_facts.parity(f, parsed) == []
    assert _line(text, "price_implied").startswith("- price_implied: coe=") and _line(text, "price_implied").endswith(f"| {PI_EXPLANATION}")
    # the sidecar-only keys are not in the text: a text read gives None, a sidecar read gives the values
    for k in pack_facts.SIDECAR_ONLY:
        assert parsed[k] is None, k


def test_the_defaults_run_in_a_built_pack_reproduces_the_price_or_is_not_reachable_with_its_bound(screener_data_stub, monkeypatch):
    calls = []
    real = cr.build
    monkeypatch.setattr(cr, "build", lambda *a, **k: (calls.append(real(*a, **k)), calls[-1])[1])
    pack = _pack_with_bill_rate(monkeypatch, 0.04)
    f, ref = pack.facts, calls[-1]
    args, why = cr.defaults_desk_args(ref, f)
    assert why is None
    price = f["price_implied_price"]
    pi = fmt.defaults_price_implied(args, price, rf_eff=f["rf_eff"], gdp_trend=f["nominal_gdp_trend"], levels=f["levels"])
    assert "error" not in pi
    n_reached = 0
    for name, blk in pi.items():
        if blk["reachable"]:
            n_reached += 1
            if name != "fade_years":
                assert abs(blk["base_at_value"] - price) <= 0.01, name
        else:
            assert blk["bound"]["low"] is not None or blk.get("not_available"), name
    assert n_reached >= 1
    # and what the pack printed is that block at its printed precision
    assert f["price_implied_defaults"] == pi_text.quantize_block(pi)


def test_no_reference_means_no_defaults_run_and_the_line_says_why(screener_data_stub, monkeypatch):
    # a synthetic pack with no estimates: the reference is not available
    from test_throughcycle_reference import _synthetic_pack
    nope = _synthetic_pack(monkeypatch, enrich_override={"_ticker": "GEV", "_fetched_at": "2026-09-26T12:00:00", "estimates": None})
    assert nope.facts["reference_status"] == "not_available"
    assert nope.facts["price_implied_defaults"] == {"not_available": "the pack has no consensus reference (reference_status not_available)"}
    assert _line(str(nope), "price_implied") == ("- price_implied: not available — the pack has no consensus reference (reference_status not_available)"
                                                  f" | {PI_EXPLANATION}")
    assert nope.facts["reference_path"] is None and nope.facts["price_implied_price"] is None
    assert pack_facts.parity(nope.facts, pack_facts.from_text(str(nope))) == []


# ---- D4: the facts and the accessor ---------------------------------------------------------------------------------------------------

def test_the_new_keys_are_in_the_empty_object_and_an_older_sidecar_reads_them_as_none(tmp_path):
    e = pack_facts.empty()
    for k in ("rf_eff", "nominal_gdp_trend", "reference_path", "price_implied_defaults", "price_implied_price", "base_year_cash_and_investments_b"):
        assert k in pack_facts.KEYS and e[k] is None
    old = {k: v for k, v in e.items() if k not in ("rf_eff", "nominal_gdp_trend", "reference_path", "price_implied_defaults", "price_implied_price")}
    old["version"] = 6
    (tmp_path / pack_facts.SIDECAR).write_text(json.dumps(old), encoding="utf-8")
    read = pack_facts.read_sidecar(tmp_path)
    assert all(read[k] is None for k in ("rf_eff", "nominal_gdp_trend", "reference_path", "price_implied_defaults", "price_implied_price"))
    # an older DEFAULTS block (no price_implied line) reads as None
    block = pack_facts.render_defaults_block(pack_facts.empty())
    older = "\n".join(l for l in block.splitlines() if not l.startswith("- price_implied:"))
    assert pack_facts.from_text("# DATA PACK - X   (pack revision 18)\n\n" + older)["price_implied_defaults"] is None


def _anchors(monkeypatch, tmp_path, payload=None, age_days=1):
    """Point rs2_data at a folder holding long_run_growth_anchor.json with `payload` (dated `age_days` ago)."""
    from datetime import date, timedelta
    d = tmp_path / "anchors"
    d.mkdir(exist_ok=True)
    if payload is not None:
        doc = dict({"anchor_id": "long_run_growth", "asof": (date.today() - timedelta(days=age_days)).isoformat(), "degraded": False,
                    "nominal_gdp_trend": 0.0446, "terminal_g_suggestion": 0.0375}, **payload)
        (d / "long_run_growth_anchor.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(rs2_data, "load_anchors", lambda: {"long_run_growth": json.loads((d / "long_run_growth_anchor.json").read_text(encoding="utf-8"))}
                        if (d / "long_run_growth_anchor.json").exists() else {})


def test_the_nominal_gdp_trend_accessor_follows_the_freshness_and_degraded_rules_with_no_fallback(monkeypatch, tmp_path):
    _anchors(monkeypatch, tmp_path, {})
    v, src = rs2_data.anchor_nominal_gdp_trend()
    assert v == 0.0446 and src.startswith("anchor_long_run_growth(")
    # a value that is not the terminal_g suggestion
    assert rs2_data.anchor_terminal_g()[0] == 0.0375
    _anchors(monkeypatch, tmp_path, {"degraded": True})
    assert rs2_data.anchor_nominal_gdp_trend() == (None, f"long_run_growth_anchor_degraded({json.loads((tmp_path / 'anchors' / 'long_run_growth_anchor.json').read_text())['asof']})")
    _anchors(monkeypatch, tmp_path, {"nominal_gdp_trend": None})
    assert rs2_data.anchor_nominal_gdp_trend() == (None, "long_run_growth_anchor_has_no_nominal_gdp_trend")
    _anchors(monkeypatch, tmp_path, {"nominal_gdp_trend": True})
    assert rs2_data.anchor_nominal_gdp_trend()[0] is None                                           # a bool is not a number
    _anchors(monkeypatch, tmp_path, {}, age_days=400)
    assert rs2_data.anchor_nominal_gdp_trend() == (None, "no_usable_long_run_growth_anchor")      # stale
    (tmp_path / "anchors" / "long_run_growth_anchor.json").unlink()
    assert rs2_data.anchor_nominal_gdp_trend() == (None, "no_usable_long_run_growth_anchor")      # absent
    # a zero is a value, not an absence
    _anchors(monkeypatch, tmp_path, {"nominal_gdp_trend": 0.0})
    assert rs2_data.anchor_nominal_gdp_trend()[0] == 0.0


def test_without_the_trend_the_terminal_g_bound_is_not_available(monkeypatch):
    from test_rev19_solver import _b, _pi
    pi = _pi(_b(), 20.0, gdp_trend=None)
    assert pi["terminal_g"]["not_available"] == "nominal_gdp_trend is not available" and pi["terminal_g"]["reachable"] is False


def test_the_desk_context_carries_the_two_anchors_from_the_facts():
    src = Path(HERE / "audit_202608" / "consensus_valuation.py").read_text(encoding="utf-8")
    assert '"rf_eff": facts.get("rf_eff")' in src and '"nominal_gdp_trend": facts.get("nominal_gdp_trend")' in src
