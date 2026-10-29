# WO_N5: qwen_c packet builder v5 (builder brief, 2026-10-29)

**Read first:**
- `CROSS_CHECK_N_opus.md` finding 4 and `CROSS_CHECK_N_RULINGS.md` (same folder);
- `SPEC_m3n_event_validation.md` §3;
- `C:\Users\riper\stocks\AGENTS.md` and the worktree's `AGENTS.md`.

**Where to work:**
- **Worktree:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3n`, branch `review-2026-10/m3n` (head `a252f6e`). Change only `qwen_c/`.
- **`sec_primary.py` is a shared rs2 production module and must NOT be edited.** Anything new goes in qwen_c's own code.
- **Do not:**
  - push;
  - use the network;
  - run a GPU job;
  - read or print any `.secrets.json` or `.env*` file.
- **Commits:** commit by pathspec, with messages ending in `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Style:** match the existing code and docstring style, and give every rule a docstring sentence.

## The defect (measured)

`qwen_c/packet.py` around lines 856–870: an 8-K chosen for the earnings-release slot (Item 2.02) is kept out of `other_8k` (`rel_acc`). The release reader (`sec_primary._release_doc`) reads only EX-99.1, EX-99.01 or EX-99.

**The failing case, C3-04-OPTU:** 8-K 0001702780-26-000057 has items 2.02, 4.02 and 9.01 and no EX-99. It yields `release_exhibit_not_found` and no item, so its Item 4.02 non-reliance text never reaches the packet.

**Related:**
- YEXT's 2.02 8-K has its guidance text in EX-99.2, which is never read.
- Item 7.01 is not in `OTHER_8K_ITEMS`.

## Builder v5 (`BUILDER_VERSION = "m3m.packet.builder.v5"`)

1. **The release slot keeps its other items.** An 8-K used for the release slot that also lists any item of `OTHER_8K_ITEMS` other than 2.02 also yields an `other_8k` item. It is built exactly as other 8-K items are built (the body from its first listed qualifying Item heading, then EX-99.x, to the caps). It counts toward `MAX_OTHER_8K` like any other.
   - **A release-slot 8-K with no readable release exhibit** still yields its other-item `other_8k` item, with the `release_exhibit_not_found` annotation unchanged.
2. **The release reads every EX-99 exhibit.** Every `EX-99.x` exhibit (EX-99, EX-99.1, EX-99.2, …, in exhibit order) is read up to `RELEASE_CAP` in total, not only the first. Implement it in qwen_c, reusing `sec_primary` helpers only by import. If a reused helper hard-codes EX-99.1, write a qwen_c-local reader and say so in the docstring.
3. **`OTHER_8K_ITEMS` gains `"7.01"`** (Regulation FD releases).
4. **Unchanged:** the acceptance rule, the caps, the item ordering and trimming, the regimes.

## Tests

The existing suite must pass, plus new tests for:
- a 2.02 + 4.02 8-K with no EX-99, which yields an `other_8k` item carrying the 4.02 text;
- a 2.02 8-K with EX-99.1 and EX-99.2, where the release contains EX-99.2 text;
- a 7.01-only 8-K, which is now an `other_8k` item;
- `MAX_OTHER_8K` still applying.

Use fixture HTML in the style of `qwen_c/tests/fixtures*`.

## Offline check

- Rebuild one stored packet offline from the store (`C:\…\wt-m3n\cache\m3m\raw`) with v5, for example the OPTU T1 packet. Its arguments are in `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3n\n5\packets.jsonl`, case C3-04-OPTU, kind T1.
- Use `regime="archival_sec_acceptance_v1"`, `screener_repo_path=C:\Users\riper\stocks\stock-screener`, and `cik` from that record.
- Online fetching is not allowed. If v5 needs a document the store lacks, the build raises `NotInStore`; report which URLs. The lead will fetch them.
- Save the rebuilt packet only under a scratch root: `save(pk, root=…\wt-m3n\cache\m3n\packets_v5_probe)`.

## Report

`RR_N5.md` in the orchestration folder covers:
- the commits;
- the test counts;
- the OPTU probe result (does the 4.02 text now appear, and in which item);
- every choice this brief did not fix.
