# RR_M1: inventory of the existing Qwen pipeline (2026-10-29)

**Result:** DONE. The inventory was made by a read-only Explore agent from git objects. Claude spot-checked it against
the code:

- `r26-harness` is `481d0cf`, 39 commits above `e82a08b`, and its `run_stage2/3/4` are `NotImplementedError` stubs.
- `ollama_raw.TEMPLATE_SHA256` and the template refusal are present.
- `turn_log.log_turn` stores the prompt only as a sha256.
- The overflow guard is present.

## Runtime (observed 2026-10-29 00:40Z)

- Ollama **0.40.6**. The tag `rs2-analyst-deep-mtp5-v33` is id `f0f5ce2dcea3`, 19 GB, architecture qwen35, 27.3B,
  Q5_K_M. It has a 262,144 context and the tools/thinking capabilities.
- Modelfile sampling: temperature 0.6, top_p 0.95, top_k 20, min_p 0, repeat_penalty 1. Its SYSTEM is the 2,400-word
  charter v3.3; a request that sends its own system message replaces it.
- RTX 3090: 34 MiB of 24,576 MiB used, and no model loaded.

## Reusable

| Area | Reuse | Note |
|---|---|---|
| Invocation | `tools/audit_202608/ollama_raw.py` (`chat`, template pin, overflow guard, `ollama_version`), `turn_log.py`, `llm_provider.ollama_serving` (manifest and system-layer digests), `ops.wait_unloaded` | Only on the branches from `ollama-raw` on; base `r26-harness` |
| SEC text | `sec_primary.py` helpers: HTML cleaning `blocks_of`, `select_text` with omission markers, `canonical`, `pick_segment_report`, figure tokens; `sec_guidance.UA` | `sec_primary` filters by `filingDate`, **not** by acceptance: 3M applies the acceptance rule itself |
| SEC acceptance rule | `m3l_sec_pit_asof.py` (`accepted_at` takes the later of the UTC and Eastern readings; `effective_at` is the next full NYSE session, plus one after 17:30 ET), policy id `sec_acceptance_next_full_xnys_session_late_after_1730_plus_one_v1` | Re-implemented in rs2 (no cross-repo import) |
| Tests | `test_ollama_raw.py` (stub HTTP server), `test_llm_provider_window_and_retries.py` | Patterns to copy |

## Not reused (revision 26 valuation, frozen)

The following stay out of `qwen_c`:
- `tools/r26_forecast.py`, `tools/r26_spread.py`, `r26_late.py`;
- `r26_stages.py` from stage 2 on;
- the `r26` arm of `consensus_valuation.py`;
- the desk schemas 25.x and D2.

`qwen_c` imports none of them.

## Gaps against PLAN §3M (addressed by SPEC_m3m_qwen_pipeline.md)

- **Output:** there is no output schema; the verdict contract is a key list in `extract_scorecard`. **There is also no
  `analysis_incomplete` state anywhere**, and per-claim source references exist only in revision 26's stage 1.
- **Records:** the Ollama version, `num_ctx`/`num_predict` and the penalties are not recorded per run. The prompt text
  is stored only as a hash.
- **Pack markers:** they are inconsistent (`PACK_REVISION_R26 = 28` but the header prints 27, and `consensus.json`
  stamps 24). This is history: `qwen_c` has its own `m3m.packet.v1` and `m3m.prompt.v1`.
- **Holds:** `model_release_blocked` exists in no rs2 code; it is a receipt field in the 3C–3K reports only.
  `DEPTH_PAUSED` is the file `cache/DEPTH_PAUSED`.
