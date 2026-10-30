# RR_N (FRESH): Qwen material-event detection on the sealed half (2026-10-31)

**Status:** final. The run finished 128 of 128 tasks (2026-10-31 ~04:00 KST) and was scored once by `n8_score_fresh.py`, which runs
`n6_score.py` unchanged on the FRESH runs, packets and rulings (`n6/score_fresh.json`). FRESH was unsealed 2026-10-30 13:36Z
(`n7/FRESH_UNSEALED.txt`). It was run once and is not used to tune anything (SPEC_m3n §7).

## 1. What ran

- **Version:** rs2-local worktree `wt-m3n-v6` at `d2f3f15`. Packet builder v7, contract `m3m.analysis.v3`, prompt `m3m.prompt.v3`.
  This is the DEV regression version (RR_N_DEV §8b).
- **Model:** `rs2-analyst-deep-mtp5-v33` through ollama_raw. Seeds 1000 (primary) and 3000 (spread).
- **Frame pin:** stock-screener `1e3f826e`, the first origin/main commit after the last FRESH T (LESL T2, 13:30Z).
- **Truth:** v2 (`728a289d…`). 23 FRESH events in 8 classes, frozen before any model run.
- **Packets:** 64 built, plus 5 T0 packets refused (`ticker_not_in_stocks`). T0 is exploratory only.
- **Tasks:** 128 in total, through the scheduled task RS2-M3N-FRESH-Runner, outside any Claude session. One smoke row
  (SNBR T1) was kept as the first run row.
- **Controls:** none. All 24 truth controls are DEV, so FRESH reports no control false-alarm rate. The rate comes only from
  DEV (RR_N_DEV §8b: 2/9 at seed 1000, 4/9 at seed 3000). This shortfall is recorded, not filled.

## 2. Results

| Measure | Seed 1000 | Seed 3000 |
|---|---|---|
| **Strict model recall, T1** | **18/22 = 0.82 (0.61–0.93)** | **20/22 = 0.91 (0.72–0.97)** |
| System recall, T1 (all 23 events) | 18/23 = 0.78 (0.58–0.90) | 20/23 = 0.87 (0.68–0.95) |
| Lenient model recall (own-class claim, any support) | 21/22 = 0.95 | 21/22 = 0.95 |
| Support rate, all material_events claims | 102/124 = 0.82 | 119/134 = 0.89 |
| Support rate, detecting claims | 19/22 = 0.86 | 23/24 = 0.96 |
| Early warning (T0 `risks` names the class) | 11/17 = 0.65 | 10/18 = 0.56 |
| Precision (adjudicated, seed 1000 only, as on DEV) | 101/108 = 0.94 (0.87–0.97) | — |
| **Reference bar 0.90 (18/20 scaled)** | **not met at the point** | met at the point; lower bound 0.72 |

- **Recall denominators.** The scorer counts an event whose frozen in-packet label is `absent` when the model detected it
  anyway. This is the same rule as on DEV. Two such events are in FRESH: ATYR (C6) and MEHA (C8). Counting only events labelled
  `exact` or `equivalent`, strict recall is 16/20 at seed 1000 and 18/20 at seed 3000.
- **Lag (seed 1000):**
  - 18 events detected at T1, a median of 2 XNYS sessions after first public;
  - 3 detected at T2 only: SNBR, GOSS and HWH, all three contract false negatives at T1 (§4);
  - 1 missed at both, AXTI;
  - 1 not in the packet, LOCL.
- **Seed spread:**
  - the seeds agree on 18 of 22 events;
  - 17 both hit, 1 both miss (AXTI), 3 seed-3000 only, 1 seed-1000 only (RAMP);
  - κ = 0.24. κ is low because all four splits are contract check failures at one seed on the same event (§4), not
    disagreements about what the filing says.
- **Per class:** strata of 2–3 events, descriptive only. At seed 1000 the weak classes are C4 at 1/3 (GOSS and HWH are
  contract false negatives) and C8 at 1/2 detectable (AXTI missed, LOCL not in the packet).

## 3. Against DEV and baseline B

| Measure | DEV, final version (§8b) | FRESH |
|---|---|---|
| Strict model recall, seed 1000 | 19/23 = 0.83 | 18/22 = 0.82 |
| Strict model recall, seed 3000 | 21/23 = 0.91 | 20/22 = 0.91 |
| Precision, seed 1000 | 130/149 = 0.87 | 101/108 = 0.94 |
| Support rate, detecting claims, seed 1000 | 0.90 | 0.86 |

**FRESH reproduces DEV.** The fix was diagnosed on DEV, so DEV numbers were optimistic by construction (RR_N_DEV §8a). FRESH
did not fall below them, so the fixes generalise to unseen events.

**Baseline B on FRESH:**
- model recall 18/20, system recall 18/23;
- McNemar against Qwen at seed 1000: B only 4 (SNBR, GOSS, HWH, AXTI), Qwen only 2 (AVB, LXP), p = 0.69, no difference;
- B's recall is biased upward by construction, as on DEV (RR_N_DEV §6).

## 4. Failure taxonomy (SPEC §7)

| Event | Seed | T1 outcome | Cause |
|---|---|---|---|
| SNBR (C1) | 1000 | missed | **contract false negative:** `number_not_listed` "11399" from "Case No. 26-11399" |
| GOSS (C4) | 1000 | missed | **contract false negative:** `number_not_listed` "180" in the Nasdaq notice claim |
| HWH (C4) | 1000 | missed | **contract false negative:** `number_not_listed` "1" from "Listing Rule 5550(b)(1)" |
| RAMP (C5) | 3000 | missed | **contract false negative:** `quote_not_found`, the model's quote of the board resolution does not match the printed text |
| AXTI (C8) | both | missed | **model missed it in evidence:** it reported the IPO withdrawal and the redemption rights it triggered as `other_material_event`, never as a default or acceleration |
| LOCL (C8) | both | not in the packet | packet gap |

**What this taxonomy says:**
- Contract v3's designator rule covers a bare number right after a designator word. It does not cover compound designators: a
  hyphenated case number (26-11399), or a rule with parenthesised subsections (5550(b)(1)).
- The model named the event correctly in all four contract misses. Lenient recall stays 21/22 at both seeds.
- Fixing compound designators is a second systemic change. Under SPEC §7 a second change needs a new draw (FRESH-2) before
  any fresh number is reported on it. It is carried to 3N's follow-up list, not applied here.
- **False alarms (S4, seed 1000; 72 rulings, `adjudication/claims_s4s5_fresh.jsonl`):**
  - 57 true other events, 7 false alarms, 5 past events, 3 unclear;
  - the false alarms are the DEV kinds: a guidance cut read as a withdrawal, a cost programme read as a restructuring, a
    buyer-side termination, and a going-concern doubt stated as alleviated.
- **The seed-3000 claims (72) are not ruled.** Precision is pre-registered on seed 1000 only, as on DEV, so ruling them
  changes no reported measure.

## 5. Limits

- 23 events and no FRESH controls. The intervals are wide; the lower bounds are 0.61 (seed 1000) and 0.72 (seed 3000).
- The adjudicator is Claude, alone, from the cited text, by the DEV precedents.
- The archival regime measures model accuracy on today's download of the SEC record. It is not evidence of what the system
  held at the time.
- The DEV limits carry: small strata, reviewer independence, unreviewed C5/C6 non-events, the SPAC going-concern stratum, and
  B's bias (RR_N_DEV §9).

## 6. What it means

- **On unseen post-cutoff events,** Qwen names the right critical event about 19 times in 20 (lenient 21/22).
- **Under the code's strict support check,** 4 to 5 detections in 5 survive (0.82–0.91).
- **Its other-class critical claims** are right 94% of the time on seed 1000.
- **The remaining strict losses** are mostly the code check rejecting compound reference numbers, not the model.
- **This grants no trading authority (PLAN §3N).** It closes the measurement: the shadow label on FQ and FB flips to
  `paper_post_3N` from the next formation (2026-11-30).
