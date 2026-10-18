# Cross-check request 21: the revision-25 failure, the switch to Qwen, the D2 terminal-value rebuild, its data coverage, and the short form before its GPU test

Written 2026-10-18 by the coordinator. **This document is self-contained.** Where an answer would rest on code you cannot see, say so
rather than assume. Critique freely. The coordinator rules on each point, and the operator decides.

- **Code:** `github.com/riperdy-tech/rs2-local`. Branches:
  - `review-2026-10/rev25-bridge`: the revision-25 bridge;
  - `review-2026-10/ollama-raw`: our own Qwen prompt rendering and tool-call reader, plus the crux message fix;
  - `review-2026-10/d2-port`: the D2 desk formula;
  - `review-2026-10/d2-facts`: the D2 pack facts.

  The screener's new data fields are on a stock-screener branch that is not public; section 6 describes them.
- **Records:** branch `docs/rev23-records`, folder `docs/rev23/`.
  - `PLAN_terminal_reinvestment.md`: the D2 plan, every ruling, and the coverage records at its end;
  - `PROBLEM_STATEMENT_terminal_reinvestment.md`;
  - `STAGE1_R25_REPORT.md`;
  - `PLAN_phase4_qwen_restoration.md`;
  - the briefs `BRIEF_D2a`, `D2b1`–`D2b4`, `D2r`, `P4B` and `SF`;
  - cross-check 20.

## 1. The system, in brief
- **A stock screener** nominates about 160 US-listed stocks.
- **A local AI analyst** values each one: it researches, chooses the valuation inputs, and writes a memorandum and a structured contract.
- **Code does all the arithmetic** through a "desk" tool, and applies the gates.
- **Real money will depend on the verdicts.** Real-money trading is halted (`KIS_HALT`), and everything here is paper and test only.

## 2. What happened since cross-check 20

### 2a. Revision 25 on Muse failed Stage 1
- **What revision 25 is:** the normalization bridge. The analyst declares revenue growth and earnings margin per year, plus normalization
  fields: normalized margin, horizon, structural growth, flags and three classifications. The desk cross-checks them (checks C1–C5 and
  K1–K4) and asks for a named reason when they disagree.
- **The test:** arms B and C (C withheld consensus in pass 1) against arm A, which is revision 24.
- **Coherence:** A 6/8, B 5/10, C 4/10. B and C were also worse than A on compliance and citations.
- **The consequence:** under the pre-registered kill rule, no revision 26 followed. The model was changed instead.

### 2b. The model is now Qwen 3.8 27B (Q5_K_M, charter v3.3)
Qwen runs on the revision-24 desk, through a new provider, `ollama_raw`.
- **Why the new provider:** Ollama 0.40.3 (auto-updated on 2026-10-11) drops array-typed properties nested inside array items in tool
  calls. The trigger is the item schema, upstream of Qwen's parser, probably constrained decoding; this is not proven.
- **What `ollama_raw` does:**
  - renders the official chat template with jinja2;
  - calls `/api/generate` with `raw:true`;
  - parses Qwen's XML tool calls with our own reader.
- **Restoration, one run per stock, 7 stocks:**
  - 7 of 7 passed the bar; 6 are coherent and 1 questionable (BUD);
  - all 4 directional calls rest on a verified crux;
  - MCY carries a copying signature (1.02× the reference value);
  - twice the memo disagreed with the verdict (TASK, GOLD). The cause was the all-or-nothing crux rule. A message fix now states plainly
    that one failing crux entry invalidates the crux.

### 2c. The terminal-value problem and the design D2
**The problem:** a "year-6 seam".
- Years 1–5 were valued on owner earnings.
- The fade and the terminal were valued on earnings × (1 − g/RONIC).
- Where the two reinvestment conventions met, cash flow jumped.

**D2's years 1–5, valued on filed levels:**

> Flow_t = X_t − (1 − δ)(capex_t − D&A_org,t + ΔNWC_t) − (P_t − ROU_t) + τ·A_t

- X is net income plus after-tax acquired-intangible amortization.
- D&A_org is D&A less right-of-use depreciation less acquired amortization.
- P is lease principal and ROU is right-of-use depreciation.
- τ·A is the amortization tax shield.
- δ is measured leverage: non-lease debt over (debt + market cap).
- Returns on new investment are converted to equity returns with the measured cost of debt:
  ROE = ROC + δ/(1−δ)·(ROC − kd(1−τ)).

**D2's long run:**
- **The year-5 wedge:** w_5 = (I_5 − I*_5)/R_5, with I*_5 = (g_6/RONIC_0)·E_5. It fades linearly to 0 over the fade period F.
- **A cited capex path:** the analyst may give one for H years beyond year 5. The levels then run to year 5 + H, and the funded path
  follows with no wedge.
- **The terminal:** E_{N+1}(1 − g_T/RONIC_T)/(r − g_T).
- **Financials** use E_t(1 − g_{t+1}/ROE_t) from year 1.

**No sustaining charge (ruling O8):**
- A measured "sustaining" charge for depleting firms was tested and removed: it double counts.
- Depleters' finding-and-development cost against DD&A, and REITs' recurring capex against D&A, are diagnostics only.
- Two synthetic depleters fail the ±3% truth bar on the default path (+7.37% and +4.53%). They pass only on a cited escalation path, and
  are reported that way, never as default passes.

**The port's regression gates, all passed and re-run by the coordinator:**
- With no D2 inputs, the desk is byte-identical to the old one.
- The legacy-equivalent D2 form reproduces today's values to the cent and to 1e-6 relative.
- On 12 synthetic firms built from simulated statements, the value and every annual flow match an independent reference implementation
  to ≤ 4e-16.
- Removing the diagnostics' inputs changes no value.
- The full suite shows the same 42 known failures by name.

### 2d. D2 needs more filed data: coverage, and the policy for gaps
**Coverage:**
- At first, D2 had complete inputs for 57 of 160 names.
- New D2-only screener fields brought it to **99 of 160** in the real pack build (84 operating, 15 financial). They cover:
  - lease principal and lease interest, right-of-use depreciation;
  - IFRS and non-operating borrowing interest;
  - gross PP&E and the amortization schedule;
  - industry capex tags, with non-lease debt;
  - since then, D2-only D&A and revenue fallbacks.
- **Existing fields are never changed.** Today's numbers do not move, and that is proven field by field on test ticker sets.

**Fallback tags are trusted only on vendor agreement:**
- A fallback (rung) value is used only within 0.7–1.3× the data vendor's figure.
- Outside that band, the input is unavailable. With no vendor figure, it is used and stamped unverified.
- A cost of debt outside 1–20% counts as unmeasured.
- Nothing is ever filled with a guess. A missing input means `d2` is null, with the missing members named.

**Remaining gaps, as measured:**
- **Pooled capex/D&A (27 names).** Many file capex under company-extension XBRL tags, which the SEC company-facts bulk file omits.
  - A recovery rule using the SEC Financial Statement Data Sets picks the screener's known capex in 96% of the cases where both exist.
  - It recovers only 3 names, all on extension tags, which matched 0 of 9 in control cases. The vendor has no multi-year capex to verify
    them.
- **Non-USD reporters.** A currency fix would recover about 5.
  - **Defect found along the way:** where those filers tag USD convenience translations, the screener ships flows at the year-end rate.
    The convention is the period average.
- **A materiality rule** (proposed, threshold not yet set by the operator):
  - a missing kd, δ or amortization shield blocks D2 only if valuing at both ends of its range moves the value by more than the threshold;
  - otherwise the name is valued at the **lower** end and stamped;
  - on neutral inputs it would release 8, 10 or 14 names at thresholds of 2%, 5% or 10%.
- **The policy for the names left over,** ruled after ChatGPT's and Gemini's reviews:
  - D2 is the only valuation eligible for decisions;
  - a name without complete D2 inputs gets `unvaluable_missing_input`;
  - the old desk runs on it as a separately labelled screening view, never ranked with D2 values and never in a book;
  - an uncertain financial-or-operating route is a stop.

### 2e. D2 needs the analyst's revenue and margin path, so we tested Qwen on the revision-25 bridge (MSGE, one run)
The production Qwen arm (revision 24) asks for owner-earnings growth, not a revenue and margin path.

**The result:**
- **The verdict:** overvalued, Base $42.89, against $45.08 on revision 24, at a price of $79.60.
- **The crux and citations:** the crux is valid (long-run margin 8.5% against the 23.3% the price implies), and citations resolved 4/4.
- **Refusals:** 5 of 8 desk calls were refused, because the C1, C3, C4, C5 and K1 checks kept asking for reasons. The loop guard fired twice.
- **Time:** 127 minutes, against 73.
- **The outcome class:** `reason_loop`, the same failure pattern as Muse's Stage 1, though Qwen recovered to a coherent result.

**From Qwen's reasoning notes (one run, indicative):**
- It understood the margin basis (X).
- Its 12% "normal" margin was its own estimate (adjusted operating income less interest and tax). That estimate happens to sit near the
  12.8% operating margin, so the basis check C5 largely raised a false alarm.
- The pack's margin facts are hard to reconcile:
  - the X-basis history (median 5.1%) is depressed by one-off impairments and restructuring;
  - the desk's default year-5 margin is 8.1%;
  - consensus implies about 12% in years 1–2.
- Some C1 and C3 failures were genuine inconsistencies between its own declarations.

## 3. What we propose now: the short form (desk schema 25.2), with its GPU test

**The analyst gives, per scenario:**
- five revenue-growth values and five X-basis earnings-margin values;
- every revision-24 input, unchanged;
- optionally, later and in part (c): a cited capex plan.

**Removed:**
- the normalization block;
- every C and K cross-check, with its reason fields;
- the two-pass protocol.

The revision-24 written report keeps near-term and normalized earnings and the three labels (margin persistence, cycle position, growth
trajectory). They are read, not cross-checked by code.

**Added to the pack:**
- the margin basis in plain words;
- the X-basis margin history per year, **with and without one-offs** (filed impairment and restructuring lines, added back after tax);
- the X-basis margin the consensus EPS levels imply for years 1–2.

**The basis flag (annotate, never refuse):**
- each scenario's year-1 and year-2 margin against the consensus-implied margin;
- outside [0.67, 1.5], `margin_basis_gap` is stamped and shown;
- with no consensus, `no_basis_check_no_consensus`.

This compares forecast with forecast. An earlier idea, comparing the forecast with history, was dropped: history versus forecast is no
basis test.

**The test, registered before any run:**
- MSGE, TASK and DAC; DAC is the cyclical name. Each has a revision-24 Qwen run for comparison. D2 stays off: this tests the form only.
- It passes only if all of these hold:
  - no desk refusals or loop markers;
  - minutes within about 1.2× revision 24;
  - a valid crux and verified citations;
  - every declared margin on the X basis (the coordinator checks this against the history and the consensus);
  - no unexplained basis flag.
- On failure, option B:
  - the desk builds revenue as earnings over the held base margin, stamped;
  - no analyst margin path, and no further form iterations.

## 4. The coordinator's own concerns
1. **Dropping the cross-checks removes the automated catch** for an analyst who mistakes a cyclical peak or trough for normal. Only the
   written labels and D2's diagnostics remain: the implied return of the explicit years, and the clean-surplus ROIC roll-forward against
   RONIC_T.
2. **The basis flag covers only years 1–2,** and only names with consensus. Small names get no basis check.
3. **One run diagnosed the loop.** The "pack facts are hard to reconcile" explanation is a hypothesis.
4. **The vendor-agreement band of 0.7–1.3 was chosen, not calibrated.** The plan is to calibrate it field by field from filed-versus-vendor
   ratios before the coverage effect is looked at.
5. **The comparison with revision 24** is the same model on the same frozen evidence, but one run per name. Run-to-run variance is not
   measured.

## 5. Questions
1. **The short form:** is dropping every normalization cross-check sound, given D2's diagnostics? Which single check, if any, would you
   keep, and why would it not cause the loop?
2. **The basis flag:** is consensus-implied margin the right anchor for a basis check? Is [0.67, 1.5] sensible? What should replace it for
   names without consensus?
3. **The pack's margin facts:** is "with and without one-offs" (impairment and restructuring added back after tax) a sound normalization
   to show, or does it invite the analyst to treat recurring "one-offs" as non-recurring?
4. **The test design:** are 3 names with one run each enough to choose between the short form and option B? What result would make you
   reject the short form even if it passes the registered rules?
5. **D2 itself:**
   - Any flaw in the levels leg, the wedge fade, the O2c cited path, the equity-return conversion, or the financial route?
   - Is valuing at the lower end under the materiality rule the right asymmetry?
6. **Coverage policy:** D2-only valuation, the old desk as a labelled screening view, and an uncertain route as a stop. Anything unsafe for
   real money?
7. **The `ollama_raw` provider:** owning the chat template and the tool-call parser ourselves. What are the risks, and what tests would you
   require?
8. **Anything else** a careful reviewer would challenge.

At the end, give:
- your verdict on running the 3-name test as designed (go / change / no-go);
- the one change you would make first;
- the result that would most worry you.
