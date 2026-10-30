# RR_Q2 + RR_Q4: the D2 desk port, the point-in-time SEC inputs and their coverage (2026-10-30)

**Branch:** rs2 `review-2026-10/m3q` from `d2f3f15`, pushed. Commits:
- `c6da688`: `desk.py`, `facts.py` and their tests;
- `c70af98`: `inputs.py`, plus tags from the census.

**Suite:** 470 passed (`qwen_c/tests`).

## WO_Q2: `qwen_c/value/desk.py` (m3q.desk.v1)

**What was ported.** The D2 arithmetic audited at `1dcb3b2`:
- the levels leg, the year-5 wedge and the O2c state path;
- vintages D&A and the financial route;
- no sustaining charge.

**What was added:**
- the fade convention B1 = revenue (RR_Q3);
- the PV of the amortization shield left after N (an accepted requirement, PLAN_terminal_reinvestment:468);
- named refusals and no defaults.

**Parity.** Fixtures come from `terminal_d2/gen_value_fixtures.py`. On 20 cases, value and every annual flow match
`reference_d2.py` to 1e-9. The cases are:
- the 13 registered paths of the old desk test (vintages; B at H = 25, E at H = 9, C and C2 at H = 15);
- M1–M6;
- the insurer.

**Truth bar:** each case passes or fails ±3% exactly as registered. C and C2 on the default path (+7.37%, +4.53%) and M6 stay
failures.

**The kappa defect cannot occur.** No base-cash-flow scaling exists in this desk.

## WO_Q4: `qwen_c/value/facts.py` (m3q.facts.v1) and `inputs.py` (m3q.inputs.v1)

**`facts.py`:**
- companyfacts and submissions are read through `sec_store` (pinned bytes);
- a value counts only if its accession was effective by T;
- per fiscal year, the latest eligible filing and the highest-priority tag;
- ProfitLoss is reconciled to diluted EPS × shares within 1%;
- concepts that end before the latest revenue year are named stale.

**Defects found on real data and fixed systemically (not per ticker):**
- **Mastercard tags net income as `ProfitLoss` since 2014.** One-tag-per-concept left a series ending in 2013. Fix: per-year
  merge by tag priority.
- **Subtracting the noncontrolling interest from ProfitLoss** was wrong for MA, whose ProfitLoss is already attributable
  (EPS × shares 12,876 against 12,874). Fix: take the basis that reconciles with EPS, else stamp it unverified.

**`inputs.py`:** the code-owned base.
- X_0 = NI + A(1 − τ), only when the amortization schedule and the year's amortization are both filed. Otherwise X_0 = NI with
  no shield, so the two are never mixed.
- Pooled intensities, w, V8 tax, RONIC_0, δ at market weights, kd, shares and cash.
- The operating-margin bridge.

## Coverage on the 156-name census (160 less SENEA, SENEB, MOV, MG), T = 2026-10-30

| Family | Names | Valuation base ready | Main refusals |
|---|---|---|---|
| Operating | 77 | **38** | input_missing 10, tax_unavailable 9, shares 5, history_short 5, invested capital ≤ 0 5 |
| Commodity | 29 | 6 | tax_unavailable 10, facts_stale 5, history_short 3 |
| Financial | 20 | 1 | input_missing 12 (no classified balance sheet; capex) |
| Family not built | 30 | 6 | tax_unavailable 9, input_missing 6, facts_stale 4 |
| **All** | **156** | **51** | |

**What the refusals are:**
- **Financials (12 `input_missing`).** The operating base needs current assets and capex, which banks and insurers do not
  file. The financial route (O3) needs neither, but its own base (E_0, ROE_0 on book equity) is not built yet. **This is
  next.**
- **Tax (31):**
  - 11 had a loss before tax in the latest year;
  - 7 have a rate above 35% in every measured year;
  - 6 have a negative latest rate;
  - 5 file no listed tax or pretax tag.
  - *Corrected the same day:* I first called these 7 persistently high rates that a fixed band wrongly refuses. Their
    histories show otherwise: they are erratic or mostly loss years (e.g. 1.43 then 0.67; 0.73, 0.63, 0.80; −1.76, 0.43,
    0.38). Refusing them is correct.
- **Stale (13) and missing (operating 10):** tag variants not yet listed, and companies that changed tags. Each addition must
  come from a census like the one in this report.
- **Non-USD filers (6):** facts are read in USD only, so they are absent. The FX quarantine stands (PLAN_terminal_reinvestment).

## Decisions and next steps

1. **V8 band: DONE (`inputs.tax_rate`).** A persistent rate outside the band is accepted: ≥ 3 measured positive-pretax
   years, all ≥ 0, within 5 points of each other; stamped. It matches no census name today. It stays because it is the
   economically right rule, not a coverage fix.
2. **The financial base: DONE (`inputs.base_financial`).**
   - The driver is opening book equity, with ROE as the margin, so each route flow equals E_t minus the growth of book
     equity (tested).
   - Financials ready: 1/20 → **13/20**. All names ready: 51 → **63/156**.
   - Remaining financial refusals: history_short 3, stale 2, E_0 ≤ 0 2.
3. **Tag census** for pretax income, D&A and capex on the stale and missing names. Every tag added is one the census
   finds in use.
4. Coverage reported again after each step. Valuation stays diagnostic (B9), so coverage gates nothing.

## WO_Q5 part 1: `forecast.py` and `checks.py` (`39d718a`, 2026-10-30)

**What is built:**
- the filed record as `filed_record` packet items, one per fiscal year;
- rev 26's path rules;
- assembly onto the desk;
- checks V1–V4, V6, V7 and V9–V11 as WO_Q5 §2 defines them.

**Tests (13):** rev 26's recorded faults fail their own checks:
- MSGE premium without a span: V3;
- DAR adjusted basis alone: V4;
- DAC direction: V10;
- VSNT decliner: V7.

A clean output passes every check. Sanity of the clean case: value 16.7 per share on earnings of 1.0 per share at r 9% and
g_T 3%; seam ratio 1.03.

**Gap (stated, not filled): V5's withdrawn/superseded rule.** Packets carry no withdrawn or superseded marker, so V5 is
today only "cited items exist in the packet and are effective by T". Marking withdrawn guidance needs a packet field that the
builder fills from the filings (for example, a later release that withdraws an outlook). That is a builder change, so it is
versioned, and it is listed for WO_Q5b.

**Not built yet (WO_Q5b):**
- the prompt text `m3m.prompt.v4`;
- runner wiring and the one repair turn;
- `memo.py`;
- the cost-of-equity anchor port.

## WO_Q5b: the cost of equity, the prompt, the runner and the memo (2026-10-30)

| Commit | What |
|---|---|
| `caac104` | `coe.py`: max(rf, g_anchor) + adjusted loading × closure ERP. A missing leg is refused (no fallback), and a leg dated after T is refused (E2 may allow it, stamped). Live: Technology 10.27% |
| `4a6a42c` | `task.py`, prompt `m3q.prompt.v1`. SYSTEM is the shared text, byte-identical; the task is outside `tasks.TASKS`, so the formation tasks do not move. The prompt's own example passes `checks.shape`; the hash is pinned |
| `774941c` | `run.py`: code-owned preparation, then the model, the checks and one repair turn listing the failures. A no_call happens before any model call. `authority: diagnostic_only` |
| (memo) | `memo.py`: code numbers and labels; only supported reasons are printed |

**Suite:** 500 passed.

**Not done:**
- The financial route's forecast task and checks (the runner refuses `financial` by name).
- V5's withdrawn marker.
- The GPU smoke and E2. A blind Opus cross-check of the whole 3Q build comes first, per the standing rule.
