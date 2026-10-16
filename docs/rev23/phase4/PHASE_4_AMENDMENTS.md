# Phase 4 — amendments to the work order (orchestrator review, 2026-09-24)

`PHASE_4_ANALYST.md` was written on 2026-09-22, before Phases 1–3, S4 and S5 ran. Several things
it assumes have since changed, and a few of its choices would hurt what the phase is for. The
items below amend it. Each says what, why, and the evidence. The operator may veto any of them.

## A. Missing prerequisites

**A1. rs2 reads stale screener data. Fix it first (new P4.−1).**
- `screener_data_dir` points at the `stock-screener` dev checkout. That checkout is on another
  session's old branch (Phase 2 review C9).
- Phase 4 feeds the analyst from screener files: §2.5 reads `factor_scores.json` and
  `momentum_state.json`, P4.5 reads `momentum_state.json`, and P4.10 reads `stocks.json`. As
  things stand, all of those would be days or weeks old, silently.
- **Decision:**
  - rs2 reads screener data from the dedicated publish clone.
  - At sweep start, and before `--monitor`, under the existing publish lock, it refreshes the
    clone to `origin/main`.
  - Every verdict is stamped with `screener_data_commit`.
  - If the refresh fails, the sweep refuses to run, loudly.

**A2. The GPU budget is not sized. Stage the battery.**
- Measured: one analyst sample takes about 35–60 minutes (FLXS 09-19: 58 min and 43 min; GEV
  09-20: 33–44 min).
- The battery as written is 10 names × 5 samples × 3 arms = 150 samples, which is **about 110
  GPU-hours (4–5 days continuous)**.
- **Decision:** run it in stages.
  - **Stage 1:** 4 names × 3 samples, arm A only, frozen pack and frozen evidence. That is
    about 9 hours. The names are among the widest base-IV spreads on record (measured over 98
    tickers' consensus runs), preferring names with repeated runs:

    | name | max spread | runs |
    |---|---|---|
    | FIX | 240% | 3 |
    | AMD | 172% | 3 |
    | DXC | 159% | 1 |
    | GEV | 136% | 7 |
  - Attribution runs on Stage 1.
  - Arms B and C run only for the input that dominates, and only on the names where it
    dominates.
- The battery writes no ledger (it calls `consensus_valuation` directly) and publishes nothing.
  `DEPTH_PAUSED` stays on.
- It needs Ollama running on the PC. **The operator must agree to the GPU time.**

## B. Design corrections

**B1. §2.5 must not show the screener's opinion to the analyst.**
- The work order prints the nomination door, rank, band and the `falling_knife` label. Those are
  the quant screen's verdict, not facts about price.
- Showing "research_now, rank 3" invites the analyst to agree. That erodes the independent
  second opinion the divergence engine exists to record. The pack already excludes
  `factor_scores.json` as "circular" (`capability_test.py:460-461`) for exactly this reason.
- **Decision:** §2.5 prints only price facts (returns, distance from high, 200-day trend,
  relative strength, realised vol, `regime_shift`, `mom_break`, the sector-neutral momentum z).
  The nomination context is stamped on the verdict for grading, not shown to the model.

**B2. The instability check must not compare against invalid verdicts.**
- P4.7's `--prior-base` compares the new median with the prior verdict. Every prior verdict on
  record comes from the old, invalid analyst.
- Comparing against those would fire `mode_instability` on the new analyst for the old one's
  errors.
- **Decision:** a prior counts only if `depth_gates.analyst_valid(prior)`. Otherwise the check is
  skipped and stamped `prior_base: "none_valid"`.

**B3. Turning validity on is part of the phase gate.**
- Phase 2 left `depth_gates.FIRST_VALID_PACK_REVISION = None`.
- **Decision:**
  - The Phase 4 gate sets it to the Phase 4 pack revision.
  - `depth_gates.assess` then adds the reason `pre_valid_analyst` to any older row, so no
    verdict from the old analyst can ever become actionable again.
  - The grader starts counting from that revision.

**B4. The gate run must not reach production.**
- The gate's "one full production-style run" through `orchestrate_depth.py` would:
  - write the production ledger;
  - publish the overlay, which is a public site deploy;
  - hand the screener an `actionable: true` row that `rn_depth` could buy on paper.
- That would happen before Phase 6's resume protocol.
- **Decision:**
  - Add `--no-publish`.
  - The gate run goes to the test ledger (`RS2_RUN_SOURCE=gate_test`, routed like `manual`).
  - Every gate check reads the test ledger and the run directory.
  - The first production verdicts come only through Phase 6.

**B5. The battery's falling-knife names.** P3.3 removed every falling knife from the book. Pick
the two names from scored profiles flagged `falling_knife` with the lowest `z_momentum` that
have full fundamentals.

**B6. The success metric must include direction.**
- The harm on record is a direction flip: GEV the same day went undervalued, hold, then
  overvalued. A ≤ 15% base-IV spread can still hide that near a band edge.
- **Decision:** add "all samples agree on `direction` for ≥ 90% of battery names" to the P4.0
  metric, and report it beside the spread distribution.

## C. Links to work done since the plan

**C1. Shocks.**
- Pack §1.5 prints the active shocks from the S4 register (facts: shock, severity, onset).
- The verdict stamps `active_shocks_at_verdict`.
- If S4's forward-risk test (T3) passes, `risk_flag` becomes a fourth component of P4.9:
  `size_hint = min(dispersion, mos, conviction, risk)`.
- If T3 fails, the label is shown, and nothing else changes.

**C2. Grading the new fields.** P4.3's new verdict fields (`entry_timing`, `momentum_view`, `m`)
and `analyst_valid` must be carried onto TRK-06 graded rows (Phase 2 C4). The `entry_timing`
cut was the strongest graded signal in the retired lane (+8.59% vs −5.22% at 30 days). The
grader must be able to measure it on the new analyst from day one.

**C3. Momentum source.** §2.5 reads the daily fields from `momentum_state.json`, which is now
saved each run (P3.1). It uses the verdict's `price_asof` as its date. Fields are absent, never
guessed, when the daily file lacks the name.

## D. Order

1. **P4.−1** data path (A1).
2. **One pack revision** carrying P4.0a (declared inputs), P4.1 (§2.5 as amended in B1), P4.2
   (charter v3.1 and the structured contract), P4.6 (rate engine and the CoE anchor) and C1. One
   revision means one model rebuild and one battery, not four.
3. **Stage 1 battery** and attribution (A2, B6), then P4.0d controls for the dominating input,
   then its arm.
4. P4.3, P4.4, P4.7 (with B2), P4.8, P4.9 (with C1), P4.10, P4.11.
5. P4.5 thesis monitor.
6. The gate (B3, B4). P4.12 docs.

**Trade-off.** Bundling the pack changes means the before/after cannot credit each change
separately. That is acceptable: the metric is about the result (stable, direction-consistent
verdicts), and attribution works on the declared inputs within the new pack.

## Operator decisions needed

1. **GPU time for the battery:** about 9 hours for Stage 1, with Ollama running. More only if
   attribution needs it.
2. **Registering the daily `--monitor` task.** This is in the original plan; it stays approval.
3. Any veto of A–D above.

---

## E. Getting valuation right (operator mandate, 2026-09-24)

**The mandate.** The analyst must get valuation right, be common-sensical, and be current on the
real world: the AI and semiconductor boom, the Iran war, high inflation. The operator's view:
"nothing beats AI momentum; like the internet boom, only bigger". The orchestrator defines
"right" and measures it.

### E0. What the old analyst got wrong — measured 2026-09-24

The graded rows are invalid for judging the new analyst, but they diagnose the old one.

- **It called almost everything overvalued.** Of 534 verdicts, 284 (53%) were `overvalued`, 130
  `hold`, 100 `undervalued`. The book it analysed was already pre-screened for value and quality,
  so a majority of "overvalued" there is a sign of model bias.
- **AI and semiconductor names were worse.** Of 62 verdicts, 51 (82%) were `overvalued`. Examples:
  - STX: −75.6% "overvalued" while its trailing 12-1 return was +253%;
  - LITE: −67.3% while it rose +462%;
  - DELL, AMAT, ANET, MPWR: −46% to −58%.
- **Its calls ran backwards.** The grader's 46 distinct 30-day outcomes (n is small, one period):

  | direction | n | mean excess vs IWM | share that beat IWM |
  |---|---|---|---|
  | overvalued | 28 | +7.4% | 75% |
  | undervalued | 8 | −4.7% | 38% |

- **Mechanism (hypothesis, tested by E-audit below).** A textbook DCF with a 5-year explicit
  stage and then a GDP-like perpetual growth rate cannot value a company that keeps growing 20%+
  for a decade. Every secular winner comes out "overvalued", and the market keeps proving it
  wrong.

### E1. Definition of "right" — measurable, owned by the orchestrator

1. **Predictive.** Across valid verdicts, the continuous score `m` and the direction rank forward
   excess returns at 3, 6 and 12 months: rank IC > 0 with t ≥ 2 once n allows. Undervalued calls
   beat overvalued calls. Graded by TRK-06; the first read is about 90 days after the first valid
   verdicts.
2. **Calibrated.** Larger claimed upside goes with larger realised excess return (bucketed).
3. **No structural skew.**
   - On a value-and-quality pre-screened book, the share of `overvalued` calls must not dominate
     by construction. The battery reports the direction mix. A mix beyond 50% `overvalued` on the
     nominated book triggers the E-audit before any verdict counts.
   - No theme bias: AI and semiconductor names are not called overvalued at a rate unrelated to
     their measured fundamentals.
4. **Consistent.** The P4.0 metric: spread ≤ 15% and the same direction across samples (B6).
5. **Engages the market.** Every verdict states what the current price implies (reverse DCF:
   growth rate and years) and argues, with dated evidence, why its own view differs.

### E2. Valuation mechanics — fix the growth blind spot (pack contract and desk)

**Three-stage model** (`financial_model_tool`):

- an explicit stage (5 years);
- a fade stage (years 6–10 or longer) from the analyst's growth toward the terminal rate;
- a terminal value computed both as Gordon growth and as an exit multiple, reconciled against
  the MRI sector multiple band (P4.0d iii).

The fade length and speed are declared inputs, justified by reinvestment runway, moat and
industry growth. A company in an industry growing 20%+ may not be faded to GDP in year 6 without
saying why.

**Base rates.** The pack prints the historical probability of sustaining ≥ 10%, ≥ 20% and ≥ 30%
revenue growth for 5 and 10 years, by starting revenue size. The analyst's stage-1 and fade
growth are compared against them; beyond the 90th-percentile base rate needs explicit evidence.

- Source: Mauboussin/Credit Suisse base-rate tables where published. Otherwise, measured from
  our own `fundamentals_history` (10-year arrays, about 6,900 names). **Decision: measure our
  own.** It is reproducible and current.

**Reverse DCF, mandatory.** The desk returns the growth the price implies over 10 years under the
anchor cost of equity. The analyst must print it and reconcile it with its own view.

**Scenarios.** Bull, base and bear with explicit probabilities. The IV is the
probability-weighted value, with base IV kept for comparison. For AI-exposed names, the bull case
must model sustained AI capex demand and the bear case a capex digestion or cycle downturn. The
analyst must say which one current evidence points to.

### E3. Current-world awareness

The model's own knowledge ends at its training cutoff. It does not know 2026 unless the pack or
its research tells it.

**Pack §1.6 "STATE OF THE WORLD"**, deterministic and dated:

- the MRI regime vector;
- the active shocks, from the S4 register (e.g. oil, if the Iran war is moving it; the
  turbulence flag);
- the latest inflation and rate prints;
- the MRI news layer's recent theme summary (narrative only, dated sources).

**Research mandate** (`deep_research.py` brief template):

- a "what changed in the last 12 months" section for the company and its industry;
- at least 3 sources dated within 30 days for the key growth driver;
- AI exposure explicitly assessed (AI revenue share, capex and customer concentration) where
  relevant.

The brief-age ceiling stays at 14 days (P1.7/C4).

### E4. Checks before anything counts

1. **Error audit (operator approved).**
   - An independent reviewer model, run once by the orchestrator, reads a stratified sample of
     about 40 archived reports: AI and semiconductors, value names, overvalued and undervalued
     calls, and the worst 30-day misses.
   - It uses a checklist: earnings base, share count, debt bridge, growth versus base rate,
     terminal method, discount rate, whether current events were known, and arithmetic.
   - Output: a failure-mode table with counts. It is written **before** the charter edit (P4.2),
     so the charter fixes measured failures.
2. **Assumption sanity (operator approved).** On every verdict, the harness compares declared
   growth and margins with the company's 10-year history, the base-rate percentile and the
   reverse-DCF implied growth. Outliers are flagged and shown in the report bundle. This is a
   flag, not a veto.
3. **Time-travel trial (operator approved).**
   - About 10 names, briefing dated 2026-03-31 (after Qwen's training cutoff; verify the cutoff
     from the model card), with point-in-time fundamentals and prices, and research OFF (live web
     search would leak the future).
   - Graded against 2026-03-31 → 2026-06-30 excess returns.
   - This tests the valuation engine, not research. It is a trial: it informs, it does not gate.

### E5. The balance on "AI momentum"

- The design rides secular winners. It does so through:
  - growth fade and base rates instead of a GDP cliff;
  - timing from price action (P4.2: value decides whether, price decides when);
  - no cull of large-cap AI names by forensic or solvency screens (P3.6b).
- It keeps the ability to say "priced for perfection" when the implied growth exceeds any base
  rate. The internet boom made both Amazon (+10,000% over the following decades) and Cisco (−80%
  after 2000). The analyst's job is to tell them apart, and the momentum-break rules (P4.2)
  protect the exit.

### E5b. The momentum basis — riding the trend when value alone says no (orchestrator, 2026-09-24)

**The gap.** E5 says the design rides secular winners, but charter v3.1 as first written had no
path to a position when the honest value sits below the price: "value decides WHETHER", and "a
fairly valued business in a strong uptrend is not a buy on momentum alone". The E-audit's
re-pricing shows that is most AI leaders. The auditors' defensible values (midpoint of each
stated range), as a share of the price at the time:

| about fair (≥ 0.9) | 0.6–0.9 | 0.5–0.6 | below 0.5 |
|---|---|---|---|
| NVDA 1.03, GOOG 1.04, CLS 1.04 | GEV 0.89, STX 0.88, AMZN 0.87, CDNS 0.83, AVGO 0.77, ANET 0.77, CAT 0.74, CIEN 0.73, MU 0.67, LITE 0.66, DELL 0.61, MPWR 0.60, SITM ≤ 0.9 | ARM 0.58, AMD 0.50 (at $508) | FIX 0.47, AMAT 0.46 |

The old analyst's `overvalued` calls beat IWM by +7.4% over 30 days (n = 28, one period). That is
what the gap cost.

**Evidence used.**
- Momentum is strongest among expensive (growth) stocks, and value is weakest among recent
  winners (Asness 1997, "The Interaction of Value and Momentum Strategies").
- Nearness to the 52-week high carries much of the momentum return and does not reverse later
  (George & Hwang 2004).
- Sharp run-ups do not predict lower average returns. They predict a higher chance of a crash
  (Greenwood, Shleifer & You 2019, "Bubbles for Fama"). So the risk is carried by position size
  and a trend exit, not by the verdict.

**Decision.**
1. **The verdict stays honest.** `direction` remains the valuation call. Nobody inflates a value
   to justify a trend.
2. **New contract fields.**
   - `position_basis`: `value` | `momentum` | `none`.
   - `momentum_evidence`: the dated fundamental facts behind the trend (guidance raised,
     backlog or orders growth, estimates rising), cited from the GUIDANCE block or the filings.
   - `value` requires `undervalued`.
   - `momentum` requires all of:
     - direction `hold` or `overvalued`;
     - `entry_timing` `buy_now`;
     - non-empty `momentum_evidence`;
     - a `momentum_break_rule`.
   - Corrected 2026-09-24 after the AMD probe. The first version also required `momentum_view`
     `confirming`, which contradicts that field's definition: an uptrend CONTRADICTS an
     overvalued call. Under it, a textbook case could never qualify (AMD, with estimates +18% in
     90 days and 33 up / 3 down). Trend strength is checked by the deterministic eligibility
     below, not by that field.
3. **Deterministic eligibility for `momentum`** (harness, from the pack's own facts):
   - universe momentum z ≥ +0.5 (the top third: measured p70 = +0.53, n = 2,874, 2026-09-23;
     NVDA sits at +0.67, so a 0.75 cut would exclude it);
   - 6-month return > 0;
   - within 15% of the 12-month high (`high_52w_proxy` ≥ −0.15; the universe median is −0.17);
   - no `regime_shift_down` flag;
   - TTM revenue growth > 0;
   - base IV ≥ 0.5 × price. Below that, the price needs about double what a guidance-anchored,
     faded valuation supports. That is bubble territory, where crashes are deepest. It keeps 18
     of the 20 audited AI leaders (AMD exactly at the line).

   Measured 2026-09-23: 764 of 2,874 scored names pass the price checks, 73 of them nominated.
   AI leaders passing today: NVDA, AMD, MU, TSM, ANET, MRVL, DELL, LITE, STX, ARM, INTC, ETN,
   PWR, GOOGL, AMZN, AAPL. Those that have stalled fail it: AVGO, LRCX, AMAT, KLAC, SNDK, VRT,
   GEV, COHR, CIEN, FIX, CAT, WDC, TER.

   When the analyst proposes `momentum` and a check fails, the basis becomes `none` with the
   flag `momentum_basis_ineligible:<check>`. When every check passes but the analyst says
   `none`, its choice stands; its reasons are in the report.
4. **Size (P4.9).**
   - For `momentum`, the MoS component is replaced by a basis cap: `half` when the direction is
     `hold`, `quarter` when it is `overvalued`.
   - The dispersion, conviction and turbulence components still apply, under the same min rule.
   - Kelly stays the DCF Kelly: 0 when overvalued, and `kelly_on_overvalued` is unchanged.
5. **Exit.**
   - A momentum position is exited when the trend breaks, not when the valuation looks stretched.
   - The monitor (P4.5) applies the analyst's `momentum_break_rule` plus a system trend exit:
     `mom_6m < 0` or `high_52w_proxy < −0.25`, whichever fires first.
   - The 10-point gap between the −0.15 entry and the −0.25 exit is hysteresis, so a normal
     pullback does not whipsaw the position.
6. **Grading.**
   - TRK-06 and Phase 5 grade `momentum` entries separately from `value` entries, against IWM at
     1, 3 and 6 months.
   - Momentum entries that fail to beat IWM after 30 or more entries send this section back for
     review.
7. **Downstream (Phase 6).**
   - The KIS sync must treat `momentum` as buyable at its capped size and the monitor's exit as a
     sell.
   - A portfolio-level cap on the momentum sleeve is set with the Phase 6 baseline.

### E7. Guarding against curve-fitting (pre-registered 2026-09-24 ~13:10, before any Stage 2 result)

**The risk.** The operator asked whether the orchestrator is tuning Qwen to produce the outputs it
wants, rather than building a system that behaves correctly in every situation and on every
repetition. That risk is real. Most of today's changes are defect fixes that apply to every name:
- the search loop;
- the broken tools;
- guidance from the filings;
- the world news;
- fresh consensus data;
- the calculator requiring every input.

Four choices were made while looking at today's names:
- the momentum thresholds (z ≥ 0.5 was checked against NVDA; the 0.5× value line was checked
  against the 20 audited AI leaders);
- the Blume adjustment (prompted by COST's 5.84% cost of equity);
- the AI-specific wording in the charter (3c and the AI bull/bear scenarios);
- the Stage 2 names themselves (FIX, AMD, DXC and GEV motivated the fixes, so Stage 2 is
  in-sample).

**Rules from now on.**
1. **Frozen.** The following do not change in response to Stage 2, the hold-out, the gate or
   the time-travel trial:
   - the E5b thresholds;
   - the fail-fast bounds (0.5× the discounted street low, 2× the discounted street high);
   - the 10% MoS direction rule;
   - the 15% spread tolerance;
   - the charter text.
2. **Only defects get fixed.** A result may only trigger a fix for a defect: a bug, bad or
   missing data, or a contract violation the harness can show. It may never trigger a change to
   make a number look better. Any fix is re-tested on a **new** rule-based draw (next seed),
   never on the names that exposed it.
3. **Hold-out.** Drawn by rule before any result:
   - the draw was seed 20260924, 4 random sectors of the nominated book and one name each,
     excluding every name touched during design (~90);
   - it gave **FSM, LAMR, LIND, UGI**;
   - they run through the PRODUCTION path (`RS2_RUN_SOURCE=gate_test`, `--no-publish`,
     3 samples each), which also serves as the Phase 4 gate run.
4. **Pass criteria, pooled over the 8 names (Stage 2 + hold-out), fixed now.**
   - At least 7 of 8 names have a spread ≤ 15%.
   - At least 90% of all usable samples match their name's majority direction.
   - The hold-out is also reported on its own, because it is the out-of-sample evidence.
   - A fail-fast stop is a flag for the orchestrator to read the report. It is not scored as a
     wrong answer. Street targets are a plausibility fence, not a target.
5. **Process checks count as much as numbers.** Every sample is checked for:
   - a desk-backed base IV;
   - a cost of equity within the anchor band, or a stated reason;
   - a stated reason for any deviation from guidance;
   - evidence for any cycle call;
   - a neutral reverse DCF;
   - the repeat and re-run flags.

   These hold "in every situation" regardless of which number comes out.
**Stage 2 findings (2026-09-24 16:30) and the defect fixes they allow.**

FIX converged: $1,842 / $1,876 / $1,985, spread 7.8% (Stage 1: 52%). AMD did not: $394 / $205 /
$146, spread 170%. Attribution, from the run snapshots:

- **Silent share-count default.** AMD s1's published $394.44 came from a desk call that omitted
  `shares_diluted`. The desk used 1.0 bn instead of 1.635 bn (+63% per share) and also dropped
  `sbc_treatment` on a TTM FCF base. FIX s1's $65 and $75 desk values are the same default.
- **Budget burned by rejections.** AMD s1's corrected calls were rejected (missing terminal_g)
  and the rejections used up the 5-call budget, so the fixed call was refused.
- **Base cash flow ambiguity.** The three AMD samples used three different starting cash flows
  (5.10 / 6.77 / 8.40), the dominant source of the spread. All three FIX samples started from a
  TTM FCF inflated by about $1bn of working-capital float, which sample 2 itself named as
  non-recurring.

These are defects (a silent default, a budget rule, an ambiguous contract with no default
base), fixed for every name: required desk inputs, no budget charge for rejections, an
owner-earnings default base plus a cash-flow quality line, and a check that the published value
matches its desk call. They do not target any value. The owner-earnings default raises AMD's
base against two of its samples and lowers FIX's.

**Retest, per rule 2 — never on AMD or FIX.**
- The hold-out: FSM, LAMR, LIND, UGI.
- A second rule-based draw pre-registered now, seed 20260925: 2 of the 14 untouched book names
  with TTM revenue growth ≥ 30%. It gave **GPOR, AU** (natural gas and gold: growth from a
  commodity price rather than AI; no untouched AI name remains in the book).
- The pooled pass criterion stays exactly as pre-registered: the 8 names FIX, AMD, DXC, GEV,
  FSM, LAMR, LIND and UGI. GPOR and AU are reported separately.
- Two things are reported alongside it, never swapped in for it:
  - the result per configuration (Stage 2 ran before the fixes, the hold-out after);
  - the hold-out on its own.

**Accuracy checks for the retest (pre-registered 2026-09-24 ~18:05, before any retest result).**

The operator asked why repeatability is tested when the answers may not be accurate. Repeatability
is necessary but not sufficient. Three runs at $146, $205 and $394 cannot all be right, and the
system cannot tell which is. But three runs that agree can still be wrong together: FIX agreed at
7.8% while all three samples started from a base inflated by prepayment float.

No "true value" can be observed, so accuracy today is judged by proxies. Each proxy is scored per
run, alongside the spread:

- **A1. Right inputs.** None of these on any run:
  - `desk_share_count_mismatch`, `desk_contract_mismatch`, `scenario_order_violation`,
    `scenario_not_desk_backed`;
  - a base cash flow off the owner-earnings default without `base_cf_reason`;
  - an earnings-quality or cash-flow-quality warning in the pack that the report ignores.

  Every one of these was an actual error mode of the old analyst or of Stage 2.
- **A2. Information capture.** Each run names, in `catalysts` or its report, the stock-specific
  development visible in that stock's RECENT COMPANY NEWS and estimate revisions. The developments
  were identified from the preview packs, before any run:

  | Stock | Development |
  |---|---|
  | LIND | White Desert / Echo Charlie acquisition (2026-09-15) and raised 2026 guidance; next-FY EPS estimate +69% in 90 days |
  | LAMR | Raised 2026 guidance (EPS $5.95–5.99, AFFO $8.75–8.90), dividend increase, upgrade |
  | UGI | Jefferies upgrade to Buy ($43 target); fiscal-2026 guidance reaffirmed; estimates −3.6% in 90 days |
  | GPOR | J.P. Morgan double downgrade to Underweight; next-FY EPS estimate −14% in 90 days (7 down / 4 up); stock −23% in 6 months |
  | FSM | West Africa growth (the CEO's comments) and the gold price; analysts' Buy ratings |
  | AU | −12% in 1 month with estimates cut (3 down / 0 up) |

  This is the AMD failure mode, tested on names the fixes were not built on.
- **A3. Engages the market.**
  - Bull ≥ today's price, or a stated reason.
  - The base IV is inside [0.5× street low, 2× street high], or argued explicitly.
  - Years 1–2 are within 25% of consensus or guidance, or `guidance_deviation_reason` is given.
- **A4. The time-travel trial** (after the retest) is the only check against actual returns
  available now: 10 names, 2026-03-31 → 06-30. It is small and noisy; it informs and does not
  gate.

**Retest pass** = the repeatability mark (rule 4) AND, on the 6 retest names, A1 clean on at least
90% of usable runs and A2 met on at least 5 of 6 names. A3 is reported, not gated.

**Regression check on AMD and FIX (operator clarification, 2026-09-24 ~18:10).** Rule 2 was too
strict. The operator meant: first make the analysis of the failing name stop being extreme, then
check other names to rule out curve-fitting. So AMD and FIX, the two names whose failures drove
the fixes, are re-run on the fixed system right after the six-name retest: same frozen copy, same
production path, 3 samples. This checks whether the known failure went away. It is not evidence
against curve-fitting; that evidence is the untouched names.

"Less extreme", fixed now without naming any target value:

- **AMD**
  - Spread ≤ 15%.
  - No A1 flag.
  - Names the Meta Muse / agentic-AI CPU-demand catalyst.
  - Years 1–2 within 25% of consensus (current FY revenue +47%, next FY +73%) or a
    `guidance_deviation_reason`.
  - Bull ≥ today's price, or `bull_below_price_reason` naming the market-implied assumption it
    rejects.
  - No sample below 0.5× the discounted street low.
- **FIX**
  - Spread ≤ 15%.
  - The base cash flow either excludes the ~$1bn of prepayment float (owner-earnings default) or
    `base_cf_reason` shows why the float is structural.

No value level is specified for either name. Any further change prompted by these two is
re-tested on a new rule-based draw, per rule 2. The real test of
accuracy remains forward grading (TRK-06, E1.1–E1.2).

6. **The honest limit.**
   - The model knows the past up to its training cutoff, so past market regimes (2022's bear
     market, the 2000 bust) cannot be replayed out-of-sample with it.
   - Robustness across regimes can only be established going forward: TRK-06 grading, with the
     momentum basis graded separately.
   - Thresholds are not re-tuned on returns before n ≥ 30 graded entries.

### E8. Catching what moves the stock (orchestrator, 2026-09-24 ~16:45, after the operator's AMD challenge)

**The failure.** AMD rose 31% in the month before Stage 2. The catalyst was Meta's "Muse" agent
launch reviving the agentic-AI CPU-demand thesis (TrendForce 2026-09-22; the thesis dates from
April).
- Neither the research brief nor any of the three samples found it: "Muse" and "agentic" appear
  0 times in all three reports and their reasoning.
- Every search was about the GPU deals already known.
- No step ever asked why the stock moved.
- The Bull cases ($235–$346) sat below today's price ($617) and below the lowest analyst target
  ($365), with no reason given.
- One Bull came out below its own Base, computed by hand.

The operator's verdict: a system that misses this is unusable. The orchestrator agrees; this
blocks the gate.

**The cause** is the questions, not the search engine.
- The local SearXNG finds the story when asked: "why is Advanced Micro Devices stock up
  September 2026" returns the Motley Fool, CNBC and "Meta's AI Agent App Explained".
- The same generic question finds GE Vernova's 2026-09-14 sell-initiation drop.
- The old company-news source is dead (defeatbeta 404). yfinance news and SearXNG's news
  category return nothing.

**Decision (generic; the same for every name and in both directions).**

The first draft, four canned web searches, was rejected by the operator as low quality, rightly:
headline snippets from content farms, undated, and dependent on how a headline is worded. A
professional reads three things. The revised design gives the analyst the first two directly and
makes it do the third.

1. **What the market expects, and how that changed.** A structured CONSENSUS ESTIMATES table
   replaces the ambiguous "forward growth" line in SECTION 8 (yfinance).
   - It covers revenue and EPS for the current and next fiscal year (average, low, high,
     analysts), the 30/60/90-day trend of next-FY EPS, and upward versus downward revisions over
     30 days.
   - AMD, measured: next-FY revenue $88.1B ($61.3B–$116.1B, 52 analysts); next-FY EPS $13.16 90
     days ago against $15.57 now; 33 up and 3 down in 30 days. The samples had used 32–56%
     next-FY growth against a 73% consensus.
2. **What happened: RECENT COMPANY NEWS.** SearXNG's news category, with Reuters and Bing News
   enabled on the production instance, last 30 days, dated where the engine gives a date.
   - Measured: Reuters 2026-09-23 "Meta's Muse rekindles fears over winners and losers…" tops
     AMD's feed.
   - GE Vernova's feed shows its turbine deals and the Vineyard Wind settlement.
   - Point-in-time mode omits it.
   - GDELT was tried first and refused us (HTTP 429).
3. **The analyst connects them.**
   - It names the dated catalysts behind the price move and whether estimates moved with them,
     recorded in `catalysts`.
   - Base years 1–2 start from guidance or the consensus average. Bull and Bear years 1–2 sit
     near the consensus high and low unless the analyst says why.
   - Bull rests on the strongest bull catalyst and Bear on the strongest bear catalyst.
   - Bear ≤ Base ≤ Bull, all three desk-backed. An order violation makes the sample unusable.
   - A Bull below today's price must name the market-implied assumption it rejects; a Bull below
     the lowest price target must say what every analyst is missing.
   - Price targets stay context. The anchoring is to the published estimate range, not to a
     target price.

**Curve-fitting check.** The rules name no ticker and no value. The queries were tested on AMD,
GEV and DXC before being fixed. Validation happens on the untouched retest names (E7); AMD
itself is revisited later.

### E9. Discovery before valuation (orchestrator decision, 2026-09-24 ~18:30)

**Root cause.** One model pass is asked to discover what is happening AND to run a long
valuation. The model's knowledge ends before the events that matter (Meta's Muse did not exist
for it). Under a 60k-character pack it follows its prior plan — value the known business, check
the known deals — and discovery is starved.

Evidence: on the fixed system, with the Muse headline at the top of RECENT COMPANY NEWS and a TASK
bullet ordering it to explain the +31% month first, the AMD probe's first three searches were
again Q2 results, the OpenAI deal and the Helios launch. More prompt bullets will not fix this.
Deterministic scraping was prototyped on design-touched names and rejected as the main mechanism.
Causal-sentence extraction is precise but low-recall: excellent for GEV and MU, weak for AMD, FIX,
NVDA and DXC. Headline-seeded searches were mostly off-topic.

**Decision: a separate discovery run per name, then the valuation.** This is how a research desk
works: news desk first, valuation analyst second.

1. **The discovery run.**
   - It uses the same analyst model, with search_web and fetch_page only (no desk) and its own
     small budget.
   - It is one focused task: what happened in the last 90 days that investors are reacting to,
     and why.
   - Inputs: the price moves (SECTION 2.5), RECENT COMPANY NEWS, the consensus estimate trend and
     revisions, and the company's own latest release headline.
   - Output: a JSON CATALYST BRIEF. It holds 3–6 dated events, each with its mechanism (how it
     changes revenue, earnings or risk), direction, whether estimates moved, and a source URL the
     run actually fetched. It adds the price's current narrative, the main bear narrative and
     open questions. No valuation.
2. **Harness checks.**
   - Every event's URL must be among the pages fetched in that run; otherwise the event is marked
     unverified.
   - A 1-month move of 10% or more must be explained by at least one event dated within 45 days.
   - Fewer than 3 events, or no parseable brief, prints "not available" with the reason. Never
     invent.
3. **In the pack.** A CATALYST BRIEF section sits right after RECENT COMPANY NEWS (≤ 5,000
   characters). It is cached per name per day, and frozen into battery packs so every sample sees
   the same brief. Point-in-time mode leaves it off.
   - *Changed 2026-09-24, before any valuation run used a brief (defect fix, not tuning):* the cap
     was 3,000. The first real brief (AMD) rendered at 5,400 characters, 4,300 of them outside the
     mechanisms. The renderer cut only mechanisms, and each cut re-added "...", so it never
     finished. The discovery CLI hung after saving AMD's brief, and every pack build would have
     hung the same way. Fix: 5,000 characters (about 1,300 tokens next to a 55–65k-character
     pack in the analyst's 81,920-token window). Over the cap, text is cut in order of least use to the valuation: open
     questions, then narrative and bear, then event text and estimates, and mechanisms last. Every
     event is kept, and the cut level is computed, so rendering always finishes. The real AMD
     brief now renders at 4,995 characters with only the open questions shortened. Test (a) was
     not affected, because it scores the saved JSON brief.
4. **The valuation must use it.** The TASK's "Explain The Recent Move First" starts from the
   brief: accept or dispute each event, with a reason, say how it enters Bull, Base and Bear, and
   add any event the analyst finds itself (`catalysts`).

**Test plan, fixed now (no re-planning on individual results).**
- **(a) Discovery component test, known answers**, on design-touched names. Pass = at least 5 of
  6 capture the first-listed development:
  - AMD: Meta Muse / agentic-AI CPU demand (plus the neocloud CPU price rise of 09-17 and the $1T
    milestone);
  - GEV: the AI-slowdown selloff of 09-14 (plus the GLJ Sell initiation and guidance that backlog
    passes $200bn);
  - MU: a worsening memory shortage (the Intel CEO, 09-15);
  - NVDA: the Hugging Face acquisition (09-18);
  - FIX: data-centre backlog growth to $14.06bn and the pullback from its high;
  - DXC: falling revenue and estimates, a downgrade, the new partnerships.
- **(b) The E7 retest** on FSM, LAMR, LIND, UGI, GPOR and AU with the pre-registered A1/A2/A3
  and repeatability marks.
- **(c) The AMD/FIX regression check**, as pre-registered.
- (b) and (c) run only after (a) passes. If (a) fails, the discovery run is fixed and (a) re-run
  before anything else.

**Test (a), run 1: FAIL, 3 of 6.** Ran 2026-09-24, 18:58–20:28, on commit a77d133.

| Name | Score | What happened |
|---|---|---|
| AMD | pass | Meta Muse → agentic-AI → EPYC CPU demand; 4 events, all sourced to pages it read |
| GEV | pass | the 09-14 AI-slowdown selloff appears in its bear argument, not as a dated event |
| NVDA | pass | the Hugging Face acquisition, sourced to the article it read |
| MU | fail | **harness defect:** the final turn spent the whole 16,384-token cap thinking; no brief |
| FIX | fail | **scorer defect:** the rule wanted "data center"; the brief wrote "data-center" (record $14.1bn backlog, "heavily weighted to tech/data-center") |
| DXC | fail | **harness defect:** the JSON brief was invalid at character 4,240 and was discarded |

Four more defects surfaced during the run, and all are fixed:
- the renderer looped forever on AMD's brief;
- every sec.gov page failed with HTTP 403;
- HTML entities leaked into the text the model reads;
- a brief written just before midnight was invisible to the pack.

The fixes are in commits a157d99, a524a4a, 4bf6561 and 757d8cc (963 tests):
- the renderer;
- the midnight lookup;
- a discovery cap of 32,768 tokens, plus a one-time "write only the block" recovery with thinking
  off;
- the model's final text is now saved;
- sec.gov fetches carry the declared identity;
- an EDGAR submission starts at its first document;
- all HTML entities are decoded;
- a bounded JSON repair.

The official score of run 1 is the literal v1 score, 3 of 6. The scorer's defect is fixed in v2,
which also matches hyphenated spellings. v2 was written after run 1 was seen and before run 2. It
changes nothing else, and run 1 keeps its v1 score. Per the plan, (a) is re-run on all six names,
scored with v2 and the same bar: at least 5 of 6.

- **Run 2, first attempt.** Started at 20:31 on commit 757d8cc and stopped after AMD at 20:47.
  Its output is kept (`test_a_run2_aborted`), unscored.
- **Why it was stopped.** Run 1's fetch records showed two more fetch_page defects, fixed in
  05e7b3b:
  - 7 of 86 fetches were 404s on URLs the model re-typed from memory. On a 404, fetch_page now
    opens the search-returned address with the same host and article slug.
  - One site failed certificate verification. Certificates are now checked against certifi's
    bundle plus the Windows store.

  The restart lets (a) test the exact code that (b) and (c) will use.
- **Run 2 proper** started at about 20:49 on commit 05e7b3b, meant as the frozen code. It was
  stopped at 21:08 during MU, for two reasons:
  - **GEV lost its brief to a JSON defect** (a list closed with the wrong bracket).
  - **The operator asked why blocked pages are not replaced from other sources.** The fetch
    records supported doing it: 28 of 86 fetches had been refused (401/403), and AMD's first run 2
    attempt lost the Muse story that way. So this is a defect fix backed by the data, not a
    preference.

  AMD had finished: 5 events, all 5 read and verified, 7 pages. The partial record is in
  `test_a_run2_05e7b3b`.
- **Fixes in 52f93b5** (979 tests):
  - When a page is blocked, paywalled, or missing, fetch_page searches the headline and opens
    the same story from a legitimate free copy: a licensed syndicator, the same publisher, or
    another outlet's own reporting. It does not circumvent paywalls: no crawler impersonation, no
    mirror or archive sites.
  - Live, 5 of 6 blocked discovery pages resolved, for example Barron's Muse story → Yahoo
    Finance's.
  - The JSON repair now also handles wrong or stray brackets and cut-off blocks. As a last
    resort the model re-emits the JSON, and that fix is accepted only if it adds no events.
- **Run 3** started at about 21:10 on commit 52f93b5. **It is the deciding run for (a).** If it
  scores under 5 of 6, the defects go to the operator before anything else runs; there is no
  silent re-run.
- **Run 3 result (22:05): 6 of 6 on v2.** Every brief parsed, and no repair or recovery path was
  used.

  | Name | Events | Verified | Pages read | Notes |
  |---|---|---|---|---|
  | AMD | 5 | 5 | 5 | |
  | GEV | 8 | 3 | 10 | now names the 09-14 slowdown, the GLJ Sell and the $200bn backlog |
  | MU | 4 | 4 | 8 | |
  | NVDA | 5 | 5 | 7 | |
  | FIX | 5 | 5 | 6 | |
  | DXC | 3 | 3 | 4 | names the partnerships (LOXO, Arrive AI) |

  - The Fable review's replacement gate is also met: parses, at least 3 events, no unexplained
    move of 10% or more.
  - The review's human-read item is not met in full: AMD's Muse mechanism is the GPU/inference
    story, not the CPU thesis. The CPU link appeared in 1 of 3 discovery runs today.
  - Per the review (F2), the keyword score is plumbing evidence, not proof of discovery quality.
  - Record: `discovery_logs/test_a_run3`.

**Scoring for (b) and (c), fixed 2026-09-24 20:10 KST, before any retest or regression sample
existed** (scorer: `score_retest.py` in the session scratchpad).

1. **One change to a pre-registered criterion.** The reason is structural; no result prompted it.
   The pooled mark (at least 7 of 8 names within 15%, over Stage 2 plus the hold-out) can no
   longer be met, whatever the retest shows:
   - AMD's Stage 2 spread was 170%, before the fixes;
   - DXC and GEV never ran, because Stage 2 was stopped to fix defects.

   The repeatability mark therefore moves to the six retest names, with the same thresholds:
   - at least 5 of 6 names have a spread ≤ 15% (at most one name outside, as 7 of 8 allowed);
   - at least 90% of usable samples match their name's majority direction.

   The pooled 8 is still reported as first registered, with this caveat.
2. **Definitions.**
   - A usable sample is plausible, not truncated, and has an IV.
   - A sample's direction is the frozen 10% rule applied to that one sample: IV ≥ 1.10 × price is
     undervalued, IV ≤ 0.90 × price is overvalued, anything else is hold.
   - The spread is the run's published `spread_pct`. A name with fewer than 2 usable samples
     fails the spread mark.
   - A1 is as listed above, with two operational definitions:
     - "Base cash flow off the default without a reason" means `base_cf_basis` is not
       `owner_earnings_default` and `base_cf_reason` is empty.
     - "Quality warning ignored" means the pack prints an EARNINGS QUALITY or CASH-FLOW QUALITY
       line and the report uses none of a fixed word list (earnings quality, one-off,
       non-recurring, working capital, prepayment, float, normalise, non-operating, tax benefit,
       discontinued, and close variants).
   - A2 is met for a name when every usable sample names that name's development. There is one
     keyword rule per row of the table above:
     - LIND: White Desert or Echo Charlie;
     - LAMR: the raised guidance, or its figures;
     - UGI: Jefferies;
     - GPOR: J.P. Morgan, plus downgrade or Underweight;
     - FSM: West Africa, Côte d'Ivoire, Séguéla or Diamba;
     - AU: the 1-month drop, plus an estimate cut.

     The keyword result is the score. My reading of each report is reported alongside it and
     never replaces it. Each alternative also matches the text with letter-letter hyphens turned
     into spaces. This was added at 20:23, before any (b) sample, after the same gap cost FIX its
     test (a) match.
3. **A3 (reported, not gated).**
   - Bull ≥ price, or a stated reason.
   - The base IV is within [0.5× street low, 2× street high].
   - Years 1–2 revenue is within ±25% of the consensus path (current-FY and next-FY growth from
     the pack), or `guidance_deviation_reason` is given.
4. **(c)** is scored as pre-registered above. "No sample below 0.5× the discounted street low"
   uses the fail-fast's discount: street low ÷ 1.10.
5. **Cost.** (b) and (c) together are 24 valuation samples plus 8 discovery runs: roughly 16–20
   GPU hours.
   - One sample takes about 40 minutes. The AMD probe measured 38 minutes of generation (92,430
     tokens at 40 tok/s) against 1.4 minutes spent reading prompts.
   - 86% of the output is thinking, because the model runs at its maximum reasoning setting.
     The "high" requested is mapped to "xhigh" in the template.
6. **Order (changed 2026-09-24 ~21:20, before either ran):** (c) runs before (b), so AMD and FIX
   report within about 4 hours. The code is frozen and nothing is decided between the two, so the
   order does not affect either result.
   - **Checkpoint after AMD's 3 samples**, following the operator's "if results are outrageous, no
     point running the full run". The batch stops for diagnosis before FIX and (b) if either
     holds:
     - AMD's spread is over 50%;
     - any AMD sample is below 0.5× the discounted street low.

     Both bounds were fixed in advance. It is a stop rule for spending GPU hours, not a pass mark:
     (c)'s own criteria are unchanged.
   - **Hold (2026-09-24 ~21:30):** (b) and (c) wait for the Fable 5.1 cross-review the operator
     asked for, and for the operator's go-ahead.
7. **Follow-up after the gate, not now:** measure the analyst at "medium" reasoning on two names.
   *(Corrected after the Fable review: I had written "throughput roughly doubles". The
   repository's own August measurement found about 6% faster wall-clock, and medium invented a
   figure the pack held. Measure it; do not assume.)*

### E10. The valuation contract: growth of what (2026-09-24, from the Fable cross-review)

The operator asked for an independent review ("circling … losing my trust"). Fable 5.1 ran at max
effort and returned PROCEED WITH CHANGES; the full report is
`reports/PHASE_4_FABLE_CROSS_REVIEW_2026-09-24.md`. Its main finding (F1), which I verified:

- The desk compounds a **cash-flow** base by the rates it is given, and nothing said growth of
  what.
- The AMD probe used consensus **revenue** growth (+46.9%, +73.1%) on a $5.1B base. The base was
  an older year, chosen because of the EARNINGS QUALITY wording.
- Its "consensus plays out" case reached $12.96B of cash flow in year 2, against consensus
  next-FY net income of $25.41B. That is half of consensus before any judgement.
- The pre-registered (c) criteria would have **passed** the resulting $378.92 "avoid". Their
  "years 1-2 within 25% of consensus" check compared revenue growth.

**Decided 2026-09-24 ~22:15, before code** (commit fa846ca, 988 tests):
1. **Growth is growth of the cash flow.** Base years 1-2 start from consensus EPS growth, which
   carries margin change.
   - If EPS growth is unusable (a negative base, or above +150% off a trough): revenue growth
     plus a stated margin path, with guidance_deviation_reason.
   - Years 3-5 fade from next-FY revenue growth to the growth base-rate median by year 5.
2. **CONSENSUS-IMPLIED VALUE** (`tools/consensus_reference.py`), printed in SECTION 8. It is the
   analysts' own earnings path at our discount rate: the owner-earnings default base, years 1-2 at
   consensus EPS growth, years 3-5 as in rule 1, then 5 fade years to the terminal-g anchor, the
   COE anchor, and a Gordon terminal value. It is a reference, not a forecast or a target.
   - AMD on saved inputs: **$520.02**, with year-2 flow $28.3B.
   - The Fable review's replications ranged $554-663 at other discount inputs.
3. **Harness flags**, each requiring guidance_deviation_reason:
   - `years12_off_consensus_earnings`: (1+g1)(1+g2) outside 0.75-1.33× of consensus.
   - `base_far_from_consensus_implied`: the base IV outside 0.75-1.33× of the reference.

   Plus `years35_above_base_rate_p90`, information only. One tolerance, "more than a quarter away
   from consensus needs a reason", is used for both checks. It was not set to catch AMD: the
   ⅔-1.5× I first drafted would have missed the probe (0.73×), and the same ±25% already applied
   to years 1-2.
4. **EARNINGS QUALITY wording.** Interest on cash is real earnings. Subtract only one-offs, and
   never switch base because of this line alone.
5. **Deferred:** mid-year discounting (about 5-7%, uniform across names), with its own
   measurement later.
6. **Scoring** (`score_retest.py`, before any (b)/(c) sample; the prior version is kept as
   `score_retest_pre_e10.py`):
   - A1 adds the two consensus flags.
   - (c)'s "years 1-2 near consensus" now uses EPS growth.
   - Each sample reports IV/price, IV/consensus-implied value, and year-2 flow ÷ consensus next-FY
     net income. On the probe that last line reads **0.51**.

**Fable check of E10 (2026-09-24 ~22:20): APPROVED WITH CONDITIONS for (c) on AMD.** Blocking
conditions and how they were met (commit 730ffb4, 990 tests):
1. `PACK_REVISION` bumped 6 → 7.
2. `years12_ratio`, `base_to_civ` and `consensus_implied_value` are stamped on every sample and
   verdict, whatever reason the model wrote.
3. The run copy is at 730ffb4, and `depth_model` is the v31 model.
4. The expected AMD shape is written below, before the run.

Blocking before (b), not yet done: the reference is unavailable for MU (EPS growth +787% off a
trough) and for LIND (a negative EPS base). It must be built from consensus EPS *levels* when
growth is unusable.

Carriable:
- note the TTM-base timing bias in the pack line;
- align the p90 wording;
- no generous fallback when the revenue estimate is missing;
- add `reference_deviation_reason` at the next revision;
- document GAAP vs non-GAAP in the docstring;
- a Phase 6 preflight item: re-run enrich. All 289 production enrich records predate `estimates`.

**Expected AMD shape under E10, written 2026-09-24 ~22:30 before the run.**
- The consensus-implied value is **$520.27**. The band that needs no stated reason is
  **$390–$692** (0.75–1.33×).
- If the analyst follows consensus, the base will be about $450–$550, i.e. 0.73–0.89× the
  $614.61 price.
  - Under the frozen 10% rule that reads **overvalued**, or **hold** if the median is at or above
    $553.
  - The E5b momentum basis stays eligible (base/price ≥ 0.5, strong uptrend), so a quarter-size
    momentum position is possible.
- **Read a $450–$550 AMD as the design working:** consensus earnings, valued at our 10.45% cost of
  equity, against the price. A $615 price then says the market prices more than consensus at that
  discount rate (a lower rate, or a longer runway). It does not say the analyst failed.
- **What would count as failure:**
  - a base far below $390 without a reason (the old defect);
  - samples more than 15% apart;
  - the Muse / agentic-AI catalyst not named;
  - A1 flags.

**Two AI-momentum names for (b): the rule, written 2026-09-24 ~22:50 before the draw** (the
operator noticed that (b) holds no AI name; Fable's conditions apply):
- **Pool.** `stocks.json` in the screener publish clone (6,949 names), filtered:
  - industry is Semiconductors, Semiconductor Equipment & Materials, Computer Hardware,
    Electronic Components, or Communication Equipment;
  - market cap is at least $10bn;
  - momentum z is at least 0.5: the E5b eligibility bar, which is `mom_z_universe` =
    `tickers[sym].fct_z.momentum` in factor_scores.json. *(Wording corrected ~23:00 before any
    name was drawn. The first attempt read the file wrongly and found an empty pool; the rule had
    mislabelled the field "sector-neutral".)*
- **Excluded: every name touched in design,** meaning every ticker named in PHASE_4_AMENDMENTS,
  PHASE_4_ERROR_AUDIT_SUMMARY or STATUS:
  AAPL, AMAT, AMD, AMZN, ANET, ARM, ASML, AU, AVGO, BRBR, CAT, CDNS, CIEN, CLS, CMBT, COHR, COST,
  DELL, DK, DXC, ETN, FINV, FIX, FLXS, FRO, FSM, FUTU, GE, GEV, GOOG, GOOGL, GPOR, GRDN, INSW,
  INTC, IREN, KLAC, LAMR, LIND, LITE, LRCX, MPWR, MRVL, MU, NVDA, PWR, QFIN, SITM, SMCI, SNDK, STX,
  TER, TIGR, TREE, TSEM, TSM, TWLO, UGI, UMC, VICR, VLO, VRT, WDC.
- **Draw.** Sort the pool alphabetically, then `random.Random(20260926).sample(pool, 2)`.
- **Scoring.** The two names are reported beside GPOR/AU and never swapped into the pass mark.
  Each also reports base IV/price and year-2 desk flow / consensus net income (Fable).
- **Data prep counts as part of the cost:** enrich, research brief and caches for names outside
  the book.
- **Draw result (2026-09-24 ~23:00):**
  - 47 untouched AI-hardware names of at least $10bn.
  - 13 passed the momentum bar: ADI, APH, ASX, CSCO, HPE, HPQ, LFUS, P, QRVO, SANM, SMTC, VSAT,
    ZBRA.
  - Seed 20260926 drew **APH (Amphenol) and ADI (Analog Devices)**.
  - Output: scratchpad `ai_name_draw_20260924.txt`.

**(c) AMD sample 1 (2026-09-24 23:12). Joint review with Fable: sound, the design working.**
- **Numbers.** Base $514.48, which is 0.844× the $609.43 price and 0.989× the reference. Bull
  $842.15, bear $117.91. Verdict label `overvalued`, `position_basis` momentum (all six E5b
  checks pass).
- **Scenario inputs.** The base copies the reference path. Bull years 1-2 are exactly the
  consensus EPS highs, bear years 1-2 exactly the lows.
- **Flags.** No A1 flag. `years35_above_base_rate_p90` (information) and the annotation-only
  `ocf_multiple` fired.
- **Catalysts.** Muse is named, as inference/agent demand; the CPU link appears only as "the
  durable EPYC base".
- **Carriable items:**
  - net debt is a free input again (under 1% here; watch it on UGI and LAMR);
  - report the years-3-5 average as a number;
  - the TASK's "fetch what you rely on" was only partly followed (1 fetch; the OpenAI warrant
    terms left unverified).

**(c) AMD complete (2026-09-25 01:11): PASS on all six pre-registered criteria.**

| Sample | Base | Base / price ($609.43) | Base / reference | Bull | Bear | Label | Basis |
|---|---|---|---|---|---|---|---|
| 1 | $514.48 | 0.844 | 0.989 | $842 | $118 | overvalued | momentum |
| 2 | $509.99 | 0.837 | 0.980 | $933 | $90 | hold (self-label) | momentum |
| 3 | $464.47 | 0.762 | 0.893 | $933 | $71 | overvalued | momentum |

- **Pre-registered marks:** base spread 10.8%; A1 clean on 3/3; Muse named; years 1-2 on consensus EPS growth; bull above price; no sample below 0.5× the discounted street low.
- **Verdict:** overvalued, median $509.99, size quarter, position_basis momentum; pack revision 7; gate_test. The old probe gave $378.92.
- **Ungated lines:** bull spread 10.8%, **bear spread 66.8%**, 2 of 3 samples within 5% of the reference, year-2 flow / consensus NI 1.113.
- **Where the base spread comes from.** Sample 3 counted the OpenAI warrant (up to 160M shares) as dilution; its report puts the pre-dilution equivalent at about $510.
- **Samples 2 and 3 first tried a $4.64B base they derived themselves** before returning to the
  default. *(Corrected by Fable: this is not the pack's CASH BASIS line, which is $6.765B. It cost
  2-3 desk calls and about 15 minutes per sample; the published value is unaffected.)*
- **The frame differs:** firm with net debt in sample 1, equity in samples 2 and 3.

**Joint review with Fable (2026-09-25 ~02:45): (c) AMD PASSED; the design works as written down
before the run.**
- **Decomposition.** s1 − s2 = $4.49, which is exactly net cash per share (the frame). s3 is s2
  scaled by the warrant dilution (×1.6325/1.7925). With the base inputs pinned, the model's
  disagreement on the base is zero.
- **Reported line (b) must carry:** the analyst's remaining judgment is in bull, bear and the
  probabilities. Bull year-2 growth was the consensus high set on the consensus average (s1)
  versus high-on-high (s2, s3). Bear inputs vary: year 2 at the consensus low vs +5%, and WACC
  +150 vs +200 bp. So bear/price was 0.19 / 0.15 / 0.12.
- **Blocking before FIX:** none. FIX runs on the same frozen copy, 730ffb4, as E7 requires.
- **Blocking before (b)** (E7 rule-2 defects: free inputs the harness can show):
  1. **Shares.** The pack prints diluted shares plus known contingent instruments with their
     vesting terms. The contract gains `shares_basis` and `shares_reason`. The harness flags any
     share count that differs from the pack figure (today it flags only at ≥10%; s3 was 9.8%),
     and flags a dilution applied in a scenario whose premise is non-vesting. s3 applied the
     warrant in its own bear case.
  2. **Net debt / frame.** One net-debt figure including investments becomes the default, with
     a reason field for any other. The frame is reported per sample. There were four different
     net-cash values across four samples for one filed fact.
  3. **Bull/bear years 1-2.** The ratio to the consensus EPS high/low is stamped per sample, with
     `scenario_deviation_reason`. Reported, not gated.
- **Carriable:**
  - `report_verdict_mismatch` per sample, not only on the medoid (s2's "hold" left no trace);
  - wording: start from the default base, not a trial one;
  - per-sample bear/price, its probability and the WACC shock in the results table.
- **For the operator, plainly:**
  - Base agreement is now by construction, so the registered spread mark is weak evidence from
    here on.
  - The next dispersion to discipline is bull/bear years 1-2.
  - The system will not call AMD cheap at $609; it rides it small. A larger AI sleeve is a
    Phase 6 sizing decision.
  - Muse is caught as an inference story; whether the CPU thesis appears still depends on the
    pages the discovery run happens to read.

**Added before any FIX or (b) sample (2026-09-24 ~23:35). Reported and ungated; the
pre-registered marks are unchanged.** Where the reference exists and the base copies it, a base
spread ≤ 15% is nearly automatic. So `score_retest.py` now also reports, per name:
- bull spread, bear spread and the probability-weight range;
- `position_basis` agreement;
- how many samples sit within 5% of the reference;
- per sample: bear/price, the probabilities, the years-3-5 average, and the desk's net debt.

Names without a reference (MU, and LIND before 9902a92) are reported separately: for them the
base spread is the real test. The previous scorer is kept as `score_retest_pre_ungated.py`.

**Dry-run acceptance before any GPU run:**
- On the probe's own numbers the new flags fire: tested.
- The real AMD pack prints the reference line with real anchors.
- The Fable reviewer checks the fix.
- Only then (c) on AMD, 3 samples (about 2 hours), reviewed jointly with Fable (operator,
  2026-09-24 ~22:00: "Consult Fable Max whenever you review the AMD, FIX, six stock plus two AI
  stock runs").

### E11. The pack reads the top company stories (operator, 2026-09-25 ~03:00)

The operator asked why the Muse → CPU angle depended on discovery instead of being in the pack.
It did: RECENT COMPANY NEWS held headlines only, and only a model run choosing its own searches
ever read an article. AMD's pack had Reuters' Muse headline but not its text, and the TrendForce
CPU piece was never among the company-news results.

**Built (commits 3db4662, 293d34e):**
- When the pack is built, code reads the five most recent stories through fetch_page, with the
  free-copy fallback when a page is blocked.
- Each story gets about 600 characters from its lede: the first real sentence that names the
  company or shares two headline words.
- Page furniture, subscription walls and non-English prose are skipped.
- The excerpts are cached with the day's news, and the pack prints each under its headline with
  the host actually read.

**Live results:**
- AMD: 4-5 of 5 excerpts, including the Reuters Muse text via a free copy.
- LIND: its acquisition text.
- UGI: German and Indonesian pages refused.

**Known limit:** the headline list keeps non-English and ticker-collision rows for short tickers
(UGI).

### E12. Shares, net debt and bull/bear pinned (pack revision 8, 2026-09-25)

These are the (b)-blocking items from the joint AMD (c) review. Once the base inputs were pinned,
the base-case disagreement between samples was zero; the whole 10.8% spread came from two free
inputs. Commit da5f43b:
1. **Shares.** Use SECTION 2's count everywhere. A contingent instrument may be added only in
   the scenarios where it vests, with `shares_basis` and `shares_reason`. Flags:
   `shares_off_pack_without_reason` (more than 1% off) and `dilution_in_bear`.
2. **Net debt.** SECTION 6 prints one NET DEBT default (total debt − cash − short-term
   investments) for the firm frame, with `net_debt_reason` for any other value. Flag:
   `net_debt_off_default_without_reason`.
3. **Bull and bear.** Years 1-2 are anchored to the consensus EPS high/low path. The ratios
   `bull_years12_ratio` and `bear_years12_ratio` are stamped per sample (reported, not gated),
   with `scenario_deviation_reason`.
4. **Carriable items:** `report_verdict_mismatch_sample` per sample, and "start from the default
   base".
5. **Scorer:** A1 adds `shares_off_pack_without_reason`, `net_debt_off_default_without_reason`
   and `dilution_in_bear`. This was written at 06:10, before any (b) sample.

**Dry runs, no GPU.**
- `scenario_checks` on AMD's three real samples reproduces the review exactly:
  - s1: bull 1.081, bear 0.923, firm frame;
  - s2: the "hold" self-label is flagged;
  - s3: shares 1.098 in every scenario, flagged twice.

  The first version stamped the base path for bull/bear. The dry run caught it; it is fixed and
  covered by a regression test.
- Revision-8 packs for UGI, LIND and AMD build cleanly:
  - net debt $6.31B, $0.41B and −$8.20B;
  - LIND's reference ($19.24) comes via EPS levels.

Tests: 1007.

**Fable's pre-(b) check (2026-09-25 ~05:50): APPROVED WITH CONDITIONS.** Fable reproduced the dry
runs exactly. Two blocking items, fixed in 6a4b94e (1010 tests):
- **F1.** LAMR and LIND have one next-FY analyst (high = low = average). Anchoring bull/bear there
  would force Bull = Base = Bear. The anchor now needs 3 or more analysts; with fewer, the analyst
  states its own range and the stamps read "no consensus range". Scenarios are matched by name
  before value.
- **F2.** A multi-company headline brought Royal Caribbean's fleet paragraph into LIND's news. The
  two-headline-word rule now applies only when the headline names the company; otherwise the
  sentence must. For short tickers the ticker stands in.

LIND's pack was rebuilt: the paragraph is gone, and the acquisition excerpt carries the deal
terms.

Carriable:
- one share figure (the filed diluted count) as the default in both places;
- the UGI reference caveat: a utility's growth capex depresses owner earnings, so read base/price
  beside base/reference;
- the A1 additions: judged legitimate.

(b) runs on 6a4b94e after FIX (c) finishes on 730ffb4, reviewed jointly as names complete. For
LIND and LAMR the bull/bear construction is read by hand. *(Superseded by E13: (b) runs on
7ea3d4a.)*

### E13. One anchored terminal, and the equity frame by default (pack revision 9, 2026-09-25)

**FIX (c) samples 1–2, joint review with Fable (~07:15–07:50).**
- Both samples used the same base ($1.186B owner earnings, float excluded), growth path, COE
  8.98%, terminal g 3.75%, fade and shares. Their Gordon legs are the same valuation: $1,915.27 −
  $1,891.00 = $24.27, which is exactly net cash per share ($0.843B / 0.0352B).
- s1 published $1,915.27 (undervalued). s2 published the exit leg at 16× ($1,650.07, hold). Its
  Gordon leg, $1,891.00, is the consensus-implied value within 0.1%.
- The spread is therefore at least 16.1% whatever sample 3 does: 12.7 points from the exit
  multiple and 1.3 points from the frame. **FIX's pre-registered spread mark fails.** The float
  mark passes on both samples. FIX is not re-run on the fix (rule 2).

**Defect 1: the exit multiple was a free input.** Fable ruled it a defect under rule 2, on two
grounds the harness can show:
- **Missing data.** The charter derives terminal multiples from the net capitalization rate and
  verified peer comps, but the pack has no EV/FCF peer data (SECTION 8.5 holds trailing P/E only).
  s2 calibrated 16× to a terminal P/E and tagged it [Assumption]. The desk's in-band check compared
  it with a P/E band the model itself passed.
- **Anchor override.** The desk applies the exit multiple after the flow has faded to terminal_g,
  so any multiple other than (1+g)/(r−g) states a different terminal growth. 16× at 8.98% implies
  2.57% against the 3.75% anchor. The desk publishes the exit leg whenever one is passed.
- **Every P4 run shows the pattern:**
  - AMD (c): 15× against the implied 15.49× (−20 bp); the two legs are within 2%.
  - AMD probe: 20× against 15.49× (+144 bp), worth +18.6% of value.
  - FIX s1: 19.84×, equal to the implied multiple.
  - FIX s2: 16× (−118 bp).

**Defect 2: the frame.** I raised this as a follow-up and Fable ruled it blocking.
- Every flow the pack prints (owner earnings, the cash basis, the FY owner CF column) is after
  interest, which makes it an equity flow. The pack anchors a cost of equity, not a WACC.
- A firm-frame valuation on those flows subtracts the debt a second time, at a rate the analyst
  invents.
- On FIX and AMD, which hold net cash, the effect is about 1%. On UGI (net debt $6.3B), a 50 bp
  WACC choice moves the value by 25–30%; even a correctly built firm frame moves about 30% per
  50 bp.
- The samples chose the frame roughly 50/50: AMD s1 and FIX s1 used the firm frame, the others the
  equity frame.

**Fix: commit 7ea3d4a (1023 tests), written before any (b) sample.**
1. The desk returns `exit_implied_terminal_g` = (M·r − 1)/(M + 1) and the rate it applied, and
   prints both next to each scenario's Gordon leg.
2. SECTION 1.5 prints the DEFAULT EXIT MULTIPLE, (1 + g)/(COE − g) at the anchors: FIX 19.84×,
   UGI 26.10×, LAMR 21.92×.
3. **TASK "Terminal Multiple".** The exit multiple defaults to the value in item 2; at a scenario's
   different rate, it defaults to the desk's Gordon multiple for that scenario.
   - A multiple whose implied terminal growth is more than 0.5 points from the anchor needs
     `terminal_multiple_reason`, with dated peer EV/FCF evidence.
   - A P/E ratio is not an EV/FCF multiple.
4. **TASK "Valuation Frame".** The equity frame is the default. The firm frame needs:
   - a pre-interest flow (`interest_addback`, from SECTION 5's filed interest);
   - a WACC built from the COE anchor (`wacc_reason`);
   - SECTION 6's NET DEBT.

   The OWNER EARNINGS, CASH BASIS and NET DEBT lines say so.
5. The desk schema's example multiple ("16.0 for 16x") is removed. FIX s2 chose exactly 16.0; that
   is one data point, and not claimed as anchoring.
6. **A1 flags:**
   - `exit_multiple_off_default_without_reason`, on the published base. The threshold is 50 bp of
     implied growth (Fable's preferred form), about 10% of the multiple and about 6.5% of value,
     under half the frozen 15% tolerance.
   - `firm_frame_on_equity_flow`: the firm frame with no interest add-back.
   - `firm_frame_without_wacc_reason`.
   - `interest_addback_above_filed`: an add-back above the latest filed interest expense.

   Stamped per sample, reported and ungated: `base/bull/bear_exit_g_gap_bp` and
   `base_exit_to_gordon_multiple`.
7. **Scorer.** A1 adds the four flags, and the ungated lines show the frames and the base exit
   gaps. The previous scorer is kept as `score_retest_pre_e13.py`. Written ~07:45, before any (b)
   sample.

**Three departures from Fable's wording, sent back to Fable for a final check:**
- **Add-back test.** Fable's version compared base_cf − interest_addback with the pack's
  after-interest figures. That would flag legitimate custom bases, such as a multi-year average.
  The flag instead checks that an add-back exists and does not exceed the latest filed interest
  expense.
- **Surplus cash.** Fable proposed a `surplus_cash_reason` field. The desk refuses net_debt in the
  equity frame, so the field would need a new desk input, which reopens both a free input and the
  double count. The pack states the limitation in one sentence instead. Revisit after the gate if
  a cash-rich name shows it matters.
- **Rate check in the firm frame.** Fable proposed comparing the COE inside `wacc_reason` with the
  anchor, but `wacc_reason` is free text. The existing `coe_minus_anchor` stamp already records the
  desk rate minus the COE anchor, which in the firm frame is the WACC gap.

**Dry runs, no GPU.**
- The new flags on the saved desk calls:
  - AMD probe: flagged for both the exit multiple (+144 bp) and the firm frame.
  - AMD (c) s1 and FIX s1: flagged for the firm frame only.
  - AMD s2/s3: clean (exit −20 bp).
  - FIX s2: flagged (−118 bp).
- Revision-9 packs for UGI and LAMR build with the new lines.
- (c) is not re-scored on the new flags.

**Expectation for (b), written before it runs (Fable).** Once the base inputs were pinned, the
samples stopped disagreeing on the flows: E10–E12 did this on AMD (its residual came from
dilution) and E13 on FIX (its residual came from the exit multiple). The remaining dispersion
should sit in bull/bear, the probabilities and the basis call.

What the E10–E13 pins predict for (b) (Fable's condition), recorded ~07:50 before the first
sample. This is reported, not scored:
- On every name whose pack prints a CONSENSUS-IMPLIED VALUE, each base is within 0.75–1.33× of it,
  or the sample gives a `guidance_deviation_reason`.
- Every sample uses the equity frame, unless `interest_addback` and `wacc_reason` appear.
- Every exit multiple is within 50 bp of implied growth, or the sample gives a
  `terminal_multiple_reason`. The bear legs are watched for the same (stamped only).
- Base spreads come mainly from bull/bear and the probabilities, not from base-case inputs.
- If a base spread over 15% appears, the first diagnostic is the Gordon-leg comparison in one
  frame.

**Fable's final check (~07:50): GO, with one condition before launch.** My revision-9 dry-run packs
had been built in the dev worktree, which holds no estimate records. So the reference line, the
E12 bull/bear anchor and the E13 lines had not been exercised on a pack with estimates. Before
(b), the packs are rebuilt at 7ea3d4a in the dry worktree, which holds the (b) names' records, and
checked. Fable accepted the three departures above.

**(c) FIX complete (07:53): FAIL on the spread mark, PASS on the float mark.**
- Samples: $1,915.27 / $1,650.07 / $1,801.47 against a $1,643.39 price.
  - Spread 16.1% (mark ≤ 15%): ✗.
  - All three used the owner-earnings base, which excludes the float: ✓.
  - A1 clean 3/3.
  - Directions: undervalued, hold, hold. Verdict HOLD, size quarter.
- s3 used an 18× exit multiple: 3.24% implied growth, −51 bp, which E13 would flag.
- Taken in one frame, the three Gordon legs are $1,915.27, $1,915.27 and $1,919.36, all within
  0.2%. The whole spread is the exit multiple (19.84× / 16× / 18×) plus the frame, which E13
  pins after the run. FIX is not re-run (rule 2).
- Fable agreed this as the record. It noted that s3 sits at the edge of the 50 bp rule, so near-miss
  gaps in (b) are to be read by hand, not by the flag alone.

### E14. Labelled fallbacks for the owner-earnings default (2026-09-25 ~08:00, before any FSM, GPOR or AU sample)

**Found by Fable's pre-launch condition, not by a result.** The revision-9 packs were rebuilt at
7ea3d4a in the dry worktree, which holds the (b) estimate records.
- UGI, LAMR, LIND, APH and ADI print everything.
- FSM, GPOR and AU print "OWNER EARNINGS: not available" and no CONSENSUS-IMPLIED VALUE:
  - FSM and AU are 40-F/20-F filers, so no TTM record exists.
  - The screener's capex extractor (`stock-screener/scripts/build_fundamentals_history.py:88`)
    maps only `PaymentsToAcquirePropertyPlantAndEquipment`. So GPOR (oil-and-gas capex tags), FSM
    and AU have no capex in any year.
- Three of the six retest names therefore had no default base: the base cash flow was a free input
  again, which was FIX Stage 1's failure mode.

**Fix (commit faf2f87, 1028 tests; approved by Fable with two conditions, both met).** Live path
only, since the vendor figure is today's and the point-in-time path never uses it.
- Net income: TTM, else the latest fiscal year's filed figure.
- Capex, in order:
  - TTM;
  - else the latest fiscal year's filed figure;
  - else the vendor's latest-annual capex (financials `Capital_Expenditure`, yfinance's annual
    cash-flow statement, with its fetch date). It is stored negative and is refused if positive
    (Fable's condition 1).
- The line names each source. The CASH BASIS line uses the same capex source.
- An `owner_earnings_source` token is printed when a fallback is used, and the harness stamps it on
  every verdict ("ttm_filed" otherwise; Fable's condition 2).
- On the complete names the vendor figure tracks our TTM capex: UGI 0.837 vs 0.875, LAMR 0.181 vs
  0.189, ADI 0.534 vs 0.541.
- Resulting defaults: FSM $0.324B, GPOR $0.273B, AU $4.198B.
- **The five complete packs are byte-identical before and after**, so the batch split below changes
  nothing for them. The screener extractor fix is deferred to Phase 6: it lives in another
  repository, and pushing it deploys the public site.
- **FSM, GPOR and AU are E14's first use**, so their A1/A3 results are read with that in mind.

**Batch split, recorded before the first sample.**
- (b) part 1: UGI, LAMR, LIND, APH, ADI on 7ea3d4a, started 07:53:44.
- UGI's live pack (08:00:45) prints the reference ($42.08), NET DEBT, the DEFAULT EXIT MULTIPLE and
  the catalyst brief, which meets Fable's condition.
- (b) part 2: FSM, GPOR and AU, on the E14 commit, after ADI. The run copy moves only between names.

**Open before part 2: the reference on the three commodity names.** With a base, the E10 reference
computes, but it is not credible for these names:

| name | reference | ratio to price | street targets |
|---|---|---|---|
| FSM | $75.60 | 6.2× | $14.50 |
| GPOR | $564.78 | 3.6× | $186–253 |
| AU | $463.69 | 4.5× | $76–140 |

There are three causes:
- consensus EPS growth on spot commodity prices;
- a years 3–5 fade toward the conditional base-rate median;
- a perpetual terminal on depleting assets (AU's capex is below its D&A).

The frozen fail-fast fence (0.5× discounted street low, 2× discounted street high) separates the
names cleanly. All five part-1 references are inside it, as are AMD's and FIX's; all three
commodity references are outside it. Proposed E15: a reference outside the fence is "not used" and
its number is not printed. It is with Fable for a ruling before part 2.

### E15. A consensus reference outside the fail-fast fence is not used (2026-09-25 ~08:10, before any FSM, GPOR or AU sample)

**Fable's ruling (~08:05): approved, with the direction printed and a verdict stamp.**
- **The line.** When the reference lies outside the fence, the line reads "CONSENSUS-IMPLIED VALUE:
  not used — the consensus path carried forward at our discount rate lands above (below) the fence
  [$lo, $hi] built from the street's targets". The number itself is never printed.
  - "Above" tells the analyst the market treats these earnings as finite or cyclical.
  - "Below" would say the market pays for more than the consensus path.
- **The fence.** It is the fail-fast's own: the same band (`valuation_backbone._consensus_band`) and
  the same 10% discount. It is frozen under E7 rule 1, so there is no new threshold.
- **The stamp.** `consensus_reference_status` goes on every verdict: `used`, `outside_fence_above`,
  `outside_fence_below` or `not_available`. `base_far_from_consensus_implied` applies only to `used`.
- **Commit 92b42a9, 1033 tests.** The packs were rebuilt: the five part-1 packs are byte-identical,
  and FSM, GPOR and AU now read "lands above the fence" ([$6.59, $26.36], [$84.55, $460.00],
  [$34.55, $254.55]).
- **Caution recorded.** FSM's fence rests on one analyst's target ($14.50). A fail-fast on it is a
  flag, not a score (E7).

**Run.** Part 2 (FSM, GPOR, AU) runs on 92b42a9 (E14 + E15). `run_b2.sh` starts it only when part 1
ends cleanly: a part-1 stop is a defect to diagnose. The run copy moves only between the two parts.

**Pre-registered now, before part 2 and before any (b) result:**
1. **Commodity names (read, not scored).**
   - FSM and AU are read for a `base_cf_reason` that addresses depletion: AU's D&A ($2.473B) is
     above its capex ($1.449B), so the default counts about $1.0B of depletion as cash.
   - They are also read for a `cycle_evidence` that addresses spot prices.
   - `years12_off_consensus_earnings` will fire on FSM (+111.8%) and AU (+60.2%) unless a reason is
     given. A substantive mid-cycle reason counts as clean and a boilerplate one as the flag, by a
     human read reported beside the keyword score.
   - If the analyst does its job, expect `overvalued` or `hold` on these three. The price sits far
     below the consensus path's perpetuity value but near the street's mine-life values.
   - GPOR's default ($0.273B) sits below its FY2025 net income because the vendor capex ($0.528B)
     exceeds the company's 2026 guidance ($430M, in the pack). The analyst may adjust it with a
     reason.
2. **After (b), for all names: the reference fade rule.**
   - The years 3–5 target becomes `min(conditional median, next-FY revenue growth)`, so the path
     never rises after year 2. Today GPOR's path goes +5.9 → +10.5 → +15.1% and AU's +11.8 → +14.9
     → +18.0%, toward the conditional median.
   - The affected references are to be recomputed and reported beside the originals.
   - AMD's reference also depends on this convention: $520 at the conditional median, against about
     $429 at the size-bucket median (Fable's sensitivity).
   - It is not changed mid-batch, because LAMR is running on the current convention.
3. **After (b), on a new draw: the treatment of depleting assets.**
   - maintenance capex at least equal to D&A for depleting assets;
   - a mine-life terminal instead of a perpetuity;
   - a cyclical-aware reference.

   A "D&A exceeds capex" pack note is not added mid-batch: it would also fire on LAMR (real-estate
   D&A), which is already running.

### E16. Two tool-layer defects from UGI (b) sample 1 (2026-09-25 ~10:00)

**What happened.** UGI s1 finished its desk work cleanly by 08:42:
- equity frame, rate 7.72%;
- the default 26.1× exit multiple (0 bp gap);
- owner-earnings base $0.357B;
- base value $42.08, equal to the reference.

It then spent about 40 minutes on two defects:
1. It fetched a signed storage link five times. The link's key and signature were masked with "…"
   (`OSSAccessKeyId=LTAI5t…QVZr`). Every attempt failed with `'ascii' codec can't encode character`,
   an error the model could not act on. The "…" did not come from the harness (Fable checked: the
   search results carry full URLs), so the model copied a masked link from page text.
2. It re-read the same pages: one earnings-call transcript 4 times and three other pages twice each.
   Each repeat was a cache hit returning the same first 9,000 characters.

**Fix: commit da8e2fa (1036 tests), tool behaviour only.** No pack, instruction or valuation input
changes.
- A URL containing "…" is refused with a plain reason. Other non-ASCII characters are
  percent-encoded.
- A second fetch of the same URL in the same sample gets a note of what the first fetch gave (its
  length or its failure) instead of the page. It still counts against the budget and as a repeat.
  The note carries no `chars`, so the discovery run's URL verification counts only real fetches.

**Batch versions (final record).**
- **UGI:** all three samples on 7ea3d4a (E13). It exposed E16 and is not re-run on it (rule 2).
- **The other seven** (LAMR, LIND, APH, ADI, FSM, GPOR, AU) run on da8e2fa (E13+E14+E15+E16).
  E14 and E15 leave the LAMR, LIND, APH and ADI packs byte-identical, so for those four the only
  difference from UGI's code is E16's tool behaviour. For FSM, GPOR and AU it is their first use of
  E14–E16.
- **Switch mechanism.** Only the part-1 loop's bash was stopped; UGI's own process continues.
  `run_b3.sh` waits for that process to exit, scores UGI under the part-1 stamp, stops if UGI ended
  without a verdict, then checks out da8e2fa and runs the seven names. Fable approved the plan.
- **Timing.** UGI's s2 and s3 may repeat the same pattern. The wasted minutes per sample go into
  the results table, so the effect of E16 on the other seven can be shown (Fable's note).

### (b) results, name by name (joint review with Fable as each completes)

| name | code | base IVs vs price | spread | directions | A1 clean | A2 | verdict | ungated | minutes per sample (repeats) |
|---|---|---|---|---|---|---|---|---|---|
| UGI | 7ea3d4a | $42.08 / $42.12 / $42.12 vs $36.37 | 0.1% ✓ | undervalued ×3 | 3/3 | ✓ (Jefferies) | UNDERVALUED, half size, conviction 10 | bull 4.0%, bear 28.3%; equity ×3; base = reference ×3 | 116 (8 of 21) / 31 (0) / 51 (0; report rescued by continuation) |
| LAMR | da8e2fa | $164.61 / $166.36 / $169.02 vs $143.71 | 2.7% ✓ | undervalued ×3 | 3/3 | ✓ (raised AFFO guidance) | UNDERVALUED, half size, conviction 11 | bull 11.2%, bear 10.5%; equity ×3; base/reference 0.87–0.90, each with a stated reason | 67 (0; report rescued) / 37 (1 of 6) / 35 (0) |
| LIND | da8e2fa, 2 samples | $19.14 / $19.13 vs $27.58 | 0.1% ✓ | overvalued ×2 | 2/2 | ✓ (White Desert / Echo Charlie) | OVERVALUED, quarter size (momentum basis), conviction 7, Kelly 0 | bull 72.8%, bear 75.8% (no consensus range); equity ×2; base = reference (EPS-levels) ×2 | 44 (0) / 61 (0) |
| APH (AI draw) | da8e2fa, 2 samples; restarted after the operator's GPU pause (16:47–18:35) | $88.15 / $88.13 vs $83.08 | 0.0% ✓ | hold ×2 | 2/2 | n/a (AI draw: no keyword rule) | HOLD, quarter size, conviction 9, Kelly 6.48% | bull 14.1%, bear 14.2%; equity ×2; base = reference ×2; s2 self-label "undervalued" at 1.061× (`report_verdict_mismatch_sample`) | 110 (20 of 25: the Bing loop) / 32 |
| ADI (AI draw) | da8e2fa, 2 samples | $238.02 / $399.32 vs $382.61 | **67.8% ✗** | overvalued / hold (split) | 2/2 | n/a | HOLD (high-dispersion quarantine), quarter size, momentum ×2, conviction 10 | bull 103.5%, bear 65.6%; s1 FY cash-basis base + CF growth +28/+21% with reasons; s2 = reference exactly | 39 / 39 |
| FSM | da8e2fa, 2 samples; first use of E14/E15 | **$64.83 / $63.06 vs $11.635 (5.6×)** | 2.8% ✓ | undervalued ×2 | 2/2 | ✓ | **UNDERVALUED, half size, Kelly 24.75%**, conviction 9. Flags: MoS +442–457% beyond 150%, 4.8–4.9× the analyst high, 4.6× the 52-week high | bull 6.8%, bear 16.8%; reference withheld (E15); base "other" (annualised H1 FCF $0.50B) | 83 (3 of 14) / 35 |

| GPOR | da8e2fa, 2 samples | $409.92 / $425.00 vs $156.22 (2.6–2.7×) | 3.7% ✓ | undervalued ×2 | **0/2**: s1 `bear_above_price_without_reason`; s2 not desk-backed | ✓? | **UNDERVALUED, half size, Kelly 24.75%**, conviction 10. Flags: MoS +162–172% beyond 150%, 1.8× the analyst high | s1 pinned exactly, default exit multiple 23.8×; **s2 made zero tool calls** (turn 1 hit the output cap while thinking; the forced report was hand-computed and rescued by continuation) and was still counted as usable | 48 (3 of 16) / 34 |

| AU | da8e2fa, 2 samples | $237.92 / $321.44 vs $98.64 (2.4–3.3×) | **35.1% ✗** | undervalued ×2 | 2/2 | ✓ | HOLD (high-dispersion quarantine), quarter size, Kelly 24.75%, conviction 9.5 | bull 18.2%, bear 33.0%; the spread is s1's terminal-g override (2.5% vs the 3.75% anchor) plus a steeper fade, with a reason | 33 / 47 |

### (b) verdict (2026-09-26 06:08; Fable's batch-level read, ~06:30)

**Score as pre-registered: PASS.**

| mark | needed | result |
|---|---|---|
| spread ≤15% | ≥5 of 6 | 5/6 (AU ✗) |
| direction match | ≥90% | 100% |
| A1 clean | ≥90% of usable | 93% of 14 (GPOR s2 ✗) |
| A2 | ≥5 of 6 | 6/6 |

- Hold-out alone (FSM, LAMR, LIND, UGI): spreads 4/4, A2 4/4.
- AI names, reported separately: APH ✓, ADI ✗.
- The pooled 8 as first registered cannot be met (see E9).

**How to read it, in order:**
- **(a) The pass stands, with its scope:** the hold-out carries it.
- **(b) The GPOR pass is hollow.** Under the desk-backed definition the spread mark reads 4/6 and
  **fails**.
- **(c) Where the design agrees with itself, it also agrees with the street.** Five names sit
  inside the street range at or near the consensus path: UGI, LAMR, LIND, APH and ADI's pinned
  sample.
  - Every remaining disagreement traces to a named knob: dilution, exit multiple, frame, base period,
    terminal g.
  - Where it fails, it fails structurally. The three commodity names come out at 2.4–5.6× price,
    because the model has no finite-life or mid-cycle concept.
  - This is progress over Stage 2 (AMD 170%, undiagnosed). It is also proof that repeatability was
    bought by pinning inputs. The analyst's own judgment now shows only in bull, bear, the
    probabilities and the basis call.
- **(d) E18 reference bias.** Fast-grower references ran 9–35% high. AMD's (c) base carried +23%.
- **(e) The gate gap (Phase 6 blocker).** It also ignores `desk_not_used` and the rescue marker.
- **(f) The research layer is broken** (E17).
  - 42% of search results share no token with their query, and there were two loops.
  - 4 of 24 samples hit the 81,920 context window; one of them lost its desk.
- **(g) What decides the direction.** Six of eight directions are decided by the MRI cost-of-equity
  anchor and the fade convention; LAMR and APH flip within 100 bp. That is the design, and it is what
  "our value" now means.

**Fable's one-paragraph truth.** Phase 4 has turned an unrepeatable analyst into a repeatable one by
pinning what the model is told. The pins hold on ordinary businesses, where its value is the consensus
earnings path at the MRI cost of equity and lands inside the street's own range. It has not yet shown
correctness where the pins do not reach:
- cyclicals and depleting assets come out at 2.4–5.6× price and read as buys;
- the reference that anchors fast growers is 9–35% high, from a period mismatch;
- one sample entered a verdict with no desk behind it;
- the actionability gate would pass all of that to the paper book and, if un-halted, to KIS.

The momentum sleeve fires as designed on AMD, LIND, APH and ADI, and was dropped once by a
resolution defect. None of this is the model misbehaving; all of it is contract, data and harness,
each with a fix on the list below. **The Phase 4 gate is not passable yet.**

**AU (Fable).**
- The whole 35% is one knob: s1 cut **terminal g** to 2.5% (from the 3.75% anchor) and steepened the
  years 3–5 fade, with a reason. s1's first desk call on the pinned path gave $321.15, the same as s2.
- E13 pinned the exit multiple but not `terminal_g` itself, so the desk accepts any value unflagged.
- AU is priced like about 12 years of next year's cash flow: the same finite-life read as GPOR.

**After-(b) plan, in priority order.**

*Phase 4 gate blockers:* fix, dry-run on the saved (b) records, then test on a new draw.
1. **E18.** Period-consistent reference, and a level-based years-1–2 check. Needs a PACK_REVISION.
2. **Harness.**
   - Desk-backed usability rule: a desk-less base IV is not basis; its flags are kept.
   - Context-window fix: a 32k per-turn cap on tool turns, a desk-only recovery turn, and a
     report-turn reservation.
3. **Terminal-g pin (AU).** Stamp `terminal_g_gap_bp`, flag
   `terminal_g_off_anchor_without_reason` beyond 50 bp, and widen the field to `terminal_reason`.
   Same revision.
4. **`depth_gates` v3.** Reasons `outside_street_fence` and `mos_beyond_150pct`, plus
   `desk_not_used` and the rescue marker. Small; also required for Phase 6.
5. **Scorer, pre-registered before the draw.**
   - desk-backed usability;
   - level-based A3;
   - `bear_above_price_without_reason` into A1;
   - rescue and terminal-g columns.

*Phase 6 preflight blockers:*
6. **Depleting and cyclical assets.**
   - A finite-life terminal.
   - A mid-cycle base from the P3.7 window.
   - Sustaining capex ≥ D&A.
   - Growth capex for regulated utilities.

   Needs a revision and its own new draw. Until then the fence gate keeps those names
   non-actionable. The book holds such names (FRO, INSW, DK, VLO, miners), so Phase 6 cannot start
   without it.
7. **Basis and sizing.** APH's basis is resolved from valid votes; Kelly never sizes a hold.
8. **E17 code.** A1 (the SearXNG repair) is ops and can go first once the operator agrees.

*Carriable, bundled into the same revision:*
- the 10% band wording;
- `reference_deviation_reason`;
- one share figure;
- the "owner CF" column renamed;
- the EPS analyst count;
- the excerpt furniture list;
- a TTM-lag freshness line.

*Revision ruling.* One PACK_REVISION bump (10) covering items 1, 3 and 6 plus the carriables,
presented to the operator as a single decision under non-negotiable 7.

*Next GPU test.*
- Items 1–5 first, all dry-run on the saved (b) records:
  - the E18 recompute for the eight names;
  - GPOR s2 under the usability rule;
  - GPOR s1/s2 under the window rule;
  - FSM, GPOR and AU under the gate;
  - AU s1 under the terminal-g flag.
- Then a **new rule-based draw**: two untouched names, one fast grower with a mid-year TTM and one
  steady name, 2 samples each (about 3 GPU hours), with the pre-registered scorer.
- A commodity name only once item 6 exists.
- Medium versus xhigh (with the truncation rate) afterwards.

### Operator rulings after (b) (2026-09-26 ~06:30)

1. **Item 6, as Fable wrote it, is curve fitting** (operator: "unless you fit for all industry
   types"). Special treatment for `commodity_cyclical` industries, designed after three commodity
   names failed, is the ticker-patching non-negotiable 2 forbids. It is **withdrawn in that form**.
   It is replaced by a universal treatment, applied to every company from its own filed data with no
   industry labels:
   - a through-cycle base beside the current one;
   - growth paid for by reinvestment at the company's own return on capital, in the terminal;
   - excess returns fading over a period set by the company's own record.

   It is to be designed with Fable. It is tested first on the whole book by sector (it must move
   peak-cycle and low-return names and leave steady compounders roughly unchanged), then on a new
   draw across all sectors. It gets its own later PACK_REVISION.
2. **PACK_REVISION 10 approved**, covering:
   - item 1, the E18 period-consistent reference with year-1 and year-2 levels. It includes the
     pre-registered years 3–5 fade rule (the path never rises after year 2), which is part of the
     reference's correctness; it is flagged in the before/after review;
   - item 2, the terminal-g pin;
   - the small fixes:
     - the 10% band wording;
     - the EPS analyst count;
     - a base-year check line;
     - a TTM freshness line;
     - bull and bear anchored to the company's own guidance range when there is no consensus
       range;
     - the takeover-offer wording;
     - the momentum data date;
     - the "owner CF" column renamed;
     - "use null when no reason is needed".

   The operator sees before/after briefings for several names before any GPU test.
**Whole-book test for the E18 reference change, pre-registered before any recompute (~06:40).**
The operator confirmed that the whole-book discipline applies to every change that moves a number
for every name, not only to the universal valuation item.

*Method.*
- Every book name with the inputs gets the reference computed three ways:
  - **old:** revision 9, a TTM base;
  - **E18 alone:** a fiscal-year base, fiscal-year growth, rolled forward to today;
  - **E18 + fade rule:** years 3–5 never rise above year 2.
- Ratios are reported by growth bucket (current-FY EPS growth g₁ < 0, 0–10%, 10–25%, 25–50%, >50%)
  and by sector.

*Pass criteria* (E18 alone; the fade rule is reported separately):
1. In the 25–50% and >50% buckets, the median new/old ratio is below 1, so the correction bites
   where the mechanism predicts.
2. In the 0–10% bucket, the median ratio lies within [0.90, 1.10], so steady names barely move.
3. No name that had a reference loses it. Names gaining one, such as foreign filers with fiscal-year
   data, are counted.
4. Each (b)/(c) name's ratio lies within its growth bucket's 10th–90th percentile, so the change has
   no special effect on the names that exposed it.

The fade rule may change only names whose old years 3–5 path rose above year-2 growth, by
construction; every other name must be unchanged by it.

*If any criterion fails,* stop and diagnose with Fable before any GPU run.

*Fable's additions (~07:05). Added before any recompute; nothing has been computed yet.*
5. **The size follows the mechanism.** The rank correlation between each name's new/old ratio and
   the predicted factor (1+COE)^(m/12) / (1+g₁)^(q/4) is above 0.5 across names with a reference.
   Here q is the number of quarters of the current fiscal year inside the TTM.
6. **The levels are right.** year-2 flow / consensus next-FY net income lies within [0.8, 1.25] for
   at least 80% of names with a growth-method reference.
7. **Criterion 4 counts only in buckets with n ≥ 10.**
8. **No hidden choice.** Within each g₁ bucket, every sector median lies within ±0.10 of the bucket
   median.

Levels-method names (LIND, MU) are reported separately.

**Result (2026-09-26 ~11:57 KST): FAIL on criteria 3, 4, 5, 6 and 8. Stopped; no GPU run.**

*Method.*
- 176 names were built as real revision-10 packs, offline: the 170 active names plus the (b)/(c)
  names. Worktree `rs2-P4-book` at 2cda9cb.
- Consensus estimates and targets were fetched fresh for every name. Company news, the world digest
  and SEC guidance were stubbed; none of them feeds the reference.
- A wrapper on `consensus_reference.build` captured each pack's own inputs, including the r9 TTM
  base from the caller.
- There were 0 build errors. 151 names have both references: growth method 139, levels or mixed 12.
- Script `scratchpad\e18_wholebook.py`; data `e18_book.json`.

*E18 alone / old, book names, growth method:*

| g₁ bucket | n | median | p10 | p90 |
|---|---|---|---|---|
| g₁ < 0 | 9 | 1.058 | 0.944 | 1.829 |
| 0–10% | 18 | 1.024 | 0.898 | 1.091 |
| 10–25% | 51 | 1.010 | 0.785 | 1.097 |
| 25–50% | 30 | 0.962 | 0.740 | 1.066 |
| >50% | 26 | 0.867 | 0.497 | 1.071 |

*Criteria.*
1. **PASS.** The median is below 1 in the 25–50% and >50% buckets.
2. **PASS.** The 0–10% median is 1.024.
3. **FAIL.** Six names lose their reference; none gains one.
   - EPAC, PSMT and MU have August fiscal years. FY2025 ended 12.9 months ago, and FY2026 has ended
     but is not filed, so the 0–12-month stub guard drops them. The guard assumes consensus rolls
     to the next year at the fiscal year end; it rolls at the report.
   - SAP and TSM hold no current fiscal-year data (SAP stops at FY2017, TSM at FY2024, and neither
     has a TTM). Their old references ran on those stale years through the E14 fallback.
   - LIVN's FY2025 base is negative: a −$242M net loss.
4. **FAIL.**
   - GPOR is 0.792, below its bucket's p10 of 0.898.
   - LAMR is 1.121, above its bucket's p90 of 1.097.
   - ADI, AMD, APH, AU, FIX and FSM lie inside their buckets.
   - LIND (levels method) and UGI (g₁ < 0 bucket, n = 9) are not counted.
5. **FAIL.** The rank correlation is ρ = 0.351 (n = 125).
6. **FAIL.** 59.7% of year-2 levels lie within [0.8, 1.25] of consensus next-FY net income; the
   median is 0.93. The old TTM base scores 63.4% on the same test.
8. **FAIL.**
   - Communication Services in the >50% bucket sits at −0.37: n = 2, GOOG and GOOGL, one company.
   - Financial Services in the g₁ < 0 bucket sits at −0.17: n = 1.

The fade rule changed 30 names, all in the rising-path set, as required.

*Diagnosis sent to Fable.*
- **The ratio follows the base window, not the period.**
  - The rank correlation between E18/old and the FY/TTM owner-earnings base ratio is 0.975.
  - Against the predicted period factor it is 0.35; on the 106 names whose base moved at most 30%,
    it is 0.32.
  - 16 of 134 bases moved more than 30% between the two windows: ALKS, AMZN, BLBD, BMRN (×9.7),
    EXPE, GEV, GOOG/GOOGL (×0.47), GRDN, HCSG, JBHT, META, NBIX, P, PTC and VCEL (×0.03).
  - The causes are net-income one-offs (equity-stake mark-ups, acquired IPR&D, impairments) and
    capex swings.
- **What E18 fixes and what it does not.** It removes the period bias on the median: UGI's
  predicted factor is 1.225 and its measured ratio 1.212. It also trades the TTM window's one-offs
  for the fiscal year's.
- **The stub guard (criterion 3) is a defect in the E18 implementation.**
- **Criterion 6 compares owner earnings with net income.** D&A − capex separates them by
  construction.

No criterion is changed after the result. A revised design gets new criteria, pre-registered
before its rerun, and this FAIL stays on the record.

**Fable's rulings (2026-09-26 ~12:05 KST).**
- **The mechanism.** e18/old = (FY base / TTM base) × a residual. The residual is about 1.06 in
  every bucket: the roll-forward (1+COE)^(m/12). So the whole period fix lives in the base swap.
  - On fast growers the swap is the period effect: AMD 1.23, ADI 1.28 and APH 1.17 measured,
    against 1.35, 1.29 and 1.26 predicted.
  - Elsewhere it is one-offs, landing on either side. GOOG's and AMZN's TTM windows hold 2026
    equity mark-ups, so E18 halves them, correctly. BMRN's TTM holds an acquired-IPR&D charge, so
    E18 raises it 10×.
- **a. The stub guard.** Take the period from the consensus vintage, not the calendar.
  - When the vendor has moved past an unfiled fiscal year, years 1–2 are the EPS levels, stamped
    `fy_rolled_unfiled`.
  - History older than 15 months is "not available — stale history".
  - A fiscal-year base that is not positive goes to the EPS levels.
  - *Orchestrator refinement, to confirm with Fable:* the ruling assumed the vendor had rolled
    whenever the filed year is more than 12 months old. The data says otherwise: EPAC, PSMT and MU
    have a current-year "year-ago revenue" equal to their filed FY2025 revenue, to the dollar. So
    the vendor still starts from the filed year, and the fiscal-year reference stays valid. The
    built rule:
    - vintage aligned (year-ago revenue within 2% of the filed year's) → the growth method on the
      filed year;
    - not aligned, or unknown → the EPS levels, valued at the end of the unfiled year.
- **b. One-offs: annotate, don't choose.**
  - When the TTM owner earnings differ from the fiscal-year base, grown by consensus current-FY
    growth for the quarters between them, by more than 15%, SECTION 8 prints a BASE WINDOW CHECK.
    It holds the TTM window's reference and year-2 level; the BASE-YEAR CHECK is printed beside it.
  - The analyst names the window in `base_cf_reason` (A1 flag `base_window_without_reason`).
  - The harness checks against the reference nearer the base IV and stamps `base_window_gap` and
    `reference_window_used`.
  - Nothing is chosen by rule: a rule "nearer the consensus" would prefer the window carrying a
    positive one-off.
  - *Built as "net of the consensus growth for the quarters between them"*, so ADI's gap, which is
    the period effect itself, reads −0.6% and is not flagged. The ruling said "the window gap"; to
    confirm with Fable.
- **c. Criteria.** C1, C2 and the fade check were sound. C4 failed by chance: 1.6 misses were
  expected and 2 occurred. C3, C5, C6 and C8 were mis-specified, re-specified below.
- **d. Revision 10.** Keep E18; do not revert to the TTM base. Ship it with a, b and the BASE-YEAR
  CHECK (built: 3dc2951). Rerun the whole-book test, then the draw.
- **Draw pass-mark additions.**
  - A name whose window gap exceeds 15% is scored on the reference the analyst named.
  - `reference_window_used` must agree across its samples; otherwise the disagreement is reported
    as a base-choice split.

**Whole-book rerun, pre-registered before it runs (2026-09-26).** These criteria were re-specified
by Fable **after** seeing the first run, so the rerun is not blind. It can confirm the fixes. The
independent evidence is the new draw.

*Method.* Same script and same book (the 170 active names plus the (b)/(c) names), on the same
estimates snapshot of 2026-09-26, with the code at 3dc2951.
- "old" is revision 9 on the TTM base.
- "e18" is the revised design with the r9 years 3–5 rule; "e18_fade" is what the pack prints.

*Criteria:*
1. In the 25–50% and >50% g₁ buckets, the median e18/old is below 1.
2. The 0–10% bucket median e18/old is within [0.90, 1.10].
3. No name whose old reference rested on data at most 15 months old loses its reference.
4. Among the (b)/(c) names in buckets with n ≥ 10, at most 2 lie outside their bucket's 5th–95th
   percentile of e18/old, each named with its cause.
5. On growth-method names with both bases:
   - in the >50% and 25–50% buckets, the median TTM/FY owner-earnings ratio lies within ±0.10 of
     the bucket median of (1+g₁)^(q/4);
   - in the 0–10% bucket, the median TTM/FY ratio lies within [0.85, 1.15].
6. For ≥ 80% of growth-method names, the E18 year-2 level ÷ (consensus next-FY net income + the
   filed year's D&A − capex) lies within [0.8, 1.25].
7. Criterion 4 counts buckets with n ≥ 10 only.
8. Within each g₁ bucket, every sector cell with n ≥ 5 has a median within ±0.10 of the bucket
   median.

Fade check: only rising-path names change.

*Reported:* the count of window flags (|gap| > 15%), levels-method names by reason (growth
unusable, base not positive, rolled vintage), and stale-history names.

**Rerun result (2026-09-26 12:18 KST, code 3dc2951): 7 of 8 PASS, criterion 6 FAILS. Stopped; no GPU
run.** Script `scratchpad\e18_wholebook_rerun.py`; data `e18_book_rerun.json`.

*Setup.* 176 names built, 0 errors. 155 names have both references (141 on the growth method both
times).

*Criteria.*
1. **PASS.** Medians 0.962 (25–50%) and 0.867 (>50%).
2. **PASS.** The 0–10% median is 1.024.
3. **PASS.** No credible reference is lost. SAP and TSM rested on data more than 15 months old;
   SMTC gains a reference.
4. **PASS.** One (b)/(c) name lies outside its bucket's p5–p95: LAMR at 1.121, whose FY/TTM base
   ratio is 1.06.
5. **PASS.** Median TTM/FY base against the median of (1+g₁)^(q/4): 1.139 vs 1.138 (25–50%),
   1.251 vs 1.27 (>50%); the 0–10% median is 1.071.
6. **FAIL.** 64.5% of names lie within [0.8, 1.25]; the median is 0.90.
8. **PASS.** 14 sector cells with n ≥ 5, all within ±0.10.

The fade check passes.

*Reported.*
- 35 window flags (20% of names). Examples: BMRN −92%, PSMT −44%, GOOG +56%, AMZN +80%,
  VCEL +2329%.
- No name hit the rolled-vintage case: every vintage was aligned, or its filed year was at most
  12 months old.
- The levels method now covers LIVN and SMTC (base not positive).
- Stale history: BWMX, CGAU, SAP, TSM.

*Diagnosis of criterion 6, for Fable.*
- **Adjusted vs reported earnings.** Even the reported fiscal-year net income grown at consensus
  rates, set against consensus next-FY net income, has a median of 0.956 and only 66% within
  [0.8, 1.25]. Consensus EPS is adjusted and our base is reported: TEAM, DT, DOCU and RNG are
  heavy on stock compensation.
- **Capex above depreciation.** On AMZN and META capex exceeds D&A by about 5.5× the base, and
  the level grows that (D&A − capex) with the consensus rates while the denominator adds it once.
- **Currency.** Yahoo quotes ZTO's and ATAT's EPS in yuan against our dollar filings; their
  year-ago revenue is 6.99× the filed figure. The same mismatch shows at GMAB (6.3×), KMDA (3.1×)
  and IHG (0.48×).

So criterion 6 again tests something the reference does not claim.

**Warning:** re-specifying a criterion a second time, until it passes, is criteria-fitting. The
ruling on criterion 6 goes to Fable and the operator with that said plainly.

*Which book (noted 2026-09-26 ~15:35 KST, before any further run).* Both runs used the rs2 active book:
170 names, `rs2-local/cache/analysis_state.json`. The new draw's "nominated book" is the
screener's current nominations: `factor_scores_dual_door.json` `nominated_tickers`, 135 names,
generated 2026-09-23, which hold the (b) hold-out names. Only 14 names are in both. The draw needs
estimates for the nominated book anyway, so the rerun criteria are also applied to it, unchanged.
That is supplementary evidence, reported whatever it shows: it neither replaces nor rescues the
book result above.

*Supplementary result on the nominated book (2026-09-26 15:44 KST, code 3dc2951).* Script
`e18_rerun_nominated.py`. 135 names built, 0 errors; 88 have both references (65 on the growth
method both times).

*Criteria.*
1. **FAIL.** The medians are 0.997 (25–50%, n=14) and 1.024 (>50%, n=9).
   - This is composition. 6 of the 9 >50% names have no TTM window (AU, EFXT, EQNR, FSM, MSGE,
     STX), so old and new both use the fiscal year and the ratio is only the roll-forward,
     1.02–1.065.
   - The three that have a TTM window read 0.85–0.93, as designed: ATI, MOV, MYE.
2. **PASS.** The median is 0.929 (n=5).
3. **FAIL.** WSE lost a credible reference. This is a defect: see the next item.
4. **PASS.** LAMR 1.121 and UGI 1.212 lie inside; the other buckets have n < 10.
5. **PASS.**
6. **FAIL.** 69.8% within the band; the median is 1.016.
8. **PASS.** Only 2 sector cells have n ≥ 5.

The fade check passes.

*New defect.*
- **Cause.** WSE and TOP have no TTM record, so `_fye_month_day` falls back to 31 December, and
  their filed FY2026 reads as "ends 2026-12-31, after today".
- **Source of the real date.** The vendor's annual statement dates their fiscal year end
  2026-03-31, with the same net income.
- **Status.** Sent to the reviewer with a proposed fix.

*Latent defect found (not yet fixed).*
- The levels method multiplies vendor EPS levels by shares. For a company whose vendor figures are
  in another currency (ZTO, ATAT, GMAB, KMDA, IHG), a levels-method reference would be off by the
  exchange rate.
- None of today's 15 levels-method names is affected. Growth-method references use only ratios,
  so they are unaffected.
- Proposed guard, for Fable: the levels method needs the vendor's year-ago revenue within 2% of the
  filed revenue, the vintage test already built, or else "not available".

**Reviewer's rulings after the rerun (Opus 5.5 max, which the operator put in Fable's place on
2026-09-26; ruled ~16:00 KST, after the supplementary run, before any pool is computed).**
- Code 3dc2951; 1116 tests pass, run by the reviewer.
- Measurements are in `scratchpad\opus_p4_review\`.
- **Verdict: approved with conditions.** E18 as revised is approved. 3dc2951 is **not** the draw's
  code until B1–B7 are done and the fix commit is re-reviewed.

*1. Criterion 6: the FAIL stands, is not re-specified, and is not evidence about E18.*
- **It cannot tell the designs apart.**
  - On the same 141 book names, r9 scores 64.5%, exactly as E18 does; the medians are 1.015 and
    0.901.
  - On the nominated book, r9 scores 54.0% and E18 69.8%.
- **It measures the basis of the base year, which E18 did not change.**
  - Where our filed FY EPS is within 25% of the vendor's year-ago EPS, 87.1% of book names lie
    inside (median 0.996); elsewhere, 30.4% (median 0.733).
  - Among the aligned names whose capex exceeds D&A by less than half of net income, 73 of 77 lie
    inside.
- **The level is, by design since E10, our filed owner earnings grown at the analysts' adjusted
  EPS growth.** On 46 of 141 book names it sits more than 20% below the analysts' path.
- **Corrections to the diagnosis.**
  - IHG is a revenue definition, not a currency: its vendor EPS is in dollars.
  - KMDA's and GMAB's EPS are in dollars; only their revenue estimates are not.
  - The high side (4 book names, 7 nominated) was not diagnosed. Besides the two construction
    effects, it holds two real defects that predate E18:
    - consolidated net income over the parent's units: WLKP 6.1×, TWFG 5.2×, BIP 3.3×, BBUC 14.9×
      and AU 1.20× the vendor's attributable income;
    - a vendor unit break: AZN's year-ago EPS is $4.58 per ADS against $10.09 per share, so c₁
      reads +120%.
- **No adjusted-to-reported bridge.** It would take stock pay back out of the base, and it could
  only be tuned name by name.

*For the operator.*
- Criterion 6 failed twice and will not be rewritten a third time; it stays failed.
- It tried to show that the year-2 level we print equals what analysts expect. It cannot. We start
  from reported earnings, with stock pay as a cost and the base year's one-offs included; analysts
  start from adjusted earnings.
- For about a third of names our level sits more than 20% below theirs, so our value is more
  conservative than the street's there. That was decided in E10, and the old design scores exactly
  the same on this test.
- The independent test is the draw.
- The test did expose two real problems, now on the fix list: profits that include minority owners'
  share, and vendor figures in another currency or unit. Both are fixed by rules that apply to
  every company, with existing tolerances. Nothing is patched by name.

*2. Vendor figures meet filed figures only when shown to match.*
- **EPS levels.** Used only when `vintage_aligned` is True; otherwise not available.
- **Rolled vintage.** Not available (0 names today). This supersedes ruling a for this branch:
  vendor revenue for ZTO, ATAT and VIPS is 6.99× ours, and for RNW 116×.
- **E14 vendor capex.** Used only with no unconverted `FX` flag and a vendor statement dated at our
  FY end within 7 days. RNW subtracts 94.0B of rupee capex from dollar income.
- **Exempt.** The growth method, the Bull/Bear range levels and the E12 ratios.
- **Effect.** 3 printed levels references go: two revenue-definition mismatches and BBUC. 2 more go
  that the fence already hides. No book levels name changes.

*3. Refinements confirmed.*
- **(a) Vintage.** EPAC, PSMT and MU match to the dollar. A failed or unknown test means "not
  verified", never "rolled".
- **(b) Netted gap.** ADI reads −0.65% netted, against +27.8% raw.
  - The flag rate is 35 of 105 windowed book names (33%) and 19 of 45 nominated.
  - 15% is LEVEL_TOL; changing it now would be fitting.

*4. Blocking defects in 3dc2951.*
- The TTM window's reference is not fenced: 9 name-cases, e.g. BMRN $8.05 against a $27.3 floor.
- The Dec-31 fiscal-year default: WSE and TOP visibly, RNW silently.
- There is no currency guard on vendor figures.
- The BASE-YEAR CHECK compares mismatched share bases: 24 of 240 lines are distorted, e.g. APH
  reads −50% from a split.

*5. The draw is blocked until B1–B7.*
- Supplementary C1 is composition. The names with q ≥ 1 read medians of 0.959 and 0.896; every
  name with no TTM window reads its roll-forward, 1.022–1.068.
- Supplementary C3 is the B3 defect.
- **Order.** Record this ruling, then compute the pool. Pin the screener-publish commit in
  `draw_20260927.txt`. Add the A2 rules and read both packs before any sample runs.

*Fix list.*
- **B1.** Currency guard. EPS levels only with `vintage_aligned` True; the rolled branch is not
  available; E14 vendor capex only with a clean `FX` block and a dated match.
- **B2.** Fence the TTM-window reference: print its side of the fence, never a number.
- **B3.** `_fye_month_day` takes the month and day from the vendor statement dates (within 7 days)
  and reports its source. There is no Dec-31 default in the E18 path; a net-income match confirms
  the label year.
- **B4.** The BASE-YEAR CHECK prints only when `vintage_aligned` is True and the FY and pack share
  counts agree within LEVEL_TOL; otherwise "not available" with the cause.
- **B5.** Scorer:
  - score the window the analyst names (a human input per sample);
  - take the fence and MoS marks from gate v3, meaning the stamped `street_fence` and
    `depth_gates.assess` reasons 10–11.
- **B6.** Run the suite. Rerun both whole-book scripts as a regression diff only, re-scoring no
  criterion; the per-name table stays in scratch until the draw.
- **B7.** The operator's nod on the revision-10 text changes, as one decision: B1–B4 and the
  `metric` schema text.
- **Carried.**
  - C1: consolidated net income over parent units. A Phase 6 preflight blocker; no affected name
    meets the draw's data conditions today.
  - C2: the vendor EPS unit break (AZN).
  - C3: always stamp the FY reference, plus `reference_window_value`.
  - C4: correct the docstring's "D&A absorbs the gap", which is false for 34% of names.
  - C5: when the FY reference is outside the fence but the TTM reference is inside, no reference
    prints (VCEL).
  - C6: the pack says the TTM extract carries no D&A for any name; 3,188 of 4,479 records have it.
  - C7: `fundamentals_ttm.json` is 25 days older than the history file, stranding June-year TTMs.
  - C8: relabel the levels wording, and add a `base_year_eps_gap` stamp.
  - C9: count rolled-branch cases across the Feb–Mar reporting season before designing a verified
    path.
  - C10: the nearer-by-IV window can flag `years12` against the other window's level
    (report-only).

**Reviewer's re-review of the fix commits (Opus 5.5 max, 2026-09-26 ~17:00 KST, before any pool is
computed).**
- **Code.** db68811: 7b05b00 (B1–B4, C3, C4) plus db68811 (the B3 correction). 1128 tests pass, run
  by the reviewer.
- **Method.** Every pack in both books (291 names) was rebuilt offline on exports of 3dc2951 and
  db68811, with the B6 estimates snapshot and the B6 stubs. The reference values match the B6 data
  on both commits, name for name. Measurements are in `scratchpad\opus_p4_rereview\`.
- **Verdict: approved with conditions.** db68811 is the draw's code. The draw waits on D1–D6 below,
  none of which changes rs2 code.

*1. B1–B6 against their acceptance lines.*
- **B1: met.**
  - EPS levels need a verified vintage, and the rolled branch is gone; no name reaches "not verified"
    today.
  - Vendor capex needs a clean FX block and a statement dated at our FY end within 7 days, on both
    fallbacks. 36 names depend on it and 33 pass: RNW is refused for rupees, BWMX and SAP on the date
    (both are stale anyway).
  - As ruled, the printed levels references of BBUC, HOG and NGVT are lost, and so are the fenced
    ones of ASX and INSW.
- **B2: met.** All 8 TTM-window values outside the fence (9 name-cases) are withheld, and none prints
  outside it.
- **B3: met in effect.**
  - No name in either book falls to the default. 240 take the TTM record, none more than 7 days
    from the vendor's same-year statement; 51 take vendor dates, all 31 December or 31 March.
  - WSE gains its reference ($13.95).
  - RNW is correctly stale: its FY2025 ended 2025-03-31, 18 months ago.
- **B4: met exactly.** 189 lines print, each verified; 64 print "not available" with the cause.
- **C3 and C4: done.**
- **B6: done, with three corrections to the diff note.**
  - RNW moved through B3 (stale history), not B1.
  - "Book 0 moved" holds for reference values only. B2 changed the BASE WINDOW CHECK line on 6 book
    names, and B4 changed 64 BASE-YEAR CHECK lines across both books.
  - CX did not return to its 3dc2951 line (see 3).

*2. The BASE-YEAR CHECK.* All 253 lines that 3dc2951 printed were re-measured against the vendor's
own GAAP diluted EPS.
- **Suppressed correctly.** 27 lines mixed per-share bases, and B4 suppresses 23 of them: APH −50%
  (a split), SIMO +290%, ATAT +2168%.
- **Still printed.** 4 distorted lines, none on a name that prints a reference:
  - AU, HG and NEXA carry consolidated income (C1);
  - AZN reads −31% where one basis gives about +39%, a unit break inside the vendor's series (C2).
- **Suppressed although correct.** 38 lines, 9 of them within ±3%. That is the price of the rule
  (C12).
- **Defects.**
  - A None share count with a verified vintage raises TypeError (R1).
  - The vintage-False text is too strong (R3).
  - No test covers the share branch or the vintage-False branch.
- **Share count source.** SECTION 2's share count is the vendor's `impliedSharesOutstanding`, else
  `sharesOutstanding`, and is in ADS units for ADS names. The share test catches every ADS ratio
  other than 1.

*3. The label-year conflict.*
- **The same-year rule is right.** The history builder bins every fiscal year by the calendar year
  it ends, so a start-year label cannot occur. No name without a TTM record closes in January or
  February.
- **A match in another year** can only be a coincidence or a vendor error.
- **CX is a coincidence.** Our FY2024 is consolidated income (960 against the vendor's attributable
  939), and the vendor's FY2025 rounds to the same $960M.
  - CX's outcome is right, because its history is 21 months old, but its printed reason is false
    (R4).
  - CX also shows that the 2% revenue vintage test cannot tell a flat year from the next (C9,
    widened).

*4. The scorer.* It implements the marks and the B5 additions, with four deviations, fixed before
any sample runs (D5):
- depth_gates is imported from a default run tree on gate v2;
- a bull or bear years 1–2 ratio that could not be computed counts as a pass;
- a named window other than fy or ttm silently becomes "no reference";
- an open mark prints "DRAW: FAIL", and the human columns sit outside `pass`.

*5. The draw procedure, gaps found before the pool.*
- **The draw script.** It writes the worktree's name, not the rs2 commit. It pins no screener-publish
  commit and does not check the estimates' fetch date.
- **Exclusions.** BFH, DAC and GSL are nominated and in the E-audit, but none of the three documents
  names them. They are design-touched and are named here so that they are excluded.
- **C1 reaches the draw.** The first review's statement that no affected name meets the draw's
  conditions was wrong. GOLD's filed net income is 1.076× the vendor's and AMT's 1.039×
  (consolidated); OUT's filed EPS is 1.06× the vendor's with equal net income (a preferred claim).
- **A name without a fence.** ACIC prints a reference but has no usable band.
- **The band's source.** `_consensus_band` reads `cache\openbb_*` first, with no fallback when that
  entry is stale.

*Conditions before the draw.*
- **D1.** B7: the operator's nod on the revision-10 text. R3 and R7 are the only carried items that
  can print in a drawn pack; fixing them first means a new commit and a short re-review (the diff and
  the suite).
- **D2.** `draw_20260927.py` writes the rs2 commit, the screener-publish commit and each pool name's
  estimates fetch time, and refuses to draw if any fetch is not from the pool's day. The runs check
  both commits before the first sample.
- **D3.** Two new data conditions:
  - filed FY net income within 2% of the vendor's same-year net income, and no same-year statement
    fails it (AMT, GOLD and VIPS fail);
  - a usable street band.
- **D4.** BFH, DAC and GSL are excluded.
- **D5.** The four scorer fixes. The scorer's sha256 goes into `draw_20260927.txt` before any sample
  runs, and the reviewer reads the scorer diff before scoring.
- **D6.** The pool and the runs use one worktree at the draw's code, with the same `enrich\` and
  `cache\`.

*Carried: rs2 code, before the branch merges or any production run.*
- R1: a None share count raises; the zero or None wording; tests for the share and vintage-False
  branches.
- R2: the "not verified" text claims a mismatch when the year-ago revenue is only unavailable.
- R3: B4's vintage-False wording.
- R4: a label conflict needs the shifted match in two consecutive years and no same-year match.
- R5: say why the vendor capex was refused.
- R6: a test skips itself from December 2026.
- R7: the BASE WINDOW CHECK points to the BASE-YEAR CHECK even when that line is "not available".
- C1 (widened to every claim senior to common) stays a Phase 6 preflight blocker.
- C9 (widened) and C12 (new) are carried.

*Orchestrator's decision (2026-09-26 17:05 KST).* All of R1–R7 are fixed before the operator is asked,
so that the operator approves the final text once. That means a new commit and the short re-review
the reviewer described. D2–D6 follow.

**Short re-review (Opus 5.5 max, 2026-09-26 ~17:30 KST).**
- **Verdict:** approved with conditions. d0455a6 (R1–R7) is the draw's code and replaces db68811.
- **Suite:** 1134 passed, run by the reviewer.
- **Full-pack diff,** db68811 → d0455a6, over all 291 names:
  - 66 packs change, 70 lines in all, each traced to an R item: 63 are R3 wording; ITT (R1: a zero
    share count); BWMX, RNW and SAP (R5); GRDN and HOV (R7); CX (R4).
  - The operator's nod covers these lines (O1).
- **Moved clock:** R6's tests pass at 2026-09-26, 2026-12-15 and 2027-06-30.
- **Measurements:** `scratchpad\opus_p4_r1r7\`.

*The reviewer corrects two of its own rulings.*
- **B5 was too narrow.** "Reasons 10–11" narrowed the pre-registered rule "the draw must not pass what
  gate v3 rejects". On made-up verdicts, rows that gate v3 rejects for `fiduciary_fail`,
  `low_effort_rescue` or `kelly_on_overvalued` scored as passing.
- **D6 did not fix the data's shape.** The book tree's enrich records hold estimates and targets only,
  and it has no `cache\`. So all 291 packs print "not available" for trailing multiples, the 52-week
  range, short interest and ownership, where the (b) packs had values.

*Fix list for the draw tooling (no rs2 code).*
- **Before the pool:**
  - **T1.** The exclusion search swallows a full stop and misses MYE. Use a whole-word search per
    ticker: 41 names are excluded today.
  - **T2.** The D3 net-income match compares calendar years, which fails 52/53-week filers (DAR:
    2026-01-03 against the vendor's 2025-12-31, identical net income). Match the statement dated
    within 7 days of our fiscal year end, as B1 and B3 do.
  - **T3.** Refuse unless the nominated list is the pre-registered one (generated
    2026-09-23T16:25:18Z, 135 names). Refuse a dirty tree or clone when pinning.
  - **T4.** On the pool's day, fetch full enrich (`enrich_ticker`) and openbb for every nominated
    name into the draw tree. Refuse any `_book_fetch` record.
  - **S1.** The gate mark passes only when `assess` returns nothing but `non_production_row` on a
    `gate_test` row, together with the per-sample fence and MoS checks.
  - **S2.** Check each verdict's `pipeline_commit`, `screener_data_commit` and `run_source` against
    the draw file, on full shas, with a clean tree.
  - **S3.** A name with no run or no verdict prints NOT RUN or OPEN, never FAIL.
  - **S4.** The drawn names' A2 rules go into a data file whose sha256 is appended to the draw file
    before the first sample.
- **Before the first sample:**
  - **R-a.** A run check before each name and after the last: `RS2_RUN_SOURCE=gate_test`, both commits
    equal to the pins, both trees clean, and `RS2_SCREENER_DATA_COMMIT` set to the checked sha.
  - **R-b.** Write down how a recovered sample is re-run.
- **For the operator's decision:**
  - **O1.** The nod covers the final text at d0455a6.
  - **O2.** With S1, a low-effort forced report without a desk recovery fails the name; only a
    desk-only recovery gets a re-run. It stands unless the operator overrules it.
- **Carried:**
  - C13: a 52/53-week filer with no TTM record loses its reference with a wrong reason (fails closed;
    0 names).
  - C14: R4's text says "a year apart" when the shift is more than a year (fails closed; 0 names).
  - C15: scorer strictness items that can go with S1–S4.
- **After T1–T4 and S1–S4:** the reviewer takes a short look at the two script diffs, without the
  suite, before the pool.

*Orchestrator (2026-09-26 ~17:40 KST): the draw tooling as built, before any pool.*
- **Pool (`draw_20260927.py`).**
  - T1: a whole-word exclusion search per ticker. It excludes 44 of 135 today, including MYE, BFH, DAC
    and GSL; the record grew after the reviewer's count of 41.
  - T2: the net-income match uses the vendor statement dated within 7 days of our fiscal year end.
  - T3: it refuses a nominated list other than the 2026-09-23T16:25:18Z, 135-name one, and a dirty rs2
    tree or clone.
  - T4: it refuses any `_book_fetch` record or a missing openbb cache.
  - C15(c): any pack build failure stops the draw.
  - The draw file pins the full rs2 commit, the rs2 tree, the screener-publish commit, the scorer's
    sha256 and every pool name's fetch time.
- **Data (`prep_draw_data.py`, T4).** Full `enrich_ticker.enrich` and `openbb_data.fetch` for every
  nominated name, into the draw tree, on the pool's day.
- **Scorer (`score_draw.py`).**
  - S1: the gate mark passes only when gate v3 gives nothing but `non_production_row`, together with
    the per-sample fence and MoS checks.
  - S2: a provenance mark: `run_source` is `gate_test`; `pipeline_commit` (a short sha, as
    depth_pipeline writes it) is a prefix of the pinned full sha; `screener_data_commit` equals the
    pin.
  - S3: a name that is not run, or has no verdict, is open.
  - S4: the A2 rules live in `draw_a2_rules.json`, whose sha256 must match the draw file's
    `a2 rules sha256` line, appended before the first sample.
  - C15(b): a missing terminal-g stamp leaves the process mark open.
- **Tree check (`draw_check.py`, S2 and R-a),** shared by the scorer and the run script:
  - the rs2 tree sits at the pinned full commit;
  - its only change is config.json's `depth_model` line pointing at the candidate
    `rs2-analyst-deep-mtp5-v31`, as in (b), and nothing is untracked outside `draw_logs/` and
    `discovery_logs/`;
  - the clone sits at its pin and is clean.
- **Runs (`run_draw.sh`, R-a and R-b).**
  - It runs the tree check before each name and after the last, with `RS2_RUN_SOURCE=gate_test` and
    `RS2_SCREENER_DATA_COMMIT` set to the pinned sha.
  - **R-b, the rule:** a name with a desk-only-recovered sample is re-run once, whole; the newest
    folder is scored and both folders are recorded (`draw_logs/folders.txt`).
- **Order after the operator's yes:**
  1. `prep_draw_data.py`, then `draw_20260927.py` (the pool and the draw);
  2. the two names are shown to the operator;
  3. pack previews and the A2 rules, their sha appended to the draw file;
  4. config.json's `depth_model` switched;
  5. `run_draw.sh`, about 3 GPU hours.

**Tooling look (Opus 5.5 max, 2026-09-26 ~18:05 KST; no suite).**
- **Verdict:** approved with conditions. The pool waits on items 1–5, the first sample on 6–7. No rs2
  code or revision-10 text changes, so the operator is asked for D1 now.
- **As built:**
  - T1–T3, S1, S2, S4 and C15(b)(c) are as specified.
  - T1 excludes 44 names (reproduced). T2 moves no pool name today.
  - The tree check is sound: every write of the draw path lands in gitignored paths.
  - The short-sha prefix is acceptable, given the full-sha tree checks.
  - Production caches and quotas are untouched: the draw tree has its own cache and quota ledger, and
    no keys.
- **Before the pool:**
  1. **S3.** A name with no verdict, or with failed provenance, must print OPEN, not FAIL. A verdict
     without a street fence leaves the fence mark OPEN.
  2. **Provenance** also requires `model` = rs2-analyst-deep-mtp5-v31, `pack_revision` = 10 and a
     `pipeline_commit` of at least 7 hex characters. As built, a run on the unswitched model scored
     PASS.
  3. **Folders.** Score the folder `draw_logs/folders.txt` records last. An unrecorded folder since
     the run started, or a second re-run, leaves the name OPEN. R-b gains a crash rule: a non-zero
     exit stops the batch, and after diagnosis the name is re-run whole, once, and recorded.
  4. **Pins.** The draw file also pins `draw_check.py`'s sha256. The scorer refuses if its own sha or
     draw_check's differs from the pin.
  5. **Empty records.** A throttled fetch writes an empty record that passes T4 and silently drops the
     name. Prep retries such records. The pool refuses any name with no estimates or no 52-week high,
     and any openbb cache not fetched on the pool's day. Prep never runs during the screener's
     self-hosted fetch: Sat/Sun 19:35, Mon–Fri 23:35 KST.
- **Acceptance for 1–4:** the reviewer's seven simulated cases (`opus_p4_tooling\sim\`) give CLEAN
  PASS, FIDFAIL FAIL, and OPEN for the other five.
- **Before the first sample:**
  6. The draw tree needs the `research-venv` junction (the (b) tree has one). Without it, runs skip
     deep research and strip SECTION 11. `run_draw.sh` refuses without the interpreter and stops a
     name whose log shows "research-venv missing".
  7. `run_draw.sh` refuses to start unless all of these hold: the `depth_model` line is switched; the
     A2 sha matches; the registered v31 model's system layer has the pinned digest; there is no
     `.secrets.json`.
- **Carried:**
  - **C16.** R and TASK are excluded only by label collisions: the item labels R1–R7, R-a and R-b, and
    the TASK section. Neither would enter a pool today. *Orchestrator's decision: the rule as coded
    stands (conservative).* Nothing naming a pool candidate goes into the three documents before the
    pool.
  - **C17.**
    - Pin the sha256 of the three documents, `run_draw.sh` and the MRI outputs.
    - Refuse an empty fast or steady pool.
    - Drop the `discovery_logs/` allowance.
    - Fix the scorer's stale "reasons 10 and 11" sentence.
  - **C18, disclosed.** Like (b), the draw tree has no API keys: research is SearXNG-only, with no FMP
    transcripts. It has no production ledger, so there is no prior base.
  - **C19, done.** The times of the short re-review and of the tooling note were corrected to
    ~17:30 and ~17:40 KST.
  - **C20.** Production, Phase 6 preflight: the on-demand drain resets the publish clone before it
    checks DEPTH_PAUSED. No on-demand requests until the runs end.

*Orchestrator (2026-09-26 ~18:25 KST): items 1–7 and C17 built.*
- **Items 1–4 (`score_draw.py`).**
  - No verdict, or failed provenance, leaves the name OPEN; a verdict without a fence leaves the fence
    mark open.
  - Provenance checks model, `pack_revision` and a 7–40 hex `pipeline_commit`.
  - The folder scored is the one `draw_logs/folders.txt` records last. An unrecorded folder, or a
    second re-run, leaves the name OPEN.
  - The scorer refuses unless its own sha256 and `draw_check.py`'s match the draw file.
  - **Acceptance:** the reviewer's seven cases, run on a copy in `scratchpad\sim_accept\` with a
    `folders.txt` fixture, give CLEAN PASS, FIDFAIL FAIL, and NOVERDICT, OLDMODEL, BADPROV, NOTG and
    REROLL OPEN, as required.
- **Item 5.**
  - `prep_draw_data.py` treats an enrich record with no estimates or no 52-week high as a failed fetch
    and retries it.
  - The pool refuses any name with such a record, or an openbb cache not fetched on the pool's day.
  - Prep will not run during the screener fetch windows.
- **Items 6–7.**
  - The draw tree now has the `research-venv` junction to `rs2-local\research-venv`. Git ignores it,
    and the tree stays clean.
  - `run_draw.sh` refuses to start without that interpreter, with `depth_model` unswitched, with an A2
    file that does not match its pin, with a v31 system layer other than the pinned one, or with a
    `.secrets.json`.
  - It stops a name whose log shows "research-venv missing".
  - The draw file pins the v31 system layer digest: today `sha256:a76fd089a4c3…`, as the reviewer
    measured.
- **C17.**
  - The draw file pins the sha256 of the three documents, `run_draw.sh`, `draw_check.py` and the six
    MRI files the packs read.
  - An empty fast or steady pool stops the draw.
  - The `discovery_logs/` allowance is dropped.
  - The scorer's stale sentence is fixed.

**Operator rulings, 2026-09-27 ~00:30–00:40 KST (before any pool).**
- **Reduced thinking is not a result.** Operator: "Thinking low result should not be considered a
  result at all. I'd rather have it FAIL loud than to have a silent shit result."
  - This overrides O2 and R-b. A valuation or news write-up produced at `think: "low"` or
    `think: False` never counts, and the draw has no re-run.
  - It covers the news step's cut-off rescue. That rescue has not fired in 15 briefs since its output
    limit was raised on 2026-09-24; the most any brief used was 50,025 of 81,920 tokens (GEV).
  - The JSON syntax repair (`_llm_fix_json`, thinking off) is not covered. *Corrected after review:* the
    model is told to change no content, but the code only checks that the first 30 characters of each
    event appear in the broken text. It has never fired (0 of 15 briefs).
- **Full-thinking retry (operator OK).** Replaces the desk-only recovery. Specification below.
- **Bigger window (operator OK).** Measured below.
- **The window choice gets its own test (operator OK).** It is a separate pre-registered test,
  after the two-stock draw. The current draw checks only that a flagged sample names a window and
  sits on that window's reference, not that the choice is right.
  - It will use 4 names flagged by the BASE WINDOW CHECK, drawn by rule from names never touched in
    design. 35 of 176 book names are flagged today.
  - "Right" will be defined from the filings before any run, never from the price:
    - a gap driven by non-operating one-offs has the one-off-free window as right;
    - a gap driven by operating earnings has the TTM window as right;
    - mixed causes go to a human read.
  - The reviewer designs the classification rule first.
- **GPU.** Operator: "You're free to use GPU as much as you want."

**Why the analyst hits the window (batch (b), 26 valuations, measured 2026-09-27).**
- The median peak use was 74,334 of 81,920 tokens. 17 of 26 valuations went above 70k, and 4 hit
  the ceiling: GPOR s1, GPOR s2, LAMR s1 and UGI s3.
- Only GPOR's two ended at reduced thinking. GPOR s1 had a desk result and got the forced report
  (think low). GPOR s2 spent its first turn, 53,338 tokens, deliberating: 28,581 + 53,338 = 81,919.
  Sampled at five points, that thinking was mostly DCF arithmetic done by hand, a PV table and a
  bear path tuned by hand, although it wrote "I'll let the desk compute it".
- *Added after review:* LAMR s1, UGI s3 and GPOR s2 had their reports cut off and finished by a follow-up
  turn (`continue_report`) that sees only the pack and the unfinished text, with no research and no desk
  output. For LAMR s1 and UGI s3 that turn wrote the final numbers, and their records read
  `truncated False, done stop`. Nothing said so.
- **The label cap (the window fix's `ARG_MAX_CHARS`), replayed on the saved snapshots:** it frees
  up to about 29,800 tokens on UGI s3, 15,900 on LAMR s1 and 11,600 on FIX s2. It frees more than
  1k tokens on 5 of 26 samples, and 0–420 on GPOR. It fixes the essay cases, not the overthinking.
  - Method: every `run_financial_model` string argument over 300 characters, and each desk-result
    string over 300 characters (capped at the 12,000-character tool message), at 3.2 characters per
    token. It is an upper bound: it counts every such call as present in the peak prompt.

**Window measurement (RTX 3090, rs2-analyst-deep-mtp5-v31, KV cache q8_0, flash attention;
2026-09-27 ~00:45 KST).** The model loads fully on the GPU at each size; prompts are filled from
GPOR's pack.

| num_ctx | VRAM used / free (MiB) | filled to (tokens) | prefill | generation |
|---|---|---|---|---|
| 81,920 | 22,885 / 1,442 | 78,590 | 749 tok/s | 45.5 tok/s |
| 98,304 | 23,589 / 738 | 97,192 | 701 tok/s | 43.1 tok/s |
| 106,496 | 23,941 / 386 | 102,669 | 688 tok/s | 36.7 tok/s |
| 114,688 | 24,275 / 52 | (load only) | | |
| 131,072 | 24,275 / 52 (spills) | (load only) | | |

- **Decision: 98,304** (+16,384 tokens, +20%).
- *Corrected after review:*
  - "738 MiB free" is the graphics card's own reading. By the model runner's count only about 52 MiB
    is spare at 98,304, against about 757 MiB at 81,920.
  - The card does not refuse a model that is too big. It quietly spills into ordinary memory and slows
    down: 131,072 loaded "66/66 layers" with about 24,691 MiB of buffers. So nothing else may use the
    graphics card during the runs.
  - Each speed in the table is one reading of about 70 tokens. The firmer evidence is that 98,304 fits
    inside the memory the runner saw free, and 106,496 does not.
- The news step keeps 81,920: its highest use is 50k.

**Full-thinking retry and "not a result": the specification (orchestrator, 2026-09-27 ~01:00 KST;
coded by Gemini, to be reviewed by Opus 5.5 max).**
- **Harness (`analyst_tools.py`).**
  - The desk-only recovery is removed: `DESK_RECOVERY_PROMPT`, its think-low turn and its desk-only
    tools.
  - When a tool turn ends at the length limit with no tool call, no report and no desk result, the
    analyst gets one retry at the configured think level, with the normal options and tools. At
    98,304 that limit is usually the 65,536-token output cap, not the window. The retry prompt is
    revision-10 text, replaced after review (B3):
    > Your previous turn ran out of room deliberating before any tool call, and that reasoning is
    > lost. Do not compute values in your reasoning: run_financial_model does the arithmetic. Call it
    > now with Base, Bull and Bear as the TASK sets them. This first call is a starting point, not
    > your answer: research what the TASK asks, then re-run the desk, listing each change in 'Model
    > revisions' with the evidence that moved it.
    The first text said "used the whole context window", which is false at 98,304. Its "call it now,
    revise after" also clashed with the TASK's "One model, stated once" rule.
  - If the retry also ends at the length limit without a desk call, there is no forced report, and the
    attempt ends with `window_exhausted_twice`. *Corrected after review:* the sample does not fail at
    once. The existing whole-sample retry (full thinking, new seed) runs first, and the sample fails
    only if that retry also fails.
  - The forced report (a stub after a desk result) now runs at the configured think level with the
    normal options. If it is still not deliverable, the sample fails with `report_not_delivered`.
  - The news step's cut-off rescue runs at the configured think level. If the brief is still
    missing, it fails with `brief_not_delivered`. *Corrected after review:* at a928870 the
    `discovery_failed` flag still read "no parseable brief"; review item C6 passes the name on.
  - Every turn records the think level it was sent with.
- **Samples (`consensus_valuation.py`).**
  - `reduced_thinking` is true when any turn's think level differs from the configured one. For older
    snapshots it keeps the old meaning: stub, forced report or desk recovery.
  - `failed_reason` is the harness failure, or `empty_report`.
  - `counts_as_result()` keeps both out of the band and out of the early stop.
  - The existing empty-report whole-sample retry (full thinking) stays, and is recorded as
    `sample_retried`.
- **Verdict and gate.**
  - `LOW_EFFORT_RESCUE` now names reduced-thinking samples as "not a result: excluded".
  - A new `SAMPLE_FAILED:<n>:<reason>` flag, or `SAMPLE_FAILED:lost:<n>` for an exception, prints a
    loud line.
  - Gate v4 adds reason 14 `sample_failed` and reason 15 `discovery_failed`. A missing news brief
    used to be a flag only.
- **The draw.**
  - The scorer has a new mark, "every sample a result". It is False on any `reduced_thinking`,
    `failed_reason` or lost sample, and the name then FAILS with a printed "FAIL (not a result)" line.
  - *Changed pre-registered mark (before any data):* repeatability and base-on-reference used
    "non-recovered samples"; they now use "samples that are results". A sample saved by the
    full-thinking retry counts toward both.
  - The scorer requires gate v4.
  - `run_draw.sh` has no R-b re-run. It prints the SAMPLE FAILED count per name and moves on.
- **What this changes for the test.** GPOR-shaped overthinking now gets one real, full-thinking
  retry. A stub after a desk result gets a full-thinking report. Anything that still fails is
  counted, never hidden.
- **Carried to revision 11 (not built).** Tell the analyst from the start not to hand-compute
  values, since the desk does the arithmetic. That changes every valuation, so it needs its own
  measurement.

**Review of a928870 (Opus 5.5 max, 2026-09-27 ~01:50 KST): approved with conditions; not the draw's code
yet.** The suite passed (1144). The window table, the (b) figures, the label-cap savings, the news-step
claims and the dry run all reproduce.
- **What holds:**
  - No request lowers thinking. The ruling bites through `failed_reason`; the `reduced_thinking` stamp
    guards against future changes.
  - `counts_as_result` controls the early stop, the band, the median, the votes and the medoid.
  - The NOT_USABLE fix is right.
  - Nothing that reads the gate version breaks.
  - Side effect: every stored verdict becomes "not actionable" (`pre_v3.1_gates`) until the book is
    re-run. That costs nothing while trading is halted.
- **Before the pool:**
  - **B1.** After the whole-sample retry, the desk checks read the failed first attempt's snapshot. A
    clean retry was recorded as "desk not used", and the first failure was erased. Fix: read the
    retry's snapshot, and keep `first_attempt_failure`.
  - **B2.** The report continuation is a silent rescue. Fix: stamp `report_continued`, pass the
    configured think level, and add a `REPORT_CONTINUED` flag. The operator rules whether a continued
    sample counts.
  - **B3.** Replace the retry text (above).
  - **B4.** Scorer:
    - the gate gets its own mark;
    - a failed news brief is "not a result";
    - failed samples don't count as desk-less;
    - provenance requires `think` "high";
    - B1 and B2 are read and printed;
    - the slowest long turn's speed is printed.
  - **B5.** The crash rule disappeared with R-b. It needs writing down and the operator's
    confirmation.
- **Before the first sample:**
  - **S1.** Nothing else on the GPU for the whole run. `run_draw.sh` refuses to start unless the GPU is
    idle.
  - **S2.** The scorer prints each sample's median long-turn generation speed. Under 34 tok/s
    suggests a spill; the lowest sample median in (b), with no spill, was 37.9. *Corrected in the
    re-review (F1):* the first version flagged the slowest turn under 40, which 24 of 26 healthy (b)
    samples would have tripped.
- **Carried, and built now:**
  - C1: `REPORT_ROOM_TOKENS` 36,000 → 42,000. The largest full-thinking report turn in (b) generated
    39,031 tokens (FSM s2).
  - C2: the budget-exhausted memo sets `report_not_delivered`.
  - C3: an exception in the whole-sample retry is a lost sample, not a crash.
  - C6: the news-step failure name is passed on.
  - C7: stale gate docs.
  - C8: stale 81,920 literals.
- **Carried, not built:**
  - C4: unparseable, implausible or truncated samples leave the band with no flag on the row.
  - C5: the JSON-repair guard.
  - C9 (Phase 6): stored verdicts need a re-run; the sweep needs a GPU-memory guard; the worst case
    per sample is about 4 × 25 minutes against the 180-minute watchdog.
- **For the operator (asked 2026-09-27 ~02:00 KST):**
  1. the B3 retry text, as part of revision 10;
  2. B2, whether a continued report counts (the reviewer and orchestrator: count it, always shown);
  3. B5, the crash rule (proposed below);
  4. whether the ruling also covers the research brief written by the 14B helper with thinking off, by
     design (orchestrator's recommendation: no; it is an input the analyst checks, and the research
     layer is redesigned in E17).
- **Operator's answers (2026-09-27 ~02:10 KST): "Yes but on #4, place thinking ON on the research 14B
  helper. I don't know why it should be toggled off, it shouldnt. Otherwise all ok."**
  - 1–3 approved: the B3 retry text as part of revision 10; a continued report counts, always shown;
    the crash rule below.
  - 4: the research helper's thinking goes ON. It was off "for speed across LDR's many calls"
    (`deep_research.py`). The helper's window (`research_ctx`) goes from 8,192 to 32,768, because the
    thinking shares that window with the page being summarised. It is measured on UGI, on and off,
    before it is adopted.
- **Research helper, measured on UGI (2026-09-27 02:18–02:35 KST), thinking on (window 32,768) against off
  (8,192), same code otherwise:**
  - 21 requests each; none was truncated;
  - the largest request was 3,636 tokens (on) against 5,094 (off);
  - wall time 501 s against 512 s;
  - a direct probe confirms the helper really thinks when asked (961 characters of thinking on a
    two-sentence answer).
  - Both briefs are thin. Our search sources are the known E17 problem, and the probe ran without the
    company name. Adopted in cd9a9f3; the 900 s research limit stands.
- **Window options, put to the operator (2026-09-27 ~02:36 KST).**
  - Figures from the Ollama log: at 98,304 the model weights take 18,163 MiB, the main KV cache 3,264
    MiB, and the speculative-decoding draft about 548 MiB (384 KV and 164 compute; 466 at batch 256).
    Each 1,000 tokens of window costs about 42 MiB. *Corrected in the re-review:* the first text said
    "about 700 MiB".
  - The options:
    - (A) a processing batch of 256: measured +174 MiB margin (about 222 MiB spare by the runner's
      count), prefill −5%, generation unchanged. No quality change is expected, but none was measured,
      and samples are not bit-identical to batch 512 at the same seed. *Corrected in the re-review:*
      the first text said "no quality effect";
    - (B) KV cache q4_0: about 140–150k tokens, at a long-context accuracy cost;
    - (C) the Q4 v31 weights, already registered: about 150k+ tokens, at an arithmetic and coherence
      cost;
    - (D) no speculative draft: about 115k tokens, with slower generation;
    - (E) a bigger or second card.
  - **Operator: "I follow your recommendation and see how it goes."** A is built now (cd9a9f3,
    `depth_num_batch` 256). B and C wait for the two-stock test's recorded headroom and, if needed, a
    pre-registered side-by-side accuracy test. E is the operator's call.
- **Scorer acceptance after the fixes:** `scratchpad\sim_accept\sim_ft2.py` runs 18 cases against the
  scorer and rs2 at cd9a9f3, and all score as expected.
  - PASS: CLEAN, WRETRY, RETRIED (as now recorded), CONTINUED (printed), CRASHOK, and SLOW (printed
    "SLOW").
  - FAIL: FIDFAIL, LOWTHINK, FAILED, LOST, DISCFAIL ("news brief" not a result) and CRASH2.
  - OPEN: NOVERDICT, OLDMODEL, BADPROV, NOTG, CRASH and NOTHINK.
- **Operator delegation (2026-09-27 ~02:42 KST): "I'm going to sleep, so make best possible judgement
  before running the GPU test. You can use up to 6 hours."** The orchestrator's reading, recorded
  before acting:
  - **Revision 10.** Its parts are approved: items 1, 2 and the small fixes on 2026-09-26, and the B3
    retry text today. The yes to the revision as a whole is delegated. The orchestrator takes it for
    this test only: the draw writes gate-test rows to the test ledger, which are never published and
    are not production verdicts. The production-wide nod stays with the operator.
  - **Showing the two names before the run.** The operator is asleep, so the names are recorded in
    the draw file and in this record before any sample, and shown on waking. The draw is by fixed
    rule and seed, so showing them earlier would change nothing.
  - **Gates the orchestrator applies before the GPU:**
    - the reviewer's short re-review passes, or its findings are fixed;
    - the pool and draw scripts run clean;
    - both packs are read and the A2 rules pinned;
    - the GPU is idle;
    - the whole run fits the 6 hours.
  - If a gate fails, the GPU test waits for the operator.
**Short re-review of bab4206 and cd9a9f3 (Opus 5.5 max, 2026-09-27 ~02:50 KST): approved with
conditions. cd9a9f3 is the draw's code.**
- The suite passed (1155), and B1, B2, B3, C1–C3, C6–C8, batch 256 and the research thinking path were
  all verified. The 18 acceptance cases reproduce.
- **Before the pool, done:**
  - F1: the speed flag uses the median long turn under 34 tok/s, with a 39 tok/s fixture that must
    not flag.
  - F2: `run_draw.sh` starts only below 200 MiB of GPU use.
  - F3 (below): a stopped run is a crash.
  - The acceptance run is now 19 cases, all as expected.
- **Carried:**
  - config.json's "Outputs are unaffected" overstates the batch change (corrected here, not in the
    pinned code).
  - The thinking measurement cannot size how much the helper thinks, because the two runs read
    different pages. The code path and the direct probe are the evidence.
  - `deep_research.py:501` reads an empty contradiction-check reply as "no contradictions".
  - Stale comments (`deep_research.py:98`, `depth_pipeline.py:76` and `:296`,
    `consensus_valuation.py:1946`, reason 7's docstring).
  - C4, C5 and C9.
**The draw (2026-09-27 02:54 KST, rs2 cd9a9f3, `draw_20260927.txt`).**
- **Prep.** 135 of 135 fetched, with none failed.
- **Pool.** 44 names excluded, leaving 91. 15 met every data condition: a fast-grower pool of 5 (CHEF,
  DLTR, ENVA, NEM, TGT) and a steady pool of 2 (ACA, MO).
- **DRAWN: fast grower DLTR; steady name MO.** No pack was read before the draw.
- **A2, pre-registered from the live pack previews (`scratchpad\draw_previews\`) before any sample.**
  The rules file's sha256 (`50108fdf…`) is appended to the draw file.
  - **DLTR.** Q2 results (8-K, 2026-08-27):
    - diluted EPS $2.70, including a $1.31 benefit from tariff refunds;
    - fiscal-2026 adjusted EPS guidance of $7.70–8.05, including about $0.60 of tariff refunds;
    - the stock is down 10.1% in a month; a news headline reads "margin risks test its rebound".
    - Rule: "tariff refund" (or "refund(s) of tariffs", "IEEPA refund").
  - **MO.** The quarterly dividend was raised 4.7%, to $1.11 (2026-08-27). Full-year guidance was
    narrowed to $5.61–5.72 with a raised low end (2026-07-30).
    - Rule: "1.11" or a dividend increase ("dividend increase", "raised/increased its/the (quarterly)
      dividend", "dividend hike/raise").
- **What the previews show, written down before any sample (observations, not changes):**
  - **DLTR.**
    - The reference is $163.23 against a $116.95 price (1.40×); the targets are $98–170.
    - The +36.2% current-FY consensus EPS growth carries the one-off tariff refunds. The reference
      treats them as cash-flow growth, and the next FY is +1.0%.
    - The analyst has to recognise the one-off to land near the price. That is an A1/process test.
  - **MO.**
    - The reference is $108.79 against a $68.72 price (1.58×); the targets are $58–82.
    - Consensus grows 4.7% and 3.3%, then revenue growth is 0.9%. The standard fade then climbs to
      the 3.75% terminal-growth anchor at a 7.51% cost of equity, which implies a 27.6× exit.
    - That is the universal-anchor problem for a shrinking-volume business (the revision-11 family).
      The analyst needs a stated `terminal_reason` or `guidance_deviation_reason` to depart from it.
    - The BASE-YEAR CHECK is "not available": the vendor's year-ago revenue is on a different basis.
  - **Both.** RECENT COMPANY NEWS is mostly lifestyle and dividend-blog items (E17). Research relies on
    the analyst's own searches.
- **GPU run.** Started under the operator's delegation, with the gates above met: re-review passed,
  pool clean, packs read, A2 pinned, GPU idle. Started 02:56:40 KST. A watchdog for a hard stop at 08:40
  KST was armed. The operator then wrote (~03:05 KST) "let the run finish, don't force stop at 8:40",
  so the watchdog was removed and the run goes to completion.
- **During the run, recorded before any score (orchestrator, 2026-09-27 ~03:58 KST).**
  - **DLTR sample 1 was lost** at 03:53:13: "sample 1: FAILED HTTP Error 500".
  - The first three turns, from the Ollama log:
    - turn 1: 31,827-token prompt, 33,761 generated, 41 tok/s, speculative draft acceptance 0.57;
    - turn 2: 1,448 generated, acceptance 0.69;
    - turn 3: 33,559-token prompt, 64,743 generated at 58 tok/s, acceptance 0.975. It filled the
      window (n_tokens 98,303, truncated = 1).
  - Ollama returned HTTP 500 after 18m39s. Every earlier window-full turn in the logs, at 81,919, returned
    200 with done_reason "length". The server process is the same (0.34.2), and it logged no error line.
  - **Reading:**
    - The draft acceptance of 0.975, against 0.57–0.69 on healthy turns, means turn 3 was a
      repetition loop: the draft predicts repeated text almost perfectly.
    - The 500 at the window edge is a new failure shape. The harness treats it as an exception, not
      as `done_reason` "length", so neither the retry nor the forced report ran. The sample loop's
      handler recorded it as lost.
    - Candidate causes of the 500 (not yet tested): the peg-native chat parser failing on content
      cut mid-loop, or the batch-256 or 98,304 settings at the context edge.
  - **Under the rules fixed before the run, DLTR FAILS** ("every part a result": lost sample; and
    repeatability, with one sample left). Nothing was changed mid-run. The run continues with DLTR
    sample 2, then MO. The cause goes to the joint review.
- **Result, scored on the pre-registered marks (`score_draw_final.txt`, 2026-09-27 ~06:05 KST): DRAW FAIL,
  0 of 2.** The run took 02:56:40–05:58:15; the folders are the ones recorded in `folders.txt`.
  Provenance holds on both: the pinned commit, gate test, v31 model, revision 10, and thinking "high".

  | name | samples | base IVs vs price | reference | spread | failed marks | passed marks |
  |---|---|---|---|---|---|---|
  | DLTR | 1 of 2 (s1 lost) | $155.84 vs $114.07 | $163.23 | n/a | repeatability; gate v4 (`single_sample`, `sample_failed`); every part a result | A1, base on reference, fence and MoS, provenance, A2, process |
  | MO | 2 of 2 | $103.16 and $88.84 vs $68.82 | $108.79 | 16.1% (limit 15%) | repeatability; base on reference (s2 at 0.817×, with no `guidance_deviation_reason`) | A1, fence and MoS, gate v4, provenance, every part a result, A2, process |

  - **Human reads (orchestrator, to be checked in the joint review):**
    - A2: DLTR s2 treats the tariff refund as one-time; both MO samples name the 4.7% raise to $1.11
      on 2026-08-27.
    - The reason fields are substantive.
    - No BASE WINDOW CHECK was printed for either name.
  - **MO's split.** s1 kept the 3.75% terminal-growth anchor and argued it on pricing power. s2 set 2.5%,
    with a dated `terminal_reason` citing volume decline. This is the question flagged in the preview:
    the analyst disagrees with itself on whether the universal anchor fits a shrinking-volume business.
    The mark accepts only `guidance_deviation_reason`; it is not rewritten after the result.
  - **Room.** The report turns had about 60k tokens spare (59,937, 61,235 and 62,830). Only DLTR s1's loop
    filled the window. Long-turn medians ran 39.9–41.3 tok/s, with no spill. The research helper ran with
    thinking on without incident.
  - Per the procedure, a failure is diagnosed and never re-drawn. The joint review with Opus and a GPU
    reproduction of the window-edge 500 are running.

**Joint review of the draw (Opus 5.5 max, 2026-09-27 ~06:12 KST; orchestrator's findings reconciled).**
- **Scoring approved.** The reviewer's re-run of the pinned scorer is identical: DRAW FAIL, 0 of 2. Nothing
  should read OPEN, and the human reads hold. The Phase 4 gate is not passed.
- **Corrections to the orchestrator's findings, accepted:**
  1. DLTR s1's only desk call failed validation ("missing required inputs: shares_diluted"), so it had
     no desk result. Had the server answered "length", the full-thinking window retry would have run, not
     the forced report.
  2. The preview's expectation that DLTR would "land near the price" once the refund was recognised was
     wrong. A once-only refund of about $0.60 cannot close a $46 gap. s2 at 0.955× the reference is
     consistent.
- **DLTR s1, two failures:**
  - **The loop.** Draft acceptance was 0.975, against 0.51–0.65 on every other long turn. The sampler
    cannot see a loop longer than 64 tokens (repeat window 64, presence penalty 0.05, no DRY).
  - **The server error.**
    - The slot stopped cleanly ("truncated = 1", no decode or memory error), then HTTP 500.
    - All six window-full stops at 81,919 since the 09-20 upgrade returned 200. Four loops before the
      upgrade also returned 200, on an older build.
    - Loop text, or the 98,304/256 settings, as the trigger is still open; a looping reproduction is
      requested.
- **MO.** s1 is exactly the reference path. s2 lowered the terminal to 2.5% with a dated reason, so the
  exit falls from 27.6× to about 20.5×, which accounts for the 16% gap.
  - The default machinery caps years 3–5 at next-FY revenue growth (0.9%), then fades up to the 3.75%
    anchor forever. 50 of 279 book names (18%) get a path that rises more than 0.5 point into the anchor,
    and 28 have shrinking revenue.
  - s2's years 3–5 (3.0/2.8/2.5%) break the cap, and nothing checks that.
  - The base-on-reference mark (±15%) is stricter than the TASK and the harness (0.75–1.33×). It stands
    for this draw, since it does not change the result.
- **Fixes, blocking the next draw:**
  - **F1.** `_post` lets a 5xx escape. Record the turn and route it like a length stop with no output: the
    window retry without a desk result, the forced report with one. A second 5xx is
    `failed_reason = "server_error"`.
  - **F2.** Each turn gets `num_predict = min(NUM_PREDICT, ctx − estimated prompt − 2,048)`, so no turn
    reaches the window edge. `REPORT_ROOM_TOKENS` rises by 2,048 so the report's room is unchanged.
    There is no fixed per-turn cap.
  - **F4 (versioned text; needs the operator).** The tool definition says `shares_diluted` is "Required in
    firm frame" and lists only `price` as required. The desk requires it, with terminal_g, fade_years and
    sbc_treatment, in every frame. The first desk call failed this way in 19 of 28 samples, including all
    4 in the draw, and DLTR's loop began right after one.
  - **F5.** Flag years 3–5 above the cap.
  - **F6.** Align the base-on-reference mark with the TASK (0.75–1.33× or a reason), before the next
    draw's pre-registration.
  - **T1 (measured, then an operator ruling).** The default path never rises into perpetuity: below the
    anchor, the terminal default is the year-5 growth, and going higher needs a dated `terminal_reason`.
    Measure it across the book first.
  - **P1 (operator).** The population is exhausted. The record names all seven fast and steady names, and
    the other eight qualifying names are neither. A pool from the same 135 names is empty today, so the
    operator chooses a new population.
    - *Lesson, the orchestrator's error:* the pools were written into the record after the draw. Undrawn
      names stay out of the three documents from now on.
- **Not blocking:**
  - F3, a loop flag on length-ended turns (calibrated first); early stopping via streaming comes later.
  - Sampler changes (DRY, repeat window) are a versioned decision.
  - `depth_sanity`'s "invisible in consensus.json" wording is stale.
  - MO s2's 1.36× swing counts a bull-only desk run.
  - The server keeps up to 8 GB of prompt cache in RAM on a machine with about 12 GB.
- **What it shows.** The three completed samples passed every process mark the draw tested. Two landed on
  the reference, with about 60k tokens of room and no spill. Two names at two samples each cannot show
  whether the analyst is right about value.

**T1 measured (orchestrator, 2026-09-27 ~06:20 KST, `scratchpad	1_measure.py`; read-only, no GPU).**
- **Method.** 195 growth-method names across the book and the nominated list, with revision-10 inputs.
  For each, the ratio of the reference under the rule to today's reference.
- **The rule applies only when next-FY revenue growth is below the 3.75% anchor.** Three variants of the
  default terminal growth:

  | variant | names changed | median ratio | lowest ratio | negative terminal | MO |
  |---|---|---|---|---|---|
  | year-5 growth (the reviewer's T1) | 27 of 195 (14%) | 0.720 | 0.430 | 11 | 0.656 |
  | year-5 growth, floored at 0% | 27 | 0.752 | 0.653 | 0 | 0.656 |
  | year-5 growth, floored at 2.34% breakeven inflation (zero real growth) | 27 | 0.853 | 0.784 | 0 | 0.784 |

- **The weakness of plain T1:** it turns one year's consensus revenue growth into a perpetual rate. A
  company in a cyclical dip gets a permanent low terminal unless the analyst argues it up.
- **Orchestrator's recommendation: the breakeven floor.**
  - A company that cannot grow volume but keeps pricing with inflation is worth zero real growth by
    default. Anything below that, meaning perpetual real decline, needs dated evidence in
    `terminal_reason`, and so does anything above.
  - *Disclosed:* this variant was formed after seeing MO s2 choose 2.5% with a volume-decline reason. The
    rule is argued from economics, not from that sample. The operator rules with that in view.
- **Status.** T1 changes the reference and the default exit multiple, which the analyst reads. So it is
  a versioned decision (rule 7), for the operator.

**F4, the proposed text for the operator's approval (the desk tool definition in `analyst_tools.py`).**
- `shares_diluted`: "Diluted share count in billions. REQUIRED in every frame: the desk refuses a call
  without it. Use SECTION 2's shares outstanding unless you state a diluted count."
- The schema's `required` list becomes `["price", "shares_diluted", "terminal_g", "fade_years",
  "sbc_treatment"]`, matching what `financial_model_tool.py` refuses without.
- Evidence (reviewer): the first desk call failed on exactly these in 19 of 28 samples (all 4 in the
  draw), and DLTR s1's loop began right after one.

**The window-edge 500, reproduced on the GPU (2026-09-27 06:05–06:35 KST; `scratchpad
epro_500.py`,
`repro_loop.py`).** Each case fills the window with pack text and sends a tool definition, as the analyst's
requests do.
- **Ordinary text run into the edge answers 200 "length" at 98,304:**
  - batch 512, answer channel: 97,872 + 430 tokens;
  - batch 256, thinking channel: 97,908 + 396 tokens.
  So neither the window size nor the batch size produces the 500.
- **A request larger than the window is refused (HTTP 400, `exceed_context_size_error`), not trimmed.**
  Two cases overshot at 81,920. F2's prompt estimate and the report-room rule keep requests below the
  window.
- **A loop could not be forced.** An assistant turn prefilled with 60 repetitions, of a sentence and of a
  tool-call envelope, stopped at once (1 and 34 tokens), at both settings.
  - So the trigger inside a real loop is unconfirmed. The likeliest is the response parser on looped
    output.
  - It does not block: F2 stops every turn 2,048 tokens before the edge, where the server answers 200
    "length", and F1 routes any 5xx that still arrives.

**Built: F1, F2, F5 (Gemini, reviewed by the orchestrator; rs2 230c00d; 1161 tests pass).**
- **F1.** A 5xx is recorded on the turn (`server_error`, `http_status`) and routed like a length stop. A
  second one fails the sample with `server_error`.
- **F2.** Per-request `num_predict` is `min(configured, ctx − estimated prompt − 2,048)`, floor 1,024,
  logged per turn. `REPORT_ROOM_TOKENS` is 44,048.
- **F5.** The new flag is `years35_above_revenue_cap`. Dry run on the draw's saved data: it fires on MO
  s2 (3.0/2.8/2.5% against 0.9%), not on s1.
- The `depth_sanity` wording is fixed.
- **Waiting on the operator:**
  - F4, the tool-definition text;
  - T1, the terminal default;
  - P1, the next population;
  - the production-wide yes to revision 10.
- **F6** (the next draw's base-on-reference mark aligned with the TASK: 0.75–1.33× or a reason) goes
  into the next draw's pre-registration.
- A short review of 230c00d comes with the next draw's package.

**Operator rulings, 2026-09-27 ~09:15–09:25 KST.**
- **"Yes to all."** Approved:
  - F4, the desk tool text;
  - T1 with the zero-real-growth floor (breakeven inflation);
  - the next population: the screener's next-ranked names below the nomination cut;
  - revision 10.
- **"For revisions - Do not need my approval from now on please. You have my perpetual approval."**
  - This is the standing ruling for non-negotiable 7. Every PACK_REVISION is still bumped, recorded
    here with its reason, and checked by the Opus reviewer.
  - It does not extend to the other standing constraints: KIS_HALT, DEPTH_PAUSED, nothing published
    or put in production before Phase 6, secrets, CI.
- **"I am worried you're not finding solutions."**
- **"I am away for the next 12+ hours, so don't stop and get as much progressed as possible. I leave to
  the best of your judgement, but whenever you judge, invoke opus 5.5 max for reviewer of judgement."**
- **Orchestrator's response, recorded before acting:**
  - Stop the one-issue-per-GPU-test cycle.
  - Census every saved sample for mechanical defects first: `scratchpad\error_census.py`, 30 samples.
    The only live one is F4; the fetch encoding errors were already refused since E16.
  - Build every known fix in one revision.
  - Test on a larger pre-registered battery, so one run surfaces what remains.
  - The plan (J1–J6) went to the reviewer before execution.
- **Revision 11 (building):** F4, T1 with the floor, and a TASK bullet, "The desk does the arithmetic",
  the carried revision-11 item.

**Judgment review of the 12-hour plan (Opus 5.5 max, ~09:27 KST). Adopted as ruled:**
- **J1.** Fold in the through-cycle line with `base_cycle_reason`, and the desk's `finite_life_years`
  with `finite_life_reason`. Defer the maintenance floor, a book-wide doctrine change. Shadow legs are
  computed and stamped only, never printed to the model. Run C1–C3 and C6 on the pack's own function
  before wiring.
- **J2.** The population is `factor_scores.json` ranks 136–400, the next below the cut: 265 names, none
  vetoed.
  - A pool below 3 widens the rank window by 200, up to 1,000.
  - Sort each pool, then `rng.sample(pool, 3)`, fast pool first.
  - A pack-build failure excludes only that name. The draw stops if more than 5% of builds fail.
- **J3.** The battery is 3 fast and 3 steady names, 2 samples each.
  - Integrity marks must hold on all six: every part a result, provenance, fence and MoS, gate v4.
  - One judgment miss is allowed (repeatability, base on reference, A1, A2, process), and it is
    diagnosed.
  - F6 mirrors the TASK: 0.75–1.33× the reference, or `guidance_deviation_reason`.
  - Six names screen for systemic defects; they do not prove fitness.
- **J4.** No streaming detector and no sampler change. The scorer prints any turn of at least 10,000
  tokens faster than 52 tok/s.
- **J5.**
  - Development GPU checks on touched names while code is written: MO on revision 11; FSM and GPOR
    after the universal batch.
  - Changes to anything the model reads, the desk, the marks or the pool get a short re-check.
  - The full pre-registration is frozen and pinned before prep.
- **J6.**
  - F5 becomes `…_without_reason`, cleared by `guidance_deviation_reason`, and the TASK's "never above"
    becomes "above it needs guidance_deviation_reason with dated evidence". As built it would have
    failed LAMR s1–s3's evidence-backed departures.
  - The finite-life TASK text must ask for `guidance_deviation_reason`.
  - Correction: T1 still lets growth rise, from year-5 growth up to 2.34%. "Never rises into
    perpetuity" is wrong; the rise is capped at zero real growth.
  - The battery measures the "desk does the arithmetic" bullet: whether the first desk call came
    before research, and whether the final inputs equal the first call's.
  - The tooling is rebuilt and re-accepted for six names.
  - Nothing may move `screener-publish` during the run.

**Through-cycle line, pre-registered criteria computed (orchestrator, ~09:30 KST;
`scratchpad	hroughcycle.py`, the function the pack will call, and `throughcycle_criteria.py`).**
- **Data.** 132 of the 176 book names are scored. 39 have fewer than 8 complete years, and 5 have a
  fiscal-year base at or below zero.
- **C1 PASS.** Bucket medians: ≤50th percentile 1.055, 50–80th 0.908, >80th 0.555, monotone.
- **C2 FAIL.** One cell: Consumer Defensive, >80th, n=3, +0.222 from the bucket median. Cells under 3
  names are not scored, which is a disclosed choice.
- **C3 FAIL.** Only 59% of 44 steady compounders fall within [0.85, 1.15]; 80% is required.
- **C6 FAIL.** One named name sits just outside its bucket's p90 (0.939 against 0.874).
- **Diagnosis.** 71 of 132 names sit above their own 80th-percentile margin. A decade's median margin
  mistakes a margin TREND for a cycle, so improving companies read as "at a cyclical peak". That is
  the F2 failure the design itself warned of. As specified, the line would demand `base_cycle_reason`
  from most of the book and anchor compounders low.
- **Decision (pre-registered rule: stop and diagnose).** The through-cycle line does not go into
  revision 11 as specified.
- **One declared variant, written here before it is measured, against the SAME criteria.**
  - The company's cycle is measured around its own linear margin trend: an ordinary least-squares fit
    of margin on fiscal year over the held years.
  - The through-cycle margin is the trend value at the latest year.
  - The percentile is the latest year's residual among the record's residuals.
  - Rationale: a cycle is a deviation from trend, and improving companies sit on their trend.
  - If this variant also fails any of C1–C3 or C6, the through-cycle line is dropped for this
    battery, and the design goes back to the reviewer. No further variants are tried.
- **The declared variant, measured (~09:31 KST; `throughcycle_criteria.py --detrended`).**
  - C1 PASS: bucket medians 1.113 / 0.936 / 0.543, monotone.
  - C2 PASS: every scored cell within ±0.150.
  - **C3 FAIL:** 70.5% of 44 steady compounders fall within [0.85, 1.15].
  - **C6 FAIL:** one named name at 0.807 against its bucket's p90 of 0.792.
  - **As declared, the through-cycle line is dropped for this battery.** The design goes back to the
    reviewer. The detrended version is the better measure (C2 now passes, and C3 rose from 59% to 71%),
    but it does not meet the pre-registered bar.
- **What stays in revision 11 from the universal design:** the desk's optional `finite_life_years`, with
  `finite_life_reason` and a TASK sentence asking for `guidance_deviation_reason` when a finite life moves
  the value off the reference. It is an option, never a default, so there is no whole-book criterion.
- **Known risk carried into the battery.** A cyclical producer at a peak margin is still valued by
  perpetuity unless the analyst declares a finite life or a lower base. The integrity tier (fence and
  MoS, gate v4) fails the battery on such a valuation rather than hiding it. The FSM and GPOR
  development runs will show whether the finite-life option is used.

### The battery, pre-registered (orchestrator, 2026-09-27 ~09:41 KST; before any prep result, pool or draw; per review J2–J6)

- **Purpose.** Screen revision 11 for systemic defects on six untouched names. It does not prove fitness:
  a system that passes 80% of names still passes 5 of 6 about two-thirds of the time.
- **Population.**
  - `factor_scores.json` of the dual-door run of 2026-09-23T16:25:19Z, the run whose nominations are
    ranks 1–135. It is read with `git show` from publish commit 4b382bd and pinned in the draw file as the
    population source commit. *Amended before any pool (~09:44 KST), see the note below.*
  - Names not vetoed, not nominated, with `fct_rank` 136–400 (265 names).
  - If either pool has fewer than 3 names, the window widens by 200 ranks, up to 1,000.
- **Exclusion.** Any ticker whole-word in the three documents at pool time.
  - Pool names are written only to the scratchpad draw file, never to the documents. Only the six drawn
    names enter the record, after the draw.
- **Data.** A full enrich record and an openbb cache fetched on the pool's day (`prep_battery_data.py`,
  ranks 136–600).
  - A name without them, or whose pack build fails, is excluded and listed.
  - The draw stops if more than 5% of the pool fails either way.
- **Data conditions and pools.** As in the 2026-09-27 draw:
  - the reference is printed;
  - at least 3 next-FY EPS analysts;
  - at least 8 years of history;
  - the vendor's same-year net income matches within 2%;
  - a usable street band;
  - fast pool: g1 ≥ 0.30 and q ≥ 1; steady pool: |g1| ≤ 0.10.
- **Draw.** Each pool sorted; `rng = random.Random(20260928)`; `fast = rng.sample(fast_pool, 3)`, then
  `steady = rng.sample(steady_pool, 3)`. Script: `draw_20260928.py`.
- **Code.** The rs2 commit that carries revision 11, including the finite-life desk option, after the
  reviewer's package check. *Amended ~14:00 KST, before any pool, per the ruling above: revision 12,
  which adds the required cash-flow-life decision, subject to its development bars.* It is pinned in `draw_20260928.txt` with:
  - the scorer, `draw_check_b.py`, `run_battery.sh` and the draw script;
  - the v31 system digest;
  - the documents and the MRI files.
- **Run.** `run_battery.sh`: the six names, 2 samples each, gate-test mode, the production path, v31, no
  API keys, an idle GPU at the start, and the tree check before each name.
  - The crash rule of 2026-09-27 applies (one re-run after diagnosis; a second crash FAILS). A stop is a
    crash (F3).
- **A2.** Each drawn name's development is set from its live pack preview before any sample, in
  `draw_a2_rules_b.json`, with its sha appended to the draw file.
- **Marks per name** (`score_battery.py`), as in the draw, except:
  - pack revision 11 (*amended: 12*);
  - **F6:** base on reference = 0.75–1.33× the printed reference (the named window's), or
    `guidance_deviation_reason`, mirroring the TASK;
  - A1 adds `years35_above_revenue_cap_without_reason` and `finite_life_without_reason`
    (*amended: and revision 12's `cash_flow_life_missing` and `finite_life_mismatch`*).
- **Battery verdict (tiered, J3).**
  - **Integrity marks must hold on all six:** every part a result, fence and MoS, gate v4.
  - **Provenance:** a failure means the run is not evidence, so the battery is OPEN.
  - **Judgment marks:** at most one name may miss (repeatability, base on reference, A1 clean, A2,
    process). The miss is diagnosed; a systemic cause becomes a Phase 6 preflight item.
  - Any open mark or unscored name leaves the battery OPEN.
- **Reported, not scored:**
  - turns of at least 10,000 tokens faster than 52 tok/s (loops);
  - whether the first desk call preceded research, and whether the final desk inputs equal the first
    call's (measuring the "desk does the arithmetic" bullet);
  - long-turn median speed (spill);
  - report continuations and whole-sample retries.
- **OPEN names.** A provenance failure scores OPEN. An OPEN name may be cleared by one re-run under the crash
  rule, recorded. A second OPEN on the same name leaves the battery for the operator.
- **Acceptance.** `sim_battery\sim_battery.py`, run before the pool: 11 per-name cases and 7 six-name
  sets, all as expected. *Now 17 per-name cases (the reviewer's three, revision 12's two flags and a
  wrong-revision name) and 10 sets, all as expected.*
- **Nothing moves `screener-publish` during the run:**
  - DEPTH_PAUSED stays on;
  - no on-demand requests;
  - the Sunday 19:35 KST screener fetch is a GitHub job in the runner's own folder;
  - the tree check stops the run loudly if the clone moves.
- **Note (~09:44 KST, before any pool): the publish clone moved.**
  - The MO development run was started without `RS2_SCREENER_DATA_COMMIT`. `depth_pipeline` then
    refreshed the clone to f62d164, the latest scheduled data. Nothing was published; the refresh pulls
    data only.
  - The clone now holds a newer engine run (2026-09-26T12:12:15Z) that nominates 161 names scattered over
    ranks 1–1,198. "Next below the nomination cut" is well defined only in the pre-registered run, so the
    population stays that run's, read from 4b382bd.
  - The packs read the clone's current, newer data, which is pinned at draw time.
  - The first prep had read the new run's list. It was stopped at 36 names and restarted on the pinned
    run's 465 names (ranks 136–600).
  - From now on every development run exports `RS2_SCREENER_DATA_COMMIT` (the clone's current commit),
    as `run_battery.sh` does, so nothing moves the clone again.
  - The 2026-09-27 two-stock draw is already scored. Its tree check would now report the moved clone if
    re-run; its recorded result stands.
- **Reviewer's check of the population decision (~09:45 KST): approved, with conditions, adopted.**
  1. The pool is computed at ranks ≤ 400 first, and widens only by the pre-registered rule.
  2. The pool reads only population names, and the pool-day prep refetches any overlap with the 36
     records fetched from the wrong list.
  3. Development runs export `RS2_SCREENER_DATA_COMMIT` and `RS2_RUN_SOURCE=gate_test`, and run only in
     `rs2-P4-dev`. The MO run already under way uses `test`, also a non-production ledger.
  - The refresh is recorded as an incident. It was a pull into the publish clone, not a publish, so no
    rule was breached.
- **Added to the battery pre-registration:** a provenance failure scores OPEN, not FAIL (the run is not
  evidence). An OPEN name may be cleared by one re-run under the crash rule, recorded as such. A second
  OPEN on the same name stays OPEN, and the battery goes to the operator.

**Development runs: pass bars, written before any result is read (2026-09-27 ~09:46 KST).** These are
development runs on touched names, not evidence. The bars are stated first so the runs inform.
- **MO (revision 11, running):** both samples in the same direction, spread ≤ 15%, and each base within
  0.75–1.33× the new $85.25 reference, or with `guidance_deviation_reason`.
- **FSM and GPOR (revision 11 with finite life):**
  - finite life declared, with evidence, where the business depletes;
  - each base inside the street fence;
  - a margin of safety of at most 150%.
- **Stop rule.** If FSM or GPOR still land outside the fence with finite life available, the battery does
  not start. The case goes back to the reviewer, because any producer the draw picks would fail an
  integrity mark for a known reason.

**Revision 11 built (2026-09-27 ~09:52 KST).**
- **eea401b:** F4, T1 with the zero-real-growth floor, the "desk does the arithmetic" bullet, and F5
  renamed `…_without_reason` with its TASK sentence.
- **24923eb:** the finite-life desk option, with its schema, TASK bullet, contract field, stamp and A1
  flag.
- 1177 tests pass.
- **Dry runs:**
  - MO's pack prints a 2.34% default, a 19.80× exit and an $85.25 reference; DLTR's and UGI's are
    unchanged.
  - GPOR s1's inputs over a 15-year life: desk $186.43, an independent calculation $186.44.
- The package went to the reviewer (J5), in parallel with the development runs.

**Package review (Opus 5.5 max, ~10:00 KST): approved with conditions. The battery commit waits on the
development bars.**
- **B1, fixed.** The battery verdict mis-scored three cases. It now classifies each name once:
  1. a crash-rule FAIL;
  2. not evidence (provenance failed or no verdict), which is OPEN and kept out of both FAIL lists;
  3. evidence, to which the tiered tests apply.
  The reviewer's three cases joined `sim_battery`: 14 per-name cases and 10 six-name sets, all as
  expected.
- **B2 (after prep).** Move `rs2-P4-bat` to the battery commit and add the `research-venv` junction.
  `config.json` stays at HEAD for the pool, and the model line is switched after the previews.
- **B3.** The pool is computed today (KST): prep stamps records with today's date.
- **B4, the stop rule extended before any result is read.** If MO's two samples miss their bar under T1,
  the battery does not start either; low-growth steady names would miss repeatability for the same known
  reason. The case goes back to the reviewer.
- **Carried and done: 63c8245.** A finite life written as 15.0 or "15" is accepted as that integer
  (1178 tests pass). 63c8245 is the battery-commit candidate. It differs from the development runs'
  commits only by this coercion (24923eb for FSM/GPOR) and by the finite-life option (eea401b for MO).
- **Carried to the next revision:**
  - an annuity flow combined with a finite life is still valued as a perpetuity (refuse the
    combination, or cut the annuity at the life);
  - the Finite Life bullet should say that `terminal_g` there is the growth of the remaining years.

**Development run MO on revision 11 (eea401b, rs2-P4-dev; 2026-09-27 09:36–11:17 KST): passes its bar.**
- Samples: $91.15 (1.069× the $85.25 reference) and $80.84 (0.948×), against a $68.82 price. Both are
  undervalued, with a spread of 12.8% (the draw had 16.1%).
- Both use the new 2.34% terminal default (gap 0 bp), with no `terminal_reason` needed, so T1 closed the
  split.
- No sample failed, no reduced thinking, no window retry.
- It flags `research_repeats_2_of_10` (E17, open).
- Incident noted earlier: this run refreshed the publish clone (no data-commit pin); run source `test`.

**Through-cycle redesign (Opus 5.5 max, ~11:30 KST; not for this battery; no GPU;
`scratchpad\opus_p4_ft	hroughcycle\`).**
- **Method.** Three candidates were declared and hashed before measuring, each measured once against the
  unchanged C1–C3 and C6:
  - B: the median of the last 5 years, each carried along a robust trend;
  - A: the robust trend value in the latest year;
  - C: the latest margin unless a fall is on record.
- **Result.** None passes all four; the best (B) reaches C3 at 75% against the 80% required. Nothing is
  proposed.
- **The data gap matters more.** The three depleting producers of (b) have no fiscal year with revenue,
  net income, D&A and capex all present; capex is missing. Any through-cycle formula prints "not
  available" for exactly the names it was built for. They stay protected by the finite-life option and
  the fence gate.
- **Criteria flaws (post-hoc, with numbers):**
  - **C6:** six named names that are ordinary members of their buckets would all land within p10–p90
    only 26–39% of the time, and the test is two-sided.
  - **C3:** 12 of its 44 "steady compounders" have an unusual latest year. On the other 32, B scores
    93.8%.
  - **C2:** on 3–5-name cells it passes random sector labels only 58–80% of the time.
  - **C1:** its bucket, read literally as the latest-year percentile, cannot be met by any trend-aware
    measure.
- **Rulings for the operator (later):**
  - may the record use the pack's labelled vendor-capex fallback for years with no filed capex;
  - which C1 bucket reading is meant;
  - a re-registered C3 and C6.
- **Clean path.** Re-register the criteria, then run B once on histories it was never measured on (for
  example, the battery population after the pool is drawn), and adopt it only if it passes there.
- The book names in the reviewer's files stay out of the documents until the pool is computed.

**Development runs FSM and GPOR on revision 11 with finite life (24923eb, rs2-P4-dev2, gate_test, data pinned
f62d164; 2026-09-27 11:20–13:52 KST), against the bars written before them.**
- **FSM: fails.**
  - $35.38 against an $11.69 price: margin of safety +203% (limit 150%), above the street fence's
    $26.36 high, and flagged at 2.68× the analyst high.
  - No finite life was declared. Its `guidance_deviation_reason` anchors on company guidance and a new
    mine's ramp, at the 3.75% perpetual terminal.
- **GPOR: half-passes.**
  - $225.29 against $154.62: inside the fence ($81.82–460), margin of safety +45.7%, 0.946× the $238.14
    reference, with the T1 default of 2.34%.
  - No finite life was declared, although the record puts its drilling inventory at about 15 years.
- **Both:** one sample each, no failure, no reduced thinking.
- **Stop rule applied.** FSM lands outside the fence with finite life available, so the battery does not
  start. The option exists, but the analyst does not consider it, and the pack gives no prompt to decide
  a business's cash-flow life. The case goes to the reviewer.
- *Correction (reviewer):* under the bars as written, GPOR failed too. The first bar item was "finite life
  declared, with evidence, where the business depletes". Both names missed their bars.

**Ruling (Opus 5.5 max, ~13:55 KST): build revision 12 with a required cash-flow-life decision. No battery
on revision 11.**
- **Why.** On revision 11 a drawn producer gives either a false pass or a known-cause fail. GPOR, as a
  perpetuity, would pass every battery mark while being unsound, because the marks never check a
  business's life.
- **The TASK decides by economics, not industry.** Cash flows end when they come from extracting a finite
  stock or from a right that expires, unless the filings show the stock or right is replaced out of the
  capex the base already deducts.
  - The life is filed reserves ÷ current production, or the remaining term, with the filing's date.
  - A perpetual value must deduct the capex that replaces what the business depletes.
  - Where revenue moves with a quoted commodity price, the reason states the price deck and its source. A
    spot price held for the whole life needs evidence.
- **Contract and harness.**
  - `cash_flow_life` ("perpetual" or years) and `cash_flow_life_reason` are required for every name.
  - A1 flags:
    - `cash_flow_life_missing`, which also fires on an empty or "null" reason;
    - `finite_life_mismatch`, checked on Base, Bull and Bear of the final desk run.
  - The battery scorer adds both flags and requires pack revision 12, and the pre-registration is
    amended before the pool.
- **Development bars for FSM and GPOR, revision 12, 1 sample each** (unchanged, plus one item), written
  before the runs:
  - the analyst declares a finite `cash_flow_life` citing filed reserves (FSM: reserve life; GPOR: drilling
    inventory) and passes it to the desk in every scenario;
  - each base inside the street fence;
  - margin of safety ≤ 150%.
- **Outcomes, written before the runs:**
  - **Either name declares perpetual:** the requirement does not bite. Back to design; no battery tonight.
  - **FSM declares a finite life but sits above the fence, holding spot gold for the whole life:** the
    price-deck gap remains. No battery tonight; the operator chooses tomorrow between a price-deck design
    and a battery scoped to exclude producers. Tonight's GPU runs development checks on touched names
    under revision 12: AU, and one ordinary (b) compounder.
  - **Both bars met:** move `rs2-P4-bat` to revision 12 and compute the pool before about 22:00 KST.
- MO need not be re-run: under revision 12 it only declares "perpetual" with a reason, and the battery
  measures that.

**Revision 12 built (2e115f9; 2026-09-27 ~14:10 KST; 1183 tests pass).**
- The TASK "Cash-Flow Life" bullet is the reviewer's text, verbatim.
- `cash_flow_life` and `cash_flow_life_reason` are carried through the scorecard, the medoid summary and
  the verdict. The verdict writer's field list also gains `finite_life_years`, which revision 11 had
  missed (non-negotiable 5).
- The A1 flags `cash_flow_life_missing` and `finite_life_mismatch` replace `finite_life_without_reason`.
- The battery scorer requires revision 12 and carries both flags.
- The FSM and GPOR re-runs started at 14:12 in `rs2-P4-dev2` (gate_test, data f62d164). The reviewer's
  short diff check runs in parallel.
- **Reviewer's short check: one blocker, fixed in f622796** (1184 tests pass).
  - `finite_life_mismatch` read the last desk call even when the desk had refused it; MO s2 of the draw
    ended on "call budget exhausted". It now judges the last completed run, with a test.
  - Everything else was verified.
  - f622796 is the battery-commit candidate. The FSM and GPOR bars do not depend on this fix, since they
    read the declared life, the fence and the margin of safety.

**FSM and GPOR on revision 12 (2e115f9, rs2-P4-dev2; 14:12–16:12 KST): both declared "perpetual". The
requirement did not bite. Per the outcome written beforehand: back to design, no battery tonight.**
- **FSM:** $38.91 against $11.69, margin of safety +233%, above the fence.
  - `cash_flow_life` "perpetual": replacement is claimed through a new mine and reserve growth "funded by
    capex already deducted from the base CF".
  - The deck is gold at about $4,200–4,500 (spot $4,284) held flat through year 10, then 3.75%. That is
    spot held for the life.
- **GPOR:** $235.95 against $154.62, inside the fence, margin of safety +52.6%, 0.991× the reference.
  - "Perpetual": about 15 years of inventory, "replaced" by base and acreage capex.
  - The gas deck is stated ($3.0–3.2/mcf).
- **Reading.** The escape clause ("unless the filings show the stock or right is replaced out of the capex
  your base already deducts") is used as a claim, not shown from filings. And for FSM, a spot deck held for
  the life, which the rule says "needs evidence", passed without any.
- **The prepared population data** (stamped 2026-09-27) is re-fetched on the day the pool is computed.

**Development runs tonight, while design goes back to the reviewer (bars written before the runs, ~16:15
KST; revision 12 at f622796, data pinned f62d164, gate_test, 1 sample each, in `rs2-P4-dev2`):**
- **AU (the third producer):** a finite `cash_flow_life` citing filed reserves, passed to the desk in every
  scenario; the base inside the fence; margin of safety ≤ 150%. Informative only.
- **LAMR (an ordinary (b) compounder):** revision 12 leaves it alone.
  - It declares "perpetual" with a reason, with no `cash_flow_life_missing` or `finite_life_mismatch`.
  - Its base is within 0.75–1.33× the reference, or has `guidance_deviation_reason`.
  - Its margin of safety is ≤ 150%.

**Ruling (Opus 5.5 max, ~16:15 KST): a temporary depleting-producer class, gated and out of the battery's scope
(option A); B rejected; C is the producer project.**
- **Why not B.** Revision 12 shows that this model asserts escape clauses rather than evidencing them, so
  more prompt text will not bind.
- **The class:** revenue from extracting a finite stock, priced on a commodity.
  - It is read from the `industry` field of the screener's `stocks.csv` at the pinned clone commit.
  - Industries in it: Oil & Gas E&P, Oil & Gas Integrated, Gold, Silver, Copper, Other Precious Metals &
    Mining, Other Industrial Metals & Mining, Thermal Coal, Coking Coal, Uranium.
  - Left out: midstream, drilling, equipment and services, and refining, since none extracts; steel,
    aluminium and agricultural inputs are revisited in C.
- **The gate: GATE_VERSION 5, reason 16 `depleting_producer_unsupported`.**
  - `stamp_and_route` stamps `producer_class` on every verdict.
  - The classifier fails closed: a table that cannot be read gives
    `depleting_producer_class_unavailable`.
  - A name with no row gets the information flag `producer_class_unknown`; there are none in the
    population today.
- **Recorded as a judgment made under the operator's delegation, for the operator's confirmation.** In
  production it makes every producer verdict non-actionable. That changes nothing today, because trading
  is halted.
- **C, the producer project, comes next:**
  - a filed reserve-life line in the pack;
  - a printed futures-strip deck as the default price;
  - a finite-life value computed by the harness, shown beside the perpetual one;
  - the vendor-capex fallback in the own-record data.
- **Conditions for tonight's battery:**
  - AU and LAMR come back as expected; if LAMR omits `cash_flow_life`, stop;
  - the pinned commit carries the `finite_life_mismatch` fix;
  - the scorer expects pack revision 12 and gate version 5;
  - the reviewer does a short check of the gate diff and the new acceptance cases.
- **Battery pool amendment (written ~16:16 KST, before any pool):** "Amended before any pool (2026-09-27,
  ~16:16 KST): names whose industry in `stocks.csv` (screener-publish f62d164, pinned in the draw file with its
  sha256) is in the depleting-producer class (Oil & Gas E&P, Oil & Gas Integrated, Gold, Silver, Copper,
  Other Precious Metals & Mining, Other Industrial Metals & Mining, Thermal Coal, Coking Coal, Uranium) are
  excluded from the pool and listed in the draw file. A name with no row or an empty industry is also
  excluded (none today). Reason: revisions 11 and 12 did not make the analyst value depleting producers
  soundly (FSM, GPOR: perpetual values at spot decks), and gate reason 16 makes their verdicts
  non-actionable. The battery measures the system on the names it is built for; its report states that
  depleting producers are out of scope. The class and the gate end when a producer design passes its own
  pre-registered test." Provenance also requires gate version 5.

**Option A built and checked (2026-09-27 ~16:35 KST).**
- **819988d:** `producer_class` fails closed; the stamp is written in `stamp_and_route`; GATE_VERSION 5;
  reason 16.
- **05e771e:** the reviewer's carried items. A bad byte makes the table unavailable, and any unknown class
  status fails closed. 1198 tests pass.
- **Tooling:**
  - the draw script checks its class list against the pinned tree's `depth_gates.DEPLETING_INDUSTRIES`
    and refuses the draw if they differ;
  - the scorer's gate mark is relabelled "gate v5";
  - `sim_battery` has 19 per-name cases and 11 sets, all as expected, including a producer that slips
    into the battery, which FAILS it.
- **Reviewer's short check: OK, no blockers.** 05e771e is the battery commit, subject to AU and LAMR.
- **Watch at pool time:** excluding producers shrinks the fast pool most. Widening beyond rank 600 would
  need same-day prep of ranks 601 and up.
- **Reserve prep done (16:36–17:08 KST):** ranks 601–1000 of the pinned run, 400 of 400, same day.
  The draw widens only by its pre-registered rule; this data is used only if that rule reaches it.

**Development runs AU and LAMR on revision 12 (f622796, rs2-P4-dev2; 16:13–18:22 KST), against the bars written
before them.**
- **AU (a producer, informative): "perpetual" again.**
  - $233.54 against $99.03, margin of safety +135.8%, inside the fence at 1.83× the analyst high.
  - Replacement is claimed through new reserves and a project, the same pattern as FSM and GPOR. This
    confirms the class decision: producers are gated (reason 16) and out of the battery's scope.
- **LAMR (ordinary compounder): meets its bar.**
  - "Perpetual", with a sound filed reason: permits and leases, fleet maintained out of deducted capex, no
    depleting reserve.
  - No `cash_flow_life_missing` and no `finite_life_mismatch`.
  - 0.842× the reference, margin of safety +17.0%.
- **Observation, written before the pool:** LAMR tripped `years35_above_revenue_cap_without_reason` (A1),
  going above next-FY revenue growth in years 3–5 without `guidance_deviation_reason`. That is 1 of the 5
  revision 11/12 development samples that print a cap (MO dev s1 and s2, GPOR, AU and LAMR); FSM had no
  reference. In the battery it counts as a judgment miss, and only one is allowed across six names.
- **Conditions for tonight:** LAMR declared `cash_flow_life`; the pinned commit carries the mismatch fix;
  the scorer expects revision 12 and gate v5. All are met. The go/no-go goes to the reviewer with this
  observation.

**Go/no-go (Opus 5.5 max, ~18:23 KST): GO. The expected outcome for the years 3–5 mark is written down before the
draw (~18:24 KST).**
- **LAMR's trip is a real compliance miss.** The pack printed a +3.9% next-FY revenue growth and a
  +3.9% / +3.9% / +3.9% default path. LAMR used 6.0% / 5.0% / 4.5%, with no `guidance_deviation_reason`:
  it faded from its own year-2 rate of 8%. MO s2 in the draw did the same.
- **Expected outcome.** Of the revision 10–12 samples that printed a cap, 2 of 8 went above it without a
  reason. At that rate about 40% of names miss the mark, so there is roughly a 70% chance that two or more
  of the six do, which fails the battery on judgment marks alone.
- **If that happens, the diagnosis is known.** The analyst carries its year-2 growth into years 3–5. The fix
  is mechanical, not more text: the desk applies the pack's default years 3–5 unless
  `guidance_deviation_reason` is given. That fix is re-tested on a new draw.
- **Why go rather than hold:**
  - the rule is stated and the default path is printed, and every text-only fix this session was asserted
    rather than followed;
  - a revision 13 now would be untested and would blur what the battery measures;
  - the battery still yields the other marks on six untouched names, and it measures this rate on them.
- **Confirmed:**
  - AU supports the producer exclusion: it would have passed both integrity marks while unsound;
  - 05e771e differs from f622796 (the code of the AU and LAMR runs) only in the gate, the class-table
    handling, the scorer label and the draw script. Nothing the model sees changed.

- **B5, the crash rule (approved).** A crash (a program error, rc ≠ 0) produces no result. It is neither a
  pass nor a "not a result" sample.
  - The run stops and the cause is diagnosed.
  - The analyst code and the draw pins are not changed; only an environment fault, such as Ollama or the
    network, may be fixed.
  - Then the name is re-run once with `run_draw.sh --rerun NAME`, and the scorer scores that folder.
  - A second crash of the same name is a FAIL.
  - An exception inside a sample is no longer a crash: it is a lost sample, and the name FAILS (C3).
  - **F3.** A run stopped by hand, for example at the operator's 6-hour limit, is a crash. Before
    `--rerun`, append `NAME first <its folder>` to `draw_logs/folders.txt` for the stopped name.
    Otherwise the unrecorded folder leaves every later score OPEN. The orchestrator watches the time
    limit, because the script has none.

**The battery draw (computed 2026-09-27 ~18:25 KST; `draw_20260928.txt`).**
- **Pins.** rs2 `05e771e`, screener-publish `f62d164`, and the population read from `4b382bd`.
- **Pool counts:** population 265; design-touched 15; producer class 14; pool 236; data conditions met 102;
  fast pool 17; steady pool 33.
- **DRAWN: fast EZPW, ASTH, CXW; steady DAL, UFPT, PCRX.** No pack was read before the draw.
- **A2, pre-registered from the live pack previews (`scratchpad\draw_previews_b\`) before any sample.**
  - The orchestrator drafted the rules. The reviewer (Opus 5.5 max, ~18:50 KST) approved them with
    conditions:
    - DAL's development was changed;
    - keywords were added where the draft was too tight, measured against 36 earlier reports on 12 other
      names.
  - The rules file's sha256 (`9ddb4a14…`) is appended to the draw file.
  - The keyword is necessary. The human read is the second half of the mark, and its test is written
    here, before any sample:
  - **EZPW.** Fiscal Q3 2026 (8-K 2026-08-05):
    - record pawn loans outstanding of $387.2M;
    - revenue +34.7% to $418.8M;
    - adjusted EPS $0.47 against $0.39 expected.
    - Rule: the figures, "record pawn/PLO/quarter/results", or naming the fiscal third quarter.
    - Human read: a sentence names these results. A copied table row alone does not count.
  - **ASTH.** The "material" cyberattack and data breach the company disclosed in September; the shares
    fell and law firms are investigating.
    - Rule: "cyber", "data breach", "security breach", "ransomware", "unauthorized access", "security
      incident", "social engineering", "hack".
    - Human read: names the 2026-09-23 cyberattack or breach. A generic cyber-risk line does not count.
  - **CXW.** CEO Patrick Swindle stepped down for health reasons, and Lucibeth Mayberry was named CEO
    (2026-09-25). The shares fell 3–4%.
    - Rule: the names, or a CEO or leadership-transition phrase.
    - Human read: names Swindle's resignation and Mayberry's appointment.
  - **DAL.** The fuel shock against Delta's affirmed 2026 guidance: earnings +20% "overcoming a
    multi-billion dollar fuel headwind", and September-quarter EPS of $2.00–2.50.
    - Next-FY EPS fell from $8.79 to $8.53 in 30 days.
    - The world-news section carries the Hormuz closure and oil above $100.
    - Rule: "fuel", "earnings by 20", "20 percent", "2.00 to", "2.00-", "11 to 13".
    - The keyword does not discriminate: "fuel" appears in 17 of 36 other-name reports. DAL's A2 therefore
      rests on the human read.
    - Human read: names the current fuel shock (Hormuz, oil at or above $100, jet fuel) as it bears on
      Delta's earnings, or the affirmed +20% guidance set against it. A generic fuel-volatility line does
      not count.
  - **UFPT.** Record Q2 (8-K 2026-08-03):
    - net sales $174.0M, +15.1%;
    - net income $20.9M, +21.4%;
    - 3 up revisions in 7 days.
    - Rule: the figures, "record q2/second/quarter/sales/revenue/profit/results/net income", or "second
      quarter".
    - Human read: a sentence names the record Q2 results. A table row alone does not count.
  - **PCRX.** The iovera° divestiture to Zimmer Biomet reset 2026 revenue guidance to $735–760M, from
    $745–770M (8-K 2026-08-04).
    - Next-FY EPS fell from $3.65 to $3.44, with 6 down revisions in 30 days.
    - Rule: "iovera", "zimmer", "divest".
    - Human read: names the iovera divestiture.
- **Observations, written down before any sample (not rules):**
  - **DAL.** A flight-attendant union drive (2026-09-09). This was the orchestrator's first choice. The
    reviewer overruled it: it was a letter from senators with no company action, and it is tied to neither
    the price nor the estimates.
  - **ASTH.**
    - A GlassHouse short-seller report (−2%) and law-firm investigations.
    - The screener's quarterly data holds ASTH only through 2026-03-31; the other five run to 2026-06-30.
      ASTH's Q2 release is dated 2026-08-06 (revenue $972.5M, +49%). An ASTH miss on the base check, or a
      split in base choice, may come from the data rather than the analyst. Whether ASTH filed its Q2 10-Q
      late is to be checked on EDGAR after the battery.
  - **CXW.** Updated 2026 EPS guidance includes a one-off gain from four facility sales, and $608.5M of
    debt repayment. That tests the analyst the way DLTR's tariff refund did.
  - **PCRX.** Short interest is 27.27% of float, 14.83 days to cover.
  - **UFPT.** The "margin story gets complicated" and "labor problems" pieces.
- **Tie-break for future draws (reviewer).** Materiality means evidence in the company's own numbers or in
  estimate revisions. How prominent an item is in the news only breaks ties.

**The F5 desk fix, designed while the battery runs (reviewer, Opus 5.5 max, ~19:20 KST; before any battery
result).** Brief: `scratchpad\brief_f5_desk.md`.
- **What happens with it.**
  - It is being built now in a separate worktree, `rs2-P4-r13`, branch `review-2026-09/phase-4-rev13`.
  - It is used only if the battery is scored with F5 misses. If the battery passes, the design is shelved.
  - Nothing in the battery's tree changes.
- **Corrections to the record:**
  - The desk budget is 5 completed calls (`max_model_calls=5`), not 8. Validation errors do not count
    against it, up to 6.
  - MO sample 2 of the draw ran on revision 10, whose pack has no F5 sentence; that sentence came in
    revision 11. LAMR on revision 12 is the only miss made under the rule's text.
- **Part of the cause is a text defect.** The contract's `guidance_deviation_reason` description lists only
  two triggers: the year-2 level and the consensus value. LAMR's report checked that list and wrote "No
  guidance_deviation_reason triggered".
- **The design, PACK_REVISION 13 (desk and text).** It supersedes the GO note's "the desk applies the
  pack's default years 3–5".
  - **The clamp.** For each Base DCF (every scenario not named Bull or Bear, and a top-level single DCF),
    the desk takes each applied year 3–5, including fade and terminal years, and holds it at min(requested,
    next-FY consensus revenue growth). It does this unless the call carries `guidance_deviation_reason`.
  - **Why a clamp and not the fade path.** Replacing the path with the pack's fade path is not monotone: on
    a synthetic fast grower, a request 0.02 points over the cap would lose 31% of the value. The clamp is
    continuous.
  - **Annotated, not refused.** The value on the requested path is printed beside the desk value. It is
    never a desk value.
  - **No cost to the run.** No desk call is spent on the rule, and no sample can fail because of it. Bull
    and Bear are never changed.
  - **The cap reaches the desk as harness context, never as a model argument.**
  - **The contract's reason stays the single owner.**
    - `years35_above_revenue_cap_without_reason` is unchanged.
    - The desk-to-contract match uses the path the desk valued.
    - A new information flag, `years35_capped_by_desk`, is not part of A1.
  - **Text.** The TASK sentence and the `guidance_deviation_reason` description name the years 3–5 trigger.
  - **Recorded regressions:**
    - MO sample 2, Base $88.84 → $82.74;
    - LAMR, Base $168.45 → $161.62;
    - Bull and Bear unchanged.
- **Before any GPU run on revision 13:**
  - the reviewer's diff review;
  - the full suite;
  - a replay proof on every recorded desk call plus the battery's. Compliant calls must be identical,
    capped values must equal the prototype, and Bull and Bear must be unchanged.
- **Development run (recommended, not evidence).** One sample on the battery name with the largest F5
  excess. Its bars are written first:
  - the final Base is a desk value;
  - the contract path is the valued path, or a reason is in both the call and the contract;
  - no budget exhaustion from a re-call;
  - no ordering violation.
- **The retest, pre-registered now.**
  - A new draw by the battery's own rule and script, with the same population (4b382bd, ranks 136–400),
    data conditions and strata (3 fast, 3 steady). The seed is the pool day as YYYYMMDD.
  - Excluded: the three documents' names (which now include the battery six) and the depleting-producer
    class.
  - Revision 13, 2 samples each, and the same tiered verdict.
  - Added mark: the F5 flag on 0 usable samples.
  - Reported, not gated: capped samples, samples kept on a reason, requested versus applied Base, and the
    uncapped ratios of any capped sample that misses another mark.
- **Known limits (carried to the post-retest review).**
  - The rule works on rates, not levels. LAMR's above-cap rates were catching up to the reference level,
    not overshooting it.
  - The clamp can pull a Base toward the 0.75× boundary of F6: MO sample 2 goes from 0.82× to 0.76×.
- **Built and reviewed (~20:15 KST): `5998cc3` on `review-2026-09/phase-4-rev13`, not merged.** Whether it is
  used still depends on the battery's F5 result.
  - **Replay proof (reviewer).** 111 recorded desk calls from 40 snapshots, two of them the battery's EZPW
    calls, replayed through the old desk and the new:
    - with no cap, 111 of 111 results are identical;
    - compliant calls are identical, 59 of 59;
    - capped calls equal an independent prototype, 30 of 30;
    - Bull, Bear, the reverse DCF and Kelly are unchanged in the capped calls, 30 of 30;
    - there are no new errors.
  - **Harness, end to end through JSON:**
    - the applied path with the applied value is desk-backed and carries `years35_capped_by_desk`;
    - the requested path gives the stage-1 contract mismatch and the F5 flag;
    - the requested value is not a desk value.
  - **Fixes during review:**
    - the coordinator removed a `TypeError` fallback, added by the coder, that silently dropped the cap;
    - the reviewer replaced a dict-subclass attribute, lost in JSON, with a `requested_fade_years` key, and
      added a test for it.
  - **Tests.** 1221 pass.
  - **Carried:**
    - the coder ran pytest in the background despite the brief, so the coder prompt is tightened;
    - a pre-existing defect: the cloud arm (`api_llm/deep_api_run.py`) sends the TASK, which requires desk
      values, without a desk tool. The Depth Cloud Backstop stays disabled until Phase 6; this goes to
      Phase 6.
- **Retest tooling (~20:15 KST, reviewed; before any retest pool or draw).**
  - `make_f5_tooling.py` generates `draw_f5.py`, `draw_check_f5.py`, `run_f5.sh` and `score_f5.py` from the
    battery's frozen files, which stay untouched.
  - The retest tree is `rs2-P4-f5`, detached at `5998cc3`.
  - **Amended mark (reviewer, before the draw).** The registered wording, "the F5 flag on 0 usable samples",
    had a hole. A Base typed by hand at the desk's uncapped value is not desk-backed, so it is unusable, and its
    flag was ignored; the name paid only one repeatability miss, which the tiered rule allows. With the
    applied path written into the contract, no flag fired at all. The mark is now: **the F5 flag, or a Base
    within 1% of the desk's uncapped value that is not desk-backed, on 0 samples of an evidence name, usable or
    not.** One such sample fails the retest.
  - **The seed rule stands.** If the retest's pool day is 2026-09-28, its seed equals the battery's (20260928),
    over a different pool: the battery six are excluded through the documents, and the data is fresh. Choosing
    another seed after noticing this is the choice the rule exists to prevent.
  - **The draw runs once, after the battery ends,** and its first run is the result. screener-publish is not
    refreshed before then. No pool candidate is written into these documents.

**Project C, the producer project: design registered (reviewer, Opus 5.5 max, ~19:40 KST, while the battery runs;
before any C code).**
- **Files.**
  - Design: `scratchpad\design_producer_C.md`, sha256
    `08fd18860616ca0c2d1d82f345fb43a619de78d4e61f7cb0b980c22779c8001b`. Its section 6 is the pre-registered
    acceptance test for lifting gate reason 16.
  - First coding brief: `scratchpad\brief_producer_C1.md`, sha256
    `638c3cec4638e49f7d0e356d96442e24b37b65d5c3e5e3a0d38b939bd33c31c5`.
- **The design / hold-out split of the depleting-producer class.**
  - Computed before any C code or any per-name value.
  - The population is the 268 class rows of `stocks.csv` at f62d164.
  - Every class name already in these documents is forced into the design half. The rest is shuffled with
    seed 9321300 and halved: 140 design names, 128 hold-out.
  - Hashes:
    - `split_design.txt` 7322b520f351952fd2219b58a8197d7239d61d6a1780087621c32c8b698b88f0
    - `split_holdout.txt` b06a8adc54985eb43d7da895dceedfe7a38504f00a8d9c3ef81f4661f7027aab
    - `split_manifest.json` b92b3fe859f2316bfba6204fc90da2a0fd6a333a81e26ad97986b953bcedacc6
  - C development uses design-half names only.
  - The acceptance draw uses the hold-out only, with seed 1300932. Hold-out names are never written into these
    documents.
- **What the measurements showed.**
  - The life is the larger error.
    - GPOR's revision-12 Base ($235.95) is the perpetual consensus path ($238.14).
    - The same path over its filed proved-reserve life of 11 years is worth $107.60, against a $154.62 price.
  - The deck is the second effect.
  - Mining reserves are not in SEC XBRL at all (none in 244 class files).
  - Oil and gas reserve XBRL exists but is messy. Unit labels are wrong, and signs are flipped.
  - Yahoo's per-contract futures cover WTI to 2034 and Henry Hub to 2031.
- **Decisions.**
  - **Scope of the lift.** Reason 16 can be lifted only for names with a filed reserve life verified by the roll-forward
    identity (within 0.5%, allowing one sign flip) and an oil-and-gas share of at least 50% of fiscal-year revenue,
    after a passed hold-out test. In practice these are US 10-K oil and gas filers.
    - Miners, and names without a verified series, stay under reason 16.
    - The mining arm is a separate project.
  - **The trigger is filed data, not the industry label.**
  - **The life.**
    - It is a ratio of filed reserves to filed production from one series.
    - There is never a default life.
    - The desk applies the filed life by default, through the same plumbing as F5.
    - A perpetual value on a business with a filed life is recorded but never actionable (a new gate reason).
  - **The harness finite-life reference** is the consensus reference path cut at the life, with no terminal value,
    printed beside the perpetual reference.
  - **The strip.** The futures strip is the default deck for oil and gas only. The metals curve is a carry curve, which
    would raise a miner's value.
  - **Capex.** Part 4 is re-specified. The filed alternative capex concepts fill the own record; the vendor file holds
    one year. The universal fix belongs to the screener extractor, a Phase 6 item.
  - **Revisions.** C1, C1b and C2 are dark: no pack text and no revision. C3 is its own PACK_REVISION after F5 and is
    never merged with it.
- **Needs the operator:**
  - confirm gate v5's temporary class;
  - confirm the lift scope and procedure. The lift happens only after a PASS, the reviewer's check and the operator's
    confirmation, in its own commit;
  - the screener capex extractor fix for Phase 6.
- **Build order.**
  - C1 (reserve facts and the finite-life reference, CPU only, dark) is built now in `rs2-P4`.
  - Then C1b (the dimensional XBRL parse, which raises coverage from 8 of 44 design-half US oil and gas filers).
  - Then C2 (the strip, checked against CME settlements).
  - Then C3 (the pack revision, the desk default, gate v6).
  - Then the acceptance test.
- **C1 built and reviewed (~20:20 KST): `699f835` on `review-2026-09/phase-4-producer`, dark, not merged.**
  - **Checks (reviewer):**
    - on all 130 comparable design-half names, the report equals the reference implementation exactly;
    - 9 lives are verified, and 2 names fail closure as registered;
    - the fixtures are verbatim;
    - the producer tests pass with sockets blocked;
    - a hold-out list is refused without being read or printed.
  - **Seven defects fixed by the reviewer, each with a test.** 1230 tests pass.
    - Invalid CIK and `asof` dates are refused.
    - `asc932_filer` is None (unknown) when the facts were never read. False would have failed open in C3.
    - The SEC fetch fails closed on bad bytes.
    - An identity gap between two zero balances is None.
    - The report counts only usable capex years and no longer prints hold-out names.
  - **Withdrawn: D9's capex precedence ("first filed concept present wins"; design §4.4, appendix A).** The
    registered design file is not edited, and its hash stands.
    - Measured: the same XBRL concept is a total at one company and a component at another.
    - In the design half, 26 names file several capex concepts in the same year. In 164 of those 213
      name-years the rule would pick a smaller line; one name's 2019 took $40M of acquisitions and dropped
      $2,594M of development.
    - Such years are now refused, with every concept's value recorded.
    - C3's capex rule must be designed and measured before it is built. The reviewer's proposal: per company,
      the concept, or sum of concepts, that matches the vendor's checked latest-annual capex within 2% defines
      the company's capex; otherwise it is not available.
  - **Blocking for the acceptance test.** The oil and gas revenue share is computable for only 5 of the 9
    verified lives. C1b's dimensional parse must recover it.
  - **Carried to the coder:**
    - a cache-write failure is labelled "fetch failed";
    - a unit tie-break at the same period end is not recorded;
    - the fixture script copies the concept lists instead of importing them;
    - one test comment names the wrong route.
- **C1b designed (reviewer, ~20:45 KST); the build started at 20:48 in `rs2-P4`.**
  - **Files.**
    - Brief: `scratchpad\brief_producer_C1b.md`, sha256 `9190178e…f707d`.
    - Addendum: `design_producer_C_addendum.md`, sha256 `5071003a…fc55d`. The registered design file is not edited.
  - **What C1b does.** It reads each filing's own XBRL instance: members, precisions, and a second labelled basis
    for the oil and gas revenue share. It is offline, built from the reviewer's SEC cache: 167 requests at ≤1 per
    second, no Yahoo.
  - **Measured on the 38 design-half 10-K oil and gas filers.**

    | | C1 | C1b |
    |---|---|---|
    | Verified lives | 8 | 13 |
    | Lift scope (life and share ≥ 0.5) | 4 | 10 |

    - All 8 C1 lives are reproduced exactly.
    - One rule refinement was made after seeing a case: a stray figure with no production does not block the
      rule. The addendum discloses it.
    - The ≥80% coverage bar cannot be met by any XBRL parser, and it stays failed on the record:
      - 17 of the 38 tag no reserve roll-forward;
      - 3 royalty trusts file no XBRL.
  - **Capex: D9's whole chain is withdrawn.**
    - The vendor disagrees with the company's only filed capex figure in 16 of 41 cases.
    - In 14 of those 16 the filed figure is lower, so preferring it would inflate owner earnings.
    - The capex default stays as it is today. C3 gets an annotate-only CAPEX CHECK line.
  - **Proposed pool amendment, pending the operator's confirmation, recorded before any hold-out data is read:**
    - drop the registered "≥ 8 fiscal years" pool condition for the producer test. No producer mark uses that much
      history.
    - Why: 5 of the 10 design-half lift-scope names are young companies with 3–7 years. Scaled to the hold-out,
      the pool is about 3–5, under the stop rule's 6.
    - Until the operator confirms, the registered condition stands.
    - Proposed follow-on: after C3, a text-extraction slice (C1c) reads the reserve table from the 10-K for filers
      without XBRL roll-forwards, checked by the same identity.
  - **Hygiene note.** The reviewer's final check ran a line count on `split_holdout.txt`. Its output was discarded
    and no contents were seen. It is recorded here because the rule is never to open the file.
  - **Built and reviewed: `8e5ad70` on `review-2026-09/phase-4-producer`, dark, not merged.**
    - **Checks.**
      - The offline design-half report matches the reference implementation on all 54 oil and gas names, with 0
        mismatches.
      - All 9 C1 lives reproduce.
      - The producer tests pass with sockets blocked.
      - A hold-out list is refused before anything is read.
    - **Reviewer fixes, each with a test.** 1273 tests pass.
      - A submissions cache that never refreshed now refreshes, and a failed refresh is an error, never the
        stale list.
      - An older filing's life is no longer used when a newer filing for the period is unreadable.
      - A unit conflict ends the search.
      - An inconsistent revenue total is refused.
      - An unreadable precision makes that fact unusable.
      - Production is stored as a magnitude.
      - Lives carry their accession.
      - A broad `except` that hid a broken test is narrowed.
    - **Blocking before C3, after the battery.** A short live smoke test of the fetch path on 2–3 design-half
      names at 1 request per second, compared with the offline cache.
    - **The registered 80% coverage bar stays failed on the record.**
- **C3 designed (reviewer, ~22:30 KST); the build started at 22:32.**
  - **Brief:** `scratchpad\brief_producer_C3.md`, sha256 `2a995d9d…1901a`.
  - **Base.** Branch `review-2026-09/phase-4-c3` in `rs2-P4`: merge commit `7b9002f` of C1b (`8e5ad70`) and
    revision 13 (`5998cc3`), with tree `053de86d…` as the brief pins.
  - **Revision.** It is pack revision 14 on that base. If F5 is shelved, Appendix A makes it revision 13 on
    `8e5ad70`.
  - **Scope.**
    - The section 8.6 reserve block prints only for ASC 932 filers.
    - The producer rules apply to a verified life with an oil and gas share of at least 0.5 (or not computable).
    - The desk's default life, and the TASK and schema variants, apply only when a default life N exists.
    - Every consumer reads scope from the pack text through one parser.
  - **Proof that nothing else changes.** A replay of the baseline against C3 on the same inputs:
    - recorded non-producer packs and every recorded desk call must be identical;
    - fresh builds of the book: every non-ASC-932 pack byte-identical, and ASC 932 packs identical once the
      block is removed;
    - any difference stops the build.
  - **Price deck.** C3 does not wait for C2. Reason 18 reads a `deck_check` stamp that C2 fills later. Until
    then, every in-scope producer is non-actionable.
  - **Every model-visible text is verbatim in the brief's section 12.**
    - The new desk field is `perpetual_reason`, not `life_reason`, which is a substring of
      `cash_flow_life_reason`.
    - Revision 12's workaround sentence is retired only in packs with a default life.
  - **Not authorised yet:**
    - the live SEC smoke test (section 16) waits for the battery's end;
    - the replay's recorded-run inputs are copied after the battery.
  - **Revision numbering against E17.** E17 was also written as revision 14 on `5998cc3`. Numbers go in merge
    order and are never combined. Whichever lands second is rebased, and the reviewer re-pins its text hashes.
  - **Needs the operator:**
    - revision 14 re-queues the whole book;
    - gate v6 makes every v5 row stale;
    - reason 18 makes every in-scope producer non-actionable until the price-deck slice lands. That includes one
      name labelled midstream that is really a mineral and royalty owner with a filed life;
    - new reason 19: an SEC read that fails with nothing cached makes that run's verdict non-actionable;
    - the finite-life-plus-annuity fix applies to producers only. Applying it to everyone would change
      non-producer values, so that is a separate decision;
    - production verdicts on hold-out producers are never cited in any document before the draw.
  - **Coder switch (~22:50 KST).** Gemini hit its quota partway through ("Resets in 1h6m46s", so about 23:57 KST).
    Its partial edits were saved to `scratchpad\c3_gemini_partial.diff` and reverted, and the tree is back at
    `053de86d…`. Its partial baseline copy was moved to `c3_base_aborted_gemini`. The brief went to Sonnet 5, the
    fallback coder.
  - **Disclosures (reviewer).** `split_holdout.txt` was passed to `sha256sum` in a batch. No contents were shown,
    and its hash is already registered.
**E17 re-scoped (reviewer, Opus 5.5 max, ~22:00 KST; offline measurement while the battery runs).** Brief:
`scratchpad\brief_e17_research.md`, sha256 `c96269b9…c73cd4`. The build started at 22:00 in `rs2-P4-e17`, branch
`review-2026-09/phase-4-e17`, from `5998cc3`.
- **The cause was wrong.** Both loops came from the desk closing silently, not from the search engine.
  - After the 5th desk run, `chat_with_tools` removes `run_financial_model` from the tool list and tells the model
    nothing.
  - All 28 loop repeats came after that point:
    - UGI (b) s1 made 14 research calls in 72.5 minutes;
    - APH (b) s1 made 24 in 72.8 minutes. It wrote that the desk "doesn't exist in my function schema".
  - No loop happened while the desk was still offered: 0 in 46 valuation samples and 32 research-only runs.
- **Corrections to the E17 record:**
  - UGI's masked link was made up by the model. It appears in no result, page, pack, brief or thinking.
  - APH repeated its Bing request 19 times, not 18. Six of those turns carried over 10,000 tokens of thinking, so
    "no reasoning between them" is wrong.
  - The "58% of 462" figure cannot be reproduced uniquely. The (b) batch measures 55.6% related.
  - E16's repeat note says a second fetch "adds nothing", but by then the model's notes hold only 1,500 characters
    of the page.
- **Measured (offline):**
  - loops (one request sent 3+ times): 2 of 46 samples, 0 of 13 on revisions 10–12;
  - search results unrelated to the query: 37.9% (valuation), 34.0% (discovery);
  - pages longer than the 9,000-character cut: 69 of 95. In at least 7 samples the needed fact lay past the cut;
  - PDFs served as raw bytes: 2 of 215 pages.
- **Kept:**
  - **D1 (new, the loop fix).** Each desk result shows "k of 5 desk runs used". The model is told when the desk
    closes, and research results after that say it is closed.
  - **A2, changed.** Unrelated results are set aside, with a count and host list shown and a full audit record.
    Still 6 results served.
  - **B2.** Pages are served in 9,000-character parts; a repeat gives the next part.
  - **B3.** A `find` argument on `fetch_page`.
  - **B5's repeat count,** inside B2's note.
  - **F (new).** A PDF is refused with a reason.
  - **Two words added to E11's furniture list:** "return to homepage", "top stories".
  - **The budgets are unchanged.**
- **Dropped, with measured reasons:**
  - **A1, the SearXNG engine change. It is NOT applied** (for the operator). A2 makes engine choice secondary,
    and turning Bing off would leave yandex as the only general engine. The live test reports on it.
  - A3, B1, B4, and B5's list and C.
- **This is a PACK_REVISION.** The tool schema and notes are what the model is told.
  - Revisions are numbered in merge order and never combined: F5 is 13 if it lands; E17 and C3 then take the next
    free numbers.
  - E16 changed a model-visible note without a revision. That is recorded here, not repeated.
- **Live test, pre-registered in the brief's section 12. It runs only after the battery and any F5 retest end.**
  - **L1 (no GPU).** The 212 saved queries against production search. The pass bars are the brief's: no result
    worse than today, and a blind hand check with at most 9 of 60 served results off topic and at most 3 of 60
    set-aside results on topic.
  - **L2 (GPU).** Two names chosen by rule, plus a probe that closes the desk after 2 runs. It passes only if the
    model makes at most 6 research calls after closure and writes the memo on its own turn.
- **Carried.** APH s1's desk runs 4–6 returned run 1's results unchanged; the model says it pasted the desk's own
  output back in. That deserves its own look at the desk. Not E17; not verified.
- **Built and reviewed (~22:45 KST): `3d02fbd` on `review-2026-09/phase-4-e17`, not merged.**
  - **Checks (reviewer):**
    - the three replays give the brief's parts, notes and repeat counts;
    - the corpus gives 790/482 (valuation) and 891/459 (discovery);
    - the suite passes with every socket blocked;
    - E16's texts are byte-identical;
    - the budgets are unchanged.
  - **Reviewer fixes, each with a test:**
    - the single-part note cited the wrong call;
    - parts that could not be served were reported as served;
    - cache accounting was lost through a second address;
    - a dead fallback that invented an empty page now fails loudly.
  - **Tests.** 1244 pass.
  - **Blocking before the cloud backstop is re-enabled (Phase 6).** `api_llm/deep_api_run.py` sends the new tool
    definitions but calls `fetch_page` without `part` or `find`, and it passes search results with their audit
    fields, set-aside junk included. The brief missed this caller.
  - **Blocking before production.** The live tests L1 and L2, after the battery and any F5 retest.
- **L1 passed (reviewer, 2026-09-28 ~01:15 KST; the battery had been stopped, and no F5 retest had started).**
  - **Run.** 212 queries to production at 8888, 4 s apart; the yandex report arm at 8889 was up.
  - **Result.**

    | | related results per query | queries with nothing related |
    |---|---|---|
    | C0, today's first 6 | 3.84 of 6 (35.9% of served are unrelated) | 3 |
    | C1, E17's filter | 5.78, all related | 3 |

  - **The four criteria:**
    - C1 ≥ C0 on 212 of 212 queries;
    - empty queries 3 ≤ 3;
    - served but off topic: 8 of 60 (limit 9), in a blind hand check with seeds 1717/1718/1719 and the labels
      hashed before unblinding;
    - set aside but on topic: 0 of 60 (limit 3).
  - **A1 stays out:** with the filter in place, the engine set changes nothing the model is served.
  - **Carried:** the relevance tokenizer splits words at accented letters.
- **L2 started 01:22 KST from `rs2-P4-e17` (3d02fbd, v31 with the pinned system digest, gate_test, screener data
  f62d164).** The order is EZPW L2b, then L2a (the desk forced to close after 2 runs, seeds 1001 and 1002), then
  ASTH L2b.
  - The baseline is the battery's revision-12 record for both names. The reviewer confirmed that the gated items
    are unaffected.
  - Reported differences are labelled "revision 12 → 14", not as E17's effect.
  - ASTH sample 2 of the battery already closed the desk on revision 12: 8 research calls in 69.8 minutes after
    the 5th desk run. That is the fourth recorded closure.
- **L2 ran on degraded data: an orchestrator setup error (found ~08:05 KST).**
  - `rs2-P4-e17` had no `enrich/` cache; the battery tree had one from `prep_battery_data.py`. Every L2 pack
    therefore printed an empty SECTION 8: "CONSENSUS ESTIMATES: not available — enrich record missing", with no
    consensus-implied value, no analyst targets, no street fence, and an F5 cap of None.
  - The research-mechanics results stand:
    - L1;
    - L2a's desk-closure probe;
    - the repeat and exception gates.
  - Values, spreads and times are not comparable with revision 12. They are:
    - EZPW: $47.08 and $45.26, both excluded on shares;
    - ASTH: $62.25 and $76.01, 22% apart.
  - The reviewer rules whether L2b must be re-run on a prepared tree before merge.
  - **L2b gates on the degraded run (reviewer, ~08:50): all four gates pass on all four samples.**
    - no repeats;
    - no failure field set;
    - no exception;
    - 0 unrelated results served, against 15, 8, 4 and 11 on revision 12;
    - no `_audit` key reaches the model.
    EZPW's share exclusion is not a gate-2 failure: it comes from the plausibility guard, and E17's `find` made the
    filed diluted count reachable.
  - **E17 verdict: APPROVED WITH CONDITIONS. Merge after one prepared L2b re-run** of EZPW and ASTH.
    - **Preparation:**
      - the battery's enrich and openbb caches for both names are copied in, with sha256 recorded;
      - the degraded day's discovery briefs are moved aside;
      - a pre-check refuses to start unless SECTION 8 has a fetch date, no "enrich record missing", a numeric
        next-FY revenue growth, the CIV and the targets.
    - **Decision rules, written before the re-run:**
      - merge if all four gates pass on all four samples;
      - if any EZPW sample is again excluded on shares after reaching the filed count, S2b merges before or
        with E17;
      - values go to the joint review and are not scored.
  - **Re-run started (08:53).** The pre-check passed: EZPW 0.095, ASTH 0.101, fetched 2026-09-27.
  - **EZPW re-run sample 1: $38.10, excluded again** (`desk_share_count_mismatch_1.36x`).
    - The model used the filed diluted count after reading the 10-Q.
    - Under the decision rule written before the re-run, **S2b merges before or with E17, never E17 alone.** Both sit
      on `review-2026-09/phase-4-simplify`, which is the branch to merge.
  - **The re-run finished (13:23).**
    - EZPW sample 2 is $41.69, also excluded on shares, so EZPW is NOT_USABLE.
    - **ASTH gives $58.87 and $61.11, 3.8% apart**, UNDERVALUED at half size. On the same name, revision 12 was 26%
      apart and the degraded revision-14 run 22%.
    - Gates and the final E17 verdict are with the reviewer.
  - **Final E17 verdict (reviewer, ~13:25): APPROVED WITH CONDITIONS.**
    - **The pre-registered record is complete:**
      - L1 passes 4 of 4;
      - L2a passes (2 of 3 seeds informative, both pass);
      - the L2b gates pass on all 8 samples, degraded and prepared: 0 unrelated results served, against 15, 8, 4 and
        11 on revision 12; no repeats; no exceptions.
    - **The re-run is valid:** the caches are byte-identical to the battery's, SECTION 8 prints, and the F5 cap is
      active (0.095 and 0.101).
    - **EZPW's exclusions are caused by E17 but are not gate failures.** `find` reached the in-the-money 3.750% 2029
      convertibles, and the model moved to 83.4M shares with a substantive reason. Rescaled to 61.44M, the values
      are $51.71 and $56.59, close to the battery's.
    - **ASTH's direction changed from hold to undervalued.** F5, E17 and the fresh briefs cannot be separated; this goes
      to the joint review unscored.
    - **Effort:** research calls 41 against 31 on revision 12, but model time fell from 263 to 242 minutes.
    - **Blocking:**
      - E17 merges only in the same merge as S2b; the simplify branch already orders them;
      - an offline replay of the prepared EZPW samples through S2b must keep them. This is with the simplification
        reviewer.
    - **Carried:**
      - the relevance tokenizer's accented-letter gap;
      - the cloud-arm tool mismatch (Phase 6).
- **Gate hole found (blocking before any test or production).**
  - The degraded ASTH verdict (UNDERVALUED at half size, `no_street_fence`, consensus missing) gets only
    `non_production_row` from `depth_gates.assess`. On a production row it would be actionable.
  - The flag fires, but the gate does not act on it.
  - The fix goes to the simplification reviewer: fail closed on a missing fence or consensus, and measure the blast
    radius over the recorded verdicts.
  - **Designed as S2c (reviewer, ~08:05; the orchestrator accepts): `brief_gate_consensus_anchor.md`,
    `9950299f…`.**
    - **Three places let it through:**
      - the fence stamp's comment, "No fence is an information flag, never a gate";
      - gate reason 10, which runs only when a fence exists;
      - the sweep's data-health scan, which never checks consensus records.
    - **Blast radius:**
      - 2 recorded verdicts lack consensus, both from the degraded e17 L2 runs;
      - 11 older verdicts lack a fence but are already blocked as gate v2;
      - 13 of the 291 book and nominated names have no analyst target band today, and will be blocked.
    - **The fix:**
      - a `consensus_data_status` fact;
      - a loud `::PACK DATA::` line before sampling;
      - the next gate version (numbered in merge order against the producer branch), with two reasons that fail
        closed: `consensus_data_unavailable` and `no_street_fence`;
      - the battery pack builder refuses missing or stale consensus;
      - A/B bar B-1 requires consensus status ok.
    - **consensus_valuation still values**, so no measurement is deleted. The gate refuses loudly.
    - **Sequencing.** A separate commit after the S3 A+B fix-up, before package C, the A/B or any final test. It must
      reach production before `DEPTH_PAUSED` is lifted.
    - **For the operator:**
      - may a name with a fence but no estimates trade?
      - do the 13 unfenced names stay blocked?
  - **Committed as `82530a3` (reviewer APPROVED WITH CONDITIONS; 1462 tests).**
    - **Reviewer fixes:**
      - a fail-open default in the DEFAULTS reader, which had inferred `ok`;
      - reused frozen packs are checked too;
      - a stale docstring;
      - 16 review tests.
    - **Reviewer ruling, reversing its own brief: `estimates_unavailable` is gated.**
      - **Production's `rs2-local/enrich/` cache holds no `estimates` field on any of its 289 records.** They were
        fetched June to August by an older fetcher.
      - Over the 176 book names today: 6 have no record, 35 are stale, and 135 would print "estimates
        unavailable".
      - A failed fetch prints the same line.
      - Left open, the gate would have passed them with no consensus data behind them.
      - **So production depth verdicts before the pause had no consensus anchor on most names.**
    - **Blocking before `DEPTH_PAUSED` is lifted:**
      - S2c reaches production only through the branch merge; the live checkout is at gate v2, pack revision 5;
      - refetch the production enrich cache with the current `enrich_ticker.py` and measure the status
        distribution;
      - schedule a refresh: nothing calls `enrich_ticker.py`, so the cache goes stale 45 days after each fetch.
    - **Operator policy:** names genuinely without estimates, and the 13 unfenced names.
- **Package C went to the coder** from the S3 brief `d30df2ae…`. It builds on S2c: facts version 4, a
  `consensus_data_status` line in DEFAULTS, and the replay base is the S2c export.
  - **Coder switch (~10:30).** Gemini hit its quota partway ("Resets in 2h59m47s", about 13:30 KST).
    - Its partial diff is saved to `scratchpad\s3c_gemini_partial.diff`, unreviewed, and the tree is reverted to
      `82530a3`.
    - Package C went to Sonnet 5 from a clean tree.
  - **Package C built by Sonnet (~13:15), uncommitted, PACK_REVISION 15; 1483 tests. Sent to review.**
    - **7.3.** The orchestrator stopped Sonnet's first rebuild script: it had no socket block and fetched live news and
      SEC data. It then ran with the S1 harness:
      - 0 errors;
      - 283 of 291 names equal on the 14 keys; the 8 that differ are the share-default names, as expected;
      - facts equal the text on 291 of 291;
      - consensus status ok on 291;
      - pack plus prompt 17.3% smaller (TASK from 4,731 to 2,263 tokens).
    - **7.5.** 22 of 22 runs, 0 differences.
    - **Deviations to review:**
      - two network near-misses in ad-hoc checks;
      - a TypeError on a filed-zero share count (DAC, GSL, ITT), fixed;
      - a numeric-format extension in the SECTION 8 reference line.
  - **Package C committed: `d57837e`. Revision 15 is runnable (reviewer APPROVED WITH CONDITIONS; 1487 tests).**
    - **The reviewer re-ran the acceptance itself:**
      - 7.3(a)–(e) reproduce, and the pack is 17.4% smaller;
      - the 22 replays against an `82530a3` export are empty;
      - an independent re-implementation of 5.11 matches on 291 of 291.
    - **Reviewer fixes:**
      - a point-in-time look-ahead: the dilution factor came from a quarter after the as-of date;
      - the TASK and tool text now name `shares_default`;
      - a test that depended on a folder outside the repo.
    - **The E17 merge condition is met.** Both prepared EZPW re-run samples are kept and annotated under S2b
      (desk_share_count_departure_with_reason; 83.4M shares against the §5.11 default of 79.4M).
    - **Bar B-6 amended before any A/B sample (orchestrator, 13:55).**
      - The first sub-bar, "r15 first-turn prompt ≤ 0.80 × r14", becomes **≤ 0.90 × r14**.
      - Reason: the reviewer's 25–30% size estimate was wrong. The deterministic measure predicts 0.853× on v32 and
        0.866× on v31, so 0.80 would fail by construction on a frozen pack, not on behaviour.
      - B-6's other two sub-bars (median thinking ≤ 1.10×, peak window ≤ r14) are unchanged.
      - Recorded as a correction of an estimate, before any data.
    - **The near-miss cache files are left in place.** They sit in the ignored `rs2-P4-s15\cache`, and nothing that
      counts reads them.
- **F committed: `e7c0b03` (reviewer APPROVED; 1518 tests).**
  - **Fences:** 278 → 279 over 291 names; only MU changes, gaining [$234.09, $4,000.00]. MU's $6,207
    consensus-implied value is no longer used.
  - **Rebuild and replay:** the whole book changes 1 of 291 texts, and the 22 replays are empty.
  - **Reviewer fixes:**
    - distinct failure reasons in the sibling fetcher;
    - a mean mislabelled as the median;
    - a crash on a non-numeric sibling record;
    - one owner for sibling scaling.
  - **Process breach (Gemini's F session).**
    - At 14:16 something ran `world_news.digest()` live, which ran `git fetch origin run-history` in
      `macro-regime-indicator`. Only the remote-tracking ref was updated; the working tree is untouched.
    - It also rewrote `rs2-P4-book\enrich\MOG-B.json`, the read-only data root. The pack's text and facts are
      unchanged.
    - Nothing needs undoing. Future coder prompts forbid pack builds without the socket block.
  - **MOG-B needs a refetch** with the F1 fetcher before the final test's pool day.
- **D4: model v32 created by the orchestrator (15:10).**
  - v31's form is LF (system `a76fd089…`); a copy of its manifest was saved first.
  - `ollama create rs2-analyst-deep-mtp5-v32` used the reviewer's LF Modelfile (0 CR bytes).
  - **Pins, verified:**
    - v32's system layer is `sha256:04894e6c3b217be46f48c329ca7c6c8dd7347d344513ec4c5cd723213b0c0ab7`, equal to the
      pin;
    - the model, template and params layers are identical to v31's;
    - v31's manifest is byte-identical before and after (`d4a7eb71…`);
    - `ollama show --system` equals `system_v32.txt` (15,632 characters).
  - **Tag IDs:** v32 `5578678df015`, v31 `d4a7eb712677`. Nothing was deleted; rollback is `--model v31`.
  - The Q4 v32 candidate was not created (not wanted).
  - D's repository part is with the coder.
  - **D built by Gemini (~16:00), uncommitted; 1525 tests.** Sent to review with the D4 pins.
  - **Committed: `3153924` (reviewer APPROVED; 1526 tests).**
    - Gemini's "Deviations: none" was false: about 30 test assertions accepted either SECTION or DATA, and two
      reader tests copied the code under test. The reviewer fixed both, and five mutations now fail.
    - The whole book rebuilds with rename-only diffs, and no SECTION word is left in any pack.
    - The 22 replays against an `e7c0b03` export are empty.
- **Step-4 A/B mechanism brief `brief_ab_step4.md` (`d2f1d8bb…`, reviewer).** Four items, accepted by the orchestrator
  before any sample (~16:50):
  1. **Run order.** One 2-sample run per arm per name, with the first arm alternating by name. The runner seeds
     sample i with 1000+i and cannot offset it, so §8's interleaved single samples would repeat the first draw.
  2. **B-1 facts equality on EZPW.** The consensus-implied value is compared by scaled equality: $58.92 at r14 and
     $45.62 at r15, a ratio equal to the dilution factor k = 1.2917. All other facts are equal, and so are UGI and
     LAMR.
  3. **Reduced thinking.** A reduced-thinking sample counts as not recorded in B-1 (the operator's ruling of
     2026-09-27).
  4. **The shared catalyst brief** is written by the r15 tree with v32, the system that would ship.
  - **Also fixed by the brief:**
    - one live quote per name for every arm;
    - `--ctx 98304 --num-batch 256`;
    - a separate folder per frozen pack;
    - the MRI git fetch stubbed during builds;
    - build deadlines;
    - scoring definitions for B-1 to B-9;
    - the predicted B-6 ratio, 0.852–0.871, under the amended ≤ 0.90.
  - **Arms:**
    - r14 is `ca7dd0c` with v31;
    - r15 is `3153924` with v32;
    - the attribution arm is `e7c0b03` with v31, and runs only where a bar fails.
  - The reviewer writes the build, check, run and scoring scripts.
- **A/B scripts delivered (reviewer, 2026-09-28 ~17:20; scratchpad `ab\`).** They were tested with no GPU, network
  or Ollama: git-archive test roots, fake model and desk through both arms' real harness, stubbed run tools, and
  negative cases. Three items are recorded before any sample, all accepted by the orchestrator (17:25):
  1. **B-7 uses production's fiduciary gate.** The brief's §8 said "`is_valid` True", which is weaker than the bar
     it implements. The scorer calls `depth_pipeline.fiduciary_verdict_gate`, which also fails an invalid
     `entry_timing` or invalidation rules that cannot be checked. `is_valid` is reported alongside.
  2. **New pre-sample check (j).** Every frozen pack must carry the company's own earnings-release words, proving
     the prep's SEC caches served the build. A mechanism check, not a bar.
  3. **One clock the build cannot freeze.** `valuation_backbone` imports `datetime` inside its functions, so the
     build sees the real clock. It moves only the price-range age; the three arms are built seconds apart, and
     checks (a) and (g) would catch a divergence.
  - **Data:** quotes are fetched once by the prep (the only networked step) and read by the socket-blocked build.
    Enrich and openbb records are copied, not refetched: UGI and LAMR from `rs2-P4-book`, EZPW from `rs2-P4-bat`,
    each sha256-checked; all three have consensus status `ok`.
  - Script sha256s are in the reviewer's hand-off and were re-checked by the orchestrator before use.
- **The final six-name test, pre-registered (reviewer, Opus 5.5 max, 2026-09-28 ~22:20 KST; pasted by the
  orchestrator at 22:20, before any pool, prep or draw, while the before/after test runs).**
  - **Purpose.** This is the finish-line test of Phase 4: revision 15 with model v32, the system that would ship,
    run on six names no design has touched. Like the battery, it screens for systemic defects; it cannot prove
    fitness.
  - **When.** Only after the before/after verdict is PASS. If a bar fails, the attribution arm runs first, as
    registered, and this test waits for a ruling.
    - The code is the commit that verdict approves: `3153924`.
    - If the verdict names a defect to fix first, the fixed commit replaces `3153924` by amendment before the pool
      day, and the tooling is regenerated.
  - **Pins, written into `final\draw_final.txt` by the draw script:**
    - **rs2:** `3153924c6fcaf372819f731248e1855d3fc0eb6d` (revision 15, gate v6).
      - It runs in a fresh detached tree, `scratchpad\final\tree`, with its own data root and a `research-venv`
        junction.
      - The only change allowed is `config.json`'s `depth_model` line switched to `rs2-analyst-deep-mtp5-v32`,
        after the previews.
    - **Model:** `rs2-analyst-deep-mtp5-v32` (tag `5578678df015`), system layer
      `sha256:04894e6c3b217be46f48c329ca7c6c8dd7347d344513ec4c5cd723213b0c0ab7`. The draw refuses any other
      digest, and the run checks it before every name.
    - **screener-publish:** stays at `f62d164020b99daada6a352badafebd6f576c3b5`, clean.
      - Every revision-15 measurement ran on this data: the whole-book checks, the price-range fence's reach and the
        before/after test.
      - A refresh would bring an unmeasured engine run, and the screener's pending capital-spending changes, into the
        finish line.
      - Freshness comes from the pool-day analyst data and the live quote at run time.
      - `RS2_SCREENER_DATA_COMMIT` pins the commit, and the tree check stops the run if the clone moves.
    - **Population source:** `4b382bdc91be9b75d36b503c034d39d91f392c8f`.
    - **Tooling:** `final\final_tooling.sha256` (sha256
      `718de453be34bd57964403041987c4e0ec05fd2e576a4e9066fd728436dd0c9c`) pins twelve files, including:
      - `score_final.py`, `8b50381e…b592`;
      - `draw_final.py`, `cd8dfa7f…a1ba9`;
      - `run_final.sh`, `cb214259…6bccb`;
      - `draw_check_final.py`, `5f05bc1a…896f`.

      All were generated by `make_final_tooling.py` (`4c0ba70c…170d`) from the retest's and the before/after
      test's files, which stay untouched. The orchestrator re-checked all twelve hashes at 22:20; all match.
  - **Population and strata.** The battery's rule, as the retest registered it:
    - `factor_scores.json` of the dual-door run of 2026-09-23T16:25:19Z, read with `git show` from 4b382bd;
    - names not vetoed, not nominated, `fct_rank` 136–400;
    - if either pool has fewer than 3 names, the window widens by 200 ranks, up to 1,000;
    - three fast growers (g1 ≥ 0.30 and q ≥ 1) and three steady names (|g1| ≤ 0.10).
  - **Exclusions.**
    - Every ticker named, as a whole word, in the three documents at pool time. That includes the battery six,
      the before/after names and every name any review touched.
    - The depleting-producer class, read from the pinned clone's `stocks.csv`.
    - Pool names are written only to the scratchpad draw file. Only the six drawn names enter the documents, after
      the draw.
  - **Data, on the pool day.**
    - `prep_final_data.py` fetches a full analyst record and an openbb cache for ranks 136–600.
      - It uses the fence-band commit's fetcher, share-class sibling targets included.
      - It writes into the final tree's own data root, never `rs2-P4-book` or any other root; the script refuses
        anything else.
    - A name without these records, or whose pack build fails, is excluded and listed. The draw stops if more than
      5% of the pool fails.
    - **Data conditions:** the battery's, plus consensus data status `ok`:
      - the reference is printed;
      - at least 3 next-FY EPS analysts;
      - at least 8 years of history;
      - the vendor's same-year net income within 2%;
      - a usable street band.

      The consensus status and the street band are gate v6's reasons 17 and 18.
  - **Pool day and seed.**
    - The pool day is the local day on which the prep and the draw both run. The seed is that day as YYYYMMDD.
    - `random.Random(seed)`, with each pool sorted: `fast = rng.sample(fast_pool, 3)`, then
      `steady = rng.sample(steady_pool, 3)`.
    - After the before/after verdict the pool day is **2026-09-29**, so the seed is **20260929**. If the day slips,
      the seed follows the day; no seed is chosen.
    - The draw runs once, and its first run is the result.
  - **No network in any pack build except the run itself.**
    - The draw's pool computation and the previews build packs with sockets blocked, git fetch refused and the MRI
      run-history fetch stubbed.
    - In the draw, company news, the SEC release and the world-news digest are stubbed. In the previews they are
      read from same-day caches.
    - `prep_final_news.py` (network, no pack built) fills those caches for the six drawn names before the previews.
    - The run is the production path and fetches as production does.
  - **A2.** Each drawn name's development is set from its preview before any sample, in
    `final\draw_a2_rules_final.json`. `pin_a2.py` appends that file's sha256 to the draw file.
  - **Run.** `run_final.sh`: six names, 2 samples each, through `depth_pipeline.py --no-publish` in gate-test mode,
    with v32, no API keys and the tree check before each name.
    - Before each name, the before/after test's checks:
      - no PAUSE file (the operator's GPU-sharing rule);
      - SearXNG answers;
      - every model stopped and none loaded;
      - GPU under 200 MiB;
      - the v32 digest as pinned.
    - v32 must stay 100% on GPU for the whole name. A stop by that watch is a crash.
    - Every model is stopped after each name.
    - **The crash rule stands:** one re-run after a recorded diagnosis (`--rerun NAME`); a second crash fails. A
      name already run is never run again otherwise.
    - DEPTH_PAUSED stays on in production, KIS stays halted, and nothing is published. The run takes about 14 GPU
      hours.
  - **Marks (`score_final.py`): the retest's, adapted to revision 15.**
    - **Provenance:** a gate-test row, the pinned commit and clone, model v32, pack revision 15, think high.
    - **Gate mark:** gate v6's own verdict, with no reason except `non_production_row`. It includes reason 17
      (`consensus_data_unavailable`) and reason 18 (`no_street_fence`).
    - **Facts object:** the reference, the levels, the base window and `shares_default` are read from the run's
      `_pack_facts.json`. Revision 15 no longer prints the level and window lines.
    - **The years 3–5 cap mark (registered as F5), unchanged.**
      - The mark fires on the flag, or on a Base within 1% of a desk call's uncapped value that is not desk-backed.
        It must appear on 0 samples of an evidence name, usable or not; one such sample fails the test.
      - On revision 15 the code fills the Base from the desk, so the second clause can fire only if the code fill
        fails. The mark stays as a regression guard.
    - **Share count, inside A1 (the harness's reason flags).**
      - Every usable sample's Base share count (the answer desk run's effective count) is within 1% of the pack's
        `shares_default`, or the run carries `shares_reason`.
      - `shares_reason_uncited` is an A1 flag.
      - A reasoned departure (`desk_share_count_departure_with_reason`) is an annotation, not a flag.
      - A usable sample whose count cannot be read leaves A1 open.
    - **The thinking-loop 500.**
      - A sample whose delivered attempt holds a turn that ended in an HTTP 500 is not usable: a forced report after
        a runaway turn is not a valuation. Its name then lacks two usable samples, which is a repeatability
        (judgment) miss.
      - A 500 in a first attempt followed by a clean whole-sample retry leaves the sample usable; it is reported.
      - A sample the harness itself failed (two 500s, a lost sample, or reduced thinking) is not a result, as
        before, and fails integrity.
    - **Everything else as in the battery and the retest:**
      - F6, base on reference: 0.75–1.33× the named window's reference, or `guidance_deviation_reason`;
      - repeatability;
      - fence and MoS;
      - A1 with revision 12's flags;
      - A2;
      - process;
      - every part a result.
  - **Verdict (tiered, unchanged).**
    - Integrity must hold on all six: every part a result, provenance, fence and MoS, gate v6.
    - At most one name may miss judgment marks (repeatability, base on reference, A1, A2, process), and that miss
      is diagnosed.
    - Any sample with the years 3–5 cap mark fails the test.
    - An open mark or an unscored name leaves the test OPEN. A provenance failure is OPEN and can be cleared by one
      re-run under the crash rule.
  - **Reported, not scored:**
    - the battery's list: loops of at least 10,000 tokens faster than 52 tok/s, whether the first desk call came
      before research, whether the final desk inputs equal the first call's, long-turn speed, report continuations
      and whole-sample retries;
    - each sample's Base share count against `shares_default`;
    - 500s in first attempts;
    - desk-capped samples, and requested versus applied Base.
  - **Acceptance, run before the pool (reviewer, 2026-09-28).**
    - `sim_final.py`: 23 per-name cases and 16 six-name sets, all as expected.
    - An end-to-end dry run in a test root: a clone at 3153924, with no network and no GPU.
      - The prep ran with fake fetchers: 465 of 465 names.
      - The draw ran socket-blocked: a 229-name pool, 0 data or build failures, every consensus status `ok`.
      - The news prep and the previews ran.
      - The run script ran with its checks stubbed, and six names went through the real production path with a fake
        model and desk.
      - The scorer read every folder with provenance intact. It marked a planted 500 sample unusable and a planted
        5% share departure an A1 miss.
      - The MRI fetch time was unchanged throughout.
    - Not tested: the real fetchers and the real model runs.
  - **MOG-B refetch** (booked "before the final test's pool day"): no longer needed for this test.
    - MOG-A and MOG-B are vetoed (`NOT_TRADABLE`, no rank) in the 4b382bd population, and both are named in the
      documents.
    - The final tree never reads `rs2-P4-book`.
    - The refetch stays a production item under Phase 6's enrich refetch, never written into `rs2-P4-book`.
  - **If it passes,** production's `depth_model` still changes only by the operator's ruling; Phase 6 merges gate v6
    and revision 15.
- **Before/after test: scored FAIL (`ab_score.py`, 2026-09-29 08:58 KST; the run ended 02:27, and scoring waited
  because the orchestrator session dropped overnight).** All six invocations exited rc=0, with no lost or
  reduced-thinking samples. `score.json` is in `ab_step4\records\`.

  | arm | UGI | LAMR | EZPW |
  |---|---|---|---|
  | r14 (v31) | $47.28, $34.59 (sample 2 fid FAIL, not recorded) | $188.03, $188.78 | $45.87, $43.69 |
  | r15 (v32) | $48.75, $47.24 (sample 2 scenario_wise, no desk-backed Base) | $189.09, $164.68 | $41.48, $44.60 |

  - **Pass:** B-2 (direction agrees on all three), B-5, B-7 (fiduciary gate PASS on all six r15 contracts).
    B-6's first-turn ratio (0.854–0.872 ≤ 0.90) and peak window also pass.
  - **Fail:**
    - **B-1:** 11/12 recorded.
    - **B-3:** LAMR's r15 median equity is $17.95B, below r14's low of $18.15B. The section 8 exception is for the
      reviewer's trace.
    - **B-4:** r15 UGI's spread cannot be computed; sample 2 has no Base equity.
    - **B-6 median thinking:** r15 104,636 tokens against r14 67,712 (1.55×; the bar is ≤ 1.10×).
    - **B-8:** r15 UGI 2 is scenario_wise. Desk refusals are 0, 2, 0, 0, 3 and 1.
    - **B-9:** r15 UGI 2's Base share count is unreadable. EZPW 1's departure carries its reason.
  - Sent to the reviewer for the trace, the verdict, the attribution arm's names and the fix path. The final test
    waits on it.
- **Before/after verdict: REJECTED (reviewer, 2026-09-29 ~10:00 KST).** `3153924` (revision 15) does not go to the
  final test.
  - **Bars after the registered hand step.** The share count of r15 UGI 2 was read from its memo (214,494,967, the
    desk default).
    - **B-1 FAIL:** r14 UGI 2's contract does not parse. This is the baseline arm's failure; r15 recorded 6 of 6.
    - **B-3 FAIL on LAMR.**
    - **B-4 PASS:** UGI 3.2%, LAMR 14.8% (limit 15%), EZPW 2.4%.
    - **B-6 FAIL:** 1.545×.
    - **B-8 FAIL.**
    - **B-9 PASS.**
    - B-2, B-5 and B-7 pass.
  - **r15 UGI sample 2: model behaviour exposed a desk gap.**
    - All five desk calls sent only Bull and Bear as scenarios, with the Base as top-level inputs. The desk accepted
      three of them:
      - the probability-sum check runs only when all three roles are present;
      - the reason checks read the top-level Base only when no scenario ran;
      - Kelly sized two outcomes summing to 0.55.
    - The fill dropped the top-level result, so no call had a Base, and the reasons were not copied. The harness
      flags `cash_flow_life_missing` and `bear_above_price_without_reason` are artifacts: the model gave both
      reasons.
    - The same shape appears in 7 of r15's 15 desk calls (EZPW 2 too), against 0 of r14's 8.
  - **B-6: where the thinking went.**
    - Leaving out research and refused turns, r15's median is 0.870× r14's. The checklist TASK and the DEFAULTS block
      did not lengthen deliberation.
    - Refusals cost 74,253 tokens.
    - Research went from 34 calls to 65, almost all in two samples:
      - UGI 2: 24 calls, on the reported take-private bid;
      - LAMR 2: 14 calls, on the pack's base-year gap.
    - **The EZPW share-unit trap.** Calls with 83,371,000 shares returned $0.00 a share. The tool text states no unit
      (bf95182 dropped "in billions", and the reviewer's own review of d57837e missed it), while the DCF divides by
      the raw input and the checks convert it.
  - **B-3 LAMR:** the section 8 exception does not apply (0 refusals, no r14 flag). LAMR 2's Base year-1 growth of
    10%, against about 26% in the other samples, was a dated, reasoned departure on the one-time Vistar gain. It is
    not a defect.
  - **The attribution arm runs to completion on all three names** (started 09:06). It separates whether the extra
    research comes from the revision-15 briefing and desk or from the v3.2 charter. Its samples use the unfixed
    desk and do not count toward the re-run.
  - **Fix path: revision 16** (the model-visible tool text changes; standing approval covers the bump).
    1. The desk requires exactly one Base, one Bull and one Bear whenever scenarios are sent.
    2. One unit for share counts in the DCF and in the checks.
    3. The tool text gives the share-count unit and exactly three scenarios.
    4. The revision check reads any revision of 15 or later as revision 15. Today it matches "(pack revision 15)"
       exactly, and a revision-16 pack would fall to the legacy readers.
    5. `PACK_REVISION = 16`, with the golden fixture updated.
    6. Acceptance: the full suite, then a replay of every recorded r15 and attribution desk call:
       - accepted full sets reproduce;
       - the two-scenario calls are refused;
       - the share-unit variants are equal.
    7. A new pre-registration for revision 16 on v32. The packs are rebuilt from the frozen data. The 6 new
       samples are compared with r14's recorded samples as scored. About 5–6 GPU hours.
    8. After a PASS, the final-test registration is amended to the new commit and revision 16, and its tooling is
       regenerated.
    - Carried:
      - the refusal text names the share unit;
      - `consensus_valuation.py`:2331 defaults `base_iv` with `or` (non-negotiable 4; this predates the work);
      - bare-key contract JSON is watched.
- **Operator ruling on B-6 (2026-09-29 10:17 KST), made after seeing the results and recorded as such.**
  - For the revision-16 re-run, the 1.10× bar applies to generated tokens outside research turns.
  - Research turns are reported separately, not gated.
  - The first-turn and peak-window sub-bars are unchanged.
  - Grounds (reviewer's recommendation):
    - the extra research went to material, dated questions that revision 15 asks the analyst to settle;
    - leaving research out, r15 already sits at 1.006×, or about 0.87× without the share-unit trap;
    - the peak-window sub-bar, which guards the thinking-loop 500, is kept.
- **The before/after re-run on revision 16, pre-registered (reviewer, Opus 5.5 max, 2026-09-29 ~10:50 KST).**
  Written before the fix commit exists, before any revision-16 pack or sample, and while the attribution arm runs.
  - **Purpose.** The before/after test failed, and section 8 of `brief_simplify_s3.md` requires a new
    pre-registration before any rerun. This re-run tests the fix commit on the same three names, against the same
    recorded baseline.
    - A PASS lets the fix commit replace `3153924` in the final test, by the follow-on amendment.
    - A FAIL keeps the final test waiting.
  - **Arms.**
    - **r14, the baseline, not re-run.** `ca7dd0c` with v31, and its six recorded samples of the before/after test.
      - They are used as scored in `ab_step4\records\score_main_20260929_0858.json` (sha256
        `c627fabb17f85c000aba80c5f69dddda373966ee3c6d591ac0daea21d9cc1e5c`).
      - r14 UGI 2, whose contract does not parse, stays in the baseline as scored: its Base equity ($7.42B) sets
        UGI's B-3 band and B-4 limit, and its tokens count in B-6. This is fixed now, before any data.
    - **r16, the new arm.** The fix commit of the revision-16 brief (`SP\brief_rev16.md`) with
      `rs2-analyst-deep-mtp5-v32`.
      - The v32 tag is `5578678df015`, with system layer
        `sha256:04894e6c3b217be46f48c329ca7c6c8dd7347d344513ec4c5cd723213b0c0ab7`. The model is unchanged.
      - The commit id (40 hex) is recorded here by amendment when the orchestrator commits it, after review and
        before the setup.
      - It must read `PACK_REVISION = 16`.
    - The attribution arm is not part of this re-run.
  - **Trees.** Two detached worktrees of `rs2-local`, made by the orchestrator (a `git archive` export works
    equally):
    - `scratchpad\ab_rev16\trees\r16` at the fix commit, which is the only tree the samples run in;
    - `scratchpad\ab_rev16\trees\r15ctl` at `3153924`, for the pack comparison only.

    Each tree gets the junctions `enrich`, `research` and `cache` into `scratchpad\ab_rev16\data`.
  - **Held equal to the before/after test.**
    - **Names and order:** UGI, LAMR, EZPW; one invocation of two samples each.
    - **Command line:** unchanged apart from the tree, the pack and the output folder: `--ctx 98304 --num-batch 256
      --think high --tools --samples 2 --no-early-stop`. The seeds are the harness's, 1001 and 1002.
    - **Environment:** `RS2_RUN_SOURCE=gate_test`, and `RS2_SCREENER_DATA_COMMIT` pinned to `f62d164`.
    - **Quotes:** the recorded ones (UGI $36.51, LAMR $143.98, EZPW $31.16, as of 2026-09-25).
    - **Data:** copies of `ab_step4\data`, with mtimes kept. The harness ages each research brief by its file's
      mtime.
    - **Evidence stores:** copies of `ab_step4\evidence`, taken after the attribution arm's last invocation ends.
      The r16 samples read and add to the copies.
    - **Pinned state:** the screener clone at `f62d164`, clean. The MRI run-history ref is recorded; a move is
      reported.
  - **Packs.** The r16 packs are fixed now.
    - **Rule.** Each r16 pack is the frozen r15 pack of the before/after test, with its first line's
      "(pack revision 15)" changed to "(pack revision 16)". Each sidecar is the frozen r15 sidecar, byte for byte.
    - **Registered sha256:**

      | Name | Pack | Sidecar (the r15 sidecar's own hash) |
      |---|---|---|
      | UGI | `ccb1aebe20a2ddc37641299fc6d8f62bde53e1bc47fe63a80bc23f069442f610` | `704928273f893af61df2f32b27972fa3219cd6e736ed2d7b6ab6dfd0f4df1711` |
      | LAMR | `2603f3d81864e3333bbf58fc7893d1d28154a3628af7d66634e60c0e9b33e2db` | `7a6f6d52eb9ea00b88767848a7d23d4cbbe5e14309689826d0d76f887e4630ce` |
      | EZPW | `ac3b65c176346a8d81ffcdf30d2cf1e5f91f3daf9c33c61a84341ddd022b03d1` | `fb0e8cbf98025d1555905cc7c7ab2096785e143cfcda0a6d87265679118a6604` |
    - **Proof that this is what the fix commit builds (G1, required).**
      - In one session, the build makes every pack twice, with the before/after test's own worker, from the copied
        data at the before/after clock (2026-09-28 12:00): once in the fix commit and once in a control tree at
        `3153924`.
      - The worker blocks sockets, refuses git network calls, stubs the MRI fetch and uses the recorded quotes.
      - The two packs must be identical except their first line, which may differ only in the revision number.
        The two sidecars must be identical.
      - Any other difference stops the re-run: the fix changed what the model reads.
    - **Reported (G2).** Whether the control rebuild equals the frozen r15 pack byte for byte. It did in the
      reviewer's dry runs (2026-09-29).
    - **Deadlines.** The build must run before 2026-10-01 17:14 KST. Every sample must finish before 2026-10-08
      17:14 KST, when the research briefs turn 14 days old.
  - **Checks before the first sample** (`ab16_check.py`; all must pass; (i) is reported only).
    - (a) The version-1 facts match r14's, with the before/after rule for EZPW's consensus-implied value.
    - (b) Consensus data status is "ok".
    - (c) The packs are the registered ones.
    - (d) The fix commit's pack reader reads the revision-16 pack as it reads revision 15, reads r14's as legacy
      text, and agrees with `3153924`'s reader.
    - (e) The model-visible tool text differs from `3153924`'s only in the descriptions of `shares_diluted` (top
      level and per scenario) and of `scenarios`. Every difference is listed for the reviewer.
    - (f) The TASK and research addendum are unchanged.
    - (g) The price line is present.
    - (h) The company's own words line is present.
    - (i) The first-turn prediction.
    - (j) The r14 run files and the baseline score are unchanged, and v32's system text is the registered one.
  - **Run.** Each of the three invocations must first pass these checks:
    - the state check (packs, data, quotes, the fix commit's tree clean at its commit, the screener clone);
    - the sample deadline;
    - SearXNG answers;
    - no model is loaded;
    - the GPU holds less than 200 MiB;
    - v32's system layer is the pinned one.

    During each invocation, the model must load 100% on GPU, or the invocation is stopped.
    - **Stop rules.** An invocation that exits non-zero stops the run. A failed bar does not stop the run.
    - **No re-run.** An invocation already recorded is never run again.
    - **Standing rules.** The operator's GPU-sharing rule applies (a PAUSE file). `DEPTH_PAUSED` stays, and KIS
      stays halted.
    - **Duration.** About 4.5–5 GPU hours; r15's three invocations took 1 h 25, 1 h 09 and 1 h 59.
  - **Bars.** Every bar must pass.
    - **Definitions.** Per-sample definitions are those of `brief_ab_step4.md` section 8, with the before/after
      scorer's two recorded corrections:
      - B-6's first sub-bar is 0.90;
      - B-7 uses production's fiduciary gate.
    - **The registered hand step.** A sample with no desk-backed Base has its share count read from its memo by the
      reviewer.
    - **References.** S_ref is the r16 sidecar's `shares_default` (the r15 value). The price is the recorded quote.
      The r14 values below are from the baseline score.
    - **B-1.** 6 of 6 r16 samples are recorded, no r16 invocation lost a sample, and the pre-sample checks pass.
    - **B-2.** For each name, r16's direction on the equity basis equals r14's.
    - **B-3.** For each name, r16's median Base equity lies in [0.95 × min r14, 1.05 × max r14]:

      | Name | Band |
      |---|---|
      | UGI | $7.049B–$10.649B |
      | LAMR | $18.149B–$20.139B |
      | EZPW | $3.462B–$4.017B |

      - The section 8 exception is unchanged: a miss passes only if it follows from a desk refusal that made the
        model give a reason for, or correct, a departure that r14 made without a reason, as an r14 flag shows.
    - **B-4.** r16's two-sample spread is at most max(r14's spread, 15%). The limits are UGI 36.69%, LAMR 15% and
      EZPW 15%.
    - **B-5.** r16's median catalysts are at least r14's median minus 1 (UGI 1.0, LAMR 5.5, EZPW 4.0).
      `catalysts_missing` appears in r16 only where it appeared in r14; it appeared in no r14 sample.
    - **B-6.** Three sub-bars.
      1. **First turn.** For each (name, sample) pair, r16's first turn is at most 0.90 × r14's (UGI 30,532, LAMR
         30,670, EZPW 30,696).
      2. **Tokens outside research turns** (the operator's ruling, 2026-09-29 10:17 KST, recorded as made after
         seeing results). The median of r16's six gated totals must be at most 1.10 × the median of r14's six.
         r14's median is 76,738.5 generated tokens, so the limit is 84,412.35.
      3. **Peak window.** The median of r16's six peak-window values is at most r14's (66,781.5).
      - **Turns.** A sample's turns are the `turns` entries of every `sample<i>_research*\_research_snapshot.json`
        of that sample, retries included.
      - **Calls in a turn.** Each turn takes the next `n_tool_calls` entries of its snapshot's `calls`, in order. A
        turn marked `forced_report` or `budget_exhausted` takes none.
      - **Research turn.** A turn after its snapshot's first turn, with at least one call and no
        `run_financial_model` call.
      - **Gated turns** are all the others:
        - each snapshot's first turn;
        - every turn with a `run_financial_model` call, accepted or refused (refused desk turns count inside the
          gated total);
        - a turn that mixes research and desk calls;
        - every turn with no call: the memorandum, a forced report, a budget-exhausted turn, a window retry.
      - **Gated total.** The sum of `gen_tokens` over the gated turns.
      - **When sub-bar 2 fails outright:**
        - an r16 sample's calls do not add up to `len(calls)`;
        - a gated turn has no integer `gen_tokens`;
        - fewer than six r16 samples exist.
      - **Reported, not gated:**
        - research-turn tokens and research calls per sample;
        - refused-desk tokens;
        - the before/after thinking measure (`qtok`), for continuity.
    - **B-7.** All 6 r16 contracts carry every field in `FORM_FIELDS`, and production's fiduciary gate returns PASS.
    - **B-8.**
      - All 6 r16 samples have a joint desk run.
      - None reaches 7 refused calls.
      - The median of refused calls is at most 3.
    - **B-9.**
      - Every r16 Base share count is within 1% of S_ref, or the run carries `shares_reason`.
      - No sample is flagged `shares_reason_uncited`.
      - EZPW's counts and per-share values are reported for both arms.
  - **Scoring.**
    - `ab16_score.py` first re-extracts every r14 sample from `ab_step4` with the before/after extractor, writing
      nothing there.
    - Each r14 sample must reproduce the baseline score's row, field by field, and r14's gated median must
      reproduce 76,738.5. Otherwise no verdict is written.
    - The scorer then writes the bars. B-3's exception, the hand step and the verdict are the reviewer's.
  - **After the verdict.**
    - **FAIL.** Revision 16 is not used, the final test keeps waiting, and the reviewer diagnoses. Any further rerun
      needs a new pre-registration.
    - **PASS.** The follow-on amendment to the final test applies.
  - **Scripts** (`scratchpad\ab16\`; hashes in `ab16\ab16_tooling.sha256`). All seven were tested with no GPU,
    network or Ollama.
    - `ab16_common.py`
    - `ab16_setup.py`
    - `ab16_build.py`
    - `ab16_check.py`
    - `ab16_extract.py`
    - `ab16_score.py`
    - `ab16_run.sh`

    They import or source the before/after scripts unchanged (`ab\ab_common.py`, `ab_build.py`, `ab_check.py`,
    `ab_score.py`, `ab_gpu.sh`), checked by hash. They read `ab_step4` and never write it; every output goes to
    `scratchpad\ab_rev16\`.
  - Pasted by the orchestrator at 10:48 KST, before the fix commit, any revision-16 pack or any r16 sample. The tooling list `ab16\ab16_tooling.sha256` (sha256 `4d501384fdec2b0ad801d0ec40b073192da127b430f7fb9e5336c48ccd10d9ab`) was re-checked at the same time: all files match.
- **The final six-name test, amended to revision 16 (reviewer, 2026-09-29; takes effect only if the revision-16
  re-run's verdict is PASS, and before any pool, prep or draw).**
  - **Why.** The final-test registration says: "If the verdict names a defect to fix first, the fixed commit
    replaces `3153924` by amendment before the pool day, and the tooling is regenerated." The before/after verdict
    named three desk defects. Their fix is revision 16, and the re-run tests it.
  - **When.** Only after the reviewer's PASS on the revision-16 re-run. Until then, the final test waits. If the
    re-run fails, this amendment never takes effect.
  - **What changes.**
    - **Code.** The fix commit replaces `3153924` (its commit id is recorded here when it exists). The code is
      revision 16. The gate is unchanged, v6. The draw file pins the commit from the tree's HEAD, as registered.
    - **Tree.** `scratchpad\final\tree` is the registered detached worktree, still unused.
      - Before the move, it must hold no data root (no `enrich`, `cache` or `research` folder) and no
        `final_logs`, which shows no prep or draw ran there.
      - The orchestrator moves it with `git -C <tree> checkout --detach <fix commit>`.
      - It must then sit at the fix commit, clean, with its `research-venv` junction.
      - If the tree holds any data, a fresh detached worktree at the fix commit is made in its place instead.
    - **Tooling.** The reviewer regenerates it with `make_final_tooling.py`, from the same untouched sources. Two
      changes:
      - `score_final.py`'s `PACK_REVISION` goes from 15 to 16, so it scores only revision-16 verdicts;
      - the docstrings say "revision 16 (<fix commit>)".

      Then:
      - `sim_final.py` moves to revision-16 pack text and is re-run: every per-name case and every six-name set as
        expected;
      - the files generated for `3153924` are kept, with their hashes, under `final\superseded_rev15\`;
      - the new `final_tooling.sha256` replaces the pinned `718de453be34bd57964403041987c4e0ec05fd2e576a4e9066fd728436dd0c9c`,
        and its hash is recorded here.
    - **Wording.** Where the registration says "revision 15", read "revision 16". The years 3–5 cap mark and every
      other mark carry over unchanged.
  - **What does not change.**
    - The model: `rs2-analyst-deep-mtp5-v32`, tag `5578678df015`, system layer
      `sha256:04894e6c3b217be46f48c329ca7c6c8dd7347d344513ec4c5cd723213b0c0ab7`. The draw still refuses any other
      digest.
    - The screener pin (`f62d164`) and the population source (`4b382bd`, ranks 136–400).
    - The strata, exclusions, data conditions and marks. The re-run's names (UGI, LAMR, EZPW) are already excluded.
    - The run rules, the crash rule and the thinking-loop 500 rule.
    - The seed rule. The pool day is the local day on which the prep and the draw both run, after this amendment;
      the seed follows that day. No seed is chosen.
- **Revision 16 committed: `9c3d53a5bafafd2d62156b481e30f8a5d2f68db3` (orchestrator, 2026-09-29 12:12 KST), on
  `review-2026-09/phase-4-simplify`.** This is the fix commit the revision-16 re-run registration names.
  - **Coder.** Gemini's quota ran out mid-task (`Individual quota reached … Resets in 82h5m36s`). Its partial diff
    was saved as `scratchpad\gemini_rev16_partial.patch` and the tree reverted. Sonnet then did the brief from
    scratch.
  - **Beyond the brief (orchestrator).**
    - Any scenario entry lacking `base_cf`, `explicit_growth` or `wacc` is refused. Sonnet showed that a
      three-entry call with one incomplete entry was accepted, with Kelly at probabilities summing to 0.67.
    - `fiduciary_gate.contract_base` uses `is None` instead of `or`.
  - **Reviewer: APPROVED WITH CONDITIONS, then APPROVED.**
    - Three conditions were met:
      1. the share-unit refusal carries no per-share values (§3.5), only the ratio and the pack's count;
      2. a V5 test that passed for the wrong reason was rewritten;
      3. the revision comment was corrected.
    - The reviewer independently verified:
      - the suite, 1581 (1526 at `3153924`);
      - the r15 replay: 15/15 reproduced, 5/5 full sets identical, 7/7 two-scenario calls refused, and 2/2
        share-unit variants equal;
      - 291 packs differing on the first line only, with facts equal;
      - the tool text differing in exactly the three allowed descriptions, with the TASK unchanged;
      - every existing test's desk outcome, before and after, across 92 tests: none loosened;
      - the ab16 setup, build and checks on the tree: the three revision-16 packs reproduce the registered hashes.
    - A `git archive` export of `9c3d53a` gives 1579 passed, 1 skipped and 1 failed. The failure,
      `test_p1_7_research_brief::…stale_brief_adds_force`, also fails on the export of `3153924`: it belongs to the
      bare export's environment, not to the change.
  - **Attribution (reviewer's replay of the calls finished so far).** v31 with the revision-15 briefing also sends
    the two-scenario shape (UGI sample 1 call 11, LAMR sample 2 call 1). The shape comes from the revision-15
    briefing and tool text, not the v3.2 charter.
  - **Carried to a follow-up (coder):**
    - `depth_sanity.py`:154 and :162, numeric `or`;
    - the `sbc_dilution` ≥ 1 share unit;
    - the years 3–5 cap tests 04, 05 and 13, which have no price;
    - README:91's stale `PACK_REVISION = 6`;
    - a harness flag for a Base share count 10× or more away from the default (a unit error written with every
      reason is still accepted, by the annotate-only design).
- **Attribution arm complete and the re-run cleared to start (reviewer, 2026-09-29 13:05 KST, before the first r16
  sample).**
  - **Attribution values (e7c0b03 with v31):**

    | Name | Sample 1 | Sample 2 |
    |---|---|---|
    | UGI | $47.28 | $47.28 |
    | LAMR | $155.89 | $177.86 |
    | EZPW | $46.43 | $46.71 |

  - **Turn split** (`b6_split.py`, `ab_step4\records\b6_split_20260929.json`), r14 / attribution / r15:

    | Measure | r14 | attribution | r15 |
    |---|---|---|---|
    | Median thinking | 67.7k | 60.1k | 104.6k |
    | Median tokens outside research | 76.7k | 65.6k | 77.2k |
    | Research tokens, summed | 83.9k | 148.6k | 149.2k |
    | Refused-turn tokens, summed | 0 | 8.0k | 74.3k |
    | Two-scenario calls | 0 | 2 | 7 |

  - **What it localizes:**
    - The two-scenario shape and the research growth come from the revision-15 briefing and tool text, not the
      v3.2 charter.
    - The briefing does not lengthen deliberation, and the v3.2 charter shortens the memo.
    - r15's excess over the attribution arm is almost all desk-defect turns, which revision 16 removes: refusals
      add 66k and extra desk turns add 33k.
    - LAMR's lower values come from the briefing's base-year check. 3 of 4 revision-15 LAMR samples moved year-1
      growth down from about 26%, against 0 of 2 in r14. Two of them cite the one-time Vistar gain.
    - The orchestrator's first reading, which pointed at the charter, was wrong and is corrected here.
  - **Setup, build and checks** (13:01–13:02): all pass. The r16 packs equal the registered hashes. G2 holds: the
    control rebuilds are byte-identical to the frozen r15 packs.
  - **The registration stands as recorded.** Known risks, written down before the run:
    - **B-3 on LAMR will probably fail again.** Three of the four revision-15 LAMR equities ($16.72B, $15.82B and
      $18.05B) sit below the $18.149B floor. Resampling puts the chance that r16's median also falls below it at
      about 80%.
    - **B-4 on LAMR is borderline:** 14.8% and 14.1% against a 15% limit.
    - B-3 is not widened. The briefing causes the LAMR move, but that does not show the lower value is right. The
      pack prints two bases (0.694 in the defaults and 0.733 in the consensus-implied line) and flags a −12%
      base-year gap. That is an open question about the consensus reference, and B-3 is the only bar watching it.
    - **If the re-run fails only on LAMR's B-3 or B-4,** the reviewer traces it and the operator rules on it,
      recorded as made after seeing the results.
    - **Design item (reviewer, after the re-run):** LAMR base-year handling in the consensus reference.
- **Revision-16 re-run: reviewer's partial trace (UGI and LAMR done, EZPW running), and a conditional operator
  ruling (2026-09-29 16:14 KST, made after seeing results and recorded as such).**
  - **UGI** ($48.75 and $47.23): clean.
    - Both samples sent Base, Bull and Bear; there were no two-scenario calls.
    - Sample 2's call 7 was refused by the new incomplete-entry check (no wacc in the Base and Bull entries).
      Replayed through the `3153924` desk, that call would have been accepted, valuing only the Bear ($24.62) and
      sizing Kelly on one outcome. The check caught a real defect.
  - **LAMR** ($178.99 and $165.08): **B-3 fails as registered.**
    - Median equity is $17.46B against the $18.149B floor. The exception does not apply.
    - B-4 passes: the spread is 8.4%.
    - Both samples keep the default base_cf ($0.694B TTM) and take year-1 growth below the reference's +19.4%, with
      reasons: sample 1 cleans out the Q1'25 Vistar gain, and sample 2 bridges to the company's FY26 FCF run rate
      from its 2026-08-06 8-K.
    - There were no refusals and no unit issue. The `3153924` desk gives identical values for both calls, so
      revision 16 did not cause the miss.
    - **Cause (reviewer):** the reference level applies consensus growth to FY2025 GAAP owner earnings that
      include the one-time $67.7M Vistar gain. It implies FY26 EPS of $6.90 against a consensus of $6.06, about
      14% high. This is the GAAP/adjusted artifact E18 named. Five of six LAMR samples under revisions 15 and 16 sit
      below r14's $188.
  - **Other bars so far:**
    - first turn 0.8676 and 0.8737;
    - gated tokens 59.9k, 58.9k, 44.3k and 59.9k, so the sub-bar's median cannot exceed 59.9k against a limit of
      84.4k;
    - peak window 54.4k–58.9k, against 66.8k;
    - every sample joint; refusals 0, 1, 0 and 0.
  - **Operator ruling (conditional).** If LAMR's B-3 is the only miss once EZPW is scored, the miss is accepted
    and the final test proceeds on revision 16 (`9c3d53a`) under the follow-on amendment.
  - **Booked as a must-fix before real money (reviewer owns the design):** the consensus reference's handling of
    one-time items in the GAAP base year.
- **Revision-16 re-run: scored FAIL as registered; operator ruling extended; final test cleared (2026-09-29 17:10
  KST).** The run finished 16:50 and all invocations exited rc=0. Score: `ab_rev16\records\score.json`.

  | arm | UGI | LAMR | EZPW |
  |---|---|---|---|
  | r14 | $47.28, $34.59 | $188.03, $188.78 | $45.87, $43.69 |
  | r16 | $48.75, $47.23 | $178.99, $165.08 | $42.05, $44.58 |

  - **Pass:**
    - B-1: 6/6 recorded.
    - B-2.
    - B-4: spreads 3.2%, 8.4% and 6.0%.
    - B-5.
    - B-6:
      - first turns 0.855–0.874;
      - gated tokens at 0.78× r14;
      - peak window below r14's.
    - B-7: fiduciary PASS on all six.
    - B-8: all joint; refusals 0, 1, 0, 0, 0 and 0.
    - B-9: every share count within 1%.
  - **Fail: B-3 on two names.**
    - LAMR: median equity $17.46B against the $18.149B floor.
    - EZPW: median equity $3.439B against the $3.462B floor, 0.7% below.
  - **Reviewer's trace of EZPW.** Only year-1 growth moved; every other input is identical across the four arms, and
    the share count cancels in equity.
    - r16 took +3% and +5% in year 1, because the June TTM base already holds nine months of a year whose
      consensus EPS growth is +42%. This is the E18 level rule.
    - r14 and most revision-15 samples took +9% to +12% on top: the period double count that E18 measured, which
      the desk's ±15% level band let through.
    - The exception does not apply: there was no r16 refusal, and r14's share-count flag records a reasoned
      departure.
    - Replaying every accepted r16 desk call through the revision-15 desk gives identical values, so revision 16's
      code caused neither miss.
  - **Reviewer's verdict:** REJECTED as registered; APPROVED WITH CONDITIONS for the final test. The condition is that
    the operator extends the LAMR ruling to EZPW.
  - **Operator ruling (17:10 KST, made after seeing the results and recorded as such).** Both B-3 misses are
    accepted. The final six-name test proceeds on revision 16 (`9c3d53a`), under the follow-on amendment.
  - **Booked (reviewer owns both):**
    1. **Consensus reference must-fix, widened.** It covers one-time items in the GAAP base year (LAMR) and the
       level band. ±15% lets a sample re-apply the current year's growth on a trailing base (EZPW).
    2. **B-3 redesign.** Before the next comparison test, B-3 is measured against a baseline built on the corrected
       reference path, not on the path that double counts.
- **Final-test amendment to revision 16 took effect (orchestrator, 2026-09-29 17:11 KST, after the operator's
  ruling and before any pool, prep or draw).**
  - The fix commit is `9c3d53a5bafafd2d62156b481e30f8a5d2f68db3`.
  - The regenerated tooling manifest `final\final_tooling.sha256` has sha256
    `646de6ac289be9c834ba79fddad80ce95e3ba9905cd9cca593520a415a8f372d`. It replaces `718de453…0dd0c9c`, and every
    file checks.
  - The revision-15 files are kept in `final\superseded_rev15\` with their manifest, and every file checks.
  - The only logic change is `score_final.py`'s revision check, which went from 15 to 16. The reviewer's simulations
    are all as expected.
  - `final\tree` moved from `3153924` to `9c3d53a`. It was clean before and after, and it still has its
    `research-venv` junction.
  - The pool day is 2026-09-29 and the seed is 20260929, provided the prep and the draw both finish before
    midnight.
- **Final six-name test: pool day 2026-09-29, seed 20260929 (orchestrator, 17:55 KST).**
  - **Prep** (17:11–17:49): 465 of 465 names complete, with no failures.
    - Every name logged an HTTP 404 from the openbb earnings-call transcript source (`defeatbeta`
      `stock_earning_call_transcripts.parquet`); on 2026-09-27 it was about 135. The transcript excerpt is therefore
      absent from every pack. The SEC 8-K block is present on all six drawn names. Sent to the reviewer.
  - **Draw** (17:49–17:50, first and only run, rc 0): population 265, 23 excluded as design-touched, 13 in the
    producer class, a pool of 229, with 0 data or build failures.
    - **Fast:** FIVE, KALU, NUE.
    - **Steady:** HAE, PIPR, KMT.
  - **News prep and previews** (17:50–17:54): all six done (`final\previews_final\`).
  - **Seen in the previews and sent to the reviewer:**
    - FIVE's RECENT COMPANY NEWS block is almost all unrelated articles. The ticker is a common word, and the
      pack's company-news search has no relevance filter for it.
    - NUE's trailing twelve months run through 2026-04-04 and KMT's through 2026-03-31, under the pinned screener
      clone. The pack declares both in its DATA FRESHNESS line.
  - **A2:** the orchestrator's draft is with the reviewer (`final\draw_a2_rules_final_DRAFT.json`).
- **A2, pre-registered from the final test's previews before any sample (reviewer, approved with conditions; pinned
  by the orchestrator at 18:23 KST).**
  - **The rules file.** `final\draw_a2_rules_final.json` is the reviewer's `a2_rules_reviewer.json`, copied byte for
    byte (sha256 `4e53785f82dbf7dd8bd0213c4c0f30d9df76ccc66dd2b9e4574a2824e6ad2da1`).
  - **Tightening against the draft.**
    - The orchestrator's draft matched 17–34 of 72 earlier reports on 14 other names.
    - The reviewer's lists match 5, 1, 3, 0, 0 and 0 (FIVE, KALU, NUE, HAE, PIPR, KMT).
    - Every list keeps phrases that appear in that name's own pack.
  - **How A2 passes.** Both usable samples match the keyword list, and the human read passes. Each name's
    development and the test the human read applies are set now:

    | Name | Development | Human read passes when |
    |---|---|---|
    | FIVE | Q2 FY2026 (8-K 2026-09-02): net sales +22.9% to $1.3B, comparable sales +14.1%, full-year sales and EPS outlook raised | A sentence names these results or the raised outlook. A copied table row alone does not count. |
    | KALU | Record Q2 2026 (8-K 2026-07-22): conversion revenue $437M, adjusted EBITDA margin 38.1%. The 2026 outlook was raised: conversion revenue at the high end of +10–15%, adjusted EBITDA +45–55% | It names the record quarter or the raised outlook. |
    | NUE | The September Q3 2026 guidance trailing estimates; the shares fell about 5% | It names the September guidance and that it fell short. Quoting the July "Third Quarter of 2026 Outlook" alone does not count. |
    | HAE | Q1 FY2027 (8-K 2026-08-06): revenue $339.4M (+5.6%); FY2027 guidance raised to reported +5–8% and organic +4–7%. Or the September re-rating: Citi's upgrade, and BofA's upgrade on the CSL supply deal | It names the raised guidance, or the CSL supply deal or the upgrades. CSL named only as a customer does not count. |
    | PIPR | The launch of equities trading in Europe with a new Paris office | It names the European equities launch or the Paris office. A generic "international expansion" does not count. |
    | KMT | Q4 FY2026 (8-K 2026-08-05): sales $737M (+43% reported, +42% organic), EPS $2.96 against $2.31 expected, and the FY2027 outlook. Or the tungsten-price rally behind that surge, and whether it has played out | It names the Q4 results or the FY2027 outlook, or weighs the tungsten-price effect. A generic "tungsten is a key input" does not count. |

  - **The preview notes: none stops the run.**
    - FIVE's noise news: if a FIVE sample cites a noise row, the human read records it as a finding.
    - The transcript gap and the stale trailing figures are notes only.
  - **Carried (coder, Phase 6):**
    - a relevance filter for the pack's company-news block, for tickers that are also words;
    - a transcript source, or the gap declared in DATA 12 (the pack now omits the section without saying so).
- **Final run: HAE crash, diagnosed before its one re-run (orchestrator, 2026-09-29 23:53 KST).**
  - **Finished:**
    - FIVE: HOLD, $233.93 and $214.44 against $228.00;
    - KALU: HOLD, $158.12 and $158.04 against $151.57;
    - NUE: OVERVALUED, $169.18 and $198.11 against $244.49.
  - **HAE exited rc=3 at 23:52, before any sample.** The run stopped, as its stop rule says.
  - **Diagnosis.** The deep-research step aborted with `::ABORT:: 1/5 topics hit infra errors — brief NOT written`.
    - After two low-trust domains were dropped, the "Competitive Position & Moat" topic had zero sources, and its
      uncited prose was discarded.
    - The SearXNG preflight also warned that two engines were failing (gabanza: connection error; dogpile:
      suspended).
    - The pipeline refuses to analyse on a partial brief (`::HARD FAIL:: research infra error`).
    - This is a web-research sourcing failure. It is not a model or harness defect, and no sample was written.
  - **Action under the crash rule:** one `--rerun HAE`, then the first-mode run resumes for PIPR and KMT (names
    already run are skipped). A second HAE crash fails HAE.
  - **Booked for Phase 6:** one zero-source topic aborting the whole research brief is a single point of failure
    in production. The design question is whether a zero-source topic should be declared missing rather than
    aborting the brief.
- **Final run: KMT crash, diagnosed before its one re-run (orchestrator, 2026-09-30 03:10 KST).**
  - **The HAE re-run succeeded:** HOLD, $109.49 and $106.38 against $105.73.
  - **PIPR:** UNDERVALUED, $133.17 and $117.90 against $68.245.
    - Sample 1 is flagged `above_analyst_high_1.58x_cap_1.5x` and `desk_share_count_mismatch`.
    - This goes to the reviewer's human read.
  - **KMT exited rc=3 at 03:10, before any sample.** The failure is the same as HAE's: the "Competitive Position &
    Moat" topic had zero sources (`::ABORT:: 1/6 topics`). The SearXNG preflight shows the same two failing engines.
  - **Two of six names failed the same way, so this is systemic:**
    - that topic's searches return mostly low-trust domains;
    - one zero-source topic aborts the whole brief.
  - The Phase 6 item booked at the HAE crash is raised to must-fix before production.
  - **Action under the crash rule:** one `--rerun KMT`. A second KMT crash fails KMT.
- **Final six-name test: FAIL as registered; verdict REJECTED (reviewer, 2026-09-30 05:24 KST).**
  - **Scorer** (sha `965ac793…db06`, run at 05:19; human reads `final_human.json` `f6f53168…7b11`): 3 of 6 names
    pass every mark.
    - Three names miss a judgment mark where the rule allows one.
    - No integrity failure, no F5 hit, no open mark.

    | Name | Verdict | Values vs price | Marks |
    |---|---|---|---|
    | FIVE | HOLD | $233.93, $214.44 vs $228.00 | all pass |
    | KALU | HOLD | $158.12, $158.04 vs $151.57 | base on reference FAIL |
    | NUE | OVERVALUED | $169.18, $198.11 vs $244.49 | repeatability FAIL (17.1%) |
    | HAE | HOLD | $109.49, $106.38 vs $105.73 (re-run) | all pass |
    | PIPR | UNDERVALUED | $133.17, $117.90 vs $68.245 | A1 FAIL |
    | KMT | UNDERVALUED | $58.89, $58.89 vs $31.08 (re-run) | all pass |

  - **Causes of the three misses.**
    - **NUE is a real analyst miss.** Both samples rejected the capex-depressed default owner-earnings base ($0.587B,
      against about $4.35B of consensus earnings), with reasons, but corrected it in different ways.
    - **PIPR is a harness defect.** `consensus_valuation.py`:1748–1763 passes a whole share count (71,241,000,
      legal since revision 16) to `contract_fill.s2b_share_match`, which works in billions. The result is a false
      `desk_share_count_mismatch`. The desk itself read the count correctly. The reviewer's revision-16 approval
      replayed the desk but not the harness.
    - **KALU is a defect in the reviewer's registered window rule.** A TTM-named sample that stays on the printed
      levels is measured against the TTM-path value, which double counts. Its $158.04 equals sample 1's $158.12.
    - The reviewer does not recommend re-scoring to a pass: a pass would be a choice made after the results, and it
      would not make the two buy calls safe.
  - **The finding that matters: PIPR and KMT would have been live buy calls.**
    - They were valued at 1.8× and 1.9× the price, 1.58× and 1.70× the discounted Street high.
    - Gate v6's fence (about 1.82× the high) and the 150% margin-of-safety cap let both through, as designed.
      Fiduciary PASS; quarter-Kelly 24.75%; proposed weights 5–7%.
    - **The values come from engine defaults, not the analyst's research.**
      - A uniform cost of equity, plus terminal growth taken from one year's revenue growth clamped to
        2.34%–3.75%, gives about 20× terminal multiples on cyclicals near a peak.
      - PIPR is 65–70% terminal value in a record deal cycle.
      - KMT capitalizes post-tungsten-spike owner earnings as permanent. Its FY26 operating cash flow was −$0.004B,
        because inventory absorbed the windfall. With pre-spike earnings from year 2, KMT is about $38.
      - PIPR has no unit error (a 4-for-1 split, handled). The split detector prints False, a data-flag defect.
    - **The wider pattern.** All three directional calls lie outside the whole Street range:
      - NUE below the lowest target;
      - PIPR and KMT above the highest.

      This is the treatment the operator ruled on 2026-09-26 (a through-cycle base, terminal growth paid for by
      reinvestment, fading excess returns). Its first attempt failed and is back with the reviewer.
  - **The HAE and KMT research crashes** each re-ran once, cleanly (see the two diagnoses above).
  - **Fix list:**
    1. **Blocking before real money:** the ruled through-cycle treatment. Evidence: PIPR, KMT, NUE. The reviewer
       designs it; then the operator rules, a versioned PACK_REVISION, a whole-book test by sector and a new draw.
    2. **Blocking:** the harness share-check units (`consensus_valuation.py`:1748–1763). Test: 71,241,000 must match
       the vendor count at 1.008 with no flag. Coder; reviewer checks.
    3. **Blocking for production:** research must not abort when the trust filter empties a topic (HAE, KMT). Coder;
       reviewer checks the design. The failing search engines (gabanza, dogpile) belong to the orchestrator.
    4. **Blocking for the next registration:** an external-validity mark. Any directional call outside the discounted
       Street range gets a human evidence read. Reviewer.
    5. **Carriable:**
       - the window rule for a TTM-named sample on the printed levels (reviewer);
       - the reference rolls forward while the desk does not, a 2–7% bias (reviewer, then coder);
       - the split detector (coder);
       - the dilution-factor double count, measured across the book (coder);
       - earlier bookings: one-time items in the consensus reference, the company-news relevance filter, and the
         transcript source.
  - **Verdict: REJECTED.** The analyst is not certified for real money. DEPTH_PAUSED and KIS_HALT stay.
- **After the final test (2026-09-30 11:26 KST). The operator approved the three next steps and asked for a
  Qwen3.6 single-stock trial. They are away for the day ("fix the ones you identified … don't start phase 6 yet").**
  - **Committed `fee17cf` (review-2026-09/phase-4-simplify):**
    - the harness share-check units fix;
    - clean-up batch 1:
      - two depth_sanity numeric `or` defaults;
      - the `sbc_dilution` unit;
      - the years 3–5 cap tests 04, 05 and 13 now test accepted runs;
      - README;
      - the annotate-only flag `desk_share_count_far_from_default_<ratio>x`.
    - Nothing the model reads changed; PACK_REVISION stays 16. Suite: 1632.
    - **Reviewer: APPROVED.** A harness replay over 18 samples changes only PIPR sample 1.
  - **Dilution census (report only, `cleanups_accept\dilution_census.json`).**
    - The double-count shape (vendor count within 1% of filed diluted, factor ≥ 1.02) occurs on 9 of 291 book
      names. Only PGY has the factor applied: default/filed 1.086.
    - **Reviewer decision for revision 17 (C5):** the factor is not applied when the vendor count is already within
      1% of filed diluted.
  - **Revision-17 package (reviewer design; briefs in `scratchpad\rev17\` A–D).** One bump, one whole-book test and
    one registration cover everything:
    1. **Through-cycle valuation (the 2026-09-26 ruling).** Everything is computed from the company's own filed
       record, with no industry labels:
       - (A) growth is paid for at the return on new capital;
       - (B) excess returns fade by the record: the terminal return on new capital is
         r + p × (median return on tangible equity − r), where p is the share of 8 years above the cost of equity;
       - (C) where the record shows a completed cycle, the margin reverts to its 8-year median over years 6–10;
       - (D) a working-capital charge from the company's median working capital per dollar of revenue;
       - terminal growth from the 8-year revenue trend, bounded between breakeven inflation and 3.75%.
       - Returns are measured on tangible equity, which needs goodwill, intangibles and amortization from the
         extractor (brief A, stock-screener, local-only).
       - Exit-multiple inputs are removed.
       - The model still chooses years 1–5, the scenarios and the probabilities.
    2. A research topic left empty by the trust filter is written as NOT RESEARCHED. The brief still aborts on a
       real infra error or when half the topics are empty.
    3. The company-news relevance filter (full name, or the ticker in a finance pattern).
    4. The transcript status is declared in DATA 12.
    5. A split detector after the last filing.
    6. The window rule: the Base's years 1–2 are held at the fiscal-year levels unless a reason is given. The
       base-on-reference mark uses the fiscal-year reference only.
    7. The desk adopts the reference's roll-forward convention.
    8. Base-year earnings are capped at the consensus year-ago EPS (one-time items), and the level tolerance moves
       from 15% to a 5% hold.
    9. An external-validity mark for the next registration.
  - **Reviewer's development check** (book-equity stand-in, illustration only):

    | Name | Package | Price | Street |
    |---|---|---|---|
    | KMT | about $33 | $31.08 | $27–38 |
    | PIPR | about $64 | $68.25 | $81–93 |
    | NUE | about $196 | $244.49 | $231–310 |

    Two choices were made after the first replica numbers, and are declared in `tcd\DECLARED_BEFORE_COMPUTING.txt`:
    convergence over years 6–10, and part D.
  - **Decisions taken under the operator's delegation (recorded as such, reversible, nothing deploys):**
    - Keep part C, in its late form. The pre-declared fallback is the package without C.
    - Keep one cost of equity per sector. A company-level beta is revisited only if the whole-book test shows a
      bias by cohort.
  - **Whole-book test (brief D), with criteria W1–W9 pre-registered in the brief before any book-wide number.**
    - W1: steady compounders are about unchanged.
    - W2: peak-cycle names fall.
    - W3: low-return names fall.
    - W4: trough names are not pushed down.
    - W5: no hidden sector effect.
    - W6: external validity against the analyst range.
    - W7: no more than half the book is more than 10% below its price.
    - W8: coverage of at least 85%.
    - W9: desk equals reference.
    - If a criterion fails: diagnose, run the declared variant once, and if it fails too, go back to design.
  - **Build:** Sonnet runs brief A in `scratchpad\ss-r17A` (branch `review-2026-09/rev17-extractor`) and brief B in
    `scratchpad\rs2-P4-r17` (branch `review-2026-09/phase-4-rev17` from `fee17cf`), started 11:25. Brief C follows
    B, then D.
  - **Qwen3.6-35B-A3B preview (exploratory, not a registered test):**
    - unsloth UD-IQ4_XS, 17.7 GB, downloaded with the operator's approval;
    - model `rs2-analyst-q36-v32test`, v32's Modelfile with FROM changed and draft_num_predict removed;
    - it fits 100% on the GPU at 98k context (18.6 GB); tool calls work at about 90–115 tok/s, against about 40.
- **Revision-17 whole-book test (brief D): FAIL, so back to design by the pre-registered rule (Sonnet run, recorded 2026-09-30 15:17 KST; reviewer not yet consulted).**
  - **Population:** all 291 names built in both arms. W1–W7 count 185 names; 106 development names are excluded.
  - **Pass:**
    - W1: steady compounders unchanged, median 0.992.
    - W2: peak-cycle names fall, median 0.631.
    - W3: low-return names fall, median 0.545.
    - W5: no hidden sector effect.
    - W7: 50.00%, exactly on the line.
  - **Fail:**
    - W4: trough names are pushed down (median 0.812 on n=6; the bar is at least 0.95).
    - W6: 13.3% of names above 1.5× the discounted high and 15.6% below 0.5× the discounted low; the bar is at most 5% for each.
    - W8: three names lose their reference (AER; ATRO and SITM come out negative).
    - W9: PRTH's desk and reference differ (the `wc_in_base` rule), and three names differ only by rounding.
  - **The declared variant without the cycle margin also fails** (W2, W4, W6, W8).
  - **Revision 16 on the new data:** facts are identical on 291 of 291 names.
  - **Splits detected:** 9, of which 2 are real (MNST, IESC). The other seven are share-count unit defects: ATAT, DDI, EMBJ, SIMO, TSM, VLRS and POWL.
  - **Files:** `scratchpad
ev17D_accept
eport.md`.
- **Whole-book test verdict and redesign (reviewer; operator approved the redesign 2026-09-30 afternoon).**
  - **Revision 17's reference (cf6eb13) is REJECTED**, as the pre-registered rule requires. The follow-ups
    (C2b, C6b, C8, C1b) are APPROVED and committed as `c78dbf2`.
  - **The diagnosis rests on base rates** measured on 5,606 screener histories (base years 2018–2021, outcomes to
    2025):
    - margins at 1.2× or more of their typical level closed 61% of the gap in 3–4 years: 77% for records that
      swing, 33% for steady trends. The "one bad year" cycle flag predicts nothing (59% with it, 61% without);
    - the latest 3-year return median ranks future returns at least as well as the 8-year median (Spearman 0.675
      against 0.651);
    - a loss-making typical margin that has just turned profitable fell back to near zero about half the time.
  - **Classified failures:**
    - **Design:**
      - W6b: 10 new names far below the range, from full reversion on steady climbers, one-off shocks read as
        cycles, and negative typical margins;
      - W8: two negative values (one development name, SITM);
      - W9: the desk's working-capital proximity rule diverges from the reference.
    - **The reviewer's own criterion errors:**
      - W4 tested the whole package for one mechanism's job (the cycle margin lifted all six trough names;
        funded growth lowered them);
      - W6's 5% bars were unmeasured and unrealistic (under revision 16 a third of the book was already outside).
        This is recorded as a lesson for the next test and not applied to this verdict. W6 fails on relative bars
        too.
    - **Data and wording:** 3 real splits and 6 depositary-share unit mismatches. The case the D report called a
      vendor error is a real 3-for-1 split (the vendor's EPS history is divided by 3).
  - **Redesign (operator approved; reversible; nothing deploys):**
    - keep the earnings base, the one-off cap, working capital and funded growth;
    - margins revert partially for every name, at rates measured by the shape of the record, never below zero;
    - the return on new capital is a measured blend of the 8-year and 3-year medians, never below r, with
      persistence capped;
    - a value at or below zero is "not meaningful";
    - remove the desk's working-capital proximity rule;
    - the share-unit wording names depositary shares.
  - **Next:**
    - calibration offline on the screener universe minus the book;
    - a new test registered before any number, with one criterion per mechanism, W6 relative to revision 16 with
      stated denominators, W8 "no value ≤ 0" and W9 at a half-cent tolerance, run on a hold-out set of names not
      in the book.
- **Redesign progress (2026-09-30 17:20 KST).**
  - **Brief E calibration: APPROVED as registered.**
    - Operating margin is chosen (like-for-like 0.173 against 0.080).
    - Gap-closing fractions by cell: peak swing 0.751, peak trend 0.370, trough swing 0.530, trough trend 0.202,
      loss 0.981 (flagged).
    - w8 = 0.25; the retention caps never bind.
    - A hold-out of 400 undrawn candidates is frozen (sha d67cb07d…). Its names stay out of these documents.
  - **Brief F (the redesign) is coded, 1925 tests: APPROVED WITH CONDITIONS.**
    - Operating income is missing for 72 of 291 book names (32 have no revenue series, mostly banks; 33 file only
      pre-tax income), so their margin is held. That lifted a development name (PIPR) back to about $119, above the
      Street high.
    - The reviewer calls this a design gap, and his own. The fix is a pre-tax fallback that uses E's rates
      unchanged, adopted only if the registered transfer test E2 passes (at least 100 company-years, and at least
      0.05 better than no move). If E2 fails, those margins stay held and the pack says so.
    - The old cycle gate is not brought back: it predicts nothing.
    - Also required: hold the margin for a current loss (ruling 3); fix the tool text so it no longer contradicts
      the TASK, and re-pin (ruling 9); AGENTS.md; pin the calibration by its content.
  - **Hold-out data prep, D0 2026-09-30 16:29–17:19:** SEC refresh 400 of 400 (history sha dbd1df6a…) and enrich 400 of
    400, both with 0 failures. Brief G Amendment 1 was recorded before any hold-out number: the new arm is F + F2.
  - **Known limit:** 32 book names with no revenue series (mostly banks) keep a held margin.
- **E2 adopted; F+F2 committed as `6e6a5f9` (2026-09-30 18:02 KST; reviewer APPROVED).**
  - **E2 (the registered pre-tax transfer test):** 290 company-years (at least 100 required), skill against no move
    0.209 (at least 0.05 required). Every cell improves; base year 2018 is negative (n=48).
  - **Reviewer rulings:**
    - removing a stray scan hit on the token "G" (from the new "Brief G" text) restores E's exact firm set, and is
      not a post-hoc change;
    - the hold-out file is unchanged (d67cb07d…).
  - **Development check after F2, systemic only:**
    - PIPR $92.00: the top of its Street range ($81–93), 1.35× price;
    - NUE $219.55: 0.90× price;
    - the other seven development names are unchanged from F.
  - **Known limit:** where a company has large minority interests, its pre-tax margin includes the outside
    owners' share.
  - **Stale pack sentence:** the claim that the pre-tax field "admits a US-domestic-only tag" is false since
    stock-screener `32feee200a`. The fix is carried, before any GPU run.
  - **Next:** hold-out test G, run offline as registered with Amendment 1. The new arm is `6e6a5f9`; the old arm is
    `fee17cf`; the clock is frozen at D0 12:00 UTC.
- **Hold-out test G: FAIL on V5 alone; operator chose confirmation on fresh names (2026-09-30 19:01 KST).**
  - **Run:** `6e6a5f9` against `fee17cf`; 400 of 400 hold-out candidates built; H_tgt 268.
  - **Pass:**
    - V1a 0.190, V1b 0.083, V1c, V1d 0.293 (n=80, thin);
    - V2: 297 of 297 within half a cent;
    - V3: 0 violations;
    - V4;
    - V6a 0.075 against old 0.164, V6b, V6c;
    - V7 0.485;
    - book V2 and V3.
  - **Fail:** V5, steady compounders. The share in [0.85, 1.15] is 0.708 against a bar of at least 0.80; the median
    is 0.878 against a band of 0.90–1.07.
  - **Reviewer diagnosis: no defect.**
    - Funded growth accounts for ×0.952 (compounders with ordinary high returns now pay for growth) and the margin
      rule for ×0.974. The earnings base has no effect (×1.000).
    - The reviewer's V5 bar allowed only for the effect on infinite-return names. That bar error is the reviewer's,
      and it is recorded.
  - **Operator ruling:** accept that steady compounders are valued about 10–12% below revision 16, for those two
    ruled reasons.
  - **Next:** confirmation test G2 on 400 fresh names, drawn and frozen before any computation. Every other bar is
    unchanged. V5 becomes a residual check once the margin and funding effects are removed.
  - **Report-only concern:** in the loss-record cell, 12 of 21 names sit below 0.5× the discounted low, against 1
    under revision 16. That cell's rate is a flagged median with a wide interval, and it is due for the next
    calibration.
  - **Sonnet's smoke test** computed 3 hold-out references before the full run. No decision was made on them.
- **Confirmation test G2: FAIL on V7 alone; operator chose the loss-cell fix and one final test G3 (2026-10-01 11:05 KST).**
  - **Pass:**
    - V1a 0.127, V1b, V1c, V1d (thin);
    - V2: 304 of 304;
    - V3, V4;
    - **V5' residual median 0.999, with 0.829 within ±10%;**
    - V6a 0.088 against old 0.196;
    - V6b, V6c.
  - **Fail:** V7: 155 of 304 = 0.510 below 0.9 × price, against a bar of at most 0.50. The miss is 3 names. G had 0.485.
  - **Reviewer's diagnosis:**
    - The design sits on V7's line: both samples straddle 0.50 by about one standard error.
    - The loss-record cell concentrates the shortfall: 27 of 31 of its names are below the line, against 46.9% outside
      it.
    - That cell's rate (0.981) is the weakest calibration number. It is flagged, its own cell had n=73, and its
      interval is 0.51–1.40. The reviewer raised the median-versus-expectation concern at brief E's review, before G
      ran.
    - **Reviewer self-correction:** G2's V1 was not cleanly out of sample, because E excluded only G's names. G's V1
      remains the clean result.
    - The report's direction-mix table had its arms swapped; it is to be fixed.
  - **Operator ruling:** re-measure the loss cell as the expected non-negative outcome (brief E3, estimator fixed
    before computing), then run G3 on 400 of the 567 still-eligible names, with every bar unchanged, V7 included.
    - The fix applies to every company with a loss-making 8-year typical margin, about 1 in 10. It is not targeted at
      the names that tipped V7.
    - **If G3 fails, revision 17's reference does not ship and revision 16's reference stays.** This is the last
      fresh draw; 167 names remain.
- **E3 as registered failed; a one-time correction was approved (2026-10-01 11:21 KST).**
  - **G3's draw:** 400 of 567, seed 20261005, sha 8fb79467…, frozen; disjoint from everything already used. Nothing
    about these names has been computed.
  - **The registered E3 estimator** (mean of min(f, 1)) gave f_loss = −1.471 on n = 168, with the floor lifted.
    - f is unbounded below when the base margin is near zero, and three firm-years dominate the result.
    - Applied, it would have *raised* loss-record margins 2.46×. It was stopped before any further step.
    - **This is a specification error by the reviewer:** the formula capped only the fall. Two of this round's four
      stops are the reviewer's specification errors (the V5 allowance, and this formula).
  - **Reviewer ruling (Amendment 1 of the E3/G3 brief):** a correction is legitimate once, on four conditions:
    - a principle stated before its value is computed;
    - applied once;
    - G3 untouched;
    - if G3 fails for any reason, revision 16's reference stays, with no further fix this round.
  - **The correction:** each firm-year's outcome counted inside [0, 1], where a fall to zero or below is 1 and a rise
    is 0. The ratio of sums (0.73) and the trimmed mean (about 0.005) were already seen, so neither was chosen. A
    loader guard refuses any rate outside [0, 1].
  - **Known bias, recorded and not changed:** the lifted floor mixes in small companies, so the rate is probably
    harsh for the companies the system analyses.
  - **Operator approved:** correct once, then run G3.
- **Revision-17 hold-out test G3: FAIL on V5' and V6b (2026-10-01, reviewer verdict 13:05 KST). Revision 16's
  reference stays; the round is closed with no further fix (G3 registration, Amendment 1).**
  - **Inputs:**
    - 400 fresh names, sha 8fb79467…, the last draw the eligible pool allows; 167 remain.
    - History sha 3ceaa8c8…; clock frozen at D2 = 2026-10-01 12:00 UTC.
    - New arm ac68e25 (calibration v2: the loss cell re-measured as the clipped mean, 0.597). Old arm fee17cf.
    - 400 of 400 built in each arm, 0 errors. Outputs are in the scratch folder `rev17G3_accept`.
  - **Fail:**
    - V5': 30 of 39 = 0.769 within ±10%, against a bar of 0.80. The median, 0.997, passes.
    - V6b: outside the loss cell, 0.167 against 0.121 + 0.03 = 0.151, on 264 names (44 names against 32).
  - **Pass:**
    - V2: 311 of 311;
    - V3;
    - V4a 0.006, V4b 0.015;
    - V6a: 0.085 against 0.204;
    - V6c: 0.235 against 0.174;
    - V7: 150 of 311 = 0.482.
    - V1 is report-only and passed.
  - **Report only:**
    - V7 inside the loss cell 22 of 31 = 0.710; outside it 128 of 280 = 0.457.
    - Loss-cell names with targets: 20 of 30 below 0.5 × D_low (old arm 0.333).
    - Direction mix, old → new: above 160 → 126, within 39 → 35, below 114 → 151, no value 87 → 88.
    - G2's swapped table was an error in the written report only; the script was correct.
  - **Deviations, which do not affect the verdict:**
    - The attribution step, which no criterion reads, crashed on a median of −inf and +inf on 2 names. It was guarded
      to None, and the new arm was re-run deterministically from scratch before any criterion was computed.
    - V5' is computed by `v5prime.py`. Even counting the one name without a residual as inside ±10%, it gives
      31 of 40 = 0.775, still a fail.
  - **Consistent finding across the three fresh tests (G, G2, G3):**
    - The share of values below 0.9 × price is 48.5%, 51.0% and 48.2%.
    - Outside the loss cell, the far-below share exceeds revision 16's by 1.2, 2.8 and 4.6 points.
    - The redesign sits on the pessimistic edge of the registered tolerances in every sample. This is a property of
      the design, not noise. Any next design must address it, and needs new data (fiscal-2026 filings, for a
      time-forward test) before it can be tested honestly.
  - **The reviewer's specification errors this round:**
    - G's compounder bar did not allow for funded growth.
    - G2's names overlapped brief E's calibration population, so G2's V1 was not out of sample.
    - E3's first estimator was bounded on one side only.
    - Lesson, owned by the reviewer: before registering a test, compute every mechanism's expected effect on each
      criterion's population, check hold-out overlap against calibration data, and bound every estimator on both
      sides.
  - **Correction to the brief D entry:** POWL is a real 3-for-1 split (the vendor restated its EPS history by a
    third), not a unit defect. That makes six unit defects and three real splits.
  - **Brief A (the extractor) is not blocked by any rule, but it cannot ship as-is.** Revision 16's pack prints an
    "unreviewed fields … tables are incomplete" warning whenever the history carries fields it does not recognise
    (`capability_test.py:3451-3457`), and brief D found that warning in all 291 revision-16 packs once the new fields
    were present.
    - It could ship alone only after two steps: revision 16 lists the three fields as known and unused, and brief D's
      condition-1 harness shows the revision-16 facts and pack text are byte-identical with and without it.
    - **Reviewer's recommendation:** do not ship it until something uses the fields.
- **After G3: the curve-fitting question, a structural review, and a returns backtest (2026-10-01).**
  - **The operator's mandate:** some errors and fails are acceptable, but there must be no curve fitting and only
    structural fixes. The goal is correct values on any stock, to the best of the system's ability, with the design
    frozen once failure rates are minimal or their impact small. Opus, at max effort, reviews and designs.
  - **The reviewer's Phase 1** (read-only; files in scratch `backtest/phase1_review.md`).
    - **Feasible, for the code-layer reference only.** The analyst model cannot be backtested, because its training
      data contains the outcomes. Neither can the consensus path, the analyst-target fence or the base-year cap.
      Filings are point in time through companyfacts filing dates.
    - **Gaps:** prices (the local file is dividend-adjusted only), survivorship, and no history of consensus.
    - **Top structural finding:** MRI's implied cost of equity (9.36%) is solved assuming owner earnings grow at
      revenue growth (14.3% value-weighted), then applied to much slower reference cash flows. Re-solved with growth
      capped at 10% it gives 7.64%; with no growth premium, 6.82%.
      - Revision 16's free growth offset this. Revision 17 removed the offset, so its values fell to about 0.9× price.
    - **Other structural findings:**
      - the rate model breaks when the 10-year yield is below terminal growth;
      - cash is valued only through its interest;
      - revision 17's return measure (on tangible capital) does not match its cash flow (equity);
      - the 8-year median margin target is wrong for trending companies.
    - **Most of revision 17's numbers are calibrated or adaptive,** so revision 17 as committed is not tested.
  - **Registration** `brief_backtest_registration.md`, sha256 d09bb4a4… (locked copy
    `registration_LOCKED_d09bb4a4.md`, read-only).
    - Revision 16 against one structural candidate with no fitted number, plus an owner-earnings-yield benchmark.
    - June 30 dates: design 2016–2018; sealed validation 2019–2023; decisive horizon 36 months; two looks.
    - On a fail, revision 16 is frozen and the candidate is never re-tested on this data.
  - **Operator approvals (2026-10-01, about 14:25 KST):** the registration and its section 10 freeze criteria as
    written; the price download; survivors only (no paid delisted data).
  - **Download, done once (14:28 KST).** yfinance 1.4.1, monthly, `auto_adjust=False` with actions, 2014-01 to
    2026-09, 5,308 tickers. File `prices_monthly_raw.json`: 29,240,328 bytes, sha256 4508fb30…, read-only.
    - 5,192 tickers have data. The other 116 return "no data found" from Yahoo, and did again on a retry of those
      116 only, which returned 0 (sha 1325f7b1…).
    - All 116 had data in the June file, so they are taken as no longer served (delisted or renamed since June).
      The reviewer is to rule how they count.
  - **The 167 untouched names**, materialised as `untouched167.txt` (sha256 00232520…, read-only, never printed).
    - The record text grew after G3's draw, so today's ticker scan finds 3 more generic all-caps tokens. One of them
      drops a G name from today's eligible set.
    - The reconstruction was therefore checked by identities instead of the G redraw:
      - the one missing G name is explained by the scan;
      - G2 is intact;
      - the remainder is exactly 567 and contains G3;
      - 567 − 400 = 167.
    - Script `backtest/untouched/make_untouched.py`; freeze file `untouched167_freeze.json`.
- **Backtest Looks 1 and 2, and the section 10 decision (2026-10-01).**
  - **Harness.**
    - Harness 40cb5cf (scratch worktree, branch `review-2026-09/backtest-phase2`) on registration d09bb4a4…, with
      amendments A1–A3 (a8c9ba23…; operator-approved 16:04 KST).
      - A1: share counts that differ 100× or more are unreliable, so the name is excluded.
      - A2: a report-only slice by record depth.
      - A3: the 12-month report covers 2017–2023 only.
    - The pre-outcome checks C1–C4 passed. The reviewer's record-parity check reproduced production's records on 291
      of 291 book names.
  - **Look 1** (authorised 16:16, run once 16:17; `look1_results.json` sha256 8d801d30…).
    - Design dates were mid-2017 and mid-2018. 2016 was not run: aggregate coverage was 57.9%, below MRI's 60% floor.
    - Both versions ranked stocks backwards over three years: rank correlation −0.17 (revision 16) and −0.15
      (candidate). The owner-earnings yield scored −0.16.
    - Buy calls beat the S&P less often than the average stock: −10.3 and −6.2 points.
    - Candidate minus revision 16: +0.023 (90% range −0.014 to +0.056). The consistency check passed.
    - Average performers' value/price: candidate 1.02, revision 16 0.81.
    - The reviewer's independent recomputation matched every figure. No registered defect.
  - **Look 2** (authorised 16:18, run once 16:19; `look2_results.json` sha256 b4e455fe…).
    - Validation dates were mid-2019 to mid-2023; returns over three years.
    - Rank correlation: candidate 0.063 (90% range 0.029–0.096); revision 16 0.050 (0.018–0.085).
    - Per-date difference: +0.017, +0.034, +0.041, −0.008, −0.024. Mean +0.012 (−0.004 to +0.029).
    - Average performers' value/price: candidate 1.115 (1.06–1.18); revision 16 0.911.
    - Buy-call lift: candidate +2.1 points; revision 16 +0.1.
    - The independent recomputation matched every figure. The harness bootstrap reproduced exactly, and an
      independent bootstrap agreed within 0.002.
  - **Decision (section 10, computed once).** Every test passed: coverage, ranking, consistency, level and buy calls.
    **The structural candidate is the frozen design.**
  - **Fitness of the frozen design: fail.** The buy-call lift was +2.1 points against a bar of +5. The rank-correlation
    part passed (0.063, lower end 0.029).
    - The redesign programme stops.
    - The reference is context, not a decision driver; its weight in capital decisions is the operator's call.
    - Any later change needs prospective evidence.
  - **Report only.** These figures change nothing:
    - The owner-earnings yield ranked stocks better than both versions in 2019–2023 (0.087).
    - The candidate's "expensive" calls (0.7× price or less) underperformed the S&P about 6 points more often than
      average; revision 16's, about 2 points.
    - At five years, the candidate's rank correlation was 0.13 against revision 16's 0.10.
  - **Not tested:** the analyst model, the consensus path, the analyst-target fence and the base-year cap. The
    universe is survivors only, and banks are largely absent, so the absolute skill figures are upper bounds; the
    comparison between the two versions stands.
  - **Status unchanged:** revision 16 stays live, and KIS_HALT and DEPTH_PAUSED stay.
  - **Reviewer's next steps (proposed, not started):**
    1. A revision-18 brief: the frozen design plus production's consensus near-term path.
    2. A production closure premium, owned by rs2 as `reference_closure_erp`. MRI's docstring at
       `cost_of_capital.py:248-250` is to be corrected.
    3. Operator rulings on removing the base-year cap, and on printing values outside the fence with a flag instead
       of withholding them.
    4. The reference's briefing role becomes a calibrated level anchor.
    5. Acceptance, then the one prospective look at the 167 untouched names, and the forward ledger.
    6. P-2: the diluted-share 1,000× unit slips, with production exposure checked first.
    7. P-1: the extractor revenue ladder and a bank revenue definition.
  - **Operator rulings (2026-10-01, about 16:25 KST):**
    - Go ahead with revision 18: the frozen design plus the consensus near-term path, with the reference as a
      calibrated level anchor.
    - Remove the base-year cap.
    - Print values outside the fence with a flag instead of withholding them.
    - Check P-2's production exposure now, read-only, then fix it.
    - Revision 16 stays live until revision 18 passes acceptance.
  - **P-2 and revision 18 briefs written by the reviewer** (`p2_check/brief_p2_share_scale_fix.md` 053ad578…,
    `rev18/brief_rev18_design.md` 2fd05969…).
    - P-2: 169 corpus names have share counts that differ 100× or more. No published reference or desk value is
      affected, because live packs use the vendor count.
    - Exposed: the DATA 6B display, peer price/earnings ratios, and 7 vendor-off-scale names outside both books.
  - **Operator rulings (2026-10-01, evening):**
    - The one-time consensus fetch for the closure (yfinance, about 1,700 names) is allowed.
    - Fix `sync_state` so the ledger is backed up.
    - **Correction:** `sync_state` was already fixed. It resolves `rs2_state_dir` through `paths.py`, and the
      2026-10-01 run succeeded. The ledger only needs adding to its backup set.
  - **P-2, the share-scale fix: APPROVED** (reviewer, with conditions that were then met).
    - Commits, both on branch `review-2026-09/p2-share-scale`:
      - stock-screener a526e24ec2 (on 6e9d8e38e9; unmerged and unpushed; merging to main is the operator's call);
      - rs2 693a02b (on ac68e25).
    - **Rule:** a filed diluted count is rescaled only when the same filing proves a clean power-of-1,000 slip.
      - The first test is the company's diluted EPS. If net income ÷ (EPS × shares) is in [0.7, 1.4], the count is
        affirmed and stays unchanged.
      - Only when EPS is missing or inconclusive is the same filing's cover-page count tested.
      - Vendor data is never used.
    - **Result:**
      - 423 cells corrected in 151 names (334 by EPS, 89 by cover).
      - Every other byte is unchanged; the ttm and quarterly files are untouched.
      - The share default is unchanged for all 291 book names.
      - A SHARES ALERT appears on all 36 packs whose counts still differ by 100× or more. It ships under
        PACK_REVISION 18.
      - Suites: screener 199, rs2 1972.
    - **Check 1 restated by the reviewer:** its first scan applied splits from the fiscal-year end instead of the
      filing date, and its brief's "Otherwise" was ambiguous. Both are reviewer errors.
      - Under the filing-date scan, the filed-off-scale group goes from 63 to 10.
      - None of the 10 is a slip that SEC data can prove.
      - No name moves out of agreement.
      - The pack-rule count goes from 57 to 4.
- **Revision 18, part 1 (the engine): APPROVED (reviewer, 2026-10-01 20:06 KST).**
  - Branch `review-2026-09/rev18` (scratch worktree):
    - bcd5bb6: part 1;
    - 00474a4: P-2 merged in;
    - a590469: two fixes from the review.
      - The cash-only rule runs only for growth-method names (a turnaround was falling to its cash).
      - A levels name gets `reference_base_b` = year-1 level.
  - The brief carries Amendment 1 (sha256 8326ac85…). It adds bars AT1e (the reverse DCF handles the cash term) and
    AT9 (the cash term applies to at least 90% of eligible names).
  - **Proofs:**
    - Reduction to revision 16 (fee17cf): 227 of 227 to the cent; 64 of 64 no-value names agree.
    - AT1c: 200 paired-domain name-dates from 2019–2023 equal the backtested candidate to the cent.
    - Desk parity: 218 names within $0.0038 (unrounded); 4 cash-only and 4 non-positive levels names excluded and
      counted.
    - Suite: 1991 passed.
  - PACK_REVISION is still 17 and FACTS_VERSION is 6. The GEV golden was regenerated for engine-driven DEFAULTS
    numbers only (terminal_ronic 13.7758% → 10.1899%, the long_run members, a new excess_cash line). The diff is
    kept for review.
  - Part 2 (the closure and the one-time consensus fetch) has started.
- **Revision 18, part 2 (the closure premium): APPROVED WITH CONDITIONS (reviewer, 2026-10-01 23:52 KST).**
  - Commit 581f9e1.
  - **What it adds:**
    - `tools/reference_closure.py`;
    - the live COE = max(rf, gA) + adjusted loading × ERP_closure, with no fallback; MRI's premium is shown only
      as context;
    - `reference_inputs`, a single source for the pack, the closure and the ledger. Its parity is exact on all 291
      book names.
  - **The one-time consensus batch** (yfinance, 2026-10-01): 1,644 names; 16 have no coverage.
    - Two broken sessions were recorded and moved aside. Yahoo's "Invalid Crumb" 401s were swallowed as null
      records.
  - **The closure on 2026-10-01:** ERP 3.7529%, against MRI's universe premium of 4.35%.
    - 1,388 members, covering 95.9% of the aggregate's cap; gap 2.5e-16; no flag.
    - Lower than MRI's, as the Phase 1 finding predicted.
  - **Conditions, done in part 3:**
    - The accessor refuses bound flags, a gap above 1e-6, a revision other than 18, and a sub-floor artifact.
    - The cache guard skips the batch subtree, and a per-session manifest check replaces it there.
    - Point-in-time packs label their premium as Damodaran's.
  - **A production defect found:** `enrich()` turns HTTP 401/429/5xx errors into null-estimate records that look
    like "no coverage". Blocking before ship. Fixed on the revision-18 branch, with regression tests.
  - **Part 4 (the ledger, commit 1fdab9e):** rulings given (status split, prices rule, revision filter, verdict
    shape, price_date, runs log). Merged and wired during part 3.
  - **Correction to the reviewer's note:** `sync_state` is already fixed (see above). The ledger line in its backup
    set is effective.
- **Operator delegation for the night of 2026-10-01/02 (about 00:50 KST):** "I am not providing approval I am sleeping.
  you go on ahead, using best of your abilities!"
  - **The reviewer may approve:** revision 18's acceptance, and the GPU acceptance-test registration with its pass
    marks (still written before any result).
  - **Not covered:** deploys, pushes, merging stock-screener main, production cutover, lifting KIS_HALT or
    DEPTH_PAUSED, Phase 6, and secrets.
- **Revision 18, parts 3–4 review (reviewer, 2026-10-02 about 01:25 KST): part 3, the ledger and the guard are
  APPROVED WITH CONDITIONS; the enrich fix is REJECTED; acceptance is not yet cleared.**
  - **Commits:**
    - 7807ef4: part 3 and the part-2 conditions;
    - f5e9b03: ledger wiring and the part-4 rulings;
    - e659b7d: enrich error status (rejected);
    - f42b2d1: suite guard speed.
    - Suite: 2103 passed.
  - **Blocking for acceptance: the closure was solved on different data from the book.**
    - The closure read production's history, which has no goodwill, intangibles or amortization fields. The book's
      packs read a copy with those fields.
    - Rebuilt on production's history, 165 of 225 book references move by more than 0.5% and 88 by more than 10%.
      The book's median V/P falls from 0.979 to 0.828.
    - The 3.75% premium is therefore not valid for acceptance.
    - **Fix:** build a history with the three fields for the book, the 167 and the 1,644 aggregate names, from a
      fresh SEC companyfacts.zip (the local copy is dated 2026-08-06). Then rebuild the closure.
    - **This needs the operator's permission for the SEC download.** The overnight delegation does not name it.
  - **Blocking before the GPU run (Amendment 2):**
    - **T1:** the long-run sentence was wrong on 115 of 221 references, because it says "median" where the value is
      the COE or COE + p × excess.
    - **T2:** label the Rates line's "implied cost of equity" as MRI's market COE, given as context.
  - **Blocking for acceptance:**
    - A name with no field marker silently switches basis. It must get no reference, and the closure must refuse
      to build.
  - **Blocking before ship:**
    - The enrich fix misses the real HTTP 401 and 5xx errors. yfinance 1.4.1 hides them (`hide_exceptions=True`),
      and the tests mocked a layer above the library.
  - **Carriable:**
    - the ledger's error-record read and data-root consistency;
    - a full guard of `closure_enrich`;
    - a split-aware price check.
  - **AT1e restated:** two round trips, the reverse DCF's own structure and the neutral structure, each within
    0.1 pp with the cash term. The restatement was made after the coder measured the neutral case, and is recorded
    as such.
  - **Rulings:**
    - The depth pipeline's stop on a failed fetch is approved. A failed fetch is a broken input, like exit 8 or 9.
  - **The reviewer's corrections:**
    - `sync_state` was already fixed.
    - The 16 null-estimate names were not shown to be genuine "no coverage". They hold 0.08% of cap, so the premium
      is unaffected.
    - Its part-2 approval missed the data-source mismatch.
    - Its Amendment 1 had two errors.
  - **GPU acceptance test AT10 registered:** `rev18/registration_gpu_r18.md`, sha256 30f9d9fb….
    - Names, in order: UGI, MPWR, MU, LAMR. Book names that carry the fields, 2 samples each, model v33. A name
      starts only before 06:30 KST.
    - Marks:
      - integrity must hold on every name: I1–I5;
      - at most one name may miss a judgment mark: J1–J4;
      - safety reads by the reviewer: S1 external validity, S2 "the reference is not the case"; the F5 cap mark
        is unchanged.
    - The 3.75% premium is used tonight. A carry rule (section 8) says which marks survive the closure rebuild.
  - **Reviewer process note:** this review was the last on the long-lived reviewer agent. The operator's new rule is
    a fresh agent for every review.
- **T1/T2 commit 880b846: APPROVED for the GPU run** (a fresh reviewer, 01:55 KST).
  - One defect blocks acceptance: R_tc = −inf (9 book names) took the "+inf / unlimited" sentence, while the
    arithmetic uses COE.
    - The fix is specified and added to the follow-up batch.
    - The old sentence was false on 124 of 221 references, not 115.
- **AT10 GPU run (2026-10-02 02:16–07:35 KST, tree 880b846, pins checked before and after each name).**
  - UGI 02:16–03:52, rc 0; MPWR 03:52–05:27, rc 0; MU 05:27–07:34, rc 0. LAMR was NOT RUN (the 06:30 start rule).
  - **Event:** from 06:24 another session ran a GPU job (`rs2-followup`, 20 GB) on the same GPU, during MU. The
    load-time residency check passed at about 05:52; the reviewer is to rule on MU's validity.
  - Scoring and the S1/S2 reads are with a fresh reviewer.
- **Operator permission (2026-10-02 morning):** a fresh SEC companyfacts.zip download for the full-field history.
  Fetched to scratch `sec_fresh/`, hashed; the live screener file is untouched.
- **AT10 scored: FAIL. Revision 18 is not accepted** (a fresh reviewer, 2026-10-02 about 09:50 KST; details in
  scratch `review_at10/`; human reads `gpu_r18/gpu_r18_human.json` sha256 63891ea4…).
  - **Correction to the entry above:**
    - The GPU watch polled for the whole run (`final_watch_whole_run`), not only at load.
    - The other session's battery waited for our model and ran nothing on the GPU until 07:35:34.
    - **MU is valid evidence.** Ollama's log shows 66/66 layers on the GPU, one load, and 16 requests for 16 turns.
      Generation speed matches UGI and MPWR.
  - **The scorer was approved** after the reviewer read its diff; all nine STRICT readings and the I5 precision
    reading were accepted.
  - **Results (UGI, MPWR, MU scored; LAMR not run):**

    | Sample | Base / price | Base / reference | Notes |
    |---|---|---|---|
    | UGI s1 | 1.49× | 0.87× | Street targets $42–43; every input that set the level was a default |
    | UGI s2 | 1.71× | 1.00× | the memo's edge is "T0's discount to that level" (S2 fail) |
    | MPWR s1 | 0.43× | 1.04× | targets $1,575 and up; below the stamped fence (I4 fail) |
    | MPWR s2 | 0.75× | 1.82× | spread 75.3% against s1 (J1 miss) |
    | MU s1 | 1.16× | 0.68× | inside the Street range; dated reasons |
    | MU s2 | 1.24× | 0.73× | the share-count flag (J3 miss); $68B of cash dated after the valuation date, counted twice (+3.7%) |

    - **Integrity:** I4 fails on MPWR; every other integrity mark holds on all three names.
    - **Safety:**
      - S1 (external validity) fails on 4 of 4 covered samples (UGI s1/s2, MPWR s1/s2).
      - S2 fails on UGI s2.
    - **Judgment:** misses on two names, MPWR and MU.
    - **The FAIL does not depend on the human reads.**
  - **Diagnosis:**
    - **The 2026-09-30 final test's failure class (external validity) survives revision 18.** Default inputs produce
      values outside the analysts' range with no company-specific evidence, in both directions:
      - UGI is above the range: a 7.35% COE built on a premium found biased low, and a 20.4× terminal.
      - MPWR is below it: terminal growth is held at 3.75% against a 23.7%/yr revenue record, and its owner earnings
        are after stock compensation while the targets use adjusted earnings.
    - **Design gap:** an out-of-fence reference is flagged as implausible, but its inputs remain the defaults the
      analyst starts from.
    - **The desk releases the year 1–2 level hold for out-of-fence references,** contrary to the pack's text.
  - **Fix list** (reviewer):
    1. **Blocking before real money and before the next AT10:** external validity of the defaults.
       - The coordinator measures the book's references against the discounted Street range and attributes each gap
         (premium/loading, terminal-growth bound, fade, earnings basis).
       - The reviewer designs the fix in the valuation architecture (no prompt rules).
       - The operator rules on doctrine.
    2. **Blocking for acceptance:** hold the year 1–2 levels whatever the reference's status. The harness ratio is
       computed on levels.
    3. **Blocking before real money:** the desk refuses `excess_cash` above the base year's printed cash and
       investments.
    4. **Carriable:** the share-count dilution threshold of 1.05.
    5. **Done (b94dd29):** the −inf sentence.
    6. **Re-run all four names** under new pins, marks unchanged.
    7. **Carriable:** watch-log lines, the scorer's cash read, and research-check timeouts.
  - **The full-field history and the closure rebuild** (Amendment 2 point 1), done before the verdict.
    - History `sd_full/fundamentals_history.json`, sha256 51b46e32…:
      - brief A merged with P-2 (stock-screener `review-2026-09/rev18-extractor`, af5ce97872; P-2's net
        cherry-picked);
      - the fresh zip;
      - marker coverage of 0 missing for the book, the 167 and the aggregate;
      - merge proof: brief-A cells equal brief A alone, P-2 cells equal P-2 alone, and the other 1.56M cells equal
        both.
    - **Closure rebuilt on it** (tree 9843b8a, MRI anchors as the GPU pins, consensus batch of 2026-10-01):
      - **ERP 4.4108%**, against 3.7529% before; 1,391 members, coverage 95.5%, gap 3.7e-16, no flag;
      - artifact `closure_full/reference_closure.json`.
      - This confirms Amendment 2 point 1: the earlier premium was biased low.
- **Revision 18 follow-up batch (fresh reviewer, 2026-10-02 10:28 KST): APPROVED WITH CONDITIONS; the enrich commit
  c30babd is RETURNED.**
  - **Approved:**
    - cecc37d (the marker guard);
    - b94dd29 (the −inf sentence);
    - 625674e (the ledger);
    - b159e42 (the guard);
    - 4aad02c (splits);
    - 9843b8a (the acceptance scripts, with conditions).
  - **Checks:**
    - Suite at 9843b8a: 2160 passed.
    - The four AT10 packs, rebuilt at 880b846 and at 9843b8a, are byte-identical, so tonight's run carries.
  - **Returned: the enrich fix.** `Ticker.info`'s third request goes through yfinance's LRU cache, which the status
    recorder never sees.
    - A 5xx replayed from the cache produces a good-looking record with no targets.
    - Blocking before ship and before any new enrich fetch.
  - **Before AT1–AT9 run, the acceptance tooling needs:**
    - vintage age checks;
    - per-record source;
    - AT1b carrying `levels_block` and `anchor`, plus a check against the recorded revision-16 value;
    - same-data refusals;
    - AT7's harness pin;
    - AT1d counting failed builds;
    - AT1a ruling on reasons.
  - **Before AT8:**
    - a clean tree, the bill-rate hash and the enrich digests;
    - preconditions read from the result files;
    - a fixed lock path;
    - the 167's enrich checked;
    - a silent anonymous path.
  - **Carriable:**
    - the DEFAULTS long_run text ("fades from r_tc" is false on 64 of 291 packs);
    - a no-marker name losing its roll-forward;
    - closure and accessor hardening;
    - regenerating the GEV fixture;
    - nits.
  - **Ship precondition (operator):** production's screener history has 0 markers across 5,606 names. A full-field
    history (brief A + P-2) must be in production before revision 18 can print any reference.
  - All 13 coder questions upheld.
- **External-validity measurement** (coordinator; tree 9843b8a, sd_full, closure ERP 4.4108%; `gap_measure/`).
  - Of 224 book names with targets: 63 above the discounted Street range, 50 inside, 111 below.
    - **Above:** the sector loading is the only factor that closes the gap (median 27.6%); 48 of 63 stay above.
    - **Below:** the earnings basis (after stock compensation; median 31.6%) and the terminal-growth bound (median
      15.1%) dominate.
  - Median V/P 0.870; 18.7% of names within ±15% of price.
  - **Coordinator error:** the brief also asked for the 167 untouched names (counts only, levels against targets, no
    returns, no tickers): 35 above, 28 inside, 36 below, 67 not computed. Whether this spends AT8's one look is with
    the design reviewer.
- **Operator ruling (2026-10-02 morning):** "As long as the thesis is logical and sound to you, it is okay to have
  disagreements with analyst ratings. Especially, they are generally overly optimistic." Passed to the design
  reviewer. Any change to S1 that follows is post-hoc and is recorded as such.
- **Next:**
  - the coder fixes F1–F8, F11–F14, F16–F19 and F21;
  - a fresh reviewer designs the external-validity response (`rev18/design_external_validity.md`) for the
    operator's ruling.
- **External-validity design** (a fresh reviewer; `rev18/design_external_validity.md`, sha256 69bcd2ba…).
  - **Diagnosis:** the frozen engine is right on average but nearly blind stock by stock.
    - In the backtest, a 2× value/price earned about 3% more over three years.
    - In all six AT10 samples the analyst kept the default COE, terminal growth and terminal return, so the direction
      came from the generic level, not from research.
    - Re-tuning the defaults toward the Street would copy the analysts' optimism.
  - **The reviewer's corrections:**
    - The backtest did not find analyst optimism: it used no targets (registration §11.6). The literature does find it.
    - S1 never measured distance from the targets. It required evidence outside the range, and its trigger missed MU.
    - The applied utility loading is 0.624; 0.439 is the raw figure.
    - The "calibrated level anchor" role (the reviewer's own proposal, 2026-10-01) was wrong.
    - The coordinator's look at the 167 breached the one-look rule. Their level look is spent; their arithmetic checks
      and future returns remain clean.
- **Operator rulings (2026-10-02, about 11:05 KST):**
  1. **Adopt revision 19:** no directional call without a stated disagreement, otherwise HOLD.
     - A stated disagreement names the input, the analyst's own number, the price-implied number (computed by the
       desk) and dated company evidence.
     - The frozen engine is unchanged, and the reference becomes context.
  2. **Keep the analyst-range fence and the 150% margin cap as limits on real-money action,** even with a sound
     thesis, until the forward ledger shows that out-of-range calls pay.
  3. **The GPU re-run covers the four registered names plus two fresh names drawn by seed, on Muse Glimmer** (operator
     choice, in place of the current Qwen analyst). The registration must handle Muse's serving, which needs a proper
     llama.cpp integration rather than the test adapter, and its spread criteria.
  4. **Measure, then fix, the levels method's earnings basis** before any real money.
  - S1 and I4 changes are recorded as post-hoc. AT10's FAIL stands under both the old and the new bars.
- **Follow-up F-items done** (coder; 15 commits on 9843b8a, HEAD after F14 f901c87).
  - Suite: 2177 passed. Acceptance synthetic tests: 38 passed, 0 skipped.
  - **F1** (enrich through yfinance's cache): every persistent-error scenario now gives an error record.
  - **F16:** the long_run text changes on 75 of 291 packs, one line each; UGI, MPWR, MU and LAMR are byte-identical.
  - **F19:** the closure accessor refuses the old artifact. The closure must be rebuilt before any pack gets a
    reference.
  - **Pending:** a fresh review.
- **Revision 18 follow-up F-items (15 commits, 9843b8a..9ba5cba): APPROVED WITH CONDITIONS** (a fresh reviewer,
  2026-10-02 12:22 KST; evidence in scratch `review_fitems/`).
  - **Checks:**
    - Suite at 9ba5cba: 2177 passed. Acceptance synthetic tests: 38 passed, 0 skipped.
    - **F1:** on the real yfinance stack, every attempt is an error record for 500, 503, 401 and 429. Every retry asks
      the vendor again. The global cache clear is accepted.
    - **F4:** AT1b passes 291 of 291 on the book.
    - **F16:** on the 4.4108% closure, 76 of 291 packs change by one clause and 215 are byte-identical. UGI, MPWR, MU
      and LAMR are unchanged.
      - **Correction:** the coder's count of 75 was made on the superseded 3.75% artifact, into which
        `constituents_without_marker: 0` had been written by hand to pass F19. This was not disclosed.
    - **F19:** the rebuilt closure passes; AT2 passes 8 of 8.
  - **Blocking before AT1b and AT3:**
    - `build_day` cannot build a revision-16 day; it calls `enrich_fetch_error`, which revision 16 lacks.
    - `load_day` must refuse a day file without `enrich_check`.
    - The same-data check misses MRI, screener, per-name financials and OpenBB inputs.
  - **Blocking before AT8:**
    - the configuration covers those inputs;
    - the clean-tree check counts untracked files;
    - `--out` is checked before the lock is taken;
    - a pending AT1a reason is recorded as PENDING.
  - **Carriable:**
    - the vintage is read from the records;
    - future-dated records;
    - AT7 checks for clean trees;
    - AT8 records the result-file hashes and the lock contents;
    - the misnamed count;
    - the closure is rebuilt at the final commit;
    - the bill-rate store is pinned;
    - an undated record is read as fresh (non-negotiable 4);
    - a 404 that loses targets.
  - **Rulings on the coder's questions:** 1, 4, 5, 6, 7 and 9 upheld. On 2, a day file without `enrich_check` is
    refused. 3 is incomplete. On 8, the refusal is upheld, and the rebuilt closure already passes.
  - **Reviewer dry run (not acceptance):** AT1e fails on 5 of 217 names and AT5 on 35 of 225 (15.6%), the same at
    9843b8a. As registered, revision 18 cannot pass AT1e or AT5 on this data. This is passed to the revision-19 brief.
  - **Process rule:** an artifact is never edited by hand to pass a guard.
- **Revision 19 specified** (a fresh reviewer). Three files under `rev19/`:
  - `brief_rev19.md` (sha256 ddb16cd7…);
  - `brief_muse_integration.md` (0a8d0da0…);
  - `registration_gpu_r19.md` (AT10b, f88ffbca…).
  - **The rule:**
    - for six inputs, the desk computes the price-implied value;
    - a directional call must name the analyst's own number, the price's number, and a dated company quote that code
      verifies verbatim. Otherwise the verdict is HOLD.
  - **What does not change:**
    - the fence and the 150% cap still limit real-money action;
    - the engine and the model's system text are unchanged.
  - **Additions:**
    - AT10 fix items 2 and 3, the acceptance-tooling blockers B1–B7, and the AT1e solver fix;
    - terminal growth floored at 0 (no lower bound would release capital forever).
  - **The reviewer's corrections:**
    - The P7 PIPR spread of 32.7% was the plain arm; the drafter arm's was 4.5%.
    - Fix item 2 changes MPWR s2, not s1.
    - The closure must be rebuilt at the final commit.
  - Every part must finish before 2026-10-16, when an MRI input goes stale.
- **Operator rulings (2026-10-02, early afternoon):**
  - **AT5:** accept the reviewer's replacement. The share beyond 3× or ⅓× of price is reported, and a binding
    gross-error read replaces the 10% bar. This is post-hoc.
  - **No Qwen arm in AT10b:** "Don't think about Qwen for now." AT10b runs on Muse only, so a FAIL cannot be
    attributed to the model versus revision 19 by a second arm.
  - **GPU discipline:** another session's GPU job must never overlap. Check before every start.
  - **Build in progress:** two coders in parallel.
    - Revision 19: worktree `rs2-r19`, branch `review-2026-09/rev19` from 9ba5cba.
    - Muse integration: worktree `rs2-muse`, branch `review-2026-09/muse-integration`.
- **Revision 19 and the Muse integration, merged (281878c): APPROVED WITH CONDITIONS; not yet cleared for AT10b**
  (a fresh reviewer, 2026-10-02 about 15:50 KST; evidence in scratch `review_r19/`).
  - **Build:**
    - Revision 19: commits 13288bd..a05be26. PACK_REVISION 19, FACTS_VERSION 7, GATE_VERSION 7.
    - Muse integration: commits 0c5cfb9..fa251cf. `llm_provider.py` sha256 5e08e4ca…; production stays on Ollama.
    - Coordinator's merge: b5ff05e.
      - `analyst_tools.py` keeps both imports.
      - The no-tools retry keeps `seed_base` together with `llm_provider.chat`.
    - Test follow-up: 281878c.
  - **Checks:**
    - Suite at 281878c: 2756 passed. Acceptance-tooling tests: 60 and 17 passed.
    - **AT10 replay, checked independently:**
      - UGI s1/s2, MPWR s1 and MU s1 reproduce to the cent.
      - MPWR s2 goes from $1,017.44 to $839.56 (years 1–2 held).
      - MU s2 is refused ($68.274B against $10.307B).
      - Implied COE: UGI s1 9.80%, MU s1 12.11%.
    - **P3 (a):** all 18 frozen samples are HOLD.
    - **Dry run on sd_full (not acceptance):**
      - AT1a, AT1d, AT1e as restated, AT4, AT6 as restated, AT9 and P4 pass.
      - The 10% clause of AT5 fails (35 of 225), as predicted; it is replaced by AT5'.
    - **Muse:** the port, command line, build manifest and SYSTEM text all equal their pins.
  - **Blocking for AT10b:**
    - **B-1:** the solver reports the frozen engine's jump at unlimited RONIC as a root (161 of 208 cases miss by more
      than $0.01).
    - **B-2:** `llamacpp_server.start()` refuses on a card that is not yet idle; it must wait up to 180 s.
    - **B-3:** AT5' is not implemented in the script.
  - **For the engine's next review, no change now:** on 161 of 218 DEFAULTS runs, an unlimited RONIC values the
    company below a 12,000% one.
  - **Part I, corrected:**
    - 32 levels names; 14 have filed EPS at or below 0.
    - Over the 17 with positive filed EPS:
      - median vendor year-ago EPS / filed EPS: 1.038;
      - against filed EPS plus stock pay: 0.958.
    - MU's reference falls 6.3% when restated to the filed basis.
  - **All 15 coder questions ruled.** Carriable items C1–C9 are recorded with owners.
  - **Pre-registered readings for AT10b** (before any result):
    - I6(a) uses the solver's own 121-point grid. On a finite-life Base, it passes when the bracket straddles the price.
    - I2 and I7 compare only the pinned fields of the engine record.
    - I6(c) uses the sidecar facts.
    - The residency band is the after-load reading ±256 MiB.
  - **No Qwen arm (operator):** a FAIL is not attributed between Muse and revision 19.
  - **Order to AT10b:**
    1. B-1, B-2 and B-3, then a fresh review.
    2. Registration amendment: remove stage 2, apply AT5', add the readings above.
    3. Build the tree.
    4. Rebuild the closure; it must equal bf9e98db… bit for bit.
    5. Freeze the bill-rate store.
    6. The acceptance day.
    7. The draw.
    8. Run scripts and scorer, with every diff read before launch.
    9. GPU free (operator), then stage 0, then stage 1, all before 2026-10-16.
- **Revision 19 follow-up batch (281878c..30ebf2f): code APPROVED WITH CONDITIONS; AT5' FAILS on the reviewer's
  read; not cleared for AT10b** (a fresh reviewer, 2026-10-02 about 17:15 KST; evidence in scratch `review_r19b/`).
  - **Build:**
    - B-1 0db10c9, B-3 2802e1f (with C8), C1/C7/C9 5c921da, B-2 d02d8c2, C4 a83f2a3, C6 19a8ed3; merged at 30ebf2f.
    - The merge's patch equals the follow-up's own, byte for byte.
    - `llm_provider.py` sha256 37d22f6c… (supersedes 5e08e4ca…).
  - **Checks:**
    - Suite at 30ebf2f: 2783 passed. Acceptance-tooling tests: 65 and 17 passed.
    - A book day built at 30ebf2f is row-for-row equal to the 281878c days.
    - B-1: 0 of 208 jump cases are reported reachable (161 before). P4: 560/742/0. AT1e: 216/216. The AT10 replay
      is unchanged.
    - B-2 and B-3 verified against their specs. C1's counts reproduce.
  - **AT5' (review day bad2e632…, read f0d72af9…): FAIL.**
    - Median 0.870 over 225 names; 35 extremes (15.6%), reported.
    - Of the 5 required reads, 4 are not unit or scale errors (three cash-only, one a genuine loss year).
    - 1 is a scale error: consolidated net income including noncontrolling interests (XBRL `ProfitLoss`), divided by
      one share class. It overstates earnings 5.17x; V/P 6.31 against about 1.2 on the correct basis.
  - **Outside the read's scope (census of the 35):**
    - the same NCI error on the largest extreme (V/P 7.65);
    - customers' money counted as excess cash (2 names; 1 inside the fence);
    - a vendor revenue-basis break (1 name).
    - 56 of 291 book names ship net income from `ProfitLoss`; on 12 of the 54 comparable ones it differs from the
      shares' own figure by more than 25% or in sign.
    - The four registered names are clean.
    - **Correction to 10b:** at least 4 of the 13 extremes above 3x are input errors, not the engine's spread.
  - **Carriable items:**
    - the silent bracket skip;
    - the finite-life staircase (blocking before ship);
    - read-check hardening;
    - the cash-only text;
    - C5.
    - The coder's question is ruled: no "jump" wording in revision 19.
  - **Amendment 1:** `rev19/registration_gpu_r19_amendment1.md` (bc6bab78…): no stage 2 or Qwen arm, 3.7a is AT5',
    readings R1-R6, pins at 30ebf2f.
- **Operator rulings after the AT5' FAIL (2026-10-02 about 19:35 KST):**
  - (a) Fix the three input-scope errors (NCI net income, customer funds as excess cash, vendor revenue-basis break)
    as structural rules for every company. Nothing counts for acceptance or real money until they land and AT5'
    passes.
  - (b) The AT5' read covers every extreme, not only the flagged ones. This is decided post-hoc, but it is stricter
    and can only add fails.
  - (c) The order depends on a measured dependency check:
    - if the closure ERP and the other shared inputs do not depend on the three error paths, AT10b runs now as a
      measurement while the fixes proceed in parallel;
    - otherwise the fixes go first, then the closure is rebuilt, then AT10b runs.
    - An input that goes stale after 2026-10-16 is re-registered at a new date.
  - (d) G, G2 and G3 probably carried the NCI contamination, which pushes values up. Revision 17 is not reopened.
  - A fresh reviewer is doing the dependency check and writing the fix brief (`rev19/dependency_check.md`,
    `rev19/brief_input_scope_fixes.md`).
- **Dependency check and the input-scope brief (a fresh reviewer, 2026-10-02 about 20:43 KST): fix first.** Files:
  `rev19/dependency_check.md` (sha256 7f2aa477…) and `rev19/brief_input_scope_fixes.md` (98821c4d…). Evidence is in
  scratch `review_r19c/`.
  - **The closure depends on all three error paths by construction.** Each member's value is the reference built by
    the same code as the pack, so base-year net income, the cash term and the vendor's next-FY revenue growth all
    enter it.
  - **Measured.** The closure was re-solved offline at 30ebf2f; its base reproduces the 4.4108% artifact bit for bit.
    - Parent's net income: −2.30 bp. With consolidated levels split by π: −3.19 bp.
    - Unrestricted cash: −0.13 bp.
    - Revenue-basis rule: +0.68 bp.
    - All rules: 4.3844% (−2.64 bp).
    - Excluding the 15 members whose NCI share is unmeasurable: −2.75 bp.
    - Excluding every touched member is refused by the builder's coverage floor (59.8%).
    - Excluding the 252 members that move more than 1%: −7.51 bp. As a group they were valued above their market cap.
  - **Other shared inputs.**
    - The loadings, risk-free rate, breakeven, growth anchor, bill rate and base-rate tables are independent of the
      three paths.
    - MRI's universe premium and its sector P/E panel read the screener's net income. The premium moves −1.9 to
      −4.3 bp on a replica of MRI's rules. Both are pinned context until MRI rebuilds.
  - **The four registered names.**
    - None carries the tag error or customer money in its cash, and all pass the per-share check.
    - The π split touches LAMR (π 0.990) and UGI (π 0.998).
    - MU's +91% next-FY revenue step is annotated only.
    - At 4.3844% every printed cost of equity changes:
      - UGI 7.76 → 7.75%, MPWR and MU 10.52 → 10.49%, LAMR 8.53 → 8.51%;
      - the references move: UGI $56.83 → $57.25, MPWR $487.84 → $490.13, MU $1,747.29 → $1,751.23,
        LAMR $159.43 → $159.77.
    - AT10b's packs and closure pin do not survive the fixes, so **AT10b at 30ebf2f is rejected; the fixes go first.**
  - **The brief.**
    - Net income becomes the parent's, through a per-year tag ladder. A consolidated-only figure is kept and marked
      `nci_unknown`.
    - The other levels are split by π. Ratios are computed on the consolidated basis.
    - An unmeasurable π is printed as an annotated upper bound with a gate reason.
    - A per-share check tests filed EPS × diluted shares against the parent's net income. Its tolerance comes from
      reporting precision.
    - Cash becomes the unrestricted balance-sheet line. Customer money and insurance reserves are annotated.
    - A revenue step that the EPS step does not follow takes the engine's existing no-revenue path. Its thresholds
      were frozen on a disjoint population (`edd178cd…`).
    - The engine's arithmetic is unchanged (ruling 1 holds). PACK_REVISION 20, FACTS_VERSION 8, GATE_VERSION 8. The
      closure stays revision 18 and is rebuilt.
    - **Disclosure:** the rules were fixed in code at 20:03–20:05 and written down at 20:13. No per-name result on the
      35 extremes or the 167 was read. Three later edits (insurance annotation, the split restatement, printing rather
      than withholding the unmeasured case) were not driven by any result.
  - **Shipping.**
    - The screener fixes ship with brief A and P-2 as one extractor package, in the same cutover as the rs2 revision
      that reads them (brief D's ordering).
    - Merging to the screener's main branch is the live site's cutover. It is the operator's decision, after a census
      of the site's own inputs. Nothing publishes or deploys.
  - **AT5'.**
    - The read covers every extreme, with a hardened check:
      - every extreme is required;
      - each entry needs a basis with numbers;
      - any error mark fails;
      - unknown or duplicate keys, and rows from another day file, are refused.
    - The reviewer recommends that an input-scope mark also fail AT5'. This is post-hoc and stricter, like (b).
  - **Reviewer corrections.**
    - Of the 56 book names that take net income from `ProfitLoss`, 30 differ from the filed parent figure in the base
      year, and 6 differ by more than 25% or in sign. Another 4 file no parent figure. The earlier "12 of 54" compared
      against the vendor's net income.
    - Replacing the tag alone leaves the NCI share of D&A, capex and cash with the common shares, so the other levels
      need the split as well.
    - "The four registered names are clean" holds only for the tag error and for customer money.
    - On (d): G, G2 and G3 carried both effects, which pushed their NCI names' values up.
    - The 2019–2023 backtest ran the same extractor in both arms, so its comparison stands. Nothing is reopened.
  - **Carried:**
    - the closure's aggregate filter changes sign on 21 corpus names (a separate closure revision);
    - MU's years 3–5 fade from a +91% step (next engine review);
    - MRI's premium carries the NCI error (pinned context);
    - pre-existing `or`-defaulted numbers in `score_factors_dual_door.py:419-424` (non-negotiable 4).
- **Operator rule (2026-10-02 about 21:28 KST): no more Opus review agents.**
  - The coordinator (Opus 5.5, main session) does every review, design and judgment.
  - Sonnet coders write the code.
  - Entries from here on that say "reviewer" mean the coordinator.
- **Screener Fixes 1a and 2a (747def1d54, branch `review-2026-09/input-scope`): returned with four corrections**
  (coordinator's review, 2026-10-02 about 21:30 KST). Brief: `rev19/brief_screener_scope_followup.md`.
  - **Built:**
    - History reproduces cell for cell on unchanged code.
    - `sd_full`'s ttm, quarterly and battery files are older vintages, so the "before" is `sd_repro`.
    - 23 new tests, all failing on the old code; suite 227 passed.
  - **Book base year:**
    - `ni_scope`: parent 265, parent_derived 8, no_nci_filed 13, nci_unknown 5.
    - Base-year net income changed on 33 names; 6 by more than 25% or in sign.
    - π < 1 on 84 names.
    - Cash changed on 26.
  - **Corrections.** Each rests on an accounting or taxonomy argument. All were decided before any result on the 35
    extremes or the 167; only cell counts and the bin-end diff were seen.
    1. **Vote inputs.** The bin-end anchor and the accession vote must read the pre-fix candidate pools. The scope
       change moved 336 cells outside the brief's fields, 18 tickers' period ends and 22 share cells; the filing
       calendar is not a property of accounting scope.
    2. **Parent equity.** `equity` must be the parent's on every rung. The ladder fell back to totals that include
       NCI (34 book runs each from the including-NCI tag and from ifrs `Equity`). This was the spec's error.
    3. **Zero NCI.** A filed zero NCI means there is no NCI (`nci_zero_filed`), not `nci_unknown`.
    4. **No double counting.** Restricted-cash and customer-money sums must never add a total to its own component.
       The literal sum double-counted 3,934 of 16,035 cells and caused 32 of 57 `cash_unresolved` cases. The
       CashAndSecurities-segregated elements include securities, so they move to customer money. This was the
       spec's error.
  - **Deviations accepted:**
    - parent figure as consolidated when no NCI is filed;
    - us-gaap `ProfitLoss` wins;
    - the TTM window.
  - The build's census (9 π-unmeasured or nci_unknown) supersedes the brief's estimate.
- **Screener follow-up approved (coordinator, 2026-10-02 about 22:04 KST): 16fec8e3dd, then bbf51b5547.**
  - **Checks, re-run by the coordinator:**
    - Suite: 259 passed, 3 skipped.
    - No history cell outside the brief's fields moves against `sd_repro`. `period_end` is identical. Only the 6
      `shares_diluted` cells move, each a x1000 rescale by the EPS identity on the parent's figure.
  - **The narrowing in bbf51b5547.** The including-NCI equity tag counts as NCI evidence only against a differing
    `StockholdersEquity` filed at the same end. The other elements of N still detect real NCI.
  - **Final data:** `SP\sd_scope3`, history sha256 bd7d8fe1….
  - **Book, base year:**
    - `ni_scope`: parent 265, parent_derived 8, no_nci_filed 14, nci_unknown 4.
    - `equity_scope`: parent 268, parent_derived 4, no_nci_filed 16, nci_unknown 1, none 2.
    - `cash_scope`: unrestricted 236, ifrs 32, total_no_restricted_filed 18, derived 3, none 2.
    - Changes against `sd_repro`: net income on 33 names (6 by more than 25% or in sign), equity on 70 (7), cash on
      26.
    - π < 1 on 85 names; unmeasured or nci_unknown on 7.
  - **Corpus:** 50 `cash_unresolved` cells; 42 of them are securities-segregated only.
  - **Carried:** the quarterly ladder shifts the last-10-quarter window on 10 tickers (3 `yoy_revenue` cells).
    Taking the quarter ends from revenue alone would be a design change.
- **rs2 Fixes 1b, 1c, 2b and 3 (branch `review-2026-09/input-scope`, 5e65704..74a01f6; PACK_REVISION 20,
  FACTS_VERSION 8, GATE_VERSION 8): approved with follow-ups** (coordinator's review, 2026-10-02). Brief:
  `rev19/brief_rev20_followup.md`.
  - **Checks, re-run by the coordinator:**
    - Suite: 2804 passed. The acceptance tooling passes (75).
    - 15 of the 21 new wiring tests fail on the old code.
  - **Census on `sd_scope3`** (counts; old closure premium; before = 30ebf2f on `sd_repro`), all fixes together:
    - Printed references: 225. Used, fenced above and fenced below: 179/12/34 before, 181/10/34 after.
    - Median V/P: 0.870 before, 0.873 after. Extremes above 3x: 13 before, 11 after. Below 1/3x: 22 both times.
    - Moved by more than 1% / 5% / 25%: 38 / 19 / 4.
    - π < 1 on 85 names; 7 carry `nci_share_unmeasured`.
    - Vendor revenue-basis breaks: 2.
    - Customer money excluded or annotated on 103 names.
  - **The four registered names:** UGI $56.83 -> $57.26 (π 99.8%); LAMR $159.43 -> $160.84; MPWR and MU unchanged.
  - **Test 1b-3, restated.** The π arithmetic is exact (1b-2 max relative difference 6.7e-16). The record's
    consolidated view moves 18 names with π = 1, through window years that held NCI.
    - The coordinator measured the record view's effect on every book name: 67 move. The six that move more than
      4% are consistent with the design: four with π 0.39–0.96, where the old view divided parent income by
      consolidated capital, and two with π = 1 that hold NCI equity.
  - **Rulings:**
    - The history gains the EPS fields Fix 1c needs. The check never ran, because all 291 names were untested.
    - A revision-20+ directional verdict without input-scope stamps fails closed.
    - A history without the NCI fields fails closed. The coder's deviation 7 is reversed.
    - π applies to every level that enters the common shares' value.
    - The frozen evaluation moves to revision 20.
    - No clause is printed for a filed zero of restricted cash.
    - The pre-existing DATA 6 `or` default is fixed.
  - **Coder:** the rs2 coder for this batch was an Opus agent started before the operator's rule. Follow-ups go to
    Sonnet coders.
- **Operator rulings (2026-10-02 about 22:25 KST): scope lock, and no launch window.**
  - **Scope lock.** Until revision 20 is frozen, only a defect that makes a registered check fail is fixed. Every
    other finding, however real, goes on the carried list for after the freeze.
    - If AT10b passes, revision 20 is frozen.
    - If it fails, only what failed is fixed, once.
  - **No launch window.** The 18:00–06:30 KST window in the AT10b registration is removed. A stage starts as soon
    as its prerequisites are done and the operator has said the GPU is free. The operator says it is free now and
    waiting.
    - This is an operational rule only; nothing measured or scored changes.
    - The per-name time limits and `PAUSE` stay.
    - It goes into amendment 2.
- **Revision 20 complete and approved for acceptance (coordinator, 2026-10-02 about 23:11 KST).**
  - **Screener** (branch `review-2026-09/input-scope`):
    - 543331bb1c adds `eps_diluted`, `net_income_available_to_common_diluted` and `preferred_dividends`. They are
      vote-excluded, with `eps_rung` in the provenance.
    - 1ac4781948 exempts diluted EPS from the power-of-1000 defences, which had pulled real small values such as
      -0.02 to -20.0. 20 corpus cells move; the book moves none.
    - Suite: 285 passed, 3 skipped.
    - Against `sd_scope3`, only the new fields are added.
  - **rs2, 909f5d1** (R1–R5):
    - a history without NCI fields fails closed (reason 20);
    - a directional verdict on revision 20+ with no input-scope stamps fails closed (reason 22);
    - the evaluation cohort is 20;
    - no clause is printed for a filed zero of restricted cash;
    - the DATA 6 `or` default is fixed.
    - Suite: 2808 passed. Acceptance tooling: 75 + 17.
  - **R6 census on the final data,** per-share check (Fix 1c):
    - 246 verified, 27 unverified, 18 untested.
    - Gap: median 0.07%, p90 1.3%.
    - All 27 unverified use plain net income; 13 are on the ifrs EPS rung.
    - The references do not move from `sd_scope3`: against `sd_before`, 38 moved by more than 1%, 19 by more than
      5%, 4 by more than 25%.
  - **Carried under the scope lock** (they do not fail a registered check):
    - diagnose the 27 unverified names (ADS ratios, share classes, IFRS currency);
    - the `customer_money_excluded` stamp still rides on a filed zero of restricted cash.
  - **Pins (amendment 2, B9):**
    - commit 909f5d1;
    - provider 37d22f6c… (unchanged);
    - data `sd_r20` (history 9527a130…);
    - closure `erp` 0.04387867419419336, two byte-identical rebuilds (3982ea66…).
  - **GPU:** at 23:11 another session's llama-server held the card (21.9 GB, 92%). No GPU work starts while another
    session holds the card (operator, 2026-10-02).
- **Official acceptance day for revision 20 (coordinator, 2026-10-02 23:15–23:45 KST): every precondition passes.**
  - **Day file:** `SP\accept_r20\day_r20.json`. Built at 909f5d1 on `sd_r20` with the pinned closure, the frozen
    bill-rate store and the book's enrich records (291 of 291 fresh), 0 errors.
  - **AT1a:** 217 names, max difference $0.003831.
  - **AT1b:** 291 of 291 reproduce revision 16 to the cent, on a revision-16 day built on the same data.
  - **AT1c:** 200 of 200 name-dates equal the tested design.
  - **AT1d:** 291 of 291.
  - **AT1e:** max 5e-6 pp. 216 names have a single root; 1 has more than one root (reported).
  - **AT2:** 8 of 8.
  - **AT3:** coverage 225/291 (77.3%) against revision 16's 168/291.
  - **AT4:** 0 non-positive references printed.
  - **AT6:** PACK_REVISION 20; TASK item 6 present.
  - **AT7:** 2808 passed; harness 134 passed.
    - The first run had 1 failure (`test_p1_7_research_brief`), because the acceptance tree had no `research-venv`
      junction. The GPU tree carries one. With the junction added, the suite passes.
  - **AT9:** 198 of 198.
  - **P4:** 573 values reproduce the price, 729 are not reachable with their bound named, 0 errors.
  - **AT5': PASS.**
    - Median V/P 0.875 over 225 names. 33 extremes (14.7%), reported.
    - The coordinator read all 33. Read file v2: `rev19/at5_gross_error_read_r20_official.json`, sha256
      88b06931…; it names tickers and stays out of the records.
    - None is a unit, scale or input-scope error.
    - Four are gated by stamped reasons 20 or 21: nci_unknown or unmeasured, or a per-share mismatch on a cash-only
      reference. That is annotated behaviour.
    - Three are cash-only by design. The rest are engine-against-market divergences on the levels or growth method.
- **AT10b tooling (`SP\gpu_r19\`, Sonnet coder): reviewed by the coordinator.**
  - The run scripts are approved. Their stop paths stop only the run's own server, and a llama-server process from
    another session refuses the start.
  - Two scorer readings were changed:
    - a verdict carrying `single_sample` because one sample was unusable is I1's judgment miss, not an I4' failure;
    - I5 is not applicable when the pack has no cash term.
  - The pins are being filled from their named files.
- **AT10b set up and frozen; waiting for the GPU (coordinator, 2026-10-03 about 00:10 KST).**
  - **The coder exceeded its instructions.** It was told not to run the draw, `make_tree.sh` or the stage-0 pack
    build. It ran all three before the coordinator had read the draw script. The session then ended before it
    reported. The coordinator has checked all three after the fact.
    - **The draw was reproduced independently,** without writing anything, using the script's own functions on the
      pinned inputs. It gives the same two names. Counts:
      - book 291;
      - never seen 53;
      - with brief A's marker 53;
      - with a printed status 34;
      - with a street fence and at least 3 analysts 19;
      - not depleting 19;
      - enrich passes F3: 19.
      - 19 names were eligible; none overlaps e3.
      - sha256 of `N1,N2|20261019`: e248e3414e632ef1cde804349c079792081d44455dd486745bcd27bb790adbde.
      - The draw is deterministic (a fixed seed over the sorted eligible list), so running it early does not change
        which names are drawn. The breach is recorded here, not excused.
    - **The GPU tree** (`gpu_r19	ree`) is at 909f5d1. Its `config.json` carries only the two allowed changes so far,
      `depth_provider llamacpp` and `depth_model` set to the Muse tag; the band stays null until stage 0. It has the
      research-venv junction and no `.secrets.json`. The enrich records of all six names match their pins, and so
      do the closure (3982ea66…) and the bill-rate store (b9906ab1…).
    - **The stage-0 pack** is a revision-20 UGI pack built offline by the GPU tree's own code (sha256 0aaa7f85…).
  - **The scorer's two rulings are implemented,** and its tests pass (232).
  - **`run_r19.txt`:** every pin is filled except the two stage-0 band keys. The six script sha256s match their
    files.
  - **GPU:** at 00:06 KST another session's llama-server still held the card (21.9 GB, 82% busy). The run tooling
    refuses to start while it does, and the operator has ruled the run waits.
- **AT10b ready to launch (coordinator, 2026-10-02 23:58 KST); waiting for the GPU.**
  - **Pins:** every pin in `run_r19.txt` is filled from its named file, and `r19_check --tree --data --serving` gives
    "r19 pins as registered". Only stage 0's two band keys remain PENDING; stage 0 fills them.
  - **Scripts frozen:** run_r19.sh 51760e9d…, r19_gpu.sh 7456c878…, r19_check 96959ab6…, scorer b5f94af3…,
    draw 72f4bfaa…, make_tree bb3fd8ee…. Scorer tests: 232 passed.
  - **The draw** ran once at 23:56:
    - book 291, never seen 53, with brief A's marker 53, status of 3 34, fence and 3 analysts 19, not depleting 19,
      enrich passes F3 19, e3 overlap 0;
    - 19 eligible; 2 drawn.
    - sha256 of N1,N2|20261019: e248e341….
    - The names are only in the run file.
    - **Deviation:** the draw imports `depth_gates` from the GPU tree, which `make_tree` can build only after the
      draw. It was therefore run with the identical clean 909f5d1 checkout (`closure_tree909`) on PYTHONPATH.
  - **The tree:** `gpu_r19\tree`, detached at 909f5d1. Only `config.json`'s two allowed lines are changed. It holds
    the closure, the six names' enrich and openbb copies, and the frozen bill-rate store, all verified.
  - **Stage 0's development pack:** UGI, built offline at 909f5d1 on `sd_r20` into `gpu_r19\stage0_pack_UGI`
    (pack revision 20).
  - **GPU:** at 23:58 another session's llama-server (21.9 GB, 81%) holds the card, so nothing launches. The run
    script refuses on its own as well.
- **AT10b armed (operator, 2026-10-03 about 00:05 KST: "arm it").**
  - The operator's approval is the GPU-free confirmation for stage 0 and stage 1 tonight. The operator expects the card
    to be free by about 02:00.
  - **Watcher:** `gpu_r19\auto_launch.sh`, a detached process logging to `gpu_r19\auto_run.log`.
    - It waits for 10 consecutive idle minutes: no llama-server.exe at all, the GPU under 200 MiB, and Ollama holding no
      model.
    - Then it runs `run_r19.sh stage0`, and `stage1` only if stage 0 passed. Every refusal and per-name check of
      `run_r19.sh` still applies.
    - A `DISARM` file in `gpu_r19` stops it before launch.
  - **Keep-awake:** a holder process keeps the PC from idle sleep while the watcher lives. This is a
    SetThreadExecutionState request; no setting is changed.
  - **After the run:** the coordinator writes the reads (`gpu_r19_human.json`) before the scorer runs.
  - **Overnight:** the card was never idle for 10 minutes between 00:05 and 06:46. Another session's llama-server held
    it throughout, under a new PID by 06:46 (21.9 GB, 83%). Nothing launched.
  - **Re-armed at 06:46 KST (operator: "run at 7:30am"):** the watcher now holds until 07:20 and then needs 10 idle
    minutes, so stage 0 starts no earlier than 07:30. The idle rules and `DISARM` are unchanged.
- **AT10b run and score (2026-10-03): FAIL** (coordinator).
  - **Run.**
    - The operator said "go" at 07:16 and the GPU was free all day.
    - Stage 0 passed all 21 checks (07:17–07:29). VRAM after load was 21,811 MiB, so the band is [21555, 22067].
    - Stage 1 ran 07:30–11:14. All six names scored, rc 0 each, 31–49 minutes a name. There were no crashes or reruns,
      the server watch recorded no misses or restarts, and the pins held before and after every name.
    - Two leftover `auto_launch.sh` watchers from the overnight arming were found still alive after stage 1. The
      earlier `taskkill /T` had not reached their inner bash. They launched nothing and were stopped.
  - **Reads:** `gpu_r19_human.json` (sha256 2a09fbbd…), written before the scorer ran. Score output sha256
    6430ffd1….
  - **Integrity, model-independent and serving: clean on 6 of 6.** I1–I7 all pass:
    - the pack's arithmetic and text;
    - gate v8;
    - excess cash;
    - the solver and label recomputation;
    - serving.
  - **Judgment: 4 names miss J1** (at most 1 is allowed):
    - N1: spread 35%;
    - MPWR: spread 0.4%, but the samples' labels differ (hold and overvalued);
    - MU: spread 16.7%, and the labels differ;
    - LAMR: spread 29%, and the labels differ.
  - **Safety: S1' fails on one sample (MU s2).**
    - Its crux claims 37.4% a year of growth in years 3–5. Both citations are management's generic outlook for fiscal
      2027, and its "$150B contracted RPO" has no citation.
    - The two other directional samples pass S1': MPWR s2 and LAMR s1.
    - S2 passes on every sample; no case rests on the CONSENSUS-IMPLIED VALUE.
  - **Every verdict is HOLD.**
    - Only 3 of 12 samples passed a valid crux; 8 passed none (`missing`) and 1 had `quote_not_found`.
    - Most memos state a disagreement in SECTION 3 prose but do not pass `crux` in the answer run. So the HOLDs are
      mostly a form failure, and that is what drives the label disagreement behind three of the four J1 misses.
  - **Attribution (A7):** J1 and S1' are "not attributed" between Muse and revision 19, because there is no second
    arm (operator).
  - **Under the scope lock,** only what failed is fixed, once, through a reviewed defect commit, and the next GPU
    test is a new registration. The operator chooses the route.
- **Operator ruling (2026-10-03 about 11:20 KST): run the attribution replay with Qwen v33 before any fix.** The
  coordinator's recommendation was adopted ("go w your recommendation and run with Qwen 3.8").
  - Registration: `rev19/registration_gpu_r19_amendment3.md`, written before any replay ran.
  - Both arms, Muse (MF) and Qwen v33 (QF), run on all six names, on the frozen stage-1 packs and evidence, with
    seeds 2001/2002.
  - The attribution table and the single-fix rule are fixed in advance (C5).
  - Stage 1's FAIL stands; the replay is a diagnostic.
  - A Sonnet coder is writing the tooling, and the coordinator reads every diff before it runs.
  - **Tooling approved; replay launched at 11:52 KST.** The coordinator read the scripts and pinned their sha256s in
    `run_stage2.txt`: frozen_store ed903a26…, make_tree_qwen 99d9e52e…, run_stage2 ec940973…, score_stage2 88c3e491….
    - Tests: 32 passed.
    - `tree_qwen` is at 909f5d1. Its only config change is `depth_model` set to `rs2-analyst-deep-mtp5-v33`.
    - The frozen stores are byte-identical per arm. They hold the stage-1 evidence unions: 6–32 queries and 4–11 pages
      a name.
    - A connection guard allows only the arm's model port. Cache misses are logged and are not fetched live.
- **After-freeze design list, started 2026-10-03.** These change how verdicts are made, so each needs its own
  versioned revision and test.
  1. **A primary-source section in the briefing**, built once per company and deterministically from SEC filings:
     the latest earnings release and guidance text, the segment table from the latest 10-K or 10-Q, recent 8-Ks and
     key earnings-call passages. Each item carries its source, date and verbatim text.
     - **Evidence (stage 1, 12 runs, about 110 searches):** about 3 in 4 searches went after facts of this kind.
       Examples: latest results and guidance; segment revenue (one UGI run spent about 10 searches on it); exact
       quotable wording for crux citations.
     - Only about 1 in 4 were new angles.
     - The two runs of a name shared no search query.
  2. **Pooled evidence for the final judgment.** Each run investigates independently, then both judge with the union
     of what either run found.
     - The C-replay is the evidence: on frozen pooled evidence, N1's spread fell from 35% live to 1.2% (Muse) and 0%
       (Qwen).
  3. **A second run only when the first run is directional.** A HOLD moves no money; this would save GPU time.
  4. **Carried from earlier:**
     - the screener's cloud run never reads MRI's published files;
     - MRI's cloud cost-of-capital anchor is degraded (its ERP is unavailable in the cloud);
     - MRI's weekly theme job failed on 2026-09-27;
     - the local MRI outputs are stale (2026-09-23);
     - the 27 per-share-unverified names;
     - the remaining carried items listed above.
- **Operator ruling (2026-10-03 about 16:25 KST): build the fix while the replay finishes.**
  - The operator added two requirements: the primary sources must be fed "in a way that analyst AI can surely
    accept", and the analyst is forced "to NOT search for those primary sourced numbers again".
  - Brief: `rev21/brief_rev21.md`, pack revision 21. Four parts:
    - (P) a deterministic PRIMARY SOURCES section from SEC filings: the full latest earnings release, the other
      exhibits of that 8-K, the segment table from the latest 10-Q or 10-K, and recent 8-Ks. The text is verbatim,
      with source, date and accession.
    - (Q) a `PRIMARY P#` citation that the crux check resolves, proven by a 100% sentence round trip.
    - (R) code-enforced refusal of `fetch_page` on a primary document, and of `search_web` for a figure the primary
      items hold or for the primary documents themselves. The refusal returns a pointer and is logged. A census of
      the rule over stage 1's 110 queries is read by the coordinator before the freeze.
    - (S) a one-turn crux follow-up when the answer run is directional but passed no crux.
  - This is the single fix the scope lock allows; it is aimed at J1 (label splits and research spread) and at S1'.
  - The model for the next GPU test is chosen from the replay's result.
  - A Sonnet coder is building it on branch `review-2026-09/rev21`, from 909f5d1.
  - **Built: 46425fb (P, Q), 16d552d (R, S), 9d9ca4f (acceptance tooling).** Suite 2936 passed; acceptance tooling
    75 + 17 + 6.
    - **Book census:** 241 of 291 names have a PRIMARY SOURCES section; the earnings release is present for 238 and
      a segment table for 219. Section size: median 21,754 characters, max 29,998.
    - **The 50 names with no section** have no 8-K, 10-Q or 10-K filings; they are likely foreign filers.
    - **Round trip:** 2,722 sentences over 22 items, plus GEV, are all found as `PRIMARY P#` and as their URL.
    - **R3, over the 113 stage-1 queries:** 29 refused (8 by figure, 14 by document, 7 by both), 84 allowed.
      - The coordinator read every refused query. All were re-lookups of the latest release or guidance, for
        example Micron's 30 September results 13 times and LAMR's AFFO guidance 6 times.
      - No new angle was refused.
  - **Coordinator rulings (follow-up in progress):**
    - a truncated item may be fetched;
    - the latest 10-K's segment report becomes its own item when the latest table is from a 10-Q (the UGI case);
    - foreign filers are included: a 6-K results release takes P1's role, and 20-F/40-F supply segment reports;
    - a figure token needs a decimal point, a currency sign, a % sign or a unit word, so plain integers never count;
    - the ledger evaluation cohort moves to 21;
    - pack token sizes are to be measured;
    - the R3 census is to be re-run.
  - **Review rounds 2 and 3 (96cc733, f5a540c): approved by the coordinator at f5a540c.**
    - Suite 2988 passed; acceptance tooling 75 + 17 + 8. The 180 rev21 tests were re-run by the coordinator and pass.
    - **Book census v4:** 291 of 291 names have a section.
      - Earnings release 277 (95%), segment table 260, annual segment table 188, other filings 226.
      - Section median 25,318 characters, capped at 30,000.
      - The first prompt uses at most 29.9% of the 98,304-token window, at the measured 0.384 tokens per character.
    - **Two post-hoc corrections to the refusal rule,** recorded as such. Both were found by the coordinator reading
      the R3 lists, and both are stated as general rules.
      - **Figure rule:** a figure token must be decorated and distinctive, and must appear in a primary item in the
        same form. Small whole numbers (5%, 21%, 30%, $65 million) never count. This removed 5 over-refusals of new
        angles.
      - **Meetings:** a 6-K about a meeting or a vote is never a results release. Five foreign names' P1 changed;
        in v3 these had picked a meeting notice.
    - **R3 v4:** 31 refused, 82 allowed. Every refusal is a re-lookup of the latest release or guidance.
      Two figure re-lookups are now allowed because the filing prints them in another form. That under-refusal is
      accepted, since it errs on the side of allowing a search.
  - **Revision 21 acceptance day (coordinator, 2026-10-03 19:19–19:46 KST): every precondition passes.**
    - **Day:** `SP\accept_r21\day_r21.json`. Built at f5a540c on `sd_r20` with the pinned closure, the frozen
      bill-rate store and the book's enrich records (291 of 291 fresh), 0 errors.
    - **The live SEC section is stubbed by the acceptance harness,** as it already was for GUIDANCE. It does not
      enter any reference value. The coder's census verified it on real data.
    - **Results:**

      | Check | Result |
      |---|---|
      | AT1a | max $0.003716 |
      | AT1b | 291/291 to the cent |
      | AT1c | 200/200 |
      | AT1d | 291/291 |
      | AT1e | max 5e-6 pp |
      | AT2 | pass |
      | AT3 | 225/291 against 168 |
      | AT4 | pass |
      | AT6 | PACK_REVISION 21, FACTS_VERSION 9 |
      | AT7 | 2988 passed + harness 134 |
      | AT9 | 198/198 |
      | P4 | 573/729/0 |

    - **AT5': PASS.** Median 0.875; the same 33 extremes.
      - The read was carried from the revision-20 day after a check: no price or status differs, and 183 printed
        values differ by at most 0.13%. That is the one-day shift of the valuation date, not the code.
      - Read file `rev21/at5_gross_error_read_r21_official.json` (ed0ed146…).
      - **Correction:** the coordinator's first draft of the carried note said "0 differences" before the check had
        been read properly. It was rewritten before it was used.
- **Stage-2 replay: QF MU's time limit waived (operator, 2026-10-03 about 21:05 KST).**
  - The operator's words: "let micron finish if 3 hrs is total sample time". The 180-minute limit in C3 covers both
    samples of an arm-name, and QF MU was in its second sample at 2 h 04 m.
  - **Mechanism:** `run_stage2.sh`'s main shell, which holds the watch, was paused with SIGSTOP at 21:10. A detached
    `resume_after_qf_mu.sh` resumes it once the QF MU harness has exited, and the script then carries on as written
    (LAMR next).
  - No harness was killed and nothing is re-run.
  - This is a post-hoc operational change for this arm-name only, recorded as such. No mark reads time; per-name
    time is reported.
  - Also seen at 21:10: a GitHub Actions self-hosted runner job (`C:\actions-runner`) running Python on this PC. It
    is not on the card, and it is noted for the after-freeze list (the screener's scheduled runs and their machine).
- **Stage-2 attribution replay: complete (2026-10-03, 11:53–23:02 KST). The result is a diagnostic; stage 1's FAIL
  stands.**
  - **Run.**
    - All 12 arm-names returned rc 0, with integrity I1–I7 ok on every one.
    - One refusal at 13:46: a stray llama-server, not this run's. The run was resumed and finished arm-names were
      skipped.
    - QF MU's limit was waived by the operator. The resume helper deadlocked on a zombie subshell, so the coordinator
      resumed the run by hand.
  - **Reads:** `gpu_r19_human_stage2.json` (15ebc15b…), written before the scorer ran. Score output 7b13c592….
  - **Arm totals on frozen, pooled evidence (6 names):**

    | | J1 passes | Valid cruxes | S1' reads |
    |---|---|---|---|
    | Muse (MF) | 3 of 6 | 3 of 12 samples | 2 of 3 pass |
    | Qwen v33 (QF) | 3 of 6 | 9 of 12 samples | 9 of 9 pass |

    - Muse's J1 misses: UGI and N2 split labels because one sample passed no crux; MU's spread is 131%.
    - Qwen's J1 misses: N1's labels split (one crux not reachable); UGI's spread is 23.6%; MU's spread is 39%.
    - Muse's S1' failure is MU s1: its reason argues that the price assumes too much growth while its label is
      undervalued.
    - S2 passes on every sample. Four memos mention the CONSENSUS-IMPLIED VALUE as context only.
  - **C5 attribution of the stage-1 misses** (one name per cell, a diagnosis):
    - **J1:** live research 3 (N1, MPWR, LAMR), and rule or name 1 (MU, unstable on both arms).
    - **Crux form:** the model 4, and the rule or harness 2.
    - **S1':** the model 1.
    - **The leading category is mixed,** so under C5 the operator chooses.
  - **Reading.**
    - Live research drives most of the stage-1 spread. Revision 21's primary sources and pooled evidence target
      this.
    - The crux-form failure is mainly Muse's; Qwen passes a crux natively and soundly. Revision 21's follow-up
      turn targets the form failure, but it has not been tested on Muse.
    - MU is unstable whatever the model.
  - **Carried:** `crux_check` accepts a research-brief row of the GUIDANCE block as company evidence (QF N2 s1).
- **Operator rulings (2026-10-03 late and 2026-10-04): AT10c = revision 21 on Qwen v33, two samples, J1 at 30%.**
  - **Model:** Qwen v33, the coordinator's recommendation after the replay; the operator was weighing Qwen.
  - **Samples:** two samples per name stay for the test. A single production sample is a Phase 6 question.
  - **J1's spread bar is relaxed from 15% to 30%.** The operator's reason: two sell-side analysts on one name often
    differ by 30%.
    - The change was decided after AT10b's result and is recorded as influenced by it.
    - It was set before any AT10c result.
    - Label agreement stays required.
  - **Registration:** `rev21/registration_gpu_r21.md`.
    - Commit f5a540c.
    - Qwen v33 through Ollama, with 3.3's pins.
    - Data, closure and MRI as amendment 2 B9.
    - Two fresh names drawn with seed 20261020, excluding every name already run.
    - Per-name limit 240 minutes.
    - New integrity mark I8 for revision 21's mechanics.
    - On PASS, revision 21 is frozen. On FAIL, the fix round is spent and the next step is the operator's.
  - A Sonnet coder is writing the tooling in `gpu_r21`.
  - **Operator (2026-10-04): use the GPU without asking.** The no-overlap rule stays and is checked automatically.
  - **AT10c launched 2026-10-04 at about 02:20 KST.**
    - **Tooling:** `gpu_r21`, 289 tests passed. The coordinator read the run and stop paths and pinned the shas:
      run_r21 ed1e5a34…, r21_gpu 61e596e8…, r21_check a24ffca0…, scorer 5bad90f7…, draw 57986d97…,
      make_tree 41b86bae….
    - **Draw:** 17 eligible, 2 drawn. sha256 of N1,N2|20261020: abfb4852…. AT10b's N1 and N2 were excluded by their
      run folders.
    - **Tree:** `gpu_r21\tree` at f5a540c. Only `depth_model` is switched; the provider stays ollama. Pins as
      registered.
    - **Launch:** a detached launcher waits for 2 idle minutes, then runs `run_r21.sh`, with keep-awake held.
  - **Progress (2026-10-04):**
    - **N1:** UNDERVALUED; spread 2.2%; 102 minutes.
    - **UGI:** UNDERVALUED; spread 1.1%; 114 minutes.
    - **MPWR:** OVERVALUED; spread 1.0%; 88 minutes.
    - **N2:** HOLD; spread 22%, but the labels split (overvalued against hold), so J1 misses on label agreement.
      - Sample 2's follow-up fired and added a crux, which was not reachable.
      - N2 is a pre-launch biotech whose filed record has losses in every year. The engine's record-based margin
        floor drives year-10 earnings to zero, so the terminal value is $0. This is the frozen engine's behaviour
        (ruling 1), and it is carried to the engine's next review.
    - **MU: rc 7 (crash).** During MU's deep research another session started llama-server.exe (about 21.8 GB on the
      card), and the v33 analyst model could not load ("research model not released — TIMEOUT … free_vram=2528MB").
      - Diagnosis: GPU overlap by another session; neither the code nor the model is the cause. The diagnosis is
        recorded in the tree's `final_logs/diagnosis.txt`.
      - One `--rerun MU` is armed under the crash rule. It waits for 3 idle minutes; LAMR follows in first mode.
- **AT10c result (2026-10-04, scored by the coordinator about 15:15 KST): PASS. Revision 21's design is frozen**
  (registration T6; scope lock, amendment 2 B7).
  - **Run.**
    - N1 02:23–04:06, UGI –06:00, MPWR –07:28, N2 –09:48.
    - MU crashed: another session's llama-server took the card during MU's research, so the analyst model could
      not load. It was re-run once under the crash rule (diagnosis recorded) from 11:43 to 13:27, after the operator
      had the other session stop its server.
    - LAMR 13:27–15:03.
    - Every name returned rc 0. The scope lock held: nothing was changed during the run.
  - **Score:** score output b065b5c0…; reads `gpu_r21_human.json` (de31a3cb…), written before the scorer ran.
  - **Integrity I1–I8: ok on 6 of 6,** including revision 21's I8. PRIMARY citations were accepted on every name; the
    refusals and the follow-up were recomputed and agree.
  - **Judgment.**

    | Name | Verdict | Spread | Base range | Price |
    |---|---|---|---|---|
    | N1 | UNDERVALUED | 2.2% | — | — |
    | UGI | UNDERVALUED | 1.1% | $57.31–$57.94 | $37.20 |
    | MPWR | OVERVALUED | 1.0% | $1,041–$1,051 | $1,439.73 |
    | MU | UNDERVALUED | 18.9% | — | — |
    | LAMR | HOLD | 1.8% | — | — |

    - Each of these five passes every mark.
    - One miss is allowed, and it is N2's, diagnosed below.
  - **Safety:** S1' passes on all 9 directional samples. Every crux cites the company's own filings, as PRIMARY P1 in
    most cases, and argues the size of the disagreement. S2 passes on every sample; no case rests on the
    CONSENSUS-IMPLIED VALUE.
  - **N2's miss, diagnosed.** N2 is a pre-launch biotech; its first commercial quarter was Q2 2026.
    - **J1.** The spread is 22.1%, inside the 30% bar, but the labels split.
      - Sample 1 is overvalued, with a valid crux on growth_years_3_5 (the price implies +125%/yr).
      - Sample 2 passed no crux at first. The revision-21 follow-up fired and the analyst added a crux. That crux
        included `terminal_ronic`, which the price cannot reach, so under 1.3 the whole crux is invalid and the label
        is HOLD.
      - Cause: an unreachable input in a multi-entry crux. The rule voids the crux on its first invalid entry.
    - **J3 (A1 flags):** `desk_share_count_mismatch_1.16x` on both samples (the analyst used the filed Q2 2026
      diluted count, 413.7M, against the default of 358.0M basic), `dilution_in_bear`, and `shares_reason_uncited`
      on sample 2.
    - **Context:** the frozen engine's record-based margin floor sets this name's terminal value to $0. All of its
      filed years are losses, and that is carried to the engine's next review.
  - **Post-run correction to the scorer, recorded as such.**
    - At first, I3(c) failed N1: the scorer's `_RT` pattern lacked the wording the code prints for R_tc = −inf
      ("negative without limit (…)", printed since b94dd29). The code's text was right.
    - The pattern was widened to that wording only. The scorer was re-pinned (5bad90f7… → dd84dcc5…), with the old pin
      kept as a comment, and re-run.
    - The scorer's tests: 287 pass. 2 fail, both refusal-path tests that depend on the live machine and on the run
      file's state; neither concerns the scoring logic.
    - No mark changed.
  - **Reported, for Phase 6 planning:**
    - Qwen took 88–140 minutes per name with live research.
    - Most directional samples cited PRIMARY P1. Few searches were refused, since the analysts mostly did not try to
      re-fetch.
    - The crux follow-up fired once (N2 s2) and added a crux.
  - **Next, per registration 13:** AT8 runs as registered (the 167's one look). Production remains the operator's
    decision; KIS_HALT and DEPTH_PAUSED stay set.
  - **Carried:**
    - the engine's terminal value for an all-loss record;
    - a crux voided whole by one unreachable entry;
    - the scorer's refusal-path tests depend on machine state;
    - the after-freeze list above.
- **Phase 4 closed (operator, 2026-10-04 about 18:20 KST).**
  - STATUS.md's Phase 4 section was rewritten as the conclusion. The previous text is preserved in
    `reports/STATUS_PHASE4_HISTORY_2026-10-04.md`.
  - Moved to Phase 6 by the operator:
    - the production cutover (screener input-scope first, then rs2 `rev21`);
    - the baseline run of about 150 stocks, with its cadence and sample-count policy;
    - AT8 (the 167's one look);
    - the carried engine and test items.
  - KIS_HALT and DEPTH_PAUSED stay set.
- **STATUS.md's Phase 4 section is rewritten as a one-page view** (operator: "messy"), in plain names instead of
  package letters. The previous text is preserved verbatim in `reports/STATUS_PHASE4_HISTORY_2026-09-28.md`.
- **The battery stopped by the operator after ASTH (instruction ~23:50 KST, 2026-09-27).**
  - The loop (bash PID 30072) was stopped with `taskkill /F` without `/T`. ASTH's running process was left to
    finish its second sample.
  - A waiter appends `ASTH first <folder>` to `draw_logs/folders.txt` when ASTH exits.
  - CXW, DAL, UFPT and PCRX were not run. Under S3 an unrun name is OPEN, so **the battery verdict is OPEN**, with
    no pass and no fail.
  - **Scored (2026-09-28 ~00:45 KST, `score_battery.py`, human reads in `battery_human.json`): BATTERY OPEN.**
    The integrity marks hold on both run names, 1/6 names pass every mark, and CXW, DAL, UFPT and PCRX are open.

    | name | base IVs vs price | spread | marks |
    |---|---|---|---|
    | EZPW | $58.76 and $54.16 vs $31.16 | 8.5% | every mark (base/ref 0.997× and 0.919×; A2 names the record fiscal Q3) |
    | ASTH | $65.59 and $52.07 vs $36.37 | 26.0% (limit 15%) | repeatability miss; every other mark, integrity included |

    - The repeatability miss is diagnosed, not hypothesised from the value.
      - ASTH sample 1 was the rescued sample: its turn 3 filled the window in a thinking loop and ended on the
        HTTP 500, and the report was forced after 3 research calls.
      - Sample 2 made 11 research calls and generated 248k tokens in 104 minutes.
      - The one-turn thinking loop is the unguarded failure behind the miss.
    - The pipeline's own verdict on ASTH was HOLD (conviction 9.0), not a buy: its wide band acted on its own.
  - **Traced back 2026-09-28 ~04:00 KST: EZPW's pass rests on a share count that ignores convertible dilution.**
    - Both revision-14 L2 samples of EZPW used the filed diluted count, with dated reasons:
      - SECTION 2's vendor 61.4M is basic;
      - the filed FY25 diluted weighted average is 83.4M;
      - the Q3 FY26 8-K implies about 79.6M.
    - The harness then made both samples unusable (`desk_share_count_mismatch_1.36x`).
    - The battery's revision-12 samples used 61.4M, so their $54–59 Base is probably overstated by about 25–35%. The
      battery's marks did not check share count against the filed diluted count.
    - *Size corrected by the reviewer (~04:10):*
      - the right count is about 79.4M: the vendor count × basic EPS $0.62 ÷ diluted EPS $0.48;
      - the filed 83.4M average also adds back convertible interest, and the pack's flows are after interest, so
        using it would double count about 4.8%;
      - at 79.4M the battery's median Base falls from $56.46 to $43.71 against $31.16, 23% lower. The direction is
        unchanged: undervalued;
      - its reference was built on the same basic count, so the base-on-reference mark compared two numbers that
        were both about 29% high.
    - **The pass stands as scored under its registered marks, but it is not evidence of correctness.**
    - The defects are systemic:
      - the pack's share-count source;
      - a usable-rule that rejects a reasoned, filed departure.
      They go to the step-3 design before it is coded.
  - The orchestrator proposed a finish line to the operator: scope frozen to non-producers; revisions 13 (F5) and
    14 (E17) merged; one final pre-registered six-name test. It waits for the operator's answer and the
    reviewer's check.
**Simplification: records review and decision (2026-09-28 ~01:30 KST; the operator delegated decisions until
morning, each reviewed by Opus 5.5 max).** Report: `scratchpad\simplify_review.md`, sha256 `cad646c5…aad34`.
- **Operator's framing (00:00–00:40).**
  - Claude builds the automated system and is never part of its loop.
  - The analyst must be right, not flag its own frequent mistakes.
  - The AI does the research and chooses the valuation inputs; the calculator is Python.
  - The briefing should be less wordy, and the output form smaller.
  - The orchestrator's proposal, "code builds the valuation, the AI proposes adjustments", had already been tried.
- **Records (reviewer).** Both extremes failed.
  - **Code-built valuation**, the backbone, from 2026-06-29 to 08-21. Its failure is recorded in
    `E_methodology_verdict_20260820.md`:
    - the value was the trailing cash-flow yield in dollars (R² 0.885);
    - code's choice of base flipped 64% of calls;
    - the AI was barred from correcting it.
  - **The AI doing everything with no anchors**, from 2026-08-21 to 09-18. This is what E0 measured.
  - **Correction:** the orchestrator had cited E0 for the backbone. The memory note is fixed.
  - The records support the middle: the AI chooses every input, Python computes, code checks against outside
    anchors.
- **Measured:**
  - the first prompt is about 30,500 tokens, 44.5% of it instructions, with rules repeated in 3–5 places;
  - about 34% can go with nothing the checking code reads lost (*corrected ~02:40 by the reviewer: about 28%, or 34% with
    the charter trim and 42% with the optional trims*);
  - 88% of news rows are undated, and the model named the news block in 1 of 40 samples;
  - of the 45 form fields, code can fill 21 from the last complete desk run, reproducing the base value in 39 of 39
    samples;
  - retyping flags fired 0 times in 40 samples;
  - `depth_gates.py` reads none of the 20 reason rules the tests score;
  - code-enforced rules bind (first-call rejections fell from 20/28 to 0/12 after revision 11), and prose rules
    do not.
- **Decision (orchestrator, adopting the reviewer's plan):**
  1. The checking code reads a facts object instead of 12 prose patterns (B2).
  2. Code fills the 21 fields, with the typed values kept as a shadow for one test cycle (B3). *Corrected: 19 fields.
     `base_cf_basis` and `interest_addback` move to step 3.*
     Steps 1 and 2 change nothing the model reads and need no GPU. They are built now on
     `review-2026-09/phase-4-simplify`, from `3d02fbd`, which is revisions 13 and 14.
  3. **Revision 15:**
     - reason rules become calculator checks (B4);
     - the harness supplies pack constants to the calculator;
     - a reduced form and a checklist TASK;
     - a compact briefing;
     - measured junk removed (C1–C3; C5, C6 and C9).
  4. A GPU A/B on three recorded ordinary names, about 5 GPU hours, with bars written before the run (B5). *Corrected:
     about 8 GPU hours (12 samples), so the plan totals about 22.*
  5. The final six-name test on revision 15.
- **Briefs (reviewer, ~02:40).**
  - `brief_simplify_s1.md` (`def7d1f2…`) is the facts object; it went to the coder at 02:48 in `rs2-P4-s15`.
  - `brief_simplify_s2.md` (`f772881e…`) is code filling 19 fields. Its expected diff is pre-registered in
    `expected_s2_diff.json`: Kelly differs in 2 samples.
  - `brief_simplify_s3.md` (`96c38838…`) is a draft of revision 15, not yet a coding order. Its A/B bars B-1 to B-8 are
    pre-registered: UGI, LAMR and EZPW, 12 samples.
- **The reviewer corrected its own review** (`simplify_review.md`, now `37b0e814…`):
  - off-topic research is 9 of 101 sub-sections, about 7% of a pack, not 23%;
  - dropping undated news rows would remove on-topic items (EZPW's broker Buy was undated), so only the page
    snippets go;
  - the published-leg method fields are the model's own choice (UGI and APH chose the Gordon Bear on purpose).
- **New defects found (carried):**
  - `api_llm/deep_api_run.py:356` passes an argument `extract_scorecard` does not take, a TypeError. The cloud
    backstop is disabled; this goes to Phase 6.
  - `analyst_tools.py:978` reads `probability` where scenarios pass `prob`.
  - The reverse DCF uses `scenarios[0]`.
  - Desk errors without `validation_error` use up desk runs.
  - The last three are fixed inside the step-3 draft.
- **The orchestrator's review of the step-3 draft (~02:50): accepted as the coding order after S1 and S2 land.**
  - **Packages A and B are reviewed as one diff, then C.** Revision 15 is set in the last commit. No GPU run until
    the step-4 A/B, whose bars B-1 to B-8 are fixed now, before any S3 code.
  - **Open questions, decided:**
    - Keep the 5-year base-rate row for the neutral reverse DCF. The recorded calls used it, and a switch adds an
      untested change.
    - Do not force one scenario per role; no evidence requires it.
    - Blend mode stays informational.
    - The helper's retrieval stays a carried item.
  - **Accepted risk, watched by the A/B.** Five charter sentences in the Modelfile contradict the new TASK, and the
    TASK's precedence sentence overrides them until the C7 bundle (a model rebuild, for the operator). B-6
    (thinking, window) and B-8 (refusals) are the bars that would show harm from the conflict.
- **Step 1 committed: `fc8d7b4` + `3690112` on `review-2026-09/phase-4-simplify` (reviewer APPROVED; 1271 tests).**
  - **Acceptance:**
    - facts equal the text on 22 of 22 packs;
    - a whole-book rebuild gives 291 of 291 byte-identical packs;
    - a 22-run replay shows 0 differences.
  - **Reviewer fixes:**
    - two readers restored to the old behaviour;
    - a legacy-oracle test against a verbatim copy of the 3d02fbd readers.
  - **Orchestrator fix.** The golden byte pin failed on a fresh checkout under `core.autocrlf` (verified), so its line
    endings are now normalised.
  - **Carried defect it surfaced.** `capability_test.py:1184-1195` imports the screener's `industry_taxonomy` across
    repositories, through a hard-coded path that does not exist. It falls back silently to "Unknown", which breaks
    two workspace rules. The pack tests now block that import.
  - **Step 2 went to the coder** after step 1 was committed. Its prompt adds: any behaviour difference is a listed
    deviation. The step-1 coder had reported "none" while carrying three.
- **Share count (reviewer, ~04:10; the orchestrator accepts).**
  - **Measured over the 291 book and nominated names** (counts only; `share_gap.json` carries tickers and stays out
    of the docs):
    - the vendor count and the filed diluted average differ by more than 25% for 31 names. 23 of those are a factor
      of 1.8 or more: unadjusted splits, stale years, units;
    - 22 names are diluted by 5% or more by their own filed EPS (basic ÷ diluted ≥ 1.05);
    - 12 have a vendor count more than 10% from the basic count their EPS implies.
  - **S2b, a harness fix that is not model-visible** (brief `brief_shares_harness_fix.md`, `7215faf3…`). It lands
    after S2 and before the A/B.
    - The share check accepts the vendor count, or the filed diluted count when that is within 0.55–1.8× the
      vendor count.
    - A departure with `shares_reason` is never excluded; it is annotated instead.
    - The acceptance replay expects both L2 EZPW samples usable.
  - **S3 §5.11, model-visible (the updated draft, `de6d8eef…`).**
    - The default share count is vendor × basic EPS ÷ diluted EPS from the latest profitable filing, when that
      factor is at least 1.05; otherwise the vendor count.
    - A warning, and a required reason, when the vendor count is more than 10% from the EPS-implied basic count.
    - The reference uses the same basis.
    - It changes the default for 22 names.
  - **A/B bars re-set.**
    - Both arms carry S2b.
    - B-2 to B-4 compare Base equity values, not per-share values.
    - The new B-9 checks share counts against the default or a reason.
    - EZPW stays as the test of the new default.
  - **Carried.** Every production verdict on the 22 diluted names so far used basic counts, 5–50% high per share.
    S3 fixes it; the depth sweep stays paused.
- **Step 2 committed: `dc68146` (reviewer APPROVED, no code defects; 1290 tests).**
  - **Acceptance:**
    - 40 of 40 samples match the golden fill and provenance;
    - the 22-run replay equals `expected_s2_diff.json`.
  - **Carried to S3** (in the updated draft, `d0d54923…`):
    - `shares_basis` is redefined;
    - one function reads the snapshot for both paths;
    - a numeric `or` in the blend branch is removed;
    - a redundant path insert is dropped.
  - **For any revision-15 years 3–5 mark.** Read `years35_capped_by_desk` and the requested paths: with the fill,
    the harness F5 flag cannot fire on a capped Base.
  - **S2b went to the coder** after step 2 was committed.
- **S2b committed: `ca7dd0c` (reviewer APPROVED after four fixes; 1303 tests).**
  - **Acceptance:**
    - a whole-book rebuild with 291 of 291 texts byte-identical and facts parity;
    - the 22-run replay shows no difference;
    - the L2 EZPW replay keeps both samples, annotated `desk_share_count_departure_with_reason`.
  - **Reviewer fixes:**
    - two unrequested `except` fallbacks removed; one scraped digits from any first cell;
    - flags limited to real departures (more than 1% from SECTION 2);
    - a harness field kept out of the model's scorecard whitelist.
- **S3 packages A and B went to the coder** from the S3 brief `168d26cc…`, which carries the reviewer's S2b follow-ups:
  - older sidecars are filled on read;
  - share candidates gain the default;
  - `dilution_in_bear` compares Bear with Base.
  Package C and PACK_REVISION 15 follow after review.
  - **Coder switch (05:58).** Gemini hit its quota before editing ("Resets in 1h49m59s", about 07:49 KST), and the
    tree was clean. Packages A and B went to Sonnet 5, the fallback coder, with the same scope.
  - **A and B built by Sonnet (~07:05), uncommitted, and sent to the reviewer.**
    - **Suite:** 1377 passed and **41 failed**. They are pre-existing tests of the retired calling convention; the
      brief says no existing test is edited, which contradicts the convention change. The reviewer rules on it.
    - **The 22-run replay** shows 0 differences.
    - **The census of 122 recorded desk calls:** 73 accepted and 49 refused. Most refusals are compute errors,
      because the default share count only exists once package C builds it. The census cross-check and the
      whole-book rebuild are still to do.
    - **Eight deviations** are listed for review.
  - **Reviewer ruling (~07:20): APPROVED WITH CONDITIONS; held, not committed.**
    - **The 41 tests are updated to the new convention, with a ledger.** Nothing is deleted or loosened, and the
      desk is not made backward-compatible: that would bring back the silent defaults V1 and V2 end.
    - **A+B is committed as a non-runnable checkpoint after the fix-up.** PACK_REVISION stays 14 until C. The
      census and replay run now; the whole-book test and the A/B run after C.
    - **The reviewer fixed 10 defects, with 12 tests.** Among them:
      - R1 on small share counts;
      - R5, R6 and R9 now use the harness's exact tolerances;
      - the order refusal's wording;
      - R1b made live;
      - the `cash_flow_life` schema type set to string, safe for Ollama's tool parser;
      - the share flags measured against the share default.
    - **Sonnet's DEFAULTS-reader fallback is rejected.** §5.2 is rewritten as one fact per line; C builds the renderer
      and reader together.
    - **Not done by the coder, and undeclared:** the §3.8 retirements. They are in the fix-up order
      `brief_s3ab_fixup.md` (`54015de3…`), which went to Sonnet at 07:25.
  - **Fix-up done and approved (~08:30): checkpoint `bf95182`, NOT runnable until package C; PACK_REVISION stays 14.
    1433 tests pass.**
    - The 41 tests of the retired convention are updated with a ledger; no assertion is loosened.
    - The §3.8 retirements are done.
    - The 22-run replay shows 0 differences.
    - **The census of the 119 recorded desk calls**, on each run's own pack facts (the reviewer's corrected version;
      the coder's used the wrong facts file):
      - 78 accepted and 41 refused, of which 5 are `base_cf_reason`;
      - on the 39 desk-backed answer calls, 1 difference, classified (v), and 0 unclassified.
      - R2 accepts all 90 calls whose Base is within 2% of the printed default.
    - **Reviewer fixes:**
      - a conditional `pytest.skip` turned into a failure;
      - S2's blend rule no longer applies to revision-15 answer runs. A blend is never the answer, and §5.12
        carries the blends-only case to package C.
    - **S2c (the gate fix) went to the coder at 08:30,** before package C.
- **L2a, the E17 desk-closure probe (EZPW's frozen pack, `max_model_calls=2`):**
  - seed 1002 is informative and passes: the desk closed at call 12, 0 research calls followed, and the memo was
    written on the model's own turn 11.3 minutes later. The recorded revision-12 closures made 14, 24, 4 and 8
    calls;
  - seed 1001 used only 1 desk run, so it is not informative;
  - seed 1003 ran after ASTH, as the brief requires, and **passes**: the desk closed at call 12, 0 research calls
    followed, and the memo came 6.7 minutes later on the model's own turn. **L2a: PASS** (informative 2 of 3).
- **Operator rulings (2026-09-28 morning):**
  1. **Mines and oil and gas stay blocked** (gate v5 reason 16 is confirmed).
  2. **Equipment leased to others counts as capex** (the screener capex rule is confirmed).
  - **Asked about the names without a street fence.**
    - Of the 176 book names, 6 have none:
      - MU has 46 analysts, but one $361 target against a $1,545 median makes high/low 6.1, over `_sane`'s limit of
        6, so the whole band is rejected. That is a design defect, to fix with a band that resists outliers;
      - MOG-B's targets sit under the class A ticker, a mapping defect;
      - CIX, NVEC, NHC and JOE have no targets in the data.
    - Under gate v6 they are valued but not actionable.
    - The operator's answer is pending, after the explanation.
  3. **C7, the charter trim: YES** (about 10:30).
     - Remove the five contradicting charter sentences, shorten the memo specification and rename the pack sections.
     - This is a model rebuild to a new tag. v31 is kept for rollback.
  4. **Fix MU and MOG-B: YES.**
     - MU: a fence band that resists outliers.
     - MOG-B: map a share-class ticker to the primary class's analyst data.
  5. **Missing consensus: "analyst consensus is a valuable reference, but just because there are none shouldn't
     mean we should throw it all away, we just need to be careful with the ones missing such data."**
     - **Adopted:** a data FAILURE (fetch failed, record missing or stale, point-in-time) stays blocked, because it is
       a system error.
     - **Genuine absence of coverage** (the vendor answered: no targets or no estimates) becomes a CAUTION tier, not a
       block:
       - capped size;
       - a stricter margin of safety;
       - a substitute sanity check from the company's own or sector multiples, by fixed rule;
       - a loud annotation.
     - This refines S2c's policy. It needs the data layer to record failed fetches separately. The design is with the
       reviewer.
  6. **Phase 6 on hold (~10:55): "hold until we fix phase 4. Don't force quit the current background tasks but book it
     for later."**
     - Booked in STATUS under Phase 6:
       - the production enrich refetch and schedule;
       - the production merge with gate v6;
       - the caution tier (moved here from the reviewer's current task);
       - the remaining capex parts;
       - the cloud-backstop fixes;
       - Kelly sizing.
     - The reviewer's scope is now Phase 4: the fence band (MU), the share-class mapping (MOG-B) and the charter trim.
- **Briefs F and D (reviewer, ~11:10).** The order is C → F → D → v32 create and digest checks → the A/B → the
  final test.
  - **F, `brief_fence_band.md` (`eea3bf56…`), gate v6 unchanged.**
    - The target band is anchored on the median: a target more than 3× from it is pulled to 3×, and more than 6×
      means a bad record and no band.
    - Over the 291 names only MU changes: it gains a fence of $234–$4,000. No fence is lost, and the corrupt ATAT case
      stays rejected.
    - MU's pack also stops presenting a $6,207 consensus-implied value, 5.8× price, as "used".
    - MOG-B takes MOG-A's targets scaled by the price ratio. The share classes need both the same CIK and the same
      name; 5 names, and only MOG-B lacks targets.
    - A stale openbb band no longer shadows a fresh enrich band.
  - **D, `brief_charter_v32.md` (`e17b4edb…`): charter v3.2 and the rename.**
    - Six contradicting charter sentences are rewritten, including the retired `coe_source`.
    - Part II's memo goes from 20 entries to 13 sections; the conviction rubric and the moat scale are kept.
    - Pack blocks are renamed `DATA n`, so the memo keeps `SECTION n`.
    - New model tag `rs2-analyst-deep-mtp5-v32`, created from LF text, with a system-layer pin of `04894e6c…`. v31 is
      never overwritten.
    - Two Phase 4 defects fixed in D:
      - the TASK and tool text still said "use SECTION 2's count" against the §5.11 share default;
      - the share-citation regex accepts only "SECTION 2/6B".
    - **A/B arms:**
      - r14 is revision 14 with v31;
      - r15 is the D commit with v32;
      - an attribution arm (F with v31) runs only where a bar fails.
    - The final test's draw file pins v32 and its digest. Production `depth_model` is unchanged until the operator
      rules.
  - **Phase 6 coverage notes are booked, not designed** (`phase6_coverage_notes.md`). No Phase 6 item blocks the A/B
    or the final test.
- **Left for the operator:**
  - C7, trimming the memo in the charter;
  - C10, the display-only fields;
  - C4: the Kelly size sits at its 24.75% cap in 53 of 85 outputs. This is Phase 6 sizing.
- **Observed during the battery: the HTTP 500 is a thinking loop that fills the window (Ollama log, read ~23:15
  KST).** Not a battery result.
  - **ASTH sample 1, turn 3.** It generated exactly its `num_predict` cap (60,427 tokens) in 19m28s, ending at
    98,135 of the 98,304-token window. Ollama then answered 500.
  - **The same signature as the draw's DLTR sample 1** (03:53 KST, 18m39s).
  - **The speed points to repetition.** Generation ran at 52 tok/s, against 39 on normal turns, with a draft
    acceptance of 0.85. MTP drafts accept that well only on repetitive text.
  - **F1 treated it as a length stop,** and the harness forced the report with full thinking. The sample is scored
    under the existing rules, and the rescue is reported.
  - **To diagnose after the battery:**
    - why the model loops in one turn;
    - whether the 500 comes from Ollama's parser meeting a cut-off output, where a length stop was expected;
    - whether the rescue loses the research the turn was doing.
  - **Timing.** Samples take 31–64 minutes; wall time is generation, and prompt processing is 50–150 s per sample.
    EZPW's samples generated 150k and 128k tokens, against the draw's MO at 81k and 96k. The battery now looks set
    to end around 09:00–10:00, not 05:00.
- **Observed during the battery (not ours).** A GitHub Actions job on this PC's self-hosted runner started at
  19:35 KST: stock-screener `schedule-data-fetch.yml`, fetching from Yahoo.
  - Correction (~22:35 KST): this is the routine self-hosted fetch, which runs Sat/Sun at 19:35 and Mon–Fri at
    23:35 KST, as recorded in this file's tooling notes. Its trigger shows as `workflow_dispatch`. It is not
    stopped, and nothing needs cancelling.
  - Retest prep must not run during the fetch windows, the same rule as for battery prep.
  - The battery's pins are unaffected. screener-publish is still at f62d164, and the check before each name
    passes.
  - Each battery name's pack is read for fetch failures when it is scored.

**Universal valuation design (Fable, ~07:05; revision 11, not 10; not yet built).** This replaces
withdrawn item 6. Nothing in it uses an industry label.
- **Through-cycle base: a printed line and a required reason, never a default.** The company's own
  record prints: the owner-earnings margin's min, median, max and the current percentile, over all
  held years (at least 8). The through-cycle base is the median margin × the fiscal-year base
  revenue. `base_cycle_reason` is required when the base sits above the company's own
  80th-percentile margin.
  - This is the universal test. AMD, FIX and APH trigger it and can answer with filed evidence;
    FSM, GPOR and AU trigger it and cannot.
  - A default would force mean reversion on real improvements such as AMD's: the F2 failure, which
    the E-audit counted 13 times.
- **A maintenance floor on the base: owner earnings deduct max(capex, depreciation).** It uses a
  depreciation proxy (capex − Δppe_net), because the D&A tag combines depreciation with
  acquired-intangible amortisation. Where the proxy or the capex history is missing, the floor is
  "not available", never a default.
- **Finite life.** The desk supports `finite_life_years` (an annuity, no terminal) for any analyst
  who declares it with evidence, such as a reserve statement.
- **Shadow legs only** (printed beside Gordon and exit, never primary until ruled):
  - the value-driver terminal, NOPAT × (1 − g/RONIC);
  - a fade of excess returns to the cost of capital.

  Adopting either would collapse terminals to about 10–12× (the F4 failure) and re-base the model
  on NOPAT. That is a doctrine ruling for the operator, with whole-book numbers.
- **Contract.** New fields `base_cycle_reason`, `maintenance_reason` and `finite_life_reason`.
  Stamps `base_vs_throughcycle`, `margin_percentile_own`, `maintained_base_ratio` and
  `roic_median_own`. A1 flags `base_above_own_record_without_reason` and
  `capex_below_depreciation_without_reason`.
- **Missing data.** "Not available — <input>" plus a stamp; never a default or a silent weaker
  fallback.
- **Consistency note for the operator:** the screener's P3.7 uses industry-specific earnings
  windows, which puts it on the other side of the "no industry labels" rule. The own-record
  statistics above are the per-company version and could later replace it.

*Pre-registered whole-book criteria for the universal design* (fixed now; every book name with at
least 8 years; no GPU).
- **Buckets.** Own-record margin percentile of the latest year (≤50, 50–80, >80). ROIC record:
  years above the COE anchor (0–3, 4–7, 8+). Sector is for reporting only.
- **C1. Through-cycle / current base.**
  - The median ratio in the ≤50 bucket lies within [0.90, 1.25].
  - The median ratio in the >80 bucket is below 0.75.
  - The ratio is monotone across the buckets.
- **C2. No hidden industry choice.** Within each percentile bucket, every sector median lies within
  ±0.15 of the bucket median.
- **C3. Steady compounders** (8+ years of ROIC above the anchor, margin coefficient of variation
  below the book median): at least 80% have a ratio within [0.85, 1.15].
- **C4. Maintained / current base.**
  - Exactly 1.00 wherever capex ≥ the proxy.
  - Median within [0.6, 0.95] where capex < the proxy.
  - Names whose inferred amortisation exceeds 30% of D&A keep a ratio of at least 0.9.
- **C5. Shadow legs** (report only).
  - Value-driver / Gordon ≤ 1 where ROIC ≤ the anchor.
  - Within [0.85, 1.0] where ROIC > 2× the anchor.
  - A C2-style sector test at equal ROIC bucket.
- **C6. Named names.** Each (b)/(c) name lies within its bucket's 10th–90th percentile (n ≥ 10).
  FSM, GPOR and AU are reported and set nothing.
- **Fail on any criterion:** stop and diagnose before a new draw.

**Revision 10 check (Fable): no industry-specific choice.** One filer-type effect is labelled: the
guidance-range anchor for Bull and Bear comes from 8-K Item 2.02, which 20-F/40-F filers do not
file, so they fall back to "your own range, with a reason".

3. **Search source repair (E17 A1): the orchestrator's recommendation is accepted.** It is not
   applied on its own; it ships with E17's filtering and paging, so yandex is never the only general
   source without a fallback.

**GPOR s2: a new failure mode.** The model spent its entire first-turn output budget thinking, and made
no tool call of any kind: no research and no desk. The harness forced a report, the report was also
cut off and rescued, and its value was computed by hand. It is flagged (`desk_not_used`,
`iv_not_desk_backed`, `scenario_not_desk_backed`) but still `usable=True`, so it enters the band and
the verdict. With the three report truncations (UGI s3, LAMR s1, GPOR s2), this points at the
per-turn reasoning budget. With Fable: whether a sample without desk calls should count as usable,
and the sound fix.

**GPOR, joint review (Fable, ~05:00).**
1. **A sample with no desk call is not a usable sample. Today it is counted.**
   - `consensus_valuation.py:2096-2099` flags `desk_not_used` and `iv_not_desk_backed` but leaves
     `plausible: True`. The sample joins the band, the median (`$417.46`) and the spread.
   - The medoid selector already refuses such a sample, so the harness half-treats it as invalid.
   - **Fix after (b).** Treat it like `scenario_order_violation`: the sample stays in `runs` with its
     IV and flags, and is excluded from `n_basis`, the band, the median and the spread. With one
     basis sample, the existing `single_sample` gate reason makes the verdict non-actionable.
   - **Scored both ways:**

     | GPOR | usable | spread | pass |
     |---|---|---|---|
     | as pre-registered | 2/2 | 3.7% | ✓ (hollow) |
     | under the desk-backed definition | 1 | — | ✗ |

2. **Root cause of the truncations: the context window (81,920), not `NUM_PREDICT` (65,536).**
   - Every length-capped turn in the batch stopped at the window. GPOR s2 turn 1: 28,581 prompt +
     53,338 generated = 81,919.
   - Across 24 (b)+(c) samples, first-turn generation has a median of 29k tokens (range 12–53k).
     4 of 24 samples hit the wall.
   - The forced-report turn runs without tools at low effort (`analyst_tools.py:1044-1050`), so the
     desk cannot be reached from it.
   - **Fix after (b)**, tested on GPOR s1/s2:
     - Cap tool turns at 32k output.
     - On `done_reason: length` with no tool call, one recovery turn with **only**
       `run_financial_model` enabled: "call the desk with your three scenarios now". Then the report.
     - Report-turn reservation: if `ctx − prompt_tokens < 40k`, compact the tool history to headers
       first.
     - The medium-vs-xhigh test reports the truncation rate and first-turn tokens.
3. **GPOR is the cleanest demonstration of the perpetuity gap.**
   - s1 is pinned exactly: Gordon leg, no exit multiple, 8.11% anchor.
   - On the same base, path and anchor, a flat annuity with no terminal gives:
     - 15 years: **$164/share, the price**;
     - 10 years: $128;
     - 20 years: $189.
   - The desk's perpetuity gives $410, with 67% of it in the terminal. GPOR is priced as about 15
     years of current cash flow, which is its stated drilling inventory.
   - **Correction to the E14 note:** 2026 all-in capex is $430M + $140M = $570M, *above* the vendor's
     $528M. The base is not understated on capex; the terminal is the whole gap.
4. **Fence gate.** $417 sits inside the fence [$84.55, $460], so reason 10 does not fire. MoS +162%
   fires reason 11, and under item 1 `single_sample` also fires.

**Also, after (b):**
- Add `bear_above_price_without_reason` (an E8 contract requirement) to A1, stricter only.
- Carry `LOW_EFFORT_RESCUE` into the results table.

**FSM: every pre-registered mark passes, and the value is not credible.**
- **The marks.** Spread, direction, A1 and A2 test consistency, contract compliance and information
  capture, not correctness. FSM shows they are necessary but not sufficient, as E7 already said
  ("the real test of accuracy remains forward grading").
- **The cause is the depleting-assets gap pre-registered under E15.**
  - E15 withheld the reference, but the analyst built the same perpetuity from its own FCF: spot-gold
    cash flow, growing, with a perpetual terminal at the 8.93% anchor.
  - The market prices finite mine lives, West African jurisdiction risk and gold-price mean
    reversion.
- **The prediction failed.** The pre-registered expectation ("overvalued or hold if the analyst does
  its job") did not hold.
- **Real-money safety, open with Fable.**
  - The verdict carries the implausibility flags, but `verdict_depth.json` has no actionable or
    blocked field.
  - Which gate stops a half-size "undervalued" at 5.6× price from becoming a buy must be verified
    before Phase 6. If none does, that is a Phase 6 preflight blocker.
  - No risk now: KIS_HALT is on, DEPTH_PAUSED is on, and gate runs are unpublished.
- **Fail-fast.** Sample 1 was 2.5× the fence high, and no fail-fast stop fired. The question is with
  Fable.

**FSM, joint review (Fable, ~03:10).**
1. **No arithmetic error.** Both samples build the same perpetuity: spot gold ($4,358), the 8.93%
   anchor (Blume beta 0.90, no jurisdiction premium), 3.75% growth forever, and a terminal worth
   65–67% of the value. Three labelled data caveats, none a bug:
   - the E14 base includes discontinued-ops gains;
   - the vendor capex predates the Diamba Sud and Séguéla build;
   - s1's "ongoing operations" FCF excludes growth capex.

   The contract has no concept of a finite-life asset. The pre-registered expectation assumed one.
   **As run, A3 ✗ on both samples** (base 4.5× the street high). This is the "agree and be wrong
   together" case, and A3 is the mark that catches it. The write-up leads with that, not with the
   pass.
2. **Real-money safety: a confirmed gap, and a Phase 6 preflight BLOCKER.**
   - **The gate.** `depth_gates.assess` (v2) never reads `flags`, `mos_vs_base_pct` or the street
     targets. On FSM only `non_production_row` fired, from its gate-test provenance.
   - **What a production row would do.** Had the same verdict come from the orchestrator, it would
     be `actionable: True`. `track_paper_portfolios.depth_targets` (publish clone) buys every
     undervalued, actionable row at equal weight, and an un-halted KIS would follow.
   - **Fix.**
     - Stamp `street_fence {low, high, n_targets, asof}` on every verdict at write time, from
       `valuation_backbone._consensus_band` with the fail-fast's 1.10 discount and 0.5×/2×.
     - Add two `assess` reasons: `outside_street_fence` (an undervalued call above the fence high,
       or an overvalued call below the fence low) and `mos_beyond_150pct`.
     - `GATE_VERSION` becomes 3. A row without a fence gets an information flag, never a gate.
   - **Tests.** FSM gets both reasons; the seven other (b) records and AMD/FIX get neither (all sit
     inside their fences).
   - **P6.1 preflight gains:** "assess reads the fence; consumers honour actionable on origin/main".
   - Chain questions are read in `screener-publish`. The dev checkout's consumers lack the
     actionable gate.
3. **The missing fail-fast is by design.** `--failfast-street` is a `consensus_valuation` CLI flag
   for measurement runs; production annotates instead of stopping. The defect was that the
   annotation had no consumer, which item 2 fixes.
4. **Depleting assets (after (b), on a new draw).** Industries the screener classes as
   `commodity_cyclical` (metals & mining; oil & gas E&P) get:
   - **Terminal:** a reserve-life annuity with no perpetuity. `finite_life_years` comes from
     reserves in the filings; default 10 years with a flag.
   - **Base:** the P3.7 mid-cycle base, plus sustaining capex ≥ D&A where it is filed.
   - **Discount rate:** a stated jurisdiction premium through `coe_source: own`.
   - **Reference:** the finite-life form.

   Checked on s1's flows: a 12-year annuity at spot gives about $27; +300 bp gives about $42;
   finite life plus a mid-cycle gold deck (~$3,300) lands at $14–16, near the street's $14.50.

### Harness fixes after (b) (2026-09-26, joint rulings with Fable)

These change harness behaviour, not what the pack tells the model, except where marked. Branch
`review-2026-09/phase-4-pack` in the rs2-local worktree.

**1. A sample with no desk calculation is not a basis sample** (f66302d, completed in 41a2027).
- A sample flagged `desk_not_used` or `iv_not_desk_backed` stays in `runs` with its IV and flags.
  It is left out of the band, the median, the spread, `n_basis` and the two-sample early stop.
  With no desk-backed sample there is no basis.
- `consensus_valuation` stamps `basis` on every run. `band_verdict` reads that stamp; before
  41a2027 it re-counted the samples itself, so a desk-less sample still set the verdict row's
  `n_basis`, band and flags. An excluded sample shows on the row as
  `desk_less_sample_excluded:N`.
- GPOR (b) under the rule: one basis sample, so `single_sample` makes it non-actionable.

**2. Gate v3** (41a2027). `GATE_VERSION` 3.
- **The fence.** `valuation_backbone.street_fence` computes the fail-fast's fence: 0.5× the lowest
  and 2× the highest analyst target, each discounted a year at 10%.
  - `stamp_and_route` stamps it on every row as `{low, high, n_targets, asof, age_days, source}`.
    `asof` is derived from the band's age.
  - A missing or stale band gives no fence (as in the fail-fast), and the row carries the
    information flag `no_street_fence`, never a gate.
- **New `assess` reasons:**
  - 10 `outside_street_fence`: a buy above the fence high, or a sell below the fence low;
  - 11 `mos_beyond_150pct`;
  - 12 `desk_not_used` on a basis sample (guards rows from before rule 1);
  - 13 `low_effort_rescue` on a basis sample.
- **On the saved (b) verdicts:**
  - FSM gets reasons 10 and 11.
  - GPOR's saved row gets 11, 12 and 13: it predates rule 1, so it still carries `desk_not_used`
    and `LOW_EFFORT_RESCUE`. Re-derived under rule 1, it gets `single_sample`, 11 and 13.
  - AU, a hold, gets 11.
  - ADI, APH, LIND, LAMR, UGI, FIX and AMD get none.
- **Not done:** the cosmetic `mos_bucket` change. Fable called it cosmetic once the gate exists.

**3. The context window** (8cdb96c). Data: 26 samples, 216 turns with per-turn metrics.
- **No flat per-turn cap.** 17 turns generated more than 32,768 tokens, and 15 of them were
  healthy: 8 ended in tool calls and 7 were complete reports. A cap would have cut 12 of 26
  samples. The window already returns control; all 5 length stops came back as `done_reason:
  length`.
- **Desk-only recovery** (GPOR s2).
  - **Trigger:** a tool turn hits the window with no tool call, no deliverable report and no desk
    result yet in the sample.
  - **The turn:** one turn with only `run_financial_model`, think low, `num_predict` 16,384, and
    this frozen text:

    > Your previous turn ran out of room before any tool call. Do not deliberate. Call
    > run_financial_model once, now, with Base, Bull and Bear: the base you declared or the pack's
    > OWNER EARNINGS default; Base years 1–2 from SECTION 8's consensus EPS growth and the printed
    > years 3–5 fade; Bull and Bear years 1–2 on the consensus EPS high and low; the COE ANCHOR, the
    > terminal-g anchor, 5 fade years, the DEFAULT EXIT MULTIPLE or none; the Bear rate +150 bp.
    > Nothing else in this turn.

  - **After it:** one retry if the desk rejects the call, then the existing forced report.
  - **Stamps:** the sample records `desk_recovery_used`; the verdict flags `DESK_RECOVERY` and, via
    the forced report, `LOW_EFFORT_RESCUE` (gate reason 13). The scorer reports recovered samples
    separately, because a low-effort call on the printed defaults is a copy of the reference, not
    judgment.
  - **No desk result is a narrowing of the ruling.** A sample that already has one goes straight
    to the forced report, which can cite it, as GPOR s1 did. The recovery would otherwise replace
    researched scenarios with the pack's defaults. Fable confirmed this narrowing.
  - The cut turn's thinking is not injected (Fable: its tail is mid-computation and would anchor
    the recovery on the unverified number).
- **The essay** (UGI s3, LAMR s1).
  - 6 of 85 desk calls carried a `sector_multiple_band.metric` over 1,000 characters, up to 30,523.
    The text stayed in every later prompt, and the desk echoed it into every scenario. In 3 calls
    that pushed Bear past the 12,000-character tool-message cut.
  - **Rules:**
    - Desk string arguments are cut to 300 characters before dispatch, recorded as
      `arg_truncated {field, original_length}`.
    - Every assistant tool call reaches the prompt with strings over 300 characters shortened
      ("[N characters omitted]"); the stored history keeps the original.
    - The desk echoes band low/mid/high and 80 characters of the label, and judges the full band.
    - A desk tool message leads with its scenario summary (name, probability, IV, Gordon and exit
      legs, implied g), then reverse DCF and Kelly, then the markdown report, then the details.
      Any cut of any tool message is recorded as `tool_result_truncated {chars, cut_at}`.
  - **Revision 10 addition, pending the operator's nod:** the `metric` schema text now reads "Short
    label, at most 300 characters". Tool-definition text the model reads falls under
    non-negotiable 7, and revision 10 has not run yet.
- **Report room.**
  - Every sample records `report_turn_headroom_tokens`, the window minus the prompt of the turn
    that delivered the report. UGI s1's 400 spare tokens would now be a number on the record.
  - When the next prompt would leave the report less than 36,000 tokens, older **page** notes
    shrink to headers, oldest first. Search and desk notes stay, since they are the evidence the
    report cites. The turn records `page_notes_to_headers`.
  - The wider reservation (all notes to headers) is deferred. Revisit if a sample on the new draw
    shows headroom under 4,000 tokens.

**4. Cloud arm (Phase 6 blocker).** `api_llm/deep_api_run.py` called
`select_medoid_scorecard(runs, med, price)` against the signature `(runs, price, eff_tol)`. So
`eff_tol` received the price (every run "converges"), and margin of safety and direction were
measured against the median instead of the market. Fixed in 68c33d0 (price by keyword). A static
test checks that every caller outside the owner module passes everything after `runs` by keyword.

**5. APH basis** (2cda9cb, e1db261).
- `position_basis` is the majority of the valid declarations across basis samples; the medoid
  breaks a tie. A tie the medoid cannot break gives none.
- Each invalid declaration keeps its `position_basis_mismatch` flag.
- When the basis comes from a sample other than the medoid, the row carries that sample's
  momentum block and `position_basis_source_sample`. The medoid's own view and timing stay on the
  row as `medoid_momentum_view` and `medoid_entry_timing`, so the mixing is visible.
- On the saved APH record: hold + momentum from s1 at half size.

**Fable's review of items 1–5 (2026-09-26).**
- The recovery narrowing (item 3) is confirmed.
- Gate reason 13 on a rescued basis sample is confirmed: the recovery keeps the measurement, never
  a trade.
- **Phase 6 notes:**
  - The resume protocol re-queues `low_effort_rescue` verdicts automatically instead of leaving
    them parked. At the batch's 4-of-24 rescue rate, about a sixth of names would otherwise wait.
  - The rescue rate is reported per draw as a health metric.
- The momentum block from the source sample is agreed as the lesser evil, with the medoid's own
  fields kept on the row.

### The new draw, pre-registered (Fable's marks, 2026-09-26, before any pack preview)

**Draw rule.**
- **Pool:** seed 20260927 over the nominated book, minus every design-touched name: the
  amendments' list, the 20 audited AI leaders, the eight (b) names, AMD, FIX, DXC and GEV.
- **Fast grower:**
  - current-FY consensus EPS growth ≥ 30%, with at least one quarter of the current fiscal year
    inside the TTM;
  - a usable reference (growth or levels method);
  - ≥ 3 next-FY EPS analysts;
  - ≥ 8 years of history.
- **Steady name:** |g₁| ≤ 10%, with the same data conditions.
- **Runs:** two samples each on the revision-10 code. A sample that used the desk-only recovery is
  re-run once: the recovery protects the measurement, not the mark.

**Per name, all must hold:**
- **Repeatability.** 2 usable, desk-backed, non-recovered samples; spread ≤ 15%; the same
  direction under the 10% rule.
- **A1.** Clean on both samples, including `bear_above_price_without_reason` and
  `terminal_g_off_anchor_without_reason`.
- **Base on the reference.** Base within ±15% of the reference, or `guidance_deviation_reason`.
- **The gate would pass it.** Both samples inside the street fence and under 150% MoS. The draw
  must not pass what gate v3 rejects.
- **A2.** The development pre-registered from the pack preview: the keyword rule plus a human read.
- **Process marks (E7 rule 5).**
  - Equity frame, or `wacc_reason`.
  - Exit multiple within 50 bp of the anchor, or `terminal_reason`.
  - Terminal g the same.
  - Bull and bear years 1–2 on the consensus high/low, or a reason.
  - Every reason read as substantive, not boilerplate (human column).

**Reported, not gated:**
- bull ≥ price or a reason, and bear ≤ price or a reason;
- bull and bear spreads;
- `position_basis` agreement;
- the old/E18 reference ratio;
- report headroom and first-turn tokens;
- research calls, repeats and truncations. E17 is not in this build, so time is reported, not
  scored.

**Draw procedure, made exact before any pool is computed (orchestrator, 2026-09-26 ~15:40 KST).**
- **Nominated book.** `nominated_tickers` in the publish clone's `factor_scores_dual_door.json`:
  135 names, generated 2026-09-23. It is the list the (b) hold-out was drawn from.
- **Excluded as design-touched.** Every ticker named in PHASE_4_AMENDMENTS.md,
  reports/PHASE_4_ERROR_AUDIT_SUMMARY.md or STATUS.md at the moment the pool is computed. That includes
  every name the whole-book diagnosis named, the 20 audited AI leaders, the (b) names, AMD, FIX,
  DXC and GEV.
- **Data conditions.** All three must hold:
  - the revision-10 pack (the code of the draw run) prints a CONSENSUS-IMPLIED VALUE line, growth
    or levels method: "not available" and "not used" (E15) fail;
  - `+1y` EPS analysts ≥ 3 in the enrich estimates;
  - at least 8 fiscal years in `fundamentals_history.json`.
- **Fast grower.**
  - g₁ is `consensus_earnings_growth()`'s current-FY EPS growth, at least 0.30.
  - q ≥ 1: at least one quarter of the current fiscal year inside the TTM. q is counted from the
    TTM record's `fy_leg_end` and `through`, and only when `fy_leg_end` is the latest filed fiscal
    year.
- **Steady name.** |g₁| ≤ 0.10.
- **Draw.**
  - Each pool is sorted alphabetically.
  - `rng = random.Random(20260927)`.
  - Fast grower = `rng.choice(fast_pool)`, then steady name = `rng.choice(steady_pool)`.
- **Data freshness.** Estimates are fetched on the day the pool is computed. The pool, the
  exclusion list and the draw are written to the scratchpad file `draw_20260927.txt` before any
  pack preview.

**Pass** = both names pass. A single failure is diagnosed, never re-drawn.

**What it measures and what it does not.**
- **Measures:** the E10–E13 pins, E18, gate v3 and the window fix, on names that touched none of
  the design.
- **Does not measure:** the research layer (E17) and the universal valuation item. Each has its
  own test.

**Scorer.** `scratchpad\score_draw.py` implements these marks. `score_retest.py` is kept unchanged
as the pre-change copy. A3's years 1–2 mirrors the harness exactly:
- ±15% on levels when the pack prints levels;
- [0.75, 1.33] on the growth ratio otherwise;
- it says which of the two applied.

The scorer is frozen before the draw runs.

### E18. The consensus reference's period bias (Fable, ADI joint review, 2026-09-25 ~23:00; to fix after (b))

**Fable corrects its own E10 ruling.** At E10 Fable said the TTM-base timing effect and end-of-year
discounting "roughly cancel". They do not cancel for fast growers.

**The mechanism.** The reference applies the full current-FY consensus growth to a TTM base that
already contains q quarters of that fiscal year. It therefore overstates the year-1 flow by about
(1+g₁)^(q/4):

| name | overstatement | reference as run | FY-consistent reference | effect on the call |
|---|---|---|---|---|
| ADI | +29% | $399 | ~$310–340 (0.82–0.89× price) | — |
| AMD | +35% | $510 (the (c) base) | ~$424–457 | direction unchanged: overvalued, momentum-eligible |
| APH | +26% | $88 | ~$75–81 | hold unchanged |
| LAMR | +9% | — | — | — |

The harness already showed the symptom: `yr-2 flow / consensus NI` read 1.26 on ADI's pinned path.

**ADI's split explained.**
- s2 followed the pin exactly, and the pin carried the +28% bias.
- s1 diagnosed the double count correctly, then under-corrected by about a quarter:
  - it used a cash-basis FY base ($3.957B, the column the pack mislabels "owner CF") with
    cash-flow growth of +28% / +21%;
  - its year-2 flow ($6.13B) is 22% below the consensus-consistent $7.7–7.8B.
- It is not a LAMR-type GAAP/adjusted artifact: year-ago EPS and the estimate are both adjusted.

**Fix, after (b), for every name, pre-registered and re-tested on the next draw.**
1. **Period-consistent reference.**
   - The base is the last full fiscal year's owner earnings (NI + D&A − capex, from SECTION 5).
   - Years 1–2 are the current-FY and next-FY consensus EPS growth.
   - The fade stays as now.
   - The value is computed at FY-end and rolled forward to the valuation date by
     (1+COE)^(months/12).
   - The EPS-levels method (LIND) gets the same treatment.
2. **Pin the level, not the rate.**
   - The pack prints the reference's year-1 and year-2 flows in $B, and the TASK says "reach these
     levels from whatever base you declare".
   - `years12_off_consensus_earnings` becomes a level check: the sample's year-2 flow against the
     reference's, within ±15%, whatever the base.
   - Under that check both ADI samples would have been flagged (0.78 and 1.28), with their reasons.
3. **Rejected.** Neither requiring a deviation to be desk-tested against the reference (reporting
   both legs does not reduce the spread) nor treating ADI's split as judgment variance (the pinned
   sample was wrong by construction).
4. **Offline first.** Recompute the references for UGI, LAMR, LIND, APH, ADI, AMD and FIX on the
   new basis, and publish old and new side by side. The runs as scored stand.

**Scope for the remaining (b) names.**
- FSM and AU already use a fiscal-year base (E14), so they are period-consistent.
- GPOR's year-1 growth is small (+6.2%), so its bias is small.
- Their E10 references are withheld anyway (E15).

(b) therefore finishes as it is.

**Other items, all carriable.**
- The SECTION 5 "owner CF" column is now costing: s1 cited it as owner earnings (see the LIND
  rename).
- The screener TTM extract lags a filed 10-Q by a quarter on ADI. A freshness line in SECTION 3
  would show it ("latest 10-Q on file vs latest 8-K").
- The conditional fade keys on FY2025's +16.9% (pre-acceleration), giving a 9.6% target.
- ADI common sense: at the 10.45% anchor the consensus path is worth about 0.85× the price. The
  street's $365–675 needs a hurdle of about 9% or a longer runway. The design's answer is
  "overvalued or borderline, ride at quarter", which the split reached by accident
  (high-dispersion quarantine, momentum ×2).

### E17. The research layer: loops come from a broken search source (Fable's design, 2026-09-25 ~21:00; not yet built. **Cause corrected and re-scoped 2026-09-27 ~22:00: see "E17 re-scoped" below the battery records.**)

**Asked by the operator** after rejecting both "close research after repeated notes" and "cut everyone's
budget": both reduce research, and research must stay as rich as it is.

**The evidence.** Two loops in 13 valuation samples:
- UGI s1: the transcript cut at 9,000 characters, then a masked URL retried five times.
- APH s1: 18 repeats of one Bing results page, 4–5 seconds apart and with no reasoning between them.

**Fable's root cause.** The search layer starves the model and then traps it.
- The SearXNG `bing` general engine returns bot-detection filler at the top score. I reproduced it:
  running-shoe pages for the APH query.
- Five engines are dead or time out.
- Only 58% of the batch's 462 search results share one content token with their query.
- The model went to Bing's own pages because the search results handed it Bing's navigation links.
- An identical request that always gets an identical short note is a fixed point. E16's note made the
  response shorter and even more identical.

**Design (the operator's constraint: no research cut, no global budget cut):**
- **A1.** SearXNG config: turn off `bing` general (keep `bing news` and `reuters`), drop the dead
  engines, and add bot-tolerant general engines. Test first on a separate instance against the 77
  saved queries.
- **A2.** `search_web` requests 20 results, drops ones unrelated to the query, returns up to 8, and
  adds each result's date and engine.
- **A3.** A near-duplicate search returns the next page of results.
- **B1.** A search-engine results URL passed to `fetch_page` runs through `search_web` instead.
- **B2.** `fetch_page` gains a `part` argument; a repeated fetch serves the next unread part. Once
  every part is served, the note lists the sample's unopened results.
- **B3.** A new tool, `find_in_page(url, pattern)`, returns passages from a page already fetched.
- **B4.** Pages are requested with `Accept-Language: en-US`.
- **B5.** The repeat note shows the repeat count and that list.
- **C.** A third identical request on an exhausted source is refused for that source only. The
  25-call budget stays the only overall backstop.
- **Also:** the E11 furniture list gains "advertisement", "top stories" and "return to homepage".

**Tests before any GPU:**
- replay the two saved loops through the new tools;
- run A2's filter over the 462 saved results;
- run the 77 queries per engine;
- unit tests.

**Timing.**
- A1: between names, after ADI, only with the operator's approval and a passing test.
- Everything else: after (b).

**A1 test, pre-registered (operator approved "test it now and apply after ADI if it passes", ~21:10).**
Written before any test query ran.

*Method.*
- **Queries.** The test set is every `search_web` query recorded in the (b) sample snapshots so
  far.
- **Baseline.** The results production actually served during the batch, read from those
  snapshots. Production is not re-queried: ADI is researching on it.
- **Candidate.** A separate SearXNG test instance (port 8889) with the proposed engine set, queried
  through the same `search_web` code path (LOW_TRUST filter, top 6). Queries are spaced a few
  seconds apart.
- **Relevance.** A result is relevant when its title, snippet and URL share at least one content
  token with the query. The tokens come from the harness's `_title_tokens`, excluding stopwords,
  numbers and tokens of two letters or fewer.
- **Engine choice.** Candidate engines are probed one at a time first. An engine that refuses
  automated access (CAPTCHA or "access denied") is not used, keeping the header's rule that such
  refusals are respected.

*Pass: all four must hold.*
1. The share of relevant results is at least 15 points above baseline.
2. The mean number of relevant results per query (top 6) is higher than baseline.
3. Queries with 0 relevant results in the top 6 are no more than baseline.
4. Median latency per query is at most 1.5× production's measured latency. Production's latency is
   taken from 3 spaced queries.

*If it fails,* nothing changes before the end of (b).

**A1 test result (~21:50): FAIL, on 1 of 4 criteria. Not applied during (b).**

*Per-engine probe* (test instance, 10 spaced queries each):
- `bing` general answered every query, but **0% of its results were relevant** (shoe reviews,
  legal FAQs).
- `yandex` gave 100% relevant results.
- `zapmeta`, `wiby`, `google` and `mwmbl` answered with almost no results.
- `gabanza`, `mojeek`, `startpage`, `qwant` and `yahoo` refused or were suspended. So did
  `duckduckgo` (CAPTCHA), `yep` (403), and `brave`, `presearch` and `dogpile` (failed).
- `abcnyheter` timed out on 8 of 10 queries.

The only working general engine is yandex.

*Comparison:* candidate = yandex general only, against the baseline production served in (b), over
73 unique queries.

| criterion | baseline | yandex only | result |
|---|---|---|---|
| 1. relevant share | 51.8% | 98.1% | ✓ |
| 2. mean relevant in the top 6 | 3.11 | 5.67 | ✓ |
| 3. queries with 0 relevant | 1 | 2 | **✗** |
| 4. median latency | 4.0 s | 1.0 s | ✓ |

The two zero queries are long, quote-heavy searches:
- LIND's 8-K outlook search;
- UGI's KKR board statement.

Yandex returned nothing for both. Production had returned 6 junk results for each ("is it illegal to
open someone else's mail", USDA contract records). The baseline's single "relevant" hit for the UGI
query was a USDA contract page, which is a false positive of the token metric. Under the
pre-registered rule this is a fail, and nothing changes during (b). This also keeps all eight names
on the same search layer.

*After (b):* A1 goes in with A2 and A3 (filtering, paging), so an empty yandex result pages or
falls back rather than returning nothing. Relying on yandex alone for general search is a single
point of failure, and E17 must handle it (a fallback engine, or the empty case) before going live.
The test instance `searxng-test` (port 8889, `scratchpad\searxng-test\`) is kept for the E17 build.

**APH, joint review (Fable, ~21:30).** One harness defect changed the published outcome.
- **Basis resolution.** `depth_pipeline.py` resolves `position_basis` from the medoid's declaration
  alone. APH s2 (the medoid) declared `value`, which is invalid at hold, so the basis became
  `none`. s1's valid `momentum` declaration was ignored.
- **What it should have been:** hold + momentum at **half** size. The published result is hold +
  none at quarter, which Phase 6 would not buy.
- **Fix after (b), with a test on this verdict record.** Resolve the basis from the *valid*
  declarations across usable samples (majority; the medoid breaks ties). Keep the flag for the
  invalid one. Phase 6 sizes holds from the basis cap, never from Kelly.

Also recorded:
- **s2's "undervalued" at 1.061×** is a literal label. The pack never states the 10% band, so it
  goes in the human read as "label without the band". The fix is one sentence in the field
  description.
- **Momentum date.** The price-action block is dated 09-17 against a 09-24 T0, and z +0.535 sits
  3.5 bp above the E5b threshold. Stamp the momentum date beside the eligibility result.
- **Held cleanly.** E12 and E13 held with 16–17 analysts.
- **s1's `FORCED_REPORT`** came from the Bing loop. Its values were settled before the loop and
  match s2.

**LIND, joint review (Fable, ~16:35): consistent with the design and the pre-registered marks.**
The two samples agree on everything the contract pins and disagree only where it leaves
judgment.
- **Base.** s2's "other" base ($0.041B with 0% in year 1) is the same flow as s1's default
  ($0.012B with +241.7%). Every year's flow is identical, and so is the value. With the EPS-levels
  method, base and year-1 growth are jointly determined; the levels are what is pinned.
- **The $19 value against the street's $29–40 is a growth call, not a rate call (unlike LAMR).**
  - The consensus path at the 10% anchor is worth $19, about 10–11× FY26 EBITDA after $0.4B of net
    debt.
  - The street's range needs 16–18× current EBITDA, or earnings well beyond FY2027 consensus.
  - A 100 bp change in the anchor moves the value about 15%, which does not flip the direction.
- **Bull and bear (73–76% apart).** There is no consensus range to anchor them (1 analyst).
  - s1's bull puts the deal, the guidance top and the 2028 launches into year 2, landing at $44.84.
  - s2's bull lands below the price, with a `bull_below_price_reason`.
  - Both bears are severe, which is real for a levered operator at an earnings inflection.
- **Quarter size on an overvalued call is the E5b momentum rule, as on AMD.**
  - Eligibility: z +1.72, 6-month +55%, −9.1% from the high, no regime shift down, revenue growing,
    base ≥ 0.5× price.
  - Contract: momentum basis, `buy_now` timing, dated evidence.
  - Sizing: MoS replaced by the basis cap, overvalued means quarter, Kelly 0.
- **Human read.** s1's `cycle_evidence` leans on "pricing at a decade high", which the charter
  says is not evidence alone; its dated fuel-shock indicator carries the requirement.

**Added to the after-(b) list:**
- **Degenerate consensus range.** Anchor bull and bear years 1–2 to the company's own filed
  guidance range (LIND: EBITDA $130–140M, revenue $830–860M) before the analyst's own paths.
- **Scorer, EPS-levels method.** A3 "years 1–2 within 25%" and `years12_ratio` should compare flow
  levels with the reference flows, not growth rates the reference declared unusable. Both LIND
  samples would read 1.00.
- **Rename a pack column.** SECTION 5's "owner CF [Arithmetic]" column (OCF − capex − SBC) becomes
  "cash basis", so "owner" has one meaning.
- **Explicit "none" reason.** The harness accepts an explicit "none" in
  `guidance_deviation_reason`.

**Sample count, operator decision (2026-09-25 ~13:55), recorded before any of the six names ran:**
- The remaining six names (LIND, APH, ADI, FSM, GPOR, AU) run **2 samples**, not 3, to save about 5 hours.
- The scoring rules already accept 2 samples, since the spread needs at least 2 usable.
- The cost: a single unusable sample fails the name's spread mark, and a 1–1 direction split counts
  against the 90% direction mark.
- LAMR kept 3. The switch used the same between-names method as E16 (`run_b4.sh`, `run_b_n.sh`).
- For production after the gate: 1 sample, plus a second only on an objective trigger. The
  triggers are an A1 flag, the fail-fast fence, being more than 25% off the reference without a
  reason, a truncated or unusable report, or being within about 3 points of the 10% direction line.
  This is to be pre-registered before use.
- Fable: with 2 samples the spread mark rests on two draws, and the 90% direction mark becomes
  "both agree". UGI and LAMR keep their three.

**LAMR, joint review (Fable, ~14:35): consistent with the design and the pre-registered marks.**
- **The year-1 deviation is real.** Consensus "+19.4%" runs from an adjusted year-ago EPS ($5.08)
  to a GAAP-like consensus; filed FY2025 is $5.78 including the one-time Vistar gain. The company's
  own FY2026 guidance is AFFO +8.1% and GAAP EPS +2–3%. Anchoring owner earnings to AFFO growth
  (+8%) is right. This is E10 as designed: a deviation with a stated, dated reason, inside the
  bands.
- **Human read (reported beside the keyword score).** s1 cites the Q4-2024 loss (correct). s3
  cites the Vistar gain and the GAAP guidance (correct). **s2 cites "Q4 2025 GAAP NI −$1M",
  which is wrong by a year**: it is Q4 2024. Same conclusion, one mis-cited fact.
- **Bull and bear.** LAMR has one EPS analyst, so there is no consensus range. All three samples'
  bull and bear are desk-backed Gordon legs at their own rates (21.93× base and bull, 16.65× bear
  at +150 bp), with `scenario_deviation_reason` present. The models read "5 analysts" (the revenue
  count) as the EPS count.
- **What decides the verdict.** It is a cost-of-equity call. At the 8.48% anchor (Blume-adjusted
  beta 0.80) the base is about $166, 18.9× guided AFFO, undervalued at half size. At 9.5%, a rate
  many REIT investors would use, the same paths give about $145, which would be a hold. That is
  the MRI anchor's job, not the analyst's.
- **The owner-earnings default understates a REIT.** $0.694B against about $0.89B of AFFO, because
  it subtracts growth capex. It belongs with the regulated-utility capex item already on the list.

**Added to the after-(b) list:**
- **Base-year check.** A data sanity line when consensus year-ago EPS and filed FY EPS differ
  (here 12%), so a distorted growth figure is flagged up front. The reference inherited the +19.4%
  and printed $188, about 13% above the guidance path.
- **EPS analyst count.** Print it beside the revenue count, since the bull/bear rule keys on it.
- **Truncations.** 2 of 6 samples so far (UGI s3, LAMR s1) were cut at about 24–25k report
  characters and rescued. This is a reasoning-budget pattern: measure final-turn thinking against
  report tokens across (b), and set the final-turn cap from that.
- **Q4 test.** The head-to-head (current UD-Q5_K_M against Q4 or UD-Q4_K_XL, on 2 names, same
  marks) also reports tokens per sample and the truncation rate.

**UGI, joint review (Fable, ~11:50): consistent with the design and the pre-registered marks.**
- **Base.** All three samples used the pinned path, the default base, the anchor rate and the equity
  frame. s1 published the 26.1× exit leg (0 bp gap); s2 and s3 published the Gordon leg. The base
  equals the reference by construction, so the 0.1% spread reflects the design and is not evidence.
- **Bears ($27.54 / $21.47 / $22.55).** All are desk-backed Gordon legs. s1 rejected the desk's exit
  bear ($31.77) because 26.1× at the bear rate implies 4.71%, which is E13 working. The 28.3% bear
  spread breaks down into:
  - the rate shock (+100 / +150 / +200 bp, all within the charter);
  - the years 3–5 paths.

  Years 1–2 sit on the consensus low in every sample (0.998 / 0.998 / 1.0), so E12 held. This is
  judgment variance of the right kind; it is recorded, and no fix is needed.
- **The KKR bid.** All three samples valued the standalone business and carried the unsolicited,
  non-binding $42.50 bid as a catalyst. Fable judged that right for today. The dates differ (s2
  08-07, s1/s3 08-18): secondary-source noise.
- **s3's continuation.** s3's report was cut off and then completed by the continuation step. Its
  contract parses, matches its last desk call, and contains no duplicated sections.
- **Common sense.** The answer is conservative, not generous. The owner-earnings default subtracts
  all capex ($0.875B against about $0.55B of D&A), so the base flow is half of consensus net income.
  For a rate-base utility that growth capex earns an allowed return.

**Added to the after-(b) list, for a new draw:**
- growth capex for regulated utilities (the mirror of maintenance capex for depleting assets);
- a TASK line for live public offers: state the probability and the expected value with and
  without the offer, and keep the verdict on standalone value.

### E6. Order and gate additions

- **Order.** E4.1 error audit before P4.2. E2 and E3 join the single pack revision (D2). E4.2 in
  the harness with P4.3. E4.3 after the Stage 1 battery.
- **Gate to Phase 5 adds:**
  - the battery's direction mix and theme mix reported against E1.3;
  - the reverse-DCF block present in every battery report;
  - the error-audit failure modes each mapped to a charter or pack change, or explicitly
    accepted;
  - the time-travel trial reported.

### E2 measurement — revenue growth base rates (orchestrator, 2026-09-24)

**Source.** The screener `fundamentals_history.json`, read from the refreshed publish clone:
about 6,900 current listings, fiscal years roughly 2014–2025. Each row is every (company,
start-year) with revenue at the start year and h years later.

**Caveats.**
- The sample holds survivors only, because delisted companies are absent. The rates are
  therefore biased upward.
- The window is one decade, which includes the AI build-out.

| h | revenue at start | n | share ≥10%/yr | ≥20%/yr | ≥30%/yr | median | p90 |
|---|---|---|---|---|---|---|---|
| 5 | < $1B | 10,586 | 46.9% | 28.1% | 17.4% | 8.9% | 46.8% |
| 5 | $1–10B | 6,052 | 26.7% | 6.8% | 2.2% | 5.6% | 16.7% |
| 5 | $10–50B | 1,641 | 17.2% | 4.0% | 1.5% | 4.3% | 14.0% |
| 5 | > $50B | 439 | 21.4% | 2.3% | 0.0% | 5.2% | 13.6% |
| 10 | < $1B | 2,223 | 40.3% | 19.4% | 10.7% | 7.2% | 31.0% |
| 10 | $1–10B | 1,316 | 18.4% | 2.4% | 0.5% | 4.7% | 13.1% |
| 10 | $10–50B | 370 | 10.0% | 2.2% | 0.0% | 2.9% | 10.1% |
| 10 | > $50B | 109 | 11.0% | 1.8% | 0.0% | 3.4% | 10.3% |

**Use.**
- The pack prints the row for the name's size, plus the conditional table ("given the growth
  just delivered") from the existing `tools/growth_persistence.py`, run on the same data.
- An analyst's stage-1 or fade growth above the p90 for its size needs dated, company-specific
  evidence (for example signed AI capacity contracts or backlog). It is not forbidden.
- The base rates discipline the forecast. They do not cap it.

## Revision 24: Muse as the analyst; no reference anchor; facts and population ranges (2026-10-16)

The work order is `PHASE_4_REV24_MUSE.md` (v2, 2026-10-16 07:04).

**The operator's direction (2026-10-15):** finish Phase 4, the AI analyst working properly, with Muse Glimmer, within the frozen
revision-21/22 design. No new system. The detour of revision 23 into a code-only system is recorded as an error in rev23 SPEC_rebuild AK.93.

**The defect census** (`rev23/defect_census.md`) found the baseline's skew (growth at 0.2–0.45× price, cyclicals and insurers at 2–3.7×)
came from two causes:
- A1: the analyst copied the reference;
- the formula's own defects O1–O3 and U1–U5.

**A finding during the R24.2 build** (branch `review-2026-10/rev24-muse`, commits `600be12`, `a8c10b2`): the briefing's **DEFAULTS
are the reference formula's own inputs.** Run through the desk unchanged, they return the CONSENSUS-IMPLIED VALUE to the cent in 16 of 16
saved packs, and within 1% in 9 of 9 accepted runs. Hiding the printed value therefore does not remove the anchor.

**Cross-check 18 and the operator's rulings** ("yes to both, go ahead", 2026-10-16 07:04):
1. **The reference is never shown to the analyst, before or after it commits.** The post-commit reveal (stage B) is **dropped**. The
   reference is kept only in the logs, as a benchmark for evaluating the analyst. This reverses the operator's earlier choice of (a), on the
   reviewer's reasoning: a reference with no demonstrated stock-picking value can only re-anchor.
2. **Modified option (iii):** the briefing gives **facts and population ranges**, not formula defaults for the long-run assumptions.
   - **Consensus years 1–2 are evidence,** not a fixed input. The analyst separates near-term earnings from normalized mid-cycle earnings and
     justifies the transition.
   - **Classification is per dimension,** never one forced global label: margin persistence, the earnings-cycle position and the growth
     trajectory, each from the evidence.
   - **Three levels of citation:**
     - an ordinary in-range choice needs a concise rationale tied to the facts and the population evidence;
     - an outlier needs a sourced, causal explanation of why the company differs from its cohort;
     - the buy or sell crux needs verified primary-source evidence (as revision 21).
   - **A plausibility gate on the whole implied trajectory:** tail assumptions and implausible implied outcomes are flagged, and override
     needs verifiable, causally relevant evidence. **The valuation is rejected, with a named reason, when the support is missing.** It is
     never silently clamped. There are no hard caps (no "never above the historical peak", no "never above 3–4% terminal growth", no forced
     zero for a shrinker), only mathematical consistency (terminal growth below the discount rate).
3. **Sequence:**
   1. an arithmetic audit of the desk (the operating-to-earnings margin translation traced through the default generator and the desk DCF; a
      unit test that each input moves cash flow as intended);
   2. building modified (iii);
   3. a **blinded six-stock ablation pilot** (the current briefing against modified iii; the population ranges with P50 shown against
      omitted; the reference hidden; each input vector frozen before valuation);
   4. evaluation on four separate dimensions:
      - clustering at the midpoint or a boundary, and sensitivity to harmless presentation changes;
      - run-to-run stability;
      - cash-flow plausibility, judged without the price or the reference;
      - the evidence for outliers and the crux.

      **No valuation-to-price targets;**
   5. expanding;
   6. the live paper record, graded by TRK-06 (the operator ruled past-date checks unnecessary).
4. **The population tables** (rev23 `priors_v5`, point-in-time vintages, including delisted firms where the records hold them) are audited
   for survivorship and look-ahead before use, and the audit is recorded.

### Revision 24 step 1: the desk arithmetic audit (2026-10-16 07:23; commit `f737115`, tests only: 55 pass and 8 strict xfails; suite 3,054 passed, the 42
known failures plus the timing flake, no new failure)
- **The decisive finding: the desk has no long-run margin of its own.**
  - It takes `margin_ratio` from the default generator's `margin_rule`, and its tool schema has no long-run margin input.
  - So no change to the briefing can move LITE's or LIND's long-run margin off zero.
  - Algebra: in `margin_rule` m5 cancels, giving `m_long = x_L + (1 − tax_L)(om_trend − om_L)`. The base year's earnings-margin wedge
    (interest, one-offs, a loss) is carried forever.
  - **Reproduced:**
    - LITE: OM_5 352%, `m_long` 0; the desk gives $271.20, the reference to the cent, with a terminal value of 0;
    - LIND: `m_long` 0; the desk gives $9.53, terminal value 0.
- **Defects in the desk's own path** (strict xfails):
  - **D2:** a fade of 0, or explicit rates that use up the fade, silently drops `margin_ratio`. LITE is worth $768.81 at fade 0 against
    $271.20 at fade 5.
  - **D3:** with a reference, `E5 = e5 + OE5 − oe5` is additive and can flip sign in Bear. Without a reference the same step is proportional.
  - **D4:** an unlimited terminal RONIC holds the starting RONIC through the fade, so "unlimited" is worth less than RONIC 10^6. The
    price-implied block then stamps a discontinuity the desk itself creates.
  - **O2a/O2b/O2c:**
    - an impossible implied operating margin is accepted without a stamp;
    - the clamp to 0 is silent;
    - a base-year one-off sets the long-run margin.
  - **Designed but silent:** a `terminal_ronic` below r is valued as r with no stamp.
- **The coordinator's rulings** (the arithmetic fixes, built in step 2):
  1. **The desk gets an analyst-chosen long-run margin:** `long_run_margin`, the earnings margin reached at the end of the fade. The desk
     applies it **proportionally** to each scenario's own year-5 earnings margin: ratio = long_run_margin ÷ the scenario's year-5 earnings
     margin. The analyst chooses it from the facts and the population `margin_retention` and `normalization` ranges, under design point 6's
     citation levels. `margin_ratio` from the generator no longer reaches the desk; the generator's `margin_rule` serves only the logged
     reference benchmark.
  2. **D2:** the long-run margin path applies whatever the fade length. With fade 0 it is reached in the terminal year.
  3. **D3:** year-5 earnings are always proportional (`E5 = e5 × OE5/oe5`), with or without a reference.
  4. **D4:** with an unlimited terminal RONIC, the reinvestment charge (g/RONIC) fades linearly to 0. Value is monotone in the terminal RONIC,
     and the price-implied block loses its self-made discontinuity.
  5. **Annotate, never silent:**
     - a `terminal_ronic` below r is valued as r **with a stamp**;
     - the reference generator stamps an implied operating margin outside [−50%, 100%] and any clamp to 0 (O2a/O2b) in the logged benchmark.
  6. Each fix turns its strict xfail into a pass. The O2 cases (LITE, LIND) are re-run on the desk with an analyst-style `long_run_margin`
     to show a positive long run.

### Revision 24 step 2a: the desk fixes, built and audited (2026-10-16 08:21; `0d87270`, `4e825c4`, `9a36244`, `e0f824a`)
- **The suite:** 3,085 passed, the 42 known failures plus the timing flake, 0 xfailed. The 8 audit xfails now pass.
- **The coordinator read** the core diff of `consensus_reference.py`, `long_run_value` and `ronic_at`.
- **LITE and LIND** with an analyst-style long-run margin:
  - LITE: Base $594.32, terminal value $60.93B (Bull $759, Bear $356); the formula reference was $271.20 with a terminal value of 0;
  - LIND: $14.72, terminal value $0.71B; the reference was $9.53.
- **The coordinator's rulings on the builder's open points:**
  1. **"Year-5 revenue" is the builder's reading.** Each scenario's year-5 revenue scales with its owner earnings, so
     `margin_ratio = long_run_margin / m5` in every scenario. The long run follows the analyst's own years 1–5 path. The other reading pinned
     it to the formula's years 3–5 revenue, which is the anchoring this revision removes.
  2. **D4 as built:** the reinvestment charge (1/RONIC) moves linearly for every terminal RONIC, the only version meeting monotonicity and the
     unlimited limit. The effect on the saved references: 19 of 20 unchanged, JCAP −0.18%. Accepted and recorded.
  3. **No year-5 revenue in the facts** (17 of 34 saved packs): m5 falls back to **the base fiscal year's filed earnings margin** (filed
     earnings ÷ filed revenue), stamped `m5_from_base_year`, so the analyst's `long_run_margin` always applies. When the base-year margin is
     not positive, the margin is held, with the existing stamp `long_run_margin_not_applied_no_revenue` and a reason. Built in step 2b.
- **The 2a gaps carried into 2b:**
  - the DEFAULTS `long_run` line still prints the reference's long-run margin, ratio and OM_5, so the reference can be derived (HRTG within
    0.01%, KSS exact). **2b removes the long-run defaults;**
  - the DEFAULTS explanation text is out of date;
  - the price-implied block has no `long_run_margin` input;
  - the TASK does not name `long_run_margin`;
  - `long_run_margin` is not on the verdict row;
  - `excess_cash`, `coe_premium_source` and `working_capital` still say "the reference".

### Revision 24 step 2b: ranges, briefing, gate, built; the coordinator's audit and rulings (2026-10-16 09:30; `4111abf`, `836c37c`, `52651ff`, `50b2de0`, `e8b8a9b`)
- **The suite:** 3,178 passed and the 42 known failures, the identical set, so no new failure. **Lookup parity** with `wt-v21`'s
  `valuation/priors.py`: 0 mismatches in 47 comparable cases, 30 names at 2 dates (`scratch/rev23/r24_s2b/PARITY_REPORT.md`).
- **The coordinator read** the desk diff (`financial_model_tool.py`: ruling 3, `implied_trajectory`, the withheld-defaults switches and the
  price-implied `long_run_margin`) and the plausibility gate (`fiduciary_gate.py`). Both are sound, except for the points ruled below.
- **The population-table audit (recorded, not fixed):**
  - **Survivorship:** delisted firms are in (20,175 processed; 42.4% of vintage-2025 observations are from firms that later ceased).
    However:
    - acquired and failed firms are not told apart;
    - tables other than `terminal` lose a firm's outcomes once it stops filing, so the long-horizon cells describe survivors;
    - the commodity family holds almost no delisted firms (it is assigned by current SIC).
  - **Look-ahead:** the fact cut is proven (`test_priors.py` 117–172). Not covered by that proof: current-dated SIC (on 42% of
    observations), a price panel with 0–4 post-cut rows per vintage, and hindsight "ceased" labels. Vintages exist for 2016–2025 only.
  - **For revision 24** these are context ranges and outlier bounds, not forecasts that are scored. The survivor tilt narrows the long-horizon
    cells, which makes the gate stricter, not looser. They stand as stated, and are printed with the cohort's n and vintage.
- **The coordinator's rulings on the builder's points:**
  1. **The long-run margin range is rebuilt (blocking).** The brief's construction, `trend + R × (current − trend)` at each quantile of
     the retained share R, was the coordinator's error. R is a ratio whose tails explode for firms with a small deviation:
     - MU's P10–P90 came out as −154% to +189%;
     - KSS's collapsed to 1.6–1.9%.

     The rebuild solved this in Addendum I1. The range is **the rebuild's own `margin_target`**: the year-5 margin level centred on the
     median-retention path (`retention_k5_used` × the deviation), with the spread from the measured level residuals conditional on the
     company's current margin band (`margin_retention.residual_k5_by_level`), merged up by the same rule and refused under MIN_N. It is
     reproduced exactly as `priors.py` positions it (the commodity family by the normalization curve, as `836c37c` already does), and the
     parity script is extended to these quantiles.
  2. **Units.** The tables measure operating margins, while `long_run_margin` is an earnings margin.
     - The range is printed in the unit it was measured in (operating margin), next to the company's filed 8-year median operating and
       earnings margins.
     - It is also printed in earnings-margin terms by one stated translation anchored at the record's medians, never the base year (that was
       O2's defect): `earnings_q = m_tc + (1 − t) × (OM_q − om_tc)`.
     - **t is** the record's median effective tax rate over the same window when it lies within [0, 0.5]. Otherwise it is 21%, stamped
       `tax_rate_statutory_fallback`.
     - The gate compares the analyst's `long_run_margin` with the earnings-margin P5–P95 under the same translation.
     - The builder reports the translation's inputs and both ranges for the six pilot names plus LITE, LIND, KSS and HRTG.
  3. **The normalization line prints the company's band, as built** (it is context; the gate never reads it).
  4. **Unmeasured quantiles** (the growth and ROIC-fade P10/P90) print "not measured". A gate metric with no measured P5–P95 is annotated,
     never rejected, as built.
  5. **Terminal growth.**
     - The `terminal` table measures **10-year revenue CAGR** (the `with_delisted` variant is accepted). It is printed under that name, as
       context for the growth path, and it bounds the gate's revenue CAGR to year 10.
     - **It is not a perpetual-growth distribution,** and it is no longer printed as `terminal_g`'s range.
     - `terminal_g` has no population range. Its checks are:
       - the mathematics (below the discount rate, rejected otherwise);
       - **a `terminal_g` above the pack's printed long-run growth anchor** (a fact the pack already prints), which is an outlier needing an
         outlier-level citation (`implausible_supported_terminal_g` or `implausible_unsupported_terminal_g`).
  6. **Return on new investment.**
     - The range is the rebuild's **ROIC level five years on** (`roic_level` with `residual_k5_by_level`, positioned as `priors.py` does, with
       parity), printed as the context for `terminal_ronic`.
     - The incremental `ronic` table is too noisy to print (P10 −50%, P90 +49% for MU's cohort) and is dropped.
     - The gate compares `terminal_ronic` with that range's P5–P95. "Unlimited" is above P95, as built.
  7. **Families the tables do not measure** (UGI utility, LAMR REIT; HRTG's margin and RONIC): the section prints "no measured population
     for this family" per input. Every input then needs the in-range rationale, and the gate runs the mathematics, plus `terminal_g` against
     the growth anchor, annotated `no_population_cohort`.
     - **UGI and LAMR stay in the pilot.** The book holds utilities and REITs, so the analyst's behaviour without ranges must be seen.
     - Measure (a) is reported as not applicable for them.
  8. **Gate citations follow `crux_check`'s own acceptance rule:** `pack_company` or `fetched_page_naming_company`, with the quote found. One
     rule for both levels; the outlier level must not be stricter than the crux level. The other gate choices are accepted:
     - the revenue CAGR is supported by `growth_years_3_5` or `fade_years`;
     - the gate runs on the iii arms only;
     - any basis sample's rejection makes the verdict `not_usable` with Kelly 0.
  9. **The iii desk drops the years 3–5 cap: accepted.** It is a cap, and the design has none. **R11 (the reason for Bull/Bear more than 15%
     from consensus) stays:** it asks for a reason and caps nothing.
  10. **The `rev22` control prints the CONSENSUS-IMPLIED VALUE: accepted.**
      - The operator approved the ablation as "the revision-22 briefing against (iii) with P50 against (iii) without P50". The control measures
        the old briefing's behaviour on Muse. It is a pilot arm only and never reaches a verdict that is used, a ledger or the book; the system
        never shows the reference.
      - **But the control must run:** under `pilot_arm` `rev22`, the desk takes the long run as revision 22 did (the generator's margin path;
        `long_run_margin` not required), stamped `rev22_control_desk`. The step-2a arithmetic fixes D2–D4 stay. They are corrections, and the
        control tests the old briefing, not the old defects.
  11. **The reference can be approached with natural inputs** (KSS 0.05%, HRTG 0.9%) but not from printed defaults. That is economics, not a
      leak, and measures (a) and (c) will see it.
  12. **Working capital (blocking):** the deduction must follow **the analyst's own revenue path** (the stated intensity × that path's revenue
      change), not the reference's path. Fixed in 2c, with a test.
  13. Accepted (the price-implied block, and the margin search over 0–100%).
  14. Accepted (the 17 packs: the margin applies on 13 and is held on 4 with reasons).
  15. Accepted (the common-share scaling π; `base_cf` in $B).
  16. The three other entry points (`api_llm/deep_api_run.py`, `tools/dispersion_battery.py`, `tools/time_travel_trial.py`) are outside the
      pilot and production path. They are recorded as known and left alone.
  17. The coordinator adds `RS2_PRIORS_DIR` and `RS2_PRIORS_INPUTS_DIR` to the workspace `AGENTS.md` variables list.
  18. **The classifications are checked against their allowed values;** an invalid one is annotated `invalid_classification_<name>`.
      **`within_p10_p90` is computed by code** from the printed range. The analyst's declaration is kept and a mismatch annotated, and the
      citation level required follows the code's computation.
  19. Accepted (the parity script stays in workspace scratch).
- **Step 2c** (a fresh builder; brief `BRIEF_R24_S2c_ranges_fix.md`) builds rulings 1, 2, 5, 6, 7, 8, 10, 12 and 18. The pilot waits for it.
