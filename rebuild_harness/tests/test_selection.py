"""Plan E1: the selection evaluation of REGISTRATION_selection.md v2 on synthetic panels with a planted signal, no signal, and a factor-only signal."""
import math

import numpy as np
import pandas as pd
import pytest

from rebuild_harness.selection import evaluate as ev


def panel(n_dates=40, n=200, planted=0.0, factor_loading=0.0, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(n_dates):
        d = (pd.Timestamp("2027-04-30") + pd.offsets.MonthEnd(t)).date().isoformat()
        f_shock = rng.normal(0, 0.03)
        for i in range(n):
            ctrl = {c: rng.normal() for c in ev.EXPANDED}
            sig = rng.normal()
            r = planted * 0.02 * sig + factor_loading * 0.02 * ctrl["bp"] + f_shock + rng.normal(0, 0.05)
            row = dict(date=d, cik=f"{i:04d}", industry=str(10 + i % 12), family="operating", hs2=sig, hs1_raw=sig, trend=["up", "flat", "down"][i % 3],
                       adv=float(rng.lognormal(15, 1)), **ctrl)
            for h in (1, 3, 6):
                for b in ("excluded", "minus100", "last_close"):
                    row[f"ret_{h}_{b}"] = r
            rows.append(row)
    return pd.DataFrame(rows)


def test_a_planted_signal_is_recovered_and_passes_and_a_null_signal_does_not():
    ic = ev.ic_series(panel(planted=1.0), "hs2", 3, "excluded")
    r = ev.nw_mean_t(ic, ev.NW_LAGS[3])
    assert r["n"] == 40 and r["mean"] > 0.1 and r["t"] > 5
    hits = 0
    for s in range(20):
        r0 = ev.nw_mean_t(ev.ic_series(panel(n_dates=36, n=120, seed=100 + s), "hs2", 3, "excluded"), ev.NW_LAGS[3])
        hits += (r0["t"] or 0) >= ev.T_BAR
    assert hits <= 3                                                          # about 2.7% expected at t >= 2 one-sided; never routinely


def test_a_signal_that_is_only_a_control_factor_is_removed_by_the_residualisation():
    p = panel(factor_loading=3.0, seed=7)
    p["hs2"] = p["bp"] + np.random.default_rng(1).normal(0, 0.1, len(p))       # the "signal" is book/price
    raw = ev.ic_series(p, "hs2", 3, "excluded", controls=())
    res = ev.ic_series(p, "hs2", 3, "excluded")
    assert raw.mean() > 0.3 and abs(res.mean()) < 0.05


def test_newey_west_matches_the_plain_t_at_zero_lags_and_widens_with_positive_autocorrelation():
    x = np.random.default_rng(3).normal(0.1, 1, 500)
    r0 = ev.nw_mean_t(x, 0)
    assert r0["t"] == pytest.approx(x.mean() / (x.std() / math.sqrt(len(x))), rel=1e-9)
    ar = np.convolve(np.random.default_rng(4).normal(0, 1, 503), np.ones(4) / 4, mode="valid") + 0.1
    assert abs(ev.nw_mean_t(ar, 3)["t"]) < abs(ev.nw_mean_t(ar, 0)["t"])


def test_the_long_short_book_charges_tiered_costs_on_actual_turnover_and_borrow_on_the_short_leg():
    p = panel(n_dates=3, n=100, planted=1.0, seed=5)
    ls = ev.long_short(p, "hs2")
    assert len(ls) == 3 and (ls["cost"] > 0).all() and (ls["borrow"] > 0).all()
    assert ls["net"].iloc[0] == pytest.approx(ls["gross"].iloc[0] - ls["cost"].iloc[0] - ls["borrow"].iloc[0])
    first = ls["cost"].iloc[0]                                                 # date 1: buy 20 and short 20 names from cash: 2 x 1.0 of weight traded
    assert ev.COST_SIDE * 2 <= first <= ev.COST_SIDE_ILLIQ * 2 + 1e-12


def test_the_sized_book_buffers_caps_names_and_industries_and_never_exceeds_full_investment():
    day = panel(n_dates=1, n=200, seed=9)
    tg = ev.sized_targets(day, "hs2", held=[])
    assert tg and sum(tg.values()) <= 1.0 + 1e-9 and max(tg.values()) <= ev.NAME_CAP + 1e-9
    ind = dict(zip(day["cik"], day["industry"]))
    by = {}
    for c, w in tg.items():
        by[ind[c]] = by.get(ind[c], 0.0) + w
    assert max(by.values()) <= ev.INDUSTRY_CAP + 1e-9
    pct = dict(zip(day["cik"], day["hs2"].rank(pct=True)))
    assert all(pct[c] > 0.8 for c in tg)                                       # entry only at the top quintile
    mid = [c for c, x in pct.items() if 0.5 < x <= 0.8][:3]
    assert set(mid) <= set(ev.sized_targets(day, "hs2", held=mid))             # held names stay while above the median


def test_turnover_is_capped_by_dropping_the_smallest_trades_first():
    prev = {"a": 0.4, "b": 0.3, "c": 0.3}
    target = {"a": 0.0, "b": 0.3, "d": 0.4, "c": 0.25, "e": 0.05}
    out = ev.turnover_capped(prev, target, cap=0.30)
    assert "e" not in out and out.get("c") == pytest.approx(0.3)               # the two 0.05 trades are dropped first
    assert sum(abs(out.get(k, 0) - prev.get(k, 0)) for k in set(out) | set(prev)) <= 0.6 + 1e-12
    assert sum(out.values()) <= 1.0 + 1e-12                                     # never above full investment (a dropped sell cannot fund a kept buy)
    for s in range(200):                                                        # property: any book, any target
        rng = np.random.default_rng(s)
        a = rng.dirichlet(np.ones(8)) * rng.uniform(0.5, 1.0)
        b = rng.dirichlet(np.ones(8)) * rng.uniform(0.5, 1.0)
        pv, tg = {f"n{i}": float(x) for i, x in enumerate(a)}, {f"n{i}": float(x) for i, x in enumerate(b)}
        o = ev.turnover_capped(pv, tg)
        assert sum(o.values()) <= 1.0 + 1e-9 and sum(abs(o.get(k, 0) - pv.get(k, 0)) for k in set(o) | set(pv)) <= 2 * ev.TURNOVER_CAP + 1e-9


def test_alpha_recovers_a_planted_intercept_and_crisis_months_and_the_sequence_follow_the_registration():
    rng = np.random.default_rng(11)
    F = pd.DataFrame(rng.normal(0, 0.04, (48, 6)), columns=["MKT", "SMB", "HML", "MOM", "STR", "LVOL"])
    y = 0.01 + F.to_numpy() @ np.array([0.5, 0.2, -0.1, 0.0, 0.1, 0.3]) + rng.normal(0, 0.005, 48)
    a = ev.alpha(y, F)
    assert a["alpha_monthly"] == pytest.approx(0.01, abs=0.003) and a["t"] > 5
    idx = pd.bdate_range("2027-01-01", "2027-06-30")
    px = pd.Series(np.exp(np.cumsum(np.where(idx.month == 3, np.random.default_rng(2).normal(0, 0.04, len(idx)), 0.001))), index=idx)
    cm = ev.crisis_months(px)
    assert bool(cm[pd.Period("2027-03", "M")]) and not bool(cm[pd.Period("2027-05", "M")])
    ok = {"n": 40, "mean": 0.03, "t": 2.5}
    assert ev.sequence({"hs2": ok, "hs1": {"n": 40, "mean": 0.01, "t": 1.2}, "hs3": ok}) == {"hs2": "pass", "hs1": "fail", "hs3": "not tested (an earlier hypothesis failed)"}
    assert ev.sequence({"hs2": {"n": 20, "mean": 0.05, "t": 3.0}}, adopted_o3=False)["hs2"].startswith("not decided")
