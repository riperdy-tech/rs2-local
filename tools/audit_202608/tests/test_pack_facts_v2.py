"""tools/audit_202608/tests/test_pack_facts_v2.py — S3 3.1: pack_facts version 3 (section 6 item 1).

Covers the legacy readers for the five new keys that already have a revision-14 print site, the
revision-15 DEFAULTS-block reader on hand-written blocks, and the no-DEFAULTS-block raise.

NOT covered here (Package C, out of scope for this brief pass): the DEFAULTS reader round-tripped
against a real golden_pack_GEV_rev15.md build, since section 5.2's DEFAULTS block is not rendered
by capability_test.build_pack in this step (PACK_REVISION stays 14). The reader is instead
exercised against hand-written text matching 5.2's format, as the brief allows.
"""
from pathlib import Path
import sys

import pytest

_HERE = Path(__file__).resolve().parent.parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO))

import pack_facts


# ---------------------------------------------------------------------------------------------
# Legacy readers (revisions <= 14) for the five new keys with an existing revision-14 print site
# ---------------------------------------------------------------------------------------------

def test_terminal_g_anchor_legacy_pattern():
    text = "- Long-run nominal growth anchor for terminal_g: 3.75%  [structural]\n"
    assert pack_facts.from_text(text)["terminal_g_anchor"] == pytest.approx(0.0375)


def test_terminal_g_anchor_not_available():
    text = "- Long-run nominal growth anchor for terminal_g: not available  (no anchor)\n"
    assert pack_facts.from_text(text)["terminal_g_anchor"] is None


def test_terminal_g_anchor_absent_line():
    assert pack_facts.from_text("no such line here\n")["terminal_g_anchor"] is None


def test_base_rate_5y_legacy_pattern():
    text = ("- 5y sustained growth, this size bucket (n=42): >=10%/yr 26.7%, >=20%/yr 6.8%, "
            ">=30%/yr 2.2%, median 5.6%, p90 16.7%\n")
    facts = pack_facts.from_text(text)
    assert facts["base_rate_5y"] == {
        "share_ge_10": 26.7, "share_ge_20": 6.8, "share_ge_30": 2.2, "p50": 5.6, "p90": 16.7,
    }


def test_base_rate_5y_absent_is_empty_dict():
    assert pack_facts.from_text("nothing here\n")["base_rate_5y"] == {}


def test_owner_earnings_default_b_legacy_pattern():
    text = ("- [Arithmetic] OWNER EARNINGS (default base_cf): TTM net income $0.500B + D&A (FY2025) "
            "$0.050B − TTM capex $0.030B = $0.520B. Stock compensation...\n")
    assert pack_facts.from_text(text)["owner_earnings_default_b"] == pytest.approx(0.520)


def test_owner_earnings_default_b_not_available():
    text = "- OWNER EARNINGS (default base_cf): not available — TTM net income missing\n"
    assert pack_facts.from_text(text)["owner_earnings_default_b"] is None


def test_cash_basis_b_legacy_pattern():
    text = ("- [Arithmetic] CASH BASIS (alternative base_cf): TTM operating cash flow $0.600B "
            "− TTM capex $0.030B − stock compensation (FY2025) $0.020B = $0.550B. "
            "Includes working-capital swings...\n")
    assert pack_facts.from_text(text)["cash_basis_b"] == pytest.approx(0.550)


def test_cash_basis_b_absent_is_none():
    assert pack_facts.from_text("nothing here\n")["cash_basis_b"] is None


def test_revenue_cagr_5y_pct_legacy_pattern():
    text = "- Revenue CAGR, trailing 5 fiscal years: +9.1%\n"
    assert pack_facts.from_text(text)["revenue_cagr_5y_pct"] == pytest.approx(9.1)


def test_revenue_cagr_5y_pct_negative():
    text = "- Revenue CAGR, trailing 5 fiscal years: -3.4%\n"
    assert pack_facts.from_text(text)["revenue_cagr_5y_pct"] == pytest.approx(-3.4)


def test_revenue_cagr_5y_pct_not_available():
    text = "- Revenue CAGR, trailing 5 fiscal years: not available\n"
    assert pack_facts.from_text(text)["revenue_cagr_5y_pct"] is None


def test_five_11_share_keys_never_found_pre_revision_15():
    """5.11 (Package C) has no revision-14 print site, so a legacy (non-revision-15) text never
    carries these facts."""
    text = "- Shares outstanding: 61,443,377\n" + "- COE ANCHOR for this name: rf 5% = 8.91%\n"
    facts = pack_facts.from_text(text)
    assert facts["shares_default"] is None
    assert facts["shares_dilution_factor"] is None
    assert facts["shares_dilution_period"] is None
    assert facts["shares_warning"] is None


def test_facts_version_and_key_count():
    assert pack_facts.FACTS_VERSION == 3
    assert len(pack_facts.KEYS) == 23


def test_empty_has_all_23_keys():
    e = pack_facts.empty()
    for k in pack_facts.KEYS:
        assert k in e


# ---------------------------------------------------------------------------------------------
# Revision-15 DEFAULTS-block reader (hand-written text; no golden pack yet, package C)
# ---------------------------------------------------------------------------------------------

_EZPW_DEFAULTS_BLOCK = """# DATA PACK - EZPW   (pack revision 15)

## DEFAULTS   [each desk input takes this value unless you pass another; a departure needs the named reason, and the desk asks for it]
- shares_outstanding: <61,443,377> | SECTION 2, the vendor's basic count
- shares_dilution_factor: <1.2917> (<quarter ended 2026-06-30>: basic EPS <0.62>, diluted EPS <0.48>) | the company's own diluted EPS; applied when it is at least 1.05
- shares_default: <79,364,362> | the desk's shares_diluted unless you pass another count with shares_reason
- shares_warning: <not available> | when present, the desk asks for shares_reason on every call
- owner_earnings_default_b: <0.148> (<owner_earnings_source>) | the Base base_cf; more than 2% away needs base_cf_reason | cash_basis_b: <0.126>, the alternative
- base_window: gap <+56%>, ttm_value <12.34>, ttm_year2 <0.160> | when printed, base_cf_reason names the window you judge representative and the item behind the gap
- coe_anchor: <8.91%> | the Base discount rate; more than 1.5 points away needs coe_adjustment_reason
- terminal_g_default: <3.75%> (terminal_g_anchor: <3.75%>) | the Base terminal_g; more than 0.5 points away needs terminal_reason
- default_exit_multiple: <20.12>x | (1 + g) / (rate - g) at the defaults; a Base multiple implying terminal growth more than 0.5 points from terminal_g_default needs terminal_reason
- valuation_frame: equity | the pack's flows are after interest; the firm frame needs interest_addback (at most the latest filed interest expense, interest_expense_latest_b: <0.016>), wacc_reason, and net_debt_b: <-0.048> (another figure needs net_debt_reason)
- consensus_implied_value: <58.92> (<reference_status>) | a Base value outside 0.75-1.33 of it (<44.19>-<78.36>) needs guidance_deviation_reason
- levels: year1 <0.147>, year2 <0.160>, bull2 <0.164>, bear2 <0.159> | a Base year-2 cash flow more than 15% from year2 needs guidance_deviation_reason; a Bull or Bear more than 15% from bull2 or bear2 needs scenario_deviation_reason
- next_fy_revenue_growth: <+9.5%> | Base years 3-5 above it need guidance_deviation_reason, or the desk holds them at it
- years35_p90: <16.7%> | growth above the base-rate p90 needs dated, company-specific evidence (a flag, not a veto)
- base_rate_5y: p50 <5.6%>, p90 <16.7%>, share_ge_10 <26.7%>, share_ge_20 <6.8%>, share_ge_30 <2.2%> | the desk ranks the market-implied growth against it
- revenue_cagr_5y_pct: <+9.1%> | the desk compares the market-implied growth with it
- cash_flow_life: required on every desk call ("perpetual" or years), with cash_flow_life_reason
- price: a Bull value below today's price needs bull_below_price_reason; a Bear value above it needs bear_above_price_reason
"""


def test_defaults_block_round_trip_ezpw_example():
    f = pack_facts.from_text(_EZPW_DEFAULTS_BLOCK)
    assert f["version"] == 3
    assert f["shares_outstanding"] == 61443377.0
    assert f["shares_default"] == 79364362.0
    assert f["shares_dilution_factor"] == pytest.approx(1.2917)
    assert f["shares_dilution_period"] == "quarter ended 2026-06-30"
    assert f["shares_warning"] is None
    assert f["owner_earnings_default_b"] == pytest.approx(0.148)
    assert f["cash_basis_b"] == pytest.approx(0.126)
    assert f["base_window"] == {"gap": pytest.approx(0.56), "ttm_value": pytest.approx(12.34),
                                "ttm_year2": pytest.approx(0.160)}
    assert f["coe_anchor"] == pytest.approx(0.0891)
    assert f["terminal_g_default"] == pytest.approx(0.0375)
    assert f["terminal_g_anchor"] == pytest.approx(0.0375)
    assert f["net_debt_b"] == pytest.approx(-0.048)
    assert f["interest_expense_latest_b"] == pytest.approx(0.016)
    assert f["consensus_implied_value"] == pytest.approx(58.92)
    assert f["levels"] == {"year1": pytest.approx(0.147), "year2": pytest.approx(0.160),
                           "bull2": pytest.approx(0.164), "bear2": pytest.approx(0.159)}
    assert f["next_fy_revenue_growth"] == pytest.approx(0.095)
    assert f["years35_p90"] == pytest.approx(0.167)
    assert f["base_rate_5y"] == {"p50": 5.6, "p90": 16.7, "share_ge_10": 26.7,
                                 "share_ge_20": 6.8, "share_ge_30": 2.2}
    assert f["revenue_cagr_5y_pct"] == pytest.approx(9.1)


def test_defaults_block_with_none_values():
    text = """# DATA PACK - X   (pack revision 15)

## DEFAULTS   [test]
- shares_outstanding: <not available> | x
- shares_dilution_factor: <not available> | x
- shares_default: <not available> | x
- shares_warning: <SECTION 2's count is 12% from the basic count implied by filed EPS> | x
- owner_earnings_default_b: <not available> (<not available>) | x | cash_basis_b: <not available>, x
- base_window: <not available> | x
- coe_anchor: <not available> | x
- terminal_g_default: <not available> (terminal_g_anchor: <not available>) | x
- default_exit_multiple: <not available>x | x
- valuation_frame: equity | x, interest_expense_latest_b: <not available>, x, net_debt_b: <not available> x
- consensus_implied_value: <not available> (<not_available>) | x (<not available>-<not available>) x
- levels: <not available> | x
- next_fy_revenue_growth: <not available> | x
- years35_p90: <not available> | x
- base_rate_5y: <not available> | x
- revenue_cagr_5y_pct: <not available> | x
- cash_flow_life: x
- price: x
"""
    f = pack_facts.from_text(text)
    for k in ("shares_outstanding", "shares_default", "shares_dilution_factor",
              "owner_earnings_default_b", "cash_basis_b", "coe_anchor", "terminal_g_default",
              "terminal_g_anchor", "net_debt_b", "interest_expense_latest_b",
              "consensus_implied_value", "next_fy_revenue_growth", "years35_p90",
              "revenue_cagr_5y_pct"):
        assert f[k] is None, f"{k} should be None"
    assert f["base_window"] == {}
    assert f["levels"] == {}
    assert f["base_rate_5y"] == {}
    assert f["shares_warning"] == "SECTION 2's count is 12% from the basic count implied by filed EPS"


def test_defaults_block_net_cash_sign():
    text = """# DATA PACK - X   (pack revision 15)

## DEFAULTS   [test]
- valuation_frame: equity | x, interest_expense_latest_b: <0.010>, x, net_debt_b: <-1.234> x
"""
    f = pack_facts.from_text(text)
    assert f["net_debt_b"] == pytest.approx(-1.234)


def test_defaults_block_zero_value():
    text = """# DATA PACK - X   (pack revision 15)

## DEFAULTS   [test]
- valuation_frame: equity | x, interest_expense_latest_b: <0.000>, x, net_debt_b: <0.000> x
"""
    f = pack_facts.from_text(text)
    assert f["net_debt_b"] == 0.0
    assert f["interest_expense_latest_b"] == 0.0


def test_defaults_block_empty_base_window_and_missing_levels_members():
    text = """# DATA PACK - X   (pack revision 15)

## DEFAULTS   [test]
- base_window: <not available> | x
- levels: year1 <0.100>, year2 <0.200> | x
"""
    f = pack_facts.from_text(text)
    assert f["base_window"] == {}
    assert f["levels"] == {"year1": 0.100, "year2": 0.200}
    assert "bull2" not in f["levels"]
    assert "bear2" not in f["levels"]


def test_revision_15_text_without_defaults_block_raises():
    text = "# DATA PACK - X   (pack revision 15)\n\nno defaults block anywhere in this text\n"
    with pytest.raises(ValueError):
        pack_facts.from_text(text)


def test_revision_15_marker_only_on_first_line():
    """A pack revision 15 mention elsewhere in the text does not trigger the revision-15 path
    (it must be the first line, section 5.1's exact format)."""
    text = "# DATA PACK - X\n\nsome text mentioning (pack revision 15) later on\n"
    # No DEFAULTS block and no raise: falls to the legacy reader.
    f = pack_facts.from_text(text)
    assert f["version"] == 3
    assert f["source"] == "text"


# ---------------------------------------------------------------------------------------------
# Older sidecars (3.1): every KEYS member an old sidecar lacks becomes None
# ---------------------------------------------------------------------------------------------

def test_read_sidecar_backfills_every_missing_key(tmp_path):
    old_sidecar = {"version": 2, "source": "text", "consensus_implied_value": 58.92}
    import json
    (tmp_path / pack_facts.SIDECAR).write_text(json.dumps(old_sidecar), encoding="utf-8")
    data = pack_facts.read_sidecar(tmp_path)
    for k in pack_facts.KEYS:
        assert k in data
    assert data["consensus_implied_value"] == 58.92
    assert data["terminal_g_anchor"] is None
    assert data["shares_default"] is None


def test_read_sidecar_absent_returns_none(tmp_path):
    assert pack_facts.read_sidecar(tmp_path) is None


def test_parity_compares_all_23_keys():
    a = pack_facts.empty()
    b = pack_facts.empty()
    b["terminal_g_anchor"] = 0.03
    mismatches = pack_facts.parity(a, b)
    assert mismatches == ["terminal_g_anchor"]
