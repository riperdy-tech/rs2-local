"""The study panel: the pass-1 rows (universe at T and the code's forecasts) joined with the priors vintage-2024 observation table (outcomes, first filed, every filing before 2025-01-01).

    python -m rebuild_harness.forecast_study.panel PASS_DIR OUT.pkl

INFORMATION CUT.  The only outcome source is `data/priors_v3/2024/obs.csv.gz`, whose rule is "fiscal years whose own annual report was filed strictly before 2025-01-01, first-filed values".  No file of
fiscal 2025 exists in it, and `assert_cut` refuses any outcome filed after 2024-12-31.  The population medians (candidate i) and every walk-forward fit use an outcome only if its annual report was filed
strictly before the origin date of the fit (`known_at`).

Outcome definitions (the engine's, on first-filed values): revenue growth in year k = rev_k / rev_(k-1) - 1 (rev_0 = the base year); tangible-book growth likewise; operating margin = operating income / revenue of
fiscal year B+k; ROTE = net income / average tangible equity (the priors build's definition, `obs.rote_by_period`).  Year k exists only when fiscal years B+1..B+k follow the base year with no gap (the chain index)."""
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CUT = "2024-12-31"
MAX_BASE_AGE_MONTHS = 18.0
OBS = Path(r"C:\Users\riper\stocks\stocks-workspace\data\priors_v3\2024\obs.csv.gz")
KS = (1, 2, 3)
OBS_COLS = (["cik", "fye", "own_filed", "family", "rev", "m", "med8", "dev", "cyc", "rote", "tbv", "rote_med8", "years_held", "n_ahead"]
            + [f"{a}_{k}" for k in KS for a in ("rev", "m", "rote", "tbv", "filed")])


def load_obs():
    d = pd.read_csv(OBS, usecols=OBS_COLS, dtype={"cik": str})
    d["cik"] = d["cik"].str.zfill(10)
    d = d.drop_duplicates(["cik", "fye"])            # one placeholder cik (0) is held twice
    for k in KS:
        d[f"filed_{k}"] = d[f"filed_{k}"].astype("string")
    for k in KS:
        prev_r, prev_t = ("rev" if k == 1 else f"rev_{k - 1}"), ("tbv" if k == 1 else f"tbv_{k - 1}")
        r0, r1 = d[prev_r], d[f"rev_{k}"]
        d[f"g_{k}"] = np.where((r0 > 0) & (r1 > 0), r1 / r0 - 1.0, np.nan)
        t0, t1 = d[prev_t], d[f"tbv_{k}"]
        d[f"tg_{k}"] = np.where((t0 > 0) & (t1 > 0), t1 / t0 - 1.0, np.nan)
    return d


def assert_cut(d):
    for k in KS:
        v = d[f"filed_{k}"].dropna()
        assert v.empty or v.max() <= CUT, f"an outcome filed after {CUT} is in the table: {v.max()}"
    assert d["own_filed"].max() <= CUT


def read_pass(pass_dir):
    rows = []
    for f in sorted(Path(pass_dir).glob("pass_*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                fc = r.get("forecast") or {}
                o = {"date": r["date"], "year": int(r["date"][:4]), "cik": r["cik"], "ticker": r.get("ticker"), "family": r["family"], "industry": r.get("industry"), "mcap": r["mcap"],
                     "base_fye": r["base_fye"], "base_age_months": r["base_age_months"], "vintage": r.get("vintage"), "unavail": "; ".join(r.get("unavailable", [])),
                     "g_term": r.get("g_term"), "error": r.get("error")}
                ft = r.get("features") or {}
                for a in ("rev", "g_latest", "g3", "tg_latest", "tg3", "m", "med8", "dev", "n8", "rote", "rote_med8", "rote_dev", "cyc_equal"):
                    o["f_" + a] = ft.get(a)
                st = r.get("state") or {}
                o["rote_latest"] = st.get("rote_latest")
                o["s_tbv"] = st.get("tbv")
                mech = r.get("mech") or {}
                o["mech_g1"] = mech.get("g1")
                o["cyc"] = (r.get("cyc") or {}).get("score")
                for k in KS:
                    for nm in ("growth", "margin", "margin_curve", "rote", "rote_norm", "rote_curve", "rote_norm_curve"):
                        q = fc.get(f"{nm}_{k}")
                        if q:
                            for lv in ("p10", "p50", "p90"):
                                if lv in q:
                                    o[f"c_{nm}_{k}_{lv}"] = q[lv]
                if "margin_ret" in fc:
                    for a, b in fc["margin_ret"].items():
                        o["mret_" + a] = b
                if "rote_ret" in fc:
                    for a, b in fc["rote_ret"].items():
                        o["rret_" + a] = b
                rows.append(o)
    return pd.DataFrame(rows)


def build(pass_dir):
    p = read_pass(pass_dir)
    n0 = len(p)
    stale = (p.base_age_months < 0) | (p.base_age_months > MAX_BASE_AGE_MONTHS)
    p = p[~stale].copy()                               # a base year more than 18 months old (a delinquent filer) or ending after the origin is not a forecast of "the next fiscal year"
    obs = load_obs()
    assert_cut(obs)
    keep = ["cik", "fye", "own_filed", "rev", "m", "rote", "tbv", "years_held"] + [f"{a}_{k}" for k in KS for a in ("rev", "m", "rote", "tbv", "filed", "g", "tg")]
    o = obs[keep].rename(columns={"fye": "base_fye", "rev": "o_rev", "m": "o_m", "rote": "o_rote", "tbv": "o_tbv", "own_filed": "base_filed"})
    j = p.merge(o, on=["cik", "base_fye"], how="left", validate="many_to_one")
    j["matched"] = j["base_filed"].notna()
    # the year-1 growth is measured from the base year AS KNOWN AT T (the state the code forecast from), to the first-filed value of the next year: H3's convention (`gate1_v2.b4_v2`); years 2 and 3 are first-filed on both ends
    r0, t0 = pd.to_numeric(j["f_rev"], errors="coerce"), pd.to_numeric(j["s_tbv"], errors="coerce")
    j["g_1"] = np.where((r0 > 0) & (j["rev_1"] > 0), j["rev_1"] / r0 - 1.0, np.nan)
    j["tg_1"] = np.where((t0 > 0) & (j["tbv_1"] > 0), j["tbv_1"] / t0 - 1.0, np.nan)
    for k in KS:
        j[f"filed_{k}"] = j[f"filed_{k}"].astype("string")
        bad = j[f"filed_{k}"].notna() & (j[f"filed_{k}"] <= j["date"])
        j.loc[bad, [f"g_{k}", f"tg_{k}", f"m_{k}", f"rote_{k}", f"rev_{k}", f"tbv_{k}"]] = np.nan          # an outcome filed on or before the origin is not an outcome
        j[f"n_bad_{k}"] = bad
    j.attrs["excluded_stale_base"] = int(n0 - len(p))
    return j, obs


if __name__ == "__main__":
    j, _ = build(sys.argv[1])
    j.to_pickle(sys.argv[2])
    print(j.shape, j["matched"].mean())
