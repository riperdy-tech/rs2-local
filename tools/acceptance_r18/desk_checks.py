"""The desk-side arithmetic AT1a and AT1e share (revision 18 acceptance). Offline; works on the rows of build_day.py.

`desk_parity(ns, rows)` - AT1a: for every name with a printed reference, the desk's Base value on the facts the pack PRINTS (parsed back from
the pack text's DEFAULTS block) with the reference's own base and growth path at full precision, against the reference's value, unrounded
(amendment 1, point 3: the desk's rounding to the cent is not part of its arithmetic; |desk - reference| < $0.005). Names whose reference is
cash-only are excluded and counted (the desk cannot value a zero operating business); any other name the desk cannot run is listed with the
reason - by class and count, never by name when `names=False`.

`round_trips(ns, rows)` - AT1e (amendment 2, point 3). For every name with a printed reference whose reverse DCF runs:
  g* is the reference's year-1 growth (path[0] of the growth method); where there is none (a levels name) g* = 5%.
  (a) own structure: price = unbundled_dcf per-share value at a constant stage-1 growth g* on the DEFAULTS inputs the desk's reverse call
      uses (base = reference_base_b, rate = coe_anchor, terminal_g_default, 5 fade years, the DEFAULTS terminal_ronic, long_run,
      working_capital and excess_cash); reverse_dcf_expectations_gap with the same excess cash must return g* within 0.1 pp.
  (b) neutral structure: price = _neutral_reference_dcf value at g* plus the DEFAULTS excess cash per share; the neutral solve with the same
      excess cash must return g* within 0.1 pp.
  Reported, not a bar: both round trips without the cash term. Names the reverse DCF cannot run are counted with the reason.
"""
import math
import statistics

B = 1e9
TOL_PP = 0.1
CENT = 0.005
FADE_YEARS = 5
DEFAULT_G_STAR = 0.05
PRINTED = ("used", "outside_fence_above", "outside_fence_below")


def _printed(row):
    return row.get("error") is None and row.get("status") in PRINTED and isinstance(row.get("reference"), dict) \
        and row["reference"].get("value") is not None


def desk_parity(ns, rows, *, names=True, tol=CENT):
    fmt, pack_facts = ns.fmt, ns.pack_facts
    real_round = getattr(fmt, "round", None)
    fmt.round = lambda x, nd=None: x                      # the desk's own rounding is not part of its arithmetic
    try:
        checked, maxdiff, fails, cash_only, nonpos, unrun, no_desk = 0, 0.0, [], 0, 0, [], 0
        for key, r in sorted(rows.items()):
            if not _printed(r):
                continue
            f, ref = r["facts"], r["reference"]
            if r["status"] == "not_meaningful":
                continue
            if ref["method"] == "cash_only":
                cash_only += 1
                continue
            parsed = pack_facts.from_text(r["text"])
            B_ = B
            lv = ref["levels"]
            if ref["base_cf"] is not None:
                base, path = ref["base_cf"] / B_, ref["path"]
            else:
                # amendment 1: a levels name's base is its year-1 owner-earnings level after the cash term (the printed reference_base_b)
                base = lv[0] / B_
                path = [0.0, lv[1] / lv[0] - 1] + ref["path"][2:]
            if base <= 0:
                nonpos += 1
                unrun.append((key if names else None, "the year-1 owner-earnings level after the cash term is not positive"))
                continue
            coe = parsed["coe_anchor"]
            sc = lambda name, prob, w: {"name": name, "prob": prob, "base_cf": base, "explicit_growth": list(path), "wacc": w}
            reasons = {k: "diagnostic" for k in ("cash_flow_life_reason", "base_cf_reason", "scenario_deviation_reason", "bull_below_price_reason",
                                                 "bear_above_price_reason", "terminal_reason", "coe_adjustment_reason", "shares_reason",
                                                 "guidance_deviation_reason", "excess_cash_reason")}
            call = dict(reasons, scenarios=[sc("Base", 0.4, coe), sc("Bull", 0.3, coe - 0.0005), sc("Bear", 0.3, coe + 0.0005)],
                        terminal_g=parsed["terminal_g_default"], fade_years=FADE_YEARS, sbc_treatment="deducted_in_cf",
                        cash_flow_life="perpetual")
            ctx = {"price": 1e6, "shares_default_b": parsed["shares_default"] / B_, "coe_anchor": coe,
                   "terminal_g_default": parsed["terminal_g_default"], "terminal_g_anchor": parsed["terminal_g_anchor"],
                   "owner_earnings_default_b": parsed["owner_earnings_default_b"], "levels": parsed["levels"],
                   "terminal_ronic": parsed["terminal_ronic"], "long_run": parsed["long_run"], "working_capital": parsed["working_capital"],
                   "cash_basis_b": parsed["cash_basis_b"], "reference_base_b": parsed["reference_base_b"],
                   "excess_cash": parsed["excess_cash"], "reference_status": parsed["reference_status"]}
            out = fmt.execute_financial_model(call, ctx)
            if "error" in out:
                # a stand-in Bull or Bear can break the scenario order; the Base is what is under test, so it is valued alone
                dcf = fmt.unbundled_dcf(base_cf=base, explicit_growth=path, wacc=coe, terminal_g=parsed["terminal_g_default"],
                                        shares_diluted=parsed["shares_default"] / B_, fade_years=FADE_YEARS, sbc_treatment="deducted_in_cf",
                                        terminal_ronic=parsed["terminal_ronic"], long_run=parsed["long_run"],
                                        working_capital=parsed["working_capital"], excess_cash=parsed["excess_cash"])
                no_desk += 1
            else:
                dcf = out["scenario_dcfs"][0]["dcf"]
            if "per_share_iv" not in dcf:
                unrun.append((key if names else None, str(dcf.get("error"))[:120]))
                continue
            d = abs(dcf["per_share_iv"] - ref["value"])
            checked += 1
            maxdiff = max(maxdiff, d)
            if not d < tol:
                fails.append((key if names else None, d, r["status"], ref["method"]))
    finally:
        if real_round is None:
            del fmt.round
        else:
            fmt.round = real_round
    ok = checked > 0 and not fails
    return {"at": "AT1a desk parity", "pass": ok, "names_compared": checked, "max_abs_difference": maxdiff, "differences_at_or_above_bar": len(fails),
            "fails": sorted(fails, key=lambda x: -x[1])[:20], "cash_only_excluded": cash_only,
            "cannot_run_listed": unrun, "cannot_run_count": len(unrun), "base_valued_alone": no_desk, "bar": f"|desk - reference| < ${tol}",
            "summary": f"{checked} names compared, max |difference| ${maxdiff:.6f}, {len(fails)} at or above ${tol}; {cash_only} cash-only "
                       f"excluded; {len(unrun)} the desk cannot run (listed)"}


def _gstar(row):
    ref = row["reference"]
    path = ref.get("path")
    if ref.get("method") == "growth" and path and path[0] is not None:
        return float(path[0]), "reference year-1 growth"
    return DEFAULT_G_STAR, "no year-1 growth: 5%"


def round_trips(ns, rows, *, names=True, tol_pp=TOL_PP):
    fmt, pack_facts = ns.fmt, ns.pack_facts
    reasons, diffs = {}, {"a": [], "b": [], "a_no_cash": [], "b_no_cash": []}
    fails, run = [], 0

    def skip(why):
        reasons[why] = reasons.get(why, 0) + 1
    for key, r in sorted(rows.items()):
        if not _printed(r):
            continue
        if r["status"] == "not_meaningful":
            continue
        ref, parsed = r["reference"], pack_facts.from_text(r["text"])
        if ref["method"] == "cash_only":
            skip("cash-only reference: no operating business to solve for")
            continue
        base = parsed.get("reference_base_b")
        shares = parsed.get("shares_default")
        coe, tg, tga = parsed.get("coe_anchor"), parsed.get("terminal_g_default"), parsed.get("terminal_g_anchor")
        if not all(isinstance(x, (int, float)) for x in (base, shares, coe, tg, tga)):
            skip("a DEFAULTS input is not available")
            continue
        if not (base > 0 and shares > 0 and coe > tg and coe > tga):
            skip("a DEFAULTS input is out of range (base, shares, or rate not above growth)")
            continue
        shares_b = shares / B
        ec = parsed.get("excess_cash")
        cash_b = 0.0 if ec is None else ec                  # a cash term that is not available is zero cash in the round trip
        g, _how = _gstar(r)
        common = dict(base_cf=base, wacc=coe, terminal_g=tg, shares_diluted=shares_b, fade_years=FADE_YEARS, sbc_treatment="deducted_in_cf",
                      terminal_ronic=parsed["terminal_ronic"], long_run=parsed["long_run"], working_capital=parsed["working_capital"])
        rev = dict(shares_diluted=shares_b, base_cf=base, wacc=coe, terminal_g=tg, fade_years=FADE_YEARS, stage1_years=5, net_debt=0.0,
                   valuation_frame="equity", coe_anchor=coe, terminal_g_anchor=tga, terminal_ronic=parsed["terminal_ronic"],
                   long_run=parsed["long_run"], working_capital=parsed["working_capital"])
        res = {}
        for label, cash in (("", cash_b), ("_no_cash", None)):
            own = fmt.unbundled_dcf(explicit_growth=[g] * 5, excess_cash=cash, **common)
            iv_n, _cf, _cagr = fmt._neutral_reference_dcf(base_cf=base, g=g, coe_anchor=coe, terminal_g_anchor=tga, net_debt=0.0,
                                                          shares_diluted=shares_b)
            price_a = own.get("per_share_iv")
            price_b = iv_n + ((cash / shares_b) if cash is not None else 0.0)
            if own.get("error") or price_a is None or not price_a > 0 or not price_b > 0:
                res = None
                skip("the own-structure or neutral value at g* is not positive or cannot be computed")
                break
            ga = fmt.reverse_dcf_expectations_gap(current_price=price_a, excess_cash=cash, **rev)
            gb = fmt.reverse_dcf_expectations_gap(current_price=price_b, excess_cash=cash, **rev)
            sa = (ga.get("own_structure") or {}).get("solved_growth_pct")
            sb = (gb.get("neutral_reference_structure") or {}).get("solved_initial_growth_pct")
            if sa is None or sb is None:
                res = None
                skip("the reverse DCF returned no solution: " + str(ga.get("error") or gb.get("error") or "no neutral structure")[:80])
                break
            res[label] = (sa - g * 100.0, sb - g * 100.0)
        if res is None:
            continue
        run += 1
        da, db = res[""]
        diffs["a"].append(da)
        diffs["b"].append(db)
        diffs["a_no_cash"].append(res["_no_cash"][0])
        diffs["b_no_cash"].append(res["_no_cash"][1])
        if abs(da) > tol_pp or abs(db) > tol_pp:
            fails.append((key if names else None, da, db))

    def summ(v):
        return {"n": len(v), "max_abs_pp": max((abs(x) for x in v), default=None),
                "median_abs_pp": statistics.median([abs(x) for x in v]) if v else None,
                "outside_0.1pp": sum(1 for x in v if abs(x) > tol_pp)}
    ok = run > 0 and not fails
    return {"at": "AT1e reverse DCF round trips", "pass": ok, "names_run": run, "cannot_run_by_reason": reasons,
            "bar": f"both round trips within {tol_pp} pp with the cash term",
            "a_own_structure": summ(diffs["a"]), "b_neutral_structure": summ(diffs["b"]),
            "reported_not_a_bar": {"a_without_cash_term": summ(diffs["a_no_cash"]), "b_without_cash_term": summ(diffs["b_no_cash"])},
            "fails": fails[:20], "fails_count": len(fails),
            "summary": f"{run} names run; (a) own max {summ(diffs['a'])['max_abs_pp']} pp, (b) neutral max {summ(diffs['b'])['max_abs_pp']} pp; "
                       f"{len(fails)} outside {tol_pp} pp; {sum(reasons.values())} cannot run"}
