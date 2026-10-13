"""abstention.py - "no view" with a reason (operator O2, 2026-10-12; SPEC_verdict_contract_v4 section 6 (draft); plan B6).

`abstention(...)` turns a company the system cannot value validly into {code, reason}: a published "no view", never a fallback value and never a silent
absence.  The codes:
  family_not_built      a family the engines do not build (commodity, REIT, utility, pre-profit), a company without a Damodaran industry (BDCs), or a
                        financial without a priors growth cell (the market-structure financials of AJ.11 / AK.14)
  engine_refused        the engine names inputs the filings do not supply (its reasons are copied)
  no_share_count        no value per share can be formed (a foreign issuer without a usable count, AK.13)
  no_quarterly_filings  no 10-Q in the 12 months before the date (foreign private issuers)
A technical failure (status `error` and the like) is NOT an abstention: it is `not_usable` (a defect to fix), so it can never hide as a "no view".
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

FAMILY_NOT_BUILT = "family_not_built"
ENGINE_REFUSED = "engine_refused"
NO_SHARE_COUNT = "no_share_count"
NO_QUARTERLY = "no_quarterly_filings"
TECHNICAL = ("error", "model_unavailable", "context_overflow", "request_rejected", "transport_failure")
NOT_BUILT_MARKERS = ("industry_unmapped", "no Damodaran industry", "growth_decay")


def _reasons(reason) -> list:
    if reason is None:
        return []
    return [str(r) for r in reason] if isinstance(reason, (list, tuple)) else [str(reason)]


def abstention(status: str, reason=None, *, family: Optional[str] = None, built_families: Sequence[str] = ("operating", "financial"),
               has_value_per_share: Optional[bool] = None, has_recent_10q: Optional[bool] = None) -> Optional[dict]:
    """{code, reason, reasons} for a company the system abstains on, or None (it is valued, or the failure is technical)."""
    rs = _reasons(reason)
    if status in TECHNICAL:
        return None
    if has_recent_10q is False:
        return {"code": NO_QUARTERLY, "reason": "no 10-Q filed in the 12 months before the date", "reasons": rs}
    if family is not None and family not in built_families:
        return {"code": FAMILY_NOT_BUILT, "reason": f"family {family!r} is not built", "reasons": rs}
    if status in ("refused", "engine_refused", "not_valued"):
        joined = " ".join(rs)
        if status == "not_valued" or any(m in joined for m in NOT_BUILT_MARKERS):
            return {"code": FAMILY_NOT_BUILT, "reason": rs[0] if rs else "not built", "reasons": rs}
        return {"code": ENGINE_REFUSED, "reason": rs[0] if rs else "the engine refused", "reasons": rs}
    if status == "ok" and has_value_per_share is False:
        return {"code": NO_SHARE_COUNT, "reason": "no usable share count: no value per share", "reasons": rs}
    return None
