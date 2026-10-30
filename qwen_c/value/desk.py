"""desk.py - the 3Q valuation desk: design D2 (SPEC_m3q_valuation.md §2; PLAN_terminal_reinvestment.md O1-O8, O2c, O7).

A fresh port of the D2 arithmetic audited on 2026-10-18 (rs2 `1dcb3b2`, tools/consensus_reference.py: equity_ronic, d2_flow,
d2_amortization, d2_da_org_path, d2_value, d2_value_financial; ronic_at from revision 24). Deterministic: the model chooses inputs, this
module only computes. Nothing here is a default of a judgment input; a missing or invalid input is a named refusal (DeskRefusal).

The equity frame, per year t:
  years 1..5+H  Flow_t = X_t - (1 - delta)(capex_t - D&A_org,t + dNWC_t) - (P_t - ROU_t) + tau A_t                       (O7)
  fade          Flow_t = X_t (1 - g_{t+1} / RONIC_t) - w_t R_t + tau A_t; g is REVENUE growth (B1 = R, RR_Q3)
                w_t = w_5 (1 - (t - 5) / F) only when H = 0 (O2c drops the gap when a cited investment path extends the levels leg)
  terminal      TV = X_{N+1} (1 - g_T / RONIC_T) / (r - g_T), N = 5 + max(F, H); plus the PV of the amortization shield left after N
  financial     Flow_t = E_t (1 - g_{t+1} / ROE_t) from year 1 (O3)
RONIC_t moves on 1/RONIC from RONIC_0 to RONIC_T; returns on capital become equity returns by O5. There is no sustaining charge s (O8).
"""
import math

DESK_VERSION = "m3q.desk.v4"   # v4 2026-10-31 CROSS_CHECK_Q3b N1: driver book takes BV_t = R_t (no division by ROE)   # v3 2026-10-30 CROSS_CHECK_Q3 3: driver "book" carries the year-5 book growth g5 and fades growth over years 6..5+F   # v2 2026-10-30: financial route on the clean-surplus identity (CROSS_CHECK_Q 25), driver required
FADE_CONVENTION = "revenue"          # B1, ruled by the truth test RR_Q3 (2026-10-30)


class DeskRefusal(ValueError):
    """A named refusal: `code` is the machine reason, the message says why."""

    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code = code


def _fin(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def ronic_at(ronic0, ronic_t, frac):
    """RONIC at fraction `frac` of the fade: 1/RONIC moves linearly from 1/RONIC_0 to 1/RONIC_T (an unlimited return is a charge of 0)."""
    if frac >= 1:
        return ronic_t
    if frac <= 0 or ronic0 == ronic_t:
        return ronic0
    u0 = 0.0 if math.isinf(ronic0) else 1.0 / ronic0
    ut = 0.0 if math.isinf(ronic_t) else 1.0 / ronic_t
    u = u0 + (ut - u0) * frac
    return math.inf if u <= 0 else 1.0 / u


def equity_ronic(roc, delta, kd, tau):
    """O5: ROE = ROC + delta / (1 - delta) (ROC - kd (1 - tau))."""
    if not delta:
        return roc
    return roc + delta / (1.0 - delta) * (roc - kd * (1.0 - tau))


def d2_flow(x, capex, da_org, dnwc, p, rou, a, delta, tau):
    """The levels leg of one year (O7). The lease term takes no delta; tau A is the amortization's tax shield."""
    return x - (1.0 - delta) * (capex - da_org + dnwc) - (p - rou) + tau * a


def amortization_path(schedule, thereafter, n_years):
    """A_1..A_n: the filed five-year schedule, then the 'thereafter' balance run off at the year-5 rate until exhausted.
    Returns (path, left), left = the balance still unamortized after year n."""
    out = [float(a) for a in schedule]
    after = float(thereafter)
    rate = next((a for a in reversed(out) if a > 0), 0.0)        # A_5 = 0 with a balance left: the last positive amount (ruling 30)
    while len(out) < n_years:
        a = min(rate, max(0.0, after)) if rate > 0 else 0.0
        out.append(a)
        after -= a
    return out[:n_years], max(0.0, after) + sum(out[n_years:])


def shield_after(left, rate, tau, r, n):
    """PV at year 0 of tau A on the balance `left` after year n, run off at `rate` a year (the finite shield the terminal does not carry)."""
    pv, t = 0.0, n
    while left > 1e-15 and rate > 0:
        t += 1
        a = min(rate, left)
        pv += tau * a / (1 + r) ** t
        left -= a
    return pv


def da_org_path(n_years, revenue, capex, d_ratio, ppe=None):
    """D&A_org for years 1..n_years: the vintages rule from filed PP&E (gross_prior, gross, net, da_org_0) when usable, else the pooled
    D&A / revenue ratio. Returns (path, rule)."""
    pooled = [d_ratio * revenue[t] for t in range(1, n_years + 1)]
    if not ppe:
        return pooled, "pooled"
    da0, gross0, net0, gross_prior = ppe["da_org_0"], ppe["gross"], ppe["net"], ppe["gross_prior"]
    if not (da0 > 0 and gross0 > 0 and gross_prior > 0):
        return pooled, "pooled"
    life = max(3, min(60, round(gross_prior / da0)))

    def net_over_gross(g):
        w = [(1 + g) ** (-a) for a in range(life)]
        return sum(wi * (1 - a / life) for a, wi in enumerate(w)) / sum(w)

    lo, hi, target = -0.3, 0.6, net0 / gross0
    for _ in range(80):
        mid = (lo + hi) / 2
        if net_over_gross(mid) < target:
            lo = mid
        else:
            hi = mid
    g = (lo + hi) / 2
    w = [(1 + g) ** (-a) for a in range(life)]
    k = gross0 / sum(w)
    vint = [k * wi for wi in w]
    out = []
    for t in range(1, n_years + 1):
        existing = sum(c / life for a, c in enumerate(vint) if a + t <= life)
        new = sum(capex[j - 1] / life for j in range(1, t) if 0 < t - j <= life)
        out.append(existing + new)
    return out, "vintages"


def _check(inp, keys):
    for k in keys:
        if k not in inp:
            raise DeskRefusal("input_missing", f"{k} is required")


def value_operating(inp):
    """Operating route. inp keys:
      revenue R_0..R_{5+H}; margin m_1..m_{5+H} (X / revenue); capex_1..capex_{5+H}; d_ratio (pooled D&A_org / revenue); ppe (optional,
      vintages rule); w (NWC / revenue); p_ratio, rou_ratio (lease principal, ROU depreciation / revenue; 0.0 for none); amort_schedule
      (A_1..A_5), amort_thereafter; delta, kd, tau; r, g_T, F, H (0 unless a cited investment-state path extends the levels leg);
      ronic0, ronic_T (returns on capital; math.inf allowed); m_long; shares; excess_cash; stub_days (fiscal-year end to T: the equity
      value is rolled forward at r; cash is at its measured amount).
    Returns the per-share value and the whole schedule."""
    _check(inp, ("revenue", "margin", "capex", "d_ratio", "w", "p_ratio", "rou_ratio", "amort_schedule", "amort_thereafter", "delta", "kd",
                 "tau", "r", "g_T", "F", "H", "ronic0", "ronic_T", "m_long", "shares", "excess_cash", "stub_days"))
    h, f_years = int(inp["H"]), int(inp["F"])
    e_end = 5 + h
    rev = [float(x) for x in inp["revenue"]]
    mg = [float(x) for x in inp["margin"]]
    cx = [float(x) for x in inp["capex"]]
    if len(rev) != e_end + 1 or len(mg) != e_end or len(cx) != e_end:
        raise DeskRefusal("input_shape", f"revenue needs {e_end + 1} values, margin and capex {e_end} (H = {h})")
    if f_years < 1:
        raise DeskRefusal("input_invalid", "F must be at least 1")
    r, gt, delta, kd, tau = (float(inp[k]) for k in ("r", "g_T", "delta", "kd", "tau"))
    if not (0.0 <= delta < 1.0 and 0.0 <= tau < 1.0):
        raise DeskRefusal("input_invalid", "delta and tau must be in [0, 1)")
    if not r > gt:
        raise DeskRefusal("rate_not_above_terminal_growth", f"r = {r} must exceed g_T = {gt}")
    if not (inp["ronic0"] > 0 and inp["ronic_T"] > 0):
        raise DeskRefusal("ronic_not_positive", "RONIC_0 and RONIC_T must be positive")
    for name in ("ronic0", "ronic_T"):                               # ruling 3 (1dcb3b2 refused it): the O5 equity return must be positive
        eq = equity_ronic(float(inp[name]), delta, kd, tau)
        if not eq > 0:
            raise DeskRefusal("equity_ronic_not_positive", f"{name} {inp[name]} at delta {delta}, kd {kd} gives an equity return {eq:.6g}")
    eq_t = equity_ronic(float(inp["ronic_T"]), delta, kd, tau)
    if not eq_t > gt:                                                 # the re-run: growth paid at a return at or below itself never pays out
        raise DeskRefusal("ronic_not_above_growth", f"the long-run equity return {eq_t:.6g} does not exceed g_T {gt}")
    stub = inp["stub_days"]
    if not (isinstance(stub, (int, float)) and 0 <= stub <= 800):
        raise DeskRefusal("input_invalid", "stub_days (fiscal-year end to T) must be in [0, 800]")
    if not inp["shares"] > 0:
        raise DeskRefusal("shares_unavailable", "a positive share count is required")
    x = [rev[t] * mg[t - 1] for t in range(1, e_end + 1)]
    n = max(5 + f_years, e_end)
    amort, left = amortization_path(inp["amort_schedule"], inp["amort_thereafter"], n)
    da, da_rule = da_org_path(e_end, rev, cx, float(inp["d_ratio"]), inp.get("ppe"))
    w = float(inp["w"])
    levels = []
    for t in range(1, e_end + 1):
        levels.append(d2_flow(x[t - 1], cx[t - 1], da[t - 1], w * (rev[t] - rev[t - 1]), float(inp["p_ratio"]) * rev[t],
                              float(inp["rou_ratio"]) * rev[t], amort[t - 1], delta, tau))
    tail = _tail(levels, x, rev, mg, amort, delta, kd, tau, r, gt, f_years, h, float(inp["ronic0"]), float(inp["ronic_T"]),
                 float(inp["m_long"]))
    pv_levels = sum(f / (1 + r) ** t for t, f in enumerate(levels[:5], 1))
    shield = shield_after(left, amort[-1] if amort else 0.0, tau, r, n)
    equity = pv_levels + tail["pv_flows"] + tail["tv_pv"] + shield
    factor = (1 + r) ** (float(inp["stub_days"]) / 365.0)          # ruling 7: valued at the fiscal-year end, rolled forward to T at r
    return dict(tail, route="operating", desk=DESK_VERSION, fade_convention=FADE_CONVENTION, da_rule=da_rule, pv_levels=pv_levels,
                shield_after_n_pv=shield, equity_value=equity, rollforward_factor=factor, stub_days=inp["stub_days"], da_path=da,
                amort_path=amort, value_per_share=(equity * factor + float(inp["excess_cash"])) / float(inp["shares"]))


def _tail(levels, x, rev, margin, amort, delta, kd, tau, r, gt, f_years, h, ronic0, ronic_t, m_long):
    """Years 6..N and the terminal (1dcb3b2 d2_value). pv_flows covers the flows of years 6..N only."""
    e_end = 5 + h
    n = max(5 + f_years, e_end)
    fr = n - e_end
    g_e = rev[e_end] / rev[e_end - 1] - 1.0
    g5 = rev[5] / rev[4] - 1.0
    g6_def = g5 + (gt - g5) / f_years

    def g_at(t):
        return gt if (fr == 0 or t > n) else g_e + (gt - g_e) * (t - e_end) / fr

    def ron_eq(frac):
        return equity_ronic(ronic_at(ronic0, ronic_t, frac), delta, kd, tau)

    flows, xs = list(levels), list(x)
    i5 = x[4] - (levels[4] - tau * amort[4])
    i5_star = g6_def / ron_eq(0.0) * x[4]
    w5 = (i5 - i5_star) / rev[5]
    wedge_on = h == 0
    frac0 = (e_end - 5) / f_years
    rt, m_e = rev[e_end], margin[e_end - 1]
    for t in range(e_end + 1, n + 1):
        frac = (t - e_end) / fr
        rt *= 1.0 + g_at(t)
        xt = rt * (m_e + (m_long - m_e) * frac)
        ron = ron_eq(min(1.0, frac0 + (1.0 - frac0) * frac))
        f = xt * (1.0 - g_at(t + 1) / ron) + tau * amort[t - 1]
        if wedge_on:
            f -= w5 * max(0.0, 1.0 - (t - 5) / f_years) * rt
        flows.append(f)
        xs.append(xt)
    x_n1 = rt * (1.0 + gt) * m_long
    ron_t_eq = equity_ronic(ronic_t, delta, kd, tau)
    tv = x_n1 * (1.0 - gt / ron_t_eq) / (r - gt)
    tv_pv = tv / (1 + r) ** n
    pv_flows = sum(f / (1 + r) ** (t + 1) for t, f in enumerate(flows) if t + 1 >= 6)
    seam = flows[5] / flows[4] if len(flows) > 5 and flows[4] else None
    return {"n_years": n, "flows_all": flows, "x_all": xs, "pv_flows": pv_flows, "tv": tv, "tv_pv": tv_pv, "i5": i5, "i5_star": i5_star,
            "wedge_rate_5": w5, "wedge_applied": wedge_on, "levels_years": e_end, "seam_ratio": seam}


def value_financial(inp):
    """Financial route (O3). inp keys: revenue R_0..R_5; margin m_1..m_5 (E / revenue); r, g_T, F; ronic0 (ROE_0), ronic_T (ROE_T); m_long;
    shares; excess_cash (0.0 for a financial: its cash is operating); driver ("book": R is opening book equity and m the ROE; "revenue":
    R is a revenue line and ROE follows ronic0 -> ronic_T)."""
    _check(inp, ("revenue", "margin", "r", "g_T", "F", "ronic0", "ronic_T", "m_long", "shares", "excess_cash"))
    rev, mg = [float(v) for v in inp["revenue"]], [float(v) for v in inp["margin"]]
    if len(rev) != 6 or len(mg) != 5:
        raise DeskRefusal("input_shape", "revenue needs 6 values and margin 5")
    r, gt, f_years = float(inp["r"]), float(inp["g_T"]), int(inp["F"])
    ronic0, ronic_t, m_long = float(inp["ronic0"]), float(inp["ronic_T"]), float(inp["m_long"])
    if not r > gt:
        raise DeskRefusal("rate_not_above_terminal_growth", f"r = {r} must exceed g_T = {gt}")
    if not (ronic0 > 0 and ronic_t > 0) or f_years < 1:
        raise DeskRefusal("input_invalid", "ROE_0 and ROE_T must be positive and F at least 1")
    if not inp["shares"] > 0:
        raise DeskRefusal("shares_unavailable", "a positive share count is required")
    n = 5 + f_years
    driver = inp.get("driver")
    if driver not in ("book", "revenue"):                            # required: never defaulted
        raise DeskRefusal("input_invalid", f"driver {driver!r}")
    # driver "book" (CROSS_CHECK_Q3 3): g5 is the analyst's year-5 book growth (R_6 = R_5 (1 + g5)); growth in year t >= 6 fades from g5 to
    # g_T by year n, aligned with the ROE fade. driver "revenue": as before, g5 = R_5 / R_4 - 1 and R_t = R_{t-1} (1 + g_at(t)).
    if driver == "book" and "g5" not in inp:
        raise DeskRefusal("input_missing", "driver book needs g5, the year-5 book growth")
    g5 = float(inp["g5"]) if driver == "book" else rev[5] / rev[4] - 1.0

    def g_at(t):
        return gt if t > n else g5 + (gt - g5) * (t - 5) / f_years

    # CROSS_CHECK_Q 25: the clean-surplus identity Flow_t = E_t - (BV_{t+1} - BV_t), BV_t = E_t / ROE_t the book equity at the start of
    # year t. driver "book" (inputs.base_financial): R_t IS the book equity and m_t the ROE, so ROE_t = m_t. driver "revenue" (premiums, the
    # reference's insurer): ROE_t is ROE_0 through year 5, then moves to ROE_T on 1/ROE over the fade. A constant ROE gives the reference's
    # E_t (1 - g_{t+1} / ROE) in both.
    R = {t: rev[t] for t in range(1, 6)}
    m = {t: mg[t - 1] for t in range(1, 6)}
    for t in range(6, n + 3):
        R[t] = R[t - 1] * (1.0 + (g5 if t == 6 else g_at(t - 1))) if driver == "book" else R[t - 1] * (1.0 + g_at(t))
        m[t] = mg[4] + (m_long - mg[4]) * min(1.0, (t - 5) / f_years)
    roe = (lambda t: m[t]) if driver == "book" else (lambda t: ronic0 if t <= 5 else ronic_at(ronic0, ronic_t, (t - 5) / f_years))
    E = {t: R[t] * m[t] for t in R}
    bv = dict(R) if driver == "book" else {t: E[t] / roe(t) for t in R}
    flows = [E[t] - (bv[t + 1] - bv[t]) for t in range(1, n + 1)]
    xs = [E[t] for t in range(1, n + 1)]
    tv = (E[n + 1] - gt * R[n + 1] if driver == "book" else E[n + 1] * (1.0 - gt / roe(n + 1))) / (r - gt)
    tv_pv = tv / (1 + r) ** n
    pv_all = sum(f / (1 + r) ** t for t, f in enumerate(flows, 1))
    equity = pv_all + tv_pv
    return {"route": "financial", "desk": DESK_VERSION, "n_years": n, "flows_all": flows, "x_all": xs, "tv": tv, "tv_pv": tv_pv,
            "equity_value": equity, "value_per_share": (equity + float(inp["excess_cash"])) / float(inp["shares"]),
            "seam_ratio": flows[5] / flows[4] if flows[4] else None}
