# Problem statement: reconciling owner earnings and the funded-growth terminal value in a DCF desk

*For outside review (ChatGPT, Gemini). This document is self-contained. Please read it all before answering.*

## 1. The system, briefly
We run an equity valuation pipeline for a real-money stock-selection system. Every company runs through the same three steps:
1. **A local AI analyst** (an LLM) reads a data pack: the company's filings, consensus estimates, macro anchors and population statistics.
   It chooses the valuation **inputs**: growth rates, margins, fade length, terminal growth and return on new investment.
2. **Deterministic Python code** (the "desk") computes the value from those inputs. The AI never does arithmetic.
3. **Code checks** annotate the result (plausibility, citations, consistency). They never silently override the AI's inputs.

**Our design rules, which any solution must respect:**
- The same method for every company. **No rule names or targets a specific company.**
- Every number is either a textbook method or is measured from the population. Nothing is tuned to make outputs look right.
- The AI chooses judgment inputs and code computes. A solution may add an input for the AI to choose, but it must be well defined.
- **Annotate, never silently gate.** Flags and reasons ride on the result; inputs are not clamped.
- Values are per share, in the **equity frame:** flows after interest, discounted at the cost of equity r.

## 2. The current formula
**Notation:**
- r is the cost of equity;
- g_T is terminal growth and RONIC_T the terminal return on new investment;
- F is the fade length in years;
- the base year is year 0.

**Years 1–5 (explicit), on owner earnings:**
- OE_0 = base_cf. The default is net income + D&A − capex, after SBC, for the base fiscal year.
- OE_t = OE_{t−1} × (1 + g_t), with g_1…g_5 chosen by the AI.
- Flow_t = OE_t − WC_t, where WC_t = intensity × the change in revenue (the working-capital investment).

**Years 6…5+F (the fade), on accounting earnings with funded growth:**
- **The year-5 earnings:** E_5 = consensus year-5 earnings × (OE_5 / consensus year-5 owner earnings). This is the analyst's year-5 owner
  earnings converted to earnings at consensus's earnings-to-owner-earnings ratio.
- **Growth** fades linearly from g_5 to g_T over F years.
- **Earnings:** E_t = E_5 × Π(1 + g) × k_t, where the margin factor k_t moves the earnings margin from its year-5 level to the analyst's
  `long_run_margin` by the end of the fade.
- **The return:** RONIC_t moves from the company's measured historical return (r_tc) to RONIC_T. The interpolation is on 1/RONIC.
- **Flow_t = E_t × (1 − g_{t+1} / RONIC_t)** (the value-driver form: reinvestment = growth / return).

**Terminal (from year 5+F):**
- TV = E_{N+1} × (1 − g_T / RONIC_T) / (r − g_T), with N = 5+F, discounted N years.
- **This is typically 36–76% of the total value.**

**Value:** PV(flows) + PV(TV), plus excess cash, divided by shares.

## 3. The problem
**Two different reinvestment conventions meet at year 5:**
- **Years 1–5** charge the company's *actual* reinvestment: owner earnings = earnings − (capex − D&A), less working capital.
- **Years 6 on and the terminal** charge a *theoretical* reinvestment of g / RONIC × earnings.

**When the two disagree, two things happen:**
1. **The cash flow jumps at year 6:**
   - up, when earnings ≫ owner earnings (capital-heavy companies);
   - down, when owner earnings > earnings (asset-light companies where D&A exceeds capex).
2. **More importantly, the terminal value inherits the theoretical convention.** For a company whose capex has run far above D&A for years,
   the terminal assumes reinvestment falls to g / RONIC of earnings. That may or may not be economically true.

**Measured on 8 real runs** (the year-6 flow over the year-5 flow):

| Company (type) | Year-6 / year-5 flow | Earnings / owner earnings at year 5 | Terminal share of value |
|---|---|---|---|
| Equinor (integrated oil, capital-heavy) | **6.57×** | about 6.7 | 66% |
| DAC (ship owner, newbuild programme) | 1.27× | 1.42 | 36% |
| TASK (business services) | 1.09× | 1.18 | 72% |
| GOLD (precious-metals trader) | 1.06× | 0.98 | 46% |
| PACS (skilled nursing) | 1.02× | 1.00 | 75% |
| MCY (insurer) | 0.76× | 0.97 | 61% |
| BUD (brewer) | 0.66× | 0.80 | 50% |
| MSGE (venues; D&A > capex) | **0.42×** | 0.68 | 43% |

**A worked example, Equinor, FY2025:**
- **The filed figures:** net income $5.04B, D&A $9.84B, capex $13.99B, so owner earnings ≈ $0.9B.
- **The analyst's inputs:** terminal g = 2.5%, terminal RONIC = 10%.
- **What the terminal assumes:** reinvestment = 25% of earnings (≈ $1.3B on $5B), against an actual net reinvestment of ≈ $4.2B (capex − D&A)
  plus working capital.
- **So the terminal free cash flow is about 4× the current owner earnings,** even though growth is only 2.5%.
- **The open question:** either the company is currently in a growth or replacement capex phase that will end, so the terminal is right; or
  its true sustaining reinvestment is much higher than g / RONIC implies, perhaps because of a reserve depletion and replacement treadmill,
  so the terminal overstates value. In the latter case, RONIC at the current capex is far below 10%.

**The fix we computed: option (b),** blending the fade-year flows linearly from the owner-earnings path into the funded path, with the
terminal unchanged.
- **The year-6 seam is smoother:** Equinor goes from 6.6× to 2.3×, MSGE from 0.42× to 0.83×.
- **Values move only −8% to +5%,** because the terminal (most of the value) is unchanged.
- **It treats the symptom, not the question of what the steady-state reinvestment really is.**
- **It also exposed a second seam:** working capital is deducted only in years 1–5.

## 4. What we think the real question is
**What is the right steady-state reinvestment (and so the terminal free cash flow) for a company, given:**
1. its historical reinvestment (capex vs D&A, and working capital, over the last 5–10 years);
2. its growth;
3. its return on capital;
4. its business type?

**For example:**
- **depleting-asset businesses** (oil and gas, mining), where "maintenance" capex replaces reserves and D&A understates the true sustaining
  cost;
- **capital-heavy growers** (shipping newbuilds, utilities, renewables), where capex above D&A is growth capex that should earn its return;
- **asset-light businesses** (services, software, venues), where D&A can exceed capex, or intangibles and acquisitions are the real
  reinvestment;
- **financials** (insurers, banks), where capex is irrelevant and "reinvestment" means retained capital to support growth.

We suspect the answer is a category- or situation-dependent method. Our design rules forbid ad hoc per-company rules, and prefer textbook
methods or population-measured parameters.

## 5. Questions for you
1. **Diagnosis.**
   - Is our framing right? Is the inconsistency between "actual reinvestment" in years 1–5 and "g / RONIC reinvestment" in the terminal a
     real valuation error, or is the value-driver terminal correct by construction once RONIC is chosen correctly?
   - What does the textbook literature say (Damodaran; McKinsey's *Valuation*; Koller, Goedhart and Wessels; Penman)?
2. **The right terminal reinvestment.** Which formulation should the terminal use? For example:
   - (i) the value-driver formula NOPAT × (1 − g/RONIC), with RONIC chosen consistently with the company's history;
   - (ii) the terminal reinvestment rate converging from the company's measured reinvestment rate to g/RONIC;
   - (iii) normalized maintenance capex (e.g. capex/D&A over a cycle), with growth capex separated;
   - (iv) something else.
3. **A consistency rule.** Is there a textbook identity we should enforce or check, for example implied RONIC = (change in earnings) /
   (reinvestment) over the explicit years, compared with the terminal RONIC? It must be stated so code can compute it and the AI can
   explain any departure.
4. **Categories.**
   - Should the method differ by business type (depleting assets, capital-heavy growth, asset-light, financial)?
   - If so, how should a company be assigned to a category by objective, filed data (SIC codes, the balance-sheet structure, capex/D&A over
     time), without per-company rules?
   - What is the minimum set of categories that captures most of the error?
5. **What the AI should choose against what code should compute.** Which of these quantities should be the analyst's judgment, and which
   should be measured from the filings or the population?
   - the sustaining reinvestment rate;
   - the RONIC;
   - the length of a capex cycle.
6. **Working capital in the long run.** WC is deducted explicitly in years 1–5 but only implicitly (inside g/RONIC) afterwards. Is that
   consistent? How should WC enter the fade and the terminal?
7. **Validation.** How would you test a new method without fitting it to the outcomes? Examples: synthetic companies with known economics;
   reconciling implied RONIC with history; the distribution of value/price by category before and after.

**Please be concrete:** give formulas, the definitions of every input, and how each would be computed from filed data. Say where you are
uncertain.

---

## 6. Our proposed design, "D": please critique it, don't just start from zero
**One reinvestment model for the whole forecast**, using the standard value-driver identity (reinvestment rate = growth ÷ return on new
investment), applied consistently from year 1 to the terminal. Each year's flow is

> **Flow_t = E_t × (1 − ρ_t)**

where ρ_t is the reinvestment rate: the share of earnings reinvested, including working capital and net capex.

**The rate along the path:**
1. **Year 5:** ρ_5 = 1 − Flow_5 / E_5, the reinvestment rate the analyst's year-5 path implies (owner earnings less working capital, over
   earnings). The explicit years are therefore unchanged.
2. **Terminal:** ρ_T = g_T / RONIC_T + ρ_sust. The ρ_sust term is above zero only for depleting-asset companies (see 4).
3. **The fade:** ρ_t moves linearly from ρ_5 to ρ_T. **The terminal uses ρ_T.**

**4. Sustaining reinvestment for depleting assets** (reserve replacement is maintenance, not growth):
- ρ_sust = max(0, ρ_hist − g_hist / RONIC_hist): the part of historical net reinvestment that historical growth at the historical return
  does not explain;
- ρ_hist = (capex − D&A + ΔNWC) / earnings, over a cycle window (5–8 years) in the real build. In the offline test below it is the base year
  only.

**5. A diagnostic, never a gate:**
- the **implied return of the explicit years** = (average year-1–5 earnings growth) / ρ_5, reported beside the analyst's terminal RONIC and
  the company's historical return;
- a large gap draws a reason request from the analyst.

**6. The categories,** assigned from filed data with no per-company rules. **Depleting:**
- SIC 1000–1499;
- **or** reserve or depletion disclosures in the filings (ASC 932 / IFRS 6 oil-and-gas or mineral reserves).

**Our finding:** Equinor's SEC SIC is **2911 "Petroleum Refining"**, not 13xx, so a SIC-only rule misses it. **The other three:**
- **financial:** SIC 6000–6799. RONIC_T is read as the return on equity, and ρ is retained capital;
- **capital-heavy operating:** capex/D&A above a threshold over the window. ρ_sust = 0, but the implied-return diagnostic matters most here;
- **operating:** everything else.

**7. Unchanged:** the AI still chooses growth, margins, fade, g_T and RONIC_T. Code computes ρ and the diagnostics, and never clamps an
input.

### 6a. Computed offline on the same 8 runs
The coordinator's independent code reproduces every current value exactly first. Base value change against today:

| Company | Type | (b) | **D** | Year-6/5 now | (b) | **D** | ρ_5 | ρ_T | Implied return, years 1–5 | RONIC_T | Value/price now | **D** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EQNR | depleting | −8.2% | **−52.7%** | 6.57 | 2.33 | 1.31 | 0.88 | 0.68 | 17.9% | 9.0% | 0.91 | **0.43** |
| MSGE | operating | +5.4% | +7.1% | 0.42 | 0.83 | 0.96 | −0.70 | 0.29 | n/a | 13.0% | 0.57 | 0.61 |
| BUD | operating | +2.3% | +2.3% | 0.66 | 0.85 | 0.87 | −0.35 | 0.30 | n/a | 10.0% | 1.02 | 1.04 |
| MCY | financial | +1.9% | +1.9% | 0.76 | 0.99 | 0.99 | −0.03 | 0.27 | n/a | 14.0% | 2.63 | 2.68 |
| PACS | operating | +1.2% | +1.1% | 1.02 | 1.23 | 1.23 | 0.00 | 0.21 | n/a | 18.0% | 1.35 | 1.37 |
| GOLD | operating | +0.7% | −0.3% | 1.06 | 1.20 | 1.01 | 0.15 | 0.25 | 56.4% | 12.0% | 2.26 | 2.25 |
| TASK | operating | +0.1% | −0.8% | 1.09 | 1.09 | 1.00 | 0.20 | 0.26 | 29.5% | 11.5% | 1.60 | 1.59 |
| DAC | operating (capital-heavy) | −1.5% | −2.1% | 1.27 | 1.03 | 0.98 | 0.30 | 0.25 | **−19.2%** | 10.0% | 1.68 | 1.64 |

**How we read it:**
- **For ordinary operating companies, D is close to today's values** (−2% to +7%) and makes the year-6 step near 1.
- **The real lever is depleting assets.** On base-year data, Equinor falls by about half. That rests on one year of capex and a revenue trend
  inflated by prices (g_hist = 5.2% revenue CAGR, RONIC_hist = 12.4%), so its size is uncertain.
- **A negative ρ_5** (BUD, MSGE, MCY) means the forecast's year 5 reinvests less than nothing (D&A above capex, or a working-capital release).
  That is not sustainable; D moves it to a positive terminal rate.
- **The implied-return diagnostic flags DAC** (earnings falling while reinvesting) and GOLD and TASK (very high implied returns), beside their
  terminal RONICs.

### 6b. What we most want challenged in D
1. **Is ρ_sust = ρ_hist − g_hist / RONIC_hist** a defensible measure of sustaining reinvestment? What should g_hist be: revenue,
   production volume, or real growth? Over what window?
2. **For depleting assets,** is a reserve-life or production-decline approach (maintenance capex to hold output flat) better than this
   residual?
3. **The depleting-category rule:** SIC plus reserve disclosures. Is there a better objective test? How should integrated oils, which also
   refine, be handled?
4. **Should ρ_sust exist only for depleting assets?** Capital-heavy growers can also have treadmill capex.
5. **Negative ρ_5:** should a forecast whose year 5 reinvests below zero draw a reason request?
6. **Linear convergence over the fade:** right, or should ρ converge faster or slower?
7. **Anything in D that breaks textbook consistency,** e.g. double counting working capital or depreciation.
