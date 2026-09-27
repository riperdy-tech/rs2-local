"""Reviewer's tests for brief S2b (2026-09-28), one per defect fixed at review.

1. A shares_reason attached to SECTION 2's own count is not a departure: no
   `desk_share_count_departure_with_reason`, no `shares_reason_uncited`.
2. SECTION 6B's reader takes only year rows (a four-digit fiscal year in the first cell); it never
   digs digits out of another first cell. The build side sets `filed_shares_fy` from an int year.
3. `extract_scorecard`'s whitelist is the model's output schema. A harness-computed field such as
   `desk_share_basis_matched` stays out of it, arriving through `scorecard.update(desk_info)`.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import consensus_valuation as cv  # noqa: E402
import pack_facts  # noqa: E402


def _check(desk_shares_b, facts, shares_reason=None):
    snapshot = [{
        "tool": "run_financial_model",
        "params": {"shares_diluted": desk_shares_b, "base_cf": 1.0, "explicit_growth": [0.1],
                   "fade_years": 5, "wacc": 0.10},
        "result": {"dcf_model": {"per_share_iv": 50.0}},
    }]
    sc = {"shares_reason": shares_reason} if shares_reason is not None else {}
    return cv.extract_desk_snapshot_metrics(snapshot=snapshot, base_iv=50.0, scorecard=sc, facts=facts)


FACTS = {"shares_outstanding": 61443377.0, "filed_shares_diluted": 83383000.0, "filed_shares_fy": 2025}


def test_reason_on_vendor_count_is_not_a_departure():
    res = _check(0.061443377, FACTS, shares_reason="Uses SECTION 2's count; no contingent instrument vests.")
    assert res["desk_share_basis_matched"] == "vendor"
    assert "desk_share_count_departure_with_reason" not in res["desk_share_flags"]
    assert "shares_reason_uncited" not in res["desk_share_flags"]
    assert res["desk_share_implausible"] is False


def test_uncited_reason_on_vendor_count_is_not_flagged():
    res = _check(0.0615, FACTS, shares_reason="analyst judgement")
    assert res["desk_share_basis_matched"] == "vendor"
    assert res["desk_share_flags"] == []


def test_reason_on_filed_count_is_a_departure():
    res = _check(0.0834, FACTS, shares_reason="SECTION 6B filed diluted count, 10-Q")
    assert res["desk_share_basis_matched"] == "filed_fy_wa"
    assert "desk_share_count_departure_with_reason" in res["desk_share_flags"]
    assert "shares_reason_uncited" not in res["desk_share_flags"]


SIXB = (
    "### SECTION 6B - CAPITAL STRUCTURE, DEBT & EQUITY\n"
    "| FY | cash | long-term debt | total liabs | equity | retained earnings | wtd-avg shares |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
    "| 2024 | $0.171B | $0.224B | $0.689B | $0.805B | $0.507B | 84,448,000 |\n"
    "| 2025 | $0.470B | $0.518B | $0.926B | $1.025B | $0.613B | 83,383,000 |\n"
    "| FY2026E | x | x | x | x | x | 90,000,000 |\n"
    "| avg 3y | x | x | x | x | x | 12,345 |\n")


def test_6b_reader_takes_year_rows_only():
    f = pack_facts.from_text(SIXB)
    assert f["filed_shares_diluted"] == 83383000.0
    assert f["filed_shares_fy"] == 2025
    assert isinstance(f["filed_shares_fy"], int)


def test_6b_reader_none_without_year_rows():
    t = SIXB.split("| 2024 |")[0] + "| FY2026E | x | x | x | x | x | 90,000,000 |\n"
    f = pack_facts.from_text(t)
    assert f["filed_shares_diluted"] is None and f["filed_shares_fy"] is None


def test_harness_field_not_in_model_schema():
    card = cv.extract_scorecard("", 10.0)
    assert "desk_share_basis_matched" not in card
