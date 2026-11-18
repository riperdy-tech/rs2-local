"""decided_value.py - WO_NC7: the cloud read decides the valuation inputs; code pins the facts, checks the reply and values it (operator 2026-11-18).

Asked once per run, two runs per name (the seeds 1000 and 3000 of the menu method, kept as the run labels), only by the cloud arms
(gemini_ondemand.analyze with VALUE_METHOD "decided"), for the operating and commodity routes. Nothing under qwen_c/ changes: Qwen's prompts
and the menu method are not touched.

    code pins the facts   vrun.prepare: tax, leverage, working capital, depreciation rule, shares, cash, cost of equity (unchanged), and
                          for the prompt only the revenue, growth and operating margin of every filed year
    the read decides      one JSON object: the situation, 7 inputs, a low and a high for 3 of them (the values with about a 1 in 4 chance
                          of being undershot and overshot), a reason with exact quotes for every input, the largest risks, a confidence
    code checks           shape and counts, margins inside (-1, 1), long-run growth below the cost of equity, the long-run return above 0 and
                          above long-run growth, low <= input <= high, a verified quote for every input. A failure gets ONE repair turn
                          naming what was wrong; a second failure is `decision_invalid`, no value. Code never changes a number the read gave.
    code values           desk.value_operating on the pinned base with the read's numbers: base; bear = every ranged input at its low, bull =
                          every ranged input at its high (a growth bound moves all five yearly growths by the same amount, so that the
                          year-3 growth is the bound); the weights 25/50/25 are checks.PROB
    flags, not clamps     a margin or growth outside the company's own filed record, a long-run return above the base year's, a base year
                          judged not representative, a low confidence, quotes verified n of m
    reference number      the value at the code's old defaults (the record-neutral menu value), code only, kept beside the new one

WO_NC9a (phase 2, decided.v2): the same call also states, each null where the filings do not say, the cash that is not free (restricted, held for
customers, a minimum the company states) and the non-operating one-offs of the base year, each with exact quotes whose digits code checks (the rule
of interest_from_filing.py); and two situation flags (tax rate and debt level representative). The valuation then uses a COPY of the base:
excess_cash less that cash, the interest earned on it put back into the earnings base, and the one-offs taken out of the held constant k0; bear
and bull use the same copy; the result keeps the pinned base and `decided.adjustments`. Nothing under qwen_c/ changes.
"""
import json
import math
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from qwen_c import contract, runner, tasks  # noqa: E402
from qwen_c.value import checks, coe, desk, facts, inputs, menu, run as vrun, task as vtask  # noqa: E402
import interest_from_filing as IFF  # noqa: E402                    # WO_NC9a: the digit-in-quote rule and the scales

DECIDED_VERSION = "decided.v2 2026-11-19 WO_NC9a"          # v2: cash not free, base-year one-offs, tax and debt flags (the method label stays decided.v1)
METHOD = "decided.v1"
FAMILIES = vrun.ROUTED                    # the financial route keeps the menu until it is tested the same way
VARIANTS = {}                             # WO_NC9c: family -> the module that registered itself here (decided_real_estate): record text, task text, extra checks
ALL_YEARS = 100                           # facts.build's `years`: every filed fiscal year the company facts hold, for the prompt's record only

INPUT_KEYS = ("rev_growth", "op_margin", "long_run_op_margin", "terminal_growth", "fade_years", "return_on_new_investment_long_run", "capex_to_revenue")
SCALAR_KEYS = INPUT_KEYS[2:]
RANGE_KEYS = ("long_run_op_margin", "rev_growth_y3", "terminal_growth")
TRIPLE = ("yes", "no", "unclear")
CONFIDENCE = ("low", "medium", "high")
SIGNS = ("charge", "gain")                # WO_NC9a: a one-off of the base year
SITUATION_FLAGS = ("tax_rate_representative", "debt_level_representative")      # WO_NC9a: flags only, no number moves
# WO_UV2: stamps of the base that the run's flags also carry, so a reader of the site sees them: no EPS to prove the share count, and each reading made where a figure was not filed
SURFACED_STAMPS = ("shares_unreconciled_no_eps", "working_capital_unclassified_balance_sheet", "pretax_derived_from_net_income_nci_tax", "nci_income_includes_redeemable_nci",
                   "debt_from_senior_notes_tags_parts_reconciled", "oi_interest_from_cash_interest_paid", "shares_from_partnership_units_reconciled_with_per_unit_eps")
SURFACED_PREFIXES = ("preferred_dividends_taken_as_0_eps_times_shares_reconciles:", "preferred_balance_not_filed_taken_as_0:")
FADE_YEARS = (1, 25)                      # the range the prompt states for fade_years (the reference test's own)

SYSTEM = ("You are an equity analyst setting the inputs of a discounted cash flow valuation for one company, from its filings. Decide each "
          "input for THIS company. Do not default to a generic number: say what this company's situation is and what follows from it. "
          "Use only the evidence in this conversation; quote it exactly. Where the evidence does not support a view, say so and give your "
          "best estimate with a wide range.")

BASE_RATES = ("BASE RATES (measured on filed history of many companies; information, not instructions)\n"
              "Ordinary companies: about half of the gap between the latest margin and the 5-year median is still there 2 to 10 years later. "
              "Cyclical/commodity companies: a margin ABOVE the company's own long-run median keeps roughly 40 to 60% of that gap 5 to 10 "
              "years later (wide uncertainty); a margin BELOW it has returned to the median by about year 2.")

TASK = """TASK. Decide the valuation inputs for this company and return ONE JSON object and nothing else (no text before or after it).
Use fractions, not percents: 0.05 means 5%, 0.5059 means 50.59%. Operating margin is on the same GAAP basis as the operating margin in the FILED RECORD (operating income / revenue). Year 1 is the fiscal year after the base year in the FILED RECORD; years 1 to 5 are five consecutive fiscal years.
What each input means: rev_growth = revenue growth of years 1..5 (list of 5); op_margin = operating margin of years 1..5 (list of 5); long_run_op_margin = the operating margin the company fades to over fade_years after year 5 and keeps for ever; terminal_growth = revenue growth for ever after that fade (growth fades linearly from year 5's to this); fade_years = the number of years (a whole number, 1 to 25) of that fade; return_on_new_investment_long_run = the after-tax return on tangible capital earned on new investment in the long run (same basis as the return on tangible capital in the FILED RECORD, which also prints the return at which growth adds no value); capex_to_revenue = capital expenditure / revenue, held in years 1..5.
Ranges: for long_run_op_margin, rev_growth_y3 (the growth of year 3; code moves all five yearly growths together by the difference between your bound and your year-3 growth) and terminal_growth, give [low, high]: the values you judge have about a 1 in 4 chance of being undershot (low) and about a 1 in 4 chance of being overshot (high). Your own input lies between them.
Two optional items for the earnings base; each is null where the filings do not say, and you do not estimate either. cash_not_free: cash and short-term investments the company cannot spend freely (restricted cash, cash held for customers, a minimum operating cash the company itself states); code counts all other cash as excess and adds it to the value at face. value = the amount as printed in the filing, digits only; scale = the unit the filing states for that line. base_year_one_offs: a list of NON-OPERATING items of the base year that will not recur, which sit between operating income and pretax income (for example a gain or loss on an investment, a debt extinguishment cost); code holds the base year's non-operating items for ever and removes these from that. sign = charge or gain; value = the pre-tax amount as printed. Do not list operating items here: your margins already set how they bear on operating income. Each item needs an exact quote that contains its number. Two further judgements, flags only (no number moves): tax_rate_representative = whether the tax rate in the FILED RECORD is one the company can keep paying; debt_level_representative = whether the total debt in the FILED RECORD is the level the company will keep relative to its size; each is yes, no or unclear with one sentence.
Every reason needs at least one exact quote copied character for character from the evidence item it cites (id = the id in brackets at the head of the item, e.g. F1 or P2; the FILED RECORD has id REC and any reason may cite it). Do not quote the PRIOR READ: it is not evidence. biggest_risks: the largest risks to your inputs; bear_value = the number that input would have if the risk happened.
Schema:
{"situation": {"cyclical": "yes|no|unclear", "margin_position": "<plain words: why the margin is where it is>", "base_year_representative": "yes|no|unclear", "why": "<2-4 sentences>",
  "tax_rate_representative": {"answer": "yes|no|unclear", "why": "<one sentence>"}, "debt_level_representative": {"answer": "yes|no|unclear", "why": "<one sentence>"}},
 "inputs": {"rev_growth": [y1,y2,y3,y4,y5], "op_margin": [y1,y2,y3,y4,y5], "long_run_op_margin": x, "terminal_growth": x, "fade_years": n, "return_on_new_investment_long_run": x, "capex_to_revenue": x},
 "ranges": {"long_run_op_margin": [low, high], "rev_growth_y3": [low, high], "terminal_growth": [low, high]},
 "cash_not_free": null or {"value": <as printed>, "scale": "units|thousands|millions|billions", "what": "<restricted cash, cash held for customers, ...>", "quotes": [{"id": "<evidence id>", "quote": "<exact text>"}]},
 "base_year_one_offs": null or [{"value": <as printed>, "scale": "units|thousands|millions|billions", "sign": "charge|gain", "what": "<the item>", "quotes": [{"id": "<evidence id>", "quote": "<exact text>"}]}],
 "reasons": {"<each key of inputs>": {"why": "<1-3 sentences tied to this company>", "quotes": [{"id": "<evidence id>", "quote": "<exact text>"}]}},
 "biggest_risks": [{"risk": "...", "input_hit": "<key of inputs>", "bear_value": x}],
 "confidence": "low|medium|high"}"""


# ---------------------------------------------------------------- the prompt
def _money(v):
    return f"${v / 1e6:,.1f} million"


def _by_end(f, concept):
    return {v["end"]: v["value"] for v in (f.get(concept) or {}).get("values", [])}


def _consecutive(prev_end, end):
    """Two fiscal-year ends one year apart (the bounds of inputs._year_chain)."""
    return 350 <= (date.fromisoformat(end) - date.fromisoformat(prev_end)).days <= 380


def _f4(x):
    return "n/a" if x is None else f"{x:.4f}"


def record_text(f, f_all, b, r, prov, no_oi="no operating income being filed"):
    """(text of the item [REC], {"margins": {end: operating margin}, "growths": {end: growth}}): every filed fiscal year's revenue, growth and
    operating margin (f_all), then the pinned base (b) as the prompt shows it. Facts computed by code from the filings."""
    rev, oi = _by_end(f_all, "revenue"), _by_end(f_all, "operating_income")
    basis = "operating income / revenue"
    if not oi:                                                  # as inputs.base: no operating income filed in any year
        pt, ie = _by_end(f_all, "pretax_income"), _by_end(f_all, "interest_expense")
        oi, basis = {e: pt[e] + ie[e] for e in pt if e in ie}, f"(pretax income + interest expense) / revenue, {no_oi}"
    ends = sorted(rev)
    margins, growths = {}, {}
    lines = ["[REC] FILED RECORD (computed by code from the filings; facts). Currency: USD as filed. Fiscal years, oldest first.",
             f"fiscal year end | revenue | revenue growth vs prior fiscal year | operating margin ({basis})"]
    for i, e in enumerate(ends):
        if i and rev[ends[i - 1]] > 0 and _consecutive(ends[i - 1], e):
            growths[e] = rev[e] / rev[ends[i - 1]] - 1
        if e in oi and rev[e] > 0:
            margins[e] = oi[e] / rev[e]
        lines.append(f"{e} | {_money(rev[e])} | {_f4(growths.get(e))} | {_f4(margins.get(e))}")
    lines.append(f"Base year (the last filed fiscal year): ended {b['fy0']}; base-year revenue {_money(b['R0'])}.")
    da, rev_p, cx = _by_end(f, "da"), _by_end(f, "revenue"), b["record"]["capex_ratio"]
    lines.append("Pooled years (the last 5 fiscal years with revenue): fiscal year end | capital expenditure / revenue | depreciation and amortization as filed / revenue")
    for e in sorted(cx):
        lines.append(f"{e} | {cx[e]:.4f} | {'n/a' if e not in da else f'{da[e] / rev_p[e]:.4f}'}")
    lines.append(f"Pooled over those years: capital expenditure / revenue {b['c_ratio']:.4f}; depreciation (without amortization of acquired intangibles) / revenue {b['d_ratio']:.4f}.")
    lines.append(f"Base year: return on tangible capital {b['ronic0']:.4f}; tax rate {b['tau']:.4f}; total debt {_money(b['debt0'])}; cash counted as excess {_money(b['excess_cash'])}; "
                 f"net debt (debt less that cash) {_money(b['debt0'] - b['excess_cash'])}.")
    lines.append(f"Non-operating items that the valuation holds in dollars for ever (K_0 = base-year operating income less pretax income without the interest earned on cash and the minority share; positive = a net cost): "
                 f"{_money(b['k0'])}, of which interest on debt {_money(b['k0_interest'])}.")             # WO_NC9a: what the one-offs would be taken out of
    lines.append(f"Return on new investment at which growth adds no value (code, after the company's leverage): {menu.neutral_ronic(b, r):.4f}.")
    lines.append(f"Cost of equity r {r:.4f}; long-run nominal growth anchor g_anchor {_f4(prov.get('g_anchor'))}.")
    return "\n".join(lines), {"margins": margins, "growths": growths}


def prior_read(an):
    """(text, kept, dropped): the stored read's claims that the code's support check passed, with their mechanism where there is one."""
    out, dropped = [], 0
    for tid, t in ((an or {}).get("tasks") or {}).items():
        for c in (t or {}).get("claims") or []:
            if c.get("support") != "supported":
                dropped += 1
                continue
            out.append(f"- [{tid}] {c.get('claim')}" + (f" Mechanism: {c['mechanism']}" if c.get("mechanism") else ""))
    return ("\n".join(out) if out else "(none)"), len(out), dropped


def messages(packet, rec, prior, retry=None, task=None):
    """[system, user] (+ the repair turn: the previous reply and what was wrong). The packet is shown with its prices masked."""
    user = "\n\n".join([tasks.render_packet(vtask.mask_price(packet)), rec,
                        "PRIOR READ (another analyst's notes, unverified; not evidence, not to be quoted)\n" + prior, BASE_RATES, task or TASK])
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    if retry:
        prev, problems = retry
        msgs += [{"role": "assistant", "content": prev},
                 {"role": "user", "content": "These inputs did not pass the code checks. Reply again with the whole JSON; keep what passed:\n"
                                             + "\n".join(f"- {p}" for p in problems)}]
    return msgs


# ---------------------------------------------------------------- the checks
def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _item_shape(it, label, with_sign):
    """WO_NC9a: the form of the cash_not_free object or of one base_year_one_offs item."""
    if not isinstance(it, dict):
        return [f"{label} must be an object"]
    p, v = [], IFF._printed(it.get("value"))
    if v is None or not v.is_finite() or not v > 0:
        p.append(f"{label}.value must be a number above 0, as printed in the filing")
    if it.get("scale") not in IFF.SCALES:
        p.append(f"{label}.scale must be one of {', '.join(IFF.SCALES)}")
    if with_sign and it.get("sign") not in SIGNS:
        p.append(f"{label}.sign must be one of {', '.join(SIGNS)}")
    if not (isinstance(it.get("what"), str) and it["what"].strip()):
        p.append(f"{label}.what is missing")
    if not isinstance(it.get("quotes"), list):
        p.append(f"{label}.quotes must be a list")
    return p


def _adjustment_shape(obj):
    """WO_NC9a: both keys must be present, each null or well formed (a reply of the v1 shape, without them, is invalid)."""
    p = []
    if "cash_not_free" not in obj:
        p.append("cash_not_free is missing (null where the filings do not say)")
    elif obj["cash_not_free"] is not None:
        p += _item_shape(obj["cash_not_free"], "cash_not_free", False)
    if "base_year_one_offs" not in obj:
        p.append("base_year_one_offs is missing (null where the filings do not say)")
    elif isinstance(obj["base_year_one_offs"], list):
        p += [m for i, it in enumerate(obj["base_year_one_offs"]) for m in _item_shape(it, f"base_year_one_offs[{i}]", True)]
    elif obj["base_year_one_offs"] is not None:
        p.append("base_year_one_offs must be null or a list")
    return p


def shape_problems(obj):
    """What is wrong with the reply's form (names, types, counts), or []."""
    if not isinstance(obj, dict):
        return ["the reply is not a JSON object"]
    p = []
    sit = obj.get("situation")
    if not isinstance(sit, dict):
        p.append("situation is missing or not an object")
    else:
        p += [f"situation.{k} must be one of {', '.join(TRIPLE)}" for k in ("cyclical", "base_year_representative") if sit.get(k) not in TRIPLE]
        p += [f"situation.{k} is missing" for k in ("margin_position", "why") if not (isinstance(sit.get(k), str) and sit[k].strip())]
        for k in SITUATION_FLAGS:                                                                  # WO_NC9a
            e = sit.get(k)
            if not (isinstance(e, dict) and e.get("answer") in TRIPLE and isinstance(e.get("why"), str) and e["why"].strip()):
                p.append(f"situation.{k} must be {{answer: one of {', '.join(TRIPLE)}, why: one sentence}}")
    inp = obj.get("inputs")
    if not isinstance(inp, dict):
        p.append("inputs is missing or not an object")
    else:
        p += [f"inputs.{k} must be a list of 5 numbers" for k in ("rev_growth", "op_margin")
              if not (isinstance(inp.get(k), list) and len(inp[k]) == 5 and all(_num(x) for x in inp[k]))]
        p += [f"inputs.{k} must be a number" for k in SCALAR_KEYS if not _num(inp.get(k))]
        fy = inp.get("fade_years")
        if _num(fy) and not (float(fy).is_integer() and FADE_YEARS[0] <= fy <= FADE_YEARS[1]):
            p.append(f"inputs.fade_years must be a whole number from {FADE_YEARS[0]} to {FADE_YEARS[1]}")
    rng = obj.get("ranges")
    if not isinstance(rng, dict):
        p.append("ranges is missing or not an object")
    else:
        p += [f"ranges.{k} must be a list [low, high] of 2 numbers" for k in RANGE_KEYS
              if not (isinstance(rng.get(k), list) and len(rng[k]) == 2 and all(_num(x) for x in rng[k]))]
    why = obj.get("reasons")
    if not isinstance(why, dict):
        p.append("reasons is missing or not an object")
    else:
        for k in INPUT_KEYS:
            e = why.get(k)
            if not (isinstance(e, dict) and isinstance(e.get("why"), str) and e["why"].strip() and isinstance(e.get("quotes"), list)):
                p.append(f"reasons.{k} must be {{why: text, quotes: a list}}")
    p += _adjustment_shape(obj)
    risks = obj.get("biggest_risks")
    if not (isinstance(risks, list) and all(isinstance(x, dict) and isinstance(x.get("risk"), str) and x["risk"].strip() and x.get("input_hit") in INPUT_KEYS for x in risks)):
        p.append("biggest_risks must be a list of {risk: text, input_hit: a key of inputs, bear_value: a number}")
    if obj.get("confidence") not in CONFIDENCE:
        p.append(f"confidence must be one of {', '.join(CONFIDENCE)}")
    return p


def scenario_inputs(inp, rng, side):
    """The inputs with every ranged input at its low (side 0) or its high (side 1): the long-run margin and the long-run growth at the
    bound, and the five yearly growths moved together by (the bound - the year-3 growth)."""
    shift = rng["rev_growth_y3"][side] - inp["rev_growth"][2]
    return dict(inp, rev_growth=[g + shift for g in inp["rev_growth"]], long_run_op_margin=rng["long_run_op_margin"][side],
                terminal_growth=rng["terminal_growth"][side])


def numeric_problems(obj, r):
    """The numeric checks of a reply of valid shape: margins inside (-1, 1), long-run growth below r, the long-run return above 0 and above
    long-run growth, low <= input <= high. The range ends are valued, so the same domain checks apply to them."""
    inp, rng, p = obj["inputs"], obj["ranges"], []
    for k, xs in (("op_margin", inp["op_margin"]), ("long_run_op_margin", [inp["long_run_op_margin"], *rng["long_run_op_margin"]])):
        p += [f"{k} {x} is outside (-1, 1)" for x in xs if not -1 < x < 1]
    base = {"long_run_op_margin": inp["long_run_op_margin"], "rev_growth_y3": inp["rev_growth"][2], "terminal_growth": inp["terminal_growth"]}
    for k in RANGE_KEYS:
        lo, hi = rng[k]
        if not lo <= base[k] <= hi:
            p.append(f"ranges.{k} [{lo}, {hi}] must contain the input {base[k]} (low <= input <= high)")
    gs = [inp["terminal_growth"], *rng["terminal_growth"]]
    p += [f"terminal_growth {g} is not below the cost of equity {r:.4f}" for g in gs if not g < r]
    ron = inp["return_on_new_investment_long_run"]
    if not ron > 0:
        p.append(f"return_on_new_investment_long_run {ron} is not above 0")
    p += [f"return_on_new_investment_long_run {ron} is not above terminal_growth {g}" for g in gs if ron > 0 and not ron > g]
    for name, side in (("base", None), ("low", 0), ("high", 1)):                   # a revenue path needs growth above -1 in every year
        gr = inp["rev_growth"] if side is None else scenario_inputs(inp, rng, side)["rev_growth"]
        p += [f"rev_growth of the {name} case, year {t}: {g:.4f} is not above -1" for t, g in enumerate(gr, 1) if not g > -1]
    return p


def verify_quotes(obj, texts):
    """{key of inputs: (the quotes found word for word in the item they cite, the number given)}."""
    out = {}
    for k in INPUT_KEYS:
        qs = obj["reasons"][k]["quotes"]
        kept = []
        for q in qs:
            i, s = (q.get("id"), q.get("quote")) if isinstance(q, dict) else (None, None)
            if isinstance(i, str) and isinstance(s, str) and i in texts and contract.quote_found(s, [texts[i]]):
                kept.append({"id": i, "quote": s})
        out[k] = (kept, len(qs))
    return out


def quote_problems(verified):
    return [f"reasons.{k} has no quote found word for word in the item it cites" for k, (kept, n) in verified.items() if not kept]


# ---------------------------------------------------------------- the adjusted base (WO_NC9a)
def _checked_item(it, label, texts):
    """(problems, record): the item's quotes found word for word in the item they cite, and the printed number in at least one of them."""
    v, kept = IFF._printed(it["value"]), []
    for q in it["quotes"]:
        i, s = (q.get("id"), q.get("quote")) if isinstance(q, dict) else (None, None)
        if isinstance(i, str) and isinstance(s, str) and i in texts and contract.quote_found(s, [texts[i]]):
            kept.append({"id": i, "quote": s})
    if not kept:
        return [f"{label} has no quote found word for word in the item it cites"], None
    carrying = [k for k in kept if IFF.digits_in_quote(v, [k["quote"]])]
    if not carrying:
        return [f"{label}: the number {it['value']!r} does not appear in any quote that was found word for word"], None
    return [], {"printed": it["value"], "scale": it["scale"], "amount": float(v * IFF.SCALES[it["scale"]]), "what": it["what"].strip(),
                "quotes": carrying + [k for k in kept if k not in carrying], "quotes_given": len(it["quotes"])}


def adjust_base(b, cash, one_offs):
    """(a copy of the base with the two adjustments, the record of them). cash = the checked cash_not_free record or None; one_offs = the checked
    items (each with "sign"). With N the cash that is not free and bill the base's bill rate, inputs.base built excess_cash = C, i_pre = C x bill,
    pt_ex = PT_0 - i_pre - NCI/(1 - tau), x0 = (pt_ex + A_0)(1 - tau), k0 = OI_0 - pt_ex. The earnings base before tax is higher by
    d = N x bill + (charges - gains), so, OI_0 and every other part of the base being untouched:
        excess_cash' = C - N      (the desk adds it at face)       cash_interest_pretax' = i_pre - N x bill
        k0' = k0 - d              (k0_interest is not touched)     x0' = x0 + d (1 - tau)     m0' = x0' / R0
    which keeps the bridge exact: (OI_0 - k0' + A_0)(1 - tau) = x0'. ronic0 stays the filed base year's return (its tangible capital is not stored
    and is not rebuilt here), stamped. Raises DeskRefusal e0_not_positive when x0' is not above 0."""
    n = cash["amount"] if cash is not None else 0.0
    back = n * b["bill_rate"] if cash is not None else 0.0                 # a cash amount above 0 exists only where the base has a bill rate (excess_cash > 0)
    charge = sum(o["amount"] for o in one_offs if o["sign"] == "charge")
    gain = sum(o["amount"] for o in one_offs if o["sign"] == "gain")
    d = back + (charge - gain)
    a = dict(b, excess_cash=b["excess_cash"] - n, k0=b["k0"] - d, x0=b["x0"] + d * (1 - b["tau"]), cash_interest_pretax=b["cash_interest_pretax"] - back)
    a["m0"] = a["x0"] / b["R0"]
    if not a["x0"] > 0:
        raise desk.DeskRefusal("e0_not_positive", f"X_0 = {a['x0']:.6g} after the adjustments: no earnings base")
    stamps = (["cash_not_free_taken_out_of_excess_cash", "interest_on_cash_not_free_returned_to_the_earnings_base"] if cash is not None else []) \
        + (["base_year_one_offs_taken_out_of_k0"] if one_offs else []) + (["ronic0_not_readjusted"] if cash is not None or one_offs else [])
    return a, {"cash_not_free": cash, "base_year_one_offs": list(one_offs), "excess_cash_before": b["excess_cash"], "excess_cash_after": a["excess_cash"],
               "k0_before": b["k0"], "k0_after": a["k0"], "k0_interest": b["k0_interest"], "x0_before": b["x0"], "x0_after": a["x0"],
               "cash_interest_returned": back, "one_offs_charge": charge, "one_offs_gain": gain, "stamps": stamps}


def read_adjustments(obj, b, texts):
    """(problems, the adjusted base, its record, the checked cash, the checked one-offs): the quotes and digits of both objects checked, the cash
    above 0 and at most the cash counted as excess, the adjusted earnings base above 0. A null or an empty list leaves the base as it is."""
    problems, cash, offs = [], None, []
    if obj["cash_not_free"] is not None:
        pr, cash = _checked_item(obj["cash_not_free"], "cash_not_free", texts)
        problems += pr
        if cash is not None and not 0 < cash["amount"] <= b["excess_cash"]:
            problems.append(f"cash_not_free {cash['amount']:,.0f} is not above 0 and at most the cash and short-term investments counted as excess ({b['excess_cash']:,.0f})")
    for i, it in enumerate(obj["base_year_one_offs"] if obj["base_year_one_offs"] is not None else []):
        pr, rec = _checked_item(it, f"base_year_one_offs[{i}]", texts)
        problems += pr
        if rec is not None:
            offs.append(dict(rec, sign=it["sign"]))
    if problems:
        return problems, b, None, None, []
    try:
        a, adj = adjust_base(b, cash, offs)
    except desk.DeskRefusal as e:
        return [f"the adjustments leave no earnings base: {e}"], b, None, None, []
    return [], a, adj, cash, offs


# ---------------------------------------------------------------- the numeric route
def value_inputs(b, r, inp):
    """(value per share, desk result) from numeric inputs, through desk.value_operating on the pinned base: forecast.assemble's own arithmetic with
    the five yearly paths typed instead of blended. Raises desk.DeskRefusal; AssertionError when V1 (checks._recompute) disagrees."""
    rev = [float(b["R0"])]
    for g in inp["rev_growth"]:
        rev.append(rev[-1] * (1 + float(g)))
    amort, _ = desk.amortization_path(b["amort_schedule"], b["amort_thereafter"], 5)
    x_m = inputs.bridge_x_margin(b, [float(m) for m in inp["op_margin"]], rev[1:], amort[:5])
    capex = [float(inp["capex_to_revenue"]) * R for R in rev[1:]]
    m_long = inputs.bridge_x_margin(b, [float(inp["long_run_op_margin"])], [rev[-1]])[0]
    d = {"revenue": rev, "margin": x_m, "capex": capex, "d_ratio": b["d_ratio"], "w": b["w"], "p_ratio": b["p_ratio"], "rou_ratio": b["rou_ratio"],
         "amort_schedule": b["amort_schedule"], "amort_thereafter": b["amort_thereafter"], "delta": b["delta"], "kd": b["kd"], "tau": b["tau"],
         "r": float(r), "g_T": float(inp["terminal_growth"]), "F": int(inp["fade_years"]), "H": 0, "ronic0": b["ronic0"],
         "ronic_T": float(inp["return_on_new_investment_long_run"]), "m_long": m_long, "shares": b["shares"], "excess_cash": b["excess_cash"],
         "stub_days": b["stub_days"], "ppe": b.get("ppe"), "real_estate": bool(b.get("real_estate"))}
    v = desk.value_operating(d)
    checks._recompute(d, v)
    return v["value_per_share"], v


def values(b, r, inp, rng):
    """({base, bear, bull: value per share}, [what the desk could not value], the base's desk result)."""
    out, problems, base_v = {}, [], None
    for name, i in (("base", inp), ("bear", scenario_inputs(inp, rng, 0)), ("bull", scenario_inputs(inp, rng, 1))):
        try:
            out[name], v = value_inputs(b, r, i)
        except (desk.DeskRefusal, ArithmeticError) as e:
            problems.append(f"the desk could not value the {name} inputs: {e}")
        else:
            base_v = v if name == "base" else base_v
    return out, problems, base_v


def old_defaults(b, bar, r):
    """(value per share, how) at the code's old defaults: the record-neutral reply of the menu method. Code only; never loses a valuation."""
    try:
        return checks._neutral_op(b, bar, r)
    except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError, OverflowError, AssertionError) as e:
        return None, f"unavailable: {type(e).__name__}: {e}"


def surfaced_stamps(b):
    """WO_UV2: the stamps of the base `b` that the flags of a run repeat (SURFACED_STAMPS, SURFACED_PREFIXES), in the base's order."""
    return [s for s in b["stamps"] if s in SURFACED_STAMPS or s.startswith(SURFACED_PREFIXES)]


def flags_of(obj, b, rec, verified, vals):
    """The stamps of one run: flags and annotations, never a clamp or a gate."""
    inp, out = obj["inputs"], []
    for series, rows, label in ((rec["margins"], [(f"op_margin.y{t}", x) for t, x in enumerate(inp["op_margin"], 1)] + [("long_run_op_margin", inp["long_run_op_margin"])], "margin"),
                                (rec["growths"], [(f"rev_growth.y{t}", x) for t, x in enumerate(inp["rev_growth"], 1)], "growth")):
        if series:
            lo, hi = min(series.values()), max(series.values())
            out += [f"{label}_outside_filed_record: {k} {x:.4f} (filed {lo:.4f} to {hi:.4f})" for k, x in rows if not lo <= x <= hi]
    if inp["return_on_new_investment_long_run"] > b["ronic0"]:
        out.append(f"return_above_base_year: long-run {inp['return_on_new_investment_long_run']:.4f} against the base year's {b['ronic0']:.4f}")
    if obj["situation"]["base_year_representative"] == "no":
        out.append("base_year_not_representative")
    out += [f"{k}_no: {obj['situation'][k]['why'].strip()}" for k in SITUATION_FLAGS if obj["situation"][k]["answer"] == "no"]       # WO_NC9a: flags only
    if obj["confidence"] == "low":
        out.append("confidence_low")
    out += surfaced_stamps(b)
    n, m = sum(len(k) for k, _ in verified.values()), sum(t for _, t in verified.values())
    out.append(f"quotes_verified: {n} of {m}")
    if not vals["bear"] <= vals["base"] <= vals["bull"]:
        out.append(f"scenario_order_not_monotone: bear {vals['bear']:.4f}, base {vals['base']:.4f}, bull {vals['bull']:.4f}")
    return out


def _tax_range(f, b, market_cap, inp, rng, r, vals, cash=None, offs=()):
    """The same read valued at the second rate of a statutory tax fallback, in the shape of run._tax_range. The first values are never touched.
    The same checked adjustments (cash, one-offs) are made on the second rate's base (WO_NC9a)."""
    tf = b["tax_fallback"]
    tr = {"rate": tf["rate"], "rate_alt": tf["rate_alt"], "values": vals, "values_alt": None, "status_alt": None}
    try:
        alt, problems, _ = values(adjust_base(vrun.alt_tax_base(f, b, market_cap), cash, offs)[0], r, inp, rng)
    except desk.DeskRefusal as e:
        return dict(tr, status_alt=f"no_call: {e.code}: {e}")
    except AssertionError as e:
        return dict(tr, status_alt=f"engine_defect: {e}")
    return dict(tr, values_alt=alt if not problems else None, status_alt="ok" if not problems else "no_call: " + "; ".join(problems))


# ---------------------------------------------------------------- one run
def _write(run_dir, result):
    runner._write_json(run_dir / "result.json", result)
    return result


def read_analysis(q1):
    """The stored read (analysis.json of the Q1 run) from the Q1 result, or {}."""
    p = Path(q1.get("run_dir") or "") / "analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if q1.get("run_dir") and p.exists() else {}


def value(packet_path, cik, sector, market_cap, *, family, analysis=None, seed=runner.SEED_BASE, out_root=vrun.RUNS, online=True, root=None,
          allow_after_T=False, interest_override=None):
    """One run of the decided method (one decision call, plus one repair turn when a check fails); writes result.json and raw/attempt_<n>.json
    under out_root. The result has vrun.value's shape (status, values, base, cost_of_equity, checks.prob, stamps, versions) and `decided`.
    A name code refuses before any call is refused as the menu method refuses it. A call that gets no reply raises (the worker's failure path)."""
    packet, src = runner.load_packet(packet_path)
    run_dir = out_root / f"{packet['ticker']}_{runner.t_compact(packet['decision_time_utc'])}_{runner.sha256_bytes(src)[:12]}_decided_{seed}"
    (run_dir / "raw").mkdir(parents=True, exist_ok=True)
    result = {"ticker": packet["ticker"], "T": packet["decision_time_utc"], "packet_sha256": runner.sha256_bytes(src), "seed": seed,
              "versions": {"method": METHOD, "decided": DECIDED_VERSION, "desk": desk.DESK_VERSION, "facts": facts.FACTS_VERSION,
                           "inputs": inputs.INPUTS_VERSION, "checks": checks.CHECKS_VERSION, "coe": coe.COE_VERSION,
                           "contract": contract.CONTRACT, "model": runner.MODEL, "git": runner.git_state()},
              "authority": "diagnostic_only"}
    V = VARIANTS.get(family)                                           # WO_NC9c: the family's variant (record text, task text, extra checks), or None
    if V:
        result["versions"]["variant"] = V.VERSION
    try:
        if family not in FAMILIES and V is None:
            raise desk.DeskRefusal("family_not_routed", f"family {family!r}: the decided method values only {FAMILIES}")
        if any(e.get("kind") == "news" for e in packet.get("evidence") or []):         # as vrun.value
            raise desk.DeskRefusal("news_items_not_valued", "the packet holds news items; the valuation reads filings only")
        f, b, bar, record, r, prov, fy_ends = vrun.prepare(packet, cik, sector, market_cap, online=online, root=root, allow_after_T=allow_after_T, family=family,
                                                     interest_override=interest_override, **(V.PREPARE if V else {}))      # WO_NC8, WO_NC9c
    except desk.DeskRefusal as e:
        result.update(status="no_call", reason=e.code, detail=str(e))
        return _write(run_dir, result)
    result.update(family=family, base=b, bar=bar, cost_of_equity=r, coe=prov, facts_provenance=f.get("_provenance"), stamps=b["stamps"] + prov.get("stamps", []))
    old_value, old_how = old_defaults(b, bar, r)                       # code only: before any call
    f_all = facts.build(cik, runner._parse_t(packet["decision_time_utc"]), online=False, root=root, years=ALL_YEARS, substitute_revenue=True, substitute_items=True)
    rec_text, rec = (V.record_text if V else record_text)(f, f_all, b, r, prov)
    texts = contract.evidence_texts(vtask.mask_price(packet))
    texts["REC"] = rec_text
    prior, n_kept, n_dropped = prior_read(analysis)
    attempts, retry, out, extra = [], None, None, None
    for n in (1, 2):
        msgs = messages(packet, rec_text, prior, retry, V.TASK if V else None)
        t0 = time.monotonic()
        kind, resp, detail = runner.call({"model": runner.MODEL, "stream": False, "messages": msgs}, runner.llm_provider.OLLAMA_URL, runner.TASK_TIMEOUT_S)
        secs = round(time.monotonic() - t0, 3)
        if kind != "reply":
            raise RuntimeError(f"decided call failed: {kind}: {detail}")
        content = ((resp or {}).get("message") or {}).get("content")
        obj, perr = runner.parse_reply(content)
        att = {"attempt": n, "seconds": secs, **{k: (resp or {}).get(k) for k in ("prompt_eval_count", "eval_count", "done_reason")}}
        verified = vals = base_v = adj = cash = offs = None
        if perr:
            problems = [f"not valid JSON: {perr}"]
        else:
            problems = shape_problems(obj) or (V.shape_problems(obj) if V else [])
            ref = V.refusal(obj) if V and not problems else None         # WO_NC9c: a refusal the read itself states (a lender), before any further check
            if ref:
                att.update(outcome="refused", problems=[])
                attempts.append(att)
                runner._write_json(run_dir / "raw" / f"attempt_{n}.json", {"messages": msgs, "response": content, "problems": [], "refusal": ref})
                result.update(status="no_call", reason=ref[0], detail=ref[1], attempts=attempts, decided={"situation": obj["situation"]})
                return _write(run_dir, result)
            if not problems:
                verified = verify_quotes(obj, texts)
                problems = numeric_problems(obj, r) + quote_problems(verified)
                ap, b_adj, adj, cash, offs = read_adjustments(obj, b, texts)           # WO_NC9a
                problems += ap
                if V:
                    vp, extra = V.check(obj, texts, f, b)                 # WO_NC9c: the variant's own fields; its problems go to the repair turn with the others
                    problems += vp
            if not problems:
                try:
                    vals, problems, base_v = values(b_adj, r, obj["inputs"], obj["ranges"])
                except AssertionError as e:                               # an engine defect is recorded, never a crash
                    att.update(outcome="engine_defect", problems=[str(e)])
                    attempts.append(att)
                    runner._write_json(run_dir / "raw" / f"attempt_{n}.json", {"messages": msgs, "response": content, "problems": [str(e)]})
                    result.update(status="engine_defect", reason="engine_defect", detail=str(e), attempts=attempts)
                    return _write(run_dir, result)
        att.update(outcome="ok" if not problems else "invalid", problems=problems)
        attempts.append(att)
        runner._write_json(run_dir / "raw" / f"attempt_{n}.json", {"messages": msgs, "response": content, "problems": problems})
        if not problems:
            out = (n, obj, verified, vals, base_v, adj, cash, offs)
            break
        retry = (content or "", problems)
    result["attempts"] = attempts
    if out is None:
        result.update(status="no_call", reason="decision_invalid", detail="; ".join(attempts[-1]["problems"]))
        return _write(run_dir, result)
    n, obj, verified, vals, base_v, adj, cash, offs = out
    inp, rng = obj["inputs"], obj["ranges"]
    flags = flags_of(obj, b, rec, verified, vals) + (extra["flags"] if V else [])
    dec = {"situation": obj["situation"], "inputs": inp, "ranges": rng, "risks": obj["biggest_risks"], "confidence": obj["confidence"],
           "reasons": {k: {"why": obj["reasons"][k]["why"], "quotes": verified[k][0], "quotes_given": verified[k][1]} for k in INPUT_KEYS},
           "scenarios": {s: {k: v for k, v in scenario_inputs(inp, rng, side).items() if k in ("rev_growth", "long_run_op_margin", "terminal_growth")}
                         for s, side in (("bear", 0), ("bull", 1))},
           "flags": flags, "adjustments": adj, "value_at_old_defaults": old_value, "old_defaults_inputs": old_how,
           "prior_read_claims": {"kept": n_kept, "dropped_unsupported": n_dropped},
           "diagnostics": {"equity_value": base_v["equity_value"], "tv_share": base_v["tv_pv"] / base_v["equity_value"] if base_v["equity_value"] else None,
                           "seam_ratio": base_v["seam_ratio"], "da_rule": base_v["da_rule"], "wedge_rate_5": base_v["wedge_rate_5"],
                           "depreciation_kept_rate": base_v["depreciation_kept_rate"]}}
    if V:
        dec[V.KEY] = extra["record"]
    result.update(status="ok", values=vals, checks={"prob": dict(checks.PROB), "version": DECIDED_VERSION}, inputs=obj, checked_attempt=n, decided=dec)
    if b.get("tax_fallback"):
        result["tax_range"] = _tax_range(f, b, market_cap, inp, rng, r, vals, cash, offs)
    return _write(run_dir, result)


# ---------------------------------------------------------------- the two runs
def run_gap(a, c):
    """|a - c| / mean(|a|, |c|), or None when both are 0."""
    d = (abs(a) + abs(c)) / 2
    return None if d == 0 else abs(a - c) / d


def combine_runs(results):
    """(valued, v): the report's values from the two runs, {seed: result}. Both runs must have a valued result: there is no fallback to a default
    and no single-run value. v = {"values": the mean of the two runs' bear, base and bull, "annotations", "decided"}."""
    ok = {s: x for s, x in sorted(results.items()) if str(x.get("status", "")).startswith("ok")}
    if len(ok) != 2 or len(results) != 2:
        return False, {}
    (s1, a), (s2, c) = ok.items()
    cyc = {s: x["decided"]["situation"]["cyclical"] for s, x in ok.items()}
    unclear = len(set(cyc.values())) > 1
    flags = (["situation_unclear"] if unclear else []) + [f"run {s}: {fl}" for s, x in ok.items() for fl in x["decided"]["flags"]]
    d1 = a["decided"]
    return True, {"values": {k: (a["values"][k] + c["values"][k]) / 2 for k in ("bear", "base", "bull")},
                  "annotations": [f"seeds_disagree: situation.cyclical ({', '.join(f'{s} {y}' for s, y in cyc.items())})"] if unclear else [],
                  "decided": {"version": DECIDED_VERSION, "method": METHOD, "runs": {s: dict(x["decided"], values=x["values"]) for s, x in ok.items()},
                              "run_gap": run_gap(a["values"]["base"], c["values"]["base"]), "situation_unclear": unclear, "flags": flags,
                              "value_at_old_defaults": d1["value_at_old_defaults"], "old_defaults_inputs": d1["old_defaults_inputs"]}}


def tax_range_alt(ok):
    """(the mean of the two runs' values at the second rate or None, status_alt, {seed: base value at the second rate})."""
    alts = {s: ((x.get("tax_range") or {}).get("values_alt")) for s, x in ok.items()}
    seed_base = {s: (a or {}).get("base") for s, a in alts.items()}
    if all(alts.values()):
        return {k: sum(a[k] for a in alts.values()) / len(alts) for k in ("bear", "base", "bull")}, "ok", seed_base
    return None, next((str((x.get("tax_range") or {}).get("status_alt")) for s, x in ok.items() if not alts[s]), "not_available"), seed_base
