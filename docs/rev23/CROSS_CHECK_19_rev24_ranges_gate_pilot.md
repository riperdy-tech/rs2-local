# Cross-check request 19: the AI analyst's new briefing (population ranges, plausibility gate) and the pilot, before any GPU run

Written 2026-10-16 by the coordinator. **This document is self-contained.** Where an answer would rest on code you cannot see, say so rather than
assume. Critique freely: the coordinator rules on each point, and the operator decides.

The code is public: `github.com/riperdy-tech/rs2-local`, branch `review-2026-10/rev24-muse`. The records are on branch `docs/rev23-records`,
folder `docs/rev23/`.

## 1. The system, in brief
- **A stock screener** nominates about 160 US stocks.
- **For each, a local AI analyst** (Muse Glimmer, a 30B open-weights model on one GPU) reads:
  - a long briefing: 10 years of filings, recent quarters, consensus forecasts, a research brief, news, macro;
  - primary sources it searches itself.

  It chooses the valuation inputs.
- **Code does all the arithmetic** through a "desk" tool (a discounted-cash-flow engine: years 1–5 explicit, then a fade, then a terminal
  value), checks a buy or sell "crux" against quoted filings, and applies gates.
- **Real money will depend on the verdicts.** It is halted.

## 2. Where cross-check 18 left us
- **The problem:** the analyst copied a code-computed reference value. The briefing's "default inputs" were that formula's own inputs, so
  running them unchanged reproduced it to the cent. The formula's defects then rode in: growth stocks were valued at 0.2–0.45× price, and
  cyclicals and insurers near peak at 2–3.7×.
- **The design adopted** after your reviews and the operator's approval, "modified option (iii)":
  1. The reference is never shown to the analyst (logged as a benchmark only; the planned "reveal after commit" is dropped).
  2. Filed facts stay as defaults.
  3. **Long-run judgments get population ranges instead of defaults:**
     - the long-run margin;
     - growth in years 3–5;
     - the fade length;
     - terminal growth;
     - the return on new investment (RONIC).
  4. Consensus years 1–2 are evidence, not fixed inputs.
  5. Three classifications: margin persistence, cycle position and growth trajectory.
  6. Three citation levels:
     - within P10–P90, a rationale;
     - outside P10–P90, a sourced causal explanation;
     - for the crux, verified primary-source quotes.
  7. **A plausibility gate** on the implied trajectory: outside the cohort's P5–P95 with a verifiable citation passes, annotated; without one,
     the valuation is rejected as unusable. Nothing is clamped and there are no hard caps.
  8. An arithmetic audit first, then a blinded six-stock pilot.

## 3. Done since (steps 1 and 2a, in one paragraph)
**The arithmetic audit** found the desk had **no long-run margin input at all.** It silently took the formula's margin rule, which carried the
base year's operating-to-earnings gap forever (one stock's implied operating margin was 352%, another's long-run margin was zeroed). Fixed:
- the analyst now chooses `long_run_margin` (the earnings margin at the end of the fade), applied proportionally in every scenario;
- three further arithmetic defects fixed:
  - the margin was dropped when the fade was short;
  - year-5 earnings were mis-scaled in Bear;
  - the reinvestment charge jumped at an unlimited RONIC;
- a RONIC below the discount rate is valued at the rate, **with a stamp**;
- the remaining places where the reference leaked into the briefing are closed;
- the reveal is off behind a flag.

## 4. Step 2b: what was built (after 2a)
**The briefing:**
- All long-run default lines are removed.
- **A POPULATION RANGES section.** For each long-run input: the cohort in words, n, the vintage, and P10/P25/P75/P90. P50 is shown only in one
  pilot arm.
- One line: "how companies like this one actually evolved; context for your choice, not a target."
- Consensus years 1–2 are printed as "what analysts forecast; evidence, not a value the desk holds."

**The tables:** measured point-in-time from SEC filings (vintages 2016–2025; a valuation date T uses vintage year(T) − 1), by family,
cyclicality band and margin band. They come from our rebuild, a separate code-only engine whose population priors carry a tested point-in-time cut.
The briefing reads them and reproduces the rebuild's cohort assignment: **0 mismatches in 47 comparable cases** (30 stocks × 2 dates).

**The instructions (TASK)** ask the analyst, in order:
1. state near-term earnings, normalized mid-cycle earnings and the transition with its reason;
2. classify the three dimensions, each from its own evidence;
3. choose each long-run input with the ranges "as context, not a target";
4. support each choice at its citation level.

They also say that code checks the implied trajectory against the cohort's P5–P95, and that `terminal_g` must stay below the discount rate.

**New output fields:**
- near-term and normalized earnings, with the reason;
- the three classifications, each with an evidence pointer;
- for each long-run input: the value, within P10–P90 or not, the rationale, and a citation.

**The desk, when the long-run defaults are withheld:**
- no year is held at the consensus levels;
- the years 3–5 growth cap is removed (a cap, and the design has none);
- the rule asking for a reason when Bull or Bear sits more than 15% from consensus stays (it asks for a reason and caps nothing).

**The desk outputs the implied year-10 trajectory:** the long-run margin, the 10-year revenue CAGR, terminal RONIC, year-10 earnings ÷ base
earnings, and terminal growth.

**The plausibility gate:**
- **reject** when `terminal_g` is at or above the discount rate;
- for each implied metric outside the cohort's P5–P95:
  - **pass, annotated,** with a verifiable citation;
  - otherwise **reject** (`implausible_unsupported_<metric>`), and the verdict is `not_usable`;
- a metric with no measured cohort is annotated, never rejected.

**Pilot arms:**
- `rev22`: the old briefing byte for byte, the control;
- `iii_p50`: the new briefing with P50;
- `iii_no_p50`: the same without P50, differing only there.

## 5. The coordinator's audit of step 2b, and the rulings (step 2c is building them now)
1. **The margin range was wrong, through the coordinator's own brief.**
   - The brief built it as `trend + R × (current − trend)` at each quantile of R, the share of a margin deviation still there after 5 years.
     R is a ratio, and its tails explode for firms whose deviation was small.
   - Micron's P10–P90 came out as **−154% to +189%**, which the gate would never flag. Kohl's collapsed to **1.6–1.9%**, which it would flag
     every time.
   - **Fix:** the rebuild's own construction (its Addendum I1). The centre is the median-retention path at year 5. The spread is the measured
     residual of the year-5 margin level, conditional on the company's current margin band, with cells merged up to n ≥ 50 or refused by name.
2. **Units.** The tables measure operating margins; the analyst's input is an earnings margin.
   - The range is printed both ways, by one stated translation anchored at the company's filed 8-year medians, never the base year (anchoring
     at the base year caused the 352% defect): `earnings_q = m_tc + (1 − t) × (OM_q − om_tc)`.
   - t is the record's median effective tax rate, or 21% stamped.
   - The gate checks the earnings-margin P5–P95.
3. **Terminal growth.**
   - The table first used measures **10-year revenue CAGR** (P90 +30%), not perpetual growth. It is now printed under that name, and it
     bounds the 10-year revenue CAGR check.
   - `terminal_g` gets no population range. It must sit below the discount rate (reject otherwise). Above the briefing's printed long-run
     growth anchor (for example 3.75%), it is an outlier needing a verifiable citation.
4. **RONIC.** The incremental-return table is too noisy (P10 −50%, P90 +49%) and is dropped. The context and the gate bound become the
   rebuild's **ROIC level five years on**, built the same way as the margin.
5. **Families the tables do not measure** (utilities, REITs, parts of insurers): "no measured population" is printed per input. The gate
   runs the mathematics and the growth-anchor check, annotated `no_population_cohort`. **Two pilot names (a utility and a REIT) stay in
   deliberately,** because the book holds such companies.
6. **Citations:** the gate accepts exactly what the crux check accepts. That is a quote found verbatim in the briefing's company material or
   in a fetched page naming the company. The outlier level must not be stricter than the crux level.
7. **The control arm shows the reference value,** as revision 22 did. It is a measurement arm only, never used for a verdict, a ledger or the
   book, and the operator approved the ablation as "the revision-22 briefing against (iii)". It must run with revision 22's long-run desk
   behaviour (the step-2a arithmetic fixes stay), or the desk refuses every call.
8. **Working capital** was still deducted along the reference formula's revenue path. It will follow the analyst's own path.
9. **The classifications are validated against their allowed values.** "Within P10–P90" is computed by code, not taken from the analyst's
   declaration.
10. **Residual anchoring:** the reference cannot be derived from printed figures. But natural analyst inputs can land on it (Kohl's within
    0.05% when the terminal RONIC equals the cost of equity, Heritage within 0.9%). We read this as economics, not a leak.

## 6. The population-table audit (recorded, not fixed)
- **Survivorship:**
  - delisted firms are included: 42% of vintage-2025 observations come from firms that later stopped filing;
  - acquisitions and failures are not told apart;
  - tables other than the 10-year growth one lose a firm's outcomes once it stops filing, so the long-horizon cells describe survivors;
  - the commodity family holds almost no delisted firms.
- **Look-ahead:** the financial-fact cut is proven by test. Not covered:
  - industry codes are current-dated (they affect 42% of observations);
  - a few post-cut price rows per vintage;
  - "ceased" labels use hindsight.
- **The coordinator's reading:** these ranges are context and outlier bounds, not scored forecasts. Survivor tilt narrows long-horizon cells,
  so it makes the gate stricter, not looser.

## 7. The pilot (registered before any run)
- **Names:**
  - Micron;
  - Monolithic Power;
  - UGI (a utility);
  - Lamar (a REIT);
  - AMD (the census's growth case: the formula said 0.45× price);
  - Costamare (the census's shipping cyclical: the formula said 2.01×, the old analyst 3.71×).
- **Runs:** 3 arms × 6 names, one sample each, plus repeats on 2 names for both new arms. That is 22 runs, about 12–15 GPU hours.
- **Research:** one deep-research run and one news-discovery run per name, frozen. All arms of a name share one frozen briefing and one
  evidence cache.
- **Measures, each reported separately** (no valuation-to-price targets):
  - **(a) clustering:** each chosen input's percentile in its cohort; the share at P50, at a printed quantile, and outside P10–P90; P50 shown
    against hidden; the same percentile whatever the company is a red flag;
  - **(b) stability:** the two seeds on the repeat names;
  - **(c) cash-flow plausibility,** scored blind by the coordinator: price, values and label masked; scores hashed before unmasking;
  - **(d) evidence:** citations, crux validity, gate outcomes, and the crux-form failures that sank this model's earlier acceptance test.
- **Reading:** expansion is recommended only with no incoherent memo in (c), no unverified crux or unsupported outlier accepted in (d), and no
  systematic copying in (a). Otherwise the report names the failure and the operator decides.

## 8. Questions
1. **The margin range.** Is the rebuild's construction (median-retention centre plus a residual spread conditional on the current margin
   level) the right context for a long-run margin? There is a horizon issue: the tables measure the margin **five years on**, but
   `long_run_margin` is the margin **at the end of the fade** (up to about 10 years out). Should the range be labelled as year 5, be measured
   at the longest horizon with enough data (7 years), or something else?
2. **The units translation** `m_tc + (1 − t)(OM − om_tc)`: sound, or a back door for the old translation defect? Is there a better way to give
   an earnings-margin range from operating-margin tables?
3. **Terminal growth:** is "below the discount rate, and above the long-run growth anchor needs a citation" the right check? Should a
   perpetual-growth population be measured instead, and from what?
4. **RONIC:** is the ROIC level five years on a defensible context for the return on *new* investment in perpetuity?
5. **The gate:** is rejecting an unsupported outlier as unusable right, given that the P5–P95 bands may be wide? Are the five metrics the right
   ones? Is anything missing, such as reinvestment rate against growth, or the terminal-value share?
6. **The control arm** shows the old reference value. Keep it as approved, or replace it with something that says more?
7. **The pilot:** are 6 names, 3 arms and 22 runs enough to find failures early? Are the measures and the reading rule right? Should the
   utility and the REIT (no ranges) be in it?
8. **The population-table gaps** (survivorship, current-dated industry codes): acceptable for context ranges, or blocking?
9. **Anything else** a careful reviewer would challenge before we spend the GPU hours.

At the end, give: the one change you would make before the GPU runs, and the one result in the pilot that would most worry you.
