# Engine v2 specification — DRAFT, 2026-10-11 13:38: base rates as the point forecast, measured dispersion for years 1–3

Recovery plan S4. Written by the coordinator during gate-2 run 2, before any gate-2 outcome is read. Engine v2 is
needed in every S3 branch: it is the best non-AI forecaster, the prior Muse's deviations are transported to (C1), and
the baseline every later system must beat (gate 2b B1).

**Its basis is development evidence only:**
- the forecast study (`review-2026-10/forecast-study` `c0400a5`, `984ed11`; outputs
  `scratch/rev23/forecast_study/out/`);
- the coordinator's audit of it (Addendum AB);
- Addenda Y and AA.

Nothing here is fitted on a return or on any date after 2024-12-31.

## 1. What changes and what does not

| Part | c7d7a4f (v1) | v2 |
|---|---|---|
| Years 1–3, point forecast (P50) | the chain at the prior's median | base-rate rules of section 2, one per family, variable and year |
| Years 1–3, dispersion | whatever the input draws imply; measured coverage 71% / 33% / 9% | drawn directly from measured residual distributions of the v2 forecast itself (section 3) |
| Years 4–5 | the chain from year 0 | the same chain shapes, started from the year-3 draw (section 4) |
| Years 6+, terminal value, ROIC path, reinvestment, maintenance, equity bridge, discount rate | Addenda H–J | **unchanged** |
| Long-run inputs (m_5, ronic, rote_target) and their priors | priors v3 | **unchanged** |
| The priors Muse is shown in pass 1 | priors v3 | **unchanged**: Muse's prompts and positions do not change |
| Operating-leverage model | — | not used (rejected on evidence, AB 4) |
| Commodity, REIT, utility, pre-profit families | out of scope (V3) | out of scope (S6 decides) |

**The engine files of `c7d7a4f` are not edited.** v2 is new modules (`valuation/engine_operating_v2.py`,
`valuation/engine_financial_v2.py`, `valuation/near_term.py`) with `ENGINE_VERSION = "v2.0"`. Gate 2 stays reproducible
on the frozen engine, and its freeze check (the engine diff against `c7d7a4f`) stays empty.

## 2. The point forecast for years 1–3 (P50)

**Notation:**
- `i_k` is the unconditional population median of the year-k outcome of the family: all companies of any size in the
  SEC archive, whose outcome annual report was filed before the vintage cut. This is candidate (i) of the study.
- `ii_k` is the code's year-k path at the prior's median, computed by the v1 chain unchanged (candidate (ii)).

| Family | Variable | Rule | Measured basis (study headline, walk-forward 2018–2024) |
|---|---|---|---|
| operating | revenue growth, k = 1 | `i_1 + 0.5·(ii_1 − i_1)` | Fitted w (last three years) 0.53. MAE 0.1317, against i 0.1326 (t −2.9) and ii 0.1324 (t −2.1). |
| operating | revenue growth, k = 2, 3 | `i_k` (w = 0) | Fitted w 0.05 and 0.00. ii is worse than i at k = 3 (0.1269 against 0.1200, t +3.7). |
| operating | operating margin, k = 1–3 | `ii_curve_k = med8 + r_k·(m_0 − med8)`, the code's retention-only path (w = 1) | Beats persistence by 6.1%, 8.4% and 12.1% in MAE (Study B, t −5.3, −3.9, −3.8). The 2025 holdout was worse than persistence (AB 2); the edge is small, not stable. |
| financial | ROTE, k = 1–3 | `i_k + 0.75·(ii_curve_k − i_k)` | Empirical-Bayes w 0.74 / 0.83 / 0.85. b_eb MAE 0.0612 against ii 0.0630 at k = 1 (AB 3: about 3%). The retention path beats persistence by 11–19%. |
| financial | tangible-book growth, k = 1–3 | `ii_k` (w = 1) | Not ruled in AB. i, ii and the blends are within 1% at k = 1–2. The code is kept, a minimal change, stated. |

**Fixed constants.** The weights 0.5, 0, 1, 0.75 and 1 are fixed constants of v2.0, not refitted per vintage. They come
from the 2018–2024 study, so v2's own development validation (section 7) is in-sample for them. Their out-of-sample
test is gate 2b (B1–B3, against V2 and the base rates).

**The population medians `i_k`.** They are measured per vintage under the priors' rule: a valuation date T uses vintage
year(T) − 1, built only from fiscal years and outcomes whose annual reports were filed strictly before 1 January of
year(T). They are stored in the vintage's new `near_term` table.

**A missing piece is an abstention, never a fill-in.**
- If `ii_k` cannot be formed (the v1 chain refuses), the company is refused with v1's reasons, exactly as today.
- If `i_k` has fewer than 50 observations, the variable is refused and named.

**The Muse interface for S5.** Each near-term centre accepts an optional deviation, `deviations[variable][k]`,
defaulting to none. S5 defines how Muse's position maps into it. The default reproduces V2 exactly, and a deviation is
stamped in the result.

## 3. Dispersion for years 1–3: measured residuals of the v2 forecast

**What is drawn.** A draw for variable v and year k is `P50_v,k + e_v,k`. `e_v,k` is drawn from the empirical
distribution of v2's own walk-forward residual (outcome minus v2 forecast) in the company's cell. So the bands are
built to cover what v2's forecasts actually missed by in the past, at the same horizon and state.

**Residual tables,** built per vintage from the priors' observation panel:
- **The panel:** every company in the archive with a filed annual report, delisted companies included, of market cap
  at least $300M at the origin (the gate universe's floor), with origins at each 30 June before the cut.
- **Each residual:** v2's forecast at that origin, rebuilt from that origin's own vintage, against the year-k outcome
  first filed. The outcome's annual report must be filed before the vintage cut.
- **What is kept:** quantiles P1, P5, P10, P25, P50, P75, P90, P95 and P99, with linear interpolation between them.

**Cells,** following the priors' merge rules (MIN_N 50; merges stated in `meta["fallbacks"]`):
- **growth:** size bucket × the company's growth band (the g1 cell axes of priors v3);
- **margin and ROTE:** the current-level band (quintiles within family, as Addendum I1);
- **merges:** an undersized cell merges to the family pool; an undersized family pool refuses the variable.

**Amended 2026-10-13 (SPEC_rebuild AL.1):** for the two growth variables (revenue growth, tangible-book growth) the residual is measured and drawn in log space, `log(1 + outcome) − log(1 + forecast)`, so no draw reaches −100%. The chains also refuse growth at or below −100% as an invalid draw.

**Dependence.** One Gaussian copula per family holds:
- the residuals of one variable across k = 1, 2, 3;
- the growth and margin residuals in the same year;
- the year-3 margin residual with the drawn m_5, so the path into the long run is coherent.

Its rank correlations are measured on the same residual panel. An unmeasurable pair falls back to independence,
stamped (the priors v3 convention).

**The P50 of the drawn distribution.** The residual distribution's median is generally not zero. It is kept, not
re-centred, so the drawn P50 is v2's forecast plus the measured median bias of its cell. This is reported as
`median_bias`. The point forecast of section 2 is reported separately as `forecast_p50_rule`. Gate 2b scores the
calibrated distribution; G1-type comparisons use the distribution's P50.

## 4. The chain after year 3

**Operating:**
- **Growth:** `growth_t = g_T + (g_3 − g_T)·d_t / d_3` for t ≥ 4, so the measured decay curve continues from the
  year-3 draw toward terminal growth. `g_T` is Addendum H2, unchanged.
- **Margin:** `margin_t = m_3 + (m_5 − m_3)·(r_3 − r_t)/(r_3 − r_5)` for t = 4, 5, and m_5 after. This is the measured
  retention shape between years 3 and 5, and m_5 is the unchanged H1 level input. When `r_3 = r_5` (a flat curve) the
  margin moves to m_5 linearly over years 4–5, stamped.
- **Unchanged:** the ROIC path (H3), reinvestment priced at m_5, maintenance (the Greenwald gap), the no-growth rule
  for non-positive m_5 or L_5 (I2), and the equity floor.

**Financial:**
- **ROTE:** ROTE_t for t ≥ 4 fades from the year-3 draw toward `rote_target` along the measured `rote_retention`
  shape, in the same way.
- **Tangible-book growth:** the same, along `growth_decay`.
- **Unchanged:** the excess-return fade (I4) and the terminal excess.

## 5. What the result carries

Everything v1 carries, plus:
- `engine_version: "v2.0"`;
- `forecast_years: {1, 2, 3}`: per measure, P10, P25, P50, P75 and P90 of the drawn distribution, `forecast_p50_rule`
  and `median_bias`;
- the cells used and the fallbacks;
- `deviations` (none by default);
- the copula pairs measured and those falling back to independence;
- `near_term_vintage` with its table hashes.

`forecast_year1` is kept with v1's meaning (year-1 quantiles), filled from `forecast_years[1]`, so every consumer reads
the same key.

## 6. Building

1. **`valuation/priors_build/near_term.py`** builds, per vintage, the `i_k` medians and the residual tables. It reuses
   the observation panel and the forecast study's pass-1 code path (`pass_priors.py`) for `ii_k`. It writes into a new
   data directory `data/priors_v4/` (the v3 tables are copied unchanged, the `near_term` tables added) and hashes every
   file into the vintage manifest.
2. **The cut proof:** the `test_priors.py` method applied to the new tables. Every fact filed after the cut is changed,
   and the tables must stay identical.
3. **`valuation/near_term.py`** holds the centre rules, the residual draws and the copula.
4. **The engines `engine_operating_v2.py` and `engine_financial_v2.py`** reuse v1's functions for everything section 1
   marks unchanged, by import, without copying.
5. **CPU only.** The residual build re-runs v1's chain on the panel at many origins, which is the heavy step. It runs
   only while no GPU run holds the model (memory: `ram-limit-during-gpu-runs`).

## 7. Validation

Its validation is registered in `REGISTRATION_engine_v2.md`, written with this specification and before any v2 number
exists.

## 8. What v2 deliberately is not

- **Not a return model.** Nothing is fitted on returns or prices.
- **Not a claim of company-specific revenue skill.** For revenue it is the base rate, with half the code's year-1
  deviation (AB 1).
- **Not a change to what Muse sees.** Pass-1 prompts, packs and priors are unchanged, so gate-2 evidence about Muse
  carries over.
- **Not tuned on gate-2 or gate-2b data.** Its weights are the study's constants, and its residual tables end at the
  vintage cut.

## 9. Approval record

Approved by the operator on 2026-10-11 21:04 KST ("approve the engine-v2 spec and registration").
