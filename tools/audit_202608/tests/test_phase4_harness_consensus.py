import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from tools.audit_202608 import analyst_tools as at
from tools.audit_202608.consensus_valuation import (
    extract_desk_snapshot_metrics,
    check_base_cf_default_reason,
    extract_scorecard,
)


class _FakeOllamaResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# S3 A+B (brief §3.2, §3.7): price comes from desk_context now; cash_flow_life and its reason are
# required, given here so the refusal under test stays the missing shares_diluted/sbc_treatment
# one; DESK_BUDGET is unchanged in this test (nothing asserts on its text).
def test_validation_errors_do_not_consume_budget_and_7th_refused(monkeypatch, tmp_path):
    """Validation errors do not consume the 5-call budget and the 7th validation error is refused."""
    # We will simulate 7 consecutive invalid run_financial_model tool calls from the model,
    # followed by a valid report turn.
    turns_payloads = []

    # 7 tool calls omitting required parameters (shares_diluted, sbc_treatment)
    for i in range(7):
        turns_payloads.append({
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_financial_model",
                            "arguments": {
                                "base_cf": 10.0,
                                "growth_rates": [0.05],
                                "fade_years": 0,
                                "wacc": 0.09,
                                "terminal_g": 0.025,
                                "cash_flow_life": "perpetual",
                                "cash_flow_life_reason": "test",
                                "long_run_margin": 0.10,     # revision 24 step 2a: required
                                # missing shares_diluted, sbc_treatment
                            }
                        }
                    }
                ]
            },
            "done_reason": "stop",
            "eval_count": 10,
            "eval_duration": 100_000_000,
        })
    
    # Final memorandum delivery turn
    report_content = "# INSTITUTIONAL MEMORANDUM\n" + ("x" * 6000)
    turns_payloads.append({
        "message": {
            "content": report_content,
            "tool_calls": []
        },
        "done_reason": "stop",
        "eval_count": 500,
        "eval_duration": 1_000_000_000,
    })

    call_count = [0]
    def fake_urlopen(req, timeout=None):
        idx = call_count[0]
        call_count[0] += 1
        payload = turns_payloads[min(idx, len(turns_payloads) - 1)]
        return _FakeOllamaResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    rep, think, meta = at.chat_with_tools("test-model", "test-pack", tmp_path, verbose=False,
                                          desk_context={"price": 100.0})

    # 1. Verification of snapshot calls
    snap_path = tmp_path / "_research_snapshot.json"
    assert snap_path.exists()
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    calls = snap.get("calls", [])
    assert len(calls) == 7

    # Calls 1 to 6 returned validation_error: True
    for c in calls[:6]:
        res = c.get("result") or c
        assert res.get("validation_error") is True
        assert "no silent defaults since Phase 4" in res.get("error", "")

    # Call 7 was refused with budget exhausted message
    call_7 = calls[6]
    res_7 = call_7.get("result") or call_7
    assert "financial model call budget exhausted (5)" in res_7.get("error", "")

    # desk_validation_errors is 7
    assert meta["desk_validation_errors"] == 7


# S3 A+B (brief §3.8 retirement): desk_contract_mismatch:* and _evaluate_contract_mismatches are
# gone (no typed values remain to compare the desk against), so this test's whole subject is
# retired. Replaced with a minimal test that the flag list is always empty and matching still works.
# S3 A+B (fixup Task 3, §7.5 replay): desk_contract_flags itself stays, always empty -- it is not an
# ignored replay key, so its presence (as []) must be identical to the pre-retirement tree.
def test_desk_contract_match_has_no_mismatch_flags_and_matches_nearest_iv():
    """desk_contract_flags is always []; desk_matched_inputs is the candidate nearest base_iv."""
    calls_exact = [
        {
            "tool": "run_financial_model",
            "params": {
                "base_cf": 10.0,
                "explicit_growth": [0.10, 0.08, 0.06],
                "fade_years": 3,
                "wacc": 0.095,
                "shares_diluted": 1.0,
            },
            "result": {
                "dcf_model": {
                    "per_share_iv": 150.0,
                }
            }
        }
    ]
    res_exact = extract_desk_snapshot_metrics(calls_exact, base_iv=150.0, scorecard={})
    assert res_exact["desk_iv_match"] is True
    assert res_exact["desk_contract_flags"] == []
    assert res_exact["desk_matched_inputs"]["base_cf"] == 10.0
    assert res_exact["desk_matched_inputs"]["fade_years"] == 3


def test_share_count_mismatch_thresholds():
    """Share-count mismatch at 1.63x marks sample implausible, at 1.15x flags only, at 1.05x nothing."""
    pack_text = """
## SECTION 2 - CURRENT PRICING & LIQUIDITY
- Current price: $100.00
- Shares outstanding: 1,000,000,000   [source: shares_diluted, vendor share count]
- Market cap: $100.0B
"""
    # 1. 1.63x mismatch (> 25%): 1.63B vs 1.0B
    calls_163 = [
        {
            "tool": "run_financial_model",
            "params": {"shares_diluted": 1.63, "base_cf": 10.0, "wacc": 0.09, "terminal_g": 0.025, "fade_years": 0},
            "result": {"dcf_model": {"per_share_iv": 100.0}}
        }
    ]
    res_163 = extract_desk_snapshot_metrics(calls_163, base_iv=100.0, pack=pack_text)
    assert "desk_share_count_mismatch_1.63x" in res_163["desk_share_flags"]
    assert res_163["desk_share_implausible"] is True
    assert res_163["desk_share_reason"] == "desk share count off by more than 25% (units or omission)"

    # 2. 1.15x mismatch (10-25%): 1.15B vs 1.0B
    calls_115 = [
        {
            "tool": "run_financial_model",
            "params": {"shares_diluted": 1.15, "base_cf": 10.0, "wacc": 0.09, "terminal_g": 0.025, "fade_years": 0},
            "result": {"dcf_model": {"per_share_iv": 100.0}}
        }
    ]
    res_115 = extract_desk_snapshot_metrics(calls_115, base_iv=100.0, pack=pack_text)
    assert "desk_share_count_mismatch_1.15x" in res_115["desk_share_flags"]
    assert res_115["desk_share_implausible"] is False

    # 3. 1.05x mismatch (< 10%): 1.05B vs 1.0B
    calls_105 = [
        {
            "tool": "run_financial_model",
            "params": {"shares_diluted": 1.05, "base_cf": 10.0, "wacc": 0.09, "terminal_g": 0.025, "fade_years": 0},
            "result": {"dcf_model": {"per_share_iv": 100.0}}
        }
    ]
    res_105 = extract_desk_snapshot_metrics(calls_105, base_iv=100.0, pack=pack_text)
    assert res_105["desk_share_flags"] == []
    assert res_105["desk_share_implausible"] is False

    # 4. No shares line in pack: skipped
    res_noshares = extract_desk_snapshot_metrics(calls_163, base_iv=100.0, pack="## SECTION 2\n- Market cap: $100.0B\n")
    assert res_noshares["desk_share_flags"] == []
    assert res_noshares["desk_share_implausible"] is False


def test_base_cf_off_default_without_reason_flag():
    """base_cf_off_default_without_reason fires when off default with no reason, and does not fire otherwise."""
    # 1. Default basis with no reason -> clean (no flag)
    sc_default = {"base_cf_basis": "owner_earnings_default", "base_cf_reason": None}
    assert check_base_cf_default_reason(sc_default) == []

    # 2. Non-default basis with empty reason -> flag fires
    sc_empty_reason = {"base_cf_basis": "latest_fy", "base_cf_reason": ""}
    assert check_base_cf_default_reason(sc_empty_reason) == ["base_cf_off_default_without_reason"]

    # 3. Non-default basis with null/none reason -> flag fires
    sc_null_reason = {"base_cf_basis": "ttm_fcf", "base_cf_reason": "null"}
    assert check_base_cf_default_reason(sc_null_reason) == ["base_cf_off_default_without_reason"]

    # 4. Non-default basis with explanation -> clean (no flag)
    sc_with_reason = {"base_cf_basis": "latest_fy", "base_cf_reason": "FY2025 has normalized capex cycle"}
    assert check_base_cf_default_reason(sc_with_reason) == []

    # 5. Omitted basis -> clean (no flag)
    sc_no_basis = {"base_cf_basis": None, "base_cf_reason": None}
    assert check_base_cf_default_reason(sc_no_basis) == []
