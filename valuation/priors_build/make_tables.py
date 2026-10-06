"""make_tables.py - the statistics of one vintage -> data/priors/<Y>/tables.json (what valuation/priors.py reads), next to its obs table.

    python -m valuation.priors_build.make_tables 2016 2020 ...

The vintage's observation table holds only company-years whose own annual report was filed before the vintage's cut date, with outcomes only from
annual reports filed before it too.  Nothing here reads a price or a return except the two valuation references (EV / FCFF1 and P / TBV), which read
the month-end close at the observation date and never an outcome price.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from valuation.priors_build import config as C
from valuation.priors_build import stats as S


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if (o != o or o in (float("inf"), float("-inf"))) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_inputs(year, mcap=True):
    d = C.vintage_dir(year)
    df = pd.read_csv(d / "obs.csv.gz", dtype={"cik": str, "sic": str}, low_memory=False)
    status = pd.read_csv(C.INPUTS_DIR / "company_status.csv.gz", dtype={"cik": str})
    meta = json.loads((d / "obs_meta.json").read_text(encoding="utf-8"))
    mc = None
    p = C.INPUTS_DIR / "mcap_panel.csv.gz"
    if mcap and p.exists():
        mc = pd.read_csv(p, dtype={"cik": str})
    return df, status, meta, mc


def tables_from_frames(df: pd.DataFrame, status, meta: dict, mc, year: int) -> dict:
    """The tables of one vintage from its observation frame (pure: no disk).  `status` (hindsight labels) and `mc` (the market-cap panel) may be None."""
    t0 = time.time()
    cut = C.cut_date(year)
    d = S.prep_frame(df, status, cut)
    # the cyclicality weights (development years only), then the score the bands use
    wstudy = S.cyc_weight_study(d, year, C.DEV_LAST_YEAR)
    d["cyc_eq"] = d["cyc"]
    if wstudy["adopted"]:
        w = wstudy["weights"]
        d["cyc"] = sum(w[i] * d[c] for i, c in enumerate(S.COMPONENTS))
    opc = d["family"].isin(["operating", "commodity"])
    cyc_cuts = S.terciles(d.loc[opc & d["dev"].notna(), "cyc"])
    cyc_cuts5 = S.quintiles(d.loc[opc & d["dev"].notna(), "cyc"])
    roic_cuts = S.terciles(d.loc[opc, "roic"])
    d = S.add_roic_k(d)
    # valuation references (prices at the observation date; survivors only)
    refs_note = "no market-cap panel built"
    d["mcap"], d["ev"] = np.nan, np.nan
    if mc is not None:
        m = mc[["cik", "fye", "market_cap"]].rename(columns={"market_cap": "mcap"})
        d = d.drop(columns=["mcap", "ev"]).merge(m, on=["cik", "fye"], how="left")
        d["ev"] = d["mcap"] - d["bridge"]
        refs_note = f"market-cap panel: {int(d['mcap'].notna().sum())} observations priced"
    ret = S.margin_retention(d, cyc_cuts)
    roic_pool = d.loc[opc, "roic"].median()
    rote_pool = d.loc[d["family"].eq("financial"), "rote"].median()
    tables = {
        "priors_version": C.PRIORS_VERSION, "vintage": year, "cut_date": cut,
        "rule": "every figure comes from fiscal years whose own annual report was filed strictly before the cut date (first-filed values); a valuation date T "
                "uses the vintage year(T) - 1",
        "obs_sha256": meta["obs_sha256"], "store_fingerprint_sha256": meta["store_fingerprint_sha256"], "observations": meta["observations"],
        "edges": {"size_usd": S.SIZE_EDGES, "growth": S.GROWTH_EDGES, "fcf_growth": S.FCF_GROWTH_EDGES, "rote": S.ROTE_EDGES},
        "min_n": C.MIN_N, "cuts": {"cyc_terciles": cyc_cuts, "cyc_quintiles": cyc_cuts5, "roic_terciles": roic_cuts},
        "cyc_weights": wstudy,
        "population": S.population_state(d, cut), "survivorship": S.survivorship(d),
        "g1": S.g1_tables(d), "growth_decay": S.decay_tables(d),
        "margin_retention": ret, "normalization": S.normalization_bands(d, cyc_cuts5), "rote_retention": S.rote_retention(d),
        "ronic": S.ronic_tables(d, roic_cuts),
        "ronic_fade": S.excess_return_fade(d, "roic", "roic_{k}", opc, float(roic_pool)) if np.isfinite(roic_pool) else None,
        "excess_fade_financial": S.excess_return_fade(d, "rote", "rote_{k}", d["family"].eq("financial"), float(rote_pool)) if np.isfinite(rote_pool) else None,
        "terminal": S.terminal_tables(d), "correlation": S.correlation_tables(d),
        "ev_fcf": S.ev_fcf_tables(d, roic_cuts), "ptbv": S.ptbv_tables(d), "refs_note": refs_note,
        "baseline": S.mechanical_baseline(d, ret),
    }
    return clean(tables)


def build(year: int, mcap: bool = True) -> dict:
    t0 = time.time()
    df, status, meta, mc = load_inputs(year, mcap)
    tables = tables_from_frames(df, status, meta, mc, year)
    tables["seconds"] = round(time.time() - t0)
    body = json.dumps(tables, separators=(",", ":"), allow_nan=False)
    (C.vintage_dir(year) / "tables.json").write_text(body, encoding="utf-8")
    sha = sha256_bytes(body.encode("utf-8"))
    (C.vintage_dir(year) / "tables.sha256").write_text(sha + chr(10), encoding="utf-8")
    return {"vintage": year, "tables_sha256": sha, "seconds": tables["seconds"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("years", nargs="+", type=int)
    ap.add_argument("--no-mcap", action="store_true")
    a = ap.parse_args()
    for y in a.years:
        print(build(y, not a.no_mcap), flush=True)
