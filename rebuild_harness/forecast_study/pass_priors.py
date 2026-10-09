"""Forecast-study pass 1 (Addendum Z 5, 6): the gate-1 universe at one origin date a year, and what the CODE would forecast for each name there.

    python -m rebuild_harness.forecast_study.pass_priors --out-dir OUT --dates 2016-06-30 ... [--workers 2] [--limit-ciks N]

Per origin date T it follows the registered gate-1 pass 1 (`stage2.obs.prepare_light`: the same companies, price, market capitalisation, strict SIC as filed, classification and state) and keeps, for
every operating and financial name of market cap >= $300M (commodity is out of scope, V3), the engine's own year-1..3 forecasts at the prior's P10 / P50 / P90:
  * growth_t        g_T + (g_1 - g_T) d_t           (revenue growth; for the financial family the growth of tangible book, the engine's g1)
  * margin_t        m_0 + (m_5 - m_0) w_t           operating family, the engine's chain (needs the vintage's margin_target); `margin_curve_t` is the same path with the residual median dropped, i.e. the
                                                    measured retention only (med8 + r_t x dev), which the vintage supports in years the residual table does not (n < 50)
  * rote_t / rote_norm_t   the financial engine's ROTE after and before the fade toward the industry median (`rote_curve_t`: retention only)
It uses `common.build_state` and `PopulationPriors.for_company` exactly as `gate1.value_company` does, with the date's industry medians from a `DateContext` built on every prepared name of the date.

NO OUTCOME IS READ, NO RETURN, NO CENSUS (the survivorship census looks at delistings after T, which is information the study may not use).  A valuation date after 2024-06-30 is refused here (the
study's information stops at 2024-12-31 and the outcome of a year-1 forecast is filed after the base year).  CPU only, no network."""
import argparse
import gzip
import json
import math
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

from valuation import common as vc
from valuation import gate1
from valuation.common import build_state
from valuation import classification
from valuation.discount_rate import MriRiskFree
from valuation import pit_adapter
from rebuild_harness import gate1_run as g1r
from rebuild_harness.stage2 import obs as s2obs

FLOOR = gate1.MCAP_FLOOR
LAST_ORIGIN = "2024-06-30"
KS = (1, 2, 3)
LEVELS = (0.10, 0.50, 0.90)


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _lv(f):
    return {f"p{int(round(p * 100))}": _num(f(p)) for p in LEVELS}


def forecasts(family, st, ps, g_term):
    """The engine's year-1..3 forecast quantiles for one name from its PriorSet (absent for what the prior does not supply).  Pure arithmetic on the PriorSet and the state."""
    out = {}
    cur, dist = ps.curves, ps.inputs
    gd = cur.get("growth_decay")
    if gd is not None and "g1" in dist:
        for t in KS:
            d_t = gd.at(t)
            out[f"growth_{t}"] = _lv(lambda p: g_term + (dist["g1"].ppf(p) - g_term) * d_t)
    N = len(gd) if gd is not None else None
    meta_f = ps.meta.get("features") or {}
    if family == "operating":
        mr = cur.get("margin_retention")
        m0 = st.get("op_margin")
        if mr is not None and N is not None and m0 is not None:
            wm, _ = vc.level_path_weights(mr, N)
            med8, dev = meta_f.get("med8"), meta_f.get("dev")
            centre = med8 if (med8 is not None and dev is not None) else m0
            m5c = centre + mr.at(5) * (0.0 if dev is None else dev)
            for t in KS:
                out[f"margin_curve_{t}"] = {"p50": _num(m0 + (m5c - m0) * wm[t - 1])}
                if "margin_target" in dist:
                    out[f"margin_{t}"] = _lv(lambda p: m0 + (dist["margin_target"].ppf(p) - m0) * wm[t - 1])
            out["margin_ret"] = {f"r{t}": mr.at(t) for t in (1, 2, 3, 5)}
    else:
        rho, phi = cur.get("rote_retention"), cur.get("excess_fade")
        R0 = st.get("rote_latest")
        ind = (st.get("industry_rote") or {}).get("value")
        if rho is not None and R0 is not None:
            med8 = meta_f.get("rote_med8")
            centre = med8 if med8 is not None else R0
            for t in KS:
                out[f"rote_norm_curve_{t}"] = {"p50": _num(centre + (R0 - centre) * rho.at(t))}
                if "rote_target" in dist:
                    out[f"rote_norm_{t}"] = _lv(lambda p: dist["rote_target"].ppf(p) + (R0 - dist["rote_target"].ppf(p)) * rho.at(t))
                if phi is not None and ind is not None:
                    out[f"rote_curve_{t}"] = {"p50": _num(ind + ((centre + (R0 - centre) * rho.at(t)) - ind) * phi.at(t))}
                    if "rote_target" in dist:
                        out[f"rote_{t}"] = _lv(lambda p: ind + ((dist["rote_target"].ppf(p) + (R0 - dist["rote_target"].ppf(p)) * rho.at(t)) - ind) * phi.at(t))
            out["rote_ret"] = {f"rho{t}": rho.at(t) for t in (1, 2, 3)}
            if phi is not None:
                out["rote_ret"].update({f"phi{t}": phi.at(t) for t in (1, 2, 3)})
    return out


def prepare_state(d, cik, pit, key):
    """Adaptation, classification and state, as `gate1.prepare` does them (without packing the company)."""
    ar = pit_adapter.adapt(pit, cik, d, ticker=key)
    if not ar.ok:
        return None, "refused:" + ";".join(r.split(":")[0] for r in ar.refusals)[:60]
    p = ar.company
    cl = classification.classification(p.ticker, p.asof, p)
    fam = cl["family"]
    if fam is None:
        return None, "unclassifiable"
    if fam == "family_not_built":
        return None, "family_not_built"
    st = build_state(p)
    return {"family": fam, "industry": ar.industry, "st": st}, "prepared"


def pass_date(d):
    if d > LAST_ORIGIN:
        raise RuntimeError(f"refused: origin {d} is after {LAST_ORIGIN}")
    cfg = g1r._ENV["cfg"]
    pit, priors = g1r._ENV["pit"], g1r._ENV["priors"]
    rf = MriRiskFree()(d)[0]
    g_term = vc.terminal_growth_rate(rf)
    t0 = time.time()
    keep, ctx_rows, status = [], [], {}
    prev = None
    for cik in cfg["ciks"]:
        if prev is not None:
            pit.evict(prev)
        prev = cik
        snap = pit.snapshot(cik, d)
        if snap is None or not snap.years:
            status["refused:no_annual_report"] = status.get("refused:no_annual_report", 0) + 1
            continue
        key, mc, _ = g1r._best_ticker(pit, cik, d)
        if mc["price"] is None:
            status["refused:no_price"] = status.get("refused:no_price", 0) + 1
            continue
        if mc["market_cap"] is None:
            status["refused:market_cap_unavailable"] = status.get("refused:market_cap_unavailable", 0) + 1
            continue
        prep, s = prepare_state(d, cik, pit, key)
        status[s] = status.get(s, 0) + 1
        if prep is None:
            continue
        st = prep["st"]
        ctx_rows.append({"industry": prep["industry"], "family": prep["family"], "roic3": st.get("roic3"), "rote3": st.get("rote3")})
        if mc["market_cap"] < FLOOR or prep["family"] == "commodity":
            continue
        keep.append({"cik": cik, "ticker": key, "mcap": mc["market_cap"], "price": mc["price"], "family": prep["family"], "industry": prep["industry"],
                     "base_fye": snap.L_fye, "base_age_months": (g1r.pdm.to_date(d) - g1r.pdm.to_date(snap.L_fye)).days / 30.4375, "st": st})
    if prev is not None:
        pit.evict(prev)
    ctx = gate1.DateContext.build(d, rf, ctx_rows)
    rows = []
    for k in keep:
        st, fam = k.pop("st"), k["family"]
        ir = ctx.industry_return(k["industry"], fam)
        if ir is not None:
            st["industry_roic" if fam != "financial" else "industry_rote"] = ir
        rec = dict(k, date=d, g_term=g_term)
        try:
            ps = priors.for_company(fam, st, d)
        except Exception as e:                       # a failure is stated on the record
            rec["error"] = f"{type(e).__name__}: {str(e)[:160]}"
            rows.append(rec)
            continue
        rec["prior_source"] = ps.source
        rec["vintage"] = ps.meta.get("vintage")
        rec["unavailable"] = [u[:140] for u in ps.meta.get("unavailable", [])]
        rec["fallbacks"] = [u[:140] for u in ps.meta.get("fallbacks", [])]
        rec["features"] = {a: (_num(b) if not isinstance(b, (bool, str)) else b) for a, b in (ps.meta.get("features") or {}).items() if not isinstance(b, (dict, list))}
        rec["state"] = {a: _num(st.get(a)) for a in ("revenue", "op_margin", "op_margin_median", "growth_latest", "rote_latest", "rote_median", "tbv", "roic3", "rote3")}
        rec["cyc"] = {"score": ps.meta.get("cyc_score"), "basis": ps.meta.get("cyc_score_basis")}
        rec["mech"] = {a: (_num(b) if not isinstance(b, (dict, str)) else None) for a, b in (ps.meta.get("mechanical_baseline") or {}).items()}
        rec["cells"] = {a: {kk: vv for kk, vv in b.items() if isinstance(vv, (int, float, str, bool, type(None)))} for a, b in (ps.meta.get("cells") or {}).items() if a in ("g1", "margin_target")}
        rec["inputs"] = {a: {f"p{int(p * 100)}": _num(v.ppf(p)) for p in (0.1, 0.5, 0.9)} for a, v in ps.inputs.items()}
        rec["forecast"] = forecasts(fam, st, ps, g_term) if ps.source != "UNAVAILABLE" else {}
        if ir is not None:
            rec["industry_return"] = {"value": ir["value"], "n": ir["n"], "basis": ir["basis"]}
        rows.append(rec)
    out_dir = Path(cfg["out_dir"])
    tmp = out_dir / f"pass_{d}.jsonl.gz.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(g1r._clean(r)) + "\n")
    tmp.replace(out_dir / f"pass_{d}.jsonl.gz")
    pit.drop_cache()
    return {"date": d, "rows": len(rows), "status": status, "seconds": round(time.time() - t0)}


def _work(d):
    try:
        return pass_date(d)
    except Exception as e:
        import traceback
        return {"date": d, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--dates", nargs="*", required=True)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--limit-ciks", type=int)
    a = ap.parse_args(argv)
    if any(d > LAST_ORIGIN for d in a.dates):
        ap.error(f"refused: origins after {LAST_ORIGIN}")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    todo = [d for d in a.dates if not (a.out_dir / f"pass_{d}.jsonl.gz").exists()]
    cfg = s2obs.build_cfg(a.out_dir, a.dates, a.limit_ciks)
    cfg.update(survivorship_cover=None, delisting_index=None, delisting_docs=None)       # no census: it looks at delistings after T
    t0 = time.time()
    with Pool(a.workers, initializer=s2obs._init, initargs=(cfg,)) as pool:
        for s in pool.imap_unordered(_work, todo):
            print(datetime.now().strftime("%H:%M"), f"{time.time() - t0:.0f}s", json.dumps(s)[:600], flush=True)
    print("done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
