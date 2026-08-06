# RS2 Local — session handoff (2026-08-05 → 2026-08-06)

Self-contained summary for a follow-up repair session. Nothing here is committed;
all changes are working-tree only.

Repo: `C:\Users\riper\Downloads\RS2 Local` (branch `main`, was clean at session start)
Sibling repo touched by findings: `C:\Users\riper\Downloads\Stock Screener\Stock Screener`

---

## 0. What started this

User swapped the analyst base model to a leaner text-only build to cut VRAM pressure.
That was done and verified — but auditing the result surfaced a far larger problem:
**most RS2 verdicts were resting on fabricated research**, and the tier system that
consumes them was keying on an unstable field.

---

## 1. Model swap (DONE, verified)

`rs2-analyst` rebuilt on `mdq100/qwen3.5-flash:35b` (was `qwen3.6:35b-a3b`).
`config.json` unchanged — it points at the `rs2-analyst` tag.

Verified via `/api/show` that the two bases are **identical on the text path**:
`block_count 40`, `attention.head_count 16`, `expert_count 256`, `expert_used_count 8`,
`context_length 262144`. The only delta is qwen3.6's `vision.block_count: 27` encoder,
which RS2 never calls. That encoder is the whole 36.0B → 34.7B parameter drop.

Measured resident footprint on the 24,576 MiB card (nvidia-smi, 100% GPU both):

| ctx | qwen3.6 | flash | free after |
|---|---|---|---|
| 24576 (`stage_ctx`) | 23,873 MiB | 21,391 MiB | 703 → **3,185 MiB** |
| 32768 (`final_ctx`) | 24,041 MiB | 21,559 MiB | 535 → **3,017 MiB** |

~2.5 GB recovered (not the ~1 GB the `ollama list` sizes imply). This pulls final
assembly out of the sub-1GB margin regime documented in `RS2-Research.Modelfile` as
fatal. Confirmed 21,403 MiB / 3,173 MiB free during a live run.

Revert is one line: set `FROM qwen3.6:35b-a3b` in `RS2-Analyst.Modelfile`, re-run
`ollama create rs2-analyst -f RS2-Analyst.Modelfile`. Old weights still on disk.

---

## 2. THE CORE BUG — fabricated research shipped as real

### Root cause
`deep_research.py` appended the model's summary to the brief **before** extracting
sources. With no usable search results, LDR still returns fluent, `[1][2]`-annotated
prose from model recall — and it got written to disk, cached 7 days, analyzed,
published, and git-pushed automatically.

### Evidence it was fabrication, not thin research
POWL's brief asserted **debt/equity 4.2 and "debt restructuring"** for a company with
**$1.66M total debt vs $450.7M cash** (per the engine's own
`financials/POWL.json`). It also invented a plant fire ($120M loss), a CEO
resignation, a $500M chemical-spill lawsuit, an activist investor "GreenFuture
Capital", and called POWL a "specialty metals" company (it makes electrical
switchgear). Those fabrications propagated into the verdict's red-team section.

### Why nothing caught it
- **Size is ANTI-correlated**: fabricated briefs median **25.3KB** vs healthy **15.9KB**.
  A big brief is *more* suspect, not less.
- `ops.infra_error()` passes them — fluent prose, not error text.
- Only a `^- https?://` citation test catches it (landed same-day in commit f308857).

### Scale (log-mined from `reports/_orchestrate.log`)
- **searxng: 2,676 / 2,676 subqueries returned ZERO sources — 100%**
- tavily: 34 / 343 (9%)
- The searxng container reported "Up" while returning nothing usable to LDR.
  It had only been genuinely healthy for ~5h at audit time.

### Blast radius (corpus audit, 1,401 bundles)
| class | all bundles | live (newest per ticker, n=256) |
|---|---|---|
| HEALTHY (cited) | 193 (13%) | 103 (40%) |
| FABRICATED | 713 (50%) | 111 (43%) |
| INFRA (OOM stub) | 300 (21%) | 19 (7%) |
| MISSING | 195 (13%) | 23 (8%) |

**153 of 256 live verdicts (60%) rest on ungrounded research.** They are published to
the screener site and git-pushed.

### Fixes applied to `deep_research.py`
1. **Zero-source guard** — sources resolved *before* any prose is committed; a section
   with no sources is discarded and recorded as a failure, so the brief is never
   written (`ResearchInfraError`, exit 3, Telegram).
2. **Cache rejection** — the 7-day cache now rejects uncited briefs, not just
   infra-error text. Without this, every affected ticker would burn 3 retries × ~10 min
   forever with no self-heal (130 briefs uncited, 73 inside the window).

### Validation
- Monkeypatched guard tests: **8/8 pass**, including rejection paths
  (`scratchpad/test_guards.py`).
- Live re-research of POWL: **43 real sources** across 4 topics, fabrications gone
  (0/8 markers), correctly identifies electrical equipment, Eaton/Hubbell/Schneider,
  and cites 30.2% gross margins matching the screener's `TTM_Gross_Margin_%` of 30.10.

---

## 3. Verdict homogenization — NOT caused by research

68% of live verdicts were the same action. **Research quality is not the cause:**

| brief class | n | top-action share |
|---|---|---|
| HEALTHY (cited) | 103 | **77%** "hold stage in on" |
| FABRICATED | 111 | 74% |

Cited briefs are marginally *worse*. Conviction spread nearly identical
(8.57±1.23 vs 8.36±1.09). This was measured from existing data and **prevented a
~32-hour re-run that would not have fixed verdict quality.**

### Actual cause — the prompt
- `run_rs2.py:113` (S5 stage prompt): *"'Valuation attractiveness' must DOCK for a thin
  realistic MoS (<15%) … is a **MEDIUM (7-9)**"*. That condition fires for **77%** of
  the book; **76%** of verdicts land in 7-9. Near-perfect 1:1.
- `FINAL_TASK` stance rubric literally supplies the words: *"4: ACCUMULATE ON DIPS /
  stage in (constructive, prefer weakness); 3: HOLD"*.

### Why it fires so often
`fair_value_method = consensus_snap` for **198/255 (78%)** of live names → fair value
≈ analyst consensus → sits near price → MoS thin → DOCK rule fires.

**STILL OPEN.** No fix applied. This is the main remaining quality issue.

---

## 4. Result-measurement / display bugs

Audited `llm_overlay.json` (173 names) and the consumer
`Stock Screener/scripts/score_factors.py::apply_llm_overlay`.

### BUG F (most serious) — the RN tier is decided by a coin flip
`score_factors.py:209`: `bearish = any(w in act for w in BEAR) or stance == "overvalued"`,
and bearish → demoted, excluded from the LLM set.

But `stance` was the model's free-text `valuation_stance`, **not computed**. Two
consecutive POWL runs on byte-identical inputs returned:

- Run A: gap 28.5pts, achievable **low** → stance **overvalued**
- Run B: gap 28.5pts, achievable **medium** → stance **fair**

**55 of 173 live names (32%)** were demoted *solely* because of that field. MPWR
(MoS 21.5, conv 11.0) and TSM (MoS 15.4, conv 11.0) swing all the way from
`demoted` → `research_now` depending on which way the coin lands.

**FIXED** — see §5.

### BUG A — action string truncated (FIXED)
Old regex `([A-Za-z][A-Za-z /&\-]{2,45})` excluded digits and `$`, so it stopped at
the price level. 5 live names published e.g. `"Hold / Stage-in on weakness below"` —
trigger price gone. Unanchored, it also matched prose: **FIX** shipped an action of
`"will be severe due to the cyclical nature of t"`.

### BUG B — two contradictory value signals displayed side by side (OPEN)
**66/173** names have `expectations_gap_pts` and `realistic_mos_pct` pointing opposite
ways, with no reconciliation. Gap>0 = rich on fundamentals; MoS>0 = cheap vs consensus.

### BUG C — conviction scale is `/15` but published bare (OPEN)
94% of values are ≤10, so it's indistinguishable from a `/10` scale. No `scale` field
is published anywhere. Any consumer assuming /10 overstates every conviction.

### BUG D — `stance` (label) vs `stance_score` (1-5) are independent (OPEN)
They can contradict: 'overvalued' appears with stance_score 4, 'undervalued' with 3.

### BUG E — method label misrepresents the value source (OPEN)
**138/173** publish `method: reverse_dcf` while `fair_value_method: consensus_snap`.
The displayed "method" is not where the fair value came from.

### BUG G — investigated, NOT a real bug
Predicted substring false-positives in the BEAR/BULL keyword lists
(`SHORT` inside another word, etc). **Zero** occurrences in live data.

---

## 5. Fixes applied this session (all working-tree, uncommitted)

### `deep_research.py`
- zero-source guard (§2)
- cache rejects uncited briefs (§2)
- added `import re`

### `run_rs2.py`
- **`_stance_from_gap()`** — stance now DETERMINISTIC from the computed
  `expectations_gap_pts`. Cuts: `>= +15` overvalued, `<= -7` undervalued, else fair.
  Model's opinion preserved as `stance_model` (telemetry, never a gate).
  Applied in both valuation paths **and** in `emit_verdict` (single source of truth, so
  `repatch_verdicts.py` picks it up too).

  Thresholds calibrated against 241 live verdicts (quartiles of the computed gap under
  each model stance):
  ```
  undervalued  p25 -33.4  median -11.1  p75  -7.7
  fair         p25  -2.6  median  +4.0  p75  +8.9
  overvalued   p25 +14.7  median +20.4  p75 +26.8
  ```
  `+15` reproduces today's classification volume (72 vs the model's 76) while removing
  the instability. **User chose this cut explicitly** over +12 (88 names) and +20 (50).

- **Expectations override in `_dont_chase_brake()`** — tier-1 "genuine bargain" is
  blocked when `expectations_gap_pts >= 15`. Cheap-vs-consensus is not
  cheap-vs-fundamentals. Keyed on the computed gap, never on `stance`.
  Tier-3 conviction cap now also applies to rich names (previously a fat MoS protected
  conviction, so a name could land on "do not chase" while carrying 12/15).

- **Action parser** — requires an `Action:` label and takes the rest of the line;
  strips markdown, `[Estimate]` tags, and trailing `| Changed-Because:` fields.
  Recovered trigger prices on all 5 truncated names; FIX now returns `None` instead of
  prose. `action=None` went 7 → 13 corpus-wide (the extra 6 genuinely have no parseable
  action line, where `None` is the honest answer); 0 dangling prepositions remain.

- **Weight parser** — now accepts ranges (`5-7%`, `5 to 7%`, en/em dash), collapsing to
  the **midpoint**. Was silently returning `None` on every range: 203/1390 bundles,
  24 live. **107 previously-null weights recovered** on the existing corpus.
  Tests 9/9.

### `research_health.py` (NEW)
Aggregate health check for the search leg — the seatbelt the system lacked. The
`0 sources` signal was in the logs 2,710 times with nothing summing it.
```
python research_health.py                 # whole log + brief corpus
python research_health.py --since-hours 6 # this run only
python research_health.py --alert         # Telegram on breach
```
Alerts when an engine's zero-source rate ≥25% (n≥8) or ≥5 uncited briefs written in 24h.
Exits 1 on breach for scripting. Current output correctly flags searxng 100%.

### `RS2-Analyst.Modelfile`
New base + measured VRAM figures + revert instructions in the header.

---

## 6. POWL quarantined

Every POWL bundle in history (11/11) was ungrounded — zero sources, ever.
Moved (not deleted, reversible) to `_quarantine/POWL_20260805_234723/`:
- the fabricated cached brief
- 11 local report bundles
- **7 published site bundles** from `Stock Screener/public/data/rs2/POWL/`
- its `index.json` entry (count 256 → 255)
- its `cache/analysis_state.json` row (so it re-queues as due)

POWL has since been re-researched clean (43 sources) and re-analyzed 3×.

---

## 7. Pilot results (POWL, controlled)

All on the same cited 43-source brief and the same analyst model:

| run | stance | action | conv | weight | brake | entry |
|---|---|---|---|---|---|---|
| A `022630` | overvalued | ACCUMULATE ON DIPS | 12.0 | 5.0 | False | buy |
| B `023533` | **fair** | ACCUMULATE ON DIPS / STAGE IN | 12.0 | 6.0 | False | buy |
| C `030605` (post-fix) | overvalued | **Hold / accumulate on weakness (do not chase)** | **9.5** | 3.0 | **True** | stage |

- A vs B = the variance measurement. The *decision* was stable (`stance_score` 4,
  conviction 12.0, entry buy, ACCUMULATE family all identical) — only the `stance`
  label flipped. That single unstable label is what gates the RN tier.
- C = post-fix. Brake fires, the unbraked conviction-12 BUY on a name the engine's own
  DCF calls rich becomes a do-not-chase at 9.5. Stance now deterministic.
- All three passed sanity — the first POWL runs ever to do so.

---

## 8. Open items for the repair session

1. **Homogenization / DOCK rule (§3)** — the biggest remaining quality issue. 77% of
   the book funnelled into conviction 7-9 and one action phrase by the S5 prompt and
   the FINAL stance rubric. Needs prompt redesign, not a re-run.
2. **`consensus_snap` anchoring** — 78% of fair values are the analyst median, which is
   the upstream cause of both the thin-MoS DOCK cascade and BUG B. Arguably the single
   highest-leverage structural fix.
3. **BUG B / C / D / E** — display-layer integrity (§4).
4. **Tavily → SearXNG failover** — three gaps, none fixed:
   - `preflight()` runs once with whichever engine `pick_tool()` picks at that moment
     and returns immediately if it isn't searxng — so a run starting on Tavily never
     health-checks the engine it may fall back to mid-ticker.
   - Fallback is **quota-based only, never failure-based**. A Tavily 429/500 records a
     failure and voids the whole brief; the topic is never retried on SearXNG.
   - Quota is estimated (flat `tavily_calls_per_query_est` per topic), not measured.
   - **Fires on its own ~Sept 1** when the monthly cap resets to 900 (~37 tickers of
     Tavily, then depletion mid-queue). Tavily is at **6 calls** now.
5. **Re-run scope** — `repatch_verdicts.py` replays `emit_verdict` over existing
   FINAL.md **without the LLM**, so the stance/brake/action/weight fixes apply in
   minutes to the ~103 names with healthy briefs. The **153 ungrounded names need a
   full LLM re-run** regardless, because their FINAL.md text rests on hallucinated
   facts. Run `research_health.py` alongside it as the seatbelt.
6. **153 ungrounded live verdicts are still published** and being served. Not yet
   quarantined — user was asked, decision pending.
7. **Scheduled task `RS2-Orchestrator`** (daily 08:00 + at logon) is still `Ready` and
   will run against all of the above.

## Test assets (scratchpad, not in repo)
`test_guards.py` (8 assertions), `test_brake_stance.py` (19), `audit_corpus.py`,
`audit_verdicts.py`, `audit_display.py`, `audit_rn_tier.py`, `vram_probe.py`,
`quarantine_powl.py`. Worth promoting the two test files into the repo.
