"""Addenda AD R3/R8 and AE.1-AE.3: the reported diagnostics."""
import numpy as np
import pytest

from rebuild_harness.gate2 import diagnostics as dg


def world(n=80, p1_better=True, seed=0):
    rng = np.random.default_rng(seed)
    rows, outs = [], {}
    for c in range(n):
        for d in ("2025-10-31", "2025-12-31"):
            key = f"{d}_{c:010d}"
            y = rng.normal(0.05, 0.05)
            arm = lambda e: {"growth": {"p50": y + e}, "margin": {"p50": y + e}, "margin_base": 0.0}
            good, bad = rng.normal(0, 0.01), rng.normal(0, 0.08)
            rows.append({"key": key, "date": d, "cik": f"{c:010d}", "family": "operating", "decisions": [], "positions": {},
                         "muse_p1": arm(good if p1_better else bad), "code": arm(bad if p1_better else good), "muse": arm(good if p1_better else bad),
                         "persistence": arm(bad), "pop_median": arm(bad), "t4q": arm(bad)})
            outs[key] = {"quarters": {"q1": {"revenue_growth": y, "operating_margin_change": y}}}
    return rows, outs


def test_filing_skill_needs_pass1_to_beat_the_code_population_median_and_persistence():
    rows, outs = world(p1_better=True)
    for b in ("code", "pop_median", "persistence"):
        r = dg.compare(rows, outs, "muse_p1", b, "growth", draws=200)
        assert r["a_better"] is True and r["n"] == 160 and set(r["by_date"]) == {"2025-10-31", "2025-12-31"}
    rows, outs = world(p1_better=False)
    assert dg.compare(rows, outs, "muse_p1", "code", "growth", draws=200)["a_better"] is False


def test_compare_skips_missing_forecasts_and_wrong_families():
    rows, outs = world(n=5)
    rows[0]["code"]["growth"] = None
    rows[1]["family"] = "financial"
    r = dg.compare(rows, outs, "muse_p1", "code", "growth", draws=50)
    assert r["n"] == 8


def test_g4_strict_counts_toward_price_revisions_without_a_new_filing_quote():
    rows = [{"decisions": [{"proposed": True, "toward_price": True, "new_quote_from_filing": False, "accepted": False},
                           {"proposed": True, "toward_price": True, "new_quote_from_filing": True, "accepted": True},
                           {"proposed": True, "toward_price": False, "accepted": True}, {"proposed": False}]}]
    r = dg.r3c(rows)
    assert r["n_proposed"] == 3 and r["n_toward_without_new_filing_quote"] == 1 and r["share"] == pytest.approx(1 / 3) and r["passes"] is False
    assert dg.r3c([{"decisions": []}])["vacuous"] is True


def test_repeatability_reads_shifts_and_flags_multi_sampling():
    main = [{"key": "k", "positions": {"g1": {"percentile": 60, "width": "normal"}, "m": {"percentile": 40, "width": "normal"}}}]
    rep = [{"key": "k", "positions": {"g1": {"percentile": 60, "width": "normal"}, "m": {"percentile": 70, "width": "normal"}}}]
    r = dg.r8(main, rep)
    assert r["n_inputs"] == 2 and r["median_abs_shift"] == 15 and r["share_identical"] == 0.5 and r["multi_sample_required"] is True


# ---- Addendum AH: the run-rate arms and the annual target -------------------------------------------------------------------------------------

def test_baseline_arms_read_the_runrate_and_its_population_median():
    base = {"companies": {"k": {"baselines": {"growth": {"persistence": 0.2, "t4q": 0.1}}, "runrate": {"growth": 0.05, "margin": 0.0}}},
            "pop_median": {"d": {"operating": {"growth": 0.07}}}, "pop_median_runrate": {"d": {"operating": {"growth": 0.06, "margin": -0.01}}}}
    arms = dg._baseline_arms({"key": "k", "date": "d", "family": "operating"}, base)
    assert arms["persist_rr"]["growth"] == {"p50": 0.05} and arms["persist_rr"]["margin"] == {"p50": 0.0}          # 0.0 is a value
    assert arms["popmed_rr"]["margin"] == {"p50": -0.01} and arms["persistence"]["growth"] == {"p50": 0.2} and arms["t4q"]["margin"] is None
    assert all(a["margin_base"] == 0.0 for a in arms.values())


def test_the_annual_target_reads_only_ok_outcomes_and_rote_for_financials():
    oc = {"annual": {"status": "ok", "revenue_growth": 0.1, "operating_margin_change": 0.0, "rote_change": -0.02}, "quarters": {"q1": {"revenue_growth": 0.3}}}
    assert dg.target_value(oc, "annual", "growth", "operating") == 0.1 and dg.target_value(oc, "annual", "margin", "operating") == 0.0
    assert dg.target_value(oc, "annual", "margin", "financial") == -0.02 and dg.target_value(oc, "q1", "growth", "operating") == 0.3
    assert dg.target_value({"annual": {"status": "year1_not_filed_by_scoring_date"}}, "annual", "growth", "operating") is None


def test_compare_on_the_annual_target_and_c1_reads_the_runrate_arms():
    rows, outs = world(p1_better=True)
    for r in rows:
        r["persist_rr"], r["popmed_rr"] = r["persistence"], r["pop_median"]
    for k, o in outs.items():
        y = o["quarters"]["q1"]["revenue_growth"]
        o["annual"] = {"status": "ok", "revenue_growth": y, "operating_margin_change": y}
    r = dg.compare(rows, outs, "muse_p1", "persist_rr", "growth", draws=200, target="annual")
    assert r["target"] == "annual" and r["n"] == 160 and r["a_better"] is True
    assert dg.C1_ARMS == ("code", "persist_rr", "popmed_rr")


def test_run_end_to_end_on_mock_runs_reports_both_targets_and_the_c1_reading(tmp_path):
    import json
    from rebuild_harness.gate2 import sample as sample_mod, scoring as sc
    from rebuild_harness.gate2.tests.test_scoring_outcomes_freeze import run_mock
    from rebuild_harness.gate2 import stage2_layer as sl
    smp = run_mock(tmp_path, n=3)
    sl.write_pfail({sl.job_key(j["date"], j["cik"]): {"status": "ok", "p_fail": 0.05} for j in sample_mod.jobs(smp)}, "m", "s", tmp_path)
    rows, _s, _e = sc.load_rows(tmp_path)
    outs, comps = {}, {}
    for r in rows:
        q = {"revenue_growth": 0.05, "operating_margin_change": 0.01, "rote_change_annualised_on_tbv_at_T": 0.01}
        outs[r["key"]] = {"key": r["key"], "quarters": {"q1": q},
                          "annual": {"status": "ok", "revenue_growth": 0.04, "operating_margin_change": 0.0, "rote_change": 0.0}}
        comps[r["key"]] = {"baselines": {"growth": {"persistence": 0.03, "t4q": 0.03}, "margin": {"persistence": 0.0, "t4q": 0.0}},
                           "runrate": {"growth": 0.02, "margin": 0.0}}
    po, pb = tmp_path / "o.jsonl", tmp_path / "b.json"
    po.write_text("\n".join(json.dumps(v) for v in outs.values()), encoding="utf-8")
    pb.write_text(json.dumps({"companies": comps, "pop_median": {}, "pop_median_runrate": {}}), encoding="utf-8")
    rep = dg.run(tmp_path, po, pb, draws=50)
    assert set(rep) >= {"R3a", "R3a_annual", "R3b", "R3b_annual", "R3c", "C1_rule"}
    g = rep["R3a"]["growth"]
    assert set(g) >= {"code", "persist_rr", "popmed_rr", "persistence", "pop_median", "t4q", "filing_skill"}
    assert g["persist_rr"]["n"] > 0 and g["popmed_rr"]["n"] == 0 and g["filing_skill"] is None      # no population median given: C1 cannot be read, never assumed
    assert rep["R3a_annual"]["growth"]["persist_rr"]["target"] == "annual" and rep["R3a_annual"]["growth"]["persist_rr"]["n"] == g["persist_rr"]["n"]
