# WO_Q1: read-only inventory for 3Q, the valuation engine and Qwen reasoning repair (2026-10-29)

**Goal:** the facts a 3Q spec needs (PLAN §3Q). This WO only describes; it proposes no fix.

**Read-only:**
- No edit, no git change, no GPU, no network.
- Never read `.secrets.json` or `.env*`.
- **Do not open any untouched holdout's labels or outcomes.** List the holdouts and where they are recorded, but do not
  read their scored results if a record says they are sealed (CTVA, NHC, TTAM, CLDT and any other named holdout).

**Start at:**
- `stocks-workspace/docs/review_2026-09-22/rev23/handoff_2026-10-23/00_README_START_HERE.md`;
- `rev23/SPEC_factor_led_v2.md` §0;
- `rev23/REPORT_*` on revisions 25 and 26;
- the memory notes the README points to;
- the rs2-local branches `review-2026-10/d2-port`, `r26-harness` and the live desk branch, with `git -C ... log/show` only.

## Questions (cite file:line or record)

1. **Revision 26's recorded failure modes.** Coherence 1/9 and 0/9: what exactly failed, per the records? List each
   failure class with its count and an example case id.
2. **The D2 year-6+ reinvestment/fade convention** (memory `terminal-reinvestment-d2`: O1–O8 approved 2026-10-18, the
   desk port split a/b/c). What was approved, what is built (which commits, on which branch), and what is still open?
   Which convention is decided, and which is undecided ("reinvestment follows sales vs earnings growth")?
3. **The valuation code map.** Where the growth, margin, reinvestment, cost of capital, tax, dilution and terminal value
   arithmetic lives today (file:function), and which parts are deterministic code versus model text.
4. **Business models.** Is there any existing handling for financials, cyclicals, capital-intensive businesses or REITs?
   Where, and how does it work?
5. **The evaluation panels:**
   - which panels are consumed (scored and viewed);
   - which are untouched holdouts, and where each is recorded;
   - which date windows are still unviewed and eligible for a new evaluation.
6. **The existing reconciliation checks** between model prose and numbers (fiduciary gate, contract FAIL kinds,
   dispersion quarantine): what each checks, and its file:line.

## Report

`RR_Q1.md` in this folder: one section per question, evidence-cited, then a short list of the open decisions 3Q will
need from the operator.
