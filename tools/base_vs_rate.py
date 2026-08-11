import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\riper\Downloads\RS2 Local")
import rs2_data, valuation_backbone as vb
from pathlib import Path
import statistics as st

SD = Path(rs2_data.CONFIG["screener_data_dir"])
TTM = (rs2_data.load_json(SD / "fundamentals_ttm.json") or {}).get("tickers", {})
camp = json.load(open(r"C:\Users\riper\Downloads\RS2 Local\cache\baseline_campaign.json"))
RF = 0.0465

rows = []
for t in camp["done"]:
    b = vb.backbone(t)
    if not b.get("ok") or b.get("method") != "reverse_dcf":
        continue
    tf = (TTM.get(t) or {}).get("fields") or {}
    ni, da, cx = (vb._num(tf.get("net_income")), vb._num(tf.get("da")), vb._num(tf.get("capex")))
    if not (ni and ni > 0 and b.get("market_cap")):
        continue
    oe = (ni + da - cx) if None not in (da, cx) else None
    rows.append({"t": t, "ni": ni, "oe": oe, "engine_base": b.get("base_cf"),
                 "mcap": b["market_cap"]})

NI = sum(r["ni"] for r in rows)
OE = sum(r["oe"] for r in rows if r["oe"] and r["oe"] > 0)
EB = sum(r["engine_base"] for r in rows if r["engine_base"])
M = sum(r["mcap"] for r in rows)
print(f"live book ({len(rows)} names), aggregate:")
print(f"  market cap            ${M/1e12:6.2f}T")
print(f"  TTM net income        ${NI/1e9:6,.0f}B  -> book multiple {M/NI:5.1f}x")
print(f"  TTM owner earnings    ${OE/1e9:6,.0f}B  -> book multiple {M/OE:5.1f}x")
print(f"  ENGINE base_cf in use ${EB/1e9:6,.0f}B  -> book multiple {M/EB:5.1f}x")
print(f"\n  the engine capitalizes {EB/NI:.0%} of the book's actual earnings")
print(f"  => it must award a {M/EB:.0f}x multiple just to call the book FAIR,")
print(f"     while its DCF frame awards ~20-27x. THAT is the structural MoS floor.")

# per-name: how much of the gap is base vs rate?
ratio = sorted((r["engine_base"] / r["ni"]) for r in rows if r["engine_base"] and r["ni"])
print(f"\nper-name engine_base / net income:  p10 {ratio[len(ratio)//10]:.2f}  "
      f"median {st.median(ratio):.2f}  p90 {ratio[9*len(ratio)//10]:.2f}")
low = [r["t"] for r in rows if r["engine_base"] and r["ni"] and r["engine_base"]/r["ni"] < 0.5]
print(f"names where the engine capitalizes <50% of earnings: {len(low)} of {len(rows)}")
print("  e.g.", ", ".join(low[:14]))
