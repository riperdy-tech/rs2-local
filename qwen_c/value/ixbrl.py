"""ixbrl.py - a reader for the inline XBRL of one stored main filing document (WO_UV3 part B).

SEC's companyfacts keeps only the us-gaap, ifrs-full, dei and srt taxonomies and no fact that carries a dimension, and it lags behind
filings. The filing's own document holds every fact it reported: company extension tags, class-of-stock and segment members, and a filing
companyfacts has not ingested. This module only READS those facts, exactly as the document states them; it decides nothing. The rules that
may use a fact, and how each is verified, are in ix_figures.py.

    parse(html) -> Doc        Doc.facts: every readable numeric fact, in document order
    Fact: name ("prefix:LocalName"), start, end (ISO dates; start None for an instant), dims ((axis, member), ...), unit, decimals,
          value (float, scale and sign applied from the tag's own attributes), row (the index of its table row, or None)

What is read, and what is refused (the fact is then absent, never guessed):
- Scale comes from the tag's `scale` attribute and sign from its `sign` attribute; the number's text is read by the format named in the
  tag's `format` attribute (FORMATS below). A format this module does not know, or text that does not read as a number in it, makes
  the fact unreadable.
- A fact with xsi:nil, and a table cell that carries no tag at all, are not values. Only a fact the filer tagged is read: a tagged "-"
  (format zerodash or fixed-zero) is a filed 0.
- A context with a typed dimension is read with its member text as the member; a context that cannot be resolved makes the fact unreadable.
"""
import bisect
import re
from dataclasses import dataclass, field
from datetime import date

IX_VERSION = "m3q.ixbrl.v1"

_CONTEXT = re.compile(r"<(?:\w+:)?context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</(?:\w+:)?context>", re.S)
_EXPLICIT = re.compile(r"<(?:\w+:)?explicitMember\b[^>]*\bdimension=\"([^\"]+)\"[^>]*>\s*([^<\s]+)\s*</", re.S)
_TYPED = re.compile(r"<(?:\w+:)?typedMember\b[^>]*\bdimension=\"([^\"]+)\"[^>]*>(.*?)</(?:\w+:)?typedMember>", re.S)
_DATE = {k: re.compile(r"<(?:\w+:)?%s>\s*(\d{4}-\d{2}-\d{2})\s*</" % k) for k in ("startDate", "endDate", "instant")}
_NONFRACTION = re.compile(r"<ix:nonFraction\b([^>]*?)(/>|>(.*?)</ix:nonFraction>)", re.S)
_ATTR = re.compile(r"([\w:.-]+)=\"([^\"]*)\"")
_ROW = re.compile(r"<tr[\s>]", re.I)
_TABLE = re.compile(r"<table[\s>]", re.I)
_TAGS = re.compile(r"<[^>]+>")
_UNIT = re.compile(r"<(?:\w+:)?unit\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</(?:\w+:)?unit>", re.S)
_MEASURE = re.compile(r"<(?:\w+:)?measure>\s*([^<\s]+)\s*</")

ZERO_FORMATS = ("zerodash", "fixed-zero")            # the tagged "-" or "none" of a statement cell: a filed 0
DOT_FORMATS = ("numdotdecimal", "num-dot-decimal")   # 1,234.56
COMMA_FORMATS = ("numcommadecimal", "num-comma-decimal")   # 1.234,56
# any other format (a space as the thousands mark, words, dates) is not read: the fact is unreadable


@dataclass
class Fact:
    name: str
    start: str
    end: str
    dims: tuple
    unit: str
    decimals: int
    value: float
    row: int
    table: int
    neg: bool        # the statement shows the figure in parentheses (or with a minus sign): an outflow, as printed
    text: str = ""


@dataclass
class Doc:
    facts: list = field(default_factory=list)
    unreadable: int = 0


def _contexts(html):
    out = {}
    for cid, body in _CONTEXT.findall(html):
        dims = [(a, m) for a, m in _EXPLICIT.findall(body)] + [(a, "typed:" + _TAGS.sub("", m).strip()) for a, m in _TYPED.findall(body)]
        d = {k: (rx.search(body).group(1) if rx.search(body) else None) for k, rx in _DATE.items()}
        out[cid] = {"start": d["startDate"], "end": d["endDate"] or d["instant"], "dims": tuple(sorted(dims))}
    return out


def _units(html):
    """{unit id: its measure(s) joined by '/'} from the unit definitions (a divide unit lists the numerator first)."""
    return {uid: "/".join(m.split(":")[-1] for m in _MEASURE.findall(body)) for uid, body in _UNIT.findall(html)}


def number(text, fmt):
    """The float a tag's text states in format `fmt` (the part after the namespace prefix), or None when it does not read in that format."""
    f = (fmt or "").split(":")[-1]
    if f in ZERO_FORMATS:
        return 0.0
    t = text.replace("\xa0", " ").strip()
    if f in DOT_FORMATS or f == "":
        t = t.replace(",", "").replace(" ", "")
    elif f in COMMA_FORMATS:
        t = t.replace(".", "").replace(" ", "").replace(",", ".")
    else:
        return None
    if not re.fullmatch(r"\d+(\.\d*)?|\.\d+", t):
        return None
    return float(t)


def _shown_negative(html, start):
    """Whether the cell holding the tag at `start` prints it in parentheses or after a minus sign (the text before the tag in its cell)."""
    pre = _TAGS.sub("", html[max(html.rfind("<td", 0, start), 0):start]).replace("&#160;", " ").replace(chr(0xA0), " ").strip()
    return pre.endswith(("(", "-", chr(0x2212), chr(0x2013)))


def parse(html):
    """Every readable numeric inline XBRL fact of `html`. Facts that cannot be read are counted in Doc.unreadable, never guessed."""
    ctx, units = _contexts(html), _units(html)
    rows = [m.start() for m in _ROW.finditer(html)]
    tables = [m.start() for m in _TABLE.finditer(html)]
    doc = Doc()
    for m in _NONFRACTION.finditer(html):
        a = dict(_ATTR.findall(m.group(1)))
        if a.get("xsi:nil") == "true" or "name" not in a:
            continue
        inner = m.group(3) or ""
        c = ctx.get(a.get("contextRef"))
        if c is None or c["end"] is None:
            doc.unreadable += 1
            continue
        text = _TAGS.sub("", inner)               # a tag nested in this one (the same figure tagged twice) leaves the printed text
        v = number(text, a.get("format"))
        try:
            scale = int(a.get("scale") or 0)
        except ValueError:
            doc.unreadable += 1
            continue
        if v is None:
            doc.unreadable += 1
            continue
        v *= 10.0 ** scale
        if a.get("sign") == "-":
            v = -v
        dec = a.get("decimals")
        try:
            dec = None if dec in (None, "INF") else int(dec)
        except ValueError:
            doc.unreadable += 1
            continue
        i = bisect.bisect_right(rows, m.start()) - 1
        j = bisect.bisect_right(tables, m.start()) - 1
        doc.facts.append(Fact(a["name"], c["start"], c["end"], c["dims"], units.get(a.get("unitRef"), a.get("unitRef") or ""), dec, v,
                              i if i >= 0 else None, j if j >= 0 else None, _shown_negative(html, m.start()), text.strip()))
    return doc


def duration_days(f):
    try:
        return (date.fromisoformat(f.end) - date.fromisoformat(f.start)).days
    except (TypeError, ValueError):
        return None
