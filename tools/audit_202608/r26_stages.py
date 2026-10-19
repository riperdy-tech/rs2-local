"""r26_stages.py - the staged analyst of revision 26 (SPEC_rev26_staged_analyst.md): four separate model sessions joined only by artifacts.

    stage1  research and the fact ledger      -> dossier.json     (built here: brief R26-A1)
    stage2  the blind forecast, K = 3 samples -> forecasts.json   (brief R26-A2, on R26-C's functions)
    stage3  reveal and reconcile, one revision-> reveal.json      (brief R26-A2)
    stage4  the memorandum                    -> final.json       (brief R26-A2)

Every stage starts from a FRESH message list built only from the artifacts the SPEC names for it (ALLOWED_INPUTS; `fresh_messages` refuses any
other); no stage reads another stage's messages, reasoning or tool results. The artifacts are written under the run directory. Every model turn of
every stage is logged by the ollama_raw provider under <run_dir>/turns/<stage>_<n>.json (turn_log.py; SPEC section 0).

STAGE 1
-------
The session sees the blind pack (the pack without its valuation TASK), the tools search_web, fetch_page and register_facts, and the stage-1 TASK. It
researches, registers facts (each with the exact quote it rests on) and ends with register_facts(done=true, research_summary=...). Code checks every
fact and ANNOTATES it (SPEC section 1); nothing is deleted:

  quote            `quote_verified` when the quote occurs in its source after NORMALIZATION (below), else `quote_not_found`.
  proximity        every content word of `metric` and of `entity` must occur within +-300 characters of the quote's place in the source, else
                   `metric_not_near_quote` naming the missing words. When the quote occurs more than once, the occurrence with the fewest missing
                   words counts. Content words: letters-only tokens of at least 4 letters, lower-cased, not in STOPWORDS, a plural -s/-ies folded.
  value            `value_in_quote` when a number written in the quote equals `value` in the same written form (WRITTEN FORMS below), else
                   `value_not_in_quote`; `value_null` when the fact carries no value.
  association      (cross-check 23, item 5) a fact that carries a value must pass a stronger test or it is `association_uncertain`, which is not usable:
                   the value is written in the quote, and then, for PROSE, the registered metric is the nearest metric term to the value within the value's sentence
                   of the quote (METRIC_VOCABULARY); for a TABLE ROW (the quote's source line holds two or more `|`) the table's header row and the row's label are added to
                   the window the proximity check reads. A fact with no value has nothing to associate.
  usable           a fact is usable iff it is well-formed, `quote_verified`, not `metric_not_near_quote` and not `association_uncertain`. The others stay in the dossier,
                   with the reason; later stages are told only their number and reason codes (r26_late.render_dossier), never the facts.
  incomplete       the dossier is marked `incomplete` (with the cause) when the session ended without an accepted register_facts(done=true).

NORMALIZATION (applied to the quote and to the source alike; the quote is found in the normalized source and mapped back to the source's own
character positions for the proximity window): Unicode NFKC; case folded; every whitespace character dropped (HTML-stripped pages put spaces where
tags were: "$ 274.4" and "$274.4" are the same text); the markdown marks * and ` dropped; the curly single quotes and primes become ', the curly double
quotes become ", every dash variant (hyphen, non-breaking hyphen, en dash, em dash, minus sign) becomes -. All other punctuation is KEPT, so 1.5 never
equals 15. For a pack source the "> " that opens each line of a quoted filing is removed first.

WRITTEN FORMS of a value: the quote's number tokens are read as [sign] [$] digits[,digits][.digits] [unit word], the sign being a leading - or minus sign,
or parentheses; a unit word scales the token (thousand/k 1e3, million/mm/mn/m 1e6, billion/bn/b 1e9, trillion/tn/t 1e12; % and percent do not scale). The value is
in the quote when it equals a token or a token times its own scale, compared as exact decimals. 12.5 matches "12.5%" and "$12.5 million"; 12500000 matches "$12.5 million"; it does not match "0.125", "125", "-12.5" or "12,500 thousand".

SOURCES a fact may cite: `pack:<section id>`, `page:<url>` (a page this session fetched), `query:Q<n>` (the n-th tool call, a search this session ran;
its text is the results it returned: title, url, snippet). A pack section id is the slug of a pack heading: see pack_sections().
"""
import copy
import hashlib
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
from decimal import Decimal, InvalidOperation
from pathlib import Path

_AUDIT_DIR = str(Path(__file__).resolve().parent)
if _AUDIT_DIR not in sys.path:
    sys.path.insert(0, _AUDIT_DIR)
_REPO = str(Path(__file__).resolve().parents[2])
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
_TOOLS = str(Path(__file__).resolve().parents[1])
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import analyst_tools  # noqa: E402
import llm_provider  # noqa: E402
import r26_blind  # noqa: E402
import r26_forecast as rf  # noqa: E402
import r26_late  # noqa: E402
import sec_primary  # noqa: E402
import turn_log  # noqa: E402

PACK_REVISION_R26 = 26
ARM = "r26"
STAGES = ("stage1", "stage2", "stage3", "stage4")
ARTIFACTS = {"stage1": "dossier.json", "stage2": "forecasts.json", "stage3": "reveal.json", "stage4": "final.json"}

# What each stage may be handed (SPEC sections 1-4). `fresh_messages` refuses any other name, so a stage cannot be given another stage's reasoning.
ALLOWED_INPUTS = {
    "stage1": {"blind_pack", "task"},
    "stage2": {"blind_pack", "dossier", "op_margin_bar", "task"},
    "stage3": {"dossier", "median_forecast", "median_desk_result", "base_values", "price", "revealed_price_context", "price_implied_inputs", "consensus_corrected",
               "diagnostics", "task"},
    "stage4": {"dossier", "revealed_price_context", "frozen_desk_result", "bridge_table", "crux", "crux_verification", "stage2_spread", "diagnostics", "task"},
}

QUOTE_MAX_CHARS = 400
PROXIMITY_CHARS = 300
SUMMARY_MAX_WORDS = 600
BASIS_VALUES = ("filed_gaap", "company_adjusted", "third_party", "n/a")
FACT_FIELDS = ("fact_id", "source", "quote", "entity", "metric", "period", "value", "unit", "basis", "duration_years")
SOURCE_RE = re.compile(r"^(pack|page|query):(\S.*)$", re.S)

# English function words plus the corporate-form words every company name carries; no industry term, no company term.
STOPWORDS = frozenset("""
about above after again against all also and any are because been before being below between both but can could did does doing down during each
few for from further had has have having her here hers him his how into its itself just more most other our ours out over own same she should
some such than that the their theirs them then there these they this those through too under until upon very was were what when where which while
who whom why will with would you your yours
corporation company companies incorporated limited holdings holding group inc corp
""".split())


# ---------------------------------------------------------------- the pack's section ids

_HEADING = re.compile(r"^(#{2,3}) +(.+?) *$")
_ITEM = re.compile(r"^\[P(\d+)\]")


def slug(text):
    """lower case; every run of characters other than a-z, 0-9 and the dot becomes one hyphen; no leading or trailing hyphen."""
    return re.sub(r"[^a-z0-9.]+", "-", (text or "").lower()).strip("-.")


def strip_quote_marks(text):
    """The "> " that opens each line of a quoted filing in the pack."""
    return re.sub(r"(?m)^> ?", "", text)


def pack_sections(pack_text):
    """{section id: text} for a pack. A pack section opens at a line `## ...` or `### ...` whose title (the heading up to its first " - ", " [" or
    two spaces) has no lower-case letter: `## DATA 5 - FISCAL-YEAR ...` -> `data-5`, `### DATA 6A - ...` -> `data-6a`, `## GUIDANCE & CONSENSUS   [...]` ->
    `guidance-consensus`, `## PRIMARY SOURCES   [...]` -> `primary-sources`, `## DEFAULTS` -> `defaults`. The headings of the research brief inside DATA 11
    (`## Competitive Position & Moat`) have lower-case letters, so they are not sections: the brief is part of `data-11`. A section's text runs to the
    next section heading of the same or a higher level (a `###` section is inside its `##` parent as well). A repeated id gets -2, -3. Each filing item
    `[P1]` .. `[Pn]` of PRIMARY SOURCES is also a section: `primary-p1` .. `primary-pn`. Ids are lower case; `section_id()` slugs a model's spelling."""
    lines = (pack_text or "").split("\n")
    heads = []                                  # (line index, level, id)
    seen = {}
    for i, ln in enumerate(lines):
        m = _HEADING.match(ln)
        if not m:
            continue
        title = re.split(r" - | \[|  ", m.group(2), maxsplit=1)[0].strip()
        if not re.search(r"[A-Za-z]", title) or title != title.upper():
            continue
        sid = slug(title)
        if not sid:
            continue
        seen[sid] = seen.get(sid, 0) + 1
        if seen[sid] > 1:
            sid = f"{sid}-{seen[sid]}"
        heads.append((i, len(m.group(1)), sid))
    out = {}
    for k, (i, level, sid) in enumerate(heads):
        end = len(lines)
        for j, lv, _ in heads[k + 1:]:
            if lv <= level:
                end = j
                break
        out[sid] = "\n".join(lines[i:end])
    prim = out.get("primary-sources")
    if prim is not None:
        plines = prim.split("\n")
        starts = [(i, int(m.group(1))) for i, ln in enumerate(plines) for m in [_ITEM.match(ln)] if m]
        for k, (i, n) in enumerate(starts):
            j = starts[k + 1][0] if k + 1 < len(starts) else len(plines)
            out.setdefault(f"primary-p{n}", "\n".join(plines[i:j]))
    return out


def section_id(text):
    """The id a model's spelling of a section means: `DATA 5`, `data-5`, `PRIMARY P1` -> data-5, data-5, primary-p1."""
    return slug(text)


TASK_SEPARATOR = "\n\n---\n\nYou are underwriting this company"


def split_task(pack):
    """(pack without its valuation TASK, True) when `pack` ends with the TASK block of the revision-24 family (the separator line and the TASK's first
    sentence), whatever follows the TASK (the research addendum) included; else (pack, False)."""
    k = pack.rfind(TASK_SEPARATOR)
    if k < 0:
        return pack, False
    return pack[:k], True


# ---------------------------------------------------------------- normalization and the three fact checks

_CHARMAP = {}
for _c in "‘’‚‛′´":
    _CHARMAP[_c] = "'"
for _c in "“”„‟″":
    _CHARMAP[_c] = '"'
for _c in "‐‑‒–—―−﹣－":
    _CHARMAP[_c] = "-"
_DROPPED = frozenset("*`​‌‍⁠﻿")


def normalize_with_map(text):
    """(normalized text, positions): the NORMALIZATION of the module docstring, and for each normalized character the index of the source character it came from."""
    out, pos = [], []
    for i, ch in enumerate(text or ""):
        for c in unicodedata.normalize("NFKC", ch):
            if c.isspace() or c in _DROPPED:
                continue
            c = _CHARMAP.get(c, c)
            for c2 in c.casefold():
                out.append(c2)
                pos.append(i)
    return "".join(out), pos


def normalize(text):
    return normalize_with_map(text)[0]


def find_quote(source, quote, limit=50):
    """[(start, end)] character spans of `source` (the source's own indexes) where the normalized quote occurs in the normalized source."""
    nq = normalize(quote)
    if not nq:
        return []
    ns, pos = normalize_with_map(source)
    spans, k = [], ns.find(nq)
    while k >= 0 and len(spans) < limit:
        spans.append((pos[k], pos[k + len(nq) - 1] + 1))
        k = ns.find(nq, k + 1)
    return spans


def _stem(w):
    if w.endswith("ies") and len(w) > 5:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 4:
        return w[:-1]
    return w


def content_word_forms(text):
    """{folded form: the word as written (lower case)} for the letters-only tokens of at least 4 letters that are not stopwords; plurals fold (-s, -ies)."""
    return {_stem(w): w for w in (t.lower() for t in re.findall(r"[^\W\d_]+", text or "")) if len(w) >= 4 and w not in STOPWORDS}


def content_words(text):
    """The folded content words of `text`, a set."""
    return set(content_word_forms(text))


def _window(source, a, b, radius):
    """source[a - radius : b + radius], a word cut by either edge kept whole."""
    lo, hi = max(0, a - radius), min(len(source), b + radius)
    while 0 < lo < len(source) and source[lo].isalpha() and source[lo - 1].isalpha():
        lo -= 1
    while 0 < hi < len(source) and source[hi].isalpha() and source[hi - 1].isalpha():
        hi += 1
    return source[lo:hi]


def proximity(source, spans, entity, metric, radius=PROXIMITY_CHARS, extra=None):
    """(missing words sorted, the span used): over the quote's occurrences, the one whose window (`radius` characters each side of the quote, in the source's
    own characters) misses the fewest content words of `entity` and `metric`; the words are named as the model wrote them. No content word at all gives no
    missing word (nothing to look for). `extra(a, b)`, when given, is more text added to that occurrence's window (a table's header row and row label: item 5)."""
    need = {**content_word_forms(entity), **content_word_forms(metric)}
    best = None
    for a, b in spans:
        have = content_words(_window(source, a, b, radius) + ((" " + extra(a, b)) if extra is not None else ""))
        miss = sorted(need[k] for k in need if k not in have)
        if best is None or len(miss) < len(best[0]):
            best = (miss, (a, b))
        if not miss:
            break
    return best if best is not None else (sorted(need.values()), None)


_SCALES = {"thousand": Decimal(10) ** 3, "k": Decimal(10) ** 3, "million": Decimal(10) ** 6, "mm": Decimal(10) ** 6, "mn": Decimal(10) ** 6,
           "m": Decimal(10) ** 6, "billion": Decimal(10) ** 9, "bn": Decimal(10) ** 9, "b": Decimal(10) ** 9, "trillion": Decimal(10) ** 12,
           "tn": Decimal(10) ** 12, "t": Decimal(10) ** 12, "%": Decimal(1), "percent": Decimal(1)}
_NUMBER = re.compile(r"(?P<pre>[(\-−–—])?\s*\$?\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                     r"(?:\s*(?P<unit>%|(?:thousand|million|billion|trillion|percent)\b|(?:mm|mn|bn|tn|k|m|b|t)\b))?(?P<post>\))?", re.I)


def number_token_spans(quote):
    """[(Decimal value, scale Decimal, start, end)] for every number written in `quote` (signed; the scale of its unit word, 1 without one; the span is the whole token)."""
    out = []
    for m in _NUMBER.finditer(quote or ""):
        try:
            v = Decimal(m.group("num").replace(",", ""))
        except InvalidOperation:
            continue
        pre = m.group("pre")
        if pre in ("-", "−", "–", "—") or (pre == "(" and m.group("post") == ")"):
            v = -v
        unit = (m.group("unit") or "").lower()
        out.append((v, _SCALES.get(unit, Decimal(1)), m.start(), m.end()))
    return out


def number_tokens(quote):
    """[(Decimal value, scale Decimal)] for every number written in `quote` (signed; the scale of its unit word, 1 without one)."""
    return [(v, sc) for v, sc, _a, _b in number_token_spans(quote)]


def value_in_quote(value, quote):
    """True when `value` equals a number written in `quote` or that number times its unit word's scale (module docstring, WRITTEN FORMS)."""
    try:
        want = Decimal(repr(float(value))) if not isinstance(value, int) else Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return False
    return any(want == v or want == v * s for v, s in number_tokens(quote))


def _want(value):
    try:
        return Decimal(repr(float(value))) if not isinstance(value, int) else Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return None


# ---------------------------------------------------------------- the metric vocabulary and the association test (cross-check 23, item 5)

# ONE generic vocabulary of financial and operating metric terms: canonical name -> the surface forms (lower case; a trailing plural s is matched). No industry list, no company
# term. A phrase is matched longest first, so "operating income" is never read as "income". "per share", "percent" and the periods are not metric terms: they qualify one.
METRIC_VOCABULARY = {
    "revenue": ("revenue", "sales", "net sales", "turnover"),
    "operating_income": ("operating income", "operating profit", "income from operations", "operating earnings", "operating result"),
    "net_income": ("net income", "net earnings", "net profit", "net loss", "net result", "profit attributable", "income attributable"),
    "income": ("income",), "earnings": ("earnings",), "profit": ("profit",),
    "gross_profit": ("gross profit",), "ebitda": ("ebitda",), "ebit": ("ebit",),
    "eps": ("eps", "earnings per share"),
    "operating_margin": ("operating margin", "operating income margin"), "net_margin": ("net margin", "net income margin"), "gross_margin": ("gross margin",),
    "ebitda_margin": ("ebitda margin",), "margin": ("margin",),
    "free_cash_flow": ("free cash flow", "fcf"),
    "operating_cash_flow": ("operating cash flow", "ocf", "cash flow from operations", "cash from operations", "cash provided by operating activities", "cash flows from operating activities"),
    "cash_flow": ("cash flow",), "cash": ("cash", "cash and cash equivalents", "liquidity"),
    "capex": ("capex", "capital expenditure", "capital spending", "capital investment"),
    "depreciation_amortization": ("depreciation and amortization", "d&a"), "depreciation": ("depreciation",), "amortization": ("amortization",),
    "operating_expense": ("operating expense", "operating cost"), "interest_expense": ("interest expense", "finance cost"), "interest_income": ("interest income",),
    "cost_of_revenue": ("cost of revenue", "cost of sales", "cost of goods sold", "cogs"), "sga": ("sg&a", "selling, general and administrative", "general and administrative"),
    "research_development": ("research and development", "r&d"), "expense": ("expense",), "cost": ("cost",),
    "tax_rate": ("tax rate", "effective tax rate"), "tax": ("tax", "income tax"),
    "net_debt": ("net debt",), "debt": ("debt", "borrowing", "indebtedness"), "leverage": ("leverage", "gearing"),
    "assets": ("assets", "total assets"), "liabilities": ("liabilities",), "equity": ("equity", "shareholders' equity", "stockholders' equity"), "book_value": ("book value",),
    "working_capital": ("working capital",),
    "backlog": ("backlog", "orderbook", "order book", "remaining performance obligations"),
    "contract": ("contract", "charter", "agreement"),
    "customers": ("customer", "subscriber", "user", "member"),
    "price": ("price", "pricing"), "rate": ("rate",), "day_rate": ("day rate", "tce", "time charter equivalent"), "yield": ("yield",),
    "interest_rate": ("interest rate",), "discount_rate": ("discount rate", "cost of equity", "cost of capital", "wacc"),
    "volume": ("volume", "shipment", "delivery", "unit"), "production": ("production", "output", "throughput"), "capacity": ("capacity",), "utilization": ("utilization", "utilisation", "load factor"),
    "fleet": ("fleet", "vessel", "ship", "aircraft", "rig"), "locations": ("store", "location", "branch", "facility", "plant"), "employees": ("employee", "headcount"),
    "term": ("term", "tenor", "duration", "maturity", "remaining life"), "age": ("age",),
    "roic": ("roic", "return on invested capital"), "roe": ("roe", "return on equity"), "roa": ("roa", "return on assets"),
    "shares": ("share count", "shares outstanding", "shares"), "dividend": ("dividend",), "repurchase": ("repurchase", "buyback"), "payout": ("payout ratio", "payout"),
    "growth": ("growth", "cagr"), "market_share": ("market share",), "market_size": ("market size",), "coverage": ("coverage",), "ratio": ("ratio",),
    "guidance": ("guidance", "outlook"),
}
_TERM_FORMS = sorted(((form, canon) for canon, forms in METRIC_VOCABULARY.items() for form in forms), key=lambda fc: -len(fc[0]))
_TERM_RE = re.compile("(?<![a-z0-9&])(?:" + "|".join(re.escape(f) for f, _c in _TERM_FORMS) + r")(?:e?s)?(?![a-z0-9&])", re.I)
_TERM_CANON = {f: c for f, c in _TERM_FORMS}


def metric_terms(text):
    """[(canonical term, start, end)] of the vocabulary terms in `text`, longest phrase first and without overlap."""
    out = []
    for m in _TERM_RE.finditer(text or ""):
        w = m.group(0).lower()
        canon = _TERM_CANON.get(w)
        if canon is None:
            for f, c in _TERM_FORMS:
                if w.startswith(f):
                    canon = c
                    break
        if canon is not None:
            out.append((canon, m.start(), m.end()))
    return out


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[$])")


def sentence_spans(text):
    """[(start, end)] of the sentences of `text` (a break is . ! or ? followed by white space and a capital, a quote, a bracket or a $; decimals never break)."""
    spans, last = [], 0
    for m in _SENTENCE_BREAK.finditer(text or ""):
        spans.append((last, m.start()))
        last = m.end()
    spans.append((last, len(text or "")))
    return spans


def prose_association(quote, value, metric):
    """(ok, detail) for a fact in PROSE: the registered `metric` names the nearest vocabulary term to the value, within the value's sentence of the quote. The value's token is
    any number of the quote equal to `value` (value_in_quote's forms); distance is the number of characters between the token and the term (0 when they touch). The nearest term
    is the one that counts; a tie goes to the term before the number. Passes when ANY matching token passes."""
    want = _want(value)
    if want is None:
        return False, "value_not_a_number"
    toks = [(a, b) for v, sc, a, b in number_token_spans(quote) if want == v or want == v * sc]
    if not toks:
        return False, "value_not_in_quote"
    registered = {c for c, _a, _b in metric_terms(metric)}
    first = None
    for a, b in toks:
        sa, sb = next((x for x in sentence_spans(quote) if x[0] <= a < x[1] or x[0] <= a <= x[1]), (0, len(quote)))
        terms = [(c, ta + sa, tb + sa) for c, ta, tb in metric_terms(quote[sa:sb])]
        if not terms:
            res = (False, "no_metric_term_in_the_values_sentence")
        else:
            def gap(t):
                return (a - t[2]) if t[2] <= a else ((t[1] - b) if t[1] >= b else 0)
            near = min(terms, key=lambda t: (max(gap(t), 0), 0 if t[2] <= a else 1))
            if near[0] in registered:
                return True, None
            res = (False, f"nearest_metric_term_is_{near[0]}" + ("" if registered else "_and_the_registered_metric_names_no_vocabulary_term"))
        first = first or res
    return first


def table_context(source, a, b):
    """The table a quote at source[a:b] sits in: None when its source line is not a table row (fewer than two `|`), else {"row_label", "header_row", "text"}. A table is the
    unbroken run of lines holding two or more `|`; its header row is the line before the first rule line (cells of dashes) or, with no rule line, the run's first line; the row
    label is the first non-empty cell of the quote's line. `text` is both, the words added to the proximity window."""
    lines = source.split("\n")
    pos, idx = 0, None
    for i, ln in enumerate(lines):
        if pos <= a <= pos + len(ln):
            idx = i
            break
        pos += len(ln) + 1
    if idx is None or lines[idx].count("|") < 2:
        return None
    lo = idx
    while lo > 0 and lines[lo - 1].count("|") >= 2:
        lo -= 1
    hi = idx
    while hi + 1 < len(lines) and lines[hi + 1].count("|") >= 2:
        hi += 1
    block = lines[lo:hi + 1]
    rule = next((k for k, ln in enumerate(block) if re.fullmatch(r"[\s|:\-]+", ln) and "-" in ln), None)
    header = block[rule - 1] if rule is not None and rule >= 1 else block[0]
    cells = [c.strip(" \t\u200b\u200c\u200d\ufeff") for c in lines[idx].split("|")]
    label = next((c for c in cells if c), "")
    return {"row_label": label, "header_row": header, "row_line": lines[idx], "text": header + " " + label}


def _cells(line):
    cells = [c.strip(" 	​‌‍﻿") for c in line.split("|")]
    while cells and not cells[0]:
        cells.pop(0)
    while cells and not cells[-1]:
        cells.pop()
    return cells


def column_check(tctx, value, metric):
    """(ok, detail) or None - the table's column test: when the header row and the quote's row have the same number of cells, the cell that writes the value sits in a
    column whose header cell, together with the row label, must name the registered metric (by the vocabulary's terms when both name one, else by content words): a value under
    `operating income` is not a `net income` fact although both words stand in the header row. None when the cell counts differ (a filing's padded cells) or no cell writes the value: the window rule alone then decides."""
    want = _want(value)
    row, head = _cells(tctx["row_line"]), _cells(tctx["header_row"])
    if want is None or len(row) != len(head):
        return None
    idx = next((i for i, c in enumerate(row) if any(want == v or want == v * sc for v, sc in number_tokens(c))), None)
    if idx is None:
        return None
    where = head[idx] + " " + tctx["row_label"]
    reg, there = {c for c, _a, _b in metric_terms(metric)}, {c for c, _a, _b in metric_terms(where)}
    if reg and there:                                      # both name vocabulary terms: they must share one (so `net income` is not read under `operating income`)
        return (True, None) if reg & there else (False, "metric_not_in_the_values_column_or_row_label")
    have = content_words(where)
    miss = sorted(w for k, w in content_word_forms(metric).items() if k not in have)
    return (False, "metric_not_in_the_values_column_or_row_label") if miss else (True, None)


# ---------------------------------------------------------------- the facts

def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_fact_shape(f):
    """[problem, ...] for a fact object that does not have the SPEC section 1 shape; [] when it does."""
    if not isinstance(f, dict):
        return ["the fact is not an object"]
    bad = []
    for k in FACT_FIELDS:
        if k not in f:
            bad.append(f"{k} is missing")
    for k in ("fact_id", "source", "quote", "entity", "metric", "period", "unit"):
        if k in f and (not isinstance(f[k], str) or not f[k].strip()) and not (k == "unit" and f[k] == ""):
            bad.append(f"{k} must be a non-empty string")
    if "source" in f and isinstance(f["source"], str) and f["source"].strip() and not SOURCE_RE.match(f["source"].strip()):
        bad.append("source must be pack:<section id>, page:<url> or query:<query id>")
    if "value" in f and f["value"] is not None and not _is_number(f["value"]):
        bad.append("value must be a number or null")
    if "basis" in f and f["basis"] not in BASIS_VALUES:
        bad.append(f"basis must be one of {', '.join(BASIS_VALUES)}")
    if "duration_years" in f:
        d = f["duration_years"]
        if not (d is None or d == "ongoing" or (_is_number(d) and d >= 0)):
            bad.append('duration_years must be a number of years, "ongoing" or null')
    return bad


def company_words(company, ticker):
    """The folded content words of the pack company's name plus its ticker (lower case): the entity words a `pack:` fact need not find near its quote."""
    return content_words(company) | ({_stem(ticker.lower())} if ticker else set())


def check_fact(fact, source_text, waived=None):
    """The SPEC section 1 annotations of one well-formed fact against the text of its source (None when the source could not be resolved), with the association test of
    cross-check 23 item 5. Returns {"quote_status", "quote_over_400_chars", "proximity_status", "missing_words", "value_status", "table", "association_status",
    "association_detail", "usable", "unusable_reason", "unusable_code"}."""
    quote = fact["quote"]
    rec = {"quote_status": None, "quote_over_400_chars": len(quote.strip()) > QUOTE_MAX_CHARS, "proximity_status": "not_checked", "missing_words": [],
           "value_status": ("value_null" if fact["value"] is None else
                            ("value_in_quote" if value_in_quote(fact["value"], quote) else "value_not_in_quote")),
           "table": False, "association_status": "not_checked", "association_detail": None}
    spans = find_quote(source_text, quote) if source_text is not None else []
    rec["quote_status"] = "quote_verified" if spans else "quote_not_found"
    is_query = str(fact.get("source") or "").strip().lower().startswith("query:")        # a search result's `title | url | snippet` lines are not tables
    tables = {}

    def extra(a, b):
        if is_query:
            return ""
        t = tables.setdefault((a, b), table_context(source_text, a, b))
        return t["text"] if t else ""

    if spans:
        miss, used = proximity(source_text, spans, fact["entity"], fact["metric"], extra=extra)
        if waived and miss:
            # a `pack:` source: the pack is about the company, so its name tokens and ticker as ENTITY words count as satisfied (never as metric words)
            keep = {w: w for w in content_word_forms(fact["entity"]).values() if _stem(w) not in waived}
            miss2, used = proximity(source_text, spans, " ".join(keep), fact["metric"], extra=extra)
            rec["entity_from_pack_company"] = sorted(set(miss) - set(miss2))
            miss = miss2
        rec["missing_words"] = miss
        rec["proximity_status"] = "metric_not_near_quote" if miss else "near"
        tctx = None if (used is None or is_query) else tables.get(tuple(used)) or table_context(source_text, used[0], used[1])
        rec["table"] = tctx is not None
        if tctx is not None:
            rec["table_row_label"], rec["table_header_row"] = tctx["row_label"], tctx["header_row"]
        if fact["value"] is None:
            rec["association_status"] = "no_value"
        elif rec["value_status"] != "value_in_quote":
            rec["association_status"], rec["association_detail"] = "association_uncertain", "value_not_in_quote"
        elif tctx is not None:
            col = column_check(tctx, fact["value"], fact["metric"])
            rec["association_status"], rec["association_detail"] = (("association_uncertain", col[1]) if col is not None and not col[0] else
                                                                     ("associated_by_table_header_and_row_label", None))
        else:
            ok, why = prose_association(quote, fact["value"], fact["metric"])
            rec["association_status"], rec["association_detail"] = ("associated_nearest_metric_term", None) if ok else ("association_uncertain", why)
    rec["usable"] = (rec["quote_status"] == "quote_verified" and rec["proximity_status"] != "metric_not_near_quote"
                     and rec["association_status"] != "association_uncertain")
    if rec["usable"]:
        rec["unusable_reason"], rec["unusable_code"] = None, None
    elif source_text is None:
        rec["unusable_reason"], rec["unusable_code"] = "source not resolved", "source_not_resolved"
    elif rec["quote_status"] != "quote_verified":
        rec["unusable_reason"], rec["unusable_code"] = "quote not found in its source", "quote_not_found"
    elif rec["proximity_status"] == "metric_not_near_quote":
        rec["unusable_reason"], rec["unusable_code"] = "metric_not_near_quote: " + ", ".join(rec["missing_words"]), "metric_not_near_quote"
    else:
        rec["unusable_reason"], rec["unusable_code"] = "association_uncertain: " + str(rec["association_detail"]), "association_uncertain"
    return rec


class Evidence:
    """What a fact's source names, as this session saw it: the pack's sections, the pages it fetched, the searches it ran."""

    def __init__(self, pack_text, url_cache):
        self.sections = pack_sections(pack_text)
        self.url_cache = url_cache
        self.fetched = {}               # url the model asked for (and the url it was served) -> the url cache key of the page
        self.queries = {}               # "Q<n>" -> the text of the results returned

    @staticmethod
    def _norm_url(u):
        return (u or "").split("#", 1)[0].rstrip("/")

    def resolve(self, source):
        """(text, None) or (None, why) for a fact's `source`."""
        m = SOURCE_RE.match((source or "").strip())
        if not m:
            return None, "malformed source"
        kind, key = m.group(1), m.group(2).strip()
        if kind == "pack":
            sid = section_id(key)
            if sid in self.sections:
                return strip_quote_marks(self.sections[sid]), None
            return None, f"no pack section {sid!r} (known: {', '.join(self.sections)})"
        if kind == "query":
            qid = key.upper()
            if qid in self.queries:
                return self.queries[qid], None
            return None, f"no search {qid!r} was run in this session"
        want = self._norm_url(key)
        for u, cache_key in self.fetched.items():
            if self._norm_url(u) == want:
                rec = self.url_cache.get(cache_key) or {}
                text = rec.get("full_text") if rec.get("full_text") is not None else rec.get("text")
                if text is not None:
                    return text, None
        return None, f"page {key!r} was not fetched in this session"


class Ledger:
    """The facts of stage 1 with their annotations."""

    def __init__(self, evidence, company=None, ticker=None):
        self.evidence = evidence
        self.waived = company_words(company, ticker)
        self.facts = []             # annotated facts, in registration order
        self.rejected = []          # {"fact_id", "why"} - a fact that could not be kept (a repeated fact_id)
        self.done = False
        self.summary = ""
        self.calls_refused = []     # register_facts calls that were not understood at all

    def _ids(self):
        return {f["fact_id"] for f in self.facts}

    def register(self, args):
        """Apply one register_facts call; returns the tool result shown to the model."""
        facts = args.get("facts")
        if isinstance(facts, dict):
            facts = [facts]
        if facts is None:
            facts = []
        if not isinstance(facts, list):
            self.calls_refused.append("facts is not a JSON array")
            return {"error": "facts must be a JSON array of fact objects; nothing was registered."}
        shown = []
        for raw in facts:
            f = copy.deepcopy(raw) if isinstance(raw, dict) else raw
            problems = validate_fact_shape(f)
            fid = f.get("fact_id") if isinstance(f, dict) else None
            if not problems and f["fact_id"] in self._ids():
                self.rejected.append({"fact_id": f["fact_id"], "why": "fact_id already registered"})
                shown.append({"fact_id": f["fact_id"], "status": "rejected: fact_id already registered; use a new id"})
                continue
            if problems:
                rec = {**(f if isinstance(f, dict) else {"raw": f}), "statuses": {"shape": "malformed", "problems": problems},
                       "usable": False, "unusable_reason": "malformed: " + "; ".join(problems), "unusable_code": "malformed"}
                if not isinstance(fid, str) or not fid.strip() or fid in self._ids():
                    rec["fact_id"] = f"_malformed_{len(self.facts) + 1}"
                self.facts.append(rec)
                shown.append({"fact_id": rec["fact_id"], "status": rec["unusable_reason"]})
                continue
            text, why = self.evidence.resolve(f["source"])
            chk = check_fact(f, text, self.waived if f["source"].strip().lower().startswith("pack:") else None)
            statuses = {k: chk[k] for k in ("quote_status", "proximity_status", "missing_words", "value_status", "quote_over_400_chars", "table", "association_status", "association_detail")}
            if chk.get("entity_from_pack_company"):
                statuses["entity_from_pack_company"] = chk["entity_from_pack_company"]
            if why:
                statuses["source_problem"] = why
            rec = {**f, "statuses": statuses, "usable": chk["usable"], "unusable_reason": chk["unusable_reason"], "unusable_code": chk["unusable_code"]}
            if why:
                rec["unusable_reason"] = f"{chk['unusable_reason']} ({why})"
                rec["unusable_code"] = "source_not_resolved"
            self.facts.append(rec)
            shown.append({"fact_id": f["fact_id"], "status": ", ".join(
                [chk["quote_status"], *(["metric_not_near_quote: " + ", ".join(chk["missing_words"])] if chk["proximity_status"] == "metric_not_near_quote" else []),
                 *(["association_uncertain: " + str(chk["association_detail"])] if chk["association_status"] == "association_uncertain" else []),
                 chk["value_status"], "usable" if chk["usable"] else "unusable"])})
        out = {"registered": shown, "facts_registered": len(self.facts), "facts_usable": sum(1 for x in self.facts if x["usable"])}
        if args.get("done") is True:
            summary = args.get("research_summary")
            if not isinstance(summary, str) or not summary.strip():
                out["done"] = "not accepted: done=true needs research_summary (at most 600 words). Call register_facts again with done=true and the summary."
            else:
                self.done, self.summary = True, summary.strip()
                out["done"] = "accepted"
        elif "research_summary" in args and isinstance(args.get("research_summary"), str) and args["research_summary"].strip():
            out["note"] = "research_summary is read only with done=true"
        return out

    def dossier(self, **extra):
        usable = [f for f in self.facts if f["usable"]]
        return {
            "schema": "r26.dossier.v1", "stage": "stage1", "pack_revision": PACK_REVISION_R26,
            "done": self.done, "incomplete": not self.done,
            "summary": self.summary, "summary_words": len(self.summary.split()),
            "summary_over_600_words": len(self.summary.split()) > SUMMARY_MAX_WORDS,
            "facts": self.facts, "rejected": self.rejected,
            "counts": {"facts": len(self.facts), "usable": len(usable), "unusable": len(self.facts) - len(usable)},
            **extra,
        }


def usable_facts(dossier):
    return [f for f in dossier["facts"] if f.get("usable")]


def unusable_listing(dossier):
    """[(fact_id, why)] for the facts later stages list as "unusable, why"."""
    return [(f["fact_id"], f.get("unusable_reason")) for f in dossier["facts"] if not f.get("usable")]


# ---------------------------------------------------------------- the register_facts tool and the stage-1 TASK

REGISTER_FACTS_TOOL = {
    "type": "function",
    "function": {
        "name": "register_facts",
        "description": (
            "Register the facts the valuation will need, each with the exact quote it rests on. Call it as often as you like while you research, and "
            "finish the stage by calling it once with done=true and your research_summary. Code checks every fact against its source: that the quote "
            "occurs there verbatim, that the entity and the metric are named near it, that the value is written in the quote, and that the metric you register is the metric term "
            "nearest to the value in its sentence (in a table row: that the table's header row and the row's label name it). A fact that fails a "
            "check is kept with its status and cannot be used by later stages, so quote the source exactly: the whole sentence, or the whole table row. A fact has no number when value is null "
            "(a qualitative fact). A later stage sees only the facts you register and the summary: it cannot see this research."),
        "parameters": {
            "type": "object",
            "properties": {
                "facts": {
                    "type": "array",
                    "description": "The facts to register in this call (an empty list is allowed with done=true).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact_id": {"type": "string", "description": "Your id for the fact, unique in this stage: F1, F2, ..."},
                            "source": {"type": "string", "description": "pack:<section id> (an id from the list in the TASK), page:<the exact url of a page you fetched>, or query:Q<n> (the search made as [call n])."},
                            "quote": {"type": "string", "description": "Copied exactly from that source, at most 400 characters, containing the number when there is one."},
                            "entity": {"type": "string", "description": "The company, segment or market the number is about."},
                            "metric": {"type": "string", "description": "What is measured, in the source's own words where you can."},
                            "period": {"type": "string", "description": "The period, e.g. FY2025, Q2 2026, 2027-2029."},
                            "value": {"type": ["number", "null"], "description": "The number as written in the quote (12.5 for 12.5%), or null."},
                            "unit": {"type": "string", "description": "%, USD m, USD/day, x, ... (empty when there is no value)."},
                            "basis": {"type": "string", "enum": list(BASIS_VALUES), "description": "filed_gaap, company_adjusted, third_party, or n/a."},
                            "duration_years": {"type": ["number", "string", "null"], "description": "The span the fact speaks for: a contract term, a guidance horizon or a backlog, in years; \"ongoing\"; null for a one-off figure."},
                        },
                        "required": list(FACT_FIELDS),
                    },
                },
                "done": {"type": "boolean", "description": "true on the last call of the stage: your research is finished."},
                "research_summary": {"type": "string", "description": "With done=true: at most 600 words: the business as the evidence shows it, what you found, where sources conflict, and what you could not establish."},
            },
            "required": ["facts"],
        },
    },
}

STAGE1_TASK = """STAGE 1 OF 4: RESEARCH AND THE FACT LEDGER.

You are the analyst for the company in the data pack above. In this stage you do NOT value the company: no value per share, no verdict, no scenario, no probability, no
desk. You research, and you register the facts a valuation will need, each with the exact quote it rests on. A later stage, in a new session, sees only the facts you register and
your research summary; it cannot see this conversation, the pack's research or your reasoning.

1. Read the pack. Its figures are the company's filings and our systems' data; its PRIMARY SOURCES hold the company's own filings verbatim. Do not search for or fetch what the pack already holds.
2. Research what the pack does not hold with search_web and fetch_page: the company's own guidance and plans, contracts and backlog and how long they run, capacity, pricing, the competitive position, regulation, one-off items inside the reported
   figures, and the facts of the industry that decide how long today's economics last. Prefer the company's own words and primary documents; a number from a secondary source is third_party.
3. Register facts with register_facts as you find them (do not leave them all to the end). A fact is one statement with its exact quote: what the number is about (entity), what is measured (metric), the period, the value as written in the quote, its unit, the basis
   (filed_gaap, company_adjusted, third_party, n/a) and, for contracts, guidance and backlog, how many years the fact speaks for (duration_years; "ongoing"; null for a one-off).
4. The quote is copied exactly from the source you name in `source`: pack:<section id> (one of the ids listed below; filings in PRIMARY SOURCES are pack:primary-p1, pack:primary-p2, ...), page:<the exact url> of a page you fetched, or query:Q<n> for a search result ([call n]).
   Name the entity and the metric in words the source uses, close to the quote: code checks that they appear within 300 characters of it. Quote the whole sentence the number is in, so that the metric's own name stands in the quote beside the number (for a table, the whole row: code also reads the table's header row and the row's label). Code checks that the value is written in the quote and that the metric you register is the metric term nearest to the value in its sentence; a fact it cannot tie to its value is unusable (association_uncertain), and the stages that follow never see it.
5. Register what disagrees as well as what agrees. Do not register an opinion as a fact; register what the source says and who says it.
6. When your research is done, call register_facts with done=true and your research_summary (at most 600 words). That ends the stage.

Pack section ids you may cite: {section_ids}."""


def stage1_task(pack_text):
    ids = ", ".join(pack_sections(pack_text)) or "(none found)"
    return STAGE1_TASK.format(section_ids=ids)


STAGE_ORDER = {
    "stage2": ("blind_pack", "dossier", "op_margin_bar", "task"),
    "stage3": ("dossier", "median_forecast", "median_desk_result", "base_values", "price", "revealed_price_context", "price_implied_inputs", "consensus_corrected", "diagnostics", "task"),
    "stage4": ("dossier", "revealed_price_context", "frozen_desk_result", "bridge_table", "crux", "crux_verification", "stage2_spread", "diagnostics", "task"),
}


def _as_text(name, v):
    """An input as the words a session reads: text is used as it is; the dossier, the operating-margin bar and a forecast have their renderers (r26_late)."""
    if isinstance(v, str):
        return v
    if name == "dossier":
        return r26_late.render_dossier(v)
    if name == "op_margin_bar":
        return r26_late.render_bar(v)
    if name == "median_forecast":
        return r26_late.render_forecast_numbers(v)
    return json.dumps(v, indent=1, default=str)


def fresh_messages(stage, inputs):
    """The message list of a new session: one user message built only from `inputs`, whose names must all be in ALLOWED_INPUTS[stage]; a stage never reads another
    stage's messages, reasoning or tool results. Stage 1: the blind pack and the TASK. Stages 2-4: the named artifacts in STAGE_ORDER, then the TASK."""
    if stage not in ALLOWED_INPUTS:
        raise ValueError(f"unknown stage {stage!r}")
    extra = sorted(set(inputs) - ALLOWED_INPUTS[stage])
    if extra:
        raise ValueError(f"{stage} may not be handed {', '.join(extra)} (SPEC revision 26 names only {', '.join(sorted(ALLOWED_INPUTS[stage]))})")
    if stage == "stage1":
        return [{"role": "user", "content": inputs["blind_pack"].rstrip() + "\n\n---\n\n" + inputs["task"]}]
    head = inputs["blind_pack"].rstrip() + "\n\n---\n\n" if "blind_pack" in inputs else ""
    body = "\n\n".join(_as_text(n, inputs[n]) for n in STAGE_ORDER[stage] if n in inputs and n not in ("blind_pack", "task"))
    task = ("\n\n---\n\n" + inputs["task"]) if inputs.get("task") else ""
    return [{"role": "user", "content": head + body + task}]


# ---------------------------------------------------------------- stage 1: the session

MAX_TURNS = 40
NUDGE = ("You ended the turn without calling a tool. Register the facts you have found with register_facts and, when your research is done, call it with done=true and "
         "your research_summary. Do not write the memorandum or a valuation in this stage.")
LAST_TURNS = ("Two turns remain in this stage. Register any fact you have not registered yet, and end with register_facts done=true and your research_summary.")


def _turn_options(base_opts, msgs_sent, cpt, ctx, num_predict):
    est = int(len(json.dumps(msgs_sent)) / (cpt if cpt is not None else 3.0))
    np_req = base_opts.get("num_predict", num_predict)
    eff_np = max(1024, min(np_req, ctx - est - 2048))
    return dict(base_opts, num_predict=eff_np), est, eff_np


def _result_text(result):
    return "\n".join(f"{r.get('title', '')} | {r.get('url', '')} | {r.get('snippet', '')}" for r in (result.get("results") or []) if isinstance(r, dict))


def run_stage1(model, pack, run_dir, think="high", ctx=98304, num_predict=49152, seed=None, timeout=14400, verbose=True, draft_num_predict=None,
               temperature=None, query_cache=None, url_cache=None, max_search_calls=25, max_turns=MAX_TURNS, num_batch=None, ticker=None, company=None):
    """Run the stage-1 session on `pack` (the blind pack; a trailing valuation TASK is cut off) and write <run_dir>/dossier.json. Returns the dossier.
    Also written: _research_snapshot.json (the tool calls, in the format of chat_with_tools), evidence_query_cache.json, evidence_url_cache.json and the
    turn log under turns/ (stage1_<n>.json, run_hashes.json). The session uses the tools search_web, fetch_page and register_facts only."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    body_pack, task_split = split_task(pack)
    task = stage1_task(body_pack)
    msgs = fresh_messages("stage1", {"blind_pack": body_pack, "task": task})
    meta_msgs = [None]
    q_cache = query_cache if query_cache is not None else {}
    u_cache = url_cache if url_cache is not None else {}
    evidence = Evidence(body_pack, u_cache)
    ledger = Ledger(evidence, company, ticker)
    primary_items = sec_primary.parse_pack(body_pack)
    opts = {"num_ctx": ctx, **({"num_batch": num_batch} if num_batch else {}), "num_predict": num_predict, "repeat_penalty": 1.05, "presence_penalty": 0.05}
    if seed is not None:
        opts["seed"] = seed
    if draft_num_predict is not None:
        opts["draft_num_predict"] = draft_num_predict
    if temperature is not None:
        opts["temperature"] = temperature
    tools_all = [REGISTER_FACTS_TOOL, *analyst_tools.research_tools()]
    snap, turns = [], []
    t0 = time.time()
    calls = search_calls = server_errors = primary_refusals = 0
    cpt = None
    nudged = False
    warned = False
    seen_result_urls = {}
    ended = None

    def write_dossier(final=False):
        d = ledger.dossier(
            ticker=ticker, pack_sha256=hashlib.sha256(pack.encode("utf-8")).hexdigest(), blind_pack_sha256=hashlib.sha256(body_pack.encode("utf-8")).hexdigest(),
            task_split=task_split, incomplete_reason=(None if ledger.done else ended or "in_progress"),
            research={"turns": len(turns), "tool_calls": calls, "search_and_fetch_calls": search_calls, "queries": {k: v[:200] for k, v in evidence.queries.items()},
                      "pages_fetched": sorted(set(evidence.fetched.values()))},
            provenance={"model": model, "seed": seed, "think": think, "ctx": ctx, "num_predict": num_predict, "temperature": temperature,
                        "provider": llm_provider.provider_name(), "elapsed_s": round(time.time() - t0)})
        (run_dir / ARTIFACTS["stage1"]).write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
        return d

    for turn in range(1, max_turns + 1):
        if turn == max_turns - 1 and not warned and max_turns > 2:
            msgs.append({"role": "user", "content": LAST_TURNS})
            meta_msgs.append(None)
            warned = True
        active = analyst_tools._compact_history(msgs, meta_msgs)
        req_opts, est, eff_np = _turn_options(opts, active, cpt, ctx, num_predict)
        tools = [t for t in tools_all if search_calls < max_search_calls or t["function"]["name"] == "register_facts"]
        body = {"model": model, "stream": False, "think": think, "messages": active, "options": req_opts, "tools": tools}
        try:
            with turn_log.logging_to(run_dir / "turns", "stage1"):
                resp = llm_provider.chat(body, timeout)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise
            server_errors += 1
            resp = {"message": {}, "done_reason": "server_error", "http_status": e.code,
                    **({"server_error_cause": e.cause} if getattr(e, "cause", None) else {})}
        if resp.get("prompt_eval_count"):
            cpt = len(json.dumps(active)) / resp["prompt_eval_count"]
        msg = resp.get("message") or {}
        turns.append({"turn": turn, **analyst_tools.turn_metrics(resp), "think": think, "est_prompt_tokens": est, "num_predict": eff_np})
        if server_errors >= 2:
            ended = "server_error"
            break
        tcs = msg.get("tool_calls") or []
        if not tcs:
            if nudged or turn == max_turns:
                ended = "no_tool_call" if nudged else "turn_budget"
                break
            nudged = True
            msgs.append({"role": "assistant", "content": msg.get("content") or ""})
            meta_msgs.append(None)
            msgs.append({"role": "user", "content": NUDGE})
            meta_msgs.append(None)
            continue
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
        meta_msgs.append(None)
        for tc in tcs:
            calls += 1
            fn = tc.get("function") or {}
            name, args = fn.get("name"), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            rec = {"tool": name, "call_index": calls, "ts": time.strftime("%H:%M:%S"), "params": args}
            snap.append(rec)
            if name == "register_facts":
                result = ledger.register(args if isinstance(args, dict) else {})
            elif name in ("search_web", "fetch_page"):
                result = _research_call(name, args, calls, snap_rec=rec, evidence=evidence, q_cache=q_cache, u_cache=u_cache, known=seen_result_urls,
                                        primary_items=primary_items, ticker=ticker, search_calls=search_calls, max_search_calls=max_search_calls,
                                        primary_refusals=primary_refusals)
                if result.pop("_counted"):
                    search_calls += 1
                if result.pop("_primary_refusal"):
                    primary_refusals += 1
            else:
                result = {"error": f"unknown tool {name}; the tools of this stage are register_facts, search_web and fetch_page"}
            if isinstance(result, dict) and name != "register_facts":
                rec.update({k: v for k, v in result.items() if not k.startswith("_audit")})
            elif isinstance(result, dict):
                rec["result"] = result
            content, _cut = analyst_tools.tool_message(name, args, result)
            msgs.append({"role": "tool", "content": content})
            meta_msgs.append({"name": name, "args": args, "result": result, "call_index": calls})
            if verbose:
                q = (args or {}).get("query") or (args or {}).get("url") or (f"{len((args or {}).get('facts') or [])} fact(s)" if name == "register_facts" else "")
                print(f"    [stage1 tool {calls}] {name}: {str(q)[:88]}", flush=True)
        analyst_tools._write_snapshot(run_dir, model, seed, calls, False, turns, t0, snap)
        write_dossier()
        if ledger.done:
            break
    else:
        ended = "turn_budget"
    if not ledger.done and ended is None:
        ended = "turn_budget"
    analyst_tools._write_snapshot(run_dir, model, seed, calls, False, turns, t0, snap)
    analyst_tools._write_own_evidence_caches(run_dir, q_cache if query_cache is None else None, u_cache if url_cache is None else None)
    dossier = write_dossier(final=True)
    if verbose:
        print(f"    [stage1] {'done' if ledger.done else 'INCOMPLETE (' + str(ended) + ')'}: {dossier['counts']['facts']} fact(s), {dossier['counts']['usable']} usable", flush=True)
    return dossier


def _research_call(name, args, call_index, snap_rec, evidence, q_cache, u_cache, known, primary_items, ticker, search_calls, max_search_calls, primary_refusals):
    """search_web / fetch_page for the stage-1 session. Adds `_counted` (it used a research call) and `_primary_refusal` to the result (popped by the caller)."""
    args = args if isinstance(args, dict) else {}
    pref = analyst_tools.primary_refusal(name, args, primary_items, ticker) if primary_items else None
    if pref is not None:
        result, rule = pref
        snap_rec["primary_refusal"] = rule
        over = primary_refusals + 1 > analyst_tools.PRIMARY_REFUSAL_CAP
        return {**result, "_counted": over, "_primary_refusal": True}
    if search_calls >= max_search_calls:
        return {"status": "search_quota_met", "message": f"Web search budget completed ({max_search_calls} calls). Do not search again. Register your facts with register_facts "
                f"and finish with done=true and your research_summary.", "_counted": False, "_primary_refusal": False}
    if name == "search_web":
        res = analyst_tools.dispatch_tool("search_web", args, snap=None, query_cache=q_cache, url_cache=u_cache, known_urls=known)
        if isinstance(res, dict):
            for r in (res.get("results") or []):
                if isinstance(r, dict) and r.get("url"):
                    known.setdefault(r["url"], r.get("title") or "")
            qid = f"Q{call_index}"
            evidence.queries[qid] = (args.get("query") or "") + "\n" + _result_text(res)
            res = {"query_id": qid, **res}
        return {**res, "_counted": True, "_primary_refusal": False}
    # fetch_page: part 1 from the dispatcher (which fills the url cache), then the part or the find the model asked for
    u = args.get("url") or ""
    res = analyst_tools.dispatch_tool("fetch_page", {"url": u}, snap=None, query_cache=q_cache, url_cache=u_cache, known_urls=known)
    if not isinstance(res, dict) or res.get("error") or res.get("refused"):
        return {**(res if isinstance(res, dict) else {"error": str(res)}), "_counted": True, "_primary_refusal": False}
    src = res.get("url") or u
    evidence.fetched[src] = evidence.fetched[u] = src
    rec = u_cache.get(src)
    if rec is None:
        rec = {"url": src, "chars": res.get("chars", len(res.get("text") or "")), "text": res.get("text") or ""}
        u_cache[src] = rec
    find, raw_part = args.get("find"), args.get("part")
    if find is not None:
        res = {**analyst_tools.find_in_page(rec, str(find)), **({"cache_hit": res["cache_hit"]} if "cache_hit" in res else {})}
    elif raw_part is not None:
        part, err = analyst_tools._parse_part(raw_part)
        res = {"url": src, "error": err} if err else analyst_tools.page_part(rec, part)
    return {**res, "_counted": True, "_primary_refusal": False}


# ---------------------------------------------------------------- stages 2-4 (brief R26-A2)
#
# STAGE 2   K = 3 sessions (seeds s, s+1, s+2), each fresh from the blind pack, the usable dossier, the operating-margin bar and the stage-2 TASK. One tool, submit_forecast.
#           Structure and four domain rules are checked (cross-check 23); a first failure gets one repair turn, a second drops the sample (forecast_invalid). Code builds the path, bridges it to the X basis,
#           values it (r26_forecast.value_forecast) and values the alternative paths. forecasts.json.
# STAGE 3   a fresh session; no model call when the samples split by direction or no sample was valued. It sees the median sample's forecast NUMBERS (the reason text of
#           the normalized state is dropped), its desk result, the three Base values, the price, the price-implied inputs, the basis-corrected consensus and the diagnostics.
#           Tools: state_crux (the crux, and keep or revise) and submit_forecast (one revision, citing a fact id). reveal.json.
# STAGE 4   a fresh session, no tools: the memorandum over the frozen table. Every numeric contract field is filled by code (contract_fill.fill over a synthetic desk call
#           of the final valuation); the verifier annotates; final.json holds the verdict for the existing ledger path (pilot_arm r26, desk_schema "26").

R26_DESK_SCHEMA = "26"
SCEN = rf.SCENARIOS
CODE_REASON = "revision 26: set by code; the inputs are the forecast of stage 2 and stage 3 (forecasts.json, reveal.json) and nothing the desk was asked to approve"
STAGE2_MAX_TURNS = 4
STAGE3_MAX_TURNS = 8
CRUX_FORM_ATTEMPTS = 2


class R26InputError(ValueError):
    """A code-owned input of stages 2-4 is missing; the message names it and its owner."""


def _read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _write_json(p, obj):
    Path(p).write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


# ---------------------------------------------------------------- the valuation inputs (code-owned; the model sees none of this)

def bridge_facts_from_row(row, family="operating"):
    """The filed inputs of r26_forecast's base-year-calibrated bridge from the base fiscal year's row of the screener history (dollars -> $B, the unit of the desk's revenue):
    operating_income_0 the filed operating income, and tax_rate the MEASURED rate tax_provision / pretax_income clipped to [0, 0.35] (None when either is missing or the
    pretax income is not positive; not the record's 0.21 fallback); `tax_rate_raw` is the unclipped figure, and a clipped rate is stamped `tax_rate_clipped` (item 8). X_0, the X-basis earnings, is the pack's own (x_L x rev_L): valuation_inputs adds it. Net interest and
    the acquired amortization are not read here: they sit inside K_0 = OI_0 - X_0 / (1 - tau). Nothing is defaulted."""
    row = row or {}

    def n(k):
        v = row.get(k)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None

    pre, tax, oi, rev = n("pretax_income"), n("tax_provision"), n("operating_income"), n("revenue")
    out = {"family": family, "operating_income_0": None if oi is None else oi / 1e9, "revenue_0": None if rev is None else rev / 1e9, "tax_rate": None, "tax_rate_raw": None, "stamps": []}
    if pre is not None and tax is not None and pre > 0:
        raw = tax / pre
        out["tax_rate_raw"] = raw                                 # item 8: the measured rate, kept beside the applied one
        out["tax_rate"] = min(0.35, max(0.0, raw))
        if out["tax_rate"] != raw:
            out["stamps"].append(rf.TAX_CLIPPED_STAMP)
    return out


def load_bridge_facts(ticker, family="operating", root=None):
    """bridge_facts_from_row for `ticker`'s base fiscal year in the screener history (capability_test.DataRoot); None when the history holds no year for it."""
    import capability_test as cap
    dr = root if root is not None else cap.DataRoot()
    h = dr.history(ticker)
    yrs = sorted(int(y) for y in h if str(y).isdigit())
    if not yrs:
        return None
    return bridge_facts_from_row(h.get(str(yrs[-1])) or h.get(yrs[-1]), family)


def default_desk_params():
    """The scenario-independent arguments of the desk call that code makes. The reasons the desk asks for when an input leaves its default are all set to CODE_REASON
    (the forecast is the evidence; the model is not asked to defend a desk call)."""
    import contract_fill
    p = {k: CODE_REASON for k in contract_fill.REASONS_11}
    p.update(cash_flow_life="perpetual", sbc_treatment="deducted_in_cf")
    return p


def resolve_family(facts, bar=None):
    """(bridge family, None) or (None, why). The pack facts' own classification is facts["population_ranges"]["family"] (population_ranges.family_for on the SIC code and
    the base year's balance sheet, set by capability_test._population_ranges_for): "financial" -> the identity bridge (the margins are on the X basis); "operating" and
    "commodity" -> the operating bridge. Anything else (None, family_not_built, absent) is unresolved, and so is a bar on the other basis than the family
    (op_margin_bar["basis"] "x" is the financial family's): nothing is defaulted."""
    fam = ((facts or {}).get("population_ranges") or {}).get("family")
    if fam == "financial":
        out = "financial"
    elif fam in ("operating", "commodity"):
        out = "operating"
    else:
        return None, f"family_unresolved: population_ranges.family is {fam!r}"
    basis = (bar or {}).get("basis")
    if out == "operating" and basis == "x" and "x_basis_no_operating_income" in ((bar or {}).get("stamps") or []):
        return "financial", None                  # no filed operating income in the window (any name): the X basis throughout, the identity bridge
    if basis in ("operating", "x") and (basis == "x") != (out == "financial"):
        return None, f"family_unresolved: family {fam!r} but the margin bar is on the {basis!r} basis"
    return out, None


def valuation_inputs(facts, price, desk_context, ticker=None, bridge_facts=None):
    """Everything code needs to value a forecast: rev0 and base_cf ($B), the bridge facts, the desk's call arguments and context, the price and the verdict band.
    rev0 is facts["long_run"]["rev_L"] and base_cf facts["owner_earnings_default_b"] (the desk's own base year and cash basis); a missing rev_L raises R26InputError, a missing base_cf sets `base_cf_unavailable` (the name ends in a no_call).
    The bridge facts are facts["r26_bridge_facts"] when the pack's facts carry them, else the history's (load_bridge_facts); a name whose history is not held gets
    {"family": ...} alone, so every sample says `bridge_unavailable_*` and is not valued. The bridge needs tau, OI_0 and X_0 (x_L x rev_L of the facts' long_run)."""
    lr = (facts or {}).get("long_run") or {}
    rev0, base_cf = lr.get("rev_L"), (facts or {}).get("owner_earnings_default_b")
    if not rf._num(rev0):
        raise R26InputError(f"facts['long_run.rev_L'] is not a number ({rev0!r}); owner: pack facts")
    # no code-owned base cash flow exists (PACS: no D&A in the filed 10-K facts): r26 does not invent one. A model-independent data no_call, recorded, not a code defect.
    base_cf_why = None if rf._num(base_cf) else f"base_cf_unavailable: owner_earnings_default_b is {base_cf!r} (the pack holds no owner earnings)"
    fam, fam_why = resolve_family(facts, (facts or {}).get("op_margin_bar"))
    bf = bridge_facts if bridge_facts is not None else (facts or {}).get("r26_bridge_facts")
    if bf is None and ticker and fam is not None:
        try:
            bf = load_bridge_facts(ticker, fam)
        except Exception as e:                                                    # noqa: BLE001 - stated, not defaulted
            bf = {"family": fam, "stamps": [f"bridge_facts_not_loaded: {type(e).__name__}: {e}"]}
    bf = dict(bf) if bf else {"family": fam, "stamps": ["bridge_facts_not_held"]}
    bf["family"] = fam
    # X_0, the base year's X-basis earnings, is the pack's own: x_L x rev_L ($B). A figure the bridge facts already carry is kept.
    x_L = lr.get("x_L")
    if "x_0" not in bf and rf._num(x_L):
        bf["x_0"] = float(x_L) * float(rev0)
    # The desk's rev_L and x_L are the base year's filed figures times the attribution factor (rev_L = filed revenue x pi: BUD's 47.8 against a filed 59.3), so OI_0 goes on the
    # same basis: the filed operating margin times rev_L. The filed margin is untouched, and X_0 = (OI_0 - K_0)(1 - tau) holds at the desk's own revenue.
    r0, oi0 = bf.get("revenue_0"), bf.get("operating_income_0")
    if rf._num(r0) and r0 > 0 and rf._num(oi0):
        f = float(rev0) / float(r0)
        if abs(f - 1.0) > 1e-9:
            bf["operating_income_0"] = float(oi0) * f
            bf["stamps"] = list(bf.get("stamps") or []) + [f"operating_income_0_on_desk_revenue_basis_x{f:.6f}"]
        bf["revenue_0"] = float(rev0)
    elif rf._num(oi0):
        bf["stamps"] = list(bf.get("stamps") or []) + ["operating_income_0_revenue_basis_not_checked"]
    if "x_basis_no_operating_income" in (((facts or {}).get("op_margin_bar") or {}).get("stamps") or []) and fam == "financial":
        bf["stamps"] = list(bf.get("stamps") or []) + ["x_basis_no_operating_income"]
    ctx = dict(desk_context or {})
    return {"family": fam, "family_unresolved": fam_why, "base_cf_unavailable": base_cf_why, "rev0": float(rev0), "base_cf": float(base_cf) if base_cf_why is None else None, "bridge_facts": bf, "desk_params": default_desk_params(), "desk_context": ctx,
            "price": float(price), "min_mos": None, "run_date": ctx.get("run_date") or time.strftime("%Y-%m-%d")}


def _value(forecast, val, bar):
    try:
        return rf.value_forecast(forecast, bar, val["rev0"], val["bridge_facts"], base_cf=val["base_cf"], desk_params=val["desk_params"], desk_context=val["desk_context"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError) as e:
        return {"status": "valuation_error", "values": None, "base_value": None, "scenarios": {}, "desk": None, "stamps": [], "message": f"{type(e).__name__}: {e}"}


def _alt_paths(forecast, dossier, val, bar):
    try:
        return rf.alt_paths(forecast, dossier, bar, val["rev0"], val["bridge_facts"], base_cf=val["base_cf"], desk_params=val["desk_params"], desk_context=val["desk_context"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError) as e:
        return [{"label": "alt_path_after_evidence_expiry", "status": f"alt_path_error: {type(e).__name__}: {e}", "value": None, "fact_id": None, "duration_years": 0.0, "stamps": []}]


def trim_valuation(vf):
    """The JSON a stage artifact keeps of a value_forecast result (the desk's full record is recomputed from the forecast when needed)."""
    out = {"status": vf.get("status"), "values": vf.get("values"), "base_value": vf.get("base_value"), "stamps": vf.get("stamps"), "scenarios": {}}
    if vf.get("message"):
        out["message"] = vf["message"]
    for n, sp in (vf.get("scenarios") or {}).items():
        out["scenarios"][n] = {"status": sp.get("status"), "path": sp.get("path"), "bridge": sp.get("bridge"), "long_run": sp.get("long_run")}
    desk = vf.get("desk")
    if isinstance(desk, dict):
        out["price_implied"] = desk.get("price_implied")
    return out


def published_values(vf):
    """{scenario: per_share_iv} as the desk publishes it (two decimals) - the figures contract_fill and the table use."""
    out = {}
    for it in ((vf.get("desk") or {}).get("scenario_dcfs") or []):
        nm = str(it.get("name", ""))
        for n in SCEN:
            if nm.lower().startswith(n.lower()):
                out[n] = (it.get("dcf") or {}).get("per_share_iv")
    return out


# ---------------------------------------------------------------- a session

def _session(model, msgs, tools, run_dir, label, handle, *, think, ctx, num_predict, seed, temperature=None, num_batch=None, draft_num_predict=None,
             timeout=14400, max_turns=4, nudge="", verbose=True):
    """A short tool session on the message list `msgs` (appended to). Every model turn is logged under <run_dir>/turns/<label>_<n>.json. `handle(name, args)` returns
    (result, stop). Returns {"turns", "ended"}: ended is `closed` (handle said stop), `no_tool_call`, `turn_budget` or `server_error`."""
    opts = {"num_ctx": ctx, **({"num_batch": num_batch} if num_batch else {}), "num_predict": num_predict, "repeat_penalty": 1.05, "presence_penalty": 0.05}
    if seed is not None:
        opts["seed"] = seed
    if draft_num_predict is not None:
        opts["draft_num_predict"] = draft_num_predict
    if temperature is not None:
        opts["temperature"] = temperature
    cpt, nudged, server_errors, ended, turns = None, False, 0, "turn_budget", 0
    for turn in range(1, max_turns + 1):
        req_opts, _est, _np = _turn_options(opts, msgs, cpt, ctx, num_predict)
        body = {"model": model, "stream": False, "think": think, "messages": msgs, "options": req_opts, "tools": tools}
        try:
            with turn_log.logging_to(Path(run_dir) / "turns", label):
                resp = llm_provider.chat(body, timeout)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise
            server_errors += 1
            resp = {"message": {}, "done_reason": "server_error"}
            if server_errors >= 2:
                turns = turn
                ended = "server_error"
                break
        turns = turn
        if resp.get("prompt_eval_count"):
            cpt = len(json.dumps(msgs)) / resp["prompt_eval_count"]
        msg = resp.get("message") or {}
        tcs = msg.get("tool_calls") or []
        if not tcs:
            if nudged:
                ended = "no_tool_call"
                break
            nudged = True
            msgs.append({"role": "assistant", "content": msg.get("content") or ""})
            msgs.append({"role": "user", "content": nudge})
            continue
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
        stop = False
        for tc in tcs:
            fn = tc.get("function") or {}
            name, args = fn.get("name"), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            result, st = handle(name, args if isinstance(args, dict) else {})
            msgs.append({"role": "tool", "content": json.dumps(result, default=str)})
            stop = stop or st
            if verbose:
                print(f"    [{label} tool] {name}", flush=True)
        if stop:
            ended = "closed"
            break
    return {"turns": turns, "ended": ended}


# ---------------------------------------------------------------- stage 2

SUBMIT_NUDGE = "You ended the turn without calling a tool. Call submit_forecast with your forecast; that is the only thing this stage asks."


def _structure_message(problems):
    return ("The structure and a few domain rules are checked, never the size of a margin. Problems: "
            + "; ".join(f"{p['field']}: {p['problem']}" + (f" ({p['detail']})" if p.get("detail") else "") for p in problems))


def _stage2_sample(model, msgs0, dossier, run_dir, k, seed, sess, tool=None):
    """One of the K sessions. Returns the sample record without its valuation."""
    state = {"subs": 0, "forecast": None, "problems": [], "history": [], "ignored": 0, "closed": False}
    msgs = copy.deepcopy(msgs0)

    def handle(name, args):
        if name != "submit_forecast":
            return {"error": f"unknown tool {name}; this stage's only tool is submit_forecast"}, False
        # item 7: acceptance is idempotent. Once a forecast is accepted, or the repair has failed, a further call (the same turn may carry several) changes nothing.
        if state["forecast"] is not None or state["closed"]:
            state["ignored"] += 1
            return ({"accepted": True, "message": "A forecast was already accepted; this call is ignored."} if state["forecast"] is not None else
                    {"accepted": False, "message": "This sample is already closed; this call is ignored."}), True
        state["subs"] += 1
        probs = rf.validate_forecast(args, dossier) + r26_late.validate_labels(args, dossier)
        state["history"].append(probs)
        if not probs:
            state["forecast"], state["problems"] = copy.deepcopy(args), []
            return {"accepted": True}, True
        state["problems"] = probs
        if state["subs"] == 1:
            return {"accepted": False, "message": _structure_message(probs) + ". You have one correction: call submit_forecast again with the whole forecast."}, False
        state["closed"] = True
        return {"accepted": False, "message": _structure_message(probs) + ". This is the second failure: this sample is dropped."}, True

    res = _session(model, msgs, [tool or r26_late.SUBMIT_FORECAST_TOOL], run_dir, f"stage2_k{k}", handle, seed=seed, max_turns=STAGE2_MAX_TURNS, nudge=SUBMIT_NUDGE, **sess)
    status = "forecast_invalid" if (state["subs"] and state["forecast"] is None) else ("no_forecast" if state["forecast"] is None else "submitted")
    return {"k": k, "seed": seed, "status": status, "forecast": state["forecast"], "submissions": state["subs"], "repair_used": state["subs"] >= 2,
            "problems": state["problems"], "problem_history": state["history"], "turns": res["turns"], "ended": res["ended"], "stamps": [],
            "ignored_submissions": state["ignored"]}


def run_stage2(*, run_dir, model, blind_pack, dossier, op_margin_bar, valuation, seed=0, k=3, think="high", ctx=98304, num_predict=49152, temperature=None,
               num_batch=None, draft_num_predict=None, timeout=14400, verbose=True, facts=None):
    """Stage 2: K sessions with seeds seed, seed+1, ... (each a FRESH message list from the filed-data lines of blind_pack, the audited view of the dossier, op_margin_bar and
    STAGE2_TASK), the path, the bridge and the value of each valid forecast, its alternative paths, and the aggregate. Writes <run_dir>/forecasts.json and returns it.

    `facts` (the pack's facts) carries what the two views need (cross-check 23, items 3 and 4): facts["r26_blind_source"]["spans"] cut the pack to its filed-data lines, and
    the removed-class numbers audit the dossier. Without them the pack is shown whole and the dossier is filtered by the sentence rule alone; both say so in the stamps."""
    t0 = time.time()
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    pre = ("family_unresolved", valuation["family_unresolved"]) if valuation.get("family_unresolved") else (
        ("base_cf_unavailable", valuation["base_cf_unavailable"]) if valuation.get("base_cf_unavailable") else None)
    if pre:
        out = {"schema": "r26.forecasts.v1", "stage": "stage2", "pack_revision": PACK_REVISION_R26, "k": int(k), "seeds": [], "samples": [], "aggregate": rf.aggregate([]),
               "median_index": None, "spread": None, "base_values": [], "op_margin_bar": op_margin_bar, pre[0]: pre[1], "stamps": [pre[0]], "elapsed_s": 0}
        _write_json(run_dir / ARTIFACTS["stage2"], out)
        return out
    view, vaudit = r26_blind.stage2_dossier_view(dossier, blind_pack, facts)
    spans = ((facts or {}).get("r26_blind_source") or {}).get("spans")
    view_stamps = list(vaudit.get("stamps") or [])
    if spans:
        pack2, pack_report = r26_blind.filed_only_pack(blind_pack, spans)
    else:
        pack2, pack_report = blind_pack, None
        view_stamps.append("stage2_pack_not_filtered:no_spans")
    leaks_after = r26_blind.text_leaks(r26_late.render_dossier(view), blind_pack, facts) if facts is not None else None
    if leaks_after:
        view_stamps.append("stage2_dossier_leaks_after_filter")
    msgs0 = fresh_messages("stage2", {"blind_pack": pack2, "dossier": view, "op_margin_bar": op_margin_bar, "task": r26_late.stage2_task(op_margin_bar)})
    sess = dict(think=think, ctx=ctx, num_predict=num_predict, temperature=temperature, num_batch=num_batch, draft_num_predict=draft_num_predict, timeout=timeout, verbose=verbose)
    samples = []
    for i in range(int(k)):
        s = _stage2_sample(model, msgs0, view, run_dir, i + 1, (seed if seed is not None else 0) + i, sess, r26_late.stage2_tool(op_margin_bar))
        if s["forecast"] is not None:
            s["stamps"] += [f"{rf.DELTA_SCALE_STAMP}:{n}" for n in SCEN if rf.delta_pts_scale_suspect(s["forecast"]["scenarios"][n]["normalized"]["delta_pts"])]
            vf = _value(s["forecast"], valuation, op_margin_bar)
            s["status"] = "valued" if vf["status"] == rf.BRIDGE_OK else vf["status"]
            s["valuation"] = trim_valuation(vf)
            s["base_value"] = vf.get("base_value") if vf["status"] == rf.BRIDGE_OK else None
            s["alt_paths"] = _alt_paths(s["forecast"], dossier, valuation, op_margin_bar) if vf["status"] == rf.BRIDGE_OK else []
        else:
            s["valuation"], s["base_value"], s["alt_paths"] = None, None, []
        samples.append(s)
        if verbose:
            print(f"    [stage2] sample {i + 1}: {s['status']}" + (f" base ${s['base_value']:.2f}" if rf._num(s["base_value"]) else ""), flush=True)
    agg = rf.aggregate([s["base_value"] for s in samples])
    stamps = ([f"samples_valued:{agg['n']}_of_{int(k)}"] if agg["n"] < int(k) else []) + view_stamps
    out = {"schema": "r26.forecasts.v1", "stage": "stage2", "pack_revision": PACK_REVISION_R26, "k": int(k), "seeds": [s["seed"] for s in samples],
           "samples": samples, "aggregate": agg, "median_index": agg["median_index"], "spread": agg["spread"],
           "base_values": [s["base_value"] for s in samples], "op_margin_bar": op_margin_bar,
           "valuation_inputs": {"rev0": valuation["rev0"], "base_cf": valuation["base_cf"], "bridge_facts": valuation["bridge_facts"], "price": valuation["price"]},
           "stamps": stamps, "elapsed_s": round(time.time() - t0), "task_sha256": hashlib.sha256(r26_late.stage2_task(op_margin_bar).encode("utf-8")).hexdigest(),
           "stage2_pack_sha256": hashlib.sha256(pack2.encode("utf-8")).hexdigest(),
           "stage2_inputs_audit": {"dossier_view": vaudit, "dossier_leaks_after_filter": leaks_after, "pack": pack_report}}
    _write_json(run_dir / ARTIFACTS["stage2"], out)
    return out


# ---------------------------------------------------------------- stage 3

CRUX_SOURCE_MAP = (("guidance-consensus", "GUIDANCE"),)


def translate_source(src):
    """A dossier fact's source -> the name crux_check reads: pack:primary-pN -> PRIMARY PN, pack:data-N -> DATA N (3..6, 6a/b/c as DATA 6x), pack:guidance-consensus ->
    GUIDANCE, page:<url> -> the url; anything else (a search result, another pack section) is returned as written and is context, never company evidence."""
    s = (src or "").strip()
    m = re.match(r"^(pack|page|query):(.*)$", s, re.S)
    if not m:
        return s
    kind, key = m.group(1), m.group(2).strip()
    if kind == "page":
        return key
    if kind == "query":
        return s
    k = key.lower()
    mm = re.match(r"^primary-p(\d+)$", k)
    if mm:
        return f"PRIMARY P{mm.group(1)}"
    mm = re.match(r"^data-(\d)([a-c]?)$", k)
    if mm:
        return f"DATA {mm.group(1)}{mm.group(2).upper()}"
    return dict(CRUX_SOURCE_MAP).get(k, s)


def translate_crux(crux):
    out = copy.deepcopy(crux)
    for e in out if isinstance(out, list) else []:
        for c in (e.get("citations") if isinstance(e, dict) and isinstance(e.get("citations"), list) else []):
            if isinstance(c, dict) and isinstance(c.get("source"), str):
                c["source"] = translate_source(c["source"])
    return out


def resolve_crux_citations(crux, dossier, run_date, pack_text=""):
    """(resolved crux, problems) - cross-check 23, item 9. The model cites a usable dossier fact by id, {"fact_id": "F3"}; code supplies the citation's source (the fact's own),
    its quote (the fact's verbatim quote, nothing retyped) and its date: the filing date of a `pack:primary-pN` source (the PRIMARY SOURCES item's `filed`, if not after
    `run_date`), else `run_date`, the date the TASK has always told the model to give when it cannot tell. A citation that names no usable fact, or whose fact quote is outside
    crux_check's 30-600 characters, is a problem (a sentence for the refusal) and is left unresolved. The model's crux is not changed."""
    import crux_check
    resolved = copy.deepcopy(crux)
    problems = []
    use = {f["fact_id"]: f for f in (dossier or {}).get("facts", []) if isinstance(f, dict) and f.get("usable")}
    filed = {f"pack:primary-p{it['id'][1:]}": it.get("filed") for it in sec_primary.parse_pack(pack_text or "")}
    for i, e in enumerate(resolved if isinstance(resolved, list) else [], 1):
        cits = e.get("citations") if isinstance(e, dict) else None
        if not isinstance(cits, list):
            continue
        for k, c in enumerate(cits, 1):
            tag = f"crux[{i}].citations[{k}]"
            fid = c.get("fact_id") if isinstance(c, dict) else None
            f = use.get(fid) if isinstance(fid, str) else None
            if f is None:
                problems.append(f"{tag}.fact_id (cite the id of a usable dossier fact, such as F1; {fid!r} is not one. You do not type a source, a date or a quote)")
                continue
            n = len(crux_check.normalise(f.get("quote") or ""))
            if not crux_check.QUOTE_MIN <= n <= crux_check.QUOTE_MAX:
                problems.append(f"{tag}.fact_id ({fid}'s quote has {n} characters; a cited quote needs {crux_check.QUOTE_MIN} to {crux_check.QUOTE_MAX}. Cite another fact)")
                continue
            d = filed.get(str(f.get("source") or "").strip().lower())
            cits[k - 1] = {"fact_id": fid, "source": f["source"], "date": d if (isinstance(d, str) and crux_check.DATE_RE.match(d) and d <= run_date) else run_date, "quote": f["quote"]}
    return resolved, problems


def fetch_calls_from_cache(url_cache):
    """The fetch_page records crux_check reads (what stage 1 fetched), from the evidence url cache {url: {"full_text"/"text", ...}}."""
    out = []
    for u, rec in (url_cache or {}).items():
        if not isinstance(rec, dict):
            continue
        text = rec.get("full_text") if rec.get("full_text") is not None else rec.get("text")
        out.append({"tool": "fetch_page", "params": {"url": u}, "url": u, "text": text if isinstance(text, str) else ""})
    return out


def _diagnostics(forecast, vf, cview, dossier, val, bar):
    """alt_paths of the Base, the consensus divergence (the forecast's filed operating margin of years 1-2 against the consensus equivalent), and the stamps."""
    alts = _alt_paths(forecast, dossier, val, bar) if vf.get("status") == rf.BRIDGE_OK else []
    div = None
    if cview.get("status") == "ok":
        div = []
        rows = {r["year"]: r for r in r26_late.path_rows(vf, "Base")}
        for y, c in sorted(cview["years"].items()):
            if y in rows and rf._num(c.get("op")):
                div.append({"year": y, "forecast_op": rows[y]["op_margin"], "consensus_op": c["op"], "gap_pts": (rows[y]["op_margin"] - c["op"]) * 100.0})
    return {"alt_paths": alts, "consensus_divergence": div, "consensus_status": cview.get("status"), "stamps": list((vf.get("stamps") or []))}


def _input_items(fc, bar):
    """{(scenario, item): number} for every input of a forecast (cross-check 23, item 12): the year-1 and year-2 operating margins, the normalized margin (code's sum), the
    long-run margin and its fade, terminal_g and terminal_ronic of each scenario, and the discount rate (scenario "All")."""
    out = {("All", "discount_rate"): float(fc["discount_rate"])}
    for n in SCEN:
        s = fc["scenarios"][n]
        out[(n, "op_margin_y1")], out[(n, "op_margin_y2")] = float(s["near_term"]["op_margin"][0]), float(s["near_term"]["op_margin"][1])
        nm = rf.normalized_margin(s["normalized"], bar)
        out[(n, "normalized_margin")] = nm["value"]
        out[(n, "long_run_margin_op")] = float(s["long_run_margin_op"])
        out[(n, "fade_years")] = float(s["fade_years"])
        out[(n, "terminal_g")] = float(s["terminal_g"])
        out[(n, "terminal_ronic")] = float(s["terminal_ronic"])
    return out


def pull_record(pre_fc, post_fc, bar, cview, pre_value=None, post_value=None):
    """Every input of the forecast, pre and post the revision, and the Base value per share pre and post (item 12): {"scenario", "item", "pre", "post", "changed", "consensus",
    "pull_ratio"}. The consensus is known for the year-1 and year-2 operating margins only (operating basis); every other item has none and no ratio. `changed` is false for an
    input the revision left alone, so a reader can take the changed ones (a ratio of an unchanged input is 0.0, a value)."""
    pre, post = _input_items(pre_fc, bar), _input_items(post_fc, bar)
    cons = {"op_margin_y1": ((cview.get("years") or {}).get(1) or {}).get("op"), "op_margin_y2": ((cview.get("years") or {}).get(2) or {}).get("op")}
    items = []
    for key in pre:
        a, b = pre[key], post.get(key)
        if a is None or b is None:
            continue
        c = cons.get(key[1]) if cview.get("status") == "ok" else None
        items.append({"scenario": key[0], "item": key[1], "pre": a, "post": b, "changed": a != b, "consensus": c, "pull_ratio": rf.pull_ratio(a, b, c)})
    if rf._num(pre_value) and rf._num(post_value):
        items.append({"scenario": "Base", "item": "base_value", "pre": float(pre_value), "post": float(post_value), "changed": pre_value != post_value, "consensus": None, "pull_ratio": None})
    return items


def _stage3_messages(dossier, fc, vf, forecasts, val, cview, diag, run_date, revealed=None, bar=None):
    pi = (vf.get("desk") or {}).get("price_implied")
    import financial_model_tool as fmt
    pi_lines = fmt.price_implied_lines(pi) if isinstance(pi, dict) else ["not computed"]
    inputs = {
        "dossier": dossier,
        "median_forecast": r26_late.render_forecast_numbers(fc),
        "median_desk_result": r26_late.render_desk_result(vf, val["price"], fc),
        "base_values": r26_late.render_sample_values(forecasts["base_values"], forecasts["median_index"], forecasts["spread"]),
        "price": r26_late.render_price(val["price"]),
        "price_implied_inputs": r26_late.render_price_implied(pi_lines),
        "consensus_corrected": r26_late.render_consensus(cview),
        "diagnostics": r26_late.render_diagnostics(diag),
        "task": r26_late.stage3_task(bar, run_date),
    }
    if revealed:
        inputs["revealed_price_context"] = revealed
    return fresh_messages("stage3", inputs)


def run_stage3(*, run_dir, model, dossier, valuation, op_margin_bar, consensus_corrected=None, revealed=None, blind_pack="", fetch_calls=(), company=None, ticker=None, facts=None,
               forecasts=None, seed=0, think="high", ctx=98304, num_predict=49152, temperature=None, num_batch=None, draft_num_predict=None, timeout=14400, verbose=True):
    """Stage 3: reveal and reconcile. Reads forecasts.json (or `forecasts`), writes reveal.json and returns it. See the section comment above and the module docs."""
    import crux_check
    t0 = time.time()
    run_dir = Path(run_dir)
    forecasts = forecasts if forecasts is not None else _read_json(run_dir / ARTIFACTS["stage2"])
    price = valuation["price"]
    cview = r26_late.consensus_view(consensus_corrected, valuation["bridge_facts"])
    reveal = {"schema": "r26.reveal.v1", "stage": "stage3", "pack_revision": PACK_REVISION_R26, "called": False, "no_call": False, "no_call_reasons": [], "price": price,
              "median_index": forecasts.get("median_index"), "consensus": cview, "decision": None, "crux": None, "revision": {"submitted": False, "accepted": False},
              "stamps": [], "turns": 0, "ended": None, "final_source": None, "final_forecast": None, "pre": None, "post": None, "pull": None, "diagnostics": None}
    mi = forecasts.get("median_index")
    if mi is None:
        pre_key = next((k for k in ("family_unresolved", "base_cf_unavailable") if forecasts.get(k)), None)
        reveal["no_call"], reveal["no_call_reasons"] = True, ([pre_key] if pre_key else ["no_valued_sample"])
        if pre_key:
            reveal[pre_key] = forecasts[pre_key]
        _write_json(run_dir / ARTIFACTS["stage3"], reveal)
        return reveal
    pre_fc = forecasts["samples"][mi]["forecast"]
    pre_vf = _value(pre_fc, valuation, op_margin_bar)
    if pre_vf["status"] != rf.BRIDGE_OK:
        reveal["no_call"], reveal["no_call_reasons"] = True, [f"median_not_valued:{pre_vf['status']}"]
        _write_json(run_dir / ARTIFACTS["stage3"], reveal)
        return reveal
    reveal["pre"] = {"forecast": pre_fc, "valuation": trim_valuation(pre_vf), "base_value": pre_vf["base_value"]}
    reveal["final_source"], reveal["final_forecast"] = "stage2_median", pre_fc
    band = {"price": price, "min_mos": valuation.get("min_mos")}
    split = rf.direction_split(forecasts["base_values"], band)
    diag = _diagnostics(pre_fc, pre_vf, cview, dossier, valuation, op_margin_bar)
    reveal["diagnostics"] = diag
    if split:
        reveal["no_call"], reveal["no_call_reasons"] = True, ["samples_split_by_direction"]
        reveal["directions"] = rf.sample_directions(forecasts["base_values"], price, valuation.get("min_mos"))
        _write_json(run_dir / ARTIFACTS["stage3"], reveal)
        return reveal
    # ---- the session
    msgs = _stage3_messages(dossier, numbers_only(pre_fc), pre_vf, forecasts, valuation, cview, diag, valuation["run_date"], revealed, op_margin_bar)
    st = {"crux": None, "resolved": None, "crux_attempts": 0, "crux_state": None, "decision": None, "subs": 0, "revision": None, "form_problems": [], "closed": False, "rev_resolved": False}
    known = rf.dossier_fact_ids(dossier)
    usable = rf.usable_fact_ids(dossier)

    def done():
        return st["crux_state"] is not None and (st["rev_resolved"] or st["decision"] == "keep")

    def handle(name, args):
        if name == "state_crux":
            if st["crux_state"] is not None:
                return {"error": "the crux is already stated"}, done()
            st["crux_attempts"] += 1
            crux = args.get("crux")
            if args.get("decision") in ("keep", "revise"):
                st["decision"] = args["decision"]
            st["resolved"], cprobs = resolve_crux_citations(crux, dossier, valuation["run_date"], blind_pack)
            bad = tuple(x.split(".fact_id")[0] for x in cprobs)
            probs = cprobs + [x for x in crux_check.form_problems(st["resolved"], valuation["run_date"]) if not any(x.startswith(t) for t in bad)]
            probs += [f"crux[{i}].input ({e.get('input')!r} is not offered on this desk path; one of {', '.join(r26_late.CRUX_INPUTS)})" for i, e in enumerate(crux if isinstance(crux, list) else [], 1)
                      if isinstance(e, dict) and e.get("input") in crux_check.J and e.get("input") not in r26_late.CRUX_INPUTS]
            if probs and st["crux_attempts"] < CRUX_FORM_ATTEMPTS:
                st["form_problems"] = probs
                return {"accepted": False, "message": "The crux is malformed. Correct it once: " + "; ".join(probs)}, False
            st["crux"] = crux
            st["form_problems"] = probs
            st["crux_state"] = "form_failed" if probs else "accepted"
            return ({"accepted": False, "message": "The crux is still malformed; it stands as invalid. " + "; ".join(probs)} if probs else {"accepted": True}), done()
        if name == "submit_forecast":
            st["subs"] += 1
            if st["subs"] >= 2:
                st["closed"] = True
                return {"accepted": False, "message": "Only one revision is accepted. This second call is refused and the stage is closed."}, True
            body = {k: v for k, v in args.items() if k not in ("revision_fact_ids", "revision_reason")}
            rids, rreason = args.get("revision_fact_ids"), args.get("revision_reason")
            probs = [dict(p) for p in rf.validate_forecast(body, dossier) + r26_late.validate_labels(body, dossier)]
            if not (isinstance(rids, list) and rids and all(isinstance(x, str) for x in rids)):
                probs.append({"field": "revision_fact_ids", "problem": "a revision must cite at least one fact id"})
            elif [x for x in rids if x not in known]:
                probs.append({"field": "revision_fact_ids", "problem": "fact_id_not_in_dossier", "detail": ", ".join(x for x in rids if x not in known)})
            elif [x for x in rids if x not in usable]:
                probs.append({"field": "revision_fact_ids", "problem": "fact_id_not_usable", "detail": ", ".join(x for x in rids if x not in usable)})
            if not (isinstance(rreason, str) and rreason.strip()):
                probs.append({"field": "revision_reason", "problem": "missing_text"})
            st["revision"] = {"submitted": True, "accepted": not probs, "problems": probs, "fact_ids": rids if isinstance(rids, list) else None,
                              "reason": rreason, "forecast": body if not probs else None, "submitted_forecast": body}
            st["rev_resolved"] = True
            return ({"accepted": True} if not probs else {"accepted": False, "message": "The revision is not accepted and the forecast stays as shown: " + _structure_message(probs)}), done()
        return {"error": f"unknown tool {name}; the tools of this stage are state_crux and submit_forecast"}, False

    sess = dict(think=think, ctx=ctx, num_predict=num_predict, temperature=temperature, num_batch=num_batch, draft_num_predict=draft_num_predict, timeout=timeout, verbose=verbose)
    res = _session(model, msgs, [r26_late.STATE_CRUX_TOOL, r26_late.revision_tool_for(op_margin_bar)], run_dir, "stage3", handle, seed=seed, max_turns=STAGE3_MAX_TURNS,
                   nudge="You ended the turn without calling a tool. Call state_crux (with your decision), and submit_forecast if you revise.", **sess)
    reveal.update(called=True, turns=res["turns"], ended=res["ended"], decision=st["decision"], elapsed_s=round(time.time() - t0))
    reveal["revision"] = {k: v for k, v in (st["revision"] or {"submitted": False, "accepted": False}).items() if k != "forecast"}
    if st["subs"] >= 2:
        reveal["revision"]["second_call_refused"] = True
    final_fc, final_vf = pre_fc, pre_vf
    post = None
    if st["revision"] and st["revision"]["accepted"]:
        rvf = _value(st["revision"]["forecast"], valuation, op_margin_bar)
        if rvf["status"] == rf.BRIDGE_OK:
            final_fc, final_vf = st["revision"]["forecast"], rvf
            post = {"forecast": final_fc, "valuation": trim_valuation(rvf), "base_value": rvf["base_value"]}
            reveal["final_source"] = "stage3_revision"
            reveal["pull"] = pull_record(pre_fc, final_fc, op_margin_bar, cview, pre_vf["base_value"], rvf["base_value"])
            reveal["stamps"] += [f"{rf.DELTA_SCALE_STAMP}:{n}" for n in SCEN if rf.delta_pts_scale_suspect(final_fc["scenarios"][n]["normalized"]["delta_pts"])]
        else:
            reveal["revision"].update(accepted=False, not_valued=rvf["status"])
            reveal["stamps"].append(f"revision_not_valued:{rvf['status']}")
    reveal["post"] = post
    reveal["final_forecast"] = final_fc
    reveal["diagnostics"] = _diagnostics(final_fc, final_vf, cview, dossier, valuation, op_margin_bar) if post else diag
    # ---- the crux, resolved against the final run
    crux_t = translate_crux(st["resolved"]) if st["crux"] is not None else None
    chk = crux_check.check(crux_t, (final_vf.get("desk") or {}).get("price_implied"), blind_pack, list(fetch_calls), company, ticker, facts or {})
    if st["crux_state"] == "form_failed":
        chk = dict(chk, valid=False, reason="crux_form: " + "; ".join(st["form_problems"]))
    reveal["crux"] = {"stated": st["crux"], "resolved": st["resolved"], "translated": crux_t, "form_problems": st["form_problems"], "state": st["crux_state"] or "not_stated", "check": chk, "valid": bool(chk.get("valid"))}
    if not chk.get("valid"):
        reveal["no_call"] = True
        reveal["no_call_reasons"].append(f"crux_invalid:{chk.get('reason')}")
    _write_json(run_dir / ARTIFACTS["stage3"], reveal)
    return reveal


def numbers_only(fc):
    """The forecast as stage 3 is shown it: the reason text of each normalized state (stage 2's reasoning) is removed, and so is the sentence that says why no fact matches
    the long run (the flag that it was said stays: `no_duration_matched_evidence` becomes true)."""
    out = copy.deepcopy(fc)
    for sc in out["scenarios"].values():
        sc["normalized"].pop("reason", None)
        if sc.get("no_duration_matched_evidence") is not None:
            sc["no_duration_matched_evidence"] = True
    return out


# ---------------------------------------------------------------- stage 4

CONTRACT_NUMERIC_FROM_FILL = ("base_iv", "bull_iv", "bear_iv", "base_probability", "bull_probability", "bear_probability", "kelly_fraction_pct", "asymmetric_payoff_skew")


def synthetic_desk_call(vf, valuation, forecast, crux_translated):
    """The final valuation as the run_financial_model record contract_fill reads (params with the three scenario entries and the crux; the desk's own result merged in,
    as the snapshots hold a call)."""
    entries = [vf["scenarios"][n]["desk_entry"] for n in SCEN]
    params = {**valuation["desk_params"], "valuation_frame": forecast.get("frame", "equity"), "scenarios": entries}
    if crux_translated is not None:
        params["crux"] = crux_translated
    return {"tool": "run_financial_model", "call_index": 1, "params": copy.deepcopy(params), **copy.deepcopy(vf["desk"])}


def code_earnings(vf, valuation):
    """near_term_earnings = the Base's year-1 earnings on the valuation basis (margin x revenue); normalized_earnings = the Base's normalized valuation-basis margin on
    the base year's revenue. Both $B; None when the bridge did not give a margin."""
    rows = r26_late.path_rows(vf, "Base")
    near = rows[0]["x_margin"] * rows[0]["revenue"] if rows and rf._num(rows[0].get("x_margin")) else None
    br = (((vf.get("scenarios") or {}).get("Base") or {}).get("bridge") or {}).get("rows") or []
    nm = (((vf.get("scenarios") or {}).get("Base") or {}).get("path") or {}).get("normalized") or {}
    n_year = (((vf.get("scenarios") or {}).get("Base") or {}).get("path") or {}).get("normalized_year")
    xn = next((r["x_margin"] for r in br if r.get("year") == n_year), None)
    norm = xn * valuation["rev0"] if rf._num(xn) else None
    return near, norm


def run_stage4(*, run_dir, model, dossier, valuation, op_margin_bar, facts=None, revealed=None, blind_pack="", fetch_calls=(), company=None, ticker=None, forecasts=None, reveal=None,
               seed=0, think="high", ctx=98304, num_predict=49152, temperature=None, num_batch=None, draft_num_predict=None, timeout=14400, verbose=True):
    """Stage 4: the memorandum over the frozen result. Reads forecasts.json and reveal.json (or the arguments), writes final.json and returns it. The final valuation is
    recomputed from the final forecast (deterministic), frozen into a table, and the contract's numbers are filled by code."""
    import contract_fill
    t0 = time.time()
    run_dir = Path(run_dir)
    forecasts = forecasts if forecasts is not None else _read_json(run_dir / ARTIFACTS["stage2"])
    reveal = reveal if reveal is not None else _read_json(run_dir / ARTIFACTS["stage3"])
    price = valuation["price"]
    fc = reveal.get("final_forecast")
    final = {"schema": "r26.final.v1", "stage": "stage4", "pack_revision": PACK_REVISION_R26, "pilot_arm": ARM, "desk_schema": R26_DESK_SCHEMA, "status": None,
             "no_call": bool(reveal.get("no_call")), "no_call_reasons": list(reveal.get("no_call_reasons") or []), "actionable": False, "non_actionable_reasons": [],
             "flags": [], "table": None, "memo": "", "report": "", "contract_text": {}, "verdict": None, "verifier": None, "turns": 0}
    if fc is None:
        final.update(status="no_forecast", flags=["r26_no_call"], non_actionable_reasons=["no_call"] + final["no_call_reasons"], no_call=True)
        final["verdict"] = _bare_no_call_verdict(final["no_call_reasons"])
        _write_json(run_dir / ARTIFACTS["stage4"], final)
        return final
    vf = _value(fc, valuation, op_margin_bar)
    if vf["status"] != rf.BRIDGE_OK or not isinstance(vf.get("desk"), dict):
        final.update(status=f"final_not_valued:{vf['status']}", no_call=True, flags=["r26_no_call"], non_actionable_reasons=["no_call", f"final_not_valued:{vf['status']}"])
        final["no_call_reasons"].append(f"final_not_valued:{vf['status']}")
        final["verdict"] = _bare_no_call_verdict(final["no_call_reasons"])
        _write_json(run_dir / ARTIFACTS["stage4"], final)
        return final
    pub = published_values(vf)
    code_direction = contract_fill.label(pub.get("Base"), price)
    verdict_word = "no_call" if final["no_call"] else _label19_word(reveal, valuation, pub)
    rows = r26_late.table_rows(price=price, values=pub, forecast=fc, vf=vf, verdict=verdict_word,
                               pre_base=(reveal.get("pre") or {}).get("base_value") if reveal.get("post") else None, spread=forecasts.get("spread"))
    cview = reveal.get("consensus") or {"status": "unavailable", "reason": None, "years": {}}
    cview = {**cview, "years": {int(k): v for k, v in (cview.get("years") or {}).items()}}
    diag = reveal.get("diagnostics") or _diagnostics(fc, vf, cview, dossier, valuation, op_margin_bar)
    crux = reveal.get("crux") or {}
    shown = crux.get("resolved") or crux.get("stated")
    crux_txt = json.dumps(shown, indent=1) if shown else "(no crux was stated)"
    chk = crux.get("check") or {}
    ver_lines = [f"Crux valid: {bool(crux.get('valid'))}" + (f" (reason: {chk.get('reason')})" if chk.get("reason") else "")]
    for e in chk.get("entries") or []:
        ver_lines.append(f"  {e.get('input')}: reachable {e.get('reachable')}; valid {e.get('valid')}" + (f" ({e.get('reason')})" if e.get("reason") else "")
                         + "; citations: " + ", ".join(f"{c['source']} [{c['class']}, quote found {c['quote_found']}]" for c in e.get("citations") or []))
    table_text = r26_late.render_table(rows)
    if final["no_call"]:
        table_text += "\n[No call]\n" + "\n".join(f"Reason: {r}" for r in final["no_call_reasons"])
    inputs = {"dossier": dossier, **({"revealed_price_context": revealed} if revealed else {}), "frozen_desk_result": table_text, "bridge_table": r26_late.render_bridge_table(vf), "crux": crux_txt,
              "crux_verification": "\n".join(ver_lines), "stage2_spread": (f"STAGE-2 SPREAD of the three Base values: {forecasts.get('spread') * 100:.1f}%." if rf._num(forecasts.get("spread"))
                                                                               else "STAGE-2 SPREAD: not defined."),
              "diagnostics": r26_late.render_diagnostics(diag), "task": r26_late.stage4_task(op_margin_bar)}
    msgs = fresh_messages("stage4", inputs)
    opts = {"num_ctx": ctx, **({"num_batch": num_batch} if num_batch else {}), "num_predict": num_predict, "repeat_penalty": 1.05, "presence_penalty": 0.05}
    if seed is not None:
        opts["seed"] = seed
    if draft_num_predict is not None:
        opts["draft_num_predict"] = draft_num_predict
    if temperature is not None:
        opts["temperature"] = temperature
    req_opts, _e, _n = _turn_options(opts, msgs, None, ctx, num_predict)
    with turn_log.logging_to(run_dir / "turns", "stage4"):
        resp = llm_provider.chat({"model": model, "stream": False, "think": think, "messages": msgs, "options": req_opts}, timeout)
    final["turns"] = 1
    content = ((resp.get("message") or {}).get("content")) or ""
    memo, ctext, cproblem = r26_late.parse_contract_text(content)
    cited = set()
    for sc_ in fc["scenarios"].values():
        cited |= set((sc_.get("near_term") or {}).get("fact_ids") or []) | set((sc_.get("normalized") or {}).get("fact_ids") or []) | set(sc_.get("long_run_fact_ids") or [])
        for lk in r26_late.LABEL_ENUMS:
            cited |= set((sc_.get(lk) or {}).get("fact_ids") or [])
    ver = (r26_late.verify_memo(memo, rows, [f for f in dossier.get("facts", []) if f.get("usable")], sorted(cited)) if memo.strip()
           else {"flags": ["memo_missing"], "annotations": [], "details": [{"flag": "memo_missing"}]})
    # ---- the contract: numbers by code
    crux_t = crux.get("translated")
    call = synthetic_desk_call(vf, valuation, fc, crux_t)
    ffacts = dict(facts or {}, desk_schema=None, long_run_defaults_withheld=False)
    filled, prov = contract_fill.fill(list(fetch_calls) + [call], {}, ffacts, price, ticker=ticker, allow_blend=False, pack_text=blind_pack, company=company)
    near, norm = code_earnings(vf, valuation)
    verdict = dict(filled)
    verdict.update(near_term_earnings=near, normalized_earnings=norm)
    for k in r26_late.LABEL_ENUMS:                            # the three classifications are the stage-2 forecast's (revised or not): code writes them, never the memo
        v = (fc["scenarios"]["Base"].get(k) or {})
        verdict[k] = v.get("label")
    for k in r26_late.TEXT_FIELDS:
        if k in ctext:
            verdict[k] = ctext[k]
    if final["no_call"]:
        verdict["code_label"] = verdict.get("verdict_label")
        verdict["verdict_label"] = "hold"
        verdict["no_call"] = {"reasons": list(final["no_call_reasons"])}
    reasons = (["no_call"] + final["no_call_reasons"] if final["no_call"] else []) + list(ver["flags"])      # the prose-number check annotates and does not gate (item 13)
    if cproblem:
        reasons.append(cproblem)
    unfilled = [k for k in r26_late.UNFILLED_NUMERIC if verdict.get(k) is None]
    if unfilled:
        reasons.append("contract_fields_unfilled")             # item 14: no code source for these numbers yet; resolve before any book-wide run
    if reveal.get("revision", {}).get("submitted") and not reveal["revision"].get("accepted"):
        final["flags"].append("revision_not_accepted")
    verdict["r26"] = {"pilot_arm": ARM, "desk_schema": R26_DESK_SCHEMA, "pack_revision": PACK_REVISION_R26, "actionable": not reasons, "non_actionable_reasons": reasons,
                      "no_call": final["no_call"], "verifier": ver, "final_source": reveal.get("final_source"), "spread": forecasts.get("spread"),
                      "pre_reveal_base": (reveal.get("pre") or {}).get("base_value"), "post_reveal_base": (reveal.get("post") or {}).get("base_value"),
                      "contract_unfilled": unfilled, "model_typed_numbers_in": [k for k in r26_late.MODEL_TYPED_NUMBERS if k in ctext],
                      "contract_fill": prov, "code_directionection_m": code_direction}
    verdict["pilot_arm"], verdict["desk_schema"], verdict["pack_revision"] = ARM, R26_DESK_SCHEMA, PACK_REVISION_R26
    block = {k: verdict[k] for k in (*CONTRACT_NUMERIC_FROM_FILL, "near_term_earnings", "normalized_earnings", "verdict_label") if k in verdict and verdict[k] is not None}
    block.update({k: ctext[k] for k in ctext})
    report = memo.rstrip() + "\n\n```json:underwriting\n" + json.dumps(block, indent=1, default=str) + "\n```\n"
    final.update(status="ok" if memo.strip() else "memo_missing", memo=memo, report=report, contract_text=ctext, verdict=verdict, verifier=ver,
                 flags=final["flags"] + list(ver["flags"]) + list(ver.get("annotations") or []) + (["r26_no_call"] if final["no_call"] else []), elapsed_s=round(time.time() - t0),
                 table=rows, actionable=not reasons, non_actionable_reasons=reasons, desk_call=call,
                 task_sha256=hashlib.sha256(r26_late.stage4_task(op_margin_bar).encode("utf-8")).hexdigest())
    _write_json(run_dir / ARTIFACTS["stage4"], final)
    _append_snapshot_call(run_dir, call)
    return final


def _bare_no_call_verdict(reasons):
    """The verdict of a name nothing was valued for (family_unresolved, no valued sample): hold, no_call with its reasons, never actionable."""
    return {"verdict_label": "hold", "no_call": {"reasons": list(reasons)}, "pilot_arm": ARM, "desk_schema": R26_DESK_SCHEMA, "pack_revision": PACK_REVISION_R26,
            "r26": {"pilot_arm": ARM, "desk_schema": R26_DESK_SCHEMA, "actionable": False, "non_actionable_reasons": ["no_call"] + list(reasons), "no_call": True}}


def _label19_word(reveal, valuation, pub):
    """The code's verdict word for a result that is not a no call: the revision-19 label (the base against the price band, directional only with a valid crux)."""
    import crux_check
    chk = (reveal.get("crux") or {}).get("check")
    lab, _dm, _st = crux_check.label19(pub.get("Base"), valuation["price"], chk)
    return lab or "hold"


def _append_snapshot_call(run_dir, call):
    """The final desk run goes into the sample's _research_snapshot.json calls, where the harness reads the desk calls of a sample (extract_desk_snapshot_metrics,
    contract_fill): the staged analyst's desk is code's, and it is recorded as the one run_financial_model call."""
    p = Path(run_dir) / "_research_snapshot.json"
    try:
        doc = _read_json(p) if p.exists() else {"calls": []}
        doc.setdefault("calls", [])
        doc["calls"] = [c for c in doc["calls"] if not (isinstance(c, dict) and c.get("tool") == "run_financial_model" and c.get("call_index") == call["call_index"])]
        doc["calls"].append(call)
        _write_json(p, doc)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- the sample

def run_sample(model, pack, run_dir, **kw):
    """The arm r26's counterpart of analyst_tools.chat_with_tools for consensus_valuation: returns (report, thinking, meta). Runs the four stages in order under
    <run_dir>: stage 1 (dossier.json, from `kw` as run_stage1 takes them), stage 2 (forecasts.json), stage 3 (reveal.json), stage 4 (final.json). `kw` also carries
    facts (the pack's facts: op_margin_bar, consensus_corrected, long_run, owner_earnings_default_b), price and desk_context; the report is the memorandum with the contract
    block code filled (an empty report fails the sample, as in every arm)."""
    run_dir = Path(run_dir)
    facts, price, desk_context = kw.pop("facts", None), kw.pop("price", None), kw.pop("desk_context", None)
    verbose = kw.get("verbose", True)
    dossier = run_stage1(model, pack, run_dir, **kw)
    bar = (facts or {}).get("op_margin_bar")
    if not isinstance(bar, dict) or not bar:
        raise R26InputError("facts['op_margin_bar'] is missing: owner R26-B (the operating-margin history bar)")
    if not rf._num(price):
        raise R26InputError("price is missing")
    ticker, company = kw.get("ticker"), kw.get("company")
    val = valuation_inputs(facts, price, desk_context, ticker)
    blind_pack, _ = split_task(pack)
    cache = kw.get("url_cache")
    if cache is None and (run_dir / "evidence_url_cache.json").exists():
        cache = _read_json(run_dir / "evidence_url_cache.json")
    fetch_calls = fetch_calls_from_cache(cache)
    revealed = r26_late.revealed_price_context(facts)
    sess = {k: kw[k] for k in ("think", "ctx", "num_predict", "temperature", "num_batch", "draft_num_predict", "timeout") if k in kw}
    seed = kw.get("seed")
    forecasts = run_stage2(run_dir=run_dir, model=model, blind_pack=blind_pack, dossier=dossier, op_margin_bar=bar, valuation=val, seed=seed if seed is not None else 0,
                           verbose=verbose, facts=facts, **sess)
    reveal = run_stage3(run_dir=run_dir, model=model, dossier=dossier, valuation=val, op_margin_bar=bar, consensus_corrected=facts.get("consensus_corrected"), revealed=revealed,
                        blind_pack=blind_pack, fetch_calls=fetch_calls, company=company, ticker=ticker, facts=facts, forecasts=forecasts,
                        seed=seed if seed is not None else 0, verbose=verbose, **sess)
    final = run_stage4(run_dir=run_dir, model=model, dossier=dossier, valuation=val, op_margin_bar=bar, facts=facts, revealed=revealed, blind_pack=blind_pack, fetch_calls=fetch_calls,
                       company=company, ticker=ticker, forecasts=forecasts, reveal=reveal, seed=seed if seed is not None else 0, verbose=verbose, **sess)
    meta = {"r26": {"stage1": dossier["counts"], "stage2": {"statuses": [s["status"] for s in forecasts["samples"]], "spread": forecasts["spread"]},
                    "stage3": {"called": reveal["called"], "no_call": reveal["no_call"], "reasons": reveal["no_call_reasons"], "final_source": reveal["final_source"]},
                    "stage4": {"status": final["status"], "flags": final["flags"], "actionable": final["actionable"]}},
            "done_reason": "stop", "research_calls": (dossier.get("research") or {}).get("search_and_fetch_calls", 0), "repeat_calls": 0}
    return final["report"], "", meta
