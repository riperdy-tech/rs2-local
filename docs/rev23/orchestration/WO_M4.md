# WO_M4: apply the CROSS_CHECK_M rulings (two builders, in parallel)

- **Milestone:** 3M.
- **Rulings:** `CROSS_CHECK_M_RULINGS.md`. Every **FIX** there is a requirement here, and its exact wording is the
  spec.
- **Background:** `SPEC_m3m_qwen_pipeline.md`, `AUDIT_M2.md`, `AUDIT_M3.md`, and the reviewer's reply
  `CROSS_CHECK_M_gemini_reply.txt`, which holds the failing inputs. Each failing input of a FIX becomes a test.
- **Worktree:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3m`, branch `review-2026-10/m3m-qwen`, at
  commit `f584410`.
- **Do NOT:** commit, push or check out; run a model, contact a real Ollama server or use the GPU (tests use stubs);
  read `.secrets.json` or `.env*`; touch files outside your list.

## Builder A2: `qwen_c/packet.py` and its tests (`test_packet.py`, `test_replay.py`, `test_sec_store.py` if needed)

Rulings to apply:
- **2.1** The run-time check. A verified-record row now carries `run_updated_at`, GitHub's clock. Refuse when it is
  missing or after T. The newest record is
  `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3l_verifier\out\check_20261029T015407Z.json`.
- **2.3** Refuse when T is older than the oldest `filings.recent` row.
- **3.1** The S0 whitelist, exactly as ruled. Keep `factor_blob_sha` in the header, but read nothing from that file
  into evidence. `Last_Updated` is labelled as the price as-of.
- **5.1** The verified row goes into the header.
- **5.2** Fix the docstring.
- **5.3** `builder_code` in the header, and `T_outside_calendar`.
- **6.1b** Other-8-K text: the body from its first listed Item heading, then EX-99.x. Never EX-1, EX-3, EX-4 or EX-10.
- **6.2a** `amendment` items.
- **6.2c** The release staleness bound.

Then rebuild the 5 real packets at a new T (`date -u`, whole seconds) on commit `92592e2156` with the new record,
online:
- run from the worktree with `STOCKS_ROOT=C:\Users\riper\stocks`;
- tickers MA, CMRE, HRTG, ILMN, ECPG;
- write them through `packet.save` to `cache/m3m/packets/`;
- run `python -m qwen_c.replay` and report the result;
- report the evidence ids and kinds per packet;
- confirm ILMN's other-8-K items now hold 8-K body text.

The old packets at `...T013151Z.json` stay; nothing is overwritten.

## Builder B2: `qwen_c/contract.py`, `qwen_c/tasks.py`, `qwen_c/runner.py` and their tests

Rulings to apply:
- **1.1–1.5** (contract). The reader is owned by `contract.py`; `sec_primary.py` is not edited.
- **3.4, 6.1a, 6.1c** (tasks).
- **4.1–4.6, 6.3, 6.4** (runner), with `NUM_CTX = 98304`.
- Re-pin the prompt hashes, and keep `PROMPT_VERSION = "m3m.prompt.v1"` (ruled: no run has used it yet).

The packet's new kinds (`amendment`) and S0 shape come from builder A2. Your tests use synthetic packets: do not
depend on A2's files.

## Both

- Run `"C:\Program Files\Python312\python.exe" -m pytest -q -p no:cacheprovider qwen_c/tests` from the worktree root.
  The other builder may be mid-edit, so a failure in a file that is not yours is not yours to fix: report it.
- Write your return report, `RR_M4A.md` or `RR_M4B.md` in the orchestration folder, at most about 100 lines. Give each
  ruling id with what you changed and which test covers it, plus any deviation and why.
