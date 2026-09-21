#!/usr/bin/env python3
"""rate_engine.py — the frame-gated discount-rate contract (WACC spec v1.1, RS2-aligned).

WHY THIS EXISTS. RS2 holds three hand-typed rates and records none of them:
  1. `valuation_backbone.SECTOR_WACC` — a table a human typed, never measured;
  2. `tools/audit_202608/consensus_valuation.py` `wacc = 0.10` — a second, independent literal
     used when checking the model's answer against the analyst band;
  3. the depth tier — the pack supplies a risk-free rate and NO equity risk premium, then tells
     the model to "rigorously derive WACC", so the model invents the premium. Measured, one such
     invented call was worth +30% of the AMD answer against a 25% tolerance.
None of the three is recorded in the run output, so none can be audited or compared across runs.

WHAT THIS MODULE OWNS, AND WHAT IT DOES NOT.
  OWNS: the valuation-frame/claim pairing invariant; the semantic rate type; the shape of a
        sourced input and of the result; the audit record.
  DOES NOT OWN: the rate's arithmetic. It delegates to the shipped primitives
        (`SECTOR_WACC`, `coe_offset_pts()`, `coe_level_source()`) rather than re-deriving them,
        because a second implementation of the same number is a second authority over it.

WHY THE NUMBERS ARE NOT VETTED HERE. Whether ~9.7% is the right level for this book is a
separate, measured question, and the answer was "the level is right, the dispersion is not".
This module makes the existing answer visible and auditable. It does not change it.

DEFERRED, deliberately, each with its own step: renaming the legacy `wacc`/`wacc_pct` fields;
the 12 primary frameworks and 20 overlays (spec §50 Phases 2-5); rewiring
`valuation_backbone.backbone()` to call this module; routing the sourced ERP into the depth
tier's pack; and the FCFE completeness question (spec §4.3 assigns the cash-flow definition to
the valuation engine, not to this one).
"""
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Optional

import rs2_data

METHODOLOGY_VERSION = "1.1.0-rs2"

# ── Valuation frames (spec §3.1). The frame is chosen by the VALUATION engine, before a rate is
# requested, because the correct rate depends on what cash flow is discounted and what claim the
# result is compared against.
RS2_EQUITY_FRAME = "RS2_EQUITY_FRAME"
FIRM_FCFF_FRAME = "FIRM_FCFF_FRAME"
EQUITY_DIVIDEND_FRAME = "EQUITY_DIVIDEND_FRAME"
EQUITY_RESIDUAL_INCOME_FRAME = "EQUITY_RESIDUAL_INCOME_FRAME"
ASSET_PROJECT_FRAME = "ASSET_PROJECT_FRAME"
SPECIALIZED_FINANCIAL_FRAME = "SPECIALIZED_FINANCIAL_FRAME"

# ── Cash-flow claims. This is the axis that decides the rate, not the industry and not the frame
# label, because the claim is what the arithmetic is actually about.
CLAIM_EQUITY = "EQUITY"
CLAIM_FIRM = "FIRM"

# ── Rate types. COST_OF_EQUITY is the real thing; COST_OF_EQUITY_PROXY is the semantic type of
# the legacy `SECTOR_WACC` table, whose name implies a firm-level blend it has never performed.
COST_OF_EQUITY = "COST_OF_EQUITY"
TRUE_WACC = "TRUE_WACC"
COST_OF_EQUITY_PROXY = "COST_OF_EQUITY_PROXY"

VALUE_ANCHOR_MARKET_CAP = "MARKET_CAP"
VALUE_ANCHOR_ENTERPRISE_VALUE = "ENTERPRISE_VALUE"

# ── The pairing invariant (spec §21.3). Keyed by CLAIM, so an unrecognised claim cannot fall
# through to a permissive default: it is absent from this table and therefore an error.
#
# COST_OF_EQUITY_PROXY is legal for an EQUITY claim and ONLY for one. It is not a second kind of
# rate: it is the semantic type of the legacy `SECTOR_WACC` table, which §21.5 says is a
# cost-of-equity proxy. Leaving it out of this set made the engine refuse its own production
# output — the contract declared the rate it ships to be illegal — which is the kind of
# contradiction somebody eventually "fixes" by widening the wrong set.
_ALLOWED_RATE_TYPES = {
    CLAIM_EQUITY: (COST_OF_EQUITY, COST_OF_EQUITY_PROXY),
    CLAIM_FIRM: (TRUE_WACC,),
}

# ── What claim each frame discounts (§3.1's table, as data rather than prose).
_FRAME_CLAIM = {
    RS2_EQUITY_FRAME: CLAIM_EQUITY,
    FIRM_FCFF_FRAME: CLAIM_FIRM,
    EQUITY_DIVIDEND_FRAME: CLAIM_EQUITY,
    EQUITY_RESIDUAL_INCOME_FRAME: CLAIM_EQUITY,
    SPECIALIZED_FINANCIAL_FRAME: CLAIM_EQUITY,
    ASSET_PROJECT_FRAME: CLAIM_EQUITY,
}

_FRAME_ANCHOR = {
    RS2_EQUITY_FRAME: VALUE_ANCHOR_MARKET_CAP,
    FIRM_FCFF_FRAME: VALUE_ANCHOR_ENTERPRISE_VALUE,
    EQUITY_DIVIDEND_FRAME: VALUE_ANCHOR_MARKET_CAP,
    EQUITY_RESIDUAL_INCOME_FRAME: VALUE_ANCHOR_MARKET_CAP,
    SPECIALIZED_FINANCIAL_FRAME: VALUE_ANCHOR_MARKET_CAP,
    ASSET_PROJECT_FRAME: VALUE_ANCHOR_MARKET_CAP,
}

# The RS2 construction, named so the record says what actually happened rather than implying a
# CAPM formula the engine does not use.
RS2_RATE_CONSTRUCTION = "sector_table_rate + market_level_offset"


class FrameMismatch(ValueError):
    """A cash flow was paired with a rate type from a different claim. Never recoverable silently.

    Spec §21.3, §37.1, §51.6-7. The pairing this refuses is the one the project measured and
    reverted on 2026-08-07: a levered equity flow discounted with a firm-level WACC and compared
    against market cap. That combination double counts the debt claim, and it is only ever a
    mistake made to make a number appear, so the failure is loud.
    """


def _hashable(value):
    """Whether a value can be used as a dict key. A list or dict argument cannot, and `in` then
    raises TypeError instead of the refusal this module promises its callers."""
    try:
        hash(value)
    except TypeError:
        return False
    return True


def allowed_rate_types(cash_flow_claim):
    """The rate types this claim may be discounted with, or () if the claim is unknown."""
    return _ALLOWED_RATE_TYPES.get(cash_flow_claim, ())


def claim_for_frame(valuation_frame):
    """The claim a frame discounts, or None if the frame is unknown."""
    return _FRAME_CLAIM.get(valuation_frame)


def check_pairing(valuation_frame, cash_flow_claim, rate_type):
    """Raise FrameMismatch unless this (frame, claim, rate_type) triple is coherent.

    Four checks, all of them refusals rather than coercions: the frame must be known, the claim
    must be known, the frame must actually discount that claim, and the rate type must be legal
    for it. A caller that gets this wrong is told which part is wrong, because the message is the
    only thing that reaches a human reading a failed run.

    Hashability is checked first on each argument: an unhashable one cannot be looked up, and the
    bare TypeError that would otherwise escape is not the exception callers are told to catch.
    """
    if not _hashable(valuation_frame) or valuation_frame not in _FRAME_CLAIM:
        raise FrameMismatch(
            f"unknown or unusable valuation_frame {valuation_frame!r}; the frame must be declared "
            f"before a rate is requested (known: {sorted(_FRAME_CLAIM)})"
        )
    if not _hashable(cash_flow_claim) or cash_flow_claim not in _ALLOWED_RATE_TYPES:
        raise FrameMismatch(
            f"unknown or unusable cash_flow_claim {cash_flow_claim!r}; the claim decides which "
            f"rate types are legal, so an unrecognised one cannot be allowed through (known: "
            f"{sorted(_ALLOWED_RATE_TYPES)})"
        )
    implied = _FRAME_CLAIM[valuation_frame]
    if implied != cash_flow_claim:
        raise FrameMismatch(
            f"frame {valuation_frame} discounts a {implied} claim, but {cash_flow_claim} was "
            f"supplied; the two arguments contradict each other"
        )
    legal = allowed_rate_types(cash_flow_claim)
    # No hashability guard on `rate_type`: membership in a TUPLE tests equality, not hashing, so
    # an unhashable rate type already raises the FrameMismatch below rather than a TypeError.
    # A guard for it was written first and mutation testing proved it could never fire — an
    # unreachable branch that no test can exercise is a branch that rots.
    if rate_type not in legal:
        raise FrameMismatch(
            f"cash_flow_claim {cash_flow_claim} may not be discounted with {rate_type}; "
            f"allowed rate types for {cash_flow_claim}: {list(legal)}. "
            f"Pairing a levered equity flow with a firm-level WACC (or the reverse) changes the "
            f"claim frame and double counts the financing claim."
        )


def gate_result(result):
    """Validate a finished RateResult against the frame it declares, then return it.

    EVERY construction path must return through here. Before this existed the invariant guarded
    only `calculate_true_wacc`, which nothing calls, while `build_rs2_rate` — the function that
    actually produces the shipping rate — was ungated: the check was protecting the unused door.
    Deriving the expected anchor from the frame is also what makes `_FRAME_ANCHOR` load-bearing
    rather than a table nothing consults.
    """
    check_pairing(result.valuation_frame, result.cash_flow_claim, result.rate_type)
    expected_anchor = _FRAME_ANCHOR.get(result.valuation_frame)
    if expected_anchor is not None and result.value_anchor != expected_anchor:
        raise FrameMismatch(
            f"frame {result.valuation_frame} is compared against {expected_anchor}, but the "
            f"result declares {result.value_anchor!r}; the frame decides what the value is "
            f"compared against, and an enterprise anchor on an equity frame is the reverted "
            f"2026-08-07 pairing arriving through the back door."
        )
    return result


@dataclass(frozen=True)
class FinancialInput:
    """One sourced number (spec §8's stored shape, §26's provenance contract, §51.18).

    `source` is REQUIRED and non-empty by construction. A bare float is exactly the defect this
    module exists to remove: it cannot be dated, cannot be traced to a vintage, and cannot be
    distinguished from a value a model made up. `fallback` marks a value that is the engine's own
    constant rather than a measurement, so a defaulted input stays visible in the record.

    `value` is validated too. Provenance on a non-number is not provenance: a NaN rate carries a
    perfect source string, propagates through every arithmetic operation, and tests False against
    every `<= 0` guard downstream, so it survives the checks that exist to catch bad numbers.
    """
    value: float
    source: str
    as_of: Optional[str] = None
    currency: str = "USD"
    maturity: Optional[str] = None
    fallback: bool = False

    def __post_init__(self):
        if not self.source or not str(self.source).strip():
            raise ValueError("a FinancialInput requires a non-empty source (provenance)")
        # bool is an int subclass, so True would otherwise arrive as a 1.0 rate.
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError(
                f"a FinancialInput requires a real number, got {type(self.value).__name__} "
                f"({self.value!r}); valid provenance on a non-number is still not a rate"
            )
        if not math.isfinite(self.value):
            raise ValueError(
                f"a FinancialInput requires a FINITE number, got {self.value!r}"
            )

    def to_record(self):
        return {"value": self.value, "source": self.source, "as_of": self.as_of,
                "currency": self.currency, "maturity": self.maturity, "fallback": self.fallback}


@dataclass(frozen=True)
class RateResult:
    """A rate with its frame, its semantic type and its provenance (spec §32 schema).

    Fields the active frame does not use stay None rather than being zero-filled. A `debt_weight`
    of 0.0 would read as "we measured the capital structure and there is no debt", which is a
    different claim from "this frame has no capital-structure step at all".
    """
    ticker: str
    valuation_date: str
    valuation_currency: str

    valuation_frame: str
    cash_flow_claim: str
    value_anchor: str

    applicable: bool
    status: str
    rate_type: str
    legacy_label: Optional[str] = None
    primary_framework: Optional[str] = None
    rate_framework: Optional[str] = None
    construction: Optional[str] = None

    # ── Sourced inputs. For the RS2 equity frame the risk-free rate and the ERP are provenance
    # for the market LEVEL that the sector offset was anchored to; they are not direct terms in
    # the rate (the construction string above says what the rate actually is).
    risk_free_rate: Optional[FinancialInput] = None
    mature_erp: Optional[FinancialInput] = None
    cost_of_equity: Optional[FinancialInput] = None

    # ── Firm-frame-only inputs. Present in the schema, None in the RS2 equity frame.
    pre_tax_cost_of_debt: Optional[FinancialInput] = None
    tax_shield_rate: Optional[FinancialInput] = None
    after_tax_cost_of_debt: Optional[FinancialInput] = None
    equity_value: Optional[FinancialInput] = None
    debt_value: Optional[FinancialInput] = None
    equity_weight: Optional[float] = None
    debt_weight: Optional[float] = None

    primary_rate: Optional[float] = None
    low_rate: Optional[float] = None
    high_rate: Optional[float] = None

    # Compatibility aliases. These must never redefine the semantic type (§4.4): the legacy name
    # is a LABEL, and the semantic type above is the authority.
    base_wacc: Optional[float] = None

    active_overlays: tuple = ()
    warnings: tuple = ()
    exceptions: tuple = ()

    methodology_version: str = METHODOLOGY_VERSION
    source_vintages: dict = field(default_factory=dict)

    def __post_init__(self):
        # `frozen=True` stops attribute REBINDING, not mutation of a dict reached through an
        # attribute. Without this freeze a caller could edit `source_vintages["rate_inputs"]`,
        # which moves `input_hash` without changing any input and leaves the record's own fields
        # contradicting its hash. An audit trail the audited object can rewrite is not one.
        object.__setattr__(self, "source_vintages", _freeze(self.source_vintages))

    def _inputs(self):
        return {
            "risk_free_rate": self.risk_free_rate.to_record() if self.risk_free_rate else None,
            "mature_erp": self.mature_erp.to_record() if self.mature_erp else None,
            "cost_of_equity": self.cost_of_equity.to_record() if self.cost_of_equity else None,
        }

    def to_record(self):
        """The §33 audit trail: everything needed to reproduce this result without the session.

        The input hash covers the values and sources that PRODUCED the rate, so it moves when any
        of them moves and is stable when none does. The result hash covers the answer itself, so a
        refactor that changes the number without changing the inputs is visible rather than
        silent.
        """
        payload = {
            "ticker": self.ticker.upper(),
            "valuation_date": self.valuation_date,
            "currency": self.valuation_currency,
            "valuation_frame": self.valuation_frame,
            "cash_flow_claim": self.cash_flow_claim,
            "value_anchor": self.value_anchor,
            "applicable": self.applicable,
            "status": self.status,
            "rate_type": self.rate_type,
            "legacy_label": self.legacy_label,
            "primary_framework": self.primary_framework,
            "rate_framework": self.rate_framework,
            "construction": self.construction,
            "primary_rate": self.primary_rate,
            "low_rate": self.low_rate,
            "high_rate": self.high_rate,
            "base_wacc": self.base_wacc,
            "inputs": self._inputs(),
            "debt_weight": self.debt_weight,
            "equity_weight": self.equity_weight,
            "active_overlays": list(self.active_overlays),
            "warnings": list(self.warnings),
            "exceptions": list(self.exceptions),
            "methodology_version": self.methodology_version,
            "source_vintages": _thaw(self.source_vintages),
        }
        rate_inputs = _thaw(self.source_vintages.get("rate_inputs") or {})
        payload["input_hash"] = _hash({"ticker": self.ticker.upper(), **rate_inputs})
        payload["result_hash"] = _hash({"rate_type": self.rate_type,
                                        "primary_rate": self.primary_rate})
        return payload


def _freeze(value):
    """Deep, read-only view of a plain-data structure (dicts, lists, tuples, scalars).

    Called on `source_vintages` at construction. Deep on purpose: a shallow MappingProxyType over
    an outer dict still hands out the inner dict, which is the one that carries `rate_inputs`.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value):
    """The inverse of `_freeze`, so the record stays plain JSON (an audit trail that cannot be
    stored is not an audit trail)."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def _hash(payload):
    """Short, stable, order-independent digest of a dict."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def calculate_true_wacc(equity_value, debt_value, cost_of_equity, pre_tax_cost_of_debt,
                        tax_shield_rate, *, valuation_frame):
    """WACC = w_E R_e + w_D R_d (1 - T_shield). Firm/unlevered frames ONLY.

    Spec §21.1: the frame is a REQUIRED keyword with no default, so this cannot be reached from
    the RS2 equity path by omission — a defaulted frame would make the guard optional, which is
    the same as absent. Available for a future FIRM_FCFF_FRAME model; not wired to anything today.
    """
    check_pairing(valuation_frame, CLAIM_FIRM, TRUE_WACC)
    total_capital = equity_value + debt_value
    if total_capital <= 0:
        raise ValueError("Total capital must be positive")
    equity_weight = equity_value / total_capital
    debt_weight = debt_value / total_capital
    return (equity_weight * cost_of_equity
            + debt_weight * pre_tax_cost_of_debt * (1.0 - tax_shield_rate))


def calculate_rs2_equity_discount_rate(cost_of_equity):
    """The RS2 equity-frame rate. Spec §21.2: it IS the cost of equity — no averaging step.

    Deliberately a function rather than an identity so the frame rule has a name, and deliberately
    not a no-op that some future hand might "improve" into a blend. The economics were settled
    upstream: net income is after-interest, the flow is an equity claim, market cap is an equity
    claim value, so the rate is the cost of equity.
    """
    return cost_of_equity


def _rs2_primitives():
    """The shipped rate primitives, imported LATE and on purpose.

    They live in valuation_backbone today. When backbone is rewired to call this module (a
    deferred step), a module-level import here would be a cycle; a function-local one is not.
    Importing them at all, rather than re-deriving the offset, is what keeps this module from
    becoming a second authority over the same number.
    """
    import valuation_backbone as vb
    return vb


def build_rs2_rate(ticker, valuation_date=None, currency="USD"):
    """The RS2 equity-frame rate for one ticker, with its provenance, as a RateResult.

    Uses the same two terms the shipped `backbone()` uses — the sector table rate plus the
    market-anchored level offset — and produces the same number to the same rounding, so adopting
    this contract does not move any valuation. Every source, every fallback and the construction
    itself travel in the result.
    """
    vb = _rs2_primitives()
    ticker = str(ticker).upper()
    when = valuation_date or date.today()
    when_iso = when.isoformat() if hasattr(when, "isoformat") else str(when)

    warnings = []

    sector, _industry = rs2_data.sector_lookup(ticker)
    table_rate = vb.SECTOR_WACC.get(vb.SECTOR_ALIASES.get(sector, sector))
    sector_fallback = table_rate is None
    if sector_fallback:
        table_rate = vb.DEFAULT_WACC
        warnings.append(
            f"{ticker}: sector lookup returned {sector!r}, which is not in the rate table; "
            f"using DEFAULT_WACC={vb.DEFAULT_WACC}. A defaulted sector rate is recorded because "
            f"an unrecorded one is indistinguishable from a measured one."
        )

    level_offset_pts = vb.coe_offset_pts()
    level_source = vb.coe_level_source()
    if "calibration_not_applicable" in level_source or "raw_sector_table" in level_source:
        warnings.append(
            f"{ticker}: the market level anchor is unusable ({level_source}); the raw sector "
            f"table is in force with a zero offset. A stale anchor changes nothing, as designed."
        )

    rate_pct = round(table_rate + level_offset_pts, 1)
    primary_rate = rate_pct / 100.0

    # The modelled components, recorded as provenance for the market LEVEL. Absent is absent.
    rf_value, rf_source = rs2_data.anchor_risk_free_rate()
    erp_value, erp_source = rs2_data.anchor_mature_erp()
    rf_input = (FinancialInput(value=rf_value, source=rf_source, currency=currency, maturity="10Y")
                if rf_value is not None else None)
    erp_input = FinancialInput(value=erp_value, source=erp_source, currency=currency) \
        if erp_value is not None else None

    construction = (f"{RS2_RATE_CONSTRUCTION}: sector {sector!r} table "
                    f"{table_rate:.1f}% + level offset {level_offset_pts:+.1f}pts = {rate_pct:.1f}%")

    cost_of_equity = FinancialInput(value=primary_rate, source=level_source, as_of=when_iso)

    result = RateResult(
        ticker=ticker,
        valuation_date=when_iso,
        valuation_currency=currency,
        valuation_frame=RS2_EQUITY_FRAME,
        cash_flow_claim=CLAIM_EQUITY,
        value_anchor=_FRAME_ANCHOR[RS2_EQUITY_FRAME],
        applicable=True,
        status="OK",
        rate_type=COST_OF_EQUITY_PROXY,
        legacy_label="SECTOR_WACC",
        rate_framework="SECTOR_TABLE_PLUS_MARKET_LEVEL_OFFSET",
        construction=construction,
        risk_free_rate=rf_input,
        mature_erp=erp_input,
        cost_of_equity=cost_of_equity,
        primary_rate=primary_rate,
        warnings=tuple(warnings),
        source_vintages={
            "coe_level": level_source,
            "sector_fallback": str(sector_fallback).lower(),
            # The values the input hash is computed over. Only what produced the rate belongs
            # here; a date that moves daily would make the hash useless for change detection.
            "rate_inputs": {"sector": sector, "table_rate": table_rate,
                            "level_offset_pts": level_offset_pts, "level_source": level_source},
        },
    )
    return gate_result(result)
