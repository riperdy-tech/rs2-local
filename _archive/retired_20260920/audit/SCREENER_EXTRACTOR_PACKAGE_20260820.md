# SCREENER EXTRACTOR — CHANGE PACKAGE

**Target file:** `C:\Users\riper\Downloads\Stock Screener\Stock Screener\scripts\build_fundamentals_history.py`
**Output:** `C:\Users\riper\Downloads\Stock Screener\Stock Screener\public\data\fundamentals_history.json`
**Evidence source:** local `companyfacts.zip` at the screener repo root — 1,398,828,353 bytes, mtime 2026-08-07T14:27:51Z, 20,175 `CIK##########.json` entries, newest member 2026-08-06 19:49:36. **Every expected number in this package is a claim about that snapshot** (13 days stale as of 2026-08-20). A prior snapshot `companyfacts.zip.20260623` (1,383,626,002 B) sits beside it and must never be substituted. The dir `public/data/sec_facts/` (5,701 files, all 2026-06-23) is a decoy: `grep sec_facts scripts/build_fundamentals_history.py` returns nothing — the extractor reads only the zip (`ZIP_PATH`, line 50/51).
**Population:** "live book" = the 172 tickers in `public/data/llm_overlay.json['tickers']`. All 172 resolve to a CIK in `public/data/cik_map.json` and to a zip entry (0 missing on both joins). "Corpus" = 5,600 tickers in the shipped file (6,082 zip-resolvable). Every count below names which population it covers.
**Baseline proof:** an instrumented line-for-line clone of `extract_history`/`resolve_field_series` reproduces the shipped file **byte-for-byte for all 5,600 tickers** (`MISMATCH vs production: 0`), and re-serialising the production payload with the same serializer gives the exact on-disk size. Two size constants, both verified by execution: `json.dumps({'generated_at','source','tickers'}, sort_keys=True)` = **28,063,731 B** (== file on disk); `json.dumps(d['tickers'], sort_keys=True)` alone = **28,063,627 B**. Any acceptance test below that re-serialises tickers-only must use 28,063,627 — the first draft of this package used 28,063,731 for both and would have failed a correct build.
**Warning:** `build_fundamentals_history.py.bak-20260820` exists beside the extractor and DIFFERS (pre-FIELD_SPECS vintage). The current file is proven to be the production generator by the byte-identical replication. Do not patch the `.bak`.
**Locator convention:** line numbers below were re-verified 2026-08-20, but where a line number and a quoted code string disagree, **the quoted string is the normative locator** — a first-pass audit of this package found 1–17 lines of drift in some anchors, all corrected here.

---

## 0. WHY THIS EXISTS, AND WHAT CONSUMES IT

`fundamentals_history.json` is the sole fundamentals feed for two systems:

1. **The screener itself** — `scripts/fetch_data.py` (`load_fund_hist()`, latest-FY row at ~377-378: `years = sorted(yrs_map); f0 = yrs_map[years[-1]]`, effective tax rate for ROIC at ~389), `scripts/score_factors.py:143` and `:341` (`debt = num(fy_row.get('lt_debt')) or 0.0` → `ev = mcap + debt - cash`), `scripts/build_valuation_models.py:181` (+129), `scripts/backtest_lite.py:74,244,255`, `scripts/audit_data.py:50`.
2. **RS2** (`C:\Users\riper\Downloads\RS2 Local`) — `rs2_data.py:396-398` builds the fact pack handed to the local analyst model; `rs2_data.py:~168` computes `nd = ltd - cash` (the "net debt Nx OCF" solvency flag and the `net_debt_b` fact); `valuation_backbone.py:290` loads history, `:~853` computes `net_cash = cash - lt_debt` for the Engine-5 biotech floor, and `base_cf = net_income + D&A - capex` is the reverse-DCF's cash-flow anchor; `data_health.py:93-94, 292` and `tools/growth_persistence.py:11,14` iterate year keys with `int(y)`; `tools/test_coverage_gate.py:47-48` also reads the file (`hist.get('tickers') or hist`).

Every reader accesses the document through the `tickers` key and reads row fields with `.get()`. **No reader iterates a year-row's keys**, so *additive fields inside year rows* and *new top-level sibling keys* are both safe by construction. A new **ticker-level** key is fatal (see REJECTED §3.1).

Why the gaps matter to a valuation: a missing capex nulls `fcf` and starves `base_cf` (LLY ships null capex+fcf for all 12 years); a depreciation-only D&A understates `base_cf` by half (AMD FY2025 −75%); a basic share count in `shares_diluted` overstates every per-share figure; a dead `lt_debt` series understates EV by the company's whole debt (AVGO: null on $65bn); missing marketable securities makes GOOG look net-DEBT $18.4bn when it is net-CASH $77.8bn; and a silent XBRL tag splice fabricates a 64% revenue collapse (PM) that the analyst model then explains as a business event.

**The two rules that govern this file:**

- **THE PRIMARY-VOTE TRAP** (documented in-file at lines 298-303): `annual_duration_series`/`annual_instant_series` select a winner with `max(candidates, key=lambda s: (max(s[0]), len(s[0])))` — latest year, then coverage. Expanding the list a *primary* vote sees changes which tag wins and drops years the old winner covered; measured cost when violated: 13 capex values lost on LNKS and LTM. Corollary discovered in this audit: the backfill sort at line 316 is `(-max_year, -coverage)`, **not list order**, so adding any tag to a COMBINED list can re-order backfill of already-filled years (measured: 9 corpus capex cells changed from an "add-only" edit). Only a full-corpus diff catches this class.
- **PER-FILER VERIFICATION BEFORE ANY TAG SHIPS** (KNOWN TRAP 2): a plausible tag without per-filer proof is how "just add Depreciation" would have understated Novartis by 76% ($1,208M vs $4,949M). Every tag in this package names the filers it was checked on and the values found. Every refused tag is written into the file's refusal comment block with its disproving filer, so it cannot be re-proposed from plausibility.

**Deployment procedure:** push extractor CODE only. The cloud rebuild (`.github/workflows/paradigm-weekly-analyst.yml`, cron `'0 10 * * 0'`) runs `scripts/fetch_sec_data.py` — which downloads `https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip` **fresh** onto a clean runner (`fetch_sec_data.py:36`, always true in CI) — then `build_fundamentals_history.py`. **Never commit a local rebuild from the stale zip**: it has already cost a ticker's newest fiscal year once. Run acceptance tests locally against the 2026-08-07 zip first; when the cloud run drifts from an expected count, treat it as **new filings and re-baseline** — do not chase it as a regression, and do not adjust expected numbers to force a local pass. `--limit/--tickers` runs write to `fundamentals_history.SUBSET.json` (main(), lines 1005-1010) and never touch production — use them freely.

---

## 1. PRIORITY ORDER

**Tier 1 — fixes fields that ship WRONG today (outranks everything below):**

| # | Change | One-line reason |
|---|--------|-----------------|
| 1 | CH-4 gated capex (LLY, ROP) | LLY ships **null capex and null fcf for all 12 years including the latest FY** — `base_cf` is starved right now on a top-10 pharma. |
| 2 | CH-2 scale-overwrite arbitration | 23 shipped cells hold raw-thousands values (e.g. GRMN shares 194,165), and 6 names' dilution signals are deleted by the resulting fake "splits". |
| 3 | CH-3 shares_diluted primary restriction | 44 live cells are BASIC counts shipped as diluted (INVA +14.9%), invisible because no tag is recorded. Must ship together with CH-2. |
| 4 | CH-1 remove Domestic pretax tag | 173 cells on 38 names, 16 sign flips (VRTX 2017: +330M shipped vs −15.7M true). Honest de-urgency: **0 of the 173 is a latest FY**, and both latest-FY consumers are unaffected today — it is a corrupt audit trail, not a live fire. |
| 5 | CH-5 D&A gated change (conditional) | AMD's latest-FY D&A is −75%; the gated fix takes it to −6% but creates two declared regressions (LIVN 2020, AMD 2022). Operator sign-off required — see §2.5. |

**Tier 2 — adds fields/metadata we do not have:**

| # | Change | One-line reason |
|---|--------|-----------------|
| 6 | CH-6 provenance persistence + basis-break detector | Turns 94 proven tag-splices (PM's fake 64% revenue collapse among them) from invisible into deterministic, threshold-free flags; strictly dominates RS2's `_revenue_break` heuristic. |
| 7 | CH-7 marketable-securities fields | Six live names' net debt has the wrong SIGN (GOOG/GOOGL, AAPL, META, MU, ADSK); $96bn swings on the two largest names in the book. |
| 8 | CH-8 SBC field | Vendor scalar is provably wrong (RTX 2.1x, ZTO wrong currency, AIT component-only) or null; extractor covers 169/172 with median 10/10 recent years. |
| 9 | CH-9 debt component fields | `lt_debt` is null/zero/understated for 28 of 172 live names (MAR ships 23,000,000 against a true 14,995,000,000; ABNB ships literal 0). Legacy field stays untouched. |

**Sequencing constraints (binding):**
- CH-6 must land **before** CH-1, or all of CH-6's acceptance counts are invalid: 18 of the 43 pretax DISAGREE_proven detector events are caused by the Domestic tag CH-1 removes. Land CH-6 against the numbers here, then CH-1, then re-baseline the provenance counts as a follow-up measurement.
- CH-3 must land **with or after** CH-2: 21 of the 98 corpus cells the shares change moves by >25% are power-of-1000 regressions in the newly chosen tag that only CH-2's arbitration contains.
- CH-7 and CH-9 both add instant fields to `series` and both MUST join the same `VOTE_FIELDS` exclusion (§2.7) — the accession vote scores accessions by field coverage, and adding fields without the exclusion rewrote 11 pre-existing cells in measurement.
- Every change ships alone, with its own full-corpus before/after diff. Never bundle.

---

## 2. THE CHANGES

### 2.1 CH-1 — Remove the Domestic pretax tag

**Current behaviour.** `FIELD_SPECS["pretax_income"]["COMBINED"]` (entry at line 275) contains `IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic`. It is absent from `DURATION_TAGS["pretax_income"]` (lines 92-94), so it can never be primary — measured: 0 primary cells — but it wins **backfill** because the tax-footnote series runs later than the income-statement series and the backfill sort at line 316 is `(-max_year, -coverage)`.

**Measured damage (live book, census).** 173 cells / 38 names, all provenance=backfill, year histogram 2012:2 … 2021:2 (peak 2014-2018). The tag is the **US-only geographic component**: Domestic + Foreign == Total holds in **54 of 54** common filer-year ends across JNJ, BMY, MDT, SYK, GOOGL, ILMN, MA, REGN with zero exceptions (re-measured; an earlier "47 of 47" count was a tally error). For 165 of the 173 cells a correct TOTAL tag covers the same year: 149 differ >5%, **16 flip sign**, 0 identical. Named: GOOG/GOOGL FY2014 shipped 8,894,000,000 vs true 17,259,000,000 (Domestic 8,894 + Foreign 8,365 = 17,259 exactly); EXPD FY2014 211,588,000 vs 610,889,000; VRTX 2017 +330,340,000 vs −15,689,000; MDT FY2018 −958,000,000 vs +5,675,000,000; ADI FY2016 2,642,000 vs 956,921,000. Shipped implied tax rates: ADI 2016 36.055, MCO 7.586, JNJ 3.365. Identity check: DOMESTIC rows fail `|pretax−(NI+tax)|/|NI+tax|>5%` at 86.3% vs a 10.4% noise floor on all other rows.

**Change.** Delete the line `"IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",` from the COMBINED list at line 275, leaving it identical to `DURATION_TAGS["pretax_income"]`. Append to the refused-tags comment block (**lines 279-286**, not 267 — corrected anchor): the tag is the tax-footnote domestic component, GOOG FY2014 8,894M vs true 17,259M; it won backfill only because the footnote series runs later. Do NOT add an NHC allowlist: the 8 cells it would save are 2014-2021, none a latest FY, and no pretax allowlist mechanism exists.

**Per-filer verification.** GOOG/GOOGL, EXPD broken as above. **NHC is the only counter-case and it is genuine**: files no `...Foreign` tag ever, no total tag before 2022; its Domestic == NI+tax exactly 2014-2016 (85,193,000 / 85,274,000 / 80,207,000), within 0.7% 2017-2021. Removal correctly nulls those 8 cells; NHC 2022-2025 resolve from the total tag. A `COMPONENT_SLOTS=[[Domestic],[Foreign]]` recovery was shadow-run and gains **0** live cells — dead code, rejected.

**Acceptance test (FAILABLE, expected numbers).** Live book: pretax changed = **165**, lost(→null) = **8** (exactly NHC 2014-2021), gained = 0; every other field 0/0/0. Spots: GOOG & GOOGL FY2014 → 17,259,000,000, FY2015 → 19,651,000,000, FY2016 → 24,150,000,000; EXPD FY2014 → 610,889,000; ADI FY2016 → 956,921,000; MDT FY2018 → 5,675,000,000; VRTX 2017 → −15,689,000. Identity gate — **corrected constants** (the first-draft bounds 175/17 fail a correct build): post-fix fails must be ≤ **200** of 1,827 and sign flips ≤ **20** (measured: 194 and 18; n drops to 1,827 because the 8 nulled NHC rows leave the denominator; the residual 194 is the identity's own noise floor — discontinued ops and minority interest sit below the tax line). Corpus gate — state the diff level: diffing the **shipped file** (12-year windows) expect ~**1,877 changed / ~836 nulled** ±5%; a raw field-resolve diff over 6,082 tickers gives 3,710/1,232 and is NOT the same measurement.

**Risk if wrong.** None structural — the tag cannot be primary, so removal cannot move any primary cell. The only cost is the 8 honest NHC nulls.

---

### 2.2 CH-2 — Scale-overwrite arbitration (`_pow1000_ratio` directional hole)

**Current behaviour.** `_pow1000_ratio` (lines 161-169) computes `r = |a|/|b|` and tests only `0.7·p ≤ r ≤ 1.4·p` for p ∈ (1e3, 1e6, 1e9) — never the reciprocal band. Its call sites at lines 180 (`_pick_consistent`) and 211 (`_normalise_series_scale`) pass arguments largest-first by construction; the call at **line 738** inside the accession vote — `if av != v and _pow1000_ratio(av, v) is None and not (av == 0 and v):` — is UNORDERED. Result: the vote reinstates a raw-thousands accession value over a series value the scale defence had already corrected.

**Measured damage (live book, census of overwritten cells).** **23 corrupted shipped cells across 4 fields and 10 names** (first-draft counts of "24 cells / 8 fields" were wrong — the 24th directional hit is NHC 2023 sga, where the buggy overwrite installs the CORRECT value 21,412,000 over a corrupt resolved 21.4 trillion; affected by the bug, not corrupted by it): shares_diluted 19 (AGX 2015; AGYS 2019, 2020; EMBJ 2021, 2022; GRMN 2014-2017, 2021, 2022; IMAX 2014-2017; NICE 2014-2017), current_assets 1 (BLBD 2014), interest_expense 2 (GWRE 2017, P 2018), sga 1 (MAMA 2016). Downstream, `fundamentals_battery.json` marks AGX, AGYS, EMBJ, GRMN, IMAX, NICE `share_count_split_suspected=True` from these fake 1000x steps, deleting `net_issuance_1y`, `net_issuance_3y_cagr` and the no-dilution F-score check.

**Change.** Replace the guard at line 738 with median arbitration (a symmetric band alone is REJECTED — it would ship NHC a 21.4-trillion SG&A, §3.11). Inside the per-field loop (~731-739), after `av`:

```python
if av != v and not (av == 0 and v):
    _ref = _series_median(series[f])
    if _pow1000_ratio(max(av, v, key=abs), min(av, v, key=abs)) is None:
        v = av
    elif _ref and abs(math.log10(max(abs(av), 1e-9) / _ref)) < \
                 abs(math.log10(max(abs(v), 1e-9) / _ref)):
        v = av
```

with a module-level helper next to `_pick_consistent` (whose own median line is **186** — corrected anchor):

```python
def _series_median(s):
    vals = [abs(x) for x in s.values() if x]
    return statistics.median(vals) if vals else None
```

`math` and `statistics` are already imported at **lines 32-33** (corrected anchor). Keep the `av == 0 and v` zero-artifact refusal exactly as is.

**Verification.** The arbitration rule was executed against all 24 directional hits: KEEP_RESOLVED 23, KEEP_ACCESSION 1 (NHC) — 24/24 correct. Full-pipeline run of the patch as written: changes **exactly 23 live cells**, all the enumerated restorations, NHC 2023 sga stays 21,412,000, zero collateral.

**Acceptance test.** MUST SEE exactly these 23 restorations: AGX 2015 14,823 → 14,823,000; AGYS 2019 → 23,037,000; AGYS 2020 → 23,233,000; EMBJ 2021 → 734,730,000; EMBJ 2022 → 734,632,806; GRMN 2014/2015/2016/2017/2021/2022 → 194,165,000 / 191,107,000 / 189,343,000 / 188,732,000 / 193,043,000 / 193,042,000; IMAX 2014-2017 → 69,754,202 / 71,058,000 / 68,263,000 / 65,540,000; NICE 2014-2017 → 59,362,000 / 59,552,000 / 59,667,000 / 60,444,000; BLBD 2014 current_assets → 164,062,000; GWRE 2017 interest_expense → 13,000,000; P 2018 → 19,000,000; MAMA 2016 sga → 24,000,000. Several restored values are floats from `_normalise_series_scale` (e.g. `23037000.0`) — JSON diffs will show `x.0`; that is expected. MUST NOT SEE: NHC 2023 sga moving off 21,412,000. Downstream: `share_count_split_suspected` flips to False for AGX, AGYS, EMBJ, GRMN, IMAX, NICE; **SPHR stays True** (its 2020 overwrite 34,942,000 → 24,017 is a 1455x gap outside every power-of-1000 band — a declared STOP, §4). Live names with `net_issuance_1y = null`: **33 → at most 27** (corrected from 34/28: SAP has no battery entry at all).

**Risk if wrong.** The arbitration touches every field's vote path. Guard: with the patch applied, the full-corpus diff must show ONLY the 23 cells (plus, at corpus level, cells of the same directional class outside the live book — enumerate and inspect them before accepting).

---

### 2.3 CH-3 — shares_diluted: primary restricted to the diluted tag, plus tag-provenance sidecar

**Current behaviour.** `DURATION_TAGS["shares_diluted"]` (lines 87-89) hands a 4-tag list to the recency+coverage winner vote, so a filer whose BASIC series outlives its Diluted series hands the entire field to Basic. Live census: 1,641 cells/153 names diluted; **64 cells/6 names BASIC** (AGYS, ARWR, GE, INVA, MAMA, NICE); **88 cells/12 names undifferentiated** `WeightedAverageShares` (ARGX, AZN, CGAU, DCBO, EMBJ, GMAB, IHG, KMDA, NVS, SAP, TSM, VIK); 114 null. The output records no tag anywhere, so the substitution is invisible.

**Change.** (a) `DURATION_TAGS["shares_diluted"] = ["WeightedAverageNumberOfDilutedSharesOutstanding"]`. (b) Add `FIELD_SPECS["shares_diluted"] = {"COMBINED": ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic", "WeightedAverageShares", "AdjustedWeightedAverageShares"], "COMPONENT_SLOTS": []}` so the other three backfill only. This IS a deliberate primary-vote change — the exact move the warning comment at lines 298-303 forbids without proof — justified only by the corpus gate below. `ttm_snapshot` unaffected: `TTM_FIELDS` (**line 444** — corrected anchor) excludes shares_diluted. (c) Record the winning tag: alongside `row[f] = v` (~line 740) accumulate a per-cell tag map and write it in `main()` as a **TOP-LEVEL sibling** of `"tickers"`: `"tag_provenance": {ticker: {year: {field: tag}}}` — never inside a ticker's year dict (the `int(y)` hazard is documented in-file at **lines 53-55** — corrected anchor). If CH-6 lands, fold this into its run-length-encoded provenance block instead of a second sidecar.

**Per-filer verification.** All 44 changes are upward, basic→diluted, +0.09% to +14.93%: INVA 2016-2021 +11.75% to +14.93% (2021: 82,062,000 → 94,310,000); NICE 12; GE 7 (2014: 10,045,000,000 → 10,123,000,000); AGYS 6; MAMA 8; ARWR 1 (2019: 93,858,857 → 98,607,815). The 12 `WeightedAverageShares` names file no diluted tag — 0 changed, 0 lost; the honest fix for them is disclosure via the tag record, not substitution. Gains = 14 (CLS 7, NUTX 2, TEAM 5).

**Acceptance test.** Live: changed = **44** (AGYS 6 incl. FY2026, ARWR 1, GE 7, INVA 10, MAMA 8, NICE 12), gained = **14**, lost = **0**; spots as above; the 12 WAS names 0/0. **CORPUS GATE, mandatory and hard: 0 cells LOST over the full corpus** — any loss is the 13-capex failure mode repeating; revert. Corpus magnitudes as a tolerance band, not exact constants (first-draft exact counts do not reproduce): shipped-window measurement ~41,076 same / ~982 changed / ~185 gained. Ship only together with CH-2. `tag_provenance`: assert it is top-level, `json.load(...)['tickers']['AAPL']` still has only 4-digit-year keys, and `tag_provenance['INVA']['2021']['shares_diluted'] == 'WeightedAverageNumberOfDilutedSharesOutstanding'`.

**Risk if wrong.** Primary-vote trap. The 0-lost corpus gate on the real rebuild (not just field-resolve level) is the guard.

---

### 2.4 CH-4 — Gated capex additions (LLY, ROP) via a new `TICKER_GATED_TAGS` mechanism

**Current behaviour.** `FIELD_SPECS["capex"]` (lines 266-268) maps only `PaymentsToAcquirePropertyPlantAndEquipment` and `PaymentsToAcquireProductiveAssets` (+ the primary list at `DURATION_TAGS` 78-80). 78 live null capex cells on 19 names; 5 names null every year. When capex is null, `fcf` is null (line 745).

**Measured damage.** LLY: capex and fcf null **12/12 years** — it files neither mapped tag, but files `PaymentsToAcquireOtherPropertyPlantAndEquipment` continuously 2007-2025 (FY2024 5,058,000,000; FY2025 7,841,000,000). Verified against independent estimators: capex/revenue 4.6-12.0% (rise tracks the known 2023-25 manufacturing buildout); capex/(ΔPPE+D&A) 0.50-0.93 over 11 years. ROP: null 2019-2025; `PaymentsToAcquireOtherProductiveAssets` agrees with ΔPPE+Depreciation within 2.5% for the three latest years (68.0M vs 69.7M; 66.0M vs 67.2M; 47.4M vs 47.0M — the depreciation-only estimator is correct for a serial acquirer whose D&A is amortization-dominated).

**Why gated.** The SAME tag is REFUTED on GSAT: values 5.1-7.1M for 2020-2025 against ΔPPE+Depreciation of up to 717,924,000 — FY2025 tag value is <1% of what GSAT actually put into PP&E (net PP&E 673,632,000 → 1,305,458,000). An ungated addition ships GSAT a capex 1/130th of truth and a matching inflated FCF. This is KNOWN TRAP 2 in its purest form.

**Change.** (a) `FIELD_SPECS["capex"]` gains the two tags in COMBINED plus:
```python
"TICKER_GATED_TAGS": {"PaymentsToAcquireOtherPropertyPlantAndEquipment": {"LLY"},
                      "PaymentsToAcquireOtherProductiveAssets": {"ROP"}},
```
(b) In `resolve_field_series`, at the top of the backfill loop over `combined` (~line 309):
```python
gated = spec.get("TICKER_GATED_TAGS") or {}
for tag in combined:
    if tag in gated and ticker not in gated[tag]:
        continue
```
Do NOT touch `DURATION_TAGS["capex"]` — the primary vote stays as is. Mechanism regression guard: with an empty gate dict the rebuild must be byte-identical to today's file (verified reproducible baseline exists).

**Acceptance test.** Live: capex gained = **19** and only 19 (LLY 2014-2025 = 12, ROP 2019-2025 = 7); changed = 0; lost = 0; fcf gained = 19/0/0; all other fields 0/0/0. **GSAT capex must remain null 2020-2025** — if GSAT gains cells the gate is not wired. Spots — **corrected to what the pipeline actually ships** (the accession vote adjusts two ROP years; first-draft tag-series values would fail): ROP 2019 = **52,700,000**, ROP 2020 = **28,300,000** (not 43.0M/24.7M), ROP FY2025 = 47,400,000; LLY FY2024 capex 5,058,000,000 → fcf 8,818,000,000 − 5,058,000,000 = **3,760,000,000**; LLY FY2025 capex 7,841,000,000 → fcf **8,972,000,000**; LLY 2023 ships **3,447,600,000** (not 3,448,000,000). Corpus gate — name the diff level: diffing the **shipped file**, gained must be **19**, identical to live; at raw field-resolve level it is 26 (LLY 2007-2013 are pre-MAX_YEARS-window — reconciles exactly). Corpus changed must be **0** (the ungated variant changed 9-15 existing corpus cells via backfill re-ordering).

**Risk if wrong.** The gate helper touches `resolve_field_series`, which every curated field runs through. Empty-gate byte-identity is the guard.

---

### 2.5 CH-5 — D&A: `OtherDepreciationAndAmortization` gated to ABNB + slot zero-suppression fix — **CONDITIONAL, operator sign-off required**

**Current behaviour and damage.** `OtherDepreciationAndAmortization` sits ungated in `FIELD_SPECS["da"]["COMBINED"]` (line 246) and is **polysemous** — proven three ways at the three live filers using it: at **AMD** it is the "other D&A" line EXCLUDING acquisition-intangible amortization (exact reconciliations: 2022 `AdjustmentForAmortization` 3,548M + OtherD&A 626M = 4,174M, the value AMD itself tagged as OtherD&A in accns 0000002488-23-000047/-24-000012 before re-tagging; 2023: 2,811M + 642M = 3,453M) — shipped FY2023/24/25 are **−81.4% / −78.1% / −75.0%**, and FY2025 feeds `base_cf` today (shipped owner earnings 4,111M vs true 6,365M, +54.8%); at **LIVN** it is an alias for the amortization line (2018: 37,194,000 == `AmortizationOfIntangibleAssets` == `AdjustmentForAmortization`, exact); at **ABNB** it is the BROADEST line and the shipped primary is the partial one. Separately, the slot merge at line ~329 (`merged.setdefault(y, v)`) lets a 0-valued tag beat a later non-zero alternative in the same slot (LIVN `AmortizationOfIntangibleAssets` = 0 for 2019/2020 while real amortization exists).

**Change.** (a) `FIELD_SPECS["da"]["TICKER_GATED_TAGS"] = {"OtherDepreciationAndAmortization": {"ABNB"}}` (reuses CH-4's mechanism). (b) Slot merge prefers the first NON-ZERO alternative: `if merged.get(y) in (None, 0) and v is not None: merged[y] = v`. (c) `LONE_DEPRECIATION_ALLOWLIST` (line 254) untouched — verified still necessary: exactly 22 cells (GOOG/GOOGL 2021-25, UNP 2014-25), emptying it loses all 22 with no replacement; Alphabet and UNP file no amortization-of-intangibles element for those years.

**Acceptance test — CORRECTED numbers (the first-draft "changed=0, lost=5" is wrong and would make a correct implementation look broken).** After (a) alone, measured through the full pipeline: da **changed = 9, lost = 4, gained = 0** — component sums take over immediately: AMD 2022 4,174,000,000 → 3,987,000,000; 2023 642,000,000 → 3,241,000,000; 2024 671,000,000 → 2,854,000,000; 2025 750,000,000 → 2,821,000,000; LIVN 2018 → 69,940,000; 2019 → 30,317,000; 2020 → 29,031,000; 2023 → 50,209,000; 2024 → 42,316,000; lost: AMD 2020, AMD 2021, LIVN 2021, LIVN 2022. ABNB 2023 stays 44,000,000 and 2024 stays 65,000,000. After (b) as well: LIVN 2019 → **70,692,000**; **LIVN 2020 stays 29,031,000** — the first-draft expectation of 67,343,000 is IMPOSSIBLE: `AdjustmentForAmortization` has **no 2020 entry** in LIVN's companyfacts (series is {2016: 45,511,000, 2017: 45,881,000, 2018: 37,194,000, 2019: 40,375,000} and stops; the 38,312,000 exists only under the tag being gated off). Regression guard: the 22 lone_depreciation cells unchanged; FIX/DT/GE unchanged (this change does not touch them).

**The declared-regression ledger this change ships with (this is why it is conditional):**
- **LIVN 2020: 38,312,000 → 29,031,000 vs true ~67M — measurably WORSE than the status quo.** The change is NOT strictly non-worsening.
- AMD 2022: 4,174,000,000 → 3,987,000,000 (true 4,174M; the old value was correct only because the vote reinstated a superseded mis-tag).
- AMD 2023-2025 remain ~6% low vs the reconciled 3,453M / 3,064M / 3,004M (AMD's "other D&A" 642/671/750M exceeds its Depreciation line).
- AMD 2020/2021 and LIVN 2021/2022 go null (all four currently correct).

**Decision for the operator:** the trade is AMD's latest-FY error −75% → −6% (live in `base_cf`) against the ledger above. If the ledger is unacceptable, ship nothing here and treat all of D2 as blocked; do NOT ship a partial variant that hides the ledger.

**Risk if wrong.** Corpus-wide, the tag supplies 593 cells on 131 names (author-measured, not re-verified); the gate confines all change to AMD/LIVN/ABNB by construction, which the corpus diff must confirm.

---

### 2.6 CH-6 — Persist tag provenance; ship the basis-break detector contract

The resolver already computes provenance and throws it away; the entire change is capture + emission, proven byte-inert on the values.

**Current behaviour, verified.** `resolve_field_series` (def line 289) returns provenance as its third element with exactly four states — line 308 `prov = {y: 'primary' ...}`, 319 `'backfill'`, 341 `'component_sum'`, 346 `'lone_depreciation'`, return 347. `extract_history` discards it at **lines 649-652** (verbatim: `series[field], raws[field], prov = resolve_field_series(` … `summed[field] = {y for y, p in prov.items() if p in ("component_sum", "lone_depreciation")}`) — and `summed` is **never read** (grep: lines 642, 651 only; the promised vote-exclusion happens by accident because those states set `raws[y]=[]` at 341/346). Non-FIELD_SPECS fields get no provenance at all (lines 654/656 call the two-value `annual_duration_series`/`annual_instant_series`).

**Measured facts the design rests on (live 172 / corpus 5,600, from the byte-exact instrumented clone):**
- Live cells 38,881: primary 36,622 / backfill 766 / component_sum 279 / lone_depreciation 22. Corpus 887,299: 843,110 / 15,244 / 4,303 / 22.
- The accession vote overwrites **1,192 live cells on 142 tickers** and **24,620 corpus cells** (2.775%), and the overwrites are material: median rel-change 3.1%, p90 91.6%, max 22.3x (GSAT 2022 shares 120,055,000 → 1,800,825,000; DELL 2020 tax −572M → −5,533M).
- The vote never changes WHICH TAG supplied a cell, only which FILING — structurally (raws come from the winning tag alone; lines 308/319/731) and empirically (base states of the 1,192: {primary 1147, backfill 45}; zero component_sum/lone_depreciation). This is what makes "accession_override" a valid fifth state layered over the base four.
- A state-only record is insufficient: 21 of 316 live tag changes carry no state change.
- PM's 64% revenue collapse is a pure basis change, reconciled **to the dollar**: overlap period ending 2016-12-31, `SalesRevenueNet` 74,953,000,000 vs `RevenueFromContractWithCustomerExcludingAssessedTax` 26,685,000,000; difference 48,268,000,000 == PM's `ExciseAndSalesTaxes` FY2016 exactly (FY2017 identity holds too). Operating income and net income are continuous across the boundary.
- Basis breaks corrupt shipped stats: 25 live op-margin histories span a proven revenue break; PM's shipped `op_margin_10y_median` 0.3752 with `op_margin_years: 12` claims 12 comparable observations when only 10 are; IHG's is off by −4.6pp (0.2115 → 0.1656).

**Spec item A — return the winning tag from the two series functions.** `annual_duration_series`: change the candidate append (**line 396**: `candidates.append((_normalise_series_scale(resolved), raw))` → append `(…, raw, tag)`), the empty return (**line 398**: `return {}, {}` → `return {}, {}, None`), and LEAVE the winner return untouched — the normative locator is the string `return max(candidates, key=lambda s: (max(s[0]), len(s[0])))` (**line 399**; the first-draft anchor "line 397" is the `if not candidates:` line — do not edit that). Identical three edits in `annual_instant_series` (append 434, empty return 436, winner return 437). **Update ALL FIVE two-value unpack call sites** (the first draft listed only two, which crashes on the first field): lines **305, 313, 327** inside `resolve_field_series`, plus **654** and **656** in `extract_history`. TRAP GUARD: the `key=` must keep selecting on `s[0]` only; tuple comparison would let tag strings enter the ordering — the documented 13-capex-loss failure.

**Spec item B — return the tag map from `resolve_field_series` as a fourth element.** At 308 add `tags = {y: ptag for y in series}`; carry the tag through the backfill `alts` tuple (change line ~314 `alts.append((max(s), len(s), s, r))` to append `tag` too; the sort key at **line 316** `lambda z: (-z[0], -z[1])` must stay untouched) and set `tags[y] = tag` at 319; for COMPONENT_SLOTS track the winning slot tag under the same `merged.setdefault` condition and at 341 set `tags[y] = '+'.join(slot_tags)` (the composite is deliberate: it marks a cell with no single filed tag, excluded from overlap testing); at 346 the lone-dep tag; return 4 elements at 347.

**Spec item C — capture in `extract_history`.** (a) Unpack four values at 649-652; delete the now-orphaned `summed` (line 642) — orphaned BY this change, so in scope. For the 654/656 branches set `prov_of[field] = {y: 'primary' …}` and the winning tag. (b) When the override condition fires (**line 738**, verbatim `av != v and _pow1000_ratio(av, v) is None and not (av == 0 and v)` — coordinate with CH-2 if both land: the capture hooks whatever the final override condition is), record `overrides[str(y)][f] = chosen` — do NOT overwrite base state or tag. (c) Store the bin's period-end anchor: the `end_ref` loop is at **lines 692-696** (the first-draft anchor 707-711 is the accession-tally loop and does NOT compute end_ref); save `period_end[str(y)] = end_ref` when non-None. (d) Return `history, {'runs':…, 'overrides':…, 'period_end':…}` — and **also convert the early `return {}` at line 662** (`if not years:`) to the two-value shape, or every empty CIK crashes the build (first-draft omission; failure is loud but the instruction set was incomplete). Single call site at **line 981**.

**Spec item D — emission shape.** Parallel **top-level** `"provenance"` sibling of `"tickers"` with `_schema`, `_states` ({p,b,s,l,o}), index-addressed `_tags` and `_accns` dictionaries, run-length-encoded `runs {T: {field: [[first_year, tag_index, state_code], …]}}` (a run holds until the next run's first_year, intersected with the years actually present; it does not assert a year exists), `overrides {T: {"YYYY": {field: accn_index}}}` (effective state is "o" on membership), `period_end {T: {"YYYY": "YYYY-MM-DD"}}`. Keep `sort_keys=True` at the write (lines 1013-1015); the SUBSET redirect at 1005-1010 already applies. Shape safety was proven by **executed** tests of all four consumer access patterns: a ticker-level sibling silently corrupts `fetch_data.py` (sorts after '2025' and becomes the "latest FY") and raises ValueError in every `int(y)` reader — fatal; year-level and parallel-top-level are both safe; only the parallel map permits RLE, which is +12.96% file growth vs +76.7% per-cell.

**The detector contract (consumer-side; replaces/augments RS2 `valuation_backbone.py::_revenue_break`, lines 443-469 — whose actual bars are down-step <0.60 and up-step >1.67, not a symmetric "40%").** Deterministic, no magnitude threshold:
- **Step 1 (flag):** for each pair of adjacent present years, emit TAG_CHANGE iff the tag changed. **CORRECTED RULE — do NOT filter '+'-joined component tags at Step 1** (the first draft filtered them here, which contradicts its own acceptance counts: filtering yields 296 events/4 UNPROVEN, not 316/24). Emit everything.
- **Step 2 (grade):** if either tag is '+'-joined → UNPROVEN_no_common_period. Else key both tags' annual series by **PERIOD END DATE** (300-400d duration rows, forms 10-K/10-K/A/20-F/40-F; duplicate filings of one period end within a tag resolve by **latest filed date** — normative, the counts reproduce only under this rule). Empty intersection → UNPROVEN. Same value at the nearest common end → BENIGN_same_value. Different → **DISAGREE_proven**, report splice_ratio as DATA, never as a gate. **MATCH ON PERIOD END, NEVER THE YEAR BIN** — bin matching manufactured a phantom 5.15x EXEL break (its FY2015 row ends 2016-01-01 and bins as 2016); 15 live ticker-years on EXEL, ILMN, JNJ, KAI, LHX sit in colliding bins.
- **Step 3 (report):** DISAGREE_proven is a proof by contradiction — one filed period, two filed values — and deliberately does not claim the cause (PM = excise-tax reclassification; EPAC = continuing-ops restatement, ratio 0.5627 at 2017-08-31; NVEC = tag repurposing, ratio 24.11 at 2022-03-31 with all shipped values nonetheless correct). Hand tag names + overlap end + ratio to the analyst layer.

**Acceptance tests (all against the 2026-08-07 zip; every constant re-verified by an independent re-implementation except where marked corrected):**
1. Values byte-inert: 0 differing cells over 5,600 tickers; tickers-only re-serialisation = **28,063,627 B** (corrected — 28,063,731 is the full payload/file size and FAILS on the tickers subtree).
2. Runs: exactly **77** distinct tags, **111,573** runs over 887,299 non-null cells (0.1257 runs/cell). PM revenue = exactly two runs [2014, SalesRevenueNet, b], [2016, RevenueFromContractWithCustomerExcludingAssessedTax, p]; JNJ pretax = [2012, …Domestic, b], [2019, …ExtraordinaryItemsNoncontrollingInterest, p] (pre-CH-1 only).
3. Overrides: exactly **24,620** corpus cells / **1,192** live on **142** tickers, base split exactly {primary 1147, backfill 45}, zero component_sum/lone_dep members, distinct accessions = **8,534** (corrected — the first-draft 8,504 was a transcription error and fails a correct build). JNJ 2022 carries overrides for revenue and pretax_income, accn 0000200406-23-000016.
4. Size: **33.6 MB ± 0.2 MB** as a tolerance, NOT an exact byte gate — two faithful implementations of the same schema measured 33,625,843 and 33,642,519 B (encoding details the schema does not pin). Near 47-50 MB ⇒ RLE not applied.
5. Detector, live book: Step 1 = **316** events on **142** tickers (revenue 137, pretax 70, ocf 63, da 30, capex 10, net_income 4, operating_income 2); Step 2 = **198 BENIGN (124 tickers) / 94 DISAGREE (72) / 24 UNPROVEN (19)** — the 24 split as 20 '+'-tag events (16 tickers) + 4 genuine no-common-period (KRYS ocf 2018, UTHR net_income 2021, ZTO revenue 2018, ZTO ocf 2017). Corpus: 6,252 events on 2,976 tickers. PM: DISAGREE at end 2016-12-31, 74,953,000,000 vs 26,685,000,000, ratio 0.35602310781423024. **NEGATIVE CONTROL: EXEL revenue 2016 must grade BENIGN with 191,454,000 == 191,454,000 at end 2016-12-30; a ~5.15 DISAGREE means the implementation bin-matches and is WRONG.** DISAGREE revenue set = 27 names, of which exactly 20 (ADI, CLS, CRM, CW, DELL, DOV, EXPE, GRMN, HCSG, ISRG, JKHY, MA, NVEC, PSMT, RMD, RNG, ROP, TEAM, TYL, VRT) are invisible to `_revenue_break` and exactly 7 flagged by both; `_revenue_break` alone flags 40.
6. Consumer safety: for all 5,600 tickers `sorted(int(y) for y in d['tickers'][t])` must not raise and the last key is a 4-digit year.

**Risk if wrong.** Primary-vote trap (guarded by test 1, run FIRST); a bin-matched detector (guarded by EXEL); the fifth state is valid **only while the vote draws candidates from a single tag** — add a build-time assertion so a future widening fails loudly.

---

### 2.7 CH-7 — Marketable securities: `st_investments` + `lt_investments`

**Current behaviour.** `INSTANT_TAGS` (lines 98-116) has 11 fields and nothing matching /Securit|Investment/. Net-debt consumers see securities-heavy balance sheets as levered.

**Measured damage.** GOOG FY2025 (@2025-12-31, 10-K accn 0001652044-26-000018): cash 30,708M, lt_debt 49,085M → shipped net debt **+18,377M**; `MarketableSecuritiesCurrent` 96,135M flips it to **−77,758M net cash** — and the figure is proven the right line by the filer's own identity: 30,708 + 96,135 = 126,843 == `CashCashEquivalentsAndShortTermInvestments` exactly. Six live names flip sign (AAPL swing 96,486M; GOOG/GOOGL; META; MU; ADSK). Coverage: st resolves for 73/172 at latest FY (103 in ≥1 year, 800 ticker-years); lt for 23/172 (264 t-y); lt-at-latest-FY ⊂ st.

**Change (three parts, all mandatory together).**
(a) **INSTANT_TAGS additions**, inserted after `"retained_earnings"` (line 115), with the ladder/never-sum comment:
```python
"st_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                   "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                   "OtherShortTermInvestments", "HeldToMaturitySecuritiesCurrent"],
"lt_investments": ["MarketableSecuritiesNoncurrent",
                   "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
                   "HeldToMaturitySecuritiesNoncurrent"],
```
Two fields, deliberately not merged: AAPL FY2025 is 18,763M current vs 77,723M noncurrent — 80.6% of the balance is not one-year liquidity. Ladders are alternatives for ONE line, never summed (ADI FY2025 files 1,153M under two tags for the same line; component-sum vs filer-total has p10 = 0.133 over 81 paired t-y).
(b) **VOTE_FIELDS exclusion** — the accession vote scores accessions by field coverage; letting the new fields vote rewrote 11 pre-existing cells on 2 tickers in measurement (RC FY2015 total_assets 775,138,921 → 2,329,781,000; CPT FY2017 revenue 8,176,000 → 900,896,000). After line 656 insert `VOTE_FIELDS = [f for f in series if f not in ("st_investments", "lt_investments")]` (with the comment recording the RC/CPT measurement); change the loop headers at **line 693** (end_ref loop) and **line 707** (accns loop) from `for f in series:` to `for f in VOTE_FIELDS:`; **line 728 (row-build loop) UNCHANGED** — the new fields must still RECEIVE the chosen accession's correction. **Hardening added by the adversarial pass:** also exclude the new fields from the years-union at **lines 658-663** — `sorted(years)[-MAX_YEARS:]` truncates before the revenue/assets row filter, so a new-field-only year bin could evict the oldest existing year-row; zero occurrences measured over 1,374 tickers, but the exclusion is free (a new-field-only year can never form a row anyway) and the "0 removed year-rows" gate backstops it.
(c) **Refusal-block comments** appended to the refused-tags block (opens **line 279**, append after the `PaymentsToAcquireBusinesses*` line at 287), each with its disproving filer — see REJECTED §3.4-3.8 for the list; the comment text must carry the filer and number.

**Per-filer verification (highlights; exact-dollar corrections from the adversarial pass folded in).** TAKEN: GOOG identity exact; PAYX is the positive control that the ladder separates fiduciary from corporate (corporate `MarketableSecuritiesCurrent` 36,300,000 while client float sits under `FundsHeldForClients` 4,832,000,000, untouched); REGN 5,487,100,000/10,260,600,000; BMRN 248,930,000/492,242,000; CRM st 2,238,000,000 with the 7,591M "strategic investments" excluded. REFUSED with proof: GE `LongTermInvestments` 38,788M is run-off insurance float against `LiabilityForFuturePolicyBenefits` 35,438M; PAYC `Investments` 5,507M is client funds (RestrictedCash **4,762,500,000**, LiabilitiesCurrent **5,368,400,000**); PCTY **3,482,421,000**; HG **5,026,660,000** (=144.6% of mcap, insurer); UVE **1,532,604,000** / AFS **1,431,028,000**; BMRN's un-suffixed AFS total double-counts 100% of its cash to the dollar (2,052,851,000 − 741,172,000 = 1,311,679,000 == cash); NHC un-suffixed `MarketableSecurities` **303,462,000** vs current-asset headroom 216M (AssetsCurrent **461,820,000**). INVA is the accepted false negative: its **404,497,000** IS marketable AFS debt but sits under the GE-poisoned tag — coverable only by named allowlist with evidence, never by rule. Known defects, declared: **2 defective ticker-years out of 800** (corrected from 3 — LIVN FY2015 was re-measured and is a bin-collision of one tag at two period ends, with the shipped 6,997,000 being the filer's correct December year-end): SYK FY2024 ships 91,000,000 vs true 841,000,000 (two genuinely different lines under two tags — the 1-in-250 multi-component case); ARWR FY2022 ships 0 while `HeldToMaturitySecuritiesCurrent` files **268,391,000** (winner-tag zero-masking). Neither is at any latest FY.

**Acceptance test.** Subset run (`--tickers GOOG,GOOGL,AAPL,META,REGN,BMRN,SYK,MPWR,CRM,GE,PAYC,PCTY,HG,UVE,INVA,NHC,GD,PAYX,ANET,CSCO,ARWR`), assert on the SUBSET file: GOOG 2025 st = 96,135,000,000 / lt None; GOOG 2024 = 72,191,000,000 / 266,000,000; AAPL 2025 = 18,763,000,000 / 77,723,000,000; META 2025 = 45,719,000,000; REGN 5,487,100,000 / 10,260,600,000; BMRN 248,930,000 / 492,242,000; ANET 8,779,100,000; CSCO 7,764,000,000; CRM 2026 = 2,238,000,000; PAYX 2026 = 36,300,000; **MPWR 2025 = 157,243,000 — FAILS as 389,310,000 if the vote wiring is missing** (its 10-K carries four 2025-binned instants — Mar/Jun/Sep/Dec — and only the bin-end anchor recovers the Dec value; the same mechanism is already load-bearing for CSCO FY2020 cash). MUST BE None: GE, PAYC, PCTY, HG, UVE, INVA, NHC, GD (both fields) — any value is a refused tag leaking in. Known-defect assertions (so future drift is caught): SYK 2024 == 91,000,000; ARWR 2022 == 0. Full-build byte-identity: **0 changed pre-existing cells, 0 removed/added year-rows** (measured 0 over 298,656 cells / 1,374 tickers = live 172 + seeded-1,200 + RC + CPT; the FULL 5,600 diff is the closing gate and must actually be run). Sentinels: RC 2015 total_assets == 775,138,921; CPT 2017 revenue == 8,176,000.

**Risk if wrong.** Implementing only the INSTANT_TAGS half ships a silent 0.17%-of-tickers data rewrite. IFRS blind spot: 13 of the 14 IFRS filers get None (see STOP §4.3) — consumers must distinguish None from zero. HTM tags are amortized cost, not fair value. `cash` can already include restricted cash for some filers (ladder entry at 106-108) — measure before wiring any RS2 net-debt consumer (STOP §4.10).

---

### 2.8 CH-8 — Per-year SBC (`sbc`)

**Current behaviour.** No SBC field. RS2 consumes the vendor scalar `SBC_Stock_Based_Comp` (`fetch_data.py:603`), which is provably wrong or null for named live names: AIT 7,289,000 = the `RestrictedStockExpense` COMPONENT only (filed total `AllocatedShareBasedCompensationExpense` 12,002,000 = 7,289,000 + 4,713,000 exactly); ZTO 229,250,000 is the CNY row (USD row in the same 20-F accession: 32,782,000); RTX 1,092,000,000 matches no RTX SBC fact (filed 519,000,000); LHX 366,000,000 vs filed 113,000,000; CMI/AZN/GE/GEV null.

**Change.** (a) `DURATION_TAGS` gains exactly one line after `"tax_provision"` (ends line 96): `"sbc": ["ShareBasedCompensation"],` — single-tag primary, so the primary vote cannot re-rank (trap respected by construction). (b) `FIELD_SPECS["sbc"] = {"COMBINED": ["ShareBasedCompensation", "AdjustmentsForSharebasedPayments", "AllocatedShareBasedCompensationExpense"], "COMPONENT_SLOTS": []}` — note for the implementer: backfill priority is `(-max_year, -coverage)` at line 316, NOT list order; the list order is documentation. (c) Extend the refused-tags block (**lines 279-286** — corrected anchor; the annual_duration_series call sites inside `resolve_field_series` are **305, 313, 327**): `AllocatedShareBasedCompensationExpense` backfill-only, never primary (component at AIT; 7.7x superset/mis-tag at SIMO — 203,305,000 vs filed 26,283,000 against 93,037,000 operating income; SIGN-FLIPPED at INTU 2008-2010); `ExpenseFromSharebasedPaymentTransactionsWithEmployees` is the P&L expense, not the CF add-back (NVS 1,330M vs 1,096M); `IncreaseDecreaseThroughSharebasedPaymentTransactions` is an equity movement (IHG 67M vs 47M).

**Coverage & choice evidence.** `ShareBasedCompensation`: 153/172, median 17 years; best match to the independent APIC equity-statement witness (85.3% vs Allocated's 78.0%). Proposed field populates 169/172 (absent: CIX — files no SBC tag of any kind; HEI; SAP — all-EUR), present at latest history year 166/172, ≥8 of last 10 FYs for 148. Backfill from Allocated touches 12 names; the two off-ratio cases (AIT 1.545, CMI 0.936) are both cases where Allocated is the CORRECT total. **Declared, per the adversarial pass:** GE, GEV, DOCU, CHE ship series sourced 100% from Allocated with no cross-tag witness possible (values that would ship: GE 2025 325,000,000; GEV 2025 257,000,000; DOCU FY2026 622,321,000; CHE 2025 38,680,000) — plausible in magnitude, unverifiable per-filer; declared, not hidden. **AIT known defect widened (corrected):** AIT's `ShareBasedCompensation` has FIVE component-valued years, 2016-2020 (2,524,000 / 3,629,000 / 4,666,000 / 4,474,000 / 4,000,000 vs true 4,067,000 / 5,520,000 / 6,627,000 / 6,913,000 / 6,954,000), not two — COMBINED backfill cannot overwrite a primary-filled year, so all five ship understated; declared. **7 negative ticker-years flow through unguarded and must** (PAYC FY2024 −22,900,000 is a genuine forfeiture reversal filed identically under both tags in two successive 10-Ks; a sign guard deletes filed truth — REJECTED §3.10). Fiscal-calendar note: LHX's 113,000,000 lands in bin '2026'; bin '2024' is genuinely empty, consistent with LHX's existing history binning.

**Acceptance test.** AAPL 2025 == 12,863,000,000, 2024 == 11,688,000,000; RTX 2025 == 519,000,000 (NOT 1,092,000,000); LHX 2026 == 113,000,000; ZTO 2025 == 32,782,000 (NOT the CNY 229,250,000 — the USD-only unit filter protects this); GD 2025 == 196,000,000; SIMO 2025 == 26,283,000 (proves Allocated did not overwrite a primary year); CMI 2025 == 93,000,000 and 2024 == 100,000,000 (backfill; vendor null — pure gain); AIT 2025 == 12,002,000 (NOT 7,289,000); AZN 2025 == 719,000,000 (ifrs backfill, vendor null); NVS 2025 == 1,096,000,000 (ifrs backfill; **corrected: NVS's vendor value is 1,096,000,000, not null** — only AZN is vendor-null in that pair). Coverage gates: non-null at latest FY for ≥ **166**/172; ≥8 of last 10 FYs for ≥ **148**. Full-corpus diff: no pre-existing field changes anywhere.

**Optional, gated behind filing reads (do NOT ship blind):** `SBC_LONE_TAG_ALLOWLIST {"HEI": "StockOptionPlanExpense", "EMBJ": "IncreaseDecreaseThroughSharebasedPaymentTransactions"}` mirroring the lone-depreciation branch. HEI files no total tag (only StockOptionPlanExpense, FY2025 34,381,000 — matching the vendor, an independent second source but not the filing); EMBJ's CF tag stops at 2022 while the equity tag continues and matched exactly in all 3 overlap years — but the same tag disagrees badly at IHG and CGAU, so it can never be a rule. Without the allowlist HEI/EMBJ ship null and the 166 gate is met anyway.

---

### 2.9 CH-9 — Debt component fields (legacy `lt_debt` untouched)

**Current behaviour.** `lt_debt` ladder (line 109) is `["LongTermDebtNoncurrent", "LongTermDebt"]` — two tags with DIFFERENT definitions (noncurrent-only vs total-incl-current), mixed silently across the book (winner: Noncurrent for 96 live names, LongTermDebt for 35). Root cause of the deaths: ASC-842-era tag migration to `LongTermDebtAndCapitalLeaseObligations(+Current)` etc., unmapped, so series simply stop.

**Measured damage (live, verified against the shipped file).** Null/zero/understated for **28 of 172** at the latest FY. MAR 2025 ships **23,000,000** — a LongTermDebt residual that wins the production 2-tag list on recency — vs 14,995,000,000 + 1,209,000,000 real (99.86% understatement). ABNB 2025 ships **literal 0** (2026 converts reclassified to current: `LongTermDebtCurrent` 1,999,000,000) — reads downstream as debt-free. AVGO null on 65,136,000,000 (which equals vendor Total_Debt exactly as LTCL 61,984M + LTDCurrent 3,152M; the filer's own `DebtLongtermAndShorttermCombinedAmount` 67,120M is a face-value figure 1,984M higher — why components are preferred over the total tag). PM null on 48,667M. Consumers hit: `score_factors.py:341` EV understated by full debt for these names; RS2 net-debt/net-cash sites.

**Change.** Five NEW fields; `lt_debt` byte-identical for compatibility (blast radius if redefined in place: Piotroski 778-779, Beneish 874-877, fetch_data 393, score_factors 341, RS2 853/168 — all verified).

(a) Module-level `INSTANT_FIELD_SPECS` (after the refusal block, before `resolve_field_series` at 289):
```python
INSTANT_FIELD_SPECS = {
 "debt_lt_noncurrent": {"COMBINED": ["LongTermDebtNoncurrent",
   "LongTermDebtAndCapitalLeaseObligations",   # == LongTermDebtNoncurrent in 25/27 live filers filing both: lease NOT inside
   "LongtermBorrowings", "NoncurrentPortionOfNoncurrentBondsIssued"]},   # ifrs; TSM
 "debt_current": {"COMBINED": ["LongTermDebtCurrent",
   "LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent",
   "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
   "CurrentPortionOfLongtermBorrowings", "ShortTermBorrowings", "ShorttermBorrowings"]},
 "short_term_borrowings_separate": {"COMBINED": ["CommercialPaper", "ShortTermBorrowings", "ShorttermBorrowings"]},
 "finance_lease_liability": {"COMBINED": ["FinanceLeaseLiability", "CapitalLeaseObligations"],
   "SUM_PAIRS": [("FinanceLeaseLiabilityCurrent", "FinanceLeaseLiabilityNoncurrent"),
                 ("CapitalLeaseObligationsCurrent", "CapitalLeaseObligationsNoncurrent")]},
 "operating_lease_liability": {"COMBINED": ["OperatingLeaseLiability", "LeaseLiabilities"],
   "SUM_PAIRS": [("OperatingLeaseLiabilityCurrent", "OperatingLeaseLiabilityNoncurrent"),
                 ("CurrentLeaseLiabilities", "NoncurrentLeaseLiabilities")]},
}
```
(b) New resolver `resolve_instant_field_series(facts, spec, unit_keys=("USD",))` after `annual_instant_series` (winner return at **line 437**): resolve one tag at a time **in list order**, first tag to cover a year wins it; provenance = `'primary'` for `combined[0]`, else **the tag name** (this is what the code emits — a first-draft acceptance test expected 'primary' for a second-tag fill and could never pass). `FIELD_SPECS` cannot be reused (`resolve_field_series` hard-calls the duration function at 305/313/327; instants have no start date and never pass the 300-400d gate). **CORRECTED RATIONALE for list-order-not-single-call** (the first draft's MAR-residual justification is FALSE — measured, the expanded single call `annual_instant_series(MAR, [Noncurrent, LongTermDebt, LTCL])` returns 14,995,000,000 because LTCL ties on recency and wins on coverage 15-vs-9; only the PRODUCTION 2-tag list yields 23,000,000): the single-call recency+coverage vote can crown `LongTermDebt` — a **total-including-current** — for a **noncurrent-only** field, mixing definitions. List order with a curated ladder is the fix; do not "restore" a single call.
**SUM_PAIRS — CORRECTED, both sides mandatory:** the first draft's `(sa.get(y) or 0) + (sb.get(y) or 0)` over the union emits a ONE-SIDED component as the field total — measured **101 live ticker-years** fire one-sided (CMI finance-lease 2009-2017 noncurrent-only; EXPE/MEDP operating-lease 2018 = 0 from a lone 0-valued side = a false "no leases"). Require BOTH sides present for a year (mirror the COMPONENT_SLOTS all-slots rule at ~340), provenance `'pair_sum'`, `raws[y] = []`.
(c) In `extract_history`, after the INSTANT_TAGS loop (655-656), resolve the five new fields. Pair-sum years carry `raws[y]=[]` and are thereby excluded from the accession vote — that is the actual mechanism (**corrected:** `summed` is write-only dead state, assigned at 642/651 and never read; do not describe registering it as load-bearing). **The five new fields MUST join CH-7's VOTE_FIELDS exclusion** (both loop headers AND the years-union) — six added fields change the vote's `mx` denominator and 0.8 bar for every pre-existing field; prove inert with the full-corpus byte diff, do not argue it.
(d) File-header `_debt_note` (at the write, 1013-1015): `debt_lt_noncurrent + debt_current` = interest-bearing debt EXCLUDING all leases; `short_term_borrowings_separate` is additive only when debt_current resolved from `LongTermDebtCurrent` (verified 15 of 16 live names; DOV overshoots) and must NOT be added when it resolved from `DebtCurrent`/`ShortTermBorrowings` (nesting is filer-specific: EMR's DebtCurrent 4,797M = LTDCurrent 605M + CP 4,192M exactly, ITT's DebtCurrent == ShortTermBorrowings with CP nested inside); leases are separate BY DESIGN (§4.9); `lt_debt` is LEGACY, null/zero/understated for 28/172 live names, not for new work. Footnote: ifrs `LeaseLiabilities` (mapped into operating_lease_liability) is ALL IFRS-16 lease liabilities — IFRS does not split operating from finance — so AZN/NVS-class filers include finance-lease equivalents there.

**Per-filer verification (highlights).** MAR: LTCL 14,995,000,000 + 1,209,000,000 (Noncurrent tag died 2011). PM: 45,134M + 3,533M; vendor 48,835M = 48,667 + STB 168 exactly. AVGO as above. AAPL: 78,328M / 12,350M with separate CP 7,979M, finance lease 1,230M, operating lease 12,490M — reproducing the vendor's 98,657M as LTD+CP while EXCLUDING both leases. AZN: ifrs identity exact both years — Borrowings 29,622M = 24,715 + 3,104 + **leases 1,803** (Borrowings INCLUDES IFRS-16 leases); SAP: Borrowings 6,150M = 4,550 + 1,600 with leases 1,684M EXCLUDED — same tag, opposite composition, which is why `Borrowings` is refused as a rule (§3.14). ROST: vendor 5,212,338,000 == LongTermDebt 1,517,606,000 + operating lease 3,694,732,000 exact, and the component tags reproduce 1,517,606,000 (1,017,863,000 + 499,743,000) — vs AIT, where the same vendor field equals long-term debt alone with 198,320,000 of operating leases excluded: the vendor has no single definition and is REJECTED as a target (§3.13).

**NVS is a declared STOP inside this change (corrected — the first draft's narrative contradicted its own spec):** NVS files no `LongtermBorrowings` for 2025; with Borrowings refused, the spec as written emits `debt_lt_noncurrent = null` and `debt_current = 794,000,000` against true Borrowings 28,729,000,000 — a null→0 summing consumer (the live `num(...) or 0.0` pattern) reads 97%-understated debt. Resolution required before ship: either a named per-filer Borrowings allowlist for NVS (evidence already measured: leases 1,920M sit OUTSIDE its Borrowings) or NVS nulled with the gap declared. Do not ship the ambiguous middle.

**Acceptance test.** Coverage gates at latest history year, live book — **the deliverable numbers** (the first-draft "usable total 121/172" counted 13 sources — LongTermDebt-only 9, Borrowings 2, DebtLongtermAndShorttermCombinedAmount 2 — that no proposed field maps; do not gate on 121): debt_lt_noncurrent ≥ **103**/172, debt_current ≥ **103**, finance_lease_liability ≥ **57**, operating_lease_liability ≥ **165**. Spots: MAR 2025 = 14,995,000,000 / 1,209,000,000, with resolver provenance == **'LongTermDebtAndCapitalLeaseObligations'** (not 'primary'); PM 2025 = 45,134,000,000 / 3,533,000,000; AVGO 2025 = 61,984,000,000 / 3,152,000,000; AZN 2025 = 24,715,000,000 / 3,104,000,000 with the 1,803M leases in operating_lease_liability, not debt; AAPL as above; ABNB 2025 debt_current = 1,999,000,000. **Production contrast test** (replaces the refuted expanded-list test): `annual_instant_series(MAR_facts, ['LongTermDebtNoncurrent','LongTermDebt'])` returns 2025 → 23,000,000 — the production failure the new resolver must beat. NO field named total_debt/net_debt anywhere in the output. Full-corpus byte diff: every pre-existing field identical, ticker-year key set unchanged.

**Risk if wrong.** Vote perturbation (guarded); a consumer summing components with null→0 understates names whose only total is an unmapped tag — the `_debt_note` and the None-vs-0 distinction are the mitigation; SUM_PAIRS regression to union-mode reintroduces the 101 one-sided cells.

---

## 3. REJECTED

Proposals killed by measurement or the adversarial pass. Re-proposing any requires evidence stronger than the refutation cited.

1. **Ticker-level `_provenance` sibling key.** Executed test: `fetch_data.py:377-378` sorts it after '2025' and silently feeds provenance strings into ROIC/gross-margin/Altman-Z; every `int(y)` reader raises. Parallel top-level map only.
2. **Per-year / per-cell provenance encodings.** Measured +66.9% to +76.7% file growth vs +12.96% for RLE. Rejected on size with no information gain.
3. **Detector Step-1 filtering of '+'-joined tags.** Internal contradiction: filtering yields 296 events / 4 UNPROVEN and can never satisfy the 316 / 198-94-24 acceptance counts. Emit all changes; grade '+' events UNPROVEN at Step 2.
4. **`Investments` (us-gaap) for securities.** Fiduciary/insurance float: PAYC 5,507M = 72.5% of assets vs client-fund LiabilitiesCurrent 5,368,400,000; PCTY 3,482,421,000; HG 5,026,660,000 = 144.6% of market cap; UVE 1,532,604,000.
5. **`LongTermInvestments`.** Polysemous with opposite economics: GE 38,788M = insurance run-off vs INVA 404,497,000 = genuine AFS debt. No rule separates them; neither taken (INVA's false negative accepted and declared).
6. **`AvailableForSaleSecuritiesDebtSecurities` (un-suffixed total).** BMRN identity to the dollar: total − (current + noncurrent) == cash — 100% double-count of cash; above current-asset headroom in 81 of 487 testable t-y (AAPL 2018: 237,100M vs 105,426M).
7. **`OtherLongTermInvestments`, un-suffixed `MarketableSecurities`, `CashCashEquivalentsAndShortTermInvestments`, equity-method/non-readily-determinable tags.** GOOG's OtherLTI 68,687M is literally "Non-marketable securities"; NHC's MarketableSecurities exceeds its own current headroom; CCESTI contains cash by definition.
8. **Summing securities ladder tags / component summing.** Tags are duplicate labels for one line (ADI 1,153M under both); sum-vs-filer-total p10 = 0.133 (ADI 2011-15 sums to 0-1M vs true 2,187-4,291M).
9. **`AllocatedShareBasedCompensationExpense` as SBC primary.** Component at AIT, 7.7x mis-tag at SIMO, sign-flipped at INTU. Backfill only.
10. **Blanket sign guard on SBC.** PAYC FY2024 −22,900,000 is a genuine forfeiture reversal filed under both tags in two successive 10-Ks. A guard deletes filed truth.
11. **Symmetric `_pow1000_ratio` block without median arbitration.** Would block the one overwrite that is CORRECT (NHC 2023 sga) and ship a 21.4-trillion SG&A.
12. **Blanket removal of `OtherDepreciationAndAmortization`.** Measured worse for 2 of 3 live users: ABNB 2023 −30% and 2024 nulled; AMD 2020/2021 (correct) nulled; corpus 272 cells changed in an unverifiable direction, 249 nulled.
13. **Vendor `Total_Debt` as extraction target.** No single definition: 56 live names reproduce only WITH operating leases, 23 only WITHOUT while carrying material leases, 21 under no formula (AMZN reproducible by nothing tested).
14. **ifrs-full `Borrowings` as a rule.** AZN's includes IFRS-16 leases (identity exact, two years); SAP's and NVS's exclude them (identity exact). Per-filer allowlist or nothing.
15. **Ungated capex tags.** GSAT refuted outright (tag <1% of actual PP&E additions); TEAM blocked by an irreconcilable dual FY2017 value (15,129,000 filed 2018 vs 925,000 filed 2019 — most-recent picks the wrong one); INCY unverified (2023 off 2.2x); IFRS bundled element (KMDA/CLS/SAP) is a capex DEFINITION change (includes intangible purchases), not a coverage fix; `CapitalExpendituresIncurredButNotYetPaid` is an accrual disclosure, not cash.
16. **Split adjustment as an inferred rule.** companyfacts DOES carry `StockholdersEquityNoteStockSplitConversionRatio1` with dates for 16 of 19 candidates (the "no source" premise was wrong and is corrected), but the fact names no fiscal-year set, multi-splits need hand composition, the observed step never equals the ratio (AAPL 3.719 vs filed 4.0), and VRT/CART/LIVN have no ratio at all. Per-filer verified table only (out of scope).
17. **Summing short-term debt tags.** `DebtCurrent` is a sum at EMR, an alias at ITT, triple-identical at LLY 2013. companyfacts carries no statement placement; components are emitted, never summed.
18. **One merged securities field.** AAPL: 80.6% of its $96.5bn book is not one-year liquidity — a merged field misstates it 5.1x.
19. **MAR expanded-list contrast test.** Refuted by execution: the expanded single call returns 14,995,000,000 (LTCL wins on coverage), not 23,000,000. Replaced by the production 2-tag contrast (§2.9).
20. **SUM_PAIRS union with `or 0`.** 101 live one-sided ticker-years = components promoted to totals, the Novartis shape. Both sides required.
21. **Wiring DISAGREE_proven to automatic margin/window trims.** The three proven causes (PM reclassification, EPAC restatement, NVEC repurposing) demand different responses; `_revenue_break`'s own docstring records auto-trimming was tested and rejected. Ship flag + tags + overlap end + ratio; the analyst layer judges.
22. **`COMPONENT_SLOTS=[[Domestic],[Foreign]]` pretax recovery.** Gains 0 live cells (COMBINED wins all 165; NHC has no Foreign leg). Dead code.
23. **Describing `summed[]` as the vote-exclusion mechanism.** It is write-only dead state (assigned 642/651, never read); exclusion works via `raws[y]==[]`. A wrong stated mechanism is itself the failure mode this repo documents.

---

## 4. STOP CONDITIONS

What cannot be fixed from companyfacts, what would close each gap, and the honest interim behaviour. Per CLAUDE.md §0: never substitute a weaker method the data happens to allow.

1. **FIX (Comfort Systems) D&A — the most urgent unfixed live defect.** FY2025 (latest FY, feeding `base_cf` now) ships 62,400,000 == its own Depreciation line to 0.03% while `AmortizationOfIntangibleAssets` is a separate 79,580,000 → −56.0% (FY2024 −66.9%; 2019-2023 −52% to −59%). Not fixable by tag lists — `DepreciationAndAmortization` is a legitimate total for 223 other live primary cells. Needs a per-filer override AFTER reading FIX's cash-flow statement. Interim: shipped value stands; declare it to the analyst layer. If Tier-1 ships without this, the book still carries a 56% D&A understatement on FIX — do not mark the D&A work "done".
2. **ABNB D&A adjudication.** companyfacts cannot decide whether ABNB's CF D&A total is OtherD&A (138M FY2021) or Depreciation+Amortization (110M); what IS proven is the shipped 2019-2022 primary equals the depreciation line and is partial either way. One filing read closes it. DT's 2018-2023 history (−77% to −91%, self-healed from 2024, leaving a 4.4x artificial step at 2023→2024) is the same class.
3. **IFRS filers, securities.** 13 of the 14 live IFRS filers get `st_investments = None` structurally (only TEAM resolves, via a us-gaap tag). The ifrs financial-asset families are note-level grab-bags (NVS OtherCurrentFinancialAssets 1,998M → 155M in one year with cash flat). Closing this needs a source beyond companyfacts. Interim: None ≠ 0; consumers must not rank Nones as "no securities".
4. **SAP and all non-USD-only filers.** The USD unit filter (deliberate, commented at 63-67) excludes SAP entirely (EUR SBC, EUR Borrowings 6,150M, history stops 2017). No field in this package can cover them without an FX policy — out of scope. Declare and leave null; never substitute a EUR figure into a USD field. `cik_map.json` (fetched 2026-06-10/2026-06-23 vintage) bounds all coverage: post-dated listings/symbol changes resolve wrong or not at all.
5. **PM SBC after 2011; HEI; EMBJ/NVEC after 2022; CIX.** PM's only SBC tag ends 2011 — any later value would be invented; null. HEI files only a component (allowlist candidate after a filing read). EMBJ/NVEC's continuing adjacent tag is a different concept at IHG/CGAU — allowlist-or-null. CIX files no SBC element at all — null is correct.
6. **Capex beyond LLY and ROP.** 59 of 78 live null cells stay null: genuine non-filers (HG, VIK, ABNB 2023-25, ADSK 2015-18, NUTX, ARGX, LHX, VRT — widened tag search returns no PP&E-purchase element), refuted (GSAT), unverified (INCY), definitional (KMDA/CLS/SAP), conflicted (TEAM FY2017), accrual-only (UFPT, SPHR). RS2 already declares gaps to the model; that remains the honest behaviour.
7. **An authoritative "total debt" scalar.** Cannot be met from companyfacts (no statement placement; current-tag nesting is filer-specific). If a consumer requires one, escalate — do not approximate.
8. **NVS debt.** Decision required before CH-9 ships: per-filer Borrowings allowlist (evidence in §2.9) or declared null. The measured default emits a misleading 794M debt_current.
9. **Operating leases as debt.** A post-ASC-842 judgment, not a data question; the vendor itself is inconsistent (56 with / 23 without / 21 neither). The extractor emits `operating_lease_liability` separately; whoever consumes it must state their choice in writing. 38 live names have operating leases and NO other debt.
10. **Wiring RS2 consumers to the new securities/debt fields.** Adding fields is inert; USING them is a valuation change requiring separate approval, plus two unmeasured prerequisites: (a) how often `cash` already contains restricted cash (ladder entry 106-108); (b) whether amortized-cost, long-dated `lt_investments` belongs in a net-debt bridge at all. This package takes no position.
11. **Detector component_sum arm.** 20 of 24 UNPROVEN events involve '+'-tags with no single filed series. The slot-sum-vs-combined overlap extension is unimplemented and unmeasured — report UNPROVEN honestly; do not treat as continuous, do not build the extension without measuring it on real filers.
12. **SPHR 2020 shares (34,942,000 → 24,017, a 1455x gap).** Outside every power-of-1000 band and the arbitration's reach. Adjudicate alone; do NOT widen the band — it protects NVDA's real 29x net-income jump and AMZN's real 20:1 split (documented at 152-157).
13. **The fifth-state invariant.** "accession_override" is valid only while the vote draws candidates from a single tag (holds by construction and empirically today). Add a build-time assertion; if the vote is ever widened across tags, the provenance contract must be redesigned first.
14. **The stale-zip discipline.** If the local zip's mtime/entry-count (2026-08-07T14:27:51Z / 20,175) doesn't match before acceptance runs, expected numbers are void — re-verify the source before calling anything a code defect. A cloud-run drift = new filings: re-baseline, never force.
15. **Fiscal-bin instability (logged for the owner, not this change).** EXEL's Jan-1-3 year-ends shift its bins (no 2019/2024 rows, but 2020/2026 — "FY2020" is fiscal 2019); 15 live ticker-years on EXEL, ILMN, JNJ, KAI, LHX collide. CH-6's `period_end` block makes this visible for the first time; re-binning is a separate, larger question.

---

## 5. ACCEPTANCE — HOW TO KNOW THE REBUILD IS GOOD

Run per change, in the shipping order, each against a pre-change baseline copy of `fundamentals_history.json`. All expected numbers assume the 2026-08-07 zip; on the cloud's fresh fetch, treat ≤5% drift in COUNT-type gates as new filings and re-baseline — but a drift in a BYTE-IDENTITY or 0-LOST gate is always a defect.

**Universal gates (every change):**
- Full-corpus diff of every pre-existing (ticker, year, field): pure-addition changes (CH-6, CH-7, CH-9) require **0 changed / 0 lost / 0 added year-rows**. Value-fixing changes (CH-1..5, CH-8) require the diff to equal the enumerated expected set EXACTLY — nothing else moves.
- **Coverage must not DROP for any field** on the live book. RS2's `data_health.py --update-baseline` tracks 93 field coverages over the 172; run it after each cloud rebuild — it is the natural regression tripwire for this whole package (new fields appear as new coverage rows; a vanished field screams).
- Consumer safety: for all 5,600 tickers, `sorted(int(y) for y in d['tickers'][t])` does not raise; last key is a 4-digit year; document root gains only the agreed siblings (`provenance`, `tag_provenance`, `_debt_note`).
- Tickers-only serialization stays **28,063,627 B** for pure-addition changes (full payload 28,063,731 pre-change).

**Field coverage, live book (172), before → after all changes ship:**

| Field | Before (latest-FY non-null) | After | Check |
|---|---|---|---|
| pretax_income history cells | 173 Domestic-corrupted | 0 (165 corrected, 8 NHC nulls) | identity fails ≤200/1,827, flips ≤20 |
| shares_diluted | 64 basic cells, 23 scale-corrupt cells | 0 basic-where-diluted-exists, 0 scale | 44 changed +14 gained, 0 lost; 23 restorations |
| capex / fcf | LLY+ROP 19 null cells | filled | gained exactly 19+19; GSAT still null |
| da (AMD) | −75% latest FY | −6% | CH-5 ledger honored, if shipped |
| sbc | (absent) | ≥166/172 latest FY | ≥148 with ≥8/10 years |
| st_investments / lt_investments | (absent) | 73 / 23 at latest FY | 8 trap names None |
| debt fields | lt_debt dead for 28 names | 103/103/57/165 | lt_debt itself byte-identical |
| provenance | (absent) | 77 tags, 111,573 runs, 8,534 accns, 24,620 overrides | detector 316 → 198/94/24 |

**Named spot-checks (one command each, post-rebuild):** GOOG 2014 pretax == 17,259,000,000 · GRMN 2014 shares == 194,165,000 · INVA 2021 shares == 94,310,000 · LLY 2025 fcf == 8,972,000,000 · ROP 2019 capex == 52,700,000 · AMD 2025 da == 2,821,000,000 (if CH-5) · RTX 2025 sbc == 519,000,000 · ZTO 2025 sbc == 32,782,000 · GOOG 2025 st_investments == 96,135,000,000 · MPWR 2025 st_investments == 157,243,000 · MAR 2025 debt_lt_noncurrent == 14,995,000,000 · ABNB 2025 debt_current == 1,999,000,000 · PM revenue provenance = two runs splitting at 2016 · EXEL revenue 2016 detector grade == BENIGN_same_value · RC 2015 total_assets == 775,138,921 · CPT 2017 revenue == 8,176,000 · NHC 2023 sga == 21,412,000.

**Identity checks:** pretax ≈ NI + tax (per CH-1 bounds); GOOG cash + st_investments == CashCashEquivalentsAndShortTermInvestments == 126,843,000,000; ladder_pick ≤ current_assets − cash (zero live violations expected); zero cells with base state component_sum/lone_depreciation in the overrides map.

---

## 6. WHAT WAS NOT VERIFIED

Honest gaps in this package's own evidence:

1. **Source staleness — the master caveat.** Every tag claim was verified against `companyfacts.zip` mtime 2026-08-07T14:27:51Z (newest filed date in the live book: 2026-08-06), 13 days stale at write time. The cloud rebuild fetches fresh: filings accepted 2026-08-07..now are invisible here. Most exposed: latest-FY constants (AMD FY2025 D&A, FIX FY2025, LLY FY2025 capex — AMD has already re-tagged two prior years once). All acceptance numbers are 2026-08-07-snapshot claims by construction.
2. **CH-7's full-corpus byte-identity is sampled, not censused:** 0 changes proven over 1,374 tickers (live 172 + seeded-1,200 + RC + CPT) = 24.5% of the corpus. The full 5,600 diff named in the acceptance test closes this and must actually be run. The wide-sample coverage aggregates (392/1200 st, 117/1200 lt) were not independently re-run (the decisive RC/CPT/MPWR content was).
3. **CH-6's exact output size is not schema-pinned:** two faithful implementations differ by ~17KB. The tolerance band replaces the byte gate; anyone wanting an exact gate must pin the encoding first.
4. **Area C corpus figures are a seeded sample** (n=600 of 5,600; 18.0% materially-uncaptured debt rate, $319.6bn) — not a census; do not quote as corpus fact. The F1-F4 vendor Total_Debt classification counts (56/23/21/7/3) were not independently re-measured (the vendor-inconsistency CONCLUSION is independently proven by the exact ROST-vs-AIT reproductions).
5. **GE, GEV, DOCU, CHE SBC series** are 100% Allocated-sourced with no cross-tag witness possible — plausible magnitudes, per-filer unverifiable from this source.
6. **"True D&A" for FIX, DT, GE is reconstructed from tags, not read from statements** (shipped == Depreciation line + a separate non-trivial amortization tag proves the shipped figure is PARTIAL; the true total is inferred). AMD and LIVN have exact internal reconciliations and are stronger. Anyone acting on the FIX numbers should read one cash-flow statement first.
7. **Author-only censuses not independently re-measured:** the depreciation-only wide scan's full 26-cell/9-name census (FIX/DT/ABNB spot-verified; GE/ARWR/CHEF/IESC/AMZN/NUTX percentages not re-run); OtherD&A corpus census (593 cells/131 names) and blanket-removal corpus direction; the Domestic+Foreign==Total 95.62% corpus stat; the D1 pretax corpus counts at raw-resolve level (the windowed ~1,877/~836 band is the deliverable gate).
8. **CH-3's corpus 0-lost gate was measured at field-resolve level**, without the accession vote applied — necessary but not fully sufficient; the real-rebuild full-file diff is the closing check.
9. **`cik_map.json` vintage (2026-06)** bounds every coverage number: tickers listed or renamed since resolve wrong or not at all. Not introduced by this package; declared.
10. **Not attempted at all:** IFRS securities coverage, FX policy, split-adjustment table, fiscal re-binning, any RS2 consumer wiring — each is a STOP in §4 with what it would take.