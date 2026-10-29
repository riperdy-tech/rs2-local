# PREREG_m3n amendment 6: scoring rules S1–S10, and truth re-frozen (2026-10-29)

**When it was written:** after CROSS_CHECK_N and its rulings, **before any 3N model run.**

The S1–S10 text is adopted from `CROSS_CHECK_N_opus.md`, "Proposed scoring amendment", with these changes:

| Rule | Change |
|---|---|
| **S1** | Implemented as amendment 5's text rule. Per event and per T (T1, T2), `in_packet` is `exact` when a qualifying item contains the key passage, and `absent` otherwise. The paraphrase class `equivalent` is not used: no reader is defined for it. The per-event record is frozen in `m3n/n5/in_packet.json` before the run. |
| **S3** | Status never disqualifies a claim, except for an event cancelled, terminated or cured at or before T. A `cancelled_at` field is added: null for every current event, and checked at T2 by the post-run adjudicator. The truth has no null `status`; `status_source` records a class default. |
| **S4** | Adopted as written. |
| **S5** | Adopted, **except `past_event`**: a claim about an event that occurred but ended or was cured before T−180d is **not a false alarm**. It is reported as `stale_event_claims` (CROSS_CHECK_N_RULINGS). |
| **S6** | Adopted as written. |
| **S7** | Adopted as written. |
| **S8** | Adopted as written. |
| **S9** | Adopted as written. |
| **S10** | Adopted as written. |
| **Precision** | Uses seed base 1000 only, and only after the S4/S5 adjudication is finished. |

## The truth re-frozen (v2)

The re-freeze applies these rulings:
- **Finding 6:** 91 blocked candidates were requeued, reviewed by r1 and second-reviewed by r2, and the PREREG one-event-per-issuer rule was applied in class order.
- **Finding 7:** all C7 `non_event` labels were second-reviewed, which found LXP, an r1 miss.
- **Findings 2 and 9:** YEXT and WS are `not_in_frame_at_anchor`.
- **Finding 8:** the record fields are taken from the final label's source.
- **The exhibit-name gap:** 6 events and 2 controls were rebuilt and re-reviewed.

The resulting sample, by class (k-order, DEV on odd k):

| Class | DEV | FRESH |
|---|---|---|
| C1 | FATBP, SNYR, SOPA | SNBR, LESL, GOCO |
| C2 | ORIQU, ALTS, AMS | IACOU, SBLX, CSAI |
| C3 | SDEV, OPTU, PTHS | CETY, AVAV, RR |
| C4 | EONR, FFAI, QSEAU | ALDF, GOSS, HWH |
| C5 | CHMI, FONR, SYNA | AVB, RAMP, MCW |
| C6 | XNCR, LSTA, LMNR | ATYR, ALEC, RIGL |
| C7 | QDEL, BWEN | LXP, ARAY (the pool holds 4) |
| C8 | ARAI, ACNT, QVCGA | MEHA, LOCL, AXTI |

**Skipped:**
- SNBR (C2) and AIFC (C4): the issuer was already sampled in an earlier class (AIFC and ALTS share CIK 862861).
- YEXT and WS: not in the frame at the anchor.

**Totals:** 46 events (23 DEV, 23 FRESH) and 24 DEV controls.

| File | sha256 |
|---|---|
| `truth_events.json` | `728a289d3f5dfb081d9f4599a4b798d822f1ec7dde5564340d014e05ba2e92e8` |
| `truth_controls.json` | `c3660d8d67ad670c91a369985f34ddc725540f64410ab5428b4bbd28c98e8b11` |

The input hashes are in `m3n/truth/FROZEN_sha256_v2.txt`. **The v1 freeze is superseded.** No model output existed at either freeze.

## Addendum: S1 equivalence (2026-10-29, before any run)

The DEV in-packet freeze showed that the exact-passage rule misses a paraphrase.
- **The case:** C7-31-BWEN's EX-99.1 headline says "withdraws 2026 financial guidance", but the truth quote's sentence is not in the packet.

**`equivalent` is therefore defined,** using a reader already pre-registered:
- an event whose key passage is absent is `equivalent` when the PREREG baseline-B pattern of its class hits a qualifying item (its own filing, or a later filing on the same event);
- `exact` and `equivalent` both count as in the packet.

**Effects:**
- Baseline B's own detections are unchanged, since a B hit on a qualifying item means `equivalent` or better.
- Every `equivalent` case is listed in RR_N with its matched text.
- The freeze (`n5/in_packet.json`) is rewritten with this rule, and its sha256 is logged.
