"""Tests for share check harness fix (Brief S2b).

Covers:
1. EZPW L2-like: SECTION 2 61,443,377; filed 83,383,000; desk 0.0834B with reason citing SECTION 6B.
2. EZPW without reason: nearest ratio 1.00 to filed count, neither excluded nor flagged.
3. Split case (filed / vendor = 4.0): filed count not candidate; excluded without reason, flagged & kept with reason.
4. Edge ratios: 1.099, 1.10, 1.25, 1.2501; cited vs uncited reasons; absent filed count.
5. from_text for new keys: not available cells last, table with no share column, thousands separators.
6. Citation forms: filing forms and pack sections recognition.
7. band_verdict copies desk_share_basis_matched.
"""
from pathlib import Path
import sys
import pytest

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import consensus_valuation as cv
import contract_fill
import depth_pipeline as dp
import financial_model_tool as fmt
import pack_facts


def _run_check(desk_shares_b, facts, shares_reason=None, base_iv=50.0):
    snapshot = [
        {
            "tool": "run_financial_model",
            "params": {
                "shares_diluted": desk_shares_b,
                "base_cf": 1.0,
                "explicit_growth": [0.1],
                "fade_years": 5,
                "wacc": 0.10,
            },
            "result": {
                "dcf_model": {
                    "per_share_iv": base_iv,
                }
            },
        }
    ]
    sc = {"shares_reason": shares_reason} if shares_reason is not None else {}
    return cv.extract_desk_snapshot_metrics(
        snapshot=snapshot,
        base_iv=base_iv,
        scorecard=sc,
        facts=facts,
    )


def test_ezpw_l2_like_with_reason():
    facts = {
        "shares_outstanding": 61443377.0,
        "filed_shares_diluted": 83383000.0,
        "filed_shares_fy": 2025,
    }
    reason = (
        "Vendor's 61,443,377 (SECTION 2) is the BASIC count; matches SECTION 6B's FY2025 wtd-avg "
        "of 83,383K. Diluted count used."
    )
    res = _run_check(0.0834, facts, shares_reason=reason)

    assert res["desk_share_implausible"] is False
    assert not any("desk_share_count_mismatch" in f for f in res["desk_share_flags"])
    assert "desk_share_count_departure_with_reason" in res["desk_share_flags"]
    assert "shares_reason_uncited" not in res["desk_share_flags"]
    assert res["desk_share_basis_matched"] == "filed_fy_wa"


def test_ezpw_l2_like_without_reason():
    facts = {
        "shares_outstanding": 61443377.0,
        "filed_shares_diluted": 83383000.0,
        "filed_shares_fy": 2025,
    }
    res = _run_check(0.0834, facts, shares_reason=None)

    assert res["desk_share_implausible"] is False
    assert res["desk_share_flags"] == []
    assert res["desk_share_basis_matched"] == "filed_fy_wa"


def test_split_case():
    facts = {
        "shares_outstanding": 20000000.0,
        "filed_shares_diluted": 80000000.0,
        "filed_shares_fy": 2025,
    }
    desk_count = 0.080  # equal to filed, 4.0x vendor

    # Without reason: excluded as today
    res_no_reason = _run_check(desk_count, facts, shares_reason=None)
    assert res_no_reason["desk_share_implausible"] is True
    assert "desk_share_count_mismatch_4.00x" in res_no_reason["desk_share_flags"]
    assert res_no_reason["desk_share_basis_matched"] is None

    # With reason: flagged and kept
    res_reason = _run_check(desk_count, facts, shares_reason="Diluted count per 10-K filing")
    assert res_reason["desk_share_implausible"] is False
    assert "desk_share_count_mismatch_4.00x" in res_reason["desk_share_flags"]
    assert "desk_share_count_departure_with_reason" in res_reason["desk_share_flags"]
    assert "shares_reason_uncited" not in res_reason["desk_share_flags"]
    assert res_reason["desk_share_basis_matched"] is None


def test_edge_ratios():
    facts = {
        "shares_outstanding": 100000000.0,
        "filed_shares_diluted": 100000000.0,
        "filed_shares_fy": 2025,
    }

    # 1.099 edge: no mismatch flag, not excluded
    res_1099 = _run_check(0.1099, facts, shares_reason=None)
    assert not any("desk_share_count_mismatch" in f for f in res_1099["desk_share_flags"])
    assert res_1099["desk_share_implausible"] is False

    # 1.10 edge: mismatch flag present, not excluded
    res_110 = _run_check(0.110, facts, shares_reason=None)
    assert "desk_share_count_mismatch_1.10x" in res_110["desk_share_flags"]
    assert res_110["desk_share_implausible"] is False

    # 1.25 edge: mismatch flag present, not excluded without reason
    res_125 = _run_check(0.125, facts, shares_reason=None)
    assert "desk_share_count_mismatch_1.25x" in res_125["desk_share_flags"]
    assert res_125["desk_share_implausible"] is False

    # 1.2501 edge without reason: mismatch flag present, excluded
    res_12501_no = _run_check(0.12501, facts, shares_reason=None)
    assert "desk_share_count_mismatch_1.25x" in res_12501_no["desk_share_flags"]
    assert res_12501_no["desk_share_implausible"] is True

    # 1.2501 edge with cited reason: not excluded, flagged departure
    res_12501_cited = _run_check(0.12501, facts, shares_reason="Count from 10-Q filing")
    assert res_12501_cited["desk_share_implausible"] is False
    assert "desk_share_count_mismatch_1.25x" in res_12501_cited["desk_share_flags"]
    assert "desk_share_count_departure_with_reason" in res_12501_cited["desk_share_flags"]
    assert "shares_reason_uncited" not in res_12501_cited["desk_share_flags"]

    # 1.2501 edge with uncited reason: not excluded, flagged departure and uncited
    res_12501_uncited = _run_check(0.12501, facts, shares_reason="Estimated by analyst judgement")
    assert res_12501_uncited["desk_share_implausible"] is False
    assert "desk_share_count_mismatch_1.25x" in res_12501_uncited["desk_share_flags"]
    assert "desk_share_count_departure_with_reason" in res_12501_uncited["desk_share_flags"]
    assert "shares_reason_uncited" in res_12501_uncited["desk_share_flags"]

    # Absent filed count: only vendor candidate
    facts_absent = {"shares_outstanding": 100000000.0, "filed_shares_diluted": None}
    res_absent = _run_check(0.100, facts_absent, shares_reason=None)
    assert res_absent["desk_share_basis_matched"] == "vendor"
    assert res_absent["desk_share_implausible"] is False
    assert res_absent["desk_share_flags"] == []


# Revision 16: the desk accepts a whole share count or billions and converts with `_to_b`. The
# harness compares in billions, so a whole count must be converted first (PIPR sample 1 raised
# desk_share_count_mismatch_957671873.74x on 71,241,000 against a vendor count of 70,670,000).
PIPR_FACTS = {"shares_outstanding": 70670000.0}


@pytest.mark.parametrize("desk_count", [71241000.0, 0.071241])
def test_whole_count_and_billions_agree_on_pipr(desk_count):
    res = _run_check(desk_count, PIPR_FACTS)
    assert res["desk_share_flags"] == []
    assert res["desk_share_implausible"] is False
    assert res["desk_share_reason"] is None
    assert res["desk_share_basis_matched"] == "vendor"
    assert res["desk_matched_inputs"]["shares_diluted"] == desk_count   # the record keeps what the model sent


def test_pipr_ratio_is_1_008_in_either_unit():
    # 71,241,000 / 70,670,000 = 1.00808; the comparison sits between the 1% match and the 1.10x flag
    ratio_b = 71241000.0 / 70670000.0
    assert round(ratio_b, 3) == 1.008
    for desk_count in (71241000.0, 0.071241):
        name, ratio = contract_fill.s2b_share_match(fmt._to_b(desk_count), PIPR_FACTS)
        assert name == "vendor"
        assert ratio == pytest.approx(ratio_b, abs=1e-9)


@pytest.mark.parametrize("factor, printed", [(1.10, "1.10x"), (1.25, "1.25x"), (2.0, "2.00x")])
@pytest.mark.parametrize("unit", [1.0, 1e-9])
def test_real_mismatch_still_flags_with_correct_ratio(factor, printed, unit):
    res = _run_check(70670000.0 * factor * unit, PIPR_FACTS)
    assert f"desk_share_count_mismatch_{printed}" in res["desk_share_flags"]
    assert res["desk_share_basis_matched"] is None
    # off by more than 25% and no reason: excluded (units or omission)
    assert res["desk_share_implausible"] is (factor > 1.25)


def test_departure_from_default_reads_a_whole_count_in_billions():
    # the departure test in the same block divides the default by 1e9; a whole count must agree with it
    facts = {"shares_outstanding": 70670000.0, "shares_default": 70670000.0}
    reason = "Count from 10-K filing"
    for desk_count in (71241000.0, 0.071241):
        res = _run_check(desk_count, facts, shares_reason=reason)
        assert res["desk_share_flags"] == []
    for desk_count in (77737000.0, 0.077737):
        res = _run_check(desk_count, facts, shares_reason=reason)
        assert "desk_share_count_departure_with_reason" in res["desk_share_flags"]


@pytest.mark.parametrize("unreadable", ["not a count", "79,364,362", None])
def test_unreadable_count_behaves_as_before(unreadable):
    res = _run_check(unreadable, PIPR_FACTS)
    assert res["desk_share_flags"] == []
    assert res["desk_share_implausible"] is False
    assert res["desk_share_basis_matched"] is None
    assert fmt._to_b(unreadable) is None


# The far-from-default annotation: a Base count 10x or more from facts["shares_default"] (whole count,
# 5.11), in either direction, rides on the verdict as a flag. Never an exclusion of its own.
FAR_FACTS = {"shares_outstanding": 70670000.0, "shares_default": 70670000.0}
FAR_DEFAULT_B = 0.07067


@pytest.mark.parametrize("multiple, printed", [
    (10.0, "10.00x"), (11.5, "11.50x"), (100.0, "100.00x"),        # above the default
    (0.1, "10.00x"), (0.05, "20.00x"), (0.02, "50.00x"),            # below it
])
@pytest.mark.parametrize("unit", [1.0, 1e9])                         # billions, and the whole count
def test_a_count_10x_or_more_from_the_default_is_flagged_either_way(multiple, printed, unit):
    res = _run_check(FAR_DEFAULT_B * multiple * unit, FAR_FACTS, shares_reason="Count from 10-K filing")
    assert f"desk_share_count_far_from_default_{printed}" in res["desk_share_flags"]
    assert res["desk_share_implausible"] is False       # with a reason it is kept: the flag annotates only


@pytest.mark.parametrize("multiple", [9.0, 9.99, 1.0, 0.11, 0.5, 2.0])
@pytest.mark.parametrize("unit", [1.0, 1e9])
def test_a_count_under_10x_from_the_default_is_not_flagged_far(multiple, unit):
    res = _run_check(FAR_DEFAULT_B * multiple * unit, FAR_FACTS, shares_reason="Count from 10-K filing")
    assert not any("far_from_default" in f for f in res["desk_share_flags"])


@pytest.mark.parametrize("facts", [
    {"shares_outstanding": 70670000.0},                                   # no default at all
    {"shares_outstanding": 70670000.0, "shares_default": None},
    {"shares_outstanding": 70670000.0, "shares_default": 0.0},            # 0.0 is no usable count, not a ratio
    {"shares_outstanding": 70670000.0, "shares_default": "n/a"},
])
def test_no_default_gives_no_far_flag(facts):
    res = _run_check(FAR_DEFAULT_B * 50, facts, shares_reason="Count from 10-K filing")
    assert not any("far_from_default" in f for f in res["desk_share_flags"])


def test_the_far_flag_never_excludes_a_sample_by_itself():
    """A count that matches SECTION 6B's filed count is no 25% mismatch; sitting 10x from the default is
    only a flag, so nothing is removed from the sample."""
    facts = {"shares_outstanding": 706700000.0, "filed_shares_diluted": 706700000.0, "filed_shares_fy": 2025,
             "shares_default": 70670000.0}
    res = _run_check(0.7067, facts)
    assert res["desk_share_flags"] == ["desk_share_count_far_from_default_10.00x"]
    assert res["desk_share_implausible"] is False
    assert res["desk_share_reason"] is None
    assert res["desk_share_basis_matched"] == "vendor"


def test_the_far_flag_follows_its_neighbours_in_the_list():
    res = _run_check(0.7067, FAR_FACTS, shares_reason="Count from 10-K filing")
    flags = res["desk_share_flags"]
    assert flags[-1] == "desk_share_count_far_from_default_10.00x"
    assert "desk_share_count_mismatch_10.00x" in flags[:-1]


def test_from_text_new_keys():
    # Table with not available cells last
    t1 = (
        "### SECTION 6B - CAPITAL STRUCTURE, DEBT & EQUITY\n"
        "| FY | cash | long-term debt | total liabs | equity | retained earnings | wtd-avg shares |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| 2023 | $1.0B | $0.5B | $1.2B | $0.8B | $0.1B | 100,000,000 |\n"
        "| 2024 | $1.2B | $0.5B | $1.4B | $0.9B | $0.2B | 110,000,000 |\n"
        "| 2025 | $1.5B | $0.5B | $1.6B | $1.0B | $0.3B | not available |\n"
    )
    f1 = pack_facts.from_text(t1)
    assert f1["filed_shares_diluted"] == 110000000.0
    assert f1["filed_shares_fy"] == 2024

    # Table with no share column
    t2 = (
        "### SECTION 6B - CAPITAL STRUCTURE, DEBT & EQUITY\n"
        "| FY | cash | long-term debt | total liabs | equity | retained earnings |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 2024 | $1.0B | $0.5B | $1.2B | $0.8B | $0.1B |\n"
    )
    f2 = pack_facts.from_text(t2)
    assert f2["filed_shares_diluted"] is None
    assert f2["filed_shares_fy"] is None

    # Thousands separators
    t3 = (
        "### SECTION 6B - CAPITAL STRUCTURE, DEBT & EQUITY\n"
        "| FY | cash | long-term debt | total liabs | equity | retained earnings | wtd-avg shares |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| 2025 | $1.0B | $0.5B | $1.2B | $0.8B | $0.1B | 83,383,000 |\n"
    )
    f3 = pack_facts.from_text(t3)
    assert f3["filed_shares_diluted"] == 83383000.0
    assert f3["filed_shares_fy"] == 2025


def test_citation_recognition():
    cited_forms = [
        "10-K", "10-Q", "8-K", "20-F", "6-K", "40-F",
        "DEF 14A", "DEF14A", "S-1", "424B", "424B2",
        "SECTION 6B", "SECTION 2",
    ]
    facts = {
        "shares_outstanding": 100000000.0,
        "filed_shares_diluted": 100000000.0,
        "filed_shares_fy": 2025,
    }
    for form in cited_forms:
        reason = f"Verified count against {form} disclosures"
        res = _run_check(0.12501, facts, shares_reason=reason)
        assert "shares_reason_uncited" not in res["desk_share_flags"], f"Expected {form} to be cited"
        assert "desk_share_count_departure_with_reason" in res["desk_share_flags"]

    uncited_reasons = [
        "Analyst management guidance",
        "Estimated from market cap and stock price",
        "Adjusted for stock splits",
        "SECTION 2.5 shows price action",
    ]
    for reason in uncited_reasons:
        res = _run_check(0.12501, facts, shares_reason=reason)
        assert "shares_reason_uncited" in res["desk_share_flags"], f"Expected {reason!r} to be uncited"
        assert "desk_share_count_departure_with_reason" in res["desk_share_flags"]


def test_band_verdict_copies_desk_share_basis_matched():
    doc = {
        "ticker": "TEST",
        "price": 100.0,
        "model": "test-model",
        "scorecard": {
            "base_iv": 100.0,
            "desk_share_basis_matched": "filed_fy_wa",
        },
        "runs": [
            {
                "sample": 1,
                "iv": 100.0,
                "basis": True,
                "plausible": True,
                "scorecard": {
                    "base_iv": 100.0,
                    "desk_share_basis_matched": "filed_fy_wa",
                },
            }
        ],
    }
    v = dp.band_verdict(doc)
    assert v.get("desk_share_basis_matched") == "filed_fy_wa"
