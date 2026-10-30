# CROSS_CHECK_Q3c: blind check of the CROSS_CHECK_Q3b fixes (rs2 `review-2026-10/m3q`, `2e00b86..84ad2df`), 2026-10-31

## Verdict: APPROVE, with conditions (APPROVED WITH CONDITIONS)

- **Approved:** a GPU smoke of `valuation_inputs_financial` on the 9 ready names. Nothing in this commit makes such a run unsafe or wrong in its plumbing.
- **Not approved:** keeping any value, on either route, as E2 or E3 evidence until Q3c-1 to Q3c-4 below are fixed. This is the same bar Q3b set for N3.
- **What holds:**
  - N1, N4, N6, N7 and N9 are fixed.
  - N2 is fixed in effect: every ALL release variant is annotated.
  - Desk v4 agrees with v3 to 6.9e-14 on driver `book`. Driver `revenue` is bitwise identical.
  - b10, re-run on all 9 names: 0 false engine defects on 306 replies.
  - Injected errors of finding 3's class are all caught by V1.
- **What does not hold:** N3 is only partly fixed. A reply can still reach an extreme value at status `ok` with no B13 annotation, on both routes:
  - **operating route:** growth at the record maximum with median margins gives DAR **+16,447%** (only the V2 seam annotation) and the suite company +56% (no annotation at all) (Q3c-1);
  - **terminal growth:** g_T at r − 0.0201, supported by any two-fiscal-year quote, gives HRTG +105%, RNR +91% and DAR +77% with no annotation (Q3c-2);
  - **bull scenario:** a bull at the record maximum ROE gives ALL **+3,090%** with no annotation (Q3c-3).
  - Meanwhile the new P/B annotation fires on the *neutral* reply for 6 of the 9 names (Q3c-4).
- **The coordinator's statements that need correcting:**
  - "The claim in the B13 ruling now holds." It does not on the operating route, for bear and bull, or for terminal growth.
  - "The reviewer's probes were re-run to the end." `rerun_b4_levers.out` and `rerun_b10_v1_real.out` stop after 2 of the 9 names (Q3c-9).
  - The N5 comment's "0 or par": only the zero case is handled.

**Scope.** `git diff 2e00b86 84ad2df` (10 files), read against:
- CROSS_CHECK_Q3, CROSS_CHECK_Q3b and the rulings' last section;
- the Q3b probes;
- `run.py`, `forecast.py` and `forecast_fin.py` as they stand.

The commit message and the rulings were not taken as given.

**Suite (foreground, once).** `qwen_c/tests -q -p no:cacheprovider`, bytecode writing off: **625 passed in 208.54 s**.

**Probes.** Scripts and outputs are in `C:\Users\riper\AppData\Local\Temp\claude\C--Users-riper-stocks\69b4116b-d43f-4a78-867f-8f8db1d8ff91\scratchpad\q3c\`. `old2e0\` is `git archive 2e00b86 qwen_c`.

| Probe | What it measures |
|---|---|
| `c1_desk_v1` | desk v4 against v3 (4,000 random inputs); b10 on all 9 names; ROE 0 and below 0; V1's detection thresholds; injected engine errors |
| `c2_levers_fin` | b4's E0/E1/E3 on all 9 names; release variants R2–R4; P2 (below p75); P3 (g_T lever with a span); P4 (an extreme bull) |
| `c3_levers_op` | B13 on the operating route: the suite company and DAR (real, cached) |
| `c4_preferred`, `c4b_old_vs_new` | Preferred instants of the 20 census financials; BFH's tags; synthetic variants at 2e00b86 and at 84ad2df |
| `c5_chain` | `_year_chain` edge cases; equity strays in the census; the N4 boundary |
| `c6_record_items` | `[Y]` for the two new preferred bases |
| `c7_coverage` | The code half of `_prepare_financial` on the 20 census financials |

**Assumptions:**
- r 0.10 (financial) and 0.09 (operating), g_anchor 0.035, bill rate 0.04; the MRI chain was not called.
- T is 2026-10-30T14:19:07Z.
- The span probes (P3, O4) add two generic filed annual sections dated in the last two fiscal years, standing in for 10-K text a model could quote.

**Read-only throughout:**
- HEAD stayed `84ad2df`;
- `git status --short --ignored` was identical before and after;
- no `__pycache__` was written, and no cache file is newer than the start;
- no network, model or GPU call.

---

## Per-finding status

| # | Status | Evidence |
|---|---|---|
| N1 | **Fixed** | <ul><li>`desk.py:261` `bv = dict(R)`; `desk.py:264` TV = (E_{N+1} − g_T R_{N+1})/(r − g_T). This is identical to the old form whenever ROE_T > 0, which `shape_fin` and the desk enforce.</li><li>v4 against v3: driver `book` agrees to 6.93e-14 on 2,000 inputs; driver `revenue` is bitwise identical on 2,000 (c1 §1).</li><li>b10 on all 9 names: 0 AssertionErrors or invalid replies in 306 full-retention replies, against 17 of 96 before (c1 §2).</li><li>A typed ROE of 0 or −0.05 in base or in bear is valued, never `invalid` (c1 §3).</li><li>New defect in the tolerance: Q3c-5.</li></ul> |
| N2 | **Fixed in effect; the annotation itself is narrow** | <ul><li>`book_release_cumulative` fires on b4 E3: ALL +263% and UFCS +23% (c2).</li><li>Three variants evade it:<ul><li>R2, release just under 25%: ALL +161%;</li><li>R3, the release moved into the fade (step at year 5, F 30): ALL +215%;</li><li>R4, ROE above r in years 1–5 and the long run below r: ALL +315%.</li></ul></li><li>All three are still annotated, by the median P/B annotation.</li><li>The one unannotated residual is OPY R3, +6.9%, which is immaterial.</li><li>The coordinator's ruling on a lower bound net of OCI and buybacks (Q3b N2, second row) is not recorded.</li></ul> |
| N3 | **Partly fixed** | <ul><li>Fixed: b4 E1 (the peak perpetuity) is annotated on all 9 names (`implied_pb_above…` and `roe_at_record_peak`). The memo prints the implied P/B and the TV share.</li><li>Not fixed:<ul><li>the operating analogue Q3b specified (an implied multiple against a median perpetuity) was not built (Q3c-1);</li><li>the reference moves with the reply's own g_T (Q3c-2);</li><li>the annotations cover base only (Q3c-3);</li><li>the P/B annotation fires on neutral replies (Q3c-4).</li></ul></li></ul> |
| N4 | **Fixed** | <ul><li>WTM is ready: ROE record −0.0705 to 0.2468, `NetIncomeLoss` from 2021; the unverified ProfitLoss rows are 2018–2020, all unused.</li><li>A stamp on `ends[1]` still refuses (c5).</li></ul> |
| N5 | **Partly fixed; four regressions or gaps** | <ul><li>Fixed: zero carrying value with a liquidation preference (`test_N5`). BFH is refused, which is correct: it files no preferred dividends and no income to common for FY2025, only common dividends (c4 §2).</li><li>Not fixed or new: Q3c-6 (a crash) and Q3c-7 (par value; a late-tagged preferred; a redeemed preferred; `[Y]` on the liquidation basis).</li></ul> |
| N6 | **Fixed** | checks v5, inputs v7, facts v4, memo v3, desk v4, prompt fin v3; the pin was re-hashed (`test_value_fin.py:225`). |
| N7 | **Fixed** | <ul><li>`checks.py:430` binds at min(record minimum, 0).</li><li>The prompt v3 wording ("shrinking faster than in the record's worst year") matches it, including for a positive minimum.</li></ul> |
| N8 | **Fixed in `base_financial`; residual Q3c-8** | <ul><li>`_year_chain` behaves on strays, on 52/53-week years, on a moved year end and on gaps. A moved or truncated chain is refused, never valued (c5).</li><li>No ready name has a stray.</li></ul> |
| N9 | **Fixed** | <ul><li>Every injected error was caught on ALL, HRTG, CTBI and UFCS (c1 §5): g5 taken as g4 (value effects from 0.027% to 5.3%), the book path shifted one year, and the ROE fade one year early.</li><li>Remaining limit (one line): `_path`, F, g_T and `m_long` still come from `assemble` and `build_path`, so a `build_path` defect is not covered.</li></ul> |
| N10 | **Not fixed as stated** | The b4 and b10 re-runs stopped after ACIC and ALL (Q3c-9). c1 §2 and c2 re-run both on all 9 names. |

Coverage: 9 of 20 confirmed. The code half of `_prepare_financial` passes for ACIC, ALL, CTBI, HRTG, OPY, RNR, UFCS, UVE and WTM. AII passes `base_financial` but is refused by `record_bar` (`history_short`) (c7).

---

## New findings

### Q3c-1. Major (N3 residual, operating route). `margin_at_record_peak` sees only margins. Growth at the record maximum, faded over 30 years, still reaches extreme values at status `ok` with no B13 annotation.

**Where:**
- `checks.py:689-691`: the only operating B13 annotation, on the normalized and long-run margins;
- `checks.py:707-714`: V3g binds only *above* the record's maximum revenue growth;
- `checks.py:716-727`: no implied multiple or TV share on the operating route.

**Scenario (c3).** Growth just under the record maximum in years 1–5, F 30, terminal RONIC unlimited, g_T 3.5%, with `[Y]`-quoted reasons:

| Name and variant | Result |
|---|---|
| DAR, margins at the record **median** | `ok`, **+16,447%** (10,040 against 60.68), annotation only `V2 flow_seam_out_of_band` |
| DAR, margins at the maximum in years 1–4 (`hold_then_linear` 5), normalized and long-run just under p75 | `ok`, **+19,374%**, V2 seam only |
| Suite company, the same two | `ok`, **+55.8%** and **+59.1%**, no annotation |

- DAR's record maximum revenue growth is 0.3777, a single year. This is the operating twin of finding 2.
- b9's own scenario (margins at the maximum) *is* annotated, so the fix matches the probe rather than the lever.

**Fix:**
- Build Q3b's item: the implied terminal multiple, or the value, against a perpetuity at the record-median margin and g_anchor, annotated.
- Annotate growth held above the record's p75 for F > 10 (`growth_at_record_peak`).
- The coordinator corrects "the claim in the B13 ruling now holds".

### Q3c-2. Major (both routes). Terminal growth above the anchor, once span-supported, is invisible: the P/B reference is computed at the reply's own g_T.

**Where:**
- `checks.py:520-522`: `pb_ref = (median − g_T)/(r − g_T)` with the reply's g_T, so the threshold rises with the lever;
- `checks.py:496-498` and `702-704`: V3g accepts any two-fiscal-year span (the stated limit: the quotes are not checked to reach the premium);
- `checks.py:499-500` and `705-706`: `terminal_spread_thin` fires only below 2 points.

**Scenario (c2 P3, c3 O4).** Everything at the median and g_T = r − 0.0201, with a supported `terminal_g` reason quoting two filed sections of two fiscal years. Every case is status `ok` with **no annotation**:

| Route and name | Base value against the neutral reply |
|---|---|
| Financial: HRTG | **+104.9%** |
| Financial: RNR | +90.6% |
| Financial: UVE | +76.3% |
| Financial: ACIC | +64.0% |
| Financial: WTM | +51.9% |
| Financial: CTBI | +39.8% |
| Operating: suite company | +71.7% (**+151%** with RONIC unlimited) |
| Operating: DAR | +77.3% (+134.6% with RONIC unlimited) |

**Fix:**
- Compute `pb_ref` at min(g_T, g_anchor).
- Annotate `terminal_g_above_anchor` whenever g_T > g_anchor, supported or not, on both routes. This is an annotation, never a gate.

### Q3c-3. Major for E2/E3 (both routes). The B13 annotations are computed for base only.

**Where:**
- `checks.py:517-529` (`if name == "base"`): the implied P/B and `roe_at_record_peak`;
- `checks.py:689-691`: uses base's `m_n` and `m_l`.

**Scenario (c2 P4).** Base neutral; the bull replaces normalized (baseline max), `long_run_roe` (record max) and `fade_years` 30, all inside the record, so no span is needed. The result is status `ok` with no B13 annotation:

| Name | Bull against base |
|---|---|
| ALL | **807.63 against 25.31 (+3,090%)** |
| OPY | +259% |
| UFCS | +138% |

The memo prints the bull value and its probability.

**Fix:** compute the TV share, the implied P/B, `roe_at_record_peak` and `margin_at_record_peak` per scenario, naming the scenario.

### Q3c-4. Minor (but it decides whether B13's "annotate" carries information at E3). The median-perpetuity P/B annotation fires on the neutral reply.

**Data:**
- **Neutral reply (c2 E0):** ROE at the median, growth 5%, F 10, g_T 3%. The annotation fires on 6 of the 9 names:

  | Name | P/B | Reference |
  |---|---|---|
  | ACIC | 1.83 | 1.73 |
  | CTBI | 1.39 | 1.35 |
  | HRTG | 3.92 | 3.56 |
  | RNR | 2.80 | 2.58 |
  | UVE | 2.18 | 2.04 |
  | WTM | 1.58 | 1.51 |

- **The suite's own clean reply:** 1.05 against 1.05 (`q3b\rerun_p3_fixed.out`).
- **A flat record (p75 = median):** `roe_at_record_peak` fires on a median reply (the same file, low-ROE bank).
- **Consequence for those six names:** P2 carries the same single annotation as the neutral reply. P2 is years 1–4 at the record maximum ROE, normalized and long-run just under p75, F 30: CTBI +5%, HRTG +49%, RNR +61%, UVE +77%, WTM +87%, ACIC +246%.

Under the old maximum reference the annotation never fired (Q3b N3). It now fires almost always.

**Fix (coordinator rules the margin):**
- Fire above a registered margin over the reference, measured on neutral replies, or reference a neutral path (median ROE, the record's median retained growth, g_anchor).
- Fire `roe_at_record_peak` only when p75 > median.

### Q3c-5. Minor (check bypass, introduced by N1). The book-scaled tolerance also applies to the value-per-share leg of V1.

**Where:** `checks.py:563-566` define `same()` with `scale = max(book)` in dollars; `checks.py:575` applies it to a per-share figure.

**Measured (c1 §4).** The tolerance is 1e-9 × the largest book on the horizon. Smallest per-share error detected, on a grid from 1e-12 to 5:

| Name and reply | Tolerance | Value per share | Smallest error detected |
|---|---|---|---|
| ALL, neutral | **≥ $34.77/share** | $25.31 | **500%** (200% passes) |
| ACIC, growth 0.3 | ≥ $0.91/share | $146.00 | 100% |
| OPY, growth 0.3 | ≥ $2.81/share | −$258.43 | 200% |
| UFCS, growth 0.3 | ≥ $2.69/share | −$202.06 | 200% |
| RNR, CTBI, HRTG, OPY, UVE, neutral | — | — | 5% (1% passes) |

- For example, a `forecast_fin.value` that dropped the roll-forward (+8.2% at 303 stub days) would pass on ALL.
- Flows, the TV and the equity value are still checked to 1e-9–1e-4.

**Fix:** keep `scale` for flows, the TV and the equity value. Compare value per share at the relative 1e-9 tolerance (or scale divided by shares).

### Q3c-6. Minor (a crash on the commit's own new base). `[Y]` raises KeyError for a preferred first issued inside the record.

**Where:**
- `forecast_fin.py:34-35` reads `pref[end]` for every record year once the stamp is `preferred_subtracted_at_carrying_value`;
- `run.py:69` calls `record_items` inside `prepare`;
- `run.py:108` catches only `DeskRefusal`.

**Scenario (c6).** The suite's own `test_b4_preferred_first_issued_in_the_record` base raises `KeyError '2021-12-31'`, so `run.value()` raises instead of writing a `no_call`. No ready name hits it today.

**Fix:**
- Print from the base's own common-equity and preferred series (`pref.get(end, 0.0)`).
- Add `record_items` to the test.

### Q3c-7. Minor (latent silent defaults and regressions in N5's preferred logic; no census name is affected today)

**Where:** `inputs.py:293-295`, `318-333`; `forecast_fin.py:34`. Results from c4 §3 and c4b:

- **(a) Par value.** A par-valued `PreferredStockValue` ($750) with a $10M liquidation preference is taken at par: R1 127.999M instead of 118M, stamped `preferred_subtracted_at_carrying_value`. The code comment claims "0 or par".
- **(b) A preferred tagged late.** Its dividends are filed for 2021–25 and its balance only for 2024–25, so it existed earlier. It is read as a new issue: valued with an artificial **−3.45% release year** (`book_growth_min` −0.0345), stamped `preferred_first_filed`. At 2e00b86 it was refused (`preferred_series_incomplete`); this commit turned a refusal into a wrong record.
- **(c) A redeemed preferred.** A preferred redeemed in 2023 and filed as 0 afterwards is now **refused**, because filed zeros are dropped at line 293. At 2e00b86 it was valued.
- **(d) `[Y]` on the liquidation basis.** For a liquidation-preference base, `[Y]` omits the preferred and common equity. The model is shown total book (128M) beside an ROE on common (12.3/112).
- **(e) Shares with no value.** Preferred shares outstanding with neither a value nor a liquidation tag still get no stamp: UVE's 10,000 shares, immaterial.

**Fix:**
- Keep filed zeros.
- When a liquidation preference is filed, take max(carry, liquidation), or prefer the APIC-inclusive tag, with a stamp.
- Refuse when preferred dividends, or an income-to-common gap, are filed for any year before `first`.
- Print common equity in `[Y]` whenever the base has a preferred.
- Stamp shares filed with no value.

### Q3c-8. Minor (latent span inflation). `run.py:72` passes every equity instant as `fy_ends`, not N8's chain.

A stray instant splits a fiscal year in two for V3's span: with a 2022-06-30 stray, quotes dated 2022-03-31 and 2022-09-30 count as two fiscal years (c5). HG and PRCH have strays; both are refused today.

**Fix:** take `fy_ends` from `inputs._year_chain`.

### Q3c-9. Process (N10 recurrence)

`rerun_b4_levers.out` and `rerun_b10_v1_real.out` end in BFH's traceback after 2 of the 9 names, yet the rulings say the probes were "re-run to the end". N1's "0 assertions" was therefore shown on ACIC and ALL only. c1 §2 now shows it on all 9.

**Fix:** probes catch refusals per name, and a re-run is cited only when it completes.

**Cosmetic (one line each):**
- The `book_release_*` annotations repeat once per scenario.
- The prompt v3's INPUTS line still says "net income over book equity", while `[V0]` says income to common over opening common equity.
- `memo.py:41` prints `tv_share` None as 0.0% (non-negotiable 4).
- `at_liq` is computed over preferred years outside the record.
- `MEMO_VERSION` is not in `result["versions"]`.
- `_recompute_fin` does not check that the flow lists have the same length; the equity comparison covers it.

---

## The questions

**Q1. Is each of N1–N9 fixed?** N1, N4, N6, N7 and N9 are fixed. The variants tried:

| # | Variants tried |
|---|---|
| N1 | full retention at 17 growth levels × 2 normalized growths × 9 names; ROE 0 and −0.05 in base and in bear |
| N4 | the stamp moved to `ends[1]` |
| N7 | a positive record minimum |
| N9 | three injected errors |

The other four:
- **N2:** fixed in effect (R2–R4 are caught by the P/B annotation).
- **N3:** partly fixed (Q3c-1 to Q3c-4).
- **N5:** partly fixed (Q3c-6, Q3c-7).
- **N8:** fixed where it is used (Q3c-8).

**Q2. New defects.**

| Item | Finding |
|---|---|
| desk v4 | Correct. `bv = R`, and the TV is algebraically the old one for ROE_T > 0. Driver `revenue` is bitwise unchanged. |
| recompute tolerance | Not too loose for flows, TV or equity: every injected engine error was caught, down to a 0.027% value effect. Too loose for value per share (Q3c-5). |
| `_year_chain` | Sound. Its failure modes are refusals, never wrong values. The chain is not propagated to `run.py` (Q3c-8). |
| preferred logic | Q3c-6 and Q3c-7. |
| new annotations | Q3c-1 to Q3c-4. |
| prompt `fin.v3` | Consistent with the code (N7) and pinned; one stale clause (cosmetic). |

**Q3. Can a reply still reach an extreme value at `ok` with no annotation?** Yes, on both routes:

| Route | Lever | Result |
|---|---|---|
| Operating | growth lever (Q3c-1) | DAR +16,447% (V2 seam only); suite +56% (none) |
| Both | g_T lever (Q3c-2) | HRTG +105%; suite +151% |
| Financial | bull (Q3c-3) | ALL +3,090% |

On the financial base, every lever that needs no span is now annotated, but for 6 of the 9 names only by an annotation the neutral reply also carries (Q3c-4).

---

## Fix list

| # | Fix | Blocking | Owner |
|---|---|---|---|
| Q3c-1 | Operating implied-multiple (or value) annotation against a median perpetuity at g_anchor; `growth_at_record_peak`; correct the B13 claim | **blocking before any value is kept as E2/E3 evidence** (not the smoke) | builder, coordinator |
| Q3c-2 | `pb_ref` at min(g_T, g_anchor); `terminal_g_above_anchor` annotation, both routes | **blocking before E2/E3 evidence** | builder |
| Q3c-3 | B13 annotations per scenario | **blocking before E2/E3 evidence** | builder |
| Q3c-4 | Registered margin, or a neutral-path reference, for the P/B annotation; `roe_at_record_peak` only when p75 > median | **blocking before E2/E3 evidence** (the margin is a ruling) | coordinator, builder |
| Q3c-5 | V1 per-share leg at a relative tolerance | carriable (next commit) | builder |
| Q3c-6 | `record_items` for a preferred first issued inside the record; test | carriable (before E3 or any new formation) | builder |
| Q3c-7 | Preferred: keep zeros; par against liquidation; refuse a late-tagged preferred; `[Y]` common line; stamp shares with no value | carriable (before E3) | builder |
| Q3c-8 | `fy_ends` from the chain | carriable | builder |
| Q3c-9 | Probes catch refusals; cite only completed re-runs; correct the N10 row | carriable (process) | coordinator |
| N2 (Q3b) | Rule on the lower bound net of OCI and buybacks | ruling before E3 | coordinator |
| — | Cosmetic items | carriable | builder |

After the four blocking items, re-run `c2_levers_fin` and `c3_levers_op` and expect:
- every P1–P4, O2–O4 and E1 case annotated;
- E0 neutral not annotated;
- `c1_desk_v1` §4 per-share threshold at or below 1e-8.
