#!/usr/bin/env python3
"""valuation_backbone.py — deterministic reverse-DCF valuation backbone.

Port of the screener's scripts/build_valuation_models.py into RS2 Local, per-ticker, so the
local engine uses the SAME sound, reproducible method instead of letting the 3B model guess
base_cf / growth / WACC (see AUDIT.md C2/H1-H6).

Method (expectations investing):
  base_cf  = owner earnings (NI + D&A - capex), from SEC fundamentals_history.json.
             Honest NULL when <= 0 (never a fabricated number) -> caller routes to Engine 4.
             Cyclicals (energy/materials/industrials) use MID-CYCLE owner earnings (multi-yr avg),
             because a single trough/peak fiscal year is unrepresentative.
  WACC     = sector table (mirror of scripts/reverse_config.json).
  implied  = growth solved so PV(base_cf @ WACC, two-stage 5+5) == MARKET CAP (equity; no
             net_cash bridge -- the screener's consistent convention).
  evidence = demonstrated 5y revenue & FCF CAGR; expectations gap = implied - demonstrated rev CAGR.

backbone(ticker) -> dict with ok=True + fields, OR {"ok": False, "reason": ...}.
Deterministic, reproducible, no LLM / no network. Standalone CLI: python valuation_backbone.py NVDA
"""
import json
import math
import re
import sys
from pathlib import Path

import valuation_engine as ve   # dcf_value — identical math to lib/dcf.ts
import rs2_data                 # sector_lookup, load_json, CONFIG

CONFIG = rs2_data.CONFIG
SD = Path(CONFIG["screener_data_dir"])
HERE = Path(__file__).resolve().parent

FWD_GROWTH_CEIL = 0.20     # forward-growth cap for the fair-value DCF (no blind hyper-extrapolation)

# GROWTH PERSISTENCE — MEASURED, not assumed (2026-08-11). FWD_GROWTH_CEIL was an invented
# constant: it stopped hyper-extrapolation but contradicted the gap signal on corroborated
# accelerators, and letting delivered growth run instead reproduced the malfunction it existed
# to prevent (MU: +2784% MoS off a 346% supercycle quarter). So the question was measured
# against the corpus: for every ticker-year that delivered growth g0, what did the company
# ACTUALLY compound over the next five years? n=3,115 ticker-years, 12y history, 5,600 tickers:
#     delivered   n     p25    median    p75     p90
#     15-25%   1092    3.2%     9.4%   16.0%   24.6%
#     25-40%    811    3.9%    12.1%   21.4%   29.8%
#     40-70%    619    3.8%    14.5%   27.3%   44.9%
#       >70%    593    0.1%    16.5%   35.5%   57.3%
# High growth DOES predict higher forward growth, and decays hard: >70% growers go on to
# compound at a median 16.5%, not 70%. (lo, hi) = (median, p75) per bucket — the honest central
# case and a defensible optimistic case, both empirical. Re-derive with tools/growth_persistence.
GROWTH_PERSISTENCE = ((0.15, (0.094, 0.160)), (0.25, (0.121, 0.214)),
                      (0.40, (0.145, 0.273)), (0.70, (0.165, 0.355)))


def persistence_growth(delivered):
    """(central, optimistic) forward-5y CAGR empirically consistent with what a company just
    delivered, or (None, None) below the 15% measurement floor (ordinary growth — the analyst
    consensus is the better estimate there and needs no persistence haircut)."""
    if not isinstance(delivered, (int, float)) or delivered < 0.15:
        return None, None
    band = GROWTH_PERSISTENCE[0][1]
    for lo, vals in GROWTH_PERSISTENCE:
        if delivered >= lo:
            band = vals
    return band

# STABILITY FENCE (2026-08-07). The fair value used to be fenced against the ANALYST BAND: if the
# DCF landed outside it, snap to the consensus median. Measured across 241 live covered names,
# that fired for 87% -- 67% snapped UPWARD, because the engine's own DCF says the median name is
# worth 0.57x the analyst target. So the published "fair value" was the analyst number for
# essentially the whole book, MoS collapsed to a median of +2.5% (fair value IS the target, minus
# one year of discounting), and the <15% ENTRY DISCIPLINE / DOCK rules then fired on 80% of names.
# That is the homogenization: 76% of verdicts landed at conviction 7-9 and 67% shared one action.
#
# The fence was originally added for a REAL problem -- trailing-CAGR extrapolation blew up 2-12x on
# post-IPO / hyper-ramp names (HRMY +1143% MoS). But forward-anchoring and FWD_GROWTH_CEIL landed in
# the same change and appear to have done the actual work: measured today, the median name's MoS
# moves only 5.9pts per 1pt of growth input (p90 14.3pts), and the pathology is concentrated in ~13
# names. Fencing all 247 to control 13 destroyed the signal.
#
# So fence on INSTABILITY, measured from our own numbers, instead of on disagreement with analysts:
# perturb the growth input +/-1pt and see how far the answer moves. A model whose output swings
# wildly on a 1pt input change is not producing a usable value for that name -- which is a
# defensible reason to distrust it, unlike "analysts disagree". Verified to catch HRMY, the original
# bug report, plus BWMX (+9653% MoS), FMX (+2811%), CALM (+833%).
MOS_SENSITIVITY_MAX = 20.0   # pts of MoS per +/-1pt of growth input
MOS_EXTREME_MAX = 1.00       # |MoS| above 100% is not a valuation, it is a malfunction
STALE_TARGET_DAYS = 45     # analyst-target band older than this is flagged low-confidence


def _iso_age_days(iso):
    """Age in days of an ISO timestamp string, or None."""
    if not iso:
        return None
    try:
        from datetime import datetime, timezone
        s = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except Exception:
        return None


def _consensus_band(ticker):
    """Analyst consensus price-target band {low, median, high, n, age_days, stale, source} or None.
    Prefer the OpenBB cache (richer); fall back to the yfinance enrich file. No network — reads the
    already-fetched JSON artifacts, keeping the backbone deterministic."""
    t = ticker.upper()
    ob = rs2_data.load_json(HERE / "cache" / f"openbb_{t}.json") or {}
    def _sane(lo, hi):
        lo, hi = _num(lo), _num(hi)
        # reject corrupt/degenerate bands (e.g. ATAT high $558 vs $32 price) — too dispersed to fence
        return bool(lo and hi and lo > 0 and hi >= lo and hi / lo <= 6)
    c = ob.get("analyst_consensus") or {}
    lo, med, hi = c.get("target_low"), c.get("target_median") or c.get("target_consensus"), c.get("target_high")
    if _sane(lo, hi):
        age = _iso_age_days(ob.get("_fetched_at"))
        return {"low": _num(lo), "median": _num(med) or (_num(lo) + _num(hi)) / 2, "high": _num(hi),
                "n": c.get("number_of_analysts"), "age_days": round(age, 1) if age is not None else None,
                "stale": bool(age is not None and age > STALE_TARGET_DAYS), "source": "openbb"}
    en = rs2_data.load_json(HERE / "enrich" / f"{t}.json") or {}
    lo, med, hi = en.get("analyst_target_low"), en.get("analyst_target_median") or en.get("analyst_target_mean"), en.get("analyst_target_high")
    if _sane(lo, hi):
        age = _iso_age_days(en.get("_fetched_at"))
        return {"low": _num(lo), "median": _num(med) or (_num(lo) + _num(hi)) / 2, "high": _num(hi),
                "n": en.get("analyst_count"), "age_days": round(age, 1) if age is not None else None,
                "stale": bool(age is not None and age > STALE_TARGET_DAYS), "source": "enrich"}
    return None


def _forward_growth(ticker):
    """Forward analyst growth as a fraction/yr, plus its source. Priority:
    OpenBB cached forward_growth (revenue then EPS) -> PEG-implied (pe/peg) -> (None, None).
    No network — reads the cache the openbb_data step already wrote."""
    t = ticker.upper()
    ob = rs2_data.load_json(HERE / "cache" / f"openbb_{t}.json") or {}
    fg = ob.get("forward_growth") or {}
    for key in ("revenue_cagr", "eps_cagr"):
        v = _num(fg.get(key))
        if v is not None:
            return v, f"fwd_{key}"
    m = ob.get("metrics") or {}
    pe, peg = _num(m.get("pe_ratio")), _num(m.get("peg_ratio"))
    if pe and peg and pe > 0 and peg > 0:
        g = (pe / peg) / 100.0            # PEG = PE / growth% -> growth% = PE/PEG
        if 0 < g < 1.5:
            return g, "peg_implied"
    return None, None

TERMINAL_G = 0.025
STAGE1, FADE = 5, 5
G_LO, G_HI = -0.50, 1.50          # implied-growth solver bounds (wide; diagnostic, like the screener)

# Mirror of scripts/reverse_config.json sector_wacc (percent). Kept here because the screener's
# scripts/ are git-tracked but not checked out locally. Resync if the screener table changes.
# NAMING: these are labelled WACC for historical continuity with the screener, but in THIS engine's
# equity framing they function as a COST-OF-EQUITY proxy — base_cf = NI + D&A - capex is net of
# interest (a levered flow), discounted and compared against MARKET CAP. Pairing that flow with a
# true firm-level WACC and enterprise value was tried (2026-08-07), proven to double-count the
# debt claim, and reverted; see CLAUDE.md "Standard of Proof".
SECTOR_WACC = {
    "Technology": 11, "Healthcare": 10, "Consumer Discretionary": 10, "Consumer Staples": 8,
    "Industrials": 9, "Financials": 10, "Energy": 11, "Materials": 10, "Utilities": 7,
    "Real Estate": 8, "Communication Services": 10,
}
SECTOR_ALIASES = {  # stocks.csv carries Yahoo sector names; the WACC table uses GICS-ish names
    "Consumer Cyclical": "Consumer Discretionary", "Consumer Defensive": "Consumer Staples",
    "Financial Services": "Financials", "Basic Materials": "Materials",
}
DEFAULT_WACC = 10.0
# Commodity / heavy-capex cyclicals whose latest fiscal year is trough/peak distorted -> use
# mid-cycle owner earnings. Utilities are deliberately EXCLUDED (regulated, steady; latest-FY fine).
MIDCYCLE_SECTORS = ("energy", "materials", "industrials")

# Balance-sheet financials are ROUTED BY INDUSTRY to the P/B-ROE model (2026-07-11): the old
# base_cf<=0 trigger almost never fired for insurers/banks (their NI+D&A-capex is usually
# POSITIVE), so UVE/HG-type names ran the owner-earnings DCF the AUDIT calls structurally
# invalid for them. Yahoo lumps card networks (V/MA) under "Credit Services" with lenders,
# so Credit Services deliberately STAYS on the reverse-DCF (asset-light correctness dominates);
# so do Capital Markets / Asset Management / exchanges (fee businesses).
PB_ROE_INDUSTRIES = ("bank", "insurance", "mortgage")   # substring match, lowercase Yahoo industry
PB_ROE_EXCLUDE = ("insurance broker",)                  # fee businesses, not underwriters

# RATE-REGULATED utilities are book-value businesses like banks, for the same structural reason:
# the regulator sets allowed ROE on a RATE BASE that is essentially book equity, and the 1.3-2.0x
# P/B they trade at IS the capitalised spread of allowed ROE (9.5-11%) over market cost of equity
# (6-7%). So they belong on the SAME justified-P/B model, not on an owner-earnings DCF: a growing
# utility funds rate-base expansion with capex > D&A permanently, making NI+D&A-capex structurally
# negative (measured: 58 of 116 utilities returned negative_base_cash_flow, which then routed them
# to the Engine-4 OPTION bridge -- the most speculative path for the most predictable businesses).
# Substring match on the lowercase Yahoo industry: catches "Utilities-Regulated {Electric,Gas,Water}"
# (76 names) and deliberately EXCLUDES Renewable / Independent Power Producers / Diversified, which
# are merchant or contracted generators with no rate base to earn on.
REGULATED_UTILITY_INDUSTRIES = ("regulated",)
UTIL_COE = 0.07   # market cost of equity for a large regulated utility (= the Utilities sector WACC)

# Ceiling on the ROE fed to the justified-P/B for a REGULATED utility. A rate-regulated return is
# bounded by what the commission allows (9.5-11% industry-wide; measured here: median 9.2%, p90
# 12.5%), so a one-off 24% year is an asset sale or a depressed equity base, NOT rate-base earning
# power that can be capitalised in perpetuity. Without this the Gordon form explodes: utility CoE
# is 7% and g caps at 4%, leaving a 3% denominator -- HALF the 6% a bank gets at CoE 10% -- so
# (ROE-g)/(CoE-g) turned EIX's 24.4% into a 6.8x justified P/B and a +376% MoS, and BIPC's 34.9%
# into 10.3x and +276%. Both shipped UNFENCED because neither has an analyst band (51 of 56
# utilities have none), i.e. straight to the verdict as a screaming BUY.
# 15% is deliberately generous -- well above p90 -- so it binds only on genuine outliers.
UTIL_ROE_CEIL = 0.15


def _pow1000_ratio(a, b):
    """Power-of-1000 step between |a| and |b| if there is one, else None. Same definition as
    the screener extractor's scale defence (0.7p..1.4p band): one economic quantity cannot be
    a clean factor-of-1000 from itself, so a hit is provable corruption, never judgement."""
    if not a or not b:
        return None
    r = abs(a) / abs(b)
    if r < 1:
        r = 1 / r
    for p in (1e3, 1e6, 1e9):
        if 0.7 * p <= r <= 1.4 * p:
            return p
    return None


def _num(v):
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


# ── Ingest guard: share counts ───────────────────────────────────────────────────────────────
# SEC filings contradict themselves on scale. The same fiscal period is sometimes reported twice
# with values a clean power of 1000 apart, and the corrupt value usually sits in the LATER filing,
# so "most recent wins" picks it. The screener's extractor now resolves those contradictions at
# source, but it CANNOT fix a year where only one (wrong) value was ever filed — BKTI reported
# shares in thousands through FY2022 with nothing to contradict it. So the number is validated
# again here, on the way in. Nothing corrupt gets to enter a valuation, whatever upstream says.
#
# shares_diluted is the field that matters most: it is 49% of all ~1000x breaks measured (331 of
# 672 across 451 tickers), and it divides into FFO-per-share, the Engine-5 net-cash floor and the
# Engine-5 dilution term.
#
# The test is CROSS-SOURCE, not magnitude. financials.json Shares_Outstanding comes from a
# different provider entirely, so agreement is real evidence. Measured on 255 live names: 253
# agree within 5x, and the 2 that disagree (VTEX, BWMX) are at exactly 0.001x. Zero false
# positives — AMZN's real 20:1 split appears in BOTH sources and so does not trip it.
#
# A magnitude test was evaluated and REJECTED: at a 10x bar it flags NVDA's real $120bn net income
# (29x its own median), AMZN's split (21.5x), AMD's Xilinx equity (22.3x) and CRM's margin
# expansion (20.7x). A filter that deletes the best names in the book is worse than the corruption.
SHARES_SCALE_TOLERANCE = 5.0     # agreement band vs the independent source


def _shares_sane(shares_diluted, shares_outstanding):
    """(value_to_use, was_corrected). Rescales a clean power-of-1000 discrepancy, else passes through.

    Returns the ORIGINAL value when there is no independent reference — an unverifiable number is
    not the same as a wrong one, and silently discarding it would lose real data.
    """
    sd, so = _num(shares_diluted), _num(shares_outstanding)
    if sd is None or sd <= 0 or so is None or so <= 0:
        return sd, False
    ratio = so / sd
    if 1.0 / SHARES_SCALE_TOLERANCE <= ratio <= SHARES_SCALE_TOLERANCE:
        return sd, False                      # agrees with the independent source
    for p in (1e3, 1e6):                      # clean scale error -> correct it
        if 0.7 * p <= ratio <= 1.4 * p:
            return sd * p, True
        if 0.7 * p <= 1.0 / ratio <= 1.4 * p:
            return sd / p, True
    return sd, False                          # disagrees but not by a scale factor — leave alone


def _hist(ticker):
    h = rs2_data.load_json(SD / "fundamentals_history.json") or {}
    t = (h.get("tickers") or h).get(ticker.upper())
    return t if isinstance(t, dict) else None


def _owner_earnings(fy):
    """Owner earnings = NI + D&A - capex for one fiscal-year dict, or None if inputs missing."""
    ni, da, capex = _num(fy.get("net_income")), _num(fy.get("da")), _num(fy.get("capex"))
    if None in (ni, da, capex):
        return None
    return ni + da - capex


def _cagr(first, last, years):
    if not first or not last or first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def _growth_evidence(ydata):
    """(revenue_cagr_5y, fcf_cagr_5y) from up to 6 fiscal years (mirror of the screener)."""
    yrs = sorted(int(y) for y in ydata.keys())
    rev = [(y, _num(ydata[str(y)].get("revenue"))) for y in yrs]
    rev = [(y, v) for y, v in rev if v and v > 0]
    fcf = [(y, _num(ydata[str(y)].get("fcf"))) for y in yrs]
    fcf = [(y, v) for y, v in fcf if v and v > 0]
    rc = fc = None
    if len(rev) >= 4:
        (ya, va), (yb, vb) = rev[max(0, len(rev) - 6)], rev[-1]
        rc = _cagr(va, vb, yb - ya)
    if len(fcf) >= 4:
        (ya, va), (yb, vb) = fcf[max(0, len(fcf) - 6)], fcf[-1]
        fc = _cagr(va, vb, yb - ya)
    return rc, fc


def _solve_implied_growth(base_cf, target_value, wacc):
    """Bisection for stage-1 g s.t. dcf_value == target_value (market cap). Wide bounds."""
    if base_cf <= 0 or target_value <= 0:
        return None
    f = lambda g: ve.dcf_value(base_cf, g, wacc, TERMINAL_G, STAGE1, FADE)
    lo_v, hi_v = f(G_LO), f(G_HI)
    if lo_v is None or hi_v is None:
        return None
    if target_value <= lo_v:
        return G_LO
    if target_value >= hi_v:
        return G_HI
    lo, hi = G_LO, G_HI
    for _ in range(60):
        mid = (lo + hi) / 2
        v = f(mid)
        if v is None:
            return None
        if v < target_value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _verdict(gap_pts):
    if gap_pts is None:
        return "No growth evidence to compare — judge the implied rate on its own."
    if gap_pts > 10:
        return f"Price demands ~{gap_pts:+.0f}pts MORE growth than demonstrated — must believe acceleration."
    if gap_pts > 5:
        return f"Price assumes modest acceleration ({gap_pts:+.0f}pts above demonstrated)."
    if gap_pts >= -5:
        return "Priced roughly in line with demonstrated growth."
    return f"Priced {abs(gap_pts):.0f}pts BELOW demonstrated growth — market expects deceleration."


def _ffo_ps_series(ydata, _shares_outstanding=None):
    """FFO per diluted share by fiscal year. FFO = net income + D&A: real-estate depreciation is
    an accounting fiction for an appreciating asset, which is exactly why owner earnings
    (NI+D&A-capex) misprices a REIT. Per SHARE because REIT revenue growth is largely acquisition
    roll-up funded by issuing equity -- O showed a 28.4% revenue CAGR that no existing holder
    received. Gains on property sales are NOT backed out (not in fundamentals_history), so this is
    NAREIT FFO less that adjustment."""
    out = []
    for y in sorted(int(v) for v in ydata.keys()):
        fy = ydata[str(y)]
        ni, da = _num(fy.get("net_income")), _num(fy.get("da"))
        sh, _ = _shares_sane(fy.get("shares_diluted"), _shares_outstanding)
        if ni is not None and da is not None and sh and sh > 0:
            out.append((y, (ni + da) / sh))
    return out


def _ffo_ps_cagr(ydata, _shares_outstanding=None):
    """CAGR of FFO/share over the available history, or None."""
    s = _ffo_ps_series(ydata, _shares_outstanding)
    if len(s) < 4 or s[0][1] <= 0 or s[-1][1] <= 0:
        return None
    yrs = s[-1][0] - s[0][0]
    return (s[-1][1] / s[0][1]) ** (1.0 / yrs) - 1.0 if yrs > 0 else None


def _midcycle_owner_earnings(ydata):
    """Mean of positive owner earnings across the available history, or None if too short."""
    owners = [_owner_earnings(ydata[str(y)]) for y in sorted(int(v) for v in ydata.keys())]
    owners = [o for o in owners if o is not None and o > 0]
    return (sum(owners) / len(owners)) if len(owners) >= 3 else None


def _midcycle_of_kind(ydata, kind):
    """Mid-cycle average of the SAME metric the name already uses, or (None, None).

    USED FOR DISCLOSURE ONLY -- it does not set base_cf. Normalizing a cyclical's base year
    cannot be done reliably from ~10 noisy annual observations, and four approaches were measured
    against each other before settling on disclosure:
      * sector whitelist (MIDCYCLE_SECTORS): misses 12 of 39 model-labelled cyclicals incl. MU.
      * coefficient-of-variation trigger: cyclicals (NOVT 0.28, ESCA 0.27) overlap completely
        with stable compounders (KO 0.35, AAPL 0.33) -- no threshold separates them.
      * raw mean: correct for a flat cyclical (MU +85.7 -> +60.8) but wrong for a secular grower,
        whose decade-average sits far below run-rate (AMD +18.9 -> +44.7, a fabricated
        overvalued signal).
      * log-linear trend fit: fixes the growers (AMD -> +7.4) but breaks the cyclicals, because a
        window starting at a cycle peak reads as secular decline (MU -> +100.0, worse than doing
        nothing at all).
    Trend and cycle are not separable at this sample size, so the engine reports BOTH bases and
    lets the analyst layer judge, rather than silently picking one and being wrong for half the
    universe. fcf_ttm_yf is a single trailing figure with no history -> (None, None).
    """
    yrs = sorted(int(v) for v in ydata.keys())
    if kind in ("owner_earnings", "blended_owner_earnings"):
        # The mid-cycle counterpart of the BLEND is the plain owner-earnings average: averaging
        # over the cycle already normalizes the margin, so averaging per-year blends would
        # shrink toward the median twice.
        vals = [_owner_earnings(ydata[str(y)]) for y in yrs]
        kind = "owner_earnings"
    elif kind == "fcf_fallback":
        vals = [_num(ydata[str(y)].get("fcf")) for y in yrs]
    elif kind == "ocf_minus_da_proxy":
        vals = []
        for y in yrs:
            ocf, da = _num(ydata[str(y)].get("ocf")), _num(ydata[str(y)].get("da"))
            vals.append(ocf - da if None not in (ocf, da) else None)
    else:
        return None, None
    pairs = [(y, v) for y, v in zip(yrs, vals) if v is not None and v > 0]
    if len(pairs) < 4:
        return None, None
    vs = [v for _, v in pairs]
    return sum(vs) / len(vs), f"midcycle_{kind}_archetype"


def _revenue_break(ydata):
    """Latest PERSISTENT revenue level shift (>40% step confirmed by the later-years median) in
    the history window: {"year": Y, "ratio": R} or None. DISCLOSURE ONLY — measured across the
    live blended book (2026-08-08, 22 flagged names): 8 of the 12 material flags are cyclical /
    COVID / organic-hypergrowth swings, not entity changes (CALM's egg-price cycles fire it twice
    — trimming there would anchor the margin at the avian-flu boom), 3 are divestiture
    RESTATEMENT breaks whose post-break rows are internally basis-mixed (WDC 2023: continuing-ops
    revenue against a consolidated net loss — a margin that ratio-s two different entities), and
    1 (HQY) is a clean acquisition. Revenue alone cannot tell these apart, so an automatic trim
    of the margin/averaging window is REJECTED: it would damage more names than it fixes. The
    break is surfaced to the analyst layer instead; the arithmetic stays untouched."""
    revs = []
    for y in sorted(ydata, key=int):
        r = _num(ydata[str(y)].get("revenue"))
        if r is not None and r > 0:
            revs.append((int(y), r))
    brk = None
    for i in range(1, len(revs)):
        step = revs[i][1] / revs[i - 1][1]
        if step < 0.60 or step > 1.67:
            later = [r for _, r in revs[i:]]
            if len(later) >= 2:
                import statistics as _st
                med = _st.median(later) / revs[i - 1][1]
                if med < 0.70 or med > 1.43:
                    brk = {"year": revs[i][0], "ratio": round(step, 2)}
    return brk


# fundamentals_ttm.json: trailing-twelve-month flows built at source from 10-Q YTD rows
# (TTM = FY + YTD_cur − YTD_prior, date-guarded; see the screener's build_fundamentals_history).
# Loaded lazily and re-read when the file changes — the orchestrator runs for hours across a
# rebuild.
_TTM_CACHE = {"mtime": None, "data": {}}
_QTR_CACHE = {"mtime": None, "data": {}}


def _cached_record(cache, fname, t):
    p = SD / fname
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    if cache["mtime"] != mt:
        cache["data"] = (rs2_data.load_json(p) or {}).get("tickers") or {}
        cache["mtime"] = mt
    return cache["data"].get(t.upper())


def _ttm_record(t):
    return _cached_record(_TTM_CACHE, "fundamentals_ttm.json", t)


def _quarterly_record(t):
    """Single-quarter sequence with YoY (fundamentals_quarterly.json) — the delivered-growth
    evidence the regime judgment rests on."""
    return _cached_record(_QTR_CACHE, "fundamentals_quarterly.json", t)


def apply_basis(bb, cell_name):
    """Rewrite a backbone result onto the earnings basis the analyst layer endorsed.

    Called BEFORE any stage runs (2026-08-12). The basis decision needs only filings data —
    the lattice, the quarterly trajectory, TTM figures and cycle history — so it does not have
    to wait for the report. Deciding it afterwards created a seam: the six stages reasoned on
    the engine's default basis, the VALUATION RESULT header showed that basis, the model
    dutifully wrote it into the Engine-verdict slot, and then the verdict switched underneath —
    after which the tier-1 slot check compared the slot against a value that had changed. The
    model was doing exactly as told and failing for it. Resolving first removes the seam
    instead of papering over it: stages, header, prose and verdict all agree by construction."""
    cell = ((bb.get("lattice") or {}).get("cells") or {}).get(cell_name or "")
    if not (bb.get("ok") and cell and cell.get("mos_pct") is not None):
        return bb
    out = dict(bb)
    out["base_cf_engine_default"] = bb.get("base_cf")
    out["mos_engine_default"] = bb.get("realistic_mos_pct")
    out["regime_basis"] = cell_name
    out["base_cf"] = cell.get("base_cf")
    out["base_cf_kind"] = f"lattice_{cell_name}"
    out["implied_growth"] = cell.get("implied_growth")
    if cell.get("gap_trailing") is not None:
        out["expectations_gap_pts"] = cell["gap_trailing"]
    if cell.get("fair_value") is not None:
        out["fair_value"] = cell["fair_value"]
        out["mos_pct"] = out["realistic_mos_pct"] = cell["mos_pct"]
        out["fair_value_method"] = f"lattice_{cell_name}"
    return out


def base_lattice(ydata, ttm, mcap, wacc, price, shares, demo_trail, g_fwd, delivered=None):
    """Every DEFENSIBLE base for this name, each priced through the same DCF frame.

    Why a lattice instead of one base (measured 2026-08-11 across the 144-name live book):
      * The engine capitalizes only 53% of the book's actual earnings ($642B base vs $1,212B
        TTM net income) because owner earnings subtract the WHOLE capex line. For 21 names it
        capitalizes under half — AMZN $37B vs $135B NI, because $173B of capex is AI/AWS
        BUILD-OUT, not maintenance. To call the book fair on that base the DCF would have to
        award ~50x while its frame awards 20-27x: a structural MoS floor, not analysis.
      * Mid-cycle averaging suppresses the base again through secular step-changes (HWM $0.63B
        average vs $1.87B current earning power).
      * The discount rate was tested as the culprit and CLEARED: the book's own pricing implies
        an 11.8% cost of equity vs the engine's ~10%, i.e. the rate is if anything generous.
        Recalibrating it would have moved every fair value the WRONG way.
    No single cell is right for every company, and which one is right is a JUDGMENT about
    whether today's capex is maintenance or expansion — so the engine computes them all and
    the analyst layer picks, in the open, with delivered evidence in front of it.

    Cells: current_earnings (maintenance capex ~ D&A, i.e. the market's own basis),
    owner_earnings (full capex; the conservative extreme), blend (margin-shrunk owner
    earnings), midcycle (cycle average). Yardsticks per cell: trailing CAGR, forward
    consensus, delivered TTM-YoY. Deterministic throughout — no model input."""
    if not (mcap and wacc and price and mcap > 0):
        return None
    yrs = sorted(int(y) for y in ydata.keys())
    fy = ydata[str(yrs[-1])]
    tf = (ttm or {}).get("fields") or {}
    bases = {}
    ni_t, da_t, cx_t = _num(tf.get("net_income")), _num(tf.get("da")), _num(tf.get("capex"))
    if ni_t is not None and ni_t > 0:
        bases["current_earnings"] = ni_t
        if None not in (da_t, cx_t):
            bases["owner_earnings"] = ni_t + da_t - cx_t
    else:
        ni_f, da_f, cx_f = (_num(fy.get("net_income")), _num(fy.get("da")), _num(fy.get("capex")))
        if ni_f is not None and ni_f > 0:
            bases["current_earnings"] = ni_f
            if None not in (da_f, cx_f):
                bases["owner_earnings"] = ni_f + da_f - cx_f
    owners = [_owner_earnings(ydata[str(y)]) for y in yrs]
    owners = [o for o in owners if o is not None and o > 0]
    if len(owners) >= 3:
        bases["midcycle"] = sum(owners) / len(owners)
    out = {}
    for name, base in bases.items():
        if not isinstance(base, (int, float)) or base <= 0:
            continue
        g_imp = _solve_implied_growth(base, mcap, wacc)
        if g_imp is None:
            continue
        cell = {"base_cf": round(base, 0), "base_cf_b": round(base / 1e9, 2),
                "implied_growth": round(g_imp, 4)}
        for lbl, yard in (("trailing", demo_trail), ("forward", g_fwd), ("delivered", delivered)):
            cell[f"gap_{lbl}"] = (round((g_imp - yard) * 100, 1)
                                  if isinstance(yard, (int, float)) else None)
        g_drive = g_fwd if g_fwd is not None else demo_trail
        if g_drive is not None:
            g_fair = max(-0.20, min(g_drive, FWD_GROWTH_CEIL))
            fm = ve.dcf_value(base, g_fair, wacc, TERMINAL_G, stage1_years=STAGE1,
                              fade_years=FADE)
            if fm and fm > 0:
                fv = price * fm / mcap
                cell["fair_value"] = round(fv, 2)
                cell["mos_pct"] = round((fv / price - 1) * 100, 1)
            # PERSISTENCE-BASED growth (replaces the invented 20% cap on names with delivered
            # evidence). The company's own delivered growth selects an EMPIRICAL forward CAGR
            # band from GROWTH_PERSISTENCE — what companies that grew this fast actually went
            # on to compound. Never the delivered rate itself (that reproduced MU's +2784%
            # malfunction), never above consensus, and the optimistic leg is the measured p75,
            # not a guess.
            _cen, _opt = persistence_growth(delivered)
            if _cen is not None:
                for lbl, gg in (("persist", _cen), ("persist_opt", _opt)):
                    g_p = max(-0.20, min(g_drive, gg) if g_drive is not None else gg)
                    fm2 = ve.dcf_value(base, g_p, wacc, TERMINAL_G, stage1_years=STAGE1,
                                       fade_years=FADE)
                    if fm2 and fm2 > 0:
                        fv2 = price * fm2 / mcap
                        m2 = round((fv2 / price - 1) * 100, 1)
                        # same malfunction fence the primary path uses — a lattice cell is not
                        # exempt from "|MoS| > 100% is not a valuation"
                        if abs(m2) <= MOS_EXTREME_MAX * 100:
                            cell[f"fair_value_{lbl}"] = round(fv2, 2)
                            cell[f"mos_{lbl}_pct"] = m2
                            cell[f"growth_{lbl}"] = round(g_p, 4)
        out[name] = cell
    if not out:
        return None
    moss = [v for c in out.values()
            for k, v in c.items()
            if k in ("mos_pct", "mos_persist_pct", "mos_persist_opt_pct") and v is not None
            and abs(v) <= MOS_EXTREME_MAX * 100]
    span = (round(min(moss), 1), round(max(moss), 1)) if moss else (None, None)
    return {"cells": out, "mos_low": span[0], "mos_high": span[1],
            # CONTESTED = the cells disagree enough that the basis choice, not the price,
            # decides the verdict. 30pts of MoS spread is the operative threshold: below it
            # every basis tells the same story and there is nothing to judge.
            "contested": bool(span[0] is not None and (span[1] - span[0]) >= 30.0)}


def _base_cf(ticker, ydata, sector_l, industry_l="", force_midcycle=False, force_latest=False,
             ttm=None):
    """Return (base_cf_$, kind, period_meta). Equity REITs -> FFO; cyclicals -> mid-cycle avg
    owner earnings; else LATEST-POINT owner earnings with fcf / ocf-minus-da fallbacks. None
    base_cf -> honest null upstream. force_latest skips the sector mid-cycle rule and returns
    the latest-point basis — DISCLOSURE ONLY (the mirror of force_midcycle, for names the
    sector whitelist already averaged): it never sets the scored base_cf.

    THE LATEST POINT IS TTM WHEN AVAILABLE (2026-08-08). The annual history's newest row is a
    completed fiscal year, up to ~11 months stale by fiscal calendar; measured live: HWM TTM
    net income $1,871M = +24% vs its FY leg, and MU's FY2025 base missed a hyper-cycle whose
    trailing owner earnings run ~18x higher across four internally consistent 10-Qs. `ttm`
    (validated/gated by the caller) supplies the trailing legs; a field set that cannot form a
    complete same-period pair falls back to the FY row — periods are NEVER mixed inside one
    estimator (no TTM owner earnings against FY revenue). Averages (mid-cycle) stay strictly
    annual: appending a trailing window to a cycle average would double-weight the newest
    period. kind strings are unchanged; period_meta ({"period","through"}) records which basis
    the point terms used.
    """
    yrs = sorted(int(y) for y in ydata.keys())
    fy = ydata[str(yrs[-1])]
    tf = (ttm or {}).get("fields") or {}
    t_ni, t_da, t_cx = _num(tf.get("net_income")), _num(tf.get("da")), _num(tf.get("capex"))
    t_rev, t_fcf = _num(tf.get("revenue")), _num(tf.get("fcf"))
    ttm_meta = ({"period": "ttm", "through": ttm.get("through")} if ttm else None)
    # Equity REIT -> FFO. Owner earnings subtract the whole capex line, but a REIT's capex is
    # mostly ACQUISITION of income-producing property, not maintenance of existing capacity, so
    # subtracting it understates earning power badly (O landed on an ocf-minus-da proxy of
    # $1.47B against an FFO several times that). Mortgage REITs are excluded upstream -- they
    # are lenders and route to the P/B-ROE model.
    if "reit" in industry_l and "mortgage" not in industry_l:
        if ttm_meta and t_ni is not None and t_da is not None and (t_ni + t_da) > 0:
            return t_ni + t_da, "ffo_reit", ttm_meta
        ni, da = _num(fy.get("net_income")), _num(fy.get("da"))
        if ni is not None and da is not None and (ni + da) > 0:
            return ni + da, "ffo_reit", None
    # The sector whitelist below is a PROXY for "is this company cyclical", and it misses: 12 of
    # 39 model-labelled cyclicals sit outside it, including MU, whose latest trough year produced
    # a 97.5% implied growth and an +85.7pt gap. No statistic separates cycle from growth here --
    # coefficient of variation overlaps completely between cyclicals (NOVT 0.28, ESCA 0.27) and
    # stable compounders (KO 0.35, AAPL 0.33) -- because averaging raw owner earnings over a
    # GROWING company mixes trend with cycle. force_midcycle lets the caller supply the judgment
    # the statistic cannot (see run_rs2: the Stage-1 archetype).
    if force_midcycle and not force_latest:
        # Resolve the metric this name would NATURALLY use, then average that same metric.
        _, nat_kind, _ = _base_cf(ticker, ydata, sector_l, industry_l, force_midcycle=False,
                                  ttm=ttm)
        mid, mid_kind = _midcycle_of_kind(ydata, nat_kind)
        if mid is not None:
            return mid, mid_kind, None
    # cyclical: average owner earnings over the available cycle (trough+peak cancel)
    if not force_latest and any(c in sector_l for c in MIDCYCLE_SECTORS):
        owners = [_owner_earnings(ydata[str(y)]) for y in yrs]
        owners = [o for o in owners if o is not None and o > 0]
        if len(owners) >= 3:
            return sum(owners) / len(owners), "midcycle_owner_earnings", None
        # too little history -> fall through to latest-point logic
    owner_fy = _owner_earnings(fy)
    # TTM owner earnings need the complete NI/D&A/capex trio — no mixed-period trios, no
    # proxies. A clean power-of-1000 step vs the FY leg means one side is scale-corrupt
    # (same defence as everywhere else; magnitude-vs-history filters stay banned): distrust
    # the TTM side, it has one filing behind it vs the FY's reconciled row.
    owner_ttm = (t_ni + t_da - t_cx) if None not in (t_ni, t_da, t_cx) else None
    if owner_ttm is not None and owner_fy is not None and _pow1000_ratio(owner_ttm, owner_fy):
        owner_ttm = None
    use_ttm = (ttm_meta is not None and owner_ttm is not None
               and t_rev is not None and t_rev > 0)
    owner = owner_ttm if use_ttm else owner_fy
    fcf = _num(fy.get("fcf"))
    ocf, da = _num(fy.get("ocf")), _num(fy.get("da"))
    if owner is not None and owner > 0:
        # MARGIN BLEND (2026-08-07). A single fiscal year's owner-earnings margin is a noisy
        # observation of earning power: measured causally over 4,685 clean ticker-years, margins
        # mean-revert monotonically toward their own history (a year >50% above its median gives
        # back a median -3.5pts over the next 3y; >50% below recovers +4.2pts). Growing the latest
        # year at revenue growth therefore bakes a transient margin into perpetuity.
        #
        # The estimator is a 50/50 SHRINK toward the causal median margin:
        #     base_cf = 0.5 x OE_latest + 0.5 x (revenue_latest x median_margin)
        # chosen by MEASURED prediction error against the realized next-3y mean margin, on the
        # production-faithful population (OE>0, median margin>0, scale-corrupt tickers excluded):
        #     >=5y history (n=4,104): blend median err 2.78pts vs latest 3.10, gated-median 3.10
        #     2-4y history (n=4,037): blend 3.43 vs latest 3.55
        # Blend beats latest-FY in BOTH populations (body and tail), needs no gate threshold, and
        # applies one formula to the whole book — the alternatives tested and rejected: normalize-
        # all (asserts unprovable mean reversion on 74% of names), a 50% gate (pure tail fix, ties
        # latest at the median), OE-CAGR growth (definable for only 54%, splits the book).
        # The MEDIAN is robust to a residual corrupt year in the history; latest-year corruption
        # is guarded separately (data_health, 0 in live use).
        margins = []
        for y in yrs:
            oe_y, rev_y = _owner_earnings(ydata[str(y)]), _num(ydata[str(y)].get("revenue"))
            if oe_y is not None and rev_y and rev_y > 0:
                margins.append(oe_y / rev_y)
        # The blend's two terms must share one period: TTM owner earnings pair with TTM
        # revenue, FY with FY. The margin MEDIAN stays annual either way — it is the causal
        # history the latest point shrinks toward, not a latest-point term.
        rev_latest = t_rev if use_ttm else _num(fy.get("revenue"))
        meta = ttm_meta if use_ttm else None
        if len(margins) >= 2 and rev_latest and rev_latest > 0:
            import statistics as _st
            med_m = _st.median(margins)
            if med_m > 0:
                return 0.5 * owner + 0.5 * (rev_latest * med_m), "blended_owner_earnings", meta
        return owner, "owner_earnings", meta
    if use_ttm:
        # A complete TTM view OWNS the latest-point verdict. Trailing owner earnings were
        # non-positive to reach here; falling back to a stale positive FY figure would
        # resurrect exactly the one-off-year pathology TTM exists to correct (ARWR: +$30M
        # milestone FY owner earnings vs −$272M trailing). Trailing FCF may still carry it;
        # otherwise return the honest null on the TTM basis.
        if t_fcf is not None and t_fcf > 0:
            return t_fcf, "fcf_fallback", ttm_meta
        return owner, "none", ttm_meta
    if ttm_meta and t_fcf is not None and t_fcf > 0:
        return t_fcf, "fcf_fallback", ttm_meta
    if fcf is not None and fcf > 0:
        return fcf, "fcf_fallback", None
    if _num(fy.get("capex")) is None and None not in (ocf, da) and (ocf - da) > 0:
        return ocf - da, "ocf_minus_da_proxy", None   # capex tag missing: steady-state proxy ~ D&A
    return (owner if owner is not None else fcf), "none", None


# Cumulative PROBABILITY OF APPROVAL by development phase — the rNPV risk discount. Compounded
# from the published BIO/Informa phase-transition rates (P1->P2 63.2%, P2->P3 30.7%, P3->filing
# 58.1%, filing->approval 85.3%): the phase-1 figure of 9.6% reproduces the widely-published
# "only ~10-12% of drugs entering Phase 1 are ever approved", which is the cross-check that this
# table is right. PHASE is the one thing the model supplies (a closed-set classification it is
# good at); the PROBABILITY is never model-chosen — that is the whole point of the table.
# preclinical is the weakest entry: ~0.55 preclinical->phase1 applied to the phase-1 LOA.
PHASE_POS = {"preclinical": 0.05, "phase1": 0.096, "phase2": 0.152,
             "phase3": 0.496, "filed": 0.853, "approved": 1.0}

# rNPV risk-discounts the WHOLE company by a trial probability, which is only valid when the
# whole company IS the trial. A biotech already SELLING an approved drug has a commercial base
# that must not be halved by a phase base rate: validated on MRNA, which the model labelled
# phase3 despite $1.94B of product revenue, turning a $51.90 value-if-approved into a $29.59 IV
# and a spurious -46.3% MoS. Above this revenue line the name keeps the Engine-4 option bridge.
# $50m rather than $10m because below ~$50m, revenue in this sector is typically collaboration
# and milestone income rather than product sales. Excludes 69 of 480 (SRPT, MRNA, NVAX, LEGN,
# IONS, ...); the other 411 are genuinely pre-commercial.
COMMERCIAL_REVENUE_FLOOR = 50e6

# A clinical-stage biotech that runs out of money before approval MUST raise equity, and that
# dilution is the honest "drag" — not a number the model should invent. Assume it must fund
# itself to the approval horizon below.
# Below this much cash, the rNPV dilution term stops being a modelling detail and becomes
# the whole question — see the going-concern flag in rnpv().
GOING_CONCERN_RUNWAY_YRS = 0.5

YEARS_TO_APPROVAL = {"preclinical": 8.0, "phase1": 6.0, "phase2": 4.0,
                     "phase3": 2.0, "filed": 1.0, "approved": 0.0}

FIN_COE = 0.10   # cost of equity for financials (the Financials sector WACC)


def _fin_verdict(gap_pts):
    if gap_pts is None:
        return "Judge ROE durability on its own."
    if gap_pts > 4:
        return f"Price implies ~{gap_pts:+.0f}pts HIGHER ROE than delivered — demands ROE expansion."
    if gap_pts >= -4:
        return "Priced roughly in line with the delivered ROE."
    return f"Priced {abs(gap_pts):.0f}pts BELOW delivered ROE — market doubts ROE durability."


def _clinical_scaffold(ydata, price, mcap, shares):
    """Deterministic rNPV scaffolding for a PRE-PROFIT clinical-stage biotech (Engine 5).

    Engine 4 took core / prob / value / drag as FOUR free model numbers. Three of them the
    balance sheet can settle: the net-cash FLOOR, and the DILUTION the company must accept to
    fund itself to approval (cash burn vs runway). The probability comes from PHASE_POS. That
    leaves the model supplying only the phase (closed set) and the value if the asset works.

    Returns None when the inputs are missing, so the caller keeps today's Engine-4 behaviour.
    """
    yrs = sorted(int(y) for y in ydata.keys())
    fy = ydata[str(yrs[-1])]
    cash, ocf = _num(fy.get("cash")), _num(fy.get("ocf"))
    sh, _fixed = _shares_sane(fy.get("shares_diluted"), shares)
    sh = sh or shares
    if not cash or not sh or sh <= 0 or ocf is None or not price or not mcap:
        return None
    burn = -ocf if ocf < 0 else 0.0            # positive $/yr; a cash-generative name has none
    net_cash = cash - (_num(fy.get("lt_debt")) or 0.0)   # most clinical names carry no LT debt
    net_cash_ps = net_cash / sh
    # Guard a stale/expired share count: a "floor" above the market price is a data artifact
    # (e.g. an unrecorded reverse split), not a free lunch. Flag it and refuse to floor on it.
    suspect = net_cash_ps > price * 2
    return {
        "net_cash_ps": round(net_cash_ps, 2),
        "net_cash_ps_suspect": suspect,
        "burn_per_yr": round(burn, 0),
        "runway_years": round(cash / burn, 2) if burn > 0 else None,
        "shares_diluted": sh,
        "fiscal_year": yrs[-1],
    }


def norm_phase(p):
    """Normalize a model-written phase to a PHASE_POS key, or None.

    The closed set is still enforced -- this only absorbs formatting. CRSP emitted "Phase 2",
    which is the right answer in the wrong shape, and a strict key match threw it away and fell
    through to the Engine-4 bridge. Handles case, spaces/hyphens/underscores, and roman numerals.
    """
    if not isinstance(p, str):
        return None
    s = re.sub(r"[\s_\-]+", "", p.strip().lower())
    for roman, arabic in (("iii", "3"), ("ii", "2"), ("i", "1")):
        if s == "phase" + roman:
            s = "phase" + arabic
            break
    return s if s in PHASE_POS else None


def rnpv(scaffold, phase, value_if_approved_ps, price):
    """Engine 5 / rNPV, assembled from the deterministic scaffold + the model's phase & upside.

        IV = net_cash_floor + P(approval | phase) x value_if_approved_ps / (1 + dilution)

    Dilution is the equity the company must issue to fund the burn through to the approval
    horizon; it scales DOWN what an existing share is worth. Returns None on bad inputs.
    """
    phase = norm_phase(phase) if phase not in PHASE_POS else phase
    if not scaffold or phase not in PHASE_POS:
        return None
    v = _num(value_if_approved_ps)
    if v is None or v < 0 or not price or price <= 0:
        return None
    burn, sh = scaffold["burn_per_yr"], scaffold["shares_diluted"]
    runway = scaffold["runway_years"]
    years = YEARS_TO_APPROVAL[phase]
    shortfall = max(0.0, (years - (runway if runway is not None else years)) * burn)
    dilution = shortfall / (price * sh) if (price * sh) > 0 else 0.0
    floor = 0.0 if scaffold["net_cash_ps_suspect"] else max(0.0, scaffold["net_cash_ps"])
    iv = floor + PHASE_POS[phase] * v / (1.0 + dilution)
    # GOING CONCERN. The dilution term assumes the company CAN raise, at roughly today's price.
    # For a name with weeks of cash that assumption is doing all the work: a failed raise is zero,
    # and a distressed one is far worse than the modelled dilution. Measured: 147 of 411 Engine-5
    # biotechs have <0.5yr runway. Surfaced on OSTX, which the engine valued at +122% MoS on 0.02
    # years of cash — about one week — while its own S3 text said "immediate capital raise
    # required". Flag rather than haircut: inventing a discount would be a fabricated number, and
    # the honest statement is that this IV is conditional on financing that may not happen.
    flag = None
    if runway is not None and runway < GOING_CONCERN_RUNWAY_YRS and years > 0:
        flag = (f"GOING CONCERN: {runway:.2f}yr of cash ({runway*12:.1f} months) against a "
                f"~{years:.0f}yr path to approval. This IV assumes the company can raise "
                f"{dilution*100:.0f}% dilution worth of equity at roughly today's price; a failed "
                f"or distressed raise is NOT modelled and would make the equity worth far less.")
    return {"method": "engine5_rnpv", "phase": phase, "pos": PHASE_POS[phase], "flag": flag,
            "value_if_approved_ps": round(v, 2), "net_cash_floor_ps": round(floor, 2),
            "dilution_pct": round(dilution * 100, 1), "years_to_approval": years,
            "runway_years": runway, "iv": round(iv, 2),
            "mos_pct": round((iv / price - 1) * 100, 1)}


def _financial_backbone(t, ydata, price, mcap, shares, coe=FIN_COE, pb_kind="financial"):
    """Banks/insurers (and rate-regulated utilities, pb_kind="regulated_utility"): a cash-flow DCF is
    structurally invalid, so value on equity returns.
    Justified P/B = (ROE - g) / (CoE - g) (Gordon, in P/B space). Invert the CURRENT P/B to the
    ROE the price implies, and compare to the delivered ROE -> an expectations gap parallel to the
    reverse-DCF one. Deterministic: no LLM-chosen multiple (the old Engine-2 was unstable, AUDIT M2).
    The raw Gordon fair value is CONSENSUS-FENCED exactly like the reverse-DCF path (band
    de-forwarded by one year of CoE; never more bullish than the PV of the analyst median;
    escapes the band -> snap to median) so a g-near-CoE artifact can't blow up the $ value."""
    yrs = sorted(int(y) for y in ydata.keys())
    fy = ydata[str(yrs[-1])]
    ni, eq = _num(fy.get("net_income")), _num(fy.get("equity"))
    if not ni or not eq or eq <= 0 or ni <= 0:
        return {"ok": False, "reason": "no_book_or_earnings", "price": price,
                "market_cap": mcap, "shares": shares}
    roe = ni / eq
    # Regulated utilities only: cap the CAPITALISED return at what a regulator plausibly allows.
    # See UTIL_ROE_CEIL — an unsustainable one-off ROE otherwise explodes the 3% denominator.
    roe_capped = bool(pb_kind == "regulated_utility" and roe > UTIL_ROE_CEIL)
    if roe_capped:
        roe = UTIL_ROE_CEIL
    rev_cagr, _ = _growth_evidence(ydata)
    g = rev_cagr if rev_cagr is not None else 0.03
    # Sustainable LONG-RUN growth for a mature financial ~ GDP. Cap hard at 4%: a recent revenue
    # spurt is not perpetual, and g near CoE makes the Gordon P/B explode (JPM 4.8x artifact).
    g = max(0.0, min(g, 0.04))
    current_pb = mcap / eq
    implied_roe = current_pb * (coe - g) + g           # invert justified_pb = (roe-g)/(coe-g)
    justified_pb = (roe - g) / (coe - g)
    bvps = (eq / shares) if shares else None
    fair_value = justified_pb * bvps if (bvps and justified_pb > 0) else None
    gap_pts = (implied_roe - roe) * 100

    # Consensus fence (same discipline + field names as the reverse-DCF path).
    band = _consensus_band(t)
    fv_method = "pb_roe_noband" if fair_value is not None else "blank"
    if band:
        disc = 1.0 + coe
        lo, med, hi = band["low"] / disc, band["median"] / disc, band["high"] / disc
        if fair_value is not None and lo <= fair_value <= hi:
            fair_value = min(fair_value, med)          # never more bullish than the PV'd median
            fv_method = "pb_roe_in_band"
        else:
            fair_value, fv_method = med, "pb_roe_consensus_snap"
    mos = round((fair_value / price - 1) * 100, 1) if (fair_value and price) else None
    # An UNFENCED extreme MoS is the P/B model computing a defensible number for a reason it
    # cannot see. EIX prints +157% because a 15% ROE justifies 3.67x book while it trades at
    # 1.43x -- the market is pricing wildfire liability, and a return-on-book model has no
    # channel for contingent claims. 51 of 56 utilities have NO analyst band, so the consensus
    # fence that normally bounds this path is absent for almost all of them. Flag rather than
    # clip: clipping would fabricate a number, this tells the reader the model is out of its
    # depth and lets conviction/sizing dock it.
    flag = None
    if fv_method == "pb_roe_noband" and mos is not None and abs(mos) > 60:
        flag = (f"UNFENCED P/B valuation with an extreme {mos:+.0f}% MoS and no analyst band to "
                f"bound it — likely something this model cannot see (contingent liabilities, "
                f"asset-sale ROE, depressed book). Treat the $ value as low confidence.")
    return {
        "flag": flag,
        "ok": True, "ticker": t, "method": "financial_pb_roe", "pb_kind": pb_kind,
        "price": price, "market_cap": mcap, "shares": shares, "fiscal_year": yrs[-1],
        "roe": round(roe, 4), "implied_roe": round(implied_roe, 4), "coe": coe,
        # surfaced so a capped name is auditable rather than silently smoothed
        "roe_capped": roe_capped, "roe_reported": round(ni / eq, 4),
        "sustainable_g": round(g, 4), "current_pb": round(current_pb, 2),
        "justified_pb": round(justified_pb, 2), "book_value_ps": round(bvps, 2) if bvps else None,
        "fair_value": round(fair_value, 2) if fair_value else None,
        "mos_pct": mos, "realistic_mos_pct": mos, "fair_value_method": fv_method,
        "consensus_low": band["low"] if band else None,
        "consensus_median": band["median"] if band else None,
        "consensus_high": band["high"] if band else None,
        "consensus_stale": band["stale"] if band else None,
        "consensus_age_days": band["age_days"] if band else None,
        "expectations_gap_pts": round(gap_pts, 1), "verdict": _fin_verdict(gap_pts),
    }


# ── Cross-sectional MoS calibration ────────────────────────────────────────────────────────
# "Cheap" only means anything RELATIVE TO THE BOOK. The old rules used an absolute cut (MoS < 15%
# -> ENTRY DISCIPLINE + conviction DOCK), which fired on 80% of names -- not because 80% of the
# book was expensive, but because the absolute threshold sat above wherever the distribution
# happened to live. And where it lives is set by the sector WACC, which is a JUDGEMENT: measured,
# a 2pt lower WACC moves the median MoS from -38.9% to -13.5%, and 3pts moves it to +6.3%. An
# absolute threshold on a distribution whose level is an assumption is not a valuation rule.
# Percentile cuts are invariant to that choice, which is the point.
MOS_DIST_CACHE = HERE / "cache" / "mos_distribution.json"
MOS_DIST_MAX_AGE_DAYS = 3
MOS_CHEAP_PCTL = 33          # bottom third by MoS = the expensive end -> do-not-chase


def mos_cut(pctl=MOS_CHEAP_PCTL):
    """MoS value at the given percentile of the analysed book, or None if not calibrated.

    None is a MEANINGFUL answer, not an error: callers must fall back to stating the raw number
    without a cheap/expensive judgement rather than silently reverting to an absolute cut that
    this whole change exists to remove.
    """
    d = rs2_data.load_json(MOS_DIST_CACHE) or {}
    ts = _iso_age_days(d.get("built_at"))
    if ts is None or ts > MOS_DIST_MAX_AGE_DAYS:
        return None
    return (d.get("percentiles") or {}).get(str(pctl))


def build_mos_distribution(tickers):
    """Recompute the cross-sectional MoS percentiles and cache them. Returns the dict written."""
    vals = []
    for t in tickers:
        try:
            b = backbone(t)
        except Exception:
            continue
        m = b.get("realistic_mos_pct")
        if isinstance(m, (int, float)):
            vals.append(float(m))
    if len(vals) < 30:                      # too thin to calibrate a percentile on
        return None
    vals.sort()
    from datetime import datetime, timezone
    out = {"built_at": datetime.now(timezone.utc).isoformat(), "n": len(vals),
           "percentiles": {str(p): round(vals[min(len(vals) - 1, int(len(vals) * p / 100))], 1)
                           for p in (10, 25, 33, 50, 67, 75, 90)}}
    MOS_DIST_CACHE.parent.mkdir(parents=True, exist_ok=True)
    MOS_DIST_CACHE.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def backbone(ticker, force_midcycle=False, force_latest=False):
    t = ticker.upper()
    fin = rs2_data.load_json(SD / "financials" / f"{t}.json") or {}
    price = _num(fin.get("Price"))
    mcap = _num(fin.get("Market_Cap"))
    shares = _num(fin.get("Shares_Outstanding"))
    ydata = _hist(t)
    if not ydata:
        return {"ok": False, "reason": "no_fundamentals_history"}
    if not mcap or mcap <= 0:
        return {"ok": False, "reason": "no_market_cap"}

    sector, _ind = rs2_data.sector_lookup(t)
    sl = (sector or "").lower()
    wacc_pct = SECTOR_WACC.get(SECTOR_ALIASES.get(sector, sector), DEFAULT_WACC)
    wacc = wacc_pct / 100.0

    # Balance-sheet financials (banks / insurance underwriters / mortgage) -> P/B-ROE model,
    # ALWAYS — their owner earnings are usually positive but economically meaningless, so the
    # old base_cf<=0 trigger never fired for them. See PB_ROE_INDUSTRIES note above.
    ind_l = (_ind or "").lower()
    if any(k in ind_l for k in PB_ROE_INDUSTRIES) and not any(k in ind_l for k in PB_ROE_EXCLUDE):
        return _financial_backbone(t, ydata, price, mcap, shares)

    # Rate-regulated utilities: same justified-P/B model, utility cost of equity. See the
    # REGULATED_UTILITY_INDUSTRIES note above for why an owner-earnings DCF cannot work here.
    if "utilities" in sl and any(k in ind_l for k in REGULATED_UTILITY_INDUSTRIES):
        return _financial_backbone(t, ydata, price, mcap, shares,
                                   coe=UTIL_COE, pb_kind="regulated_utility")

    # SEC-derived TTM legs, gated: the TTM must be anchored on the SAME latest fiscal year the
    # annual history holds (both builders label FY by end-year), or the two files are out of
    # step and the trailing window cannot be trusted against this history.
    ttm = _ttm_record(t)
    if ttm and int(str(ttm.get("fy_leg_end", ""))[:4] or 0) != max(int(y) for y in ydata.keys()):
        ttm = None
    base_cf, kind, period_meta = _base_cf(t, ydata, sl, ind_l, force_midcycle=force_midcycle,
                                          force_latest=force_latest, ttm=ttm)
    if (base_cf is None or base_cf <= 0) and not (period_meta or {}).get("period") == "ttm":
        # SEC fundamentals_history lacks capex/D&A for many foreign filers (SAP/VIK/BWMX/JLHL) or is
        # stale — a data gap, not a genuinely unvaluable company. Fall back to the fresh yfinance
        # trailing FCF we already have (financials.json) before giving up. NEVER when a complete
        # SEC TTM already ruled the trailing period non-positive: Free_Cash_Flow_TTM mirrors the
        # FY figure for ~75% of names (measured 2026-08-07), so it would resurrect the stale
        # positive year the SEC TTM just refuted.
        fcf_ttm = _num(fin.get("Free_Cash_Flow_TTM"))
        if fcf_ttm and fcf_ttm > 0:
            base_cf, kind = fcf_ttm, "fcf_ttm_yf"
    if base_cf is None or base_cf <= 0:
        # Banks/insurers fail owner-earnings DCF by construction -> value on ROE vs P/B instead.
        # (Payment networks like V/MA have positive owner earnings and stay on the reverse-DCF above.)
        if any(k in sl for k in ("financial", "bank", "insurance")):
            return _financial_backbone(t, ydata, price, mcap, shares)
        # A PROFITABLE company that out-spends its D&A is REINVESTING, not pre-profit. Conflating
        # the two sent capex-heavy names down the Engine-4 "negative earnings / option-led" path and
        # told the model they had no earning power. Split the reason so only genuine NI<=0 names
        # can be described as PRE-PROFIT (see valuation_block in rs2_data.py). When an
        # authoritative TTM ruled the base non-positive, the SPLIT must read the same trailing
        # legs — classifying ARWR as "reinvesting" off its stale milestone-year FY NI would send
        # a name whose trailing twelve months LOST money down the normalized-earning-power path.
        fy_last = ydata[str(max(int(y) for y in ydata.keys()))]
        if (period_meta or {}).get("period") == "ttm":
            _tfields = (ttm or {}).get("fields") or {}
            ni_l, da_l, capex_l = (_num(_tfields.get("net_income")), _num(_tfields.get("da")),
                                   _num(_tfields.get("capex")))
        else:
            ni_l, da_l, capex_l = (_num(fy_last.get("net_income")), _num(fy_last.get("da")),
                                   _num(fy_last.get("capex")))
        reinvesting = bool(ni_l and ni_l > 0 and da_l is not None and capex_l is not None
                           and capex_l > da_l)
        out = {"ok": False,
               "reason": "reinvestment_negative_fcf" if reinvesting else "negative_base_cash_flow",
               "base_cf_kind": kind, "price": price, "market_cap": mcap, "shares": shares,
               "base_period": (period_meta or {}).get("period", "fy"),
               "base_through": (period_meta or {}).get("through")}
        # Pre-profit biotech -> attach the deterministic rNPV scaffolding (Engine 5). Only for
        # genuinely pre-profit names: a reinvesting company has earning power to capitalise.
        # Same TTM-consistency rule as the reason split above (trailing revenue, not a stale FY).
        if (period_meta or {}).get("period") == "ttm":
            rev_l = _num(((ttm or {}).get("fields") or {}).get("revenue")) or 0.0
        else:
            rev_l = _num(fy_last.get("revenue")) or 0.0
        if not reinvesting and "biotech" in ind_l and rev_l < COMMERCIAL_REVENUE_FLOOR:
            sc = _clinical_scaffold(ydata, price, mcap, shares)
            if sc:
                out["rnpv_scaffold"] = sc
        return out

    implied = _solve_implied_growth(base_cf, mcap, wacc)
    if implied is None:
        return {"ok": False, "reason": "solver_failed", "price": price, "market_cap": mcap}

    rev_cagr, fcf_cagr = _growth_evidence(ydata)
    # For a REIT the implied growth is in FFO terms, so the demonstrated side must be too --
    # comparing implied FFO growth against a revenue CAGR inflated by equity-funded acquisitions
    # is apples-to-oranges and was overstating the gap. Falls back to revenue when FFO/share
    # history is too short.
    demo_cagr, demo_kind = rev_cagr, "revenue_cagr_5y"
    if kind == "ffo_reit":
        f = _ffo_ps_cagr(ydata, shares)
        if f is not None:
            demo_cagr, demo_kind = f, "ffo_ps_cagr"
    gap_pts = (implied - demo_cagr) * 100 if demo_cagr is not None else None
    yrs = sorted(int(y) for y in ydata.keys())

    # DETERMINISTIC fair value — FORWARD-anchored & CONSENSUS-FENCED (replaces the old trailing-5y-CAGR
    # extrapolation, which blew up 2-12x for post-IPO / hyper-ramp names, e.g. HRMY +1143% MoS).
    # Growth input: forward analyst growth (fresh) -> else trailing CAGR, capped at FWD_GROWTH_CEIL.
    # Then FENCE the resulting value inside the analyst target band [low, high]; if it escapes the
    # band, snap to the consensus median (the raw DCF is malfunctioning, not leaning). With NO band
    # AND implausible/short trailing history -> BLANK the $ value (keep only the gap signal). The
    # EXPECTATIONS GAP above remains the headline signal; this is a fenced sanity price, never an LLM number.
    n_years = len(yrs)
    g_fwd, g_src = _forward_growth(t)
    band = _consensus_band(t)
    g_drive = g_fwd if g_fwd is not None else rev_cagr
    src = g_src if g_fwd is not None else ("trailing" if rev_cagr is not None else None)
    fair_value = mos_pct = fv_sensitivity_pts = None
    fv_method = "blank"
    if g_drive is not None and price:
        g_fair = max(-0.20, min(g_drive, FWD_GROWTH_CEIL))
        fair_mcap = ve.dcf_value(base_cf, g_fair, wacc, TERMINAL_G, stage1_years=STAGE1, fade_years=FADE)
        if fair_mcap and fair_mcap > 0:
            raw = price * fair_mcap / mcap
            # STABILITY SELF-TEST: how far does the answer move on +/-1pt of growth input?
            def _fv(gg):
                fm = ve.dcf_value(base_cf, max(-0.20, min(gg, FWD_GROWTH_CEIL)), wacc,
                                  TERMINAL_G, stage1_years=STAGE1, fade_years=FADE)
                return (price * fm / mcap) if (fm and fm > 0) else None
            _up, _dn = _fv(g_drive + 0.01), _fv(g_drive - 0.01)
            sens = (abs(_up - _dn) / price * 100.0) if (_up and _dn and price) else None
            unstable = ((sens is not None and sens > MOS_SENSITIVITY_MAX)
                        or abs(raw / price - 1.0) > MOS_EXTREME_MAX)
            fv_sensitivity_pts = round(sens, 1) if sens is not None else None
            if not unstable:
                # STABLE -> publish OUR value. This is the number the engine actually computed.
                fair_value = round(raw, 2)
                fv_method = "forward_dcf" if src != "trailing" else "trailing_dcf"
            elif band:
                # De-forward the analyst band to PRESENT value: consensus targets are 12-month PRICE
                # TARGETS (~13% above spot = one year of expected return), while our reverse-DCF `raw`
                # is already a present intrinsic value. Discount the target by one year of the sector
                # discount rate (CoE proxy) so the fence is a like-for-like present value and MoS
                # measures cheapness TODAY, not cheapness + a year of ordinary equity drift.
                disc = 1.0 + wacc
                lo, hi, med = band["low"] / disc, band["high"] / disc, band["median"] / disc
                if lo <= raw <= hi:
                    # Discipline: never MORE bullish than the (present-valued) analyst median.
                    fair_value = round(max(lo, min(raw, med)), 2)
                    fv_method = "forward_dcf" if src != "trailing" else "trailing_in_band"
                else:
                    fair_value, fv_method = round(med, 2), "consensus_snap"   # raw escaped band -> malfunction
            else:
                implausible = (rev_cagr is not None and rev_cagr > 0.25) or n_years < 5
                if g_fwd is not None and not implausible:
                    fair_value, fv_method = round(raw, 2), "forward_dcf_noband"
                # else: no forward anchor + wild/short trailing -> leave blank (gap-only)
    elif band is not None:                                   # no growth input but analysts cover it
        fair_value, fv_method = round(band["median"] / (1.0 + wacc), 2), "consensus_only"  # PV of 12-mo target
    if fair_value and price:
        mos_pct = round((fair_value / price - 1) * 100, 1)

    # A margin-median (blend) or multi-year average (midcycle) built across a persistent revenue
    # level shift spans two business perimeters — surfaced for the analyst layer, never acted on
    # automatically (see _revenue_break for why an auto-trim is rejected by measurement).
    rev_break = (_revenue_break(ydata)
                 if (kind == "blended_owner_earnings" or str(kind).startswith("midcycle")) else None)

    # DELIVERED growth: median YoY revenue across the last 4 reported quarters — the regime
    # evidence, from filings. Not a forecast and not news-dependent (a fresh AMD brief carried
    # none of its +50% record quarter, 2026-08); it is what the company actually did.
    delivered = None
    _qs = ((_quarterly_record(t) or {}).get("quarters") or [])[-4:]
    _yy = [q["yoy_revenue"] for q in _qs if q.get("yoy_revenue") is not None]
    if _yy:
        import statistics as _st2
        delivered = round(_st2.median(_yy) / 100.0, 4)
    lattice = base_lattice(ydata, ttm, mcap, wacc, price, shares, demo_cagr, g_fwd, delivered)

    return {
        "ok": True, "ticker": t, "method": "reverse_dcf",
        "price": price, "market_cap": mcap, "shares": shares,
        "base_cf": base_cf, "base_cf_kind": kind, "fiscal_year": yrs[-1],
        "base_period": (period_meta or {}).get("period", "fy"),
        "base_through": (period_meta or {}).get("through"),
        "revenue_break": rev_break,
        "delivered_growth": delivered,
        "lattice": lattice,
        "contested": bool((lattice or {}).get("contested")),
        "wacc": wacc, "wacc_pct": wacc_pct, "terminal_growth": TERMINAL_G,
        "stage1_years": STAGE1, "fade_years": FADE,
        "implied_growth": round(implied, 4), "implied_growth_clamped": implied in (G_LO, G_HI),
        "hist_revenue_cagr_5y": round(rev_cagr, 4) if rev_cagr is not None else None,
        # what the gap is actually measured against (FFO/share for REITs, revenue otherwise)
        "demonstrated_cagr": round(demo_cagr, 4) if demo_cagr is not None else None,
        "demonstrated_cagr_kind": demo_kind,
        "hist_fcf_cagr_5y": round(fcf_cagr, 4) if fcf_cagr is not None else None,
        "expectations_gap_pts": round(gap_pts, 1) if gap_pts is not None else None,
        "fair_value": fair_value, "mos_pct": mos_pct, "realistic_mos_pct": mos_pct,
        # how many pts of MoS move per +/-1pt of growth input — the stability fence input
        "fv_sensitivity_pts": fv_sensitivity_pts,
        "fair_value_method": fv_method, "forward_growth": round(g_fwd, 4) if g_fwd is not None else None,
        "forward_growth_src": g_src,
        "consensus_low": band["low"] if band else None,
        "consensus_median": band["median"] if band else None,
        "consensus_high": band["high"] if band else None,
        "consensus_stale": band["stale"] if band else None,
        "consensus_age_days": band["age_days"] if band else None,
        "verdict": _verdict(gap_pts),
    }


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--build-mos-dist" in sys.argv:
        # Recalibrate the cross-sectional MoS percentiles. MUST be run periodically (the cache
        # expires after MOS_DIST_MAX_AGE_DAYS) or mos_cut() returns None and the ENTRY DISCIPLINE
        # line degrades to "no ranking available" — loud by design, never a silent absolute cut.
        rep = Path(CONFIG["out_reports_dir"])
        universe = sorted({d.name.rsplit("_", 2)[0] for d in rep.glob("*_*") if d.is_dir()})
        out = build_mos_distribution(universe)
        if not out:
            print("mos distribution: too few valued names to calibrate (need >=30)")
            sys.exit(1)
        print(f"mos distribution rebuilt from {out['n']} names -> {MOS_DIST_CACHE}")
        for k, v in out["percentiles"].items():
            print(f"   p{k:>2s}  {v:+7.1f}%")
        sys.exit(0)

    for tk in (sys.argv[1:] or ["NVDA"]):
        b = backbone(tk)
        if b.get("method") == "financial_pb_roe":
            print(f"{tk}: FINANCIAL | ROE {b['roe']*100:.1f}% vs implied {b['implied_roe']*100:.1f}% | "
                  f"P/B {b['current_pb']}x vs justified {b['justified_pb']}x | fair ${b['fair_value']} | "
                  f"gap {b['expectations_gap_pts']}pts | {b['verdict']}")
        elif b.get("ok"):
            print(f"{tk}: base_cf ${b['base_cf']/1e9:.2f}B [{b['base_cf_kind']}] FY{b['fiscal_year']} | "
                  f"WACC {b['wacc_pct']}% | implied {b['implied_growth']*100:.1f}% vs demonstrated "
                  f"{(b['hist_revenue_cagr_5y'] or 0)*100:.1f}% | gap {b['expectations_gap_pts']}pts | {b['verdict']}")
        else:
            print(f"{tk}: NULL ({b['reason']}) — pre-profit, route to Engine 4")
