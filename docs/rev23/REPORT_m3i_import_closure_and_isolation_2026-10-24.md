# Milestone 3I — Producer dependency closure, source I/O sites and isolation boundaries

**Date:** 2026-10-24 KST · **Disposition:** read-only import dependency analysis and auditable static graph **complete**; a runtime-sandboxed, current-input screener run **NOT attempted or approved**. Qwen benefit and risk detection performance remain **unmeasured**.

## 1. Why this check was necessary

3H showed the real publisher scorer overwrites `factor_scores_dual_door.json` and `factor_scores.json`, reuses previous ranks for hysteresis, reads a depth overlay and invokes `sync_mri_snapshot()`, which copies current MRI data into the publisher's `public/data/mri/`. Merely copying the scorer file to a different directory would not guarantee isolation; its imported modules and `peer_paths` resolver may have other effects.

The 11 publisher input/output artifacts in 3H were about 185–210 hours old on 2026-10-24. **No reliable current PIT source appeared in that audit.** 3I therefore did not rerun the live scorer, fetch new prices or write an ungrounded `generated_at` timestamp.

## 2. Actual recursively audited module graph

New scratch-only `stocks-workspace/scratch/baselineA/m3i_dependency_gate.py` parses the original scorer and recursively follows local `scripts/*.py` imports **without importing, executing, or modifying production modules**. The inspected local closure has **8 modules**:

`score_factors_dual_door`, `mri_sync`, `peer_paths`, `tradability`, `depth_conviction`, `momentum_math`, `hygiene_thresholds`, `industry_taxonomy`.

The AST scan records per-module original code SHA256, byte length, local/standard library import names, possible file/network/subprocess calls, and dynamic/relative import warnings. All four expected local helpers (`mri_sync`, `peer_paths`, `tradability`, `depth_conviction`) were reached; this does **not** prove that other imported libraries or dynamically computed paths are safe.

The **final refined static scan found 6 possible I/O call sites**, including one read, and **5 direct filesystem modification candidates**:

| Original file | Approx. source line | Static call | Consequence |
|---|---:|---|---|
| `mri_sync.py` | 55 | `SNAPSHOT_DIR.mkdir` | Can create local MRI directory |
| `mri_sync.py` | 62 | `shutil.copyfile` | Can copy externally resolved MRI outputs into local snapshot |
| `mri_sync.py` | 74 | `MANIFEST_JSON.write_text` | Writes MRI snapshot manifest |
| `score_factors_dual_door.py` | 105 | `path.open` | Reads local file |
| `score_factors_dual_door.py` | 2493 | `OUT_JSON.write_text` | Overwrites Dual-Door output |
| `score_factors_dual_door.py` | 2588 | `FACTOR_SCORES_COMPAT_JSON.write_text` | Overwrites compatibility output, altering future hysteresis seed |

**Accuracy correction made during 3I:** the first AST draft counted ordinary dict `.get()` calls as possible network I/O, reporting **345** false-inflated sites; the second draft still included `str.replace()` and `datetime.replace()`, reporting **9**. Both earlier diagnostic records remain as historical, sealed artifacts only. The corrected classifier excludes regular `.get()`, non-filesystem `.replace()`, while recording qualified `requests.get` and known file-path replacement patterns. Its final count is **6**; this count remains a **static heuristic**, not a complete security or runtime syscall audit. Under- and over-detection remain possible, including aliased imports, dynamic reflection and file-descriptor methods.

A locally sealed final **research-only receipt** was created at:
`stocks-workspace/scratch/baselineA/m3i_dependency_receipts/219307b01f8881e2132ed960`.
A separate invocation re-opened its sealed manifest and verified the id, content hash, 8 modules, 6 sites and `model_release_blocked=true`.

## 3. Actual tests
- Added `m3i_test_dependency_gate.py`: **15/15 unit tests passed**, with synthetic local module trees, imported-file mutations, `subprocess.run`, network client calls, dictionary and ordinary string false-positive exclusions, refusal to execute malicious import-time code, recursive imports, change detection and create-only seals.
- Entire prior + new isolated Milestone 3 scratch test suite: **163/163 PASS** with Python 3.12.
- This is **source-analysis and test coverage only**; the actual scorer **was not imported or executed**, not even in a mock subprocess. No isolated runtime sandbox has yet passed a real read/write or network escape test.

## 4. Strict forward isolation plan / no producer run authorization

The following are prerequisites, **not permissions already obtained or operations executed**:

1. **Pin and timestamp each actual upstream artifact** (prices and listings, financial histories, EPS trajectory, previous compatible scorer result, capital-cost and MRI sector anchor, veto config and depth overlay). Preserve capture/first-public time separately. A copy of old `stocks.json` does not become fresh because the scorer's output time changes.
2. **Stage a writeable paper-only clone** of the required code and inputs under `stocks-workspace/scratch` with an owner-controlled unique run id. Clone must not import sibling project code, inherit live production `MRI_OUTPUTS_DIR` or `STOCKS_ROOT`, or resolve `.env` or broker secrets; no symlink/hardlink back to any production data root.
3. **Enforce an actual OS write/network boundary**, with explicit allowlist of scratch writes, and validate peer path resolution, MRI copying, overlay, and previous-book hysteresis against pinned offline artifact hashes. An AST checker alone cannot enforce this boundary; do not execute the scorer without it.
4. Compare full outputs to registered contracts and freeze originals with their **actual** generation and source information time. Preserve Door-3 separate ranking semantics and share-class identity.
5. Secure an independent event truth set and external design review before any Qwen shadow-only benchmark. Qwen is **not** entitled to trade or to veto a buy; 3A A1 turnover gate remains failed and the revision-26 valuation holdout stays untouched.

**Operational states:** no `KIS_HALT`/`DEPTH_PAUSED` changes, no live publisher modification, no CI/deploy, no GPU inference, no scheduled job and no actual transactions.

**Milestone 3I static dependency audit COMPLETE; full milestone 3 remains OPEN.**
