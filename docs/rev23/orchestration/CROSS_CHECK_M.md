# CROSS_CHECK_M: the 3M Qwen pipeline, before its first GPU run (2026-10-29)

**Reviewer brief:** you are an outside reviewer. Your reply is advice, and Claude rules on each point. Read the files
below, then answer the questions. Be concrete: name a file and a line, and give the failing input. Do not edit any file.

## What was built

The code is `rs2-local` branch `review-2026-10/m3m-qwen`, commit `42640f8`, at
`C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3m\qwen_c\`:

| File | What it holds |
|---|---|
| `packet.py` | The input contract: SEC acceptance rule, evidence items, refusals, caps |
| `sec_store.py` | The raw byte store |
| `replay.py` | The pack replay gate |
| `tasks.py` | The SYSTEM text and the seven task instructions |
| `contract.py` | The output contract and the citation and number checks |
| `runner.py` | Calls, statuses, retries, records |

- **Design:** `orchestration/SPEC_m3m_qwen_pipeline.md`.
- **Audits:** `AUDIT_M3.md`. The builder reports are `RR_M2.md` and `RR_M3.md`.
- **Real packets:** `wt-m3m/cache/m3m/packets/*.json` holds 5 packets (MA, CMRE, HRTG, ILMN, ECPG), all built at
  T = 2026-10-29T01:31:51Z.

## Measured so far

- **Tests:** 175 pass.
- **Replay:** all 5 real packets rebuild byte-identically offline from the pinned raw bytes.
- **Exclusion:** HRTG's Q3 earnings 8-K, accepted at `2026-10-28T20:25:14.000Z`, is excluded with effective time
  2026-10-30 13:30Z. The rule takes the later of the UTC and the Eastern-wall readings, and the filing falls after
  17:30 ET, so it gets one more session.
- **Missed sections:** ILMN's 10-K and 10-Q sections are not found, because they use a cross-reference-index layout
  with no "Item" headings in the body. They are annotated, not guessed.

## Questions we most want challenged

1. **False `supported`.** Can a claim come out `supported` while its figure or quotation is not in a cited item?
   Look at `contract.check_claim`, `figures_of` and `fig_matches` (scale words, %, currency, parentheses, years
   exempted 1900–2100).
2. **Look-ahead.** Can any evidence that became public after T enter a packet? Consider `_pick` and the eligibility
   check, `accepted_at`/`effective_at`, the screener commit check, the submissions JSON fetched after T, and the
   statements chosen from "the latest periodic filing".
3. **Prompt contamination.** Do the SYSTEM text or the instructions invite the model to use outside knowledge, to
   value the company, or to recommend actions? Does anything in the rendered packet leak T+ information, such as the
   `excluded` list? (It is not rendered; check that.)
4. **Silent bypass.** Is there any path where a failed, malformed or timed-out task, or a crash, ends up looking like
   a complete analysis?
5. **Determinism.** Is there any input to `packet.build` that is not pinned in `raw_inputs` or in the screener commit,
   such as the calendar, the locale or the dict order?
6. **Anything else** that would make the first GPU run wasted or misleading.
