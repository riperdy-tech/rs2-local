# Institutional Underwriting Synthesis: Qwen PM & Python Financial Desk Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform RS2 Depth Underwriting into an institutional-grade division of labor where Qwen acts as Portfolio Manager & Lead Underwriter (economic viewpoints, scenario boundaries, moat trajectories, and final capital decisions) while Python acts as Financial Modeling Desk (exact unbundled DCF, reverse DCF expectations gap, and continuous multi-outcome Kelly sizing). Completely removes Kelly arithmetic from the LLM analyst's prompt.

**Architecture:** 
1. `financial_model_tool.py`: Exposes a deterministic financial modeling engine to Qwen via Ollama function calling during reasoning (handles unbundled DCF, reverse DCF, and continuous multi-outcome Kelly math).
2. `analyst_tools.py`: Dispatches `run_financial_model` mid-reasoning and feeds exact spreadsheet calculations back to Qwen.
3. `capability_test.py`: 
   - **Removes Kelly calculation from the LLM analyst**: Qwen only outputs scenario probabilities and payoffs; Python handles Kelly math.
   - Updates the `TASK` prompt to guide Qwen's role as PM/Lead Underwriter collaborating with the financial desk tool.
   - Adds Working Capital Customer Advances / Prepayment Float note.

*(Note: Task 4 Consensus Gate is DELAYED pending operator's full-blown audit. Tasks 5 & 6 are dropped.)*

**Tech Stack:** Python 3.11+, Ollama (Local Qwen 2.5 32B / rs2-analyst-deep-mtp5), SearXNG.

## Global Constraints

- **Cognitive Primacy**: Qwen owns all qualitative judgements, scenario bounds, unit economics, invalidation tripwires, and the final fiduciary capital allocation verdict. Python does arithmetic; it never replaces the PM's judgement.
- **Remove Kelly from LLM**: Qwen is a single-stock fundamental underwriter, NOT a portfolio sizing calculator. Sizing math is strictly owned by Python.
- **Zero Double Work**: Preserve existing Section 1.5 Macro anchors and Section 7 quality metrics already present in `capability_test.py`.

---

### Task 1: Financial Modeling Desk Tool (`financial_model_tool.py`)

**Files:**
- Create: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/financial_model_tool.py`
- Test: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/tests/test_financial_model_tool.py`

**Interfaces:**
- Produces: `execute_financial_model(params: dict) -> dict`
- Sub-functions:
  - `unbundled_dcf(base_cf, growth_rates, wacc, terminal_g, terminal_multiple, annuity_flow, annuity_cap_rate, net_debt, shares)`
  - `reverse_dcf_expectations_gap(current_price, shares, base_cf, wacc, terminal_g, demonstrated_cagr_5y)`
  - `continuous_multi_outcome_kelly(price: float, outcomes: list[dict], position_cap_pct: float) -> dict`
  - `calculate_payoff_skew(base_iv, bull_iv, bear_iv, price)`

- [x] **Step 1: Write test for financial modeling math**
- [x] **Step 2: Run test to verify failure before implementation**
- [x] **Step 3: Implement `financial_model_tool.py`**
- [x] **Step 4: Run test to verify PASS**

---

### Task 2: Register Financial Desk Tool in `analyst_tools.py`

**Files:**
- Modify: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/analyst_tools.py`
- Test: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/tests/test_analyst_tools_integration.py`

**Interfaces:**
- Exposes: `run_financial_model` function in `TOOLS` array for Ollama.
- Executes: When Qwen calls `run_financial_model`, invokes `financial_model_tool.execute_financial_model` and returns structured JSON + Markdown summary table.

- [x] **Step 1: Write integration test for `analyst_tools.py` tool dispatch**
- [x] **Step 2: Run test to verify failure**
- [x] **Step 3: Add `run_financial_model` to `TOOLS` and dispatch handler in `analyst_tools.py`**
- [x] **Step 4: Run test to verify PASS**

---

### Task 3: Lead Underwriter Prompt & Working Capital Float Awareness in `capability_test.py`

**Files:**
- Modify: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/capability_test.py`
- Test: `c:/Users/riper/Downloads/RS2 Local/tools/audit_202608/tests/test_pack_enrichment.py`

**Interfaces:**
- Enhancements:
  - **Remove Kelly arithmetic from `TASK` prompt**: Delete the requirement for Qwen to calculate $p, q, b, f^*, f^*/4$ in prose. Instead, Qwen outputs the economic scenarios (Base/Bull/Bear IV and probabilities), while Python computes Kelly.
  - **Add Section 6C/Working Capital Float Note**: highlights customer down-payment / prepayment float when contract liabilities/deferred revenue diverge from OCF.
  - **Update `TASK` prompt**: Instructs Qwen on its role as Lead Underwriter / PM. Qwen defines operational scenario assumptions, calls `run_financial_model` to calculate exact DCF, expectations gap, and Kelly numbers, examines the output against business reality, sets entry tranches & invalidation triggers, and outputs the final Section 12 machine contract.

- [x] **Step 1: Write test for prompt and working capital float note**
- [x] **Step 2: Run test to verify failure**
- [x] **Step 3: Update `capability_test.py`**
- [x] **Step 4: Run test to verify PASS**

---

## Detailed Test Plan & Verification Protocol

*(Full specification document: [`docs/TEST_PLAN_INSTITUTIONAL_UNDERWRITING.md`](file:///c:/Users/riper/Downloads/RS2%20Local/docs/TEST_PLAN_INSTITUTIONAL_UNDERWRITING.md))*

### 1. Automated Test Suite (13 Automated Tests)
Run: `python -m pytest "tools/audit_202608/tests" -v`

#### Phase 1: Deterministic Arithmetic Unit Tests (`test_financial_model_tool.py`)
- [x] **TC-1.1** `test_unbundled_dcf_basic`: 5-year discrete DCF + terminal exit multiple - net debt.
- [x] **TC-1.2** `test_unbundled_dcf_with_annuity`: Separate capitalization of installed-base annuity stream (proves no double counting).
- [x] **TC-1.3** `test_reverse_dcf_expectations_gap`: Bisection search for 5y growth implied by $T_0$ price vs demonstrated 5y CAGR.
- [x] **TC-1.4** `test_continuous_multi_outcome_kelly_negative_edge`: GEV empirical reproduction (35% Base @ $1100, 20% Bull @ $1450, 45% Bear @ $550 at $951 price -> Expected return -2.99% -> strictly clamps to **0.0% Kelly**).
- [x] **TC-1.5** `test_continuous_multi_outcome_kelly_positive_edge`: Multi-scenario non-linear log-wealth optimization (Full Kelly > 0%, Quarter-Kelly = Full Kelly / 4).
- [x] **TC-1.6** `test_calculate_payoff_skew`: Mathematical payoff skew $(Bull - P) / (P - Bear)$.
- [x] **TC-1.7** `test_execute_financial_model_dispatch`: Master JSON dispatcher execution and verification.
- [x] **TC-1.8** `test_unbundled_dcf_boundary_conditions`: Error handling for negative base cash flows and $WACC \le terminal\_g$.
- [x] **TC-1.9** `test_calculate_payoff_skew_zero_downside`: Zero downside division protection (clamps to 99.9x ceiling).
- [x] **TC-1.10** `test_batch_scenario_dcf_execution`: Batch multi-scenario DCF execution in a single call (computes Base/Bull/Bear IVs, reverse DCF gap, and continuous Kelly together).

#### Phase 2: Tool Dispatch Integration Tests (`test_analyst_tools_integration.py`)
- [x] **TC-2.1** `test_financial_model_tool_registered_in_tools_list`: Ollama function calling schema in `analyst_tools.py`.
- [x] **TC-2.2** `test_dispatch_financial_model_tool`: Tool dispatch, formatted markdown table generation, and `_research_snapshot.json` logging.
- [x] **TC-2.3** Smart Tool Governor: Decoupled `search_calls` (cap 25) from `model_calls` (cap 5). Web search quota intercepts with guidance; `run_financial_model` is never stripped from the Ollama schema.

#### Phase 3: Prompt & Context Hygiene Tests (`test_pack_enrichment.py`)
- [x] **TC-3.1** `test_task_prompt_removes_manual_kelly_math_and_introduces_financial_desk`: Confirms manual mental Kelly derivation is 100% removed; Lead Underwriter role and batch `run_financial_model` instructions present.
- [x] **TC-3.2** `test_pack_contains_working_capital_float_notice`: Confirms Section 6 Customer Prepayment Float notice is present.
- [x] **TC-3.3** Balance Sheet Clean Separation: Section 6 split into Section 6A (Operating Assets) and Section 6B (Capital Structure & Net Worth) with an explicit Verified Liquidity Card to eliminate token column-slip.
- [x] **TC-3.4** Stage 1 Normalized Earnings Extraction: Catalysts & Guidance prompt in `deep_research.py` explicitly extracts one-time M&A gains, divestitures, and normalized operating income into Section 11.

### 2. Live Sweep Non-Interference Check
- [x] `python status.py --once`: Verified live orchestrator operations (`PID: 24216`) remained active, clean, and uncorrupted.

### 3. End-to-End Live Ticker Verification Protocol
Executed live on `GEV` with Batch Financial Desk Tool & Smart Governor:
```bash
python depth_pipeline.py GEV --samples 1 --ondemand
```
- [x] Stage 1 Deep Research ran fresh (archived prior cache), extracted Q2 2026 backlog and normalized outlook into `research/GEV.md`.
- [x] Clean Section 6A (Operating Assets) and 6B (Capital Structure & Net Debt -$7.68B) prevented token column-slip.
- [x] Smart Tool Governor kept `run_financial_model` permanently accessible across 23 tool calls.
- [x] Qwen formulated operational drivers and dispatched batch `run_financial_model` with all 3 scenarios.
- [x] Python deterministic arithmetic produced:
  - Base IV: $1,139.78 (+19.8% MoS)
  - Bull IV: $1,570.65 (+65.2% MoS)
  - Bear IV: $636.29 (-33.1% MoS)
  - Reverse DCF Expectations Gap: -3.1 points (5.5% implied vs 8.6% demonstrated)
  - Continuous Multi-Outcome Kelly: 24.75% quarter-Kelly (+22.85% expected return)
  - Asymmetric Payoff Skew: 1.97x
- [x] Section 12 JSON machine contract matches Python output to the exact cent and basis point (zero mental math hallucinations).
- [x] Verdict emitted: `direction: "undervalued"`, `size_hint: "quarter"` (appropriately capped for single sample), audited via `depth_sanity.py` (0 errors), recorded to `depth_ondemand_ledger.jsonl`.
- [x] GPU VRAM cleanly released back to 0 MiB.

