# CROSS_CHECK_M rulings (Claude, 2026-10-29)

The reply is `CROSS_CHECK_M_gemini_reply.txt` (Gemini through `agy`, read-only, on commit `42640f8`). Gemini advises
and Claude rules. Before ruling, Claude reproduced the high-impact claims:
- Q1.1, the trillion/million wildcard: through the `fig_matches` code path;
- Q1.4, the omission marker read as a figure;
- Q3.1, S0's contents: by reading HRTG's `stocks.json` row;
- Q6.1, ILMN's `_main_exhibit`: by reading the packet.

**Verdicts:** **FIX** means it is fixed before any GPU run. **NOTE** means it is recorded as a limitation or a v2
item, with the reason given.

## Q1 False `supported`

| # | Point | Ruling |
|---|---|---|
| 1.1 | Unrecognised units (trillion, T, plural scale words, x, bps, ppt) parse as unit `""`, and a bare wanted figure matches any printed unit, so "$10.6 trillion" is found in "$10.6 million" | **FIX.** `contract.py` gets its own figure reader with a wider unit set: k, m, bn, tn (trillion, tn, T attached to a number), %, x, bp (bps, basis points), pp (ppt, percentage points). Plural scale words are read as their singular. **Units must be equal**, except that k/m/bn/tn convert among themselves. A bare figure matches only a bare figure. |
| 1.2 | `(?<![A-Za-z0-9,.])` hides numbers after "." and after unlisted currency codes ("approx.99%", "CHF990m") | **FIX** for listing: the claim-side reader reads a number after `.` or `,` when not inside a number, and reads ISO codes (CHF, JPY, CNY, RMB, SEK, NOK, DKK, KRW, HKD, SGD, INR, BRL, MXN, ZAR, TWD, ILS, PLN, CZK, TRY) as currencies. A number glued to letters (H100, Q3, FY26, F1) is still not a figure. A misread such as ".99" read as 0.99 can only cause `number_not_listed`, never a false `supported`. |
| 1.3 | Ranges drop the unit of the lower bound ("8-10%", "$4.60-$4.64 billion") | **FIX.** In "a-b", "a–b" and "a to b", a lower bound with no unit takes the upper bound's unit and currency, in items and claims alike. |
| 1.4 | Omission markers ("[… 65,074 characters omitted …]") are read as figures | **FIX.** `OMIT_RE` is removed from every text before figures are read. |
| 1.5 | The year exemption covers "2,025" and "closed 2025 stores" | **FIX.** Exempt only a 4-digit token with no comma, directly preceded by a year word: in, fiscal, FY, year, since, by, through, until, from, during, of, ended, ending, end, before, after, early, late, mid, a month name, Q1–Q4, H1/H2, quarter, half. It must also be printed by a cited item. |
| 1.6 | Signs and parentheses are not compared; word numerals are not read | **NOTE.** `supported` certifies presence, not meaning (AUDIT_M3). Semantic support is the 3N blinded review. Word numerals ("nine billion") are not figures, and the SYSTEM text already requires digits. |

## Q2 Look-ahead

| # | Point | Ruling |
|---|---|---|
| 2.1 | S0 market data (price, EPS TTM) can reflect a release that the SEC policy still holds back. The commit date `%cI` is a self-claim | **Partly FIX.** S0 is cut to identity and market fields (Q3.1), so `epsTtm`, `quarterlyEps` and the other derived metrics leave the prompt. Price and market cap stay, labelled with their as-of. They were public before T: the commit is witnessed by the verified GitHub run, which must end before T. **The packet now also refuses when T is earlier than the verified run's GitHub `run_updated_at`, which `check_new_runs` rows now carry from the witness index. A row without it is refused.** |
| 2.2 | `excluded` can list a filing that was really after T (Eastern-mislabelled clock) | **NOTE.** `excluded` is never rendered. It is a record of what was held back, and listing too much there harms nothing. |
| 2.3 | `filings.recent` only covers about 1,000 rows; a historical T can lose filings | **NOTE + guard.** v1 is prospective: T is the build time. The packet refuses when T is older than the oldest row of `filings.recent`. Reading `filings.files` for historical packets is a 3N item. |

## Q3 Prompt contamination

| # | Point | Ruling |
|---|---|---|
| 3.1 | **S0 prints the screener's own opinions** (doors, ranks, bands, scores, `reverse.*` valuation signals, the `rev_con` risk narrative, forward consensus) and placeholder zeros | **FIX (severe).** S0 is a whitelist: `symbol`, `name`, `sector`, `industry`, `country`, `price`, `marketCap`, `Last_Updated` (labelled as the price as-of), `last_listed`. Nothing comes from `factor_scores_dual_door.json`; its blob is still pinned in the header, for audit only. The Yahoo `description` is dropped: it is not primary and can be stale (CMRE). This matches the rs2 rule that no nomination door, rank or band is shown to the model. |
| 3.2 | `confidence_basis` allows "inferred" | **NOTE**, kept. An inference labelled as an inference is honest, and its figures and quotes are still checked. |
| 3.3 | `settled_by` names documents outside the packet | **NOTE**, kept. That is the purpose of the field. |
| 3.4 | `thesis_change` re-injects prior claims that are not supported | **FIX.** Only prior claims with `support == "supported"` become points. The count left out is stated in the instruction. |

## Q4 Silent bypass

| # | Point | Ruling |
|---|---|---|
| 4.1 | `claims: []` with `unknowns: []` is `ok`; a run with every claim unsupported is `complete` | **FIX.** An empty reply (no claims and no unknowns) is `malformed` (retry once). Each task records `support_counts`. `analysis.json` and the ledger line carry a run-level `support_summary` (claims, supported, unsupported), so a run that is `complete` but wholly unsupported is visible. |
| 4.2 | The overflow guard misses front truncation, because Ollama truncates before evaluating | **FIX.** **Preflight:** refuse a task when the rendered prompt's characters / 2.5 + `num_predict` > `num_ctx`. **Post-check:** `prompt_eval_count + eval_count >= num_ctx - 1` is `context_overflow`. `NUM_CTX` rises to 98,304, the value rs2 already runs on this card. |
| 4.3 | `thesis_change` point ids are not checked | **FIX.** A claim whose `point` is not one of the prior point ids is a shape error. Points not addressed are recorded as `points_not_addressed`. |
| 4.4 | A prior run without usable tasks becomes `not_applicable_no_prior`, so the run is `complete` | **FIX.** New status `prior_unusable`, which is not ok, so the run is `analysis_incomplete`, with the cause. A prior with only one of `growth_thesis`/`risks` ok records the other as missing in the instruction and in the manifest. |
| 4.5 | A crash between the manifest and the ledger hides the run from `find_prior` (an older run gets used); a torn ledger line crashes everything | **FIX.** `find_prior` reads `read_ledger()`, which includes runs that are missing from the ledger but have a finished manifest. `_read_jsonl` skips a torn **last** line and records it; a torn line in the middle still raises. |
| 4.6 | An HTTP 200 carrying `{"error": ...}` or an empty response is treated as malformed | **FIX.** `resp.get("error")`, or an empty `response` with `done` not true, is `infra_retry`. `done_reason == "length"` is named in the malformed cause. |

## Q5 Determinism

| # | Point | Ruling |
|---|---|---|
| 5.1 | `verified_record` is not pinned | **FIX (small).** The header carries the verified row as found (`run_id`, `verdict`, `pair`, `output_commit`). |
| 5.2 | `build(online=False)` reads the latest receipt, not the one the packet pinned | **NOTE + doc fix.** The determinism gate is `replay` (`get_pinned`), as the spec states. The docstring's claim about `build(online=False)` is corrected to "over the same store state". |
| 5.3 | Library versions are not recorded; T outside 2005–2031 is uncaught | **FIX.** The header records `builder_code` (sha256 of `packet.py` and `sec_primary.py`, plus the `exchange_calendars` and `tzdata` versions). A T outside the calendar is `PacketRefused("T_outside_calendar")`. |

## Q6 Other

| # | Point | Ruling |
|---|---|---|
| 6.1a | Missing sections are not shown to the model | **FIX.** The rendered packet lists, under "NOT IN THIS PACKET", every `section_not_found`, `statement_not_found` and `no_eligible_filing` annotation. It never lists `excluded`. |
| 6.1b | **`_other_8k` prefers EX-10/EX-4/EX-1 contracts over the 8-K body**, as in ILMN P4, where a credit agreement's cover took the slot | **FIX.** The other-8-K text is the 8-K body from its first listed Item heading, then EX-99.x exhibits to the cap. Contracts (EX-1, EX-3, EX-4, EX-10) are never used. |
| 6.1c | The title is not rendered | **FIX.** The item header line includes `title`. |
| 6.2a | Amendments (10-K/A, 10-Q/A, 20-F/A) are invisible | **FIX.** Up to 2 eligible amendments accepted after the chosen annual report become `amendment` items: the body text from its first Item heading, at most 4,000 characters. |
| 6.2b | Foreign interim 6-Ks and 40-F exhibits | **NOTE.** v2, annotated (`no_eligible_filing: quarterly`). |
| 6.2c | The release has no staleness bound | **FIX.** A release accepted more than 120 days before T is not used, and is annotated `release_stale`. |
| 6.3 | Another model holding the GPU wastes the run | **FIX.** The runner preflights `/api/ps` and refuses (`RunRefused("gpu_busy")`) when any other model is loaded. |
| 6.4 | Sampling is not recorded; truncation at `num_predict` is not named | **FIX.** The manifest records the model's parameters from `/api/show`. `done_reason == "length"` is named (4.6). Repeatability under temperature 0.6 with a fixed seed is what M-LIVE measures. Temperature is **not** changed in v1: the Modelfile defaults are Qwen's recommended thinking settings. |

**Prompt version:** S0, the rendering and the `thesis_change` text change. No run has used `m3m.prompt.v1` yet, so it
stays v1, and the pins are re-pinned. Recorded here.
