"""The old engine as a harness engine: revision 21's consensus reference (tools/consensus_reference.py, tools/throughcycle_record.py at this
commit) computed point in time wherever its inputs can be.

What cannot be point in time, and how it is stamped (nothing is filled from today):
  * Vendor consensus estimates do not exist for a past date.  The reference's estimates are SYNTHETIC, the earlier harness's registered
    construction (backtest_phase2.arms.synthetic_estimates): EPS and revenue growth m for the next two years, m = the base-rate median growth
    (the growth-persistence conditional median for the growth just delivered, else the size-bucket 5-year median), measured on a corpus of
    fiscal years filed before the date.  Stamp `consensus_synthetic_base_rate_median`.
  * The corpus is whatever companies the caller puts in the `BaseRateCorpus` (the whole archive for a result; a sample for a smoke run -
    stamped with its size).
  * Discount-rate anchors (risk-free, growth anchor, breakeven, sector loading, premium, bill rate) must come from a dated provider
    `anchors_at(asof)`; with none, the engine returns no value (`no_pit_anchor`).  The harness never supplies one.
  * Input scope (revision 20's noncontrolling-interest attribution pi, the per-share check, customer money) is not applied: pi = 1,
    stamp `input_scope_not_applied`.  Net income is the ladder's (parent-attributable where filed; flagged otherwise).
  * The cost of equity is not quantised to the pack's two decimals (`coe_unquantised`).
  * The sector comes from `sector_of(cik)` (a label the caller supplies; a screener label is today's: the caller stamps where it is from).
  * The terminal-value share is not reported by this engine (the reference does not return the pieces).

`consensus_reference.build` is called exactly as the pack calls it: same arguments, same module.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
TOOLS = REPO / "tools"
for _p in (str(TOOLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import consensus_reference as cref      # noqa: E402  (revision 21's, from this tree)
import throughcycle_record as tcr       # noqa: E402
import base_rates as br                 # noqa: E402
import growth_persistence as gp         # noqa: E402

from backtest_phase2.arms import _precheck, synthetic_estimates   # noqa: E402  (the earlier harness's registered construction)
from valuation.pit_data import is_num, to_date   # noqa: E402
from .engines import Context, result, REGISTRY   # noqa: E402

R17_FIELDS = ("goodwill", "intangibles_ex_goodwill", "amortization_intangibles")
OLD_ENGINE_FILES = [HERE, TOOLS / "consensus_reference.py", TOOLS / "throughcycle_record.py", TOOLS / "base_rates.py",
                    TOOLS / "growth_persistence.py", REPO / "backtest_phase2" / "arms.py"]


class BaseRateCorpus:
    """The growth base rates as of a date, from a Panel of first-filed revenue (fiscal years and cells filed before the date only).  The
    repository's own base_rates / growth_persistence read a fundamentals_history-shaped file: one is written per date into a temporary folder."""

    def __init__(self, panel):
        self.panel = panel
        self._dirs = {}
        self._tables = {}
        self._sizes = {}
        self._tmp = tempfile.TemporaryDirectory(prefix="pit_corpus_")

    def _for(self, asof):
        a = to_date(asof).isoformat()
        if a not in self._dirs:
            view = self.panel.asof(a)
            d = Path(self._tmp.name) / a
            d.mkdir(parents=True, exist_ok=True)
            doc = {"tickers": {cik: {str(y): {"revenue": r.get("revenue")} for y, r in yrs.items()} for cik, yrs in view.items()}}
            (d / "fundamentals_history.json").write_text(json.dumps(doc), encoding="utf-8")
            self._dirs[a] = d
            self._sizes[a] = len(view)
            self._tables[a] = gp.persistence_table(sd=d)
        return self._dirs[a], self._tables[a]

    def size(self, asof):
        self._for(asof)
        return self._sizes[to_date(asof).isoformat()]

    def synthetic_m(self, rows, L, asof):
        """The base-rate median growth (fraction) and its source: the earlier harness's `synthetic_m` on this corpus."""
        d, table = self._for(asof)
        rl = (rows.get(L) or {}).get("revenue")
        rprev = (rows.get(L - 1) or {}).get("revenue")
        g0 = rl / rprev - 1 if is_num(rl) and is_num(rprev) and rprev > 0 else None
        med, src = None, "conditional"
        if g0 is not None:
            lbl = gp.bucket_for_growth(g0)
            stats = table.get(lbl) if lbl else None
            med = (stats or {}).get("median")
        if med is None:
            _sz, tb = br.base_rate_table(rl, sd=d)
            med = ((tb or {}).get(5) or {}).get("p50")
            src = "size_bucket"
        if not isinstance(med, (int, float)):
            return None, "none"
        return med / 100.0, src


def untagged_marker(rows):
    """The R17 fields the company never tags in any held year (the extractor's provenance marker, rebuilt from the held rows)."""
    return [f for f in R17_FIELDS if not any(is_num((r or {}).get(f)) for r in rows.values())]


def make_old_engine(anchors_at, corpus, sector_of=None, family_of=None, name="old_engine_rev21"):
    """Build and register the old engine.
    anchors_at(asof) -> {"rf", "ga", "breakeven", "loading": {sector: adjusted loading}, "erp", "bill_rate_at": f(fye iso) -> 12-month mean bill rate}
    or None.  corpus: a BaseRateCorpus.  sector_of(cik) -> a screener-style sector string or None.  family_of(cik, asof) -> family string."""

    def old_engine(ticker, asof, data_root):
        ctx = Context(ticker, asof, data_root)
        stamps = ["consensus_synthetic_base_rate_median", "input_scope_not_applied", "coe_unquantised"] + ctx.stamps()
        family = family_of(ctx.cik, ctx.asof) if (family_of and ctx.cik) else None
        if ctx.cik is None:
            return result(reason="no_cik_for_ticker", family=family)
        if ctx.rowL is None:
            return result(reason="no_annual_report_before_date", family=family)
        anchors = anchors_at(ctx.asof) if anchors_at else None
        if not anchors:
            return result(reason="no_pit_anchor", family=family, stamps=stamps)
        sector = sector_of(ctx.cik) if sector_of else None
        rows = ctx.rows
        L = ctx.L
        m, m_src = corpus.synthetic_m(rows, L, ctx.asof)
        shares, sflags = data_root.diluted_shares(ctx.cik, ctx.asof, ctx.key)
        stamps += sflags + [f"base_rate_source:{m_src}", f"base_rate_corpus_companies:{corpus.size(ctx.asof)}"]
        nm = {"rows": rows, "L": L, "m": m, "shares": shares}
        why, rowL, oe, rev = _precheck(nm)
        if why:
            return result(reason=why, family=family, stamps=stamps)
        loading = (anchors.get("loading") or {}).get(sector)
        rf, ga, be, erp = anchors.get("rf"), anchors.get("ga"), anchors.get("breakeven"), anchors.get("erp")
        if not all(is_num(v) for v in (rf, ga, loading, erp)):
            return result(reason="anchor_incomplete", family=family, stamps=stamps)
        coe = max(rf, ga) + loading * erp
        untagged = untagged_marker(rows)
        dc_tags = {y.year: y.cells["debt_current"].tag for y in ctx.snap.years.values() if "debt_current" in y.cells}
        rec = tcr.analyse(rows, coe, untagged_fields=untagged, base_year=L, debt_current_tags=dc_tags)
        tg, basis, _treason = cref.terminal_growth_default(ga, be, rec["g_rev"], None, m)
        est = synthetic_estimates(rev, float(rowL["net_income"]), shares, m)
        bill = anchors["bill_rate_at"](ctx.snap.L_fye) if callable(anchors.get("bill_rate_at")) else None
        cash = cref.cash_term(rowL, bill, sector)
        out = cref.build(oe, est, coe, tg, shares, m, da=rowL.get("da"), capex=rowL.get("capex"), stub_months=ctx.snap.stub_months(),
                         anchor=ga, record=rec, base_ni=tcr.adjusted_earnings(rowL, untagged), base_revenue=rev, cash=cash)
        stamps += list(out.get("stamps") or [])
        comps = {"method": out.get("method"), "coe": coe, "terminal_g": tg, "terminal_basis": basis, "m": m, "base_fye": ctx.snap.L_fye,
                 "long_run_path": out.get("long_run_path"), "margin_ratio": out.get("margin_ratio"), "ronic0": out.get("ronic0"),
                 "terminal_ronic": out.get("terminal_ronic")}
        rev_path = out.get("revenue")
        forecasts = {k: {"revenue": rev_path[k]} for k in (1, 2, 3) if rev_path and len(rev_path) > k and is_num(rev_path[k])} or None
        if out.get("value") is None:
            return result(reason=out.get("growth_unusable") or out.get("reason") or "no_value", family=family, stamps=stamps, components=comps)
        return result(value_per_share=float(out["value"]), family=family, stamps=stamps, components=comps, forecasts=forecasts)

    old_engine.engine_name, old_engine.engine_kind = name, "value"
    old_engine.frozen_files = list(OLD_ENGINE_FILES)
    REGISTRY[name] = old_engine
    return old_engine
