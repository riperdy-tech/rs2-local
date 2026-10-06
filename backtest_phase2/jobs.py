"""The jobs an arm worker runs (arm_worker.py).  Each is `fn(arm, cref, tcr, job) -> dict`; the revision modules are the
caller's.  Nothing here reads a return.

  date_baseline   V_B at (rf_eff, ERP_B) and variant a (rf_eff := rf) for every name of one date           [baseline arm]
  date_candidate  variant b (ERP_B), the closure solve, V_S at ERP_S, and the C3 reduction values          [candidate arm]
  c2_production   the arm's `build` fed the production consensus inputs recorded in G's book run (C2)
  call            one named arm function on given synthetic inputs (the unit tests)
  probe           which files the worker actually loaded
"""
import json
import math
import pickle
from pathlib import Path

from . import arms, closure
from .common import is_num


def _coe(nm, rf_eff, erp):
    return arms.coe_of(nm["adjL"], rf_eff, erp)


def _slim(res):
    keep = {"value": res.get("value"), "reason": res.get("reason"), "coe": res.get("coe"), "tg": res.get("terminal_g")}
    for k in ("operating_base_not_positive", "cash", "interest_removed"):
        if k in res and res[k]:
            keep[k] = res[k]
    st = [s for s in (res.get("stamps") or []) if s in ("record_not_available", "long_run_floor", "operating_base_not_positive")
          or s.startswith("cash_term") or s.startswith("margin_rule")]
    if st:
        keep["stamps"] = st
    return keep


def _load_pop(job):
    with open(job["inputs"], "rb") as f:
        return pickle.load(f)


def date_baseline(arm, cref, tcr, job):
    d = _load_pop(job)
    rf, rf_eff, gA, pi = job["rf"], job["rf_eff"], job["gA"], job["pi"]
    coe_mkt = job["coe_mkt_B"]
    erp_B = arms.erp_from_market(coe_mkt, rf_eff)
    erp_a = coe_mkt - rf                      # variant a: production as it would have run at those rates (rf_eff := rf)
    out = {"B": {}, "a": {}, "erp_B": erp_B, "erp_a": erp_a}
    low_rate = {"coe_minus_g_lt_1pct": 0, "coe_le_g": 0, "n": 0}
    for nm in d["pop"]:
        tg = arms.baseline_terminal_growth(cref, gA, pi, nm.get("m"))
        out["B"][nm["cik"]] = _slim(arms.baseline_value(cref, nm, _coe(nm, rf_eff, erp_B), tg))
        coe_a = nm["adjL"] * erp_a + rf
        out["a"][nm["cik"]] = _slim(arms.baseline_value(cref, nm, coe_a, tg))
        if nm.get("in_U"):
            low_rate["n"] += 1
            low_rate["coe_minus_g_lt_1pct"] += int(coe_a - tg < 0.01)
            low_rate["coe_le_g"] += int(coe_a <= tg)
    out["variant_a_low_rate"] = low_rate
    return out


def date_candidate(arm, cref, tcr, job):
    d = _load_pop(job)
    rf, rf_eff, gA, pi = job["rf"], job["rf_eff"], job["gA"], job["pi"]
    coe_mkt = job["coe_mkt_B"]
    erp_B = arms.erp_from_market(coe_mkt, rf_eff)
    pop = d["pop"]
    byc = {nm["cik"]: nm for nm in pop}
    out = {"b": {}, "S": {}, "red": {}, "erp_B": erp_B}
    for nm in pop:
        out["b"][nm["cik"]] = _slim(arms.candidate_value(cref, tcr, nm, _coe(nm, rf_eff, erp_B), gA, pi))
    # the closure set C(T): aggregate constituents with a loading (every pop name has one) and a candidate value > 0 at ERP_B
    agg_ciks = {c["cik"] for c in d["agg"]["constituents"]}
    members = [c for c in sorted(agg_ciks) if c in byc and is_num(out["b"][c]["value"]) and out["b"][c]["value"] > 0
               and is_num(byc[c].get("shares")) and byc[c]["shares"] > 0]
    target = sum(byc[c]["cap"] for c in members)
    n_none = [0]

    def total_at(erp):
        tot = 0.0
        for c in members:
            nm = byc[c]
            v = arms.candidate_value(cref, tcr, nm, _coe(nm, rf_eff, erp), gA, pi)["value"]
            if v is None:
                n_none[0] += 1
                continue
            tot += max(v, 0.0) * nm["shares"]
        return tot

    erp_S, flag = closure.solve_erp(total_at, target)
    tot_S = total_at(erp_S)
    out["closure"] = {"erp_S": erp_S, "flag": flag, "members": len(members), "sum_cap": target, "sum_value_x_shares": tot_S,
                      "gap": closure.closure_gap(tot_S, target) if target > 0 else None, "none_evaluations": n_none[0],
                      "aggregate_constituents": len(agg_ciks), "aggregate_constituents_in_pop": sum(1 for c in agg_ciks if c in byc)}
    for nm in pop:
        out["S"][nm["cik"]] = _slim(arms.candidate_value(cref, tcr, nm, _coe(nm, rf_eff, erp_S), gA, pi))
    # C3: the candidate switched to the revision-16 arithmetic, at the baseline's rate
    red = arms.Switches(returns="inf", margin="none", cash=False, working_capital=False, terminal="gA", earnings_base="OE")
    for nm in pop:
        out["red"][nm["cik"]] = _slim(arms.candidate_value(cref, tcr, nm, _coe(nm, rf_eff, erp_B), gA, pi, sw=red))
    return out


def _enrich_estimates(root, ticker):
    p = Path(root) / "enrich" / f"{ticker}.json"
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            return (json.load(f) or {}).get("estimates")
    except (OSError, json.JSONDecodeError):
        return None


def c2_production(arm, cref, tcr, job):
    """C2: replay the recorded `build` calls of G's book run through the harness call sites; compare with the recorded value.
    The run's rows (rev16 b_old.json, rev17 b_new.json) hold every scalar input; the consensus estimates are read from the
    run's enrich cache."""
    rows = json.loads(Path(job["rows"]).read_text(encoding="utf-8"))["rows"]
    res, n_value, n_match, n_none_match, mism = {}, 0, 0, 0, []
    for t, r in sorted(rows.items()):
        ref = r.get("reference")
        if not ref:
            continue
        est = _enrich_estimates(job["enrich_root"], t)
        rec_v = ref.get("value")
        base_arg, coe, tg, shares, med = ref.get("base_arg"), ref.get("coe"), ref.get("terminal_g"), ref.get("shares"), ref.get("median_5y")
        da = capex = None
        if ref.get("method") == "levels" and ref.get("levels") and est:
            lv = (est.get("0y") or {}).get("eps", {}).get("avg")
            if is_num(lv) and is_num(shares):
                da, capex = ref["levels"][0] - lv * shares, 0.0      # only da - capex enters the levels method
        common = dict(base_cf=base_arg, estimates=est, coe=coe, terminal_g=tg, shares=shares, median_5y=med,
                      stub_months=ref.get("stub_months"), da=da, capex=capex, levels_reason=ref.get("levels_reason"))
        if arm == "baseline":
            out = arms.baseline_build(cref, **common)
        else:
            record = dict(r.get("record") or {})
            record["R"] = r.get("record_R_series")
            kw = dict(common, anchor=None, record=record, base_ni=ref.get("base_x"), base_revenue=ref.get("base_revenue"),
                      base_cap=ref.get("base_year_cap"))
            out = arms.candidate_build(cref, **kw)
            if out.get("value") != rec_v and ref.get("long_run_path") == "owner_earnings_ratio":
                out = arms.candidate_build(cref, **dict(kw, levels_block="the vendor's year-ago revenue does not match the filed revenue"))
        v = out.get("value")
        ok = (v is None and rec_v is None) or (v is not None and rec_v is not None and round(v, 2) == round(float(rec_v), 2))
        if rec_v is not None:
            n_value += 1
            n_match += int(ok)
        else:
            n_none_match += int(ok)
        if not ok:
            mism.append({"ticker_hash": abs(hash(t)) % 10 ** 6, "recorded": rec_v, "got": v})
        res[t] = {"recorded": rec_v, "got": v, "ok": ok}
    return {"names": len(res), "valued_recorded": n_value, "valued_match_to_the_cent": n_match,
            "no_value_recorded_and_no_value_got": n_none_match,
            "no_value_recorded": sum(1 for x in res.values() if x["recorded"] is None),
            "mismatches": mism[:50], "max_abs_diff_valued": max([abs(x["got"] - x["recorded"]) for x in res.values()
                                                                 if x["recorded"] is not None and x["got"] is not None] or [0.0])}


def call(arm, cref, tcr, job):
    """One arms.py function on given inputs: {"fn": name, "kwargs": {...}, "switches": {...}} (the unit tests)."""
    fn = job["fn"]
    kw = dict(job.get("kwargs") or {})
    if "switches" in job:
        kw["sw"] = arms.Switches(**job["switches"])
    if fn == "baseline_value":
        return {"result": arms.baseline_value(cref, **kw)}
    if fn == "candidate_value":
        return {"result": arms.candidate_value(cref, tcr, **kw)}
    if fn == "trend_level":
        untagged = frozenset(kw.get("untagged") or ())
        rec = tcr.analyse(kw["rows"], kw["coe"], untagged_fields=untagged, base_year=kw["L"], debt_current_tags={})
        return {"result": {"T_L": arms.trend_level(tcr, kw["rows"], rec, kw["L"], untagged), "om_basis": rec["om_basis"],
                           "om_years": rec["om_years"], "om_tc": rec["om_tc"], "om_L": rec["om_L"], "R_tc": rec["R_tc"], "p": rec["p"]}}
    if fn == "build":
        return {"result": (arms.baseline_build if arm == "baseline" else arms.candidate_build)(cref, **kw)}
    raise ValueError(fn)


def probe(arm, cref, tcr, job):
    return {"cref_file": cref.__file__, "tcr_file": tcr.__file__ if tcr else None}


def run(arm, cref, tcr, job):
    fn = {"date_baseline": date_baseline, "date_candidate": date_candidate, "c2_production": c2_production, "call": call,
          "probe": probe}[job["type"]]
    return fn(arm, cref, tcr, job)
