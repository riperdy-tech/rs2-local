# RR_M4B: builder B2, the CROSS_CHECK_M rulings in contract.py, tasks.py and runner.py (2026-10-29)

Worktree `wt-m3m` (branch `review-2026-10/m3m-qwen`, base `f584410`). Nothing committed, pushed or checked out; no Ollama, model or
GPU contact; no secrets read. Files changed: `qwen_c/contract.py`, `qwen_c/tasks.py`, `qwen_c/runner.py`, `qwen_c/tests/test_contract.py`,
`qwen_c/tests/test_tasks.py`, `qwen_c/tests/test_runner.py`, `qwen_c/tests/fixtures_b/contract_cases.json`. `sec_primary.py` is not edited.

## Rulings applied (tests are in `qwen_c/tests/`)

| Ruling | Change | Test |
|---|---|---|
| 1.1 | `contract.py` has its own reader (`read_figures`): k, m, bn, tn (trillion/tn/capital T glued), %, x (x, ×), bp (bp, bps, basis point), pp (pp, ppt, percentage point); plurals read as the singular. `fig_matches`: units equal, k/m/bn/tn convert; a bare figure matches only a bare figure | `test_cross_check_m_q1_failing_inputs` (1.1 A, B, the MA `$10.6T` reverse case, bps/ppt), `test_the_number_rule`, `test_the_reader_reads_each_unit_and_currency` |
| 1.2 | Claim-side reader (claim text and `numbers` entries) reads a number after `.`/`,` not inside a number; the 19 ISO codes are currencies (RMB = CNY); H100/Q3/FY26/F1 still not figures | same parametrized test (1.2 A, B, C), `test_the_reader_reads_each_unit_and_currency` |
| 1.3 | In `a-b`, `a–b`, `a to b` a unitless lower bound takes the upper bound's unit (and its currency when it has none), items and claims alike | Q1 test: `8-10%`, `8 to 10%`, ILMN `$4.60-$4.64 billion`, en dash |
| 1.4 | `OMIT_RE` (and its NFKC "..." spelling) is removed from every text before figures are read | Q1 test: MA "65,074 employees", both spellings |
| 1.5 | Year exemption: bare 4-digit token, no comma, 1900-2100, directly after a listed year word, and printed by a cited item as a bare 4-digit token; decided per occurrence | Q1 test: "closed 2,025 stores", "closed 2025 stores", mixed claim, `$2,025 million`, `2,025 units`, mid-2025 / Q3 2025 |
| 3.4 | `tasks.prior_points` keeps only `support == "supported"` claims; `LEFT_OUT_LINE` states the count left out | `test_thesis_change_instruction_lists_the_prior_points_and_the_newer_items`, `test_thesis_change_is_sent_against_the_newest_prior_run` |
| 6.1a | `render_packet` prints "NOT IN THIS PACKET" with every `section_not_found`, `statement_not_found`, `no_eligible_filing` annotation verbatim ("none" when there is none); never `excluded` | `test_the_packet_rendering`, `test_not_in_this_packet_lists_only_the_missing_kinds_and_never_excluded` |
| 6.1c | Item header line carries `title` | `test_the_item_header_carries_the_title` |
| 4.1 | Empty reply (no claims, no unknowns) is a shape error, so `malformed` with one retry. `support_counts` per task (already there); run-level `support_summary` {claims, supported, unsupported} in analysis.json, the ledger line and the result | `test_an_empty_reply_is_malformed` (contract), `test_an_empty_reply_is_malformed_and_retried`, `test_a_clean_run_is_complete_and_every_record_recomputes` |
| 4.2 | `NUM_CTX = 98304`. Preflight: chars / 2.5 + num_predict > num_ctx is `context_overflow`, not sent (each attempt, retry prompt too). Post-check: prompt_eval_count + eval_count >= num_ctx - 1 is `context_overflow` | `test_the_preflight_refuses_a_prompt_that_cannot_fit`, `test_the_post_check_catches_a_reply_at_the_context_wall` |
| 4.3 | `check_task(..., point_ids)`: a `point` not among the earlier ids is a shape error; `points_not_addressed` recorded in analysis and manifest | `test_thesis_change_points_are_checked_and_unaddressed_points_recorded`, `test_a_thesis_change_claim_naming_a_point_that_is_not_listed_is_malformed` |
| 4.4 | New status `prior_unusable` (applicable, not ok, so `analysis_incomplete`). One-of-two prior: `MISSING_LINE` in the instruction, `prior_run.tasks_missing` in the manifest | `test_a_prior_without_ok_growth_or_risks_is_prior_unusable`, `test_a_prior_with_one_task_not_ok_names_it_in_the_instruction_and_the_manifest` |
| 4.5 | `find_prior` reads `read_ledger()` (finished runs missing from the ledger included, `ledger_missing` recorded). `_read_jsonl` skips and records a torn last line; a torn middle line raises | `test_a_finished_run_missing_from_the_ledger_is_still_the_prior`, `test_a_torn_last_ledger_line_is_skipped_and_reported_and_not_appended_after`, `test_a_torn_middle_ledger_line_still_raises` |
| 4.6 | 200 with `error`, or empty response with `done` not true, is `infra_retry` (unload, one retry); `done_reason == "length"` named in the malformed cause | `test_an_http_200_error_or_empty_response_is_an_infra_retry`, `test_a_reply_cut_at_num_predict_names_done_reason_length` |
| 6.3 | `gpu_preflight`: `/api/ps`; any model other than `MODEL`/`MODEL:latest` is `RunRefused("gpu_busy: ...")`, before anything is written | `test_another_resident_model_refuses_the_run_and_writes_nothing` |
| 6.4 | `model_show`: `/api/show` parameters, details, modified_at and the response sha in `manifest.model.show`. Temperature not changed | `test_no_model_parameters_refuses_the_run`, clean-run test |
| Pins | `PROMPT_VERSION` stays `m3m.prompt.v1`; re-pinned `thesis_change` and `render_packet(packet_acme)`, added `LEFT_OUT_LINE` and `MISSING_LINE` (also run through the banned-vocabulary test). SYSTEM and the six instructions are unchanged | `test_prompt_version_and_pinned_hashes` |

## Deviations (each the more conservative reading)

1. **Currency must be equal too (1.1).** "A bare figure matches only a bare figure" read with this code's meaning of bare (no currency,
   no unit), applied to currency as well: a figure with no currency no longer matches a printed `$`/`€` figure. Otherwise "1.2 billion
   dollars" would be `supported` by "€1.2 billion". Effect: "1.2 billion" is no longer found in "$1.2 billion".
2. **More currencies than the ISO list (1.2):** the yen, won and rupee signs, and 1-3 capitals glued to `$` (HK$, S$, NT$, R$), each its
   own currency. ISO codes are read in capitals only, so "we try 5" has no currency.
3. **A prior with no supported claim is `prior_unusable`** (`prior_run_problem.kind = "no_supported_points"`), not sent with an empty point list.
4. **`check_task` for `thesis_change` without `point_ids`** treats every point as unknown, so the shape check fails.
5. **Ledger writer (4.5 rules the reader only):** while the last line is torn the run does not append (that would bury the torn line
   mid-file and make every later read raise). It records `ledger_not_appended` and `ledger_appended: false`; read_ledger still lists the run.
   A whole last line with no newline gets one before the append.
6. **`/api/ps` unreadable is a refusal (`gpu_state_unreadable`)**; names are matched exactly, so another tag of the v33 name is "other".
7. **`/api/show` failing or with empty `parameters` is a refusal (`model_show_failed`)**, since the sampling in force would be unrecorded.
8. **A reply with no `prompt_eval_count` is `context_overflow`**, because the post-check cannot be made.
9. **Point ids keep the claim's stored position** (G1, G3 when G2 was unsupported), so an id names one stored claim.
10. **Year words:** full month names only (no "Dec"); "directly preceded" allows spaces or one hyphen ("mid-2025"). A range's lower
    bound keeps its own currency if it has one.

## Fixture outcomes changed (all stay unsupported; `note` added in `contract_cases.json`)

`supported_claims` claim 7 (bare 310.5 against "$310.5 million") and `percent_word_is_percent` claim 2 (bare 9.1 against 9.1%) are now
`number_not_found` under 1.1. Claims 2 and 3 of `unlisted_number` now fail first on `number_not_found` (deviation 1 and 1.1);
`number_not_listed` is still recorded for each. `point_ids: ["G1"]` added to the two thesis_change cases. In
`test_every_claim_number_is_listed_and_found` the item's `$ 1,234` became `1,234`, so the bare-figure cases test what they did before.

## Verification

- `"C:\Program Files\Python312\python.exe" -m pytest -q -p no:cacheprovider qwen_c/tests`: **262 passed, 6 errors.** All 6 errors are
  conftest teardown errors ("test wrote into production cache/"): A2's live rebuild was writing `cache/m3m/raw/receipts.jsonl` and the
  new `cache/m3m/packets/*_20261029T021310Z.json` while the suite ran. Five are in A2's test files and one in
  `test_contract.py::test_the_reader_reads_each_unit_and_currency`, which touches no files. Run on their own, my three files give **169 passed**.
- Every Q1 failing input of the reply was checked by hand and in tests; the reader ran without error over all ten real packets (old
  `T013151Z` and A2's new `T021310Z`): MA's `$10.6T` reads as trillion.
- Preflight on the real packets at `NUM_CTX = 98304`: all ten fit. The largest is ECPG `T013151Z` at 65,204 estimated tokens (with the retry line).

## For the coordinator

- **Spec drift:** `SPEC_m3m_qwen_pipeline.md` §6 still gives `num_ctx` 65,536 and no `prior_unusable`, and §5 describes the old number rule.
  The spec is outside my file list, so it is not edited.
- **Post-check limit (not measured, check in M-LIVE):** if Ollama's `prompt_eval_count` counts only the tokens not served from the
  prefix cache, the post-check cannot see an overflow on tasks 2-7, which share the packet prefix. The preflight is then the effective guard.
- **Not in NOT IN THIS PACKET:** `release_stale` (A2's 6.2c) is not listed, because the ruling names three kinds. Rule on whether it should be.
- Remaining limits, recorded: unit or currency words outside the list ("pct", "dollars") read as bare / no currency (deviation 1 limits
  the harm); there are existing misreads that can only fail a claim ("10-K" gives a bare 10, "1,2,3" gives 123); the GPU is checked once,
  at run start, and a llama-server outside Ollama is not visible to `/api/ps`.
