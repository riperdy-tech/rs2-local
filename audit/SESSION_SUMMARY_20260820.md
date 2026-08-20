# RS2 — SESSION SUMMARY, 2026-08-18 → 2026-08-20

**Purpose: this is the single document to hand a fresh session.** It states the operating
configuration, what was proven, what was disproven, and what is open. Every number here was
re-verified against the live tree on 2026-08-20 before this file was written.

Read order for a new session: **this file → `HANDOFF_20260820.md` §2b (target architecture) →
`G_queue_verification_20260820.md` (which supersedes `HANDOFF` §2) → `PIPELINE_MAP_20260820.md`.**

---

## 0. CURRENT STATE — read this before touching anything

| | |
|---|---|
| **Sweeps** | **PAUSED.** `cache/PAUSED` exists. The Windows scheduled task is still enabled but exits at the pause check. |
| **Production pipeline** | Changed substantially this session and **has not run once since**. First sweep after resume is a live test. |
| **Git** | **12 commits ahead of `origin/main`, unpushed.** Nothing published to the site since the pause. |
| **Overlay / site** | Frozen coherent at 172 names. |
| **Screener data** | Rebuilt (backups `*.bak-20260820`). |
| **GPU** | Clear, no model resident. No background jobs running. |
| **Working tree** | Clean except `api_llm/usage_log.jsonl` (other session) and untracked `RS2-Analyst-38.Modelfile`. |

---

## 1. THE MODEL STACK — which Qwen, and how it is configured

This is the question the previous handoff failed to answer plainly. All values verified from
`config.json` and the Modelfiles on 2026-08-20.

### Production analyst — `rs2-analyst`

- **`config.json` `model` = `"rs2-analyst"`.** This tag is what production runs. It stays constant
  across base-model swaps; the base is changed inside `RS2-Analyst.Modelfile`.
- **Base: `qwen3.8:27b-mtp-q4_K_M`** — Qwen3.8-27B **dense** (all 27.3B params active per token),
  Q4_K_M, with the **MTP speculative-decoding head** (draft-4): 48.5 tok/s vs 35.8 without (+35%).
- **Thinking is OFF** — `config.json` `"think": false`. This is deliberate and evidence-backed:
  thinking measurably broke the report contract (MU failed 2/2 thinking runs, 0/1 think-off).
- Sampling: `temperature 0.4`, `top_p 0.9`, `top_k 20` — Qwen's **non-thinking** profile.
- Migrated 2026-08-18 from `mdq100/qwen3.5-flash:35b` (35B-A3B MoE, 3B active).
  Evidence: `api_llm/QWEN38_AB_REPORT_20260818.md` — 9-ticker A/B, think-off arm avg 10.6 min/name,
  8/9 clean single-attempt audits vs flash 4/9, verdict directions agreed 9/9.
- Resident footprint 19.1 GiB @ ctx 32768 on the 24GB card (flash was 21.6).
- **Revert path** is written into the Modelfile header: set `FROM` back to flash, `num_gpu` 42,
  `"think": true`, `ollama create rs2-analyst -f RS2-Analyst.Modelfile`.

### Depth / audit tier — `rs2-analyst-deep`

Built this session **for audit work only. Production is untouched by it.**

- **Base: Qwen3.8-27B `UD-Q5_K_M`** (Unsloth Dynamic — sensitive layers kept at higher precision).
  Q5_K_M is +0.0415 ppl vs Q4_K_M's +0.0796: about half the quantization loss, concentrated in
  arithmetic and long-context coherence, which is exactly this workload.
- **Text-only** — the 0.93GB / 460.73M-param CLIP projector is deliberately excluded. Never used for
  equity analysis; the VRAM buys KV cache instead.
- **Thinking sampling profile**, and both penalties are **zero** (`presence 0`, `repeat 0`). Qwen
  documents that a repetition penalty over a long reasoning trace bans common-but-necessary tokens
  and degenerates the completion. Never greedy-decode.
- **Context is deliberately NOT pinned** — the caller sets `num_ctx` (audit harness uses 65536).
- `rs2-analyst-deep-q4` is a **byte-identical twin except the weights** (Q4_K_M). It exists only to
  isolate quantization; the earlier arm B could not, because it ran production's template so quant
  and template moved together.

### Research model — `rs2-research`, `research_ctx` 8192.

### Thinking levels — the corrected facts

Ollama accepts `true / false / low / medium / high / max`. Measured on the deployed model:

- **`true` == `low`.** (The operator was right to challenge the earlier "thinking is just on/off".)
- **`max` is INVALID** on a correctly-templated Qwen3.8: HTTP 500 **before generating a token**.
  The chat template resolves `reasoning_effort|default('xhigh')`, and `max` is not a member.
- **Use `"high"`.** All depth-tier callers now default to it (`analyst_tools.py:150`,
  `capability_test.py:513`, `consensus_valuation.py:164`). Fixed in `ba1b61d`.
- ⚠️ **Stale comment:** `RS2-Analyst-Deep.Modelfile` header still says *"Depth tier calls with
  max."* The code is right, the comment is not. Harmless but should be corrected.

---

## 2. LIVE CONFIG VALUES (verified 2026-08-20)

| key | value | note |
|---|---|---|
| `model` | `rs2-analyst` | |
| `think` | `false` | was dead config until wired at `run_rs2:2132` |
| `stage_ctx` | **49152** | raised from 24576 this session |
| `final_ctx` | **49152** | raised from 32768 this session (`7923525`) |
| `research_ctx` | 8192 | |
| `research_model` | `rs2-research` | |
| `research_timeout_s` | **900** | **new this session** (`aa50c76`) |
| `ticker_timeout_min` | **40** | **deliberately NOT raised** — see §5 |
| `vram_unload_timeout_s` | 180 | |
| `searxng_url` | `http://localhost:8888` | local, unmetered, no API key |

Underscore-prefixed `_*_note` keys in `config.json` are **inert** (no code path reads them) and
carry the measurement rationale for each value. They are worth reading.

---

## 3. WHAT WAS PROVEN

**On the method itself — the central finding:**

- RS2's fair value is arithmetically `base_cf × M(g,wacc) × price/mcap`. **R² 0.885** against the
  trailing scalar alone; **0.025** against the full DCF. *It ranks by one trailing accounting yield;
  it does not value.*

**On the model — the operator's thesis was substantially right:**

- The local model is **not** the bottleneck. Unshackled, it caught GOOG's ~$100B one-off
  **unprompted**. The shackled pipeline published **$702.49 / +97.4% MoS** on the same data.
- Letting it **search during reasoning** moved GOOG from $270 → $240/$161 against a $205 benchmark.
- **But unshackling does not fix instability**: six free runs span **$161–$335**.
- Apparent consensus between runs was **compensating errors** — three GOOG valuations shared one
  unsourced 2027+ capex-collapse assumption. Refusing it moved them $317/$321/$273 → $204/$178/$149.
  That single invented assumption decided the answer.

**On the harness:**

- **Q4 truncates, Q5 does not** — 4/6 vs 0/6 on the depth tier.
- **Quantization bought nothing; the harness did** (`6f1871a`).
- **Seeding is deterministic** for a fixed (prompt, seed, num_ctx) — *on the audit harness at
  num_ctx 65536*. This does **not** prove production's windows reproduce. Do not overstate it.
- **226 context-wall hits** across three Ollama logs: 177 @ 24575 (old `stage_ctx`), **45 @ 32767**
  (old `final_ctx`), 2 @ 8191 (helper calls). Both large buckets are **now fixed**.
- **The 40-min watchdog fired 4 times ever**, none of them analyst generation. ARGX ×3 on 08-18 —
  deep research alone ran **1,967s (32.8 min)**, one SearXNG subquery taking 1,035s against a p90
  of 121s. ARGX has not published since 2026-07-23.

**On the data:**

- Extraction rewritten (stitch → component slots → curated allowlist): revenue nulls
  **17.2% → 3.1%**, D&A **20.4% → 4.0%**, GOOG lattice un-collapsed **1 → 2 cells**, book
  single-cell **57 → 24**.
- **934 dead pack fields** — five fields printed the literal string `"None"` for all 172 live names
  because upstream keys moved (`pe_ratio` → `metrics.pe_ratio`, `short_percent_float` →
  `short_pct_float`). Undetected for months; no existing check could see a *uniformly absent* field.
- `openbb metrics.price_to_sales`: present on 294 records, **non-null on zero**.

**On the prompts and the auditor:**

- The "Basis judgment" contradiction is **real but has cost zero rejections** — all 6
  `MISSING BASIS JUDGMENT` charges **predate** it.
- **Auditor rule 1b vs rule 3 is real and does cost rejections** — 24 phantom "missing section"
  charges, all false against the full file, all on reports where `tier1_pass=True`.
- **8 auditor violations provably quote the pre-brake number the model actually wrote.** `KNSA` was
  capped 12→9.5 and then charged with **FABRICATION for stating its own score**. Fix by feeding
  pre-brake fields to the auditor, **not** by weakening the check — 17 of the 65 catch real
  inconsistency and must keep firing.
- **`_stance_from_gap` is blind to MoS**: **261/422 = 61.8%** of deterministic-era `fair` verdicts
  carry MoS ≤ −30% (GLBE −73.7% at gap −0.2).

---

## 4. WHAT WAS WITHDRAWN OR DISPROVEN — do not cite these

- **C1–C6 are WITHDRAWN.** A naive "buy what fell" reversal null **beat** MoS (ρ **+0.567** vs
  **+0.404**) on 8 entry dates in a single 30-day window — the most reversal-favourable month of 16.
- **C3's SBC experiment double-counted.** GAAP net income already expenses SBC. Corrected by C10;
  scope narrowed to the 45 FCF-derived names. `C_findings.md` carries a CORRECTION banner.
- **"Steps 1–5 move no published number" is FALSE** — the most consequential error in the previous
  handoff. `llm_overlay.json` is git-added, committed and **pushed** by `orchestrate.py:960-974`
  (Vercel auto-redeploys). Its payload carries **model-emitted** `action`, `conviction`,
  `stance_score`, `thesis_break`, `changed_because`, `recommended_weight_pct`. Only `stance` is
  deterministic. **Every S3 / FINAL_TASK / auditor-pack edit moves published fields.**
- **Arms A vs C were confounded seven ways**; the A/B was rebuilt with a byte-identical twin.
- **`F_config_findings_20260820.md` is stale in two places** — its §6 still says GOOG's lattice holds
  one cell (it holds 2), and its line-number and token-range claims are wrong.
- Earlier in the session I claimed sweeps were paused when **`cache/PAUSED` did not exist** and the
  08:00 sweep had already run and pushed. Inherited from a session-start survey and never verified.

---

## 5. WHAT IS OPEN — in priority order

`G_queue_verification_20260820.md` **supersedes `HANDOFF_20260820.md` §2.** Five measurement passes
were run against the live tree, each handed to an adversarial pass instructed to refute it; **all
five original queue premises came back `survives: false`.** What remains:

1. **`retries=1` at `run_rs2.py:2156`.** `for attempt in range(retries)` runs **one** attempt, so the
   context-escalation ladder never advances past attempt 0 and the `RuntimeError` is unwrapped. A
   report that overruns even 49,152 still kills the ticker and burns a full rerun including deep
   research. The window was raised; **this tail is uncovered.** Watch it on the first sweep.
2. **⚠️ `repatch_verdicts.py` + `build_mos_distribution` must ship in ONE commit.** Fixing repatch
   alone **republishes GOOG at $702.49** — repatch is currently the only thing suppressing it, and
   `MOS_EXTREME_MAX` catches **none** of the 8 names ≥ +50% resolved MoS
   (GOOG, GOOGL, HRMY, FSLR, NICE, META, EXEL, HCSG).
3. **`ticker_timeout_min` stays at 40.** Raising it would weaken the only bound on what *was* the
   only unbounded phase. Now partly moot: `research_timeout_s=900` bounds research directly. The
   longest *healthy* research phase on record is ~33 min, so any future ticker bound must sit above
   that or it starts killing good names.
4. **Regime-decider ctx 8192 → 16384.** Right target, but both stated reasons were wrong: **0 of 170**
   live-book prompts overflow 8,192 (max 7,708). The real case is a ~14s context reload per contested
   name, not evidence loss. Low priority.
5. **Seed threading.** Seven call sites confirmed: 305, 1077, 1783, 2156, 2406, 2418, 2430.
   Two traps in §6.
6. **§2b shadow-arm test** — the target architecture: **AI specifies, code computes, guard judges.**
   The model picks the engine and the `base_cf` definition (FFO / owner earnings / 50/50 blend /
   FCF fallback); code only executes the arithmetic it was told to. This is the operator's explicit
   direction and the main unbuilt thing.
7. **Plausibility-guard thresholds are my picks, not corpus-calibrated** (`BAND_HIGH_MULT=1.5`,
   `BAND_LOW_DIV=3.0`, `OCF_MULT_MAX=40.0`, `MOS_EXTREME=1.50`, `TOL_PCT=25.0`). Calibrate from the
   corpus before relying on them. **I owed this to the handoff and it is still not done.**
8. Longstanding: FX ingestion for 20-F filers, historical SBC ingestion, f16 KV probe at 64k.

**No corpus-replay tooling exists.** `o2_replay_review.py` replays `valuation_backbone.backbone(t)`
only — no FINAL.md, no auditor, no LLM. There is no writer for `_replay_set.json` /
`_replay_results.json`, and `run_rs2.py` has no `--audit-only`.

**The replay population must be partitioned before it can attribute anything.** Of 818 `audit.json`:
463 pre-`e1900bc` auditor prompt on flash, 340 current prompt on flash, and **only 15 under the
current prompt on the deployed Qwen3.8.** A null arm is required first.

---

## 6. TRAPS — each of these cost real time this session

- **`TaskStop` does not kill child processes.** A bash loop and its Python children survived and
  advanced two tickers. Kill the loop, kill Python, then unload the model from VRAM.
- **`run_rs2.py:2418` and `:2430` are byte-identical.** A `replace_all` edit gives both the same seed
  index and reintroduces the exact sample collapse the change exists to prevent. **Edit by line
  number.**
- **Off-by-one at `run_rs2.py:212`.** Any seed-perturbation formula must pass `call_seed`'s output
  **unmodified** at `attempt == 0`, or no published draw is regenerable from the recorded base.
- **`api_chat()` takes no seed and sends none**, and `api_chat.py:93` builds the request body
  *outside* the retry loop. Do not ship a cloud seed field that creates a false impression of
  determinism.
- **`.claude/worktrees/strange-perlman-3498fc`** is a detached worktree at `b196163` holding full
  copies of `run_rs2.py` (−111 lines vs live) and `RS2-Analyst.Modelfile`. **Any recursive grep from
  the repo root returns both copies**, so a `file:line` harvested that way can be wrong by up to 111
  lines. Needs a decision.
- **Never re-wrap `sys.stdout` at import in a library** — it closed the caller's wrapper and killed
  the first tool-enabled run (`analyst_tools.py:37-40`).
- **A tool-loop `break` on budget exhaustion returns an empty report** — one sample produced 59,074
  chars of thinking and **0 chars of report**. Force a final answer instead.
- **The Q5 pull filename is `UD-Q5_K_M`, not `Q5_K_M`.**
- **A BOM wipes orchestrator state.** (See memory `rs2-orchestrator-ops`.)
- **Three grader false negatives** this session, all from regex slips — and **every one flattered my
  prior conclusion.** Check the grader before believing a result that agrees with you.

---

## 7. OPERATOR CONTEXT

- RS2 is for **personal wealth-building**. The operator is a non-expert and wants **honest
  assessment, not validation**.
- **Standing authorization given verbatim:** *"I hereby give you UNLIMITED access to all my repos.
  Do as you wish as long as it gets the job done"* and *"push to main on screener repo. you have my
  approval."*
- **Explicit direction on architecture:** *"screen ALL the valuation layer and make absolutely 100%
  sure … nothing is decided using code or script. Let Qwen 3.8 decide"*, and *"'after it speaks'
  brake and gates and holds all that — get rid of it. I want to revalidate everything from baseline
  — which is what Cloud AI does, using the deterministic dataset we have."*
- **Wants diligence spent on getting the RIGHT data**, and on finding missing data — not on
  constraining the model.
- **No re-route, no second method, no blend** as a fallback when an evaluation fails.
- **Prefers short answers.** Said so directly, more than once.
- **Do not start long-running background work without being asked.** I did this after being told the
  session was being refreshed, and was rightly called out.

---

## 8. DOCUMENT MAP

| file | what it is | trust |
|---|---|---|
| `SESSION_SUMMARY_20260820.md` | **this file — start here** | current |
| `G_queue_verification_20260820.md` | supersedes `HANDOFF` §2; five refuted premises | current |
| `HANDOFF_20260820.md` | §2b target architecture is the live part | **§2 superseded by G** |
| `PIPELINE_MAP_20260820.md` | process tables, rules-and-shackles, cloud-vs-ours | current |
| `E_methodology_verdict_20260820.md` | methodology verdict; withdraws C1–C6 | current |
| `D_base_contamination_20260819.md` | GOOG $702.49 root cause, defects D1–D6 | current |
| `F_config_findings_20260820.md` | config findings, arms A–D, probes P1–P3 | **stale in §6 + line refs** |
| `C_findings.md` | experiments C1–C10 | **C1–C6 withdrawn; C3 corrected** |
| `A_institutional_checklist.md` / `B_gap_analysis.md` | institutional standard + gap analysis | B corrected re: consensus_snap, SBC |
| `VALUATION_AUDIT_202608.md` | effort×value chart, three options | Option 2 marked APPLIED |

Experiment scripts: `tools/audit_202608/` (c1–c10, p1–p3, `consensus_valuation.py`,
`analyst_tools.py`, `capability_test.py`, `tag_coverage_census.py`).

---

## 9. THE HONEST CAVEAT

There is **no accuracy oracle** in this system. Every campaign run this session could demonstrate
*method appropriateness and repeatability* — it could not demonstrate *correctness*. Six names is
enough to see whether routing works; it is not enough to conclude the valuations are right.

Under CLAUDE.md §0 that is a **stop condition to be stated, not a gap to be papered over**.
