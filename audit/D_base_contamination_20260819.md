# Phase D — Base Contamination & Lattice Degeneracy (GOOG trigger)

**Date:** 2026-08-19 · **Scope:** `base_lattice` basis selection, its evidence pack, and the
repatch path · **Method:** deterministic replay of the live engine + direct reads of
`fundamentals_ttm.json` / `fundamentals_quarterly.json` / `fundamentals_history.json`.
**No LLM was invoked. No pipeline file was modified.**

Continues `A_institutional_checklist.md` → `B_gap_analysis.md` → `C_findings.md` →
`VALUATION_AUDIT_202608.md`. This phase was not planned; it was opened by a published result
that failed inspection.

---

## 1. Executive summary

The published GOOG report (`reports/GOOG_20260814_002226/FINAL.md`) carries
**"AUTHORITATIVE: fair value $702.49 (lattice_current_earnings) | MoS 97.4% | undervalued"**.

That number is not an aggressive judgment. It is an **arithmetic artifact**: the DCF
capitalized ~$100B of non-cash mark-to-market gains on private equity stakes, in perpetuity,
at a 20% growth rate.

Five defects, all measured, in one causal chain:

| # | Defect | Measured scope |
|---|---|---|
| **D1** | `current_earnings` cell takes TTM GAAP net income raw — no non-cash-income test | 21 book names have TTM NI > TTM OCF; GOOG/GOOGL are #1 and #2 |
| **D2** | Missing `da` collapses the lattice to a single cell — the "basis choice" has no alternatives | **57 of 283** names have a 1-cell lattice; **56 of 255** lack TTM D&A |
| **D3** | The basis-decision evidence pack gates *all* cash-flow lines on `da` being present | Same 56 names decide "is capex converting?" with zero capex/OCF/FCF shown |
| **D4** | `_forward_growth` reads `revenue_cagr`, never `eps_cagr` | GOOG: grew a distorted earnings base at +20% while consensus EPS CAGR was **−28.4%** |
| **D5** | `financials/{T}.json` mixes FY and TTM periods in the LLM prompt | GOOG capex published as "$91.45B TTM [Actual]" ×9; real TTM capex **$132.40B** |
| **D6** | `repatch_verdicts.py` never calls `apply_basis()` | Report says $702.49/+97.4%; ledger says **$64.30/−81.3%**. Both live, 11× apart |

**Verdict: D1 and D6 are correctness bugs and should be treated as STOP conditions.
D2/D3 are blocked on an upstream data gap (D&A ingestion) and cannot be repaired downstream.**

---

## 2. The trigger

GOOG was analysed independently by an external frontier model on the same T0 data. It reached
Base IV ~$205 (MoS −58%). RS2 local published +97.4% MoS on the same company. A 4× divergence
in fair value between two competent processes is a signal to audit the process, not to
average the answers.

Critically, the external report's "Killed Arguments" section names our exact failure mode:

> *"Trailing P/E is only 17.4× — it's cheap"* → dismissed, *"Trailing EPS of $19.93 is inflated
> by the $99.0B equity gain… **Never — this is an arithmetic error, not a viewpoint.**"*

`cache/openbb_GOOG.json` carries `pe_ratio: 17.253`. RS2 built its valuation on the artifact
that report identified as the trap.

---

## D1 — `current_earnings` capitalizes non-cash income

### Code

```
valuation_backbone.py:560-562
    ni_t, da_t, cx_t = _num(tf.get("net_income")), _num(tf.get("da")), _num(tf.get("capex"))
    if ni_t is not None and ni_t > 0:
        bases["current_earnings"] = ni_t        # <-- raw TTM GAAP NI, no quality test
```

The only qualification is `ni_t > 0`. Nothing checks whether that net income is *operating*.

### Measurement (GOOG, from our own data — no external source needed)

| Test | Value | Inference |
|---|---|---|
| TTM net income vs TTM operating cash flow | **$244.205B vs $185.675B** | NI exceeds OCF by **$58.53B** — *before* adding back ~$21B D&A and ~$25B SBC, both of which push OCF *above* NI. Implies **>$120B of non-cash income** in the base. |
| Q2'26 net margin | $112.19B NI ÷ $119.80B revenue = **93.6%** | Impossible from operations. TTM operating margin is 34.03%. |
| Pre-spike quarterly net margin (Q1–Q4'25) median × TTM revenue | 32.2% × $445.87B = **$143.7B** | Clean earning power proxy. Implied one-off: **~$100.5B**. |

Quarterly net income series (`fundamentals_quarterly.json`):

```
2025-03-31  rev  90.23B   NI  34.54B   (38.3%)
2025-06-30  rev  96.43B   NI  28.20B   (29.2%)
2025-09-30  rev 102.35B   NI  34.98B   (34.2%)
2025-12-31  rev 113.83B   NI  34.45B   (30.3%)
2026-03-31  rev 109.90B   NI  62.58B   (56.9%)   <-- break
2026-06-30  rev 119.80B   NI 112.19B   (93.6%)   <-- break
```

Revenue +24% YoY; net income +298%. The step is the SpaceX/Anthropic remeasurement
(SpaceX IPO 2026-06-12; Anthropic Level-2 remark). Triangulation: the external report
attributes $6.26/share of one quarter's EPS to the equity gain → $76.6B on 12.23B shares;
adding a ~$27.6B Q1 remark gives ~$104B, against our margin-proxy estimate of **$100.5B**.
Two independent methods agree within 4%.

### Effect on the published number

Reproduced exactly (`valuation_engine.dcf_value`, g=20%, terminal 2.5%, 5+5 fade):

| Base | $B | WACC 10% (as-run) | WACC 11.7% (current) |
|---|---|---|---|
| **TTM GAAP NI — what ran** | 244.21 | **$702.49** (+104% vs $343.54) | $554.45 (+61%) |
| Clean NI proxy | 143.7 | $413.37 (+20%) | $326.26 (−5%) |
| TTM OCF | 185.68 | $534.12 (+56%) | $421.56 (+23%) |
| TTM FCF | 53.27 | $153.25 (−55%) | $120.95 (−65%) |

**Roughly 41% of the published fair value is a mark-to-market gain on private stakes.**

### Book-wide scope

21 names have TTM NI > TTM OCF. Top 5 by absolute gap:

```
GOOG   244.21  185.68   +58.53   1.32x
GOOGL  244.21  185.68   +58.53   1.32x
NVDA   159.61  125.65   +33.97   1.27x
WDC      6.51    3.29    +3.23   1.98x
NFLX    13.65   11.97    +1.68   1.14x
```

**Caveat (do not over-read):** NI > OCF is a *screen*, not a diagnosis. For NVDA it is far
more likely a working-capital build in a hypergrowth ramp than a one-off gain. NVDA, WDC and
NFLX all carry full lattices and defaulted to `blended_owner_earnings`, so none of them
published on the contaminated cell. **GOOG/GOOGL are the only names where the screen fires
*and* the lattice offered no alternative.** That conjunction is the actual bug surface.

---

## D2 — Missing D&A collapses the lattice to a single cell

`fundamentals_ttm.json` for GOOG:

```json
{"fields": {"capex": 132402000000, "fcf": 53273000000, "net_income": 244205000000,
            "ocf": 185675000000, "revenue": 445866000000},
 "filed": "2026-07-23", "through": "2026-06-30"}
```

**No `da` key.** `fundamentals_history.json` has `da: None` for all 12 fiscal years (2014–2025).

Cascade:

1. `owner_earnings` requires `da_t` — `valuation_backbone.py:563` `if None not in (da_t, cx_t)` → **not built**.
2. `midcycle` requires ≥3 years of `_owner_earnings(fy)`, which returns `None` when `da` is
   missing (`valuation_backbone.py:295-300`) → **not built**.
3. Verified by replay: `vb.backbone('GOOG')['lattice']['cells']` = `{'current_earnings'}` **only**.

The lattice docstring (`valuation_backbone.py:478-498`) states its purpose: *"the engine
computes them all and the analyst layer picks, in the open, with delivered evidence in front
of it."* For these names **there is nothing to pick from.** The basis decision is a
three-sample unanimous ratification of the sole survivor, and `regime_decision.json` records
it as a deliberate judgment.

### Book-wide scope (deterministic replay, 283 tickers with reports)

```
lattice with >=2 cells (a real choice existed) : 219
lattice with exactly 1 cell (no choice)        :  57
lattice with 0 cells                           :   7
```

56 of 255 names with a TTM record (**22%**) are missing `da`. Sample:
`ABBV ABNB ADI ADP AVGO CSCO GILD GLW GOOG GOOGL GRMN ILMN INTU ISRG JKHY LLY MSFT
NVS SAP TSLA TSM UNP …` — i.e. much of the mega-cap cohort.

**This is an upstream defect.** Alphabet's cash-flow statement reports D&A; the field is
absent from the screener's `build_fundamentals_history` output. It cannot be repaired inside
RS2.

---

## D3 — The evidence pack hides cash flow from the basis decision

```
run_rs2.py:937-945
    rec = (valuation_backbone._ttm_record(t) or {}).get("fields") or {}
    if rec:
        ni, da, cx, ocf = (rec.get("net_income"), rec.get("da"), rec.get("capex"), rec.get("ocf"))
        if None not in (ni, da, cx):                     # <-- one missing field drops ALL of it
            L.append(f"TTM: net income …, D&A …, capex …, operating cash flow …, free cash flow …")
            L.append(f"  -> capex is {cx/da:.1f}x D&A …")
```

A missing `da` suppresses the net income, capex, **OCF and FCF** lines together. The exact
pack the GOOG basis decision received (reproduced verbatim, no LLM call — `_regime_evidence`
is pure string formatting):

```
Quarterly trajectory (10-Q filings) — judge ACCELERATION vs FADE:
  2025-03-31: revenue $90.23B, net income $34.54B
  …
  2026-06-30: revenue $119.80B (+24% YoY), net income $112.19B
Delivered growth (median last 4 quarters): +19.9%/yr. …
CYCLE HISTORY (2014-2025, 11 years): 0 year(s) of REVENUE DECLINE, worst +0%.
  -> … Do NOT choose mid-cycle. Decide between current earnings and owner earnings
     on whether the capex is converting.
```

**It was asked whether capex is converting and shown no capex, no OCF, no FCF.** All three
votes in `reports/GOOG_20260814_002226/regime_decision.json` cite the same evidence:

> *"Net income of $112.19B in the most recent quarter (2026-06-30) vs $34.54B in the prior
> year quarter, demonstrating immediate conversion of investment into earnings"*

It read a mark-to-market gain as operating conversion. Given the pack it was handed, no other
reading was available to it. **This is a harness defect, not a model failure** — and it
mirrors the C-phase pattern where a stage was blamed for doing exactly as told.

---

## D4 — Growth series mismatch

```
valuation_backbone.py:154-158
    for key in ("revenue_cagr", "eps_cagr"):
        v = _num(fg.get(key))
        if v is not None:
            return v, f"fwd_{key}"
```

`revenue_cagr` wins whenever present. For GOOG, `cache/openbb_GOOG.json` carries:

```json
"forward_growth": {"eps_cagr": -0.2838, "revenue_cagr": 0.2189, "source": "yfinance_estimates"}
```

Consensus expects **EPS to fall 28.4%/yr** — which is consensus stating plainly that trailing
EPS is inflated and will normalize. The engine grew that inflated earnings base at **+20%**
(revenue CAGR, capped by `FWD_GROWTH_CEIL`). Both errors compound in the same direction.

**Design question for the audit, not a proposed patch:** a revenue growth rate applied to an
earnings base is only coherent under constant margins and zero incremental reinvestment.
Whether that is defensible in general — and what should happen when the two consensus series
diverge sharply — is a methodology decision, not a bug fix.

---

## D5 — Period-mixed prompt data

`financials/GOOG.json` (fetched 2026-08-18) feeds the LLM:

| Field | Value fed | Actual period | TTM truth |
|---|---|---|---|
| `Capital_Expenditure` | −$91.447B | **FY2025** | **$132.402B** |
| `Operating_Cash_Flow` | $164.713B | **FY2025** | **$185.675B** |
| `Total_Cash` | $30.708B | cash & equivalents only | ~$242B incl. marketable securities |
| `TTM_Revenue` | $445.867B | TTM through 2026-06-30 | ✓ |
| `FCF_Margin_%` | 16.43% | FY2025 FCF ÷ **TTM** revenue | — |

FY figures are rendered adjacent to TTM figures with no period label. Result: `FINAL.md`
asserts **"CapEx ($91.45B TTM) [Actual]"** nine times, understating the single most important
variable in the GOOG thesis by 31%, and cites **"strong balance sheet ($30.71B Cash)"**.

A mitigation already exists for exactly this class of error on the FCF line
(`rs2_data.py:641-652` prefers the SEC-derived TTM after the MU incident of 2026-08-08).
**The same fix was never extended to `Operating_Cash_Flow` or `Capital_Expenditure`.**

Related staleness (lower severity, different cause): the research brief (generated
2026-08-04) supplies the **Q1** Cloud backlog of $462B, used throughout `FINAL.md`, while
`cache/openbb_GOOG.json`'s own Q2 transcript excerpt quotes Pichai saying **"$514 billion"**.
The correct figure was already in the prompt context.

---

## D6 — Repatch discards the endorsed basis (report ⇄ ledger contradiction)

Currently live, simultaneously:

| Surface | Fair value | MoS | Stance |
|---|---|---|---|
| `reports/GOOG_20260814_002226/FINAL.md` (what a human reads) | **$702.49** | **+97.4%** | undervalued |
| `verdict.json` / `llm_overlay.json` (what publishes) | **$64.30** | **−81.3%** | overvalued |

Cause: `repatch_verdicts.py:71-84` refreshes `VAL_REFRESH` fields from `vb.backbone(t)` — the
**engine default** basis — and never calls `apply_basis()`. GOOG's engine default is
`fcf_fallback_sbc` = $28.32B, ~8.6× below the endorsed `current_earnings` base of $244.21B.

`apply_basis` exists precisely to prevent this seam; its docstring (`valuation_backbone.py:508-518`)
documents the 2026-08-12 fix that moved basis resolution *before* the stages so "stages,
header, prose and verdict all agree by construction." **The repatch path reintroduced the seam
it was written to close.**

Note the repatch's own invariant check did not catch it: |−81.3%| < `MOS_EXTREME_MAX` (150%),
so the counter reported clean. The fence tests magnitude, not agreement with the report.

**Neither published number is correct.** $702.49 rests on the contaminated base; $64.30 rests
on a base the report never used and does not argue for.

---

## 3. Reproduction

All deterministic, CPU-only, no LLM. From the repo root:

```bash
# D1 — contaminated base
python -c "import json;SD='C:/Users/riper/Downloads/Stock Screener/Stock Screener/public/data/';d=json.load(open(SD+'fundamentals_ttm.json'));print((d.get('tickers') or d)['GOOG'])"

# D2 — single-cell lattice
python -c "import valuation_backbone as vb;print(list(vb.backbone('GOOG')['lattice']['cells']))"

# D3 — the exact evidence pack (string formatting only, no model call)
python -c "import run_rs2,valuation_backbone as vb;print(run_rs2._regime_evidence('GOOG',vb.backbone('GOOG')))"

# D1 — fair value by base
python -c "import valuation_engine as ve,valuation_backbone as vb;[print(n,round(ve.dcf_value(b*1e9,0.20,0.10,vb.TERMINAL_G,stage1_years=vb.STAGE1,fade_years=vb.FADE)/12.23e9,2)) for b,n in ((244.205,'GAAP_NI'),(143.7,'clean'),(185.675,'OCF'),(53.273,'FCF'))]"

# D6 — the contradiction
python -c "import json;print(json.load(open('reports/GOOG_20260814_002226/verdict.json'))['fair_value'])" && head -2 reports/GOOG_20260814_002226/FINAL.md
```

**Version note:** `FINAL.md`'s $702.49 was produced at WACC 10%. Replaying today gives
$554.45 because the Option-2 market-anchored CoE offset (+1.7pts → 11.7%) landed 2026-08-19.
The defect is identical; only the level moved. Do not read the difference as a partial fix.

---

## 4. Proposed remediations — **all held pending approval**

Per CLAUDE.md §0, these are raised as STOP conditions, not applied.

### R1 — Non-cash-income guard on `current_earnings` *(cheap, no new data, high value)*

Reject or haircut the `current_earnings` cell when `TTM NI > TTM OCF`. The test needs no D&A,
runs on fields we already have for every name, and would have blocked this publication.
**Open question for the audit:** reject the cell outright, or substitute a
`min(NI, OCF)`-style capped base? Rejection is cleaner but leaves GOOG with a zero-cell
lattice until R3 lands — which may be the honest answer (CLAUDE.md §0: *"if the data cannot
support the correct method, the answer is NOT to substitute a weaker method"*).

### R2 — `repatch_verdicts.py` must call `apply_basis()` *(correctness bug, isolated)*

Either resolve the basis from the report's `S3_valuation_inputs.json` (`base_cf_kind` carries
the `lattice_*` prefix) and re-apply it, or refuse to repatch when the endorsed basis cannot
be reproduced. Silent basis substitution is worse than a skipped row. **Scope check needed:
how many of the 290 repatched verdicts had a lattice basis silently replaced?** Not yet
measured.

### R3 — Source the D&A gap *(upstream, blocks D2/D3)*

56 names lack TTM `da`; GOOG lacks it for all 12 fiscal years. Alphabet reports D&A on the
cash-flow statement, so this is most likely an extraction defect in the screener's
`build_fundamentals_history`, not an unavailable field. **Until this is resolved the lattice
is not a lattice for 57 names, and no downstream fix can make it one.**

### R4 — Ungate the evidence pack *(cheap, follows R3)*

`run_rs2.py:940` should emit each available line independently rather than dropping the whole
block on one missing field. OCF and FCF are present for GOOG and were withheld for no reason.

### R5 — Extend the SEC-TTM preference to OCF and CapEx *(cheap, mirrors an existing fix)*

`rs2_data.py:641-652` already does this for FCF. Same treatment for
`Operating_Cash_Flow` and `Capital_Expenditure`, or an explicit `(FY2025)` label when the
TTM value is unavailable.

**Suggested order:** R2 (correctness, isolated) → R1 (guard, prevents recurrence) →
R3 (unblocks the rest) → R4, R5.

---

## Appendix — External cross-check

The external GOOG report reconciles against our own independent data on every field checkable
from this repo. Recorded because it establishes that the divergence is **ours**, not a data
disagreement:

| Field | External report | RS2 data | Source |
|---|---|---|---|
| TTM revenue | $445.87B | $445.866B | `fundamentals_ttm.json` |
| TTM OCF | $185.68B | $185.675B | `fundamentals_ttm.json` |
| TTM capex | $132.40B | $132.402B | `fundamentals_ttm.json` |
| TTM FCF | $53.27B | $53.273B | `fundamentals_ttm.json` |
| GAAP EPS TTM | $19.93 | 19.94 | `financials/GOOG.json` |
| ROE | 48.68% | 48.676% | `cache/openbb_GOOG.json` |
| Gross / operating margin | 60.90% / 34.0% | 60.897% / 34.033% | `cache/openbb_GOOG.json` |
| Beta (aggregator) | 1.24–1.25 | 1.247 | `financials/GOOG.json` |
| Shares short | 55.7–70.5M | 55,653,051 | `enrich/GOOG.json` |
| Cloud backlog / growth | $514B / +82% | "$514 billion" / "82%" | `cache/openbb_GOOG.json` transcript |
| Search / YouTube growth | +17% / +13% | "17%" / "13%" | `cache/openbb_GOOG.json` transcript |
| Consensus PT | avg $428 | mean $421.79, median $425 | `enrich/GOOG.json` |

13 independent confirmations, zero conflicts.

**Framing for the audit:** a third-model review of that report disputed its *judgments*
(capex-cycle analogue, 10.8% vs 13–14% revenue CAGR, stake haircuts) and argued for
$280–310 against its $205. Those are legitimate arguable calls on clean inputs. **RS2's
$702.49 and $64.30 are not in that category** — they are not a third opinion on Alphabet,
they are two different arithmetic errors. The distinction matters when deciding how much of
the engine to trust: this phase found no evidence against RS2's *ranking* machinery, which
C1/C6 measured as working. It found a defect in the *base* the ranking is computed from,
confined to a subpopulation we can now enumerate exactly.

---

*Deterministic replays only. No LLM invoked, no pipeline file modified, no verdict rewritten.
Every figure above is reproducible from §3 against the repo state of 2026-08-19.*
