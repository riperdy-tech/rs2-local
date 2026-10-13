# Verdict contract v4 — DRAFT, 2026-10-13 14:51: what the new analyst publishes, and how the existing chain reads it

Recovery plan S7; remaining-work plan C1. Written during gate-2 run 2, before any gate-2 outcome is read.

**Its basis:**
- the system map: DEP-07 (the band verdict and the Section 12 contract), DEP-07b (the fiduciary gate), DEP-09 (the ledger, gate on
  read and the overlay), TRK-01/02/03/06;
- `SPEC_engine_v2.md`, `SPEC_S5_muse_integration.md`, `REGISTRATION_selection.md`;
- the operator's decisions O2, O3 and O8 (Addendum AK).

**The goal.** Map the new core's output (a calibrated distribution of value per share, the year 1–3 forecasts, Muse's positions and
evidence) into the downstream contract with the least change. Every consumer keeps working, and nothing is invented to fill a field
the new core does not produce.

**The rule followed throughout:**
- a field with a faithful mapping is kept, with the same name and meaning;
- a field whose old source was the LLM report's self-assessment (conviction, moat, Kelly, scenario probabilities, re-entry tranches)
  has no honest source in v4, so it is **absent**, never synthesised;
- consumers branch on `scheme`.

## 1. Identity and versioning

| Field | Value | Note |
|---|---|---|
| `scheme` | `"core_v4"` | v1–v3 rows keep `"band_direction_v1"`. Consumers branch on it. |
| `gate_version` | `3` | `depth_gates` v4. Rows with `gate_version < 3` are read by the existing rules, unchanged. |
| `run_source` | as today | DEP-09 routing, unchanged. |
| `versions` | `{engine, near_term_vintage, priors_vintage, pack, templates, runner, calibration, model_sha256, llama_cpp_build, s5_freeze}` | Every one is required; a row missing any is `not_usable`. |
| `asof`, `price`, `price_date` | as today | |

## 2. Value and direction

| Field | Definition | Kept from v3? |
|---|---|---|
| `iv_quantiles` | `{p10, p25, p50, p75, p90}` of the **calibrated** value per share (S5 section 6; identity calibration when S5 adopted none) | new |
| `median_iv` | `iv_quantiles.p50` | kept (same meaning: the central value) |
| `base_iv` | `iv_quantiles.p50`. In v3 it was the medoid sample's own base case. v4 has one coherent distribution, so base and median coincide; both are kept so consumers need not change | kept (meaning narrowed, stated) |
| `iv_band_low`, `iv_band_high` | `p10`, `p90` | kept |
| `prob_value_above_price` | Pr(value per share > price) under the calibrated distribution | new |
| `expected_mos` | `(median_iv − price) / price` | new |
| `tv_share` | the terminal-value share of value, P50 | new |
| `direction` | **`undervalued`** iff price < `iv_band_low` **and** `expected_mos ≥ 0.10` (`MIN_MOS_FOR_DIRECTION`, D7). **`overvalued`** iff price > `iv_band_high` **and** `expected_mos ≤ −0.10`. Otherwise **`hold`**. | kept (the band rule on the calibrated P10–P90) |
| `m` | `(median_iv − price) / ((iv_band_high − iv_band_low)/2)`, `compute_m()`, unchanged | kept |
| `status` | `"ok"` or `"not_usable"` (direction null) | kept |
| `n_basis` | the number of model samples combined (S5 R8 k; 1 when not multi-sampled) | kept (meaning: samples combined) |

**Absent in v4, by the rule above:**
- `conviction`, `moat`;
- Kelly and its half-Kelly cap;
- `scenarios` with probabilities, and `payoff_skew`;
- the re-entry tranches;
- `coe_source` and the other LLM-declared Section 12 inputs.

The discount rate actually used is carried under `discount`, from the engine.

## 3. Size

`size_hint ∈ {quarter, half, full}` = the most conservative of these buckets (`_min_bucket`, unchanged; a `None` bucket is excluded,
never an extreme):

| Bucket | Rule | Status |
|---|---|---|
| `dispersion_bucket` | (P90 − P10) / P50 ≤ 0.40 full; ≤ 0.80 half; else quarter | **new thresholds**: calibrated bands are wider than v3's sample spread |
| `mos_bucket` | `expected_mos` ≥ 0.25 full; ≥ 0.10 half; else quarter | kept |
| `probability_bucket` | `prob_value_above_price` ≥ 0.90 full; ≥ 0.80 half; else quarter | new; replaces `conviction_bucket` |
| `risk_bucket` | the MRI turbulence flag read fresh; `None` with `risk_flag_unavailable` when unreadable | kept |

`size_components` publishes every bucket with its raw value.

**This size rule is provisional.** If S8 (`REGISTRATION_selection.md`) passes a sizing rule, that rule replaces it as a new version. It
is never changed on returns otherwise.

## 4. Entry timing (O3, adopted: deterministic, two axes)

`entry_timing ∈ {buy_now, wait_for_momentum, avoid}` and `momentum_view ∈ {confirming, neutral, contradicting}` are computed by code
from the value direction and the SCR-10 trend state at `asof`, never by a model:

| direction \ SCR-10 trend | up | flat | down |
|---|---|---|---|
| undervalued | `buy_now` / confirming | `buy_now` / neutral | `wait_for_momentum` / contradicting |
| hold | `avoid` / neutral | `avoid` / neutral | `avoid` / neutral |
| overvalued | `avoid` / contradicting | `avoid` / neutral | `avoid` / confirming |

- **`momentum_state`:** the exact SCR-10 numbers used are copied in.
- **`momentum_flip_condition`:** generated as the SCR-10 rule that turns the trend `up`, using the existing vocabulary.
- **`momentum_break_rule`:** generated as the rule that turns it `down`.
- **Grading:** every axis is graded by TRK-06, as today.

## 5. Watch items and invalidation rules (for DEP-13/14), generated by code

For each year-1 forecast the engine publishes (`forecast_years[1]`), one rule per measure, in the existing shape
`{metric, comparator, threshold, window_days, source}`:

- operating: `revenue_yoy_pct < 100 × growth.p10`, and `operating_margin_pct < 100 × margin.p10` (both on the next 10-Q, window 120 days,
  `source: "forecast_p10"`);
- financial: the ROTE equivalent, through `net_income` against `p10 × tbv`, declared `source: "forecast_p10"`;
- plus the momentum break rule (section 4), so the fiduciary requirement of at least one financial and one price/momentum checkable
  rule holds by construction;
- an input Muse placed outside P25–P75 with hard evidence gets a rule on the metric its evidence names, when that metric is in the
  vocabulary.

**Never selling.** A watch item never sells (memory `part2-followup-system`); it re-triggers analysis (DEP-13/14), as today.

## 6. Abstention ("no view", O2)

`abstention: {code, reason}` with `direction: null`, `status: "ok"`, `actionable: false`:

| `code` | When |
|---|---|
| `family_not_built` | commodity, REIT, utility, pre-profit, and BDC / market-structure financials without a priors cell (AJ.11) |
| `engine_refused` | the engine names a missing input, with its reasons copied |
| `no_share_count` | no value per share can be formed (the dual-class gap, AJ.2) until D3 fixes it |
| `no_quarterly_filings` | no 10-Q in the 12 months before `asof` (foreign private issuers) |

An abstention is published, so the site shows **"no view: <reason>"**. It is never silently absent.

## 7. Display-only consensus (O8)

`consensus_display: {source, asof, price_target_median, n_analysts, rating_mix, display_only: true}`.
- **What may read it:** the site desk only.
- **What may not:** `depth_gates`, sizing, the paper book, the follow-up and the grader.
- **Enforcement:** a contract test fails if any module except the site's display reads it.

## 8. Actionable reasons, gate on read (`depth_gates.assess` v4, `gate_version` 3)

`assess(v)` never mutates or drops a row and returns every applicable reason (non-negotiable 3). For `scheme == "core_v4"`:

| Reason | Rule (registered now) |
|---|---|
| `not_usable` | `status != "ok"`, or a required `versions` field is missing |
| `family_not_built` | `abstention` present |
| `integrity_fail` | any accepted citation fails the quote re-check (part-label errors excepted, AJ.5), or a leakage violation in the run |
| `unanchored_high` | more than half of the Muse-adjustable inputs unanchored |
| `implausible_level` | `median_iv / price` outside the family's P1–P99 of the same ratio over the engine-v2 code-only pass of the whole universe at `asof` |
| `extraordinary_without_evidence` | the reverse valuation flags an input as extraordinary (outside P5–P95) **and** that input has no hard evidence |
| `instability` | \|ΔP50 IV\| / prior P50 > 25% (`INSTABILITY_TOL_PCT`) against the previous verdict, with no new 10-Q/10-K/8-K between them |
| `stale_inputs` | fundamentals older than the filing calendar allows (the latest 10-Q/10-K expected but not ingested 10 days past its deadline); price older than 3 trading days; Damodaran older than 45 days; priors vintage not `year(asof) − 1` |
| `pre_valid_analyst` | `versions.s5_freeze` is not the freeze gate 2b promoted. Shadow-only rows are never actionable. |
| `non_production_row` | `run_source` not production (as today) |

**Not carried into v4:**
- `pre_v3.1_gates`, `single_sample` (replaced by R8's multi-sample rule inside the core), `fiduciary_fail` (section 9) and
  `kelly_on_overvalued` (no Kelly);
- `high_dispersion`: a calibrated band is honest uncertainty, not a malfunction. Direction already requires the price outside it, and
  size reads its width.

## 9. The fiduciary gate for v4 (DEP-07b rewritten for `core_v4`)

Kept and adapted:
1. **Monotonicity:** p10 ≤ p25 ≤ p50 ≤ p75 ≤ p90.
2. **Non-negative edge:** `undervalued` requires `prob_value_above_price > 0.5` and `expected_mos ≥ 0.10`; the mirror for `overvalued`.
3. **Checkable invalidation:** at least one financial and one price/momentum rule in the vocabulary (true by construction, still
   checked).
4. **Versions complete.**

Dropped with their fields: the probability simplex, the tranche monotonicity and the payoff-skew recalculation. A failure is
`not_usable`.

## 10. What each consumer must change

| Consumer | Change |
|---|---|
| rs2 `depth_gates.assess` | v4 branch (section 8); v3 rows unchanged |
| rs2 `fiduciary_gate` | v4 branch (section 9) |
| rs2 overlay writer (DEP-09/10) | carries the v4 fields; publishes only through `screener-publish` |
| screener `apply_llm_overlay` (SCR-04) | reads `direction`, `actionable`, `size_hint`, `m`, `entry_timing` as today. New fields are additive. Absent v3 fields (`conviction`, Kelly) handled as absent, not zero |
| TRK-03 `rn_depth` | unchanged predicate (undervalued and actionable) |
| TRK-06 grading | adds calibration grading of `prob_value_above_price` and coverage of `forecast_years` against realised fundamentals (D2/D3 tracking) |
| site desk | shows the quantiles, the probability, "no view: <reason>", and consensus marked display-only; drops conviction and moat for v4 rows |
| follow-up DEP-13/14 | reads the generated watch items (section 5), same shape |

## 11. Validation (before any consumer merges)

- **Contract tests in both repositories:** v4 fixture rows built from real gate-2 run-2 results (structure only, no outcomes) pass
  through every consumer in section 10. v3 rows still produce today's outputs byte for byte.
- **A single-owner table:** every field has exactly one producer (non-negotiable 5); a test fails on a field written by two modules.
- **Audit 4:** a field-by-field trace from engine result to site display on 5 fixture rows, checked by hand.
- **The O8 test:** no non-display module reads `consensus_display`.
- **Property tests:** the direction is always consistent with the band and the MoS floor; `size_hint` is always the minimum of the
  buckets; an abstention is never actionable.

## 12. Approval record

Not yet approved. It is for the operator, and part of cross-check 10.
