# SPEC 3N: Qwen accuracy and risk validation (v1, 2026-10-29)

**Status:** design and **pre-registration**.
- Written before any truth label is set and before any 3N model output exists.
- What §4 to §7 fix may change only by a dated amendment written before the affected labels or runs exist.
- Owner: Claude, lead and executor, under the operator's standing go of 2026-10-29.

## 0. What 3N must answer (PLAN §3N)

1. When a material event happens to an eligible company, does Qwen report it from the evidence it is given? This gives recall per class, with uncertainty.
2. How often does it report a material event that did not happen? This is the false-alarm rate.
3. How late does it report it? This is the detection lag.
4. Does Qwen do better than a deterministic check on the same evidence?
5. Are its claims supported by primary sources? This is the support rate of material claims.

Qwen keeps its mandatory role whatever the answers are. No answer grants it trading authority.

## 1. Inventory facts this design rests on

All are from the 3N inventory of 2026-10-29.

- **The model's knowledge cutoff.** `rs2-analyst-deep-mtp5-v33` is Qwen 3.8 27B. Its knowledge cutoff is about mid-April 2025, with thin leakage to 2025-08 (`scratch/qwen_cutoff/REPORT_cutoff.md`). The rule recorded there: use dates from 2025-10 onward.
- **The 18/20 strict-recall reference.** It is a pre-registered *bar* from Phase 6 (`PHASE_6_FOLLOWUP_RECALL.md`), not a result.
  - Muse scored 6/20 strict on news-only events.
  - Qwen was never scored.
  - Those 20 events are not reusable: re-running the same set is not valid evidence, and none of them is a filing event.
- **Holdouts.**
  - The Revision 26 untouched holdout is **CTVA, NHC, TTAM and CLDT**. It is excluded here.
  - The Gate 1 and Gate 1b holdouts are factor-stage month-ends, unrelated to this test.
- **What exists.** The 3B schema (`SCHEMA_m3b_event_truth_2026-10-24.md`) gives the label vocabulary and the disjoint-datasets rule. It has no rows.
- **What does not exist:** an event scorer, and any deterministic check that reads filing text for going concern, covenant default or guidance withdrawal.
- **The screener's git history.** `stocks.json` exists in stock-screener's history from one commit on 2025-12-14 (1,991 rows), then from 2026-04-05 on (7,012 rows by October). `cik_map.json` exists only from 2026-06. Before 2025-12-14 there is no screener record at all.
- **The verified screener commits.** The 3M packet requires a screener commit verified PASS with pair PASS whose run ended by T. No such commit exists before about 2026-10-28, because the pair check fails before the `3094` fix. A historical T cannot be built under the 3M regime.

## 2. Two evidence regimes

**R-A `archival_sec_acceptance_v1`** (historical; this spec's main test).
- **What counts as evidence:** only SEC EDGAR documents whose acceptance time is before T, under the 3M acceptance rule.
  - An accession's bytes are immutable once accepted. An amendment is a new accession, with its own acceptance time.
  - The documents are fetched today. That makes this **archival reconstruction**, not a replay of what this system held at T.
- **What it measures:** Qwen's accuracy on what was public at T. It is **never** evidence about this system's history or point-in-time record (3B schema §3; 3L).
- **The screener commit.** S0 comes from the last screener git commit whose committer time is at or before T. The packet records it as `regime: archival_sec_acceptance_v1` and `screener_commit_verified: false`, with that commit's time.
  - The pair and witness verification of 3M is replaced by that annotation. This is not a relaxation of the gate: it is a different regime, declared here.
- **The universe at T** is that same commit's `stocks.json` (§4.1).
- **The repository** is the stock-screener development checkout, read-only through `git show`. `screener-publish` is a shallow clone, and its history starts at 2026-08-26.

**R-P `prospective_v1`** (from 2026-10-29 on).
- 3M packets exactly as built, with verified commits.
- Events that occur from now on in the screener's book go to a forward register (§4.6).
- This regime is too young to give 20 events. It runs alongside R-A and is reported separately.

## 3. The task added to qwen_c: `material_events` (prompt v3, contract v2)

The existing `risks` task lists *possible* risks. It cannot say that something *has happened*, so it cannot be scored for detection or false alarms. A new task is added. It is a versioned change:
- `PROMPT_VERSION m3m.prompt.v3`;
- `CONTRACT m3m.analysis.v2`;
- the v1 and v2 pins are kept.

**The wording.** The task asks for every material event that the evidence shows **has occurred or has been formally announced**, one claim per event. Each claim gives:
- `event_type`, one of:

| event_type | Meaning |
|---|---|
| bankruptcy_or_restructuring | bankruptcy or restructuring |
| going_concern_doubt | substantial doubt about continuing as a going concern |
| restatement_or_non_reliance | a restatement, or prior statements that may no longer be relied on |
| delisting_notice | a notice of delisting or non-compliance with listing rules |
| acquisition_of_the_company | the company is being acquired |
| contract_loss | loss or termination of a material contract |
| guidance_withdrawal | guidance withdrawn |
| debt_default_or_acceleration | a debt default, or debt made due early |
| material_impairment | a material impairment |
| auditor_change | a change of auditor |
| trading_halt | a halt in trading |
| other_material_event | any other material event |

- `status`: `occurred` or `announced_pending`;
- `occurred_on`: the date as an item prints it, or `"not stated"`.

**When there is no event,** the reply is no claims and one `unknowns` line saying so. A reply with no claims and no unknowns stays malformed.

**The contract** checks the same citation, quote and figure rules as every other task, and validates the two new enum fields. Nothing else changes.

**The packet** adds 8-K Item **1.02** (termination of a material definitive agreement) to `OTHER_8K_ITEMS`. Without it a contract loss could never be in evidence.
- `BUILDER_VERSION` becomes `m3m.packet.builder.v4`.
- The 3M packets are not rebuilt; they stay the records of v3.

**What the 3N runs execute.** They run `material_events` on every packet, and `risks` on the early-warning packets (§5.3). The full seven-task run stays the production form. The runner gains a `--tasks` option, recorded in the manifest.

## 4. The truth register (built before any 3N model run)

### 4.1 The window, the frame and the classes

**The event window.** The first public time, meaning the SEC acceptance time of the first filing that discloses the event, falls in **2025-12-15 to 2026-09-30**. It starts after the first screener snapshot and is 8 months past the cutoff, which is clear of the leakage band. It ends early enough to leave room for the T2 ladder (§5.1).

**The frame at T is the last stock-screener commit whose committer time is at or before T,** even when that commit is months old: from 2025-12-15 to 2026-04-04, that is the 2025-12-14 snapshot. A stale frame is the screener's universe as it was then known. A later snapshot is never used for an earlier T, because names that failed would have dropped out of it (survivorship).

**Who is eligible.** The issuer is in the frame when the trading symbol on the cover page of the event filing (or of its last periodic report before T) is a `stocks.json` symbol at the frame commit, and the names agree. Disagreements are recorded and resolved by reviewer 1. A present-day ticker map is never used, because tickers are reused and dead names leave it. The frame commit's `cik_map.json` is used where it exists, as a cross-check.

**Excluded:**
- MG, MOV, SENEA and SENEB (operator exclusion);
- the Revision 26 holdout: CTVA, NHC, TTAM and CLDT.

**The critical classes,** with their accepted `event_type` values:

| Class | Accepted event_type | Typical first source |
|---|---|---|
| C1 bankruptcy | bankruptcy_or_restructuring | 8-K 1.03 |
| C2 going concern | going_concern_doubt | 10-Q / 10-K text ("substantial doubt") |
| C3 restatement | restatement_or_non_reliance | 8-K 4.02 |
| C4 delisting | delisting_notice | 8-K 3.01 |
| C5 company acquired (target) | acquisition_of_the_company | 8-K 1.01 merger agreement, or 2.01 completion |
| C6 contract loss | contract_loss | 8-K 1.02, or 1.01/8.01 text |
| C7 guidance withdrawal | guidance_withdrawal | 8-K 2.02/7.01/8.01 release text |
| C8 debt default / acceleration | debt_default_or_acceleration | 8-K 2.04, or 10-Q text |

**Not testable in R-A:**
- **Trading halts:** no exchange-time source is held (3B schema §3).
- **Material impairment** and **auditor change:** recorded as non-critical when found, and not sampled.

### 4.2 Candidate discovery (several channels, each recorded)

**The channels:**
- **(a)** EDGAR full-text search, with fixed queries per class over the window, for example "substantial doubt" "going concern" in 10-Q and 10-K, "withdraw" near "guidance", "event of default", "non-reliance".
- **(b)** 8-K item codes from EDGAR submissions and the D1 index (`data/sec_bulk/index_P4b`).
- **(c)** For C1 and C4 as well, D1's bankruptcy and delisting classes.

Every candidate records `candidate_discovery_channel`. A form code or a search hit creates a **candidate**, never an event.

**The query set, the frame commits and the code** are frozen in `PREREG_m3n.json` before discovery runs.

### 4.3 The draw

- **The seed** is `m3n-2026-10-29`, hashed by sha256 to an integer.
- **From the eligible candidates,** per class in a fixed order, candidates are drawn without replacement and reviewed in draw order, until **6 confirmed_critical events per class** are reached, or the class runs out.
- **At most one event per issuer** across all classes, so no company dominates.
- **The target** is 48 confirmed events. 3N asks for at least 20 in all and reports honestly if fewer exist.
- **The split.** Each confirmed event is assigned DEV or FRESH by its draw order within its class: odd draws go to DEV, even draws to FRESH. **FRESH is sealed.** It is neither run nor read until the first change of prompt, model or contract made after DEV is scored (§7).

### 4.4 The controls

- **Draw.** From the same frames, 48 issuer-dates are drawn at random: the date is uniform over the XNYS sessions of the window, then the row is uniform over the frame commit's `stocks.json`.
- **The CIK** comes from the frame's `cik_map.json` where it exists. Otherwise it comes from an EDGAR company match on the name, checked against the issuer's SEC name at T (including `formerNames`). An unresolved row is replaced by the next draw, and the replacement is recorded. The same seed is used, with the suffix `/controls`. They are split DEV/FRESH by draw parity.
- **Exclusion.** A control is excluded if its issuer has any confirmed or candidate critical event within 180 days before T or 30 days after it. Every exclusion is recorded. An excluded draw is replaced by the next draw.
- **What a control's truth needs.** It is `non_event` for a class only when the reviewers checked every SEC filing of the issuer accepted in [T − 180 days, T]: the 8-K item codes, and the 10-Q and 10-K texts for C2, C7 and C8. Otherwise it is `unknown` for that class.
- **What counts toward false alarms.** Only a control that is `non_event` for every critical class enters the false-alarm denominator.

### 4.5 Adjudication

The 3B schema §4 rules apply.

**The reviewers:**
- **Reviewer 1** is Claude, reading the primary documents.
- **Reviewer 2** is Gemini through `agy`, given the same documents and the label rules, and never reviewer 1's labels or any model output.

**The labels** are `confirmed_critical`, `confirmed_noncritical`, `non_event`, `unknown` and `insufficient_evidence`.
- A disagreement is resolved by Claude with a written reason. A disagreement is never collapsed silently.
- Both labels and the resolution are kept.

**What each event records:**
- issuer and role (subject or target);
- class;
- first public accession and acceptance time;
- the verbatim quote;
- `status` (occurred or announced_pending);
- T1 and T2;
- whether the source is in the T1 packet (filled after the packets are built, before any run).

**The independence limit, stated:** Claude also builds qwen_c. The labels are frozen, with their sha256 recorded in LOG, before the first 3N GPU run.

### 4.6 The forward register (R-P)

Every new 8-K or periodic filing of a `research_now` name from 2026-10-29 on is a candidate, under the same classes and adjudication. It is reported separately.

## 5. The runs

### 5.1 Decision times

| T | When |
|---|---|
| **T1, first eligible** | the effective time of the first public filing, under the acceptance rule `sec_acceptance_next_full_xnys_session_late_after_1730_plus_one_v1` |
| **T2, late** | T1 + 20 XNYS sessions |
| **T0, early warning** | the first public time − 60 calendar days |
| **Controls** | the drawn date at 14:30Z (09:30 New York) |

### 5.2 Seeds

Every packet runs twice: with seeds 1000 + task index, and with seeds 3000 + task index. The first is primary and the second measures spread.

### 5.3 What runs where

- `material_events` runs on T1, T2 and the controls.
- `risks` runs on T0, as an exploratory measure (§6.4).

**Approximate GPU cost for DEV,** at about 2 minutes a task:
- 24 events × (T1 + T2) + 24 controls, which is 72 packets, × 2 seeds: about 5 hours;
- T0, risks only: about 1.6 hours more.

### 5.4 Before the long run

A smoke run of one event and one control, and an outside-AI cross-check of the 3N code first (operator rules of 10-16 and 10-18).

## 6. Scoring (fixed now)

### 6.1 Detection

**An event is detected at T, strictly,** when the T packet's `material_events` reply has a claim that meets all four conditions:
1. its `event_type` is in the class's accepted set;
2. its support is `supported`;
3. its `fact_ids` include the evidence item that carries the event's source accession, or a later accession on the same event;
4. its status is not contradicted by the truth (an announced deal reported as `occurred` still counts; a cancelled event does not).

**Lenient detection** drops condition 2.

**Each event at T1 falls into one of:**
- `detected`;
- `missed_in_evidence` (the source is in the packet, but no qualifying claim);
- `not_in_packet` (the source is not in the packet);
- `run_incomplete` (the task is not ok).

**Recall is reported two ways:**
- **Model recall** = detected / (detected + missed_in_evidence).
- **System recall** = detected / every event (packet gaps included).

Each comes with Wilson 95% intervals, per class and in all, and for each seed.

### 6.2 False alarms

**A false alarm** is a `material_events` claim of a critical `event_type`, of either status, on a packet whose truth is `non_event` for that class at T.

| Measure | Definition |
|---|---|
| Control false-alarm rate | controls with at least one false alarm / clean controls (Wilson 95%) |
| Event-packet false alarms | claims on event packets of a critical class other than the event's own that the truth does not confirm. Adjudicated by Claude after the runs, as `false_alarm`, `true_other_event` (added to the register as `confirmed_*`, never counted as a hit) or `unclear` |
| Precision | true critical claims / all critical claims, over DEV |

### 6.3 Lag and spread

**Lag.** For an event detected at T1, the lag is T1 − first public time, which the acceptance rule fixes. For an event missed at T1 and detected at T2, the lag is T2 − first public. Events missed at both are reported as missed.

**Run-to-run spread.**
- The two seeds' detection verdicts are compared per event: both hit, both miss, or split.
- Recall is reported per seed. The pair's agreement is reported as a percentage and as Cohen's kappa.

### 6.4 Early warning (exploratory, not a pass criterion)

At T0: does `risks` give a risk of the class's mapped `risk_type`?

| Classes | Mapped risk_type |
|---|---|
| C1, C2, C8 | bankruptcy or liquidity_rupture |
| C3 | restatement |
| C4 | delisting |
| C6 | contract_rupture |
| C7 | guidance_withdrawal |
| C5 | other (none) |

It is reported against the same measure on the controls.

### 6.5 The deterministic baseline B (same packet, same evidence budget)

These rules run on the packet text, are written before the runs and are frozen in PREREG:

| Class | Rule |
|---|---|
| C1 | 8-K Item 1.03 |
| C2 | "substantial doubt" within 300 characters of "going concern" |
| C3 | Item 4.02, or "should no longer be relied upon" |
| C4 | Item 3.01, or "notice of delisting" / "not in compliance with … listing" |
| C5 | Item 1.01 or 2.01 text with "Agreement and Plan of Merger" and the company named as the acquired party (a target-role phrase list) |
| C6 | Item 1.02 |
| C7 | "withdr…" within 100 characters of "guidance", "outlook" or "forecast" |
| C8 | Item 2.04, or "event of default" within 300 characters of "occurred", "notice" or "accelerat…" |

B is scored by §6.1 (a rule hit on the source item counts) and §6.2 exactly. Qwen and B are compared per class, with McNemar's test on the paired event verdicts.

### 6.6 Support rate

The `supported` share of all `material_events` claims, and of the claims scored as detections, reported with the cause counts. Rechecking under later contract code is a separate record (3M Amendment 2).

### 6.7 The 18/20 reference

Strict model recall at T1 on DEV is reported with its Wilson interval beside the 0.90 bar (18/20 scaled to N). Meeting it is not a safety guarantee and grants no authority.

## 7. Diagnose, change, retest

- **DEV failures** are put in a failure taxonomy:
  - packet gap;
  - section not found;
  - model missed it in evidence;
  - wrong class;
  - contract false negative;
  - false alarm from boilerplate risk factors;
  - false alarm from a past or other entity's event.
- **Fixes** are systemic, never per ticker. Each fix is a versioned prompt, packet or contract change.
- **After the first such change,** FRESH is unsealed and run once under the changed version. DEV is rerun too, as a regression check.
- **Records:** both are reported; failures and regression tests are kept across versions. A FRESH result is never used to tune and then reported as fresh again. A second change needs a new draw (FRESH-2) from the remaining candidates.

## 8. Pass criteria (PLAN §3N), and what closes 3N

3N closes when all of these are reported, with honest counts:
- the support rate (§6.6);
- recall, precision, false-alarm rate, lag and uncertainty (§6.1–6.3);
- at least 20 independently verified critical event opportunities, or the honest shortfall;
- the 18/20 reference with its intervals (§6.7);
- the comparison with B (§6.5);
- the failure taxonomy and the regression tests (§7).

**3N passes when this measurement is complete and recorded,** whatever the recall is. A low recall is a result, and it changes what authority Qwen may later get (none in 3N). It does not fail the milestone.

## 9. Work orders

| WO | Work |
|---|---|
| N1 | **PREREG_m3n.json**: the seed, windows, frame commit rule, classes, discovery queries, baseline-B patterns, scoring constants. Its sha256 goes in LOG before discovery |
| N2 | **qwen_c v3:** `material_events` task and contract v2, 8-K Item 1.02, the archival regime builder option, the runner `--tasks` option. With tests |
| N3 | **Discovery and frame tools** (scratch `m3n/`): FTS and item-code candidates, the frame from screener git history, the draw |
| N4 | **Adjudication:** reviewer 1 labels; a reviewer-2 packet through `agy`; resolution; the frozen truth file and its sha256 in LOG |
| N5 | **Packets, baseline B, the smoke run, the cross-check, the DEV GPU runs** |
| N6 | **The scorer and RR_N** (the DEV report). Then §7 |
