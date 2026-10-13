"""D-T1 recomputed from the exported residual file alone (SPEC_rebuild AK.19 rule, AK.20 result). Imports nothing from rs2-local; numpy
and pandas only, so anyone with the CSV can reproduce it.

    python d_t1_from_csv.py d_t1_residuals_cut2025.csv.gz

Per family, the pairs of the build's copula (`priors_build/near_term.copula_pairs`): each variable across years (1-2, 2-3, 1-3) and the
family's two variables in the same year. Pair rows = company-dates with both residuals; n >= 300. Rank PITs u = rank / (n + 1) (average
ranks). Gaussian r = 2 sin(pi rho / 6), rho the Spearman correlation. The Gaussian co-exceedance Pr(Z1 < z, Z2 < z), z = Phi^-1(0.10), is
by Monte Carlo (4M draws, seed 20261013). Trigger: empirical / Gaussian >= 1.5 in the lower tail AND the empirical rate's one-sided 90%
lower bound (10th percentile of 2,000 company resamples, seed 20261013, PITs held fixed) above the Gaussian rate.
"""
import sys

import numpy as np
import pandas as pd

VARS = {"operating": ("growth", "margin"), "financial": ("tbvg", "rote")}
Q, NMIN, SEED, B, NMC = 0.10, 300, 20261013, 2000, 4_000_000


def main(path):
    res = pd.read_csv(path)
    rng = np.random.default_rng(SEED)
    for fam, (a, b) in VARS.items():
        piv = res[res["family"] == fam].pivot_table(index=["cik", "date"], columns=["var", "k"], values="resid")
        pairs = [((v, 1), (v, 2)) for v in (a, b)] + [((v, 2), (v, 3)) for v in (a, b)] + [((v, 1), (v, 3)) for v in (a, b)]
        pairs += [((a, k), (b, k)) for k in (1, 2, 3)]
        for x, y in pairs:
            both = piv[[x, y]].dropna()
            n = len(both)
            if n < NMIN:
                print(fam, x, y, "n", n, "skipped")
                continue
            rk = both.rank()
            rho = float(np.corrcoef(rk.iloc[:, 0], rk.iloc[:, 1])[0, 1])
            r = 2 * np.sin(np.pi * rho / 6)
            u = rk.to_numpy() / (n + 1)
            low = (u[:, 0] < Q) & (u[:, 1] < Q)
            up = (u[:, 0] > 1 - Q) & (u[:, 1] > 1 - Q)
            z1 = rng.standard_normal(NMC)
            z2 = r * z1 + np.sqrt(1 - r * r) * rng.standard_normal(NMC)
            g = float(np.mean((z1 < np.quantile(z1, Q)) & (z2 < np.quantile(z2, Q))))
            ciks = both.index.get_level_values("cik").to_numpy()
            uniq, inv = np.unique(ciks, return_inverse=True)
            lows = np.bincount(inv, weights=low.astype(float), minlength=len(uniq))
            cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
            boots = []
            for _ in range(B):
                w = np.bincount(rng.integers(0, len(uniq), len(uniq)), minlength=len(uniq))
                boots.append((w * lows).sum() / (w * cnts).sum())
            lb = float(np.quantile(boots, 0.10))
            el, eu = float(low.mean()), float(up.mean())
            trig = el / g >= 1.5 and lb > g
            print(f"{fam:9s} {x[0]}{x[1]}|{y[0]}{y[1]:<3} n={n:5d} r={r:+.3f} gauss={g:.5f} lower={el:.5f} ({el / g:.2f}, lb90 {lb:.5f})"
                  f" upper={eu:.5f} ({eu / g:.2f}){'  TRIGGER' if trig else ''}")


if __name__ == "__main__":
    main(sys.argv[1])
