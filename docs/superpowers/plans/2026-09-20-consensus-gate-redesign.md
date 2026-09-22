# Consensus Gate Redesign: Medoid Anchor & Fiduciary Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the RS2 Consensus Gate and Verdict Engine to eliminate "Frankenstein" independent medians, enforce strict fiduciary mathematical consistency on Section 12 machine contracts, and prevent non-converged runs or lost samples from corrupting the real-money portfolio ledger.

**Architecture:** 
1. `fiduciary_gate.py`: A deterministic validation and sanitization gate that enforces scenario monotonicity ($\text{Bear} \le \text{Base} \le \text{Bull}$), probability simplex normalization ($\sum p_i = 1.0$), non-negative mathematical edge before capital allocation ($\text{Kelly} = 0.0\%$ if expected return $\le 0$), and dollar-cost-averaging tranche discipline ($\text{Starter} \ge \text{Core}$).
2. `consensus_valuation.py`: Replaces independent column medians with the **Medoid (Central Anchor Sample)** selection algorithm. The authoritative Section 12 contract is taken intact from the single sample closest to consensus, while sample variance measures epistemic spread.
3. `depth_pipeline.py`: Replaces naive Base-only band checks with a **Fiduciary Verdict Gate** that blocks unqualified buys when models disagree beyond tolerance (`spread > 25%`), applies penalties for lost samples, and accounts for asymmetric compounder moats.
4. `depth_sanity.py`: Upgraded to audit Section 12 fiduciary coherence, convergence compliance, and sample completeness.

**Tech Stack:** Python 3.11+, pytest, statistics, json, math.

**Spec:** [`docs/Review SKILL.md`](file:///c:/Users/riper/Downloads/RS2%20Local/docs/Review%20SKILL.md) & Audit Findings SR-001 through SR-006.

## Global Constraints

- **Systemic Integrity**: No heuristic band-aids. Mathematical rules must be universally valid across all tickers.
- **Cognitive Primacy with Fiduciary Bounds**: The LLM provides fundamental views; Python deterministically validates that the contract is mathematically coherent before any capital can be allocated.
- **Zero Double Work**: Reuse the mathematical formulas in `financial_model_tool.py` (`continuous_multi_outcome_kelly`, `calculate_payoff_skew`).

---

### Task 1: Fiduciary Contract Validator (`fiduciary_gate.py`)

**Files:**
- Create: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/fiduciary_gate.py`
- Test: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/tests/test_fiduciary_gate.py`

**Interfaces:**
- Produces: `validate_fiduciary_contract(scorecard: dict, price: float) -> tuple[bool, dict, list[str]]`
  - Returns `(is_valid, sanitized_card, issues)`:
    - `is_valid`: True if the scorecard is coherent and usable; False if fatal defects exist (e.g. non-positive Base IV, inverted scenarios $\text{Bear} > \text{Bull}$).
    - `sanitized_card`: Corrected contract where minor floating point drift or un-clamped negative Kelly is repaired deterministically.
    - `issues`: List of warnings or failure reasons.

- [ ] **Step 1: Write unit tests for fiduciary contract validation**

```python
# tools/audit_202608/tests/test_fiduciary_gate.py
import pytest
from tools.audit_202608.fiduciary_gate import validate_fiduciary_contract

def test_valid_coherent_contract():
    card = {
        "base_iv": 1139.78, "bull_iv": 1570.65, "bear_iv": 636.29,
        "base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2,
        "conviction_score": 12.0, "business_quality_moat": 4.3,
        "kelly_fraction_pct": 24.75, "asymmetric_payoff_skew": 1.97,
        "reentry_tranches": {"tranche_1_starter": 951.04, "tranche_2_core": 795.00},
        "thesis_invalidation_trigger": "Backlog declines for 2 quarters."
    }
    is_valid, sanitized, issues = validate_fiduciary_contract(card, price=951.04)
    assert is_valid is True
    assert issues == []
    assert sanitized["base_iv"] == 1139.78
    assert sanitized["asymmetric_payoff_skew"] == 1.97

def test_inverted_scenarios_rejected():
    card = {
        "base_iv": 100.0, "bull_iv": 80.0, "bear_iv": 120.0, # INVERTED!
        "base_probability": 0.5, "bull_probability": 0.3, "bear_probability": 0.2,
    }
    is_valid, sanitized, issues = validate_fiduciary_contract(card, price=100.0)
    assert is_valid is False
    assert any("monotonicity" in i.lower() or "inverted" in i.lower() for i in issues)

def test_negative_edge_clamps_kelly():
    card = {
        "base_iv": 90.0, "bull_iv": 110.0, "bear_iv": 50.0,
        "base_probability": 0.5, "bull_probability": 0.2, "bear_probability": 0.3,
        "kelly_fraction_pct": 8.0, # Hallucinated Kelly on negative return!
    }
    # Expected IV = 0.5*90 + 0.2*110 + 0.3*50 = 45 + 22 + 15 = 82 vs price 100 -> Expected return -18%
    is_valid, sanitized, issues = validate_fiduciary_contract(card, price=100.0)
    assert is_valid is True
    assert sanitized["kelly_fraction_pct"] == 0.0
    assert any("clamped" in i.lower() for i in issues)

def test_tranche_inversion_repaired():
    card = {
        "base_iv": 120.0, "bull_iv": 160.0, "bear_iv": 80.0,
        "reentry_tranches": {"tranche_1_starter": 80.0, "tranche_2_core": 100.0} # Inverted: starter < core
    }
    is_valid, sanitized, issues = validate_fiduciary_contract(card, price=100.0)
    assert is_valid is True
    assert sanitized["reentry_tranches"]["tranche_1_starter"] >= sanitized["reentry_tranches"]["tranche_2_core"]
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tools/audit_202608/tests/test_fiduciary_gate.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'tools.audit_202608.fiduciary_gate')

- [ ] **Step 3: Implement `fiduciary_gate.py`**
Implement validation functions covering:
  - Scenario monotonicity: $\text{Bear} \le \text{Base} \le \text{Bull}$.
  - Probability normalization ($\sum p = 1.0$).
  - Expected return calculation and strict Kelly clamping to $0.0\%$ when edge $\le 0$.
  - Exact payoff skew recalculation: $(Bull - P) / (P - Bear)$.
  - Tranche monotonicity: $\text{Starter} \ge \text{Core}$.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tools/audit_202608/tests/test_fiduciary_gate.py -v`
Expected: PASS (4/4 passed)

---

### Task 2: Medoid Consensus Aggregation (`consensus_valuation.py`)

**Files:**
- Modify: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/consensus_valuation.py:545-585`
- Test: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/tests/test_medoid_consensus.py`

**Interfaces:**
- Consumes: `tools.audit_202608.fiduciary_gate.validate_fiduciary_contract`
- Produces: `select_medoid_scorecard(runs: list[dict], price: float) -> tuple[dict, dict]`
  - Returns `(medoid_scorecard, consensus_summary)`:
    - `medoid_scorecard`: The complete, coherent Section 12 contract from the central anchor sample.
    - `consensus_summary`: Multi-sample metrics (`iv_band_low`, `iv_band_high`, `median_iv`, `spread_pct`, `converged`).

- [ ] **Step 1: Write test for Medoid Anchor selection vs independent medians**

```python
# tools/audit_202608/tests/test_medoid_consensus.py
import pytest
from tools.audit_202608.consensus_valuation import select_medoid_scorecard

def test_medoid_selection_preserves_sample_integrity():
    price = 100.0
    runs = [
        {
            "sample": 1, "iv": 110.0, "plausible": True, "truncated": False,
            "scorecard": {
                "base_iv": 110.0, "bull_iv": 150.0, "bear_iv": 80.0,
                "conviction_score": 11.0, "business_quality_moat": 4.0,
                "kelly_fraction_pct": 12.0, "asymmetric_payoff_skew": 2.50,
                "thesis_invalidation_trigger": "Trigger 1"
            }
        },
        {
            "sample": 2, "iv": 115.0, "plausible": True, "truncated": False,
            "scorecard": {
                "base_iv": 115.0, "bull_iv": 160.0, "bear_iv": 85.0,
                "conviction_score": 12.0, "business_quality_moat": 4.2,
                "kelly_fraction_pct": 14.0, "asymmetric_payoff_skew": 3.00,
                "thesis_invalidation_trigger": "Trigger 2"
            }
        },
        {
            "sample": 3, "iv": 200.0, "plausible": True, "truncated": False, # Outlier
            "scorecard": {
                "base_iv": 200.0, "bull_iv": 300.0, "bear_iv": 90.0,
                "conviction_score": 14.0, "business_quality_moat": 4.5,
                "kelly_fraction_pct": 25.0, "asymmetric_payoff_skew": 20.0,
                "thesis_invalidation_trigger": "Trigger 3"
            }
        }
    ]
    medoid, summary = select_medoid_scorecard(runs, price)
    # The medoid sample should be Sample 2 (closest to median IV $115.0 and median Moat 4.2)
    assert medoid["base_iv"] == 115.0
    assert medoid["bull_iv"] == 160.0
    assert medoid["thesis_invalidation_trigger"] == "Trigger 2"
    assert medoid["kelly_fraction_pct"] == 14.0
    # The summary captures the full 3-sample dispersion
    assert summary["iv_band_low"] == 110.0
    assert summary["iv_band_high"] == 200.0
    assert summary["spread_pct"] == pytest.approx(81.8, 0.1) # (200 - 110) / 110
    assert summary["converged"] is False # 81.8% > 25.0%
```

- [ ] **Step 2: Run test to verify failure**
Run: `python -m pytest tools/audit_202608/tests/test_medoid_consensus.py -v`
Expected: FAIL (ImportError: cannot import name 'select_medoid_scorecard')

- [ ] **Step 3: Implement `select_medoid_scorecard` and integrate into `consensus_valuation.py`**
Update lines 545–585 in `consensus_valuation.py` to validate scorecards with `validate_fiduciary_contract` and select the Medoid sample instead of building independent column medians.

- [ ] **Step 4: Run test to verify PASS**
Run: `python -m pytest tools/audit_202608/tests/test_medoid_consensus.py -v`
Expected: PASS

---

### Task 3: Fiduciary Verdict Gate (`depth_pipeline.py`)

**Files:**
- Modify: `c:/Users/riper/Downloads/RS2 Local/depth_pipeline.py:161-220`
- Test: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/tests/test_fiduciary_verdict_gate.py`

**Interfaces:**
- Produces: Enhanced `band_verdict(doc: dict) -> dict`
  - Gating Rules:
    1. **Strict Non-Convergence Gate**: If `spread_pct > TOL_PCT` (25%), block automatic directional buy. Clamp direction to `"hold"` with reason `"high dispersion (spread > 25%) — model disagreement prohibits capital allocation"` and attach `HIGH_DISPERSION_QUARANTINE` flag.
    2. **Lost-Sample Sizing Penalty**: If `samples_run == 3` but `n_basis == 2` (due to sample loss), clamp `size_hint` to maximum `"half"`.
    3. **Asymmetric Moat Override**: If Price is above Base IV by $\le 10\%$, but Moat $\ge 4.0$, Payoff Skew $\ge 2.0\times$, and Kelly $> 0\%$, do not label `"overvalued"`; label `"hold (asymmetric optionality)"` with starter tranche defined.

- [ ] **Step 1: Write unit tests for Fiduciary Verdict Gate**

```python
# tools/audit_202608/tests/test_fiduciary_verdict_gate.py
import pytest
from depth_pipeline import band_verdict

def test_non_converged_spread_blocks_undervalued_buy():
    # Like DXC: Price 11.07, IVs [17.4, 45.0], spread 158.6% -> Must NOT be "undervalued" buy!
    doc = {
        "ticker": "DXC", "price": 11.07, "samples_run": 3, "converged": False,
        "spread_pct": 158.6, "median_iv": 31.2, "tolerance_pct": 25.0,
        "runs": [
            {"sample": 1, "iv": 17.4, "plausible": True, "truncated": False},
            {"sample": 2, "iv": 45.0, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 17.4, "median_quality_moat": 2.1}
    }
    v = band_verdict(doc)
    assert v["direction"] == "hold"
    assert "high dispersion" in v["reason"].lower() or "quarantine" in v["reason"].lower()
    assert "HIGH_DISPERSION_QUARANTINE" in v["flags"]

def test_lost_sample_caps_size_to_half():
    # Like GTE: 1 sample lost, 2 surviving agree within 11.8% -> Must NOT be "full" size!
    doc = {
        "ticker": "GTE", "price": 10.47, "samples_run": 3, "converged": True,
        "spread_pct": 11.8, "median_iv": 13.2, "early_stop": False,
        "runs": [
            {"sample": 1, "iv": None, "plausible": False, "truncated": True},
            {"sample": 2, "iv": 12.49, "plausible": True, "truncated": False},
            {"sample": 3, "iv": 13.96, "plausible": True, "truncated": False},
        ],
        "scorecard": {"median_iv": 13.2}
    }
    v = band_verdict(doc)
    assert v["direction"] == "undervalued"
    assert v["size_hint"] in ["half", "quarter"]
    assert v["size_hint"] != "full"
```

- [ ] **Step 2: Run test to verify failure**
Run: `python -m pytest tools/audit_202608/tests/test_fiduciary_verdict_gate.py -v`
Expected: FAIL (AssertionError: direction is "undervalued", not "hold")

- [ ] **Step 3: Update `band_verdict()` in `depth_pipeline.py`**
Implement the non-convergence gate, lost-sample penalty, and asymmetric compounder check in `band_verdict()`.

- [ ] **Step 4: Run test to verify PASS**
Run: `python -m pytest tools/audit_202608/tests/test_fiduciary_verdict_gate.py -v`
Expected: PASS

---

### Task 4: Sanity Auditor Upgrade (`depth_sanity.py`)

**Files:**
- Modify: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/depth_sanity.py:85-160`
- Test: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/tests/test_depth_sanity_fiduciary.py`

**Interfaces:**
- Produces: Enhanced `audit(ticker: str, verdict: dict) -> tuple[int, list[str]]`
  - Fails (`level = 2`) if:
    1. Scorecard has broken scenario monotonicity ($\text{Bear} > \text{Bull}$).
    2. Kelly fraction $> 0\%$ when Expected Return $\le 0$ or Base IV < Price.
    3. Verdict is `undervalued` when `spread_pct > TOL_PCT` (violating non-convergence gate).
  - Warns (`level = 1`) if:
    1. Size hint is `full` despite missing/lost samples.

- [ ] **Step 1: Write tests for enhanced sanity audit**

```python
# tools/audit_202608/tests/test_depth_sanity_fiduciary.py
import pytest
from tools.audit_202608.depth_sanity import audit

def test_sanity_fails_on_broken_scorecard_monotonicity():
    verdict = {
        "ticker": "BAD", "price": 100.0, "direction": "undervalued",
        "iv_band_low": 120.0, "iv_band_high": 150.0, "n_basis": 2, "spread_pct": 10.0,
        "scorecard": {
            "median_iv": 130.0, "median_bull_iv": 110.0, "median_bear_iv": 140.0 # BROKEN!
        }
    }
    level, lines = audit("BAD", verdict)
    assert level == 2 # FAIL
    assert any("monotonicity" in l.lower() or "inverted" in l.lower() for l in lines)

def test_sanity_fails_on_unconverged_undervalued_verdict():
    verdict = {
        "ticker": "DXC", "price": 11.07, "direction": "undervalued", # ILLEGAL: spread 158%
        "iv_band_low": 17.4, "iv_band_high": 45.0, "n_basis": 2, "spread_pct": 158.6,
        "flags": ["HIGH_DISPERSION_QUARANTINE"], "scorecard": {"median_iv": 17.4}
    }
    level, lines = audit("DXC", verdict)
    assert level == 2 # FAIL
    assert any("spread" in l.lower() and "undervalued" in l.lower() for l in lines)
```

- [ ] **Step 2: Run test to verify failure**
Run: `python -m pytest tools/audit_202608/tests/test_depth_sanity_fiduciary.py -v`
Expected: FAIL (AssertionError: level is not 2)

- [ ] **Step 3: Update `audit()` in `depth_sanity.py`**
Incorporate fiduciary contract validation and non-convergence gate auditing into `depth_sanity.py`.

- [ ] **Step 4: Run test to verify PASS**
Run: `python -m pytest tools/audit_202608/tests/test_depth_sanity_fiduciary.py -v`
Expected: PASS

---

### Task 5: Full Integration & Regression Sweep

**Files:**
- Run all test suites across the repository:
  `python -m pytest "tools/audit_202608/tests" -v`
- Re-run `depth_sanity.py` across historical ledgers to verify clean detection of past anomalies:
  `python tools/audit_202608/depth_sanity.py --ledger cache/depth_ondemand_ledger.jsonl`

- [x] **Step 1: Run comprehensive test suite** (`python -m pytest "tools/audit_202608/tests" -v` -> 27/27 PASS)
- [x] **Step 2: Verify all tests pass cleanly** (0.70s execution time)
- [x] **Step 3: Update plan document with final verification results**
  - Legacy ledger scan caught GOOG contract failure (Kelly > 0 with Base <= Price).
  - Ondemand ledger scan caught single-sample point estimate on GEV.
  - Active ledger verified BFH as cleanly converged.
