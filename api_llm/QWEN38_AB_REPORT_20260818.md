# Qwen3.8-27B vs production analyst — A/B evaluation report (2026-08-18)

Operator plan: `~/.claude/plans/i-found-out-there-iridescent-diffie.md`. All test runs via the
isolated `run_rs2.py --api` path (reports under `api_llm/reports/`, never the live site).
Same-day, same cached briefs, sequential single-slot runs. Production was PAUSED throughout;
no production file was modified.

## Recommended configuration (the "sweet spot")

**`qwen3.8:27b-mtp-q4_K_M` (official Ollama MTP tag) + thinking OFF (`think: false`), temp 0.4,
served by Ollama — no orchestration changes.**

- MTP speculative decoding on this 3090: **48.5 tok/s vs 35.8** plain (+35%), distribution-identical output.
- VRAM @ ctx 32768: **19.1 GiB used / 5.2 GiB free** — ~2.5 GiB MORE headroom than production flash (21.6).
  Loads in ~30 s; `ops.wait_unloaded` releases cleanly (research-model swap unaffected).
- Text-only in practice (vision projector never engaged; RS2 sends no images).

## Battery results (9 tickers, single attempt each, exit-code scored)

| Arm | Avg | Worst | In 20-min budget | Clean (sanity+tier1+tier2) |
|---|---|---|---|---|
| **Qwen3.8 MTP, think off** | **10.6 m** | 11.7 m | 9/9 | **8/9** |
| Production flash (thinking) | 10.2 m | 13.9 m | 9/9 | **4/9** |
| Qwen3.8 MTP, effort low | 23.2 m (n=3) | 25.6 m | 0/3 | 2/3 |
| Qwen3.8, default effort | ~70 m (n=1) | — | no | fail |

- Same speed class as production, **double the single-attempt audit cleanliness** (fewer production
  retries → fewer 10-attempt names).
- Flash single-attempt failures were the classic classes: slot transcription (CAT), conviction
  cross-section contradiction (PM 12/15 vs 11), tier-2 fabrication charges (MU, KRYS), aggressive
  sizing (META "Initiate Position" conv 15 → tier-1 fail). Qwen3.8's one failure: HG tier-1 slot slip.
- Verdict directions agree across arms on all 9 names (HOLD/stage-in family everywhere except
  EXEL/META BUY-family on both arms). Qwen3.8 runs 1-3 conviction points more conservative
  (flash hit 15/15 twice; Qwen3.8 max 13).
- Qwen3.8 effort **low** was the wall-clock loser (23-25 min) AND produced 1/3 early-EOS truncated
  finals — rejected. Default effort is unusable (~70 min).

## Ladder replay (model-as-judge, 14 adjudicated production dirs)

Candidate (think off) re-judged yesterday's production audit outcomes:
- Prior-PASSES: **7/7 preserved — zero new rejections** (the direction that would break the fleet).
- Prior-FAILS: 4/7 preserved; 3 flipped to pass → hand-checked against the data:
  - ST "fabricated 109.96% institutional" — **the figure is verbatim in `enrich/ST.json`** → flash false positive; candidate correct.
  - INVA institutional figure — same class, `enrich/INVA.json` holds 110.31 → flash false positive; candidate correct.
  - ROST engine-field contradiction — ambiguous: `S4_valuation_result.md` itself carries two fair values
    (band ~$261 vs fenced $105.66). Needs operator eyeball.

## Integration facts learned (kept in api_chat.py / memory)

- Ollama `/v1` counts thinking against `max_tokens` → default-effort Qwen3.8 returns EMPTY
  `finish_reason=length` at 8192. Production `/api/chat` path has no cap — non-issue after migration.
- `reasoning_effort` works on `/v1`; native path controls thinking via `think` (config.json).
- `num_gpu 42` in the production Modelfile would CPU-spill this base (65 blocks vs 40) — must be ≥65.
- Qwen3.8 quirks seen: Unicode-box tables (`│` can survive the ASCII pipe-split in the action
  extractor — cosmetic, seen once), bolded `**SECTION**` headers at think-off (extractor tolerant).

## GO change-set (pending operator approval — NOT applied)

1. `RS2-Analyst.Modelfile`: `FROM qwen3.8:27b-mtp-q4_K_M`; `num_gpu 42 → 99`; header updated
   (swap date, old FROM, one-line revert). Sampling params unchanged.
2. `config.json`: `"think": true → false`.
3. `ollama create rs2-analyst -f RS2-Analyst.Modelfile`; warm + unload (first-call flake).
4. Validation ladder completion: ≥2 fresh full runs incl. one hard name via the normal local path,
   then remove `cache/PAUSED`.
5. Keep `mdq100/qwen3.5-flash:35b` + `qwen3.6:35b-a3b` weights until the first 30d graded cohort
   (`grade_rs2_verdicts.py`) confirms; revert is one Modelfile line either way.

## Housekeeping state

- `api_llm/config.json` restored to DeepSeek defaults after testing. `api_chat.py` gained additive,
  config-gated `reasoning_effort` support (uncommitted, review welcome). `.secrets.json` has a dummy
  `OLLAMA_LOCAL_KEY: "ollama"` for local /v1 testing.
- New uncommitted files: `RS2-Analyst-38.Modelfile` (baked-SYSTEM candidate, unsloth base — superseded
  by the MTP tag for production), `api_llm/_battery_local.sh`, `_ab_summary.json`, `_replay_set.json`,
  `_replay_results.json`, battery logs, test report dirs.
- Disk: unsloth GGUF (18 GB) + official MTP tag (18 GB) added. `qwen3-coder:latest` (18 GB) is unused
  by RS2 if space is wanted. 3.8-27B is the smallest Qwen3.8 (only 27B + API-only Max exist), so the
  research engine keeps `qwen3:14b`; a Gemma 4 12B research A/B remains an optional follow-up.
