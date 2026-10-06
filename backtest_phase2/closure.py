"""Backtest registration section 4.8: the candidate's closure.

Solve ERP_S in [0.0005, 0.20] so that  sum over C of max(V_S,i, 0) x shares_i  =  sum over C of cap_i  (C fixed for the
solve), by bisection with 80 iterations.  If no root lies inside the bounds the nearer bound is used and the date is flagged.
Pure: the total is a callable of the premium, so the same solver serves the real arms and the synthetic tests.
"""

ERP_LOW, ERP_HIGH, ITERATIONS = 0.0005, 0.20, 80


def solve_erp(total_at, target, lo=ERP_LOW, hi=ERP_HIGH, iterations=ITERATIONS):
    """(erp, flag) where `total_at(erp)` is the aggregate value (non-increasing in erp) and `target` the aggregate cap.

    flag is None for an interior root, "bound_low" when even the lowest premium leaves the aggregate value below the
    target (the root would be below `lo`; `lo` is used), "bound_high" when even the highest premium leaves it above the
    target (`hi` is used)."""
    f_lo, f_hi = total_at(lo), total_at(hi)
    if f_lo < target:
        return lo, "bound_low"
    if f_hi > target:
        return hi, "bound_high"
    a, b = lo, hi
    for _ in range(iterations):
        mid = (a + b) / 2.0
        if total_at(mid) > target:
            a = mid
        else:
            b = mid
    return (a + b) / 2.0, None


def closure_gap(total_value, total_cap):
    """|sum(V x shares) - sum(cap)| / sum(cap): the identity check of C4."""
    return abs(total_value - total_cap) / total_cap
