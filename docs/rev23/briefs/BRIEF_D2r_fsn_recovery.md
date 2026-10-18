# Brief D2r: recover extension-tag capex from the SEC Financial Statement data sets (measurement first)

## Why
`companyfacts.zip` carries no company-extension XBRL elements. Of the 160 census names, 27 have no window year with revenue, capex
and D&A together (`scratch/rev23/d2_coverage/m/m_result.json`, `pooled_no_complete_year`), and most of them file capex under extension
tags. See `PLAN_terminal_reinvestment.md`, the section "Rulings on the outside reviews of the coverage decision".

## The source
The SEC's **Financial Statement Data Sets**: quarterly zips, each holding `sub.txt`, `tag.txt`, `num.txt` and `pre.txt`.
- `num.txt` holds custom tags too: `version` = the accession number, and `tag.custom` = 1.
- `pre.txt` gives the statement (`stmt` = CF), the line and the preferred label (`plabel`).

Steps:
1. Verify the current URL pattern on sec.gov before downloading (it was `https://www.sec.gov/files/dera/data/financial-statement-data-sets/YYYYqN.zip`).
2. Download the quarters that cover the annual filings for fiscal years 2020–2025, to `scratch/rev23/sec_data/fsds/`.
   - Use the User-Agent `StockScreener/1.0 (contact@example.com)`, as the screener does.
   - Pause at least 1 s between requests.
   - SEC downloads have standing operator approval.
   - Check that each zip is complete before using it.
   - Report the total size.

## Build (a measurement script, not wired into any pipeline)
Write `scratch/rev23/d2_recovery/fsds_capex.py`. For each of the 27 names, and for the 160 names as a control:
1. **Filings.** Map ticker to CIK with the screener's `cik_map.json` (read only), then to the annual filings in `sub.txt` (10-K, 10-K/A,
   20-F, 40-F) and their fiscal year and period end.
2. **Candidate lines.** Take the cash-flow statement lines (`pre.stmt` = CF) for those filings. A candidate is an outflow line whose
   tag or `plabel` matches property / plant / equipment / vessel / fleet / aircraft / capital expenditure / additions to / construction /
   productive assets / rental equipment / satellites. Exclude acquisitions of businesses, securities and investments, intangibles alone,
   loans, and deposits.
   - Use the full-year duration (`qtrs` = 4), in USD only.
   - Standard and extension tags are both eligible. Record whether each is custom.
3. **One number per filing.** Exactly one candidate means use it. More than one: if the labels show a sum, such as "vessels" plus
   "other fixed assets", report them as components and do **not** sum them automatically; mark the filing `ambiguous_multiple`. No
   candidate means `none`.
4. **Agreement with the screener and the vendor:**
   - **Screener:** where the screener's own `capex` or `capex_d2` exists for that year, compare (from the coverage-round data in
     `scratch/rev23/d2_coverage/m/data_build`). This measures the rule's error on known values.
   - **Vendor:** take the vendor's multi-year annual capex from the stock-screener vendor financials files (read only; report what
     history they hold).
5. **Output:** `scratch/rev23/d2_recovery/fsds_capex.json`, holding per name and year:
   - value, tag, custom flag, plabel and accession;
   - the candidate count;
   - the screener comparison and the vendor comparison.

## Report (≤40 lines)
- Download size and quarters.
- **The control,** on names with known capex:
  - how often the rule picks the same number as the screener (within 1%), and the error distribution;
  - the false-pick cases by label.
- **The 27 names:** how many get a single candidate in ≥ 3 of the 5 window years, and how many of those agree with the vendor
  multi-year history (report the ratios; set no band yet).
- Names still unrecoverable, and why.
- Ambiguities for a ruling.

## Limits
- Read only on every repository.
- No commits; scratch outputs only.
- No GPU.
- About 12 GB of RAM: stream `num.txt` filtered by CIK, and never load all quarters at once.
