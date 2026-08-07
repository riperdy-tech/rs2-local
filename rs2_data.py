#!/usr/bin/env python3
"""
rs2_data.py — Screener data injector for the local RS2 pipeline.

Python port of the screener's `lib/prompt-builder.ts`. Reads the verified,
daily-fetched data the screener already produces and formats it into the
data-discipline + priming + financial-brief blocks that get appended to every
RS2 stage prompt. RS2.txt itself is baked into the `rs2-analyst` Ollama model,
so this module produces only the per-ticker DATA payload.

Buckets assembled here (Bucket A of the plan):
  financials/{T}.json   -> financial brief (market snapshot, TTM metrics, IS)
  reverse_scores.json   -> reverse-engine triage priming
  valuation_models.json -> reverse-DCF expectations priming
  overlay_signals.json  -> GPR + informed-demand priming
  macro_state.json      -> REAL macro block (primary regime evidence)
  MRI current_regime.json -> regime probabilities (only if fresh; else skipped)

Bucket B (enrich/{T}.json) and Bucket C (research/{T}.md) are produced by
enrich_ticker.py / research_agent.py and folded in by build_data_context().

Every missing file/field degrades to "not provided" — never crashes, never
substitutes a guessed value (RS2 data discipline).

CLI:  python rs2_data.py NVDA      # prints the assembled data context
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

ARCHETYPE_NAMES = {
    "A": "Stable Incumbent",
    "B": "Quality Compounder",
    "C": "Cyclical",
    "D": "Product-Platform Hybrid",
    "E": "Option-Led / High-Beta",
    "F": "Pure Regulatory / Binary",
}

# 5 MRI regimes -> RS2's 4 (tightening folds into Stagflation-adjacent; kept labelled).
MRI_REGIME_LABELS = {
    "goldilocks": "Goldilocks",
    "reflation": "Reflation",
    "stagflation": "Stagflation",
    "recession": "Recession",
    "tightening": "Tightening (high-rate)",
}


# ── safe IO ───────────────────────────────────────────────────────────────
def load_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:   # utf-8-sig: a BOM'd data file is data, not None
            return json.load(f)
    except Exception:
        return None


_SECTOR_CACHE = None

def sector_lookup(ticker):
    """Sector/Industry from the screener stocks.csv (cached). Used to ground Layer-0
    archetype classification (the reverse-triage archetype is unreliable for cyclicals)."""
    global _SECTOR_CACHE
    t = ticker.upper()
    if _SECTOR_CACHE is None:
        _SECTOR_CACHE = {}
        try:
            import csv
            path = Path(CONFIG["screener_data_dir"]) / "stocks.csv"
            with open(path, "r", encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                sc = next((c for c in r.fieldnames if c.lower() == "sector"), None)
                ic = next((c for c in r.fieldnames if c.lower() == "industry"), None)
                syc = next((c for c in r.fieldnames if c.lower() == "symbol"), None)
                for row in r:
                    sym = (row.get(syc) or "").upper()
                    if sym:
                        _SECTOR_CACHE[sym] = (row.get(sc), row.get(ic))
        except Exception:
            _SECTOR_CACHE = {}
    return _SECTOR_CACHE.get(t, (None, None))


# Sectors where the reverse-triage archetype tends to mislabel cyclicals as quality/platform.
CYCLICAL_SECTORS = ("energy", "materials", "industrials", "utilities")


def _entry_discipline(rmos):
    """ENTRY DISCIPLINE line for a given realistic MoS, keyed on the CROSS-SECTION.

    The old rule was absolute (MoS < 15%) and fired on 80% of the book -- so the prompt instructed
    "even a superb franchise here is a HOLD / stage-in" for four names in five, and the model
    complied: 76% of verdicts landed at conviction 7-9, 67% shared one action phrase. That is not
    a valuation finding, it is a constant.

    It fired that often because the cut was absolute while the DISTRIBUTION's level is set by the
    sector WACC, which is a judgement (a 2pt lower WACC moves median MoS from -38.9% to -13.5%).
    A percentile cut is invariant to that: "expensive" now means expensive RELATIVE TO THE BOOK,
    which is the only sense in which a ranking engine can mean it.

    Returns None when the calibration is missing or stale -- the honest answer is then to state the
    number and let the analyst judge, NOT to silently fall back to the absolute cut.
    """
    import valuation_backbone as vb
    if rmos is None:
        return None
    cut = vb.mos_cut()
    if cut is None:
        return ("- ENTRY DISCIPLINE: cross-sectional MoS calibration is stale or missing, so no "
                "cheap/expensive ranking is available. Judge the margin of safety on its own terms "
                "and say so explicitly.")
    if rmos < cut:
        return (f"- ENTRY DISCIPLINE: this MoS ({rmos:+.0f}%) is in the EXPENSIVE THIRD of the "
                f"analysed book (cut {cut:+.0f}%). Poor entry edge relative to the alternatives — a "
                f"DO-NOT-CHASE. Even a superb franchise here is a HOLD / stage-in on weakness, not a "
                f"fresh full BUY; conviction's valuation component must reflect that.")
    return (f"- ENTRY EDGE: this MoS ({rmos:+.0f}%) is BETTER than the expensive third of the book "
            f"(cut {cut:+.0f}%). Judge the entry on the business evidence; do NOT reflexively "
            f"discount conviction for valuation alone.")


def valuation_block(ticker):
    """PRIMARY valuation context (inverted architecture) — the deterministic reverse-DCF
    BACKBONE (expectations investing). Replaces the old forward-DCF priming + analyst-consensus
    anchor. The model does NOT set base_cf / growth / WACC and does NOT compute IV; it judges
    whether the price-IMPLIED growth is ACHIEVABLE. See AUDIT.md C2."""
    import valuation_backbone as vb  # lazy: vb imports rs2_data (avoid circular import)
    b = vb.backbone(ticker)
    L = ["## VALUATION — REVERSE-DCF EXPECTATIONS MODEL (deterministic backbone; do NOT recompute)", ""]
    if not b.get("ok"):
        sl = (sector_lookup(ticker)[0] or "").lower()
        ni = _trailing_net_income(ticker)
        if any(k in sl for k in ("financial", "bank", "insurance")):
            # Banks/insurers: cash-flow DCF is structurally invalid (lending/deposit flows
            # dominate; owner-earnings = NI+D&A-capex is meaningless). Value on equity returns.
            L.append(f"- No cash-flow DCF ({b.get('reason')}): this is a FINANCIAL — a DCF on owner "
                     "earnings does not apply. Value it on NORMALIZED EARNINGS × a justified P/E, or "
                     "P/B vs ROE (is ROE above cost of equity?). Engine 2 (multiple) framing, not a DCF, "
                     "not an option bridge.")
        elif b.get("reason") == "reinvestment_negative_fcf":
            # PROFITABLE but capex > D&A: a reinvestment profile, NOT pre-profit. Must never be
            # described as "negative earnings / option-led" — that framing sent capex-heavy names
            # to the Engine-4 option bridge (see valuation_backbone.REGULATED_UTILITY_INDUSTRIES).
            L.append(f"- No DCF model ({b.get('reason')}): the company IS profitable, but capex "
                     "exceeds D&A, so owner earnings (NI+D&A−capex) are negative. This is a "
                     "REINVESTMENT profile (rate-base / capacity build), NOT a pre-profit or "
                     "option-led company. Do NOT value it as an option bridge. Value it on "
                     "NORMALIZED mid-cycle earning power × a justified multiple, or on book "
                     "equity vs ROE, and flag the lower confidence.")
        elif b.get("rnpv_scaffold"):
            # Pre-profit clinical biotech -> Engine 5 / rNPV. Show the deterministic scaffolding so
            # the model supplies ONLY the phase and the value-if-approved (see ENGINE5_SCHEMA).
            sc = b["rnpv_scaffold"]
            L.append(f"- No DCF model ({b.get('reason')}): PRE-PROFIT CLINICAL-STAGE BIOTECH — value "
                     "on **ENGINE 5 / rNPV**, not a DCF and not a free-form option bridge.")
            L.append(f"- rNPV SCAFFOLD (deterministic, FY{sc['fiscal_year']}): net cash "
                     f"${sc['net_cash_ps']}/sh"
                     + (" [SUSPECT — share count looks stale, floor will be ignored]"
                        if sc["net_cash_ps_suspect"] else "")
                     + f"; cash burn ${sc['burn_per_yr']/1e6:.0f}M/yr; runway "
                     + (f"{sc['runway_years']} years." if sc['runway_years'] is not None
                        else "n/a (not burning cash)."))
            L.append("- YOU supply only: the LEAD asset's development phase, and the per-share value "
                     "IF it is approved. The probability of approval (published phase base rates), "
                     "the net-cash floor and the dilution needed to reach approval are computed for "
                     "you — do NOT estimate a probability yourself.")
        elif ni is not None and ni <= 0:
            L.append(f"- No DCF model ({b.get('reason')}): negative earnings — PRE-PROFIT / OPTION-LED "
                     "(Archetype E, Engine 4). Value = proven-core value/share + Σ(success_prob × "
                     "value-if-it-works) − execution drag, per share, base-rate disciplined. No earning "
                     "power to capitalize — do NOT force a DCF.")
        else:
            L.append(f"- No DCF model ({b.get('reason')}): base cash flow is negative/missing this year "
                     "(e.g. a capex super-cycle or one-off). Do NOT force a DCF — value on normalized "
                     "mid-cycle earning power × a justified multiple, and flag the low confidence.")
        L.append("")
        return "\n".join(L)
    if b.get("method") == "financial_pb_roe":
        # FINANCIAL (or RATE-REGULATED UTILITY): ROE vs P/B expectations model; no cash-flow DCF.
        _util = b.get("pb_kind") == "regulated_utility"
        L[0] = ("## VALUATION — REGULATED-UTILITY ROE / RATE-BASE (P-B) EXPECTATIONS MODEL "
                "(deterministic; do NOT recompute)" if _util else
                "## VALUATION — FINANCIAL ROE / P-B EXPECTATIONS MODEL (deterministic; do NOT recompute)")
        if _util:
            L.append("- RATE-REGULATED utility: the regulator sets an allowed ROE on a RATE BASE that is "
                     "essentially book equity, so value is book × the capitalised spread of earned ROE "
                     "over cost of equity — NOT an owner-earnings DCF (capex exceeds D&A permanently "
                     "while the rate base grows, which is normal here, not distress).")
        L.append(f"- Delivered ROE [Actual]: {b['roe']*100:.1f}% (FY{b['fiscal_year']}); cost of equity "
                 f"{b['coe']*100:.0f}%, sustainable growth {b['sustainable_g']*100:.1f}%.")
        L.append(f"- Current price = P/B {b['current_pb']}x (book ${b['book_value_ps']}/sh). To pay that, the "
                 f"market must believe an ROE of ~{b['implied_roe']*100:.1f}% (vs {b['roe']*100:.1f}% delivered).")
        if b.get("fair_value") is not None:
            L.append(f"- Justified P/B at the delivered ROE ≈ {b['justified_pb']}x → fenced fair value "
                     f"~${b['fair_value']}/sh ({b.get('fair_value_method')}).")
        else:
            L.append(f"- Justified P/B at the delivered ROE ≈ {b['justified_pb']}x (no $ fair value — "
                     "no consensus band to fence it).")
        L.append(f"- ROE EXPECTATIONS GAP: {b['expectations_gap_pts']:+.0f} pts (implied minus delivered ROE). {b['verdict']}")
        med = b.get("consensus_median")
        if med is not None:
            price, rmos = b.get("price"), b.get("realistic_mos_pct")
            pos = "AT/ABOVE" if (price and price >= med) else "below"
            line = (f"- ANALYST CONSENSUS fair value [Estimate]: ~${med} (band ${b.get('consensus_low')}-"
                    f"${b.get('consensus_high')}); today's price is {pos} it.")
            if rmos is not None:
                line += f" Fenced fair value => realistic margin of safety {rmos:+.0f}%."
            if b.get("consensus_stale"):
                line += " [targets may be stale — lower confidence]"
            L.append(line)
            _ed = _entry_discipline(rmos)
            if _ed:
                L.append(_ed)
        L.append("- YOUR JOB (Layer 3): judge whether that implied ROE is SUSTAINABLE given the moat, balance-sheet "
                 "risk (credit/rate cycle), capital return and the research brief — NOT to recompute. A big positive "
                 "ROE gap the franchise can't sustain => overvalued; a negative gap with a durable franchise => "
                 "undervalued. State stance + how achievable (low/med/high).")
        L.append("")
        return "\n".join(L)
    dg, fg = b["hist_revenue_cagr_5y"], b["hist_fcf_cagr_5y"]
    L.append(f"- Base cash flow [Actual]: ${b['base_cf']/1e9:.2f}B "
             f"({str(b['base_cf_kind']).replace('_',' ')}, FY{b['fiscal_year']}); "
             f"sector discount rate (WACC) {b['wacc_pct']}%.")
    L.append(f"- The CURRENT price IMPLIES ~{b['implied_growth']*100:.1f}%/yr cash-flow growth for 5yr "
             f"(then fading to {b['terminal_growth']*100:.1f}%). This is what you must BELIEVE to pay today's price.")
    _reit = b.get("base_cf_kind") == "ffo_reit"
    if _reit:
        L.append("- REIT: base cash flow is FFO (net income + D&A), because real-estate depreciation "
                 "is an accounting fiction for an appreciating asset. CAVEAT — FFO does NOT deduct "
                 "recurring maintenance capex (AFFO would; the split is not in the filings we hold), "
                 "so the implied growth above is if anything UNDERSTATED. Treat a marginal negative "
                 "gap on a REIT as fair, not cheap.")
    dem = []
    if _reit and b.get("demonstrated_cagr") is not None:
        dem.append(f"FFO/share {b['demonstrated_cagr']*100:+.1f}%/yr")
    if dg is not None: dem.append(f"revenue {dg*100:+.1f}%/yr")
    if fg is not None: dem.append(f"FCF {fg*100:+.1f}%/yr")
    if dem:
        L.append(f"- DEMONSTRATED 5yr growth [Actual]: {', '.join(dem)}."
                 + (" Revenue growth for a REIT is largely equity-funded acquisition roll-up — the "
                    "PER-SHARE FFO figure is what an existing holder actually received, and is what "
                    "the gap is measured against." if _reit else ""))
    if b["expectations_gap_pts"] is not None:
        L.append(f"- EXPECTATIONS GAP: {b['expectations_gap_pts']:+.0f} pts (price-implied minus "
                 f"demonstrated {'FFO/share' if _reit else 'revenue'} growth). {b['verdict']}")
    if b.get("forward_growth") is not None:
        L.append(f"- FORWARD analyst growth [Estimate]: {b['forward_growth']*100:+.1f}%/yr — the FRESH "
                 "consensus expectation (use this, not trailing, to judge achievability).")
    med = b.get("consensus_median")
    if med is not None:
        price = b.get("price")
        rmos = b.get("realistic_mos_pct")
        pos = "AT/ABOVE" if (price and price >= med) else "below"
        line = (f"- ANALYST CONSENSUS fair value [Estimate]: ~${med} (band ${b.get('consensus_low')}-"
                f"${b.get('consensus_high')}); today's price is {pos} it.")
        if rmos is not None:
            line += f" Fenced fair value ${b.get('fair_value')} => realistic margin of safety {rmos:+.0f}%."
        if b.get("consensus_stale"):
            line += " [targets may be stale — lower confidence]"
        L.append(line)
        _ed = _entry_discipline(rmos)
        if _ed:
            L.append(_ed)
    L.append("- YOUR JOB (Layer 3): judge whether that price-implied growth is ACHIEVABLE given the moat, research "
             "brief, end-market TAM, reinvestment runway AND any embedded OPTIONALITY (a scarce asset or secular "
             "tailwind — e.g. AI-power demand, a platform call-option — can justify a gap that trailing growth alone "
             "does not). Calibrate the stance: a SMALL gap (≈ ≤5 pts) on a durable franchise is FAIR, not overvalued "
             "(a modest premium for quality is normal); reserve OVERVALUED for a LARGE gap (~≥12 pts) the evidence "
             "can't support, OR a smaller gap with clear deterioration (declining guidance, eroding moat). A NEGATIVE "
             "gap with an intact moat => the market underrates demonstrated delivery (undervalued). NOT a DCF recompute. "
             "State your stance + how achievable (low/med/high).")
    L.append("")
    return "\n".join(L)


def _trailing_net_income(ticker):
    fin = load_json(Path(CONFIG["screener_data_dir"]) / "financials" / f"{ticker.upper()}.json") or {}
    ann = fin.get("Annual_Income_Statement") or []
    return ann[0].get("NetIncome") if ann else None


def classification_context(ticker):
    sector, industry = sector_lookup(ticker)
    L = ["## CLASSIFICATION CONTEXT (Layer 0)", ""]
    if sector:
        L.append(f"- GICS Sector / Industry: {sector} / {industry or '?'} [Actual].")
    else:
        L.append("- GICS Sector: not provided.")
    L.append("- Classify the archetype FROM FIRST PRINCIPLES. The reverse-engine triage "
             "archetype below is a low-confidence hint, NOT a verdict.")
    sl = (sector or "").lower()

    # Pre-profit / option-led OVERRIDES any sector default: a company with no (or
    # negative) earnings cannot be valued by Engine 1/2/3 — it is Archetype E,
    # Engine 4 (option bridge). Catches OKLO/IONQ-type pre-revenue names that sit
    # in "cyclical" sectors (Utilities/Industrials) and would otherwise mis-route.
    ni = _trailing_net_income(ticker)
    if ni is not None and ni <= 0:
        L.append(f"- NOTE: trailing net income is negative (${ni/1e9:.2f}B) — this is a "
                 "PRE-PROFIT / Option-Led company (Archetype E). Use Engine 4 (option bridge: "
                 "core_value + Σ(prob×value) − drag). Do NOT use Engine 1/2/3 — there are no "
                 "stable earnings to capitalize. Be base-rate disciplined on success probabilities.")
        L.append("")
        return "\n".join(L)

    if sl and any(c in sl for c in CYCLICAL_SECTORS):
        L.append(f"- NOTE: {sector} is a cyclical sector (Archetype C). Value it with "
                 "Engine 1 as a CYCLE-ADJUSTED DCF on NORMALIZED MID-CYCLE owner-earnings — "
                 "set base_cf to mid-cycle cash earning power (the engine bounds it to "
                 "owner-earnings), pick a moderate through-cycle growth rate, and a normal WACC. "
                 "Prefer this over Engine 2 (EPS×multiple): a single through-cycle multiple is "
                 "error-prone. Do NOT capitalize trough earnings, and do not over-weight a "
                 "'platform' narrative on a capex/cycle-driven business.")
    if "financial" in sl or "bank" in sl or "insurance" in sl:
        L.append(f"- NOTE: {sector} is a financial. The valuation METHOD is deterministic and stated "
                 "in the VALUATION block: balance-sheet financials (banks / insurance underwriters / "
                 "mortgage) are valued on equity returns (P/B vs ROE); asset-light financials (payment "
                 "networks, exchanges, asset managers) run the normal reverse-DCF. Do NOT run a "
                 "cash-flow DCF on a bank/insurer yourself — lending/underwriting flows make owner "
                 "earnings meaningless there.")
    if "real estate" in sl or "reit" in sl:
        L.append(f"- NOTE: {sector} is a REIT. Use Engine 1 on FFO/AFFO (not GAAP EPS); "
                 "dividend/yield support matters.")
    L.append("")
    return "\n".join(L)


def market_for(ticker):
    t = ticker.upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return "Korea"
    if t.endswith(".TW") or t.endswith(".TWO"):
        return "Taiwan"
    return "US"


def fmt(val, market="US", is_price=False, decimals=2):
    """Mirror prompt-builder.ts fmt(): scale to B/M, currency prefix by market."""
    if val is None:
        return "N/A"
    try:
        n = float(val)
    except (TypeError, ValueError):
        return str(val)
    prefix = {"US": "$", "Korea": "₩", "Taiwan": "NT$"}.get(market, "")
    if market == "None":
        prefix = ""
    if is_price:
        return f"{prefix}{n:,.{decimals}f}"
    if market == "None":
        return f"{n:.{decimals}f}"
    if market == "Korea":
        if abs(n) >= 1e12: return f"{n/1e12:.{decimals}f}조원"
        if abs(n) >= 1e8:  return f"{n/1e8:.{decimals}f}억원"
        if abs(n) >= 1e4:  return f"{n/1e4:.{decimals}f}만원"
        return f"{prefix}{n:,.{decimals}f}"
    if market == "Taiwan":
        if abs(n) >= 1e12: return f"{n/1e12:.{decimals}f}兆元"
        if abs(n) >= 1e8:  return f"{n/1e8:.{decimals}f}億元"
        if abs(n) >= 1e4:  return f"{n/1e4:.{decimals}f}萬元"
        return f"{prefix}{n:,.{decimals}f}"
    # US / default
    if abs(n) >= 1e9: return f"{prefix}{n/1e9:.{decimals}f}B"
    if abs(n) >= 1e6: return f"{prefix}{n/1e6:.{decimals}f}M"
    return f"{prefix}{n:.{decimals}f}"


def _suf(val, market, suffix, decimals=2):
    s = fmt(val, market, False, decimals)
    return "N/A" if s == "N/A" else f"{s}{suffix}"


# ── blocks ────────────────────────────────────────────────────────────────
DATA_DISCIPLINE = (
    "## DATA DISCIPLINE — MANDATORY\n\n"
    "- Use ONLY the figures provided in this prompt. Do NOT recall revenues, margins, "
    "prices, ownership, short interest, or any number from memory or training data.\n"
    "- If a figure you need is not provided, write \"not provided\" and reason "
    "qualitatively — never substitute a remembered or estimated value.\n"
    "- Every web/news claim must cite the source URL given in the RESEARCH BRIEF. "
    "Do not assert news that is not in the brief.\n"
    "- Knowledge of events after the data dates below must not inform the analysis "
    "(look-ahead contamination).\n"
)


def format_financial_data(d, market="US"):
    L = []
    L.append("━" * 42)
    L.append(f"  FINANCIAL DATA BRIEF — {d.get('Ticker','?')}")
    L.append(f"  Data As Of           : {d.get('Data_Fetched_Date') or 'Unknown'}")
    L.append(f"  Next Earnings Report : {d.get('Next_Earnings_Date') or 'Not Available'}")
    L.append("━" * 42)
    L.append("")
    L.append("── MARKET SNAPSHOT ──────────────────")
    L.append(f"  Stock Price          : {fmt(d.get('Price'), market, True)}")
    L.append(f"  Fully Diluted Shares : {fmt(d.get('Shares_Outstanding'), 'None', False, 0)}")
    L.append(f"  Market Cap           : {fmt(d.get('Market_Cap'), market)}")
    L.append(f"  Enterprise Value     : {fmt(d.get('Enterprise_Value_EV'), market)}")
    L.append(f"  Total Cash           : {fmt(d.get('Total_Cash'), market)}")
    L.append(f"  Total Debt           : {fmt(d.get('Total_Debt'), market)}")
    L.append(f"  Stock-Based Comp     : {fmt(d.get('SBC_Stock_Based_Comp'), market)}")
    L.append(f"  Operating Cash Flow  : {fmt(d.get('Operating_Cash_Flow'), market)}")
    L.append(f"  CapEx                : {fmt(d.get('Capital_Expenditure'), market)}")
    L.append(f"  Free Cash Flow TTM   : {fmt(d.get('Free_Cash_Flow_TTM'), market)}")
    L.append("")
    m = d.get("Calculated_Metrics") or {}
    L.append("── CALCULATED METRICS (TTM) ─────────")
    L.append(f"  TTM Revenue          : {fmt(m.get('TTM_Revenue'), market)}")
    L.append(f"  Gross Margin         : {_suf(m.get('TTM_Gross_Margin_%'), 'None', '%', 1)}")
    L.append(f"  YoY Revenue Growth   : {_suf(m.get('YoY_Revenue_Growth_%'), 'None', '%', 1)}")
    L.append(f"  FCF Margin           : {_suf(m.get('FCF_Margin_%'), 'None', '%', 1)}")
    L.append(f"  Rule of 40           : {_suf(m.get('Rule_of_40'), 'None', ' pts', 1)}")
    L.append(f"  EV / Sales           : {_suf(m.get('EV_to_Sales'), 'None', 'x', 2)}")
    L.append(f"  EV / Gross Profit    : {_suf(m.get('EV_to_Gross_Profit'), 'None', 'x', 2)}")
    L.append(f"  EV / EBIT            : {_suf(m.get('EV_to_EBIT'), 'None', 'x', 2)}")
    L.append(f"  Core Anchor Multiple : {_suf(m.get('Core_Anchor_Multiple_0.4Sales_0.4GP'), 'None', 'x', 2)}")
    L.append("")

    def income(rows, title, period_label):
        if not rows:
            return
        L.append(title)
        for r in rows:
            L.append(f"  {period_label}: {r.get('Date')}")
            L.append(f"    Revenue          : {fmt(r.get('TotalRevenue'), market)}")
            L.append(f"    Gross Profit     : {fmt(r.get('GrossProfit'), market)}")
            L.append(f"    Operating Income : {fmt(r.get('OperatingIncome'), market)}")
            L.append(f"    Net Income       : {fmt(r.get('NetIncome'), market)}")
            if r.get("DilutedEPS") is not None or r.get("BasicEPS") is not None:
                L.append(f"    EPS (Dil/Basic)  : {r.get('DilutedEPS','N/A')} / {r.get('BasicEPS','N/A')}")
        L.append("")

    income(d.get("Annual_Income_Statement"), "── ANNUAL INCOME STATEMENT ─────────", "Period")
    income(d.get("Quarterly_Income_Statement"), "── QUARTERLY INCOME STATEMENT ──────", "Quarter")
    L.append("━" * 42)
    return "\n".join(L)


def reverse_priming(rev):
    if not rev or not rev.get("rev_band") or rev.get("rev_band") == "Excluded":
        return ""
    p = ["## Reverse Screening Engine — Pre-Analysis Context", "",
         "This stock was triaged by the reverse screening engine. Findings are a "
         "starting hypothesis to verify and challenge, NOT a verdict:", ""]
    arch = rev.get("rev_archetype")
    if arch:
        name = ARCHETYPE_NAMES.get(arch, arch)
        sec = rev.get("rev_archetype_secondary")
        astr = f"{arch} ({name})" + (f" +{sec} transition" if sec else "")
        p.append(f"- Archetype (triage): {astr}")
    if rev.get("rev_composite") is not None:
        p.append(f"- Reverse composite: {round(rev['rev_composite'])}/100 "
                 f"(band: {rev.get('rev_band')}, rank: #{rev.get('rev_rank','?')})")
    if rev.get("rev_mos") is not None:
        p.append(f"- Margin-of-safety proxy: {round(rev['rev_mos'])}/100")
    p.append(f"- Quality: {rev.get('rev_quality','?')}/100 | "
             f"Survivability: {rev.get('rev_survivability','?')}/100 | "
             f"Impairment prob: {round(rev['rev_impairment_prob']*100) if rev.get('rev_impairment_prob') is not None else '?'}%")
    if rev.get("rev_cagr_proxy") is not None:
        p.append(f"- CAGR proxy: {rev['rev_cagr_proxy']:.1f}% | "
                 f"Drawdown proxy: {rev['rev_drawdown_proxy']*100:.1f}%" if rev.get("rev_drawdown_proxy") is not None
                 else f"- CAGR proxy: {rev['rev_cagr_proxy']:.1f}%")
    if rev.get("rev_data_quality") is not None:
        p.append(f"- Data quality: {rev['rev_data_quality']}/5 | Route confidence: {rev.get('rev_route_confidence','?')}")
    if rev.get("rev_pro"): p.append(f"- Strongest reason flagged: {rev['rev_pro']}")
    if rev.get("rev_con"): p.append(f"- Strongest concern flagged: {rev['rev_con']}")
    if rev.get("rev_flags"):
        flags = ", ".join(f for f in rev["rev_flags"].split(",") if f)
        p.append(f"- Forensic flags: {flags}")
    p.append("")
    return "\n".join(p) + "\n"


def forward_priming(eps_traj, analyst):
    """Consensus forward estimates — the screener fetches these (eps_trajectory.json,
    analyst_coverage.json) but neither the cloud prompt-builder.ts nor the trailing
    financials/{T}.json expose them. Fed as [Estimate] expectations, NOT ground truth."""
    L = []
    if eps_traj:
        parts = []
        if eps_traj.get("next_q_eps") is not None:
            parts.append(f"next Q ${eps_traj['next_q_eps']:.2f}")
        if eps_traj.get("next_q_plus_1_eps") is not None:
            parts.append(f"Q+1 ${eps_traj['next_q_plus_1_eps']:.2f}")
        if eps_traj.get("next_y_eps") is not None:
            parts.append(f"next FY ${eps_traj['next_y_eps']:.2f}")
        if parts:
            slope = eps_traj.get("trajectory_slope")
            L.append(f"- Consensus forward EPS [Estimate]: {', '.join(parts)}"
                     + (f" (trajectory slope {slope})" if slope is not None else "")
                     + f". Source: {eps_traj.get('source','analyst consensus')}.")
    if analyst:
        a = []
        if analyst.get("analyst_count") is not None:
            a.append(f"{analyst['analyst_count']} analysts")
        if analyst.get("buy_consensus_ratio") is not None:
            a.append(f"{analyst['buy_consensus_ratio']*100:.0f}% buy-rated")
        if analyst.get("structured_score") is not None:
            a.append(f"coverage score {analyst['structured_score']}/100")
        if a:
            L.append(f"- Analyst sentiment [Estimate]: {', '.join(a)}.")
    if not L:
        return ""
    # Analyst PRICE TARGETS are deliberately omitted (they were a consensus crutch — AUDIT.md H5).
    # Forward EPS is kept only as a sanity check on the implied-growth believability.
    return ("## FORWARD ESTIMATES (consensus — a sanity check on believability, NOT a target)\n\n"
            + "\n".join(L) + "\n\n"
            "Use consensus forward EPS only to sanity-check whether the price-implied growth in the "
            "VALUATION block is consistent with what analysts expect, and buy-rating as Layer 5.5 "
            "sentiment. Do NOT treat any analyst figure as intrinsic value.\n")


def overlay_priming(ov):
    if not ov:
        return ""
    L = []
    g = ov.get("gpr")
    if g and g.get("gpr_level") is not None:
        ch = f" via {', '.join(g['channels'])}" if g.get("channels") else ""
        L.append(f"- Geopolitical exposure (LLM-tagged): level {g['gpr_level']}/3{ch}. {g.get('note','')}")
    if ov.get("informed_demand") == 1:
        L.append("- Informed demand: POSITIVE (insider net buying without rising short interest) — confirming.")
    if ov.get("informed_demand") == -1:
        L.append("- Informed demand: NEGATIVE (insider selling with elevated/rising short interest) — red flag.")
    if ov.get("inst_pct") is not None:
        L.append(f"- Institutional ownership: {ov['inst_pct']*100:.1f}% (screener overlay).")
    if not L:
        return ""
    return "## Risk Overlay Context\n\n" + "\n".join(L) + "\n\n"


def _fresh(date_str, max_age_days):
    if not date_str:
        return False
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(str(date_str)[:19], f)
            age = (datetime.now() - dt).days
            return 0 <= age <= max_age_days   # future-dated synthetic => age<0 => rejected
        except ValueError:
            continue
    return False


def macro_block(macro_state, regime):
    """Real macro from macro_state.json (primary). Regime probs only if MRI file is fresh."""
    L = ["## MACRO CONTEXT (verified — use for Layer 1, do NOT recall macro from memory)", ""]
    if macro_state and macro_state.get("series"):
        L.append(f"Macro snapshot as of {macro_state.get('fetched_at','?')} (source: {macro_state.get('source','FRED')}):")
        for sid, s in macro_state["series"].items():
            L.append(f"  - {s.get('label', sid)}: {s.get('value')} (as of {s.get('as_of','?')}) — {s.get('interpretation','')}")
        flags = macro_state.get("triggered_flags")
        if flags:
            L.append(f"  - Triggered macro flags: {', '.join(flags) if isinstance(flags, list) else flags}")
    else:
        L.append("Macro snapshot: not provided.")
    L.append("")
    if regime and regime.get("_fresh"):
        L.append(f"Regime model (Macro Regime Indicator, as of {regime.get('date')}): "
                 f"dominant = {MRI_REGIME_LABELS.get(regime.get('dominant_regime'), regime.get('dominant_regime'))}, "
                 f"confidence {regime.get('confidence')}.")
        rp = regime.get("regime_probabilities", {})
        if rp:
            L.append("  Regime probabilities: " +
                     ", ".join(f"{MRI_REGIME_LABELS.get(k,k)} {v*100:.0f}%" for k, v in rp.items()))
        L.append("")
    else:
        L.append("Regime model: not available/stale — derive the 4-regime probability "
                 "distribution (Goldilocks / Reflation / Stagflation / Recession) yourself "
                 "from the verified macro snapshot above (must total 100%).")
        L.append("")
    return "\n".join(L)


# ── optional Bucket B / C ─────────────────────────────────────────────────
def enrichment_block(ticker):
    path = Path(CONFIG["out_enrich_dir"]) / f"{ticker.upper()}.json"
    e = load_json(path)
    if not e:
        return ("## BEHAVIORAL / POSITIONING DATA\n\n"
                "Not provided (run enrich_ticker.py). Tag related Layer 5.5 items "
                "[Unconfirmed].\n")
    L = ["## BEHAVIORAL / POSITIONING DATA (verified, yfinance — Layer 5.5 / Layer 1 DXY)", ""]
    for k, v in e.items():
        if k.startswith("_"):
            continue
        L.append(f"  - {k}: {v}")
    L.append("")
    return "\n".join(L)


def openbb_block(ticker):
    """Analyst-grade data via OpenBB (consensus targets, insider, 13F, metrics, transcript).
    Imported lazily — openbb load is heavy and only needed during a full run."""
    try:
        import openbb_data
        return openbb_data.format_block(ticker)
    except Exception as e:
        return f"## ANALYST-GRADE DATA (OpenBB)\n\nNot available ({str(e)[:120]}).\n"


def news_block(ticker, days=14, max_items=10, char_cap=1500):
    """Supplemental RECENT HEADLINES via the defeatbeta HF dataset (free, remote-DuckDB
    per-ticker query — no bulk download, no Yahoo throttling). The deep-research brief
    stays the primary news source; this covers the gap on research-cache-hit days when
    the brief may be up to research_cache_days old. Empty string on any failure or for
    names the dataset lacks (e.g. intl tickers) — never blocks the run."""
    try:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # package banner is emoji
        except Exception:
            pass
        from datetime import timedelta
        from defeatbeta_api.data.ticker import Ticker as _DbTicker
        nl = _DbTicker(ticker.upper()).news().get_news_list()
        if nl is None or len(nl) == 0:
            return ""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        nl = nl[nl["report_date"].astype(str) >= cutoff].sort_values("report_date", ascending=False)
        if len(nl) == 0:
            return ""
        # ON-ENTITY filter: Yahoo tags loosely (NVDA's feed carries ARM/Costco pieces), so keep only
        # headlines whose TITLE mentions the ticker (3+ chars — 'V'/'MA' would match noise) or the
        # company's lead name token ('NVIDIA Corporation' -> NVIDIA, 'Visa Inc.' -> Visa). Word-bounded.
        import re as _re
        fin = load_json(Path(CONFIG["screener_data_dir"]) / "financials" / f"{ticker.upper()}.json") or {}
        stop = {"the", "corporation", "corp", "inc", "incorporated", "ltd", "limited", "plc",
                "co", "company", "group", "holdings", "holding", "sa", "nv", "ag", "se"}
        toks = [w for w in _re.sub(r"[^A-Za-z0-9 ]", " ", str(fin.get("Name") or "")).split()
                if w.lower() not in stop][:1]
        pats = ([ticker.upper()] if len(ticker) >= 3 else []) + toks
        scope = "on-entity"
        if pats:
            rx = r"\b(?:" + "|".join(_re.escape(p) for p in pats) + r")\b"
            nl = nl[nl["title"].astype(str).str.contains(rx, case=False, regex=True, na=False)]
            if len(nl) == 0:
                return ""
        else:
            # short ticker + no Name in financials -> can't filter; be honest about the scope
            scope = "loosely tagged, may include sector/peer stories"
        L = [f"## RECENT HEADLINES (Yahoo via defeatbeta, last {days}d, {scope} — recency signals "
             "ONLY; for any claim cite the RESEARCH BRIEF or the headline's own link)", ""]
        for r in nl.head(max_items).itertuples(index=False):
            L.append(f"- [{r.report_date}] {r.title} — {r.publisher} ({r.link})")
        L.append("")
        out = "\n".join(L)
        if len(out) > char_cap:
            out = out[:char_cap].rsplit("\n", 1)[0] + "\n"   # cut at a whole headline, not mid-URL
        return out
    except Exception:
        return ""


def research_block(ticker):
    path = Path(CONFIG["out_research_dir"]) / f"{ticker.upper()}.md"
    try:
        md = path.read_text(encoding="utf-8").strip()
    except Exception:
        md = ""
    if not md:
        return ("## DEEP RESEARCH BRIEF (news / catalysts / competitive / bear-case)\n\n"
                "Not provided (run deep_research.py). Tag news-dependent items [Unconfirmed]; "
                "do NOT invent news.\n")
    # Cap what's fed to each stage (full brief stays on disk for audit). Keeps total
    # context within the 24576 budget once prior-stage results accumulate.
    cap = int(CONFIG.get("research_feed_char_cap", 14000))
    if len(md) > cap:
        md = md[:cap] + "\n\n…[brief truncated for context; full version in research/" + ticker.upper() + ".md]"
    return ("## DEEP RESEARCH BRIEF (cite only sources listed here)\n\n" + md + "\n")


# ── main assembly ─────────────────────────────────────────────────────────
def build_data_context(ticker):
    t = ticker.upper()
    market = market_for(t)
    sd = Path(CONFIG["screener_data_dir"])

    fin = load_json(sd / "financials" / f"{t}.json")
    rev = (load_json(sd / "reverse_scores.json") or {}).get(t)
    ov = ((load_json(sd / "overlay_signals.json") or {}).get("tickers") or {}).get(t)
    eps_traj = ((load_json(sd / "eps_trajectory.json") or {}).get("tickers") or load_json(sd / "eps_trajectory.json") or {}).get(t)
    analyst = ((load_json(sd / "analyst_coverage.json") or {}).get("tickers") or load_json(sd / "analyst_coverage.json") or {}).get(t)
    macro = load_json(sd / "macro_state.json")

    regime = load_json(Path(CONFIG["mri_outputs_dir"]) / "current_regime.json")
    if regime:
        regime["_fresh"] = _fresh(regime.get("date"), CONFIG.get("regime_max_age_days", 45))

    if fin:
        fin_brief = format_financial_data(fin, market)
    else:
        fin_brief = (f"## FINANCIAL DATA BRIEF — {t}\n\nNot provided "
                     f"(no financials/{t}.json). All fundamental figures are [Unconfirmed]; "
                     f"do NOT recall them from memory.")

    parts = [
        f"### Company Ticker: {t}   (market: {market})",
        "",
        DATA_DISCIPLINE,
        classification_context(t),
        reverse_priming(rev),
        valuation_block(t),          # inverted: deterministic reverse-DCF backbone (replaces
                                     # forward-DCF priming + the analyst-consensus anchor crutch)
        forward_priming(eps_traj, analyst),
        overlay_priming(ov),
        macro_block(macro, regime),
        enrichment_block(t),
        openbb_block(t),
        research_block(t),
        news_block(t),
        fin_brief,
    ]
    return "\n".join(p for p in parts if p is not None)


def market_anchor(ticker):
    """Tiny verified-fact header for the FINAL assembly (avoids re-sending the
    bulky research/priming blocks while keeping the model's numbers anchored)."""
    t = ticker.upper()
    market = market_for(t)
    fin = load_json(Path(CONFIG["screener_data_dir"]) / "financials" / f"{t}.json")
    if not fin:
        return f"VERIFIED ANCHOR — {t}: financials not provided; keep prior-stage numbers."
    m = fin.get("Calculated_Metrics") or {}
    return (
        f"VERIFIED ANCHOR (use these exact figures; do not alter) — {t}:\n"
        f"  T0 Price {fmt(fin.get('Price'), market, True)} (as of {fin.get('Data_Fetched_Date')}) | "
        f"Mkt Cap {fmt(fin.get('Market_Cap'), market)} | EV {fmt(fin.get('Enterprise_Value_EV'), market)} | "
        f"Shares {fmt(fin.get('Shares_Outstanding'), 'None', False, 0)}\n"
        f"  TTM Rev {fmt(m.get('TTM_Revenue'), market)} | FCF TTM {fmt(fin.get('Free_Cash_Flow_TTM'), market)} | "
        f"Gross Margin {_suf(m.get('TTM_Gross_Margin_%'),'None','%',1)} | "
        f"EV/Sales {_suf(m.get('EV_to_Sales'),'None','x',2)} | "
        f"Core Anchor {_suf(m.get('Core_Anchor_Multiple_0.4Sales_0.4GP'),'None','x',2)}"
    )


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: python rs2_data.py <TICKER>", file=sys.stderr)
        sys.exit(1)
    print(build_data_context(sys.argv[1]))
