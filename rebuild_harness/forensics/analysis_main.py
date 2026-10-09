"""Run F1-F9 on a forensic panel.

    python -m rebuild_harness.forensics.analysis_main PANEL.pkl OUT_DIR [--only F1 F2 ...]

One markdown and one JSON file per section go into OUT_DIR (a new folder per attempt)."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import analysis_f as AF
from . import analysis_g as AG

SECTIONS = {"F1": AF.f1, "F2": AF.f2, "F3": AG.f3, "F4": AG.f4, "F5": AG.f5, "F6": AG.f6, "F7": AF.f7, "F8": AG.f8, "F9": AF.f9}


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        o = o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    return o


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("panel", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--dates", nargs="*", help="restrict to these dates (a smoke test)")
    a = ap.parse_args(argv)
    df = pd.read_pickle(a.panel).reset_index(drop=True)
    if a.dates:
        df = df[df["date"].isin(a.dates)].reset_index(drop=True)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    print("panel", df.shape, "dates", df["date"].nunique(), flush=True)
    for k, fn in SECTIONS.items():
        if a.only and k not in a.only:
            continue
        t0 = time.time()
        out = {}
        try:
            L = fn(df, out)
        except Exception:
            import traceback
            tb = traceback.format_exc()
            (a.out_dir / f"{k}_ERROR.txt").write_text(tb, encoding="utf-8")
            print(k, "ERROR", tb[-600:], flush=True)
            continue
        (a.out_dir / f"{k}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        (a.out_dir / f"{k}.json").write_text(json.dumps(_clean(out), indent=1, default=str), encoding="utf-8")
        print(k, f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
