# Plan: the terminal reinvestment fix (design D2)

*2026-10-18. Answers `PROBLEM_STATEMENT_terminal_reinvestment.md` after the Gemini and ChatGPT reviews. A plan, not an implementation.
Nothing here is built or registered yet.*

**Operator rulings, 2026-10-18:** O1–O6 approved as recommended (O2: the wedge fades over the analyst's F). Steps 0 and 1a authorized; the work continues through step 7, then the GPU runs go back to the Phase 4 stage 0.1 session.

## 1. Verdict

Design D is not approved as written. Both reviews reject its sustaining-reinvestment term, ρ_sust = ρ_hist − g_hist / RONIC_hist,
and they are right. Its numerator holds working capital (which needs no reinvestment at zero growth), its g_hist is a revenue CAGR
inflated by oil prices, and in the offline test it rests on one base year. Equinor's −52.7% is the output of that noise, not a measurement.

What survives from D: one reinvestment model for the whole forecast, a smooth year-6 seam, and diagnostics instead of gates.
What replaces ρ_sust: a sustaining charge that is **measured from reserve disclosures, or not applied** (flagged instead).

## 2. Rulings on the reviews

| # | Point | Source | Ruling |
|---|---|---|---|
| 1 | ρ_sust residual is invalid in production; keep it only as a diagnostic | both | **Accept.** |
| 2 | ΔNWC does not belong in a zero-growth sustaining term | Gemini | **Accept.** |
| 3 | Revenue CAGR must not stand in for earnings or volume growth; average ROIC is not marginal ROIC | both | **Accept.** |
| 4 | ρ_5 is not the analyst's measured reinvestment: E_5 = E5_cons × OE_5/OE5_cons fixes OE_5/E_5 at the consensus ratio (the rev25 bridge fixes it at κ = base_cf/E_0) | Gemini; ChatGPT ("call it rho_5_bridge") | **Accept as fact.** ρ_5 is a boundary condition, and is renamed `rho_5_bridge`. Making explicit-year reinvestment respond to the analyst's growth is a separate change to the just-registered rev25 explicit years; it is recorded, not done here. |
| 5 | Negative ρ_5 means only Flow_5 > E_5, not "unsustainable" | ChatGPT | **Accept.** This corrects our own problem statement (6a, third bullet). Keep the number, request a reason when material. |
| 6 | Financials must not run capex − D&A in years 1–5 | both | **Accept.** MCY's ρ_5 = −0.03 is an artefact of the operating formula. |
| 7 | Depleting classification from reserve disclosures, not SIC | both | **Accept**, with a simplification: the ASC 932 supplementary tables are upstream-only by construction, so an integrated oil needs no segment scaling when S is computed from them. |
| 8 | Separate the zero-growth sustaining charge from growth reinvestment: Flow = Ẽ (1 − g/RONIC), Ẽ = E − S | Gemini (κ_T), ChatGPT (s_T) | **Accept.** Multiplicative and additive forms are the same thing once RONIC is defined on Ẽ; we use Ẽ. |
| 9 | Synthetic firms with a known long-horizon value as the main test; no fitting to prices | both | **Accept.** |
| 10 | Charge only (1 − λ) of net capex, λ the target debt share | Gemini | **Revised 2026-10-18 (see §2a): accept, with λ measured, not targeted.** First ruling was "reject: the fixed-dollar-debt convention is consistent". It is consistent arithmetically, but it discounts all-equity-funded growth at a levered k_e, and the error scales with growth × leverage. Small for the 8 test names; large for the book's utilities, charter-backed shipowners, IFRS-lease airlines and REITs, which fund most growth with debt. Desk-wide: equity reinvestment = (1 − δ) × net reinvestment, δ = measured net debt / (net debt + market capitalization) at the base year, 0 for net cash (market weights: book equity is unstable after buybacks, MSGE's book δ is 0.84 against 0.06 at market); the analyst keeps choosing a return on capital, and code converts it to a return on incremental equity, ROE = ROC + δ/(1−δ) × (ROC − k_d(1 − t)) (Damodaran), with k_d and t measured. |
| 11 | Apply an inflation depreciation lag, D&A × [πL/(1−e^(−πL)) − 1], to all PP&E as a sustaining charge | Gemini | **Reject.** It double counts. In steady state with nominal growth g, capex − D&A = ΔNet PP&E = g × IC, which is exactly E × g/ROIC_book. The value-driver formula already charges the inflation lag when RONIC is a nominal return on book capital. The identity stays as a diagnostic (how much of capex/D&A steady-state growth explains); synthetic firm A in §5 tests it. |
| 12 | Fade the capex wedge over min(F, 5) years | Gemini | **Not adopted as the default.** 5 is as arbitrary as any number. Default is the analyst's own F; the 5-year version is reported as a sensitivity. Operator decision O2. |
| 13 | Linear fade is a convention, not an identity; report sensitivity | ChatGPT | **Accept.** |
| 14 | Strip acquired-intangible amortization from earnings | Gemini | **Already done.** The desk's E is X, net income before acquired-intangible amortization (`consensus_reference.py`, base_ni). BUD's gap is not explained by it. |
| 15 | Gemini's Equinor figures (L ≈ 8, renewables capex, ρ_sust ≈ 0.15) | Gemini | **Not used.** Unverified, and the method behind them is rejected (row 11). |

**A defect neither review named, to verify first:** leases. Under IFRS 16 (BUD and Equinor file IFRS) and for US finance leases, D&A
includes depreciation of right-of-use assets while the lease principal is paid in financing, outside capex. Then base_cf =
NI + D&A − capex overstates owner earnings by the principal payments, in exactly the "D&A above capex" companies the problem statement
flags (BUD, MSGE, plausibly PACS). A grep of the pack builders finds no lease handling. This is an engine-wide input defect, not a terminal
question, and could be the largest correction in the set.

## 2a. The whole book, not the 8 test names

Mapped against the 160-name census of 2026-10-06 (`scratch/rev23/census_book.json`; the book drifts, so step 1a re-measures it).
Financials and miners are not the only exceptions. The cases fall in three groups.

**A different equation (a route of its own):**

| Case | Book names (census) | Why D2's operating form fails | Treatment |
|---|---|---|---|
| Financials | 22 classed financial: banks (CTBI, STT), lenders (BFH, ECPG, JCAP, PGY), brokers (OPY, TOP), insurers (MCY, ALL, RNR, ARX, UVE, HRTG, HG, AII, ACIC, UFCS, WTM, SLDE, PRCH), RHLD | capital is retained equity, not PP&E | retained-equity route from year 1 (O3) |
| Lenders the census misses | SEZL (SIC 7389, classed operating) and any other lender coded as services | the loan book is the capital | census rule check: lending-book share on every name, not only SIC 6xxx |
| Mortgage REITs | NREF, CIM | a lending book | financial route, not real estate |
| Equity real estate | 13 of the 15 "family not built": AMT, LAMR, OUT, HST, DRH, CLDT, RHP, LXP, ALX, CBL, STRW, DEA, MRP | depreciation of buildings and land improvements overstates economic depreciation; GAAP earnings understate cash earnings (the MSGE seam, in its strongest form) | **Inside this fix (O6 revised 2026-10-18).** "Family not built" is the code-only engine's status (SPEC_rebuild §2: classified, not valued); the AI desk values these names today with the ordinary operating formula, with nothing real-estate-specific except no cash term (`consensus_reference.FINANCIAL_SECTORS`). No new formula is needed: D2 with a measured, negative s = (recurring capex − D&A)/E, so the long run runs on Ẽ = NI + D&A − recurring capex (an AFFO-like base) instead of GAAP net income. Recurring capex from the filed capital-improvement line (XBRL PaymentsForCapitalImprovements), 5 years pooled; acquisitions and development are growth and stay in g/RONIC. Where the filings do not separate recurring from development capex: the analyst may state it with a citation; otherwise s = 0, stamped `recurring_capex_not_separable`, with total property capex reported only as a sensitivity (it double counts growth: `RULINGS_step1a_outside_review.md`). D&A here excludes the acquired-intangible amortization X already adds back. Plus δ (O5) |
| Finite-life concessions | CAAP (airport concessions), IHS, BIP, RNW, ENLT, CWEN (contracted renewables) | no perpetuity: the asset is handed back or the contract runs out | the desk's existing `finite_life_years` mode; code flags concession or contract-expiry disclosures and requests the analyst's choice |

**The same equation, but it needs a measured input:**

| Case | Book names | Input | Measured from |
|---|---|---|---|
| Depleting | E&P: APA, SM, GTE, PNRG, DEC, EQNR; miners: NEM, BTG, NEXA | s | ASC 932 tables (E&P); S-K 1300 for miners, flagged until a method exists (O4) |
| Debt-funded growth | utilities (NJR, UGI, CWEN, BIP), shipowners on charter-backed debt (GSL, CMRE, ESEA, FRO, INSW, HSHP, GASS, HAFN, ZIM), VLRS, R, TRN, the REITs | δ | §2 row 10 |
| IFRS 16 and finance-lease lessees | the 24 foreign filers (EQNR, BUD, ZIM, VLRS, IHS, TLK, KOF, JBS, VEON, CAAP, HAFN, …) and US finance leases | lease principal | the cash-flow statement's lease repayments (step 2) |
| Acquirers | DEC (buys mature wells), DAR, SAH, RUSHB, CHEF, BHC, DXC | acquisition spend as reinvestment | cash paid for acquisitions, 5-year pooled; when material, the explicit years understate reinvestment the analyst's growth needs. Diagnostic and reason request; the explicit-year change is the §6 item |
| Negative or near-zero earnings | biotech and tools (BCRX, PTCT, TXG, CDNA, ILMN, NUTX), GSAT, PRCH, cyclical troughs (MU, shipping, refiners at times) | the wedge's scale | D2's wedge as a share of earnings divides by E. It is restated as a share of revenue (§3) |

**No special treatment, and why:**
- **R&D-heavy and asset-light** (FTNT, OKTA, TWLO, RNG, MTCH, V, MA, AMD, TER, pharma): R&D is expensed, so E is already after that
  reinvestment and g/RONIC on tangible capital charges only the rest. Consistent as long as RONIC is measured on the same tangible basis.
- **Homebuilders and distributors** (HOV, AVT, GOLD): the capital is inventory and receivables, inside working capital, which r_tc's
  capital includes.
- **Cyclicals** (refiners VLO, CLMT, PARR; ATI, WLKP, PTEN, MU, shipping): the risk is normalizing E across the cycle, a separate question (§6).
  The wedge handles a capex wave at year 5.
- **Leases under US GAAP operating-lease accounting** (KSS, DLTR, EAT, PACS, NHC, THC, DVA): rent is in operating cost, not D&A. No defect,
  unless a lease is a finance lease.

**A classification gap that touches all of the above:** 24 of 160 names (15%) are unclassified ("no annual report filed before the
valuation date"), all foreign 20-F or 40-F filers, including EQNR and BUD. Any routing by family misroutes them today. The census must
read 20-F and 40-F filings before any route depends on it (step 1a).

## 3. Design D2

Notation as in the problem statement. E_t is X. RONIC is the after-tax return on total tangible capital (r_tc's basis).

**Years 1–5:** unchanged.

**Year-5 boundary (code computes):**
- actual reinvestment I_5 = E_5 − Flow_5 (bridge identity; holds working capital);
- modelled reinvestment I*_5 = S_5 + (g_6 / RONIC_0)(E_5 − S_5);
- the wedge rate w_5 = (I_5 − I*_5) / R_5, a share of year-5 revenue (not of earnings, which can be near 0 or negative; §2a).
  Positive for a builder (DAC, Equinor), negative for a capex holiday (MSGE).

**Fade, t = 6 … N = 5 + F:**

> Flow_t = E_t (1 − s)(1 − g_{t+1} / RONIC_t) − w_t × R_t,  w_t = w_5 × (1 − (t − 5)/F)

All reinvestment terms here are equity reinvestment: net reinvestment × (1 − δ) (§2 row 10), and RONIC is the code-converted return on
incremental equity.

**Terminal:**

> TV = E_{N+1} (1 − s)(1 − g_T / RONIC_T) / (r − g_T)

**The sustaining rate s = S / E:**
- **Depleting, measured:** from the ASC 932 supplementary tables, pooled over 5 years (sums, not averages of ratios):
  F&D per boe = Σ costs incurred / Σ reserve additions (extensions, discoveries, improved recovery, revisions, purchases);
  S = (F&D per boe × production − producing-activities DD&A) × (1 − δ) (corrected 2026-10-18, `RULINGS_step1a_outside_review.md`: no tax factor, since E already carries DD&A's tax shield). Kept as measured, negative
  included (DD&A above replacement cost is information, not an error).
- **Depleting, not measurable** (the tables are missing or untagged, or a miner under S-K 1300 with no costs-incurred table): s = 0, stamped
  `depleting_sustaining_unmeasured`; the reason request goes to the analyst; code reports the value at the D residual as a sensitivity.
- **Everyone else:** s = 0. A capex treadmill shows up in the diagnostics and in the analyst's RONIC_T, not in a hidden charge.

**Financials:** from year 1, Flow_t = E_t (1 − g_{t+1} / ROE_t), ROE on book equity, ROE_0 measured, ROE_T the analyst's RONIC_T read as
ROE. No capex, D&A or working capital. (Ruling O3.)

**With s = 0, w_5 = 0 and δ = 0, D2 is exactly today's long run** (the step-3 regression test). For operating companies D2 differs from D only in that the wedge fades
toward the funded rate instead of toward D's ρ_T, so their offline values should stay inside D's −2% to +7%.

**Diagnostics (code, stamped, never gates):**
1. `rho_5_bridge` and `wedge_rate_5` (w_5).
2. Explicit-years implied return: (E_5 − E_0) / Σ_{t=0..4} I_t. Σ ≤ 0 is stamped `negative_net_reinvestment_explicit`, not `n/a`.
3. Capital roll-forward (clean surplus): IC_N = IC_0 + Σ I_t over the whole horizon; implied ROIC_{N+1} = E_{N+1} / IC_N, set beside
   RONIC_T and r_tc. This catches a forecast whose cumulative reinvestment cannot produce its terminal earnings at the stated return.
4. Seam ratio Flow_6 / Flow_5.
5. Steady-state capex/D&A at g_T for the company's asset life (row 11's identity), against its measured 5-year capex/D&A.
6. For depleting companies, the D residual ρ_sust beside the measured s.

Material negative ρ_5, a wedge above a registered size, and an implied return far from RONIC_T draw reason requests. The thresholds are
registered before any run, from the book's distribution, not tuned on outcomes.

## 3a. Step 3 specification of the O7 leg (2026-10-18, after Gemini's three guardrails)

**Years 1–5, levels:**

> Flow_t = E_t − (1 − δ)(capex_t − D&A_nl,t + ΔNWC_t) − (P_t − ROU_t)

- E_t = R_t × m_t: the rev25 bridge's revenue and margin.
- D&A_nl is D&A less right-of-use depreciation. P_t is lease principal and ROU_t right-of-use depreciation (L1).
- **The lease term takes no δ:** leases are 100% lease-funded (`REPORT_step2_lease_audit.md` §3).
- **Gemini's point 1, ruling:** lease principal does **not** go on the capex side. It is a separate term, without δ. With no lease the
  form is O7 as approved.

**Default paths: five-year pooled ratios to revenue** (Gemini 1, accepted). capex/revenue = Σ capex / Σ revenue over the five base years,
likewise D&A_nl, P and ROU. Never the mean of annual ratios. A base year below 2025 or a vendor-capex fallback is stamped, as the pack
stamps them today.

**δ applies to negative net reinvestment as well** (Gemini 2, accepted; it restates `RULINGS_step1a_outside_review.md`). A company
disinvesting at constant leverage repays debt pro rata, so its equity flow is reduced by δ of the release. Expected effect, registered in
step 7: names with D&A above capex and δ > 0 lose value relative to δ = 0 (BUD δ 0.29, DXC δ 0.51).

**Analyst override of the capex path** (Gemini 3, accepted with one change):
- **Format:** either five values [c_1..c_5] (a build-out that winds down, as at DAC or firm B) or a year-5 target c_5, linearly
  interpolated from the pooled base ratio.
- **Citation:** each override carries a citation (filing, guidance, the company's capex plan).
- **The change:** the citation check annotates, it does not gate. An uncited override is used as stated, stamped
  `capex_override_uncited`, and draws a reason request (design rule: annotate, never silently gate). D&A_nl follows its pooled ratio to
  revenue in both cases. Firm B tests whether that is close enough after a build-out; if not, D&A_nl gains the depreciation of the
  override's capex at the filed asset life.

**Positivity:** the rule moves from base_cf to E_0: E_0 ≤ 0 is refused, as before; a negative flow year is valued.

**Amendment, 2026-10-18 (ChatGPT P0/P1, Gemini's drop-in spec), ruled by the coordinator:**

- **D&A basis (P0, accepted, with the exact identity).** The pack's E is X = NI + (1 − τ)·A, A being acquired-intangible amortization
  (`throughcycle_record.earnings_detail`), an after-tax add-back at the record's tax rate. Substituting into the cash identity
  Flow = NI + D&A − capex − ΔNWC − P gives exactly

  > Flow_t = X_t − (1 − δ)(capex_t − D&A_org,t + ΔNWC_t) − (P_t − ROU_t) + τ·A_t,   D&A_org = D&A − ROU − A

  The τ·A term is the amortization's tax shield, which X drops. Gemini's identity check ("Flow_0 ≡ E_0 at δ = 0, capex = D&A, no
  leases") is therefore wrong by τ·A; the code checks the identity above instead, to 1e-9. A_t follows the filed five-year amortization
  schedule (`FiniteLivedIntangibleAssetsAmortizationExpenseNextTwelveMonths` … `YearFive`, filed by 91 of 160 names), else A_0 held,
  stamped `amortization_schedule_not_filed`. After year 5 the shield is dropped, as today (synthetic firm D's −1.7%; recorded, not
  changed).
- **Units and interpolation (accepted, as Gemini wrote them).** c_t is capex over revenue and capex_t = c_t R_t. Mode 1 is five values;
  mode 2 is a year-5 target, c_t = c_base + (t/5)(c_5 − c_base); mode 3 is no override, c_t = c_base. c_base and d_base are five-year pooled
  sums, with the raw totals and the denominator flags (`rev_5yr_nonpositive`, `partial_history_n_years`) on the payload.
- **The override's depreciation (P1).** Settled on firm B **before** coding:
  - **First test:** D&A_org = d_base R_t in a reference implementation inside the harness. The ±3% value criterion applies, and the
    annual flows are compared.
  - **If that fails,** Gemini's incremental-vintage rule: ΔCapex_j = (c_j − c_base) R_j, depreciated straight line from the half year,
    ΔD&A_t = (½ΔCapex_t + Σ_{j<t} ΔCapex_j)/L, each vintage capped at its cost. With no override it is identically 0. L is
    2 × net PP&E / D&A_org at the base year (the store holds net, not gross, PP&E; under straight line the average asset is half
    depreciated), bounded [3, 40], stamped.
- **δ excludes leases (confirmed):** debt is non-lease debt (`REPORT_census_1a_addendum.md` §2).
- **Regression gate (confirmed):** s = 0, w = 0, δ = 0 on the legacy path reproduces today to the cent and 1e-6 relative, tested
  separately from the synthetic suite.
- **Sequence (accepted):** the harness exists (step 1). Step 3 starts with a reference implementation of D2 inside the harness
  (`synthetic.py`, no rs2 code changed). The desk code is written only once that reference passes A–I, C2, G and H at the registered criteria
  (C, C2 and H only with s, which is step 5).

## 4. Work plan

Each step has its check. Coders are fresh agents per step; every diff is audited line by line before merge.

| Step | Work | Verified by |
|---|---|---|
| 0 | Records: this plan; correct problem statement 6a ("negative ρ_5 is not sustainable") and 2 (ρ_5 is a bridge, not a measurement) | operator reads |
| 1a | Book census from filed data, no GPU: read 20-F and 40-F so the 24 foreign filers classify; per name, 5-year capex/D&A, δ, lease principal / owner earnings, acquisitions / net income, E ≤ 0, reserve tables present, concession disclosures, lending-book share. Sets which §2a cases are material and how many names each touches | every name in the book has a family or a named reason; counts per case reported before building anything |
| 1 | Synthetic harness first: firms A–F built from simulated statements, true value from a 200-year DCF of their own cash flows. A inflation-only compounder; B lumpy newbuild; C depleter with rising F&D cost; D serial acquirer; E capex holiday; F insurer; G utility (50% debt, 6% rate-base growth); H equity REIT (building depreciation above recurring capex, 40% debt, growth by acquisition) | harness reproduces each firm's closed-form value; today's desk run on it gives the baseline error per firm |
| 2 | Lease audit: done 2026-10-18, `REPORT_step2_lease_audit.md`. The fix is L1–L4 (a lease-principal and lease-interest field at the screener field owner; base_cf less lease principal; return after lease interest), not base_cf alone; implemented in step 3's desk revision | firm I exact with L1–L4 (−18.9% with base_cf alone); BUD, EQNR, MU, MSGE, PACS traced |
| 3 | D2 seam and diagnostics with s = 0 (desk only, `consensus_reference.long_run_value` and `financial_model_tool`) | s = 0, w = 0, δ = 0 reproduces today to the cent; firms A, B, D, E within ±3% of truth; full test suite |
| 4 | Financial route from year 1 | firm F within ±3%; MCY by hand |
| 5 | ASC 932 feasibility: which depleting names in the book have the tables in XBRL or parseable 20-F/10-K HTML; then S measurement | coverage count reported; EQNR's S traced by hand from its 20-F; firm C within ±3% when S is measured, and its error reported when not |
| 6 | Offline recompute from stored analyst inputs (no GPU; about 20 names hold stored runs, not 160: `REPORT_census_1a_terminal.md` §5): value change, seam ratio and diagnostics by category | report; value/price shown, never a target |
| 7 | Outside-AI cross-check of steps 1–6, then registration (desk version, diagnostic thresholds, reason requests as a PACK_REVISION, recorded) | cross-check record; registration record |
| 8 | GPU runs only after 7 | the registered gate |

Order matters: step 2 can change base_cf for many names, so the offline numbers of step 6 are only meaningful after it.

## 5. Operator decisions (all approved 2026-10-18)

- **O1.** D2 replaces D; the ρ_sust residual becomes a diagnostic only. (Recommended.)
- **O2.** The wedge fades over the analyst's F (recommended), or over min(F, 5).
- **O3.** Financials move to the retained-equity route from year 1. This changes MCY-type values and is a method change for a family.
- **O4.** Miners stay flagged-only (s = 0, `depleting_sustaining_unmeasured`) until a measured method exists.
- **O5.** Desk-wide measured leverage δ (§2 row 10, revised). Raises value for debt-funded growers; synthetic firm G (a
  utility with a 50% debt share and 6% rate-base growth) is added to step 1 to prove it.
  Offline on the 8 runs (`scratch/rev23/phase4_restore/o5_check.py`, today's rule with δ; δ = 0 reproduces today exactly):
  EQNR +11.9% (δ 0.19), BUD +2.4% (δ 0.27), the rest within ±0.3% (DAC, GOLD hold net cash, so δ = 0; DAC is not a debt-funded grower
  today, correcting §2a). Book weights would give EQNR +24.7%. The large effects are outside the 8: utilities, levered shipowners,
  REITs, VLRS; step 1a counts them. A utility whose capex exceeds D&A has base_cf ≤ 0 and is refused by the desk today; under δ it may become
  valuable. That is a change in which names reach the book, not only in their values.
- **O7 (APPROVED by the operator 2026-10-18; restated after the step-1a reviews).** Explicit years on levels: Flow_t = E_t − (1 − δ)(capex_t − D&A_t + ΔNWC_t), E_t from the rev25 bridge's revenue and margin, capex_t and D&A_t from the five-year pooled filed intensities (capex/revenue, D&A/revenue) unless the analyst states a capex path with a citation. It merges with §6's first recorded item (explicit reinvestment that does not respond to growth), so it is the explicit-year leg of D2, not a separate coverage patch. The positivity rule stays where it has a reason: E_0 ≤ 0 (no earnings base) remains refused; a negative flow year is valued as the economics (ChatGPT: do not weaken the rule for coverage; this removes a representation limit, not a check). Synthetic firms B and G are its acceptance cases. Changes the rev25 explicit years: a versioned PACK_REVISION, recorded and cross-checked. Decide before step 3; step 6 reports the refusal count with and without it.
- **O6 (revised).** Equity real estate goes through D2 now, with a measured negative s and δ; mortgage REITs (NREF, CIM) take the financial route. The first wording (wait for a family build) mixed up the code-only engine, which does not value REITs, with the AI desk, which does.

## 6. Recorded, not done here

- Explicit-year reinvestment does not respond to the analyst's growth (OE/E is fixed at κ or the consensus ratio). A faster path should need
  more reinvestment. A change to the rev25 explicit years; its own decision.
- Commodity earnings normalization (Equinor's E_0 across the price cycle) is a separate question from reinvestment and may move Equinor
  more than any of this.
