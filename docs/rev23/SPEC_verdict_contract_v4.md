# Verdict contract v4 — APPROVED (v2, 2026-10-13 17:45; joint-tail flag added 21:33): what the new analyst publishes, and how the existing chain reads it

Recovery plan S7; remaining-work plan C1. Written during gate-2 run 2, before any gate-2 outcome is read.

**Revision v2 (SPEC_rebuild AK.19, after the ChatGPT and Gemini reviews of cross-check 9):**
- the survival adjustment is defined as a mixture, and `prob_fail_12m` and the distress model version are published (section 2a);
- the value distribution is labelled model-implied, because no calibration of value per share is claimed (section 2b);
- `expected_mos` is renamed `median_mos`, and `mean_iv` and `mean_mos` are added, each with its users named;
- section 8 keeps the specific abstention code as the reason;
- TRK-06 grades only observable quantities.

**Its basis:**
- the system map: DEP-07 (the band verdict and the Section 12 contract), DEP-07b (the fiduciary gate), DEP-09 (the ledger, gate on
  read and the overlay), TRK-01/02/03/06;
- `SPEC_engine_v2.md`, `SPEC_S5_muse_integration.md`, `REGISTRATION_selection.md`;
- the operator's decisions O2, O3 and O8 (Addendum AK).

**The goal.** Map the new core's output (a model-implied distribution of value per share, section 2b; the year 1–3 forecasts, Muse's positions and
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
| `gate_version` | `9` | `depth_gates` v4 (erratum AK.54, 2026-10-14 21:30: the draft said 3, but the live `GATE_VERSION` is already 8). Consumers branch on `scheme`; rows that are not `core_v4` are read by the existing rules, unchanged. |
| `run_source` | as today | DEP-09 routing, unchanged. |
| `versions` | `{engine, near_term_vintage, priors_vintage, pack, templates, runner, calibration, distress_model, model_sha256, llama_cpp_build, s5_freeze}` | Every one is required; a row missing any is `not_usable`. `distress_model` names the P(fail) model in force (B5: `C0` until a candidate is selected) with its hash. |
| `asof`, `price`, `price_date` | as today | |

## 2. Value and direction

| Field | Definition | Kept from v3? |
|---|---|---|
| `iv_quantiles` | `{p10, p25, p50, p75, p90}` of the **survival-adjusted** value per share (section 2a) | new |
| `iv_quantiles_going_concern` | the same quantiles of the going-concern distribution, before the survival adjustment (section 2a) | new |
| `median_iv` | `iv_quantiles.p50` | kept (same meaning: the central value) |
| `base_iv` | `iv_quantiles.p50`. In v3 it was the medoid sample's own base case. v4 has one coherent distribution, so base and median coincide; both are kept so consumers need not change | kept (meaning narrowed, stated) |
| `mean_iv` | the mean of the survival-adjusted distribution = `(1 − prob_fail_12m) × mean(going-concern draws)`. The existing distress formula, value = mean IV × P(survive 12 months), unchanged | new |
| `iv_band_low`, `iv_band_high` | `p10`, `p90` | kept |
| `prob_fail_12m` | P(distress exit within 12 months) from the distress model in force (`versions.distress_model`; B5 section 7). In [0, 1] | new |
| `prob_value_above_price` | Pr(value per share > price) under the survival-adjusted distribution = `(1 − prob_fail_12m) × Pr(going-concern value > price)`. **Model-implied** (section 2b) | new |
| `median_mos` | `(median_iv − price) / price` (named for what it is: a median, not an expectation) | new |
| `mean_mos` | `(mean_iv − price) / price` | new |
| `tv_share` | the terminal-value share of value, P50 | new |
| `direction` | **`undervalued`** iff price < `iv_band_low` **and** `median_mos ≥ 0.10` (`MIN_MOS_FOR_DIRECTION`, D7). **`overvalued`** iff price > `iv_band_high` **and** `median_mos ≤ −0.10`. Otherwise **`hold`**. | kept (the band rule on the survival-adjusted P10–P90) |
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

**Which measure each consumer uses** (one reading, everywhere):

| Use | Measure |
|---|---|
| `direction`, `mos_bucket`, the fiduciary edge check | `median_mos` and the survival-adjusted P10/P90 |
| `probability_bucket` | `prob_value_above_price` (survival-adjusted) |
| H-S1 in `REGISTRATION_selection.md` ("log(expected IV ÷ price)") | `log(mean_iv / price)`: the survival-adjusted mean. The mean keeps the ranking signal that the median loses (Addendum V); this amendment to the selection registration is made before any selection data exist and is for the operator (AK.19) |
| `m` | `median_iv` and the band, `compute_m()` unchanged |

### 2a. The survival adjustment, as a distribution

The engine produces N going-concern draws of value per share, `V_1 … V_N`: engine v2, the S5 transport, and the S5 year-1
calibration when it was adopted. With `p = prob_fail_12m` and equity recovery 0 on failure (Stage 2 V2, unchanged), the published
distribution is the **mixture**: value 0 with probability p, and the going-concern distribution with probability 1 − p.
- **Quantile at level q:** 0 if q ≤ p; otherwise the going-concern quantile at level (q − p) / (1 − p).
- **Mean:** `(1 − p) × mean(V)`, which is exactly the existing formula; B5's "value = mean IV × P(survive)" is this mean.
- **Not done:** multiplying every draw by 1 − p. That matches the mean but describes a different distribution, with no mass at 0.
- **Its consequences, stated:**
  - with p ≥ 0.10, `iv_band_low` is 0, so the name cannot be `undervalued`;
  - with p ≥ 0.50, `median_iv` is 0.
  That is the intended reading of a 10% chance that the equity is worth nothing. Section 11 reports how many fixture rows change
  direction because of it.
- **The horizon limit, stated:** p covers 12 months only. Failure after month 12 sits inside the going-concern draws. B5 reports a
  36-month diagnostic. A longer horizon is a later version, never a drive-by change.

### 2b. What is and is not calibrated

Value per share is not observable, so no calibration of the value distribution is claimed. The year-1 calibration of S5 section 6 does
not carry through the engine's long-run chain and the copula to the value distribution, and this contract does not say it does.
- **Claimed and tested:**
  - year-1 forecast quantiles, `forecast_years[1]` (S5 section 6; tested by gate 2b's B4);
  - `prob_fail_12m` (B5; graded by TRK-06 against realised exits).
- **Model-implied:**
  - `iv_quantiles`, `prob_value_above_price`, `median_mos`, `mean_mos`, `direction`;
  - each row carries `value_distribution: "model_implied"`;
  - their only observable test is returns, through `REGISTRATION_selection.md` (S8). They are never called calibrated.

## 3. Size

`size_hint ∈ {quarter, half, full}` = the most conservative of these buckets (`_min_bucket`, unchanged; a `None` bucket is excluded,
never an extreme):

| Bucket | Rule | Status |
|---|---|---|
| `dispersion_bucket` | (P90 − P10) / P50 of `iv_quantiles_going_concern` ≤ 0.40 full; ≤ 0.80 half; else quarter (going concern, because the mixture's P50 can be 0; distress enters through `probability_bucket`) | **new thresholds**: v4's residual-based bands are wider than v3's sample spread |
| `mos_bucket` | `median_mos` ≥ 0.25 full; ≥ 0.10 half; else quarter | kept |
| `probability_bucket` | `prob_value_above_price` ≥ 0.90 full; ≥ 0.80 half; else quarter | new; replaces `conviction_bucket` |
| `risk_bucket` | the MRI turbulence flag read fresh; `None` with `risk_flag_unavailable` when unreadable | kept |

`size_components` publishes every bucket with its raw value: keys `dispersion_bucket`, `mos_bucket`, `probability_bucket` and `risk_bucket`, each
`{"bucket": quarter|half|full|null, "value": <raw value or null>}` (fixed in AK.54, 2026-10-14 21:30).

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

## 8. Actionable reasons, gate on read (`depth_gates.assess` v4, `gate_version` 9; erratum AK.54)

`assess(v)` never mutates or drops a row and returns every applicable reason (non-negotiable 3). For `scheme == "core_v4"`:

| Reason | Rule (registered now) |
|---|---|
| `not_usable` | `status != "ok"`, or a required `versions` field is missing |
| the abstention's own code (`family_not_built`, `engine_refused`, `no_share_count`, `no_quarterly_filings`) | `abstention` present: the reason is `abstention.code`, never a fixed label, so a refused engine input is never reported as an unbuilt family |
| `integrity_fail` | any accepted citation fails the quote re-check (part-label errors excepted, AJ.5), or a leakage violation in the run |
| `unanchored_high` | more than half of the Muse-adjustable inputs unanchored |
| `implausible_level` | `median_iv / price` outside the family's P1–P99 of the same ratio over the engine-v2 code-only pass of the whole universe at `asof` |
| `extraordinary_without_evidence` | the reverse valuation flags an input as extraordinary (outside P5–P95) **and** that input has no hard evidence |
| `instability` | \|ΔP50 IV\| / prior P50 > 25% (`INSTABILITY_TOL_PCT`) against the previous verdict, with no new 10-Q/10-K/8-K between them |
| `stale_inputs` | fundamentals older than the filing calendar allows (the latest 10-Q/10-K expected but not ingested 10 days past its deadline); price older than 3 trading days; Damodaran older than 45 days; priors vintage not `year(asof) − 1` |
| `pre_valid_analyst` | `versions.s5_freeze` is not the freeze gate 2b promoted. Shadow-only rows are never actionable. |
| `non_production_row` | `run_source` not production (as today) |

**Flags that annotate and never block** (published in `flags`, shown on the site):
- `distress_model_not_validated`: the distress model in force has not passed B5's fresh-date bars (C0 included);
- `value_distribution_model_implied`: on every v4 row (section 2b);
- `joint_tail_undercoverage`: on every row whose `versions.engine` uses engine v2.0's Gaussian copula. AK.20's D-T1 measured revenue
  and margin falling together 1.6–1.9 times as often as that copula draws, so P10 sits too high and `undervalued` is too easy. The flag
  stays until a copula version passes its own registration (v2.1). It is versioned with the engine and named in the release record.

**Not carried into v4:**
- `pre_v3.1_gates`, `single_sample` (replaced by R8's multi-sample rule inside the core), `fiduciary_fail` (section 9) and
  `kelly_on_overvalued` (no Kelly);
- `high_dispersion`: the v4 band is the model's stated uncertainty, not a malfunction. Direction already requires the price outside it, and
  size reads its width.

## 9. The fiduciary gate for v4 (DEP-07b rewritten for `core_v4`)

Kept and adapted:
1. **Monotonicity:** p10 ≤ p25 ≤ p50 ≤ p75 ≤ p90.
2. **Non-negative edge:** `undervalued` requires `prob_value_above_price > 0.5` and `median_mos ≥ 0.10`; the mirror for `overvalued`.
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
| TRK-06 grading | adds only observable grades: coverage of `forecast_years` against realised fundamentals (D2/D3 tracking), and calibration of `prob_fail_12m` against realised distress exits. `prob_value_above_price` is not graded as a calibration (section 2b); its test is S8's return evaluation |
| site desk | shows the quantiles, the probability, "no view: <reason>", and consensus marked display-only; drops conviction and moat for v4 rows |
| follow-up DEP-13/14 | reads the generated watch items (section 5), same shape |

## 11. Validation (before any consumer merges)

- **Contract tests in both repositories:** v4 fixture rows built from real gate-2 run-2 results (structure only, no outcomes) pass
  through every consumer in section 10. v3 rows still produce today's outputs byte for byte.
- **A single-owner table:** every field has exactly one producer (non-negotiable 5); a test fails on a field written by two modules.
- **Audit 4:** a field-by-field trace from engine result to site display on 5 fixture rows, checked by hand.
- **The O8 test:** no non-display module reads `consensus_display`.
- **Property tests:** the direction is always consistent with the band and the MoS floor; `size_hint` is always the minimum of the
  buckets; an abstention is never actionable; each of the four abstention codes comes back from `assess` as its own reason.
- **The mixture (section 2a), against an independent script that imports nothing from the producer:** on random p and draws, the
  quantiles equal the stated formula, `mean_iv = (1 − p) × mean(V)`, `prob_value_above_price = (1 − p) × Pr(V > price)`, and p = 0
  reproduces the going-concern quantiles exactly.
- **Reported on the fixture universe (no outcomes):** the distribution of `prob_fail_12m` under C0, and how many rows change direction
  or size because of the survival adjustment, so its effect is seen before any consumer merges.

## 12. Approval record

**Approved by the operator, 2026-10-13 21:50 KST:** "approve C1, B5, S5, mean_iv, and the engine v2 bundle" (SPEC_rebuild AK.23). The version approved is draft v2 with the AK.21 `joint_tail_undercoverage`
flag. Any change from here on is a new version. Cross-check 10 reviews the downstream changes (plan C2).

## 13. Errata

These are binding where they differ from the sections above. Each is recorded in SPEC_rebuild.

- **AK.54:**
  - `gate_version` is 9;
  - the `size_components` keys are fixed (section 3).
- **AK.55, 3: versions for SYSTEM = engine v2 alone.**
  - `pack`, `templates`, `model_sha256` and `llama_cpp_build` are `"not_applicable"`, allowed only when `muse_used` is false;
  - `s5_freeze` is `"w0_AK52"` and `calibration` is `"identity_AK52"`;
  - the new key `system_freeze` holds the engine freeze's identifier;
  - `pre_valid_analyst` compares `versions.system_freeze` with the freeze gate 2b promotes.
- **AK.55, 4: the trend state from SCR-10** (`momentum_state.json` as filed):
  - **down** if `mom_break`;
  - **up** if `above_200dma` and `dma200_slope_20d` > 0;
  - **flat** otherwise;
  - **unknown** if a field is absent: the trend-dependent axes are then null, and stated.

  `momentum_break_rule` is the `mom_break` condition and `momentum_flip_condition` the "up" condition, both with `window_days` 20.
- **AK.55, 5: invalidation rules** carry `window`, the phrase the consumers read, plus a numeric `window_days`. Momentum rules keep
  `window_days`.
- **AK.55, 6: the single-owner table** adds `run_id`, `cik`, `ticker`, `family`, `stale_inputs`, `notes`, `reasons`, `forecast_years`,
  `discount`, `muse_used` and `system_freeze`. The live runner is their only producer.
- **AK.55: an `unclassifiable` company** is a no-view: `family_not_built`, with reason "unclassifiable".
- **AK.59 (2026-10-14 21:58): field ownership between the live runner (producer) and the gate.**
  - **`flags` (producer)** holds the properties of the method: `value_distribution_model_implied`, `joint_tail_undercoverage`,
    `continuation_binary_interim` and `distress_model_not_validated`. The gate never overwrites them; **`gate_flags` (gate)** holds what
    the gate derives.
  - **`actionable` belongs to the gate alone.** The producer never writes it, abstentions included.
  - **Gate inputs, which the producer emits** (the names are the gate's):
    - `integrity` and `muse`, **not applicable** when `muse_used` is false;
    - `level_reference` `{family, p01, p99, n, asof}` (key names corrected to the gate's, AK.60), the P1 and P99 of `median_iv / price` over the engine-v2 pass of the whole universe
      at that `asof`. A run over a subset reads the last universe pass of the same `asof`; without one, the row is blocked, failing closed;
    - `prior_verdict`, which the gate reads from the ledger.
  - **`system_freeze`** sits in `versions` only.
  - **Momentum rules** carry both `window_days` (20) and `window` ("20 trading days").
  - **The producer runs `validate_fiduciary_contract_v4`** and marks a failure `not_usable`. `assess` reads that result.
  - **The overlay header,** when v4 rows are present: `"scheme": "mixed"` with each row's own `scheme`, and `gate_version` 9.
  - **The producer also emits `date`** (equal to `asof`) for the grader's key.
  - **TRK-06's realised values:**
    - revenue growth and margin come from `rebuild_harness/gate2/same_filing.annual_measures`, the outcome definition of record;
    - ROTE comes from `build_state`;
    - tangible-book growth is **unavailable** until a same-filing rule exists;
    - `prob_fail_12m` grading is **unavailable** until the event index records the date it is resolved through, which D5's refresh adds.
- **AK.60 (2026-10-14 22:02): corrections to AK.59.**
  - **`level_reference`'s keys are `p01` and `p99`**, the names the gate already reads. AK.59 wrote `p1`, which was my error.
  - **`prior_verdict` is emitted by the producer, not read by the gate.** Only the producer holds the filing dates that
    `new_filing_between` needs. Its shape is `{median_iv, asof, new_filing_between}`, built from the producer's previous v4 row for the
    company:
    - explicit `null` on the first verdict;
    - when the key is absent, `instability` applies, which fails closed (as the gate does now).
- **AK.65 (2026-10-14 22:42): additions to the single-owner table**, with the live runner as the only producer: `momentum_state`,
  `momentum_break_rule`, `momentum_flip_condition`, `continuation_at_median`, `fiduciary_v4`, `prior_verdict`, `level_reference`, `date`,
  `integrity` and `muse` (the last two not applicable while `muse_used` is false).
  - **The flip condition** (`momentum_flip_condition`, an AND of three terms) is an **entry-timing** condition, not an invalidation rule.
    The checkable momentum watch item is `mom_break`, a single rule.
  - **SCR-10 freshness:** a `momentum_state.json` built after the row's date is never read. One built more than **3 weekdays** before the
    date gives trend "unknown" with the reason "stale".
- **AK.75 (2026-10-15 04:31): additions to the single-owner table** (producer: the live runner).
  - **`classification_source`:** one of `as_filed`, `current_at_asof`, `current_dated_file` or `no_sic`, or null for a row refused before
    classification.
  - **`stale_inputs`** adds "price: last close <date>, <n> weekdays old" for a company's own close more than 3 weekdays old.
  - **In the shadow's `submissions_read` mode,** the facts are fresh when the company's SEC record was read within 2 days and SEC lists no
    10-Q or 10-K filed after the store's latest filing for it.
