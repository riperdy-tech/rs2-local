# RR_M3: `qwen_c` prompts, output contract and runner (builder B), 2026-10-29

Worktree `scratch\rev23\wt-m3m` (branch `review-2026-10/m3m-qwen`, base `481d0cf`). Nothing committed, pushed or checked out. No model,
no real Ollama server, no GPU. No secret or `.env*` file read.

## Files
- `qwen_c/tasks.py`: SYSTEM, the six fixed instructions plus the thesis_change template, `RETRY_LINE`, `render_packet`, `messages`.
  `PROMPT_VERSION = "m3m.prompt.v1"`.
- `qwen_c/contract.py`: `m3m.analysis.v1`. Holds the validator (`validate`), the claim checks (`check_claim`) and `check_task`.
- `qwen_c/runner.py`: `run()`, `parse_reply`, `call`, `find_prior`, `read_ledger`, and the CLI `python -m qwen_c.runner`.
- `qwen_c/tests/test_tasks.py`, `test_contract.py`, `test_runner.py`, with the fixtures `qwen_c/tests/fixtures_b/packet_acme.json`
  (a synthetic packet) and `contract_cases.json` (22 reply cases).
- `qwen_c/tests/__init__.py`: an empty file. I created it because it did not exist yet. `qwen_c/__init__.py` was already there from
  builder A, and I did not touch it.

## Tests
`"C:\Program Files\Python312\python.exe" -m pytest -q -p no:cacheprovider qwen_c/tests` gives **106 passed** (26 s). When I ran it,
all 106 tests were mine; builder A had no tests in that folder yet. I also re-ran `tools/audit_202608/tests/test_ollama_raw.py` and
`test_r26_logging.py`, which I did not change: 36 passed.
- **M-ERR** (stub `ThreadingHTTPServer` on 127.0.0.1, `ops.wait_unloaded` stubbed), one test per case:
  - malformed then valid: the retry uses seed + 50,000 and the appended line;
  - malformed twice gives `malformed`;
  - timeout is not retried;
  - a 500 then valid: wait_unloaded runs, then the retry uses the same seed and prompt;
  - a 500 twice gives `infra_error`;
  - a dropped connection gets one retry;
  - an unload that is not confirmed gets no retry;
  - a 4xx is not retried;
  - an overflow gives `context_overflow` and is not retried;
  - when every task fails, the run is `failed` and still goes into the ledger;
  - a crash mid-run (a KeyboardInterrupt raised inside the run) leaves the manifest `running` with no `finished_at`, and `read_ledger`
    reports it as `crashed`;
  - an internal TypeError becomes `infra_error`, not a raise.
- **M-CONTRACT** covers every §7 case: a supported claim (7 variants), a fabricated quote, a number off by scale, an unlisted number, an
  unknown id and a missing field. It also covers no_citation, a quote across an omission marker, the wrong currency, a number in an
  uncited item, the wrong or unknown task id, risk_type, and the extra fields of thesis_change and unresolved_questions. Dropped fields
  are logged. 19 parametrised cases pin the number rule.
- **M-REC**: every record exists, and each recorded sha recomputes:
  - packet copy, canonical sha, prompt files, raw files, turn files, analysis and manifest-in-ledger;
  - the Ollama manifest sha, from a fake `OLLAMA_MODELS`;
  - each POSTed prompt matches its prompt file sha and the `prompt_sha256` in the turn log;
  - the thinking text never appears in `analysis.json`.
- **Prompt pins**: the sha256 values of SYSTEM, of each instruction, of the thesis_change template, of RETRY_LINE and of the fixture
  packet's rendering are pinned under `PINS["m3m.prompt.v1"]`. SYSTEM is 379 words.
- Other tests check that no valuation or trading words appear (a banned-word regex), and that each instruction's JSON shape has exactly
  the fields `contract.py` owns.

## SYSTEM text (verbatim)
```
You analyse one company using only the evidence given in this conversation.

EVIDENCE. The user message holds numbered evidence items. [S0] is a data row from a stock screener. [F1], [F2] and so on are financial statements from SEC filings. [P1], [P2] and so on are passages from SEC filings and company releases. Each item states its form, its period and the time it became public. Text shown as "[… 1,234 characters omitted …]" was cut and is not evidence.

CUTOFF. The decision time T is stated at the top of the user message. Use nothing you know from training, from memory or from events after T, even when you believe it is true. What the items do not say is not known.

CLAIMS. Each claim is one short statement drawn from the evidence. Every claim lists in "fact_ids" the ids of the items it rests on, for example ["F2", "P1"]. A statement that no item supports does not belong in "claims".

QUOTATIONS. "quotes" holds extracts copied exactly, character for character, from the cited items, each one sentence or shorter. Do not shorten, join, translate or correct a quotation. If you cannot copy it exactly, leave it out.

FIGURES. Every number written in a claim must also be listed in that claim's "numbers", written exactly as a cited item prints it, with the currency sign, the unit word (thousand, million, billion) or the % only when the item prints it next to the number. When a table gives its scale only in its heading, such as "$ in Millions", write the number in the claim and in "numbers" exactly as printed, for example "1,234", and name the scale apart from it, for example "(table in millions)". Do not round, convert, add up or compute new figures.

UNKNOWNS. When the evidence cannot answer part of the task, say so in "unknowns" in a short sentence. Do not guess.

SCOPE. Describe and explain what the evidence shows. Do not value the company, forecast its share price or recommend any action.

OUTPUT. Reply with JSON only, inside one fenced block that opens with ```json and closes with ```. Write nothing outside the block. Use exactly the shape the task gives; every field shown is required unless the task says it is optional.
```

## Number-matching rule as implemented (`contract.py`)
**Reading a number.** Text is NFKC-normalised, and "percent" or "per cent" after a number is read as `%`. Every number is then read
with `sec_primary.item_figures` as (value, currency, unit):
- commas are removed, and values are compared as exact decimals;
- currency is one of `$`, `C$`, `A$`, euro or pound (US$ and USD count as `$`);
- unit is one of `k`, `m`, `bn` or `%`.

**When a wanted figure (v, c, u) matches a printed figure (v2, c2, u2).** Both of these must hold:
1. If the wanted figure has a currency, the printed one has the same currency.
2. Either v2 == v and (u is empty or u2 == u), or u and u2 are both scale words and v·scale(u) == v2·scale(u2).

**Where the rule is applied.**
- Each `numbers` entry must be matched in a cited item.
- Each figure token of the claim text (`sec_primary.figure_tokens`, using the packet's ticker) must be matched by an entry; otherwise
  it is `number_not_listed`.
- An entry with no number in it is `number_not_found`.
- An entry with several numbers needs every one of them found.

**Examples.**
- `1.2 billion` is found in "1,200 million" and in "$1.2 billion".
- `1.2 billion` is NOT found in a bare "1,200", even under a "$ in Millions" heading, nor in "1.23 billion", "1.2%" or "1.2".
- `1,200 thousand` is found in "1.2 million".
- `15.4%` is NOT found in a bare "15.4", but a bare `15.4` is found in "15.4%".
- `$1.2 billion` is NOT found in "1.2 billion". `€1.2 billion` is NOT found in "$1.2 billion".
- `45` is found in "(45)": magnitudes are compared, and signs and parentheses are not read.
- A claim saying "31.2 percent" whose only entry is `31.2` is `number_not_listed`.

## Deviations, each the more conservative reading
1. **KIS_HALT.** Nothing in rs2-local resolves it. It is a GitHub repository variable of stock-screener (docs/CONTROL_TOWER.md). As the
   WO directs, the manifest records `kis_halt: "not_resolvable_in_rs2"` and the run proceeds. Spec §6 says to refuse when KIS_HALT is
   not set; I followed the WO.
2. **Heading scale is never read.** A number under "$ in Millions" supports only the bare form. This rejects some true claims (false
   `number_not_found`), but it can never produce a false `supported`. SYSTEM tells the model to copy table numbers as printed.
3. **Signs are not compared** (this is sec_primary's reader). `1,200` and `(1,200)` are one magnitude.
4. **Quote normalisation** covers whitespace and quote marks only (NFKC, curly or low quotes and primes to straight quotes, runs of
   whitespace collapsed). Case and dashes are kept. An empty quote, or one holding an omission marker in either spelling, is never found.
5. **New contract fields**, owned by `contract.py`:
   - `point` (required for `thesis_change`): needed to map each answer to a prior point;
   - `settled_by` (required for `unresolved_questions`): "which document would settle it".
6. **`risk_type` values** come from the event types in PROTOCOL §6: guidance_withdrawal, bankruptcy, delisting, restatement,
   liquidity_rupture, contract_rupture, regulatory_action, thesis_break, other. "Liquidity/contract rupture" is split into two types.
   Any other value is a shape error, so the task becomes `malformed`.
7. **Optional `mechanism`/`horizon`/`counter`** may be a string or null. Any other type is a shape error.
8. **Message layout.** There is one user message: the packet first, then the instruction. A malformed retry appends the retry line to
   that same message. This avoids two consecutive user turns in the pinned template, and the system and packet prefix is identical
   across tasks (tested). Packet `annotations` and `excluded` are not shown to the model, because `excluded` names filings that become
   effective after T.
9. **Model tag** is the constant `MODEL = "rs2-analyst-deep-mtp5-v33"`, the v33 Qwen `depth_model` at 481d0cf. It is not read from
   config.json, so a later change to config cannot switch qwen_c silently. `think="medium"`: the pinned template prints no
   reasoning-effort line for medium (it does for low and xhigh). I checked this, not assumed it.
10. **Refusals.** A bad packet (wrong contract, no evidence, duplicate fact_ids, a T without a zone) or a bad option raises `RunRefused`
    before any directory is created, and the CLI exits with 2. Once the run directory exists, `run()` never raises: an unexpected error
    finishes the run as `failed` with its cause. A BaseException such as a crash still propagates, as it should.
11. **Errors outside the spec's table** get `infra_error` with no retry: an HTTP 4xx, any `RawProviderError` other than overflow (such
    as a changed template), or an unreadable response.
    - If `wait_unloaded` does not confirm the unload, there is no retry. Its own contract says never to load on top of a model that is
      still resident.
    - Each kind of retry (malformed, infra) happens at most once per task, so a task makes at most 4 calls.
12. **The 1,800 s timeout** is urllib's socket timeout. With `stream:false` nothing arrives until the reply is complete, so it bounds
    the call, but it is not a separate wall-clock limit.
13. **Parse.** Exactly one fenced ```json block (case-insensitive). With none, the whole content is tried as JSON. Two or more fenced
    blocks, NaN or Infinity make the reply malformed.
14. **Prior run for thesis_change.** It is the newest finished run (complete or analysis_incomplete) in the ledger for the same ticker
    with T earlier than this run's T. Its manifest sha must match the ledger and its analysis sha must match the manifest.
    - If that run does not verify, thesis_change is `infra_error`. No older run is used in its place.
    - If neither its growth_thesis nor its risks is ok, thesis_change is `not_applicable_no_prior`, with the cause.
    - If only one of them is ok, that one alone is used.
    - Prior points (G1…, R1…) are shown together with their code-check `support`. The newer items are those whose `effective_at` is
      after the prior T; an item whose time cannot be read is not counted.
15. **Records.**
    - A malformed retry writes `prompts/<task>_retry.txt` in addition to `<task>.txt`.
    - The seed index is 0-based: business_model gets 1000 and unresolved_questions gets 1006.
    - The manifest `contract` is `m3m.analysis.v1`, with `packet_contract` beside it.
    - The manifest also records `options.differs_from_defaults`, which marks a smoke-test change.
    - `runner.canonical_bytes` repeats the definition in spec §3 instead of importing `packet.py` (WO: no dependency on it).

## Not done, or for the auditor
- I did not test against builder A's real packets. The input was only my synthetic packet. At merge, check that
  `runner.canonical_bytes` equals `packet.canonical_bytes`, and check that the `effective_at` and `source` field names match.
- No live or real-data run (M-LIVE). The test for the real `git_state()` reads this worktree, read-only.
- The pass bar "unsupported figures are never `supported`" holds on the fixtures. It still needs the real-run audit.
