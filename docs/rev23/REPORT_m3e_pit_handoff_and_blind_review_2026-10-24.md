# Milestone 3E — PIT handoff preflight and blind event-review contract

**Date:** 2026-10-24 KST · **Verdict:** Mechanical handoff/reviewer controls implemented, **real prospective cohort and independently adjudicated event truth remain BLOCKED**. All changes are scratch/docs only. No screener deployment, live scoring, real trading, GPU inference or automatic AI role promotion.

## 1. Inputs and decision

The current `screener-publish/public/data/factor_scores_dual_door.json` generated **2026-10-15T17:44:03Z** reports **161** `nominated_tickers` and matching 161 per-name profiles, but **none contain a `cik` field or numeric global `rank`**. Earlier milestone 3D located a `2026-06-10` ticker/CIK map that provisionally joins 161 symbols to 160 CIKs (SENEA/SENEB share issuer `0000088948`). Its existence **does not prove the issuer aliases are valid at a later decision time**, nor supply the missing numeric rank.

**Decision:** require two separately versioned, source-bound artifacts before even classifying a cohort as structurally ready for **human** review. Do not derive a global rank from Door percentiles, do not infer a missing CIK from today's ticker, do not collapse share classes, and do not retroactively modify frozen 3C/3D receipts.

## 2. Implemented proposed paper-only artifact contracts

Implementation is `stocks-workspace/scratch/baselineA/m3e_pit_handoff.py`, with deterministic tests `m3e_test_pit_handoff.py`.

1. **Original screener artifact:** full matching `nominated_tickers`/`profiles` and `nominated_count`, `generated_at` before T; 24-hour freshness criterion (operational safety metadata only); raw score SHA256 pinned. Same completeness principle applies to a later *held* cohort handoff, but this code currently audits nominations only.
2. **Issuer alias artifact**, `schema=paper-pit-issuer-alias-v1`, `source_owner=pit_issuer_alias_registry`, SHA256 of the exact scored artifact, `observed_utc <= T`, *one record per nominated symbol*, explicit 10-digit issuer CIK or missing reason, source-kind and SHA256, and symbol alias effective-from/effective-until coverage of decision T. All records are retained even when invalid. This is a **proposed contract**, not a live producer output.
3. **Global rank artifact**, `schema=paper-pit-global-rank-v1`, `source_owner=screener_rank_producer`, SHA256 of exact score artifact, `generated_utc <= T`, one integer `global_rank >= 1` per candidate and per-row source-score binding. The producer must document whether it is universe, Door-specific or shortlist rank before a paper selection algorithm consumes it; this verifier does not infer semantics from percentile fields.
4. **Audit result**, `schema=m3e-paper-pit-handoff-audit-v1`, preserves each symbol, candidate CIK, rank, missing reasons, input hashes and UTC times, `complete_structural_rows`, `block_reasons`, `structural_review_ready`, plus always `time_proven_identity_verified=false`, `independent_ground_truth_ready=false`, `model_release_blocked=true`, `paper_trade_action=null`. Even structurally complete *synthetic* sources are **not** independently proven true: assertions of source ownership and alias validity inside a JSON object are not external attestations.

### Actual read-only original-source preflight
The real publisher artifact was inspected on 2026-10-24 (KST; actual invocation stamped in emitted output). Read-only audit returned:

| Metric | Actual |
|---|---:|
| Full nominated cohort | **161** |
| Original score SHA256 | `ed9c8c515429b08cd3d3b8586c1ab6048cdaa55358aa7b488ff505b3f0170e99` |
| Records with a supplied authoritative rank artifact | **0** |
| Records with a supplied authoritative issuer alias artifact | **0** |
| Structurally complete for human review | **0** |
| Block reasons | `stale_score_generated_over_24h`, `missing_versioned_alias_artifact`, `missing_original_rank_artifact`, `per_candidate_missing_or_unverified` |
| Model-ready, deploy-ready, risk-verdict-ready | **NO** |

The 161/161 *provisional* June-map associations from 3D remain available **in the separate source-audited record**, not promoted into PIT-verified handoff. The current test deliberately does not inject or backfill them.

## 3. Independent truth-review control implementation

`m3e_blind_truth.py` / `m3e_test_blind_truth.py` provide a **paper-only reviewer opinion comparator**, not the human review itself.

- A case must have a stable id, timezone-qualified decision time, registered event family, explicit source-evidence inventory, event coverage state, and `model_predictions_available=false`.
- Two separate reviewer ids, blind-review declarations, full timezone-qualified reviewed times, matching case ids, and source references selected from the registered evidence list are required to construct a two-opinion comparison. Unsupported critical-event claims with no source are rejected.
- An apparent `non_event` requires `complete_audited` source coverage **and** a separately claimed signed negative-coverage audit. Partial or missing records cannot produce a clean negative.
- Two differing opinions yield `disputed_needs_third_review`. Agreement yields only `dual_opinion_agrees_NOT_ground_truth` and a `provisional_agreement_label`. Because reviewer identifiers, independence, signatures and source completeness are not independently cryptographically proven here, **both verified event and verified negative counters remain exactly ZERO**, even if both inputs claim `confirmed_critical` or `non_event`.
- Neither raw filing category, two JSON reviewer entries nor this comparator creates a model veto, paper position change, forced sale, or production signal.

### Real sealed filing smoke
A previously sealed Apple 8-K (accession `0000320193-26-000018`; locally acquired **2026-10-24 01:13 KST**) was passed **only as an unreviewed test case**, not a nominated-cohort case or positive finding. Output:
`review_state=pending_independent_review`, `verified_event_opportunity_count=0`, `verified_negative_control_count=0`, `model_release_blocked=true`.
The source body was NOT claimed as a verified risk event; its historical availability for any 2025 decision remains false.

## 4. Schema correction revealed by real source

In `SCHEMA_m3b_event_truth_2026-10-24.md`, changed the stable case key to **`(formation_utc, symbol_asof, issuer_cik, role)`** instead of `(formation_utc, issuer_cik, role)`. Without `symbol_asof`, SENEA and SENEB would have identical keys despite being separate traded security classes. This is a minimal *paper registry contract* correction only, not a change to deployed issuer identity or issuer-level event aggregation.

## 5. Tests and what remains unverified

- New **15/15** PIT handoff tests and **16/16** blind reviewer-opinion tests passed with Python 3.12, including missing source/rank, future times, invalid zero rank, share classes, hash mismatches, duplicate rows, reviewer disagreement, attempted source-free event positives, incomplete-coverage negative controls and model-contaminated truth input.
- Full milestone-3 scratch test suite **114/114 passed**, combining 3A + 3B + 3C + 3D + 3E. Python syntax checked on both new modules and tests.
- **Not tested:** true independently authenticated identity, the real production rank export, real adjudicator independence, source-complete negative events, independent event enumeration, risk-prediction recall/precision, prospective performance, exchange halts, Qwen GPU or live orders.
- External `CROSS_CHECK_26_strategy_after_baseline_A.md` still awaits an **independent review**. This internal analysis is *not* a substitute.

## 6. Next safe milestone boundary

1. An authoritative screener rank producer / alias owner must agree on real PIT rank semantics and a complete, time-stamped export contract. Do **not** change the live screener or publisher from this scratch test; build a separate isolated producer branch only after reviewing deployment impact.
2. Start a *fresh* end-to-end paper cohort: original scores generated within 24 hours of T, complete candidate or held list, actual documented alias observations and individually captured SEC/exchange source receipts with publication/acquisition times before T. Current publisher score remains stale and thus blocked.
3. Form independent, blind positive **and negative** real-event opportunities from that cohort; sign/source-audit the underlying completeness and conduct two reviewer adjudications. A model-alert-only selection cannot be the universe of truth. Unavailable evidence must be counted as unknown.
4. Obtain actual external cross-check and operator review. Only then consider a **single resource-capped, observation-only** Qwen trial. No automatic buy pause, sale, AI override or capital allocation.
5. A1 turnover gate remains failed (1.6311 > 1.60), revision-26 holdout and D2 undecided remain untouched. `KIS_HALT` and `DEPTH_PAUSED` are not changed.

**Milestone 3E implementation and mechanical testing COMPLETE; full milestone 3's source completeness, independent ground truth and Qwen outcome measurement are still OPEN.**
