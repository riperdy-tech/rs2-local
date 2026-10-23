# 04. Revision 26 (the staged analyst): design, harness, and how to run anything

The authoritative design is `rev23/SPEC_rev26_staged_analyst.md` (sections 1-8 plus Amendments 1-3 in sections 9-11). This file explains it in
operational terms and documents the pilot harness so you can rerun, rescore or extend it.

## 1. The design in one page

Each stage is a **separate model session** (fresh context), on Qwen 3.8 27B via `ollama_raw`. Since pack revision 28 every stage sends its **own
short SYSTEM message** (`r26_late.STAGE_SYSTEM`); before that, the model tag's 2,400-word v33 charter was silently inserted into every stage.

1. **Stage 1, research and fact ledger.** Sees the *blind pack* (the data pack with every consensus-, price- and reference-derived line removed by
   source class; narrative filtered sentence by sentence; a leak audit proves no removed number survives). Tools: `search_web` (SearXNG),
   `fetch_page`, `register_facts`. Each fact: entity, metric, period, value, unit, basis (`filed_gaap` / `company_adjusted` / `third_party` / `n/a`),
   `duration_years`, source, exact quote. Code checks the quote exists verbatim, metric and entity words are within ±300 characters, and the value is in
   the quote; only facts passing the first two are "usable". The dossier is **frozen once per name** (stage 1 never re-runs for the benchmark).
2. **Stage 2, blind forecast, K = 3 samples** (seeds s, s+1, s+2). Sees the blind pack (filed/derived lines only), the usable dossier and the filed
   operating-margin history bar (min/p25/median/p75/max/last). Submits Base/Bull/Bear: years 1-2 growth and operating margin; a normalized state in year
   N (3..5) = a baseline percentile + `delta_pts`; a transition (linear / step_at_year / hold_then_linear); long-run margin, terminal growth, terminal
   return on new investment, fade years, probabilities; fact ids per part; for the Base three labels (margin persistence, cycle position, growth
   trajectory) and (rev 27+) a durability thesis (anchor, mechanism, evidence_limit, failure_condition). Validation is structure only, one repair turn.
   Code builds the path, converts operating margin to the valuation (X) basis with a **bridge calibrated to the filed base year**
   (`K_0 = OI_0 − X_0/(1−τ)`, `X_t = (op_t − K_0/R_t)(1−τ)`), values on the 25.2 desk, computes alternative paths when a cited fact's duration expires,
   and records median and spread = (max − min)/median of the three Base values. Since rev 27: the discount rate is **code-owned** (the cost-of-equity
   anchor), the growth label is **derived by code**, S3 spread attribution is recorded.
3. **Stage 3, reveal and crux.** Sees the median forecast's numbers, the three values, the price and what it implies for each judgment input, a
   basis-corrected consensus (when comparable), the removed price/momentum lines, diagnostics. States a **crux**: 1-3 of coe, fade_years, terminal_g,
   terminal_ronic, long_run_margin with own value, price-implied value and cited fact ids. Code solves each input's price-implied value within bounds;
   Amendment 1: a crux is *reachable* (an input reaches the price alone), *jointly_reachable* (moved together on a 121-point ray they do), or
   *beyond_reach* (valid but non-actionable until reviewed). One content correction plus one syntax-only repair. May revise **once**, citing a fact;
   code records the pull ratio toward the consensus. Rev 27: `path_dominated_crux` when jointly reachable but no input reaches alone.
4. **Stage 4, memo.** Written from a **frozen table** of results; code fills every numeric contract field; a verifier flags memo numbers that differ
   from their labelled table value, the verdict word, label mismatches; rev 27 annotates unknown fact ids.

**Data no-calls** (decided before any model time, outside the scoring denominator): `base_cf_unavailable` (no or non-positive owner earnings),
`shares_unavailable` (no positive share count), `bridge_unavailable` (a missing bridge input, e.g. no tax provision), `family_unresolved`.

**Per-name actionability:** spread ≤ 20% and unanimous direction (and no other non-actionable reason). Every verdict so far is non-actionable at
least because three contract fields have no code source (`contract_fields_unfilled`: conviction score, moat, re-entry tranches).

## 2. The benchmark

- **Panel (12):** MSGE, TASK, PACS, DAC, BUD, GOLD, MCY (the 7 "restoration" names), LPG, ITGR (drawn), KOF, DAR, VSNT (Amendment 1 replacements for
  OGE, HNRG, PTCT, skipped for negative base cash flow). Holdout (untouched): **CTVA, NHC, TTAM, CLDT** (recorded in `frozen_p4r26/_draw.json`;
  note `design.py`'s `P4_R26_HOLDOUT_REGISTERED` constant is stale and still lists KOF, DAR, VSNT, CTVA: the draw file is authoritative).
- **Pass bar (registered; SPEC §6 as amended):** 0 loops; 0 incoherent; ≥83% of callable names coherent; median spread ≤ 20%; ≥83% with unanimous
  direction; median unverified pull ≤ 0.15; 0 memo verdict mismatches. Data no-calls reported as coverage.
- **Readers:** two fresh agents score masked extracts on a 4-criterion rubric (`pilot_r25/READER_RUBRIC.md`; criterion 4 amended 10-22; the original is
  `READER_RUBRIC_v1.md`); disagreements adjudicated by the coordinator in `runs_p4r26/<N>/adjudication.json` with reasons.
- **Canary:** stage 3 re-run on MSGE, TASK, DAC, BUD with the revealed consensus margins shifted ±3 points (or a constructed test consensus); measures pull.
- **Freeze rule (Amendment 2 D):** iteration 3 last; approved for a paper run at 0 incoherent and ≥70% coherent; else "paper-only, low confidence".
  Amendment 3 added a one-change comparison (iteration 4).

## 3. The pilot harness (`C:\Users\riper\stocks\stocks-workspace\scratch\rev23\pilot_r25\`)

Not a git repository. Pinned by hash in the run file. Key files:

| File | Role |
|---|---|
| `design.py` | constants: `P4_R26_TREE_COMMIT` (currently `1484ea2`), panel, seeds (s = SEED_BASE+1 → stage-2 seeds 2502/2503/2504 seen in runs), K=3, smoke name MSGE |
| `pilot_lib.py` | shared helpers; also the offline network block used in P5 builds (`pilot: offline (P5 build, or stub mode)`) |
| `fill_run.py` | writes/re-pins `run_p4r26.txt`: `--iteration N` (re-pins tree commit, tree config hash, script hashes; drops the smoke result; refused for a started iteration: only `cur+1`, or `cur` if unstarted); `--frozen` appends frozen pins |
| `stage_p.py` | stage P: P1 draw, P2, P3 deep research (`deep_research.py` in the tree, research-venv), P4 catalyst/discovery brief, P5 blind pack build (offline, with a one-time online cache warm) and the leak audit; writes `frozen_p4r26/<T>/p*.json`, `STOPPED.json` on a stop; appends frozen pins to the run file (refuses to overwrite differing pins) |
| `stage_r26.py` | kinds `check`, `smoke`, `smoke_e2e`, `stage1`, `stages24`, `canary`; guards (pins, smoke gate, memory cap 4 GB); fail-fast exit 8 on a code defect |
| `run_p4r26.sh` | `run_p4r26.sh <kind>`: sets `PILOT_MODEL=qwen38q5raw`, `P4_R26=1`; needs `STOCKS_ROOT` |
| `launch_detached_p4r26.sh` / `launch_p4r26.vbs` | the scheduled-task wrappers: log to `logs_p4r26/console_<kind>.log`; the vbs writes `logs_p4r26/exit_<kind>.flag` when the kind exits and **quits immediately if that flag already exists** |
| `mask_extract.py` | `mask_extract.py <iteration> [--names A,B] [--out DIR]`: masked extracts for readers → `masked_p4r26/<N>/<T>.md`, audit in `masked_p4r26/<N>_AUDIT/` (hardened 10-22/23; exempts forecast inputs, table input rows and revealed consensus margins from the result-number leak check) |
| `score_p4r26.py` | `score_p4r26.py <iteration>`: the scorecard (reads `runs_p4r26/<N>/readers/reader_A.json`, `reader_B.json`, `adjudication.json`); `DATA_NO_CALL_REASONS` includes base_cf, shares, bridge, family |
| `READER_RUBRIC.md`, `reader_prompt.txt` | what the readers get |
| `run_p4r26.txt` | **the run file**: pins (tree commit, config, scripts, frozen artifacts per name, smoke results, iteration). Backups: `run_p4r26_backup_pre_DAR_repin_2035.txt`, `run_p4r26_tree*.txt` |
| `tree_p4r26/` | a git worktree of rs2 at the pinned commit (detached), with a **hardlinked** `.secrets.json` (search keys; never read it) and its own `cache/` (research, catalyst briefs, sec_8k, quota.json) |
| `frozen_p4r26/<T>/` | per name: p1..p5.json, quote.json, research.md, discovery_brief.json, dossier.json (stage 1), stage1_frozen.json, `r26/_pack.md` + `_pack_facts.json` (blind pack and facts); moved-aside files carry suffixes (`_gaps_prefallback`, `_wifi_1602`, ...) |
| `runs_p4r26/<N>/<T>/` | per iteration and name: forecasts.json, reveal.json, final.json, turns/ (every model turn with system/prompt hashes and token counts), readers/, adjudication.json, score.json |
| `runs_p4r26/stage1/<T>/` | stage-1 sessions and turns |
| `logs_p4r26/` | console logs per kind; exit flags (old ones moved aside with suffixes like `_it3_2026-10-22`) |

## 4. How to run (exact commands, Git Bash)

```bash
cd /c/Users/riper/stocks/stocks-workspace/scratch/rev23/pilot_r25
# offline readiness check (pins, guard, panel, smoke gate status)
./run_p4r26.sh check            # needs: export STOCKS_ROOT='C:\Users\riper\stocks' (run_p4r26.sh refuses without it)
# re-pin a new design iteration after moving the tree
#   1) commit + push on rs2 review-2026-10/r26-int; 2) edit design.py P4_R26_TREE_COMMIT; 3) checkout the tree:
git -C tree_p4r26 fetch -q origin review-2026-10/r26-int && git -C tree_p4r26 checkout -q --detach <commit>
STOCKS_ROOT='C:\Users\riper\stocks' PILOT_MODEL=qwen38q5raw P4_R26=1 "/c/Program Files/Python312/python.exe" fill_run.py --iteration <N>
# score an iteration after its readers
STOCKS_ROOT='C:\Users\riper\stocks' P4_R26=1 PILOT_MODEL=qwen38q5raw "/c/Program Files/Python312/python.exe" mask_extract.py <N>
STOCKS_ROOT='C:\Users\riper\stocks' P4_R26=1 PILOT_MODEL=qwen38q5raw "/c/Program Files/Python312/python.exe" score_p4r26.py <N>
```

GPU runs are launched **only through scheduled tasks** (never from a Claude shell, which the desktop app may kill). Before starting one:
1. move aside any `logs_p4r26/exit_<kind>.flag` for the kinds you want to run (`mv exit_smoke.flag exit_smoke_<reason>_<time>.flag`; never delete);
2. check the GPU is free (`nvidia-smi`, `ollama ps`) and the Wi-Fi is up;
3. `schtasks /Run /TN <task>`.

## 5. The scheduled tasks for this pilot

| Task | Chain (cmd.exe /c wscript launch_p4r26.vbs <kind> && ...) | Notes |
|---|---|---|
| `RS2-P4-R26-IT3` | smoke → stages24 → canary | used for iterations 3 and 4; start boundary 2027-01-01 (manual start only) |
| `RS2-P4-R26-AMEND1` | prep → smoke → smoke_e2e → stage1 → stages24 | the Amendment 1 chain; stage 1 is done for all 12 |
| `RS2-P4-R26-PREP`, `-SMOKE`, `-STAGE1`, `-ITER` | single kinds | older |
`&&` means a non-zero exit stops the chain. A kind whose exit flag exists is skipped (exit 0) and the chain continues: **stale flags silently skip
steps** (this bit us twice).

## 6. Iteration/run state now

- `run_p4r26.txt`: iteration **4**, tree `1484ea2`, smoke result of iteration 4 recorded. `iteration.max` = 4 (all used).
- Tree `tree_p4r26` at `1484ea2`. The newer commit `c255803` (desk diagnostics) is **not pinned** in the pilot (post-freeze; not run).
- `runs_p4r26/1` iteration 1 (non-counting), `/2` iteration 2 (9 names), `/3`, `/4` complete with readers and adjudication.

## 7. Tests

- Interpreter: **system Python** `C:\Program Files\Python312\python.exe` (pytest installed); `research-venv` (`rs2-local\research-venv`) runs deep research only.
- r26 tests: `"/c/Program Files/Python312/python.exe" -m pytest -q -p no:cacheprovider tools/audit_202608/tests/test_r26_*.py` (468 pass at `c255803`).
- Full suite: `... -m pytest tests tools/audit_202608/tests -q -p no:cacheprovider` (≈7-10 min). **Known baseline: 44 failures** (42 pre-existing
  fixture/pin failures + 2 stale byte-identity pins); compare failures **by name** against a previous run, never by count only. One flaky timing test
  (`test_llm_provider_p7_ports.py::test_missing_timings_fall_back_to_wall_clock`) occasionally fails.
- Pilot tests: `pilot_r25/test_mask_extract_leaks.py` (10), `tests/` folder.

## 8. Research (stage P3) mechanics

- `deep_research.py` (in the tree) uses LDR (local-deep-research) in `rs2-local\research-venv`, with SearXNG at `http://localhost:8888` (Docker container
  `searxng`; settings `rs2-local/searxng/settings.yml`, `keep_only` engines) and the keyed fallback chain tavily → exa → serper (keys in `.secrets.json`,
  read via `quota.key`; usage in the tree's `cache/quota.json`). Since `bb0d7ab` a topic falls back when a backend leaves no *usable* sources.
  Since `24ff859` (included in the pinned tree `1484ea2`) an empty answer while the internet is down is an infra failure, and a stage-1 research call
  waits up to 45 min for the network.
- The research bound is `research_timeout_s` = 900 s per name (config.json); exceeding it stops the name (exit 3).
- A brief is written with up to half its topics missing ("NOT RESEARCHED" declared); 4/5 failed topics abort.

## 9. Checking that nothing is running

```bash
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
ollama ps
schtasks //Query //FO CSV | grep -i -E "RS2|MRI"          # look for "Running"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | ? { \$_.CommandLine -match 'stage_r26|stage_p|deep_research' } | select ProcessId,CommandLine"
```
