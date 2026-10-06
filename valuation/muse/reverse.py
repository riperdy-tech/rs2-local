"""reverse.py - the reverse valuation (SPEC_muse_passes section 3, "Reverse valuation, by Python").

For each input Muse was asked about, with ALL OTHER inputs held at their pass-1 medians (the prior's quantile at the position's percentile; curve inputs at
their positioned curve), find the percentile u of the POPULATION PRIOR of that input at which the value per share equals today's price.
  * "the median IV" of the spec is the value of the engine's chain at point inputs (every other input at its pass-1 median, this input at the prior's
    u-quantile), rolled forward to the valuation date and divided by the share count of the engine's state. It is a deterministic evaluation, not the median
    of a simulation (the simulation's median differs from the chain at median inputs because the chain is non-linear).
  * u is searched on a grid of 1% steps inside P1..P99 and refined by bisection where the value minus the price changes sign. A draw the engine cannot
    value (terminal growth at or above the discount rate) is skipped, never repaired. When several crossings exist the one nearest the input's own pass-1
    percentile is reported and all are listed.
  * No crossing inside P1..P99: "not_reachable", with the direction (the price is above or below every value in P1..P99). It is an extraordinary
    assumption too (it lies outside P5..P95).
  * A required percentile outside P5..P95 is flagged `extraordinary` (Addendum C 5; ChatGPT's correction of Gemini: the price is evidence of
    expectations, not of the company's future, so the flag raises the evidence bar for the side that relies on it and never moves a forecast).
The base prior set is the one Muse was shown; the discount rate is the price-free one (book D/E, Addendum B 3).
"""
from __future__ import annotations

from typing import List, Mapping, Optional

from valuation.common import DrawInvalid
from valuation.engine_financial import financial_chain
from valuation.engine_operating import operating_chain
from valuation.priors_interface import PriorSet

from .mapping import Position, positioned_curves
from .schema import (EXTRAORDINARY_HI, EXTRAORDINARY_LO, INPUTS, LEVEL, REVERSE_HI, REVERSE_LO, muse_inputs, prior_distribution)

ENGINE_LEVEL_INPUTS = {"operating": ("g1", "g_terminal", "margin_target", "ronic"), "commodity": ("g1", "g_terminal", "margin_target", "ronic"),
                       "financial": ("g1", "g_terminal", "rote_target")}
GRID_STEP = 0.01


def point_value_per_share(family: str, st: dict, point: Mapping[str, float], curves: Mapping, disc, shares: Optional[float], *,
                          operating_leases_in_cash_flow: bool = True, maint_gap_floor: Optional[float] = 0.0) -> Optional[float]:
    """The chain's equity value per share at point inputs, or None (an invalid draw, or no share count)."""
    if not shares:
        return None
    try:
        if family == "financial":
            r = financial_chain(st, dict(point), dict(curves), disc)
        else:
            r = operating_chain(st, dict(point), dict(curves), disc, operating_leases_in_cash_flow=operating_leases_in_cash_flow,
                                maint_gap_floor=maint_gap_floor)
    except DrawInvalid:
        return None
    return r["equity"] / shares


def pass1_point(base: PriorSet, family: str, st: dict, positions: Mapping[str, Position]):
    """(point inputs, curve positions {name: q}) at the pass-1 medians; an input with no position sits at the prior's median (level) or keeps the measured
    curve (curve input)."""
    point = {}
    for n in ENGINE_LEVEL_INPUTS[family]:
        dist = base.inputs[n]
        pos = positions.get(n)
        point[n] = dist.ppf(0.5 if pos is None else pos.percentile / 100.0)
    q = {}
    for n in muse_inputs(family):
        if INPUTS[n]["kind"] == LEVEL:
            continue
        dist = prior_distribution(base, n, st)
        if dist is not None and n in positions:
            q[n] = dist.ppf(positions[n].percentile / 100.0)
    return point, q


def reverse_valuation(base: PriorSet, family: str, st: dict, positions: Mapping[str, Position], disc, price_per_share: float,
                      shares: Optional[float], **chain_kw) -> dict:
    """The reverse valuation for every input in `positions` that has a prior (see the module docstring)."""
    out = {"price_per_share": price_per_share, "inputs": {}, "status": "ok"}
    if not shares or price_per_share is None or price_per_share <= 0:
        out["status"] = "refused"
        out["reason"] = "a positive price and a share count are needed"
        return out
    point0, q0 = pass1_point(base, family, st, positions)

    def value(point, q):
        curves, _nc, _s = positioned_curves(base, family, st, q)
        return point_value_per_share(family, st, point, curves, disc, shares, **chain_kw)

    out["iv_at_pass1_medians"] = value(point0, q0)
    for name, pos in positions.items():
        dist = prior_distribution(base, name, st)
        if dist is None:
            continue
        level = INPUTS[name]["kind"] == LEVEL

        def f(u, name=name, dist=dist, level=level):
            if level:
                p = dict(point0)
                p[name] = dist.ppf(u)
                return value(p, q0)
            q = dict(q0)
            q[name] = dist.ppf(u)
            return value(point0, q)

        n = int(round((REVERSE_HI - REVERSE_LO) / GRID_STEP))
        grid = [round(REVERSE_LO + k * GRID_STEP, 10) for k in range(n + 1)]
        vals = [(u, f(u)) for u in grid]
        valid = [(u, v - price_per_share) for u, v in vals if v is not None]
        rec = {"input": name, "pass1_percentile": pos.percentile, "valid_points": len(valid), "grid_points": len(grid)}
        if not valid:
            rec.update(status="not_available", reason="the engine cannot value any point of the grid", extraordinary=None)
            out["inputs"][name] = rec
            continue
        crossings: List[float] = []
        for (ua, da), (ub, db) in zip(valid, valid[1:]):
            if ub - ua > GRID_STEP * 1.5:
                continue                                  # an invalid stretch lies between: do not bridge it
            if da == 0.0:
                crossings.append(ua)
            elif da * db < 0.0:
                lo, hi, dlo = ua, ub, da
                for _ in range(60):
                    mid = 0.5 * (lo + hi)
                    vm = f(mid)
                    if vm is None:
                        break
                    dm = vm - price_per_share
                    if dm == 0.0:
                        lo = hi = mid
                        break
                    if (dm < 0.0) == (dlo < 0.0):
                        lo, dlo = mid, dm
                    else:
                        hi = mid
                crossings.append(0.5 * (lo + hi))
        if valid[-1][1] == 0.0:
            crossings.append(valid[-1][0])
        if crossings:
            u0 = pos.percentile / 100.0
            u_star = min(crossings, key=lambda c: abs(c - u0))
            rec.update(status="ok", required_percentile=u_star * 100.0, required_value=dist.ppf(u_star), crossings=[c * 100.0 for c in crossings],
                       extraordinary=bool(u_star < EXTRAORDINARY_LO or u_star > EXTRAORDINARY_HI), direction=None)
        else:
            if all(d > 0 for _, d in valid):
                direction = "the price is below every value inside P1..P99"
            elif all(d < 0 for _, d in valid):
                direction = "the price is above every value inside P1..P99"
            else:
                direction = "no crossing could be located (the engine cannot value part of P1..P99)"
            nearest = min(valid, key=lambda t: abs(t[1]))[0]
            rec.update(status="not_reachable", required_percentile=None, required_value=None, crossings=[], extraordinary=True, direction=direction,
                       nearest_percentile=nearest * 100.0)
        out["inputs"][name] = rec
    out["extraordinary_inputs"] = sorted(n for n, r in out["inputs"].items() if r.get("extraordinary"))
    return out
