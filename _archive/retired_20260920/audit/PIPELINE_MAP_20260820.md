# RS2 PIPELINE MAP — every process, its data, its code, its AI, its output

Companion to `HANDOFF_20260820.md`. Read left to right: where data comes from, what deterministic
code does with it, **what the code does NOT do**, what the AI is allowed to decide, and where the
result goes.

Legend — **ENGINE** = who does the work: `PY` deterministic Python · `API` vendor fetch ·
`LLM-R` research model (`qwen3:14b`) · `LLM-A` analyst model (Qwen3.8-27B) · `SEC` filings.

---

## 1. DATA LAYER — everything the analyst ever sees

| # | Process | Source → Output | Engine | What the code DOES | What it does NOT do | Known defects |
|---|---|---|---|---|---|---|
| D1 | Fundamentals extract | `companyfacts.zip` (19.7K CIK, SEC XBRL) → `fundamentals_history.json`, `_ttm`, `_quarterly`, `_battery` | **PY** (`build_fundamentals_history.py`) | Maps XBRL tags → 24 fields, 12 yrs. Scale defences (1000× slips), row-consistency by accession, **NEW**: stitch → component-slot sums → lone-depreciation allowlist | No segments (not filed). No quarterly OCF/capex. No per-year SBC. No marketable securities. No FX conversion | Op-income 231 null (never filed). Capex still 170 null. 24 lattices still single-cell |
| D2 | Market snapshot | yfinance → `financials/{T}.json` | **API** | Price, shares, mcap, beta, cash, debt, SBC, EV multiples | — | **OCF/capex are FY figures presented next to TTM with no period label** — 146/152 names |
| D3 | Consensus + transcript | OpenBB/yfinance → `cache/openbb_{T}.json` | **API** | P/E, ROE, P/B, forward growth (rev + EPS CAGR), verbatim call excerpt | Doesn't summarise (correct — keeps Tier 1) | `_forward_growth` returns `revenue_cagr` first; GOOG's `eps_cagr −0.2838` sat unread |
| D4 | Behavioural | yfinance → `enrich/{T}.json` | **API** | Analyst targets, 52wk, short %, ownership, options skew | — | Keys are `analyst_target_*`; my pack read `target_*` → model saw "None" (**fixed**) |
| D5 | Web research | SearXNG → **`rs2-research` qwen3:14b** → `research/{T}.md` | **LLM-R** | 4–5 topics, cited, low-trust sources stripped, on a *clean* model so the analyst prompt can't contaminate it | Doesn't re-check its own numbers | **Only LLM-written input.** Carried a stale $462B backlog while the correct $514B sat in D3's transcript |
| D6 | Classification | `stocks.csv` | **PY** | Sector/industry | — | — |

---

## 2. VALUATION LAYER — deterministic, no AI

| # | Process | Input → Output | What the code DOES | What it does NOT do |
|---|---|---|---|---|
| V1 | `_base_cf` | D1 → one scalar + `kind` | Picks ONE definition: FFO (REIT) · mid-cycle (cyclical) · **50/50 margin blend** (default) · fcf_fallback · ocf−da proxy · yf FCF. SBC now deducted on FCF-derived kinds | No maintenance-vs-growth capex split. No ΔWC. No non-operating scrub |
| V2 | `dcf_value` | base_cf, g, wacc → PV | 2-stage: 5y constant + 5y linear fade + Gordon @ 2.5% | **Homogeneous of degree 1 in base_cf** — contributes only a scalar multiple. Cannot express a negative year, a U-shaped margin, or a capex path |
| V3 | Discount rate | sector table + CoE anchor | 11-row table 7–11%, +1.7pt market-anchored offset | No beta (ingested for 96.9%, read by zero code). No CAPM, no rf/ERP build-up |
| V4 | Implied growth | mcap, base_cf, wacc → g | Bisection so PV == market cap. **The headline signal** | Compares an *earnings* growth requirement against *revenue* CAGR — only valid at constant margin, zero reinvestment |
| V5 | `base_lattice` | D1 TTM/FY → cells | Same DCF on 3 bases: current earnings / owner earnings / mid-cycle. `contested` if MoS spread ≥30pts | **No quality test on `current_earnings`** — raw TTM GAAP NI, contamination and all |
| V6 | Fair value | g_fwd capped 20% → $ | Forward-anchored, consensus-fenced, blanked if \|MoS\|>150% | `fv_sensitivity_pts` computed, read by nothing. Reads **exactly 0.0** for 40/276 names because the growth cap binds both legs |
| V7 | Comps | corpus EV/EBIT → signal | Sector median, cheap/inline/rich | Never enters fair value — display + tripwire only |
| V8 | Calibrations | book → `cache/*.json` | `mos_distribution` (percentiles), `coe_calibration`, `sector_evebit` | `build_mos_distribution` has the **same repatch bug** — must be fixed in the same commit |

---

## 3. PRODUCTION PER-TICKER PIPELINE — what the AI actually gets to decide

| # | Step | Engine | AI decides | AI is FORBIDDEN from | Output → |
|---|---|---|---|---|---|
| P1 | enrich / OpenBB warm | PY/API | — | — | D2–D4 |
| P2 | deep research | **LLM-R** | Sub-questions, synthesis | — | `research/{T}.md` |
| P3 | backbone | PY | — | — | V1–V8 |
| P4 | **regime decide** | **LLM-A** ×3 vote | **The earnings basis** — the ONLY LLM call that can move a published valuation (~80 pts of MoS) | Anything else. Runs at **8,192 ctx** (4–8% headroom); `think=False` | `regime_decision.json` |
| P5 | S1 classify | LLM-A | Archetype, regime probabilities | *"DO NOT select a valuation engine"* | `routing.json` |
| P6 | S2 quality | LLM-A | Moat, Lynch class — **prose only** | — | context only |
| P7 | S3 valuation | LLM-A | Believability *stance* | *"The intrinsic value is NOT yours to compute"* | stance JSON |
| P8 | S5 conviction | LLM-A | Scenarios (prose), conviction /15, weight | — | SECTION 12 |
| P9 | S6 red team | LLM-A | Short thesis, pre-mortem | — | context only |
| P10 | final assembly | LLM-A | Section 0–12 narrative | **FIELD OWNERSHIP: "may NEVER print a different value"** than the engine header | `FINAL.md` |
| P11 | emit_verdict | **PY** | — | — | Parses §12, then **overrides**: `apply_regime_judgment` → **don't-chase brake** (caps conviction ≤9.5, weight ≤3.0) → `_stance_from_gap` **discards the model's stance 31.5% of the time** |
| P12 | sanity + tier-1 | PY | — | — | 23 checks, all internal-consistency |
| P13 | tier-2 audit | **LLM-A** | Violation classes | Told the engine result is **AUTHORITATIVE**; a model that *corrects* a wrong engine number **scores as violating** | pass/fail gate |

**Between every stage:** carry truncated to 4,500 chars — 38.8% of the model's own reasoning
discarded (now head+tail, was head-only, which deleted every conclusion).

---

## 4. DEPTH TIER (experimental, not in production)

| # | Step | Engine | What changes vs production |
|---|---|---|---|
| X1 | `build_pack` | PY | Honest, period-labelled facts. **No** base_cf, **no** fair value, **no** engine header |
| X2 | analyst run | **LLM-A** | **Owns engine selection AND the valuation.** thinking `high`, one 64K context, no stage split, no truncation |
| X3 | `analyst_tools` | LLM-A + SearXNG | Searches *during* reasoning. Every query/page snapshotted. Scoped: forward guidance yes, re-sourcing filings no |
| X4 | `consensus_valuation` | PY | N seeded samples → plausibility guard (calibrated on 6 reference points) → tolerance check → median |

---

## 5. CURRENT RULES — and which are shackles

**A rule is a shackle when it stops the model doing something it can do well, for a reason that
no longer holds.**

| Rule (current) | Where | Shackle? | Why |
|---|---|---|---|
| "DO NOT select a valuation engine" | Modelfile + S1 | **Yes** | Added when a small model guessed with no data. Data is now fixed; the framework's own Step 0-2/0-4 were *deleted* to enforce it |
| "Intrinsic value is NOT yours to compute" | S3 | **Yes** | Same origin. Unshackled, the model catches contamination the engine cannot |
| Field ownership: never print a different value | FINAL_TASK | **Partly** | Prevents invented numbers (real), but also prevents *correcting* a wrong one |
| Auditor: engine result is AUTHORITATIVE | tier-2 | **Yes** | Makes being right a violation |
| Post-brake fields given to the auditor | tier-2 | **Yes — broken** | Structurally unsatisfiable: fails the model for not matching numbers written *after* it wrote |
| `think = False` | config | **Yes** | Reasoning disabled to satisfy a format contract |
| `num_ctx` 16,384 pinned; carry 4,500 | Modelfile/config | **Yes** | Model trains to 262,144. Its own reasoning is truncated between stages |
| Regime ctx 8,192 | run_rs2 | **Yes** | Smallest window on the highest-stakes call |
| Don't-chase brake | emit_verdict | **Keep, instrument** | Behavioural discipline; but it overwrites the model silently |
| `_stance_from_gap` override | emit_verdict | **Keep** | Model stance was unstable on byte-identical input — still true |
| Percentile MoS cuts | rs2_data | **Keep** | Absolute cut fired on 80% of the book |
| `MOS_EXTREME_MAX` 150% | backbone | **Keep, but weak** | Catches none of the 8 worst offenders — malfunction detector, not plausibility guard |
| `FWD_GROWTH_CEIL` 20% | backbone | **Obsolete — replace, don't remove** | Built for trailing-CAGR blowups; 159/164 now have forward growth. Bare removal sends MU to +716% |
| `ENGINE 3 RETIRED` | Modelfile | **Keep** | Segments genuinely not filed |
| Blended Engine deleted | Modelfile vs RS2.txt:111 | **Missing capability** | Specified, never built; 50% of names are contested |

---

## 6. CLOUD AI vs OURS — the same model, different cage

The benchmark GOOG report was produced under **RS2 v2.0, the same framework**. Only the
conditions differed.

| Dimension | Cloud AI does | Production RS2 does | Depth tier now does |
|---|---|---|---|
| **Method choice** | Picks the engine, states why, names what would be wrong with alternatives | Forbidden — hard-coded decision tree | Picks its own ✅ |
| **The number** | Computes intrinsic value itself | Forbidden — Python computes it, model may only quote it | Computes its own ✅ |
| **Reasoning** | Thinks freely, as long as needed | `think=False`; 4,500-char carry truncation | `high`, one 64K context ✅ |
| **Missing facts** | Searches mid-reasoning | Cannot. Fills gaps with assumptions | Searches, snapshotted ✅ |
| **Evidence** | Sees everything at once | Cash-flow lines were gated off on 22/88 basis decisions | Whole pack ✅ (gate now removed) |
| **Disagreeing** | Says the number is wrong and explains | Contract forbids it; auditor fails it | Free ✅ |
| **Uncertainty** | "[Unconfirmed]", ranges, CIs, declares model confidence MEDIUM | Emits a point estimate; scenario probs were deleted | Instructed to mark and carry it ✅ |
| **Structure** | One pass, whole picture | 5 stages, each seeing a truncated summary of the last | One pass ✅ |
| **After it speaks** | Nothing overrides it | Brake caps conviction/weight; stance discarded 31.5%; basis swapped | Guard *refuses*, never rewrites ✅ |

**What cloud AI still does that we do not:**
- **Fallback / blend.** A cloud analyst notices a method doesn't fit and switches or weights two.
  Ours has no re-route: routing is a tree, the lattice is a *basis* choice not a *method* choice,
  and the guard refuses rather than re-routing. The framework specifies a Blended Engine; it is
  implemented nowhere.
- **Self-critique of method.** Framework Step 0-4 ("what errors if an alternative engine were
  used?") was deleted.

**What we do that cloud AI does not** — keep all of it: SEC-derived filings as the number source,
1000× corruption gating, cross-sectional calibration, an append-only point-in-time verdict ledger
with an outcome grader, deterministic reproducibility, and empirically-derived parameters
(`GROWTH_PERSISTENCE`, 3,115 ticker-years).

---

## 7. THE HONEST SUMMARY

Unshackling gives the model back the two things it does better than our code — **choosing the
method** and **noticing when the inputs are wrong**. It does **not** fix instability: six
unshackled runs on GOOG span $161–$335, and better data made the spread *widen* (14.8% → 31.4%).

So the design that follows is neither "trust the model" nor "constrain the model", but:
**the model reasons freely; deterministic code supplies honest data and then judges the output
for plausibility and repeatability — and refuses, rather than rewrites.**
