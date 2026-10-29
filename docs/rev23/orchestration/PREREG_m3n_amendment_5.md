# PREREG_m3n amendment 5: what "in the packet" means (2026-10-29)

**When it was written:** after the DEV packets were built (`n5/packets.jsonl`), before any 3N model run. The truth set is frozen and is not changed.

## The ambiguity

SPEC §6.1's `not_in_packet` means "the source is not in the packet", which can be read two ways:
- **as an item:** an evidence item exists whose accession is the event's filing;
- **as text:** the event's passage is in that item's text.

They differ, because sections are capped and trimmed. In the DEV T1 packets:
- **YEXT:** the 8-K item is present, but its text lacks the "suspend forward guidance" passage.
- **SBLX:** the 10-K items are present, but the going-concern conclusion is in the notes, which are outside the packet's sections.
- **OPTU:** the Item 4.02 8-K is not in the packet at all.

Counting the first two as model misses (`missed_in_evidence`) would charge the model for passages it was never shown.

## The rule

1. **A qualifying item** (an anchor or later accession on the same event, as in the scorer) **"carries the event"** when its text contains the event's key passage.
   - **The key passage** is the first 80 characters of the truth quote (`truth_events.json` `quote`) after Unicode NFKC normalisation, collapsing whitespace and lower-casing.
   - **Where the truth quote is empty,** it is the upheld reviewer-2 quote (`adjudication/r2_all.json`). This happens for events confirmed by adjudication over a reviewer-1 `non_event`: PAACU, ACNT, MEHA.
2. **The T1 outcome** is one of:
   - `not_in_packet`: no qualifying item carries the event;
   - `detected`: the strict rule, where the claim must cite a qualifying item, whether or not that item carries the passage;
   - `missed_in_evidence`;
   - `run_incomplete`.
3. **Both are reported:** the item-only count (`not_in_packet_item`) and the text count.
4. **Model recall** uses the text definition. **System recall** is unchanged (all events in the denominator).
5. **Baseline B** uses the same `not_in_packet`, so the two are compared on the same evidence.

## Also resolved here (SPEC §6.4 against §5.3)

§6.4 compares the early-warning measure with "the same measure on the controls", but §5.3 runs `risks` only on T0 packets. The controls therefore also run `risks`, on their control packet at the drawn T, with both seed bases.

The T0 packets that cannot be built are recorded as `not_testable` and leave the early-warning denominator:
- 3 fall before the first screener snapshot;
- 4 tickers were not yet in the frame.
