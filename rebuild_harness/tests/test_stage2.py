"""Tests of the Stage 2 layers (Addendum V): V1 mean value and dispersion guard, V2 survival model (variables, transform, fit, expanding window, no look-ahead), V3 scope, V4 within-industry rank."""
import json
import math

import numpy as np
import pandas as pd
import pytest

from rebuild_harness.stage2 import layers as L
from rebuild_harness.stage2 import survival as S

INF = float("inf")


# ---- V1 -------------------------------------------------------------------------------------------------------------------------------------

def test_v1_mean_of_floored_draws_is_not_the_median():
    draws = [0.0, 0.0, 0.0, 10.0, 90.0]                      # per-share equity values; equity is floored at 0 by the engine
    assert L.v1_value_ps(draws) == pytest.approx(20.0)
    assert float(np.median(draws)) == 0.0                    # the median ignores the right tail; the mean is the expectation
    assert L.v1_value_ps([]) is None


def test_v1_zero_is_a_value():
    assert L.v1_value_ps([0.0, 0.0]) == 0.0


def test_dispersion_cases():
    assert L.dispersion(10.0, 40.0) == pytest.approx(math.log(4.0))
    assert L.dispersion(0.0, 5.0) == INF                       # the lower tail is wiped out: widest
    assert math.isnan(L.dispersion(0.0, 0.0))                  # no draw has a positive value
    assert math.isnan(L.dispersion(None, 3.0))
    assert L.dispersion(2.0, 2.0) == 0.0                       # 0.0 is a value


def test_add_dispersion_columns():
    df = pd.DataFrame({"vp_p10": [1.0, 0.0, 0.0], "vp_p90": [math.exp(2.0), 1.0, 0.0]})
    out = L.add_dispersion(df)
    assert out["disp"].iloc[0] == pytest.approx(2.0)
    assert out["disp"].iloc[1] == INF
    assert math.isnan(out["disp"].iloc[2])


# ---- V3, V4 -------------------------------------------------------------------------------------------------------------------------------

def test_v3_commodity_out_of_scope():
    df = pd.DataFrame({"family": ["operating", "commodity", "financial", None]})
    assert L.v3_in_scope(df).tolist() == [True, False, True, True]


def test_v4_rank_within_industry_with_small_industry_fallback():
    n = 12
    df = pd.DataFrame({"date": ["d"] * (2 * n + 2), "industry": ["A"] * n + ["B"] * n + ["tiny", "tiny"], "x": list(range(n)) + list(range(100, 100 + n)) + [-5.0, 500.0]})
    r = L.v4_rank(df, "x", min_industry=5)
    assert r.iloc[:n].tolist() == pytest.approx(r.iloc[n:2 * n].tolist())          # each industry ranks from 0 to 1 on its own
    assert r.iloc[0] < r.iloc[n - 1]
    wide = df.groupby("date")["x"].transform(L.fxm.rank_nan)
    assert r.iloc[-2] == pytest.approx(wide.iloc[-2]) and r.iloc[-1] == pytest.approx(wide.iloc[-1])      # a 2-name industry takes the date-wide rank, not dropped
    df.loc[3, "x"] = np.nan
    assert math.isnan(L.v4_rank(df, "x", min_industry=5).iloc[3])


def test_v2_score_is_mean_times_survival():
    assert L.v2_score([2.0, 0.0], [0.25, 0.5]).tolist() == [1.5, 0.0]
    assert np.isnan(L.v2_score([2.0], [np.nan])[0])


# ---- V2 variables ---------------------------------------------------------------------------------------------------------------------------

SV = {"current_assets": 200.0, "current_liabilities": 100.0, "cash": 50.0, "st_investments": 10.0, "debt": 300.0, "finance_leases": 20.0, "operating_income": 60.0, "da": 40.0,
      "interest_expense": 20.0, "ocf": 70.0}


def test_raw_features_ordinary_company():
    f = S.raw_features(SV, "operating")
    assert f["cur_ratio"] == pytest.approx(2.0)
    assert f["nd_ebitda"] == pytest.approx((300 + 20 - 60) / 100.0)
    assert f["int_cov"] == pytest.approx(3.0)
    assert f["ocf_neg"] == 0.0
    assert f["burn_inv"] == 0.0 and f["financial"] == 0.0


def test_raw_features_ebit_fallback_when_da_not_filed():
    f = S.raw_features(dict(SV, da=None), "operating")
    assert f["nd_ebitda"] == pytest.approx((300 + 20 - 60) / 60.0)


def test_raw_features_distress():
    f = S.raw_features(dict(SV, operating_income=-30.0, da=10.0, ocf=-40.0, cash=20.0, st_investments=None), "operating")
    assert f["nd_ebitda"] == INF                                    # negative EBITDA with positive net debt
    assert f["int_cov"] == pytest.approx(-1.5)
    assert f["ocf_neg"] == 1.0
    assert f["burn_inv"] == pytest.approx(40.0 / 20.0)               # one year of burn is twice the liquid assets: a runway of half a year
    g = S.raw_features(dict(SV, cash=0.0, st_investments=0.0, ocf=-1.0), "operating")
    assert g["burn_inv"] == INF                                      # burning against no liquid assets
    h = S.raw_features(dict(SV, operating_income=-30.0, da=10.0, debt=0.0, finance_leases=None, cash=500.0), "operating")
    assert h["nd_ebitda"] == 0.0                                      # net cash with a negative EBITDA: 0.0 is a value


def test_raw_features_no_interest_and_missing():
    assert S.raw_features(dict(SV, interest_expense=0.0), "operating")["int_cov"] == INF
    assert math.isnan(S.raw_features(dict(SV, interest_expense=None), "operating")["int_cov"])        # not filed while debt is outstanding: unknown
    assert S.raw_features(dict(SV, interest_expense=None, debt=0.0), "operating")["int_cov"] == INF
    f = S.raw_features({}, "financial")
    assert f["financial"] == 1.0 and all(math.isnan(f[k]) for k in S.FEATURES if k != "financial")
    assert math.isnan(S.raw_features(dict(SV, current_liabilities=0.0), "operating")["cur_ratio"])


# ---- V2 transform and fit -------------------------------------------------------------------------------------------------------------------

def _toy(n=4000, seed=1, base=-4.0):
    rng = np.random.default_rng(seed)
    cur = np.exp(rng.normal(0.5, 0.6, n))
    lev = rng.normal(2.0, 2.0, n)
    ocfneg = (rng.random(n) < 0.2).astype(float)
    z = base - 1.2 * (cur - 1.6) + 0.5 * lev + 1.5 * ocfneg
    y = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(float)
    X = np.column_stack([cur, lev, np.where(rng.random(n) < 0.1, INF, rng.normal(5, 3, n)), ocfneg, np.where(ocfneg > 0, rng.random(n), 0.0), np.zeros(n)])
    return X, y


def test_transform_uses_training_statistics_and_winsorises_infinities():
    X, _ = _toy()
    tf = S.Transform.fit(X)
    Z = tf.apply(X)
    assert np.isfinite(Z).all()
    j = S.FEATURES.index("int_cov")
    assert tf.hi["int_cov"] < INF
    # +inf sits at the upper cut
    zi = tf.apply(np.array([[1.0, 1.0, INF, 0.0, 0.0, 0.0]]))[0, j]
    zc = tf.apply(np.array([[1.0, 1.0, tf.hi["int_cov"], 0.0, 0.0, 0.0]]))[0, j]
    assert zi == pytest.approx(zc)
    # missing -> the training mean -> 0 after standardising
    assert tf.apply(np.array([[np.nan] * 6]))[0].tolist() == [0.0] * 6
    # a validation value is standardised with the TRAINING mean, not its own
    far = tf.apply(np.array([[100.0, 100.0, 100.0, 1.0, 1.0, 0.0]]))
    assert far[0, 0] == pytest.approx((tf.hi["cur_ratio"] - tf.mean["cur_ratio"]) / tf.sd["cur_ratio"])


def test_ridge_logistic_recovers_signs_and_ranks():
    X, y = _toy(n=20000)
    tf = S.Transform.fit(X)
    b0, b = S.fit_ridge_logistic(tf.apply(X), y)
    j = {k: i for i, k in enumerate(S.FEATURES)}
    assert b[j["cur_ratio"]] < 0 and b[j["nd_ebitda"]] > 0 and b[j["ocf_neg"]] > 0
    p = S._sigmoid(b0 + tf.apply(X) @ b)
    assert S.auc(p, y) > 0.7
    assert abs(p.mean() - y.mean()) < 0.005                         # calibrated in the mean


def test_ridge_makes_a_separable_sample_finite():
    Z = np.array([[-1.0, 0.0], [-0.5, 0.0], [0.5, 0.0], [1.0, 0.0]] * 5)
    y = np.array([0, 0, 1, 1] * 5, dtype=float)
    b0, b = S.fit_ridge_logistic(Z, y)
    assert np.isfinite(b0) and np.isfinite(b).all() and b[0] > 0


def test_auc():
    assert S.auc(np.array([0.1, 0.2, 0.8, 0.9]), np.array([0, 0, 1, 1])) == 1.0
    assert S.auc(np.array([0.5, 0.5, 0.5, 0.5]), np.array([0, 1, 0, 1])) == 0.5
    assert math.isnan(S.auc(np.array([0.1, 0.2]), np.array([0, 0])))


# ---- labels and the expanding window ------------------------------------------------------------------------------------------------------

def _events(tmp_path, items):
    p = tmp_path / "events_all.json"
    p.write_text(json.dumps([{"cik": c, "date": d, "class": k, "evidence": []} for c, d, k in items]), encoding="utf-8")
    return S.load_fail_events(p)


def test_label_window_and_classes(tmp_path):
    ev = _events(tmp_path, [("1", "2021-02-01", "bankruptcy"), ("2", "2021-02-01", "acquisition_completed"), ("3", "2022-03-31", "delisted_other"), ("4", "2021-03-31", "exit_record_still_reporting")])
    assert S.label_failure("0000000001", "2020-03-31", ev) == 1
    assert S.label_failure("0000000002", "2020-03-31", ev) == 0               # an acquisition is not a failure
    assert S.label_failure("0000000004", "2020-03-31", ev) == 0               # not a failure class
    assert S.label_failure("0000000003", "2021-03-31", ev) == 1               # 2022-03-31 is the last day of the window (t + 12 months)
    assert S.label_failure("0000000003", "2020-12-31", ev) == 0               # beyond the window
    assert S.label_failure("0000000001", "2021-02-01", ev) == 0               # strictly after t
    assert S.label_failure("0000000099", "2020-03-31", ev) == 0               # no events: 0 is a value


def test_label_known_before_the_valuation_date(tmp_path):
    ev = _events(tmp_path, [("1", "2021-03-31", "bankruptcy")])
    assert S.label_failure("0000000001", "2020-03-31", ev) == 1
    assert S.label_failure("0000000001", "2020-03-31", ev, known_before="2021-03-31") == 0       # the event is dated on T: not known at T
    assert S.label_failure("0000000001", "2020-03-31", ev, known_before="2021-04-01") == 1


def test_training_mask_expanding_window():
    dates = pd.Series(["2019-12-31", "2020-03-31", "2020-06-30", "2021-03-31"])
    assert S.training_mask(dates, "2021-03-31").tolist() == [True, True, False, False]
    assert S.training_mask(dates, "2020-12-31").tolist() == [True, False, False, False]
    assert S.training_mask(dates, "2020-12-30").tolist() == [False, False, False, False]      # the 12 months of 2019-12-31 end on 2020-12-31: not yet resolved on the 30th


def _obs(tmp_path):
    rng = np.random.default_rng(7)
    rows, items = [], []
    k = 0
    for d in ("2018-03-31", "2018-06-30", "2018-09-30", "2018-12-31", "2019-03-31", "2019-06-30", "2019-09-30", "2019-12-31", "2020-03-31"):
        for i in range(600):
            cik = f"{i:010d}"
            weak = i < 40
            rows.append({"date": d, "cik": cik, "family": "operating", "cur_ratio": 0.6 if weak else 2.0, "nd_ebitda": 6.0 if weak else 1.0, "int_cov": 1.0 if weak else 8.0,
                         "ocf_neg": 1.0 if weak else 0.0, "burn_inv": 1.0 if weak else 0.0, "financial": 0.0})
            if weak and rng.random() < 0.4:
                k += 1
                items.append((cik, (pd.Timestamp(d) + pd.DateOffset(months=5)).strftime("%Y-%m-%d"), "bankruptcy"))
    return pd.DataFrame(rows), _events(tmp_path, items)


def test_fit_for_date_uses_only_resolved_observations(tmp_path):
    obs, ev = _obs(tmp_path)
    m = S.fit_for_date(obs, "2019-12-31", ev)
    assert m is not None and m.train_dates[-1] == "2018-12-31"               # 2019-03-31 + 12 months is after 2019-12-31... and 2018-12-31 + 12 months is 2019-12-31: resolved
    assert "2019-03-31" not in m.train_dates
    assert m.coef[S.FEATURES.index("cur_ratio")] < 0 and m.coef[S.FEATURES.index("nd_ebitda")] > 0
    # a model for an earlier date cannot know a later date's events: perturbing the later observations leaves it unchanged
    obs2 = obs.copy()
    late = obs2["date"] >= "2019-03-31"
    obs2.loc[late, "cur_ratio"] = 99.0
    ev2 = dict(ev)
    ev2["0000000500"] = np.array(["2019-12-31", "2020-01-15"], dtype="datetime64[D]")     # dated on T, and after T: neither is known at T
    m2 = S.fit_for_date(obs2, "2019-12-31", ev2)
    assert m2.intercept == pytest.approx(m.intercept) and np.allclose(m2.coef, m.coef)
    assert m2.n_train == m.n_train


def test_fit_for_date_no_model_without_events(tmp_path):
    obs, ev = _obs(tmp_path)
    assert S.fit_for_date(obs, "2018-09-30", ev) is None                      # nothing is resolved yet
    assert S.fit_for_date(obs, "2019-12-31", {}) is None                      # no failures in the training set: undefined, not zero


def test_predict_is_a_probability_and_weak_names_score_higher(tmp_path):
    obs, ev = _obs(tmp_path)
    m = S.fit_for_date(obs, "2020-03-31", ev)
    p = m.predict(obs[obs["date"] == "2020-03-31"][list(S.FEATURES)].to_numpy())
    assert ((p > 0) & (p < 1)).all()
    assert p[:40].mean() > 5 * p[40:].mean()
    d = m.as_dict()
    assert set(d["coef"]) == set(S.FEATURES) and d["n_events"] == m.n_events and d["asof"] == "2020-03-31"


def test_with_features_from_panel_columns():
    keys = ("current_assets", "current_liabilities", "cash", "st_investments", "debt", "operating_income", "da", "interest_expense", "ocf", "finance_leases")
    row = {"family": "operating"}
    for k in keys:
        row["sv_" + k] = SV.get(k)
    row["sv_cash"] = np.nan
    out = S.with_features(pd.DataFrame([row]))
    assert out["cur_ratio"].iloc[0] == pytest.approx(2.0)
    assert math.isnan(out["nd_ebitda"].iloc[0])                              # cash not filed: net debt unknown


def test_fit_is_stable_when_groups_are_collinear_and_probabilities_saturate(tmp_path):
    """Identical covariates inside two groups (a Newton step without line search sends the intercept to -1e14): the fit must return the group frequencies."""
    obs, ev = _obs(tmp_path)
    tr = obs[S.training_mask(obs["date"], "2020-03-31")]
    y = np.array([S.label_failure(c, d, ev, known_before="2020-03-31") for c, d in zip(tr["cik"], tr["date"])], dtype=float)
    tf = S.Transform.fit(tr[list(S.FEATURES)].to_numpy(dtype=float))
    Z = tf.apply(tr[list(S.FEATURES)].to_numpy(dtype=float))
    b0, b = S.fit_ridge_logistic(Z, y)
    p = S._sigmoid(b0 + Z @ b)
    weak = (tr["cur_ratio"] < 1).to_numpy()
    assert abs(b0) < 50 and np.abs(b).max() < 50
    assert p[weak].mean() == pytest.approx(y[weak].mean(), abs=0.05)             # ridge shrinks slightly; the group frequency is recovered
    assert p[~weak].mean() < 0.01
    A = np.column_stack([np.ones(len(y)), Z])
    grad = A.T @ (y - p) - np.concatenate([[0.0], S.RIDGE * b])
    assert np.abs(grad).max() < 1e-3                                              # converged: the penalised score is zero


# ---- the development pass rule and the table helpers -----------------------------------------------------------------------------------------

def _metrics(lower=0.05, early=0.1, late=0.1, s_early=0.02, s_late=0.02, g_lower=0.04, g_spread=0.01):
    from rebuild_harness.stage2 import devcheck as DC
    m = {}
    for b in DC.BOUNDS:
        m[b] = {"B1_all": {"lower90": lower, "beta": 0.1}, "B1_2020_2022": {"beta": early}, "B1_2023_2024": {"beta": late},
                "B2_all": {"spread_resid": 0.02}, "B2_2020_2022": {"spread_resid": s_early}, "B2_2023_2024": {"spread_resid": s_late},
                "B1_all_guard": {"lower90": g_lower, "beta": 0.05}, "B2_all_guard": {"spread_resid": g_spread}}
    return DC, m


def test_pass_rule_all_conditions():
    DC, m = _metrics()
    r = DC.pass_rule(m)
    assert r["PASS"] and r["P1_B1_lower_bound_positive_all_bounds"] and r["P4_dispersion_guard_holds"]


@pytest.mark.parametrize("kw,key", [({"lower": -0.001}, "P1_B1_lower_bound_positive_all_bounds"), ({"late": -0.01}, "P2_B1_point_positive_each_subperiod_all_bounds"),
                                    ({"s_early": 0.0}, "P3_B2_positive_each_subperiod_all_bounds"), ({"g_lower": 0.0}, "P4_dispersion_guard_holds"),
                                    ({"g_spread": -0.001}, "P4_dispersion_guard_holds")])
def test_pass_rule_each_condition_can_fail(kw, key):
    DC, m = _metrics(**kw)
    r = DC.pass_rule(m)
    assert not r[key] and not r["PASS"]                                  # zero is not positive; one failing bound or period fails the condition


def test_pass_rule_one_bound_fails_and_missing_counts_as_failure():
    DC, m = _metrics()
    m["minus100"]["B1_all"] = {"lower90": -0.01}
    assert not DC.pass_rule(m)["PASS"]
    DC, m = _metrics()
    m["last_close"]["B1_all"] = None
    assert not DC.pass_rule(m)["P1_B1_lower_bound_positive_all_bounds"]
    DC, m = _metrics()
    m["excluded"]["B1_2020_2022"] = {"beta": float("nan")}
    assert not DC.pass_rule(m)["P2_B1_point_positive_each_subperiod_all_bounds"]


def test_auc_table_by_period():
    from rebuild_harness.stage2 import devcheck as DC
    rows = []
    for d in ("2020-03-31", "2023-03-31"):
        for i in range(100):
            rows.append({"date": d, "year": int(d[:4]), "pfail": i / 100.0, "fail12": 1.0 if i >= 95 else 0.0})
    t = DC.auc_table(pd.DataFrame(rows))
    assert t["pooled"]["auc"] == 1.0 and t["sub_2020_2022"]["events"] == 5 and t["sub_2023_2024"]["n"] == 100 and t["mean_within_date_auc"] == 1.0


def test_variants_use_the_layers_in_order():
    from rebuild_harness.stage2 import devcheck as DC
    n = 30
    df = pd.DataFrame({"date": ["2020-03-31"] * n, "industry": ["A"] * n, "family": ["operating"] * (n - 3) + ["commodity"] * 3, "vp": np.linspace(0.1, 2, n), "vp_mean": np.linspace(0.2, 4, n),
                       "pfail": np.linspace(0.0, 0.5, n), "vp_p10": 1.0, "vp_p90": 2.0})
    v = {lab: (frame, col) for lab, frame, col in DC.build_variants(df)}
    assert len(v) == 8
    f, c = v["V1+V2+V3 mean x (1-P), commodity out (THE CONFIGURATION)"]
    assert (f["family"] != "commodity").all() and len(f) == n - 3
    assert f[c].tolist() == pytest.approx((f["vp_mean"] * (1 - f["pfail"])).tolist())
    f0, c0 = v["V0 registered median, all families"]
    assert len(f0) == n and (f0[c0] == f0["vp"]).all()
