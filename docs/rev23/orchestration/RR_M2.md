# RR_M2: `qwen_c` raw store, input packet and pack replay (builder A), 2026-10-29

Worktree `scratch/rev23/wt-m3m` (branch `review-2026-10/m3m-qwen`). Nothing committed, pushed or checked out. No model or GPU job.
No secrets or `.env*` read. Nothing written under the repository's `cache/` (the conftest guard passes). Real-data exploration went to
the session scratchpad only.

## Files

| File | Holds |
|---|---|
| `qwen_c/__init__.py` | empty |
| `qwen_c/sec_store.py` | `get(url, *, online, root=None)`, `get_pinned(url, sha256, *, root=None)`, `latest_receipt`. Errors: `NotInStore`, `StoreCorrupt`, `FetchFailed(status)`. Store is `cache/m3m/raw/<sha256>` plus `receipts.jsonl`. Hosts: https sec.gov, www.sec.gov and data.sec.gov. Uses `sec_guidance.UA`, a throttle of at least 0.15 s, 200 only, atomic and append-only writes. A submissions URL is fetched again on every online call. |
| `qwen_c/packet.py` | `build`, `canonical_bytes`, `packet_sha256`, `save` (never overwrites different bytes), and a CLI. Also `accepted_at` / `effective_at` (policy re-implemented from `m3l_sec_pit_asof.py`), `pick_statements`, `find_section`, `SECTIONS`, the refusals (`PacketRefused.code`) and the 140,000 trim. |
| `qwen_c/replay.py` | `replay(packet_path)` returns `{identical, first_diff, stored_sha256, rebuilt_sha256}` and rebuilds through `get_pinned` only. `first_diff` gives a JSON path, or a byte offset when the stored file is not canonical. CLI: `python -m qwen_c.replay [--dir]` exits 0 only when there is at least one packet and all are identical. |
| `qwen_c/tests/test_sec_store.py` | 12 tests |
| `qwen_c/tests/test_packet.py` | 42 tests. Synthetic store and a throwaway git repo in `tmp_path`. |
| `qwen_c/tests/test_replay.py` | 9 tests |
| `qwen_c/tests/fixtures/` | `amd_10q_FilingSummary_trimmed.xml` and `amd_10q_R4.htm`: trimmed real bytes from AMD 10-Q 0000002488-26-000123 |

Reuse from `sec_primary`: `blocks_of`, `select_text`, `prefix_text`, `canonical`, `_split_documents`, `_is_text_exhibit`, `_release_doc`,
`_main_exhibit` and `_items_list`, plus the segment-table row flattening. `OMIT` is reached through `prefix_text` and `select_text`.
`_short_names` is mirrored as `_reports`, which adds MenuCategory. `pick_segment_report` is not used because §3 has no segment item.

## Tests

`"C:\Program Files\Python312\python.exe" -m pytest -q -p no:cacheprovider qwen_c/tests`: **174 passed**. Of these, 63 are mine and
the rest are builder B's. The broader repository suite was not run: this change touches no shared file.

The tests cover every M-P4 negative:
- effective after T is excluded and listed;
- tampered bytes give `StoreCorrupt`, in the store and in replay;
- an unverified commit is refused, in 7 shapes;
- an excluded ticker is refused before anything is read (all 4, plus lower case), and again on replay;
- a missing raw input gives `NotInStore`, in build and in replay, including an input the packet did not pin.

They also cover:
- the acceptance rule: UTC versus Eastern-wall reading, the 17:30 boundary on naive and Z clocks, weekend, Good Friday, Thanksgiving,
  and T exactly at `effective_at`;
- determinism: two builds give identical bytes;
- the trim order and its annotations;
- 0 printed as `0`;
- the `paths.py` resolver.

## Section finding on real filings (all fetched 2026-10-29)

Found means the heading through the next heading of another item, with table-of-contents rows skipped.

| Form | Issuer, accession | Business | Risk | MD&A |
|---|---|---|---|---|
| 10-K large | AAPL 0000320193-25-000079 | found | found | found |
| 10-K large | AMD 0000002488-26-000018 | found | found | found |
| 10-K mid | BCRX 0001628280-26-012240 | found | found | found |
| 10-K small cap | CRMD 0001213900-26-023889 (latest 10-K unamended; it has a 2019 10-K/A) | found | found | found |
| 10-K small REIT | CLDT 0001437749-26-006103 | found | found | found |
| 10-K, no 10-K/A in the recent submissions | CHEF 0001517175-26-000005; ARX 0001997350-26-000003 | found | found | found |
| 20-F | BUD 0001193125-26-088105 | found (Item 4) | found ("D. \| RISK FACTORS") | found (Item 5) |
| 20-F | CMRE 0001140361-26-007868 | found | found ("D. Risk Factors") | found |
| 20-F | DDI 0001628280-26-022395 | found | found ("D.Risk Factors") | found |
| 20-F | CAAP 0001104659-26-029442 | found | found | found |
| 40-F | AAUC 0001628280-26-022512 | **not found** | **not found** | **not found**: the AIF and MD&A are EX-99.1 and EX-99.2, and the primary document is a cover |

10-Q results, 8 filings from 7 issuers:
- MD&A was found in all 8: AAPL -26-000020, AMD -26-000123, BCRX -26-053300, CHEF -26-000036 and -26-000028, CLDT -26-025638,
  CRMD -26-000056, ARX -26-000015.
- Part II Item 1A was found for AAPL, AMD and BCRX.
- It was **not found** in the other 5 filings (4 issuers). I checked the text of 4 of them: CHEF -036 (311 characters), CLDT (163),
  CRMD (206) and ARX (258). Each real section is one sentence, "no material changes …". CHEF -028 is annotated only; I did not read
  its text.
- These fall under the WO's rule that fewer than 1,500 characters before the next item heading marks a contents entry, so they are
  annotated rather than guessed. **This needs a ruling** (see deviation 6).

Real-data replay: 11 packets were built online at T = 2026-10-29T00:00:00Z on screener commit `694c929` (verified PASS / pair PASS,
run 40425800027). The tickers were AMD, BUD, CHEF, CLDT, CRMD, DDI, AAUC, CAAP, CMRE, BCRX and ARX. All 11 replay identical, and an
offline rebuild of each is also byte-identical. That took 106 SEC requests in total.

CHEF shows the policy working: its 10-Q and 8-K of 2026-10-28 (12:36Z, effective 2026-10-29 13:30Z) are in `excluded`, and the previous
10-Q is used.

## Deviations (the more conservative reading in each case)

1. **Signatures.**
   - `build` takes a required keyword, `verified_record` (a path or a list of rows), plus optional `screener_repo_path` and `store_root`
     for tests.
   - `sec_store.get` / `get_pinned` take an optional `root`.
   - `get` returns bytes, as the spec says.
2. **CIK source.** `stocks.json` holds no CIK, so the CIK is read from `public/data/cik_map.json` at the same commit. Its blob id is in
   the header as `screener.cik_map_blob_sha`. The header also records `screener.verified_run_id`, the run that verified the commit.
3. **Extra evidence fields.**
   - `name` (for example `risk_factors`) and `title` (human-readable) are added.
   - S0's `source.path` and `raw_sha256` are two-element lists, one per blob. Its form, period and clocks are null.
4. **Extra refusals.**
   - `ticker_not_in_factor_profiles`: the package analyses nominees, and without this it would build a degraded S0.
   - `screener_commit_after_T`: the git committer date, a self-claim, is later than T. This guards against look-ahead.
   - `screener_commit_invalid`: not 10 to 40 hex characters.
   - T must be aware and in whole seconds.
   - A document that cannot be had raises (`NotInStore`, `FetchFailed` or `StoreCorrupt`) instead of being annotated.
5. **`excluded`** lists, per slot, every newer ineligible filing whose *earlier* acceptance reading is at or before T. Without that
   condition a historical T would list every later filing.
6. **The 1,500-character contents rule was kept as written.** It drops genuine short 10-Q Item 1A sections: 5 of the 8 10-Qs checked, from 4 of 7 issuers.
   Possible refinement, if ruled: treat a short candidate as a contents entry only when a later candidate for the same heading exists.
   - A section ends at the next heading of a **different** item, so a running page header such as "Item 1A … (continued)" does not cut
     it.
   - A heading with no later item heading is not found; there is no fallback to the end of the document.
   - "PART II" lines are not boundaries.
7. **Cuts.**
   - Sections, statements and other 8-Ks keep their start (`prefix_text` with an `OMIT` marker). Only the release uses `select_text`.
   - The 140,000 cap counts evidence text characters.
   - Trimming runs in reverse list order, with the other 8-Ks oldest first. An item that would keep fewer than 600 characters is dropped,
     and every cut or drop is annotated.
8. **Foreign filers.** There is no 6-K release because §3 names only the 8-K; it is annotated `no_eligible_filing: release`. A 40-F's
   sections are not found (see above).
9. **Statements.**
   - Only MenuCategory "Statements" reports are read, and never one that is parenthetical or a details report.
   - The income statement falls back to "Comprehensive Income (Loss)" only when no separate statement exists; "Other comprehensive" is
     never used.
   - `period` is `reportDate`.
10. **Submissions.** Only `filings.recent` is read; the older `filings.files` are not. A missing slot says so: "in the recent
    submissions".
11. **Store behaviour.**
    - There is no retry on 429 or 5xx: they raise `FetchFailed`.
    - A redirect off SEC raises `ValueError`.
    - A torn receipt line raises `StoreCorrupt`.
    - Bytes are decoded as UTF-8, else cp1252 (Apple and AMD HTML carry raw 0x92 bytes).
12. **Calendar.** The XNYS calendar has fixed bounds of 2005 to 2031. The library's default bounds depend on today's date, which would
    break the rule that the build reads no clock. A T after 2031 raises.
13. **Replay** skips only the verified-record check, which is a build-time precondition, and carries `verified_run_id` through. It
    re-runs every other refusal.

## Could not do, and notes for step 4

- **The publish clone lacks the newest verified commits.** `screener-publish` does not hold `e41974be` or `ed661784`, the verified
  commits in `check_20261028T180257Z.json`; it does hold `694c929` and `9046be40`. A build on the newer commits needs a `git fetch` in
  that clone first. I did not fetch.
- **STOCKS_ROOT must be set.** The repository is resolved with `paths.resolve("screener_publish_repo", paths.load_config())`. Run from
  this worktree, `STOCKS_ROOT` must be set to `C:\Users\riper\stocks`, because the default is the worktree's parent, and `load_config`
  needs every peer key to resolve.
- **Not done:** live online packet builds into the real `cache/m3m/` (that is step 4 of the spec), and any test of `--online` against
  SEC inside the suite. The suite is offline.
