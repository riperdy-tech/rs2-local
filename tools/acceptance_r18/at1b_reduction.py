"""AT1b (brief section 6): the reduction test at engine level. For every book name, revision 18's `build` with the section 4 part 1 switches
on, fed exactly the inputs revision 16's `build` receives on that day (revision 16's base, estimates, COE, terminal growth and share count),
reproduces revision 16's (fee17cf) value to the cent. It compares engines, not packs.

  python at1b_reduction.py --day16 <build_day.py output of revision 16's tree> --day <build_day.py output of revision 18's tree, same day>
                           --tree16 <rs2 at fee17cf> --tree18 <rs2 at the final commit> [--out <result.json>]
Refused unless --day16 was built on the same data as --day (date, history, TTM and MRI anchor hashes, data root, enrich records).

One engine per process (the backtest harness's rule): the driver starts this script twice with --worker, once per tree, and compares.
The switches (revision 18 worker):
  returns +inf         record R_tc = ronic_t = +inf          margin rule off      record om_trend = None
  working capital off  record nwc_intensity = None           cash off             cash = None
  terminal growth      revision 16's rule: the recorded terminal_g is passed unchanged
  X = owner earnings   growth method: base_ni = base_cf. Levels method: the vendor's EPS levels are replaced by (cash-flow level / shares)
                       and D&A, capex by 0.0 (identical cash flows, earnings = cash flows); only where revision 16 had a value
  closure off          MRI's premium, no floor: the recorded coe is passed unchanged
|difference| < $0.005 (and both None) for every name. `build` receives every argument revision 16's build received that carries information:
base, estimates, coe, terminal growth, shares, median, D&A, capex, stub months, levels_reason, levels_block and anchor. The revision 16 worker's
value must also equal the value the day file recorded for revision 16's own build (the worker is checked against the record, not only against
revision 18). Offline: every socket is blocked.
"""
import argparse
import copy
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_common as ac  # noqa: E402

INF = math.inf


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def worker(mode, tree, rows, out_path):
    ac.block_network()
    tools = Path(tree).resolve() / "tools"
    sys.path.insert(0, str(tools))
    import consensus_reference as cref
    assert tools in Path(cref.__file__).resolve().parents, cref.__file__
    if mode == "rev16":
        assert not hasattr(cref, "long_run_value"), "the rev16 process holds revision 17+ code"
    else:
        assert hasattr(cref, "long_run_value") and hasattr(cref, "cash_term"), "the rev18 process holds an older revision"
    out = {}
    for key, r in sorted(rows.items()):
        ref = r.get("reference")
        if not ref:
            continue
        est = ref.get("estimates")
        base_arg, coe, tg, shares, med = ref.get("base_arg"), ref.get("coe"), ref.get("terminal_g"), ref.get("shares"), ref.get("median_5y")
        da, capex = ref.get("da"), ref.get("capex")
        levels_reason = ref.get("levels_reason_arg")
        if levels_reason is None:
            levels_reason = ref.get("levels_reason")
        if ref.get("method") == "levels" and ref.get("levels") and est and da is None:
            lv = (est.get("0y") or {}).get("eps", {}).get("avg")
            if _num(lv) and _num(shares):
                da, capex = ref["levels"][0] - lv * shares, 0.0           # only da - capex enters revision 16's levels method
        levels_block, anchor = ref.get("levels_block_arg"), ref.get("anchor_arg")      # the two arguments of `build` the day file keeps besides the rest
        kw = dict(stub_months=ref.get("stub_months"), da=da, capex=capex, levels_reason=levels_reason, levels_block=levels_block, anchor=anchor)
        if mode == "rev16":
            res = cref.build(base_arg, est, coe, tg, shares, med, **kw)
            out[key] = {"value": res.get("value"), "method": res.get("method")}
            continue
        record = {"R_tc": INF, "ronic_t": INF, "om_trend": None, "om_L": None, "nwc_intensity": None, "stamps": []}
        est18, da18, capex18 = est, da, capex
        if ref.get("method") == "levels" and ref.get("value") is not None and da is not None:
            est18 = copy.deepcopy(est)
            for k in ("0y", "+1y"):
                eps = est18[k]["eps"]
                eps["avg"] = (eps["avg"] * shares + da - capex) / shares      # revision 16's cash-flow level of that year, per share
            da18 = capex18 = 0.0
        res = cref.build(base_arg, est18, coe, tg, shares, med, da=da18, capex=capex18, stub_months=ref.get("stub_months"),
                         levels_reason=levels_reason, levels_block=levels_block, anchor=anchor, record=record, base_ni=base_arg,
                         base_revenue=None, cash=None)
        out[key] = {"value": res.get("value"), "method": res.get("method")}
    Path(out_path).write_text(json.dumps(out), encoding="utf-8")


def _same(a, b, tol):
    return (a is None and b is None) or (a is not None and _num(a) and _num(b) and abs(a - b) < tol)


def compare(v16, v18, recorded, *, names=True, tol=0.005):
    """`v16` / `v18`: the two workers' values by key; `recorded`: revision 16's own value for each key as the day file recorded it. The revision 16
    worker must reproduce the recorded value to the cent (else the inputs it was fed are not the ones revision 16 received, and the comparison
    with revision 18 proves nothing), and revision 18 must reproduce the revision 16 worker's."""
    bad, bad16, n = [], [], 0
    for key in sorted(v16):
        n += 1
        a, b = v16[key]["value"], (v18.get(key) or {}).get("value", "missing")
        same = _same(a, b, tol) if b != "missing" else False
        if not same:
            bad.append((key if names else None, a, b if b != "missing" else "no revision 18 value"))
        rec = recorded.get(key, "missing")
        if rec == "missing" or not _same(a, rec, tol):
            bad16.append((key if names else None, rec if rec != "missing" else "no recorded revision 16 value", a))
    ok = n > 0 and not bad and not bad16
    return {"at": "AT1b reduction", "pass": ok, "names": n, "differences": len(bad), "details": bad[:20],
            "rev16_worker_differs_from_recorded": len(bad16), "rev16_worker_details": bad16[:20],
            "bar": f"|rev18 - rev16| < ${tol} and |rev16 worker - rev16 recorded| < ${tol}",
            "summary": f"{n - len(bad)} of {n} names reproduce revision 16's value to the cent; {len(bad)} differ; the revision 16 worker differs from "
                       f"the recorded revision 16 value on {len(bad16)}"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day16", required=True, type=Path)
    ap.add_argument("--day", type=Path, help="revision 18's day file on the same data (required unless --worker)")
    ap.add_argument("--tree16", type=Path)
    ap.add_argument("--tree18", type=Path)
    ap.add_argument("--out", default=None, type=Path)
    ap.add_argument("--worker", choices=["rev16", "rev18"], default=None)
    ap.add_argument("--tree", type=Path)
    ap.add_argument("--worker-out", type=Path)
    a = ap.parse_args(argv)
    if a.worker:
        _meta, rows = ac.load_day(a.day16)
        worker(a.worker, a.tree, rows, a.worker_out)
        return 0
    if a.day is None:
        ap.error("--day is required: revision 16's day is compared with revision 18's on the same data")
    meta16, rows16 = ac.load_day(a.day16)
    meta18, rows18 = ac.load_day(a.day)
    ac.require_same_data(meta16, rows16, meta18, rows18)           # finding 5: revision 16's day on other data is no baseline
    recorded = {key: (r.get("reference") or {}).get("value") for key, r in rows16.items() if r.get("reference")}
    ac.block_network()
    results = {}
    with tempfile.TemporaryDirectory(prefix="at1b_") as tmp:
        for mode, tree in (("rev16", a.tree16), ("rev18", a.tree18)):
            p = Path(tmp) / f"{mode}.json"
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", mode, "--tree", str(tree), "--day16", str(a.day16),
                            "--worker-out", str(p)], check=True)
            results[mode] = json.loads(p.read_text(encoding="utf-8"))
    result = compare(results["rev16"], results["rev18"], recorded)
    result["trees"] = {"rev16": {"path": str(a.tree16), "commit": ac.git_head(a.tree16)[0]}, "rev18": {"path": str(a.tree18), "commit": ac.git_head(a.tree18)[0]}}
    result["day16_file_sha256"] = ac.sha256_file(a.day16)
    result["day_file_sha256"] = ac.sha256_file(a.day)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
