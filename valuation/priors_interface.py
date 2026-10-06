"""priors_interface.py - what the engines ask the population priors for, and a clearly labelled placeholder until T-priors delivers.

A `Priors` object answers `for_company(family, state, asof) -> PriorSet`:

  inputs : {name: QuantileDist}       the judgment inputs, as P10..P90 (P5/P25/P75/P95 optional), conditional on the company's state
  curves : {name: Curve}              measured curves: growth decay, margin retention (A2), return-on-new-capital fade, ...
  refs   : {name: callable}           population references for the secondary cross-checks (see each engine)

Input names by family (SPEC section 4):
  operating and commodity : g1 (year-1 revenue growth), g_terminal (may be negative), margin_target (long-run operating margin),
                            ronic (return on new invested capital, year 1)
  financial               : g1 (growth of tangible book), g_terminal, rote_target (long-run return on tangible equity)
Curves: operating: growth_decay, margin_retention, ronic_fade. commodity: the same, with margin_retention = refs["normalization_curve"]
(cyclicality score) when the engine asks for it. financial: growth_decay, rote_retention, excess_fade.
Curve convention: year t = 1..N holds the fraction of the initial gap still present in year t (see common.Curve).

PlaceholderPriors exists so the plumbing and the tests can run. Its numbers are arbitrary round figures. They are NOT measurements, they are
not conditioned on any population, and nothing built on them is a valuation. Every PriorSet it returns has placeholder=True, and the
engines copy that flag into their result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from .common import Curve, InputError, QuantileDist, exp_curve

PLACEHOLDER_LABEL = "PLACEHOLDER_NOT_A_MEASUREMENT"


@dataclass
class PriorSet:
    family: str
    inputs: Dict[str, QuantileDist]
    curves: Dict[str, Curve]
    refs: Dict[str, Callable] = field(default_factory=dict)
    source: str = ""
    placeholder: bool = False


class Priors:
    def for_company(self, family: str, state: dict, asof) -> PriorSet:   # pragma: no cover - interface
        raise NotImplementedError


def _linear_to_zero(n: int, name: str) -> Curve:
    """1 at year 1 falling in equal steps to 0 at year n."""
    return Curve([1.0 - (t - 1) / (n - 1) for t in range(1, n + 1)], name, PLACEHOLDER_LABEL)


class PlaceholderPriors(Priors):
    """Round-number stand-ins (see the module docstring). Construction needs the explicit flag."""

    HORIZON = 10

    def __init__(self, i_understand_tests_only: bool):
        if not i_understand_tests_only:
            raise InputError("PlaceholderPriors is for tests and plumbing; pass i_understand_tests_only=True")

    def for_company(self, family: str, state: dict, asof) -> PriorSet:
        n = self.HORIZON
        gl = state.get("growth_latest")
        gl = 0.0 if gl is None else gl
        g1 = QuantileDist({0.10: gl - 0.10, 0.25: gl - 0.05, 0.50: gl, 0.75: gl + 0.05, 0.90: gl + 0.10}, PLACEHOLDER_LABEL)
        gT = QuantileDist({0.10: -0.01, 0.50: 0.02, 0.90: 0.03}, PLACEHOLDER_LABEL)
        curves = {"growth_decay": _linear_to_zero(n, "growth_decay"),
                  "margin_retention": exp_curve(n, 3.0, "margin_retention", PLACEHOLDER_LABEL),
                  "ronic_fade": _linear_to_zero(n, "ronic_fade")}
        refs: Dict[str, Callable] = {}
        if family in ("operating", "commodity"):
            m = state.get("op_margin_median")
            m = 0.10 if m is None else m
            inputs = {"g1": g1, "g_terminal": gT,
                      "margin_target": QuantileDist({0.10: m - 0.04, 0.50: m, 0.90: m + 0.04}, PLACEHOLDER_LABEL),
                      "ronic": QuantileDist({0.10: 0.06, 0.50: 0.12, 0.90: 0.25}, PLACEHOLDER_LABEL)}
            refs["ev_fcf_multiple"] = placeholder_ev_fcf_multiple
            refs["normalization_curve"] = placeholder_normalization_curve
        elif family == "financial":
            r = state.get("rote_median")
            r = 0.10 if r is None else r
            inputs = {"g1": g1, "g_terminal": gT,
                      "rote_target": QuantileDist({0.10: r - 0.04, 0.50: r, 0.90: r + 0.04}, PLACEHOLDER_LABEL)}
            curves = {"growth_decay": curves["growth_decay"],
                      "rote_retention": exp_curve(n, 3.0, "rote_retention", PLACEHOLDER_LABEL),
                      "excess_fade": _linear_to_zero(n, "excess_fade")}
            refs["ptbv_of_rote"] = placeholder_ptbv_of_rote
        else:
            raise InputError(f"no priors for family {family!r}")
        return PriorSet(family, inputs, curves, refs, PLACEHOLDER_LABEL, placeholder=True)


def placeholder_ev_fcf_multiple(state, draw, disc) -> Optional[float]:
    """PLACEHOLDER (not a population measure): the Gordon multiple on terminal growth, 1 / (WACC - g_terminal)."""
    d = disc.wacc - draw["g_terminal"]
    return None if d <= 0 else 1.0 / d


def placeholder_normalization_curve(score: float, horizon: int = PlaceholderPriors.HORIZON) -> Curve:
    """PLACEHOLDER (not the measured A2 curve): exponential reversion whose half-life shrinks as the cyclicality score rises."""
    return exp_curve(horizon, 4.0 * (1.0 - score) + 0.5, "normalization", PLACEHOLDER_LABEL)


def placeholder_ptbv_of_rote(rote: float, coe: float, g: float) -> Optional[float]:
    """PLACEHOLDER (not a population measure): the textbook justified price-to-tangible-book, (ROTE - g) / (COE - g)."""
    d = coe - g
    return None if d <= 0 else (rote - g) / d
