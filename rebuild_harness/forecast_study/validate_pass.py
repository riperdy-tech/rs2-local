"""Check that the pass-1 forecast arithmetic equals the engines' own `forecast_year1` (the code's year-1 input as H3 scored it) on a sample of real names at one origin date.

    python -m rebuild_harness.forecast_study.validate_pass --out OUT.json [--date 2022-06-30] [--limit-ciks 500]

Uses the same state, industry medians and `PopulationPriors.for_company` as the pass; compares P10 / P50 / P90 of growth, margin and ROTE with `engine_operating.forecast_year1` /
`engine_financial.forecast_year1`.  No outcome is read."""
import argparse
import json
from pathlib import Path

from valuation import common as vc
from valuation import engine_financial, engine_operating, gate1
from valuation.discount_rate import MriRiskFree
from rebuild_harness import gate1_run as g1r
from rebuild_harness.stage2 import obs as s2obs
from rebuild_harness.forecast_study import pass_priors as pp


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--date", default="2022-06-30")
    ap.add_argument("--limit-ciks", type=int, default=500)
    a = ap.parse_args(argv)
    d = a.date
    cfg = s2obs.build_cfg(a.out.parent, [d], a.limit_ciks)
    cfg.update(survivorship_cover=None, delisting_index=None, delisting_docs=None)
    s2obs._init(cfg)
    pit, priors = g1r._ENV["pit"], g1r._ENV["priors"]
    g_term = vc.terminal_growth_rate(MriRiskFree()(d)[0])
    keep, rows, prev = [], [], None
    for cik in cfg["ciks"]:
        if prev is not None:
            pit.evict(prev)
        prev = cik
        snap = pit.snapshot(cik, d)
        if snap is None or not snap.years:
            continue
        key, mc, _ = g1r._best_ticker(pit, cik, d)
        if mc["price"] is None or mc["market_cap"] is None:
            continue
        prep, s = pp.prepare_state(d, cik, pit, key)
        if prep is None:
            continue
        rows.append({"industry": prep["industry"], "family": prep["family"], "roic3": prep["st"].get("roic3"), "rote3": prep["st"].get("rote3")})
        if mc["market_cap"] >= gate1.MCAP_FLOOR and prep["family"] in ("operating", "financial"):
            keep.append((cik, prep))
    ctx = gate1.DateContext.build(d, MriRiskFree()(d)[0], rows)
    res = {"date": d, "g_term": g_term, "n": 0, "max_abs_diff": {}, "compared": {}, "no_engine_forecast": 0}
    for cik, prep in keep:
        st, fam = prep["st"], prep["family"]
        ir = ctx.industry_return(prep["industry"], fam)
        if ir is not None:
            st["industry_roic" if fam != "financial" else "industry_rote"] = ir
        ps = priors.for_company(fam, st, d)
        if ps.source == "UNAVAILABLE":
            continue
        mine = pp.forecasts(fam, st, ps, g_term)
        try:
            if fam == "operating":
                if not all(k in ps.inputs for k in ("g1", "margin_target")) or "margin_retention" not in ps.curves or "growth_decay" not in ps.curves or st.get("op_margin") is None:
                    res["no_engine_forecast"] += 1
                    continue
                eng = engine_operating.forecast_year1(st, ps.inputs, ps.curves, g_term)
                pairs = [("growth", "growth_1", eng["growth"]), ("margin", "margin_1", eng["margin"])]
            else:
                if not all(k in ps.inputs for k in ("g1", "rote_target")) or "rote_retention" not in ps.curves or "excess_fade" not in ps.curves or st.get("industry_rote") is None \
                        or st.get("rote_latest") is None:
                    res["no_engine_forecast"] += 1
                    continue
                eng = engine_financial.forecast_year1(st, ps.inputs, ps.curves)
                pairs = [("rote", "rote_1", eng["rote"]), ("rote_normalized", "rote_norm_1", eng["rote_normalized"])]
        except Exception as e:
            res.setdefault("engine_errors", []).append(f"{cik}: {type(e).__name__}: {str(e)[:80]}")
            continue
        res["n"] += 1
        for name, mk, ev in pairs:
            for lv in ("p10", "p50", "p90"):
                if mk not in mine:
                    res.setdefault("missing_in_pass", {}).setdefault(mk, 0)
                    res["missing_in_pass"][mk] += 1
                    break
                diff = abs(mine[mk][lv] - ev[lv])
                key = f"{fam}.{name}.{lv}"
                res["max_abs_diff"][key] = max(res["max_abs_diff"].get(key, 0.0), diff)
                res["compared"][key] = res["compared"].get(key, 0) + 1
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
