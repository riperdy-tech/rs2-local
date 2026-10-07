"""Outcomes (SPEC section 6, Addendum C): total-return excess over SPY at 3, 6, 12, 24 and 36 months where the price data allows, and the fundamental
outcomes of the first subsequent annual reports, as first filed.

THE ONLY MODULE THAT READS A RETURN OR A POST-DATE FILING.  Engines never import it.  `coverage_only=True` answers "does the bar exist" and never
forms a ratio, so a smoke run can report coverage without reading a return.

Entry: a decision is taken at 16:00 ET on the valuation date and traded at the NEXT session, so the return starts at the next session's adjusted close
(`PriceSource.entry_point`; a monthly source has no sessions and says so with a flag).

Delisting is a corporate-action event, modelled on CRSP's method (Addendum C 4): when a security has no bar at the horizon,
  * an ACQUISITION pays its consideration (cash per share plus stock ratio x the acquirer's traded close at the event date): the return runs to the last
    bar and scales the last adjusted price by consideration / last traded close;
  * a BANKRUPTCY is -100%;
  * a security that moved to OTC (`otc_continuation`) continues to be priced by the provider - if it has no bar, it is unobservable;
  * with no event on record the outcome is OUTCOME_UNOBSERVABLE: never an invented -100%.
Addendum D (no paid data): an unresolved delisting - no event on record, or an event whose consideration / equity treatment code cannot read reliably - is
OUTCOME_UNOBSERVABLE, and every return is reported under three BOUNDS (`bounds`): `excluded` (the name leaves the sample), `minus100` (the position is
lost), `last_close` (the return to the last bar the provider holds, then held as cash).  An observed or resolved outcome has the same value under all
three.  A security with a bar after the horizon, or with no entry price, has no bounds.
After a delisting the proceeds are held as cash (no further return; the benchmark keeps moving, so the excess is measured to the horizon);
`flags` says so.  A horizon beyond the end of the benchmark's data is `horizon_beyond_data`, not a missing security.
"""
from valuation.pit_data import to_date, is_num, split_product
from . import fundamentals

HORIZONS = (3, 6, 12, 24, 36)
BENCHMARK = "SPY"
OBSERVED, ACQUIRED, BANKRUPT, UNOBSERVABLE, BEYOND = ("observed", "delisted_acquisition", "delisted_bankruptcy", "OUTCOME_UNOBSERVABLE",
                                                      "horizon_beyond_data")
AVAILABLE = (OBSERVED, ACQUIRED, BANKRUPT)


def _delisting_terminal(src, key, ev, a_entry):
    """(return to the delisting, flags) for an event, or (None, flags) when the consideration cannot be valued."""
    kind = ev.get("type")
    if kind == "bankruptcy":
        return -1.0, ["delisting_bankruptcy_minus_100pct"]
    if kind == "acquisition":
        last = src.last_session(key)
        if last is None:
            return None, ["no_last_bar"]
        adj_last, px_last = src.adj_close(key, last), src.close_unadjusted(key, last)
        if adj_last is None or px_last is None:
            return None, ["no_last_bar"]
        cash = ev.get("cash_per_share")
        stock = 0.0
        if is_num(ev.get("stock_ratio")) and ev.get("acquirer_key") and src.has_key(ev["acquirer_key"]):
            a = src.close_unadjusted(ev["acquirer_key"], ev["date"])
            if a is None:
                return None, ["acquirer_price_missing"]
            stock = ev["stock_ratio"] * a.price
        elif is_num(ev.get("stock_ratio")):
            return None, ["acquirer_price_missing"]
        if not is_num(cash) and stock == 0.0:
            return None, ["consideration_unknown"]
        proceeds = (cash if is_num(cash) else 0.0) + stock
        return adj_last.price * (proceeds / px_last.price) / a_entry - 1.0, ["delisting_acquisition_consideration", "proceeds_held_as_cash"]
    return None, ["delisting_" + str(kind)]


def horizon_outcome(pit, key, asof, months, benchmark=BENCHMARK, coverage_only=False):
    """{"status", "available", "ret", "bench", "excess", "flags"} for one security and horizon (see the module docstring for the statuses)."""
    src = pit.price_source
    d1 = src.target_date(asof, months)
    out = {"status": UNOBSERVABLE, "available": False, "ret": None, "bench": None, "excess": None, "flags": [],
           "bounds": {"excluded": None, "minus100": None, "last_close": None}}
    a0 = src.entry_point(key, asof) if src.has_key(key) else None
    b0 = src.entry_point(benchmark, asof) if src.has_key(benchmark) else None
    b1 = src.adj_close(benchmark, d1) if src.has_key(benchmark) else None
    if a0 is None or b0 is None:
        out["status"] = UNOBSERVABLE
        out["flags"].append("no_entry_price" if a0 is None else "no_benchmark_entry")
        return out
    out["flags"] += [f for f in a0.flags if f.startswith(("no_next_session", "price_monthly_fallback"))]
    if b1 is None:
        out["status"] = BEYOND
        return out
    a1 = src.adj_close(key, d1) if src.has_key(key) else None
    if a1 is not None:
        out.update(status=OBSERVED, available=True)
        if not coverage_only:
            ret, bench = a1.price / a0.price - 1.0, b1.price / b0.price - 1.0
            out.update(ret=ret, bench=bench, excess=ret - bench)
            out["bounds"] = {k: ret - bench for k in out["bounds"]}
        return out
    ev = src.delisting(key)
    if ev is None:
        out["flags"].append("no_delisting_event_on_record")
        ret, flags = None, []
    else:
        ret, flags = _delisting_terminal(src, key, ev, a0.price)
        out["flags"] += flags
    if ret is None:
        _unresolved_bounds(src, key, a0, b0, b1, d1, out, coverage_only)
        return out
    out.update(status=BANKRUPT if ev.get("type") == "bankruptcy" else ACQUIRED, available=True)
    if not coverage_only:
        bench = b1.price / b0.price - 1.0
        out.update(ret=ret, bench=bench, excess=ret - bench)
        out["bounds"] = {k: ret - bench for k in out["bounds"]}
    return out


def _unresolved_bounds(src, key, a0, b0, b1, d1, out, coverage_only):
    """The three bounds of an unobservable delisting.  Only a security whose history ENDED before the horizon has them (a security that simply has no
    bar at the horizon date but trades later is a data gap, not a delisting)."""
    last = src.last_session(key) if src.has_key(key) else None
    if last is None or last >= d1:
        out["flags"].append("gap_not_delisting")
        return
    out["flags"].append("history_ended_before_horizon")
    if coverage_only:
        return
    adj_last = src.adj_close(key, last)
    bench = b1.price / b0.price - 1.0
    out["bounds"] = {"excluded": None, "minus100": -1.0 - bench,
                     "last_close": (adj_last.price / a0.price - 1.0 - bench) if adj_last is not None else None}


def horizon_outcomes(pit, key, asof, horizons=HORIZONS, benchmark=BENCHMARK, coverage_only=False):
    return {h: horizon_outcome(pit, key, asof, h, benchmark, coverage_only) for h in horizons}


def fundamental_outcomes(pit, cik, base_fye, ks=(1, 2, 3)):
    """The first-filed fundamentals of the k-th fiscal year after the base year (k = 1: the FIRST annual report filed after the valuation date).
    {k: {"fye", "filed", "measures", ...} or None}.  The year must follow the base year by one fiscal year (350-380 days) each step: a gap
    (a missed filing, a delisting, a changed year end) is None, never bridged.  Values are the first value reported for the period (the outcome
    rule), never a later restatement."""
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
            dct = nxt.cells.get("debt_current")
            out[step] = {"fye": nxt.fye, "filed": nxt.exists_from, "own_accn": nxt.own_accn, "stamps": list(nxt.stamps),
                         "measures": fundamentals.measures(row, prow, dct.tag if dct is not None else None)}
    return out
