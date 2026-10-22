# Cross-check request 25: why three blind forecasts of the same stock disagree, and what to change before iteration 3

Written 2026-10-22 by the coordinator. **This document is self-contained.** You advise, the coordinator rules on each point, and the
operator decides. Records: `github.com/riperdy-tech/rs2-local`, branch `docs/rev23-records`, folder `docs/rev23/` (`SPEC_rev26_staged_analyst.md`,
cross-checks 22–24, `PLAN_terminal_reinvestment.md` end sections). Code: branch `review-2026-10/r26-int`.

## 1. Background you need

**The system.**
- A screener nominates about 160 US-listed stocks.
- A local AI analyst (Qwen 3.8 27B on one GPU) values each one.
- Code does all arithmetic through a "desk" (a DCF engine).
- Real money will depend on the verdicts (undervalued, hold, overvalued). Trading is halted; everything here is a paper test.

**The staged design (revision 26).** Each stage is a separate model session.
1. **Research:** the analyst registers facts, each with a verbatim quote that code verifies. The resulting dossier is frozen.
2. **Blind forecast, K = 3 independent samples** (seeds s, s+1, s+2, each a fresh session that sees the same frozen dossier, no price and no
   consensus). Each sample submits, per scenario (Base, Bull, Bear):
   - years 1–2 revenue growth and operating margin;
   - a normalized state in year N (3–5): a baseline chosen from the company's filed 8-year operating-margin record (min, p25, median, p75,
     max or last) plus a stated `delta_pts`, and a revenue growth;
   - a transition shape, a long-run operating margin and a fade length;
   - `terminal_g`, `terminal_ronic` (the return on new investment after the fade) and scenario probabilities;
   - for the whole forecast, the `discount_rate` (cost of equity; the pack shows a code-owned anchor, and the desk requires a value within
     ±150 bp of it unless the analyst declares its own source with a reason) and the valuation frame;
   - fact IDs for every part.

   Code builds the path, converts it to the valuation basis and values it. The three Base values are recorded with their spread,
   (max − min) / median.
3. **Reveal and crux:** price, the price-implied inputs and a corrected consensus are shown; the analyst states its crux and may revise once.
4. **Memo** from frozen numbers.

**Why three samples.** The three-sample gate exists to catch an analyst whose answer depends on sampling luck. Two rules use it:
- **Benchmark pass bar** (registered before any run): median spread across names ≤ 20%; ≥ 83% of callable names with all three samples on
  the same side of the price; plus coherence (two blind readers), no loops, low pull toward revealed numbers, and no memo verdict mismatch.
- **Per-name actionability** (frozen 2026-10-21): a name is actionable only if its spread is ≤ 20% and its direction is unanimous. Otherwise
  the verdict is published with a flag and is not acted on.

## 2. What iteration 2 produced

Iteration 2 ran stages 2–4 for 9 of 12 names before a data defect stopped it (KOF has no share count; now a recorded data no-call). Two of
the 9 are data no-calls (PACS: no D&A filed; LPG: no tax provision filed). That leaves 7 callable names:

| Name | Business | Three Base values ($) | Spread | Price ($) | Direction |
|---|---|---|---|---|---|
| TASK | IT services | 20.54 / 20.71 / 22.25 | 8.2% | 8.22 | undervalued, unanimous |
| MSGE | live entertainment | 35.51 / 39.37 / 39.90 | 11.2% | 79.60 | overvalued, unanimous |
| DAC | container shipping | 474 / 489 / 545 | 14.4% | 158.17 | undervalued, unanimous |
| BUD | brewer | 86.47 / 93.93 / 102.98 | 17.6% | 82.59 | undervalued, unanimous |
| ITGR | medical device contract manufacturer | 63.72 / 93.86 / 94.61 | **32.9%** | 126.70 | overvalued, unanimous |
| MCY | property and casualty insurer | 173.88 / 210.55 / 264.36 | **43.0%** | 102.80 | undervalued, unanimous |
| GOLD | precious-metals trading and dealing | 65.54 / 75.17 / 127.78 | **82.8%** | 39.35 | undervalued, unanimous |

On the registered bar, the median spread is 17.6% (it passes) and direction is unanimous for 6 of 7 (it passes): one BUD sample ($86.47
against a $82.59 price) falls inside the 10% hold band. But 3 of 7 names fail the per-name 20% rule. The readers' results are in section 7.

## 3. Where the spread comes from (measured: the inputs that differ between the three Base scenarios)

**GOLD (82.8%).** Operating margins near 0.5% of revenue, so value is close to proportional to the margin.
- Years 1–2 revenue growth: −8% / +5%, −20% / +15%, and **+15% / +10%** (the high sample).
- Years 1–2 margin: 0.45%/0.55%, 0.30%/0.50%, 0.50%/0.60%. Long-run margin: 0.5%, 0.6%, 0.7%.
- Normalized baseline: "last" in one sample, "median" in two; delta −0.1 to +0.2 points.
- `terminal_ronic`: 12%, 12%, **20%**. Fade: 5, 4, 5 years.
- The samples disagree on whether a recent forward-sale revenue spike reverses (the dossier supports both readings), and a 0.2-point margin
  difference is a 40% value difference at these margins.

**MCY (43.0%).** A cyclical insurer.
- Normalized baseline: median, **p75**, median, with deltas of +1.5, +1.8, +1.0 points.
- Long-run margin: 8%, **10%**, 7%. `terminal_ronic`: 12%, 13%, 9%.
- Cycle-position label: mid, mid, peak.

**ITGR (32.9%).**
- `discount_rate`: **9.0%** in one sample, against the 7.96% anchor in the other two (within the ±150 bp band).
- Years 1–2 margin: 8.5%/10.5%, 11.5%/11.9%, 8.0%/11.5%. Normalized revenue growth: 4%, 4%, 6.5%.
- `terminal_ronic`: 10%, 15%, 12%.

**For contrast, BUD (17.6%)** also varies `terminal_ronic` (14%, 8%, 15%) and its baseline (p75, median, last), but a stable 26% margin
makes those choices move the value much less.

**Two observations.**
- Most of the variation is in inputs that the dossier does not pin down: the baseline percentile, the long-run margin and the
  terminal return. Several samples state, in their own words, that "no usable fact speaks for as long as the long run" and that the long-run
  margin "rests on the filed history as a base rate".
- The disagreement is real: each sample is internally reasonable. Averaging more samples would narrow the estimate of the median, but it
  would not remove the disagreement, and the spread measure would show it again.

## 4. Constraints and earlier rulings

- **No narrow patches.** A fix must be generic, never per ticker or per sector.
- **Annotate, never silently gate.** Spread and direction already ride as flags; nothing is deleted.
- **Code must not substitute its judgment for the analyst's.** Earlier ruling: an automatic code fade on a failed repair was rejected; so was
  prescriptive wording such as "fade to the 10-year median". Questions to the analyst are allowed; dictated answers are not.
- **The pass bar and the per-name rule are registered.** They are not changed after results without a documented, separately approved
  amendment (as Amendment 1 was).
- **Each design iteration is one tree.** Iteration 3 re-runs stages 2–4 for all 12 names (about 5.5 hours of GPU, plus 2 hours of smoke
  tests). At most 2 counted iterations remain.
- Changing the model-facing text is a versioned decision (a pack revision), and is allowed when versioned and recorded.

## 5. The coordinator's options for iteration 3

- **S1. Code-owned defaults for the long-run judgment inputs, with a cited departure.** `discount_rate` and `terminal_ronic` default to
  code-owned values (the cost-of-equity anchor; the company's own measured return on new capital from its filed record). The baseline
  defaults to the median of the filed record. A sample may depart from any default only by citing a usable fact that speaks for the
  relevant horizon, and code records every departure. Rationale: the dossier rarely holds evidence for these inputs, so they are where
  sampling noise lives. Risk: it looks like code substituting judgment, although the analyst can still depart on evidence.
- **S2. More samples.** K = 5 with the median reported. It narrows the median's noise; it does not shrink the disagreement, and costs about
  70% more stage-2 time.
- **S3. Attribute the spread.** Code re-values each sample with one input swapped to another sample's value, and reports which input
  drives the spread. That is a diagnostic only; it changes no number. Useful in any case, and it tells the operator which disagreement
  matters.
- **S4. Keep the design and accept that some names are non-actionable.** Spread is honest uncertainty; a thin-margin dealer or a cyclical
  insurer may genuinely not be valuable to ±20%, and the per-name rule already withholds action.
- **S5. Ask the analyst to reconcile its own samples.** After the three samples, one more session sees all three forecasts (inputs only, no
  values) and states which disagreement it can resolve with a cited fact. Risk: it reintroduces self-conditioning and a fourth session per
  name.

**The coordinator's current lean:** S3 always, plus S1 for `discount_rate` and `terminal_ronic` only, and S4 for what remains (keep the
per-name rule; do not loosen it). Not decided.

## 6. A second, smaller question: DAC

DAC (a container-ship owner) is valued at about 3× its price, with all three samples within 14%. Its crux is "jointly reachable", but no
single judgment input reaches the price on its own: even a 0% long-run margin values it at $198, above the $158 price. The whole gap
therefore sits in the years 1–5 path (contracted charter revenue), which the crux cannot name as an input. Cross-check 24 deferred making the
forecast path a crux input (B3), because the path is ten or more numbers.

## 7. What the two blind readers found (added after scoring)

Two independent readers scored masked extracts (no values, price or verdict) on four criteria: (1) facts correct; (2) forecast consistent
with the memo's stated economics and labels; (3) no unsupported copy of a revealed number; (4) the normalized state and the long-run margin
defended by evidence of matching duration. They agreed on 27 of 28 ratings; the coordinator adjudicated the one difference (GOLD,
criterion 4: questionable).

**Scorecard (iteration 2, 7 callable names): FAIL.**
- Coherent: **0 of 7** (a name is coherent only when all four criteria are). Incoherent: 1 (ITGR).
- Loops 0; median spread 17.6%; unanimous direction 6 of 7; unverified pull 0.000; memo verdict mismatches 0 (all pass).

**Criterion 4 was "questionable" for every name.** The long-run margin is held in perpetuity, and no fact "speaks for" perpetuity: the
readers repeatedly wrote that the evidence is "shorter than the claim" (an 8-year margin record, a 5-year lease, a 4.7-year charter book).
This is the same place the sample spread comes from.

**Real faults the readers found:**
- ITGR (incoherent): the memo calls Integer "an MRI business with an installed-base service annuity" and uses that as the basis of its
  margin-persistence label; the dossier describes cardio, vascular and neuromodulation device segments only. The Bull case also cites
  guidance the company withdrew, and the Base case adds "+0.5 pt for KKR cost discipline" to a standalone value.
- Basis mixing: company-adjusted EBIT or EBITDA figures used to defend a filed GAAP operating margin (BUD, TASK).
- Labels that contradict the inputs: MSGE's "accelerating" label on a path that slows every year; TASK's memo describing its baseline as
  a size-bucket base rate when the input is the filed-history median.
- A premium resting on a figure no fact contains (BUD's "H1 2026 normalized EBIT margin of 27.2%").
- TASK's revision reached the right number (3.9%, from the 8-K) with a wrong comparison in its reason.

**Questions added by these results:**
7. Is criterion 4 achievable as written? Should "matching duration" for a perpetual long-run margin mean a long filed record (8 years or
   more) plus an explicit statement of what would change it, or should the design stop asking for a perpetual margin at all (for example a
   code-owned fade to the filed median after year 5, with the analyst arguing only for a departure)? Is that code substituting judgment?
8. How should the next iteration attack the invented business description (ITGR), the basis mixing and the label contradictions:
   prompt changes, a code check (for example a basis tag on every cited fact compared with the margin it supports), or a verifier pass
   on the memo against the dossier?
9. With 0 of 7 coherent, is iteration 3 (the last but one) worth spending on fixes alone, or does the design need a larger change first?

## 8. Questions

1. Is the spread on GOLD, MCY and ITGR a design defect to fix, or honest uncertainty that the per-name rule correctly withholds? Can you
   tell them apart from the evidence in section 3?
2. Of S1–S5, which would you implement, and why? Is S1 code substituting judgment, or a legitimate default with a cited-departure rule?
   If S1, what should the defaults be, exactly (for the baseline, `terminal_ronic` and `discount_rate`)?
3. Should the near-term disagreement (GOLD's years 1–2 revenue growth, from −20% to +15%) be handled differently from the long-run
   disagreement? It rests on the dossier rather than on missing evidence.
4. Is a 20% per-name spread rule right for thin-margin businesses, where any honest valuation is very sensitive to the margin? Or should
   the rule measure the spread of something less leveraged (for example, the margins themselves)?
5. For DAC: is a verdict whose whole gap lies in the years 1–5 path safe to make actionable through the current crux? What review should
   it require?
6. Anything in these results that should change the plan before iteration 3?

Please answer questions 1–9. At the end, give your recommendation for iteration 3 in one line, and the result you would most expect to fail in it.
