# AUDIT: WO_L1, WO_L3 and WO_L4 (2026-10-29, Claude)

**Note on independence.** Claude both executed and audited this work (PLAN W, revision c). The audit reran every
acceptance test from scratch and recomputed key numbers from raw git blobs. It found and corrected four defects in
its own work (listed below). The gate verdicts in L-P2/P3 and L-P4F change P-criteria, so under W.2 step 5 they are
offered for an outside cross-check: `CROSS_CHECK_L3_L4.md`.

## WO_L1: APPROVED

- **Reran:** row count = `total_count` (933); `sha256sum -c` passes; the truncated-zip control; and the 40608600897 zip
  hash, which matches the two earlier downloads.
- **Defects found and fixed in the audit:**
  1. `run_log.txt` was being checksummed while still being written. It is now excluded.
  2. The in-progress run 40707381769 was mislabelled `LOGS_EXPIRED`. It is now `NOT_COMPLETED` and will be retried on
     the next pass.
- **Gate L-ARCH: PASS.** 648 runs preserved, back to 2026-07-30. **Follow-up:** a weekly refresh, so later runs are
  preserved before they expire.

## WO_L3: APPROVED

- **Reran:** pytest 9/9, and the full verifier on 40608600897.
- **Defects found and fixed in the audit:**
  1. The first input list missed three files read by imported helpers: `not_tradable.json`, `depth_reports/` and the
     sifter config.
  2. The first input list misclassified the output-only `factor_scores_dual_door.json`.
  3. The first input list flagged the unused fallback `momentum_config.json` as `MISSING`.

  All three are fixed and re-verified.
- **Recomputed by hand from git blobs:** 160 unique nominees; 9 with EPS rows, matching 9 non-null `z_revisions`;
  `shares_cover` maximum filed date 2026-10-23, not after the decision.
- **Gate L-P2/P3: PASS for paper scope, run 40608600897.** All 160 nominees are `PIT_PROSPECTIVE` under W.4, with the
  momentum leg annotated `PIT_VALID_UNPRESERVED` for all 160. All 160 are kept visible, including the four
  operator-excluded names, which are flagged.

## WO_L4: APPROVED (the work); gate L-P4F is BLOCKED_OWNER

- **Reran:** replays A, B, C and D, plus the seed check.
- **Defects found and fixed in the audit:**
  1. The first negative control (doubling revenue) did not discriminate. It was replaced by one the code guarantees
     matters, and both are kept on record.
  2. An unfrozen clock in `tradability` caused 434 spurious differences. That clock is now frozen.
- **Gate L-P4F: `BLOCKED_OWNER`.**
  - The only input that blocks a byte-exact replay is the uncommitted in-run `momentum_state.json` (and
    `daily_closes.json`).
  - The unblocking change is two `git add` lines in `price-refresh.yml`, matching what `schedule-data-fetch.yml`
    already does. It is a CI change, so it needs the operator's approval (W.5).
  - After approval: re-run L4 on the next price-refresh run.

## Corrections carried into the records

- `DECISION_m3l_3L_PIT_resolution_2026-10-28.md` overstated the tree-as-manifest claim. It needs an erratum: the
  momentum state is not in the trees. The erratum is added there.
