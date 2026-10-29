# RR_M4A: builder A2 return report (WO_M4, CROSS_CHECK_M rulings on `qwen_c/packet.py`)

- **Worktree:** `scratch/rev23/wt-m3m`, branch `review-2026-10/m3m-qwen` at `f584410`, uncommitted. Nothing was committed, pushed or checked out, and no model or GPU was used.
- **Files changed:** `qwen_c/packet.py`, `qwen_c/tests/test_packet.py`, `qwen_c/tests/test_replay.py`, and `qwen_c/replay.py` (2 lines plus its docstring; see D1).
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest -q -p no:cacheprovider qwen_c/tests` gives **262 passed**. My three test files give 93 passed.

## Rulings

| Id | Change in `packet.py` | Test |
|---|---|---|
| 2.1 | `check_run_time`: the pinned row's `run_updated_at` must be a zoned ISO time at or before T. Refusal codes: `verified_run_time_missing` (absent, null, empty, naive or unreadable) and `verified_run_after_T`. It runs in `_core`, so replay repeats the check. | `test_a_verified_row_without_a_run_end_by_T_is_refused` (6 cases), `test_a_run_that_ended_exactly_at_T_is_accepted`, `test_replay_reruns_the_run_time_check_on_the_pinned_verified_row` |
| 2.3 | `check_filings_window`: refuses `T_before_filings_recent` when T is older than the earliest readable acceptance in `filings.recent`, and also when no row is readable (D6). | `test_T_older_than_the_oldest_filings_recent_row_is_refused` (1 s before vs exactly at), `test_an_empty_filings_recent_is_refused` |
| 3.1 | S0 is the whitelist `S0_FIELDS`, in the ruled order. `Last_Updated` prints as `price as-of (Last_Updated, zone not stated)`, and a missing field prints `absent`. No value from `factor_scores_dual_door.json` reaches evidence; `factor_blob_sha` stays in the header. The Yahoo `description` is gone. | `test_s0_is_the_identity_and_market_whitelist_only` (the reviewer's inputs: `rev_mos`, `rev_band`, the `rev_con` narrative, doors, scores, `forwardEpsEstimate`, `pegRatio`, `peRatio: 0`, `netIncome: 0`, the "79 containerships and 38 dry bulk" description; all absent), `test_s0_lines_print_zero_as_zero_null_as_null_and_a_missing_field_as_absent` |
| 5.1 | `screener.verified_row` = `{run_id, verdict, pair, output_commit, run_updated_at}` as found. It replaces `verified_run_id`. | `test_the_real_check_new_runs_row_shape_is_pinned_and_other_runs_are_visible` (the reviewer's input: two records with run ids 40796224964 and 40799999999 now give visibly different headers), `test_a_packet_without_a_pinned_verified_row_is_refused_on_replay` |
| 5.2 | The module docstring now says "over the same store state". It notes that `get` serves the latest receipt, and that the determinism gate is `replay` / `get_pinned`. | docstring only |
| 5.3 | Top-level `builder_code` holds: the sha256 of `packet.py`, `sec_primary.py` and `sec_guidance.py` (CRLF normalised to LF), plus the `exchange_calendars` and `tzdata` versions. `check_T_in_calendar` refuses `T_outside_calendar` for a T before the first session open, and for a T whose own effective session falls past the end of the calendar. | `test_T_outside_the_calendar_is_refused` (5 cases, incl. 2031-12-30 18:00 ET), `test_the_calendar_bounds_that_are_inside`, `test_builder_code_pins_the_source_files_and_the_calendar_libraries`, `test_a_changed_builder_source_is_not_identical_on_replay` |
| 6.1b | `_other_8k`: the 8-K body from its first heading of an item the filing lists, then the EX-99.x exhibits in file order, up to the 4,000 cap. No other exhibit is read. The title lists only the documents the kept text reaches. A body with no listed-item heading is never used and is annotated `8k_item_heading_not_found`. `_main_exhibit` is no longer imported. | `test_other_8k_is_the_body_from_its_first_listed_item_and_never_a_contract` (the reviewer's ILMN P4 shape plus EX-9.01 / 4.2 / 1.1 / 3.1 / 5.1), `test_other_8k_body_then_ex99_and_the_title_names_only_what_the_cut_text_reaches`, `test_other_8k_without_a_listed_item_heading_uses_no_cover_page`, `test_eight_k_body_lines_start_at_the_first_heading_of_a_listed_item` |
| 6.2a | `amendment` items: up to 2 eligible 10-K/A, 10-Q/A, 20-F/A or 40-F/A accepted after the chosen annual report, newest first. Each is the primary document from its first Item heading, at most 4,000 characters. The slot is `amendment` in `excluded`. A missing heading is annotated `amendment_text_not_found`. | `test_an_amendment_after_the_annual_report_is_an_item_from_its_first_item_heading` (HRTG shape), `test_at_most_two_amendments_newest_first_and_a_contents_entry_is_skipped`, `test_amendment_lines_rules` |
| 6.2c | A release accepted more than 120 days before T (`RELEASE_MAX_DAYS`) is not used and is annotated `release_stale: <acc> accepted <raw>, more than 120 days before T`. | `test_a_release_accepted_more_than_120_days_before_T_is_not_used` (exactly 120 days is used; +1 s is stale) |

## Deviations (each is the more conservative or the minimal reading)

- **D1. `replay.py` was edited**, although it is outside my file list. `_core` now takes the pinned verified row instead of a run id, so replay passes `pk["screener"].get("verified_row")`. That is one line plus its docstring, and B2 does not own the file.
- **D2.** `builder_code` also pins `sec_guidance.py`. Its `_has_item_202` decides which 8-K is the release.
- **D3.** 40-F/A is counted as an amendment form, the same class as 20-F/A.
- **D4. Meaning of "first Item heading" in an amendment.** I read it as the first item heading that is followed by at least `SHORT_MIN_CHARS` (100) characters before the next heading of a different item. Without that rule, a contents row would become the evidence.
- **D5. Meaning of "first listed Item heading" in an 8-K.** "Listed" means listed in the filing's own `items` field. So ECPG 0001084961-26-000052 starts at Item 7.01, which is listed there but is not in `OTHER_8K_ITEMS`. The old code fell back to the cover page when it found no heading; that fallback is removed.
- **D6.** A `filings.recent` with no readable row is refused too: there is no oldest row to compare T with.
- **D7. Version strings.** `BUILDER_VERSION` is now `m3m.packet.builder.v2`. `CONTRACT` stays `m3m.packet.v1`, because `runner.PACKET_CONTRACT` checks it.
- **D8. Other S0 details.** S0's `raw_sha256` is now a single string (the stocks blob) and `source.path` is a single path. The `ticker_not_in_factor_profiles` refusal is kept: it reads the factor file for membership only. Amendments sit after the quarterly sections and before the release. With no annual report, any eligible amendment qualifies, the same as the quarterly rule.

## Real-data rebuild

- **T:** `2026-10-29T02:13:10Z`, from `date -u`.
- **Inputs:** commit `92592e2156`, record `check_20261029T015407Z.json` (run 40796224964, `run_updated_at` 2026-10-29T01:13:38Z), online, `STOCKS_ROOT=C:\Users\riper\stocks`.
- **Saved with `packet.save`** as `cache/m3m/packets/<T>_20261029T021310Z.json`. The `T013151Z` files are untouched.
- **Builder pins:** `packet.py` LF sha256 `8f8e8fdb…a711`; exchange_calendars 4.13.2; tzdata 2025.2.

**Evidence per packet:**

| Ticker | packet sha256 | Evidence ids and kinds |
|---|---|---|
| MA | `da50102d…` | S0 screener_row; F1–F3 statement (10-Q); P1–P3 annual_section; P4–P5 quarterly_section; P6 release |
| CMRE | `beb2c056…` | S0; F1–F3 (20-F); P1–P3 annual_section. Annotated: no quarterly, no release (a 6-K filer, NOTE 6.2b) |
| HRTG | `c9a2dd32…` | S0; F1–F3; P1–P3 annual; P4–P5 quarterly; **P6 amendment** (10-K/A 0001193125-26-115451, from Item 8); P7 release. Excluded: Q3 8-K 0001193125-26-436203 (effective 2026-10-30T13:30Z) |
| ILMN | `537809e2…` | S0; F1–F3; P1 release; P2–P5 other_8k, all `(8-K body)`. Five `section_not_found`, as before |
| ECPG | `2539ed47…` | S0; F1–F3; P1–P3 annual; P4–P5 quarterly; P6 release; P7 other_8k `(8-K body, EX-99.1)`; P8 other_8k `(8-K body)` |

- **ILMN is confirmed.** Each other-8-K item now opens at its Item heading and holds 8-K body text:
  - P2 opens at "Item 1.01. Entry into a Material Definitive Agreement" and states the $1.0 billion CP program; no `[●]` form template.
  - P4 opens at "Item 1.01" and states the $1,000 million five-year revolver; no credit-agreement cover.
  - P3 and P5 open at "Item 8.01" and state the $300,000,000 4.950% notes.
  - No EX-1, EX-4, EX-9.01 or EX-10 text appears.
- **`python -m qwen_c.replay` exits 1.** All 5 new packets are `identical: true`. The 5 old `T013151Z` packets are refused with `verified_run_time_missing`: they predate the pinned row. A copy of the 5 new packets alone in a scratch folder replays with exit 0.

## For the coordinator

1. **Ruling 6.2a drops HRTG's explanatory note.** The note sits before Item 8 and says the 10-K/A is filed "solely to add the date" of the auditor's report, and that Item 8 is unchanged. Starting at the first Item heading leaves the model a 10-K/A Item 8 with no reason given, which invites a false "restatement" reading. Suggested ruling: start at an `EXPLANATORY NOTE` heading when one precedes the first Item heading. I did not change this; the ruling's wording is the spec.
2. **New annotations are not listed for the model.** `release_stale`, `amendment_text_not_found` and `8k_item_heading_not_found` are not among the prefixes B2's "NOT IN THIS PACKET" list shows, per the 6.1a wording. `release_stale` means the release is missing from the packet.
3. **The replay gate over `cache/m3m/packets/` will keep failing** while the old packets sit there. Moving or archiving them is your call; I moved nothing.
4. **Rebuild after any edit to the builder files.** `builder_code` pins the working-tree bytes of `packet.py`, `sec_primary.py` and `sec_guidance.py`. Any audit edit to them makes the 5 new packets non-identical by design, so they must be rebuilt.
5. **Latent defect, not fixed (outside the rulings).** A `filings.recent` row accepted before 2005 raises `DateOutOfBounds` in `_filing_rows`. It fails loudly, not silently. None of the 5 tickers is affected: their oldest rows are from 2010 to 2019.
6. **Residual of 2.3.** When `filings.files` is non-empty (ECPG, ILMN and MA have 1 to 2 files), a T just after the oldest recent row could still miss an older annual report. With a prospective T this has no effect now.
7. **SPEC §3 is now stale** on S0 (it says full record plus factor profile) and on the header fields. The spec is outside my files.
8. **Placeholder zeros remain in the data.** At `92592e2156`, 131 rows have `price` 0 and 882 have `marketCap` 0. They print as 0 (non-negotiable 4). None of the 5 tickers has one.
