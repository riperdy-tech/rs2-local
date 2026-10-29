# CROSS_CHECK_O: before the first 3O GPU run (2026-10-29)

**Note (10-29):** a Gemini run on this brief was started at ~22:35 KST and stopped on the operator's instruction (no outside AI unless requested) before it wrote anything. Claude ran the cross-check itself; see `CROSS_CHECK_O_RULINGS.md`.

**For:** an outside reviewer (Gemini via agy). Your reply is advice; Claude rules on each point and records the
rulings in `CROSS_CHECK_O_RULINGS.md`.
**Context:** a paper-only investment research system. A factor screener nominates about 60 US stocks each month
(the A0 book). A local model, Qwen 3.8 27B, analyses each company from its own SEC filings through a pipeline called
`qwen_c`. Real money is not involved yet: brokerage stays halted. But these rules will later decide whether model
findings may touch a portfolio, so a design error here costs real money later.

## What to read

1. `SPEC_m3o_integration.md` and `PREREG_m3o.json` (this folder): the rules for three paper arms on the same A0 book.
   - **F:** factor only.
   - **FB:** F plus deterministic text rules.
   - **FQ:** FB plus model findings.
   - A fourth arm (F-A1) is a forward observation of an earlier low-turnover design.
2. `WO_O2.md` (this folder): how the 2026-10-30 formation's analyses will be run before the 2026-11-02 fill.
3. The code change since the last cross-check, in rs2-local branch `review-2026-10/m3n-v6` (worktree
   `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3n-v6`). Run `git diff 626e086 035ef96 -- qwen_c/`.
   - Packet builder v6 adds going-concern passages and shares the 8-K body across its items (`RR_N6.md`, `AUDIT_N6.md`).
   - A `find_prior` fix.
4. Background, only if needed: `SPEC_factor_led_v2.md` and `PROTOCOL_factor_ai_m2_2026-10-23.md` (the folder above),
   and `SPEC_m3n_event_validation.md` (this folder; the 8 event classes and baseline B).

**Do not** open anything under `scratch\rev23\m3n\n5\runs*`, `m3n\n6\`, or any `cache\*\runs\` directory: model outputs
of an evaluation still in progress. Do not edit any file. Do not run the GPU or any model.

## Questions I most want challenged

1. **Look-ahead.** Can any input to an FQ or FB action at formation T carry information from after T? Consider:
   - the decision-run rule;
   - packet acceptance;
   - `finished_at` as a self-claimed clock;
   - re-queuing when the decision run changes;
   - the 180-day windows.
2. **Rule Q1** (SPEC §3.2). A supported critical `material_events` claim restricts a new entry.
   - Is "supported" (a quote or number present in a cited filing) strong enough to call this "source verification"?
   - What false-restriction paths exist? For example: a past event mis-dated, another entity's event, or boilerplate
     risk-factor language.
   - Should a missing `occurred_on` act?
3. **Effects** (SPEC §3.4).
   - A restricted new name's weight is redistributed.
   - A restricted incumbent is held, not sold.
   - Pending and incomplete analyses hold cash.

   Does this bias the FQ − FB or FQ − F comparison? Is cash-versus-redistribution the right split?
4. **Shadow label** (SPEC §5): does it satisfy the earlier rule in SPEC_factor_led_v2 §4, which disables a model buy
   pause until it has been measured? Or does running the FQ series at all already breach that rule?
5. **F-A1 forward.** Is observing the unchanged, historically failed A1 forward a legitimate independent window, or
   is it a back door around "do not tune on viewed outcomes"?
6. **The v6 diff.** Can the going-concern selection or the 8-K segment sharing:
   - drop a key passage that v5 kept;
   - produce duplicate or misattributed text;
   - break the packet's determinism?
7. **The `find_prior` fix.** Can a subset run, a crashed run or an old ledger line still become the wrong prior?
8. **Anything** in SPEC_m3o that contradicts SPEC_factor_led_v2, PROTOCOL_factor_ai_m2, or the "Qwen is mandatory,
   no silent bypass" rule.

## Reply format

Numbered points. For each:
- the file and line or section;
- what is wrong;
- a concrete failing input or scenario;
- severity (critical / major / minor);
- the fix you suggest.

Say "no finding" for a question where you found nothing. Write the reply to `CROSS_CHECK_O_gemini_reply.txt` in this
folder. That is the only file you may create.
