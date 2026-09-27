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
import depth_pipeline as dp
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
