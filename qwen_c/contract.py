"""contract.py - the output contract `m3m.analysis.v1` and its citation checks (SPEC_m3m_qwen_pipeline.md section 5).

This module is the single owner of `m3m.analysis.v1`. A field the model sends that is not listed here is dropped from the stored
analysis and the drop is logged in the task's `dropped_fields`; model text that is kept is never edited.

THE SHAPE (a hand-written validator, no dependency). Per task the model returns
    {"task": <the task id asked>, "claims": [claim, ...], "unknowns": [str, ...]}
and a claim is
    {"claim": str, "fact_ids": [str], "quotes": [str], "numbers": [str | number], "confidence_basis": str,
     "mechanism"?: str | null, "horizon"?: str | null, "counter"?: str | null}
plus, for `risks`, "risk_type" (RISK_TYPES); for `thesis_change`, "point" (the prior point's id) and "change_type" (CHANGE_TYPES); for
`unresolved_questions`, "settled_by" (the document that would settle the question). A missing field, a wrong type, an unknown task id or
a task id other than the one asked is a shape error; any shape error makes the task `malformed`.

THE CHECKS, per claim, recorded beside it as `support` (the first failing check in the order below, else `supported`) and
`support_failures` (every failure with its detail):
    unknown_fact_id    a cited id is not an evidence item of the packet
    no_citation        `fact_ids` is empty
    quote_not_found    a quote is not a substring of a cited item's text after NORMALISATION (below); an empty quote, or one that
                       holds an omission marker, is never found
    number_not_found   an entry of `numbers` is not printed by a cited item under the NUMBER RULE (below); an entry with no number in it
                       is never found
    number_not_listed  a number of the claim text (every number `figures_of` reads, decorated or not, except an all-digit ticker, and a bare
                       year 1900-2100 that a cited item prints) is not listed in `numbers`. Every number counts, small ones too: "grew 12%" with 12% printed
                       nowhere must never be `supported` (audit 2026-10-29)

NORMALISATION of quotes (quote and item text alike): Unicode NFKC; the curly and low single quotes and the prime become ', the curly
and low double quotes and the double prime become "; every run of whitespace becomes one space; leading and trailing space removed.
Case, dashes and all other punctuation are kept.

NUMBER RULE. Text is NFKC-normalised and "percent" / "per cent" after a number is read as %, then every number in it is read with sec_primary's figure reader (`item_figures`) as
(value, currency, unit): thousands separators removed, value compared as an exact decimal (65 = 65.0), currency $ / C$ / A$ / euro /
pound (US$ and USD are $), unit k / m / bn (thousand, million, billion and their short forms) or %. A sign or parentheses is not read
(magnitudes are compared). A wanted figure (v, c, u) is matched by a printed figure (v2, c2, u2) when
    - the wanted currency, if any, is the printed one (c2 == c); and
    - either v2 == v and (the wanted figure has no unit or u2 == u),
      or both u and u2 are scale words (k, m, bn) and v x scale(u) == v2 x scale(u2).
So "1.2 billion" is found in "1,200 million" and in "$1.2 billion"; it is NOT found in a bare "1,200" (even under a table heading
"$ in Millions": a scale stated only in a heading is not read), nor in "1.23 billion", "1.2%" or "1.2". "15.4%" is not found in a
bare "15.4"; a bare "15.4" is found in "15.4%". "$1.2 billion" is not found in "1.2 billion" (the currency is not printed there).
The same predicate decides whether a number of the claim text is listed in `numbers` (every number, not only sec_primary figure tokens).

An unsupported claim stays visible with its reason. Nothing downstream may read a claim whose `support` is not `supported` as a
verified value (non-negotiable 3).
"""
import re
import sys
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[1])
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import sec_primary  # noqa: E402

CONTRACT = "m3m.analysis.v1"
TASK_IDS = ("business_model", "financial_health", "competitive_position", "growth_thesis", "risks", "thesis_change",
            "unresolved_questions")
# PROTOCOL_factor_ai_m2_2026-10-23.md section 6, the event types of the ground-truth register ("liquidity/contract rupture" is two
# types here), plus `other`.
RISK_TYPES = ("guidance_withdrawal", "bankruptcy", "delisting", "restatement", "liquidity_rupture", "contract_rupture",
              "regulatory_action", "thesis_break", "other")
CHANGE_TYPES = ("unchanged", "changed", "unknown", "unsupported")
SUPPORT_ORDER = ("unknown_fact_id", "no_citation", "quote_not_found", "number_not_found", "number_not_listed")
SUPPORTED = "supported"

TASK_FIELDS = ("task", "claims", "unknowns")
CLAIM_REQUIRED = {"claim": "str", "fact_ids": "list_str", "quotes": "list_str", "numbers": "list_num", "confidence_basis": "str"}
CLAIM_OPTIONAL = {"mechanism": "opt_str", "horizon": "opt_str", "counter": "opt_str"}
TASK_EXTRA = {
    "risks": {"risk_type": "risk_type"},
    "thesis_change": {"point": "str", "change_type": "change_type"},
    "unresolved_questions": {"settled_by": "str"},
}
SCALE = {"k": Decimal(10) ** 3, "m": Decimal(10) ** 6, "bn": Decimal(10) ** 9}


# ---------------------------------------------------------------- the shape

def _type_ok(kind, v):
    if kind == "str":
        return isinstance(v, str)
    if kind == "opt_str":
        return v is None or isinstance(v, str)
    if kind == "list_str":
        return isinstance(v, list) and all(isinstance(x, str) for x in v)
    if kind == "list_num":
        return isinstance(v, list) and all(isinstance(x, str) or (isinstance(x, (int, float)) and not isinstance(x, bool)) for x in v)
    if kind == "risk_type":
        return isinstance(v, str) and v in RISK_TYPES
    if kind == "change_type":
        return isinstance(v, str) and v in CHANGE_TYPES
    raise ValueError(kind)


def validate(task_id, obj):
    """(kept, errors, dropped): the model's object restricted to the fields this contract owns (values unedited), the shape errors
    (empty when the shape is right) and the paths of the fields dropped."""
    errors, dropped = [], []
    if task_id not in TASK_IDS:
        return None, [f"unknown task id {task_id!r}"], dropped
    if not isinstance(obj, dict):
        return None, [f"the reply is a {type(obj).__name__}, not an object"], dropped
    for k in obj:
        if k not in TASK_FIELDS:
            dropped.append(k)
    t = obj.get("task")
    if "task" not in obj:
        errors.append("missing field task")
    elif not isinstance(t, str):
        errors.append("task is not a string")
    elif t not in TASK_IDS:
        errors.append(f"unknown task id {t!r}")
    elif t != task_id:
        errors.append(f"task is {t!r}, the task asked was {task_id!r}")
    if "unknowns" not in obj:
        errors.append("missing field unknowns")
    elif not _type_ok("list_str", obj["unknowns"]):
        errors.append("unknowns is not a list of strings")
    claims_in = obj.get("claims")
    kept_claims = []
    if "claims" not in obj:
        errors.append("missing field claims")
    elif not isinstance(claims_in, list):
        errors.append("claims is not a list")
    else:
        spec = {**CLAIM_REQUIRED, **TASK_EXTRA.get(task_id, {})}
        for i, c in enumerate(claims_in):
            if not isinstance(c, dict):
                errors.append(f"claims[{i}] is not an object")
                continue
            kc = {}
            for f, kind in spec.items():
                if f not in c:
                    errors.append(f"claims[{i}] missing field {f}")
                elif not _type_ok(kind, c[f]):
                    errors.append(f"claims[{i}].{f} has a wrong type or value")
                else:
                    kc[f] = c[f]
            for f, kind in CLAIM_OPTIONAL.items():
                if f in c:
                    if _type_ok(kind, c[f]):
                        kc[f] = c[f]
                    else:
                        errors.append(f"claims[{i}].{f} has a wrong type")
            for f in c:
                if f not in spec and f not in CLAIM_OPTIONAL:
                    dropped.append(f"claims[{i}].{f}")
            kept_claims.append(kc)
    if errors:
        return None, errors, dropped
    return {"task": t, "claims": kept_claims, "unknowns": list(obj["unknowns"])}, [], dropped


# ---------------------------------------------------------------- quotes

_SQ = dict.fromkeys(map(ord, "‘’‚‛′"), "'")
_DQ = dict.fromkeys(map(ord, "“”„‟″"), '"')


def norm_quote_text(s):
    s = unicodedata.normalize("NFKC", s or "").translate(_SQ).translate(_DQ)
    return re.sub(r"\s+", " ", s).strip()


def quote_found(quote, texts):
    q = norm_quote_text(quote)
    if not q or sec_primary.OMIT_RE.search(quote or "") or sec_primary.OMIT_RE.search(q.replace("...", "…")):
        return False                                    # NFKC writes the marker's ellipsis as "...": both spellings are refused
    return any(q in norm_quote_text(t) for t in texts)


# ---------------------------------------------------------------- numbers

_PERCENT_WORD = re.compile(r"(\d)\s*(?:percent|per cent)\b", re.I)


def norm_figure_text(text):
    """NFKC, and the words "percent" / "per cent" right after a number written as %."""
    return _PERCENT_WORD.sub(r"\1%", unicodedata.normalize("NFKC", text or ""))


def figures_of(text):
    """{(value Decimal, currency, unit)} printed by a text (sec_primary.item_figures over norm_figure_text)."""
    return sec_primary.item_figures(norm_figure_text(text))


def entry_text(x):
    """A `numbers` entry as text: a JSON number is written in plain decimal form (1200.0 -> "1200.0", 1e-05 -> "0.00001")."""
    if isinstance(x, str):
        return x
    try:
        return format(Decimal(repr(x)), "f")
    except InvalidOperation:
        return ""


def fig_matches(want, have):
    v, c, u = want
    v2, c2, u2 = have
    if c and c2 != c:
        return False
    if v2 == v and (not u or u2 == u):
        return True
    return u in SCALE and u2 in SCALE and v * SCALE[u] == v2 * SCALE[u2]


def figure_found(want, figures):
    return any(fig_matches(want, h) for h in figures)


# ---------------------------------------------------------------- the claim checks

def check_claim(claim, items, ticker=None):
    """{"support", "support_failures"} for one kept claim; `items` is {fact_id: text} of the packet."""
    failures = []
    ids = claim["fact_ids"]
    unknown = [i for i in ids if i not in items]
    for i in unknown:
        failures.append({"check": "unknown_fact_id", "detail": i})
    if not ids:
        failures.append({"check": "no_citation", "detail": "fact_ids is empty"})
    cited = [items[i] for i in ids if i in items]
    for q in claim["quotes"]:
        if not quote_found(q, cited):
            failures.append({"check": "quote_not_found", "detail": q})
    cited_figs = set()
    for t in cited:
        cited_figs |= figures_of(t)
    listed = set()
    for x in claim["numbers"]:
        s = entry_text(x)
        figs = figures_of(s)
        listed |= figs
        if not figs:
            failures.append({"check": "number_not_found", "detail": f"{s!r}: no number in the entry"})
            continue
        missing = [f for f in figs if not figure_found(f, cited_figs)]
        if missing:
            failures.append({"check": "number_not_found", "detail": s})
    tk = Decimal(ticker).normalize() if ticker and str(ticker).isdigit() else None
    for f in sorted(figures_of(claim["claim"]), key=str):
        v, c, u = f
        if not c and not u and (v == tk or (v == v.to_integral_value() and 1900 <= v <= 2100 and figure_found(f, cited_figs))):
            continue                                    # a year is exempt only when a cited item prints it ("Cash was 2,034" is not)
        if not figure_found(f, listed):
            failures.append({"check": "number_not_listed", "detail": f"{v}{u or ''} {c or ''}".strip()})
    support = next((k for k in SUPPORT_ORDER if any(f["check"] == k for f in failures)), SUPPORTED)
    return {"support": support, "support_failures": failures}


def evidence_texts(packet):
    """{fact_id: text} of the packet's evidence items."""
    return {e["fact_id"]: e.get("text") or "" for e in packet.get("evidence") or []}


def check_task(task_id, obj, packet):
    """The stored record of one task's reply: {"status": "ok" | "malformed", "shape_errors", "dropped_fields", "claims", "unknowns",
    "support_counts"}. Each kept claim carries `support` and `support_failures` beside the model's own fields."""
    kept, errors, dropped = validate(task_id, obj)
    if errors:
        return {"status": "malformed", "shape_errors": errors, "dropped_fields": dropped, "claims": [], "unknowns": [],
                "support_counts": {}}
    items = evidence_texts(packet)
    claims, counts = [], {}
    for c in kept["claims"]:
        chk = check_claim(c, items, packet.get("ticker"))
        claims.append({**c, **chk})
        counts[chk["support"]] = counts.get(chk["support"], 0) + 1
    return {"status": "ok", "shape_errors": [], "dropped_fields": dropped, "claims": claims, "unknowns": kept["unknowns"],
            "support_counts": counts}
