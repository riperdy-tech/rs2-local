# PREREG_m3n amendment 2: one ticket per issuer, and first-public anchoring (2026-10-29)

**When it was written:** after the WO_N3 draw, **before any truth label was written and before any 3N model run.**
- Reviewer 1 had looked at the first 8 C1 cases through a reading aid. No label was recorded.
- Reviewer 2 had produced 2 C1 outputs on the old queue. They are kept in `m3n/r2_v1/` and are not used.

## 1. The draw unit is the (issuer, class), not the filing

**The defect.** `draw.class_order` shuffled **filings**, so an issuer with many candidate filings in a class held many tickets. For example, OPI has five Item 1.03 8-Ks in the window. The chance of drawing an event was therefore proportional to its number of follow-up filings, which favours long and complex cases.

**The rule now.** The candidates of a class are grouped by CIK. Each group is represented by its earliest candidate: by `file_date`, then accession. The groups are sorted by CIK and shuffled with the same class seed. The rest of the draw is unchanged:
- membership at the representative's T1;
- one event per issuer across classes, in class order C1 to C8;
- 12 queued per class, with `--more`;
- DEV/FRESH by the parity of the confirmed order.

The earlier queue is kept as `m3n/queue_v1/`.

## 2. First-public anchoring (applying SPEC §4.1; a rule written down, not a change)

- **First public time** is the acceptance time of the **first filing that discloses the event.** That may be earlier than the drawn candidate, whose filing may be a follow-up.
- **Reviewer 1 finds it.** The aid is `r1_anchor.py`, which lists the issuer's earlier filings carrying the class's item codes. Reviewer 1 records `anchor_accession`.
- **Then:**
  - **(a)** if the anchor's acceptance time is before 2025-12-15, the event is **`out_of_window`**. It is recorded, not sampled, and the walk continues.
  - **(b)** otherwise T1 is recomputed from the anchor with the acceptance rule, and frame membership is checked again at that T1. A non-member is `not_in_frame_at_anchor`: recorded, not sampled.
- **The evidence item a detection must cite** (SPEC §6.1) is the anchor filing, or a later filing on the same event that is in the packet.

## 3. Event candidates that are not events

A queued candidate that shows no event of the class gets the label **`non_event`**, with the reason `candidate_not_event`. For an event case, `non_event` means "not an event of this class". It does not mean the issuer has no event.
