#!/usr/bin/env python3
"""pack_data_sanity.py — Data sanity checks for the analyst pack (Charter v3.1 / Phase 4 D9).

Checks:
  1. shares_missing: zero or missing share count.
  2. shares_mismatch: implied shares (marketCap / price) differs from diluted shares by > 10%.
  3. ttm_inconsistent: TTM revenue / OCF / capex disagrees with the sum of the last 4 quarters by > 10%.
"""
from __future__ import annotations

from typing import Any
from pathlib import Path


def _get_num(d: dict, *keys: str) -> float | None:
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (ValueError, TypeError):
                pass
    return None


def check_pack_data_sanity(
    ticker: str | None = None,
    price: float | None = None,
    market_cap: float | None = None,
    diluted_shares: float | None = None,
    ttm_fields: dict[str, Any] | None = None,
    quarterly_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """(warnings: list[dict])

    Evaluates data sanity on share counts and TTM vs quarterly figures.
    Returns a list of warning dicts with the warning name, values, and formatted message.
    """
    warnings: list[dict[str, Any]] = []

    # If inputs not supplied, resolve from screener files if ticker provided
    if ticker and (market_cap is None or price is None or diluted_shares is None or ttm_fields is None or quarterly_rows is None):
        try:
            import rs2_data
            sd = Path(rs2_data.CONFIG["screener_data_dir"])
            if market_cap is None or price is None or diluted_shares is None:
                fin = rs2_data.load_json(sd / "financials" / f"{ticker}.json") or {}
                if market_cap is None:
                    market_cap = _get_num(fin, "Market_Cap", "market_cap")
                if price is None:
                    price = _get_num(fin, "Price", "price")
                if diluted_shares is None:
                    diluted_shares = _get_num(fin, "Shares_Outstanding", "shares_outstanding")
                    h = (rs2_data.load_json(sd / "fundamentals_history.json") or {}).get("tickers", {}).get(ticker) or {}
                    yrs = sorted(int(y) for y in h if str(y).isdigit())
                    if yrs:
                        latest_shares = (h.get(str(max(yrs))) or {}).get("shares_diluted")
                        if latest_shares is not None:
                            diluted_shares = float(latest_shares)
            if ttm_fields is None:
                ttm_rec = (rs2_data.load_json(sd / "fundamentals_ttm.json") or {}).get("tickers", {}).get(ticker) or {}
                ttm_fields = ttm_rec.get("fields") or {}
            if quarterly_rows is None:
                qrec = (rs2_data.load_json(sd / "fundamentals_quarterly.json") or {}).get("tickers", {}).get(ticker) or {}
                quarterly_rows = qrec.get("quarters") or []
        except Exception:
            pass

    # 1. shares_missing
    if diluted_shares is None or diluted_shares <= 0:
        warnings.append({
            "warning": "shares_missing",
            "diluted_shares": diluted_shares,
            "message": "DATA WARNING shares_missing: share count is zero or missing on file",
        })
    else:
        # 2. shares_mismatch (only if shares are present and non-zero)
        if price is not None and price > 0 and market_cap is not None and market_cap > 0:
            implied_shares = market_cap / price
            diff_pct = abs(implied_shares - diluted_shares) / diluted_shares
            if diff_pct > 0.10:
                warnings.append({
                    "warning": "shares_mismatch",
                    "price": price,
                    "market_cap": market_cap,
                    "implied_shares": implied_shares,
                    "diluted_shares": diluted_shares,
                    "diff_pct": round(diff_pct * 100, 2),
                    "message": (
                        f"DATA WARNING shares_mismatch: implied shares (marketCap/price = "
                        f"{implied_shares:,.0f}) differs from pack diluted shares ({diluted_shares:,.0f}) "
                        f"by {diff_pct*100:.1f}% (> 10%)"
                    ),
                })

    # 3. ttm_inconsistent for revenue, OCF, capex
    if ttm_fields and quarterly_rows and len(quarterly_rows) >= 4:
        try:
            sorted_qs = sorted(quarterly_rows, key=lambda q: str(q.get("end", "") or "")) if any("end" in q for q in quarterly_rows) else quarterly_rows
        except Exception:
            sorted_qs = quarterly_rows
        recent_qs = sorted_qs[-4:]
        check_items = [
            ("revenue", ("revenue", "Revenue")),
            ("ocf", ("ocf", "OCF", "operating_cash_flow", "Operating_Cash_Flow")),
            ("capex", ("capex", "Capex", "capital_expenditure", "Capital_Expenditure")),
        ]
        for field_name, aliases in check_items:
            ttm_val = _get_num(ttm_fields, *aliases)
            if ttm_val is None:
                continue

            q_vals = [_get_num(q, *aliases) for q in recent_qs]
            if any(v is None for v in q_vals):
                continue

            q_sum = sum(q_vals)
            denom = abs(ttm_val) if abs(ttm_val) > 0 else 1.0
            diff_pct = abs(q_sum - ttm_val) / denom
            if diff_pct > 0.10:
                warnings.append({
                    "warning": "ttm_inconsistent",
                    "field": field_name,
                    "ttm_value": ttm_val,
                    "quarterly_sum": q_sum,
                    "diff_pct": round(diff_pct * 100, 2),
                    "message": (
                        f"DATA WARNING ttm_inconsistent: TTM {field_name} (${ttm_val/1e9:.3f}B) "
                        f"differs from sum of last 4 quarters (${q_sum/1e9:.3f}B) "
                        f"by {diff_pct*100:.1f}% (> 10%)"
                    ),
                })

    return warnings
