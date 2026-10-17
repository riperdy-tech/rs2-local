# Brief H: the `ollama_raw` provider, where our code renders Qwen's prompt and reads Qwen's tool calls (operator, 2026-10-17)

## Why
Ollama 0.40.3 (auto-updated 2026-10-11) drops array-typed properties inside array items from Qwen tool calls:
- the scenarios' `explicit_growth`, `revenue_growth` and `earnings_margin` arrive missing;
- the cause is upstream of its parser, triggered by the tool schema;
- the record is `PHASE_4_AMENDMENTS.md`, "Why Ollama drops the nested lists".

The operator chose to take tool rendering and tool-call parsing into our own code, so that no Ollama update can silently change them again.
**Ollama stays the engine** (the same tag, its MTP speed-up and sampling), used as plain text in, text out.

## Workspace
- **Branch:** create `review-2026-10/ollama-raw` from `9ed16fc`, in a worktree at
  `stocks-workspace/scratch/rev23/wt-ollama-raw`:
  `git -C C:/Users/riper/stocks/rs2-local worktree add -b review-2026-10/ollama-raw ../stocks-workspace/scratch/rev23/wt-ollama-raw 9ed16fc`.
- **Commit there by pathspec.**
- **Limits:**
  - never push, merge or deploy; no GPU and no model calls (the coordinator runs the live test); never edit `.env*` or config defaults;
  - no bare `git stash`;
  - read the code by section;
  - **the existing `"ollama"` and `"llamacpp"` providers must stay byte-identical in behaviour.**

**Read first:** `rs2-local/AGENTS.md`, and `tools/audit_202608/llm_provider.py` (how the `"ollama"` provider builds its request and
returns its result).

## Build: a third value of `depth_provider`, `"ollama_raw"`
1. **The template.** `stocks-workspace/scratch/rev23/ollama_raw/chat_template_qwen38_v33.jinja` is the model's official Jinja chat
   template (from `ollama show rs2-analyst-deep-mtp5-v33 --template`, sha256 prefix `12827f24b742ea4e`).
   - Copy it into the repo at `charters/chat_template_qwen38_v33.jinja` and pin its sha256 in the provider. Refuse if the file differs.
   - Render with `jinja2` (3.1.6 is in the system Python).
   - Pass `messages`, `tools` (exactly the tool list the harness already builds), `add_generation_prompt=True`, and
     `enable_thinking`/`reasoning_effort` mapped from the harness's think setting ("high" → `reasoning_effort` "high", thinking on;
     false → thinking off).
   - Give any template helper it needs (e.g. `raise_exception`, `tojson`) the same meaning as Hugging Face's `apply_chat_template`.
   - **Do not edit the template.**
2. **The request.** POST `/api/generate` with `raw: true`, the rendered prompt and the **same** model, options, seed, `num_ctx`,
   `num_predict` and keep-alive the `"ollama"` provider sends.
   - **No `tools` field and no `think` field:** the template carries both.
   - Use streaming only if the `"ollama"` provider does, and keep its timing and metadata fields where /api/generate gives them.
3. **The reader** (a new module, `tools/audit_202608/qwen_tool_reader.py`, pure functions).
   - **Input:** the raw completion. **Output:** the same result shape the `"ollama"` provider returns: `content`, `thinking`, and
     `tool_calls` as [{function: {name, arguments}}].
   - **Thinking:** the text up to `</think>`, since the generation prompt may already open `<think>`.
   - **Tool calls:** each `<tool_call><function=NAME><parameter=KEY>VALUE</parameter>…</function></tool_call>`.
   - **Values are converted by the tool's top-level schema type for that parameter,** as Ollama's `qwen3coder.parseTypedToolValue`
     does:
     - strip one leading and one trailing newline;
     - array or object: `json.loads`, kept whole, nested values never filtered;
     - number or integer: numeric, with no int64 clamping, because Ollama issue #18421 is a known bug to avoid;
     - boolean;
     - otherwise string;
     - unparseable JSON for an array or object stays as the raw string.
   - **Malformed or truncated tool-call markup:** no call is made, and the text stays in `content`.
4. **Multi-turn.** The harness sends earlier assistant turns (with their tool calls) and tool results back. Render them through the same
   template from the message list the harness keeps: assistant `tool_calls` with arguments as dicts, `role: "tool"` results. Nothing the
   model wrote is re-serialized differently from what the template expects.
5. **Stamps.** Each result records `provider: "ollama_raw"`, the template sha256 and the Ollama version.

## Tests (system Python; targeted only)
- **The reader:**
  - nested arrays inside an array of objects (the exact scenarios payload from the record) round-trip exactly;
  - two tool calls in one turn;
  - a string parameter containing newlines and `<`;
  - malformed markup;
  - a turn with only thinking;
  - numbers above the int64 range.
- **The renderer:**
  - the rendered prompt for a fixed fixture (system, user, assistant with a tool call, a tool result, user) is pinned as a golden file;
  - the tool block contains the full nested schema, including the `items` properties;
  - the thinking flags change only the expected generation-prompt suffix.
- **The provider:**
  - with a stub HTTP server, `"ollama_raw"` sends `/api/generate` with `raw: true` and no `tools`, and returns the reader's result in the
    `"ollama"` shape;
  - `"ollama"` and `"llamacpp"` requests are byte-identical to before (an existing test, or a new one against `9ed16fc`).
- **The full suite is not required;** the coordinator runs it.

## Report (at most 50 lines)
- the commits and files;
- the test counts;
- how think "high" maps;
- anything in the template that needed a helper;
- ambiguities.
