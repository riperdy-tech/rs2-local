# Cross-check request 13: the growth-decay curves and the fiscal period's authority. Two decisions before gate 2b's freeze.

Written 2026-10-14 21:06 by fork 2 (the session that owns engine v2 and the data fixes). **This document is self-contained**: every
number, rule and definition you need is inline. Where an answer would rest on code you cannot see, say so rather than assume.

## Background

**The system.** A local model (Muse) reads a company's filings and proposes inputs; a valuation engine turns inputs into a distribution of
intrinsic value per share. Real money will depend on the verdicts, so every change is registered before any result exists, and outside
reviews (you) are read and ruled on before the operator approves.

**Two engines matter here:**
- **v1** (frozen for gate 2): growth in year t is `g_T + (g_1 − g_T)·d_t`, where `g_1` is the year-1 growth, `g_T` the terminal growth and
  `d_t` a **growth-decay curve** (d_1 = 1) looked up by family (operating, financial) and growth band (7 bands, 0–6).
- **v2.0.3** (the candidate for gate 2b, operator-confirmed as an INTERIM): years 1–3 are drawn from residual distributions around v1's own
  path; years 4 and later continue from the year-3 draw as `g_T + (g_3 − g_T)·λ_t` with `λ_t = d̃_t / d̃_3`, where `d̃` is the curve's
  **running minimum** (so `λ_t` lies in [0, 1] and never rises). The financial family does the same with its ROTE and fade curves.
  v2.0.3 also clips the growth draws' upper tail (P99 := P95) as an interim measure.

**Gate 2b** is the next registered out-of-sample test of the system (engine v2 alone; 150 companies per date on 2026 dates). Its inputs
freeze after the 2026-10-30 filings land, around 2026-11-05. Anything that changes the priors must be decided and built before then, or
it waits for the next test.

**Status of results.** Nothing in this request reads an outcome:
- the registration below has **no candidate result**; no walk-forward error has been computed;
- two illustrative shapes in section 1.4 apply the candidate's definition to two published curves — a shape, not a score;
- E5 and E8 (the oracle and valuation-sanity checks of v2.0.3) are running; their verdicts stay sealed and are not part of this request.

**How to answer.** Critique freely; the coordinator rules on each point and the operator decides. The most useful answer is a list of
problems ranked by how much each could hurt a real-money decision, then your answer to each numbered question.

---

## 1. The growth-decay curves (decision 1: approve the registration, change it, or reject it)

### 1.1 What the curves are

For each family and growth band, `growth_decay` at horizon k is the **median of the ratio** `(g_k − g_T)/(g_1 − g_T)` over historical
company-years. It is:
- measured while at least MIN_N = 50 pairs stand behind the point;
- clipped to [0, 1];
- held at the last measured value out to year 10.

Each vintage V (2016–2025) has its own tables, built only from filings available at V (point in time). The tables in question are
`priors_v3_fy`: the current tables after a fiscal-year labelling fix (section 2).

### 1.2 The problem: the curves rise ("pins")

The measured medians are not monotone. Where `d_4 > d_3`, v2.0.3's running minimum sets `λ_4 = 1`: the year-3 growth deviation carries
into year 4 at full strength. Where the curve never falls below `d_3` again, the deviation carries **through year 10** ("pinned through the
whole horizon"). A "cliff" (the envelope sending `λ_4` to 0) would be the opposite failure.

Measured on all 133 growth-decay curves of `priors_v3_fy` (2016–2025):

| | Count |
|---|---|
| Cliffs | **0** |
| Pins (d_4 > d_3, d_3 > 0) | **54 of 133 (41%)** |
| Pins by vintage 2017…2025 | 0, 1, 3, 7, 7, 6, 9, 7, 6 (2025: **8 of 14**) |
| Pinned through the whole horizon, 2017…2025 | 0, 1, 3, 5, 5, 2, 0, 0, 0 (2025: **2**) |

v1 uses the raw curve, so for v1 a rise means year-5 growth sits *further* from terminal than year-3 growth.

**The 2025 curves** (the vintage gate 2b would use). `d_1..d_10`; `n` = pairs behind d_1..d_8; points after the last n ≥ 50 are held.

| Family | Band | d_1 … d_10 | n (k = 1..8) | Pin |
|---|---|---|---|---|
| operating | 0 | 1.0, 0.221, 0.0, 0.031, 0.348, 0.035, 0.0, 0.0, 0.0, 0.0 | 1461, 1161, 911, 677, 458, 364, 262, 128 | (d_3 = 0) |
| operating | 1 | 1.0, 0.279, 0.0, 0.044, 0.311, 0.229, 0.0, 0.187, 0.187, 0.187 | 2609, 2165, 1758, 1375, 906, 659, 471, 235 | (d_3 = 0) |
| operating | 2 | 1.0, 0.259, 0.0, 0.07, 0.289, 0.124, 0.0, 0.159, 0.159, 0.159 | 2680, 2238, 1808, 1354, 987, 680, 452, 209 | (d_3 = 0) |
| operating | 3 | 1.0, 0.238, 0.0, 0.11, 0.344, 0.296, 0.102, 0.039, 0.039, 0.039 | 2550, 2088, 1610, 1219, 924, 649, 398, 201 | (d_3 = 0) |
| operating | 4 | 1.0, 0.298, 0.062, 0.145, 0.36, 0.379, 0.08, 0.099, 0.099, 0.099 | 2836, 2192, 1637, 1225, 953, 644, 396, 190 | PIN, whole horizon |
| operating | 5 | 1.0, 0.347, 0.124, 0.206, 0.416, 0.324, 0.083, 0.119, 0.119, 0.119 | 1560, 1174, 870, 644, 476, 342, 213, 100 | PIN |
| operating | 6 | 1.0, 0.185, 0.103, 0.219, 0.172, 0.044, 0.002, 0.051, 0.051, 0.051 | 883, 668, 485, 363, 275, 200, 133, 59 | PIN |
| financial | 0 | 1.0, 0.115, 0.001, 0.134, 0.134, … (held) | 189, 128, 67, 51, 40, 34, 21, 7 | PIN, whole horizon |
| financial | 1 | 1.0, 0.548, 0.434, 0.454, 0.871, 0.546, 0.247, 0.247, … | 537, 416, 268, 226, 182, 132, 84, 37 | PIN |
| financial | 2 | 1.0, 0.411, 0.237, 0.325, 0.746, 0.441, 0.203, 0.33, 0.33, 0.33 | 676, 564, 467, 370, 291, 225, 153, 71 | PIN |
| financial | 3 | 1.0, 0.288, 0.081, 0.035, 0.436, 0.097, 0.06, 0.106, 0.106, 0.106 | 728, 640, 573, 446, 340, 255, 163, 88 | |
| financial | 4 | 1.0, 0.146, 0.01, 0.126, 0.19, 0.025, 0.0, 0.0, 0.0, 0.0 | 698, 618, 552, 425, 314, 219, 132, 60 | PIN |
| financial | 5 | 1.0, 0.237, 0.032, 0.059, 0.067, 0.0, 0.037, 0.037, … | 377, 332, 283, 217, 168, 109, 69, 35 | PIN |
| financial | 6 | 1.0, 0.206, 0.024, 0.024, … (held) | 92, 70, 51, 43, 36, 27, 17, 8 | |

Notes on reading the table:
- The flat tail of financial band 0 (from d_4) and band 6 (from d_3) is the hold rule, not a measurement: n fell below 50.
- Six operating curves (bands 0–5) have a hump at k = 5 (0.29–0.42 after 0.0–0.12 at k = 3), each with n ≥ 458 at k = 5. A hump that consistent and that
  well populated may be a **real feature of the ratio statistic**, not noise: a median of a ratio whose denominator `(g_1 − g_T)` can be
  near zero, and whose sample composition changes with k (fewer companies survive to k = 5). Whether to smooth it away is the question.
- An earlier correction of a few hundred observation rows (the fiscal-year fix) moved some points by up to 1.0, so individual points are
  also known to be fragile.

### 1.3 The registration as drafted (full text of its binding sections)

> **Candidates, fixed now**
>
> | | Estimator | What changes |
> |---|---|---|
> | **K (keep)** | as measured; v2.0.3's envelope after year 3 | nothing |
> | **I (isotonic)** | the measured medians replaced by their **weighted non-increasing isotonic fit** (pool-adjacent-violators, weights n_ratio), then clipped to [0, 1] and held as now | removes the rises; a curve that never rises is unchanged |
> | **S (shrunk isotonic)** | as I, but each point first shrunk toward the family's pooled curve at the same k by n/(n + 200) | as I, and also damps the thin long-horizon points |
>
> - No parametric shape: no exponential form is imposed, because the measured shapes include a fast early drop.
> - Scope: `growth_decay` only. `margin_retention`, `rote_retention`, `ronic_fade` and `excess_fade` are reported with the same pin counts
>   and left as they are unless a separate registration covers them.
>
> **The test (fixed before any number exists)**
>
> *Data.* The per-vintage panels on `priors_v3_fy`. For each vintage V from 2017 to 2024: the curves are estimated with only the
> observations V's priors used; they are scored on the realised growth at k = 4..8 of the observations whose year-k outcome was filed in
> the following years, which V never saw (walk-forward).
>
> *Scored quantity.* The forecast `g_T + (g_1,realised − g_T)·d_k`, with the realised year-1 growth as the anchor. That isolates the
> curve's shape from the year-1 forecast.
>
> *Statistic.* The median absolute error of year-k growth, per family, per k from 4 to 8, pooled over vintages and by vintage.
>
> *Bars.*
> - Adoption of I or S: its pooled median absolute error is not worse than K's at every k from 4 to 8, in both families, and strictly
>   better at k = 4 or 5 in at least one family.
> - Choosing between I and S: S is chosen only if it beats I by that same rule. Otherwise I is chosen, as the simpler.
> - No change to MIN_N, the clipping, the held tail, the bands or any other curve.
>
> *Reported, not barred:* pin and cliff counts per vintage; the change in v2.0.3's E8 measures on two diagnostic dates only; the shift in
> v2's year-1–3 centres.
>
> **What adoption means**
> - A new priors version (`priors_v5`: `priors_v3_fy` with the new growth-decay estimator) and new near-term tables (rebuilt on it,
>   because v2's year-1–3 centres read v1's path).
> - Re-run in full: E1–E8 on the new version, the E8 bars unchanged.
> - Untouched: gate 2's frozen inputs.
> - Gate 2b freezes on whichever version passes before its freeze. If none passes in time, it freezes on K with the pins documented.

### 1.4 Something the draft does not say plainly: I and S also move years 2 and 3

Isotonic regression pools a rise with the points **before** it. Applied (definition only, no score) to two 2025 curves:

| Curve | d_1 … d_8 as measured | I (weighted PAV) | v2.0.3's running minimum |
|---|---|---|---|
| operating band 4 | 1.0, 0.298, 0.062, 0.145, 0.36, 0.379, 0.08, 0.099 | 1.0, 0.298, **0.194**, 0.194, 0.194, 0.194, 0.086, 0.086 | 1.0, 0.298, 0.062, 0.062, … 0.062 |
| financial band 1 | 1.0, 0.548, 0.434, 0.454, 0.871, 0.546, 0.247 | 1.0, **0.554, 0.554**, 0.554, 0.554, 0.546, 0.247 | 1.0, 0.548, 0.434, 0.434, 0.434, 0.434, 0.247 |

So under I:
- `d_3` of operating band 4 **triples** (0.062 → 0.194). v1's year-3 growth, and v2's year-1–3 centres (which read v1's path), move with
  it. The registration's test scores only k = 4..8 and lists the year-1–3 shift as "reported, not barred".
- The pin disappears in a different way from the envelope: the envelope keeps `d_3` and flattens everything after it (`λ_t = 1` to year
  10 here); I raises `d_3` and lets the curve fall afterwards (`λ_7 ≈ 0.44`).

A variant not in the draft, **I₃ (isotonic from year 3 on)**: keep d_1..d_3 as measured and fit the non-increasing isotonic curve to
d_3..d_10 with d_3 pinned as an upper bound. It removes the pins without touching years 1–3. It would have to be added to the registration
**before** any candidate is scored.

### 1.5 Questions on decision 1 (most important first)

1. **Is a monotone constraint right at all?** Given the k = 5 hump in six well-populated operating curves, is it more likely noise or a
   real feature of the median-of-ratio statistic (denominator near zero, survivorship by k)? If real, would a different statistic
   (for example a median of `g_k − g_T` regressed on `g_1 − g_T`, or a trimmed mean of the ratio) be the right repair rather than
   smoothing?
2. **Should the test also score k = 2..3,** given that I and S move d_2 and d_3? If so, with what bar? Or should I₃ replace I so years
   1–3 are untouched?
3. **Is the scored quantity fair?** It anchors on the realised year-1 growth. Is a median absolute error of growth the right loss, given
   that valuation sensitivity to years 4–8 is roughly proportional to the cumulative product of growth, and that the median ignores tails?
4. **Is the walk-forward sound?** Vintages 2017–2024 are scored on outcomes filed after V. Late vintages contribute few or no k = 6..8
   outcomes, because those years have not been filed yet, so the pooled k = 6..8 errors come mostly from early vintages. Should the bar be
   read only on k where every vintage contributes, or weighted by n?
5. **Is the adoption bar too strict or too loose?** "Not worse at every k = 4..8 in both families, strictly better at k = 4 or 5 in at
   least one" — no tolerance band. A tie within noise counts as "not worse"? Should there be a bootstrap or a minimum improvement?
6. **S's shrinkage constant 200:** fixed by judgement, not fitted. Acceptable, or should it be a small grid fixed now?
7. **Scope:** the draft leaves `margin_retention`, `rote_retention`, `ronic_fade` and `excess_fade` alone. v2's financial continuation
   uses `rote_retention` and the fade with the same running-minimum envelope. Should those be in scope now, given the freeze?
8. **The fall-back:** if nothing passes before the freeze, gate 2b runs on K with 8 of 14 curves pinned. Is that acceptable for a
   real-money test, or should the freeze wait?

---

## 2. The fiscal period's authority (decision 2: refine now, after gate 2b, or never)

### 2.1 Background: the fiscal-year fix

The legacy code decided which fiscal year an annual report covers by taking the latest end date among the report's year-length duration
facts, in any unit. Some 10-Ks also file a forward-looking annual fact: Boeing's FY2017 10-K, filed 2018-02-12, files the 2018 federal
statutory tax rate for 2018-01-01 to 2018-12-31, and that one fact relabelled the whole report as FY2018. The effects were a missing year
(inputs a year stale) and, in later extractions, a false early filing date on the relabelled row, which is look-ahead. 0.44–0.70% of
observation rows per vintage were affected.

The fix (operator-approved and merged) bounds the period by the **filing date**: the period is the latest end of the report's year-length
USD durations that end on or before the filing date. Before merging it was checked on Boeing and 20 other rows against the filed cover page
("Period of Report"), 21 of 21.

### 2.2 The new validation (all companies, against SEC's `reportDate`)

SEC's submissions file lists, for each accession, a `reportDate` filed with the form (so it is point in time). Every annual accession
(10-K, 20-F, 40-F, 10-KT and amendments) of all 20,175 companies in the data store was dumped with the legacy code and with the fixed code,
and compared with `reportDate` (including SEC's paged history files). A **disagreement** is a period more than 10 days from `reportDate`;
accessions SEC does not list are counted apart, never as agreeing.

**(a) The 877 accessions whose period the fix changed:**

| | Agrees with reportDate |
|---|---|
| Fixed period | **856 (97.6%)** |
| Legacy period | **0** |

21 still disagree. They include:
- **late filers**, for example CIK 1379043: an FY2016 10-K filed in 2019 that holds 2018 durations, so the filing-date bound picks 2018;
- **odd `reportDate`s**, for example CIK 941548: `reportDate` 2012-02-15 and 2013-02-15 for calendar-year reports, which are not period
  ends at all.

**(b) The gate-2b universe proxy** (gate 2's 2026 universe, 2,122 companies):

| Annual accessions | Agree | Disagree | Not listed by SEC |
|---|---|---|---|
| 26,213 | 26,118 (99.64%) | 94 (0.36%) | 1 |

The 94 disagreements, as (inferred period − `reportDate`) in days: minimum −730, median −77, maximum +365; 30 of them more than 200 days
apart. So most residual cases put the period **earlier** than SEC does, by about a quarter to two years — consistent with late or
transition-period filings, and with a few `reportDate`s that are not period ends.

### 2.3 The options

| Option | What | Cost | Effect |
|---|---|---|---|
| **R-now** | Take `reportDate` as the period's authority wherever SEC lists it **and** it lies within a year-length window of a duration end in that filing; otherwise keep the filing-date rule. Build before gate 2b's freeze. | A rebuild of the priors cascade (observations, tables, near-term tables) and a re-run of E1–E8: about the size of the fiscal-year rebuild; competes with the decay-curve work for the same window | Touches ~0.4% of accessions; gate 2b's universe 99.64% → near 100% consistent with SEC |
| **R-after** | The same rule, built after gate 2b's freeze, for the next version | None now | Gate 2b runs with the 94 disagreements listed and known |
| **R-never** | Keep the filing-date rule. The alternative authority, storing XBRL `DocumentPeriodEndDate` with each fact, is also a store change | None | The residue stays, documented |

The coordinator's recommendation is **R-after**: 0.36% of the universe's accessions, the residue is listed, and the freeze window is
better spent on the decay curves. The operator decides.

### 2.4 Questions on decision 2

1. **Is `reportDate` trustworthy enough to be the authority,** given cases like CIK 941548 (a `reportDate` that is a filing-ish date, not
   a period end)? Is the "within a year-length window of a duration end in the filing" guard enough, or should `reportDate` only break
   ties between candidate periods the filing itself contains?
2. **Is `reportDate` really point in time?** It is filed with the form; can SEC revise it later in the submissions file, which would make a
   rebuild from today's file look ahead?
3. **Is 0.36% material for gate 2b?** A mislabelled period shifts a growth outcome or a base year by a year for that company. With about
   150 companies per date, expect roughly 0–1 affected per date. Is that negligible, or concentrated where it hurts (late filers are
   distressed more often)?
4. **Late filers (CIK 1379043):** for an FY2016 10-K filed in 2019 holding 2018 durations, which period is "right" for a valuation dated
   in 2019 — the fiscal year the form claims, or the latest numbers it contains? The filing-date rule picks the latter.
5. **Is `DocumentPeriodEndDate` the better authority** (it is in the filing's own XBRL), worth the store change?

---

## What is not asked here

- E5 and E8 on v2.0.3: computing now, verdicts sealed; a separate cross-check if needed.
- The v2.0.3 interim clip (operator-confirmed) and the financing-aware growth model meant to replace it (a later registration).
- Gate 2's scoring and the tag-consistent outcome rules (the other session's work).
