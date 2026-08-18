"""C8 — Peer-multiple cross-check feasibility: EV/EBIT vs sector median.

Builds sector EV/EBIT medians from the full screener corpus (financials/*.json
Calculated_Metrics.EV_to_EBIT + stocks.csv sectors), then for each live-book reverse-DCF
name compares its own EV/EBIT to its sector median and asks whether the relative-multiple
signal agrees with the expectations-gap signal:
  multiple_cheap  : EV/EBIT < 0.8 x sector median
  multiple_rich   : EV/EBIT > 1.25 x sector median
  gap_rich        : expectations_gap_pts >= +15 (STANCE_OVERVALUED_GAP)
  gap_cheap       : expectations_gap_pts <= -7  (STANCE_UNDERVALUED_GAP)
Disagreement rate = names where the two signals point in opposite directions - the
population where a comps cross-check would actually have tripped a review.
"""
import csv
import json
from pathlib import Path

import common

common.enable_json_cache()
import rs2_data  # noqa: E402
import valuation_backbone as vb  # noqa: E402


def main():
    sectors = {}
    with open(common.SD / "stocks.csv", "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        sy = next((c for c in r.fieldnames if c.lower() == "symbol"), None)
        sc = next((c for c in r.fieldnames if c.lower() == "sector"), None)
        for row in r:
            if row.get(sy) and row.get(sc):
                sectors[row[sy].upper()] = row[sc]

    by_sector = {}
    n_files = n_used = 0
    for p in (common.SD / "financials").glob("*.json"):
        n_files += 1
        t = p.stem.upper()
        sec = sectors.get(t)
        if not sec:
            continue
        try:
            fin = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        ev_ebit = ((fin.get("Calculated_Metrics") or {}).get("EV_to_EBIT"))
        if isinstance(ev_ebit, (int, float)) and 0 < ev_ebit < 200:
            by_sector.setdefault(sec, []).append(float(ev_ebit))
            n_used += 1
    med = {}
    for sec, vals in by_sector.items():
        vals.sort()
        if len(vals) >= 20:
            med[sec] = round(vals[len(vals) // 2], 2)

    rows, agree, disagree, no_signal = {}, [], [], []
    for t in common.book_tickers():
        try:
            b = vb.backbone(t)
        except Exception:
            continue
        if not b.get("ok") or b.get("method") != "reverse_dcf":
            continue
        sec = sectors.get(t)
        fin = rs2_data.load_json(common.SD / "financials" / f"{t}.json") or {}
        ev_ebit = (fin.get("Calculated_Metrics") or {}).get("EV_to_EBIT")
        gap = b.get("expectations_gap_pts")
        if sec not in med or not isinstance(ev_ebit, (int, float)) or ev_ebit <= 0 or gap is None:
            no_signal.append(t)
            continue
        rel = ev_ebit / med[sec]
        m_sig = "cheap" if rel < 0.8 else ("rich" if rel > 1.25 else "inline")
        g_sig = "rich" if gap >= 15 else ("cheap" if gap <= -7 else "inline")
        rows[t] = {"sector": sec, "ev_ebit": round(ev_ebit, 1), "sector_median": med[sec],
                   "rel": round(rel, 2), "multiple_signal": m_sig,
                   "gap_pts": gap, "gap_signal": g_sig}
        if {m_sig, g_sig} == {"cheap", "rich"}:
            disagree.append(t)
        elif m_sig == g_sig and m_sig != "inline":
            agree.append(t)

    common.save("c8_peer_multiples", {
        "corpus_files": n_files, "corpus_with_usable_ev_ebit": n_used,
        "sectors_with_median": med,
        "n_book_compared": len(rows), "n_no_signal": len(no_signal),
        "n_agree": len(agree), "agree": sorted(agree),
        "n_disagree": len(disagree), "disagree": sorted(disagree),
        "disagree_detail": {t: rows[t] for t in sorted(disagree)},
        "per_ticker": rows,
    })


if __name__ == "__main__":
    main()
