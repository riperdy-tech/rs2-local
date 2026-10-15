# RS2 Local

Local LLM equity-analysis engine. Runs the RS2 framework (expectations investing) over the
screener's research_now / watchlist book on a local Ollama model, publishes verdicts to the
screener site overlay, and keeps an append-only, graded track record.

**Rewritten 2026-08-19** to match the code (the previous README described the retired
pre-inversion architecture). If this document and the code disagree, the code wins — and per
`CLAUDE.md` §0, fix the document in the same change.

## Architecture in one paragraph

Valuation is **deterministic Python**; the LLM never supplies a number for a DCF-able name.
`valuation_backbone.py` solves the growth the market price implies (reverse DCF on blended
owner earnings, two-stage 5+5, sector cost-of-equity table) and compares it to demonstrated
growth — the **expectations gap** is the headline signal, ranked cross-sectionally against
the book (`cache/mos_distribution.json`). The LLM contributes judgment: an achievability
stance, an earnings-basis choice on contested names, conviction, and prose. Verdicts pass a
deterministic don't-chase brake, then a two-tier audit (deterministic reproducibility +
AI contradiction audit) before anything publishes.

## Two levels

| Level | Entry point | What it does |
|---|---|---|
| Sweep | `orchestrate_depth.py` | the LIVE depth-tier pipeline: research (cached, bounded) → seeded samples with tools → plausibility guard → band-direction verdict → overlay/publish. |
| Per ticker | `depth_pipeline.py` | research → consensus (`tools/audit_202608/consensus_valuation.py`) → fiduciary contract gate → `verdict_depth.json` + ledger, then `depth_sanity` audits it in-process. |

Monitoring: `status.py` / `telegram_status_bot.py`. A powered-off PC is covered by the cloud
backstop (`api_llm/cloud_backstop.py`, GitHub Actions), which imports `orchestrate_depth` — the
same live pipeline, not a second one.

### Retired: the v2.0 generation

`orchestrate.py`, `run_rs2.py`, `valuation_io.py`, `verdict_ledger.py`, `tools/publish_only.py`,
`tools/run_batch.py` and `register_orchestrator_task.ps1` moved to `_archive/retired_20260920/`
on 2026-09-20, along with the `RS2.txt` framework they were built on. The "RS2-Orchestrator"
task that ran them is disabled. Nothing live imports them, and
`tools/audit_202608/tests/test_group_b_decoupling.py` enforces that.

## LLM stages

Each stage's user message = [fed data from `rs2_data.build_data_context`] + [prior-stage
carry] + [stage task]; the RS2 engine spec (`RS2.txt`) is baked into the model.

- **S1** classification / macro / base rates (archetype routes cyclicality via `routing.json`)
- **S2** business quality / moat / adjusted financials
- **S3** expectations test — emits the stance JSON (or Engine 2/4/5 inputs for names the
  backbone can't value); the engine then writes the authoritative VALUATION RESULT block
- **S5** scenarios (Layers 4/4.5, prose only — the structured S4 stage was retired 2026-08-19
  after audit C7/C9 measured its output dead and 82% template) + conviction / behavioral /
  portfolio / Kelly
- **S6** red team / pre-mortem / 37-point audit
- **Final assembly** consolidates Sections 0–12 under the field-ownership contract; the
  engine prefixes `FINAL.md` with an engine-typed valuation header.

Models: `rs2-analyst` (Qwen3.8-27B MTP tag, thinking off — migrated 2026-08-19 after the A/B
battery; see `RS2-Analyst-38.Modelfile` and `api_llm/` for the harness) and `rs2-research`
(`qwen3:14b`, clean of the analyst system prompt, for `deep_research.py`).

## Valuation routes

reverse-DCF on blended owner earnings (default) · mid-cycle for cyclical sectors · FFO for
REITs · justified P/B-ROE for banks/insurers and regulated utilities · rNPV (Engine 5) for
pre-revenue biotech · Engine 4/2 fallbacks. Contested lattices (≥30pts MoS spread across
earnings bases) get a 3-sample LLM majority vote on the basis *before* stages run.

Deterministic tripwires (audit 2026-08): earnings-quality battery (F-score, accruals,
Beneish M, issuance — from the screener's `fundamentals_battery.json`) and solvency
(coverage, net-debt/OCF) surface in the prompt and in `verdict.json`; they gate nothing.

## Data

- **Bucket A** — screener repo (git-pulled): SEC `fundamentals_history/_ttm/_quarterly`,
  `financials/{T}.json`, factor/reverse scores, macro; plus the Macro Regime Indicator.
- **Bucket B** — `enrich_ticker.py` (yfinance behavioral) and `openbb_data.py` caches.
- **Bucket C** — `deep_research.py` → cited `research/{T}.md` (SearXNG first, then
  Tavily/Brave/Serper metered by `quota.py`).
- **Bucket D** — the engine's own graded track record (`outcome_feedback.py`).

Corpus integrity is a blocking sweep gate: `data_health.py --gate-live`.

## Outputs

`reports/{T}_{ts}/` bundles → overlay `public/data/llm_overlay.json` (audit-clean only) →
full-text site bundles (`publish_reports.py`) → append-only `rs2_verdict_log.jsonl` ledger →
graded weekly by the screener's `grade_rs2_verdicts.py` (30/91/182/365d vs IWM/SPY/QQQ).

## Pack revision 6 — the desk is mandatory (Phase 4, charter v3.1)

Revision 6 bundled Phase 4's pack and charter changes into one revision (bumping
`tools/audit_202608/capability_test.PACK_REVISION` re-triggers every name in the book; the current
value lives there, not in this file). `base_iv` must now equal a
`tools/audit_202608/financial_model_tool.py` desk result (three-stage DCF, declared `fade_years`,
required `terminal_g`, terminal reconciled against the MRI sector band, frame-checked
`equity`/`firm`) within 1%, or a named desk `blend` — samples with `desk_calls == 0` or an
unmatched IV are excluded from medoid candidacy. (Revision 17 replaced the dual Gordon/exit-multiple
terminal with one funded-growth terminal valued from the company's own record: `terminal_ronic`, the
`long_run` and `working_capital` facts in the DEFAULTS block, the Base's years 1-2 held at the
consensus levels, a base-year cap for one-time gains; see `tools/throughcycle_record.py` and
`tools/consensus_reference.py`.) The pack gained SECTION 1.5's `COE ANCHOR`
(±150 bp mandate), SECTION 1.6 "state of the world", SECTION 2.5 price-only momentum facts (no
screener opinion shown to the model), a GROWTH BASE RATES block (`tools/base_rates.py`), a
GUIDANCE & CONSENSUS block, SECTION 8.5 peer P/E context, and a DATA WARNINGS block
(`tools/audit_202608/pack_data_sanity.py`). Every verdict now carries `coe_used`/`coe_source`,
`terminal_method`, `momentum_view`/`entry_timing`/`invalidation_rules`, and `m` (the price's
position in the IV band, in half-widths). Full detail:
`stocks-workspace/docs/system-map/03_RS2_DEPTH.md` (DEP-04/DEP-06/DEP-07/DEP-07b).

### Pack revision 21 — primary sources, and the crux follow-up

The pack carries a `## PRIMARY SOURCES` section directly after GUIDANCE & CONSENSUS: the company's own SEC filings as verbatim
text (HTML cleaned, nothing paraphrased), built once per pack by `sec_primary.py` from EDGAR with `sec_guidance`'s User-Agent, one
request at a time, each accession cached forever in `cache/sec_primary/`. In order: the latest 8-K Item 2.02 earnings release
(14,000 characters at most; a longer one keeps its start, its outlook, guidance, segment and backlog paragraphs and its tables, every cut
marked `[… n characters omitted …]`), that 8-K's other text exhibits (6,000 each; a PDF is skipped and said so), the segment report of
the latest 10-Q or 10-K (`FilingSummary.xml`; 6,000), and the other 8-Ks of the last 120 days with item 1.01, 2.01, 2.03, 5.02, 7.01 or
8.01 (2,500 each, four at most); 30,000 characters in all, the oldest other 8-K trimmed first. Each item is `[P1] …` with its filing
date, accession, period and URL, its text a block quote. A name with no CIK, an unreachable SEC or nothing filed prints
`PRIMARY SOURCES: not available — <reason>`. The facts sidecar's `primary_sources` (FACTS_VERSION 9) records each item's id, type, form,
accession, filed, period, URL, text sha256 and length.

A citation of `PRIMARY P#` (or of an item's URL) is company evidence for a crux: `crux_check` resolves it to the item and looks for the
quote in that item's text (`crux_check.normalise` is the one matching rule). `tools/acceptance_r21/q2_round_trip.py` proves every
sentence of an item is found, as `PRIMARY P#` and as its URL, in a built pack.

The harness does not let the analyst search or fetch again for what the items hold (`sec_primary.refuse_fetch`, `refuse_search`, applied
in `analyst_tools.chat_with_tools` before the call is dispatched): a `fetch_page` of an item's document, or a `search_web` query that
holds a figure an item prints verbatim, or names a document word and a period an item covers, returns a pointer
(`{"served_from_primary": [...], "note": ...}`), is recorded in the snapshot (`served_from_primary`, `primary_refusal`) and does not use
the search budget (refusals past `PRIMARY_REFUSAL_CAP` do, so a refusal loop ends). `tools/acceptance_r21/r3_census.py` applies the
search rules to a recorded run's queries; `prefetch_sec.py` is the one script that reaches the network, and only sec.gov.

The crux follow-up: after a sample's memorandum, when its answer run is undervalued or overvalued and passed no crux (`crux_check`
says `missing`), the harness sends one message (`analyst_tools.CRUX_FOLLOWUP`): call the desk once more with the answer-run inputs
unchanged plus a crux, or reply HOLD. The desk refuses a changed input (`financial_model_tool.followup_input_changes`, the existing
"Not accepted as a desk run" refusal); the follow-up has one desk run of its own. `consensus.json` records per sample `crux_followup`
`{fired, outcome: crux_added | hold_confirmed | no_change}`, and a sample whose memorandum's SECTION 0 verdict word differs from the
code's label carries the flag `memo_verdict_mismatch` (reported, never a gate).

### Pack revision 24 — the reference shown only after the analyst commits

Stage A: the pack does not print the CONSENSUS-IMPLIED VALUE. DATA 8 has no reference line, the BASE WINDOW CHECK leaves out its
fiscal-year value and the TTM window's fence side, the DEFAULTS block has no `consensus_implied_value` or `reference_status` line, TASK
item 6 no longer names it, and the desk's R10 gate is off (its share-unit note compares with the price). The value, its status and the
omitted line are still computed and kept in the facts and the sidecar (FACTS_VERSION 10: `reference_withheld`, `reference_line`); a
revision-24 DEFAULTS read gives None for the value and the status, so a replay takes them from the sidecar, never from text.

Stage B (`analyst_tools.chat_with_tools`, after the final memorandum and any crux follow-up): when the reference is in force (status
`used`), the harness sends one message (`reference_reveal_message`) with the value, its inputs and the stage-A Base. The model replies
KEEP, or calls the desk once more with its answer-run inputs, changing only the inputs it lists in `reference_revision` (each with a
citation); the desk refuses an unlisted change and accepts `reference_revision` only in stage B. The guardrails
(`reference_revision_outcome`: G5 malformed, G4 more than 25% from stage A's Base, G3 a move toward the reference of more than 10% with
any changed input uncited, G1 an unverified citation, G2 a quote stage A already used) keep stage A's answer run on any failure; the
rejected run is marked `reference_revision_rejected` and never counts as a run. Every sample records `base_iv_stage_a`, `base_iv_final`
and `reference_revision` `{fired, outcome: keep | revised_accepted | revised_rejected | not_available, guard_failed, changed_inputs,
toward_civ, civ, base_over_civ_a, base_over_civ_final}`, carried to the verdict row; the full exchange is in the sample's
`_reference_reveal.md`.

Step 2a (`BRIEF_R24_S2a_desk_fixes.md`, the coordinator's rulings on the desk arithmetic audit): stage B is off. It runs only when
config.json sets `reference_reveal` to `true` (`analyst_tools.reference_reveal_enabled`); absent, the default, REFERENCE_REVEAL is never
sent and the desk refuses every `reference_revision`. Stage A also no longer prints the TTM window's value (in the BASE WINDOW CHECK and
the DEFAULTS `base_window` line; the facts keep it and parity leaves it out) and no longer names the reference in `reference_base_b`'s line,
TASK item 3 or the desk's share-unit note.

The long-run margin is the analyst's. `run_financial_model` takes `long_run_margin` (required for a perpetual cash-flow life, with no
default; at the top level or per scenario): the earnings margin at the end of the fade. Each scenario's year-5 revenue is the facts'
(e5 / m5) scaled by its year-5 owner earnings, as its earnings are, so its year-5 earnings margin is m5; the desk moves that margin to
`long_run_margin` proportionally over the fade (`margin_ratio = long_run_margin / (E5 / R5)`), and with a fade of 0 in the terminal year.
Where the facts carry no year-5 revenue (no reference, or one without a revenue path) the margin is held and the run is stamped
`long_run_margin_not_applied_no_revenue`. The facts' `margin_ratio` no longer reaches the desk, nor the DEFAULTS run
(`defaults_desk_args`); `margin_rule` serves only the logged reference and stamps `implied_operating_margin_out_of_range` and
`long_run_margin_clamped_to_zero` into the facts' `stamps_full` (never printed). Year-5 earnings scale with the scenario's owner earnings
(E5 = e5 x OE5 / oe5); the return on new investment moves linearly in its charge 1 / RONIC over the fade, so an unlimited terminal return
is the limit of a large one and the value is monotone in it; a `terminal_ronic` below r is valued as r and stamped
`terminal_ronic_floored_at_r` (in the desk output and the sample's `desk_stamps`).

## Verdict provenance and gating (P1.2/P1.3/P1.5)

Every depth verdict (`verdict_depth.json`, each ledger row) carries, stamped by
`depth_pipeline.stamp_and_route()`:

- `run_source` — how the run was invoked, resolved by `depth_pipeline._run_source()`:
  `--ondemand` always wins; then the `RS2_RUN_SOURCE` env var a spawner sets
  (`orchestrator` | `cloud` | `gate_test` — the Phase 4 gate run's own marker, kept distinct
  from plain `manual` so the ledger row says what actually ran, though both route to the test
  ledger); then `--production` for an operator-invoked production run; anything else is `manual`
  — a bare, unmarked `python depth_pipeline.py TICKER`.
- `screener_data_commit` (P4.−1) — the resolved SHA of the screener-publish clone this verdict's
  pack was built from, stamped by `screener_refresh.refresh_screener_data()` at the start of every
  entry point that reads screener data (the sweep, `depth_ondemand.drain()`, a standalone
  `depth_pipeline.py` invocation). A refresh failure refuses the run rather than analysing against
  unverified data.
- `arm` — always `"local"` today (this is the local-Ollama pipeline).
- `pack_source` — always `"fresh"` today.
- `research_brief_asof` / `research_brief_age_days` — the mtime of `research/{T}.md` at verdict
  time, or both `None` if the brief does not exist. Never fabricated.
- `price_asof` / `price_source` / `price_asof_basis` — from `price_now.quote()` (below).
  `price_asof_basis: "fast_info_unverified"` marks a quote that fell back to an unsettled
  `fast_info` price rather than a verified daily close; it is absent (`None`) for a verified
  close. `price_asof_reason` explains a missing quote on the rare path where one is genuinely
  unavailable after `main()`'s own hard-fail check.
- `gate_version` — the schema version this verdict was stamped with (see `depth_gates.py`).
- `pipeline_commit` — `git rev-parse --short HEAD` at verdict time, best-effort, `None` on
  failure.

### Live price at verdict time — `price_now.py` (P1.5)

`price_now.quote(ticker)` fetches a live quote via yfinance and runs before research on every
`depth_pipeline.py` invocation; if it returns nothing, `main()` hard-fails with **exit code 8**
("live price unavailable") before any research or model work starts. It refuses a quote older
than 4 calendar days, and checks the *newest* daily-close row before dropping NaNs: if that row
is NaN (today's session, unsettled) or dated later than the newest row with a usable close, it
refuses the older close and falls back to `fast_info.last_price` instead, stamped with the
newest row's own session date and `asof_basis: "fast_info_unverified"` — never silently serving
a stale close. `yfinance` is imported lazily inside the function so importing `price_now` never
requires it (the cloud continuity arm has no install step for it). Returns `None` on any network
failure or unparseable quote.

### Gate on read, not on write — `depth_gates.py` (P1.3)

`depth_gates.assess(v)` is the single owner of what makes a published verdict `actionable`. It
never mutates or drops a ledger row (non-negotiable 3: annotate, never silently gate) — it
judges one on read and returns `(actionable: bool, reasons: list[str])`, evaluating every
applicable reason so a row can carry more than one at once:

1. `direction` not one of `undervalued`/`hold`/`overvalued` -> `not_usable`
2. `gate_version` absent or `< GATE_VERSION` (currently 8) -> `pre_v3.1_gates`
3. `n_basis == 1` -> `single_sample`
4. `fiduciary_verdict == "FAIL"` -> `fiduciary_fail`
5. `direction == overvalued` and `kelly_fraction_pct > 0` -> `kelly_on_overvalued`
6. `direction` in `{undervalued, overvalued}` and `spread_pct > 25` -> `high_dispersion`
   (**symmetric** since P4.8 — previously undervalued-only)
7. `run_source` in `{manual, test, gate_test}` -> `non_production_row`
8. `instability.unstable is True` -> `mode_instability` (P4.7 — annotation-only at the verdict
   layer, an actionability gate here)
9. `FIRST_VALID_PACK_REVISION` is set and `not analyst_valid(v)` -> `pre_valid_analyst` (Phase 4
   B3 — the switch that turns Phase 4 validity on; `None` until the Phase 4 gate sets it, so this
   reason never fires before the ruling)
10. `median_iv` above `street_fence.high` on an undervalued call, or below
    `street_fence.low` on an overvalued call -> `outside_street_fence`
11. `|mos_vs_base_pct| > 150` -> `mos_beyond_150pct`
12. a basis sample flagged `desk_not_used` / `iv_not_desk_backed` -> `desk_not_used`
13. a sample written at reduced thinking (`LOW_EFFORT_RESCUE`); from 2026-09-27 such a sample is
    never a basis sample, so this guards rows written before that -> `low_effort_rescue`
14. any flag starting with `SAMPLE_FAILED` -> `sample_failed`
15. any flag starting with `discovery_failed` -> `discovery_failed`
16. depleting producer (industry in depleting list) -> `depleting_producer_unsupported`;
    producer_class unavailable (or absent on v>=5) -> `depleting_producer_class_unavailable`
17. `consensus_data_status` present and not `ok`, or absent on v>=6 -> `consensus_data_unavailable`
18. `street_fence` not a dict with numeric `low` and `high` -> `no_street_fence`
19. `pack_revision` >= 19, a directional verdict and `crux_valid` not True -> `directional_without_valid_crux`
20. a directional verdict whose `input_scope_stamps` hold `nci_share_unmeasured` (noncontrolling interests filed, the common
    shareholders' share not measurable; pack revision 20), or `nci_scope_fields_absent` (a history written before the
    noncontrolling-interest fields existed) -> `nci_share_unmeasured`
21. a directional verdict whose `input_scope_stamps` hold `per_share_basis_unverified` (the filed net income, diluted EPS and
    diluted share count fail the ASC 260 identity; pack revision 20) -> `per_share_basis_unverified`
22. `pack_revision` >= 20, a directional verdict and `input_scope_stamps` not a list (a pack replayed from its text alone has
    none) -> `input_scope_stamps_missing`

`orchestrate_depth.rebuild_overlay()` runs every ledger row's newest-per-ticker through
`assess()` and adds `actionable` / `actionable_reasons` / `gate_version` to each row, plus
top-level `actionable_count` and `gate_version` on `cache/depth_overlay.json` — additive only,
the row itself is never dropped. A verdict whose `direction` is the malfunction sentinel
`NOT_USABLE` (zero plausible complete samples) publishes `direction: null, status: "not_usable"`
instead of leaking that sentinel; every other row publishes `status: "ok"`.

### Ledgers and the events log

Three append-only ledgers under `cache/`, routed by `run_source` in `stamp_and_route()`:

| File | Written when |
|---|---|
| `depth_ledger.jsonl` | `run_source` is `orchestrator`, `cloud`, or `manual_production` (`--production`) — the production book |
| `depth_ondemand_ledger.jsonl` | `run_source == "ondemand"` (`--ondemand`) — nothing downstream reads it (see `depth_ondemand.py`) |
| `depth_test_ledger.jsonl` | `run_source == "manual"` — a bare, unmarked invocation with no `--ondemand`/`--production`/`RS2_RUN_SOURCE`; a loud Telegram notice fires so it is never mistaken for a production row. `run_source == "gate_test"` (`RS2_RUN_SOURCE=gate_test`, the Phase 4 gate run) routes here too, kept as its own value rather than folded into `manual` |

`cache/depth_ledger_events.jsonl` is a separate append-only log of operator/administrative
actions on the ledger: quarantine events (`tools/ledger_quarantine.py`) and
`membership_correction` events — a membership row deliberately removed from
`cache/depth_membership.jsonl`, honoured by `sync_state._corrected_membership_dates()` so the
corrected local file, not the pre-correction `rs2-state` copy, wins the next sync (see below).

### Factor guard — `--ignore-factor-guard`, `factor_max_age_h`

`depth_membership.check_factor_scores()` refuses to snapshot membership — and
`orchestrate_depth.main()` refuses to run at all — unless `factor_scores.json`'s `engine` is
exactly `dual_door_dynamic_macro_v2_cluster_guarded` and its `generated_at` is no older than
`CONFIG["factor_max_age_h"]` and no more than 5 minutes (clock-skew tolerance) in the future; a
future-dated file is refused rather than passing on a negative age. `--ignore-factor-guard` on
`orchestrate_depth.py` bypasses both the sweep-level refusal and the membership-snapshot guard —
deliberate recovery only, never a default.

### Research brief staleness — `research_max_age_days`, `deep_research.py --force`

`consensus_valuation.snapshot_research_brief()` reads `CONFIG["research_max_age_days"]` and
compares it against the on-disk `research/{T}.md`'s age on every path that consumes the brief,
including `depth_pipeline.py --no-research` (which skips `run_research` entirely and reads
whatever brief is already on disk, at any age). A brief older than the ceiling never blocks the
run — it rides onto the verdict as a `stale_research_brief` per-sample flag (non-negotiable 3:
annotate, never gate), which `band_verdict` aggregates into the published verdict's `flags`.
`deep_research.py --force` skips the cache-freshness check and rebuilds the brief
unconditionally; `deep_research.fresh()`'s own 7-day `research_cache_days` rule already rebuilds
anything older than that, so `--force` only matters on a brief the 7-day rule already refused to
reuse.

### `rs2-state` backup — `rs2_state_dir` / `RS2_STATE_DIR`

`paths.py` resolves `rs2_state_dir` (candidate `rs2-state`, env override `RS2_STATE_DIR`) as a
**required** key in `load_config()` — every rs2-local entry point raises if the backup store
cannot be found, not only `sync_state.py`. `sync_state.py` is what actually reads/writes it: it
imports cloud-arm membership and verdict deltas, runs the same `audit_verdict()` every local
append path calls against each imported row, and honours `membership_correction` events (above)
so a locally corrected row is never re-imported from the stale `rs2-state` copy.

### Suite guard — repo-root `conftest.py`

A repo-root `conftest.py` (the common ancestor of `tests/` and `tools/audit_202608/tests/`, so
it loads for the canonical `pytest tests tools/audit_202608/tests` invocation) snapshots every
file's mtime under `cache/` before each test and fails the test if any file's mtime changed or a
file was added or removed — the backstop against a test writing into production `cache/` state,
present and future, not only the specific tests that caused that class of defect.

## Grading the depth ledger — `tools/grade_depth_verdicts.py` (TRK-06, P2.1)

Nothing graded a `band_direction_v1` verdict until this. The honest-measurement rules (entry =
first close on/after the verdict date; exit = last close on/before date+h; benchmarks on the same
actual dates; a horizon graded only once fully elapsed) are COPIED, not imported, from the
screener's `scripts/grade_rs2_verdicts.py` — the zero-import rule (`../AGENTS.md`) means nothing
in this repo imports a sibling repo's code, so a fixture test
(`tests/test_grade_depth_verdicts.py`) proves the copies agree byte-for-byte on a shared sample
instead. One addition beyond the copied original: a **3-day horizon-shortfall guard** (mirroring
the retired lane's offline grader) skips — never truncates — a horizon whose resolved exit lands
more than 3 calendar days short of its target.

Grades every row across four ledgers (`production`, `archive` — the pre-Charter-v3.1 legacy
ledger under `_archive/`, `ondemand`, `test`), each tagged `ledger_source`. Before grading, rows
go through `dedupe_rows` (P2-fix B3) so one verdict is never counted twice: an exact
(ticker, date, consensus_dir) triple logged into more than one ledger collapses to a single row
by fixed precedence (`test` > `production` > `ondemand` > `archive` — the quarantine label is
the deliberate, later classification), recording the dropped ledgers as `also_in`; a
within-ledger rederivation chain (the archive ledger corrects a verdict in place by appending a
new line sharing the same triple) keeps every line but tags every one but the last
`superseded_by` its successor, excluded from every stat/cut/correlation while staying visible in
`graded`. `actionable` and `analyst_valid` are recomputed live via `depth_gates` on every row,
never trusted from a ledger stamp. Nomination context (`nomination_run_id`, `nomination_engine`,
`fct_band`, `fct_rank`, `fct_composite`, `fct_nominated_doors`, `z_momentum`, `z_value`,
`z_exp_gap`, `cluster`, `sector`) is joined from the screener's append-only
`public/data/factor_signal_log.jsonl`, read via `git show` from the DEDICATED
`screener_publish_repo` clone (never the working tree, never `screener_data_dir`) — the LATEST
run whose `run_id` falls on or before the verdict date and within 10 days of it, never a run
after the verdict. Any git failure blanks every nomination field and is stated in the caveats.

Outputs `cache/depth_outcome_prices.json` (its own price cache: every graded ticker plus
IWM/SPY/QQQ and a 17-ETF sector/industry cluster proxy set), `cache/depth_outcomes.json` (graded
rows, per-horizon cuts — direction, spread bucket, size, conviction/`mos_vs_base_pct`/`z_momentum`
terciles, nominated doors, arm, pack revision, sector, cluster, ledger source — Spearman
correlations, and a generated `caveats` block), and `reports/depth_outcomes_report.md`. A bucket
under 10 verdicts is still shown, flagged `inconclusive`, never silently dropped, and every cut in
the work order's list always renders — an empty one prints `n = 0` with the reason (missing field
count included) instead of being silently omitted. The caveats block states, from the data: the
dedupe counts, the nomination-join hit count and reasons, and how many graded rows come from the
valid analyst per `depth_gates.analyst_valid` (gated on `depth_gates.FIRST_VALID_PACK_REVISION`,
`None` until the Phase 4 ruling sets it — until then NO CONCLUSION ABOUT THE ANALYST may be drawn
from anything this grader reports).

`orchestrate_depth.main()` re-runs it `--offline` (no network) right before the sweep's final
publish (non-fatal, logged, `run_offline_grader()`), so the site's copy carries that sweep's fresh
verdicts instead of lagging a cycle behind. `--offline` never touches the network: a missing price
cache is a hard failure, and a horizon whose exit date is beyond the offline cache's reach counts
as pending, never missing/"delisted?". `publish_overlay()` copies `depth_outcomes.json` to the
site as `public/data/depth_outcomes.json` alongside the overlay — validated BEFORE copying, and,
being an optional scoreboard artifact, never able to block the overlay publish: an invalid or
missing source is skipped (logged) and the clone's own copy is left exactly as published. A weekly
network refresh (Sunday 09:00, 1-hour execution limit, no wake) is prepared as
`register_grader_task.ps1` (mirrors `register_depth_task.ps1`) but is NOT registered — registering
a Windows Scheduled Task is a machine change and needs operator approval.

## Screener data refresh — `screener_refresh.py` (P4.−1)

`paths.py` now resolves `screener_data_dir` to `<screener_publish_repo>/public/data` — the SAME
dedicated clone `publish_overlay()` writes to — instead of the shared `stock-screener` dev
checkout another session can leave on a stale branch with no signal to a reader. Every entry
point that reads screener data (`orchestrate_depth.main()`, `depth_ondemand.drain()`, a
standalone `depth_pipeline.py`) calls `screener_refresh.refresh_screener_data()` first, which
resets that clone to `origin/main` under the same `cache/screener_publish.lock` critical section
`publish_overlay()` uses. On any failure the caller refuses to run rather than analyse against
unverified data. On success it returns the resolved SHA, stamped on every verdict as
`screener_data_commit`.

## Thesis monitor — `thesis_monitor.py` (DEP-13, P4.5)

For every ledger row `depth_gates.assess` marks `actionable`, re-evaluates each checkable
`invalidation_rules` entry against current quarterly fundamentals, TTM fields, the battery,
`momentum_state.json` and 8-K count since the verdict. Writes `cache/depth_thesis.json`
(`{asof, tickers: {T: {thesis_status: intact|breached|unknown, checks, entry_timing_now,
momentum_flip_met, evaluated_at}}}`) — never a ledger row. `orchestrate_depth.rebuild_overlay()`
merges the result onto each overlay row; `depth_triggers.triggers_for()` reads it for the new
`thesis_break` (class 0) and `momentum_flip` (class 2) triggers. Runs at the start of every sweep,
right after the membership snapshot and before the trigger map, and standalone via
`orchestrate_depth.py --monitor` (refresh + monitor + overlay + publish, no GPU, no analyst) —
meant to be scheduled daily via `register_monitor_task.ps1`, which exists but is **not
registered** (a Windows Scheduled Task change stays operator approval). `--monitor --no-publish`
is the one mode allowed to run under `cache/DEPTH_PAUSED`, restricted to writing
`cache/depth_thesis.json` only.

## Where the truth lives

- `CLAUDE.md` — standard of proof (read it first)
- `audit/VALUATION_AUDIT_202608.md` — 2026-08 methodology audit: measured findings,
  effort×value chart, adopted plan (Option 2), standing STOP flags (FX, historical SBC, ΔWC)
- `AUDIT.md`, `SESSION_HANDOFF_*.md` — dated reviews and operational handoffs
- `PLAN_FX_INGESTION_20260814.md` — open FX plan for 20-F filers
