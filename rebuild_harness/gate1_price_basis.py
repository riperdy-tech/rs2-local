"""How far the local month-end price file is from a traded unadjusted close, for the names a gate-1 run valued (a development diagnostic, no return is formed).

    python -m rebuild_harness.gate1_price_basis RUN_DIR [--prices prices_monthly_raw.json] [--out file.json]

For each valued record: the file's split-adjusted Close and its Adj Close in the date's month.  `Close / Adj Close` is the dividend (and spin-off) adjustment that an
adjusted-only proxy would bake into the price level: IV / price on the adjusted proxy is the IV / price of the run times that factor.  Reported per date: the quantiles
of the factor.  Records without both bars are counted.
"""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--prices", type=Path, default=Path(r"C:\Users\riper\stocks\stocks-workspace\data\priors\_inputs\prices_monthly_raw.json"))
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    prices = json.loads(a.prices.read_text(encoding="utf-8"))["prices"]
    out = {}
    for f in sorted(a.run_dir.glob("records_*.jsonl.gz")):
        d = f.name[len("records_"):-len(".jsonl.gz")]
        month = d[:7]
        fac, miss = [], 0
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r["status"] != "valued":
                    continue
                bar = (prices.get(r["ticker"]) or {}).get(month)
                if not bar or not (bar[0] and bar[1] and bar[0] > 0 and bar[1] > 0):
                    miss += 1
                    continue
                fac.append(bar[0] / bar[1])
        if fac:
            q = np.percentile(fac, [5, 25, 50, 75, 95])
            out[d] = {"n": len(fac), "missing_bar": miss, "close_over_adj_close_p5_p25_p50_p75_p95": [float(x) for x in q]}
        else:
            out[d] = {"n": 0, "missing_bar": miss}
    text = json.dumps(out, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
