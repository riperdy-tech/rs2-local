# AUDIT_N4: the 3N truth register (2026-10-29)

The truth set was **frozen before any 3N model run.** The files are in `scratch/rev23/m3n/truth/`, and their hashes are in LOG and in `FROZEN_sha256.txt`:

| File | sha256 |
|---|---|
| `truth_events.json` | `f80ec918…` |
| `truth_controls.json` | `ab5906ce…` |

## What was built

**Discovery (WO_N3, after amendments 2 and 3):**
- 21,247 candidates in total;
- one ticket per (issuer, class);
- the C7 and C8 hits restricted to reporting documents.

**Events.** Reviewer 1 (Claude) read **642 event cases** in draw order.

| Final label (events) | Count |
|---|---|
| `confirmed_critical` | 52 |
| `confirmed_noncritical` | 48 |
| `non_event` | 521 |
| `out_of_window` | 11 |
| `unknown` | 10 |

**The sample:** the first 6 confirmed per class, in draw order. C7 had only **3 in its whole pool** of 208 issuers.

| Set | Size |
|---|---|
| Sampled events | 45 |
| DEV | 23 |
| FRESH (sealed) | 22 |

None was skipped at the anchor check. Membership in the frame was re-checked at each anchor's T1.

**Controls:** 48 drawn under amendment 1. The 24 DEV controls were labelled per class (192 labels).

| Measure | Value |
|---|---|
| Controls clean for all 8 classes | 9 |
| Per-class `non_event` denominators | C1 19, C2 15, C3 20, C4 17, C5 17, C6 17, C7 20, C8 19 |

**Unknown controls:**
- 2 funds: unknown for every class;
- 2 foreign filers whose 6-K exhibits were not captured: unknown for most classes.

## Reviewer agreement and errors (second-reviewed cases)

**Coverage:**
- 332 event cases were second-reviewed: 46 by Gemini, then 286 by Sonnet (amendment 4).
- 176 of the 192 control labels agree on whether the class is a non-event.

**Agreement:** on whether a case is critical, the reviewers agree on **306 of 332 (92.2%)**.

| Reviewer | Errors found by the resolutions |
|---|---|
| Reviewer 1 | **5 misses**, 0 false criticals |
| Reviewer 2 | 1 miss, 20 critical labels not upheld |

**Reviewer 1's misses:**
- **C2:** SBLX and PAACU. My sentence tagger counted "doubt no longer exists" as an assertion, and read the head of the standard SPAC sentence ("In connection with the Company's assessment …") as conditional.
- **C8:** MEHA, ACNT and SURG. My regex screen dropped waived-after-arising defaults, missed maturities, and statements that a default occurred.

**What caught them:**
- C2 had a full second review.
- C8's 20% sample turned up MLCI (an earlier default), which triggered amendment 4's full second review of the C8 prefix.
- After that full review, C8's six changed from ARAI, AXTI, CMCT, DOMO, MFIN and RIME to **ARAI, MEHA, ACNT, AXTI, CMCT and SURG**.

**Reviewer 2's 20 critical labels not upheld:**
- 14 are real events first disclosed before the window. Reviewer 2 was not given the window rule, so these are not reading errors.
- 6 are conditional language, prior-year auditor reports, an immaterial lease, or a de-SPAC.

## Limits

- **C5 to C7 non-events were second-reviewed only by a 20% sample** (amendment 4). The samples found no reviewer-1 miss of a critical event; one immaterial lease was relabelled non-critical. Reviewer 1's error rate in C2 and C8 suggests the unsampled C5 to C7 non-events may hold misses. That would bias which events were sampled, not their truth. This is reported as a limit.
- **Independence:** reviewer 1 is Claude, and so is reviewer 2 for 286 cases. Gemini covered only the first 46.
- **What the labels rest on:** the texts given, which are 8-K bodies, EX-99 exhibits and keyword windows of periodic reports, not every word of every filing. A foreign filer's coverage was too thin, and those classes are `unknown`.
- **The C7 shortfall** (3 events) is a property of the pool. It is reported, not filled.

## Addendum: truth v2 (2026-10-29, after CROSS_CHECK_N; before any model run)

**Re-frozen** as `truth_events.json 728a289d…` (46 events, 23 DEV / 23 FRESH) and `truth_controls.json c3660d8d…`.

**What changed since v1:**
- **The draw rule.** The PREREG rule is one event per issuer, not one queue entry. 91 blocked candidates were requeued, labelled by r1 and fully second-reviewed by r2 (Sonnet), and the sample was re-derived in class order.
- **C7.** All `non_event` labels were second-reviewed. r2 found LXP (a guidance withdrawal); C7 now holds 4 events in its whole pool.
- **Two events left the sample:**
  - YEXT, re-anchored to its March 2026 shareholder letter, is not in the frame;
  - WS: the "ALUR WS" cover cell was split wrongly, so it is not in the frame.
- **The cross-class rule:** AIFC (sharing CIK 862861 with ALTS) and SNBR's C2/C8 events are skipped, because the issuer was already sampled in an earlier class.
- **Review folders:** they missed EX-99 exhibits with unusual file names (`xexx991`, `exh_991`). 6 event cases and 2 controls were rebuilt and re-reviewed; no label changed.
- **Truth fields:** they now come from the final label's source, with `r1_blind` kept apart; there is no null status.
- **Membership:** re-checked with names, allowing for truncation and "/DE" suffixes, and the cik_map.

**Reviewer-1 misses caught by reviewer 2 in this round:** LXP (C7). The 10 new critical events r1 found among the blocked candidates were all confirmed by r2.

**DEV packets** (builder v5): **84 of 84 replay byte-identical offline** (`n5/replay_v5.txt`).
