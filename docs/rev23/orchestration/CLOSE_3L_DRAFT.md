# CLOSE 3L (draft for the operator's signature): 2026-10-29

**Proposed decision: `PASS_PROSPECTIVE` for the factor stage, paper scope, *for scorings made by the data-fetch
workflow*.** Price-refresh scorings stay `PIT_PROSPECTIVE` but not replayable until CI commit `df6b4ecb` is approved.
This certifies nothing historical and nothing about Qwen. Under PLAN §3L the Qwen pack replay is a 3M gate.

## Gates

| Gate | Verdict | Record |
|---|---|---|
| L-ARCH witness preservation | **PASS**: 936 runs listed, 648+ with logs, back to 2026-07-30 | RR_L1, AUDIT_L1_L3_L4 |
| L-INV code inventory | **DONE**: the rs2 live branch was restored to `e82a08b`, and ChatGPT's 7 commits kept on a branch | RR_L2, RR_L2_partial |
| L-P2/P3 per-candidate point-in-time table | **PASS** (paper): 160/160 for run 40608600897; **79/79 dual-door runs PASS** | RR_L3 (+ addendum) |
| L-P4F deterministic replay | **PASS for data-fetch runs** (three exact replays: 09-30 GitHub-hosted, 10-05 PC, 10-28 atomic PC). **BLOCKED_OWNER for price-refresh runs** (momentum not committed). | RR_L4 (+ 2 addenda) |
| L-P1 publication pair | **PASS (paper scope)**: first post-fix output 7,012/7,012, guard ran twice. The served HTTP copy is unverified. | RR_L5 |
| L-FIX small fixes | **DONE, unpushed**: branch `review-2026-10/3l-fixes` (MRI read-once, EPS failure cache, CI alignment, UTC date in tradability) | RR_L6 |
| L-H historical | **CLOSED_UNVERIFIABLE** for forensic reads; Gate-2 FAIL, 0/163 and 0/29 unchanged | register §L-H |
| Forward record | **STARTED**: A0 formation 2026-09-30 (60 names), OPEN | RR_L7 |
| L-P5 signoff | **awaiting the operator** | this file |

## Decisions needed from the operator

1. **Sign** the 3L decision above, or return it with changes.
2. **Approve pushing `review-2026-10/3l-fixes` to `stock-screener` `main`.** It has four commits; one is a CI change
   (`price-refresh.yml` commits `daily_closes.json` and `momentum_state.json`).
3. **Optional:** a scheduled task that refreshes the witness archive and the forward ledger weekly. This is a standing
   configuration, so it is your choice.
4. **Optional:** verify the served HTTP pair by opening both JSON URLs while signed in to Vercel.

## Findings to carry forward (each systemic, none patched per ticker)

- **The scorer was not timezone-deterministic.** `tradability.scan` used the machine's *local* `date.today()`, so PC
  (KST) runs counted one day more than GitHub runs. Fixed in `e0f8d768` on the `3l-fixes` branch; awaiting push approval.
- **The MRI snapshot was absent in 26 of 79 dual-door runs.** In those runs the scorer used neutral quotas and the
  constant 10% discount rate. It was normal in the early weeks.
- **The 2026-09-30 book held 9 non-common securities** (AFG debentures and bank preferreds), a defect since fixed.
- **ChatGPT's `build_fundamentals_history.py` guard (`f99cdda5`)** was measured in RR_L8: 1,701 cells nulled across 226
  tickers, and 26 whole fiscal years dropped through a cascade. Nominations are unchanged. **HOLD**, with a change
  request: keep the years and annotate the guarded cells.
- **41 `rs2-local` tests fail identically on `e82a08b` and `f2e8543`**, so they predate the reset. Triage: almost all of
  them read the live enrichment and closure caches, which have gone stale while `DEPTH_PAUSED` is on. The packs no
  longer print the consensus-reference or cost-of-equity anchor lines (`not_available`, "closure premium missing or
  stale"), and 8 fail with `StopIteration`, finding no `CONSENSUS-IMPLIED VALUE` line. For 3M: these tests should use
  fixtures, not live caches.

Holds unchanged: `KIS_HALT`, `DEPTH_PAUSED`, `model_release_blocked=true`. No deploy, trade, model run or push was
made.
