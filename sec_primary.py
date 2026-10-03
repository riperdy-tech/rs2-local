#!/usr/bin/env python3
"""sec_primary.py - the PRIMARY SOURCES section of the data pack (pack revision 21, brief_rev21.md parts P, Q and R).

WHY. 3 of every 4 queries of AT10b's stage 1 went after facts of the company's own documents (its latest earnings release and guidance,
its segment revenue, the exact words of a crux citation), and the pack carried only a 3,000-character outlook excerpt. This module builds,
for a CIK and an as-of date, an ordered list of the company's own SEC filings as VERBATIM text (after HTML cleaning: no paraphrase and no
summary), prints them in the pack as PRIMARY P1, P2, ..., and owns the code-enforced refusals of a search or a fetch for what they hold.

THE ITEMS, in order (ids are sequential, so an absent kind leaves no gap):
  earnings release       the latest 8-K Item 2.02 release exhibit (the exhibit sec_guidance picks), at most RELEASE_CAP characters; when
                         longer, the start, then the paragraphs on outlook, guidance, segments and backlog, then the tables, with every cut
                         marked "[... n characters omitted ...]"
  other exhibits         the other text exhibits of the same 8-K (prepared remarks, CFO commentary, a supplemental exhibit), each at most
                         EXHIBIT_CAP characters; a PDF (an investor presentation) is skipped and annotated
  segment table          the latest 10-Q or 10-K's FilingSummary.xml, then the R report whose ShortName matches /segment/i (a ShortName of
                         "Segment Information" or "Segment Reporting" first, else the first match), flattened to label | value rows, at most
                         SEGMENT_CAP characters; none: annotated "not filed as a separate report"
  other recent 8-Ks      each 8-K filed in the 120 days to the as-of date with item 1.01, 2.01, 2.03, 5.02, 7.01 or 8.01, newest first, at
                         most 4: the item list in its header, the first OTHER_8K_CAP characters of its main exhibit (the 8-K body when it
                         has none)
TOTAL_CAP characters across all items: the oldest other-8-K item is trimmed first, then the other exhibits.

Network: only sec.gov and data.sec.gov, with sec_guidance's User-Agent, under 10 requests per second (THROTTLE_S after every request), and
each accession fetched once and cached forever in cache/sec_primary/. A failure (no CIK, SEC unreachable, nothing filed) is a reason, never
a crash and never silent: the pack prints `PRIMARY SOURCES: not available - <reason>`.

THE CODE-ENFORCED REFUSALS (part R; analyst_tools applies them before a search or fetch is dispatched and does not count the call):
  refuse_fetch   a URL that is a primary item's document is not fetched; a pointer comes back
  refuse_search  a query holding a figure the items hold verbatim, or naming a document word and a period the items cover, is refused
"""
import gzip
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import sec_guidance
from sec_guidance import PAT_SAFE_HARBOR, UA, _clean_html, _has_item_202

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache" / "sec_primary"
SCHEMA = 1

RELEASE_CAP = 14000
EXHIBIT_CAP = 6000
SEGMENT_CAP = 6000
OTHER_8K_CAP = 2500
TOTAL_CAP = 30000
MAX_OTHER_8K = 4
OTHER_8K_DAYS = 120
OTHER_8K_ITEMS = ("1.01", "2.01", "2.03", "5.02", "7.01", "8.01")
MIN_TRIMMED = 600            # a trimmed item shorter than this is dropped
START_CHARS = 3000           # the start of a long release kept before the paragraphs on outlook and the tables
MARKER_RESERVE = 400         # room kept for the omission markers a selection prints
UNIT_MAX = 1200              # a paragraph longer than this is split at sentence ends into units of at most UNIT_TARGET
UNIT_TARGET = 700
THROTTLE_S = 0.15            # one request at a time, well under SEC's 10 requests per second
RAW_MAX = 1_500_000          # the raw characters kept of one document in the cache
ALLOW_STALE_SUBMISSIONS = False   # an offline build reads the last submissions JSON whatever its age (set by the acceptance scripts only)

OMIT = "[… {n:,} characters omitted …]"
OMIT_RE = re.compile(r"\[… [\d,]+ characters omitted …\]")
SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".gif", ".png", ".zip", ".xsd", ".xml", ".json", ".css", ".js", ".xlsx", ".xls", ".svg")

PAT_FORWARD_KEY = re.compile(r"\b(outlook|guidance|reaffirm\w*)\b", re.I)
PAT_KEY = re.compile(r"\b(outlook|guidance|segments?|backlog|bookings|orders|book-to-bill|remaining performance obligations?|RPO)\b", re.I)


# ---- network and cache --------------------------------------------------------------------------------------------------------

def _http_get(url, timeout=60):
    """The bytes of one sec.gov / data.sec.gov URL (an exception on any failure); one request, then the throttle."""
    if not re.match(r"^https://(www\.|data\.)?sec\.gov/", url):
        raise ValueError(f"sec_primary fetches only sec.gov and data.sec.gov, not {url[:60]}")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read(25_000_000)
            time.sleep(THROTTLE_S)
            return data
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(2.0 * (attempt + 1))          # SEC asks a client that is too fast to slow down
    raise OSError("unreachable")


def _subs(cik):
    """The submissions JSON of a CIK (sec_guidance._submissions: cached per UTC day), or None. An offline build (ALLOW_STALE_SUBMISSIONS) falls
    back to the last copy on disk, whatever its age."""
    d = sec_guidance._submissions(cik)
    if d is None and ALLOW_STALE_SUBMISSIONS:
        try:
            return json.loads((sec_guidance.SUB_CACHE / f"CIK{cik}.json").read_text(encoding="utf-8"))
        except Exception:
            return None
    return d


def _cik10(cik):
    return str(cik).zfill(10) if str(cik).isdigit() else str(cik)


def _cache_path(cik, accession):
    return CACHE / f"{_cik10(cik)}_{accession}.json.gz"


def _cache_read(cik, accession):
    p = _cache_path(cik, accession)
    if not p.exists():
        return None
    try:
        d = json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
        return d if d.get("schema") == SCHEMA else None
    except Exception:
        return None


def _cache_write(cik, accession, doc):
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        _cache_path(cik, accession).write_bytes(gzip.compress(json.dumps(doc, ensure_ascii=False).encode("utf-8"), 6))
    except Exception as e:
        print(f"[sec_primary] failed writing cache for {accession}: {e}", file=sys.stderr)


def _base_url(cik, accession):
    try:
        c = int(cik)
    except (ValueError, TypeError):
        c = cik
    return f"https://www.sec.gov/Archives/edgar/data/{c}/{accession.replace('-', '')}"


def _doc_text(raw):
    """The body of a document the way EDGAR wraps it: the <TEXT> section when the raw string is a <DOCUMENT> wrapper (this archive serves its
    report pages that way), else the string itself."""
    if re.match(r"\s*<DOCUMENT>", raw, flags=re.I):
        m = re.search(r"<TEXT>(.*?)(?:</TEXT>|\Z)", raw, flags=re.S | re.I)
        return m.group(1) if m else raw
    return raw


# ---- HTML to blocks -----------------------------------------------------------------------------------------------------------

_POSITIONED = re.compile(r"position\s*:\s*(absolute|var\()", re.I)
_HIDDEN = re.compile(r"display\s*:\s*none", re.I)
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "blockquote", "pre", "hr", "center", "section", "article",
               "header", "footer", "dd", "dt", "dl", "body", "html"}
_VOID = {"br", "img", "hr", "meta", "link", "input", "col", "wbr", "area", "base", "param", "source", "track"}


class _Extract(HTMLParser):
    """Blocks of a filing's HTML: ("p", text) paragraphs and ("t", [row text, ...]) tables. Inline tags (span, font, b, i, a) join their text
    without a space, as the page shows it; a block tag ends a paragraph; a positioned div (a line of a PDF-like page) is a line, not a paragraph.
    Hidden subtrees, scripts and styles are dropped. A table becomes one row per tr, its non-empty cells joined by ' | ', with a lone '$'
    attached to the next cell and a lone ')' or '%' to the previous one."""

    def __init__(self, positioned_divs_break=False):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.par = []
        self.skip_tag, self.skip_depth = None, 0
        self.tdepth = 0
        self.rows, self.row, self.cell = [], [], []
        self.in_cell = False
        self._pdb = positioned_divs_break

    # -- text pieces
    def _flush_par(self):
        t = re.sub(r"\s+", " ", "".join(self.par).replace("\xa0", " ")).strip()
        self.par = []
        if t:
            self.blocks.append(("p", t))

    def _flush_cell(self):
        t = re.sub(r"\s+", " ", "".join(self.cell).replace("\xa0", " ")).strip()
        self.cell = []
        if t:
            self.row.append(t)
        self.in_cell = False

    def _flush_row(self):
        if self.in_cell or self.cell:
            self._flush_cell()
        cells = _merge_cells(self.row)
        self.row = []
        if cells:
            self.rows.append(" | ".join(cells))

    def _flush_table(self):
        self._flush_row()
        if self.rows:
            self.blocks.append(("t", self.rows))
        self.rows = []

    def _put(self, s):
        (self.cell if self.tdepth > 0 else self.par).append(s)

    # -- events
    def handle_starttag(self, tag, attrs):
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        style = next((v or "" for k, v in attrs if k == "style"), "")
        if tag in ("script", "style", "title") or (_HIDDEN.search(style) and tag not in _VOID):
            self.skip_tag, self.skip_depth = tag, 1
            return
        if tag == "table":
            if self.tdepth == 0:
                self._flush_par()
            elif self.cell:
                self._flush_cell()
            self.tdepth += 1
        elif tag == "tr" and self.tdepth > 0:
            self._flush_row()
        elif tag in ("td", "th") and self.tdepth > 0:
            if self.in_cell or self.cell:
                self._flush_cell()
            self.in_cell = True
        elif tag == "br":
            self._put(" ")
        elif tag == "div":
            if self.tdepth > 0 or (_POSITIONED.search(style) and not self._pdb):
                self._put(" ")
            else:
                self._flush_par()
        elif tag in _BLOCK_TAGS:
            if self.tdepth > 0:
                self._put(" ")
            else:
                self._flush_par()

    def handle_endtag(self, tag):
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth <= 0:
                    self.skip_tag, self.skip_depth = None, 0
            return
        if tag == "table" and self.tdepth > 0:
            self.tdepth -= 1
            if self.tdepth == 0:
                self._flush_table()
        elif tag == "tr" and self.tdepth > 0:
            self._flush_row()
        elif tag in ("td", "th") and self.tdepth > 0:
            self._flush_cell()
        elif tag == "div":
            if self.tdepth > 0 or not self._pdb:
                self._put(" ")
            else:
                self._flush_par()
        elif tag in _BLOCK_TAGS:
            if self.tdepth > 0:
                self._put(" ")
            else:
                self._flush_par()

    def handle_data(self, data):
        if self.skip_tag is None:
            self._put(data)

    def close(self):
        super().close()
        if self.tdepth > 0:
            self.tdepth = 0
            self._flush_table()
        self._flush_par()


def _merge_cells(cells):
    """['$', '1,234', ')'] -> ['$1,234)']: the stray currency, bracket and percent cells of an EDGAR table join their number."""
    out = []
    pending = ""
    for c in cells:
        if c in ("$", "€", "£"):
            pending += c
            continue
        if c in (")", "%", ")%", "%)", "*") and out:
            out[-1] += c
            continue
        out.append(pending + c)
        pending = ""
    if pending:
        out.append(pending)
    return out


def blocks_of(raw, positioned_divs_break=False):
    """The blocks of a document string (HTML or plain text), `_Extract`'s. Plain text with no tag is one paragraph per blank-line-separated chunk."""
    body = _doc_text(raw)
    if not re.search(r"<[a-zA-Z/!]", body):
        return [("p", re.sub(r"\s+", " ", c.replace("\xa0", " ")).strip()) for c in re.split(r"\n\s*\n", html.unescape(body))
                if c.strip()]
    ex = _Extract(positioned_divs_break)
    try:
        ex.feed(body)
        ex.close()
    except Exception:
        ex.blocks = ex.blocks or [("p", _clean_html(body))]
    return ex.blocks


def _units(blocks):
    """The selection units of a document: a table is one unit (its rows joined by newlines); a paragraph longer than UNIT_MAX is split at
    sentence ends into units of about UNIT_TARGET characters (a page laid out in positioned lines has no paragraph breaks)."""
    out = []
    for kind, content in blocks:
        if kind == "t":
            out.append(("t", "\n".join(content)))
            continue
        text = content
        if len(text) <= UNIT_MAX:
            out.append(("p", text))
            continue
        sents = re.split(r"(?<=[.;!?])\s+(?=[A-Z•\"(“])", text)
        cur = ""
        for s in sents:
            if cur and len(cur) + 1 + len(s) > UNIT_TARGET:
                out.append(("p", cur))
                cur = s
            else:
                cur = f"{cur} {s}" if cur else s
            while len(cur) > UNIT_MAX:           # a sentence with no break: cut at a space
                k = cur.rfind(" ", 0, UNIT_TARGET)
                k = k if k > 0 else UNIT_TARGET
                out.append(("p", cur[:k]))
                cur = cur[k:].lstrip()
        if cur:
            out.append(("p", cur))
    return out


def select_text(blocks, cap):
    """The text of a document within `cap` characters, markers included. Whole when it fits. Otherwise, in document order: the start (about
    START_CHARS characters); then the paragraphs on outlook or guidance, then those on segments, backlog, bookings and orders (never a
    safe-harbor paragraph), as many whole ones as fit; then the tables (those that mention segments, backlog or orders first), a table that
    does not fit with as many leading rows as do. Every gap is one marker line `[... n characters omitted ...]` with the characters it
    leaves out."""
    units = _units(blocks)
    total = sum(len(t) + 1 for _, t in units) - 1 if units else 0
    if total <= cap:
        return "\n".join(t for _, t in units)
    budget = cap - MARKER_RESERVE
    chosen = {}          # unit index -> text kept

    def room():
        return budget - sum(len(t) + 1 for t in chosen.values())

    start = 0
    for i, (kind, t) in enumerate(units):
        if start >= min(START_CHARS, budget // 4):
            break
        take = t if len(t) + 1 <= room() else t[:max(0, room() - 1)]
        if not take:
            break
        chosen[i] = take
        start += len(take) + 1
        if len(take) < len(t):
            break
    for group in (0, 1):
        for i, (kind, t) in enumerate(units):
            if kind != "p" or i in chosen or PAT_SAFE_HARBOR.search(t):
                continue
            hit = PAT_FORWARD_KEY.search(t) if group == 0 else (PAT_KEY.search(t) and not PAT_FORWARD_KEY.search(t))
            if hit and len(t) + 1 <= room():
                chosen[i] = t
    tables = [(0 if PAT_KEY.search(t) else 1, i) for i, (kind, t) in enumerate(units) if kind == "t" and i not in chosen]
    for _, i in sorted(tables):
        t = units[i][1]
        if len(t) + 1 <= room():
            chosen[i] = t
            continue
        rows = t.split("\n")
        keep, used = [], 0
        for r in rows:
            if used + len(r) + 1 > room():
                break
            keep.append(r)
            used += len(r) + 1
        if len(keep) >= 3:
            chosen[i] = "\n".join(keep)
    for i, (kind, t) in enumerate(units):            # the room that is left goes to the rest of the paragraphs in document order (never a safe-harbor one)
        if kind == "p" and i not in chosen and not PAT_SAFE_HARBOR.search(t) and len(t) + 1 <= room():
            chosen[i] = t
    text = _assemble(units, chosen)
    while len(text) > cap and chosen:                # the markers outgrew the reserve: drop the last additions
        chosen.pop(max(chosen))
        text = _assemble(units, chosen)
    return text


def _assemble(units, chosen):
    """The kept units in document order, a gap between them one marker line with the characters it leaves out; a gap no longer than its marker
    is kept as text instead (a marker for a dozen characters says less than the characters)."""
    out, run, n_run = [], [], 0

    def close():
        nonlocal run, n_run
        if run:
            total = sum(len(t) + 1 for t in run)
            if total <= len(OMIT.format(n=total)) + 1:
                out.extend(run)
            else:
                out.append(OMIT.format(n=total))
        run = []

    for i, (kind, t) in enumerate(units):
        if i not in chosen:
            run.append(t)
            continue
        close()
        out.append(chosen[i])
        if len(chosen[i]) < len(t):
            run = [t[len(chosen[i]):]]
    close()
    return "\n".join(out)


def prefix_text(text, cap):
    """The first characters of `text` within `cap`, marker included: cut at the last line end or space; a text that fits is returned whole."""
    if len(text) <= cap:
        return text
    marker_room = len(OMIT.format(n=len(text))) + 1
    k = max(0, cap - marker_room)
    cut = max(text.rfind("\n", 0, k), text.rfind(" ", 0, k))
    cut = cut if cut > k // 2 else k
    kept = text[:cut].rstrip()
    return kept + "\n" + OMIT.format(n=len(text) - len(kept))


def canonical(text):
    """Lines stripped, empty ones dropped: the form an item's text is stored, hashed and printed in, so that parsing the pack gives it back."""
    return "\n".join(l.strip() for l in (text or "").split("\n") if l.strip())


# ---- the period of a filing ---------------------------------------------------------------------------------------------------

_QWORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
_MONTHS = {"january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
           "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10, "november": 11,
           "nov": 11, "december": 12, "dec": 12}
_MON_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))


def _yr(s):
    n = int(s)
    return n if n >= 100 else 2000 + n


def release_period(text):
    """A fiscal-period label for an earnings release, from its opening (the first 4,000 characters): `Q2 2026` (second quarter 2026, 2Q26, Q2 FY26,
    fiscal 2026 second quarter; or a quarter named without its year beside `quarter ended June 30, 2026`, which gives the year), `FY 2026` (full
    year, fiscal year) or `period ended 2026-06-30` (three, six, nine or twelve months ended); None when the opening names none. A quarter and its
    year together win over a year alone; within a kind the earliest mention wins."""
    head = (text or "")[:4000]
    q = r"(first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter"
    yr4 = r"((?:19|20)\d{2})"
    found = []                                                      # (rank, position, label)
    for m in re.finditer(r"\b" + q + r"\s*(?:of\s*)?(?:fiscal\s*)?(?:year\s*)?(?:fy\s*)?'?" + yr4 + r"\b", head, re.I):
        found.append((0, m.start(), f"Q{_QWORD[m.group(1).lower()]} {m.group(2)}"))
    for m in re.finditer(r"\bfiscal\s*(?:year\s*)?" + yr4 + r"\s+" + q + r"\b", head, re.I):
        found.append((0, m.start(), f"Q{_QWORD[m.group(2).lower()]} {m.group(1)}"))
    for m in re.finditer(r"\b" + yr4 + r"\s+" + q + r"\b", head, re.I):
        found.append((0, m.start(), f"Q{_QWORD[m.group(2).lower()]} {m.group(1)}"))
    for m in re.finditer(r"\bQ([1-4])\s*[-/']?\s*(?:FY\s*)?'?((?:19|20)\d{2}|\d{2})\b", head):
        found.append((0, m.start(), f"Q{m.group(1)} {_yr(m.group(2))}"))
    for m in re.finditer(r"\b([1-4])Q\s*'?((?:19|20)\d{2}|\d{2})\b", head):
        found.append((0, m.start(), f"Q{m.group(1)} {_yr(m.group(2))}"))
    if not found:
        qm = re.search(r"\b" + q + r"\b", head, re.I)
        dm = re.search(r"\bquarter\s+(?:ended|ending)\s+(?:" + _MON_RE + r")\.?\s+\d{1,2},?\s+" + yr4, head, re.I)
        if qm and dm:
            found.append((1, qm.start(), f"Q{_QWORD[qm.group(1).lower()]} {dm.group(1)}"))
    for m in re.finditer(r"\b(?:full[- ]year|fiscal(?:\s+year)?)\s*'?" + yr4 + r"\b", head, re.I):
        found.append((3, m.start(), f"FY {m.group(1)}"))
    if found:
        return min(found)[2]
    m = re.search(r"\b(?:three|six|nine|twelve)\s+months\s+ended\s+(" + _MON_RE + r")\.?\s+(\d{1,2}),?\s+" + yr4, head, re.I)
    if m:
        return f"period ended {int(m.group(3)):04d}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    return None


# ---- per-accession fetching ---------------------------------------------------------------------------------------------------

def _split_documents(raw):
    """[(type, filename, text)] of a full EDGAR submission .txt."""
    docs = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", raw, flags=re.S | re.I) or re.split(r"(?i)<DOCUMENT>", raw)[1:]
    out = []
    for d in docs:
        t = re.search(r"<TYPE>\s*([^\r\n<]+)", d, re.I)
        f = re.search(r"<FILENAME>\s*([^\r\n<]+)", d, re.I)
        tm = re.search(r"<TEXT>(.*?)(?:</TEXT>|\Z)", d, flags=re.S | re.I)
        out.append((t.group(1).strip() if t else "", f.group(1).strip() if f else "", tm.group(1) if tm else d))
    return out


def _is_text_exhibit(dtype, filename):
    t = dtype.upper()
    if filename.lower().endswith(SKIP_EXT):
        return False
    return t in ("8-K", "8-K/A") or (t.startswith("EX-") and not t.startswith(("EX-101", "EX-104")))


def fetch_8k(cik, accession):
    """The documents of one 8-K, from the cache or one request: {"schema", "accession", "docs": [{"type", "filename", "raw"} for a text
    document, {"type", "filename", "skipped": "pdf" or the extension} for a document not kept]}, or None on a failed fetch (nothing cached)."""
    got = _cache_read(cik, accession)
    if got is not None:
        return got
    try:
        raw = _http_get(f"{_base_url(cik, accession)}/{accession}.txt").decode("utf-8", "replace")
    except Exception as e:
        print(f"[sec_primary] failed fetching {accession}: {str(e)[:120]}", file=sys.stderr)
        return None
    docs = []
    for dtype, fname, text in _split_documents(raw):
        if _is_text_exhibit(dtype, fname):
            docs.append({"type": dtype, "filename": fname, "raw": text[:RAW_MAX]})
        elif fname.lower().endswith(".pdf"):
            docs.append({"type": dtype, "filename": fname, "skipped": "pdf"})
    if not docs:
        print(f"[sec_primary] no text document in {accession}", file=sys.stderr)
        return None
    got = {"schema": SCHEMA, "kind": "8k", "accession": accession, "docs": docs}
    _cache_write(cik, accession, got)
    return got


def _short_names(summary_xml):
    """[(ShortName, HtmlFileName)] of a FilingSummary.xml, in file order."""
    out = []
    for m in re.finditer(r"<Report\b[^>]*>(.*?)</Report>", summary_xml, flags=re.S | re.I):
        b = m.group(1)
        sn = re.search(r"<ShortName>(.*?)</ShortName>", b, flags=re.S | re.I)
        hf = re.search(r"<HtmlFileName>(.*?)</HtmlFileName>", b, flags=re.S | re.I)
        if sn and hf:
            out.append((html.unescape(re.sub(r"\s+", " ", sn.group(1))).strip(), hf.group(1).strip()))
    return out


def pick_segment_report(summary_xml):
    """(ShortName, HtmlFileName) of the segment report: the first whose ShortName is "Segment Information" or "Segment Reporting"
    (case-insensitive), else the first that matches /segment/i; None when none does."""
    names = _short_names(summary_xml)
    for sn, hf in names:
        if re.fullmatch(r"segment (information|reporting)", sn, re.I):
            return sn, hf
    for sn, hf in names:
        if re.search(r"segment", sn, re.I):
            return sn, hf
    return None


def fetch_periodic(cik, accession):
    """The pieces of one 10-Q or 10-K: {"schema", "kind": "periodic", "accession", "summary": FilingSummary.xml or None, "cover": R1.htm raw or
    None, "segment": {"short_name", "file", "raw"} or None}, from the cache or up to three requests; None when FilingSummary.xml cannot be had."""
    got = _cache_read(cik, accession)
    if got is not None:
        return got
    base = _base_url(cik, accession)
    try:
        summary = _http_get(f"{base}/FilingSummary.xml").decode("utf-8", "replace")
    except Exception as e:
        print(f"[sec_primary] failed fetching FilingSummary of {accession}: {str(e)[:120]}", file=sys.stderr)
        return None
    cover = None
    try:
        cover = _http_get(f"{base}/R1.htm").decode("utf-8", "replace")[:RAW_MAX]
    except Exception:
        pass
    seg = None
    pick = pick_segment_report(summary)
    if pick is not None:
        try:
            seg = {"short_name": pick[0], "file": pick[1], "raw": _http_get(f"{base}/{pick[1]}").decode("utf-8", "replace")[:RAW_MAX]}
        except Exception as e:
            print(f"[sec_primary] failed fetching {pick[1]} of {accession}: {str(e)[:120]}", file=sys.stderr)
            return None
    got = {"schema": SCHEMA, "kind": "periodic", "accession": accession, "summary": summary, "cover": cover, "segment": seg}
    _cache_write(cik, accession, got)
    return got


def periodic_period(cover_raw, report_date):
    """`Q2 2026` or `FY 2025` from the filing's cover report (Document Fiscal Period Focus and Year Focus), else `period ended <date>`, else None."""
    if cover_raw:
        rows = " ".join(r for k, c in blocks_of(cover_raw) if k == "t" for r in c)
        fp = re.search(r"Document Fiscal Period Focus \| (Q[1-4]|FY|H[12]|[A-Z0-9]{1,3})\b", rows)
        fy = re.search(r"Document Fiscal Year Focus \| ((?:19|20)\d{2})\b", rows)
        if fp and fy:
            return f"FY {fy.group(1)}" if fp.group(1) == "FY" else f"{fp.group(1)} {fy.group(1)}"
    if report_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(report_date)):
        return f"period ended {report_date}"
    return None


# ---- the build ----------------------------------------------------------------------------------------------------------------

def _asof_str(asof):
    if hasattr(asof, "isoformat"):
        return asof.isoformat()[:10]
    return str(asof)[:10] if asof is not None else datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _filings(subs, asof_s):
    """The recent filings of a submissions JSON dated on or before `asof_s`, as dicts, in the file's order (newest first)."""
    rec = (subs.get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    out = []
    for i, f in enumerate(forms):
        def col(name):
            v = rec.get(name) or []
            return v[i] if i < len(v) else ""
        dt = col("filingDate")
        if not dt or dt > asof_s or not col("accessionNumber"):
            continue
        out.append({"i": i, "form": f, "filed": dt, "report_date": col("reportDate"), "items": col("items"),
                    "accession": col("accessionNumber"), "primary_document": col("primaryDocument")})
    return out


def _items_list(val):
    if not val:
        return []
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if str(x).strip()]
    return [p for p in re.split(r"[,;\s]+", str(val).strip()) if p]


def _newest(rows):
    return sorted(rows, key=lambda r: (r["filed"], -r["i"]), reverse=True)


def _doc_url(cik, accession, filename):
    return f"{_base_url(cik, accession)}/{filename}"


def _release_doc(docs):
    """The exhibit sec_guidance's rule picks (EX-99.1, EX-99.01, EX-99, in that order) among the kept text documents."""
    for want in ("EX-99.1", "EX-99.01", "EX-99"):
        for d in docs:
            if d["type"].upper() == want and "raw" in d:
                return d
    return None


def _item(type_, form, accession, filed, period, url, title, text):
    return {"type": type_, "form": form, "accession": accession, "filed": filed, "period": period, "url": url, "title": title,
            "text": canonical(text)}


def build(cik, asof=None):
    """{"items": [...], "annotations": [str], "reason": None or "<why nothing is available>"} for a CIK and an as-of date (an ISO string or a
    date; None is today, UTC). Each item is {"id", "type", "form", "accession", "filed", "period", "url", "title", "text"}. Only filings dated
    on or before the as-of date are used. Never raises."""
    try:
        return _build(cik, asof)
    except Exception as e:                      # a failure is a reason in the pack, never a crash
        print(f"[sec_primary] build failed for CIK {cik}: {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
        return {"items": [], "annotations": [], "reason": f"error while building: {type(e).__name__}"}


def _build(cik, asof):
    out = {"items": [], "annotations": [], "reason": None}
    if not cik:
        out["reason"] = "no CIK"
        return out
    asof_s = _asof_str(asof)
    subs = _subs(cik)
    if not subs:
        out["reason"] = "SEC fetch failed (submissions)"
        return out
    filings = _filings(subs, asof_s)
    items, notes = [], out["annotations"]

    # P: the earnings release, and the other text exhibits of its 8-K
    rel_rows = _newest([f for f in filings if f["form"] in ("8-K", "8-K/A") and _has_item_202(f["items"])])
    rel_acc = None
    if not rel_rows:
        notes.append(f"No 8-K Item 2.02 earnings release on or before {asof_s}.")
    else:
        r = rel_rows[0]
        rel_acc = r["accession"]
        got = fetch_8k(cik, r["accession"])
        d = _release_doc(got["docs"]) if got else None
        if got is None:
            notes.append(f"The 8-K Item 2.02 filed {r['filed']} (accession {r['accession']}) could not be fetched from SEC.")
        elif d is None:
            notes.append(f"The 8-K Item 2.02 filed {r['filed']} (accession {r['accession']}) has no EX-99.1, EX-99.01 or EX-99 text exhibit.")
        else:
            blocks = blocks_of(d["raw"])
            period = release_period(" ".join(c if k == "p" else " ".join(c) for k, c in blocks[:15]))
            text = select_text(blocks, RELEASE_CAP)
            items.append(_item("earnings_release", r["form"], r["accession"], r["filed"], period,
                               _doc_url(cik, r["accession"], d["filename"]), f"{r['form']} Item 2.02 earnings release ({d['type']})", text))
            for x in got["docs"]:
                if x is d:
                    continue
                if "raw" not in x:
                    notes.append(f"{x['filename']} (a PDF exhibit of the same 8-K, such as an investor presentation, accession {r['accession']}) "
                                 f"is a PDF and is not included.")
                    continue
                if x["type"].upper().startswith("EX-99"):
                    t = select_text(blocks_of(x["raw"]), EXHIBIT_CAP)
                    if t:
                        items.append(_item("other_exhibit", r["form"], r["accession"], r["filed"], period,
                                           _doc_url(cik, r["accession"], x["filename"]), f"{r['form']} Item 2.02 other exhibit ({x['type']})", t))

    # P: the segment table of the latest 10-Q or 10-K
    per_rows = _newest([f for f in filings if f["form"] in ("10-Q", "10-K")])
    if not per_rows:
        notes.append(f"No 10-Q or 10-K on or before {asof_s}.")
    else:
        p = per_rows[0]
        got = fetch_periodic(cik, p["accession"])
        if got is None:
            notes.append(f"The {p['form']} filed {p['filed']} (accession {p['accession']}) could not be fetched from SEC.")
        elif not got.get("segment"):
            notes.append(f"The {p['form']} filed {p['filed']} (accession {p['accession']}): the segment table is not filed as a separate report.")
        else:
            seg = got["segment"]
            rows = []
            for k, c in blocks_of(seg["raw"]):
                rows += c if k == "t" else [c]
            text = prefix_text("\n".join(rows), SEGMENT_CAP)
            items.append(_item("segment_table", p["form"], p["accession"], p["filed"], periodic_period(got.get("cover"), p["report_date"]),
                               _doc_url(cik, p["accession"], seg["file"]), f"{p['form']} segment table ({seg['file']}, \"{seg['short_name']}\")", text))

    # P: the other recent 8-Ks
    cutoff = (datetime.strptime(asof_s, "%Y-%m-%d") - timedelta(days=OTHER_8K_DAYS)).strftime("%Y-%m-%d")
    other = [f for f in _newest(filings) if f["form"] in ("8-K", "8-K/A") and f["filed"] >= cutoff and f["accession"] != rel_acc
             and set(_items_list(f["items"])) & set(OTHER_8K_ITEMS)]
    for f in other[:MAX_OTHER_8K]:
        got = fetch_8k(cik, f["accession"])
        if got is None:
            notes.append(f"The 8-K filed {f['filed']} (accession {f['accession']}) could not be fetched from SEC.")
            continue
        ex = next((x for x in got["docs"] if x["type"].upper().startswith("EX-") and "raw" in x
                   and re.match(r"EX-99|EX-2|EX-10|EX-1\.", x["type"].upper())), None)
        ex = ex or next((x for x in got["docs"] if x["type"].upper().startswith("EX-") and "raw" in x), None)
        ex = ex or next((x for x in got["docs"] if "raw" in x), None)
        if ex is None:
            continue
        blocks = blocks_of(ex["raw"])
        if not ex["type"].upper().startswith("EX-"):          # an 8-K body opens with its cover page: start at the item text
            item_re = re.compile(r"Item\s+(%s)\b" % "|".join(re.escape(i) for i in OTHER_8K_ITEMS))
            blocks = blocks[next((n for n, (k, c) in enumerate(blocks) if k == "p" and item_re.match(c)), 0):]
        text = prefix_text("\n".join(c if k == "p" else "\n".join(c) for k, c in blocks), OTHER_8K_CAP)
        its = [i for i in _items_list(f["items"])]
        where = ex["type"] if ex["type"].upper().startswith("EX-") else "8-K body"
        items.append(_item("other_8k", f["form"], f["accession"], f["filed"], None, _doc_url(cik, f["accession"], ex["filename"]),
                           f"{f['form']} Item{'s' if len(its) != 1 else ''} {', '.join(its)} ({where})", text))

    items = _trim(items, notes)
    items = [i for i in items if i["text"]]
    for n, it in enumerate(items, 1):
        it["id"] = f"P{n}"
    if not items:
        out["reason"] = f"no 8-K Item 2.02, 10-Q, 10-K or recent 8-K text on or before {asof_s}"
    out["items"] = items
    return out


def _trim(items, notes):
    """TOTAL_CAP across all items: the oldest other-8-K item is cut first, then the other exhibits (the last first); an item cut below
    MIN_TRIMMED characters is dropped. The cut item keeps its start and ends with an omission marker."""
    def total():
        return sum(len(i["text"]) for i in items)
    order = [i for i in sorted([i for i in items if i["type"] == "other_8k"], key=lambda i: i["filed"])]
    order += [i for i in reversed([i for i in items if i["type"] == "other_exhibit"])]
    for it in order:
        excess = total() - TOTAL_CAP
        if excess <= 0:
            break
        room = len(it["text"]) - excess
        if room < MIN_TRIMMED:
            items.remove(it)
            notes.append(f"{it['title']} (accession {it['accession']}) was left out to keep the section within {TOTAL_CAP:,} characters.")
        else:
            it["text"] = canonical(prefix_text(it["text"], room))
            notes.append(f"{it['title']} (accession {it['accession']}) was shortened to keep the section within {TOTAL_CAP:,} characters.")
    return items


# ---- the pack text ------------------------------------------------------------------------------------------------------------

SECTION_HEADER = "## PRIMARY SOURCES   [the company's own SEC filings, verbatim; cite as PRIMARY P#]"
INTRO = ("Each item below is a company filing's text as filed (HTML cleaned, nothing paraphrased); a quoted line starts with `> `. Cite an item as "
         "source `PRIMARY P#` (for example `PRIMARY P1`) with the quote copied exactly from its text.")


def item_header(it):
    return (f"[{it['id']}] {it['title']}, filed {it['filed']}, accession {it['accession']}, "
            f"period {it['period'] if it.get('period') else 'not stated'}, {it['url']}")


def section_lines(res):
    """The lines of the PRIMARY SOURCES section (header first), for a `build` result."""
    L = [SECTION_HEADER]
    if not res["items"]:
        L.append(f"PRIMARY SOURCES: not available — {res.get('reason') or 'no reason recorded'}")
        L += [f"- {n}" for n in res.get("annotations") or []]
        return L
    L.append(INTRO)
    for it in res["items"]:
        L.append("")
        L.append(item_header(it))
        L += [f"> {line}" for line in it["text"].split("\n")]
    if res.get("annotations"):
        L.append("")
        L += [f"- {n}" for n in res["annotations"]]
    return L


_HEAD_RE = re.compile(r"^\[P(\d+)\] (.+?), filed (\d{4}-\d{2}-\d{2}), accession (\S+), period (.+?), (https?://\S+)$")


def _title_form_type(title):
    form = title.split(" ", 1)[0]
    if "earnings release" in title:
        return form, "earnings_release"
    if "other exhibit" in title:
        return form, "other_exhibit"
    if "segment table" in title:
        return form, "segment_table"
    return form, "other_8k"


def parse_pack(pack_text):
    """The primary items a pack prints, [{"id", "type", "form", "accession", "filed", "period", "url", "title", "text"}], from its PRIMARY SOURCES
    section (an empty list when the pack has none or prints `not available`). The inverse of `section_lines`."""
    lines = (pack_text or "").split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("## PRIMARY SOURCES")), None)
    if start is None:
        return []
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    items, cur = [], None
    for l in lines[start + 1:end]:
        m = _HEAD_RE.match(l)
        if m:
            form, typ = _title_form_type(m.group(2))
            cur = {"id": f"P{m.group(1)}", "type": typ, "form": form, "accession": m.group(4), "filed": m.group(3),
                   "period": None if m.group(5) == "not stated" else m.group(5), "url": m.group(6), "title": m.group(2), "_lines": []}
            items.append(cur)
        elif cur is not None and l.startswith("> "):
            cur["_lines"].append(l[2:])
        elif cur is not None and l.strip() == "":
            cur = None if cur["_lines"] else cur
    for it in items:
        it["text"] = "\n".join(it.pop("_lines"))
    return items


def facts_items(items):
    """The facts sidecar's `primary_sources`: per item, its id, type, form, accession, filed, period, url, the sha256 of its text and its
    character count."""
    return [{"id": i["id"], "type": i["type"], "form": i["form"], "accession": i["accession"], "filed": i["filed"], "period": i.get("period"),
             "url": i["url"], "sha256": hashlib.sha256(i["text"].encode("utf-8")).hexdigest(), "chars": len(i["text"])} for i in items]


# ---- what a citation of a primary source names (Q1) ---------------------------------------------------------------------------

_SRC_RE = re.compile(r"^\s*(?:PRIMARY(?:\s+SOURCES?)?)?\s*[:#\-–—(\[]*\s*P\s*(\d+)\b", re.I)
_PRIMARY_ONLY_RE = re.compile(r"^\s*PRIMARY(?:\s+SOURCES?)?\s*$", re.I)


def _url_key(u):
    s = re.sub(r"^https?://(www\.)?", "", (u or "").strip(), flags=re.I)
    return s.split("#", 1)[0].rstrip("/").lower()


def _acc_in(url, accession):
    u = (url or "").lower()
    return accession.lower() in u or accession.replace("-", "").lower() in u


def resolve_source(source, items, quote=None):
    """The primary item a citation's `source` names, or None. `PRIMARY P1`, `P1` and `PRIMARY SOURCES P1` (case, `#`, `:` and brackets
    ignored) name P1; a bare `PRIMARY` names the first item that holds the quote; a URL whose accession or whose address equals an item's
    names that item (the URL the model knows is not refused)."""
    s = (source or "").strip()
    if not s or not items:
        return None
    m = _SRC_RE.match(s)
    if m:
        return next((i for i in items if i["id"].upper() == f"P{int(m.group(1))}"), None)
    if _PRIMARY_ONLY_RE.match(s):
        import crux_check
        return next((i for i in items if quote and crux_check._found(quote, i["text"])), None)
    if re.match(r"^https?://", s, re.I):
        k = _url_key(s)
        for i in items:
            if _url_key(i["url"]) == k:
                return i
        host = re.sub(r"^https?://", "", s, flags=re.I).split("/", 1)[0].lower()
        if host.endswith("sec.gov"):
            return _item_for_sec_url(s, items)
    return None


# ---- R1: a fetch of a primary document ---------------------------------------------------------------------------------------

FETCH_NOTE = ("This document is already in your briefing as PRIMARY {id}, verbatim. Cite it as source 'PRIMARY {id}'. "
              "It was not fetched again.")
SEARCH_NOTE = ("Your briefing already holds the company's own documents for this: PRIMARY {ids} (verbatim). Use and cite them. "
               "Search only for what they do not contain.")


def _item_for_sec_url(url, items):
    """The item an sec.gov URL is the document of: the same address; else, for a filing text, the item with the same file name under the same
    accession, else the first item of that accession (an 8-K's other documents are its exhibits: what the item prints is the filing). A 10-Q
    or 10-K item is only its segment report: its filing's other pages are not in the briefing, so only the report's own address matches."""
    k = _url_key(url)
    path = k.split("/", 1)[1] if "/" in k else ""
    name = path.rsplit("/", 1)[-1] if path else ""
    for i in items:
        if _url_key(i["url"]) == k:
            return i
    same_acc = [i for i in items if _acc_in(k, i["accession"])]
    for i in same_acc:
        if name and _url_key(i["url"]).rsplit("/", 1)[-1] == name:
            return i
    for i in same_acc:
        if i["form"] in ("8-K", "8-K/A"):
            return i
    return None


def refuse_fetch(url, items):
    """The model-facing refusal of a fetch_page call for a primary item's document, or None when the URL is not one. The call is not made."""
    u = (url or "").strip()
    if not items or not re.match(r"^https?://", u, re.I):
        return None
    host = re.sub(r"^https?://", "", u, flags=re.I).split("/", 1)[0].lower()
    it = None
    k = _url_key(u)
    for i in items:
        if _url_key(i["url"]) == k:
            it = i
            break
    if it is None and (host == "sec.gov" or host.endswith(".sec.gov")):
        it = _item_for_sec_url(u, items)
    if it is None:
        return None
    return {"served_from_primary": it["id"], "note": FETCH_NOTE.format(id=it["id"])}


# ---- R2: a search for what the primary items hold -----------------------------------------------------------------------------

_NUM_RE = re.compile(r"(?<![A-Za-z0-9,.])(\$?)(\d[\d,]*(?:\.\d+)?)(?:\s?(%|bn|billion|million|mm|m|b)\b)?", re.I)
_TEXT_NUM_RE = re.compile(r"(?<![A-Za-z0-9,.])\$?(\d[\d,]*(?:\.\d+)?)")


def figure_tokens(query, ticker=None):
    """The figure tokens of a query: a number with a decimal point or of 3 or more digits, optionally with $, %, bn, million or billion, as
    its digits with the commas removed. Left out: a plain year (1900 to 2099 written bare), a number that is part of a word or code (H100,
    Q2, FY26), and a number equal to an all-digit ticker."""
    tk = re.sub(r"\D", "", ticker or "") if ticker and str(ticker).isdigit() else None
    out = []
    for m in _NUM_RE.finditer(query or ""):
        core = m.group(2).rstrip(",").replace(",", "")
        if not core or core[-1] == ".":
            continue
        if "." not in core and len(core) < 3:
            continue
        if "." not in core and len(core) == 4 and 1900 <= int(core) <= 2099 and not m.group(1) and not m.group(3):
            continue
        if tk and core == tk:
            continue
        out.append(core)
    return out


def item_figures(text):
    """The set of numbers a text prints (digits and decimal point, commas removed)."""
    return {m.group(1).rstrip(",").replace(",", "") for m in _TEXT_NUM_RE.finditer(text or "")}


DOC_WORDS = ("earnings release", "press release", "prepared remarks", "exhibit 99", "guidance", "outlook", "8-K", "results", "10-K", "10-Q",
             "annual report", "quarterly report", "segment")
# (pattern, the kind of item the word asks for): release = an 8-K, remarks = an 8-K's other exhibit, 10-K or 10-Q = that form, segment = a release or a segment table, any = either
_DOC_RES = [(re.compile(r"(?<![A-Za-z0-9])" + pat + r"(?![A-Za-z0-9])", re.I), cls) for pat, cls in (
    (r"earnings[\s-]+release", "release"), (r"press[\s-]+release", "release"), (r"prepared[\s-]+remarks", "remarks"),
    (r"exhibit[\s-]+99", "release"), (r"guidance", "release"), (r"outlook", "release"), (r"8-?k", "release"), (r"results", "any"),
    (r"10-?k", "10-K"), (r"10-?q", "10-Q"), (r"annual[\s-]+report", "10-K"), (r"quarterly[\s-]+report", "10-Q"),
    (r"segments?", "segment"))]


def _quarter_keys(text):
    t = (text or "").lower()
    keys = set()
    pats = [
        (r"\bq([1-4])\s*[-/']?\s*(?:fy\s*)?'?((?:19|20)\d{2}|\d{2})\b", lambda m: ("Q", int(m.group(1)), _yr(m.group(2)))),
        (r"\b([1-4])q\s*'?((?:19|20)\d{2}|\d{2})\b", lambda m: ("Q", int(m.group(1)), _yr(m.group(2)))),
        (r"\b(?:fy\s*|fiscal\s*(?:year\s*)?)'?((?:19|20)\d{2}|\d{2})\s*[- ]?q([1-4])\b", lambda m: ("Q", int(m.group(2)), _yr(m.group(1)))),
        (r"\b((?:19|20)\d{2})\s*[- ]?q([1-4])\b", lambda m: ("Q", int(m.group(2)), _yr(m.group(1)))),
        (r"\b(first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter\s*(?:of\s*)?(?:fiscal\s*)?(?:year\s*)?(?:fy\s*)?'?((?:19|20)\d{2}|\d{2})\b",
         lambda m: ("Q", _QWORD[m.group(1)], _yr(m.group(2)))),
        (r"\b(?:fiscal\s*(?:year\s*)?|fy\s*)'?((?:19|20)\d{2}|\d{2})\s+(first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter\b",
         lambda m: ("Q", _QWORD[m.group(2)], _yr(m.group(1)))),
        (r"\b((?:19|20)\d{2})\s+(first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter\b", lambda m: ("Q", _QWORD[m.group(2)], _yr(m.group(1)))),
        (r"\b(?:fiscal(?:\s+year)?|fy|full[- ]year)\s*'?((?:19|20)\d{2}|\d{2})\b", lambda m: ("Y", _yr(m.group(1)))),
        (r"\b(" + _MON_RE + r")\.?,?\s+((?:19|20)\d{2})\b", lambda m: ("M", _yr(m.group(2)), _MONTHS[m.group(1)])),
    ]
    spans = []
    for pat, mk in pats:
        for m in re.finditer(pat, t):
            k = mk(m)
            if k[0] == "Y" and any(a < m.end() and m.start() < b for a, b in spans):      # "fiscal 2026 third quarter" is a quarter, not also the year
                continue
            if k[0] == "Q":
                spans.append(m.span())
            keys.add(k)
    return keys


def query_periods(query):
    """The periods a query names, as keys: ("Q", n, year) for Q2 2026, 2Q26 or second quarter 2026; ("Y", year) for fiscal 2026, FY26 or full
    year 2026; ("M", year, month) for July 2026. A bare year is not a period."""
    return _quarter_keys(query)


def item_periods(item):
    """The periods an item covers, as keys: its fiscal-period label (a quarter also covers its fiscal year), the month and year of its period
    end when the label is a date, and the month and year it was filed."""
    keys = set()
    p = item.get("period") or ""
    m = re.fullmatch(r"Q([1-4]) ((?:19|20)\d{2})", p)
    if m:
        keys |= {("Q", int(m.group(1)), int(m.group(2))), ("Y", int(m.group(2)))}
    m = re.fullmatch(r"FY ((?:19|20)\d{2})", p)
    if m:
        keys.add(("Y", int(m.group(1))))
    m = re.fullmatch(r"period ended ((?:19|20)\d{2})-(\d{2})-\d{2}", p)
    if m:
        keys |= {("M", int(m.group(1)), int(m.group(2))), ("Y", int(m.group(1)))}
    m = re.match(r"((?:19|20)\d{2})-(\d{2})-\d{2}$", item.get("filed") or "")
    if m:
        keys.add(("M", int(m.group(1)), int(m.group(2))))
    return keys


def _class_fits(cls, item):
    if cls == "any":
        return True
    if cls == "release":
        return item["form"] in ("8-K", "8-K/A")
    if cls == "remarks":                 # prepared remarks are held only when the 8-K's own exhibit of them is
        return item["type"] == "other_exhibit"
    if cls in ("10-K", "10-Q"):
        return item["form"] == cls
    return item["type"] in ("earnings_release", "segment_table")


def refuse_search(query, items, ticker=None):
    """(refusal, rule) for a search_web query, or None. The query is refused when (a) it holds a figure token a primary item prints verbatim
    (rule "figure"), or (b) it names a document word and a period that an item of that kind covers (rule "document"); both give the same
    pointer, listing the items. A query that names neither is searched."""
    if not items or not (query or "").strip():
        return None
    hit = {}
    toks = figure_tokens(query, ticker)
    if toks:
        for i in items:
            figs = item_figures(i["text"])
            if any(t in figs for t in toks):
                hit[i["id"]] = "figure"
    classes = {cls for rx, cls in _DOC_RES if rx.search(query)}
    periods = query_periods(query)
    doc = {}
    if classes and periods:
        for i in items:
            if any(_class_fits(c, i) for c in classes) and periods & item_periods(i):
                doc[i["id"]] = "document"
    ids = sorted(set(hit) | set(doc), key=lambda s: int(s[1:]))
    if not ids:
        return None
    rule = "figure+document" if hit and doc else ("figure" if hit else "document")
    return ({"served_from_primary": ids, "note": SEARCH_NOTE.format(ids=", ".join(ids))}, rule)
