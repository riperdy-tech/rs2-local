# RR_N6: qwen_c packet builder v6 (builder report, 2026-10-29)

Work order: `WO_N6.md`. New worktree `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3n-v6`, branch `review-2026-10/m3n-v6`, made from `review-2026-10/m3n` (head `626e086`). Only `qwen_c/` changed. `wt-m3n` and `sec_primary.py` are untouched. No network, no GPU or Ollama, no push, no `.secrets.json` or `.env*` read. No file under `m3n\n5\runs*`, `n6\` or a run directory was opened. `n5\packets_v5.jsonl` and `n5\in_packet.json` were read for the probe arguments and key passages.

## Commits (by pathspec)

1. `3994c88` qwen_c: packet builder v6 - the going-concern note, the 8-K body shared across its listed items (WO_N6). This is the brief.
2. `c4f46d0` qwen_c: packet builder v6 - an amendment is read for going-concern passages too (separate, so it can be reverted). **This one goes beyond the brief; see open choice 1.**

## Tests

- Baseline at start: 373 passed. Now: **387 passed** in 160 s, one process, run once at the end on the final code (`"C:\Program Files\Python312\python.exe" -m pytest qwen_c/tests -q`).
- 14 new tests in `test_packet.py` (section "WO_N6: builder v6"):
  - constants;
  - the going-concern note's place, title and paragraph either side, with a line the packet already shows not repeated;
  - a 10-K with no going-concern paragraph: no item and `gc_text_not_found` for it and for the 10-Q;
  - the 10-Q's own note after its sections;
  - `gc_passages` merge, order, gap marker, shown-line skip and document edges;
  - the over-cap choice (below);
  - the cap and the `gc_passages_omitted` annotation;
  - **`TOTAL_CAP` trimming with gc_notes present** (order of the annotations, the 10-Q's note dropped before the 10-Q's sections, the annual note dropped before the annual sections, statements and annual sections whole);
  - **QVCGA's shape**: a long 1.01 first, then 1.03, 2.04 and 7.01. The 2.04 sentence is kept, every listed item has its segment, 9.01 is not, the long item is cut and marked, and the v5 text for the same body loses the sentence;
  - space a short segment leaves passes to the long one, and the exhibits fill the rest;
  - the fallback to v5's reading when the body has no heading of a qualifying item;
  - `eight_k_item_segments`; `_share`;
  - an amendment's own note (commit 2).
- Four existing assertions changed, each because of the brief's own rules:
  - `builder_version` v5 to v6 in `test_packet.py` (twice, and `test_builder_v5_constants` no longer checks the version) and in `test_replay.py`;
  - the "cut" 8-K test now uses a 400-character EX-99.1. A 28-character exhibit now fits in the room the body leaves, which is the new behaviour;
  - the no-EX-99 Item 4.02 test: the text now starts at Item 4.02, not at the Item 2.02 paragraph before it (2.02 is not in `OTHER_8K_ITEMS`).

## What changed (`qwen_c/packet.py`, `BUILDER_VERSION = "m3m.packet.builder.v6"`, `GC_CAP = 6_000`)

**1. The going-concern item (`gc_note`).**
- `_gc_note` runs on the primary document of the annual report and of the 10-Q (and, commit 2, of each amendment).
- A passage is a line (paragraph or table row, as `doc_lines` gives them) matching `going\s+concern|substantial\s+doubt`, with the line before and after. Passages that overlap or touch are merged. The output is in document order, with an `OMIT` marker over the lines between two passages.
- Title: "<form> going concern and liquidity passages". The kind and name are `gc_note`. The item sits right after its filing's P sections.
- A filing with no match, or with no primary document, is annotated `gc_text_not_found: <accession>`.
- Lines already in that filing's sections in the packet are not repeated, and they do not count as matches (see choice 2).

**2. The 8-K body is shared.**
- `eight_k_item_segments` gives one segment per heading of a listed item, from that heading to the next one. A combined heading ("Items 2.03 and 2.04") carries both numbers.
- Only segments of an `OTHER_8K_ITEMS` item are kept, so 2.02, 9.01 and 5.07 segments are not.
- `_share` splits the cap evenly. The shortest segment goes first and takes what it needs, up to an equal share of what is left, and the rest passes on.
- A segment over its share is cut by `prefix_text` and marked. The exhibits then fill what remains.
- When the body must be cut and exhibits exist, a marker's worth of room is kept free, so the final `prefix_text` cut cannot clip the body's tail.
- A body with no heading of a qualifying item is read as in v5, from its first listed heading.

**3. Unchanged:** `_trim`, `TOTAL_CAP`, the acceptance rule, all other caps.

### How the new items rank in `_trim` (the brief asked for the rule)

`_trim` cuts from the end of the evidence list, and I changed nothing in it. With the gc_notes placed right after their filing's sections, the order of dropping is:

1. the other 8-Ks, oldest first;
2. the release;
3. each amendment's gc_note, then that amendment;
4. the 10-Q's gc_note;
5. the 10-Q's sections;
6. the annual report's gc_note;
7. the annual report's sections;
8. the statements;
9. S0.

So a gc_note goes **after the release and the 8-Ks, before the statements**, and before its own filing's sections. The reasoning, also in the module docstring: the note supplements its filing's text, so the rest of the packet is cut first and the filing the note comes from is cut last.

One consequence is that the annual note outlasts the 10-Q's sections. The test shows it. If you would rather every gc_note outranked every section, `_trim` would need an explicit order; I did not add one.

## Offline probes

The store is `wt-m3n\cache\m3m\raw`. The arguments are the frame commit, T and CIK from `n5\packets_v5.jsonl`. I first rebuilt the three v5 packets with the unchanged v5 code and got the logged shas (`569c6ea3…`, `ec7019e4…`, `dd8115fe…`), so the store and the arguments are right.

The v6 packets are in `wt-m3n-v6\cache\m3n\packets_v6_probe\<case>\`. **There were no `NotInStore` URLs.**

| Probe (T1) | v6 sha256 | Key passage (from `in_packet.json`) now in the packet? |
|---|---|---|
| C2-1072-ALTS | `1a89652026011ea810da6f1fe773d3ee6e3e0b1fc8e76510c11923d8d361c197` | **Yes**, in P4 `gc_note` of 10-K 0001493152-26-016259 (2,371 characters). It is the "Liquidity and Going Concern Considerations" note. |
| C2-1122-AMS | `2b4f056e51310d51bd9f213007702573af20de347031ddbce3b990694ccbf6d0` | **Yes, with commit 2 only**, in P6 `gc_note` of 10-Q/A 0001437749-26-001452 (5,786 characters; 3 of 9 passages kept). Not with commit 1 alone. See choice 1. |
| C8-1053-QVCGA | `f0a7855528d602307484c11dbc1459a32adab1f8f1c15817fabf004a89a95ed4` | **Yes**, in P5 `other_8k` 0001104659-26-044521: the Item 2.04 sentence "The filing of the Chapter 11 Cases described above in Item 1.03 constitutes an event of default …". The segments are 1.01 (cut and marked), 1.03, 2.04 and 7.01, and the text is 3,993 characters. |

QVCGA side effects:
- Its 10-K also gets a `gc_note` (4,005 characters, 4 of 7 passages), which now holds the auditor's report and the "Going Concern" note.
- The 8-Ks' EX-99.1 exhibits are now reached where the body used to fill the cap. For QVCGA's 8-K this is only a trailing "Exhibit 99.1 / UNITED" plus an omit marker, about 40 characters of nothing (see note 4).

In all three, the P-numbers after the new `gc_note` move up by one.

## Open choices

1. **Amendments (commit 2).**
   - The brief names the annual report and the 10-Q. C2-1122-AMS's key passage is in the **10-Q/A**, past the 4,000-character amendment item. The 10-Q before it has no going-concern text, nor does the 10-K (0 matches in each).
   - The brief's two sources cannot close the AMS gap, so I added each amendment's own note. It is the same filings the packet already uses, and it is a one-line change in `_core`.
   - **Revert `c4f46d0` if you want the brief literally.** Then AMS stays "absent". Cost of keeping it: up to 6,000 characters for each of the two amendments, against `TOTAL_CAP`.
2. **The over-cap rule (departure from "document order, to the cap").**
   - With document order cut at 6,000, QVCGA's 10-K note was filled by the forward-looking-statements preamble and Item 1A tails, and the Going Concern note (Item 8) was cut. I measured this on the store.
   - So lines already shown in the filing's sections are skipped. Over the cap, whole passages are kept, those with `substantial doubt` first and, within each group, the later first. The output is still in document order, and omitted passages are annotated `gc_passages_omitted: <accession> kept k of n (over 6000 characters)`.
   - ALTS fits whole (2 passages). AMS keeps 3 of 9 (the passage with the key sentence among them). QVCGA keeps 4 of 7.
   - Alternatives I did not take: latest-first alone (it misses all four AMS key lines), or per-passage even shares (each passage would be ~500 characters and cut mid-sentence).
   - The rule names two phrases and no class or outcome. Rule on it, or tell me another.
3. **"liquidity" in the title** is the brief's wording. The match is only `going concern|substantial doubt`, so liquidity-only paragraphs are not selected.

## Other notes

1. **Every packet changes.** `builder_code` and `builder_version` differ, and most packets gain a gc_note and take 8-K body changes. DEV regression must be rebuilt in full (the brief says so).
2. **`TOTAL_CAP` pressure.** Four gc_notes, 24,000 characters at most, are added to packets that were already near 140,000 when all sections run to their caps. Trimming works as above, and the annual note comes after the 8-Ks, release and amendments. Watch `trimmed:` annotations in the rebuild.
3. **Repeated headings.** If the same item heading starts two lines (a page header "Item 8.01 (continued)"), each is its own segment and takes its own share. I did not merge them, and I did not measure how often this occurs.
4. **Residual exhibit text.** When the body consumes the cap, an exhibit may contribute only a few characters (QVCGA above). I kept the brief's "exhibits fill what remains" without a minimum.
5. **SBLX (FRESH)** was not probed. It is a FRESH case, and the brief lists only the DEV probes.
