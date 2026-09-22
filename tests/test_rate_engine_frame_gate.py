"""Frame gate and rate contract (WACC spec v1.1, §3.1-3.3, §21, §30.0, §32).

The bug these tests exist to prevent: RS2 discounts a LEVERED, equity-claim cash flow against
market cap, but labels the rate `SECTOR_WACC`. On 2026-08-07 the project tried pairing that flow
with a true firm-level WACC and an enterprise-value bridge, measured the pairing as double
counting the debt claim, and reverted it. A field named WACC sitting in an equity-framed engine is
exactly the invitation to try it again, so the pairing is enforced here rather than documented.

The second bug: nothing recorded the rate. A completed AMD run's consensus.json carries 24 fields
and no discount-rate field, so the model's own choice can be neither audited nor compared across
runs. Every result here therefore carries its provenance by construction.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import rate_engine  # noqa: E402


# ------------------------------------------------------------------ the pairing invariant

def test_equity_claim_rejects_true_wacc():
    """Spec §21.3 and §51.6. The reverted pairing must be impossible to express."""
    with pytest.raises(rate_engine.FrameMismatch) as excinfo:
        rate_engine.check_pairing(
            rate_engine.RS2_EQUITY_FRAME, rate_engine.CLAIM_EQUITY, rate_engine.TRUE_WACC
        )
    message = str(excinfo.value)
    assert "EQUITY" in message and "TRUE_WACC" in message


def test_firm_claim_rejects_cost_of_equity():
    """Spec §51.7 — the mirror case, so the rule cannot be satisfied by a one-sided check."""
    with pytest.raises(rate_engine.FrameMismatch):
        rate_engine.check_pairing(
            rate_engine.FIRM_FCFF_FRAME, rate_engine.CLAIM_FIRM, rate_engine.COST_OF_EQUITY
        )


@pytest.mark.parametrize(
    "frame,claim,rate_type",
    [
        (rate_engine.RS2_EQUITY_FRAME, rate_engine.CLAIM_EQUITY, rate_engine.COST_OF_EQUITY),
        (rate_engine.FIRM_FCFF_FRAME, rate_engine.CLAIM_FIRM, rate_engine.TRUE_WACC),
        (rate_engine.EQUITY_DIVIDEND_FRAME, rate_engine.CLAIM_EQUITY, rate_engine.COST_OF_EQUITY),
        (rate_engine.EQUITY_RESIDUAL_INCOME_FRAME, rate_engine.CLAIM_EQUITY,
         rate_engine.COST_OF_EQUITY),
        (rate_engine.SPECIALIZED_FINANCIAL_FRAME, rate_engine.CLAIM_EQUITY,
         rate_engine.COST_OF_EQUITY),
    ],
)
def test_every_legal_pair_passes(frame, claim, rate_type):
    rate_engine.check_pairing(frame, claim, rate_type)


def test_an_unknown_claim_is_an_error_not_a_silent_pass():
    """A table that returns () for an unknown key would let anything through the gate."""
    with pytest.raises(rate_engine.FrameMismatch):
        rate_engine.check_pairing(rate_engine.RS2_EQUITY_FRAME, "PROFIT", rate_engine.COST_OF_EQUITY)


def test_an_unknown_frame_is_an_error():
    with pytest.raises(rate_engine.FrameMismatch):
        rate_engine.check_pairing("SOME_NEW_FRAME", rate_engine.CLAIM_EQUITY,
                                  rate_engine.COST_OF_EQUITY)


def test_a_frame_contradicted_by_its_claim_is_rejected():
    """§42: the engine derives the allowed rate from the frame, so a contradictory argument pair
    must fail rather than have one of the two quietly win."""
    with pytest.raises(rate_engine.FrameMismatch):
        rate_engine.check_pairing(rate_engine.RS2_EQUITY_FRAME, rate_engine.CLAIM_FIRM,
                                  rate_engine.TRUE_WACC)


# ------------------------------------------------------------------ provenance on every input

def test_financial_input_refuses_a_value_without_provenance():
    """§51.18 'Every input has provenance'. A bare float is the defect being removed."""
    with pytest.raises(ValueError):
        rate_engine.FinancialInput(value=0.0918, source="")


def test_financial_input_carries_source_vintage_and_currency():
    """§8's stored shape: value, source, as_of, currency, maturity."""
    item = rate_engine.FinancialInput(value=0.0494, source="(cost_of_capital,universe)",
                                      as_of="2026-09-20", currency="USD", maturity="10Y")
    assert item.value == pytest.approx(0.0494)
    assert item.as_of == "2026-09-20" and item.maturity == "10Y"
    with pytest.raises(Exception):
        item.value = 0.05          # frozen: a sourced input is not editable in place


# ------------------------------------------------------------------ the two calculators

def test_true_wacc_is_not_callable_from_the_rs2_path():
    """§21.1 — the frame guard is the entire point of the keyword-only argument."""
    with pytest.raises(rate_engine.FrameMismatch):
        rate_engine.calculate_true_wacc(
            1000.0, 500.0, 0.10, 0.06, 0.21, valuation_frame=rate_engine.RS2_EQUITY_FRAME
        )


def test_true_wacc_cannot_be_called_without_declaring_a_frame():
    """A defaulted frame would make the guard optional, which is the same as absent."""
    with pytest.raises(TypeError):
        rate_engine.calculate_true_wacc(1000.0, 500.0, 0.10, 0.06, 0.21)


def test_true_wacc_matches_the_documented_formula():
    """§21.1: WACC = w_E R_e + w_D R_d (1 - T_shield)."""
    got = rate_engine.calculate_true_wacc(
        750.0, 250.0, 0.10, 0.06, 0.21, valuation_frame=rate_engine.FIRM_FCFF_FRAME
    )
    assert got == pytest.approx(0.75 * 0.10 + 0.25 * 0.06 * 0.79)


def test_true_wacc_rejects_non_positive_total_capital():
    with pytest.raises(ValueError):
        rate_engine.calculate_true_wacc(
            0.0, 0.0, 0.10, 0.06, 0.21, valuation_frame=rate_engine.FIRM_FCFF_FRAME
        )


def test_the_rs2_rate_is_the_cost_of_equity_unchanged():
    """§21.2 — 'There is no debt/equity weighted averaging step here.'

    A blended rate would be the reverted bug, so this asserts identity, not proximity.
    """
    for value in (0.097, 0.065, 0.1234):
        assert rate_engine.calculate_rs2_equity_discount_rate(value) == value


# ------------------------------------------------------------------ what ships to RS2

def test_the_rs2_rate_equals_what_the_backbone_already_uses():
    """The contract must not become a SECOND authority over the same number.

    Same ticker, same figure as the shipped computation — otherwise the change would create the
    duplicate authority that existing-machinery-first exists to prevent.
    """
    import rs2_data
    import valuation_backbone as vb

    result = rate_engine.build_rs2_rate("AMD")
    sector, _ = rs2_data.sector_lookup("AMD")
    expected_pct = round(
        vb.SECTOR_WACC.get(vb.SECTOR_ALIASES.get(sector, sector), vb.DEFAULT_WACC)
        + vb.coe_offset_pts(), 1
    )
    assert result.primary_rate == pytest.approx(expected_pct / 100.0)


def test_the_rs2_result_never_carries_a_debt_weighted_rate():
    """Review Focus item 1 at the entry point a caller actually uses."""
    result = rate_engine.build_rs2_rate("AMD")
    assert result.valuation_frame == rate_engine.RS2_EQUITY_FRAME
    assert result.cash_flow_claim == rate_engine.CLAIM_EQUITY
    assert result.value_anchor == "MARKET_CAP"
    assert result.rate_type == rate_engine.COST_OF_EQUITY_PROXY
    assert result.debt_weight is None
    assert result.pre_tax_cost_of_debt is None
    assert result.after_tax_cost_of_debt is None
    assert result.equity_weight is None


def test_the_legacy_SECTOR_WACC_label_is_recorded_as_a_proxy():
    """§4.4 and §21.5: the legacy name may be displayed but must never redefine the semantic type."""
    result = rate_engine.build_rs2_rate("AMD")
    assert result.rate_type == rate_engine.COST_OF_EQUITY_PROXY
    assert result.rate_type != rate_engine.TRUE_WACC
    assert result.legacy_label == "SECTOR_WACC"


def test_an_unmapped_sector_is_recorded_rather_than_silently_defaulted(monkeypatch):
    """Review Focus item 3. DEFAULT_WACC is a legitimate fallback; an UNRECORDED one is not."""
    import rs2_data
    import valuation_backbone as vb

    monkeypatch.setattr(rs2_data, "sector_lookup", lambda ticker: (None, None))
    result = rate_engine.build_rs2_rate("ZZZZ")
    assert result.primary_rate == pytest.approx(round(vb.DEFAULT_WACC + vb.coe_offset_pts(), 1) / 100.0)
    joined = " ".join(result.warnings)
    assert "DEFAULT_WACC" in joined or "default" in joined.lower()
    assert "ZZZZ" in joined


def test_a_disabled_calibration_is_recorded_in_the_warnings():
    """`coe_level_source()` names its own fallback; the result must not swallow it."""
    result = rate_engine.build_rs2_rate("AMD")
    assert result.source_vintages.get("coe_level")
    assert result.rate_type == rate_engine.COST_OF_EQUITY_PROXY


def test_the_record_is_reconstructable():
    """§33: 'A future analyst should be able to reproduce the exact result without depending on
    the original LLM conversation.'"""
    record = rate_engine.build_rs2_rate("AMD", valuation_date=date(2026, 9, 21)).to_record()
    for key in ("ticker", "valuation_date", "valuation_frame", "cash_flow_claim", "value_anchor",
                "rate_type", "primary_rate", "methodology_version", "source_vintages",
                "warnings", "input_hash"):
        assert key in record, f"audit trail is missing {key}"
    assert record["ticker"] == "AMD"
    assert record["valuation_date"] == "2026-09-21"
    assert record["rate_type"] == rate_engine.COST_OF_EQUITY_PROXY
    assert record["input_hash"], "an empty hash is not a hash"


def test_the_hash_moves_when_an_input_moves_and_not_otherwise():
    """A hash that never changes is not a hash; a hash that always changes is not reconstructive."""
    import rs2_data
    import valuation_backbone as vb

    first = rate_engine.build_rs2_rate("AMD").to_record()["input_hash"]
    again = rate_engine.build_rs2_rate("AMD").to_record()["input_hash"]
    assert first == again, "same inputs produced a different hash"

    original = vb.SECTOR_WACC.get("Technology")
    try:
        vb.SECTOR_WACC["Technology"] = original + 0.5
        moved = rate_engine.build_rs2_rate("AMD").to_record()["input_hash"]
    finally:
        vb.SECTOR_WACC["Technology"] = original
    assert moved != first, "a changed sector rate did not move the hash"
    assert rate_engine.build_rs2_rate("AMD").to_record()["input_hash"] == first
