# Rate Engine Routing — Implementation Plan 2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the firm-level (Mode B) half of the capital-cost engine and route **every** place RS2 derives or accepts a discount rate through the engine, so no rate is invented anywhere.

**Architecture:** `rate_engine.py` gains a Mode B construction (CAPM → capital structure → cost of debt → tax shield) beside the existing Mode A rate. Every inventoried site is then converted to call the engine and stop deriving its own rate. The frame gate (H00) stays the hard boundary: an equity/levered flow may never receive a true WACC.

**Tech Stack:** Python 3.12 stdlib only (`dataclasses`, `math`, `datetime`), pytest. No new dependencies.

**Spec:** `C:\Users\riper\Downloads\Stock Screener\docs\WACC_ENGINE_SPEC_v1.1_RS2_ALIGNED.md` — implements §14–20 (Rf, ERP, CAPM, cost of debt, tax shield, capital structure), §21.1 (true WACC), §32–33 (schema, audit), §50 Phase 1.

## Why this plan exists (the correction that created it)

Plan 1's report said the Mode B half had no consumer in RS2 and was therefore not worth building. **That was wrong.** The inventory (`scratch/rate_site_inventory.py`) shows the analyst's own tool is a Mode B construction:

```python
# tools/audit_202608/financial_model_tool.py
unbundled_dcf(base_cf, growth_rates, wacc, terminal_g, ..., net_debt, shares_diluted)
    enterprise_value = dcf_pv + tv_pv + annuity_pv
    equity_value     = enterprise_value - net_debt      # <-- an enterprise-to-equity bridge
```

An enterprise value discounted at a rate the **model supplies**, then bridged to equity with net debt. So Mode B is not hypothetical: it is live, in the analyst's tool, with a model-chosen `wacc` — which is precisely the pairing the project measured and reverted on 2026-08-07, arriving through a different door.

## Global Constraints

From the spec, verbatim. Every task's requirements implicitly include this section.

- §21.3 pairing invariant: `CLAIM_EQUITY` → {`COST_OF_EQUITY`, `COST_OF_EQUITY_PROXY`}; `CLAIM_FIRM` → {`TRUE_WACC`}; any other pairing is a hard error
- §21.1 `WACC = w_E R_e + w_D R_d (1 - T_shield)`, reachable only from `FIRM_FCFF_FRAME`
- §30/§30.0: the LLM may not invent Rf, ERP, beta, credit spreads or tax rates, and never edits the numerical rate
- §15.3: one approved ERP vintage for all names valued on the same date
- §17.4: factor extensions (size, liquidity) require an explicit versioned methodology, default off
- §51.21: missing data produces explicit uncertainty or failure — never a substitute
- RS2 discipline: a missing/stale/degraded anchor changes nothing and is disclosed

## Review Focus

1. **A Mode B rate reaching a Mode A flow.** The levered flow against market cap must never be discounted with a debt-weighted rate. Expected: hard `FrameMismatch`, and the analyst's tool must stop accepting a model-chosen `wacc` at all.
2. **The model still able to supply a rate.** If `wacc` remains an *optional* parameter, the model will keep passing one and nothing improves. Expected: the parameter is removed or ignored with a warning recorded, never silently honoured.
3. **Two DCF implementations drift.** `financial_model_tool._two_stage_dcf_for_reverse` duplicates `valuation_engine.dcf_value`. Expected: one implementation, or a test pinning them equal.
4. **A missing input becoming a zero.** No debt on the balance sheet is not `Rd = 0`; an absent tax rate is not 0% and not the TTM effective rate (§51.9). Expected: absence propagates as absence or an explicit status, never as a silent zero.
5. **Routing changing the numbers.** Converting the backbone must reproduce today's rate exactly; converting the analyst's tool *will* change its output, and that change must be visible in the one-sample validation rather than discovered later.

## Not in this plan

Phase 3 (peer/beta engine) — measured not to help on this book (per-name beta −0.192 with the market's own required rate; a CAPM rate scored 21.4% vs 27.3% for the flat table). Phase 4 country risk for the ~10 non-US names. Phase 5 uncertainty ranges beyond what §32 already carries. The `wacc`/`wacc_pct` rename.

---

### Task 1: Mode B sourced inputs — CAPM, cost of debt, tax shield, capital structure

**Files:** Modify `rate_engine.py`; Test `tests/test_rate_engine_mode_b.py`

**Interfaces:**
- Produces: `build_cost_of_equity(*, risk_free, mature_erp, beta, country_risk_premium=None) -> FinancialInput` (§17.1/17.2); `calculate_true_wacc(...)` already exists from plan 1; `build_firm_wacc(ticker, *, beta, equity_value, debt_value, pre_tax_cost_of_debt, tax_shield_rate, ...) -> RateResult` with `rate_type=TRUE_WACC`, `valuation_frame=FIRM_FCFF_FRAME`.

- [ ] **Step 1:** failing test — CAPM matches `Rf + β×ERP`; a missing ERP yields `applicable=False` with a named status, never a substituted rate.
- [ ] **Step 2:** run, watch it fail for the right reason.
- [ ] **Step 3:** implement, consuming `rs2_data.anchor_risk_free_rate()` / `anchor_mature_erp()`.
- [ ] **Step 4:** run; **Step 5:** mutate a guard and confirm a test kills it.

### Task 2: `gate_result` on the Mode B path

**Files:** Modify `rate_engine.py`; Test `tests/test_rate_engine_mode_b.py`

- [ ] **Step 1:** failing test — a firm result carrying `COST_OF_EQUITY_PROXY` is refused; a firm result carrying `MARKET_CAP` as its anchor is refused.
- [ ] **Steps 2–5:** implement, verify, mutate.

### Task 3: Route `valuation_backbone` through the engine (behaviour-preserving)

**Files:** Modify `valuation_backbone.py:1358-1361` (and the `FIN_COE`/`UTIL_COE` routes at 831/217); Test `tests/test_backbone_rate_routing.py`

- [ ] **Step 1:** failing test — `backbone(t)["wacc"]` equals `rate_engine.build_rs2_rate(t).primary_rate` for every book name.
- [ ] **Steps 2–4:** delegate the rate construction; keep the construction identical (sector table + level offset), so **no valuation moves**. The existing equivalence harness must stay at zero disagreement.
- [ ] **Step 5:** mutate; then run `scratch/verify_rate_engine_equivalence.py`.

### Task 4: Kill the model-supplied rate in the analyst's tool

**Files:** Modify `tools/audit_202608/financial_model_tool.py:315-362`, `tools/audit_202608/analyst_tools.py:112-146`; Tests in `tools/audit_202608/tests/`

- [ ] **Step 1:** failing test — `execute_financial_model` with a scenario carrying `wacc=0.095` does **not** use 0.095; the rate is resolved by the engine and the record shows it.
- [ ] **Steps 2–4:** resolve the rate from the engine per ticker; if the caller supplied one, record a warning and ignore it (§30). Update the tool schema so `wacc` is no longer advertised as a parameter.
- [ ] **Step 5:** mutate. **This task changes live model output — it needs the one-sample validation run.**

### Task 5: Replace the hard-typed `0.10` in `consensus_valuation.py:271`

**Files:** Modify `tools/audit_202608/consensus_valuation.py:271-272`; Test in `tools/audit_202608/tests/`

- [ ] **Step 1:** failing test — the band de-forwarding uses the engine's rate for that ticker, not a literal.
- [ ] **Steps 2–5:** implement, verify, mutate.

### Task 6: One DCF, not two

**Files:** Modify `tools/audit_202608/financial_model_tool.py`; Test pinning equality with `valuation_engine.dcf_value`

- [ ] **Step 1:** failing test — the same inputs through both implementations agree.
- [ ] **Steps 2–5:** delegate to `ve.dcf_value`; verify; mutate.

---

## The one decision this plan does not make for you

**Which construction Mode A ships.** Plan 1 preserved RS2's existing rate (sector table + market-level offset) because it reproduces today's numbers. The blueprint's construction is CAPM (`Rf + β×ERP`). I measured the difference on this book: **a CAPM rate scored 21.4% on the pass test against 27.3% for the flat table it would replace**, and per-name beta correlates −0.192 with the market's own required rate.

So routing Mode A through the engine with CAPM as the construction would *change* every valuation, and by measurement make them worse. My recommendation is therefore: **route first with the existing construction (no valuation moves), then flip the construction as its own measured step if you want it** — at which point the numbers above are the evidence for the decision rather than a surprise after it.

Mode B has no such conflict: nothing today derives a firm-level rate at all, so the blueprint's construction is a straight improvement there. Tasks 1–2 and 4 can proceed without that decision.
