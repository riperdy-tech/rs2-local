# PREREG_m3n amendment 1: controls (2026-10-29)

**When it was written:** after the WO_N3 draw, and **before any truth label and any 3N model run**. It amends `PREREG_m3n.json`, whose sha256 `eafda743…` stays the frozen base. SPEC_m3n §4.4 is read with this amendment.

## The defect

`controls.exclusion` removed a drawn issuer whenever it had a discovery **candidate** within [T−180d, T+30d]. Candidates are hints, not events, and two channels match ordinary filings:
- the C5 item-code channel catches every Item 1.01 material agreement;
- the C8 text query matches "event of default" in ordinary credit agreements.

The WO_N3 draw shows the effect:

| What happened | Count |
|---|---|
| draws excluded and replaced | 36 of 86 |
| exclusion rate on the newer frames | 60% |
| exclusion rate on the stale 2025-12-14 frame | 21% |
| controls on the stale frame | 31 of 48 (about 19 expected by date share) |

**Why that is wrong:** the controls would have been skewed toward quiet companies, which makes a false-alarm rate look better than it is. Excluding on events up to 30 days after T has a second problem: it removes the pre-event companies, where false alarms are most likely. A claim at T can only be true or false about events at or before T.

## The amended rule

1. **At draw time** the only removals are:
   - the excluded tickers, as before;
   - a row whose CIK cannot be resolved: replaced and recorded, as before.

   No candidate-based exclusion.
2. **The issuer's candidates** in [T−180d, T] are listed in the control record as `candidates_in_window`, for the reviewer only.
3. **Truth.** The reviewers label every control per class, from the filings accepted in [T−180d, T] (as PREREG `controls.non_event_requires`).
   - A control **confirmed_critical** for a class is not a control for that class. It is recorded and reported, never added to the event set, and never counted as a hit or a false alarm for that class.
4. **The false-alarm denominator is per class:** the controls that are `non_event` for that class. The headline control false-alarm rate is over the controls that are `non_event` for all eight classes. Both are reported, with Wilson intervals.
5. **The draw itself is unchanged:** same seeds, same order, same 48, same parity split.

## Correction

SPEC §5.1 says the control time is "14:30Z (09:30 New York)". That holds only in winter; from 2026-03-08 it is 10:30 New York. **The PREREG value of 14:30:00Z stands.** Only the parenthetical was wrong. A packet at T needs nothing that falls between 09:30 and 10:30.

## The earlier draw is kept

The earlier draw is kept as `m3n/controls_v1_excluding.jsonl` and `m3n/controls_draw_log_v1.jsonl`, renamed and not deleted.
