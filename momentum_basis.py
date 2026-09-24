"""momentum_basis.py — E5b momentum basis: riding the trend when value alone says no.

PHASE_4_AMENDMENTS.md E5b. Pure functions, no network, no model.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import rs2_data

THRESHOLDS = {
    "mom_z_universe_min": 0.5,
    "mom_6m_min_exclusive": 0.0,
    "high_52w_distance_min": -0.15,
    "revenue_ttm_yoy_min_exclusive": 0.0,
    "base_iv_to_price_min": 0.5,
}

EXIT = {
    "mom_6m_below": 0.0,
    "high_52w_distance_below": -0.25,
}


def revenue_ttm_yoy(ticker: str) -> float | None:
    """TTM revenue YoY growth for ticker:
    From fundamentals_quarterly.json: sum of revenue over newest 4 quarters / sum over 4 before - 1
    (needs 8 quarters with revenue);
    else from fundamentals_history.json: newest fiscal-year revenue / prior fiscal-year revenue - 1;
    else None.
    """
    t = str(ticker).upper()
    sd = Path(rs2_data.CONFIG["screener_data_dir"])

    # 1. From fundamentals_quarterly.json
    try:
        fq = rs2_data.load_json(sd / "fundamentals_quarterly.json") or {}
        quarters = (fq.get("tickers", {}).get(t) or {}).get("quarters") or []
        if len(quarters) >= 8:
            last_8 = quarters[-8:]
            revs = [q.get("revenue") for q in last_8]
            if all(isinstance(r, (int, float)) for r in revs):
                prior_4 = sum(revs[:4])
                newest_4 = sum(revs[4:])
                if prior_4 > 0:
                    return newest_4 / prior_4 - 1.0
    except Exception:
        pass

    # 2. Fallback to fundamentals_history.json
    try:
        fh = rs2_data.load_json(sd / "fundamentals_history.json") or {}
        hist = fh.get("tickers", {}).get(t) or {}
        valid_years = []
        for y, row in hist.items():
            if str(y).isdigit() and isinstance(row, dict):
                rev = row.get("revenue")
                if isinstance(rev, (int, float)):
                    valid_years.append((int(y), rev))
        valid_years.sort(key=lambda x: x[0])
        if len(valid_years) >= 2:
            prior_rev = valid_years[-2][1]
            newest_rev = valid_years[-1][1]
            if prior_rev > 0:
                return newest_rev / prior_rev - 1.0
    except Exception:
        pass

    return None


def eligibility(
    momentum_state: dict[str, Any] | None,
    revenue_yoy: float | None,
    base_iv: float | None,
    price: float | None,
) -> dict[str, Any]:
    """Evaluate deterministic eligibility for momentum basis over:
    1. mom_z_universe >= 0.5
    2. mom_6m > 0
    3. high_52w_distance >= -0.15
    4. regime_shift_down is not True (None counts as not True)
    5. revenue_ttm_yoy > 0
    6. base_iv / price >= 0.5
    """
    ms = momentum_state if isinstance(momentum_state, dict) else None
    checks = []

    # 1. mom_z_universe >= 0.5
    z_val = ms.get("mom_z_universe") if ms is not None else None
    if z_val is None:
        c1_res = "unknown"
    else:
        c1_res = "pass" if z_val >= THRESHOLDS["mom_z_universe_min"] else "fail"
    checks.append({
        "check": "mom_z_universe",
        "value": z_val,
        "threshold": THRESHOLDS["mom_z_universe_min"],
        "result": c1_res,
    })

    # 2. mom_6m > 0
    m6_val = ms.get("mom_6m") if ms is not None else None
    if m6_val is None:
        c2_res = "unknown"
    else:
        c2_res = "pass" if m6_val > THRESHOLDS["mom_6m_min_exclusive"] else "fail"
    checks.append({
        "check": "mom_6m",
        "value": m6_val,
        "threshold": THRESHOLDS["mom_6m_min_exclusive"],
        "result": c2_res,
    })

    # 3. high_52w_distance >= -0.15
    h52_val = None
    if ms is not None:
        h52_val = ms.get("high_52w_distance")
        if h52_val is None:
            h52_val = ms.get("high_52w_proxy")
    if h52_val is None:
        c3_res = "unknown"
    else:
        c3_res = "pass" if h52_val >= THRESHOLDS["high_52w_distance_min"] else "fail"
    checks.append({
        "check": "high_52w_distance",
        "value": h52_val,
        "threshold": THRESHOLDS["high_52w_distance_min"],
        "result": c3_res,
    })

    # 4. regime_shift_down is not True (None counts as not True)
    if ms is None:
        rsd_val = None
        c4_res = "unknown"
    else:
        rsd_val = ms.get("regime_shift_down")
        if rsd_val is True:
            c4_res = "fail"
        else:
            c4_res = "pass"
    checks.append({
        "check": "regime_shift_down",
        "value": rsd_val,
        "threshold": False,
        "result": c4_res,
    })

    # 5. revenue_ttm_yoy > 0
    if revenue_yoy is None:
        c5_res = "unknown"
    else:
        c5_res = "pass" if revenue_yoy > THRESHOLDS["revenue_ttm_yoy_min_exclusive"] else "fail"
    checks.append({
        "check": "revenue_ttm_yoy",
        "value": revenue_yoy,
        "threshold": THRESHOLDS["revenue_ttm_yoy_min_exclusive"],
        "result": c5_res,
    })

    # 6. base_iv / price >= 0.5
    iv_ratio = None
    if base_iv is not None and price is not None and price > 0:
        iv_ratio = base_iv / price
    if iv_ratio is None:
        c6_res = "unknown"
    else:
        c6_res = "pass" if iv_ratio >= THRESHOLDS["base_iv_to_price_min"] else "fail"
    checks.append({
        "check": "base_iv_to_price",
        "value": iv_ratio,
        "threshold": THRESHOLDS["base_iv_to_price_min"],
        "result": c6_res,
    })

    first_failure = None
    for c in checks:
        if c["result"] != "pass":
            first_failure = c["check"]
            break

    return {
        "eligible": first_failure is None,
        "checks": checks,
        "first_failure": first_failure,
    }


def system_exit(momentum_state: dict[str, Any] | None) -> tuple[bool, str | None]:
    """True when mom_6m < 0 or high_52w_distance < -0.25 (None values never trigger)."""
    if not isinstance(momentum_state, dict):
        return False, None
    m6 = momentum_state.get("mom_6m")
    if m6 is not None and m6 < EXIT["mom_6m_below"]:
        return True, f"mom_6m {m6} < {EXIT['mom_6m_below']}"
    h52 = momentum_state.get("high_52w_distance")
    if h52 is None:
        h52 = momentum_state.get("high_52w_proxy")
    if h52 is not None and h52 < EXIT["high_52w_distance_below"]:
        return True, f"high_52w_distance {h52} < {EXIT['high_52w_distance_below']}"
    return False, None
