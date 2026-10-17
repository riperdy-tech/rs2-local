# Rulings: the outside reviews of step 1a (and step 1)

*2026-10-18. ChatGPT and Gemini reviewed `REPORT_census_1a_terminal.md`. Advice, ruled on point by point by the coordinator. Amends
`PLAN_terminal_reinvestment.md`; where the two disagree, this file wins.*

## Corrections to my own plan

1. **The sustaining charge S takes no (1 − t) factor.** (ChatGPT P1.) The plan wrote S = (F&D per boe × production − producing DD&A) ×
   (1 − t). That is wrong. Flow = NI + DD&A − capex exactly, and NI is already after tax with DD&A deducted, so the extra cash is
   sustaining capex − DD&A, pre-tax, in full. The tax shield of DD&A is already inside E. Corrected:
   **S = (sustaining capex − producing DD&A) × (1 − δ)**. The (1 − δ) follows O5: all net reinvestment is equity-funded at the measured
   debt share. Synthetic firm C2 (C with 40% debt at book) tests both parts.
2. **REIT total property capex is not a production fallback.** (ChatGPT P0.) It holds development and acquisitions, which g/RONIC
   already charges, so it double counts. Ruling: s comes from recurring capex that is separated, either the filed
   capital-improvement line or the recurring/maintenance capex of the REIT's own AFFO reconciliation. Where neither exists, the analyst
   may state recurring capex with a citation (a defined judgment input; code checks the citation). Otherwise s = 0, stamped
   `recurring_capex_not_separable`, and the total-capex value is reported beside it as a sensitivity, never as the value.
3. **Which D&A s adds back.** (ChatGPT P0.) E is X, which already excludes acquired-intangible amortization (for REITs: in-place-lease and
   above-market-lease intangibles). s uses D&A less that amortization, so nothing is added back twice.

## Accepted

| # | Point | Source | What changes |
|---|---|---|---|
| 1 | A 160-name routing table: classification, the evidence, the desk route, any unresolved reason, with counts by route; acceptance cases V, MA (operating), STT, SEZL, PGY, CIM, NREF, ECPG, JCAP (financial), RHLD | both | Step 1a addendum (below). RHLD now classifies operating on SIC 3572 from SEC submissions, against SIC 6199 in the 2026-10-06 census; the table records which is right and why |
| 2 | Wider LOAN_TAGS (notes and loans receivable, financing receivables, mortgage loans on real estate, purchased credit-deteriorated assets) | Gemini | Step 4 |
| 3 | The financial route bypasses O5 and the lease adjustment (debt there is the raw material, not funding for capex) | Gemini | Step 4: ECPG, JCAP, NREF leave the δ list |
| 4 | δ for non-USD reporters on one currency basis, with a registered FX source | both | **The FX owner already exists:** `stock-screener/scripts/fx_normalize.py` (balance sheet at the period-end rate, IAS 21; a proven-currency table; an unproven currency is a STOP, never a spot substitution). δ converts net debt with it. A name it does not prove (KOF, TLK, UMC are flagged `unreviewed_currency_mismatch` today) gets δ = 0, stamped `delta_fx_unproven`. One name checked by hand |
| 5 | Leases and debt on one definition: either both in debt (with lease interest in k_d) or both out | Gemini | Leases are out of δ and k_d. They are an operating cash cost handled in step 2, and lease interest is excluded from k_d. This removes the KOF and ZIM k_d artefacts |
| 6 | Before deducting lease principal, prove that ROU depreciation is inside the pack's D&A; under US GAAP operating leases it is not, and a deduction would charge rent twice | Gemini | Step 2: the per-name check is the gate for the deduction. EAT's capex/D&A of 6.0 suggests a partial D&A tag, which is checked first |
| 7 | The lease fix must hold in the fade and the terminal, not only in base_cf | ChatGPT | Step 2: trace BUD, EQNR, MSGE, PACS through all three periods; **synthetic firm I** (a lessee with recurring lease principal) must reconcile to its true value |
| 8 | Fragile denominators: report the pooled raw amounts beside every ratio; count invalid or unstable ratios | ChatGPT | Addendum. The ratios are already five-year pooled sums with positive-income guards; the raw amounts and an `unstable_ratio` count are added |
| 9 | Reserve coverage reported as identified / parsed / computable | ChatGPT | Step 5 |
| 10 | Concessions: no XBRL tag is not evidence of no concession; screen filing text and carry the unresolved forward | ChatGPT | Addendum: a full-text screen of the latest annual report of every name (SEC full-text search, standing approval) for concession, license term, PPA expiry and reversion, with positive, negative and unresolved counts |
| 11 | Count the `base_cf must be positive` refusals after the lease and O5 changes, separately and with reasons; do not weaken the rule to widen coverage | ChatGPT | Step 6. O7 does not weaken the rule: it states flows as levels where a growth rate on a negative base has no meaning |
| 12 | Track the acquired-amortization share of D&A as a diagnostic | Gemini | Step 3 diagnostic |
| 13 | Pre-register expected directions separately for REITs and acquirers | Gemini | Step 7 |

## Rejected

| Point | Source | Why |
|---|---|---|
| "In the fade E is GAAP net income, which deducts acquired amortization, so acquirers step down at year 6" | Gemini §4 | Not the desk. E is X, net income before acquired-intangible amortization (`consensus_reference.py`, base_ni); synthetic firm D's −1.7% is the dropped tax shield, not this |
| "Equity REITs are crushed because the terminal charges GAAP depreciation as cash" | Gemini §3 | That was design D. D2 handles it with the negative s of O6, which this file corrects (rulings 2 and 3) |
| Apply (1 − δ) only when net capex is positive | Gemini checklist | An asymmetric rule. Under constant leverage, a company that disinvests repays debt pro rata, and its equity flow is reduced by δ of the release. The symmetric form is the identity; the asymmetric one is a gate |
| δ on book weights because they are FX-invariant | Gemini §5 | Book equity is unstable after buybacks (MSGE 0.84 on book against 0.06 at market). FX is solved by the existing owner (accepted point 4) |

## Added to the work

- **Step 1a addendum** (no GPU): the routing table; FX-consistent δ for the 6 non-USD reporters; raw amounts and unstable-ratio counts;
  the concession text screen.
- **Step 1 harness:** firm C2 (levered depleter, testing S's tax and δ treatment) and firm I (lessee). Their baselines are added before
  step 2 starts.
