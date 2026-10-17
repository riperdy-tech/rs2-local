# Step 1a report: the book census for the terminal reinvestment fix

*2026-10-18. Step 1a of `PLAN_terminal_reinvestment.md`. No GPU, no valuation. Script and full rows:
`scratch/rev23/terminal_d2/census_1a.py`, `census_1a.json`.*

## What was run

- **Names:** the 160 of the latest depth membership snapshot (`rs2-local/cache/depth_membership.jsonl`).
- **Data:** the compact SEC companyfacts store (`harness_smoke/store_all`, all 20,175 CIKs) with the code-only engine's classifier
  (`valuation/classification.py`, engine-v2.2 worktree, read only); five fiscal years filed before 2026-10-18.
- **Market cap:** the screener's `stocks.json`; where it holds 0 (DAC, GSL, MCY, KOF), price × filed shares.

## 1. The 24 "unclassifiable" names were a lookup gap, not a classifier gap

The 2026-10-06 census used the harness's sample ticker→CIK map, which holds no foreign filers. With the SEC `company_tickers.json` map
merged in (downloaded 2026-10-18 under the SEC standing approval) all 160 names load and classify. The SIC file the harness uses also lacks
most foreign filers; 27 names took their SIC from SEC submissions instead (EQNR 2911, BUD 2082, CWEN and ENLT 4911, HSHP and ECO 4412, …).

The classifier itself reads 20-F and 40-F (ANNUAL_FORMS) and IFRS facts. No change to it is needed for this.

Families now: operating 81, commodity 29, financial 20, family not built 30 (15 real estate, 10 pre-profit, 5 utilities).
"Family not built" is the code-only engine's status. The AI desk values all of these with the operating formula.

## 2. Case counts (thresholds are census reporting conventions: "material" is 10% of the base it is set against)

| Case (plan §2a) | n | Names |
|---|---|---|
| Financial route | 20 by family; see §3 | ACIC AII ALL ARX BFH CTBI ECPG HG HRTG JCAP MCY OPY PRCH RNR SLDE TOP UFCS UVE V WTM |
| Equity real estate | 13 | ALX AMT CBL CLDT DEA DRH HST LAMR LXP MRP OUT RHP STRW |
| Mortgage REITs (financial route) | 2 | CIM NREF |
| Utilities (rate base) | 5 | CWEN ENLT NJR RNW UGI |
| Depleting, oil and gas | 6 | APA GTE PNRG (ASC 932 costs-incurred tags in companyfacts); EQNR SM DEC (not in companyfacts: filing tables) |
| Depleting, mining (flag only, O4) | 4 | NEM BTG NEXA AAUC |
| Debt share δ ≥ 0.25 (O5 matters) | 35 | BHC .90, DEC .75, NREF .66, ECPG .65, GTE .63, DEA .59, JCAP .59, HOV .57, JBS .56, CWEN .52, DXC .51, STRW .50, WNC .46, DVA .45, IHS .45, R .45, SAH .44, UGI .44, HSHP .42, NEXA .41, NJR .39, QUAD .39, ALX .36, CMRE .34, OUT .34, CLDT .33, NGVT .33, THC .33, AMT .31, BUD .29, CLMT .29, DRH .29, KSS .29, SGU .28, DAR .27 |
| Lease principal ≥ 10% of owner earnings (step 2) | 23 | VLRS 1.77, VEON 1.21, EAT .76, MU .63, UMC .62, CHEF .28, GTE .28, MG .25, DXC .21, HAFN .21, BIP .20, JBS .19, TLK .19, IHS .17, SENEA/SENEB .17, KSS .16, ATI .12, EQNR .12, BUD .11, EFXT .11, OPTX .11, FET .10 |
| Acquisitions ≥ 10% of net income | 38 | ACA ALNT AMT BIP CHA CHEF CLDT CWEN DAR DDI DEC DVA EAT ENLT GOLD KOF LAMR MA MLR MTCH MTRN NEM NXT OUT PARR R RNR RUSHB SAH SGU STRW TASK THC TLK TRN UGI VSXY WTM |
| Base-year loss or ≥ 2 loss years in 5 | 44 | see `census_1a.json` |
| Five-year owner earnings ≤ 0 | 28 | includes ENLT, FRO, HSHP, VLRS, VEON, IHS, GTE, NEXA, the pre-profit names |
| Pooled capex / D&A ≥ 1.5 | 19 | ENLT 11.2, HSHP 11.2, EAT 6.0, VLRS 3.4, CHA 2.9, FTNT 2.6, … |
| Non-USD reporters (δ needs FX) | 6 | CHA KOF LPL RNW TLK UMC |

**Reading:** the cases are not marginal. O5 touches 35 names (22% of the book), leases 23, acquirers 38, and 28 names have
non-positive five-year owner earnings, which the desk's `base_cf must be positive` rule meets head on.

## 3. Classification findings for the AI desk's financial route (O3)

- **V is "financial" by SIC 6099 only.** No insurance reserves, no lending book, no deposits. A payment network; it must stay operating.
- **STT is "operating" by SIC 6282** (investment advice), but deposits are 81% of its liabilities. A custody bank; it must be financial.
- **SEZL and PGY** (consumer lenders, SIC 7389 and 7370) are "operating": the lending-book test was not evaluated because their loan tags
  are not among the classifier's LOAN_TAGS.
- **Financial by SIC only, legitimately:** OPY and TOP (broker-dealers), ECPG and JCAP (debt purchasers), PRCH and WTM (insurance holding
  structures). The balance-sheet tests do not cover brokers or debt buyers.
- **CIM and NREF** sit in real estate by SIC but are lenders; their lending-book share is not evaluated either.

**Rule for the desk route (no per-company list):** a name takes the financial route when a balance-sheet test confirms it (insurance
reserves ≥ 10% of assets, lending book ≥ 50% of assets with borrowings funding it, or deposits ≥ 50% of liabilities), or its SIC is a
broker-dealer or a credit institution and no test contradicts it. A financial SIC with no confirming balance sheet and no lending or
insurance activity (V) is operating, stamped. The loan-tag list is widened to the consumer-lending and mortgage-receivable tags.

## 4. Data coverage: what this store cannot supply

- **Capex is missing in companyfacts for 27 names** (shipowners DAC, GSL, CMRE, ESEA, INSW, ZIM, ECO; most REITs; NJR; MSGE; insurers),
  and D&A for 7 (PACS, SM, STT, DRH, …). The AI desk's packs carry them, from the filings or, where the filings lack them, the vendor's annual capex (DAC's pack: `owner_earnings_source: fy_ni+vendor_capex`). **Steps 2–6 take their inputs from the desk's
  pack facts, not from this store.** This census is for sizing the cases.
- **ASC 932 in companyfacts:** costs-incurred and reserve tags only for APA, GTE and PNRG. EQNR, SM and DEC need the 20-F/10-K
  supplementary tables (companyfacts drops dimensioned facts). Step 5 parses the filing tables.
- **REIT recurring capex** (`PaymentsForCapitalImprovements`) is tagged for DRH, HST and RHP only; the rest need the filing or the AFFO
  reconciliation, or fall back to total property capex with `recurring_capex_not_separable`.
- **Concessions:** no XBRL tag found for any name. The flag must come from filing text (step 5 scope), or from the analyst's research.
- **Implausible ratios kept, flagged:** KOF's cost of debt 2.34 and ZIM's 5.27 (lease interest over non-lease debt), TLK's acquisitions at
  83× net income, FRO's capex/D&A 22.8 (a partial depreciation tag). Census values, not inputs.

## 5. Consequences for the plan

1. **Step 6 is narrower than written.** Stored analyst inputs exist for about 20 names, not 160. Step 6 recomputes those offline; the
   full-book effect is first seen in the 160-stock GPU baseline, so step 7's registration must state the expected direction per case.
2. **Step 4 gets the route rule of §3**, with V, STT, SEZL, PGY, CIM and NREF as its acceptance cases.
3. **Step 3 must decide what happens to the 28 names with non-positive owner earnings.** Under O5 some turn positive; the rest stay
   refused by `base_cf must be positive`, which is a coverage hole for the baseline, not a terminal question. Recorded; not widened here.
4. **Leases (step 2) matter beyond IFRS:** US finance leases are material for EAT and MU.
