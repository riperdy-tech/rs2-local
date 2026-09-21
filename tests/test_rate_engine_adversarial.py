"""Adversarial tests for the rate contract.

The first suite (`test_rate_engine_frame_gate.py`) tests the contract on its intended inputs. This
one tries to make it do something it claims it cannot. Four of these tests were written against
behaviour that was WRONG when they were written, so they are regression tests for real defects
found by probing rather than by reading:

  D1  the engine typed its own production rate `COST_OF_EQUITY_PROXY`, which its own pairing
      invariant REFUSED. The contract declared its own output illegal.
  D2  `build_rs2_rate` never called `check_pairing`. The invariant protected `calculate_true_wacc`,
      which nothing calls, while the function that actually ships the rate was ungated — inverted.
  D3  `_FRAME_ANCHOR` was defined and never read; `value_anchor` was hard-coded in the constructor,
      so the table could not constrain it.
  D4  `source_vintages` is a dict inside a frozen dataclass, so a caller could MUTATE it and move
      `input_hash` without changing any input. The audit trail was not tamper-evident.
  D5  `FinancialInput` accepted NaN, inf and even the string "0.05" for `value`. A NaN rate is
      worse than an absent one: it propagates silently and defeats every `<= 0` guard.
  D6  an unhashable claim leaked `TypeError` instead of the documented `FrameMismatch`.
"""
import inspect
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import rate_engine as re_          # noqa: E402


# --------------------------------------------------------------- D1: the contract vs its own output

def test_the_engines_own_output_satisfies_its_own_invariant():
    """D1. The production rate must pass the gate it is subject to.

    Before the fix this raised: COST_OF_EQUITY_PROXY was absent from the allowed set for EQUITY,
    so the engine's own result was illegal by its own rule. A contract that rejects its own output
    is not a contract, and the next person to notice would have been the one adding a second
    exception to silence it.
    """
    result = re_.build_rs2_rate("AMD")
    re_.check_pairing(result.valuation_frame, result.cash_flow_claim, result.rate_type)


def test_a_proxy_rate_is_equity_only_and_never_legal_for_a_firm_claim():
    """The fix for D1 must widen the EQUITY set ONLY. If the proxy type leaked into FIRM, the
    reverted pairing would become expressible again and the gate would be worse than useless."""
    assert re_.COST_OF_EQUITY_PROXY in re_.allowed_rate_types(re_.CLAIM_EQUITY)
    assert re_.COST_OF_EQUITY_PROXY not in re_.allowed_rate_types(re_.CLAIM_FIRM)
    with pytest.raises(re_.FrameMismatch):
        re_.check_pairing(re_.FIRM_FCFF_FRAME, re_.CLAIM_FIRM, re_.COST_OF_EQUITY_PROXY)


# --------------------------------------------------------------- D2: is the gate actually wired?

def test_the_production_entry_point_passes_through_the_gate(monkeypatch):
    """D2. A guard on an unused function is not a guard.

    Behavioural, not introspective: a spy proves `check_pairing` is reached on the shipping path.
    """
    calls = []
    real = re_.check_pairing

    def spy(valuation_frame, cash_flow_claim, rate_type):
        calls.append((valuation_frame, cash_flow_claim, rate_type))
        return real(valuation_frame, cash_flow_claim, rate_type)

    monkeypatch.setattr(re_, "check_pairing", spy)
    re_.build_rs2_rate("AMD")
    assert calls, "build_rs2_rate produced a rate without passing through check_pairing"
    assert calls[0] == (re_.RS2_EQUITY_FRAME, re_.CLAIM_EQUITY, re_.COST_OF_EQUITY_PROXY)


def test_a_wrong_rate_type_cannot_reach_a_caller_from_the_entry_point(monkeypatch):
    """The gate must be able to FIRE on the production path, not merely be present.

    A probe is injected that makes the constructor produce a firm-level rate for the equity frame.
    The entry point must refuse rather than return it — this is the reverted pairing arriving by
    accident instead of by intent.
    """
    real_result = re_.RateResult

    class Sabotaged(real_result):
        pass

    import dataclasses

    def bad(*args, **kwargs):
        kwargs["rate_type"] = re_.TRUE_WACC
        return real_result(*args, **kwargs)

    # Make the constructor lie about the rate type without touching the gate itself.
    monkeypatch.setattr(dataclasses, "replace", dataclasses.replace)
    original = re_.build_rs2_rate.__globals__["RateResult"]
    try:
        re_.build_rs2_rate.__globals__["RateResult"] = bad
        with pytest.raises(re_.FrameMismatch):
            re_.build_rs2_rate("AMD")
    finally:
        re_.build_rs2_rate.__globals__["RateResult"] = original


# --------------------------------------------------------------- D3: the anchor follows the frame

def test_the_value_anchor_is_derived_from_the_frame_not_hard_coded():
    """D3. `_FRAME_ANCHOR` existed but nothing read it.

    A table that constrains nothing is a comment. This asserts the anchor in the result is the one
    the frame's own table prescribes, so a future frame cannot carry the wrong anchor.
    """
    result = re_.build_rs2_rate("AMD")
    assert result.value_anchor == re_._FRAME_ANCHOR[re_.RS2_EQUITY_FRAME]


def test_a_frame_with_the_wrong_anchor_is_refused():
    """And the gate must enforce it, not just expose the table."""
    bad = re_.RateResult(
        ticker="AMD", valuation_date="2026-09-21", valuation_currency="USD",
        valuation_frame=re_.RS2_EQUITY_FRAME, cash_flow_claim=re_.CLAIM_EQUITY,
        value_anchor=re_.VALUE_ANCHOR_ENTERPRISE_VALUE,       # an enterprise anchor on an equity frame
        applicable=True, status="OK", rate_type=re_.COST_OF_EQUITY_PROXY,
    )
    with pytest.raises(re_.FrameMismatch):
        re_.gate_result(bad)


# --------------------------------------------------------------- D4: the audit trail cannot be edited

def test_the_input_hash_cannot_be_moved_by_a_caller():
    """D4. Before the fix, mutating `source_vintages` moved `input_hash` from e8e70ffc... to
    ca5e3735... while every real input stayed put, and the record's own fields then contradicted
    its hash. An audit trail that the audited object can rewrite is not an audit trail."""
    result = re_.build_rs2_rate("AMD")
    before = result.to_record()["input_hash"]
    with pytest.raises(TypeError):
        result.source_vintages["rate_inputs"]["table_rate"] = 999.0
    assert result.to_record()["input_hash"] == before


def test_the_frozen_vintages_are_not_reachable_through_a_nested_dict():
    """A shallow proxy would still expose the inner dict; the freeze must be deep."""
    result = re_.build_rs2_rate("AMD")
    with pytest.raises(TypeError):
        result.source_vintages["rate_inputs"] = {}
    inner = result.source_vintages["rate_inputs"]
    with pytest.raises(TypeError):
        inner["table_rate"] = 999.0


def test_the_record_is_still_plain_json_after_the_freeze():
    """A tamper-evident record that cannot be stored is not an improvement."""
    blob = json.dumps(re_.build_rs2_rate("AMD").to_record())
    assert "RS2_EQUITY_FRAME" in blob


def test_the_hashes_are_deterministic_across_processes():
    """A hash seeded by PYTHONHASHSEED would disagree between runs and destroy change detection."""
    import subprocess

    code = ("import sys; sys.path.insert(0, r'%s'); import rate_engine as r; "
            "print(r.build_rs2_rate('AMD').to_record()['input_hash'])" % str(HERE))
    outputs = set()
    for _ in range(2):
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              cwd=str(HERE))
        if proc.returncode != 0:
            pytest.skip(f"subprocess could not import the module: {proc.stderr[:200]}")
        outputs.add(proc.stdout.strip())
    assert len(outputs) == 1, f"hash is not deterministic across processes: {outputs}"


# --------------------------------------------------------------- D5: a sourced number must be a number

@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf"),
                                       "0.05", None, True, [0.05]])
def test_a_sourced_input_refuses_a_non_finite_or_non_numeric_value(bad_value):
    """D5. `source` was validated and `value` was not, so a NaN rate arrived with full provenance.

    NaN is the worst of these: it propagates through every arithmetic operation, and every
    `<= 0` or `> 0` guard downstream tests False against it, so it survives the checks that exist
    to catch bad numbers. `True` is included because bool is an int subclass and would otherwise
    arrive as 1.0 — a 100% rate.
    """
    with pytest.raises(ValueError):
        re_.FinancialInput(value=bad_value, source="looks legit (2026-09-20)")


def test_a_sourced_input_still_accepts_a_plain_number():
    """The guard must not reject the values it exists to carry."""
    assert re_.FinancialInput(value=0.0494, source="x").value == pytest.approx(0.0494)
    assert re_.FinancialInput(value=5, source="x").value == 5


# --------------------------------------------------------------- D6: refusal has a documented type

@pytest.mark.parametrize("bad", [["EQUITY"], {"EQUITY": 1}, {"EQUITY"}, re_.CLAIM_FIRM.upper()])
def test_an_unhashable_or_odd_claim_refuses_with_the_documented_exception(bad):
    """D6. `in` against a dict raised a bare TypeError for an unhashable argument, which a caller
    catching FrameMismatch would never see. The refusal type is part of the contract.

    A valid claim is deliberately NOT parametrised here: `EQUITY` on the RS2 frame with
    COST_OF_EQUITY is a legal triple and raising for it would be a different bug.
    """
    with pytest.raises(re_.FrameMismatch):
        re_.check_pairing(re_.RS2_EQUITY_FRAME, bad, re_.COST_OF_EQUITY)


def test_an_unhashable_frame_refuses_with_the_documented_exception():
    """M4 of the mutation run. The frame is looked up in a DICT, and dict lookup hashes its key,
    so an unhashable frame raised a bare TypeError - not the exception callers are told to catch.
    The claim guard happened to be tested; this one was not, which is how the hole survived."""
    for bad_frame in (["RS2_EQUITY_FRAME"], {"RS2_EQUITY_FRAME": 1}, {"a", "b"}):
        with pytest.raises(re_.FrameMismatch):
            re_.check_pairing(bad_frame, re_.CLAIM_EQUITY, re_.COST_OF_EQUITY)


def test_an_unhashable_rate_type_refuses_with_the_documented_exception():
    """No guard is needed for this one: membership in a tuple tests equality, not hashing, so the
    ordinary refusal already applies. Pinned anyway, because the refusal TYPE is the contract."""
    with pytest.raises(re_.FrameMismatch):
        re_.check_pairing(re_.RS2_EQUITY_FRAME, re_.CLAIM_EQUITY, ["COST_OF_EQUITY"])


def test_two_names_in_the_same_sector_do_not_share_an_input_hash(monkeypatch):
    """M14 of the mutation run: the ticker was droppable from the hashed inputs and nothing
    noticed. Two names in one sector have identical sector, table rate, offset and level source,
    so without the ticker they share a hash - and the hash stops identifying the result it came
    from, which is the one job it has."""
    import depth_membership
    import rs2_data

    seen = {}
    for ticker in depth_membership._current_book():
        sector_id = rs2_data.mri_sector_id(rs2_data.sector_lookup(ticker)[0])
        if sector_id in seen:
            first = re_.build_rs2_rate(seen[sector_id]).to_record()["input_hash"]
            second = re_.build_rs2_rate(ticker).to_record()["input_hash"]
            assert first != second, (
                f"{ticker} and {seen[sector_id]} share an input hash despite being different names"
            )
            return
        seen[sector_id] = ticker
    pytest.skip("no two book names share a sector")


def test_the_input_hash_moves_when_the_level_source_moves(monkeypatch):
    """M15 of the mutation run: `level_source` was droppable from the hashed inputs.

    It is the disclosure of WHICH evidence set the market level, so a new anchor vintage that
    happens to leave the offset unchanged is still a change of input, and the audit trail must
    register it rather than reporting that nothing moved.
    """
    import valuation_backbone as vb

    before = re_.build_rs2_rate("AMD").to_record()["input_hash"]
    monkeypatch.setattr(vb, "coe_level_source",
                        lambda: "mri_anchor(level=9.18%,asof=2026-10-20)")
    after = re_.build_rs2_rate("AMD").to_record()["input_hash"]
    assert after != before, "a changed level-source vintage did not move the input hash"


def test_a_valid_triple_is_not_refused_by_the_hashability_guard():
    """The guard must not swallow the case it exists to allow."""
    re_.check_pairing(re_.RS2_EQUITY_FRAME, re_.CLAIM_EQUITY, re_.COST_OF_EQUITY)
    re_.check_pairing(re_.RS2_EQUITY_FRAME, re_.CLAIM_EQUITY, re_.COST_OF_EQUITY_PROXY)


# --------------------------------------------------------------- anti-drift across the whole book

def test_every_book_name_gets_the_same_rate_the_shipped_engine_uses():
    """The property that keeps this module from becoming a SECOND authority over one number.

    Delegate-or-duplicate is invisible until the two drift, and they drift silently. This runs the
    comparison over the real book rather than one convenient ticker.
    """
    import rs2_data
    import valuation_backbone as vb

    book = __import__("depth_membership")._current_book()
    mismatches = []
    for ticker in book:
        sector, _ = rs2_data.sector_lookup(ticker)
        table = vb.SECTOR_WACC.get(vb.SECTOR_ALIASES.get(sector, sector), vb.DEFAULT_WACC)
        shipped = round(table + vb.coe_offset_pts(), 1) / 100.0
        got = re_.build_rs2_rate(ticker).primary_rate
        if got != shipped:
            mismatches.append((ticker, got, shipped))
    assert mismatches == [], f"contract and shipped engine disagree: {mismatches[:5]}"


def test_the_frame_tables_agree_with_each_other():
    """`claim_for_frame` is public and was exercised by nothing, so its agreement with the other
    two tables was an untested assumption. A frame whose claim has no legal rate type would make
    every result for that frame unconstructable, and the failure would surface as a confusing
    FrameMismatch on valid input rather than here."""
    for frame, claim in re_._FRAME_CLAIM.items():
        assert re_.claim_for_frame(frame) == claim
        assert re_.allowed_rate_types(claim), f"frame {frame} has no legal rate type"
        assert re_._FRAME_ANCHOR.get(frame), f"frame {frame} has no value anchor"


def test_the_rounding_rule_is_round_to_one_decimal_THEN_divide():
    """Pins the exact rule, because the alternative differs measurably and quietly.

    round(10.75, 1) / 100 = 0.098, while 10.75 / 100 = 0.0975. The shipped engine rounds first; a
    change to either side of that boundary would move every rate in the book by up to 0.05pp and
    nothing else in the suite would notice.
    """
    assert round(11.0 + -1.25, 1) / 100.0 == pytest.approx(0.098)
    assert (11.0 + -1.25) / 100.0 == pytest.approx(0.0975)
    source = inspect.getsource(re_.build_rs2_rate)
    assert "round(table_rate + level_offset_pts, 1)" in source, "the 1dp rounding step is gone"
    assert "rate_pct / 100.0" in source, "the divide now happens before the rounding"
