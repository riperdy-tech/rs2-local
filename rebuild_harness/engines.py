"""The engine interface and the yardsticks.

    engine(ticker, asof, data_root) -> {"value_per_share": float|None, "family": str|None, "score": float|None, "components": {...},
                                         "stamps": [...], "reason": str|None, "forecasts": {k: {measure: value}}|None}

`ticker` is a ticker or a 'CIK<digits>' / CIK string; `data_root` is a `valuation.pit_data.PitData` (the shared point-in-time layer: everything an
engine may read, strictly before `asof`); `asof` a date or ISO string.  `score` is what the harness ranks (higher = more attractive): a value
engine's score is value_per_share / price when the engine does not set it; a yardstick sets its own.  An engine that cannot value a name returns
value_per_share/score None and says why in `reason`: nothing is dropped silently.

`@engine(name, kind, files=[...])` registers an engine and records which files make up its identity (the holdout lock hashes them).
"""
import inspect
import math
from pathlib import Path

from valuation.pit_data import is_num, to_date, add_months
from . import fundamentals

REGISTRY = {}


def engine(name, kind="yardstick", files=None):
    """Register `fn` as engine `name`.  kind: "yardstick" (a score on filed numbers) or "value" (a per-share value)."""
    def deco(fn):
        fn.engine_name, fn.engine_kind = name, kind
        fn.frozen_files = [Path(p) for p in (files if files is not None else [inspect.getsourcefile(fn)])]
        REGISTRY[name] = fn
        return fn
    return deco


def result(score=None, value_per_share=None, family=None, components=None, stamps=None, reason=None, forecasts=None):
    return {"value_per_share": value_per_share, "family": family, "score": score, "components": components or {}, "stamps": list(stamps or []),
            "reason": reason, "forecasts": forecasts}


class Context:
    """The common point-in-time reads of one (company, date): the snapshot, the base-year row and its predecessor, the market capitalisation."""

    def __init__(self, ticker, asof, pit):
        self.asof = to_date(asof)
        self.cik = pit.cik_for(ticker)
        self.ticker = ticker if self.cik is None or str(ticker).upper().startswith("CIK") or str(ticker).isdigit() else str(ticker).upper()
        self.pit = pit
        t = str(ticker).upper()
        self.key = t if t in pit.id_map else (pit.ticker_for(self.cik) if self.cik else None)
        self.snap = pit.snapshot(self.cik, self.asof) if self.cik else None
        self.rows = self.snap.rows() if self.snap else {}
        self.rowL = self.snap.row_L() if self.snap and self.snap.L_fye else None
        self.L = self.snap.L if self.snap else None
        prev_year = max([y for y in self.rows if self.L is not None and y < self.L], default=None)
        self.prevL = self.rows.get(prev_year) if prev_year is not None else None
        self._mc = None

    def market_cap(self):
        if self._mc is None:
            self._mc = self.pit.market_cap(self.cik, self.asof, self.key)
        return self._mc

    def base_age_months(self):
        if not self.snap or not self.snap.L_fye:
            return None
        return (self.asof - to_date(self.snap.L_fye)).days / 30.4375

    def stamps(self):
        s = []
        mc = self.market_cap()
        s += list(mc.get("flags") or [])
        age = self.base_age_months()
        if age is not None and age > 15:
            s.append("stale_base_year_over_15_months")
        return s


def _no_base(ctx):
    if ctx.cik is None:
        return result(reason="no_cik_for_ticker")
    if ctx.rowL is None:
        return result(reason="no_annual_report_before_date")
    return None


def _yield(numerator_name, numerator):
    def run(ctx):
        bad = _no_base(ctx)
        if bad:
            return bad
        mc = ctx.market_cap()
        if mc["market_cap"] is None:
            return result(reason=mc["reason"], stamps=ctx.stamps())
        if numerator is None or not is_num(numerator):
            return result(reason=f"{numerator_name}_missing", stamps=ctx.stamps())
        return result(score=numerator / mc["market_cap"], stamps=ctx.stamps(),
                      components={numerator_name: numerator, "market_cap": mc["market_cap"], "base_fye": ctx.snap.L_fye})
    return run


@engine("yardstick_earnings_yield")
def earnings_yield(ticker, asof, data_root):
    """Net income of the last annual report filed before the date over the market capitalisation on that date (parent-attributable net income
    where the ladder reaches it; a consolidated ProfitLoss carries its flag)."""
    ctx = Context(ticker, asof, data_root)
    ni = ctx.rowL.get("net_income") if ctx.rowL else None
    return _yield("net_income", ni)(ctx)


@engine("yardstick_fcf_yield")
def fcf_yield(ticker, asof, data_root):
    """(Operating cash flow - capex) of the last annual report over the market capitalisation."""
    ctx = Context(ticker, asof, data_root)
    fcf = ctx.rowL.get("fcf") if ctx.rowL else None
    return _yield("fcf", fcf)(ctx)


@engine("yardstick_gross_profitability")
def gross_profitability(ticker, asof, data_root):
    """Gross profit / total assets of the last annual report (Novy-Marx)."""
    ctx = Context(ticker, asof, data_root)
    bad = _no_base(ctx)
    if bad:
        return bad
    gp = fundamentals.gross_profitability(ctx.rowL)
    if gp is None:
        return result(reason="gross_profit_or_assets_missing", stamps=ctx.stamps())
    return result(score=gp, stamps=ctx.stamps(), components={"base_fye": ctx.snap.L_fye})


@engine("yardstick_return_on_capital")
def return_on_capital(ticker, asof, data_root):
    """NOPAT / invested capital of the last annual report (tax default stamped); see fundamentals.invested_capital."""
    ctx = Context(ticker, asof, data_root)
    bad = _no_base(ctx)
    if bad:
        return bad
    r = fundamentals.return_on_capital(ctx.rowL)
    if r is None:
        return result(reason="return_on_capital_not_computable", stamps=ctx.stamps())
    st = ctx.stamps() + (["tax_default"] if fundamentals.tax_rate(ctx.rowL)[1] else [])
    return result(score=r, stamps=st, components={"base_fye": ctx.snap.L_fye})


def momentum_12_1(pit, key, asof):
    """Total return from 12 months before `asof` to 1 month before it (the latest month skipped), on the adjusted series; None without both bars."""
    src = pit.price_source
    if key is None or not src.has_key(key):
        return None
    d0, d1 = src.target_date(asof, -12), src.target_date(asof, -1)
    a0, a1 = src.adj_close(key, d0), src.adj_close(key, d1)
    if a0 is None or a1 is None:
        return None
    return a1.price / a0.price - 1.0


@engine("yardstick_momentum_12_1")
def momentum(ticker, asof, data_root):
    """12-1 month momentum: the price history before the date only (the adjusted close of month t-1 over that of month t-12)."""
    ctx = Context(ticker, asof, data_root)
    m = momentum_12_1(data_root, ctx.key or ctx.ticker, ctx.asof)
    if m is None:
        return result(reason="no_price_history_for_12_1", stamps=["momentum_no_fundamentals_needed"])
    return result(score=m, components={"window": "t-12 to t-1 months"})


YARDSTICKS = ("yardstick_earnings_yield", "yardstick_fcf_yield", "yardstick_gross_profitability", "yardstick_return_on_capital",
              "yardstick_momentum_12_1")
