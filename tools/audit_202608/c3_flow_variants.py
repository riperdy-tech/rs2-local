"""C3 — base_cf variants: SBC-deducted and delta-working-capital-adjusted.

For every reverse-DCF name in the live book:
  variant A (SBC):  base_cf_adj = base_cf - SBC_TTM (yfinance SBC_Stock_Based_Comp).
  variant B (dWC):  base_cf_adj = base_cf - dWC, where dWC = change in non-cash working
                    capital ((current_assets - cash) - current_liabilities) across the two
                    most recent fiscal years with complete fields.

Effects measured on the two published signals:
  - implied growth / expectations gap (re-solved via vb._solve_implied_growth)
  - raw DCF fair value (linear in base_cf, so ratio = base_cf_adj / base_cf) -> MoS shift
  - Spearman of adjusted vs baseline gap ranks; brake-tier flips on the variant's own cuts.

DATA LIMIT (STOP flag for the report): fundamentals_history has NO per-year SBC field, so a
retrodictive validation of the SBC variant (like the n=4,104 blend study) is NOT possible
with current data; this experiment measures cross-sectional impact only.
"""
import common

common.enable_json_cache()
import rs2_data  # noqa: E402
import valuation_backbone as vb  # noqa: E402


def dwc(t):
    """Change in non-cash WC across the last two complete fiscal years, or None."""
    h = vb._hist(t)
    if not h:
        return None
    yrs = sorted(int(y) for y in h.keys())
    if len(yrs) < 2:
        return None

    def wc(y):
        fy = h[str(y)]
        ca, cash, cl = (vb._num(fy.get("current_assets")), vb._num(fy.get("cash")),
                        vb._num(fy.get("current_liabilities")))
        if None in (ca, cash, cl):
            return None
        return (ca - cash) - cl

    w1, w0 = wc(yrs[-1]), wc(yrs[-2])
    if w1 is None or w0 is None:
        return None
    return w1 - w0


def tier(m, p33, p75):
    if m is None or p33 is None:
        return "uncovered"
    return "chase_ok" if m >= p75 else ("stage" if m >= p33 else "no_chase")


def main():
    book = common.book_tickers()
    base = {}
    for t in book:
        try:
            b = vb.backbone(t)
        except Exception:
            continue
        if b.get("ok") and b.get("method") == "reverse_dcf":
            base[t] = b

    out = {"n_reverse_dcf": len(base), "variants": {}}
    for vname in ("sbc", "dwc"):
        rows, missing, nonpos = {}, [], []
        for t, b in base.items():
            cf = b["base_cf"]
            if vname == "sbc":
                fin = rs2_data.load_json(common.SD / "financials" / f"{t}.json") or {}
                adj = vb._num(fin.get("SBC_Stock_Based_Comp"))
                if adj is None:
                    missing.append(t)
                    continue
                cf_adj = cf - abs(adj)   # SBC reported sign varies by source; treat as a cost
            else:
                d = dwc(t)
                if d is None:
                    missing.append(t)
                    continue
                cf_adj = cf - d
            if cf_adj <= 0:
                nonpos.append(t)
                continue
            implied = vb._solve_implied_growth(cf_adj, b["market_cap"], b["wacc"])
            demo = b.get("demonstrated_cagr")
            gap = (implied - demo) * 100 if (implied is not None and demo is not None) else None
            ratio = cf_adj / cf
            mos = b.get("mos_pct")
            mos_adj = (round(((mos / 100 + 1) * ratio - 1) * 100, 1)
                       if isinstance(mos, (int, float)) else None)
            rows[t] = {
                "cf_ratio": round(ratio, 3),
                "gap_base": b.get("expectations_gap_pts"),
                "gap_adj": round(gap, 1) if gap is not None else None,
                "mos_base": mos, "mos_adj": mos_adj,
            }
        # ranking effect on the gap signal and on MoS
        ts = sorted(rows)
        rho_gap, n_g = common.spearman([rows[t]["gap_base"] for t in ts],
                                       [rows[t]["gap_adj"] for t in ts])
        rho_mos, n_m = common.spearman([rows[t]["mos_base"] for t in ts],
                                       [rows[t]["mos_adj"] for t in ts])
        base_mos = sorted(v["mos_base"] for v in rows.values()
                          if isinstance(v["mos_base"], (int, float)))
        adj_mos = sorted(v["mos_adj"] for v in rows.values()
                         if isinstance(v["mos_adj"], (int, float)))
        b33, b75 = common.percentile(base_mos, 33), common.percentile(base_mos, 75)
        a33, a75 = common.percentile(adj_mos, 33), common.percentile(adj_mos, 75)
        flips = sorted(t for t in ts
                       if tier(rows[t]["mos_base"], b33, b75) != tier(rows[t]["mos_adj"], a33, a75))
        gap_moves = sorted(((t, round(rows[t]["gap_adj"] - rows[t]["gap_base"], 1)) for t in ts
                            if rows[t]["gap_adj"] is not None and rows[t]["gap_base"] is not None),
                           key=lambda x: -abs(x[1]))
        cf_ratios = sorted(v["cf_ratio"] for v in rows.values())
        out["variants"][vname] = {
            "n_adjusted": len(rows), "n_missing_data": len(missing),
            "missing": sorted(missing),
            "n_flow_turns_nonpositive": len(nonpos), "nonpositive": sorted(nonpos),
            "cf_ratio_percentiles": {p: common.percentile(cf_ratios, p) for p in (10, 25, 50, 75, 90)},
            "spearman_gap": {"rho": rho_gap, "n": n_g},
            "spearman_mos": {"rho": rho_mos, "n": n_m},
            "brake_tier_flips": {"count": len(flips), "tickers": flips},
            "largest_gap_moves_pts": gap_moves[:15],
        }
    common.save("c3_flow_variants", out)


if __name__ == "__main__":
    main()
