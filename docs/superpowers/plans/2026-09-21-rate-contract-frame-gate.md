# Frame-Gated Rate Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give RS2 a single, frame-gated source of truth for its discount rate, with every input sourced, dated and recorded — replacing three hand-typed rates and a rate that is currently recorded nowhere.

**Architecture:** A new flat module `rate_engine.py` owns rate construction and the frame/claim pairing invariant. It CONSUMES RS2's existing machinery (`SECTOR_WACC`, `coe_offset_pts()`, `SECTOR_ALIASES`, `DEFAULT_WACC`) rather than reimplementing the arithmetic, so there is exactly one owner of the rate. Two missing sourced accessors (`risk_free_rate`, `mature_erp`) are added to `rs2_data.py`, which already owns anchor consumption. Nothing in `valuation_backbone.py` is renamed or rewired in this plan.

**Tech Stack:** Python 3.12 standard library only (`dataclasses`, `datetime`), pytest. No new dependencies.

**Spec:** `C:\Users\riper\Downloads\Stock Screener\docs\WACC_ENGINE_SPEC_v1.1_RS2_ALIGNED.md`
This plan implements §0 (two frame modes), §3.1–3.3 (valuation frame gate), §14–15 (Rf and ERP engines), §17.3 (RS2 equity-frame rule), §21.1–21.5 (frame-gated calculation), §30.0 (LLM prohibition), §32 (rate result schema), §33 (audit trail), §50 Phase 1.

## Status

**Tasks 1–6 implemented and verified** (2026-09-21). 78 tests pass; 135 book names checked with zero
disagreement against the shipped rate. Delivered: `rs2_data.anchor_risk_free_rate()`,
`rs2_data.anchor_mature_erp()`, `rate_engine.py`, `tests/test_rate_engine_frame_gate.py`, five new
tests in `tests/test_anchor_consumption.py`. Verification harness:
`scratch/verify_rate_engine_equivalence.py`.

Two deviations from the plan as written, both recorded rather than quietly taken:
1. The plan's Task 5 asserted a `RateResult.fallback` boolean. The spec's §32 schema has no such
   field, and adding one beside `warnings` would be a duplicate authority — so `fallback` was NOT
   added, and the fallback is reported through `warnings` and `source_vintages["sector_fallback"]`.
   The spec is the authority; the plan is subordinate to it.
2. The plan's Task 1 proposed a new `anchor_dir_coc` fixture. The existing test file writes
   cost-of-capital payloads inline, so a local `_cost_of_capital_payload` helper follows that
   established pattern instead of introducing a second convention.

Steps below are left unticked: the plan's step boxes track execution order, and this work was
executed as whole tasks rather than step-by-step. Per-task commits were deliberately NOT made — the
repository already carried uncommitted work from an earlier session and mixing it into a commit
would have been worse than leaving the working tree dirty for the operator to decide.

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include this section.

- Frames (§3.1): `RS2_EQUITY_FRAME`, `FIRM_FCFF_FRAME`, `EQUITY_DIVIDEND_FRAME`, `EQUITY_RESIDUAL_INCOME_FRAME`, `ASSET_PROJECT_FRAME`, `SPECIALIZED_FINANCIAL_FRAME`
- Pairing invariant (§21.3): `cash_flow_claim == EQUITY` → `allowed_rate_types = {COST_OF_EQUITY}`; `cash_flow_claim == FIRM` → `allowed_rate_types = {TRUE_WACC}`; any other pairing is a hard error
- (§21.1) `calculate_true_wacc` "MUST require an explicit `valuation_frame="FIRM_FCFF_FRAME"` … A low-level convenience function must not be callable from the RS2 equity valuation path without a frame guard."
- (§21.2) RS2 equity rate `= cost_of_equity`. "There is **no** debt/equity weighted averaging step here."
- (§21.5, §4.4) legacy label `SECTOR_WACC` → semantic type `COST_OF_EQUITY_PROXY`. Compatibility aliases "must never redefine semantic type".
- (§30.0, §30) The LLM may not invent Rf, ERP, beta, credit spreads or tax rates; the LLM never directly edits the numerical rate (§51.17).
- (§15.3) All companies valued on the same valuation date use the same approved mature-market ERP vintage.
- (§51.6, §51.7) The engine must hard-reject equity cash flow + true WACC, and FCFF + cost of equity.
- (§51.9) Do not reintroduce the reverted 2026-08-07 RS2 firm-WACC/enterprise-value pairing.
- RS2 `config.json`: `anchor_max_age_days = 45`; `anchors_dir = C:/Users/riper/Downloads/Stock Screener/Macro Regime Indicator/outputs`
- Existing RS2 discipline (from `config.json` `_anchors_note`): "A missing, stale, degraded or unreadable anchor changes NOTHING." No substituted default; the absence is disclosed.

## Review Focus

The five conditions most likely to bite a user of this code. Each gets a test in the task that owns the code.

1. **A contradictory claim/rate pairing arrives.** A caller passes `cash_flow_claim=FIRM` with a cost-of-equity rate, or EQUITY with a true WACC, intending to "just get a number". Expected: hard refusal naming the mismatch — never a coerced or averaged value.
2. **An anchor is missing, stale or degraded.** Expected: the rate falls back to RS2's raw sector table, the absence is recorded by name in the output, and no default is substituted for a missing Rf or ERP.
3. **A ticker's sector is unmapped or absent.** Expected: `DEFAULT_WACC` applies AND the record says the sector lookup fell back, so a silently-defaulted rate is auditable.
4. **Units are mixed.** RS2's existing `anchor_level_cost_of_equity_pct()` returns PERCENT (9.18) while `anchor_terminal_g()` returns a FRACTION (0.035). A new accessor that follows the wrong neighbour produces a rate 100x out. Expected: each accessor's unit is pinned by an assertion against the real payload.
5. **A foreign name is valued.** Several book names are non-US (PBR, VLRS, HAFN, QFIN, FINV, WB, YALA, TIGR, JKS, ESBA). Expected: no country-risk premium is added silently, and if one ever is, the record shows it is not double-counted with the ERP (§37.4).

---

### Task 1: Sourced risk-free rate and mature ERP accessors

**Files:**
- Modify: `rs2_data.py` (add two functions immediately after `anchor_level_cost_of_equity_pct`, ~L1028)
- Test: `tests/test_anchor_consumption.py` (the existing home of anchor-consumption tests)

**Interfaces:**
- Consumes: `rs2_data.usable_anchor("cost_of_capital")`, the payload's `risk_free.nominal_10y` and `implied_erp` fields
- Produces: `anchor_risk_free_rate() -> (float | None, str)` and `anchor_mature_erp() -> (float | None, str)`, both returning a FRACTION (e.g. `0.0494`), or `(None, reason)`. The reason string must name the failure (`no_usable_cost_of_capital_anchor`, `anchor_has_no_risk_free`, `anchor_has_no_implied_erp`).

- [ ] **Step 1: Write the failing test**

```python
def test_risk_free_and_erp_are_fractions_from_the_cost_of_capital_anchor(anchor_dir_coc):
    """Unit is the trap: the sibling accessor returns PERCENT, terminal_g returns a FRACTION.
    Pinned against the real payload shape, so a future unit drift fails loudly."""
    rf, rf_src = rs2_data.anchor_risk_free_rate()
    erp, erp_src = rs2_data.anchor_mature_erp()
    assert rf == pytest.approx(0.0494)
    assert erp == pytest.approx(0.0424)
    assert "cost_of_capital" in rf_src
    assert "cost_of_capital" in erp_src


def test_missing_anchor_returns_none_not_a_default(tmp_path, monkeypatch):
    monkeypatch.setitem(rs2_data.CONFIG, "anchors_dir", str(tmp_path))
    monkeypatch.setattr(rs2_data, "_ANCHOR_CACHE", None)
    rf, rf_src = rs2_data.anchor_risk_free_rate()
    assert rf is None
    assert rf_src == "no_usable_cost_of_capital_anchor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_anchor_consumption.py -k "risk_free" -v`
Expected: FAIL with `AttributeError: module 'rs2_data' has no attribute 'anchor_risk_free_rate'`

- [ ] **Step 3: Implement the minimal accessors**

Mirror `anchor_level_cost_of_equity_pct()`'s structure exactly: `usable_anchor` gate, then read the field, then return `(None, reason)` rather than a default. Convert to a fraction with `float(...)`, and return `None` for a non-positive/non-numeric value.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python -m pytest tests/test_anchor_consumption.py -v`

- [ ] **Step 5: Commit**

---

### Task 2: Frame and claim vocabulary, and the pairing invariant

**Files:**
- Create: `rate_engine.py`
- Test: `tests/test_rate_engine_frame_gate.py`

**Interfaces:**
- Produces: module constants `RS2_EQUITY_FRAME`, `FIRM_FCFF_FRAME`, `EQUITY_DIVIDEND_FRAME`, `EQUITY_RESIDUAL_INCOME_FRAME`, `ASSET_PROJECT_FRAME`, `SPECIALIZED_FINANCIAL_FRAME`; `CLAIM_EQUITY`, `CLAIM_FIRM`; `COST_OF_EQUITY`, `TRUE_WACC`, `COST_OF_EQUITY_PROXY`; `class FrameMismatch(ValueError)`; `check_pairing(valuation_frame, cash_flow_claim, rate_type) -> None` raising `FrameMismatch`.

- [ ] **Step 1: Write the failing test**

```python
def test_equity_claim_rejects_true_wacc():
    """Spec §21.3 / §51.6. The reverted 2026-08-07 pairing must be impossible to express."""
    with pytest.raises(rate_engine.FrameMismatch) as e:
        rate_engine.check_pairing(rate_engine.RS2_EQUITY_FRAME, "EQUITY", rate_engine.TRUE_WACC)
    assert "EQUITY" in str(e.value) and "TRUE_WACC" in str(e.value)


def test_firm_claim_rejects_cost_of_equity():
    """Spec §51.7 — the mirror case."""
    with pytest.raises(rate_engine.FrameMismatch):
        rate_engine.check_pairing(rate_engine.FIRM_FCFF_FRAME, "FIRM", rate_engine.COST_OF_EQUITY)


def test_the_two_legal_pairs_pass():
    rate_engine.check_pairing(rate_engine.RS2_EQUITY_FRAME, "EQUITY", rate_engine.COST_OF_EQUITY)
    rate_engine.check_pairing(rate_engine.FIRM_FCFF_FRAME, "FIRM", rate_engine.TRUE_WACC)
```

- [ ] **Step 2: Run test to verify it fails** — `python -m pytest tests/test_rate_engine_frame_gate.py -v` → `ModuleNotFoundError: rate_engine`

- [ ] **Step 3: Implement** the constants and a `check_pairing` that derives the allowed rate types FROM the claim (a table), so an unknown claim is itself an error rather than a silent pass.

- [ ] **Step 4: Run the tests** — all pass.

- [ ] **Step 5: Commit**

---

### Task 3: `FinancialInput` and `RateResult` with provenance

**Files:**
- Modify: `rate_engine.py`
- Test: `tests/test_rate_engine_frame_gate.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class FinancialInput(value: float, source: str, as_of: str | None = None, currency: str = "USD", maturity: str | None = None, fallback: bool = False)`; `@dataclass(frozen=True) class RateResult` carrying the §32 field set, with `primary_rate`, `rate_type`, `valuation_frame`, `cash_flow_claim`, `value_anchor`, `warnings`, `source_vintages`; and `RateResult.to_record() -> dict` for the §33 audit trail.

- [ ] **Step 1: Write the failing test**

```python
def test_financial_input_refuses_a_value_without_provenance():
    """§51.18 'Every input has provenance'. A bare float is exactly the defect being removed."""
    with pytest.raises(ValueError):
        rate_engine.FinancialInput(value=0.0918, source="")


def test_to_record_carries_the_frame_and_the_vintages():
    res = _a_result()                      # built by the helper below, in this same test module
    rec = res.to_record()
    for key in ("valuation_frame", "cash_flow_claim", "value_anchor", "rate_type",
                "primary_rate", "source_vintages", "methodology_version"):
        assert key in rec
    assert rec["rate_type"] == rate_engine.COST_OF_EQUITY_PROXY
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement** the dataclasses. `FinancialInput.__post_init__` raises on an empty source. `to_record()` returns a JSON-serialisable dict keyed exactly as §33 lists.
- [ ] **Step 4: Run the tests**
- [ ] **Step 5: Commit**

---

### Task 4: The two calculators, each frame-guarded

**Files:**
- Modify: `rate_engine.py`
- Test: `tests/test_rate_engine_frame_gate.py`

**Interfaces:**
- Produces: `calculate_true_wacc(equity_value, debt_value, cost_of_equity, pre_tax_cost_of_debt, tax_shield_rate, *, valuation_frame) -> float` raising `FrameMismatch` unless `valuation_frame == FIRM_FCFF_FRAME`; `calculate_rs2_equity_discount_rate(cost_of_equity) -> float` returning it unchanged, with no averaging step.

- [ ] **Step 1: Write the failing test**

```python
def test_true_wacc_is_not_callable_from_the_rs2_path():
    """Spec §21.1 — the guard is the whole point of the function signature."""
    with pytest.raises(rate_engine.FrameMismatch):
        rate_engine.calculate_true_wacc(1000.0, 500.0, 0.10, 0.06, 0.21,
                                        valuation_frame=rate_engine.RS2_EQUITY_FRAME)


def test_rs2_rate_is_the_cost_of_equity_unchanged():
    """§21.2 — no weighted averaging. A blended rate would be the reverted bug."""
    assert rate_engine.calculate_rs2_equity_discount_rate(0.097) == 0.097


def test_true_wacc_matches_the_documented_formula():
    got = rate_engine.calculate_true_wacc(750.0, 250.0, 0.10, 0.06, 0.21,
                                          valuation_frame=rate_engine.FIRM_FCFF_FRAME)
    assert got == pytest.approx(0.75 * 0.10 + 0.25 * 0.06 * 0.79)
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement**, including the `total_capital <= 0` → `ValueError` from §21.1.
- [ ] **Step 4: Run the tests**
- [ ] **Step 5: Commit**

---

### Task 5: `build_rs2_rate` — the single owner of the RS2 rate

**Files:**
- Modify: `rate_engine.py`
- Test: `tests/test_rate_engine_frame_gate.py`

**Interfaces:**
- Consumes: `valuation_backbone.SECTOR_WACC`, `SECTOR_ALIASES`, `DEFAULT_WACC`, `coe_offset_pts()`, `coe_level_source()`, `rs2_data.sector_lookup()`; Task 1's accessors
- Produces: `build_rs2_rate(ticker, valuation_date=None, currency="USD") -> RateResult`, with `rate_type=COST_OF_EQUITY_PROXY`, `primary_rate` equal to the same number `valuation_backbone.backbone()` would use, `fallback=True` on the sector-table fallback, and `source_vintages` naming the anchor asof dates.

- [ ] **Step 1: Write the failing test**

```python
def test_rate_equals_what_the_backbone_already_uses():
    """The contract must not become a second authority (existing-machinery-first).
    Same ticker, same number - pinned against the shipped computation."""
    import valuation_backbone as vb
    res = rate_engine.build_rs2_rate("AMD")
    sector, _ = rs2_data.sector_lookup("AMD")
    expected = round(vb.SECTOR_WACC.get(vb.SECTOR_ALIASES.get(sector, sector),
                                        vb.DEFAULT_WACC) + vb.coe_offset_pts(), 1) / 100.0
    assert res.primary_rate == pytest.approx(expected)


def test_the_rs2_frame_never_returns_a_debt_weighted_rate():
    """Review Focus 1 at the top-level entry point."""
    res = rate_engine.build_rs2_rate("AMD")
    assert res.rate_type == rate_engine.COST_OF_EQUITY_PROXY
    assert res.debt_weight is None and res.pre_tax_cost_of_debt is None
    assert "SECTOR_WACC" in " ".join(res.warnings) or res.rate_type == rate_engine.COST_OF_EQUITY_PROXY


def test_an_unmapped_sector_is_recorded_as_a_fallback(monkeypatch):
    monkeypatch.setattr(rate_engine.rs2_data, "sector_lookup", lambda t: (None, None))
    res = rate_engine.build_rs2_rate("ZZZZ")
    assert res.fallback is True
    assert any("sector" in w.lower() for w in res.warnings)
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement** by delegating to the existing functions — do NOT re-derive the offset.
- [ ] **Step 4: Run the tests**
- [ ] **Step 5: Commit**

---

### Task 6: The audit trail, and a test that it reconstructs the rate

**Files:**
- Modify: `rate_engine.py`
- Test: `tests/test_rate_engine_audit.py`

**Interfaces:**
- Produces: `RateResult.to_record()` completed with `input_hash` and `result_hash` (§33), plus every source vintage used.

- [ ] **Step 1: Write the failing test** — a record from `build_rs2_rate` contains a non-empty source for the level, the terminal-growth vintage, and the methodology version; `input_hash` changes when any input changes and is stable when none does (assert both directions — a hash that never changes is not a hash).
- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the full suite** — `python -m pytest tests/ -v`
- [ ] **Step 5: Commit**

---

## Not in this plan — deferred, one at a time

Named here so the seam is explicit rather than discovered later.

1. **Renaming `wacc` / `wacc_pct`.** `valuation_backbone.backbone()` returns those legacy field names, and the charter is mirrored into `RS2-Analyst-Deep-MTP5.Modelfile` behind `test_charter_single_source.py`. Renaming is a separate change with its own blast-radius test.
2. **The 12 primary frameworks, 20 overlays, beta engine, peer selection, country risk, cost of debt, tax shield, sensitivity and confidence scoring.** §50 Phases 2–5. No consumer in a 135-name book; each needs its own subsystem plan.
3. **Wiring the RS2 rate into `valuation_backbone.backbone()`.** Deliberately after the rename decision, because doing both at once makes a regression hard to attribute.
4. **Routing the sourced ERP into the depth tier's pack**, so the model stops inventing one. This is the fix for the verified +30%-of-the-AMD-answer defect; it needs the pack builder and its own validation run.
5. **FCFE flow completeness** (`NI + D&A - capex` omits Δ working capital and net borrowing). Measured as not the driver — the engine's base is 0.97x the companies' own reported trailing FCF — so it is noted, not acted on.

## Verification for this plan

- `python -m pytest tests/test_anchor_consumption.py tests/test_rate_engine_frame_gate.py tests/test_rate_engine_audit.py -v`
- `python -m pytest tests/ -v` (no regressions in the five existing suites)
- Offline throughout. No model, no GPU, no network. No change to `valuation_backbone.py` in this plan, so no validation sample is required — one sample cannot test a contract that nothing yet calls.
