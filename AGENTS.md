# rs2-local

The AI analyst's pipeline. It reads each company's SEC filings with a cloud model, values the company with
code, publishes the result to the screener site, watches the news on the stocks it has analysed, and keeps the
monthly paper books. Since 2026-11-20 the reader is Gemini, with Claude Sonnet as the fallback; the local model
(Qwen through Ollama) is retired and no GPU is used (operator, 2026-11-20). The older depth tier (section 2b) is paused.

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

## 1. Valuation doctrine — Charter v3.1

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

### Timing, momentum, and current-world awareness (Phase 4, mandates 7–8)

Value decides *whether* to own a business; price action decides *when* — the analyst must
reconcile both and may ignore neither. Every verdict states `momentum_view`
(`confirming|neutral|contradicting`) against the pack's price-only SECTION 2.5 (never the
screener's own opinion — no nomination door, rank or band is shown to the model) and
`entry_timing` (`buy_now|wait_for_momentum|avoid`), each backed by a checkable
`momentum_flip_condition`/`momentum_break_rule`. The model's own knowledge stops at its training
cutoff; SECTION 1.6 ("state of the world" — MRI regime, active shocks, rates, inflation, the news
theme summary) and the research brief carry what happened since. The brief is another model's
unverified output: every figure in it is a claim to check against the filings, and the filings
win on conflict (`research_wrong_company` refuses a brief about the wrong company outright).

### The desk is mandatory for the answer

`base_iv` must equal a `run_financial_model` per-share result (or a named desk `blend`) within
1% — no undisclosed "judgement" IV. The desk runs a funded-growth DCF (explicit growth for years
1-5 less the pack's working-capital schedule, held at the consensus year-1 and year-2 levels for the
Base unless `guidance_deviation_reason` is given; from year 6 a declared `fade_years` fade to
`terminal_g`, which is a **required** parameter — no silent default — with growth paid for at the
return on new investment the company's own record supports, `terminal_ronic`; the terminal is that
funded form only: revision 17 removed the exit multiple and the terminal leg), values at the base
fiscal year end rolled forward to today, reconciles the implied terminal multiple against the MRI
sector band, and enforces the valuation frame (`equity`/FCFE at cost of equity vs. `firm`/FCFF at
WACC — a frame mismatch is a structured refusal, not a silent miscalculation). The record is measured
by `tools/throughcycle_record.py` (long-run earnings are net income before acquired-intangible
amortization; the long-run margin moves toward the company's 8-year median operating margin (its pre-tax
margin, where no operating line is filed) by the fraction measured in `tools/reference_calibration_v2.json`;
the downturn test (a fiscal year with revenue down at least 5% and earnings down at least a third) is an
annotation and moves no number; returns are on tangible invested capital before interest, and the return
on new capital blends the 8-year and latest-3-year medians, capped at 100%; short-term debt is subtracted
once) and the arithmetic of the long run is one function, `consensus_reference.long_run_value`, shared by
the pack's reference and the desk. Cost of equity
must sit within ±150 bp of the pack's SECTION 1.5 anchor or declare `coe_source: "own"` with a
reason.

## 2. What runs today (since 2026-11-20)

The reader reads; code values. A model never does valuation arithmetic and never writes the published number.

| Part | Where | What it does |
| --- | --- | --- |
| Packet | `qwen_c/packet.py`, `qwen_c/sec_store.py` | builds one company's evidence packet from its SEC filings at a decision time |
| Reading | `qwen_c/runner.py`, `qwen_c/tasks.py`, `qwen_c/contract.py` | runs the reading tasks on a packet; every claim carries a quote that code checks against the packet. Thinking effort is high, always |
| Valuation | `qwen_c/value/`, `tools/site/decided_*.py` | code values the company from the filings and the reading's checked claims, at two seeds |
| Site worker | `tools/site/gemini_ondemand.py` (task `RS2-Gemini-Site`) | analyses the screener list and the requests, re-reads a stock after a new filing, publishes to the site. It swaps only the function that sends a request to the model: Gemini through `agy`, Claude Sonnet when Gemini's allowance is under its floor |
| News watch | `tools/site/news_watch.py` (task `RS2-News-Watch`, 06:00 KST) | gathers the day's news on every analysed stock, has the reader check it against that stock's own points, warns once by Telegram and on the site, queues a capped re-read. It is also the watch on held names (the stocks the reader rates BUY, which the AI book holds): for those, code adds a critical 8-K and a large price move, and their re-reads go first. It never sells. The old holdings monitor (`tools/holdings_monitor/`, task `RS2-Monitor-Daily`) is disabled and kept; the news watch borrows its news filters, price reader and price rules |
| Paper books | `tools/paper_books/` | the monthly formation, the forward ledger and the engine marks, kept in `rs2-state` |

The package is still named `qwen_c` and some files and data keys still say `qwen`: that is a name, not the model in use.
`tools/site/qwen_ondemand.py` and `qwen_site.py` supply shared code to the cloud worker; their own scheduled task is disabled.

The site worker runs from its own working tree, not from this checkout; its lock is `cache/gemini_site/worker.lock` in that tree.
Change that tree only when the lock is absent. Requests and the filing queue live in this checkout's `cache/site/`.

## 2b. The depth tier (paused by `cache/DEPTH_PAUSED`; kept, not running)

The depth tier was production until the cloud readers replaced it for the site. The model produces its own valuation from the static data the pack
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
| Screener data refresh | `screener_refresh.py` | resets the dedicated publish clone to `origin/main` before every entry point reads it; refuses the whole run on failure; stamps `screener_data_commit` |
| Thesis monitor | `thesis_monitor.py` | re-checks each actionable verdict's `invalidation_rules` against current data; writes `cache/depth_thesis.json`; feeds the `thesis_break`/`momentum_flip` triggers; also runs standalone via `--monitor` (no GPU) |
| Desk | `tools/audit_202608/financial_model_tool.py` | the only place valuation arithmetic runs: funded-growth DCF with one terminal, frame-checked, both reverse-DCF structures, named `blend` legs |

Valuation support remains deterministic Python: `valuation_backbone.py` solves the growth the
market price implies and is consumed as evidence, not as the published number.

Depth publishing lives in `orchestrate_depth.py` and targets `CONFIG['screener_publish_repo']`,
resolved through `paths.py`. It refuses to run if that path is not a git clone. Never repoint it at
the shared `stock-screener` tree — see non-negotiable 6 in the workspace file.

Scheduling is the Windows task "RS2-Depth-Orchestrator" (`register_depth_task.ps1`), every four
hours. Pause with `cache/DEPTH_PAUSED`; monitor with `status.py` or `telegram_status_bot.py`.
The DeepSeek cloud continuity arm (`api_llm/` and its GitHub Actions workflow) was disabled on GitHub
and archived to `_archive/retired_20261103/` on 2026-11-03 (operator). There is no cloud arm now.

The pre-Charter five-stage pipeline (`run_rs2.py`, `orchestrate.py` and their Modelfiles) is
retired under `_archive/retired_20260920/`. It is history, not a fallback — do not restore a path
from it to work around a defect in the depth tier.

The depth tier's analyst model is served through `tools/audit_202608/llm_provider.py` with `depth_provider` `ollama` or
`ollama_raw` only; with the local model retired on 2026-11-20 nothing calls it now. The Muse / llama.cpp provider (`llamacpp_server.py`, `llamacpp` config block) and the retired
Modelfiles (plain MTP5, v31, v32, the Q4 family) were archived 2026-11-03 under `_archive/retired_20261103/`
(`README_muse.md`); `"llamacpp"` in config is refused.

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
"C:\Program Files\Python312\python.exe" -m pytest qwen_c/tests -q
"C:\Program Files\Python312\python.exe" -m pytest tools/site -q
"C:\Program Files\Python312\python.exe" -m pytest tools/paper_books -q
"C:\Program Files\Python312\python.exe" -m pytest tools/holdings_monitor -q
```

Run the suite of the part you touched, one pytest process at a time (the machine has about 12 GB of memory), and run it in a
separate working tree (`git worktree`), not in this checkout: scheduled tasks read and write this checkout's `cache/` while they run.

`tests/test_sync_state.py` shells out to `git clone` of a local bare repository. Under a restrictive
sandbox that fails with `sh.exe: couldn't create signal pipe, Win32 error 5` — an environment
restriction on named pipes, not a code defect; with normal file access it passes. If exactly those
tests fail and everything else is green, check the sandbox before touching `sync_state.py`.
