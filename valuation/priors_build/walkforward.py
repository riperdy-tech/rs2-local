"""walkforward.py - the honest check of the priors against the mechanical baseline: the tables of vintage Y-1 applied to the observations whose outcome
became known in Y (the next-year annual report filed between the two cut dates).  These are true forecasts (the prior never saw them), unlike the
in-sample baseline comparison inside each vintage.  Fundamentals only; no price, no return.

    python -m valuation.priors_build.walkforward [out.json]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from valuation.priors_build import config as C
from valuation.priors_build import stats as S


def _band_key(b, sg):
    return f"{ {0: 'low', 1: 'mid', 2: 'high'}.get(b, b) }_{'pos' if sg > 0 else 'neg'}"


def evaluate(year, status):
    prev, cur = year - 1, year
    cut_prev, cut_cur = C.cut_date(prev), C.cut_date(cur)
    Tp = json.loads((C.vintage_dir(prev) / "tables.json").read_text(encoding="utf-8"))
    df = pd.read_csv(C.vintage_dir(cur) / "obs.csv.gz", dtype={"cik": str, "sic": str}, low_memory=False)
    d = S.prep_frame(df, status, cut_cur)
    out = {"vintage_used": prev, "outcome_window": [cut_prev, cut_cur]}
    # g1, operating family, 3-year-CAGR basis, size x growth cells
    s = d[d["family"].eq("operating") & d["size_b"].ge(0) & d["g3"].notna() & d["y1"].notna() & (d["filed_1"].astype(str) >= cut_prev) & (d["filed_1"].astype(str) < cut_cur)]
    cells = Tp["g1"]["operating"]["g3"]["cells"]
    gb = S.bucket(s["g3"], S.GROWTH_EDGES)
    sb = s["size_b"].to_numpy()
    y = s["y1"].to_numpy()
    base = s["g3"].to_numpy()
    p = {k: np.full(len(s), np.nan) for k in ("p10", "p25", "p50", "p75", "p90")}
    for i in range(len(s)):
        c = S.find_cell(cells, int(sb[i]), int(gb[i]))
        if c is not None and c.get("n", 0) >= C.MIN_N:
            for k in p:
                p[k][i] = c.get(k, np.nan)
    ok = np.isfinite(p["p50"])
    if ok.any():
        out["g1"] = {"n": int(ok.sum()), "baseline_medae": float(np.median(np.abs(y[ok] - base[ok]))), "prior_p50_medae": float(np.median(np.abs(y[ok] - p["p50"][ok]))),
                     "in_p10_p90": float(np.mean((y[ok] >= p["p10"][ok]) & (y[ok] <= p["p90"][ok]))),
                     "in_p25_p75": float(np.mean((y[ok] >= p["p25"][ok]) & (y[ok] <= p["p75"][ok])))}
    # operating margin k = 1 and 3: the A2 median path of the band x sign against the margin held
    mr = Tp["margin_retention"]
    cuts = mr["cyc_cuts"]
    for k in (1, 3):
        t = d[d["family"].isin(["operating", "commodity"]) & d["dev"].notna() & (d["dev"].abs() >= S.A2_MIN_DEV) & d["med8"].notna() & d["cyc"].notna() &
              d[f"m_{k}"].notna() & (d[f"filed_{k}"].astype(str) >= cut_prev) & (d[f"filed_{k}"].astype(str) < cut_cur)]
        if not len(t):
            continue
        cb = S.band(t["cyc"], cuts)
        pred = np.full(len(t), np.nan)
        dev, med = t["dev"].to_numpy(), t["med8"].to_numpy()
        for b in range(len(cuts) + 1):
            for sg in (1, -1):
                bd = mr["bands"].get(_band_key(b, sg))
                if not bd or bd["n"] < C.MIN_N:
                    continue
                row = [r for r in bd["ks"] if r["k"] == k][0]
                if row.get("median") is None or row["n"] < C.MIN_N:
                    continue
                m = (cb == b) & (np.where(dev > 0, 1, -1) == sg)
                pred[m] = med[m] + min(1.0, max(0.0, row["median"])) * dev[m]
        mk, m0 = t[f"m_{k}"].to_numpy(), t["m"].to_numpy()
        ok = np.isfinite(pred) & (np.abs(mk) <= 1.0) & (np.abs(m0) <= 1.0)
        if ok.any():
            out[f"margin_k{k}"] = {"n": int(ok.sum()), "held_medae": float(np.median(np.abs(mk[ok] - m0[ok]))), "a2_path_medae": float(np.median(np.abs(mk[ok] - pred[ok])))}
    return out


def main(out):
    status = pd.read_csv(C.INPUTS_DIR / "company_status.csv.gz", dtype={"cik": str})
    res = {}
    for y in range(2014, 2026):
        if (C.vintage_dir(y) / "obs.csv.gz").exists() and (C.vintage_dir(y - 1) / "tables.json").exists():
            res[str(y)] = evaluate(y, status)
    Path(out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    r = main(sys.argv[1] if len(sys.argv) > 1 else str(C.DATA_DIR / "walkforward.json"))
    for y, v in r.items():
        print(y, {k: ({a: round(b, 4) if isinstance(b, float) else b for a, b in x.items()} if isinstance(x, dict) else x) for k, x in v.items() if k in ("g1", "margin_k1", "margin_k3")})
