# SPEC 3M: the mandatory Qwen analysis pipeline (`qwen_c`), v1, 2026-10-29

Owner: Claude (PLAN §3M, rev c). Inputs to this design: `RR_M1.md` (the inventory), `SPEC_factor_led_v2.md` §4,
`PROTOCOL_factor_ai_m2_2026-10-23.md` §6, and `CLOSE_3L.md`.

## 0. What it is and what it is not

`qwen_c` analyses one factor-stage nominee as of one decision time T. It sends Qwen seven short, dedicated tasks over a
frozen packet of primary-source evidence, and stores structured JSON whose every claim cites evidence by id. Code
checks each citation.

- **It has no authority** (SPEC v2 §4). Its output is a visible paper observation. It gives no buy or sell, no weight,
  no veto and no valuation.
- **Nothing from revision 26's valuation is reused** (RR_M1 §7). No DCF, no desk, no forecast and no memo charter.
- **No web search and no news.** Evidence is the screener's PIT-verified row plus SEC primary documents. News and
  monitoring belong to 3P.

## 1. Code location

- `rs2-local`, new branch `review-2026-10/m3m-qwen` from `review-2026-10/r26-harness` (`481d0cf`). That branch gives us
  `ollama_raw` with the overflow guard and `turn_log`, without the frozen valuation code.
- New package `qwen_c/` at the repository root:

  | Module | Role |
  |---|---|
  | `sec_store.py` | Raw SEC fetch and store |
  | `packet.py` | The input contract |
  | `tasks.py` | The prompts |
  | `contract.py` | The output contract and the citation checks |
  | `runner.py` | Execution, errors and records |
  | `replay.py` | The pack replay gate |

  Tests go in `qwen_c/tests/`.
- Runtime files go in `cache/m3m/`, derived from the repository root and never written absolutely:
  - `raw/<sha256>` with `receipts.jsonl`
  - `packets/<ticker>_<T>.json`
  - `runs/<run_id>/`
  - `ledger.jsonl`
- The live tree (`phase-4`) is not touched. `config.json` `depth_provider` is not changed: `qwen_c` calls
  `ollama_raw.chat` directly.

## 2. Raw store (`sec_store.py`)

- `get(url, *, online)` returns bytes.
  - It first looks up `receipts.jsonl`, which records url, sha256, bytes, HTTP status, `fetched_at` (a self-claim) and
    the User-Agent. Stored bytes are read back and their sha256 is rechecked: a mismatch raises `StoreCorrupt`.
  - A miss with `online=False` raises `NotInStore`.
  - With `online=True` it fetches. Only `sec.gov` and `data.sec.gov` are allowed, with `sec_guidance`'s User-Agent and a
    throttle of 0.15 s or more. Only HTTP 200 is stored; anything else raises `FetchFailed(status)`.
  - Writes are atomic (temporary file, then rename) and append-only. An existing sha is never overwritten.
- `get_pinned(url, sha256)` returns exactly those bytes or raises. Replay uses only this.
- Submissions JSON changes daily, so every fetch of it is a new receipt. The packet pins the sha it used.

## 3. Input contract `m3m.packet.v1` (`packet.py`)

`build(ticker, T, screener_commit, *, online)` returns a packet dict. `canonical_bytes(packet)` is
`json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")`, and `packet_sha256` is computed
over those bytes.

**Header fields:**
- `contract: "m3m.packet.v1"`, `builder_version`, `ticker`, `cik`;
- `decision_time_utc` (T, ISO Z);
- `screener: {commit, stocks_blob_sha, factor_blob_sha}`;
- `sec_policy: "sec_acceptance_next_full_xnys_session_late_after_1730_plus_one_v1"`;
- `raw_inputs: [{url, sha256}]`, the exact bytes used;
- `evidence: [...]`, `annotations: [str]`, `excluded: [...]`.

**Eligibility of a filing:** `effective_at(accepted_at(acceptanceDateTime)) <= T`.
- `accepted_at` takes the later of the UTC reading and the Eastern-wall-clock reading of SEC's Z-suffixed value.
- `effective_at` is the open of the first NYSE session after the acceptance's Eastern date. A filing accepted at or
  after 17:30 ET gets one more session.
- This is the same policy as `m3l_sec_pit_asof.py`, re-implemented here (no cross-repo import), with its tests ported.
- An ineligible filing that would otherwise have been chosen is listed in `excluded` with its accession and
  `effective_at`.

**Evidence items** each have:
- `fact_id`: S0, then F1…, then P1…, in a fixed order;
- `kind`;
- `source`: `{accession, url}` or `{git_commit, path}`;
- `form`, `period`;
- `accepted_raw`, `effective_at`;
- `raw_sha256`;
- `text`: verbatim after HTML cleaning, never paraphrased.

A cut is marked with `sec_primary.OMIT` text. The item kinds:

| Id | Kind | Content |
|---|---|---|
| S0 | `screener_row` | The `stocks.json` record and the `factor_scores_dual_door.json` entry of the ticker, read as git blobs at `screener_commit`, rendered as `key: value` lines. Zero values print as `0`, not as missing. |
| F1–F3 | `statement` | The latest eligible periodic filing's FilingSummary R reports: balance sheet, income or operations statement, and cash flows. Chosen by ShortName (not parenthetical), each flattened like `sec_primary`'s segment table, 8,000 characters at most. |
| P… | `annual_section` | Latest eligible 10-K / 20-F / 40-F: Business (Item 1; 20-F Item 4) at most 20,000 characters; Risk Factors (Item 1A; 20-F Item 3.D) at most 30,000; MD&A (Item 7; 20-F Item 5) at most 30,000. |
| P… | `quarterly_section` | Latest eligible 10-Q filed after that annual report: MD&A (Part I Item 2) at most 15,000; Part II Item 1A when present, at most 8,000. |
| P… | `release` | The latest eligible 8-K Item 2.02 EX-99 release, at most 14,000 characters (`sec_primary` rules). |
| P… | `other_8k` | Eligible 8-Ks of the 120 days before T with items 1.01, 1.03, 2.01, 2.03, 2.04, 2.06, 3.01, 4.01, 4.02, 5.02 or 8.01; at most 4, newest first, 4,000 characters each. |

- Section boundaries are found by heading patterns in the cleaned text. A section that cannot be found is an
  annotation (`section_not_found: <name> <accession>`), never a guess and never a whole-document fallback.
- The packet total is at most 140,000 characters. Over that, items are trimmed in reverse order of the list above, and
  each cut is annotated.
- **Refusals** (the builder raises; it never builds a degraded packet):
  - the screener commit is not on a PASS line of a `check_new_runs` record, passed in as `--verified-record`;
  - the ticker is not in that commit's `stocks.json`;
  - the ticker is SENEA, SENEB, MOV or MG;
  - there is no CIK.
- **Determinism:** `build` with `online=False` over the same store and commit gives byte-identical output. No clock is
  read inside `build`: T is an argument.

## 4. Prompts (`tasks.py`), `PROMPT_VERSION = "m3m.prompt.v1"`

**The message layout** is the same for every task, so Ollama reuses the prompt prefix:
1. One shared SYSTEM text of at most 400 words. It covers:
   - the role: analyst of the evidence given, nothing else;
   - the cutoff: knowledge after T may not be used;
   - citations: every claim cites `fact_ids`, and every quotation must be copied exactly;
   - figures: every number must appear in a cited item;
   - when a fact is not in the evidence, say so under `unknowns`;
   - the output: JSON only, in one fenced `json` block.
2. A user message with the packet rendered as `[S0] …`, `[F1] …` blocks.
3. The task instruction, last.

**Seven tasks** (ids are fixed). Each states its question and its JSON shape:

| Task | Asks for |
|---|---|
| `business_model` | How the company makes money, segments and drivers |
| `financial_health` | Liquidity, leverage, cash generation and its quality, refinancing |
| `competitive_position` | Position, its evidence, threats |
| `growth_thesis` | Growth drivers, and what must be true |
| `risks` | Source-backed risks and counterarguments: mechanism, horizon, competing explanation (PROTOCOL §6 risk types) |
| `thesis_change` | Compares the prior run's `growth_thesis` and `risks` with evidence effective after the prior T: `unchanged`, `changed`, `unknown` or `unsupported`, per point. With no prior run, the task is not sent and its status is `not_applicable_no_prior`. |
| `unresolved_questions` | What the evidence cannot settle, and which document would |

## 5. Output contract `m3m.analysis.v1` (`contract.py`)

**Per task, the model returns:**
- `{"task", "claims": [...], "unknowns": [str]}`, plus `change_type` per claim for `thesis_change`.
- A claim is `{"claim", "fact_ids": [..], "quotes": [..], "numbers": [..], "mechanism"?, "horizon"?,
  "counter"?, "confidence_basis"}`.
- `risks` claims also carry `risk_type`, from PROTOCOL §6 or `other`.

**Code checks, per claim, recorded beside it.** Model text is never edited.

| `support` value | When |
|---|---|
| `unknown_fact_id` | A cited id is not in the packet |
| `no_citation` | Empty `fact_ids` |
| `quote_not_found` | A quote is not a substring of a cited item's text after whitespace and quote-mark normalisation |
| `number_not_found` | A number is not present in a cited item's text after normalising thousands separators, %, currency and unit words (so `1.2 billion` matches `1,200 million` only when the item states the value at that scale; otherwise not found) |
| `supported` | Only when every check passes |

- `numbers` must list every figure in `claim`. Code also extracts figure tokens from `claim` (with `sec_primary`'s
  figure-token rule), and a token missing from `numbers` sets `number_not_listed`.
- **An unsupported claim stays visible with its reason.** Nothing downstream may read a claim whose `support` is not
  `supported` as a verified value (non-negotiable 3: annotate, never gate).
- **Validation:** a hand-written validator, with no new dependency. The shape is wrong when a field is missing, a type
  is wrong, or the task id is unknown. A shape error makes that task `malformed`.
- **Owner:** `contract.py` is the single owner of `m3m.analysis.v1`. A new field must be added there, or it is dropped
  and the drop is logged.

## 6. Runner (`runner.py`)

`run(packet_path, *, url, num_ctx, think, seed)` performs one run per packet.

**Options are fixed per run and recorded:**
- `num_ctx` 65,536;
- `num_predict` 12,288;
- `seed` = 1000 + the task index;
- `think` "medium";
- the Modelfile's sampling defaults (temperature 0.6 is not overridden).

The smoke test (§8) may change `num_predict` and `think` once, before the long run. The change is recorded and then
frozen.

**Per task, statuses** are `ok`, `malformed`, `timeout`, `infra_error`, `context_overflow` and
`not_applicable_no_prior`:

| Event | Handling |
|---|---|
| Malformed output | One retry with seed + 50,000 and an appended line "Your last reply was not valid JSON for this shape; reply again." Still malformed: `malformed`. |
| Timeout (1,800 s per task) | `timeout`, no retry. |
| HTTP 500 or connection error, including CUDA out of memory | `ops.wait_unloaded`, then one retry; else `infra_error` with the cause. |
| Context overflow (`RawProviderError`) | `context_overflow`, no retry. |

**Run status:**
- `complete` when every applicable task is `ok`;
- otherwise `analysis_incomplete`, with `incomplete_tasks: {task: status}`;
- `failed` when no task is `ok`.

A run never raises past `run()`. A process crash leaves the run directory with `status: "running"` and no
`finished_at`, which the ledger reader reports as `crashed`.

**Records, in `runs/<run_id>/`** (`run_id` = `<ticker>_<T compact>_<packet_sha[:12]>_<n>`):
- `packet.json`: a copy whose sha is rechecked;
- `manifest.json`:
  - `contract`, `prompt_version`, `builder_version`;
  - the model tag, the model manifest sha256 and the system-layer digest (`llm_provider.ollama_serving`);
  - `template_sha256`, `ollama_version`, the options;
  - `qwen_c` git commit and dirty flag;
  - `started_at` / `finished_at` (self-claims), status, per-task status and timing;
- `prompts/<task>.txt`: the full rendered prompt text, with its sha256 in the manifest;
- `raw/<task>_<attempt>.json`: the full completion, thinking, token counts, `done_reason`;
- `analysis.json`: `m3m.analysis.v1` with the checks;
- `turns/`: `turn_log` output (active during the run).

`ledger.jsonl` gets one line per finished run: run_id, ticker, T, packet sha, status, manifest sha.

Holds: the runner refuses to start if `KIS_HALT` is not set, because its absence means something changed. The runner
writes nothing to `rs2-state`, to the overlay or to any screener file.

## 7. Gates

| Gate | Test | Evidence |
|---|---|---|
| **M-P4 pack replay** (moved from 3L) | `replay.py` rebuilds every stored packet offline from `raw_inputs` (`get_pinned`) and the screener git blobs, and gets byte-identical bytes. Negative tests: a filing whose effective time is after T is excluded and listed; tampered stored bytes give `StoreCorrupt`; an unverified screener commit is refused; an excluded ticker is refused; a missing raw input gives `NotInStore` | unit tests and a real-data replay of the live-run packets |
| **M-CONTRACT** | Validator and support checks on fixtures: a supported claim; a fabricated quote; a number off by scale; an unlisted number; an unknown id; a missing field | unit tests |
| **M-ERR** | A stub Ollama server: malformed then valid; malformed twice; timeout; 500 then valid; 500 twice; overflow; crash mid-run, giving the ledger `crashed` | unit tests |
| **M-REC** | Every record of §6 exists and its hashes recompute | unit test plus the real runs |
| **M-LIVE** (limited GPU) | After the cross-check: a one-ticker smoke, then 4 tickers from the current `research_now`, none excluded, and one ticker run twice with the same seed to measure repeatability. The repeatability test compares claim sets and support rates, not bytes. | RR_M-LIVE |

**Pass, per PLAN §3M:**
- runs are repeatable on eligible candidates, and each run has reproducible records;
- unsupported figures are never `supported`;
- incomplete runs are visible;
- the live check passes after source, design and isolation review.

**Not in 3M:** accuracy against ground truth (3N), and any authority.

## 8. Order of work

1. **WO_M2:** `sec_store` + `packet` + `replay` with tests (builder A).
2. **WO_M3:** `tasks` + `contract` + `runner` with stub tests (builder B), in parallel with WO_M2.
3. Claude audits both line by line, then merges on the branch and runs the suites.
4. Packets are built online for 5 tickers at T = now, then replayed offline (M-P4 real data).
5. **Cross-check:** Gemini through `agy` reviews the spec and the diff (CROSS_CHECK_M). Claude rules on each point.
6. M-LIVE smoke, then the 4-ticker run.
7. `CLOSE_3M`.

## Amendment 1, 2026-10-29: the code as built after the cross-check and the smoke run

Where this amendment and the sections above disagree, the amendment and the code win. Records: `CROSS_CHECK_M_RULINGS.md`,
`AUDIT_M2.md` to `AUDIT_M5.md`.

- **§3 S0** is a whitelist: symbol, name, sector, industry, country, price, marketCap, price as-of (`Last_Updated`) and
  `last_listed`. Nothing comes from `factor_scores_dual_door.json`; its blob is pinned for audit only. No door, rank,
  band, score, valuation signal or narrative reaches the model.
- **§3 refusals added:**
  - the verified row has no `run_updated_at`, or one after T;
  - T is older than the oldest `filings.recent` row;
  - T is outside the calendar;
  - no factor profile;
  - the commit is dated after T.
- **§3 header additions:** `verified_row` and `builder_code` (source hashes and library versions).
- **§3 evidence added:**
  - `amendment` items: 10-K/A, 10-Q/A, 20-F/A, 40-F/A; at most 2, starting at the explanatory note;
  - other-8-K text is the body from its first listed Item heading, then EX-99.x, never contracts;
  - a release older than 120 days is dropped (`release_stale`);
  - a short last Item 1A after a contents entry is kept.
- **§4:** the packet header lists NOT IN THIS PACKET (the "looked for and missing" annotations, never `excluded`), and
  each item header shows its title. `thesis_change` receives only supported prior claims.
  `PROMPT_VERSION = m3m.prompt.v2`, which adds the scale example to FIGURES. **m3m.prompt.v1 was used by exactly one
  run** (the MA smoke).
- **§5:** `contract.py` owns its own figure reader:
  - units k/m/bn/tn, %, x, bp and pp;
  - ISO currency codes and currency words;
  - ranges, and omission markers removed.
  
  Units must be equal, except among the scale units. A wanted figure with no currency matches a printed one; a wanted
  currency must be equal. Every number in a claim must be listed, except an all-digit ticker, a year after a year word
  that a cited item prints, and the day and year of a date that a cited item prints. An empty reply is malformed, and
  a `thesis_change` point must be a real prior point id. **`supported` certifies presence, not meaning.**
- **§6:**
  - `NUM_CTX` is 98,304, checked before the call (characters / 2.5 + `num_predict` <= `num_ctx`) and after it
    (`prompt_eval_count + eval_count < num_ctx - 1`);
  - new status `prior_unusable`;
  - runs carry `support_summary`;
  - the runner refuses `gpu_busy` and `model_show_failed`, and records the `/api/show` parameters;
  - the ledger tolerates a torn last line.

## Amendment 2, 2026-10-29: the contract after M-LIVE (commits e7c9f72, bac4cf8)

Records: `RR_M-LIVE.md`, `M_LIVE_recheck_bac4cf8.json`. The code wins where it and this text disagree.

- **§5 THE STATEMENT RULE.** An item of kind `statement` is a FilingSummary R report, and its first line declares its
  currency and scale ("... - USD ($) shares in Millions, $ in Millions | ..."). Each value cell printed with no unit,
  and with no currency or the declared one, is also read:
  - with the declared currency, on every row;
  - with the declared scale as well, on a money row.

  Row types:
  - a per-share row ("(in dollars per share)", "(USD per share)") takes the currency only;
  - a share row ("(in shares)", "(shares)") takes the share scale only, with no currency;
  - a row ending in another "(in ...)" takes nothing.

  Row labels and period cells take nothing.

  A `numbers` entry with no unit that a cited statement reads this way lists every reading of that cell. Prose items
  never take a heading scale.

  This replaces the rule that a scale stated only in a heading is not read. That rule was a builder choice, and it made
  correct statement figures ("$11,291 million" for the cell `$ 11,291` in a "$ in Millions" balance sheet)
  unsupported. It left `financial_health` with 0 supported claims on 5 of the 7 live runs.
- **§5 dates.** A date of the claim text, "Month D, YYYY" or "D Month YYYY", with the month named in full or
  abbreviated ("Jun.", "Sept"), is exempt from listing when a cited item prints the same month, day and year in any
  of those forms.
- **§5 years.**
  - "due" is a year word.
  - A year that continues a list or range of years after a year word is a year ("in 2023, 2024 and 2025",
    "in 2032-2036").
  - A range's lower bound that is a year by its form takes no unit ("98.2% in 2026 to 15.1%").
- **§6 KIS_HALT** (correcting the "Holds" line). rs2-local cannot resolve `KIS_HALT`, which is a stock-screener
  repository variable read by the KIS sync workflow. The runner therefore records
  `kis_halt: "not_resolvable_in_rs2"` in every manifest and proceeds (WO_M3). It has no trading or publishing path.
- **The stored `analysis.json` files are not rewritten.** Each is the record of what the code at its manifest's
  `qwen_c.git_commit` judged. A recheck under later code is a separate record.

## Note, 2026-10-29: the acceptance clock is conservative (CROSS_CHECK_N finding 11)

SEC full-submission headers show that the submissions JSON `acceptanceDateTime` "Z" value is true UTC. Three checks agree: SNYR, FATBP and YEXT. `packet.accepted_at` takes the later of its two readings, and so places acceptance 4 hours (EDT) or 5 hours (EST) late.

**The effect:** under `sec_acceptance_next_full_xnys_session_late_after_1730_plus_one_v1`, the effective time is one session later than the true clock gives for 27 of the 45 sampled 3N events.

**It is not leakage.** The policy only ever withholds a document longer than it needs to.

**Nothing changes yet.** 3N reports lag from `first_public_true_utc`, and 3N keeps T1 as frozen. Any change to `accepted_at` or the policy is a separate, versioned decision, because it moves every packet's T1 and the 3M replay records.
