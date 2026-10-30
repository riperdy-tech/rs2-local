# AUDIT_S2: the 3S monthly operating report (2026-10-30)

**Verdict: APPROVED after two changes of mine.** `scratch/rev23/m3s/m3s_report.py` with 35 tests (rerun: 35 passed
after my changes). It has not yet been run on real marks, because none exist until the 11-02 fill.

## Changes made in this audit

1. **The minimum record counts closed periods only.** The builder counted the open period toward the 12 formations.
   Its return is not known yet, so it cannot count toward a skill-claim minimum.
   - `minimum_record` now reports `formations` (closed) and `formations_incl_open`.
   - Three tests were updated: 13 formations are needed for 12 closed periods.
2. **The ledger `current_date` is read from the published copy.** The default was the stock-screener working tree, a
   feature branch dated 2026-09-22. It is now `git:origin/main:public/data/paper_ledgers.json`, read through
   `git show`; a path can still be given.
   - Checked live: `last_updated` 2026-10-29T01:13:17Z; `equal` is 1 day old, `equal_llm` 66 days.

## Accepted open choices (RR_S2)

- **VIX quartile:** the last observation before the fill, against the 5-year 25th/50th/75th percentiles. It is missing
  when the observation is older than 7 days or the window has fewer than 250 observations. These are design values.
- **Event tag:** buckets 0 and ≥ 1, from `resolved` `event_found` lines. A missing journal is missing, never 0.
- **Segments:** a split at every dated register row.
- **No overwrite** without `--overwrite`. A failed section goes to `errors` while the rest still prints.
