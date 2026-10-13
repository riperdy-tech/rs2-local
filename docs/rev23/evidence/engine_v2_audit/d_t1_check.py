"""Independent check of D-T1's Gaussian rates (Monte Carlo, imports nothing from d_t1_tails.py or the build), and the t(nu=4) copula's
implied lower/upper co-exceedance at the same r: what the registered v2.1 candidate would give. numpy only; seed 20261013."""
import json
from pathlib import Path

import numpy as np

d = json.loads(Path(__file__).with_name("d_t1_tails_result.json").read_text(encoding="utf-8"))
rng = np.random.default_rng(20261013)
N, Q = 4_000_000, 0.10
for p in d["pairs"]:
    if "r" not in p:
        continue
    r = p["r"]
    z1 = rng.standard_normal(N)
    z2 = r * z1 + np.sqrt(1 - r * r) * rng.standard_normal(N)
    lo1, lo2 = np.quantile(z1, Q), np.quantile(z2, Q)
    g = float(np.mean((z1 < lo1) & (z2 < lo2)))
    w = np.sqrt(rng.chisquare(4, N) / 4.0)
    t1, t2 = z1 / w, z2 / w
    a1, a2, b1, b2 = np.quantile(t1, Q), np.quantile(t2, Q), np.quantile(t1, 1 - Q), np.quantile(t2, 1 - Q)
    tl, tu = float(np.mean((t1 < a1) & (t2 < a2))), float(np.mean((t1 > b1) & (t2 > b2)))
    print(f"{p['pair']:28s} r={r:+.3f} gauss(int)={p['gauss_rate']:.5f} gauss(MC)={g:.5f} | emp lo={p['emp_lower']:.5f} up={p['emp_upper']:.5f}"
          f" | t4 lo={tl:.5f} up={tu:.5f} | emp/t4 lo={p['emp_lower'] / tl:.2f} up={p['emp_upper'] / tu:.2f}{'  TRIGGER' if p['trigger'] else ''}")
