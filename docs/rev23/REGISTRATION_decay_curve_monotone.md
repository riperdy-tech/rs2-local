# Registration: a monotone growth-decay estimator for the priors (DRAFT, fork 2, 2026-10-14)

**Status: WITHDRAWN 2026-10-14 (SPEC_rebuild AL.39), before any candidate was scored, on the outside reviews of cross-check 13.** Isotonic
smoothing changes years 2–3 and still leaves λ = 1 over the pooled block. Superseded by `REGISTRATION_continuation_direct.md`. The text
below is kept as it was reviewed.

**Original status:** a draft for the operator, written before any result of a candidate exists.

**Why now.** AK.51 ruled that a smoothed or monotone estimator goes to the operator before gate 2b's freeze if the running-minimum envelope's pins
are common. AL.35 measured them on `priors_v3_fy`:
- **pins are common:** in 54 of 133 growth-decay curves (41%), d_4 > d_3, so v2.0.3 holds the year-3 growth deviation at full strength in
  year 4;
- 8 of the 14 vintage-2025 curves are pinned, 2 of them for the whole horizon;
- there are no cliffs.

## 1. What the curves are and why they rise

**What they are.** For each family and growth band, `growth_decay` is the median, at horizon k, of the ratio
(g_k − g_T)/(g_1 − g_T). It is measured while at least MIN_N = 50 pairs stand behind it, clipped to [0, 1], and the last measured value is
held to year 10.

**Why they rise.** Many curves are measured only to k = 1–5. The medians are noisy where n is small, so a rise at k = 4 (for example 0.131 →
0.217) is held for the remaining years. AL.32 showed how noisy they are: correcting a few hundred observation rows moved some points by up to
1.0.

**Who uses them:**
- v1 (frozen for gate 2 only) uses them directly: year-t growth = g_T + (g_1 − g_T)·d_t;
- v2.0.3 uses them through the year-3 continuation, d̃_t/d̃_3 with d̃ the running minimum;
- v2's year-1–3 centres use v1's own path (section 2 of SPEC_engine_v2).

## 2. Candidates, fixed now

| | Estimator | What changes |
|---|---|---|
| **K (keep)** | as measured; v2.0.3's envelope after year 3 | nothing |
| **I (isotonic)** | the measured medians replaced by their **weighted non-increasing isotonic fit** (pool-adjacent-violators, weights n_ratio), then clipped to [0, 1] and held as now | removes the rises; a curve that never rises is unchanged |
| **S (shrunk isotonic)** | as I, but each point first shrunk toward the family's pooled curve at the same k by n/(n + 200) | as I, and also damps the thin long-horizon points |

- **No parametric shape:** no exponential form is imposed, because the measured shapes include a fast early drop.
- **Scope:** `growth_decay` only. `margin_retention`, `rote_retention`, `ronic_fade` and `excess_fade` are reported with the same pin counts
  and left as they are unless a separate registration covers them.

## 3. The test (fixed before any number exists)

**Data.** The per-vintage panels on `priors_v3_fy` (AL.20–AL.21). For each vintage V from 2017 to 2024:
- the curves are estimated with only the observations V's priors used;
- they are scored on the **realised growth at k = 4..8** of the observations whose year-k outcome was filed in the following years, which V
  never saw (walk-forward).

**Scored quantity.** The forecast g_T + (g_1,realised − g_T)·d_k, with the realised year-1 growth as the anchor. That isolates the curve's
shape from the year-1 forecast.

**Statistic.** The median absolute error of year-k growth, per family, per k from 4 to 8, pooled over vintages and by vintage.

**Bars:**
- **Adoption of I or S:** its pooled median absolute error is not worse than K's at every k from 4 to 8, in both families, and strictly
  better at k = 4 or 5 in at least one family.
- **Choosing between I and S:** S is chosen only if it beats I by that same rule. Otherwise I is chosen, as the simpler.
- **No change** to MIN_N, the clipping, the held tail, the bands or any other curve.

**Reported, not barred:**
- pin and cliff counts per vintage;
- the change in v2.0.3's E8 measures on the AL.29 diagnostic dates only;
- the shift in v2's year-1–3 centres.

## 4. What adoption means

- A new priors version (`priors_v5`: `priors_v3_fy` with the new growth-decay estimator) and new near-term tables (`priors_v4_fy` rebuilt on
  it, because v2's centres read v1's path).
- **Re-run in full:** E1–E8 on the new version, the AL.27–AL.35 E8 bars unchanged.
- **Untouched:** gate 2's frozen inputs (`c7d7a4f`, `priors_v3`).
- **Gate 2b** freezes on whichever version passes before its freeze. If none passes in time, it freezes on K (`priors_v3_fy` +
  `priors_v4_fy`) with the pins documented.

## 5. Approval

For the operator, after the outside review (cross-check 13) if the operator wants one. The definitions in sections 2–4 are fixed from
approval; no number from a candidate exists at the time of writing.
