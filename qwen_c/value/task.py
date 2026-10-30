"""task.py - what the model is told for valuation_inputs (SPEC_m3q §2; WO_Q5 §1).

The system message is qwen_c.tasks.SYSTEM, byte-identical (its SCOPE line stands: the model states forecast inputs and never a value,
a price or an action; code computes the value). The task is NOT in tasks.TASKS, so the seeds and texts of the formation tasks do not
move. The user message is the packet rendered as tasks.render_packet does, the filed record items [Y...], the code-measured base [V0],
then this instruction.

Changing any text here changes what the model is told: bump VALUATION_PROMPT_VERSION and re-pin the hash in tests/test_value_task.py.
"""
import json

from qwen_c import tasks

VALUATION_PROMPT_VERSION = "m3q.prompt.v5"   # v5 2026-10-30 (smoke 2): inner quotation marks; keep reasons short   # v4 2026-10-30 (smoke 1): the figures rule for reasons; [V0] is citable   # v3 2026-10-30 (CROSS_CHECK_Q2 N8): [V0] names the D&A rule the desk uses   # v2 2026-10-30 (CROSS_CHECK_Q 26, operator decision C5 default): price-blind [S0];
#                                              reasons must quote; scenario inputs need their own reasons; capex_path (O7)
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
 "base": {"rev_growth": [0.05, 0.04], "op_margin": [0.150, 0.152],
          "normalized": {"year": 4, "baseline": "median", "delta_pts": 0.5, "rev_growth": 0.04},
          "transition": "linear", "transition_year": null,
          "fade_years": 10, "long_run_op_margin": 0.150, "terminal_ronic": 0.15, "terminal_g": 0.03,
          "margin_source": "record", "capex_path": null, "investment_path": null},
 "bear": {"op_margin": [0.13, 0.13]},
 "bull": {"op_margin": [0.16, 0.16]},
 "prob": {"bear": 0.25, "base": 0.5, "bull": 0.25},
 "reasons": [{"input": "base.op_margin", "claim": "one short statement", "fact_ids": ["Y2025-12-31"],
              "quotes": ["an exact extract from a cited item"], "numbers": ["each figure in the claim, as printed"],
              "confidence_basis": "stated in the cited item, or inferred, and from what"}],
 "unknowns": ["what the evidence cannot answer"]}
```"""

INSTRUCTION = (
    "TASK valuation_inputs. State the forecast inputs from which code will compute the company's value. You do not compute a value, a "
    "price or a recommendation; you choose each input and give the evidence for it.\n"
    "INPUTS. rev_growth and op_margin are years 1 and 2: revenue growth as a fraction, and the operating margin on the filed basis "
    "(operating income over revenue, as the [Y] items print it). normalized is the year (3, 4 or 5) by which the margin reaches a "
    "normalized level: its baseline is one statistic of the filed record in [V0] (min, p25, median, p75, max or last), delta_pts is "
    "percentage points added to it (0 means the baseline itself), and rev_growth is that year's revenue growth. transition is linear, "
    "step_at_year or hold_then_linear (the last two name transition_year, 3 up to the normalized year). fade_years is how many years "
    "after year 5 growth takes to reach terminal_g and the margin to reach long_run_op_margin. terminal_ronic is the return on new "
    "capital in the long run (a fraction, or \"unlimited\"). terminal_g must be below the cost of equity in [V0]. margin_source says "
    "where a margin change comes from: record (the filed record), pricing_or_mix, investment_in_explicit_years, investment_after_year5 "
    "or decline. investment_after_year5 needs investment_path: one entry per year from year 6, each with capex_over_revenue, "
    "revenue_growth and op_margin.\n"
    "SCENARIOS. bear and bull list only the inputs that differ from base. A bear input is not above base and a bull input not below "
    "it, unless a reason for that scenario input explains why. prob gives the three probabilities, summing to 1.\n"
    "CAPEX. capex_path is null, or the explicit years' capital expenditure as a fraction of revenue when the evidence states a plan: "
    "five values for years 1-5, or {\"year5\": x} for a year-5 level; margin_source investment_in_explicit_years needs it.\n"
    "REASONS. Every base input needs at least one reason whose \"input\" names it, for example \"base.normalized\"; every scenario "
    "input needs its own, for example \"bear.op_margin\". A reason is a claim under the rules above, about the input it names, with "
    "at least one exact quote; one reason serves one input. In a reason write only figures a cited item prints, and the input's own "
    "value; never a figure you computed (a growth rate, margin or ratio the items do not print). [V0] may be cited. Inside a JSON "
    "string write any quotation mark the source text prints as a single quote ('); a reason is one or two sentences. A margin outside the filed "
    "record's minimum and maximum needs a reason that quotes filed statements or filing sections of at least two different fiscal "
    "years; the [Y] record items alone cannot support it. A margin "
    "reason must cite at least one [Y], statement or filing section; an adjusted or company-defined figure may support it but not "
    "alone. When the evidence cannot support an input, choose the input the filed record supports and say so in \"unknowns\".\n"
    "Reply in this shape:\n" + _SHAPE)


def base_item(b, bar, r, coe_prov):
    """[V0] as a citable evidence item (kind code_base: it never carries V3's span or V4's basis)."""
    return {"fact_id": "V0", "kind": "code_base", "period": b["fy0"], "text": render_base(b, bar, r, coe_prov)}


def render_base(b, bar, r, coe_prov):
    """[V0]: the code-measured base the inputs are chosen against."""
    lines = [f"[V0] Measured by code from the filings (not a forecast). Base fiscal year ended {b['fy0']}.",
             f"Filed operating margin record: min {bar['min']:.4f}, p25 {bar['p25']:.4f}, median {bar['median']:.4f}, "
             f"p75 {bar['p75']:.4f}, max {bar['max']:.4f}, last {bar['last']:.4f}.",
             f"Base-year revenue {b['R0']:,.0f}; tax rate {b['tau']:.4f}; return on opening capital {b['ronic0']:.4f}; "
             f"capital expenditure {b['c_ratio']:.4f} and depreciation {b['d_ratio']:.4f} of revenue (pooled); the desk depreciates by "
             f"the {b.get('da_rule', 'pooled')} rule" + (" (filed plant ages)" if b.get('da_rule') == "vintages" else "") + ".",
             f"Cost of equity {r:.4f} (risk-free {coe_prov['rf']:.4f}, long-run growth anchor {coe_prov['g_anchor']:.4f}, "
             f"loading {coe_prov['loading_adjusted']:.3f}, equity premium {coe_prov['closure_erp']:.4f})."]
    return "\n".join(lines)


def user_message(packet, record, b, bar, r, coe_prov):
    recs = "\n\n".join(f"[{i['fact_id']}] {i['text']}" for i in record)
    return "\n\n".join([tasks.render_packet(mask_price(packet)), recs, render_base(b, bar, r, coe_prov), INSTRUCTION])


def compact_failures(failures):
    """One line per failing input: its first failure (smoke 1: the full list made the repair turn run out of output)."""
    if isinstance(failures, dict):
        return "\n".join(f"- {k}: {str(v[0])[:200]}" for k, v in failures.items())
    return "\n".join(f"- {str(f)[:200]}" for f in failures)


def messages(packet, record, b, bar, r, coe_prov, retry=None):
    """[system, user] (+ the repair turn: the previous reply and the failures to fix)."""
    msgs = [{"role": "system", "content": tasks.SYSTEM}, {"role": "user", "content": user_message(packet, record, b, bar, r, coe_prov)}]
    if retry:
        prev, failures = retry
        msgs += [{"role": "assistant", "content": prev},
                 {"role": "user", "content": "These inputs did not pass the code checks. Reply again with the whole JSON, every input "
                                             "supported; keep the inputs that passed:\n" + compact_failures(failures)}]
    return msgs
