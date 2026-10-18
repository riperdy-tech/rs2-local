"""Step 1 of PLAN_terminal_reinvestment.md: synthetic companies with a known value, and today's desk run on them.

Each firm is simulated from its own economics (physical capacity bought in vintages, straight-line accounting depreciation, working
capital, taxes, a debt policy, acquired-intangible amortization), so its accounts and its cash flows are consistent by construction.
TRUE VALUE = the present value at r of the firm's own equity cash flows (FCFE = NI + D&A + amortization - capex - change in NWC
+ net borrowing) for T years, plus a Gordon tail on the last flow (the firms are in exact steady state long before T).

THE DESK is today's `financial_model_tool.unbundled_dcf` (rev25-bridge worktree, read only), fed the inputs an analyst who knew the
truth would give it: the true owner-earnings growth of years 1-5, the true working-capital changes, the true year-5 earnings and owner
earnings as the long-run reference, the true steady-state growth, return on capital (r_tc at year 0, RONIC_T in steady state) and
earnings margin. Any error is then the desk's method, not the analyst's judgment.

Run: python synthetic.py  -> prints the table and writes synthetic_baseline.json. `--self-test` checks the simulator's identities.
"""
import json, math, sys
from pathlib import Path

WT = Path(r"C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-rev25")
for p in (WT / "tools" / "audit_202608", WT / "tools", WT):
    sys.path.insert(0, str(p))
import financial_model_tool as fmt                                    # noqa: E402

HERE = Path(__file__).resolve().parent
T = 300                 # years valued explicitly
W = 120                 # warm-up years before year 0 (vintages and balances in steady state)
F = 10                  # fade years given to the desk
SS = 100               # a year by which every firm is in steady state (checked; land in H converges only asymptotically)


def simulate(spec):
    """Annual accounts for t = -W .. T. spec keys:
    r, tax, pi, vol(t), p0, margin (EBITDA / revenue) or ebitda_fn(t, st), unit_cost(t), life (physical, years), acct_life,
    dep_share (depreciable share of unit cost), retire (units leave service after `life`), w (NWC / revenue), debt ('none' or
    ('book', lam, kd)), amort(t) (acquired-intangible amortization, tax deductible), rc (recurring capex / revenue), rc_life."""
    tax, pi, life, L = spec["tax"], spec["pi"], spec["life"], spec.get("acct_life", spec["life"])
    ds, retire, w = spec.get("dep_share", 1.0), spec.get("retire", True), spec.get("w", 0.0)
    rc, rcl = spec.get("rc", 0.0), spec.get("rc_life", 10)
    ts = list(range(-W, T + 2))
    u, cost, rcx = {}, {}, {}           # units bought at end of t, their unit cost, recurring capex at t
    out = {k: {} for k in ("R", "ebitda", "da", "amort", "ebit", "capex", "nwc", "ppe", "ic", "debt", "interest", "ni", "x", "oe",
                           "fcfe", "nopat", "lease_principal", "lease_interest", "lease_liability", "rou_dep")}
    imp_y, imp_f = spec.get("impair", (None, 1.0))
    bk = lambda s_, t_: (imp_f if (imp_y is not None and s_ < imp_y <= t_) else 1.0)   # book factor of vintage s_ in year t_
    leased, il = spec.get("leased", False), spec.get("lease_rate", 0.05)   # IFRS 16 lessee: capacity is leased, not bought
    pmt_f = il / (1 - (1 + il) ** -life)
    leases = []                         # [balance, payment] per active lease
    price = lambda t: spec["p0"] * (1 + pi) ** t
    # start: units for the warm-up's first years, bought in the past at a steady state of the vol path
    # starting vintages shaped to the warm-up's own growth gw (u_s proportional to (1+gw)^s, summing to the capacity in service), so the
    # warm-up starts in steady state and no replacement echo rings through it; non-retiring assets get the same shape over one life
    gw = spec["vol"](-W + 1) / spec["vol"](-W) - 1
    shape = [(1 + gw) ** (s + W) for s in range(-W - life, -W)]
    k = spec["vol"](-W) / sum(shape)
    for s, sh in zip(range(-W - life, -W), shape):
        u[s] = k * sh
        cost[s] = spec["unit_cost"](s)
        rcx[s] = rc * spec["p0"] * (1 + pi) ** s * spec["vol"](s) if rc else 0.0
    debt_prev, nwc_prev = None, None
    for t in ts:
        in_service = sum(u.get(s, 0.0) for s in range(t - life, t)) if retire else sum(v for s, v in u.items() if s < t)
        vol = min(spec["vol"](t), in_service) if spec.get("capacity_bound") else spec["vol"](t)
        R = price(t) * vol
        da = sum(ds * cost[s] * u[s] * bk(s, t) / L for s in u if t - L <= s <= t - 1) + sum(rcx[s] / rcl for s in rcx if t - rcl <= s <= t - 1)
        st = {"t": t, "R": R, "da": da, "ic_prev": out["ic"].get(t - 1)}
        ebitda = spec["ebitda_fn"](t, st) if "ebitda_fn" in spec else spec["margin"](t) * R
        if "ebitda_fn" in spec and spec.get("revenue_from_ebitda"):
            R = ebitda / spec["revenue_from_ebitda"]
        am = spec.get("amort", lambda t: 0.0)(t)
        # capacity for next year: units still in service next year plus what must be bought
        keep = sum(u.get(s, 0.0) for s in range(t + 1 - life, t)) if retire else in_service
        u[t] = max(0.0, spec["vol"](t + 1) - keep)
        cost[t] = spec["unit_cost"](t)
        rcx[t] = rc * R
        capex = (0.0 if leased else cost[t] * u[t]) + rcx[t]
        l_int = l_prin = 0.0
        if leased:
            # payments on the leases open during year t (signed at the end of an earlier year), then the new lease signed at the end of t
            for ls in leases:
                i_ = il * ls[0]
                l_int += i_
                l_prin += ls[1] - i_
                ls[0] -= ls[1] - i_
            leases = [ls for ls in leases if ls[0] > 1e-12]
            leases.append([cost[t] * u[t], cost[t] * u[t] * pmt_f])
        ppe = (sum(cost[s] * u[s] * bk(s, t) * (1 - ds * min(L, t - s) / L) for s in u if (s > t - life or not retire) and s <= t)
               + sum(rcx[s] * (1 - min(rcl, t - s) / rcl) for s in rcx if t - rcl < s <= t))
        gross = (sum(cost[s] * u[s] * bk(s, t) for s in u if s <= t and t - s < L) if retire else
                 sum(cost[s] * u[s] * bk(s, t) for s in u if s <= t))
        out.setdefault("gross_ppe", {})[t] = gross
        nwc = w * R
        ic = ppe + nwc
        dp = spec.get("debt", "none")
        debt = 0.0 if dp == "none" else dp[1] * ic
        kd = 0.0 if dp == "none" else dp[2]
        interest = kd * (debt_prev if debt_prev is not None else debt)
        ebit = ebitda - da - am
        ni = (ebit - interest - l_int) * (1 - tax)
        fcfe = (ni + da + am - capex - (nwc - (nwc_prev if nwc_prev is not None else nwc)) + (debt - (debt_prev if debt_prev is not None else debt))
                - l_prin)
        for k, v in (("R", R), ("ebitda", ebitda), ("da", da), ("amort", am), ("ebit", ebit), ("capex", capex), ("nwc", nwc),
                     ("ppe", ppe), ("ic", ic), ("debt", debt), ("interest", interest), ("ni", ni), ("x", ni + am * (1 - tax)),
                     ("oe", ni + da + am - capex), ("fcfe", fcfe), ("nopat", (ebit + am) * (1 - tax)), ("lease_principal", l_prin),
                     ("lease_interest", l_int), ("lease_liability", sum(ls[0] for ls in leases)), ("rou_dep", da if leased else 0.0)):
            out[k][t] = v
        debt_prev, nwc_prev = debt, nwc
    return out


def insurer(spec):
    """Book-equity insurer: NI_t = ROE x BV_{t-1}; BV grows at g(t); FCFE = NI - change in BV; premiums R = prem x BV_{t-1}."""
    out = {k: {} for k in ("R", "ni", "x", "oe", "fcfe", "bv", "da", "capex", "nwc", "ic", "nopat", "debt")}
    bv = 1.0
    for t in range(-W, T + 2):
        ni = spec["roe"] * bv
        nb = bv * (1 + spec["g"](t))
        for k, v in (("R", spec["prem"] * bv), ("ni", ni), ("x", ni), ("oe", ni), ("fcfe", ni - (nb - bv)), ("bv", nb), ("da", 0.0),
                     ("capex", 0.0), ("nwc", 0.0), ("ic", nb), ("nopat", ni), ("debt", 0.0)):
            out[k][t] = v
        bv = nb
    return out


def true_value(o, r):
    pv = sum(o["fcfe"][t] / (1 + r) ** t for t in range(1, T + 1))
    g = o["fcfe"][T + 1] / o["fcfe"][T] - 1
    return pv + o["fcfe"][T + 1] / (r - g) / (1 + r) ** T


def pv_after(o, r, n):
    """Value at year n of the true flows after n."""
    return sum(o["fcfe"][t] / (1 + r) ** (t - n) for t in range(n + 1, T + 1)) + \
        o["fcfe"][T + 1] / (r - (o["fcfe"][T + 1] / o["fcfe"][T] - 1)) / (1 + r) ** (T - n)


def desk_inputs(o, r, F=F):
    oe = [o["oe"][t] for t in range(0, 6)]
    g = [oe[t] / oe[t - 1] - 1 for t in range(1, 6)] if all(x > 0 for x in oe) else None
    roic = lambda t: o["nopat"][t] / o["ic"][t - 1]
    n = 5 + F
    # steady-state figures over a 25-year window (a lumpy fleet replaces in cycles; the window spans one)
    g_t = (o["x"][SS + 25] / o["x"][SS]) ** (1 / 25) - 1
    ronic_t = sum(roic(t) for t in range(SS + 1, SS + 26)) / 25
    return {"base_cf": oe[0], "explicit_growth": g, "discount_rate": r,
            "terminal_g": g_t, "fade_years": F, "terminal_ronic": ronic_t,
            "working_capital": [o["nwc"][t] - o["nwc"][t - 1] for t in range(1, 6)],
            "long_run": {"e5": o["x"][5], "oe5": oe[5], "m5": o["x"][5] / o["R"][5], "r_tc": roic(0), "stub_months": 0},
            "long_run_margin": o["x"][SS] / o["R"][SS], "shares_diluted": 1.0, "net_debt": 0.0, "sbc_treatment": "deducted_in_cf"}


def desk(inp):
    if inp["base_cf"] <= 0 or inp["explicit_growth"] is None:
        return {"error": "owner earnings not positive in years 0-5: the desk refuses (base_cf must be positive) or cannot grow them"}
    return fmt.unbundled_dcf(**inp)


P = 0.025
FIRMS = {
    "A_compounder": dict(kind="sim", what="real growth 1%, inflation 2.5%, asset life 15, no debt: the value driver should be exact",
                         r=0.09, tax=0.25, pi=P, p0=1.0, vol=lambda t: 1.01 ** t, margin=lambda t: 0.25,
                         unit_cost=lambda t: 1.6 * (1 + P) ** t, life=15, w=0.10),
    "B_newbuild": dict(kind="sim", what="shipowner: fleet flat, then a 3-year newbuild programme doubles it (years 1-3), then flat; life 25",
                       r=0.09, tax=0.0, pi=P, p0=1.0,
                       vol=lambda t: 1.0 if t <= 1 else (1.0 + min(t - 1, 3) / 3.0), margin=lambda t: 0.55,
                       unit_cost=lambda t: 6.0 * (1 + P) ** t, life=25, w=0.02),
    "B2_newbuild": dict(kind="sim", what="shipowner: a smaller programme adds 12% to the fleet over years 1-3 (owner earnings stay positive); life 25",
                        r=0.09, tax=0.0, pi=P, p0=1.0,
                        vol=lambda t: 1.0 if t <= 1 else (1.0 + 0.12 * min(t - 1, 3) / 3.0), margin=lambda t: 0.55,
                        unit_cost=lambda t: 6.0 * (1 + P) ** t, life=25, w=0.02),
    "C2_depleter_levered": dict(kind="sim", what="firm C with 40% debt at book and 5% interest (tests S's tax and delta treatment)",
                                r=0.09, tax=0.30, pi=P, p0=1.0, vol=lambda t: 1.0, margin=lambda t: 0.55,
                                unit_cost=lambda t: 2.2 * (1 + P) ** t * 1.03 ** min(max(t, 0), 20), life=10, w=0.05, F=25,
                                debt=("book", 0.4, 0.05)),
    "C3_impaired": dict(kind="sim", what="depleter, flat output, cost with the price, asset life 10; at year -1 every asset then held is written "
                                         "down by 50% (book only: DD&A and capital fall, replacement cost does not)",
                        r=0.09, tax=0.30, pi=P, p0=1.0, vol=lambda t: 1.0, margin=lambda t: 0.55,
                        unit_cost=lambda t: 2.2 * (1 + P) ** t, life=10, w=0.05, impair=(-1, 0.5)),
    "C_depleter": dict(kind="sim", what="production flat; reserve (asset) life 10; replacement cost per unit rises 3% a year faster than "
                                        "the price for years 0-20, then with it",
                       r=0.09, tax=0.30, pi=P, p0=1.0, vol=lambda t: 1.0, margin=lambda t: 0.55,
                       unit_cost=lambda t: 2.2 * (1 + P) ** t * 1.03 ** min(max(t, 0), 20), life=10, w=0.05, F=25),
    "D_acquirer": dict(kind="sim", what="firm A plus acquired-intangible amortization of 4% of year-0 revenue, years -5..9, tax deductible",
                       r=0.09, tax=0.25, pi=P, p0=1.0, vol=lambda t: 1.01 ** t, margin=lambda t: 0.25,
                       unit_cost=lambda t: 1.6 * (1 + P) ** t, life=15, w=0.10, amort=lambda t: 0.04 if -5 <= t <= 9 else 0.0),
    "E_holiday": dict(kind="sim", what="venue owner: demand fell 40% at year -1, leaving spare capacity into year 12; it recovers at 2% real to year 15, "
                                       "then 0.5% real; retiring units are not replaced while capacity is spare (D&A above capex); life 40",
                      r=0.09, tax=0.25, pi=P, p0=1.0,
                      vol=lambda t: 1.0 if t <= -2 else 0.6 * 1.02 ** (min(t, 15) + 1) * 1.005 ** max(t - 15, 0),
                      margin=lambda t: 0.35, unit_cost=lambda t: 3.0 * (1 + P) ** t, life=40, w=0.0, F=15),
    "I_lessee": dict(kind="sim", what="firm A whose capacity is leased under IFRS 16 (lease rate 5%, 15-year leases): ROU depreciation in "
                                      "D&A, lease interest in net income, principal in financing, no capex for leased units",
                     r=0.09, tax=0.25, pi=P, p0=1.0, vol=lambda t: 1.01 ** t, margin=lambda t: 0.25,
                     unit_cost=lambda t: 1.6 * (1 + P) ** t, life=15, w=0.10, leased=True, lease_rate=0.05),
    "F_insurer": dict(kind="insurer", what="ROE 12%; book equity grows 8% in years 1-5, fading to 3.5% by year 15", r=0.09,
                      roe=0.12, prem=1.5, g=lambda t: 0.035 if t <= 0 else (0.08 if t <= 5 else max(0.035, 0.08 - 0.0045 * (t - 5)))),
    "G_utility": dict(kind="sim", what="rate base grows 3.5% real for years 0-10 then 0.5%; allowed pre-tax return 8.5% on opening "
                                       "capital; 50% debt at book, 5% interest; life 40",
                      r=0.085, tax=0.21, pi=P, p0=1.0, vol=lambda t: 1.035 ** min(max(t, 0), 10) * 1.005 ** max(t - 10, 0),
                      ebitda_fn=lambda t, st: st["da"] + 0.085 * (st["ic_prev"] if st["ic_prev"] is not None else 1.0),
                      revenue_from_ebitda=0.40, unit_cost=lambda t: 1.0 * (1 + P) ** t, life=40, w=0.0, debt=("book", 0.5, 0.05)),
    "H_reit": dict(kind="sim", what="buildings never retire (recurring capex 1.5% of revenue keeps them); accounting depreciation of 80% of "
                                    "cost over 40 years; acquisitions grow units 3% real for years 0-10, 1% before and after; 40% debt at book",
                   r=0.085, tax=0.0, pi=P, p0=1.0, vol=lambda t: 1.01 ** t * 1.02 ** min(max(t, 0), 10), margin=lambda t: 0.65,
                   unit_cost=lambda t: 12.0 * (1 + P) ** t, life=40, acct_life=40, dep_share=0.8, retire=False, rc=0.015, rc_life=10,
                   w=0.0, debt=("book", 0.4, 0.05)),
}


def run_firm(name, spec):
    o = insurer(spec) if spec["kind"] == "insurer" else simulate(spec)
    r = spec["r"]
    tv = true_value(o, r)
    Ff = spec.get("F", F)                # the ideal analyst's fade: until the firm reaches its steady state
    inp = desk_inputs(o, r, Ff)
    if spec["kind"] == "insurer":
        inp["terminal_ronic"], inp["long_run"]["r_tc"] = spec["roe"], spec["roe"]     # the analyst reads RONIC_T as the ROE (as the pack does)
    res = desk(inp)
    row = {"firm": name, "what": spec["what"], "true_value": tv, "steady": abs(o["x"][SS + 1] / o["x"][SS] - o["x"][SS + 21] / o["x"][SS + 20]) < 1e-6}
    n = 5 + Ff
    row["true_pv_1_5"] = sum(o["fcfe"][t] / (1 + r) ** t for t in range(1, 6))
    row["true_pv_6_n"] = sum(o["fcfe"][t] / (1 + r) ** t for t in range(6, n + 1))
    row["true_tv_pv"] = pv_after(o, r, n) / (1 + r) ** n
    row["inputs"] = {k: v for k, v in inp.items() if k not in ("shares_diluted", "net_debt", "sbc_treatment")}
    row["true_fcfe_1_6"] = [o["fcfe"][t] for t in range(1, 7)]
    if res.get("error"):
        row["desk_error"] = res["error"]
        return row
    pv = res["pv_cfs"]
    row.update(desk_value=res["per_share_iv_raw"], error=res["per_share_iv_raw"] / tv - 1, desk_pv_1_5=sum(pv[:5]),
               desk_pv_6_n=sum(pv[5:n]), desk_tv_pv=res["terminal_value_pv"], desk_flows_1_6=res["projected_cfs"][:6],
               seam=res["projected_cfs"][5] / res["projected_cfs"][4] if res["projected_cfs"][4] else None,
               true_seam=o["fcfe"][6] / o["fcfe"][5] if o["fcfe"][5] else None, stamps=res["stamps"])
    return row


def self_test():
    """Identities the simulator must hold: clean surplus on book capital, and the value-driver identity in steady state."""
    for name in ("A_compounder", "G_utility", "H_reit"):
        o = simulate(FIRMS[name])
        t = SS
        reinvest = o["capex"][t] - o["da"][t] + (o["nwc"][t] - o["nwc"][t - 1])
        assert abs((o["ic"][t] - o["ic"][t - 1]) - reinvest) < 1e-9 * max(1, o["ic"][t]), (name, "capital roll-forward")
        g = o["x"][t + 1] / o["x"][t] - 1
        g_ic = o["ic"][t] / o["ic"][t - 1] - 1
        assert abs(g - g_ic) < (1e-3 if name == "H_reit" else 1e-6), (name, "steady state: earnings and capital grow alike", g, g_ic)
    o = simulate(FIRMS["A_compounder"])
    t = SS
    g = o["x"][t + 1] / o["x"][t] - 1
    roic = o["nopat"][t] / o["ic"][t - 1]
    vd = o["x"][t] * (1 - g / roic)
    actual = o["oe"][t] - (o["nwc"][t] - o["nwc"][t - 1])
    print(f"self-test: firm A steady-state value driver {vd:.6f} vs actual flow {actual:.6f} (ratio {actual / vd:.6f})")
    print("self-test passed")


def lease_variants():
    """REPORT_step2_lease_audit.md section 3: firm I today, with base_cf less lease principal, and with the return also after lease interest."""
    spec = FIRMS["I_lessee"]; o = simulate(spec); r = spec["r"]; tv = true_value(o, r)
    inp = desk_inputs(o, r)
    oe = [o["oe"][t] - o["lease_principal"][t] for t in range(6)]
    a = dict(inp, base_cf=oe[0], explicit_growth=[oe[t] / oe[t - 1] - 1 for t in range(1, 6)], long_run=dict(inp["long_run"], oe5=oe[5]))
    roic = lambda t: (o["nopat"][t] - o["lease_interest"][t] * (1 - spec["tax"])) / (o["ic"][t - 1] - o["lease_liability"][t - 1])
    b = dict(a, terminal_ronic=sum(roic(t) for t in range(SS + 1, SS + 26)) / 25, long_run=dict(a["long_run"], r_tc=roic(0)))
    for label, x in (("today", inp), ("(a) base_cf less lease principal", a), ("(b) (a) + return after lease interest, capital ex leases", b)):
        res = desk(x)
        print(f"{label:58} {res['per_share_iv_raw']:.3f} {res['per_share_iv_raw'] / tv - 1:+.1%}  (true {tv:.3f})")


def main():
    if "--lease-variants" in sys.argv:
        lease_variants()
        return
    if "--self-test" in sys.argv:
        self_test()
        return
    rows = [run_firm(k, v) for k, v in FIRMS.items()]
    print(f"{'firm':13} {'true':>9} {'desk':>9} {'error':>7} | {'PV1-5 t/d':>15} | {'PV6-N t/d':>15} | {'TV t/d':>15} | seam d/t  | steady")
    for r in rows:
        if "desk_error" in r:
            print(f"{r['firm']:13} {r['true_value']:9.3f} {'refused':>9}         | {r['desk_error'][:80]}")
            continue
        print(f"{r['firm']:13} {r['true_value']:9.3f} {r['desk_value']:9.3f} {r['error']:+7.1%} | {r['true_pv_1_5']:7.3f}/{r['desk_pv_1_5']:<7.3f} | "
              f"{r['true_pv_6_n']:7.3f}/{r['desk_pv_6_n']:<7.3f} | {r['true_tv_pv']:7.3f}/{r['desk_tv_pv']:<7.3f} | "
              f"{r['seam'] or float('nan'):4.2f}/{r['true_seam'] or float('nan'):4.2f} | {r['steady']}")
    (HERE / "synthetic_baseline.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
