# RR_N (DEV): Qwen material-event detection, the DEV half (2026-10-29/30)

**Status:** sections 5–8 were filled 2026-10-30 from `n6/score_dev.json` (`n6_score.py`, `n6_tables.py`, `n6_taxonomy.py`), after all 213 run rows. FFAI T2 seed 3000 failed twice, on output length, and stands as `run_incomplete`. The S4/S5 adjudication is complete: 207 rulings, 0 claims unadjudicated.

## 1. What was measured

Does qwen_c's `material_events` task report a material event the SEC record shows? How often does it report one that did not happen? And how does it compare with deterministic text rules (baseline B) on the same evidence?

- **The model:** `rs2-analyst-deep-mtp5-v33` (Qwen 3.8 27B Q5_K_M, knowledge cutoff about mid-April 2025), served by Ollama 0.40.6 through ollama_raw.
- **The code:** prompt `m3m.prompt.v3`, contract `m3m.analysis.v2` (with the designator exemption, `626e086`), packet builder v5 (`761f640`); branch `review-2026-10/m3n`, pushed.

## 2. The truth (frozen before any model run)

- **The pre-registration:** SPEC_m3n, PREREG_m3n.json and amendments 1–6.
- **The truth set:** `truth_events.json 728a289d…` and `truth_controls.json c3660d8d…`.
- **The events:** 46 SEC-verified events from 2025-12-15 to 2026-09-30, after the model's cutoff, across 8 classes:
  - **C1** bankruptcy;
  - **C2** new going-concern doubt;
  - **C3** restatement / non-reliance;
  - **C4** delisting notice;
  - **C5** company acquired;
  - **C6** contract loss;
  - **C7** guidance withdrawal (the whole pool holds 4);
  - **C8** debt default / acceleration.
- **The split:** DEV is 23 events, chosen by parity of draw order. FRESH holds 23 and stays sealed.
- **The controls:** 24 DEV controls, drawn uniformly from the screener universe at a random session. 9 are clean in all classes; the per-class `non_event` denominators run 15–20.
- **Reviewing:** two reviewers on every sampled event, every resolved case and every control:
  - reviewer 1 is Claude;
  - reviewer 2 is Gemini for 46 cases, then Sonnet, because Gemini's quota ran out (amendment 4).
- **The disagreement record** is in `adjudication/resolutions.jsonl`, and the reviewer error analysis in AUDIT_N4.

## 3. The evidence (packets)

- **Archival regime:** `archival_sec_acceptance_v1`. SEC documents accepted before T under the frozen acceptance rule, downloaded today, and the screener universe as of the last commit at or before T.
- **What it measures:** model accuracy. It is not evidence of what this system held at the time.
- **Packets built:** 84 of 91 DEV packets: every T1 and T2, 22 controls, and 16 of 23 T0. The 7 missing T0 packets fall before the first frame, or the ticker was not yet listed.
- **Replay:** byte-identical offline, 84 of 84.
- **In-packet, frozen before the run** (`in_packet.json beb51493…`):

| | T1 | T2 |
|---|---|---|
| exact | 19 | 18 |
| equivalent | 1 | 1 |
| absent | 3 | 4 |

**The T1 gaps:**
- **ALTS, AMS:** the going-concern text is in the financial-statement notes, which the packet does not carry.
- **QVCGA:** the Item 2.04 text is cut off by the 4,000-character 8-K body cap.

Builder v7 (WO_N6, then the CROSS_CHECK_O 6a trim fix; AUDIT_N6 and its addendum; not applied to the DEV runs) carries all three in an offline rebuild of the 84 DEV packets, with no case lost against v5 (`n7/regression_v7.json`: exact 37 to 43, absent 7 to 2). The DEV regression rerun uses v7.

## 4. The runs

- **Tasks:**
  - `material_events` at T1, T2 and on the controls;
  - `risks` at T0 and on the controls.
- **Seeds:** base 1000 (primary) and 3000 (spread).
- **Scale:** 212 tasks, through the scheduled task RS2-M3N-DEV-Runner, outside any Claude session.
- **The smoke run** (FATBP plus control GNK) found a contract false negative: "Chapter 11" counted as an unlisted figure. It was fixed before the DEV run (`626e086`), and the smoke runs were set aside.

## 5. Results (DEV, 23 events, 24 controls)

| Measure | seed 1000 | seed 3000 |
|---|---|---|
| **Model recall, strict, T1** (passage in packet; own-class claim on a qualifying item, `supported`) | 12/20 = 0.60 [0.39, 0.78] | 14/21 = 0.67 [0.45, 0.83] |
| **Model recall, lenient, T1** (own-class claim, any support) | **19/20 = 0.95 [0.76, 0.99]** | 20/21 = 0.95 [0.77, 0.99] |
| System recall, strict, T1 (all 23) | 12/23 = 0.52 [0.33, 0.71] | 14/23 = 0.61 [0.41, 0.78] |
| Control false-alarm rate, clean on all classes | 1/9 = 0.11 [0.02, 0.43] | 3/9 = 0.33 [0.12, 0.65] |
| Support rate, all material_events claims, T1 | 89/140 = 0.64 | 90/144 = 0.62 |
| Support rate, detecting claims, T1 | 12/19 = 0.63 | 14/20 = 0.70 |
| Early warning at T0 (`risks` names the class) | 10/16 = 0.62 | 9/16 = 0.56 |
| Precision (S6, seed 1000, adjudicated) | 108/133 = 0.81 [0.74, 0.87] | — |
| **Reference bar 18/20 = 0.90** (strict, seed 1000) | **not met: 0.60** | |

**Seed spread:** both seeds agree on 17 of the 20 detectable events (κ = 0.68).

**Lag (seed 1000):**
- 12 detected at T1, a median of 2 XNYS sessions after first public;
- 2 detected at T2 only (ORIQU, QVCGA);
- 7 missed at both;
- 2 not in the packet.

**Per class:** small strata (2–3 events), so they are descriptive only. C5 and C7 are 3/3 and 2/2. C2 is 0/1 detectable (2 of its 3 events are not in the packet). False alarms on controls concentrate in C6 (2/17) and C1 (1–2/19).

**The headline:** the model names the right event almost every time (0.95 lenient). Strict recall is lower because most detecting claims **fail the code's support check**, not because the model misses the event. See §8.

## 6. Baseline B against Qwen

**Baseline B on DEV.** It is deterministic: the PREREG regular expressions over the same frozen packets. It does not
depend on the model, so this half was computed before the GPU run ended.

| Measure | B |
|---|---|
| Model recall at T1 (the passage is in the packet) | 19/20 = 0.95 [0.76, 0.99] |
| System recall at T1 (all DEV events) | 19/23 = 0.83 [0.63, 0.93] |
| T1 outcomes | 19 detected, 3 not in the packet (ALTS, AMS, QVCGA), 1 missed in evidence (SYNA) |
| T2 outcomes | 18 detected, 4 not in the packet, 1 missed in evidence |
| False-alarm rate on controls clean in all classes | 1/9 = 0.11 [0.02, 0.43] |

**Read these with a built-in bias.**
- B's recall here is not a fair comparison with Qwen's. The truth events were discovered partly with full-text and
  keyword searches of the same kind as B's patterns.
- "In the packet, equivalent" is itself defined by a B-pattern hit (amendment 6, S1).
- An event B's patterns do not match was less likely to be found, and cannot be "equivalent".
- B's recall is therefore biased upward by construction. The fairer comparisons are:
  - false alarms on controls;
  - what each says beyond a pattern hit: status, date, whether the event is in force;
  - the McNemar table on the events both could see.

**Against Qwen (seed 1000, the 20 detectable events):**
- B detects 8 events Qwen misses strictly; Qwen detects 1 that B misses (McNemar p = 0.039).
- Read with §8: all of Qwen's strict misses except LSTA are contract false negatives, and leniently Qwen detects 19/20, the same count as B.
- On controls, B's false-alarm rate (0.11) equals Qwen's seed 1000 (0.11) and is below its seed 3000 (0.33).
- The difference that matters is the extra a claim carries: status, date and whether the event is in force. B carries none of these.

## 7. Adjudication of other-class and control claims (S4, S5)

**The rulings,** applied identically to both seeds (`adjudication/claims_s4s5.jsonl`):
- **For C2,** a stated current doubt counts as a true event; newness is not required off the event's own class.
- **These are false alarms:**
  - an out-of-court restructuring or a cost programme labelled as bankruptcy or restructuring;
  - a guidance cut labelled as a withdrawal;
  - a revision without non-reliance labelled as a restatement;
  - a company's own termination labelled as a contract loss;
  - a de-SPAC or a non-binding offer labelled as an acquisition;
  - a merger cancelled before T stated as pending;
  - regaining compliance labelled as a delisting notice.
- **`past_event`** means an event that occurred, but more than about 180 days before T or since cured. It is not a false alarm, and is reported as stale.

## 8. Failure taxonomy (SPEC §7; `n6_taxonomy.py`, `n6/taxonomy_dev.json`)

| Category | T1 s1000 | T1 s3000 | T2 s1000 | T2 s3000 |
|---|---|---|---|---|
| **contract false negative** (own-class claim on the evidence, failed a support check) | **7** | 6 | 6 | 6 |
| passage not carried (filing in the packet, passage outside the carried text) | 3 | 2 | 4 | 3 |
| model missed it in evidence | 1 | 1 | 0 | 1 |
| wrong class | 0 | 0 | 1 | 0 |
| run incomplete (output-length cap) | 0 | 0 | 0 | 1 |

**Contract false negatives, by check, over all 25 failing detecting claims:** `number_not_listed` 21, `quote_not_found` 3,
`number_not_found` 1. The unlisted tokens are of two kinds:
1. **Designators,** not quantities:
   - "10" of "10-Q";
   - "8" of "8-K";
   - "820" of "ASC 820";
   - "26-465" of a bankruptcy case number;
   - "5250(f)" of a listing rule.

   The `626e086` exemption covers "Chapter 11", "Item 1.03" and "Rule 5550", but not form names, accounting-standard
   codes or case numbers.
2. **Real figures the claim states that sit inside the claim's own verbatim quote,** which passed the quote check:
   "30 consecutive trading days", "80%". The quote already proves that the figure is printed in the cited item.

**Passage not carried:**
- ALTS, AMS: going concern in the notes;
- QVCGA: Item 2.04 past the 8-K cap;
- FFAI T2, BWEN T2.

Builder v7 carries ALTS, AMS and QVCGA (`n7/regression_v7.json`).

**False alarms** (S4/S5 adjudication: 38 false alarms, 19 past events, 8 unclear). By reason:
- **a past or another entity's event** (stale doubt, an expired agreement, a cured notice): counted as `past_event`, 19;
- **mislabelled type:**
  - a guidance cut as a withdrawal;
  - the company's own termination as a contract loss;
  - a cost programme as a restructuring;
  - an expired or non-binding offer as an acquisition;
  - regaining compliance as a delisting;
  - a cancelled merger as pending;
- **boilerplate risk-factor text:** none counted as an acting false alarm. Supported claims cite filed facts.

**Systemic fixes this taxonomy calls for (§7):**
- (a) Contract v3: extend the designator exemption, and count a figure printed inside one of the claim's own passing
  quotes as listed. It is measured offline on the stored DEV analyses before any FRESH run.
- (b) Builder v7, already done.
- (c) The output-length cap (`num_predict` 12,288) for long packets. It is recorded; any change needs its own test.

## 8a. Contract v3, offline recheck on the stored DEV analyses (2026-10-30; `n6_recheck_v3.py`, `n6/score_dev_v3.json`)

Contract `m3m.analysis.v3` (rs2-local `15207e4`, `d2f3f15`) was re-applied to the same stored model outputs. No model was rerun, so this
measures the contract alone. DEV is the set the fix was diagnosed on, so these numbers are optimistic by construction; FRESH tests them.

| Measure | v2 seed 1000 | v3 seed 1000 | v2 seed 3000 | v3 seed 3000 |
|---|---|---|---|---|
| Strict model recall (T1) | 12/20 | 18/20 = 0.90 (0.70–0.97) | 14/21 | 18/21 = 0.86 (0.65–0.95) |
| Lenient model recall | 19/20 | 19/20 | 20/21 | 20/21 |
| System recall (all 23 events) | — | 18/23 = 0.78 | — | 18/23 = 0.78 |
| Clean-control false alarms | 1/9 | 1/9 | 3/9 | 3/9 |
| Precision (adjudicated, seed 1000) | 0.81 | 108/133 = 0.81 | — | — |

- **Seed agreement:** 19/20, κ 0.68 → 0.77.
- **Baseline B against Qwen (seed 1000):** B 19/20, Qwen 18/20. Discordant pairs 2 (B only) and 1 (Qwen only), McNemar p = 1.0.
- **Still missed at T1 and T2:**
  - ALTS and AMS (C2): the event is not in the packet;
  - LSTA and LMNR (C6): rule-literal criticals of low materiality (§9);
  - ACNT at seed 3000.
- **Reference bar 0.90:** met at the point estimate for seed 1000 only. The lower bounds sit near 0.65–0.70.
- **No new false alarms:** v3 widens what counts as listed, and control false alarms did not move at either seed.

## 9. Limits

- **Small strata:** 2–3 DEV events per class, and 9 clean controls. The intervals are wide, and per-class numbers are descriptive.
- **Reviewer independence:** reviewer 2 is mostly the same model family as reviewer 1.
- **Unreviewed non-events:** for C5 and C6, only a 20% sample of reviewer 1's non-events was second-reviewed, and reviewer 1's screening missed real events in C2, C7 and C8.
- **Rule-literal criticals of low materiality:** ACNT, XNCR, LMNR and LSTA.
- **SPAC strata:** SPAC going-concern boilerplate dominates parts of C2.
- **Clock:** the acceptance clock is 4–5 hours conservative (CROSS_CHECK_N 11). Lag is reported from the true time.

## 8b. DEV regression on the final version (builder v7, contract v3; `n7_run.py`, `n7/runs_dev_v7.jsonl`, 212/212 complete, 2026-10-30)

Scored by `n7_score.py`, which runs `n6_score.py` unchanged on the n7 runs, packets and rulings:
- 153 S4/S5 rulings were carried by the same cited documents;
- 91 new rulings, by Claude, in `adjudication/claims_s4s5_v7_new.jsonl`;
- 0 claims left unadjudicated.

| Measure | Seed 1000 | Seed 3000 |
|---|---|---|
| Strict model recall (T1) | 19/23 = 0.83 (0.63–0.93) | 21/23 = 0.91 (0.73–0.98) |
| System recall (all 23 events) | 19/23 | 21/23 |
| Lenient model recall | 21/23 | 22/23 |
| Clean-control false alarms | 2/9 | 4/9 |
| Early warning (T1 detections before first public) | 9/16 | 9/16 |
| Precision (adjudicated, seed 1000) | 130/149 = 0.87 (0.81–0.92) | — |

- **Seed agreement:** κ 0.62.
- **Baseline B:** 22/23. McNemar against Qwen at seed 1000: B-only 4, Qwen-only 1, p = 0.375.
- **What changed from the v3 offline recheck (§8a):**
  - Builder v7 puts ALTS and AMS (C2) into the packet, and both are detected, so system recall rises 18 → 19 and 21.
  - The misses that remain are the rule-literal C6 cases (LSTA, LMNR; §9) and ACNT at seed 1000.
  - Control false alarms rose by one at each seed: C1, C2, C6 and C7 at seed 1000; C1 twice, C6 twice and C7 at seed 3000.
  - The new false alarms are cost programmes read as restructurings, a non-renewal at expiry, and a guidance cut read as a
    withdrawal (the §8 taxonomy).
- **Caveat:** DEV is the diagnosis set. FRESH decides 3N (SPEC_m3n §7).
