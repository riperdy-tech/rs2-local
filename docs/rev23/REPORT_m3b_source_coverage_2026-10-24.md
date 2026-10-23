# Milestone 3B — SEC event-source observability and chronology audit
**Date:** 2026-10-24 KST · **Disposition:** offline source census and independent eligibility checker completed; **event detection and Qwen C historical grading BLOCKED for lack of time-proven evidence and ground truth**. This is not an assertion that any company had or did not have a material event.

## 1. What was inspected / run
- Original project source: `rs2-local/sec_guidance.py` and `rs2-local/sec_primary.py` (read-only). The current SEC subs cache is refreshed at today's UTC date by `sec_guidance._submissions`; `sec_primary.py` has stale-submission fallback disabled by default. Thus the existing cache is a **current research cache**, not inherently a historical as-of truth set.
- PIT cohort: `stocks-workspace/scratch/baselineA/data/s4_yahoo.pkl`, research_now non-vetoed nominations, formation dates **2025-10-31, 2025-11-30 and 2025-12-31** (after Qwen's estimated April-2025 cutoff). `m3_event_source_audit.py` reads only the frozen S4 replay plus existing `rs2-local/cache/sec_submissions`, `cache/sec_primary` and `cache/sec_8k` metadata; no SEC network traffic or saved-file modifications.
- Pure source checker: `scratch/baselineA/m3_event_provenance.py`. Tests: `m3_test_event_provenance.py` **17/17 passed** with Python 3.12. It checks known issuer CIK, URL, accession, approved source form, UTC publication/acquisition before T, full-text hash and quoted original excerpt. It **never** infers a critical event from a form code or issues trade restrictions.
- New registry design: `rev23/SCHEMA_m3b_event_truth_2026-10-24.md`. It separates eligibility census, source records, independent positive event opportunities, and stratified negative controls.

## 2. Measured historical-source coverage
| Metric | Observed |
|---|---:|
| Formation snapshots | 3 (2025-10, -11, -12) |
| Non-vetoed `research_now` snapshot rows | **180** (62 + 59 + 59) |
| Missing CIK in nominations | 0 |
| Distinct source CIK identifiers | **88** |
| CIKs with readable `sec_submissions` cache | **18** |
| CIKs without a readable cache | **70** |
| Nomination rows referencing cached SEC submissions | **42** |
| Nomination rows without readable cached SEC submissions | **138** |
| Readable submission caches with recorded `_fetched_utc` after 2025-12-31 | **18 of 18** |
| 2025-Q4 filing **retrieval hints** visible in the 18 caches | **5** |
| Hint categories | 5 `8-K` with `1.01` hint (material contracts / possible M&A) |
| Hints with `acceptanceDateTime` field | **5** |
| Matching offline cached primary/exhibit bodies for these hints | **0** |
| Independently verified material events | **0 verified; unknown true count** |
| Independently verified negative/control windows | **0 verified; unknown true count** |

These are **cache availability** counts, not estimates of population filing-event prevalence. `filings.recent` may omit older rows, and `filings.files` is not automatically expanded; 9 of 18 cached records referenced nonrecent index segments. The audit deliberately did not dereference or fetch them. A 42/180 metadata link is **not** 23.3% verified source coverage, as none of those 42 examples has a time-qualified acquisition by its 2025 decision. The 5 8-K item hints may concern ordinary agreements; no event role, status, materiality or verbatim source has been checked.

## 3. Fail-closed historical C/B decision
**Do not run a retrospective Qwen C benchmark on this 2025-Q4 cache**. The source acquisition stamps are later than its decision dates; using content from current caches without a strict provenance reconstruction risks a hindsight leak. Also, no independently ascertained true positive and true negative denominators exist yet. Automatic `no_event` for the other 138 snapshots would greatly exaggerate specificity.

The deterministic B event checker likewise cannot earn authority from 5 filing-item hints. SEC filings can establish issuer, submission time and candidate type **only after** the full accession is matched and the meaning of its text is independently reviewed. Fixed-price acquisitions must separate buyer from target and proposed from closed, plus amendments/cancellations. Trading halts need timestamped exchange evidence. For this audit there were no confirmed hard stops or actions, **not** evidence that no hard stops happened.

## 4. Exact implementation and verification
- New scratch Python files: `m3_event_source_audit.py`, `m3_event_provenance.py`, `m3_test_event_provenance.py` under `stocks-workspace/scratch/baselineA/`.
- Syntax: all three passed `bridge_validate` (Python syntax, not execution).
- Execution: read-only metadata census exit code 0; provenance unit tests 17 passed, 0 failed. Only **synthetic validation fixtures** were used by unit tests. No Qwen inference, truth adjudication, trading simulation, current-events fetch or GPU test was run in 3B.
- Source check accepts a candidate for *manual adjudication* only; it does not semantically establish that a quote names a real risk, that an event is material, or that source caching was immutable.
- Known limitations: historic prices and SEC report content may have been obtained retrospectively; 8-K/6-K index alone lacks independently verified source availability at a market-time cutoff. Without an externally complete positive-event enumeration plus audited negatives, B/C error rates are not meaningful.

## 5. Next independent milestone, before any Qwen C model use
1. Implement the registry as **paper-only immutable, time-stamped prospective snapshots** for future dates; collect published time, acquisition time, exact SEC/exchange filing bodies and complete checksums before building a prompt. Avoid future-data web retrieval in a historical prompt.
2. Produce an **independent** event enumeration and randomly sampled negative-control set across all PIT nominees; log source coverage and unavailable records, and have two reviewers label the same sample without reading model outputs.
3. Validate event family semantics and issuer target/role (acquirer vs target, open vs settled, restated vs amended, lifted halt vs active), then establish a **B-only baseline** before Qwen.
4. Obtain a review of `CROSS_CHECK_26_strategy_after_baseline_A.md` and decide whether a **prospective** shadow Qwen study has an adequately complete evidentiary packet. If fewer than 20 real independently confirmed critical event opportunities exist, report that limitation without manufacturing positive cases. Keep all AI output in observation-only mode.
5. No reason to change `KIS_HALT`, `DEPTH_PAUSED`, the rejected A1 rank buffer, revision-26 model or the 4-name valuation holdout.

**Disposition:** source-provenance audit and checker are completed; material-risk performance of deterministic B and Qwen-C is **unmeasured**. Milestone 3 overall remains open.
