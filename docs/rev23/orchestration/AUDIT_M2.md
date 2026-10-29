# AUDIT_M2: builder A's raw store, packet and replay (2026-10-29)

**Verdict: APPROVED, after one rule change made in the audit.** Committed with WO_M3's work as `42640f8` on
`review-2026-10/m3m-qwen`. The full `qwen_c` suite passes: 175 tests.

## Read

`packet.py` was read line by line. Its rules check out:
- the acceptance rule is identical to `m3l_sec_pit_asof.py`;
- `_pick` lists in `excluded` only the filings that existed at T, by their earliest reading;
- the screener commit must not be dated after T;
- the trimming order is as specified;
- the calendar has fixed bounds, so no clock is read.

`sec_store.py` and `replay.py` were read through their interfaces and tests. Every replay input is pinned.

## Rule change: a short Item 1A after a contents entry

The builder kept the work order's rule that a heading followed by fewer than 1,500 characters is a contents entry.
That rule dropped real one-sentence 10-Q Item 1A sections ("no material changes"), in 5 of 8 cases.

**Ruled:** the first heading with a body of 1,500 characters or more wins. If no heading qualifies, the **last** of
two or more headings of the item is kept when its body has at least 100 characters. A single short heading is still
not found, because it may be the contents entry itself.

New test: `test_a_short_last_section_after_a_contents_entry_is_kept`. On the real data, MA P5 (166 characters) and
HRTG P5 (277 characters) are now found.

## Rulings on RR_M2's deviations

| Deviation | Ruling |
|---|---|
| CIK read from `cik_map.json` at the same commit, with its blob id in the header | Accepted |
| `name`/`title` added to evidence items | Accepted |
| A required `verified_record`, and extra refusals (no factor profile, commit dated after T, malformed commit, naive T) | Accepted: all conservative |
| Sections keep their start when cut; only the release uses `select_text` | Accepted |
| Foreign filers get no release item (no 6-K rule) | Accepted for v1. It is annotated `no_eligible_filing: release`. A 6-K release item is a v2 candidate. |
| Only `filings.recent` of the submissions is read | Accepted: it covers about a year or 1,000 filings, enough for the latest annual and quarterly reports |
| Calendar bounds 2005–2031 | Accepted. **It must be widened before 2031.** |

## Real data: gate M-P4

- **Built:** 5 packets online at T = 2026-10-29T01:31:51Z on screener commit `92592e21`, the output of verified run
  40796224964. Their sizes run from 48,756 bytes (ILMN) to 134,745 bytes.
- **`replay`:** **5/5 byte-identical** offline.
- **Spot checks:**
  - MA: the 10-K (accepted 2026-02-11) is effective 02-12 13:30Z; the Q2 10-Q is used, because no Q3 10-Q was
    accepted before T.
  - MA P2 starts at "ITEM 1A. RISK FACTORS" and is cut with an omission marker.
  - HRTG's Q3 earnings 8-K, accepted `2026-10-28T20:25:14.000Z`, is excluded and listed (effective 10-30 13:30Z).
- **Finding (systemic, not patched per ticker):** ILMN's 10-K and 10-Q use a cross-reference-index layout. The body has
  title headings ("RISK FACTORS") and no "Item" headings. All 5 sections are annotated `section_not_found`. How common
  this layout is in the screener universe is unmeasured, and that census belongs in 3N.

**M-P4: PASS** (unit negatives plus a real-data replay).
