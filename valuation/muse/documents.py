"""documents.py - the company's own documents (section D) and its latest quarters (section Q), bounded by the 16:00 ET acceptance cutoff.

WHY THIS IS NOT `sec_primary.build`. The repo's PRIMARY SOURCES builder cannot be bounded by the acceptance cutoff: it selects by FILING DATE with an
inclusive bound (`filingDate > as-of` excluded, so a filing made on the day after 16:00 ET is in), it never looks at `acceptanceDateTime`, and it reads the
CURRENT submissions JSON that `sec_guidance._submissions` fetches live. It also never reads the annual report's own text (the business description and the
MD&A), which section D needs. So the SELECTION is redone here, under the rule of the shared layer (`valuation/pit_data.py`): an item is eligible when its EDGAR
acceptance timestamp is at or before 16:00 ET on the valuation date; with no timestamp, when it was filed on an earlier date (filed on the date itself:
ambiguous, not used). sec_primary's pure text helpers (HTML to blocks, the paragraph selector, the omission markers, the period label) and its cached fetchers
are reused unchanged; the fetchers are injectable so the tests need no network.

THE ITEMS (each a DocItem; the pack builder re-checks every item against the cutoff, whatever the source claims):
  annual_business         the latest annual report's business description (Item 1; for a 20-F, Item 4), at most BUSINESS_CAP characters
  annual_mdna_outlook     its management's discussion (Item 7; 20-F Item 5), the sec_primary selector keeping the outlook, segment and backlog paragraphs, at most MDNA_CAP
  annual_segment_note     the segment report of the latest annual report (FilingSummary R page), at most SEGMENT_CAP
  earnings_release        the newest 8-K Item 2.02 release exhibit (a foreign filer: the newest 6-K that reads as a periodic results release), at most RELEASE_CAP

SECTION Q needs quarterly facts. Their source is now the shared layer (Addendum G 12): `layer_quarters(pit_data)` returns `valuation.pit_data.PitQuarterSource`,
which reads the quarterly facts the store keeps (10-Q values, year-to-date differences, the 10-K's derived fourth quarter) under the same provenance and 16:00 ET
acceptance rule as every other input. `CompanyFactsQuarters`, which reads the raw companyfacts document, was the stopgap before the layer stored quarters; it stays
for its own tests and for a store built without quarterly facts.
"""
from __future__ import annotations

import gzip
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from valuation import pit_data as pdm

BUSINESS_CAP = 8000
MDNA_CAP = 8000
SEGMENT_CAP = 6000
RELEASE_CAP = 14000
ANNUAL_ORIGINAL = ("10-K", "10-K405", "10-KT", "20-F", "40-F")


@dataclass
class DocItem:
    kind: str
    title: str
    form: str
    accession: str
    filed: str
    text: str
    accepted_at: Optional[str] = None      # UTC ISO timestamp (EDGAR acceptance) or None
    period: Optional[str] = None
    url: Optional[str] = None              # for the manifest; never printed in the pack

    def as_manifest(self) -> dict:
        return {"kind": self.kind, "form": self.form, "accession": self.accession, "filed": self.filed, "accepted_at": self.accepted_at,
                "period": self.period, "url": self.url, "chars": len(self.text)}


def eligibility(accepted_at: Optional[str], filed: str, asof) -> str:
    """"ok" | "invalid" | "ambiguous" at valuation date `asof`: the rule of pit_data.CompanyPit.eligibility."""
    asof_d = pdm.to_date(asof)
    t = pdm.parse_accepted(accepted_at) if accepted_at else None
    if t is not None:
        return "ok" if t <= pdm.decision_time_utc(asof_d) else "invalid"
    f = str(filed)[:10]
    if f < asof_d.isoformat():
        return "ok"
    return "ambiguous" if f == asof_d.isoformat() else "invalid"


class DocumentSource:
    """items(cik, asof) -> ([DocItem], [note]). Notes are for the manifest, never for a prompt."""

    def items(self, cik, asof) -> Tuple[List[DocItem], List[str]]:   # pragma: no cover - interface
        raise NotImplementedError


class StaticDocuments(DocumentSource):
    """A fixed list (the tests; or documents extracted earlier and stored)."""

    def __init__(self, items: Sequence[DocItem], notes: Sequence[str] = ()):
        self._items, self._notes = list(items), list(notes)

    def items(self, cik, asof):
        return list(self._items), list(self._notes)


# ---- submissions (filing list with acceptance timestamps) -------------------------------------------------------------------------------

def read_submissions(directory, cik) -> List[dict]:
    """The filings of an SEC submissions JSON `CIK##########.json` (filings.recent and the files it lists): [{accession, form, filed, accepted,
    items, report_date, primary_document}] with `accepted` a UTC datetime or None."""
    d = Path(directory)
    p = d / f"CIK{str(cik).zfill(10)}.json"
    if not p.exists():
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    blocks = [(doc.get("filings") or {}).get("recent") or {}]
    for f in (doc.get("filings") or {}).get("files") or []:
        q = d / f.get("name", "")
        if q.is_file():
            blocks.append(json.loads(q.read_text(encoding="utf-8")))
    out = []
    for b in blocks:
        accs = b.get("accessionNumber") or []
        for i, a in enumerate(accs):
            def col(k, i=i):
                v = b.get(k) or []
                return v[i] if i < len(v) else ""
            out.append({"accession": a, "form": col("form"), "filed": col("filingDate"), "accepted_raw": col("acceptanceDateTime"),
                        "accepted": pdm.parse_accepted(col("acceptanceDateTime")), "items": col("items"), "report_date": col("reportDate"),
                        "primary_document": col("primaryDocument")})
    return out


def _acc_iso(t) -> Optional[str]:
    return None if t is None else t.isoformat()


# ---- the annual report's own text --------------------------------------------------------------------------------------------------------

_HEAD_MAX = 220          # a heading paragraph is short
_ITEM_PATTERNS = {
    "business": (re.compile(r"^\s*items?\s*1\s*(?:(?:and|&)\s*2\s*)?[\.\:\-–—]?\s*(?:description\s+of\s+)?(?:the\s+)?business\b", re.I),
                 re.compile(r"^\s*item\s*1a\b|^\s*item\s*1b\b|^\s*item\s*2\s*[\.\:\-–—]?\s*propert", re.I)),
    "mdna": (re.compile(r"^\s*item\s*7\s*[\.\:\-–—]?\s*management", re.I),
             re.compile(r"^\s*item\s*7a\b|^\s*item\s*8\b", re.I)),
}
_ITEM_PATTERNS_20F = {
    "business": (re.compile(r"^\s*item\s*4\s*[\.\:\-–—]?\s*information\s+on\s+the\s+company\b", re.I),
                 re.compile(r"^\s*item\s*4a\b|^\s*item\s*5\b", re.I)),
    "mdna": (re.compile(r"^\s*item\s*5\s*[\.\:\-–—]?\s*operating\s+and\s+financial\s+review", re.I),
             re.compile(r"^\s*item\s*6\b", re.I)),
}


# a heading that is only the item's number ("Item 7."): its title is in the next unit (a wrapped heading)
_BARE_ITEM = re.compile(r"^\s*item\s*\d+[a-z]?\s*[\.\:\-–—]?\s*$", re.I)
# the end of each Item's canonical title: a heading matched on its first words that has not reached it is wrapped, and the next short lines complete it
_TITLE_END = {("10", "business"): None,
              ("10", "mdna"): re.compile(r"results\s+of\s+operations", re.I),
              ("20", "business"): re.compile(r"the\s+company\b", re.I),
              ("20", "mdna"): re.compile(r"prospects\b", re.I)}
_CONT_MAX = 120          # a heading's continuation line is short
_CONT_UNITS = 3          # and there are at most this many of them


def _units(blocks):
    """The blocks as a flat list of units (kind, text, block index): a paragraph is one unit and each row of a table is one (its cells joined by " | " as the
    selector's blocks give them).  Item headings are sought among the units of both kinds: a heading may be a paragraph, a one-row table, or a row of a larger one."""
    out = []
    for bi, (k, c) in enumerate(blocks):
        if k == "p":
            out.append(("p", c, bi))
        else:
            out += [("r", row, bi) for row in c]
    return out


def _norm(text: str) -> str:
    return text.replace(" | ", " ")


def _heading_at(units, i, rx, title_end=None, start=False):
    """How many units the Item heading starting at unit `i` spans (0 = none): the unit itself when its text (a table row's cells joined with a space) matches `rx`;
    or, when the unit is only the item's number, that unit and the next, whose text completes the title.  For a START heading whose title is not complete after
    that (a heading wrapped over several lines), the following short units that finish it are part of the heading too."""
    k, t, _ = units[i]
    nt = _norm(t)
    n = 0
    if len(nt) <= _HEAD_MAX and rx.match(nt):
        n = 1
    elif _BARE_ITEM.match(nt) and i + 1 < len(units) and len(_norm(units[i + 1][1])) <= _HEAD_MAX and rx.match(nt + " " + _norm(units[i + 1][1])):
        n = 2
    if n and start and title_end is not None:
        acc = " ".join(_norm(units[j][1]) for j in range(i, i + n))
        m = n
        while not title_end.search(acc) and m < n + _CONT_UNITS and i + m < len(units):
            nxt = _norm(units[i + m][1])
            if len(nxt) > _CONT_MAX or nxt.rstrip().endswith("."):
                break
            acc += " " + nxt
            m += 1
        if title_end.search(acc):
            n = m                                   # the wrapped title is complete: its continuation lines are part of the heading
    return n


def _rebuild(units, lo, hi):
    """The units lo..hi-1 as blocks again: a paragraph is a paragraph and consecutive rows of one table are one table block."""
    out, cur = [], None
    for k, t, bi in units[lo:hi]:
        if k == "p":
            out.append(("p", t))
            cur = None
        elif cur is not None and cur[0] == bi:
            cur[1].append(t)
        else:
            cur = [bi, [t]]
            out.append(("t", cur[1]))
    return out


def _size(span) -> int:
    return sum(len(c) if k == "p" else sum(len(r) for r in c) for k, c in span)


def item_span(blocks, which: str, form: str):
    """The blocks between an Item's heading and the next Item's heading. A table of contents repeats each heading with almost nothing after
    it, so of the heading matches the one with the LONGEST span is taken. [] when no heading is found (a 40-F wrapper has none).

    A heading is a paragraph, a ONE-ROW table or a row of a larger table (Addendum H8: filings set their headings in layout tables), and it may be wrapped: the
    item's number alone in one unit with the title in the next, or a long title (Item 7's "Management's Discussion and Analysis of Financial Condition and
    Results of Operations") broken over short lines.  The next Item's heading is sought the same way."""
    foreign = form.upper().startswith(("20-F", "40-F"))
    pats = _ITEM_PATTERNS_20F if foreign else _ITEM_PATTERNS
    start_re, end_re = pats[which]
    title_end = _TITLE_END[("20" if foreign else "10", which)]
    units = _units(blocks)
    best: list = []
    best_size = 0
    for i in range(len(units)):
        n = _heading_at(units, i, start_re, title_end, start=True)
        if not n:
            continue
        lo = i + n
        hi = next((j for j in range(lo, len(units)) if _heading_at(units, j, end_re)), len(units))
        span = _rebuild(units, lo, hi)
        size = _size(span)
        if size > best_size:
            best, best_size = span, size
    return best


def _plain(blocks) -> str:
    return "\n".join(c if k == "p" else "\n".join(c) for k, c in blocks)


# ---- the acceptance-bounded source -----------------------------------------------------------------------------------------------------

def default_fetch_annual(cache_dir=None) -> Callable:
    """fetch(cik, accession) -> the raw text of the annual report's main document, from `cache_dir` or from sec.gov through sec_primary's throttled
    fetcher (one request; a failure returns None). NOT used by any test."""
    def fetch(cik, accession):
        import sec_primary as sp
        cik10 = str(cik).zfill(10)
        path = None if cache_dir is None else Path(cache_dir) / f"{cik10}_{accession}.annual.json.gz"
        if path is not None and path.exists():
            try:
                return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))["raw"]
            except Exception:
                pass
        try:
            raw = sp._http_get(f"{sp._base_url(cik, accession)}/{accession}.txt").decode("utf-8", "replace")
        except Exception:
            return None
        main = None
        for dtype, _fname, text in sp._split_documents(raw):
            if dtype.upper() in ANNUAL_ORIGINAL:
                main = text[:sp.RAW_MAX * 4]
                break
        if main is not None and path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(json.dumps({"raw": main}).encode("utf-8"), 6))
        return main
    return fetch


class AcceptanceBoundedDocuments(DocumentSource):
    """Section D from SEC filings, selected under the 16:00 ET acceptance rule (module docstring). `submissions_dir` holds `CIK##########.json`
    files; `fetch_8k(cik, accession)`, `fetch_periodic(cik, accession)` and `fetch_annual(cik, accession)` default to sec_primary's cached fetchers and
    to `default_fetch_annual`."""

    def __init__(self, submissions_dir, *, fetch_8k: Optional[Callable] = None, fetch_periodic: Optional[Callable] = None,
                 fetch_annual: Optional[Callable] = None, annual_cache_dir=None):
        self.submissions_dir = Path(submissions_dir)
        self._f8k, self._fper, self._fann = fetch_8k, fetch_periodic, fetch_annual
        self.annual_cache_dir = annual_cache_dir

    def _sp(self):
        import sec_primary as sp
        return sp

    def _fetchers(self):
        sp = self._sp()
        return (self._f8k or sp.fetch_8k, self._fper or sp.fetch_periodic, self._fann or default_fetch_annual(self.annual_cache_dir))

    def items(self, cik, asof):
        sp = self._sp()
        f8k, fper, fann = self._fetchers()
        asof_d = pdm.to_date(asof)
        notes: List[str] = []
        rows = []
        for r in read_submissions(self.submissions_dir, cik):
            st = eligibility(_acc_iso(r["accepted"]), r["filed"], asof_d)
            if st == "ok":
                rows.append(r)
            elif st == "ambiguous":
                notes.append(f"{r['form']} {r['accession']} filed on the valuation date with no acceptance timestamp: not used")
        newest = lambda rs: sorted(rs, key=lambda r: (r["filed"], r["accession"]), reverse=True)    # noqa: E731
        items: List[DocItem] = []
        # the latest annual report: business, MD&A, segment note
        ann = newest([r for r in rows if r["form"] in ANNUAL_ORIGINAL])
        if not ann:
            notes.append("no annual report accepted before the cutoff")
        else:
            a = ann[0]
            base = dict(form=a["form"], accession=a["accession"], filed=a["filed"], accepted_at=_acc_iso(a["accepted"]),
                        period=f"fiscal year ended {a['report_date']}" if a["report_date"] else None)
            raw = fann(cik, a["accession"])
            if raw is None:
                notes.append(f"the annual report {a['accession']} could not be read (business description and MD&A not in section D)")
            else:
                blocks = sp.blocks_of(raw)
                biz = item_span(blocks, "business", a["form"])
                md = item_span(blocks, "mdna", a["form"])
                if biz:
                    items.append(DocItem("annual_business", f"Annual report (Form {a['form']}): business description", text=sp.canonical(
                        sp.prefix_text(_plain(biz), BUSINESS_CAP)), **base))
                else:
                    notes.append("business description not located in the annual report")
                if md:
                    items.append(DocItem("annual_mdna_outlook", f"Annual report (Form {a['form']}): management's discussion, outlook and key paragraphs",
                                         text=sp.canonical(sp.select_text(md, MDNA_CAP)), **base))
                else:
                    notes.append("management's discussion not located in the annual report")
            got = fper(cik, a["accession"])
            seg = (got or {}).get("segment")
            if seg:
                lines = []
                for k, c in sp.blocks_of(seg["raw"]):
                    lines += c if k == "t" else [c]
                items.append(DocItem("annual_segment_note", f"Annual report (Form {a['form']}): segment note", text=sp.canonical(
                    sp.prefix_text("\n".join(lines), SEGMENT_CAP)), **base))
            else:
                notes.append("no segment report in the latest annual report")
        # the latest earnings release
        rel = newest([r for r in rows if r["form"] in ("8-K", "8-K/A") and sp._has_item_202(r["items"])])
        found = None
        if rel:
            r = rel[0]
            got = f8k(cik, r["accession"])
            d = sp._release_doc(got["docs"]) if got else None
            if d is not None:
                found = (r, d, "Item 2.02 earnings release")
            else:
                notes.append(f"the earnings release {r['accession']} could not be read")
        else:
            six = newest([r for r in rows if r["form"] in sp.FOREIGN_FORMS and r["filed"] >= (asof_d - timedelta(days=sp.SCAN_6K_DAYS)).isoformat()])
            for r in six[:sp.SCAN_6K]:
                got = f8k(cik, r["accession"])
                for d in [x for x in (got or {}).get("docs", []) if "raw" in x and x["type"].upper().startswith("EX-99")]:
                    blocks = sp.blocks_of(d["raw"])
                    head = (d.get("description") or "") + " " + " ".join(c if k == "p" else " ".join(c) for k, c in blocks)[:600]
                    if sp.RESULTS_WORDS.search(head) and sp.PERIOD_WORDS.search(head) and not sp.MEETING_WORDS.search(head):
                        found = (r, d, "6-K results release")
                        break
                if found:
                    break
            if found is None:
                notes.append("no earnings release accepted before the cutoff")
        if found is not None:
            r, d, what = found
            blocks = sp.blocks_of(d["raw"])
            period = sp.release_period(" ".join(c if k == "p" else " ".join(c) for k, c in blocks[:15]))
            items.append(DocItem("earnings_release", f"{r['form']} {what}", form=r["form"], accession=r["accession"], filed=r["filed"],
                                 accepted_at=_acc_iso(r["accepted"]), period=period, text=sp.canonical(sp.select_text(blocks, RELEASE_CAP))))
        return [i for i in items if i.text], notes


# ---- section Q: the latest quarters ------------------------------------------------------------------------------------------------------

QUARTER_FIELDS = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
}


class QuarterSource:
    """quarters(cik, asof) -> [{"period_end", "filed", "accession", "values": {field: v}, "prior_year": {field: v}}] ascending, quarters known at `asof`."""

    def quarters(self, cik, asof) -> List[dict]:        # pragma: no cover - interface
        raise NotImplementedError


class StaticQuarters(QuarterSource):
    def __init__(self, rows: Sequence[dict]):
        self.rows = list(rows)

    def quarters(self, cik, asof):
        return [dict(r) for r in self.rows]


def layer_quarters(pit_data, **kw) -> QuarterSource:
    """Section Q's quarterly source: the shared point-in-time layer (`PitQuarterSource(pit_data)`), replacing the `CompanyFactsQuarters` stopgap."""
    from valuation.pit_data import PitQuarterSource
    return PitQuarterSource(pit_data, **kw)


def zip_loader(zip_path) -> Callable:
    def load(cik):
        with zipfile.ZipFile(zip_path) as z:
            try:
                return json.loads(z.read(f"CIK{str(cik).zfill(10)}.json"))
            except KeyError:
                return None
    return load


def dir_loader(directory) -> Callable:
    def load(cik):
        p = Path(directory) / f"CIK{str(cik).zfill(10)}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return load


class CompanyFactsQuarters(QuarterSource):
    """STOPGAP, superseded by `layer_quarters` (the shared layer's quarterly facts). Three-month revenue, operating income and net income from the 10-Q facts of the raw companyfacts document, with the same quarter a year earlier as the
    comparative column of the same filings. A fact is used when its filing is eligible at the valuation date (acceptance rule); of several filings of a quarter
    the latest eligible one is used (what was known at the date). `loader(cik)` returns the raw companyfacts dict; `acceptance(cik)` -> {accession: UTC datetime}."""

    def __init__(self, loader: Callable, acceptance: Optional[Callable] = None, max_quarters: int = 6):
        self.loader, self.acceptance, self.max_quarters = loader, acceptance, max_quarters

    def quarters(self, cik, asof):
        doc = self.loader(cik)
        if not doc:
            return []
        acc = self.acceptance(cik) if self.acceptance is not None else {}
        us = (doc.get("facts") or {}).get("us-gaap") or {}
        # every eligible three-month 10-Q fact, per field: (end, filed, accession, value)
        facts: Dict[str, List[tuple]] = {}
        for fld, tags in QUARTER_FIELDS.items():
            for tag in tags:
                rows = ((us.get(tag) or {}).get("units") or {}).get("USD") or []
                got = []
                for r in rows:
                    if not str(r.get("form", "")).startswith("10-Q") or not r.get("start") or not r.get("end") or r.get("val") is None:
                        continue
                    if not 80 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 100:
                        continue
                    if eligibility(_acc_iso(acc.get(r.get("accn"))), r.get("filed", "9999-12-31"), asof) != "ok":
                        continue
                    got.append((r["end"], r["filed"], r.get("accn", ""), float(r["val"])))
                if got:
                    facts[fld] = got
                    break
        # a filing's OWN quarter is the latest period end among its facts; its other columns are comparatives, never quarters of their own
        own: Dict[str, str] = {}
        for got in facts.values():
            for end, _f, accn, _v in got:
                if accn not in own or end > own[accn]:
                    own[accn] = end
        quarter: Dict[str, Dict[str, tuple]] = {}      # field -> end -> ((filed, accn), value): the latest eligible filing of the quarter, from a filing whose own quarter it is
        pool: Dict[str, Dict[str, tuple]] = {}         # field -> end -> the same over every eligible fact (the year-earlier comparatives)
        for fld, got in facts.items():
            quarter[fld], pool[fld] = {}, {}
            for end, filed, accn, v in got:
                key = (filed, accn)
                if end not in pool[fld] or key > pool[fld][end][0]:
                    pool[fld][end] = (key, v)
                if end == own.get(accn) and (end not in quarter[fld] or key > quarter[fld][end][0]):
                    quarter[fld][end] = (key, v)
        ends = sorted({e for g in quarter.values() for e in g})
        out = []
        for e in ends:
            vals = {f: g[e][1] for f, g in quarter.items() if e in g}
            first = next(g[e][0] for g in quarter.values() if e in g)
            tgt = date.fromisoformat(e) - timedelta(days=365)
            prior = {}
            for f, g in pool.items():
                cand = [(abs((date.fromisoformat(pe) - tgt).days), pe) for pe in g if abs((date.fromisoformat(pe) - tgt).days) <= 12]
                if cand:
                    prior[f] = g[min(cand)[1]][1]
            out.append({"period_end": e, "filed": first[0], "accession": first[1], "accepted_at": _acc_iso(acc.get(first[1])), "values": vals,
                        "prior_year": prior})
        return out[-self.max_quarters:]
