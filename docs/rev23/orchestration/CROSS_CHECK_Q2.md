# CROSS_CHECK_Q2: fresh blind review of the CROSS_CHECK_Q fixes to `qwen_c/value` (rs2 `review-2026-10/m3q`, `03797d7..5fe8e91`), 2026-10-30

**Scope.** The five fix commits (68c530e, fc85a11, d2a35dd, d323133, 5fe8e91), checked against CROSS_CHECK_Q.md, CROSS_CHECK_Q_RULINGS.md,
SPEC_m3q_valuation.md, WO_Q5.md, RR_Q3.md §7, PLAN_terminal_reinvestment.md (O1-O8) and the audited line (rs2 `1dcb3b2`, `wt-d2-facts`).
Every ruling was checked against the code and, where it could be, with a probe. Nothing in a builder report was taken as given.

**Suite (foreground, `-p no:cacheprovider`).** The eight `qwen_c/tests/test_value_*.py` files: **159 passed in 14.76 s**.

**Probes.** All scripts and their outputs are in this folder:
- `p_checks.py`, `p_checks2.py`, `p_falserefusal.py`: checks.
- `p_run.py`: run.value with the model faked.
- `p_desk.py`: desk, inputs, facts, coe and routing.
- `p_census.py` (writes `p_census.json` here), `p_delta_nci.py`, `p_vint_amort.py`: the 156 stored census companyfacts, offline.
- `p_prodpath.py`: RR_Q3 §7 recomputed by importing `q3_prod_path.value`; main() is not called, so nothing is written.

The census T is 2026-10-30T03:39:45Z, as in CROSS_CHECK_Q, and the E2 check uses T 2026-10-15T13:30Z. Read-only throughout:
- worktree `git status --ignored` was unchanged before and after;
- no file under `cache/` is newer than the last commit;
- there was no network call and no model call.

Severity is critical, major or minor. Each finding says whether it was verified by running code or read only.

---

## (a) The 34 first-review findings

| # | First-review finding | Status | Evidence |
|---|---|---|---|
| 1 | V3/V4 passed by a content-free reason | **PARTIAL** | A reason with no quote is now refused (`checks.py:192-193`). p_checks Q1.1: the 30% long-run margin is `valuation_incomplete`, "no quote". Q1.2: a half-year (two 10-Q sections of FY2025) is refused. Three gaps remain. First, the span counts cited items, not quoted ones, so a [Y]-only quote carries V3 (+63.1%, status ok; **N2**). Second, verified but irrelevant quotes from two fiscal years carry V3 (+63.1%, status ok). Ruling 1 records this as a stated limit. Third, in production V3 can never be met (**N1**) |
| 2 | The investment path goes around every margin check | **PARTIAL** | The path is now judged: it needs a reason, V3 applies to each year, its capex must be above the pooled ratio, and margin_source must agree (`checks.py:254, 274-278, 290-299`). p_checks Q2: `valuation_incomplete`. Its revenue growth is unbounded: 10 years at 15% with capex at pooled + 0.1 pt is status ok at **+129.6%**, and 30% is ok at **+552.5%** (**N7**). The O2c stamps `investment_state_*` are not ported (grep: absent) |
| 3 | A non-positive equity return is not refused | **FIXED** | `desk.py:147-150`. p_desk: RONIC_T 1.5% and 2.02% at δ 0.45 are refused `equity_ronic_not_positive`. Residual: at 2.03% (equity return about 3e-5) the equity value is **-431.11** and nothing annotates it (**N4**) |
| 4 | The explicit-year capex and D&A paths production runs are not the ones E1 validated | **PARTIAL** | Done:<ul><li>O7 modes 1 and 2: `forecast.py:96-103`.</li><li>ppe from the facts: `inputs.py:193-199`; 22 of 33 base-ready names get the vintages rule.</li><li>`investment_in_explicit_years` needs a capex_path: `checks.py:303-304`.</li><li>The production-path test is in place, and p_prodpath reproduces RR_Q3 §7 exactly (M1-M5 within 0.15% with cited capex).</li></ul>New defects: the capex path is unbounded (**N6**), and the vintages rule moves real values by -767% to +4% (**N8**). On the v1.3 firms, pooled and vintages D&A give identical values (M1-M5, A, D to 0.01%), so the E1 evidence cannot tell the two rules apart |
| 5 | The measured base is silently wrong on real filings | **PARTIAL** | p_census: THC (δ 0.384 on $13.17B), DAR (0.276), ACA and ILMN now see their debt. KSS, SAH and DLTR are refused `debt_without_interest`; HOG, NUTX and ZIM are refused `kd_out_of_band`. AMT's revenue is $10,644.6M and VICR's $452.7M (the total line). SWBI is refused `shares_scale_unverified`. Not built: ruling 5's revenue tag-switch level-break stamp. Residuals: δ uses gross debt and includes finance leases (**N10**); MTCH (#27) |
| 6 | Cash is counted twice | **FIXED** | `inputs.py:117-126, 131`. p_desk: +$100M of cash earning 4% adds exactly +10.00 per share. p_prodpath: with cash at 10% of revenue, every truth error stays within 0.1% |
| 7 | No roll-forward from the fiscal-year end to T | **FIXED** | `desk.py:151-153, 170`, `run.py:44`, and the test. Same convention as `1dcb3b2` `consensus_reference.py:799` |
| 8 | Stale snapshot and stale base year | **FIXED** | companyfacts is now a mutable prefix (`sec_store.py:32`). `base_year_not_latest_annual` (`inputs.py:92-93`) refuses CX, HAFN, UMC, RNW and BFH. None of the 156 names is refused because two dates are a few days apart |
| 9 | K_0 makes base-year anomalies permanent; V8 | **PARTIAL** | A tax anomaly can no longer enter: p_desk, FY0 rate 46%, gives X_0 10.976 and K_0 3.280, identical to the normal year. The V8 5-point rule is at `inputs.py:52-56`. Not done: annotating large or volatile non-operating items. The NCI sits in K_0 as a fixed dollar charge (**N9**) |
| 10 | Long-run margin bridged at R_5 | **FIXED** | `forecast.py:114`. p_desk: the year-15 X margin is 0.109706, equal to m_long |
| 11 | Bear and Bull are neither validated nor required to be supported | **PARTIAL** | Shape rules now apply to the merged scenarios (`checks.py:131-139`), and each replacement needs its own reason (`checks.py:263-266`). Probe Q11 is now incomplete. V3, V4 and V10 still run on Base only. A Bull long-run 60% and a Bear -40% resting only on an adjusted figure, each with a quoted reason, are status ok at -25.08 / 16.97 / 54.63. There is still no negative-value annotation (**N4**) |
| 12 | V7 and one-reason-per-input ignore what the reason says | **PARTIAL (V7 NOT FIXED)** | A keyword class per input (`checks.py:33-46`) and an exact-text duplicate rule (`checks.py:196-199`) exist. V7 (`checks.py:286-289`) is just the generic rule. The terminal_g class contains `declin|shrink`, so "Revenue declined … as the market shrinks" supports a positive g_T (**N3**) |
| 13 | The V10 regex refuses correct reasons and misses contradictions | **PARTIAL** | The first review's four cases now behave (`test_v10_direction`). New misses and one false positive remain, and the year-1/2 and scenario reasons are never scanned (**N5**) |
| 14 | V6 is a min-max position | **PARTIAL (core FIXED)** | Percentile at `checks.py:319-321`. p_checks: the 5/6/6/7/20% record at 11% is now 'peak'. Flat growth is still 'growing' (`checks.py:323`). task.py never asks for labels, so the `*_submitted` mismatch can never fire |
| 15 | V5 absent, ITGR fixture missing | **PARTIAL (stamped, as allowed)** | `ALWAYS_STAMPS`, `checks.py:32`. There is no ITGR fixture. No E2 rule is recorded for ITGR-type names, and ITGR is in the E2 panel |
| 16 | V1 post-compute checks are tautologies | **PARTIAL** | The levels flows are recomputed independently (`checks.py:352-369`), and a ΔNWC sign flip is caught. Not built:<ul><li>the Flow_0 identity (ruling 16);</li><li>a recompute of PV and TV (the equity check re-adds the desk's own sum);</li><li>the audited diagnostics.</li></ul>A defect in the fade (equity return ×1.5) passes at status ok, +3.5%. The V1 AssertionError escapes `check()` and `run.value` (**N11**) |
| 17 | Family routing defaults to the operating route | **FIXED** | `run.py:28-35`, and `--family` is required. p_desk: utility, mortgage_reit, pre_profit, shell, unknown, financial and family_not_built are all `family_not_routed` |
| 18 | Per-share units: ADS ratio, cover count, splits | **PARTIAL (known not done)** | `per_share_basis_unverified` is stamped for 20-F/40-F filers (`inputs.py:95-96`). Split detection and the cover count are not built, and **domestic filers get no stamp**, so a split after FY0 would go unseen. Measured today on the 23 routed base-ready names with a dei count: 20 sit at 0.84-1.02 of diluted shares, so no split. MA (0.135), VICR (0.594) and NXT (0.894) carry stale non-dimensional dei facts (2010, 2015 and 2024), because multi-class filers report the cover count per class. Ruling 18's planned rule ("cover vs diluted > 20%: refuse") would wrongly refuse MA and VICR unless it checks the dei fact's date |
| 19 | The amortization basis flips with tag availability | **FIXED (as ruled)** | `inputs.py:107-116`: one basis across the pool. 13 of 29 routed base-ready names fall back to X = NI: AMD, AVT, DVA, EAT, MTCH, MTRN, MU, NHC, RNG, RUSHB, STX, TWFG and VSXY. This departs from the approved O7 amendment ("else A_0 held, stamped `amortization_schedule_not_filed`"). The fallback also corrupts the vintages life (**N8**) |
| 20 | Leases (L1) not implemented | **FIXED (stamp)** | `inputs.py:94`, `leases_not_modeled` |
| 21 | RONIC_0 not on the documented basis | **PARTIAL** | Tangible capital, the 100% cap and the stamps are in place (`inputs.py:169-176`). Still one year, not the doctrine's blend of 8-year and 3-year medians. An absent goodwill, intangibles or short-term investments tag is read as 0 with no stamp (**N14**) |
| 22 | Plausible replies crash `check()` and `run.value` | **FIXED** | `checks.py:236-242`. p_checks Q22a-d: the partial normalized merges, and step_at_year with a null year, a string reason and -100% growth are all `invalid`, none raises. Residuals: **N11** (AssertionError) and **N13** (prepare) |
| 23 | result.json loses data across the repair turn | **FIXED** | `run.py:112-118`. p_run: both sequences keep every attempt's inputs, checks and values |
| 24 | A data no-call is recorded as the model's failure | **FIXED** | `inputs.py:100-102` refuses a missing base-year operating income before any call: GOLD, HOV, R and NEM. Residual: **N12** |
| 25 | Financial route clean surplus | **NOT FIXED (carried, not wired)** | `desk.py:218-258` is unchanged. Unreachable: `run.py` refuses `financial` |
| 26 | The prompt shows the price | **FIXED** | `task.py:20-26, 85`; the test pins the masked message. Stated limit: prices inside filing text are not masked |
| 27 | `LongTermDebt` double counts when it is the total | **PARTIAL** | `inputs.py:31, 69-72` now always treats `LongTermDebt` as the total. MTCH files `LongTermDebt` = `LongTermDebtNoncurrent` = $3,549.1M, so its $423.9M current portion is dropped (0.893 of the census debt) |
| 28 | Restatements resolved by tag before date | **FIXED** | `facts.py:172-184`. p_desk: FY2024 revenue is 90, from the 2026 filing |
| 29 | CoE point-in-time check skips undated legs | **FIXED** | `coe.py:45`: every result carries `coe_leg_undated:loading`. A closure dated after T is refused |
| 30 | A filed "thereafter" balance is dropped when A_5 = 0 | **FIXED** | `desk.py:62`. p_desk: the balance runs off at 0.5 a year |
| 31 | Annotations dropped from the audited line | **PARTIAL** | Done: `delta_pts_scale_suspect` (`checks.py:328-330`), and the `am.get` default is gone (`inputs.py:109`). Not ported: `partial_history_n_years` and `d2_long_run_value_negative`. The per-fact stamps never reach result.json (**N16**) |
| 32 | Prompt and memo | **PARTIAL** | Done: the memo drops refused reasons (`memo.py:38-39`), and the pin covers the whole user message. Still open:<ul><li>SYSTEM's SCOPE line ("Do not value the company") is not amended;</li><li>[Y] items have no effective time, though SYSTEM says every item states one;</li><li>`memo.py:24` prints a missing probability as 0.0%;</li><li>`run.py` writes no memo.</li></ul> |
| 33 | Test adequacy | **PARTIAL** | Added: the production-path test, pass cases for V3, V7 and V10, and the two rewritten tests. Missing: a V2 test, a V5/ITGR fixture, and a V9 test on non-monotone values. The only V3 pass case dates its annual section to FY-1 (`test_value_checks.py:32`), a layout no stored packet has. That is what hides **N1** |
| 34 | Cost of equity not relevered | **NOT FIXED (carried)** | `coe.py:51`. No stamp says so; measured δ reaches 0.478 (WNC) |

Known not done, checked against the brief:
- **Stamped:** ruling 15 (V5) and B12 (`leverage_bridge_unvalidated` on 31 of 33 base-ready names).
- **Refused, so not reachable:** ruling 25 (the financial route is not routed).
- **Neither stamped nor refused:**
  - ruling 18's split detection, for domestic filers;
  - ruling 34, relevering;
  - V2, which has no test.

---

## (b) New findings

### N1. Critical. V3 cannot be satisfied by any real packet. Every margin outside the filed record ends `valuation_incomplete`, whatever the evidence. *Verified.*
- **Where:**
  - `checks.py:172-176`: `fiscal_year_of` returns None for any period after the last filed fiscal-year end;
  - `checks.py:200`: the span is taken over those mapped years;
  - `run.py:50`: `fy_ends` holds filed revenue years only;
  - `packet.py:17-20`: the packet carries statements from the latest filing, sections from the latest annual report, and sections of the 10-Q *after* it.
- **Scenario:**
  - The items are laid out the way stored packets are: the annual section is FY0 (2025-12-31) and the 10-Q section is 2026-03-31.
  - A 17% long-run margin (record maximum 16%) is argued with verified quotes from both, so the two items are of different fiscal years as the prompt asks.
  - Result: `valuation_incomplete`, "V3 unsupported_premium" (p_checks).
- **Structural proof:** the 84 packets in `wt-m3n/cache/m3n/packets_v5`.
  - Every packet's annual sections come from one filing.
  - In 69 of them the 10-Q statements and sections are dated after the annual report, so they map to None.
  - The span is therefore at most 1 in every real packet.
- **Consequences:**
  - V3, the first-priority check (B8), refuses every Base normalized, long-run or investment-path margin outside [min, max], good or bad.
  - The O2c route can never carry a margin bought above the record.
  - E2's V3 rate would measure how often forecasts leave the record, not support quality.
  - The test that passes V3 (`test_value_checks.py:184-186`) works only because its fixture dates the annual section to FY-1.
- **Fix:**
  - Map a period after the last fiscal-year end to the next fiscal year (last end + 12 months, with a 52/53-week tolerance), or carry the prior annual report in the packet (a versioned packet change).
  - Add a test on a stored-packet layout.
  - Land it together with N2.

### N2. Major. V3's span counts the items cited, not the items quoted. *Verified (test layout); latent in production only because of N1.*
- **Where:** `checks.py:188` and `checks.py:200`. Under `contract.py:457-459`, a quote need only be found in one of the cited items.
- **Scenario:**
  - A 30% long-run margin (maximum 16%) cites [Y2025-12-31, A1 (annual, 2024), Q1 (10-Q, 2025)] and quotes only "operating margin 16.0%", from the code-built [Y] item.
  - Result: **status ok, +63.1%**. That defeats ruling 1's "[Y] items cannot carry V3".
  - Citing A2 and Q1 but quoting only A2 is ok as well (+6.5%).
- **Fix:** the span is the fiscal years of FILED_KINDS items in which at least one verified quote was found.

### N3. Major. V7 accepts the fault it was built to catch. *Verified.*
- **Where:**
  - `checks.py:40`: the terminal_g keyword class includes `declin|shrink|mature`;
  - `checks.py:286-289`: V7 asks only for a supported terminal_g reason, which `JUDGMENT` requires anyway.
- **Scenario:**
  - Base growth is -5% and -4%, normalized -2%, and g_T +2.5%.
  - The terminal_g reason is "Revenue declined in the last filed year as the market shrinks.", quoting [Y2025].
  - Result: **status ok**, labelled `shrinking`.
- **Fix:** SPEC V7 as written. For a shrinking Base, g_T > 0 needs a verified quote that states a return to growth: a growth term in the quoted text and no decline term. Otherwise the input is unsupported.

### N4. Major. Scenario replacements bypass V3, V4 and V10, and values at or below zero are not annotated. *Verified.*
- **Where:** the V3 and V10 loops cover Base only (`checks.py:274-285`), and so does V4 (`checks.py:255-261`). No `d2_long_run_value_negative`.
- **Scenario:**
  - Bull: long-run 60% (record maximum 16%) and op margin 45-50%.
  - Bear: op margin -40% citing only an adjusted-EBITDA release, and long-run -30%.
  - Each replacement has its own quoted reason.
  - Result: **status ok**, values **-25.08 / 16.97 / 54.63**.
- Ruling 11 says scenarios are "validated with the Base rules".
- Also: RONIC_T 2.03% at δ 0.45 gives an equity value of -431.11 with no annotation (p_desk).
- **Fix:**
  - Run V3, V4 and V10 on the merged scenario inputs.
  - Annotate any scenario value at or below zero, and an equity RONIC_T below g_T.

### N5. Major. V10 never reads the year-1/2 margin reasons or any scenario reason, misses common phrasings, and refuses reasons about another period. *Verified.*
- **Where:** `checks.py:280-285` (the scan scope) and `checks.py:49-51` (`_REF`).
- **Scenario:**
  - **Not scanned:**
    - an op_margin of 0.158 with the reason "set below the median" (median 0.1556) is ok;
    - a Bull long-run of 0.158 "below the median" is ok.
  - **Missed, with the input above the reference each time:**
    - "below its seven-year median";
    - "below the five year median";
    - "below the historical average";
    - "lower than the 2024 margin".
  - **False positive:** a normalized margin at the median, with the reason "The 2024 margin was above the median …; the normalized margin returns to …", is refused.
- **Fix:**
  - Scan every margin reason: years 1-2, the scenarios and the investment path.
  - Accept any N-year or number-word span, average or mean, and a dated year.
  - Bind the direction phrase to the input's own subject, or annotate instead of refusing when the subject is another period.

### N6. Major. The O7 `capex_path` is an unbounded lever, and the direction of "investment" is never checked. *Verified.*
- **Where:**
  - `checks.py:90-97`: any ratio in [0, 1) is accepted;
  - `checks.py:254`: one supported reason is enough;
  - `checks.py:303-304`: `investment_in_explicit_years` accepts any capex path;
  - `forecast.py:96-103`.
- **Scenario:**
  - `capex_path` [0, 0, 0, 0, 0] with a quoted capex reason is **status ok at +24.2%**. The zero year-5 capex also enters the fade through w_5.
  - `margin_source` `investment_in_explicit_years` with capex falling to 0 by year 5 is **ok at +18.3%**.
  - The investment path has a "capex above pooled" rule (`checks.py:296-299`); the capex path has nothing comparable.
- **Fix:**
  - A capex path below the filed record's minimum capex/revenue needs V3-type support.
  - `investment_in_explicit_years` needs capex above the pooled ratio.
  - Annotate `capex_path_below_record`.

### N7. Major. Growth and terminal growth have no outside anchor, so the value is unbounded at status ok. *Verified.*
- **Where:**
  - `checks.py:68-69` and `checks.py:86-87`: growth only above -1, g_T only below r;
  - `checks.py:104-106`: the investment path's revenue_growth only above -1;
  - `desk.py:143-144`.
- **Scenario,** with the clean reasons, r 0.09 and RONIC_T 0.15:
  - g_T 0.085 gives 77.07 (+354%);
  - g_T 0.089 gives **338.08 (+1,893%)**, status ok;
  - g_T at r - 0.2 pt with RONIC_T unlimited gives 373.13;
  - an investment path of 10 years at 30% growth gives 110.71 (+552%), ok.
- [V0] prints MRI's long-run growth anchor, and no check reads it. SPEC §1 rule 1 says code checks the inputs against outside anchors.
- **Fix:**
  - Annotate a g_T above the anchor, the terminal value's share of the value, and growth above the record's maximum.
  - The coordinator rules on a bound; SPEC §4 has none.

### N8. Major. The vintages D&A rule from batch D, run on real filed PP&E, moves values by -767% to +4% against pooled, and the model is shown only the pooled ratio. *Verified.*
- **Where:**
  - `inputs.py:193-199`: ppe is built in the amortization fallback too, and there D&A_org still holds the acquired-intangible amortization (`inputs.py:195`);
  - `desk.py:81-112`: L = prior gross PP&E / D&A_org, clamped to [3, 60];
  - `task.py:77`: [V0] says "depreciation … (pooled)".
- **Data:** p_delta_nci and p_vint_amort, with a neutral forecast (the record median margin, 3% growth). 22 of the 33 base-ready names get vintages.

  | Name | Life L | Neutral value, vintages against pooled | Note |
  |---|---|---|---|
  | QUAD | 42 | **-2.83 against +0.42 per share** | the sign flips |
  | RNG | 3 (2.65 before the clamp) | **-60.5%** | $135.4M of amortization stays in D&A_org; L is 7 without it. Its year-5 vintage D&A is 0.13 × pooled |
  | VSXY | | -27.4% | |
  | EAT | | -12.9% | |
  | DVA | | -9.3% | |
  | ALNT | | -9.0% | |
  | STX | 37 | -7.4% | |
  | ILMN | | -7.3% | |
  | NHC | 29 | -7.1% | |
  | DELL | | -5.2% | |
  | MATX | | +4.3% | |

- **Mechanism:**
  - The model sets its GAAP margins from the record, which carries the record's depreciation.
  - When the code's D&A falls and the margin does not rise with it, each flow loses (1 - δ)·ΔD&A, and w_5 carries the loss into the fade.
- **Why no truth test sees it:** on the v1.3 firms, pooled and vintages give the same value (p_prodpath).
- **Fix:**
  - In the fallback, take the filed amortization out of D&A_org before computing L, or do not build ppe.
  - Annotate an L outside a registered band, and a year-5 vintage/pooled ratio outside [0.8, 1.25].
  - Show the desk's D&A path in [V0] (a versioned prompt).
  - The coordinator rules on vintages against pooled for real data, and adds a truth firm whose D&A decays.

### N9. Major. The NCI is a fixed dollar charge inside K_0, grossed up at the parent's tax rate, and all consolidated cash goes to the parent. *Verified.*
- **Where:**
  - `inputs.py:127-136`: pt_ex = PT - C·bill - NCI/(1 - τ), and K_0 = OI_0 - pt_ex;
  - `inputs.py:213-214`: the bridge holds K_0 flat;
  - `inputs.py:121-126`: all cash is added;
  - `facts.py:30`: the NCI tag ladder has one us-gaap tag.
- **Data:** p_delta_nci. Year-5 X with the NCI held fixed, against the NCI growing with operating income, at 3% growth:

  | Name | NCI share of consolidated earnings | Year-5 X overstated |
  |---|---|---|
  | TWFG (Up-C; K_0 = 16.6 × X_0) | 80.7% | **+227.5%** |
  | DVA | 30.8% | +5.9% |
  | VSXY | 14.8% | +5.7% |
  | DAR (an E2 name) | 10.8% | +3.2% |
  | THC | 40.6% | +3.0% |

- **TWFG's gross-up:** it is untaxed at the parent, yet grossed up at the parent's 7.4% rate, so X_0 is 2.1M against 4.6M.
- **Ladder gap:** NCI filed under any other tag (for example IFRS `ProfitLossAttributableToNoncontrollingInterests`) is read as 0 and stamped `nci_not_filed`, the same stamp as no NCI at all.
- **Fix:**
  - Carry the NCI as a share of earnings, outside K_0.
  - Stamp `nci_material` above a registered share, and refuse Up-C or dominant NCI until it is modelled.
  - Extend the NCI ladder.

### N10. Major (the rule deviates; the measured effect is small). δ is measured on gross debt, not O5's net debt, and finance leases are inside it. *Verified.*
- **Where:**
  - `inputs.py:179` against the approved rule: PLAN_terminal_reinvestment.md §2 row 10, "δ = measured net debt / (net debt + market capitalization) …, 0 for net cash";
  - the audited `wt-d2-facts/tools/d2_facts.py:294`: "non-lease debt … less cash and short-term investments, floored at 0";
  - `facts.py:62-66`: the ladder puts `DebtAndCapitalLeaseObligations` and `LongTermDebtAndCapitalLeaseObligations*` first.
- **Data:**
  - TASK, an E2 name: δ 0.245 against 0.038 net.
  - RUSHB 0.041 against 0.010; VSXY 0.136 against 0.068; MTCH 0.260 against 0.200.
  - AMD, FTNT, NHC, ILMN and TWFG hold net cash and still get δ > 0.
  - The neutral value moves by up to **+3.6%** (TASK).
  - Finance leases are counted as debt for MU (2,387 of 5,179M), EAT (98 of 448M), THC, DVA, DAR and ACA.
- v1 had the same gross rule; CROSS_CHECK_Q missed it.
- **Fix:** δ = max(0, non-lease debt - cash - short-term investments) / (that + market cap), with finance-lease tags dropped or netted.

### N11. Minor. V1: the AssertionError escapes, and the fade and terminal are not recomputed. *Verified.*
- **Where:** `checks.py:241` does not catch AssertionError; `checks.py:352-369` checks the levels leg only.
- **Scenario:**
  - A d2_flow defect makes `run.value` raise; only `raw/attempt_1.json` is left (p_run).
  - A fade defect passes at status ok (+3.5%).
- **Fix:**
  - Catch the error, mark the run `invalid: engine_defect` and write result.json.
  - Recompute PV and TV from the flows, and add the Flow_0 identity.

### N12. Minor. A stub over 800 days is refused only after two model calls. *Verified.*
- **Where:** `desk.py:151-153`; `run.py:44` does not check it.
- **Scenario:** p_run: two calls, then `valuation_incomplete` with `{}` values, counted as callable.
- **Fix:** refuse it in `prepare`.

### N13. Minor. A zero-revenue year in the pool crashes `inputs.base` with ZeroDivisionError. *Verified.*
- **Where:** `inputs.py:205` (the record ratios) and the pool ratios. `run.prepare` catches DeskRefusal only, so `run.value` dies before result.json.
- **Fix:** refuse a year with revenue at or below zero by name.

### N14. Minor. Silent zeros: non-negotiable 4. *Verified.*
- **Where:**
  - absent goodwill, intangibles or short-term investments are read as 0 in tangible capital (`inputs.py:170`);
  - `if eps:` treats a filed EPS of 0.0 as missing (`inputs.py:186`);
  - `(nc or 0.0) + (cur or 0.0)` (`inputs.py:75`).
- **Scenario:** with the goodwill tag absent, RONIC_0 goes from 0.2181 to 0.2030 with no stamp. 8 of 33 base-ready names file neither intangibles tag the ladder reads: ATI, AVT, MU, RUSHB, STX, VICR, VSXY and ENLT. VSXY's trade names, for example, are not subtracted.
- **Fix:** stamp each absent component; give a 0.0 EPS its own stamp.

### N15. Minor. The 5% share reconciliation refuses correct share counts. *Verified.*
- **Where:** `inputs.py:186-189`.
- **Scenario:**
  - An if-converted diluter is refused: CHEF, NI per diluted share 1.573 against a filed EPS of 1.68; the probe reproduces it.
  - EPS below about $0.10 is refused on cent rounding.
- **Fix:**
  - Allow NI/shares ≤ EPS for if-converted diluters.
  - Allow a rounding band of 0.005/EPS.
  - Reconcile with the cover count.

### N16. Minor. Per-fact stamps never reach result.json, and the revenue tag-switch stamp is not built. *Verified.*
- **Where:** `run.py:89` stores the base but not the facts' own stamps.
- **Lost stamps:**
  - `acceptance_by_filed_date` on every DELL concept, so DELL's point-in-time basis is invisible;
  - `profitloss_basis_unverified` for THC, QUAD and MTCH;
  - `revenue_largest_of_tags` for DVA and UGI.
- **Fix:** summarize the per-fact stamps into the base stamps.

### N17. Minor. Two hair-triggers refuse good outputs. *Verified.*
- **V11 has no tolerance:** a long-run margin 1 bp above the year-5 margin, with margin_source `record`, is refused (`checks.py:300-302`).
- **The keyword classes refuse correct reasons in other words:** a terminal_ronic reason "New stores pay back their cost in three years." is refused "does not address terminal_ronic".
- **Fix:** add a tolerance to V11; widen the classes, or annotate instead of refusing.

### Note for the coordinator (major for E2 planning, not a code defect). Most of the E2 panel is a data no-call. *Verified at T 2026-10-15 on the stored companyfacts.*

| Name | Outcome before any model call |
|---|---|
| MSGE | `tax_unavailable` (rates -1.76, 0.429, 0.381; capex filed as `PaymentsForProceedsFromProductiveAssets`, outside the ladder) |
| PACS | `input_missing` (D&A) |
| DAC | `facts_stale` (capex last filed for 2012) |
| BUD | `shares_unavailable` |
| GOLD | `bridge_unavailable` |
| KOF | `facts_stale` |
| VSNT | `shares_unavailable` |
| MCY | not routed |
| TASK, DAR | callable |
| LPG, ITGR | not in the store |

What this leaves for E2:
- E2 can exercise at most 4 of 12 names.
- WO_Q5's canonical fault names cannot be run: MSGE for V3, DAC for V10, VSNT for V7.
- SPEC E2's seam list (DAR, MCY, MSGE, DAC) reduces to DAR.

---

## (c) Verdict

**REJECTED for E2.** The fixes close the first review's no-quote bypass, the cash double count, the roll-forward, the equity-return sign flip, the staleness gap, the routing and the crashes, and they are verified. But E2's purpose is to report the V-rates, and four of them would measure the checks' defects, not the model:
- V3 refuses every premium or discount on a real packet (N1), and is bypassable once that is fixed (N2);
- V7 accepts a decline reason as support for positive growth (N3);
- scenarios skip V3, V4 and V10 (N4);
- V10 does not read the year-1/2 or scenario reasons (N5).

The values have unchecked levers: a capex holiday (N6), and growth or g_T up to 20 times the value at status ok (N7). E2 is one consumed run that may not be repeated after viewing, so these must be fixed before it, not after.

**APPROVED WITH CONDITIONS for the GPU smoke alone** (one real turn, mechanics only):
- **S1.** Run it on a consumed name: TASK or DAR, which are callable and on the regression panel. Use no E3-eligible name.
- **S2.** Its statuses and values are not evidence for E2 or E3, and are labelled so in the record.
- **S3.** The smoke result is read for mechanics only: parse rate, repair-turn behavior, prompt length, result.json integrity.

| # | Fix | Blocking | Owner |
|---|---|---|---|
| N1, N2, #33 | Map post-FY0 periods to the next fiscal year (or carry the prior annual report in the packet); span from quoted items only; a test on a stored-packet layout | **blocking for E2** | builder (packet option: coordinator) |
| N3 | V7: a quoted return-to-growth, else g_T ≤ 0 | **blocking for E2** | builder |
| N4, #11 | V3/V4/V10 on scenario replacements; annotate values ≤ 0 and an equity RONIC_T below g_T | **blocking for E2** | builder |
| N5, #13 | V10 over every margin reason (years 1-2, scenarios, path); phrase coverage; subject binding or annotation | **blocking for E2** (scope); carriable to E3 (phrasing) | builder |
| N6 | capex_path record bound or annotation; `investment_in_explicit_years` requires capex above pooled | **blocking for E2** (annotation at least) | builder |
| N7 | Annotate g_T above the MRI anchor, terminal-value share, growth above the record; the bound itself | **blocking for E2** (annotations); bound before E3 | builder; coordinator (SPEC ruling) |
| N10 | δ net of cash and short-term investments, non-lease (O5 as approved) | **blocking for E2** (one line; E2 name TASK +3.6%) | builder |
| Note | E2 plan: record the expected no-calls (≤ 4 of 12 callable) and decide whether E2 is still worth the run as specified; an E2 rule for ITGR (#15) | **blocking for E2** | coordinator |
| N8 | Amortization out of D&A_org for L in the fallback; L and year-5 ratio annotations; D&A path in [V0]; ruling on vintages vs pooled; a decaying-D&A truth firm | stamp before E2; **blocking before E3** | builder; coordinator |
| N9 | NCI outside K_0 as a share of earnings; `nci_material` stamp; refuse Up-C; NCI ladder | stamp before E2 (DAR); **blocking before E3** | builder |
| #1 residual | Quoted evidence need not reach the premium level (stated limit, ruling 1) | ruling before E3 | coordinator |
| #18, #34 | Stamp `split_detection_not_built` and `coe_not_relevered` on every result | carriable (stamp before E2) | builder |
| N11, N12, N13 | Catch V1 AssertionError into `invalid` with result.json; recompute PV/TV; Flow_0; stub > 800 and revenue ≤ 0 refused in `prepare` | carriable | builder |
| N14, N15, N16, N17, #14, #16, #21, #27, #31, #32 | Silent zeros stamped; share reconciliation bands; per-fact stamps in result.json; tag-switch stamp; V11 tolerance and keyword classes; flat-growth label; diagnostics; RONIC_0 blend; MTCH LongTermDebt test; partial history; prompt SCOPE and [Y] effective time; memo | carriable | builder |
| #25, #34 | Financial route identity; relevering | carried (as ruled) | builder |

After the blocking items: re-run this folder's probes, which are written so that each one turns from "ok" into a refusal or annotation once its item is fixed. Run a fresh verification of those fixes before E2.
