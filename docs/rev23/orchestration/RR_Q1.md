# RR_Q1: read-only inventory for 3Q, valuation engine and Qwen reasoning repair (2026-10-29)

Brief: `WO_Q1.md`. This report describes; it proposes no fix. Nothing was edited, run, fetched or committed; the only file written is this one.
No sealed or untouched holdout result or label was opened (they are listed in section 5 with where each is recorded). `.secrets.json`, `.env*`,
`m3n\n5\runs*`, `m3n\n6\` and every `cache\*\runs\` were not opened. I did not run any test or code, so every claim below is from reading files and from
`git -C ... log/show/grep`.

Path shorthand:
- `REC` = `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\rev23\`.
- `P25` = `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\pilot_r25\`.
- `R26` = `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-r26-int\`, the worktree of rs2 branch `review-2026-10/r26-int` at `c255803` (HEAD checked). Every
  `file:line` marked R26 is read from that worktree.
- The live rs2 branch is `review-2026-09/phase-4` (head `5b9ccf5`, restored to `e82a08b` plus the SEC user-agent fix; `RR_L2_partial_rs2_live_branch.md`). It has no
  bridge, no revision-26 stages and no D2: its desk has `unbundled_dcf` and `execute_financial_model` only (`git grep` of
  `phase-4:tools/audit_202608/financial_model_tool.py`: lines 237, 1625, no `bridge`). The revision-26 work is not on the live branch.

---

## 1. Revision 26's recorded failure modes

### What the bar was and what it returned
- Registered bar: at least 83% of callable names coherent, 0 incoherent, 0 loops, median spread at most 20%, direction unanimity at least 83%, pull at most 0.15,
  0 memo-verdict mismatches (`P25\runs_p4r26\{3,4}\score.json` key `rule`; `REC\SPEC_rev26_staged_analyst.md:163-198`).
- Panel: 12 names, 9 callable and 3 data no-calls (PACS `base_cf_unavailable`, LPG `bridge_unavailable`, KOF `shares_unavailable`;
  `score.json` `per_name.*.no_call_reasons`). Counting the 3 names skipped by Amendment 1 (OGE, HNRG, PTCT, negative base cash flow), 9 of 15 drawn names were callable
  (`score.json` `coverage`; `SPEC_rev26_staged_analyst.md:213-225`).
- Result: iteration 3 = 1/9 coherent (MSGE only), iteration 4 = 0/9. In both, 0 incoherent, loops 0, median spread 16.8% and 16.6%, direction unanimity 8/9,
  0 memo-verdict mismatches. All four items that failed are the one: "at least 83% coherent" (`score.json` `items[3]`; summary in
  `REC\handoff_2026-10-23\05_RESULTS_ALL_MEASUREMENTS.md:33-73`). So no reader found anything *wrong* ("incoherent"). Every name that missed was
  "questionable": something may be wrong, or cannot be checked from the dossier, and it matters (`P25\READER_RUBRIC.md:12-15`).
- The rubric's criterion 4 was amended on 2026-10-22 (cross-check 25) to stop asking for a fact that speaks for perpetuity, so these counts are under the amended
  rubric (`READER_RUBRIC.md:33-34`; the old one is `READER_RUBRIC_v1.md`). Iteration 2 (pack 26, before the amendment) was 0/7 coherent with one incoherent (ITGR: memo invented an
  "MRI business with an installed-base service annuity"; `05_RESULTS_ALL_MEASUREMENTS.md:23-31`).
- Freeze: 2026-10-23, pack revision 28 at rs2 `1484ea2` (+ post-freeze diagnostics `c255803`), "paper-only, low confidence" (`SPEC_rev26_staged_analyst.md:268-279`,
  `handoff_2026-10-23\02_STATE_OF_PLAY_AND_DECISION_PENDING.md:25-27`).

### Failure classes, counts per criterion (final ratings after adjudication, computed from `score.json` `readers.*.criteria.*.final`)
| Class (rubric criterion) | Iter 3 (n=9) | Iter 4 (n=9) | Example case ids |
|---|---|---|---|
| C4: normalized state / long-run margin premium or discount argued from short-span or absent evidence (the dominant class) | 8 (all but MSGE) | 8 (all but TASK) | MSGE it4: 14.0% normalized margin above the record maximum 13.5%, premium argued from operating leverage with no fact of matching span. BUD it4: +0.8 pt premium from one adjusted year and an H1-2026 27.2% margin "no dossier fact states". TASK it4: reader A, +1 pt rests on one peak year and a half-year plus an AI-productivity claim with no fact. VSNT it4: departure below the last year argued from one guidance year. ITGR it4: FY2024 12.1%, "declining amortization", "52% top-3 customers" in no dossier fact. DAC it4: pre-peak FY2019-20 margins not in the dossier. (`P25\runs_p4r26\4\readers\reader_A.json`, `reader_B.json`) |
| C1: a cited fact is the wrong entity, basis, period, withdrawn, or marked unusable | 5 (BUD, MCY, ITGR, DAR, VSNT) | 7 (DAC, BUD, GOLD, MCY, ITGR, DAR, VSNT) | ITGR: cites G17, outlook the dossier's G11 says was withdrawn. GOLD: year-1 revenue reset rests on F70, a third-party question the dossier calls unverified. DAR: near-term 25%/24% margins cite F3, a company-adjusted combined EBITDA including DGD share. MCY: "FY2025 combined ratio 96.3%" is a net-income dollar figure (F38) misread. VSNT: H14 is about the NBC network, not Versant's USGA rights. DAC: F50 registered as backlog but the quote gives an addition to it |
| C2: forecast inputs contradict the memorandum's stated economics or labels | 6 (TASK, DAC, GOLD, ITGR, DAR, VSNT) | 6 (MSGE, TASK, GOLD, MCY, DAR, VSNT) | MSGE it4 (adjudicated): memo says the 14.0% margin is "supported by a filed record" whose maximum is 13.5%. TASK it4: memo justifies mid-cycle normalization by headwinds while the path rises to near the peak. VSNT it4: memo says margins are depressed by separation items that fade, input normalizes 2 points below the last year. DAR it4: years 1-2 hold 25%/24% peak margins incl. one-offs the memo says are not structural. MCY it4: "mid-cycle" label with normalized margin above 7 of 8 filed years. DAC it3 (adjudicated): normalization_reason says "below the median" while the input is median + 0.5 |
| C3: unsupported copy of a revealed consensus margin | 0 | 0 | none. Anchoring canary pull 0.000 on 4 names (`05_RESULTS_ALL_MEASUREMENTS.md:53,72`) |

- Where adjudication changed a rating, the reasons are in `runs_p4r26\{3,4}\adjudication.json` (iteration 3: DAC and ITGR on C2; iteration 4: 8 items).
- Cross-iteration reading: the iteration-4 charter fix was "a real defect, removed on its merits; it was not the coherence problem"
  (`05_RESULTS_ALL_MEASUREMENTS.md:72-73`; `SPEC_rev26_staged_analyst.md:281-306`). Iteration 4 moved some names between questionable and coherent but not the count of failing
  names; MSGE lost "coherent" (14.0% > 13.5% record max).
- Records' own summary of the failure mode: "unjustified long-run margin persistence and memos contradicting forecast inputs" (`REC\..\STATUS.md`, Phase 4 section, 'Failure mode').

### Other recorded failure modes (not the coherence count)
| Class | Count / examples | Source |
|---|---|---|
| Valuations far from price | Iteration-3 Base/price: MSGE 0.49, ITGR 0.63, BUD 1.14, MCY 2.30, TASK 2.31, DAC 3.09, DAR 3.67, GOLD 3.80, VSNT 4.25; seven of nine "undervalued", five by 2-5x | `05_...:75-77` |
| Desk defect, kappa / year-6 cash-flow jump | `kappa = base_cf/(rev_L*x_L)` scales years 1-5 only; the long run starts from `e5 = R5*m5` without kappa. kappa per name: DAR 4.53, MCY 1.75, MSGE 1.31, BUD 1.19, ITGR 1.06, GOLD 1.02, VSNT 0.97, TASK 0.94, DAC 0.64. Year-5 to year-6 flow: DAR 4.99 to 0.85, MCY 1.34 to 0.54, MSGE 0.18 to 0.064, DAC 0.43 to 0.54. kappa=1: DAR -48%, MCY -16%, DAC +11% | `05_...:83-94`; R26 `financial_model_tool.py:2111-2112, 584, 597-606` |
| Tax clip | DAR raw -15.3% clipped to 0 (-18%/-21% if floored at 21%/25%); MSGE raw 38.1% clipped to 35%. Post-freeze `c255803` replaces the clip with the multi-year median or "unavailable" | `05_...:90-91`; R26 `r26_stages.py:1057-1096` |
| Decliner terminal growth | VSNT: positive terminal growth while Base revenue shrinks every year (-3% / -6.5% at terminal growth 0 / -2%). `c255803` only annotates it | `05_...:92`; R26 `r26_stages.py:1371-1380` |
| Forecasts, not desk, explain the remaining gaps | After the desk fixes: DAC 3.1x, GOLD 3.1x, VSNT 4.2x, TASK 2.1x, MCY 1.6x. DAR's 21% year-1 margin vs a filed 4.5%; VSNT 20%+ margins while shrinking | `05_...:93-95` |
| Spread above 20% | it3: GOLD 87.0%, DAR 44.2%, MCY 26.7%, ITGR 21.9%; it4: GOLD 87.8%, DAR 38.9%, VSNT 32.0%, MCY 20.0% | `score.json` `per_name.*.spread` |
| Non-actionable reasons on the callable 9 | `contract_fields_unfilled` 9/9 (conviction, moat, re-entry tranches have no code source); `price_beyond_every_input_reach` DAR and VSNT; `path_dominated_crux` it3 TASK and DAC, it4 DAC; `memo_number_mismatch` it3 DAR, it4 TASK and ITGR (the two it4 ones were a verifier rounding false positive, fixed in `c255803`); actionable names: 0 | `score.json` `actionability`; `05_...:79-81` |
| Memo cites a fact id not in the dossier | it3 TASK (G42b, L15, L17), BUD; it4 BUD (unknown ids 4 to 2) | `05_...:37-53,66-67` |
| Stage 1 research quality | About half of registered facts fail verification (mostly `metric_not_near_quote`, often tripping on the company's own name: "gold", "integer", "inbev"); KOF stage 1 ended INCOMPLETE (context overflow at turn 20) and became a `shares_unavailable` no-call | `05_...:3-21` |
| Not failures, for the record | Loops 0, pull 0.000, no anchoring, unanimous direction 8/9 | `05_...:53,72`; `02_...:25` |

Gap in the records (stated, not filled): the readers were two blind agents per iteration; their quotes are in `handoff_artifacts_2026-10-23\readers_it{2,3,4}_{A,B}\reader_*.json`.
I used the notes only as examples; I did not re-score anything.

---

## 2. D2 year-6+ reinvestment / fade convention

### What was approved (operator, 2026-10-18; `REC\PLAN_terminal_reinvestment.md:216-245`; memory `terminal-reinvestment-d2.md`)
- **O1** D2 replaces design D; the rho_sust residual is diagnostic only.
- **O2** the year-5 capex wedge `w_5` fades linearly over the analyst's own F (not min(F,5)); **O2c** the levels leg may continue through a *cited* investment-state path of H years beyond year 5
  (then N = 5 + max(F,H)); D&A by the vintages rule (gross/net PP&E) with a pooled fallback; tau*A runs off to exhaustion (memory; `PLAN:186-195`).
- **O3** financials take a retained-equity route from year 1: `Flow_t = E_t(1 - g_{t+1}/ROE_t)`, no capex/D&A/working capital.
- **O5** one desk-wide *measured* leverage delta at market weights. **O6** equity REITs go through D2 with delta; mortgage REITs (NREF, CIM) take the financial route.
- **O7** explicit years 1-5 on levels: `Flow_t = E_t - (1-delta)(capex_t - D&A_t + dNWC_t)`, pooled filed intensities unless the analyst cites a capex path; E_0 <= 0 stays refused.
- **O8** the sustaining charge `s` is removed from production entirely (fade, year-5 boundary, terminal). The F&D-vs-DD&A (`fd_vs_dda_gap`) and REIT recurring-capex-vs-D&A gaps are diagnostics plus a reason
  request only. Depleters C and C2 *fail by default* (+7.37%, +4.53%) and pass only on a cited path (`PLAN:232-239`).
- Port split: (a) desk formula, (b) pack facts from filings including the lease field, (c) analyst capex/H input, TASK and tool schema, PACK_REVISION (`PLAN` Step 3 text; memory).

### What is built, and where
| Part | Commits | Branch | State |
|---|---|---|---|
| (a) desk formula | `1dcb3b2` "Desk: design D2 behind optional d2 long-run members" (from `8e2cb8a`); `test_d2_desk.py` 55 pass; reproduces `reference_d2.py` to 4e-16; legacy-equivalent d2 reproduces today's value to 1e-6 | rs2 `review-2026-10/d2-port` (pushed to origin) | audited 10-18 (`PLAN:260-272`). With `d2` absent the desk is unchanged. Code: `tools/consensus_reference.py:474-680` (`d2_flow`, `d2_value` 531, `d2_value_financial` 602), `financial_model_tool.py:756-1000+` (`_d2_prepare` 800, `_d2_diagnostics` 918, `_d2_dcf` 986) at `1dcb3b2` |
| (b) pack facts | `286409a` (facts d2 / d2_provenance / d2_unavailable, L3 `r_tc_after_lease_interest`, `FACTS_VERSION` 12, `d2_enabled` switch), `84ae50c` (coverage: kd order, capex_d2, debt_d2_total), `031ab88` (da_d2 / revenue_d2) | rs2 `review-2026-10/d2-facts` (pushed) | `d2_enabled` is set by no arm (`capability_test.py:1828`, `financial_model_tool.py:2723-2725` at d2-facts). Screener fields: `6901f78de44`, `5b30e90761d`, `0e9ae7d6b26`, `65328f973ed`, `1c06210ef63` on stock-screener `review-2026-10/d2-fields`, **not in origin/main** (merge order is binding: the rs2 `REVIEWED_HISTORY_KEYS` change must be live before the screener branch publishes, `PLAN:279-281`) |
| (c) analyst input, TASK/schema, PACK_REVISION, solver on D2 | not built | none | Carried requirements: price-implied solver must run D2 too; TASK/tool schema; versioned PACK_REVISION (`PLAN:296-297`) |

- **None of D2 is on `r26-int`, `r26-harness`, `m3n`, `m3m-qwen` or the live `phase-4` branch** (`git merge-base --is-ancestor 1dcb3b2 / 031ab88` is false for all of them). The frozen revision-26 desk is the 25.2 path with the kappa defect; revision 26 lists D2 as out of scope
  (`SPEC_rev26_staged_analyst.md:200-205`; `capability_test.py:284` on r26-int: "D2 stays off").
- Why D2 matters for the kappa defect: D2 values years 1-5 from filed *levels* (earnings less reinvestment) with positivity on earnings, instead of scaling by `base_cf`, so it removes the base_cf scaling; the 25.2 desk keeps it
  (`CROSS_CHECK_24_iteration1_design_questions.md:40-51`).

### Decided vs undecided
- **Decided:** everything under O1-O8/O2c/O7 above, including that the wedge fades over F, that `s` is gone, that terminal value is `E_{N+1}(1 - g_T/RONIC_T)/(r - g_T)`.
- **Undecided (the operator's ruling is on record as still pending):** the **fade growth convention**: during the fade (years 6 to N) the margin moves from `m_5` to the long-run margin, and the reinvestment charge `g_{t+1}/RONIC_t` is charged on **revenue growth** as built
  (`consensus_reference.py:579-581` at `1dcb3b2`: `xt = rt*mt; f = xt*(1 - g_at(t+1)/ron) + tau*amort`) versus **earnings growth** (capital tied to profit). ChatGPT (major): margin 8%->12% over the fade makes the revenue
  convention 20.5% above the earnings convention; 12%->8% gives -17.8%; a flat margin gives 0. "Neither convention is right in general." Proposed resolution not done: synthetic firms whose margin change is economically specified (from existing capital vs from
  new investment), truth-tested, then a ruling (`PLAN:463-466`). Pending-status confirmations: `handoff_2026-10-23\02_...:51-53`, `07_...:31-35`, `SPEC_factor_led_v2.md:78`, `STATUS.md` Phase 4 'Desk' bullet ("D2 fade reinvestment convention remains undecided and D2 is not enabled").
  Until then `cash_scaling_out_of_band` (kappa outside 0.67-1.5) marks verdicts non-actionable (R26 `r26_stages.py:1356-1369, 2048-2050`).
- **Also still open, accepted as required before D2 is enabled** (`PLAN:467-480`): tax shield after year N (PV of the remaining finite shield); an unmeasured tau becomes "unavailable", not a stamped 21%; unverified fallback rungs become unavailable; the materiality rule (name usable only if every endpoint of the input interval gives the same verdict category; midpoint stamped `materiality_bounded`; **the threshold is the operator's**, deferred
  until recovery work is done, `PLAN:380-381`); per-route ROE_T semantics; an end-to-end `family_route_unresolved` test; coverage-bias report; the equity-conversion constant-leverage sensitivity; non-USD convenience-translation names quarantined (FX fix owner `stock-screener/scripts/fx_normalize.py`, `PLAN:373-376`); legacy L2/L3 lease fixes deferred to part (c) (`PLAN:286-291`).
- Cross-check 21 (ChatGPT/Gemini) approvals referenced by the plan are in `CROSS_CHECK_21_d2_coverage_short_form.md`; I did not need to open it for this report.

---

## 3. Valuation code map (rs2 `r26-int` @ `c255803` unless stated; "code" = deterministic Python, "model" = Qwen text or typed input)

Overall split in revision 26: the *model* supplies the forecast inputs (stage 2 `submit_forecast` JSON) and the memo text; *code* turns them into value, picks the discount rate, tax, base cash flow, shares, labels and the
memo's numbers (`r26_forecast.py:1-30` docstring: "Nothing of the DCF is re-implemented here").

| Item | Where (file:function, lines) | Code or model |
|---|---|---|
| **Revenue growth** years 1-2 | model: `scenario.near_term.rev_growth` (validated by `r26_forecast.validate_scenario:117`, `validate_forecast:185`: structure and finiteness only, "a margin is never bounded") | model |
| Growth years 3-5, normalized year N (3..5), transition | `r26_forecast.build_path:266`, `_blend:248`; model picks `normalized.year`, `normalized.rev_growth`, `transition` (linear / step_at_year / hold_then_linear) | model inputs, code interpolation |
| Growth years 6 to 5+F | desk: `consensus_reference.long_run_value:376-440`: `g_t = g5 + (gT - g5)(t-5)/F`; F = model's `fade_years`; `g5 = R5/R4 - 1` (bridge path) | model F and terminal_g, code arithmetic |
| Growth label | `r26_late.derive_growth_trajectory:96`, applied by `r26_stages.derive_labels:1329` (the model's label is kept as `label_submitted`) | code (since pack 27) |
| **Margins** years 1-2 | model: `near_term.op_margin` (filed operating-margin basis) | model |
| Normalized margin | `r26_forecast.normalized_margin:226` = `bar[baseline] + delta_pts*0.01`; the model chooses `baseline` (min/p25/median/p75/max/last) and `delta_pts`, code adds | model inputs, code sum |
| Operating margin to X-basis (net-income-before-amortization margin) | `r26_forecast.bridge_to_x:355`, `_x_of_op:334`, `bridge_margin:385`, `invert_bridge:397`: `X_t = (op_t - K_0/R_t)(1 - tau)`, `K_0 = OI_0 - X_0/(1 - tau)` held flat in dollars (stamp `bridge_calibrated_to_base_year`) | code |
| Long-run margin | model `long_run_margin_op` -> bridged at year-5 levels in `r26_forecast._scenario_spec:428`; desk reaches it at the end of the fade via `margin_ratio = long_run_margin / m_5` (`financial_model_tool.py:597-605`, `long_run_value` margin factor) | model input, code arithmetic |
| **Reinvestment** years 1-5 | desk `unbundled_dcf`, bridge branch: working capital deducted = `wc_intensity*(R_t - R_{t-1})` (`financial_model_tool.py:584-591`); owner earnings `oe_t = kappa*R_t*m_t` (`_bridge_build:2102-2112`); capex and D&A enter only through `base_cf` = TTM net income + D&A - capex (`capability_test.py:3082`, `_attributed_owner_earnings:1788`) | code; kappa defect here |
| Reinvestment years 6 to N and terminal | `long_run_value` (`consensus_reference.py:376`): `CF_t = E_t(1 - g_{t+1}/RONIC_t)`, `RONIC_t = ronic_at(RONIC_0, RONIC_T, frac)` (`:336`), `TV = E_{N+1}(1 - g_T/RONIC_T)/(r - g_T)`; `RONIC_0` = measured `r_tc` of the facts, resolved by `long_run_returns:354`; `RONIC_T` = model's `terminal_ronic` (must be > 0; used as stated, no floor at r since rev 24 step 2d); the value is floored at 0 (`long_run_floor`) | model RONIC_T, F, terminal_g; code arithmetic |
| Cost of capital | code: `coe_anchor = max(rf, terminal-g anchor) + adj. sector loading x closure ERP` (`capability_test.py:2506-2517`; as-of variant `:2270-2281`); forced onto every sample by `r26_stages.code_owned_inputs:1317-1326` (model's rate kept as `discount_rate_submitted`); desk refuses `wacc <= terminal_g` (`financial_model_tool.py:536`) and the equity frame (rate type cost of equity; `:490-520`) | code (since pack 27) |
| Tax | `r26_stages.bridge_facts_from_row:1065-1096`: measured `tax_provision/pretax_income`; outside [0, 0.35] -> multi-year median over up to 8 years if at least 3 measured (stamp `tax_rate_multi_year_median`), else unavailable (`tax_rate_unmeasured`, name is `bridge_unavailable`). Owner earnings are after-tax by construction (net income). Separate population-range tax with a 21% statutory fallback exists for cohort records only (`population_ranges.py:284, 293-306`) | code |
| **Dilution / share count / SBC** | SBC: `default_desk_params:1110-1116` sets `sbc_treatment = "deducted_in_cf"` (stock comp counted once in net income; double deduction refused, `financial_model_tool.py:520-533`); shares: the pack's `shares_default` (`capability_test.py:1689 _shares_default_state`, `shares_dilution_factor` facts `:2774-2850`); no positive share count -> data no-call `shares_unavailable` (`r26_stages.valuation_inputs:1186-1193`). No forward dilution path is modeled. | code |
| Net debt / cash | equity frame: net debt must be 0 (`financial_model_tool.py:490`), excess cash added per share at face (`:539, 636`); the bridge from enterprise-style flows is not used on this path (base_cf is levered) | code |
| Terminal growth | model `terminal_g`; checked below the discount rate (`r26_forecast.validate_forecast:185-225`); shrinking-business annotation `r26_stages.shrinking_terminal_flag:1371` (does not gate) | model + code check |
| Value per share | `unbundled_dcf` PV sum `:634-636`; `value_forecast:469` feeds the desk (`execute_financial_model`, desk schema 25.2) the revenue-growth and X-margin lists; `aggregate:590` takes the median of K=3 blind samples; `alt_paths:539` reports an alternative path after fact expiry, never substituted | code |
| Scenario probabilities, Bear/Bull | model `prob` per scenario (sum 1 +- 0.01 checked, `validate_forecast`); desk blends | model + code check |
| Memo numbers | stage 4 table is code (`r26_late.table_rows`, rendered `render_bridge_table`); memo text is model; `verify_memo:861` compares them | code table, model prose |
| Contract numbers (Kelly, skew, tranches, moat, conviction) | `contract_fill.fill:359`; `UNFILLED_NUMERIC` conviction/moat/tranches have no code source (`r26_late.py:923`) | code, three unfilled |

Not deterministic code and not checked by anything: the **content** of every margin premium, the durability thesis (4 statements, <= 40 words, structure-validated only, `r26_late.validate_durability:78`), and the three labels
other than the growth label (`margin_persistence`, `cycle_position`) which stay model-typed, with only form checks.

Live-branch note: the live desk (`phase-4`) uses the older `explicit_growth` + `base_cf` growth-rate path (`unbundled_dcf:237`), not the revenue-times-margin bridge.

---

## 4. Business models: financials, cyclicals, capital-intensive, REITs

What exists (revision-26 branch; none of this is on the live branch):
- **Family classification** by SIC code and balance-sheet tests: `population_ranges.sic_family:380` and `family_for:397` (R26 `tools/population_ranges.py`):
  `financial` = SIC 6000-6411 (exceptions 6282 and 6411 valued as operating), or insurance reserves >= 10% of assets (`INSURANCE_RESERVE_SHARE`, `:377`); `commodity` = mining, oil and gas,
  refining, commodity chemicals, steel, shipping, pulp and paper (`_COMMODITY:373`); **`family_not_built`** = REITs and real estate (SIC 6500-6599, 6798), blank-check shells, holding companies, regulated utilities and pipelines
  (SIC 4900-4949) (`_NOT_BUILT:368`), plus pre-profit names (operating income <= 0 in at least 3 of the last 4 years, `:375-376, 421-425`). The lending-book test is not evaluated (stamped `lending_book_test_not_evaluated`, so non-SIC-financial lenders stay operating).
  Book census of the 160 nominees: operating 81, commodity 29, financial 20, family not built 30 (15 real estate, 10 pre-profit, 5 utilities) (`REC\REPORT_census_1a_terminal.md:21`).
- **How the family is used by revision 26**: `r26_stages.resolve_family:1119-1137` maps `financial` -> the *identity bridge* (margins are already on the X basis, no conversion, `r26_forecast._bridge_inputs:313`, `_x_of_op:334`; an unresolved family is a `family_unresolved` no-call); `operating` and `commodity` -> the operating bridge;
  **`family_not_built` is valued with the ordinary operating formula** stamped `family_not_built_valued_as_operating` (`r26_stages.valuation_inputs:1140-1180`). That means REITs, utilities, shells and pre-profit names get the common equation today.
  The code-only engine's "not built" status (out of scope: commodity, REIT, utility, pre-profit; `REC\SPEC_engine_v2.md:26`) is a different system. Financials there use ROTE (`SPEC_engine_v2.md:44`).
- **Population ranges by family** feed the plausibility gate: tables by family (operating / commodity / financial); a financial company's margin and ROIC range, and `family_not_built`, return "no measured population for this family" (`population_ranges.py:40-45, NO_POPULATION`); the gate's cohort bounds `gate_bounds:962`, `family_unmeasured:980`.
- **Cyclicals**: a cyclicality score (`population_ranges.cyclicality_score:124`; components margin volatility, reversal frequency, autocorrelation, revenue cyclicality, `CYC_COMPONENTS:71`) sets the margin-normalization target and retention (`_margin_target:692`, `_normalization_line:754`); the model also states a `cycle_position` label checked by K2 only in the revision-25 arms (`bridge_checks.check_k2:250`). In the blind readings, cyclical names (MCY, GOLD, DAR, TASK) were exactly where "mid-cycle" labels, peak margins and short-span premiums drew questionable ratings (section 1).
- **Capital-intensive / depleting producers**: `depth_gates.producer_class:34` + reason 16 `depleting_producer_unsupported` makes any verdict on a depleting-producer industry (from the screener's `stocks.csv`) non-actionable "until a producer design passes its own pre-registered test" (`depth_gates.py:197-200, 293-305`, docstring "Reasons 16"). Capex treadmill, asset-life and D&A are *not* modeled in the revision-26 desk (it uses `base_cf` = NI + D&A - capex as one number). D2 is the designed repair (levels leg, vintages D&A, O2c cited investment path, `fd_vs_dda_gap` and `reit_recurring_capex_vs_da` diagnostics) and it is unmerged and not enabled (section 2).
- **Financials in D2**: financial route `d2_value_financial` (`consensus_reference.py:602` at `1dcb3b2`) on retained equity: built in part (a), not enabled; classification findings for the route (V is operating despite SIC 6099; STT is financial despite SIC 6282) and the rule "a balance-sheet test confirms it" are in `REPORT_census_1a_terminal.md:45-55`.
- **REITs**: today `family_not_built`, valued as operating in the AI desk; D2 plan O6 routes equity REITs through D2 with delta and mortgage REITs (NREF, CIM) to the financial route (`PLAN:230`, `REPORT_census_1a_terminal.md:30`).
- **Growth firms / pre-profit**: pre-profit is `family_not_built`; a non-positive base cash flow is a data no-call before any model call (OGE, HNRG, PTCT skipped; `r26_stages.py:1148-1156`).
- No handling anywhere for: bank-specific capital/ROE constraints beyond the route design, REIT FFO/AFFO, utility rate-base growth (D2 synthetic firm G only), insurer float, or industry-specific cyclical normalization beyond the cyclicality score. The deferred list includes "financial companies on an equity route; a proper terminal state for decliners; D2 validation of DAC and MCY" (`07_OPEN_ITEMS_AND_NEXT_STEPS.md:55`).

---

## 5. Evaluation panels

### Consumed (scored and viewed; do not reuse as fresh)
| Panel | Names / window | Where recorded |
|---|---|---|
| Revision-26 12-name benchmark (iterations 2, 3, 4) | restoration: MSGE, TASK, PACS, DAC, BUD, GOLD, MCY; drawn: LPG, ITGR, KOF, DAR, VSNT; skipped by Amendment 1 (seen, not valued): OGE, HNRG, PTCT; passed over earlier: TOP, NRP | `P25\frozen_p4r26\_draw.json`, `P25\design.py:239-244, 272`, `SPEC_rev26_staged_analyst.md:207-225`, `P25\runs_p4r26\{3,4}\score.json` |
| Revision-24 pilot (6 pilot names) + KSS, HRTG | studied during revision 25 design | `PLAN_phase4_qwen_restoration.md:31-33`, `PLAN_rev25_2026-10-16.md:166-170` |
| Revision-25 Stage-1 set (8 names) | CWEN, MSGE, MRP, EQNR, FTNT, LIND, LFST, STT | `PLAN_rev25_2026-10-16.md:166-176`, `scratch\rev23\stage1_names\STAGE1_NAMES.json` |
| Gate 1 holdout 2023-24 (code engine c7d7a4f) | FAILED B1/B2/B5; dev and holdout read | `STATUS.md` Phase 4 history; `05_...:109-117`; `scratch\rev23\gate1_holdout\` |
| Gate 1b holdout 2025 | read; registered outcome FAIL on H3; audit shows ~0 incremental information | `STATUS.md:891-908`; `scratch\rev23\gate1b_holdout\` |
| Gate 2 (Muse, 600 company-dates; run 1 sealed invalid at 54/600, run 2 completed); 2026-06-30 sample | June-quarter outcomes "seen in aggregate" | `STATUS.md:867-915`; `REGISTRATION_gate2b.md:26-29` |
| Gate 2b date 2026-07-31 (code engine v2.1) | scored, **FAIL** | `CROSS_CHECK_15_gate2b_fail.md` (section 2 'The result: FAIL') |
| Baseline A: screener replay 2017-2025 | viewed in full; "the baseline period has already been viewed" | `scratch\baselineA\REPORT_baselineA.md`; `PROTOCOL_factor_ai_m2_2026-10-23.md:29` |
| A1 candidate replay | failed its preregistered turnover gate (1.6311x vs 1.60x); do not retune on it | `REPORT_m3_a0_a1_2026-10-23.md`; PLAN rev a section 1 |
| 3M live set (MA, CMRE, HRTG, ILMN, ECPG) | used for contract tuning | `orchestration\CLOSE_3M.md`, `RR_M-LIVE.md` |
| 3N DEV set (23 events + 24 controls) | being scored now (task `RS2-M3N-DEV-Runner`) | `PREREG_m3n.json`, `SPEC_m3n_event_validation.md:138-140`, `LOG.md` |
| Muse Phase 6 tests A, B, C | A constructed 73 cases, B 20 real events, C shadow week | `05_...:124-127` |

### Untouched holdouts (listed only; results and labels not opened)
| Holdout | What it is | Where recorded |
|---|---|---|
| **CTVA, NHC, TTAM, CLDT** | the 4-name end-to-end revision-26 holdout; "untouched and must stay so until a design worth spending it on exists"; "run once on the frozen design"; also excluded from the 3N frame | `SPEC_rev26_staged_analyst.md:213-225, 274-275, 299-300` (the Amendment 1 draw; `design.py:242` still lists KOF, DAR, VSNT, CTVA and is stale, `07_OPEN_ITEMS_AND_NEXT_STEPS.md:44`), `handoff_2026-10-23\02_...:27`, `PREREG_m3n.json` `frame.excluded_tickers`, `P25\frozen_p4r26\{CTVA,NHC,TTAM,CLDT}\` (frozen packs; not opened) |
| **Rev-25 Stage 2 sealed names (3)** | sealed by a deterministic hash rule; only the file hash recorded; "untouched until everything is frozen". I could not establish from the records whether they were ever unsealed or run | `scratch\rev23\stage2_sealed\SEALED_stage2_names_v2.json` (not opened), `COURSE_GATE_1_SUMMARY.md:17`, `PLAN_rev25_2026-10-16.md:60,130,169`, `PHASE_4_AMENDMENTS.md:7711` |
| **3N FRESH set (23 events, 22 in an earlier freeze)** | sealed: neither run nor read until the first prompt/model/contract change after DEV is scored and the LESL T2 check passed | `SPEC_m3n_event_validation.md:138, 295-297`, `PREREG_m3n.json`, memory `m3n-3n-state`; truth files under `scratch\rev23\m3n\` (not opened) |
| **Gate 2b confirmation dates 2026-08-31, 09-30, 10-30** (fiscal-year-1 target, scoring 2027-04-15) | registered, "valued under the same freeze, then pooled"; the registration says a confirmation pass never rescues a 07-31 failure and a failure's dates "are never reused". Whether they were ever frozen or run is not established in what I read; status needs the operator | `REGISTRATION_gate2b.md:50-57, 222-232, 300-312`; `STATUS.md` (Phase 4 history, "Gate 2b now scores the fiscal-year-1 target on 2026-08-31/09-30/10-30") |
| **Forward paper formations** (A0 ledger 2026-09-30; 2026-10-30 formation of 3O) | prospective; outcomes not yet realized; 3O frozen before any formation analysis | `RR_L7.md`, `LOG.md` (WO_L7, WO_O2), `PREREG_m3o.json` |

### Date windows still unviewed and eligible for a new evaluation
- Valuation/Qwen retrospective windows must have decisions dated **2025-10-01 or later** (Qwen cutoff about mid-April 2025; `scratch\qwen_cutoff\REPORT_cutoff.md`; `PROTOCOL_factor_ai_m2:44-45`) and source-time-proven inputs. The historical Oct-24 nominee cohort is certified
  **0/163**, so retrospective Qwen replays are "not_testable" unless dated replayable sources exist; current web search may not substitute (`PROTOCOL:45`; `CLOSE_3L.md` L-H CLOSED_UNVERIFIABLE).
  In short: **no retrospective window is both eligible and certified**. The eligible new evidence is prospective: formations after 2026-10-15 (the date of the screener file the rev-26 panel was run on), concretely the A0 ledger from 2026-09-30 and the 2026-10-30 formation, with outcomes arriving from 2026-11-02 onward.
- The 3N event window 2025-12-15 to 2026-09-30 was used for event discovery; its DEV half has been viewed, its FRESH half is sealed. It is for events, not valuation accuracy.
- Code-engine windows: 2017-2025 (baseline A, gates 1/1b), 2026-06-30 and 2026-07-31 are used. I found no registered, unviewed code-engine window other than the gate-2b confirmation dates above (status uncertain) and new prospective dates.
- Hard rule in the plan: do not retune rev 26 against its consumed panel; new tests need new names/dates (`PLAN rev a` 3Q item 1 and 8; `07_OPEN_ITEMS_AND_NEXT_STEPS.md:64`).

---

## 6. Existing reconciliation checks between model prose and numbers

Revision-26 stage-4 path (R26, in force for the frozen pilot):
| Check | What it checks | Gates? | File:line |
|---|---|---|---|
| `verify_memo` flags `memo_number_mismatch` | each labelled table number the memo states right after its label must round to the table value (percent, units, fraction written without %) | **gates** (`MEMO_FLAGS`) | `r26_late.py:861-913`, `MEMO_FLAGS:41`; decision to reasons `r26_stages.py:2032` |
| `memo_verdict_mismatch` | the memo's verdict word must equal the code's verdict word | gates | `r26_late.py:899-903` |
| `memo_forecast_mismatch` | an enum (baseline, transition, the three labels) named in the memo must equal the forecast | gates | `r26_late.py:884-889` |
| `memo_prose_number_mismatch`, `memo_unknown_fact_id` | numbers in free prose not traceable to the table, dossier facts, cited ids or input texts; bracketed fact ids not in the dossier | **annotate only** (item 13) | `r26_late.py:840-858, 905-912` |
| Forecast structure | fields, finite numbers, enums, cited fact ids exist and are usable, probabilities sum 1 +- 0.01, `terminal_g` below the discount rate, `terminal_ronic` > 0, normalized year 3..5, reason <= 60 words; "a margin is never bounded" | refuses the sample for repair | `r26_forecast.py:185-225` |
| Labels and durability thesis form | three labels' enums and cited facts; four durability statements non-empty and <= 40 words | form only; the content is not checked | `r26_late.py:78-93, 111` |
| Crux validity | each crux entry must be a judgment input, reachable in its bound, and cite company evidence found verbatim in a source; one failing entry invalidates the crux; reach classified reachable / jointly reachable / beyond reach | gates direction (no valid crux -> hold) | `crux_check.py:249-300`, `r26_stages.assess_reach:1810`, `BEYOND_REACH_*:1804-1807` |
| `path_dominated_crux`, `price_beyond_every_input_reach` | the explicit-year path alone, or no input within reach, explains the price | non-actionable pending review | `r26_stages.py:1799-1807, 2041-2045` |
| `cash_scaling_out_of_band` | kappa = base_cf / X_0 outside 0.67-1.5 (the year-6 jump) | non-actionable | `r26_stages.py:1356-1369, 2048-2050` |
| `terminal_growth_positive_for_shrinking_business` | Base revenue shrinks in most of years 1-2 and normalized, yet terminal_g > 0 | annotate only | `r26_stages.py:1371-1380, 2051-2053` |
| `margin_level_without_filed_fact` | a margin level supported only by company-adjusted or third-party facts | annotate only | `r26_stages.py:1343-1353` |
| Sample dispersion / direction | three blind Base samples must agree on direction and spread <= 20%: `samples_direction_split`, `samples_spread_above_20pct` | non-actionable | `r26_stages.py:2072-2090` (`SAMPLES_SPREAD_MAX`), `r26_forecast.direction_split:635` |
| `contract_fields_unfilled` | conviction, moat, re-entry tranches have no code source | non-actionable, 9/9 | `r26_late.py:923`, `r26_stages.py:2036-2037` |
| Data no-calls before any model call | `base_cf_unavailable`, `shares_unavailable`, `bridge_unavailable_*`, `family_unresolved` | no-call | `r26_stages.valuation_inputs:1140-1197` |
| Desk refusals | `base_cf <= 0`, `wacc <= terminal_g`, `terminal_ronic <= 0`, equity frame with net debt, SBC double deduction | refuses the valuation | `financial_model_tool.py:469, 475, 490, 520-536` |

Fiduciary gate and verdict-row gates (live branch and r26-int; the r26-int copy of `fiduciary_gate.py` has 233 more lines than live):
- **Fiduciary contract** (`fiduciary_gate.validate_fiduciary_contract`, R26 `tools/audit_202608/fiduciary_gate.py:85-410`; applied by `depth_pipeline.fiduciary_verdict_gate:442-490`):
  - Fatal (`is_valid = False`): `base_iv` missing / not a number / non-positive (110-118); `base_iv` outside 0.01x-15x price (122); scenario monotonicity Bear <= Base <= Bull (141-147).
  - Repairs recorded as amendments: probabilities normalized or declared unusable (168-185); payoff skew recomputed (253); inverted re-entry tranches swapped (268); score clamping.
  - **Kelly clamp = contract FAIL** (237, 356): non-positive expected edge or Base <= price clamps Kelly to 0.0%; `fiduciary_verdict_gate` turns any clamp or fatal into `fiduciary_verdict: FAIL`, size zero, flag `FIDUCIARY_CONTRACT_FAIL` (depth_pipeline 474-480).
  - Invalidation rules: none checkable, or a missing momentum break rule -> clamp -> FAIL; some uncheckable -> `invalidation_partially_checkable` annotation (289-340).
  - `plausibility_gate` (480-593, r26-int only): terminal growth not below the rate -> reject (501); each implied metric (long-run margin, 10-year revenue CAGR, terminal RONIC, 10-year earnings ratio, terminal_g) against the cohort's P5-P95 -> reject unless it has a resolving citation (`implausible_unsupported_<metric>` 556, supported outliers annotated); `reject` makes the verdict not usable (`depth_pipeline.py` after 833); no cohort -> annotated, not gated.
- **Dispersion quarantine** (`depth_pipeline.band_verdict:615` ... 822-831): spread across basis samples above `tol` (25%) demotes `undervalued`/`overvalued` to `hold`, stamps `HIGH_DISPERSION_QUARANTINE`; early-stop tolerance 15% and bear-IV tolerance 40% (`consensus_valuation.py:84-91`); read again on write by `depth_gates.assess` reason 6 `high_dispersion` (`depth_gates.py:132, 252-256`) and `iv_instability` 25% between runs (`depth_pipeline.py:161-179`).
- **`depth_gates.assess`** (`depth_gates.py:138-330`): 22 reasons, among them `fiduciary_fail` (4), `high_dispersion` (6), `outside_street_fence` (10), `mos_beyond_150pct` (11, `MOS_BEYOND_PCT = 150`), `desk_not_used` (12), `depleting_producer_unsupported` (16), `directional_without_valid_crux` (19), `nci_share_unmeasured` / `per_share_basis_unverified` (20-21); `FIRST_VALID_PACK_REVISION = None` means reason 9 is dormant.
- **Audit after the fact**: `depth_sanity.audit:66` (published direction vs the band, lost samples, stub reports, one-sided surviving samples), `pack_data_sanity.check_pack_data_sanity:25` (shares missing / mismatch >10%, TTM vs quarters >10%).
- **Revision-25 bridge checks** C1-C5 and K1-K4 (`bridge_checks.py:77-308`; tolerances frozen: margin 0.03, revenue 0.10, basis 0.01): they compare declared margins/labels with the declared path and ask for a reason; they apply to the r25 arms, and I did not find them wired into the r26 stage path.

What no check does today (stated, not proposed): compare memo claims about economics (supported by a record, "mid-cycle", "depressed by one-offs") with the dossier's facts; check the premium or discount over the filed record against the span of evidence; check that Bull/Bear
probabilities and tails are economically coherent; check the year-5 to year-6 flow seam as a gate (it is only a flag). These appear in the deferred list as "a semantic memo entailment check" and "a scenario-coherence diagnostic" (`07_OPEN_ITEMS_AND_NEXT_STEPS.md:53,56`; `SPEC_rev26_staged_analyst.md:277-279`).

---

## Open decisions 3Q will need from the operator

1. **D2 fade convention**: reinvestment during the fade follows revenue growth (as built, `consensus_reference.py:579-581`) or earnings growth (capital tied to profit); plus whether to accept the proposed synthetic-firm truth test first. The values differ by about +-20% in the controlled examples.
2. **Does D2 go into the desk at all in 3Q** (part (c): TASK/schema, PACK_REVISION, price-implied solver on D2, plus the unmerged screener `d2-fields` branch whose merge order is binding), or does 3Q fix kappa by a smaller change? The kappa defect (DAR -48% at kappa = 1) cannot be fixed "properly" without this choice. Also the base branch: D2 and rev 26 are not on the live `phase-4` branch.
3. **D2 materiality threshold** (interval rule, release counts at 2% / 5% / 10% were 8 / 10 / 14 of 24 tested; "the operator decides after the recovery work").
4. **PACK_REVISION**: any change to what the model is told is a versioned decision (workspace non-negotiable 7); the standing note in memory (2026-09-27) says change without asking, version, record, and have a check done. Confirm that still governs for the 3Q pack/TASK edits.
5. **Which evaluation evidence 3Q may use**: whether the 12-name panel may serve only as a no-retuning regression set; whether CTVA, NHC, TTAM, CLDT stay sealed (current plan: yes); whether a new panel is a prospective draw (pre-registered, hash-ordered) because no retrospective window is certified; and the status of the Stage-2 sealed names and the gate-2b confirmation dates.
6. **The new pass bar for "Qwen claims agree with the calculation"**: keep the 83% coherent rule under the amended rubric, or register a different, preferably deterministic, bar; and who the blind readers are (outside AI unavailable; a fresh blind Opus is the standing fallback, memory `cross-check-fallback-opus`).
7. **Scope of business models**: 30 of 160 nominees are `family_not_built` (15 real estate, 10 pre-profit, 5 utilities) and 29 commodity. Choose per family: value with the repaired common equation, route (financial ROE route, D2 REIT route), or no-call with a stated reason. O3/O6 are already approved for the D2 routes; depleting producers are currently non-actionable by gate 16.
8. **Fix list priority among known defects** not blocked by D2: tax rule (already changed post-freeze), decliner terminal state (annotation only), `contract_fields_unfilled` (conviction/moat/tranches have no code owner, 9/9 non-actionable), the 14.0% > 13.5% style premium-over-record checks (none exist).
9. **Authority ceiling**: confirm valuation stays diagnostic only (SPEC_factor_led_v2 section 1; 3Q pass criteria give portfolio-weight authority only after independent evidence and explicit approval), so 3Q's output cannot change paper selection, weights, exits or eligibility.
10. **GPU/time**: 3Q's rerun of Qwen needs a stage-1 refreeze or reuse of the frozen dossiers; standing GPU go exists (memory `gpu-standing-go`), but the cross-check-before-GPU rule applies and the operator games on the card.
