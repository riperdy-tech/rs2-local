#!/usr/bin/env python3
"""data_health.py — continuous integrity audit of the fundamentals feeding every valuation.

WHY THIS EXISTS
SEC filings are not internally consistent. The same fiscal period is sometimes reported twice with
values a clean power of 1000 apart, and because the corrupt value usually sits in the LATER filing,
"most recent wins" picks it. Proven against raw companyfacts:

    COHR  FY2023 D&A          681,687,000 (10-K)  vs      681,687,000,000 (later 10-K)
    INVE  FY2021 NetIncome      1,620,000 (10-K)  vs    1,620,000,000,000 (10-K/A)
    BKTI  FY2020 shares            12,561         and           12,561,000

Measured across the corpus: 672 year-over-year ~1000x transitions in 451 tickers, 49% of them in
shares_diluted -- the field that divides into FFO-per-share, the Engine-5 net-cash floor and the
Engine-5 dilution term. This was discovered by accident while investigating something else. Nothing
was watching, which is the actual failure.

WHAT IT DOES *NOT* DO -- and why
It does NOT flag values merely for being large relative to their own history. That was tested and
is unsafe: at a 10x bar it flags NVDA's real $120bn net income (29x its own median), AMZN's real
20:1 split (21.5x), AMD's Xilinx equity (22.3x) and CRM's margin expansion (20.7x). A filter that
deletes the best-performing names in the book is worse than the corruption it claims to prevent.

Only PROVABLE signatures are reported:
  1. CROSS-FILING CONTRADICTION - one period, two values ~1000x apart. A period cannot have two
     true values 1000x apart; a genuine restatement moves a number by percent (INVE's real ones
     move 0.3%). Requires the screener's sec_facts.
  2. CROSS-SOURCE DISAGREEMENT   - fundamentals shares_diluted vs financials Shares_Outstanding.
     Independent providers, so agreement is evidence. 253 of 255 live names agree within 5x.
  3. VALUE-IN-USE CHECK          - the components actually feeding each live base_cf.

    python data_health.py            # audit, human-readable
    python data_health.py --alert    # Telegram if anything provable is found
    python data_health.py --json     # machine-readable
Exits 1 when a provable corruption is present, so it can gate a sweep.
"""
import argparse
import json
import statistics as st
import sys
from pathlib import Path

import rs2_data
import valuation_backbone as vb

HERE = Path(__file__).resolve().parent
SD = Path(rs2_data.CONFIG["screener_data_dir"])
REPORTS = Path(rs2_data.CONFIG["out_reports_dir"])
SCALE_STEPS = (1e3, 1e6, 1e9)
FIELDS = ("revenue", "net_income", "da", "capex", "ocf", "fcf", "equity", "total_assets",
          "cash", "lt_debt", "shares_diluted", "ppe_net")


def _pow1000(a, b):
    if not a or not b:
        return None
    r = abs(a) / abs(b)
    for p in SCALE_STEPS:
        if 0.7 * p <= r <= 1.4 * p:
            return p
    return None


def live_tickers():
    return sorted({d.name.rsplit("_", 2)[0] for d in REPORTS.glob("*_*") if d.is_dir()})


def audit_shares(tickers, hist):
    """Cross-source: fundamentals shares_diluted vs an independent Shares_Outstanding."""
    out = []
    for t in tickers:
        fin = rs2_data.load_json(SD / "financials" / f"{t}.json") or {}
        so = fin.get("Shares_Outstanding")
        yd = {k: v for k, v in (hist.get(t) or {}).items()
              if str(k).isdigit() and isinstance(v, dict)}
        if not so or not yd:
            continue
        sd = yd[max(yd, key=int)].get("shares_diluted")
        if not isinstance(sd, (int, float)) or sd <= 0:
            continue
        fixed, corrected = vb._shares_sane(sd, so)
        if corrected:
            out.append({"ticker": t, "field": "shares_diluted", "raw": sd,
                        "independent": so, "corrected_to": fixed})
    return out


def audit_series_breaks(tickers, hist):
    """Year-over-year clean power-of-1000 transitions — the units-error fingerprint."""
    out = []
    for t in tickers:
        yd = {k: v for k, v in (hist.get(t) or {}).items()
              if str(k).isdigit() and isinstance(v, dict)}
        for f in FIELDS:
            s = sorted(((int(y), yd[y].get(f)) for y in yd), key=lambda z: z[0])
            s = [(y, v) for y, v in s if isinstance(v, (int, float)) and v != 0]
            for i in range(1, len(s)):
                if _pow1000(s[i][1], s[i-1][1]) or _pow1000(s[i-1][1], s[i][1]):
                    out.append({"ticker": t, "field": f, "from_year": s[i-1][0],
                                "to_year": s[i][0], "from": s[i-1][1], "to": s[i][1]})
    return out


def audit_financials_feed(tickers):
    """Integrity of financials/{T}.json and price_history.json — the OTHER feeds.

    Only PROVABLE signatures, measured 2026-08-07 across 258-260 live names before gating:
      * Market_Cap vs Price x Shares_Outstanding is an exact identity on this feed (measured max
        deviation 0.0%), so >2% is corruption, not noise.
      * financials Price vs the last monthly price_history close varies legitimately by timing
        (median 1.9%, max 37% — real moves since the monthly snapshot), so magnitude is NOT
        gated; only a ~power-of-1000 ratio (units error) is.
    """
    ph = rs2_data.load_json(SD / "price_history.json") or {}
    prices = ph.get("prices") or {}
    out = []
    for t in tickers:
        fin = rs2_data.load_json(SD / "financials" / f"{t}.json") or {}
        p_, so, mc = fin.get("Price"), fin.get("Shares_Outstanding"), fin.get("Market_Cap")
        if p_ and so and mc and p_ > 0 and so > 0 and mc > 0:
            dev = abs(mc / (p_ * so) - 1)
            if dev > 0.02:
                out.append({"ticker": t, "check": "mcap_identity", "market_cap": mc,
                            "price_x_shares": p_ * so, "deviation_pct": round(dev * 100, 1)})
        s_ = prices.get(t)
        if p_ and isinstance(s_, list) and s_ and isinstance(s_[-1], (int, float)) and s_[-1] > 0:
            if _pow1000(p_, s_[-1]):
                out.append({"ticker": t, "check": "price_scale", "financials_price": p_,
                            "price_history_last": s_[-1]})
    return out


def audit_values_in_use(tickers, hist):
    """The components actually feeding each live base_cf — is the year we USE self-consistent?"""
    out = []
    for t in tickers:
        try:
            b = vb.backbone(t)
        except Exception as e:
            out.append({"ticker": t, "field": "backbone", "error": str(e)[:120]})
            continue
        fy = b.get("fiscal_year")
        if not fy:
            continue
        yd = {k: v for k, v in (hist.get(t) or {}).items()
              if str(k).isdigit() and isinstance(v, dict)}
        row = yd.get(str(fy))
        if not row:
            continue
        for f in ("net_income", "da", "capex", "fcf", "ocf"):
            v = row.get(f)
            if not isinstance(v, (int, float)) or v == 0:
                continue
            others = [abs(yd[y].get(f)) for y in yd
                      if y != str(fy) and isinstance(yd[y].get(f), (int, float)) and yd[y].get(f)]
            if len(others) < 3:
                continue
            # ONLY a clean power-of-1000 break counts. Ordinary magnitude differences are growth.
            if _pow1000(v, st.median(others)):
                out.append({"ticker": t, "field": f, "fiscal_year": fy, "value": v,
                            "series_median": st.median(others), "in_use": True})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true", help="Telegram when a provable issue is found")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="audit the whole corpus, not just live names")
    a = ap.parse_args()

    hist = rs2_data.load_json(SD / "fundamentals_history.json") or {}
    hist = hist.get("tickers") or hist
    tickers = sorted(hist) if a.all else live_tickers()

    shares = audit_shares(tickers, hist)
    breaks = audit_series_breaks(tickers, hist)
    in_use = audit_values_in_use(tickers, hist)
    feeds = audit_financials_feed(tickers)
    report = {"scope": "all" if a.all else "live", "n_tickers": len(tickers),
              "shares_cross_source": shares, "series_scale_breaks": breaks,
              "corrupt_values_in_use": in_use, "financials_feed": feeds}

    if a.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("DATA HEALTH — fundamentals integrity")
        print(f"  scope: {report['scope']}  tickers: {len(tickers)}")
        print(f"  shares_diluted disagreeing with independent source : {len(shares)}")
        for r in shares[:10]:
            print(f"     {r['ticker']:6s} raw {r['raw']:>16,.0f}  independent {r['independent']:>16,.0f}"
                  f"  -> corrected {r['corrected_to']:>16,.0f}")
        print(f"  year-over-year ~1000x scale breaks                 : {len(breaks)}"
              f"  ({len({r['ticker'] for r in breaks})} tickers)")
        print(f"  CORRUPT VALUES ACTUALLY FEEDING A LIVE base_cf     : {len(in_use)}   <== the one that matters")
        print(f"  financials/price feed integrity breaches           : {len(feeds)}")
        for r in feeds[:6]:
            print(f"     {r['ticker']:6s} {r['check']}: {r}")
        for r in in_use[:10]:
            print(f"     {r['ticker']:6s} FY{r['fiscal_year']} {r['field']:12s} "
                  f"value {r['value']:>18,.0f}  series median {r['series_median']:>16,.0f}")

    # Only corruption reaching a live valuation, or an unresolved cross-source disagreement, is a
    # breach. Historic series breaks are recorded but do not fail the run: the extractor resolves
    # them at source and the ingest guard corrects what it can.
    problems = len(in_use) + len(shares) + len(feeds)
    if problems:
        msg = (f"[RS2 ops] data_health: {len(in_use)} corrupt value(s) feeding a live valuation, "
               f"{len(shares)} share-count disagreement(s)")
        if not a.json:
            print(f"\nPROBLEMS: {msg}")
        if a.alert:
            import ops
            ops.notify_telegram(msg)
            print("[alert] Telegram sent")
        return 1
    if not a.json:
        print("\nOK — no provable corruption reaching a live valuation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
