# Milestone 3F — Recover real screener global ranks from existing compatible output

**Date:** 2026-10-24 KST. **Verdict: structural research rank source recovered and sealed, but NOT a fresh PIT cohort or approved AI input.** Production screener, broker, live publisher, CI, and GPU/model operation remain unchanged. No trading or deployment.

## 1. Correction to previous interpretation

Previous 3C/3E checks correctly reported that the publisher's `factor_scores_dual_door.json` **per-nominee profile lacks a numeric global rank** and does not contain a CIK. Milestone 3E had **zero independently supplied versioned rank handoff artifacts**. A read-only analysis of the ACTUAL production scorer code `screener-publish/scripts/score_factors_dual_door.py` now establishes a more specific, important fact:

- The scorer already calculates `rank_by_ticker` in its `main()` function, lines 2428–2444. This rank orders the nominated Door-1/2 priority queue, then extends it with the remaining scored universe. `rank_by_ticker` is never something to infer from the later score percentile alone.
- It writes the full numeric `fct_rank = rank_by_ticker.get(t)` into the compatibility output `public/data/factor_scores.json` around lines 2495–2518.
- It writes the 161-name published shortlist and its source profiles into **a different file** `public/data/factor_scores_dual_door.json` around lines 2489–2493, without adding the numeric rank per profile.
- Door 3 uses a separate momentum/key order (`_door3_rank_key` around 2303–2313); some Door-3 research_now members legitimately have high global Door-1/2 rank. **Never apply Door-1/2 rank80 retention to Door 3**, and never claim `fct_rank` equals Door-3 momentum rank.

**Correction:** numeric ranks are NOT absent from the producer. They are present in a separate existing compatibility output. This is a structural discovery, not new alpha or proof of fresh data.

## 2. Real saved file comparison (read-only)

Read from the same `screener-publish/public/data/` folder, without re-running the scorer:

| Field | Observed |
|---|---|
| `factor_scores_dual_door.json` generated | **2026-10-15 17:44:03 UTC** |
| `factor_scores.json` generated | **2026-10-15 17:44:03 UTC** |
| Candidate count in dual-door file | **161** |
| Every candidate also present in compatible `tickers` | **161/161** |
| Candidates with valid positive integer `fct_rank` | **161/161** |
| Candidate bands from compatible output | **61 research_now + 100 watchlist** |
| Candidates with Door-3 nomination in separate membership list | **20** |
| Valid source ranks across scored universe | **2,865**, consecutive 1..2865, without duplicate rank |
| Published candidate global rank min/max | **1 / 1,569** |
| Corporate regime and hysteresis state | Both outputs match |
| Candidate `best_pctl` versus compatible `fct_percentile` | All 161 numerically match (2-decimal source rounding) |
| Candidate `nominated_doors` versus compatible `fct_nominated_doors` | All 161 match |
| Candidate veto/band conflicts | None found |
| Named CIK in these per-candidate output profiles | **None** |

The identical generated-at second plus complete matching attributes is strong **internal consistency evidence**, **not an independent cryptographic proof of one production process**. Both files are **older than the pre-registered 24-hour freshness rule** on 2026-10-24. Their collection *today* does not make them a prospective ranking captured on Oct 15.

Source SHA256s:
- Dual-door output: `ed9c8c515429b08cd3d3b8586c1ab6048cdaa55358aa7b488ff505b3f0170e99`
- Compatible output: `59b0f915043eefafd92a7d4593d79796ae2850ba2cef6b00e2ebabb3493b48de`

## 3. Isolated paper extraction + evidence

Added in `stocks-workspace/scratch/baselineA/`:
- `m3f_compat_rank_receipt.py`: joins unchanged source bytes of BOTH original files by symbol and source generation timestamp, checks source cohort count, macro/hysteresis, all compatible rank uniqueness, candidate rank, matching band, percentile, doors and veto, and stores a create-only sealed pair of full raw files with per-file SHA256 and extracted, auditable 161-name rank table.
- `m3f_test_compat_rank_receipt.py`: 14 deterministic offline fixtures for missing nominee, rank, conflicting band/door, inconsistent generation timestamp/percentile, duplicate ranks, null percentile, stale source and altered file seal.

**One real audit receipt created:** `stocks-workspace/scratch/baselineA/m3f_rank_receipts/abc21d9d591026a365184c0c/`. Full original files were preserved in `dual.json` and `compat.json` plus `rank_audit.json` and `SEALED`. A **separate reader invocation** verified the seal and recomputed all 161 ranks from saved originals: exact match; 61 research_now, 100 watchlist, 20 Door-3 nominated; `fresh_24h=false`, `model_release_blocked=true`.

**Important owner constraint:** this scratch receipt is `source_owner=paper_compat_rank_extractor`, not a forged original `screener_rank_producer` release. It is **not** automatically accepted as the versioned handoff expected in `m3e_pit_handoff.py`. The producer still needs an authoritative paired-output identity/provenance contract and fresh evidence before a paper decision.

## 4. Tests and limitation
- New rank extractor tests **14/14 passed**. Full scratch suite 3A–3F **128/128 passed** using system Python 3.12; all changes in scratch and docs.
- Real existing rank receipt verification **passed**; did not re-run full production scorer or overwrite the source data.
- **NOT tested**: whether these two files came from exactly one process rather than coincidentally sharing a timestamp; any new/fresh score build; issuer CIK effective-dated joins; complete SEC/exchange coverage; independent ground-truth event labels; Qwen precision/recall or incremental risk advantage; strategy A1 promotion; real-money trading.
- The prior 3A strategy failure remains: A1 turnover 1.6311x exceeds pre-registered 1.60x, and true delisting bounds remain invalid. Do not retune the same historical window.
- KIS and depth control states were not changed; revision-26 holdout remains untouched.

## 5. Next work, minimum additional contract
1. Do not rebuild old rankings from now-known prices: **reuse existing producer `fct_rank`** and pair source output hashes. Identify a change-safe, isolated paper-side handoff from the producer that carries `fct_rank` with its **exact generating-run revision and timestamp**, plus a separate reviewed effective-dated CIK/alias source. New fields belong to registered owners.
2. Only score paper nominations after a **fresh source generation** within the agreed decision cutoff; historic Oct-15 files are **forensic evidence only**.
3. Build independently adjudicated positive/negative corporate-event opportunities, with full source accession-body evidence and missing-coverage inventory. SEC index/form hints are not events.
4. Obtain independent design cross-check and operator sign-off before considering any Qwen shadow trial. No model veto, forced sale, automatic buy pause or deployment.

**Disposition:** 3F structural rank-source gap substantially narrowed by recovering 161 actual global ranks. Full milestone 3 still blocked by fresh PIT/source-attested issuer identity and independent event labels; Qwen edge remains unmeasured.
