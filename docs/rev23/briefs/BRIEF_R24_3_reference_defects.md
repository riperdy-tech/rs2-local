# Brief R24.3: the reference and desk long-run defects, fixed as measured population rules (Phase 4 revision 24)

## Where and how
- **Repository:** rs2-local. **Worktree:** `scratch/rev23/wt-rev24`, branch `review-2026-10/rev24-muse`, **after R24.2 is merged there**. The
  coordinator says when.
- **Limits** (as R24.2): no GPU, model or server; no push, merge or deploy; no deletes; no `.env*`; commit by pathspec; 42 known failures, no
  new ones.

## Read first
- `PHASE_4_REV24_MUSE.md` (R24.3).
- `rev23/defect_census.md`, all of it: O1–O3, U1–U5, and A1 for context.
- The code: `tools/consensus_reference.py`:
  - `margin_rule` (:273);
  - `terminal_growth_default` (:171) and `terminal_default` (:146);
  - `long_run_value` (:330), **the one copy the reference and the desk both call**;
  - `build` (:457), `reference_path`, `_years35`, and the owner-earnings base.
- `tools/throughcycle_record.py`: the record's `om_trend`, `om_L`, `om_tc`, `x_L`, `tax_L` and `g_rev`.
- **The population tables:** `stocks-workspace/data/priors_v5/<vintage>/tables.json`, point-in-time vintages 2012–2025, built in revision 23 with a
  no-look-ahead proof. Their keys:
  - `margin_retention`: bands × k → the median share of a margin deviation from trend still present after k years;
  - `normalization`: bands by cyclicality score × k → the reversion of an abnormal margin;
  - `terminal`: the long-run growth distribution by family, including `shrinking`;
  - `growth_decay`: growth fade by growth band, k up to 10, with `terminal_reference`.

  The vintage for a valuation date T is year(T) − 1. Read them through `valuation/priors.py` / `PopulationPriors` where possible; never write
  to them.

## The fixes. Each is a general rule; parameters come from the tables, never fitted to the census names.
- **O1, margin forced back to its history.** In `margin_rule`, the long-run target becomes
  **target = om_trend + R × (OM_5 − om_trend)**:
  - R is `margin_retention`'s median at its largest measured k, for the company's band (sign and level, as the table's `bands` define
    them);
  - the target is floored at 0;
  - the chosen R, band and k are recorded in the rule's output and the pack text.
- **O2, the translation breaks.**
  - OM_5 stays `om_L + (m5 − x_L)/(1 − tax_L)`, but when the translated OM_5 is outside [−0.5, 1.0] (an impossible operating margin), or the
    gap between the operating and the earnings margin exceeds the earnings margin itself, the rule is **not applied**. It gets a new stamp,
    `margin_rule_translation_out_of_range`, the reference is **withheld** (status `not_available`, with that reason), and the margin is never
    zeroed.
  - m_long = m5 × (target / OM_5) (proportional) when OM_5 > 0.
- **O3, terminal growth from the record.** In `terminal_growth_default`, the record's revenue trend no longer sets terminal growth for a
  growing company. Terminal growth = **min(anchor, growth_decay's `terminal_reference`)** for the family. The long-run fade length
  (`FADE_YEARS`) becomes **growth_decay's measured horizon** (`horizon_k − 5`), recorded. Tests must show the desk and the reference agree.
- **U1, normalization switched off.** When `margin_rule` cannot apply (no revenue path, too short a record, out of range), the reference is
  **withheld** (`not_available`, reason named). Spot earnings growing forever are **never** printed as the reference.
- **U2, a shrinking company growing forever.** When the record's revenue trend `g_rev` < 0, terminal growth = **max(`terminal`.shrinking p50 for
  the family, g_rev)**, never above 0 and never breakeven inflation. The table value is recorded.
- **U3, owner earnings for an under-investor.** When `g_rev` < 0, owner earnings use **capex at least equal to D&A** (maintenance), and the
  difference is recorded.
- **U4, peak earnings held five years.** When the base margin is above the record's through-cycle margin by more than `normalization`'s band
  cut for the company's cyclicality score, years 1–5 apply the table's **reversion by k** from year 1 (not from year 6). The band, the score
  and the fractions are recorded.
- **U5, valuing spot earnings with no reference.**
  - The pack flags `peak_earnings_risk` when U4's condition holds, or the record's cyclicality score is in `normalization`'s top band.
  - With the flag, the TASK requires the analyst's desk Base to use the through-cycle earnings basis (the existing desk argument that takes
    the record's through-cycle margin).
  - A Base on spot earnings with the flag fails the fiduciary gate (`spot_earnings_on_peak`, a new reason).
- **DDI (controlled company):** no change. It is the analyst's judgment.

## Tests (each fails without its fix)
- A synthetic record per defect: O1 retained margin (not trend); O2 out of range → withheld, never zeroed; O3 terminal ≤ anchor from the table;
  U1 withheld; U2 negative terminal for a shrinker; U3 maintenance capex; U4 normalization from year 1; U5 the gate fails spot on peak.
- **Desk and reference agree** on `long_run_value` for the same inputs.
- **Point-in-time:** a date in vintage year Y reads tables Y − 1. Show a 2024 date reading 2023.
- **The before-and-after table** over the baseline's 33 census names, using their saved revision-21/22 facts. For each: the old and new
  reference ÷ price, the defect(s) that applied, and the new status. **Reported, not tuned to.** The coordinator reads it.

## Deliverable
The commits, the suite counts before and after, the 33-name table, and every judgement call or gap, as text. Decide nothing left open.
