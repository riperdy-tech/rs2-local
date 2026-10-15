# Registration: the v2.1 paper book (rn_v4). A diagnostic only, never a promotion route.

**Status:** APPROVED by the operator 2026-10-15 13:52 (AK.88). Formerly a draft for the operator's approval (SPEC_rebuild AK.84–AK.86; cross-check 15, rulings in AK.86). Written before the first
publication of any paper-book row. **Fixed from approval on;** any change afterwards is a dated amendment that applies only forward.

## 1. What it is, and what it can never be
- **What it is:** a no-money paper ledger, `rn_v4`, trading engine v2.1's nightly shadow verdicts. v2.1 **failed** gate 2b v3 (AK.82) and is
  **unpromoted**.
- **Purpose:** diagnostic evidence on the operating pipeline and on the economic behaviour of v2.1's value signal.
- **Never a promotion route.** The paper record can never promote v2.1, and never substitutes for a failed or outstanding validation gate
  (gate-2b tracks 1 and 2, B4, the fiscal-year-2 calibration, D1–D10, the WACC correction). A favourable interval does not allow early promotion.
- **Isolation:**
  - its own ledger, `rn_v4`, never `rn_depth`;
  - `kis/targets.py` `PAPER_ONLY_LEDGERS` refuses it;
  - its own data file, `v4_paper_overlay.json`, never `depth_overlay.json`;
  - `PROMOTED_SYSTEM_FREEZE` stays None, so no v4 row is actionable on any production path.

## 2. The engine and its inputs
- **The engine:** v2.1, manifest `ENGINE_V2_1_FREEZE.json`, sha256 `2908cf71077736b595267ac90c723657f1fe4bee60ab7e53b1715b96f9d2a58e`.
  - Every row carries `versions` (the engine, the tables, the runner version and commit, `system_freeze`).
  - A row whose engine files differ from the manifest is refused before the ledger.
- **The producer:** `shadow_v4.py`, nightly at 07:30 KST, valuing the whole gate universe at the latest US close (`asof`) through the live
  runner.
- **Snapshots:** every night's shadow ledger rows and paper overlay are kept immutably (append-only ledger; dated run folders, never deleted).
  The record must be reproducible from them.

## 3. The construction rule
1. **Paper-actionable row:** producer `status` ok; a direction; the gate's reasons exactly {`pre_valid_analyst`}. Every other gate reason
   blocks: stale inputs, implausible level, instability, and so on.
2. **The discount-spread rule (AK.86 3):**
   - excluded when the discount rate (operating WACC; financial cost of equity) lies within **2 points** of terminal growth, or the spread is
     unknown;
   - excluded rows stay in the shadow ledger, annotated `paper_exclusion`, and every report counts them.
3. **Targets:** the screener's `depth_targets` rule, the same as `rn_depth`. Names that are factor-ranked, not vetoed, `undervalued` and
   paper-actionable are held at equal weight over max(count, 8), with cash as the residual.
4. **Execution:**
   - the screener's post-close paper run (weekdays 21:05 UTC) reads the published overlay;
   - a verdict for `asof` T, produced about 22:30 UTC, trades at the close of the **next** US session, T+1;
   - costs are 25 bps per side (`COST_BPS`);
   - dividends and corporate actions as the existing paper engine handles them;
   - a held name missing from the file is held, not sold, as for `rn_gemini`.
5. **Every signal is kept:** each night's eligible, excluded, abstained and refused rows are logged with reasons. No position is dropped from the
   record afterwards.

## 4. The observation window and reading
- **The primary window:** 12 full months from the first published paper overlay. **Monitoring is monthly**, describing what happened and
  deciding nothing.
- **The primary measure:** the ledger's net return against **IWM** (the paper engine's primary benchmark) over the window. Also:
  - against SPY and the `equal` control ledger;
  - drawdown, turnover, concentration;
  - hit rate by `discount_spread` decile and by distance from the family prior (Gemini's contamination decomposition).
- **Matched comparison** (ChatGPT): a v1 paper arm through the same shadow, rules and mechanics. It is built as soon as practical, and compared
  over the common window only, with its start date stated.
- **Inference:** the monthly excess return's mean, with a Newey–West t-statistic (lag 3).
  - "Positive" only if t ≥ 2 over the full window. Otherwise the result is reported as **inconclusive**.
  - There is no extension, shortening or extra look beyond this schedule.
- **Reported always:**
  - coverage: valued, abstained, refused, excluded by spread;
  - pipeline reliability: nights run, failed or held;
  - stale inputs and K fall-backs (expected 0);
  - the reconciliation of paper trades to overlay rows.

## 5. What ends or changes it
- **The paper book stops** if:
  - the producer's engine changes (a new frozen version starts a new ledger; this one is closed, not merged);
  - an isolation check fails (any `rn_v4` weight reaching a KIS target);
  - the operator rules so.
- **A coordinator audit** (a reconciliation of paper trades to the overlay rows) runs monthly, and before any report that cites the record.
