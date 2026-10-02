"""AT1b (brief section 6): the reduction test at engine level. For every book name, revision 18's `build` with the section 4 part 1 switches
on, fed exactly the inputs revision 16's `build` receives on that day (revision 16's base, estimates, COE, terminal growth and share count),
reproduces revision 16's (fee17cf) value to the cent. It compares engines, not packs.

  python at1b_reduction.py --day16 <build_day.py output of revision 16's tree> --tree16 <rs2 at fee17cf> --tree18 <rs2 at the final commit>
                           [--out <result.json>]

One engine per process (the backtest harness's rule): the driver starts this script twice with --worker, once per tree, and compares.
The switches (revision 18 worker):
  returns +inf         record R_tc = ronic_t = +inf          margin rule off      record om_trend = None
  working capital off  record nwc_intensity = None           cash off             cash = None
  terminal growth      revision 16's rule: the recorded terminal_g is passed unchanged
  X = owner earnings   growth method: base_ni = base_cf. Levels method: the vendor's EPS levels are replaced by (cash-flow level / shares)
                       and D&A, capex by 0.0 (identical cash flows, earnings = cash flows); only where revision 16 had a value
  closure off          MRI's premium, no floor: the recorded coe is passed unchanged
|difference| < $0.005 (and both None) for every name. Offline: every socket is blocked.
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
        kw = dict(stub_months=ref.get("stub_months"), da=da, capex=capex, levels_reason=levels_reason)
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
                         levels_reason=levels_reason, record=record, base_ni=base_arg, base_revenue=None, cash=None)
        out[key] = {"value": res.get("value"), "method": res.get("method")}
    Path(out_path).write_text(json.dumps(out), encoding="utf-8")


def compare(v16, v18, *, names=True, tol=0.005):
    bad, n = [], 0
    for key in sorted(v16):
        n += 1
        a, b = v16[key]["value"], (v18.get(key) or {}).get("value", "missing")
        same = (a is None and b is None) or (a is not None and _num(b) and abs(a - b) < tol)
        if not same:
            bad.append((key if names else None, a, b if b != "missing" else "no revision 18 value"))
    ok = n > 0 and not bad
    return {"at": "AT1b reduction", "pass": ok, "names": n, "differences": len(bad), "details": bad[:20], "bar": f"|rev18 - rev16| < ${tol}",
            "summary": f"{n - len(bad)} of {n} names reproduce revision 16's value to the cent; {len(bad)} differ"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day16", required=True, type=Path)
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
    ac.block_network()
    results = {}
    with tempfile.TemporaryDirectory(prefix="at1b_") as tmp:
        for mode, tree in (("rev16", a.tree16), ("rev18", a.tree18)):
            p = Path(tmp) / f"{mode}.json"
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", mode, "--tree", str(tree), "--day16", str(a.day16),
                            "--worker-out", str(p)], check=True)
            results[mode] = json.loads(p.read_text(encoding="utf-8"))
    result = compare(results["rev16"], results["rev18"])
    result["trees"] = {"rev16": {"path": str(a.tree16), "commit": ac.git_head(a.tree16)[0]}, "rev18": {"path": str(a.tree18), "commit": ac.git_head(a.tree18)[0]}}
    result["day16_file_sha256"] = ac.sha256_file(a.day16)
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
