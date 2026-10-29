# WO_M2: `qwen_c` raw store, input packet and pack replay (builder A)

- **Milestone:** 3M.
- **Spec:** `SPEC_m3m_qwen_pipeline.md` §1, §2, §3 and the M-P4 row of §7. Read the spec first; it is the contract.
- **Worktree:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3m` (branch `review-2026-10/m3m-qwen`, based on
  `r26-harness` `481d0cf`).
- **Write only these files:**
  - `qwen_c/__init__.py` (empty)
  - `qwen_c/sec_store.py`, `qwen_c/packet.py`, `qwen_c/replay.py`
  - `qwen_c/tests/__init__.py`, `qwen_c/tests/test_sec_store.py`, `qwen_c/tests/test_packet.py`, `qwen_c/tests/test_replay.py`
  - test fixtures under `qwen_c/tests/fixtures/` (small, synthetic or trimmed real SEC bytes)

  Another builder is writing `tasks.py`, `contract.py` and `runner.py` in the same folder: do not touch them.
- **Do NOT:** commit, push or check out; run any model or GPU job; read `.secrets.json` or any `.env*`; edit any file
  outside the list.
- **Network:** you may fetch from SEC (`sec.gov`, `data.sec.gov`) only, with `sec_guidance.UA`, at most a few hundred
  requests in total. Fetching is only to look at real document structure and to build trimmed fixtures. Tests must run
  offline.

## Requirements

**Reuse:**
- `sec_primary.py` (repository root) helpers for HTML cleaning and cutting: `blocks_of`, `select_text`, `canonical`,
  `OMIT`, `_split_documents`, `pick_segment_report`/`_short_names` and the FilingSummary flattening. Read the module
  before writing.
- Copy the acceptance rule (`accepted_at`, `effective_at`) and its intent from
  `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3l_source_owner_main_20261028\scripts\m3l_sec_pit_asof.py`
  (with its test file beside it). `exchange_calendars` 4.13.2 is installed in system Python.

**Behaviour:**
- `packet.build(...)` is pure given the store and the commit. It reads no clock; T is an argument. Screener blobs are
  read with `git -C <stock-screener repo> show <commit>:public/data/stocks.json` and `...factor_scores_dual_door.json`.
  - The screener repository is located through `paths.py` (`load_config()`/`resolve()`), under the key used for the
    screener repository or data directory. Read `paths.py` and use its existing key; do not hardcode a path. If no key
    fits, stop and report.
  - The verified-record check: the `--verified-record` JSON is a list of rows; a row passes when `verdict == "PASS"`,
    `pair == "PASS"`, and `output_commit` equals the commit (prefix match on at least 10 hex characters).
- Section finding for 10-K / 10-Q / 20-F is the hardest part.
  - Use heading patterns. A section ends at the next item heading.
  - Skip table-of-contents hits: a candidate heading followed by under about 1,500 characters before the next item
    heading is a contents entry.
  - Test on at least 6 real filings of different issuers and sizes, including one 20-F and one 10-K/A-free small cap.
    Record which were found and which were not in your report.
  - **Not found is an annotation, never a guess.**
- `0.0` is a value: never default a numeric field with `or`.
- `replay.py`:
  - `replay(packet_path)` rebuilds from `raw_inputs` through `get_pinned`, plus the screener commit, and returns
    `{"identical": bool, "first_diff": ...}`;
  - a CLI that replays every packet in `cache/m3m/packets/`.

**Tests:** cover every M-P4 negative in the spec, the acceptance-rule cases (UTC versus Eastern-wall reading, the
17:30 ET boundary, weekend and holiday), determinism (build twice gives identical bytes), the size-cap trimming order
with its annotations, and the excluded-ticker refusal.

Run with `"C:\Program Files\Python312\python.exe" -m pytest -q -p no:cacheprovider qwen_c/tests` from the worktree root.

## Return report

Write `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\rev23\orchestration\RR_M2.md`, at most about 120
lines:
- the files and what each holds;
- the test count and result;
- the section-finding results on the real filings, by accession;
- every deviation from the spec and why;
- anything you could not do.

If you cannot write that file, return the report as text.
