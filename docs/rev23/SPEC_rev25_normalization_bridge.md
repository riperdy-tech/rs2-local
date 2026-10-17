# Spec: the revision 25 normalization bridge (Stage 0.2, amendment A), v1, 2026-10-16

- **What this is:** the one canonical mathematical path from the analyst's declarations to the cash flows the desk values, and the
  deterministic checks between them.
- **Its inputs:** `PLAN_rev25_2026-10-16.md` (v2) 0.2 and `H3_DECOMPOSITION_REPORT.md`.
- **What it does not do:**
  - it sets no threshold value; the tolerances are named here and calibrated in 0.4;
  - it does not touch arm A, which runs revision 24 as it ran.

## 1. Why the bridge is needed
- **Revision 24 asks for two unconnected things.**
  - `near_term_earnings` and `normalized_earnings` are free $B numbers, with no metric, no horizon and no link to the path.
  - The path itself is owner-earnings growth rates. From them the desk implies revenue, by scaling the consensus year-5 revenue with the
    scenario's year-5 owner earnings, and earnings, by scaling the consensus year-5 earnings the same way.
- **The stated figures therefore cannot be checked against the path.** H3 measured what that costs:
  - read as owner earnings rather than earnings, the same stated figures move CMRE by +87 points against −1, and UGI by +107 against +10;
  - MU's stated normalization, if carried, halves the value, yet it is nowhere on the path.

## 2. The measures, the basis and the units
| Symbol | Meaning | Source |
|---|---|---|
| R_t | revenue in year t, $B | R_0 = the facts' `rev_L` (base fiscal year, filed); R_1..R_5 from the analyst's revenue growth |
| m_t | **earnings margin**: earnings before acquired-intangible amortization over revenue (the desk's X basis, the same as `x_L`, `m5` and `m_tc`) | m_0 = `x_L`; m_1..m_5 declared by the analyst |
| E_t | earnings, R_t × m_t, $B | derived |
| κ | owner earnings over earnings | derived once: κ = base_cf / E_0, held for years 1–5 |
| OE_t | owner earnings, κ × E_t, $B | derived |

**Operating margins** (`om_tc`, `om_L`, `om_trend`, `om_5`):
- They are printed as **context only**, each labelled "operating basis".
- No contract field takes an operating margin.
- **Where the analyst cites one,** for example "revert toward the historical 24%", the desk prints the X-basis figure for the same window
  beside it (`m_tc` for the 8-year median). That is the UGI case: 15% and 9.6% on two bases.

## 3. The declarations (independent assumptions, per scenario)
Base is required. Bull and Bear inherit Base's declarations unless they give their own.

**The path:**
- `revenue_growth`: g^R_1..g^R_5, the annual revenue growth of years 1–5.
- `earnings_margin`: m_1..m_5, on the X basis.
- `long_run_margin`: unchanged, the X-basis margin at the end of the fade, year 5+F.
- `fade_years`, `terminal_g`, `terminal_ronic`, the discount rate and `base_cf`: unchanged.

**The normalization:**
- **`normalized_margin`** m_N: the X-basis earnings margin once any abnormal margin condition has ended.
- **`normalization_horizon`** H: an integer from 0 to 5+F, the first year in which the margin is at m_N. H = 0 means the margin is not
  abnormal today, so m_N is the current margin.
- **`normalized_revenue_base`** R_N0, in $B: today's revenue on a normal footing. It defaults to R_0. It differs only when the flags include
  `cyclical` and today's revenue is itself at a cyclical level, for example a price peak.
- **`structural_growth`** g_S: the annual revenue growth with the cyclical swing removed, a decimal.

**The flags**, composable and replacing the single `forecast_type`:
- `cyclical`, `structural_growth`, `structural_decline`, `turnaround`;
- any combination, or none.

**Derived, never declared:**
- **normalized earnings** N_t = m_N × R_N0 × (1 + g_S)^t, in $B and on the X basis. **N_0 is "normalized earnings at today's revenue
  scale"** and replaces the free `normalized_earnings` field.
- `near_term_earnings` becomes derived too, as E_1 and E_2.
- The memo quotes the derived figures; the verdict row stores them.

## 4. The forecast path (how it wraps the desk)
**Years 1–5:**
- R_t = R_{t−1}(1 + g^R_t);
- E_t = R_t m_t;
- OE_t = κ E_t;
- WC_t = intensity × (R_t − R_{t−1}), where intensity is the facts' `nwc_intensity`;
- flow_t = OE_t − WC_t.

This **replaces** revision 24's three conventions for revision-25 scenarios:
- owner-earnings growth rates;
- the consensus-scaled revenue in `_year5_revenue`;
- the base-normalized working-capital path of step 2d, no longer needed because revenue is explicit from the filed base.

**Years 6 on:** `long_run_value` is unchanged, with these inputs:
- e5 = E_5 = R_5 m_5, not e5_facts × OE_5 / oe5_facts;
- g5 = R_5 / R_4 − 1, the revenue growth. **This is a change:** revision 24 used owner-earnings growth.
- margin_ratio = `long_run_margin` / m_5;
- RONIC, the fade, the terminal value and the roll-forward exactly as in revision 24 step 2d.

**Year 10 and the other implied figures** come from the same path: R_10 = E_10 / m_10, and the 10-year revenue CAGR follows. The
plausibility gate reads them as before.

**Persist or rejoin, answered by the declarations, never by a rule:**
- **The revenue level persists** unless `cyclical` declares R_N0 ≠ R_0. In that case C3 below requires the revenue path to rejoin
  R_N0(1 + g_S)^t by H.
- **The margin moves** to m_N by H (C1) and to `long_run_margin` by 5+F.

**Where the bridge does not apply:**
- the firm frame, finite-life scenarios, R_0 or E_0 not positive, and a missing `x_L`;
- these keep revision 24's path, stamped `bridge_not_applied:<reason>`, and the run reports it;
- none of the 8 Stage 1 names is expected to hit this. Any that does is listed in the Stage 1 registration.

## 5. The deterministic checks
- **Each check returns** {id, status: pass | fail | not_computable, declared, derived, horizon, tolerance}.
- **A fail draws a structured reason request in the same turn** (0.3).
- **An unresolved fail makes the run not usable.**
- **Nothing is clamped, overwritten or re-labelled.**
- The margin path is m_1..m_5 as declared, then m_t = m_5 × (1 + (margin_ratio − 1) × (t − 5)/F) for t = 6..5+F.

| ID | Checks | Rule | Tolerance |
|---|---|---|---|
| **C1** (primary) | the margin path against the declared normalized margin and horizon | for each t from max(H, 1) to 5+F: \|m_t − m_N\| ≤ τ_m(t) | τ_m per horizon band (years 1–5, 6–10), in margin points |
| C1b | the end of the fade against the normalization | \|`long_run_margin` − m_N\| ≤ τ_m(5+F); a fail asks why the margin moves again after normalizing (a structural change, with its evidence) | as C1 |
| C2 | the direction of normalization against the cycle position | `cycle_position` peak ⇒ m_N ≤ m_0; trough ⇒ m_N ≥ m_0; mid ⇒ \|m_N − m_0\| ≤ τ_m(1) | τ_m(1) for mid; none otherwise |
| C3 | revenue against structural growth | at T = 5, and also at T = H when 1 ≤ H ≤ 4 and R_N0 ≠ R_0: \|R_T / (R_N0 (1+g_S)^T) − 1\| ≤ τ_R(T). With R_N0 = R_0 (no cyclical revenue) it checks that the path's 5-year revenue CAGR is g_S; with cyclical revenue it also checks that revenue has rejoined its normal level by H | τ_R(T), a relative revenue gap |
| C4 | the flags against the declarations | `structural_decline` ⇒ g_S < 0; `structural_growth` ⇒ g_S > `g_rev` (the record's trend) or a citation; `turnaround` ⇒ m_N > m_0 and H ≥ 1; `cyclical` ⇒ `cycle_evidence` is present; no flag ⇒ H = 0 or a reason | exact |
| C5 | the basis | every margin field is on the X basis; a declared value within τ_b of an operating-basis fact (`om_tc`, `om_L`, `om_trend`) and outside τ_b of every X-basis one (`m_tc`, `x_L`, `m5`) draws a basis question, and is never rejected | τ_b |

**On C3:** the window is years 1–5, the declared path. Years after 5 follow the desk's growth fade.

**The checks are composable:** C1 to C3 run for every scenario, and C4 runs on whichever flags are present. Cyclical and structural growth
together, for example, run C1, C2, C3 and both of C4's rules.

**Kept separate, not duplicated:**
- the 0.5 classification checks (growth trajectory, cycle against the cyclical margin measure, persistence, shrinking);
- the plausibility gate;
- the citation rules.

## 6. Kept apart
- **Independent:** the path (g^R, m_t, `long_run_margin`), the normalization (m_N, H, R_N0, g_S), the flags, and the existing terminal
  inputs.
- **Derived:** R_t, E_t, κ, OE_t, WC_t, N_t, the year-10 figures and every check result.
- **The desk report prints, per scenario:**
  - the derived R/m/E/OE/WC table for years 0–5;
  - m_t to 5+F;
  - N_0 and N_H;
  - the check table.

## 7. Worked example: MU, the pilot's iii_p50_s2401 Base, read under this spec
**The facts:**
- R_0 = 133.188, m_0 = `x_L` = 0.638;
- `m_tc` = 0.222 (X basis);
- `om_tc` = 0.244 (operating basis).

**Revision 24's path:** m_5 = 0.714 and `long_run_margin` = 0.35 at year 10.

**The analyst's reason text** says "revert toward historical 24% operating margin median". **Under C5,** 24% is the operating-basis median.
The X-basis median, 22.2%, is printed beside it.

**If the analyst had declared** m_N = 0.222 with H = 10:
- C1 fails at year 10: 0.35 against 0.222.

**If the analyst had declared** m_N = 0.35 and H = 10:
- C1 passes;
- C2 passes (peak, 0.35 ≤ 0.638);
- N_0 = 0.35 × 133.188 = 46.6.

The stated 80 is neither N_0 (46.6 at m_N = 0.35, 29.6 at 0.222) nor any figure the path implies at today's revenue scale. That is the disconnection H1 named; under this spec it could not arise, because N is derived.

**The conclusion:** the spec does not say which reading is right. It forces the analyst to choose one, and makes the path agree with it.

## 8. Versioning and the tests 0.3 must carry
- **The desk schema is `desk-schema 25.1`,** stamped on every run apart from `PACK_REVISION` 25 (0.10).
- **The tests:**
  - **the long run is unchanged:** for equal (e5, g5, margin_ratio, RONIC, fade, terminal), the bridge path's years-6-on value equals
    revision 24's `long_run_value` to 1e-9. Exact reproduction of a whole revision-24 value is not expected, because §4 changes e5 and g5
    by design;
  - **an independent recompute** (h3 style, importing nothing from rs2) reproduces the bridge desk's values on a fixed set of synthetic
    declarations;
  - each check in §5 has a pass, a fail and a not-computable case;
  - C1 to C5 have no write path to any input.

## v1.1: the rulings from the Stage 0.3 audit (2026-10-16)
These supersede the text above where they differ.

1. **C1b is a subset of C1,** because C1 reads year 5+F, where the margin is `long_run_margin`. C1b stays as its own reason message (a
   margin that moves again after normalizing). Measures count C1 failures only.
2. **C5 reads `normalized_margin` and `long_run_margin` only.** A near-term margin that equals an operating figure is not a basis claim.
3. **A horizon after year 5 is coherent only when** fade_years = H − 5, or m_5 = m_N, because the fade is linear to `long_run_margin`. The
   TASK and the tool schema say so.
4. **Every tolerance comparison allows 1e-12,** so a deviation equal to a tolerance written in decimals passes.
5. **`cycle_position` and `cycle_evidence` are optional desk-call fields** (top level or Base), so C2 and C4 can read them.
   - Without `cycle_position`, C2 is not computable.
   - C2 with `not_cyclical` has no rule: not computable, and no reason request.
6. **`near_term_earnings` is E_1, a number.** E_2 is in the bridge table. `normalized_earnings` is N_0.
7. **C4's "or a citation"** is answered through `bridge_C4_reason`, the same reason mechanism as every other check.
8. **A scenario the bridge does not apply to** keeps revision 24's path. Only that scenario may carry `explicit_growth`; its typed S12
   figures stand, stamped `s12_figures_typed_bridge_not_applied`.
9. **Under the bridge, the price-implied block** solves the Base through the bridge. `growth_years_3_5` and `year2_level` are not
   applicable, and the years-3–5 cap and the years-1–2 hold do not run: both read owner-earnings growth.

## v1.2: the classification checks (Stage 0.5), K1–K4
- **Where:** the desk, for desk schema 25.1.
- **The declarations move into the desk call.** `growth_trajectory`, `cycle_position` and `margin_persistence` are given beside the bridge
  declarations: top level or Base, and Bull and Bear inherit them.
- **The contract** keeps these fields, now filled from the desk call. The desk call is their single owner.
- **The evidence fields** (`*_evidence`) stay typed in the contract.
- **Each check:**
  - checks its own variable on the Base;
  - returns the same shape as C1–C5;
  - turns a fail into a reason request, `class_K<n>_reason`;
  - **never changes a label.**
- **The tolerances are registered priors,** frozen with this spec. No pilot fitting:
  - τ_g = 0.02, a growth-rate change;
  - τ_m = 0.03, the frozen bridge value.

| ID | Checks | Rule |
|---|---|---|
| K1 | `growth_trajectory` against the change in revenue growth | Δ = mean(g^R_4, g^R_5) − mean(g^R_1, g^R_2). **accelerating:** Δ > τ_g; **decelerating:** Δ < −τ_g; **steady:** \|Δ\| ≤ τ_g; **shrinking:** the 5-year revenue CAGR < 0. A falling growth rate is deceleration whatever its level (MPWR's +50% then +45% is decelerating). |
| K2 | `cycle_position` against the cyclical margin measure, today's margin against the record's through-cycle margin, d = m_0 − m_tc | **peak:** d ≥ τ_m; **trough:** d ≤ −τ_m; **mid:** \|d\| ≤ τ_m; **not_cyclical:** no rule. K2 reads margins only: "peak" does not require negative growth. |
| K3 | `margin_persistence` against `long_run_margin` (L), relative to today (m_0) and the record (m_tc) | When \|m_0 − m_tc\| ≤ τ_m the labels cannot be told apart, so the result is a pass, noted "not distinguishable". Otherwise: **structural:** \|L − m_0\| ≤ \|L − m_tc\| + τ_m (L stays nearer today); **transient:** \|L − m_tc\| ≤ \|L − m_0\| + τ_m (L returns nearer the record); **partly_structural:** L lies between m_tc and m_0, with τ_m allowed at each end. |
| K4 | "shrinking" against positive growth | `growth_trajectory` shrinking ⇒ `terminal_g` ≤ 0 and `structural_growth` < 0; each breach is reported separately. |

**Labelled pilot cases** (illustration only, not used to set anything):
- MU "mid" at m_0 0.638 against m_tc 0.222 fails K2;
- MPWR's falling growth labelled "accelerating" would fail K1.
