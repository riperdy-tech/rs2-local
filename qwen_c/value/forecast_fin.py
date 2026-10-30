"""forecast_fin.py - the financial route's typed forecast to the desk (WO_Q6 §2; O3 retained equity).

record_items: the filed annual record as packet items (kind "filed_record", fact_id "Y<end>"): book equity, net income and the ROE on
opening equity, so the model can cite the record and the contract can check the figures it quotes.
record_bar: forecast.record_bar on the filed ROE record.
build_path: years 1..5 of one scenario under forecast.build_path's rules (years 1-2 typed, years 3..N blended to the normalized ROE by the
transition, years after N held), with book growth in the place of revenue growth and ROE in the place of the margin.
assemble: one scenario to desk.value_financial's input, driver "book". R_1 is the filed FY0 closing book equity (the opening equity of
year 1) and R_{t+1} = R_t (1 + g_t) for t = 1..4. Stated limit: the year-5 book growth does not enter; the desk's fade starts from
R_5 / R_4 - 1, year 4's growth (stamp book_growth_year5_unused).
value: desk.value_financial rolled forward from the fiscal-year end to T at r, as desk.value_operating does (ruling 7).
"""
from qwen_c.value import desk, forecast, inputs

FORECAST_FIN_VERSION = "m3q.forecast.fin.v1"


def _money(v):
    return f"${v / 1e6:,.1f} million"


def record_items(f, years=5):
    """[{fact_id, kind, period, form, source, text}] for the last `years` fiscal years with filed book equity."""
    eq = {v["end"]: v for v in (f.get("equity") or {}).get("values", [])}
    ni = {v["end"]: v for v in (f.get("net_income") or {}).get("values", [])}
    ends = sorted(eq)
    out = []
    for i, end in enumerate(ends):
        if i < len(ends) - years:
            continue
        e = eq[end]
        parts = [f"book equity at year end {_money(e['value'])}"]
        if end in ni:
            parts.append(f"net income {_money(ni[end]['value'])}")
            if i > 0 and eq[ends[i - 1]]["value"] > 0:
                parts.append(f"return on opening equity {100 * ni[end]['value'] / eq[ends[i - 1]]['value']:.1f}%")
        text = f"Filed annual record, fiscal year ended {end} ({e.get('form')}, accession {e.get('accn')}): " + "; ".join(parts) + "."
        out.append({"fact_id": f"Y{end}", "kind": "filed_record", "period": end, "form": e.get("form"),
                    "source": {"accession": e.get("accn"), "concepts": "companyfacts"}, "text": text})
    return out


def record_bar(record_roe):
    if len(record_roe) < inputs.MIN_POOL_YEARS:
        raise desk.DeskRefusal("history_short", f"{len(record_roe)} filed returns on opening equity")
    return forecast.record_bar(record_roe)


def as_operating(sc):
    """The scenario in forecast.build_path's keys (book_growth as rev_growth, roe as op_margin), so the path rules are one function."""
    nm = sc["normalized"]
    return {"rev_growth": sc["book_growth"], "op_margin": sc["roe"], "transition": sc["transition"],
            "transition_year": sc.get("transition_year"),
            "normalized": {"year": nm["year"], "baseline": nm["baseline"], "delta_pts": nm["delta_pts"], "rev_growth": nm["book_growth"]}}


def build_path(sc, bar):
    """([{year, book_growth, roe}] for years 1..5, the normalized ROE)."""
    path, roe_n = forecast.build_path(as_operating(sc), bar, 1.0)
    return [{"year": y["year"], "book_growth": y["rev_growth"], "roe": y["op_margin"]} for y in path], roe_n


def assemble(sc, b, bar, *, r):
    """desk.value_financial input for one scenario `sc` on base `b` (inputs.base_financial) at cost of equity r."""
    path, roe_n = build_path(sc, bar)
    R = [b["R0"], b["R1"]]
    for y in path[:4]:
        R.append(R[-1] * (1.0 + y["book_growth"]))
    roe_t = float(sc["long_run_roe"])
    return {"revenue": R, "margin": [y["roe"] for y in path], "r": float(r), "g_T": float(sc["terminal_g"]), "F": int(sc["fade_years"]),
            "ronic0": b["roe0"], "ronic_T": roe_t, "m_long": roe_t, "shares": b["shares"], "excess_cash": b["excess_cash"],
            "driver": "book", "stub_days": b["stub_days"], "_path": path, "_normalized_roe": roe_n}


def value(inp):
    """desk.value_financial, rolled forward from the fiscal-year end to T at r."""
    stub = inp["stub_days"]
    if not (isinstance(stub, (int, float)) and 0 <= stub <= 800):
        raise desk.DeskRefusal("input_invalid", "stub_days (fiscal-year end to T) must be in [0, 800]")
    v = desk.value_financial({k: x for k, x in inp.items() if k != "stub_days"})
    factor = (1 + float(inp["r"])) ** (float(stub) / 365.0)
    return dict(v, rollforward_factor=factor, stub_days=stub,
                value_per_share=(v["equity_value"] * factor + float(inp["excess_cash"])) / float(inp["shares"]))
