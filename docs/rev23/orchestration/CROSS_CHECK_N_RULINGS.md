# CROSS_CHECK_N rulings (Claude, lead, 2026-10-29)

**The review:** `CROSS_CHECK_N_opus.md`, by a fresh, blind Opus reviewer. It substitutes for the outside-AI cross-check, because Gemini's quota is out and the gemini CLI is retired; the operator ruled this on 10-29. It is not an outside AI.

**Every finding is accepted unless a ruling below says otherwise.** No GPU run starts until items 1–3, 4, 6–10 and 13 are closed.

## Findings 1–14

| # | Finding | Ruling |
|---|---|---|
| 1 | In-packet must be judged by text | **FIX.** Amendment 5 already defines in-packet by text: the event's key passage must be in a qualifying item's text. It is extended to T2. The per-event `in_packet` record (status, items, key passage) is frozen in `m3n/n5/in_packet.json` after the v5 rebuild and before the run, with its sha256 in LOG. |
| 2 | C7-43-YEXT anchor | **FIX.** Read 8-K 0001628280-26-016005. If it announces the suspension, YEXT is `not_in_frame_at_anchor` (it is not in the 2025-12-14 frame) and leaves the sample; C7 becomes QDEL (DEV) and BWEN (FRESH). |
| 3 | Scoring amendment | **FIX.** S1–S10 adopted as **amendment 6**, with one change to S5 (`past_event`; see below). |
| 4 | Builder drops 2.02 co-items | **FIX before the run:** builder v5 (WO_N5). It is done now, because doing it after DEV would force a DEV rerun and spoil FRESH. The DEV packets are rebuilt with v5. |
| 5 | Controls' unseen old 10-K text | **Ruled: S5 instead of a pre-run re-review.** Every critical claim on a control is adjudicated from its cited text. `true_in_window` takes the control out of that class's denominator; `past_event` (S5 change, below) is not a false alarm. This settles the risk where it arises, at the cited text. |
| 6 | Draw blocks queued, not confirmed, issuers | **FIX, option (a):** PREREG says one *event* per issuer. All **86** blocked candidates before their class's last sampled position, and in C7's exhausted pool, are queued, reviewed by r1 and second-reviewed by r2 (Sonnet), and the sample is re-derived under the PREREG rule. No amendment-by-deviation. |
| 7 | C7 non-events read once | **FIX:** a full r2 second review of all 98 C7 `non_event` cases, plus C7's blocked candidates (finding 6). |
| 8 | Truth fields | **FIX** in `truth_build`: quote, file, status and event date come from the final label's source (the resolution, else r2 when r2's label is final). `r1_blind` (r1's first line) and `r1_final` are separate, and agreement is computed from `r1_blind`. A null `status` is refused. |
| 9 | C6-187-WS | **FIX:** `not_in_frame_at_anchor` (ALUR is not in the frame; "WS" came from splitting "ALUR WS"). `truth_build` re-checks the name and the cik_map; every sampled `needs_review` gets a recorded membership ruling. |
| 10 | XNCR anchor; anchor sweep | **FIX:** read 0001326732-26-000021. Then sweep every sampled event: every 8-K and periodic report of the issuer in the 30 days before the anchor is read for the event's words, and the earliest disclosing filing is the anchor. |
| 11 | Clock | **FIX** in reporting: `first_public_true_utc` (the raw submissions value, which SEC headers show is true UTC); lag is measured from it, and the one-session policy delay is stated. T1 stays as frozen. A dated note goes to the 3M acceptance-policy record (SPEC_m3m), saying `accepted_at` makes T1 one session late for 27 of 45 events; any policy change is a separate, versioned decision. |
| 12 | T0 has no control baseline | Already resolved by amendment 5: `risks` runs on the controls. |
| 13 | K03-GNK built with pre-fix code | Superseded: every DEV packet is rebuilt with v5. |
| 14 | Frame history simplification | **NOTE accepted.** The driver recomputes `frame_at(T)` independently on a `--full-history` list and records both. The stocks.json blob is identical in every case measured. |

## Findings 15–21

| # | Finding | Ruling |
|---|---|---|
| 15 | Baseline B is strong | Report B pooled; per-class McNemar is descriptive only. |
| 16 | Thin strata | Report these strata separately: SPAC-boilerplate C2, low-materiality rule-literal criticals (ACNT, XNCR, LMNR, LSTA), and C7 n=1. |
| 17 | Detection depends on listing numbers | Report support-failure causes among lenient detections. |
| 18 | Funds and foreign filers | Funds HPI and DLY (unknown in every class, S0-only packets) are **not run**. TRX and BN are run, and count only where their labels are `non_event`. |
| 19 | FRESH hazards | LESL's T2 lies in the future: FRESH waits until T2 has passed and the frame tip is refreshed. |
| 20 | AUDIT_N2 condition 3 | Corrected in the record: runs land in `wt-m3n/cache/m3m/runs`. Harmless. |
| 21 | Output length | The smoke run includes C1-01-FATBP and checks `done_reason` and `eval_count`. |

## The change to S5

A claim on a control about an event that **did occur but ended or was cured before T−180d** (`past_event`) is **not** a false alarm. The claim is true, and `material_events` asks for events the evidence shows have occurred. It is reported separately as `stale_event_claims`, the noise a monitoring use would have to filter. This replaces the reviewer's default ("counts as a false alarm").
