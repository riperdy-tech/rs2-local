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

## The valuation rebuild's shared code and validation harness (SPEC_rebuild.md, Phase 5, Addenda A-C)

Offline; no model, no GPU, no network. Tests: `pytest valuation rebuild_harness`.

- `valuation/pit_data.py` - the ONE point-in-time data layer (SEC companyfacts per filing: value, filing date, accession). Decision time is 16:00 ET on
  the valuation date (EDGAR acceptance timestamps from submissions files; filing dates alone are conservative). INPUTS are as known at T (the latest
  eligible filing, amendments included); OUTCOMES are first filed. A fiscal year exists only from its own annual report. The extraction is the
  screener's production extractor, vendored byte for byte in `valuation/vendored/` (sha256 in MANIFEST.json) and run unchanged on the cut document.
  Every fact keeps its filing metadata and a provenance state (`facts_table`). `PriceSource` is the price-provider interface (traded unadjusted
  close, quality verified/unverified/missing, delisting events, a Yahoo provider that is offline unless allowed). SIC and name as filed at T from
  filing headers (`HeaderSic`). Quarterly facts (10-Q values, year-to-date differences, 10-K-derived fourth quarters) with the same provenance
  (`quarterly`, `quarterly_rows`, `PitQuarterSource`). API at the top of the module.
- `rebuild_harness/` - extends `backtest_phase2` (whose metric primitives it reuses): any list of valuation dates, total-return excess vs SPY at
  3/6/12/24/36 months from the next session, delisting returns, first-filed fundamental outcomes, five yardsticks, the old engine (revision 21's
  reference, synthetic consensus) as a pluggable engine `engine(ticker, asof, data_root)`, Spearman IC / quintile spreads / sector-neutral IC /
  incremental information / value-over-price distribution by family / forecast error vs a naive forecast, date-block bootstrap, per-date share of
  the universe the provider cannot price, and the holdout lock (`holdout.py`: a run touching 2023-2024 is refused unless a freeze file names every
  engine by git commit and file sha256). `python -m rebuild_harness.run_harness --help`.
- `valuation/priors.py` + `valuation/priors_build/` - the population priors at T (SPEC section 4, Addenda A-E): `PopulationPriors.for_company(family, state, asof)`
  returns a `PriorSet` (inputs as P5..P95, measured curves, `refs`: `ev_fcf_multiple`, `ptbv_of_rote`, `normalization_curve`, `curve_position`; `meta`: cell sizes, merges, fallbacks, the
  mechanical baseline, input correlations). Vintage Y is cut at Dec 31 of Y and serves dates in Y+1; observations are company-years of the whole SEC archive (delisted companies kept)
  from the layer's first-filed rows. Build: `python -m valuation.priors_build.prep_inputs`, `build_vintage <years>`, `mcap_panel`, `make_tables <years>`, `walkforward`, `report`; output under
  `stocks-workspace/data/priors/` (version 1, `PRIORS_REPORT.md`), `data/priors_v2/` (version 2, Addendum H) and `data/priors_v3/` (version 3, Addendum I1; the default `DATA_DIR`; the earlier folders
  are kept as they were, `PRIORS_DATA_DIR` overrides; v3 reuses v2's observation tables, which I1 does not change: `make_tables` is rerun on a copy of each `obs.csv.gz`). Tests: `valuation/tests/test_priors.py`
  (the no-look-ahead proof included).
- `backtest_phase2/` - the earlier registered backtest harness, unchanged (branch review-2026-09/backtest-phase2, 40cb5cf).

## Gate 1 on the development dates (T-integrate; REGISTRATION_gate1_DRAFT.md, Addenda F-H)

Offline; no model, no GPU, no network except SEC filings through `sec_primary` in the Muse checks. Tests: `pytest valuation/tests/test_gate1.py rebuild_harness/tests/test_gate1_metrics.py`.

- `valuation/pit_adapter.py` - the adapter from `PitData` to the engines' `CompanyPIT` (replaces the interim `pit_companyfacts.py`, which stays for its tests): the 16:00 ET
  rule re-checked on every accession behind a value (PIT_INVALID and AMBIGUOUS refuse the company), provenance counts, a non-dollar filer refused, the SIC as filed at T from
  the layer's header history else the current assignment (`CurrentSicFile`, stamped `sic_current_dated` / `industry_current_dated`).
- `valuation/common.py`: a debt component never tagged in any held year counts as 0, stamped (Addendum G 5). Addendum H (round 2; `SPEC_rebuild.md`):
  H1 `margin_target` is the margin LEVEL five years on, drawn directly (the priors give 8-year median + r_5 x deviation + the measured residual spread, unscaled; the F 4 rescale is gone) and the
  engine moves m_0 -> m_5 along the measured retention curve's shape and holds it (`common.level_path_weights`); H2 terminal growth is not drawn: `common.terminal_growth_rate` = min(risk-free rate
  at T, 3.75%), one value per date, and a negative decay-path rate at the last explicit year continues; H3 `ronic` is the ROIC level five years on (the own trailing 3-year ROIC, `build_state` `roic3`,
  fading along the measured retention of ROIC's excess to the median ROIC of the company's industry on the date's population, `gate1.DateContext.industry_return`; the spread is the measured dispersion of
  the ROIC level, table `roic_level`), perpetuity max(industry median, WACC) (superseded by J3 below); financials: the excess ROTE fades to the industry median ROTE, perpetuity max(median, COE); the engines refuse naming a missing
  `roic3` / industry median (`state["industry_roic"]`, `state["industry_rote"]`, attached by the caller; Muse's `run_company(industry_context=...)`); H4 `classification`: pre-profit (operating income <= 0 in
  >= 3 of the last 4 fiscal years) and SIC 4900-4949 are `family_not_built`, counted by kind; H5 `gate1.invalid_draw_refusal`: more than 5% invalid draws refuses the name, reasons named.
- Addendum I (round 3; `SPEC_rebuild.md`): I1 the year-5 residuals of the margin level and of the ROIC level are measured by the company's CURRENT level band (`stats.residual_by_level`: quintiles of
  the current margin / trailing 3-year ROIC within the cyclicality x sign cell, merged to n >= 50 by `merge_1d`; tables `residual_k5_by_level`, priors version 3) and the prior's quantiles are the median
  path plus the residual quantiles of the company's own band; I2 `engine_operating.operating_chain`: a draw whose long-run NOPAT margin or return on new capital (the ROIC level five years on) is not
  positive is valued, not invalid: no growth after year 5 (growth capped at 0 from year 6, terminal growth 0), NOPAT path kept, near-term growth that cannot be priced carries no reinvestment, and equity
  per draw is floored at 0 (`common.EQUITY_FLOOR_RULE`); the draws each rule applied to are counted (`dist["draw_rules"]`), invalid stays for numerical impossibility (the H5 refusal applies to those);
  I3 the financial family's cost of equity is rf + the industry's LEVERED beta (the betas sheet's column "Beta") x ERP, no Hamada (`DamodaranStore.levered_beta_provider`, `compute_discount_rate(levered_beta=True)`);
  I4 the financial terminal excess is kappa x max(industry median ROTE - COE, 0) with kappa the plateau of the measured excess-retention curve (its value at the longest k with n >= 50; the operating terminal
  RONIC is unchanged); I5 a prior cell under 50 after the stated merges refuses the input, named (`meta["unavailable"]`, then the engine's "priors do not supply" refusal with the cell and its n); I6 Muse
  prompts P3 and P4 are template version 2 (`ronic` is the ROIC level path; terminal growth is no longer a judgment input).
- Addendum J / K (round 4; `SPEC_rebuild.md`, `REGISTRATION_gate1_v2_DRAFT.md`): K the discount rate's ERP is Damodaran's MONTHLY implied ERP, column "ERP (T12 m with sustainable payout)" of
  `implprem_ERPbymonth.xlsx`: the newest start-of-month row dated on or before the valuation date (`DamodaranStore.erp_provider`, meta `row_date` / `source`); a row older than 62 days refuses; the annual
  year-end path is the fallback before the column's first value (2016-01-01) and when the manifest lists no monthly file. J3 the operating and commodity terminal return on new capital is
  WACC + kappa x (industry median ROIC - WACC), kappa the plateau of the measured ROIC-excess retention (the curve's last value = its value at the longest k with n >= 50; `meta["cells"]["ronic_fade"]`),
  floored at WACC only where the formula goes below it (`ronic_terminal_floored_at_wacc`). J1 `valuation/variants.py` swaps ONE engine component at a time (every engine takes `variant=None`; neutral and None
  are bit-for-bit the registered engine) and `rebuild_harness/gate1_decompose.py` + `gate1_decompose_summary.py` run each swap on a fixed universe (the ERP swap, to round 3b's closure ERP, replaces the `Rates`
  object): diagnostic only. J11 `valuation/sic_crosswalk.py`: the SIC -> Damodaran-industry crosswalk (modal industry of the US companies of `indname` that carry the SIC, 4 -> 3 -> 2 digit fallback, ties to the
  name that sorts first; file `data/crosswalk/sic_to_damodaran_industry_v1.json`, built by `build_file`, never overwritten), the EDGAR headers CSV as the SIC as filed (`HeadersFile`, with a coverage frontier
  = the newest filing date in the file minus 31 days) and `SicResolver`, which the adapter uses: header SIC + crosswalk industry where the file covers the date and holds a header of the company, else the
  current-dated SIC and industry, stamped `sic_current_dated` / `industry_current_dated`. J10 `rebuild_harness/holdout.py`: a freeze names the code commit, the store (tree hash), the price snapshot, every
  Damodaran file, the priors folder and each vintage, the crosswalk, the SIC headers, the configuration (`gate1_run.frozen_config`), the seeds and the package versions; `write_freeze` refuses to write
  without them and `enforce` refuses a holdout run whose `inputs` hash differently, naming the key.
- Registration v2 in the harness (`rebuild_harness/gate1_v2.py`, `gate1_report --v2`): month-end dates (`gate1_run.dev_dates`: 36 from 2020-01-31, returns to 2021-12-31, forecasts all); B1 pooled OLS with
  industry and date effects (alternating projections) and a wild-cluster bootstrap-t by date (Rademacher weights, null imposed, one-sided 90% lower bound b - q90(t*) se), the share of positive monthly
  coefficients; B2 the residual quintile spread (pass > 0, strong pass >= +3 pp, raw reported); B3 the level bar (universe median IV / price in [0.67, 1.5]) with the pathology diagnostics; B4 per family
  and measure, the P50 against the naive baseline, P10..P90 coverage and directional accuracy (the engines store `forecast_year1`: growth, margin, ROTE' at P10/P50/P90); B5 direction under the three bounds
  and without the 1% of observations with the largest |residual|, with the ERP +-1 pp (`gate1_run` stores `score_alt` on the return dates), sector-neutral, size-neutral and price-basis variants reported.
  `gate1_compare_v2.py` puts runs side by side on the same dates. Tests: `pytest valuation/tests rebuild_harness/tests tests/test_valuation_engines.py tests/test_valuation_classification_rates_pit.py`.
- Holdout inputs (Addendum L3, L4; freeze preparation, no freeze file exists): `rebuild_harness/daily_prices.py` `LazyDailyPriceSource` reads the D5 daily raw closes (`data/prices_daily/<TICKER>.csv.gz`) lazily, an LRU
  of tickers per worker, never the folder; the traded close = Close x the product of the split ratios with ex-date after the session; the entry of an outcome is the NEXT session's total-return-adjusted OPEN
  (registration v2 section 2). `rebuild_harness/delisting_inputs.py` turns the D1 event index (`data/sec_bulk/index/events.json`) and the D3 documents (`delisting_docs/`, primary 8-K document only) into price
  events through the existing strict readers (`delistings.read_cash_consideration`, `read_equity_cancelled`); a missing document leaves the event unresolved (three bounds). `rebuild_harness/holdout_inputs.py`:
  `StrictSicResolver` (the SIC as filed from the D2 headers, never the current-dated file; a company with no header by T is `industry_unmapped`), `require_headers_cover` (the whole run refuses while the headers
  download has not reached a holdout date), `require_holdout_configuration` (daily prices, D1 + D3 complete, one window per run). `gate1_run` takes `--prices-daily`, `--delisting-index`, `--delisting-docs`; on a
  holdout date it requires them, uses the strict resolver, the 12-month horizon only and outcomes to 2025-12-31; the freeze contents also name the D1 and D3 folders.
- `valuation/gate1.py` - one company at one date: classification, priors, the discount rate at T (Damodaran files dated before T, the dated FRED risk-free, Hamada on the book D/E with the
  industry D/E when parent equity is not positive or book D/E exceeds the industry's 95th percentile on the date, cost of debt = risk-free + the industry's median spread when there is no clean
  interest line), the family engine over the prior (the distribution's median is the value; P10..P90, the secondary, the disagreement, the terminal-value share), per share on the price's share basis.
- `rebuild_harness/gate1_run.py` - the 36 month-ends 2020-01-31 .. 2022-12-31 from round 4 on (rounds 1-3: the 16 quarter-ends 2019-03-31 .. 2022-12-31; H6: the dates to 2021-12-31 serve the return metrics, the 2022 dates forecast quality only; no price outcome is formed past
  2022-12-31), two passes per date (prepare; measure the population; value), a date per worker; the holdout lock answers first; `--priors-dir` names the vintages folder. The development prices are the
  operator-approved raw monthly pull of 2026-10-01, stamped `raw_monthly_2026-10-01_survivors` (H9).
  `rebuild_harness/gate1_metrics.py` + `gate1_report.py` - B1-B4 under the three survivorship bounds and the structural diagnostics (every figure PROVISIONAL): B1, B2, B3 on the return dates, B4 on every date;
  the old engine is not a yardstick (H7), B3(c) is the absolute floor IQR of ln(IV / price) >= 0.30, a missing yardstick is imputed at the median rank with an indicator. `gate1_compare.py` reads any number of
  reports into one rounds-side-by-side table (round 3 adds draw-rule counts, the cost of equity by family, the prior widths by current level band, and the named I5 refusals). `rebuild_harness/gate1_muse_checks.py` - the leakage audit on real packs and the Item 1 / Item 7 extraction check; `gate1_extraction_recheck.py` re-runs
  that extraction on the same (name, date) pairs (H8: `documents.item_span` reads headings in table rows and wrapped headings; pack v2 template version 2.1).

## Muse passes of the rebuild (`valuation/muse/`; SPEC_muse_passes.md)

Offline; no model, no GPU, no server is started by any module. Tests: `pytest valuation/muse` (a mock model and PLACEHOLDER priors, labelled).

- `pack_v2.py` - the pack: header ("Analysis date: <T>", name and ticker as of T, family, industry) and sections F (filed history), Q (latest quarters),
  D (the company's own documents), S (state), R (population prior and mechanical baseline per input), all from the point-in-time layer at T. The builder has
  no price argument. `documents.py` selects section D under the 16:00 ET acceptance rule (`sec_primary.build` is date-inclusive and cannot be bounded,
  so only its text helpers and fetchers are reused) and reads quarterly facts for Q (the shared layer stores none).
- `prompts/` - versioned templates P1-P6, `system.txt` and `inputs.json`; their sha256 and the hash of the set are recorded in every run's `run_manifest.json`.
  `prompting.py` renders them; pass-1 rendering has no argument that can carry a price.
- `runner.py` - one chat call per prompt to an OpenAI-compatible llama.cpp server (default `http://127.0.0.1:8080`), system prefix `Reasoning strength: xhigh`,
  JSON only, one retry with the checker's message, every request and response saved; a transport failure stops the run (never a fallback value).
- `checkers.py` - quotes (the revision-21 `crux_check` normalisation), the hard-evidence rule for positions outside P10..P90, schema.
- `mapping.py` - percentile + width -> distribution on the prior's quantile function (width factors 0.5 / 1 / 1.5, a stated convention), curve positions,
  `MusePriors` (feeds the unchanged family engines). `reverse.py` - the percentile of each input at which the value equals the price (extraordinary outside
  P5..P95). `redteam.py` - the revision rule and the anchoring metric. `pipeline.py` - one company end to end. `leakage_audit.py` - the scripted leakage audit.
- The priors object may supply `PriorSet.refs["curve_position"](name, state)`, the population distribution of the fraction of the initial gap still open
  five years out (median = the measured curve's value at year 5); without it growth_persistence / margin_retention / rote_retention are not asked of Muse.

## Where the truth lives

- `CLAUDE.md` — standard of proof (read it first)
- `audit/VALUATION_AUDIT_202608.md` — 2026-08 methodology audit: measured findings,
  effort×value chart, adopted plan (Option 2), standing STOP flags (FX, historical SBC, ΔWC)
- `AUDIT.md`, `SESSION_HANDOFF_*.md` — dated reviews and operational handoffs
- `PLAN_FX_INGESTION_20260814.md` — open FX plan for 20-F filers
