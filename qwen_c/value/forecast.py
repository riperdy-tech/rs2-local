"""forecast.py - the analyst's typed forecast to the desk (SPEC_m3q §2; WO_Q5 §1).

record_items: the filed annual record as packet items (kind "filed_record", one per fiscal year, fact_id "Y<end>"), built by code from
facts.py so the model can cite the multi-year record and the contract can check the figures it quotes.
record_bar: the operating-margin statistics of that record (min, p25, median, p75, max, last), the baselines a normalized margin starts from.
build_path: years 1..5 of one scenario (rev 26's rules, r26_forecast.build_path: years 1-2 typed, years 3..N blended to the normalized
value by the transition, years after N held).
assemble: one scenario to desk.value_operating's input, the margins bridged from the GAAP operating basis to X (inputs.bridge_x_margin).
"""
import statistics

from qwen_c.value import inputs
from qwen_c.value.desk import DeskRefusal

FORECAST_VERSION = "m3q.forecast.v1"
BASELINES = ("min", "p25", "median", "p75", "max", "last")
TRANSITIONS = ("linear", "step_at_year", "hold_then_linear")


def _money(v):
    return f"${v / 1e6:,.1f} million"


def record_items(f, years=5):
    """[{fact_id, kind, period, form, source, text}] for the last `years` fiscal years with revenue."""
    by = {c: {v["end"]: v for v in (f.get(c) or {}).get("values", [])} for c in ("revenue", "operating_income", "net_income", "da", "capex")}
    out = []
    for end in sorted(by["revenue"])[-years:]:
        rv = by["revenue"][end]
        parts = [f"revenue {_money(rv['value'])}"]
        oi = by["operating_income"].get(end)
        if oi:
            parts.append(f"operating income {_money(oi['value'])}")
            parts.append(f"operating margin {100 * oi['value'] / rv['value']:.1f}%")
        for c, label in (("net_income", "net income"), ("da", "depreciation and amortization"), ("capex", "capital expenditure")):
            if end in by[c]:
                parts.append(f"{label} {_money(by[c][end]['value'])}")
        text = f"Filed annual record, fiscal year ended {end} ({rv['form']}, accession {rv['accn']}): " + "; ".join(parts) + "."
        out.append({"fact_id": f"Y{end}", "kind": "filed_record", "period": end, "form": rv["form"],
                    "source": {"accession": rv["accn"], "concepts": "companyfacts"}, "text": text})
    return out


def record_bar(record_margins):
    """{min, p25, median, p75, max, last} of the filed operating margins ({end: margin})."""
    vals = [record_margins[e] for e in sorted(record_margins)]
    if len(vals) < inputs.MIN_POOL_YEARS:
        raise DeskRefusal("history_short", f"{len(vals)} filed operating margins")
    q = statistics.quantiles(vals, n=4, method="inclusive")
    return {"min": min(vals), "p25": q[0], "median": statistics.median(vals), "p75": q[2], "max": max(vals), "last": vals[-1]}


def _blend(start, target, t, n, transition, k):
    if t >= n:
        return target
    if transition == "linear":
        return start + (target - start) * (t - 2) / (n - 2)
    if transition == "step_at_year":
        return target if t >= int(k) else start
    if transition == "hold_then_linear":
        return start if t <= int(k) else start + (target - start) * (t - int(k)) / (n - int(k))
    raise DeskRefusal("input_invalid", f"unknown transition {transition!r}")


def build_path(sc, bar, rev0):
    """[{year, rev_growth, op_margin, revenue}] for years 1..5 and the normalized margin."""
    nm = sc["normalized"]
    if nm["baseline"] not in BASELINES:
        raise DeskRefusal("input_invalid", f"baseline {nm['baseline']!r}")
    n = int(nm["year"])
    if not 3 <= n <= 5:
        raise DeskRefusal("input_invalid", f"normalized year {n} outside 3..5")
    if sc["transition"] != "linear" and not (sc.get("transition_year") and 3 <= int(sc["transition_year"]) <= n):
        raise DeskRefusal("input_invalid", "step_at_year and hold_then_linear need transition_year in 3..N")
    m_n = bar[nm["baseline"]] + float(nm["delta_pts"]) * 0.01
    g, m = [float(x) for x in sc["rev_growth"]], [float(x) for x in sc["op_margin"]]
    rev, years = float(rev0), []
    for t in range(1, 6):
        if t <= 2:
            gt, mt = g[t - 1], m[t - 1]
        else:
            gt = _blend(g[-1], float(nm["rev_growth"]), t, n, sc["transition"], sc.get("transition_year"))
            mt = _blend(m[-1], m_n, t, n, sc["transition"], sc.get("transition_year"))
        rev *= 1.0 + gt
        years.append({"year": t, "rev_growth": gt, "op_margin": mt, "revenue": rev})
    return years, m_n


def assemble(sc, b, bar, *, r):
    """desk.value_operating input for one scenario `sc` (the merged base + replacements) on base `b` (inputs.base) at cost of equity r."""
    path, m_n = build_path(sc, bar, b["R0"])
    rev = [b["R0"]] + [y["revenue"] for y in path]
    x_m = inputs.bridge_x_margin(b, [y["op_margin"] for y in path], rev[1:])
    capex = [b["c_ratio"] * R for R in rev[1:]]
    h = 0
    ip = sc.get("investment_path")
    if ip:
        h = len(ip)
        for j, yr in enumerate(ip):
            if yr["year"] != 6 + j:
                raise DeskRefusal("input_invalid", "investment_path years must run 6, 7, ... without gaps")
            R = rev[-1] * (1 + float(yr["revenue_growth"]))
            rev.append(R)
            x_m += inputs.bridge_x_margin(b, [float(yr["op_margin"])], [R])
            capex.append(float(yr["capex_over_revenue"]) * R)
    m_long = inputs.bridge_x_margin(b, [float(sc["long_run_op_margin"])], [rev[5]])[0]
    ronic_t = float("inf") if sc["terminal_ronic"] == "unlimited" else float(sc["terminal_ronic"])
    return {"revenue": rev, "margin": x_m, "capex": capex, "d_ratio": b["d_ratio"], "w": b["w"], "p_ratio": b["p_ratio"],
            "rou_ratio": b["rou_ratio"], "amort_schedule": b["amort_schedule"], "amort_thereafter": b["amort_thereafter"],
            "delta": b["delta"], "kd": b["kd"], "tau": b["tau"], "r": float(r), "g_T": float(sc["terminal_g"]), "F": int(sc["fade_years"]),
            "H": h, "ronic0": b["ronic0"], "ronic_T": ronic_t, "m_long": m_long, "shares": b["shares"], "excess_cash": b["excess_cash"],
            "_path": path, "_normalized_op_margin": m_n}
