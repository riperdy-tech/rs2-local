# Milestone 3D — First-hand SEC receipt smoke and provisional issuer-identity bridge
**Date:** 2026-10-24 KST. **Status:** source capture and provenance linkage implemented/tested; **Qwen risk-performance evaluation remains NOT ELIGIBLE**. Work is isolated to `stocks-workspace/scratch/baselineA/` and the rev23 docs. **No new model, broker, screener publisher, production task, CI, or investment decision was changed.**

## 1. Why this work exists
The 3B audit showed 2025-Q4 SEC submissions files were acquired **after** their supposed historic decision dates. The 3C capture of the publisher's current score artifact reported 161 nominees but **no CIK or global rank in per-name profiles**, and its source was generated on 2026-10-15 (not fresh for the 2026-10-24 decision). Giving Qwen a current cache would contaminate a purported 2025 assessment.

Goal here: establish whether a local *first-hand* SEC retrieval receipt and an explicitly **provisional** CIK join can be captured, checked and preserved without inventing past information.

## 2. Evidence produced and independently rechecked

### 2.1 SEC CIK submissions index — 1 actual HTTPS request, successful
- SEC URL: `https://data.sec.gov/submissions/CIK0000320193.json` (Apple CIK `0000320193`), HTTP 200; **163,917 bytes**.
- Collection observed locally: **2026-10-23 16:08:21.429894–16:08:21.538091 UTC** = 2026-10-24 01:08:21 KST.
- Body SHA256: `47e4383b0133a4146cc631725f9aa28bac6d5679d504f735a78f1a1923c4b622`.
- Create-only paper receipt id `e823c9836def5e0a4520014e` in `m3d_sec_receipts/`. It is an SEC **index**, NOT a filing document, adjudicated event, verified negative, or proof that this system possessed it in 2025.

### 2.2 Actual SEC 8-K primary document — 1 HTTPS request, successful
- Obtained the accession and `primaryDocument` from the *sealed index above*, then requested one Apple 8-K document:
  `https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/aapl-20260730.htm`.
- HTTP 200; **38,467 raw bytes**; SHA256 `ca03ec3b300279dc2fc1761b8a68ece4018fe4383d1e2d4a033c41987b727d75`.
- Actual local fetch **2026-10-23 16:13:42.035040–16:13:42.114073 UTC** (2026-10-24 01:13:42 KST).
- Create-only paper receipt id `6f218bbe3a27aa8b00971f93` in `m3d_sec_receipts/`. Full raw bytes preserved; no extraction or semantic verification claimed.

### 2.3 Link the two receipts without promoting a trading risk
- Link verifier checks receipt seals, matching CIK, exact accession `0000320193-26-000018`, matching primary filename and chronology. The SEC index states acceptance **2026-07-31T00:30:28Z**. This is an **SEC index metadata claim recorded now**, not a local 2026-07-31 receipt.
- Create-only linked metadata receipt id `8eb6b5af5fa9fab77da52995` in `m3d_link_receipts/`. `ground_truth_event=null`, `historic_asof_availability_proven=false`, `model_release_blocked=true`.
- The linkage confirms *which SEC document the currently obtained index names*; it does **not** classify the company's business risk, transaction role, correctness of accounting, materiality, return impact or absence of other events.

### 2.4 Existing CIK map reaches all nominees, but is an unverified time bridge
- Previously separate read-only publisher artifact `screener-publish/public/data/cik_map.json`: `fetched_at=2026-06-10T16:28:15Z`, SHA256 `ade712aa93511cedf773c9556df088be366006571e1832d66e4593eb8d4bbf53`.
- Screener publisher's `factor_scores_dual_door.json` is `generated_at=2026-10-15T17:44:03Z`; the 161 `nominated_tickers` agree exactly with the 161 `profiles`.
- The join maps **161/161 symbols** to 160 distinct CIKs. The sole duplicate is **SENEA/SENEB → 0000088948**, two share-class symbols for one issuer; it is **not dropped or treated as an error**.
- Source originals, hashes and complete 161-row join table were stored as a sealed, create-only paper identity audit id `e443e577620c118fb623fb9d` in `m3d_identity_receipts/`; independent verifier passed.
- All 161 matches remain labelled `unverified_ticker_to_cik`; **0 of 161 have demonstrated PIT identity proof** in this exercise, and **0 source global numeric ranks**. This particular CIK map was fetched months before the October screener snapshot; without a versioned ticker/CIK alias-effective-time owner and source freshness tests, its existence does not certify every as-of alias, successor or share-class meaning. Do not inject these CIKs into the already frozen 3C snapshot.

## 3. New scratch code and test results
Code in `stocks-workspace/scratch/baselineA/`:
- `m3d_sec_receipt.py`: exact SEC HTTPS host/path allowlist, no redirects, URL/account binding, response size cap, SEC user-agent identification, locally observed UTC GET start/end, raw bytes SHA256, create-only `body.bin` / `receipt.json` / `SEALED`. Submissions index must match requested CIK.
- `m3d_identity_bridge.py`: joins the **complete** original publisher nominations to the already-existing ticker/CIK map, validates source dates and source profiles, tracks unmapped symbols and share classes, preserves both original files and immutable join/provenance manifest; never upgrades a candidate to verified PIT identity.
- `m3d_link_receipts.py`: matches sealed SEC index to sealed filing document; returns a sealed metadata link with claimed SEC acceptance date and actual fetch date, but **no event verdict**.
- `m3d_test_sec_receipt.py`, `m3d_test_identity_bridge.py`, `m3d_test_link_receipts.py`: no-network synthetic tests for time, CIK/document mismatch, malicious URL, overlong/missing document, redirect, future acceptance, duplicate share classes, missing mapping, altered raw input, unexpected file, create-only and missing provenance.

| Tests, system Python 3.12 | Result |
|---|---:|
| 3A quarterly accounting | 14/14 |
| 3B SEC source-time verifier | 17/17 |
| 3C snapshot integrity | 26/26 |
| **3D SEC retrieval receipts** | **11/11** |
| **3D provisional CIK bridge** | **9/9** |
| **3D index/filing metadata link** | **6/6** |
| **Entire scratch milestone-3 suite** | **83/83** |

All four create-only records (SEC index, filing body, provisional identity bridge and linked metadata) were separately reopened and validated; actual test output and receipt ids are recorded in the work log. All source files are in scratch, **not a deployed application**. Local write-once IDs and hashes are tamper-evident for accidental changes, not a privileged-user-proof WORM or external timestamp attestation.

## 4. Hard limitations: not a claim of AI edge
- The index and real 8-K were acquired **today**, not during 2025. No backdated files, automatic historic source reclassification, fake `no_event` rows or unverified negative controls were created.
- The screener snapshot is still **older than the registered 24-hour freshness bar**, and current publisher profiles have no authoritative per-symbol CIK and **no numeric global rank**; the June CIK map is only a preliminary, time-bounded candidate mapping.
- One 8-K retrieved and linked is **not** a representative real-event corpus; neither SEC event type nor truth labels have been dual-adjudicated. No source family completeness, false exclusion, false-positive cost, missed-winner audit, Qwen recall/precision or incremental portfolio return has been measured.
- **A1 failed its prior turnover gate and remains rejected**; no retuning. Frozen revision-26 holdout remains untouched.
- The independent external design cross-check `CROSS_CHECK_26_strategy_after_baseline_A.md` is still **pending**. This engineering work and self-tests are not an external reviewer.

## 5. Next safe activities / promotion gate
1. Specify a versioned **authoritative PIT ticker→issuer CIK alias and global rank handoff**, independent from user-provided post-T mapping, for a *fresh* paper-screener output (without changing live producer until separate review).
2. On a fresh documented formation date, freeze *the entire* eligible/held universe and per-source first-hand SEC/exchange documents; preserve timestamped coverage failures. One SEC Apple filing is only the collector's smoke.
3. Register and dual-adjudicate genuine positive **and negative** event opportunities blind to model predictions; evaluate deterministic B coverage, detected lead time, and false alarms before Qwen. Keep unclear cases labelled unknown, not clean.
4. Obtain independent external cross-check and operator review. Only consider a resource-capped **shadow-only** Qwen run once the audit packet, issuer role and time cut are genuinely eligible. No automatic pause/sale.
5. `KIS_HALT` and `DEPTH_PAUSED` stay unchanged. No deployment, scheduled GPU work, live screener edit or real-money orders.

**Disposition:** 3D SEC retrieval-and-linkage **smoke success**, identity join **provisional success**, Qwen-B/C performance **not measured**. Overall milestone 3 is **open**; move on to time-proven fresh cohort and independent event truth, not a premature AI score.
