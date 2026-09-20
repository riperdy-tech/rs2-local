"""C2 — Terminal-value share of PV across the live book.

Replicates the production fair-value DCF (same g_fair construction as backbone(): forward
growth else trailing CAGR, clamped to [-0.20, FWD_GROWTH_CEIL]) and decomposes PV into
stage-1 + fade vs Gordon terminal. Institutional norm: TV 60-80% of PV; names beyond ~75-80%
have most of their value set by the 2.5% terminal-g assumption.
"""
import common

common.enable_json_cache()
import valuation_backbone as vb  # noqa: E402


def dcf_decompose(base_cf, growth, wacc, tg, s1, fade):
    if wacc <= tg:
        return None
    pv = 0.0
    cf = float(base_cf)
    year = 0
    for _ in range(s1):
        year += 1
        cf *= 1 + growth
        pv += cf / (1 + wacc) ** year
    for i in range(1, fade + 1):
        year += 1
        g_t = growth + (tg - growth) * i / fade
        cf *= 1 + g_t
        pv += cf / (1 + wacc) ** year
    terminal = (cf * (1 + tg)) / (wacc - tg) / (1 + wacc) ** year
    total = pv + terminal
    return {"pv_total": total, "tv_share": terminal / total if total > 0 else None}


def main():
    book = common.book_tickers()
    rows = {}
    shares = []
    for t in book:
        try:
            b = vb.backbone(t)
        except Exception:
            continue
        if not b.get("ok") or b.get("method") != "reverse_dcf":
            continue
        g_drive = b.get("forward_growth")
        if g_drive is None:
            g_drive = b.get("hist_revenue_cagr_5y")
        if g_drive is None or not b.get("base_cf"):
            continue
        g_fair = max(-0.20, min(g_drive, vb.FWD_GROWTH_CEIL))
        d = dcf_decompose(b["base_cf"], g_fair, b["wacc"], vb.TERMINAL_G,
                          b["stage1_years"], b["fade_years"])
        if not d or d["tv_share"] is None:
            continue
        s = round(d["tv_share"] * 100, 1)
        rows[t] = {"tv_share_pct": s, "g_fair": round(g_fair, 4), "wacc_pct": b["wacc_pct"],
                   "fair_value_method": b.get("fair_value_method")}
        shares.append(s)

    shares.sort()
    over75 = sorted([t for t, v in rows.items() if v["tv_share_pct"] > 75.0])
    over85 = sorted([t for t, v in rows.items() if v["tv_share_pct"] > 85.0])
    common.save("c2_tv_share", {
        "n": len(shares),
        "tv_share_percentiles": {p: common.percentile(shares, p) for p in (10, 25, 50, 75, 90)},
        "n_over_75pct": len(over75), "tickers_over_75pct": over75,
        "n_over_85pct": len(over85), "tickers_over_85pct": over85,
        "per_ticker": rows,
    })


if __name__ == "__main__":
    main()
