# Engine v2.1 registration: the empirical copula — DRAFT, 2026-10-13

Written before any part of it is built or measured. **Its basis:**
- **The need:** D-T1 triggered (SPEC_rebuild AK.20). Revenue and margin residuals fall together 1.6–1.9 times as often as v2.0's Gaussian
  copula draws, and so do several ROTE pairs. A symmetric t(ν=4) copula was checked and withdrawn, because it does not fit.
- **The approval to write it:** the operator, in AK.23.
- **The conditions it must meet:** AL.5 item 5, from the outside review.

The build belongs to fork 2 (`valuation/near_term.py`, `priors_build/near_term.py`, `data/priors_v4`). This document is the
coordinator's.

## 1. What changes, and what may not

- **Changes:** only the dependence among the six near-term inputs of a family. For operating, revenue growth and margin in years 1–3; for
  financial, tangible-book growth and ROTE in years 1–3.
- **Unchanged:**
  - every marginal: the centres (section 2 of `SPEC_engine_v2.md`), the residual quantile tables, the cell rule, the median bias and
    the log-space growth (AL.1);
  - the v1 chain after year 3, v1's own inputs and their Gaussian copula;
  - the year-3 level's pair with its long-run partner, which stays independent as in v2.0 because it cannot be measured.
- **A precondition, checked by the build:** in the v2.0 matrix no near-term input is correlated with a non-near-term input. If one is, the
  build stops and this registration is revised, because the near-term block could then not be drawn separately.

## 2. The candidate

**The checkerboard empirical copula of the residual rank vectors.**

- **The vectors.** For vintage V, take the residual panel exactly as `priors_build/near_term.residual_frame` builds it at V's cut. The
  vectors are the company-dates with **all six** residuals present (the complete vectors of the family).
- **The ranks.** For each of the six coordinates, the residual's rank within that coordinate's family pool at V, with average ranks for
  ties, giving `R_ij ∈ {1..n}` over the n complete vectors.
- **The draw,** with the engine's own seeded stream so that draws stay common:
  - pick a vector index J uniformly from 1..n;
  - for each coordinate, `U_i = (R_Ji − 1 + V_i) / n` with V_i ~ U(0, 1) independent;
  - feed U_i to the coordinate's own QuantileDist, exactly where v2.0 feeds the Gaussian uniform.

  This has no fitted parameter, keeps any asymmetry, and has continuous uniform marginals.
- **The minimum.** At least 500 complete vectors for the family at V. Otherwise the family keeps v2.0's Gaussian copula at that
  vintage, stated in the result.
- **Missing data, by rule.** Only complete vectors enter. That favours companies with three years of outcomes, the same survival
  selection the year-3 residuals already carry. This is stated, not corrected.
- **The table.** Each vintage's `near_term.json` gains `copula_vectors` (the n × 6 rank matrix, integers) and its sha256. E6's cut
  proof covers it.

## 3. Validation, out of time (definitions and bars fixed now)

Each test vintage V uses the copula built at V, compared with the **untouched** residuals of V + 1: the rows whose year-k outcome was
filed in [cut(V), cut(V + 1)). They are never used in V's build. Test vintages V = 2019–2024. Pooled results are the decision;
per-vintage results are reported.

| # | Test | Bar |
|---|---|---|
| C1 | **Joint tails, both, dependence only.** For each pair of the 18 measured in D-T1, the test residuals are rank-transformed **within the test set**, so the marginals cancel. The co-exceedance rate at q = 0.10 is computed in the lower tail and in the upper tail. The model's rate for the same pair and tail is computed from the copula built at V: for v2.1 by drawing 1M vectors, for v2.0 from its Gaussian. Pooled over test vintages, pairs with n_test ≥ 300. | On every pair and both tails, v2.1's ratio of test to model rate lies within **0.67–1.5**. **And** v2.1's mean \|log ratio\| over pairs and tails is below v2.0's. |
| C2 | **Joint fit, a proper score.** The energy score of each test company-date's six-dimensional rank vector under the copula built at V. Reported per vintage and pooled. | v2.1's pooled mean energy score ≤ v2.0's, with the paired difference's one-sided 90% upper bound < 0. The bootstrap resamples companies and origin years independently (the B5 two-way method, 2,000 resamples, seed 20261013). |
| C3 | **Marginals untouched (E3 and E4 re-run).** v2.1 with common draws. | Every E3 coverage and every E4 interval score within ±0.5 pt of v2.0's: Monte Carlo only. Anything larger is a defect in the build, not a result. |
| C4 | **E5 re-run.** The oracle IC, as registered in `REGISTRATION_engine_v2.md`. The copula changes the value distribution and its mean, so rankings can move, and no invariance is assumed. | E5's own bar: at least v1's oracle IC − 0.02, pooled and by year; no family's sort inverted. |
| C5 | **Value-level effect, reported only.** On the gate-2 run-2 company-dates (inputs only, no outcomes): the change from v2.0 to v2.1 in P10, P50, `mean_iv` and `prob_value_above_price`, and the number of rows whose verdict-contract direction or size would change. | Reported. |

**The order is fixed:** the build, then E6 for the new tables, then C3 (a build defect stops everything), then C1, C2, C4 and C5. The
definitions above are frozen at approval. No pair, quantile level, minimum, vintage range or bar may change after any number from C1–C5
exists.

## 4. What a pass means, and what it does not

- **A pass makes v2.1 a candidate only.** Adoption is the operator's decision with the evidence (AL.5). Before B4's SYSTEM freeze, an
  adopted v2.1 becomes the engine that gate 2b runs. After the freeze, it is a new version: shadow-only until its own gate.
- **A pass says nothing about E3's shock-year marginal undercoverage** (AL.5 item 4). The copula cannot fix marginals.
- **A failure keeps v2.0** with `joint_tail_undercoverage` (contract v4, section 8). Any further candidate needs its own registration.

## 5. What may never happen

- A copula, minimum, pair set or bar chosen or changed after any C-test result is seen.
- A change to any marginal, weight or cell rule under this registration.
- Use of any gate-2 or gate-2b outcome.

## 6. Audit

- **An independent recomputation** of C1 and C2 by a script that imports nothing from `valuation`. It works from an exported residual
  panel per vintage, as `d_t1_from_csv.py` does for D-T1, and every published C-number must agree.
- **E6's cut proof** for the new `copula_vectors` of every vintage.

## 7. Approval record

Not yet approved. It is for the operator, after fork 2 reads it (its build) and cross-check 10.
