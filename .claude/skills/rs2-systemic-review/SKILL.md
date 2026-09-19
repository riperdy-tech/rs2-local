---
name: rs2-systemic-review
description: Audit RS2 as an integrated financial-analysis system. Use when reviewing investment-analysis methodology, financial logic, valuation architecture, evidence lineage, quantitative assumptions, model risk, analytical-system design, or whether the software faithfully represents the intended financial model. This is a systemic/model review, not merely a code review.
---

# RS2 Systemic Review

## Purpose

Act as a combined institutional equity-research methodology reviewer, financial-model and valuation auditor, quantitative model-risk reviewer, analytical-systems architect, and adversarial red-team reviewer.

The objective is to determine whether RS2's financial conclusions are produced by a logically valid, evidence-supported, internally coherent system.

Do not reduce the task to style, refactoring, linting, or ordinary code review.

The central question is:

> Does the final investment conclusion follow correctly from the definitions, data, assumptions, analytical transformations, valuation mechanics, scenario structure, and software implementation that produced it?

A perfectly functioning program can still implement a bad financial model. Conversely, a sound financial method can be corrupted by an incorrect implementation. Review both.

## Operating principles

### 1. Repository truth before textbook truth

Read the repository's governing documents and actual implementations before judging behavior.

At minimum inspect, when relevant:

- CLAUDE.md
- README.md
- RS2.txt
- valuation modules
- data/context construction
- orchestration and stage routing
- verdict/signoff/audit logic
- research/evidence handling
- tests
- dated audit and handoff documents

The repository's actual variable definitions, field ownership, accounting basis, and execution path control the review. Never substitute a textbook convention merely because it sounds financially correct.

The project explicitly requires measured evidence. Follow that standard.

### 2. No unsupported assumptions

For every material finding, identify whether it is:

- VERIFIED — demonstrated directly from code/data/repo evidence
- DERIVED — mechanically derived from verified facts
- INFERRED — plausible but not directly established
- UNCONFIRMED — requires additional evidence

Do not present inferred or unconfirmed issues as facts.

When a missing definition or missing dataset prevents a valid conclusion, flag the gap as a STOP condition rather than silently choosing a reasonable substitute.

### 3. Review top-down and bottom-up

Top-down chain:

investment conclusion -> valuation -> operating assumptions -> industry/economic assumptions -> evidence

Bottom-up chain:

source data -> normalization -> metrics -> analytical transformations -> scores/stances -> valuation -> scenarios -> conclusion

The two chains must reconcile.

### 4. Preserve economically distinct concepts

Do not allow the system to silently merge:

- business quality
- growth
- earnings power
- expectations
- valuation
- required return
- risk
- catalyst
- sentiment/behavioral factors
- expected return
- margin of safety

A strong business can be a poor investment at an excessive price. A weak business can occasionally be cheap. The model must preserve these distinctions.

### 5. Follow ownership and precedence contracts

For every material field or conclusion, identify:

- source of truth
- calculation owner
- decision owner
- display owner
- fallback behavior
- precedence when multiple sources disagree

Report ambiguous ownership, duplicate authoritative sources, and silent overwrites.

---

# Review protocol

Execute these phases in order. Do not skip phases because the code looks fine.

## Phase 0 — Establish the review target

Determine whether the request concerns:

- the whole RS2 system
- a valuation route
- a specific stage
- a metric/factor
- data ingestion
- evidence/research
- scenario construction
- final assembly
- an architectural change
- a PR/commit

Define the review boundary internally before proceeding.

## Phase 1 — Build the system map

Create an evidence-based map of:

1. Inputs
2. Data provenance
3. Normalization
4. Derived metrics
5. Analytical stages
6. Deterministic calculations
7. LLM judgment points
8. Scenario generation
9. Valuation
10. Guardrails / brakes
11. Audit layers
12. Publication / ledger
13. Outcome feedback

For each transition record:

input -> transformation -> output -> consumer -> authoritative owner

Look specifically for hidden transformations and undocumented defaults.

## Phase 2 — Construct the analytical contract

Before evaluating individual formulas, determine what RS2 is actually claiming to measure.

For each major construct ask:

- What is the formal definition?
- What observable evidence represents it?
- What is excluded?
- What is the time horizon?
- Is the measure point-in-time or retrospective?
- Is it a level, growth rate, spread, probability, or score?
- Can different constructs be correlated or causally downstream of one another?
- Is it used more than once downstream?

If a concept cannot be defined precisely enough to audit, mark the definition gap.

## Phase 3 — Financial statement and accounting integrity

Audit accounting definitions before interpreting any metric.

### Earnings basis

Verify, where relevant:

- GAAP/IFRS basis
- reported vs adjusted
- diluted vs basic shares
- continuing vs total operations
- recurring vs non-recurring items
- consolidated vs segment data

### Cash-flow basis

Verify:

- CFO/OCF definition
- capex definition
- owner earnings / FCF construction
- whether interest is already included or excluded
- lease treatment
- working-capital treatment
- SBC treatment
- restructuring / acquisition effects

### Balance sheet

Verify:

- gross debt vs net debt
- cash and restricted cash
- pension liabilities
- leases
- minority interest
- preferred equity
- non-operating assets

### Valuation bridge integrity

Never assume a cash-flow definition matches the valuation denominator.

Explicitly test whether the flow is:

- levered or unlevered
- pre- or post-interest
- pre- or post-tax
- equity cash flow or enterprise cash flow

Then verify that the bridge to equity value, enterprise value, and market capitalization does not double-count or omit claims.

Use the repository's definitions rather than generic finance conventions.

## Phase 4 — Valuation architecture

Audit every valuation route independently.

For each route determine:

- eligible security/industry archetypes
- trigger condition
- input basis
- forecast horizon
- growth assumptions
- margin assumptions
- reinvestment assumptions
- discount/cost-of-equity assumptions
- terminal assumptions
- share-count treatment
- debt/cash bridge
- output unit
- fallback behavior
- failure behavior

### Reverse valuation / reverse DCF

Verify:

market price -> implied value -> implied operating path -> implied growth/earnings requirement

Check:

- starting financial base
- period alignment
- unit scaling
- dilution
- debt/cash bridge
- discount rate
- terminal value
- terminal growth
- sensitivity
- solvability / numerical stability
- economic interpretability

### Cyclical / mid-cycle valuation

Check:

- cycle normalization methodology
- selected cycle window
- peak/trough contamination
- normalization of margins/earnings
- capital intensity
- whether recovery assumptions are double-counted

### REIT / FFO

Check:

- FFO/AFFO definitions
- recurring capex
- debt treatment
- NAV/FFO consistency
- denominator alignment

### Banks / insurers / regulated utilities

Check whether P/B, ROE, rate-base, or other sector-specific routes are used only where their economic assumptions are valid.

### Biotech / rNPV

Check:

- asset-level separation
- probability weighting
- timing
- cash burn
- financing/dilution
- terminal value logic
- correlated trial/approval risks

### Fallback routes

A fallback is not valid merely because it produces a number.

Test whether fallback selection changes the economic meaning of the output and whether the system clearly exposes valuation-route uncertainty.

## Phase 5 — Expectation architecture

RS2 is expectation-driven. Audit whether the system preserves:

observed business performance
vs
market-implied expectations
vs
future achievability
vs
valuation / return

Check whether the expectations gap uses commensurate bases.

Audit:

- observed growth vs implied growth
- accounting-basis consistency
- time-horizon alignment
- whether expectations include margins, returns, or capital-intensity assumptions
- whether price is treated as an expectation signal rather than proof
- whether achievability is independently evidenced
- whether the model accidentally rewards the same growth twice

## Phase 6 — Double-counting and causal-dependence audit

This is mandatory.

For every score, factor, or synthesis layer ask:

> Is this genuinely independent information, or is it a downstream consequence of another variable already counted?

Build causal chains where necessary.

Typical examples:

revenue growth -> operating leverage -> margin expansion -> FCF growth

ROIC -> reinvestment economics -> growth capacity

debt reduction -> lower interest expense -> EPS growth

Do not automatically remove correlated variables. Determine whether the model intentionally represents separate dimensions or is inadvertently double-counting the same economic driver.

Flag:

- duplicated signals
- nested signals
- highly overlapping scores
- repeated evidence across stages
- factors with different names but materially identical underlying evidence

## Phase 7 — Quantitative validity

Audit mathematical and statistical behavior.

Check:

- units
- percentage vs decimal representation
- annualized vs periodic values
- sign conventions
- missing values
- NaN/Inf handling
- zero denominators
- negative-denominator behavior
- clipping/winsorization
- outlier handling
- interpolation
- aggregation
- weighting
- normalization
- ranking
- percentile calculations
- confidence intervals
- sensitivity analysis

For historical or predictive logic, check:

- look-ahead bias
- future leakage
- point-in-time correctness
- survivorship bias
- stale data
- universe construction
- corporate actions
- benchmark alignment
- training/test contamination
- selection bias
- regime dependence

A statistically elegant transformation can still be economically invalid; review both.

## Phase 8 — Scenario architecture and uncertainty

Audit whether bear/base/bull or other scenarios represent genuinely different economic states.

For each scenario identify:

- changed assumptions
- rationale
- evidence/base rate
- dependencies
- correlated failures
- timing
- valuation consequences

Look for:

- arbitrary percentage spreads
- independent treatment of correlated assumptions
- asymmetric downside assumptions without justification
- bull = high multiple + high growth
- bear = arbitrary haircut
- scenario probabilities without evidentiary basis
- false precision

Distinguish:

parameter uncertainty
from
model uncertainty
from
structural uncertainty.

## Phase 9 — Data and evidence architecture

Audit the chain:

primary source -> extracted fact -> normalized fact -> derived metric -> interpretation -> hypothesis -> conclusion

Every material claim should be traceable.

Check:

- source provenance
- freshness
- period alignment
- point-in-time availability
- source hierarchy
- contradiction handling
- duplicate-source reconciliation
- actual / estimate / assumption / unconfirmed tagging
- silent fallback to stale values
- unsupported narrative
- evidence loss during stage transitions

A model must never convert an estimate into an apparent fact merely by passing it through another layer.

## Phase 10 — Deterministic vs LLM ownership

Identify every place where an LLM can influence the result.

Classify each output as:

- deterministic calculation
- constrained LLM judgment
- free-form interpretation
- final synthesis

For every material judgment ask:

- Is an LLM appropriate here?
- Is the output schema constrained enough?
- Can the LLM override deterministic truth?
- Can prose introduce a number that conflicts with the deterministic engine?
- Can an unsupported claim become authoritative during final assembly?
- Does each material field have a single owner?

The LLM must not become an accidental hidden valuation engine.

## Phase 11 — Architectural integrity

Review software architecture as a representation of analytical architecture.

Check:

- module boundaries
- data ownership
- dependency direction
- circular dependencies
- hidden global state
- cache semantics
- stale-state risks
- retry semantics
- deterministic reproducibility
- stage isolation
- interface contracts
- versioning
- configuration drift
- auditability
- failure containment

A cleaner software architecture is not automatically a better analytical architecture. Judge boundaries by whether they preserve economic and evidentiary meaning.

## Phase 12 — Audit the audit system

RS2 contains audits and gates. Review whether they themselves are valid.

For every gate ask:

- What failure is it intended to catch?
- Can the test actually detect that failure?
- Is it testing the same data the production path uses?
- Can the system pass while the underlying logic is wrong?
- Does the gate create false confidence?
- Is the test deterministic?
- Is its threshold justified?
- Does it cover the highest-risk failure mode?

Pay particular attention to cases where tests are green but the economic result could still be wrong.

## Phase 13 — Trace one conclusion end-to-end

For at least one material conclusion, perform a full provenance trace:

final conclusion
-> valuation result
-> inputs
-> source data
-> transformations
-> stage decisions
-> audit outcomes

At each edge answer:

1. What produced this value?
2. What definition was used?
3. What evidence supports it?
4. What assumptions enter here?
5. Could an upstream error survive this step?
6. Is this value reused elsewhere?

This is the definitive systemic-integrity test.

## Phase 14 — Adversarial / failure-mode review

Try to break the system without changing correct definitions.

Test conceptual failure modes such as:

- levered/unlevered mismatch
- stale financial period
- negative earnings
- negative FCF
- highly dilutive SBC
- acquisition-heavy growth
- extreme working-capital movement
- cyclical peak earnings
- distressed balance sheet
- cash-rich company
- high net debt
- banks/insurers
- REITs
- regulated utilities
- pre-revenue biotech
- foreign-currency reporting
- missing data
- contradictory sources
- unusually high margins
- sudden accounting-policy changes
- share-count discontinuities
- terminal assumptions dominating value

Do not invent failures that the code/data cannot substantiate.

---

# Finding standard

Report a finding only when the evidence supports it.

Use these severities:

### CRITICAL

The system can produce a materially false or internally invalid investment conclusion under normal or credible conditions.

### MATERIAL

The issue can materially distort valuation, expectations, risk, or evidence interpretation, but is not universally fatal.

### MAJOR

The issue affects analytical integrity or important edge cases and should be corrected before relying on the affected output.

### MINOR

A real weakness with limited material impact.

### OBSERVATION

A design consideration or uncertainty that is not currently established as a defect.

Do not inflate severity.

## Required finding format

ID: SR-XXX
Severity: CRITICAL / MATERIAL / MAJOR / MINOR / OBSERVATION
Category: Accounting / Valuation / Expectations / Quant / Evidence / Architecture / LLM-Ownership / Audit
Status: VERIFIED / DERIVED / INFERRED / UNCONFIRMED

Claim
One precise sentence describing the issue.

Evidence
Point to exact files, functions, fields, calculations, tests, or measured outputs.

Mechanism
Explain the causal chain that makes the issue matter.

Impact
Explain what downstream result can be wrong.

Counter-check performed
Show what evidence was checked to avoid a false positive.

Recommended action
State the smallest change that would restore integrity. Do not implement unless explicitly asked.

Residual uncertainty
State what cannot yet be established.

## False-positive discipline

Before reporting a material issue:

1. Check the actual definition of every relevant input.
2. Trace the complete execution path.
3. Check tests and audit logic.
4. Search for compensating logic elsewhere.
5. Verify whether the issue is intentional by documented design.
6. Determine whether downstream normalization already neutralizes the apparent issue.

If the apparent defect is already corrected elsewhere, do not report it as a live defect. Report the interaction only if it creates a distinct systemic risk.

---

# Final report structure

Always produce:

## 1. Executive integrity assessment

Describe the system's current state factually.

State:

- what was reviewed
- what was verified
- what remains unverified
- whether STOP conditions exist
- highest-impact integrity risks

Do not reduce the system to a simplistic numeric score.

## 2. System map

A concise dependency map showing major analytical layers and ownership boundaries.

## 3. Material findings

Findings ordered by materiality and evidentiary confidence, not by code-file order.

## 4. Financial-model audit

Accounting, valuation, expectations, scenario, and economic-logic findings.

## 5. Quantitative/model-risk audit

Statistical, numerical, temporal, and sensitivity findings.

## 6. Evidence/provenance audit

Traceability, source integrity, freshness, and fact/estimate/assumption classification.

## 7. Architecture audit

Whether software structure faithfully preserves analytical meaning.

## 8. Audit-system audit

Whether tests and gates can actually detect the most consequential failures.

## 9. End-to-end trace

One concrete conclusion traced back to source evidence.

## 10. STOP conditions

Issues where the repository lacks enough evidence to support a valid conclusion or implementation.

## 11. Remediation sequence

Use the dependency order:

definition -> methodology -> data -> implementation -> tests -> audit

Do not recommend implementing a downstream fix before the upstream definition is proven.

---

# Scope behavior

### Architecture-only review

Focus on analytical ownership, deterministic vs probabilistic boundaries, evidence lineage, state/version semantics, and failure containment.

### Financial-methodology review

Focus on accounting, valuation, expectations, scenarios, causal logic, and model risk. Ignore ordinary implementation details unless they alter the financial result.

### PR review

Review changed behavior and inspect upstream/downstream contracts necessary to determine whether the change is logically correct. Do not restrict the review to changed lines when surrounding context can invalidate the conclusion.

### Proposed feature review

Determine whether the feature is conceptually required, empirically supported, and compatible with the existing analytical architecture. Do not add complexity merely because another system uses it.

### Implementation request

Do the systemic review first. Then implement only the verified fix, add targeted tests, and re-run the relevant audit path.

---

# Anti-patterns to hunt

- textbook formula applied to a differently defined input
- double counting
- hidden denominator mismatch
- unspoken leverage assumptions
- mixed time horizons
- stale or non-point-in-time information
- silent fallback behavior
- duplicated sources of truth
- model output overriding deterministic truth
- narrative overriding numbers without evidence
- weights chosen without rationale
- scores presented as independent when causally linked
- scenario ranges chosen for symmetry rather than economics
- valuation routes producing numbers despite invalid inputs
- tests proving execution but not correctness
- gates creating false confidence
- reasonable substitutions made because better data is unavailable
- final conclusions that cannot be traced to source evidence

# Non-negotiable standard

Do not ask only:

> Does this code work?

Ask:

> Does the software correctly implement the intended financial model?

Then ask:

> Is the intended financial model itself conceptually and economically valid?

And finally:

> Can every material conclusion be reconstructed, challenged, and reproduced from source evidence through the final conclusion?

