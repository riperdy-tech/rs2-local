"""Is each chosen same-filing revenue figure the TOTAL revenue (AK.39; the review's partial-line point)?  For every q1 row of the version of record:
  dominance   two or more revenue tags present for both periods in the filing, the chosen one the largest (a total dominates its lines)
  closure     in the SAME filing, same unit, both periods, within 1% of revenue:
                (a) GrossProfit + cost of revenue (CostOfRevenue | CostOfGoodsAndServicesSold | CostOfGoodsSold) = revenue, or
                (b) revenue - CostsAndExpenses = OperatingIncomeLoss
              (a derived Q4 is tested on its 10-K's fiscal-year pair)
  closure_fail  a closure test exists and fails: evidence of a partial line
  unverified  no test available
Reads the raw companyfacts zip (the store keeps only the extractor's tags).   python revenue_scope_check.py TC_OUTCOMES COMPANYFACTS_ZIP OUT"""
import json
import sys
import zipfile
from pathlib import Path

DEV = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-gate2-dev")
sys.path.insert(0, str(DEV))
from rebuild_harness.gate2 import same_filing as sf  # noqa: E402

COST = ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")
TOL = 0.01


def raw_rows(cf, tag, unit):
    out = []
    for r in (((cf.get("facts") or {}).get("us-gaap") or {}).get(tag) or {}).get("units", {}).get(unit, []):
        if r.get("start") and r.get("end") and r.get("val") is not None:
            out.append({"taxo": "us-gaap", "tag": tag, "unit": unit, "start": r["start"], "end": r["end"], "val": float(r["val"]), "accn": r["accn"],
                        "filed": r["filed"], "form": r["form"]})
    return out


def one(cf, tags, unit, accn, end, rng):
    for t in tags:
        p = sf.pairs_in_filing(raw_rows(cf, t, unit), accn, end, rng)
        if p:
            return next(iter(p.values()))
    return None


def main():
    src, zp, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    z = zipfile.ZipFile(zp)
    names = set(z.namelist())
    res = {"n": 0, "dominance": 0, "closure": 0, "closure_fail": 0, "unverified": 0, "rows": []}
    for line in src.read_text(encoding="utf-8").splitlines():
        o = json.loads(line)
        q = (o.get("quarters") or {}).get("q1") or {}
        t = (o.get("tag_consistent") or {}).get("q1") or {}
        if q.get("revenue_growth") is None or not (t.get("tags") or {}).get("revenue"):
            continue
        res["n"] += 1
        reg = (o["registered"]["quarters"] or {}).get("q1") or {}
        accn, end = reg.get("accession"), reg.get("period_end")
        _taxo, rtag, unit = t["tags"]["revenue"].split("/")
        kind = (t.get("kinds") or {}).get("revenue", t.get("kind"))
        ntags = len(((t.get("revenue_tags") or {}).get("tags") or {}))
        rec = {"key": o["key"], "ticker": o.get("ticker"), "tag": rtag, "n_revenue_tags": ntags, "kind": kind}
        if ntags >= 2:
            rec["status"] = "dominance"
        else:
            nm = f"CIK{str(o['cik']).zfill(10)}.json"
            cf = json.loads(z.read(nm)) if nm in names else {}
            rng = sf.QFY if kind == "derived_q4" else sf.Q3M
            rv = one(cf, (rtag,), unit, accn, end, rng)
            tests = {}
            if rv:
                gp, cost = one(cf, ("GrossProfit",), unit, accn, end, rng), one(cf, COST, unit, accn, end, rng)
                if gp and cost:
                    tests["gross_profit_plus_cost"] = all(rv[i] and abs((gp[i] + cost[i]) / rv[i] - 1) <= TOL for i in (0, 1))
                ce, oi = one(cf, ("CostsAndExpenses",), unit, accn, end, rng), one(cf, ("OperatingIncomeLoss",), unit, accn, end, rng)
                if ce and oi:
                    tests["revenue_minus_costs_equals_oi"] = all(rv[i] and abs((rv[i] - ce[i] - oi[i]) / rv[i]) <= TOL for i in (0, 1))
            rec["tests"] = tests
            rec["status"] = ("closure" if any(tests.values()) else "closure_fail") if tests else "unverified"
        res[rec["status"]] += 1
        res["rows"].append(rec)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    for r in res["rows"]:
        if r["status"] == "closure_fail":
            print("CLOSURE FAIL", r["key"], r["ticker"], r["tag"], r["kind"], r["tests"])


if __name__ == "__main__":
    main()
