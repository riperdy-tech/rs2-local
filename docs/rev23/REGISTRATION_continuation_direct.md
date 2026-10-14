# Registration: a directly measured year-3 continuation for engine v2 (fork 2, 2026-10-14)

**Status: APPROVED by the operator 2026-10-14 21:44 (SPEC_rebuild AL.40).** Written before any number from the candidate existed. It replaces
`REGISTRATION_decay_curve_monotone.md`, which is withdrawn (SPEC_rebuild AL.39) before any candidate was scored.

## 1. The problem

**How v2 continues today.** After year 3, engine v2 sets growth to `g_T + (g_3 − g_T)·λ_t`, with `λ_t = d̃_t / d̃_3`:
- `d̃` is the running minimum of the growth-decay curve;
- the curve is the median of `(g_k − g_T)/(g_1 − g_T)`, so it is normalised by the **year-1** deviation;
- `λ_t = 0` when `d̃_3 = 0` (`RULE_FLAT_DECAY`).

v2 therefore never measures the quantity it needs, which is how much of a **year-3** deviation survives to year k. It infers that as a ratio
of two points on a curve built for something else.

**The result is close to binary** (all 133 growth-decay curves of `priors_v3_fy`, 2016–2025; AL.39):
- **17 curves are flat** (`d̃_3 = 0`): the year-3 deviation is dropped at year 4. In vintage 2025, these are operating bands 0–3, which
  hold 64% of the operating pairs. The raw medians at k = 3 are negative there (−0.009 to −0.105) and are clipped to 0.
- **Of the other 116, 93 have `λ_4 = 1`** (the deviation carries undiminished into year 4) **and 57 have `λ_10 = 1`** (it carries to year
  10).
- **The financial ROTE continuation behaves the same way.** In 2025, `rote_retention`'s positive band and its pooled band are pinned,
  and its negative band is flat.

**Why the earlier draft is withdrawn.** Isotonic smoothing of `d` (candidates I and S) pools a rise backwards into `d_3`:
- it changes years 2–3, and so v1's path and v2's year-1–3 centres;
- it still leaves `λ = 1` over the pooled block; in 2025, `λ_4 = 1` in 9 of the 10 non-flat curves.

## 2. The candidate, fixed now

**C (direct continuation), for `growth_decay` in both families** (operating revenue growth; financial tangible-book growth). For each
family, growth band and k = 4..10:

- **The estimate:** `λ_k` is the L1 regression slope through the origin of `y = g_k − g_T` on `x = g_3 − g_T`, over the vintage's own
  observation pairs. That is the weighted median of `y/x` with weights `|x|`.
  - Pairs with x near zero get little weight, so no single ratio can explode.
  - It is the least-absolute-deviation fit of the very formula the engine uses.
- **Bands:** the same as `growth_decay`'s, assigned from `g_1`, so a company's band does not change.
- **Then, as today:** clipped to [0, 1]; measured while n ≥ MIN_N = 50; the last measured value held to year 10; then the running minimum,
  so a rise is flagged and never amplifies. Rises are reported.
- **Years 1–3 are untouched:** no input, table or draw of years 1–3 changes. That is checked by an identity test (below).

**K** is v2.0.3 as frozen: `λ_t = d̃_t / d̃_3`, and 0 when `d̃_3 = 0`.

**Out of scope here:** the ROTE continuation (`rote_retention`, `excess_fade`). The same estimator, with y and x the deviations of
`ROTE_k` and `ROTE_3` from the population-median ROTE (the `excess_fade` reference), is **measured and reported** alongside. A separate
registration follows if it is adopted.

## 3. The test (fixed before any number exists)

**Data.** The per-vintage panels on `priors_v3_fy`. For each vintage V from 2017 to 2024:
- `λ` (C) and `d̃` (K) are estimated only from the observations V's priors used;
- they are scored on the realised growth at k = 4..8 of the pairs whose year-k outcome was filed after V's cut (walk-forward).

**Scored quantity.** `ĝ_k = g_T + (g_3,realised − g_T)·λ_k`. Anchoring on the realised year 3 isolates the continuation from every
year-1–3 forecast.

**Statistic.** The median absolute error of `g_k`, per family and per k from 4 to 8, pooled over vintages.

**Bar for adopting C:** C's pooled median absolute error is not worse than K's at every k from 4 to 8 in both families, and strictly better
at k = 4 or 5 in at least one family. Nothing is changed after scoring.

**Reported, not barred** (methods fixed now):
- **by vintage:** the C − K difference, with n and the contributing vintages for every family × k cell;
- **uncertainty:** a paired, company-clustered bootstrap 90% interval of the C − K difference in median absolute error per cell (1,000
  resamples of companies, seed 20261014). If an interval spans 0 at k = 4 and k = 5, the report says "no demonstrated winner" even when
  the bar is met;
- **the cumulative path:** the median absolute error of the cumulative log revenue (or tangible book) over k = 4..8;
- **counts:** flat, `λ_4 = 1` and `λ_10 = 1`, per vintage, for C and K;
- the ROTE measurement of section 2.

## 4. What adoption means

**v2.1** is v2.0.3 with C's continuation. It needs a priors table addition (`priors_v3_fy` + `continuation`); the near-term tables are
unchanged.

**Before v2.1 values anything:**
- **an identity test:** v2.1 and v2.0.3 give the same years 1–3 (draws, revenue, margins, cash flows) on the E8 samples;
- **E8 and E5 re-run** on their registered samples, with their bars unchanged.

**Gate 2b:**
- It freezes on v2.0.3 (K) on schedule.
- Its bars (B2, B3) score q1 measures only (AK.53), which no year after 3 enters. With the identity test passed, its verdict therefore
  applies to v2.1 unchanged.
- This is for the operator and the gate-2b owner (fork 1) to confirm.

**Real money:**
- Adopting C, or the operator's explicit acceptance of K's binary continuation, is a **condition for real money** (like B4). It is not a
  condition for paper (shadow) operation.
- If C fails its bar, K stays, and its behaviour is documented on every verdict (the existing `RULE_FLAT_DECAY` and `RULE_DECAY_ENVELOPE`
  flags).

## 5. Approval

For the operator. The definitions in sections 2–4 are fixed from approval. No number from C exists at the time of writing.
