"""The bisection of the diagnostic closure ERP (rebuild_harness.gate1_closure): synthetic monotone functions, both directions, and the no-root case."""
from rebuild_harness.gate1_closure import bisect_closure


def _f(root, scale=3.0):
    return lambda x: (scale * (root - x), {})


def test_finds_a_root_below_the_start():
    res = bisect_closure(_f(0.021), 0.052, _f(0.021)(0.052)[0], tol=5e-5)
    assert res["status"] == "ok" and abs(res["erp"] - 0.021) <= 5e-5 and abs(res["g"]) <= 3.0 * 5e-5


def test_finds_a_root_above_the_start():
    res = bisect_closure(_f(0.0705), 0.0472, _f(0.0705)(0.0472)[0], tol=5e-5)
    assert res["status"] == "ok" and abs(res["erp"] - 0.0705) <= 5e-5


def test_exact_start_and_no_root():
    assert bisect_closure(_f(0.04), 0.04, 0.0, tol=5e-5)["status"] == "exact"
    res = bisect_closure(lambda x: (-0.5 - x, {}), 0.04, -0.54, tol=5e-5)         # the function is negative everywhere: no root at or above the floor
    assert res["status"] == "no_root_above_floor" and res["erp"] == 0.0005
