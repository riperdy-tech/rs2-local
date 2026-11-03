# Muse / llama.cpp serving path and retired Modelfiles, retired 2026-11-03

Moved here in the post-review cleanup (stocks-workspace `docs/review_2026-11-03/B_rs2_local.md` §5.2), operator-approved
2026-11-03. `config.json` `depth_provider` was `"ollama"`, so every branch below was dead at runtime. The live analyst now
has one serving family: `ollama` and `ollama_raw` (`tools/audit_202608/llm_provider.py`, used by `qwen_c`). A config that
still says `"llamacpp"` is refused with an error naming this archive; it never falls back to another provider.

What moved (paths mirror the originals):

- `llamacpp_server.py` - the llama-server lifecycle (start, stop, status, pins, `begin_run`).
- `charters/SYSTEM_muse_v33.txt`, `tools/make_muse_system.py` - the Muse SYSTEM text and its generator.
- Tests that existed only for that path: `tests/test_llamacpp_*.py`, `tests/llamacpp_fakes.py`,
  `tests/fixtures/mock_llama_server_process.py`, `tests/fixtures/ollama2llamacpp.py`, `tests/fixtures/b11272_manifest.json`,
  `tests/test_muse_system.py`, `tests/test_llm_provider_equivalence.py`, `tests/test_llm_provider_p7_ports.py`,
  `tests/test_llm_provider_server_identity.py` (its two provider-setting tests moved to
  `tools/audit_202608/tests/test_llm_provider_ollama_identity.py`),
  `tools/audit_202608/tests/test_llm_provider_call_sites_llamacpp.py`,
  `tools/audit_202608/tests/test_llm_provider_window_and_retries.py`.
- Modelfiles: `RS2-Analyst-Deep-MTP5.Modelfile`, `-v31`, `-v32`, and the whole `-Q4` family (`-Q4`, `-Q4-v31`,
  `-Q4-v32`, `-Q4-v33`). No live code reads them; the Q4 Ollama tags were deleted on 2026-11-01. Tests that only pinned
  them lost those assertions; `test_charter_single_source.py` now pins the plain MTP5 SYSTEM block by its sha256 instead of
  reading the file, and `test_d_review.py` dropped its v32-to-v33 line diff (v33 stays pinned by sha256).

Removed in place rather than moved: the `llamacpp` branch of `llm_provider.py` (the adapter translation, error table,
engine checks), the `llamacpp` block and `_llamacpp_note` of `config.json` (the pins are in git history at b0527dc), and
the llama-server hooks in `depth_pipeline.py`, `depth_ondemand.py`, `orchestrate_depth.py` and `status.py`.

Kept live: `RS2-Analyst-Deep-MTP5-v33.Modelfile` and `RS2-Research.Modelfile`.

History, not a fallback.
