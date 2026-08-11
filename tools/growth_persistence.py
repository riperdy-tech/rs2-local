"""How much of a high-growth year actually persists? Measured across the full corpus:
for every ticker-year with revenue growth g0, what was the REALIZED 5y forward CAGR?"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\riper\Downloads\RS2 Local")
import rs2_data
from pathlib import Path
import statistics as st

SD = Path(rs2_data.CONFIG["screener_data_dir"])
H = (rs2_data.load_json(SD / "fundamentals_history.json") or {}).get("tickers", {})
buckets = {}
for t, yd in H.items():
    ys = sorted(int(y) for y in yd if str(y).isdigit())
    revs = {}
    for y in ys:
        r = (yd.get(str(y)) or {}).get("revenue")
        if isinstance(r, (int, float)) and r > 0:
            revs[y] = r
    for y in sorted(revs):
        if (y - 1) not in revs or (y + 5) not in revs:
            continue
        g0 = revs[y] / revs[y - 1] - 1
        if not (-0.5 < g0 < 5):
            continue
        fwd5 = (revs[y + 5] / revs[y]) ** (1 / 5) - 1
        if not (-0.9 < fwd5 < 3):
            continue
        for lo, hi, lbl in ((0.15, 0.25, "15-25%"), (0.25, 0.40, "25-40%"),
                            (0.40, 0.70, "40-70%"), (0.70, 5.0, ">70%")):
            if lo <= g0 < hi:
                buckets.setdefault(lbl, []).append(fwd5)
print("REALIZED next-5y revenue CAGR, by the growth rate a company just delivered:")
print(f"{'delivered':>10s}{'n':>7s}{'p25':>8s}{'median':>8s}{'p75':>8s}{'p90':>8s}")
for lbl in ("15-25%", "25-40%", "40-70%", ">70%"):
    v = sorted(buckets.get(lbl, []))
    if len(v) < 30:
        continue
    q = lambda p: v[int(len(v) * p)]
    print(f"{lbl:>10s}{len(v):>7d}{q(.25)*100:>7.1f}%{st.median(v)*100:>7.1f}%{q(.75)*100:>7.1f}%{q(.90)*100:>7.1f}%")
allv = sorted(x for v in buckets.values() for x in v)
print(f"\nacross all high-growth years (n={len(allv)}): median forward 5y CAGR "
      f"{st.median(allv)*100:.1f}%, p90 {allv[int(len(allv)*.9)]*100:.1f}%")
