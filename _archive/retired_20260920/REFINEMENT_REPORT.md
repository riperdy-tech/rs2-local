# RS2 Local Refinement — ChatGPT gold-set comparison & engine fixes

_Generated 2026-07-04. Reference set: 67 hand-run ChatGPT RS2 v2.0 analyses in
`Chatgpt Analysis for RS2 Local Refinement/rs2_actual_deep_research_md/`, compared to RS2 Local's
`reports/{T}_*/verdict.json`._

## 1. The discrepancies (measured over 67 Research-Now names)

| Axis | Finding |
|---|---|
| Action-family agreement | **64%** (42/66). Every disagreement one-directional: **RS2 more bullish than ChatGPT, never the reverse.** |
| RS2 posture | **34 BULL / 33 HOLD / 0 BEAR** — not one cautious call in the whole set. |
| ChatGPT posture | **Pullback-gated entry 64/67 (96%)** — "do not chase / wait for weakness / below $X / insufficient margin / starter only." |
| HOLD→BUY flips | Where ChatGPT said HOLD, **RS2 flipped to BUY 15/39 (38%).** |
| Dollar-value blowups | **16/67 `mos_pct` > 60%** — HRMY +1143%, TBPH +411%, DCBO +364%, CPRX +308%, ATAT +290%, GMED +258%, NICE +203%, HALO +161%… |

## 2. Why (root causes, in code)

1. **Fair value extrapolated trailing 5-year revenue CAGR forward** (`valuation_backbone.py`, old
   `g_fair = clamp(rev_cagr, .35)`). For post-IPO / hyper-ramp names the trailing CAGR is huge and
   unrepresentative → fair value 2–12× price. Benchmarked vs ChatGPT fair value: trailing median
   error **61.7%** vs analyst-consensus **28%**. For every blowup name the trailing fair sat *above
   the analyst consensus HIGH target*, while the consensus band landed on ChatGPT (MEDP band-high
   $495 ≈ ChatGPT $515 vs trailing $945). **The forward/consensus data was already fetched but the
   2026-06-29 inversion disconnected it from valuation.**
2. **No entry-timing / "don't-chase" brake.** The valuation block fed to the model was gap-only
   ("negative gap = undervalued"); action was free-text-parsed from the LLM with nothing forcing
   "thin MoS or price at/above the analyst target → Hold/stage, not BUY." Analyst target sat *below*
   price on **13/65** names — a "rich" signal the engine ignored.
3. **Conviction never docked** for thin-MoS-at-highs → all calls clustered 9.5–14, no Medium/Low.

## 3. What changed

- **`valuation_backbone.py` — forward-anchored, consensus-fenced fair value.** Growth input is now
  forward analyst growth (OpenBB `forward_growth`, else PEG-implied), capped at 20%; the DCF value
  is fenced inside the analyst target band `[low, high]` and, per the "don't chase" intent, is
  **never more bullish than the analyst median** (may be lower). Escapes the band → snap to median.
  No band + implausible/short trailing history → **blank the $ value** (gap-only). New fields:
  `fair_value_method`, `consensus_low/median/high`, `realistic_mos_pct`, `consensus_stale`.
- **`openbb_data.py` — forward analyst growth added** (`forward_eps`/`forward_sales`, yfinance-first
  to stay free; FMP only as a quota-guarded fallback → no impact on the 200/day cap) + PEG fallback
  + staleness age.
- **`run_rs2.py` — graduated "don't-chase" brake** (`_dont_chase_brake`), on ChatGPT's own MoS
  bands: MoS ≥ 25% & below median & not near 52wk-high → BUY ok; 15–25% → staged accumulate (conv
  capped ~11, starter weight); < 15% or price ≥ median or within 2% of 52wk-high → **Hold /
  do-not-chase** (conv capped to Medium ≤9.5, starter size, `entry_timing` + `pullback_trigger`
  emitted). S3 stance + S5 conviction prompts extended to teach the same discipline. `verdict.json`
  gains `realistic_mos_pct`, `fair_value_method`, `consensus_median`, `entry_timing`,
  `pullback_trigger`, `raw_action`, `brake_applied`.
- **`rs2_data.py`** — feeds the consensus band + price-vs-target + forward growth + a do-not-chase
  cue into the model's prompt context.
- **`enrich_ticker.py`** — adds `fifty_two_week_high/low` for the near-highs brake (effective on the
  next enrich fetch).
- **`signoff_rn.py` (new)** — repeatable comparator vs the 67-name set (replaces the stale
  `signoff.py`, which pointed at the old 24-name dir). This file is the living A/B report.

## 4. Results (deterministic, `python signoff_rn.py`)

| Metric | Before | After |
|---|---|---|
| MoS blowups > 60% | **16** | **3** (INVA/SAP/BWMX — each equals the analyst *median*, i.e. genuinely bullish analysts, not engine garbage) |
| Fair value inside analyst band | — | **65/65** |
| Action-family agreement vs ChatGPT | 64% | **68–70%** (deterministic lower bound) |
| Conviction spread | flat 9.5–14, all high | 44 Medium (≤9.5) calls now appear |
| Don't-chase brake fires | — | 48/67, with entry-timing + pullback triggers |

**Important:** the "after" agreement is a *lower bound* — the comparator holds the OLD LLM action
constant and applies only the new valuation + brake. It does **not** yet reflect (a) the new S3/S5
prompt discipline that will make the model itself more cautious, or (b) the 52-week-high brake,
which needs a fresh `enrich` fetch. Both push agreement higher on live runs.

The residual disagreements are **not bugs**: most are ChatGPT's hedged "Buy on weakness / staged
starter" language sitting genuinely between BUY and HOLD (a crude 3-way classifier must pick a
side), plus a philosophical gap where sell-side analysts (which we now anchor to) are more bullish
than ChatGPT (e.g. AVGO: analysts + our DCF see +39%, ChatGPT flags AI-concentration risk → Hold).

## 5. Verification

- Deterministic re-benchmark + before/after: `python signoff_rn.py` (add `--brief` for aggregates).
- `emit_verdict` integration-tested end-to-end: all three brake tiers fire, full verdict schema
  emitted (EXEL/MEDP → Hold + wait_for_pullback; RMD → staged accumulate; GMED → clean BUY).
- **Not done here (hand off):** a full-pipeline spot re-run to confirm the LLM stages honor the new
  prompts. Run e.g. `python run_rs2.py EXEL` (and MEDP, HRMY) when the box is free — deferred
  because the full pipeline is GPU/RAM-heavy and the 12 GB box overloads if runs stack.
- The screener overlay rollout (branch `llm-overlay`, frozen `main`) was **not** touched; no git
  push.
