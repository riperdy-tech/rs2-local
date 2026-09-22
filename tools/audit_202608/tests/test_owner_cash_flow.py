"""Owner cash flow: the pack prints the arithmetic, and the analyst must declare its basis.

BACKGROUND. Measured 2026-09-20: the analyst is not stable about which cash-flow figure it uses
as its starting point. Two runs of GEV on the same day, same pack revision, same $951.04 price
produced clustered-but-different levels (median IV 934.535 then 517.745) because one run started
from a trailing-twelve-month figure near $12.4B and the other from a normalized forward figure
near $5.0B. Both are defensible readings of the same accounts. What was missing is that the
analyst never SAYS which it used, so the disagreement could not be seen, cited, or checked.

The pack already prints, per fiscal year, all three inputs: OCF, capex and SBC. It even already
carries a caveat that an owner-earnings figure starting from OCF and not subtracting SBC is
overstated. So Part A adds only the SUBTRACTION - one more column in the existing twelve-column
SECTION 5 table, symmetric across every year, no headline. Deliberately QUIET: a highlighted
"latest-year owner cash flow" callout would make one basis salient in a system whose basis choice
is exactly what is under measurement, and would make the result impossible to attribute between
the fix working and the pack steering.

Part B asks the analyst to declare the value it used AND which of a fixed list of bases it came
from, so a computer can check the claim. A free-text declaration would repeat the Task 2 defect:
a stated value the system silently cannot verify.
"""
import pytest

import depth_pipeline as dp
from tools.audit_202608 import capability_test as cap
from tools.audit_202608.consensus_valuation import extract_scorecard, owner_cf_basis_check


# ---- the arithmetic: ONE definition, used by the pack and by the check -----------------

def test_owner_cf_subtracts_both_charges():
    # OCF adds SBC back, so an owner figure that does not subtract it is overstated.
    assert cap.owner_cf(100.0, 20.0, 5.0) == 75.0


def test_owner_cf_is_none_when_any_input_is_missing():
    assert cap.owner_cf(None, 20.0, 5.0) is None
    assert cap.owner_cf(100.0, None, 5.0) is None
    assert cap.owner_cf(100.0, 20.0, None) is None


def test_owner_cf_is_none_on_a_non_numeric_input():
    assert cap.owner_cf("not available", 20.0, 5.0) is None


def test_owner_cf_can_be_negative():
    # A capital-hungry year is a real reading, not an error. Do not clamp.
    assert cap.owner_cf(10.0, 40.0, 5.0) == -35.0


# ---- Part A: the pack prints it, quietly and symmetrically -----------------------------

@pytest.fixture
def gev_pack(screener_data_stub):
    # `screener_data_stub` (conftest) redirects the data directory to a committed GEV slice.
    # Without it this fixture read the operator's `Downloads` path and the tests below passed
    # only on the machine that wrote them. Function scope, not module: the stub is per-test.
    return cap.build_pack("GEV")


def _require_section5(pack):
    """Skip when the pack carries no fiscal-year table.

    The committed fixture (`conftest.screener_data_stub`) reproduces SECTION 5 from real GEV data,
    but the SEC companyfacts path is deeper than that slice covers: with the data directory
    redirected, `_sec_facts()` still returns empty and the table renders as "all 0 years we
    hold". These tests assert on the CONTENT of that table, so on a machine without the filings
    they would fail - or, worse, pass vacuously against an empty table.

    HERMETICITY IS NOT ACHIEVED HERE. This is an explicit, visible dependency, which is the
    honest alternative to a test that reports success while measuring nothing - the failure mode
    this suite has already produced twice.
    """
    if "## SECTION 5" not in pack:
        pytest.skip("pack has no SECTION 5 - screener data unavailable")
    sec5 = pack.split("## SECTION 5")[1].split("## SECTION 6")[0]
    if not any(l.strip().startswith("| 20") for l in sec5.splitlines()):
        pytest.skip("no fiscal-year rows in SECTION 5 - screener sec_facts unavailable")
    return sec5


def test_the_pack_prints_the_owner_cash_flow_column(gev_pack):
    _require_section5(gev_pack)
    assert "owner CF [Arithmetic]" in gev_pack


def test_the_column_sits_in_the_section_5_table(gev_pack):
    # Named for the section whose inputs it uses, so its provenance is unambiguous.
    sec5 = _require_section5(gev_pack)
    assert "owner CF [Arithmetic]" in sec5


def test_the_arithmetic_line_is_not_a_headline(gev_pack):
    # The quiet requirement, pinned. A callout would make one basis salient.
    _require_section5(gev_pack)
    head = "\n".join(gev_pack.splitlines()[:60])
    assert "owner CF" not in head


def test_the_section_5_header_and_separator_have_equal_widths(gev_pack):
    sec5 = _require_section5(gev_pack).split("\n")
    header = next(l for l in sec5 if "OCF" in l and "capex" in l)
    sep = next(l for l in sec5 if set(l.strip()) <= set("-| "))
    cols = lambda line: len([c for c in line.split("|") if c.strip()])
    assert cols(header) == cols(sep)


def test_every_fiscal_year_row_has_the_same_width_as_the_header(gev_pack):
    sec5 = _require_section5(gev_pack).splitlines()
    header = next(l for l in sec5 if "OCF" in l and "capex" in l)
    sep = sec5.index(next(l for l in sec5 if set(l.strip()) <= set("-| ")))
    # The table is contiguous and terminated by a blank line; the note bullets that follow it are
    # prose and have one "column", so they must not be counted as rows.
    rows = []
    for line in sec5[sep + 1:]:
        if not line.strip():
            break
        rows.append(line)
    expected = len([c for c in header.split("|") if c.strip()])
    assert rows, "no fiscal-year rows found after the separator"
    assert {len([c for c in r.split("|") if c.strip()]) for r in rows} == {expected}


def test_pack_revision_moved_with_the_pack_text():
    # The governance invariant, not a change detector: a pack whose TEXT changed while its
    # revision stayed put leaves old and new verdicts stamped identically, so nothing re-runs
    # the stale ones and the book silently mixes two dossiers.
    assert cap.PACK_REVISION >= 4


# ---- Part B: the declared basis is checkable -------------------------------------------

# GEV's real filed figures, in $B, as the pack prints them.
YEARS = {2023: 4.10, 2024: 4.70, 2025: 5.00}


def test_a_matching_latest_year_claim_is_silent():
    sc = {"base_cf_used": 5.0, "base_cf_basis": "latest_fy"}
    assert owner_cf_basis_check("GEV", sc, years=YEARS) is None


def test_a_mismatched_latest_year_claim_is_flagged():
    sc = {"base_cf_used": 12.438, "base_cf_basis": "latest_fy"}
    note = owner_cf_basis_check("GEV", sc, years=YEARS)
    assert note and "12.4" in note and "latest fiscal year" in note


def test_a_matching_average_claim_is_silent():
    sc = {"base_cf_used": 4.6, "base_cf_basis": "multi_year_avg"}
    assert owner_cf_basis_check("GEV", sc, years=YEARS) is None


def test_a_mismatched_average_claim_is_flagged():
    sc = {"base_cf_used": 12.438, "base_cf_basis": "multi_year_avg"}
    assert owner_cf_basis_check("GEV", sc, years=YEARS)


def test_a_tolerance_is_applied():
    # 5.0 exact; 5.4 is +8% (inside), 6.0 is +20% (outside).
    assert owner_cf_basis_check("GEV", {"base_cf_used": 5.4, "base_cf_basis": "latest_fy"}, years=YEARS) is None
    assert owner_cf_basis_check("GEV", {"base_cf_used": 6.0, "base_cf_basis": "latest_fy"}, years=YEARS)


def test_other_is_an_honest_escape_hatch():
    sc = {"base_cf_used": 12.438, "base_cf_basis": "other"}
    assert owner_cf_basis_check("GEV", sc, years=YEARS) is None


def test_an_unrecognised_basis_is_flagged():
    sc = {"base_cf_used": 5.0, "base_cf_basis": "vibes"}
    assert owner_cf_basis_check("GEV", sc, years=YEARS)


# ---- the trailing basis, which is the reading that actually overstated GEV ------------
# Real data: GEV's trailing record holds OCF $14.139B and capex $1.701B but NO SBC, so trailing
# free cash flow is 14.139 - 1.701 = $12.438B against a latest-FY owner CF of $3.453B. That is
# exactly the figure the unstable run used. It must be CHECKABLE, which requires the basis name
# to say which trailing figure it means.

TTM_FCF = 12.438


def test_a_matching_ttm_fcf_claim_is_silent():
    sc = {"base_cf_used": 12.438, "base_cf_basis": "ttm_fcf"}
    assert owner_cf_basis_check("GEV", sc, years=YEARS, ttm_fcf=TTM_FCF) is None


def test_a_ttm_fcf_claim_pointing_at_the_latest_fy_figure_is_flagged():
    sc = {"base_cf_used": 3.453, "base_cf_basis": "ttm_fcf"}
    note = owner_cf_basis_check("GEV", sc, years=YEARS, ttm_fcf=TTM_FCF)
    assert note and "trailing twelve months" in note.lower()


def test_ttm_fcf_is_unchecked_when_we_hold_no_trailing_record():
    # We hold no trailing record for the name; absence is not a defect and must not be flagged.
    sc = {"base_cf_used": 12.438, "base_cf_basis": "ttm_fcf"}
    assert owner_cf_basis_check("GEV", sc, years=YEARS, ttm_fcf=None) is None


def test_the_bare_basis_name_ttm_is_no_longer_offered():
    # It was ambiguous - it did not say whether it meant trailing OCF or trailing FCF.
    assert "ttm" not in cap.OWNER_CF_BASES
    assert "ttm_fcf" in cap.OWNER_CF_BASES


def test_an_absent_declaration_is_not_a_defect():
    # Legacy verdicts and the non-tools path declare nothing; absence is not an error.
    assert owner_cf_basis_check("GEV", {}, years=YEARS) is None
    assert owner_cf_basis_check("GEV", {"base_cf_used": 5.0}, years=YEARS) is None


def test_no_filed_years_means_nothing_to_check_against():
    assert owner_cf_basis_check("GEV", {"base_cf_used": 5.0, "base_cf_basis": "latest_fy"}, years={}) is None


def test_the_basis_is_case_and_space_insensitive():
    sc = {"base_cf_used": 5.0, "base_cf_basis": "  LATEST_FY "}
    assert owner_cf_basis_check("GEV", sc, years=YEARS) is None


# ---- the declaration must survive extraction ------------------------------------------

def _report(card_extra):
    import json
    card = {"base_iv": 100.0, "bull_iv": 150.0, "bear_iv": 80.0, "conviction_score": 12.0,
            "business_quality_moat": 4.0, "kelly_fraction_pct": 10.0,
            "reentry_tranches": {"tranche_1_starter": 95.0, "tranche_2_core": 80.0},
            "thesis_invalidation_trigger": "Backlog declines."}
    card.update(card_extra)
    return "```json:underwriting\n" + json.dumps(card) + "\n```\n"


def test_extract_scorecard_carries_the_declared_basis():
    # The Task 2 lesson: a field absent from this whitelist is dropped unrecoverably.
    sc = extract_scorecard(_report({"base_cf_used": 5.0, "base_cf_basis": "latest_fy"}), 100.0)
    assert sc["base_cf_used"] == 5.0
    assert sc["base_cf_basis"] == "latest_fy"


def test_extract_scorecard_reports_an_absent_declaration_as_none():
    sc = extract_scorecard(_report({}), 100.0)
    assert sc["base_cf_used"] is None
    assert sc["base_cf_basis"] is None


def test_the_task_asks_for_both_fields():
    assert "base_cf_used" in cap.TASK
    assert "base_cf_basis" in cap.TASK


def test_the_task_lists_the_allowed_bases():
    for basis in cap.OWNER_CF_BASES:
        assert basis in cap.TASK
