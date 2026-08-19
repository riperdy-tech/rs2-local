# RS2 Valuation Methodology Audit — Decision Document

**Date:** 2026-08-18 · **Scope:** financial methodology + LLM stage architecture ·
**Method:** institutional-standards research (`A_institutional_checklist.md`) → bidirectional
gap analysis (`B_gap_analysis.md`) → 8 deterministic experiments on the live book
(`C_findings.md`, raw: `C_experiments/*.json`, scripts: `tools/audit_202608/`).
No pipeline file was modified; no LLM was invoked.

## 1. Executive summary

RS2 is a **well-built expectations-ranking engine** whose signals, measured against realized
30-day outcomes, all point the right way (MoS ρ +0.40, conviction +0.34, gap −0.24; BULLs
+6.0% excess vs IWM, BEARs −7.0% — descriptive, not significance-tested). Its engineering
disciplines (data-corruption gating, cross-sectional calibration, deterministic brake,
outcome ledger) exceed common institutional practice. Verdict: **refine, don't rebuild.**

The audit found exactly one **measured ranking distortion** (SBC treated as free money —
**CORRECTED 2026-08-19:** C3 overstated this by double-counting SBC on owner-earnings names,
which GAAP NI already expenses; the real defect is confined to the 45 FCF-derived names,
see C10 and the C3 correction banner in C_findings.md), one **honesty problem at the level**
(the 7–11% sector table sets every published MoS; the book's measured implied rate is ~12%),
one **pure waste** (S4's structured output is computed every run and read by nothing —
10.7% of LLM runtime), and a set of **cheap missing tripwires** (quality battery, solvency,
peer-multiple cross-check) whose measured incidence today is low because the upstream
screener already filters junk — they are insurance, not gold mines.

Two widely-expected "institutional" additions were **measured unnecessary**: a terminal-value
sanity gate (zero names above 75% TV share; median 54%) and — per C1 — chasing per-name
discount-rate precision (uniform rate error barely moves the ranking; ρ ≥ 0.995).

## 2. Effort × value chart (Phase D)

Effort: XS < 1h · S = hours · M = 1–3 sessions · L = multi-week.
Status: **PROVEN** = measured in Phase C on the live book · **LIT** = literature-supported,
not measurable with current data · **STOP** = blocked pending data/method (CLAUDE.md §0).

| # | Candidate change | Effort | Measured value (this book) | Status / evidence |
|---|---|---|---|---|
| A1 | **Deduct SBC from FCF-derived `base_cf` kinds only** — CORRECTED 2026-08-19: C3's original all-names version double-counted SBC on owner-earnings flows (GAAP NI already expenses it); scope re-proven in C10 | S — `_sbc_adjust()` in `_base_cf` + yf fallback | **MEDIUM.** 45 names affected (fcf_fallback/ocf_proxy/fcf_ttm_yf); real gap moves ATRC +38.9pts, DT +14.6, GOOG +13.4, ARGX +9.5; ANAB's all-SBC "FCF" now honest-nulls | PROVEN (C10) + STOP on retrodictive check (no historical SBC field). **APPLIED 2026-08-19** |
| A2 | **Anchor the rate level to the measured implied CoE** (`tools/implied_erp.py` → level; keep sector spreads) | S–M — one table + re-baseline | **MEDIUM.** Level honesty: median MoS −41.7% → −53.1% (truthful vs 10% folk level); ranking effect modest (ρ 0.976, 17 flips) | PROVEN level effect (C1) |
| A3 | **Load `fundamentals_battery.json`** (f_score, accruals, M-score, issuance) as verdict tripwire + prompt facts | S — file exists, RS2 just never opens it | **LOW now / insurance.** 1/35 BULLs flagged (INVA +7.4%/yr issuance); incidence rises if screener bands loosen | PROVEN incidence (C4) |
| A4 | **Solvency tripwire** (coverage <3×, net-debt/OCF >4×) from already-ingested fields | S | **LOW now / insurance.** 0/35 BULLs, 6/125 HOLDs flagged | PROVEN incidence (C5) |
| A5 | **Peer-multiple cross-check** (EV/EBIT vs sector median; disagreement flag into valuation block + tier-1 audit) | S–M | **MEDIUM.** Fully feasible from existing data; flags 8/148 (~5%) genuine conflicts incl. MU, ABNB, DT | PROVEN feasibility + flag list (C8) |
| A6 | ΔWC term in `base_cf` | M (method design) + validation | Naive 1-yr ΔWC is **noise** (43 flips incl. absurd AMD/CMI exclusions) | **STOP** — needs smoothed volume-linked estimator, then validation |
| A7 | Terminal-value sanity gate | S | **~ZERO.** No name exceeds 75% TV share (median 54%, p90 60%) | PROVEN unnecessary (C2) — **do not build** |
| A8 | Per-name CAPM / beta precision | M–L | **~ZERO for ranking.** Uniform level shifts: ρ ≥ 0.995; sector structure worth only 15 flips | PROVEN low (C1) — **do not build**; A2 captures the value |
| A9 | Variable forecast horizon (CAP) + driver-level expectations decomposition | L | Unmeasured; the highest-fidelity form of RS2's own paradigm | LIT (Rappaport/Mauboussin) — design work |
| A10 | FX ingestion for 20-F filers | M–L (upstream) | Unblocks BWMX-class names; correctness precondition | Pre-existing STOP (PLAN_FX_INGESTION_20260814.md) |
| R1 | **S4: remove** (fold the scenario ask into S5 prose, delete the structured emission) | S | **10.7% of LLM runtime** (43s/ticker) pure waste. Wiring measured NOT worthwhile (C9, added 2026-08-19): 82% of emitted prob triples are 6 templates, tilt-vs-outcome ρ +0.14 (~0 in the cheap tercile), redundant with conviction (ρ +0.32), and no deterministic scenario values exist to weight | PROVEN waste (C7) + PROVEN low information (C9) |
| R2 | **Delete stale `<15%` prompt strings** (`run_rs2.py:92, 501, 1826`) — they contradict the percentile ENTRY DISCIPLINE line in the same prompt | XS | Removes a live contradictory instruction to the model | PROVEN present (grep) |
| R3 | Fix stale brake docstring (`run_rs2.py:1113-1121`) + stale `run_rs2.py:1154` "78%" comment (measured: 4/155) + stale module docstrings (`run_rs2.py:7`, `rs2_data.py:20`) | XS | Doc-truth; the exact error class CLAUDE.md §0 memorializes | PROVEN stale (C1 + grep) |
| R4 | Retire orphans (`research_agent.py`, `AgentWebSearch-MCP/`, `Run-RS2.ps1`, `data/TEMPLATE.md`, dup `RS2 engine.txt`) + rewrite README to the post-inversion architecture | S | Removes ~70% wrong documentation; prevents future sessions acting on dead paths | PROVEN orphaned (call-site grep) |
| R5 | Trim never-used display fields from prompts (keep ones A3–A5 activate) | S | Token savings, minor; do after A3–A5 decide which fields become live | Partially proven (14 unused fields) |

## 3. Options (Phase E)

The options nest: 1 ⊂ 2 ⊂ 3.

### Option 1 — Hygiene & Tripwires (deterministic only, ~1–2 sessions)
R1(remove-path), R2, R3, R4, A3, A4 (+A5 if time allows).
- Effect: −~11% LLM runtime/ticker, zero contradictory prompt rules, quality/solvency
  insurance on every future verdict, honest docs.
- Risk: minimal. No published number changes except S4's absence (verify via `--refinal`-style
  A/B on 3 names + tier-2 pass-rate watch).
- Does NOT fix: SBC ranking distortion, MoS level honesty.

### Option 2 — Institutional Core (RECOMMENDED, ~3–5 sessions, still deterministic)
Option 1 + **A1 (SBC, corrected scope)** + **A2 (implied-ERP level)** + **A5 (comps cross-check)**.

> **STATUS 2026-08-19: APPLIED AND LIVE.** All three landed with the guardrails: full-book
> replay review in `audit/O2_replay_review.md` (166 names changed a field; 52 brake-tier
> flips; ANAB route change), implied CoE calibrated at ~12.1% → +1.7/+1.8pt level offset
> (`cache/coe_calibration.json`), sector EV/EBIT medians cached, MoS distribution rebuilt
> under the new methodology, and the continuity anchor carries a one-cycle methodology note
> so `changed_because` cannot fabricate business narratives for methodology deltas.
>
> **Correction to an earlier claim in this file's history:** sweeps were never paused —
> `cache/PAUSED` did not exist (the session-start survey reported it present and it was not
> re-verified). The 08:00 sweep of 2026-08-19 ran on the new code and published at 11:04
> (13 tickers; `[coe] implied 12.06% → +1.7pts`). The transition was then completed the same
> evening: all 290 verdicts repatched onto the new methodology (`repatch_verdicts.py`, no
> LLM) and the overlay regenerated and pushed via `tools/publish_only.py` — 172 names,
> MoS p33/p50/p75 −67.2/−54.2/−39.4, 134 HOLD / 33 BULL / 4 BEAR, conviction mean 9.7.
> Repatched rows carry old-methodology prose in FINAL.md until each name's next full run;
> the ledger's `repatched` flag marks them and the grader already accounts for it.
- Effect: fixes the one *measured* ranking distortion (~21% of tiers reseat, in the direction
  every valuation authority endorses); published MoS levels become defensible ("the median
  name prices ~12% CoE against SBC-true flows" is a statement an institution can sign);
  a ~5% disagreement tripwire catches engine malfunctions the fence no longer catches.
- Mandatory rollout guardrails (this is where the risk lives):
  1. Stage A1/A2 behind a side-by-side replay (`repatch_verdicts.py`-style) across the full
     book BEFORE going live; review the 30 SBC tier flips by hand.
  2. Rebuild `cache/mos_distribution.json` the same sweep the change lands (stale-percentile
     refusal already protects, but don't run blind).
  3. Expect continuity-anchor churn: ~20–30 names' verdicts legitimately change; the anchor
     prompt must carry "methodology change" context for one cycle, or `changed_because` will
     fabricate narratives.
  4. Log a before/after C6 snapshot so the 30d rank correlations become the regression test.
- Explicitly deferred: ΔWC (STOP), TV gate (proven unnecessary), beta precision (proven low).

### Option 3 — Full Expectations Engine (multi-week, LLM-dependent, gated)
Option 2 + the deferred LLM A/Bs (stage ablation S2/S6, S4 wiring, conviction anchoring —
specs in `C_findings.md`) + ΔWC proper estimator + historical SBC ingestion upstream
(unblocks the A1 retrodictive STOP) + FX plan execution (A10) + variable CAP (A9).
- Gate: Qwen 3.8 battery finished (GPU free) AND Option 2's C6 regression snapshot clean.
- This is the only tier that touches prompt/stage architecture, and every element of it ships
  through its own measured A/B — never on argument.

## 4. Recommendation

**Adopt Option 2, sequenced as Option 1 first** (it is a subset and de-risks the rest), with
Option 3 items entering one-by-one behind their gates. Reasoning:

1. C6 says the current stack ranks outcomes correctly — the burden of proof is on changes,
   which is why every Option 2 element is one that *measured* a distortion (A1), an honesty
   defect (A2), or a near-free tripwire (A3–A5), and why Option 3's architecture surgery
   waits for A/B capacity.
2. The two glamorous-looking upgrades the checklist would naively demand — terminal-value
   discipline and discount-rate sophistication — are exactly the two this book's data says
   not to build (C2, C1). The audit paid for itself here.
3. The single biggest measured improvement (SBC) is also the one with unambiguous
   institutional backing (Damodaran: SBC is an expense, full stop). Alignment of measurement
   and literature is as strong as evidence gets inside this repo's standard of proof.

## 5. What remains unproven (standing STOP flags)

1. Forward edge at any horizon — 30d correlations are descriptive; 91d/365d ungraded;
   significance testing impossible until months more ledger history accrues.
2. SBC retrodictive superiority — blocked on historical SBC ingestion (upstream change).
3. ΔWC estimator — method design + validation required before any adoption.
4. FX conversion — open plan, unchanged by this audit.
5. S2/S6 stage value — unmeasurable deterministically; resolved only by the deferred ablation.
