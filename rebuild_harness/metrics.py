"""The metrics of SPEC section 6, as pure functions of record lists (no file, no price, no network; tested on synthetic data).

A record is one (valuation date, company) row:
    {"date": iso, "cik", "sector", "family", "price", "score": {engine: float|None}, "vp": {engine: value/price|None},
     "excess": {horizon months: excess total return over SPY | None},
     "base": {measure: value at the base year}, "out": {k: {measure: value as first filed in the k-th later year} | None},
     "forecasts": {engine: {k: {measure: value}} | None}}

Conventions:
  * Spearman IC: ties averaged (backtest_phase2.metrics); undefined (nan) below 3 observations or for a constant variable.
  * Percentile rank within a date: (average rank - 0.5) / n.  The pooled IC is the Spearman correlation of those within-date percentile ranks of the
    score and of the excess return over all dates' rows together.
  * Quintile spread: mean excess return of the top score quintile minus that of the bottom quintile on each date (ranks cut into five near-equal
    groups; a date needs at least `MIN_QUINTILE_N` names), averaged over dates.
  * Sector-neutral IC: within a date, percentile ranks of score and excess are demeaned inside each sector group of at least `MIN_SECTOR_N` names; the
    Pearson correlation of the demeaned ranks is that date's IC.
  * Incremental information over the yardsticks, on the names that have the engine AND every yardstick: (a) residual IC - the engine's percentile rank
    regressed on the yardsticks' percentile ranks (OLS with intercept, per date), the Spearman correlation of the residual with the excess return;
    (b) the Fama-MacBeth coefficient - per date OLS of the excess return's percentile rank on the engine's and the yardsticks' percentile ranks, the mean
    coefficient on the engine's rank, with its t statistic over dates.
  * Value/price distribution: shares below 0.4x and above 2.5x, overall and by family; the lift of each family among the extremes (its share of the
    extreme names over its share of all valued names) and Cramer's V of family against extreme.
  * Forecast error against a naive forecast (the last filed value of the base year): revenue on the log ratio, the rest on the difference; skill
    = 1 - MAE(engine) / MAE(naive).  Outcomes are the first-filed values of the k-th later fiscal year.
  * Intervals: bootstrap over valuation dates (resample dates with replacement), 5th to 95th percentile, `N_RESAMPLES` resamples, seed `SEED`.
"""
import math
from collections import OrderedDict, defaultdict

import numpy as np

from backtest_phase2.metrics import rankdata_avg, spearman

SEED = 20261006
N_RESAMPLES = 2000
MIN_IC_N = 10
MIN_QUINTILE_N = 25
MIN_SECTOR_N = 5
MIN_INCR_N = 30
VP_LOW, VP_HIGH = 0.4, 2.5
LOG_MEASURES = ("revenue",)


def pct_rank(x):
    x = np.asarray(x, dtype=float)
    return (rankdata_avg(x) - 0.5) / len(x) if len(x) else x


def by_date(records):
    out = OrderedDict()
    for r in sorted(records, key=lambda r: r["date"]):
        out.setdefault(r["date"], []).append(r)
    return out


def _pairs(recs, engine, h):
    """[(score, excess)] for the records that have both; the records themselves in the same order."""
    keep = [r for r in recs if (r["score"].get(engine) is not None) and (r["excess"].get(h) is not None)]
    return keep, np.array([r["score"][engine] for r in keep], dtype=float), np.array([r["excess"][h] for r in keep], dtype=float)


def _nanmean(v):
    v = [x for x in v if x == x]
    return float(np.mean(v)) if v else float("nan")


# ---- IC -----------------------------------------------------------------------------------------------------------------------------

def ic_by_date(rbd, engine, h, min_n=MIN_IC_N):
    """{date: (spearman IC, n)}; a date with fewer than `min_n` names has IC nan (its n is still reported)."""
    out = {}
    for d, recs in rbd.items():
        _k, s, e = _pairs(recs, engine, h)
        out[d] = (spearman(s, e) if len(s) >= min_n else float("nan"), int(len(s)))
    return out


def pooled_ic(rbd, engine, h, min_n=MIN_IC_N):
    xs, ys = [], []
    for d, recs in rbd.items():
        _k, s, e = _pairs(recs, engine, h)
        if len(s) >= min_n:
            xs.append(pct_rank(s))
            ys.append(pct_rank(e))
    if not xs:
        return float("nan"), 0
    x, y = np.concatenate(xs), np.concatenate(ys)
    return spearman(x, y), int(len(x))


# ---- quintiles ----------------------------------------------------------------------------------------------------------------------

def quintile_means(score, excess):
    """Mean excess return of each score quintile (lowest score first), or 5 nan under MIN_QUINTILE_N names."""
    n = len(score)
    if n < MIN_QUINTILE_N:
        return [float("nan")] * 5
    order = np.argsort(np.asarray(score, dtype=float), kind="mergesort")
    grp = np.empty(n, dtype=int)
    grp[order] = (np.arange(n) * 5) // n
    e = np.asarray(excess, dtype=float)
    return [float(e[grp == g].mean()) for g in range(5)]


def quintiles_by_date(rbd, engine, h):
    out = {}
    for d, recs in rbd.items():
        _k, s, e = _pairs(recs, engine, h)
        q = quintile_means(s, e)
        out[d] = {"quintiles": q, "spread": q[4] - q[0], "n": int(len(s))}
    return out


# ---- sector-neutral IC --------------------------------------------------------------------------------------------------------------

def sector_neutral_by_date(rbd, engine, h, min_n=MIN_IC_N):
    out = {}
    for d, recs in rbd.items():
        keep, s, e = _pairs(recs, engine, h)
        if len(s) < min_n:
            out[d] = (float("nan"), int(len(s)), 0)
            continue
        ps, pe = pct_rank(s), pct_rank(e)
        groups = defaultdict(list)
        for i, r in enumerate(keep):
            groups[r.get("sector") or "unknown"].append(i)
        xs, ys = np.zeros(len(s)), np.zeros(len(s))
        used = np.zeros(len(s), dtype=bool)
        for _g, ix in groups.items():
            if len(ix) < MIN_SECTOR_N:
                continue
            ix = np.array(ix)
            xs[ix], ys[ix] = ps[ix] - ps[ix].mean(), pe[ix] - pe[ix].mean()
            used[ix] = True
        if used.sum() < min_n or xs[used].std() == 0 or ys[used].std() == 0:
            out[d] = (float("nan"), int(len(s)), int(used.sum()))
        else:
            out[d] = (float(np.corrcoef(xs[used], ys[used])[0, 1]), int(len(s)), int(used.sum()))
    return out


# ---- incremental information ------------------------------------------------------------------------------------------------------

def _ols(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def incremental_by_date(rbd, engine, yardsticks, h, min_n=MIN_INCR_N):
    """{date: {"n", "n_engine", "resid_ic", "fm_coef"}}; names with the engine and every yardstick and the excess return only."""
    out = {}
    for d, recs in rbd.items():
        have = [r for r in recs if r["score"].get(engine) is not None and r["excess"].get(h) is not None]
        common = [r for r in have if all(r["score"].get(y) is not None for y in yardsticks)]
        row = {"n": len(common), "n_engine": len(have), "resid_ic": float("nan"), "fm_coef": float("nan")}
        if len(common) >= max(min_n, len(yardsticks) + 10):
            eng = pct_rank([r["score"][engine] for r in common])
            ex = np.array([r["excess"][h] for r in common], dtype=float)
            Y = np.column_stack([pct_rank([r["score"][y] for r in common]) for y in yardsticks]) if yardsticks else np.zeros((len(common), 0))
            X = np.column_stack([np.ones(len(common)), Y])
            resid = eng - X @ _ols(X, eng)
            row["resid_ic"] = spearman(resid, ex)
            beta = _ols(np.column_stack([np.ones(len(common)), eng, Y]), pct_rank(ex))
            row["fm_coef"] = float(beta[1])
        out[d] = row
    return out


# ---- value / price distribution -----------------------------------------------------------------------------------------------------

def vp_distribution(records, engine):
    """The distribution of value/price for an engine: overall and by family, the extremes, and whether the extremes sort by family."""
    vals = [(r["vp"][engine], r.get("family") or "unclassified") for r in records if r["vp"].get(engine) is not None and r["vp"][engine] > 0]
    if not vals:
        return {"n": 0}
    v = np.array([x for x, _ in vals], dtype=float)
    fam = np.array([f for _, f in vals])

    def block(vv):
        lv = np.log(vv)
        q = np.percentile(vv, [5, 25, 50, 75, 95])
        return {"n": int(len(vv)), "share_below_0_4": float((vv < VP_LOW).mean()), "share_above_2_5": float((vv > VP_HIGH).mean()),
                "share_within_0_8_1_25": float(((vv >= 0.8) & (vv <= 1.25)).mean()),
                "quantiles_5_25_50_75_95": [float(x) for x in q], "sd_log_vp": float(lv.std()),
                "iqr_log_vp": float(np.percentile(lv, 75) - np.percentile(lv, 25))}

    out = {"overall": block(v), "by_family": {}}
    for f in sorted(set(fam)):
        out["by_family"][f] = block(v[fam == f])
    out["family_sorting"] = {}
    fams = sorted(set(fam))
    for name, mask in (("below_0_4", v < VP_LOW), ("above_2_5", v > VP_HIGH)):
        n_ext = int(mask.sum())
        entry = {"n_extreme": n_ext, "lift_by_family": {}}
        if n_ext and len(fams) > 1:
            chi2 = 0.0
            for f in fams:
                share_all = float((fam == f).mean())
                share_ext = float((fam[mask] == f).mean())
                entry["lift_by_family"][f] = share_ext / share_all if share_all > 0 else None
                exp_ext, exp_non = share_all * n_ext, share_all * (len(v) - n_ext)
                obs_ext, obs_non = float((fam[mask] == f).sum()), float((fam[~mask] == f).sum())
                if exp_ext > 0:
                    chi2 += (obs_ext - exp_ext) ** 2 / exp_ext
                if exp_non > 0:
                    chi2 += (obs_non - exp_non) ** 2 / exp_non
            entry["chi2"], entry["dof"] = chi2, len(fams) - 1
            entry["cramers_v"] = math.sqrt(chi2 / len(v)) if len(v) else None
        out["family_sorting"][name] = entry
    return out


def vp_dispersion_by_date(rbd, engine):
    """{date: sd of ln(V/P)}: the cross-sectional spread, to compare with the old engine's."""
    out = {}
    for d, recs in rbd.items():
        v = [r["vp"][engine] for r in recs if r["vp"].get(engine) is not None and r["vp"][engine] > 0]
        out[d] = float(np.std(np.log(v))) if len(v) >= 3 else float("nan")
    return out


# ---- forecast error -----------------------------------------------------------------------------------------------------------------

def _err(measure, forecast, actual):
    if forecast is None or actual is None:
        return None
    if measure in LOG_MEASURES:
        if not (forecast > 0 and actual > 0):
            return None
        return math.log(forecast / actual)
    return forecast - actual


def forecast_error_rows(records, engine, measure, k):
    """[(date, engine error, naive error)] over the records with an engine forecast, a base value (the naive forecast) and the outcome."""
    rows = []
    for r in records:
        fc = ((r.get("forecasts") or {}).get(engine) or {}).get(k) or {}
        out = (r.get("out") or {}).get(k)
        actual = (out or {}).get(measure) if out else None
        e_eng = _err(measure, fc.get(measure), actual)
        e_naive = _err(measure, (r.get("base") or {}).get(measure), actual)
        if e_eng is not None and e_naive is not None:
            rows.append((r["date"], e_eng, e_naive))
    return rows


def forecast_error(records, engine, measure, k):
    rows = forecast_error_rows(records, engine, measure, k)
    if not rows:
        return {"n": 0}
    ee = np.abs([r[1] for r in rows])
    en = np.abs([r[2] for r in rows])
    return {"n": len(rows), "mae_engine": float(ee.mean()), "mae_naive": float(en.mean()), "median_abs_engine": float(np.median(ee)),
            "median_abs_naive": float(np.median(en)), "skill": float(1.0 - ee.mean() / en.mean()) if en.mean() > 0 else float("nan"),
            "bias_engine": float(np.mean([r[1] for r in rows]))}


# ---- bootstrap over valuation dates -------------------------------------------------------------------------------------------------

def _interval(draws):
    a = np.array(draws, dtype=float)
    ok = a[~np.isnan(a)]
    if not len(ok):
        return (float("nan"), float("nan"), int(len(a)))
    return (float(np.percentile(ok, 5)), float(np.percentile(ok, 95)), int(len(a) - len(ok)))


def bootstrap_mean_over_dates(per_date_values, n=N_RESAMPLES, seed=SEED):
    """90% interval of the mean of a per-date statistic, resampling dates with replacement (nan dates are dropped from each draw)."""
    v = np.array(list(per_date_values), dtype=float)
    ok = v[~np.isnan(v)]
    if len(ok) < 2:
        return (float("nan"), float("nan"), 0)
    rng = np.random.default_rng(seed)
    draws = [float(ok[rng.integers(0, len(ok), size=len(ok))].mean()) for _ in range(n)]
    return _interval(draws)


def bootstrap_pooled_ic(rbd, engine, h, n=N_RESAMPLES, seed=SEED, min_n=MIN_IC_N):
    blocks = []
    for d, recs in rbd.items():
        _k, s, e = _pairs(recs, engine, h)
        if len(s) >= min_n:
            blocks.append((pct_rank(s), pct_rank(e)))
    if len(blocks) < 2:
        return (float("nan"), float("nan"), 0)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n):
        pick = rng.integers(0, len(blocks), size=len(blocks))
        x = np.concatenate([blocks[i][0] for i in pick])
        y = np.concatenate([blocks[i][1] for i in pick])
        draws.append(spearman(x, y))
    return _interval(draws)


def bootstrap_skill(records, engine, measure, k, n=N_RESAMPLES, seed=SEED):
    rows = forecast_error_rows(records, engine, measure, k)
    if not rows:
        return (float("nan"), float("nan"), 0)
    dates = sorted({r[0] for r in rows})
    if len(dates) < 2:
        return (float("nan"), float("nan"), 0)
    agg = {d: [0.0, 0.0, 0] for d in dates}
    for d, ee, en in rows:
        agg[d][0] += abs(ee)
        agg[d][1] += abs(en)
        agg[d][2] += 1
    arr = np.array([agg[d] for d in dates], dtype=float)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n):
        s = arr[rng.integers(0, len(dates), size=len(dates))].sum(axis=0)
        draws.append(1.0 - s[0] / s[1] if s[1] > 0 else float("nan"))
    return _interval(draws)


# ---- the summary --------------------------------------------------------------------------------------------------------------------

def summarize(records, engines, yardsticks, horizons, value_engines=(), measures=("revenue", "operating_margin", "roc", "reinvestment_rate"),
              ks=(1, 2, 3), n_resamples=N_RESAMPLES):
    """Every metric of section 6 for every engine and horizon, as a JSON-able dict.  `engines`: all engines scored; `yardsticks`: the names that
    count as yardsticks for the incremental tests; `value_engines`: those with a value/price distribution."""
    rbd = by_date(records)
    out = {"dates": list(rbd), "n_records": len(records), "engines": {}}
    for eng in engines:
        e_out = {"horizons": {}}
        for h in horizons:
            ic = ic_by_date(rbd, eng, h)
            ics = [v[0] for v in ic.values()]
            pooled, n_pooled = pooled_ic(rbd, eng, h)
            q = quintiles_by_date(rbd, eng, h)
            sn = sector_neutral_by_date(rbd, eng, h)
            block = {"n_dates_with_ic": int(sum(1 for x in ics if x == x)), "ic_by_date": {d: {"ic": v[0], "n": v[1]} for d, v in ic.items()},
                     "mean_ic": _nanmean(ics), "mean_ic_ci90": bootstrap_mean_over_dates(ics, n_resamples),
                     "pooled_ic": pooled, "pooled_n": n_pooled, "pooled_ic_ci90": bootstrap_pooled_ic(rbd, eng, h, n_resamples),
                     "quintile_means_avg": [_nanmean([x["quintiles"][i] for x in q.values()]) for i in range(5)],
                     "quintile_spread_mean": _nanmean([x["spread"] for x in q.values()]),
                     "quintile_spread_ci90": bootstrap_mean_over_dates([x["spread"] for x in q.values()], n_resamples),
                     "sector_neutral_ic_mean": _nanmean([v[0] for v in sn.values()]),
                     "sector_neutral_ic_ci90": bootstrap_mean_over_dates([v[0] for v in sn.values()], n_resamples)}
            if eng not in yardsticks and yardsticks:
                inc = incremental_by_date(rbd, eng, list(yardsticks), h)
                rs = [v["resid_ic"] for v in inc.values()]
                fm = [v["fm_coef"] for v in inc.values()]
                fmv = [x for x in fm if x == x]
                block["incremental"] = {"yardsticks": list(yardsticks), "resid_ic_mean": _nanmean(rs),
                                        "resid_ic_ci90": bootstrap_mean_over_dates(rs, n_resamples), "fm_coef_mean": _nanmean(fm),
                                        "fm_coef_ci90": bootstrap_mean_over_dates(fm, n_resamples),
                                        "fm_t_stat": (float(np.mean(fmv) / (np.std(fmv, ddof=1) / math.sqrt(len(fmv))))
                                                      if len(fmv) > 2 and np.std(fmv, ddof=1) > 0 else float("nan")),
                                        "common_sample_share": _nanmean([v["n"] / v["n_engine"] for v in inc.values() if v["n_engine"]]),
                                        "by_date": inc}
            e_out["horizons"][str(h)] = block
        if eng in value_engines:
            e_out["value_over_price"] = vp_distribution(records, eng)
            e_out["value_over_price_sd_log_by_date"] = vp_dispersion_by_date(rbd, eng)
        fe = {}
        for m in measures:
            for k in ks:
                x = forecast_error(records, eng, m, k)
                if x["n"]:
                    x["skill_ci90"] = bootstrap_skill(records, eng, m, k, n_resamples)
                    fe[f"{m}_k{k}"] = x
        if fe:
            e_out["forecast_error_vs_naive"] = fe
        out["engines"][eng] = e_out
    return out
