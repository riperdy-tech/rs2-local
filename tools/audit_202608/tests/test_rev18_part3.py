"""Revision 18, part 3 (brief section 3, the carried items and bar AT1e): the text the model sees, the schema and contract for
excess_cash / excess_cash_reason, and the reverse DCF that handles the cash term."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyst_tools as at  # noqa: E402
import capability_test as cap  # noqa: E402
import consensus_reference as cr  # noqa: E402
import contract_fill  # noqa: E402
import financial_model_tool as fmt  # noqa: E402
import pack_facts  # noqa: E402
from test_rev18_part1 import _build, _cash, _margin_record, X_BASE, OE_BASE, B  # noqa: E402
from test_throughcycle_reference import COE, GA, REDUCTION, REV_BASE, _synthetic_pack  # noqa: E402

ROLE = ("— a calibrated level anchor, not a buy signal: on point-in-time data (valuation dates 2017–2023, returns to 2026) this "
        "method valued stocks that went on to earn an average return within ±15% of their price, but it ranked stocks only weakly, "
        "and its 'worth 30% more than the price' calls beat the S&P only about 2 points more often than an average stock in "
        "2019–2023, and less often in 2017–2018.")
bn = lambda v: f"{v / B:.3f}"


# ---- 3.1 the reference line --------------------------------------------------------------------------------------------------

def test_the_reference_line_keeps_its_label_and_adds_the_anchor_role_sentence_after_the_value():
    ref = _build(_margin_record(x_L=X_BASE / REV_BASE), _cash(1.0 * B))
    line = cr.pack_line(ref, OE_BASE, COE, GA, bn, anchor=GA)
    head = "- [Arithmetic] CONSENSUS-IMPLIED VALUE (reference, not a forecast): $"
    assert line.startswith(head) and f"${ref['value']:,.2f} per share, the analysts' own earnings path at our discount rate {ROLE} | " in line
    # the parsers' regex still reads the value
    assert pack_facts._CIV_RE.search(line).group(1).replace(",", "") == f"{ref['value']:.2f}"
    assert cr.ANCHOR_ROLE == ROLE
    # every printed reference line carries it: the cash-only line too; a line with no number (not meaningful) prints none
    only = _build(_margin_record(), {"applies": True, "financial": False, "cash": 3.0 * B, "interest": OE_BASE, "stamps": []})
    assert only["method"] == "cash_only" and ROLE in cr.pack_line(only, OE_BASE, COE, GA, bn, anchor=GA)
    assert ROLE not in cr.not_meaningful_line({"reason": None, "stamps": []})


def test_the_clauses_say_the_median_return_the_trend_margin_the_cash_and_the_closure_premium():
    rec = dict(_margin_record(x_L=X_BASE / REV_BASE), R_tc=0.2, ronic_t=0.15)
    ref = _build(rec, _cash(1.0 * B))
    line = cr.pack_line(ref, OE_BASE, COE, GA, bn, anchor=GA, closure_asof="2026-09-20")
    assert ("from year 6 growth is paid for at the median return on tangible capital your record shows "
            "(20.0% in year 5, 15.0% from year 10)") in line
    m5 = ref["long_run"]["m5"]
    assert (f"earnings margin moving from {m5 * 100:.1f}% to {ref['m_long'] * 100:.1f}% by year 10: the operating margin moves to the "
            f"trend level of your 8-year record (6.0%) by year 10 (the consensus implies {ref['om_5'] * 100:.1f}% at year 5)") in line
    assert "plus excess cash $1.000B at face (after-tax interest on it removed from earnings)" in line
    assert f"discounted at the COE ANCHOR {COE * 100:.2f}%, built from the market-consistent premium (rs2 closure, as of 2026-09-20)" in line
    assert line.index("from year 6") < line.index("plus excess cash") < line.index("discounted at the COE ANCHOR")
    plain = cr.pack_line(ref, OE_BASE, COE, GA, bn, anchor=GA)
    assert f"discounted at the COE ANCHOR {COE * 100:.2f}% |" in plain + " |" and "market-consistent" not in plain
    fin = _build(rec, {"applies": False, "financial": True, "cash": 0.0, "interest": 0.0, "stamps": []})
    assert "no excess-cash term (financial company)" in cr.pack_line(fin, OE_BASE, COE, GA, bn, anchor=GA)
    none = _build(rec, {"applies": False, "financial": False, "cash": None, "interest": 0.0,
                        "stamps": ["cash_term_not_available_no_bill_rate"]})
    assert ("no excess-cash term (not available: cash_term_not_available_no_bill_rate)"
            in cr.pack_line(none, OE_BASE, COE, GA, bn, anchor=GA))
    held = _build(dict(REDUCTION, om_trend=None, om_L=None), None)
    assert "to measure its trend level" in cr.pack_line(held, OE_BASE, COE, GA, bn, anchor=GA)


def test_the_pack_line_in_a_built_pack_carries_the_sentence_and_the_closure_date(screener_data_stub, monkeypatch):
    text = str(_synthetic_pack(monkeypatch))
    line = next(l for l in text.splitlines() if "CONSENSUS-IMPLIED VALUE (reference" in l)
    assert ROLE in line and "(rs2 closure, as of 2026-09-20)" in line and "median return on tangible capital" in line
    assert "plus excess cash" in line or "no excess-cash term" in line


# ---- 3.2 the TASK -------------------------------------------------------------------------------------------------------------

LEVEL_ANCHOR = ("   - Level anchor: the CONSENSUS-IMPLIED VALUE checks the level of your Base, not the direction of your call. It values "
                "average performers close to their price, but by itself it is not evidence that a stock is cheap or expensive. Your "
                "call rests on the economics you set out above. A Base far from the reference needs the reason DEFAULTS names; a "
                "Base close to it needs no reason and earns no credit.\n")


def test_the_task_has_the_level_anchor_bullet_after_valuation_date_and_no_sentence_names_the_base_year_cap(screener_data_stub, monkeypatch):
    t = cap.TASK
    assert LEVEL_ANCHOR in t
    vd = t.index("   - Valuation date:")
    assert t.index("   - Level anchor:") == t.index("\n", vd) + 1 and t.index("   - Frame:") > t.index("   - Level anchor:")
    surfaces = {"TASK": t, "TOOLS": json.dumps(at.TOOLS), "RESEARCH_ADDENDUM": cap.RESEARCH_ADDENDUM,
                "pack": str(_synthetic_pack(monkeypatch))}
    for name, text in surfaces.items():
        assert "base-year cap" not in text.lower() and "base year cap" not in text.lower(), name
    for ms in (2.0, 0.25):
        for confirmed in (True, False):
            assert "cap" not in pack_facts._split_explanation(ms, confirmed).replace("capital", "")
    assert cap.PACK_REVISION == 18 and pack_facts.FACTS_VERSION == 6


# ---- the schema and the contract ----------------------------------------------------------------------------------------------

def test_the_desk_schema_declares_excess_cash_and_its_reason_and_the_contract_carries_the_reason():
    tool = next(x for x in at.TOOLS if x["function"]["name"] == "run_financial_model")
    props = tool["function"]["parameters"]["properties"]
    assert props["excess_cash"]["type"] == "number" and props["excess_cash_reason"]["type"] == "string"
    assert "DEFAULTS excess_cash" in props["excess_cash"]["description"] and "excess_cash_reason" in props["excess_cash"]["description"]
    assert "excess_cash_reason" in contract_fill.REASONS_11 and "excess_cash_reason" in contract_fill.FILLED
    import consensus_valuation as cv
    import depth_pipeline
    src_cv, src_dp = Path(cv.__file__).read_text(encoding="utf-8"), Path(depth_pipeline.__file__).read_text(encoding="utf-8")
    assert src_cv.count('"excess_cash_reason"') >= 2 and '"excess_cash_reason"' in src_dp   # the scorecard schema and the pass-throughs


def test_a_desk_call_with_a_different_excess_cash_is_refused_without_the_declared_reason_and_accepted_with_it():
    from test_rev18_part1 import _desk_call, _desk_ctx
    from test_rev17f_redesign import _w9_reference
    ref = _w9_reference()
    refused = fmt.execute_financial_model(_desk_call(ref, excess_cash=0.4), _desk_ctx(ref, excess_cash=1.0))
    assert "excess_cash_reason needed" in refused["error"]
    ok = fmt.execute_financial_model(
        _desk_call(ref, excess_cash=0.4, excess_cash_reason="cash held in a restricted account, per the 2026-08 10-Q"),
        _desk_ctx(ref, excess_cash=1.0))
    assert "error" not in ok


# ---- the reverse DCF and the cash term (bar AT1e) -----------------------------------------------------------------------------

def _neutral_forward(base, g, coe, ga, shares, cash=0.0):
    iv, _cf, _cagr = fmt._neutral_reference_dcf(base_cf=base, g=g, coe_anchor=coe, terminal_g_anchor=ga, net_debt=0.0,
                                                shares_diluted=shares)
    return iv + cash / shares


def test_the_reverse_dcf_subtracts_the_cash_and_returns_the_growth_a_price_with_cash_implies():
    base, shares, coe, ga, cash = 1.0, 0.5, 0.09, 0.0375, 2.0          # $B, billions of shares: the cash is $4 a share
    for g in (-0.05, 0.0, 0.08, 0.20):
        price = _neutral_forward(base, g, coe, ga, shares, cash)
        got = fmt.reverse_dcf_expectations_gap(current_price=price, shares_diluted=shares, base_cf=base, wacc=coe, terminal_g=ga,
                                               fade_years=5, coe_anchor=coe, terminal_g_anchor=ga, excess_cash=cash)
        assert abs(got["neutral_reference_structure"]["solved_initial_growth_pct"] - g * 100) <= 0.1
        # without the cash term the same price reads as faster growth: the cash is mistaken for operating value
        blind = fmt.reverse_dcf_expectations_gap(current_price=price, shares_diluted=shares, base_cf=base, wacc=coe, terminal_g=ga,
                                                 fade_years=5, coe_anchor=coe, terminal_g_anchor=ga)
        assert blind["neutral_reference_structure"]["solved_initial_growth_pct"] > g * 100 + 1.0
    # the firm frame's net_debt already nets the cash: it adds none
    price = _neutral_forward(base, 0.08, coe, ga, shares)
    firm = fmt.reverse_dcf_expectations_gap(current_price=price, shares_diluted=shares, base_cf=base, wacc=coe, terminal_g=ga,
                                            fade_years=5, coe_anchor=coe, terminal_g_anchor=ga, valuation_frame="firm",
                                            excess_cash=cash)
    assert abs(firm["neutral_reference_structure"]["solved_initial_growth_pct"] - 8.0) <= 0.1
    # no cash passed: the old arithmetic exactly
    plain_price = _neutral_forward(base, 0.12, coe, ga, shares)
    plain = fmt.reverse_dcf_expectations_gap(current_price=plain_price, shares_diluted=shares, base_cf=base, wacc=coe,
                                             terminal_g=ga, fade_years=5, coe_anchor=coe, terminal_g_anchor=ga, excess_cash=0.0)
    assert abs(plain["neutral_reference_structure"]["solved_initial_growth_pct"] - 12.0) <= 0.1


def test_the_desks_reverse_dcf_gets_the_default_excess_cash(monkeypatch):
    calls = []
    real = fmt.reverse_dcf_expectations_gap
    monkeypatch.setattr(fmt, "reverse_dcf_expectations_gap", lambda **k: (calls.append(k), real(**k))[1])
    from test_rev18_part1 import _desk_call, _desk_ctx
    from test_rev17f_redesign import _w9_reference
    ref = _w9_reference()
    ctx = _desk_ctx(ref, excess_cash=1.0, price=50.0, coe_anchor=0.09, terminal_g_anchor=0.0375, revenue_cagr_5y_pct=5.0)
    out = fmt.execute_financial_model(_desk_call(ref, shares_diluted=0.05), ctx)
    assert "error" not in out and "reverse_dcf" in out and calls and calls[-1]["excess_cash"] == 1.0
