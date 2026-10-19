"""r26_blind.py - the blind pack, the operating-margin bar and the basis-corrected consensus of revision 26 (SPEC_rev26_staged_analyst.md section 5; BRIEF_R26_B).

Pure functions and one list type; nothing here reads a file, calls a model or touches the network.

1. SOURCE CLASSES. capability_test.build_pack appends its elements to a `PackLines`, a list that records, beside each element, the source class of the code that
   emitted it and the section it sits in (a side list, never printed). An element carries its own class when the emitting code wrapped it in `tag(cls, text)`;
   otherwise it takes the list's current class (`L.cls`, set at the top of each section). The classes:
     removed from the blind pack (REMOVED_CLASSES): consensus (estimates, the base-year check, the estimate trend and revisions, the DEFAULTS levels, next-FY growth,
       consensus status, base_year_cap, base_window and the consensus margins), price_target, price, market_cap, multiple (multiples on price, the dividend yield),
       price_action (DATA 2.5), reference (the CONSENSUS-IMPLIED VALUE, any reference value and the price-implied run);
     kept: filed (SEC filings and exact arithmetic on them), derived (code-owned anchors, ranges and conventions), aggregator (a vendor's figures), narrative
       (prose of another party: news, the catalyst brief, guidance, the earnings call, the research brief).
   The blind pack is decided by these classes, never by searching the rendered text. Only narrative is filtered, sentence by sentence, by one generic rule
   (`names_removed_class`); each dropped sentence is listed with its source.
2. `r26_leak_audit(blind_pack_text, facts)`: every number of the removed classes (the removed lines the build recorded and the removed facts), rendered to 1-3
   significant digits, with and without the $ % B M x marks, searched in the blind pack. An occurrence on a filed or derived line is an exception, listed with its
   source; an occurrence on a narrative or aggregator line is a leak. A bare integer is a weak match (counted, not failing).
3. `op_margin_bar`: filed operating margin per year and min, p25, median, p75, max and last over the filed window. A year that cannot be computed is stated, never filled.
4. `consensus_corrected`: the vendor's consensus EPS on the filed base year's basis, as X-basis margins, for stage 3 only.
5. (cross-check 23, items 3 and 4) `stage2_dossier_view`: the leak audit applied to the model-facing dossier of stage 2 - the research summary is filtered sentence by sentence and
   a fact that quotes analyst, consensus or price content, or a removed number, is withheld, each drop listed; `filed_only_pack`: stage 2 reads the blind pack's filed-data
   lines only.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---- the source classes ------------------------------------------------------------------------------------------------------------------------

FILED, DERIVED, AGGREGATOR, NARRATIVE = "filed", "derived", "aggregator", "narrative"
CONSENSUS, PRICE_TARGET, PRICE, MARKET_CAP, MULTIPLE, PRICE_ACTION, REFERENCE = (
    "consensus", "price_target", "price", "market_cap", "multiple", "price_action", "reference")
REMOVED_CLASSES = (CONSENSUS, PRICE_TARGET, PRICE, MARKET_CAP, MULTIPLE, PRICE_ACTION, REFERENCE)
KEPT_CLASSES = (FILED, DERIVED, AGGREGATOR, NARRATIVE)
EXCEPTION_CLASSES = (FILED, DERIVED)         # a removed number on such a line is a coincidence with a filed or code-owned fact: listed, not failing

# the DEFAULTS block's lines by their fact key (pack_facts.render_defaults_block records the key of each line it builds; a line with no key is derived)
DEFAULTS_KEY_CLASS = {
    "levels": CONSENSUS, "next_fy_revenue_growth": CONSENSUS, "consensus_data_status": CONSENSUS, "base_year_cap": CONSENSUS, "base_window": CONSENSUS,
    "x_margin_consensus_y1y2": CONSENSUS,
    "consensus_implied_value": REFERENCE, "reference_status": REFERENCE, "price_implied": REFERENCE,
    "price": PRICE,
}
# DATA WARNINGS by the check that raised them (pack_data_sanity): the share-count mismatch prints the market cap and the price
WARNING_CLASS = {"shares_mismatch": MARKET_CAP}


class Tagged(str):
    """A pack element that carries its own source class (and, optionally, the text the blind pack prints in its place)."""
    cls: Optional[str] = None
    blind: Optional[str] = None            # the text the blind pack prints instead of this element (the element is kept in full in the full text)
    removed_cls: str = "consensus"         # the class of what the blind variant leaves out
    removed_text: Optional[str] = None     # what the blind variant leaves out, recorded as a removed line (a consensus member of an otherwise kept line)


def tag(cls: str, text: str, blind: Optional[str] = None, removed_text: Optional[str] = None, removed_cls: str = "consensus") -> Tagged:
    s = Tagged(text)
    s.cls = cls
    s.blind = blind
    s.removed_text = removed_text
    s.removed_cls = removed_cls
    return s


class PackLines(list):
    """The pack's element list with a parallel side list of (class, section, is_header). Behaves as a list of str: `"\\n".join(L)` is the full pack. An element
    takes its own class (a Tagged) or the list's current class `cls`; an element starting with "## " is a section header and sets the section."""

    def __init__(self, items: Iterable[str] = ()):
        super().__init__()
        self.tags: List[Tuple[str, str, bool]] = []
        self.cls = FILED
        self.section = ""
        self.extend(items)

    def _note(self, x: str) -> Tuple[str, str, bool]:
        header = isinstance(x, str) and x.startswith("## ")
        if header:
            self.section = x[3:].split("   [")[0].strip()
        return (getattr(x, "cls", None) or self.cls, self.section, header)

    def append(self, x):
        self.tags.append(self._note(x))
        super().append(x)

    def extend(self, items):
        for x in items:
            self.append(x)

    def __iadd__(self, items):
        self.extend(items)
        return self

    def insert_block(self, i: int, items: Sequence[str], cls: str) -> None:
        """Insert a block of elements at index `i`, all of class `cls`; a leading "## " element names the block's section for every element of it."""
        section = self.section
        sec = section
        for k, x in enumerate(items):
            if isinstance(x, str) and x.startswith("## "):
                sec = x[3:].split("   [")[0].strip()
            c = getattr(x, "cls", None) or cls
            self.tags.insert(i + k, (c, sec, isinstance(x, str) and x.startswith("## ")))
            super().insert(i + k, x)
        self.section = section

    def insert(self, i, x):
        n = len(self)
        i = max(0, min(i if i >= 0 else n + i, n))
        saved = self.section
        t = self._note(x)
        self.section = saved
        self.tags.insert(i, t)
        super().insert(i, x)


# ---- the narrative filter: one generic rule, applied sentence by sentence ----------------------------------------------------------------------

_I = re.IGNORECASE
DROP_RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("consensus", re.compile(r"\bconsensus\b", _I)),
    ("analyst_estimate", re.compile(
        r"\banalysts?\b|\bsell[- ]side\b|\bwall street\b|\bstreet (?:estimates?|expectations?|forecasts?|consensus)\b|"
        r"\b(?:eps|earnings|revenue|sales|profit|income)\s+(?:estimates?|forecasts?)\b|\bestimates?\s+(?:revisions?|trend)\b|\bestimated by\b", _I)),
    ("price_target", re.compile(
        r"\bprice[- ]targets?\b|\btarget price\b|\bprice objective\b|\bupgrad\w+|\bdowngrad\w+|\bstreet\b.{0,30}\btargets?\b|"
        r"\b(?:avg|average|mean|median)\b.{0,15}\btargets?\b", _I)),
    ("share_price", re.compile(
        r"\b(?:share|stock)\s+price\b|\bprice per share\b|\b(?:shares|stock)\s+(?:rose|fell|jumped|climbed|surged|slid|dropped|gained|declined|tumbled|plunged|soared|"
        r"sank|slumped|rallied|closed|traded|trades|trading|are up|are down|is up|is down|edges|edged)\b|\btrading at\b|\b52[- ]week (?:high|low|range)\b|"
        r"\bthe price (?:is|was|has|had)\b|\b(?:12|six|6|3|1)[- ]?(?:month|week|day|year)s?\s+(?:run|rally|rise|gain|move|return|decline|drop|performance)\b|"
        r"\$\d[\d.,]*\s+price\b|%\s+at\s+~?\$\d", _I)),
    ("analyst_view", re.compile(
        r"\b(?:buy|sell|hold|overweight|underweight|outperform|underperform|neutral|equal[- ]weight|market[- ]perform)\s+ratings?\b|"
        r"\bratings?\s+(?:of|to|from)\s+(?:buy|sell|hold|overweight|underweight|outperform|underperform|neutral)\b|"
        r"\brated\s+(?:buy|sell|hold|overweight|underweight|outperform|underperform|neutral)\b|\binitiat(?:e|ed|es|ing)\s+(?:\w+\s+)?coverage\b|\bcoverage\s+initiat\w+|"
        r"\bupgrad\w+|\bdowngrad\w+|\bprice\s+(?:target|objective)s?\b|\btarget\s+price\b|(?-i:\bPTs?\b)|\bthe street\b|(?-i:\bStreet\b)|\bsell[- ]side\b|"
        r"\bestimates?\b|\bEPS\s+revisions?\b|\brevisions?\s+(?:up|down|upward|downward|higher|lower)\b|\brevised\s+(?:up|down|upward|downward)\b|"
        r"\b\d+\s+up\s*/\s*\d+\s+down\b|\b\d+\s+up,?\s+\d+\s+down\b|\bon the day\b|\b(?:stock|shares?)\s+[-+\u2212]\s*\d|"
        r"\b(?:stock|shares?)\s+(?:moved|rose|fell|gained|lost|dropped|jumped|climbed|slid|slipped|sank|surged|plunged|tumbled|soared|rallied)\b|"
        r"\b(?:fell|rose|dropped|gained|lost|jumped|slid|slipped|sank|surged|plunged|tumbled|soared|rallied|climbed)\s+[-+\u2212]\s*\d", _I)),
    ("market_cap", re.compile(r"\bmarket cap(?:italization|italisation)?\b", _I)),
    ("price_multiple", re.compile(
        r"\bP/E\b|\bprice[- /]to[- /](?:earnings|book|sales|cash[- ]?flow)\b|\bEV/(?:EBITDA|sales|revenue|ebit)\b|\benterprise value (?:to|of)\b.{0,30}\b(?:ebitda|sales|revenue)\b|"
        r"\b(?:trading|valuation|forward|trailing|ntm|ltm|implied)\s+(?:multiples?|p/e)\b|\bthe multiple\b|\bre-?rat(?:e|ing|ed)\b|\bde-?rat(?:e|ing|ed)\b|"
        r"\b\d+(?:\.\d+)?x\s+(?:forward |trailing |ntm |ltm |next[- ]twelve[- ]months? )?(?:earnings|ebitda|sales|revenue|cash flow)\b|\bPEG\b|\bdividend yield\b|"
        r"\bearnings yield\b|\b(?:free cash flow|fcf) yield\b", _I)),
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])(\s+)")


def names_removed_class(sentence: str) -> Optional[str]:
    """The name of the first rule the sentence breaks (it names consensus, analyst estimates, a price target, the share price, the market cap or a price
    multiple), else None. The one rule of the narrative filter."""
    for name, rx in DROP_RULES:
        if rx.search(sentence):
            return name
    return None


def filter_narrative(text: str, source: str, extra=None) -> Tuple[str, List[Dict[str, str]]]:
    """(kept text, drops). The text is split into lines, each line into sentences; a sentence that breaks the rule is dropped and listed as
    {"source", "rule", "sentence"}. A line with no sentence left is dropped; blank lines stay. The remaining sentences keep their own separators.
    `extra(sentence)`, when given, is a second rule that returns a rule name (a sentence is dropped under it) or None."""
    drops: List[Dict[str, str]] = []
    out_lines: List[str] = []
    for line in str(text).split("\n"):
        if not line.strip():
            out_lines.append(line)
            continue
        parts = _SENT_SPLIT.split(line)              # unit, sep, unit, sep, ... unit
        kept: List[str] = []
        for i in range(0, len(parts), 2):
            unit = parts[i]
            rule = (names_removed_class(unit) or (extra(unit) if extra is not None else None)) if unit.strip() else None
            if rule:
                drops.append({"source": source, "rule": rule, "sentence": unit.strip()})
                continue
            if kept:
                kept.append(parts[i - 1] if i - 1 >= 0 else " ")
            kept.append(unit)
        if kept:
            out_lines.append("".join(kept))
    return "\n".join(out_lines), drops


# ---- the blind pack ----------------------------------------------------------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{2,3}) +(.+?) *$")
_ITEM = re.compile(r"^\[P(\d+)\]")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", (text or "").lower()).strip("-.")


def assign_ids(elements: Sequence[str]) -> List[str]:
    """The pack-section id of each element, by the harness's rule (r26_stages.pack_sections, restated here: nothing imports across repositories): a `##` or `###`
    heading whose title (up to its first " - ", " [" or two spaces) has no lower-case letter opens a section, whose id is the title's slug (`DATA 5 - ...` -> data-5,
    `GUIDANCE & CONSENSUS` -> guidance-consensus; a repeat gets -2); a `###` section sits inside its `##` parent; the research brief's lower-case headings open none; each
    `[P#]` item of PRIMARY SOURCES is `primary-p#`. An element before the first section has id ""."""
    stack: List[Tuple[int, str]] = []
    seen: Dict[str, int] = {}
    prim: Optional[str] = None
    out: List[str] = []
    for e in elements:
        first = str(e).split("\n", 1)[0]
        m = _HEADING.match(first)
        if m:
            title = re.split(r" - | \[|  ", m.group(2), maxsplit=1)[0].strip()
            if re.search(r"[A-Za-z]", title) and title == title.upper() and _slug(title):
                sid = _slug(title)
                seen[sid] = seen.get(sid, 0) + 1
                if seen[sid] > 1:
                    sid = f"{sid}-{seen[sid]}"
                level = len(m.group(1))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, sid))
                prim = None
        top = stack[-1][1] if stack else ""
        if top == "primary-sources":
            mi = _ITEM.match(first)
            if mi:
                prim = f"primary-p{mi.group(1)}"
            out.append(prim or top)
        else:
            out.append(top)
    return out


def blind_split(L: PackLines) -> Dict[str, Any]:
    """Split the full pack's elements by their source classes. {"blind_text", "full_text", "removed" [{cls, section, text}], "drops" [{source, rule, sentence}],
    "spans" [{start, end, cls, section}] (0-based blind-text lines, inclusive), "dropped_sections" [section names whose every body element was removed]}."""
    full = list(L)
    tags = list(L.tags)
    assert len(full) == len(tags), "the side list is out of step with the pack's elements"
    ids = assign_ids(full)
    kept: List[Tuple[str, str, str, bool, str]] = []          # (text, cls, section, header, id)
    removed: List[Dict[str, str]] = []
    drops: List[Dict[str, str]] = []
    for text, (cls, sec, header), sid in zip(full, tags, ids):
        if cls in REMOVED_CLASSES:
            removed.append({"cls": cls, "section": sec, "id": sid, "text": str(text)})
            continue
        shown = str(text)
        alt = getattr(text, "blind", None)
        if alt is not None:
            if getattr(text, "removed_text", None):
                removed.append({"cls": text.removed_cls, "section": sec, "id": sid, "text": text.removed_text, "replaced_by_blind_variant": True})
            shown = alt
        if cls == NARRATIVE and not header:
            shown, d = filter_narrative(shown, sec)
            for x in d:
                x["id"] = sid
            drops += d
            if not shown.strip() and str(text).strip():
                continue
        kept.append((shown, cls, sec, header, sid))
    # a section whose header survived but whose body was removed entirely is dropped with its blank lines (listed); a section empty in the full pack stays
    had_body = {sec for text, (cls, sec, header) in zip(full, tags) if not header and str(text).strip()}
    dropped_sections: List[str] = []
    out: List[Tuple[str, str, str, str]] = []
    i = 0
    while i < len(kept):
        text, cls, sec, header, sid = kept[i]
        if header:
            j = i + 1
            while j < len(kept) and not kept[j][3] and kept[j][2] == sec:
                j += 1
            if not any(k[0].strip() for k in kept[i + 1:j]) and sec in had_body:
                dropped_sections.append(sec)
                i = j
                continue
        out.append((text, cls, sec, sid))
        i += 1
    texts = [t for t, _, _, _ in out]
    spans: List[Dict[str, Any]] = []
    line = 0
    for t, c, s, i_d in out:
        n = str(t).count("\n") + 1
        if spans and spans[-1]["cls"] == c and spans[-1]["section"] == s and spans[-1]["id"] == i_d and spans[-1]["end"] == line - 1:
            spans[-1]["end"] = line + n - 1
        else:
            spans.append({"start": line, "end": line + n - 1, "cls": c, "section": s, "id": i_d})
        line += n
    # the harness's section ids: `removed_ids` lost every body element; `partial_ids` lost part of the body (the id stays, the removal is partial)
    kept_ids = {k[4] for k in kept if not k[3] and k[0].strip()}
    body_ids = {sid for text, (cls, sec, header), sid in zip(full, tags, ids) if not header and str(text).strip()}
    removed_ids = sorted(body_ids - kept_ids)
    partial_ids = sorted({r["id"] for r in removed if r.get("id") in kept_ids} | {x["id"] for x in drops if x["id"] in kept_ids})
    return {"blind_text": "\n".join(texts), "full_text": "\n".join(str(x) for x in full), "removed": removed, "drops": drops, "spans": spans,
            "dropped_sections": dropped_sections, "removed_ids": removed_ids, "partial_ids": partial_ids}


# ---- the leak test ------------------------------------------------------------------------------------------------------------------------------

_NUM = re.compile(r"(?<![\w.])(?P<tok>(?:[-+]?\$)?[-+]?\d[\d,]*(?:\.\d+)?(?P<unit>%|\s?(?:million|billion|thousand|mn|bn)\b|[BMK](?![A-Za-z])|x(?![A-Za-z]))?)")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _norm(tok: str) -> str:
    s = re.sub(r"[^\d.]", "", tok)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s and "." not in s:
        s = s.lstrip("0") or "0"
    return s


def sig_forms(x: float, top: int = 3) -> List[str]:
    """`x` rendered to 1, 2 and 3 (up to `top`) significant digits as plain decimals (no sign, no marks, no trailing zeros after the point)."""
    x = abs(float(x))
    if not math.isfinite(x) or x == 0:
        return []
    out = []
    for k in range(1, top + 1):
        s = format(Decimal(f"{x:.{k - 1}e}"), "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        if s not in out:
            out.append(s)
    return out


def _tokens(line: str) -> Iterable[Tuple[str, str, bool]]:
    """(raw token, normalized digits, strong) for each number in a line. Strong: the token has a decimal point or a $ % B M K x mark; a bare integer is weak."""
    scrubbed = _DATE.sub(lambda m: " " * len(m.group(0)), line)
    for m in _NUM.finditer(scrubbed):
        tok = m.group("tok")
        strong = ("." in tok) or ("$" in tok) or bool(m.group("unit"))
        yield tok, _norm(tok), strong


def unit_class(tok: str) -> str:
    """The unit class of a printed number: "%", "x" (a multiple), "B" / "M" / "K" (an amount with that suffix or word), "$" (a dollar figure with no suffix: per share),
    else "bare"."""
    tail = re.sub(r"^[-+]?\$?[-+]?[\d,]*(?:\.\d+)?", "", tok).strip().lower()
    if tail in ("%", "x"):
        return tail
    if tail[:1] in ("b", "m", "k"):
        return tail[:1].upper()
    if tail[:1] == "t":
        return "K"
    return "$" if "$" in tok else "bare"


_SECTION_REF = re.compile(r"\bDATA \d+(?:\.\d+)?\b")


def numbers_in_text(text: str) -> List[Tuple[float, str]]:
    """The numbers of a removed line worth testing: those with a decimal point or a mark (a bare integer is a count or a year). A section header is a label and a
    reference to a section ("DATA 2.5") is not a number. [(value, printed token)]."""
    out = []
    for line in str(text).split("\n"):
        if line.startswith("## "):
            continue
        for tok, norm, strong in _tokens(_SECTION_REF.sub(" ", line)):
            if not strong or not norm:
                continue
            try:
                v = float(norm)
            except ValueError:
                continue
            if v != 0:
                out.append((v, tok))
    return out


# The removed FACTS, by what of each is a removed-class number. A fact that holds filed figures beside the removed ones (the reference line's inputs, the
# correction's filed EPS, a path's base year, a bound that is a fixed constant) contributes only its removed part.
REMOVED_FACT_PATHS = ("consensus_implied_value", "levels", "next_fy_revenue_growth", "x_margin_consensus_y1y2", "price_implied_price", "base_year_cap",
                      "base_window.ttm_value", "base_window.ttm_year2")
REMOVED_LONG_RUN_MEMBERS = ("e5", "oe5", "m5", "oe_path", "oe_base", "om_5", "m_long", "margin_ratio")      # revenue_path[1:] too (index 0 is the filed base year)
# consensus_corrected: the vendor EPS, the ratio (it gives the vendor EPS back from the filed one) and the per-year corrected figures; not the band, the analyst minimum,
# the filed EPS or the filed margin
REMOVED_CORRECTED_PATHS = ("consensus_corrected.vendor_eps", "consensus_corrected.ratio", "consensus_corrected.years", "consensus_corrected.x_margin")


def _floats(obj: Any, path: str = "") -> Iterable[Tuple[float, str]]:
    if isinstance(obj, bool):
        return
    if isinstance(obj, float):
        if math.isfinite(obj) and obj != 0 and obj != int(obj):
            yield obj, path
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _floats(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _floats(v, f"{path}[{i}]")


def _at(obj: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def removed_numbers(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every number of the removed classes: from the removed lines the build recorded and from the removed facts. [{value, origin, kind}] where kind is
    "printed" (the number as the removed line printed it) or "fact" (a fact's value, also tried x 100 when it is a fraction)."""
    out: List[Dict[str, Any]] = []
    src = facts.get("r26_blind_source") or {}
    for r in src.get("removed_lines") or []:
        text = r.get("text") or ""
        if r.get("section") == "DEFAULTS":
            text = text.split(" | ", 1)[0]          # "- key: value | explanation": the value is the fact, the explanation is fixed text (its rule constants are not data)
        for v, tok in numbers_in_text(text):
            out.append({"value": v, "origin": f"{r.get('cls')}:{r.get('section')}:{tok}", "kind": "printed", "unit": unit_class(tok)})

    def add(obj: Any, path: str) -> None:
        for v, p in _floats(obj, path):
            out.append({"value": v, "origin": f"fact:{p}", "kind": "fact"})

    for path in REMOVED_FACT_PATHS + REMOVED_CORRECTED_PATHS:
        add(_at(facts, path), path)
    pid = facts.get("price_implied_defaults")
    if isinstance(pid, dict):
        for name, rec in pid.items():
            if isinstance(rec, dict):
                add(rec.get("value"), f"price_implied_defaults.{name}.value")
    lr = facts.get("long_run") or {}
    for k in REMOVED_LONG_RUN_MEMBERS:
        add(lr.get(k), f"long_run.{k}")
    rp = lr.get("revenue_path")
    if isinstance(rp, list):
        add(rp[1:], "long_run.revenue_path[1:]")
    return out


def _span_of(spans: Sequence[Dict[str, Any]], line_no: int) -> Tuple[str, str]:
    for s in spans:
        if s["start"] <= line_no <= s["end"]:
            return s["cls"], s["section"]
    return "unknown", ""


# a removed fact's unit is not recorded: it is tried in every class a pack prints it in (a fraction also x 100 as a percent; an amount in $B also as $M and $K)
_FACT_CLASSES = (("$", 1.0), ("bare", 1.0), ("x", 1.0), ("%", 1.0), ("B", 1.0), ("M", 1e3), ("K", 1e6))


def _leak_forms(nums: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], List[str]]:
    """{(unit class, form): [origins]}: each removed number to 1-3 significant digits in the unit class it is printed in. A printed number keeps its own class and the
    scale it was printed at ($2.50 is a "$", $2.5M an "M", 2.5x an "x"). A fact has no recorded unit: it is tried as a "$", a bare number, a multiple, a percent, and a $B amount
    (shown in $M or $K at that scale too); a fact that is a fraction is also x 100 as a percent."""
    forms: Dict[Tuple[str, str], List[str]] = {}

    def put(cls: str, x: float, origin: str) -> None:
        for f in sig_forms(x, 6):         # to 6 digits: a copy at the number's own precision is a leak too
            forms.setdefault((cls, f), []).append(origin)

    for n in nums:
        v = n["value"]
        if n["kind"] == "printed":
            put(n.get("unit") or "bare", v, n["origin"])
            continue
        for cls, scale in _FACT_CLASSES:
            put(cls, v * scale, n["origin"])
        if abs(v) <= 1.0:
            put("%", v * 100.0, n["origin"])
    return forms


def _form_hit(forms: Dict[Tuple[str, str], List[str]], tok: str, norm: str, strict: bool = True) -> Optional[List[str]]:
    """The origins of the removed number the token matches: same unit class (a "$" figure and a bare number are one class here: a per-share figure is printed either way)
    and the same digits at the token's own written precision; else None. Not `strict`: the digits alone decide (a filed line's bare figure is in the section's unit, and a
    bare integer has no unit to compare)."""
    if not strict:
        return next((o for (c, f), o in forms.items() if f == norm), None)
    cls = unit_class(tok)
    for c in (("$", "bare") if cls in ("$", "bare") else (cls,)):
        hit = forms.get((c, norm))
        if hit:
            return hit
    return None


def _filed_eps_values(obj: Any) -> Iterable[float]:
    """Every number held under a `filed_eps` key anywhere in the facts: the base-year diluted EPS is filed data, whoever's block carries it."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "filed_eps" and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                yield float(v)
            else:
                yield from _filed_eps_values(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _filed_eps_values(v)


def _filed_support(lines: Sequence[str], classes: Sequence[Tuple[str, str]], facts: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """{form: first section} for the numbers of the filed and derived lines, each at 1-3 significant digits, and for the filed EPS facts (section "filed_eps fact") to 6."""
    support: Dict[str, str] = {}
    for v in _filed_eps_values(facts or {}):
        for f in sig_forms(v, 6):
            support.setdefault(f, "filed_eps fact")
    for line, (cls, sec) in zip(lines, classes):
        if cls in EXCEPTION_CLASSES and not line.startswith("## "):
            for tok, norm, strong in _tokens(line):
                if not norm:
                    continue
                try:
                    v = float(norm)
                except ValueError:
                    continue
                for f in set(sig_forms(v)) | {norm}:
                    support.setdefault(f, sec)
    return support


def r26_leak_audit(blind_pack_text: str, facts: Dict[str, Any]) -> Dict[str, Any]:
    """The leak test of the blind pack. {"pass", "leaks", "exceptions", "weak_matches", "n_removed_numbers", "n_forms", "rule"}.
    A number of a removed class (the removed lines the build recorded and the removed facts) is rendered to 1, 2 and 3 significant digits (a fact that is a fraction also
    x 100); the blind pack is searched for each form, with and without the $ % B M x marks (a token is compared by its digits). Header lines are labels and are not searched.
    An occurrence is, in order: weak, when the token is a bare integer (counted, never failing); an exception on a filed or derived line (the number is a filed or code-owned
    fact: listed once per section and form, with its section named); an exception on a narrative or aggregator line when the same number is also a filed or derived
    line's number at that precision (`filed_source` names the first section that holds it); else a leak. `pass` is true when there is no leak."""
    spans = (facts.get("r26_blind_source") or {}).get("spans") or []
    nums = removed_numbers(facts)
    forms = _leak_forms(nums)
    lines = str(blind_pack_text).split(chr(10))
    classes = [_span_of(spans, i) for i in range(len(lines))]
    # the numbers of the filed and derived lines, each at 1-3 significant digits, with the first section that holds them
    support = _filed_support(lines, classes, facts)
    leaks: List[Dict[str, Any]] = []
    exceptions: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    weak = 0
    for i, line in enumerate(lines):
        if line.startswith("## ") or not line.strip():
            continue
        cls, sec = classes[i]
        for tok, norm, strong in _tokens(line):
            hit = _form_hit(forms, tok, norm, strict=strong and cls not in EXCEPTION_CLASSES)
            if hit is None:
                continue
            if not strong:
                weak += 1
                continue
            source = sec if cls in EXCEPTION_CLASSES else support.get(norm)
            if source is None:
                leaks.append({"line": i, "token": tok, "form": norm, "unit": unit_class(tok), "class": cls, "section": sec, "matches": hit[:3], "text": line[:160]})
                continue
            e = exceptions.setdefault((sec, norm, source), {"section": sec, "class": cls, "form": norm, "filed_source": source, "count": 0, "example": line[:160],
                                                           "matches": hit[:3]})
            e["count"] += 1
    return {"pass": not leaks, "leaks": leaks, "exceptions": sorted(exceptions.values(), key=lambda e: (e["section"], e["form"])),
            "weak_matches": weak, "n_removed_numbers": len(nums), "n_forms": len(forms),
            "rule": "removed-class numbers to 1-3 significant digits; a hit on a filed or derived line, or on another line whose number is also a filed or derived line's, "
                    "is a listed exception; any other hit is a leak; a bare integer is weak"}


# ---- the stage-2 views (cross-check 23, items 3 and 4) --------------------------------------------------------------------------------------------

STAGE2_PACK_CLASSES = (FILED, DERIVED)      # stage 2 reads filed data and code-owned derivations only; narrative and vendor figures reach it through usable facts only


def filed_only_pack(blind_text: str, spans: Sequence[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """(text, report): the blind pack cut to the lines of the filed and derived classes (item 4). `spans` are blind_split's line spans (facts["r26_blind_source"]["spans"]);
    a line no span covers has an unknown class and is cut. A section header is kept only while a body line of its own section (or of a `###` inside it) is kept; runs of blank
    lines collapse to one. report: {"lines_in", "lines_kept", "dropped_by_class", "sections_cut"}."""
    lines = str(blind_text).split("\n")
    cls = [_span_of(spans, i)[0] for i in range(len(lines))]
    keep = [c in STAGE2_PACK_CLASSES for c in cls]
    dropped: Dict[str, int] = {}
    for c, k, ln in zip(cls, keep, lines):
        if not k and ln.strip():
            dropped[c] = dropped.get(c, 0) + 1
    level = [len(m.group(1)) if (m := re.match(r"^(#{2,3}) ", ln)) else 0 for ln in lines]
    sections_cut: List[str] = []
    for i, ln in enumerate(lines):
        if not level[i]:
            continue
        j = i + 1
        while j < len(lines) and not (level[j] and level[j] <= level[i]):
            j += 1
        body = any(keep[k] and not level[k] and lines[k].strip() for k in range(i + 1, j))
        if not body:
            keep[i] = False
            if ln.strip():
                sections_cut.append(ln.lstrip("#").strip().split("   [")[0].strip())
    out: List[str] = []
    for ln, k in zip(lines, keep):
        if not k:
            continue
        if not ln.strip() and (not out or not out[-1].strip()):
            continue
        out.append(ln)
    return "\n".join(out), {"lines_in": len(lines), "lines_kept": len(out), "dropped_by_class": dropped, "sections_cut": sections_cut}


def _number_leak(text: str, forms: Dict[str, List[str]], support: Dict[str, str]) -> Optional[str]:
    """The first strong number of `text` that is a removed-class number with no filed or derived line holding it too, as `removed_class_number:<origin>`; else None."""
    for line in str(text).split("\n"):
        for tok, norm, strong in _tokens(line):
            hit = _form_hit(forms, tok, norm) if strong and norm not in support else None
            if hit:
                return f"removed_class_number:{hit[0]}"
    return None


def text_leaks(text: str, blind_pack_text: str, facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The leaks in `text` (a rendered view): [{"line", "token", "form", "matches"}] - strong numbers equal to a removed-class number that no filed or derived line of the blind
    pack holds (r26_leak_audit's rule, applied to a text that is not the pack)."""
    spans = (facts.get("r26_blind_source") or {}).get("spans") or []
    forms = _leak_forms(removed_numbers(facts))
    plines = str(blind_pack_text).split(chr(10))
    support = _filed_support(plines, [_span_of(spans, i) for i in range(len(plines))], facts)
    out = []
    for i, line in enumerate(str(text).split("\n")):
        for tok, norm, strong in _tokens(line):
            hit = _form_hit(forms, tok, norm) if strong and norm not in support else None
            if hit:
                out.append({"line": i, "token": tok, "form": norm, "matches": hit[:3]})
    return out


def stage2_dossier_view(dossier: Dict[str, Any], blind_pack_text: Optional[str] = None, facts: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(view, audit): the dossier as stage 2 may read it (items 3). The leak audit of the blind pack, applied to what the dossier carries into stage 2:
      the research summary   filtered sentence by sentence: a sentence that names consensus, analysts, a price target, the share price, the market cap or a price multiple
                             (the narrative rule), or holds a removed-class number that no filed line holds, is dropped and listed;
      each fact              a fact whose quote, metric or entity breaks the same rule, or whose quote holds such a number, is WITHHELD from the view (a verbatim quote
                             cannot be cut to a sentence) and listed. The view's `withheld_from_stage2` counts them; stage 2 cannot cite them.
    With no `facts` the number test is not run (stamped `number_audit_not_run`); the sentence rule always is. The input is not changed. The audit holds the drops, the
    withheld facts and the stamps; a later check of the rendered view belongs to the caller (text_leaks)."""
    view = dict(dossier)
    audit: Dict[str, Any] = {"summary_drops": [], "facts_withheld": [], "stamps": []}
    forms = support = None
    if facts is not None and blind_pack_text is not None:
        spans = (facts.get("r26_blind_source") or {}).get("spans") or []
        forms = _leak_forms(removed_numbers(facts))
        plines = str(blind_pack_text).split(chr(10))
        support = _filed_support(plines, [_span_of(spans, i) for i in range(len(plines))], facts)
    else:
        audit["stamps"].append("number_audit_not_run")

    def number_rule(unit: str) -> Optional[str]:
        return _number_leak(unit, forms, support) if forms is not None else None

    text, drops = filter_narrative(str(dossier.get("summary") or ""), "dossier:summary", extra=number_rule)
    view["summary"] = text
    audit["summary_drops"] = drops
    kept, withheld = [], []
    for f in dossier.get("facts") or []:
        why = None
        if isinstance(f, dict) and f.get("usable"):
            for field in ("quote", "metric", "entity"):
                t = str(f.get(field) or "")
                why = names_removed_class(t) or (number_rule(t) if field == "quote" else None)
                if why:
                    why = f"{field}:{why}"
                    break
        if why:
            withheld.append({"fact_id": f.get("fact_id"), "rule": why})
        else:
            kept.append(f)
    view["facts"] = kept
    view["withheld_from_stage2"] = len(withheld)
    audit["facts_withheld"] = withheld
    return view, audit


# ---- the operating-margin bar ------------------------------------------------------------------------------------------------------------------

OP_BAR_LABEL = "filed operating margin, operating income / revenue"
X_BAR_LABEL = "filed X-basis earnings margin, (net income + after-tax amortization of acquired intangibles) / revenue"
OP_BAR_FIELDS = ("operating_income", "revenue")
PERCENTILE_RULE = "linear interpolation between order statistics (position (n-1)q)"
BAR_WINDOW_YEARS = 8        # throughcycle_record.WINDOW_YEARS: the record's window


def _isnum(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def percentile(sorted_vals: Sequence[float], q: float) -> Optional[float]:
    n = len(sorted_vals)
    if n == 0:
        return None
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _bar_stats(years: List[Dict[str, Any]], last_year: Optional[int]) -> Dict[str, Any]:
    vals = sorted(y["margin"] for y in years)
    by_year = {y["fy"]: y["margin"] for y in years}
    return {"n": len(vals), "min": vals[0] if vals else None, "p25": percentile(vals, 0.25), "median": percentile(vals, 0.5), "p75": percentile(vals, 0.75),
            "max": vals[-1] if vals else None, "last": by_year.get(last_year) if last_year is not None else None, "last_year": last_year,
            "percentile_rule": PERCENTILE_RULE}


def op_margin_bar(rows: Dict[Any, Dict[str, Any]], window: int = BAR_WINDOW_YEARS) -> Dict[str, Any]:
    """The operating-margin history bar over the filed window: the last `window` fiscal years ending at the latest filed year of `rows` (fundamentals_history's
    year rows). Per year operating_income / revenue (the fields `operating_income` and `revenue`, the ones DATA 5 prints); a year whose row, operating income or
    positive revenue is not held is listed in `missing` with the reason and is not filled or interpolated. 0.0 is a value. Statistics over the years held."""
    held = sorted(int(y) for y in rows if str(y).isdigit())
    out: Dict[str, Any] = {"basis": "operating", "label": OP_BAR_LABEL, "fields": list(OP_BAR_FIELDS), "window": [None, None], "years": [], "missing": []}
    if not held:
        out.update(_bar_stats([], None))
        return out
    last = held[-1]
    out["window"] = [last - window + 1, last]
    for y in range(last - window + 1, last + 1):
        r = rows.get(str(y)) if str(y) in rows else rows.get(y)
        if not isinstance(r, dict):
            out["missing"].append({"fy": y, "why": "no fiscal-year record held"})
            continue
        rev, oi = r.get("revenue"), r.get("operating_income")
        if not _isnum(oi):
            out["missing"].append({"fy": y, "why": "operating_income not held"})
        elif not (_isnum(rev) and rev > 0):
            out["missing"].append({"fy": y, "why": "revenue not held or not positive"})
        else:
            out["years"].append({"fy": y, "operating_income_b": oi / 1e9, "revenue_b": rev / 1e9, "margin": oi / rev})
    out.update(_bar_stats(out["years"], last))
    return out


def no_filed_operating_income(bar: Dict[str, Any]) -> bool:
    """True when an operating-basis bar holds no year and none of its missing years lacks only revenue: no operating income is filed anywhere in the window."""
    return bar.get("basis") == "operating" and not bar.get("years") and not any(m.get("why") == "revenue not held or not positive" for m in bar.get("missing") or [])


def x_margin_bar(x_history: Optional[Dict[str, Any]], window: int = BAR_WINDOW_YEARS) -> Dict[str, Any]:
    """The same bar on the X basis, for the financial family (a bank or insurer files no operating income): the X-basis margin per filed year as filed
    (x_margin_basis.history's `x_margin`, not the without-one-offs series)."""
    out: Dict[str, Any] = {"basis": "x", "label": X_BAR_LABEL, "fields": ["x_margin_history.years[].x_margin"], "window": [None, None], "years": [], "missing": []}
    hist = x_history if isinstance(x_history, dict) else {}
    last = hist.get("base_year")
    if not _isnum(last):
        out.update(_bar_stats([], None))
        out["missing"].append({"fy": None, "why": "no X-basis history held"})
        return out
    last = int(last)
    out["window"] = [last - window + 1, last]
    got = {int(y["fy"]): y for y in hist.get("years") or [] if _isnum(y.get("x_margin"))}
    skipped = {int(s["fy"]): s.get("why") for s in hist.get("skipped") or []}
    for y in range(last - window + 1, last + 1):
        if y in got:
            out["years"].append({"fy": y, "x_b": got[y].get("x_b"), "revenue_b": got[y].get("revenue_b"), "margin": got[y]["x_margin"]})
        else:
            out["missing"].append({"fy": y, "why": skipped.get(y) or "no fiscal-year record held"})
    out.update(_bar_stats(out["years"], last))
    return out


def _pct(v: Optional[float]) -> str:
    return "not held" if v is None else f"{v * 100:.1f}%"


def op_margin_bar_lines(bar: Dict[str, Any], financial_family: bool) -> List[str]:
    """DATA 5.1's lines (the blind pack prints them): the per-year margins, the missing years stated, the six statistics, and the note that no single default is offered."""
    first, last = bar["window"]
    head = f"## DATA 5.1 - MARGIN HISTORY BAR   [Arithmetic on filed values; fiscal years FY{first}-FY{last}]" if first is not None else "## DATA 5.1 - MARGIN HISTORY BAR   [no fiscal-year record held]"
    lines = [head]
    if "x_basis_no_operating_income" in (bar.get("stamps") or []):
        lines.append("- This company files no operating income in the window, so the bar is on the X basis (the basis of your earnings_margin).")
    elif financial_family:
        lines.append("- This company is in the financial family: it files no operating income, so the bar is on the X basis (the basis of your earnings_margin).")
    per_year = " | ".join(f"FY{y['fy']} {_pct(y['margin'])}" for y in bar["years"])
    lines.append(f"- {bar['label']}, by fiscal year: {per_year if per_year else 'none held'}")
    for m in bar["missing"]:
        lines.append(f"- FY{m['fy']}: not held ({m['why']}); not filled.") if m["fy"] is not None else lines.append(f"- not held ({m['why']}).")
    if bar["n"]:
        lines.append(f"- {bar['label']}, over the {bar['n']} filed year(s) held: min {_pct(bar['min'])} | p25 {_pct(bar['p25'])} | median {_pct(bar['median'])} | "
                     f"p75 {_pct(bar['p75'])} | max {_pct(bar['max'])} | last (FY{bar['last_year']}) {_pct(bar['last'])}   [percentiles: {bar['percentile_rule']}]")
    else:
        lines.append("- no year of the window has a defined margin; no statistic is computed.")
    lines.append("- The bar is the company's own record, not a default: no single line of it is the margin to use.")
    lines.append("")
    return lines


# ---- the basis-corrected consensus (stage 3 only) -----------------------------------------------------------------------------------------------

RATIO_BAND = (0.5, 2.0)
MIN_EPS_ANALYSTS = 3


def _bridge_hook(x_margins: Dict[str, Optional[float]], years: Dict[str, Optional[Dict[str, Any]]], facts: Dict[str, Any], base_year: Optional[int]) -> Dict[str, Any]:
    """The operating-basis equivalent of each X-basis margin, by inverting the bridge at the same year: `r26_forecast.invert_bridge(x_margin, year, facts, revenue=...)`
    (tools/r26_forecast.py, R26-C), with the consensus revenue of that year in $B. {"status": "pending_bridge"} when that module is not importable."""
    try:
        from r26_forecast import invert_bridge          # noqa: WPS433  (R26-C's module; absent until it lands)
    except (ImportError, AttributeError):
        return {"status": "pending_bridge"}
    if base_year is None:
        return {"status": "no_base_year"}
    out: Dict[str, Any] = {}
    for n, label in ((1, "y1"), (2, "y2")):
        x, y = x_margins.get(label), (years or {}).get(label)
        if x is None or not isinstance(y, dict):
            continue
        out[label] = invert_bridge(x, n, facts, revenue=y["revenue_b"])      # n is the path year (1, 2); revenue in $B, the unit of the bridge facts
    return {"status": "inverted", "values": out}


def consensus_corrected(estimates: Optional[Dict[str, Any]], filed_eps: Any, vendor_eps: Any, shares: Any, pi: Any, vendor_break: bool,
                        vintage_aligned: Any = True, shares_agree: bool = True, filed_x_margins: Optional[Dict[str, Any]] = None,
                        bridge_facts: Optional[Dict[str, Any]] = None, base_year: Optional[int] = None,
                        filed_eps_from_pack_shares: bool = False) -> Dict[str, Any]:
    """The vendor's consensus EPS on the filed base year's basis (SPEC section 5): each year's vendor EPS x (filed base-year EPS / the vendor's base-year EPS),
    converted to an X-basis margin on the consensus revenue (x_margin_basis.consensus_margins, the arithmetic of x_margin_consensus_y1y2).
    {"consensus_not_comparable", "reason", "ratio", "ratio_band", "min_eps_analysts", "filed_eps", "vendor_eps", "x_margin": {"y1", "y2"}, "years": {...},
    "operating_basis": {...}}. Not comparable when: the base-year ratio cannot be formed (no vendor or filed EPS, or the vendor's basis is not shown to be the filed one),
    the ratio is outside [0.5, 2], or no year has at least 3 EPS analysts; each year with fewer than 3 EPS analysts or no revenue consensus is stated and has no
    margin. No margin is printed for a not-comparable consensus. 0.0 is a value."""
    import x_margin_basis as xm
    out: Dict[str, Any] = {"consensus_not_comparable": True, "reason": None, "ratio": None, "ratio_band": list(RATIO_BAND), "min_eps_analysts": MIN_EPS_ANALYSTS,
                           "filed_eps": filed_eps if _isnum(filed_eps) else None, "vendor_eps": vendor_eps if _isnum(vendor_eps) else None,
                           "x_margin": {"y1": None, "y2": None}, "years": {"y1": None, "y2": None},
                           "filed_x_margin": filed_x_margins, "operating_basis": {"status": "not_computed"},
                           "stamps": ["filed_eps_from_pack_shares"] if filed_eps_from_pack_shares else []}

    def stop(reason: str) -> Dict[str, Any]:
        out["reason"] = reason
        return out

    if not isinstance(estimates, dict) or not estimates:
        return stop("no consensus estimates")
    if not (_isnum(vendor_eps) and vendor_eps > 0):
        return stop("the vendor's base-year EPS is not held or not positive")
    if not _isnum(filed_eps):
        return stop("the filed base-year EPS cannot be formed (net income or diluted shares missing, or net income zero)")
    if vintage_aligned is not True or not shares_agree:
        return stop("the vendor's figures and the filed ones are not shown to be on one basis (vintage test or share count)")
    ratio = float(filed_eps) / float(vendor_eps)
    out["ratio"] = ratio
    lo, hi = RATIO_BAND
    if not (lo <= ratio <= hi):
        return stop(f"the base-year ratio filed/vendor EPS {ratio:.3f} is outside [{lo:g}, {hi:g}]")
    scaled: Dict[str, Any] = {}
    reasons: Dict[str, Optional[str]] = {}
    for label, key in (("y1", "0y"), ("y2", "+1y")):
        eps = dict(((estimates.get(key) or {}).get("eps")) or {})
        rev = dict(((estimates.get(key) or {}).get("revenue")) or {})
        n = eps.get("analysts")
        if not (_isnum(eps.get("avg")) and n):
            reasons[label] = "no EPS consensus"
        elif int(n) < MIN_EPS_ANALYSTS:
            reasons[label] = f"{int(n)} EPS analyst(s), fewer than {MIN_EPS_ANALYSTS}"
        else:
            reasons[label] = None
        if reasons[label] is None:
            eps["avg"] = float(eps["avg"]) * ratio
        scaled[key] = {"eps": eps if reasons[label] is None else {"analysts": 0}, "revenue": rev}
    cm = xm.consensus_margins(scaled, shares, pi, vendor_break=vendor_break)
    for label in ("y1", "y2"):
        y = cm.get(label)
        if isinstance(y, dict) and reasons[label] is None:
            out["x_margin"][label] = y["x_margin"]
            out["years"][label] = {"eps_vendor": y["eps_avg"] / ratio, "eps_corrected": y["eps_avg"], "eps_analysts": y["eps_analysts"], "revenue_b": y["revenue_b"],
                                   "x_earnings_b": y["x_earnings_b"], "x_margin": y["x_margin"]}
        else:
            why = reasons[label] or ("; ".join(s for s in cm.get("stamps", []) if s.startswith(f"consensus_{label}")) or cm.get("reason") or "no consensus revenue")
            out["years"][label] = {"not_comparable": why}
    if out["x_margin"]["y1"] is None and out["x_margin"]["y2"] is None:
        return stop("no year with at least 3 EPS analysts and a revenue consensus")
    out["consensus_not_comparable"] = False
    out["operating_basis"] = _bridge_hook(dict(out["x_margin"]), out["years"], dict(bridge_facts or {}), base_year)
    return out
