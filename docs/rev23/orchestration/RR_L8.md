# RR_L8: Impact of ChatGPT's unmerged `build_fundamentals_history` guard (`f99cdda5`)

**Result:** DONE (measurement only). **Ruling: HOLD**, with one specific change request.

## What changes behaviour

Of the three ChatGPT commits on the builder, only `f99cdda5` changes default output. It is 6 lines: an instant-tag
cell is set to `None` when none of that year's raw candidates is near the year's reference date, which mirrors the
existing accession-vote rule. The other two commits are opt-in tracing and audit code.

## Measured: A = 3094 code, B = branch tip, same zip and inputs

The zip is the local copy dated 2026-08-07; the inputs are `stocks.json` and `cik_map.json` from `e41974be`.

| Measure | Value |
|---|---|
| Tickers built | 5,183 on both sides (186 have no zip entry; 707 have no usable annual history, on both sides) |
| Cells changed | **1,701, all nulled** (no values changed or filled), across **226 tickers** |
| Instant cells nulled inside years that are kept | 1,205: cash 147, total_liabilities 144, ppe_net 132, lt_debt 132, current_liabilities 130, retained_earnings 130, current_assets 129, … |
| **Whole fiscal years dropped** | **26 tickers**, for example ALP 2025 and BNC 2025 (their *latest* year), ATCH 2024, KAVL 2018–19. In these, valid flows (net income, operating cash flow, EPS) are lost along with the bad instants: the builder's later year-validity filter drops a year once its balance-sheet cells are null. |
| Rows changed in `fundamentals_battery` | 35 |
| Motivating case | CMRE FY2025 `total_liabilities` 500.1M (an instant dated 2025-05-06) becomes `None`. CMRE's other cells are unchanged. |
| **Factor stage** (scorer at 3094 on run 40707381769's inputs, A vs B swapped in) | **No change**: nominations 162 = 162, research_now identical, 0 veto changes |

## Ruling

**HOLD.**

- The cell guard is consistent with the builder's own vote rule. It nulls values that are out of period (bad data
  becomes an absence; non-negotiable 4 is respected), and it moved no nomination today.
- But the cascade that drops whole years removes good income-statement data, including the latest year for some names.
  That is a gate, not an annotation (non-negotiable 3).

**Change request before merge:**
- Keep the year when only its instant cells are guarded away. Null the bad cells, and keep the year's flows.
- Annotate each guarded cell in provenance (state `off_anchor_instant_nulled`).
- Then re-measure with this work order's `compare.py`.

**Not yet verified:** whether each of the 1,205 nulled values really is a wrong-period instant, beyond the CMRE spot
check. A sample review of about 20 cells against the filings belongs with the change request.

## Files

`stocks-workspace/scratch/rev23/m3l_fh_impact/`: `A/`, `B/`, `codeA/`, `codeB/`, `compare.py`, `impact.json`,
`score_A/`, `score_B/`.

## Addendum 2026-10-29: the change request is implemented, not yet re-measured (3L carried check C3)

**Where:** stock-screener branch `review-2026-10/fh-guard-keep-year`, made from the `review-2026-10/m3l-mri-read-once`
tip `88e1862`, in worktree `scratch/rev23/wt-fh-guard`. Commit `fc588e6c` is **local only**: pushing a screener branch
can start a Vercel preview deploy (non-negotiable 8).

**The change:**
- The guarded `total_assets` figure still counts at the revenue/assets gate, so the year keeps its flows.
- Every guarded instant is annotated in `ladder_notes`: `off_anchor_instant_nulled`, with the value, the tag and the
  candidates' end dates. This uses the existing provenance channel, so there is no schema change, and the provenance
  doc string is updated.

**Tests:**
- Four synthetic tests:
  - the cascade case is reproduced and fixed (the year is kept, with net income and operating cash flow);
  - an anchored instant is untouched;
  - a year with neither revenue nor assets is still dropped;
  - the note ships in `encode_provenance`.
- Suite: 904 passed, 23 failed. The branch tip without this change gives the same 23 failures (rs2_data trace hooks and
  p3_review_c5), plus 3 of the new tests.

**Still to do:**
- Re-measure with this work order's `compare.py`, a full build of about 5,183 tickers. It is deferred until the GPU run
  ends (RAM limit).
- The ~20-cell sample review against filings.
- Merge only after both.
