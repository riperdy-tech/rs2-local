# RS2 SESSION HANDOFF — 2026-08-12 (end of session)

Read this fully before touching anything. It exists so the next session does not re-derive what
is already measured, does not repeat mistakes that already cost hours, and knows exactly where to
resume.

---

## 0. HOW WE WORK (non-negotiable — these are the operator's standing rules)

`CLAUDE.md` Section 0 governs everything: **no assumptions, no skipping, never build to fit the
available data, gaps are STOP conditions.** Beyond it, these were earned the hard way this week:

1. **Measure before designing.** Every constant must be derived from this repo's data or
   disclosed as unproven. Two invented constants (`FWD_GROWTH_CEIL`, terminal/discount frame)
   caused real distortion; the fix was measurement, not argument.
2. **Validation ladder before any rule/prompt/model change ships:** replay against ALL
   previously-passing artifacts (zero new rejections) AND all previously-failing (zero new
   passes); hand-adjudicate sentinels; ≥2 fresh runs including one hard name. **n=1 certification
   of a stochastic system is forbidden.**
3. **Sentinels must be unambiguous.** An ambiguous case sampled once is not evidence — the
   verifier flips on judgment-boundary cases (measured).
4. **Edit freeze during batches.** Engine files (`run_rs2.py`, `rs2_data.py`,
   `valuation_backbone.py`, `orchestrate.py`, `RS2-Analyst.Modelfile`, `config.json`) are frozen
   while any batch runs. Each ticker is a fresh subprocess reading current files, so a mid-run
   edit silently splits one experiment into two.
5. **Launch batches ONLY via `python tools/run_batch.py`** (see §5). Never call `orchestrate.py`
   directly.
6. **Verify state, never trust the report of it.** Check the lock before launching, check the
   file actually contains the edit, check the receipt before believing a pass rate. Multiple
   hours were lost to a silently-failed edit script and to lock collisions misread as failures.
7. **When the auditor flags a fabrication, CHECK THE DATUM first** against `enrich/{T}.json`,
   `_fed_data.md` and the engine data. Two "fixes" were made on the auditor's word and both were
   wrong — the figures were real.
8. **One change, then one test.** Bundling fixes made it impossible to attribute cause.
9. **Small batches.** 5 names to validate, ~12 per chunk after. A 69-name batch on unproven
   machinery costs a night before the first signal.
10. **Nothing publishes to the live site without the operator's approval** (`--no-push` is the
    default posture while hardening).

---

## 1. WHERE THINGS STAND RIGHT NOW

- **Engine PAUSED** (`cache/PAUSED` present). No lock, GPU idle, nothing running.
- **Baseline COMPLETE: 172/172** audit-clean verdicts, live on the site since 2026-08-11.
- **Live site (`llm_overlay.json`, 178 names) is what `equal_llm` trades on.** As of tonight it
  carries the 172 baseline verdicts **plus 4 lattice-era verdicts** that a stray bare
  `orchestrate.py` published: ACTG, **AMZN (+16.7%, lattice-corrected, audit-clean)**, ANET, BMY.
  CHEF was reverted to its last audited verdict after being published unaudited (gate now fixed).
- **All work committed and pushed** — RS2 repo through `0044326c24`-era commits; screener repo
  likewise.

---

## 2. WHAT WAS BUILT THIS SESSION (all committed, all measured)

### 2.1 The problem we set out to solve
The operator observed that many names carried extreme negative margins of safety that no market
participant agreed with (e.g. AMZN at −77.5%). Investigation confirmed the engine was distorted —
but **not** in the way first assumed.

### 2.2 Measured findings (do NOT re-derive these)
- **Discount rate is NOT the problem.** Implied cost of equity backed out of our own book
  (Damodaran method, RF 4.65% from FRED DGS10) = **11.8%**; engine uses ~10%. Our rate is
  slightly *generous*. An earlier claim that this was the primary error was **retracted**.
- **Base definition IS the structural depressor.** The engine capitalized only **53%** of the
  book's actual earnings ($642B base vs $1,212B TTM net income) because owner earnings subtract
  the *whole* capex line. For 21 names it capitalized under half (AMZN $37B vs $135B — $173B of
  capex is AI build-out, not maintenance).
- **Growth persistence, measured over 3,115 ticker-years** (replaces the invented 20% cap):
  delivered 15–25% → realized median 9.4% forward 5y CAGR (p75 16.0); 25–40% → 12.1 (21.4);
  40–70% → 14.5 (27.3); >70% → **16.5** (35.5). High growth decays hard.
- **Cyclicality discriminator is PRIOR DECLINES, not level.** "TTM vs own median" is worthless
  (META 1.8× with zero down years vs STX 1.0× with three). Live clusters: none
  (META/AMZN/VRT/PTC/HQY/NHC), mild −14/−15% (KO, LRCX), deep −37/−50% (MU, STX, WDC). The 25%
  cut sits in the empty gap.
- **Verdict grading (first ever run, 600 verdict-horizons, 230 names, 30d vs IWM):** the
  deterministic stance ranks realized returns **monotonically** — undervalued +3.7% excess /
  fair +1.2% / overvalued −2.6%, beat rates 63/56/40%. The model's disposition adds power inside
  each bucket (undervalued+BULL +8.8%, 76% beat). Conviction Spearman **+0.34**. Entry timing is
  the sharpest field (buy +6.4%/73% vs wait_for_pullback −2.7%/40%). Brake ≈ neutral — leave it.
- **`equal_llm` does NOT size on `recommended_weight_pct`** (it equal-weights) but DOES select
  membership and F-04 exits on stance/action/conviction from the overlay. Verdict quality reaches
  real money through the *selection* channel.
- **~3 microstructure figures per report were "fabricated"** — they were REAL, from
  `enrich/{T}.json`. See §3.1.

### 2.3 Components built
- **Valuation lattice** (`valuation_backbone.base_lattice`): prices every defensible base
  (current earnings / owner earnings / mid-cycle) against three yardsticks (trailing / forward /
  delivered), flags `contested` when MoS spans ≥30pts. **69 of 172 names are contested.**
- **`persistence_growth()`** — the measured curve above.
- **`apply_basis(bb, cell)`** — rewrites the backbone onto an endorsed cell, preserving
  `*_engine_default` for audit.
- **Regime decision** (`run_rs2.regime_decide`): dedicated focused call, `think=False`
  (mandatory — thinking ON returns empty content), **3 samples, majority rule**, no majority →
  engine default stands. Runs **before stage 1** so the whole pipeline is consistent.
- **Quarterly trajectory** (`fundamentals_quarterly.json`, 3,763 tickers, built by the screener
  extractor): single-quarter revenue/NI with YoY, from 10-Qs. The regime evidence.
- **Outcome feedback** (`outcome_feedback.py`): the engine's own graded track record injected
  into every analysis context, situation-matched, with sample sizes and a regime caveat.
- **`tools/run_batch.py`** — the batch guard (§5).
- **`tools/`** — `growth_persistence.py`, `implied_erp.py`, `base_vs_rate.py` (every number
  above is re-derivable).

---

## 3. BUGS FIXED THIS SESSION (do not reintroduce)

### 3.1 Auditor blind spots — THE dominant failure cause
The tier-2 verifier reads the data context as **head(8K) + tail(12K)**. Blocks in the elided
middle were invisible, so it charged REAL sourced figures as fabrications:
- behavioral/microstructure block at ~offset 8,538 (short interest, institutional %, insider %,
  put-call, 52wk) — BMY's "fabricated 84.81% institutional" is verbatim our enrich value;
- macro block at ~offset 7,443 (DXY, Treasury yields, credit spreads).

**Fixes:** both blocks are now extracted deterministically into the evidence pack, AND the rule
changed at the root — **a windowed reader can prove CONTRADICTION but never ABSENCE**, so the
verifier may only flag figures that contradict something visible. This is the third instance of
this family (after Section-12 phantom truncation and WDC's basis judgment).

### 3.2 Consistency bugs between components (five, all mechanical)
- Basis resolved *after* the stages → the model was shown one stance, wrote it, and the verdict
  changed underneath → failed the slot check for obeying instructions. **Fixed: resolve first.**
- Tier-1 recomputed the backbone without the resolution → guaranteed "drift" (BMY 9.28 vs 10.34).
  **Fixed: replay `regime_decision.json` before diffing.**
- **Router retries lost the resolved basis** → contested names could NEVER heal: the retry reused
  the source's stages/header but rebuilt a default backbone, producing a self-contradictory
  report by construction. This is why AMZN/BMY burned entire budgets. **Fixed: record copied +
  basis replayed.**
- Rules 16 and 19 both demanded a basis sentence → they could contradict each other inside one
  report (BMY). **Rule 16 retired everywhere.**
- Publish gate treated "no `audit.json`" as pre-audit-era → a run killed mid-audit published
  unaudited (CHEF). **Fixed: `AUDIT_ERA` timestamp check in `orchestrate.audit_clean`.**

### 3.3 Other
- `ollama_chat` RAISES on empty content, so the inline stage-retry never saw it and the ticker
  crashed (exit 1). **Fixed: catch and retry the stage with `think=False`.**
- **Prompts are instructions, not documentation.** An 8-line rule containing rationale, dates and
  example fabricated figures caused empty generations 1-in-3; the 2-line version, 0-in-4.
  Rationale belongs in code comments.

---

## 4. WHERE TO RESUME (the operator chose: KEEP HARDENING)

**Goal:** get a guarded 5-name test to ≥4/5 clean, then re-run the 69 contested names in ~12-name
chunks, audit, and publish with approval.

**Last measured state:** `reports/_cleantest5.log` — the router fix fired correctly 5×, BMY passed
clean, AMZN/ACTG/ANET published clean earlier in the session. Remaining failures were *ordinary
model slips*, not structural traps:
- **ANET**: `SIZING INCOHERENCE` (Kelly in §6.5 vs final weight in §12 without stated
  reconciliation) and once cited `$178.19` — **GILD's fair value from another report**.
- **CHEF**: `INTERNAL CONTRADICTION` on one attempt.

**Suggested next steps, in order:**
1. Run `python tools/run_batch.py --tickers "ACTG,AMZN,ANET,BMY,CHEF" --log reports/_t1.log
   --limit 12 --pause-after`, check the **receipt** (`{log}.receipt.json` must say `CLEAN`), then
   the pass rate. This is the first test with every known structural trap fixed.
2. If ≥4/5: proceed to contested names in 12-name chunks (list: recompute via
   `lattice.contested`; 69 names as of this session).
3. If <4/5: the remaining classes are sizing coherence and cross-report contamination. Consider
   whether rule 17's sizing-coherence check is worth its failure rate now that the ledger shows
   `recommended_weight_pct` is not used for sizing by `equal_llm`.
4. **Fallback if hardening stalls (operator is aware of this option):** ship the lattice as
   **disclosure-only** — the card shows the range and reasoning, the published MoS stays on the
   engine default. One-line change, keeps most of the value, no fragility.

**Expected retry rate:** the baseline ran 172 names at **2.15 attempts/name** with this same model
and auditor. Tonight's high counts were names trapped in unwinnable loops (§3.2), not genuine
quality failures. If the rate does not return toward ~2, that is a signal something structural
remains — investigate rather than accept.

---

## 5. OPERATIONAL FACTS

- **Launch:** `python tools/run_batch.py --tickers "A,B,C" --log reports/_x.log [--limit N]
  [--pause-after]`. Refuses to start against a live lock (names the PID) and writes
  `{log}.receipt.json` with `CLEAN` / `CONTAMINATED — engine files changed mid-run`.
  **Never trust a pass rate without reading the receipt.**
- **Pause:** `cache/PAUSED` (any content) stops sweeps at the next ticker boundary and makes the
  scheduled task exit. Direct `run_rs2.py <T>` runs are deliberately NOT blocked.
- **Danger:** a bare `orchestrate.py` (no `--no-push`) **pushes to the live site**. That is how
  today's test verdicts went live. Keep `PAUSED` in place whenever the engine is mid-hardening.
- **Model:** `rs2-analyst` on `mdq100/qwen3.5-flash:35b`, 22GB, 100% GPU, stage ctx 24576 / final
  32768, ~29 tok/s visible output, ~9–10 min per full ticker.
- **Model rebuild:** `ollama create rs2-analyst -f RS2-Analyst.Modelfile`. The FIRST run after a
  rebuild reliably flakes with empty content — warm it, then unload, before a real run.
- **Data provenance:** the CLOUD rebuilds fundamentals on a schedule with a FRESH companyfacts
  fetch and already runs whatever extractor code was pushed. **Never commit a local rebuild
  unless the local `companyfacts.zip` is verifiably newer** — doing so regressed 5 tickers
  (LRCX lost FY2026).
- **Key files:** `cache/baseline_campaign.json` (172 done), `cache/verifier_variance.jsonl`,
  `cache/label_history.jsonl`, `public/data/rs2_verdict_log.jsonl` (1,793 rows),
  `public/data/rs2_verdict_outcomes.json` (grading), `enrich/{T}.json` (microstructure).
- **Telegram:** structured outcome feed per attempt + `/status` bot
  (`python telegram_status_bot.py`, replies only to the operator's chat).

---

## 6. OPEN ITEMS (measured, not yet done)

- **Foreign-filer ingestion** (TSM, FMX, SAP, BWMX): 20-F filers, no 10-Qs → no TTM. TSM's base
  is FY2024 and its verdict is unreliable-pending-data. Needs FX-aware ingestion. TSM is a
  top-ranked RN name, so this has real cost.
- **Adjacent-walk normaliser**: 626 residual ~1000× scale transitions corpus-wide, **0 feeding a
  live base_cf**. False-positive hazard documented (NVDA/AMZN/AMD/CRM real events).
- **Retro-grading the lattice**: the ledger now records `regime_basis`, so basis CHOICES can be
  graded against realized returns once horizons mature (6,567 pending vs 600 graded).
- **`data_health.py --gate-live`** is wired into orchestrate startup (exit 10). Currently CLEAR.
- Two non-tracked corpus edge cases: DUKR (short-series scale), QXO (transformation
  false-positive).
