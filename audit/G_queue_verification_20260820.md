# G — VERIFICATION OF THE §2 QUEUE (2026-08-20, later same day)

Successor check on `HANDOFF_20260820.md` §2 steps 1–5. Every step was measured against the live
tree before any edit. **Most of the queue's stated premises did not survive.** Per CLAUDE.md §0 the
corrections are recorded here in the same breath as the work.

Method: five measurement passes (one per step), each then handed to an adversarial pass instructed
to refute it. All five original findings came back `survives: false`. What follows is what survived
the second pass, plus what was verified directly.

---

## 0. THE HEADLINE — a live regression, not on the queue at all

**45 final-assembly completions truncated at the context wall, and since `9ba2929` each one now
kills the ticker outright.**

Measured across all three Ollama server logs (2,821 `stop processing` lines, 226 wall hits),
bucketed by `n_tokens = num_ctx − 1`:

| bucket | events | window | dates | status |
|---|---|---|---|---|
| 24575 | 177 | `stage_ctx` 24,576 | 08-17 ×63, 08-18 ×105, 08-19 ×9 | **fixed** (stage_ctx now 49,152) |
| **32767** | **45** | **`final_ctx` 32,768** | **08-17 ×25, 08-18 ×20** | **STILL OPEN — final_ctx unchanged** |
| 8191 | 2 | helper calls (`regime_decide`, `get_assumptions`) | 08-19 | open, low severity |
| 40959 / 65535 | 1 / 1 | depth-tier | — | experimental |

The session raised the stage window and left the final window alone. Before `9ba2929` a truncated
final published as a silent stub. Now `run_rs2.py:236` raises — and `run_rs2.py:2156` passes
`retries=1`, so `for attempt in range(retries)` runs **one** attempt, the context-escalation ladder
(`this_ctx = min(ctx * 2**attempt, 131072)`) never advances past `attempt 0`, and the `RuntimeError`
is **unwrapped**. The ticker dies and burns a full rerun including deep research, against
`MAX_RETRIES=3`.

45 events in two days. It will fire on the first sweep after resume, preferentially on the longest
and richest reports — the exact selection-against-quality §2 step 1 was written to prevent, arriving
through a different door.

**This outranks all of steps 1–5. It is one line, but it is a live-behaviour change and it is the
operator's call.**

---

## 1. STEP 1 — `ticker_timeout_min`: the diagnosis was pointed at the wrong phase

The queue says a larger `stage_ctx` lets a stage generate more, so the most productive run is the
one the 40-minute watchdog kills. **Measured: the watchdog has fired exactly 4 times ever**, and
none of them was analyst generation.

`reports/_orchestrate.log`, 57,723 lines, all four firings:

- NOVT ×1
- **ARGX ×3 on 2026-08-18** (13:07:54 / 13:54:28 / 14:38:02) — the full retry budget, all killed.
  **ARGX never published; its newest bundle is `reports/ARGX_20260723_011459`, now a month stale.**

Attempt 3 is legible in the log: deep research alone ran **1,967s (32.8 min)** across four
subqueries — 1035s / 775s / 98s / 59s via searxng — leaving ~7 of the 40 minutes for six analyst
stages that need ~10. The binding constraint is **deep_research latency**, not generation.

**The structural gap:** `run_rs2.py:2038` is
`subprocess.run(cmd, capture_output=True, text=True, ...)` with **no `timeout=`**, and
`deep_research.py` contains exactly **one** timeout in the entire file (line 161, a 20s SearXNG
preflight probe). The research phase is unbounded, and this ticker-level watchdog is the only thing
bounding it. `capture_output=True` also buffers the child until exit, so the log is silent for the
whole phase and cannot distinguish a stall from slow-but-healthy work — which is why no heartbeat
budget can be derived from the current log either.

**Raising `ticker_timeout_min` weakens the only bound on the only unbounded phase.** Left at 40.
The fix belongs at `run_rs2.py:2038` / inside `deep_research.py`, and needs an operator decision on
what a legitimate research ceiling is — the longest *healthy* research phase on record is ~33 min,
so any bound must sit above that or it starts killing good names.

---

## 2. STEP 2 — regime ctx 8192: right target, both stated reasons wrong

`F_config_findings_20260820.md:130-131` is wrong on all three of its claims:

| claim | measured |
|---|---|
| "`run_rs2.py:1033`" | the call is at **:1077** (HANDOFF:143 has it right; 1033 is a cycle-history f-string) |
| "prompts 7,581–7,880 tokens" | true production prompts **7,224–7,689** — wrong at both ends |
| "4–8% headroom" | **6.1–11.8%** — the note *overstates* the urgency |

And the motivating premise — that the call is dropping evidence today — is false: **0 of 170
live-book prompts overflow 8,192** (max 7,708), 0 of 55 contested, `truncated=0` on all 30
production requests sampled. The real case for raising it is a ~14s context-reload per contested
name plus a small tail, not evidence loss.

Also false: `F_config_findings_20260820.md` §6 still says GOOG's lattice holds exactly one cell.
It holds **2** (current_earnings +61.4, midcycle −62.7, contested). `HANDOFF:109` already recorded
the un-collapse; F was never updated.

---

## 3. STEP 3 — the "Basis judgment" contradiction has cost zero rejections

The contradiction is real: `RS2-Analyst.Modelfile:515-516` (rule 16, retired 2026-08-12) forbids the
line; `run_rs2.py:163-165`, `:696`, `:707` command it; `:1754-1755` extracts it for the auditor. A
**third live emitter** exists at `run_rs2.py:2095-2096`, gated only on `if val_block:`, which the
handoff does not mention and which reaches essentially every final assembly.

But the evidence offered for urgency does not hold:

- **All 6 `MISSING BASIS JUDGMENT` auditor charges predate the contradiction** (DELL/MU 08-08,
  MOV/WDC×2 08-09) — a period when rule 16 and FINAL_TASK agreed the line was mandatory. `e1900bc`
  retired rule 16 on 08-12 18:50. **The contradiction has produced zero measured charges.**
- "18.3% of reports print it, 63 carry both" reproduces **only case-insensitively**. Production's
  own extractor (`run_rs2.py:1755`, `re.search` with no flags) is case-**sensitive** and sees
  **14.7% corpus / 51 both**. The 18.3% denominator is also undocumented (81/443 post-08-12 dirs,
  not the corpus).
- The baked SYSTEM prohibition **works**: 0.0% before the clause existed → 77.4% with the clause and
  no rule 16 → 18.3% with both. A 4.2× reduction. Delete the clause because its precondition fires
  on ~8.6% of reports, not because the model ignores the system prompt.

"Four residual engine references" is also off-target: two of the three genuine ones are in
`rs2_data.py`, which the handoff's own grep targets would never have reached.

**Auditor rule 1b vs rule 3 is real and does cost rejections** — 24 phantom "missing section"
charges, all false against the full file, all on reports where `tier1_pass=True`.

---

## 4. STEP 4 — seeding: confirmed, with two traps

`grep -c "seed=" run_rs2.py` = 1 (the definition). Seven call sites confirmed complete: 305, 1077,
1783, 2156, 2406, 2418, 2430. Two traps that would have shipped silently:

- **`2418`/`2430` are byte-identical.** A `replace_all` edit gives both the same seed index and
  reintroduces exactly the sample collapse the change exists to prevent. Edit by line number.
- **Off-by-one at `:212`.** Any perturbation formula must send `call_seed`'s output *unmodified* at
  `attempt == 0`, or no published draw is regenerable from the recorded base.

The handoff's "Seeding IS deterministic — verified" is **true but scope-misleading**: the evidence
is the audit harness on `rs2-analyst-deep` at `num_ctx 65536`. It proves the Ollama+CUDA stack is
deterministic for a fixed (prompt, seed, num_ctx). It does not prove production's windows reproduce.

`api_chat()` takes no seed and sends none, and `api_chat.py:93` builds the request body *outside*
the retry loop — a fixed seed there would make every cloud retry a byte-identical re-request.
**Do not ship a cloud seed field that creates a false impression of determinism.**

---

## 5. STEP 5 — "free items" were not free

- **Post-brake fields to the auditor: CONFIRMED, and narrower than claimed.** True for 3 of 5 keys.
  `action` and `conviction` are reconcilable — `raw_action`/`raw_conviction` *are* in verdict.json
  and reach the auditor. `recommended_weight_pct`, `entry_timing`, `pullback_trigger` have no
  pre-brake counterpart at all. Direct measurement over 818 archived `audit.json` (288 tier-2
  failures): 65 violations cite conviction, 56 on braked verdicts, and **8 provably quote the
  pre-brake number the model actually wrote** — `GOOG_20260809` 12→9.5, `CIEN` 12.5→9.5,
  `BMY` 13.5→11.0, and `KNSA`, capped 12→9.5 and charged with **FABRICATION** for stating its own
  score. 17 of the 65 quote neither figure — those are the auditor catching real
  Section-5-vs-Section-12 inconsistency and must keep firing. **Fix by feeding pre-brake fields, not
  by weakening the check.**
- **"Open-ended auditor taxonomy": the prompt is already closed** (`:1654`, "passes only if there
  are NO violations from the list above"). Off-list records went 27.6% → 1.9% after `e1900bc`; 1 of
  157 current-era fails rests on an off-list class. And the `type` string is **not** inert
  telemetry — it is read by `_STAGE_TAINT` in the retry router (`:624`, `:666-668`) and echoed back
  to the model as retry guidance.
- **S3 stance bands: BARRED.** `_stance_from_gap` keys **only** on the gap, blind to fair value and
  MoS: **261/422 = 61.8%** of deterministic-era `fair` verdicts carry MoS ≤ −30% (GLBE −73.7% at
  gap −0.2). Hard-coding ±15/−7 into the prompt would assert "FAIR" to the model beside a header
  reading `MoS −73.7%` — making a mis-specification permanent by design. Whether `stance` should
  incorporate MoS at all is a design question, not a measurement gap.
- **"Be disciplined, not reflexively bearish": STOP.** Entered at root commit `103297f` with no
  message; zero mentions in any audit file, refinement report or handoff. No mechanical consumer
  (provable); no behavioural purpose (unprovable). Under §0 that is a stop, not a deletion.

---

## 6. THE PREMISE THAT FAILED — "steps 1–5 move no published number"

`HANDOFF_20260820.md:136-137` is **false**, and it is the most consequential error in the document.

`llm_overlay.json` is git-added, committed and **pushed** by `orchestrate.py:960-974` (Vercel
auto-redeploys; `:981` logs `::ERROR:: git push FAILED — SITE OVERLAY IS STALE`). Its payload
(`orchestrate.py:378-390`) carries **model-emitted** `action`, `conviction`, `stance_score`,
`thesis_break`, `changed_because`, `recommended_weight_pct`, plus brake-derived `entry_timing` and
`pullback_trigger`. Only `stance` is deterministic. **Every S3 / FINAL_TASK / auditor-pack edit
moves those on the next run.** Auditor-facing edits additionally route reports into
`refinal_retry`, which regenerates the final with a fresh LLM call and re-parses
`action`/`conviction`/`weight` into `verdict.json`.

The handoff also contradicts itself: line 137 places `regime_decide` in the "moves no published
number" block, while lines 143-145 call it "the one call that can move a published valuation".

**Consequence: steps 1–5 are not a free tranche.** They are prompt changes that move published,
pushed, model-emitted fields, and they fall under the 2026-08-09 RULE-CHANGE VALIDATION LADDER.

---

## 7. THE LADDER — and the tooling that does not exist

The ladder is live in two records (memory `rs2-orchestrator-ops`, `SESSION_HANDOFF_20260812.md:17-20`).
The 2026-08-09 **rule freeze has expired** (`cache/baseline_campaign.json` records
`completed = 2026-08-11 06:35`), so it bars nothing here. The **edit freeze still binds** and names
every file touched — currently satisfied only because sweeps are PAUSED.

**Corpus-replay tooling does not exist.** `tools/audit_202608/o2_replay_review.py` replays
`valuation_backbone.backbone(t)` old-vs-new — no FINAL.md, no auditor, no LLM. There is **no writer**
anywhere for `api_llm/_replay_set.json` or `_replay_results.json`. `run_rs2.py` has no
`--audit-only`; `--refinal` re-*generates*.

**And the replay population must be partitioned before it can attribute anything.** Of 818
`audit.json`: **463** were judged under the pre-`e1900bc` auditor prompt on qwen3.5-flash, **340**
under the current prompt on qwen3.5-flash, and **15** under the current prompt on the deployed
qwen3.8. **Only those 15 are like-for-like.** A null replay arm (current auditor, current model,
unchanged prompt) is required first to quantify how much of any diff is the 08-12 prompt rewrite and
the 08-19 model swap. Usable sentinels: 19, of which 3 were produced under the current auditor
prompt and **0** under the deployed model.

---

## 8. WHAT WAS APPLIED

Documentation only. No behavioural key changed; `ticker_timeout_min` left at 40, `stage_ctx` at
49152, `final_ctx` at 32768.

- `run_rs2.py:1575-1576` — deleted a stranded comment describing a basis-judgment presence check
  that does not exist. Verified: `grep` for any `basis_judgment` identifier returns nothing, and the
  block's only `rec()` calls are `final.section12_present`, `final.regime_judgment_telemetry`,
  `final.engine_verdict_slot`. Removed by `e1900bc`; the comment was left behind.
- `config.json` `_watchdog_note`, `_stage_ctx_note` — rewritten from the measurements above.
  Verified inert: no underscore-prefixed `CONFIG` key is read by any code path.

---

## 9. UNRELATED, FOUND IN PASSING — not touched

`.claude/worktrees/strange-perlman-3498fc` is a detached worktree at `b196163` (2026-08-14) holding
full copies of `run_rs2.py` (−111 lines vs live) and `RS2-Analyst.Modelfile` (+3). Any recursive
grep from the repo root returns both copies, so a `file:line` harvested that way can be wrong by up
to 111 lines. Given the 2026-08-09 finding that the deployment surface is the working tree, this is
worth a decision.
