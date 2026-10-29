# WO_M1: 3M inventory of the existing Qwen pipeline

- **Milestone:** 3M (PLAN §3M, work items 1–2). **Executor:** Claude, with one read-only Explore subagent.
- **Goal:** know exactly what can be reused before designing the 3M pipeline: the model and runtime, the invocation
  path (`ollama_raw`), the input pack, the output contract, error handling, run records and tests.
- **Scope:** read-only. No model run, no GPU job, no `ollama create`, no checkout of the live rs2 tree, no commits.
- **Acceptance:** `RR_M1.md` lists, with citations, (1) the installed model tags, digests, the Ollama version and the
  GPU state; (2) the reusable modules per area; (3) what revision 26 contains that must not be reused; (4) the gaps
  against PLAN §3M work items 3–8 and SPEC_factor_led_v2 §4.
- **Budget:** one subagent and about one hour.
