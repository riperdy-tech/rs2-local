# The rebuild's AI layer: Muse pass 1 (price-blind) and pass 2 (red team)

Written by the coordinator (Opus 5.5, main session) on 2026-10-07. This implements `SPEC_rebuild.md` section 5, under
Addenda A–D. **No GPU is used until gate 1 (the code engines) has passed.** The code, the prompts and the mock-model
tests are built now.

## 0. The coordinator's rulings that shape this layer
- **Core inputs are the company's filings only, live and replay alike.**
  - No consensus (Addendum C 5).
  - **No live web research in the core** either. Same reason: the replay cannot have it without leaking the future,
    and a core that differs between live and replay is not the system that was tested.
  - Research and consensus come back later as separate, measured experiments ("core + research"). This extends the
    reviewers' consensus argument; it is the coordinator's ruling, not theirs.
- **Muse reads short, focused prompts, not one 50,000-character pack** (Gemini, adopted). Each prompt gets only the
  sections it needs.
- **Muse places the company inside population distributions** (ChatGPT, adopted). It does not invent numbers. Python
  maps positions to values.
- **Reasoning strength:** xhigh, as in AT10b (the "Reasoning strength: xhigh" system prefix), and recorded per run.
  Lower settings are a later, measured experiment.

## 1. The pack, version 2 (built only from the point-in-time layer at T)

The header says only "Analysis date: <T>", the company name and ticker as of T, the family and the industry. Nothing
else about dates or data availability.

| Section | Content | Used by |
|---|---|---|
| F | Filed financial history, up to 10 fiscal years known at T; each cell's provenance (form, accession, filed) available as an appendix | all prompts |
| Q | The latest quarters known at T | P1, P2 |
| D | Primary documents filed before T, verbatim excerpts: the latest annual report's business description, MD&A outlook and segment note, and the latest earnings release (`sec_primary`, bounded by the 16:00 ET acceptance rule) | all prompts |
| S | Company state: size, growth delivered, margin and its deviation from the 8-year median, cyclicality score, return on capital | all prompts |
| R | Population priors at T for each judgment input: P5 to P95, conditioned on S, plus the company's mechanical baseline. Example: growth year 1 by the trailing 3-year CAGR, margin held | the prompt for that input |

**Never present in pass 1:** price, market cap, returns, targets, consensus, any valuation, news, or the word "replay".

## 2. Pass 1, price-blind (five calls)

Each call returns JSON only, validated by code. The models used are the operating family's inputs
`g1, growth_persistence, margin_target, margin_retention, ronic, g_terminal`. The financial family uses `rote_target`
and `rote_retention` instead of the margin and RONIC inputs.

**P1, revenue runway.**
- **Sections:** F, Q, D, S, and R for `g1` and `growth_persistence`.
- **Question:** where in each distribution this company sits for its year-1 growth and how long its growth persists,
  and why.
- **Output, per input:**
  - `{percentile: 5..95, width: narrow|normal|wide, reasons, citations:[{section, quote}]}`;
  - plus `bull_case` and `bear_case`, one sentence each, each with a citation.

**P2, margins.** Same shape, for `margin_target` and `margin_retention`. It must say whether today's margin is
cyclical, structural or a one-off, citing D.

**P3, reinvestment and returns.** Same shape, for `ronic`. Question: what one dollar of growth costs this company, from
its record and its business model.

**P4, the long run and the risks.** Same shape, for `g_terminal`. It also lists the three most material risks, each
with a citation and the input it would move.

**P5, synthesis.**
- **Input:** the P1–P4 outputs, sections S and R.
- **Coherence check:** for example, top-decile growth with top-decile margin and top-decile returns needs a stated
  moat with evidence; a shrinking company with an expanding margin needs a cause.
- **Output:** the final position and width per input, and the changes from P1–P4 with reasons.

**Code checks on every output.** A failed check gives one retry with the checker's message, then the input is marked
`unanchored` and falls back to the prior's P50 with width wide, stamped.
1. **Quotes:** every quote must be found in the cited section. The pack's own normalization rules apply (the
   revision-21 `crux_check` rules).
2. **Hard evidence:**
   - a position outside P10..P90 must cite section D or Q with a quote holding a figure or a commitment: guidance,
     contract, backlog, capacity, a price or volume agreement;
   - a general outlook sentence does not qualify;
   - this is a stated rule, checked by code.
3. **Schema:** percentiles must be in range and each width a named value.

**Python mapping.**
- **Position:** an input's distribution is the prior's quantile function, shifted so its median is at the chosen
  percentile's value.
- **Spread:** the prior's own interquartile spread, scaled by width (narrow 0.5×, normal 1×, wide 1.5×). These scale
  factors are a stated convention; they are replaced by the calibration of section 4 once the replay has measured
  them.
- **Valuation:** the family engine computes the IV distribution (P10..P90), the terminal-value share and the
  secondary cross-check.

## 3. Pass 2, red team (one call, then Python)

**Reverse valuation, by Python:**
- for each input, with the others held at their pass-1 medians, find the percentile of the prior at which the median
  IV equals today's price;
- report it, or "not reachable within P1..P99";
- an input whose required percentile is outside P5..P95 is flagged an **extraordinary assumption** (Addendum C 5;
  ChatGPT's correction of Gemini, adopted).

**P6, red team.**
- **Input:**
  - the price and market cap;
  - for each input, Muse's pass-1 position and the price-required percentile with the extraordinary flags;
  - sections S and R, and D excerpts on request by section name.
- **Instruction:**
  1. For each input, state the strongest case for the market's required value, from the evidence.
  2. Then keep or revise your position.
  3. A revision needs either a quote not cited in pass 1, or a named error in a pass-1 reason (which reason, and why
     it was wrong).
  4. When the price requires an extraordinary assumption, the side relying on it carries the burden. A position near
     an extraordinary price requirement needs hard evidence, as in pass 1.
- **Code checks:** quotes as in pass 1. A revision without new evidence and without a named error is refused, and the
  pass-1 position stands.
- **Anchoring metric** (measured in the replay, never a gate inside a run): the share of revisions that move toward
  the price, and among those the share without new evidence. The coordinator reads it per replay date.

**Python final:** the IV distribution, Pr(IV > price), Pr(IV > 1.2 × price), Pr(IV < 0.8 × price), the terminal-value
share, model disagreement, the count of hard-evidence positions, and the extraordinary flags.

## 4. Calibration (after the replay)
- For every forecast input with an observed outcome (first reported after T), record where the outcome fell in the
  distribution Muse stated.
- Fit the mapping from stated to realised percentiles per input, by isotonic regression on replay dates, with
  cross-fitting by date.
- Live runs apply it. The width scale factors of section 2 are replaced the same way.

## 5. What gets built now (T-muse, a Sonnet coder; no GPU)
1. **The pack v2 builder:** sections F, Q, D, S and R from the shared point-in-time layer, the engines and the priors
   interface. Placeholder priors are allowed in tests only.
2. **Prompt templates P1–P6** as versioned text files, with a hash recorded per run.
3. **The runner:**
   - calls the llama.cpp server's OpenAI endpoint (Muse) with the pinned system prefix;
   - one call per prompt, JSON-only responses;
   - the retry rule;
   - every request and response saved per run.
4. **The checkers:** quotes, hard evidence and schema.
5. **The Python mapping, the reverse valuation and the final assembly.**
6. **The leakage audit script** (Addendum C 8): grep every pack and prompt for dates later than T, and for words
   about data availability and replays; the report is read by the coordinator.
7. **Tests with a mock model** (canned JSON, including invalid outputs): each checker, the retry, the fallback,
   the mapping, the reverse valuation, the anchoring metric, and that no pass-1 prompt contains the price, market cap
   or any value.
