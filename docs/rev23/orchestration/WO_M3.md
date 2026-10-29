# WO_M3: `qwen_c` prompts, output contract and runner (builder B)

- **Milestone:** 3M.
- **Spec:** `SPEC_m3m_qwen_pipeline.md` §1, §4, §5, §6 and the M-CONTRACT / M-ERR / M-REC rows of §7. Read the spec first;
  it is the contract.
- **Worktree:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3m` (branch `review-2026-10/m3m-qwen`, based on
  `r26-harness` `481d0cf`).
- **Write only these files:**
  - `qwen_c/tasks.py`, `qwen_c/contract.py`, `qwen_c/runner.py`
  - `qwen_c/tests/test_contract.py`, `qwen_c/tests/test_runner.py`, `qwen_c/tests/test_tasks.py`
  - fixtures under `qwen_c/tests/fixtures_b/`

  Another builder is writing `qwen_c/__init__.py`, `qwen_c/tests/__init__.py`, `sec_store.py`, `packet.py` and
  `replay.py`. **Do not touch them.** If you need `__init__.py` before they exist, create empty ones only if absent.
- **Do NOT:** commit, push or check out; run any model, contact a real Ollama server or use the GPU (tests use a stub
  HTTP server on localhost, as `tools/audit_202608/tests/test_ollama_raw.py` does); read `.secrets.json` or any `.env*`;
  edit any file outside the list.

## Requirements

**Reuse:**
- `tools/audit_202608/ollama_raw.py` (`chat(body, timeout, url)`, `RawProviderError`, `ollama_version`,
  `TEMPLATE_SHA256`);
- `tools/audit_202608/turn_log.py` (activation API: read the module);
- `tools/audit_202608/llm_provider.py` (`ollama_serving(model)`, `OLLAMA_URL`);
- `ops.py` (`wait_unloaded`).

Find how existing modules import from `tools/audit_202608` (the `sys.path` pattern) and follow it. Read `ollama_raw.py`
fully first: `qwen_c` calls `ollama_raw.chat` directly, sends its own system message, and passes `think` exactly as the
template expects (see `think_kwargs`).

**Your input is the packet dict of spec §3.** Build synthetic packets in tests; do not depend on `packet.py`. The
rendering of a packet into the user message lives in `tasks.py`.

**Prompts:**
- Write the shared SYSTEM text (at most 400 words) and the seven task instructions yourself, following spec §4.
- Each instruction includes the exact JSON shape required.
- Keep them plain and short. No investment-committee language, no valuation, no buy/sell vocabulary.
- `PROMPT_VERSION = "m3m.prompt.v1"`.
- Add a test that pins the sha256 of the SYSTEM text and of each instruction, so that any later change to what the
  model is told fails a test until the version is bumped.

**Contract (`contract.py`):**
- The validator and the support checks of spec §5.
- For figure tokens, reuse `sec_primary.figure_tokens` / `item_figures` / `figure_in` (repository root) where they fit.
  Read them first.
- **Number-matching rule:** a number in `numbers` is found when its value, at the scale written, appears in a cited
  item's text (normalised). `1.2 billion` is NOT matched by `1,200` unless the item states `million` in that context.
  When unsure, mark the number `number_not_found`. A false "supported" is the failure we must never have.

**Runner:**
- Implement spec §6 exactly: statuses, retries, timeouts and records.
- **Parse:** extract the single fenced `json` block. If none, try the whole content as JSON. Else `malformed`.
- **Thinking:** keep it in `raw/`, never in `analysis.json`.
- `run_id` uses a counter `_n` so a re-run never overwrites.
- **The `KIS_HALT` check:** read how the repository resolves `KIS_HALT` (search the code) and refuse when it is not in
  force. If it is not determinable from rs2-local, record `kis_halt: "not_resolvable_in_rs2"` in the manifest and
  proceed. Do not guess a path.
- The `qwen_c` git commit and dirty flag come from `git rev-parse HEAD` and `git status --porcelain` in the worktree.
- A CLI: `python -m qwen_c.runner <packet.json> [--num-predict N] [--think low|medium|high] [--url ...]`.

**Tests:** every M-ERR case of spec §7 against a stub server, every M-CONTRACT fixture, and M-REC (all records exist
and every recorded sha recomputes).

Run with `"C:\Program Files\Python312\python.exe" -m pytest -q -p no:cacheprovider qwen_c/tests` from the worktree root.

## Return report

Write `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\rev23\orchestration\RR_M3.md`, at most about 120
lines:
- the files;
- the test count and result;
- the full SYSTEM text;
- the number-matching rule as implemented, with examples;
- every deviation from the spec and why;
- anything you could not do.

If you cannot write that file, return the report as text.
