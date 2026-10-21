#!/usr/bin/env python3
"""capability_test.py — has the local model ever actually been ASKED to do the job?

Phase E recommended putting a frontier model in the depth tier. That recommendation embedded an
untested assumption: that the local model cannot do what the benchmark GOOG analysis did. RS2 has
never once asked it to. Every production constraint points the other way:

  * config.json think=False        — reasoning disabled to satisfy a format contract
  * S1 prompt "DO NOT select a valuation engine"
  * S3 prompt "The intrinsic value is NOT yours to compute"
  * FINAL_TASK "you may NEVER print a different value" than the engine header
  * AI_AUDIT_PROMPT treats the engine number as AUTHORITATIVE -> a model that CORRECTS a
    contaminated fair value is scored as a violation and the run repeats
  * stage carry truncated to 4,500 chars, severing cross-stage reasoning
  * the basis-decision evidence pack withheld capex/OCF/FCF (the `da` gate, defect D3)
  * financials/{T}.json fed FY figures labelled as current (defect D5)

This harness removes ALL of those and gives the model the same conditions the benchmark had:
honest, correctly-period-labelled data; the full RS2 framework (baked into the model); thinking
ON; one long context; and ownership of BOTH the engine choice and the intrinsic value.

It is deliberately NOT hinted. The pack contains no mention of one-off gains, no pre-computed
base_cf, no fair value. Whether the model notices that TTM net income ($244.2B) exceeds TTM
operating cash flow ($185.7B), and that one quarter printed a 93.6% net margin, is exactly what
is being measured.

Output: ab_reports/capability_test/{TICKER}_{ts}/ — isolated, never ingested by the overlay.

  python tools/audit_202608/capability_test.py GOOG
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))   # base_rates.py / growth_persistence.py (D11)
from pack_data_sanity import check_pack_data_sanity

import rs2_data  # noqa: E402
import sec_guidance  # noqa: E402
import sec_primary  # noqa: E402
import base_rates  # noqa: E402
import growth_persistence  # noqa: E402
import world_news  # noqa: E402
import company_news  # noqa: E402
import catalyst_research  # noqa: E402
import consensus_reference  # noqa: E402
import population_ranges  # noqa: E402
import throughcycle_record  # noqa: E402
import input_scope  # noqa: E402
import pack_facts  # noqa: E402
import r26_blind  # noqa: E402
import pi_text  # noqa: E402
import x_margin_basis  # noqa: E402

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
OUT = HERE / "ab_reports" / "capability_test"
CTX = 65536          # default; --ctx overrides. Pair large values with OLLAMA_KV_CACHE_TYPE=q8_0
# num_predict covers THINKING + CONTENT together. MEASURED 2026-08-20 (arm B): at think=max the
# model spent ~30k tokens reasoning and was cut off at SECTION 2.5 of 12 with only ~2k left for
# the report. A full RS2 report needs ~12k of content, so budget generously or the deliverable
# is silently truncated and looks like a quality failure.
MAX_TOKENS = 49152
# The ONE string meaning "we do not hold this value". Never 0, never blank, never omitted -
# a null the model cannot distinguish from a zero corrupts every flow computed from it.
NULL = "not available"
# Companies filing no combined D&A concept: our extract carries DEPRECIATION ONLY for these,
# via a hard-coded allowlist in the screener extractor. Disclosed in the pack, not hidden.
LONE_DEPRECIATION_NAMES = {"GOOG", "GOOGL", "UNP"}
TIMEOUT = 14400

# Bump ONLY when a change alters what the model is actually told — new data, a corrected
# declaration, a changed caveat. Do not bump for wording or formatting: every bump re-runs the
# whole published book at roughly 76 GPU-minutes a name. Verdicts record the revision they were
# produced under, and depth_triggers queues any name below the current one, so a book cannot end
# up half-analysed on a superseded pack. A verdict with no stamp counts as revision 1.
#   1  everything up to 2026-08-24.
#   2  2026-08-24. SBC series, SECTION 6B debt/investment components, SECTION 12 declarations
#      computed per ticker instead of hard-coded (four of them had gone false after the
#      2026-08-23 extractor rebuild), unreviewed-field sensor, SECTION 8/9 fetch-age stamps,
#      and the 1000x filed-series corruption alert.
#   3  2026-08-24. The last four hard-coded population counts ("18 live names", "51 live names",
#      "38 live names", "3,380,466 fact rows") replaced by per-company facts read from sec_facts:
#      which share tag this column actually carries, our capex against the vendor's, which years
#      fail the pre-tax identity, and a verified segment-row count. Bumped rather than folded into
#      2 because one ticker was mid-run and would otherwise have kept revision 2 with the older
#      pack; it re-runs once at 3 either way.
#   4  2026-09-20. SECTION 5 gained an `owner CF [Arithmetic]` column (OCF - capex - SBC, per
#      fiscal year, blank where any input is absent) and the Section 12 contract gained
#      `base_cf_used` and `base_cf_basis`, which the analyst must now declare. This is a DERIVED
#      column, not new filed data - all three inputs were already printed in the same table - so
#      the strict reading of the rule above ("new data, a corrected declaration") does not quite
#      cover it. Bumped anyway, by operator decision: the pack TEXT changes, and the analyst's
#      basis choice is precisely the quantity under measurement (GEV, 2026-09-20, read ~$12.4B in
#      one run and ~$5.0B in another on the same dossier), so verdicts before and after must not
#      share a stamp.
#   5  2026-09-23. SECTION 1.5 never invents a macro number: replaced or-defaults with None;
#      sourced block anchor-first from MRI capital-market anchors (nominal and real 10y, breakeven,
#      implied ERP, implied CoE, sector loading, metadata) with macro_state.json series as
#      secondary source; regime date freshness gate (<= 45 days); regime label demoted and full
#      probability vector + headline margin printed per operator ruling; mandate line conditional
#      on present Rf; pack-level flag macro_degraded carried onto consensus runs when inputs missing.
#      AMENDED same day (B6, Phase 1 approval review): the regime demotion was incomplete — the
#      capitalization mandate still conditioned its terminal-multiple instruction on the regime
#      LABEL ("In the current {headline} regime, derive terminal multiples..."), with a headline
#      margin as thin as 0.044. The mandate text is now unconditional (label removed entirely),
#      and the "Current Macro Regime" line prints the probability vector FIRST and the label
#      second, as a contested headline with its margin, e.g. "headline goldilocks (margin
#      0.044 — contested)". Not a new PACK_REVISION: no revision-5 verdict exists yet to
#      distinguish from (ledgers hold {3, 4}; the sweep is paused).
#   6  2026-09-24 (Phase 4 T3, PHASE_4_PACK_SPEC.md D3/D4/D8/D9/D10/D11, AMENDMENTS B1/C1/C3/E2/E3,
#      ANALYST P4.0a §12 fields, P4.2 §12 fields). Every change alters what the model is told:
#        - SECTION 1.5 gained the `COE ANCHOR for this name` line (rf + sector loading x implied
#          ERP) with the +-150bp mandate, and the `Long-run nominal growth anchor for terminal_g`
#          line from long_run_growth_anchor.json (D3).
#        - NEW SECTION 1.6 "STATE OF THE WORLD [dated facts, not a forecast]": the full 5-way MRI
#          regime probability vector with headline+margin, active shocks from the S4 register (or
#          "none active"), the `elevated_volatility_ahead` risk flag, the dated rf/real/breakeven
#          10y legs, and an inflation-trend line printed only when the anchor carries one (D10/E3).
#        - NEW SECTION 2.5 "PRICE ACTION (facts, not a valuation input)": momentum facts read from
#          factor_scores.json's per-ticker `fct_momentum_state`/`fct_z` ONLY — never the screener's
#          band, rank, door, composite or falling_knife label (P4.1 as amended by B1/C3). Fields
#          this pack cannot source yet (200d mean/slope, RS vs cluster ETF/IWM, 60d realised vol,
#          mom_break) print `not available` rather than being invented.
#        - NEW "GROWTH BASE RATES" block (financials area): the company's size-bucket 5y/10y
#          sustained-growth base rates, measured fresh from fundamentals_history.json (new module
#          `tools/base_rates.py`, cached per file sha within the run), plus the conditional "given
#          the growth just delivered" table from `tools/growth_persistence.py`, plus the p90
#          evidence mandate and the survivorship caveat (D11/E2).
#        - "GUIDANCE & CONSENSUS" block: company's own earnings release from SEC EDGAR (newest
#          8-K or 8-K/A with Item 2.02, EX-99.1/EX-99.01/EX-99 exhibit text, verbatim dated
#          guidance excerpt, STALE flag past 120 days), followed by research-brief rows when
#          present (fenced ```guidance``` table: `metric | period | value | source | date`),
#          or states plainly when unavailable (D4/D4b).
#        - SECTION 11's header reverts to "Written by another model, not verified — every figure
#          is a claim to check against the filings above; cite the filing when you rely on it."
#          Every "verified ... ground truth / ingest directly" phrase is removed from the pack and
#          from RESEARCH_ADDENDUM (D8).
#        - A "DATA WARNINGS" block (T2's `pack_data_sanity` checks) now prints at the TOP of
#          SECTION 2, and the shares-outstanding line states its source and as-of date explicitly
#          (D9).
#        - NEW "SECTION 8.5 - PEER CONTEXT [Aggregator, context not an anchor]": cluster peers'
#          trailing P/E and EV/EBITDA from stocks.json (this pack STATES which of the two fields
#          is actually usable before printing either — measured 2026-09-24: `peRatio` is 0 for
#          every one of 6,949 names on file and `stocks.json` carries no EV/EBITDA field at all, so
#          both currently print `not available` with the reason stated, not silently), and the MRI
#          sector trailing-P/E band from `sector_multiple_bands.json` via
#          `rs2_data.anchor_multiple_bands`. SECTION 8/9 fetch-age stamps now show `STALE (n days)`
#          past 45 days and SUPPRESS the values themselves to `not available (stale)` rather than
#          merely flagging them (P4.10).
#        - TASK's SECTION 12 JSON contract gained every field the harness already whitelists but
#          the prompt never asked for: `coe_used`, `coe_source`, `coe_adjustment_reason`,
#          `valuation_frame`, `terminal_method`, `terminal_multiple_or_g`, `fade_years`,
#          `stage1_growth_path`, `guidance_deviation_reason`, `cycle_evidence`, `verdict_label`
#          (P4.0a) and `momentum_view`, `entry_timing`, `momentum_flip_condition`,
#          `momentum_break_rule`, `invalidation_rules` with the metric vocabulary (P4.2). TASK now
#          instructs that ALL valuation arithmetic runs through `run_financial_model` (three-stage,
#          both terminal legs, neutral reverse DCF), base IV must be a desk result, the desk's
#          neutral reverse-DCF implied CAGR and its base-rate band must be printed and argued
#          against, and a cyclical treatment requires `cycle_evidence`.
# Revision 7 (Phase 4 E10, 2026-09-24): stage-1 growth is growth of the CASH FLOW, not revenue;
#   Base years 1-2 start from consensus EPS growth; SECTION 8 prints the CONSENSUS-IMPLIED VALUE;
#   EARNINGS QUALITY no longer pushes the base to an older year. A revision-6 pack and a
#   revision-7 pack give the analyst different instructions and must never be graded as one.
# Revision 8 (Phase 4 E12, 2026-09-25): SECTION 6 prints one NET DEBT default (cash and short-term
#   investments); the TASK pins the share count, net debt and bull/bear years 1-2; the contract
#   gains shares_basis, shares_reason, net_debt_reason, scenario_deviation_reason; RECENT COMPANY
#   NEWS carries the opening text of the top stories (E11).
# Revision 9 (Phase 4 E13, 2026-09-25): SECTION 1.5 prints the DEFAULT EXIT MULTIPLE (the net
#   capitalization rate at the anchors) and the desk returns the terminal growth an exit multiple
#   implies; the equity frame is the default, because every flow the pack prints is after interest
#   and the pack anchors a cost of equity; the firm frame needs interest_addback and wacc_reason;
#   the contract gains terminal_multiple_reason, interest_addback and wacc_reason.
# Revision 10 (Phase 4 E18 + the terminal-g pin + small fixes, operator ruling 2026-09-26): the
#   CONSENSUS-IMPLIED VALUE is built on the last full fiscal year and rolled forward, prints the
#   year-1 and year-2 cash-flow levels (and Bull/Bear year-2 levels with 3+ analysts), and its
#   years 3-5 never rise above next-FY revenue growth; the TASK anchors Base years 1-2 to the
#   levels, not the rates; terminal_g off the anchor needs terminal_reason; the 10% direction band
#   is stated; the estimates table shows EPS analysts; base-year and TTM-freshness lines; guidance
#   range for Bull/Bear without a consensus range; takeover-offer wording; the momentum date; the
#   SECTION 5 column "owner CF" is renamed "cash basis"; reason fields take null when unneeded.
# Revision 11 (Phase 4 draw review, operator approval 2026-09-27): the desk tool definition marks
#   shares_diluted, terminal_g, fade_years and sbc_treatment required (F4); a per-name TERMINAL-GROWTH
#   DEFAULT: below the anchor's reach the default path rises no further than zero real growth
#   (breakeven inflation), not to the anchor (T1); the TASK says the desk does the arithmetic; years 3-5
#   above next-FY revenue growth need guidance_deviation_reason (F5).
# Revision 12 (Phase 4 development runs, reviewer ruling 2026-09-27): every valuation declares cash_flow_life
#   ('perpetual' or years) with cash_flow_life_reason; a finite life goes to the desk in Base, Bull and Bear; a perpetual
#   value of a depleting business deducts replacement capex; a commodity price deck is stated.
# Revision 13 (Phase 4 battery F5, reviewer design 2026-09-27): the desk holds Base years 3-5 at or below next-FY
#   consensus revenue growth unless the call gives guidance_deviation_reason, and prints the value on the requested path
#   beside the desk value; the contract's guidance_deviation_reason names the years 3-5 trigger.
# Revision 14 (Phase 4 E17, reviewer design 2026-09-27): the research tools change what the model is told.
#   fetch_page serves a page in 9,000-character parts, with part and find arguments, and says which part it served.
#   search_web sets aside results that share no word with the query and says how many. Every desk result states how many
#   of the 5 desk runs are used and says when the desk closes; research results after that say it is closed. A PDF
#   address is refused with a reason. RECENT COMPANY NEWS excerpts skip 'return to homepage' and 'top stories'
#   furniture.
# Revision 15 (brief_simplify_s3.md, package C, 2026-09-28, C's last step): the DEFAULTS block (5.2)
#   replaces the rules scattered through the data; SECTION 0 and SECTION 12 shrink; SECTION 1.5,
#   SECTION 3 and the SECTION 8 reference line become typed lines; money tables carry their unit
#   once (5.7); news snippets, off-topic research sub-sections and SECTION 1.6 duplicates are
#   trimmed (C1-C3); the share-count default (5.11) replaces SECTION 2's vendor count as what
#   divides by shares; a revision-15 answer run never publishes a blend (5.12). Packages A and B
#   (the desk's calling convention, the 13-field form) landed first, at PACK_REVISION 14.
# Revision 16 (brief_rev16.md, 2026-09-29, from the revision-15 before/after GPU test): a desk call that sends scenarios
#   needs exactly one Base, one Bull and one Bear, each with base_cf, explicit_growth and wacc (a two-scenario call was
#   accepted and Kelly sized two outcomes whose probabilities summed to 0.55); the desk divides by a share count in one
#   unit (a whole count and its billions value give the same value); a refusal names the share unit when the Base value
#   is under 0.01x or over 100x the reference (the consensus-implied value when present, else the price). The tool text
#   says shares_diluted is a whole share count (billions also accepted) and scenarios are exactly three. A base_iv of 0.0
#   is a value in the harness and in fiduciary_gate.contract_base (no `or` default). The pack text and TASK are unchanged
#   apart from this number; pack_facts reads every revision from 15 on as revision 15.
# Revision 17 (brief_rev17_B_valuation.md, 2026-09-30, the through-cycle valuation package): the long run is valued from the
#   company's own record (tools/throughcycle_record.py). Years 1-5 deduct working capital (nwc_intensity x the revenue change);
#   from year 6 growth is paid for at the return the record supports (terminal_ronic, facts long_run) and, for a cyclical
#   record, the margin reverts toward its median; terminal growth is the company's own revenue trend held between breakeven
#   inflation and the anchor; a one-time gain in the base year is removed (base_year_cap). The desk holds the Base's years 1-2
#   at the fiscal-year levels unless guidance_deviation_reason is given, values at the base fiscal year end rolled forward,
#   and has no exit multiple or terminal leg. DEFAULTS gains terminal_ronic, long_run, working_capital (and base_year_cap when
#   applied) and loses default_exit_multiple; the tool text and TASK change with it; sbc_dilution has one unit rule.
# Revision 18 (brief_rev18_design.md, 2026-10-01, the frozen design in production): the reference is the structure the backtest
#   tested - returns r + p x max(0, R_tc - r) with no blend, the margin moves all the way to the record's trend level, cash at
#   face (excess_cash, the after-tax interest on it out of earnings), no base-year cap - discounted at rf_eff + loading x the
#   closure premium (rs2's market-consistent premium; MRI's premium is context). The reference line carries a calibrated
#   level-anchor sentence, the TASK a Level anchor bullet, the DEFAULTS an excess_cash line (the desk adds it per share and a
#   different amount needs excess_cash_reason), and a value outside the street-target fence is printed with its flag.
# Revision 19 (brief_rev19.md, 2026-10-02, operator ruling 1: no directional call without a stated disagreement): the printed
#   levels hold a Base's years 1-2 whatever the reference's status and the desk refuses an excess_cash above the base year's cash
#   (the DEFAULTS gain base_year_cash_and_investments_b); then the price-implied value of each judgment input, the crux, the
#   reference line as context, and the TASK's item 6 (recorded in rev19/BEFORE_AFTER_r19.md).
# Revision 20 (brief_input_scope_fixes.md, 2026-10-02, operator ruling (a): the input-scope errors fixed as rules for every company):
#   noncontrolling interests (DATA 5's NONCONTROLLING INTERESTS line and its consolidated net-income column, the OWNER EARNINGS
#   line's pi, the reference line's attribution and upper-bound clauses, the DEFAULTS' display-only nci_attribution line), the
#   per-share check (DATA 2 and the reference line), the cash scope and customer money (DATA 6's cash line, the cash clause), and the
#   vendor's revenue-basis break (the years 3-5 clause); recorded in rev20/BEFORE_AFTER_r20.md.
# Revision 21 (brief_rev21.md, 2026-10-03, the primary-source fix after AT10b): the PRIMARY SOURCES section after GUIDANCE & CONSENSUS (the
#   company's own SEC filings, verbatim: its latest earnings release, the other text exhibits of that 8-K, the segment table of its latest 10-Q
#   or 10-K, its other recent 8-Ks; sec_primary.py), cited as PRIMARY P#; the GUIDANCE line says the full release is PRIMARY P1; TASK item 6 names
#   PRIMARY P# first among the sources of a crux; the TASK and both research tool descriptions say not to search or fetch what the primary
#   sources hold again (the tools return a pointer instead); recorded in rev21/BEFORE_AFTER_r21.md.
# Revision 22 (operator 2026-10-05, from an outside review of the baseline's ESEA run): DATA 6's liquidity card printed a net-debt
#   position as "Net Debt -$X", a double negative the analyst read as net cash (ESEA: debt $0.198B, cash $0.176B, memo "net cash $21M").
#   The card now prints "Net Debt $X" unsigned, matching the [Arithmetic] NET DEBT line and net_debt_b; no number changes.
# Revision 24 (PHASE_4_REV24_MUSE.md R24.2): the CONSENSUS-IMPLIED VALUE is shown only after the analyst commits (stage A without it, stage B
#   reveal with code-enforced revision guardrails); the R10 gate is off. Step 2a: desk long_run_margin (analyst), D2–D4 fixed, reveal off.
#   Step 2b (BRIEF_R24_S2b_ranges_gate.md): no default for a long-run judgment (terminal_g, terminal_ronic, long_run_margin, the years 3-5 path and
#   its price-implied run); the POPULATION RANGES section after DEFAULTS; the consensus years 1-2 as evidence (no desk hold); the three
#   classifications, normalized earnings and the input rationale in SECTION 12; the plausibility gate; the pilot arms (pilot_arm rev22 is the
#   revision-22 pack byte for byte). Step 2c (BRIEF_R24_S2c_ranges_fix.md): ranges per rebuild I1 (margin, ROIC level), 10-year revenue CAGR,
#   terminal_g by anchor, working capital on own path, rev22 control desk. Step 2d (BRIEF_R24_S2d_ronic_diagnostics.md): RONIC as stated (no floor
#   at r), TV share and reinvestment diagnostics; terminal_ronic's ROIC-five-years range annotates only (TASK item 3d).
# Revision 26 (BRIEF_R26_B_blind_pack.md, SPEC_rev26_staged_analyst.md section 5; operator-approved 2026-10-19): the pilot arm r26 is the staged analyst's pack. It runs desk schema 25.2 on the
#   revision-24 briefing (as r25_sf does) and its marker is R26_REVISION 27 for this arm only (SPEC amended: revision 27 for the staged arm, so it differs from r25_sf's 26); PACK_REVISION stays 24, so no book name re-triggers and every other arm's pack is
#   byte-identical. The text build_pack returns for it is the BLIND pack: the full pack's elements carry a source class each (r26_blind.PackLines, a side list never printed), and
#   the classes consensus, price_target, price, market_cap, multiple, price_action and reference are left out; the narrative sources (news, the catalyst brief, guidance, the
#   earnings call, the research brief) are filtered sentence by sentence by one rule (r26_blind.names_removed_class) and every dropped sentence is listed in the facts
#   (r26_blind_drops). The DEFAULTS lines are classed by their fact key; the long_run line prints without the consensus members e5, oe5 and m5. DATA 5.1 prints the
#   operating-margin history bar (op_margin_bar; the X basis for the financial family). The facts gain r26_blind_drops, op_margin_bar, consensus_corrected (for stage 3, never
#   printed), r26_leak_audit and r26_blind_source (FACTS_VERSION 12). The full text, with every class, is PackText.full_text.
PACK_REVISION = 24
# Revision 24 step 2b: the pilot arms (PHASE_4_REV24_MUSE.md step 3). `rev22` is the revision-22 briefing byte for byte (the control: its marker,
# the CONSENSUS-IMPLIED VALUE, the DEFAULTS of revision 22 and its TASK); the two `iii` arms are the revision-24 briefing and differ only by P50 in
# the POPULATION RANGES section.
PILOT_ARMS = ("rev22", "iii_p50", "iii_no_p50", "r25_b", "r25_c", "r25_sf", "r26")
REV22_REVISION = 22
# Revision 25 (Stage 0.3, SPEC_rev25_normalization_bridge.md): the pilot arms B and C run desk schema 25.1 (the normalization bridge) with the
# revision-25 briefing (PACK_REVISION 25 for these packs only, TASK_REV25, P50 omitted). Their difference (consensus withheld until pass 2) is Stage 0.6.
R25_ARMS = ("r25_b", "r25_c")
R25_REVISION = 25
DESK_SCHEMA_25 = "25.1"
# Revision 25 short form (BRIEF_SF_short_form.md, operator-approved 2026-10-18): the pilot arm r25_sf runs desk schema 25.2 on the revision-24 briefing. It is the 25.1
# bridge's path arithmetic (R_t, m_t, kappa, working capital on the declared revenue) with the two lists revenue_growth and earnings_margin as the only declarations: no
# normalization block, no C or K check, no desk-call labels and a single pass (the arm is not in R25_ARMS, so the two-pass protocol never opens). The briefing adds the
# earnings margin basis in plain words, x_margin_history (the X-basis margin per filed year, with and without one-offs) and x_margin_consensus_y1y2 to DEFAULTS, and the
# TASK asks for the two lists (TASK_SF). The pack's revision marker is R25_SF_REVISION (PACK_REVISION stays 24: no book name re-triggers); the near-term and normalized
# earnings and the three labels stay the written contract of revision 24. D2 stays off (d2_enabled unset): this arm is the analyst form only.
R25_SF_ARM = "r25_sf"
R25_SF_REVISION = 26
DESK_SCHEMA_252 = "25.2"
# Revision 26 (see the comment log above PACK_REVISION): the arm r26 and its marker.
R26_ARM = "r26"
R26_REVISION = 27


def pack_flags(pilot_arm=None, ranges_show_p50=None):
    """(arm, show_p50) of a build: the arguments, else config.json's `pilot_arm` and `ranges_show_p50` (absent: no arm, P50 not shown). An arm
    sets P50 (iii_p50 shows it, iii_no_p50 does not; rev22 prints no ranges); a contradicting ranges_show_p50 is refused, never resolved silently.
    Only a literal true shows P50."""
    arm = pilot_arm if pilot_arm is not None else CONFIG.get("pilot_arm")
    if arm is not None and arm not in PILOT_ARMS:
        raise ValueError(f"pilot_arm {arm!r} is not one of {PILOT_ARMS}")
    flag = ranges_show_p50 if ranges_show_p50 is not None else CONFIG.get("ranges_show_p50")
    flag = None if flag is None else (flag is True)
    if arm == "rev22":
        return arm, None
    if arm in ("iii_p50", "iii_no_p50", "r25_b", "r25_c", R25_SF_ARM, R26_ARM):
        want = arm == "iii_p50"
        if flag is not None and flag != want:
            raise ValueError(f"pilot_arm {arm} and ranges_show_p50 {flag} contradict each other")
        return arm, want
    return None, bool(flag)

LAST_PACK_MACRO_DEGRADED = False
LAST_PACK_FLAGS = []
# Rule 11 (verdict stamping, C1 of the amendments + P4.3 prep): consensus_valuation.main() reads
# these two after a FRESH build_pack() call and copies them onto consensus.json as
# `active_shocks_at_verdict` and `momentum_state` — the exact §1.6/§2.5 blocks this pack printed,
# same T2-whitelisting pattern as LAST_PACK_MACRO_DEGRADED above. Unknown (None) after a frozen
# `--pack-file` run, which does not call build_pack() at all.
LAST_PACK_ACTIVE_SHOCKS = []
LAST_PACK_MOMENTUM_STATE = {}
LAST_PACK_FACTS = None


class PackText(str):
    full_text: str = ""        # revision 26: the pack with every source class (the text itself is the blind pack); "" for every other arm
    macro_degraded: bool = False
    flags: list = []
    facts: dict = {}
    research_omitted: list = []

    def __new__(cls, content, macro_degraded=False, flags=None, facts=None, research_omitted=None):
        obj = str.__new__(cls, content)
        obj.macro_degraded = bool(macro_degraded)
        obj.flags = list(flags or [])
        obj.facts = dict(facts) if facts is not None else {}
        # S3 5.9 (C2): the SECTION 11 sub-section titles this build dropped as off-topic, so
        # consensus.json can record the annotation (never a silent deletion).
        obj.research_omitted = list(research_omitted or [])
        return obj

    def __add__(self, other):
        res = PackText(super().__add__(other),
                       macro_degraded=self.macro_degraded,
                       flags=self.flags,
                       facts=self.facts,
                       research_omitted=self.research_omitted)
        return res



# OWNER CASH FLOW. Defined ONCE, here, and imported by the verdict stage that audits it - two
# copies of a subtraction is the same second-authority defect the rest of this work removes.
#
# `base_cf_basis` is a FIXED list rather than free text because a free-text declaration is one
# the system cannot check. That is the Task 2 defect exactly: the analyst stated three scenario
# probabilities, `extract_scorecard`'s whitelist discarded them, and nothing could tell. `other`
# is the honest escape hatch - it declares "none of the above" and is deliberately NOT checked.
#
# `ttm_fcf` is named precisely and not just `ttm`, because the trailing record holds no SBC and
# so OCF-minus-capex and OCF are different figures ($12.438B vs $14.139B for GEV). An ambiguous
# name would have made the declaration uncheckable, and `ttm_fcf` is the reading that actually
# overstated GEV - so it is the one that most needs checking.
OWNER_CF_BASES = ("owner_earnings_default", "latest_fy", "multi_year_avg", "ttm_fcf", "other")


def owner_cf(ocf, capex, sbc):
    """OCF - capex - SBC, in whatever units the caller passed. None if any input is absent.

    OCF adds stock-based compensation back, so a figure that starts from OCF and does not
    subtract SBC overstates what the owners actually received. A NEGATIVE result is a real
    reading of a capital-hungry year, not an error, so it is not clamped.
    """
    try:
        return float(ocf) - float(capex) - float(sbc)
    except (TypeError, ValueError):
        return None


# Keys this pack depends on, by source. Checked per build against sources that are NON-EMPTY, so
# a missing FILE (a name we have no openbb record for at all) is not reported as drift - only a
# present record whose shape has changed under us. See _schema_drift().
EXPECTED_KEYS = {
    "financials/{T}.json": ("fin", ("Price", "Shares_Outstanding", "Market_Cap", "Total_Cash",
                                    "Total_Debt", "SBC_Stock_Based_Comp", "Data_Fetched_Date")),
    "openbb_{T}.json": ("ob", ("metrics", "forward_growth", "transcript_excerpt")),
    "openbb metrics block": ("met", ("pe_ratio", "price_to_book", "price_to_sales", "peg_ratio",
                                     "return_on_equity", "gross_margin", "operating_margin",
                                     "dividend_yield")),
    "enrich/{T}.json": ("en", ("analyst_target_low", "analyst_target_mean", "analyst_target_high",
                               "fifty_two_week_low", "fifty_two_week_high", "short_pct_float",
                               "shares_short", "short_ratio_days_to_cover", "institutional_pct",
                               "insider_pct")),
    "fundamentals_battery": ("bat", ("f_score", "f_score_checks_available", "accruals_ratio",
                                     "net_issuance_1y", "op_margin_latest",
                                     "op_margin_10y_median", "revenue_cagr_5y")),
}


# Every key we have REVIEWED in a fundamentals_history year row: the ones the pack prints, plus
# the two it excludes on purpose (pretax_income / tax_provision — see build_pack's docstring).
# A key outside this set is one the screener started filing that nobody here has looked at.
REVIEWED_HISTORY_KEYS = frozenset({
    "revenue", "gross_profit", "operating_income", "net_income", "ocf", "capex", "fcf", "da",
    "sga", "interest_expense", "sbc", "total_assets", "current_assets", "current_liabilities",
    "cash", "receivables", "inventory", "ppe_net", "lt_debt", "total_liabilities", "equity",
    "retained_earnings", "shares_diluted", "debt_lt_noncurrent", "debt_current",
    "short_term_borrowings_separate", "finance_lease_liability", "operating_lease_liability",
    "borrowings_total", "st_investments", "lt_investments",
    "pretax_income", "tax_provision",
    # revision 17: read by the through-cycle record (tools/throughcycle_record.py), printed as its statistics
    "goodwill", "intangibles_ex_goodwill", "amortization_intangibles",
    # revision 20 (brief_input_scope_fixes.md 1.2(b), 2.2(b), 1.4): read by tools/input_scope.py - the consolidated net income and equity,
    # the balances outside the unrestricted cash line, and the per-share check's three facts
}) | frozenset(input_scope.HISTORY_FIELDS)


def _consensus_band_or_none(t):
    """The street-target band the fence is built from (valuation_backbone._consensus_band), or None when it cannot be read: the
    one place the pack and the forward ledger take it from."""
    try:
        import valuation_backbone as _vb
        return _vb._consensus_band(t)
    except Exception:
        return None


def _reference_outside_fence(value, band):
    """Phase 4 E15: ("above" | "below", (fence_low, fence_high)) when a CONSENSUS-IMPLIED VALUE lies
    outside the harness's frozen fail-fast fence, else (None, fence or None). Same band and the same
    10% discount as consensus_valuation's fail-fast: 0.5x the discounted street low, 2x the
    discounted street high. A stale or missing band fences nothing."""
    if not band or band.get("stale") or not isinstance(value, (int, float)):
        return None, None
    lo, hi = band.get("low"), band.get("high")
    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > 0 and hi > 0):
        return None, None
    fence = (0.5 * lo / 1.10, 2.0 * hi / 1.10)
    return ("above" if value > fence[1] else "below" if value < fence[0] else None), fence


def _schema_drift(sources):
    """Return ['source: missing key, key'] for every EXPECTED key absent from a NON-EMPTY source.

    Distinguishes the two failure modes that the 934-None bug conflated:
      * key present, value null  -> a data gap. Honest. Renders as NULL. Not reported here.
      * key ABSENT entirely      -> the upstream shape changed under us. A bug. Reported loudly.
    """
    out = []
    for label, (var, keys) in EXPECTED_KEYS.items():
        d = sources.get(var)
        if not d:
            continue                      # no record for this name at all; not drift
        missing = [k for k in keys if k not in d]
        if missing:
            out.append(label + ": " + ", ".join(missing))
    return out


def _unreviewed_history_fields(h):
    """Fields the screener now files in fundamentals_history that this pack has never reviewed.

    ADDED 2026-08-24, because drift runs in BOTH directions and we were only watching one. The
    2026-08-23 extractor rebuild added SBC, the debt components and the investment lines; nothing
    was missing, so _schema_drift stayed silent, and the pack spent every run since declaring that
    data it now held did not exist. A disappearing field is a bug we shout about; an APPEARING
    field was invisible. It is the more dangerous of the two, because the pack keeps working and
    keeps making a statement that has quietly become false.

    fundamentals_history is also not covered by EXPECTED_KEYS at all — those entries watch the
    vendor and enrichment sources, not the filed series the valuation actually rests on.
    """
    seen = {k for yr in (h or {}).values() if isinstance(yr, dict) for k in yr}
    return sorted(seen - REVIEWED_HISTORY_KEYS)


def _b(v):
    """Money in billions. A FILED ZERO renders $0.000B; absence renders the one null string."""
    return f"${v/1e9:,.3f}B" if isinstance(v, (int, float)) else NULL


def _bn(v):
    """S3 5.7: a money TABLE cell (SECTIONS 4, 5, 6, 6A, 6B, 6C) — the same digits and sign as
    `_b()`, with the $/B unit carried once in the section's header bracket instead, and `NA` in
    place of the null string. A FILED ZERO renders 0.000."""
    return f"{v/1e9:,.3f}" if isinstance(v, (int, float)) else "NA"


def _v(d, k):
    """Scalar passthrough that collapses an EXPLICIT null to the null string. `.get(k, NULL)`
    does not: it returns the stored None whenever the key is present, which leaked a literal
    'None' into the pack for price_to_sales and short_pct_float on live names."""
    x = (d or {}).get(k)
    return NULL if x is None else x


def _n(v, fmt="{:,.0f}"):
    return fmt.format(v) if isinstance(v, (int, float)) else NULL


def _pct(v):
    return f"{v*100:+.1f}%" if isinstance(v, (int, float)) else NULL


def _fy_end(ttm, qs):
    """Fiscal-year end, DERIVED — fundamentals_history carries no date on any row, so a bare
    'FY2025' is ambiguous for the 53 live names that do not close in December. Prefer the TTM
    record's fy_leg_end (the actual FY close); fall back to the newest 10-Q period end."""
    d = (ttm or {}).get("fy_leg_end")
    if isinstance(d, str) and len(d) >= 10:
        return d, "fundamentals_ttm.fy_leg_end"
    if qs:
        e = qs[-1].get("end")
        if isinstance(e, str) and len(e) >= 10:
            return f"unknown; newest quarter ends {e}", "newest 10-Q period end (FY close not held)"
    return NULL, "not derivable from our data"


def _row(cells):
    return "| " + " | ".join(cells) + " |"


def _held(h, yrs, key):
    """Years in which THIS ticker holds a numeric value for `key`.

    Every "we do not hold X" line in SECTION 12 is computed through this rather than hard-coded.
    Four of those declarations went silently false when the screener's extractor was rebuilt on
    2026-08-23 and began filing SBC, the debt components and the investment lines: the pack went
    on telling every model that data we now hold for most of the book did not exist. A declaration
    stated as a literal cannot notice that it has stopped being true.
    """
    return [y for y in yrs if isinstance((h.get(str(y)) or {}).get(key), (int, float))]


_SEC_CACHE = {}


def cik(t):
    """CIK for a ticker. cik_map.json nests the tickers under a "map" key.

    THE ONLY reader of that file outside the screener's own census. It lives here rather than in
    depth_triggers because a second copy read it flat, returned None for every ticker, and silently
    disabled the 8-K and filing triggers for the entire life of the depth pipeline.
    """
    cm = rs2_data.load_json(SD / "cik_map.json") or {}
    cm = cm.get("map") if isinstance(cm.get("map"), dict) else cm
    c = cm.get(t) or cm.get(t.upper())
    return str(c).zfill(10) if c else None


def _sec_facts(t):
    """Raw SEC companyfacts for one company: ~3-4 MB, ~0.034s to parse, cached per process.

    This is the source our extractor reads. Consulting it directly is what lets the notes below
    state a fact about THIS company instead of reciting a population count someone measured once
    and typed in as a string.
    """
    if t in _SEC_CACHE:
        return _SEC_CACHE[t]
    c = cik(t)
    p = (SD / "sec_facts" / f"CIK{c}.json") if c else None
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else {}
    except Exception:
        d = {}
    _SEC_CACHE[t] = d
    return d


def _annual(us, concept):
    """{fiscal_year: value} for a concept, annual 10-K rows only."""
    out = {}
    for rows in ((us.get(concept) or {}).get("units") or {}).values():
        for r in rows:
            if r.get("fp") == "FY" and str(r.get("form", "")).startswith("10-K") and r.get("fy"):
                out[int(r["fy"])] = r["val"]
    return out


_DILUTED = "WeightedAverageNumberOfDilutedSharesOutstanding"
_BASIC = "WeightedAverageNumberOfSharesOutstandingBasic"
_UNDIFF = ("WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
           "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted")


def _share_tag_note(t, h, yrs):
    """Which share count our `wtd-avg shares` column actually carries, FOR THIS COMPANY.

    Replaces "on 18 live names the underlying tag is basic, or an undifferentiated weighted
    average" - a frozen count, measured once, about 18 companies this reader is probably not.
    Determined by matching our extracted value against the filed diluted and basic values for the
    same fiscal year, so it is a demonstration rather than an assertion.
    """
    if not yrs:
        return None
    us = (_sec_facts(t).get("facts") or {}).get("us-gaap") or {}
    if not us:
        return ("- `wtd-avg shares`: we could not verify which share count this column carries - "
                "we hold no raw filing index for this company. Treat it as UNVERIFIED.")
    dil, bas = _annual(us, _DILUTED), _annual(us, _BASIC)
    und = {}
    for c in _UNDIFF:
        und.update(_annual(us, c))
    # Check the newest year that BOTH sides hold. Our history often runs a fiscal year ahead of
    # the raw 10-K index (measured: 32 of 171 book names), and comparing against a year the index
    # has not reached yet would report "matches neither" - implying a discrepancy where there is
    # simply nothing to compare. Verifying the previous year still establishes which tag the
    # column carries, because the extractor's mapping does not change between years.
    checkable = [y for y in sorted(yrs, reverse=True)
                 if isinstance((h.get(str(y)) or {}).get("shares_diluted"), (int, float))
                 and (h.get(str(y)) or {}).get("shares_diluted")
                 and (y in dil or y in bas or y in und)]
    if not checkable:
        newest = max(list(dil) + list(bas) + list(und), default=None)
        return (f"- `wtd-avg shares`: UNVERIFIED - our newest fiscal year (FY{max(yrs)}) has no "
                f"annual 10-K row in our filing index yet"
                + (f" (newest indexed is FY{newest})" if newest else "")
                + ". Do not build a dilution rate from this column without checking the filings.")
    y = checkable[0]
    ours = h[str(y)]["shares_diluted"]
    near = lambda v: isinstance(v, (int, float)) and v and abs(ours - v) / abs(v) < 0.005
    if near(dil.get(y)):
        return (f"- `wtd-avg shares` VERIFIED DILUTED for FY{y}: our {ours:,.0f} matches the filed "
                f"diluted count exactly (basic was {bas.get(y, 0):,.0f}).")
    if near(bas.get(y)):
        return (f"- **`wtd-avg shares` IS THE BASIC COUNT for FY{y}**, not diluted: our "
                f"{ours:,.0f} matches the filed basic count. Per-share figures built on it "
                f"OVERSTATE value because dilution is excluded.")
    if near(und.get(y)):
        return (f"- **`wtd-avg shares` is an UNDIFFERENTIATED basic-and-diluted count for FY{y}** "
                f"({ours:,.0f}) - this company reports one figure for both.")
    return (f"- `wtd-avg shares` for FY{y} ({ours:,.0f}) matches NEITHER the filed diluted nor the "
            f"filed basic annual count for that year, so which count it carries is UNVERIFIED. "
            f"Do not build a dilution rate from this column.")


def _capex_note(t, h, yrs, fin):
    """Our capex against the vendor's, FOR THIS COMPANY, instead of "1.1x to 42x on 51 live
    names" - a frozen range that today measures 0.64x to 49.05x across the book, both ends
    outside it, and whose low end contradicts the claim that the vendor definition is broader."""
    if not yrs:
        return None
    ours = (h.get(str(max(yrs))) or {}).get("capex")
    ven = fin.get("Capital_Expenditure")
    if not (isinstance(ours, (int, float)) and ours and isinstance(ven, (int, float)) and ven):
        return None
    r = abs(ven) / abs(ours)
    if 0.95 <= r <= 1.05:
        return (f"- `capex` AGREES with the vendor for this company ({_b(abs(ours))} vs "
                f"{_b(abs(ven))}), so the definitional gap below does not bite here.")
    return (f"- **`capex` DISAGREES with the vendor for this company: ours {_b(abs(ours))} "
            f"(FY{max(yrs)}, property/plant/equipment purchases only) against the vendor's "
            f"{_b(abs(ven))} — {r:.2f}x.** Ours excludes capitalised software, which for "
            f"software-heavy companies is a real cash outflow, so the FCF column above is "
            f"overstated relative to the broader definition. Neither has been chosen for you.")


def _pretax_note(h, yrs):
    """Which fiscal years fail net_income + tax == pretax, FOR THIS COMPANY.

    The effective tax rate stays WITHHELD; this only says where the inputs are provably broken,
    replacing "contaminated on 38 live names" - anonymous, and measurably stale: 116 of the 171
    book names carry the domestic-only tag. Presence of that tag was tested as a gate and
    REJECTED: it misses 14 of the 57 contaminated book names and needlessly condemns 73 that pass.
    The identity is the better screen but is only NECESSARY, not sufficient - a domestic-only
    pretax paired with a domestic-only tax is internally consistent and still not consolidated -
    so it cannot license releasing a rate.
    """
    bad = []
    for y in yrs:
        r = h.get(str(y)) or {}
        ni, tx, pt = r.get("net_income"), r.get("tax_provision"), r.get("pretax_income")
        if not all(isinstance(x, (int, float)) for x in (ni, tx, pt)) or not pt:
            continue
        if abs((ni + tx) - pt) / abs(pt) > 0.05:
            bad.append(y)
    # S3 5.5: shortened to one sentence per branch; every number (5%, the broken FY list) stays.
    if not bad:
        return ("- Effective tax rate: WITHHELD; net income + tax == pre-tax income holds in "
                "every year we can test here, but holding is necessary and not sufficient - a "
                "domestic-only pre-tax paired with a domestic-only tax is self-consistent and "
                "still not the consolidated figure - so derive a rate yourself if you need one, "
                "and label it your own assumption.")
    return (f"- Effective tax rate: WITHHELD; net income + tax does not equal pre-tax income, by "
            f"more than 5%, in FY{', FY'.join(str(y) for y in bad)} (our pre-tax field admits a "
            f"US-domestic-only tag), so do not reconstruct a tax rate from those years.")


def _segment_note(t):
    """Verify the no-segment-data claim against THIS company's own filings rather than reciting
    a corpus-wide row count."""
    # S3 5.5: shortened to one sentence; the fact-row count `n` and the SECTION 11 pointer stay.
    d = _sec_facts(t)
    if not d:
        return ("- Segment revenue and margin in raw SEC XBRL: NOT MAPPED; dimensional axes are "
                "stripped from the companyfacts API. See DATA 11 for extracted segment "
                "economics and backlog.")
    n = sum(len(rows) for ns in (d.get("facts") or {}).values()
            for c in ns.values() for rows in (c.get("units") or {}).values())
    return (f"- Segment revenue and margin in raw SEC XBRL: NOT MAPPED; of the {n:,} fact rows in "
            f"raw SEC companyfacts, zero carry a dimension. See DATA 11 for extracted segment "
            f"economics and backlog.")


def _transcript_line(ob, section10_printed):
    """DATA 12's earnings-call line. When DATA 10 printed, the Q&A pointer; otherwise what
    openbb_data.py recorded as `transcript_status` (revision 17, brief C3): a source that answered with no
    transcript is a coverage fact, a source that failed is an outage, and a record from before the field
    existed says neither."""
    if section10_printed:
        return "- Analyst Q&A from earnings calls: NOT HELD; DATA 10 holds prepared remarks only."
    status = (ob or {}).get("transcript_status")
    if status == "not_covered":
        return "- Earnings-call text: NOT HELD \u2014 the source has no transcript for this company."
    failed = re.fullmatch(r"source_failed: (.+) \((\d{4}-\d{2}-\d{2})\)", status) if isinstance(status, str) else None
    if failed:
        return (f"- Earnings-call text: NOT AVAILABLE \u2014 the transcript source failed ({failed.group(1)}, "
                f"{failed.group(2)}); the call is not in this pack, so search for it if you need "
                f"management's own words.")
    return "- Earnings-call text: NOT AVAILABLE \u2014 transcript status not recorded."


def _age(rec):
    """How old the aggregator record actually is, from its own `_fetched_at` stamp.

    ADDED 2026-08-24. SECTION 8 and SECTION 9 were labelled "[Aggregator]" with no date, so a
    price target fetched a month ago read exactly like one fetched this morning. Measured across
    the 171-name book on the day this was added: median 8 days old, p90 13, max 32. Analyst
    targets, short interest and the multiples all move inside that window, and the model has no
    way to discount a number whose age it cannot see. The depth pipeline does not refresh these
    sources, so the honest fix is to state the age rather than to imply currency.
    """
    ts = (rec or {}).get("_fetched_at") if (rec or {}).get("_fetched_at") is not None else (rec or {}).get("fetched_at")
    if not isinstance(ts, str) or len(ts) < 10:
        return "fetch date NOT RECORDED - age unknown, treat as potentially stale"
    try:
        days = (datetime.now() - datetime.fromisoformat(ts[:19])).days
    except ValueError:
        return f"fetched {ts[:10]}"
    return (f"fetched {ts[:10]}, {days} day(s) ago"
            + (" - STALE, discount accordingly" if days > 14 else ""))


# P4.10 staleness suppression: past this many days, SECTION 8/9 no longer merely FLAGS an
# aggregator value as old (_age() above, at the 14-day "discount accordingly" bar) - it withholds
# the value entirely. `_age()` returns only a display string; a caller that needs to threshold
# against 45 days cannot recover the day count from it without re-parsing, hence this pair.
STALE_SUPPRESS_DAYS = 45
STALE_NULL = "not available (stale)"


def _age_days(rec):
    """Integer days since `_fetched_at` (or `fetched_at`), or None when undatable. Companion to _age()."""
    ts = (rec or {}).get("_fetched_at") if (rec or {}).get("_fetched_at") is not None else (rec or {}).get("fetched_at")
    if not isinstance(ts, str) or len(ts) < 10:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(ts[:19])).days
    except ValueError:
        return None


def _not_fresh(rec):
    """Revision 19 (10c, C9): True when a record that exists is older than STALE_SUPPRESS_DAYS OR carries no readable fetch date (an undated record's
    age cannot be shown to be within the limit, so it is never read as fresh). A missing record ({} or None) is not "not fresh": it is absent, and
    the callers say so separately."""
    if not rec:
        return False
    days = _age_days(rec)
    return days is None or days > STALE_SUPPRESS_DAYS


def _age_label(rec):
    """_age()'s string, with `- STALE (n days)` appended once the record crosses the P4.10
    suppression threshold (distinct from _age()'s own 14-day "discount accordingly" note)."""
    days = _age_days(rec)
    base = _age(rec)
    if days is not None and days > STALE_SUPPRESS_DAYS:
        return f"{base} - STALE ({days} days)"
    return base


def _sv(d, k, is_stale):
    """_v(d, k), or STALE_NULL when `is_stale` — the P4.10 value-suppression twin of _v()."""
    return STALE_NULL if is_stale else _v(d, k)


def _parse_guidance_block(text):
    """Rows from a fenced ```guidance block in a research brief: pipe-delimited lines
    `metric | period | value | source | date` (Phase 4 D4 — this pack defines the format; T4
    makes the research template emit it). [] when `text` holds no such block.

    A header row (literal column names) is skipped BY NAME, not by position, so a real metric
    that happens to be named e.g. "source revenue" is never silently dropped.
    """
    if not text:
        return []
    m = re.search(r"```guidance\s*\n(.*?)```", text, re.DOTALL)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        line = line.strip().strip("|").strip()
        if not line or line.startswith("#") or set(line) <= {"-", " ", "|"}:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 5:
            continue
        metric, period, value, source, date = parts
        if metric.lower() == "metric" and period.lower() == "period":
            continue   # header row
        if not (metric and period and value):
            continue
        rows.append({"metric": metric, "period": period, "value": value,
                     "source": source or NULL, "date": date or NULL})
    return rows


# S3 5.9 (C2): the reviewer's measured rule for off-topic SECTION 11 sub-sections, ported verbatim
# from opus_simplify\c2_rule.py (`LACK`, `CIT`, `YEAR`, `ABBR`, `sentences`, `has_figure`, `body`,
# `classify`). A sub-section is dropped only when (a) its first sentence matches `LACK` and (b)
# none of its sentences carries both a citation and a figure.
_C2_LACK = re.compile(r"(do(?:es)?\s+not\s+(?:contain|provide|include|offer|address)|no\s+(?:\*\*)?relevant\s+information"
                  r"|cannot\s+be\s+(?:extracted|derived|answered|addressed|determined|found)|lacks?\s+(?:any|specific)"
                  r"|(?:are|is)\s+unrelated)", re.I)
_C2_YEAR = re.compile(r"\b(?:19|20)\d\d\b")
_C2_CIT = re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]")
_C2_ABBR = re.compile(r"(?:\b(?:Inc|Corp|Co|Ltd|plc|Plc|S\.A|N\.V|U\.S|e\.g|i\.e|vs|No|St|Mr|Ms|Dr|approx))$")


def _c2_sentences(b):
    out, start = [], 0
    for m in re.finditer(r"[.!?](?=\s)", b):
        if _C2_ABBR.search(b[start:m.start()]):
            continue
        out.append(b[start:m.end()].strip())
        start = m.end()
    if b[start:].strip():
        out.append(b[start:].strip())
    return out


def _c2_has_figure(sent):
    s = _C2_CIT.sub(" ", sent)
    s = _C2_YEAR.sub(" ", s)
    s = re.sub(r"\b(?:Q[1-4]|H[12]|FY\d{2,4}|10-[KQ]|8-K|\d{1,2}\s+months?)\b", " ", s)
    return bool(re.search(r"\d", s))


def _c2_body(s):
    return "\n".join(s.splitlines()[1:]).split("**Sources:**")[0]


def _c2_classify(s):
    b = _c2_body(s)
    sents = [x for line in b.split("\n") for x in _c2_sentences(line) if x.strip()]
    first = sents[0] if sents else ""
    a = bool(_C2_LACK.search(first))
    fig = any(_C2_CIT.search(x) and _c2_has_figure(x) for x in sents)
    return a, fig, first


def _c2_filter_research_brief(rb_text):
    """S3 5.9: drop each off-topic SECTION 11 sub-section (`## ` heading) from `rb_text`, per
    `_c2_classify`. Returns (filtered_text, [dropped titles]); the title is the heading text with
    its engine tag (` _(engine: ...)_`) stripped."""
    if not rb_text:
        return rb_text, []
    parts = re.split(r"\n(?=## )", rb_text)
    kept, dropped_titles = [parts[0]], []
    for sub in parts[1:]:
        drop, fig, _ = _c2_classify(sub)
        if drop and not fig:
            heading = sub.splitlines()[0][3:].strip()
            title = re.sub(r"\s*_\(engine:[^)]*\)_\s*$", "", heading).strip()
            dropped_titles.append(title)
            continue
        kept.append(sub)
    return "\n".join(kept), dropped_titles


# S3 5.11: the 1.05 threshold is 2.5x the cent-rounding error of k at the precision floor (basic
# and diluted EPS are filed to the cent).
_DILUTION_APPLY_THRESHOLD = 1.05
_SHARE_DEFAULT_DEPART_TOL = 0.10
# Revision 17, brief C5: the vendor's count already within 1% of the filed diluted count is the filed count, not a
# basic count awaiting a dilution factor (the census of 291 packs found the double count on 9 names).
_SHARE_DEFAULT_FILED_TOL = 0.01

# Revision 17, brief C4: a split after the last filing. The screener's `share_count_split_suspected` reads only the
# filed series, so a split that came after the last filing (PIPR: filed FY2025 17.8M, vendor 70.7M) was invisible.
_SPLIT_KS = (2, 3, 4, 5, 8, 10, 15, 20)
_SPLIT_TOL = 0.03
# Revision 17, brief F7: the pack says "split" only when the company is in the United States and the vendor's restated
# fiscal-year EPS times the multiplier is within this of the filed diluted EPS; depositary shares (an ADS is several
# ordinary shares) show the same share-count ratio and the same EPS ratio without any split.
_SPLIT_EPS_TOL = 0.03


def _split_k(x):
    """The k of _SPLIT_KS that the ratio `x` is within 3% of, else None."""
    for k in _SPLIT_KS:
        if abs(x / k - 1) <= _SPLIT_TOL:
            return k
    return None


def _filed_diluted_series(h):
    """[(fiscal year, filed diluted share count)] ascending, for the years whose shares_diluted is a number, at the
    whole-share precision DATA 6B prints (`facts["filed_shares_diluted"]` is the last of them)."""
    out = []
    for y in sorted(int(y) for y in h if str(y).isdigit()):
        v = (h.get(str(y)) or {}).get("shares_diluted")
        if isinstance(v, (int, float)) and float("-inf") < v < float("inf"):     # DATA 6B prints NaN and inf as text
            out.append((y, float(f"{v:.0f}")))
    return out


def _split_after_last_filing(vendor_shares, h):
    """Revision 17, brief C4: a split after the last filing. ratio = the vendor's shares_outstanding / the latest filed
    diluted share count; the split is detected when the ratio (1/ratio for a reverse split) is within 3% of a k in
    {2, 3, 4, 5, 8, 10, 15, 20} AND the filed series itself shows no step of that size between its last two years
    (then the screener's own flag already says so). None when not detected. Otherwise a dict: `k`, `reverse`,
    `multiplier` (the factor that turns a filed count into today's: k, or 1/k for a reverse split), `fy` and
    `filed` (the latest filed diluted count and its fiscal year), `vendor`."""
    if not (isinstance(vendor_shares, (int, float)) and vendor_shares > 0):
        return None
    series = [(y, v) for y, v in _filed_diluted_series(h) if v > 0]
    if not series:
        return None
    fy, filed = series[-1]
    ratio = vendor_shares / filed
    reverse = ratio < 1
    k = _split_k(1 / ratio if reverse else ratio)
    if k is None:
        return None
    if len(series) >= 2:
        prev = series[-2][1]
        if _split_k(prev / filed if reverse else filed / prev) == k:
            return None
    return {"k": k, "reverse": reverse, "multiplier": (1.0 / k if reverse else float(k)), "fy": fy,
            "filed": filed, "vendor": float(vendor_shares)}


def _screener_country(t):
    """The company's country as the screener's `stocks.json` holds it, None when the ticker or the field is absent."""
    stocks = rs2_data.load_json(SD / "stocks.json") or []
    return next((row.get("country") for row in stocks if isinstance(row, dict) and row.get("symbol") == t), None)


def _split_confirmed(split, h, fin, country):
    """Revision 17, brief F7: is a split after the last filing (`_split_after_last_filing`'s dict) a split? True only
    when `country` is the United States and the vendor's DilutedEPS for the latest filed fiscal year (`fin`'s
    Annual_Income_Statement row of that year) times the split's multiplier lies within `_SPLIT_EPS_TOL` of the filed
    diluted EPS (net income / shares_diluted of `h`'s row of that year). False when either is unavailable."""
    if country != "United States":
        return False
    row = h.get(str(split["fy"])) or {}
    ni, sh = row.get("net_income"), row.get("shares_diluted")
    if not (isinstance(ni, (int, float)) and isinstance(sh, (int, float)) and sh > 0 and ni != 0):
        return False
    vendor = next((r.get("DilutedEPS") for r in (fin.get("Annual_Income_Statement") or [])
                   if isinstance(r, dict) and str(r.get("Date"))[:4] == str(split["fy"])), None)
    if not isinstance(vendor, (int, float)):
        return False
    return abs(vendor * split["multiplier"] / (ni / sh) - 1) <= _SPLIT_EPS_TOL


def _split_sentence(split):
    """DATA 7's account of a split after the last filing (`split` with its `confirmed` flag), or None for none."""
    if not split:
        return None
    span = f"filed FY{split['fy']} {split['filed'] / 1e6:.1f}M -> vendor {split['vendor'] / 1e6:.1f}M"
    if split["confirmed"]:
        what = f"a {split['k']}-for-1 split" if not split["reverse"] else f"a 1-for-{split['k']} reverse split"
        return (f"{what} ({span}; the vendor's restated FY{split['fy']} EPS agrees); filed per-share figures in "
                f"DATA 5 and 6 are pre-split.")
    of = f"{split['k']}x" if not split["reverse"] else f"1/{split['k']} of"
    return (f"the vendor's share count is {of} the filed diluted count ({span}): a split after the last filing, or a "
            f"different share unit such as depositary shares; the filed per-share figures in DATA 5 and 6 are on "
            f"the filed unit.")


def _x_over_owner_earnings(ni, oe, fy_row, untagged):
    """Revision 17, brief C7: the base window's earnings before acquired-intangible amortization over its owner earnings, for
    a desk with no consensus reference. X = the window's net income + the base fiscal year's amortization x (1 - tax
    rate) (`throughcycle_record.earnings_detail` on that year's row with the window's net income). None unless the base
    year's amortization is known (a null in a series the filer tags is a gap: the desk then scales by net income) and
    both X and owner earnings are positive."""
    x, gap = throughcycle_record.earnings_detail(dict(fy_row or {}, net_income=ni), untagged)
    return x / oe if (x is not None and not gap and x > 0 and oe > 0) else None


# P-2: the latest filed diluted count and the vendor's count on one name differ by a factor of 100 or more (amendment A1's
# rule). The screener's `shares_cover` (the latest filing's cover-page count, from the SEC) says which of the two is wrong;
# "agree" is within 50%, the same test the reviewer's scan used.
_SHARES_GAP = 100.0
_SHARES_COVER_AGREE = 0.5


def _positive_count(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and 0 < x < float("inf")


def _shares_scale_gap(filed, vendor):
    """vendor / filed when the two counts differ by a factor of 100 or more in either direction, else None."""
    if not (_positive_count(filed) and _positive_count(vendor)):
        return None
    r = vendor / filed
    return r if (r >= _SHARES_GAP or r <= 1 / _SHARES_GAP) else None


def _counts_agree(a, b):
    return 1 / (1 + _SHARES_COVER_AGREE) <= a / b <= 1 + _SHARES_COVER_AGREE


def _shares_gap_state(filed, vendor, cover, is_10k_filer):
    """P-2: None unless `filed` (the latest filed diluted count on today's share basis) and `vendor` differ by 100x or
    more. Else a dict: `ratio` (vendor / filed), `cover` and `cover_date` (the screener's `shares_cover` record, None
    when absent), `agrees` ("filed" | "vendor" | "both" | "neither" | None when there is no cover count),
    `vendor_unusable` (the cover count agrees with the filed count only, and the company files 10-Ks: the vendor's count
    is proven wrong and the share default is withheld) and `depositary` (the same, for a foreign filer: the vendor's
    count is kept and may be a depositary-share count). `is_10k_filer` is called only when it decides."""
    ratio = _shares_scale_gap(filed, vendor)
    if ratio is None:
        return None
    cv = cover.get("val") if isinstance(cover, dict) else None
    cv = float(cv) if _positive_count(cv) else None
    if cv is None:
        agrees = None
    else:
        a_f, a_v = _counts_agree(cv, filed), _counts_agree(cv, vendor)
        agrees = "both" if (a_f and a_v) else "filed" if a_f else "vendor" if a_v else "neither"
    only_filed = agrees == "filed"
    ten_k = bool(is_10k_filer()) if only_filed else False
    return {"ratio": ratio, "cover": cv, "cover_date": (cover or {}).get("date") if cv is not None else None,
            "agrees": agrees, "vendor_unusable": only_filed and ten_k, "depositary": only_filed and not ten_k}


def _marker_for(hist_doc, t):
    """Brief A's provenance marker of company `t` in the history document: the fields the extractor found this filer never tags in
    any held year, as a list - [] is a marker with nothing untagged - or None when the history holds no marker for `t` at all
    (revision 18, amendment 2: the extractor never processed the name; this is not the same as []). The record reads a missing
    goodwill, intangibles or amortization series as "none held" only where the marker says so."""
    m = ((hist_doc.get("provenance") or {}).get("untagged_fields") or {}).get(t)
    return None if m is None else list(m)


class DataRoot:
    """Revision 18 (brief section 2, step 1): the screener data a company's reference needs, each file read once and kept, so
    the closure (a thousand names, many trial rates) and the ledger do not re-read the 47 MB history. `sd` defaults to the
    module's SD at call time (a test's redirect reaches it). Read-only; every read goes through `rs2_data.load_json`."""

    def __init__(self, sd=None):
        self.sd = Path(sd) if sd is not None else Path(SD)
        self._hist = self._ttm = self._cik = None
        self._fin = {}

    def hist_doc(self):
        if self._hist is None:
            self._hist = rs2_data.load_json(self.sd / "fundamentals_history.json") or {}
        return self._hist

    def history(self, t):
        return self.hist_doc().get("tickers", {}).get(t) or {}

    def untagged(self, t):
        """The marker list (possibly []), or None when the history has no marker for `t` (amendment 2: not the same as [])."""
        return _marker_for(self.hist_doc(), t)

    def shares_cover(self, t):
        return (self.hist_doc().get("shares_cover") or {}).get(t)

    def ttm(self, t):
        if self._ttm is None:
            self._ttm = (rs2_data.load_json(self.sd / "fundamentals_ttm.json") or {}).get("tickers", {})
        return self._ttm.get(t) or {}

    def fin(self, t):
        if t not in self._fin:
            self._fin[t] = rs2_data.load_json(self.sd / "financials" / f"{t}.json") or {}
        return self._fin[t]

    def cik_map(self):
        if self._cik is None:
            self._cik = (rs2_data.load_json(self.sd / "cik_map.json") or {}).get("map") or {}
        return self._cik

    def financial_tickers(self):
        return sorted(p.stem.upper() for p in (self.sd / "financials").glob("*.json"))


def _shares_alert_text(g, filed, fy, vendor):
    """P-2: SECTION 2's SHARES ALERT, from `_shares_gap_state`'s dict. Annotates; the filed cells are untouched."""
    r = g["ratio"]
    rel = f"{r:,.0f} times" if r >= 1 else f"1/{1 / r:,.0f} of"
    text = (f"**SHARES ALERT - the latest filed diluted share count ({filed:,.0f}, FY{fy}, split-adjusted) and the "
            f"vendor's count ({vendor:,.0f}) differ by a factor of 100 or more: the vendor's count is {rel} the filed "
            f"count.**")
    if g["cover"] is None:
        text += " No cover-page count is held for this company, so which of the two is wrong is not established."
        return text
    when = f", {g['cover_date']}" if g["cover_date"] else ""
    agree = {"filed": "agrees with the filed count", "vendor": "agrees with the vendor's count",
             "both": "agrees with both", "neither": "agrees with neither"}[g["agrees"]]
    text += f" The latest filing's cover-page count ({g['cover']:,.0f}{when}) {agree}."
    if g["agrees"] == "vendor":
        text += (" The filed count is the one that is off-scale: DATA 6B's weighted-average share column, and any "
                 "per-share figure built from it, carries that factor.")
    elif g["vendor_unusable"]:
        text += (" The vendor's count is not usable: this pack gives no share-count default, and a valuation call must "
                 "pass shares_diluted with a shares_reason.")
    elif g["depositary"]:
        text += " The vendor count may be a depositary-share count."
    return text


def _peer_shares_gap(vendor, years):
    """P-2: the ratio (vendor / latest filed diluted count, split-adjusted as for the target) of a peer whose two counts
    differ by 100x or more, else None. `years` is the peer's fundamentals_history ticker dict."""
    series = _filed_diluted_series(years) if isinstance(years, dict) else []
    if not series:
        return None
    split = _split_after_last_filing(vendor, years)
    return _shares_scale_gap(series[-1][1] * (split["multiplier"] if split else 1.0), vendor)


def _share_default(fin, V, point_in_time=False, filed_diluted=None, vendor_unusable=False):
    """S3 5.11: the share-count default, added after the E17 L2 finding on EZPW. SECTION 2's
    vendor count `V` is the BASIC count; this multiplies it by the company's own dilution factor
    (basic / diluted EPS) when the dilution is large enough to matter, so the default pairs with
    the pack's after-interest flows the way a filed diluted weighted-average count (SECTION 6B)
    cannot (it double-counts a convertible's interest add-back).

    Inputs come from the vendor's income statements in `financials/<T>.json` (`fin`, already
    loaded by `build_pack`). Returns (shares_default, shares_dilution_factor, period, warning),
    where `period` is `{"B", "k", "basic_eps", "diluted_eps", "label"}` or None (the caller reads
    `period["label"]` for the `shares_dilution_period` fact):
      - `vendor_unusable` (P-2: the cover count proves V wrong): (None, None, None, a warning), as for no count.
      - V missing, or filed as 0 or negative (a share count of exactly 0.0 is a real filed value,
        never treated as "missing" per the 0.0 rule, but it is not a usable basic count either):
        (None, None, None, a warning naming which case it is) — the desk refuses as today (no
        default).
      - the latest quarter, else the latest fiscal year, is not profitable with |basic EPS| >=
        0.50 (a loss makes diluted EPS equal basic by the anti-dilution rule): (V, None, None,
        None) — not measurable, SECTION 2 notes it.
      - |V / B - 1| > 0.10 (B = NetIncome / BasicEPS, the basic count filed EPS implies): (V,
        k, period, a warning) — SECTION 2's count cannot be trusted as the basic count (share
        classes, ADS units or a stale vendor count), so no dilution is applied on top of it.
      - k >= 1.05 and `filed_diluted` (the latest filed diluted count, split-adjusted by
        `_split_after_last_filing`) is available with V within 1% of it (revision 17, brief C5): (V, k,
        period with "matches_filed" True, None) — DATA 2's count already IS the filed diluted count, so the
        factor is not applied a second time (SECTION 2 says so in one clause; no shares_warning).
      - otherwise: (round(V * k) if k >= 1.05 else V, k, period, None).
    """
    if not (isinstance(V, (int, float)) and V > 0):
        # 0.0 is a value, not an absence: a filed zero count gets its own message, never the
        # "not available" one V is None gets.
        if V is None:
            warning = ("DATA 2's count is not available: the desk has no share-count default "
                      "and refuses a call without shares_diluted.")
        else:
            warning = (f"DATA 2's count is filed as {V:,.0f}: the desk has no share-count "
                      f"default from a count that is not positive.")
        return None, None, None, warning

    if vendor_unusable:
        # P-2: the cover count agrees with the filed count and the vendor's is 100x or more away from both (SECTION 2's
        # SHARES ALERT says so): a count proven wrong is no basis for a default, so the desk refuses as for no count.
        return None, None, None, ("DATA 2's count is proven wrong (see the SHARES ALERT): the desk has no share-count "
                                  "default and refuses a call without shares_diluted.")

    if point_in_time:
        # S3 C review (2026-09-28): a point-in-time pack's SECTION 2 count is already the filed
        # diluted average of the latest allowed fiscal year, and `fin`'s income statements are
        # today's vendor snapshot, whose latest period can postdate asof (measured: GEV as of
        # 2026-03-31 printed "quarter ended 2026-06-30"). No factor is measured or applied.
        return V, None, None, None

    period = None
    for key, is_quarter in (("Quarterly_Income_Statement", True), ("Annual_Income_Statement", False)):
        rows = fin.get(key) or []
        if not rows:
            continue
        row = rows[0]
        ni, basic, diluted = row.get("NetIncome"), row.get("BasicEPS"), row.get("DilutedEPS")
        if (isinstance(ni, (int, float)) and ni > 0
                and isinstance(basic, (int, float)) and abs(basic) >= 0.50
                and isinstance(diluted, (int, float)) and diluted != 0):
            date = row.get("Date")
            label = f"quarter ended {date}" if is_quarter else f"fiscal year {str(date)[:4]}"
            k_full = basic / diluted
            # S1's rule: the shares_dilution_factor FACT is the same formatted substring the
            # print site prints (4 decimals), like every other quantized fact (coe_anchor,
            # terminal_g_default, ...). The default itself (below) uses the full-precision ratio,
            # not this display rounding.
            period = {"B": ni / basic, "k_full": k_full, "k": float(f"{k_full:.4f}"),
                      "basic_eps": basic, "diluted_eps": diluted, "label": label}
            break

    if period is None:
        return V, None, None, None

    B, k_full, k = period["B"], period["k_full"], period["k"]
    if abs(V / B - 1) > _SHARE_DEFAULT_DEPART_TOL:
        gap_pct = abs(V / B - 1) * 100.0
        warning = (f"DATA 2's count is {gap_pct:.0f}% from the basic count implied by filed "
                  f"EPS: share classes, ADS units or a stale vendor count")
        return V, k, period, warning

    if (k_full >= _DILUTION_APPLY_THRESHOLD and isinstance(filed_diluted, (int, float)) and filed_diluted > 0
            and abs(V / filed_diluted - 1) <= _SHARE_DEFAULT_FILED_TOL):
        period["matches_filed"] = True
        return float(V), k, period, None

    default = round(V * k_full) if k_full >= _DILUTION_APPLY_THRESHOLD else V
    return float(default), k, period, None


def _share_default_lines(V, default, k, period, warning, point_in_time=False):
    """S3 5.11: SECTION 2's two new lines (the dilution line, then the default line), from
    `_share_default`'s result. `[]` when V is missing or not usable (filed as 0 or negative,
    `_share_default`'s own validity rule) — `default` is None in both cases, and there is nothing
    to report: SECTION 2's own "ZERO on file" note already declares a zero count's problem."""
    if V is None or default is None:
        return []
    if k is not None:
        # `default` is either V*k (rounded) or V, printed with the same "not applied" caveat
        # when a warning fired.
        dil_line = (f"- Shares dilution factor: {k:.4f} = basic EPS {period['basic_eps']:g} / "
                    f"diluted EPS {period['diluted_eps']:g} ({period['label']}); applied to the "
                    f"default at 1.05 or above (convertibles, options or warrants)"
                    + (f" — not applied: {warning}" if warning else
                       " — not applied: DATA 2's count already matches the filed diluted count"
                       if period.get("matches_filed") else ""))
    elif point_in_time:
        dil_line = (f"- Shares dilution factor: {ASOF_NULL} — the vendor's EPS statements are a "
                    f"same-day snapshot, and DATA 2's count is already the filed diluted average "
                    f"of the latest allowed fiscal year")
    elif period is None and warning is None:
        dil_line = ("- Shares dilution factor: not available — no profitable period (net "
                    "income above 0, |basic EPS| >= 0.50) in the latest quarter or fiscal year; "
                    "dilution could not be measured for this company")
    else:
        dil_line = None
    def_line = (f"- Shares default: {default:,.0f}   [the desk's shares_diluted unless you pass "
               f"another count with shares_reason]" + (f" — {warning}" if warning else ""))
    return [x for x in (dil_line, def_line) if x is not None]


def _decl(label, h, yrs, keys, held_phrase, gap_phrase):
    """One SECTION 12 line (S3 5.5), decided by what THIS ticker's record actually contains.

    Emits HELD (with the years covered) or NOT MAPPED, so the declaration cannot drift out of
    agreement with the tables above it the way the hard-coded versions did.
    """
    years = sorted({y for k in keys for y in _held(h, yrs, k)})
    if not years:
        return f"- {label}: NOT MAPPED for this company; {gap_phrase}"
    span = f"{years[0]}" if len(years) == 1 else f"{years[0]}-{years[-1]}"
    return f"- {label}: HELD, {len(years)} year(s) ({span}), {held_phrase}"


# ── SECTION 1.6 WORLD NEWS block (P4 D10) — shared by the live and point-in-time branches ───
# Formats a world_news.digest() result (or None). Never invents a headline: an unreadable/empty
# digest prints a stated reason, exactly like every other SECTION 1.6 line.
def _world_news_lines(wn, asof_date):
    if asof_date is not None:
        if not wn or not wn.get("top"):
            # No date is printed here: the feed's first partition is AFTER asof on every trial
            # date to date, and a point-in-time pack must carry no date later than asof — even
            # metadata tells the model that time has passed (2026-09-24 leakage scan).
            reason = "the news history does not reach back to this date"
            return [f"- WORLD NEWS: {ASOF_NULL} — {reason}"]
    elif not wn or not wn.get("top"):
        reason = (f"no qualifying headlines in the last {wn['window_days']} days" if wn else
                 "MRI news feed unavailable this run (no live digest and no usable cache)")
        return [f"- WORLD NEWS: {NULL} — {reason}"]

    stale_days = wn.get("stale_days")
    prefix = (f"STALE ({int(stale_days)} days) — "
             if isinstance(stale_days, (int, float)) and stale_days > 3 else "")
    lines = [f"- {prefix}WORLD NEWS, last {wn['window_days']} days — one-line AI summaries of "
            f"dated headlines from the MRI news feed (context, not verified facts; check anything "
            f"you rely on). {wn['n_considered']} items considered, newest classified "
            f"{wn.get('newest_classified') or NULL}:"]
    for row in wn["top"]:
        lines.append(f"  - {row['date']} | {row['source']} | {row['summary']}  "
                     f"(severity {row['severity']:.2f})")
    lines.append("- Structural themes in the news (same feed):")
    for row in wn["themes"]:
        lines.append(f"  - {row['date']} | {row['secular_theme']} | {row['summary']}")
    return lines


# ── Point-in-time (as-of) pack helpers — Phase 4 E4.3, time-travel trial ────────────────────
# A conservative filing lag applied to every fundamentals cutoff below: the period end date
# itself is not enough, because a period that ended just before `asof` may not have been FILED
# yet. 45 days matches the anchor/regime freshness gates already used elsewhere in this pack
# (CONFIG["regime_max_age_days"], CONFIG["anchor_max_age_days"]) and covers the SEC's own filing
# deadlines for every filer size (10-K: 60/75/90 days; 10-Q: 40/45 days) except the slowest
# non-accelerated 10-K filers, which is the honest, stated trade-off of picking ONE conservative
# number instead of a per-company filer-status lookup this pack does not have.
POINT_IN_TIME_FILING_LAG_DAYS = 45
ASOF_NULL = "not available (point-in-time)"


def _parse_asof(asof):
    """A `datetime.date` for `asof`, which may already be one, or a "YYYY-MM-DD" string."""
    if isinstance(asof, datetime):
        return asof.date()
    from datetime import date as _date
    if isinstance(asof, _date):
        return asof
    return datetime.strptime(str(asof)[:10], "%Y-%m-%d").date()


def _fye_month_day(t, with_source=False, ttm=None, fin=None):
    """(month, day) of this company's fiscal year end, from TODAY's `fundamentals_ttm.json`.

    This is the ONLY use a point-in-time pack makes of a same-day snapshot file: not the VALUE
    of anything filed, only the recurring calendar pattern of WHEN this company's fiscal year
    closes (e.g. NVDA closes in late January, not December) — a structural fact about the
    company's reporting calendar that is, for essentially every filer, unchanged year over year
    and so carries no look-ahead about what happened in the period being restricted. With no TTM
    record, the month and day of the vendor's newest dated annual statement (review B3: WSE and TOP
    close on 31 March; the old calendar default dropped WSE's reference as "after today" and dated
    RNW's year silently wrong). Only then a calendar (Dec 31) year end, reported as source "default"
    so the E18 reference can refuse it. `with_source=True` returns (month, day, source).
    """
    from datetime import date as _date
    # revision 18: the caller may hand over the records it already holds (the reference's inputs read each file once)
    rec = ttm if ttm is not None else (rs2_data.load_json(SD / "fundamentals_ttm.json") or {}).get("tickers", {}).get(t) or {}
    fy_end = rec.get("fy_leg_end")
    out = None
    if isinstance(fy_end, str) and len(fy_end) >= 10:
        try:
            d = _date.fromisoformat(fy_end[:10])
            out = (d.month, d.day, "ttm")
        except ValueError:
            pass
    if out is None:
        dates = _vendor_annual_dates(fin if fin is not None else (rs2_data.load_json(SD / "financials" / f"{t}.json") or {}))
        out = (dates[0].month, dates[0].day, "vendor") if dates else (12, 31, "default")
    return out if with_source else out[:2]


_fye_month_day.takes_records = True


def _vendor_annual_dates(fin):
    """The vendor's annual statement dates, newest first; [] when it holds none."""
    from datetime import date as _date
    out = []
    for r in fin.get("Annual_Income_Statement") or []:
        try:
            out.append(_date.fromisoformat(str(r.get("Date"))[:10]))
        except ValueError:
            pass
    return sorted(out, reverse=True)


def _vendor_fy_end_for(fin, net_income, year, prev_net_income=None):
    """Review B3/R4: (date, conflict). `date` is the vendor's annual statement dated in `year` whose
    net income matches our filed FY`year`'s within the vintage tolerance, which confirms the label
    year. `conflict` is the date of a statement from another year when the SAME shift matches in
    two consecutive years (FY`year` and FY`year`-1) and no same-year statement matches: only then
    is our label in doubt. One coincidental match (CX: our consolidated FY2024 net income, $960M,
    equals the vendor's attributable FY2025 figure) leaves the label standing, and the age rules
    decide. (None, None) otherwise."""
    from datetime import date as _date

    def _matches(ni):
        out = []
        if not isinstance(ni, (int, float)) or ni == 0:
            return out
        for r in fin.get("Annual_Income_Statement") or []:
            v = r.get("NetIncome")
            try:
                d = _date.fromisoformat(str(r.get("Date"))[:10])
            except ValueError:
                continue
            if isinstance(v, (int, float)) and abs(v / ni - 1) <= consensus_reference.VINTAGE_TOL:
                out.append(d)
        return out
    now = _matches(net_income)
    same = next((d for d in now if d.year == year), None)
    if same:
        return same, None
    before = {d.year for d in _matches(prev_net_income)}
    shifted = next((d for d in now if d.year != year and (d.year - 1) in before), None)
    return None, shifted


def _vendor_capex_usable(fin, fy_end):
    """Review B1: (usable, why not). The vendor's latest-annual capex may stand in for a filed one
    only when the screener's FX block shows no unconverted currency on this vendor file and the
    vendor's latest annual statement is dated at our latest fiscal year end within 7 days (RNW
    subtracted 94.0B of rupee capex from dollar net income)."""
    fx = fin.get("FX") or {}
    if fx and not fx.get("converted") and fx.get("flag"):
        return False, (f"the vendor's statements are in {fx.get('statement_currency')}, not converted "
                       f"({fx.get('flag')})")
    dates = _vendor_annual_dates(fin)
    if not dates or fy_end is None or abs((dates[0] - fy_end).days) > 7:
        return False, "the vendor's latest annual statement is not dated at our latest fiscal year end"
    return True, None


def _fy_end_date_for(year, month, day):
    """`date(year, month, day)`, clamped to the last real day of `month` (handles Feb 29 in a
    non-leap fiscal-label year, and any other month/day combination that cannot exist)."""
    import calendar
    from datetime import date as _date
    last_day = calendar.monthrange(year, month)[1]
    return _date(year, month, min(day, last_day))


def _last_allowed_fiscal_year(cutoff_date, month, day):
    """The greatest fiscal-year label Y such that this company's FY-end date for label Y
    (approximated as `date(Y, month, day)`, from `_fye_month_day`) falls at or before
    `cutoff_date`. `fundamentals_history.json` keys its rows by this same label convention
    (verified against `fy_leg_end`: NVDA's FY2026 row is keyed "2026" for a period ending
    2026-01-25) — this function inverts that same convention rather than assuming a calendar
    year end for every company (Dec-31 alone would incorrectly exclude an already-filed
    January-fiscal-year-end company like NVDA from its own most recent completed year).
    """
    y = cutoff_date.year + 1
    while _fy_end_date_for(y, month, day) > cutoff_date:
        y -= 1
    return y


def _asof_price_lookup(t, asof_date, lookback_days=400):
    """{'price', 'asof' (the actual trading-day date used), 'series' ({iso_date: close}, every
    close STRICTLY on or before `asof_date` — the single filter point that makes every SCR-10
    computation below provably unable to read a future close)}, or None when no close is found
    within `lookback_days` before `asof_date` (network failure, an unlisted/delisted ticker, or
    a `lookback_days` window too short for this ticker's history).

    Reuses `tools/grade_depth_verdicts.py`'s own price fetch/cache machinery verbatim (same
    `fetch_history`/`close_on_or_before` this pipeline's grader already uses to price a verdict's
    forward return) rather than a second yfinance client — the brief's "grader's price fetch/
    cache approach". A network fetch of HISTORICAL prices is explicitly permitted at pack build
    time (point-in-time restriction is about not reading data dated after `asof`, not about
    avoiding the network); this function never fetches or reads anything dated after `asof`.
    """
    try:
        import grade_depth_verdicts as gdv
    except Exception:
        return None
    from datetime import timedelta as _td
    start = (asof_date - _td(days=lookback_days)).isoformat()
    cache = {}
    try:
        gdv.fetch_history([t], start, cache)
    except Exception:
        return None
    asof_iso = asof_date.isoformat()
    # The one filter point: every date after `asof_date` is discarded here, before any SCR-10
    # figure is computed from this series, regardless of how far `fetch_history` itself reached.
    series = {d: c for d, c in (cache.get(t) or {}).items() if d <= asof_iso}
    if not series:
        return None
    close_date, close = gdv.close_on_or_before(
        {t: series}, t, asof_iso, window=10)
    if close is None:
        return None
    return {"price": close, "asof": close_date, "series": series}


def _series_close_on_or_before(series, target_iso, window=10):
    """`gdv.close_on_or_before`'s exact rule, applied to an already-fetched {date: close} dict
    directly (no second network round-trip): the close on the last trading day on/before
    `target_iso`, within `window` calendar days. (None, None) when nothing qualifies."""
    from datetime import date as _date, timedelta as _td
    t0 = _date.fromisoformat(target_iso)
    for back in range(0, window + 1):
        key = (t0 - _td(days=back)).isoformat()
        if key in series:
            return key, series[key]
    return None, None


def _scr10_from_series(series, asof_iso):
    """SECTION 2.5's price-fact fields, recomputed directly from historical closes ending at
    `asof_iso` (PHASE_4_PACK_SPEC.md D10 / the E4.3 brief: "52-week range and SCR-10-style price
    facts ... recomputed from monthly/daily closes ending at asof"), never from
    `factor_scores.json` (a same-day snapshot with no history). Every field is None when the
    reference close it needs is not in `series` (a lookback window too short, or too new a
    listing) — never approximated.

    `mom_12_1`: the standard 12-1 momentum window (12 months back to 1 month back, skipping the
    most recent month) — NOT `mom_6m`/`mom_1m`'s own simple "today vs N months back".
    """
    close_asof_date, close_asof = _series_close_on_or_before(series, asof_iso)
    if close_asof is None:
        return {}
    from datetime import date as _date, timedelta as _td

    def _months_back(months):
        d = _date.fromisoformat(asof_iso)
        # Calendar months back via day-count approximation (30.44 days/mo average) — consistent
        # with how mom_6m/mom_1m are described ("N-month return"), not a banker's exact
        # month-boundary rule this pack has no other use for.
        return (d - _td(days=round(months * 30.4375))).isoformat()

    def _ret(months):
        _, base = _series_close_on_or_before(series, _months_back(months))
        return (close_asof / base - 1.0) if base else None

    _, close_1m = _series_close_on_or_before(series, _months_back(1))
    _, close_12m = _series_close_on_or_before(series, _months_back(12))
    mom_12_1 = (close_1m / close_12m - 1.0) if (close_1m and close_12m) else None

    window_start = (_date.fromisoformat(asof_iso) - _td(days=365)).isoformat()
    high_52w = max((c for d, c in series.items() if window_start <= d <= asof_iso), default=None)
    high_52w_dist = (close_asof / high_52w - 1.0) if high_52w else None

    return {
        "mom_12_1": mom_12_1, "mom_6m": _ret(6), "mom_1m": _ret(1),
        "high_52w_distance": high_52w_dist, "high_52w_basis": "daily (recomputed, point-in-time)",
        "price_asof": close_asof_date,
    }


def _span_n(years):
    """[first, last, n] of a list of fiscal years, or None when there are none (the long_run fact's
    "basis years": the record's span and how many years it used)."""
    return [min(years), max(years), len(years)] if years else None


_PERSISTENCE_MEMO = {}


def _base_rate_median(h, sd, last_allowed_fy):
    """The growth base-rate median the reference fades toward (revision 18: extracted from build_pack, one copy): (size_label,
    br_table, g_lbl, g_stats, median_5y), median_5y a fraction or None - the conditional median for the growth just delivered,
    else the size-bucket 5-year median."""
    yrs = sorted([int(y) for y in h if str(y).isdigit()])
    latest_rev = h.get(str(max(yrs)), {}).get("revenue") if yrs else None
    size_label, br_table = base_rates.base_rate_table(latest_rev, sd=sd, max_fiscal_year=last_allowed_fy)
    g0 = None
    g_stats = None
    g_lbl = None
    if yrs:
        y_last = max(yrs)
        if (y_last - 1) in yrs:
            rlast = h.get(str(y_last), {}).get("revenue")
            rprev = h.get(str(y_last - 1), {}).get("revenue")
            if isinstance(rlast, (int, float)) and isinstance(rprev, (int, float)) and rprev > 0:
                g0 = rlast / rprev - 1
    if g0 is not None:
        # the persistence table depends on the corpus and the delivered-growth BUCKET only, and measuring it scans the corpus: one
        # measurement per (bucket, corpus file, as-of year) serves a thousand names (the closure) as well as one pack
        _fn = growth_persistence.persistence_for_growth
        try:
            _stamp = Path(sd).joinpath("fundamentals_history.json").stat().st_mtime_ns
        except OSError:
            _stamp = None
        _key = (growth_persistence.bucket_for_growth(g0), str(sd), _stamp, last_allowed_fy, id(_fn))
        if _key not in _PERSISTENCE_MEMO:
            _PERSISTENCE_MEMO[_key] = _fn(g0, sd=sd, max_fiscal_year=last_allowed_fy)
        g_lbl, g_stats = _PERSISTENCE_MEMO[_key]
    _med = (g_stats or {}).get("median") if g_stats else None
    if _med is None:
        _med = ((br_table or {}).get(5) or {}).get("p50")
    return size_label, br_table, g_lbl, g_stats, (_med / 100.0 if isinstance(_med, (int, float)) else None)


def _record_for(t, h, hist_doc, coe, ga, be, rev_g2, median_5y, printed=True):
    """Revision 17 brief B sections 1 and 3 (revision 18: extracted from build_pack, one copy): the company's own record at
    r = `coe` and the terminal-growth default built on its revenue trend: (record, default, basis, reason). `printed`: the
    default is quantized to the two decimals the pack prints, so the reference, the printed default and the desk's default are
    one number; the closure solves on unquantized values."""
    yrs = sorted([int(y) for y in h if str(y).isdigit()])
    _prov = hist_doc.get("provenance") or {}
    _dc_runs = ((_prov.get("runs") or {}).get(t) or {}).get("debt_current")
    _dc_tags = throughcycle_record.resolve_run_tags(_dc_runs, _prov.get("_tags"), yrs)
    untagged = _marker_for(hist_doc, t) or []       # a missing marker is stated by the callers (`reference_inputs`, the pack); the record reads it as none
    # revision 20 (brief_input_scope_fixes.md 1.3(b)): the record reads consolidated net income and equity, so its returns, margins, cycle
    # and working capital are ratios on one basis; `scope_mixed_years` are the window years that fall back to the company's own figures
    view, mixed = input_scope.record_view_for(h, hist_doc, t, max(yrs) if yrs else None)
    rec = throughcycle_record.analyse(view, coe, untagged_fields=untagged, base_year=max(yrs) if yrs else None,
                                      debt_current_tags=_dc_tags)
    rec["scope_mixed_years"] = mixed
    val, basis, reason = consensus_reference.terminal_growth_default(ga, be, rec["g_rev"], rev_g2, median_5y)
    if val is not None and printed:
        val = float(f"{val * 100:.2f}") / 100.0
    return rec, val, basis, reason


def _cash_term_for(fy_rec, sector, fye_src, fye_conflict, fy_end_dt):
    """Revision 18 (brief 1.3), extracted from build_pack: the cash term of the base fiscal year. The mean 3-month bill rate
    over the 12 months to that year's end prices the interest the cash earns; a fiscal year end that is only a default or
    unconfirmed has no such window."""
    if sector in consensus_reference.FINANCIAL_SECTORS:
        return consensus_reference.cash_term(fy_rec, None, sector)
    if fye_src == "default" or fye_conflict is not None or fy_end_dt is None:
        return {"applies": False, "financial": False, "cash": None, "interest": 0.0,
                "stamps": ["cash_term_not_available_fiscal_year_end_unknown"]}
    import calendar as _cal
    _y0 = fy_end_dt.year - 1
    _d0 = min(fy_end_dt.day, _cal.monthrange(_y0, fy_end_dt.month)[1])
    _bill, _bill_src = rs2_data.bill_rate_mean(fy_end_dt.replace(year=_y0, day=_d0), fy_end_dt)
    return consensus_reference.cash_term(fy_rec, _bill, sector)


def _fiscal_year_base(t, h, fin, ttm, f, ttm_stale, estimates, untagged, today):
    """The E18 base of the CONSENSUS-IMPLIED VALUE (revision 18: extracted from build_pack, one copy): the last full fiscal
    year, its end date, its age, the vintage test and the reference's base inputs. Returns a dict: latest_yr, fy_rec,
    fye_src, fye_conflict, fy_end_dt, ven_capex_ok, ven_capex_why, stub, aligned, thr, ref_fy (the base dict, or None) and
    ref_fy_na (why there is none, or None). `today` is a date; `f` the TTM fields kept after the stranded-TTM gate."""
    from datetime import date as _date
    hy = [int(y) for y in h if str(y).isdigit()] if h else []
    latest_yr = max(hy) if hy else None
    fy_rec = (h.get(str(latest_yr)) or {}) if latest_yr is not None else {}
    out = {"latest_yr": latest_yr, "fy_rec": fy_rec, "fye_src": None, "fye_conflict": None, "fy_end_dt": None,
           "stub": None, "aligned": None, "thr": None, "ref_fy": None, "ref_fy_na": None}
    if latest_yr is not None:
        # the real `_fye_month_day` takes the records already in hand; a stand-in (a test's) is called as it always was
        mm, dd, src = (_fye_month_day(t, with_source=True, ttm=ttm, fin=fin) if getattr(_fye_month_day, "takes_records", False)
                       else _fye_month_day(t, with_source=True))
        vend, conflict = ((_vendor_fy_end_for(fin, fy_rec.get("net_income"), int(latest_yr),
                                              (h.get(str(int(latest_yr) - 1)) or {}).get("net_income")))
                          if src != "ttm" else (None, None))
        out.update(fye_src=src, fye_conflict=conflict, fy_end_dt=vend or _fy_end_date_for(int(latest_yr), mm, dd))
    fy_end_dt = out["fy_end_dt"]
    out["ven_capex_ok"], out["ven_capex_why"] = _vendor_capex_usable(fin, fy_end_dt)
    if latest_yr is None:
        return out
    stub = (today - fy_end_dt).days / 30.4375
    fy_cx = fy_rec.get("capex")
    if not isinstance(fy_cx, (int, float)) and out["ven_capex_ok"]:
        vc = fin.get("Capital_Expenditure")
        fy_cx = -float(vc) if isinstance(vc, (int, float)) and vc < 0 else None
    fy_ni, fy_da = fy_rec.get("net_income"), fy_rec.get("da")
    # Whole-book test (2026-09-26): the period comes from the consensus vintage, not the calendar. Past a fiscal year end the
    # vendor keeps the finished year as "current" until it is reported (EPAC, PSMT, MU: year-ago revenue = the filed FY2025 to
    # the dollar), and then moves past it before our filings hold it.
    try:
        thr = _date.fromisoformat(str(ttm.get("through"))[:10]) if f else None
    except ValueError:
        thr = None
    newest = max(d for d in (fy_end_dt, thr) if d is not None)
    age = (today - newest).days / 30.4375
    aligned = consensus_reference.vintage_aligned(estimates, fy_rec.get("revenue"))
    out.update(stub=stub, aligned=aligned, thr=thr)
    src, conflict = out["fye_src"], out["fye_conflict"]
    if src == "default":
        out["ref_fy_na"] = "the fiscal year end is unknown (no TTM record and no dated vendor statement)"
    elif conflict is not None:
        out["ref_fy_na"] = (f"the label year cannot be confirmed: the vendor's statements with FY{latest_yr}'s "
                            f"and FY{int(latest_yr) - 1}'s net income are dated a year apart from ours "
                            f"({conflict.isoformat()})")
    elif stub < 0:
        out["ref_fy_na"] = f"FY{latest_yr} ends {fy_end_dt.isoformat()}, after today"
    elif age > consensus_reference.STALE_MONTHS:
        out["ref_fy_na"] = (f"stale history: the newest period we hold ends {newest.isoformat()}, "
                            f"{age:.0f} months ago")
    elif stub > 12 and aligned is not True:
        # review B1: a failed or unknown vintage test is "not verified", never "rolled"
        out["ref_fy_na"] = (f"not verified: FY{latest_yr} ended {stub:.0f} months ago and the vendor's "
                            + ("year-ago revenue does not match its filed revenue within 2%" if aligned is False
                               else "year-ago revenue is not available")
                            + ", so the year consensus starts from cannot be checked")
    else:
        ref_fy = {"stub": stub,
                  "label": f"FY{latest_yr}, the last full fiscal year, ended {fy_end_dt.isoformat()}",
                  "da": fy_da if isinstance(fy_da, (int, float)) else None,
                  "capex": fy_cx,
                  # revision 17: the earnings path's base (X: net income before acquired-intangible amortization, F1) and the
                  # revenue path's base year
                  "x": throughcycle_record.adjusted_earnings(fy_rec, untagged),
                  "revenue": fy_rec.get("revenue"),
                  "base": (fy_ni + fy_da - fy_cx)
                  if all(isinstance(x, (int, float)) for x in (fy_ni, fy_da, fy_cx)) else None,
                  # review B1: the vendor's EPS levels meet filed D&A and capex only when the vintage test shows the two
                  # describe the same year and currency
                  "levels_block": (None if aligned is True else
                                   f"the vendor's year-ago revenue does not match FY{latest_yr}'s "
                                   f"filed revenue within 2% (currency, perimeter or period)"
                                   if aligned is False else
                                   f"the vendor's year-ago revenue is not available to check "
                                   f"against FY{latest_yr}'s filed revenue")}
        # the FY and TTM windows are compared only when the TTM is this fiscal year's own (the caller adds `quarters`/`through`)
        out["ref_fy"] = ref_fy
    return out


def _shares_default_state(t, fin, h, shares_cover):
    """The share-count default of a live pack (revision 18: extracted from build_pack's SECTION 2 for the reference's inputs):
    (shares_default, vendor shares, filed shares on today's basis). The same split, filed-series and P-2 vendor-protection
    steps the pack prints from."""
    sh = fin.get("Shares_Outstanding")
    split = _split_after_last_filing(sh, h)
    series = _filed_diluted_series(h) if h else []
    filed_today = (series[-1][1] * split["multiplier"] if split else series[-1][1]) if series else None
    gap = _shares_gap_state(filed_today, sh, shares_cover, lambda: fin.get("FX") is None and _screener_country(t) == "United States")
    unusable = bool(gap and gap["vendor_unusable"])
    so = float(f"{sh:,.0f}".replace(",", "")) if (isinstance(sh, (int, float)) and not isinstance(sh, bool)
                                                 and not (isinstance(sh, float) and (sh != sh)) and sh >= 0) else None
    default, _k, _period, _warning = _share_default(fin, so, filed_diluted=filed_today, vendor_unusable=unusable)
    return default, sh, filed_today


def reference_inputs(t, root, estimates, anchors, closure, *, printed=True, today=None):
    """Revision 18 (brief section 2, step 1): the single source of everything `consensus_reference.build` needs for company `t`,
    and nothing printed. build_pack, the closure builder and the ledger all call it; the parity test pins the pack's printed
    reference to `build(**reference_inputs(...)["kwargs"])` to the cent.

      t           ticker
      root        a DataRoot (the screener data, each file read once)
      estimates   the consensus estimates dict (enrich's "estimates"), or None
      anchors     {"rf": the anchor's nominal 10-year (fraction) or None, "ga": the long-run growth anchor (fraction, unquantized)
                  or None, "breakeven": 10-year breakeven (fraction) or None, "loading": {sector: Blume-adjusted loading}}
      closure     {"erp": the closure premium (fraction)} or None; the cost of equity is max(rf, ga) + adjusted loading x erp,
                  and there is NO fallback: without a premium (or a loading, or rf) the cost of equity is None
      printed     True (the pack): the cost of equity and the terminal default are quantized to the two decimals the pack prints
                  and the terminal anchor is the printed one; False (the closure's solve): unquantized, smooth in the premium
      today       the date the base year's age is measured at (default: now)

    Returns {"kwargs": the arguments of build (everything but the positional base_cf, estimates, coe, terminal_g, shares,
    median_5y, which it also carries under those names), "no_marker" (True when the history holds no brief-A provenance marker for
    `t`: amendment 2, point 2 - `build` then returns no value and says why), "coe", "coe_reason" (why there is none),
    "terminal_g", "record", "shares_default", "sector", "loading", "fy" (`_fiscal_year_base`'s dict, its `ref_fy` attributed), "cash"
    (attributed), "scope" (`input_scope.base_year_scope`), "vendor_basis" (`input_scope.vendor_revenue_basis`)}.

    Revision 20 (brief_input_scope_fixes.md): the inputs are scoped before `build` sees them - every level but net income multiplied by
    pi (Fix 1b), the record on the consolidated basis (`_record_for`), and on a vendor revenue-basis break the estimates without the next-FY
    revenue entry (Fix 3). `build` itself is unchanged."""
    today = today if today is not None else datetime.now().date()
    key = (t, today, id(estimates))
    memo = root.__dict__.setdefault("_static", {})
    if key not in memo:
        h = root.history(t)
        fin = root.fin(t)
        ttm = root.ttm(t)
        yrs = [int(y) for y in h if str(y).isdigit()]
        ttm_stale = bool(ttm and yrs and int(str(ttm.get("fy_leg_end", ""))[:4] or 0) != max(yrs))
        f = {} if ttm_stale else (ttm.get("fields") or {})
        marker = root.untagged(t)
        untagged = [] if marker is None else marker
        fy = _fiscal_year_base(t, h, fin, ttm, f, ttm_stale, estimates, untagged, today)
        sector, _industry = rs2_data.sector_lookup(t)
        cash = _cash_term_for(fy["fy_rec"], sector, fy["fye_src"], fy["fye_conflict"], fy["fy_end_dt"]) if fy["latest_yr"] is not None else None
        # revision 20 (brief_input_scope_fixes.md 1.3-1.4, 2.3): the base year's scope; net income stays the company's own and every
        # other level `build` receives (the base's D&A and capex, X's amortization, revenue, the cash term) is attributed by pi
        scope = input_scope.base_year_scope(h, root.hist_doc(), t, sector in consensus_reference.FINANCIAL_SECTORS)
        fy = dict(fy, ref_fy=input_scope.attribute_fy_base(fy["ref_fy"], fy["fy_rec"], scope["nci"]["pi"]))
        cash = input_scope.attribute_cash(cash, scope["nci"]["pi"])
        shares_default, _sh, _filed = _shares_default_state(t, fin, h, root.shares_cover(t))
        _size, _br, _gl, _gs, median_5y = _base_rate_median(h, root.sd, None)
        memo[key] = (h, fy, sector, cash, shares_default, median_5y, marker is None, scope)
    h, fy, sector, cash, shares_default, median_5y, no_marker, scope = memo[key]
    # revision 20 (brief 3.2): a vendor revenue-basis break gives `build` the estimates without the next-FY revenue entry; then (brief 1.3(b))
    # the vendor's revenue levels are attributed by pi. The terminal-growth default reads the vendor's figures as they are (brief 3.2).
    vendor_basis = input_scope.vendor_revenue_basis(estimates)
    est_build = input_scope.drop_next_fy_revenue(estimates) if vendor_basis["status"].startswith("break") else estimates
    est_build = input_scope.attribute_estimates(est_build, scope["nci"]["pi"])
    rf, ga, be = anchors.get("rf"), anchors.get("ga"), anchors.get("breakeven")
    loading = (anchors.get("loading") or {}).get(sector)
    erp = (closure or {}).get("erp")
    coe, coe_reason = None, None
    if not (_is_number(rf) and _is_number(ga) and _is_number(loading) and _is_number(erp)):
        coe_reason = "the closure premium, the risk-free rate, the growth anchor or the sector loading is not available"
    else:
        coe = max(rf, ga) + loading * erp
        if printed:
            coe = float(f"{coe * 100:.2f}") / 100.0
    ga_used = (float(f"{ga * 100:.2f}") / 100.0 if printed else ga) if _is_number(ga) else None
    rev_g2 = consensus_reference.revenue_growth_next_fy(estimates or {})
    record, terminal_g, basis, reason = _record_for(t, h, root.hist_doc(), coe, ga_used, be, rev_g2, median_5y, printed=printed)
    ref_fy = fy["ref_fy"] or {}
    kwargs = dict(base_cf=ref_fy.get("base"), estimates=est_build, coe=coe, terminal_g=terminal_g,
                  shares=shares_default if (isinstance(shares_default, (int, float)) and shares_default > 0) else None,
                  median_5y=median_5y, da=ref_fy.get("da"), capex=ref_fy.get("capex"), stub_months=ref_fy.get("stub"),
                  base_label=ref_fy.get("label"), levels_reason=ref_fy.get("levels_reason"), levels_block=ref_fy.get("levels_block"),
                  anchor=ga_used, record=record, base_ni=ref_fy.get("x"), base_revenue=ref_fy.get("revenue"), cash=cash,
                  unavailable_reason=consensus_reference.NO_MARKER_REASON if no_marker else None)
    return {"kwargs": kwargs, "no_marker": no_marker, "coe": coe, "coe_reason": coe_reason, "terminal_g": terminal_g, "terminal_basis": basis,
            "terminal_reason": reason, "record": record, "shares_default": shares_default, "sector": sector, "loading": loading,
            "fy": fy, "cash": cash, "median_5y": median_5y, "scope": scope, "vendor_basis": vendor_basis}


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _attributed_owner_earnings(ni, da, capex, pi):
    """Revision 20 (brief 1.3(b)): owner earnings, the company's own net income plus pi x (D&A - capex); pi = 1 is the filed arithmetic
    exactly (ni + da - capex)."""
    return ni + da - capex if pi == 1.0 else ni + pi * (da - capex)


def _oe_levels(text, pi):
    """The OWNER EARNINGS line's D&A-minus-capex term: as filed, or (pi < 1) the common shares' share of it."""
    return text if pi == 1.0 else f"\u03c0 {pi * 100:.1f}% \u00d7 ({text}), the common shares' share (NONCONTROLLING INTERESTS, DATA 5)"


def _attributed_row(row, pi):
    """A base-year row whose acquired-intangible amortization is attributed by pi (X = net income + pi x amortization x (1 - tax)); pi = 1
    returns the row."""
    if row is None or pi == 1.0 or not _is_number(row.get("amortization_intangibles")):
        return row
    return dict(row, amortization_intangibles=pi * row["amortization_intangibles"])


def _q_b_or_none(v):
    """Dollars as $B at the six decimals the facts keep, or None (revision 20's scope facts)."""
    return pack_facts.q_b(v / 1e9) if _is_number(v) else None


def _population_ranges_for(t, h, record, asof_date, hist_doc=None):
    """Revision 24 step 2b: tools/population_ranges.ranges_for on this company's record at the valuation date (the pack's as-of date, else
    today): the family from the rebuild's rules on the SIC (sic_by_cik.json, through the CIK) and the base year's row, the features from the
    fiscal-year rows `h` (already cut to the as-of date), the earnings margins from the pack's own record. Never raises: a table or file that cannot
    be read gives {"inputs": {}, "unavailable": <why>}, which the section prints."""
    T = asof_date if asof_date is not None else datetime.now().date()
    try:
        import paths as _paths
        sic_doc = rs2_data.load_json(_paths.resolve("priors_inputs_dir") / "sic_by_cik.json") or {}
        c = cik(t)
        sic = ((sic_doc.get("map") or {}).get(c) or {}).get("sic") if c else None
        base_year = (record or {}).get("base_year")
        fam = population_ranges.family_for(sic, h, base_year=base_year)
        # step 2c (cross-check 19, ruling A): the paired gap reads the earnings on the rows the record was measured on (the consolidated view) and
        # the filer's untagged fields, as the record does
        view = input_scope.record_view_for(h, hist_doc, t, base_year)[0] if (hist_doc is not None and base_year is not None) else None
        untagged = (_marker_for(hist_doc, t) or []) if hist_doc is not None else ()
        rec = population_ranges.company_record(h, base_year=base_year, family=fam["family"], earnings_record=record, untagged=untagged,
                                               earnings_rows=view)
        rec["family_reason"] = fam["reason"]           # step 2c: an unmeasured family's line names why
        out = population_ranges.ranges_for(rec, T)
        out["family_reason"], out["family_stamps"], out["sic"] = fam["reason"], fam["stamps"], sic
        out["record"] = {k: v for k, v in rec.items() if k != "missing"}
        out["record_missing"] = rec.get("missing")
        return out
    except Exception as e:                    # an unreadable table is stated in the pack, never a crash and never a silent blank
        return {"vintage": population_ranges.vintage_for(T), "inputs": {}, "unavailable": f"the population tables could not be read ({type(e).__name__}: {e})"}


def _one_off_us_gaap(t):
    """The us-gaap block of company `t`'s filed SEC companyfacts, from paths.resolve("screener_sec_facts_dir"), or None when the directory or the company's file is not
    held (the one-off lines are then "not held", never "none filed")."""
    import paths as _paths
    c = cik(t)
    d = _paths.resolve("screener_sec_facts_dir", required=False)
    p = (Path(d) / f"CIK{c}.json") if (d is not None and c) else None
    if p is None or not p.is_file():
        return None
    try:
        return (json.loads(p.read_text(encoding="utf-8")).get("facts") or {}).get("us-gaap") or {}
    except (OSError, ValueError):
        return None


def x_margin_basis_facts(t, h, hist_doc, estimates, facts):
    """Revision 25 short form (desk schema 25.2): {"x_margin_history", "x_margin_consensus_y1y2"} for company `t`, a pure function of its stored data - the screener's
    fiscal-year rows `h` and history document (the record's own view of them, as `_record_for` reads), the filed companyfacts, the frozen enrich `estimates` - and of the
    pack's own `facts` (shares_default, nci_attribution.pi, vendor_revenue_basis). Collects nothing: the build, and the derivation of a frozen revision-24 pack, call it alike."""
    yrs = sorted(int(y) for y in h if str(y).isdigit())
    base_year = max(yrs) if yrs else None
    untagged = _marker_for(hist_doc, t) or []
    view = input_scope.record_view_for(h, hist_doc, t, base_year)[0]
    period_ends = (((hist_doc.get("provenance") or {}).get("period_end") or {}).get(t)) or {}
    hist = x_margin_basis.history(view, untagged, period_ends, _one_off_us_gaap(t), base_year)
    pi = (facts.get("nci_attribution") or {}).get("pi")
    vb = str((facts.get("vendor_revenue_basis") or {}).get("status") or "")
    cons = x_margin_basis.consensus_margins(estimates, facts.get("shares_default"), pi, vendor_break=vb.startswith("break"))
    fy_rev = (h.get(str(base_year)) or {}).get("revenue") if base_year is not None else None
    cons["vintage_aligned"] = consensus_reference.vintage_aligned(estimates, fy_rev)
    return {"x_margin_history": hist, "x_margin_consensus_y1y2": cons}


def build_pack(t, price_override=None, include_research=True, asof=None, news_snippets=False, pilot_arm=None, ranges_show_p50=None):
    """Every fact we hold that is FILED, or is exact arithmetic on filed values, labelled with its
    source and its period. No judgment is exercised here: no valuation, no basis choice, no
    normalisation, no composite of our own. Where a series is known to be defective the pack says
    so inline, rather than dropping it or presenting it clean.

    DELIBERATELY EXCLUDED, each for a measured reason (and each declared in SECTION 12):
      * pretax_income / tax_provision / any effective tax rate — FIELD_SPECS['pretax_income']
        admits ...BeforeIncomeTaxesDomestic, so an unknown subset carries a domestic-only figure.
        Re-measured 2026-08-24: the identity net_income + tax == pretax fails by >5% on 180 of
        1,795 book rows (57 of 170 names) and on 6,461 of 39,671 corpus rows (1,762 of 4,606
        names) — so widening the universe makes it worse, not better. Tag presence was tested as a
        release gate and REJECTED: 116 book names carry the tag, but it misses 14 of the 57
        broken names and needlessly condemns 73 that pass. _pretax_note() now reports the failing
        years per company; the rate itself stays withheld, because the identity holding is
        necessary and not sufficient. A false [Actual] tax rate is worse than none: an invented
        one at least gets labelled [Assumption].
      * battery m_score — imputes absent Beneish ratios at 1.0 and a missing TATA term at 0.0,
        then publishes a score, presenting a guess as a measurement.
      * valuation_models.json / factor_scores.json — our own finished valuation and our own
        ranking. Handing either over makes the analysis circular.

    `asof` (Phase 4 E4.3, the time-travel trial): a date (or "YYYY-MM-DD" string). When given,
    EVERY input is restricted to what was knowable on that date — see the point-in-time helpers
    above `build_pack` and the header this prints. `include_research` is forced off regardless of
    what is passed: research is unconditionally OFF in point-in-time mode (a live web brief could
    only leak the future). None (the default) is unchanged, live-pack behaviour.

    `news_snippets` (S3 5.8, C1): RECENT COMPANY NEWS's default (False) drops a row's search
    snippet when that row carries no excerpt (246 of 278 recorded rows have no excerpt because the
    engine gives no date; the excerpt-bearing rows are unchanged). `catalyst_research.
    discovery_context` passes True, so the discovery run's input stays byte-identical to revision
    14's.

    `pilot_arm` and `ranges_show_p50` (revision 24 step 2b): the pilot's arm and the POPULATION RANGES section's P50 flag (`pack_flags`; config.json
    when not passed). The rev22 arm builds the revision-22 pack (its marker, the reference printed, the revision-22 DEFAULTS); every other build is
    the revision-24 pack (no reference, no long-run default, the POPULATION RANGES section).
    """
    # Declared exactly once, here, for the whole function: two separate `global X` statements
    # either side of X's first assignment raise a SyntaxError even when each is individually
    # valid for its own branch (SECTION 2.5 below assigns both names in either an asof branch
    # or a live branch, never both).
    global LAST_PACK_MOMENTUM_STATE, LAST_PACK_ACTIVE_SHOCKS
    asof_date = _parse_asof(asof) if asof is not None else None
    asof_cutoff = None
    last_allowed_fy = None
    asof_omitted = []   # every input dropped for point-in-time reasons, printed in SECTION 12
    _ref_oe = None      # the OWNER EARNINGS default, for SECTION 8's CONSENSUS-IMPLIED VALUE (E10)
    _ref_da = _ref_capex = None   # FY D&A and TTM capex, for the reference's EPS-levels method
    _ref = None         # revision 19: the consensus reference build returned (None when SECTION 8 builds none), for the DEFAULTS run
    _rf_eff = None      # revision 19: the risk-free rate the cost of equity is built on (a bound of the desk's coe search)
    _pack_price = None  # revision 19: the price the pack is built at, the one the desk uses (the DEFAULTS run is solved at it)
    _ref_fy = None      # E18: the last full fiscal year's base and its age, for the reference
    _ref_fy_na = None   # E18: why that fiscal year cannot anchor the consensus path
    _aligned = None     # E18: the vendor's estimates start from the filed fiscal year (vintage test)
    _byc_printed = False  # the BASE-YEAR CHECK line printed its numbers (the window line points to it)
    _r26_base = {}      # revision 26: the base year's vendor and filed EPS and the two basis tests, for consensus_corrected (set where the BASE-YEAR CHECK is built)
    _cash = None        # revision 18: consensus_reference.cash_term's dict for the base fiscal year (cash at face)
    section10_printed = False   # S3 5.5/5.10: SECTION 12's Q&A pointer names SECTION 10 only if it ran
    facts = pack_facts.empty()
    facts["source"] = "build"
    _arm, _show_p50 = pack_flags(pilot_arm, ranges_show_p50)
    _rev22 = _arm == "rev22"
    facts["pilot_arm"] = _arm
    facts["ranges_show_p50"] = _show_p50
    _r25 = _arm in R25_ARMS
    _r26 = _arm == R26_ARM
    _sf = _arm in (R25_SF_ARM, R26_ARM)          # revision 26 runs desk schema 25.2 on the revision-24 briefing, as the short form does
    if _r26 and asof is not None:
        raise ValueError("pilot_arm r26 has no point-in-time build: the blind pack's source classes are defined for the live pack")
    facts["desk_schema"] = DESK_SCHEMA_25 if _r25 else (DESK_SCHEMA_252 if _sf else None)        # revision 25: the desk's schema (pack_facts.KEYS), absent for every existing arm
    # revision 24 (R24.2): the reference is computed and kept in the facts, never printed; stage B shows it after the memorandum. Step 2b: nor is a
    # default for a long-run judgment. The rev22 arm prints both, as revision 22 did.
    facts["reference_withheld"] = None if _rev22 else True
    facts["long_run_defaults_withheld"] = None if _rev22 else True
    if asof_date is not None:
        from datetime import timedelta as _td
        asof_cutoff = asof_date - _td(days=POINT_IN_TIME_FILING_LAG_DAYS)
        _fye_m, _fye_d = _fye_month_day(t)
        last_allowed_fy = _last_allowed_fiscal_year(asof_cutoff, _fye_m, _fye_d)
        include_research = False

    # S3 5.1: the revision marker. from_text() dispatches on "(pack revision N)", N >= 15, appearing
    # in this first line (pack_facts._REVISION_RE) to read the DEFAULTS block instead of the legacy
    # regexes.
    L = r26_blind.PackLines([f"# DATA PACK - {t}   (pack revision {REV22_REVISION if _rev22 else (R25_REVISION if _r25 else (R26_REVISION if _r26 else (R25_SF_REVISION if _sf else PACK_REVISION)))})", ""])
    if asof_date is not None:
        L += [f"**POINT-IN-TIME BRIEFING — as of {asof_date.isoformat()}; you must not use "
              f"knowledge of events after this date.**",
              f"- Fundamentals below are restricted to periods whose end date is on or before "
              f"{asof_cutoff.isoformat()} ({POINT_IN_TIME_FILING_LAG_DAYS}-day conservative "
              f"filing lag before {asof_date.isoformat()}) — a period not yet filed by that date "
              f"cannot appear. This company's own fiscal calendar (month/day of its fiscal year "
              f"end — never a filed VALUE) decides which fiscal-year labels qualify; the "
              f"cross-company GROWTH BASE RATES corpus below instead applies one uniform "
              f"calendar (Dec 31) fiscal year end to all ~6,900 constituents, a stated "
              f"simplification for a population this size.",
              f"- Any input this pack cannot honestly restrict to {asof_date.isoformat()} is "
              f"OMITTED and printed as `{ASOF_NULL}` — never today's value.",
              ""]

    fin = rs2_data.load_json(SD / "financials" / f"{t}.json") or {}
    cm = fin.get("Calculated_Metrics") or {}
    ttm = (rs2_data.load_json(SD / "fundamentals_ttm.json") or {}).get("tickers", {}).get(t) or {}
    f = ttm.get("fields") or {}
    # TTM ALIGNMENT GATE, ported from the dropped engine (valuation_backbone.py:1244) on
    # 2026-08-24. A TTM record whose fiscal anchor disagrees with the newest annual year is not
    # this company's trailing twelve months - it is a stranded old record. Measured: 12 of 171
    # book names, MDT anchored to 2015 against FY2026. Printing it as "TRAILING TWELVE MONTHS"
    # states a period that is years wrong, and the plausibility fence divides by its OCF.
    # one read of the 47 MB history for the year list, the rows and (revision 17) the provenance marker
    _hist_doc = rs2_data.load_json(SD / "fundamentals_history.json") or {}
    _yrs = [int(y) for y in _hist_doc.get("tickers", {}).get(t, {}) if str(y).isdigit()]
    ttm_stale = bool(ttm and _yrs
                     and int(str(ttm.get("fy_leg_end", ""))[:4] or 0) != max(_yrs))
    if ttm_stale or asof_date is not None:
        # asof mode: TODAY's TTM snapshot is not a point-in-time figure at all — see the
        # point-in-time TTM recomputation (from allowed quarters only) further below.
        f = {}
    qrec = (rs2_data.load_json(SD / "fundamentals_quarterly.json") or {}).get("tickers", {}).get(t) or {}
    qs = qrec.get("quarters") or []
    h = _hist_doc.get("tickers", {}).get(t) or {}
    _shares_cover = (_hist_doc.get("shares_cover") or {}).get(t)     # P-2: the latest filing's cover-page count
    # Revision 17 (brief A's provenance marker): the fields (goodwill, intangibles_ex_goodwill,
    # amortization_intangibles) this filer never tags in any held year, which the through-cycle record
    # reads as "none held" (0); a null in a tagged series is a gap. provenance["untagged_fields"][T].
    _untagged_fields = ((_hist_doc.get("provenance") or {}).get("untagged_fields") or {}).get(t) or []
    # Revision 18 (amendment 2, point 2): a name the extractor never processed has NO marker, which is not the same as a marker of
    # nothing untagged ([]): its record would be computed without subtracting goodwill and intangibles. Such a name gets no
    # reference, and the DEFAULTS lines derived from the record say so with the reason.
    _no_marker = _marker_for(_hist_doc, t) is None
    bat = (rs2_data.load_json(SD / "fundamentals_battery.json") or {}).get("tickers", {}).get(t) or {}
    ob = rs2_data.load_json(HERE / "cache" / f"openbb_{t}.json") or {}
    en = rs2_data.load_json(HERE / "enrich" / f"{t}.json") or {}
    met = ob.get("metrics") or {}

    asof_ttm_recomputed = None   # set below, in asof mode, from the allowed quarters only
    if asof_date is not None:
        cutoff_iso = asof_cutoff.isoformat()
        qs_allowed = [r for r in qs if isinstance(r.get("end"), str) and r["end"] <= cutoff_iso]
        if len(qs) != len(qs_allowed):
            asof_omitted.append(
                f"fundamentals_quarterly.json: {len(qs) - len(qs_allowed)} quarter(s) ending "
                f"after {cutoff_iso} excluded (DATA 4)")
        qs = qs_allowed
        h_allowed = {y: v for y, v in h.items()
                    if str(y).isdigit() and int(y) <= last_allowed_fy}
        if len(h) != len(h_allowed):
            asof_omitted.append(
                f"fundamentals_history.json: fiscal year(s) after FY{last_allowed_fy} excluded "
                f"(DATA 5/6/6A/6B/6C, GROWTH BASE RATES)")
        h = h_allowed
        # TTM (SECTION 3): revenue/net income are recomputable as the sum of the trailing 4
        # ALLOWED quarters; OCF/capex/FCF/D&A are NOT — fundamentals_quarterly.json carries only
        # revenue/gross_profit/net_income per quarter (verified 2026-09-24: no ocf/capex/fcf/da
        # field exists at quarterly granularity anywhere in this file), so those four are omitted
        # rather than sourced from the single, un-restrictable TODAY snapshot.
        last4 = qs[-4:]
        if len(last4) == 4:
            rev4 = [q.get("revenue") for q in last4]
            ni4 = [q.get("net_income") for q in last4]
            if all(isinstance(x, (int, float)) for x in rev4 + ni4):
                asof_ttm_recomputed = {
                    "revenue": sum(rev4), "net_income": sum(ni4),
                    "through": last4[-1].get("end"),
                }
                capex4 = [q.get("capex") for q in last4]
                if all(isinstance(x, (int, float)) for x in capex4):
                    asof_ttm_recomputed["capex"] = sum(capex4)
                ocf4 = [q.get("ocf") for q in last4]
                if all(isinstance(x, (int, float)) for x in ocf4):
                    asof_ttm_recomputed["ocf"] = sum(ocf4)
        if asof_ttm_recomputed is None:
            asof_omitted.append(
                "TTM revenue/net income (DATA 3): fewer than 4 quarters end on or before "
                f"{cutoff_iso}")
        asof_omitted.append(
            "TTM operating cash flow / capex / FCF / D&A (DATA 3): fundamentals_quarterly.json "
            "carries no ocf/capex/fcf/da field at quarterly granularity, so these cannot be "
            "recomputed for any as-of date")
        if bat:
            asof_omitted.append("fundamentals_battery.json (DATA 7, quality/solvency "
                                "measures): same-day snapshot, no stored history to restrict")
        bat = {}
        if ob:
            asof_omitted.append("openbb cache (DATA 8 consensus & multiples, DATA 10 "
                                "earnings transcript): same-day snapshot, no stored history")
        ob = {}
        met = {}
        if en:
            asof_omitted.append("enrich/*.json (DATA 8 analyst targets/52-week range, "
                                "DATA 9 positioning): same-day snapshot, no stored history")
        en = {}
        asof_omitted.append("DATA 8.5 peer context: stocks.json is a same-day snapshot; "
                            "reconstructing it would need an as-of price+EPS fetch for every "
                            "cluster peer, not attempted this run")

    # PROVABLE 1000x SCALE CORRUPTION in this company's filed series. Detected with
    # data_health.audit_series_breaks so there is ONE definition of the test rather than a second
    # copy here that can drift from it. Imported lazily: depth_triggers imports this module on the
    # orchestrator's hot path and does not need valuation_backbone dragged in behind it.
    #
    # Why the pack has to say this itself. The 2026-08-08 gate in the dropped orchestrator cleared
    # these breaks whenever they did not reach a live `base_cf` - a quantity THIS pipeline never
    # computes - while the pack prints the entire year series to the model as filed fact. Measured
    # 2026-08-24: 3 of the 171 book names carry a provable break, and INCY's published HOLD verdict
    # was produced from a pack stating $19.094B of long-term debt for FY2018, a 1000x corruption of
    # roughly $19M. The model had no way to know.
    try:
        import data_health as _dh
        breaks = _dh.audit_series_breaks([t], {t: h}) if h else []
    except Exception:
        breaks = []
    if breaks:
        L.insert(2, "**DATA INTEGRITY ALERT - THIS COMPANY'S FILED SERIES CONTAINS A PROVABLE "
                    "SCALE CORRUPTION.** One period is recorded roughly 1000x away from the rest "
                    "of its own series, which a real restatement does not do. The affected cells "
                    "are printed below UNCHANGED, because silently patching filed data would hide "
                    "the defect rather than disclose it. DO NOT use these cells; use the "
                    "neighbouring years, and say in your report that you excluded them:\n"
                 + "\n".join(f"  - `{b['field']}` moves from {b['from']:,} in FY{b['from_year']} "
                             f"to {b['to']:,} in FY{b['to_year']}" for b in breaks))
        L.insert(3, "")

    fy_end, fy_src = _fy_end({} if (ttm_stale or asof_date is not None) else ttm, qs)
    drift = _schema_drift({"fin": fin, "ob": ob, "met": met, "en": en,
                           "bat": bat})
    if drift:
        print("   [pack] ::SCHEMA DRIFT:: " + t + " - expected keys absent upstream: "
              + " | ".join(drift), file=sys.stderr, flush=True)

    # ---- SECTION 0 -------------------------------------------------------------------------
    # S3 5.4 (verbatim). Old wording (revision 14, four bullets plus a "Series continuity warning"
    # paragraph) is replaced by this two-bullet form; every number it carried is unchanged (none).
    L += ["## DATA 0 - HOW TO READ THIS PACK",
          f"- `{NULL}` (NA in tables) means we do not hold the value; it never means zero, and a "
          f"filed zero prints 0.000. [Filed] = reported to the SEC by the company; [Arithmetic] = "
          f"exact arithmetic on filed values, with the window stated; [Aggregator] = a vendor's "
          f"restatement or estimate, not a filing. Money is in billions of the reporting currency "
          f"unless a line or table header says otherwise. Nothing here was verified by the code "
          f"that assembled it.",
          "- Series continuity: each year's column comes from whichever XBRL tag the company "
          "filed that year, and we do not record which. A step between adjacent years that never "
          "reverts is far more often a change of reporting basis than an event: Philip Morris "
          "shows revenue $73.91B in FY2015 and $26.68B in FY2016 because excise taxes left the "
          "revenue line. Verify any step you lean on.", ""]

    # Phase 4 T1: compute consensus next-FY revenue growth and growth base rates median
    # for Section 1.5's TERMINAL-GROWTH DEFAULT and Section 8's CONSENSUS-IMPLIED VALUE.
    yrs = sorted([int(y) for y in h if str(y).isdigit()])
    size_label, br_table, g_lbl, g_stats, pack_median_5y = _base_rate_median(h, SD, last_allowed_fy)

    enrich_est = (en.get("estimates") or {}) if en else {}
    pack_rev_g2 = consensus_reference.revenue_growth_next_fy(enrich_est)
    terminal_def_val = None
    terminal_def_reason = None
    terminal_def_basis = None
    _record = None     # revision 17: the company's own record (tools/throughcycle_record.py), set in SECTION 1.5
    _lr_raw = {}       # revision 17: the long_run fact's raw members, completed as the pack learns them

    def _through_cycle(ga_q, be):
        """Revision 17, brief B sections 1 and 3: the company's own record at r = the COE anchor the pack
        prints (facts coe_anchor), and the terminal-growth default built on its revenue trend: (record,
        default, basis, reason). The default is quantized to the two decimals the pack prints, so the
        reference, the printed default and the desk's default are one number."""
        return _record_for(t, h, _hist_doc, facts["coe_anchor"], ga_q, be, pack_rev_g2, pack_median_5y)

    def _terminal_default_line(gt, basis, reason, ga_q, be, rec):
        """SECTION 1.5's TERMINAL-GROWTH DEFAULT line: the revenue-trend basis (revision 17), or the
        revision-16 wording when the default came from the consensus-growth fallback."""
        if ga_q is None:
            return None
        if basis == "revenue_trend":
            yrs_g = rec["g_rev_years"]
            return (f"- TERMINAL-GROWTH DEFAULT for this name: {gt * 100:.2f}% — from your own revenue "
                    f"trend FY{yrs_g[0]}-FY{yrs_g[-1]}: {rec['g_rev'] * 100:.2f}%/yr, held between breakeven "
                    f"inflation ({be * 100:.2f}%) and the anchor ({ga_q * 100:.2f}%).")
        if gt != ga_q:
            return (f"- TERMINAL-GROWTH DEFAULT for this name: {gt * 100:.2f}% — "
                    f"next-FY consensus revenue growth ({pack_rev_g2 * 100:.1f}%) is below the anchor, "
                    f"so the default is the year-5 growth floored at zero real growth "
                    f"(10-year breakeven inflation {be * 100:.2f}%).")
        if reason is not None and be is None:
            return (f"- TERMINAL-GROWTH DEFAULT for this name: {ga_q * 100:.2f}% — "
                    f"next-FY consensus revenue growth ({pack_rev_g2 * 100:.1f}%) is below the anchor, "
                    f"but the 10-year breakeven inflation floor is not available, so the default remains the anchor.")
        return None

    def _record_facts():
        """Revision 17: the record's part of the facts, stamped once the branch above has run."""
        if _record is None or _no_marker:
            return
        _rt = _record["ronic_t"]
        facts["terminal_ronic"] = pack_facts.q_rate(_rt) if _rt is not None else None
        def _yrs(stat, years):
            # the years a statistic used: none when the record was too short for the statistic
            return _span_n(years) if stat is not None else None
        _lr_raw.update({
            "cycle": _record["cycle"], "cycle_year": _record["cycle_year"], "cycle_years": _record["cycle_years"],
            "m_tc": _record["m_tc"], "m_years": _yrs(_record["m_tc"], _record["m_years"]),
            "r_tc": _record["R_tc"], "r_years": _yrs(_record["R_tc"], _record["r_years"]), "p": _record["p"],
            "g_rev": _record["g_rev"], "g_rev_years": _yrs(_record["g_rev"], _record["g_rev_years"]),
            "terminal_g_basis": terminal_def_basis,
            "nwc_intensity": _record["nwc_intensity"], "nwc_years": _yrs(_record["nwc_intensity"], _record["nwc_years"]),
            "om_tc": _record["om_tc"], "om_trend": _record["om_trend"], "om_L": _record["om_L"],
            "om_years": _yrs(_record["om_tc"], _record["om_years"]),
            "om_shape": _record["om_shape"], "om_basis": _record["om_basis"],
            # brief C7: the DEFAULTS block lists the eight window years' stamps as ranges; the facts (the verdict) keep the
            # record's full list
            "stamps": pack_facts.compact_stamps(_record["stamps"], _record["window"]),
            "stamps_full": list(_record["stamps"])})
        # revision 24 step 2b (ruling 3 of step 2a): the base fiscal year's filed earnings margin (the record's x_L) and filed revenue, the common
        # shares' share of it (pi, as e5 and oe5 are attributed), $B; the desk's m5 when the facts hold no year-5 revenue, and the implied
        # trajectory's base
        _rev_L = throughcycle_record._num((h.get(str(_record["base_year"])) or {}).get("revenue")) if _record.get("base_year") else None
        _lr_raw.update({"x_L": _record.get("x_L"),
                        "rev_L": (_rev_L * _pi / 1e9) if (_rev_L is not None and isinstance(_pi, (int, float))) else None})

    # ---- SECTION 1 - IDENTITY & INSTITUTIONAL TAXONOMY -------------------------------------
    sector, industry = rs2_data.sector_lookup(t)
    # revision 20 (brief_input_scope_fixes.md): the base year's scope, the one copy `reference_inputs` also reads - pi (Fix 1b), the
    # per-share check (Fix 1c), the cash scope and customer money (Fix 2b)
    _scope = input_scope.base_year_scope(h, _hist_doc, t, sector in consensus_reference.FINANCIAL_SECTORS)
    _pi = _scope["nci"]["pi"]
    _nci = _scope["nci"]
    # the record's window years that fall back to the company's own figures while noncontrolling interests are filed (the record itself
    # is computed on the same view, `_record_for`)
    _mixed = input_scope.record_view_for(h, _hist_doc, t, _scope["year"])[1]
    facts["nci_attribution"] = {"pi": pack_facts.q_ratio(_pi), "basis": _nci["basis"], "year": _nci["year"],
                                "ni_parent_b": _q_b_or_none(_nci["ni_parent"]), "ni_incl_nci_b": _q_b_or_none(_nci["ni_incl_nci"]),
                                "equity_b": _q_b_or_none(_nci["equity"]), "equity_incl_nci_b": _q_b_or_none(_nci["equity_incl_nci"]),
                                "stamps": list(_nci["stamps"]) + ([input_scope.mixed_stamp(_mixed)] if _mixed else [])}
    facts["ni_scope"] = _scope["ni_scope"]
    _ps = _scope["per_share"]
    facts["per_share_basis"] = {"status": _ps["status"], "year": _ps["year"], "n_common_b": _q_b_or_none(_ps["n_common"]),
                                "n_common_source": _ps["n_common_source"], "eps_filed": _ps["eps_filed"], "shares_diluted": _ps["shares_diluted"],
                                "eps_implied": _ps["eps_implied"], "gap": _ps["gap"], "tolerance": _ps["tolerance"], "stamps": list(_ps["stamps"])}
    _money = _scope["money"]
    facts["cash_scope"] = _scope["cash_scope"]
    facts["cash_restricted_b"] = _q_b_or_none(_money["cash_restricted"])
    facts["customer_money"] = {"assets_b": _q_b_or_none(_money["assets"]), "liabilities_b": _q_b_or_none(_money["liabilities"]),
                               "gap_b": _q_b_or_none(_money["gap"]), "stamps": list(_money["stamps"])}
    facts["insurance_reserves_b"] = _q_b_or_none(_money["insurance_reserves"])
    
    # Ingest Canonical Industry Taxonomy & Corporate Finance Archetype
    canon_industry, cluster, archetype = industry, "Unknown", "compounder_general"
    try:
        candidates = [SD.parents[2] / "scripts", SD.parents[1] / "scripts", Path("C:/Users/riper/Downloads/Stock Screener/scripts")]
        for sc in candidates:
            if sc.exists() and str(sc) not in sys.path:
                sys.path.append(str(sc))
        from industry_taxonomy import get_taxonomy_profile
        tax_profile = get_taxonomy_profile(industry, sector)
        canon_industry = tax_profile.get("canonical_industry", industry)
        cluster = tax_profile.get("cluster", "Unknown")
        archetype = tax_profile.get("archetype", "compounder_general")
    except Exception:
        pass

    L += ["## DATA 1 - IDENTITY & TAXONOMY",
          f"- Ticker: {t} | Sector: {sector} | Canonical Industry: {canon_industry}",
          f"- Macro Strategic Cluster (1 of 24): {cluster}",
          f"- Primary Archetype Category: {archetype} (Deconstruct into constituent value drivers per Pillar 1)",
          f"- Fiscal year ends: {fy_end}   [derived from {fy_src}]",
          "- Rows below are labelled by FISCAL year, not calendar year.", ""]

    # ---- SECTION 1.5 / 1.6 - MACRO REGIME, COST OF CAPITAL, STATE OF THE WORLD --------------
    L.cls = r26_blind.DERIVED
    if asof_date is not None:
        # Point-in-time reconstruction (Phase 4 E4.3) — read-only queries against MRI's own
        # duckdb store, never today's *_anchor.json/current_regime.json/shock_register.json
        # snapshots. See rs2_data.asof_* for what each leg can and cannot be reconstructed from.
        coc = rs2_data.asof_cost_of_capital(asof_date)
        rf_v, real_v, be_v = (coc["risk_free"].get(k) for k in
                              ("nominal_10y", "real_10y", "breakeven_10y"))
        rf_pct = rf_v * 100.0 if rf_v is not None else None
        real_pct = real_v * 100.0 if real_v is not None else None
        be_pct = be_v * 100.0 if be_v is not None else None

        # ERP(asof): latest Damodaran annual implied ERP whose year-end <= asof - 30 days
        erp_v, erp_src = rs2_data.asof_damodaran_erp(asof_date)
        erp_pct = erp_v * 100.0 if erp_v is not None else None
        coe_pct = coc["implied_cost_of_equity"]   # already percent (asof_cost_of_capital's convention)

        mri_sec = rs2_data.mri_sector_id(sector)
        # sector_loading: CURRENT anchor's loading for name's MRI sector id (structural parameter)
        anchor_load_val, _ = rs2_data.anchor_sector_loading(sector)
        # terminal_g anchor: CURRENT long_run_growth_anchor value (structural parameter)
        terminal_g_val, terminal_g_src = rs2_data.anchor_terminal_g()

        _STRUCTURAL_LOADING_LABEL = (
            "sector loading from the current anchor (structural parameter; small look-ahead risk, "
            "accepted for this trial)"
        )
        _STRUCTURAL_TERMINAL_G_LABEL = (
            "from the current anchor (structural parameter; small look-ahead risk, accepted for this trial)"
        )

        # S3 5.6: the individual anchor lines (rf/real/breakeven/ERP/implied CoE/sector loading)
        # are folded into one "Rates:" line below; only the values are needed here.
        adj_load_val, raw_load_val, _ = rs2_data.coe_loading(sector)
        if rf_pct is not None and adj_load_val is not None and erp_pct is not None:
            coe_anchor_pct = rf_pct + adj_load_val * erp_pct
            facts["coe_anchor"] = float(f"{coe_anchor_pct:.2f}") / 100.0
            facts["coe_premium_source"] = "damodaran_point_in_time"
        else:
            coe_anchor_pct = None
            facts["coe_anchor"] = None

        if terminal_g_val is not None:
            facts["terminal_g_anchor"] = float(f"{terminal_g_val*100:.2f}") / 100.0
        else:
            facts["terminal_g_anchor"] = None

        be_val = be_pct / 100.0 if be_pct is not None else None
        _record, terminal_def_val, terminal_def_basis, terminal_def_reason = _through_cycle(
            facts["terminal_g_anchor"], be_val)
        terminal_def_line = _terminal_default_line(terminal_def_val, terminal_def_basis, terminal_def_reason,
                                                   facts["terminal_g_anchor"], be_val, _record)

        sec_series = rs2_data.asof_secondary_macro_series(asof_date)
        t10y2y = sec_series["t10y2y"][0] if sec_series["t10y2y"] else None
        baa10y = sec_series["baa10y"][0] if sec_series["baa10y"] else None
        hy_oas = sec_series["hy_oas"][0] if sec_series["hy_oas"] else None
        if t10y2y is not None:
            slope = "Inverted" if t10y2y < 0 else "Normal / Steepening"
            curve_clause = (f"Curve 10y-2y {t10y2y:+.2f}% ({slope}, as of "
                           f"{sec_series['t10y2y'][1]}, point-in-time MRI raw_observations)")
        else:
            curve_clause = f"Curve 10y-2y {ASOF_NULL}"
        if baa10y is not None:
            ig_clause = (f"IG spread (BAA - 10Y) {baa10y:.2f}% (as of {sec_series['baa10y'][1]}, "
                        f"point-in-time MRI raw_observations)")
        else:
            ig_clause = f"IG spread (BAA - 10Y) {ASOF_NULL}"
        if hy_oas is not None:
            hy_clause = (f"HY OAS {hy_oas:.2f}% (as of {sec_series['hy_oas'][1]}, point-in-time "
                        f"MRI raw_observations)")
        else:
            hy_clause = f"HY OAS {ASOF_NULL}"

        regime = rs2_data.asof_regime_vector(asof_date)
        probs = regime["probabilities"] if regime else {}
        regime_headline = regime["headline"] if regime else None
        regime_fresh = regime is not None
        if regime is None:
            regime_line = f"- Regime probabilities: {ASOF_NULL}"
        else:
            vec_items = [f"{k} {v:.3f}" for k, v in sorted(probs.items(), key=lambda x: -x[1])]
            if regime.get("margin") is not None:
                label_clause = f"headline {regime_headline}, margin {regime['margin']:.3f}, contested"
            else:
                label_clause = f"headline {regime_headline}, contested" if regime_headline else "contested"
            regime_line = (f"- Regime probabilities (as of {regime['date']}, point-in-time): "
                          f"{', '.join(vec_items)} | {label_clause}")

        # S3 5.6/5.3: same typed-line pattern as the live path (header + Rates/COE ANCHOR/exit
        # multiple/Curve/Regime); the MANDATE/COE MANDATE/COST OF CAPITAL lines and rule tails are
        # gone (they live in the DEFAULTS block and the desk's refusals now). Every number stays.
        degraded_str = str(coc['degraded'])
        reasons_str = '; '.join(coc['degradation_reasons']) or 'none'
        rates_line = ("- Rates: rf (nominal 10y) " + (f"{rf_pct:.2f}%" if rf_pct is not None else ASOF_NULL)
                      + " | real 10y " + (f"{real_pct:.2f}%" if real_pct is not None else ASOF_NULL)
                      + " | breakeven 10y " + (f"{be_pct:.2f}%" if be_pct is not None else ASOF_NULL)
                      + " | implied ERP " + (f"{erp_pct:.2f}%" if erp_pct is not None else ASOF_NULL)
                      + " | implied cost of equity " + (f"{coe_pct:.2f}%" if coe_pct is not None else ASOF_NULL)
                      + " | sector cost-of-equity loading"
                      + (f" ({mri_sec})" if mri_sec is not None else f" (unmapped sector: {sector or 'none'})")
                      + " " + (f"{anchor_load_val:.3f}x" if anchor_load_val is not None else ASOF_NULL))

        if coe_anchor_pct is not None:
            coe_clause = (f"COE ANCHOR for this name: {coe_anchor_pct:.2f}% = rf {rf_pct:.2f}% + "
                         f"adjusted loading {adj_load_val:.3f}× (Blume: 0.67 × raw "
                         f"{raw_load_val:.3f} + 0.33) × implied ERP {erp_pct:.2f}% (asof "
                         f"{asof_date.isoformat()}, {erp_src}; {_STRUCTURAL_LOADING_LABEL}); point-in-time packs use "
                         f"Damodaran's premium; " + ("the live reference's closure premium" if _rev22 else "the closure premium")
                         + " cannot be rebuilt for a past date")
        else:
            coe_clause = f"COE ANCHOR for this name: {ASOF_NULL}"
        if terminal_g_val is not None:
            tg_clause = (f"long-run nominal growth anchor {terminal_g_val * 100:.2f}% "
                        f"({_STRUCTURAL_TERMINAL_G_LABEL})")
        else:
            tg_clause = f"long-run nominal growth anchor {ASOF_NULL} ({terminal_g_src})"
        coe_anchor_line = f"- {coe_clause} | {tg_clause}"

        curve_line = f"- {curve_clause} | {ig_clause} | {hy_clause}"

        L += [f"## DATA 1.5 - MACRO STATE & COST OF CAPITAL ANCHORS   [MRI anchors as of "
              f"{asof_date.isoformat()}, degraded: {degraded_str}, reasons: {reasons_str}, "
              f"point-in-time; verified: do not search the web for them]",
              rates_line,
              coe_anchor_line]
        if terminal_def_line and _rev22:      # revision 24 step 2b: no long-run default is printed (the facts keep it, for the benchmark)
            L.append(terminal_def_line)
        facts["terminal_g_default"] = terminal_def_val   # quantized to the printed two decimals
        _record_facts()
        L += [curve_line, regime_line]
        L.append("")

        macro_degraded = bool(
            rf_pct is None or real_pct is None or be_pct is None or erp_pct is None
            or coe_pct is None or anchor_load_val is None or t10y2y is None or baa10y is None
            or hy_oas is None or coc["degraded"] or not regime_fresh
        )

        shock_state = rs2_data.asof_shock_register(asof_date)
        L16 = ["## DATA 1.6 - STATE OF THE WORLD   [dated facts, not a forecast, "
              "point-in-time]", ""]
        if regime is not None:
            vec5 = [f"{k} {probs[k]:.3f}" if k in probs else f"{k} {ASOF_NULL}"
                    for k in ("goldilocks", "reflation", "stagflation", "recession", "tightening")]
            margin_txt = f"{regime['margin']:.3f}" if regime.get("margin") is not None else ASOF_NULL
            L16.append(f"- MRI regime probability vector (as of {regime['date']}): "
                      f"[{', '.join(vec5)}] | headline {regime_headline or ASOF_NULL} (margin "
                      f"{margin_txt} - contested)")
        else:
            L16.append(f"- MRI regime probability vector: {ASOF_NULL}")

        if shock_state is None:
            L16.append(f"- Active shocks (S4 register): {ASOF_NULL}")
        elif shock_state["shocks"]:
            for s in shock_state["shocks"]:
                L16.append(f"- ACTIVE SHOCK: `{s['shock_id']}` | severity {s['severity']} | "
                          f"direction {s['direction']} | onset {s['onset_date'] or ASOF_NULL}  "
                          f"(as of {shock_state['asof']})")
        else:
            L16.append(f"- Active shocks (S4 register): none active  (as of "
                      f"{shock_state['asof']})")

        if shock_state is None:
            L16.append(f"- Risk flag `elevated_volatility_ahead`: {ASOF_NULL}")
        else:
            evf_state = "ACTIVE" if shock_state["elevated_volatility_ahead"] else "inactive"
            # `meaning` is static narrative metadata (config/shocks.yaml risk_flags), not a
            # per-date measurement — reproduced verbatim rather than recomputed.
            L16.append(f"- Risk flag `elevated_volatility_ahead`: {evf_state} - Expect higher "
                      "market turbulence over the next 3 months. No evidence of lower returns "
                      f"or deeper drawdowns.  (as of {shock_state['asof']})")

        L16.append("- Nominal 10-Year Treasury yield: "
                  + (f"{rf_pct:.2f}%  (point-in-time)" if rf_pct is not None else ASOF_NULL))
        L16.append("- Real 10-Year Treasury yield: "
                  + (f"{real_pct:.2f}%  (point-in-time)" if real_pct is not None else ASOF_NULL))
        L16.append("- 10-Year breakeven inflation: "
                  + (f"{be_pct:.2f}%  (point-in-time)" if be_pct is not None else ASOF_NULL))
        infl = rs2_data.asof_inflation_trend(asof_date)
        if infl.get("cpi_yoy") is not None or infl.get("pce_yoy") is not None:
            parts = []
            if infl.get("cpi_yoy") is not None:
                parts.append(f"CPI YoY {infl['cpi_yoy']*100:.2f}%")
            if infl.get("pce_yoy") is not None:
                parts.append(f"PCE YoY {infl['pce_yoy']*100:.2f}%")
            L16.append(f"- Inflation trend: {', '.join(parts)}  (point-in-time)")

        # WORLD NEWS (P4 D10): read-only from the MRI news feed's `origin/run-history` branch
        # (world_news.py) — never today's news leaking into a past briefing; see _world_news_lines.
        wn = world_news.digest(asof=asof_date)
        L16.extend(_world_news_lines(wn, asof_date))

        L16.append("")
        L += L16
    else:
        coc_payload = rs2_data.usable_anchor("cost_of_capital")
        anchor_asof = coc_payload.get("asof") if coc_payload else None
        anchor_degraded = coc_payload.get("degraded") if coc_payload else None
        anchor_reasons = (coc_payload.get("provenance") or {}).get("degradation_reasons") if coc_payload else []

        # Accessors for MRI anchors:
        # 1) Nominal 10-year
        anchor_rf_val, anchor_rf_src = rs2_data.anchor_risk_free_rate()
        # 2) Real 10-year
        anchor_real_val, anchor_real_src = rs2_data.anchor_real_10y()
        # 3) Breakeven 10-year
        anchor_be_val, anchor_be_src = rs2_data.anchor_breakeven_10y()
        # 4) Implied ERP
        anchor_erp_val, anchor_erp_src = rs2_data.anchor_mature_erp()
        # 5) Implied cost of equity
        anchor_coe_val, anchor_coe_src = rs2_data.anchor_level_cost_of_equity_pct()
        # 6) Sector loading
        anchor_load_val, anchor_load_src = rs2_data.anchor_sector_loading(sector)

        # Secondary macro source: macro_state.json
        macro_json = rs2_data.load_json(SD / "macro_state.json") or {}
        macro_series = macro_json.get("series") or {}
        dgs10_series = macro_series.get("DGS10") or {}
        dgs10_sec = dgs10_series.get("value")
        t10y2y_series = macro_series.get("T10Y2Y") or {}
        t10y2y = t10y2y_series.get("value")
        baa10y_series = macro_series.get("BAA10Y") or {}
        baa10y = baa10y_series.get("value")
        hy_oas_series = macro_series.get("BAMLH0A0HYM2") or {}
        hy_oas = hy_oas_series.get("value")

        # S3 5.6: the individual anchor lines (rf/real/breakeven/ERP/implied CoE/sector loading)
        # are folded into one "Rates:" line below; only the values are needed here.
        # 1) Nominal 10-Year (anchor first, secondary fallback)
        if anchor_rf_val is not None:
            rf_pct = anchor_rf_val * 100.0
        elif dgs10_sec is not None:
            rf_pct = float(dgs10_sec)
        else:
            rf_pct = None

        # 2) Real 10-Year
        real_pct = anchor_real_val * 100.0 if anchor_real_val is not None else None

        # 3) Breakeven 10-Year
        be_pct = anchor_be_val * 100.0 if anchor_be_val is not None else None

        # 4) Implied ERP
        erp_pct = anchor_erp_val * 100.0 if anchor_erp_val is not None else None

        # 5) Implied Cost of Equity
        coe_pct = float(anchor_coe_val) if anchor_coe_val is not None else None

        # 6) Sector Loading
        mri_sec = rs2_data.mri_sector_id(sector)

        # D3 (PHASE_4_PACK_SPEC.md): COE ANCHOR for this name = rf + Blume-adjusted sector loading x implied ERP —
        # the single number `coe_used` is measured against (+-150bp), not just its separate legs above.
        adj_load_val, raw_load_val, _ = rs2_data.coe_loading(sector)
        coe_anchor_pct = None
        _coe_asof_str = NULL
        facts["coe_anchor"] = None

        # D3: the long-run nominal growth anchor terminal_g must be built from, per P1.6/anchor_terminal_g().
        lrg_payload = rs2_data.usable_anchor("long_run_growth")
        terminal_g_val, terminal_g_src = rs2_data.anchor_terminal_g()
        if terminal_g_val is not None:
            facts["terminal_g_anchor"] = float(f"{terminal_g_val*100:.2f}") / 100.0
        else:
            facts["terminal_g_anchor"] = None

        # Revision 18 (brief 1.6): COE_i = rf_eff + adjusted loading x ERP_closure, rf_eff = max(rf, the long-run growth anchor).
        # The closure premium is rs2's (tools/reference_closure.py); there is NO fallback to MRI's universe premium - a substituted
        # rate is the defect the accessors exist to end. MRI's premium stays on the Rates line as market context.
        _clos_erp, _clos_asof, _clos_why = rs2_data.reference_closure()
        _rf_eff = None
        if anchor_rf_val is not None and terminal_g_val is not None and adj_load_val is not None and _clos_erp is not None:
            _rf_eff = max(anchor_rf_val, terminal_g_val)
            coe_anchor_pct = (_rf_eff + adj_load_val * _clos_erp) * 100.0
            _coe_asof_str = str(_clos_asof) if _clos_asof else NULL
            facts["coe_anchor"] = float(f"{coe_anchor_pct:.2f}") / 100.0
            facts["coe_premium_source"] = "closure"

        be_val = be_pct / 100.0 if be_pct is not None else None
        _record, terminal_def_val, terminal_def_basis, terminal_def_reason = _through_cycle(
            facts["terminal_g_anchor"], be_val)
        terminal_def_line = _terminal_default_line(terminal_def_val, terminal_def_basis, terminal_def_reason,
                                                   facts["terminal_g_anchor"], be_val, _record)

        # Anchor metadata (S3 5.6: folded into the section header bracket, not a separate bullet)
        reasons_str = "; ".join(str(r) for r in anchor_reasons) if anchor_reasons else "none"
        degraded_str = str(anchor_degraded) if anchor_degraded is not None else NULL
        asof_str = str(anchor_asof) if anchor_asof else NULL

        # Secondary macro series (S3 5.6: one "Curve" line; each clause keeps its own date so no
        # number drops out of the pack's per-name numbers set, 7.3(c))
        if t10y2y is not None:
            slope = 'Inverted' if float(t10y2y) < 0 else 'Normal / Steepening'
            curve_clause = (f"Curve 10y-2y {float(t10y2y):+.2f}% ({slope}, as of "
                            f"{t10y2y_series.get('as_of', 'recent')})")
        else:
            curve_clause = f"Curve 10y-2y {NULL}"
        if baa10y is not None:
            ig_clause = f"IG spread (BAA - 10Y) {float(baa10y):.2f}% (as of {baa10y_series.get('as_of', 'recent')})"
        else:
            ig_clause = f"IG spread (BAA - 10Y) {NULL}"
        if hy_oas is not None:
            hy_clause = f"HY OAS {float(hy_oas):.2f}% (as of {hy_oas_series.get('as_of', 'recent')})"
        else:
            hy_clause = f"HY OAS {NULL}"
        curve_line = f"- {curve_clause} | {ig_clause} | {hy_clause}"

        # Regime line (S3 5.6: one line)
        regime_file = rs2_data.load_json(Path(CONFIG.get("mri_outputs_dir", "")) / "current_regime.json") or {}
        regime_date = regime_file.get("date")
        # C13 (Phase 1 approval review): no silent default — a missing config key must raise,
        # never quietly substitute a hidden constant that duplicates config.json's own value.
        regime_fresh = bool(regime_date and rs2_data._fresh(regime_date, CONFIG["regime_max_age_days"]))
        # Defined here, not only inside the "fresh" branch below, so SECTION 1.6's regime vector
        # (printed regardless of freshness) can read it without a NameError on a stale/absent regime.
        probs = {}

        if not regime_file or not regime_date:
            regime_headline = None
            regime_line = f"- Regime probabilities: {NULL}"
        elif not regime_fresh:
            regime_headline = None
            regime_line = f"- Regime probabilities: {NULL} (stale: {regime_date})"
        else:
            regime_headline = regime_file.get("season_headline") or regime_file.get("reported_regime") or regime_file.get("dominant_regime") or regime_file.get("regime")
            margin = regime_file.get("headline_margin")
            posterior = regime_file.get("season_posterior") or {}
            probs = {}
            if posterior:
                for k, v in posterior.items():
                    p_val = v.get("probability") if isinstance(v, dict) else v
                    if isinstance(p_val, (int, float)):
                        probs[k] = float(p_val)
            elif regime_file.get("regime_probabilities"):
                for k, v in (regime_file.get("regime_probabilities") or {}).items():
                    if isinstance(v, (int, float)):
                        probs[k] = float(v)

            vec_items = [f"{k} {v:.3f}" for k, v in sorted(probs.items(), key=lambda x: -x[1])]
            vec_str = ", ".join(vec_items) if vec_items else NULL
            # B6 (Phase 1 approval review): the vector prints FIRST and the label second, as a
            # contested headline with its margin — never an unqualified regime name. Operator
            # ruling: the label is demoted and may no longer drive any numeric output.
            if isinstance(margin, (int, float)):
                label_clause = f"headline {regime_headline}, margin {float(margin):.3f}, contested"
            else:
                label_clause = f"headline {regime_headline}, contested" if regime_headline else "contested"
            regime_line = f"- Regime probabilities (as of {regime_date}): {vec_str} | {label_clause}"

        # S3 5.6: SECTION 1.5 becomes a header plus five typed lines (Rates, COE ANCHOR, default
        # exit multiple, Curve, Regime probabilities); 5.3 drops the MANDATE/COE MANDATE/COST OF
        # CAPITAL lines and the rule tails — those rules now live in the DEFAULTS block (5.2) and
        # the desk's own refusals (3.4-3.5). Every number that survives is unchanged.
        rates_line = ("- Rates: rf (nominal 10y) " + (f"{rf_pct:.2f}%" if rf_pct is not None else NULL)
                      + " | real 10y " + (f"{real_pct:.2f}%" if real_pct is not None else NULL)
                      + " | breakeven 10y " + (f"{be_pct:.2f}%" if be_pct is not None else NULL)
                      + (" | MRI universe premium (context; not used in the reference) " if _rev22 else
                         " | MRI universe premium (context; not used in the COE ANCHOR) ")
                      + (f"{erp_pct:.2f}%" if erp_pct is not None else NULL)
                      + " | MRI market cost of equity (context) " + (f"{coe_pct:.2f}%" if coe_pct is not None else NULL)
                      + " | sector cost-of-equity loading"
                      + (f" ({mri_sec})" if mri_sec is not None else f" (unmapped sector: {sector or 'none'})")
                      + " " + (f"{anchor_load_val:.3f}x" if anchor_load_val is not None else NULL))

        if coe_anchor_pct is not None:
            coe_clause = (f"COE ANCHOR for this name: {coe_anchor_pct:.2f}% = rf_eff {_rf_eff * 100:.2f}% (the larger of rf "
                         f"{anchor_rf_val * 100:.2f}% and the growth anchor {terminal_g_val * 100:.2f}%) + "
                         f"adjusted loading {adj_load_val:.3f}× (Blume: 0.67 × raw "
                         f"{raw_load_val:.3f} + 0.33) × the market-consistent premium {_clos_erp * 100:.2f}% (rs2 closure, as of "
                         f"{_coe_asof_str})")
        else:
            coe_clause = (f"COE ANCHOR for this name: {NULL} \u2014 the closure premium is missing or stale "
                          f"({_clos_asof or _clos_why})" if _clos_erp is None else f"COE ANCHOR for this name: {NULL}")
        if terminal_g_val is not None:
            _tg_asof = lrg_payload.get("asof") if lrg_payload else None
            tg_clause = f"long-run nominal growth anchor {terminal_g_val * 100:.2f}% (asof {_tg_asof or NULL})"
        else:
            tg_clause = f"long-run nominal growth anchor {NULL} ({terminal_g_src})"
        coe_anchor_line = f"- {coe_clause} | {tg_clause}"

        L += ["## DATA 1.5 - MACRO STATE & COST OF CAPITAL ANCHORS   [MRI anchors as of "
              f"{asof_str}, degraded: {degraded_str}, reasons: {reasons_str}; verified: do not "
              "search the web for them]",
              rates_line,
              coe_anchor_line]
        if terminal_def_line and _rev22:      # revision 24 step 2b: no long-run default is printed (the facts keep it, for the benchmark)
            L.append(terminal_def_line)
        facts["terminal_g_default"] = terminal_def_val   # quantized to the printed two decimals
        _record_facts()
        L += [curve_line, regime_line]
        L.append("")

        macro_degraded = bool(
            rf_pct is None
            or real_pct is None
            or be_pct is None
            or erp_pct is None
            or coe_pct is None
            or anchor_load_val is None
            or t10y2y is None
            or baa10y is None
            or hy_oas is None
            or bool(anchor_degraded)
            or not regime_fresh
        )

        # ---- SECTION 1.6 - STATE OF THE WORLD [dated facts, not a forecast] --------------------
        # D10 (PHASE_4_PACK_SPEC.md) / E3 (AMENDMENTS.md): everything here is a dated fact from the
        # MRI, never a forecast and never invented — a missing source prints NULL/omits its line,
        # it is never defaulted. The WORLD NEWS block below (D10's "news-theme summary", added
        # 2026-09-24) sources differently from the rest of this section: the MRI's local duckdb
        # store carries no news, so it reads the macro repo's `origin/run-history` branch instead,
        # read-only, via world_news.py — see that module's docstring and _world_news_lines above.
        shock_reg = rs2_data.load_json(Path(CONFIG.get("mri_outputs_dir", "")) / "shock_register.json") or {}
        shock_asof = shock_reg.get("asof")

        L16 = ["## DATA 1.6 - STATE OF THE WORLD   [dated facts, not a forecast]", ""]

        # S3 5.10 (C3): the regime vector and the three rate lines duplicated SECTION 1.5's Regime
        # and Rates lines verbatim and are removed here; the shocks, risk flag, inflation trend
        # and world news below are unique to this section and stay.
        shocks = shock_reg.get("shocks") or []
        active_shocks = [s for s in shocks if isinstance(s, dict) and s.get("active")]
        if not shock_reg:
            L16.append(f"- Active shocks (S4 register): {NULL}")
        elif active_shocks:
            for s in active_shocks:
                L16.append(f"- ACTIVE SHOCK: `{s.get('shock_id', NULL)}` | severity "
                          f"{s.get('severity', NULL)} | direction {s.get('direction', NULL)} | onset "
                          f"{s.get('onset_date') or NULL}  (as of {shock_asof or NULL})")
        else:
            L16.append(f"- Active shocks (S4 register): none active  (as of {shock_asof or NULL})")

        risk_flags = shock_reg.get("risk_flags") or []
        evf = next((f for f in risk_flags if isinstance(f, dict)
                   and f.get("id") == "elevated_volatility_ahead"), None)
        if evf is not None:
            evf_state = "ACTIVE" if evf.get("active") else "inactive"
            L16.append(f"- Risk flag `elevated_volatility_ahead`: {evf_state} - "
                      f"{evf.get('meaning') or NULL}  (as of {shock_asof or NULL})")
        else:
            L16.append(f"- Risk flag `elevated_volatility_ahead`: {NULL}")

        _rate_asof = str(anchor_asof) if anchor_asof else NULL

        # Inflation trend — printed ONLY when the anchor itself carries one. Never invented.
        infl = (coc_payload or {}).get("inflation") if coc_payload else None
        if isinstance(infl, dict) and (isinstance(infl.get("cpi_yoy"), (int, float))
                                       or isinstance(infl.get("pce_yoy"), (int, float))):
            parts = []
            if isinstance(infl.get("cpi_yoy"), (int, float)):
                parts.append(f"CPI YoY {infl['cpi_yoy']*100:.2f}%")
            if isinstance(infl.get("pce_yoy"), (int, float)):
                parts.append(f"PCE YoY {infl['pce_yoy']*100:.2f}%")
            L16.append(f"- Inflation trend: {', '.join(parts)}  (as of {_rate_asof})")
        # else: line omitted entirely — the anchor carries no inflation-trend leg this run.

        wn = world_news.digest()
        L16.extend(_world_news_lines(wn, None))

        L16.append("")
        L += L16

    # ---- SECTION 2 -------------------------------------------------------------------------
    L.cls = r26_blind.AGGREGATOR
    asof_price_data = None
    if asof_date is not None:
        # asof mode owns its own price sourcing entirely — any `price_override` the caller
        # passed is not consulted, because it carries no history to recompute SCR-10 from.
        asof_price_data = _asof_price_lookup(t, asof_date)
        if asof_price_data is None:
            asof_omitted.append(
                f"price (DATA 2/2.5): no historical close found on or near "
                f"{asof_date.isoformat()} (network fetch failed or no listing that far back)")
        px = asof_price_data["price"] if asof_price_data else None
        sh = None
        if h:
            _hy_asof = [int(y) for y in h if str(y).isdigit()]
            if _hy_asof:
                sh = (h.get(str(max(_hy_asof))) or {}).get("shares_diluted")
        if sh is None:
            asof_omitted.append(
                "shares outstanding (DATA 2): no shares_diluted held for any allowed fiscal "
                "year — TODAY's vendor share count is not point-in-time and was not used")
        mcap = (px * sh) if (isinstance(px, (int, float)) and isinstance(sh, (int, float))) else None
    else:
        px, sh = fin.get("Price"), fin.get("Shares_Outstanding")

    # Revision 17, brief C4/C5: a split after the last filing (live packs only: a point-in-time pack's count IS the
    # filed one), and the latest filed diluted count on today's share basis, for the share default.
    _split = None if asof_date is not None else _split_after_last_filing(sh, h)
    if _split:
        _split["confirmed"] = _split_confirmed(_split, h, fin, _screener_country(t))
    facts["split_after_last_filing"] = _split["multiplier"] if _split else None
    _filed_series = _filed_diluted_series(h) if h else []
    _filed_today = (_filed_series[-1][1] * _split["multiplier"] if _split else _filed_series[-1][1]) if _filed_series else None

    # D9 (PHASE_4_PACK_SPEC.md): T2's pack-data-sanity checks, printed as a DATA WARNINGS block
    # at the TOP of SECTION 2 — before the figures they warn about, not after. Explicit params,
    # not `ticker=t` alone: this function's own ticker-resolution path reads
    # `rs2_data.CONFIG["screener_data_dir"]` directly, which a test's `cap.SD` monkeypatch does
    # not reach, so passing the values this pack already loaded is what keeps it test-isolated.
    _dsh = sh if isinstance(sh, (int, float)) and sh else None
    if _dsh is None and h:
        _hy = [int(y) for y in h if str(y).isdigit()]
        if _hy:
            _dsh = (h.get(str(max(_hy))) or {}).get("shares_diluted")
    data_warnings = check_pack_data_sanity(
        ticker=t, price=px, market_cap=(mcap if asof_date is not None else fin.get("Market_Cap")),
        diluted_shares=_dsh, ttm_fields=f, quarterly_rows=qs)
    if data_warnings:
        L += ["## DATA WARNINGS   [T2 sanity checks — read before trusting DATA 2's figures]"]
        L += [r26_blind.tag(r26_blind.WARNING_CLASS.get(w["warning"], r26_blind.DERIVED), f"- {w['message']}") for w in data_warnings]
        L.append("")

    # P-2: SHARES ALERT. Live packs only: a point-in-time pack's count IS the filed one, there is no vendor count to differ.
    _shares_gap = None
    if asof_date is None:
        _shares_gap = _shares_gap_state(_filed_today, sh, _shares_cover,
                                        lambda: fin.get("FX") is None and _screener_country(t) == "United States")
    if _shares_gap:
        L += [_shares_alert_text(_shares_gap, _filed_today, _filed_series[-1][0], sh), ""]
    _sd_unusable = bool(_shares_gap and _shares_gap["vendor_unusable"])

    if asof_date is not None:
        price_line = (f"- Price: ${px} [point-in-time close, as of "
                      f"{asof_price_data['asof']}]" if px is not None else f"- Price: {ASOF_NULL}")
        facts["shares_outstanding"] = float(f"{sh:,.0f}".replace(",", "")) if (isinstance(sh, (int, float)) and not isinstance(sh, bool) and not (isinstance(sh, float) and (sh != sh)) and sh >= 0) else None
        # S3 5.11: the share-count default, from the same vendor income statements in every path.
        _sd_default, _sd_k, _sd_period, _sd_warning = _share_default(fin, facts["shares_outstanding"],
                                                                     point_in_time=True)
        facts["shares_default"] = _sd_default
        facts["shares_dilution_factor"] = _sd_k
        facts["shares_dilution_period"] = _sd_period["label"] if _sd_period else None
        facts["shares_warning"] = _sd_warning
        L += [f"## DATA 2 - MARKET   [point-in-time, as of {asof_date.isoformat()}]",
              r26_blind.tag(r26_blind.PRICE, price_line),
              f"- Shares outstanding: {_n(sh)}   [source: shares_diluted, "
              f"FY{max((int(y) for y in h if str(y).isdigit()), default=NULL)} "
              f"(fundamentals_history.json) — the most recent allowed fiscal year, not TODAY's "
              f"vendor share count]" if sh is not None else f"- Shares outstanding: {ASOF_NULL}"]
        L += [r26_blind.tag(r26_blind.DERIVED, x) for x in _share_default_lines(facts["shares_outstanding"], _sd_default, _sd_k, _sd_period, _sd_warning,
                                                                              point_in_time=True)]
        # revision 20 (brief 1.4): the per-share check's two figures when the identity fails (annotation; the reference is still printed)
        if _ps["status"] == "unverified":
            L.append(input_scope.per_share_data_line(_ps))
        L += [r26_blind.tag(r26_blind.MARKET_CAP, f"- Market cap: {_b(mcap) if mcap is not None else ASOF_NULL}"),
              f"- Beta: {ASOF_NULL}   [same-day vendor snapshot, no stored history]",
              "",
              f"- Total cash (vendor): {ASOF_NULL}   [same-day vendor snapshot; see DATA 6 for "
              f"the filed, fiscal-year-restricted `cash` series]",
              f"- Total debt (vendor): {ASOF_NULL}   [same-day vendor snapshot; see DATA 6 for "
              f"the filed, fiscal-year-restricted `long-term debt` series]",
              f"- Stock-based compensation (vendor): {ASOF_NULL}   [same-day vendor snapshot; "
              f"prefer the filed per-year SBC series in DATA 5]", ""]
    elif price_override is not None:
        if isinstance(price_override, dict):
            live_px = price_override.get("price")
            live_asof = price_override.get("asof")
        else:
            live_px = float(price_override)
            live_asof = None
        asof_str = f", as of {live_asof}" if live_asof else ""
        _pack_price = live_px
        vdate = _v(fin, 'Data_Fetched_Date')
        vpx = f"${px}" if px is not None else NULL
        price_line = f"- Price: ${live_px} [live quote{asof_str}]   [vendor quote: {vpx} as of {vdate}]"
        facts["shares_outstanding"] = float(f"{sh:,.0f}".replace(",", "")) if (isinstance(sh, (int, float)) and not isinstance(sh, bool) and not (isinstance(sh, float) and (sh != sh)) and sh >= 0) else None
        # S3 5.11: the share-count default, from the same vendor income statements in every path.
        _sd_default, _sd_k, _sd_period, _sd_warning = _share_default(fin, facts["shares_outstanding"],
                                                                     filed_diluted=_filed_today,
                                                                     vendor_unusable=_sd_unusable)
        facts["shares_default"] = _sd_default
        facts["shares_dilution_factor"] = _sd_k
        facts["shares_dilution_period"] = _sd_period["label"] if _sd_period else None
        facts["shares_warning"] = _sd_warning
        L += [f"## DATA 2 - MARKET   [Aggregator - vendor quote as of {_v(fin, 'Data_Fetched_Date')}]",
              r26_blind.tag(r26_blind.PRICE, price_line),
              f"- Shares outstanding: {_n(sh)}   [source: vendor financials, as of "
              f"{_v(fin, 'Data_Fetched_Date')}]"
              + ("   <- ZERO on file. No per-share value is derivable for this name."
                 if sh == 0 else "")]
        L += [r26_blind.tag(r26_blind.DERIVED, x) for x in _share_default_lines(facts["shares_outstanding"], _sd_default, _sd_k, _sd_period, _sd_warning)]
        # revision 20 (brief 1.4): the per-share check's two figures when the identity fails (annotation; the reference is still printed)
        if _ps["status"] == "unverified":
            L.append(input_scope.per_share_data_line(_ps))
        L += [r26_blind.tag(r26_blind.MARKET_CAP, f"- Market cap: {_b(fin.get('Market_Cap'))}"),
              f"- Beta: {_v(cm, 'Beta')}   [Aggregator - the vendor does not state its window or "
              f"benchmark. No RS2 code consumes beta; it is here only if you want to build your own "
              f"cost of equity.]",
              "",
              "**The three figures below are the VENDOR's restatement of the last annual report - not "
              "live, and not our SEC extract. The filed series is in DATA 6.**",
              f"- Total cash (vendor): {_b(fin.get('Total_Cash'))}",
              f"- Total debt (vendor): {_b(fin.get('Total_Debt'))}   [our filed extract maps LONG-TERM "
              f"debt only, so the two legitimately differ - and neither is a complete debt figure]",
              f"- Stock-based compensation (vendor): {_b(fin.get('SBC_Stock_Based_Comp'))}   [the "
              f"period is NOT reliably trailing-twelve-months; on most names it is a fiscal year. "
              f"Prefer the filed per-year SBC series in DATA 5 where it is present]", ""]
    else:
        price_line = f"- Price: ${px}" if px is not None else f"- Price: {NULL}"
        _pack_price = px
        facts["shares_outstanding"] = float(f"{sh:,.0f}".replace(",", "")) if (isinstance(sh, (int, float)) and not isinstance(sh, bool) and not (isinstance(sh, float) and (sh != sh)) and sh >= 0) else None
        # S3 5.11: the share-count default, from the same vendor income statements in every path.
        _sd_default, _sd_k, _sd_period, _sd_warning = _share_default(fin, facts["shares_outstanding"],
                                                                     filed_diluted=_filed_today,
                                                                     vendor_unusable=_sd_unusable)
        facts["shares_default"] = _sd_default
        facts["shares_dilution_factor"] = _sd_k
        facts["shares_dilution_period"] = _sd_period["label"] if _sd_period else None
        facts["shares_warning"] = _sd_warning
        L += [f"## DATA 2 - MARKET   [Aggregator - vendor quote as of {_v(fin, 'Data_Fetched_Date')}]",
              r26_blind.tag(r26_blind.PRICE, price_line),
              f"- Shares outstanding: {_n(sh)}   [source: vendor financials, as of "
              f"{_v(fin, 'Data_Fetched_Date')}]"
              + ("   <- ZERO on file. No per-share value is derivable for this name."
                 if sh == 0 else "")]
        L += [r26_blind.tag(r26_blind.DERIVED, x) for x in _share_default_lines(facts["shares_outstanding"], _sd_default, _sd_k, _sd_period, _sd_warning)]
        # revision 20 (brief 1.4): the per-share check's two figures when the identity fails (annotation; the reference is still printed)
        if _ps["status"] == "unverified":
            L.append(input_scope.per_share_data_line(_ps))
        L += [r26_blind.tag(r26_blind.MARKET_CAP, f"- Market cap: {_b(fin.get('Market_Cap'))}"),
              f"- Beta: {_v(cm, 'Beta')}   [Aggregator - the vendor does not state its window or "
              f"benchmark. No RS2 code consumes beta; it is here only if you want to build your own "
              f"cost of equity.]",
              "",
              "**The three figures below are the VENDOR's restatement of the last annual report - not "
              "live, and not our SEC extract. The filed series is in DATA 6.**",
              f"- Total cash (vendor): {_b(fin.get('Total_Cash'))}",
              f"- Total debt (vendor): {_b(fin.get('Total_Debt'))}   [our filed extract maps LONG-TERM "
              f"debt only, so the two legitimately differ - and neither is a complete debt figure]",
              f"- Stock-based compensation (vendor): {_b(fin.get('SBC_Stock_Based_Comp'))}   [the "
              f"period is NOT reliably trailing-twelve-months; on most names it is a fiscal year. "
              f"Prefer the filed per-year SBC series in DATA 5 where it is present]", ""]

    # ---- SECTION 2.5 - PRICE ACTION (facts, not a valuation input)   [P4.1, amended by B1] ---
    L.cls = r26_blind.PRICE_ACTION
    if asof_date is not None:
        # D10/E4.3: recomputed directly from historical closes ending at `asof`, never from
        # factor_scores.json (a same-day snapshot with no history).
        scr10 = (_scr10_from_series(asof_price_data["series"], asof_date.isoformat())
                 if asof_price_data else {})

        def _mpct(v):
            return f"{v*100:+.1f}%" if isinstance(v, (int, float)) else ASOF_NULL

        L += [f"## DATA 2.5 - PRICE ACTION (facts, not a valuation input)   [recomputed from "
              f"historical closes, as of {asof_date.isoformat()}]",
              f"- 12-1 month return: {_mpct(scr10.get('mom_12_1'))}",
              f"- 6-month return: {_mpct(scr10.get('mom_6m'))}",
              f"- 1-month return: {_mpct(scr10.get('mom_1m'))}",
              f"- Distance from 52-week high (daily, recomputed): "
              f"{_mpct(scr10.get('high_52w_distance'))}",
              f"- Above/below 200-day mean, and its slope: {ASOF_NULL}",
              f"- Relative strength vs cluster ETF, 3-month: {ASOF_NULL}",
              f"- Relative strength vs IWM, 3-month: {ASOF_NULL}",
              f"- Realised volatility, 60-day: {ASOF_NULL}",
              f"- Regime-shift flags: {ASOF_NULL} (factor_scores.json is a same-day snapshot)",
              f"- mom_break: {ASOF_NULL}",
              f"- Sector-neutral momentum z: {ASOF_NULL}",
              f"- Universe momentum z: {ASOF_NULL}",
              "",
              "These are facts about price and are not a valuation input.", ""]
        LAST_PACK_MOMENTUM_STATE = {
            "price_asof": scr10.get("price_asof"),
            "mom_12_1": scr10.get("mom_12_1"), "mom_6m": scr10.get("mom_6m"),
            "mom_1m": scr10.get("mom_1m"),
            "high_52w_distance": scr10.get("high_52w_distance"),
            "high_52w_basis": scr10.get("high_52w_basis"),
            "above_below_200d_mean": None, "rs_vs_cluster_etf_3m": None, "rs_vs_iwm_3m": None,
            "realised_vol_60d": None, "regime_shift_up": None, "regime_shift_down": None,
            "mom_break": None, "mom_z_sector": None, "mom_z_universe": None,
        }
        LAST_PACK_ACTIVE_SHOCKS = (rs2_data.asof_shock_register(asof_date) or {}).get("shocks", [])
    else:
        # Reads ONLY the price-fact fields off factor_scores.json's per-ticker
        # `fct_momentum_state` / `fct_z` — never `fct_band`, `fct_rank`, `fct_composite`,
        # `fct_nominated_doors` or `falling_knife_detail`. Those are the screener's own opinion,
        # and B1's decision is that the analyst must never see it here: showing "research_now,
        # rank 3" invites the analyst to agree, which erodes the independent second opinion the
        # divergence engine exists to record.
        fs_all = rs2_data.load_json(SD / "factor_scores.json") or {}
        fs_row = (fs_all.get("tickers") or {}).get(t) or {}
        mom = fs_row.get("fct_momentum_state") or {}
        fs_flags = fs_row.get("fct_flags") or []
        fs_z = fs_row.get("fct_z") or {}
        price_asof_25 = _v(fin, "Data_Fetched_Date")

        def _mpct(v):
            return f"{v*100:+.1f}%" if isinstance(v, (int, float)) else NULL

        def _mz(v):
            return f"{v:+.3f}" if isinstance(v, (int, float)) else NULL

        # `momentum_proxy_monthly` (fct_flags) is the screener's own marker that `high_52w_proxy`
        # is a MONTHLY proxy rather than a daily reading — the only granularity our momentum
        # source currently carries. A `high_52w` daily field (absent today) would take priority.
        if "high_52w" in mom:
            high52_val, high52_label = mom.get("high_52w"), "daily"
        else:
            high52_val = mom.get("high_52w_proxy")
            high52_label = ("monthly proxy" if "momentum_proxy_monthly" in fs_flags
                            else "monthly proxy (unlabelled by the source)")
        shifts = [lbl for lbl, key in (("regime_shift_up", "regime_shift_up"),
                                       ("regime_shift_down", "regime_shift_down"))
                 if mom.get(key)]
        L += [f"## DATA 2.5 - PRICE ACTION (facts, not a valuation input)   [Arithmetic on price "
              f"history, as of {price_asof_25}]",
              f"- 12-1 month return: {_mpct(mom.get('mom_12_1'))}",
              f"- 6-month return: {_mpct(mom.get('mom_6m'))}",
              f"- 1-month return: {_mpct(mom.get('mom_1m'))}",
              f"- Distance from 52-week high ({high52_label}): {_mpct(high52_val)}",
              f"- Above/below 200-day mean, and its slope: {NULL}",
              f"- Relative strength vs cluster ETF, 3-month: {NULL}",
              f"- Relative strength vs IWM, 3-month: {NULL}",
              f"- Realised volatility, 60-day: {NULL}",
              f"- Regime-shift flags: {', '.join(shifts) if shifts else 'none'}",
              f"- mom_break: {NULL}",
              f"- Sector-neutral momentum z: {_mz(mom.get('mom_z_sector'))}",
              f"- Universe momentum z: {_mz(fs_z.get('momentum'))}",
              "",
              "These are facts about price and are not a valuation input.", ""]

    if asof_date is None:
        # Rule 11 (verdict stamping): the exact §2.5 block this pack printed, for
        # consensus_valuation.main() to copy onto consensus.json as `momentum_state`. (asof mode
        # sets both globals itself, inside the branch above, from the recomputed SCR-10 facts.
        # `global` for both names is declared once, at the top of this function — see there for
        # why: two `global X` statements either side of X's first assignment raise a SyntaxError
        # even when each is individually valid for its own branch.)
        LAST_PACK_MOMENTUM_STATE = {
            "price_asof": price_asof_25,
            "mom_12_1": mom.get("mom_12_1"), "mom_6m": mom.get("mom_6m"),
            "mom_1m": mom.get("mom_1m"),
            "high_52w_distance": high52_val, "high_52w_basis": high52_label,
            "above_below_200d_mean": None, "rs_vs_cluster_etf_3m": None, "rs_vs_iwm_3m": None,
            "realised_vol_60d": None,
            "regime_shift_up": bool(mom.get("regime_shift_up")) if "regime_shift_up" in mom else None,
            "regime_shift_down": bool(mom.get("regime_shift_down")) if "regime_shift_down" in mom else None,
            "mom_break": None,
            "mom_z_sector": mom.get("mom_z_sector"), "mom_z_universe": fs_z.get("momentum"),
        }
        LAST_PACK_ACTIVE_SHOCKS = active_shocks

    # ---- RECENT COMPANY NEWS   [Item 2] ----------------------------------------------------
    L.cls = r26_blind.NARRATIVE
    if asof_date is not None:
        L += ["## RECENT COMPANY NEWS   [not available (point-in-time) \u2014 the news search cannot be restricted to the briefing date]",
              ""]
    else:
        company_for_news = rs2_data.resolve_name(t) or t
        cnews = company_news.fetch(company_for_news, t)
        cnews_date = cnews.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        m1 = LAST_PACK_MOMENTUM_STATE.get("mom_1m") if LAST_PACK_MOMENTUM_STATE else None
        m6 = LAST_PACK_MOMENTUM_STATE.get("mom_6m") if LAST_PACK_MOMENTUM_STATE else None
        mom_1m_str = f"{m1*100:+.1f}%" if isinstance(m1, (int, float)) else NULL
        mom_6m_str = f"{m6*100:+.1f}%" if isinstance(m6, (int, float)) else NULL
        L += [f"## RECENT COMPANY NEWS   [SearXNG news search (Reuters, Bing News), last 30 days, fetched {cnews_date}; third-party claims \u2014 the five most recent carry their opening text, read by code from the page shown after the arrow]",
              r26_blind.tag(r26_blind.PRICE, f"- The stock moved {mom_1m_str} in 1 month and {mom_6m_str} in 6 months (DATA 2.5).")]
        news_rows = cnews.get("rows") or []
        not_naming = cnews.get("rows_not_naming", 0)     # rows the search returned whose headline did not name the company
        if news_rows:
            for nr in news_rows:
                d_str = nr.get("date") or "undated"
                src = nr.get("source") or "unknown"
                tit = nr.get("title") or ""
                u = nr.get("url") or ""
                snip = nr.get("snippet") or ""
                # S3 5.8 (C1): a row with no excerpt drops its snippet, unless news_snippets=True
                # (catalyst_research.discovery_context, so the discovery run's input stays
                # byte-identical to revision 14's). No row is removed.
                if news_snippets or nr.get("excerpt"):
                    L.append(f"- {d_str} | {src} | {tit} | {u} | {snip}")
                else:
                    L.append(f"- {d_str} | {src} | {tit} | {u}")
                if nr.get("excerpt"):
                    _rf = urllib.parse.urlparse(nr.get("read_from") or u).hostname or "?"
                    L.append(f"  > read from {_rf[4:] if _rf.startswith('www.') else _rf}: {nr['excerpt']}")
            if not_naming > 0:
                L.append(f"- {not_naming} more rows from the search do not name the company in the headline; not shown.")
        elif not_naming > 0:
            L.append(f"- no row names the company in its headline ({not_naming} returned by the search; none shown)")
        else:
            unresp = cnews.get("unresponsive_engines") or []
            errs = cnews.get("errors") or []
            details = []
            if unresp:
                details.append(f"unresponsive engines: {', '.join(unresp)}")
            if errs:
                details.append(f"errors: {'; '.join(errs)}")
            L.append(f"- no news returned ({'; '.join(details)})" if details else "- no news returned")
        L.append("")

    # ---- CATALYST BRIEF   [Phase 4 E9] ----------------------------------------------
    if asof_date is not None:
        L += ["## CATALYST BRIEF   [not available (point-in-time) — the discovery run searches today's web]",
              ""]
    else:
        brief_today = catalyst_research.get_cached_brief(t)
        if brief_today is not None:
            L += catalyst_research.render(brief_today)
        else:
            L += ["## CATALYST BRIEF   [not available — no discovery run today]"]
        L.append("")

    # ---- SECTION 3 -------------------------------------------------------------------------
    L.cls = r26_blind.FILED
    # S3 5.6: one typed line (Revenue | net income | ...), bare numbers, unit stated once in the
    # header.
    if asof_date is not None:
        L.append(f"## DATA 3 - TRAILING TWELVE MONTHS   [point-in-time: revenue/net income "
                 f"recomputed from the 4 trailing allowed quarters; $B]")
        if asof_ttm_recomputed:
            L.append(f"- Revenue {_bn(asof_ttm_recomputed['revenue'])} (Arithmetic, sum of the 4 "
                     f"quarters through {asof_ttm_recomputed['through']}) | net income "
                     f"{_bn(asof_ttm_recomputed['net_income'])} (same window) | operating cash "
                     f"flow {ASOF_NULL} | capital expenditure {ASOF_NULL} | free cash flow "
                     f"{ASOF_NULL} | D&A: not carried in the TTM extract for any name")
        else:
            L.append(f"{ASOF_NULL} - fewer than 4 quarters end on or before "
                     f"{asof_cutoff.isoformat()}.")

        hy = [int(y) for y in h if str(y).isdigit()] if h else []
        latest_yr = max(hy) if hy else None
        da = (h.get(str(latest_yr)) or {}).get("da") if latest_yr is not None else None
        ni = asof_ttm_recomputed.get("net_income") if asof_ttm_recomputed else None
        capex = asof_ttm_recomputed.get("capex") if asof_ttm_recomputed else None
        ocf = asof_ttm_recomputed.get("ocf") if asof_ttm_recomputed else None

        if isinstance(ni, (int, float)) and isinstance(da, (int, float)) and isinstance(capex, (int, float)):
            # revision 20 (brief 1.3(b)): net income is the company's own; D&A and capex are attributed by pi
            oe = _attributed_owner_earnings(ni, da, capex, _pi)
            _ref_oe = oe
            _ref_da, _ref_capex = da, capex
            # revision 17: the base window's net income over its owner earnings, for a desk with no
            # consensus reference (the long run then takes earnings from owner earnings at this ratio)
            if ni > 0 and oe > 0:
                _lr_raw["ni_over_oe"] = ni / oe
                _lr_raw["x_over_oe"] = _x_over_owner_earnings(ni, oe, _attributed_row(h.get(str(latest_yr)), _pi), _untagged_fields)
            facts["owner_earnings_source"] = "ttm_filed"
            facts["owner_earnings_default_b"] = float(f"{oe / 1e9:,.3f}".replace(",", ""))
            # S3 5.6/5.3: result-first equation, bare numbers; the "equity frame" rule sentence is
            # gone (it lives in the DEFAULTS block's owner_earnings_default_b explanation now).
            _lv = _oe_levels(f"D&A (FY{latest_yr}) {_bn(da)} \u2212 TTM capex {_bn(capex)}", _pi)
            L.append(f"- [Arithmetic] OWNER EARNINGS {_bn(oe)} = TTM net income {_bn(ni)} + {_lv}. Stock compensation is already expensed in net income, so it is counted once (sbc_treatment \"deducted_in_cf\"); working-capital swings are excluded.")
            if isinstance(ocf, (int, float)):
                denom = ni + da
                gap = ocf - denom
                if denom > 0 and gap > 0 and (gap / denom) > 0.25:
                    pct = (gap / denom) * 100.0
                    L.append(f"- CASH-FLOW QUALITY: TTM operating cash flow exceeds net income + D&A by {_b(gap)} ({round(pct):.0f}%). That gap is working capital \u2014 customer prepayments, deposits or collection timing. It recurs only while advance bookings keep growing: count it as recurring owner cash flow only if you show it is structural to the business (deposits that grow with bookings), and never extrapolate a one-off swing. A base built on TTM OCF or FCF (including the CASH BASIS line) includes it; the OWNER EARNINGS default does not.")
        else:
            missing = []
            if not isinstance(ni, (int, float)):
                missing.append("TTM net income")
            if not isinstance(da, (int, float)):
                missing.append("D&A")
            if not isinstance(capex, (int, float)):
                missing.append("TTM capex")
            missing_str = ", ".join(missing)
            facts["owner_earnings_source"] = None
            facts["owner_earnings_default_b"] = None
            L.append(f"- OWNER EARNINGS: not available (point-in-time) \u2014 {missing_str} missing")
        if latest_yr is not None:
            latest_rec = h.get(str(latest_yr)) or {}
            fy_oi = latest_rec.get("operating_income")
            fy_ni = latest_rec.get("net_income")
            if isinstance(fy_oi, (int, float)) and isinstance(fy_ni, (int, float)):
                if fy_oi > 0 and fy_ni > fy_oi:
                    L.append(
                        f"- EARNINGS QUALITY: in FY{latest_yr} net income ({_b(fy_ni)}) exceeded operating income ({_b(fy_oi)}) \u2014 non-operating gains, tax benefits or discontinued operations; recurring items (interest earned on cash, equity-method income) are real owner earnings, so keep the OWNER EARNINGS default for them. Only a one-off (a gain on a sale, a tax-allowance release, discontinued operations) inflates it: find it in the filings, subtract that amount from the default and state it in base_cf_reason. Do not switch to an older fiscal year or to another base because of this line alone."
                    )
                elif fy_oi <= 0 and fy_ni > 0:
                    L.append(
                        f"- EARNINGS QUALITY: in FY{latest_yr} net income ({_b(fy_ni)}) was positive while operating income was not ({_b(fy_oi)}) \u2014 non-operating gains, tax benefits or discontinued operations; recurring items (interest earned on cash, equity-method income) are real owner earnings, so keep the OWNER EARNINGS default for them. Only a one-off (a gain on a sale, a tax-allowance release, discontinued operations) inflates it: find it in the filings, subtract that amount from the default and state it in base_cf_reason. Do not switch to an older fiscal year or to another base because of this line alone."
                    )
        L.append("")
    else:
        # S3 5.6: one typed line (Revenue | net income | ...), bare numbers, unit stated once in
        # the header.
        L.append(f"## DATA 3 - TRAILING TWELVE MONTHS   [Filed - SEC 10-Q derived; through "
                 f"{_v(ttm, 'through')}, filed {_v(ttm, 'filed')}; $B]")
        if f:
            _l3 = (f"- Revenue {_bn(f.get('revenue'))} | net income {_bn(f.get('net_income'))} | "
                  f"operating cash flow {_bn(f.get('ocf'))} | capital expenditure "
                  f"{_bn(f.get('capex'))} | free cash flow {_bn(f.get('fcf'))}")
            ni, ocf = f.get("net_income"), f.get("ocf")
            if isinstance(ni, (int, float)) and isinstance(ocf, (int, float)):
                _l3 += f" | [Arithmetic] net income minus operating cash flow {_bn(ni - ocf)}"
            _l3 += " | D&A: not carried in the TTM extract for any name; use DATA 5"
            L.append(_l3)
        elif ttm_stale:
            L.append(f"{NULL} - our TTM record for this name is STRANDED: its fiscal anchor "
                     f"({ttm.get('fy_leg_end')}) disagrees with the newest annual year we hold "
                     f"({max(_yrs)}), so it is not this company's trailing twelve months and has been "
                     f"withheld rather than shown with a wrong period label. Use DATA 5.")
        else:
            L.append(f"{NULL} - no TTM record. 20-F and 40-F filers file no 10-Q, so no TTM is "
                     f"derivable for them from this source.")

        hy = [int(y) for y in h if str(y).isdigit()] if h else []
        latest_yr = max(hy) if hy else None
        da = (h.get(str(latest_yr)) or {}).get("da") if latest_yr is not None else None
        ni = f.get("net_income") if f else None
        capex = f.get("capex") if f else None
        ocf = f.get("ocf") if f else None
        # E14 (2026-09-25): labelled fallbacks, so 20-F/40-F filers (no TTM) and companies whose
        # capex tag our filed extract does not map (oil-and-gas and IFRS capex) still get a default
        # base and SECTION 8's reference. Live path only: the vendor figure is today's.
        ni_src, capex_src = "TTM net income", "TTM capex"
        oe_src = ["ttm", "ttm"]
        _fy_rec = (h.get(str(latest_yr)) or {}) if latest_yr is not None else {}
        # Review B3/B1 (2026-09-27): the fiscal year end (TTM record, else the vendor's dated
        # statements, the matching net income confirming the label year), and whether the vendor's
        # capex may stand in for a filed one
        # revision 18: the E18 base, its fiscal year end, the vintage test and the vendor-capex test are `_fiscal_year_base`'s
        # (one copy, also read by `reference_inputs`)
        _fyb = _fiscal_year_base(t, h, fin, ttm, f, ttm_stale, en.get("estimates") if en else None, _untagged_fields,
                                 datetime.now().date())
        _fye_src, _fye_conflict, _fy_end_dt = _fyb["fye_src"], _fyb["fye_conflict"], _fyb["fy_end_dt"]
        _ven_capex_ok, _ven_capex_why = _fyb["ven_capex_ok"], _fyb["ven_capex_why"]
        if not isinstance(ni, (int, float)) and isinstance(_fy_rec.get("net_income"), (int, float)):
            ni, ni_src, oe_src[0] = _fy_rec["net_income"], f"FY{latest_yr} net income (no TTM held)", "fy"
        if not isinstance(capex, (int, float)):
            _ven_capex = fin.get("Capital_Expenditure")
            if isinstance(_fy_rec.get("capex"), (int, float)):
                capex, capex_src, oe_src[1] = _fy_rec["capex"], f"FY{latest_yr} capex (no TTM capex held)", "fy"
            elif isinstance(_ven_capex, (int, float)) and _ven_capex < 0 and _ven_capex_ok:
                # yfinance reports capex as a negative cash flow (FCF = OCF + capex). A positive
                # figure would mean that convention changed under us, so it is refused.
                capex, oe_src[1] = -float(_ven_capex), "vendor"
                capex_src = (f"vendor latest-annual capex (financials, fetched "
                             f"{str(fin.get('Data_Fetched_Date') or NULL)[:10]}; our filed extract maps no "
                             f"capex tag for this company)")
        # Stamped on every verdict (owner_earnings_source); printed only when a fallback was used,
        # so a pack built from TTM inputs is byte-identical to revision 9's.
        oe_tag = ("" if oe_src == ["ttm", "ttm"]
                  else f" (owner_earnings_source: {oe_src[0]}_ni+{oe_src[1]}_capex)")
        # E18: the CONSENSUS-IMPLIED VALUE's base is the last full fiscal year, the period consensus growth is measured from,
        # valued at that year end and rolled forward to today (`_fiscal_year_base`)
        if latest_yr is not None:
            _stub, _aligned, _thr = _fyb["stub"], _fyb["aligned"], _fyb["thr"]
            _ref_fy, _ref_fy_na = _fyb["ref_fy"], _fyb["ref_fy_na"]
            if _ref_fy is not None:
                # the FY and TTM windows are compared only when the TTM is this fiscal year's own
                if f and _thr is not None and not ttm_stale and oe_src == ["ttm", "ttm"]:
                    _ref_fy["quarters"] = max(0, round((_thr - _fy_end_dt).days / 30.4375 / 3))
                    _ref_fy["through"] = _thr.isoformat()
                # revision 17: the desk values at the base fiscal year end and rolls forward by this age
                _lr_raw["stub_months"] = _stub
            # revision 18 (brief 1.3): cash at face for a non-financial company (`_cash_term_for`)
            # revision 20 (brief 1.3(b)): the cash term's cash and interest, and the desk's cash bound, are attributed by pi
            _cash = input_scope.attribute_cash(_cash_term_for(_fy_rec, sector, _fye_src, _fye_conflict, _fy_end_dt), _pi)
            # revision 19 (AT10 fix item 3): the bound the desk holds an excess_cash to, for every sector
            _cash_bound = input_scope.attribute_amount(consensus_reference.cash_and_investments(_fy_rec), _pi)
            if _cash_bound is not None:
                facts["base_year_cash_and_investments_b"] = pack_facts.q_b(_cash_bound / 1e9)
            if _cash["applies"]:
                facts["excess_cash"] = pack_facts.q_b(_cash["cash"] / 1e9)
            elif _cash["financial"]:
                facts["excess_cash"] = 0.0
            _cash_stamps = [x for x in _cash["stamps"] if x.startswith("cash_term")]
            if _cash_stamps:
                for _sk in ("stamps", "stamps_full"):
                    _lr_raw[_sk] = list(_lr_raw.get(_sk) or []) + _cash_stamps

        # revision 18: the after-tax interest on the cash is out of the earnings the Base and the reference capitalise
        _i_cash = _cash["interest"] if (_cash and _cash["applies"]) else 0.0
        if isinstance(ni, (int, float)) and isinstance(da, (int, float)) and isinstance(capex, (int, float)):
            # revision 20 (brief 1.3(b)): net income is the company's own; D&A and capex are attributed by pi (the TTM window, too)
            oe = _attributed_owner_earnings(ni, da, capex, _pi)
            _ref_oe = oe
            _ref_da, _ref_capex = da, capex
            # revision 17: the base window's net income over its owner earnings, for a desk with no
            # consensus reference (the long run then takes earnings from owner earnings at this ratio)
            if ni - _i_cash > 0 and oe - _i_cash > 0:
                _lr_raw["ni_over_oe"] = (ni - _i_cash) / (oe - _i_cash)
                _lr_raw["x_over_oe"] = _x_over_owner_earnings(ni - _i_cash, oe - _i_cash, _attributed_row(_fy_rec, _pi), _untagged_fields)
            facts["owner_earnings_source"] = f"{oe_src[0]}_ni+{oe_src[1]}_capex" if oe_tag else "ttm_filed"
            facts["owner_earnings_default_b"] = float(f"{(oe - _i_cash) / 1e9:,.3f}".replace(",", ""))
            # S3 5.6/5.3: result-first equation, bare numbers; the "equity frame" sentence (OWNER
            # EARNINGS) and the base_cf_basis sentence (CASH BASIS) are gone \u2014 those rules live in
            # the DEFAULTS block now.
            _lv = _oe_levels(f"D&A (FY{latest_yr}) {_bn(da)} \u2212 {capex_src} {_bn(capex)}", _pi)
            L.append(f"- [Arithmetic] OWNER EARNINGS {_bn(oe)}{oe_tag} = {ni_src} {_bn(ni)} + {_lv}. Stock compensation is already expensed in net income, so it is counted once (sbc_treatment \"deducted_in_cf\"); working-capital swings are excluded.")
            _sbc_fy = (h.get(str(latest_yr)) or {}).get("sbc") if latest_yr is not None else None
            if isinstance(ocf, (int, float)) and isinstance(_sbc_fy, (int, float)):
                _cash_basis = ocf - capex - _sbc_fy
                facts["cash_basis_b"] = float(f"{_cash_basis / 1e9:,.3f}".replace(",", ""))
                L.append(f"- [Arithmetic] CASH BASIS {_bn(_cash_basis)} = TTM operating cash flow {_bn(ocf)} \u2212 {capex_src} {_bn(capex)} \u2212 stock compensation (FY{latest_yr}) {_bn(_sbc_fy)}. Includes working-capital swings.")
            if isinstance(ocf, (int, float)):
                denom = ni + da
                gap = ocf - denom
                if denom > 0 and gap > 0 and (gap / denom) > 0.25:
                    pct = (gap / denom) * 100.0
                    L.append(f"- CASH-FLOW QUALITY: TTM operating cash flow exceeds net income + D&A by {_b(gap)} ({round(pct):.0f}%). That gap is working capital \u2014 customer prepayments, deposits or collection timing. It recurs only while advance bookings keep growing: count it as recurring owner cash flow only if you show it is structural to the business (deposits that grow with bookings), and never extrapolate a one-off swing. A base built on TTM OCF or FCF (including the CASH BASIS line) includes it; the OWNER EARNINGS default does not.")
        else:
            missing = []
            if not isinstance(ni, (int, float)):
                missing.append("TTM net income")
            if not isinstance(da, (int, float)):
                missing.append("D&A")
            if not isinstance(capex, (int, float)):
                missing.append("TTM capex")
            missing_str = ", ".join(missing)
            _vc_x = fin.get("Capital_Expenditure")
            if (not isinstance(capex, (int, float)) and not _ven_capex_ok and isinstance(_vc_x, (int, float))
                    and _vc_x < 0):
                missing_str += f" (the vendor's capex is not used: {_ven_capex_why})"
            facts["owner_earnings_source"] = None
            facts["owner_earnings_default_b"] = None
            L.append(f"- OWNER EARNINGS: not available \u2014 {missing_str} missing; declare your base and why.")
        if latest_yr is not None:
            latest_rec = h.get(str(latest_yr)) or {}
            fy_oi = latest_rec.get("operating_income")
            fy_ni = latest_rec.get("net_income")
            if isinstance(fy_oi, (int, float)) and isinstance(fy_ni, (int, float)):
                if fy_oi > 0 and fy_ni > fy_oi:
                    L.append(
                        f"- EARNINGS QUALITY: in FY{latest_yr} net income ({_b(fy_ni)}) exceeded operating income ({_b(fy_oi)}) \u2014 non-operating gains, tax benefits or discontinued operations; recurring items (interest earned on cash, equity-method income) are real owner earnings, so keep the OWNER EARNINGS default for them. Only a one-off (a gain on a sale, a tax-allowance release, discontinued operations) inflates it: find it in the filings, subtract that amount from the default and state it in base_cf_reason. Do not switch to an older fiscal year or to another base because of this line alone."
                    )
                elif fy_oi <= 0 and fy_ni > 0:
                    L.append(
                        f"- EARNINGS QUALITY: in FY{latest_yr} net income ({_b(fy_ni)}) was positive while operating income was not ({_b(fy_oi)}) \u2014 non-operating gains, tax benefits or discontinued operations; recurring items (interest earned on cash, equity-method income) are real owner earnings, so keep the OWNER EARNINGS default for them. Only a one-off (a gain on a sale, a tax-allowance release, discontinued operations) inflates it: find it in the filings, subtract that amount from the default and state it in base_cf_reason. Do not switch to an older fiscal year or to another base because of this line alone."
                    )
        L.append("")

    # ---- SECTION 4 -------------------------------------------------------------------------
    # S3 5.7: the money columns carry the unit once, in the header bracket, as bare numbers (NA
    # for absence) in the table; percent and count cells are unchanged.
    L.append(f"## DATA 4 - QUARTERLY   [Filed - 10-Q; all {len(qs)} quarters we hold, oldest "
             f"first; $B]")
    if qs:
        L += [_row(["period end", "revenue", "net income", "gross profit", "YoY revenue",
                    "YoY net income"]),
              _row(["---"] * 6)]
        for r in qs:
            L.append(_row([str(r.get("end") or NULL), _bn(r.get("revenue")),
                           _bn(r.get("net_income")), _bn(r.get("gross_profit")),
                           _n(r.get("yoy_revenue"), "{:+.1f}%"),
                           _n(r.get("yoy_net_income"), "{:+.1f}%")]))
    else:
        L.append(f"{NULL} - no quarterly record held for this name.")
    L.append("")

    yrs = sorted(int(y) for y in h) if h else []

    # ---- SECTION 5 -------------------------------------------------------------------------
    # S3 5.7: money columns carry the unit once (header bracket), as bare numbers / NA.
    L.append(f"## DATA 5 - FISCAL-YEAR INCOME & CASH FLOW   [Filed - SEC companyfacts; all "
             f"{len(yrs)} years we hold; $B]")
    if yrs:
        # revision 20 (brief 1.3(d)): where the consolidated net income (noncontrolling interests included) differs from the company's own,
        # both are printed
        _ni_both = any(_is_number(h[str(y)].get("net_income_incl_nci")) and h[str(y)].get("net_income_incl_nci") != h[str(y)].get("net_income")
                       for y in yrs)
        _ni_cols = ["net income", "net income incl. NCI"] if _ni_both else ["net income"]
        L += [_row(["FY", "revenue", "gross profit", "operating income"] + _ni_cols + ["OCF",
                    "capex", "FCF", "D&A", "SG&A", "interest expense", "SBC",
                    "cash basis [Arithmetic]"]),
              _row(["---"] * (12 + len(_ni_cols)))]
        for y in yrs:
            r = h[str(y)]
            ie = r.get("interest_expense")
            if isinstance(ie, (int, float)):
                facts["interest_expense_latest_b"] = float(f"{ie / 1e9:,.3f}".replace(",", ""))
            _ni_cells = [_bn(r.get("net_income"))] + ([_bn(r.get("net_income_incl_nci"))] if _ni_both else [])
            L.append(_row([str(y), _bn(r.get("revenue")), _bn(r.get("gross_profit")),
                           _bn(r.get("operating_income"))] + _ni_cells + [
                           _bn(r.get("ocf")), _bn(r.get("capex")), _bn(r.get("fcf")), _bn(r.get("da")),
                           _bn(r.get("sga")), _bn(r.get("interest_expense")), _bn(r.get("sbc")),
                           _bn(owner_cf(r.get("ocf"), r.get("capex"), r.get("sbc")))]))
        if _held(h, yrs, "sbc"):
            L += ["",
                  "- `SBC` is stock-based compensation as filed, per fiscal year. It is a real "
                  "expense that is added back in OCF, so an owner-earnings figure that starts from "
                  "OCF and does not subtract it is overstated. Use this series, not the single "
                  "vendor scalar in DATA 2, whose period is unreliable."]
        L += ["",
              "- `cash basis [Arithmetic]` = OCF minus capex minus SBC, on the filed values in "
              "this table and nothing else. Exact arithmetic, NOT a normalisation, and blank "
              "where any of the three inputs is absent."]
        if _ni_both:
            L.append("- `net income` is the company's own (attributable to its shareholders); `net income incl. NCI` is the consolidated "
                     "figure, the noncontrolling interests' share included.")
        # revision 20 (brief 1.3(d)): the attribution, printed when pi < 1, the base year's scope is derived or unknown, pi is unmeasured,
        # or the record is mixed
        if input_scope.nci_text_due(_nci, _mixed):
            L.append(input_scope.nci_data_line(_nci, _mixed, _b))
        if t in LONE_DEPRECIATION_NAMES:
            L += ["",
                  f"**D&A WARNING for {t}:** this company files no combined depreciation-and-"
                  f"amortisation concept, so every D&A cell above is DEPRECIATION ONLY - admitted "
                  f"here rather than hidden. Intangible amortisation is missing from it. Owner "
                  f"earnings, EBITDA, and any capex-to-D&A ratio built on this column will be "
                  f"understated."]
    else:
        L.append(f"{NULL} - no fiscal-year record held.")
    L.append("")

    _bar_at = len(L)      # revision 26: where DATA 5.1 (the operating-margin bar) is inserted, once the X-basis history is known
    # ---- GROWTH BASE RATES   [D11 / AMENDMENTS.md E2] --------------------------------------
    L.cls = r26_blind.DERIVED
    # Measured fresh from our OWN fundamentals_history.json corpus at pack build (base_rates.py,
    # cached per data-file sha within this run), not a hard-coded snapshot of the one-off
    # measurement the orchestrator published in E2 — this stays current with the corpus.
    latest_rev = h.get(str(max(yrs)), {}).get("revenue") if yrs else None
    size_label, br_table = base_rates.base_rate_table(latest_rev, sd=SD, max_fiscal_year=last_allowed_fy)
    L.append("## GROWTH BASE RATES   [Measured from our own fundamentals_history.json corpus"
            + (f", restricted to fiscal years <= {last_allowed_fy} across the whole corpus "
               "(point-in-time)]" if asof_date is not None else "]"))
    if size_label:
        L.append(f"- Latest annual revenue: {_b(latest_rev)} (FY{max(yrs)})  ->  size bucket "
                 f"{size_label}")
        for hz in (5, 10):
            row = br_table.get(hz)
            if row:
                if hz == 5 and "p90" in row:
                    facts["years35_p90"] = float(br_table[5]["p90"]) / 100.0
                    facts["base_rate_5y"] = {
                        "share_ge_10": float(row["share_ge_10"]),
                        "share_ge_20": float(row["share_ge_20"]),
                        "share_ge_30": float(row["share_ge_30"]),
                        "p50": float(row["p50"]),
                        "p90": float(row["p90"]),
                    }
                L.append(f"- {hz}y sustained growth, this size bucket (n={row['n']}): "
                         f">=10%/yr {row['share_ge_10']}%, >=20%/yr {row['share_ge_20']}%, "
                         f">=30%/yr {row['share_ge_30']}%, median {row['p50']}%, p90 {row['p90']}%")
            else:
                L.append(f"- {hz}y sustained growth, this size bucket: {NULL}")
    else:
        L.append(f"- Latest annual revenue: {_b(latest_rev) if latest_rev is not None else NULL}"
                 f"  -  no usable size bucket for base rates this run.")

    g0 = None
    g_stats = None
    if yrs:
        y_last = max(yrs)
        if (y_last - 1) in yrs:
            rlast = h.get(str(y_last), {}).get("revenue")
            rprev = h.get(str(y_last - 1), {}).get("revenue")
            if isinstance(rlast, (int, float)) and isinstance(rprev, (int, float)) and rprev > 0:
                g0 = rlast / rprev - 1
    if g0 is not None:
        g_lbl, g_stats = growth_persistence.persistence_for_growth(
            g0, sd=SD, max_fiscal_year=last_allowed_fy)
        if g_lbl and g_stats:
            facts["years35_p90"] = float(g_stats["p90"]) / 100.0
            L.append(f"- Given the growth just delivered ({g0*100:+.1f}% YoY revenue, FY{max(yrs)}, "
                     f"bucket {g_lbl}): realized next-5y revenue CAGR across the corpus "
                     f"(n={g_stats['n']}) - p25 {g_stats['p25']}%, median {g_stats['median']}%, "
                     f"p75 {g_stats['p75']}%, p90 {g_stats['p90']}%")
        elif g_lbl:
            L.append(f"- Given the growth just delivered ({g0*100:+.1f}% YoY revenue, bucket "
                     f"{g_lbl}): {NULL} (fewer than 30 corpus observations in this bucket)")
        else:
            L.append(f"- Given the growth just delivered ({g0*100:+.1f}% YoY revenue): outside the "
                     f"measured bucket range (15-25%, 25-40%, 40-70%, >70%) - no conditional table "
                     f"applies.")
    else:
        L.append(f"- Given the growth just delivered: {NULL} (no consecutive-year revenue pair on "
                 f"file)")
    # S3 5.3: the GROWTH BASE RATES **MANDATE** line is removed (years35_p90's rule now lives in
    # the DEFAULTS block); no number was printed on it.
    L += ["- Survivorship caveat: this sample holds only companies that still exist today - failed "
          "and delisted companies are absent - so every rate above is biased upward. Source: our "
          "own screener corpus (fundamentals_history.json), not a published third-party table.",
          ""]

    # ---- SECTION 6 -------------------------------------------------------------------------
    L.cls = r26_blind.FILED
    # S3 5.7: the money tables below (6A, 6B, 6C) carry their $B unit once, in their own header.
    L.append("## DATA 6 - FISCAL-YEAR BALANCE SHEET & CAPITAL STRUCTURE   [Filed, except columns marked [Arithmetic]; $B]")
    if yrs:
        # Unambiguous Net Liquidity Card (prevents column-slip and guessing leverage)
        latest_y = max(yrs)
        lr = h.get(str(latest_y), {})
        cash_val = lr.get("cash") if lr.get("cash") is not None else fin.get("Total_Cash")     # a filed 0.0 is a value
        raw_debt = lr.get("lt_debt")
        vendor_debt = fin.get("Total_Debt")
        effective_debt = raw_debt if (raw_debt is not None and raw_debt > 0) else vendor_debt

        L.append("**EXPLICIT LIQUIDITY & CAPITAL STRUCTURE CARD (Zero-Guess Anchor):**")
        if cash_val is not None:
            # revision 20 (brief 2.3): the cash scope when it is not the unrestricted line, and what the line excludes
            _cn = (input_scope.cash_note(_scope["cash_scope"], _money, _b) if _is_number(lr.get("cash")) else
                   f"the vendor's figure: the filed cash is not resolved, cash_scope {_scope['cash_scope']}"
                   if _scope["cash_scope"] is not None else None)
            L.append(f"- Total Cash & Cash Equivalents: {_b(cash_val)}" + (f" ({_cn})" if _cn else ""))
        if effective_debt is not None:
            L.append(f"- Total Debt (Filed / Vendor): {_b(effective_debt)}")
        sti_val = lr.get("st_investments")
        if cash_val is not None and effective_debt is not None:
            _sti = sti_val if isinstance(sti_val, (int, float)) else 0.0
            net_liq = cash_val + _sti - effective_debt
            net_desc = f"Net Cash +{_b(net_liq)}" if net_liq >= 0 else f"Net Debt {_b(abs(net_liq))}"
            L.append(f"- Net Liquidity Position: **{net_desc}** (Cash + short-term investments minus Total Debt)")
            # E12: one filed figure, used as net_debt in the firm frame (four samples had used four).
            # E13: the equity frame is the default; the firm frame needs a pre-interest flow.
            _sti_txt = _b(sti_val) if isinstance(sti_val, (int, float)) else "$0.000B (none filed)"
            p = float(f"{abs(net_liq) / 1e9:,.3f}".replace(",", ""))
            facts["net_debt_b"] = -p if net_liq > 0 else p
            # S3 5.3: SECTION 6's NET DEBT line drops its rule text (frame instructions now live in
            # the DEFAULTS block and the desk's refusals); every number stays.
            L.append(f"- [Arithmetic] NET DEBT: total debt "
                     f"{_b(effective_debt)} \u2212 cash {_b(cash_val)} \u2212 short-term investments "
                     f"{_sti_txt} = {'-' if net_liq > 0 else ''}{_b(abs(net_liq))} (negative = net cash).")
        L.append("")

        # 6A: Working Capital & Operating Assets (8 columns, clean and focused)
        L.append("### DATA 6A - WORKING CAPITAL & OPERATING ASSETS   [$B]")
        L += [_row(["FY", "total assets", "current assets", "current liabs",
                    "working capital [Arithmetic]", "change in WC [Arithmetic]",
                    "receivables", "inventory"]),
              _row(["---"] * 8)]
        prev_wc = None
        for y in yrs:
            r = h[str(y)]
            ca, cl = r.get("current_assets"), r.get("current_liabilities")
            wc = (ca - cl) if isinstance(ca, (int, float)) and isinstance(cl, (int, float)) else None
            dwc = (wc - prev_wc) if isinstance(wc, (int, float)) and isinstance(prev_wc, (int, float)) else None
            if isinstance(wc, (int, float)):
                prev_wc = wc
            L.append(_row([str(y), _bn(r.get("total_assets")), _bn(ca), _bn(cl), _bn(wc), _bn(dwc),
                           _bn(r.get("receivables")), _bn(r.get("inventory"))]))
        L.append("")

        # 6B: Capital Structure, Debt & Equity (7 columns, clean and distinct from operating assets)
        L.append("### DATA 6B - CAPITAL STRUCTURE, DEBT & EQUITY   [$B]")
        L += [_row(["FY", "cash", "long-term debt", "total liabs",
                    "equity", "retained earnings", "wtd-avg shares"]),
              _row(["---"] * 7)]
        for y in yrs:
            r = h[str(y)]
            y_debt = r.get("lt_debt") if r.get("lt_debt") is not None else (vendor_debt if y == latest_y else None)
            sh_cell = _n(r.get("shares_diluted"))
            if sh_cell != NULL:
                c_clean = sh_cell.replace(",", "").strip()
                if re.match(r"^-?\d+(?:\.\d+)?$", c_clean):
                    facts["filed_shares_diluted"] = float(c_clean)
                    facts["filed_shares_fy"] = y   # yrs holds ints (`sorted(int(y) for y in h)`)
            L.append(_row([str(y), _bn(r.get("cash")), _bn(y_debt),
                           _bn(r.get("total_liabilities")), _bn(r.get("equity")),
                           _bn(r.get("retained_earnings")), sh_cell]))
        L += ["",
              "- `working capital` = current assets minus current liabilities. `change in WC` is "
              "the year-over-year difference of that.",
              "- `long-term debt` is LONG-TERM ONLY; vendor total debt is given in the card above.",
              "- `wtd-avg shares` is the weighted-average share count as filed and is **NOT SPLIT-"
              "ADJUSTED**.",
              "",
              "**WORKING CAPITAL FLOAT & CUSTOMER PREPAYMENT NOTICE:**",
              "- When customers make large advance down-payments or slot reservations (surging contract liabilities/deferred revenue), "
              "operating cash flow (OCF) surges temporarily from working-capital float. Do NOT treat this one-off prepayment float as recurring "
              "owner cash flow. Credit what it secures (capacity lock-in, a service or parts annuity) ONLY where the filings show the "
              "backlog or installed base behind it - cite the filing and the figure (charter v3.1 mandate 2)."]
        L += [x for x in (_share_tag_note(t, h, yrs), _capex_note(t, h, yrs, fin)) if x]
    else:
        L.append(f"{NULL} - no fiscal-year record held.")
    L.append("")

    # ---- SECTION 6C ------------------------------------------------------------------------
    # Added 2026-08-24. Detailed breakdown of debt and liquidity components.
    DEBT_COLS = [("lt_debt", "long-term debt"),
                 ("debt_lt_noncurrent", "LT debt, noncurrent"),
                 ("debt_current", "current portion"),
                 ("short_term_borrowings_separate", "short-term borrowings"),
                 ("finance_lease_liability", "finance leases"),
                 ("operating_lease_liability", "operating leases"),
                 ("borrowings_total", "borrowings total"),
                 ("st_investments", "short-term investments"),
                 ("lt_investments", "long-term investments")]
    present = [(k, lbl) for k, lbl in DEBT_COLS if _held(h, yrs, k)]
    if present:
        L.append("### DATA 6C - DETAILED DEBT COMPONENTS & INVESTMENTS   [Filed. Columns absent for this "
                 "company are omitted entirely rather than shown empty; $B]")
        L += [_row(["FY"] + [lbl for _, lbl in present]), _row(["---"] * (len(present) + 1))]
        for y in yrs:
            r = h[str(y)]
            L.append(_row([str(y)] + [_bn(r.get(k)) for k, _ in present]))
        L += ["",
              "- **WE DO NOT KNOW WHETHER THESE COLUMNS OVERLAP, SO WE DO NOT SUM THEM.** Which "
              "XBRL tag produced each number is not recorded (see DATA 0), and the two "
              "long-term columns are measurably not interchangeable: across the live book they "
              "are identical on 72 of the 80 companies that carry both and disagree on 8, in one "
              "case by a factor of 650 (Marriott files $0.023B under one tag and $14.995B under "
              "the other). `current portion` and `short-term borrowings` agree on only 10 of the "
              "35 names carrying both. So a total-debt figure is NOT provided here: adding these "
              "cells would double-count on most names, and picking one tag per company is a "
              "judgment call. YOU decide which components belong in your net-debt figure, and say "
              "which you used.",
              "- The vendor's own total-debt scalar in DATA 2 is an independent cross-check "
              "built on a different definition. Where it disagrees with every column here, treat "
              "the discrepancy as unresolved rather than picking the number that suits the case.",
              "- Investments columns are securities held outside `cash`. Omitting them from net "
              "debt overstates leverage; on this book they run a median 32% of the cash balance."]
        L.append("")

    # ---- SECTION 7 -------------------------------------------------------------------------
    if asof_date is None:
        if bat:
            _rc5 = bat.get('revenue_cagr_5y')
            facts["revenue_cagr_5y_pct"] = float(f"{_rc5*100:.1f}") if isinstance(_rc5, (int, float)) else None
            L += [f"## DATA 7 - FILING-DERIVED QUALITY MEASURES   [Arithmetic on filed values; each "
                  f"line states its window; fiscal year {_v(bat, 'fiscal_year')}]",
                  f"- Piotroski F-score: {_v(bat, 'f_score')} out of "
                  f"{_v(bat, 'f_score_checks_available')} checks WE WERE ABLE TO EVALUATE (the "
                  f"denominator is what our data supported, not the standard 9)",
                  f"- Accruals ratio: {_v(bat, 'accruals_ratio')}   (accrual share of earnings; "
                  f"more positive means more of the reported profit is not yet cash)",
                  f"- Net share issuance, 1 year: {_pct(bat.get('net_issuance_1y'))}   |   3-year "
                  f"CAGR: {_pct(bat.get('net_issuance_3y_cagr'))}   (negative = net buyback)",
                  f"- Operating margin, latest: {_pct(bat.get('op_margin_latest'))}   |   median over "
                  f"{_v(bat, 'op_margin_years')} years: {_pct(bat.get('op_margin_10y_median'))}",
                  f"- Revenue CAGR, trailing 5 fiscal years: {_pct(_rc5)}",
                  f"- Years of history available: {_v(bat, 'years_available')}",
                  f"- Share-count split suspected in the filed series: "
                  f"{_v(bat, 'share_count_split_suspected')}. After the last filing: "
                  + (_split_sentence(_split) or "none detected."),
                  "",
                  "The Beneish M-score is deliberately omitted: it imputes absent inputs and then "
                  "publishes a score, which would present a guess as a measurement.", ""]

        # ---- SECTION 8 -------------------------------------------------------------------------
        # P4.10 staleness: past STALE_SUPPRESS_DAYS the header shows "STALE (n days)" AND the values
        # themselves are suppressed to STALE_NULL, rather than merely flagged (_age()'s 14-day note).
        fg = ob.get("forward_growth") or {}
        ob_stale = _not_fresh(ob)
        en_stale = _not_fresh(en)
        L.cls = r26_blind.CONSENSUS
        L += [r26_blind.tag(r26_blind.AGGREGATOR, f"## DATA 8 - CONSENSUS & MULTIPLES   [Aggregator, {_age_label(ob)}]"),
              # price_to_sales dropped 2026-08-20: measured non-null on 0 of 294 vendor records, so
              # the line could never print a value. Market cap and revenue are both in this pack;
              # the model can divide. A field that is structurally always absent is noise, not a
              # disclosed gap.
              r26_blind.tag(r26_blind.MULTIPLE, f"- Trailing P/E: {_sv(met, 'pe_ratio', ob_stale)}   |   P/B: "
              f"{_sv(met, 'price_to_book', ob_stale)}   |   PEG: {_sv(met, 'peg_ratio', ob_stale)}   "
              f"[trailing; the vendor does not state the period]"),
              r26_blind.tag(r26_blind.AGGREGATOR, f"- Return on equity: {_sv(met, 'return_on_equity', ob_stale)}   |   gross margin: "
              f"{_sv(met, 'gross_margin', ob_stale)}   |   operating margin: "
              f"{_sv(met, 'operating_margin', ob_stale)}   |   dividend yield: "
              f"{_sv(met, 'dividend_yield', ob_stale)}   [vendor-computed, expressed as fractions not "
              f"percents]",
              # revision 26: the blind pack prints this line without the dividend yield (a yield on the price)
              blind=(f"- Return on equity: {_sv(met, 'return_on_equity', ob_stale)}   |   gross margin: "
                     f"{_sv(met, 'gross_margin', ob_stale)}   |   operating margin: "
                     f"{_sv(met, 'operating_margin', ob_stale)}   [vendor-computed, expressed as fractions not percents]"),
              removed_text=f"- dividend yield: {_sv(met, 'dividend_yield', ob_stale)}", removed_cls=r26_blind.MULTIPLE)]
        est = en.get("estimates") if en else None
        _civ_na = None   # why SECTION 8 has no CONSENSUS-IMPLIED VALUE (E10)
        if en_stale:
            facts["consensus_data_status"] = "stale"
            L.append("- CONSENSUS ESTIMATES: not available \u2014 stale (> 45 days)")
            _civ_na = "consensus estimates stale"
        elif not en:
            facts["consensus_data_status"] = "enrich_missing"
            L.append("- CONSENSUS ESTIMATES: not available \u2014 enrich record missing")
            _civ_na = "no consensus estimates"
        elif rs2_data.enrich_fetch_error(en) is not None:
            # a vendor HTTP error (401, 429, 5xx) is a failed fetch, never "no coverage" (enrich_ticker.enrich's error record)
            _fe_status, _fe_where = rs2_data.enrich_fetch_error(en)
            facts["consensus_data_status"] = "fetch_error"
            L.append(f"- CONSENSUS ESTIMATES: not available — the vendor fetch failed (HTTP {_fe_status} at {_fe_where}, "
                     f"{(en.get('_fetched_at') or '')[:10] or 'unknown date'}); a failed fetch, not a lack of coverage")
            _civ_na = "consensus fetch failed"
        elif not est or not isinstance(est, dict):
            facts["consensus_data_status"] = "estimates_unavailable"
            L.append("- CONSENSUS ESTIMATES: not available \u2014 yfinance estimates unavailable")
            _civ_na = "no consensus estimates"
        else:
            facts["consensus_data_status"] = "ok"
            en_date = (en.get("_fetched_at") or "")[:10] or "unknown"
            L.append(f"- CONSENSUS ESTIMATES   [yfinance, fetched {en_date}; sell-side estimates, not company guidance]")
            L.append(_row(["period", "revenue avg", "low", "high", "analysts", "growth", "EPS avg", "low", "high",
                           "EPS analysts", "growth"]))
            L.append(_row(["---"] * 11))
            p0 = est.get("0y") or {}
            p1 = est.get("+1y") or {}
            for p_lbl, p_data in [("current FY", p0), ("next FY", p1)]:
                rev = p_data.get("revenue") or {}
                eps = p_data.get("eps") or {}
                # 0 analysts = no estimate: yfinance then reports avg/low/high as 0, which must print
                # as an absence, never as a $0.000B forecast (FSM next-FY revenue, 2026-09-24).
                if rev.get("analysts") == 0:
                    rev = {}
                if eps.get("analysts") == 0:
                    eps = {}
                r_avg = _b(rev.get("avg"))
                r_low = _b(rev.get("low"))
                r_high = _b(rev.get("high"))
                n_analysts = rev.get("analysts") if rev.get("analysts") is not None else eps.get("analysts")
                r_analysts = _n(n_analysts)
                r_growth = _pct(rev.get("growth"))
                if p_lbl == "next FY":
                    g = rev.get("growth")
                    if isinstance(g, (int, float)):
                        facts["next_fy_revenue_growth"] = round(float(f"{g * 100:+.1f}") / 100.0, 6)
                e_avg = f"${eps.get('avg'):.2f}" if isinstance(eps.get("avg"), (int, float)) else NULL
                e_low = f"${eps.get('low'):.2f}" if isinstance(eps.get("low"), (int, float)) else NULL
                e_high = f"${eps.get('high'):.2f}" if isinstance(eps.get("high"), (int, float)) else NULL
                e_growth = _pct(eps.get("growth"))
                L.append(_row([p_lbl, r_avg, r_low, r_high, r_analysts, r_growth, e_avg, e_low, e_high,
                               _n(eps.get("analysts")), e_growth]))

            # revision 10: the year-ago EPS consensus growth is measured from, against the filed year
            # (LAMR (b): consensus +19.4% ran from an adjusted $5.08 against a filed $5.78)
            _ya = (p0.get("eps") or {}).get("year_ago")
            _fyh = (h.get(str(latest_yr)) or {}) if latest_yr is not None else {}
            _fy_ni_x, _fy_sh_x = _fyh.get("net_income"), _fyh.get("shares_diluted")
            # revision 17 (brief C4): a split after the last filing leaves the filed count pre-split; the
            # vendor's year-ago EPS is split-adjusted, so the check uses the filed count x k
            _split_note = ""
            if _split and _split["fy"] == latest_yr and isinstance(_fy_sh_x, (int, float)):
                _fy_sh_x = _fy_sh_x * _split["multiplier"]
                _split_note = (f", the filed count x {_split['k']}" if not _split["reverse"] else
                               f", the filed count / {_split['k']}") + (
                                   " for the split after the last filing (DATA 7)" if _split["confirmed"] else
                                   " for the share-count difference after the last filing (DATA 7)")
            # review B4 (2026-09-27): only when the vendor's figures and ours are on one basis: the
            # vintage test passes and our filed share count agrees with the pack's (APH read -50%
            # across a split, ADS names read +290% and +2168%)
            _sh_ok = (isinstance(sh, (int, float)) and sh > 0 and isinstance(_fy_sh_x, (int, float))
                      and abs(_fy_sh_x / sh - 1) <= consensus_reference.LEVEL_TOL)
            _r26_base.update({"vendor_eps": _ya,
                              "filed_eps": (_fy_ni_x / _fy_sh_x) if (isinstance(_fy_ni_x, (int, float)) and isinstance(_fy_sh_x, (int, float))
                                                                      and _fy_sh_x > 0 and _fy_ni_x != 0) else None,
                              "aligned": _aligned, "shares_agree": bool(_sh_ok)})
            _sd26 = facts.get("shares_default")
            if (_r26 and _r26_base["filed_eps"] is None and not isinstance(_fy_sh_x, (int, float)) and isinstance(_fy_ni_x, (int, float)) and _fy_ni_x != 0
                    and isinstance(_sd26, (int, float)) and _sd26 > 0):
                # revision 26: the filer tags no diluted share count (a 20-F filer): the pack's own code-owned count stands in, stamped; the vintage test and the analyst floor are unchanged
                _r26_base.update({"filed_eps": _fy_ni_x / _sd26, "shares_agree": True, "filed_eps_from_pack_shares": True})
            if (isinstance(_ya, (int, float)) and _ya > 0 and isinstance(_fy_ni_x, (int, float))
                    and isinstance(_fy_sh_x, (int, float)) and _fy_sh_x > 0 and _fy_ni_x != 0
                    and not (_aligned is True and _sh_ok)):
                L.append(f"- BASE-YEAR CHECK: not available \u2014 "
                         + (f"the vendor's year-ago revenue does not match FY{latest_yr}'s filed revenue within 2%"
                            if _aligned is False else
                            f"the vendor's year-ago revenue is not available to check against FY{latest_yr}'s "
                            f"filed revenue" if _aligned is None else
                            "DATA 2 holds no share count" if not (isinstance(sh, (int, float)) and sh > 0) else
                            f"our filed FY{latest_yr} diluted share count ({_fy_sh_x / 1e9:.3f}B) and DATA 2's "
                            # S3 5.11: the cause list gains dilution now that SECTION 2's count
                            # carries its own dilution factor.
                            f"({sh / 1e9:.3f}B) differ by more than 15% (a split, ADS units, "
                            f"share classes or dilution (convertibles, options))")
                         + ", so the vendor's year-ago EPS and ours cannot be shown to be on one basis.")
            elif (isinstance(_ya, (int, float)) and _ya > 0 and isinstance(_fy_ni_x, (int, float))
                    and isinstance(_fy_sh_x, (int, float)) and _fy_sh_x > 0 and _fy_ni_x != 0):
                _fy_eps = _fy_ni_x / _fy_sh_x
                _byc_printed = True
                L.append(f"- [Arithmetic] BASE-YEAR CHECK: consensus measures current-FY EPS growth from a "
                         f"year-ago EPS of ${_ya:.2f}; our filed FY{latest_yr} EPS is ${_fy_eps:.2f} (net income / "
                         f"diluted shares{_split_note}), {(_ya / _fy_eps - 1) * 100:+.0f}% apart. A large gap means the "
                         f"consensus growth rate starts from a different base than the filings (adjusted rather "
                         f"than GAAP figures, or one-off items).")
            trend = p1.get("eps_trend") or {}
            now_val = f"${trend.get('current'):.2f}" if isinstance(trend.get("current"), (int, float)) else NULL
            d30_val = f"${trend.get('d30'):.2f}" if isinstance(trend.get("d30"), (int, float)) else NULL
            d60_val = f"${trend.get('d60'):.2f}" if isinstance(trend.get("d60"), (int, float)) else NULL
            d90_val = f"${trend.get('d90'):.2f}" if isinstance(trend.get("d90"), (int, float)) else NULL
            cur_num = trend.get("current")
            d90_num = trend.get("d90")
            if isinstance(cur_num, (int, float)) and isinstance(d90_num, (int, float)) and d90_num != 0:
                pct_90 = (cur_num - d90_num) / abs(d90_num) * 100.0
                pct_str = f"({pct_90:+.1f}% in 90 days)"
            else:
                pct_str = "(change unknown in 90 days)"
            L.append(f"- Next-FY EPS estimate trend: now {now_val} | 30 days ago {d30_val} | 60 days ago {d60_val} | 90 days ago {d90_val}  {pct_str}")

            revs = p1.get("eps_revisions") or {}
            up30 = _n(revs.get("up30"))
            down30 = _n(revs.get("down30"))
            up7 = _n(revs.get("up7"))
            down7 = _n(revs.get("down7"))
            L.append(f"- Estimate revisions, last 30 days (next FY): {up30} up / {down30} down  (last 7 days: {up7} up / {down7} down)")
            # ---- CONSENSUS-IMPLIED VALUE   [Phase 4 E10] ---------------------------------------
            # What the analysts' own earnings path is worth at our discount rate, computed the same
            # way for every name (tools/consensus_reference.py). Not a forecast and not a target.
            if asof_date is None:
                _med = (g_stats or {}).get("median") if g_stats else None
                if _med is None:
                    _med = ((br_table or {}).get(5) or {}).get("p50")
                # revision 17 (brief B Notation): r and the anchor are the values the pack prints (facts), the
                # ones the desk defaults to, so the reference and the desk value on identical inputs
                _coe = facts["coe_anchor"]
                _fy = _ref_fy or {}
                # S3 5.11: the reference divides by the share-count default (5.11), not SECTION
                # 2's raw count, so the Base and its reference are on one share basis (R10).
                _ref_shares = facts.get("shares_default")
                # revision 18 (brief section 2, step 1): every input of the reference is `reference_inputs`'
                _root = DataRoot()
                _root._hist, _root._ttm = _hist_doc, {t: ttm}
                _root._fin[t] = fin
                _ri = reference_inputs(t, _root, est,
                                       {"rf": anchor_rf_val, "ga": terminal_g_val, "breakeven": be_val,
                                        "loading": {sector: adj_load_val}},
                                       {"erp": _clos_erp} if _clos_erp is not None else None, printed=True,
                                       today=datetime.now().date())
                _ref = consensus_reference.build(**_ri["kwargs"])
                # revision 20 (brief 1.3(b), 3.3): the base the reference grows from, attributed by pi (the window check reads it too), and
                # the vendor's revenue basis
                _fy_base = (input_scope.attribute_fy_base(_fy, h.get(str(latest_yr)) or {}, _pi) or {}).get("base")
                _vb = _ri["vendor_basis"]
                facts["vendor_revenue_basis"] = {"status": _vb["status"], "s": _vb["s"], "k": _vb["k"]}
                _scope_clauses = {
                    "after_base": [c for c in (input_scope.pi_clause(_nci),
                                               input_scope.upper_bound_clause(_nci) if input_scope.NCI_UNMEASURED in _nci["stamps"] else None,
                                               input_scope.per_share_clause(_ps) if _ps["status"] == "unverified" else None) if c],
                    "years35": input_scope.years35_break_text(_vb) if _vb["status"].startswith("break") else None,
                    "years35_extra": [input_scope.years35_untested_clause(_vb)] if input_scope.VENDOR_UNTESTED in _vb["stamps"] else [],
                    "cash_note": input_scope.cash_note(_scope["cash_scope"], _money, lambda v: f"${_bn(v)}B")}
                if _ri["coe"] is None and _ref.get("value") is None and not _ri["no_marker"]:
                    _ref["reason"] = f"the closure premium is missing or stale ({_clos_asof or _clos_why})"
                if not _ref_fy and _ref.get("value") is None and _ref_fy_na and not _ri["no_marker"]:
                    _ref["reason"] = _ref_fy_na
                # E15, revision 18 (brief 1.5): outside the fail-fast fence the reference is no longer a credible
                # summary of the consensus (spot commodity earnings carried forward as a perpetuity): the line prints
                # the number and the fence, and the status flag keeps it out of every band, reason and refusal. Every fact
                # the reference derives (levels, long run, working capital, base) is kept as for a reference in force, so
                # the desk's default inputs equal the reference; the desk and the harness read the status before they apply
                # a band, a hold or a refusal to it.
                _band = _consensus_band_or_none(t)
                # brief F5: a value of zero or less (as printed, to the cent) is no reference: it is stamped not_meaningful,
                # prints no number, and the fence is not evaluated for it
                _ref_value = (_ref or {}).get("value")
                _not_meaningful = _ref_value is not None and float(f"{_ref_value:.2f}") <= 0
                _fence_box = []

                def _fence_side():
                    _s, _f = _reference_outside_fence(_ref_value, _band)
                    _fence_box.append(_f)
                    return _s
                _status = consensus_reference.classify_status(_ref_value, _fence_side)
                _side = _status.split("_")[-1] if _status.startswith("outside_fence") else None
                _fence = _fence_box[0] if _fence_box else None
                _tg_used = terminal_def_val if terminal_def_val is not None else 0.0
                if _ref.get("value") is None:
                    facts["reference_status"] = "not_available"
                    facts["consensus_implied_value"] = None
                elif _not_meaningful:
                    facts["reference_status"] = "not_meaningful"
                    facts["consensus_implied_value"] = None
                elif _side:
                    facts["reference_status"] = f"outside_fence_{_side}"
                    facts["consensus_implied_value"] = float(f"{_ref['value']:,.2f}".replace(",", ""))
                else:
                    facts["reference_status"] = "used"
                    facts["consensus_implied_value"] = float(f"{_ref['value']:,.2f}".replace(",", ""))
                if _ref.get("value") is not None and _ref.get("levels"):
                    facts["levels"] = {
                        "year1": float(f"{_ref['levels'][0] / 1e9:,.3f}".replace(",", "")),
                        "year2": float(f"{_ref['levels'][1] / 1e9:,.3f}".replace(",", "")),
                    }
                    if _ref.get("range"):
                        facts["levels"]["bull2"] = float(f"{_ref['range'][0] / 1e9:,.3f}".replace(",", ""))
                        facts["levels"]["bear2"] = float(f"{_ref['range'][1] / 1e9:,.3f}".replace(",", ""))
                # S3 5.6/5.7: bare numbers (_bn), not $/B (_b) — the unit is carried once, by
                # convention with SECTION 3's typed lines, not a header bracket here.
                # Revision 24 (R24.2): the line is not printed (stage A); its text is kept in the facts for stage B's reveal and the records.
                # Step 2b: the rev22 arm prints it, as revision 22 did.
                if _not_meaningful and _rev22:
                    L.append(consensus_reference.not_meaningful_line(_ref))
                elif _not_meaningful:
                    facts["reference_line"] = consensus_reference.not_meaningful_line(_ref)
                else:
                    _civ_line = consensus_reference.pack_line(_ref, _fy_base, _coe if _coe is not None else 0.0,
                                                              _tg_used, _bn, anchor=facts["terminal_g_anchor"],
                                                              closure_asof=_clos_asof, scope=_scope_clauses)
                    if _side:
                        _civ_line += (f" | outside the street-target fence [${_fence[0]:,.2f}, ${_fence[1]:,.2f}] (0.5× the "
                                      f"lowest and 2× the highest analyst target, each discounted by 10%) — read it as a "
                                      f"level check only")
                    if _rev22:
                        L.append(_civ_line)
                    else:
                        facts["reference_line"] = _civ_line
                if facts["reference_status"] in ("used", "not_meaningful") or _side:
                    # revision 17: what the reference's long run and working capital hold, for the desk (brief F5: a
                    # reference that is not meaningful still prints these)
                    _rlr = _ref.get("long_run")
                    if _rlr:
                        _lr_raw.update({"e5": _rlr["e5"] / 1e9, "oe5": _rlr["oe5"] / 1e9, "m5": _rlr["m5"],
                                        "om_5": _ref["om_5"], "m_long": _ref["m_long"],
                                        "margin_ratio": _ref["margin_ratio"]})
                    # brief F2: the margin rule's stamps join the record's in the facts' stamps
                    _margin_stamps = [s for s in _ref["stamps"]
                                      if s.startswith("margin_rule_") or s == "operating_base_not_positive"]
                    if _margin_stamps:
                        for _sk in ("stamps", "stamps_full"):
                            _lr_raw[_sk] = list(_lr_raw.get(_sk) or []) + _margin_stamps
                    # revision 24 step 2a (ruling 5): the margin rule's benchmark annotations are logged (the sidecar and the verdict's
                    # long_run_facts carry stamps_full) and never printed: the rule serves only the reference benchmark
                    # revision 24 step 2d: the returns' annotations (consensus_reference.RONIC_STAMPS) are logged the same way
                    _bench_stamps = [s for s in _ref["stamps"]
                                     if s in consensus_reference.BENCHMARK_STAMPS + consensus_reference.RONIC_STAMPS]
                    if _bench_stamps:
                        _lr_raw["stamps_full"] = list(_lr_raw.get("stamps_full") or []) + _bench_stamps
                    if _ref.get("wc"):
                        facts["working_capital"] = [pack_facts.q_b(x / 1e9) for x in _ref["wc"]]
                    if _ref.get("revenue") and _ref.get("oe_path"):
                        # revision 24 step 2c (ruling 12): the consensus revenue path and its owner earnings ($B), unprinted long_run members the
                        # desk builds each scenario's own revenue path from (the working-capital deduction); step 2d: and the base they were grown
                        # from (`oe_base`, consensus_reference.oe_base), at which the desk normalizes the path
                        _lr_raw.update({"revenue_path": [x / 1e9 for x in _ref["revenue"]], "oe_path": [x / 1e9 for x in _ref["oe_path"]]})
                        if consensus_reference.oe_base(_ref) is not None:
                            _lr_raw["oe_base"] = consensus_reference.oe_base(_ref) / 1e9
                    if _ref.get("base_cf") is not None:
                        facts["reference_base_b"] = pack_facts.q_b(_ref["base_cf"] / 1e9)
                    elif _ref.get("method") == "levels" and _ref.get("flows"):
                        # revision 18 (amendment 1): a levels name's base is its year-1 owner-earnings level after the cash term,
                        # so the desk's working-capital rule recognises the base as owner earnings
                        facts["reference_base_b"] = pack_facts.q_b(_ref["flows"][0] / 1e9)
                _win = (None if _not_meaningful else
                        consensus_reference.window_check(_ref, _fy_base, _ref_oe, _fy.get("quarters")))
                if _win and _win.get("ttm_value") is not None:
                    _wside, _wfence = _reference_outside_fence(_win["ttm_value"], _band)
                    _win = consensus_reference.fence_window(_win, _wside, _wfence)
                _wl = consensus_reference.window_line(_win, _ref, _ref_oe, _fy.get("through"), _bn,
                                                      base_year_check=_byc_printed, reference_shown=_rev22)
                if _wl:
                    L.append(_wl)
                    gap = int(f"{_win['gap'] * 100:+.0f}") / 100.0
                    ttm_val = float(f"{_win['ttm_value']:,.2f}".replace(",", "")) if _win.get("ttm_value") is not None else None
                    ttm_y2 = float(f"{_win['ttm_levels'][1] / 1e9:,.3f}".replace(",", "")) if _win.get("ttm_value") is not None else None
                    facts["base_window"] = {
                        "gap": gap,
                        "ttm_value": ttm_val,
                        "ttm_year2": ttm_y2,
                    }
        if _civ_na and asof_date is None:
            facts["reference_status"] = "not_available"
            if _rev22:
                L.append(f"- CONSENSUS-IMPLIED VALUE: not available \u2014 {_civ_na}")
            else:
                facts["reference_line"] = f"- CONSENSUS-IMPLIED VALUE: not available \u2014 {_civ_na}"   # revision 24: not printed
        if en:
            L += [r26_blind.tag(r26_blind.PRICE_TARGET, f"- Analyst price targets: low {_sv(en, 'analyst_target_low', en_stale)} / mean "
                  f"{_sv(en, 'analyst_target_mean', en_stale)} / median "
                  f"{_sv(en, 'analyst_target_median', en_stale)} / high "
                  f"{_sv(en, 'analyst_target_high', en_stale)}   [Aggregator - 12-month sell-side "
                  f"targets, {_age_label(en)}]")]
            sib = en.get("analyst_targets_sibling")
            own_low = en.get("analyst_target_low")
            own_high = en.get("analyst_target_high")
            if own_low is None or own_high is None:
                import valuation_backbone as _vb
                scaled_dict = _vb._sibling_scaled(sib)
                if scaled_dict is not None:
                    ratio = sib["price_ratio"]
                    legs, _st = _vb._band_legs(scaled_dict["low"], scaled_dict["median"],
                                               scaled_dict["high"], mean=scaled_dict["mean"])
                    if legs is not None:
                        sib_days = _age_days(sib)
                        sib_stale = bool(sib_days is not None and sib_days > STALE_SUPPRESS_DAYS)
                        sib_tk = _v(sib, "ticker")
                        n_analysts = _v(sib, "count")
                        L.append(r26_blind.tag(r26_blind.PRICE_TARGET,
                            f"- Analyst price targets, share class {sib_tk} "
                            f"(this class has none; scaled by the price ratio {ratio:.4f}): "
                            f"low {_sv(scaled_dict, 'low', sib_stale)} / "
                            f"median {_sv(scaled_dict, 'median', sib_stale)} / "
                            f"high {_sv(scaled_dict, 'high', sib_stale)}   "
                            f"[Aggregator - {n_analysts} analysts, {_age_label(sib)}]"
                        ))
            L += [r26_blind.tag(r26_blind.PRICE, f"- 52-week range: {_sv(en, 'fifty_two_week_low', en_stale)} - "
                  f"{_sv(en, 'fifty_two_week_high', en_stale)}")]
        L.append(r26_blind.tag(r26_blind.AGGREGATOR, ""))

        # ---- SECTION 8.5 - PEER CONTEXT [Aggregator, context not an anchor]   [P4.10] -----------
        L.cls = r26_blind.MULTIPLE
        L.append("## DATA 8.5 - PEER CONTEXT   [Aggregator, context not an anchor]")
        fs_cluster = fs_row.get("cluster")
        stocks_list = rs2_data.load_json(SD / "stocks.json") or []
        peer_syms = set()
        if fs_cluster and isinstance(stocks_list, list):
            peer_syms = {sym for sym, row in (fs_all.get("tickers") or {}).items()
                        if isinstance(row, dict) and row.get("cluster") == fs_cluster}
        # `peRatio` is a real field in stocks.json, but measured 2026-09-24: it reads 0 for every
        # one of 6,949 names on file - a P/E of exactly 0.0 for every company is not a filed value,
        # it is an unpopulated sentinel (the same structural-absence pattern already documented for
        # `price_to_sales` above), so it is never used. Compute trailing P/E ourselves instead, from
        # fields that DO carry real values: top-level `price` / `metrics.epsTtm` (trailing EPS) -
        # measured populated for 5,984 of 6,949 names, positive (usable) for 3,423.
        eps_field_exists = bool(stocks_list) and any(
            isinstance(row, dict) and isinstance((row.get("metrics") or {}).get("epsTtm"), (int, float))
            for row in stocks_list[:200])
        peer_pe, pe_source = [], None
        peer_pe_left_out = 0
        if peer_syms and eps_field_exists:
            for row in stocks_list:
                if not isinstance(row, dict) or row.get("symbol") not in peer_syms:
                    continue
                price = row.get("price")
                eps = (row.get("metrics") or {}).get("epsTtm")
                # Excludes non-positive earnings: a P/E on a loss-making peer is not a comparable
                # multiple, and `0.0` here would be indistinguishable from the dead `peRatio` field.
                if (isinstance(price, (int, float)) and price > 0
                        and isinstance(eps, (int, float)) and eps > 0):
                    peer_pe.append(price / eps)
            pe_source = "price / trailing EPS (`metrics.epsTtm`), `stocks.json`"
        elif peer_syms:
            # `epsTtm` itself absent from this corpus's schema - fall back to the screener's own
            # fundamentals history: each peer's latest fiscal-year net income / diluted shares
            # against its current price from stocks.json.
            fh_tickers = (rs2_data.load_json(SD / "fundamentals_history.json") or {}).get("tickers") or {}
            price_by_sym = {row.get("symbol"): row.get("price") for row in stocks_list
                            if isinstance(row, dict)}
            for sym in peer_syms:
                years = fh_tickers.get(sym) or {}
                if not isinstance(years, dict) or not years:
                    continue
                yr_row = years.get(max(years, key=str)) or {}
                ni, sh, price = yr_row.get("net_income"), yr_row.get("shares_diluted"), price_by_sym.get(sym)
                if (isinstance(ni, (int, float)) and ni > 0
                        and isinstance(sh, (int, float)) and sh > 0
                        and isinstance(price, (int, float)) and price > 0):
                    # P-2: a peer whose filed and vendor counts differ by 100x or more has a units error in one of
                    # them, and its P/E is off by that factor: left out, and counted below.
                    _pfin = rs2_data.load_json(SD / "financials" / f"{sym}.json") or {}
                    if _peer_shares_gap(_pfin.get("Shares_Outstanding"), years) is not None:
                        peer_pe_left_out += 1
                        continue
                    peer_pe.append(price / (ni / sh))
            if peer_pe:
                pe_source = ("price / (latest fiscal-year net income / diluted shares), "
                            "`fundamentals_history.json`")
        ev_ebitda_field_exists = bool(stocks_list) and any(
            "ebitda" in str(k).lower() for row in stocks_list[:1] if isinstance(row, dict)
            for k in list(row.keys()) + list((row.get("metrics") or {}).keys()))
        pe_field_note = (
            f"present but measured 0 for every one of {len(stocks_list):,} names on file, so it "
            f"carries no usable signal (trailing P/E below is computed instead from "
            + (pe_source if pe_source else "price / trailing EPS or fundamentals history; not "
                                           "available - neither source had usable data")
            + ")") if stocks_list else NULL
        L.append(f"- Fields checked in `stocks.json`: trailing P/E (`peRatio`) - {pe_field_note}; "
                 f"EV/EBITDA - "
                 + ("a field of that name exists" if ev_ebitda_field_exists
                    else "no field of that name exists in `stocks.json`'s per-ticker record")
                 + ". Only fields found usable are printed as values below.")
        pe_n = len(peer_pe)
        if pe_n:
            pe_sorted = sorted(peer_pe)
            pe_med = (pe_sorted[pe_n // 2] if pe_n % 2
                     else (pe_sorted[pe_n // 2 - 1] + pe_sorted[pe_n // 2]) / 2)
            L.append(f"- Cluster peers' trailing P/E (n={pe_n}, source: {pe_source}): median "
                     f"{pe_med:.1f}x | p25 {pe_sorted[int(pe_n * .25)]:.1f}x | p75 "
                     f"{pe_sorted[int(pe_n * .75)]:.1f}x")
        else:
            L.append(f"- Cluster peers' trailing P/E: {NULL}")
        if peer_pe_left_out:
            L.append(f"- {peer_pe_left_out} cluster peer(s) left out of that trailing P/E: the peer's filed diluted "
                     f"share count and the vendor's differ by a factor of 100 or more, so its P/E carries a units error.")
        L.append(f"- Cluster peers' EV/EBITDA: {NULL}")
        peer_band = rs2_data.anchor_multiple_bands(sector)
        if peer_band:
            ntm = peer_band.get("anchor_ntm_pe") or {}
            rstate = peer_band.get("anchor_regime_state")
            rstate_str = (", ".join(f"{k} {v}" for k, v in rstate.items())
                         if isinstance(rstate, dict) else (rstate or NULL))
            L.append(f"- MRI sector trailing-P/E band ({mri_sec}): median "
                     f"{ntm.get('median', NULL)}x | p25 {ntm.get('p25', NULL)}x | p75 "
                     f"{ntm.get('p75', NULL)}x   [regime state: {rstate_str}, as of "
                     f"{peer_band.get('anchor_asof', NULL)}]")
        else:
            L.append(f"- MRI sector trailing-P/E band: {NULL}")
        L.append("")

        # ---- SECTION 9 -------------------------------------------------------------------------
        L.cls = r26_blind.AGGREGATOR
        if en:
            if en_stale:
                L += [f"## DATA 9 - POSITIONING   [Aggregator, {_age_label(en)}]",
                      f"- {STALE_NULL} - record older than {STALE_SUPPRESS_DAYS} days; values "
                      f"suppressed rather than shown potentially wrong.", ""]
            else:
                L += [f"## DATA 9 - POSITIONING   [Aggregator, {_age_label(en)} - short interest is "
                      f"semi-monthly settlement data; ownership is 13F data lagged by up to a quarter]",
                      f"- Short % of float: {_v(en, 'short_pct_float')}   |   shares short: "
                      f"{_n(en.get('shares_short'))}   |   days to cover: "
                      f"{_v(en, 'short_ratio_days_to_cover')}   |   month-on-month change: "
                      f"{_v(en, 'short_mom_change_pct')}",
                      f"- Institutional ownership: {_v(en, 'institutional_pct')}%   |   insider: "
                      f"{_v(en, 'insider_pct')}%", ""]

        # ---- SECTION 10 ------------------------------------------------------------------------
        tr = ob.get("earnings_transcript") or ob.get("transcript_excerpt")
        L.cls = r26_blind.NARRATIVE
        if tr:
            section10_printed = True   # S3 5.5/5.10: SECTION 12's Q&A pointer fires only here
            L += ["## DATA 10 - EARNINGS CALL EXCERPT   [Verbatim management speech - an assertion "
                  "by the company, not an audited fact]",
                  "**This excerpt is capped at ingest and is prepared remarks only. The analyst Q&A - "
                  "where guidance gets challenged, and where forward capital-spending plans are "
                  "usually pinned down - is NOT in our data for any name. If your valuation turns on "
                  "guidance beyond the current year, this excerpt cannot settle it.**",
                  str(tr)[:12000], ""]

    else:
        # Phase 4 E4.3: SECTIONs 7-10 read same-day vendor/battery snapshots
        # (fundamentals_battery.json, the openbb cache, enrich/*.json) with no stored history —
        # none of them can be honestly restricted to an as-of date, so all four are OMITTED here
        # rather than shown with today's values under a point-in-time label. See SECTION 12 for
        # the full list of what was omitted and why.
        L += ["## DATA 7 - FILING-DERIVED QUALITY MEASURES   [" + ASOF_NULL + "]",
              "- fundamentals_battery.json is a same-day snapshot with no stored history to "
              "restrict to this as-of date.", ""]
        facts["consensus_data_status"] = "point_in_time"
        L += ["## DATA 8 - CONSENSUS & MULTIPLES   [" + ASOF_NULL + "]",
              "- the openbb cache (trailing multiples, consensus forward growth, analyst price "
              "targets) is a same-day snapshot with no stored history.", ""]
        L += ["## DATA 8.5 - PEER CONTEXT   [" + ASOF_NULL + "]",
              "- reconstructing peer point-in-time price/EPS would need an as-of network fetch "
              "for every cluster peer; not attempted this run.", ""]
        L += ["## DATA 9 - POSITIONING   [" + ASOF_NULL + "]",
              "- enrich/*.json (short interest, institutional/insider ownership) is a same-day "
              "snapshot with no stored history.", ""]
        L += ["## DATA 10 - EARNINGS CALL EXCERPT   [" + ASOF_NULL + "]",
              "- the openbb cache carries no historical transcript archive.", ""]
    # ---- research brief load (shared by GUIDANCE & CONSENSUS and SECTION 11) ---------------
    rb = HERE / "research" / f"{t}.md"
    rb_text, brief_ok = None, False
    if include_research and rb.exists():
        rb_text = rb.read_text(encoding="utf-8", errors="replace")
        try:
            from research_brief_guard import check_research_brief
            brief_ok, brief_reason = check_research_brief(t, brief_text=rb_text)
        except Exception:
            brief_ok, brief_reason = True, None
        if not brief_ok:
            print(f"   [pack] WARN research brief failed company verification for {t} "
                  f"({brief_reason}) — omitting GUIDANCE & CONSENSUS and DATA 11",
                  file=sys.stderr, flush=True)

    # ---- GUIDANCE & CONSENSUS   [D4/D4b] -----------------------------------------------------
    L.cls = r26_blind.NARRATIVE
    L.append("## GUIDANCE & CONSENSUS   [company's own earnings release from SEC EDGAR, then research-brief claims]")

    asof_str = asof_date.isoformat() if asof_date is not None else None
    pack_date = asof_str if asof_str is not None else datetime.now().strftime("%Y-%m-%d")
    c = cik(t)
    # revision 21: the PRIMARY SOURCES section, built once per pack (the pack's date bounds every filing, in point-in-time mode and live)
    primary = sec_primary.build(c, asof=pack_date)
    facts["primary_sources"] = sec_primary.facts_items(primary["items"])
    p1 = next((i for i in primary["items"] if i["type"] == "earnings_release"), None)
    if not c:
        L.append("COMPANY'S OWN WORDS: not available — no CIK")
    else:
        rel = sec_guidance.latest_earnings_release(c, asof=asof_str)
        if not rel:
            reason = getattr(sec_guidance.latest_earnings_release, "last_reason", None) or f"no 8-K Item 2.02 on or before {pack_date}"
            L.append(f"COMPANY'S OWN WORDS: not available — {reason}")
        else:
            fdate = rel.get("filing_date", "")
            try:
                age_days = (datetime.strptime(pack_date, "%Y-%m-%d") - datetime.strptime(fdate, "%Y-%m-%d")).days
            except Exception:
                age_days = 0
            stale_prefix = f"STALE ({age_days} days) — " if age_days > 120 else ""
            full_ptr = (f"The full release is PRIMARY {p1['id']}. "
                        if p1 is not None and p1["accession"] == rel.get("accession") else "")
            words_hdr = (f"{stale_prefix}COMPANY'S OWN WORDS — latest earnings release "
                         f"(SEC 8-K Item 2.02, filed {rel['filing_date']}, {rel['url']}). "
                         f"{full_ptr}The company's statement, not a verified forecast:")
            L.append(words_hdr)
            # revision 10: ADI (b)'s trailing figures lagged a filed quarter
            _thru = ttm.get("through") if isinstance(ttm, dict) else None
            if _thru:
                L.append(f"- DATA FRESHNESS: DATA 3's trailing figures run through {_thru}; this release was "
                         f"filed {rel['filing_date']}. A release filed after the next quarter end reports a "
                         f"quarter those figures do not hold yet.")
            excerpt = sec_guidance.guidance_excerpt(rel.get("text", ""))
            if excerpt:
                L.append(excerpt)

    L.append("")
    L.append("Research-brief rows (claims by another model, check before relying):")
    guidance_rows = _parse_guidance_block(rb_text) if (rb_text and brief_ok) else []
    if guidance_rows:
        L += [_row(["metric", "period", "value", "source", "date"]), _row(["---"] * 5)]
        for gr in guidance_rows:
            L.append(_row([gr["metric"], gr["period"], gr["value"], gr["source"], gr["date"]]))
    elif asof_date is not None:
        L.append("not available (point-in-time trial) — research is unconditionally OFF in "
                 "point-in-time mode")
    else:
        L.append(f"{NULL} — research did not return dated guidance")
    # S3 5.3: the GUIDANCE & CONSENSUS **MANDATE** line is removed (it pointed at "the SECTION 12
    # contract", which no longer carries reasons; the rule now lives in the DEFAULTS block).
    L.append("")

    # ---- PRIMARY SOURCES   [revision 21] -----------------------------------------------------
    L.cls = r26_blind.FILED
    L += sec_primary.section_lines(primary)
    L.append("")

    # ---- SECTION 11 - DEEP RESEARCH BRIEF   [D8] -------------------------------------------
    research_omitted = []
    L.cls = r26_blind.NARRATIVE
    if rb_text is not None and brief_ok:
        # S3 5.9 (C2): drop each off-topic sub-section (its own text says the sources were not
        # about this company) and annotate what was dropped, rather than silently shortening the
        # brief.
        rb_filtered, research_omitted = _c2_filter_research_brief(rb_text)
        L.append("## DATA 11 - DEEP RESEARCH BRIEF   [Written by another model, not verified - "
                 "every figure is a claim to check against the filings above; cite the filing when "
                 "you rely on it.]")
        if research_omitted:
            L.append("- Omitted " + str(len(research_omitted)) + " research topic(s) whose own "
                     "text says their sources were not about this company: "
                     + "; ".join(research_omitted) + ".")
        L += [rb_filtered[:25000], ""]

    # ---- SECTION 12 ------------------------------------------------------------------------
    L.cls = r26_blind.FILED
    # S3 5.5: the "Declared so..." line becomes a header bracket, and each _decl line shrinks to
    # one line (HELD .../ NOT MAPPED ...) using the phrase table verbatim.
    L += ["## DATA 12 - WHAT WE DO NOT HOLD   [declared so you can source it or carry the "
          "uncertainty]",
          _segment_note(t),
          _decl("Marketable securities and short-term investments", h, yrs,
                ("st_investments", "lt_investments"),
                held_phrase="in DATA 6C; liquidity held there makes a cash-only net debt "
                            "understate liquid assets, even flip its sign",
                gap_phrase="the cash column and DATA 2's vendor cash can understate liquid "
                           "assets badly"),
          _decl("Stock-based compensation per year", h, yrs, ("sbc",),
                held_phrase="in DATA 5's SBC column",
                gap_phrase="only DATA 2's vendor scalar, whose period is unreliable"),
          _pretax_note(h, yrs),
          _decl("Debt components beyond long-term debt", h, yrs,
                ("debt_current", "short_term_borrowings_separate", "finance_lease_liability",
                 "operating_lease_liability", "borrowings_total", "debt_lt_noncurrent"),
                held_phrase="in DATA 6C; whether they overlap is not known, so no total debt "
                            "is computed",
                gap_phrase="DATA 6's long-term debt understates total debt by an unknown "
                            "amount; DATA 2's vendor total is the only cross-check"),
          "- Which XBRL tag produced each number: NOT RECORDED (see DATA 0).",
          _transcript_line(ob, section10_printed), ""]
    if drift:
        L += ["**SCHEMA DRIFT DETECTED WHILE BUILDING THIS PACK.** Fields this builder expects "
              "were absent from the upstream record, so sections above may be missing data we "
              "actually hold. Treat the affected areas as unreliable rather than empty: "
              + " | ".join(drift), ""]
    unreviewed = _unreviewed_history_fields(h)
    if unreviewed:
        L += ["**UNREVIEWED FIELDS PRESENT IN THE FILED RECORD.** The screener is filing these "
              "columns and this pack does not print them, so the tables above are INCOMPLETE by "
              "exactly this much and any 'we do not hold it' line above may be stale: "
              + ", ".join(f"`{k}`" for k in unreviewed)
              + ". Weigh your conclusions accordingly and say so in your report.", ""]
    if asof_date is not None and asof_omitted:
        L += [f"**POINT-IN-TIME OMISSIONS (as of {asof_date.isoformat()}).** Every input this "
              f"pack could not honestly restrict to this date, omitted rather than shown with "
              f"today's value:"]
        L += [f"  - {reason}" for reason in asof_omitted]
        L.append("")

    # S3 5.2: the DEFAULTS block is the last block of the pack, printed immediately before the
    # TASK, so the model reads what each desk input defaults to right before it is asked to call
    # the desk. `coe_anchor_pct` and `terminal_def_val`/`terminal_g_val` are set by whichever
    # SECTION 1.5 branch ran above (both branches use these same names) and are still in scope
    # here — Python functions have no block scope.
    # revision 18 follow-up, finding 17: a name with no marker has no record, but the age of the base fiscal year (stub_months) is not part of
    # the record: it stays, so the desk still rolls the value forward to today. Without it the desk skipped the roll-forward unstamped.
    _lr_facts = _lr_raw if not _no_marker else (
        {"stub_months": _lr_raw["stub_months"]} if _lr_raw.get("stub_months") is not None else {})
    facts["long_run"] = pack_facts.quantize_long_run(_lr_facts)
    # revision 19 (brief D3, D4): the DEFAULTS run's price-implied value of each judgment input, solved at the pack's price by the desk's own solver
    # on the one production construction of the DEFAULTS run (consensus_reference.defaults_desk_args); the two anchors the desk's bounds read
    facts["rf_eff"] = _rf_eff
    facts["nominal_gdp_trend"] = rs2_data.anchor_nominal_gdp_trend()[0]
    # revision 24 step 2b: the rev22 arm's DEFAULTS run applies the reference's long-run margin (m_long), as revision 22's did; the revision-24 run
    # holds it (the run is the logged benchmark's, never printed there)
    _dargs, _dwhy = consensus_reference.defaults_desk_args(_ref, facts, reference_margin=_rev22)
    if _dargs is None:
        facts["price_implied_defaults"] = {"not_available": _dwhy}
    else:
        facts["reference_path"] = [float(g) for g in _dargs["explicit_growth"]]
        if isinstance(_pack_price, (int, float)) and not isinstance(_pack_price, bool) and _pack_price > 0:
            import financial_model_tool as _fmt
            facts["price_implied_price"] = float(_pack_price)
            facts["price_implied_defaults"] = pi_text.quantize_block(_fmt.defaults_price_implied(
                _dargs, _pack_price, rf_eff=facts["rf_eff"], gdp_trend=facts["nominal_gdp_trend"], levels=facts.get("levels")))
        else:
            facts["price_implied_defaults"] = {"not_available": "the pack has no price to solve at"}
    if _sf:
        # revision 25 short form: the earnings-margin basis facts, computed from this build's own record, estimates and the filed companyfacts (the DEFAULTS block prints them)
        facts.update(x_margin_basis_facts(t, h, _hist_doc, en.get("estimates") if en else None, facts))
    L.cls = r26_blind.DERIVED
    if _r26:
        # revision 26: the DEFAULTS lines are classed by their fact key (pack_facts records it); the long_run line also carries the text the blind pack prints in its place
        _dkeys = []
        _dargs26 = dict(split_confirmed=bool(_split and _split["confirmed"]), no_marker=_no_marker, withhold_reference=True, withhold_long_run=True)
        _dfull = pack_facts.render_defaults_block(facts, tags_out=_dkeys, **_dargs26).split("\n")
        _dblind = pack_facts.render_defaults_block(facts, blind_long_run=True, **_dargs26).split("\n")
        assert len(_dfull) == len(_dkeys) + 1 == len(_dblind), "a DEFAULTS line holds a line break"
        _lr26 = facts.get("long_run") or {}
        L.append(_dfull[0])
        for _line, _bline, _key in zip(_dfull[1:], _dblind[1:], _dkeys):
            _cls = r26_blind.DEFAULTS_KEY_CLASS.get(_key, r26_blind.DERIVED)
            if _bline != _line:        # the long_run line (without its consensus members) and the earnings_margin_basis line (which no longer names them)
                L.append(r26_blind.tag(_cls, _line, blind=_bline, removed_text=(
                    ", ".join(f"{m}={_lr26.get(m)!r}" for m in pack_facts.BLIND_LONG_RUN_MEMBERS) if _key == "long_run" else None)))
            else:
                L.append(r26_blind.tag(_cls, _line))
        L.append("")
    else:
        L += [pack_facts.render_defaults_block(facts, split_confirmed=bool(_split and _split["confirmed"]), no_marker=_no_marker,
                                               withhold_reference=not _rev22, withhold_long_run=not _rev22), ""]
    # revision 24 step 2b (BRIEF_R24_S2b_ranges_gate.md item 2): the population ranges of the long-run inputs, after DEFAULTS; the rev22 arm
    # prints none. The facts keep them for the plausibility gate.
    facts["population_ranges"] = _population_ranges_for(t, h, _record, asof_date, _hist_doc)
    if not _rev22:
        L += [population_ranges.render_section(facts["population_ranges"], bool(_show_p50)), ""]
    if _r26:
        # revision 26: DATA 5.1, the operating-margin bar (the X basis for the financial family); consensus_corrected for stage 3; the blind pack, the drops and the leak test
        _fin_family = (facts.get("population_ranges") or {}).get("family") == "financial"      # the family r26_stages.resolve_family reads, not the vendor sector (Gold.com: sector Financial Services, SIC 5051, operating)
        _bar = r26_blind.x_margin_bar(facts.get("x_margin_history")) if _fin_family else r26_blind.op_margin_bar(h)
        if not _fin_family and r26_blind.no_filed_operating_income(_bar):
            # any name, never by ticker: an operating-family name with no filed operating income in the window is on the X basis throughout
            _bar = r26_blind.x_margin_bar(facts.get("x_margin_history"))
            _bar["stamps"] = ["x_basis_no_operating_income"]
            _fin_family = True
        facts["op_margin_bar"] = _bar
        L.insert_block(_bar_at, r26_blind.op_margin_bar_lines(_bar, _fin_family), r26_blind.FILED)
        _pi26 = (facts.get("nci_attribution") or {}).get("pi")
        _vb26 = str((facts.get("vendor_revenue_basis") or {}).get("status") or "")
        _xh = facts.get("x_margin_history") or {}
        _xh_last = (_xh.get("years") or [None])[-1]
        facts["consensus_corrected"] = r26_blind.consensus_corrected(
            en.get("estimates") if en else None, _r26_base.get("filed_eps"), _r26_base.get("vendor_eps"), facts.get("shares_default"), _pi26,
            _vb26.startswith("break"), vintage_aligned=_r26_base.get("aligned"), shares_agree=bool(_r26_base.get("shares_agree")),
            filed_eps_from_pack_shares=bool(_r26_base.get("filed_eps_from_pack_shares")),
            filed_x_margins=({"fy": _xh_last["fy"], "x_margin": _xh_last["x_margin"]} if isinstance(_xh_last, dict) else None),
            bridge_facts=facts, base_year=_xh.get("base_year"))
        # the company's own 8-K Item 2.02 releases of the trailing year: their numbers are filed support for the leak test
        _filed_8k = [{k: r.get(k) for k in ("accession", "filing_date", "url", "text")} for r in (sec_guidance.earnings_releases(c, asof=pack_date) if c else [])]
        _split26 = r26_blind.blind_split_audited(L, facts, _filed_8k)
        facts["r26_blind_drops"] = _split26["drops"]
        facts["r26_blind_source"] = _split26["r26_blind_source"]
        facts["r26_leak_audit"] = r26_blind.r26_leak_audit(_split26["blind_text"], facts)

    global LAST_PACK_MACRO_DEGRADED, LAST_PACK_FLAGS, LAST_PACK_FACTS
    LAST_PACK_MACRO_DEGRADED = macro_degraded
    LAST_PACK_FLAGS = ["macro_degraded"] if macro_degraded else []
    if asof_date is not None:
        LAST_PACK_FLAGS.append("point_in_time")
    LAST_PACK_FACTS = facts
    if _r26:
        _pt = PackText(_split26["blind_text"], macro_degraded=macro_degraded, flags=LAST_PACK_FLAGS, facts=facts, research_omitted=research_omitted)
        _pt.full_text = _split26["full_text"]
        return _pt
    return PackText("\n".join(L), macro_degraded=macro_degraded, flags=LAST_PACK_FLAGS, facts=facts,
                    research_omitted=research_omitted)


# P4.4 — single source for the `invalidation_rules` / `momentum_flip_condition` /
# `momentum_break_rule` metric vocabulary. TASK's text below is built by interpolating these
# tuples so the prompt and `fiduciary_gate.validate_fiduciary_contract` can never drift apart;
# `fiduciary_gate` imports them from here rather than restating the list.
MOMENTUM_METRICS = (
    "mom_12_1", "mom_6m", "mom_1m", "high_52w_distance", "above_below_200d_mean",
    "rs_vs_cluster_etf_3m", "rs_vs_iwm_3m", "realised_vol_60d", "mom_z_sector", "mom_break",
)
FINANCIAL_METRICS = (
    "revenue_yoy_pct", "gross_margin_pct", "operating_margin_pct", "net_income", "ocf", "fcf",
    "net_issuance_1y", "filing_8k_count",
)

# S3 4.1: the form's 13 fields. The last two are kept until the operator rules on C10.
FORM_FIELDS = ("catalysts", "conviction_score", "business_quality_moat", "cycle_evidence", "momentum_view",
               "entry_timing", "position_basis", "momentum_evidence", "momentum_flip_condition",
               "momentum_break_rule", "invalidation_rules", "reentry_tranches", "thesis_invalidation_trigger")
# Revision 24 step 2b (BRIEF_R24_S2b_ranges_gate.md item 3): the fields the revision-24 contract adds after cycle_evidence - the near-term and
# normalized earnings and the transition, the three classifications with their evidence pointers, and the input rationale. The rev22 arm's TASK
# keeps FORM_FIELDS.
S12_FIELDS = ("near_term_earnings", "normalized_earnings", "normalization_reason", "margin_persistence", "margin_persistence_evidence",
              "cycle_position", "cycle_position_evidence", "growth_trajectory", "growth_trajectory_evidence", "input_rationale")
FORM_FIELDS_III = FORM_FIELDS[:4] + S12_FIELDS + FORM_FIELDS[4:]

# S3 4.2 (2026-09-28): replaces the revision-14 TASK, whose narrative rules code now enforces
# (the desk's DEFAULTS block and its refusals) or which is now derived, not typed. Old literal
# above this comment, in git history at 3d02fbd.
TASK_REV22 = """You are underwriting this company for real money. T0 is today's price in DATA 2. The data pack above is what our systems hold. Its DEFAULTS block gives the value each desk input takes unless you decide otherwise, and the reason the desk asks for when you do.

YOU OWN THE UNDERWRITING; THE DESK DOES THE ARITHMETIC. You own the economic view, the moat judgment, the scenario boundaries and the capital decision, as the charter sets them. Every value you publish comes from run_financial_model: do not compute present values, terminal values, per-share values or Kelly sizes in your reasoning. Call the desk as soon as your inputs are set, and reason from its output.

1. Explain the recent move first. Start from the CATALYST BRIEF, RECENT COMPANY NEWS and DATA 8's estimate trend and revisions. For each development, say whether you accept or dispute it and why, and how it enters Bull, Base and Bear. Add any development you find yourself, and fetch the articles you rely on. Record them in `catalysts`. If a public takeover offer is pending, value the business standalone; in the memorandum give the offer's probability and the expected value with and without it. The verdict stays on standalone value.
2. Decompose the business into its economic engines: transactional deliveries; a captive installed base, recurring contractual annuity or subscriptions; strategic optionality. Do not force it into one formula. Credit a multi-year annuity only where the filings show the backlog or installed base that secures it (cite the filing and the figure). Customer advances and one-off prepayment float are not recurring cash flow, and a supplier purchase commitment is not customer revenue.
3. Choose every valuation input and pass it to the desk: the cash-flow base and its window; the growth of that cash flow (not revenue) for years 1-5 in Base, Bull and Bear; fade years; terminal growth and terminal_ronic (the return on new investment that pays for growth from year 6); the discount rate; the frame; the share count; net debt (firm frame only); the cash-flow life; and the scenario probabilities, justified by milestones and the balance of evidence. Start from the DEFAULTS; do not run trial bases through the desk.
   - Growth: the desk holds the Base's years 1-2 at the consensus cash-flow levels in DEFAULTS unless you give the reason DEFAULTS names for a departure. From year 3, growth follows next-FY revenue growth, fading toward the base-rate median by year 5. Growth above the base-rate p90 needs dated, company-specific evidence. With fewer than 3 analysts there is no consensus range: anchor Bull and Bear to the top and bottom of the company's own guidance range where the GUIDANCE section gives one; otherwise state your own range and why.
   - Scenarios: Bull rests on the strongest bull catalyst the market is reacting to, and Bear on the strongest bear catalyst. The Bear traces an operating shock through the business (volume, the installed base's durability, operating deleverage, a wider discount rate), not an arbitrary cut. Where the filings show contracted backlog above one year of revenue or recurring revenue above 70%, cite it: the Bear may not fall below that contracted floor without a stated reason.
   - Terminal value: do not clamp terminal growth or impose multiple ceilings on durable compounders; a departure from the terminal_g or terminal_ronic default needs evidence, not a cap.
   - Working capital: the desk deducts the DEFAULTS working_capital from every scenario's owner earnings in years 1-5, unless your base_cf is within 2% of cash_basis_b and not within 2% of owner_earnings_default_b or reference_base_b (a base that matches an owner-earnings figure is owner earnings).
   - Valuation date: the desk values at the base fiscal year end and rolls the value forward to today at your discount rate, as the CONSENSUS-IMPLIED VALUE does.
   - Frame: every flow in this pack is after interest, so value it in the equity frame. The firm frame needs a pre-interest flow, a WACC built from the COE ANCHOR, and net debt; the desk asks for each.
   - Shares: use the DEFAULTS block's shares_default, the desk's default (DATA 2's count, times the dilution factor when DATA 2 shows one). Add a contingent instrument (warrants, earn-outs) only in the scenarios where it vests, never in one whose premise is that it does not.
   - Cash-flow life: cash flows end when they come from a finite stock (a mine, a well, a reservoir) or a right that expires (a licence, concession or patent), unless the filings show the stock or right is replaced out of capex your base already deducts. The life is filed reserves over current production, or the remaining term, with the filing's date. A perpetual value must deduct the capex that replaces what the business depletes. Where revenue follows a quoted commodity price, state the price deck your flows assume and its source.
4. Where an input departs from its DEFAULT, give the reason with dated evidence in the same desk call. The desk names any reason it needs, and a refused call does not use one of your desk runs. A reason is evidence, never text such as "no deviation"; leave a reason out when none is needed.
5. Run Bear, Base and Bull together in one call. Your last complete desk run of all three is your answer. If you change any input after a complete run, the memorandum's 'Model revisions' list gives each changed input's old value, new value and the dated evidence that forced the change. Changing an input because you dislike the resulting value is forbidden; the harness records every run.
6. The desk also returns price_implied: for each judgment input (coe, growth_years_3_5, fade_years, terminal_g, terminal_ronic, year2_level), the value at which your Base would equal today's price with your other inputs unchanged, or "not reachable" when no value inside the input's bound does it. DEFAULTS prints the same at the default inputs. A verdict of undervalued or overvalued needs a stated disagreement with the price: in your answer run, pass crux, naming one to three of those inputs where your evidence says the price is wrong, each with your reason and at least one citation {source, date, quote} of this company's own evidence: the company's own filings, verbatim, in PRIMARY SOURCES (cite them as PRIMARY P# with the quote copied exactly), or DATA 3, DATA 4, DATA 5, DATA 6, GUIDANCE (the company's own release), or a page you fetched in this session that names the company, with the quote copied exactly. Code fills in your value and the price-implied value from that run. DEFAULTS, the base rates, the macro anchors, the CONSENSUS-IMPLIED VALUE, the sector bands, the consensus rows, the news list and the research briefs are context and never support a crux. Without a valid crux your verdict is HOLD, wherever your Base sits. Disagreeing with the analysts' targets is allowed when your evidence supports it. In SECTION 3, state each crux (the input, your number, the number the price implies, and the dated evidence) and argue the size of the disagreement, not only its sign. Also report the neutral reverse DCF's implied 10-year growth and the base-rate band it falls in. SECTION 0 and SECTION 12 state the verdict this item gives; where the system text says otherwise, this TASK takes precedence.
7. Timing: DATA 2.5's price facts are not a valuation input. State whether they confirm, sit neutral to or contradict your value call, when to enter, the position basis, and checkable conditions that would break the trend or the thesis.
8. Tag every driver's source: [Actual], [Estimate], [Assumption] or [Unconfirmed]. The research brief and the news are claims by others; where they conflict with the filings, the filings win. PRIMARY SOURCES holds the company's own filings verbatim; do not search for or fetch them again — the tools return a pointer instead. Search only for what they do not contain.

Produce the full memorandum, SECTION 0 through SECTION 12, as the system text specifies, and end with the contract below. The contract no longer carries the scenario values, probabilities, Kelly size, verdict label, valuation inputs, reasons or crux: code takes them from your last complete desk run of Bear, Base and Bull. Where the system text asks you to type any of them into SECTION 12's contract, this TASK takes precedence, and SECTION 4's scenario table and SECTION 12's figures must show that run's values exactly.

```json:underwriting
{
  "catalysts": [{"date": "<YYYY-MM-DD>", "event": "<what happened>", "direction": "<bull | bear>", "estimates_moved": "<how consensus estimates moved with it, or 'no visible change'>", "scenario": "<which scenario it supports and how it moves the numbers>"}],
  "conviction_score": <float between 4.0 and 15.0: analytical certainty>,
  "business_quality_moat": <float between 1.0 and 5.0: moat durability>,
  "cycle_evidence": "<a dated, industry-specific indicator (pricing, inventory, capacity, orders) when you apply a cyclical, mid-cycle or margin-mean-reversion treatment; a growth rate alone is not evidence; null otherwise>",
  "momentum_view": "<confirming | neutral | contradicting: DATA 2.5's price action against your value call>",
  "entry_timing": "<buy_now | wait_for_momentum | avoid>",
  "position_basis": "<value | momentum | none: value only when undervalued; momentum when your honest direction is hold or overvalued but the business is in a strong, fundamentally backed uptrend (entry_timing buy_now); otherwise none>",
  "momentum_evidence": "<when position_basis is momentum: the dated facts from the GUIDANCE block or the filings that back the trend (guidance raised, backlog or orders growth, estimates rising); null otherwise>",
  "momentum_flip_condition": {"metric": "<one of the SCR-10 price-fact fields printed in DATA 2.5>", "comparator": "< | <= | > | >=", "threshold": <float>, "window_days": <integer>},
  "momentum_break_rule": {"metric": "<one of the SCR-10 price-fact fields printed in DATA 2.5>", "comparator": "< | <= | > | >=", "threshold": <float>, "window_days": <integer>},
  "invalidation_rules": [{"metric": "<name from the metric vocabulary below>", "comparator": "< | <= | > | >=", "threshold": <float>, "window": "<string, e.g. 'next reported quarter'>", "source": "<where this is checked, e.g. 'fundamentals_quarterly.json'; \\"unverifiable\\" if the metric is outside both vocabularies>"}],
  "reentry_tranches": {"tranche_1_starter": <float price for the starter allocation, reflecting margin of safety>, "tranche_2_core": <float price for the core allocation, anchored to Bear IV or a deep pullback>},
  "thesis_invalidation_trigger": "<the exact operational or financial threshold that invalidates this thesis>"
}
```

METRIC VOCABULARY for `invalidation_rules` (at least one FINANCIAL and at least one PRICE/MOMENTUM rule are required; anything outside both lists must be declared `source: "unverifiable"`):
  - MOMENTUM metrics (the SCR-10 field names, exactly as printed in DATA 2.5): """ + ", ".join(MOMENTUM_METRICS) + """.
  - FINANCIAL metrics: """ + ", ".join(FINANCIAL_METRICS) + """.

Think carefully through the complete economic machinery before writing. Numbers before narrative."""


# Revision 24 step 2b (BRIEF_R24_S2b_ranges_gate.md item 4): the TASK of the revision-24 pack (the pilot arms iii). The long-run inputs have no default; items 3a-3d ask for the near-term and normalized
# earnings, the three classifications, the choice with the POPULATION RANGES as context, and the three citation levels; SECTION 12's contract carries them. It never names the reference.
# Revision 24 step 2c (ruling 8 of step 2b and the coordinator's addition): the company evidence the TASK names, one text for the crux (item 6)
# and the outlier citations (item 3d), exactly what crux_check accepts (crux_check.COMPANY_EVIDENCE: pack_company - PRIMARY P#, DATA 3-6,
# GUIDANCE - and fetched_page_naming_company), no more and no less; tests/test_rev24_s2c_gate.py pins the agreement.
EVIDENCE_SOURCES = ("the company's own filings, verbatim, in PRIMARY SOURCES (cite them as PRIMARY P# with the quote copied exactly), or DATA 3, DATA 4, DATA 5, DATA 6, GUIDANCE (the company's own release), or a page you fetched in this session that names the company, with the quote copied exactly")
TASK = """You are underwriting this company for real money. T0 is today's price in DATA 2. The data pack above is what our systems hold. Its DEFAULTS block gives the filed facts and conventions each desk input takes unless you decide otherwise, and the reason the desk asks for when you do. The long-run inputs (long_run_margin, the growth of years 3-5, fade_years, terminal_g and terminal_ronic) have no default: you choose them, and the POPULATION RANGES section shows how companies like this one actually evolved, as context for your choice, not a target.

YOU OWN THE UNDERWRITING; THE DESK DOES THE ARITHMETIC. You own the economic view, the moat judgment, the scenario boundaries and the capital decision, as the charter sets them. Every value you publish comes from run_financial_model: do not compute present values, terminal values, per-share values or Kelly sizes in your reasoning. Call the desk as soon as your inputs are set, and reason from its output.

1. Explain the recent move first. Start from the CATALYST BRIEF, RECENT COMPANY NEWS and DATA 8's estimate trend and revisions. For each development, say whether you accept or dispute it and why, and how it enters Bull, Base and Bear. Add any development you find yourself, and fetch the articles you rely on. Record them in `catalysts`. If a public takeover offer is pending, value the business standalone; in the memorandum give the offer's probability and the expected value with and without it. The verdict stays on standalone value.
2. Decompose the business into its economic engines: transactional deliveries; a captive installed base, recurring contractual annuity or subscriptions; strategic optionality. Do not force it into one formula. Credit a multi-year annuity only where the filings show the backlog or installed base that secures it (cite the filing and the figure). Customer advances and one-off prepayment float are not recurring cash flow, and a supplier purchase commitment is not customer revenue.
3. Choose every valuation input and pass it to the desk: the cash-flow base and its window; the growth of that cash flow (not revenue) for years 1-5 in Base, Bull and Bear; fade years; long_run_margin (the earnings margin, earnings over revenue, the business earns at the end of the fade); terminal growth and terminal_ronic (the return on new investment that pays for growth from year 6); the discount rate; the frame; the share count; net debt (firm frame only); the cash-flow life; and the scenario probabilities, justified by milestones and the balance of evidence. The filed facts and the conventions (the cash-flow base, the COE ANCHOR, the share count, working capital, excess cash) start from the DEFAULTS; do not run trial bases through the desk. For the long-run inputs, in this order:
   a. State your near-term earnings (what the business earns over the next one to two years; DATA 8 and the DEFAULTS levels show what analysts forecast, as evidence) and your normalized mid-cycle earnings, and the transition between them with its reason.
   b. Classify three dimensions, each from its own evidence and none forced by another: margin_persistence (structural, partly_structural or transient), cycle_position (trough, mid, peak or not_cyclical) and growth_trajectory (accelerating, steady, decelerating or shrinking).
   c. Choose each long-run input (long_run_margin, the growth of years 3-5, fade_years, terminal_g, terminal_ronic), using the POPULATION RANGES as context, not a target.
   d. Support each choice at its level. An ordinary choice needs a concise rationale tied to the facts and the population: within the P10-P90 its POPULATION RANGES line prints, and also whenever no P10-P90 is printed for it (the growth of years 3-5, fade_years, and a line that reads "no measured population for this family" or "not available"). An outlier needs a sourced, causal explanation of why this company differs from its cohort, with a citation {source, date, quote} of this company's own evidence: """ + EVIDENCE_SOURCES + """. An outlier is a long_run_margin outside the earnings-margin P10-P90 of its line, a terminal_ronic outside the P10-P90 of the return on invested capital five years out, a terminal_g above the long-run nominal growth anchor the pack prints (terminal_g_anchor), and any terminal_g above 0 for a shrinking business (your record's revenue trend is falling, or you classify growth_trajectory as shrinking). The long-run margin's range is measured five years out, while your long_run_margin is the margin at the end of your fade: outside its P10-P90 it still needs the outlier's citation. The buy or sell crux needs the same evidence (item 6). Code reads within_p10_p90 from the printed range itself, and checks the trajectory your inputs imply: the revenue growth to year 10 against the cohort's 10-year revenue CAGR P5-P95, and terminal_g against the growth anchor and the shrinking rule. A value outside them without a citation the code can verify, given under the input that drives it (the growth of years 3-5 or fade_years for the revenue growth), makes the valuation unusable. A long_run_margin outside its five-years-out P5-P95, and a terminal_ronic outside the P5-P95 of the return on invested capital five years out, are recorded against your verdict, not rejected (those ranges are measured five years out, not at the end of your fade or in perpetuity). terminal_g must stay below your discount rate.
   - Growth: your years 1-2 are your own; the consensus levels in DEFAULTS are what analysts forecast, evidence and not a value the desk holds, and the desk holds or caps no year. Growth above the base-rate p90 needs dated, company-specific evidence. With fewer than 3 analysts there is no consensus range: anchor Bull and Bear to the top and bottom of the company's own guidance range where the GUIDANCE section gives one; otherwise state your own range and why.
   - Scenarios: Bull rests on the strongest bull catalyst the market is reacting to, and Bear on the strongest bear catalyst. The Bear traces an operating shock through the business (volume, the installed base's durability, operating deleverage, a wider discount rate), not an arbitrary cut. Where the filings show contracted backlog above one year of revenue or recurring revenue above 70%, cite it: the Bear may not fall below that contracted floor without a stated reason.
   - Terminal value: do not clamp terminal growth or impose multiple ceilings on durable compounders; terminal_g and terminal_ronic have no default and need the support item 3d asks for, not a cap.
   - Working capital: in years 1-5 the desk deducts from every scenario's owner earnings the working capital that scenario's own revenue path ties up: the DEFAULTS working_capital_intensity times each year's revenue change, the revenue being the consensus revenue path scaled year by year by that scenario's owner earnings over the consensus owner earnings, unless your base_cf is within 2% of cash_basis_b and not within 2% of owner_earnings_default_b or reference_base_b (a base that matches an owner-earnings figure is owner earnings).
   - Valuation date: the desk values at the base fiscal year end and rolls the value forward to today at your discount rate.
   - Frame: every flow in this pack is after interest, so value it in the equity frame. The firm frame needs a pre-interest flow, a WACC built from the COE ANCHOR, and net debt; the desk asks for each.
   - Shares: use the DEFAULTS block's shares_default, the desk's default (DATA 2's count, times the dilution factor when DATA 2 shows one). Add a contingent instrument (warrants, earn-outs) only in the scenarios where it vests, never in one whose premise is that it does not.
   - Cash-flow life: cash flows end when they come from a finite stock (a mine, a well, a reservoir) or a right that expires (a licence, concession or patent), unless the filings show the stock or right is replaced out of capex your base already deducts. The life is filed reserves over current production, or the remaining term, with the filing's date. A perpetual value must deduct the capex that replaces what the business depletes. Where revenue follows a quoted commodity price, state the price deck your flows assume and its source.
4. Where an input departs from its DEFAULT, give the reason with dated evidence in the same desk call. The desk names any reason it needs, and a refused call does not use one of your desk runs. A reason is evidence, never text such as "no deviation"; leave a reason out when none is needed.
5. Run Bear, Base and Bull together in one call. Your last complete desk run of all three is your answer. If you change any input after a complete run, the memorandum's 'Model revisions' list gives each changed input's old value, new value and the dated evidence that forced the change. Changing an input because you dislike the resulting value is forbidden; the harness records every run.
6. The desk also returns price_implied: for each judgment input (coe, growth_years_3_5, fade_years, terminal_g, terminal_ronic, year2_level, long_run_margin), the value at which your Base would equal today's price with your other inputs unchanged, or "not reachable" when no value inside the input's bound does it. A verdict of undervalued or overvalued needs a stated disagreement with the price: in your answer run, pass crux, naming one to three of those inputs where your evidence says the price is wrong, each with your reason and at least one citation {source, date, quote} of this company's own evidence: """ + EVIDENCE_SOURCES + """. Code fills in your value and the price-implied value from that run. DEFAULTS, the base rates, the macro anchors, the sector bands, the consensus rows, the news list and the research briefs are context and never support a crux. Without a valid crux your verdict is HOLD, wherever your Base sits. Disagreeing with the analysts' targets is allowed when your evidence supports it. In SECTION 3, state each crux (the input, your number, the number the price implies, and the dated evidence) and argue the size of the disagreement, not only its sign. Also report the neutral reverse DCF's implied 10-year growth and the base-rate band it falls in. SECTION 0 and SECTION 12 state the verdict this item gives; where the system text says otherwise, this TASK takes precedence.
7. Timing: DATA 2.5's price facts are not a valuation input. State whether they confirm, sit neutral to or contradict your value call, when to enter, the position basis, and checkable conditions that would break the trend or the thesis.
8. Tag every driver's source: [Actual], [Estimate], [Assumption] or [Unconfirmed]. The research brief and the news are claims by others; where they conflict with the filings, the filings win. PRIMARY SOURCES holds the company's own filings verbatim; do not search for or fetch them again — the tools return a pointer instead. Search only for what they do not contain.

Produce the full memorandum, SECTION 0 through SECTION 12, as the system text specifies, and end with the contract below. The contract no longer carries the scenario values, probabilities, Kelly size, verdict label, valuation inputs, reasons or crux: code takes them from your last complete desk run of Bear, Base and Bull. Where the system text asks you to type any of them into SECTION 12's contract, this TASK takes precedence, and SECTION 4's scenario table and SECTION 12's figures must show that run's values exactly.

```json:underwriting
{
  "catalysts": [{"date": "<YYYY-MM-DD>", "event": "<what happened>", "direction": "<bull | bear>", "estimates_moved": "<how consensus estimates moved with it, or 'no visible change'>", "scenario": "<which scenario it supports and how it moves the numbers>"}],
  "conviction_score": <float between 4.0 and 15.0: analytical certainty>,
  "business_quality_moat": <float between 1.0 and 5.0: moat durability>,
  "cycle_evidence": "<a dated, industry-specific indicator (pricing, inventory, capacity, orders) when you apply a cyclical, mid-cycle or margin-mean-reversion treatment; a growth rate alone is not evidence; null otherwise>",
  "near_term_earnings": <float, $B: what the business earns over the next one to two years>,
  "normalized_earnings": <float, $B: its normalized mid-cycle earnings>,
  "normalization_reason": "<the transition from near-term to normalized earnings, and why>",
  "margin_persistence": "<structural | partly_structural | transient>",
  "margin_persistence_evidence": "<one line: where the evidence is>",
  "cycle_position": "<trough | mid | peak | not_cyclical>",
  "cycle_position_evidence": "<one line: where the evidence is>",
  "growth_trajectory": "<accelerating | steady | decelerating | shrinking>",
  "growth_trajectory_evidence": "<one line: where the evidence is>",
  "input_rationale": {"long_run_margin": {"value": <float>, "within_p10_p90": <true | false>, "rationale": "<tied to the facts and the population>", "citation": <null for an ordinary choice; for an outlier {"source": "<PRIMARY P# | DATA 3 | DATA 4 | DATA 5 | DATA 6 | GUIDANCE | the URL of a page you fetched in this session that names the company>", "date": "<YYYY-MM-DD>", "quote": "<copied exactly from the source>"}>}, "growth_years_3_5": {<the same four fields>}, "fade_years": {<the same>}, "terminal_g": {<the same>}, "terminal_ronic": {<the same>}},
  "momentum_view": "<confirming | neutral | contradicting: DATA 2.5's price action against your value call>",
  "entry_timing": "<buy_now | wait_for_momentum | avoid>",
  "position_basis": "<value | momentum | none: value only when undervalued; momentum when your honest direction is hold or overvalued but the business is in a strong, fundamentally backed uptrend (entry_timing buy_now); otherwise none>",
  "momentum_evidence": "<when position_basis is momentum: the dated facts from the GUIDANCE block or the filings that back the trend (guidance raised, backlog or orders growth, estimates rising); null otherwise>",
  "momentum_flip_condition": {"metric": "<one of the SCR-10 price-fact fields printed in DATA 2.5>", "comparator": "< | <= | > | >=", "threshold": <float>, "window_days": <integer>},
  "momentum_break_rule": {"metric": "<one of the SCR-10 price-fact fields printed in DATA 2.5>", "comparator": "< | <= | > | >=", "threshold": <float>, "window_days": <integer>},
  "invalidation_rules": [{"metric": "<name from the metric vocabulary below>", "comparator": "< | <= | > | >=", "threshold": <float>, "window": "<string, e.g. 'next reported quarter'>", "source": "<where this is checked, e.g. 'fundamentals_quarterly.json'; \\"unverifiable\\" if the metric is outside both vocabularies>"}],
  "reentry_tranches": {"tranche_1_starter": <float price for the starter allocation, reflecting margin of safety>, "tranche_2_core": <float price for the core allocation, anchored to Bear IV or a deep pullback>},
  "thesis_invalidation_trigger": "<the exact operational or financial threshold that invalidates this thesis>"
}
```

METRIC VOCABULARY for `invalidation_rules` (at least one FINANCIAL and at least one PRICE/MOMENTUM rule are required; anything outside both lists must be declared `source: "unverifiable"`):
  - MOMENTUM metrics (the SCR-10 field names, exactly as printed in DATA 2.5): """ + ", ".join(MOMENTUM_METRICS) + """.
  - FINANCIAL metrics: """ + ", ".join(FINANCIAL_METRICS) + """.

Think carefully through the complete economic machinery before writing. Numbers before narrative."""


# Revision 25 (Stage 0.6): the two-pass paragraph of TASK_REV25. The pass-2 message the harness sends is analyst_tools.TWO_PASS_MESSAGE.
TWO_PASS_TASK_PARAGRAPH = (
    "You work in two passes. In pass 1 you research and make at least one complete desk run (Bear, Base and Bull) as your preliminary forecast; "
    "without one, pass 2 does not open and the sample is not used. When pass 1 ends, the harness sends one message opening pass 2, where you "
    "reconcile your preliminary forecast with everything in the pack, make your final desk calls and write the memorandum and the contract. "
    "Code compares your final run's inputs with your preliminary run's and records every change; in `reconciliation_reasons` give one "
    "{input, reason} for each input that changed, tied to the evidence.\n\n")

# Revision 25 (Stage 0.3): the TASK of the packs with desk schema 25.1 - the revision-24 TASK with the path and normalization declarations in place of
# the owner-earnings growth and the two typed earnings figures (near_term_earnings and normalized_earnings are derived by the desk, so the contract no
# longer carries them). Built by replacing exact passages of TASK, so every other word is TASK's; a passage that moves breaks the import, not the run.
def _task_rev25():
    t = TASK
    for old, new in (('the growth of that cash flow (not revenue) for years 1-5 in Base, Bull and Bear;', 'the revenue growth and the earnings margin of years 1-5 in Base, Bull and Bear;'), ('   a. State your near-term earnings (what the business earns over the next one to two years; DATA 8 and the DEFAULTS levels show what analysts forecast, as evidence) and your normalized mid-cycle earnings, and the transition between them with its reason.\n', "   a. Declare your path and your normalization in the desk call. Path: revenue_growth (the annual revenue growth of years 1-5, five values; DATA 8 and the DEFAULTS levels show what analysts forecast, as evidence) and earnings_margin (the earnings margin of years 1-5, five values). The margin basis is the X basis: earnings before acquired-intangible amortization over revenue, the basis of x_L, m_tc and m5 in DEFAULTS. Operating margins (om_tc, om_L, om_trend, om_5) are context only, on the operating basis; no input takes one. Normalization, for Base (Bull and Bear inherit Base's unless they give their own; a scenario whose long_run_margin differs from the normalized_margin it would inherit gives its own normalized_margin and normalization_horizon, or the desk asks why): normalized_margin (the X-basis earnings margin once any abnormal margin condition has ended), normalization_horizon (a whole number from 0 to 5 plus fade_years, the first year the margin is at normalized_margin; 0 when today's margin is not abnormal; the desk moves the margin in a straight line from year 5 to long_run_margin over the fade, so a horizon after year 5 is coherent only with fade_years equal to normalization_horizon minus 5, or a year-5 margin already at normalized_margin), structural_growth (the annual revenue growth with any cyclical swing removed), normalized_revenue_base ($B, only when flags include cyclical and today's revenue is itself at a cyclical level; default today's revenue) and flags (a list: any of cyclical, structural_growth, structural_decline, turnaround, or none). For a cyclical business also pass cycle_position and cycle_evidence. The desk derives near-term earnings (years 1 and 2) and normalized earnings (at today's revenue scale) from these declarations; do not type them. State the transition and why in normalization_reason. The desk checks the declarations against each other and asks for a named bridge reason (bridge_C1_reason to bridge_C5_reason) where one disagrees. revenue_growth and earnings_margin replace explicit_growth, which this desk refuses except for a scenario the bridge does not apply to (a finite cash_flow_life or the firm frame; the desk says so).\n"), ("the revenue being the consensus revenue path scaled year by year by that scenario's owner earnings over the consensus owner earnings, unless", 'the revenue being your declared revenue path from the filed base year, unless'), ('  "near_term_earnings": <float, $B: what the business earns over the next one to two years>,\n  "normalized_earnings": <float, $B: its normalized mid-cycle earnings>,\n', "")):
        assert t.count(old) == 1, old[:60]
        t = t.replace(old, new)
    # Stage 0.5 (SPEC v1.2): the three classification labels go in the desk call (the desk checks them, K1-K4); the *_evidence fields stay in the contract
    for old, new in (("For a cyclical business also pass cycle_position and cycle_evidence.", "For a cyclical business also pass cycle_evidence."),
                     ("Classify three dimensions, each from its own evidence and none forced by another: margin_persistence (structural, partly_structural or transient), cycle_position (trough, mid, peak or not_cyclical) and growth_trajectory (accelerating, steady, decelerating or shrinking).",
                      "Classify three dimensions, each from its own evidence and none forced by another, and pass all three in the desk call, at the top level or in Base (required: the desk refuses a Base without them; Bull and Bear inherit them): margin_persistence (structural, partly_structural or transient), cycle_position (trough, mid, peak or not_cyclical) and growth_trajectory (accelerating, steady, decelerating or shrinking). The desk checks each label against your numbers and asks for a named reason (class_K1_reason to class_K4_reason) where one disagrees; it never changes a label. In the contract, give each one's evidence field (margin_persistence_evidence, cycle_position_evidence, growth_trajectory_evidence); the labels are not in the contract: the desk call owns them.")):
        assert t.count(old) == 1, old[:60]
        t = t.replace(old, new)
    # Stage 0.6 (the two-pass protocol): the contract carries the analyst's reasons for what changed between its passes, and the TASK says there are
    # two passes. Both arms (r25_b and r25_c) are sent the same words; only the pack and the pass-2 message differ.
    for anchor, add in (('  "momentum_view": "<confirming | neutral', '  "reconciliation_reasons": [{"input": "<an input your final desk run changed from your preliminary run, as the desk names it>", "reason": "<why, tied to the evidence>"}],\n'),):
        assert t.count(anchor) == 1, anchor
        t = t.replace(anchor, add + anchor)
    # Stage 0.5 follow-up (ruling 2): the desk call is the labels' single owner under 25.1 - the three label fields leave the contract template
    for line in ('  "margin_persistence": "<structural | partly_structural | transient>",\n', '  "cycle_position": "<trough | mid | peak | not_cyclical>",\n',
                 '  "growth_trajectory": "<accelerating | steady | decelerating | shrinking>",\n'):
        assert t.count(line) == 1, line
        t = t.replace(line, "")
    anchor = "Think carefully through the complete economic machinery before writing. Numbers before narrative."
    assert t.count(anchor) == 1
    t = t.replace(anchor, TWO_PASS_TASK_PARAGRAPH + anchor)
    return t


TASK_REV25 = _task_rev25()


# Revision 25 short form (BRIEF_SF_short_form.md item 6): the TASK of the packs with desk schema 25.2 - the revision-24 TASK with item 3 asking for the two lists in place of the
# owner-earnings growth, the basis stated in plain words, and the working-capital sentence on the declared revenue. Nothing else changes: the near-term and normalized earnings
# (item 3a), the three classifications (item 3b) and the contract are the revision-24 text, there is no normalization block, no check and no second pass. Built by replacing
# exact passages of TASK, so every other word is TASK's; a passage that moves breaks the import, not the run.
SF_BASIS_PARAGRAPH = (
    "   - The two lists: revenue_growth (the annual revenue growth of years 1-5, five values) and earnings_margin (the earnings margin of years 1-5, five values), "
    "in each of Base, Bull and Bear, from the filed base year. " + x_margin_basis.BASIS_WORDS[0].upper() + x_margin_basis.BASIS_WORDS[1:] + ". "
    "DEFAULTS prints this basis (earnings_margin_basis), your record on it for each filed year, with the after-tax impact of any filed one-off lines in margin points and how often they recur (x_margin_history), and the margin the consensus "
    "EPS levels imply for years 1 and 2 (x_margin_consensus_y1y2). The desk derives the owner earnings from your two lists and values the long run from year 5 as before; "
    "revenue_growth and earnings_margin replace explicit_growth, which this desk refuses except for a scenario they do not apply to (a finite cash_flow_life or the firm "
    "frame; the desk says so). If a declared margin of year 1 or 2 is outside 0.67 to 1.5 times the consensus-implied one and more than 3 margin points from it, the desk states the divergence once, "
    "as information: it asks for no reason and changes nothing." + chr(10))


def _task_sf():
    t = TASK
    for old, new in (('the growth of that cash flow (not revenue) for years 1-5 in Base, Bull and Bear;', 'the revenue growth and the earnings margin of years 1-5 in Base, Bull and Bear (the two lists, below);'),
                     ("the revenue being the consensus revenue path scaled year by year by that scenario's owner earnings over the consensus owner earnings, unless", 'the revenue being your declared revenue path from the filed base year, unless'),
                     ("   - Growth: your years 1-2 are your own;", SF_BASIS_PARAGRAPH + "   - Growth: your years 1-2 are your own;")):
        assert t.count(old) == 1, old[:60]
        t = t.replace(old, new)
    return t


TASK_SF = _task_sf()
FORM_FIELDS_25 = tuple(f for f in FORM_FIELDS_III if f not in ("near_term_earnings", "normalized_earnings", "margin_persistence", "cycle_position", "growth_trajectory")) + ("reconciliation_reasons",)      # Stage 0.6: the contract field of the two-pass protocol


def task_for(facts):
    """Revision 24 step 2b: the TASK a pack is sent with - the revision-22 TASK for the rev22 arm (its facts' pilot_arm), the revision-24 TASK
    otherwise; revision 25: TASK_REV25 for a pack with desk schema 25.1, TASK_SF for desk schema 25.2."""
    f = facts or {}
    if f.get("desk_schema") == DESK_SCHEMA_25:
        return TASK_REV25
    if f.get("desk_schema") == DESK_SCHEMA_252:
        return TASK_SF
    return TASK_REV22 if f.get("pilot_arm") == "rev22" else TASK


# ---- Revision 25, Stage 0.6: what arm C withholds in pass 1 ------------------------------------------------------------------------------------
# Arm C (r25_c) sees the same pack as arm B (r25_b) except for every element derived from analyst estimates, which it sees only in the pass-2
# message. `split_consensus` takes the rendered pack text (before TASK is appended) and returns (pass1_text, withheld_block, elements): the pack
# with each such element replaced by one placeholder line, the lines it took out (verbatim, under the heading of the section they came from) and
# the list of elements with their source line. It works on the rendered text, so what is withheld is exactly what the pack printed; the facts
# sidecar is not touched (the desk reads it). The elements, by the code that prints them:
#   DATA 8 (build_pack, "## DATA 8 - CONSENSUS & MULTIPLES"): the CONSENSUS ESTIMATES table (revenue, EPS, low/high, analysts, growth), the BASE-YEAR
#     CHECK (the vendor's year-ago EPS), the next-FY EPS estimate trend, the estimate revisions and the analyst price targets, and the PEG member of the multiples line (it uses forward growth estimates; the trailing P/E and P/B stay);
#   DEFAULTS (pack_facts.render_defaults_block): the `levels` line (the consensus cash-flow levels, bull2 and bear2), the `next_fy_revenue_growth`
#     line, the `base_year_cap` line (it prints the vendor's year-ago EPS) and the `long_run` members e5, oe5 and m5 (the year-5 earnings and
#     margin at the consensus estimates of years 1-2).
# Not withheld: filed facts, the company's own guidance, price, the population ranges and the research (news, the catalyst brief, the research
# brief). The fence of the street targets and the CONSENSUS-IMPLIED VALUE are not printed in a revision-24 or later pack, so there is nothing to
# take out.
WITHHELD_FILE = "_withheld_consensus.md"
WITHHELD_NOTE = "withheld until pass 2"
_LR_MEMBER = re.compile(r"(?<![A-Za-z_0-9])(e5|oe5|m5)=([^,\s|]+)")
_PEG_MEMBER = re.compile(r"(\|\s+PEG: )(.+?)(?=\s{3}\[|$)")     # the PEG member of DATA 8's multiples line (it uses forward growth estimates)
_DATA8_LINES = (
    ("- CONSENSUS ESTIMATES   [", "DATA 8 consensus estimates table", True),
    ("- BASE-YEAR CHECK", "DATA 8 base-year check (the vendor's year-ago EPS)", False),
    ("- [Arithmetic] BASE-YEAR CHECK", "DATA 8 base-year check (the vendor's year-ago EPS)", False),
    ("- Next-FY EPS estimate trend", "DATA 8 next-FY EPS estimate trend", False),
    ("- Estimate revisions", "DATA 8 estimate revisions", False),
    ("- Analyst price targets", "DATA 8 analyst price targets", False),
    # lines a revision-24 or later pack does not print (the reference is kept in the facts); an older pack, or a fixture of one, would
    ("- [Arithmetic] CONSENSUS-IMPLIED VALUE", "DATA 8 consensus-implied value", False),
    ("- CONSENSUS-IMPLIED VALUE", "DATA 8 consensus-implied value", False),
    ("- [Arithmetic] BASE WINDOW CHECK", "DATA 8 base window check", False),
)
_DEFAULTS_LINES = (
    ("- levels:", "DEFAULTS levels"),
    ("- next_fy_revenue_growth:", "DEFAULTS next_fy_revenue_growth"),
    ("- base_year_cap:", "DEFAULTS base_year_cap (the vendor's year-ago EPS)"),
)


def split_consensus(pack_text):
    """(pass1_text, withheld_block, elements). `elements` is [{"element", "section", "source_line" (1-based, in `pack_text`), "text"}]; the text of
    a long_run element is its three members. A pack with no such element gives the pack itself, an empty block and no elements."""
    lines = str(pack_text).split("\n")
    kept, held, elements = [], [], []
    section, held_section = None, None
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## "):
            section = ln[3:].split("   [")[0].strip()
        label, span = None, 1
        if section and section.startswith("DATA 8 - "):
            for prefix, lab, table in _DATA8_LINES:
                if ln.startswith(prefix):
                    label = lab
                    if table:
                        while i + span < len(lines) and lines[i + span].startswith("|"):
                            span += 1
                    break
            if label is None and ln.startswith("- Trailing P/E:") and _PEG_MEMBER.search(ln):
                # ruling 3 on builders A and B: the PEG is withheld in pass 1; the trailing P/E, P/B and the rest of the line are kept
                peg = _PEG_MEMBER.search(ln)
                kept.append(_PEG_MEMBER.sub(lambda m: m.group(1) + WITHHELD_NOTE.replace(" ", "_"), ln))
                if held_section != section:
                    held += ["", f"[{section}]"]
                    held_section = section
                held.append("- PEG: " + peg.group(2))
                elements.append({"element": "DATA 8 PEG (forward growth estimates)", "section": section, "source_line": i + 1, "text": "PEG: " + peg.group(2)})
                i += 1
                continue
        elif section == "DEFAULTS":
            for prefix, lab in _DEFAULTS_LINES:
                if ln.startswith(prefix):
                    label = lab
                    break
            if label is None and ln.startswith("- long_run:") and _LR_MEMBER.search(ln):
                members = [m.group(0) for m in _LR_MEMBER.finditer(ln)]
                kept.append(_LR_MEMBER.sub(lambda m: f"{m.group(1)}={WITHHELD_NOTE.replace(' ', '_')}", ln))
                if held_section != section:
                    held += ["", f"[{section}]"]
                    held_section = section
                held.append("- long_run members: " + ", ".join(members))
                elements.append({"element": "DEFAULTS long_run members e5, oe5, m5", "section": section, "source_line": i + 1,
                                 "text": ", ".join(members)})
                i += 1
                continue
        if label is None:
            kept.append(ln)
            i += 1
            continue
        chunk = lines[i:i + span]
        if held_section != section:
            held += ["", f"[{section}]"]
            held_section = section
        held += chunk
        elements.append({"element": label, "section": section, "source_line": i + 1, "text": "\n".join(chunk)})
        kept.append(f"- {label}: {WITHHELD_NOTE}")
        i += span
    block = ""
    if elements:
        block = ("CONSENSUS AND ANALYST-DERIVED PACK ELEMENTS, withheld in pass 1 (the pack's own lines, verbatim, under the section each came from)"
                 + "\n".join(held) + "\n")
    return "\n".join(kept), block, elements


# S3 4.3 (2026-09-28): replaces the revision-14 RESEARCH_ADDENDUM. Old literal above this
# comment, in git history at 3d02fbd. Appended ONLY when the analyst is given search tools
# (consensus_valuation --tools). Keeps the leading "\n\n" that main() relies on when appending.
RESEARCH_ADDENDUM = """

RESEARCH RULES — you have web search, so do not assume what you can look up.
1. When your reasoning needs a fact you do not have, search for it while you reason; never substitute an assumption, a trend extrapolation or a placeholder. A number found to justify a conclusion you already reached is not evidence.
2. Do not search to re-verify filed figures: DATA 3-6 come from SEC filings and are authoritative. Research-brief figures are another model's claims; cite the filing when you rely on one. Search only for what neither the filings nor the brief can tell you.
3. Name the source of every retrieved figure inline. It stays [Actual] only if it came from the company or a regulator; a secondary report is [Estimate]. A number you could not establish is [Unconfirmed]: say what you could not resolve, and carry the uncertainty into the scenarios instead of burying it in a point estimate.
4. The written memorandum is the deliverable, not the tool calls. When your research is done, write the complete memorandum, SECTION 0 through SECTION 12, ending with the ```json:underwriting contract. A run that ends on tool output is discarded unread, however long it ran. Never write tool-call syntax as prose, and never treat a tool result as your answer."""


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    t = (args[0] if args else "GOOG").upper()
    model = _arg("--model", CONFIG["model"])
    ctx = int(_arg("--ctx", CTX))
    # CORRECTED 2026-08-20 by reading the deployed template, not by inference. The previous
    # default here was "max" with a comment claiming max requested the model's highest level.
    # It does not: Qwen3.8's chat template (line 63) validates against ('xhigh','medium','low')
    # and RAISES on anything else, so `think:"max"` returns HTTP 500 before a token is generated
    # — measured on rs2-analyst-deep, error `raise_exception('Unexpected reasoning effort max.
    # Supported types are xhigh (default), medium, and low.')`. Line 60 maps 'high' -> 'xhigh',
    # so "high" IS the maximum and is the correct value. Verified working: False (0ch thinking),
    # low (158ch), high (105ch); max 500s.
    # NOTE this only applies to a model carrying the real template. Production `rs2-analyst` has
    # a bare `{{ .Prompt }}` template, so it has NO reasoning-effort layer at all and the think
    # flag cannot reach the model however it is set.
    think = _arg("--think", "high")
    if think in ("true", "false"):
        think = think == "true"
    label = _arg("--label", f"{model.replace(':','_').replace('/','_')}-{think}")
    # Sampling: omitted entirely unless overridden, so the MODELFILE's profile governs.
    # rs2-analyst-deep bakes Qwen's thinking profile (0.6 / 0.95 / no penalties).
    temp = _arg("--temp")

    pack = build_pack(t)
    content = f"{pack}\n\n---\n\n{task_for(pack.facts)}"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = OUT / f"{t}_{ts}_{label}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "_pack.md").write_text(content, encoding="utf-8")
    print(f"[capability] {t} | model={model} think={think} ctx={ctx} | "
          f"pack {len(content):,} chars -> {d}", flush=True)

    opts = {"num_ctx": ctx, "num_predict": int(_arg("--num-predict", MAX_TOKENS))}
    if temp is not None:
        opts["temperature"] = float(temp)
    # --qwen-thinking applies Qwen's official thinking-mode profile as a REQUEST override, so a
    # model whose Modelfile bakes the non-thinking profile (production rs2-analyst: 0.4/0.9 with
    # presence 0.1 / repeat 1.05) can be tested on equal footing. Penalties go to zero: Qwen
    # documents that on long reasoning traces a repetition penalty bans common-but-necessary
    # tokens and degenerates the completion.
    if "--qwen-thinking" in sys.argv:
        opts.update({"temperature": float(temp) if temp is not None else 0.6, "top_p": 0.95,
                     "top_k": 20, "min_p": 0, "presence_penalty": 0.0, "repeat_penalty": 1.0})
    body = {"model": model, "stream": False, "think": think,
            "messages": [{"role": "user", "content": content}], "options": opts}
    req = urllib.request.Request(
        f"{CONFIG.get('ollama_url', 'http://localhost:11434')}/api/chat",
        data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        resp = json.loads(r.read().decode("utf-8"))
    msg = resp.get("message") or {}
    out, think = msg.get("content") or "", msg.get("thinking") or ""
    (d / "REPORT.md").write_text(out, encoding="utf-8")
    if think:
        (d / "_thinking.md").write_text(think, encoding="utf-8")
    print(f"[capability] done in {time.time()-t0:.0f}s | report {len(out):,} chars | "
          f"thinking {len(think):,} chars -> {d/'REPORT.md'}", flush=True)


if __name__ == "__main__":
    main()
