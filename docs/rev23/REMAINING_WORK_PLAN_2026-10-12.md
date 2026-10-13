# Remaining work to a complete, rolled-out system — plan of 2026-10-12

## Context

The approved recovery plan (`rev23/RECOVERY_PLAN_2026-10-10.md`, stages S0–S12) is the frame; this plan details everything still to do
after gate-2 run 2, across all four systems, with the validation and audits that keep errors out.

**Where things stand (2026-10-12 22:30):**
- Gate-2 run 2 is at 435 of 600 company-dates, ending about 10-13 17:00; the two controls end about 10-14 morning.
- Milestone reviews run every 50 company-dates.
- Engine v2 and the gate-2b and selection registrations are approved.

**What is not yet done:**
- **Analyst:** no live analyst exists. The old analyst is paused; the new one exists only in the test harness.
- **Downstream:** the downstream chain (gates, overlay, paper book, site, follow-up) is built for the old analyst. The follow-up system
  (P6.5–P6.9) sits on a branch and is under test.
- **Screener and MRI**, open defects on record (STATUS "Loose ends"):
  - rs2 reads screener data from a stale dev checkout;
  - the screener's financial tables have been frozen since 08-20;
  - the screener's cloud run never reads MRI;
  - MRI's market premium is degraded daily;
  - MRI theme discovery has failed silently for weeks;
  - MRI's local outputs are stale;
  - the DeepSeek key is rejected;
  - the cloud workflow must move off Node 20 **before 2026-10-19**.

**The operator's decisions (2026-10-12),** recorded at step 0:
- **O2:** "no view" with a reason for unbuilt families now; build families later.
- **O5:** standing approval for SEC, Yahoo and Damodaran downloads.
- **O6:** retire the cloud backstop; the system fails closed.
- **O8:** consensus is shown for display only.
- **Earlier:** O1 (keep D9) and O3 (two-axis entry timing).
- **Still open:** O7 (ARX and the KIS resume details, needed at S11).

**Lesson built into this plan:** defects surfaced one at a time because checks were rehearsed on 20 items. Every long run and every
cutover now gets a full-scale dry sweep first (Q3).

---

## 1. Quality system (applies to every work package)

| # | Rule | How it is checked |
|---|---|---|
| Q1 | Register before data | Bars, reading rules and holdouts go in an addendum or registration before any result exists. No tuning on outcomes. |
| Q2 | Test first, on real fixtures | Every check is tested on saved real outputs, not mocks only. Contract tests keep prompts, checkers and consumers in agreement. |
| Q3 | Full-scale dry sweep | Before any run over 1 hour, and before any cutover: every check applied to ≥150 real items, with dummy outcomes where outcomes would be read. All findings are fixed together, then the run starts. |
| Q4 | Independent recomputation | Every headline number is reproduced by a separate script that imports nothing from the code under test, before it is reported. |
| Q5 | Contracts | Each field has one owner schema (non-negotiable 5). A new field is added to its owner, with a contract test through every consumer. |
| Q6 | Look-ahead audit | Each new data path gets a cut proof: changing every fact filed after the cut leaves the output identical. |
| Q7 | Diff and suites before commit | Read the full diff. Run the repository's suites against a recorded baseline: rs2 `valuation rebuild_harness` (678 now) and the canonical `tests tools/audit_202608/tests` (42 known failures); screener `npm test` and the type check. |
| Q8 | Reviews during long runs | Every 50 items, by `milestone_review.py`. A pause only for a defect in what the model is fed. |
| Q9 | Outside review | ChatGPT and Gemini review every registration and result (cross-checks 8–11). Each point is ruled on in an addendum. |
| Q10 | Memory guard | CPU-heavy jobs run only when no model is loaded, or with commit headroom ≥ 8 GB, at low priority. |
| Q11 | Records | An addendum per decision. STATUS updated. `Get-Date` timestamps. A bell-character check. A handoff at each stage end. |
| Q12 | Fail-closed tests | Each live component is tested with injected failures (source down, stale data, GPU busy, PC off), and must refuse, never fall back silently. |

---

## 2. Work packages

Status key: **NOW** = no GPU needed and not blocked; **AFTER x** = waits on x. "Approval" = the operator decides before a merge, CI
change, deploy or secret.

### Step 0 — Record the decisions (NOW, 15 min)
- **Records:** O2, O5, O6 and O8 go into SPEC_rebuild Addendum AK; the plan's O-table is updated.
- **Memory:** O5 standing downloads join `sec-downloads-standing-approval`.
- **Exit:** the records are re-read and pass the bell check.

### Track A — Finish gate 2 (S2–S3)

**A0. One-command scoring procedure (NOW).**
- **Builds:** new `rebuild_harness/gate2/score_day.py`. It chains:
  1. the SEC store refresh (standing approval, hashed);
  2. outcome extraction, q1 and annual (`outcome_extract.py`);
  3. the baselines v2 build;
  4. `scoring.score`;
  5. `diagnostics.run`;
  6. `scratch/rev23/gate2_audit/independent_g1.py`;
  7. one markdown report, negatives first.

  It refuses unless `gate2_finished.flag` exists and the controls are final.
- **Validation:**
  - unit tests on a mock state;
  - a rehearsal on run 2 with dummy outcomes, end to end;
  - outcome extraction rehearsed only on companies **not** in the gate-2 sample (no gate-2 outcome is read).
- **Exit:** the rehearsal runs clean, with 0 mismatches against the independent script.

**A1. Run 2 completion (running).**
- Milestone reviews continue.
- **Exit:** `gate2_finished.flag` exists, and the last review has 0 unresolved flags.

**A2. Controls (AFTER A1).**
- **Masked:** run `register_gate2_task.ps1 -Mode masked` from `wt-gate2-run2`.
- **Repeat (R8):**
  - a scratch launcher (the task script lacks `repeat`);
  - a new state folder with the `REPEAT_CONTROL` marker;
  - hash-verified copies, as AF.
- **Validation:** the behaviour gate and a leakage audit on both folders; usable counts reported (expected about 16 and 25).

**A3. Scoring (AFTER A2; the model unloaded).**
- **Run:** `score_day.py`.
- **Audit 1** (before anything is reported):
  - **look-ahead:** every input filed before T, every outcome filed after T;
  - **outcome coverage:** by date, family and measure, with included and missing compared;
  - **hand check:** 20 outcomes against the SEC filings themselves;
  - **agreement:** the independent script agrees.
- **Exit:** report written. CROSS_CHECK_8 results sent; the replies ruled on.

**A4. The branch decision (AFTER A3).**
- C1, C2 or C3, by the AD rules with the AH C1 arms.
- Also: R3b (keep or drop the red team) and R8 (multi-sample k).
- **Exit:** recorded in an addendum; the operator is told.

### Track B — The analyst core (S4–S6)

**B1. S5 spec and registration: Muse integrated with engine v2 (NOW; must be fixed before A3 reads outcomes).**
- **Content:**
  - transport `x = v2_P50 + w·(Muse − c7d7a4f prior P50)` per input and family;
  - w by leave-one-date-out over the 5 gate-2 dates, on forecast loss only; w = 0 where there is no out-of-fold gain;
  - the margin deviation maps into years 1–3 through the retention weights;
  - the calibration method chosen by cross-fitted loss (isotonic against a smoothed monotone mapping);
  - the red-team rule from R3b;
  - multi-sample k from R8 (standard error ≤ 5 points);
  - the C2/C3 structural-search candidates and their pre-registration format.
- **Validation:** synthetic-data tests of the fitting (a known w is recovered; w = 0 under noise); a leakage audit of the fitting split.
- **Exit:** approved and fixed before A3. Part of cross-check 9.

**B2. Engine v2 code (NOW).**
- **Files:** `valuation/near_term.py`, `engine_operating_v2.py`, `engine_financial_v2.py`, `priors_build/near_term.py`, all per
  `SPEC_engine_v2.md`.
- **Tests:**
  - centre rules;
  - residual draws;
  - the copula;
  - the after-year-3 chain;
  - refusals;
  - v1 untouched (E7).
- **Independent:** the E1 identity script, written before the build.
- **Exit:** the suites are green, and E7 passes.

**B3. Engine v2 build and validation (AFTER A2; CPU-heavy, no model loaded).**
- **Build:** the near-term tables per vintage 2016–2025 into `data/priors_v4`.
- **Validation:** E1–E6 as registered.
- **Audit 2:** recompute E2 and E3 with independent code; the cut proof for every vintage.
- **Exit:** the registration passes; v2 frozen with hashes.

**B4. S5 fit and gate 2b (AFTER A4, B3).**
1. **Fit:** w and the calibration on gate-2 data only.
   - **Audit 3:** no gate-2b data touched; the leave-one-date-out split verified by an independent script.
2. **Freeze SYSTEM.**
3. **Prepare the dates:** after 2026-10-30, the store refresh. Then:
   - the engine-valuable pre-check;
   - the quota draw (100 operating + 50 financial per date, seed 20261010);
   - the freeze.
4. **Q3 dry sweep before the long run:** a rehearsal over the first 150 company-dates, with every check and dummy outcomes.
5. **Run:** about 3.1 GPU-days, with milestone reviews.
6. **Score:**
   - an early q1 read on 2026-12-18 (no weight);
   - the bars on 2027-04-15 by `score_day`-style automation, with the independent script.
- **Exit:** the gate-2b verdict, then promotion (or not) per its section 5.

**B5. Distress layer v2 (S6; NOW for the registration, CPU for training).**
- **Registration first:**
  - candidates: solvency variables, distance to default, Muse distress flags (post-cutoff dates only);
  - the walk-forward AUC and Brier score against the current layer;
  - the bar: no inversion of the least-solvent tercile on fresh dates.
- **Then:** training on D1 events in an expanding window.
- **Audit:** an independent AUC recompute; a look-ahead check on the event labels.

**B6. Coverage as "no view" (O2; NOW).**
- **Families:** BDCs, commodity, REIT, utility, pre-profit, and companies with no share count or no 10-Q.
- **The rule:** each becomes an explicit abstention with a reason code in the verdict, never a fallback value.
- **Validation:** every refusal path in run 2 (the 109+12 cases) maps to a reason code; a contract test.

### Track C — Verdict and downstream (S7)

**C1. `SPEC_verdict_contract_v4.md` (NOW).**
- **Fields:** the calibrated quantiles, Pr(IV > price), the expected margin of safety, the terminal-value share, unanchored inputs, repeat
  spread, every version stamp, `run_source`, abstention codes (B6), consensus for display (O8), two-axis entry timing (O3).
- **Actionable reasons, gate on read:** `not_usable`, `family_not_built`, `integrity_fail`, `unanchored_high`, `implausible_level`,
  `extraordinary_without_evidence`, `instability`, `stale_inputs`, `pre_valid_analyst`.
- **Watch items for the follow-up,** generated by code.
- **Validation:**
  - **field ownership:** a single-owner table;
  - **fixtures:** v4 rows built from real run-2 results (no outcomes).
- **Exit:** the operator approves; cross-check 10.

**C2. Downstream changes (AFTER C1; each on a branch, with operator approval to merge, never deployed automatically).**

| Repository | Change |
|---|---|
| rs2 | `depth_gates.assess` v4; the overlay writer (publishing only through `screener-publish`) |
| screener | `apply_llm_overlay`; the paper-book `rn_depth` targets; the site desk (design brief sections 02/05 updated); TRK-06 grading of v4 fields |

- **Validation:** contract tests run v4 fixture rows through every consumer in both repositories; the screener `npm test` and type
  check; rs2 suites.
- **Audit 4:** a field-by-field trace from engine result to site display on 5 fixture rows, checked by hand.

**C3. Follow-up system (P6.5–P6.9) onto v4 (AFTER C1).**
- **Work:** rebase the branch onto the new contract; generate watch items from v4; point the follow-up at the shared Muse server.
- **Validation:** its acceptance tests A (battery) and C (shadow week) re-run.
- **Audit:** "monitoring never sells" verified by test.

### Track D — Live production (S9) and the rest of the stack

**D0. Deadline items (NOW; urgent).**

| Item | What | Deadline / approval |
|---|---|---|
| Node 20 | The CI move off Node 20 / Ubuntu 26. The workflow change is prepared on a branch and tested by a manual dispatch. | **Before 2026-10-19**; operator approval |
| DeepSeek key | `DEEPSEEK_API_KEY` in stock-screener | The operator replaces the secret |

**D1. Screener-side prerequisites (NOW).**
- **rs2's screener data path:**
  - Fix rs2 so it reads screener data from the publish clone or a resolved data directory via `paths.py` / `peer_paths.py`, never the
    dev checkout.
  - Test that the path resolves and refuses when the data are stale.
- **Frozen financial tables:** the weekly job never commits `fundamentals_*.json`. Prepare a CI change; operator approval.
- **Validation:** a freshness check added to the preflight; the screener tests.

**D2. MRI fixes (NOW for code; the refresh is CPU, with no model loaded).**
- **The screener reads MRI's published files,** with date checks (a CI change; approval).
- **MRI's premium is degraded daily:** design decision, with the analyst's closure premium as the candidate. Recorded, then built.
- **Theme discovery's silent failures:** an alert on failure and a fix of the empty-reply handling.
- **Refresh:** MRI's local outputs and the news store.
- **Validation:** MRI's own suite; a date-check test; one forced-failure test that must alert.

**D3. Live data layer (O5; NOW).**
- **Refreshes:** SEC submissions and companyfacts daily, Yahoo daily closes, Damodaran monthly. Each run is hashed and logged, and every
  input is stamped with its as-of date.
- **Gaps:**
  - the dual-class share count, tested on the 17 run-2 names;
  - the foreign-filer abstention.
- **Validation:**
  - Q6 cut proof;
  - Q12 fail-closed tests: a source down or stale data gives `stale_inputs`.

**D4. Live runner and parity (AFTER B4 freeze, C1).**
- **The runner:** pack → Muse through `llamacpp_server` at the gate-2 pins → engine v2 + calibration → red team (if kept) → contract v4
  → ledger row. It reuses the replay code paths unchanged.
- **Audit 5, parity:**
  - the live runner in as-of mode, fed recorded model responses, reproduces the replay byte for byte on a replay date: packs, prompts,
    engine results;
  - any difference blocks cutover.

**D5. Orchestration and operations (AFTER D4).**
- **DEP-00 orchestration:**
  - the book: research_now ∪ watchlist ∪ ledgered names;
  - triggers: a new 10-Q/10-K, 8-K items, a price-range crossing, 14-day rotation;
  - the GPU budget, with a wait while gaming;
  - the on-demand path (DEP-11).
- **Operations:**
  - **preflight (OPS-09):** model and llama.cpp hashes, data freshness, the priors and calibration versions;
  - **backups:** new state files added to the `sync_state` backup list;
  - **records:** the system map updated;
  - **retirements:** the backstop (O6) and the old Qwen analyst, with its weights kept.
- **Validation:** Q12 fail-closed tests, including PC off: the overlay goes stale and buying pauses after 36 h.

**D6. Pre-cutover dress rehearsal (Audit 6; AFTER C2, C3, D5).**
- **The rehearsal:** a full chain on a test date in a sandbox: screener → analyst → gates → overlay to a test directory, **not**
  published → paper book → follow-up.
- **Checks:** the Q3 sweep on every artifact; the failure-injection set.
- **Exit:** 0 open flags; the operator approves the cutover.

### Track E — Selection and sizing (S8)

**E1. Evaluation tooling (NOW).**
- **Builds:**
  - the factor panel with the core and expanded controls;
  - the liquidity-tiered cost and borrow schedule;
  - the long-short and sized books with the buffer rule;
  - Newey–West statistics;
  - the fixed sequence H-S2 → H-S1 → H-S3.
- **Validation:**
  - synthetic panels with a planted signal (recovered) and no signal (t about 0);
  - an independent recompute script.

**E2. Exploratory dates (AFTER B4 candidate core).** Reported only. Confirmatory dates start after promotion (earliest 2027-04-30).

### Track F — Shadow and readiness (S10–S11)

**F1. Shadow operation (AFTER D6 and the gate-2b promotion).**
- **What runs:** the live system unattended, paper only; `KIS_HALT` stays on.
- **Scorecards each quarter:** D2, D3, D7, D8, D10 and the D9 accrual.
- **Before promotion:** a provisional shadow with the candidate core may run from about 2027-01, counting nothing.

**F2. Real-money readiness (Audit 7; operator decision O7).**
- `RESUME_PROTOCOL_v4.md`.
- **Verified first:**
  - `KIS_HALT` is sticky;
  - no code path reaches real execution until S11;
  - KIS dry runs against the shadow book;
  - the staged ramp, the attended first sync and the rollback.

---

## 3. Order and timeline (GPU waits while the operator games)

| When | Work |
|---|---|
| Now → 10-14 | Step 0; **B1** (S5 spec, before outcomes); **A0**; **D0** Node 20 change (approval by 10-19); B2; D1 path fix; C1 drafting |
| 10-13 → 10-15 | A1 end → A2 controls → A3 scoring → A4 branch; CROSS_CHECK_8 results |
| 10-15 → 11-05 | B3 build (CPU, model unloaded); B4 fit; B5; B6; D2; D3; E1; C1 approval |
| ~11-05 → ~11-20 | Gate-2b preparation (after 10-30 filings), dry sweep, run (~3 GPU-days); C2, C3 branches |
| 11-20 → 2027-01 | D4 parity; D5; D6 dress rehearsal; early gate-2b read 12-18 |
| 2027-01 → 04 | Provisional shadow (no count); fixes from shadow |
| 2027-04-15 | Gate-2b scored → promotion → F1 official shadow; confirmatory selection dates from 04-30 |
| ~2030 | D9 readable; S11 by operator decision |

## 4. Operator approvals queue

| Approval | Kind |
|---|---|
| Node 20 workflow change (by 10-19) | CI |
| Fundamentals auto-commit | CI |
| MRI fetch in the screener run | CI |
| DeepSeek key | Secret |
| S5 registration | Registration |
| Distress registration | Registration |
| Verdict contract v4 | Spec |
| Each downstream merge | Merge |
| Cutover after D6 | Cutover |
| Old-analyst retirement | Retirement |
| O7 at S11 | Decision |

## 5. Risks

| Risk | Handling |
|---|---|
| Muse shows no skill (C2/C3) | Engine v2 is the core. B4 becomes the structural search. Tracks C–F proceed unchanged, since they are branch-independent. |
| Gate 2b fails | Its section 5: no promotion; next untouched dates. |
| Hidden defects at scale | Q3 sweeps and Q8 reviews. |
| Live and replay drift | Audit 5 byte-for-byte parity. |
| Data sources fail | Fail-closed tests and staleness refusal. |
| Memory exhaustion | Q10 guard. |
| Operator-gated CI items slip | The approvals queue is shown in every report; the Node 20 deadline is flagged first. |

## 6. Verification of the whole programme

Each package exits only on:
- its listed validation;
- green suites against baseline;
- independent recomputation of its headline numbers;
- its audit;
- a recorded addendum and STATUS line.

The system is complete when D6 passes, gate 2b promotes a core, shadow operation runs unattended with the quarterly scorecards, and every
open loose end in STATUS is closed or explicitly accepted by the operator.
