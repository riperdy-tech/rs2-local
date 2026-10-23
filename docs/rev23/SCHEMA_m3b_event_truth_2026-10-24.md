# Milestone 3B — Event, source, and negative-control truth registry (paper-only)
**Prepared:** 2026-10-24 KST. **Status:** validation contract, not a complete evidence corpus; no verified-event rows have been independently adjudicated. No production deployment and no automated trade restrictions.

## 1. Three disjoint datasets
Do not use the current SEC cache as a ground truth by default. The registry must have **separate denominators** and independent time labels:

1. **Snapshot census**: every PIT eligible screener nomination/held-name at T, including missing-issuer-id and missing-source cases. Stable id `(formation_utc, issuer_cik, role)`; never restrict to AI-selected or previously risky names. Counts missing data separately from negatives.
2. **External event opportunity register**: all independently identified positive events in the eligible issuer universe and prespecified future observation window, including events **not** found by the deterministic checker and not raised by Qwen. Reviewers consult contemporaneously published primary sources; retrospective enrichment requires a disclosed collection-time limitation. A form code alone creates a candidate, not an opportunity.
3. **Time-stratified negative/control samples**: randomly sampled company-months from the *same* eligible universe and dates, with reviewed source coverage. Reviewers record credible no-event only where sufficiently complete event sources exist; otherwise `unknown`. Random seed, frame, strata, exclusions and every draw must be registered before opening model predictions.

Sampling frame (initial): paper nominations 2025-10 onward and new prospective snapshots, split by month, market-cap cohort, listing family (US domestic/foreign), and seven event classes. Use a fixed random seed/version for reproducibility. This is not a license to claim 2025 Q4 was a valid Qwen replay when no contemporaneous source acquisitions exist.

## 2. Snapshot record contract
Required fields, with owner `paper_snapshot_registry`:
```json
{
  "snapshot_id": "<stable unique opaque id>",
  "asof_utc": "<ISO8601 with timezone, trading decision cutoff>",
  "issuer_cik": "<zero-padded 10-digit CIK or null with reason>",
  "symbol_asof": "<as-of ticker, alias history separately>",
  "selection_role": "nominated | held | eligible_control",
  "screener_source_sha256": "<64 lowercase hex>",
  "rank_asof": "<integer, or null and explicit missing_reason>",
  "source_bundle_id": "<immutable provenance envelope id>",
  "source_coverage_state": "complete_audited | partial | missing | future_collected",
  "source_missing_reasons": ["<enumerated nonempty reasons when not complete>"],
  "evidence_count": 0,
  "code_revision": "<git commit>",
  "created_utc": "<actual acquisition and recording time>"
}
```
`source_coverage_state` must **not** be inferred as `complete_audited` merely because a cached SEC submissions file is readable. Source acquisition and public dissemination are different timestamps. `0.0` is a valid metric, never an absent value. IDs belong to the paper registry and are not inserted into production contracts.

## 3. Evidence envelope contract
Source owner `paper_evidence_registry`. Every candidate filing/source has:
```json
{
  "issuer_cik": "<10 digits>",
  "document_cik": "<verified issuer of the filing, independent of accession prefix>",
  "accession": "<SEC accession with dashes>",
  "form": "<8-K/8-K/A/6-K/6-K/A/10-K/10-Q/20-F/40-F/...>",
  "source_url": "https://www.sec.gov/...",
  "published_utc": "<full timezone-aware acceptance/publication timestamp>",
  "acquired_utc": "<actual source snapshot acquisition timestamp>",
  "source_sha256": "<hash of exactly stored full source UTF-8 text>",
  "source_text": "<unmodified original source body>",
  "quote": "<verbatim passage present in source_text>",
  "event_type": "fixed_price_acquisition | going_concern | delisting_notice | restatement | exchange_trading_halt | bankruptcy_or_restructuring | dilutive_reverse_split | other_material_change",
  "candidate_discovery_channel": "independent | deterministic | ai",
  "event_status": "candidate | confirmed | cancelled | superseded | unknown",
  "entity_role": "subject | buyer | seller | subsidiary | counterparty | unknown",
  "effective_utc": "<time or null with reason>",
  "materiality_basis": "<typed, source-grounded or unresolved>"
}
```
No source with `published_utc` **or** `acquired_utc` after the requested paper replay decision time T is eligible under the current strict historical replay protocol. A present-day download of a 2025 filing is **not** evidence that *this system* had that document then. To permit archival reconstruction rather than strict replay, define and preregister a separate evidence regime explicitly; do not silently change the current gate.

The runnable `scratch/baselineA/m3_event_provenance.py` implements **source eligibility only**, not interpretation. It never outputs `verified_event=true` or an order. SEC `form` and `items` are retrieval hints; `issuer_cik` must be corroborated from the source, and a fixed-price merger must identify **target versus buyer** and pending versus completed status. Exchange trading halts require an exchange-time source; SEC alone does not prove complete halt coverage.

## 4. Independent adjudication / truth labels
Truth owner `paper_truth_review`. Every reviewed issuer/event/month must record two reviewer ids, timestamps, review agreement or an explicit adjudicator, evidence ids and independently labelled status:
- `confirmed_critical`: material real event with documentary context and event effective/published time.
- `confirmed_noncritical`: real source event, not material enough for registered risk label.
- `non_event`: **only when independently audited source coverage is sufficient** for that issuer, event type and T interval.
- `unknown`: incomplete or inaccessible sources, unresolved identity, effective date or active status.
- `insufficient_evidence`: claims with citation or quote mismatch, unclear provenance or contradictory sources.

For each event retain: first-public timestamp, first-eligible-detection timestamp, event/issuer/role, primary excerpts, withdrawn/superseded history, eventual outcome, evidence completeness and whether **a potentially profitable purchase would have been wrongly blocked**. In forward tests reviewers must freeze the truth sample protocol before seeing Qwen output. If a reviewer disagrees, never collapse to `non_event` or `confirmed_critical` silently.

## 5. Counts and promotion guard
Always publish `eligible_snapshot_count`, `distinct_issuer_count`, `timestamped_source_coverage_by_type`, `verified_event_opportunity_count`, `negative_control_opportunity_count`, `not_testable_count`, `false_alarm_count`, `missed_critical_event_count` and `missed_winner_cost`. Counts for opportunity detection must be independent of both model output and deterministic suggestions; stratify all confidence intervals by opportunity sampling.

In historical 2025 Q4, the local archive is insufficient: 180 nominated snapshot rows, 88 unique CIKs, 42 rows referencing readable submissions, 138 without a readable submission and all 18 readable CIK caches acquired after 2025-12; 5 retrieval hints in those caches, 0 matching saved primary/exhibit documents, **0 independently verified events**. Those 5 hints MUST NOT be reported as critical events, and the 138 uncovered snapshots MUST NOT be counted as `non_event`.

**Promotion remains blocked:** first independently adjudicate real event and negative opportunities with verified time coverage, then evaluate deterministic B alone, then compare Qwen-C in **shadow observation** mode. A20-event score on hand-picked positives cannot validate 90% sensitivity or the false-positive cost. No automated buy pause or sale from this registry.
