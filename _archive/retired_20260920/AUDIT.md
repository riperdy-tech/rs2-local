# RS2 Local — Process Audit (STOP-WORK review)

Date: 2026-06-29. Scope: full pipeline — valuation math, data use, logic/assumptions,
determinism, and the trustworthiness of our own validation. Triggered by the
`growth 4.0 → clamp 1.5 → IV $147,584` bug, which proved the deterministic engine was never
checked against the model's *actual* output formats.

**Headline:** the math *port* is faithful, but the valuation *architecture* is inverted. We have
the unreliable 3B model guess `base_cf`/`growth`/`WACC`, force a forward DCF from those guesses,
and bandage the wreckage with analyst consensus — while the screener's **already-sound,
deterministic reverse-DCF** (`valuation_models.json`, `build_valuation_models.py`) sits right
there, is even fed to the model as *priming*, and is ignored for the actual number. Most findings
below are downstream of that one inversion.

Legend: 🔴 CRITICAL  🟠 HIGH  🟡 MEDIUM  ⚪ LOW   | status: [open] unless noted.

---

## 🔴 CRITICAL

### C1 — Percent-vs-decimal unit slip produced blow-ups [patched, root cause open]
The model intermittently emits rates as whole-number percent (`growth: 4.0` meaning 4%, `wacc: 8.5`,
`terminal: 2.5`). `valuation_engine.validate_scenario` *clamped* growth to `GROWTH_MAX=1.50` (=150%/yr)
instead of recognizing the unit → CAT IV **$147,584** on a $994 stock (temp_test run 2).
- Evidence: `reports/_vartest.log`; `validate_scenario` old clamp path.
- Patched this session: `_norm_rate` (`|x|>1 → ÷100`) + `GROWTH_MAX 1.50→0.50`.
- **Root cause still open:** validation/clamp was written against an *assumed* output format, never the
  model's real one. The schema (run_rs2.py:85) shows `e.g. 0.25` but does not forbid `25`/`4.0`, and
  `valuation_io.valid_valuation_inputs` does no numeric/range checks at all. Need format-contract tests
  using *recorded* model outputs, not hand-written samples.

### C2 — We reinvent (badly) a sound model that already exists
`lib/dcf.ts` header: *"mirror of scripts/build_valuation_models.py."* The screener computes a
deterministic **reverse DCF** for 164 names → `valuation_models.json`:
- `base_cf = owner earnings (NI + D&A − capex)`, labeled `base_cf_kind`, real D&A from SEC history;
  fallbacks `fcf_fallback`, `ocf_minus_da_proxy`; **negative base CF → null model with reason (never a
  fabricated number).**
- **Sector WACC table** (`reverse_config.json`), not a guess.
- Solves **implied growth** s.t. PV = market cap, compares to **demonstrated 5y revenue/FCF CAGR** →
  `expectations_gap_pts` + verdict. This is the actual analytical edge.
- We FEED this as priming (`rs2_data.valuation_priming`, build_data_context:557) but then drive MoS off
  the LLM's *forward* DCF instead. The sound method is flavor text; the unreliable one is the number.
- Evidence: `git show HEAD:scripts/build_valuation_models.py`; `valuation_models.json` (LLY base_cf
  $14.8B `ocf_minus_da_proxy`; GOOG $73.3B `fcf_fallback`; 7 names skipped `negative_base_cash_flow`).

---

## 🟠 HIGH

### H1 — Negative/zero-FCF names bypass ALL base_cf validation
`backfill_common` (run_rs2.py:204) gates the entire band on `if fcf_b > 0:`. Banks (JPM), deep-cyclical
troughs, and any name with TTM FCF ≤ 0 skip every check → the model's raw `base_cf` is used unverified.
JPM only produced a sane IV by accident (bound skipped → its net-income guess passed through).
- **Evidence (validation set scan):** 4/27 bypass the bound — FANG (FCF −$0.7B), **JPM (−$147.8B)**,
  MRNA (−$2.1B), OKLO (−$0.1B). JPM's "FCF"/"OCF" = −$147.8B is itself **garbage from yfinance** (a bank's
  cash-flow statement is dominated by lending/deposit flows) — extra proof the yfinance source is wrong for
  financials; the screener uses SEC `fundamentals_history` + skips/handles banks correctly.
- **Adjacent (H2/H3):** many capex-heavy names have trailing FCF far below OCF — GOOG 73 vs 164, XOM 24 vs
  52, NEE 3.2 vs 12.5, CEG 1.3 vs 4.2, LLY 6.0 vs 16.8 — i.e. owner-earnings ≫ trailing FCF, exactly where
  the wide `½capex` band lets the model anchor low.

### H2 — base_cf band is too wide and does not force normalization
Band `[0.5×FCF, max(FCF, OCF−½capex, 10yr-avg-FCF)]`. FCX trough $1.72B sits inside `[0.56, 3.36]` →
kept. The model picks the low (trough) end and the bound permits it. The "normalize cyclicals up" intent
is an unenforced *should*.

### H3 — Wrong base_cf formula + wrong data source
We use `OCF − ½capex` (a Damodaran rule-of-thumb; `½` is an unjustified per-name assumption — expanding
miners ≪ ½, mature ≈ full) read from `financials.json` (yfinance TTM, **no D&A**). The canonical
`owner earnings = NI + D&A − capex` with **real D&A** is available in `fundamentals_history.json`
(fields `net_income`, `da`, `capex`, `ocf`, …) — the same file `midcycle_norm` already reads. We used the
weaker source and a proxy when the correct inputs were in the pipeline.

### H4 — FCFF vs FCFE inconsistency (mixed methods)
`base_cf` is trailing FCF ≈ FCFE (OCF is post-interest under US GAAP, minus capex). The engine then
discounts at **WACC** and adds **net_cash** in the equity bridge (`equity_per_share`) — both FCFF
treatments. For levered names this double-counts debt (net-debt subtracted again) and under-discounts.
Small for low-debt cash cows (GOOG works), material for utilities/REITs/miners. Pick one framework end to
end (the screener's reverse-DCF sidesteps this by solving growth to market cap).

### H5 — Consensus is a DOUBLE crutch
Analyst consensus is injected both (a) in the S3 prompt — *"your base IV should land near the ANALYST
CONSENSUS mean"* (run_rs2.py:80-83) — and (b) in the post-hoc `reconcile_to_band`. The user's objection
("overly dependent on analyst ratings") is structurally correct: the model is steered to consensus before
it reasons, then snapped to it after. Two layers of the same crutch, masking the input unreliability.

### H6 — Engine routing is model-dependent and mis-fires
TSLA → Engine 2 (`normalized_eps 2.35 × 14 = $33`) is wrong for a growth/optionality name. Engine
selection is left to the 3B model with thin guards; pre-profit detection is a single `NetIncome ≤ 0`
check. Mis-routes (TSLA E2, NVDA E3 lowball) generate the worst IVs.

---

## 🟡 MEDIUM

- **M1 — Loose schema validation.** `valuation_io.valid_valuation_inputs` checks only that `engine` +
  a `scenarios` dict exist. No numeric/range/scale checks; everything deferred to a clamp that proved
  insufficient (C1).
- **M2 — Engine 3/4/5 scale ambiguity.** Model supplies `metric`/`core_value`/`value`; per-share vs
  billions is never validated. Drives NVDA E3 $72 and the old OKLO/MRNA E4 blow-ups. The `[0.25×,4×]`
  clamp is a bandage, not a unit check.
- **M3 — Engine 2** has no equity bridge and leans on a single through-cycle multiple (fragile; documented).
- **M4 — Arbitrary fallback** `owner_earn = 2.0×fcf` when OCF ≤ 0 (backfill_common:207).
- **M5 — Our own validation yardstick is noisy.** `build_matrix` action column is garbled ("al Kelly",
  "capped at" — bad SECTION-12 regex), and conviction was read from FINALs generated against the *old
  broken* IVs. We were grading against an unreliable ruler. Fix the tooling before trusting any matrix.
- **M6 — Non-determinism.** temp 0.4 + MoE → `base_cf`/`growth`/`WACC` wobble run-to-run (GOOG base_cf
  $119B vs $95B across runs). Not yet stabilized (low-temp / median-of-N test was interrupted).

## ⚪ LOW
- **L1** engine5_binary doesn't renormalize probs to 1.
- **L2** `extract_json` largest-object-first can grab a JSON from the thinking trace, not the payload.
- **L3** model can override `stage1_years`/`fade_years`.
- **L4** `GROWTH_MAX` now 0.50 still admits 50%/yr stage-1.

---

## Cross-cutting conclusion
The valuation layer is an **LLM-guessed forward DCF + heuristic bounds + consensus net**, run in parallel
with — and ignoring, for the headline number — the screener's **deterministic reverse-DCF** that is
already sound and already in the prompt. A 3B-active model cannot reliably set `base_cf`, `growth`, *and*
`WACC`; the deterministic model already sets them from data. The architecture is backwards.

## Recommended direction (for discussion — NOT yet implemented; work remains stopped)
1. **Invert it.** Make the deterministic reverse-DCF the valuation backbone: consume
   `valuation_models.json` (implied_growth, expectations_gap, base_cf, base_cf_kind, sector WACC) as the
   IV/MoS source. Port `build_valuation_models.py`'s base_cf logic verbatim (owner earnings NI+D&A−capex
   from `fundamentals_history.json`); adopt its **honest-null** discipline for negative base CF.
2. **LLM does only what the math can't:** archetype/engine selection where the DCF is invalid (pre-profit
   → Engine 4 option bridge), qualitative theses, scenario probabilities, conviction. It should not pick
   `base_cf`/`growth`/`WACC`.
3. **Remove consensus from the prompt**; keep it (if at all) as a single last-resort sanity *flag*, not a
   driver.
4. **Fix the bugs regardless of architecture:** C1 unit contract + tests, H1 negative-FCF handling,
   M1 strict schema validation, M5 comparison tooling.
5. **Stabilize determinism** (M6) before any re-validation, so the matrix measures signal not noise.

## Resolutions (2026-06-29 — inverted architecture + cleanup)
- **C2 RESOLVED** — `valuation_backbone.py` is the deterministic reverse-DCF backbone (port-exact vs the
  screener, implied growth to 4dp). The expectations gap is the headline; the LLM only judges believability.
- **C1 RESOLVED (root)** — the model no longer supplies DCF numbers, so the percent/decimal class is
  impossible. `_norm_rate` retired with the rest of the forward-DCF code.
- **H1/H3 RESOLVED** — base_cf = owner earnings (NI+D&A−capex) with real D&A from SEC `fundamentals_history`,
  mid-cycle for cyclicals; negative base CF → honest NULL (routed to Engine 4 / Engine 2). The `if fcf_b>0`
  bypass and the OCF−½capex heuristic are gone (`backfill_common` deleted).
- **H2 RESOLVED** — no model base_cf pick to bound; the backbone computes it.
- **H4 RESOLVED** — adopted the screener's consistent convention (owner-earnings @ WACC, PV vs market-cap
  equity, no net_cash bridge). FCFE/FCFF mix removed.
- **H5 RESOLVED** — consensus removed from the prompt (`valuation_block` replaces the anchor) AND as a
  driver (`reconcile_to_band`, `analyst_target`, `valuation_anchors_block`, `valuation_priming` deleted).
- **H6 PARTIAL** — DCF-able names no longer need engine selection; pre-profit → Engine 4, financial →
  Engine 2 routed deterministically from the backbone null reason. (Engine 2/3/5 forward pickers retired.)
- **M1 RESOLVED** — the LLM JSON shrank to a believability stance (or Engine-4/2 inputs); far less to validate.
- **M5 RESOLVED** — `build_matrix.py` retired; `valuation_matrix.py` reads the new format cleanly (action
  column no longer garbled) and runs an anomaly check (deterministic re-validation: 0 anomalies on 27 names).
- **M6 RESOLVED (valuation)** — the valuation is now deterministic/reproducible; only the believability
  stance + scenario probs come from the LLM. (Power/Modern-Standby teardown also fixed: display-never-off
  on AC + `keep_awake`/`keepawake.py`.)
- **M2 PARTIAL** — Engine 3/5 retired; Engine 4 keeps a unit-sanity FLAG (not a silent clamp).
- Dead code removed: run_rs2 `compute_with_revision`/`backfill_common`/`backfill_engine_specific`/`_plausible`;
  valuation_engine trimmed to `dcf_value`/`engine2_cycle`/`engine4_bridge`; obsolete scripts deleted
  (`recompute_val.py`, `temp_test.py`, one-off `proof_*`/`_vartest`). All modules import clean.

## STILL OPEN (not cleared — for the next pass)
- S5 **conviction/action calibration** (model runs 8–15 vs ChatGPT 6.5–11.5) — qualitative, un-reviewed.
- Full **comparison-tooling** correctness (GPT-side + local action/conviction parsing) — must be trusted
  before any matrix is.
- **Deep-research** brief quality / on-entity / citation validity at scale (only GEV spot-checked).
- **Engine 3/4/5** end-to-end behavior beyond the few names seen.
- **Macro/regime stale-data** handling and **classification** accuracy across the full set.
- `midcycle_norm` "long window dragged by an old crash" caveat (10yr avg mis-normalizes growth-utilities
  NEE/CEG, as seen).
