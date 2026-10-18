"""Step 3, first part (PLAN_terminal_reinvestment.md §3a and its amendment): a reference implementation of design D2 inside the harness, to
settle the open specification points (P1 above all) before any desk code is written. Nothing in rs2-local is imported or changed.

D2, as specified (equity frame, all per year t):
  years 1-5   Flow_t = X_t - (1 - d)(capex_t - DA_org,t + dNWC_t) - (P_t - ROU_t) + tau A_t,   DA_org = D&A - ROU - A
              X_t = R_t m_t (the bridge's revenue and margin); capex_t = c_t R_t; DA_org,t = d_base R_t (+ the override's vintage
              depreciation under rule "vintage"); P_t = p_base R_t, ROU_t = rou_base R_t; dNWC_t = w (R_t - R_{t-1}); A_t the filed schedule.
  fade        Flow_t = X_t (1 - s)(1 - g_{t+1} / RONIC_eq,t) - w_t R_t,  w_t = w_5 (1 - (t-5)/F),
              w_5 = (I_5 - I*_5) / R_5, I_5 = X_5 - Flow_5, I*_5 = s X_5 + (g_6 / RONIC_eq,0)(1 - s) X_5
              growth fades linearly from g_5 = R_5/R_4 - 1 to g_T; the margin moves linearly from m_5 to the long-run margin;
              RONIC_t moves from r_tc to RONIC_T on 1/RONIC; RONIC_eq = ROC + d/(1-d)(ROC - k_d(1 - tau)).
  terminal    TV = X_{N+1} (1 - s)(1 - g_T / RONIC_eq,T) / (r - g_T), N = 5 + F.
  financial   Flow_t = E_t (1 - g_{t+1} / ROE_t) from year 1 (step 4's route; included so firm F has a reference too).
Pooled ratios: five base years -4..0, sum over sum. ROC on the pack's basis: (X + non-lease interest (1 - tau)) / (capital less lease
liabilities), the basis REPORT_step2_lease_audit.md §3 proved.

Run: python reference_d2.py  -> the acceptance table (true value, today's desk, D2 under each override and D&A rule).
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import synthetic as S                                                   # noqa: E402


def pooled(o, num, den="R", years=range(-4, 1)):
    a = sum(num(t) for t in years)
    b = sum(o[den][t] for t in years)
    return a / b


def roc(o, t, tax):
    """The pack's return basis: (X + non-lease interest after tax) over the prior year's capital less lease liabilities."""
    return (o["x"][t] + o["interest"][t] * (1 - tax)) / (o["ic"][t - 1] - o["lease_liability"][t - 1])


def ronic_at(r0, rt, frac):
    """1/RONIC interpolated, as consensus_reference.ronic_at."""
    return 1.0 / (1.0 / r0 + (1.0 / rt - 1.0 / r0) * min(1.0, frac))


def to_equity(roc_, d, kd, tax):
    return roc_ + d / (1 - d) * (roc_ - kd * (1 - tax)) if d else roc_


def amort_path(o, n_years):
    """A_t for years 1..n_years as the filings give it: the five-year schedule (years 1-5), then the 'thereafter' balance run off at the
    year-5 rate until exhausted (the shield tau A_t then holds in the levels leg, the fade and the transition alike)."""
    sched = [o["amort"][t] for t in range(1, 6)]
    after = sum(o["amort"].get(t, 0.0) for t in range(6, S.T + 2))         # the filed 'thereafter' total
    out = list(sched)
    rate = sched[-1]
    while len(out) < n_years:
        a = min(rate, max(0.0, after)) if rate > 0 else 0.0
        out.append(a)
        after -= a
    return out[:n_years]


def d2_value(name, override="true", da_rule="pooled", s=0.0, use_delta=True, wedge_years=None):
    spec = S.FIRMS[name]
    if spec["kind"] == "insurer":
        return financial_value(name)
    o = S.simulate(spec)
    r, tax = spec["r"], spec["tax"]
    F = spec.get("F", S.F)
    n = 5 + F
    dp = spec.get("debt", "none")
    d = (dp[1] if dp != "none" else 0.0) if use_delta else 0.0
    kd = dp[2] if dp != "none" else 0.0
    # ---- code-measured base: pooled ratios over years -4..0
    da_org = lambda t: o["da"][t] - o["rou_dep"][t]          # the simulator's D&A excludes amortization (held apart in "amort")
    c_base = pooled(o, lambda t: o["capex"][t])
    d_base = pooled(o, da_org)
    p_base = pooled(o, lambda t: o["lease_principal"][t])
    rou_base = pooled(o, lambda t: o["rou_dep"][t])
    w_int = o["nwc"][0] / o["R"][0]
    # ---- the analyst's inputs (the ideal analyst: the true bridge path; the capex path by override mode)
    R = [o["R"][t] for t in range(0, 6)]
    m = [o["x"][t] / o["R"][t] for t in range(0, 6)]
    if override == "true":
        c = [o["capex"][t] / o["R"][t] for t in range(1, 6)]           # mode 1: the true path, as a cited plan would state it
    elif override == "none":
        c = [c_base] * 5                                               # mode 3
    else:
        raise ValueError(override)
    # ---- years 1-5
    L = max(3.0, min(40.0, 2.0 * o["ppe"][0] / da_org(0))) if da_org(0) > 0 else 10.0
    dcap = [(c[j] - c_base) * R[j + 1] for j in range(5)]
    flows, I5 = [], None
    das = da_path(o, da_rule, d_base, 5, lambda t: c[t - 1] * R[t]) if da_rule in ("ppe", "uniform", "vintages") else None
    A_ = amort_path(o, 5 + F + 1)
    for t in range(1, 6):
        X = R[t] * m[t]
        capex = c[t - 1] * R[t]
        da = das[t - 1] if das else d_base * R[t]
        if da_rule == "vintage":
            da += (0.5 * dcap[t - 1] + sum(dcap[:t - 1])) / L
        dnwc = w_int * (R[t] - R[t - 1])
        P, ROU = p_base * R[t], rou_base * R[t]
        A = A_[t - 1]
        f = X - (1 - d) * (capex - da + dnwc) - (P - ROU) + tax * A
        flows.append(f)
    X5 = R[5] * m[5]
    # ---- long-run inputs (the ideal analyst's steady state, as in synthetic.desk_inputs)
    SS = S.SS
    g_T = (o["x"][SS + 25] / o["x"][SS]) ** (1 / 25) - 1
    roc_T = sum(roc(o, t, tax) for t in range(SS + 1, SS + 26)) / 25
    roc_0 = roc(o, 0, tax)
    m_L = o["x"][SS] / o["R"][SS]
    g5 = R[5] / R[4] - 1
    g_at = lambda t: g_T if t > n else g5 + (g_T - g5) * (t - 5) / F
    ron_eq = lambda frac: to_equity(ronic_at(roc_0, roc_T, frac), d, kd, tax)
    I5 = X5 - flows[4] + tax * A_[4]          # the shield is carried explicitly in the fade, so it is not part of the gap
    I5_star = s * X5 + g_at(6) / ron_eq(0.0) * (1 - s) * X5
    w5 = (I5 - I5_star) / R[5]
    pv = [f / (1 + r) ** t for t, f in enumerate(flows, 1)]
    Rt, fade = R[5], []
    for t in range(6, n + 1):
        frac = (t - 5) / F
        Rt *= 1 + g_at(t)
        mt = m[5] + (m_L - m[5]) * frac
        Xt = Rt * mt
        tau_w = F if wedge_years is None else wedge_years
        wf = 0.0 if tau_w == 0 else max(0.0, 1 - (t - 5) / tau_w)
        f = Xt * (1 - s) * (1 - g_at(t + 1) / ron_eq(frac)) - w5 * wf * Rt + tax * A_[t - 1]
        fade.append(f)
        pv.append(f / (1 + r) ** t)
    X_N1 = Rt * (1 + g_T) * m_L
    tv = X_N1 * (1 - s) * (1 - g_T / ron_eq(1.0)) / (r - g_T)
    tv_pv = tv / (1 + r) ** n
    return {"value": sum(pv) + tv_pv, "pv_1_5": sum(pv[:5]), "pv_fade": sum(pv[5:]), "tv_pv": tv_pv, "fade_flows": fade,
            "true_fade_flows": [o["fcfe"][t] for t in range(6, n + 1)],
            "seam": fade[0] / flows[4] if flows[4] else None, "flows_1_5": flows, "true_flows_1_5": [o["fcfe"][t] for t in range(1, 6)],
            "w5": w5, "L": L, "c_base": c_base, "d_base": d_base}


def financial_value(name):
    spec = S.FIRMS[name]
    o = S.insurer(spec)
    r, F = spec["r"], 10
    n = 5 + F
    roe = spec["roe"]
    SS = S.SS
    g_T = (o["x"][SS + 25] / o["x"][SS]) ** (1 / 25) - 1
    E = [o["ni"][t] for t in range(0, 6)]
    g = [E[t] / E[t - 1] - 1 for t in range(1, 6)]
    g_at = lambda t: g[t - 1] if t <= 5 else (g_T if t > n else g[4] + (g_T - g[4]) * (t - 5) / F)
    flows, pv, Et = [], [], E[0]
    for t in range(1, n + 1):
        Et *= 1 + g_at(t)
        f = Et * (1 - g_at(t + 1) / roe)
        flows.append(f)
        pv.append(f / (1 + r) ** t)
    tv = Et * (1 + g_T) * (1 - g_T / roe) / (r - g_T)
    tv_pv = tv / (1 + r) ** n
    return {"value": sum(pv) + tv_pv, "pv_1_5": sum(pv[:5]), "pv_fade": sum(pv[5:]), "tv_pv": tv_pv, "seam": flows[5] / flows[4],
            "flows_1_5": flows[:5], "true_flows_1_5": [o["fcfe"][t] for t in range(1, 6)], "w5": None, "L": None}


def truth(name):
    spec = S.FIRMS[name]
    o = S.insurer(spec) if spec["kind"] == "insurer" else S.simulate(spec)
    r = spec["r"]
    F = spec.get("F", S.F)
    n = 5 + F
    return {"value": S.true_value(o, r), "pv_1_5": sum(o["fcfe"][t] / (1 + r) ** t for t in range(1, 6)),
            "pv_fade": sum(o["fcfe"][t] / (1 + r) ** t for t in range(6, n + 1)), "tv_pv": S.pv_after(o, r, n) / (1 + r) ** n}


def main():
    base = {row["firm"]: row for row in json.loads((HERE / "synthetic_baseline.json").read_text(encoding="utf-8"))}
    rows = []
    hdr = f"{'firm':20} {'true':>8} {'today':>8} | {'D2 true-capex pooled-D&A':>26} | {'D2 true-capex vintage-D&A':>26} | {'D2 no override':>18} | periods (pooled), err 1-5 / fade / TV"
    print(hdr)
    for name in S.FIRMS:
        tv = truth(name)
        today = base.get(name, {})
        tod = f"{today['error']:+7.1%}" if "error" in today else "refused"
        a = d2_value(name, "true", "pooled")
        b = d2_value(name, "true", "vintage")
        c = d2_value(name, "none", "pooled")
        e = lambda x, y: x / y - 1 if y else float("nan")
        print(f"{name:20} {tv['value']:8.3f} {tod:>8} | {a['value']:9.3f} {e(a['value'], tv['value']):+7.1%}         | "
              f"{b['value']:9.3f} {e(b['value'], tv['value']):+7.1%}         | {c['value']:9.3f} {e(c['value'], tv['value']):+7.1%} | "
              f"{e(a['pv_1_5'], tv['pv_1_5']):+6.1%} / {e(a['pv_fade'], tv['pv_fade']):+6.1%} / {e(a['tv_pv'], tv['tv_pv']):+6.1%}")
        rows.append({"firm": name, "truth": tv, "today": today.get("error"), "d2_true_pooled": a, "d2_true_vintage": b, "d2_none_pooled": c})
    (HERE / "reference_d2.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()


def da_path(o, rule, d_base, n_years, capex_fn):
    """D&A (organic, non-lease) for years 1..n_years. 'pooled': d_base x R_t. 'rollforward': the base year's net PP&E depreciates at the
    base D&A until exhausted, and each year's capex depreciates straight line over L = 2 net PP&E_0 / D&A_0 from the next year."""
    if rule == "pooled":
        return [d_base * o["R"][t] for t in range(1, n_years + 1)]
    if rule == "vintages":
        # the filed gross PP&E, net PP&E and D&A at the base year imply a life L = gross / D&A and, under a steady geometric vintage
        # profile, the growth g that reproduces net / gross; the existing assets then depreciate vintage by vintage, and each year's capex
        # over L from the next year. Exact for a steady history; an approximation after a shock.
        da0 = o["da"][0] - o["rou_dep"][0]
        gross0, net0 = o["gross_ppe"][0], o["ppe"][0]
        if da0 <= 0 or gross0 <= 0:
            return [d_base * o["R"][t] for t in range(1, n_years + 1)]
        L = max(3, min(60, round(o["gross_ppe"][-1] / da0)))   # D&A of year 0 is the prior year-end gross over the life
        def nr(g):
            w = [(1 + g) ** (-a) for a in range(L)]
            return sum(wi * (1 - a / L) for a, wi in enumerate(w)) / sum(w)
        lo, hi = -0.3, 0.6
        target = net0 / gross0
        for _ in range(80):                          # net/gross falls as g falls: bisect
            mid = (lo + hi) / 2
            if nr(mid) < target:
                lo = mid
            else:
                hi = mid
        g = (lo + hi) / 2
        w = [(1 + g) ** (-a) for a in range(L)]
        k = gross0 / sum(w)
        vint = [k * wi for wi in w]                  # cost by age at the base year end: age 0 depreciates in years 1..L
        out, caps = [], []
        for t in range(1, n_years + 1):
            ex = sum(c / L for a, c in enumerate(vint) if a + t <= L)
            new = sum(c / L for j, c in enumerate(caps, 1) if 0 < t - j <= L)
            out.append(ex + new)
            caps.append(capex_fn(t))
        return out
    if rule == "ppe":
        # D&A follows the asset base, not revenue: the pooled rate D&A / prior net PP&E over the base years, applied to net PP&E rolled
        # forward with capex - D&A
        da_org = lambda k: o["da"][k] - o["rou_dep"][k]
        rate = sum(da_org(k) for k in range(-4, 1)) / sum(o["ppe"][k - 1] for k in range(-4, 1))
        ppe, out = o["ppe"][0], []
        for t in range(1, n_years + 1):
            da = rate * ppe
            out.append(da)
            ppe += capex_fn(t) - da
        return out
    if rule == "uniform":
        # uniform vintages: existing assets' D&A falls linearly to 0 over L = 2 net PP&E_0 / D&A_0; each year's capex depreciates
        # straight line over L from the next year (the filings give net PP&E and D&A, so L is the only life they support)
        da0 = o["da"][0] - o["rou_dep"][0]
        if da0 <= 0:
            return [d_base * o["R"][t] for t in range(1, n_years + 1)]
        L = max(3.0, min(40.0, 2.0 * (o["ppe"][0] - o["lease_liability"][0] * 0) / da0))
        out, caps = [], []
        for t in range(1, n_years + 1):
            out.append(da0 * max(0.0, 1 - t / L) + sum(c / L for k, c in enumerate(caps, 1) if 0 < t - k <= L))
            caps.append(capex_fn(t))
        return out
    da0 = o["da"][0] - o["rou_dep"][0]
    nppe = o["ppe"][0] - (o["lease_liability"][0] * 0 if False else 0.0)
    L = max(3.0, min(40.0, 2.0 * o["ppe"][0] / da0))
    left, out, caps = o["ppe"][0], [], []
    for t in range(1, n_years + 1):
        base = min(da0, max(0.0, left)); left -= base
        new = sum(min(c / L, c) for k, c in enumerate(caps) if t - (k + 1) <= L)
        out.append(base + new)
        caps.append(capex_fn(t))
    return out


def d2_value_state(name, H, da_rule="pooled", s=0.0):
    """O2b as extended levels (step 3 part 1 follow-up): the levels leg runs through year 5 + H, the end of the company's investment
    state (the analyst's cited capex path, its bridge revenue and margin), then the funded path with no gap; N = 5 + max(F, H)."""
    spec = S.FIRMS[name]
    o = S.simulate(spec)
    r, tax = spec["r"], spec["tax"]
    F = spec.get("F", S.F)
    E_end = 5 + H
    n = max(5 + F, E_end)
    dp = spec.get("debt", "none")
    d, kd = (dp[1], dp[2]) if dp != "none" else (0.0, 0.0)
    da_org = lambda t: o["da"][t] - o["rou_dep"][t]
    d_base = pooled(o, da_org)
    p_base = pooled(o, lambda t: o["lease_principal"][t])
    rou_base = pooled(o, lambda t: o["rou_dep"][t])
    w_int = o["nwc"][0] / o["R"][0]
    pv, flows = [], []
    das = da_path(o, da_rule, d_base, E_end, lambda t: o["capex"][t])
    A_ = amort_path(o, n + 1)
    for t in range(1, E_end + 1):
        R_, Rp = o["R"][t], o["R"][t - 1]
        X = o["x"][t]
        f = X - (1 - d) * (o["capex"][t] - das[t - 1] + w_int * (R_ - Rp)) - (p_base - rou_base) * R_ + tax * A_[t - 1]
        flows.append(f)
        pv.append(f / (1 + r) ** t)
    SS = S.SS
    g_T = (o["x"][SS + 25] / o["x"][SS]) ** (1 / 25) - 1
    roc_T = sum(roc(o, t, tax) for t in range(SS + 1, SS + 26)) / 25
    roc_0 = roc(o, 0, tax)
    m_L = o["x"][SS] / o["R"][SS]
    Rt, mE = o["R"][E_end], o["x"][E_end] / o["R"][E_end]
    gE = o["R"][E_end] / o["R"][E_end - 1] - 1
    Fr = n - E_end                                   # the remaining fade after the state ends
    g_at = lambda t: g_T if (Fr == 0 or t > n) else gE + (g_T - gE) * (t - E_end) / Fr
    frac0 = (E_end - 5) / F
    for t in range(E_end + 1, n + 1):
        frac = (t - E_end) / Fr
        Rt *= 1 + g_at(t)
        Xt = Rt * (mE + (m_L - mE) * frac)
        ron = to_equity(ronic_at(roc_0, roc_T, min(1.0, frac0 + (1 - frac0) * frac)), d, kd, tax)
        f = Xt * (1 - s) * (1 - g_at(t + 1) / ron) + tax * A_[t - 1]
        flows.append(f)
        pv.append(f / (1 + r) ** t)
    X_N1 = Rt * (1 + g_T) * m_L
    tv = X_N1 * (1 - s) * (1 - g_T / to_equity(roc_T, d, kd, tax)) / (r - g_T)
    tv_pv = tv / (1 + r) ** n
    return {"value": sum(pv) + tv_pv, "flows": flows, "true_flows": [o["fcfe"][t] for t in range(1, n + 1)], "tv_pv": tv_pv, "n": n}
