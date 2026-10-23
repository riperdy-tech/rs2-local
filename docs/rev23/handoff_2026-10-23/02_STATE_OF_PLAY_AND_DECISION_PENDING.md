# 02. State of play (2026-10-23) and the decision the operator must make

## 1. The evidence, all in one place

Every component of the planned system has now been measured. None has a demonstrated edge:

| Component | What was measured | Result | Source |
|---|---|---|---|
| AI analyst, long-run valuation (revision 26) | 4 iterations on 12 names; two blind readers; registered pass bar | **FAIL**: coherent 1/9 (it3) and 0/9 (it4); 0 incoherent; spread and direction passed; never loops, never copies, no anchoring | file 05 §2-5 |
| Code valuation engine (gate 1, 10-07..09) | point-in-time holdout 2023-24; gate 1b on 2025 | Gate 1 holdout **failed**; gate 1b's edge was value and size style, about 0 incremental in 2022-2025; code revenue forecasts no better than the population median; ROTE forecasts have a real edge | `SPEC_rebuild.md` addenda T-AB; file 05 §9 |
| The 25.2 desk arithmetic | offline re-valuation of iteration 3 forecasts | **Defect**: kappa scales years 1-5 but not the long run (year-6 cash-flow jump); DAR −48% when removed; tax clipped; positive terminal growth for a decliner | file 05 §7 |
| The screener (baseline A) | production screener replayed point in time 2017-2025 | **Factor tilt, no alpha**: factor-controlled alpha −0.1% over the window; −1.9% in 2017-22; +13.4% (t 3.2) only in 2023-24; turnover 3.2×/yr; fails the project's bar | file 05 §8; `scratch/baselineA/REPORT_baselineA.md` |
| AI monitoring (Phase 6, Muse Glimmer) | constructed and real-event tests | Constructed thesis breaks 36/36; **real past events 6/20 strictly (8/20 manual) vs 18/20 target**; Qwen's monitoring unmeasured | `PHASE_6_FOLLOWUP.md`, STATUS.md |
| Qwen 3.8 knowledge cutoff | probe of dated events | **About mid-April 2025** (band 2025-02..06); AI rungs can be tested historically only from 2025-10 | `scratch/qwen_cutoff/REPORT_cutoff.md` |

## 2. What is frozen

- **Revision 26 at pack revision 28** (rs2 `1484ea2`; desk diagnostics added post-freeze in `c255803`), status **paper-only, low confidence**.
- The 4-name holdout (CTVA, NHC, TTAM, CLDT) is **untouched** and must stay so until a design worth spending it on exists.
- Both iteration 3 and iteration 4 records are kept (`pilot_r25/runs_p4r26/3`, `/4`).

## 3. What is drafted

`rev23/SPEC_factor_led_v1.md` (draft v1, pushed): a factor-led, AI-supervised design:
- the screener selects (primary), Python enforces risk and **deterministic exits**, Qwen does four bounded jobs (business interpretation, risk discovery,
  change detection, focused research) with **no unconditional veto** (verified hard stop → registered restriction; uncertain concern → escalation with a
  bounded buy pause; silence is not a signal), valuation is **diagnostic** until it earns authority;
- an A→E test ladder (A screener; B + deterministic risk; C + AI risk investigation; D + AI forecasts; E + valuation), each judged on incremental value;
- a contamination rule (AI rungs on dates after Qwen's cutoff, i.e. from 2025-10, or prospectively).

It was written **before** baseline A came back. Baseline A weakens its premise: the screener is not proven as a primary engine either. The spec has not
been cross-checked by ChatGPT/Gemini yet (the operator was going to run that).

## 4. THE DECISION PENDING (ask the operator)

The coordinator's last message to the operator presented three paths and a recommendation. The operator has not answered yet (they asked for this
handoff instead). Present them again:

1. **A cheap factor fund, deliberately.** Run the screener as a disciplined value/quality/momentum tilt with much lower turnover (quarterly
   rebalance, wider bands). Use the AI only for verified hard stops (pending all-cash deals, going concern, restatements) and for explaining holdings.
   Expect market-like returns with factor exposure. Honest and runnable soon.
2. **Search for a real edge first.** Test what the AI might add on post-cutoff dates (2025-10 on) and prospectively: the risk-discovery and
   change-detection rungs. Keep the factor fund on paper meanwhile. Promote the AI only if it measurably cuts losers without excluding winners.
3. **Re-examine the screener design.** Why did 2023-24 work? Is momentum doing the work? Can turnover come down without losing it? (Quant research, no
   GPU, but risks fitting to one period.)

**The coordinator's recommendation: 1 and 2 together.** Set up the low-turnover factor version on paper as the honest baseline; spend the AI effort on
the narrow, testable roles (hard stops, risk discovery, change detection) on post-cutoff and live data; treat real money as a later decision on the
paper record, never on any benchmark so far. The coordinator also offered to write this up as a cross-check for ChatGPT and Gemini first.

Also pending from the operator:
- **The D2 fade ruling** (needed to fix the kappa / year-6 desk inconsistency properly): when margins move during the fade, does the reinvestment charge
  follow revenue growth or earnings growth? (They differ by about ±20%.) See file 07 §3.
- **The materiality threshold** for D2 inputs ("I will decide % after all the recovery work is done").
- Whether to cross-check `SPEC_factor_led_v1.md` (likely after rewriting it for baseline A).

## 5. Nothing is running

At the time of writing: no GPU job, no pilot task running (the `RS2-P4-R26-*` tasks are "Ready" with no next run, except `RS2-P4-R26-IT3` whose
dummy start boundary is 2027-01-01, i.e. it only runs when started manually). Builders/agents: none running. The MRI session (another Claude
session) has its own daily tasks (`MRI-Local-Daily` 06:30, `MRI-Events-Daily` 13:00) that briefly lock the MRI DuckDB store.
