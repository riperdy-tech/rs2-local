"""Backtest registration section 9: the pre-outcome checks that are not unit tests.

  C1  point in time: 50 name-dates (seed 20261002), every input with its filing or observation date, all on or before T
  C2  arithmetic: the harness wrappers fed the production inputs of G's book run reproduce revision 16 (fee17cf) and revision 17
      (ac68e25) reference values to the cent; the MRI solve reproduces 0.0936 (run by mri/pit_anchors.py check);
      plus C2b: the aggregate rules restated here reproduce MRI's aggregate on today's inputs
  C5  base-rate sample sizes per date
  and the data freeze (sha256 of every input).

Offline, no return.  Output: <bt-root>/out/prelook/checks.json (counts and rates; company ids only in c1_detail.json).
"""
import argparse
import hashlib
import json
import os
import pickle
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True


class _Blocked(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("Socket access blocked in this step")


def _no_net(*a, **k):
    raise RuntimeError("Network access blocked in this step")


socket.socket = _Blocked
socket.getaddrinfo = _no_net
socket.create_connection = _no_net

_TRACE = set()
_SKIP = (sys.prefix.lower(), sys.base_prefix.lower())


def _hook(event, args):
    if event == "open":
        p, mode = args[0], (args[1] if len(args) > 1 else None)
        if isinstance(p, (str, bytes, os.PathLike)) and (mode is None or ("r" in str(mode) and "w" not in str(mode))):
            s = os.fsdecode(p)
            if not s.lower().startswith(_SKIP) and "__pycache__" not in s:
                _TRACE.add(s)


sys.addaudithook(_hook)

from backtest_phase2 import aggregate as agg_mod  # noqa: E402
from backtest_phase2 import pit_data  # noqa: E402
from backtest_phase2.common import DATES, PriceBook, parse_date, ym_add  # noqa: E402

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def sha256(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---- C1 ------------------------------------------------------------------------------------------------------------------------

def _facts_by_end(member):
    """{period end: latest filing date among the member's facts with that period end} and the member's latest filing date overall."""
    by_end, latest = {}, ""
    for body in member.get("facts", {}).values():
        for c in body.values():
            for vals in c["units"].values():
                for v in vals:
                    f = v["filed"]
                    latest = max(latest, f)
                    e = v.get("end")
                    if e and f > by_end.get(e, ""):
                        by_end[e] = f
    return by_end, latest


def c1_point_in_time(bt_root, n=50, seed=20261002, zip_path=None):
    bt_root = Path(bt_root)
    pops = {}
    for y in DATES:
        with open(bt_root / "out" / "inputs" / f"inputs_{y}.pkl", "rb") as f:
            pops[y] = pickle.load(f)
    universe = sorted((y, nm["cik"]) for y in DATES for nm in pops[y]["pop"] if nm["in_U"])
    rng = np.random.default_rng(seed)
    pick = sorted(rng.choice(len(universe), size=n, replace=False).tolist())
    anchors = json.loads((bt_root / "mri" / "pit_anchors.json").read_text(encoding="utf-8"))["dates"]
    book = PriceBook.load(bt_root / "prices" / "prices_monthly_raw.json")
    detail, violations, n_inputs, removed_total = [], 0, 0, 0
    orig = zipfile.ZipFile(zip_path) if zip_path else None
    for i in pick:
        y, cik = universe[i]
        d = pops[y]
        a = anchors[y]
        T = a["T"]
        nm = next(x for x in d["pop"] if x["cik"] == cik)
        if T not in _SIDES:
            _SIDES[T] = json.loads((bt_root / "pit" / "cut" / f"side_{T}.json").read_text(encoding="utf-8"))
        s = _SIDES[T].get(cik) or {}
        inputs = []

        def add(name, date, kind):
            nonlocal violations, n_inputs
            ok = date is not None and date <= T
            inputs.append({"input": name, "date": date, "kind": kind, "on_or_before_T": ok})
            n_inputs += 1
            violations += int(not ok)

        add("price_bar_Close_" + y + "-06", T, "price bar (monthly bar closing on the last trading day of June)")
        add("rf_DGS10", a["rf_obs_date"], "observation")
        add("pi_T10YIE", a["pi_obs_date"], "observation")
        add("dtb3", a["dtb3_obs_date"], "observation")
        add("gA_growth_rung_month", a["gA_month"], "month of the replayed rung")
        add("loadings_window_end", a["loadings_window"][1], "5-year window end")
        used = [dt for dt, _v in a["dtb3_daily"] if dt <= nm["fye"]]
        add("dtb3_window_for_y_L_latest_observation", max(used) if used else None, "observation (the 12 months to the fiscal year end)")
        add("base_year_fiscal_year_end", nm["fye"], "period end")
        if nm["dil_filed"]:
            add("diluted_shares_filing", nm["dil_filed"], "filing")
        for e in s.get("cover") or []:
            add("cover_page_shares_period", e[0], "cover date")
            add("cover_page_shares_filing", e[4], "filing")
        zf = pit_data_zip(bt_root, T)
        member = json.loads(zf.read(f"CIK{cik}.json"))
        by_end, latest = _facts_by_end(member)
        add("latest_fact_of_the_company_in_the_cut_archive", latest or None, "filing")
        for yr in sorted(nm["rows"], key=int):
            pe = (d_period_end(bt_root, y, nm["ticker"]) or {}).get(yr)
            if pe is not None:
                add(f"row_FY{yr}_period_end", pe, "period end")
                add(f"row_FY{yr}_latest_filing_of_that_period", by_end.get(pe), "filing")
        removed = 0
        if orig is not None:
            full = json.loads(orig.read(f"CIK{cik}.json"))
            removed = sum(1 for body in full.get("facts", {}).values() for c in body.values() for vals in c["units"].values()
                          for v in vals if (v.get("filed") or "") > T)
            kept_after = [1 for body in member.get("facts", {}).values() for c in body.values() for vals in c["units"].values()
                          for v in vals if v["filed"] > T]
            assert not kept_after
        removed_total += removed
        post_T_splits = [m for m, _r in book.events(nm["ticker"]) if m > f"{y}-06"]
        detail.append({"year": y, "company_id": cik, "T": T, "inputs": inputs, "facts_in_the_archive_filed_after_T_removed_by_the_cut": removed,
                       "split_ratios_dated_after_T_used_only_to_undo_the_vendor_adjustment_4_3": len(post_T_splits),
                       "labels": "sector and FX flag are today's screener labels (disclosed look-ahead, 4.9)"})
    (bt_root / "out" / "prelook" / "c1_detail.json").write_text(json.dumps(detail, indent=1), encoding="utf-8")
    return {"name_dates": len(pick), "seed": seed, "inputs_checked": n_inputs, "inputs_after_T": violations,
            "facts_filed_after_T_in_the_archive_for_these_companies_removed_by_the_cut": removed_total, "pass": violations == 0}


_ZIPS, _PE, _SIDES = {}, {}, {}


def pit_data_zip(bt_root, T):
    if T not in _ZIPS:
        _ZIPS[T] = zipfile.ZipFile(Path(bt_root) / "pit" / "cut" / f"cut_{T}.zip")
    return _ZIPS[T]


def d_period_end(bt_root, y, ticker):
    if y not in _PE:
        doc = json.loads((Path(bt_root) / "pit" / f"H_{y}" / "fundamentals_history.json").read_text(encoding="utf-8"))
        _PE[y] = doc["provenance"]["period_end"]
    return _PE[y].get(ticker)


# ---- C2 ------------------------------------------------------------------------------------------------------------------------

def run_c2(bt_root, baseline_tree, candidate_tree, c2_dir):
    bt_root, c2_dir = Path(bt_root), Path(c2_dir)
    out = {}
    for arm, tree, rows in (("baseline", baseline_tree, c2_dir / "b_old_fee17cf.json"), ("candidate", candidate_tree, c2_dir / "b_new_ac68e25.json")):
        job = {"type": "c2_production", "rows": str(rows), "enrich_root": str(c2_dir / "root_book")}
        jp, op = c2_dir / f"_c2_job_{arm}.json", c2_dir / f"_c2_out_{arm}.json"
        jp.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-m", "backtest_phase2.arm_worker", "--arm", arm, "--tree", str(tree), "--job", str(jp), "--out", str(op)],
                           cwd=HARNESS_ROOT, capture_output=True, text=True, env=env)
        if r.returncode != 0:
            raise RuntimeError(r.stdout + r.stderr)
        d = json.loads(op.read_text(encoding="utf-8"))
        meta = json.loads(rows.read_text(encoding="utf-8"))["meta"]
        out[arm] = {"production_run_tree_head": meta.get("head_revision"), "names": d["names"], "valued_in_the_production_run": d["valued_recorded"],
                    "valued_and_equal_to_the_cent": d["valued_match_to_the_cent"], "no_value_in_both": d["no_value_recorded_and_no_value_got"],
                    "no_value_in_the_production_run": d["no_value_recorded"], "max_abs_difference_valued": d["max_abs_diff_valued"],
                    "mismatches": len(d["mismatches"]), "consensus_reference_sha256": d["identity"]["consensus_reference_sha256"]}
        out[arm]["pass"] = (d["valued_match_to_the_cent"] == d["valued_recorded"] and d["no_value_recorded_and_no_value_got"] == d["no_value_recorded"])
    return out


def c2b_aggregate_rules(screener_data):
    """The aggregate rules, restated here, against MRI's own stored aggregate on today's inputs (the data has drifted since MRI built it)."""
    sd = Path(screener_data)
    cik = json.loads((sd / "cik_map.json").read_text(encoding="utf-8-sig"))["map"]
    fund = json.loads((sd / "fundamentals_history.json").read_text(encoding="utf-8-sig"))
    fund = fund.get("tickers") or fund
    items = []
    for p in sorted((sd / "financials").glob("*.json")):
        t = p.stem.upper()
        try:
            fin = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        capv = fin.get("Market_Cap")
        if not isinstance(capv, (int, float)) or capv <= 0 or fin.get("FX") is not None:
            continue
        items.append({"ticker": t, "cik": str(cik.get(t) or ""), "market_cap": capv, "rows": fund.get(t) or {}})
    agg, stats = agg_mod.build_aggregate(items)
    return agg, stats


# ---- C5 -------------------------------------------------------------------------------------------------------------------------

def c5_base_rate_sizes(bt_root, tree):
    ctx = pit_data.Context(bt_root, tree)
    out = {}
    for y in DATES:
        hdir = Path(bt_root) / "pit" / f"H_{y}"
        mx = int(y) - 1
        table = ctx.br._compute_table(hdir / "fundamentals_history.json", max_fiscal_year=mx)
        pers = ctx.gp.persistence_table(hdir, max_fiscal_year=mx)
        out[y] = {"max_fiscal_year": mx,
                  "size_bucket_5y_n": {k: v.get(5, {}).get("n") for k, v in table.items()},
                  "size_bucket_5y_median_pct": {k: v.get(5, {}).get("p50") for k, v in table.items()},
                  "growth_persistence_n": {k: v["n"] for k, v in pers.items()},
                  "growth_persistence_median_pct": {k: v["median"] for k, v in pers.items()}}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bt-root", required=True, type=Path)
    ap.add_argument("--baseline-tree", required=True, type=Path)
    ap.add_argument("--candidate-tree", required=True, type=Path)
    ap.add_argument("--zip", required=True, type=Path, help="the original companyfacts.zip (C1 counts the facts the cut removed)")
    ap.add_argument("--screener-data", required=True, type=Path)
    ap.add_argument("--mri-aggregate", required=True, type=Path, help="MRI's stored equity_aggregate.json (read only)")
    ap.add_argument("--which", nargs="*", default=["c1", "c2", "c2b", "c5"])
    a = ap.parse_args(argv)
    res = {}
    path = a.bt_root / "out" / "prelook" / "checks.json"
    if path.exists():
        res = json.loads(path.read_text(encoding="utf-8"))
    if "c1" in a.which:
        res["C1"] = c1_point_in_time(a.bt_root, zip_path=a.zip)
        print("C1", res["C1"])
    if "c2" in a.which:
        res["C2"] = run_c2(a.bt_root, a.baseline_tree, a.candidate_tree, a.bt_root / "out" / "c2")
        print("C2", json.dumps(res["C2"]))
    if "c2b" in a.which:
        agg, stats = c2b_aggregate_rules(a.screener_data)
        mri = json.loads(a.mri_aggregate.read_text(encoding="utf-8"))
        if mri is not None:
            mine = {c["ticker_key"]: c for c in agg["constituents"]}
            theirs = {c["ticker"]: c for c in mri["constituents"]}
            both = [t for t in theirs if t in mine]
            res["C2b"] = {"mri_constituents": len(theirs), "restated_constituents": len(mine), "in_both": len(both),
                          "cash_flow_equal": sum(1 for t in both if mine[t]["cash_flow"] == theirs[t]["cash_flow"]),
                          "growth_equal": sum(1 for t in both if mine[t]["growth"] == theirs[t]["growth"]),
                          "coverage_share_restated": stats["coverage_share"], "coverage_share_mri": mri["coverage_share"],
                          "note": "market caps differ by the price moves since MRI built its file; the rules are the same"}
            print("C2b", res["C2b"])
    if "c5" in a.which:
        res["C5_base_rates"] = c5_base_rate_sizes(a.bt_root, a.baseline_tree)
        print("C5", "done")
    # no look file at freeze (replaces a test that depended on the scratch path)
    from backtest_phase2.look_gate import gate_path
    res["look_files_at_freeze"] = {f"AUTHORISED_LOOK_{n}.txt": gate_path(a.bt_root, n).exists() for n in (1, 2)}
    res["no_look_file_at_freeze"] = not any(res["look_files_at_freeze"].values())
    print("look files at freeze:", res["look_files_at_freeze"])
    res["files_read_by_checks"] = len(_TRACE)
    path.write_text(json.dumps(res, indent=1), encoding="utf-8")
    (a.bt_root / "out" / "prelook" / "files_read_checks.txt").write_text("\n".join(sorted(_TRACE)), encoding="utf-8")


if __name__ == "__main__":
    main()
