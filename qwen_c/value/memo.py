"""memo.py - the valuation memo (F_SPEC_valuation_menu §5): every word and number is code's. One line per input (the option, the
resolved number, the record-neutral number, the direction, and for a departure its driver), every cited sentence printed in full
beneath it; then the scenarios, the reverts and stamps, the annotations, and the model's `unknowns` under their own heading, unedited.
The memo carries the authority line: diagnostic only (B9). Stated limit (§2.2): code cannot tell a GAAP operating margin from an adjusted
margin printed in the same unit, so every guidance sentence is printed in full for a reader to judge.
"""
MEMO_VERSION = "m3q.memo.v6"   # v6 2026-11-03 F_SPEC_valuation_menu v1.3 (F11): a ytd input prints its period and filing   # v5 2026-11-03 F_SPEC_valuation_menu §5: code's text from options, drivers and cited sentences   # v4 Q3c: the record-neutral reference   # v3, v2 (see git)


def _pct(x):
    return f"{100 * float(x):.1f}%"


def _num(x):
    if isinstance(x, (list, tuple)):
        return f"{x[0]:.4f} in year 1 to {x[-1]:.4f} in year 5"
    return str(x) if isinstance(x, int) else f"{x:.4f}"


def _opt(x):
    return f"{x[0]} {float(x[1]):+g} pts" if isinstance(x, (list, tuple)) else str(x)


def render(result):
    """Markdown memo of one run.py result."""
    head = f"# {result['ticker']} at {result['T']}: {result['status']}"
    if result.get("status") == "no_call" and not result.get("checks"):
        return f"{head}\n\n{result.get('reason')}: {result.get('detail')}\n"
    chk, vals = result.get("checks") or {}, result.get("values") or {}
    lines = [head, "", "**Authority: diagnostic only.** No paper or real decision reads this value (B9).", ""]
    if chk.get("errors"):
        return "\n".join(lines + ["Reply errors (nothing is valued):"] + [f"- {k}: {'; '.join(map(str, v))}" for k, v in chk["errors"].items()]) + "\n"
    if result.get("status") == "no_call":
        return "\n".join(lines + [f"{chk.get('reason')}: {chk.get('detail')}"]) + "\n"
    prob = chk.get("prob") or {}
    lines += ["| | Bear | Base | Bull |", "|---|---|---|---|",
              "| Value per share | " + " | ".join(f"{vals[k]:,.2f}" if k in vals else "—" for k in ("bear", "base", "bull")) + " |",
              "| Probability (code) | " + " | ".join(_pct(prob[k]) if k in prob else "—" for k in ("bear", "base", "bull")) + " |", ""]
    if (result.get("base") or {}).get("route") == "financial":
        lines += [f"Cost of equity {_pct(result['cost_of_equity'])} (code). Financial route: common book equity and return on equity (O3).", ""]
    else:
        lines += [f"Cost of equity {_pct(result['cost_of_equity'])} (code). Tax {_pct(result['base']['tau'])} (code, V8).", ""]
    deps = {d["input"]: d for d in chk.get("departures") or []}
    ev = chk.get("evidence") or {}
    guid = ((result.get("inputs") or {}).get("guidance") or {})
    lines += [f"## Inputs (normalized year {chk.get('year')})", ""]
    for k, opt in (chk.get("options") or {}).items():
        line = (f"- **{k}**: {_opt(opt)}, {_num(chk['numbers'][k])} (record-neutral {_num(chk['neutral'][k])}), "
                f"{chk['directions'][k]}")
        if opt == "ytd":                                                 # F11: the period and filing of the year-to-date pair
            y = (result.get("base") or {}).get("ytd") or {}
            line += (f"; year to date {y.get('start')} to {y.get('end')} against {y.get('prior_start')} to {y.get('prior_end')}, "
                     f"{y.get('form')} {y.get('accn')} filed {y.get('filed')}")
        cited = []
        if k in deps:
            line += f"; driver {deps[k]['driver']}"
            cited = list(deps[k]["evidence"])
        if k in (chk.get("guided") or {}) and guid.get(k, {}).get("evidence") not in cited:
            cited.insert(0, guid[k]["evidence"])
        lines.append(line)
        lines += [f"  - [{i}] {ev[i]['text']}" for i in cited if i in ev]
    sc = chk.get("scenarios") or {}
    lines += ["", "## Scenarios (code: the uncertain keys' neighbours)", ""]
    for k, s in (sc.get("keys") or {}).items():
        lines.append(f"- {k}: Bear {_num(s['bear']) if s['bear'] is not None else 'Base'}, Bull {_num(s['bull']) if s['bull'] is not None else 'Base'}")
    lines += ["", "## Reverts and stamps", ""] + [f"- {x}" for x in chk.get("reverts") or ["none"]]
    lines += ["", "Stamps: " + "; ".join((result.get("stamps") or []) + (chk.get("stamps") or []))]
    if chk.get("annotations"):
        lines += ["", "Annotations: " + "; ".join(chk["annotations"])]
    rn = (chk.get("diagnostics") or {}).get("record_neutral") or {}
    lines += ["", f"Record-neutral value {rn['value']:,.2f} ({rn.get('inputs')})." if rn.get("value") is not None
              else "Record-neutral value unavailable."]
    lines += ["", "## Unknowns (the model's text, unedited)", ""] + [f"- {u}" for u in (result.get("inputs") or {}).get("unknowns") or []]
    return "\n".join(lines) + "\n"
