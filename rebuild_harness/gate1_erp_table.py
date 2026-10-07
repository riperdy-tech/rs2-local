"""The engine-consistent equity risk premium of every date of a run (Addenda L1, M), from the `context_<date>.json` files: Damodaran's published ERP, delta, the result, the engine growth used and his.

    python -m rebuild_harness.gate1_erp_table RUN_DIR [--out OUT.md] [--compare LABEL=OTHER_RUN_DIR ...]

One row per date: the monthly row used, his sustainable-payout ERP, delta (the change in the solved required return of the reproduced index model when only the five-year growth is swapped), the
engine-consistent ERP, the cap-weighted engine growth (mean of the P50 growth path of years 1-5 over the gate universe) beside his expected growth, the universe size, and the premium the run
used in the earlier rounds (`--compare`: the median ERP over the valued names of another run folder, read from its records' `discount.erp`).  Reads only; writes the markdown named.
"""
import argparse
import gzip
import json
import statistics
from pathlib import Path


def load_contexts(run_dir):
    out = {}
    for p in sorted(Path(run_dir).glob("context_*.json")):
        j = json.loads(p.read_text(encoding="utf-8"))
        if j.get("erp"):
            out[j["date"]] = j["erp"]
    return out


def median_erp_used(run_dir, date):
    p = Path(run_dir) / f"records_{date}.jsonl.gz"
    if not p.is_file():
        return None
    xs = []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("status") == "valued" and (r.get("val") or {}).get("discount"):
                xs.append(r["val"]["discount"]["erp"])
    return statistics.median(xs) if xs else None


def _pct(x, nd=2):
    return "n/a" if x is None else f"{x * 100:.{nd}f}%"


def table(run_dir, compare=()):
    ctx = load_contexts(run_dir)
    hdr = ["date", "monthly row", "Damodaran ERP", "delta (bp)", "engine-consistent ERP", "engine growth", "Damodaran growth", "universe (names)"] + [f"median ERP used, {lab}" for lab, _ in compare]
    lines = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for d, e in sorted(ctx.items()):
        row = [d, e["row_date"], _pct(e["damodaran_erp"]), f"{e['delta'] * 1e4:+.0f}", _pct(e["erp"]), _pct(e["engine_growth"]), _pct(e["damodaran_growth"]), str(e["universe"].get("n"))]
        row += [_pct(median_erp_used(p, d)) for _lab, p in compare]
        lines.append("| " + " | ".join(row) + " |")
    if ctx:
        ds = [e["damodaran_erp"] for e in ctx.values()]
        dl = [e["delta"] for e in ctx.values()]
        er = [e["erp"] for e in ctx.values()]
        eg = [e["engine_growth"] for e in ctx.values()]
        dg = [e["damodaran_growth"] for e in ctx.values()]
        lines.append("| mean | | " + " | ".join([_pct(statistics.mean(ds)), f"{statistics.mean(dl) * 1e4:+.0f}", _pct(statistics.mean(er)), _pct(statistics.mean(eg)), _pct(statistics.mean(dg))]) + " | |" + " |" * len(compare))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--compare", action="append", default=[], help="LABEL=RUN_DIR whose median ERP over the valued names is shown beside")
    a = ap.parse_args(argv)
    cmp_ = [tuple(x.split("=", 1)) for x in a.compare]
    md = "# The engine-consistent ERP by date (Addenda L1, M option B)\n\n" + table(a.run_dir, [(l, Path(p)) for l, p in cmp_]) + "\n"
    if a.out:
        a.out.write_text(md, encoding="utf-8")
        print("written", a.out)
    else:
        print(md)


if __name__ == "__main__":
    main()
