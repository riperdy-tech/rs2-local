# Milestone 3K — Scratch-only scorer staging contract, fail-closed inputs and no executable launch

**2026-10-24 KST. Status: contract BUILT AND UNIT-TESTED, real producer runtime NOT PREPARED OR EXECUTED.** This milestone checks paper staging declarations and explicitly does **not** authorize a container, score run, Qwen GPU, brokerage access, order, or deployment.

## 1. What existed before 3K

- 3I identified eight actual imported local Python modules and six heuristic file-I/O call sites.
- 3J confirmed **one harmless Docker smoke test** with root/code filesystem read-only, TCP disconnected and no privileges. That smoke was not a production scorer confinement test.
- 3H found the publisher input/output artifacts stale and lacking independently authenticated first-hand as-of time evidence; 3F/3G preserved 161 numeric ranks and 161 provisional CIK aliases from **2026-10-15**, not a fresh current formation.

Therefore generating or executing a score run now would confuse a contemporary output timestamp with old source information.

## 2. Implemented fail-closed paper staging validator

Files created only under `stocks-workspace/scratch/baselineA/`:

- `m3k_staging_gate.py`: defines a fixed **25-file** scratch-only input contract (8 imported local scorer modules; 11 3H original publisher input/output files; the `depth_overlay.json`, remaining MRI state and manifest, and `sifter_config.json`). It checks the exact set of named files, absolute scratch-root confinement, per-file original SHA256, on-disk file completeness, duplicate/unlisted files and even unexpected directories, Windows reparse/symlink components, hardlinks, registered UTC publication/acquisition and hashes of declared first-hand receipt artifacts, cutoff chronology, and local import closure. An untrusted environment-variable override is rejected.
- `m3k_test_staging_gate.py`: synthetic, offline unit fixtures for complete/missing inputs, future and old timestamps, mismatched hashes, invalid paths, hidden extra inputs/directories, hardlinked files, bad environment, incomplete dependency graph and preserved `model_release_blocked=true`.

The declaration format is `m3k-paper-stage-v1`. A theoretical **structural pass is not an execution permit**: it still sets `producer_run_approved=false`, `scorer_executed=false`, `model_release_blocked=true`, and returns a **descriptive Docker policy only**, not an executable command or launch arguments. Original acquisition/source timestamps inside a supplied manifest are **not independently certified** merely because their syntax and order pass.

The fixed list includes compatibility `factor_scores.json` because it affects hysteresis and future holdings. It also includes the MRI local snapshot and manifest because source-relative peer path resolution may otherwise change outcomes.

## 3. Actual repository preflight (read-only)

Invoked only:
`python m3k_staging_gate.py screener-publish`

Actual response:
- Eight imported local modules were available to inspect.
- **11 / 11** essential 3H publisher files were missing freshness within 24 hours based on local modification timestamps (not an independent timestamp attestation).
- **9 / 11** had no usable time-qualified provenance claim at the audited root fields.
- Unsafe operations remained blocked: scorer overwrites two outputs, MRI copies/writes files, past compatibility scores influence hysteresis, imported peer references and overlays are not pinned, no original owner-run ID or verified source-time inventory.
- `paper_stage_prepared=false`, `docker_invocation_generated=false`, `scorer_executed=false`, `model_release_blocked=true`.

This audit **does not prove that a remote publisher or another machine has no fresh sources**, only that the inspected local tree cannot be used for a new defensible paper formation.

## 4. Actual test results, including an unverified Windows test

The new staging tests total **17**:
- **16 passed** on the actual Windows machine.
- **1 skipped:** Windows could not create a test symlink using the current user's privileges. Link-denial logic was examined by source and other path/hardlink tests passed, but the actual symlink negative-control could **not** be observed.
- During first test run, a missing input was incorrectly classified as a reparse-link error. This was corrected to classify absent files before link checks; tests then passed.
- A second refinement rejects unexpected **empty directories**, not only unexpected files.

Whole isolated milestone-3 scratch suite (3A through 3K): **191 total**, **190 passing and 1 skipped**, zero failing after corrections. Synthetic tests are NOT evidence of a real production scorer sandbox or model-quality validation.

## 5. Remaining real blockers and next work

1. Existing `screener-publish` inputs need an independent, contemporaneous source-capture chain. A source hash and filesystem `mtime` cannot prove price, filing or issuer data was known by decision T.
2. A research-only copied input bundle may be audited under scratch, but **a structurally valid JSON manifest still requires external source attestation and trusted human review**. Do not produce Docker invocation strings or begin a scorer run from this code.
3. A future real scorer run would require a verified OS boundary *with actual scorer imports*, pinned MRI and previous-score/overlay sources, plus no access to production trees, host Docker socket, broker secrets or external network. The single synthetic Docker smoke from 3J does not meet that criterion.
4. Independent event-positive and eligible event-negative ground truth, issuer effective-date attestation, two blinded adjudicators and actual external strategy design cross-check remain pending. The Qwen monitoring benefit is **unmeasured**.
5. No 3A threshold retuning: preregistered A1 turnover was **1.6311x** vs **≤1.60x**, and historical delisting bounds remain invalid. Frozen valuation holdout remains untouched.
6. `KIS_HALT`, `DEPTH_PAUSED`, production screener, `rs2-local`, deployment and CI were not edited, and no trading/AI activity was initiated.

**Disposition: Milestone 3K staging CONTRACT validation complete, but fresh PIT source cohort, operator-reviewed runtime permission and full milestone-3 Qwen effect evaluation remain OPEN.**
