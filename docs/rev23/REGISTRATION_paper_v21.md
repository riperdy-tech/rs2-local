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

## Amendment AK.91 (2026-10-15 16:39): the selection rule changes before the first publication (cross-check 17, option D)

**Disclosure:**
- This amendment was made **after inspecting the first live night's signal** (2026-10-14). Under the original rule (section 3.3) the book held
  122 names, of which 121 were financial. The cause is the engine's level by family: the operating median IV/price is 0.53 and the
  financial median is 1.49.
- **No paper row had been published, and no paper return exists.**
- Both outside reviewers (Gemini, ChatGPT) independently recommended this design.

**Governing from now (it replaces section 3.3; every other rule stands):**
1. **Eligible:** every paper-actionable valued row (section 3.1–3.2), **whatever its direction** (hold, overvalued, undervalued). The level
   defect must not decide who enters.
2. **Peer groups:** family × Damodaran industry (`discount.sources.industry`). A group with fewer than 10 eligible names joins its family's pool.
   Families are never pooled together.
3. **Score:** median_iv / price; ties broken by mean_iv / price, then ticker. The percentile is (rank − 0.5) / n within the peer group.
4. **`rn_v4` (the primary book):**
   - holds the **top decile** (percentile ≥ 0.90) of each peer group, a held name kept while ≥ 0.85 (a turnover buffer);
   - the screener's factor-rank and veto filters apply;
   - equal weight over max(count, 8).
5. **`rn_v4_low` (comparison):** the bottom decile (≤ 0.10, kept while ≤ 0.15), on the same mechanics.
6. **`rn_v4_abs` (audit):** the original rule (undervalued and paper-actionable), unchanged, published beside the others in every report.
7. **The primary measure** (replacing section 4's): the monthly top-minus-bottom return spread (`rn_v4` − `rn_v4_low`).
   - Newey–West t ≥ 2 over the 12-month window to call it positive; otherwise inconclusive.
   - `rn_v4` against IWM and against the `equal` control is reported as the practical portfolio diagnostic.
   - The spread is also reported **separately for operating and financial**.
8. **The top sleeve is a "top relative-score cohort", not a set of "undervalued stocks".** With the operating level about 0.5×, even its top
   decile may sit below price.
9. **Logged per position,** for later attribution: family, industry, size, the discount spread, the distance from the family prior, and the
   value-factor rank.
10. **Any later methodology change starts a separately identified prospective experiment.** It never replaces or overwrites this one.
