"""mapping.py - from Muse's placement (percentile + width) to the distribution the family engine draws from (SPEC_muse_passes section 2,
"Python mapping").

LEVEL INPUT (g1, g_terminal, margin_target, ronic, rote_target). With prior quantile function Q(u) and its median Q(0.5):
    chosen median  m = Q(percentile / 100)
    new quantile at level p:  m + k x (Q(p) - Q(0.5)),  k = WIDTH_FACTORS[width]  (narrow 0.5, normal 1, wide 1.5)
i.e. the prior's quantile function shifted so its median sits at the chosen percentile's value, with the prior's own spread (so its
interquartile range) scaled by k. At percentile 50 and width "normal" the result is the prior itself. The scale factors are a stated
convention; the calibration of SPEC_muse_passes section 4 replaces them once the replay has measured them.

CURVE INPUT (growth_persistence, margin_retention, rote_retention). The prior supplies the population distribution of
q = the fraction of the initial gap still open CURVE_REF_YEAR years out (schema.py). Muse's percentile picks q = Qc(percentile / 100).
The engine's measured curve v_t (v_1 first year) is re-shaped by the power transform v_t' = v_t ** a with a = ln(q) / ln(v_K), K =
CURVE_REF_YEAR: it hits q at year K, keeps the curve's own shape and order, and stays inside [0, 1]. A curve whose value at year K is
not strictly between 0 and 1 cannot be positioned that way: it is left as measured and the result says so. q <= 0 puts every year
below 1 at 0; q >= 1 holds the gap fully open. For the commodity family the curve is the normalization curve of the company's
cyclicality score (priors.refs["normalization_curve"]), which the commodity engine builds itself: the position is applied by
wrapping that reference.
The engines hold ONE curve per run, so Muse's WIDTH on a curve input is recorded but not propagated into the value distribution
(stamped `curve_width_not_propagated`); the curve input moves the point estimate, the level inputs carry the dispersion.

The engine is fed through `MusePriors`, a priors object that returns the already-built PriorSet with these replacements: no engine
code is changed and the prior shown to Muse is the very object the engine then draws from.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from valuation import engine_commodity, engine_financial, engine_operating
from valuation.common import Curve, QuantileDist, InputError
from valuation.priors_interface import PriorSet, Priors

from .schema import (CURVE_REF_YEAR, INPUTS, LEVEL, WIDTH_FACTORS, WIDTHS, prior_distribution)

CURVE_WIDTH_STAMP = "curve_width_not_propagated"


@dataclass
class Position:
    """Where Muse placed the company in the prior of one input."""
    percentile: float
    width: str
    status: str = "anchored"            # anchored | unanchored (checks failed twice: the prior's P50, width wide)
    source: str = "P1"                  # the step that produced the position: P1..P5 or P6 (red team)
    stamps: List[str] = field(default_factory=list)
    hard_evidence: bool = False         # outside P10..P90 and carried by a quote that passed the hard-evidence rule

    def as_dict(self) -> dict:
        return {"percentile": self.percentile, "width": self.width, "status": self.status, "source": self.source,
                "stamps": list(self.stamps), "hard_evidence": self.hard_evidence}


def unanchored(reason: str, source: str = "P1") -> Position:
    """The fallback of SPEC_muse_passes section 2: the prior's P50 with width wide, stamped."""
    return Position(50.0, "wide", "unanchored", source, ["unanchored: " + reason])


# ---- level inputs ----------------------------------------------------------------------------------------------------------------

def muse_distribution(prior: QuantileDist, percentile: float, width: str) -> QuantileDist:
    if width not in WIDTH_FACTORS:
        raise InputError(f"width must be one of {WIDTHS}, got {width!r}")
    if not (0.0 < percentile < 100.0):
        raise InputError("percentile must lie strictly between 0 and 100")
    k = WIDTH_FACTORS[width]
    med = prior.ppf(0.5)
    m = prior.ppf(percentile / 100.0)
    levels = [p for p, _ in prior.q]
    return QuantileDist({p: m + k * (prior.ppf(p) - med) for p in levels}, f"muse P{percentile:g} {width} on {prior.label}")


def percentile_of(dist: QuantileDist, x: float) -> float:
    """The probability level u in (0, 1) at which dist.ppf(u) = x (clamped to 1e-6 .. 1-1e-6 outside the range)."""
    lo, hi = 1e-6, 1.0 - 1e-6
    if x <= dist.ppf(lo):
        return lo
    if x >= dist.ppf(hi):
        return hi
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if dist.ppf(mid) < x:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---- curve inputs ----------------------------------------------------------------------------------------------------------------

def position_curve(base: Curve, q: float, k_ref: int = CURVE_REF_YEAR) -> Tuple[Curve, Optional[str]]:
    """(curve, stamp): `base` re-shaped so its value at year k_ref is q (see the module docstring); a stamp says when it could not be."""
    q = min(max(float(q), 0.0), 1.0)
    vk = base.at(k_ref)
    if abs(q - vk) < 1e-12:
        return base, None
    if not (0.0 < vk < 1.0):
        return base, f"curve not positionable: its value at year {k_ref} is {vk:g}, not strictly between 0 and 1; left as measured"
    if q <= 0.0:
        vals = [1.0 if v >= 1.0 else 0.0 for v in base.values]
    else:
        a = math.log(q) / math.log(vk)
        vals = [min(1.0, max(0.0, v ** a)) if v > 0.0 else 0.0 for v in base.values]
    return Curve(vals, base.name, f"{base.source} | positioned to {q:.4g} at year {k_ref}"), None


def positioned_curves(base: PriorSet, family: str, state: dict, q_by_name: Dict[str, float]):
    """(curves, normalization_ref, stamps): the base curves with every curve input in `q_by_name` positioned. For the commodity family
    `curves["margin_retention"]` is the normalization curve of the company's cyclicality score (what the commodity engine uses) and the
    returned `normalization_ref` wraps the prior's reference so the commodity engine builds the positioned curve itself."""
    curves = dict(base.curves)
    stamps: List[str] = []
    nc = base.refs.get("normalization_curve")
    horizon = len(curves["growth_decay"])
    if family == "commodity":
        score = ((state or {}).get("cyclicality") or {}).get("score")
        if nc is not None and score is not None:
            curves["margin_retention"] = nc(score, horizon)
    for name, q in q_by_name.items():
        cname = INPUTS[name]["curve"]
        if cname not in curves:
            stamps.append(f"{name}: the priors hold no curve {cname!r}; nothing to position")
            continue
        c, stamp = position_curve(curves[cname], q)
        curves[cname] = c
        if stamp:
            stamps.append(f"{name}: {stamp}")
    wrapped = nc
    if family == "commodity" and nc is not None and "margin_retention" in q_by_name:
        q = q_by_name["margin_retention"]

        def wrapped(score, horizon, _nc=nc, _q=q):               # noqa: E306 (a closure over the chosen position)
            return position_curve(_nc(score, horizon), _q)[0]
    return curves, wrapped, stamps


# ---- the prior set the engine draws from -----------------------------------------------------------------------------------------

def build_muse_prior_set(base: PriorSet, family: str, state: dict, positions: Dict[str, Position]) -> PriorSet:
    """A fresh PriorSet: level inputs replaced by their Muse distributions, curve inputs positioned. Inputs without a position (or
    without a prior) keep the prior as it is."""
    inputs = dict(base.inputs)
    q_by_name: Dict[str, float] = {}
    for name, pos in positions.items():
        dist = prior_distribution(base, name, state)
        if dist is None:
            continue
        if INPUTS[name]["kind"] == LEVEL:
            inputs[name] = muse_distribution(dist, pos.percentile, pos.width)
        else:
            q_by_name[name] = dist.ppf(pos.percentile / 100.0)
    curves, nc, stamps = positioned_curves(base, family, state, q_by_name)
    refs = dict(base.refs)
    if nc is not None and "normalization_curve" in refs:
        refs["normalization_curve"] = nc
    ps = PriorSet(base.family, inputs, curves, refs, (base.source + " | muse positions").strip(" |"), base.placeholder)
    ps.muse_stamps = stamps + ([CURVE_WIDTH_STAMP] if q_by_name else [])
    return ps


class MusePriors(Priors):
    """The priors object the engine is given for one company: the base PriorSet (the one Muse was shown) with Muse's positions applied."""

    def __init__(self, base: PriorSet, family: str, state: dict, positions: Dict[str, Position]):
        self.base, self.family, self.state, self.positions = base, family, state, positions

    def for_company(self, family, state, asof) -> PriorSet:
        if family != self.family:
            raise InputError(f"MusePriors was built for family {self.family!r}, asked for {family!r}")
        return build_muse_prior_set(self.base, self.family, self.state, self.positions)

    def stamps(self) -> List[str]:
        return list(build_muse_prior_set(self.base, self.family, self.state, self.positions).muse_stamps)


# ---- running the family engine -----------------------------------------------------------------------------------------------------

ENGINES = {"operating": engine_operating, "commodity": engine_commodity, "financial": engine_financial}


def run_engine(family: str, pit, priors: Priors, disc, *, n_draws: int = 2000, seed: int = 20261006, corr=None,
               price_per_share: Optional[float] = None, roll_forward: bool = True, **extra) -> dict:
    """The family's engine (engine_operating.run, engine_commodity.run or engine_financial.run) on `priors`."""
    mod = ENGINES[family]
    return mod.run(pit, priors, disc, n_draws=n_draws, seed=seed, corr=corr, price_per_share=price_per_share, roll_forward=roll_forward, **extra)


def per_share_summary(result: dict, shares: Optional[float]) -> Optional[dict]:
    """Per-share quantiles of an engine result's equity distribution (None without a share count or a distribution)."""
    eq = (result.get("distribution") or {}).get("equity")
    if eq is None or not shares:
        return None
    return {k: (v / shares if k.startswith("p") or k == "mean" else v) for k, v in eq.items() if k != "n"}
