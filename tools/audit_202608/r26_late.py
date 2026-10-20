"""r26_late.py - stages 2 to 4 of revision 26 (SPEC_rev26_staged_analyst.md sections 2-4), the parts that are text and arithmetic: the tool schemas, the
three TASK texts, the renderers of each artifact into the words a session reads, the frozen table, the memo verifier and the consensus adapter.

No model, no network, no clock. The sessions that use these are in r26_stages.py; the forecast arithmetic is tools/r26_forecast.py (brief R26-C).

THE FROZEN TABLE (stage 4). After stage 3 the desk result is frozen into rows of (label, value, kind). Stage 4 is given the table as `Label: value` lines and is
told to quote a number only under its label; the verifier then reads the memo. A row's kind sets how its value is written and compared:

    usd    dollars, shown with two decimals           pct    a fraction x shown as x*100 with one decimal and %      int   a whole number
    plain  a number shown with up to two decimals     enum   a word (the transition, the baseline)                   word  the verdict

VERIFIER (SPEC section 4; annotate, never change). Where a label occurs in the memo and a number follows it at once (`Label: $5`, `Label of 4.5%`, `Label is 3`;
a label word inside another phrase, such as `price-implied growth`, is not a statement of that label), the number is compared with the row's value *within
rounding*: the memo's number must be the row's value rounded to the number of decimals the memo wrote, and a memo more precise than the table must equal it.
Labels are matched longest first, so "Base value per share" is never read inside a longer label. A label that does not occur is not a finding: the verifier
checks what the memo says, it does not demand it.
    memo_number_mismatch    a labelled number that is not the table's within rounding
    memo_verdict_mismatch   the verdict word SECTION 0 states differs from the code's (undervalued, overvalued, hold, no_call)
    memo_forecast_mismatch  an enum label (a transition or baseline) followed by a word that is not the forecast's
    memo_prose_number_mismatch (cross-check 23, item 13; an ANNOTATION, it does not gate) a number written with %, $, x or bps anywhere in the memo that is neither in the
                            table nor a number of a fact the forecast cites (or the memo names by id); years and dates carry no mark and are not read
"""
import copy
import json
import math
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
_TOOLS = str(Path(__file__).resolve().parents[1])
for _p in (_HERE, _TOOLS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import r26_forecast as rf  # noqa: E402

SCEN = rf.SCENARIOS
HORIZON = rf.HORIZON
MEMO_FLAGS = ("memo_number_mismatch", "memo_verdict_mismatch", "memo_forecast_mismatch")          # these gate: any one makes the result non-actionable
MEMO_ANNOTATIONS = ("memo_prose_number_mismatch",)                                                  # reported beside them; they do not gate (item 13)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# ---------------------------------------------------------------- the tools

def _numbers(desc, n=None):
    s = {"type": "array", "items": {"type": "number"}, "description": desc}
    if n is not None:
        s["minItems"] = s["maxItems"] = n
    return s


def _ids(desc):
    return {"type": "array", "items": {"type": "string"}, "description": desc}


LABEL_ENUMS = {"margin_persistence": ("structural", "partly_structural", "transient"), "cycle_position": ("trough", "mid", "peak", "not_cyclical"),
               "growth_trajectory": ("accelerating", "steady", "decelerating", "shrinking")}
LABEL_WORDS = {"margin_persistence": "margin persistence", "cycle_position": "cycle position", "growth_trajectory": "growth trajectory"}
LABEL_DESC = {"margin_persistence": "structural: the margin level rests on lasting advantages; partly_structural: part of it does; transient: it is a passing condition.",
              "cycle_position": "where the business is in its cycle now: trough, mid, peak, or not_cyclical.",
              "growth_trajectory": "accelerating, steady, decelerating or shrinking: the direction of revenue growth."}
CRUX_INPUTS = ("coe", "fade_years", "terminal_g", "terminal_ronic", "long_run_margin")      # what the price-implied solver supports on the 25.2 path (growth_years_3_5 and year2_level are "not applicable")


def validate_labels(forecast, dossier=None):
    """Structure problems of the Base's three classifications (stage 2 gives them; code fills the contract from them): each {"label": enum, "fact_ids": [existing ids]}."""
    out = []
    base = ((forecast or {}).get("scenarios") or {}).get("Base")
    if not isinstance(base, dict):
        return out                                     # rf.validate_forecast names a missing Base
    known = rf.dossier_fact_ids(dossier) if dossier is not None else None
    usable = rf.usable_fact_ids(dossier) if dossier is not None else None
    for k, enum in LABEL_ENUMS.items():
        v = base.get(k)
        if not isinstance(v, dict):
            out.append({"field": f"Base.{k}", "problem": "missing_or_not_an_object"})
            continue
        if v.get("label") not in enum:
            out.append({"field": f"Base.{k}.label", "problem": "not_one_of_" + "|".join(enum)})
        ids = v.get("fact_ids")
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            out.append({"field": f"Base.{k}.fact_ids", "problem": "not_a_list_of_fact_ids"})
        elif known is not None and [x for x in ids if x not in known]:
            out.append({"field": f"Base.{k}.fact_ids", "problem": "fact_id_not_in_dossier", "detail": ", ".join(x for x in ids if x not in known)})
        elif usable is not None and [x for x in ids if x not in usable]:
            out.append({"field": f"Base.{k}.fact_ids", "problem": "fact_id_not_usable", "detail": ", ".join(x for x in ids if x not in usable)})
    return out


def _label_schema():
    return {k: {"type": "object", "description": LABEL_DESC[k], "properties": {
        "label": {"type": "string", "enum": list(LABEL_ENUMS[k])}, "fact_ids": _ids("The ids of the dossier facts this classification rests on.")},
        "required": ["label", "fact_ids"]} for k in LABEL_ENUMS}


def scenario_schema():
    return {
        "type": "object",
        "properties": {
            "near_term": {"type": "object", "description": "Years 1 and 2, your own forecast.", "properties": {
                "rev_growth": _numbers("Annual revenue growth of year 1 and year 2, as decimals.", 2),
                "op_margin": _numbers("The filed operating margin (operating income / revenue) of year 1 and year 2, as decimals.", 2),
                "fact_ids": _ids("The ids of the dossier facts these two years rest on.")},
                "required": ["rev_growth", "op_margin", "fact_ids"]},
            "normalized": {"type": "object", "description": "The normalized state the business reaches by year N: its mid-cycle margin in year N, not the margin after year 5.", "properties": {
                "year": {"type": "integer", "description": "The year N (a whole number from 3 to 5) in which the business reaches its normalized state: the year-N mid-cycle margin."},
                "rev_growth": {"type": "number", "description": "Annual revenue growth in the normalized state, a decimal."},
                "baseline": {"type": "string", "enum": list(rf.BASELINES), "description": "Which statistic of the filed operating-margin history the normalized margin starts from."},
                "delta_pts": {"type": "number", "description": "Percentage points added to that baseline (negative subtracts). Code adds it: you never type the normalized margin."},
                "fact_ids": _ids("The ids of the dossier facts the normalized state rests on."),
                "reason": {"type": "string", "description": "At most 60 words: why this is the normalized state."}},
                "required": ["year", "rev_growth", "baseline", "delta_pts", "fact_ids", "reason"]},
            "transition": {"type": "string", "enum": list(rf.TRANSITIONS), "description": "How years 3 to N get from the year-2 values to the normalized values."},
            "transition_year": {"type": "integer", "description": "Required for step_at_year (the year of the step) and hold_then_linear (the last year held)."},
            "long_run_margin_op": {"type": "number", "description": "The post-year-5 terminal margin: the filed operating margin (a decimal) the business earns at the end of the fade after year 5. It is not the year-N mid-cycle margin."},
            "terminal_g": {"type": "number", "description": "Terminal growth after the fade, a decimal."},
            "terminal_ronic": {"type": "number", "description": "The return on new investment that pays for growth after the fade, a decimal."},
            "fade_years": {"type": "integer", "description": "Whole years over which growth and margin move from year 5 to terminal growth and the long-run margin."},
            "prob": {"type": "number", "description": "The scenario's probability; the three add to one."},
            "long_run_fact_ids": _ids("The ids of the usable dossier facts behind long_run_margin_op (give these, or no_duration_matched_evidence)."),
            "no_duration_matched_evidence": {"type": "string", "description": "Only when no usable fact speaks for as long as the long run: say so and why, in one sentence. Leave it out when long_run_fact_ids is given."},
        },
        "required": ["near_term", "normalized", "transition", "long_run_margin_op", "terminal_g", "terminal_ronic", "fade_years", "prob"],
    }


def forecast_properties():
    sc = scenario_schema()
    base = copy.deepcopy(sc)
    base["properties"].update(_label_schema())
    base["required"] = base["required"] + list(LABEL_ENUMS)
    return {
        "discount_rate": {"type": "number", "description": "The annual discount rate, a decimal."},
        "frame": {"type": "string", "enum": list(rf.FRAMES), "description": "Always equity: the flows are after interest and are valued at the cost of equity."},
        "scenarios": {"type": "object", "properties": {"Base": base, "Bull": copy.deepcopy(sc), "Bear": copy.deepcopy(sc)}, "required": list(SCEN)},
    }


FORECAST_REQUIRED = ["discount_rate", "frame", "scenarios"]

X_BASIS_PHRASES = (("filed operating margin (operating income / revenue)", "X-basis margin (net income plus after-tax amortization of acquired intangibles, over revenue)"),
                   ("filed operating margin (a decimal)", "X-basis margin (a decimal)"), ("filed operating-margin history", "X-basis margin history"),
                   ("filed operating margin", "X-basis margin"))


def _x_wording(text):
    for a, b in X_BASIS_PHRASES:
        text = text.replace(a, b)
    return text


def stage2_task(bar=None):
    """STAGE2_TASK, or its X-basis wording when the margin bar is on the X basis (the financial family, or any name with no filed operating income): the margins you give are
    the X-basis margin and code converts nothing."""
    if (bar or {}).get("basis") != "x":
        return STAGE2_TASK
    t = STAGE2_TASK.replace("1. The margin basis. Every margin you give is the filed operating margin: operating income divided by revenue, the operating-income line of the income statement. It is not a net margin, an after-tax margin or an adjusted margin. Code converts your operating margins to the basis the valuation desk uses, and shows the conversion afterwards.",
                            "1. The margin basis. Every margin you give is on the valuation desk's basis, the X-basis margin: net income plus the after-tax amortization of acquired intangibles, divided by revenue, as the history bar shows it. Code converts nothing. The line \"operating margin\" in the fields below means this margin.")
    assert t != STAGE2_TASK
    return _x_wording(t)


def stage2_tool(bar=None):
    """SUBMIT_FORECAST_TOOL with its descriptions in the X-basis wording when the bar is on the X basis."""
    if (bar or {}).get("basis") != "x":
        return SUBMIT_FORECAST_TOOL
    return json.loads(_x_wording(json.dumps(SUBMIT_FORECAST_TOOL)))


SUBMIT_FORECAST_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_forecast",
        "description": ("Submit your forecast: Base, Bull and Bear, each with its two near-term years, its normalized state, its transition and its long run. "
                        "Code checks the structure and a few domain rules (the fields, finite numbers, the enums, that every fact id exists and is usable, probabilities in 0 to 1 adding to one, revenue not negative, the discount rate above terminal growth, a positive return on new investment); it never bounds a margin. "
                        "Everything that follows (the margin path, the conversion to the valuation basis, the value) is code's."),
        "parameters": {"type": "object", "properties": forecast_properties(), "required": FORECAST_REQUIRED},
    },
}


def revision_tool():
    t = copy.deepcopy(SUBMIT_FORECAST_TOOL)
    t["function"]["description"] = (
        "Submit ONE revised forecast, in full (the same fields as the forecast you were shown), only to correct an error of fact. A revision must cite at least one usable dossier fact in revision_fact_ids and "
        "give in revision_reason the error in the forecast that fact shows. You may call this once; a second call is refused and the stage closes.")
    props = t["function"]["parameters"]["properties"]
    props["revision_fact_ids"] = _ids("At least one usable dossier fact id that shows the error.")
    props["revision_reason"] = {"type": "string", "description": "The error of fact in the forecast you were shown, and how that fact corrects it."}
    t["function"]["parameters"]["required"] = FORECAST_REQUIRED + ["revision_fact_ids", "revision_reason"]
    return t


SUBMIT_REVISION_TOOL = revision_tool()


X_BASIS_NOTE = ("The basis of every margin in this stage: the forecast, the desk table and the conversion table give the X-basis margin (net income plus the after-tax amortization of acquired "
                "intangibles, divided by revenue), the valuation desk's own basis. Code converts nothing, and a line named operating margin in them is this margin.")


def revision_tool_for(bar=None):
    """SUBMIT_REVISION_TOOL, in the X-basis wording when the margin bar is on the X basis."""
    return SUBMIT_REVISION_TOOL if (bar or {}).get("basis") != "x" else json.loads(_x_wording(json.dumps(SUBMIT_REVISION_TOOL)))


def stage3_task(bar=None, run_date=""):
    """STAGE3_TASK formatted; for an X-basis bar the X-basis note follows the first paragraph (same switch as stage2_task)."""
    t = STAGE3_TASK if (bar or {}).get("basis") != "x" else STAGE3_TASK.replace("\n\nTreat the reveal", " " + X_BASIS_NOTE + "\n\nTreat the reveal", 1)
    return t.format(run_date=run_date)


def stage4_task(bar=None):
    """STAGE4_TASK; for an X-basis bar the X-basis note follows its first paragraph."""
    if (bar or {}).get("basis") != "x":
        return STAGE4_TASK
    assert "\n\n1. Write SECTION 0" in STAGE4_TASK
    return STAGE4_TASK.replace("\n\n1. Write SECTION 0", " " + X_BASIS_NOTE + "\n\n1. Write SECTION 0", 1)



STATE_CRUX_TOOL = {
    "type": "function",
    "function": {
        "name": "state_crux",
        "description": ("State the crux of the valuation, and whether you keep the forecast or revise it. Call it once the form is right; a malformed crux is returned to you once. "
                        "You cite dossier facts by id; code pulls each fact's source, date and verbatim quote and resolves the quote against its source."),
        "parameters": {"type": "object", "properties": {
            "crux": {"type": "array", "minItems": 1, "maxItems": 3, "description": "One to three entries.", "items": {"type": "object", "properties": {
                "input": {"type": "string", "enum": list(CRUX_INPUTS)},
                "reason": {"type": "string", "description": "Why this company's value of the input differs from, or matches, what the price implies, and by how much."},
                "citations": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "object", "properties": {
                    "fact_id": {"type": "string", "description": "The id of a usable dossier fact (F1, F2, ...). You do not type its source, date or quote: code supplies them from the fact."}},
                    "required": ["fact_id"]}}},
                "required": ["input", "reason", "citations"]}},
            "decision": {"type": "string", "enum": ["keep", "revise"], "description": "keep the forecast as shown, or revise it once with submit_forecast."}},
            "required": ["crux", "decision"]},
    },
}


# ---------------------------------------------------------------- the three TASK texts

STAGE2_TASK = """STAGE 2 OF 4: THE BLIND FORECAST.

You are the analyst for the company in the data pack above. In this stage you forecast, and you do it blind: you are not shown the market price, the analysts' forecasts, or any default or reference value, and you have no tools to look for them. You see the data pack, the research dossier of stage 1 (the facts, each with a quote that code has verified, and the research summary) and the company's filed operating-margin history. Code does every calculation after you. Make exactly one call to submit_forecast.

1. The margin basis. Every margin you give is the filed operating margin: operating income divided by revenue, the operating-income line of the income statement. It is not a net margin, an after-tax margin or an adjusted margin. Code converts your operating margins to the basis the valuation desk uses, and shows the conversion afterwards. Revenue growth is the annual growth of revenue. Margins and growth are decimals; delta_pts alone is in percentage points.
2. Three scenarios: Base, Bull and Bear. For each, give the two near-term years (revenue growth and operating margin for year 1 and year 2), then the normalized state the business reaches.
3. The normalized state. Choose the year N, a whole number from 3 to 5, by which the business is in its normalized state, and its revenue growth. The normalized margin is the year-N mid-cycle margin: a baseline plus a delta. Choose a baseline from the filed history (min, p25, median, p75, max or last) and delta_pts, the percentage points added to that baseline (a negative number subtracts, zero keeps the baseline). A delta_pts of one is one percentage point. You never type the normalized margin; code adds the two. A worked example, for illustration only: if the history's median were ten percent and you chose baseline median with delta_pts 2.5, code's normalized margin would be twelve and a half percent; delta_pts -1.5 would give eight and a half percent; delta_pts 0.025 would add only a fortieth of a point, so write 2.5 for two and a half points.
4. The transition from year 2 to the normalized state: linear (a straight line from year 2 to year N), step_at_year (the year-2 values until transition_year, the normalized values from it) or hold_then_linear (the year-2 values through transition_year, then a straight line reaching the normalized values in year N). Growth moves the same way as the margin. After year N the normalized values hold to year 5.
5. A normalization that comes later than year 5 (a contract that runs for many years, a ramp, a cycle) is not given as N. Give the state of year 5, and express the later normalization through long_run_margin_op, the post-year-5 terminal margin: the operating margin the business earns when the fade after year 5 has finished (it is not the year-N mid-cycle margin of item 3), and fade_years, the whole years that fade takes (growth also moves from year 5 to terminal_g over it).
6. Also give for each scenario terminal_g, terminal_ronic (the return on new investment that pays for growth after the fade), prob (the three probabilities add to one), and for the forecast the discount_rate and the frame, which is always equity (the pack's flows are after interest and are valued at the cost of equity). The discount_rate must be above every terminal_g, terminal_ronic must be above zero, and each probability is between 0 and 1.
7. Evidence. In near_term.fact_ids and normalized.fact_ids cite the usable dossier facts each rests on (each needs at least one), and in long_run_fact_ids the facts behind long_run_margin_op; if no fact speaks for as long as the long run, leave long_run_fact_ids out and say so in no_duration_matched_evidence, with the reason. A fact speaks only for the span its duration states: code values what happens when that evidence expires and reports it, so rest the normalized state and the long run on evidence of matching duration. Every id you cite must be one listed as usable; the dossier shows you no other. A company-adjusted or non-GAAP fact tells you the direction of a change; it never sets the level of a margin, which rests on filed figures. Give in normalized.reason, in at most 60 words, why this is the normalized state.
8. Classify the Base, each with the dossier facts it rests on (fact_ids): margin_persistence says whether the margin level rests on lasting advantages (structural), only partly does (partly_structural) or is a passing condition (transient); cycle_position says where the business is in its cycle now (trough, mid, peak or not_cyclical); growth_trajectory says whether revenue growth is accelerating, steady, decelerating or shrinking. Each is judged from its own evidence and none is forced by another.
9. Code checks the structure and a few domain rules: the fields, finite numbers, the enums, that the cited fact ids are usable, that the probabilities are between 0 and 1 and add to one, that revenue never goes negative, that the discount rate is above terminal growth and that terminal_ronic is positive. It never bounds a margin, so the judgment is yours. If a check fails you get one correction."""

STAGE3_TASK = """STAGE 3 OF 4: THE REVEAL AND THE AUDIT.

In stage 2 a forecast was made blind, in three samples. You now see the forecast of the median sample (the numbers only, with its valuation), the values of all three samples, the market price, what the price implies for each judgment input, and the analysts' consensus converted by code to the same basis as the forecast, when it is comparable. Today's date is {run_date}.

Treat the reveal as an audit of the market's view, not as an answer. The price is the market's opinion; the consensus is analysts' opinion; neither is evidence. Ask what the market must believe for the price to be right, and whether the dossier's facts support that belief, your forecast, or neither. Move a number only for a reason that a fact in the dossier supplies.

(a) The crux. Call state_crux. Name one to three of the desk's judgment inputs (coe, fade_years, terminal_g, terminal_ronic, long_run_margin) that decide whether the price is right; the growth of years 3 to 5 and the year-2 level are declared in the forecast and are not offered. For each give your reason (why this company's value of the input is what you say, against what the price implies, and by how much) and one to five citations {{fact_id}} of this company's own evidence: the id of a usable dossier fact. You do not type a source, a date or a quote; code takes them from the fact and resolves the quote against its source. A fact whose quote is shorter than 30 characters cannot be cited. A crux is required whatever your view: if the evidence supports the price, name the inputs on which it does. One entry that fails makes the whole crux invalid, and without a valid crux there is no call.
(b) Keep or revise. Keep is the default: the forecast was made blind, from the filed record, and the price and the consensus are not evidence. In the same state_crux call give decision: keep, or revise. Revise only when a dossier fact shows that the forecast contains an error of fact (a figure misread, a basis mixed up, a fact it ignored that contradicts it); a difference from the price or the consensus is never a reason. To revise, call submit_forecast once with the full revised forecast, revision_fact_ids (at least one usable dossier fact) and revision_reason (the error of fact, and how that fact corrects it). Code accepts one revision only; a second call is refused and the stage closes. A revision with no fact that supports it is not accepted, and a number that moved toward the consensus or the price is recorded by code as a pull toward it, whatever fact is cited. A company-adjusted or non-GAAP fact informs the direction of a change, never the level of a margin.

You cannot see the reasoning behind the stage-2 forecast. You see its numbers, the ids of the facts it cited and its classification labels; judge it by the dossier."""

STAGE4_TASK = """STAGE 4 OF 4: THE MEMORANDUM.

The valuation is finished and frozen. Below are the revealed price and momentum facts, the final desk table (every number in it was computed by code), the conversion table, the crux with code's verification of its quotes, the stage-2 spread, the diagnostics, and the research dossier. Write the memorandum that explains the locked numbers. You cannot change a number, and you must never restate a number that is not in the table.

1. Write SECTION 0 first: its first line is `Verdict: undervalued`, `Verdict: overvalued`, `Verdict: hold` or `Verdict: no call`, the word the table gives under "Verdict", with one sentence on why. Then the sections you need: the business and what drives its economics; the forecast and why (the normalized state, the transition and the baseline, with the dossier facts behind them by id); the crux, the quotes that support it and what code found; what the diagnostics show (the alternative path if a fact's evidence expires, or the early-fade stress when it speaks for longer than the five explicit years; the consensus divergence; the spread); the risks and what would change the view.
2. Quote a number only under its label from the table, written exactly as the label is written (for example `Base value per share: $...`), and never round it more coarsely than the table does by more than the digits you write. Do not compute new numbers: no averages, differences or ratios of your own. In SECTION 2 state the forecast's labels exactly as the table writes them (for example `Base transition: ...`, `Base baseline: ...`, `Base margin persistence: ...`). Code checks every labelled number, the verdict word and these labels against the table and flags a difference.
3. If the table says no call, say so in SECTION 0 and state the reasons the table gives; do not argue a verdict.
4. End with the contract: a ```json:underwriting block holding only the text fields listed here, each as the system text describes: catalysts (a list of {date, event, direction, estimates_moved, scenario}), cycle_evidence, normalization_reason, margin_persistence_evidence, cycle_position_evidence, growth_trajectory_evidence (one line each: where the evidence for the Base classification in the table is; the classifications themselves are the forecast's and code fills them), momentum_view (confirming, neutral or contradicting; ground it in the REVEALED block), entry_timing (buy_now, wait_for_momentum or avoid), position_basis (value, momentum or none), momentum_evidence, momentum_flip_condition and momentum_break_rule ({metric, comparator, threshold, window_days}), invalidation_rules (a list of {metric, comparator, threshold, window, source}) and thesis_invalidation_trigger. Code fills every number of the contract (values, probabilities, sizes, margins) from the frozen table; leave them out."""


# ---------------------------------------------------------------- renderers

def _p(x, d=1):
    return f"{x * 100:.{d}f}%" if _num(x) else "n/a"


def _dur(d):
    if d is None:
        return "a one-off figure"
    if d == "ongoing":
        return "ongoing"
    return f"{d:g} years" if _num(d) else str(d)


REASON_CODES = ("quote_not_found", "metric_not_near_quote", "association_uncertain", "malformed", "source_not_resolved")


def reason_code(f):
    """The reason code of an unusable fact (item 2): one word from REASON_CODES, never the model's own words (the metric words a fact failed on are not shown)."""
    c = f.get("unusable_code")
    if c in REASON_CODES:
        return c
    r = str(f.get("unusable_reason") or "")
    for code, needle in (("association_uncertain", "association_uncertain"), ("metric_not_near_quote", "metric_not_near_quote"), ("malformed", "malformed"),
                         ("source_not_resolved", "source not resolved"), ("quote_not_found", "quote not found")):
        if r.startswith(needle) or needle in r:
            return code
    return "quote_not_found" if r else "malformed"


def render_dossier(dossier):
    """The dossier as stages 2-4 read it. Unusable facts are never shown (item 2): only their count and the reason codes, so no quote, metric or number of a fact that
    failed the checks reaches a stage and none can be cited."""
    d = dossier or {}
    facts = d.get("facts") or []
    use = [f for f in facts if f.get("usable")]
    lines = [f"RESEARCH DOSSIER (stage 1): {len(facts)} fact(s), {len(use)} usable" + ("" if not d.get("incomplete") else f"; INCOMPLETE ({d.get('incomplete_reason') or 'unfinished'})"), "",
             "Research summary:", d.get("summary") or "(none)", "", "USABLE FACTS (the quote was found in its source; cite them by id):"]
    for f in use:
        v = "no number" if f.get("value") is None else f"{f['value']:g} {f.get('unit') or ''}".strip()
        lines.append(f"[{f['fact_id']}] {f.get('entity')} | {f.get('metric')} | {f.get('period')} | {v} | basis {f.get('basis')} | speaks for {_dur(f.get('duration_years'))} | source {f.get('source')}")
        lines.append(f"    \"{f.get('quote')}\"")
    if not use:
        lines.append("(none)")
    bad = [f for f in facts if not f.get("usable")]
    counts = {}
    for f in bad:
        counts[reason_code(f)] = counts.get(reason_code(f), 0) + 1
    lines += ["", "UNUSABLE FACTS: " + (f"{len(bad)} (not shown; they cannot be cited). Reason codes: " + ", ".join(f"{k} {counts[k]}" for k in sorted(counts)) if bad else "none")]
    if d.get("withheld_from_stage2"):
        lines.append(f"FACTS WITHHELD FROM THIS STAGE: {d['withheld_from_stage2']} (they quote analyst, consensus or price content, or a number this stage must not see; they cannot be cited).")
    return "\n".join(lines)


def render_bar(bar):
    b = bar or {}
    lines = ["X-BASIS MARGIN HISTORY (X-basis margin, net income plus after-tax amortization, over revenue):" if b.get("basis") == "x"
             else "FILED OPERATING MARGIN HISTORY (filed operating margin, operating income / revenue):"]
    yrs = b.get("years") or b.get("by_year")
    if isinstance(yrs, dict):
        yrs = [{"fy": k, "op_margin": v} for k, v in yrs.items()]
    for y in yrs or []:
        if isinstance(y, dict):
            m = y.get("op_margin", y.get("margin"))
            lines.append(f"  FY{y.get('fy', y.get('year'))}: {_p(m)}" if _num(m) else f"  FY{y.get('fy', y.get('year'))}: not filed")
    lines.append("  Statistics over the filed window (the baselines you can choose): " + ", ".join(f"{k} {_p(b.get(k))}" for k in rf.BASELINES))
    return "\n".join(lines)


def render_forecast_numbers(fc):
    """The forecast's numbers only: the reason text of the normalized state (stage 2's reasoning) is never shown."""
    out = [f"Discount rate {_p(fc.get('discount_rate'), 2)}, frame {fc.get('frame')}"]
    b = fc["scenarios"]["Base"]
    if all(isinstance(b.get(k), dict) for k in LABEL_ENUMS):
        out.append("Base classifications: " + "; ".join(f"{LABEL_WORDS[k]} {b[k]['label']} (facts {', '.join(b[k].get('fact_ids') or []) or 'none'})" for k in LABEL_ENUMS))
    for name in SCEN:
        s = fc["scenarios"][name]
        nt, nm = s["near_term"], s["normalized"]
        out += [f"{name} (probability {_p(s['prob'], 1)}):",
                f"  near term: revenue growth {', '.join(_p(x, 2) for x in nt['rev_growth'])}; operating margin {', '.join(_p(x, 2) for x in nt['op_margin'])}; facts {', '.join(nt.get('fact_ids') or []) or 'none'}",
                f"  normalized by year {nm['year']}: revenue growth {_p(nm['rev_growth'], 2)}; margin = baseline {nm['baseline']} + {nm['delta_pts']:g} percentage points; facts {', '.join(nm.get('fact_ids') or []) or 'none'}",
                f"  transition {s['transition']}" + (f" at year {s['transition_year']}" if s.get("transition_year") is not None else ""),
                f"  long-run operating margin {_p(s['long_run_margin_op'], 2)}; terminal growth {_p(s['terminal_g'], 2)}; terminal return on new investment {_p(s['terminal_ronic'], 2)}; fade {s['fade_years']} years"
                + (f"; long-run facts {', '.join(s['long_run_fact_ids'])}" if s.get("long_run_fact_ids") else "")
                + ("; the forecast states that no fact matches the duration of the long run" if s.get("no_duration_matched_evidence") else "")]
    return "\n".join(out)


def path_rows(vf, name):
    """[{year, revenue, rev_growth, op_margin, x_margin}] of one scenario of a value_forecast result (x_margin None when the bridge did not give it)."""
    sp = ((vf or {}).get("scenarios") or {}).get(name) or {}
    years = ((sp.get("path") or {}).get("years")) or []
    bridge = {r["year"]: r for r in ((sp.get("bridge") or {}).get("rows") or [])}
    return [{"year": y["year"], "revenue": y["revenue"], "rev_growth": y["rev_growth"], "op_margin": y["op_margin"],
             "x_margin": (bridge.get(y["year"]) or {}).get("x_margin")} for y in years]


def render_desk_result(vf, price, forecast=None):
    vals = vf.get("values") or {}
    lines = ["DESK RESULT of this forecast (code-computed):"]
    for n in SCEN:
        p = forecast["scenarios"][n]["prob"] if forecast else None
        lines.append(f"  {n} value per share ${vals.get(n):.2f}" + (f" (probability {_p(p)})" if p is not None else "") if _num(vals.get(n)) else f"  {n} value per share: not computed")
    for n in SCEN:
        rows = path_rows(vf, n)
        if not rows:
            continue
        lines.append(f"{n} path (year: revenue growth / filed operating margin / valuation-basis margin):")
        lines += [f"  year {r['year']}: {_p(r['rev_growth'])} / {_p(r['op_margin'])} / {_p(r['x_margin'])}" for r in rows]
        nm = ((vf.get("scenarios") or {}).get(n) or {}).get("path", {}).get("normalized") or {}
        if _num(nm.get("value")):
            lines.append(f"  normalized operating margin = {nm.get('baseline')} {_p(nm.get('baseline_value'), 2)} + {_p(nm.get('delta'), 2)} = {_p(nm.get('value'), 2)}")
    b = ((vf.get("scenarios") or {}).get("Base") or {}).get("bridge") or {}
    if b.get("assumptions"):
        lines.append("Conversion assumptions: " + "; ".join(b["assumptions"]))
    return "\n".join(lines)


def render_sample_values(values, median_index, spread):
    parts = [f"sample {i + 1}: " + (f"${v:.2f}" if _num(v) else "dropped") for i, v in enumerate(values)]
    return ("BASE VALUES OF THE THREE STAGE-2 SAMPLES: " + "; ".join(parts) + (f". The forecast shown is sample {median_index + 1}, the median." if median_index is not None else "")
            + (f" Spread (max - min) / median: {_p(spread)}." if _num(spread) else ""))


def render_price(price):
    return f"MARKET PRICE: ${price:.2f} per share."


PRICE_DERIVED_CLASSES = ("price", "market_cap", "multiple", "price_action")        # r26_blind's removed classes that come from the price; never consensus, price_target or reference


def revealed_price_context(facts):
    """The lines the blind pack removed as price-derived (r26_blind's removed-line list, facts["r26_blind_source"]["removed_lines"]), grouped by the section they came from,
    as the "REVEALED: price and momentum" block of stages 3 and 4. The consensus classes are not here: they reach stage 3 only through consensus_corrected. None when the
    facts hold no removed-line list."""
    src = (facts or {}).get("r26_blind_source")
    if not isinstance(src, dict) or not isinstance(src.get("removed_lines"), list):
        return None
    out, seen = ["REVEALED: price and momentum (the price-derived lines of the data pack, withheld from stages 1 and 2):"], None
    for r in src["removed_lines"]:
        if isinstance(r, dict) and r.get("cls") in PRICE_DERIVED_CLASSES and str(r.get("text") or "").strip():
            if r.get("section") != seen:
                seen = r.get("section")
                out.append(f"[{seen}]")
            out.append(str(r["text"]))
    return "\n".join(out) if len(out) > 1 else "REVEALED: price and momentum: the pack held no price-derived line."


def render_price_implied(pi_lines):
    return "PRICE-IMPLIED INPUTS (the value of each judgment input at which the Base would equal the price, others held; [yours] is the forecast's own):\n" + "\n".join(
        f"  {x}" for x in (pi_lines or ["not computed"]))


def render_consensus(cm):
    """`cm` is consensus_view()'s dict."""
    if cm.get("status") != "ok":
        return f"BASIS-CORRECTED CONSENSUS: not comparable ({cm.get('reason')}). No consensus margin is shown."
    lines = ["BASIS-CORRECTED CONSENSUS (the analysts' EPS scaled to the filed base-year EPS, as a margin on the consensus revenue):"]
    for y, r in sorted(cm["years"].items()):
        lines.append(f"  year {y}: valuation-basis margin {_p(r.get('x'), 2)}" + (f"; filed operating margin equivalent {_p(r.get('op'), 2)}" if _num(r.get("op")) else "; operating equivalent not available"))
    return "\n".join(lines)


def render_diagnostics(dg):
    lines = ["DIAGNOSTICS:"]
    alts = dg.get("alt_paths") or []
    if not alts:
        lines.append("  Alternative paths: none (no cited fact has a finite duration).")
    for a in alts:
        v = a.get("value")
        val = f"${v:.2f}" if _num(v) else f"not computed ({a.get('status')})"
        if a.get("label") == rf.EARLY_FADE_STRESS:
            lines.append(f"  Early-fade stress: the evidence of {a['fact_id']} speaks for {a['duration_years']:g} years, beyond the five explicit years; if the margin instead faded to its baseline from year 5, the Base value per share is {val}"
                         + (f" ({'; '.join(a['stamps'])})" if a.get("stamps") else "") + ". This is a stress; it replaces nothing.")
            continue
        lines.append(f"  If the evidence of {a['fact_id']} (speaks for {a['duration_years']:g} years) expires, the Base value per share is {val}"
                     + (f" ({'; '.join(a['stamps'])})" if a.get("stamps") else "") + ". This is reported; it replaces nothing.")
    for c in dg.get("consensus_divergence") or []:
        lines.append(f"  Year {c['year']}: the forecast's filed operating margin {_p(c['forecast_op'], 2)}; the consensus equivalent {_p(c['consensus_op'], 2)}; gap {c['gap_pts']:+.2f} percentage points.")
    if dg.get("consensus_divergence") is None:
        lines.append("  Consensus divergence: not available (no comparable consensus).")
    for s in dg.get("stamps") or []:
        lines.append(f"  Stamp: {s}")
    return "\n".join(lines)


# ---------------------------------------------------------------- the consensus adapter

def _year_map(v):
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            try:
                out[int(str(k).lstrip("yY"))] = x
            except ValueError:
                continue
        return out
    if isinstance(v, (list, tuple)):
        return {i + 1: x for i, x in enumerate(v)}
    return {}


def consensus_view(cc, bridge_facts):
    """R26-B's `consensus_corrected` (SPEC section 5) as the stages read it: {"status": "ok" | "not_comparable" | "unavailable", "reason", "years": {year: {"x", "op",
    "revenue"}}}. ASSUMED SHAPE (R26-B has not merged; confirm at integration): a dict with `status` (or `comparable`), `reason`, `x_margins` (a list for years 1.. or a
    {year: margin} dict, decimals on the valuation basis), optionally `revenue` (same shape, the consensus revenue), optionally `op_margins` (the operating-basis equivalent;
    `pending_bridge` or absent means code inverts the bridge here with the consensus revenue, tools/r26_forecast.invert_bridge)."""
    if not isinstance(cc, dict) or not cc:
        return {"status": "unavailable", "reason": "no consensus_corrected in the facts", "years": {}}
    st = str(cc.get("status") or "")
    if "not_comparable" in st or cc.get("comparable") is False or cc.get("consensus_not_comparable"):
        return {"status": "not_comparable", "reason": cc.get("reason") or cc.get("consensus_not_comparable") or "consensus_not_comparable", "years": {}}
    xs, rev = _year_map(cc.get("x_margins") or cc.get("x_margin")), _year_map(cc.get("revenue"))
    ops = _year_map(cc.get("op_margins")) if not isinstance(cc.get("op_margins"), str) else {}
    # R26-B's shape (r26_blind.consensus_corrected): the revenue is years.<y>.revenue_b ($B, the unit of the bridge facts) and the operating equivalent is operating_basis.values.<y>.op_margin
    for k, yv in _year_map(cc.get("years")).items():
        if isinstance(yv, dict) and _num(yv.get("revenue_b")) and k not in rev:
            rev[k] = float(yv["revenue_b"])
    ob = cc.get("operating_basis") if isinstance(cc.get("operating_basis"), dict) else {}
    if ob.get("status") == "inverted":
        for k, inv in _year_map(ob.get("values")).items():
            if isinstance(inv, dict) and inv.get("status") == rf.BRIDGE_OK and _num(inv.get("op_margin")) and k not in ops:
                ops[k] = inv["op_margin"]
    years = {}
    for y, x in sorted(xs.items()):
        if not _num(x):
            continue
        op = ops.get(y)
        if not _num(op) and _num(rev.get(y)):
            inv = rf.invert_bridge(float(x), y, bridge_facts or {}, revenue=float(rev[y]))
            op = inv["op_margin"] if inv["status"] == rf.BRIDGE_OK else None
        years[y] = {"x": float(x), "op": float(op) if _num(op) else None, "revenue": float(rev[y]) if _num(rev.get(y)) else None}
    if not years:
        return {"status": "unavailable", "reason": "consensus_corrected holds no X-basis margin", "years": {}}
    return {"status": "ok", "reason": None, "years": years}


# ---------------------------------------------------------------- the frozen table

def table_rows(*, price, values, forecast, vf, verdict, pre_base=None, spread=None):
    """[{"label", "value", "kind", "group"}] of the frozen final desk table. `values` {Base, Bull, Bear} per share, `forecast` the final forecast, `vf` its
    value_forecast result, `verdict` the code's word (undervalued, overvalued, hold or no_call)."""
    rows = []

    def add(label, value, kind, group):
        rows.append({"label": label, "value": value, "kind": kind, "group": group})

    add("Verdict", verdict, "word", "Verdict")
    add("Price", price, "usd", "Valuation")
    for n in SCEN:
        add(f"{n} value per share", values.get(n), "usd", "Valuation")
    for n in SCEN:
        add(f"{n} probability", forecast["scenarios"][n]["prob"], "pct", "Valuation")
    if _num(values.get("Base")) and _num(price) and price > 0:
        add("Margin of safety", values["Base"] / price - 1.0, "pct", "Valuation")
    if _num(pre_base):
        add("Pre-reveal Base value per share", pre_base, "usd", "Valuation")
    if _num(spread):
        add("Stage-2 spread", spread, "pct", "Valuation")
    add("Discount rate", forecast.get("discount_rate"), "pct", "Valuation")
    for n in SCEN:
        s = forecast["scenarios"][n]
        sp = (vf.get("scenarios") or {}).get(n) or {}
        for r in path_rows(vf, n):
            add(f"{n} revenue growth year {r['year']}", r["rev_growth"], "pct", n)
            add(f"{n} operating margin year {r['year']}", r["op_margin"], "pct", n)
            if _num(r.get("x_margin")):
                add(f"{n} valuation-basis margin year {r['year']}", r["x_margin"], "pct", n)
        nm = (sp.get("path") or {}).get("normalized") or {}
        if _num(nm.get("value")):
            add(f"{n} normalized operating margin", nm["value"], "pct", n)
        add(f"{n} normalized year", s["normalized"]["year"], "int", n)
        add(f"{n} long-run operating margin", s["long_run_margin_op"], "pct", n)
        lr = (sp.get("long_run") or {}).get("x_margin")
        if _num(lr):
            add(f"{n} long-run valuation-basis margin", lr, "pct", n)
        add(f"{n} terminal growth", s["terminal_g"], "pct", n)
        add(f"{n} terminal return on new investment", s["terminal_ronic"], "pct", n)
        add(f"{n} fade years", s["fade_years"], "int", n)
        add(f"{n} baseline", s["normalized"]["baseline"], "enum", n)
        add(f"{n} baseline delta in percentage points", s["normalized"]["delta_pts"], "plain", n)
        add(f"{n} transition", s["transition"], "enum", n)
        if n == "Base":
            for k in LABEL_ENUMS:
                if isinstance(s.get(k), dict):
                    add(f"Base {LABEL_WORDS[k]}", s[k]["label"], "enum", n)
        if s.get("transition_year") is not None:
            add(f"{n} transition year", s["transition_year"], "int", n)
    return rows


def fmt_row(row):
    k, v = row["kind"], row["value"]
    if v is None:
        return "not computed"
    if k == "usd":
        return f"${v:,.2f}"
    if k == "pct":
        return f"{v * 100:.1f}%"
    if k == "int":
        return f"{int(v)}"
    if k == "plain":
        return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
    return str(v)


def display_decimals(row):
    return {"usd": 2, "pct": 1, "int": 0, "plain": 2}.get(row["kind"], 0)


def render_table(rows):
    out, group = ["FROZEN DESK TABLE (quote a number only under its label, written exactly as here):"], None
    for r in rows:
        if r["group"] != group:
            group = r["group"]
            out.append(f"[{group}]")
        out.append(f"{r['label']}: {fmt_row(r)}")
    return "\n".join(out)


def render_bridge_table(vf):
    out = ["CONVERSION TABLE (filed operating margin to the valuation basis, Base; each year's inputs):"]
    sp = ((vf.get("scenarios") or {}).get("Base") or {})
    br = sp.get("bridge") or {}
    for r in br.get("rows") or []:
        if r.get("identity"):
            out.append(f"  year {r['year']}: margin {_p(r['x_margin'], 2)} (financial family: no conversion)")
        else:
            out.append(f"  year {r['year']}: operating margin {_p(r['op_margin'], 2)}; less net interest, other non-operating items and acquired amortization, held at their base-year dollars,"
                       f" {_p(r['k_0_pct'], 2)} of revenue; tax rate {_p(r['tax_rate'], 1)}" + (f" (measured {_p(r['tax_rate_raw'], 1)}, clipped)" if r.get("tax_rate_clipped") else "")
                       + f"; valuation-basis margin {_p(r['x_margin'], 2)}")
    out.append("Assumptions: " + ("; ".join(br.get("assumptions") or []) or "none"))
    return "\n".join(out)


# ---------------------------------------------------------------- the memo verifier

_CONNECT = r"\s*(?::|=|\bis\b|\bof\b|\bat\b|\bwas\b|\bto\b|\bequals\b|\bstands at\b|\bwould be\b)?\s*(?:about |roughly |approximately |around |~)?"
_NUMBER_AFTER = re.compile(_CONNECT + r"([-+−]?)\s?(\$?)\s?(\d[\d,]*(?:\.\d+)?)\s?(%|x\b)?", re.I)


def _number_right_after(text, pos):
    """The number a label at `pos` is stated with: it must follow the label at once (`Label: 12.3%`, `Label of $5`, `Label is 4`), so a label word inside another
    phrase (`price-implied growth`) is not read as a statement of that label."""
    m = _NUMBER_AFTER.match(text, pos)
    if not m:
        return None
    sign, dollar, digits, unit = m.groups()
    s = digits.replace(",", "")
    dec = len(s.split(".")[1]) if "." in s else 0
    v = float(s) * (-1 if sign in ("-", "−") else 1)
    return {"value": v, "decimals": dec, "dollar": bool(dollar), "unit": unit, "text": f"{sign}{dollar}{digits}{unit or ''}", "span": (m.start(), m.end())}


def rounds_to(true_value, shown_decimals, memo_value, memo_decimals):
    """True when memo_value is true_value as the table shows it (`shown_decimals`), rounded to the memo's own decimals; a memo more precise than the table must equal it."""
    shown = Decimal(repr(float(true_value))).quantize(Decimal(1).scaleb(-shown_decimals), rounding=ROUND_HALF_UP)
    if memo_decimals >= shown_decimals:
        return abs(float(shown) - memo_value) <= 1e-9
    return abs(float(shown) - memo_value) <= 0.5 * 10 ** (-memo_decimals) + 1e-9


_VERDICT_WORDS = re.compile(r"\b(no[ _-]call|undervalued|overvalued|fairly valued|fair|hold)\b", re.I)
_VERDICT_LINE = re.compile(r"(?im)^[#>*_`\s-]*verdict\b")


def _verdict_word(memo):
    """The verdict word the memo states, as the code's label words (undervalued, overvalued, hold, no_call; fair and fairly valued read as hold), else None.
    The memo's head is everything before the line that opens SECTION 1 (4000 characters at most). In it, a line that starts with `Verdict` (markdown emphasis, heading marks, quotes or a
    list dash before it, a colon or a dash after it, any case) is the statement: the first verdict word within 120 characters after it. Wherever SECTION 0 is, or whether it is headed at all,
    that line is read. Without such a line, a headed SECTION 0 is read as before: the first verdict word within 120 characters after the word `verdict` in it, else its first verdict word."""
    text = memo or ""
    end1 = re.search(r"(?im)^[#*>\s]*SECTION\s+1\b", text)
    head = (text[:end1.start()] if end1 else text)[:4000]
    hit = None
    for m in _VERDICT_LINE.finditer(head):
        hit = _VERDICT_WORDS.search(head[m.end():m.end() + 120])
        if hit:
            break
    if hit is None:
        m = re.search(r"(?im)^[#*>\s]*SECTION\s+0\b", head)
        if m is None:
            return None
        sec = head[m.end():]
        v = re.search(r"verdict", sec, re.I)
        hit = _VERDICT_WORDS.search(sec[v.end():v.end() + 120]) if v else None
        hit = hit or _VERDICT_WORDS.search(sec)
    if hit is None:
        return None
    w = hit.group(1).lower().replace(" ", "_").replace("-", "_")
    return "hold" if w in ("fair", "fairly_valued") else w


# ---- the prose-number check (cross-check 23, item 13) --------------------------------------------------------------------------------------------

_PROSE_NUMBER = re.compile(r"(?<![\w.])(?P<sign>[-+\u2212])?\s?(?P<dollar>\$)?\s?(?P<num>\d[\d,]*(?:\.\d+)?)(?:\s?(?P<unit>%|bps?\b|x\b))?", re.I)
_SCALE_POWERS = (-12, -9, -6, -3, 0, 3, 6, 9, 12)


def _prose_allowed(rows, facts, memo_text, cited_ids):
    """The numbers a memo may state in prose: every value of the frozen table (a percentage also as its fraction and in basis points), and every number of the facts the
    forecast cites or the memo names by id (the fact's value and each number written in its quote)."""
    allowed = []
    for r in rows:
        v = r.get("value")
        if r.get("kind") == "word" or not _num(v):
            continue
        allowed.append(float(v))
        if r.get("kind") == "pct":
            allowed += [float(v) * 100.0, float(v) * 10000.0]
    named = set(re.findall(r"\bF\d+\b", memo_text or "")) | set(cited_ids or ())
    for f in facts or []:
        if not (isinstance(f, dict) and f.get("fact_id") in named):
            continue
        if _num(f.get("value")):
            allowed.append(float(f["value"]))
        for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", str(f.get("quote") or "")):
            try:
                allowed.append(float(m.group(0).replace(",", "")))
            except ValueError:
                continue
    return allowed


def _prose_matches(a, v, decimals):
    """The memo's number v (as written, `decimals` places) is the allowed number a, within the rounding of what the memo wrote, at any power of a thousand (5200 in millions
    is 5.2 billion; the unit word is not read)."""
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(a * 10.0 ** k - v) <= tol for k in _SCALE_POWERS)


def _numbers_in(texts):
    """Every number written in `texts`, as a float, at the precision it is written (a comma-grouped number is read whole)."""
    out = []
    for t in texts or ():
        for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", str(t)):
            try:
                out.append(float(m.group(0).replace(",", "")))
            except ValueError:
                continue
    return out


def prose_number_mismatches(memo, rows, facts=None, cited_ids=(), skip_spans=(), input_texts=()):
    """[{"flag": "memo_prose_number_mismatch", "memo": the number as written, "context": the words around it}] for every number the memo writes with a %, a $, an x or bps
    that is neither in the table nor a number of a cited or named fact, nor a number written in any of `input_texts` (every input stage 4 was given: ruling 2026-10-19). A number with no mark (a year, a date, a count) is not read. A number inside `skip_spans` (a labelled
    number the label check already compared) is left to that check."""
    text = memo or ""
    allowed = _prose_allowed(rows, facts, text, cited_ids) + _numbers_in(input_texts)
    out = []
    for m in _PROSE_NUMBER.finditer(text):
        if not (m.group("dollar") or m.group("unit")):
            continue
        if any(a <= m.start("num") < b for a, b in skip_spans):
            continue
        s_ = m.group("num").replace(",", "")
        dec = len(s_.split(".")[1]) if "." in s_ else 0
        v = float(s_)
        if not any(_prose_matches(a, v, dec) for a in allowed):
            lo, hi = max(0, m.start() - 40), min(len(text), m.end() + 20)
            out.append({"flag": "memo_prose_number_mismatch", "memo": m.group(0).strip(), "context": text[lo:hi].replace("\n", " ")})
    return out


def verify_memo(memo, rows, facts=None, cited_ids=(), input_texts=()):
    """{"flags": [...], "annotations": [...], "details": [{"flag", "label", "memo", "table"}]}. `flags` are the three labelled checks (they gate); `annotations` is the prose-number
    check (item 13), which reports and does not gate. `facts` are the dossier's facts and `cited_ids` the ids the final forecast cites: the numbers a memo may state besides the
    table's. Nothing is changed."""
    text = memo or ""
    details = []
    checked = []
    labels = sorted((r for r in rows if r["kind"] != "word"), key=lambda r: -len(r["label"]))
    low = text.lower()
    taken = [False] * len(text)
    spans = []                                          # (start, end, row)
    for r in labels:
        lab = r["label"].lower()
        i = low.find(lab)
        while i != -1:
            if not any(taken[i:i + len(lab)]):
                for k in range(i, i + len(lab)):
                    taken[k] = True
                spans.append((i, i + len(lab), r))
            i = low.find(lab, i + 1)
    for s, e, r in sorted(spans):
        if r["value"] is None:
            continue
        if r["kind"] == "enum":
            allowed = {"baseline": rf.BASELINES, "transition": rf.TRANSITIONS, **{LABEL_WORDS[k].split()[-1]: v for k, v in LABEL_ENUMS.items()}}[r["label"].split()[-1]]
            m = re.compile(_CONNECT + r"(" + "|".join(sorted(allowed, key=len, reverse=True)) + r")(?![\w])", re.I).match(text, e)
            if m and m.group(1).lower() != str(r["value"]).lower():
                details.append({"flag": "memo_forecast_mismatch", "label": r["label"], "memo": m.group(1), "table": r["value"]})
            continue
        n = _number_right_after(text, e)
        if n is None:
            continue
        checked.append(n["span"])
        cand = [(r["value"] * 100.0, display_decimals(r))] if r["kind"] == "pct" else [(float(r["value"]), display_decimals(r))]
        if r["kind"] == "pct" and not n["unit"]:
            cand.append((float(r["value"]), 3))                       # a fraction written without the % sign
        if not any(rounds_to(tv, td, n["value"], n["decimals"]) for tv, td in cand):
            details.append({"flag": "memo_number_mismatch", "label": r["label"], "memo": n["text"], "table": fmt_row(r)})
    vr = next((r for r in rows if r["kind"] == "word"), None)
    if vr is not None:
        w = _verdict_word(text)
        if w is None or w != vr["value"]:
            details.append({"flag": "memo_verdict_mismatch", "label": "Verdict", "memo": w, "table": vr["value"]})
    flags = [f for f in MEMO_FLAGS if any(d["flag"] == f for d in details)]
    prose = prose_number_mismatches(text, rows, facts, cited_ids, checked, input_texts)
    return {"flags": flags, "annotations": ["memo_prose_number_mismatch"] if prose else [], "details": details + prose}


# ---------------------------------------------------------------- the stage-4 contract text

TEXT_FIELDS = ("catalysts", "cycle_evidence", "normalization_reason", "margin_persistence_evidence", "cycle_position_evidence", "growth_trajectory_evidence", "momentum_view", "entry_timing", "position_basis", "momentum_evidence", "momentum_flip_condition",
               "momentum_break_rule", "invalidation_rules", "thesis_invalidation_trigger")
# the model-written fields that carry a number of its own (a threshold, a window): not valuation results, never in the table, recorded apart in final.json
MODEL_TYPED_NUMBERS = ("momentum_flip_condition", "momentum_break_rule", "invalidation_rules", "catalysts")
# contract fields that stay unfilled in arm r26: numeric, with no code source in the frozen table (reported, ruling needed)
UNFILLED_NUMERIC = ("conviction_score", "business_quality_moat", "reentry_tranches")


def parse_contract_text(report):
    """(memo text before the contract block, {text field: value} from the block, problem or None). Only TEXT_FIELDS are kept; any other key is dropped (the numbers are code's)."""
    m = re.search(r"```json:underwriting\s*(\{.*?\})\s*```", report or "", re.S)
    if not m:
        return (report or "").strip(), {}, "contract_block_missing"
    memo = (report[:m.start()]).strip()
    try:
        d = json.loads(m.group(1))
    except ValueError:
        return memo, {}, "contract_block_not_json"
    return memo, {k: d[k] for k in TEXT_FIELDS if k in d and d[k] is not None}, None
