# SPEC 3S: prospective paper portfolio trial, draft v0, 2026-10-29

**Status:** DRAFT. **Authority:** paper only. It needs no broker, no deployment and no schedule beyond those the
operator approves (OPERATOR_DECISIONS C3).
**Linked:** PLAN §3S; SPEC_m3o (the arms and the engine); SPEC_m3p (monitoring); RR_L7 (the A0 forward ledger).

## 0. What already exists, and what is missing

| PLAN §3S item | Exists | Missing |
|---|---|---|
| 1. Immutable forward-only paper book | F (A0) since 2026-09-30: `m3l_forward/forward_ledger.py`, append-only. FB, FQ and FQ_decisions_only from 2026-10-30: `m3o_engine.py`, append-only with the stop rule | Nothing for the books themselves |
| 2. Freeze each recommendation, analysis, risk judgment and action before outcomes | The WO_O2 map hash is logged before the fill. Run manifests carry sha256 hashes. Ledger lines carry input hashes | **An external witness for the freeze time.** Today the "before the fill" proof is the LOG line (a self-claim). Fix: commit the frozen map hash to a git remote (the public records branch) before the fill. GitHub's push time is then a witness (PLAN W.4) |
| 3. SPY, the investable universe, factor-only references | SPY in marks; F is the factor-only reference | **An equal-weight universe benchmark:** the screener universe at each formation (`stocks.json` at the decision commit), equal weight, the same fills and costs |
| 4. Fills, bid/ask and costs | Adjusted-open fills; 0, 20 and 60 bp round trip | **A spread-sensitivity row:** half-spread estimated from daily high/low (Corwin–Schultz) per name, reported beside the flat bp scenarios. It is reported, not used to tune |
| 5. Rising, falling, volatile and event-heavy conditions | — | **A regime tag per period:** SPY return sign, VIX quartile from FRED, and the 3P event count. Reported by tag once there are ≥ 3 periods per tag; before that, "too few" |
| 6. Pre- and post-change records separate; history never rewritten | Ledger append-only; `shadow_pre_3N_close` / `paper_post_3N` labels; PREREG versions | **A change register:** every version bump of code, prompt, builder or rule, with the first formation it applies to. The marks report series per version segment |
| 7. Completion rate, freshness, model failure, alert accuracy, reanalysis latency | Engine Qwen operations fields; 3P journal measures | **A monthly operating report** (`m3s_report.py`) that joins them, with outages (GPU busy, task failures) from the run logs |
| 8. No premature skill claims | `not_yet_validated` in marks; factor-adjusted results `not_estimable` below 12 months | A pre-registered **minimum record** before any skill statement: 12 monthly formations and at least one period with SPY down 5% or more. Below it, the report says "insufficient duration" |

## 1. Pass criteria mapping (PLAN §3S)

| PLAN criterion | Evidence |
|---|---|
| Auditable operating period and outages recorded | The monthly report plus the change register; GitHub witness for the freeze times |
| All eligible formal deep analyses require Qwen | FQ entries audited by `m3o_audit.py` (no factor-only fill in FQ) |
| Every paper decision reproducible | The engine recomputes every stored line (the stop rule); packets replay byte-identically (qwen_c `replay`) |
| Matched, after-cost comparisons | Engine marks: F, FB, FQ and FQ_decisions_only on the same fills and costs, plus the universe benchmark (to build) |
| Insufficient duration reported | The minimum-record rule above |

## 2. Work orders (proposed)

- **WO_S1:** the universe benchmark and the spread-sensitivity row in the engine's marks. No GPU.
- **WO_S2:** the change register and the regime tags. No GPU.
- **WO_S3:** `m3s_report.py`, the monthly operating report. No GPU.
- **WO_S4:** the GitHub witness for freeze times. Push the frozen map hash to the records branch before each fill. This
  is a push to the public repo, and it contains hashes only.
