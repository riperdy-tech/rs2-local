# AUDIT_N6: packet builder v6 (2026-10-29)

**Verdict: APPROVED**, with both open choices ruled below. Branch `review-2026-10/m3n-v6`, worktree
`scratch/rev23/wt-m3n-v6`. Commits `3994c88` and `c4f46d0` (builder), plus `035ef96` (Claude, the `find_prior` fix).

## What I checked

- **The diff, line by line** (`git diff 626e086 HEAD -- qwen_c/packet.py`, 154 lines):
  - `_share`: the budget is the cap less the joining newlines; the shortest text goes first and takes at most an equal
    share of what is left. Correct for one segment, for all segments fitting, and for one long segment.
  - `eight_k_item_segments`: one segment per heading of a listed item, to the next heading. Only `OTHER_8K_ITEMS`
    segments are kept; a body with none falls back to v5's reading.
  - The exhibit reserve keeps a marker's room, so the final cut cannot clip the body's tail.
  - `gc_passages`: the match is the two phrases only. A line already shown in that filing's sections neither matches
    nor repeats. The priority sort is stable: `substantial doubt` passages first, later first within each group. The
    output is in document order with gap markers. One passage over the cap is cut by the caller.
  - `_core`: the note follows its own filing's items; `_trim` is untouched, so the drop order is as RR_N6 states.
- **Tests:** I reran the full suite myself on `c4f46d0`: **387 passed** (175 s). The builder's count reproduces.
- **Scope:** only `qwen_c/` changed; `wt-m3n` and `sec_primary.py` untouched; no run output was opened (RR_N6).
- **The probes:** the builder first rebuilt the three v5 packets to their logged sha256, which shows the store and
  arguments are right. I did not repeat the v6 rebuilds; they are rebuilt in full for FRESH and the DEV regression.

## Rulings on the open choices

1. **Amendments (`c4f46d0`): kept.** The rule is "every filing whose text the packet already uses gets its
   going-concern passages". The brief's two-filing list was narrower than its own reason. It is the same rule for every
   packet and names no case. AMS (DEV) motivated it, so FRESH is where it is tested, as SPEC_m3n §7 intends.
2. **The over-cap rule: accepted.** It is neutral (two phrases, no class or outcome), and the document-order cut was
   measured to keep boilerplate and lose the note. Recorded limit: when a filing has more than 6,000 characters of
   passages, which survive depends on the phrase priority. The `gc_passages_omitted` annotation makes that visible.
3. **"liquidity" in the title:** kept as the brief worded it. The title is a label; the match rule is in the docstring.

## Notes carried

- Every packet changes. FRESH and the DEV regression use v6 packets only, never a mix (SPEC_m3o §4 uses the same rule).
- Watch `trimmed:` annotations in the rebuild (up to four gc_notes against `TOTAL_CAP`).
- A line inside a body that begins with an item heading starts a new segment. Its frequency is not measured; the rebuild
  will show it if segment counts exceed listed items.

## `035ef96`: the `find_prior` fix (AUDIT_N2 condition 3)

- `find_prior` skips a run that requested neither `growth_thesis` nor `risks`. Its requested tasks come from the
  ledger line, else from the run's manifest. A run whose requested tasks cannot be read stays a candidate, so the
  existing record checks still apply to it, and an older run is still never used in its place.
- The ledger line gains `tasks_requested`. The runner owns the ledger line, so this is the owner adding its field.
- Two new tests: a newer `material_events`-only run is not the prior; a `risks`-only run is the prior, and old lines
  without the field are read from the manifest. `test_runner.py`: 68 passed.
- This matters for 3O/3P: a monitoring subset run must not break the next full run's `thesis_change`.

## Addendum 2026-10-29 (~14:45Z): v6 failed the CROSS_CHECK_O 6a regression test; v7 fixes it

**The test.** `m3n/n7_v6_regression.py` rebuilds all 84 DEV v5 packets offline with the new builder and checks every
T1/T2 key passage against `in_packet.json`. It reads no model output.

**The v6 result.** v6 lost three cases that v5 carried:
- PTHS T1 and T2 (exact to equivalent);
- EONR T2 (exact to absent).

The cause is systemic. The going-concern notes counted against `TOTAL_CAP`, and `_trim` cuts from the end of the list,
so the extra note text pushed out the event 8-Ks (PTHS Item 4.02, EONR Item 3.01). Trim annotations rose from 3 (v5)
to 15. RR_N6 had flagged this pressure, and I approved v6 without measuring it. I was wrong to approve it unmeasured.

**v7 (`4bc9425`).**
- `_trim` neither counts nor cuts gc_notes. Every other item is trimmed exactly as in v5.
- Each note stays bounded by `GC_CAP`, so a packet is at most 140k + 24k characters. That is about 66k tokens against
  `NUM_CTX` 98,304.
- The trim test was rewritten to pin this.

**Suite:** 389 passed on a run by itself. A first run reported 80 teardown errors. The cause was my concurrent rebuild
writing into the worktree's `cache/` while the suite's cache guard watched it. That was not a code defect, and the
rerun alone is clean.

**v7 rebuild** (`n7/regression_v7.json`): 84 of 84 built, **0 regressions**.

| | v5 | v7 |
|---|---|---|
| exact / equivalent / absent | 37 / 2 / 7 | 43 / 1 / 2 |
| trim annotations | 3 | 2 |

- Improved: ALTS, AMS and QVCGA, at both T1 and T2.
- Still absent: FFAI T2 and BWEN T2. Both were absent in v5 too.

**Verdict on v7: APPROVED.** FRESH, the DEV regression and the 3O formations use v7.
