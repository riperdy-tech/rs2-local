# Phase C — Deterministic Experiment Findings

Run 2026-08-18 on the live book (159 active names; 155 on the reverse-DCF route). All
experiments CPU-only, zero LLM calls, zero pipeline mutation. Scripts:
`tools/audit_202608/c*.py`; raw results: `audit/C_experiments/*.json`. Every number below is
reproducible from those artifacts.

## C1 — Discount-rate construction (c1_discount_rate.json)

| Scenario | Median MoS | Spearman vs baseline (MoS) | Brake-tier flips /155 |
|---|---|---|---|
| baseline (sector table 7–11%) | −41.7% | 1.000 | — |
| +2pts uniform | −54.7% | 0.999 | 3 |
| −2pts uniform | −20.4% | 0.995 | 8 |
| flat 10% (no sector structure) | −41.3% | 0.975 | 15 |
| flat 11.8% (book-implied CoE) | −53.1% | 0.976 | 17 |

**Findings.**
1. **The percentile machinery works as designed**: a uniform ±2pt rate error barely touches
   the ranking (ρ ≥ 0.995, 3–8 tier flips). The system's rank-not-level defense is measured
   effective against *uniform* rate error.
2. **The sector structure carries real but bounded ranking information**: removing it flips
   15/155 brake tiers (~10% of the book). A better rate *construction* (implied-ERP level +
   per-sector risk) would change the published treatment of roughly 15–17 names, not reorder
   the book.
3. **The level stays a judgment**: −2pts moves median MoS from −41.7% to −20.4% and p75 from
   −21.3% to +8.8%. Any consumer of the *absolute* MoS number (the website overlay shows it)
   is reading an artifact of the 10%-ish table. Wiring the measured implied rate
   (`tools/implied_erp.py`, ~11.8%) fixes the honesty of the level without much ranking
   effect (ρ 0.976).
4. **Correction to the record:** only **4/155** names are `consensus_snap` today — the
   "~78% snap" note at `run_rs2.py:1154` describes the pre-2026-08-13 fence and is stale.
   The published fair value is now the engine's own DCF for 97% of the book.

## C2 — Terminal-value share (c2_tv_share.json)

TV share of PV across 155 names: p10 49.3%, median **54.4%**, p90 60.0%. Names above 75%:
**zero**. The 5+5 fade structure with 2.5% terminal g keeps the terminal claim moderate for
every name in the book.

**Finding: a TV sanity gate would never fire. LOW value; do not build.** (Institutional norm
worries about 60–80%+; RS2's structure sits below it by construction.)

## C3 — Cash-flow definition variants (c3_flow_variants.json)

**SBC-deducted** (`base_cf − SBC_TTM`, 145/155 names with data):
- SBC consumes 13% of the median name's flow — and **~47% at the p10** (cf ratio p10 0.532).
- 5 names' entire positive owner earnings are SBC (ALKS, ANAB, BMRN, **DOCU**, SITM).
- Ranking effect is REAL and concentrated: Spearman vs baseline 0.894 (MoS) / 0.903 (gap);
  **30/145 brake-tier flips (~21% of the book)**. Largest gap moves: GWRE +65.5pts,
  RNG +44.3, ATRC +38.9, AMZN +32.1, QTWO +22.8, CART +22.7, META +19.8.
- **This is the opposite profile from C1: SBC omission is NON-uniform** — it systematically
  flatters SBC-heavy software/growth names, i.e. it distorts the *ranking*, which is the one
  thing the percentile defense cannot absorb.
- **STOP flag (data):** `fundamentals_history.json` has no per-year SBC field, so a
  retrodictive validation in the style of the n=4,104 blend study is impossible with current
  data. Cross-sectional impact is proven; predictive superiority is literature-supported
  (Damodaran) but not measurable in-repo until historical SBC is ingested.

**ΔWC-adjusted** (single-year change in non-cash WC, 141 names):
- Median cf ratio 0.964 but violent tails (p10 0.495, p90 1.68); ρ ~0.74; 43 tier flips;
  10 names' flow turns non-positive (including AMD, CMI — clearly noise, not economics).
- **Finding: a raw one-year ΔWC is noise-dominated. Do NOT adopt as-is.** The correct
  estimator (Buffett's "incremental WC required for volume", i.e. smoothed / revenue-scaled)
  is method work — flagged, not scored as proven value.

## C4 — Earnings-quality battery join (c4_c5_quality_solvency.json)

Overlay population: 166 names (35 BULL / 125 HOLD / 5 BEAR / 1 unclassifiable). Battery
coverage: 165/166.

- **BULLs with any quality flag: 1/35** (INVA: net issuance +7.4%/yr). HOLDs: 6/125.
- **Finding (honest, against expectation): the upstream factor screen already keeps
  accrual/manipulation junk out of the book.** The battery join is nearly-free insurance
  (the file exists; RS2 just never opens it) and catches real dilution cases like INVA, but
  it is a tripwire with a ~3% measured incidence, not a ranking changer.

## C5 — Solvency screen (same file)

- **BULLs failing coverage/leverage screens: 0/35.** HOLDs: 6/125 (flagged names carry thin
  coverage or net-debt/OCF > 4).
- **Finding: same shape as C4 — cheap tripwire, low current incidence.** Worth having because
  the book's composition changes with the screener bands, and the cost is a dict lookup on
  fields already ingested.

## C6 — Do the published signals rank outcomes? (c6_retrodictive.json — DESCRIPTIVE ONLY)

30-day horizon vs IWM (600 graded rows, 230 names; 91d+ not yet graded — history too short):

| Signal | ρ (all rows) | ρ (per-ticker median) |
|---|---|---|
| MoS vs excess return | **+0.404** | +0.226 |
| Conviction vs excess | +0.342 | +0.289 |
| Expectations gap vs excess | −0.239 | −0.268 |

Excess vs IWM by action family: **BULL +6.0% mean** (n=67), BEAR −7.0% (n=60), HOLD −2.1%
(n=467).

**Finding: every signal ranks outcomes in the economically correct direction at 30d** —
including the gap's negative sign (priced-for-perfection names underperform). With weeks of
history and correlated repeats this is *plausibility, not proof* (grader's own disclaimer
stands). Practical consequence for this audit: the current signal stack is worth protecting —
changes should be tested against this baseline, and nothing here justifies a teardown.

## C7 — Stage runtime & consumption (c7_stage_trace.json)

235 clean-timed post-era bundles. Median seconds / share of the LLM path / 8-gram echo into
FINAL.md:

| Stage | s | share | echo | mechanical consumer |
|---|---|---|---|---|
| S1 classify | 66.3 | 16.6% | 0.1 | routing.json (cyclicality) |
| S2 quality | 50.5 | 12.6% | 0.1 | none — context only |
| S3 valuation | 50.6 | 12.7% | **0.5** | stance/engine JSON → valuation_result |
| S4 scenarios | 42.9 | **10.7%** | 0.1 | **stored, read by nothing** |
| S5 conviction | 46.6 | 11.7% | 0.2 | SECTION 12 conviction parse |
| S6 red-team | 34.3 | 8.6% | 0.2 | none — context only |
| final assembly | 108.8 | 27.2% | — | verdict.json |

**Findings.** S4 costs ~43s/ticker (10.7% of the LLM path) for a dead structured output and
the lowest echo tier. Either wire its probabilities into a consumed expected-value/range or
fold the scenario ask into S5 and delete the call (~11% runtime saved, ~2 min/sweep-ticker).
S2/S6 have no mechanical consumer; their justification is context quality — that is an
LLM-dependent ablation (deferred spec below), not a deterministic call.

## C8 — Peer-multiple cross-check (c8_peer_multiples.json)

Corpus: 2,608 names with usable EV/EBIT across sectors with n≥20; 148/155 book names
comparable. Agreement (both signals cheap or both rich): 47. **Outright disagreement
(multiple cheap vs gap rich, or vice versa): 8 names (~5%) — ABNB, BLBD, DT, EHC, KNSA,
MEDP, MU, VIK.**

**Finding: the cross-check is feasible entirely from existing data and produces a
usefully small review list, exactly the error-tripwire role the institutional literature
assigns it.** (MU's appearance is notable given the 2026-07 MU BIGMOVE incident.)

## C9 — Information content of S4's probabilities (c9_s4_information.json, added 2026-08-19)

Run in answer to "should S4 be wired instead of removed?". Across 2,219 bundles carrying
stored probs:
- **82% of emissions are one of six stock triples** (0.30/0.50/0.20 alone: 26%); 90% of
  names get a bearish tilt (bull−bear ≤ 0 at the p90). Not company-specific analysis — a
  small menu of defaults.
- Bull−bear tilt vs realized 30d excess: ρ +0.138 overall (n=600) — right direction, far
  below MoS (+0.40) and conviction (+0.34); **~0 within the cheap MoS tercile** (−0.008);
  redundant with conviction (ρ +0.32).
- No scenario *values* exist to weight (removed in the post-inversion design); pairing
  deterministic lattice/persistence values with 82%-templated weights applies a
  near-constant haircut — ~zero ranking information added.

**Finding: wiring S4's probs into the valuation is measured NOT worthwhile. R1's remove
path is the recommendation** — fold scenario reasoning into S5 prose, delete the structured
emission (~43s/ticker saved). The only residual for the deferred ablation is whether the
scenario *prose* improves downstream conviction quality.

## Deferred LLM-dependent experiment specs (run after the Qwen 3.8 battery)

1. **Stage ablation A/B:** N≥20 names, full pipeline vs S2-dropped vs S6-dropped (prompt-only
   change), compare verdict fields + tier-2 violation rates + `compare_runs.py` diffs.
   Decides whether S2/S6 context earns 21% of runtime.
2. **S4 wiring test:** compute probability-weighted fair-value range from S4 probs × lattice
   cells; A/B whether exposing it changes SECTION 12 coherence and brake outcomes.
3. **Conviction anchoring:** S5 rubric with numeric ROIC/quality anchors (from C4/C5 fields)
   vs current 5-component prose rubric; measure conviction dispersion (target: less clustering
   at 7–9) and stability across reruns.

## STOP flags raised (per CLAUDE.md §0)

1. **Historical SBC** absent from fundamentals_history — blocks retrodictive validation of
   the SBC adjustment (C3). Requires SEC companyfacts re-ingestion upstream.
2. **ΔWC estimator** — correct form (smoothed, volume-linked) is method work needing its own
   validation; the naive form is measurably noise.
3. **Forward edge** — 30d descriptive correlations only; 91d/365d ungraded; no significance
   testing possible yet. Nothing in this audit may be sold as proven alpha.
4. **FX ingestion** (pre-existing flag, unchanged) — PLAN_FX_INGESTION_20260814.md.
