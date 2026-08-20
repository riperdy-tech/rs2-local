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
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

import rs2_data  # noqa: E402

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


def build_pack(t):
    """Every fact we hold that is FILED, or is exact arithmetic on filed values, labelled with its
    source and its period. No judgment is exercised here: no valuation, no basis choice, no
    normalisation, no composite of our own. Where a series is known to be defective the pack says
    so inline, rather than dropping it or presenting it clean.

    DELIBERATELY EXCLUDED, each for a measured reason (and each declared in SECTION 12):
      * pretax_income / tax_provision / any effective tax rate — FIELD_SPECS['pretax_income']
        includes ...BeforeIncomeTaxesDomestic, so 38 live names carry a domestic-only figure. The
        identity net_income + tax == pretax fails by >5% on 318 of 1,835 rows. A false [Actual]
        tax rate is worse than none: an invented one at least gets labelled [Assumption].
      * battery m_score — imputes absent Beneish ratios at 1.0 and a missing TATA term at 0.0,
        then publishes a score, presenting a guess as a measurement.
      * valuation_models.json / factor_scores.json — our own finished valuation and our own
        ranking. Handing either over makes the analysis circular.
    """
    L = [f"# DATA PACK - {t}", ""]

    fin = rs2_data.load_json(SD / "financials" / f"{t}.json") or {}
    cm = fin.get("Calculated_Metrics") or {}
    ttm = (rs2_data.load_json(SD / "fundamentals_ttm.json") or {}).get("tickers", {}).get(t) or {}
    f = ttm.get("fields") or {}
    qrec = (rs2_data.load_json(SD / "fundamentals_quarterly.json") or {}).get("tickers", {}).get(t) or {}
    qs = qrec.get("quarters") or []
    h = (rs2_data.load_json(SD / "fundamentals_history.json") or {}).get("tickers", {}).get(t) or {}
    bat = (rs2_data.load_json(SD / "fundamentals_battery.json") or {}).get("tickers", {}).get(t) or {}
    ob = rs2_data.load_json(HERE / "cache" / f"openbb_{t}.json") or {}
    en = rs2_data.load_json(HERE / "enrich" / f"{t}.json") or {}
    met = ob.get("metrics") or {}
    fy_end, fy_src = _fy_end(ttm, qs)
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

    # ---- SECTION 1 -------------------------------------------------------------------------
    sector, industry = rs2_data.sector_lookup(t)
    L += ["## SECTION 1 - IDENTITY",
          f"- Ticker: {t} | Sector: {sector} | Industry: {industry}",
          f"- Fiscal year ends: {fy_end}   [derived from {fy_src}]",
          "- Rows below are labelled by FISCAL year, not calendar year.", ""]

    # ---- SECTION 2 -------------------------------------------------------------------------
    px, sh = fin.get("Price"), fin.get("Shares_Outstanding")
    L += [f"## SECTION 2 - MARKET   [Aggregator - vendor quote as of {_v(fin, 'Data_Fetched_Date')}]",
          f"- Price: ${px}" if px is not None else f"- Price: {NULL}",
          f"- Shares outstanding: {_n(sh)}"
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
          f"period is NOT reliably trailing-twelve-months; on most names it is a fiscal year. We "
          f"hold no per-year SBC series at all - see SECTION 12]", ""]

    # ---- SECTION 3 -------------------------------------------------------------------------
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
    else:
        L.append(f"{NULL} - no TTM record. 20-F and 40-F filers file no 10-Q, so no TTM is "
                 f"derivable for them from this source.")
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
                    "capex", "FCF", "D&A", "SG&A", "interest expense"]),
              _row(["---"] * 11)]
        for y in yrs:
            r = h[str(y)]
            L.append(_row([str(y), _b(r.get("revenue")), _b(r.get("gross_profit")),
                           _b(r.get("operating_income")), _b(r.get("net_income")),
                           _b(r.get("ocf")), _b(r.get("capex")), _b(r.get("fcf")), _b(r.get("da")),
                           _b(r.get("sga")), _b(r.get("interest_expense"))]))
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

    # ---- SECTION 6 -------------------------------------------------------------------------
    L.append("## SECTION 6 - FISCAL-YEAR BALANCE SHEET & WORKING CAPITAL   [Filed, except the two "
             "columns marked [Arithmetic]]")
    if yrs:
        L += [_row(["FY", "total assets", "current assets", "current liabs",
                    "working capital [Arithmetic]", "change in WC [Arithmetic]", "cash",
                    "receivables", "inventory", "net PP&E", "long-term debt", "total liabs",
                    "equity", "retained earnings", "wtd-avg shares"]),
              _row(["---"] * 15)]
        prev_wc = None
        for y in yrs:
            r = h[str(y)]
            ca, cl = r.get("current_assets"), r.get("current_liabilities")
            wc = (ca - cl) if isinstance(ca, (int, float)) and isinstance(cl, (int, float)) else None
            dwc = (wc - prev_wc) if isinstance(wc, (int, float))                 and isinstance(prev_wc, (int, float)) else None
            if isinstance(wc, (int, float)):
                prev_wc = wc
            L.append(_row([str(y), _b(r.get("total_assets")), _b(ca), _b(cl), _b(wc), _b(dwc),
                           _b(r.get("cash")), _b(r.get("receivables")), _b(r.get("inventory")),
                           _b(r.get("ppe_net")), _b(r.get("lt_debt")),
                           _b(r.get("total_liabilities")), _b(r.get("equity")),
                           _b(r.get("retained_earnings")), _n(r.get("shares_diluted"))]))
        L += ["",
              "- `working capital` = current assets minus current liabilities. `change in WC` is "
              "the year-over-year difference of that. Both are exact arithmetic on the two filed "
              "columns beside them, and both are stated because a DCF that omits the change in "
              "working capital has silently assumed it is zero.",
              "- `long-term debt` is LONG-TERM ONLY. Current portion, short-term borrowings and "
              "lease liabilities are not mapped by our extractor, so this column UNDERSTATES total "
              f"debt by an amount that varies by company. 33 live names file a debt tag we do not "
              f"map at all and therefore show `{NULL}` here despite carrying debt.",
              "- `wtd-avg shares` is the weighted-average share count as filed and is **NOT SPLIT-"
              "ADJUSTED**. A single-year step of several times is a stock split, not issuance. On "
              "18 live names the underlying tag is basic, or an undifferentiated weighted average, "
              "rather than diluted - and our extract does not record which. Do not compute a "
              "dilution rate or a per-share history from this column without checking the filings.",
              "- `capex` in SECTION 5 is purchases of property, plant and equipment only. It "
              "EXCLUDES capitalised software, which for software-heavy companies is a real cash "
              "outflow - so the FCF column is overstated for those names relative to a broader "
              "definition. The vendor's capex figure uses the broader definition and differs from "
              "ours by 1.1x to 42x on 51 live names. Neither definition has been chosen for you."]
    else:
        L.append(f"{NULL} - no fiscal-year record held.")
    L.append("")

    # ---- SECTION 7 -------------------------------------------------------------------------
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
    fg = ob.get("forward_growth") or {}
    L += ["## SECTION 8 - CONSENSUS & MULTIPLES   [Aggregator]",
          # price_to_sales dropped 2026-08-20: measured non-null on 0 of 294 vendor records, so
          # the line could never print a value. Market cap and revenue are both in this pack;
          # the model can divide. A field that is structurally always absent is noise, not a
          # disclosed gap.
          f"- Trailing P/E: {_v(met, 'pe_ratio')}   |   P/B: "
          f"{_v(met, 'price_to_book')}   |   PEG: {_v(met, 'peg_ratio')}   "
          f"[trailing; the vendor does not state the period]",
          f"- Return on equity: {_v(met, 'return_on_equity')}   |   gross margin: "
          f"{_v(met, 'gross_margin')}   |   operating margin: "
          f"{_v(met, 'operating_margin')}   |   dividend yield: "
          f"{_v(met, 'dividend_yield')}   [vendor-computed, expressed as fractions not "
          f"percents]",
          f"- Consensus forward growth: revenue {_v(fg, 'revenue_cagr')}, EPS "
          f"{_v(fg, 'eps_cagr')}   (source {_v(fg, 'source')})   [Estimate - sell-side "
          f"consensus. Establish the horizon before treating either as a multi-year CAGR.]"]
    if en:
        L += [f"- Analyst price targets: low {_v(en, 'analyst_target_low')} / mean "
              f"{_v(en, 'analyst_target_mean')} / median "
              f"{_v(en, 'analyst_target_median')} / high "
              f"{_v(en, 'analyst_target_high')}   [Aggregator - 12-month sell-side targets]",
              f"- 52-week range: {_v(en, 'fifty_two_week_low')} - "
              f"{_v(en, 'fifty_two_week_high')}"]
    L.append("")

    # ---- SECTION 9 -------------------------------------------------------------------------
    if en:
        L += ["## SECTION 9 - POSITIONING   [Aggregator - short interest is semi-monthly "
              "settlement data; ownership is 13F data lagged by up to a quarter]",
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

    # ---- SECTION 11 ------------------------------------------------------------------------
    rb = HERE / "research" / f"{t}.md"
    if rb.exists():
        L += ["## SECTION 11 - WEB RESEARCH BRIEF   [Narrative written by a different language "
              "model from web sources. Not a filing, and not verified. Treat every figure in it as "
              "a claim to check - especially where it restates a number that also appears in "
              "SECTIONS 3-6, which come from filings and outrank it.]",
              rb.read_text(encoding="utf-8", errors="replace")[:14000], ""]

    # ---- SECTION 12 ------------------------------------------------------------------------
    L += ["## SECTION 12 - WHAT WE DO NOT HOLD",
          "Declared so you can source it yourself or carry the uncertainty, instead of assuming it.",
          "",
          "- **Segment revenue and margin by business line: WE HAVE NONE, for any company.** "
          "Measured across the live book: of 3,380,466 fact rows in the SEC companyfacts source, "
          "ZERO carry a dimension. Segment detail exists in XBRL only as dimensional axes, and the "
          "companyfacts API strips them. No sum-of-the-parts is possible from this pack.",
          "- **Marketable securities and short-term investments: NOT EXTRACTED.** This is the "
          "largest known hole. Many companies hold much of their liquidity here rather than in "
          "cash, so the `cash` column in SECTION 6 and the vendor cash figure in SECTION 2 can "
          "both understate liquid assets badly - and a net-debt figure built from them can come "
          "out with the wrong SIGN. The data is filed, and sits in the source we already "
          "download; our extractor does not map it yet.",
          "- **Stock-based compensation per year: NOT EXTRACTED.** Only the single vendor scalar "
          "in SECTION 2, whose period is unreliable. Most companies file this every year.",
          "- **Effective tax rate: DELIBERATELY WITHHELD.** Our pre-tax income field is "
          "contaminated on 38 live names by a US-domestic-only tag, so a tax rate computed from it "
          "would be wrong while looking authoritative. If you need one, derive it yourself and "
          "label it your own assumption.",
          "- **Total debt: PARTIAL.** See the note under SECTION 6.",
          "- **Which XBRL tag produced each number: NOT RECORDED.** See the continuity warning in "
          "SECTION 0.",
          "- **Analyst Q&A from earnings calls: NOT HELD.** See SECTION 10.", ""]
    if drift:
        L += ["**SCHEMA DRIFT DETECTED WHILE BUILDING THIS PACK.** Fields this builder expects "
              "were absent from the upstream record, so sections above may be missing data we "
              "actually hold. Treat the affected areas as unreliable rather than empty: "
              + " | ".join(drift), ""]
    return "\n".join(L)


TASK = """You are performing a complete RS2 v2.0 equity analysis. T0 is today's price in the data
pack below.

YOU OWN THE ENTIRE ANALYSIS. Specifically, and unlike any constraint you may infer:
  * YOU select the valuation engine (Steps 0-2..0-4). Nothing has been pre-selected.
  * YOU compute intrinsic value. No backbone has computed it for you. There is no engine header
    to defer to and no pre-computed fair value, margin of safety or expectations gap.
  * YOU decide what cash-flow definition is appropriate and YOU build the forecast path — do not
    reduce the company to a single trailing number unless you can defend that as the right method.
  * Apply the framework's data-discipline rules to the pack itself. The data is what our systems
    hold; judge its reliability as you would any source.

Produce the full report, SECTION 0 through SECTION 12, per the framework's FINAL OUTPUT
STRUCTURE. Show your explicit forecast (per-year revenue, margin, capex, D&A or their
equivalents) and your discount-rate derivation. End with SECTION 12 Final Execution Opinion.

SOURCE EVERY FORECAST DRIVER. For each of revenue growth, margin, capital expenditure and
discount rate, state where the number came from: a figure in the data pack, a figure you
retrieved, or your own assumption. Any driver you cannot source is an [Assumption] and must be
labelled one.

Pay particular attention to periods BEYOND the data you were given. A guidance figure that
covers only the current year tells you nothing about later years, and quietly extending a
trend across a decade is the single easiest way to decide a valuation by accident. If the path
of a driver after the guided period is not established, say so, and show what the valuation
does across the plausible range instead of picking one silently.

Think carefully before writing. Numbers before narrative."""

# Appended ONLY when the analyst is given search tools (consensus_valuation --tools).
RESEARCH_ADDENDUM = """

RESEARCH RULES — you have web search available, so DO NOT ASSUME WHAT YOU CAN LOOK UP.

1. When your reasoning needs a fact you do not have, SEARCH FOR IT. Do not substitute an
   assumption, a trend extrapolation, or a "reasonable" placeholder. This applies especially to
   forward-looking drivers: guidance for years beyond the data pack, capital-expenditure plans,
   management commentary on future spending, competitor capacity, regulatory outcomes, and
   current macro (rates, policy).
2. Search DURING your reasoning, not after you have decided. A number found to justify a
   conclusion you already reached is not evidence.
3. NEVER search to re-source financial-statement figures already in your pack. Revenue, net
   income, operating cash flow, capital expenditure, free cash flow and share counts come from
   SEC filings and are authoritative — a web page restating them is less reliable, not more.
   Search for what the filings CANNOT tell you: the future, and the outside world.
4. Cite what you retrieve. Every retrieved figure gets its source named inline, and stays
   [Actual] only if it came from the company or a regulator; a secondary report is [Estimate].
5. If you search and still cannot establish a number, that is a legitimate finding: mark it
   [Unconfirmed], state what you could not resolve, and carry the uncertainty into your
   scenarios rather than burying it in a point estimate."""


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    t = (args[0] if args else "GOOG").upper()
    model = _arg("--model", CONFIG["model"])
    ctx = int(_arg("--ctx", CTX))
    # Ollama accepts true/false/low/medium/high/max. MEASURED 2026-08-20: `true` yields the
    # same trace length as `low` (1,837 vs 1,770 chars) while medium/high/max give ~50% more
    # (2,540/2,713/2,652) — so `think: true` is NOT the model's default xhigh. Qwen3.8's own
    # chat template defaults to xhigh, which Ollama does not expose; "max" is its request for
    # the model's highest level. Depth tier should use "max".
    think = _arg("--think", "max")
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
