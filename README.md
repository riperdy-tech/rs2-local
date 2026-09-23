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

## Verdict provenance and gating (P1.2/P1.3/P1.5)

Every depth verdict (`verdict_depth.json`, each ledger row) carries, stamped by
`depth_pipeline.stamp_and_route()`:

- `run_source` — how the run was invoked, resolved by `depth_pipeline._run_source()`:
  `--ondemand` always wins; then the `RS2_RUN_SOURCE` env var a spawner sets
  (`orchestrator` | `cloud`); then `--production` for an operator-invoked production run;
  anything else is `manual` — a bare, unmarked `python depth_pipeline.py TICKER`.
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
2. `gate_version` absent or `< GATE_VERSION` (currently 2) -> `pre_v3.1_gates`
3. `n_basis == 1` -> `single_sample`
4. `fiduciary_verdict == "FAIL"` -> `fiduciary_fail`
5. `direction == overvalued` and `kelly_fraction_pct > 0` -> `kelly_on_overvalued`
6. `direction == undervalued` and `spread_pct > 25` -> `high_dispersion`
7. `run_source` in `{manual, test}` -> `non_production_row`

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
| `depth_test_ledger.jsonl` | `run_source == "manual"` — a bare, unmarked invocation with no `--ondemand`/`--production`/`RS2_RUN_SOURCE`; a loud Telegram notice fires so it is never mistaken for a production row |

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
ledger under `_archive/`, `ondemand`, `test`), each tagged `ledger_source`. `actionable` is
recomputed live via `depth_gates.assess` on every row, never trusted from a ledger stamp — most
rows on record predate P1.2/P1.3 and never had one. Nomination context (sector, cluster,
`nominated_doors`, `z_momentum`, `z_value`, `z_exp_gap` from the screener's
`factor_scores_dual_door.json` profiles; `fct_band`/`fct_rank` from the nearest
`factor_signal_log.jsonl` run) is joined only within 10 calendar days of the verdict date —
outside that window, or with no matching artifact, every one of those fields is `None`, never
guessed.

Outputs `cache/depth_outcome_prices.json` (its own price cache: every graded ticker plus
IWM/SPY/QQQ and a 17-ETF sector/industry cluster proxy set), `cache/depth_outcomes.json` (graded
rows, per-horizon cuts — direction, spread bucket, size, conviction/`mos_vs_base_pct`/`z_momentum`
terciles, nominated doors, arm, pack revision, sector, cluster, ledger source — Spearman
correlations, and a generated `caveats` block), and `reports/depth_outcomes_report.md`. A bucket
under 10 verdicts is still shown, flagged `inconclusive`, never silently dropped. The caveats block
states, from the data, how many graded rows are pre-current-gates (`gate_version` absent or < the
current `depth_gates.GATE_VERSION`) — as of Phase 2 that is all of them, so no conclusion about the
CURRENT analyst may be drawn from anything this grader reports yet; it exists so it is ready for
valid verdicts after Phase 4.

`orchestrate_depth.main()` re-runs it `--offline` (no network) at the end of every sweep,
non-fatal and logged (`run_offline_grader()`); `publish_overlay()` copies `depth_outcomes.json` to
the site as `public/data/depth_outcomes.json` alongside the overlay, when present, JSON-validated
before staging like every other publish artifact. A weekly network refresh (Sunday 09:00) is
prepared as `register_grader_task.ps1` (mirrors `register_depth_task.ps1`) but is NOT
registered — registering a Windows Scheduled Task is a machine change and needs operator approval.

## Where the truth lives

- `CLAUDE.md` — standard of proof (read it first)
- `audit/VALUATION_AUDIT_202608.md` — 2026-08 methodology audit: measured findings,
  effort×value chart, adopted plan (Option 2), standing STOP flags (FX, historical SBC, ΔWC)
- `AUDIT.md`, `SESSION_HANDOFF_*.md` — dated reviews and operational handoffs
- `PLAN_FX_INGESTION_20260814.md` — open FX plan for 20-F filers
