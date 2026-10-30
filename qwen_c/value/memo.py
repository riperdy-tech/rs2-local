"""memo.py - the valuation memo (SPEC_m3q §2, V10): every number and label is code's; the only prose is the model's own reasons that
passed the contract, each printed under the input it explains. A reason that did not pass is not printed; the input's failures are.
The memo carries the authority line: diagnostic only (B9).
"""
from qwen_c import contract

MEMO_VERSION = "m3q.memo.v3"   # v3 2026-10-31 Q3b N3: diagnostics printed;   # v2 2026-10-30 WO_Q6: the financial route's inputs table


def _pct(x):
    return "unlimited" if x == "unlimited" or x == float("inf") else f"{100 * float(x):.1f}%"


def render(result, reasons_by_input):
    """Markdown memo of one run.py result. `reasons_by_input` is checks.reasons_by_input on the same output."""
    if result.get("status") in ("no_call",):
        return f"# {result['ticker']} at {result['T']}: no call\n\n{result.get('reason')}: {result.get('detail')}\n"
    inp, chk = result.get("inputs") or {}, result.get("checks") or {}
    base, vals = inp.get("base") or {}, result.get("values") or {}
    lines = [f"# {result['ticker']} at {result['T']}: {result['status']}", "",
             "**Authority: diagnostic only.** No paper or real decision reads this value (B9).", "",
             "| | Bear | Base | Bull |", "|---|---|---|---|",
             "| Value per share | " + " | ".join(f"{vals[k]:,.2f}" if k in vals else "—" for k in ("bear", "base", "bull")) + " |",
             "| Probability | " + " | ".join(_pct((inp.get("prob") or {}).get(k, 0)) for k in ("bear", "base", "bull")) + " |", "",
             *(_inputs_fin(result, base) if (result.get("base") or {}).get("route") == "financial" else _inputs_op(result, base)),
             "Labels (code, V6): " + ", ".join(f"{k} {v}" for k, v in (chk.get("labels") or {}).items() if not k.endswith("_submitted")), ""]
    for (scen, key), rs in sorted(reasons_by_input.items()):
        refused = set(chk.get("refused_reasons") or [])
        ok = [x for x in rs if x.get("ok", x["support"] == contract.SUPPORTED) and x.get("i") not in refused]
        lines.append(f"**{scen}.{key}**")
        for x in ok:
            lines.append(f"- {x['reason']['claim']} [{', '.join(x['reason']['fact_ids'])}]")
        for why in (chk.get("unsupported") or {}).get(f"{scen}.{key}", []):
            lines.append(f"- *unsupported:* {why}")
        lines.append("")
    if chk.get("annotations"):
        lines += ["Annotations: " + "; ".join(chk["annotations"]), ""]
    d = chk.get("diagnostics")
    if d:                                                                 # CROSS_CHECK_Q3b N3: the implied P/B and the TV share
        lines += [f"Implied P/B {d['implied_pb']:.2f} (a perpetuity at the record's median ROE: {d['pb_record_median_perpetuity']:.2f}); "
                  f"terminal value {_pct(d['tv_share'] or 0)} of the value.", ""]
    return "\n".join(lines)


def _inputs_op(result, base):
    return [f"Cost of equity {_pct(result['cost_of_equity'])} (code). Tax {_pct(result['base']['tau'])} (code, V8).", "",
            "| Input (Base) | Value |", "|---|---|",
            f"| Revenue growth, years 1-2 | {', '.join(_pct(g) for g in base.get('rev_growth', []))} |",
            f"| Operating margin, years 1-2 | {', '.join(_pct(m) for m in base.get('op_margin', []))} |",
            f"| Normalized margin (year {base.get('normalized', {}).get('year')}) | {base.get('normalized', {}).get('baseline')} "
            f"{base.get('normalized', {}).get('delta_pts', 0):+.1f} pts |",
            f"| Long-run operating margin | {_pct(base.get('long_run_op_margin', 0))} |",
            f"| Fade years | {base.get('fade_years')} |",
            f"| Terminal return on new capital | {_pct(base.get('terminal_ronic', 0))} |",
            f"| Terminal growth | {_pct(base.get('terminal_g', 0))} |",
            f"| Margin source | {base.get('margin_source')} |", ""]


def _inputs_fin(result, base):
    """WO_Q6: the financial route's inputs (book growth and ROE; no tax line: O3 values net income)."""
    return [f"Cost of equity {_pct(result['cost_of_equity'])} (code). Financial route: book equity and return on equity (O3).", "",
            "| Input (Base) | Value |", "|---|---|",
            f"| Book equity growth, years 1-2 | {', '.join(_pct(g) for g in base.get('book_growth', []))} |",
            f"| Return on equity, years 1-2 | {', '.join(_pct(m) for m in base.get('roe', []))} |",
            f"| Normalized return on equity (year {base.get('normalized', {}).get('year')}) | {base.get('normalized', {}).get('baseline')} "
            f"{base.get('normalized', {}).get('delta_pts', 0):+.1f} pts |",
            f"| Long-run return on equity | {_pct(base.get('long_run_roe', 0))} |",
            f"| Fade years | {base.get('fade_years')} |",
            f"| Terminal growth | {_pct(base.get('terminal_g', 0))} |", ""]
