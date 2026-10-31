# Change register: versions that affect the paper series (SPEC_m3s §0, item 6)

**Append-only.** One row per change to anything that shapes a paper decision. The marks report the series segment by
segment between these rows, and old rows are never relabelled.

| Date (UTC) | Component | From → to | Record | First formation it applies to | Note |
|---|---|---|---|---|---|
| 2026-09-22 07:13 | Screener engine | `score_factors` → dual door (A0) | RR_L7 | 2026-09-30 | the A0 forward ledger starts here |
| 2026-10-29 00:45 | Screener `main` | `fcf8594d` → `77adae57` (3L fixes: mri_sync read-once, EPS failure cache, price-refresh commits, UTC scan date) | CLOSE_3L | 2026-10-30 | factor-stage code |
| 2026-10-29 | qwen_c prompt / contract | `m3m.prompt.v3`, `m3m.analysis.v2` with the designator exemption (`626e086`) | SPEC_m3m amendment 2; LOG | 2026-10-30 (FQ) | — |
| 2026-10-29 | qwen_c packet builder | v5 → v7 (`4bc9425`: going-concern notes, 8-K segments, notes outside TOTAL_CAP) | AUDIT_N6 and its addendum | 2026-10-30 (FQ); retrospective 09-30 | — |
| 2026-10-29 | qwen_c runner | `find_prior` skips subset runs (`035ef96`) | AUDIT_N6 | 2026-10-30 | — |
| 2026-10-29 | 3O rules | PREREG_m3o v1.3 (B1, Q1 with a verified date, A1S, E1) | SPEC_m3o v1.1, CROSS_CHECK_O_RULINGS | 2026-10-30 | FB and FQ labelled `shadow_pre_3N_close` |
| 2026-10-29 | 3O engine | `m3o_engine.v2` | AUDIT_O1 | 2026-10-30 | — |
| 2026-10-30 | qwen_c contract | `m3m.analysis.v2` → `v3` (`15207e4`, `d2f3f15`: designators, quote cover) | RR_N_DEV §8; PREREG_m3o v1.4 | 2026-10-30 (FQ) | from the 3N DEV taxonomy |
| 2026-10-31 | 3O engine | `POST_3N_FIRST_FORMATION` None -> `2026-11-30` (3N closed; FQ/FB labelled `paper_post_3N` from the 11-30 formation; no row relabelled) | CLOSE_3N; SPEC_m3o §5 | 2026-11-30 | the 10-30 formation stays `shadow_pre_3N_close` |
| 2026-10-30/31 | qwen_c valuation (3Q) | prompt m3q.prompt.v1 -> v7, fin.v1 -> fin.v5; checks v1 -> v9; desk v4, forecast_fin v2, inputs v7, facts v4 (rs2 `review-2026-10/m3q`, last 8d25d85) | CROSS_CHECK_Q, Q2, Q3, Q3b-Q3e and their rulings; LOG | E3 (2026-11-03) | no valuation used for any decision before E3; values are diagnostic |
