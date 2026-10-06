"""Outcomes (SPEC section 6): total-return excess over SPY at 3, 6, 12, 24 and 36 months where the price data allows, and the fundamental
outcomes of the first subsequent annual reports, as first filed.

THE ONLY MODULE THAT READS A RETURN OR A POST-DATE FILING.  Engines never import it.  `coverage_only=True` answers "does the bar exist" and never
forms a ratio, so a smoke run can report coverage without reading a return.
"""
from valuation.pit_data import to_date, is_num
from . import fundamentals

HORIZONS = (3, 6, 12, 24, 36)
BENCHMARK = "SPY"


def horizon_outcome(pit, key, asof, months, benchmark=BENCHMARK, coverage_only=False):
    """{"ret", "bench", "excess", "available"} for one security and horizon.  Total return = adjusted close at the horizon date over the
    adjusted close at `asof`, minus 1; a security with no bar at the horizon (delisted, or beyond the data) is not available - nothing is
    imputed, and the caller counts them."""
    src = pit.price_source
    d1 = src.target_date(asof, months)
    a0 = src.adj_close(key, asof) if src.has_key(key) else None
    a1 = src.adj_close(key, d1) if src.has_key(key) else None
    b0 = src.adj_close(benchmark, asof) if src.has_key(benchmark) else None
    b1 = src.adj_close(benchmark, d1) if src.has_key(benchmark) else None
    avail = a0 is not None and a1 is not None and b0 is not None and b1 is not None
    out = {"available": avail, "ret": None, "bench": None, "excess": None}
    if coverage_only or not avail:
        return out
    ret, bench = a1.price / a0.price - 1.0, b1.price / b0.price - 1.0
    out.update(ret=ret, bench=bench, excess=ret - bench)
    return out


def horizon_outcomes(pit, key, asof, horizons=HORIZONS, benchmark=BENCHMARK, coverage_only=False):
    return {h: horizon_outcome(pit, key, asof, h, benchmark, coverage_only) for h in horizons}


def fundamental_outcomes(pit, cik, base_fye, ks=(1, 2, 3)):
    """The first-filed fundamentals of the k-th fiscal year after the base year (k = 1: the FIRST annual report filed after the valuation date).
    {k: {"fye", "filed", "measures", ...} or None}.  The year must follow the base year by one fiscal year (350-380 days) each step: a gap
    (a missed filing, a delisting, a changed year end) is None, never bridged.  Values are as first filed - never a later restatement."""
    fys = pit.outcome_fiscal_years(cik)
    order = sorted(fys)
    out = {k: None for k in ks}
    if base_fye not in fys:
        return out
    i = order.index(base_fye)
    prev = fys[base_fye]
    chain = [prev]
    for step in range(1, max(ks) + 1):
        if i + step >= len(order):
            break
        nxt = fys[order[i + step]]
        gap = (to_date(nxt.fye) - to_date(chain[-1].fye)).days
        if not 350 <= gap <= 380:
            break
        chain.append(nxt)
        if step in out:
            row, prow = nxt.row(), chain[-2].row()
            out[step] = {"fye": nxt.fye, "filed": nxt.exists_from, "own_accn": nxt.own_accn, "stamps": list(nxt.stamps),
                         "measures": fundamentals.measures(row, prow)}
    return out
