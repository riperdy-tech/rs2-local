"""erp_consistent.py - Addenda L1 and M (option B): the ENGINE-CONSISTENT implied equity risk premium.

THE PROBLEM (Addendum L1).  Damodaran's monthly implied ERP is the required return r that solves his index model - the S&P 500 level S, a base cash flow CF0 grown for five years at the analysts' expected
growth rate g, then growing at the risk-free rate rf for ever - less rf.  The engines' cash flows do not follow analysts' growth: they follow population base rates that fade growth far faster.  Pairing
the two undervalues systematically (Addendum I; the 10-01 review).

THE METHOD (Addendum M, option B, a DIFFERENTIAL).  The model's inputs are in Damodaran's monthly row (`DamodaranStore.monthly_model_row`): S (S&P 500), rf (T.Bond Rate), CF0 (the trailing-12-month cash
flow column) and g (Expected growth rate).  Re-solving the model with those inputs reproduces his plain trailing-12-month ERP to a median error of 0 bp, but his PUBLISHED "ERP (T12 m with sustainable
payout)" needs earnings and ROE that are not in the row (`scratch/rev23/gate1_dev/round5/erp_reproduction_check.md`: against the target the best column has a median error of +8 bp and a maximum of 178 bp).  So
the reproduced model is used only for a DIFFERENCE:

    r(g)   = the solution of   S = sum_{t=1..5} CF0 (1+g)^t / (1+r)^t  +  CF0 (1+g)^5 (1+rf) / (r - rf) / (1+r)^5
    delta  = r(g_engine) - r(g_damodaran)
    ERP    = Damodaran's published ERP (T12 m with sustainable payout) + delta

Both r's come from the same reproduced model with every other input identical, so the reproduction error largely cancels in delta.  The ERP never uses the engine's valuations (it is not the closure ERP of
round 3b); it replaces one assumption of Damodaran's method, the five-year growth, by the engine's own.

g_engine (Addendum L1): the cap-weighted mean, over the GATE UNIVERSE at T, of each company's mean of the P50 growth path of years 1-5, where the path is the engine's own, g_T + (g_1 - g_T) d_t with g_1
the P50 of the priors at T (point in time: the priors vintage of the date) and d the measured growth-decay curve, and the weights are the market capitalisations at T.  The gate universe is the companies of
the date that are prepared (an annual report known at T, a family the engine builds, a price and a market capitalisation of at least `MCAP_FLOOR`) and for which the priors supply a g_1 and a decay curve.  This is
ERP-independent: the valuation (and its refusals, which depend on the discount rate) is not consulted, so there is no circularity.  (For the financial family the engine's growth path grows tangible book; its
prior g_1 is the tangible-book growth, so a financial company's path is that.  The universe is reported by family.)

Everything here is arithmetic on numbers handed in; nothing is read from the network, a price or an outcome.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .common import DataNotPresent, InputError, terminal_growth_after

MODEL_YEARS = 5                    # Damodaran's model: explicit growth for five years, then growth at the risk-free rate
SOLVE_UPPER = 0.60                 # the search bracket's upper end for the required return (his own spreadsheet's solution lies far inside it)
SOLVE_TOL = 1e-14
SOLVE_MAX_ITER = 400
PLAUSIBLE_ERP = (0.0, 0.5)         # a result outside is a refusal, never clipped (the same bound as the published column's)
CONSISTENT_LABEL = "engine-consistent implied ERP (Addenda L1/M, option B)"


# ---- Damodaran's index model ---------------------------------------------------------------------------------------------------------

def model_value(r: float, S: float, cf0: float, g: float, rf: float, n: int = MODEL_YEARS) -> float:
    """The present value of the index model at the required return r, less the index level S (zero at the solution): n years of cash flow growing at g, then a perpetuity growing at rf."""
    c, pv = cf0, 0.0
    for t in range(1, n + 1):
        c *= 1.0 + g
        pv += c / (1.0 + r) ** t
    return pv + c * (1.0 + rf) / (r - rf) / (1.0 + r) ** n - S


def required_return(S: float, cf0: float, g: float, rf: float, n: int = MODEL_YEARS) -> float:
    """The required return r > rf that solves `model_value(r) = 0`, by bisection on (rf, SOLVE_UPPER).  The value falls monotonically in r (cash flows must be positive); a bracket that
    does not hold a root, or inputs that cannot define one, are a DataNotPresent naming the numbers - never a clipped or a guessed solution."""
    for name, v in (("S", S), ("CF0", cf0), ("g", g), ("rf", rf)):
        if v is None or not math.isfinite(v):
            raise DataNotPresent(f"the index model needs {name}; got {v!r}")
    if S <= 0 or cf0 <= 0:
        raise DataNotPresent(f"the index model needs a positive index level and cash flow (S={S}, CF0={cf0})")
    lo, hi = rf + 1e-9, SOLVE_UPPER
    f_lo, f_hi = model_value(lo, S, cf0, g, rf, n), model_value(hi, S, cf0, g, rf, n)
    if not (f_lo > 0.0 > f_hi):
        raise DataNotPresent(f"the index model has no root for the required return in ({rf:.4f}, {SOLVE_UPPER}) with S={S}, CF0={cf0}, g={g:.4f}, rf={rf:.4f} "
                             f"(value at the ends {f_lo:.4g}, {f_hi:.4g})")
    for _ in range(SOLVE_MAX_ITER):
        mid = 0.5 * (lo + hi)
        if model_value(mid, S, cf0, g, rf, n) > 0.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < SOLVE_TOL:
            break
    return 0.5 * (lo + hi)


# ---- the engine's growth ------------------------------------------------------------------------------------------------------------------

def growth_path(g1: float, g_term: float, decay, years: int = MODEL_YEARS) -> List[float]:
    """The engine's P50 growth of years 1..`years`: g_T + (g_1 - g_T) d_t for t up to the length N of the measured decay curve (`decay.at(t)`), and, for a curve shorter than `years`, the engine's
    perpetuity growth after year N (`common.terminal_growth_after`: g_T, or a negative last-year rate continuing) - the same arithmetic as the chain of `engine_operating` / `engine_financial`."""
    n = len(decay)
    path = [g_term + (g1 - g_term) * decay.at(t) for t in range(1, min(n, years) + 1)]
    if n < years:
        g_after, _basis = terminal_growth_after(path[-1], g_term)
        path += [g_after] * (years - n)
    return path


def mean_growth(path: Iterable[float]) -> float:
    xs = list(path)
    if not xs:
        raise InputError("an empty growth path")
    return sum(xs) / len(xs)


def cap_weighted(items: Iterable[Tuple[float, float]]) -> Dict[str, float]:
    """{"value", "n", "total_cap"}: sum(cap_i x g_i) / sum(cap_i) over (market cap, growth) pairs.  A pair whose cap or growth is not a finite number, or whose cap is not positive, is not in the
    universe (the caller counts what it drops); an empty universe is a DataNotPresent."""
    num = den = 0.0
    n = 0
    for cap, g in items:
        if cap is None or g is None or not (math.isfinite(cap) and math.isfinite(g)) or cap <= 0.0:
            continue
        num += cap * g
        den += cap
        n += 1
    if n == 0 or den <= 0.0:
        raise DataNotPresent("the gate universe holds no company with a market capitalisation and a P50 growth path: no engine growth, so no engine-consistent premium")
    return {"value": num / den, "n": n, "total_cap": den}


# ---- the premium ----------------------------------------------------------------------------------------------------------------------------

@dataclass
class ConsistentErp:
    """The engine-consistent premium of one date and everything that made it (reported per date: his ERP, delta, the result, the engine growth used)."""
    asof: str
    row_date: str
    damodaran_erp: float                 # his published "ERP (T12 m with sustainable payout)" of the row
    delta: float                         # r(g_engine) - r(g_damodaran), the reproduced model
    erp: float                           # damodaran_erp + delta
    engine_growth: float                 # the cap-weighted mean of the P50 growth path of years 1-5
    damodaran_growth: float              # his "Expected growth rate" of the row
    required_return_damodaran_growth: float
    required_return_engine_growth: float
    index_level: float
    cf_t12: float
    rf_row: float
    file: str
    file_sha256: str
    universe: Dict[str, object] = field(default_factory=dict)

    def label(self) -> str:
        return (f"{CONSISTENT_LABEL}: Damodaran monthly {self.row_date} sustainable-payout ERP {self.damodaran_erp:.4%} {self.delta * 1e4:+.0f} bp "
                f"(delta: 5-year growth {self.damodaran_growth:.2%} -> engine {self.engine_growth:.2%})")

    def meta(self) -> dict:
        return {"source": "engine_consistent", "row_date": self.row_date, "file": self.file, "file_sha256": self.file_sha256, "damodaran_erp": self.damodaran_erp, "delta": self.delta,
                "engine_growth": self.engine_growth, "damodaran_growth": self.damodaran_growth, "column": "ERP (T12 m with sustainable payout) + delta"}

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["universe"] = dict(self.universe)
        return d


def consistent_erp(asof, row: dict, engine_growth: float, universe: Optional[dict] = None) -> ConsistentErp:
    """The premium from Damodaran's monthly model row (`DamodaranStore.monthly_model_row`) and the engine's growth.  Refuses a result outside (0, 0.5): it is never clipped."""
    S, cf0, g_d, rf = row["index"], row["cf_t12"], row["growth"], row["tbond"]
    if engine_growth is None or not math.isfinite(engine_growth):
        raise DataNotPresent("no engine growth for the date")
    r_d = required_return(S, cf0, g_d, rf)
    r_e = required_return(S, cf0, engine_growth, rf)
    delta = r_e - r_d
    erp = row["erp"] + delta
    if not (PLAUSIBLE_ERP[0] < erp < PLAUSIBLE_ERP[1]):
        raise DataNotPresent(f"the engine-consistent premium {erp:.4%} (Damodaran {row['erp']:.4%} {delta * 1e4:+.0f} bp) is not a plausible fraction - refusing to use it")
    return ConsistentErp(asof=str(asof)[:10], row_date=row["date"].isoformat(), damodaran_erp=row["erp"], delta=delta, erp=erp, engine_growth=engine_growth, damodaran_growth=g_d,
                         required_return_damodaran_growth=r_d, required_return_engine_growth=r_e, index_level=S, cf_t12=cf0, rf_row=rf, file=row["file"], file_sha256=row["file_sha256"],
                         universe=dict(universe or {}))
