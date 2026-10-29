# CROSS_CHECK_N: pre-GPU cross-check of 3N (Opus 5.5, independent reviewer, 2026-10-29)

**Scope.** The qwen_c v3 diff `bac4cf8..a252f6e` (worktree `wt-m3n`, branch `review-2026-10/m3n`); the 3N tools in `scratch/rev23/m3n/`; the frozen truth (`truth_events.json` f80ec918…, `truth_controls.json` ab5906ce…, hashes recomputed and equal to LOG and `FROZEN_sha256.txt`); the label records; the 86 built DEV packets in `wt-m3n/cache/m3n/packets`.

**How.** Read-only. No GPU, no Ollama, no network, no repository change. Every measurement was run from my own scratch directory against the stored SEC responses, the packets and `git log`/`git show`/`git rev-parse` on the stock-screener checkout.

**FRESH disclosure.** To audit the truth file I read FRESH truth records and one FRESH queue record (C6-187-WS). No FRESH packet was built, run or read, and no model output exists.

## Verdict

**REJECTED for the DEV GPU run as currently frozen.**

It becomes **APPROVED WITH CONDITIONS** once findings 1–3 are closed. None of them needs GPU time or a qwen_c code change. Finding 4 (a builder defect) is strongly recommended before the run: a builder change made after DEV is scored unseals FRESH and forces a DEV rerun (SPEC §7).

## Findings

### 1. BLOCKER: "source in packet" is defined by accession; it must be defined by text

**Where:**
- SPEC §6.1 (outcomes `missed_in_evidence` / `not_in_packet`, condition 3);
- PREREG `scoring.strict_detection` (line 85) and `t1_outcomes` (line 87);
- the truth has no in-packet field (`truth_build.py:86-89`), although SPEC §4.5 asks for it before any run.

**Failing cases (measured on the DEV T1 packets):**
- **C2-24-SBLX.** The anchor accession 0001493152-26-013650 is carried by F1–F3 and P1–P3. The words "substantial doubt" occur nowhere in the packet. The doubt sentence sits at character 313,820 of the 426,103-character 10-K, beyond the 20k/30k/30k section caps.
- **C7-43-YEXT.** The anchor accession is carried by P6 (the release slot, EX-99.1). The suspension sentence is in EX-99.2, which the release slot never reads.
- **C3-04-OPTU.** No item carries the anchor at all (see finding 4).

**What the frozen quote shows elsewhere:**
- The quote is found verbatim in an anchor item for 20 of 23 DEV events at T1, and for 19 at T2.
- At T2, C4-03-FFAI's 3.01 8-K is crowded out of the four other-8-K slots. The same notice is restated in a later accession: P4, an 8-K release, says "On March 20, 2026, the Company received a Nasdaq deficiency notice…".

**Effect on the numbers:**
- Under the accession rule, SBLX and YEXT count as model misses. With 18 detections, model recall would read 18/22 = 0.82 instead of 18/20 = 0.90, which is exactly at the 0.90 bar.
- Lenient detection would accept a `going_concern_doubt` claim that cites only a 10-Q balance sheet, because F1 carries the accession.

**Fix.** Freeze, for each DEV event and each T (T1, T2), before the run:
- `in_packet` ∈ {`exact` (the fact_ids whose text contains the normalised frozen quote), `equivalent` (fact_id plus quote of a reviewer-identified statement of the same event in a later accession, as for FFAI T2 P4), `absent`};
- condition 3 becomes: the claim's fact_ids include an item listed for that event at that T;
- `missed_in_evidence` requires `in_packet` ≠ `absent`;
- baseline B uses the same item list (S9).

### 2. BLOCKER: C7-43-YEXT (DEV) has the wrong first-public anchor, and fails eligibility at the right one

**Where:** `r1/labels.jsonl` C7-43-YEXT (anchor 0001628280-26-039786); `truth_events.json`.

**The failing case:**
- The anchor's own EX-99.2 (the Q1 FY27 shareholder letter, in the case folder) says: "In our fourth quarter letter, we set out a framework … We told you we would … suspend forward guidance and quarterly earnings calls".
- The fourth-quarter letter is 8-K 0001628280-26-016005: items 2.02 and 9.01, acceptanceDateTime 2026-03-09T20:05:57Z. It is not stored, and neither r1 nor r2 read it.

**What the earlier anchor gives:**
- T1 = 2026-03-11T13:30Z under the policy;
- the frame is d327fe8e, the 2025-12-14 snapshot with 1,991 rows;
- **YEXT is not in it** (measured). The T0 build at 2026-04-04 was refused `ticker_not_in_stocks` for the same reason.
- Under amendment 2(b) the event is therefore `not_in_frame_at_anchor` and is not sampled.

**Fix:**
1. Fetch and read 0001628280-26-016005 to confirm.
2. Record r1's superseding label `not_in_frame_at_anchor`.
3. Re-run `truth_build.py`. C7 then holds QDEL (DEV) and BWEN (FRESH).
4. Re-freeze and re-log the hashes, and drop YEXT's three packets from the run list.

### 3. BLOCKER: scoring rules that two people would compute differently

**Where:** SPEC §6.1–6.5; PREREG `scoring`.

**Failing cases:** each of S2–S10 below has one.
- PAACU and ACNT have truth `status` null, so condition 4 cannot be evaluated.
- C6-72-LSTA's T1 packet describes a merger that was terminated before T1, and no rule says how a pending-acquisition claim on it is classed.
- No rule says which seed, packets or population precision, lag, kappa and McNemar use.

**Fix:** write a dated amendment with S1–S10 (end of this file) before the first DEV run. By the SPEC's own rule, scoring changes only before the affected runs exist.

### 4. FIX (strongly recommended before the run): the packet builder drops 8-Ks that carry Item 2.02

**Where:** `qwen_c/packet.py:856-870` (`rel_acc` keeps the release-slot 8-K out of `other_8k`) and `sec_primary.py:680` (`_release_doc` reads only EX-99.1, EX-99.01 or EX-99).

**Failing cases:**
- **C3-04-OPTU (DEV).** 8-K 0001702780-26-000057 has items 2.02, 4.02 and 9.01 and no EX-99. It produces `release_exhibit_not_found`, so it yields no item; and `rel_acc` bars it from `other_8k`. The 4.02 non-reliance text is in neither the T1 nor the T2 packet, and the only annotation names a missing release, not the dropped 4.02.
- **C7-43-YEXT.** The 8.01 body and the EX-99.2 of a 2.02 8-K are never read.

**FRESH exposure:** C5-98-RAMP and C5-123-MCW (1.01 together with 2.02) and C7-31-BWEN (2.02).

**Other gaps:**
- No test covers this path (grep of `test_packet.py`).
- Item 7.01 is not in `OTHER_8K_ITEMS` (`packet.py:97`), so an event published only in a 7.01 release, such as a guidance withdrawal, can never be in evidence. SPEC §3 fixed the same gap for 1.02.

**Fix — builder v5:**
- an 8-K chosen for the release slot also yields an `other_8k` item for its listed non-2.02 items (the body from the first such heading, plus its EX-99.x);
- `_release` reads every EX-99.x up to the cap;
- add 7.01 to `OTHER_8K_ITEMS`;
- add tests, rebuild the DEV packets offline from the store, and re-freeze.

### 5. FIX (before the run): the controls' truth window does not cover the controls' packets

**Where:** `review_build.py:137-142`. Control folders hold only filings accepted in [T−180d, T]; the packet's annual sections come from the latest 10-K, whatever its age.

**Measured:**
- 8 of 24 DEV control packets take 58–72% of their evidence characters from a 10-K effective before T−180d, which the reviewers never saw: K03-GNK, K09-ARW, K11-SSRM, K15-DSGR, K17-STXS, K21-SSTK, K43-MGYR, K47-FLUT.
- That is 29% of all control evidence characters.
- These include **5 of the 9 clean controls**, and those 9 form the whole headline false-alarm denominator.

**Example:** baseline B's only control false alarm, K11-SSRM C8, is risk-factor boilerplate in that unseen 10-K of 2025-02-20.

**Risk:** a true claim about an event shown only in such a 10-K is scored as a false alarm.

**Fix:** either:
- (preferred) second-review the exact old 10-K sections of those 8 packets before the run and update the labels; or
- adjudicate every critical claim on a control under S5.

### 6. FIX (decide before the run): the draw is not "one event per issuer, in class order C1–C8"

**Where:**
- `draw.py:254` and `draw.py:314` skip an issuer once it is *queued* in any class;
- `draw.py:363-365` loads the queued issuers of every class before a `--more` extension.

**Measured:**
- 86 candidates were skipped before their class's last sampled position by a queue entry that is not a confirmed event: C2 2, C5 1, C6 24, C7 28 (over its exhausted pool), C8 31.
- 5 C2 extension candidates were blocked by **later** classes, all before the 6th sampled C2 event (draw position 151):

| C2 draw position | Issuer | Blocked by |
|---|---|---|
| 72 | ALT5 Sigma | C4 |
| 92 | Clean Energy Technologies | C3 |
| 107 | Allbirds | C6 |
| 122 | American Shared Hospital Services | C3 |
| 136 | Optimum Communications | C3 |

**Why it matters:** CETY and OPTU are sampled C3 events, and OPTU is in DEV. A confirmed C2 event at those positions would move them into C2 and change the DEV/FRESH parity in both C2 and C3.

**Fix:** either:
- (a) label the 5 C2 class-order candidates and the 28 C7 candidates (C7 is short of its target), then re-derive the sample; or
- (b) record the implemented rule ("one queued candidate per issuer, first queued wins") by amendment, and report it as a deviation.

### 7. FIX (before the run): C7 is short of its target, and most of its non_event labels were read once

**Where:** amendment 4 rule 3; `adjudication/r2_all.json`.

**Measured:**
- Reviewer 2 saw 23 of the 101 C7 cases, of which 20 are r1 `non_event` labels. The other **78 of 98** rest on reviewer 1 alone.
- Reviewer 1 screened with keyword aids (`r1_view.py`, `r1_controls.py`).
- The full C8 review shows that screen missed a real default in 9 of 124 C8 non_events: 3 in the window (MEHA, ACNT, SURG) and 6 before it.

**Why it matters:** C7 exhausted its pool with 3 events, so any miss changes C7's size and its parity.

**Fix:** second-review all 98 C7 non_events (and the 28 blocked candidates of finding 6) before the run.

### 8. FIX (in the re-freeze): truth records keep r1's fields where the resolution overrode r1

**Where:** `truth_build.py:50-51,89`. `status` and `quote` come from r1; the `r1` field comes from r1's *last* line.

**Failing records:**
- C2-40-PAACU and C8-19-ACNT (DEV), and C8-16-MEHA and C8-98-SURG (FRESH), have `quote` null and `status` null, because r1's label was `non_event`.
- C2-24-SBLX shows `r1 = confirmed_critical`, but r1's blind label was `confirmed_noncritical`; the confirmed_critical line was written after adjudication, at 06:18:40Z.

**Fix:**
- take quote, file, status and event date from the final label's source: the resolution, or else r2 when r2's label is the final one;
- record `r1_blind` (r1's first line) and `r1_final` separately;
- compute agreement from `r1_blind`.

### 9. FIX (before FRESH; fold into the re-freeze): C6-187-WS is not a frame member

**Where:** `draw.py:147` splits cover cells on whitespace; `truth_build.py:84` re-checks only that the symbol is present.

**The failing case:**
- Allurion Technologies (CIK 0001964979) has cover cells "ALUR" and "ALUR WS" (its warrants).
- The split produced a bogus "WS", which matched Worthington Steel. The frame's cik_map gives WS → 0001968487.
- ALUR itself is not in the frame.
- The queue verdict was `needs_review`, but reviewer 1 recorded no membership ruling, and r1's note "flagged for adjudication" was never adjudicated.

**Fix:**
- label the case `not_in_frame`; the sixth C6 event becomes C6-206-RIGL, after checking its membership;
- make `truth_build.py` re-check names and the cik_map cross-check;
- record a membership ruling for every sampled `needs_review` case. C3-01-SDEV's truncated frame name is fine.

The builder's `cik_conflict` refusal would have stopped this case at FRESH build time.

### 10. FIX (before the run): C6-01-XNCR's first-public time is not verified

**Where:** `r1_anchor.py:18,34`. For C1, C3, C4, C5, C6 and C8 it lists only filings that carry the class's own item code.

**The failing case:**
- The 1.02 8-K says the notice was received on March 4, 2026.
- The issuer filed an 8-K with items 7.01 and 9.01 (0001326732-26-000021) at 2026-03-04T21:01Z. It is not stored and was not read.
- If that release disclosed the termination, the first-public time moves 5 days earlier. The frame stays d327fe8e.

**Fix:**
- read 0001326732-26-000021;
- for every sampled event, sweep every 8-K and periodic report in the 30 days before the anchor for the event's words. This sweep would also have caught YEXT.

### 11. FIX: first-public times are 4–5 hours late, and T1 is a session late for 27 of 45 events

**Where:** `packet.py:141-151`. `accepted_at` takes the later of the two readings of the clock.

**Measured against the SEC header's ACCEPTANCE-DATETIME (Eastern):**

| Filing | Header (Eastern) | In UTC | Submissions raw |
|---|---|---|---|
| SNYR | 20260904195013 (EDT) | 23:50:13Z | 23:50:13Z |
| FATBP | 20260127062227 (EST) | 11:22:27Z | 11:22:27Z |
| YEXT | 20260602160558 (EDT) | 20:05:58Z | 20:05:58Z |

**What follows:**
- The submissions "Z" clock is true UTC.
- So every truth `first_public_utc` is 4 hours (EDT) or 5 hours (EST) late.
- T1 is one session later than the true clock gives for **27 of 45 events (15 of 23 DEV)**.
- This is not leakage: the policy is conservative, and it is frozen.

**Fix:**
- keep T1 as frozen;
- add `first_public_true_utc` (the raw value);
- report lag from the true time, and state the one-session policy delay;
- send a dated note to the owner of the acceptance policy. Any change to the policy is a separate, versioned decision.

### 12. FIX (decide before the run): early warning at T0 has no control baseline

**Where:** SPEC §6.4 compares against "the same measure on the controls", but `risks` is not scheduled on controls (SPEC §5.3; PREREG line 83).

**Measured:** 7 of the 23 DEV T0 builds were refused (3 `no_frame_commit`, 4 `ticker_not_in_stocks`), so T0 has n = 16.

**Fix:** either run `risks` on the 24 DEV controls (about 48 tasks, roughly 1.6 hours), or strike the comparison by amendment.

### 13. FIX (carriable): K03-GNK was built with the pre-fix packet code

**Measured:**
- Its `builder_code.packet.py` is c885951… (code at 0afe377). The other 85 packets have 1b2fd4e5….
- Replay at HEAD reports it not identical, first difference `$.builder_code.packet.py`.
- SNYR, FATBP, OPTU and HPI replay byte-identical offline.

**Fix:** rebuild GNK at HEAD into a fresh root (`save()` refuses to overwrite) and run that copy, or record that its replay is at 0afe377.

### 14. NOTE: the frame list uses git's default history simplification

**Where:** `frame.py:72`.

**Measured:**
- It lists 274 commits; `--full-history` lists 375, including 28 non-merge commits that changed stocks.json.
- The frame commit would differ for 7 of 91 packets, but the stocks.json blob is identical in every case.
- No truth or control frame changes content (0 of 93).

**Also:** `n5_packets.py:68`'s "frame assertion" compares the commit a build used with the commit it was given, so it can never fail.

**Recommendation:** recompute `frame_at(T)` independently in the driver.

### 15. NOTE: baseline B is strong on this DEV set

- **Events:** at T1, B detects 19 of the 20 events whose text is in the packet. It misses C5-115-SYNA because onsemi's agreement is an "Agreement and Plan of Reorganization", not "of Merger".
- **Controls:** its only control false alarm is K11-SSRM C8.
- **Comparison:** with N ≤ 3 per class, a per-class McNemar test is degenerate; report it pooled.

### 16. NOTE: thin and peculiar strata

- **Headline false-alarm denominator.** 9 clean controls; 0 of 9 gives a Wilson upper bound of 0.30.
- **C2.** 2 of the 3 DEV C2 events are SPAC units whose doubt is mandatory-liquidation boilerplate (ORIQU, PAACU), and SBLX is not in the packet.
- **C7.** DEV has n = 1 after finding 2.
- **Rule-literal criticals of low materiality:**
  - ACNT: a waived technical default caused by share repurchases;
  - XNCR: an expected administrative termination, after Roche dropped the only product in January 2025;
  - LMNR: the buyer used a due-diligence walk-away right in an asset sale;
  - LSTA: a termination on the target side, which mixes C5 and C6.

Report these strata separately.

### 17. NOTE: strict detection depends on listing every number

**Contract probe on the SNYR T1 packet:**
- "filed … under Chapter 11" with an empty `numbers` list gives `number_not_listed`;
- with "11" listed, or with no number in the claim, it is `supported`.

**Recommendation:** report the support-failure causes among lenient detections (SPEC §6.6).

### 18. NOTE: four controls with little or no evidence

- K01-HPI and K25-DLY are closed-end funds with S0-only packets and `unknown` labels for every class; they enter no denominator. Skip them (4 tasks).
- K35-TRX and K41-BN (40-F/6-K filers) are `unknown` for six classes.

### 19. NOTE: FRESH hazards (no action needed before DEV)

- C1-08-LESL's T2 (2026-10-30T13:30Z) is later than today and later than the pinned frame tip (2026-10-29T01:13Z).
- The anchors of C6-17-ATYR and C8-98-SURG are earlier 10-Qs that r2 did not read.

### 20. NOTE: AUDIT_N2 condition 3 misstates where the runs are recorded

It says the 3N runs use `wt-m3n/cache/m3n`. The runner has no root option and writes to `wt-m3n/cache/m3m/runs` and `ledger.jsonl` (`runner.py:81,527`). This is harmless, because `thesis_change` is not requested.

### 21. NOTE: check output length in the smoke run

`material_events` over about 80k characters of 10-K sections may list many past events. In the smoke run, check `done_reason` and `eval_count` on the largest DEV packet, C1-01-FATBP (15 items).

## What I checked and found correct

**qwen_c v3:**
- Test suite: **363 passed** (179 s): the 362 of RR_N2 plus one test added by a252f6e. The working tree is clean.
- Archival regime: the refusals (`frame_commit_after_T` checked before blobs, `stocks_json_absent`, `cik_conflict`, `no_cik`, `cik_invalid`, `argument_not_for_regime`) and the header (`regime`, `screener_commit_verified: false`, `commit_time_utc`, `verified_row: null`, `cik_source`) are as WO_N2 specifies.
- Item 1.02 is in the packet, and the builder is v4.
- Runner: `--tasks` and `--seed-base` work; `material_events` has seeds 1007 and 3007, and `risks` has 1004 and 3004.
- Contract v2: `EVENT_TYPES` and `EVENT_STATUSES` are right, and the citation checks are unchanged.
- a252f6e is correct for any T the calendar admits.

**Leakage:**
- All 896 evidence items of the 86 packets are effective at or before T and were truly accepted at least 22.7 hours before T.
- Every S0 frame commit predates T.
- `excluded` is never rendered.
- Nothing from today's submissions JSON is rendered: no current name, current ticker or former name.
- The header ticker is the frame symbol, and the 8-K cover page is cut.
- The frame's content dates agree with its commit times; the apparent "later" `Last_Updated` values are stamped in KST.

**Packets:** for all 86, T, frame commit and CIK match the truth; there are 0 `cik_conflict` refusals across 39 cik_map packets; only C4-03-FFAI T0 was trimmed.

**Truth file:**
- The 45-event sample and its DEV/FRESH parity reproduce exactly from `r1/labels.jsonl` and `resolutions.jsonl`.
- No control issuer is also an event issuer, and no excluded ticker is present.
- The frame ref sha 92592e21 equals `origin/main`.

**Draw and controls:**
- Amendment 2 (one ticket per issuer and class, chosen by earliest candidate) and amendment 3 (the reporting-document filter for C7/C8) are implemented.
- `controls.py` follows PREREG and amendment 1.
- The v1 controls fingerprint is f24a34b6, as RR_N3 recorded.

**Baseline B:**
- It applies the PREREG patterns exactly, with a sha256 guard, `re.I | re.S`, per evidence item, with S0 excluded.

**Spot-checks of DEV events** (quote verbatim in the folder, class rule met, inside the window):

| Class | Cases | Anchor |
|---|---|---|
| C1 | SNYR | correct |
| C2 | ORIQU, SBLX, PAACU (prior reports read: no doubt, and doubt "no longer exists") | correct |
| C3 | OPTU | correct |
| C4 | AIFC (a new 30-day bid-price deficiency; the 2025-12-03 notice is earlier) | correct |
| C5 | SYNA | correct |
| C6 | LSTA, LMNR (the earlier 1.02 concerns another agreement) | correct |
| C6 | XNCR | unverified (finding 10) |
| C7 | YEXT | wrong (finding 2) |
| C8 | ACNT | correct |

**Spot-checks of DEV controls:**
- K07-TDY (the folder covers the packet's 10-K);
- K23-IMDX (the 10-K concludes there is no doubt);
- K37-COOK (an NYSE 802.01C notice);
- K47-FLUT (a guidance cut, not a withdrawal);
- K45-ECHO and K21-SSTK, whose labels are consistent with "presence at T".

## Proposed scoring amendment

**S1. Source in packet.** As in finding 1: `in_packet` ∈ {`exact`, `equivalent`, `absent`} per event and per T (T1, T2), with the item list, frozen before the run.

**S2. Condition 3.** The claim's fact_ids include an item listed for that event at that T.

**S3. Status.**
- Status never disqualifies a claim, except when the truth records the event as cancelled, terminated or cured at or before T. Then a claim that it is pending or in force is a false alarm.
- Add a `cancelled_at` field to the truth (null for every current event; check it at T2).
- A null `status` in the truth is not allowed.

**S4. Claims on event packets of a critical type other than the event's own.** Adjudicate from the cited item's text only, blind to the seed, and before recall is computed:

| Category | When |
|---|---|
| `true_other_event` | the text meets that class's PREREG critical rule, and the event is in force at T |
| `same_event_wrong_class` | the claim describes the truth event under another critical type. It counts as a miss for recall and as `wrong_class` in the taxonomy, not as a false alarm |
| `false_alarm` | conditional or risk-factor language, another entity, an event cancelled before T stated as pending, or a non-critical event under a critical type |
| `unclear` | none of the above can be settled |

Example: on C6-72-LSTA at T1, "acquisition_of_the_company, announced_pending" is a `false_alarm`, because the merger was terminated on 2026-07-24.

**S5. Critical claims on controls.** Every one is adjudicated from its cited text:

| Category | Treatment |
|---|---|
| `false_alarm` | counts |
| `true_in_window` | a truth gap: recorded, and the control leaves that class's denominator |
| `past_event` | the event ended, or was cured, before T−180d. It counts as a false alarm under SPEC §7 ("false alarm from a past … event"), but is reported separately. The lead may instead rule it is not a false alarm, but must rule before the run |
| `unclear` | the control leaves that class's denominator |

The `non_event` label of a control means "a claim of this class's event type at T would be false". The resolutions already apply this: K23-IMDX and K47-FLUT stay in the denominator; K05-CAIIU, K29-NCL and K31-MKLYR leave it.

**S6. Precision.**
- Population: claims on T1 and T2 event packets and on controls, primary seed.
- Numerator: detections, `true_other_event` claims, same-class claims that cite an event item, and true claims on a control that is `confirmed_critical` for that class (for example K45-ECHO, C1).
- Denominator: every claim of a critical type.
- Also report precision per (packet, class).

**S7. Lag.**
- Report it in XNYS sessions and in hours, measured from `first_public_true_utc`.
- Report the categories `detected@T1`, `detected@T2 only`, `missed` and `not_in_packet`.

**S8. Seeds.**
- The primary seed base is 1000, so `material_events` uses task seed 1007.
- Seed spread is computed over the events in the model-recall denominator where both seeds' runs are ok.
- Report kappa only when both verdicts occur under both seeds; otherwise report "n/a" with the 2×2 table.

**S9. Baseline B.**
- A detection is a hit of the class in an item listed for the event at that T (S2).
- A false alarm on a control is a hit of class Ck on a control that is `non_event` for Ck.
- B's hits of other classes on event packets are reported as counts, not adjudicated.
- McNemar's exact test is run on the model-recall denominator, pooled; per class it is descriptive only.

**S10. run_incomplete.**
- A task that is not ok after the runner's own retry.
- No manual rerun, except an `infra_error` rerun with the same seed, which is recorded; the first ok run counts.

## Fix list

| # | Item | Blocking / carriable | Owner |
|---|---|---|---|
| 1 | Text-based `in_packet` per event at T1 and T2, frozen | blocking | lead (Claude) |
| 2 | Re-anchor C7-43-YEXT, record `not_in_frame_at_anchor`, re-derive, re-freeze, re-log | blocking | lead |
| 3 | Scoring amendment S1–S10, dated and hashed | blocking | lead |
| 4 | Builder v5 (2.02 co-items, all EX-99.x, 7.01), tests, offline rebuild | carriable, strongly recommended before the run | qwen_c builder (lead assigns) |
| 5 | Re-review the old 10-K sections of 8 controls, or rely on S5 adjudication | carriable, decide before the run | lead, with a fresh r2 |
| 6 | Draw rule: label the 5 C2 and 28 C7 blocked candidates, or record the deviation by amendment | carriable, decide before the run | lead |
| 7 | Full second review of C7 | carriable, before the run if C7 is to count | fresh Sonnet r2 |
| 8 | Truth fields from the final label's source; `r1_blind` | blocking within item 2's re-freeze | lead |
| 9 | C6-187-WS → not in frame; RIGL; name re-check in truth_build | carriable, before FRESH | lead |
| 10 | Read XNCR 0001326732-26-000021; anchor sweep over all sampled events | carriable, before the run | lead |
| 11 | `first_public_true_utc`; note to the policy owner | carriable | lead |
| 12 | T0: run `risks` on controls, or strike the comparison | carriable, decide before the run | lead |
| 13 | Rebuild K03-GNK at HEAD | carriable | lead |
| 14 | Independent `frame_at` check in the driver; full-history list | carriable | lead |
