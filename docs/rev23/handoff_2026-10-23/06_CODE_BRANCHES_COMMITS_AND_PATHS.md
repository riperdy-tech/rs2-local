# 06. Code, branches, commits, worktrees and paths

## 1. rs2-local (PUBLIC repo `github.com/riperdy-tech/rs2-local`)

Main checkout: `C:\Users\riper\stocks\rs2-local` (do not develop there for this work; it holds production config, `.secrets.json`, `cache/`,
`research-venv`, the SearXNG settings). Work happens on review branches in worktrees under `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\`.

### Branch `review-2026-10/r26-int` (the revision-26 integration branch) — head `c255803`, pushed
Worktree: `scratch\rev23\wt-r26-int`. Commits of this window, newest first:

| Commit | What |
|---|---|
| `c255803` | post-freeze desk diagnostics: verifier accepts printed-table rounding; tax from multi-year median (else unavailable, no clip); `cash_scaling_out_of_band` (kappa outside [0.67,1.5]) non-actionable; `terminal_growth_positive_for_shrinking_business` annotation |
| `1484ea2` | **pack revision 28** (Amendment 3): each stage's own SYSTEM message (`r26_late.STAGE_SYSTEM`) — **the frozen design** |
| `7cc1f57` | merge of `mri/query-retry-on-lock` (reviewed): `_mri_query` retries a locked MRI store 6×10 s then raises `MriStoreLocked` |
| `31dc1a8` | **pack revision 27** (Amendment 2): code-owned discount rate, code-derived growth label, Base durability thesis, labelled alternative values, grounded memo rule, path_dominated_crux, margin_level_without_filed_fact, S3 attribution (`tools/r26_spread.py`) |
| `afec2b0` | `shares_unavailable` data no-call (KOF) |
| `dd7f9ff` | (MRI session) retry-on-lock in `rs2_data._mri_query` |
| `24ff859` | network guard (`ops.internet_up`, `wait_for_internet`; research infra failure when offline; stage-1 calls wait ≤45 min); conftest stubs the probe in tests |
| `abd2052` | `removed_number_collision`: a narrative sentence colliding with a removed number without filed support is dropped and listed (`blind_split_audited`) |
| `b1ac1e9` | leak audit: 8-K Item 2.02 releases of the trailing year are filed support (`sec_guidance.earnings_releases`); a $ amount fact never matches %/x |
| `bb0d7ab` | `deep_research.run_topic`: fall back when an answer leaves no usable sources |
| `15669dc`, `05d925b` | Amendment 1 (reach up front, joint ray, outcomes, syntax repair) |
| `50ca97a` | iteration-1 defect fixes (data no-call for non-positive base_cf, verdict parser, crux detail, fail-fast) |
| `656da7d` and earlier | revision-26 build (R26-A..G), leak-audit fixes (`ddf133e`, `ff55ed3`, `3d574bf`), `58d7bdd` bridge_unavailable, `9da836f` R26-F |

Key source files (paths relative to the rs2 root):
- `tools/audit_202608/r26_stages.py` — the stage runner: stage 1 (`run_stage1`, fact checks), `valuation_inputs` (data no-calls; kappa inputs),
  `bridge_facts_from_row` / `load_bridge_facts` (tax rule), `code_owned_inputs`, `derive_labels`, `margin_basis_flags`, `_dispatch_net` (network guard),
  `run_stage2` (K samples; attribution), `run_stage3` (crux, reach, revision), `assess_reach`, `run_stage4` (memo, verifier, contract, flags:
  `PATH_DOMINATED_*`, `BEYOND_REACH_*`, `cash_scaling_flag`, `shrinking_terminal_flag`), `fresh_messages` (SYSTEM + user), `PACK_REVISION_R26 = 28`.
- `tools/audit_202608/r26_late.py` — TASK texts (`STAGE2_TASK`, `STAGE3_TASK`, `STAGE4_TASK`), `STAGE_SYSTEM`, schemas (`scenario_schema`,
  `forecast_properties`, `SUBMIT_FORECAST_TOOL`), `validate_labels`, `validate_durability`, `derive_growth_trajectory`, `table_rows` (with alt rows),
  `alt_label`, `render_diagnostics`, `render_bridge_table`, `verify_memo` (+ unknown fact ids), `rounds_to`.
- `tools/audit_202608/r26_blind.py` — blind pack, narrative filter, leak audit, `_filed_support`, `collision_rule`, `blind_split_audited`, consensus correction.
- `tools/r26_forecast.py` — forecast schema validation, path builder, bridge (`bridge_to_x`, `_bridge_inputs`, `invert_bridge`), `value_forecast`,
  alternative paths, aggregate, directions, pull.
- `tools/r26_spread.py` — S3 attribution (`attribute_spread`).
- `tools/audit_202608/financial_model_tool.py` — the desk (25.2 path; **kappa defect at :2111-2112, :585, :597-606**).
- `tools/audit_202608/ollama_raw.py`, `llm_provider.py` — the raw provider; `template_messages` inserts the tag's SYSTEM only when the harness sends none.
- `deep_research.py`, `ops.py`, `quota.py`, `sec_guidance.py`, `rs2_data.py` (MRI queries) — research and plumbing.
- Tests: `tools/audit_202608/tests/test_r26_*.py` (468 at `c255803`), `tests/test_network_guard.py`, `tests/test_mri_query_lock.py`,
  `tests/test_deep_research_usable_fallback.py`.

### Other rs2 branches of this period
- `review-2026-10/r26-harness` (`481d0cf`), `r26-desk` (`4d2504f`), `r26-pack` (`52f2686`): the parallel build branches, merged into `r26-int`.
- `mri/query-retry-on-lock` (`dd7f9ff`): the MRI session's branch, merged.
- `review-2026-10/d2-port` (D2 desk port part a), `review-2026-10/d2-facts` (`031ab88`, D2 inputs), `review-2026-10/ollama-raw` (`141c413`), the
  rebuild branches (`rebuild-int`, `rebuild-harness`, `rebuild-engines`, `rebuild-muse`, `rebuild-priors`), `review-2026-09/rev21`, `phase-4`,
  `review-2026-09/phase-6-on-rev21`: earlier work; none merged to `main`.
- **`docs/rev23-records`** (`fcffa4c` at writing): the records mirror; worktree `scratch\rev23\wt-docs`; files under `docs/rev23/`.

### Pushing rules
- Scan the diff for secrets before every push (`git diff -- <files> | grep -i -E "api[_-]?key|secret|token|tvly-|sk-|Bearer"`).
- Commit by pathspec (`git commit -- <files>`); never `git add -A` in shared repos; never bare `git stash`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Watch out: bulk `sed -i` on many files rewrote line endings (LF vs CRLF) of untouched files; restore those with `git checkout -- <file>` only if
  `git diff --ignore-cr-at-eol` is empty.

## 2. stock-screener
- Live code: the `screener-publish` clone = `origin/main` (`C:\Users\riper\stocks\screener-publish`). The local dev checkout
  `C:\Users\riper\stocks\stock-screener` is on an OLD branch from another session (no Door 3) — do not use it for analysis.
- The ranking script: `scripts/score_factors_dual_door.py`. Branches of this era: `review-2026-10/d2-fields` (`65328f973e`, `1c06210ef6`).

## 3. Records and docs (stocks-workspace, not a single git repo you commit to casually)
- `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\rev23\` — all plans, specs, cross-checks, reports (see file 00). Mirror changed files to
  `scratch\rev23\wt-docs\docs\rev23\` and commit/push there (that is how they reach GitHub).
- `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\STATUS.md` — the one-page status (local; stocks-workspace has other sessions'
  uncommitted changes, so STATUS.md is edited in place, not committed).
- `...\review_2026-09-22\reports\STATUS_PHASE4_HISTORY_*.md` — archived Phase-4 sections (latest `_2026-10-22.md`).
- This handoff: `...\rev23\handoff_2026-10-23\`.

## 4. Scratch folders (stocks-workspace\scratch)
- `rev23\pilot_r25\` — the pilot harness (file 04).
- `rev23\wt-*` — rs2 worktrees (many older ones exist; leave them).
- `rev23\handoff_artifacts_2026-10-23\` — copies of session-scratchpad artifacts: engine measurement, reader folders with extracts and JSON for
  iterations 2-4, the stage SYSTEM text draft, helper scripts (`namecheck*.py` prints a per-name summary of an iteration), task XMLs, suite outputs.
- `baselineA\` — baseline A pipeline, data, report.
- `qwen_cutoff\` — the cutoff probe, report, raw answers.
- `baseline-2026-10\` — the old Phase 6 baseline (task removed; 33 results).
- `sec_data\` (under rev23) — SEC companyfacts 2026-10-18.

## 5. The session's temporary folder (may disappear)
`C:\Users\riper\AppData\Local\Temp\claude\C--Users-riper-stocks\69b4116b-d43f-4a78-867f-8f8db1d8ff91\scratchpad\` — the important parts are copied to
`handoff_artifacts_2026-10-23`. The session transcript is
`C:\Users\riper\.claude\projects\C--Users-riper-stocks\69b4116b-d43f-4a78-867f-8f8db1d8ff91.jsonl` (very large).
