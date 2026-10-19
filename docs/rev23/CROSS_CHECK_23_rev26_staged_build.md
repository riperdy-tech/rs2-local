# Cross-check request 23: the staged analyst (revision 26) is built. Review it before its first GPU run.

Written 2026-10-19 by the coordinator. **This document is self-contained.** Where an answer rests on code you cannot see, say so. You
advise, the coordinator rules on each point, and the operator decides.

- **Code:** `github.com/riperdy-tech/rs2-local`, branch `review-2026-10/r26-int`, which merges r26-harness, r26-desk and r26-pack.
  The key files:
  - `tools/r26_forecast.py`: the forecast schema, the path builder, the bridge, alternative paths, aggregation and the pull ratio;
  - `tools/audit_202608/r26_stages.py`: the stage runner, stage 1 and the fact checks;
  - `tools/audit_202608/r26_late.py`: stages 2–4, the TASK texts and the memo verifier;
  - `tools/audit_202608/r26_blind.py`: the blind pack, the leak audit, the margin bar and the consensus correction.
- **Records:** branch `docs/rev23-records`, folder `docs/rev23/`:
  - `SPEC_rev26_staged_analyst.md`, the design;
  - `PLAN_terminal_reinvestment.md`, whose end sections hold the build log and every ruling;
  - `briefs/R26_A2_TASK_TEXTS.md`, the exact model-facing stage texts;
  - cross-checks 21 and 22.

## 1. Why this exists
A local 27B analyst (Qwen 3.8, Q5_K_M, one RTX 3090) values about 160 stocks; code does all arithmetic. Two briefing-form designs failed.
- **The long form** looped on 10 refusing consistency checks.
- **The short form** removed the loops, but a blind reader found 2 of 3 runs incoherent: it copied a printed consensus margin (which was on
  the wrong basis), mistranslated between margin bases, misread a fact, and normalized circularly.

Cross-check 22 (ChatGPT and Gemini agreed) recommended changing the architecture, not the form. This is that architecture, now built and
unit-tested, with no model run yet.

## 2. The design as built
1. **Stage 1, research and fact ledger** (its own session).
   - **What it sees:** a *blind pack*, with every consensus-, price- and reference-derived line removed by source class, narrative filtered
     sentence by sentence, and a leak audit that proves no removed number survives.
   - **What it does:** researches with tools, then registers facts. Each fact carries entity, metric, period, value, unit, basis,
     `duration_years`, source and an exact quote.
   - **What code checks:** that the quote exists verbatim in its source; that the metric and entity words occur within ±300 characters
     (for pack sources the company name or ticker counts as present, stamped); and that the value appears in the quote. Only facts passing
     the first two checks are usable.
2. **Stage 2, the blind forecast** (a fresh session, K = 3 samples on seeds s..s+2).
   - **What it sees:** the blind pack, the usable dossier and the filed operating-margin history (min / p25 / median / p75 / max / last,
     with no "default").
   - **What it submits, per scenario:**
     - years 1–2 revenue growth and *filed operating margin*;
     - a normalized state in year N (3..5), given as a baseline percentile plus `delta_pts`, which code sums;
     - a transition shape (linear, step, or hold then linear);
     - the long-run operating margin and the fade;
     - fact IDs for each part;
     - for Base, three labels (margin persistence, cycle position, growth trajectory), each with fact IDs.
   - **Validation is structure only,** with one repair turn. Numbers are never bounded.
   - **What code does:**
     - builds the path;
     - converts operating margin to the valuation's after-tax basis by a **bridge calibrated to the filed base year**:
       K_0 = OI_0 − X_0/(1−τ), held in dollars, and X_t = (op_t − K_0/R_t)(1−τ). It is exact at the base year and needs only τ, OI_0 and X_0;
     - values the forecast on the existing desk arithmetic;
     - computes an alternative path wherever a cited fact's `duration_years` expires (the margin fades to the baseline afterwards), as
       information, never a substitute;
     - records the median and the spread.
   - **Financials,** and any name filing no operating income, use the after-tax margin directly (the identity bridge).
3. **Stage 3, reveal and reconcile** (a fresh session). It sees:
   - the median forecast's *numbers only*;
   - the three values;
   - the price and what the price implies;
   - a **basis-corrected consensus** (vendor EPS rescaled by filed / vendor base-year EPS; *not comparable* if the ratio is outside [0.5, 2],
     there are fewer than 3 EPS analysts, or a vintage or share test fails);
   - the price and momentum lines removed from the blind pack;
   - the diagnostics.

   It states the crux (verified quotes; one entry failing invalidates the crux, which means no call). It may revise **once**, citing a fact
   ID. Code records the pre and post values and the **pull ratio** `|m_post − m_pre| / |m_cons − m_pre|`.
   - **No call** when the three samples split by direction, or the crux is invalid.
4. **Stage 4, the memo** (a fresh session). It is written from a **frozen** desk table.
   - Code fills every numeric contract field.
   - A verifier flags a memo number that differs from its labelled table value, a verdict-word mismatch, or a label mismatch. Any flag makes
     the result non-actionable.

## 3. Rulings where we departed from the reviewers, or where the data forced a choice
- **Rejected:** an automatic code fade on a failed repair, which is code substituting judgment; we use no call instead. Also rejected: a
  prescriptive audit wording such as "fade to the 10-year median"; we pose questions only.
- **The median sample is reported, not crowned:** a direction split means no call.
- **The bridge:** an earlier design needed net interest and amortization separately. Our offline probe found those missing for 5 of the 7
  stored names, so we replaced it with the base-year calibration above. **Its assumption:** non-operating items, including interest and
  amortization, are held in dollars at their base-year level.
- **PACS:** files no D&A in its 10-Ks, so it has no code-owned base cash flow. It is recorded as `no_call base_cf_unavailable`; we invent
  no base.
- **GOLD:** files no operating income, so it goes to the after-tax basis throughout. A generic rule, never by ticker.
- **BUD:** no filed diluted share count, so the consensus correction uses the pack's code-owned share count, stamped.
- **Consensus comparability (rules unchanged):** comparable for TASK, PACS and BUD, and for GOLD in year 2.
  - MSGE: 2 analysts.
  - DAC: 1 analyst, and its vintage fails.
  - MCY: a real 24% basis gap.
- **The anchoring canary,** on MSGE, TASK, DAC and BUD: stage 3 is re-run with the revealed consensus margins shifted ±3 points. Where no
  comparable consensus exists, a **constructed test consensus** (the stage-2 median margins ± 3 points) is revealed. It is test-only and
  labelled.

## 4. The evaluation, registered before any run (SPEC section 6)
- **The panel:** 12 names.
  - 7 restoration names: MSGE, TASK, PACS, DAC, BUD, GOLD, MCY;
  - 5 drawn by a pre-existing hash order: OGE, HNRG, PTCT, LPG, ITGR;
  - a 4-name unseen holdout, drawn later, the same way.
- **The runs:**
  - Stage 1 runs once per name and its dossier is frozen.
  - Stages 2–4 re-run per design iteration, at about 10 minutes a name; at most 3 iterations.
- **Two readers per run,** each a fresh agent given a masked extract (no values, price, verdict or results), scoring a 4-criterion rubric:
  - facts correct;
  - path consistent with the stated economics and labels;
  - no unsupported copy of a revealed number;
  - the normalized state defended by evidence of matching duration.
- **A pass needs all of:**
  - 0 loops;
  - 0 incoherent;
  - 10 of 12 or more coherent;
  - median K = 3 spread ≤ 20%;
  - 10 of 12 or more with unanimous direction;
  - median unverified pull ≤ 0.15;
  - 0 memo verdict mismatches.

  A pass authorizes a book-wide *paper* run only.

## 5. The GPU plan this review gates
1. Stage P for the 5 new names: research collection, on the GPU.
2. A **smoke test:** one name, the first model turn of stages 1 and 2. The runner refuses any real run until the smoke passes on the
   current tree.
3. Stage 1 on all 12 (about 6–9 hours).
4. Stages 2–4, iteration 1 (about 2 hours).
5. The canary (about 1 hour).

**Throughout,** the runner stops at the first code-defect failure.

## 6. The coordinator's own concerns
1. **The calibrated bridge holds the non-operating items flat in dollars.** For a company deleveraging or levering fast, the after-tax
   margin path is biased. Is that acceptable for a 5-year path, or should debt-driven interest change be modelled?
2. **The ±300-character proximity check** may reject legitimate table facts and admit wrong ones in dense prose. It is generic but crude.
3. **Stage 3 sees no stage-2 reasoning,** only numbers. That protects against self-justification, but it may make the revision step weak.
4. **The verifier only checks numbers written as "Label: value".** A memo can still state wrong numbers in prose.
5. **Consensus is comparable for only 3–4 of 12 names,** so the anchoring evidence from real consensus is thin. The canary uses
   constructed numbers.
6. **The pass bar was fixed before results,** but the panel is small; one bad name moves the coherent count by 8 points.
7. **Three contract numbers** (conviction score, moat, re-entry tranches) have no code source yet. They must be resolved before any
   book-wide run.

## 7. Questions
1. Is the stage split, and what each stage sees, sound? Is any information leak or self-conditioning path still open?
2. **The calibrated bridge:** is it correct, and is holding K_0 in dollars acceptable? What would you change?
3. **The fact checks:** better generic rules than ±300-character proximity? Should unusable facts be shown to stages 2–3 at all?
4. **The stage TASK texts** (`briefs/R26_A2_TASK_TEXTS.md`): any wording likely to cause copying, loops, or a basis mix-up?
5. **The evaluation:** is the rubric and pass bar adequate for the decision it gates? Is the constructed-consensus canary a valid
   anchoring test?
6. **Data no-calls** (PACS) and identity-basis names (GOLD): acceptable handling?
7. **Anything that should stop the GPU run** as planned.

At the end, give:
- go / change / no-go for the GPU plan in section 5;
- the one change you would make first;
- the result you would most expect to fail.
