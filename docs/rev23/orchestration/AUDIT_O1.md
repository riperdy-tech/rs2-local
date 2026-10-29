# AUDIT_O1: the 3O paper decision engine (2026-10-29)

**Verdict: APPROVED.**
- **Code:** `scratch/rev23/m3o/m3o_engine.py` (757 lines, `m3o_engine.v2`) with `tests/` (54 tests) and `fixtures/`.
- **Build:** a Claude builder subagent wrote it, against WO_O1 plus the CROSS_CHECK_O amendment.

## What I checked

- **The whole engine, line by line.** Against SPEC_m3o v1.1 and PREREG_m3o v1.2:
  - **B1:** the 180-day window on each item's `accepted_raw`, read by the packet's own later-reading rule. A hit with no
    acceptance date does not act.
  - **Q1:** acts only on `supported` claims. `announced_pending` acts. An `occurred` claim acts only when it has one
    parseable date in the registered forms, that date is printed in a cited item, and it falls within 0–180 days before
    T. An undated or unsupported date becomes an `escalation` line that affects no series.
  - **E1:** a restricted new name is not entered, and its weight goes to the rest. A restricted incumbent is held and
    flagged `pending_reunderwriting`. A name exits only when it leaves A0.
  - **A1S:** a pending or incomplete slot is held as cash in FQ only. It is filled in FB and `FQ_decisions_only`.
  - Operator-excluded names are never in FB or FQ. F keeps them, and `F_ex_operator` is the marks-only series without
    them.
  - Fill-open lines depend only on `finished_at`, which is a self-claimed clock and is labelled so. Later outcomes are
    separate `completion` and `pending_resolution` lines.
  - The stop rule reconciles every file before anything is appended.
  - The provenance fields match the real manifest. I checked `qwen_c.git_commit` at `runner.py:561`.
- **The tests:** I reran them: **54 passed**.
- **A real-data dry run** (scratchpad only):
  - A temporary map for the 2026-09-30 formation, labelled retrospective, with no packets and no runs.
  - **F: +1.23% gross, +1.13% net at 20 bp. F without the excluded names: +1.66%. SPY: +0.69%.** These equal RR_L7's
    A0 mark exactly, so the engine reproduces forward_ledger's arithmetic on real prices.
  - FQ, with every analysis pending, holds cash (0.0%), as A1S intends.
  - Line counts reconcile: 60 factor, 58 qwen (60 less 2 excluded), and 240 action lines (4 series × 60).
  - The `git show` loader for `factor_scores.json` ran end to end.

## Rulings on the builder's open choices (RR_O1)

1. **Fill-open lines never change; late outcomes are separate lines:** accepted. It keeps the stop rule sound.
2. **A pending slot enters at the first open strictly after `finished_at`:** accepted.
3. **Incumbents whose analysis is pending or incomplete are held, not sold:** accepted (monitoring never sells). The
   cash slot applies to new entries only.
4. **Day arithmetic in UTC dates, 0–180 inclusive:** accepted.
5. **Stop-rule tolerance 1e-6; price receipt and map hash ignored in the comparison:** accepted. The decision fields
   are still compared exactly.
6. **`no_price_series` in the marks:** accepted.
7. **The `accepted_raw` and `factor_scores` fields:** accepted.

## Carried (not blocking)

- **Event response for critical events found later**, and Qwen operations (completion rate, GPU hours): these need the
  3P journal and the WO_O2 run telemetry. They go to RR_O2 and WO_P2/P3.
- **An audit script that reconciles the four ledger files:** before 3O closes.
- **`POST_3N_FIRST_FORMATION`** is set by hand when 3N closes, recorded in LOG.
