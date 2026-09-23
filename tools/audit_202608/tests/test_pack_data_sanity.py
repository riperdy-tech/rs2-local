#!/usr/bin/env python3
"""test_pack_data_sanity.py — Unit tests for Phase 4 D9 pack data sanity checks."""
import pytest
from pack_data_sanity import check_pack_data_sanity


def test_shares_missing():
    # None shares
    w_none = check_pack_data_sanity(diluted_shares=None)
    assert any(w["warning"] == "shares_missing" for w in w_none)

    # Zero shares
    w_zero = check_pack_data_sanity(diluted_shares=0)
    assert any(w["warning"] == "shares_missing" for w in w_zero)

    # Negative shares
    w_neg = check_pack_data_sanity(diluted_shares=-100)
    assert any(w["warning"] == "shares_missing" for w in w_neg)


def test_shares_mismatch():
    # Exact match: market_cap = 1000, price = 100 -> implied = 10 shares
    w_clean = check_pack_data_sanity(price=100.0, market_cap=1000.0, diluted_shares=10.0)
    assert not any(w["warning"] == "shares_mismatch" for w in w_clean)

    # 5% difference (within 10% threshold)
    w_within = check_pack_data_sanity(price=100.0, market_cap=1050.0, diluted_shares=10.0)
    assert not any(w["warning"] == "shares_mismatch" for w in w_within)

    # 20% difference (> 10% threshold)
    w_mismatch = check_pack_data_sanity(price=100.0, market_cap=1200.0, diluted_shares=10.0)
    mismatch_warnings = [w for w in w_mismatch if w["warning"] == "shares_mismatch"]
    assert len(mismatch_warnings) == 1
    assert mismatch_warnings[0]["diff_pct"] == 20.0
    assert "DATA WARNING shares_mismatch" in mismatch_warnings[0]["message"]


def test_ttm_consistent():
    ttm_fields = {"revenue": 100_000_000, "ocf": 40_000_000, "capex": 10_000_000}
    quarterly_rows = [
        {"revenue": 25_000_000, "ocf": 10_000_000, "capex": 2_500_000},
        {"revenue": 25_000_000, "ocf": 10_000_000, "capex": 2_500_000},
        {"revenue": 25_000_000, "ocf": 10_000_000, "capex": 2_500_000},
        {"revenue": 25_000_000, "ocf": 10_000_000, "capex": 2_500_000},
    ]
    w = check_pack_data_sanity(
        diluted_shares=100_000,
        price=10.0,
        market_cap=1_000_000,
        ttm_fields=ttm_fields,
        quarterly_rows=quarterly_rows,
    )
    assert not any(w_item["warning"] == "ttm_inconsistent" for w_item in w)


def test_ttm_inconsistent_fields():
    # Revenue off by 20%, OCF off by 30%, capex matches
    ttm_fields = {"revenue": 100_000_000, "ocf": 50_000_000, "capex": 10_000_000}
    quarterly_rows = [
        {"revenue": 20_000_000, "ocf": 8_750_000, "capex": 2_500_000},
        {"revenue": 20_000_000, "ocf": 8_750_000, "capex": 2_500_000},
        {"revenue": 20_000_000, "ocf": 8_750_000, "capex": 2_500_000},
        {"revenue": 20_000_000, "ocf": 8_750_000, "capex": 2_500_000},
    ]
    w = check_pack_data_sanity(
        diluted_shares=100_000,
        price=10.0,
        market_cap=1_000_000,
        ttm_fields=ttm_fields,
        quarterly_rows=quarterly_rows,
    )
    ttm_warns = [x for x in w if x["warning"] == "ttm_inconsistent"]
    warn_fields = {x["field"] for x in ttm_warns}
    assert "revenue" in warn_fields
    assert "ocf" in warn_fields
    assert "capex" not in warn_fields


def test_ttm_insufficient_quarters():
    # Only 3 quarters -> should not trigger ttm_inconsistent
    ttm_fields = {"revenue": 100_000_000}
    quarterly_rows = [
        {"revenue": 25_000_000},
        {"revenue": 25_000_000},
        {"revenue": 25_000_000},
    ]
    w = check_pack_data_sanity(
        diluted_shares=100_000,
        price=10.0,
        market_cap=1_000_000,
        ttm_fields=ttm_fields,
        quarterly_rows=quarterly_rows,
    )
    assert not any(x["warning"] == "ttm_inconsistent" for x in w)
