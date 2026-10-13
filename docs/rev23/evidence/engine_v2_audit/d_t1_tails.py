"""D-T1 and D-T3 (SPEC_rebuild AK.19; registered in stocks-workspace 52b1f8d before this was computed).

D-T1: for every measured copula pair of the vintage-2024 residual panel (outcomes filed before 2025-01-01) with n >= 300, the empirical
lower-tail co-exceedance Pr(U_a < 0.10, U_b < 0.10) of rank PITs against the Gaussian-copula rate at the pair's measured r
(r = 2 sin(pi rho / 6), the build's own conversion). Upper tail reported too. Trigger: ratio >= 1.5 AND the empirical rate's one-sided
90% bootstrap lower bound (2,000 resamples of companies, seed 20261013; PITs held at their full-sample values) above the Gaussian rate.
D-T3: operating margin year-3 residual median by margin-level quintile cell, and the top quintile's median by origin year. Reported only.

    python d_t1_tails.py            (run from anywhere; reads the dev worktree's build code for the residual frame only)
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
sys.path.insert(0, str(DEV))
from valuation import near_term as nt                      # noqa: E402  the cell rule and constants (the residuals are the build's own)
from valuation.priors_build import near_term as b          # noqa: E402

CUT, VINTAGE, Q, NMIN, SEED, B = "2025-01-01", 2024, 0.10, 300, 20261013, 2000
OUT = Path(__file__).with_name("d_t1_tails_result.json")


def Phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def Phi_inv(p):
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if Phi(mid) < p else (lo, mid)
    return (lo + hi) / 2


def gauss_lower(r, q=Q):
    """Pr(Z1 < z, Z2 < z), corr r, by integrating phi(x) Phi((z - r x)/sqrt(1 - r^2)) over x < z (trapezoid, 20,001 points)."""
    z = Phi_inv(q)
    xs = np.linspace(-12.0, z, 20001)
    s = math.sqrt(1.0 - r * r)
    f = np.exp(-xs ** 2 / 2) / math.sqrt(2 * math.pi) * np.array([Phi((z - r * x) / s) for x in xs])
    return float(np.trapz(f, xs))


def main():
    obs, panel = b.load_obs(), pd.read_pickle(b.PANEL)
    res = b.residual_frame(panel, obs, CUT)
    table = json.loads((DEV.parents[2] / "data" / "priors_v4" / str(VINTAGE) / "near_term.json").read_text(encoding="utf-8")) \
        if (DEV.parents[2] / "data" / "priors_v4" / str(VINTAGE) / "near_term.json").exists() else None
    rng = np.random.default_rng(SEED)
    out = {"cut": CUT, "q": Q, "n_min": NMIN, "pairs": [], "triggered": []}
    for fam in nt.VARIABLES:
        a_var, b_var = nt.VARIABLES[fam]
        pairs = [((v, 1), (v, 2)) for v in (a_var, b_var)] + [((v, 2), (v, 3)) for v in (a_var, b_var)] + \
                [((v, 1), (v, 3)) for v in (a_var, b_var)] + [((a_var, k), (b_var, k)) for k in nt.KS]
        piv = res[res["family"] == fam].pivot_table(index=["cik", "date"], columns=["var", "k"], values="resid")
        for (va, ka), (vb, kb) in pairs:
            key = f"{nt.name(va, ka)}|{nt.name(vb, kb)}"
            if (va, ka) not in piv or (vb, kb) not in piv:
                continue
            both = piv[[(va, ka), (vb, kb)]].dropna()
            n = len(both)
            if n < NMIN:
                out["pairs"].append({"pair": key, "n": n, "skipped": "n < 300"})
                continue
            rho = both.rank().corr().iloc[0, 1]
            r = 2.0 * math.sin(math.pi * rho / 6.0)
            u = both.rank().to_numpy() / (n + 1)
            low = (u[:, 0] < Q) & (u[:, 1] < Q)
            up = (u[:, 0] > 1 - Q) & (u[:, 1] > 1 - Q)
            g = gauss_lower(r)                                   # symmetric: the upper-tail Gaussian rate is the same
            ciks = both.index.get_level_values("cik").to_numpy()
            uniq = np.unique(ciks)
            idx = {c: np.flatnonzero(ciks == c) for c in uniq}
            boots = []
            for _ in range(B):
                pick = rng.choice(uniq, size=len(uniq), replace=True)
                rows = np.concatenate([idx[c] for c in pick])
                boots.append(low[rows].mean())
            lb = float(np.quantile(boots, 0.10))
            rec = {"pair": key, "n": n, "n_companies": int(len(uniq)), "r": round(r, 4), "gauss_rate": round(g, 5),
                   "emp_lower": round(float(low.mean()), 5), "ratio_lower": round(float(low.mean()) / g, 3), "lower_lb90": round(lb, 5),
                   "emp_upper": round(float(up.mean()), 5), "ratio_upper": round(float(up.mean()) / g, 3)}
            rec["trigger"] = bool(rec["ratio_lower"] >= 1.5 and lb > g)
            out["pairs"].append(rec)
            if rec["trigger"]:
                out["triggered"].append(key)
    # D-T3
    m3 = res[(res["family"] == "operating") & (res["var"] == "margin") & (res["k"] == 3)].copy()
    t3 = {}
    if table is not None:
        cells = table["residuals"]["operating"]["margin"]["3"]["cells"]
        t3["vintage_table_cells"] = {k: {"n": v["n"], "median": round(v["q"]["0.5"], 4), "p10": round(v["q"]["0.1"], 4), "p90": round(v["q"]["0.9"], 4)}
                                     for k, v in sorted(cells.items())} if all("0.5" in v["q"] for v in cells.values()) else cells
        cuts = table["level_cuts"]["operating"]
        m3["lb"] = np.searchsorted(np.asarray(cuts), m3["m"].astype(float), side="right")
        top = m3[m3["lb"] == 4]
        t3["top_quintile_by_origin_year"] = {str(y): {"n": int(len(g_)), "median": round(float(g_["resid"].median()), 4)}
                                             for y, g_ in top.groupby(top["date"].astype(str).str[:4])}
    out["d_t3"] = t3
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for p_ in out["pairs"]:
        print(p_)
    print("TRIGGERED:", out["triggered"] or "none")
    print(json.dumps(t3, indent=1))


if __name__ == "__main__":
    main()
