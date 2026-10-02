"""Revision 19, bar P3 (brief_rev19.md section 4): the replays of frozen runs through revision 19's code. OFFLINE: sockets are blocked, nothing is
written, no model and no GPU is used.

  python p3_replays.py --tree <rs2 tree> --sp <scratchpad> [--json]

(a) the label code. Every sample of the frozen runs (the six AT10 samples under SP/gpu_r18/tree, the final test's twelve under SP/final/tree) goes
    through contract_fill.fill with its recorded answer calls, which carry no crux: the label is hold, a sample whose recorded label was directional
    carries no_valid_crux:missing, direction_m equals the recorded label; at the verdict level (band_verdict over the rebuilt doc) every direction is
    hold and direction_m equals the published direction.
(b) the desk. The six AT10 answer calls are replayed through the desk, the context rebuilt from each run's _pack_facts.json at its recorded price,
    with rf_eff and nominal_gdp_trend from the AT10 anchor pins. The recorded Base is reproduced to the cent, except where fix items 2 and 3 change
    it (the held years 1-2 of MPWR sample 2, the refusal of MU sample 2's excess_cash). Each price_implied value reproduces the price within $0.01
    or is not reachable with its bound.
Aggregates and development names only (UGI, MPWR, MU, and the final test's six names); the 167 names are never opened.
"""
import argparse
import copy
import json
import os
import socket
import sys
from pathlib import Path

RF_EFF_AT10 = 0.0501            # the AT10 anchor pins (cost_of_capital_anchor 6242fe92, long_run_growth_anchor ff7d5a1f)
NOMINAL_GDP_TREND_AT10 = 0.0446


def block_network():
    def _blocked(*a, **k):
        raise RuntimeError("network blocked in this step")
    socket.socket.connect = _blocked
    socket.getaddrinfo = _blocked
    socket.create_connection = _blocked


def bootstrap(tree, sp):
    """Put the tree's modules on the path with the data roots pinned to the scratchpad copies (read only), and block the network."""
    tree, sp = Path(tree).resolve(), Path(sp).resolve()
    mri = sp / "backtest" / "out" / "c2" / "mri"
    os.environ["SCREENER_DATA_DIR"] = str(sp / "sd_full")
    os.environ["MRI_OUTPUTS_DIR"] = str(mri)
    os.environ["MRI_ANCHORS_DIR"] = str(mri)
    for p in (str(tree), str(tree / "tools"), str(tree / "tools" / "audit_202608")):
        if p not in sys.path:
            sys.path.insert(0, p)
    block_network()


def run_dirs(root):
    base = Path(root) / "ab_reports" / "consensus"
    return sorted(d for d in base.iterdir() if d.is_dir() and (d / "consensus.json").exists())


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _calls(d, run):
    """The sample's snapshot calls, from the folder the run itself used (the retry folder when the sample was retried)."""
    i = run["sample"]
    first, retry = d / f"sample{i}_research", d / f"sample{i}_research_retry"
    order = (retry, first) if run.get("sample_retried") else (first, retry)
    for folder in order:
        f = folder / "_research_snapshot.json"
        if f.exists():
            return _load(f).get("calls") or []
    return None


def replay_labels(sp_root):
    """P3 (a) over one frozen tree: [{run, samples: [{sample, recorded, label, direction_m, stamps}], verdict: {direction, direction_m, published, crux_valid}}]."""
    import consensus_valuation as cv
    import contract_fill
    import depth_pipeline as dp
    import pack_facts
    dp._prior_verdict = lambda *a, **k: None                          # the ledger is never read
    out = []
    for d in run_dirs(sp_root):
        doc = _load(d / "consensus.json")
        facts = _load(d / "_pack_facts.json")
        pack = (d / "_pack.md").read_text(encoding="utf-8")
        t = doc["ticker"]
        price = doc["price"]
        doc2 = copy.deepcopy(doc)
        rows = []
        for r in doc2["runs"]:
            calls = _calls(d, r)
            if calls is None:
                continue
            sc = r.get("scorecard") or {}
            recorded = sc.get("verdict_label")
            filled, prov = contract_fill.fill(calls, sc, facts, price, ticker=t, allow_blend=not pack_facts.is_revision_15(pack), pack_text=pack, company=t)
            sc.update(filled)
            r["scorecard"] = sc
            rows.append({"sample": r["sample"], "recorded": recorded, "label": filled.get("verdict_label"), "direction_m": filled.get("direction_m"),
                         "stamps": (filled.get("crux_check") or {}).get("stamps"), "reason": (filled.get("crux_check") or {}).get("reason")})
        _medoid, summary = cv.select_medoid_scorecard(doc2["runs"], price=price, eff_tol=doc2.get("effective_tolerance_pct") or cv.TOL_PCT)
        doc2["scorecard"] = summary
        v = dp.band_verdict(doc2)
        pub = d / "verdict_depth.json"
        published = _load(pub).get("direction") if pub.exists() else None
        out.append({"run": t, "samples": rows, "verdict": {"direction": v["direction"], "direction_m": v["direction_m"], "published": published,
                                                         "crux_valid": v["crux_valid"], "flags": [f for f in v["flags"] if f.startswith("no_valid_crux")]}})
    return out


def _num_b(x):
    return None if x is None else (x / 1e9 if abs(x) > 1e6 else x)


def desk_context(facts, price, rf_eff=RF_EFF_AT10, gdp=NOMINAL_GDP_TREND_AT10):
    """The desk context the harness builds from a run's facts (consensus_valuation.main's), with the two anchor facts of FACTS_VERSION 7 given."""
    return {"price": price, "shares_default_b": _num_b(facts["shares_default"]), "coe_anchor": facts["coe_anchor"],
            "terminal_g_default": facts["terminal_g_default"], "terminal_g_anchor": facts["terminal_g_anchor"],
            "base_rate_table": facts.get("base_rate_5y") or None, "revenue_cagr_5y_pct": facts.get("revenue_cagr_5y_pct"),
            "net_debt_default_b": facts.get("net_debt_b"), "interest_expense_latest_b": facts.get("interest_expense_latest_b"),
            "owner_earnings_default_b": facts.get("owner_earnings_default_b"), "base_window": facts.get("base_window"),
            "consensus_implied_value": facts.get("consensus_implied_value"), "levels": facts.get("levels"),
            "terminal_ronic": facts.get("terminal_ronic"), "long_run": facts.get("long_run"), "working_capital": facts.get("working_capital"),
            "cash_basis_b": facts.get("cash_basis_b"), "reference_base_b": facts.get("reference_base_b"), "excess_cash": facts.get("excess_cash"),
            "base_year_cash_and_investments_b": facts.get("base_year_cash_and_investments_b"), "reference_status": facts.get("reference_status"),
            "years35_cap": facts.get("next_fy_revenue_growth"), "shares_warning": facts.get("shares_warning"), "rf_eff": rf_eff,
            "nominal_gdp_trend": gdp}


def replay_desk(sp_root):
    """P3 (b): [{run, sample, status, price, recorded_base, desk, error, held, price_implied}] for each answer call of the AT10 runs."""
    import contract_fill
    import financial_model_tool as fmt
    rows = []
    for d in run_dirs(sp_root):
        facts = _load(d / "_pack_facts.json")
        cons = _load(d / "consensus.json")
        ctx = desk_context(facts, cons["price"])
        for r in cons["runs"]:
            calls = _calls(d, r)
            if calls is None:
                continue
            done = [c for c in calls if contract_fill.completed(c)]
            ans = next((c for c in reversed(done) if {"base", "bull", "bear"} <= {e["role"] for e in contract_fill.entries(c)}), None)
            if ans is None:
                continue
            rec_base = next(e["dcf"]["per_share_iv"] for e in contract_fill.entries(ans) if e["role"] == "base")
            res = fmt.execute_financial_model(copy.deepcopy(ans["params"]), dict(ctx))
            base = None if res.get("error") else next(s["dcf"] for s in res["scenario_dcfs"] if fmt._role_of(s["name"]) == "base")
            rows.append({"run": cons["ticker"], "sample": r["sample"], "status": facts.get("reference_status"), "price": cons["price"],
                         "recorded_base": rec_base, "desk": None if base is None else base["per_share_iv"], "error": res.get("error"),
                         "held": None if base is None else "years12_held_by_desk" in (base.get("stamps") or []),
                         "price_implied": res.get("price_implied")})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--sp", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    bootstrap(a.tree, a.sp)
    sp = Path(a.sp)
    result = {"labels_at10": replay_labels(sp / "gpu_r18" / "tree"), "labels_final": replay_labels(sp / "final" / "tree"),
              "desk_at10": replay_desk(sp / "gpu_r18" / "tree")}
    print(json.dumps(result, indent=None if a.json else 1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
