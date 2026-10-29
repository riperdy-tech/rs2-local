# RR_N (DEV): Qwen material-event detection, the DEV half (2026-10-29/30)

**Status:** DRAFT. The sections that do not depend on model output were written during the run. Sections 5–8 are filled in from `n6/score_dev.json` (`n6_tables.py`) after the run.

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

Builder v6 (WO_N6, prepared and not applied to DEV) targets both.

## 4. The runs

- **Tasks:**
  - `material_events` at T1, T2 and on the controls;
  - `risks` at T0 and on the controls.
- **Seeds:** base 1000 (primary) and 3000 (spread).
- **Scale:** 212 tasks, through the scheduled task RS2-M3N-DEV-Runner, outside any Claude session.
- **The smoke run** (FATBP plus control GNK) found a contract false negative: "Chapter 11" counted as an unlisted figure. It was fixed before the DEV run (`626e086`), and the smoke runs were set aside.

## 5. Results

*To be filled from n6_tables.py.*

## 6. Baseline B against Qwen

*To be filled.*

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

## 8. Failure taxonomy (SPEC §7)

*To be filled:* packet gap; section not found; model miss in evidence; wrong class; contract false negative; false alarm from boilerplate; false alarm from a past or another entity's event.

## 9. Limits

- **Small strata:** 2–3 DEV events per class, and 9 clean controls. The intervals are wide, and per-class numbers are descriptive.
- **Reviewer independence:** reviewer 2 is mostly the same model family as reviewer 1.
- **Unreviewed non-events:** for C5 and C6, only a 20% sample of reviewer 1's non-events was second-reviewed, and reviewer 1's screening missed real events in C2, C7 and C8.
- **Rule-literal criticals of low materiality:** ACNT, XNCR, LMNR and LSTA.
- **SPAC strata:** SPAC going-concern boilerplate dominates parts of C2.
- **Clock:** the acceptance clock is 4–5 hours conservative (CROSS_CHECK_N 11). Lag is reported from the true time.
