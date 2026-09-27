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
import base_rates  # noqa: E402
import growth_persistence  # noqa: E402
import world_news  # noqa: E402
import company_news  # noqa: E402
import catalyst_research  # noqa: E402
import consensus_reference  # noqa: E402

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
PACK_REVISION = 13

LAST_PACK_MACRO_DEGRADED = False
LAST_PACK_FLAGS = []
# Rule 11 (verdict stamping, C1 of the amendments + P4.3 prep): consensus_valuation.main() reads
# these two after a FRESH build_pack() call and copies them onto consensus.json as
# `active_shocks_at_verdict` and `momentum_state` — the exact §1.6/§2.5 blocks this pack printed,
# same T2-whitelisting pattern as LAST_PACK_MACRO_DEGRADED above. Unknown (None) after a frozen
# `--pack-file` run, which does not call build_pack() at all.
LAST_PACK_ACTIVE_SHOCKS = []
LAST_PACK_MOMENTUM_STATE = {}


class PackText(str):
    macro_degraded: bool = False
    flags: list = []

    def __new__(cls, content, macro_degraded=False, flags=None):
        obj = str.__new__(cls, content)
        obj.macro_degraded = bool(macro_degraded)
        obj.flags = list(flags or [])
        return obj

    def __add__(self, other):
        res = PackText(super().__add__(other),
                       macro_degraded=self.macro_degraded,
                       flags=self.flags)
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
})


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


def _default_exit_multiple_line(coe_anchor_pct, terminal_g):
    """Phase 4 E13: the exit multiple consistent with the anchors, (1 + g) / (COE - g). The desk
    fades the flow to terminal_g before the terminal, so any other multiple asserts another g."""
    if coe_anchor_pct is None or terminal_g is None or coe_anchor_pct / 100.0 <= float(terminal_g):
        return ("- DEFAULT EXIT MULTIPLE: not available (an anchor is missing); the desk prints "
                "implied_terminal_ev_fcf_gordon at your rate.")
    r, g = coe_anchor_pct / 100.0, float(terminal_g)
    return (f"- [Arithmetic] DEFAULT EXIT MULTIPLE (net capitalization rate at the anchors): "
            f"(1 + {g * 100:.2f}%) / ({r * 100:.2f}% \u2212 {g * 100:.2f}%) = {(1 + g) / (r - g):.2f}\u00d7 "
            f"the final-year cash flow: the multiple consistent with the terminal_g default. At another "
            f"rate (the Bear's wider rate) the desk prints the scenario's own as "
            f"implied_terminal_ev_fcf_gordon. A multiple whose implied terminal growth "
            f"(exit_implied_terminal_g) is more than 0.5 points from the terminal_g default needs "
            f"terminal_reason.")


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
    if not bad:
        return ("- **Effective tax rate: WITHHELD.** For this company the identity net income + "
                "tax == pre-tax income HOLDS in every year we can test, but holding is necessary "
                "and not sufficient - a domestic-only pre-tax paired with a domestic-only tax is "
                "self-consistent and still not the consolidated figure. Derive a rate yourself if "
                "you need one, and label it your own assumption.")
    return (f"- **Effective tax rate: WITHHELD, and for this company the inputs are PROVABLY "
            f"BROKEN.** Net income + tax does not equal pre-tax income, by more than 5%, in "
            f"FY{', FY'.join(str(y) for y in bad)}. Our pre-tax field admits a US-domestic-only "
            f"tag. Do not reconstruct a tax rate from those years.")


def _segment_note(t):
    """Verify the no-segment-data claim against THIS company's own filings rather than reciting
    a corpus-wide row count."""
    d = _sec_facts(t)
    if not d:
        return ("- **Segment revenue and margin in raw SEC XBRL: WE HAVE NONE.** "
                "Dimensional axes are stripped from the companyfacts API. See SECTION 11 for "
                "extracted segment economics and backlog.")
    n = sum(len(rows) for ns in (d.get("facts") or {}).values()
            for c in ns.values() for rows in (c.get("units") or {}).values())
    return (f"- **Segment revenue and margin in raw SEC XBRL: WE HAVE NONE.** Verified for this "
            f"company: of the {n:,} fact rows in raw SEC companyfacts, ZERO carry a dimension. "
            f"Segment breakdowns (e.g. Power, Wind, Electrification), contracted backlog, and "
            f"management guidance are retrieved and structured in SECTION 11.")


def _age(rec):
    """How old the aggregator record actually is, from its own `_fetched_at` stamp.

    ADDED 2026-08-24. SECTION 8 and SECTION 9 were labelled "[Aggregator]" with no date, so a
    price target fetched a month ago read exactly like one fetched this morning. Measured across
    the 171-name book on the day this was added: median 8 days old, p90 13, max 32. Analyst
    targets, short interest and the multiples all move inside that window, and the model has no
    way to discount a number whose age it cannot see. The depth pipeline does not refresh these
    sources, so the honest fix is to state the age rather than to imply currency.
    """
    ts = (rec or {}).get("_fetched_at")
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
    """Integer days since `_fetched_at`, or None when undatable. Companion to _age()."""
    ts = (rec or {}).get("_fetched_at")
    if not isinstance(ts, str) or len(ts) < 10:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(ts[:19])).days
    except ValueError:
        return None


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


def _decl(label, h, yrs, keys, held_note, gap_note):
    """One SECTION 12 line, decided by what THIS ticker's record actually contains.

    Emits HELD (with the years covered) or NOT EXTRACTED, so the declaration cannot drift out of
    agreement with the tables above it the way the hard-coded versions did.
    """
    years = sorted({y for k in keys for y in _held(h, yrs, k)})
    if not years:
        return f"- **{label}: NOT EXTRACTED for this company.** {gap_note}"
    span = f"{years[0]}" if len(years) == 1 else f"{years[0]}-{years[-1]}"
    partial = "" if len(years) == len(yrs) else f" of the {len(yrs)} years in SECTION 5"
    return (f"- **{label}: HELD**, {len(years)} year(s){partial} ({span}) - {held_note}")


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


def _fye_month_day(t, with_source=False):
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
    rec = (rs2_data.load_json(SD / "fundamentals_ttm.json") or {}).get("tickers", {}).get(t) or {}
    fy_end = rec.get("fy_leg_end")
    out = None
    if isinstance(fy_end, str) and len(fy_end) >= 10:
        try:
            d = _date.fromisoformat(fy_end[:10])
            out = (d.month, d.day, "ttm")
        except ValueError:
            pass
    if out is None:
        dates = _vendor_annual_dates(rs2_data.load_json(SD / "financials" / f"{t}.json") or {})
        out = (dates[0].month, dates[0].day, "vendor") if dates else (12, 31, "default")
    return out if with_source else out[:2]


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


def build_pack(t, price_override=None, include_research=True, asof=None):
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
    _ref_fy = None      # E18: the last full fiscal year's base and its age, for the reference
    _ref_fy_na = None   # E18: why that fiscal year cannot anchor the consensus path
    _aligned = None     # E18: the vendor's estimates start from the filed fiscal year (vintage test)
    _byc_printed = False  # the BASE-YEAR CHECK line printed its numbers (the window line points to it)
    if asof_date is not None:
        from datetime import timedelta as _td
        asof_cutoff = asof_date - _td(days=POINT_IN_TIME_FILING_LAG_DAYS)
        _fye_m, _fye_d = _fye_month_day(t)
        last_allowed_fy = _last_allowed_fiscal_year(asof_cutoff, _fye_m, _fye_d)
        include_research = False

    L = [f"# DATA PACK - {t}", ""]
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
    _yrs = [int(y) for y in (rs2_data.load_json(SD / "fundamentals_history.json") or {})
            .get("tickers", {}).get(t, {}) if str(y).isdigit()]
    ttm_stale = bool(ttm and _yrs
                     and int(str(ttm.get("fy_leg_end", ""))[:4] or 0) != max(_yrs))
    if ttm_stale or asof_date is not None:
        # asof mode: TODAY's TTM snapshot is not a point-in-time figure at all — see the
        # point-in-time TTM recomputation (from allowed quarters only) further below.
        f = {}
    qrec = (rs2_data.load_json(SD / "fundamentals_quarterly.json") or {}).get("tickers", {}).get(t) or {}
    qs = qrec.get("quarters") or []
    h = (rs2_data.load_json(SD / "fundamentals_history.json") or {}).get("tickers", {}).get(t) or {}
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
                f"after {cutoff_iso} excluded (SECTION 4)")
        qs = qs_allowed
        h_allowed = {y: v for y, v in h.items()
                    if str(y).isdigit() and int(y) <= last_allowed_fy}
        if len(h) != len(h_allowed):
            asof_omitted.append(
                f"fundamentals_history.json: fiscal year(s) after FY{last_allowed_fy} excluded "
                f"(SECTIONs 5/6/6A/6B/6C, GROWTH BASE RATES)")
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
                "TTM revenue/net income (SECTION 3): fewer than 4 quarters end on or before "
                f"{cutoff_iso}")
        asof_omitted.append(
            "TTM operating cash flow / capex / FCF / D&A (SECTION 3): fundamentals_quarterly.json "
            "carries no ocf/capex/fcf/da field at quarterly granularity, so these cannot be "
            "recomputed for any as-of date")
        if bat:
            asof_omitted.append("fundamentals_battery.json (SECTION 7, quality/solvency "
                                "measures): same-day snapshot, no stored history to restrict")
        bat = {}
        if ob:
            asof_omitted.append("openbb cache (SECTION 8 consensus & multiples, SECTION 10 "
                                "earnings transcript): same-day snapshot, no stored history")
        ob = {}
        met = {}
        if en:
            asof_omitted.append("enrich/*.json (SECTION 8 analyst targets/52-week range, "
                                "SECTION 9 positioning): same-day snapshot, no stored history")
        en = {}
        asof_omitted.append("SECTION 8.5 peer context: stocks.json is a same-day snapshot; "
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
    L += ["## SECTION 0 - HOW TO READ THIS PACK", "",
          f"- `{NULL}` means WE DO NOT HOLD THIS VALUE. It never means zero. A filed zero prints "
          f"as `$0.000B`.",
          "- `[Filed]` = reported to the SEC by the company. `[Arithmetic]` = exact arithmetic on "
          "filed values, with the window stated. `[Aggregator]` = a third-party vendor's "
          "restatement or estimate: useful, but not a filing, and its period is given where we "
          "know it.",
          "- Money is in billions of the reporting currency unless a line says otherwise.",
          "- Nothing here was verified by the code that assembled it. This is what our systems "
          "hold, with their known defects declared.",
          "",
          "**Series continuity warning - read this before relying on any multi-year trend.** Each "
          "column is assembled from whichever XBRL tag the company filed that year, and companies "
          "change tags. Our extract does NOT record which tag produced each number, so a change of "
          "reporting basis is indistinguishable here from a change in the business. A large step "
          "between adjacent years that never reverts is far more often a basis change than an "
          "event. Worked example, live in this dataset: Philip Morris shows revenue $73.91B in "
          "FY2015 and $26.68B in FY2016 - a 64% collapse that never happened. The company switched "
          "from reporting revenue including excise taxes to excluding them. Verify any step you "
          "intend to lean on; do not treat one as a business event on this pack's word alone.", ""]

    # Phase 4 T1: compute consensus next-FY revenue growth and growth base rates median
    # for Section 1.5's TERMINAL-GROWTH DEFAULT and Section 8's CONSENSUS-IMPLIED VALUE.
    yrs = sorted([int(y) for y in h if str(y).isdigit()])
    latest_rev = h.get(str(max(yrs)), {}).get("revenue") if yrs else None
    size_label, br_table = base_rates.base_rate_table(latest_rev, sd=SD, max_fiscal_year=last_allowed_fy)
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
        g_lbl, g_stats = growth_persistence.persistence_for_growth(
            g0, sd=SD, max_fiscal_year=last_allowed_fy)

    _med = (g_stats or {}).get("median") if g_stats else None
    if _med is None:
        _med = ((br_table or {}).get(5) or {}).get("p50")
    pack_median_5y = _med / 100.0 if isinstance(_med, (int, float)) else None

    enrich_est = (en.get("estimates") or {}) if en else {}
    pack_rev_g2 = consensus_reference.revenue_growth_next_fy(enrich_est)
    terminal_def_val = None
    terminal_def_reason = None

    # ---- SECTION 1 - IDENTITY & INSTITUTIONAL TAXONOMY -------------------------------------
    sector, industry = rs2_data.sector_lookup(t)
    
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

    L += ["## SECTION 1 - IDENTITY & TAXONOMY",
          f"- Ticker: {t} | Sector: {sector} | Canonical Industry: {canon_industry}",
          f"- Macro Strategic Cluster (1 of 24): {cluster}",
          f"- Primary Archetype Category: {archetype} (Deconstruct into constituent value drivers per Pillar 1)",
          f"- Fiscal year ends: {fy_end}   [derived from {fy_src}]",
          "- Rows below are labelled by FISCAL year, not calendar year.", ""]

    # ---- SECTION 1.5 / 1.6 - MACRO REGIME, COST OF CAPITAL, STATE OF THE WORLD --------------
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

        rf_src = coc["risk_free_source"].get("nominal_10y")
        rf_line = (f"- Nominal 10-Year US Treasury Yield (Risk-Free Rate Rf): {rf_pct:.2f}%  "
                   f"[point-in-time, {rf_src}]" if rf_pct is not None else
                   f"- Nominal 10-Year US Treasury Yield (Risk-Free Rate Rf): {ASOF_NULL}")
        real_line = (f"- Real 10-Year US Treasury Yield: {real_pct:.2f}%  [point-in-time, "
                    f"{coc['risk_free_source'].get('real_10y')}]" if real_pct is not None
                    else f"- Real 10-Year US Treasury Yield: {ASOF_NULL}")
        be_line = (f"- 10-Year Breakeven Inflation Rate: {be_pct:.2f}%  [point-in-time, "
                  f"{coc['risk_free_source'].get('breakeven_10y')}]" if be_pct is not None
                  else f"- 10-Year Breakeven Inflation Rate: {ASOF_NULL}")
        erp_line = (f"- Implied Equity Risk Premium (ERP): {erp_pct:.2f}%  [{erp_src}]"
                    if erp_pct is not None else
                    f"- Implied Equity Risk Premium (ERP): {ASOF_NULL}")
        coe_line = (f"- Implied Cost of Equity: {coe_pct:.2f}%  [point-in-time MRI anchor run, "
                   f"asof {coc.get('anchor_run_asof')}]" if coe_pct is not None else
                   f"- Implied Cost of Equity: {ASOF_NULL}  (no MRI anchor snapshot stored at or "
                   f"before this date)")
        if mri_sec is not None and anchor_load_val is not None:
            load_line = (f"- Sector Cost of Equity Loading ({mri_sec}): {anchor_load_val:.3f}x  "
                        f"[{_STRUCTURAL_LOADING_LABEL}]")
        elif mri_sec is not None:
            load_line = f"- Sector Cost of Equity Loading ({mri_sec}): {ASOF_NULL}"
        else:
            load_line = f"- Sector Cost of Equity Loading: {ASOF_NULL} (unmapped sector: {sector or 'none'})"

        adj_load_val, raw_load_val, _ = rs2_data.coe_loading(sector)
        if rf_pct is not None and adj_load_val is not None and erp_pct is not None:
            coe_anchor_pct = rf_pct + adj_load_val * erp_pct
            coe_anchor_line = (f"- COE ANCHOR for this name: rf {rf_pct:.2f}% + adjusted loading "
                                f"{adj_load_val:.3f}× (Blume: 0.67 × raw {raw_load_val:.3f} + 0.33) × implied ERP {erp_pct:.2f}% = "
                                f"{coe_anchor_pct:.2f}%  (asof {asof_date.isoformat()}, {erp_src}; "
                                f"{_STRUCTURAL_LOADING_LABEL})")
        else:
            coe_anchor_pct = None
            coe_anchor_line = f"- COE ANCHOR for this name: {ASOF_NULL}"

        if terminal_g_val is not None:
            terminal_g_line = (f"- Long-run nominal growth anchor for terminal_g: "
                                f"{terminal_g_val*100:.2f}%  [{_STRUCTURAL_TERMINAL_G_LABEL}]")
        else:
            terminal_g_line = (f"- Long-run nominal growth anchor for terminal_g: {ASOF_NULL}  "
                               f"({terminal_g_src})")

        be_val = be_pct / 100.0 if be_pct is not None else None
        terminal_def_val, terminal_def_reason = consensus_reference.terminal_default(
            terminal_g_val, be_val, pack_rev_g2, pack_median_5y)
        terminal_def_line = None
        if terminal_g_val is not None:
            if terminal_def_val != terminal_g_val:
                terminal_def_line = (
                    f"- TERMINAL-GROWTH DEFAULT for this name: {terminal_def_val * 100:.2f}% \u2014 "
                    f"next-FY consensus revenue growth ({pack_rev_g2 * 100:.1f}%) is below the anchor, "
                    f"so the default is the year-5 growth floored at zero real growth "
                    f"(10-year breakeven inflation {be_val * 100:.2f}%). "
                    f"terminal_g more than 0.5 points above or below it needs terminal_reason with dated evidence."
                )
            elif terminal_def_reason is not None and be_val is None:
                terminal_def_line = (
                    f"- TERMINAL-GROWTH DEFAULT for this name: {terminal_g_val * 100:.2f}% \u2014 "
                    f"next-FY consensus revenue growth ({pack_rev_g2 * 100:.1f}%) is below the anchor, "
                    f"but the 10-year breakeven inflation floor is not available, so the default remains the anchor. "
                    f"terminal_g more than 0.5 points above or below it needs terminal_reason with dated evidence."
                )

        sec_series = rs2_data.asof_secondary_macro_series(asof_date)
        t10y2y = sec_series["t10y2y"][0] if sec_series["t10y2y"] else None
        baa10y = sec_series["baa10y"][0] if sec_series["baa10y"] else None
        hy_oas = sec_series["hy_oas"][0] if sec_series["hy_oas"] else None
        if t10y2y is not None:
            slope = "Inverted" if t10y2y < 0 else "Normal / Steepening"
            t10y2y_line = (f"- 10Y-2Y Treasury Yield Spread (Curve Slope) [point-in-time, MRI "
                          f"raw_observations]: {t10y2y:+.2f}%  ({slope})  (as of "
                          f"{sec_series['t10y2y'][1]})")
        else:
            t10y2y_line = f"- 10Y-2Y Treasury Yield Spread (Curve Slope): {ASOF_NULL}"
        if baa10y is not None:
            baa_line = (f"- Investment Grade Credit Spread (BAA - 10Y) [point-in-time, MRI "
                       f"raw_observations]: {baa10y:.2f}%  (as of {sec_series['baa10y'][1]})")
        else:
            baa_line = f"- Investment Grade Credit Spread (BAA - 10Y): {ASOF_NULL}"
        if hy_oas is not None:
            hy_line = (f"- High Yield Option-Adjusted Spread (OAS) [point-in-time, MRI "
                      f"raw_observations]: {hy_oas:.2f}%  (as of {sec_series['hy_oas'][1]})")
        else:
            hy_line = f"- High Yield Option-Adjusted Spread (OAS): {ASOF_NULL}"

        regime = rs2_data.asof_regime_vector(asof_date)
        probs = regime["probabilities"] if regime else {}
        regime_headline = regime["headline"] if regime else None
        regime_fresh = regime is not None
        if regime is None:
            regime_line = f"- Current Macro Regime: {ASOF_NULL}"
        else:
            vec_items = [f"{k} {v:.3f}" for k, v in sorted(probs.items(), key=lambda x: -x[1])]
            margin_str = (f"margin {regime['margin']:.3f} — contested"
                         if regime.get("margin") is not None else "contested")
            regime_line = (f"- Current Macro Regime: Probabilities: [{', '.join(vec_items)}] | "
                          f"headline {regime_headline} ({margin_str})  [point-in-time, as of "
                          f"{regime['date']}]")

        anchor_meta_line = (f"- MRI Capital-Market Anchors Status: point-in-time reconstruction "
                            f"as of {asof_date.isoformat()} | anchor run used: "
                            f"{coc.get('anchor_run_asof') or ASOF_NULL} | degraded: "
                            f"{coc['degraded']} | reasons: "
                            f"{'; '.join(coc['degradation_reasons']) or 'none'}")

        L += ["## SECTION 1.5 - MACRO STATE & COST OF CAPITAL ANCHORS   [Primary Macro Context, "
              "point-in-time]",
              anchor_meta_line, rf_line, real_line, be_line, erp_line, coe_line, load_line,
              coe_anchor_line, terminal_g_line]
        if terminal_def_line:
            L.append(terminal_def_line)
        L += [t10y2y_line, baa_line, hy_line, regime_line]

        if rf_pct is not None:
            L.append(f"- **MANDATE:** Use the verified 10-Year Treasury yield above "
                     f"({rf_pct:.2f}%) as your base risk-free rate Rf for WACC. DO NOT search "
                     "the web for Treasury yields or cost of capital anchors; they are verified "
                     "above.")
        if coe_anchor_pct is not None:
            L.append(f"- **COE MANDATE:** Use `coe_used` within +-150 bp of the COE ANCHOR above "
                     f"({coe_anchor_pct:.2f}%), or declare `coe_source: \"own\"` with a "
                     f"`coe_adjustment_reason`. Vendor beta (SECTION 2) is context only, never "
                     "the input.")
        L.append("- **COST OF CAPITAL & CAPITALIZATION ANCHOR:** Derive terminal multiples from "
                 "net capitalization rates (1 / [WACC - g]) and verified peer comps; do not "
                 "force artificial multiple caps.")
        L.append(_default_exit_multiple_line(coe_anchor_pct, terminal_def_val if terminal_def_val is not None else terminal_g_val))
        L.append("")

        macro_degraded = bool(
            rf_pct is None or real_pct is None or be_pct is None or erp_pct is None
            or coe_pct is None or anchor_load_val is None or t10y2y is None or baa10y is None
            or hy_oas is None or coc["degraded"] or not regime_fresh
        )

        shock_state = rs2_data.asof_shock_register(asof_date)
        L16 = ["## SECTION 1.6 - STATE OF THE WORLD   [dated facts, not a forecast, "
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

        # 1) Nominal 10-Year (anchor first, secondary fallback)
        if anchor_rf_val is not None:
            rf_pct = anchor_rf_val * 100.0
            rf_line = f"- Nominal 10-Year US Treasury Yield (Risk-Free Rate Rf): {rf_pct:.2f}%  [MRI anchor, as of {anchor_asof or 'recent'}]"
        elif dgs10_sec is not None:
            rf_pct = float(dgs10_sec)
            rf_line = f"- Nominal 10-Year US Treasury Yield (Risk-Free Rate Rf): {rf_pct:.2f}%  [macro_state.json (secondary), as of {dgs10_series.get('as_of', 'recent')}]"
        else:
            rf_pct = None
            rf_line = f"- Nominal 10-Year US Treasury Yield (Risk-Free Rate Rf): {NULL}"

        # 2) Real 10-Year
        if anchor_real_val is not None:
            real_pct = anchor_real_val * 100.0
            real_line = f"- Real 10-Year US Treasury Yield: {real_pct:.2f}%  [MRI anchor]"
        else:
            real_pct = None
            real_line = f"- Real 10-Year US Treasury Yield: {NULL}"

        # 3) Breakeven 10-Year
        if anchor_be_val is not None:
            be_pct = anchor_be_val * 100.0
            be_line = f"- 10-Year Breakeven Inflation Rate: {be_pct:.2f}%  [MRI anchor]"
        else:
            be_pct = None
            be_line = f"- 10-Year Breakeven Inflation Rate: {NULL}"

        # 4) Implied ERP
        if anchor_erp_val is not None:
            erp_pct = anchor_erp_val * 100.0
            erp_line = f"- Implied Equity Risk Premium (ERP): {erp_pct:.2f}%  [MRI anchor]"
        else:
            erp_pct = None
            erp_line = f"- Implied Equity Risk Premium (ERP): {NULL}"

        # 5) Implied Cost of Equity
        if anchor_coe_val is not None:
            coe_pct = float(anchor_coe_val)
            coe_line = f"- Implied Cost of Equity: {coe_pct:.2f}%  [MRI anchor]"
        else:
            coe_pct = None
            coe_line = f"- Implied Cost of Equity: {NULL}"

        # 6) Sector Loading
        mri_sec = rs2_data.mri_sector_id(sector)
        if mri_sec is not None and anchor_load_val is not None:
            load_line = f"- Sector Cost of Equity Loading ({mri_sec}): {anchor_load_val:.3f}x  [MRI anchor]"
        elif mri_sec is not None:
            load_line = f"- Sector Cost of Equity Loading ({mri_sec}): {NULL}"
        else:
            load_line = f"- Sector Cost of Equity Loading: {NULL} (unmapped sector: {sector or 'none'})"

        # D3 (PHASE_4_PACK_SPEC.md): COE ANCHOR for this name = rf + Blume-adjusted sector loading x implied ERP —
        # the single number `coe_used` is measured against (+-150bp), not just its separate legs above.
        adj_load_val, raw_load_val, _ = rs2_data.coe_loading(sector)
        if rf_pct is not None and adj_load_val is not None and erp_pct is not None:
            coe_anchor_pct = rf_pct + adj_load_val * erp_pct
            _coe_asof_str = str(anchor_asof) if anchor_asof else NULL
            coe_anchor_line = (f"- COE ANCHOR for this name: rf {rf_pct:.2f}% + adjusted loading "
                                f"{adj_load_val:.3f}× (Blume: 0.67 × raw {raw_load_val:.3f} + 0.33) × implied ERP {erp_pct:.2f}% = "
                                f"{coe_anchor_pct:.2f}%  (asof {_coe_asof_str}, source: MRI cost-of-capital anchor)")
        else:
            coe_anchor_pct = None
            coe_anchor_line = f"- COE ANCHOR for this name: {NULL}"

        # D3: the long-run nominal growth anchor terminal_g must be built from, per P1.6/anchor_terminal_g().
        lrg_payload = rs2_data.usable_anchor("long_run_growth")
        terminal_g_val, terminal_g_src = rs2_data.anchor_terminal_g()
        if terminal_g_val is not None:
            tg_asof = lrg_payload.get("asof") if lrg_payload else None
            terminal_g_line = (f"- Long-run nominal growth anchor for terminal_g: "
                                f"{terminal_g_val*100:.2f}%  (asof {tg_asof or NULL})")
        else:
            terminal_g_line = f"- Long-run nominal growth anchor for terminal_g: {NULL}  ({terminal_g_src})"

        be_val = be_pct / 100.0 if be_pct is not None else None
        terminal_def_val, terminal_def_reason = consensus_reference.terminal_default(
            terminal_g_val, be_val, pack_rev_g2, pack_median_5y)
        terminal_def_line = None
        if terminal_g_val is not None:
            if terminal_def_val != terminal_g_val:
                terminal_def_line = (
                    f"- TERMINAL-GROWTH DEFAULT for this name: {terminal_def_val * 100:.2f}% \u2014 "
                    f"next-FY consensus revenue growth ({pack_rev_g2 * 100:.1f}%) is below the anchor, "
                    f"so the default is the year-5 growth floored at zero real growth "
                    f"(10-year breakeven inflation {be_val * 100:.2f}%). "
                    f"terminal_g more than 0.5 points above or below it needs terminal_reason with dated evidence."
                )
            elif terminal_def_reason is not None and be_val is None:
                terminal_def_line = (
                    f"- TERMINAL-GROWTH DEFAULT for this name: {terminal_g_val * 100:.2f}% \u2014 "
                    f"next-FY consensus revenue growth ({pack_rev_g2 * 100:.1f}%) is below the anchor, "
                    f"but the 10-year breakeven inflation floor is not available, so the default remains the anchor. "
                    f"terminal_g more than 0.5 points above or below it needs terminal_reason with dated evidence."
                )

        # Anchor metadata
        reasons_str = "; ".join(str(r) for r in anchor_reasons) if anchor_reasons else "none"
        degraded_str = str(anchor_degraded) if anchor_degraded is not None else NULL
        asof_str = str(anchor_asof) if anchor_asof else NULL
        anchor_meta_line = f"- MRI Capital-Market Anchors Status: as of {asof_str} | degraded: {degraded_str} | reasons: {reasons_str}"

        # Secondary macro series lines
        if t10y2y is not None:
            slope = 'Inverted' if float(t10y2y) < 0 else 'Normal / Steepening'
            t10y2y_line = f"- 10Y-2Y Treasury Yield Spread (Curve Slope) [macro_state.json]: {float(t10y2y):+.2f}%  ({slope})  [as of {t10y2y_series.get('as_of', 'recent')}]"
        else:
            t10y2y_line = f"- 10Y-2Y Treasury Yield Spread (Curve Slope) [macro_state.json]: {NULL}"

        if baa10y is not None:
            baa_line = f"- Investment Grade Credit Spread (BAA - 10Y) [macro_state.json]: {float(baa10y):.2f}%  [as of {baa10y_series.get('as_of', 'recent')}]"
        else:
            baa_line = f"- Investment Grade Credit Spread (BAA - 10Y) [macro_state.json]: {NULL}"

        if hy_oas is not None:
            hy_line = f"- High Yield Option-Adjusted Spread (OAS) [macro_state.json]: {float(hy_oas):.2f}%  [as of {hy_oas_series.get('as_of', 'recent')}]"
        else:
            hy_line = f"- High Yield Option-Adjusted Spread (OAS) [macro_state.json]: {NULL}"

        # Regime line
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
            regime_line = f"- Current Macro Regime: {NULL}"
        elif not regime_fresh:
            regime_headline = None
            regime_line = f"- Current Macro Regime: {NULL} (stale: {regime_date})"
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
            vec_str = ", ".join(vec_items) if vec_items else ""
            prob_str = f"Probabilities: [{vec_str}]" if vec_str else ""
            # B6 (Phase 1 approval review): the vector prints FIRST and the label second, as a
            # contested headline with its margin — never an unqualified regime name. Operator
            # ruling: the label is demoted and may no longer drive any numeric output.
            margin_str = f"margin {float(margin):.3f} — contested" if isinstance(margin, (int, float)) else "contested"
            headline_str = f"headline {regime_headline} ({margin_str})" if regime_headline else ""
            parts = [p for p in (prob_str, headline_str) if p]
            regime_line = (f"- Current Macro Regime: {' | '.join(parts)}  [as of {regime_date}]"
                           if parts else f"- Current Macro Regime: {NULL}")

        L += ["## SECTION 1.5 - MACRO STATE & COST OF CAPITAL ANCHORS   [Primary Macro Context]",
              anchor_meta_line,
              rf_line,
              real_line,
              be_line,
              erp_line,
              coe_line,
              load_line,
              coe_anchor_line,
              terminal_g_line]
        if terminal_def_line:
            L.append(terminal_def_line)
        L += [t10y2y_line,
              baa_line,
              hy_line,
              regime_line]

        if rf_pct is not None:
            L.append(f"- **MANDATE:** Use the verified 10-Year Treasury yield above ({rf_pct:.2f}%) as your base risk-free rate Rf for WACC. "
                     "DO NOT search the web for Treasury yields or cost of capital anchors; they are verified above.")

        # D3: the +-150bp CoE mandate. Printed unconditionally (an instruction, not a data line) —
        # when the anchor itself is unavailable this run, the second sentence tells the model exactly
        # what to do instead rather than leaving the mandate dangling against a missing number.
        if coe_anchor_pct is not None:
            L.append(f"- **COE MANDATE:** Use `coe_used` within +-150 bp of the COE ANCHOR above "
                     f"({coe_anchor_pct:.2f}%), or declare `coe_source: \"own\"` with a "
                     f"`coe_adjustment_reason`. Vendor beta (SECTION 2) is context only, never the input.")
        else:
            L.append("- **COE MANDATE:** the COE ANCHOR above is not available this run — declare "
                     "`coe_source: \"own\"` with a `coe_adjustment_reason` for whatever `coe_used` you "
                     "choose. Vendor beta (SECTION 2) is context only, never the input.")

        # B6 (Phase 1 approval review): the mandate no longer conditions on the regime LABEL.
        # Operator ruling: the label is demoted and must not drive any numeric output — it was
        # doing exactly that here, as the conditioning clause of the terminal-multiple instruction,
        # on a headline margin as thin as 0.044.
        L.append("- **COST OF CAPITAL & CAPITALIZATION ANCHOR:** Derive terminal multiples from "
                 "net capitalization rates (1 / [WACC - g]) and verified peer comps; do not force artificial multiple caps.")
        L.append(_default_exit_multiple_line(coe_anchor_pct, terminal_def_val if terminal_def_val is not None else terminal_g_val))
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

        L16 = ["## SECTION 1.6 - STATE OF THE WORLD   [dated facts, not a forecast]", ""]

        if regime_file and regime_date and regime_fresh:
            vec5 = [f"{k} {probs[k]:.3f}" if k in probs else f"{k} {NULL}"
                    for k in ("goldilocks", "reflation", "stagflation", "recession", "tightening")]
            margin_v = regime_file.get("headline_margin")
            margin_txt = f"{float(margin_v):.3f}" if isinstance(margin_v, (int, float)) else NULL
            L16.append(f"- MRI regime probability vector (as of {regime_date}): [{', '.join(vec5)}] | "
                      f"headline {regime_headline or NULL} (margin {margin_txt} - contested)")
        elif regime_file and regime_date:
            L16.append(f"- MRI regime probability vector: {NULL} (stale: {regime_date})")
        else:
            L16.append(f"- MRI regime probability vector: {NULL}")

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
        L16.append(f"- Nominal 10-Year Treasury yield: "
                  + (f"{rf_pct:.2f}%  (as of {_rate_asof})" if rf_pct is not None else NULL))
        L16.append(f"- Real 10-Year Treasury yield: "
                  + (f"{real_pct:.2f}%  (as of {_rate_asof})" if real_pct is not None else NULL))
        L16.append(f"- 10-Year breakeven inflation: "
                  + (f"{be_pct:.2f}%  (as of {_rate_asof})" if be_pct is not None else NULL))

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
    asof_price_data = None
    if asof_date is not None:
        # asof mode owns its own price sourcing entirely — any `price_override` the caller
        # passed is not consulted, because it carries no history to recompute SCR-10 from.
        asof_price_data = _asof_price_lookup(t, asof_date)
        if asof_price_data is None:
            asof_omitted.append(
                f"price (SECTION 2/2.5): no historical close found on or near "
                f"{asof_date.isoformat()} (network fetch failed or no listing that far back)")
        px = asof_price_data["price"] if asof_price_data else None
        sh = None
        if h:
            _hy_asof = [int(y) for y in h if str(y).isdigit()]
            if _hy_asof:
                sh = (h.get(str(max(_hy_asof))) or {}).get("shares_diluted")
        if sh is None:
            asof_omitted.append(
                "shares outstanding (SECTION 2): no shares_diluted held for any allowed fiscal "
                "year — TODAY's vendor share count is not point-in-time and was not used")
        mcap = (px * sh) if (isinstance(px, (int, float)) and isinstance(sh, (int, float))) else None
    else:
        px, sh = fin.get("Price"), fin.get("Shares_Outstanding")

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
        L += ["## DATA WARNINGS   [T2 sanity checks — read before trusting SECTION 2's figures]"]
        L += [f"- {w['message']}" for w in data_warnings]
        L.append("")

    if asof_date is not None:
        price_line = (f"- Price: ${px} [point-in-time close, as of "
                      f"{asof_price_data['asof']}]" if px is not None else f"- Price: {ASOF_NULL}")
        L += [f"## SECTION 2 - MARKET   [point-in-time, as of {asof_date.isoformat()}]",
              price_line,
              f"- Shares outstanding: {_n(sh)}   [source: shares_diluted, "
              f"FY{max((int(y) for y in h if str(y).isdigit()), default=NULL)} "
              f"(fundamentals_history.json) — the most recent allowed fiscal year, not TODAY's "
              f"vendor share count]" if sh is not None else f"- Shares outstanding: {ASOF_NULL}",
              f"- Market cap: {_b(mcap) if mcap is not None else ASOF_NULL}",
              f"- Beta: {ASOF_NULL}   [same-day vendor snapshot, no stored history]",
              "",
              f"- Total cash (vendor): {ASOF_NULL}   [same-day vendor snapshot; see SECTION 6 for "
              f"the filed, fiscal-year-restricted `cash` series]",
              f"- Total debt (vendor): {ASOF_NULL}   [same-day vendor snapshot; see SECTION 6 for "
              f"the filed, fiscal-year-restricted `long-term debt` series]",
              f"- Stock-based compensation (vendor): {ASOF_NULL}   [same-day vendor snapshot; "
              f"prefer the filed per-year SBC series in SECTION 5]", ""]
    elif price_override is not None:
        if isinstance(price_override, dict):
            live_px = price_override.get("price")
            live_asof = price_override.get("asof")
        else:
            live_px = float(price_override)
            live_asof = None
        asof_str = f", as of {live_asof}" if live_asof else ""
        vdate = _v(fin, 'Data_Fetched_Date')
        vpx = f"${px}" if px is not None else NULL
        price_line = f"- Price: ${live_px} [live quote{asof_str}]   [vendor quote: {vpx} as of {vdate}]"
        L += [f"## SECTION 2 - MARKET   [Aggregator - vendor quote as of {_v(fin, 'Data_Fetched_Date')}]",
              price_line,
              f"- Shares outstanding: {_n(sh)}   [source: vendor financials, as of "
              f"{_v(fin, 'Data_Fetched_Date')}]"
              + ("   <- ZERO on file. No per-share value is derivable for this name."
                 if sh == 0 else ""),
              f"- Market cap: {_b(fin.get('Market_Cap'))}",
              f"- Beta: {_v(cm, 'Beta')}   [Aggregator - the vendor does not state its window or "
              f"benchmark. No RS2 code consumes beta; it is here only if you want to build your own "
              f"cost of equity.]",
              "",
              "**The three figures below are the VENDOR's restatement of the last annual report - not "
              "live, and not our SEC extract. The filed series is in SECTION 6.**",
              f"- Total cash (vendor): {_b(fin.get('Total_Cash'))}",
              f"- Total debt (vendor): {_b(fin.get('Total_Debt'))}   [our filed extract maps LONG-TERM "
              f"debt only, so the two legitimately differ - and neither is a complete debt figure]",
              f"- Stock-based compensation (vendor): {_b(fin.get('SBC_Stock_Based_Comp'))}   [the "
              f"period is NOT reliably trailing-twelve-months; on most names it is a fiscal year. "
              f"Prefer the filed per-year SBC series in SECTION 5 where it is present]", ""]
    else:
        price_line = f"- Price: ${px}" if px is not None else f"- Price: {NULL}"
        L += [f"## SECTION 2 - MARKET   [Aggregator - vendor quote as of {_v(fin, 'Data_Fetched_Date')}]",
              price_line,
              f"- Shares outstanding: {_n(sh)}   [source: vendor financials, as of "
              f"{_v(fin, 'Data_Fetched_Date')}]"
              + ("   <- ZERO on file. No per-share value is derivable for this name."
                 if sh == 0 else ""),
              f"- Market cap: {_b(fin.get('Market_Cap'))}",
              f"- Beta: {_v(cm, 'Beta')}   [Aggregator - the vendor does not state its window or "
              f"benchmark. No RS2 code consumes beta; it is here only if you want to build your own "
              f"cost of equity.]",
              "",
              "**The three figures below are the VENDOR's restatement of the last annual report - not "
              "live, and not our SEC extract. The filed series is in SECTION 6.**",
              f"- Total cash (vendor): {_b(fin.get('Total_Cash'))}",
              f"- Total debt (vendor): {_b(fin.get('Total_Debt'))}   [our filed extract maps LONG-TERM "
              f"debt only, so the two legitimately differ - and neither is a complete debt figure]",
              f"- Stock-based compensation (vendor): {_b(fin.get('SBC_Stock_Based_Comp'))}   [the "
              f"period is NOT reliably trailing-twelve-months; on most names it is a fiscal year. "
              f"Prefer the filed per-year SBC series in SECTION 5 where it is present]", ""]

    # ---- SECTION 2.5 - PRICE ACTION (facts, not a valuation input)   [P4.1, amended by B1] ---
    if asof_date is not None:
        # D10/E4.3: recomputed directly from historical closes ending at `asof`, never from
        # factor_scores.json (a same-day snapshot with no history).
        scr10 = (_scr10_from_series(asof_price_data["series"], asof_date.isoformat())
                 if asof_price_data else {})

        def _mpct(v):
            return f"{v*100:+.1f}%" if isinstance(v, (int, float)) else ASOF_NULL

        L += [f"## SECTION 2.5 - PRICE ACTION (facts, not a valuation input)   [recomputed from "
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
        L += [f"## SECTION 2.5 - PRICE ACTION (facts, not a valuation input)   [Arithmetic on price "
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
              f"- The stock moved {mom_1m_str} in 1 month and {mom_6m_str} in 6 months (SECTION 2.5)."]
        news_rows = cnews.get("rows") or []
        if news_rows:
            for nr in news_rows:
                d_str = nr.get("date") or "undated"
                src = nr.get("source") or "unknown"
                tit = nr.get("title") or ""
                u = nr.get("url") or ""
                snip = nr.get("snippet") or ""
                L.append(f"- {d_str} | {src} | {tit} | {u} | {snip}")
                if nr.get("excerpt"):
                    _rf = urllib.parse.urlparse(nr.get("read_from") or u).hostname or "?"
                    L.append(f"  > read from {_rf[4:] if _rf.startswith('www.') else _rf}: {nr['excerpt']}")
        else:
            unresp = cnews.get("unresponsive_engines") or []
            errs = cnews.get("errors") or []
            details = []
            if unresp:
                details.append(f"unresponsive engines: {', '.join(unresp)}")
            if errs:
                details.append(f"errors: {'; '.join(errs)}")
            err_str = "; ".join(details) if details else "no news returned"
            L.append(f"- no news returned ({err_str})")
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
    if asof_date is not None:
        L.append(f"## SECTION 3 - TRAILING TWELVE MONTHS   [point-in-time: revenue/net income "
                 f"recomputed from the 4 trailing allowed quarters]")
        if asof_ttm_recomputed:
            L += [f"- Revenue: {_b(asof_ttm_recomputed['revenue'])}   [Arithmetic, sum of the 4 "
                  f"quarters through {asof_ttm_recomputed['through']}]",
                  f"- Net income: {_b(asof_ttm_recomputed['net_income'])}   [Arithmetic, same "
                  f"window]",
                  f"- Operating cash flow: {ASOF_NULL}   [fundamentals_quarterly.json carries no "
                  f"ocf field]",
                  f"- Capital expenditure: {ASOF_NULL}   [fundamentals_quarterly.json carries no "
                  f"capex field]",
                  f"- Free cash flow: {ASOF_NULL}   [fundamentals_quarterly.json carries no fcf "
                  f"field]",
                  "- Depreciation & amortisation: not carried in the TTM extract for ANY name."]
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
            oe = ni + da - capex
            _ref_oe = oe
            _ref_da, _ref_capex = da, capex
            L.append(f"- [Arithmetic] OWNER EARNINGS (default base_cf): TTM net income {_b(ni)} + D&A (FY{latest_yr}) {_b(da)} \u2212 TTM capex {_b(capex)} = {_b(oe)}. Stock compensation is already expensed in net income, so it is counted once (sbc_treatment \"deducted_in_cf\"); working-capital swings are excluded. Net income is after interest, so this is an equity flow: value it in the equity frame. Use this as base_cf unless base_cf_reason states why another base is more representative.")
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
            L.append(f"- OWNER EARNINGS (default base_cf): not available (point-in-time) \u2014 {missing_str} missing")
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
        L.append(f"## SECTION 3 - TRAILING TWELVE MONTHS   [Filed - SEC 10-Q derived; through "
                 f"{_v(ttm, 'through')}, filed {_v(ttm, 'filed')}]")
        if f:
            L += [f"- Revenue: {_b(f.get('revenue'))}",
                  f"- Net income: {_b(f.get('net_income'))}",
                  f"- Operating cash flow: {_b(f.get('ocf'))}",
                  f"- Capital expenditure: {_b(f.get('capex'))}",
                  f"- Free cash flow: {_b(f.get('fcf'))}",
                  "- Depreciation & amortisation: not carried in the TTM extract for ANY name (the TTM "
                  "build maps five fields only). Use the fiscal-year series in SECTION 5."]
            ni, ocf = f.get("net_income"), f.get("ocf")
            if isinstance(ni, (int, float)) and isinstance(ocf, (int, float)):
                L.append(f"- [Arithmetic] Net income minus operating cash flow: {_b(ni - ocf)}")
        elif ttm_stale:
            L.append(f"{NULL} - our TTM record for this name is STRANDED: its fiscal anchor "
                     f"({ttm.get('fy_leg_end')}) disagrees with the newest annual year we hold "
                     f"({max(_yrs)}), so it is not this company's trailing twelve months and has been "
                     f"withheld rather than shown with a wrong period label. Use SECTION 5.")
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
        _fye_mm = _fye_dd = _fye_src = _fy_end_dt = _fye_conflict = None
        if latest_yr is not None:
            _fye_mm, _fye_dd, _fye_src = _fye_month_day(t, with_source=True)
            _vend, _fye_conflict = ((_vendor_fy_end_for(fin, _fy_rec.get("net_income"), int(latest_yr),
                                                         (h.get(str(int(latest_yr) - 1)) or {}).get("net_income")))
                                    if _fye_src != "ttm" else (None, None))
            _fy_end_dt = _vend or _fy_end_date_for(int(latest_yr), _fye_mm, _fye_dd)
        _ven_capex_ok, _ven_capex_why = _vendor_capex_usable(fin, _fy_end_dt)
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
        # E18: the CONSENSUS-IMPLIED VALUE's base is the last full fiscal year, the period consensus
        # growth is measured from, valued at that year end and rolled forward to today. A TTM base
        # with fiscal-year growth counted part of the current year twice (ADI +29%, AMD +35%).
        if latest_yr is not None:
            _stub = (datetime.now().date() - _fy_end_dt).days / 30.4375
            _fy_cx = _fy_rec.get("capex")
            if not isinstance(_fy_cx, (int, float)) and _ven_capex_ok:
                _vc = fin.get("Capital_Expenditure")
                _fy_cx = -float(_vc) if isinstance(_vc, (int, float)) and _vc < 0 else None
            _fy_ni, _fy_da = _fy_rec.get("net_income"), _fy_rec.get("da")
            # Whole-book test (2026-09-26): the period comes from the consensus vintage, not the
            # calendar. Past a fiscal year end the vendor keeps the finished year as "current" until
            # it is reported (EPAC, PSMT, MU: year-ago revenue = the filed FY2025 to the dollar), and
            # then moves past it before our filings hold it.
            from datetime import date as _date
            try:
                _thr = _date.fromisoformat(str(ttm.get("through"))[:10]) if f else None
            except ValueError:
                _thr = None
            _newest = max(d for d in (_fy_end_dt, _thr) if d is not None)
            _age = (datetime.now().date() - _newest).days / 30.4375
            _aligned = consensus_reference.vintage_aligned(en.get("estimates") if en else None,
                                                           _fy_rec.get("revenue"))
            if _fye_src == "default":
                _ref_fy_na = "the fiscal year end is unknown (no TTM record and no dated vendor statement)"
            elif _fye_conflict is not None:
                _ref_fy_na = (f"the label year cannot be confirmed: the vendor's statements with FY{latest_yr}'s "
                              f"and FY{int(latest_yr) - 1}'s net income are dated a year apart from ours "
                              f"({_fye_conflict.isoformat()})")
            elif _stub < 0:
                _ref_fy_na = f"FY{latest_yr} ends {_fy_end_dt.isoformat()}, after today"
            elif _age > consensus_reference.STALE_MONTHS:
                _ref_fy_na = (f"stale history: the newest period we hold ends {_newest.isoformat()}, "
                              f"{_age:.0f} months ago")
            elif _stub > 12 and _aligned is not True:
                # review B1: a failed or unknown vintage test is "not verified", never "rolled"
                _ref_fy_na = (f"not verified: FY{latest_yr} ended {_stub:.0f} months ago and the vendor's "
                              + ("year-ago revenue does not match its filed revenue within 2%" if _aligned is False
                                 else "year-ago revenue is not available")
                              + ", so the year consensus starts from cannot be checked")
            else:
                _ref_fy = {"stub": _stub,
                           "label": f"FY{latest_yr}, the last full fiscal year, ended {_fy_end_dt.isoformat()}",
                           "da": _fy_da if isinstance(_fy_da, (int, float)) else None,
                           "capex": _fy_cx,
                           "base": (_fy_ni + _fy_da - _fy_cx)
                           if all(isinstance(x, (int, float)) for x in (_fy_ni, _fy_da, _fy_cx)) else None,
                           # review B1: the vendor's EPS levels meet filed D&A and capex only when
                           # the vintage test shows the two describe the same year and currency
                           "levels_block": (None if _aligned is True else
                                            f"the vendor's year-ago revenue does not match FY{latest_yr}'s "
                                            f"filed revenue within 2% (currency, perimeter or period)"
                                            if _aligned is False else
                                            f"the vendor's year-ago revenue is not available to check "
                                            f"against FY{latest_yr}'s filed revenue")}
                # the FY and TTM windows are compared only when the TTM is this fiscal year's own
                if f and _thr is not None and not ttm_stale and oe_src == ["ttm", "ttm"]:
                    _ref_fy["quarters"] = max(0, round((_thr - _fy_end_dt).days / 30.4375 / 3))
                    _ref_fy["through"] = _thr.isoformat()

        if isinstance(ni, (int, float)) and isinstance(da, (int, float)) and isinstance(capex, (int, float)):
            oe = ni + da - capex
            _ref_oe = oe
            _ref_da, _ref_capex = da, capex
            L.append(f"- [Arithmetic] OWNER EARNINGS (default base_cf): {ni_src} {_b(ni)} + D&A (FY{latest_yr}) {_b(da)} \u2212 {capex_src} {_b(capex)} = {_b(oe)}{oe_tag}. Stock compensation is already expensed in net income, so it is counted once (sbc_treatment \"deducted_in_cf\"); working-capital swings are excluded. Net income is after interest, so this is an equity flow: value it in the equity frame. Use this as base_cf unless base_cf_reason states why another base is more representative.")
            _sbc_fy = (h.get(str(latest_yr)) or {}).get("sbc") if latest_yr is not None else None
            if isinstance(ocf, (int, float)) and isinstance(_sbc_fy, (int, float)):
                L.append(f"- [Arithmetic] CASH BASIS (alternative base_cf): TTM operating cash flow {_b(ocf)} \u2212 {capex_src} {_b(capex)} \u2212 stock compensation (FY{latest_yr}) {_b(_sbc_fy)} = {_b(ocf - capex - _sbc_fy)}. Includes working-capital swings and, like every flow here, is after interest; declare base_cf_basis \"other\" with base_cf_reason if you use it.")
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
            L.append(f"- OWNER EARNINGS (default base_cf): not available \u2014 {missing_str} missing; declare your base and why.")
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
    L.append(f"## SECTION 4 - QUARTERLY   [Filed - 10-Q; all {len(qs)} quarters we hold, oldest "
             f"first]")
    if qs:
        L += [_row(["period end", "revenue", "net income", "gross profit", "YoY revenue",
                    "YoY net income"]),
              _row(["---"] * 6)]
        for r in qs:
            L.append(_row([str(r.get("end") or NULL), _b(r.get("revenue")),
                           _b(r.get("net_income")), _b(r.get("gross_profit")),
                           _n(r.get("yoy_revenue"), "{:+.1f}%"),
                           _n(r.get("yoy_net_income"), "{:+.1f}%")]))
    else:
        L.append(f"{NULL} - no quarterly record held for this name.")
    L.append("")

    yrs = sorted(int(y) for y in h) if h else []

    # ---- SECTION 5 -------------------------------------------------------------------------
    L.append(f"## SECTION 5 - FISCAL-YEAR INCOME & CASH FLOW   [Filed - SEC companyfacts; all "
             f"{len(yrs)} years we hold]")
    if yrs:
        L += [_row(["FY", "revenue", "gross profit", "operating income", "net income", "OCF",
                    "capex", "FCF", "D&A", "SG&A", "interest expense", "SBC",
                    "cash basis [Arithmetic]"]),
              _row(["---"] * 13)]
        for y in yrs:
            r = h[str(y)]
            L.append(_row([str(y), _b(r.get("revenue")), _b(r.get("gross_profit")),
                           _b(r.get("operating_income")), _b(r.get("net_income")),
                           _b(r.get("ocf")), _b(r.get("capex")), _b(r.get("fcf")), _b(r.get("da")),
                           _b(r.get("sga")), _b(r.get("interest_expense")), _b(r.get("sbc")),
                           _b(owner_cf(r.get("ocf"), r.get("capex"), r.get("sbc")))]))
        if _held(h, yrs, "sbc"):
            L += ["",
                  "- `SBC` is stock-based compensation as filed, per fiscal year. It is a real "
                  "expense that is added back in OCF, so an owner-earnings figure that starts from "
                  "OCF and does not subtract it is overstated. Use this series, not the single "
                  "vendor scalar in SECTION 2, whose period is unreliable."]
        L += ["",
              "- `cash basis [Arithmetic]` = OCF minus capex minus SBC, on the filed values in "
              "this table and nothing else. Exact arithmetic, NOT a normalisation, and blank "
              "where any of the three inputs is absent."]
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

    # ---- GROWTH BASE RATES   [D11 / AMENDMENTS.md E2] --------------------------------------
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
    L += ["- **MANDATE:** stage-1 or fade growth above the p90 for this size bucket requires dated, "
          "company-specific evidence (e.g. signed capacity/backlog contracts, disclosed AI-demand "
          "commitments) - a growth rate alone is not evidence. This is a flag, not a veto.",
          "- Survivorship caveat: this sample holds only companies that still exist today - failed "
          "and delisted companies are absent - so every rate above is biased upward. Source: our "
          "own screener corpus (fundamentals_history.json), not a published third-party table.",
          ""]

    # ---- SECTION 6 -------------------------------------------------------------------------
    L.append("## SECTION 6 - FISCAL-YEAR BALANCE SHEET & CAPITAL STRUCTURE   [Filed, except columns marked [Arithmetic]]")
    if yrs:
        # Unambiguous Net Liquidity Card (prevents column-slip and guessing leverage)
        latest_y = max(yrs)
        lr = h.get(str(latest_y), {})
        cash_val = lr.get("cash") or fin.get("Total_Cash")
        raw_debt = lr.get("lt_debt")
        vendor_debt = fin.get("Total_Debt")
        effective_debt = raw_debt if (raw_debt is not None and raw_debt > 0) else vendor_debt

        L.append("**EXPLICIT LIQUIDITY & CAPITAL STRUCTURE CARD (Zero-Guess Anchor):**")
        if cash_val is not None:
            L.append(f"- Total Cash & Cash Equivalents: {_b(cash_val)}")
        if effective_debt is not None:
            L.append(f"- Total Debt (Filed / Vendor): {_b(effective_debt)}")
        sti_val = lr.get("st_investments")
        if cash_val is not None and effective_debt is not None:
            _sti = sti_val if isinstance(sti_val, (int, float)) else 0.0
            net_liq = cash_val + _sti - effective_debt
            net_desc = f"Net Cash +{_b(net_liq)}" if net_liq >= 0 else f"Net Debt -{_b(abs(net_liq))}"
            L.append(f"- Net Liquidity Position: **{net_desc}** (Cash + short-term investments minus Total Debt)")
            # E12: one filed figure, used as net_debt in the firm frame (four samples had used four).
            # E13: the equity frame is the default; the firm frame needs a pre-interest flow.
            _sti_txt = _b(sti_val) if isinstance(sti_val, (int, float)) else "$0.000B (none filed)"
            L.append(f"- [Arithmetic] NET DEBT (net_debt for the firm frame, which needs a pre-interest flow): total debt "
                     f"{_b(effective_debt)} \u2212 cash {_b(cash_val)} \u2212 short-term investments "
                     f"{_sti_txt} = {'-' if net_liq > 0 else ''}{_b(abs(net_liq))} (negative = net cash). "
                     f"The equity frame (the default) takes no net_debt: the pack's flows are after interest, "
                     f"so the debt's cost is already in them, and cash counts through the interest it earns "
                     f"(which understates a very large cash pile; say so if it matters). In the firm frame use "
                     f"it as net_debt unless net_debt_reason says why.")
        L.append("")

        # 6A: Working Capital & Operating Assets (8 columns, clean and focused)
        L.append("### SECTION 6A - WORKING CAPITAL & OPERATING ASSETS")
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
            L.append(_row([str(y), _b(r.get("total_assets")), _b(ca), _b(cl), _b(wc), _b(dwc),
                           _b(r.get("receivables")), _b(r.get("inventory"))]))
        L.append("")

        # 6B: Capital Structure, Debt & Equity (7 columns, clean and distinct from operating assets)
        L.append("### SECTION 6B - CAPITAL STRUCTURE, DEBT & EQUITY")
        L += [_row(["FY", "cash", "long-term debt", "total liabs",
                    "equity", "retained earnings", "wtd-avg shares"]),
              _row(["---"] * 7)]
        for y in yrs:
            r = h[str(y)]
            y_debt = r.get("lt_debt") if r.get("lt_debt") is not None else (vendor_debt if y == latest_y else None)
            L.append(_row([str(y), _b(r.get("cash")), _b(y_debt),
                           _b(r.get("total_liabilities")), _b(r.get("equity")),
                           _b(r.get("retained_earnings")), _n(r.get("shares_diluted"))]))
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
        L.append("### SECTION 6C - DETAILED DEBT COMPONENTS & INVESTMENTS   [Filed. Columns absent for this "
                 "company are omitted entirely rather than shown empty]")
        L += [_row(["FY"] + [lbl for _, lbl in present]), _row(["---"] * (len(present) + 1))]
        for y in yrs:
            r = h[str(y)]
            L.append(_row([str(y)] + [_b(r.get(k)) for k, _ in present]))
        L += ["",
              "- **WE DO NOT KNOW WHETHER THESE COLUMNS OVERLAP, SO WE DO NOT SUM THEM.** Which "
              "XBRL tag produced each number is not recorded (see SECTION 0), and the two "
              "long-term columns are measurably not interchangeable: across the live book they "
              "are identical on 72 of the 80 companies that carry both and disagree on 8, in one "
              "case by a factor of 650 (Marriott files $0.023B under one tag and $14.995B under "
              "the other). `current portion` and `short-term borrowings` agree on only 10 of the "
              "35 names carrying both. So a total-debt figure is NOT provided here: adding these "
              "cells would double-count on most names, and picking one tag per company is a "
              "judgment call. YOU decide which components belong in your net-debt figure, and say "
              "which you used.",
              "- The vendor's own total-debt scalar in SECTION 2 is an independent cross-check "
              "built on a different definition. Where it disagrees with every column here, treat "
              "the discrepancy as unresolved rather than picking the number that suits the case.",
              "- Investments columns are securities held outside `cash`. Omitting them from net "
              "debt overstates leverage; on this book they run a median 32% of the cash balance."]
        L.append("")

    # ---- SECTION 7 -------------------------------------------------------------------------
    if asof_date is None:
        if bat:
            L += [f"## SECTION 7 - FILING-DERIVED QUALITY MEASURES   [Arithmetic on filed values; each "
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
                  f"- Revenue CAGR, trailing 5 fiscal years: {_pct(bat.get('revenue_cagr_5y'))}",
                  f"- Years of history available: {_v(bat, 'years_available')}",
                  f"- Share-count split suspected in the series: "
                  f"{_v(bat, 'share_count_split_suspected')}",
                  "",
                  "The Beneish M-score is deliberately omitted: it imputes absent inputs and then "
                  "publishes a score, which would present a guess as a measurement.", ""]

        # ---- SECTION 8 -------------------------------------------------------------------------
        # P4.10 staleness: past STALE_SUPPRESS_DAYS the header shows "STALE (n days)" AND the values
        # themselves are suppressed to STALE_NULL, rather than merely flagged (_age()'s 14-day note).
        fg = ob.get("forward_growth") or {}
        ob_stale = bool((_age_days(ob) or 0) > STALE_SUPPRESS_DAYS)
        en_stale = bool((_age_days(en) or 0) > STALE_SUPPRESS_DAYS)
        L += [f"## SECTION 8 - CONSENSUS & MULTIPLES   [Aggregator, {_age_label(ob)}]",
              # price_to_sales dropped 2026-08-20: measured non-null on 0 of 294 vendor records, so
              # the line could never print a value. Market cap and revenue are both in this pack;
              # the model can divide. A field that is structurally always absent is noise, not a
              # disclosed gap.
              f"- Trailing P/E: {_sv(met, 'pe_ratio', ob_stale)}   |   P/B: "
              f"{_sv(met, 'price_to_book', ob_stale)}   |   PEG: {_sv(met, 'peg_ratio', ob_stale)}   "
              f"[trailing; the vendor does not state the period]",
              f"- Return on equity: {_sv(met, 'return_on_equity', ob_stale)}   |   gross margin: "
              f"{_sv(met, 'gross_margin', ob_stale)}   |   operating margin: "
              f"{_sv(met, 'operating_margin', ob_stale)}   |   dividend yield: "
              f"{_sv(met, 'dividend_yield', ob_stale)}   [vendor-computed, expressed as fractions not "
              f"percents]"]
        est = en.get("estimates") if en else None
        _civ_na = None   # why SECTION 8 has no CONSENSUS-IMPLIED VALUE (E10)
        if en_stale:
            L.append("- CONSENSUS ESTIMATES: not available \u2014 stale (> 45 days)")
            _civ_na = "consensus estimates stale"
        elif not en:
            L.append("- CONSENSUS ESTIMATES: not available \u2014 enrich record missing")
            _civ_na = "no consensus estimates"
        elif not est or not isinstance(est, dict):
            L.append("- CONSENSUS ESTIMATES: not available \u2014 yfinance estimates unavailable")
            _civ_na = "no consensus estimates"
        else:
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
            # review B4 (2026-09-27): only when the vendor's figures and ours are on one basis: the
            # vintage test passes and our filed share count agrees with the pack's (APH read -50%
            # across a split, ADS names read +290% and +2168%)
            _sh_ok = (isinstance(sh, (int, float)) and sh > 0 and isinstance(_fy_sh_x, (int, float))
                      and abs(_fy_sh_x / sh - 1) <= consensus_reference.LEVEL_TOL)
            if (isinstance(_ya, (int, float)) and _ya > 0 and isinstance(_fy_ni_x, (int, float))
                    and isinstance(_fy_sh_x, (int, float)) and _fy_sh_x > 0 and _fy_ni_x != 0
                    and not (_aligned is True and _sh_ok)):
                L.append(f"- BASE-YEAR CHECK: not available \u2014 "
                         + (f"the vendor's year-ago revenue does not match FY{latest_yr}'s filed revenue within 2%"
                            if _aligned is False else
                            f"the vendor's year-ago revenue is not available to check against FY{latest_yr}'s "
                            f"filed revenue" if _aligned is None else
                            "SECTION 2 holds no share count" if not (isinstance(sh, (int, float)) and sh > 0) else
                            f"our filed FY{latest_yr} diluted share count ({_fy_sh_x / 1e9:.3f}B) and SECTION 2's "
                            f"({sh / 1e9:.3f}B) differ by more than 15% (a split, ADS units or share classes)")
                         + ", so the vendor's year-ago EPS and ours cannot be shown to be on one basis.")
            elif (isinstance(_ya, (int, float)) and _ya > 0 and isinstance(_fy_ni_x, (int, float))
                    and isinstance(_fy_sh_x, (int, float)) and _fy_sh_x > 0 and _fy_ni_x != 0):
                _fy_eps = _fy_ni_x / _fy_sh_x
                _byc_printed = True
                L.append(f"- [Arithmetic] BASE-YEAR CHECK: consensus measures current-FY EPS growth from a "
                         f"year-ago EPS of ${_ya:.2f}; our filed FY{latest_yr} EPS is ${_fy_eps:.2f} (net income / "
                         f"diluted shares), {(_ya / _fy_eps - 1) * 100:+.0f}% apart. A large gap means the "
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
                _coe = coe_anchor_pct / 100.0 if isinstance(coe_anchor_pct, (int, float)) else None
                _fy = _ref_fy or {}
                _ref = consensus_reference.build(
                    _fy.get("base"), est, _coe,
                    terminal_def_val if terminal_def_val is not None else terminal_g_val,
                    sh if isinstance(sh, (int, float)) and sh > 0 else None,
                    _med / 100.0 if isinstance(_med, (int, float)) else None,
                    da=_fy.get("da"), capex=_fy.get("capex"),
                    stub_months=_fy.get("stub"), base_label=_fy.get("label"),
                    levels_reason=_fy.get("levels_reason"), levels_block=_fy.get("levels_block"),
                    anchor=terminal_g_val)
                if not _ref_fy and _ref.get("value") is None and _ref_fy_na:
                    _ref["reason"] = _ref_fy_na
                # E15: outside the fail-fast fence the reference is not a credible summary of the
                # consensus (spot commodity earnings carried forward as a perpetuity): say which
                # side, print the fence, never the number
                try:
                    import valuation_backbone as _vb
                    _band = _vb._consensus_band(t)
                except Exception:
                    _band = None
                _side, _fence = _reference_outside_fence((_ref or {}).get("value"), _band)
                if _side:
                    L.append(f"- CONSENSUS-IMPLIED VALUE: not used — the consensus path carried forward at our "
                             f"discount rate lands {_side} the fence [${_fence[0]:,.2f}, ${_fence[1]:,.2f}] built "
                             f"from the street's targets (0.5× the lowest and 2× the highest analyst target, each "
                             f"discounted by 10%), so it is not a credible summary of the consensus "
                             f"(reference_status: outside_fence_{_side}).")
                else:
                    _tg_used = (terminal_def_val if terminal_def_val is not None else terminal_g_val) or 0.0
                    L.append(consensus_reference.pack_line(_ref, _fy.get("base"), _coe or 0.0, _tg_used, _b, anchor=terminal_g_val))
                    _win = consensus_reference.window_check(_ref, _fy.get("base"), _ref_oe, _fy.get("quarters"))
                    if _win and _win.get("ttm_value") is not None:
                        _wside, _wfence = _reference_outside_fence(_win["ttm_value"], _band)
                        _win = consensus_reference.fence_window(_win, _wside, _wfence)
                    _wl = consensus_reference.window_line(_win, _ref, _ref_oe, _fy.get("through"), _b,
                                                          base_year_check=_byc_printed)
                    if _wl:
                        L.append(_wl)
        if _civ_na and asof_date is None:
            L.append(f"- CONSENSUS-IMPLIED VALUE: not available \u2014 {_civ_na}")
        if en:
            L += [f"- Analyst price targets: low {_sv(en, 'analyst_target_low', en_stale)} / mean "
                  f"{_sv(en, 'analyst_target_mean', en_stale)} / median "
                  f"{_sv(en, 'analyst_target_median', en_stale)} / high "
                  f"{_sv(en, 'analyst_target_high', en_stale)}   [Aggregator - 12-month sell-side "
                  f"targets, {_age_label(en)}]",
                  f"- 52-week range: {_sv(en, 'fifty_two_week_low', en_stale)} - "
                  f"{_sv(en, 'fifty_two_week_high', en_stale)}"]
        L.append("")

        # ---- SECTION 8.5 - PEER CONTEXT [Aggregator, context not an anchor]   [P4.10] -----------
        L.append("## SECTION 8.5 - PEER CONTEXT   [Aggregator, context not an anchor]")
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
        if en:
            if en_stale:
                L += [f"## SECTION 9 - POSITIONING   [Aggregator, {_age_label(en)}]",
                      f"- {STALE_NULL} - record older than {STALE_SUPPRESS_DAYS} days; values "
                      f"suppressed rather than shown potentially wrong.", ""]
            else:
                L += [f"## SECTION 9 - POSITIONING   [Aggregator, {_age_label(en)} - short interest is "
                      f"semi-monthly settlement data; ownership is 13F data lagged by up to a quarter]",
                      f"- Short % of float: {_v(en, 'short_pct_float')}   |   shares short: "
                      f"{_n(en.get('shares_short'))}   |   days to cover: "
                      f"{_v(en, 'short_ratio_days_to_cover')}   |   month-on-month change: "
                      f"{_v(en, 'short_mom_change_pct')}",
                      f"- Institutional ownership: {_v(en, 'institutional_pct')}%   |   insider: "
                      f"{_v(en, 'insider_pct')}%", ""]

        # ---- SECTION 10 ------------------------------------------------------------------------
        tr = ob.get("earnings_transcript") or ob.get("transcript_excerpt")
        if tr:
            L += ["## SECTION 10 - EARNINGS CALL EXCERPT   [Verbatim management speech - an assertion "
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
        L += ["## SECTION 7 - FILING-DERIVED QUALITY MEASURES   [" + ASOF_NULL + "]",
              "- fundamentals_battery.json is a same-day snapshot with no stored history to "
              "restrict to this as-of date.", ""]
        L += ["## SECTION 8 - CONSENSUS & MULTIPLES   [" + ASOF_NULL + "]",
              "- the openbb cache (trailing multiples, consensus forward growth, analyst price "
              "targets) is a same-day snapshot with no stored history.", ""]
        L += ["## SECTION 8.5 - PEER CONTEXT   [" + ASOF_NULL + "]",
              "- reconstructing peer point-in-time price/EPS would need an as-of network fetch "
              "for every cluster peer; not attempted this run.", ""]
        L += ["## SECTION 9 - POSITIONING   [" + ASOF_NULL + "]",
              "- enrich/*.json (short interest, institutional/insider ownership) is a same-day "
              "snapshot with no stored history.", ""]
        L += ["## SECTION 10 - EARNINGS CALL EXCERPT   [" + ASOF_NULL + "]",
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
                  f"({brief_reason}) — omitting GUIDANCE & CONSENSUS and SECTION 11",
                  file=sys.stderr, flush=True)

    # ---- GUIDANCE & CONSENSUS   [D4/D4b] -----------------------------------------------------
    L.append("## GUIDANCE & CONSENSUS   [company's own earnings release from SEC EDGAR, then research-brief claims]")

    asof_str = asof_date.isoformat() if asof_date is not None else None
    pack_date = asof_str if asof_str is not None else datetime.now().strftime("%Y-%m-%d")
    c = cik(t)
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
            words_hdr = (f"{stale_prefix}COMPANY'S OWN WORDS — latest earnings release "
                         f"(SEC 8-K Item 2.02, filed {rel['filing_date']}, {rel['url']}). "
                         f"The company's statement, not a verified forecast:")
            L.append(words_hdr)
            # revision 10: ADI (b)'s trailing figures lagged a filed quarter
            _thru = ttm.get("through") if isinstance(ttm, dict) else None
            if _thru:
                L.append(f"- DATA FRESHNESS: SECTION 3's trailing figures run through {_thru}; this release was "
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
    L += ["- **MANDATE:** stage-1 years 1-2 start from guidance/consensus above when available; a "
          "deviation requires `guidance_deviation_reason` in the SECTION 12 contract.", ""]

    # ---- SECTION 11 - DEEP RESEARCH BRIEF   [D8] -------------------------------------------
    if rb_text is not None and brief_ok:
        L += ["## SECTION 11 - DEEP RESEARCH BRIEF   [Written by another model, not verified - "
              "every figure is a claim to check against the filings above; cite the filing when "
              "you rely on it.]",
              rb_text[:25000], ""]

    # ---- SECTION 12 ------------------------------------------------------------------------
    L += ["## SECTION 12 - WHAT WE DO NOT HOLD",
          "Declared so you can source it yourself or carry the uncertainty, instead of assuming it.",
          "",
          _segment_note(t),
          _decl("Marketable securities and short-term investments", h, yrs,
                ("st_investments", "lt_investments"),
                held_note="in SECTION 6C. Companies hold much of their liquidity here rather than "
                          "in cash, so a net-debt figure built on the `cash` column alone can "
                          "come out with the wrong SIGN.",
                gap_note="Many companies hold much of their liquidity here rather than in cash, "
                         "so the `cash` column in SECTION 6 and the vendor cash figure in "
                         "SECTION 2 can both understate liquid assets badly. The data is filed "
                         "and sits in the source we download; it is not mapped for this name."),
          _decl("Stock-based compensation per year", h, yrs, ("sbc",),
                held_note="in the SBC column of SECTION 5.",
                gap_note="Only the single vendor scalar in SECTION 2, whose period is "
                         "unreliable. Most companies file this every year."),
          _pretax_note(h, yrs),
          _decl("Debt components beyond long-term debt", h, yrs,
                ("debt_current", "short_term_borrowings_separate", "finance_lease_liability",
                 "operating_lease_liability", "borrowings_total", "debt_lt_noncurrent"),
                held_note="in SECTION 6C - but WHETHER THEY OVERLAP IS NOT KNOWN, so no total "
                          "debt is computed for you. Read the note under that table.",
                gap_note="Current portion, short-term borrowings and lease liabilities are not "
                         "mapped for this name, so the `long-term debt` column in SECTION 6 "
                         "understates total debt by an unknown amount. The vendor scalar in "
                         "SECTION 2 is the only cross-check available here."),
          "- **Which XBRL tag produced each number: NOT RECORDED.** See the continuity warning in "
          "SECTION 0.",
          "- **Analyst Q&A from earnings calls: NOT HELD.** See SECTION 10.", ""]
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
    global LAST_PACK_MACRO_DEGRADED, LAST_PACK_FLAGS
    LAST_PACK_MACRO_DEGRADED = macro_degraded
    LAST_PACK_FLAGS = ["macro_degraded"] if macro_degraded else []
    if asof_date is not None:
        LAST_PACK_FLAGS.append("point_in_time")
    return PackText("\n".join(L), macro_degraded=macro_degraded, flags=LAST_PACK_FLAGS)


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

TASK = """You are performing an institutional equity underwriting analysis. T0 is today's price in the data pack below.

YOU OWN THE COMPLETE ECONOMIC UNDERWRITING per the Institutional Underwriting Charter:
  * First-Principles Value Decomposition: Dissect the enterprise into its distinct economic engines: (1) Transactional/Deliveries, (2) Captive Installed-Base / Recurring Contractual Annuity / Subscriptions, and (3) Strategic Optionality. Do not force the enterprise into a single rigid formula.
  * Complete Value Cycle Rule: Customer advances, deferred revenue and contract liabilities can signal capacity lock-in. One-off prepayment float is not recurring cash flow. Credit a multi-year recurring annuity ONLY where the filings show the contracted backlog or installed base that secures it (cite the filing and the figure); a supplier purchase commitment is not customer revenue.
  * Dual Terminal Valuation & Capitalization Realism: DCF projection cross-checked against net capitalization rates (1 / [WACC - g]) and verified empirical peer comps. Do not clamp terminal growth or force artificial multiple ceilings on durable compounders.
  * Causal Downside Stress-Testing: The Bear case must trace operational shock transmission through the business engine bottom-up (transactional volume shock, installed-base service durability, operating de-leverage flow-through, and WACC spread expansion) rather than arbitrary top-down cash flow slashing. Enforce the Contracted Visibility Floor for backlogged/high-ARR enterprises.
  * Lead Underwriter & Portfolio Manager Role: You own the fundamental economic viewpoint, business quality moat evaluation, scenario boundaries (Base, Bull, Bear), and final capital allocation decision. You are supported by a Python Financial Modeling Desk: invoke `run_financial_model` whenever you need deterministic DCF schedules, reverse DCF expectations gap, or continuous multi-outcome Kelly sizing. You can pass all 3 scenarios together in a single call (with each scenario's base_cf, growth_rates, wacc, terminal_g) and Python will compute all intrinsic values, reverse DCF expectations gap, and Kelly sizing in one unified table. DO NOT perform manual mental math on log-wealth Kelly formulas in prose; obtain exact numbers from `run_financial_model`.
  * The desk does the arithmetic: do not compute present values, terminal values or per-share values in your reasoning. Call run_financial_model as soon as your inputs are set and reason from its output; revise with evidence, as below.
  * One model, stated once: run Bear, Base and Bull together in ONE `run_financial_model` call. If you later change any input and run again, the memorandum must include a 'Model revisions' list giving, for every changed input, the old value, the new value and the dated evidence that forced the change. Changing an input because you dislike the resulting value is forbidden. The harness records every run you make and flags unexplained swings.
  * Scratchpad Containment & Anti-Anchoring: Keep all rough-draft calculations, re-estimates, and trial reconciliations strictly inside <think>...</think>. Never adjust valuations to match market price T0. Enforce exact parity between Section 4 scenario tables and the Section 12 JSON contract.
  * Declare Your Cash-Flow Base: Declare your cash-flow base. The default is SECTION 3's OWNER EARNINGS line (base_cf_basis "owner_earnings_default"); if you use another base, say why in base_cf_reason. Start from the default; do not run a trial base through the desk. The pack prints `cash basis [Arithmetic]`
    (= OCF - capex - SBC) for every fiscal year; `ttm_fcf` means trailing-twelve-months OCF
    minus capex, which subtracts NO stock compensation. If you use a basis that is none of
    these, declare `other` rather than leaving it implied. Your declared basis is checked
    against the filed figures and any disagreement is reported.
  * All Valuation Arithmetic Through The Desk: every intrinsic value you publish MUST come from
    `run_financial_model` — the three-stage DCF (explicit stage-1 growth, a declared linear fade
    over `fade_years` to `terminal_g`, and a dual terminal value computed BOTH as Gordon growth
    and as an exit multiple, both properly discounted). `base_iv` in the JSON contract below MUST
    equal a desk `per_share_iv` (or a desk `blend` of named legs) within 1% — do not hand-compute
    or eyeball a value and then declare it. Also call the desk's reverse DCF under the NEUTRAL
    reference structure (anchor `coe_used`, 10-year linear fade to the terminal_g anchor from
    SECTION 1.5) — print its implied 10-year CAGR and the GROWTH BASE RATES percentile band it
    falls in, and argue explicitly why your own forecast differs from what the market is already
    pricing in. A mid-cycle or margin-mean-reversion (cyclical) treatment requires `cycle_evidence`
    — at least one dated, industry-specific indicator (pricing, inventory, capacity, order
    trends); a growth rate alone is not evidence.
  * Explain The Recent Move First: start from the CATALYST BRIEF, RECENT COMPANY NEWS and SECTION 8's estimate trend and revisions. For each development say whether you accept or dispute it and why, and how it enters your Bull, Base and Bear numbers; add any development you find yourself and fetch the articles you rely on. Record them in `catalysts`. If a public takeover offer for the company is pending, value the business standalone; in the memorandum state the probability you give the offer and the expected value with and without it. The verdict stays on standalone value.
  * Scenarios Anchored To Expectations: Stage-1 growth rates are growth of the CASH FLOW you value (base_cf), not of revenue: revenue growth leaves out margin change. SECTION 8's CONSENSUS-IMPLIED VALUE line prints the consensus cash-flow LEVELS for year 1 and year 2, built on the last full fiscal year, the same period consensus growth is measured from. Base years 1-2 reach those levels from whatever base you declare: the levels are the anchor, not the growth rates, so a base from another period (TTM, a cash basis) needs growth that lands on the same year-2 level; a Base year-2 cash flow more than 15% from the printed level needs guidance_deviation_reason. If no levels are printed, start from the company's guidance converted to cash-flow growth, or revenue growth plus your stated margin path, and say so in guidance_deviation_reason. When SECTION 8 prints a BASE WINDOW CHECK, the fiscal-year and TTM owner earnings disagree by more than consensus growth explains: find the item behind the gap in the filings, name in base_cf_reason the window you judge representative, and anchor to that window's reference and year-2 level; where the TTM window's value is not shown (it lands outside the street fence), a Base on that window needs guidance_deviation_reason. From year 3 growth follows revenue again: fade from next-FY consensus revenue growth toward the GROWTH BASE RATES median by year 5, and anything above its p90 needs the MANDATE's dated evidence. A Base year above next-FY revenue growth needs guidance_deviation_reason with dated evidence, given to the desk in the same call and repeated in the contract: without it the desk holds Base years 3-5 at next-FY revenue growth and prints what your path would give beside the desk value, and only the desk value can be your Base. When SECTION 8 prints Bull and Bear year-2 levels (3 or more analysts), the Bull and Bear year-2 cash flows reach them; say why in scenario_deviation_reason if not. With fewer analysts there is no consensus range: anchor Bull and Bear to the top and bottom of the company's own guidance range where the GUIDANCE section gives one, otherwise state your own range and why. SECTION 8's CONSENSUS-IMPLIED VALUE is what the consensus path is worth at our discount rate; a Base IV more than a quarter away from it needs guidance_deviation_reason. Bull rests on the strongest bull catalyst the market is reacting to, Bear on the strongest bear catalyst. Bear <= Base <= Bull, all three from the desk, never by hand. A Bull IV below today's price claims the market is pricing an outcome better than your best case: name the assumption of the market-implied path you reject, with dated evidence, in `bull_below_price_reason`; a Bear IV above today's price needs `bear_above_price_reason`. Analyst price targets are context, not an anchor; if your Bull IV is below the LOWEST analyst target, `bull_below_price_reason` must also say what every analyst is missing.
  * Share Count And Net Debt: Use SECTION 2's share count in every scenario. A contingent instrument (warrants or earn-outs that vest on milestones) may be added only in the scenarios where it vests (pass shares_diluted per scenario), with shares_basis "diluted_plus_contingent" and shares_reason naming the instrument and its vesting condition; never in a scenario whose premise is that it does not vest. In the firm frame use SECTION 6's NET DEBT as net_debt unless net_debt_reason says why.
  * Valuation Frame: Use the equity frame (valuation_frame "equity", rate_type "cost_of_equity", no net_debt). Every flow this pack prints (OWNER EARNINGS, CASH BASIS, the cash basis column, FCF) is after interest, an equity flow, and SECTION 1.5 anchors a cost of equity, not a WACC. The firm frame is the exception and needs all three of: a pre-interest flow (add back after-tax interest expense from SECTION 5 and give the amount in interest_addback, in $B); a WACC built from the COE ANCHOR, a cost of debt from filed interest over debt, a tax rate and weights from SECTION 6, stated in wacc_reason; and SECTION 6's NET DEBT. An after-interest flow in the firm frame counts the debt twice.
  * Terminal Growth And Multiple: terminal_g defaults to SECTION 1.5's TERMINAL-GROWTH DEFAULT (the long-run growth anchor unless a lower default is printed); a terminal_g more than 0.5 points from it needs terminal_reason with dated evidence. The exit multiple defaults to SECTION 1.5's DEFAULT EXIT MULTIPLE (at a scenario's other rate, the desk's implied_terminal_ev_fcf_gordon for that scenario): the flow has already faded to terminal_g, so any other multiple asserts another terminal growth. The desk returns it as exit_implied_terminal_g; if it is more than 0.5 points from the terminal_g default, give terminal_reason with dated peer EV/FCF evidence. A P/E ratio is not an EV/FCF multiple, and this pack holds no EV/FCF peer data.
  * Cash-Flow Life: before valuing, decide whether the business's cash flows are perpetual or end, and state it in cash_flow_life ("perpetual" or the number of years) with cash_flow_life_reason. Cash flows end when they come from extracting a finite stock (a mine, a well, a reservoir) or from a right that expires (a licence, concession or patent), unless the filings show the stock or right is replaced out of the capex your base already deducts. The life is filed reserves divided by current annual production, or the remaining term, with the filing's date. Pass a finite life to the desk as finite_life_years in the Base, Bull and Bear scenarios. A perpetual value must deduct the capex that replaces what the business depletes; otherwise it counts reserves it would have to buy. Where revenue moves with a quoted commodity price, state in cash_flow_life_reason the price your cash flows assume and its source (the futures strip, the street's long-term deck, or your own with evidence); a spot price held for the whole life needs that evidence. A finite-life value sits below SECTION 8's reference, so also give guidance_deviation_reason.
  * Apply data discipline: state every driver's source ([Actual], [Estimate], [Assumption], [Unconfirmed]).

Produce the full report, SECTION 0 through SECTION 12, following the mandatory institutional memorandum structure. End with SECTION 12 Final Execution Opinion and the validated JSON contract. Reason fields take null when no reason is needed; never fill them with text such as "no deviation":

```json:underwriting
{
  "base_iv": <float per-share intrinsic value for Base Case — MUST equal a desk per_share_iv/blend within 1%>,
  "bull_iv": <float per-share intrinsic value for Bull Case>,
  "bear_iv": <float per-share intrinsic value for Bear Case>,
  "base_probability": <float between 0.0 and 1.0>,
  "bull_probability": <float between 0.0 and 1.0>,
  "bear_probability": <float between 0.0 and 1.0>,
  "catalysts": [{"date": "<YYYY-MM-DD>", "event": "<what happened>", "direction": "<bull | bear>", "estimates_moved": "<how consensus estimates moved with it, or 'no visible change'>", "scenario": "<which scenario it supports and how it moves the numbers>"}],
  "bull_below_price_reason": "<string or null — required when bull_iv < today's price>",
  "bear_above_price_reason": "<string or null — required when bear_iv > today's price>",
  "shares_basis": "<diluted | diluted_plus_contingent — SECTION 2's count, or plus a contingent instrument in the scenarios where it vests>",
  "shares_reason": "<string or null — required when any scenario's share count differs from SECTION 2's: the instrument and its vesting condition>",
  "net_debt_reason": "<string or null — required when the firm frame's net_debt differs from SECTION 6's NET DEBT>",
  "scenario_deviation_reason": "<string or null — required when the Bull or Bear year-2 cash flow is more than 15% from SECTION 8's Bull or Bear year-2 level>",
  "terminal_reason": "<string or null — required when terminal_g, or an exit multiple's implied terminal growth, is more than 0.5 points from the terminal_g default: the dated evidence>",
  "cash_flow_life": <"perpetual" or an integer number of years (1-60) — required for every name>,
  "cash_flow_life_reason": "<string — required for every name: one dated sentence; for a finite life, the filed reserves and production rate or the remaining term; where revenue moves with a commodity price, the price deck and its source>",
  "interest_addback": <float or null — firm frame only: the after-tax interest expense in $B added to the after-interest flow>,
  "wacc_reason": "<string or null — firm frame only: the COE ANCHOR, the cost of debt (filed interest / debt), the tax rate and the weights behind your WACC>",
  "base_cf_used": <float, in $B, the base cash flow you actually used for the Base Case>,
  "base_cf_basis": "<owner_earnings_default | latest_fy | multi_year_avg | ttm_fcf | other — which base that figure is>",
  "base_cf_reason": "<string or null — required when base_cf_basis is not owner_earnings_default: why that base is more representative; and when SECTION 8 prints a BASE WINDOW CHECK: the window you judge representative (fiscal year or TTM) and the item behind the gap>",
  "conviction_score": <float between 4.0 and 15.0 reflecting analytical certainty>,
  "business_quality_moat": <float between 1.0 and 5.0 reflecting moat durability>,
  "kelly_fraction_pct": <float between 0.0 and 25.0 recommended quarter-Kelly position size, obtained from run_financial_model or set to 0.0 if expected edge <= 0>,
  "asymmetric_payoff_skew": <float (Bull_IV - Price) / (Price - Bear_IV)>,
  "reentry_tranches": {
    "tranche_1_starter": <float price for Starter allocation reflecting margin of safety>,
    "tranche_2_core": <float price for Core allocation anchored to Bear IV or deep pullback>
  },
  "thesis_invalidation_trigger": "<Exact operational or financial threshold that invalidates this thesis>",
  "coe_used": <float, decimal cost of equity/capital you actually used in run_financial_model, e.g. 0.0936>,
  "coe_source": "<anchor | anchor_adjusted | own — anchor/anchor_adjusted when coe_used is within +-150bp of SECTION 1.5's COE ANCHOR, own otherwise>",
  "coe_adjustment_reason": "<string, required when coe_source is not \"anchor\" — why coe_used departs from the anchor>",
  "valuation_frame": "<equity | firm — equity (the default) discounts the pack's after-interest flows at the cost of equity with net_debt refused; firm discounts a pre-interest flow (interest_addback) at a WACC built from the COE ANCHOR (wacc_reason) and requires SECTION 6's NET DEBT + shares_diluted>",
  "terminal_method": "<gordon | exit_multiple | dual_reconciled>",
  "terminal_multiple_or_g": <float — the terminal growth rate (decimal) or exit multiple actually used>,
  "fade_years": <integer >= 0 — length of the Stage-2 linear fade to terminal_g, as passed to run_financial_model>,
  "stage1_growth_path": [<5 annual growth rates of base_cf - cash flow, not revenue; years 1-2 normally consensus EPS growth>],
  "guidance_deviation_reason": "<string or null — required when the Base year-2 cash flow is more than 15% from SECTION 8's year-2 level, the Base IV is more than a quarter away from SECTION 8's CONSENSUS-IMPLIED VALUE, or a Base year 3-5 growth is above next-FY consensus revenue growth (the reason you gave the desk)>",
  "cycle_evidence": "<string or null — required when you apply a cyclical / mid-cycle / margin-mean-reversion treatment; a growth rate alone is not evidence>",
  "verdict_label": "<undervalued | hold | overvalued — undervalued means Base IV at least 1.10x today's price, overvalued at most 0.90x, otherwise hold; your own stated verdict, checked against the recorded direction>",
  "momentum_view": "<confirming | neutral | contradicting — does SECTION 2.5's price action confirm, sit neutral to, or contradict your valuation call?>",
  "entry_timing": "<buy_now | wait_for_momentum | avoid>",
  "position_basis": "<value | momentum | none — mandate 7: value only when undervalued; momentum when your honest direction is hold or overvalued but the business is in a strong, fundamentally backed uptrend (entry_timing buy_now) - e.g. estimates rising or guidance raised; momentum_view then usually reads 'contradicting', which is expected; otherwise none>",
  "momentum_evidence": "<string or null — required when position_basis is momentum: the dated facts from the GUIDANCE block or the filings that back the trend (guidance raised, backlog or orders growth, estimates rising)>",
  "momentum_flip_condition": {"metric": "<one of the SCR-10 price-fact fields printed in SECTION 2.5>", "comparator": "< | <= | > | >=", "threshold": <float>, "window_days": <integer>},
  "momentum_break_rule": {"metric": "<one of the SCR-10 price-fact fields printed in SECTION 2.5>", "comparator": "< | <= | > | >=", "threshold": <float>, "window_days": <integer>},
  "invalidation_rules": [
    {"metric": "<name from the metric vocabulary below>", "comparator": "< | <= | > | >=", "threshold": <float>, "window": "<string, e.g. 'next reported quarter'>", "source": "<where this is checked, e.g. 'fundamentals_quarterly.json'; use \"unverifiable\" if the metric is outside both vocabularies>"}
  ]
}
```

METRIC VOCABULARY for `invalidation_rules` (at least one FINANCIAL and at least one PRICE/MOMENTUM rule are required; anything outside both lists must be declared `source: "unverifiable"`):
  - MOMENTUM metrics (the SCR-10 field names, exactly as printed in SECTION 2.5): """ + ", ".join(MOMENTUM_METRICS) + """.
  - FINANCIAL metrics: """ + ", ".join(FINANCIAL_METRICS) + """.

Think carefully through the complete economic machinery before writing. Numbers before narrative."""


# Appended ONLY when the analyst is given search tools (consensus_valuation --tools).
RESEARCH_ADDENDUM = """

RESEARCH RULES — you have web search available, so DO NOT ASSUME WHAT YOU CAN LOOK UP.

1. When your reasoning needs a fact you do not have, SEARCH FOR IT. Do not substitute an
   assumption, a trend extrapolation, or a "reasonable" placeholder. This applies to
   forward-looking drivers not covered in the pack, post-brief material corporate developments,
   or specific parameter stress-tests.
2. Search DURING your reasoning, not after you have decided. A number found to justify a
   conclusion you already reached is not evidence.
3. DO NOT search to re-verify figures already established in your pack:
   - Financial statements in SECTIONS 3–6 (Revenue, net income, operating cash flow, filed debt) are authoritative from SEC filings.
   - Operational unit drivers, forward management guidance, and segment metrics cited in SECTION 11 are claims made by another model, not verified — cite the filing when you rely on one, and check it against the filings above when you can.
   - Search ONLY for what both filings AND research cannot tell you: unconfirmed gaps, missing corporate events, or specific model parameters that remain unresolved.
4. Cite what you retrieve. Every retrieved figure gets its source named inline, and stays
   [Actual] only if it came from the company or a regulator; a secondary report is [Estimate].
5. If you search and still cannot establish a number, that is a legitimate finding: mark it
   [Unconfirmed], state what you could not resolve, and carry the uncertainty into your
   scenarios rather than burying it in a point estimate.
6. THE WRITTEN MEMORANDUM IS THE DELIVERABLE, NOT THE TOOL CALLS. Tool output is raw input to
   your analysis. After you have completed all tool calls and received their results, you MUST
   immediately write the complete institutional underwriting memorandum in the full SECTION 0
   through SECTION 12 format, ending with the ```json:underwriting contract. Stopping after a
   tool call delivers nothing: a run that ends on tool output is discarded unread, however long
   it ran. Never emit tool-call syntax as prose, and never treat a tool result as your answer."""


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
    content = f"{pack}\n\n---\n\n{TASK}"
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
