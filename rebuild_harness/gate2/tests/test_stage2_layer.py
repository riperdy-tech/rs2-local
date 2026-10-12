"""The Stage 2 configuration on both arms (Addenda V, W): V1 value = mean, V2 survival weighting from a point-in-time model, V3 commodity out of scope.  Synthetic data only."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rebuild_harness.gate2 import config, freeze_content, scoring as sc, stage2_layer as sl
from rebuild_harness.gate2 import sample as sample_mod
from rebuild_harness.gate2.tests import fakes
from rebuild_harness.gate2.tests.test_scoring_outcomes_freeze import run_mock
from rebuild_harness.stage2 import survival as S


# ---- V1 and V2: the value -----------------------------------------------------------------------------------------------------------------

def test_the_value_is_the_mean_times_the_survival_probability_and_zero_is_a_value():
    assert sl.value_ps(12.0, 0.25) == pytest.approx(9.0)
    assert sl.value_ps(0.0, 0.1) == 0.0                                    # a mean of 0.0 is a value, not an absence
    assert sl.value_ps(7.0, 0.0) == 7.0                                    # P(fail) 0.0 is a value too
    for bad in ((None, 0.1), (5.0, None), (float("nan"), 0.1), (5.0, float("inf")), (True, 0.1)):
        assert sl.value_ps(*bad) is None


def _result(mean_code, p50_code, mean_muse, p50_muse):
    return {"status": "ok", "family": "operating", "asof": "2025-10-31",
            "code_only": {"iv_per_share": {"mean": mean_code, "p50": p50_code}, "result": {"forecast_year1": {"growth": {"p50": 0.05}, "margin": {"p50": 0.1}}}},
            "final": {"iv_per_share": {"mean": mean_muse, "p50": p50_muse}, "result": {"forecast_year1": {"growth": {"p50": 0.05}, "margin": {"p50": 0.1}}}}, "redteam": {"decisions": []}}


def test_a_scoring_row_carries_the_mean_times_survival_for_both_arms_and_keeps_the_median_as_a_diagnostic():
    row = sc.row_from_run(_result(12.0, 10.0, 15.0, 11.0), {"key": "k", "cik": "1", "price_info": {"price": 10.0}}, None, 0.2)
    assert row["code"]["iv"] == pytest.approx(9.6) and row["muse"]["iv"] == pytest.approx(12.0)
    assert row["code"]["iv_p50"] == 10.0 and row["muse"]["iv_p50"] == 11.0 and row["p_fail"] == 0.2
    none = sc.row_from_run(_result(12.0, 10.0, 15.0, 11.0), {"key": "k", "cik": "1", "price_info": {"price": 10.0}}, None, None)
    assert none["code"]["iv"] is None and none["muse"]["iv"] is None       # no probability: the arm has no value, never a silent unweighted one


def test_the_loader_scores_the_stage2_value_and_counts_what_it_leaves_out(tmp_path, monkeypatch):
    smp = run_mock(tmp_path, n=3)
    jobs = sample_mod.jobs(smp)
    table = {sl.job_key(j["date"], j["cik"]): {"status": "ok", "p_fail": 0.1} for j in jobs}
    drop = sl.job_key(jobs[0]["date"], jobs[0]["cik"])
    table[drop] = {"status": "ok", "p_fail": None}                         # a company-date the preparation could not give a probability
    sl.write_pfail(table, "m", "s", tmp_path)
    rows, statuses, excl = sc.load_rows(tmp_path)
    # Addendum AJ.2: the row stays for the forecast bars (G1, G3, G4, G6) and is counted; only the return bar (G2) leaves it out
    assert len(rows) == len(jobs) and excl["no_value_per_share_g2_only"] == 1
    kept = [r for r in rows if r["key"] == drop][0]
    assert kept["code"]["iv"] is None and kept["muse"]["iv"] is None
    assert all(r["p_fail"] == 0.1 and r["code"]["iv"] > 0 and r["muse"]["iv"] > 0 for r in rows if r["key"] != drop)
    obs, ex2 = sc.ic_rows(rows, {r["key"]: {"returns": {"3": {"bounds": {"excluded": 0.01}}}} for r in rows}, "3", "excluded")
    assert drop not in {o["key"] for o in obs} and ex2["no_value_per_share"] == 1
    monkeypatch.setattr(config, "OUT_OF_SCOPE_FAMILIES", ("financial",))   # V3: a row of an out-of-scope family is never scored
    rows2, _s, excl2 = sc.load_rows(tmp_path)
    assert all(r["family"] != "financial" for r in rows2) and excl2["out_of_scope_family_v3"] >= 1


def test_without_the_probability_file_scoring_refuses(tmp_path):
    run_mock(tmp_path, n=1)
    with pytest.raises(FileNotFoundError, match="survival probabilities"):
        sc.load_rows(tmp_path)


# ---- the point-in-time model ---------------------------------------------------------------------------------------------------------------

def _pool(rng, quarters, n=300):
    rows = []
    for q in quarters:
        for i in range(n):
            ocf_neg = float(rng.random() < 0.2)
            rows.append({"date": q, "cik": f"{i:010d}", "family": "operating", "cur_ratio": float(rng.lognormal(0.3, 0.4)), "nd_ebitda": float(rng.normal(2, 2)),
                         "int_cov": float(rng.normal(6, 4)), "ocf_neg": ocf_neg, "burn_inv": ocf_neg * float(rng.random()), "financial": 0.0})
    return pd.DataFrame(rows)


def _events(pool, rng):
    """Failures follow cash-flow-negative companies, six months after the observation."""
    ev = {}
    for _, r in pool[pool["ocf_neg"] == 1.0].iterrows():
        if rng.random() < 0.3:
            t = pd.Timestamp(r["date"]) + pd.DateOffset(months=6)
            ev.setdefault(r["cik"], []).append(np.datetime64(t.date()))
    return {k: np.sort(np.array(v, dtype="datetime64[D]")) for k, v in ev.items()}


QUARTERS = ["2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31", "2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31", "2024-06-30"]


def test_each_models_training_window_ends_twelve_months_before_its_date_and_no_event_on_or_after_T_counts():
    rng = np.random.default_rng(1)
    pool = _pool(rng, QUARTERS)
    events = _events(pool, rng)
    models = sl.fit_models(["2024-03-31", "2024-06-30"], pool, events)
    m1, m2 = models["2024-03-31"], models["2024-06-30"]
    assert max(m1["train_dates"]) == "2023-03-31" and max(m2["train_dates"]) == "2023-06-30"       # t + 12 months <= T, nothing later
    assert m2["n_train"] > m1["n_train"] and m1["ridge"] == S.RIDGE == 1.0 and m1["features"] == list(S.FEATURES)
    # an event dated ON T (and one after it) is not known at T: adding such events leaves the model for T unchanged
    late = dict(events)
    cik = pool["cik"].iloc[0]
    late[cik] = np.sort(np.concatenate([late.get(cik, np.array([], dtype="datetime64[D]")), np.array(["2024-06-30", "2024-09-30"], dtype="datetime64[D]")]))
    again = sl.fit_models(["2024-06-30"], pool, late)["2024-06-30"]
    assert again["n_events"] == m2["n_events"] and again["coef"] == m2["coef"] and again["intercept"] == m2["intercept"]
    # the model is informative: cash-flow-negative companies get the higher probability
    m = S.SurvivalModel.from_dict(m2)
    healthy = np.array([[2.0, 1.0, 8.0, 0.0, 0.0, 0.0]])
    burning = np.array([[0.8, 6.0, 0.5, 1.0, 0.6, 0.0]])
    assert m.predict(burning)[0] > m.predict(healthy)[0]


def test_a_date_with_too_few_failures_has_no_model_and_the_fit_says_so():
    rng = np.random.default_rng(2)
    pool = _pool(rng, QUARTERS[:3], n=50)
    with pytest.raises(RuntimeError, match="no survival model can be fitted for 2023-06-30"):
        sl.fit_models(["2023-06-30"], pool, {})


def test_the_probability_of_a_company_date_comes_from_its_dates_model_and_its_own_items(monkeypatch):
    rng = np.random.default_rng(3)
    pool = _pool(rng, QUARTERS)
    model = S.SurvivalModel.from_dict(sl.fit_models(["2024-06-30"], pool, _events(pool, rng))["2024-06-30"])
    items = {"healthy": {"current_assets": 200.0, "current_liabilities": 100.0, "cash": 80.0, "st_investments": 0.0, "debt": 50.0, "operating_income": 60.0, "da": 10.0,
                         "interest_expense": 5.0, "ocf": 55.0},
             "burning": {"current_assets": 40.0, "current_liabilities": 80.0, "cash": 5.0, "st_investments": 0.0, "debt": 300.0, "operating_income": -20.0, "da": 5.0,
                         "interest_expense": 30.0, "ocf": -25.0}}
    from rebuild_harness.forensics import analytics as A
    import valuation.common as vc
    monkeypatch.setattr(vc, "build_state", lambda pit: {"stub": True})
    monkeypatch.setattr(A, "solvency_inputs", lambda pit, st: items[pit])
    ph, pb = sl.pfail_of(model, "healthy", "operating"), sl.pfail_of(model, "burning", "operating")
    assert 0.0 < ph["p_fail"] < pb["p_fail"] < 1.0 and ph["model_asof"] == "2024-06-30"
    assert pb["features"]["ocf_neg"] == 1.0 and ph["features"]["cur_ratio"] == pytest.approx(2.0)
    json.dumps(pb)                                                          # infinities and NaN are written as JSON-safe values


class _Env:
    def __init__(self, items):
        self.items = items

    def company_inputs(self, job):
        from rebuild_harness.gate2 import env as env_mod
        if job["cik"] == "0000000009":
            return env_mod.Refusal("refused", ["no_price"])
        return type("CI", (), {"pit": self.items[job["cik"]], "family": job["family"]})()


def test_the_table_gives_every_company_date_a_probability_or_the_runners_own_refusal(monkeypatch):
    rng = np.random.default_rng(4)
    pool = _pool(rng, QUARTERS)
    models = {"2025-10-31": S.SurvivalModel.from_dict(sl.fit_models(["2024-06-30"], pool, _events(pool, rng))["2024-06-30"])}
    from rebuild_harness.forensics import analytics as A
    import valuation.common as vc
    monkeypatch.setattr(vc, "build_state", lambda pit: {})
    monkeypatch.setattr(A, "solvency_inputs", lambda pit, st: pit)
    ok = {"current_assets": 10.0, "current_liabilities": 5.0, "cash": 3.0, "debt": 1.0, "operating_income": 2.0, "da": 1.0, "interest_expense": 0.1, "ocf": 2.0}
    jobs = [{"date": "2025-10-31", "cik": "0000000001", "family": "operating"}, {"date": "2025-10-31", "cik": "0000000009", "family": "operating"}]
    t = sl.build_pfail_table(jobs, _Env({"0000000001": ok}), models, log=lambda *a: None)
    assert t["2025-10-31_0000000001"]["status"] == "ok" and 0.0 < t["2025-10-31_0000000001"]["p_fail"] < 1.0
    assert t["2025-10-31_0000000009"] == {"status": "refused", "p_fail": None, "reasons": ["no_price"]}


# ---- written once, and named in the freeze -----------------------------------------------------------------------------------------------

def test_the_probability_file_is_written_once_and_the_freeze_section_names_it(tmp_path):
    t = {"2025-10-31_0000000001": {"status": "ok", "p_fail": 0.02}}
    sha = sl.write_pfail(t, "msha", "ssha", tmp_path)
    with pytest.raises(FileExistsError):
        sl.write_pfail(t, "msha", "ssha", tmp_path)
    assert sl.load_pfail(tmp_path) == t and sl.sha256_file(sl.stage2_paths(tmp_path)["pfail"]) == sha
    sec = freeze_content.stage2_section(tmp_path)
    assert sec["survival_pfail"]["sha256"] == sha and sec["survival_models"] is None and sec["out_of_scope_families"] == ["commodity"]
    assert set(sec["layers"]) == {"V1", "V2", "V3"}


def test_addendum_ak5_only_an_evidenced_pre_model_error_leaves_the_technical_status_count(tmp_path):
    import json as _json
    from rebuild_harness.gate2 import config as _cfg, scoring as _sc
    p = _cfg.state_paths(tmp_path)["progress"]
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"key": "2026-04-30_0000000001", "status": "error", "n_calls": 0}, {"key": "2026-04-30_0000000002", "status": "error", "n_calls": 3}]
    p.write_text("\n".join(_json.dumps(x) for x in lines), encoding="utf-8")
    good = {"corrected_status": "engine_refused", "model_calls": 0, "commit": "d2bacbd"}
    ev = {"2026-04-30_0000000001": good, "2026-04-30_0000000002": good, "2026-04-30_0000000003": good}
    assert set(_sc.reproduced_refusal_keys(tmp_path, ev)) == {"2026-04-30_0000000001"}       # an error after model calls, or an unknown key, never qualifies
    assert _sc.reproduced_refusal_keys(tmp_path, {"2026-04-30_0000000001": dict(good, model_calls=1)}) == {}
