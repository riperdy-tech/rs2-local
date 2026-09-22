# Phase A — Institutional Equity-Valuation Checklist

**Purpose:** the reference standard against which RS2 is audited in Phase B. Built from web
research 2026-08-18. Each item: what it is, why institutions require it, and the failure mode of
omitting it. Tiers: **MUST-HAVE** (no credible intrinsic-valuation process omits it),
**GOOD-TO-HAVE** (adds accuracy/robustness, commonly present at quality shops), **SITUATIONAL**
(required only for certain company types), **COMMONLY-OVERRATED** (widely done, weak evidence of
value for a screening-tier system).

Calibration note: the standard applied here is "systematic process that feeds a screener /
portfolio strategy" (RS2's actual job), not "bespoke deal memo". Where the two standards diverge,
both are stated.

---

## 1. MUST-HAVE

### 1.1 A defensible discount rate with a stated construction
- **Standard:** cost of capital built from observable parts: risk-free rate + equity risk premium
  (× beta or a risk proxy). Damodaran's practice — the de-facto reference — is a **monthly
  market-implied ERP** (back-solving the discount rate from index level + consensus cash flows),
  precisely so valuations are market-neutral rather than anchored to a folk constant. A 1–2pt ERP
  error moves a DCF value 20–30%, making the discount rate the single most powerful lever in the
  model.
- **Consistency rule (non-negotiable):** levered (equity) cash flows ⇒ cost of equity ⇒ compare to
  market cap; unlevered flows ⇒ WACC ⇒ compare to EV. Mixing frames double-counts the debt claim
  (RS2 learned this empirically on 2026-08-07, CLAUDE.md §0).
- **Failure mode of omission:** every MoS in the book is leveled by an unaudited constant; the
  system can only rank, never state whether anything is actually cheap.
- Sources: [Damodaran ERP 2026 edition (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6361419),
  [Damodaran blog: The Price of Risk](https://aswathdamodaran.blogspot.com/2026/03/the-price-of-risk-equity-risk-premium.html),
  [Damodaran ch. 8, risk parameters](https://pages.stern.nyu.edu/~adamodar/pdfiles/valn2ed/ch8.pdf).
  Note: his historical implied-ERP table page is stale (ends 2016); the live monthly number is in
  the spreadsheets on his data page — pull at implementation time.

### 1.2 Terminal-value discipline
- **Standard:** terminal g ≤ long-run nominal GDP (2–3%); TV typically 60–80% of PV — which is
  exactly why institutions **sanity-check it**: (a) cross-check perpetuity-growth TV against an
  implied exit multiple (both methods side-by-side is standard banker practice), (b) flag names
  where TV dominates PV, (c) normalize the terminal-year flow to mid-cycle before capitalizing
  (McKinsey).
- **Failure mode:** a hard-coded terminal g with no TV-share telemetry means most of every fair
  value is set by an unexamined assumption.
- Sources: [Wall Street Prep, terminal value](https://www.wallstreetprep.com/knowledge/terminal-value/),
  [Wall Street Prep, common DCF errors](https://www.wallstreetprep.com/knowledge/common-errors-in-dcf-models/),
  [CBV Institute TV best practices](https://cbvinstitute.com/wp-content/uploads/2024/06/4.-Terminal-Value_Best-Practices.pdf).

### 1.3 A correctly defined cash flow for the frame chosen
- **Standard:** Buffett's owner earnings (1986) = NI + D&A + other non-cash − **maintenance**
  capex − **incremental working capital** required to sustain volume. Two elements matter at
  institutional grade: the maintenance-vs-growth capex split (Greenwald's PPE/sales method is the
  canonical estimator) and the ΔWC term.
- **SBC:** Damodaran's position is unambiguous — SBC is a real expense; do **not** add it back to
  cash flow ("a barter system to evade the cash flow effect"). Banker practice of adding it back is
  a documented error. Either expense future SBC in the flow or haircut equity value for expected
  dilution; doing neither overstates value for SBC-heavy names systematically.
- **Failure mode:** total-capex owner earnings punishes growth builders (the AMZN problem RS2
  already documented); ignoring SBC inflates tech/growth fair values.
- Sources: [Buffett owner earnings, 1986 letter summary](https://www.oldschoolvalue.com/stock-valuation/what-is-owner-earnings/),
  [Greenwald maintenance-capex method](https://janav.wordpress.com/2015/07/08/calculating-maintenance-capital-expenditure/),
  [Damodaran on dilution/options](https://pages.stern.nyu.edu/~adamodar/pdfiles/blog/TeslaDilution.pdf),
  [SBC in DCF discussion](https://www.graduatetutor.com/corporate-finance-tutoring/other-valuation-topics/how-do-you-deal-with-stock-based-compensation-in-your-dcf-valuation-model/).

### 1.4 Earnings-quality screen (accruals) before trusting any earnings-based value
- **Standard:** the accruals anomaly (Sloan 1996) — a large gap between earnings and operating
  cash flow predicts both lower forward returns (high-single-digit annual spread) and
  manipulation risk; it is the strongest single statistical predictor of earnings manipulation.
  Institutional processes run at minimum an accruals ratio / CFO-vs-NI check; fuller batteries add
  Piotroski F-score (high-F minus low-F historical spread ~23%/yr in the original study) and
  Beneish M-score.
- **Failure mode:** the DCF capitalizes earnings that cash flow says aren't real; classic value-trap
  entry point.
- Sources: [CFA UK, evolution of fundamental scoring models](https://www.cfauk.org/pi-listing/man-machine-the-evolution-of-fundamental-scoring-models-and-ml-implications),
  [Piotroski F-score overview](https://en.wikipedia.org/wiki/Piotroski_F-score),
  [GMT Research on F-score](https://www.gmtresearch.com/en/accounting-ratio/piotroskis-f-score/),
  [Beneish M-score](https://marketxls.com/blog/beneish-m-score).

### 1.5 Balance-sheet / solvency gate
- **Standard:** before sizing into anything "cheap", confirm it can survive: leverage, interest
  coverage, liquidity — or a composite (Altman Z, ~80–90% one-year-ahead bankruptcy accuracy;
  Z < 1.81 = distress). Quality-factor literature (AQR QMJ) includes **safety (low leverage)** as a
  priced component. This is a *gate*, not a valuation input.
- **Failure mode:** a leveraged melting ice cube screens as the cheapest name in the book; the
  system's most confident BUY is its most likely zero.
- Sources: [AQR Quality Minus Junk](https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk),
  [Altman Z-score reference](https://www.gurufocus.com/term/zscore).

### 1.6 A second, independent valuation lens (relative valuation cross-check)
- **Standard:** no institution publishes a single-method value. The football-field convention
  exists because triangulation is the error-detection mechanism: when DCF and peer multiples
  diverge, the divergence itself is the signal (bad assumptions or genuine mispricing). Forward
  multiples primary, trailing as cross-check. Empirically, EBITDA multiples are **as accurate as
  DCF** for target prices, and analyst target accuracy is largely method-independent — the value
  of the second method is error-catching, not precision.
- **Failure mode:** a DCF wrong by construction (bad base_cf, bad rate) has no tripwire.
- Sources: [Football field practice](https://www.fe.training/free-resources/valuation/football-field/),
  [DCF + comps practitioner guide](https://ryanoconnellfinance.com/dcf-valuation-multiples/),
  [Analysts' accuracy: do valuation methods matter? (EFMA)](https://www.efmaefm.org/0efmameetings/efma%20annual%20meetings/2013-Reading/papers/EFMA2013_0396_fullpaper.pdf).

### 1.7 Model-company fit
- **Standard:** CFA framework: the valuation model must fit the company's characteristics and data
  quality — DDM/residual-income or P/B-ROE for financials, NAV for asset plays, rNPV for
  pre-revenue biotech, normalized mid-cycle earnings for cyclicals. (RS2 already routes this way —
  this item validates the *existence* of routing, Phase B checks the routes.)
- Sources: [CFA equity valuation process](https://analystprep.com/study-notes/cfa-level-2/the-valuation-process/),
  [CFA model categories](https://analystprep.com/cfa-level-1-exam/equity/major-categories-equity-valuation-models/).

### 1.8 Sensitivity awareness
- **Standard:** CFA/McKinsey both require knowing how the output moves per unit of input error
  (rate ±1pt, growth ±1pt, terminal g). Not scenario theater — a derivative check that tells you
  which names' values are assumption-fragile.
- **Failure mode:** treating a knife-edge fair value and a robust one as equally actionable.

---

## 2. GOOD-TO-HAVE

### 2.1 Expectations-investing decomposition done fully (RS2's own paradigm)
Rappaport/Mauboussin's process is 3 steps: (1) read price-implied expectations via long-horizon
DCF — RS2 does this; (2) apply competitive-strategy analysis to judge *where revisions will come
from* (the value driver: sales growth, margins, or investment efficiency — not just a single
growth scalar); (3) buy/sell on expected expectations revisions. A faithful implementation also
treats the **competitive advantage period / forecast horizon as a variable** (market-implied CAP
clusters 5–15y; RS2 hard-codes 10y for everyone). Upgrading toward driver-level decomposition and
variable CAP is the highest-fidelity version of what RS2 already is.
Sources: [Expectations Investing (Columbia UP)](https://cup.columbia.edu/book/expectations-investing/9780231554848/),
[CFA Institute review](https://rpc.cfainstitute.org/blogs/enterprising-investor/2022/book-review-expectations-investing),
[Mauboussin on the process](https://acquirersmultiple.com/2021/10/__trashed/).

### 2.2 Base rates for growth fade
Forecast growth against the empirical distribution of realized growth for comparable delivered
levels (Mauboussin base rates). **RS2 already has this** (GROWTH_PERSISTENCE, n=3,115
ticker-years) — noted so Phase B credits it; extending below the 15% delivered floor is the
enhancement.

### 2.3 Scenario-weighted value (only if actually consumed)
Bear/base/bull with probabilities → expected value and a range, feeding sizing. Institutional
practice at research shops; Klarman's conservative-scenario discipline is the value-investing
version. The institutional point is the *range informing the decision*, not the ritual of
emitting probabilities. (RS2 currently collects S4 probabilities and reads them nowhere — worse
than not having them: pure cost.)

### 2.4 Quality/moat quantification alongside the qualitative read
AQR QMJ: profitability, growth stability, safety are priced; Greenblatt: ROC × earnings yield
outperformed either alone. A numeric ROIC (or gross-profits-on-assets) spread vs cost of capital,
computed deterministically, disciplines the LLM's moat prose and feeds conviction scoring with
something falsifiable.
Sources: [QMJ paper](http://www.econ.yale.edu/~shiller/behfin/2013_04-10/asness-frazzini-pedersen.pdf),
[Magic formula metrics](https://www.gurufocus.com/tutorial/article/57/greenblatts-earnings-yield-and-return-on-capital).

### 2.5 Position sizing with fractional Kelly (if Kelly at all)
Full Kelly is hypersensitive to edge-estimation error and assumes independent bets; practitioner
norm is 0.25–0.5× Kelly. If RS2 keeps Kelly language in S5, it should be explicitly fractional
and correlation-aware, or replaced by simple conviction-tiered caps (which the brake already
implements deterministically).
Sources: [Kelly criticisms and fractional practice](https://astuteinvestorscalculus.com/kelly-criterion-position-sizing/),
[estimation risk in Kelly (arXiv)](https://arxiv.org/pdf/2508.18868).

### 2.6 Calibration/outcome feedback loop
Not classical sell-side practice, but the quant-institutional standard: score predictions against
outcomes, name-weighted, with honest significance disclaimers. **RS2 already has this** (verdict
ledger + grader) — credited in Phase B; the enhancement is pre-registered evaluation horizons and
eventually significance testing when history allows.

---

## 3. SITUATIONAL

- **FX translation** for foreign filers (statements in local currency vs USD quote) — mandatory
  for the 20-F names RS2 covers; already an open flagged plan (PLAN_FX_INGESTION_20260814.md).
- **Dilution modeling beyond SBC** — options/converts overhang; material for small caps and
  biotech (RS2's rNPV path already models financing dilution; nothing else does).
- **Normalized tax rate** — matters where current tax provision is distorted (NOLs, one-offs);
  institutions normalize to statutory/steady-state in terminal years.
- **Industry-specific value drivers** (same-store sales, combined ratio, FFO/AFFO for REITs —
  RS2's FFO route exists; AFFO = FFO − maintenance capex is the stricter standard).
- **Country risk premium** for EM-exposed names (Damodaran adds CRP to CoE; relevant to TIGO, VTEX
  class of names).

---

## 4. COMMONLY-OVERRATED (deliberately not recommended for RS2)

- **Quarterly-precision 3-statement forecast models.** Deal-memo apparatus; empirically does not
  improve target accuracy vs simpler driver models, and is unbuildable/unmaintainable across 259
  names. The literature finding that method choice barely affects analyst accuracy cuts both ways:
  added model complexity ≠ added accuracy.
- **Precise beta estimation.** Regression betas are noisy (Damodaran himself prefers sector
  betas); chasing per-name beta precision for a screening system is effort without measurable
  payoff. A sector-level risk proxy with a market-anchored level (implied ERP) captures most of
  the value.
- **Exit-multiple terminal values as primary.** Embeds relative valuation inside the "intrinsic"
  number; acceptable only as the cross-check (see 1.2).
- **Monte Carlo valuation distributions.** Institutional adoption is thin outside real options;
  scenario ranges (2.3) deliver the decision value at a fraction of the machinery.
- **NAV-based targets for operating companies** — the one method the accuracy literature flags as
  systematically *less* accurate.

---

## 5. The standard RS2 should be held to

RS2 is a **screening-tier expectations engine**: its job is to rank a 259-name book and gate
entries, feeding a portfolio strategy. The audit standard is therefore:

1. Every MUST-HAVE either present, or absent with a measured argument that its absence does not
   distort the ranking (not just the level).
2. GOOD-TO-HAVEs adopted where the deterministic data already supports them (several are nearly
   free: the quality battery exists upstream; ROIC is computable from ingested fields).
3. SITUATIONALs implemented for the populations actually in the book (FX names are in the book
   today).
4. Nothing from the OVERRATED tier added — sophistication is not the target; measured accuracy is.
