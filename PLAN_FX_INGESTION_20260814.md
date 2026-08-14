# PLAN — FX-AWARE INGESTION (Option C) — 2026-08-14

Operator-approved plan. Executed by a dedicated session; this file is its contract.
CLAUDE.md §0 (RS2 Local) governs everything: measure first, no invented constants,
gaps are STOP conditions.

## Context (measured, do not re-derive)

- Foreign 20-F filers are ingested with statements in their REPORTING currency while the
  quote side is USD. FMX: TTM revenue 873,528,000,000 (MXN) and MXN balance-sheet legs
  (EV 172.63B) against a USD 23.06B market cap. Its reverse-DCF raw MoS of +2984% is
  mostly the MXN/USD factor (~18.6x) — not a valuation.
- Known-affected set from the 2026-08-12 handoff: FMX (MXN), TSM (TWD, base FY2024 —
  no 10-Qs, so no TTM), SAP (EUR), BWMX (MXN). This list is a HYPOTHESIS to re-measure,
  not the answer.
- 2026-08-14 state: FMX/TSM/SAP pulled from the live LLM overlay as
  unreliable-pending-data (screener commit f7a4d36ff4); BWMX was already absent.
  Restoring them is the success criterion and is OPERATOR-GATED.
- A vendor identity guard now forces Market_Cap = price x shares on a >2% payload breach
  and preserves the vendor figure as Market_Cap_vendor (screener commit 816786749a,
  scripts/fetch_data.py ~line 596 + both get_ticker_data*.py helpers). Do not undo it.

## Scope

1. **Measure the affected set.** Every live-book name whose yfinance
   `info.financialCurrency != "USD"` (also inspect the defeatbeta source used by
   fetch_data.py). Report the full list with currencies before designing anything.
2. **Design statement normalization** in the screener's detail builder
   (scripts/fetch_data.py, assembly around lines 585–700) and mirror in the helpers:
   - detect statement currency per name;
   - convert FLOWS (income statement, cash flow) at fiscal-period-AVERAGE FX and STOCKS
     (balance sheet) at period-END FX; rates from yfinance FX pairs ("{CCY}USD=X")
     history — MEASURE availability and era coverage first. If period-appropriate rates
     cannot be obtained for a period, that is a STOP/flag for that name, never a silent
     spot-rate substitution.
   - ADS/perimeter check per affected name: the shares field is the ADS count. With
     statements converted to USD, verify the earnings PERIMETER matches the share
     count's claim on it (FMX ADSs represent a subset of FEMSA's capital). The vendor's
     Market_Cap_vendor / price gives the vendor's implied whole-company ADS-equivalent
     count — reconcile against filings. If the perimeter cannot be proven, STOP and flag
     that name; do not approximate.
   - TSM's missing TTM (20-F, no 10-Qs) is a SEPARATE gap: FY-anchor only. State it;
     do not fabricate a TTM.
3. **Implement on branch `fx-aware-ingestion`** in the screener repo. NEVER push main —
   the cloud runs main's extractor on a schedule against the whole universe.
4. **Validate (ladder):**
   - USD names: run the new path on a sample (e.g. AAPL, CHEF, MU) and PROVE
     value-identical output — zero field changes.
   - Affected names: identity guard silent (mcap vs price x shares within 2%); EV legs
     in one currency (EV/mcap ratio sane); FMX EV/Sales lands near comparable staples
     multiples rather than 0.05x; hand-check FMX converted revenue against FEMSA's own
     USD convenience translation and TSM against its USD ADR reporting.
   - RS2 gate: `python data_health.py --gate-live` stays CLEAR with regenerated files.
5. **Regenerate locally ONLY the affected names'** financials/{T}.json through the new
   code (yfinance-sourced; the companyfacts-staleness rule does not bind here — confirm
   before relying on that) and commit data + code to the BRANCH.
6. **Report**: affected set, method, per-name before/after, validation evidence, open
   STOPs. The operator merges to main.
7. **After operator merge**: run the affected tickers through RS2 —
   `python tools/run_batch.py --tickers "..." --log reports/_fx_refresh.log
   --wait-lock 7200 --pause-after`. Never call orchestrate.py directly; never run while
   cache/orchestrate.lock is held (a contested campaign is running in ~3.5h chunks).
   run_batch forces --no-push. Do NOT restore FMX/TSM/SAP to llm_overlay.json — that
   decision is the operator's.

## Constraints (non-negotiable)

- RS2 ENGINE FILES are frozen while any batch runs: run_rs2.py, rs2_data.py,
  valuation_backbone.py, orchestrate.py, RS2-Analyst.Modelfile, config.json,
  outcome_feedback.py. This plan should not need them; if it does, STOP and report.
- No pushes to screener main. No publishes. Nothing touches the live site.
- Delete nothing under reports/ or cache/.
- One change, then one test. Small diffs. Every constant derived from measurement or
  flagged as unproven.

## Success criterion

The measured affected set valued on internally consistent USD bases; gate CLEAR; USD
names provably unchanged; a written report that lets the operator decide restoration.
