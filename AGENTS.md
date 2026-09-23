# rs2-local

The depth underwriting pipeline. Runs the RS2 expectations-investing framework over the screener's
research_now / watchlist book on a local Ollama model, publishes verdicts to the screener site
overlay, and keeps an append-only, graded track record.

Workspace-wide rules — path resolution between repositories, the ten non-negotiables, working
style — are in [../AGENTS.md](../AGENTS.md) and are not repeated here. This file carries only what
is specific to this repository.

## 0. Standard of proof — overrides everything else

**This project performs financial valuation. Logic and code must be institutional-grade and
PhD-level. There is no "good enough", no "largely correct", no "reasonable approximation".**

- **No assumptions.** If a step rests on something unproven, it is not done. State the claim, then
  prove it with measured data from this repository — not from reasoning, memory, or plausibility.
- **No skipping.** Every branch, every edge case, every population the change touches.
- **Never build to fit the available data.** If the data cannot support the correct method, the
  answer is NOT to substitute a weaker method that the data happens to allow. Say so and stop.
- **Fact-check, verify, inspect, audit.** A claim is not established until it has been measured
  across the actual corpus. "It should be fine" and "this is standard practice" are not evidence.
- **Gaps are STOP conditions.** On encountering a data gap, a threshold that cannot be justified
  from measurement, or a method whose correctness cannot be demonstrated: raise a flag, explain
  precisely what is missing and what it invalidates, and wait for approval. Do not proceed with a
  partial or best-effort implementation.
- **Every detail must be fool-proof and proven**, including the ones that look obvious.

**Why this is written down:** a change was shipped on the reasoning "operating cash flows should be
compared to enterprise value" — textbook-correct in general, and wrong here, because `base_cf` is
`net income + D&A − capex` and net income is already net of interest. That makes it a LEVERED flow,
so bridging to enterprise value subtracted the debt claim twice. The argument sounded rigorous and
was never checked against the definition of the input. Measure first. Every time.

## 1. Valuation doctrine — Charter v3.0 (the v3.1 revision is the Phase 4 target)

This governs prompt engineering, valuation logic, research synthesis and execution models in this
repository. It is the repository-specific half of the standard above.

### Systemic integrity over band-aids

When an analytical flaw or counter-example is uncovered, **never** implement a superficial prompt
tweak that fixes that one company or sector. Identify the overarching methodological defect —
flawed accounting normalization, missing installed-base modeling, rigid multiple caps, unrealistic
bear-case distributions — and fix the valuation architecture universally across all archetypes.
This is non-negotiable 2 in the workspace file, stated here in valuation terms.

### Complete economic machinery, not backward-looking accounting

Accounting statements record past cash and accruals. Economic value is determined by future
sustainable cash generation and competitive advantage.

**Installed-base and lifecycle monetization.** Where upfront bookings drive multi-decade aftermarket
services, spare parts, software subscriptions or maintenance contracts — power generation,
aerospace, semiconductors, medical systems:

- Customer advance commitments and contract liabilities are **leading indicators of installed-base
  expansion**, not merely working-capital noise.
- The multi-decade, high-margin aftermarket annuity must be modeled explicitly into terminal
  earning power, never erased by a simplistic working-capital deduction. Stripping out cash inflows
  while ignoring decades of locked-in cash flows is forensic tunnel vision.

**No terminal-multiple dogmatism.** A single-stage Gordon Growth terminal value with a static GDP
growth cap mechanically forces exit multiples into a narrow band, which systematically rejects
elite compounders and favors decaying value traps. Terminal multiples are anchored mathematically
to the prevailing risk-free rate and cost of capital — `terminal multiple ≈ 1 / (WACC − g)` — and
must reflect competitive durability, secular growth drivers and the macro regime. The rates come
from the MRI anchors through `rs2_data.anchor_*` accessors; there is no fallback constant, because
a substituted rate is the defect those accessors exist to end.

### Scenario dispersion and realistic risk bounds

A bear case must represent a severe but **plausible** cyclical downturn or operational misstep —
never a mathematical absurdity such as projecting an industry leader with a multi-year contracted
backlog into near-zero margins. It is bounded below by the contracted visibility floor (backlog and
service-annuity durability). If the model's bear case is wildly disconnected from the most
pessimistic institutional bears in the market, inspect the scenario assumptions for catastrophic
bias rather than accepting the number.

## 2. Architecture

The depth tier is production. The model produces its own valuation from the static data the pack
supplies plus live primary-source research; code supplies the data and judges the output with two
guards — plausibility and repeatability. Every verdict ends in a machine-readable Section 12
contract.

| Level | Entry point | What it does |
| --- | --- | --- |
| Sweep | `orchestrate_depth.py` | membership snapshot, trigger-driven queue, data-health gate, one child at a time under a watchdog, ledger append, overlay rebuild, publish |
| Per ticker | `depth_pipeline.py` | bounded research, adaptive 2-escalate consensus, medoid scorecard, fiduciary contract gate, sanity audit |
| Consensus | `tools/audit_202608/consensus_valuation.py` | seeded samples with tools; early-stops at n=2 when the pair agrees within 15%, else escalates to a third |
| Research tools | `tools/audit_202608/analyst_tools.py` | SearXNG search during reasoning, every query and page snapshotted into the run directory |
| Gate on read | `depth_gates.py` | single owner of what makes a published verdict `actionable`; annotates the ledger row, never mutates or drops it |
| Live price | `price_now.py` | live quote at verdict time via yfinance, staleness-refusing; `depth_pipeline.main()` hard-fails (exit code 8) without one |

Valuation support remains deterministic Python: `valuation_backbone.py` solves the growth the
market price implies and is consumed as evidence, not as the published number.

Depth publishing lives in `orchestrate_depth.py` and targets `CONFIG['screener_publish_repo']`,
resolved through `paths.py`. It refuses to run if that path is not a git clone. Never repoint it at
the shared `stock-screener` tree — see non-negotiable 6 in the workspace file.

`api_llm/cloud_backstop.py` reads that same clone but never writes to it: it counts the published
overlay and fails closed, because a live overlay is never empty and a count of zero means the guard
is blind. Do not "fix" that branch into a warning — being blind is exactly the wipe it prevents.

Scheduling is the Windows task "RS2-Depth-Orchestrator" (`register_depth_task.ps1`), every four
hours. Pause with `cache/DEPTH_PAUSED`; monitor with `status.py` or `telegram_status_bot.py`.
`DEPTH_PAUSED` does **not** stop the cloud continuity arm (`api_llm/cloud_backstop.py`, GitHub
Actions) — it gates only on off-peak hours and PC heartbeat and reads nothing under `cache/`.

The pre-Charter five-stage pipeline (`run_rs2.py`, `orchestrate.py` and their Modelfiles) is
retired under `_archive/retired_20260920/`. It is history, not a fallback — do not restore a path
from it to work around a defect in the depth tier.

`README.md` is the long-form description and is kept current with the code. If this file, the
README and the code disagree, the code wins — and per section 0 you fix the document in the same
change.

## 3. Testing — the canonical invocation

No single virtual environment covers this repository, so the interpreter matters:

| Environment | Has | Use for |
| --- | --- | --- |
| **System Python 3.12** (`C:\Program Files\Python312\python.exe`) | pytest, pandas, numpy | **The test suite.** `research-venv` has NO pytest. |
| `research-venv` | pandas, numpy, trafilatura, typer | the deep-research (LDR) subprocesses |

```bash
"C:\Program Files\Python312\python.exe" -m pytest tests tools/audit_202608/tests -q
```

`tests/test_sync_state.py` shells out to `git clone` of a local bare repository. Under a restrictive
sandbox that fails with `sh.exe: couldn't create signal pipe, Win32 error 5` — an environment
restriction on named pipes, not a code defect; with normal file access it passes. If exactly those
tests fail and everything else is green, check the sandbox before touching `sync_state.py`.
