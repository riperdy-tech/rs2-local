# SPEC: the factor-led, AI-supervised investment system (draft v1)

Written 2026-10-23 by the coordinator, after the revision-26 freeze and a cross-check with ChatGPT. **Status: DRAFT for cross-check (ChatGPT, Gemini)
and the operator's approval. Nothing here is built, scheduled or connected to trading.** `KIS_HALT` stays on; no production cutover; paper only.

## 0. Why this design

Four iterations of the staged analyst (revision 26, frozen 2026-10-23 at pack revision 28, paper-only, low confidence) showed a local 27B model cannot yet
produce reliable long-horizon valuation judgments: under every prompt design it argued margin premiums from short evidence, and its memos drifted
from its own inputs. The code-owned valuation engine has not earned trust either: the gate-1 holdout failed; gate 1b's edge was mostly value and size
exposure and about zero in 2022–2025; its revenue forecasts were no better than the population median; the 25.2 desk carries the kappa / year-6
inconsistency. What has measured value in this project's records: the screener's factor exposures; return-on-tangible-equity forecasts; and, from the
model, extraction with verified quotes and structured classification. Monitoring is mixed: constructed thesis breaks 36 of 36, real past events 6 of
20 strictly (8 of 20 on manual review) against an 18-of-20 target, on Muse Glimmer; Qwen's monitoring is unmeasured.

So the system is built around what is measurable, and every other component must earn its authority by showing incremental value.

## 1. Division of labor

| Component | Responsibility | Authority at start |
| --- | --- | --- |
| **Screener** (stock-screener, Dual Door + Door 3) | Rank and select from the universe on the approved factors (value, quality, momentum, …) | **Primary selection** |
| **Deterministic risk engine** (Python) | Data provenance and freshness, accounting validation, liquidity, solvency, exposure, concentration, hard restrictions | Enforces mechanical limits |
| **Qwen 3.8 27B** (local, `ollama_raw`) | Business interpretation, risk discovery, change detection, focused research (section 3) | Flag, escalate, explain |
| **Valuation desk** | Reverse expectations (what the price requires), sensitivity, transparent value ranges | **Diagnostic only** |
| **Portfolio engine** | Selection from the ranked list, sizing, rebalancing, exits (section 4) | Paper decisions |
| **Grader** (TRK-06 lineage) | Measure each component's incremental contribution | Decides future authority |

No component's authority is raised without a registered test (section 5).

## 2. How a finding affects a decision

Every material AI finding carries: the claim, the source fact ids (quotes verified by code), the causal mechanism, and its uncertainty.

| Class | Condition | Effect |
| --- | --- | --- |
| **Verified hard stop** | A source-verified event on a registered list (section 2.1) | Code applies the registered restriction (no new buys; for a held name, re-underwriting) |
| **Uncertain material concern** | A finding with verified quotes, not on the hard-stop list, judged material by the model | Escalation: priority investigation (section 3, job 4) and a **bounded buy pause** (at most N days, registered; it lapses unless the investigation confirms) |
| **No concern found** | Nothing material | No effect. Silence is never a positive signal and never extra conviction |

### 2.1 The hard-stop list (registered; extended only by a versioned decision)
A pending acquisition of the company at a fixed price (the price then tracks the deal, not the business); a going-concern qualification; a delisting
or deregistration notice; a restatement of the periods the factors use; a trading halt; bankruptcy or restructuring filings; a reverse split with
dilution beyond a registered bound. Each is confirmed by code against a filing (8-K item, 6-K, or the filing index), not by the model's word alone.

## 3. Qwen's four jobs (each a short, structured session; each with its own SYSTEM contract)

1. **Business interpretation.** Why did revenue, margins or earnings change? Pricing against volume, acquisition against organic, one-off against
   recurring, contracted against speculative. Output: typed claims, each with fact ids, mechanism, and a period it speaks for.
2. **Risk discovery.** Does the screener's selection overlook a material risk (customer concentration, regulation, unusual accounting, capital needs,
   contract expiry, corporate actions, a withdrawn outlook)? Output: findings classified per section 2, with evidence.
3. **Change detection.** For a held or nominated name, compare new filings and news with the recorded thesis: what changed, is it material, is
   re-underwriting needed. (The Phase 6 monitor, re-measured on Qwen.)
4. **Focused research.** When a decision is sensitive to one unknown (named by the valuation diagnostic or an escalation), investigate that question
   only. Output: a supported claim, a competing explanation, or `unresolved`; never a long-horizon point estimate.

**Not asked of the model:** discount rates, terminal values, perpetual margins, sizing, a buy/sell verdict.

**GPU use is selective:** new nominees, material events, escalations, and scheduled high-priority reviews; not a full underwriting of every name.

## 4. The exit contract (designed now)
- The monitor never sells (standing ruling).
- Exits are deterministic: the screener's own band and trend-break exit rules, the risk engine's limits, and the hard-stop list.
- A detected break (job 3) triggers re-underwriting: jobs 1, 2 and 4 on the name, then the hard-stop and escalation rules apply. The old AI valuation
  verdict has no sell authority.
- A bounded buy pause never forces a sale.

## 5. Proving each component (registered before any result is read)

**The ladder.** Same universe, dates, costs, capacity and sizing policy; one component added at a time:
- **A.** Screener factors only (the baseline, independently tradable).
- **B.** A + deterministic accounting and risk checks.
- **C.** B + AI risk investigation with the section-2 rules.
- **D.** C + AI forecasts or classifications, only where a component shows skill.
- **E.** D + valuation ranking or gating, only if valuation earns it.

**Measured at each rung:** risk-adjusted return after factor controls (value, size, quality, momentum, volatility), severe drawdowns, **false
exclusions and missed winners** (a veto that avoids a few losers while excluding more winners fails), turnover, and the incremental contribution
over the rung below. Returns under the three bounds already used (delisting treatment).

**Contamination rule.** An AI rung tested on history is valid only on dates after the model's knowledge cutoff (otherwise the model may remember
outcomes). Qwen 3.8's cutoff is probed first (prerequisite 2). The AI rungs are therefore proven mainly **prospectively** (paper), with any
historical window restricted to post-cutoff dates. Rungs A and B use the full point-in-time history.

**The deployed configuration is what is tested:** Qwen 3.8 27B Q5_K_M as served now. A switch to Q4 (or another model) is tested on these tasks
directly before it is used.

## 6. Prerequisites (offline or near it)
1. **Baseline A:** the screener alone on the point-in-time history (the gate-1 harness), three return bounds, factor-controlled. This also answers
   whether the screener itself is a sound primary engine.
2. **Qwen 3.8's knowledge cutoff:** a probe of dated events (as done for Muse).
3. **Desk fixes** (diagnostic quality, not blocking): the kappa / year-6 inconsistency with the D2 fade ruling, the tax clip, decliners' terminal state,
   financials' route; the verifier rounding bug.
4. **The hard-stop list** confirmed against filing types the data layer can see.

## 7. What carries over and what stops
- **Carries over:** the stage-1 research and fact ledger with verified quotes; the leak and verifier machinery; the network guard; the monitor's
  plumbing (Phase 6); the screener and its publish path; the frozen revision 26 as a reference record.
- **Stops:** a full AI DCF, three long-horizon scenarios, an investment-committee memo and a conviction score for every name as a precondition
  for the system to act.

## 8. Open questions for the cross-check
1. Is the screener a sound primary engine, or must baseline A pass a bar before anything else is built? What bar?
2. The bounded buy pause: length, and what confirms or lapses it.
3. The hard-stop list: complete? Anything that should be a hard stop only after measurement?
4. How to measure AI risk discovery prospectively with enough events in months, not years.
5. Whether job 4 (focused research) should feed any number at all before it shows skill.
