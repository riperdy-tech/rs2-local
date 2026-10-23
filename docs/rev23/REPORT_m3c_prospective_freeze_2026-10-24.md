# Milestone 3C — Prospective snapshot integrity infrastructure and first real-source coverage probe

**2026-10-24 KST. Verdict: infrastructure TESTED; current source packet BLOCKED for model use.** No AI GPU run, no risk-detection precision/recall measurement, and no trading or deployment changes.

## 1. Work implemented (scratch only, manually invoked)

Under `stocks-workspace/scratch/baselineA/`:

- `m3c_freeze.py`: validates a full cohort, supplied screener source/body/hash/acquisition/publication times, issuer CIK and ranking coverage, and any independently supplied SEC source bodies. Stores one unique create-only snapshot directory with the original screen bytes, accepted document bytes, per-file SHA256 and a final `SEALED` manifest hash. Refuses reuse of the same id. The verifier rejects changed, missing **or unindexed extra** files and requires `model_release_blocked=true`.
- `m3c_test_freeze.py`: deterministic synthetic fixtures for absent CIK/rank, 0 vs null, duplicate nominees or accessions, future publication/acquisition, screener freshness, mismatch of issuer/accession in SEC URL, checksums, tampering, sealing and replay.
- `m3c_capture_existing.py`: reads an existing complete screener JSON source in one pass, stamps the **actual time it was read** (not a claimed old date), validates that the declared nominated count, exact nominated symbols and profile keys agree, and preserves *every* nominee. It does **not** impute missing issuer CIK/global rank from modern data. No HTTP, broker, model call or scheduled task.
- `m3c_review_frame.py`: on the frozen **2025-Q4** 180 candidate-months, registers a deterministic, model-blind set of **15 manual source-review candidates** (5 each month) using a fixed seed `m3c-source-audit-controls-20261024-v1`. All 15 remain `unknown`, **not** negative labels. This is a *sampling-method diagnostic*, not an admissible Qwen historical test because 2025 source-acquisition timing failed in 3B. It does not enumerate all positive event opportunities, stratify the full population by market cap or draw true negatives.

The input's `published_utc` and `acquired_utc` metadata are checked **but user-supplied metadata cannot prove authentic contemporaneous acquisition**. This implementation is a tamper-*evident local snapshot convention*, **not** cryptographic WORM storage or independent timestamp notarisation. The source-integrity validation does not adjudicate what a SEC filing means or whether its content is a critical business risk. Even a valid snapshot remains blocked from automatic Qwen use.

## 2. Actual saved paper snapshot from a project source

Source examined read-only: `screener-publish/public/data/factor_scores_dual_door.json` (publisher clone was not edited, run or pushed). File `generated_at=2026-10-15T17:44:03Z`; source checkout revision `fe9af7b4937a`. Its nominator has **161** `nominated_tickers` and 161 matching profile records, but the per-nominee profiles include **neither an explicit issuer CIK nor a global numeric rank**. No independent current SEC primary-source documents were present in this packet. The 161 nominees are **not interchangeable with** the ~58 historical monthly `research_now` portfolio.

A new paper-only snapshot was actually created and verified:

```text
stocks-workspace/scratch/baselineA/m3c_paper_snapshots/
  fd005b4e061de3ba18692609/
    screener.txt
    snapshot.json
    SEALED
```

- Snapshot ID `fd005b4e061de3ba18692609`.
- Actual source-read time: **2026-10-23T15:53:26.851864+00:00** (2026-10-24 00:53:26 KST).
- All 161 candidates were retained; usable source documents **0**; known CIK identifiers **0**; explicit numeric ranks **0**. The absence is recorded per row rather than silently excluding a company.
- **`observation_type=stale_or_undated_selection`**, since the underlying source was ~8 days old. A new operational integrity rule requires a source-generated timestamp within **24 hours** of the prospective decision time for the *fresh* label; this is a safety metadata rule, **not an investment-performance parameter**. Reading old data today does not make an old ranking current.
- **`model_release_blocked=true`**, no order/sale/pause field, and source-acquisition trust remains unverified for any externally provided envelope. The saved snapshot passed the reader verifier in a separate command. It must NOT be used for Qwen performance claims.

## 3. Actual tests

Ran using `C:\Program Files\Python312\python.exe -m unittest discover -s stocks-workspace/scratch/baselineA -p 'm3*test*.py' -v`:

| Suite | Passing | Description |
|---|---:|---|
| 3A quarterly paper mechanics | **14** | ranks, rebalance, drift, missing price, transaction cost, delisting |
| 3B SEC evidence gate | **17** | CIK, accession, UTC time, source original/hash, quote, no automatic verdict |
| 3C snapshot integrity and freshness | **26** | future source, full candidate list, file seal, stale data, double-create, tampering |
| **Total** | **57 / 57** | **All passed**; not live-model quality validation |

Each 3C Python file passed syntax validation, and the real saved snapshot was independently verified as `stale_or_undated_selection`, 161 nominees, zero accepted documents, and blocked model release.

## 4. Self-review of method risks (NOT independent external AI review)

1. **Freshness:** Oct-15 score artifact cannot certify a decision on Oct-24; require fresh source generation, or record stale coverage, never re-label. Cross-repository publication files remain read-only.
2. **Identity:** the current publisher payload has no per-name CIK or global rank. A prospective source contract must provide issuer identity from a **time-proven, separately owned** mapping and versioned rank. Never backfill 2025 CIKs from 2026 mappings without an explicit temporal join.
3. **Independent source capture:** locally declared `acquired_utc` is not a first-party fetch receipt. A truly strict paper risk assessment needs its own issuer- and accession-bound SEC/exchange retrieval with fetch-time evidence and original text hashes **at collection time**. The scratch code currently has no network fetch and cannot claim this proof.
4. **Event truth:** no independent positive-event enumeration or audited negative-control corpus exists. A 15-name *review draw* is not an estimate of recall or specificity, and no model predictions have been read. Reviewers must independently label positives/negatives and record missing coverage per type.
5. **External cross-check:** `CROSS_CHECK_26_strategy_after_baseline_A.md` still awaits an actual independent reviewer; this self-review does **not** fulfil that check.
6. **Scope:** `KIS_HALT` and `DEPTH_PAUSED` were not altered, no deployment, CI, rev26 prompts, live overlays, live trade order, automated polling or GPU work was performed.

## 5. Next safe work package

1. Audit whether a genuinely fresh paper screener snapshot is available and **contains CIK and rank** in the authoritative source; if not, design the minimum versioned PIT identity/rank handoff without modifying a live generator.
2. Build a separate read-only SEC/exchange source-fetch **receipt** component that records first-hand fetch UTC and checks issuer/accession/source body. Add offline mocked tests and one small live connectivity smoke with a known SEC document; classify any network outage honestly. Never forge source timestamps.
3. Freeze a *complete* fresh candidate cohort into the create-only paper registry; until required identity and source coverage are present, the result remains `not_model_ready`.
4. Independently enumerate confirmed events and control windows, with two blinded adjudicators; only after that obtain an external cross-check and **consider** a Qwen shadow-only study. A 90% recall claim cannot be made without valid denominators and confidence bounds.

**Overall milestone 3:** 3A failed A1 acceptance, 3B event-source audit completed with historical data-coverage failure, 3C capture machinery works but no admissible prospective evidence cohort yet. **Qwen risk/change-detection benefit remains UNMEASURED.**
