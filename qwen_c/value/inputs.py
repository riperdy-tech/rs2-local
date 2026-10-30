"""inputs.py - the code-owned valuation inputs of 3Q (SPEC_m3q_valuation.md §2, §4 V8): filed figures (facts.py) to the desk's base.

Code owns every measured quantity; the model owns the forecast (growth, margins, F, the long-run margin, RONIC_T, terminal g). Nothing
here is a default of either: an input that cannot be measured is a named refusal (desk.DeskRefusal) or, where the economics allow a
consistent zero, a stated zero with a stamp (an unfiled amortization schedule: no shield and no add-back, so X = net income).

The earnings basis X is D2's: net income before the after-tax amortization of acquired intangibles, X = NI + A (1 - tau).
The operating-margin bridge (rev 26, r26_forecast.bridge_to_x): X_t = (op_t R_t - K_0)(1 - tau), K_0 = OI_0 - X_0 / (1 - tau) held flat in
dollars, so the analyst states GAAP operating margins and the desk reads X margins.
"""
import statistics

from qwen_c.value.desk import DeskRefusal
from qwen_c.value.facts import DA_EXCLUDES_AMORTIZATION

INPUTS_VERSION = "m3q.inputs.v1"
POOL_YEARS = 5
MIN_POOL_YEARS = 3
TAX_BAND = (0.0, 0.35)
PERSISTENT_SPREAD = 0.05


def _by_end(f, concept):
    return {v["end"]: v["value"] for v in (f.get(concept) or {}).get("values", [])}


def tax_rate(f):
    """V8: the latest measured provision / pretax income if inside [0, 0.35]; else the median of the measured in-band years (at least 3 of
    the last 8); else, a persistent rate (>= 3 measured years, all >= 0, within 5 points): their median; else refused. Returns
    (tau, stamp)."""
    tax, pre = _by_end(f, "tax_provision"), _by_end(f, "pretax_income")
    years = sorted(set(tax) & set(pre))
    rates = [(e, tax[e] / pre[e]) for e in years if pre[e] > 0]
    if rates and TAX_BAND[0] <= rates[-1][1] <= TAX_BAND[1] and rates[-1][0] == years[-1]:
        return rates[-1][1], "tax_rate_measured"
    band = [t for _, t in rates[-8:] if TAX_BAND[0] <= t <= TAX_BAND[1]]
    if len(band) >= 3:
        return statistics.median(band), "tax_rate_multi_year_median"
    # a persistent rate outside the band is the company's economics, not a distortion: >= 3 measured positive-pretax years among the last
    # 8, all at or above 0, within PERSISTENT_SPREAD of each other (RR_Q2_Q4 decision 1)
    recent = [t for _, t in rates[-8:]]
    if len(recent) >= 3 and min(recent) >= 0 and max(recent) - min(recent) <= PERSISTENT_SPREAD and max(recent) < 1:
        return statistics.median(recent), "tax_rate_persistent_outside_band"
    raise DeskRefusal("tax_unavailable", f"no in-band measured tax rate (latest {rates[-1][1] if rates else None}); never a stamped default")


def base(f, *, market_cap):
    """The measured base for value_operating: revenue R_-4..R_0, X_0 and its margin, pooled intensities, w, tau, RONIC_0, delta, kd, shares,
    excess cash, the amortization path. `market_cap` (USD, from the formation's price row) sets delta at market weights (O5)."""
    rev = _by_end(f, "revenue")
    ends = sorted(rev)[-POOL_YEARS:]
    if len(ends) < MIN_POOL_YEARS:
        raise DeskRefusal("history_short", f"{len(ends)} fiscal years of revenue; at least {MIN_POOL_YEARS} are needed to pool")
    e0 = ends[-1]
    stale = {c: d for c, d in (f.get("_stale") or {}).items() if c in ("net_income", "capex", "da", "revenue")}
    if stale:
        raise DeskRefusal("facts_stale", f"concepts end before the latest revenue year {e0}: {stale}")
    stamps = []
    tau, s = tax_rate(f)
    stamps.append(s)
    ni, da, cx, am = (_by_end(f, k) for k in ("net_income", "da", "capex", "amortization"))
    for name, series in (("net_income", ni), ("da", da), ("capex", cx)):
        if e0 not in series:
            raise DeskRefusal("input_missing", f"{name} for the latest fiscal year {e0}")
    sched = [_by_end(f, f"amort_next_{k}").get(e0) for k in range(1, 6)]
    after = _by_end(f, "amort_after_5").get(e0)
    use_amort = all(a is not None for a in sched) and e0 in am      # the add-back and the shield come together or not at all
    if use_amort:
        a0 = am[e0]
        amort_schedule, amort_after = sched, after if after is not None else 0.0
        if after is None:
            stamps.append("amortization_after_year5_not_filed")
    else:
        a0, amort_schedule, amort_after = 0.0, [0.0] * 5, 0.0
        stamps.append("amortization_schedule_not_filed")          # consistent zero: no shield and no add-back, X = net income
    x0 = ni[e0] + a0 * (1 - tau)
    if not x0 > 0:
        raise DeskRefusal("e0_not_positive", f"X_0 = {x0:.6g}: no earnings base (O7)")
    pool = [e for e in ends if e in da and e in cx]
    if len(pool) < MIN_POOL_YEARS:
        raise DeskRefusal("history_short", f"{len(pool)} years with revenue, D&A and capex")
    r_sum = sum(rev[e] for e in pool)
    da_tag = {v["end"]: v["tag"] for v in f["da"]["values"]}
    d_ratio = sum(da[e] - (am.get(e, 0.0) if use_amort and da_tag[e] not in DA_EXCLUDES_AMORTIZATION else 0.0) for e in pool) / r_sum
    c_ratio = sum(cx[e] for e in pool) / r_sum
    stamps.append("rou_depreciation_not_separated")
    ac, lc, cash, dc, dn, eq, ie = (_by_end(f, k) for k in ("assets_current", "liabilities_current", "cash", "debt_current", "debt_noncurrent",
                                                             "equity", "interest_expense"))
    if not all(e0 in d for d in (ac, lc, cash)):
        raise DeskRefusal("input_missing", f"current assets, current liabilities and cash for {e0}")
    debt0 = dc.get(e0, 0.0) + dn.get(e0, 0.0)
    nwc0 = (ac[e0] - cash[e0]) - (lc[e0] - dc.get(e0, 0.0))
    w = nwc0 / rev[e0]
    prev = ends[-2]
    if not (prev in eq and prev in cash):
        raise DeskRefusal("input_missing", f"equity and cash for {prev} (the opening capital)")
    ic_prev = eq[prev] + dc.get(prev, 0.0) + dn.get(prev, 0.0) - cash[prev]
    if not ic_prev > 0:
        raise DeskRefusal("invested_capital_not_positive", f"opening capital {ic_prev:.6g}")
    interest = ie.get(e0, 0.0)
    ronic0 = (x0 + interest * (1 - tau)) / ic_prev
    if not ronic0 > 0:
        raise DeskRefusal("ronic_not_positive", f"RONIC_0 = {ronic0:.6g}")
    if not (market_cap and market_cap > 0):
        raise DeskRefusal("market_cap_unavailable", "delta needs the market value of equity")
    delta = debt0 / (debt0 + market_cap)
    debt_prev = dc.get(prev, 0.0) + dn.get(prev, 0.0)
    kd = interest / ((debt0 + debt_prev) / 2) if debt0 + debt_prev > 0 else 0.0
    shares = _by_end(f, "diluted_shares").get(e0)
    if not (shares and shares > 0):
        raise DeskRefusal("shares_unavailable", f"diluted shares for {e0}")
    stamps.append("shares_weighted_average_diluted")
    oi = _by_end(f, "operating_income").get(e0)
    return {"version": INPUTS_VERSION, "fy0": e0, "revenue_hist": [rev[e] for e in ends], "R0": rev[e0], "x0": x0, "m0": x0 / rev[e0],
            "oi0": oi, "op_margin0": oi / rev[e0] if oi is not None else None, "d_ratio": d_ratio, "c_ratio": c_ratio, "w": w, "tau": tau,
            "ronic0": ronic0, "delta": delta, "kd": kd, "shares": shares, "excess_cash": cash[e0], "amort_schedule": amort_schedule,
            "amort_thereafter": amort_after, "p_ratio": 0.0, "rou_ratio": 0.0, "stamps": stamps,
            "record": {"op_margin": {e: _by_end(f, "operating_income")[e] / rev[e] for e in ends if e in _by_end(f, "operating_income")}}}


def bridge_x_margin(b, op_margins, revenues):
    """Analyst operating margins (GAAP basis) to X margins: X_t = (op_t R_t - K_0)(1 - tau), K_0 = OI_0 - X_0 / (1 - tau)."""
    if b.get("oi0") is None:
        raise DeskRefusal("bridge_unavailable", "operating income for the base year is not filed")
    k0 = b["oi0"] - b["x0"] / (1 - b["tau"])
    return [(m * r - k0) * (1 - b["tau"]) / r for m, r in zip(op_margins, revenues)]


def base_financial(f):
    """The measured base for value_financial (O3). The driver is opening book equity: "revenue" R_t = book equity at the start of year t and
    the "margin" m_t = ROE on it, so E_t = R_t m_t and the route's E_t (1 - g_{t+1} / ROE_t) is earnings less the growth of book equity, the
    retained-equity identity. Needs >= MIN_POOL_YEARS fiscal-year equity balances, positive E_0 and opening equity, and diluted shares."""
    eq, ni = _by_end(f, "equity"), _by_end(f, "net_income")
    ends = sorted(eq)[-(POOL_YEARS + 1):]
    if len(ends) < MIN_POOL_YEARS:
        raise DeskRefusal("history_short", f"{len(ends)} fiscal-year equity balances; at least {MIN_POOL_YEARS}")
    stale = {c: d for c, d in (f.get("_stale") or {}).items() if c in ("net_income", "equity")}
    if stale:
        raise DeskRefusal("facts_stale", f"{stale}")
    e0 = ends[-1]
    if e0 not in ni:
        raise DeskRefusal("input_missing", f"net_income for the latest fiscal year {e0}")
    opening = eq[ends[-2]]
    if not (ni[e0] > 0 and opening > 0):
        raise DeskRefusal("e0_not_positive", f"E_0 = {ni[e0]:.6g}, opening equity {opening:.6g}")
    shares = _by_end(f, "diluted_shares").get(e0)
    if not (shares and shares > 0):
        raise DeskRefusal("shares_unavailable", f"diluted shares for {e0}")
    roe_hist = {ends[i]: ni[ends[i]] / eq[ends[i - 1]] for i in range(1, len(ends)) if ends[i] in ni and eq[ends[i - 1]] > 0}
    # R_0 = book equity at the start of the base year, R_1 = at its end (the start of year 1): E_1 = R_1 ROE_1
    return {"version": INPUTS_VERSION, "route": "financial", "fy0": e0, "R0": opening, "R1": eq[e0], "e0": ni[e0],
            "roe0": ni[e0] / opening, "book_hist": [eq[e] for e in ends], "shares": shares, "excess_cash": 0.0,
            "record": {"roe": roe_hist},
            "stamps": ["financial_driver_book_equity", "preferred_not_separated", "shares_weighted_average_diluted"]}
