# S5 — Muse integrated with engine v2: specification and registration — DRAFT v2, 2026-10-13

**Drafting history.**
- **Draft v1:** 2026-10-12 23:13 (Addendum AK.1).
- **Draft v2:** this text. It applies the coordinator's rulings on the outside review of v1, recorded in Addendum AK.2.

Both were written while gate-2 run 2 was running, **before any gate-2 outcome was extracted or read.** Everything below is fixed
before A3 (scoring) reads an outcome. From the first read on, this file changes only by a dated, versioned note that names its reason,
and never in response to an outcome.

Recovery plan S5; remaining-work plan B1 and B4.

**It builds on:**
- `SPEC_engine_v2.md` (approved);
- `SPEC_muse_passes.md` section 4;
- Addenda Z 5, AD (R3, R8, the S3 branch rules) and AH (the annual-convention arms, the C1 fix);
- `REGISTRATION_gate2b.md` v2: its target is **fiscal year 1** (section 3), and B4 scores year-1 coverage on annual outcomes.

**The governing principle** (from the review, adopted): Muse influences SYSTEM only to the extent that its deviations improve
forecasts **of the same economic quantity and horizon** on data not used to fit them. That quantity is the fiscal-year-1 figure the
valuation uses.

## 1. When this applies

**In branch C1,** the procedure builds SYSTEM for gate 2b.

**In C2 and C3,** the same fit is run and reported as a diagnostic only, and nothing is adopted. SYSTEM is engine v2 alone, or v2 plus
a structural candidate registered under section 7.

## 2. What Muse can change, and what it cannot

An input moves SYSTEM only where gate 2 holds a measured outcome of its **year-1** consequence, and **only in year 1** (section 3).

| Family | Muse input | Measured consequence | Adjustable |
|---|---|---|---|
| operating | `g1`, `growth_persistence` | year-1 revenue growth | year 1 only |
| operating | `margin_target`, `margin_retention` | year-1 operating-margin change | year 1 only |
| operating | `ronic` | none in gate 2 | **no** (w = 0). Muse's implied year-1 ROIC against the realised figure is reported as a diagnostic. |
| operating, financial | `g_terminal` | none (Addendum H2) | **no** |
| financial | `rote_target`, `rote_retention` | year-1 ROTE change | year 1 only |
| financial | `g1` (tangible-book growth) | not measured | **no** |

## 3. The transport

For each company-date, measure m ∈ {growth, margin, ROTE}, and year k:

- **The deviation** is `Δ_m,k = muse_k − code_k`. Both are values of the v1 (`c7d7a4f`) chain: `code_k` with every input at the
  prior's P50, `muse_k` with Muse's positions on the inputs that feed m.
- **Why the v1 chain is the right unit.** Engine v2's company-specific near-term term `ii_k` *is* this same v1 chain
  (`SPEC_engine_v2.md` section 2), and v2 has no other map from inputs to the years 1–3 forecasts. So "Muse's effect computed within
  v2" equals `c_m,k·Δ_m,k`, where `c_m,k` is v2's own blend weight on `ii_k`: 0.5 for growth k = 1, 1 for margin, 0.75 for ROTE.
- **Transport.** `x_m,1 = v2_m,1 + w_m·Δ_m,1`, in the outcome's own units. The fitted `w_m` is the measured rate at which Muse's
  deviation transfers to the outcome, so any scaling difference between v1 and v2 is absorbed by w and measured, not assumed. Both
  `w·Δ` and `c·Δ` are reported.
- **Years 2–3: no Muse adjustment** (`w_m,2 = w_m,3 = 0`). Only year-1 outcomes exist; a weight for a later horizon needs its own
  evidence. `Δ_m,2` and `Δ_m,3` are reported as diagnostics. A later version may fit horizon-specific weights once year-2 outcomes
  accumulate, under its own registration.
- **Which positions.** Final positions if R3b keeps the red team; pass-1 (price-blind) positions if not.
- **Interface.** SYSTEM enters engine v2 through `deviations[m][1] = w_m·Δ_m,1`; nothing else in v2 changes.
- **Fallbacks, exactly as V2.** An input Muse did not anchor (unanchored, after the permitted retries) contributes Δ = 0. Its
  distribution is v2's own, unchanged. The result is stamped with the failure state; it is never shown as a Muse forecast.
- **Common random numbers.** The SYSTEM and V2 arms of a company-date use the same Monte Carlo draws, so their difference reflects the
  deviation only.

## 4. Fitting w (forecast loss only; gate-2 data only)

**The data.** Every scored gate-2 company-date with valid code, Muse and v2 forecasts. Masked and repeat runs are excluded.

**Two targets, both required.** The primary target is the one the valuation uses; the second gives the date coverage.
- **Primary, annual:** the fiscal-year-1 outcome (`outcome_extract.annual_outcomes`), on every company-date where it exists by the
  scoring date. Calendar-year companies mostly come from 2025-10-31 and 2025-12-31; non-calendar fiscal years come from all dates.
- **Breadth, q1:** the AH convention. Every arm forecasts the annual quantity and is scored on the next quarter, with a shared
  mismatch. It exists for all five dates.


**Amendment AK.37 v2 (approved by the operator 2026-10-14 14:39 KST: "approve AK.37 v2 and AL.22"; written before any gate-2b data exists and before
S5 is fitted; the rules and their measured basis are in SPEC_rebuild AK.37, AK.39 and AK.41):**
1. **Measurement.** Revenue growth and the operating-margin change come from **one filing's own comparative columns**
   (`rebuild_harness/gate2/same_filing.py`):
   - one accession, one tag, one unit;
   - among several revenue tags, the largest current value, and on a near-tie (within 0.5%) the largest prior;
   - a derived Q4 only with one tag across the 10-K and the Q3 10-Q, and no recast in between.

   The ROTE change keeps the `build_state` definition, with a net-income tag-consistency check reported beside it.
2. **Total revenue.** The chosen revenue figure must be verified as total revenue: either the largest of two or more tags, or a closure in
   the same filing (gross profit plus cost of revenue equals revenue, or revenue minus total costs and expenses equals operating income,
   within 1%).
   - A closure failure abstains, and is listed.
   - A figure with no test available is scored and flagged, and every bar is also reported on the verified rows only.
3. **Eligibility, both arms alike.** A target is not a forecast, and leaves the scored sample (listed), when its result was **public before
   the T cutoff**:
   - through an 8-K with Item 2.02 in SEC's filing index, accepted after the period's end; or
   - through an earnings release or the annual report in the pack; or
   - for the annual target, through the annual report filed on or before T.

   A quarter that ended more than 120 days before T is also excluded: a guard against a known XBRL artefact, not part of the benchmark.
   The quarterly benchmark is **the next quarterly result not yet public at T**.
4. **The register.** Every exclusion records the company, T, the target period, the metric(s), the public source with its acceptance
   timestamp, and the reason. The original and the eligible sample sizes are both reported.

   It applies to both targets here, the annual fit and the q1 breadth check, on gate-2 data.

**The procedure,** per family × measure:
1. Grid w ∈ {0, 0.05, …, 1.00}.
2. **Folds:** leave one date out. For each held-out date d, choose `w_fold(d)` by mean absolute error on the other dates' **annual**
   outcomes. Record date d's held-out errors on both targets, with `w_fold(d)` and with w = 0 (V2).
3. **Adoption.** w is adopted, with value equal to the grid w minimising annual MAE over all dates, **only if all of these hold, every
   one using the fold weights `w_fold(d)` only, never the final weight:**
   - **annual, out of fold:**
     - the paired median of `|x − y| − |v2 − y|` is < 0;
     - the upper end of its one-sided 90% bootstrap (2,000 resamples of whole companies, seed 20261013) is < 0;
     - n ≥ 150 pairs, from at least 2 distinct dates with ≥ 30 pairs each;
   - **q1, out of fold:** the paired median is ≤ 0 pooled, and ≤ 0 on at least 3 of the 5 held-out dates.

   Otherwise **w = 0**. With the annual data insufficient, w = 0, and the cell is named.
4. **Bounds:** 0 ≤ w ≤ 1.

**Reporting** (no new thresholds; the limits of five dates stated):
- per date: n, `w_fold(d)`, the paired median difference on both targets, and its contribution to the pooled result;
- the pooled result **company-date-weighted and equal-date-weighted**;
- drop-one-date stability: whether the adopted w stays favourable with each date removed from the final selection.

The bootstrap interval is labelled as uncertainty conditional on these dates, **not** as robustness across market regimes. Gate 2b is
the test on fresh dates.

## 5. The red team and repeatability (rules fixed now, read at S3)

**The red team (R3b).**
- **Kept** only if final beats pass 1 on at least one measure by G1's statistic (median < 0 and upper90 < 0), on the annual target
  where n suffices and otherwise q1, and is not worse on any measure (median d ≤ 0).
- **Otherwise dropped:** SYSTEM uses pass-1 positions, and the live system runs no P6 call.
- **Reported:** the loss differences by measure, and the accepted revisions by evidence category (a new filing quote, or a named
  mechanical error), so a legitimate correction is told apart from a new fact. Registered G4 and G4-strict behaviour is reported
  beside it.
- **What does not count:** a changed valuation or a more persuasive explanation is never a reason to keep the red team.

**Multi-sampling (R8).**
- **The rule:** `σ_run = sqrt(mean(shift²)/2)` per input; k is the smallest value with `1.2533·σ_run/√k ≤ 5`, the maximum over inputs,
  capped at 5. The median over k samples is used.
- **Reported:** σ_run per input and by family; which inputs set k; which stay above the 5-point target at the cap.
- **If k = 5 is not enough,** it is recorded as an unresolved limitation, not cured; gate 2b's B5 decides.

## 6. Calibration of SYSTEM's distribution

**The base distribution.** v2's year-1 distribution for the cell, shifted by the transport: every draw moves by `w·Δ`. Years 2–3 are
v2's own distributions, unchanged, since there is no Muse adjustment there.

*Erratum (AK.19, 2026-10-13, before any gate-2 outcome is read):* this sentence and the identity case below said "re-centred". That
contradicted `SPEC_engine_v2.md` section 3 (v2's measured median bias is kept, not re-centred) and this spec's own V5 (with w = 0,
SYSTEM equals v2 byte for byte in distributions). The meaning is the shift above: the median bias is kept and w = 0 gives v2 exactly.
Nothing else changes. **Confirmed by the operator, 2026-10-13 21:50 KST** (AK.23), with the AK.21 erratum to V5.

**Calibration of year 1,** on the **annual** year-1 target only, the same target gate 2b's B4 scores.

**Minimum:** at least 150 company-dates **and** at least 3 distinct dates with ≥ 30 each. Otherwise the calibration is the identity
(v2's bands, shifted by `w·Δ`), stated.

When the minimum is met:
1. Out-of-fold PITs `u = F(y)` under the base distribution, with folds leaving one date out.
2. **Two candidate monotone maps**, each fitted out of fold:
   - (a) isotonic regression of the PIT empirical CDF;
   - (b) a monotone cubic spline with 5 knots at the PIT quintiles.
3. **Selection** by out-of-fold mean interval score (α = 0.2), with ties to (b). The selected method is then refitted on all eligible
   data for use.
4. **Check:** out-of-fold P10–P90 coverage of 80% ± 7, with neither tail above 15%. If it fails, the identity is used, stated.

## 7. C2/C3: structural candidates (the pre-registration format)

Each candidate gets a short registration before its development run. It holds:
- the hypothesis, and the behaviour evidence that motivated it (never outcomes);
- the frozen design with hashes;
- the development set (gate-2 dates only);
- the test: the next untouched month-ends, under the gate-2b bars;
- the stop rule.

**Named candidates:**
1. Better section-D extraction.
2. Figures-to-numbers.
3. Another local model, with its knowledge cutoff probed first.

Before any design, the records are checked so the failed backbone design is not repeated.

## 8. Validation and audit (before SYSTEM is frozen)

| # | Check | Rule |
|---|---|---|
| V1 | w recovery | Synthetic panels with **shared date shocks and repeated companies**: a planted w ∈ {0, 0.3, 0.7, 1} is recovered within ±0.1. Under pure-noise deviations, w = 0 is adopted in at least 95% of 200 draws. |
| V2 | Calibration recovery | Synthetic PITs with a known miscalibration: after the map, coverage is 80% ± 3 and the interval score is not worse. The map is confirmed trained on the evaluated horizon. |
| V3 | Leakage (Audit 3) | An independent script, importing nothing from the fitting code, rebuilds the folds. It confirms that no held-out date's outcome enters the weight **or calibration** used for that date, that no gate-2b date or outcome is present, and that masked and repeat runs are excluded. It reproduces every w and out-of-fold statistic exactly. |
| V4 | Δ correctness | For 20 company-dates, `muse_k − code_k` is recomputed by hand from the saved positions and the v1 chain, to 1e-9. |
| V5 | Transport, in the real v2 | **Before the year-1 calibration map** (AK.21 erratum): with w = 0, the transported distribution equals V2 byte for byte in centres **and distributions** (common draws). The calibration step is tested separately: V2 here on synthetic data; on the real data, the identity map reproduces the transported distribution exactly, and a non-identity map changes year 1 only, never years 2–3. With nonzero w on 20 company-dates, the year-1 centre moves by exactly `w·Δ` and years 2–3 do not move. Forecast units are checked (growth and margin in fractions). |
| V6 | Freeze | The freeze records w per family × measure × horizon (years 2–3 = 0), the fallback rule, the calibration target and method with hashes, k, the red-team decision, the branch, and the engine and data hashes. `verify` reports no drift. |
| V7 | Horizon identity | For every claimed result, the forecast statistic, outcome statistic and calibration target are shown to be the same quantity and horizon (fiscal year 1), by a table generated from the code's own definitions. The q1 results are labelled as the breadth check with a shared mismatch. |
| V8 | Interactions | For 50 company-dates, the year-1 forecast with all Muse positions applied jointly is compared with the sum of the isolated measure deviations. The v1 chain is separable at year 1 (growth does not depend on margin inputs, and the margin does not depend on growth inputs), so the expected difference is 0. Any non-zero difference is reported by family and explained before freezing. |
| V9 | Δ diagnostics | The distribution of Δ and of `w·Δ` by family and measure (magnitude, sign, share at zero from fallbacks), and `c·Δ` beside it. |

Every number reported from the fit is reproduced by the V3 script before it is reported (Q4).

## 9. Approval record

**Outcome, by rule (AK.50, AK.52; operator 2026-10-14 20:18 KST: "go with A").** The eligible annual pairs are under 150 on every measure (143, 143, 49),
so **w = 0 throughout** and the calibration is the identity. SYSTEM is engine v2 alone. Muse still runs on gate 2b's dates and its positions are
recorded, unused, for a later, separately registered fit.

Approved by the operator on 2026-10-12 23:48 KST ("approve S5 v2"). Fixed from this point; cross-check 9 may still raise points, ruled on before the fit.
