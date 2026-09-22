# Consensus Gate — Revised Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the depth consensus path able to *see* its own instability, stop the fiduciary gate from enforcing a simplex over invented probabilities, and reduce the number of independent owners of the contract base — in that order, because every later change is unmeasurable without the first.

**Architecture:** All five tasks are Python-side corrections to how the pipeline reads and judges the model's output. None changes a word the model is shown (except Task 5, which is deliberately last and gated). New signals ride as *flags and reasons* on the verdict — never as gates, never deleting a sample. This follows the 2026-08-24 guard redesign: a threshold that deletes a sample destroys the measurement it was built to make.

**Tech Stack:** Python 3.12, pytest, stdlib only. No new dependencies. Ollama at `127.0.0.1:11434` (not exercised by these tasks).

**Spec:** `AGENTS.md` (governing authority — §1 "No Narrow Heuristic Patches", §2 "not erased by simplistic working-capital deductions") and `docs/Review SKILL.md` (Phase 9 provenance, Phase 10 single ownership, Phase 12 audit-the-auditor). MoS bands referenced from `_archive/retired_20260920/RS2.txt:352`.

## Global Constraints

- **MoS convention is (A):** `IV / price - 1`. Operator decision 2026-09-20. No live site may compute `(IV - price) / IV`.
- **No `PACK_REVISION` bump** for Tasks 1-4 (operator decision 2026-09-20). None of them alters what the model is told. Task 5 does, and needs a fresh ruling before it starts.
- **Annotate, never gate.** New signals add flags/reason text only. They must not change `direction`, `size_hint`, or delete a sample.
- **Single owner per field.** A new contract field must be added to its owner's schema or it is silently dropped — this is the exact bug Task 2 fixes, so Task 2 must not recreate it.
- **`0.0` is a value, not an absence.** Never use `or` to default a numeric field.
- **Both suites green at every commit:** `python -m pytest tools/audit_202608/tests -q` (currently 50) and `python -m pytest tests/ -q` (currently 49).
- Work happens on branch `fix/consensus-gate-20260920`.

## Review Focus

Inputs and conditions the spec implies but no task's tests naturally cover. Each is pinned by a test in the task that owns the code.

1. **No prior verdict exists** (a name analysed for the first time) — must not crash, must not report instability.
2. **Prior verdict written by an older code version** — may lack `base_iv`, `scorecard`, or `pack_revision`. Must degrade, not raise.
3. **Partially supplied probabilities** (2 of 3) — must never yield a simplex summing above 1.
4. **A supplied probability of exactly `0.0`** — must be respected, not overwritten by a default.
5. **A rescued sample** (`stub_rejected` / forced low-effort report) mixed with normal siblings — must be distinguishable in the consensus record.

---

### Task 1: Mode-instability detector

**Files:**
- Modify: `depth_pipeline.py` (add `INSTABILITY_TOL_PCT`, `iv_instability()`, `_prior_verdict()`, wire into `band_verdict`)
- Test: `tools/audit_202608/tests/test_mode_instability.py` (create)

**Interfaces:**
- Consumes: `contract_base(scorecard)` from `depth_pipeline.py`; `LEDGER` / `OD_LEDGER` paths.
- Produces:
  - `iv_instability(current_iv: float|None, prior_iv: float|None, tol_pct: float = INSTABILITY_TOL_PCT) -> dict|None` — pure. Returns `None` when either input is missing/<=0. Else `{"prior_iv", "current_iv", "delta_pct", "unstable"}` where `delta_pct = (current/prior - 1) * 100` rounded to 1dp and `unstable = abs(delta_pct) > tol_pct`.
  - `_prior_verdict(ticker: str, ledgers: tuple) -> dict|None` — newest row for the ticker across the given jsonl ledgers, `None` if absent or unreadable. Must skip malformed lines, never raise.
  - `band_verdict` gains `v["instability"]` (the dict or `None`) and, when unstable, flag `MODE_INSTABILITY` plus a `reason` sentence.

**Why:** Measured 2026-09-20: GEV's median IV moved 934.535 -> 517.745 between two runs on the same `pack_revision`, same price. Within each run the spread was tight (24.9%, 13.2%), so `converged` was true both times. Nothing in the depth path compares a verdict to its predecessor, so `EARLY_TOL_PCT` at n=2 can certify one mode of a bistable distribution as CONVERGED and no consumer can tell.

- [ ] **Step 1: Write the failing test** — `test_iv_instability_flags_a_large_move` (934.535 -> 517.745 gives `delta_pct == -44.6`, `unstable is True`), `test_iv_instability_quiet_on_small_move`, `test_iv_instability_returns_none_without_prior`, `test_prior_verdict_skips_malformed_lines`, `test_prior_verdict_returns_none_when_absent`.
- [ ] **Step 2: Run it, watch it fail** on the missing symbol (not a typo).
- [ ] **Step 3: Implement** the pure function and the ledger reader.
- [ ] **Step 4: Write the failing integration test** — a verdict built from a doc plus a seeded prior ledger row carries `MODE_INSTABILITY` and `instability["unstable"] is True`, and `direction` is unchanged versus the same doc with no prior.
- [ ] **Step 5: Implement the `band_verdict` wiring** (after `v.update(...)` for MoS, before `fiduciary_verdict_gate`).
- [ ] **Step 6: Run both suites.**
- [ ] **Step 7: Commit.**

---

### Task 2: Probabilities survive extraction, and the simplex is total

**Files:**
- Modify: `tools/audit_202608/consensus_valuation.py` (`extract_scorecard`, `select_medoid_scorecard`)
- Modify: `tools/audit_202608/fiduciary_gate.py` (probability block, edge test)
- Test: `tools/audit_202608/tests/test_scorecard_probabilities.py` (create), extend `tools/audit_202608/tests/test_fiduciary_gate.py`

**Interfaces:**
- Consumes: the model's ` ```json:underwriting ` block, which already contains `base_probability` / `bull_probability` / `bear_probability` (`capability_test.py:895-897`).
- Produces:
  - `extract_scorecard()` card gains the three probability keys.
  - `select_medoid_scorecard()` summary gains the three, taken from the medoid card.
  - `validate_fiduciary_contract()` sanitized card gains `probabilities_defaulted: bool`.

**Why:** `extract_scorecard` copies only the keys already in its own 9-key dict (`consensus_valuation.py:133-137`), so the model's real probabilities are discarded; `select_medoid_scorecard`'s 16-key summary never carries them; `build_contract`'s `CONTRACT_PASSTHROUGH` entries for the three are therefore dead; and `has_probs` is always `False`, routing every production contract into the hardcoded `0.50 / 0.30 / 0.20` at `fiduciary_gate.py:101-105`. A clamp is then justified in published `reason` text by a number the model never produced.

- [ ] **Step 1: Write the failing tests** — (a) `extract_scorecard` returns the three keys when the JSON block supplies them; (b) `select_medoid_scorecard` summary carries them; (c) all three supplied and summing to 1.7 normalises to 1.0; (d) **two supplied produces a legal simplex, not 1.1**; (e) `base_probability = 0.0` survives; (f) `probabilities_defaulted is True` when fewer than three arrive.
- [ ] **Step 2: Run, watch each fail for the right reason.**
- [ ] **Step 3: Implement extraction + summary plumbing.**
- [ ] **Step 4: Implement the gate fix** — `is None` checks; all-three -> normalise (existing); fewer-than-three -> set the constant triple **as a set**, set `probabilities_defaulted = True`, append a named issue.
- [ ] **Step 5: Apply the edge leg only when `not probabilities_defaulted`.** Keep `base_iv <= price` unconditional — it is deterministic and correct. Confirm `test_negative_edge_clamps_kelly` still passes (it supplies all three).
- [ ] **Step 6: Run both suites.**
- [ ] **Step 7: Commit.**

---

### Task 3: A rescued sample is visible

**Files:**
- Modify: `tools/audit_202608/consensus_valuation.py` (sample loop `runs.append`)
- Modify: `depth_pipeline.py` (`band_verdict` flag)
- Test: `tools/audit_202608/tests/test_rescue_visibility.py` (create)

**Interfaces:**
- Consumes: `chat_with_tools` meta, which already returns `stub_rejected` and `turns` (with per-turn `forced_report` / `budget_exhausted`).
- Produces: `runs[i]["stub_rejected"]`, `runs[i]["forced_report"]`; verdict flag `LOW_EFFORT_RESCUE` when any *used* sample was rescued.

**Why:** The forced-report path runs at `think: "low"` with a 32768 cap (`analyst_tools.py:436-445`), so a rescued sample is generated at a different reasoning effort from its siblings. `stub_rejected` is persisted per sample but `consensus_valuation` copies only four keys out of `meta`, so it never reaches `runs[]` or `consensus.json` and the band silently mixes two effort levels.

- [ ] **Step 1: Write the failing tests** — runs carry `stub_rejected` and `forced_report`; `forced_report` is `True` when any turn has it; a verdict whose used samples include a rescued one carries `LOW_EFFORT_RESCUE`; a clean set does not.
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** the `runs[]` fields and the flag.
- [ ] **Step 4: Run both suites.**
- [ ] **Step 5: Commit.**

---

### Task 4: One owner for the contract base, and honest MoS documentation

**Files:**
- Modify: `tools/audit_202608/fiduciary_gate.py` (own `contract_base`)
- Modify: `depth_pipeline.py` (import it; keep the name exported for existing readers)
- Modify: `tools/audit_202608/depth_sanity.py` (use the shared resolver)
- Modify: `valuation_backbone.py` (comments only: `MOS_EXTREME_MAX`, the `abs(mos) > 60` unit mismatch)
- Modify: `tools/audit_202608/consensus_valuation.py` (comment at the `MOS_EXTREME` definition)
- Test: `tools/audit_202608/tests/test_contract_base_owner.py` (create)

**Interfaces:**
- Produces: `contract_base(scorecard)` in `fiduciary_gate.py`; `depth_pipeline.contract_base` becomes a re-export; `depth_sanity` calls the shared one.

**Why:** Three independent resolutions of the same published number exist — `depth_pipeline.contract_base` (`base_iv or median_iv`), the `mos_vs_median_pct` anchor, and `depth_sanity.py:117` (`base_iv or median_iv or lo`). They diverge whenever `base_iv` exists and differs from `median_iv` — the GEV case, where the two published fields differ by 3.4 points. Separately, `MOS_EXTREME = 1.50` is documented as `|MoS|` but under convention (A) it can only ever trip at `IV > 2.5 * price`, because `IV/price - 1 >= -1`. All six published trips are positive and the repo's own recorded `-99.4%` passed untouched.

- [ ] **Step 1: Write the failing tests** — the shared resolver returns the same base for the same scorecard from all three consumers; it tolerates a legacy scorecard with no `base_iv`; `depth_sanity`'s reported base equals `contract_base` for a GEV-shaped scorecard where the two previously differed.
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Move `contract_base` to `fiduciary_gate.py`**, re-export, and repoint `depth_sanity`.
- [ ] **Step 4: Correct the comments** — state that the (A) fence is one-sided by construction and catches only the upside tail; fix the false "shared definition" claim; reconcile the `> 60` percent-unit threshold.
- [ ] **Step 5: Run both suites.**
- [ ] **Step 6: Commit.**

---

### Task 5: Owner-earnings decomposition in the pack — GATED, DO NOT START

**Blocked on two rulings:** (a) Task 1 must have shipped, so the change is measurable against the instability detector; (b) `PACK_REVISION` — this task *does* alter what the model is told, so the earlier "no bump" decision does not cover it, and shipping it un-bumped would silently mix incomparable verdicts in the ledger.

**Design so far (not final):** publish per-FY `OCF - capex - SBC` as labelled `[Arithmetic]`, symmetric across years, with **no headline normalised number** — because `AGENTS.md §2` forbids "simplistic working-capital deductions" and `build_pack`'s own contract is "no basis choice, no normalisation, no composite of our own". A single highlighted latest-FY figure would make the subtractive basis salient and risk *steering* the very distribution this work exists to measure. Any self-reported basis enum must be cross-checked by Python against which filed figure `base_cf` actually matches, and that check must annotate, never gate.
