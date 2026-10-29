# WO_N6: packet builder v6 for the measured packet gaps (builder brief, 2026-10-29)

**What this is for:** SPEC_m3n §7, systemic fixes after DEV.
- **This work does NOT touch the DEV run or its packets.** DEV is scored on builder v5 (`761f640` + contract `626e086`).
- v6 is prepared now so that, after DEV is scored, FRESH (and the DEV regression rerun) can use it.

**Where to work:**
- Branch `review-2026-10/m3n-v6`, made from `review-2026-10/m3n` (head `626e086`), in a NEW worktree: `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3n-v6`.
- Create it with `git -C C:\Users\riper\stocks\rs2-local worktree add -b review-2026-10/m3n-v6 <path> review-2026-10/m3n`.
- Never edit `wt-m3n` (the DEV run uses it) or `sec_primary.py`.

**Do not:**
- use the network (fixtures only);
- touch the GPU or Ollama;
- push;
- read or print any `.secrets.json` or `.env*` file.

**Read first:**
- `PREREG_m3n_amendment_5.md`, `PREREG_m3n_amendment_6.md` and `CROSS_CHECK_N_RULINGS.md` (same folder);
- `qwen_c/packet.py` (SECTIONS, `find_section`, `_other_8k`, `eight_k_body_lines`, the caps).

## The measured gaps (from frozen packets only, not from model output)

1. **Going-concern text sits in the notes to the financial statements**, outside every packet section (10-Q Part I Item 2 MD&A and Part II 1A; 10-K Items 1, 1A and 7).
   - **Cases:** DEV C2-1072-ALTS (10-K) and C2-1122-AMS (10-Q/A), and FRESH C2-24-SBLX (10-K, sentence at character 313,820 of 426,103).
2. **The 8-K body is cut at `OTHER_8K_CAP` (4,000 characters) from the first listed item heading.** When several items are listed, a later item's text is lost.
   - **Case:** C8-1053-QVCGA. Items 1.01, 1.03, 2.04, 7.01 and 9.01; the body starts at Item 1.01's long restructuring-support text, and Item 2.04's sentence ("The filing of the Chapter 11 Cases … constitutes an event of default that accelerated …") is cut.

## Builder v6 (`BUILDER_VERSION = "m3m.packet.builder.v6"`)

1. **A going-concern evidence item** (kind `gc_note`, title "… going concern and liquidity passages").
   - **Source:** from the primary document of the latest eligible annual report and of the latest eligible 10-Q (the same filings the packet already uses), the paragraphs whose text matches `going concern|substantial doubt`.
   - **Extent:** each with the paragraph before and after, merged where they overlap, in document order, to a new cap `GC_CAP = 6_000` per filing.
   - **Annotation:** a filing with no match is annotated `gc_text_not_found: <accession>`, which is a normal outcome.
   - **Order:** the items come after the P sections of their filing.
   - **Scope:** this is neutral (any going-concern or substantial-doubt paragraph, not selected by class or by any truth label). It is systemic: every packet gets it.
2. **The 8-K body is shared across its listed items.**
   - Each listed item of `OTHER_8K_ITEMS` gets its own segment, from its heading to the next item heading.
   - The cap is split evenly among the listed qualifying items. Space one segment does not use passes to the others.
   - Then EX-99.x fills what remains of `OTHER_8K_CAP`, as before.
   - A test must show that QVCGA's shape (a long 1.01 followed by a short 2.04) keeps the 2.04 sentence.
3. **Unchanged:** the total `TOTAL_CAP` trimming order. Say in the report how the new items rank in `_trim`, and pick the rule that drops `gc_note` after the release but before the statements. Justify it in the docstring.

## Tests

The existing suite must pass, plus new fixture tests for the two behaviours, a 10-K with no going-concern paragraph, and `TOTAL_CAP` trimming with a `gc_note` present.

## Report

`RR_N6.md` covers the commits, the tests, and the choices made.
- **Offline probes:** rebuild into a probe root, from the store at `…\wt-m3n\cache\m3m\raw`, the v5 packets of DEV C2-1072-ALTS T1, C2-1122-AMS T1 and C8-1053-QVCGA T1. Their arguments are in `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3n\n5\packets_v5.jsonl`.
- For each probe, report whether the key passage now appears; the key passages are in `m3n\n5\in_packet.json`.
- Report any `NotInStore` URLs rather than fetching them.
- **Do not open** any file under `m3n\n5\runs*`, `n6\` or the run directories. Model output is out of scope.
