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

## Architecture

Valuation is **deterministic Python**; the LLM never supplies a number for a DCF-able name.
`valuation_backbone.py` solves the growth the market price implies (reverse DCF on blended owner
earnings, two-stage 5+5, sector cost-of-equity table) and compares it to demonstrated growth. The
**expectations gap** is the headline signal, ranked cross-sectionally against the book
(`cache/mos_distribution.json`). The LLM contributes judgment only: an achievability stance, an
earnings-basis choice on contested names, conviction, and prose. Verdicts pass a deterministic
don't-chase brake, then a two-tier audit (deterministic reproducibility, then AI contradiction
audit) before anything publishes.

| Level | Entry point | What it does |
| --- | --- | --- |
| Sweep | `orchestrate.py` | queue by band/cadence, data-health gate, MoS calibration, per-ticker runs, overlay/publish/ledger, git push. **Never run directly** — a bare run pushes to the live site. Use `tools/run_batch.py`, which forces `--no-push`, takes the lock and writes a git-SHA receipt. |
| Per ticker | `run_rs2.py` | enrich (yfinance), OpenBB cache, deep research, backbone, five LLM stages, final assembly to `verdict.json` with brake and tripwires, sanity, tier-1 and tier-2 audits. |

Depth publishing lives in `orchestrate_depth.py` and targets `CONFIG['screener_publish_repo']`,
resolved through `paths.py`. It refuses to run if that path is not a git clone. Never repoint it at
the shared `stock-screener` tree — see non-negotiable 6 in the workspace file.

`api_llm/cloud_backstop.py` reads that same clone but never writes to it: it counts the published
overlay and fails closed, because a live overlay is never empty and a count of zero means the guard
is blind. Do not "fix" that branch into a warning — being blind is exactly the wipe it prevents.

Scheduling is the Windows task "RS2-Orchestrator" (`register_orchestrator_task.ps1`). Pause with
`cache/PAUSED`; monitor with `status.py` or `telegram_status_bot.py`.

`README.md` is the long-form description and is kept current with the code. If this file, the
README and the code disagree, the code wins — and per section 0 you fix the document in the same
change.

## Testing — the canonical invocation

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
