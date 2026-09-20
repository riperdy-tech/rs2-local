# Phase E — Methodology Verdict: is RS2 the right instrument?

**Date:** 2026-08-20 · **Method:** 14-agent adversarial investigation (5 measurement passes,
4 diagnosis lenses, 4 refutations, 1 synthesis). All measurements deterministic replays against
the live repo. **No pipeline file modified.**

Opened by the GOOG divergence (`D_base_contamination_20260819.md`) and the question: is this a
bug, or is the whole approach steering off course?

**Answer: the approach. This phase WITHDRAWS the central conclusion of
`VALUATION_AUDIT_202608.md` ("refine, don't rebuild").**

---

## 1. What RS2 arithmetically is

`valuation_engine.dcf_value` is homogeneous of degree one in `base_cf`. Therefore the published
fair value is exactly:

```
fair_value = base_cf × M(growth, wacc) × price / market_cap
```

verified across 876 name-basis cells, max relative deviation 0.0026 (rounding).

| Decomposition of `log(fair_value / price)` | Variance |
|---|---|
| `log(base_cf / market_cap)` — the trailing scalar | **0.7132** |
| `log M` — every growth and discount-rate assumption combined | **0.0840** |

- R² of published valuation on the trailing scalar alone: **0.885**
- R² on the entire DCF apparatus: **0.025**
- Spearman(published MoS rank, raw `base_cf/market_cap`): **0.928**
- `wacc` takes **4 distinct values across 165 companies**; M spans 6.72×–36.86×

**RS2 ranks by one trailing accounting yield. The DCF re-denominates that yield into dollars.
It does not reorder the book.**

### The base is selected, not derived

`base_cf` is chosen by a 3-sample majority vote of a local 27B model over a 3-item menu
(`run_rs2.py:889-922`). On **72% of the book (94% of market cap) the published base is not on
that menu.** Changing only the base: median fair-value factor **2.40×** (p90 7.30×, max 30.83×),
flips published stance on **64%** of names, flips brake tier on **67%**.

GOOG's $702.49, $64.30 and $153.25 are three legitimately-computed cells of one admissible set,
10.9× apart, all reproducing to the cent, all audit-clean.

---

## 2. Architectural — not patchable

1. **The object cannot represent the thesis.** `base_cf > 0` is enforced
   (`valuation_backbone.py:1260`) and the path is `base_cf × (1+g)^t`. **No parameter pair
   produces a single negative year.** GOOG's true 5-year FCF sum is −$26B; RS2's two admissible
   paths give +$253B and +$2,181B. Capex is all-or-nothing: subtract $132.4B forever (PV $1,775B)
   or zero (PV $0); truth is a path with PV $1,529B — the two options **bracket reality by $145
   per share**. A U-shaped margin has no slot.
2. **Two free parameters versus forty.** Beta is ingested for 96.9% of the book and read by
   **zero** valuation code. `fv_sensitivity_pts` is **exactly 0.0 for 40 of 276 names — including
   GOOG** — because the 20% growth cap binds both legs: it reads "perfectly insensitive" on the
   names whose value is most assumption-driven.
3. **Estimand mismatch (admitted in-code).** MoS is ranked because the level is a known artifact.
   `mos_distribution` p75 = **−26.4%**: the brake's "genuine bargain, may chase" tier fires on
   names the engine believes are 26% overvalued. 150 of 165 published MoS values are negative.
   A percentile cannot express "DO NOT INITIATE, absolute."
4. **Structural instability.** Run-to-run |Δ log fair_value|: median 1.99%, **p90 68%, p99 197%**;
   19.2% of reruns move >25%, 24.3% switch method. |Δ log price| p90 is 9.5%. **97.1% of the
   variance in the headline number comes from the numerator, not the market.**
5. **The verification regime is closed.** 23 tier-1 checks + 6 tier-2 classes + ~10 sanity
   conditions = **39 gates, zero comparing a produced number to anything outside RS2's own
   artifacts.** Across 818 recorded audits no check has ever failed for an economic reason.
   **Proof: doubling GOOG's TTM net income — a 109.5% net margin, arithmetically impossible —
   publishes at $1,108.91 with tier-1 pass 18/18.**

---

## 3. Bug class — real, owed, but does not change the instrument

- **146 of 152** live names' prompt "Operating Cash Flow" is the FY figure, not TTM. The block
  fails to reconcile with itself: OCF − capex = $73.27B printed directly above FCF $53.27B.
- **158 of 172 live names (92%)** publish one fair value on the report page and a different one
  on the screener row; 46 disagree on stance, 3 are opposite; Spearman between the two live MoS
  vectors 0.724; 22 names move >25 percentile points. Cause: `apply_regime_judgment` rewrites the
  valuation *after* the authoritative header is typed (80 bundles self-contradicted at run time,
  before any repatch).
- `_forward_growth` iterates `("revenue_cagr","eps_cagr")` and returns the first hit. GOOG's
  `eps_cagr = −0.2838` sat in the same dict as `revenue_cagr = +0.2189` — **the one ingested
  number that refuted the thesis was discarded by loop order.**
- ELMD repeat-loop: 93 of 600 graded rows are one ticker on three dates. MoS denominator uses a
  stale price (median error 1.90%; 38.6% of rows >2%).

---

## 4. WITHDRAWN — the prior audit's empirical pillars

**C6 (the pillar under "refine, don't rebuild") is beaten by a null model.**

| Signal | ρ vs 30d excess (raw) | after controlling for trailing 3m return |
|---|---|---|
| "buy whatever fell over the last 3 months" | **+0.567** | +0.328 |
| RS2 MoS | +0.404 | **+0.143** |
| MoS, name-weighted, excl. ELMD | +0.220 | **+0.106** |

Controlling for trailing return strips **65%** of MoS's association; controlling for MoS strips
only 22% of reversal's. In a structurally-matched horse race, **a three-month-old price beats
RS2's fair value in 96.2% of cluster-bootstrap draws.**

Sample validity: 600 rows but **8 entry dates, 10 distinct (entry,exit) pairs, all overlapping —
effectively ONE independent time observation**, so every C6 confidence interval was meaningless.
And the window was not neutral: across 16 monthly windows and 4,451 tickers, **July 2026 has the
most negative rho(trailing 3m, next 1m) of any month measured (−0.200 vs median +0.019).** C6
measured a reversal factor in the best month for reversal in the available history and read it as
valuation skill. Separately **275 of 600 rows (46%) carry a MoS rewritten after the fact**, 38
replayed after the outcome window closed.

Also withdrawn or qualified:
- **C2** (TV-share gate "would never fire") is *structurally incapable* of detecting a
  contaminated base: TV share is identical to 4 decimals for a base of $244B and a base of $1.
- **C4/C5** ("the factor screen keeps accrual junk out") is not licensed: GOOG's battery row is
  FY2025 and clean, GOOG was never in the 35-name BULL denominator, and the correctly-periodized
  TTM ratio (+0.0983) still misses C4's own +0.10 threshold.
- **C1**'s robustness holds only for *uniform rate* error; base error passes through at
  elasticity 1.0 versus 0.79× for the rate change actually shipped.
- **No C-phase script ever calls `apply_basis`** — all of them scored a book that differs from
  the published book on 66 names.

The audit's headline was false. Its three pillars were **blind, invariant, and confounded**.

---

## 5. What must survive any rebuild

- **`GROWTH_PERSISTENCE`** — a real empirical base rate over 3,115 ticker-years / 5,600 tickers /
  12 years of this corpus. Stronger evidence than the third-party ranges the benchmark report cites.
- **Market-anchored cost-of-equity level** (implied-ERP solved on the book's own aggregate) — more
  neutral than the benchmark's assumed 4.25% ERP.
- **The verdict ledger and grader existing at all**, and determinism/reproducibility.
- **One empirical survivor:** caliper-matching BULL and BEAR rows against HOLD rows *with the same
  trailing 3-month return* still leaves **BULL +4.73pts (95% CI [0.74, 8.46])** and
  **BEAR −4.24pts (CI [−8.37, −1.18])** — 58% and 76% of the raw edges. The *discrete verdict*
  may carry something the MoS number does not. Caveat: 43 and 58 distinct names, one episode.

---

## 6. Recommended shape — a funnel, two different activities

**Tier 1 — breadth, deterministic, no LLM, ~290 names.** Keep the backbone; **rename its output
to an expectations rank, not a fair value.** It answers "what growth does today's price require
versus what this company has demonstrated and what base rates say companies like it deliver?" —
a legitimate question `GROWTH_PERSISTENCE` makes RS2 unusually well-equipped to ask. Publish a
percentile with **no dollar figure**. Move the tripwires (NI-vs-OCF, non-operating share,
base-vs-history plausibility) here as **shortlist filters**, not audit gates.

**Tier 2 — depth on 10–25 names, at benchmark quality.** Driver-path forecast (per-year revenue,
margin, D&A, capex), explicit rf/ERP/beta WACC with a sensitivity grid, non-operating assets
valued separately and haircut, probability-weighted scenarios, absolute per-share value and a
sizing decision. **This is where a frontier model belongs** — affordable precisely because it
runs on 25 names, not 290.

**Stop doing:**
1. Calling tier-1 output "fair value"; publishing MoS as a dollar-anchored quantity.
2. Running the 5-stage prose pipeline on the full book — 25.3KB median FINAL.md distils to 822
   bytes of verdict.json, of which 4 numbers come from the model and **79% of those are
   overwritten by brake constants.**
3. Delegating base-cash-flow selection to a 27B three-way vote. `base_cf` must be **derived**
   from a stated, auditable decomposition (operating income → normalized owner earnings, with
   one-offs and non-operating items separated and explicitly valued or discarded).
4. Treating tier-1/tier-2 audits as accuracy evidence. Rename them; add ≥1 gate answering to
   something outside RS2's artifacts.
5. Optimizing against 30-day relative return — that metric drives the system toward being a
   reversal screen, which is what it already is.
6. Allowing two surfaces to render different numbers. One artifact must be the single source.

---

## 7. STOP conditions (data gaps — approval required, no workarounds)

- **D&A** absent for GOOG in all 12 years; incomplete for **90 of 290** names.
- **Marketable securities / investment holdings never ingested** — the benchmark's entire $94B
  SpaceX double-count correction is invisible to RS2 in both directions.
- **Segment revenue and margin never ingested.**
- **Invested capital and NOPAT never ingested** — ROIC appears in this codebase exactly once, as
  a word in a prompt.
- **Per-year SBC** missing (standing flag, `valuation_backbone.py:641`).

---

## 8. Still unproven

This does **not** prove RS2 has no valuation skill. It proves **C6 never demonstrated any**,
because the sample cannot separate valuation from reversal and the absolute level was never
scored by anything. The residual MoS partial (+0.106 to +0.166) and the matched BULL/BEAR effects
are not zero — they are unresolvable from 230 names in one 30-day episode.

Three measurements would settle it:
1. **Re-run the retrodictive test across multiple non-overlapping windows spanning ≥1 regime
   change**, with trailing-return control and per-name weighting built in, repatched rows
   excluded, and **the reversal null reported alongside every signal as a mandatory benchmark.**
   Until a signal beats "buy what fell" out of sample, it is not shown to be a valuation signal.
2. **Add a level-accuracy metric** (published fair value vs an independently defended valuation;
   plus fair-value stability across reruns). Rank metrics structurally cannot catch GOOG.
3. **Test whether the discrete verdict is the real signal.** If the caliper-matched BULL/BEAR
   effect replicates across regimes, the LLM layer's value is the action call, not the number.

---

## 9. Note on how this happened

Every reduction that produced the current architecture has a written, measured justification: the
single-scalar inversion was adopted because letting a small model guess base_cf/growth/WACC was
demonstrably worse; percentile cuts replaced absolute cuts because the absolute cut fired on 80%
of the book; the stability fence was retired because it fenced 5% of the book forever; S4 was
retired because 82% of its output was template text.

**This is not a codebase that drifted through carelessness.** It is a chain of locally-correct,
evidence-backed decisions that converged on an instrument answering a different question than the
one asked — and because the framework's vocabulary (Engine 1, tornado, Kelly, scenario CIs, data
tiers) was preserved intact on top of it, **nothing inside the system was capable of reporting
that the question had changed.**

---

*Adversarial note: all four diagnosis lenses returned PARTIALLY_TRUE under refutation. The
descriptive measurements above reproduced independently, several to the digit; the sweeping causal
attributions were trimmed. Numbers here are the surviving, reproduced set.*
