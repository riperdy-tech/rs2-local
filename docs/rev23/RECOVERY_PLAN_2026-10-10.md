# The full plan: a correct, accurate AI analyst for real money (written 2026-10-10)

## 0. Context

**The goal (operator):** a correct, accurate AI analysis system that is right enough to drive real money.

**The system** (system map, `03_RS2_DEPTH.md`, `05_PUBLISH_TRACK.md`), stage by stage:

| Stage | What it is | Process IDs |
|---|---|---|
| Screener | nominates research_now and watchlist | SCR-03b |
| Analyst | the depth verdict | DEP-04/07 |
| Gates | actionability | DEP-07b, DEP-09 |
| Publish | through `screener-publish` | DEP-10 |
| Paper book | `rn_depth` | TRK-03 |
| Real money | the KIS mirror, halted | TRK-04 |
| Follow-up | — | DEP-13/14 |

The analyst's valuation core is being rebuilt as rev23 (`SPEC_rebuild.md`). Filings and point-in-time data feed short price-blind prompts, in which Muse places each input inside population distributions. Python then runs the family engines and produces a distribution of intrinsic value (IV). A red-team pass sees the price. Calibration and sizing come last.

**Established** (audited):
- the data are clean point in time;
- the engine maps forecasts to value correctly: valued on the fundamentals that actually happened, it ranks well (the oracle, Addendum V);
- ROTE forecasts have skill.

**Not established:**
- company-specific revenue skill, where the code is no better than the population median;
- a stable margin edge;
- calibration, with bands covering 71%, 33% and 9% of outcomes in years 1–3;
- stock selection beyond value and size;
- distress handling;
- coverage of the commodity, REIT, utility and pre-profit families;
- repeatability.

The engine is sound. The forecasts are what fail, and Muse reading filings is the one open route to company-specific skill. Gate 2 tests it.

**What broke** (run 1, Addendum AC):
- Muse's answers mostly failed the format checks.
- After the handoff, a Sonnet fix agent ran unsupervised: it committed unaudited code, ran GPU tests and wrote a freeze before the operator stopped it.

**The operator's instructions (2026-10-10):**
- No coder agents of any kind. I write everything.
- The long run auto-launches when its gate passes.
- The red-team decision is mine to make, with time no constraint.
- The plan must be the full plan for the whole project.

**What this plan can and cannot promise.** No plan can promise that a local 30B model forecasts companies better than the base rates; that is the open question.

This plan promises four things:
- every stage is designed, registered and audited before its data are seen;
- every branch of the outcome is decided in advance;
- every gap between today and real money is named and owned;
- real money happens only on the operator's decision, after the definition of done (section 1) holds.

**Stage map** (section 3 details each stage):

| Stage | What | Main exit |
|---|---|---|
| S0 | Contain and make the records true | nothing runs; the records are accurate |
| S1 | Gate-2 machinery: audits, fix, A/B, rehearsal | the behaviour gate passes |
| S2 | Gate-2 run 2: review, freeze, 600 company-dates, controls | the run is complete and valid |
| S3 | Score gate 2; choose branch C1, C2 or C3 by rules fixed now | the branch decided |
| S4 | Engine v2: base rates and calibrated dispersion | its validation passes |
| S5 | Muse integration (C1) or the structural search (C2, C3), then gate 2b on fresh dates | gate 2b passes |
| S6 | Distress layer v2, and the coverage decisions | its validation passes |
| S7 | Verdict contract v4, and downstream design | specified and tested |
| S8 | Selection and sizing rule, registered, accruing on fresh dates | registered |
| S9 | Live production build in rs2-local, with parity proven | parity and preflight pass |
| S10 | Shadow operation: frozen paper book, scoring, follow-up | the definition of done holds |
| S11 | Real-money readiness and the resume protocol | the operator's decision |
| S12 | Continuous operation and improvement | ongoing |

---

## 1. The definition of done (recorded in Addendum AD; each item must hold out of sample, on dates never used for development)

| # | Property | Measured by | Today |
|---|---|---|---|
| D1 | **Clean, identical inputs:** point in time, filings-only core, the same in live use and replay | the leak audit; the live/replay parity test (S9) | replay audited; live not built |
| D2 | **Forecast skill:** every input the engine uses (year-1 growth, margin path, ROIC, ROTE) beats the code, the population median and persistence | paired error, clustered bootstrap, by date | ROTE only |
| D3 | **Calibration:** stated P10–P90 cover 80% ± 5 at years 1–3 | coverage by year and input | 71%, 33%, 9% |
| D4 | **Correct value mapping:** the oracle ranks; no family sorts; the level is in band | the oracle test (Addendum V) | holds |
| D5 | **Distress:** the least-solvent tercile does not invert; the default model is calibrated | splits; AUC and Brier score | inverts; AUC 0.65 |
| D6 | **Coverage:** every nominated company is either valued validly or explicitly abstained, with a reason | scope counts | four families out |
| D7 | **Repeatability:** the same filings give the same verdict within tolerance | rerun with a second seed | never measured |
| D8 | **Integrity, unattended:** quotes 100% verified, no silent fallbacks, preflight green, no human or Claude in the loop | G5-style checks; the preflight; incident log | replay only |
| D9 | **Money bar** (Addendum Z 10): factor-neutral alpha > 0 with t ≥ 2, net of 30 bp a trade, robust to exit treatment, over ≥ 36 monthly out-of-sample dates; plus a frozen shadow portfolio | by date, with the 2020 dates separated | not established |
| D10 | **Operations:** refresh cadence met; the follow-up works; records and backups current | cadence and uptime logs | old system only |

**A timing fact the operator must decide on (O1).**
- The model's knowledge ends about August 2025, and the gate-2 dates (2025-10 to 2026-06) will be used to fit shrinkage and calibration. So D9's out-of-sample dates start in 2026-07.
- 36 monthly dates end in 2029-06, and the 3-month returns are complete by about 2029-09.
- That is a property of using an LLM that would know historical outcomes. It is not slack in the plan.
- D2, D3 and D7 can be established within months, because each quarter brings hundreds of realised fundamentals.
- I will not relax D9 myself. The operator keeps it or replaces it (for example, a staged capital ramp tied to D2, D3, D7 and the shadow record).

---

## 2. Programme rules (every stage)

1. **One author.** I write all code, tests, scripts and records. No Sonnet, no Gemini, no subagents that write.
2. **Records first.** Each stage starts by checking the records for prior attempts (system map, `PHASE_4_AMENDMENTS`,
   Addenda), and every design cites them.
3. **Register before data.** Designs, bars and reading rules are written into an addendum or registration before
   any result exists. Holdouts are named before use and used once. Nothing is tuned on outcomes (`orchestration-protocol`:
   no curve-fitting).
4. **Test first, on real fixtures.** Every check is tested on real saved model outputs, not only on mocks. Contract
   tests keep prompts and checkers in agreement.
5. **Audit before reporting.** Read the diff in full. Recompute the key numbers with an independent script. Check
   look-ahead and artefacts (style, survivorship, stale prices, small samples). Negatives come first; nothing goes out
   unverified, or it is labelled "unverified".
6. **Outside review.** ChatGPT and Gemini cross-check every registration and every result, relayed by the operator.
   I rule on each point in an addendum.
7. **GPU.**
   - A behaviour gate comes before any run longer than one hour.
   - Long jobs go through scheduled tasks, from detached worktrees at frozen commits, never developed in.
   - The runner waits while the operator games, and no job overlaps another session's.
8. **Sessions.** One critical path at a time. Every stage ends with a dated handoff and STATUS, and each stage runs in
   a fresh session.
9. **Hard limits:**
   - `KIS_HALT` and `DEPTH_PAUSED` stay on until S11;
   - no deletions;
   - no secrets or `.env*`;
   - no deploys without the operator;
   - downloads only from approved sources (new recurring downloads need approval, O5);
   - publishing only through `screener-publish`.

---

## 3. The stages

### S0. Contain and make the records true (about 1 hour; needs this plan's approval)

**State verified at 00:25 KST:**
- **Nothing of gate 2 is running:** GPU at 34 MiB, run 1 at 54 of 600, sealed, `PAUSE` in place.
- **The scheduled task still restarts run 1.** `RS2-Gate2-Replay` fires every 15 minutes; each start halts with code 5, because `5d0cc8a` broke the freeze (so far at 23:55 and 00:10).
- **The agent's work, all unaudited:**
  - the branch `rebuild-gate2` head is `5d0cc8a`, its unaudited commit, local only;
  - `data/gate2_r2` holds its copies and its freeze, written at 00:12;
  - the old handoff wrongly says "no freeze".
- **Process pid 21140 is unrelated:** it is the self-hosted GitHub runner's screener data fetch.

**Work:**
1. **Disable `RS2-Gate2-Replay`** (reversible).
2. **Seal run 1.** Write `data/gate2/reports/RUN1_SEALED.json` (sha256 of every file under `runs`, created exclusively).
3. **Point a branch,** `review-2026-10/gate2-fixagent-unaudited`, at `5d0cc8a`. Nothing is reset or deleted.
4. **Addendum AD, part 1:**
   - post-handoff facts;
   - the run-1 failure taxonomy:
     - first-attempt parses P1 1/39, P2 15/39, P5 8/34;
     - 150 of 171 failed parses missing exactly one closing brace;
     - 53 R citations;
     - 281 citations labelled D1–D4;
   - rulings R1–R8 (S1–S2);
   - the definition of done (section 1);
   - the branch rules of S3.
5. **A dated correction to `HANDOFF_2026-10-09.md`.** Update `STATUS.md`. Save this plan as
   `rev23/RECOVERY_PLAN_2026-10-10.md`.
6. **Memory:**
   - a new feedback file, `coordinator-writes-everything`;
   - update `no-opus-subagents`, `orchestration-protocol` and `rev23-handoff`;
   - update the `MEMORY.md` index.

**Exit:**
- the task is disabled, and no new events appear;
- the seal re-hashes clean;
- the records are re-read and grepped for bell characters.

### S1. Gate-2 machinery: audits, fix, A/B, rehearsal (about 2 days of CPU work and 6 GPU-hours)

**Rulings** (into Addendum AD):
- **R1. Who writes:** I do.
- **R2. The agent's work is evidence only.** New work starts from `c0a8847` on `review-2026-10/gate2-run2`. After my fix is tested, I diff it against `5d0cc8a`; differences are investigated, never copied.
- **R3. The red team** (my decision, as delegated):
  - The registered system and bars stay as approved.
  - **Fixed now as reported diagnostics, with reading rules:**
    - **(a) Filing skill.** G1's statistic is computed on the pass-1 (price-blind) positions, against the code, the population median and persistence. Skill is concluded only if pass 1 beats all three.
    - **(b) The red team's effect: final against pass 1.** The red team survives only if final beats pass 1.
    - **(c) Strict G4.** Only a new quote counts as evidence. A strict share above 10% means "the red team anchors". The strict-rule counterfactual is recomputed with the frozen engine.
  - **Why:**
    - it removes price contamination from the skill test;
    - it measures the red team instead of guessing;
    - it costs no GPU time and changes no bar.
- **R4. Constrained decoding is adopted only if the A/B passes.** Otherwise run 2 uses a two-call design.
- **R5. The behaviour gate:** measured by me, from the raw files, on a rehearsal outside the scored run.
- **R6. The freeze waits for three things:** the gate, and my rulings on cross-checks 6 and 7.
- **R7. Run 2's home:** state in `data/gate2_run2`, run from a detached worktree at the frozen commit.
- **R8. Repeatability control:** 30 company-dates rerun with a second seed. A median shift above 10 percentile points means the live design must combine several samples.

**Work:**
1. **Baseline.** Create worktree `wt-gate2-dev` on `gate2-run2` from `c0a8847`. Record the two suites' counts:
   - `"C:\Program Files\Python312\python.exe" -m pytest valuation rebuild_harness -q -p no:cacheprovider`;
   - `... -m pytest tests tools/audit_202608/tests -q`.
2. **Contract audit of P1–P6** in both families: every checker rule against what the template and its example state.
   Known so far: R in the example, R in P5, and the `[Dn]` labels.
3. **Read in full the code that produces run outputs** (about 3,500 lines: `pipeline`, `mapping`, `checkers`, `redteam`,
   `prompting`, `pack_v2`, `documents`, `reverse`, `runner`, `env`, `guard`, `integrity`, `stage2_layer`). The checklist:
   - no price reaches P1–P5;
   - the mapping matches `SPEC_muse_passes` section 2;
   - unanchored means P50 with width "wide";
   - `redteam.decide` matches the spec;
   - the fields R3 and R8 need are recorded;
   - a failed SEC fetch is stamped;
   - `is None`, never `or`, and no silent fallbacks.

   The findings go into Addendum AD, part 2.
4. **The fix, test first:**
   - **New `valuation/muse/jsonschemas.py`**, generated from the checker's own constants:
     - required keys and `additionalProperties: false`;
     - enums, including the D subsections;
     - length caps;
     - `anyOf` for P6 round 1.
   - **`runner.py`:** `response_format` on both attempts, saved with each request; version 2.
   - **`checkers.py`:** `Evidence` owns the parsing of the `[Dn]` subsections, so `integrity.py` re-checks
     identically.
   - **Templates:** each example lists only the sections the checker accepts, P5 drops "or R", and each changed
     template gets a new version line.
   - **Plumbing:** `pipeline.py` passes the schema per call, and `freeze_content.py` records `response_format`.
   - **The R8 `repeat` mode** in the runner.
   - **New `rebuild_harness/gate2/behaviour.py`:** behaviour only, never outcomes.
   - **Tests:**
     - schema and checker agreement;
     - real run-1 fixtures for the D1, D3 and R cases;
     - the contract test;
     - `integrity.py` accepts every Dn citation the pipeline accepted;
     - `behaviour.py` on a fixture;
     - the `repeat` mode;
     - the engine diff from `c7d7a4f` is empty.
5. **Replay run 1 through the new checker** (answers brace-repaired, for this diagnostic only), to get the expected
   residual failure rate.
6. **GPU A/B** (a one-off scheduled task, about 3 hours; script in `scratch/rev23/gate2_ab/`, reusing `gate2.server`
   and `gpu.other_gpu_use`).
   - **Inputs:** run 1's first-attempt requests for P1, P2, P3, P5 and P6, from 10 companies (about 46 requests).
   - **Arms:** U1, run 1's saved answer; U2, a new unconstrained answer; C, the same request with the schema.
   - **Adoption criteria, all of which must hold:**
     - C passes parse and schema on ≥ 95% of first attempts;
     - for each call type, median reasoning length C ÷ U2 ≥ 0.6;
     - mean |C − U2| in percentile ≤ mean |U1 − U2| + 5;
     - C's quote verification ≥ U2's − 10 points.

     Otherwise, build the two-call design and repeat.
7. **Rehearsal** (a one-off task, about 3 hours): `runner --mode full --rehearsal --limit 20` into
   `data/gate2_rehearsal_r2`, prepared as hash-verified copies, run from a detached worktree.
   - **The gate:**
     - ≥ 90% of calls parse on the first attempt;
     - ≤ 5% of inputs unanchored;
     - P5 succeeds on ≥ 90%.
   - **Stop triggers:**
     - reasoning below 0.6 × run 1's;
     - more than 30% of inputs identical to the code arm;
     - fewer than 90% of quotes verified;
     - any leakage violation;
     - any technical status;
     - length cut-offs on more than 5% of calls.
   - **My own reading:** one full answer per company.

**Exit:**
- suites green against the baseline;
- the A/B and the gate pass, with every number reproduced by an independent count;
- my own diff audit is done.

### S2. Gate-2 run 2 (about 4 GPU-days, plus about 10 GPU-hours of controls)

**Work:**
1. **Cross-check 7.** `CROSS_CHECK_7` covers the fix, the A/B, the gate, R3 and R8. With the cross-check 6 replies,
   I rule on every point in Addendum AE. A ruling that changes the system means a new rehearsal.
2. **Freeze.**
   - Create the run worktree `wt-gate2-run2`, detached at the frozen commit.
   - Prepare `data/gate2_run2` (hash-verified copies; the sample is `d1fefc76…`).
   - Run `freeze_content write`; `verify` must come back empty, the engine diff must be empty, and the dry run must
     report 600 jobs, ready.
3. **Launch.** Run `register_gate2_task.ps1 -Mode full -StateDir data\gate2_run2` from the run worktree. Check the
   task's arguments and the first events, then report (negatives first).
4. **During the run:**
   - **Behaviour checks.** The behaviour tool runs daily against the gate thresholds. A breach means PAUSE and a report.
   - **CPU work in parallel:**
     - audit `scoring.py` and `outcome_extract.py` against the registration (both Sonnet-written and never
       independently audited);
     - code the R3 and R8 diagnostics, and the exact Z 3 baselines;
     - write my own G1 recomputation;
     - draft the S4 specification;
     - write `REGISTRATION_gate2b.md` and `REGISTRATION_selection.md`, so their bars are fixed before any gate-2
       outcome is read.
5. **After the main run:** the G6 masked control (30 company-dates), then the R8 repeat (30 company-dates), through
   the task.

**Exit:** `gate2_finished.flag` exists, the controls are done, and the behaviour stayed inside the gate throughout.

### S3. Score gate 2 and decide the branch (1–2 days)

**Work:**
- Score G1–G6 as registered, with G1 first (Addendum Z 2).
- Then the Addendum Z 3 diagnostics (four-way, factor-adjusted, average-input control, solvency splits, turnover), R3
  (a), (b) and (c), R8 and G3 calibration, all by date (Addendum AA).
- Every headline number is recomputed by my independent script before it is reported.
- `CROSS_CHECK_8` covers the results, and I rule on it in an addendum.

**Branch rules, fixed now in Addendum AD:**
- **C1. Muse has filing skill:** pass 1 beats the code, the population median and persistence on next-quarter growth
  or margin change (R3a). Go to S4 and then S5-C1.
- **C2. Muse beats the code only:** the system's forecasts become engine v2's base rates (S4). The interim system for
  financials only (cross-check 6, question 5) goes to the operator with numbers. Go to S5-C2/C3.
- **C3. Muse fails, or its behaviour is unusable:** S4, then the structural search (S5-C3).
- **In every branch:** the red team is kept only under R3b, and multi-sampling is required if R8 says so.

### S4. Engine v2: base rates and calibrated dispersion (about 1–2 weeks of CPU work; needed in every branch)

**Goal:** the best non-AI forecaster, which serves as both the baseline and the prior, with calibrated uncertainty
(D3) and the value mapping kept intact (D4).

**Design** (the Addendum AB rules, each already measured walk-forward; nothing fitted on returns):
- **Revenue growth:** the walk-forward population median exactly as the forecast study measured it. Year 1 may use
  w = 0.5, which the study found immaterial; I take w = 0 unless the study's own numbers favour 0.5.
- **Margin:** keep the code's retention path.
- **ROTE:** an empirical-Bayes blend, `x = prior + 0.75·(company − prior)`.
- **Dispersion for years 1–3:** from population outcome distributions of companies in a similar state at horizon k,
  replacing the under-dispersed bands.
- **No operating-leverage model** (rejected on evidence).
- **Versioning.** v2 is a new engine version. `c7d7a4f` stays frozen for gate 2's reproducibility.

**Work** (new branch `review-2026-10/engine-v2` in `rs2-local`):
- the priors interface and builder (a new `data/priors_v4` written by the frozen builder logic plus the new outcome
  distributions);
- the operating and financial engines' input wiring;
- `ENGINE_VERSION`;
- tests.

**Validation** (`REGISTRATION_engine_v2.md`, written before running; development data, so these are engineering
checks, not performance claims):
1. **Implementation:** reproduce the forecast study's walk-forward errors for 2016–2024 within a stated tolerance.
2. **Calibration:** walk-forward P10–P90 coverage between 75% and 85% at years 1, 2 and 3, by family.
3. **Oracle:** the engine still ranks on realised fundamentals across 2020–2024 with the Y1 controls.
4. **Level:** the median IV ÷ price is reported (a diagnostic).
5. **No look-ahead:** the priors' cut proof is repeated for v2's new tables.

**Exit:** the registration's checks pass, my audit is done, and `CROSS_CHECK_9` (which also covers S5) is ruled on.

### S5. Muse integration (C1), or the structural search (C2/C3); then gate 2b on fresh dates

**S5-C1 design** (fitted on gate-2 data, on forecast loss only, never returns):
- **Transport Muse's deviation to the v2 prior:**
  `x = v2_P50 + w·(Muse value − c7d7a4f prior P50)`, per input.
  - w is estimated per input and family by leave-one-date-out over the 5 gate-2 dates.
  - w = 0 where Muse does not improve out-of-fold error (Addendum Z 5).
- **Calibration** (`SPEC_muse_passes` section 4): an isotonic mapping from stated to realised percentile, for year 1
  per input, cross-fitted by date. It replaces the width factors.
  - Years 2–3 keep v2's population dispersion, because their outcomes have not happened yet. This is stated as a
    limitation.
- **The red team:** kept or dropped by R3b.
- **Multi-sample:** if R8 requires it, the smallest k whose median placement has a standard error ≤ 5 percentile
  points, taken from R8's measured variance. Each company's placements are the median over k samples, which costs
  k times the GPU time.

**S5-C2/C3 structural search.** The cause is found from behaviour data, never by tuning on outcomes. Each candidate is
pre-registered and tested on a fresh replay:
1. **The evidence the pack gives the model.** How often is section D thin or missing (the behaviour stats)? Fix the
   document extraction first.
2. **The placement interface.** Instead of percentiles, Muse extracts stated figures (guidance, backlog, contracts,
   capacity) with quotes, and code maps them numerically into the inputs. This removes model decisions that code can
   fill (memory `claude-builds-not-part-of-system`).
3. **Model capacity.** Another local model, with its knowledge cutoff probed first so the replay dates stay clean
   (`PHASE_7_AFTER` P7.1 method).

   Before any design, the records are checked so the failed backbone design is never repeated.

**Gate 2b, the assembled system on untouched dates** (`REGISTRATION_gate2b.md`, written and approved before S3's
outcomes are read).
- **Dates:** 2026-07-31, 2026-08-31 and 2026-09-30, untouched until then. Their next-quarter outcomes are reported by
  about 2026-11-16.
- **Sample:** a new seeded draw.
- **Bars:**
  - the assembled system beats engine v2 alone and persistence on next-quarter growth and margin (paired, clustered
    bootstrap);
  - year-1 coverage of 80% ± 7;
  - repeatability within R8's tolerance;
  - integrity 100%.
- **Volume:** about 360 company-dates, about 2.5 GPU-days.

**Exit:** gate 2b passes (C1). Otherwise its registered fail rule applies, and the structural search continues on the
next fresh dates.

### S6. Distress layer v2, and coverage (CPU; can run alongside S5)

**Distress (D5).** The current survival layer is weak (AUC 0.65), and its scores correlate 0.9999 with and without it.
- **Candidates**, all point in time and trained on D1 events with an expanding window:
  - richer solvency variables: coverage trend, refinancing walls, cash runway, the Altman and Ohlson components;
  - distance to default from prices;
  - Muse distress flags (going-concern language, covenant breaches), which can be tested only on post-cutoff dates.
- **Validation** (registered): walk-forward AUC and Brier score against the current layer; the least-solvent tercile
  no longer inverts on the next fresh dates.

**Coverage (D6):** for each family, the operator chooses between building it and abstaining (O2). My recommendation is
to abstain explicitly now, publishing "no view" with a reason so nothing is valued invalidly. Then build one family at
a time, each with its own validation:
- utilities need a rate-base model;
- commodity producers need a commodity-price input (mid-cycle normalisation failed even with perfect fundamentals);
- pre-profit companies need a survival or option model;
- REITs need FFO and NAV.

### S7. Verdict contract v4 and the downstream design (about 1 week of CPU work)

**Goal:** map the new core's calibrated IV distribution into the existing downstream contract (the overlay,
`depth_gates`, `rn_depth`, the site, the follow-up) with minimal change.

**Design** (`SPEC_verdict_contract_v4.md`, cross-checked):
- **Direction:** keep the band rule and the minimum margin of safety (D7 rule, 10%), applied to the calibrated P10–P90
  band.
  - `undervalued` = price below P10 and the margin of safety ≥ 10%;
  - `overvalued` = the mirror image;
  - otherwise `hold`.
- **Fields carried:** the calibrated quantiles, Pr(IV > price), the expected margin of safety, the terminal-value
  share, model disagreement, the count of hard-evidence positions, extraordinary flags, unanchored inputs, repeat
  spread (if multi-sample), every version stamp (pack, templates, runner, engine v2, calibration) and `run_source`.
- **Actionable reasons (v4):**
  - `not_usable`, `family_not_built`, `non_production_row`;
  - `integrity_fail` (any accepted quote fails re-check);
  - `unanchored_high` (above a registered share);
  - `implausible_level` (IV ÷ price outside its family's P1–P99 population range: a fence that can be replayed,
    replacing the consensus "street fence" because consensus is out of the core, Addendum C 5);
  - `extraordinary_without_evidence`;
  - `instability` (a change from the prior verdict beyond tolerance without a new filing);
  - `stale_inputs`;
  - `pre_valid_analyst` (a version switch).

  These are gates on read only, so no row is ever dropped (non-negotiable 3).
- **Watch items and invalidation rules for DEP-13/14,** generated by code: for each input placed away from P50, a
  checkable rule on the next reported metric (for example, `revenue_yoy_pct` below the forecast's P10). This
  replaces the old memo's SECTION 8, using the existing vocabulary.
- **Momentum and entry timing (O3).** Pass 1 is price-blind, so momentum cannot enter through the analyst as the
  2026-09-22 ruling (Option 2) assumed. My recommendation is the fallback that ruling itself allows: a deterministic
  two-axis entry timing (value direction × SCR-10 trend state), stamped and graded. The E5b momentum basis is
  evaluated inside S8, not built in.
- **Sizing inputs:** calibrated probabilities replace the saturated Kelly (stuck at its cap in 53 of 85 outputs). The
  rule itself is chosen in S8. The MRI turbulence flag, the one validated alarm, stays a risk input.
- **Downstream changes**, on branches, each merged with the operator's OK:
  - `depth_gates.assess` v4;
  - the overlay's new fields (additive);
  - SCR-04 `apply_llm_overlay`;
  - the TRK-03 `rn_depth` targets;
  - the site desk (the design brief `02_` and `05_` sections updated);
  - TRK-06 grading of v4 fields.

**Exit:** the specification is cross-checked; contract tests run v4 rows through every consumer, with fixtures in
both repositories.

### S8. Selection and sizing rule (registered during S2; accrues on fresh dates)

**Hypotheses, registered in `REGISTRATION_selection.md`** during S2, before any gate-2 outcome or fresh date's return
exists:
- **H-S1.** Rank by calibrated expected IV ÷ price within industry, neutralised for value and size.
- **H-S2.** The expectation gap: the forecast against what the price implies, on dates outside any development use
  (Addendum AA).
- **H-S3.** H-S1 with the two-axis entry timing.
- **Sizing:** from calibrated probabilities, under caps and turnover limits, with the drawdown governor kept.

**Evaluation:**
- monthly fresh dates from 2026-07 on, by date;
- net of 30 bp a trade;
- the Y1 factor controls;
- exit bounds (Y2 and Z 4);
- turnover.

This is D9's accrual (O1 sets when it is enough). Interim readings are reported every quarter and never used to
re-tune; a rule change restarts its count.

### S9. Live production build in rs2-local (about 2–3 weeks)

**Work** (new branch, a fresh worktree, the production suite green):
1. **Live data layer.**
   - Daily refreshes of SEC submissions and companyfacts (O5), SEC filing documents for section D, Yahoo daily closes,
     and Damodaran's monthly ERP and betas (O5).
   - The priors vintage built each January, the survival model retrained on a schedule, and industry medians per
     date.
   - Every input carries its as-of date; staleness refuses (`stale_inputs`).
2. **Live runner.** It replaces DEP-04's core and reuses the replay code paths unchanged: pack v2 → Muse calls through
   a managed llama.cpp server (the same pins as gate 2) → engine v2 plus calibration → red team (if kept) → contract
   v4 → ledger row.
3. **Parity test (D1).** The live runner in as-of mode, fed recorded model responses, must reproduce the replay
   harness byte for byte on a replay date: the same packs, prompts and engine results.
4. **Orchestration (DEP-00).**
   - **The book:** research_now ∪ watchlist ∪ ledgered names.
   - **Triggers:** a new 10-Q or 10-K, 8-K item codes, a price-range crossing, 14-day rotation.
   - **The GPU budget** is about 10 minutes a company, so a full pass of about 150 names takes about 25 hours; a
     multi-sample k multiplies that.
   - The on-demand path (DEP-11) on the new core.
5. **Follow-up (DEP-13/14)** rewired to the v4 watch items and the shared Muse server. Its acceptance tests A (battery)
   and C (shadow week) are re-run on the new analyst.
6. **Gates and operations.**
   - The fiduciary checks are rewritten for v4.
   - The preflight (OPS-09) is updated: llama.cpp and model hashes, Damodaran and point-in-time freshness, priors
     vintage, calibration version.
   - The new state files are added to `sync_state`'s backup list.
   - The system map and STATUS are updated.
7. **Retirements, by operator ruling:**
   - the old Qwen analyst, rev21/22 (its weights kept);
   - the Depth Cloud Backstop (O6): my recommendation is to retire it, because a DeepSeek arm is a different system
     and breaks parity; a down PC fails closed instead (the overlay goes stale, and `buy_paused` after 36 hours).
8. **The screener items that touch the analyst's input book are settled first:**
   - the `input-scope` merge decision;
   - the open capex parts;
   - the IFRS foreign-filer gap, noted as an abstention.

**Exit:** parity is proven, the preflight is green, the follow-up's acceptance tests A and C pass, and
`CROSS_CHECK_11` (live build and resume protocol) is ruled on.

### S10. Shadow operation (from the end of S9; months)

**Work:**
- The live system runs unattended: the publish pipeline runs, the paper book `rn_depth` trades on paper only, and
  `KIS_HALT` stays on.
- The shadow book is frozen by version; any change is a new version, and its count restarts.

**Scored automatically (TRK-06 extended):**
- D2 forecast accuracy against realised quarters;
- D3 coverage;
- D7 two-run spot checks;
- D8 incidents;
- D10 cadence;
- D9 returns, by date.

Quarterly scorecards go to the operator, negatives first.

**Exit:** D1–D8 and D10 hold, and D9 meets the bar the operator chose (O1).

### S11. Real-money readiness and the resume protocol (the operator's decision)

**Facts that must be handled:**
- Clearing `KIS_HALT` alone resumes real execution, because `KIS_ENV=real` and auto-execute are still set.
- `rn_depth` is in cash, so clearing the halt today would sell every real position.
- The ARX position is open, and its fate is the operator's call (O7).

**Protocol** (P6.2 adapted; `RESUME_PROTOCOL_v4.md`):
1. The preflight is green, including the tests.
2. The KIS probe and dry runs run for several days against the shadow book.
3. A staged capital ramp, with gross caps, `max_turnover` and a drawdown-governor rebase.
4. The first live sync is attended.
5. Daily reconciliation.
6. Rollback means setting `KIS_HALT` again; its sticky behaviour is verified first.

### S12. Continuous operation and improvement

- **Each January:** the new priors vintage.
- **On schedule:** survival model retrains, and Damodaran and SEC refreshes.
- **Every quarter:** scorecards (D2, D3, D7, D9).
- **Model swaps:** any model change is a new version, validated by a fresh post-cutoff replay (the P7.1 method).
- **"Core + research" experiment:** news and web research measured prospectively, never in the core until it beats
  the core (`SPEC_muse_passes` section 0).
- **New families:** built one at a time (S6).
- **Screener backlog:** its items (the static-ratio review, sector quotas) stay its own track.

---

## 4. Operator decisions (none blocks S0–S3; each is needed by the stage named)

| # | Decision | Needed by | My recommendation |
|---|---|---|---|
| O1 | Keep D9 as written (≥ 36 out-of-sample monthly dates, about 2029-09), or a staged capital ramp tied to D2, D3, D7 and the shadow record | S8/S11 | Your call; I will not relax it myself |
| O2 | Coverage: build or abstain, for each family | S6 | Abstain explicitly now; build one family at a time |
| O3 | Momentum: deterministic two-axis entry timing (revising the Option 2 ruling) | S7 | Two-axis, graded by TRK-06 |
| O4 | The live model is the validated model (Muse); any switch needs its own replay | S9 | Confirm |
| O5 | Standing downloads for live data (SEC daily, Damodaran monthly, Yahoo daily) | S9 | Approve, from approved sources only |
| O6 | The Depth Cloud Backstop | S9 | Retire (breaks parity); fail closed |
| O7 | The ARX position, and the KIS resume details | S11 | Your call |
| O8 | Consensus as a display-only flag in live use | S7 | Display only; never a gate or an input |

## 5. Timeline (estimates; GPU time waits while the operator games)

| When | Stage |
|---|---|
| 10-10 to 10-13 | S0 and S1 |
| 10-14 to 10-21 | S2 (cross-check relay, about 4 GPU-days, controls) |
| 10-21 to 10-23 | S3 |
| 10-23 to 11-15 | S4, S6 and S7 (CPU); S5-C1 fitting |
| About 11-17 to 11-23 | gate 2b run and score |
| 11-23 to mid-December | S9 |
| From mid-December | S10 shadow operation; S8 accrual (D2, D3, D7 readable within 1–2 quarters) |
| Real money | S11, per O1 |

## 6. Main risks and their handling

| Risk | Handling |
|---|---|
| Muse has no skill (C2, C3) | Branches decided in advance; the base-rate system and the structural search, never a relabel |
| Overfitting through repeated design on the same dates | Each fresh date used once; registrations before data; outside review |
| Small samples (5 dates, about 430 pairs) | Clustered bootstrap; results by date; no pooled-only claims |
| Live and replay drift apart | The S9 byte-level parity test; one code path |
| Data sources break (SEC, Yahoo, Damodaran) | Staleness refusal, preflight, alerts; fail closed |
| GPU contention (gaming, follow-up) | Runner waits; GPU budget per day; multi-sample k costed before adoption |
| A session runs too long or degrades | A fresh session per stage; handoff and STATUS at every exit |

## 7. Critical files

- **Records** (`stocks-workspace/docs/review_2026-09-22/rev23/`):
  - `SPEC_rebuild.md` (Addendum AD onward);
  - `RECOVERY_PLAN_2026-10-10.md`;
  - `CROSS_CHECK_7` to `CROSS_CHECK_11`;
  - `REGISTRATION_engine_v2.md`, `REGISTRATION_gate2b.md`, `REGISTRATION_selection.md`;
  - `SPEC_verdict_contract_v4.md`, `RESUME_PROTOCOL_v4.md`;
  - `../STATUS.md`, the system map.
- **Gate 2** (`rs2-local`, `review-2026-10/gate2-run2`):
  - `valuation/muse/{jsonschemas.py, runner.py, checkers.py, prompting.py, pipeline.py, prompts/}`;
  - `rebuild_harness/gate2/{behaviour.py, runner.py, freeze_content.py, scoring.py (audited)}`.
- **Later:**
  - `review-2026-10/engine-v2`: the priors and engines;
  - the live branch: `depth_pipeline`, `depth_gates`, `fiduciary_gate`, `orchestrate_depth`, the follow-up modules,
    `preflight.py`, `sync_state.py`;
  - `stock-screener` branches: `apply_llm_overlay`, `track_paper_portfolios`, site desk.
- **Reused as they are:**
  - `gate2/server.py` and `gpu.py`;
  - the runner's `--rehearsal`, `--limit` and `--dry-run`;
  - `freeze_content.py`, `register_gate2_task.ps1`, `launch_gate2.vbs`;
  - `checkers.check_citation`, the single owner;
  - `leakage_audit.py`;
  - `depth_gates` (gate on read);
  - `publish_overlay` (the publish invariants);
  - the TRK-06 honest-measurement functions;
  - the KIS safety layers.

## 8. Verification summary

Every stage exits only on its registered checks:
- the suites are green against a recorded baseline;
- the contract and real-fixture tests pass;
- the engine-diff and freeze `verify` are clean;
- every headline number is recomputed by an independent script;
- the cross-check is ruled on;
- STATUS and the handoff are updated.

The project is done when D1–D10 hold out of sample and the operator decides on real money.
