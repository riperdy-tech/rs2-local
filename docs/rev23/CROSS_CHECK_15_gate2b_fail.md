# Cross-check request 15: gate 2b failed. What does it mean, and what should the next registered test be?

Written 2026-10-15 by the coordinator. **This document is self-contained.** Every number, rule and definition you need is inline. Where an
answer would rest on code you cannot see, say so rather than assume. Critique freely: the coordinator rules on each point, and the operator
decides. The most useful answer is a list of problems ranked by how much each could hurt a real-money decision, then your answer to each
numbered question.

## 1. Background

### The system
A code valuation engine turns a company's point-in-time filings into a distribution of intrinsic value per share. It does this through
year-1–3 forecasts of growth, margin (operating companies) or ROTE (financials), then a continuation to a terminal state. Real money will
depend on its verdicts. Every test is registered before data, and outside reviews are ruled on before the operator approves.

### The engines
- **v1:** the old code engine. Every input sits at a population prior's P50 for the company's family and growth band.
- **v2.1:** the engine under test.
  - **Years 1–3:** residual distributions around v1's own path.
  - **Years 4 onward:** growth continues from the year-3 draw with a measured continuation, λ estimated by L1 regression by growth-decay
    bucket, with a family-pooled fall-back.
  - **An interim:** the growth upper tail is clipped (P99 := P95).

  It passed its registered acceptance checks:
  - **E5:** oracle residual IC within 0.02 of v1's, pooled and in every year 2020–2024;
  - **E8:** value-distribution sanity against v1 on 23,783 historical names;
  - **an identity test:** years 1–3 identical to the previous version on all 24,036 names.

  The previous version, v2.0.3, failed E5 in 2021 (−0.025 against v1, beyond the −0.02 margin) and was never frozen.

### Gate 2b v3
The registered out-of-sample screen of SYSTEM = v2.1 alone. A local LLM's next-quarter growth forecasts beat v1 in the earlier gate, but the
registered rule for combining them gave the LLM weight 0: only 143 eligible annual pairs existed against a minimum of 150. So the system
under test is the code engine alone.
- **Date:** 2026-07-31, a census of every eligible company. 2,059 in the universe → 1,189 valued after these removals:
  - commodity 169;
  - no 10-Q in the 12 months before T, 107;
  - the earlier gate's 2026-06-30 sample, 114: the coordinator had seen those companies' June-quarter outcomes in aggregate;
  - companies engine v2.1 cannot value, 480: mostly no trailing 3-year ROIC, or no operating income.
- **Target (q1):** the next quarterly result **not public at T**, measured from one filing's own comparative columns (same accession, tag and
  unit; revenue verified as total). A result is excluded if it was public before T through:
  - an 8-K with Item 2.02 or 7.01 accepted after the period end;
  - or a quarter ending more than 120 days before T.
- **Forecasts scored against q1 (gate 1's convention, a shared mismatch):**
  - growth: the annual fiscal-year-1 P50 growth;
  - margin change: the year-1 P50 operating margin minus the base-year margin;
  - ROTE change: the year-1 P50 ROTE minus the base-year ROTE.
- **The outcome's measures:**
  - q1 revenue growth, year over year;
  - the q1 operating-margin change against the same quarter a year earlier;
  - the annualised ROTE change on tangible book at T.
- **The arms:**
  - **V2:** the engine under test;
  - **CODE:** v1;
  - **PERSIST:** the run-rate from the latest four contiguous quarters known at T (their revenue over the same quarters a year earlier,
    minus 1; their operating margin minus the base-year margin);
  - **POPMED:** the cross-sectional median of PERSIST per family over the universe.
- **The bars:** per bar, the paired median of d = |V2 − y| − |other − y|. V2 beats the other arm when the median is < 0 **and** the upper end
  of a one-sided 90% bootstrap interval is < 0 under **both**:
  - a SIC-2 industry-cluster bootstrap (industries with fewer than 5 pooled per family);
  - a company bootstrap.

  2,000 draws each.
  - **B2:** V2 beats PERSIST and POPMED on growth and margin, and PERSIST on ROTE.
  - **B3:** V2 beats CODE on all three.
  - **Minimum paired n:** 200 for operating measures, 100 for ROTE; below it a bar reads NOT DECIDED.
  - **The verdict:** PASS only if every bar passes; FAIL if any decided bar fails.
- **Stated limits, before data:**
  - a q1 proxy screen on a period partly observed in aggregate;
  - **not** a pristine holdout and **not** a test of annual accuracy;
  - a pass would support paper operation only.
  - Real money also needs a later annual calibration test (B4, spring 2027) and other conditions.

## 2. The result: FAIL

| Bar | n | median d | upper90 industry / company | MAE V2 / other | status |
|---|---|---|---|---|---|
| B2 V2 vs PERSIST, growth | 229 | +0.0169 | 0.0250 / 0.0307 | 0.127 / 0.102 | FAIL |
| B2 V2 vs POPMED, growth | 231 | +0.0007 | 0.0008 / 0.0008 | 0.127 / 0.125 | FAIL |
| B2 V2 vs PERSIST, margin | 228 | +0.0034 | 0.0050 / 0.0052 | 0.118 / 0.055 | FAIL |
| B2 V2 vs POPMED, margin | 231 | +0.0006 | 0.0009 / 0.0008 | 0.117 / 0.057 | FAIL |
| B2 V2 vs PERSIST, ROTE | 32 | +0.0353 | 0.0573 / 0.0644 | 1.74 / 1.49 | NOT DECIDED |
| B3 V2 vs CODE, growth | 231 | −0.0052 | −0.0052 / −0.0052 | 0.127 / 0.130 | PASS |
| B3 V2 vs CODE, margin | 231 | −0.0002 | 0.0012 / 0.0004 | 0.117 / 0.120 | FAIL |
| B3 V2 vs CODE, ROTE | 32 | +0.0033 | 0.0086 / 0.0097 | 1.74 / 1.72 | NOT DECIDED |

**The reading:**
- V2 loses to the run-rate on growth and margin.
- V2 ties the population median, with a positive median d but a tight interval near zero.
- V2 beats v1 on growth, and ties it on margin.
- The ROTE bars lack their sample.

**Robustness (the same signs everywhere):**
- removing the top 10 gains;
- leaving out each industry (12 clusters on the operating bars);
- reweighting by inverse probability of selection to the universe (SIC-2 × size tercile × quarter-end month);
- by size tercile and by quarter-end month;
- on the total-revenue-verified rows only (n about 196, NOT DECIDED by count);
- excluding every company of any earlier-gate date (n about 178, NOT DECIDED by count).

**Checks:**
- an independent recomputation (code sharing nothing with the pipeline) gives identical n and median d on all 8 bars;
- look-ahead clean: every input filed before T; every outcome filed after T and on or before the scoring date 2026-10-13;
- every exclusion registered with its SEC acceptance timestamp;
- 20 of 20 hand-checked outcomes match the filed 10-Qs.

**The sample:**
- 747 of the 1,189 had filed their June-quarter 10-Q before T, so their next quarter (September) was not filed by 10-13.
- 174 of the remaining 442 had their June result public at T: Item 2.02 140, Item 7.01 alone 34.
- That leaves 268 eligible targets, operating 236 and financial 32.
- **Every target is the June quarter, which ended 26–35 days before T.** The persistence arm's four quarters end with the March quarter.

**Reported diagnostics:**
- V2's annual P10–P90 band covers the q1 outcome in 81% of cases for growth and 75% for margin (an annual band, not a calibration test).
- At median inputs, about 89% of V2's value comes from year 4 onward.

## 3. Findings beside the verdict

1. **The cost of debt is unbounded in the discount rate (shared by v1 and v2).** WACC uses the company's effective cost of debt (interest over
   debt), with no floor at the risk-free rate, weighted by **book** debt-to-equity.
   - MAN: a negative cost of debt (−7.4%) gives WACC 2.4%.
   - FOUR: convertibles at 0.4% with book D/E 3.15 give WACC 2.4%.
   - Both are below terminal growth, so no draw is valid.
   - Across 17,769 historical operating names: the cost of debt is below rf in 15.4% (25–31% in 2022–23); WACC is within 1 point of terminal
     growth in 2.5% and within 2 points in 6.4%.
   - In 2020, low risk-free rates alone gave some names a WACC near 1.5%.
2. **"Valued" with no per-share value.** 3 census names report status ok with no per-share value (the two above, plus one share-count gap).
   They are now refused by the live runner.
3. **Operator decisions since the verdict:**
   - v2.1 is **not promoted**, and real money stays barred;
   - the operator chose to **let a paper (no-money) book trade v2.1's verdicts, labelled experimental and unpromoted**, kept apart from the
     real-money mirror.

## 4. Questions
1. **Is the reading right?** Is "FAIL; not promoted" the correct consequence? Is there any defect in the design or the analysis that would
   make the failure an artefact rather than a finding? In particular:
   - the annual-forecast-against-quarter mismatch;
   - every target being the late-reported June quarter, a month past T;
   - the margin bars, where the means differ much more than the medians.
2. **Why might a population-prior engine lose to a run-rate on the next quarter?** Rank the explanations you find likely, and say what
   evidence in hand (or cheaply obtainable without new outcomes) would separate them:
   - the run-rate's recency;
   - the annual horizon;
   - V2's year-1 centre at a population P50;
   - seasonality;
   - the margin definition.
3. **What should the next registered test be?** Candidates:
   - **(a)** fix the near-term centre: blend the company's own run-rate into V2's year-1 centre, register the rule, develop it on the earlier
     gate's dates (already observed), confirm it on a fresh census (2026-09-30 or later; outcomes filed by mid-November);
   - **(b)** realign the target: score the annual fiscal-year-1 outcome (spring 2027), the quantity the engine forecasts;
   - **(c)** score returns instead: the selection registration;
   - **(d)** something else.

   Which, in what order, and what bar? What must be true before real money that none of these tests?
4. **Paper trading an unpromoted system.** What should the paper book measure, and over what horizon, for its results to inform the real-money
   decision without being cherry-picked later? What would you pre-register now?
5. **The cost of debt.** What is the sound fix: a floor at rf plus a spread; a synthetic rating from interest coverage; market rather than book
   weights; or refusal below a margin over terminal growth? Is this a defect that must be fixed before **paper** trading, or only before real
   money?
6. **What else?** Anything in the design, the numbers or the decisions above that a careful reviewer would challenge.

At the end, give:
- the single most important thing to do next;
- whether paper trading v2.1 now is reasonable as labelled.
