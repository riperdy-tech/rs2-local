"""engine_commodity.py - SPEC 3.3: mid-cycle cash flow for commodity and asset-heavy companies.

PRIMARY: the operating chain of engine_operating (same arithmetic, same equity bridge) on THROUGH-CYCLE margins and returns:
  * the long-run margin m_T (input, centred on the company's through-cycle median by the priors) is what the margin moves toward from the
    first year; the base year's margin m_0 is whatever was filed (a peak included) and is NOT held: the retention curve already has r_1 < 1,
    so normalization starts in year 1 (U4). A curve with r_1 = 1 would hold the peak a year: the result says so ("peak_held_year_1").
  * the speed is the measured normalization curve for the company's CYCLICALITY SCORE (priors.refs["normalization_curve"](score, horizon)).
    There is no cyclical/secular switch: the score is continuous (common.cyclicality_score, formulas in its docstring) and a company that
    cannot be scored (fewer than 6 annual years) is a refusal, not a default.
  * the Greenwald maintenance capex and the working-capital release of engine_operating apply unchanged.

SECONDARY CROSS-CHECK (an asset value, never averaged in):
  * oil and gas: the standardized measure of discounted future net cash flows (ASC 932; us-gaap
    StandardizedMeasureOfDiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReserves, else
    DiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReservesStandardizedMeasure) of the latest annual report filed before the valuation date,
    bridged like an enterprise value (debt, leases, minority interest out; cash and investments in). It values proved reserves after tax only.
  * elsewhere (vessels, plant), and for an oil and gas filer that does not file the tag: tangible book value as a replacement-cost PROXY.
    The result stamps it as a proxy.
  Both are carried to the valuation date by the same cost-of-equity roll-forward as the primary. model_disagreement = ln(primary median / secondary).
"""
from __future__ import annotations

from typing import Optional

from .common import CompanyPIT, build_state, equity_bridge, model_disagreement
from .discount_rate import DiscountRate
from . import engine_operating as op

ENGINE = "commodity"
ASC932_TAGS = ("StandardizedMeasureOfDiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReserves",
               "DiscountedFutureNetCashFlowsRelatingToProvedOilAndGasReservesStandardizedMeasure")


def latest_concept(pit: CompanyPIT, names):
    """(value, period_end, filed, accession, tag) of the newest annual value among `names` filed before asof, else None."""
    best = None
    for n in names:
        for pe, f in pit.concepts.get(n, {}).items():
            if best is None or pe > best[1]:
                best = (f.value, pe, f.filed, f.accession, n)
    return best


def asset_value_cross_check(pit: CompanyPIT, st: dict, disc: DiscountRate, *, oil_gas: bool, roll_forward: bool = True) -> dict:
    yrs = op.years_between(st["base_period"], disc.asof) if roll_forward else 0.0
    factor = (1.0 + disc.coe) ** yrs
    if oil_gas:
        sm = latest_concept(pit, ASC932_TAGS)
        if sm is not None:
            br = equity_bridge(sm[0], st)
            return {"kind": "asc932_standardized_measure", "equity": br["equity_value"] * factor, "standardized_measure": sm[0],
                    "period_end": sm[1], "filed": sm[2], "accession": sm[3], "tag": sm[4], "bridge": br["items"], "proxy": False,
                    "stamps": ["proved reserves only, after tax, at SEC prices; bridged like an enterprise value"]}
        why = "oil and gas filer with no standardized-measure tag in the companyfacts taxonomy (custom extension tags are not in it)"
    else:
        why = "not an oil and gas filer"
    if st.get("tbv") is None:
        return {"kind": None, "equity": None, "proxy": True, "stamps": [why, "tangible book not available"]}
    return {"kind": "tangible_book_proxy", "equity": st["tbv"] * factor, "tbv": st["tbv"], "proxy": True,
            "stamps": ["PROXY: tangible book value as a replacement-cost estimate; " + why]}


def run(pit: CompanyPIT, priors, disc: DiscountRate, *, oil_gas: Optional[bool] = None, n_draws: int = 2000, seed: int = 20261006,
        corr=None, price_per_share: Optional[float] = None, operating_leases_in_cash_flow: bool = True,
        maint_gap_floor: Optional[float] = 0.0, roll_forward: bool = True) -> dict:
    st = build_state(pit)
    gaps = op.state_gaps(st)
    cyc = st.get("cyclicality")
    if cyc is None:
        gaps.append(f"cyclicality score ({st.get('cyclicality_reason')})")
    if gaps:
        return op.refusal(ENGINE, [f"not available: {g}" for g in gaps], ticker=pit.ticker, asof=st.get("asof"))
    ps = priors.for_company("commodity", st, pit.asof)
    nc = ps.refs.get("normalization_curve")
    if nc is None:
        return op.refusal(ENGINE, ["priors supply no normalization curve (priors.refs['normalization_curve'])"], ticker=pit.ticker)
    horizon = len(ps.curves["growth_decay"])
    curves = {"margin_retention": nc(cyc["score"], horizon)}
    # the secondary is a level, not a per-draw value: the operating run is used with its own (per-draw) multiple switched off
    ps_refs = dict(ps.refs)
    ps_refs.pop("ev_fcf_multiple", None)
    ps.refs = ps_refs
    res = op.run(pit, _Fixed(ps), disc, n_draws=n_draws, seed=seed, corr=corr, price_per_share=price_per_share,
                 operating_leases_in_cash_flow=operating_leases_in_cash_flow, maint_gap_floor=maint_gap_floor, roll_forward=roll_forward,
                 state=st, engine=ENGINE, family="commodity", curves_override=curves)
    if res.get("status") != "ok":
        return res
    if oil_gas is None:
        sic = pit.sic.code if pit.sic else None
        oil_gas = bool(sic) and (sic[:3] in ("131", "132") or sic[:2] == "13")
    sec = asset_value_cross_check(pit, st, disc, oil_gas=oil_gas, roll_forward=roll_forward)
    res["secondary"] = sec
    res["cyclicality_score"] = cyc
    notes = res["notes"]
    r1 = curves["margin_retention"].at(1)
    res["normalization"] = {"curve_source": curves["margin_retention"].source, "retention_year_1": r1,
                            "peak_held_year_1": r1 >= 1.0}
    if r1 >= 1.0:
        notes.append("peak_held_year_1: the normalization curve keeps the base-year margin in year 1")
    if sec["equity"] is not None and res["distribution"]["equity"] is not None:
        md, why = model_disagreement(res["distribution"]["equity"]["p50"], sec["equity"])
        res["model_disagreement"], res["model_disagreement_note"] = md, why
    else:
        res["model_disagreement"], res["model_disagreement_note"] = None, "no secondary asset value available"
    return res


class _Fixed:
    """A priors object that returns an already built PriorSet (so the commodity run can strip the per-draw multiple)."""

    def __init__(self, ps):
        self._ps = ps

    def for_company(self, family, state, asof):
        return self._ps
