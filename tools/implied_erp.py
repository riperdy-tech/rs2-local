"""Back the market's own cost of equity out of the live book (Damodaran implied-ERP method):
find r such that the aggregate DCF of the book's earnings equals the book's aggregate market cap."""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\riper\Downloads\RS2 Local")
import rs2_data, valuation_backbone as vb
from pathlib import Path
import statistics as st

SD = Path(rs2_data.CONFIG["screener_data_dir"])
TTM = (rs2_data.load_json(SD / "fundamentals_ttm.json") or {}).get("tickers", {})
macro = rs2_data.load_json(SD / "macro_state.json") or {}
RF = (macro.get("series", {}).get("DGS10", {}).get("value") or 4.65) / 100.0
camp = json.load(open(r"C:\Users\riper\Downloads\RS2 Local\cache\baseline_campaign.json"))

names = []
for t in camp["done"]:
    b = vb.backbone(t)
    if not b.get("ok") or b.get("method") != "reverse_dcf":
        continue
    tf = (TTM.get(t) or {}).get("fields") or {}
    ni = vb._num(tf.get("net_income"))
    g = b.get("forward_growth")
    if g is None:
        g = b.get("hist_revenue_cagr_5y")
    if ni and ni > 0 and b.get("market_cap") and g is not None:
        names.append({"t": t, "ni": ni, "mcap": b["market_cap"], "g": max(min(g, 0.35), -0.05)})
print(f"aggregation set: {len(names)} names | RF (DGS10) = {RF:.2%}")
E = sum(n["ni"] for n in names); M = sum(n["mcap"] for n in names)
print(f"aggregate TTM earnings ${E/1e9:,.0f}B | aggregate market cap ${M/1e12:,.2f}T "
      f"| book P/E {M/E:.1f}x")


def agg_value(r, term_g, stage=5, fade=5):
    tot = 0.0
    for n in names:
        cf, v, g = n["ni"], 0.0, n["g"]
        for i in range(1, stage + 1):
            cf *= (1 + g); v += cf / (1 + r) ** i
        for j in range(1, fade + 1):
            gg = g + (term_g - g) * j / fade
            cf *= (1 + gg); v += cf / (1 + r) ** (stage + j)
        v += (cf * (1 + term_g) / (r - term_g)) / (1 + r) ** (stage + fade)
        tot += v
    return tot


def solve_r(term_g, stage=5, fade=5):
    lo, hi = term_g + 0.005, 0.60
    for _ in range(80):
        mid = (lo + hi) / 2
        if agg_value(mid, term_g, stage, fade) > M:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


print("\nMARKET-IMPLIED cost of equity (the rate at which the book is fairly priced):")
for tg, lbl in ((0.025, "2.5% (current, folk constant)"),
                (0.030, "3.0%"),
                (RF - 0.01, f"{RF-0.01:.2%} (RF - 1pt)"),
                (RF, f"{RF:.2%} (= risk-free, Damodaran's cap)")):
    r = solve_r(tg)
    print(f"  terminal {lbl:32s} -> implied CoE {r:6.2%} | ERP over RF {r-RF:+6.2%}")

print("\nSTAGE/FADE sensitivity (terminal = RF-1pt), implied CoE:")
for s, f in ((5, 5), (5, 10), (7, 8), (10, 10)):
    print(f"  stage {s}y fade {f}y -> {solve_r(RF-0.01, s, f):.2%}")

print(f"\nCURRENT ENGINE: sector rates 7-11% with terminal 2.5%.")
r_now = solve_r(0.025)
print(f"Market implies {r_now:.2%} at that terminal; engine uses ~10% => "
      f"engine discounts {(r_now-0.10)*-100:.1f}pts too HARD, before any company analysis.")
