"""C6 / C4: the closure solver, on synthetic aggregates with hand-computed answers."""
import pickle

import pytest

from backtest_phase2 import closure
from backtest_phase2.tests import helpers as h


def perpetuity_total(erp, names, rf_eff=0.03, g=0.02):
    """sum of cf_i / (rf_eff + adj_i erp - g) over the closure set: V_i x shares_i in closed form."""
    return sum(cf / (rf_eff + adj * erp - g) for cf, adj in names)


NAMES = [(100.0, 1.0), (50.0, 0.67 * 0.5 + 0.33), (20.0, 1.3), (5.0, 0.8)]


def test_bisection_finds_the_premium_that_closes_the_aggregate():
    target = perpetuity_total(0.05, NAMES)                                # the aggregate cap is what a 5% premium produces
    erp, flag = closure.solve_erp(lambda e: perpetuity_total(e, NAMES), target)
    assert flag is None
    assert erp == pytest.approx(0.05, abs=1e-12)
    assert closure.closure_gap(perpetuity_total(erp, NAMES), target) < 1e-12


def test_eighty_iterations_and_registered_bounds():
    assert closure.ITERATIONS == 80 and closure.ERP_LOW == 0.0005 and closure.ERP_HIGH == 0.20
    calls = []

    def total(e):
        calls.append(e)
        return perpetuity_total(e, NAMES)

    closure.solve_erp(total, perpetuity_total(0.08, NAMES))
    assert len(calls) == 2 + 80                                            # the two bounds, then 80 halvings


def test_no_root_uses_the_nearer_bound_and_flags_the_date():
    huge = perpetuity_total(closure.ERP_LOW, NAMES) * 2                    # the aggregate cap is above anything the model can produce
    erp, flag = closure.solve_erp(lambda e: perpetuity_total(e, NAMES), huge)
    assert (erp, flag) == (closure.ERP_LOW, "bound_low")
    tiny = perpetuity_total(closure.ERP_HIGH, NAMES) / 2                   # ... or below anything it can produce
    erp, flag = closure.solve_erp(lambda e: perpetuity_total(e, NAMES), tiny)
    assert (erp, flag) == (closure.ERP_HIGH, "bound_high")


def test_closure_gap_is_relative_to_the_aggregate_cap():
    assert closure.closure_gap(101.0, 100.0) == pytest.approx(0.01)
    assert closure.closure_gap(100.0, 100.0) == 0.0


def tiny_world(tmp_path, k=6):
    """k identical-in-kind synthetic names that are their own aggregate; the closure job's end-to-end input."""
    pop, agg = [], []
    for i in range(k):
        rows = h.company(growth=0.04 + 0.005 * i, margin=0.12 + 0.01 * i, shares=100.0)
        nm = h.nm_of(rows, m=0.05, sector="Industrials", y_L=0.01)
        nm.update(cik=f"{i:010d}", adjL=0.8 + 0.1 * i, cap=3000.0 + 700.0 * i, price=30.0 + 5 * i, in_U=True, u_reason=None)
        pop.append(nm)
        agg.append({"cik": nm["cik"], "market_cap": nm["cap"]})
    d = {"year": "2099", "pop": pop, "agg": {"constituents": agg}}
    p = tmp_path / "inputs_2099.pkl"
    p.write_bytes(pickle.dumps(d))
    return p, pop


def test_closure_job_closes_a_synthetic_aggregate_end_to_end(run, tmp_path):
    p, pop = tiny_world(tmp_path)
    job = {"type": "date_candidate", "inputs": str(p), "rf": 0.0066, "rf_eff": 0.0325, "gA": 0.0325, "pi": 0.0134, "coe_mkt_B": 0.09}
    r = run("candidate", job)
    cl = r["closure"]
    assert cl["flag"] is None and cl["members"] == len(pop)
    assert cl["gap"] <= 1e-6                                                # C4
    assert cl["sum_cap"] == pytest.approx(sum(nm["cap"] for nm in pop))
    assert cl["sum_value_x_shares"] == pytest.approx(cl["sum_cap"], rel=1e-9)
    # V_S of every member, recomputed from the reported per-share values, adds to the cap
    tot = sum(r["S"][nm["cik"]]["value"] * nm["shares"] for nm in pop)
    assert tot == pytest.approx(cl["sum_cap"], rel=1e-9)
    # the registered rate: COE_i = rf_eff + adjL x ERP_S
    for nm in pop:
        assert r["S"][nm["cik"]]["coe"] == pytest.approx(0.0325 + nm["adjL"] * cl["erp_S"])


def test_closure_set_is_fixed_and_excludes_names_without_a_positive_value_at_erp_b(run, tmp_path):
    p, pop = tiny_world(tmp_path)
    d = pickle.loads(p.read_bytes())
    d["pop"][0]["m"] = None                                                  # no growth rate: no value in any arm
    p.write_bytes(pickle.dumps(d))
    job = {"type": "date_candidate", "inputs": str(p), "rf": 0.0066, "rf_eff": 0.0325, "gA": 0.0325, "pi": 0.0134, "coe_mkt_B": 0.09}
    r = run("candidate", job)
    assert r["closure"]["members"] == len(pop) - 1
    assert r["S"][pop[0]["cik"]]["value"] is None and r["S"][pop[0]["cik"]]["reason"] == "m_missing"
    assert r["closure"]["sum_cap"] == pytest.approx(sum(nm["cap"] for nm in pop[1:]))


def test_variant_b_uses_the_baselines_premium_and_variant_a_drops_the_floor(run, tmp_path):
    p, pop = tiny_world(tmp_path)
    job = {"type": "date_baseline", "inputs": str(p), "rf": 0.0066, "rf_eff": 0.0325, "gA": 0.0325, "pi": 0.0134, "coe_mkt_B": 0.09}
    r = run("baseline", job)
    assert r["erp_B"] == pytest.approx(0.09 - 0.0325) and r["erp_a"] == pytest.approx(0.09 - 0.0066)
    nm = pop[0]
    assert r["B"][nm["cik"]]["coe"] == pytest.approx(0.0325 + nm["adjL"] * (0.09 - 0.0325))
    assert r["a"][nm["cik"]]["coe"] == pytest.approx(0.0066 + nm["adjL"] * (0.09 - 0.0066))
    cand = run("candidate", dict(job, type="date_candidate"))
    assert cand["b"][nm["cik"]]["coe"] == pytest.approx(r["B"][nm["cik"]]["coe"])   # variant b: ERP_S := ERP_B
