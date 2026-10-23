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

### Rulings on cross-check 21 (2026-10-18; ChatGPT verdict CHANGE, Gemini CHANGE then GO)
Each claim tested by the coordinator before ruling.

**Rejected**
- **Gemini: τ·A double counts.** Tested on a one-year cash identity (EBIT 100, A 20, D&A_org 30, capex 40, τ 0.25): cash 70.0 = D2 flow 70.0. X restores only (1 − τ)A, cash adds back the full A, so +τ·A is required (already in the plan's amendment; the Flow_0 identity test holds to 1e-9).
- **Gemini: clamp δ ≤ 0.6 and floor ROE.**
  - A floor repeats cross-check 19's RONIC-floor defect (value-destroying growth priced as neutral).
  - A non-positive equity return is already refused by name.
  - Kept instead: `delta_high` stamped above 0.5, and the book-weight versus market-weight sensitivity reported.
- **Gemini: operating-margin proximity check.** It fired falsely on MSGE: Qwen's 12% was a correct after-tax estimate next to the 12.8% operating margin.

**Accepted for the short-form test** (sent to the SF builder; all annotate-only, computed so they cannot loop)
- **The basis flag** is renamed `consensus_margin_divergence` (ChatGPT). It fires only outside [0.67, 1.5] **and** beyond 3 margin points (Gemini, against small-margin distortion). With no consensus: `consensus_margin_check_unavailable`, never a pass.
- **One-offs (both).**
  - The raw X-basis margin history is primary, with the per-year after-tax impact and a frequency count.
  - At 3 or more of 5 years: `recurring_restructuring_or_impairment`, and no ex-one-offs series is printed.
- **One normalization check kept, non-blocking (both):** `normalized_vs_path_gap` (Base m5 against the contract's normalized earnings over R_0, more than 3 points), computed after the contract. Also `flat_margin_path` (Gemini).
- **ollama_raw:** a front-truncation guard (prompt plus output limit above num_ctx raises a named failure), if it is absent (Gemini).

**Test rules amended before any run**
- A pass authorizes further testing, not adoption (ChatGPT).
- Added failure signals:
  - `flat_margin_path` on DAC;
  - an unexplained `normalized_vs_path_gap`;
  - a blinded coherence read (a fresh agent, inputs masked) that finds a contradiction between the stated normalized economics or the labels and the path.
- Before adoption: repeated runs plus at least one unseen name (the operator decides the GPU budget).
- **Option B is not automatic on failure:** it needs its own coherence assessment (ChatGPT).

**Accepted, required before D2 is enabled (part (c))**
- **Fade growth convention (ChatGPT, major).** The fade charges reinvestment on revenue growth while the margin moves.
  - Tested: with the margin moving 8% to 12% over the fade, the revenue convention values 20.5% above the earnings-growth convention; 12% to 8% gives −17.8%; a flat margin gives 0.
  - Neither convention is right in general (margin change with or without capital).
  - Resolution: synthetic firms whose margin changes are economically specified (from existing capital, and from new investment), truth-tested on flows and value, then a ruling.
- **The tax shield after year N (ChatGPT).** The terminal carries no τ·A, so a schedule outstanding beyond N is dropped. Add the PV of the remaining finite shield.
- **The 21% tax default (ChatGPT).** An unmeasured τ is unavailable (or bounded under the materiality rule), never a stamped default.
- **Unverified fallback rungs (Gemini).** With no vendor figure they become unavailable, not used-and-stamped.
- **Materiality rule (both).** An interval, not the lower end:
  - the name is usable only if every endpoint gives the same verdict category;
  - the point is the midpoint, stamped `materiality_bounded`;
  - the threshold is still the operator's (calibrate from input uncertainty).
- **Others:**
  - financial-route return semantics (ROE_T named per route);
  - an end-to-end test that `family_route_unresolved` always yields `unvaluable_missing_input`;
  - a coverage-bias report by sector, size, currency and filing type;
  - non-USD convenience-translation names stay quarantined (checked: none of the 6 is among the 99);
  - depleters on the default path stamped with the known bias;
  - O2c value shown beside the default-wedge value;
  - the equity-conversion constant-leverage assumption exposed, with sensitivity;
  - `ollama_raw` fuzz and stop-sequence tests, plus a template-equivalence test against `/api/chat` on flat schemas.
- **Kept open:** the MCY copying signature (1.02× the reference); is the analyst goal-seeking a printed number?
- **Short form audited and launched (2026-10-18 20:18).**
  - rs2 `review-2026-10/short-form` @ `4a6e292`. Full suite: 3443 passed, the same 42 failures. 37 short-form tests pass; other arms are byte-identical.
  - The coordinator checked that the TASK diff touches only item 3's path wording, the two-lists bullet and working capital, and that 25.2 still validates the lists while running no C or K check.
  - Ambiguities 1–9 accepted. `SCREENER_SEC_FACTS_DIR` was added to the workspace `AGENTS.md`.
  - Task `RS2-P4-SF`, names MSGE, TASK and DAC, tree `4a6e292`.
- **Short-form test, defect 1 (2026-10-18).** All three runs ended `lost_memo` / `server_error`, cause `context_overflow`. The new front-truncation guard counted prompt plus the output LIMIT. The harness sizes the limit from an estimated prompt (32,215 estimated against more actual), so every turn was refused after a full generation.
  - It is a coordinator specification error (cross-check 21 item), not a model outcome.
  - Fix `6bc2ad0`: the guard counts the tokens used (prompt_eval_count + eval_count), with a test. Pilot tests: the one known unrelated failure.
  - The failed runs are kept as `runs_p4sf_defect1/`. A same-seed re-run was launched at the fixed tree, as plan v4 allows for defects.
- **Short-form test, re-run result (2026-10-19 03:05), scored against the registered rules.**

| Name | Minutes (× rev 24) | Verdict, Base (rev 24) | Refused | Loop markers | Crux | Unresolved citations | Flags |
|---|---|---|---|---|---|---|---|
| MSGE | 70.7 (0.97) | overvalued, $44.45 (overvalued, $45.08) | 3/5 | 0 | valid | 1/7 | `normalized_vs_path_gap` 3.7 pts |
| TASK | 93.0 (1.69) | undervalued, $17.10 (hold, $13.14; its crux was invalid) | 5/10 | 0 | valid | 1/4 | `consensus_margin_divergence`: Bear y2 6.5% against 10.3% |
| DAC | 76.2 (0.88) | undervalued, $370.64 (undervalued, $265.02) | 1/3 | 0 | valid | 0/2 | `normalized_vs_path_gap` 5.2 pts |

  - **No C/K-type loop and no loop marker anywhere.** The refusals are revision-24 desk reasons (`bull_below_price`, `bear_above_price`, `coe_adjustment`, `scenario_deviation`) plus format slips (`explicit_growth` or `base_cf` instead of the lists; a missing `prob`). Revision 24 also refused 1/4, 2/4 and 1/4.
  - **Read by the letter, the registered rules fail:**
    - "no desk refusals" fails on all three;
    - the time rule fails on TASK (1.69 against about 1.2);
    - "verified citations" fails on MSGE and TASK (one unresolved crux candidate each, though every directional verdict rests on a verified crux);
    - `normalized_vs_path_gap` is above 3 points on MSGE and DAC, with whether it is explained still to be judged.
  - **Not flagged by any rule:** MSGE and DAC copy the consensus margin of years 1 and 2 almost exactly (MSGE 11.6/11.7, DAC 46.7/40.8), the anchoring Gemini warned of. The margin paths are not flat.
  - The blinded coherence read is running: `runs_p4sf/BLIND_READ.md`.
- **Blinded coherence read** (`runs_p4sf/BLIND_READ.md`, a fresh Opus agent): MSGE **incoherent**, TASK **questionable**, DAC **incoherent**.
  - **Not fully blind:** the reader saw this plan's result table first; it judged on the economics it cites.
  - **MSGE:**
    - it mapped "9% X basis = 13% operating", where the pack's own translation gives about 5%;
    - it copied consensus margins for years 1 and 2 that are on a vendor-adjusted basis (+30% over the filed base);
    - the fade's stated cause fails on timing.
  - **TASK:** the normalized earnings are circular (taken from the desk's year-5 output), and the labels sit loosely with the path.
  - **DAC:**
    - "peak" rests on a misread: a drybulk rate was taken as the container rate;
    - it copied a single-analyst consensus, and the copied year-2 margin cut contradicts its own "years 1–2 contractually fixed";
    - a 4.7-year backlog is used to floor a perpetual margin.
- **Pack defects behind part of this, confirmed by the coordinator** (the pack's own BASE-YEAR CHECK lines show consensus EPS +30% for MSGE and +48% for TASK above the filed EPS):
  - **B2:** `x_margin_consensus_y1y2` uses vendor-adjusted EPS, so it is not the X basis. It served both as the basis flag's reference and as the number the runs copied. This is the Street-basis risk Gemini named in cross-check 21; the coordinator's specification did not correct for it.
  - **B1:** the year that `normalized_earnings` refers to is undefined, so `normalized_vs_path_gap` measured revenue growth.
  - **B3:** SECTION 11 can deny that earlier complete desk runs existed.
- **Ruling: the short form as tested is rejected on coherence.** It removed the loops, but printing a consensus margin line invited anchoring (2 of 3 copied it), and the analyst errors are real. The registered rule says no further form iterations. Option B is next, and it needs its own coherence assessment (cross-check 21).

### Rulings on cross-check 22: controlling the analyst's output (2026-10-19)
Both reviews independently recommend the same change of architecture rather than another form. The first paste labelled "Gemini" was a duplicate of ChatGPT's; the real Gemini reply arrived afterwards.

**Gemini's claims about our setup, tested before ruling:**
- **Rejected: prior thinking accumulating in the history.** `analyst_tools` appends assistant turns as content plus tool_calls only (line 2656); no reasoning is passed back, so the template's `preserve_thinking` path never sees any.
- **Rejected: a q4 KV cache.** It is already `OLLAMA_KV_CACHE_TYPE=q8_0` with flash attention.
- **Not a bug: `min_p 0`.** It is Qwen's own recommended thinking setting; testable, one variable at a time.

**Accepted: the staged design, with separate sessions and a controlled information transfer.**
1. **Stage 1, research and a verified fact ledger** (both reviews). Every material fact carries entity, metric, period, unit, basis, source and exact quote, all verified by code. This answers the dry-bulk/container class of error; Gemini's per-industry term lists are rejected as narrow patches.
2. **Stage 2, a price-blind and consensus-blind forecast** (both).
   - No price, consensus, reference value or default path is visible; this is enforced by software, with a leak audit of every pack section, the research summary and tool results.
   - The analyst states operating-basis anchors (Gemini): years 1–2, a normalized state with its year (baseline plus a stated delta, with a reason and a fact ID), and the transition shape.
   - Code interpolates and bridges to the X basis and owner earnings, with every bridge assumption shown (code-owned bases).
   - Gemini's caution is accepted: no numeric bounds inside the grammar, only structure and enums.
3. **K = 3 cheap Stage-2 samples on the same frozen dossier** (Gemini). The spread is a gate: if direction is not unanimous, or the spread crosses the decision boundary, the result is "no call". The median is reported, not crowned as truth (ChatGPT).
4. **Stage 3, reveal the price and a basis-corrected consensus, then exactly one revision** (both).
   - A revision must cite a Stage-1 fact (Gemini, against sycophantic collapse).
   - The pre- and post-reveal values are both kept, and the pull ratio is logged.
   - Audit questions are put as questions, never with a prescribed answer (Gemini's DAC wording is rejected).
5. **Stage 4, the memo is written after the desk is frozen** (Gemini), with a final verifier that annotates or returns "no call" (ChatGPT).

**Accepted: the evaluation, which ends trial and error.**
- **A frozen benchmark** of about 12 stocks with cached Stage-1 dossiers (Gemini). Stages 2–4 take about 10 minutes per stock, so one design iteration costs about 2 GPU hours.
- **Two independent masked readers,** scoring against a registered rubric (ChatGPT).
- **The registered metrics:** loops, basis and memo-desk fidelity, anchor immunity (the perturbed-consensus canary), K = 3 reproducibility, fact and quote verification, and coherence.
- **At most 3 iterations,** then an end-to-end unseen holdout. A pass authorizes further testing, never live use.

**Later, one variable at a time:** a lower temperature with thinking off for structured turns; `num_ctx` lowered once staging shortens the context; an MTP on/off determinism check; a model change only if fact errors persist.

**Warning on the record:** revision 25 arm C (consensus withheld in pass 1, with Muse, in one session) scored worst, 4 of 10. The new design differs (separate sessions, price also hidden, a verified ledger, one revision). The precedent is a caution, not support.
- **Gemini's cheap replay experiment: checked, not usable (2026-10-19).**
  - **Rebuildable:** the prompt, tool arguments, verbatim results and compaction.
  - **Not rebuildable:** per-turn assistant content and the SYSTEM-text hash are not logged.
  - **Not clean:** the first user message (the pack) holds the consensus margin line and the consensus tables. The pre-desk reasoning used them in all three runs. DAC: "these are consensus-implied, I'll use them". MSGE calibrated against them; TASK recorded them.
  - Redacting the pack changes the first turn's conditioning, which defeats a replay. So the staged build goes ahead without it.
- **For the staged build** (from the same check):
  - the leak audit must remove every consensus-derived line from the blind stage, not only `x_margin_consensus_y1y2`: DATA 8's consensus table, the BASE-YEAR CHECK, estimate trend and revisions, price targets, the DEFAULTS `levels` (year1/2, bull2/bear2), `consensus_data_status`, the TASK lines naming those levels, and consensus prose in the catalyst brief and guidance block;
  - the harness must log raw completions per turn, plus a hash of the SYSTEM text, so that later runs can be replayed and cached.

### Revision 26 build log
- **R26-C forecast desk** (`review-2026-10/r26-desk` @ `7208e68`): 47 tests; full suite has the same 42 failures. No desk code changed; `value_forecast` calls the desk at 25.2.
  - Rulings: ambiguities 1–7 and 9 accepted. Transitions are defined in the docstrings; `delta_pts` is in percentage points (the TASK must say so); optional `long_run_fact_ids`; nothing defaulted in the bridge; direction split at the depth gate's 10%.
  - **Changed (8):** the normalized year N is limited to 3..5; a normalization after year 5 is expressed through `long_run_margin_op` and `fade_years`. The SPEC's 3..5+F is amended accordingly.
- **R26-A1 harness, stage 1** (`review-2026-10/r26-harness` @ `5c2c293`).
  - 85 new tests; full suite has the same 42 failures. Request bytes are unchanged with logging on.
  - Built: per-turn logging under `ollama_raw`; the stage runner with allow-listed session inputs; `register_facts` with all ten fields; the three checks; `dossier.json`.
  - Rulings:
    - its `pack_sections()` ids (heading slugs, `primary-p#`) are canonical, and R26-B aligns its tags to them;
    - for `pack:` sources, entity words matching the pack company's name or ticker are satisfied (stamped `entity_from_pack_company`);
    - the per-fact status feedback to the model, repeat-id rejection, `Q<n>` query ids and fetched-pages-only are accepted.
  - Still open: the logging gaps in the no-tools and `continue_report` paths (not used by r26); "r26" goes into `PILOT_ARMS` via R26-B.
  - Housekeeping: the builder left a baseline worktree at the scratchpad path `base6bc`, to remove with the operator's OK.
- Integration branch `review-2026-10/r26-int` (r26-harness at `481d0cf` + r26-desk at `4d2504f`, merge `1cd4e9e`; 133 r26 tests pass). R26-A2 (stages 2–4, reveal, memo, verifier) is building on it.
- **R26-B blind pack** (`review-2026-10/r26-pack` @ `2eec324`).
  - Zero leaks on MSGE, TASK and DAC (the audit caught two real leaks, a price and a Street target, and the filter was fixed). Every other arm is byte-identical.
  - The blind pack is about 70 KB, against about 78–83 KB for the revision-24 pack without the TASK.
  - Rulings: 1, 3–5, 7, 8, 10–12 accepted.
  - **Changed:**
    - **(2)** the r26 marker becomes 27, because `R25_SF_REVISION` already uses 26 (SPEC amended: revision 27 for the staged arm);
    - **(6)** the DATA 8 ROE / gross margin / operating margin line is kept, with only the dividend yield stripped;
    - **(9)** import `r26_forecast.invert_bridge`.
  - **Merge note:** `FACTS_VERSION` 12 is also used by `d2-facts` (different keys); reconcile at merge.
- **R26-A2 stages 2–4** (`91cf2bc`; 55 tests) merged with R26-B (`f15395d`). Coordinator fixes at `5f313cb` and `00801a3`:
  - `consensus_view` reads R26-B's shape;
  - the bridge hook indexes A_t by path year.
  - 208 r26 tests pass; the full suite is back to the 42.
- **TASK-text review and rulings:**
  - **(a)** The three labels move to stage 2, committed with the numbers; code copies them into the contract.
  - **(b)** Price-derived momentum lines are revealed to stages 3 and 4, so the momentum fields are grounded. Consensus classes reach stage 3 only through `consensus_corrected`.
  - **(c)** The family comes from the pack's existing classification, not a default "operating"; unknown means `no_call family_unresolved`.
  - **(d)** Confirm the stage-3 crux inputs against the solver on the 25.2 path.
  - A2 ambiguities 3, 5, 6 and 7 accepted.
  - **(4) Must resolve before any book-wide run:** `conviction_score`, `business_quality_moat` and `reentry_tranches` have no code source.
- **A2 follow-up** `372a6dc`: labels in stage 2; the REVEALED price/momentum block for stages 3 and 4; family from `population_ranges.family` (unknown means `no_call family_unresolved`); stage-3 crux inputs limited to what the 25.2 solver supports (coe, fade_years, terminal_g, terminal_ronic, long_run_margin). 202 r26 tests pass; full suite has the 42. R26-D (the benchmark mode) is building.
- **R26-D benchmark mode built** (pilot folder; 60 tests; nothing launched).
  - **Its offline probe found that stages 2–4 could not value most of the panel:**
    - net interest is missing for MSGE, TASK, DAC, BUD and MCY, and A_0 for MSGE;
    - PACS has no base_cf;
    - GOLD has a family/basis mismatch;
    - consensus is comparable only for TASK and GOLD.
  - **Coordinator ruling:** the bridge is calibrated to the filed base year. K_0 = OI_0 − X_0/(1 − τ) is held in dollars, so the bridge is exact at the base year and needs only τ, OI_0 and X_0. This replaces the separate interest and amortization inputs.
  - The PACS, GOLD and consensus causes are under investigation (R26-E). Comparability rules change only by ruling. If the registered canary names lack comparable consensus, the canary set is re-registered before any run, with the operator told.
  - R26-D choices accepted: the scorecard's all-12 completeness item; loops counted as guard markers + a refused second revision + `turn_budget` endings; the canary shift on the valuation basis; the reader extract including the revealed consensus and the revision; seed base 2502.
- **R26-E** (`c32c206`):
  - The base-year-calibrated bridge is built. The identity holds to ≤1.4e-17 on the real names, and OI_0 is put on the desk's revenue basis.
  - A unit bug in the consensus inversion was fixed ($ against $B).
  - GOLD's bar now reads `population_ranges.family`.
  - Readiness of the 7 restoration names: the bridge is ok for MSGE, TASK, DAC, BUD and MCY; GOLD has no filed operating income; PACS has no base_cf (D&A not filed in 10-Ks). Consensus is comparable for TASK and PACS, and for GOLD in year 2 only.
- **Rulings:**
  - **PACS:** `no_call base_cf_unavailable` (a recorded data no-call, not a run-stopping defect). r26 invents no base.
  - **GOLD and any such name (generic):** with no filed operating income in the window, the X basis is used throughout (the X bar, X wording, the identity bridge), stamped `x_basis_no_operating_income`.
  - **BUD:** with no filed diluted shares, the consensus correction may use the pack's code-owned share count, stamped `filed_eps_from_pack_shares`.
  - The vintage test and the ≥3-analyst rule are unchanged: DAC has 1 analyst, and MCY has a real 24% basis gap.
  - **The canary:** the registered names (MSGE, TASK, DAC, BUD) stay. Where consensus is not comparable, the canary reveals a **constructed test consensus** (the stage-2 median Base margins ± 3 points), so the pull is measurable on all four. This is test-only, never present in a production run, and labelled in the run record.

### Rulings on cross-check 23 (2026-10-19; ChatGPT CHANGE, Gemini CHANGE)
**Confirmed in code before ruling:**
- the frame is a free equity/firm choice;
- `dossier_fact_ids` includes unusable facts, which are only stamped;
- `prob` is checked as finite only;
- `pull_record` covers years 1–2 only;
- `contract_unfilled` is not among the non-actionable reasons;
- the tax rate is clipped to [0, 0.35] yet labelled measured.

**Rejected:**
- **Gemini, "K_0 bundles D&A".** X_0 = x_L·rev_L is on the earnings basis, not cash flow, so K_0 holds interest, other non-operating items and amortization only.
- **Gemini's α-blend of K_0 with revenue.** An arbitrary constant. Interest does not scale with revenue. K_0 stays flat in dollars, now labelled approximate on the verdict (ChatGPT).
- **Gemini, "near-fair-value names will split direction".** `direction_split` requires one undervalued and one overvalued sample under the 10% band, so three samples within ±10% are all hold, not a split.

**Accepted (R26-F, rs2):**
1. The frame is equity only for r26.
2. Unusable facts are never shown to stages 2 and 3 (a count and reason codes only).
   - Every cited fact ID must be usable.
   - near_term and normalized need non-empty usable fact IDs.
   - The long run needs fact IDs, or an explicit `no_duration_matched_evidence` with a reason.
   - One repair, as for any structure problem.
3. **The leak audit extends** to the stage-1 research summary and every model-facing dossier fact for stage 2: sentence-level drops, listed. Facts quoting analyst, consensus or price content are excluded from stage 2's view.
4. Stage 2 sees the blind pack's **filed-data sections only**; narrative reaches it only through usable facts and the audited summary.
5. **Stronger fact association** (before the stage-1 batch, since the dossiers freeze):
   - prose: the value must be in the quote, and the registered metric must be the nearest metric term to the value within its sentence, using one documented generic metric vocabulary;
   - tables: the header row and the row label are added to the association window;
   - otherwise the fact is `association_uncertain`, which means not usable.
6. **Domain checks:**
   - probabilities in [0, 1] and summing to 1 ± 0.01;
   - revenue never negative;
   - discount rate > terminal_g;
   - terminal_ronic > 0;
   - one repair.
7. Stage-2 acceptance is idempotent.
8. The tax rate records raw and applied values, stamped `tax_rate_clipped`.
9. **The stage-3 crux cites fact IDs.** Code pulls the source, date and verbatim quote into the existing crux check (no retyped quotes).
10. **TASK wording:**
    - a worked delta example;
    - adjusted or non-GAAP facts inform direction only, never the level;
    - "year-N mid-cycle margin" against "post-year-5 terminal margin";
    - stage 3 keeps by default and revises only for a fact error;
    - stage 3 sees the median sample's cited fact IDs and labels, but no prose.
11. `delta_pts_scale_suspect` (annotate) when 0 < |d| < 0.05 or |d| > 50.
12. **The pull record** covers every input (margins, long run, discount, terminal_g, terminal_ronic) and the Base value, pre and post.
13. **The memo verifier** adds a prose-number check: numbers with %, $, x or bps not matching the table or a cited fact, years and dates excluded. Reported as `memo_prose_number_mismatch`; labelled mismatches still gate.
14. Unfilled contract numbers make a result non-actionable (`contract_fields_unfilled`) and must be resolved before any book-wide run.
15. The beyond-year-5 expiry alternative is renamed `early_fade_stress`.

**Accepted (R26-G, the pilot):**
- **The canary paired pull** `(m(+3) − m(−3)) / 6` per input and for the Base value, with constructed and real consensus reported apart.
- **Evaluation:**
  - denominators over callable names, with data no-calls (PACS) under a separate coverage metric;
  - thresholds as fractions (10 of 12 becomes ≥ 83% of callable);
  - reader disagreement adjudicated, and "incoherent" counted after adjudication.
- **Smoke** extended to one full end-to-end name (MSGE, all four stages) before the stage-1 batch.

**GPU order:**
1. Stage P research for the 5 new names may start now (both reviews; it does not depend on these fixes).
2. The full smoke after F and G.
3. Stage 1 for 12.
4. Stages 2–4, then the canary.
- **R26-F built** (`9da836f`): items 1–15 of the cross-check 23 rulings. 305 r26 tests pass; full suite has the same 42 failures. Pushed after a scan.
  - Rulings: aggregator lines are cut from the stage-2 pack; stage 4 shares the count-only view; the strict association is accepted, with the usable fraction to be measured in the end-to-end smoke.
- **R26-G built** in the pilot folder: the end-to-end smoke, the paired canary, callable-name denominators, adjudication.
  - The pilot tree was re-pointed to `9da836f`. Pilot tests: 208 passed; 2 known failures in older modes (their evidence grew after their runs).
- **Stage P launched 2026-10-19 19:27** (`RS2-P4-R26-PREP`), with 3.0 GB free after the operator closed the IDE: the draw and P1–P4 for the 5 new names, and P5 blind packs for all 12.
  - The blind packs are rebuilt at the final tree before stage 1 if the tree changes.
- **Stage P finished 2026-10-19 21:18** (about 2 h). P1–P4 are done for OGE, HNRG, PTCT, LPG and ITGR.
  - **P5 blind packs:** 7 pass and 5 fail the leak audit (fail-closed, as designed).
  - **Real leaks the sentence filter missed:**
    - BUD: estimate revisions ($4.99 to $4.91) and the stock's move on the day in its catalyst brief;
    - OGE: "Buy ratings ... PT $52".
  - **False positives from unit-blind matching:**
    - PACS: +$2.5M rent against EPS $2.50;
    - GOLD: $11.6 million against 11.6x;
    - HNRG: beta 0.444 against $0.444B, and 23% against 23.08x.
  - **Fix in progress:** the generic filter learns rating, price-target, estimate-revision and price-move language, and the audit becomes unit- and scale-aware. Then P5 is rebuilt for the 5.
- **Leak-audit fix** (`ddf133e`, `ff55ed3`):
  - a generic `analyst_view` sentence rule;
  - unit- and scale-aware matching, with 6-significant-digit removed numbers;
  - filed EPS counts as filed support (OGE $2.32 equals the filed 2.3244).
- **The P5 rebuild of all 12 at `ff55ed3`** (earlier P5 outputs kept with the suffix `_tree9da836f`): 11 pass. PTCT is stopped by the audit on a real price leak ("last at USD 59.24 on Nasdaq") that the filter missed.
  - Ruling: the filter learns share-price phrasing, and USD is treated as $.
- **Ruling:** `family_not_built` (OGE, HNRG) is valued as operating, stamped. The plan records that "family not built" is the code-only engine's status, and the AI desk values these names with the operating formula. Only a missing family is `family_unresolved`.
- **Final P5 at `3d574bf`** (the price-statement filter, USD as $; `family_not_built` valued as operating): all 12 blind packs pass the leak audit (earlier outputs kept with the suffix `_treeff55ed3`).
  - Coordinator fix `58d7bdd`: a missing bridge input (LPG files no tax provision) is a recorded data no_call (`bridge_unavailable`), never a defaulted rate.
  - The pilot was re-pinned; readiness: "all names ready".
- **Smoke, then end-to-end smoke (MSGE, all four stages), launched 2026-10-19 22:00** as `RS2-P4-R26-SMOKE`.
- **Smoke PASS** (22:16, 16 min). **End-to-end smoke PASS on MSGE** (23:56; stage 1 65 min, stage 2 19, stage 3 4, stage 4 12).
  - **Stage 1:** 157 facts, 75 usable (48%).
  - **Stage 2:** three Base values $36.40, $38.69, $37.57 (spread 6.1%; price about $79). The Base path is coherent: op margin 14% then 13.5%, normalized in year 3 at median + 0.7 pt, long run 13%, labels partly_structural / mid.
  - **The stage-2 view filter worked:** the summary sentence with the price and market cap was dropped, and three consensus or market-cap facts were withheld.
  - **Defects found** (stages 3–4 only; the fix is building):
    - **(a)** One unreachable crux entry (terminal_g) voided an otherwise strong crux (long-run margin 6.7% against an implied 23.4%; coe 9.27% against an implied 5.77%), giving `no_call`. Ruling: one correction turn for an invalid crux (drop or replace the failing entry), then no_call.
    - **(b)** The prose-number check flagged numbers that legitimately come from the stage-4 inputs. Ruling: whitelist every number present in any stage-4 input. The labelled check stays, and it correctly caught "$37.23" (the early-fade stress) labelled as the Base value ($37.57).
    - **(c)** The dossier number audit stamped `number_audit_not_run`; the cause is being found.
  - Noted: MSGE's tax rate is measured at 38.1% and clipped to 35% (stamped); the clip range is to review.
- **Stage 1 for the 12 names launched 2026-10-19 23:57** (`RS2-P4-R26-STAGE1`, tree `58d7bdd`). Stages 2–4 run later on the fixed tree, after the cheap smoke.
- **Smoke-defect fixes** (`f761545`):
  - **(a)** one correction turn for an invalid crux, with both cruxes kept;
  - **(b)** the prose-number whitelist covers every stage-4 input;
  - **(c)** `number_audit_not_run` was the pilot driver omitting `facts=` in its `run_stage2` calls. The driver is fixed; with facts the audit finds 85 removed numbers for MSGE.
  - The byte-identity test the builder reported failing passes on the coordinator's run.
  - Before stages24: re-pin to the fixed tree, run the full suite once the GPU is free, and run the cheap smoke again.
- **Stage-1 progress (11:48):** 9 of 12 frozen. Stage 1 is slower than estimated (OGE 94 min, HNRG 127 min; 167 and 214 facts). Expected finish 14:30–15:30.
  - **Correction:** stages 2–4 take about 35 min per name (end-to-end smoke: 19 + 4 + 12), not the 10 the plan assumed, so one 12-name iteration is about 6–7 h.
- **Operator hold (2026-10-20):** after stage 1 completes, start nothing. The operator reboots first.
  - **On resume:**
    1. confirm 12 frozen dossiers;
    2. re-pin the pilot to `f761545` (`design.P4_R26_TREE_COMMIT`, checkout `tree_p4r26`, re-fill the run file plus prep pins);
    3. run the full rs2 suite;
    4. run the cheap smoke;
    5. launch `stages24` (iteration 1), then the canary;
    6. run the mask, the two readers and the scorecard.
- **Stage-1 crash (2026-10-20 12:46).** Windows flagged low virtual memory. The pilot python runner had grown to about 23 GB (event 2004), and Windows closed programs, including the Claude app.
  - The runner died with a MemoryError while recording a stop on LPG and unloaded the model. There was no reboot.
  - **State:** 9 names frozen normally. PTCT is frozen INCOMPLETE (no_tool_call) with 0 facts; LPG was INCOMPLETE (no_tool_call) with 137 facts, 29 usable; ITGR was not run.
  - **Operator rulings:** fix the leak (root cause plus an RSS guard `memory_cap_exceeded`), verify it, then re-run PTCT, LPG and ITGR stage 1.
  - The PTCT and LPG re-runs are recorded as defect-context re-runs: the crash, and a 0-fact dossier.
- **Leak investigation:** replays of the stage-1 sessions peak at ≤45 MB (LPG, HNRG, PTCT), with no growth across names. The 23 GB python is most likely the other workstream's Shadow-V4 grader (`grade_depth_verdicts.py`, which ran 12:27–13:02 and spans 12:46); Windows' pid cannot be mapped to prove it.
  - Precautions added: a runner RSS/commit guard (`memory_cap_exceeded`, 4 GB), and gc plus a commit log per name (29 MB observed). rs2 memory-bound test `656da7d`.
  - Shadow-V4 runs daily from 07:30; GPU runs should avoid overlapping its grader.
- **Operator ruling:** use Ollama 0.40.6 (auto-updated after the crash) for the rest. Release notes show no change to raw generate, sampling, KV, num_ctx or MTP, but list two unspecified llama.cpp updates. Recorded in the run file: 9 names on 0.40.3; PTCT, LPG and ITGR on 0.40.6.
- **Stage-1 re-run of PTCT, LPG and ITGR launched 14:32.** The earlier PTCT and LPG outputs are kept with the suffixes `_incomplete_run1` and `_oom_run1`. The runner script was re-pinned for the reviewed guard.
- **Stage 1 complete 2026-10-20 17:56** (re-run, Ollama 0.40.6; runner commit stayed at 29–38 MB per name).
  - PTCT: 125 facts, 63 usable (90.7 min).
  - LPG: 73 facts, 25 usable (40.1 min).
  - ITGR: 102 facts, 41 usable (72.4 min).
  - All 12 dossiers frozen. The operator hold before stages 2–4 applies (reboot first).
- **Shadow V4 (engine-v2 nightly, wt-d5-shadow):** the operator retired it; task `RS2-Shadow-V4` unregistered (definition saved as `wt-d5-shadow/RS2-Shadow-V4.task.xml`). The v2.1 paper books rn_v4* no longer update. The worktree and its output are kept, and the books left as they are, pending the operator.
- **Before iteration 1 (2026-10-20 19:00):** the full rs2 suite at `656da7d` gives 44 failures, the 42 plus the two pinned byte-identity tests.
  - The coordinator rebuilt the GEV fixture pack on the **untouched pre-revision code `6bc2ad0`**: same new hash `891ef3…` as the current code. So the other arms remain byte-identical between old and new code; the pinned hashes went stale through the fixture's data or time dependence, not through our code. The pins are to update.
  - The pilot was re-pinned to `656da7d` as iteration 1. `fill_run` now allows re-pinning the current iteration before any stages-2–4 run of it.
  - Launched `RS2-P4-R26-ITER`: smoke, then `stages24` iteration 1 (about 6–7 h).
- **Iteration 1 ran (2026-10-20 19:00 → 10-21 00:18). It is contaminated by code defects and does not count as a design iteration** (plan v4: defects get a same-seed re-run). Raw per-name outcome:
  - MSGE: overvalued, Base about $39.4 against price $79.6, spread 11%.
  - BUD: undervalued, spread 18%.
  - GOLD: undervalued, spread **85%** (Base samples $65.5, $73.2, $127.8).
  - ITGR: valued, spread 33%.
  - TASK, DAC: `no_call crux_invalid:not_reachable` even after the correction turn (values about 2.4× and 3× price).
  - MCY: `no_call`, a malformed corrected crux.
  - PACS, LPG: the expected data no-calls.
  - OGE, HNRG, PTCT: **all 9 samples `desk_error` with no error text** (a code defect, recorded as no_call instead of stopping).
- **Defects:**
  - **(1)** desk_error on the three new names (cause under investigation);
  - **(2)** fail-fast did not treat an all-sample desk_error as a defect;
  - **(3)** the memo verifier read no verdict from any memo ("Verdict: overvalued" is MSGE's first line), so `memo_verdict_mismatch` everywhere is a parser bug;
  - **(4)** the crux form message lists stale inputs;
  - **(5)** reveal.json does not record per-entry crux verification.
- **Design question under measurement (6):** whether, for large mispricings, *no* offered crux input is reachable by the price-implied solver. If so, the crux rule makes a no_call inevitable. This is the open "price beyond every input's reach" policy.
- **Rulings on cross-check 24** (ChatGPT and Gemini both: A2 and B2 modified), approved by the operator and frozen as **SPEC section 9, Amendment 1**.
  - **A2 is recorded as a post-result protocol amendment,** per ChatGPT: the registered rule named `oe_base`, so Gemini's "bug fix" framing is rejected.
  - **B2 with a joint-reachability ray, reachability shown up front, three outcomes, a non-actionable beyond-reach verdict with a 4-part review, and a syntax-only crux repair.**
  - **The per-name actionability rule:** spread ≤ 20% and unanimous direction.
  - **Rejected:** LPG tax as 0 (absent is not 0).
  - **Deferred:** a medium-term margin as a crux input.
- **Amendment 1 built and audited.**
  - rs2 `05d925b` and `15669dc`: up-front reach, the joint ray (121-point grid with bisection; the builder showed the coordinator's suspected non-monotone defect was a misreading, so beyond-reach was correct), three outcome codes, a syntax-only crux repair, per-name actionability.
  - The pilot: the draw replacements **KOF, DAR, VSNT** (base_cf 0.502, 0.709, 1.602) and the new holdout **CTVA, NHC, TTAM, CLDT**. Passed over: CBL, DEA, SM (no base_cf; a missing base_cf is not positive, per section 9); NREF, FRO (no x_L).
  - The scorer reports coverage apart and counts outcome codes.
- **Iteration numbering:** runs_p4r26/1 could not be moved (a file handle held by another process), so iteration 1 stays in place, recorded NON-COUNTING. The counted re-run is **iteration 2**, and `iteration.max` is raised 3 → 4 so three counted iterations remain, as registered. This is noted in the run file.
- **Launched 2026-10-21 02:57** (`RS2-P4-R26-AMEND1`, tree `15669dc`): prep for KOF, DAR and VSNT, then smoke, end-to-end smoke, stage 1 for the 3, and stages 2–4 iteration 2 for all. About 14 h.
- **Stage P for the replacements stopped (03:17).** KOF and VSNT P3 deep research aborted: 3 of 5 and 4 of 5 topics had no usable sources, so the guard refused to write a brief from model recall.
  - Cause: SearXNG upstream engines blocking us after two days of heavy research. DuckDuckGo shows a CAPTCHA (never bypassed); Dogpile and Yep deny access; gabanza is down.
  - A container restart cleared the in-memory suspensions, but the upstream blocks stand. DAR P3 succeeded at 03:12.
  - **Coordinator decision (overnight rule):** wait. The chain is rescheduled once at 2026-10-21 09:00 (`RS2-P4-R26-AMEND1`); the stop records are kept with the suffix `_searchblock_0321`.
- **Search fallback restored (operator approved, 2026-10-21 ~03:45).**
  - The pilot tree had no `.secrets.json`, so its research ran on SearXNG alone, with none of the keyed fallback (Serper, Tavily, Exa) the main repo has. `tree_p4r26/.secrets.json` is now a **hardlink** to `rs2-local/.secrets.json`: one secrets file, git-ignored, contents not read. Keys present: serper 2400, tavily 900, exa 300.
  - Note: the tree keeps its own `cache/quota.json` ledger.
- **Extra free engines probed** on a temporary default-settings SearXNG (port 8899, since removed), with two finance queries each. Every candidate refused or returned nothing:
  - mojeek, qwant and presearch: access denied;
  - startpage: timeout or CAPTCHA;
  - brave: too many requests;
  - yahoo: protocol error;
  - google: 0 results;
  - google news and startpage news: CAPTCHA;
  - qwant news and mojeek news: access denied.
  - **None added** (refusals respected, per the settings file rule). The 09:00 retry now has the keyed fallback.
- **The 09:00 retry failed the same way (09:07).** The keyed fallback never fired: `deep_research.run_topic` ended the chain on any returned URL, so a SearXNG answer whose links were all low-trust or uncited was accepted, and the topic was then voided as `::NO SOURCES::`.
  - Fix rs2 `bb0d7ab`: a backend counts as having answered only when it leaves usable sources (the same test the topic applies afterwards). Two tests.
  - A stray smoke test from a mistaken 11:55 start of the chain was still running on the old tree after the task was stopped; it was killed and its records kept with the suffix `_killed_1200` / `_pre_bb0d7ab`.
- **Relaunched 12:00 on `bb0d7ab`.** KOF P3 done (12:10, all SearXNG). VSNT P3 stopped at the 900 s research bound (12:25): two topics recovered on Tavily, two found nothing on any of the four providers, and every attempt re-runs the summary.
  - Probe: Serper and Exa answer directly (10 and 5 results) and through LDR's engines; five reruns of the bear-case topic gave sources on every provider except one Exa attempt (0 sources in 38 s). The empty answers are transient; LDR logs nothing about them.
  - **Open item:** when LDR's searches all return nothing, its summary still cites "[1]" from model recall. Our guard discards it correctly. The cause (most likely the generated sub-questions for the topic) is to be measured after the run, with the GPU free.
- **Relaunched 12:41.** VSNT P3 done (12:58) with one topic of five declared NOT RESEARCHED ("What Changed in the Last 12 Months"), under the existing gap rule. KOF and DAR P4 done.
- **P5 (13:19): KOF passes; DAR and VSNT fail the leak audit on false positives.**
  - DAR: "insider: 1.18%" matched the long-run owner-earnings path value 1.18 ($B).
  - VSNT: ten hits, all the company's own FY26 revenue guidance: $6.2–6.45B in the Q2 8-K (Item 2.02, filed 2026-08-06, verbatim in the pack's GUIDANCE section) and $6.15–6.4B from the Q1 release, repeated in the catalyst and research briefs. The consensus revenue ($6.249B, $6.368B, $6.439B) follows that guidance.
  - **Coordinator rulings (rs2 `b1ac1e9`):**
    - (1) The numbers of the company's own 8-K Item 2.02 earnings releases of the trailing year, fetched verbatim from EDGAR by code, are filed support for the leak test, as filed EPS already is. SPEC section 5 excepts "the same number as a filed fact", and SPEC section 2 names a guidance horizon as a fact's duration, so company guidance is a legitimate blind input. The narrative filter (consensus, analyst, price language) is unchanged, and a consensus number absent from the releases still leaks.
    - (2) A removed fact that is a dollar amount (the long-run `e5`, `oe5`, `oe_path`, `oe_base`, `revenue_path`; any `revenue_b` / `earnings_b`) is never matched as a percent or a multiple. The GOLD unit test's second half moved from `e5` to the margin fact `m5`, which keeps its intent.
  - Tests: 7 new; full suite 44 failures, the 42 on record plus the two byte-identity pins already known stale (the revision-26 pin fails on unmodified HEAD too).
  - The 10 names that passed P5 on earlier trees are not rebuilt: the rulings can only add exceptions, never a leak.
- **Relaunched 13:38 on `b1ac1e9`:** P5 for DAR and VSNT, then smoke, end-to-end smoke, stage 1 for the 3, and stages 2–4 iteration 2.
- **P5 at `b1ac1e9` (13:38):** DAR passes (0 leaks). VSNT keeps 4 leaks, all "$6.4 billion" from the research brief's earlier range $6.15–6.4B. Neither earlier filed release (FY25, 2026-03-03; Q1, 2026-05-14) states it, so the audit was right to fail closed: the claim cannot be told from the consensus ($6.439B, $6.368B).
  - **Coordinator ruling (rs2 `abd2052`):** the narrative filter gets a second rule, `removed_number_collision`. A narrative sentence holding a number that equals a removed-class number at its own precision and unit, with no filed or derived support (the 8-K releases included), is dropped and listed. The blind stage loses the sentence, never the pack. Filed, derived and aggregator lines are not filtered, and the leak audit still runs afterwards as the backstop.
  - Packs that already passed the audit have no such collision, so their blind text is unchanged by this rule; they are not rebuilt.
  - Tests: 3 new; full suite unchanged (44, the same names as at `b1ac1e9`).
- **Relaunched ~14:00 on `abd2052`:** VSNT P5, then smoke, end-to-end smoke, stage 1 for KOF, DAR and VSNT, and stages 2–4 iteration 2.
- **Stage 1 restarted 20:35 (tree `abd2052`)** after DAR was re-researched with a stable connection (all 6 topics, 24 sources). DAR's earlier pins (never used by a model run) are kept in the run file as commented "superseded" lines; backup `run_p4r26_backup_pre_DAR_repin_2035.txt`.
  - Root cause of today's empty searches: the Wi-Fi dropped for 1–40 minutes about hourly (WLAN event log); every DNS lookup failed on the host and in the SearXNG container. Network guard built (rs2 `24ff859`; research stops as an infra failure while offline; stage-1 calls wait up to 45 min and retry). Not in this run's tree, to keep the smoke pass; it goes into the next iteration. The operator fixed the connection.
- **KOF stage 1: INCOMPLETE after 80 min, 34 facts (26 usable).** Turn 20 hit the 98,304-token window (prompt 42,663 + output 53,460; `done_reason: length`): 130k of its 145k characters were thinking, and the cut call held 39 facts (38 complete). The harness labelled it `no_tool_call` and froze the dossier.
  - **Ruling (cross-check with Gemini, coordinator):** KOF is counted as a scored design failure (`context_exhausted`), not re-run; a post-result salvage would be a re-run. Stages 2–4 run on its dossier. The report adds a disclosed 11/12 side table; the registered pass bar stays on all 12.
  - **Next-iteration fix, first:** a per-turn output cap (`num_predict` = min(12–16k, remaining window − 2k)), salvage of complete facts from a length-cut call (through the same verifier), one recovery turn, and the correct stop label. Zero change on healthy turns. Deferred, as separate labelled changes: eviction of old fetched pages, a prompt-level batch cap.
  - **Found while checking:** most unusable facts fail the proximity rule, not the quote match, and many trip on the company's own name word ("gold", "integer", "inbev" read as metric terms). To measure after stages 2–4.
- **Iteration 2 stopped at 04:07 (exit 8) on KOF:** no positive share count (a 20-F filer, DATA 2 filed as 0), so all three stage-2 samples ended desk_error. Fix rs2 `afec2b0`: `shares_unavailable` is a data no-call decided before any model call. The harness accepts a tree change only as a new iteration, so DAR and VSNT have no stages-2-4 result in iteration 2.
- **Iteration 2 scored on 9 of 12 (7 callable; PACS, LPG data no-calls; the scorer now counts `bridge_unavailable` and `shares_unavailable` as data no-calls; the masker no longer stops on an input that equals a rounded result): FAIL.** Coherent 0 of 7 (every name questionable on criterion 4, duration); incoherent 1 (ITGR, an invented "MRI business"); median spread 17.6%; unanimous direction 6 of 7; pull 0.000; loops 0; memo verdict mismatches 0. Spread above 20%: GOLD 83%, MCY 43%, ITGR 33%. Readers agreed on 27 of 28 ratings; GOLD c4 adjudicated questionable. Both readers could recover some masked numbers from fact value fields (masker to fix).
- **Cross-check 25** written (sample spread, criterion 4, the readers' faults); iteration 3 waits for its rulings.
- **Cross-check 25 replies (Gemini, ChatGPT) and the rulings (coordinator; the operator delegated the decisions with a Friday 2026-10-23 freeze):** SPEC section 10, Amendment 2.
  - Adopted where both agreed: S3 attribution, S4 (spread above 20% stays non-actionable), S2 and S5 rejected, a code-owned discount rate, criterion 4 rewritten as a durability thesis (ChatGPT's wording), ITGR's invented description treated as a real failure.
  - Ruled on the disagreement: `terminal_ronic`, the baseline and the long-run margin stay analyst-owned (ChatGPT; Gemini's defaults would re-create the default anchoring the earlier designs suffered from). Code derives the growth-trajectory label (Gemini). A path-dominated crux is flagged non-actionable (Gemini); ChatGPT's driver-level stress test deferred.
  - **S3 on iteration 2 (real desk):** GOLD's spread comes from years 1-2 (only-G spread 28%) and the long-run margin (25%); MCY's from the long-run margin (19%); ITGR's from the normalized state (11%) and the discount rate (18%, now removed); BUD's from the terminal return (21%). The discount rate explains only ITGR.
  - **Freeze rule:** iteration 3 is the last; approved for the book-wide paper run at 0 incoherent and at least 70% coherent under the amended rubric, else frozen as paper-only, low confidence. Real money stays gated by KIS_HALT and a paper record.
- **Built (rs2 `31dc1a8`, merged with the approved `mri/query-retry-on-lock` as `7cc1f57`):** pack revision 27 (Amendment 2 A and B). Pilot: the masker no longer leaks values through fact value fields or per-share prose, and shows the durability thesis; READER_RUBRIC.md criterion 4 amended (v1 kept). Tests: 18 new (iteration 3), 6 (attribution), 10 (masker); full rs2 suite 44 failures, the known set.
- **Iteration 3 launched 2026-10-22 14:25** (`RS2-P4-R26-IT3`, tree `7cc1f57`): smoke, stages 2-4 for all 12 names (stage 1 frozen), the canary. The first name doubles as the end-to-end check of the stage 3-4 changes (fail-fast).
- **ChatGPT architecture note (2026-10-22, shared link), checked against the code.**
  - **Confirmed defect:** the stage sessions send no system message, so `ollama_raw.template_messages` inserts the model tag's SYSTEM text: the v33 underwriting charter (16,269 characters, 2,400 words; mentions price 12 times, momentum 15, Kelly 8, reverse DCF 3, "SECTION" 22). Its sha256 `ff033c25…` is the `system_sha256` of iteration 3's stage-2 turns. Every revision-26 stage, the blind forecast included, has been instructed by a charter written for the one-session underwriting design. Not a data leak (no price or consensus number reaches the blind stage), but instructions that contradict the stage, lengthen every prompt, and ask for work other stages own.
  - **Already fixed:** `max(r, RONIC)` in the funded long run (`ronic_start_from_terminal`).
  - **Recorded as the revision-28 roadmap (after the freeze):** a deterministic preflight; a price-blind sensitivity map choosing which drivers Qwen researches; typed driver claims with an `unresolved` status; decision robustness alongside spread; deterministic memo tables; one-variable-at-a-time model-setting tests.
  - **Coordinator proposal to the operator:** iteration 3 unchanged. If it scores below the freeze bar, iteration 4 on Friday with one change only (a short stage-specific system message per stage); freeze on the better-scoring iteration. If iteration 3 passes, the charter fix is the first change after the freeze.
- **Iteration 3 result (2026-10-22, scored ~22:15): FAIL on coherence alone.** All 12 names have a result; loops 0; **0 incoherent** (was 1); coherent **1 of 9** (MSGE; every other name questionable); median spread 16.8%; unanimous direction 8 of 9; pull n/a; memo verdict mismatches 0. Readers agreed on 34 of 36 ratings; DAC and ITGR criterion 2 adjudicated questionable. Data no-calls PACS, LPG, KOF. Actionable 0 of 9 (contract fields 9, spread above 20% 4, path-dominated 2, beyond reach 2). Canary done 23:12. The recurring faults: normalized premiums argued from short evidence, adjusted-basis facts defending GAAP margins, memo prose contradicting inputs, figures not in the dossier.
  - **Valuation-arithmetic causes of the large undervaluations (measured, not fixed):** DAR's cash conversion κ = base_cf / X_0 = 4.5 multiplies the margin recovery, with its tax clipped from −15% to 0; VSNT, a shrinking business, carries +1.5% terminal growth and a 22% margin forever. To be measured offline on the frozen forecasts and annotated non-actionable; the fixes need the D2 ruling.
- **Amendment 3 registered (01:30, SPEC section 11)**, adopting ChatGPT's protocol, with the disclosure that iteration 3's score was read first. Built: rs2 `1484ea2` (pack revision 28; `r26_late.STAGE_SYSTEM`, a test that the charter never reaches a rendered prompt; r26 tests 458 pass; full suite the 44 known failures). **Iteration 4 (the comparison) launched 01:38** with `RS2-P4-R26-IT3` (smoke, stages 2-4, canary), on the frozen stage-1 dossiers.
- **Offline engine measurement on iteration 3's frozen forecasts (2026-10-23; every stored median Base value reproduced exactly; `scratchpad/defects/results.json`).**
  - **The year 5 → 6 cash-flow jump (open since 10-17) is still in the 25.2 desk:** `kappa = base_cf / (rev_L·x_L)` scales the years-1-5 owner earnings (`financial_model_tool.py:2111-2112`, `:585`), but the long run starts from `e5 = R5·m5` **without kappa** (`:597-606`). DAR's flow drops 4.99 → 0.85 at year 6, MCY's 1.34 → 0.54; DAC's rises 0.43 → 0.54.
  - **kappa = 1:** DAR −48% (3.67× → 1.89× price), MCY −16%, DAC +11%, others within 6%. **Tax floor 21–25% (DAR clipped from −15% to 0):** DAR −18 to −21%. **VSNT terminal growth 0 or −2%:** −3 to −6.5%. All three on DAR: 1.21–1.26× price.
  - **After all three, the large gaps remain:** DAC 3.1×, GOLD 3.1×, VSNT 4.2×, TASK 2.1×, MCY 1.6×. They come from the forecasts (DAR's 21% margins against a filed 4.5%, VSNT's 20%+ margins on a shrinking business, GOLD's growth), not the desk.
  - Ruling: the kappa / year-6 inconsistency is a real-money desk defect, fixed after the freeze with the D2 ruling; until then every verdict with kappa outside [0.67, 1.5] or a clipped tax rate is annotated non-actionable (code only).
- **Iteration 4 result (Amendment 3 comparison, scored 2026-10-23): FAIL, the same pattern as iteration 3.** 0 incoherent; coherent **0 of 9** (iteration 3: 1 of 9); median spread 16.6%; direction 8 of 9; spread above 20% 4; unknown fact ids 2 (iteration 3: 4); path-dominated 1, beyond reach 2. Readers agreed on 28 of 36; 8 adjudicated by the iteration-3 standard. Stage-2 prompt tokens 0.92M vs 1.07M (−14%); stage-3/4 output −38%/−25%; runtime 368 vs 392 min. Median Base/price: GOLD 1.6× (3.8×), VSNT 3.6× (4.25×), others close. Two of the memo_number_mismatch flags are verifier false positives (memo "5.2%" against table "5.2%", a rounding comparison bug).
  - **Reading (no winner on score, per Amendment 3):** the charter was a real defect and its removal is adopted on its merits (leaner, somewhat less extreme, nothing worse in kind). It was not the coherence problem: under both, the analyst argues margin premiums from short evidence and its memo drifts from its inputs.
- **FREEZE (coordinator, 2026-10-23, under the registered rule):** revision 26 at pack revision 28 (rs2 `1484ea2`), **paper-only, low confidence.** Below the 70% bar in both iterations. Known defects carried: premium-from-short-evidence, memo drift, the kappa / year-6 desk inconsistency, the clipped tax rate, high values on hard names, the verifier rounding bug, the unfilled contract fields (every verdict non-actionable), the stage-1 context overflow, the proximity rule. The holdout (CTVA, NHC, TTAM, CLDT) stays untouched.
- **Direction after the freeze (cross-check with ChatGPT, coordinator rulings 2026-10-23):** a factor-led, AI-supervised design is the next candidate (`SPEC_factor_led_v1.md`, draft). The screener is the primary selection engine and the baseline; deterministic risk and exit rules; Qwen investigates, interprets, discovers risks and monitors, with no unconditional veto (verified hard stop → registered restriction; uncertain concern → escalation with a bounded buy pause; silence is not a signal); valuation is diagnostic until it earns authority. Components are added one at a time (A screener, B + deterministic risk, C + AI investigation, D + AI forecasts, E + valuation), each judged on incremental value. Prerequisites: baseline A on the point-in-time history; a probe of Qwen 3.8's knowledge cutoff (AI rungs can only be tested historically after it, otherwise prospectively). Corrections: the deployed model is Q5_K_M (not Q4); the Phase 6 real-event recall was 6 of 20 strictly (8 of 20 on manual review) against 18, on Muse Glimmer.
- **Post-freeze work (2026-10-23):** desk diagnostics committed (rs2 `c255803`: verifier accepts the printed-table rounding; tax rate from the measured multi-year median instead of clipping, else unavailable; `cash_scaling_out_of_band` non-actionable for kappa outside [0.67, 1.5]; `terminal_growth_positive_for_shrinking_business` annotated). Iteration 3 and 4 canaries: zero pull under ±3-point consensus shifts on all 4 names. **Qwen 3.8 knowledge cutoff ≈ mid-April 2025** (band 2025-02 to 2025-06): AI rungs are tested historically on dates from 2025-10 only.
- **Baseline A (2026-10-23; `scratch/baselineA/REPORT_baselineA.md`):** the production screener replayed point in time, 2017-2025, research_now ~58 names. Whole window: excess over the universe +2.5% (t 1.0), **factor alpha −0.1% (t −0.1)**; 2017-22 −1.2% (factor alpha −1.9%); 2023-24 +14.4% (factor alpha +13.4%, t 3.2); 2025 +2.2%. Turnover about 3.2× a year; net of 60 bp the whole-window excess is +0.4%. Sharpe 0.56 against the universe's 0.44; return 12.8% against SPY's 15.0%. **The screener is a factor tilt, not a stock picker; its edge is the 2023-24 regime; it fails Addendum Z 10's bar.** Spot-checked by the coordinator against `data/s5_yahoo.json`. Full suite on rs2 `c255803`: the 44 known failures.
