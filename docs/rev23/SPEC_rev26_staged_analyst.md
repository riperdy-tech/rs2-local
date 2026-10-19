# SPEC revision 26: the staged analyst (v1, 2026-10-19)

**Source:** the operator's approval (2026-10-19) of `PLAN_terminal_reinvestment.md`, the sections "Rulings on cross-check 22" and "Gemini's
cheap replay experiment". Read those first.

**Principles:**
- Qwen stays the analyst and the judge. Code does every calculation, every conversion between bases, and every check.
- Stages are **separate model sessions**, joined only by the artifacts named here. A stage sees nothing the spec does not hand it.
- Annotate, never loop. Exactly one revision turn exists, in stage 3. Anything still unresolved after it becomes "no call", stated, never
  silent.
- D2 stays off. The desk arithmetic is revision 25.2's path arithmetic (revenue × X margin, κ, working capital on the declared revenue).
  D2 is wired in later, after the fade-convention ruling.
- `PACK_REVISION` 26 for arm `r26`. Every other arm stays byte-identical.

## 0. Logging (all stages, all arms that use `ollama_raw`)
Per model turn, write `turns/<stage>_<n>.json`:
- the rendered prompt's sha256;
- the raw completion (content, thinking and tool-call text, as returned);
- `prompt_eval_count`, `eval_count`, `done_reason`, the seed and the options.

Per run, write the SYSTEM text's sha256 and the template sha256. Logging never changes what is sent to the model.

## 1. Stage 1: research and the fact ledger (one session)
**Sees:** the **blind pack** (section 5), the tools `search_web`, `fetch_page` and `register_facts`, and the stage-1 TASK. It sees no price,
no consensus, no reference value, no default path and no desk.

**Does:** researches as today, then calls `register_facts` (one or more calls). Each fact:

```
{"fact_id": "F1", "source": "pack:<section id>" | "page:<url>" | "query:<query id>", "quote": "<verbatim, ≤ 400 chars>",
 "entity": "<the company, segment or market the number is about>", "metric": "<what is measured>", "period": "<e.g. FY2025, Q2 2026>",
 "value": <number or null>, "unit": "<%, USD m, USD/day, x, ...>", "basis": "filed_gaap | company_adjusted | third_party | n/a",
 "duration_years": <number> | "ongoing" | null}
```

`duration_years` is the span the fact speaks for: a contract term, a guidance horizon or a backlog. A one-off figure gets null.

**Code checks each fact. These are annotations; the fact is kept with its status.**
- **The quote exists verbatim in its source,** after normalizing whitespace and punctuation: `quote_verified` or `quote_not_found`.
- **Entity/metric proximity:** the content words of `metric` and `entity` (≥ 4 letters, stopwords removed) must occur within ±300 characters of
  the quote in the source. Otherwise `metric_not_near_quote`, naming the missing words. Generic; no per-industry lists.
- **The value appears in the quote,** in the same written form: `value_in_quote` or `value_not_in_quote`.

**Output: `dossier.json`.** It holds every fact with its status, plus a ≤ 600-word research summary written by the model in the same call.
Only facts that are `quote_verified` **and** not `metric_not_near_quote` are **usable**. The others are listed in later stages as "unusable,
why". This stage ends when `register_facts` is called with `done: true`, or when the turn budget ends (the dossier is then marked
`incomplete`).

## 2. Stage 2: the blind forecast (a new session, K = 3 samples, seeds s, s+1, s+2)
**Sees:**
- the **blind pack**;
- `dossier.json` (usable facts plus the summary);
- the **operating-margin history bar** (section 5);
- the stage-2 TASK.

It sees no research tools, no price, no consensus and no default path.

**Does:** one call to `submit_forecast`, per scenario (Base, Bull and Bear):

```
{"near_term": {"rev_growth": [g1, g2], "op_margin": [m1, m2], "fact_ids": [...]},
 "normalized": {"year": N (3..5+F), "rev_growth": gN, "baseline": "min|p25|median|p75|max|last", "delta_pts": d, "fact_ids": [...],
                "reason": "<≤ 60 words>"},
 "transition": "linear" | "step_at_year" | "hold_then_linear", "transition_year": k (when step or hold),
 "long_run_margin_op": L, "terminal_g": gT, "terminal_ronic": ronic, "fade_years": F, "prob": p}
```

Plus the scenario-independent `discount_rate` and `frame`, as revision 24 has them.

**Rules:**
- **Margins are the filed operating margin** (operating income / revenue), the basis Qwen reads in filings. Code converts.
- **The normalized margin is code's sum:** `baseline value + delta_pts`. The model never types the result.
- **Financial family** (the D2 route): the margins are the X-basis net margin directly, and the baseline bar is the X-basis history.
- **Validation is structure only:** five fields, finite numbers, the enums and the fact IDs exist. Numbers are never bounded. A structure
  failure gets **one** repair turn; a second failure means `forecast_invalid`, and that sample is dropped.

**Code then:**
1. **Builds years 1–5.** Years 1–2 as given. Years 3..N follow the transition to the normalized margin and growth; years after N hold
   normalized. Growth moves the same way as margin.
2. **The bridge from the operating basis to the X basis,** per year, shown as a table. **Amended 2026-10-19 (coordinator ruling, R26-E): calibrated to the filed base year.**
   `K_0 = OI_0 − X_0 / (1 − τ)` in dollars, and `X_margin_t = (op_margin_t − K_0 / R_t) × (1 − τ)`.
   - **K_0** carries the base year's net interest, other non-operating items and acquired amortization together, held in dollars (no amortization schedule), stamped `bridge_calibrated_to_base_year`.
     The held amortization is listed as an assumption. At the base year the bridge returns X_0 exactly.
   - **OI_0:** the filed operating income, on the desk's revenue basis (the filed margin times rev_L). **X_0:** the pack's own x_L × rev_L.
   - **τ:** the record's measured tax rate. If it is unmeasured, the sample is `bridge_unavailable_tax` and is not valued; a missing OI_0 or X_0 is `bridge_unavailable_operating_income` / `bridge_unavailable_x_0`.
   - The bridge assumptions are listed in the result. (Superseded: the separate net-interest, other-non-operating and A_t inputs of the first draft.)
3. **Values** with the 25.2 path arithmetic (revenue and X-margin path into the existing desk). `long_run_margin` is bridged the same way at
   the final year's levels.
4. **Evidence duration:** for any fact cited in `normalized` or behind `long_run_margin_op` whose `duration_years` is a finite number, code
   also values an alternative path.
   - The margin fades linearly from the end of that duration to the normalized baseline (with no delta), over the fade.
   - It is reported as `alt_path_after_evidence_expiry` (value and path). It is never substituted.

**Output: `forecasts.json`.** The three samples, each with its path, its bridge, its value per share and its alternative paths. Plus:
- the median sample's index;
- `spread = (max − min) / median` of the Base values.

## 3. Stage 3: reveal and reconcile (a new session; one revision at most)
**Sees:**
- `dossier.json`;
- the **median** sample's forecast and its desk result;
- the three Base values;
- the market price and the price-implied inputs (the reverse solver, on the same path arithmetic);
- the **basis-corrected consensus** (section 5);
- the diagnostics: every alternative path, and consensus divergence.

**Does:**
- **(a) The crux:** it states it in the revision-24 crux form, with quotes resolved by code as today.
- **(b) Keep or revise:** it either keeps the forecast, or submits **one** revised `submit_forecast`.
- **The revision rule:** a revision must cite at least one fact ID and give the reason the fact was underweighted.
- **It is code-blocked from seeing its own stage-2 reasoning text.** It sees only the forecast numbers.

**Code:**
- **If a revision is submitted:** values it (K = 1).
- **Records the pre- and post-reveal values,** and for each changed margin the **pull ratio**
  `|m_post − m_pre| / |m_consensus − m_pre|` (null when consensus is unavailable or equal to `m_pre`).

**The verdict inputs:** the final forecast's value, against the price band, as today.

**No call:**
- the three stage-2 Base values straddle the price's verdict boundary (one sample says undervalued, another overvalued, against the same
  band);
- or the crux is invalid after this stage (no second turn).

## 4. Stage 4: the memorandum (a new session)
**Sees:**
- the dossier;
- the **frozen** final desk result (read-only table);
- the bridge table;
- the crux with its verification;
- the stage-2 spread;
- the diagnostics;
- the memo TASK.

**Does:** writes the memorandum and the contract's text fields. **Every numeric contract field is filled by code** from the frozen result
(no model-typed numbers).

**Verifier (code; annotate, never change):**
- every number in the memo that matches a frozen-table label must equal it within rounding (`memo_number_mismatch`);
- the memo's stated verdict must equal the code verdict (`memo_verdict_mismatch`);
- labels stated in the memo must match the stage-2 forecast's transition and baseline choices (`memo_forecast_mismatch`).

Any mismatch means the verdict is published with the flag, and `actionable` is false.

## 5. Code-owned inputs
- **The blind pack:** the revision-24 pack with every consensus-derived, price-derived and reference-value line removed by **section
  tags**, not by text search. The pack builder tags each emitted line with its source.
  - **The removed classes:** consensus estimates, the base-year check, the estimate trend and revisions, price targets, DEFAULTS `levels`
    and consensus status, the CONSENSUS-IMPLIED VALUE and any reference value, the price, the market cap, multiples on price, and TASK
    lines naming those.
  - **Narrative sources** (the research summary, the catalyst brief, guidance, news) are filtered **sentence by sentence**: a sentence that
    names consensus, analysts, a price target, the share price or a multiple is dropped, and the drop is listed.
  - **The leak test:** none of the removed classes' numbers (in any rounding to 1–3 significant digits) appears in the blind pack, except
    where the same number is a filed fact. An exception is listed with its filed source.
- **The operating-margin history bar:** per filed year, the operating margin; plus min, p25, median, p75, max and last over the filed
  window. All are labelled "filed operating margin, operating income / revenue". With no single "default" line.
- **The basis-corrected consensus (stage 3 only):** the vendor EPS × (filed base-year EPS / the vendor's base-year EPS), each converted to
  an X-basis margin on the consensus revenue.
  - If the base-year ratio is outside [0.5, 2], or there are fewer than 3 EPS analysts: `consensus_not_comparable`, shown with the reason
    and no margin.
  - The operating-basis equivalent is obtained by inverting the bridge at the same year.

## 6. The frozen benchmark and the evaluation (registered before any run)
- **The panel:** 12 names. The 7 restoration names (MSGE, TASK, PACS, DAC, BUD, GOLD, MCY) plus 5 drawn by the existing hash rule from
  DRAW_ORDER, excluding those 7. The 5 are drawn **before** any stage runs, recorded with the draw.
- **Stage 1 runs once per name.** Its dossier is frozen as the benchmark input. Stages 2–4 are re-run per design iteration.
- **Readers:** two fresh agents. Each gets a **masked extract**: the dossier, the forecast inputs, the memo text and the contract text
  fields, **with every value per share, price, verdict word and table of results removed**. They do not see the plan or results files.
  They score each name on the rubric below, independently. Disagreements are adjudicated by the coordinator, with reasons recorded.
- **The rubric, per name:**
  - (1) facts used in the forecast are correct (entity, metric, period, basis);
  - (2) the forecast path is consistent with the memo's stated economics and labels;
  - (3) no unsupported copy of a revealed number in stage 3;
  - (4) the normalized state and the long-run margin are defended by evidence of matching duration.

  Each is scored coherent, questionable or incoherent, with quotes.
- **Metrics:**
  - loops (must be 0);
  - stage-2 structure failures;
  - fact quote and proximity statuses;
  - the K = 3 spread;
  - direction agreement;
  - pull ratios;
  - memo-verifier flags;
  - reader scores;
  - minutes per stage.
- **A pass for a design iteration** (all must hold):
  - 0 loops;
  - 0 incoherent from either reader after adjudication;
  - at least 10 of 12 coherent;
  - median spread ≤ 20%;
  - at least 10 of 12 with unanimous direction;
  - median unverified pull ratio ≤ 0.15;
  - 0 `memo_verdict_mismatch`.
- **At most 3 iterations.** Then a 4-name unseen end-to-end holdout (all stages), drawn the same way after the panel. It must give ≥ 3 of 4
  coherent and 0 incoherent. **A pass authorizes a book-wide paper run, never live use.**
- **The anchoring canary:** on 4 panel names, stage 3 is re-run with the revealed consensus margins shifted by +3 and −3 points. The
  stage-2 output is unaffected by construction. The stage-3 pull toward the false number must stay ≤ 0.15 when no new fact is cited.

## 7. What is out of scope
- D2;
- the D&A and currency field work (already built);
- temperature or `min_p` changes (one variable at a time, later);
- `num_ctx` reduction (after the stage sizes are measured);
- any model change.

## 8. The draw, registered 2026-10-19 before any revision-26 run
- **Rule:** DRAW_ORDER.json (generated 2026-10-15, pool 143) in its order, skipping the 7 restoration names and the two passed over earlier (TOP passed over, NRP failing the draw rule).
- **Applying the rule:** each drawn name must satisfy the existing draw rule (a positive base-year `x_L`, and positive `oe_base`), or it is skipped with the reason recorded and the next name is taken.
- **Panel additions:** OGE, HNRG, PTCT, LPG, ITGR.
- **Holdout:** the next four eligible names after them, beginning KOF, DAR, VSNT, CTVA.
