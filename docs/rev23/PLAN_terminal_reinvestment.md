# Plan: the terminal reinvestment fix (design D2)

*2026-10-18. Answers `PROBLEM_STATEMENT_terminal_reinvestment.md` after the Gemini and ChatGPT reviews. A plan, not an implementation.
Nothing here is built or registered yet.*

**Operator rulings, 2026-10-18:** O1–O8 approved (O8, removing s, after step 5; see §5). O1–O6 approved as recommended (O2: the wedge fades over the analyst's F). Steps 0 and 1a authorized; the work continues through step 7, then the GPU runs go back to the Phase 4 stage 0.1 session.

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
| Depleting | E&P: APA, SM, GTE, PNRG, DEC, EQNR; miners: NEM, BTG, NEXA | no s (O8): the treadmill is carried by actual capex in years 1–5 (O7), the gap fading over F, the return path, and a cited investment-state path (O2c) | F&D vs DD&A diagnostic and reason request; ASC 932 / S-K 1300 parsing is a diagnostic input, off the port's critical path |
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
- modelled reinvestment I*_5 = (g_6 / RONIC_0) E_5 *(O8: S_5 = 0; the pre-O8 form was S_5 + (g_6 / RONIC_0)(E_5 − S_5))*;
- the wedge rate w_5 = (I_5 − I*_5) / R_5, a share of year-5 revenue (not of earnings, which can be near 0 or negative; §2a).
  Positive for a builder (DAC, Equinor), negative for a capex holiday (MSGE).

**Fade, t = 6 … N = 5 + F:**

> Flow_t = E_t (1 − g_{t+1} / RONIC_t) − w_t × R_t,  w_t = w_5 × (1 − (t − 5)/F)   *(O8: no s term)*

All reinvestment terms here are equity reinvestment: net reinvestment × (1 − δ) (§2 row 10), and RONIC is the code-converted return on
incremental equity.

**Terminal:**

> TV = E_{N+1} (1 − g_T / RONIC_T) / (r − g_T)   *(O8: no s term)*

**The sustaining rate s = S / E** (superseded by O8, 2026-10-18: s is removed; see §5 O8). *What follows is the pre-O8 text, kept for the record; under O8 the measure S below is a diagnostic only and never enters a flow, the year-5 boundary or the terminal.*
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
- **P1 and O2c, settled 2026-10-18 (`REPORT_step3_reference_d2.md` addenda 1–2; O2c approved by the operator):**
  - **D&A in the levels leg is the vintages rule:** base vintages from filed gross PP&E, net PP&E and D&A, with L = prior gross / D&A; pooled D&A/revenue is the fallback where gross PP&E is not filed, stamped `da_vintages_no_gross_ppe`.
  - **τ·A runs to exhaustion:** five-year schedule, then the 'thereafter' balance at the year-5 rate, in every period.
  - **O2c replaces O2b:** H is the years of the analyst's cited capex path beyond year 5, and the levels leg runs to 5 + H, then the funded path with no gap. N = 5 + max(F, H). With no override, the gap fades over F (O2). H must equal the supplied path's length, and each year carries units (capex/revenue), the year and a citation, filed before the valuation date. A missing, malformed or inconsistent path gets a named diagnostic, never a silently shortened forecast. An uncited path is used, stamped `investment_state_duration_uncited`, with a reason request. A negative ρ_5 faded over F > 5 draws `negative_reinvestment_faded_over_long_horizon`.
- **δ excludes leases (confirmed):** debt is non-lease debt (`REPORT_census_1a_addendum.md` §2).
- **Regression gate (confirmed):** s = 0, w = 0, δ = 0 on the legacy path reproduces today to the cent and 1e-6 relative, tested
  separately from the synthetic suite.
- **Sequence (accepted):** the harness exists (step 1). Step 3 starts with a reference implementation of D2 inside the harness
  (`synthetic.py`, no rs2 code changed). The desk code is written only once that reference passes A–I, C2, G and H at the registered criteria
  (pre-O8 wording: C, C2 and H only with s, which is step 5. Under O8: H passes with s = 0; C and C2 fail by default and pass only on their cited path, reported apart).

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
| 5 | **Done 2026-10-18** (`REPORT_step5_sustaining_charge.md`): the measured s double counts (firm A −9.9%; H from +1.73% to +5.79%), so O8 removes it. What remains: the F&D-vs-DD&A and REIT recurring-capex diagnostics, wired with the port | C and C2 reported separately: **default D2 fails (+7.37%, +4.53%)**; they pass only on their cited escalation path (+2.30%, +1.59% to year 20). A path-dependent pass is not a default pass |
| 6 | Offline recompute from stored analyst inputs (no GPU; about 20 names hold stored runs, not 160: `REPORT_census_1a_terminal.md` §5): value change, seam ratio and diagnostics by category | report; value/price shown, never a target |
| 7 | Outside-AI cross-check of steps 1–6, then registration (desk version, diagnostic thresholds, reason requests as a PACK_REVISION, recorded) | cross-check record; registration record |
| 8 | GPU runs only after 7 | the registered gate |

Order matters: step 2 can change base_cf for many names, so the offline numbers of step 6 are only meaningful after it.

## 5. Operator decisions (all approved 2026-10-18)

- **O1.** D2 replaces D; the ρ_sust residual becomes a diagnostic only. (Recommended.)
- **O2.** The wedge fades over the analyst's F (recommended), or over min(F, 5).
- **O3.** Financials move to the retained-equity route from year 1. This changes MCY-type values and is a method change for a family.
- **O4.** ~~Miners stay flagged-only (s = 0, `depleting_sustaining_unmeasured`) until a measured method exists.~~ (superseded by O8, 2026-10-18: s is removed; see §5 O8) Miners get no special rule.
- **O5.** Desk-wide measured leverage δ (§2 row 10, revised). Raises value for debt-funded growers; synthetic firm G (a
  utility with a 50% debt share and 6% rate-base growth) is added to step 1 to prove it.
  Offline on the 8 runs (`scratch/rev23/phase4_restore/o5_check.py`, today's rule with δ; δ = 0 reproduces today exactly):
  EQNR +11.9% (δ 0.19), BUD +2.4% (δ 0.27), the rest within ±0.3% (DAC, GOLD hold net cash, so δ = 0; DAC is not a debt-funded grower
  today, correcting §2a). Book weights would give EQNR +24.7%. The large effects are outside the 8: utilities, levered shipowners,
  REITs, VLRS; step 1a counts them. A utility whose capex exceeds D&A has base_cf ≤ 0 and is refused by the desk today; under δ it may become
  valuable. That is a change in which names reach the book, not only in their values.
- **O7 (APPROVED by the operator 2026-10-18; restated after the step-1a reviews).** Explicit years on levels: Flow_t = E_t − (1 − δ)(capex_t − D&A_t + ΔNWC_t), E_t from the rev25 bridge's revenue and margin, capex_t and D&A_t from the five-year pooled filed intensities (capex/revenue, D&A/revenue) unless the analyst states a capex path with a citation. It merges with §6's first recorded item (explicit reinvestment that does not respond to growth), so it is the explicit-year leg of D2, not a separate coverage patch. The positivity rule stays where it has a reason: E_0 ≤ 0 (no earnings base) remains refused; a negative flow year is valued as the economics (ChatGPT: do not weaken the rule for coverage; this removes a representation limit, not a check). Synthetic firms B and G are its acceptance cases. Changes the rev25 explicit years: a versioned PACK_REVISION, recorded and cross-checked. Decide before step 3; step 6 reports the refusal count with and without it.
- **O6 (revised; amended by O8).** Equity real estate goes through D2 now, with δ and **no s** (O8 drops the measured negative s; recurring capex against D&A is a diagnostic); mortgage REITs (NREF, CIM) take the financial route. The first wording (wait for a family build) mixed up the code-only engine, which does not value REITs, with the AI desk, which does.

- **O8 (APPROVED by the operator 2026-10-18; ChatGPT and Gemini both approve).** The sustaining charge s is **removed from the production
  formula**: it is absent from the fade, the year-5 boundary and the terminal. Not a parameter defaulted to 0; it is not in the production interface.
  A test-only copy may keep it to reproduce step 5's counterfactual.
  - **Diagnostics, never valuation adjustments:** depleters' pooled F&D-per-boe against DD&A-per-boe (`fd_vs_dda_gap`) and REITs' recurring
    capex against D&A (`reit_recurring_capex_vs_da`). A material gap draws a reason request: "state the capex path through the end of the
    gap (O2c), or say why it closes". Missing reserve data is stamped unavailable, never read as "no gap".
  - **A material unresolved gap stays visible** on the verdict row and is reviewed before any value is used for a live decision.
  - **Miners and REITs get no special sustaining rule.** The ρ_sust residual of design D stays a diagnostic (O1).
  - **Evidence and its limits (stated as the reviewers asked):** firm A (no depletion) −9.9% with s; REIT H passes at +1.73% without and
    fails at +5.79% with it; C3 (impaired depleter) −0.08% without. **C and C2 still fail by default** (+7.37%, +4.53%) and pass only on
    a cited escalation path; that is reported as a forecast-dependent pass, never as a default pass.
  - **Rulings on the two reviews** (2026-10-18): all points accepted. The harness reproducibility defect ChatGPT found was real
    (`synthetic.py` imported the desk at module import from an absolute path) and is fixed: the desk import is lazy and path-resolved;
    `reference_d2.py` runs in a clean folder with every desk import blocked and reproduces all 12 firms' D2 results exactly; the desk
    comparison (`synthetic.py`) reproduces its baseline exactly. Gemini's "passes the full suite" is restated per C and C2 above.
  - **The port is split** (coordinator, 2026-10-18): (a) the desk formula with the new long-run members optional and legacy behaviour when absent; (b) pack facts producing the members from filed data (incl. the L1 lease field at the screener field owner); (c) the analyst capex-path / H input in the TASK and tool schema (a PACK_REVISION). Each audited before the next.
  - **Step 3, part 2 (the desk port) is authorized,** behind the regression gate: s = 0, w = 0, δ = 0 reproduces today's desk to the cent;
    every synthetic firm on its registered path within ±3%, comparing annual flows as well as totals; C and C2 default and cited-path results
    reported apart; a test that the diagnostics cannot change any value; the port matching `reference_d2.py` to machine precision. Not
    production-ready until those gates pass.

## 6. Recorded, not done here

- Explicit-year reinvestment does not respond to the analyst's growth (OE/E is fixed at κ or the consensus ratio). A faster path should need
  more reinvestment. A change to the rev25 explicit years; its own decision.
- Commodity earnings normalization (Equinor's E_0 across the price cycle) is a separate question from reinvestment and may move Equinor
  more than any of this.

### Port part (a) audited (2026-10-18)
- rs2 `review-2026-10/d2-port` @ `1dcb3b2` (from `8e2cb8a`; not pushed). D2 behind the optional `d2` members of `unbundled_dcf`; the only legacy lines touched are two checks guarded by `d2 is None` and one dispatch.
- Gate, re-run by the coordinator: `test_d2_desk.py` 55 passed; full suite 3460 passed, 42 failed, the 42 identical by name to `8e2cb8a`'s.
- Legacy-equivalent `d2` (δ = 0, w_5 = 0, no s) reproduces today's value to the cent and to 1e-6 relative.
- Synthetic parity with `reference_d2.py`: every firm, value and every annual flow, difference ≤ 4e-16. C and C2 are reported twice: default fails (+7.365%, +4.534%), cited path passes (+2.302%, +1.593%).
- No hidden charge: the reserve and REIT inputs change no value or flow. The Flow_0 identity holds to 1e-9. An AST test finds no s in production.
- Builder ambiguities, all ruled by the coordinator to accept as built:
  1. `kd` and `tau` are `d2` members (needed for the O5 conversion to an equity return).
  2. `d2` requires the bridge; positivity is E_0 = R_0·m0 > 0.
  3. A malformed or missing declared state path is refused by name, never shortened.
  4. A negative D2 long-run value is not floored. It is stamped `d2_long_run_value_negative`: annotate, never gate.
  5. Financial route growth conventions as built.
  6. With no schedule filed, A_0 is held for five years then zero, stamped.
  7. The diagnostic definitions as built.
  8. The `rs2-local/AGENTS.md` desk paragraph will name `d2` at part (c).
- Part (a) is not production use. Nothing calls `d2` until part (b) (pack facts) and part (c) (TASK and tool schema, PACK_REVISION).

### Port part (b), screener fields audited (2026-10-18)
- Branch `review-2026-10/d2-fields` @ `5b30e90761` (stock-screener, from `origin/main` `18449fd5d7`; not pushed).
- Eleven new fields: `lease_principal`, `lease_interest`, `rou_depreciation`, `interest_on_borrowings`, `ppe_gross`, and `amortization_sched_y1`..`y5` plus `_thereafter`. All vote-excluded, with provenance.
- Pre-existing output is identical on 12 tickers. Suite: 698 passed, 3 skipped (`origin/main` 679 passed, 3 skipped).
- Coordinator rulings:
  - FinanceCosts less lease interest is refused as a borrowing-interest rung: it carries FX and hyperinflation items (BUD 5.0B).
  - The schedule is stored as six scalar fields, not a dict.
  - There is no IFRS gross PP&E element.
- **Merge order (binding).** rs2 `capability_test._unreviewed_history_fields` would print the 11 keys in the model-visible "UNREVIEWED FIELDS" block, which changes what the model is told. So the rs2 change that lists them in `REVIEWED_HISTORY_KEYS` (part b2) must be live before this screener branch merges and publishes.
- **L2 and L3 on the legacy path: deferred to part (c)** (operator, 2026-10-18).
  - If the legacy path stays the fallback for names whose `d2` inputs are unavailable, L2 (base_cf less lease principal) and L3 (the return after lease interest) are applied to it in the same registered revision as D2.
  - If those names are refused instead, L2 is not needed.
  - Until then the legacy path is unchanged, and D2 alone reads `r_tc_after_lease_interest`.

### Port part (b), pack facts audited (2026-10-18)
- rs2 `review-2026-10/d2-facts` @ `286409a` (from `1dcb3b2`; not pushed).
- Contents:
  - `tools/d2_facts.py` measures the `d2` members;
  - `facts["d2"]`, `d2_provenance` and `d2_unavailable`, sidecar only, with `FACTS_VERSION` 12;
  - L3 as `long_run.r_tc_after_lease_interest`, beside an unchanged `r_tc`;
  - the 11 screener keys in `REVIEWED_HISTORY_KEYS`, so pack text is byte-identical;
  - the desk forwards `d2` only under `d2_enabled`, which no arm sets.
- Coordinator re-run: full suite 3477 passed, 42 failed, the 42 identical by name to `1dcb3b2`.
- Builder ambiguities 1–12 accepted as built:
  - no second lease-interest subtraction when `interest_on_borrowings` is filed;
  - levels are in $B and scaled by π; pooled totals stay raw;
  - no filed debt means δ is unproven, never 0;
  - unresolved route tests are stamped;
  - only complete pooled years are used;
  - the currency is taken from the vendor block;
  - market cap is `shares_default` × price;
  - a missing `thereafter` is stamped;
  - `d2_enabled` without a bridge stays legacy, stamped.
- **Carried to part (c):** under `d2_enabled` the price-implied solver still runs the legacy long run. It must run D2 too, or the implied figures and the value are on different models.
- **Finding:** on the stored rows `facts["d2"]` is null for MSGE, BUD and DAC.
  - MSGE and DAC have no capex in any filed row; MSGE files `PaymentsForProceedsFromProductiveAssets`.
  - MSGE and DAC have no interest.
  - BUD has no filed debt component.
  - A book-wide coverage census is running (`scratch/rev23/d2_coverage/`) before any fix is chosen.
- **Coverage round approved** (operator, 2026-10-18; fixes 1–5): brief `briefs/BRIEF_D2b3_coverage.md`. New D2-only screener fields `capex_d2` and `debt_d2_total`, plus an extended `interest_on_borrowings`; the kd, capex, debt and debt-free rules in `d2_facts`; then a re-measure in the real pack. No existing field changes.
- **Coverage round, part S audited** (screener `review-2026-10/d2-fields` @ `65328f973e`).
  - Suite: 716 passed, 3 skipped. Pre-existing fields are identical on 160 names.
  - Coordinator rulings:
    - Short-term borrowings alone do not resolve the ladder (NVS).
    - The bonds + bank-loans interest rung needs both members.
    - Rung-sourced capex and debt are cross-checked against the vendor in rs2: 0.7 to 1.3 means used; outside means unavailable; no vendor figure means used and stamped unverified.
    - kd outside 1% to 20% is unavailable.
  - Known risk, caught by the vendor check: the debt component sum may double count NotesPayable with LongTermNotesPayable.
- **Coverage round, part R audited** (rs2 `review-2026-10/d2-facts` @ `84ae50c`). Full suite: the same 42 failures, plus one timing flake (`test_missing_timings_fall_back_to_wall_clock`, which passes 3 of 3 alone; its file is untouched).
  - Ambiguities 1, 2, 3, 5 and 6 accepted as built; the marker table matches part S.
  - 7 accepted, with a known effect: a zero-coupon convertible issuer gets kd unavailable.
  - 4 is carried to part (c): `r_tc_after_lease_interest` does not use the Nonoperating rung, so it is inconsistent with kd for those names.
  - Part M (the re-measure in the real pack) is running: `scratch/rev23/d2_coverage/m/`.
- **Part M result (2026-10-18):** `d2` is complete for **99 of 160** names in the real pack build (84 operating, 15 financial), up from 57; the 61 incomplete are null by name (`scratch/rev23/d2_coverage/m/m_result.json`).
  - Unavailable members: pooled 27 (no complete year; mostly capex under company-extension tags absent from companyfacts), kd 22, delta 21.
  - The vendor checks dropped CLDT capex (vendor 110k, an apparent vendor error), GSL capex (0.20), MTRN capex (0.67) and GOLD, IRWD, VEON debt.
  - **For part (c):**
    - 6 census-financial names (BFH CIM CTBI SEZL STT WTM) resolve operating with `family_route_unresolved`, because the lending, deposits, repurchase and investments tests have no fields. All 6 are incomplete today, so none is mis-valued, but the route tests need fields before any of them could reach D2.
    - 28 names have no SIC in `stocks.json`.

### Rulings on the outside reviews of the coverage decision (2026-10-18; ChatGPT and Gemini; the operator approved the order)
- **The 61 incomplete names (ChatGPT's structure, accepted).**
  - D2 is the only valuation eligible for decisions. A name without complete `d2` gets the status `unvaluable_missing_input`, with the missing members named. It is never treated as zero value or overvalued, and never silently dropped from reporting.
  - The legacy desk runs on such names as a separately labelled screening view only: never in one ranking with D2 values, and never in a book.
  - Gemini's fallback haircut is rejected: the legacy-versus-D2 bias can be measured only on the about 20 names with stored analyst runs, which is too few to calibrate it.
  - **This supersedes the coordinator's earlier option A recommendation.** Legacy L2 and L3 (deferred by the operator) are not needed while legacy is screening-only.
- **Routing (both reviews).** An uncertain family is a stop: no D2 value.
  - New routing evidence: the presence of standard income-statement elements for banks and insurers (net interest income, earned premiums; Gemini).
  - The SIC comes from SEC submissions, which carries it for every filer, foreign issuers included.
- **The vendor band (ChatGPT, over Gemini's fixed 0.9–1.1).** Field-specific bands are calibrated from the observed distribution of filed-ladder-versus-vendor ratios on names where both exist. They are registered before the coverage effect is looked at.
  - Also a check on the kd ratio itself (Gemini): a high interest rung combined with a low debt rung must not pass.
- **Recovery order (operator).** The data is refreshed first.
  1. Refresh the SEC company-facts bulk file to a dated copy (`scratch/rev23/sec_data/`).
  2. Recover from the SEC Financial Statement and Notes data sets (which include extension tags, presentation placement and labels; ChatGPT) in parallel with part (c).
  3. If needed, the definition-linkbase anchoring of extension elements (Gemini; the exact EFM rule to be verified first).
  4. A recovered capex series is accepted only on multi-year vendor agreement.
  5. Then re-measure coverage and calibrate the bands on the fresh data, then finish part (c).
- **Paired D2-versus-legacy comparison** on the stored runs: recorded as an observation, never used for tuning.
- **Noted for later:** bounded valuation for low-δ names without kd (value at kd 1% and 20%; use it, stamped, if the spread is immaterial).
- **Step 1 done:** fresh `companyfacts` is at `scratch/rev23/sec_data/companyfacts_2026-10-18.zip` (1.41 GB, 20,472 files, zip test clean). The Aug 7 copy is untouched. Step 2 (FSDS recovery measurement) is running under `briefs/BRIEF_D2r_fsn_recovery.md`.

### Two items moved into scope (operator, 2026-10-18)
The coordinator had left both out: the currency gap was recorded but never planned, and the materiality rule was filed as "noted for later". Both are required, and both are measured before they are built.
- **Currency fix.** The screener reads USD units only, so non-USD filers lose most fields; the 6 `delta_currency_unproven` names are one symptom.
  - The fix: the fields read in the filing's reporting currency, with that currency stamped, and converted once at a documented rate (period average for flows, period end for balances) from one owned FX source.
  - Market cap and debt must then share one currency before δ is computed.
  - **Measure first:** how many of the 160 lose fields to non-USD units, and which fields.
- **Materiality rule.** A missing member blocks D2 only when it could move the value.
  - For a member with a defensible range (kd in [1%, 20%] when δ is known; δ between 0 and the vendor-debt-based leverage when filed debt is missing; the amortization shield between 0 and A_0 held), the desk runs at both ends.
  - Spread within a registered threshold: the name is valued at the **lower** of the two values (real money), stamped `<member>_bounded` with both values.
  - Spread above the threshold: unavailable, as now.
  - Members without a defensible range (pooled capex and D&A, revenue, the family) stay required.
  - The threshold is registered before the coverage effect is seen. **Measure first:** the spread distribution on the 99 complete names, with each member blanked in turn.

### Part (c) pre-test: Qwen on the bridge (operator, 2026-10-18)
- D2 needs the 25.1 bridge, which the production Qwen arm (`iii_no_p50`) does not ask for. Operator ruling: test option A (Qwen fills the bridge, arm `r25_b`) on MSGE, one run, before part (c). The pre-run cross-check is waived for this test only; the full cross-check comes before the first GPU run that uses D2. If Qwen shows Muse's Stage 1 problems, fall back to option B (revenue path at the held base margin, stamped). Brief: `briefs/BRIEF_P4B_qwen_bridge_test.md`.
- **Currency measured** (`scratch/rev23/d2_currency/`). 11 of 160 names have non-USD facts. 6 are non-USD reporters: CHA, KOF, LPL, RNW, TLK, UMC.
  - FX conversion would plausibly recover 5 of the 61 (CHA, KOF, LPL, RNW, UMC). TLK also needs a revenue tag fix. CX, EFXT and VLRS are not helped.
  - **Existing defect found:** where those 6 file USD convenience translations, the USD-only build ships them at the year-end rate for flows as well as balances, against the documented convention (period average for flows).
  - Owner for the fix: `stock-screener/scripts/fx_normalize.py` (it already holds the convention and the proof procedure). Its yfinance rates must be archived to a data file so they are reproducible. FRED H.10 is a cross-check only (it has no IDR).
- **Materiality measured** (`scratch/rev23/d2_materiality/`; neutral inputs are sensitivity only; only 6 stored runs).
  - Median spreads: kd 0.7%, delta 1.2%, amortization 0.2%. kd spread rises with δ, and some names above δ 0.25 blow up.
  - Release counts among the 34 kd- or delta-only names (24 tested): 2% gives 8, 5% gives 10, 10% gives 14.
  - **Threshold: the operator decides after the recovery work (2026-10-18).** The coordinator noted that the choice should rest on the accepted undervaluation (a released name is valued at the lower end, so the threshold caps its downward bias), not on the release counts already seen.
- **FSDS recovery measured** (`scratch/rev23/d2_recovery/`).
  - The rule picks the screener's capex for 96% of single-candidate name-years.
  - It recovers capex for only DAC, CDNA and ALX (STRW is doubtful), all from extension tags that are unverifiable: 0 of 9 control matches, and the vendor holds no multi-year capex.
  - About 7 of the 27 already had capex; their pooled gap is D&A. That is the next check.
  - About 10 names split capex across several lines and stay ambiguous. CIM, NJR, WTM, BTG and MRP have nothing usable.
- **P4B ready, not launched (2026-10-18).** The test mode is audited: the derived arm-B pack, the copied evidence, and 107 tests pass. The launch waits for memory (0.4 to 1.4 GB free; the operator is restarting the Claude app).
  - Launch: `cd scratch/rev23/pilot_r25 && STOCKS_ROOT='C:\Users\riper\stocks' bash launch_detached_p4b.sh`, or register `register_stage1_task.ps1 -Model qwen38q5raw -Bridge`, then `Start-ScheduledTask RS2-P4-BRIDGE`.
  - Score afterwards with `python score_p4b.py` (`PILOT_MODEL` unset). Expect 75 to 110 minutes on the GPU.
- **D&A gap measured** (`scratch/rev23/d2_da/`).
  - A D2-only sibling `da_d2` would plausibly recover FLXS, GASS, DRH, PACS and SM (vendor TTM ratio 0.97 to 1.00):
    - a lone Depreciation when no amortization series is filed in any window year, stamped;
    - `CostOfGoodsAndServicesSoldDepreciationAndAmortization`, with a vendor reconcile;
    - D&A with accretion, stamped.
  - Not fixable: STT and PTEN (summed components understate by 60% and 85%), MRP. ESEA still lacks capex; FRO lacks the ROU split.
  - VLRS needs a revenue tag (`RevenueFromRenderingOfTransportServices`). OPTX fails on optional-component completeness; RNW was misclassified (not failing).
  - Not built: awaiting the operator.
- **`da_d2` and `revenue_d2` built** (screener `1c06210ef6`, rs2 `031ab88`).
  - Pre-existing output is identical on 24 tickers.
  - The 14-name build gives `da_d2` for FLXS, GASS, ESEA, FRO, DRH, PACS and SM, and `revenue_d2` for VLRS. STT, PTEN, MRP and TLK stay null.
  - The marker hand-off was checked by the coordinator: rung states decode to primary or backfill, and the marker comes from the tag table, with the COGS tag matched before the lone-depreciation tag.
  - Ambiguities accepted:
    - a filed 0 in the amortization window refuses lone depreciation (conservative);
    - the `lone_depreciation_refused` note;
    - TLK waits for the currency fix.
  - Full suites deferred until the GPU run ends.

### P4B result (2026-10-18): Qwen on the 25.1 bridge, MSGE
- Finished in 126.8 min (revision 24: 72.8). Verdict overvalued, Base $42.89 (revision 24: $45.08), price $79.60. The crux is valid (long_run_margin 8.5% against the 23.3% the price implies), and citations resolved 4 of 4.
- **Outcome class `reason_loop`** (a plan v4 failure class): 5 of 8 desk calls refused.
  - The bridge checks C1, C3, C4 and C5 and K1 repeatedly asked for reasons, and C5 recurred: normalized and long-run margins set on the operating basis (om_tc 12.8%) instead of the X basis (m5 8.1%).
  - The loop guard fired twice ("Changing inputs has not cleared ...") before a run was accepted at call 14.
  - This is the same failure pattern as Muse in Stage 1, though Qwen recovered to a coherent result.
- **Deferred full suites run (coordinator):** rs2 `d2-facts` @ `031ab88`: 3496 passed, 42 failed, the 42 identical by name. Screener `d2-fields` @ `1c06210ef6`: 728 passed, 3 skipped.
- **P4B cause, from Qwen's reasoning notes (one run, indicative):**
  - Qwen understood the X basis. Its 12% normal margin was its own estimate (adjusted operating income less interest and tax), not the operating margin typed by mistake, so C5 was largely a false alarm.
  - The pack's margin facts are hard to reconcile: the X-basis history (median 5.1%) is depressed by one-offs, the default m5 is 8.1%, and the consensus implies about 12% in years 1–2. Qwen spent effort reverse-engineering the basis. C1 and C3 also caught genuine mismatches in its own answers.
  - A short form must therefore also explain the basis in plain words and show the X-basis history with and without one-offs.

### Short form (desk schema 25.2, arm `r25_sf`), approved by the operator (2026-10-18)
- Specification and test mode: `briefs/BRIEF_SF_short_form.md`.
- The basis flag compares declared margins against the consensus-implied X margin for years 1–2 (forecast against forecast), not against history. The operator challenged the history comparison and the coordinator agreed.
- **Registered before any run:**
  - the flag band [0.67, 1.5];
  - test names MSGE, TASK and DAC (each has a revision-24 Qwen run; DAC is the cyclical name);
  - pass rules, every one of which must hold:
    - no desk refusals or loop markers;
    - minutes within about 1.2× revision 24;
    - a valid crux and verified citations;
    - every declared margin on the X basis (coordinator check);
    - no unexplained basis flag.
  - On failure: option B (the margin held by code, stamped), with no further form iterations.
- **The pre-run cross-check applies** (P4B's waiver was for that test only). It is to be written after the build, unless the operator waives it.
