# SPEC 3P: continuous Qwen thesis monitoring, v1, 2026-10-29 (frozen before any 3P GPU run)

**Status:** v1, FROZEN 2026-10-29. Written during the 3N DEV run, it depends on no 3N result. The open points below were
settled by WO_P1, WO_P2 and WO_P3a (AUDIT_P1, AUDIT_P2, AUDIT_P3a). **Authority:** paper only. Monitoring never sells (operator ruling 2026-10-01,
PHASE_6_FOLLOWUP §1.1). `KIS_HALT`, `DEPTH_PAUSED` and `model_release_blocked=true` stay. SENEA, SENEB, MOV and MG
are never monitored.
**Linked:** PLAN §3P; SPEC_m3o (the books and formation runs it watches); SPEC_m3m (qwen_c, `thesis_change`);
PHASE_6_FOLLOWUP.md (rulings 1–8 and the P6.6 gather design, built for the frozen depth analyst).

## 0. What is reused, and what is not

| Piece | Source | In 3P |
|---|---|---|
| Thesis record | the formation run's `growth_thesis` and `risks` claims (qwen_c `analysis.json`) | the recorded thesis; never rewritten |
| Change comparison | qwen_c `thesis_change` against `find_prior` (with the `035ef96` fix) | the model's comparison step |
| Event read | qwen_c `material_events` | the model's event step |
| Exact-signal floor | baseline B (PREREG_m3n) + 8-K item codes + price crossings | the deterministic floor |
| SEC gather, news gather, seen-sets | PHASE_6_FOLLOWUP P6.6 (`followup_gather.py`, `followup_news`), on branches `phase-6-followup` / `phase-6-on-rev21` only | **decided by WO_P1 (RR_P1, AUDIT_P1): not reused as a module.** `followup_gather.run()` needs a depth verdict per name, writes depth state into a fixed `cache/`, and breaks on the live branch (`sec_guidance.UA` removed in `5b9ccf5`). 3P writes a small gather under `m3p/`, copying the leaf functions `filing_texts`, `normalize_title`, `press_name`, `followup_news` and the 45-day seen-set pruning, with B2's pacing (26 names per batch, 600 s apart) and `sec_ua()` for the SEC contact |
| Daily model read (Muse) | P6.7 | **not reused**: 3P's model is qwen_c on Qwen (PLAN: Qwen is mandatory) |

## 1. The monitored set

- Every name held by an SPEC_m3o arm (F, FB, FQ, F-A1);
- every name of the newest A0 book;
- every name restricted (B1/Q1) at the newest formation.

A name leaves the set 30 days after it leaves all of these.

## 2. Daily gather (no GPU), per name, since the name's last gather

1. **SEC** (independent witness: accession and `acceptanceDateTime`): new filings of the issuer's own CIK. Forms
   8-K and 6-K, with items; 10-K and 10-Q; amendments; NT 10-K and NT 10-Q.
2. **Prices:** daily closes, with the source and quote date.
3. **News:** labelled `secondary`. It may queue a reanalysis. It can never be the only source of an action, because Q1
   needs a supported claim on a primary filing.
4. **Deduplication:**
   - a filing is new by accession;
   - a news item is new by normalised title plus URL, against the name's seen-set;
   - an undated news item is never "new" at the name's first gather (the P6.6 amendment of 2026-10-02).
5. **Cross-issuer guard:**
   - SEC items come only from the issuer's CIK;
   - a news item must name the issuer's distinctive word;
   - a filing naming another issuer as the subject is annotated, not dropped.

## 3. Triggers (deterministic floor; the model can add to it, never cancel it)

| Priority | Trigger |
|---|---|
| P0 | a held name with: an 8-K item in {1.02, 1.03, 2.04, 2.06, 3.01, 4.01, 4.02}, an NT filing, or a B-pattern hit on a new filing |
| P1 | a name of the newest book not yet held, with the same triggers; and new candidates before a formation |
| P2 | a held name with a new 10-K, 10-Q or 8-K Item 2.02 (earnings) |
| P3 | other new 8-Ks (1.01, 2.01, 2.03, 5.02, 7.01, 8.01) or a price move of at least 3 standard deviations of 60-day returns, or 20% in 5 sessions |
| P4 | the scheduled refresh: every monitored name every 14 days with no other run (ruling 3) |

**Order:** priority first; within a priority, by trigger time. A name already queued takes the highest of its
triggers. It is not queued twice.

## 4. Reanalysis

- **The run:** one qwen_c run with packet T = the trigger's effective time.
  - P0–P3: `material_events` and `thesis_change`.
  - P4 and formations: all tasks.
- **The prior:** `find_prior` gives the newest earlier full run. A subset run is never the prior (`035ef96`).
- **Run key:** (CIK, packet sha256, prompt, contract, builder). A key already run is not run again. Packet bytes
  fix the evidence, so the same evidence is never re-read as new.
- **States per thesis point:** `unchanged`, `changed`, `unknown` and `unsupported` stay distinct (`thesis_change`
  contract).
- **States per name:** `thesis_intact`, `thesis_changed`, `event_found` (a Q1-qualifying claim), `pending_review` and
  `stale_analysis`.

## 5. Failure handling

- **A failed or incomplete run** keeps the name's last good analysis and marks the name `pending_review`. Nothing is
  overwritten.
- **Carry limit** (ruling 6): after two unusable runs in a row, or 21 days, the name is `stale_analysis`. In paper this
  is a flag, and the SPEC_m3o arms are unchanged by it. The flag is visible on every report.
- **Infrastructure:**
  - GPU busy or Ollama down: the queue waits and nothing is dropped;
  - a crashed run is found by `read_ledger` (`crashed`) and re-queued once;
  - a duplicate trigger is absorbed by the run key.

## 6. Journal (`m3p/journal.jsonl`, append-only, one line per lifecycle step)

`discovered` (trigger, source ids, times) → `queued` (priority) → `analysed` (run id, manifest sha256) → `resolved`
(the name state, the thesis points' states, a Q1 verdict) or `failed` (cause). Every line names the earlier thesis run
and the dated evidence it was compared against.

## 7. Measures

- **Coverage:** monitored names with a run within 14 days; the queue's age by priority.
- **Missed material events:** a periodic truth review in the 3N way. A reviewer searches EDGAR for the monitored
  names' critical events, independent of the triggers. Did the floor or the model catch each one, and when?
- **False alarms:** `event_found` names whose event the review does not confirm.
- **Reanalysis delay:** from the trigger's SEC acceptance to the resolved line, in hours and XNYS sessions.
- **GPU throughput:** measured runs per hour by task set. The cadence of §3 is checked against it in WO_P3. If the 14-day
  refresh cannot be met, it lags. It never starves P0–P3 (ruling 3).

## 8. Work orders

| WO | What | GPU |
|---|---|---|
| WO_P1 | Read-only inventory: what of P6.5–P6.9 is built and where; can its gather run apart from the depth pipeline, under DEPTH_PAUSED, without writing depth state; the measured runtimes of qwen_c task sets from 3M/3N records | no |
| WO_P2 | Gather + floor + queue + journal (`m3p_monitor.py`), fixture tests, the failure tests of §5 | no |
| WO_P3 | Throughput benchmark on real runs; first live monitoring week on the 10-30 book | yes |

## 9. Points settled for v1

- **P6.6 code:** not reused as a module. A small gather under `m3p/` reuses its leaf functions (§0, AUDIT_P1).
- **Price trigger:** 3 standard deviations of the 60 prior daily log returns, or a 20% move over 5 sessions, with ≥
  at both boundaries. These are design values, recorded as such and not tuned.
- **News:** SearXNG, paced as in B2 (26 names per batch, 600 s apart). In v1 it is gathered, deduplicated (title OR
  URL), labelled secondary and journaled, but it **queues nothing** (AUDIT_P2 ruling 1). It is revisited after the
  first live week.
- **Escalations** (Q1 `undated` and `date_unsupported`): the name becomes `pending_review` until new evidence triggers
  a run (AUDIT_P2 ruling 7).
- **Q1 has one owner:** `m3o_engine.q1`.
- **Full-run time:** unmeasured. The records give about 140 s median per task. WO_P3b measures it.
