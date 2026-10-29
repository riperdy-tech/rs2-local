"""contract.py - the output contract `m3m.analysis.v2` and its citation checks (SPEC_m3m_qwen_pipeline.md section 5; v2 adds the
`material_events` task, SPEC_m3n_event_validation.md section 3).

This module is the single owner of `m3m.analysis.v2`. A field the model sends that is not listed here is dropped from the stored
analysis and the drop is logged in the task's `dropped_fields`; model text that is kept is never edited.

THE SHAPE (a hand-written validator, no dependency). Per task the model returns
    {"task": <the task id asked>, "claims": [claim, ...], "unknowns": [str, ...]}
and a claim is
    {"claim": str, "fact_ids": [str], "quotes": [str], "numbers": [str | number], "confidence_basis": str,
     "mechanism"?: str | null, "horizon"?: str | null, "counter"?: str | null}
plus, for `risks`, "risk_type" (RISK_TYPES); for `thesis_change`, "point" (the prior point's id) and "change_type" (CHANGE_TYPES); for
`unresolved_questions`, "settled_by" (the document that would settle the question); for `material_events`, "event_type" (EVENT_TYPES),
"status" (EVENT_STATUSES) and "occurred_on" (the date as an item prints it, or "not stated"; any string). A missing field, a wrong
type or value (an `event_type` or `status` outside its list, like a `risk_type`), an unknown task id or a task id other than the one
asked is a shape error; so is an empty reply (no claims and no unknowns, ruling 4.1) and, for `thesis_change`, a `point` that is not
one of the earlier point ids given (ruling 4.3; with none given, every point is unknown). Any shape error makes the task `malformed`.
The earlier points no claim addresses are recorded as `points_not_addressed`. A `material_events` reply with no claims and one
unknowns line (no event in the evidence) is a valid reply.

THE CHECKS, per claim, recorded beside it as `support` (the first failing check in the order below, else `supported`) and
`support_failures` (every failure with its detail):
    unknown_fact_id    a cited id is not an evidence item of the packet
    no_citation        `fact_ids` is empty
    quote_not_found    a quote is not a substring of a cited item's text after NORMALISATION (below); an empty quote, or one that
                       holds an omission marker, is never found
    number_not_found   an entry of `numbers` is not printed by a cited item under the NUMBER RULE (below); an entry with no number in it
                       is never found
    number_not_listed  a number of the claim text (every number the claim-side reader reads, decorated or not, except an all-digit ticker,
                       and a YEAR as defined below) is not listed in `numbers`. Every number counts, small ones too: "grew 12%" with 12%
                       printed nowhere must never be `supported` (audit 2026-10-29)

NORMALISATION of quotes (quote and item text alike): Unicode NFKC; the curly and low single quotes and the prime become ', the curly
and low double quotes and the double prime become "; every run of whitespace becomes one space; leading and trailing space removed.
Case, dashes and all other punctuation are kept.

THE FIGURE READER is this module's own (ruling 1.1; sec_primary's reader is not used or edited). Every text, item and model text alike,
first loses its omission markers ("[… 1,234 characters omitted …]", in either spelling of the ellipsis; ruling 1.4), is NFKC-normalised,
and has "percent" / "per cent" after a number written as %. Every number is then read as (value, currency, unit):
    value     thousands separators removed, compared as an exact decimal (65 = 65.0). A sign or parentheses is not read (magnitudes are
              compared; ruling 1.6 is a NOTE: `supported` certifies presence, not meaning).
    currency  $ (also US$ and USD), C$ / CAD, A$ / AUD, any other one to three capital letters glued to $ (HK$, S$, NT$, R$: each its own),
              euro / EUR, pound / GBP, the signs yen, won and rupee (each its own), and the ISO codes CHF JPY CNY (RMB is CNY) SEK NOK DKK
              KRW HKD SGD INR BRL MXN ZAR TWD ILS PLN CZK TRY (ruling 1.2; codes in capitals only, so the word "try" is not a currency).
    unit      k (thousand, k), m (million, mn, mm, m), bn (billion, bn, b), tn (trillion, tn, and a capital T glued to the number, as in
              "$10.6T"), % (and percent), x (x or the multiplication sign: a multiple), bp (bp, bps, basis point), pp (pp, ppt, percentage
              point). A plural scale word is read as its singular (ruling 1.1). Any other word after a number is not a unit.
    ranges    in "a-b", "a–b" and "a to b", a lower bound with no unit takes the upper bound's unit, and its currency when it has none
              ("8-10%" is 8% and 10%; "$4.60-$4.64 billion" is $4.60bn and $4.64bn; ruling 1.3), in items and model text alike; a
              lower bound that is a year by its form ("in 2026 to 15.1%") takes nothing (M-LIVE 2026-10-29).
Two readers differ only in what may stand before a number. The ITEM reader (cited item text) reads no number right after a letter, a
digit, "," or ".". The CLAIM-SIDE reader (the claim text and the `numbers` entries, the model's own text) also reads a number after "."
or "," that is not inside a number ("approx.99%", "est.$999 million"; ruling 1.2). Neither reads a number glued to letters (H100, Q3,
FY26, F1). Reading more of the model's text can only add figures that must be found or listed, so it can only fail a claim.

NUMBER RULE. A wanted figure (v, c, u) is matched by a printed figure (v2, c2, u2) when
    - the wanted currency, if any, is the printed one (c2 == c); a wanted figure with no currency matches a printed one with or
      without a currency (smoke run 2026-10-29: tables print "$ 11,291"); a currency WORD after the number (dollars, euros, pounds
      sterling, yen) is that currency, so "1.2 billion dollars" is not found in "€1.2 billion"; and
    - the units are equal and v2 == v, or both u and u2 are scale units (k, m, bn, tn) and v x scale(u) == v2 x scale(u2).
A bare figure (no currency, no unit) therefore matches only a bare figure (ruling 1.1). So "$1.2 billion" is found in "$1,200 million",
"US$1.2 billion" and "$0.0012 trillion"; it is NOT found in "1.2 billion" or "€1.2 billion" (the currency differs), nor in a bare
"1,200" of prose, nor in "$1.23 billion". A heading's scale is read only in a statement item, under THE STATEMENT RULE.

THE STATEMENT RULE (M-LIVE 2026-10-29). A statement item (kind "statement") is a FilingSummary R report whose first line declares its
currency and scale: "... - USD ($) shares in Millions, $ in Millions | Jun. 30, 2026 | ...". Every figure of a value cell printed with no
unit, and with no currency or the declared one, is also read with the declared currency and, on a money row, the declared scale; a
per-share row ("(in dollars per share)", "(USD per share)") takes the currency only; a share row ("(in shares)", "(shares)") takes the
share scale only; a row ending in another "(in ...)" and the row labels and period cells take nothing (statement_figures). So in a
"$ in Millions" balance sheet the cell "11,291" is found as "11,291", "$11,291", "$11,291 million" and "$11.291 billion", and never as
"$11,291 billion" or "$11,291 thousand"; "$4.98 million" is never found on a per-share row. A `numbers` entry with no unit that a
cited statement reads this way lists every reading of that cell, so a listed "$ 11,291" lists the claim's "$11,291 million". "15.4%" is
not found in a bare "15.4", and a bare "15.4" is not found in "15.4%", "15.4x" or "$15.4". "$10.6 trillion" is not found in
"$10.6 million". The same predicate decides whether a number of the claim text is listed in `numbers`.

A YEAR of the claim text need not be listed (ruling 1.5) only when all hold: it is a bare token of exactly four digits with no comma and
no decimal, 1900-2100; it is directly preceded (by spaces or one hyphen) by a year word: in, fiscal, FY, year, since, by, through, until,
from, during, of, ended, ending, end, before, after, early, late, mid, a month's full name, Q1-Q4, H1, H2, quarter, half, due, or by an earlier year of a list or range of years that is so
preceded ("in 2023, 2024 and 2025", "in 2032-2036"); and a cited
item prints the same four digits as a bare token with no comma. "closed 2025 stores" and "2,025" are not years.
A DATE of the claim text ("June 30, 2026", "Jun. 30, 2026", "30 June 2026", "30 Jun 2026") that a cited item prints as the same month,
day and year, in any of those forms, exempts its day and year from listing (dated_spans).

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

CONTRACT = "m3m.analysis.v2"     # v2 2026-10-29: the material_events task and its event_type, status and occurred_on (3N)
TASK_IDS = ("business_model", "financial_health", "competitive_position", "growth_thesis", "risks", "thesis_change",
            "unresolved_questions", "material_events")
# PROTOCOL_factor_ai_m2_2026-10-23.md section 6, the event types of the ground-truth register ("liquidity/contract rupture" is two
# types here), plus `other`.
RISK_TYPES = ("guidance_withdrawal", "bankruptcy", "delisting", "restatement", "liquidity_rupture", "contract_rupture",
              "regulatory_action", "thesis_break", "other")
CHANGE_TYPES = ("unchanged", "changed", "unknown", "unsupported")
# SPEC_m3n_event_validation.md section 3: the twelve event types of `material_events`, and whether the event has occurred or is announced
EVENT_TYPES = ("bankruptcy_or_restructuring", "going_concern_doubt", "restatement_or_non_reliance", "delisting_notice",
               "acquisition_of_the_company", "contract_loss", "guidance_withdrawal", "debt_default_or_acceleration",
               "material_impairment", "auditor_change", "trading_halt", "other_material_event")
EVENT_STATUSES = ("occurred", "announced_pending")
SUPPORT_ORDER = ("unknown_fact_id", "no_citation", "quote_not_found", "number_not_found", "number_not_listed")
SUPPORTED = "supported"

TASK_FIELDS = ("task", "claims", "unknowns")
CLAIM_REQUIRED = {"claim": "str", "fact_ids": "list_str", "quotes": "list_str", "numbers": "list_num", "confidence_basis": "str"}
CLAIM_OPTIONAL = {"mechanism": "opt_str", "horizon": "opt_str", "counter": "opt_str"}
TASK_EXTRA = {
    "risks": {"risk_type": "risk_type"},
    "thesis_change": {"point": "str", "change_type": "change_type"},
    "unresolved_questions": {"settled_by": "str"},
    "material_events": {"event_type": "event_type", "status": "event_status", "occurred_on": "str"},
}
SCALE = {"k": Decimal(10) ** 3, "m": Decimal(10) ** 6, "bn": Decimal(10) ** 9, "tn": Decimal(10) ** 12}
YEAR_WORDS = ("in", "fiscal", "fy", "year", "since", "by", "through", "until", "from", "during", "of", "ended", "ending", "end",
              "before", "after", "early", "late", "mid", "january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december", "q1", "q2", "q3", "q4", "h1", "h2", "quarter", "half", "due")


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
    if kind == "event_type":
        return isinstance(v, str) and v in EVENT_TYPES
    if kind == "event_status":
        return isinstance(v, str) and v in EVENT_STATUSES
    raise ValueError(kind)


def validate(task_id, obj, point_ids=None):
    """(kept, errors, dropped): the model's object restricted to the fields this contract owns (values unedited), the shape errors
    (empty when the shape is right) and the paths of the fields dropped. `point_ids` are the earlier point ids a `thesis_change` reply
    may name (None is no points)."""
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
            if task_id == "thesis_change" and "point" in kc and kc["point"] not in (point_ids or ()):
                errors.append(f"claims[{i}].point {kc['point']!r} is not one of the earlier points "
                              f"({', '.join(point_ids or ()) or 'none'})")
            kept_claims.append(kc)
    if not errors and claims_in == [] and obj["unknowns"] == []:
        errors.append("the reply has no claims and no unknowns")
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
_OMIT_NFKC = re.compile(r"\[\.\.\. [\d,]+ characters omitted \.\.\.\]")       # sec_primary.OMIT_RE after NFKC wrote "…" as "..."

_CUR = (r"(?:(?-i:[A-Z]{1,3})\$|[$€£¥₩₹]|(?-i:USD|EUR|GBP|CAD|AUD|CHF|JPY|CNY|RMB|SEK|NOK|DKK|KRW|HKD|SGD"
        r"|INR|BRL|MXN|ZAR|TWD|ILS|PLN|CZK|TRY))\s?")
_UNIT = (r"(?:\s?%|\s?(?:percentage[ -]points?|basis[ -]points?|trillions?|billions?|millions?|thousands?|ppts?|pp|bps|bp|tn|bn|mn|mm"
         r"|[mkbx×])(?![A-Za-z0-9])|(?-i:T)(?![A-Za-z0-9]))")
_BODY = r"(" + _CUR + r")?(\d[\d,]*(?:\.\d+)?)(" + _UNIT + r")?"
_ITEM_RE = re.compile(r"(?<![A-Za-z0-9,.])" + _BODY, re.I)
_CLAIM_RE = re.compile(r"(?<![A-Za-z0-9])(?<!\d[.,])" + _BODY, re.I)
_RANGE_GAP = re.compile(r"\s?[-–]\s?|\s+to\s+", re.I)
_CUR_CANON = {"US$": "$", "$": "$", "USD": "$", "CAD": "C$", "AUD": "A$", "€": "€", "EUR": "€", "£": "£",
              "GBP": "£", "RMB": "CNY"}
_UNIT_CANON = {"%": "%", "thousand": "k", "k": "k", "million": "m", "mn": "m", "mm": "m", "m": "m", "billion": "bn", "bn": "bn",
               "b": "bn", "trillion": "tn", "tn": "tn", "t": "tn", "x": "x", "×": "x", "bp": "bp", "bps": "bp",
               "basis point": "bp", "pp": "pp", "ppt": "pp", "percentage point": "pp"}
_CUR_WORD = re.compile(r"\s+(dollars?|euros?|pounds?\s+sterling|yen)\b", re.I)    # smoke run 2026-10-29: "1.2 billion dollars"
_CUR_WORDS = {"dollar": "$", "euro": "€", "pounds sterling": "£", "pound sterling": "£", "yen": "¥"}
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
_MONTH_NO = {**{m: i for i, m in enumerate(_MONTHS, 1)}, **{m[:3]: i for i, m in enumerate(_MONTHS, 1)}, "sept": 9}
_MONTH = r"(" + "|".join(_MONTHS + ("sept", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec")) + r")\.?"
_DATE = re.compile(r"(?<![A-Za-z])" + _MONTH + r"\s+(\d{1,2}),?\s+(\d{4})(?!\d)", re.I)          # June 30, 2026 / Jun. 30, 2026
_DATE_DMY = re.compile(r"(?<![A-Za-z0-9])(\d{1,2})\s+" + _MONTH + r",?\s+(\d{4})(?!\d)", re.I)    # 31 Dec 2025 (M-LIVE, CMRE)
_YEAR_BEFORE = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(YEAR_WORDS) + r")(?:\s+|-)"
                          r"(?:\d{4}(?:,\s*|,?\s+(?:and|or|to)\s+|\s?[-–]\s?))*$", re.I)     # a list or range of years continues


def norm_figure_text(text):
    """The text figures are read from: omission markers removed (ruling 1.4), NFKC, and "percent" / "per cent" after a number as %."""
    s = unicodedata.normalize("NFKC", sec_primary.OMIT_RE.sub(" ", text or ""))
    return _PERCENT_WORD.sub(r"\1%", _OMIT_NFKC.sub(" ", s))


def _unit_canon(s):
    s = re.sub(r"[\s-]+", " ", (s or "").strip())
    if s == "T":
        return "tn"
    s = s.lower()
    if s.endswith("s") and s not in ("bps",):
        s = s[:-1]                                      # a plural scale word is its singular: millions -> million, ppts -> ppt
    return _UNIT_CANON[s] if s else ""


def read_figures(text, claim_side=False):
    """[(value Decimal, currency, unit, digits as printed, the text before the number)] of a text, in order (THE FIGURE READER)."""
    s = norm_figure_text(text)
    out = []
    for m in (_CLAIM_RE if claim_side else _ITEM_RE).finditer(s):
        core = m.group(2).rstrip(",")
        try:
            v = Decimal(core.replace(",", "")).normalize()
        except InvalidOperation:
            continue
        cur = (m.group(1) or "").strip()
        if not cur:
            w = _CUR_WORD.match(s, m.end())
            cur = _CUR_WORDS[w.group(1).lower().rstrip("s")] if w else ""
        out.append([v, _CUR_CANON.get(cur, cur), _unit_canon(m.group(3)), core, s[:m.start(2)], m.start(), m.end()])
    for i in range(len(out) - 2, -1, -1):              # a range's lower bound takes the upper bound's unit (and currency, if it has none)
        lo, hi = out[i], out[i + 1]
        if not lo[2] and hi[2] and _RANGE_GAP.fullmatch(s[lo[6]:hi[5]]) and _year_of(lo) is None:
            lo[2] = hi[2]
            lo[1] = lo[1] or hi[1]
    return [tuple(f) for f in out]


def figures_of(text, claim_side=False):
    """{(value Decimal, currency, unit)} of a text: the item reader, or the claim-side reader for the model's own text."""
    return {f[:3] for f in read_figures(text, claim_side)}


def _year_of(f):
    """The four digits of a figure that is a year by its own form (YEAR rule, less the cited-item condition), else None."""
    v, c, u, core, before = f[:5]
    if c or u or not re.fullmatch(r"\d{4}", core) or not 1900 <= v <= 2100 or not _YEAR_BEFORE.search(before):
        return None
    return core


def printed_years(texts):
    """The bare four-digit tokens with no comma that the item texts print."""
    return {f[3] for t in texts for f in read_figures(t) if not f[1] and not f[2] and re.fullmatch(r"\d{4}", f[3])}


def _dates(text):
    """[((month number, day, year), start, end)] of the dates of a normalised text, in either order and with either month form."""
    out = [((_MONTH_NO[m.group(1).lower()], int(m.group(2)), m.group(3)), m.start(), m.end()) for m in _DATE.finditer(text)]
    out += [((_MONTH_NO[m.group(2).lower()], int(m.group(1)), m.group(3)), m.start(), m.end()) for m in _DATE_DMY.finditer(text)]
    return out


def dated_spans(claim_text, cited):
    """The (start, end) spans, in the normalised claim text, of the dates that a cited item prints as the same month, day and year,
    whatever the month's form or the order ("June 30, 2026" in the claim is "Jun. 30, 2026" in an R-file column head; smoke run and
    M-LIVE 2026-10-29). A date no cited item prints is not exempt."""
    printed = {k for t in cited for k, _, _ in _dates(norm_figure_text(t))}
    return [(a, b) for k, a, b in _dates(norm_figure_text(claim_text)) if k in printed]


_STMT_HEAD = re.compile(r" - ([A-Z]{3}) \([^()|]*\)((?:,?\s*\S+ in (?:Thousands|Millions|Billions))*)\s*(?:\||$)")
_STMT_SCALE = re.compile(r"(\S+) in (Thousands|Millions|Billions)")
_STMT_SCALE_UNIT = {"Thousands": "k", "Millions": "m", "Billions": "bn"}
_ROW_PER_SHARE = re.compile(r"\((?:in )?[^()]*per share\)\s*$", re.I)
_ROW_SHARES = re.compile(r"\((?:in )?shares\)\s*$", re.I)
_ROW_OTHER_UNIT = re.compile(r"\(in [^()]*\)\s*$", re.I)
_PERIOD_CELL = re.compile(r"\s*(?:\d+ Months Ended|" + _MONTH + r"\s+\d{1,2},?\s+\d{4})\s*", re.I)


def statement_heading(text):
    """(currency, money scale unit, share scale unit) that the first line of a FilingSummary R report declares, as in
    "Consolidated Balance Sheets - USD ($) shares in Millions, $ in Millions | Jun. 30, 2026 | ...", else None."""
    m = _STMT_HEAD.search((text or "").split("\n", 1)[0])
    if not m:
        return None
    money = shares = ""
    for who, scale in _STMT_SCALE.findall(m.group(2)):
        if who.lower() == "shares":
            shares = _STMT_SCALE_UNIT[scale]
        else:
            money = _STMT_SCALE_UNIT[scale]
    return _CUR_CANON.get(m.group(1), m.group(1)), money, shares


def statement_figures(text):
    """The figures a statement item states once its heading is read (THE STATEMENT RULE, M-LIVE 2026-10-29): every figure of a value
    cell (not the row label, not a period cell) printed with no unit, and with no currency or the declared one, is also read with the
    declared currency, and, on a money row, with the declared scale. A row whose label ends "(in ... per share)" or "(USD per share)"
    takes the currency only; a row ending "(in shares)" or "(shares)" takes the share scale only, with no currency; a row ending in any
    other "(in ...)" takes nothing. The literal figures are kept as read."""
    head = statement_heading(text)
    if head is None:
        return set()
    cur, money, shares = head
    out = set()
    for line in text.split("\n")[1:]:
        cells = line.split(" | ")
        if len(cells) < 2:
            continue
        label = cells[0]
        per_share, share_row = bool(_ROW_PER_SHARE.search(label)), bool(_ROW_SHARES.search(label))
        if not per_share and not share_row and _ROW_OTHER_UNIT.search(label):
            continue
        for cell in cells[1:]:
            if _PERIOD_CELL.fullmatch(cell):
                continue
            for v, c, u, *_ in read_figures(cell):
                if u or c not in ("", cur):
                    continue
                if share_row:
                    if shares:
                        out.add((v, "", shares))
                    continue
                out.add((v, cur, ""))
                if money and not per_share:
                    out.add((v, cur, money))
    return out


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
    if u2 == u:
        return v2 == v
    return u in SCALE and u2 in SCALE and v * SCALE[u] == v2 * SCALE[u2]


def figure_found(want, figures):
    return any(fig_matches(want, h) for h in figures)


# ---------------------------------------------------------------- the claim checks

def check_claim(claim, items, ticker=None, statements=()):
    """{"support", "support_failures"} for one kept claim; `items` is {fact_id: text} of the packet; `statements` are the fact ids
    whose items are statements (kind "statement"), read under THE STATEMENT RULE as well."""
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
    cited_figs, stmt_figs = set(), set()
    for i in ids:
        if i in items:
            cited_figs |= figures_of(items[i])
            if i in statements:
                stmt_figs |= statement_figures(items[i])
    cited_figs |= stmt_figs
    listed = set()
    for x in claim["numbers"]:
        s = entry_text(x)
        figs = figures_of(s, claim_side=True)
        listed |= figs
        if not figs:
            failures.append({"check": "number_not_found", "detail": f"{s!r}: no number in the entry"})
            continue
        missing = [f for f in figs if not figure_found(f, cited_figs)]
        if missing:
            failures.append({"check": "number_not_found", "detail": s})
    listed |= {h for h in stmt_figs if any(not u and v == h[0] and c in ("", h[1]) for v, c, u in listed)}    # THE STATEMENT RULE
    tk = Decimal(ticker).normalize() if ticker and str(ticker).isdigit() else None
    years = printed_years(cited)
    dates = dated_spans(claim["claim"], cited)
    must = set()
    for f in read_figures(claim["claim"], claim_side=True):     # per occurrence: "in 2025" does not exempt "closed 2025 stores"
        if (not f[1] and not f[2] and f[0] == tk) or (_year_of(f) is not None and _year_of(f) in years):
            continue
        if not f[1] and not f[2] and any(a <= f[5] < b for a, b in dates):     # by start: "2026," ends after the date
            continue
        must.add(f[:3])
    for f in sorted(must, key=str):
        v, c, u = f
        if not figure_found(f, listed):
            failures.append({"check": "number_not_listed", "detail": f"{c or ''}{format(v, 'f')}{u or ''}"})
    support = next((k for k in SUPPORT_ORDER if any(f["check"] == k for f in failures)), SUPPORTED)
    return {"support": support, "support_failures": failures}


def evidence_texts(packet):
    """{fact_id: text} of the packet's evidence items."""
    return {e["fact_id"]: e.get("text") or "" for e in packet.get("evidence") or []}


def check_task(task_id, obj, packet, point_ids=None):
    """The stored record of one task's reply: {"status": "ok" | "malformed", "shape_errors", "dropped_fields", "claims", "unknowns",
    "support_counts"}, plus "points_not_addressed" for `thesis_change`. Each kept claim carries `support` and `support_failures` beside
    the model's own fields. `point_ids` are the earlier point ids of a `thesis_change` task."""
    kept, errors, dropped = validate(task_id, obj, point_ids)
    if errors:
        return {"status": "malformed", "shape_errors": errors, "dropped_fields": dropped, "claims": [], "unknowns": [],
                "support_counts": {}}
    items = evidence_texts(packet)
    statements = {e["fact_id"] for e in packet.get("evidence") or [] if e.get("kind") == "statement"}
    claims, counts = [], {}
    for c in kept["claims"]:
        chk = check_claim(c, items, packet.get("ticker"), statements)
        claims.append({**c, **chk})
        counts[chk["support"]] = counts.get(chk["support"], 0) + 1
    out = {"status": "ok", "shape_errors": [], "dropped_fields": dropped, "claims": claims, "unknowns": kept["unknowns"],
           "support_counts": counts}
    if task_id == "thesis_change":
        named = {c["point"] for c in kept["claims"]}
        out["points_not_addressed"] = [p for p in (point_ids or ()) if p not in named]
    return out
