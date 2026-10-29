# RR_N5: qwen_c packet builder v5 (builder report, 2026-10-29)

Work order: `WO_N5.md`. Worktree `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3n`, branch `review-2026-10/m3n`, base `a252f6e`. Only `qwen_c/` changed; `sec_primary.py` is untouched. No network, no GPU, no push, no `.secrets.json` or `.env*` read.

## Commits

One commit on `review-2026-10/m3n`, by pathspec (`qwen_c/packet.py`, `qwen_c/tests/test_packet.py`, `qwen_c/tests/test_replay.py`):

- `761f640` qwen_c: packet builder v5 - the release slot keeps its other items, the release reads every EX-99.x, Item 7.01 (WO_N5)

## What changed (`qwen_c/packet.py`, `BUILDER_VERSION = "m3m.packet.builder.v5"`)

1. **The release slot keeps its other items.** The `rel_acc` exclusion is gone from the `other_8k` pick. The release-slot 8-K is now an ordinary candidate: it yields an `other_8k` item exactly when it lists an item of `OTHER_8K_ITEMS` (2.02 is not in that tuple), it is built by the unchanged `_other_8k`, it is ordered newest first with the others, and it counts toward `MAX_OTHER_8K`. A release-slot 8-K with no readable release exhibit still gets its `other_8k` item, and `release_exhibit_not_found` is annotated as before.
2. **The release reads every EX-99.x exhibit.** New `_release_docs(docs)` is qwen_c-local: `sec_primary._release_doc` hard-codes EX-99.1, EX-99.01 and EX-99 and returns one, so it is no longer imported. The exhibits are taken in exhibit order (EX-99, then by number; EX-99.01 is 1; a non-numeric suffix such as EX-99.A after the numbered ones, in file order), their blocks are joined, and `sec_primary.select_text` cuts the whole to `RELEASE_CAP`. A single-exhibit release gives the same text as before. The title names the exhibits the kept text reaches.
3. `OTHER_8K_ITEMS` gains `"7.01"`.
4. Unchanged: acceptance rule, caps, ordering and trimming, regimes. The module docstring and the `BUILDER_VERSION` comment say what v5 is.

The packet `builder_code` pin changes with the file, as designed, so every stored v4 packet is "not identical" under replay, which already says so by `builder_version`.

## Tests

- Baseline at start: 363 passed in `qwen_c/tests`.
- Now: **372 passed** in 186 s (363 + 9 new), run clean after the commit's code was final. (An earlier full run printed two teardown errors from the repository's production-cache guard because my probe wrote `cache/m3n/packets_v5_probe/` while the suite ran; with the probe files written beforehand the suite is clean.)
- Nine new tests in `test_packet.py` (section "WO_N5: builder v5"): constants; a 2.02 + 4.02 8-K with no EX-99 (item carries the 4.02 text, `release_exhibit_not_found` kept, newest-first order); the same 8-K with an EX-99.1 (release and other item both); a 2.02 + 9.01 8-K yields no other item; the release-slot 8-K counts toward `MAX_OTHER_8K` (five candidates, four kept, the oldest left out; the old code gives a different list); a 7.01-only 8-K is an `other_8k` item; every EX-99.x read in exhibit order (file order shuffled, a contract exhibit not read); the exhibit-order function; the cut over two exhibits (the EX-99.2 outlook paragraph survives the cap, the title names both, the cap holds).
- Four existing assertions had to change, and only because of the brief's own rules:
  - `documents()` gains a document for the 7.01 8-K (`A701`), which was in the submissions but was never an `other_8k`; it is now one, so the full-build test lists P6, P7, P8 (A801, A701, A502) instead of P6, P7;
  - the size-cap test now trims three other-8-K items before the release;
  - `builder_version` v4 becomes v5 in `test_packet.py` (twice) and in `test_replay.py` (the "previous builder" test).

## OPTU probe (offline, from the store)

Built C3-04-OPTU T1 (`T = 2026-09-23T13:30:00Z`, frame commit `376745894f92...`, regime `archival_sec_acceptance_v1`, `cik 0001702780`, `screener_repo_path` the stock-screener checkout) with `online=False` and `store_root = wt-m3n\cache\m3m\raw`. **It built; nothing was missing from the store, so there are no `NotInStore` URLs.**

- Saved: `wt-m3n\cache\m3n\packets_v5_probe\OPTU_20260923T133000Z.json`, sha256 `c9f4f36a00edfbc7e260bd428e869a37e92580d9f2a2507c19e0bf154fcf933e` (v4 stored packet: `d5a08bd4...`).
- **The 4.02 text now appears, in P6**: `other_8k`, accession 0001702780-26-000057, title "8-K Items 2.02, 4.02, 9.01 (8-K body)", 3,997 characters. It holds the "Item 4.02(a). Non-Reliance on Previously Issued Financial Statements ..." heading and its text ("should no longer be relied upon ...", the intent to restate) from character 943; the cut falls in the "Summary of Impacts" part, after the non-reliance conclusion.
- Annotation unchanged: `release_exhibit_not_found: 0001702780-26-000057` (the filing has no EX-99), no release item.
- The v4 packet had P6, P7, P8 as other items (the 3.01/7.01 filing 0001702780-26-000052, 0001104659-26-080797, 0001213900-26-063161); v5 has the 4.02 filing first and those three after it as P7, P8, P9. Total evidence text 121,343 characters (under `TOTAL_CAP`), nothing trimmed.
- Extra, because the brief names it: C7-43-YEXT T1 (`YEXT_20260604T133000Z.json`, same folder) also built offline. Its release now reads EX-99.1 and EX-99.2 (title names both; 13,563 characters) and the shareholder letter's "suspend forward guidance and quarterly earnings calls" sentence is in the release text. The YEXT 2.02/8.01 8-K also became an `other_8k` item (P7, 3,997 characters), which is the duplicated-exhibit effect described below.

## Choices the brief did not fix

1. **Where the other-item body starts.** "Built exactly as other 8-K items are built" was taken literally: the body starts at the first heading of any item the filing lists (`eight_k_body_lines(lines, all listed items)`), not at the first heading of a `OTHER_8K_ITEMS` item. For a 2.02 + 4.02 8-K that means the Item 2.02 paragraph comes first, then 4.02 (as in OPTU above). Starting at the first qualifying item instead would skip a long 2.02 body, but it would also change the existing other-8-K items (for example an 8-K listing 5.07 before 8.01). Not done; the lead can rule.
2. **The release exhibit text is repeated in the other item.** A release-slot 8-K that lists 8.01 or 7.01 beside 2.02 now gives its EX-99.x text twice: in full to `RELEASE_CAP` in the release, and again after the body in the `other_8k` item up to `OTHER_8K_CAP` (YEXT above). The brief's rule makes it so. A consequence of rule 1 with rule 3: 8-Ks that list 2.02 and 7.01 (a common pair) now take an `other_8k` slot, and 7.01-only investor-presentation 8-Ks now compete for the four slots with 5.02, 4.02 and the rest. `MAX_OTHER_8K` stays 4 as the brief says; the lead may want to watch crowding in the DEV rebuild.
3. **Exhibit order** is by exhibit number, not file order, with EX-99 first (so a file that lists EX-99.2 before EX-99.1 still reads 99.1 first). The old priority (EX-99.1 before EX-99.01 before EX-99) is replaced by "EX-99, then EX-99.1/99.01 (same rank), then higher". When both EX-99 and EX-99.1 exist, EX-99 now comes first.
4. **One combined cut.** The exhibits are joined and cut by `select_text` once, not budgeted per exhibit, so a very long EX-99.1 can still crowd EX-99.2 out; what survives is the start, the outlook and guidance paragraphs (from any exhibit), then tables. The cut text carries the usual omit markers and no exhibit labels (the other-8-K item has none either).
5. **Release title** names the exhibits the kept text reaches, decided by whether the first 40 characters of one of an exhibit's selection units occur in the kept text. For one exhibit that fits, the title is exactly the v4 title. The test is a presence check, not a provenance proof; a boilerplate line repeated in two exhibits could name an exhibit whose own text was cut.
6. `sec_primary._units` (private) is imported for the title check, as the module already imports other private `sec_primary` names.
7. The probe shows U+FFFD characters in some 8-K text ("the Company�s"): `_decode` falls back to cp1252 with `errors="replace"` for submissions that mix encodings. Pre-existing, not touched, and it does not affect the 4.02 text found.

## Files

- `qwen_c/packet.py`, `qwen_c/tests/test_packet.py`, `qwen_c/tests/test_replay.py` (edited).
- Probe scripts live in the session scratchpad, not in the repository; the probe output is the two files in `wt-m3n\cache\m3n\packets_v5_probe\`.
