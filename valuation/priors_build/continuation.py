"""Engine v2.1's continuation table (REGISTRATION_continuation_direct.md; SPEC_rebuild Addenda AL.40-AL.43): priors_v5 = priors_v3_fy + `continuation`.

For each family (operating: revenue growth g; financial: tangible-book growth tg) and each of the vintage's growth-decay buckets (the merged growth-delivered
buckets, unchanged), lambda_k for k = 4..10 is the L1 regression slope through the origin of y = g_k - T on x = g_3 - T over the vintage's own observation
pairs (the weighted median of y / x, weights |x|; x = 0 excluded), T = the growth-decay table's terminal reference.  Measured while n >= MIN_N, clipped to
[0, 1], the last measured value held to year 10, then the running minimum from lambda_3 = 1.  A bucket not measurable at k = 4 is None; the family-pooled
lambda (all buckets together) is stored beside it as the fall-back (AL.42, scored in AL.43).

    python -m valuation.priors_build.continuation SRC_ROOT DST_ROOT [VINTAGE ...]
writes DST_ROOT/<V>/tables.json (SRC's tables plus `continuation`, priors_version "5") and tables.sha256."""
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from . import stats as S
from .config import MIN_N

HORIZON = 10
FAMS = {"operating": ("g", "g3_b"), "financial": ("tg", "tg3_b")}
RULE = ("lambda_k (k = 4..10) = the L1 slope through the origin of (g_k - T) on (g_3 - T) by growth-decay bucket; n >= MIN_N; clipped to [0, 1]; held; "
        "running minimum from lambda_3 = 1 (Addenda AL.40-AL.43)")


def wmedian(r: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(r)
    r, w = r[o], w[o]
    c = np.cumsum(w)
    return float(r[np.searchsorted(c, 0.5 * c[-1])])


def lambdas(s: pd.DataFrame, pre: str, T: float) -> Tuple[Optional[List[float]], List[int]]:
    """lambda_4..lambda_10 (7 values) and the n behind each measured k, or (None, []) when k = 4 has fewer than MIN_N pairs."""
    x = s[f"{pre}_3"].to_numpy(dtype=float) - T
    lam, ns = [], []
    for k in range(4, HORIZON + 1):
        y = s[f"{pre}_{k}"].to_numpy(dtype=float) - T
        ok = np.isfinite(x) & np.isfinite(y) & (x != 0)
        if ok.sum() < MIN_N:
            break
        lam.append(min(1.0, max(0.0, wmedian(y[ok] / x[ok], np.abs(x[ok])))))
        ns.append(int(ok.sum()))
    if not lam:
        return None, []
    lam = (lam + [lam[-1]] * HORIZON)[:HORIZON - 3]
    env, m = [], 1.0
    for v in lam:
        m = min(m, v)
        env.append(m)
    return env, ns


def continuation_table(d: pd.DataFrame, growth_decay: dict) -> dict:
    """`d` is the vintage's prepared frame (stats.prep_frame); `growth_decay` its growth-decay table (buckets and terminal reference)."""
    out = {"rule": RULE}
    for fam, (pre, gb) in FAMS.items():
        t = growth_decay.get(fam) or {}
        if not t.get("terminal_reference"):
            continue
        T = t["terminal_reference"]["value"]
        f = d[d["family"].eq(fam) & d[f"{pre}_1"].notna()]
        buckets = []
        for bk in t["buckets"]:
            lo, hi = bk["bucket"]
            lam, ns = lambdas(f[(f[gb] >= lo) & (f[gb] <= hi)], pre, T)
            buckets.append({"bucket": [lo, hi], "lambda": lam, "n": ns})
        pooled, pns = lambdas(f[f[gb] >= 0], pre, T)
        out[fam] = {"terminal_reference": T, "buckets": buckets, "family_pooled": pooled, "family_pooled_n": pns}
    return out


def build(src_root: Path, dst_root: Path, vintage: int) -> str:
    src = Path(src_root) / str(vintage)
    T = json.loads((src / "tables.json").read_text(encoding="utf-8"))
    cut = json.loads((src / "obs_meta.json").read_text(encoding="utf-8"))["cut_date"]
    df = pd.read_csv(src / "obs.csv.gz", dtype={"cik": str, "sic": str}, low_memory=False)
    T["continuation"] = continuation_table(S.prep_frame(df, None, cut), T["growth_decay"])
    T["continuation"]["source_tables_sha256"] = hashlib.sha256((src / "tables.json").read_bytes()).hexdigest()
    T["priors_version"] = "5"
    dst = Path(dst_root) / str(vintage)
    dst.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(T, indent=1).encode("utf-8")
    (dst / "tables.json").write_bytes(raw)
    h = hashlib.sha256(raw).hexdigest()
    (dst / "tables.sha256").write_text(h + "\n", encoding="utf-8")
    return h


if __name__ == "__main__":
    a = sys.argv[1:]
    vs = [int(v) for v in a[2:]] or sorted(int(p.name) for p in Path(a[0]).iterdir() if p.name.isdigit())
    for v in vs:
        print(v, build(Path(a[0]), Path(a[1]), v), flush=True)
