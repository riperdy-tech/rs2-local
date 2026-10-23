# Milestone 3H — Fail-closed producer-side-effect and source-freshness preflight

**Date:** 2026-10-24 KST. **Disposition:** ACTUAL source/preflight audited; **isolated fresh scorer run NOT PERMITTED from presently identified inputs**. This is a complete engineering reconnaissance checkpoint, not evidence of Qwen performance, validated AI risk detection, or accepted investment selection.

## 1. Task and non-destructive scope

The immediate goal was to establish whether the existing production Dual-Door scorer could be run separately and produce an authentic **fresh** owner-native PIT score/rank handoff without overwriting the publisher. The previous 3F/3G work had already recovered 161 *real* `fct_rank` values from compatible output and paired them with 161 **provisional** CIK associations. Those historic inputs remained stale and the generating process was not cryptographically attested.

We did **not** re-run `screener-publish/scripts/score_factors_dual_door.py`, refresh inputs, touch any publisher output, import its code, run Ollama/Qwen, order a broker trade, schedule a job or modify production CI. Files in `screener-publish` were read only.

The new isolated audit code is:

- `stocks-workspace/scratch/baselineA/m3h_scorer_preflight.py` — read-only AST scan for known output mutators and sensitive helpers; whole-file hashes and local modification-age checks of 11 essential input/output files; explicit top-level timestamp probes where present; fail-closed result. The report records `scorer_was_executed=false`, `model_release_blocked=true`, `can_run_in_place=false`, `can_run_isolated_fresh_producer_now=false`.
- `stocks-workspace/scratch/baselineA/m3h_test_scorer_preflight.py` — offline fixtures that verify no output creation, detection of direct writes and side-effect helpers, older/missing files, UTC timestamp handling and blocking even if artificially recent file modification times are supplied.

**Code source pinned by SHA256:** the inspected `screener-publish/scripts/score_factors_dual_door.py` was `501f47ef19dd0d3da8881010c47b493e615998cb1080829edde6af534e70a8cc`. This is a recorded source hash, not a signed generating-run identifier.

## 2. Actual producer execution hazards established from the code

| Site | Source | Why simply invoking the scorer is unsafe |
|---|---|---|
| `main()` previous book read | scorer lines 1297–1327 | Defaults to old `factor_scores.json`; determines `prev_rn`/`prev_book`/Door-3 membership for hysteresis, so a different previous snapshot can change selections |
| `sync_mri_snapshot()` | scorer line 1329; `scripts/mri_sync.py` lines 44–75 | Reads external MRI outputs, copies up to 5 files into this repository's `public/data/mri/`, overwrites the local MRI snapshot and writes `manifest.json` |
| MRI lookup | scorer lines 517–543 | `peer_paths.mri_outputs_dir()` can resolve a sibling checkout; a copied Python scorer is not isolated just because its output `DATA` path is changed |
| Dual-Door output | scorer line 2493 | Writes `public/data/factor_scores_dual_door.json` directly |
| Depth overlay use | scorer lines 962–1000, 2556 | Reads `depth_overlay.json`; overlay state must be pinned to the paper run, not drawn dynamically from an unrelated current source |
| Compatibility output | scorer line 2588 | Writes `public/data/factor_scores.json` directly — overwrites the hysteresis seed required for a repeatable run |

These are confirmed **static source behaviors** plus `mri_sync.py` source review, not a comprehensive tracing of side effects from every imported helper. A proper isolated execution must isolate the **repository-local data root and all owner-specific peer resolvers**, preserve the exact previous-book artifact, prohibit external write/network/broker access, and capture the source/input SHA256 before execution. Running in the original publisher worktree is prohibited for this paper experiment.

## 3. Actual current input inventory (read-only)

At local audit time **2026-10-23 16:55:00 UTC** (2026-10-24 01:55 KST), all **11 of 11** inspected essential publisher input/output artifacts had local filesystem last-modification ages exceeding **24 hours**.

- Approximately **185.55 hours** old: `stocks.json`, `price_history.json`, `momentum_state.json`, `eps_trajectory.json`, `tier1_hygiene_survivors.json`, `factor_scores.json`, `factor_scores_dual_door.json`, `mri/current_sector_ranking.json`, and `mri/cost_of_capital_anchor.json`.
- Approximately **210.39 hours** old: `fundamentals_history.json`, `fundamentals_battery.json`.
- The scored JSONs internally report `generated_at=2026-10-15T17:44:03Z`, confirming they are an **October 15 result**, not a fresh October 24 formation.
- `momentum_state.json` `price_asof`, MRI ranking `date` and capital anchor `asof` were **not full timezone-qualified timestamps** under the strict paper protocol; the preflight classed those as unproven exact-publication-time metadata. Other source roots were not assumed to have independently certified as-of acquisition dates.
- Local file **mtime is an audit hint, not a reliable publication/market-data availability attestation**. A file with a newly updated mtime can still contain old prices, delayed filings or outdated aliases. The tests explicitly reject treating recent mtime alone as eligibility.

This does **not** establish a remote publisher outage or prove that no newer files exist outside the checked local workspace. It is evidence that the inspected local source cannot qualify for the predeclared fresh, time-proven paper analysis gate.

## 4. Gate and verification

The actual tool emitted these block reasons:

1. `one_or_more_original_inputs_older_than_24h_or_missing`
2. `input_point_in_time_publication_unattested`
3. `mri_sync_copy_writes_snapshot_on_scorer_invocation`
4. `live_scorer_overwrites_dual_and_compat_score_outputs`
5. `previous_scores_influence_hysteresis`
6. `live_overlay_and_peer_resolution_requires_isolation`
7. `no_approved_isolated_owner_run_id`

Python 3.12 validation: 3H new preflight tests **9/9 passed**; entire existing 3A–3H scratch suite **148/148 passed**. Test fixtures are synthetic; they do **not** show that a real isolated scorer will run correctly.

## 5. Next controlled research run — not auto-executable now

**Prerequisites for a fresh non-deploying paper producer run:**

1. Receive or separately capture **fresh original source inputs** and document their publication/acquisition time in a versioned manifest. Confirm prices, annual filings, EPS data, MRI outputs, SEC sources and previous-book identity at the decision cutoff. An old input with a newly minted output `generated_at` remains stale.
2. Build an **isolated, non-deploying working copy** (not `screener-publish` and not `stock-screener` live paths), containing only the pinned source scripts/config and a *writeable copy* of the exact input bytes. Give the run a unique ID and hashes. MRI copy targets, `peer_paths`, previous score and overlay references must resolve **only** to approved paper source locations. Do not import live sibling repositories or modify their state.
3. Static and mocked run checks must fail if any write escapes the scratch root or if a helper reads an unpinned current source. Then run one resource-bounded offline score only after all time gates pass; compare both output files and freeze them with the existing 3F rank evidence format.
4. Independently confirm issuer effective dates and corporate-event truth (positive and negative controls) and get the **actual external design cross-check**, which is still pending. Only then consider prospective observation-only Qwen analysis. Underwriting valuation revision-26 holdout and the failed A1 factor strategy gate remain untouched.

**No live operations were changed. Qwen's incremental risk detection remains UNMEASURED.** Milestone 3H static preflight and safety gate **COMPLETE**; overall milestone 3 is **OPEN**.
