"""variants.py - DIAGNOSTIC switches for the level decomposition (Addendum J1).  Nothing here changes a default: every engine takes `variant=None`, and with None (or a
neutral Variant) its arithmetic and its draws are exactly the registered engine's (tests compare them bit for bit).

A Variant swaps ONE component of the engine to a stated alternative, so that the change in the value distribution is that component's contribution:

  terminal_g      "rule" | "flat"            the terminal growth: min(rf, 3.75%) (Addendum H2) -> 3.75% flat (b)
  terminal_ronic  "j3" | "industry_median" | "wacc"
                                              the operating / commodity terminal return on new capital: WACC + kappa (I - WACC) floored at WACC (Addendum J3) -> the industry
                                              median floored at WACC (round 3's rule) -> WACC (c).  The FINANCIAL analogue (the terminal excess return over the cost of equity,
                                              Addendum I4): "industry_median" = kappa 1 (the full median excess), "wacc" = kappa 0 (no terminal excess)
  growth_decay    "measured" | "none"        the measured growth-decay curve -> g1 held for years 1-5, then a linear fade over years 6..N to the measured curve's own last value (d); a
                                              horizon of 5 years or fewer holds g1 throughout
  margin          "drawn" | "held" | "instant"
                                              the drawn year-5 margin level moved to along the measured curve -> the margin held at the base year's (operating, commodity: m_5 = m_0; financial:
                                              the ROTE target = the base-year ROTE) (e); "instant" (commodity only, h): no normalization curve, the drawn level from year 1
  reinvestment    "priced" | "zero"          growth reinvestment priced at the return on new capital -> zero for a growing year, explicit and terminal (f); a shrinking year's working-capital
                                              release stays
  width           1.0 | 0.5                  every judgment input's distribution about its P50 -> scaled by this factor (g); the P50s, so the point values, are unchanged

(a), the equity risk premium, is a swap of the `Rates` object in the harness, not an engine switch.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping

from .common import Curve, QuantileDist


@dataclass(frozen=True)
class Variant:
    name: str = "base"
    terminal_g: str = "rule"
    terminal_ronic: str = "j3"
    growth_decay: str = "measured"
    margin: str = "drawn"
    reinvestment: str = "priced"
    width: float = 1.0

    def __post_init__(self):
        for field, allowed in (("terminal_g", ("rule", "flat")), ("terminal_ronic", ("j3", "industry_median", "wacc")), ("growth_decay", ("measured", "none")),
                               ("margin", ("drawn", "held", "instant")), ("reinvestment", ("priced", "zero"))):
            if getattr(self, field) not in allowed:
                raise ValueError(f"Variant.{field} must be one of {allowed}, not {getattr(self, field)!r}")
        if not (0.0 < self.width <= 1.0):
            raise ValueError("Variant.width must lie in (0, 1]")

    @property
    def neutral(self) -> bool:
        return (self.terminal_g, self.terminal_ronic, self.growth_decay, self.margin, self.reinvestment, self.width) == ("rule", "j3", "measured", "drawn", "priced", 1.0)


def is_neutral(variant) -> bool:
    return variant is None or variant.neutral


def no_decay_curve(curve: Curve) -> Curve:
    """(d) d_t = 1 for t <= 5 (g1 held), then a linear fade from 1 at t = 5 to the measured curve's own last value d_N at t = N (the same endpoint, so the explicit path still
    ends where the measured one does); N <= 5: d_t = 1 throughout."""
    n = len(curve)
    last = curve.values[-1]
    vals = [1.0 if (t <= 5 or n <= 5) else 1.0 + (last - 1.0) * (t - 5) / (n - 5) for t in range(1, n + 1)]
    return Curve(vals, curve.name + " [no decay: g1 held 5 years, then linear fade to the measured last value]", curve.source)


def scaled_dist(d: QuantileDist, width: float) -> QuantileDist:
    """(g) every quantile moved toward the P50 by `width`: q' = P50 + width (q - P50); the P50 is unchanged."""
    if width == 1.0:
        return d
    p50 = d.ppf(0.5)
    return QuantileDist({p: p50 + width * (v - p50) for p, v in d.q}, d.label + f" [width x{width:g}]")


def scaled_dists(dists: Mapping[str, QuantileDist], width: float) -> Dict[str, QuantileDist]:
    return {k: scaled_dist(v, width) for k, v in dists.items()}


def apply_to_curves(variant, curves: Mapping[str, Curve]) -> Dict[str, Curve]:
    out = dict(curves)
    if variant is not None and variant.growth_decay == "none":
        out["growth_decay"] = no_decay_curve(out["growth_decay"])
    return out
