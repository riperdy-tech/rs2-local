"""tools/audit_202608/tests/test_pack_facts_v2.py — S3 3.1: pack_facts version 3 (section 6 item 1).

Covers the legacy readers for the five new keys that already have a revision-14 print site, and
the revision-15 DEFAULTS-block round trip (5.2, built in package C: `render_defaults_block` /
`_from_defaults_block`, exercised against hand-written facts dicts and against a real
capability_test.build_pack("GEV") output).
"""
from pathlib import Path
import sys

import pytest

_HERE = Path(__file__).resolve().parent.parent
_REPO = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO))

import capability_test as cap
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
    assert pack_facts.FACTS_VERSION == 4
    assert len(pack_facts.KEYS) == 24


def test_empty_has_all_24_keys():
    e = pack_facts.empty()
    for k in pack_facts.KEYS:
        assert k in e


# ---------------------------------------------------------------------------------------------
# Revision-15 DEFAULTS-block round trip (5.2, package C): render_defaults_block / reader
# ---------------------------------------------------------------------------------------------

def _rev15(block):
    return "# DATA PACK - X   (pack revision 15)\n\n" + block


def test_defaults_block_round_trip_ezpw_example():
    """The brief's own normative EZPW example (5.2), reproduced by the renderer byte for byte."""
    facts = dict(pack_facts.empty(), version=4,
                 shares_outstanding=61443377.0, shares_dilution_factor=1.2917,
                 shares_dilution_period="quarter ended 2026-06-30", shares_default=79364362.0,
                 shares_warning=None, filed_shares_diluted=83383000.0, filed_shares_fy=2025,
                 owner_earnings_default_b=0.148, owner_earnings_source="ttm_filed",
                 cash_basis_b=0.126, base_window={}, coe_anchor=0.0891,
                 terminal_g_default=0.0375, terminal_g_anchor=0.0375, net_debt_b=-0.048,
                 interest_expense_latest_b=None, consensus_data_status="ok",
                 consensus_implied_value=58.92, reference_status="used",
                 levels={"year1": 0.147, "year2": 0.160, "bull2": 0.164, "bear2": 0.159},
                 next_fy_revenue_growth=9.5 / 100, years35_p90=16.7 / 100.0,
                 base_rate_5y={"share_ge_10": 26.7, "share_ge_20": 6.8, "share_ge_30": 2.2,
                              "p50": 5.6, "p90": 16.7},
                 revenue_cagr_5y_pct=9.1)
    # the multiple is the caller's own pre-computed value (SECTION 1.5's, at full precision) —
    # see render_defaults_block's docstring for why it is not derived from the rounded facts.
    dex = cap._exit_multiple_value(8.91, 0.0375)
    block = pack_facts.render_defaults_block(facts, default_exit_multiple=dex)
    expected_lines = [
        "- shares_outstanding: 61,443,377 | DATA 2, the vendor's basic count",
        "- shares_dilution_factor: 1.2917 | the company's own diluted EPS (basic / diluted EPS); "
        "applied when it is at least 1.05",
        "- shares_dilution_period: quarter ended 2026-06-30 | the filed period the factor comes from",
        "- shares_default: 79,364,362 | the desk's shares_diluted unless you pass another count "
        "with shares_reason",
        "- shares_warning: not available | when present, the desk asks for shares_reason on "
        "every call",
        "- filed_shares_diluted: 83,383,000 | DATA 6B's latest filed diluted average; with "
        "after-interest flows it counts a convertible's interest twice",
        "- filed_shares_fy: 2025 | the fiscal year of that average",
        "- owner_earnings_default_b: 0.148 | the Base base_cf; more than 2% away needs base_cf_reason",
        "- owner_earnings_source: ttm_filed | where that default comes from",
        "- cash_basis_b: 0.126 | the alternative base (includes working-capital swings)",
        "- base_window: not available | when printed, base_cf_reason names the window you judge "
        "representative and the item behind the gap",
        "- coe_anchor: 8.91% | the Base discount rate; more than 1.5 points away needs "
        "coe_adjustment_reason",
        "- terminal_g_default: 3.75% | the Base terminal_g; more than 0.5 points away needs "
        "terminal_reason",
        "- terminal_g_anchor: 3.75% | the long-run nominal growth anchor",
        # the brief's worked "20.12x" comes from the real MRI anchor's full, unrounded precision
        # (5.6's normative example); the synthetic 8.91/3.75 stand-ins used above round to
        # 20.11x, so this asserts the renderer's number against `dex` (computed the same way
        # SECTION 1.5 does) rather than the brief's literal digits.
        f"- default_exit_multiple: {dex:.2f}x | (1 + g) / (rate - g) at the defaults; a Base "
        "multiple implying terminal growth more than 0.5 points from terminal_g_default needs "
        "terminal_reason",
        "- net_debt_b: -0.048 | the firm frame's net debt; another figure needs net_debt_reason "
        "(the pack's flows are after interest: value them in the equity frame)",
        "- interest_expense_latest_b: not available | the firm frame's interest_addback is at "
        "most this",
        "- consensus_data_status: ok | ok, or why DATA 8 prints no consensus estimates",
        "- consensus_implied_value: 58.92 | a Base value outside 0.75-1.33 of it (44.19-78.36) "
        "needs guidance_deviation_reason",
        "- reference_status: used | whether the reference is shown, fenced or not available",
        "- levels: year1=0.147, year2=0.160, bull2=0.164, bear2=0.159 | a Base year-2 cash flow "
        "more than 15% from year2 needs guidance_deviation_reason; a Bull or Bear more than 15% "
        "from bull2 or bear2 needs scenario_deviation_reason",
        "- next_fy_revenue_growth: +9.5% | Base years 3-5 above it need guidance_deviation_reason, "
        "or the desk holds them at it",
        "- years35_p90: 16.7% | growth above the base-rate p90 needs dated, company-specific "
        "evidence (a flag, not a veto)",
        "- base_rate_5y: share_ge_10=26.7%, share_ge_20=6.8%, share_ge_30=2.2%, p50=5.6%, "
        "p90=16.7% | the desk ranks the market-implied growth against it",
        "- revenue_cagr_5y_pct: +9.1% | the desk compares the market-implied growth with it",
        '- cash_flow_life: required on every desk call ("perpetual" or years), with '
        "cash_flow_life_reason",
        "- price: a Bull value below today's price needs bull_below_price_reason; a Bear value "
        "above it needs bear_above_price_reason",
    ]
    for expected in expected_lines:
        assert expected in block, expected
    f = pack_facts.from_text(_rev15(block))
    assert f["version"] == 4
    assert pack_facts.parity(facts, f) == []


def test_defaults_block_with_none_values():
    facts = pack_facts.empty()
    facts["shares_warning"] = "SECTION 2's count is 12% from the basic count implied by filed EPS"
    block = pack_facts.render_defaults_block(facts)
    f = pack_facts.from_text(_rev15(block))
    for k in pack_facts.KEYS:
        if k == "shares_warning":
            continue
        assert f[k] == facts[k], f"{k} should round-trip to {facts[k]!r}, got {f[k]!r}"
    assert f["base_window"] == {}
    assert f["levels"] == {}
    assert f["base_rate_5y"] == {}
    assert f["shares_warning"] == "SECTION 2's count is 12% from the basic count implied by filed EPS"


def test_defaults_block_net_cash_sign():
    facts = dict(pack_facts.empty(), net_debt_b=-1.234, interest_expense_latest_b=0.010)
    block = pack_facts.render_defaults_block(facts)
    assert "- net_debt_b: -1.234 |" in block
    f = pack_facts.from_text(_rev15(block))
    assert f["net_debt_b"] == pytest.approx(-1.234)
    assert f["interest_expense_latest_b"] == pytest.approx(0.010)


def test_defaults_block_zero_value():
    facts = dict(pack_facts.empty(), net_debt_b=0.0, interest_expense_latest_b=0.0)
    block = pack_facts.render_defaults_block(facts)
    assert "- net_debt_b: 0.000 |" in block
    assert "- interest_expense_latest_b: 0.000 |" in block
    f = pack_facts.from_text(_rev15(block))
    assert f["net_debt_b"] == 0.0
    assert f["interest_expense_latest_b"] == 0.0


def test_defaults_block_empty_base_window_and_missing_levels_members():
    facts = dict(pack_facts.empty(), base_window={}, levels={"year1": 0.100, "year2": 0.200})
    block = pack_facts.render_defaults_block(facts)
    assert "- base_window: not available |" in block
    f = pack_facts.from_text(_rev15(block))
    assert f["base_window"] == {}
    assert f["levels"] == {"year1": 0.100, "year2": 0.200}
    assert "bull2" not in f["levels"]
    assert "bear2" not in f["levels"]


def test_defaults_block_a_reference_status_with_no_value():
    """S2c fail-open bug the A+B review corrected: a reference_status without a numeric
    consensus_implied_value must still round-trip (the status is read verbatim, never inferred)."""
    facts = dict(pack_facts.empty(), consensus_implied_value=None,
                 reference_status="outside_fence_above")
    block = pack_facts.render_defaults_block(facts)
    f = pack_facts.from_text(_rev15(block))
    assert f["consensus_implied_value"] is None
    assert f["reference_status"] == "outside_fence_above"


def test_defaults_block_shares_warning_present():
    facts = dict(pack_facts.empty(), shares_warning=(
        "SECTION 2's count is 29% from the basic count implied by filed EPS: share classes, "
        "ADS units or a stale vendor count"))
    block = pack_facts.render_defaults_block(facts)
    f = pack_facts.from_text(_rev15(block))
    assert f["shares_warning"] == facts["shares_warning"]


@pytest.mark.parametrize("status", ["ok", "enrich_missing", "stale", "estimates_unavailable",
                                    "point_in_time", None])
def test_defaults_block_each_consensus_data_status_value(status):
    facts = dict(pack_facts.empty(), consensus_data_status=status)
    block = pack_facts.render_defaults_block(facts)
    f = pack_facts.from_text(_rev15(block))
    assert f["consensus_data_status"] == status


def test_defaults_block_round_trips_a_real_gev_build(monkeypatch, screener_data_stub):
    """The DEFAULTS reader round-trips the facts on a real build_pack("GEV") output (section 6
    item 1), with PACK_REVISION forced to 15 so from_text dispatches to the DEFAULTS reader — the
    module stays at 14 until package C's last step (brief section 0)."""
    monkeypatch.setattr(cap, "PACK_REVISION", 15)
    pack = cap.build_pack("GEV", include_research=False)
    text = str(pack)
    assert "(pack revision 15)" in text.splitlines()[0]
    parsed = pack_facts.from_text(text)
    assert pack_facts.parity(pack.facts, parsed) == []


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
    assert f["version"] == 4
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


def test_parity_compares_all_24_keys():
    a = pack_facts.empty()
    b = pack_facts.empty()
    b["terminal_g_anchor"] = 0.03
    mismatches = pack_facts.parity(a, b)
    assert mismatches == ["terminal_g_anchor"]
