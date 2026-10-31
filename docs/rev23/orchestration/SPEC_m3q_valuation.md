# SPEC 3Q: valuation engine and Qwen reasoning repair, draft v0, 2026-10-30

**Status:** v0.1. B1, B2, B5 and B9 RULED 2026-10-30 as §8 recommends (OPERATOR_DECISIONS §B). The spec freezes after
WO_Q3 produces B1's evidence. B3, B4, B6, B7, B8 and B10 keep §8's defaults until ruled.
**Authority:** diagnostic only (recommended B9). No 3Q output changes paper selection, weights, exits or eligibility.
**Linked:**
- PLAN §3Q; RR_Q1 (the inventory: every file:line below without a source is from there); AUDIT_R1_Q1;
- OPERATOR_DECISIONS_2026-10-30 §B;
- PLAN_terminal_reinvestment.md (D2, O1–O8); SPEC_factor_led_v2 §1;
- SPEC_m3m (qwen_c); SPEC_m3o (the books).

## 0. What exists, and what is missing (PLAN §3Q items)

| PLAN item | Exists | Missing |
|---|---|---|
| 1. Reassess rev 26's failures without retuning | RR_Q1 §1. Readers found nothing *wrong*; every miss was "questionable". The dominant fault is C4: a long-run margin premium argued from short or absent evidence, in 8/9 names in both iterations. Then C2 (memo against inputs), 6/9, and C1 (wrong basis, entity, period, or withdrawn), 5–7/9 | A design in which C1, C2 and C4 are checked by code, not left to readers |
| 2. Validate growth, margins, reinvestment, cost of capital, taxes, dilution, long-run mechanics | D2 math: reference `scratch/rev23/terminal_d2/reference_d2.py` on simulated firms with known value (`synthetic.py`: A–I, compounder to insurer, utility, REIT, lessee). Desk port `1dcb3b2` (branch `d2-port`) reproduces it to 4e-16 | D2 in the pipeline that actually runs (qwen_c). D2 is on no live branch. Dilution: no forward share path |
| 3. Resolve D2's year-6+ convention | Measured: margin 8%→12% over the fade puts the revenue convention 20.5% above the earnings convention; 12%→8% gives −17.8% | The truth test that would decide it (PLAN_terminal_reinvestment:463-466), then the ruling (B1) |
| 4. Business models where one equation is invalid | Family classifier (`population_ranges.family_for`). O3 (financials on retained equity) and O6 (equity REITs through D2, mortgage REITs financial) are approved. Gate 16 makes depleting producers non-actionable | Per-family routes wired into one engine. Today 30/160 nominees are `family_not_built` and still valued with the operating formula |
| 5. Qwen reasons, code computes | Rev 26 typed inputs, desk arithmetic. qwen_c (3M) cites evidence under a verified contract (3N: strict recall 0.90 on DEV after contract v3), and its SCOPE line forbids valuing | A qwen_c valuation task: typed assumptions, each cited under the qwen_c contract, computed by a deterministic desk |
| 6. Bear/base/bull coherent and source-backed | Desk monotonicity Bear ≤ Base ≤ Bull (`fiduciary_gate` 141-147); probabilities sum checked | A scenario-coherence check on the *inputs*, not only the values |
| 7. Refuse analyses where prose, identities and numbers contradict | `verify_memo` table-number check; `memo_prose_number_mismatch` annotates only | A memo whose numbers and labels come from code. Identity checks on every computed path |
| 8. Preserve untouched holdouts | Listed in RR_Q1 §5 | Stays as is: CTVA, NHC, TTAM, CLDT and the Stage-2 sealed names are not opened by 3Q (B5) |
| 9. Independent valuation and method review on eligible new evidence | No retrospective window is both eligible (decision ≥ 2025-10-01, after Qwen's cutoff) and certified (CLOSE_3L: 0/163). The eligible evidence is prospective | A prospective, witnessed 3Q panel drawn from the 2026-10-30 formation onward (§6 E3) |

## 1. Design rules (from the records, not new)

1. **The AI chooses every input; Python computes; code checks against outside anchors.** The backbone failed by choosing
   inputs in code; E0 failed by letting the AI do everything (memory `claude-builds-not-part-of-system`). The middle is
   the only design the records support.
2. **Right, not self-flagging.** A check that only flags leaves an unattended system making the error. Every check below
   either (a) is a contract rule enforced as qwen_c enforces quotes (the input is unsupported until repaired), or (b) is an
   annotation on a measurement that must not be deleted (non-negotiable 3). §4 says which, per check.
3. **No silent substitution.** An unsupported input is never replaced by a code default. The sample is recorded as
   `valuation_incomplete` with the reason. The plan's objective says so explicitly.
4. **No retuning on consumed evidence.** The 12-name rev 26 panel is a regression set only: it shows whether known defects
   are gone. It does not pick parameters.
5. **`0.0` is a value.** Margins, tax and growth of zero are legal inputs (non-negotiable 4).

## 2. Architecture

- **Where it lives:** inside qwen_c, on a new rs2 branch `review-2026-10/m3q` from `d2f3f15` (the 3N line).
  - Not on `r26-int`: it carries the kappa desk and the rev 26 monolith.
  - Not on `phase-4`: it has no bridge and no D2.
  - Recommended B2: D2 enters 3Q, but as a fresh port into qwen_c, not as a merge of `d2-port`/`d2-facts`. A merge would
    pull in the screener `d2-fields` branch and its binding merge order.
- **Modules (new):**
  - `qwen_c/value/facts.py`: point-in-time inputs from SEC companyfacts through `sec_store` (pinned bytes; a fact counts
    only if its accession was accepted before the packet time T):
    - revenue, operating income, net income, D&A, capex, ΔNWC components, tax provision and pretax income;
    - shares (diluted, and the latest cover-page count), debt, cash, lease liabilities and ROU depreciation (lease field L1),
      acquired-intangible amortization.
    - Each fact keeps its accession, tag, period and form.
    - This replaces the screener-field route, so 3Q needs no screener change and no Vercel risk.
  - `qwen_c/value/desk.py`: D2, ported from `reference_d2.py` and the `1dcb3b2` formula. It covers:
    - explicit years on levels (O7);
    - the wedge fade over F (O2) and the cited investment path H (O2c);
    - vintages D&A with a pooled fallback;
    - τ·A run-off, and the PV of the remaining shield after N;
    - the financial route (O3) and the REIT route (O6);
    - no sustaining charge `s` (O8);
    - the cost of equity from the code anchor, as in rev 26 (`capability_test.py:2506-2517`), ported;
    - measured leverage δ at market weights (O5).
    - No base-cash-flow scaling exists in this desk, so the kappa defect cannot occur.
  - `qwen_c/value/checks.py`: checks V1–V10 (§4).
  - `qwen_c/value/memo.py`: the memo is a code table plus the model's own reason strings, each bound to the input it
    explains. The prose carries no free numbers: every figure must be listed (the qwen_c figure rule, contract v3).
- **The Qwen task `valuation_inputs`** (prompt `m3m.prompt.v4`; a versioned prompt change, B4). It returns typed JSON:
  - revenue growth for years 1–2;
  - the operating margin for years 1–2;
  - the normalized year (3–5), with `baseline` (min/p25/median/p75/max/last of the filed record) and `delta_pts`;
  - the transition shape;
  - the fade length F, the long-run margin, RONIC_T and terminal g;
  - an optional cited capex/investment path (O2c);
  - Bear/Base/Bull deltas and probabilities;
  - one reason string per input.
  - Every input carries `fact_ids` and passing `quotes`, checked by `contract.check_claim`, the same machinery 3N
    validated.
  - The SCOPE line is amended for this task only. The other tasks keep "do not value".
  - **The other tasks' prompts stay byte-identical.** The formations (FQ) run them. WO_Q5 tests the SYSTEM and task texts'
    hashes against `d2f3f15`, so the version bump touches only `valuation_inputs`. A CHANGE_REGISTER row is added anyway.
- **Seeds:** 2 per name (1000, 3000), as in 3N. The spread is reported (V-annotation), not gated.

## 3. The fade convention (B1): resolve it by a truth test, then rule

Work order WO_Q3, CPU only, in `scratch/rev23/terminal_d2/` (the simulator already takes `margin(t)` and capacity paths).

**Firms (new, simulated with known value):**
- `M1_pricing`: the margin rises from 8% to 12% over years 6–15 from price or mix. Capacity and unit cost are unchanged,
  so no new capital is needed.
- `M2_invested`: the same margin path, bought by automation capex (unit cost of new vintages up, operating cost down).
- `M3_mixed`: half of each.
- `M4_decline` and `M5_decline_invested`: the margin falls from 12% to 8%, without and with capacity retirement.

**Candidates:**
- **(R)** revenue convention, as built;
- **(E)** earnings convention;
- **(X)** revenue-tied capital at the measured sales-to-capital, plus an explicit, cited margin-investment item when the
  analyst says the margin is bought.
- **(C)** capital stock, the parameter-free form of (X): capital is X/ROC on D2's return path (1/ROC interpolated from
  r_tc to RONIC_T), and reinvestment is the change in that capital. It needs no new analyst input (added in WO_Q3).

**Pre-registered rule:**
1. A candidate passes a firm if |value error| ≤ 3% against truth. The ±3% is D2's registered acceptance tolerance
   (PLAN_terminal_reinvestment:207, 249). Corrected 2026-10-30: v0 said 2%.
2. Rule for the single candidate that passes all five firms.
3. If none passes all five, adopt (X): the typed driver. Here the analyst *must* state the margin source, with a citation,
   and an uncited source takes (R) with the annotation `fade_margin_source_uncited`.

Until B1 is ruled, the desk runs (R) and stamps `fade_convention_unruled`.

**Result (RR_Q3, 2026-10-30):** R passes 5/5 (max error 0.59%); E fails 4/5 and C fails 3/5. **B1 = R.**
- Exploratory: C without the wedge also passes (max 1.8%).
- v1.1 (RR_Q3 §5): when the investment starts in year 8, R with the wedge overvalues by 11.9%; C without the wedge errs by 2.4%.
  - So `fade_margin_investment_after_year5` becomes a contract rule in V-checks (a later programme must enter through O2c).
  - v1.2 on new firms N1–N5 (RR_Q3 §6): R with the wedge 2/5 (fails every post-year-5 programme, +7 to +13%); C without the
    wedge 4/5 (N1 +3.34%). By the rule, B1 = R stays plus the O2c contract rule. C remains an open option (operator, O2).

## 4. The checks

| # | Check | Kind | Catches (RR_Q1 class) |
|---|---|---|---|
| V1 | Identities and units on every path: revenue × margin = earnings; flows, PV and per-share sums recompute; shares > 0; the equity frame consistent with net debt; financial-route clean surplus | Contract: a failure means the sample is refused for repair, then `valuation_incomplete` | engine defects |
| V2 | Seam continuity: the year-5 to year-6 flow ratio, reported. Outside [0.67, 1.5] without a cited investment state (O2c) | Annotation `flow_seam_out_of_band` | the kappa class |
| V3 | **Premium over the record.** Any typed explicit-year margin (years 1-2), the normalized margin or the long-run margin (on the financial route, the ROE) outside the filed [min, max] (amended 2026-10-31, CROSS_CHECK_Q3 1) of the last ≥ 5 fiscal years needs a cited, quote-verified fact that speaks to a span of ≥ 2 years. A half-year, one peak year or guidance alone does not count | Contract: the input is unsupported, one repair turn, then `valuation_incomplete: unsupported_premium` | C4 (8/9 names) |
| V4 | Basis: a cited margin fact must be on the filed GAAP operating basis (a statement fact from `facts.py`). Company-adjusted or third-party facts may explain the margin but not set it | Contract for the level; annotation for supporting cites | C1 (DAR's adjusted EBITDA, MCY's misread figure) |
| V5 | Entity, period, withdrawn: each cited quote must be verified in the packet (`quote_found`), and its period must not be after T. A fact the packet marks withdrawn or superseded cannot be cited | Contract | C1 (ITGR's withdrawn outlook, VSNT's NBC fact) |
| V6 | Labels from code: the growth trajectory (as rev 26), the cycle position (the normalized margin's percentile in the filed record), margin persistence (the long-run margin against the record median). The model's labels are kept as `*_submitted` | Code-owned | C2 ("mid-cycle" above 7 of 8 years) |
| V7 | Decliner terminal: Base revenue shrinking in most explicit years requires terminal g ≤ 0, unless a cited fact supports a return to growth | Contract | VSNT |
| V8 | Tax: measured, or the multi-year median (≥ 3 years); else `tax_unavailable`. Never a stamped 21% | Code-owned | DAR/MSGE clip |
| V9 | Scenario coherence: each scenario's inputs ordered (Bear ≤ Base ≤ Bull on growth, margin and RONIC_T, unless a reason is cited); probabilities sum to 1 ± 0.01; values monotone | Contract | PLAN item 6 |
| V10 | Memo: numbers and labels from code; the reason strings pass the qwen_c figure rule. A reason that contradicts its own input's direction (says "below the median" when the input is above) is refused | Contract | C2 (DAC, MSGE, TASK) |

Every annotation is carried on the verdict and counted in the reports. No annotation removes a name from any measurement.

## 5. Business-model families (B7, recommended defaults)

| Family (census of 160 nominees) | Route |
|---|---|
| Operating (81) | D2 operating |
| Commodity (29) | D2 operating with the cyclicality score feeding V6. Depleting producers keep gate 16 (non-actionable) unless a cited path passes O8's C/C2 test |
| Financial (20) | D2 financial route, retained equity (O3). A balance-sheet test confirms the family (census findings: V operating, STT financial) |
| Equity REIT | D2 with δ (O6); the recurring-capex gap is diagnostic. *Corrected 2026-10-31 (CROSS_CHECK_Q7 15): not built. The runner refuses REITs (ruling 17, RR_Q3: `family_not_built`), so in E3 they are named no-calls, and that is coverage lost.* |
| Mortgage REIT | Financial route (O6) |
| Utility (5) | **No call, `family_not_built: utility`.** Rate-base growth exists only as synthetic firm G; the route is not validated |
| Pre-profit (10), shells, holding companies | **No call, with the stated reason.** E_0 ≤ 0 stays refused (O7) |

**Bias report:** the median log(value/price) per family on the E3 panel, beside the whole panel's. Reported, never tuned.

## 6. Evaluation

| Stage | What | Bar | GPU |
|---|---|---|---|
| E1 | Synthetic truth: firms A–I plus M1–M5 through `desk.py` | `desk.py` reproduces `reference_d2.py` to ≤ 1e-9 on every firm. Truth errors equal to the reference's recorded errors (no new error). V1 passes on all | no |
| E2 | Regression on the consumed 12-name panel (the rev 26 dates, one run, 2 seeds, no parameter changes after viewing) | Report only:<ul><li>V2–V10 rates;</li><li>the seam on DAR/MCY/MSGE/DAC;</li><li>value/price beside rev 26's;</li><li>no-call counts.</li></ul>It cannot pass or fail the design (B5: regression set only) | yes, ~24 runs |
| E3 | Prospective panel: every FQ-book name and a hash-ordered draw of other nominees at the 2026-10-30 formation (and later formations), valued once, frozen, hash pushed to the records branch before any outcome (the WO_O2 witness pattern) | Recommended B6:<ul><li>contract-level V checks pass or are honestly incomplete on ≥ 80% of callable names;</li><li>blind coherence reading (fresh Opus readers, inputs masked, the amended rubric) ≥ 80% coherent and 0 incoherent;</li><li>direction unanimity across seeds ≥ 80%.</li></ul> | yes, ~2 × panel size |
| E4 | Outcomes: value against price drift, recorded in 3S's monthly report | No bar in 3Q. 3S's minimum-record rule applies. No skill claim | no |

- **Ship bar for 3Q:** E1 passes, E2 is reported, E3 meets the B6 bar.
- **Portfolio-weight authority (PLAN pass 5):** this needs E4 evidence over 3S's minimum record *and* an explicit operator
  approval. 3Q never grants it.

**Formation runs pre-empt 3Q GPU work.** 3P's live week and 3Q runs never overlap a formation. A smoke turn and a blind
Opus cross-check precede E2 (standing rules).

## 7. Work orders (proposed)

| WO | Content | Needs | GPU |
|---|---|---|---|
| WO_Q2 | Port D2 to `qwen_c/value/desk.py`, plus the synthetic suite E1 (A–I) | none | no |
| WO_Q3 | The fade truth test, M1–M5 (§3) | none (it produces B1's evidence) | no |
| WO_Q4 | `facts.py`: PIT companyfacts through `sec_store`, with tests on stored bytes; coverage of the 160 nominees | none | no |
| WO_Q5 | The `valuation_inputs` task, prompt v4, `checks.py` V1–V10, `memo.py`; offline tests on canned model outputs, including rev 26's recorded faults rewritten as fixtures (DAR adjusted EBITDA, MSGE 14.0% > 13.5%, ITGR withdrawn outlook, VSNT decliner) | B4, B7 | no |
| WO_Q6 | Cross-check (fresh blind Opus), smoke, E2 regression | B1 or the (R) default; B5; B10 | yes |
| WO_Q7 | E3 prospective panel, witness push, blind readers, bias report; then CLOSE_3Q | B6, B9 | yes |

## 8. Decisions (OPERATOR_DECISIONS §B), the recommended defaults, and what waits on each

| # | Recommended default | Waits |
|---|---|---|
| B1 fade convention | Decide by §3's truth test. Until then (R) plus a stamp | WO_Q6 can run on the default; the freeze needs the ruling |
| B2 D2 in 3Q, base branch | Yes; a fresh port into qwen_c on `review-2026-10/m3q` from `d2f3f15` | WO_Q2 assumes it |
| B3 materiality threshold | Defer. The interval rule is reported (release counts at 2/5/10%) and gates nothing, since valuation is diagnostic | nothing |
| B4 PACK/prompt approval | The standing approval (2026-09-27) covers prompt v4: versioned, recorded, cross-checked | WO_Q5 |
| B5 evidence | 12-name panel as regression only; holdouts stay sealed; new panels prospective only | WO_Q6, WO_Q7 |
| B6 pass bar | §6 E3 | WO_Q7 |
| B7 families | §5 | WO_Q5 |
| B8 priority | V3 and V10 first (C4 and C2 are the measured failures), then V7, then the contract fields that are unfilled (no code owner; they stay unfilled and non-actionable) | WO_Q5 order |
| B9 diagnostic only | Yes | everything after WO_Q5 |
| B10 GPU budget | E2 ≈ 24 runs, E3 ≈ 2 × panel (≈ 120 runs for a 60-name panel), outside formation windows | WO_Q6, WO_Q7 |

## 9. Limits (stated now)

- **3Q cannot show valuation accuracy.** No certified, eligible retrospective window exists. 3Q can show sound arithmetic
  (E1) and supported, coherent inputs (E3). Accuracy is an E4/3S question measured over months.
- **E2 is on consumed names.** Its numbers describe the defects, not the design's quality.
- **The readers** are the same model family as the builder (fresh blind Opus; no outside AI unless the operator asks).
- **Utilities, pre-profit names and shells** get no call. That is coverage lost, and it is reported as such.
