# Milestone 3G — Rank/issuer receipt pairing and fresh-source readiness audit

**As of:** 2026-10-24 KST. **Disposition:** EXISTING SOURCES CROSS-LINKED, prospective PIT and Qwen shadow input still **BLOCKED**. This document covers offline, paper-only evidence; no publisher scoring, broker trade, GPU inference or deployment was executed.

## 1. Actual fresh-source inventory — no eligible 24-hour producer snapshot

We inspected actual local metadata without re-running any scorer. The following are last-write timestamps, **not** independent source creation or publication attestations:

| Working tree and source | Last-modified UTC | Result |
|---|---|---|
| `stock-screener/public/data/factor_scores_dual_door.json` | 2026-09-22 02:56 | Older development copy |
| `stock-screener/public/data/factor_scores.json` | 2026-09-22 02:56 | Older development copy |
| `screener-publish/public/data/factor_scores_dual_door.json` | 2026-10-15 23:22 | Newest located dual-door file but stale |
| `screener-publish/public/data/factor_scores.json` | 2026-10-15 23:22 | Matching publisher compatibility file but stale |
| `screener-publish/public/data/stocks.json`, price/momentum data | 2026-10-15 23:22 | Inputs also old, do not assume a newly run scorer would be fresh |

The publisher's two score files themselves both record `generated_at=2026-10-15T17:44:03Z`. No complete rank/CIK/provenance-rich source produced in the 24 hours before the current observation was found among the inspected local trees. **We did not establish why automation stopped or whether an independent remote publisher may hold newer data**. Do not claim a publisher outage from these file dates alone. Running `score_factors_dual_door.py` would write the live publisher output files, so it was **not invoked**.

## 2. Two existing, previously sealed sources were cross-verified

Actual file-backed evidence reused without regenerating or altering it:

- **Rank receipt** `m3f_rank_receipts/abc21d9d591026a365184c0c`: scored dual-door shortlist and compatibility result, the **161 original numeric `fct_rank` values** from the scorer, 61 research_now, 100 watchlist, 20 Door-3 nominated, with score SHA256 `ed9c8c515429b08cd3d3b8586c1ab6048cdaa55358aa7b488ff505b3f0170e99`.
- **Issuer lookup receipt** `m3d_identity_receipts/e443e577620c118fb623fb9d`: source `cik_map.json` fetched 2026-06-10, all 161 provisional symbol-to-CIK associations, **160** distinct CIKs (SENEA/SENEB share issuer), **zero** issuer identities independently verified as valid at the later decision T.

New isolated scratch code `m3g_paired_chain.py` verifies **both existing source seals**, compares the exact original screener SHA256, generation timestamps and complete symbol set, checks numeric rank and provisional CIK type, and rejects duplicate/missing symbols or any input promoted from its blocked state. It records all information, including Door-3 membership, without inferring missing dates or new trading signals.

**New create-only sealed audit receipt:** `stocks-workspace/scratch/baselineA/m3g_paired_receipts/7f95d2f1f8faa0cf62428a21`.

| Audit field | Reverified result |
|---|---:|
| Full candidate entries | **161** |
| Actual, original numeric candidate ranks | **161 / 161** |
| Provisional CIK associations | **161 / 161** |
| Distinct provisional issuer CIKs | **160** |
| PIT/effective-dated issuer aliases independently proven | **0** |
| Same-score-file digest across both input receipts | **Exact match** |
| Registered fresh score within 24 hours | **No** |
| Same generator process independently proven | **No** |
| Independently adjudicated business risks | **0 verified / unknown true count** |
| `model_release_blocked` | **True** |

The independently invoked verifier re-opened the paired audit and **both underlying sealed receipts**, compared the original source digests, and confirmed all 161 rows plus blocked model status.

A correct hash join is **not** a temporal alias attestation: an issuer map acquired in June cannot automatically prove later ticker/CIK validity. Also, identical `generated_at` seconds and cross-file profile equality are valuable internal checks but not a signed original generating-run identity. **The combined result is a forensic, stale, model-blocked audit**, not the authoritative owner-native PIT artifact required by `m3e_pit_handoff.py`.

## 3. Test results and scope

- New `m3g_test_paired_chain.py`: **11/11** deterministic tests, including mismatched source SHA/generation, missing/duplicate symbols, incorrect CIK/rank, share classes, tampering and unsafe release.
- Full isolated scratch milestone-3 suite: **139/139 PASS** under system Python 3.12.
- No changes to `stock-screener`, `screener-publish`, `rs2-local` tracked files; no `.env`, CI, broker, Qwen model or registered 4-name valuation holdout touched. No scoring pipeline rerun.
- The 3A candidate is still **rejected** by its locked turnover threshold (1.6311x vs ≤1.60x) and unscorable historical delisting sensitivity.
- No independent full event corpus, complete negative controls, proof of human reviewer independence, or Qwen accuracy/incremental return measurement exists. The source coverage results from 3B–3E remain applicable; combining local existing snapshots cannot fix those deficiencies.

## 4. Safe next decision and work package

The **rank-data gap is addressed structurally** using original observed compatible-output `fct_rank`, so do not change the ranking formula to make a handoff. The remaining owner-native capture gap is concrete:

1. Capture **one newly generated**, complete screener output with the paired original compatibility result in a **non-deploying, read-only or isolated paper producer process** where inputs and run id are known. Do not silently overwrite the live `screener-publish/public/data` tree; first confirm isolated execution/provenance and the input data are genuinely current.
2. Source, independently verify, and effective-date the 161 issuer aliases (or a future fresh nominated cohort); if exact proof is missing, preserve candidates as unverified. A June map is a useful candidate registry, not a verified event universe.
3. Obtain first-hand SEC/exchange documents for a fresh cohort, record fetch/start/end vs publication T, adjudicate independent event positives and eligible control negatives, and get **external design cross-check**. Do not score the Qwen critical-event benchmark on hand-picked known events or current SEC caches for a historic T.
4. Until owner-native artifacts and event truth exist, **no GPU trial, buy pause, forced sale, model promotion or deployment**. `KIS_HALT` / `DEPTH_PAUSED` stay unchanged.

**Milestone 3G isolated forensic join COMPLETE; overall milestone 3's prospective PIT evidence and Qwen-risk edge remain OPEN and UNMEASURED.**
