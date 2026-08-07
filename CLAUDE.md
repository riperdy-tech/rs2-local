# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 0. Standard of Proof — OVERRIDES EVERYTHING BELOW

**This project performs financial valuation. Logic and code must be institutional-grade and
PhD-level. There is no "good enough", no "largely correct", no "reasonable approximation".**

- **No assumptions.** If a step rests on something unproven, it is not done. State the claim, then
  prove it with measured data from this repo — not from reasoning, memory, or plausibility.
- **No skipping.** Every branch, every edge case, every population the change touches.
- **Never build to fit the available data.** If the data cannot support the correct method, the
  answer is NOT to substitute a weaker method that the data happens to allow. Say so and stop.
- **Fact-check, verify, inspect, audit.** A claim is not established until it has been measured
  across the actual corpus. "It should be fine" and "this is standard practice" are not evidence.
- **Gaps are STOP conditions.** On encountering a data gap, a threshold that cannot be justified
  from measurement, or a method whose correctness cannot be demonstrated: RAISE A FLAG, explain
  precisely what is missing and what it invalidates, and WAIT FOR APPROVAL. Do not proceed with a
  partial or best-effort implementation.
- **Every detail must be fool-proof and proven**, including the ones that look obvious.

**Why this is written down:** a change was shipped on the reasoning "operating cash flows should be
compared to enterprise value" — textbook-correct in general, and wrong here, because `base_cf` is
`net income + D&A − capex` and net income is already net of interest. That makes it a LEVERED flow,
so bridging to enterprise value subtracted the debt claim twice. The argument sounded rigorous and
was never checked against the definition of the input. Measure first. Every time.

Corollary: when a check contradicts a previous statement of yours, say so plainly and correct it in
the same breath. An error carried forward silently is worse than the error itself.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
