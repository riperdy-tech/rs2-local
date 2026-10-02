"""AT1c (brief section 6, amendment 1 point 4): production is the design that was tested. 200 validation name-dates (seed 20261002) are drawn
from the PAIRED samples P(T) of the validation dates 2019-2023 (the names with V_B > 0 and V_S > 0 in the backtest harness's pre-outcome
tables, table_2019..2023.pkl); revision 18's engine is fed the backtest's consensus-free inputs (registration 4.6's synthetic estimates, that
date's premium, rf_eff, gA and pi, and the cash inputs) and must reproduce the harness's recorded V_S to the cent.

  python at1c_tested_design.py draw --backtest <SP\\backtest> --out <inputs.json>            # the sample, from the harness's pickles
  python at1c_tested_design.py run  --inputs <inputs.json> --tree <rs2 final commit> --bt-tree <rs2-bt at 40cb5cf> [--out <result.json>]

`draw` reads, read-only, backtest/pit/.. via mri/pit_anchors.json, out/inputs/inputs_<Y>.pkl, out/prelook/table_<Y>.pkl and
result_candidate_<Y>.json (closure.erp_S); the pre-outcome tables hold no returns. `run` needs the harness's input helpers only
(backtest_phase2.arms._precheck and synthetic_estimates, imported from --bt-tree after the tree's own tools, so `consensus_reference` and
`throughcycle_record` are production's). |engine - V_S| < $0.005 for every name-date. Offline: every socket is blocked.
"""
import argparse
import json
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_common as ac  # noqa: E402

SEED = 20261002
N = 200
YEARS = ("2019", "2020", "2021", "2022", "2023")


def draw_paired(pool, seed=SEED, n=N):
    """`n` entries of `pool` drawn with random.Random(seed) after sorting by (date, cik): the draw does not depend on the pool's order."""
    pool = sorted(pool, key=lambda p: (p["date"], str(p["cik"])))
    if len(pool) < n:
        raise ValueError(f"the paired pool holds {len(pool)} name-dates, fewer than {n}")
    return random.Random(seed).sample(pool, n)


def load_pool(backtest):
    """The paired pool P(T) over YEARS from the backtest folder: [{date, cik, nm, coe, gA, pi, V_S}]."""
    bt = Path(backtest)
    anchors = json.loads((bt / "mri" / "pit_anchors.json").read_text(encoding="utf-8"))["dates"]
    pool = []
    for y in YEARS:
        d = pickle.load(open(bt / "out" / "inputs" / f"inputs_{y}.pkl", "rb"))
        table = pickle.load(open(bt / "out" / "prelook" / f"table_{y}.pkl", "rb"))
        rc = json.loads((bt / "out" / "prelook" / f"result_candidate_{y}.json").read_text(encoding="utf-8"))
        erp_s = rc["closure"]["erp_S"]
        an = anchors[y]
        rf_eff = max(an["rf"], an["gA"])
        by_cik = {nm["cik"]: nm for nm in d["pop"]}
        for r in table:
            if r["in_U"] and r["V_B"] is not None and r["V_B"] > 0 and r["V_S"] is not None and r["V_S"] > 0:
                nm = by_cik[r["cik"]]
                pool.append({"date": y, "cik": r["cik"], "nm": nm, "coe": nm["adjL"] * erp_s + rf_eff, "gA": an["gA"], "pi": an["pi"], "V_S": r["V_S"]})
    return pool


def to_inputs(sample):
    """The sample in the form `run` reads: each name-date's own inputs, its COE, gA, pi and the harness's recorded V_S."""
    out = []
    for p in sample:
        nm = {k: p["nm"].get(k) for k in ("rows", "L", "stub_months", "untagged", "dc_tags", "shares", "m", "sector", "y_L")}
        nm["untagged"] = sorted(nm["untagged"] or [])
        nm.update(coe=p["coe"], gA=p["gA"], pi=p["pi"], recorded_V_S=p["V_S"], date=p["date"])
        out.append(nm)
    return out


def engine_values(names, tree, bt_tree):
    """Revision 18's value for each name-date, the way production calls it: analyse + cash_term + terminal default + build."""
    ac.block_network()
    tree = Path(tree).resolve()
    sys.path.insert(0, str(tree / "tools"))
    import consensus_reference as cref
    import throughcycle_record as tcr
    assert tree in Path(cref.__file__).resolve().parents and hasattr(cref, "cash_term"), cref.__file__
    sys.path.insert(0, str(Path(bt_tree).resolve()))
    from backtest_phase2 import arms                      # only its input helpers (precheck, synthetic_estimates)
    res = []
    for nm in names:
        coe, ga, pi = nm["coe"], nm["gA"], nm["pi"]
        why, row_l, oe, rev = arms._precheck(nm)
        if why:
            res.append({"value": None, "reason": why})
            continue
        untagged = frozenset(nm.get("untagged") or ())
        rec = tcr.analyse(nm["rows"], coe, untagged_fields=untagged, base_year=nm["L"], debt_current_tags=nm.get("dc_tags") or {})
        cash = cref.cash_term(row_l, nm.get("y_L"), nm.get("sector"))
        tg = cref.terminal_growth_default(ga, pi, rec["g_rev"], None, nm["m"])[0]
        est = arms.synthetic_estimates(rev, float(row_l["net_income"]), nm["shares"], nm["m"])
        out = cref.build(oe, est, coe, tg, nm["shares"], nm["m"], stub_months=nm.get("stub_months"), anchor=ga, record=rec,
                         base_ni=tcr.adjusted_earnings(row_l, untagged), base_revenue=rev, cash=cash)
        res.append({"value": out.get("value"), "reason": out.get("reason")})
    return res


def compare(names, values, *, tol=0.005):
    bad = []
    for i, (nm, v) in enumerate(zip(names, values)):
        rec, got = nm["recorded_V_S"], v["value"]
        if got is None or not abs(got - rec) < tol:
            bad.append((i, nm.get("date"), rec, got, v.get("reason")))
    n = len(names)
    return {"at": "AT1c same as the tested design", "pass": n > 0 and not bad, "name_dates": n, "differences": len(bad), "details": bad[:20],
            "by_date": {y: sum(1 for nm in names if nm.get("date") == y) for y in sorted({nm.get("date") for nm in names})},
            "bar": f"|engine - V_S| < ${tol} on every name-date",
            "summary": f"{n - len(bad)} of {n} name-dates reproduce the harness's V_S to the cent; {len(bad)} differ"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--backtest", required=True, type=Path)
    d.add_argument("--out", required=True, type=Path)
    r = sub.add_parser("run")
    r.add_argument("--inputs", required=True, type=Path)
    r.add_argument("--tree", required=True, type=Path)
    r.add_argument("--bt-tree", required=True, type=Path)
    r.add_argument("--out", default=None, type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "draw":
        pool = load_pool(a.backtest)
        sample = draw_paired(pool)
        ac.write_result(a.out, to_inputs(sample))
        print("paired pool", len(pool), "drawn", len(sample), {y: sum(1 for p in sample if p["date"] == y) for y in YEARS})
        return 0
    names = json.loads(a.inputs.read_text(encoding="utf-8"))
    result = compare(names, engine_values(names, a.tree, a.bt_tree))
    result["inputs_sha256"] = ac.sha256_file(a.inputs)
    result["tree_commit"] = ac.git_head(a.tree)[0]
    return ac.finish(result, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
