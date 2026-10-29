# RR_M-LIVE: the limited GPU verification of qwen_c (2026-10-29)

Claude led, executed and audited this. Gate: SPEC_m3m_qwen_pipeline.md §7 **M-LIVE**.

## What was run

**The batch:** 6 runs on 2026-10-29, 02:51:20–04:02:10 UTC (70 min 50 s). The MA v1 smoke (AUDIT_M5) came before it.

**Common settings:**
- code `2e12d37`, with prompt **m3m.prompt.v2**;
- Ollama 0.40.6, tag `rs2-analyst-deep-mtp5-v33` (manifest f0f5ce2dcea3, Q5_K_M, 27.3B);
- `num_ctx` 98,304, `num_predict` 12,288, think "medium";
- Modelfile sampling, not overridden;
- seeds 1000 + task index.

**Packets:** T = 2026-10-29T02:28:48Z, screener commit `92592e21`.

**Tickers:** CMRE, HRTG, ILMN and ECPG, plus MA twice.
- All five are `research_now` at that commit (59 names): fct_rank 8, 22, 193, 53 and 34.
- None is an excluded ticker.

| Run | Status | Tasks ok (1st attempt) | prompt_eval_count | max eval_count | Claims | Supported as run (2e12d37) | Supported, recheck (bac4cf8) |
|---|---|---|---|---|---|---|---|
| MA_…_1 (v1 smoke) | complete | 6/6 | 31.4k | 7,767 | 66 | 39 | 50 |
| MA_…_2 | complete | 6/6 | 31.4k | 11,232 | 54 | 29 | 35 |
| MA_…_3 | complete | 6/6 | 31.4k | 5,841 | 51 | 26 | 29 |
| CMRE_…_1 | complete | 6/6 | 26.5k | 8,709 | 54 | 23 | 33 |
| HRTG_…_1 | complete | 6/6 | 32.0k | 11,182 | 59 | 28 | 38 |
| ILMN_…_1 | complete | 6/6 | 11.9k | 6,578 | 52 | 28 | 40 |
| ECPG_…_1 | complete | 6/6 | 33.1k | 10,423 | 63 | 42 | 51 |
| **all 7** | | **42/42** | | | **399** | **215 (54%)** | **276 (69%)** |

**Every run:**
- `thesis_change` is `not_applicable_no_prior`, since these are the first runs;
- `done_reason` is `stop` on every task, so none was cut at `num_predict`;
- there were no retries.

The max eval_count column was read from each run's own manifest. Per-task times were 78–204 s.

## Repeatability (MA_…_2 against MA_…_3: same packet, same prompts by sha256, same seeds)

The bytes differ, as expected. Runtime decoding is not deterministic here: the tag drafts 4 tokens per step (`draft_num_predict 4`) on the GPU.

**Unchanged between the two runs:**
- status `complete`;
- 6/6 tasks ok on the first attempt;
- the set of cited evidence items per task is nearly the same.

**What changed:**
- **Supported (rechecked):** 35/54 (64.8%) against 29/51 (56.9%).
- **Claim counts** were within ±2 per task: 10/12, 7/6, 13/11, 10/8, 8/8 and 6/6.
- **Overlap of the figure values the two runs cite** (Jaccard), per task:

| Task | Overlap |
|---|---|
| business_model | 0.56 |
| financial_health | 0.77 |
| competitive_position | 0.35 |
| growth_thesis | 0.61 |
| risks | 1.00 |
| unresolved_questions | 1.00 |

**Ruling:** the runs are repeatable in what the gate asks: status, task outcomes and the evidence base. They are moderately repeatable in content, and least so for competitive_position. The support rate moves by about 8 points between identical runs.

This is a measurement for 3N. Any accuracy number 3N reports must carry this run-to-run spread.

## The contract defects the live runs exposed, and their fixes

**The symptom:** `financial_health` had **0 supported claims** on MA (all three runs), CMRE and HRTG. A whole task failing on several tickers is a systemic symptom (non-negotiable 2).

**The cause:** every statement item is a FilingSummary R report whose first line declares its currency and scale, as in `Consolidated Balance Sheets - USD ($) $ in Millions | Jun. 30, 2026 | Dec. 31, 2025`. The contract did not read that line. As a result:
- **MA:** "$11,291 million" against the cell `$ 11,291` was "off by scale", although it is exactly right.
- **CMRE:** "$570,277 (table in thousands)" against `570,277` failed, because statements print "$" only on the first row and the totals.
- **Dates:** the column heads print "Jun. 30, 2026", which the date rule (full month names only) did not know. CMRE wrote "31 Dec 2025".

**Fix 1: THE STATEMENT RULE, commit `e7c9f72`.**
- Only for items of kind `statement`, each value cell printed with no unit is also read with the declared currency. On a money row it is also read with the declared scale.
- A per-share row ("(in dollars per share)", "(USD per share)") takes the currency only.
- A share row ("(in shares)", "(shares)") takes the declared share scale only.
- A row ending in any other "(in …)" takes nothing. Row labels and period cells take nothing.
- A listed cell lists all its readings: "numbers": ["$ 11,291"] lists the claim's "$11,291 million".
- Dates now match in either order and with abbreviated months.
- What it still refuses:
  - "$11,291 billion" and "$11,291 thousand" are still not found;
  - "$4.98 million" on an EPS row is not found;
  - "536 million shares" read from a row label is not found;
  - a prose item never takes a heading scale.

**Fix 2, commit `bac4cf8`.**
- The years in a list or range continue the year rule ("in 2023, 2024 and 2025", "in 2032-2036").
- "due" is a year word ("notes due 2029").
- A range's lower bound that is a year by its form takes no unit. "98.2% in 2026 to 15.1%" had read 2026 as a percentage.

**Audit of the fixes.**
- **Every one of the 61 newly supported claims** (54 after fix 1, 7 after fix 2) was read against the row or text that now supports it: the statement, column (3- or 6-month, year), sign and scale. **None is a false support.**
- **The earlier false-support probes all still fail:** 12% printed nowhere, a 2,034 printed nowhere, a scale change, a currency change.
- **New tests:** heading parsing; money, per-share, share, other-unit, label and period cells; listing; date forms; year lists, ranges and "due".
- **Suite:** **268 tests pass** (`qwen_c/tests`).
- **Branch scope:** the branch changes only `qwen_c/`, so the rest of the rs2 suite is unaffected and was not rerun.

The stored `analysis.json` files are left as the records of what the code at `2e12d37` judged. The recheck is a separate record: `M_LIVE_recheck_bac4cf8.json`, with every changed claim, its old and new support, and the new failures.

## The 123 claims still unsupported (recheck)

| Kind | Count |
|---|---|
| `number_not_listed` | 65 |
| `number_not_found` | 28 |
| `quote_not_found` | 30 |

A sample of 22 was read.

**Most are real model deviations, rightly unsupported:**
- **computed figures:** "14.8% of operating cash flow", "a working-capital surplus of roughly $292,100", "current ratio just above 1", "4:1", "$50,430 total restricted cash" (a sum);
- **added or changed decorations:** "$1,522,979" where the 5-year table prints no "$" in a prose item; "$300 million" against "$300,000,000";
- **altered quotes:** a table row quoted with words changed, and paraphrases given as quotes;
- **enumeration markers:** "(1), (2), (3)" counted as numbers to list. This is strict but harmless.

**Known false negatives (contract or packet limits), carried to 3N:**
- **A prose table's scale is not read:** MA "$13,315 million" against a 10-K MD&A table "(in millions)". Only statements carry a machine-declared heading. A prose heading would need a reader of its own, with its own false-support risk.
- **"The 2025 net combined ratio":** a year with no year word before it is not exempt. This is the year rule's deliberate guard ("closed 2025 stores").

## Findings for 3N (not 3M defects)

1. **Withdrawn (corrected 2026-10-29, same day).** An earlier draft said the R-file flattening loses XBRL member labels. It does not. ILMN F2 prints a header line `Product`, then `Revenue:`, then `Total revenue | $ 982 | …`, and likewise `Service` above `Total revenue | 177 | …`. The member name is a line of its own above its rows. The statement rule reads it as a no-cell line and gives it nothing, which is correct. There is no defect.
2. **`num_predict` headroom is thin.** The largest reply used 11,232 of 12,288 tokens (91%), most of it thinking. A cut reply is handled (`done_reason` length makes the attempt malformed, then the retry seed is used), but at some cost. Measure it over more tickers before changing anything.
3. **The ILMN packet is 11.9k tokens against about 31k for the others.** Its 10-K uses the cross-reference-index layout, so its sections are not found and are marked NOT IN PACKET. This was already known (AUDIT_M2). A census of that layout is a 3N item.
4. **What `supported` certifies:** presence, not meaning. Sign, period column and attribution are not checked by code. The audit above checked them by hand for the newly supported claims only.

## Against the pass criteria (PLAN §3M; SPEC §7)

| Criterion | Verdict | Evidence |
|---|---|---|
| Qwen runs repeatably on eligible candidates | **PASS** | 5 research_now tickers and 7 runs, all `complete`, 42/42 tasks ok on the first attempt; the repeatability measurement above |
| Each run has reproducible evidence and configuration records | **PASS** | M-REC on the real runs: 105 recorded sha256 (packet, analysis, prompts, raw replies, manifest via the ledger) and 49 turn files recompute, 0 mismatches; ledger rows agree with manifests. M-P4: 5/5 packets replay byte-identical (AUDIT_M2, WO_M4) |
| Unsupported figures are never treated as verified values | **PASS** | contract tests; 0 false supports among the 61 newly supported; an unsupported claim stays visible with its reason |
| Missing or failed analysis is visible | **PASS** | M-ERR stub tests (malformed, timeout, 500, overflow, crash, prior_unusable); NOT IN PACKET markers in the packets; no live run was incomplete |
| Live verification only after source, design and isolation review | **PASS** | CROSS_CHECK_M (24 fixes applied before the first GPU run), AUDIT_M2–M5, isolation: the runner writes nothing to rs2-state, the overlay or the screener, and has no trading path. `KIS_HALT` is a stock-screener repository variable that rs2 cannot read, so every manifest records `kis_halt: "not_resolvable_in_rs2"` (WO_M3). SPEC §6 still says the runner refuses without it; that line is corrected in Amendment 2 |

**M-LIVE: PASS.**
