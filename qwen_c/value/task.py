"""task.py - what the model is told for valuation_inputs (SPEC_m3q §2; WO_Q5 §1; F_SPEC_valuation_menu §1-§2, prompt v8).

The system message is qwen_c.tasks.SYSTEM, byte-identical (its SCOPE line stands: the model states forecast inputs and never a value,
a price or an action; code computes the value). The task is NOT in tasks.TASKS, so the seeds and texts of the formation tasks do not
move. The user message is the packet rendered as tasks.render_packet does, with a <17> marker (its ID P4.s17 under the item [P4]) before each sentence of a prose
item (sentences.py), the filed record items [Y...], the code-measured base and its MENU [V0], then this instruction.

Changing any text here changes what the model is told: bump VALUATION_PROMPT_VERSION and re-pin the hash in tests/test_value_task.py.
"""
from qwen_c import tasks
from qwen_c.value import menu, sentences

VALUATION_PROMPT_VERSION = "m3q.prompt.v12"   # v12 2026-11-10 margin persistence: the margin record line ends with persist; the operating anchors list persist first (menu v6)   # v11 2026-11-05 J2 revision 1: "Year 1 options keep reported quarters." (menu v4)   # v10 2026-11-03 F_SPEC_valuation_menu v1.3 (F11): [V0] year 1's own MENU lines with ytd first where measured, and the year-to-date line   # v9 2026-11-03 F8: the short sentence marker <17>   # v8 2026-11-03 F_SPEC_valuation_menu: menus, sentence IDs, typed departures   # v7 2026-10-31 CROSS_CHECK_Q3e 2: forecast years in words   # v6..v2 2026-10-30/31 (see git)
PRICE_LINES = ("price:", "marketCap:", "price as-of")
NL = "\n"


def mask_price(packet):
    """A copy of the packet whose [S0] screener row has no price, market cap or price as-of line (rev 26's valuation stage was price-blind).
    Stated limit: a share price printed inside a filing's own text is not masked."""
    out = dict(packet)
    out["evidence"] = [dict(e, text=NL.join(l for l in (e.get("text") or "").split(NL) if not l.startswith(PRICE_LINES)))
                       if e.get("kind") == "screener_row" else e for e in packet.get("evidence") or []]
    return out


_SHAPE = """```json
{"task": "valuation_inputs",
 "base": {"rev_growth": {"y1": "guidance", "y2": "anchor"}, "op_margin": {"y1": "persist", "y2": "persist"},
          "normalized": {"year": 4, "anchor": "persist", "step": 0, "rev_growth": "anchor"}, "fade_years": 10,
          "long_run_op_margin": {"anchor": "normalized", "step": 0}, "terminal_ronic": "no_growth_value", "terminal_g": "anchor",
          "capex": "pooled"},
 "guidance": {"rev_growth.y1": {"evidence": "P4.s17", "metric": "revenue_growth", "sign": "as_printed", "ordinal": 1}},
 "departures": [{"input": "rev_growth.y1", "driver": "guidance", "evidence": ["P4.s17"]}],
 "uncertain": ["rev_growth.y1"],
 "unknowns": ["what the evidence cannot answer"]}
```"""

_RULES = (
    "Each input is an option of its MENU line in [V0]; code uses the number printed beside it. Never choose an option printed \"not "
    "available\". The first option of a line is the record-neutral choice (normalized: year 3, {NEUTRAL}step 0). An input whose number "
    "differs from the neutral number is a departure (a long run anchored on normalized departs with it). Each departure needs one "
    "entry: its departure key, a driver and 1 to 4 evidence IDs, at least one not V0. Cite a sentence of a text item by its item and "
    "marker (<17> in item [P4] is P4.s17), a statement, a [Y] item or [V0] by its ID. Code reverts a departure its evidence does not support: without evidence, "
    "stay neutral.\n"
    "The option guidance takes its number from one cited sentence of a filing or 8-K dated in or after the base fiscal year: under "
    "\"guidance\", keyed by the input, give evidence, metric, sign (as_printed, or negative for a stated decline) and ordinal (the n-th figure in the metric's unit, years not "
    "counted; a range counts as its first figure).\n"
    "uncertain names 1 to 3 departure keys; code builds Bear and Bull from their neighbouring options. unknowns is free text.\n")
# v12 (menu v6): the operating text no longer names the neutral anchor (persist is listed first on its MENU line, and the budget
# allows no more); the financial text keeps "median, ", byte-identical to fin.v7
_YEAR1 = "Year 1 options keep reported quarters.\n"    # v11: operating only (the financial route has no ytd); the instruction's budget allows no more

INSTRUCTION = ("TASK valuation_inputs. Choose the inputs from which code values the company; you never state a number, a value or a "
               "price. " + _RULES.replace("{NEUTRAL}", "") + _YEAR1 + "Reply in this shape:\n" + _SHAPE)


# WO_Q6: the financial route (banks, insurers; O3 retained equity). Its own text and version. Changing any text here: bump
# VALUATION_PROMPT_FIN_VERSION and re-pin its hash in tests/test_value_fin.py.
VALUATION_PROMPT_FIN_VERSION = "m3q.prompt.fin.v7"   # v7 2026-11-03 F8: the short sentence marker <17>   # v6 2026-11-03 F_SPEC_valuation_menu §2.3   # v5 2026-10-31 CROSS_CHECK_Q3e 2   # v4..v2 2026-10-30/31 (see git)

_SHAPE_FIN = """```json
{"task": "valuation_inputs_financial",
 "base": {"book_growth": {"y1": "neutral", "y2": "neutral"}, "roe": {"y1": "last", "y2": "median"},
          "normalized": {"year": 3, "anchor": "median", "step": 0, "book_growth": "neutral"}, "fade_years": 10,
          "long_run_roe": {"anchor": "normalized", "step": 0}, "terminal_g": "neutral"},
 "guidance": {},
 "departures": [{"input": "roe.y1", "driver": "record_persistence", "evidence": ["Y2025-12-31", "P2.s4"]}],
 "uncertain": ["normalized.roe", "long_run_roe"],
 "unknowns": ["what the evidence cannot answer"]}
```"""

INSTRUCTION_FIN = ("TASK valuation_inputs_financial. The company is a financial: code values it from its common book equity (preferred "
                   "stock out of book, its dividends out of income) and the return it earns on it. Choose the inputs from which code values "
                   "it; you never state a number, a value or a price. " + _RULES.replace("{NEUTRAL}", "median, ") + "Reply in this shape:\n" + _SHAPE_FIN)


def _menu_lines(b, bar, r, coe_prov, route):
    """The MENU of [V0]: every offered option with the number code resolves it to; the record-neutral option first."""
    m = menu.menus(dict(b, g_anchor=b.get("g_anchor", coe_prov["g_anchor"])), bar, r, route)

    def line(name, d, extra=""):
        return f"{name}: " + "; ".join(f"{k} " + ("not available" if v is None else f"{(v[0] if isinstance(v, tuple) else v):.4f}")
                                       for k, v in d.items()) + extra
    keys = list(menu.KEYS[route])
    g, mg, lr = keys[0].split(".")[0], keys[2].split(".")[0], keys[6]
    if route == "operating":                                             # F11: year 1 has its own line, with ytd
        growth = [line(f"{g}.y1", m["growth_y1"], "; guidance"), line(f"{g}.y2, {keys[5]}", m["growth"], "; guidance"),
                  line(f"{mg}.y1", m["margin_y1"], "; guidance"), line(f"{mg}.y2", m["margin"], "; guidance")]
    else:
        growth = [line(f"{g}.y1, {g}.y2, {keys[5]}", m["growth"], "; guidance"), line(f"{mg}.y1, {mg}.y2", m["margin"], "; guidance")]
    out = ["MENU (option and the number code uses; the first option is the record-neutral one).", *growth,
           line(f"normalized.anchor and {lr}.anchor", m["anchor"], f"; {lr}.anchor also normalized (the normalized number)"),
           f"normalized.step and {lr}.step (points added to the anchor): 0, " + ", ".join(f"{s:g}" for s in menu.STEPS if s),
           "normalized.year: 3, 4, 5", "fade_years (years from year 6 to the long run): 10, 5, 15, 20"]
    if route == "operating":
        out.append(line("terminal_ronic (return on new capital in the long run)", m["ronic"]))
    out.append(line("terminal_g", m["terminal_g"]))
    if route == "operating":
        out.append(line("capex (capital expenditure over revenue, years 1-5)", m["capex"], "; guidance (a year-1 level, then to pooled by year 5)"))
    out += [f"Departure keys: {', '.join(keys)}.", f"Drivers: {', '.join(menu.DRIVERS)}.",
            "Guidance metrics: " + ("revenue_level or revenue_growth (growth), op_margin, capex_level." if route == "operating"
                                    else "book_growth, roe.")]
    return out


def _growth_line(rec, what):
    if len(rec) < menu.MIN_GROWTH_YEARS:
        return f"Filed yearly growth of {what}: fewer than {menu.MIN_GROWTH_YEARS} consecutive fiscal years."
    return f"Filed yearly growth of {what} (consecutive fiscal years): " + ", ".join(f"{e} {g:.4f}" for e, g in sorted(rec.items())) + "."


def render_base_fin(b, bar, r, coe_prov):
    """[V0] for the financial route: the filed return-on-equity record, book equity, the cost of equity and the MENU."""
    lines = [f"[V0] Measured by code from the filings (not a forecast). Base fiscal year ended {b['fy0']}.",
             f"Filed return-on-equity record (income to common over opening common equity): min {bar['min']:.4f}, p25 {bar['p25']:.4f}, "
             f"median {bar['median']:.4f}, p75 {bar['p75']:.4f}, max {bar['max']:.4f}, last {bar['last']:.4f}.",
             f"Common book equity at the end of the base year {b['R1']:,.0f}; income to common in the base year {b['e0']:,.0f}.",
             _growth_line(b["record"].get("book_growth") or {}, "book equity"),
             f"Cost of equity {r:.4f} (risk-free {coe_prov['rf']:.4f}, long-run growth anchor {coe_prov['g_anchor']:.4f}, "
             f"loading {coe_prov['loading_adjusted']:.3f}, equity premium {coe_prov['closure_erp']:.4f})."]
    return "\n".join(lines + _menu_lines(b, bar, r, coe_prov, "financial"))


def render_base(b, bar, r, coe_prov):
    """[V0]: the code-measured base the inputs are chosen against, and the MENU."""
    lines = [f"[V0] Measured by code from the filings (not a forecast). Base fiscal year ended {b['fy0']}.",
             f"Filed operating margin record: min {bar['min']:.4f}, p25 {bar['p25']:.4f}, median {bar['median']:.4f}, "
             f"p75 {bar['p75']:.4f}, max {bar['max']:.4f}, last {bar['last']:.4f}; persist {bar['persist']:.4f} (the median plus half "
             f"the gap from the median to the last year: about half such a gap has remained 2-5 years later in filed records).",
             _growth_line(b["record"].get("rev_growth") or {}, "revenue"),
             f"Base-year revenue {b['R0']:,.0f}; tax rate {b['tau']:.4f}; return on opening capital {b['ronic0']:.4f}; "
             f"capital expenditure {b['c_ratio']:.4f} and depreciation {b['d_ratio']:.4f} of revenue (pooled); the desk depreciates by "
             f"the {b.get('da_rule', 'pooled')} rule" + (" (filed plant ages)" if b.get('da_rule') == "vintages" else "") + ".",
             f"Cost of equity {r:.4f} (risk-free {coe_prov['rf']:.4f}, long-run growth anchor {coe_prov['g_anchor']:.4f}, "
             f"loading {coe_prov['loading_adjusted']:.3f}, equity premium {coe_prov['closure_erp']:.4f}).",
             ytd_line(b.get("ytd"))]
    return "\n".join(lines + _menu_lines(b, bar, r, coe_prov, "operating"))


def ytd_line(y):
    """F11: the year-to-date pair behind year 1's ytd option, or why there is none."""
    if not y or y.get("rev_growth") is None:
        return f"Year 1 to date: not available ({(y or {}).get('absent') or 'not measured'})."
    s = (f"Year 1 to date ({y['form']} {y['accn']}, filed {y['filed']}): revenue {y['revenue']:,.0f} from {y['start']} to {y['end']} "
         f"against {y['revenue_prior']:,.0f} from {y['prior_start']} to {y['prior_end']}, growth {y['rev_growth']:.4f}")
    if y.get("operating_income") is None:
        return s + f"; operating margin not available ({y.get('op_margin_absent')})."
    return s + f"; operating income {y['operating_income']:,.0f}, margin {y['operating_income'] / y['revenue']:.4f}."


def base_item(b, bar, r, coe_prov):
    """[V0] as a citable evidence item (kind code_base: it never carries V3's span or V4's basis)."""
    render = render_base_fin if b.get("route") == "financial" else render_base
    return {"fact_id": "V0", "kind": "code_base", "period": b["fy0"], "text": render(b, bar, r, coe_prov)}


def evidence_ids(packet, record, b, bar, r, coe_prov):
    """sentences.index over the packet's items, the [Y] record items and [V0]: every ID the reply may cite."""
    return sentences.index(list(packet.get("evidence") or []) + list(record) + [base_item(b, bar, r, coe_prov)])


def user_message(packet, record, b, bar, r, coe_prov):
    recs = "\n\n".join(f"[{i['fact_id']}] {i['text']}" for i in record)
    head = tasks.render_packet(sentences.marked_packet(mask_price(packet)))
    if b.get("route") == "financial":                                     # WO_Q6
        return "\n\n".join([head, recs, render_base_fin(b, bar, r, coe_prov), INSTRUCTION_FIN])
    return "\n\n".join([head, recs, render_base(b, bar, r, coe_prov), INSTRUCTION])


def compact_failures(failures):
    """One line per failing key with each of its reply errors, cut short (smoke 1: the full list made the repair turn run out of
    output; Q3e-4: only the first hid a failure)."""
    if isinstance(failures, dict):
        return "\n".join(f"- {k}: " + " | ".join(str(x)[:200] for x in v[:4]) for k, v in failures.items())
    return "\n".join(f"- {str(f)[:200]}" for f in failures)


def messages(packet, record, b, bar, r, coe_prov, retry=None):
    """[system, user] (+ the repair turn: the previous reply and the reply errors to fix)."""
    msgs = [{"role": "system", "content": tasks.SYSTEM}, {"role": "user", "content": user_message(packet, record, b, bar, r, coe_prov)}]
    if retry:
        prev, failures = retry
        msgs += [{"role": "assistant", "content": prev},
                 {"role": "user", "content": "These inputs did not pass the code checks. Reply again with the whole JSON; keep the "
                                             "inputs that passed:\n" + compact_failures(failures)}]
    return msgs
