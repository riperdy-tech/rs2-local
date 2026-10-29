# AUDIT_M3: builder B's prompts, contract and runner (2026-10-29)

**Verdict: APPROVED, after one fix made in the audit.**

## Read

`tasks.py`, `contract.py` and `runner.py` were read line by line; the test list was read; `RR_M3.md` was read.

**Suite:** 111 passed (`test_runner`, `test_tasks`, `test_contract`), including 5 new tests added in the audit.

## Defect found and fixed: a false `supported` (the failure the spec forbids)

- **What happened:** `number_not_listed` used `sec_primary.figure_tokens`, which by design ignores small whole numbers
  and bare integers. A claim such as "Revenue grew 12%", with no `numbers` and 12% printed nowhere in the evidence,
  came out `supported`. The probe reproduced it.
- **Fix:** every number `figures_of` reads in the claim text must be listed in `numbers`, and every listed number must
  be found in a cited item. The only exceptions are a bare year from 1900 to 2100 and an all-digit ticker. The unused
  `_token_tuple` helper was removed.
- **Regression tests:** `test_every_claim_number_is_listed_and_found`, with 5 cases (12% unlisted, 15% not printed,
  12% listed, "3 segments" unlisted, and a bare year).

## Known limitation, recorded and not fixed here

**Signs are not compared.** A claim of "net income 456" against an item printing `(456)` is `supported`. `supported`
therefore means only that **every figure is printed in a cited item, and every quotation is verbatim**. It does not
mean the claim is right. That is the 3N measurement, and the spec now says so.

## Rulings on RR_M3's deviations

| Deviation | Ruling |
|---|---|
| `KIS_HALT` is not resolvable in rs2 (it is a stock-screener repository variable); the manifest records `not_resolvable_in_rs2` | **Accepted.** `qwen_c` writes nothing that KIS reads (no overlay, no `rn_depth`), so the hold cannot be affected by a run. The spec is amended. |
| New fields `point` (`thesis_change`) and `settled_by` (`unresolved_questions`) | **Accepted**, owned by `contract.py` |
| Risk type "liquidity/contract rupture" split into two types | **Accepted** |
| The prior run is the newest finished ledger run before T; an unverifiable prior gives `infra_error` and never falls back to an older run | **Accepted**: no silent substitution |
| The model tag is pinned in `runner.py`, not read from `config.json` | **Accepted**: a config change cannot switch the model silently |
| `RunRefused` before any write; never raises after | **Accepted**: matches the spec |
| The template prints no reasoning-effort line for "medium" | **Noted.** M-LIVE measures what "medium" does |

## Open for the merge with builder A

- `runner.canonical_bytes` must equal `packet.canonical_bytes`.
- The `effective_at` and `source` field names must agree with the real packets.

## Second fix, from Claude's adversarial probe (commit `f584410`)

- **What happened:** the year exemption in `number_not_listed` waved through every bare integer from 1900 to 2100. So
  "Cash was 2,034 (table in millions)", with 2,034 printed nowhere, was `supported`.
- **Fix:** a year-like number is exempt only when a cited item prints it.
- **Tests:** two new cases.

## Limitation, recorded for 3N

The checks test **presence, not meaning**. A claim that cites many large items can have a common small figure found
somewhere in them by chance. The S0 screener row also prints hundreds of numbers.

So `supported` is a necessary condition, not a sufficient one. The 3N blinded review measures semantic support. Until
then, a claim's support count is never read as accuracy.
