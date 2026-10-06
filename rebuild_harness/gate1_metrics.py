"""Gate-1 metrics B1-B4 and the structural diagnostics, from the records `gate1_run` writes (registration REGISTRATION_gate1_DRAFT.md sections 3-5).

Everything here is a pure function of records (tested on synthetic data in rebuild_harness/tests/test_gate1_metrics.py) plus a loader that reads a run folder
one date at a time and keeps only compact rows (a full run holds ~100k records).

EVERY FIGURE COMPUTED ON THE DEVELOPMENT RUN IS PROVISIONAL: the prices are the operator-approved raw month-end pull of today's listings (Addendum H9), survivors only;
none of it counts toward gate 1.  `PROVISIONAL` rides on every result.

The bars (registration section 5), computed under each survivorship bound of Addendum D (`excluded`, `minus100`, `last_close`):
  B1  per-date cross-sectional OLS of the 12-month excess return on the percentile ranks of the engine's IV / price and of the yardsticks, with industry fixed
      effects (every variable demeaned within its industry on the date); the mean engine coefficient over dates (Fama-MacBeth) must be > 0 and the 5th percentile of
      its date-block bootstrap (90% interval, lower end) must be > 0.
  B2  the industry-neutral spread of the 12-month excess return between the top and bottom quintile of IV / price (the rank taken inside the industry, the return
      demeaned inside the industry), averaged over dates, must be >= +3 percentage points; the same spread on the engine's residual after the yardsticks must be > 0.
  B3  (a) at most 15% of valued stocks below 0.4x or above 2.5x their price; (b) each family's share of those extremes within 10 points of its share of the
      universe; (c) the interquartile range of ln(IV / price) at least B3C_FLOOR = 0.30 (Addendum H7: the old engine cannot be computed point in time, so the
      comparator is a stated absolute floor, for the operator to approve with the other bars).
  B4  the median absolute error of the engine's next-fiscal-year revenue growth (its year-1 growth at the prior's P50 inputs) and operating margin against the
      first-filed outcome must not exceed the naive baseline's (trailing 3-year revenue CAGR; margin held), for the operating and commodity families.
A bar's status over the bounds is `metrics.gate_status` (pass / fail / not decided).  A bar that needs a return and has no dates with enough names is "not computed".

DATES (Addendum H6).  B1 and B2 (returns) use the dates up to RETURN_DATES_END = 2021-12-31, whose 12-month outcomes end by 2022-12-31 and so never overlap the
2023-2024 holdout years; B3 is reported on the same dates and, beside it, on every date; B4 (forecast quality) uses every development date, the 2022 dates included.
MISSING YARDSTICKS (Addendum H7).  A name missing a yardstick stays in B1 and B2 with that yardstick at the cross-sectional median rank (0.5) and an indicator
column for the yardsticks with a missing value on the date; the coverage (the share missing by yardstick) is reported.
"""
import gzip
import json
import math
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

import numpy as np

from backtest_phase2.metrics import rankdata_avg, spearman
from . import metrics as hm

PROVISIONAL = "PROVISIONAL: raw month-end prices of today's listings (Addendum H9), survivors only; not counted toward gate 1"
RETURN_DATES_END = "2021-12-31"    # Addendum H6: the last development date whose 12-month outcome ends by 2022-12-31
B3C_FLOOR = 0.30                   # Addendum H7: the interquartile range of ln(IV / price) at least this (an absolute floor)
BOUNDS = hm.BOUNDS
HORIZON = 12
VP_LOW, VP_HIGH = 0.4, 2.5
MIN_NAMES = 30                     # a date needs this many names with the engine, every yardstick and the outcome for B1/B2
MIN_INDUSTRY = 5                   # an industry with fewer names on a date does not enter the neutral spread
YARDSTICKS = ("yardstick_earnings_yield", "yardstick_fcf_yield", "yardstick_gross_profitability", "yardstick_return_on_capital", "yardstick_momentum_12_1")
ENGINE = "gate1_engine"
B2_BAR = 0.03
B3A_CAP = 0.15
B3B_BAND = 0.10


# ---- loading ----------------------------------------------------------------------------------------------------------------------------

def _int_keys(d):
    return {int(k): v for k, v in (d or {}).items()}


def compact(r):
    """The few fields the metrics and the diagnostics read, from one record."""
    v = r.get("val") or {}
    price = r.get("price")
    out = {"date": r["date"], "cik": r["cik"], "ticker": r.get("ticker"), "name": r.get("name_current_dated"), "industry": r.get("industry"),
           "family": r.get("family"), "status": r["status"], "reason": (r.get("reasons") or [None])[0], "mcap_group": r.get("mcap_group"),
           "price": price, "market_cap": r.get("market_cap"), "stale": (r.get("base_age_months") or 0) > 15, "base_age_months": r.get("base_age_months"),
           "score": r.get("score") or {}, "excess": _int_keys(r.get("excess")), "bounds": {int(k): v for k, v in (r.get("bounds") or {}).items()},
           "base": r.get("base"), "out1": (r.get("out") or {}).get("1") or (r.get("out") or {}).get(1)}
    if r["status"] == "valued":
        iv = v["iv_ps"]
        out.update({"iv": iv, "vp": iv["p50"] / price if price else None, "vp_p10": iv["p10"] / price, "vp_p90": iv["p90"] / price,
                    "vp_point": (v["iv_point_p50_inputs_ps"] / price) if v.get("iv_point_p50_inputs_ps") is not None else None,
                    "secondary_vp": (v["secondary_ps"] / price) if v.get("secondary_ps") is not None else None, "md": v.get("model_disagreement"),
                    "tv_share": v.get("tv_share_p50"), "tv_share_point": v.get("tv_share_p50_point"),
                    "invalid_share": 1.0 - v["n_valid"] / v["n_draws"], "neg_eq_share": v.get("share_negative_equity"),
                    "g1_p50": (v.get("forecast") or {}).get("year1_growth_point"), "m1_p50": (v.get("forecast") or {}).get("year1_margin_point"),
                    "g_naive": (v.get("prior_meta") or {}).get("mechanical_baseline_g1"), "m0": (v.get("state") or {}).get("op_margin"),
                    "disc": v.get("discount"), "inputs": v.get("inputs"), "state": v.get("state"), "prior_meta": v.get("prior_meta"),
                    "secondary_kind": v.get("secondary_kind"), "terminal_year": v.get("terminal_year"), "margin_path": v.get("margin_path"), "g_term": v.get("terminal_growth"), "returns": v.get("returns"), "stamps": r.get("stamps")})
    return out


def ran_row(r):
    """The few prior-shape fields of a name the engine ran on (valued, or refused for its invalid draws: Addendum H5)."""
    v = r.get("val") or {}
    return {"date": r["date"], "family": r.get("family"), "status": r["status"], "mcap_group": r.get("mcap_group"), "invalid_share": 1.0 - v["n_valid"] / v["n_draws"],
            "inputs": v.get("inputs") or {}, "m0": (v.get("state") or {}).get("op_margin"), "returns": v.get("returns"), "disc": v.get("discount"),
            "margin_target": (v.get("prior_meta") or {}).get("margin_target")}


def load_run(run_dir, dates=None, keep_all_for=(), ran=None):
    """(compact valued rows, status counters) from a run folder.  `keep_all_for`: dates whose full valued records are also returned (for the extremes).  `ran`: a list
    that receives `ran_row` of every name the engine ran on."""
    run_dir = Path(run_dir)
    rows, counters, full = [], OrderedDict(), {}
    files = sorted(run_dir.glob("records_*.jsonl.gz"))
    for f in files:
        d = f.name[len("records_"):-len(".jsonl.gz")]
        if dates is not None and d not in dates:
            continue
        cnt = {"status": Counter(), "reason": Counter(), "family_status": Counter(), "mcap": Counter(), "family_reason": Counter(), "invalid_draws": Counter(),
               "invalid_names": Counter(), "prepared": 0, "invalid_family": Counter()}
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                c = compact(r)
                cnt["status"][r["status"]] += 1
                inv = (r.get("val") or {}).get("invalid_reasons")
                if (r.get("val") or {}).get("n_draws"):
                    cnt["prepared"] += 1                      # a name the engine ran on (valued, or refused for its invalid draws)
                    if ran is not None:
                        ran.append(ran_row(r))
                if inv:
                    cnt["invalid_draws"].update(inv)          # Addendum H5: by reason, over every name with invalid draws
                    cnt["invalid_names"].update(inv.keys())
                    for k_, n_ in inv.items():
                        cnt["invalid_family"][(fam, k_)] += n_
                fam = r.get("family") or "none"
                cnt["family_status"][(fam, r["status"])] += 1
                if r["status"] != "valued":
                    cnt["reason"][_reason_class(c["reason"] or r["status"])] += 1
                    cnt["family_reason"][(fam, _reason_class(c["reason"] or r["status"]))] += 1
                else:
                    cnt["mcap"][c["mcap_group"]] += 1
                    rows.append(c)
                    if d in keep_all_for:
                        full.setdefault(d, []).append(r)
        counters[d] = cnt
    return rows, counters, full


def apply_adjusted_proxy(rows, prices_doc):
    """Re-express the price-dependent scores on the ADJUSTED-ONLY proxy basis (Addendum G's price limit): the price level is the dividend-adjusted close, so a name's
    IV / price, earnings yield and FCF yield are those of the run times f = Close / Adj Close of the date's month (>= 1 for a dividend payer; the share counts in the
    run are on the traded basis, and the adjusted price is the traded price divided by f once the split ratios cancel).  Momentum, gross profitability and return on
    capital do not use the price level.  Returns the number of rows without both bars (left on the run's basis and counted)."""
    prices = prices_doc["prices"]
    missing = 0
    for r in rows:
        bar = (prices.get(r.get("ticker")) or {}).get(r["date"][:7])
        if not bar or not (bar[0] and bar[1] and bar[0] > 0 and bar[1] > 0):
            missing += 1
            continue
        f = bar[0] / bar[1]
        for k in ("vp", "vp_p10", "vp_p90", "vp_point", "secondary_vp"):
            if r.get(k) is not None:
                r[k] = r[k] * f
        for k in (ENGINE, "yardstick_earnings_yield", "yardstick_fcf_yield"):
            if r["score"].get(k) is not None:
                r["score"][k] = r["score"][k] * f
    return missing


def _reason_class(reason):
    """A short class of a refusal reason (the text before its details)."""
    s = str(reason)
    if "family not built" in s:                          # Addendum H4: counted by kind (reit_or_real_estate, regulated_utility_or_pipeline, pre_profit, ...)
        kind = s.split(": ", 1)[1].split(";")[0] if s.startswith("SIC ") else s.split(":", 1)[0]
        return "family_not_built: " + kind
    for head in ("priors do not supply", "not available", "no_price", "market_cap_unavailable", "discount_rate", "all_draws_invalid", "engine_exception",
                 "engine_input_error", "priors_unavailable", "invalid_draws_over", "SIC ", "no_annual_report", "reporting_currency", "PIT_INVALID", "AMBIGUOUS", "unclassifiable"):
        if s.startswith(head):
            if head in ("not available", "priors do not supply", "discount_rate", "market_cap_unavailable", "no_price"):
                return s[:90]
            return head.strip()
    return s[:60]


# ---- helpers --------------------------------------------------------------------------------------------------------------------------------

def pct_rank(x):
    return hm.pct_rank(x)


def by_date(rows):
    out = OrderedDict()
    for r in sorted(rows, key=lambda r: r["date"]):
        out.setdefault(r["date"], []).append(r)
    return out


def excess_under(r, bound, h=HORIZON):
    """The h-month excess return of a row under a survivorship bound: the observed value, or the bound's value for an unobservable delisting."""
    b = (r.get("bounds") or {}).get(h)
    if b is not None:
        return b.get(bound)
    return (r.get("excess") or {}).get(h)


def _demean_by(x, groups):
    x = np.asarray(x, dtype=float).copy()
    g = np.asarray(groups)
    for k in set(groups):
        m = g == k
        x[m] -= x[m].mean()
    return x


def _usable(rows, bound, yardsticks=None, h=HORIZON):
    """(row, excess) of the names with an engine score and an outcome under the bound.  A missing yardstick does not exclude a name (Addendum H7: `yardstick_design`)."""
    out = []
    for r in rows:
        if r["score"].get(ENGINE) is None:
            continue
        e = excess_under(r, bound, h)
        if e is None:
            continue
        out.append((r, e))
    return out


def yardstick_design(rs, yardsticks):
    """(rank columns, indicator columns, missing counts) of the yardsticks for the names `rs` on one date (Addendum H7).  Each yardstick is the percentile rank among the
    names that have it; a name that lacks it gets the cross-sectional median rank 0.5 and a 1 in that yardstick's indicator column (a column only for yardsticks that
    are missing for at least one name on the date)."""
    cols, inds, missing = [], [], {}
    for y in yardsticks:
        v = np.array([np.nan if r["score"].get(y) is None else r["score"][y] for r in rs], dtype=float)
        miss = np.isnan(v)
        missing[y] = int(miss.sum())
        rank = np.full(len(v), 0.5)
        if (~miss).any():
            rank[~miss] = pct_rank(v[~miss])
        cols.append(rank)
        if miss.any():
            inds.append(miss.astype(float))
    return cols, inds, missing


# ---- B1 -------------------------------------------------------------------------------------------------------------------------------------

def b1_by_date(rows_by_date, bound, yardsticks=YARDSTICKS, h=HORIZON, y_is_rank=False):
    """{date: {"n", "coef"}}: the engine's coefficient in the date's industry-demeaned OLS of the excess return on the percentile ranks."""
    out = {}
    for d, rows in rows_by_date.items():
        pairs = _usable(rows, bound, yardsticks, h)
        if len(pairs) < MIN_NAMES:
            out[d] = {"n": len(pairs), "coef": float("nan")}
            continue
        rs = [p[0] for p in pairs]
        ex = np.array([p[1] for p in pairs], dtype=float)
        inds = [r.get("industry") or "unknown" for r in rs]
        eng = pct_rank([r["score"][ENGINE] for r in rs])
        Y, I, miss = yardstick_design(rs, yardsticks)
        X = np.column_stack([eng] + Y + I)
        X = np.column_stack([_demean_by(X[:, j], inds) for j in range(X.shape[1])])
        yv = pct_rank(ex) if y_is_rank else ex
        yv = _demean_by(yv, inds)
        beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
        out[d] = {"n": len(pairs), "coef": float(beta[0]), "missing": miss}
    return out


def b1(rows_by_date, bound, yardsticks=YARDSTICKS, n_resamples=hm.N_RESAMPLES, y_is_rank=False):
    per = b1_by_date(rows_by_date, bound, yardsticks, y_is_rank=y_is_rank)
    coefs = [v["coef"] for v in per.values()]
    ok = [c for c in coefs if c == c]
    lo, hi, _ = hm.bootstrap_mean_over_dates(coefs, n_resamples)
    mean = float(np.mean(ok)) if ok else float("nan")
    status = ("not computed" if not ok else "pass" if (mean > 0 and lo > 0) else "fail")
    return {"mean_coef": mean, "ci90": [lo, hi], "n_dates": len(ok), "by_date": per, "status": status, "yardsticks": list(yardsticks),
            "yardstick_missing_share": _missing_share(per, yardsticks)}


def _missing_share(per, yardsticks):
    """The share of the names of the dates that entered the regression with each yardstick imputed (Addendum H7 coverage)."""
    n = sum(v["n"] for v in per.values() if v.get("missing") is not None)
    return {y: (sum(v["missing"][y] for v in per.values() if v.get("missing") is not None) / n if n else None) for y in yardsticks}


# ---- B2 -------------------------------------------------------------------------------------------------------------------------------------

def _neutral_spread(scores, excess, inds):
    """Industry-neutral top-minus-bottom quintile spread: within each industry (>= MIN_INDUSTRY names) the score's percentile rank and the return demeaned;
    quintiles of the rank across the date; the mean demeaned return of the top quintile minus that of the bottom."""
    scores, excess = np.asarray(scores, dtype=float), np.asarray(excess, dtype=float)
    inds = np.asarray(inds)
    rank = np.full(len(scores), np.nan)
    dm = np.full(len(scores), np.nan)
    for k in set(inds.tolist()):
        m = np.where(inds == k)[0]
        if len(m) < MIN_INDUSTRY:
            continue
        rank[m] = pct_rank(scores[m])
        dm[m] = excess[m] - excess[m].mean()
    ok = ~np.isnan(rank)
    if ok.sum() < hm.MIN_QUINTILE_N:
        return float("nan"), int(ok.sum())
    q = hm.quintile_means(rank[ok], dm[ok])
    return q[4] - q[0], int(ok.sum())


def b2_by_date(rows_by_date, bound, yardsticks=YARDSTICKS, h=HORIZON):
    out = {}
    for d, rows in rows_by_date.items():
        pairs = _usable(rows, bound, yardsticks, h)
        if len(pairs) < MIN_NAMES:
            out[d] = {"n": len(pairs), "spread": float("nan"), "spread_residual": float("nan")}
            continue
        rs = [p[0] for p in pairs]
        ex = np.array([p[1] for p in pairs], dtype=float)
        inds = [r.get("industry") or "unknown" for r in rs]
        sc = np.array([r["score"][ENGINE] for r in rs], dtype=float)
        sp, n_used = _neutral_spread(sc, ex, inds)
        eng = pct_rank(sc)
        Yc, Ic, _miss = yardstick_design(rs, yardsticks)
        Y = np.column_stack(Yc + Ic)
        X = np.column_stack([_demean_by(Y[:, j], inds) for j in range(Y.shape[1])])
        e_dm = _demean_by(eng, inds)
        beta, *_ = np.linalg.lstsq(X, e_dm, rcond=None)
        resid = e_dm - X @ beta
        spr, _ = _neutral_spread(resid + 1e-12 * np.arange(len(resid)), ex, inds)     # the tiny tie-break keeps ranks distinct; the residual is already industry-demeaned
        out[d] = {"n": len(pairs), "n_neutral": n_used, "spread": sp, "spread_residual": spr}
    return out


def b2(rows_by_date, bound, yardsticks=YARDSTICKS, n_resamples=hm.N_RESAMPLES):
    per = b2_by_date(rows_by_date, bound, yardsticks)
    sp = [v["spread"] for v in per.values()]
    sr = [v["spread_residual"] for v in per.values()]
    oks = [x for x in sp if x == x]
    okr = [x for x in sr if x == x]
    mean_s = float(np.mean(oks)) if oks else float("nan")
    mean_r = float(np.mean(okr)) if okr else float("nan")
    status = "not computed" if not oks else ("pass" if (mean_s >= B2_BAR and mean_r > 0) else "fail")
    return {"mean_spread": mean_s, "ci90": list(hm.bootstrap_mean_over_dates(sp, n_resamples)[:2]), "mean_spread_residual": mean_r,
            "ci90_residual": list(hm.bootstrap_mean_over_dates(sr, n_resamples)[:2]), "n_dates": len(oks), "by_date": per, "status": status}


# ---- B3 -------------------------------------------------------------------------------------------------------------------------------------

def b3(rows):
    """Distribution bars on the valued names (no return involved: the same under every survivorship bound)."""
    vp = [(r["vp"], r["family"] or "unclassified") for r in rows if r.get("vp") is not None]
    if not vp:
        return {"status": "not computed", "n": 0}
    v = np.array([x for x, _ in vp], dtype=float)
    fam = np.array([f for _, f in vp])
    below, above = v < VP_LOW, v > VP_HIGH
    ext = below | above
    share = float(ext.mean())
    fams = sorted(set(fam))
    shares_all = {f: float((fam == f).mean()) for f in fams}
    shares_ext = {f: (float((fam[ext] == f).mean()) if ext.any() else 0.0) for f in fams}
    gaps = {f: shares_ext[f] - shares_all[f] for f in fams} if ext.any() else {f: 0.0 for f in fams}      # no extreme names: (b) holds vacuously
    pos = v[v > 0]
    iqr = float(np.percentile(np.log(pos), 75) - np.percentile(np.log(pos), 25)) if len(pos) > 3 else float("nan")
    a_ok = share <= B3A_CAP
    b_ok = all(abs(g) <= B3B_BAND for g in gaps.values())
    c_status = "not computed" if iqr != iqr else ("pass" if iqr >= B3C_FLOOR else "fail")
    if not (a_ok and b_ok) or c_status == "fail":
        status = "fail"
    else:
        status = "pass" if c_status == "pass" else "not computed"
    return {"n": int(len(v)), "share_below_0_4": float(below.mean()), "share_above_2_5": float(above.mean()), "share_extreme": share,
            "share_nonpositive_iv": float((v <= 0).mean()), "a_ok": a_ok, "family_share_universe": shares_all, "family_share_extremes": shares_ext,
            "family_gap_points": {f: 100 * g for f, g in gaps.items()}, "b_ok": b_ok, "iqr_ln_vp_positive_iv": iqr, "n_positive_iv": int(len(pos)),
            "c_floor": B3C_FLOOR, "c_status": c_status, "status": status}


# ---- B4 -------------------------------------------------------------------------------------------------------------------------------------

def b4(rows, n_resamples=hm.N_RESAMPLES):
    """Median absolute error of the engine's next-fiscal-year revenue growth and operating margin against the naive baseline, operating and commodity
    families (the financial engine produces no revenue or operating margin)."""
    gr, mr = [], []
    for r in rows:
        if r["family"] not in ("operating", "commodity"):
            continue
        base, o = r.get("base"), r.get("out1")
        if not base or not o:
            continue
        rev0, rev1, m1 = base.get("revenue"), o.get("revenue"), o.get("operating_margin")
        if rev0 and rev1 and r.get("g1_p50") is not None and r.get("g_naive") is not None:
            a = rev1 / rev0 - 1.0
            gr.append((r["date"], abs(r["g1_p50"] - a), abs(r["g_naive"] - a)))
        if m1 is not None and r.get("m1_p50") is not None and r.get("m0") is not None:
            mr.append((r["date"], abs(r["m1_p50"] - m1), abs(r["m0"] - m1)))

    def block(rows_):
        if not rows_:
            return {"n": 0, "status": "not computed"}
        e = np.array([x[1] for x in rows_])
        n = np.array([x[2] for x in rows_])
        dates = sorted({x[0] for x in rows_})
        by = {d: (float(np.median([x[1] for x in rows_ if x[0] == d])), float(np.median([x[2] for x in rows_ if x[0] == d]))) for d in dates}
        return {"n": len(rows_), "median_abs_error_engine": float(np.median(e)), "median_abs_error_naive": float(np.median(n)),
                "engine_not_worse": bool(np.median(e) <= np.median(n)), "share_engine_closer": float((e < n).mean()),
                "by_date_median_abs_error_engine_naive": by}
    g, m = block(gr), block(mr)
    status = ("not computed" if (g["n"] == 0 or m["n"] == 0) else "pass" if (g["engine_not_worse"] and m["engine_not_worse"]) else "fail")
    return {"revenue_growth": g, "operating_margin": m, "status": status}


# ---- the bars over the three bounds ---------------------------------------------------------------------------------------------------

def three_bounds(rows, universe_label, n_resamples=hm.N_RESAMPLES, yardsticks=YARDSTICKS, return_end=None):
    """B1-B4 for `rows`.  `return_end` (an ISO date; Addendum H6): B1, B2 and B3 use the dates up to it, B4 every date; None uses every date for all of them."""
    ret_rows = rows if return_end is None else [r for r in rows if r["date"] <= return_end]
    rbd = by_date(ret_rows)
    out = {"universe": universe_label, "n_valued": len(rows), "n_valued_return_dates": len(ret_rows), "provisional": PROVISIONAL, "yardsticks_used": list(yardsticks),
           "return_dates": sorted(rbd), "b4_dates": sorted({r["date"] for r in rows}), "return_end": return_end,
           "note_sixth_yardstick": "the old engine is not computed point in time (its anchors are not stored before 2026-05), so it is dropped (Addendum H7): five yardsticks",
           "note_missing_yardsticks": "a name missing a yardstick stays in B1 and B2 at the median rank with an indicator (Addendum H7)"}
    out["B1"] = {b: b1(rbd, b, yardsticks, n_resamples) for b in BOUNDS}
    out["B1_rank_dependent_variant"] = {b: {k: v for k, v in b1(rbd, b, yardsticks, n_resamples, y_is_rank=True).items() if k != "by_date"} for b in BOUNDS}
    out["B2"] = {b: b2(rbd, b, yardsticks, n_resamples) for b in BOUNDS}
    out["B3"] = b3(ret_rows)
    out["B3_all_dates"] = b3(rows)
    out["B4"] = b4(rows, n_resamples)
    out["B4_return_dates_only"] = b4(ret_rows, n_resamples)
    for bar in ("B1", "B2"):
        by = {b: out[bar][b] for b in BOUNDS}
        sts = {b: v["status"] for b, v in by.items()}
        vals = set(sts.values())
        out[bar + "_status_over_bounds"] = ("not computed" if vals == {"not computed"} else ("pass" if vals == {"pass"} else "fail" if vals == {"fail"} else "not decided"))
    return out


# ---- diagnostics ----------------------------------------------------------------------------------------------------------------------------

def _q(v, ps=(5, 10, 25, 50, 75, 90, 95)):
    v = np.asarray([x for x in v if x is not None and x == x], dtype=float)
    return {f"p{p}": float(np.percentile(v, p)) for p in ps} if len(v) else {}


def distribution_block(vals):
    v = np.array([x for x in vals if x is not None and x == x], dtype=float)
    if not len(v):
        return {"n": 0}
    return {"n": int(len(v)), "share_below_0_4": float((v < VP_LOW).mean()), "share_above_2_5": float((v > VP_HIGH).mean()),
            "share_nonpositive": float((v <= 0).mean()), "quantiles": _q(v)}


def vp_by(rows, keyfn, min_n=1):
    g = defaultdict(list)
    for r in rows:
        if r.get("vp") is not None:
            g[keyfn(r)].append(r["vp"])
    return {k: distribution_block(v) for k, v in sorted(g.items(), key=lambda kv: str(kv[0])) if len(v) >= min_n}


def extremes_by_family(rows):
    out = {}
    fams = sorted({r["family"] for r in rows})
    n = len(rows)
    for name, f in (("below_0_4", lambda x: x < VP_LOW), ("above_2_5", lambda x: x > VP_HIGH)):
        ex = [r for r in rows if r.get("vp") is not None and f(r["vp"])]
        out[name] = {"n": len(ex), "by_family": {fam: {"n": sum(1 for r in ex if r["family"] == fam), "share_of_extremes": (sum(1 for r in ex if r["family"] == fam) / len(ex)) if ex else None,
                                                       "share_of_universe": sum(1 for r in rows if r["family"] == fam) / n} for fam in fams}}
    return out


def tv_share_distribution(rows):
    allv = [r["tv_share"] for r in rows if r.get("tv_share") is not None]
    out = {"all": _q(allv) | {"n": len(allv)}, "by_family": {}}
    for fam in sorted({r["family"] for r in rows}):
        out["by_family"][fam] = _q([r["tv_share"] for r in rows if r["family"] == fam and r.get("tv_share") is not None])
    out["share_above_0_75"] = float(np.mean([x > 0.75 for x in allv])) if allv else None
    out["point_p50_inputs"] = _q([r["tv_share_point"] for r in rows if r.get("tv_share_point") is not None])
    return out


def disagreement_by_family(rows):
    out = {}
    for fam in sorted({r["family"] for r in rows}):
        v = [r["md"] for r in rows if r["family"] == fam and r.get("md") is not None]
        out[fam] = _q(v) | {"n": len(v), "n_valued": sum(1 for r in rows if r["family"] == fam), "mean": float(np.mean(v)) if v else None}
    return out


def structure_stats(rows):
    """Shares and levels that locate where the value comes from (diagnostics, not gates)."""
    op = [r for r in rows if r["family"] in ("operating", "commodity") and r.get("disc") and r.get("inputs")]
    out = {}
    if op:
        out["operating_commodity_n"] = len(op)
        out["coe"] = _q([r["disc"]["coe"] for r in op])
        out["wacc"] = _q([r["disc"]["wacc"] for r in op])
        out["ronic_p50_minus_wacc"] = _q([r["inputs"]["ronic"]["p50"] - r["disc"]["wacc"] for r in op if "ronic" in r["inputs"]])
        out["share_ronic_p50_below_wacc"] = float(np.mean([r["inputs"]["ronic"]["p50"] < r["disc"]["wacc"] for r in op if "ronic" in r["inputs"]]))
        gt = [r["g_term"] for r in op if r.get("g_term")]
        out["terminal_growth_date_value"] = _q([x["base"] for x in gt if x.get("base") is not None])
        out["share_terminal_growth_from_negative_decay_path"] = (float(np.mean([bool((x.get("at_p50_inputs") or {}).get("basis", "").startswith("decay path")) for x in gt])) if gt else None)
        out["terminal_growth_at_p50_inputs"] = _q([(x.get("at_p50_inputs") or {}).get("value") for x in gt])
        out["margin_target_p50_minus_current_margin"] = _q([r["inputs"]["margin_target"]["p50"] - r["m0"] for r in op if "margin_target" in r["inputs"] and r.get("m0") is not None])
        out["margin_target_width_p10_p90"] = _q([r["inputs"]["margin_target"]["p90"] - r["inputs"]["margin_target"]["p10"] for r in op if "margin_target" in r["inputs"]])
        mt = [(r["prior_meta"] or {}).get("margin_target") for r in op if r.get("prior_meta")]
        mt = [x for x in mt if x]
        out["margin_level5_r5"] = _q([x["r5"] for x in mt])
        out["g1_width_p10_p90"] = _q([r["inputs"]["g1"]["p90"] - r["inputs"]["g1"]["p10"] for r in op if "g1" in r["inputs"]])
        out["ronic_level5_width_p10_p90"] = _q([r["inputs"]["ronic"]["p90"] - r["inputs"]["ronic"]["p10"] for r in op if "ronic" in r["inputs"]])
        rt = [r["returns"] for r in op if r.get("returns")]
        out["own_trailing_roic3"] = _q([x["roic3"] for x in rt if x.get("roic3") is not None])
        out["industry_median_roic"] = _q([x["industry_roic"]["value"] for x in rt if x.get("industry_roic")])
        out["industry_median_roic_basis_pooled_share"] = float(np.mean([x["industry_roic"]["basis"].startswith("pooled") for x in rt if x.get("industry_roic")])) if rt else None
        out["ronic_terminal_at_p50_inputs"] = _q([x["ronic_terminal_at_p50_inputs"] for x in rt if x.get("ronic_terminal_at_p50_inputs") is not None])
        out["share_terminal_ronic_floored_at_wacc"] = float(np.mean([abs(x["ronic_terminal_at_p50_inputs"] - r["disc"]["wacc"]) < 1e-12 for r in op for x in [r.get("returns") or {}]
                                                                    if x.get("ronic_terminal_at_p50_inputs") is not None])) if rt else None
        out["margin_level5_median_minus_8y_median"] = _q([x["level5_median"] - x["centre_8y_median"] for x in mt])
        mp = [r.get("margin_path") for r in op if r.get("margin_path")]
        out["margin_path_linear_share"] = float(np.mean([x["shape"] == "linear" for x in mp])) if mp else None
        out["margin_path_clipped_share"] = float(np.mean([bool(x["clipped"]) for x in mp])) if mp else None
        out["terminal_year_margin_minus_current"] = _q([r["terminal_year"]["margin"] - r["m0"] for r in op if r.get("terminal_year") and r.get("m0") is not None])
    fin = [r for r in rows if r["family"] == "financial" and r.get("returns")]
    if fin:
        out["financial_industry_median_rote"] = _q([x["returns"]["industry_rote"]["value"] for x in fin if x["returns"].get("industry_rote")])
        out["financial_terminal_rote_at_p50_inputs"] = _q([x["returns"]["rote_terminal_at_p50_inputs"] for x in fin if x["returns"].get("rote_terminal_at_p50_inputs") is not None])
        out["financial_share_terminal_rote_floored_at_coe"] = float(np.mean([abs(x["returns"]["rote_terminal_at_p50_inputs"] - x["disc"]["coe"]) < 1e-12 for x in fin
                                                                           if x["returns"].get("rote_terminal_at_p50_inputs") is not None and x.get("disc")]))
        out["financial_rote_target_width_p10_p90"] = _q([x["inputs"]["rote_target"]["p90"] - x["inputs"]["rote_target"]["p10"] for x in fin if x.get("inputs") and "rote_target" in x["inputs"]])
    out["invalid_draw_share"] = _q([r["invalid_share"] for r in rows])
    out["share_names_over_5pct_draws_invalid"] = float(np.mean([r["invalid_share"] > 0.05 for r in rows])) if rows else None
    out["share_names_over_half_draws_invalid"] = float(np.mean([r["invalid_share"] > 0.5 for r in rows])) if rows else None
    ratio = [r["vp"] / r["vp_point"] for r in rows if r.get("vp") is not None and r.get("vp_point") not in (None, 0) and r["vp"] > 0 and r["vp_point"] > 0]
    out["ratio_distribution_median_to_point_inputs"] = _q(ratio)
    out["point_inputs_vp"] = distribution_block([r.get("vp_point") for r in rows])
    out["dispersion_p90_over_p10_value"] = _q([(r["vp_p90"] - r["vp_p10"]) for r in rows])
    out["secondary_over_primary"] = _q([r["secondary_vp"] / r["vp"] for r in rows if r.get("secondary_vp") is not None and r.get("vp") and r["vp"] > 0 and r["secondary_vp"] > 0])
    out["prior_fallback_counts"] = dict(Counter(f.split(":")[0] + ":" + f.split(":")[1][:60] if ":" in f else f[:80] for r in rows for f in ((r.get("prior_meta") or {}).get("fallbacks") or [])).most_common(15))
    return out


def prior_shape_stats(ran):
    """The shapes of the priors the engines drew from, over EVERY name the engine ran on (valued or refused for invalid draws), by family and by outcome: the width of the
    margin level five years on, the share of names whose P10 margin level is not positive, the same for the ROIC level, and the invalid-draw share (Addendum H5)."""
    out = {}
    for fam in ("operating", "commodity", "financial"):
        for grp, sel in (("all", lambda r: True), ("valued", lambda r: r["status"] == "valued"), ("refused_invalid_draws", lambda r: r["status"] != "valued")):
            rs = [r for r in ran if r["family"] == fam and sel(r)]
            if not rs:
                continue
            o = {"n": len(rs), "invalid_share": _q([r["invalid_share"] for r in rs])}
            if fam != "financial":
                mt = [r["inputs"]["margin_target"] for r in rs if "margin_target" in r["inputs"]]
                rn = [r["inputs"]["ronic"] for r in rs if "ronic" in r["inputs"]]
                o["margin_level5_p50"] = _q([x["p50"] for x in mt])
                o["margin_level5_width_p10_p90"] = _q([x["p90"] - x["p10"] for x in mt])
                o["share_margin_level5_p10_not_positive"] = float(np.mean([x["p10"] <= 0 for x in mt])) if mt else None
                o["margin_now"] = _q([r["m0"] for r in rs if r.get("m0") is not None])
                o["ronic_level5_p50"] = _q([x["p50"] for x in rn])
                o["ronic_level5_width_p10_p90"] = _q([x["p90"] - x["p10"] for x in rn])
                o["share_ronic_level5_p10_not_positive"] = float(np.mean([x["p10"] <= 0 for x in rn])) if rn else None
                o["own_trailing_roic3"] = _q([r["returns"]["roic3"] for r in rs if r.get("returns") and r["returns"].get("roic3") is not None])
                o["industry_median_roic"] = _q([r["returns"]["industry_roic"]["value"] for r in rs if r.get("returns") and r["returns"].get("industry_roic")])
                o["wacc"] = _q([r["disc"]["wacc"] for r in rs if r.get("disc")])
            else:
                rt = [r["inputs"]["rote_target"] for r in rs if "rote_target" in r["inputs"]]
                o["rote_target_p50"] = _q([x["p50"] for x in rt])
                o["rote_target_width_p10_p90"] = _q([x["p90"] - x["p10"] for x in rt])
                o["industry_median_rote"] = _q([r["returns"]["industry_rote"]["value"] for r in rs if r.get("returns") and r["returns"].get("industry_rote")])
                o["coe"] = _q([r["disc"]["coe"] for r in rs if r.get("disc")])
            out[f"{fam} | {grp}"] = o
    return out


def extremes_listing(full_rows, n=30):
    """The top and bottom `n` valued names by IV / price (names with a price and a positive market cap), each with the key inputs."""
    vs = [r for r in full_rows if r["status"] == "valued"]
    for r in vs:
        r["_vp"] = r["val"]["iv_ps"]["p50"] / r["price"]

    def row(r):
        v = r["val"]
        return {"ticker": r.get("ticker"), "name": r.get("name_current_dated"), "industry": r.get("industry"), "family": r.get("family"), "mcap_group": r.get("mcap_group"),
                "price": r["price"], "market_cap": r["market_cap"], "iv_p10_p50_p90": [v["iv_ps"]["p10"], v["iv_ps"]["p50"], v["iv_ps"]["p90"]], "vp": r["_vp"],
                "vp_point_p50_inputs": (v["iv_point_p50_inputs_ps"] / r["price"]) if v.get("iv_point_p50_inputs_ps") is not None else None,
                "secondary_vp": (v["secondary_ps"] / r["price"]) if v.get("secondary_ps") is not None else None, "md": v.get("model_disagreement"),
                "tv_share_p50": v.get("tv_share_p50"), "invalid_share": 1 - v["n_valid"] / v["n_draws"], "coe": v["discount"]["coe"], "wacc": v["discount"]["wacc"],
                "beta_levered": v["discount"]["beta_levered"], "de": v["discount"]["de_ratio"], "de_basis": v["discount"]["de_basis"],
                "revenue": v["state"]["revenue"], "op_margin": v["state"]["op_margin"], "op_margin_median": v["state"]["op_margin_median"],
                "growth_latest": v["state"]["growth_latest"], "tax": v["state"]["tax_rate"], "tbv": v["state"]["tbv"], "rote": v["state"]["rote_latest"],
                "inputs_p10_p50_p90": {k: [x["p10"], x["p50"], x["p90"]] for k, x in v["inputs"].items()}, "base_age_months": r["base_age_months"],
                "roic3": (v.get("returns") or {}).get("roic3"), "industry_roic": ((v.get("returns") or {}).get("industry_roic") or {}).get("value"),
                "ronic_terminal": (v.get("returns") or {}).get("ronic_terminal_at_p50_inputs"), "rote3": (v.get("returns") or {}).get("rote3"),
                "industry_rote": ((v.get("returns") or {}).get("industry_rote") or {}).get("value"), "rote_terminal": (v.get("returns") or {}).get("rote_terminal_at_p50_inputs"),
                "g_term": ((v.get("terminal_growth") or {}).get("at_p50_inputs") or {}).get("value"),
                "terminal_year_margin": (v.get("terminal_year") or {}).get("margin"),
                "stamps": r.get("stamps")[:6]}
    vs.sort(key=lambda r: r["_vp"])
    return {"bottom": [row(r) for r in vs[:n]], "top": [row(r) for r in vs[-n:][::-1]], "n_valued": len(vs)}


def coverage_tables(counters):
    """Per date: status counts; overall: refusals by reason, by family and reason, and valued by family and market-cap group."""
    per_date = {d: dict(c["status"]) for d, c in counters.items()}
    reason = Counter()
    fam_reason = Counter()
    fam_status = Counter()
    mcap = Counter()
    for c in counters.values():
        reason.update(c["reason"])
        fam_reason.update(c["family_reason"])
        fam_status.update(c["family_status"])
        mcap.update(c["mcap"])
    inv_draws, inv_names, inv_fam = Counter(), Counter(), Counter()
    for c in counters.values():
        inv_draws.update(c["invalid_draws"])
        inv_names.update(c["invalid_names"])
        inv_fam.update(c["invalid_family"])
    by_date_reason = {d: dict(c["reason"].most_common()) for d, c in counters.items()}
    by_date_family = {d: {f"{k[0]} | {k[1]}": v for k, v in sorted(c["family_status"].items())} for d, c in counters.items()}
    return {"per_date_status": per_date, "refusals_by_date_and_reason": by_date_reason, "family_and_status_by_date": by_date_family,
            "refusals_by_reason": dict(reason.most_common()), "invalid_draw_reasons_by_draws": dict(inv_draws.most_common()),
            "invalid_draw_reasons_by_names": dict(inv_names.most_common()),
            "invalid_draw_reasons_by_family_and_draws": {f"{k[0]} | {k[1]}": v for k, v in inv_fam.most_common()}, "names_the_engine_ran_on": sum(c["prepared"] for c in counters.values()),
            "refusals_by_family_and_reason": {f"{k[0]} | {k[1]}": v for k, v in fam_reason.most_common()},
            "by_family_and_status": {f"{k[0]} | {k[1]}": v for k, v in sorted(fam_status.items())}, "valued_by_mcap_group": dict(mcap)}
