"""D1 + D3 -> delisting events for the price source (Addendum L4; registration v2 section 2): the free-SEC-records delisting outcomes, through the EXISTING strict readers.

  D1 EVENT INDEX   `data/sec_bulk/index/events.json`: one event per company, from `rebuild_harness.delistings.classify_company` over the SEC submissions (the first Form 25 / Form 15, its
                   class, the evidence filings with their accession numbers) and `event_8k.csv.gz` (every 8-K that carries an event item, with its primary document name).
  D3 DOCUMENTS     `data/sec_bulk/delisting_docs/<cik>/<accession>/<file>` with `_manifest.jsonl` (one line per accession: its status and files, the primary document first).

THE RULE (unchanged from Addendum D).  `delistings.to_price_events` turns an event into a price event; it becomes anything but `unresolved_<class>` ONLY when a strict reader reads the text:
  * an `acquisition_completed` event: `read_cash_consideration` on the text of the Item 2.01 8-K(s) that are the event's evidence - exactly one distinct per-share cash amount and none of
    the words that mean stock, ratios, elections or contingent rights; else unresolved;
  * a `bankruptcy` event: `read_equity_cancelled` on the text of the Item 1.03 8-K(s): the common stock cancelled AND holders receive nothing; else unresolved;
  * every other class stays unresolved.
An unresolved event is OUTCOME_UNOBSERVABLE with the three bounds (excluded, -100%, last close).  A document that is not on disk (a download in progress, a failed fetch) gives NO text, so
the event stays unresolved: a missing document is never read as "no cash" or "no distribution", and is counted (`missing_documents` in the report).

TEXT.  The 8-K's PRIMARY document only (the exhibits - merger agreements, plans - hold many dollar figures and would make the strict reader refuse, which is the safe side, but the 8-K
body is where the completion's consideration is stated).  HTML tags become spaces, entities are unescaped, white space is collapsed; nothing else is rewritten.

Nothing here downloads anything or writes outside the folder a caller names.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import html
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from valuation.common import DataNotPresent
from . import delistings

EVENTS_FILE, EVENT_8K_FILE, MANIFEST_FILE = "events.json", "event_8k.csv.gz", "_manifest.jsonl"
ALL_EVENTS_FILE = "events_all.json"          # Addendum P4: EVERY exit event of each company (events.json keeps the first one only); built by `rebuild_harness.event_index`
ITEM_FOR_CLASS = {"acquisition_completed": "2.01", "bankruptcy": "1.03"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: bytes) -> str:
    """The visible text of an EDGAR document: tags -> spaces, entities unescaped, no-break spaces and runs of white space -> one space.  A plain-text document passes through the same way."""
    s = raw.decode("utf-8", "replace")
    p = _Text()
    try:
        p.feed(s)
        p.close()
        s = "".join(p.parts)
    except Exception:                       # a document the parser cannot take: strip tags by hand rather than lose it
        s = re.sub(r"<[^>]*>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _sha256(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


class EventIndex:
    """D1: `events.json` (a list of {cik, date, class, evidence: [{form, date, items, accession}], name}) and `event_8k.csv.gz` (the 8-Ks, with `primary_doc`)."""

    def __init__(self, index_dir):
        self.dir = Path(index_dir)
        ep = self.dir / EVENTS_FILE
        if not ep.is_file():
            raise DataNotPresent(f"the D1 event index is not at {ep}")
        self.events: List[dict] = json.loads(ep.read_text(encoding="utf-8"))
        bad = [e for e in self.events if not all(k in e for k in ("cik", "date", "class", "evidence"))]
        if bad:
            raise DataNotPresent(f"{ep}: {len(bad)} event(s) lack cik/date/class/evidence")
        self.events_sha256 = _sha256(ep)
        ap = self.dir / ALL_EVENTS_FILE
        self.has_all_events = ap.is_file()
        self.all_events_sha256 = None
        if self.has_all_events:                       # Addendum P4: the census reads every exit event of a company, the price source of the survivors the first one (as before)
            self.all_events: List[dict] = json.loads(ap.read_text(encoding="utf-8"))
            bad = [e for e in self.all_events if not all(k in e for k in ("cik", "date", "class", "evidence"))]
            if bad:
                raise DataNotPresent(f"{ap}: {len(bad)} event(s) lack cik/date/class/evidence")
            self.all_events_sha256 = _sha256(ap)
        else:
            self.all_events = self.events
        self.primary_doc: Dict[Tuple[str, str], str] = {}
        self.eight_k: Dict[Tuple[str, str], dict] = {}
        p8 = self.dir / EVENT_8K_FILE
        if p8.is_file():
            with gzip.open(p8, "rt", encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    k = (str(r["cik"]).zfill(10), r["accession"])
                    self.eight_k[k] = r
                    if r.get("primary_doc"):
                        self.primary_doc[k] = r["primary_doc"]

    def info(self) -> dict:
        return {"dir": str(self.dir), "events": len(self.events), "events_sha256": self.events_sha256, "eight_k_rows": len(self.eight_k),
                "classes": dict(Counter(e["class"] for e in self.events)),
                "all_events": len(self.all_events) if self.has_all_events else None, "all_events_sha256": self.all_events_sha256}


class DelistingDocs:
    """D3: the downloaded 8-K documents.  `text(cik, accession, primary)` -> the primary document's text, or None (with the reason in `last_reason`)."""

    def __init__(self, docs_dir):
        self.dir = Path(docs_dir)
        mp = self.dir / MANIFEST_FILE
        if not mp.is_file():
            raise DataNotPresent(f"the D3 manifest is not at {mp}")
        self.manifest: Dict[Tuple[str, str], dict] = {}
        with open(mp, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    j = json.loads(line)
                    self.manifest[(str(j["cik"]).zfill(10), j["accession"])] = j
        self.last_reason: Optional[str] = None

    def text(self, cik: str, accession: str, primary: Optional[str] = None) -> Optional[str]:
        m = self.manifest.get((str(cik).zfill(10), accession))
        if m is None:
            self.last_reason = "accession_not_in_d3_manifest"
            return None
        files = [f for f in (m.get("files") or []) if f.get("status") == "ok"]
        if not files:
            self.last_reason = "no_document_downloaded_ok"
            return None
        names = [f["name"] for f in files]
        name = primary if primary in names else names[0]
        p = self.dir / str(cik).zfill(10) / accession / name
        if not p.is_file():
            self.last_reason = "document_file_missing_on_disk"
            return None
        self.last_reason = None
        return html_to_text(p.read_bytes())


def completeness(index: EventIndex, docs: DelistingDocs, since: str = "0000-00-00") -> dict:
    """What D3 holds against what D1 asks for: every 8-K accession in `event_8k.csv.gz` with an event date on or after `since` and the number of those with a document ok on disk.  A holdout freeze
    requires the download to be complete (`complete` True): `missing` lists the first accessions that are not."""
    want = [(k, r) for k, r in index.eight_k.items() if (r.get("event_date") or "") >= since]
    have, missing = 0, []
    for k, _r in want:
        m = docs.manifest.get(k)
        ok = bool(m) and any(f.get("status") == "ok" for f in (m.get("files") or []))
        failed = bool(m) and m.get("status") not in (None, "ok") and not ok          # a fetch that failed for good (the filing has no document): not "missing", but not text either
        if ok or failed:
            have += 1 if ok else 0
            if failed:
                missing.append([k[0], k[1], "fetch_failed:" + str(m.get("status"))])
        else:
            missing.append([k[0], k[1], "not_in_manifest" if m is None else "no_file_ok"])
    n_not_downloaded = sum(1 for x in missing if not x[2].startswith("fetch_failed"))
    return {"accessions_wanted": len(want), "with_document": have, "fetch_failed": sum(1 for x in missing if x[2].startswith("fetch_failed")),
            "not_downloaded": n_not_downloaded, "complete": n_not_downloaded == 0, "first_missing": missing[:20]}


def missing_document_events(index: EventIndex, docs: DelistingDocs, since: str = "0000-00-00") -> dict:
    """Addendum P5: the events (every exit event of the index, `all_events`) dated on or after `since` whose class has a reader and one of whose evidence 8-K documents is not on disk.  Such an event
    stays UNRESOLVED (`event_text` gives it no text, never "no cash"): it is counted here and in the run's report, and it does not block a freeze or a run.  Reads the manifest and checks the file
    exists; opens no document."""
    n_reader, missing, reasons = 0, [], Counter()
    for ev in index.all_events:
        item = ITEM_FOR_CLASS.get(ev["class"])
        if item is None or ev["date"] < since:
            continue
        n_reader += 1
        why = None
        for x in ev["evidence"]:
            if not (str(x.get("form", "")).startswith("8-K") and item in (x.get("items") or [])):
                continue
            key = (str(ev["cik"]).zfill(10), x["accession"])
            m = docs.manifest.get(key)
            if m is None:
                why = "accession_not_in_d3_manifest"
            else:
                files = [f for f in (m.get("files") or []) if f.get("status") == "ok"]
                if not files:
                    why = "no_document_downloaded_ok"
                else:
                    primary = index.primary_doc.get(key)
                    name = primary if primary in [f["name"] for f in files] else files[0]["name"]
                    if not (docs.dir / key[0] / x["accession"] / name).is_file():
                        why = "document_file_missing_on_disk"
            if why:
                break
        if why:
            reasons[why] += 1
            missing.append([ev["cik"], ev["date"], ev["class"], why])
    return {"events_with_a_reader": n_reader, "unresolved_missing_document": len(missing), "by_reason": dict(reasons), "first": missing[:20]}


def event_text(ev: dict, index: EventIndex, docs: DelistingDocs) -> Tuple[Optional[str], Optional[str]]:
    """(text, reason) for an event: the joined primary-document text of its Item 2.01 (acquisition) or Item 1.03 (bankruptcy) 8-K evidence; (None, reason) when the class has no reader, there is no
    such evidence, or ANY of those documents cannot be read (a partial text could mislead the strict reader)."""
    item = ITEM_FOR_CLASS.get(ev["class"])
    if item is None:
        return None, "class_has_no_reader"
    evid = [x for x in ev["evidence"] if str(x.get("form", "")).startswith("8-K") and item in (x.get("items") or [])]
    seen, parts = set(), []
    for x in evid:
        acc = x["accession"]
        if acc in seen:
            continue
        seen.add(acc)
        t = docs.text(ev["cik"], acc, index.primary_doc.get((str(ev["cik"]).zfill(10), acc)))
        if t is None:
            return None, docs.last_reason
        parts.append(t)
    if not parts:
        return None, f"no_item_{item}_8k_in_the_evidence"
    return "\n\n".join(parts), None


def build_price_events(index: EventIndex, docs: Optional[DelistingDocs], tickers_for: Callable[[str], Iterable[str]], since: str = "2019-01-01",
                       until: str = "9999-12-31") -> Tuple[Dict[str, dict], dict]:
    """({ticker: price event}, report) for the events dated in [since, until].  With `docs` None every event is unresolved.  The report counts, per class, the events, those resolved by a
    reader and why the others were not (a missing document, a reader that declined)."""
    chosen = [e for e in index.events if since <= e["date"] <= until]
    rep = {"events": Counter(e["class"] for e in chosen), "resolved": Counter(), "unresolved_reason": Counter(), "missing_documents": 0, "since": since, "until": until}
    reasons: Dict[int, str] = {}

    def text_for(e):
        if docs is None:
            reasons[id(e)] = "no_documents_folder"
            return None
        t, r = event_text(e, index, docs)
        if t is None:
            reasons[id(e)] = r or "no_text"
            if r and ("missing" in r or "not_in_d3" in r or "no_document" in r):
                rep["missing_documents"] += 1
        return t

    pe = delistings.to_price_events(chosen, tickers_for, text_for)
    # to_price_events is keyed by ticker: read each event's outcome from its type (an event whose company has no ticker in the id map is not in `pe`)
    for e in chosen:
        if e["class"] not in ITEM_FOR_CLASS:
            rep["unresolved_reason"]["class_has_no_reader"] += 1
            continue
        tk = list(tickers_for(e["cik"]))
        if not tk:
            continue
        typ = pe[tk[0]]["type"] if tk[0] in pe else None
        if typ in ("acquisition", "bankruptcy"):
            rep["resolved"][e["class"]] += 1
        else:
            rep["unresolved_reason"][reasons.get(id(e), "reader_declined: the text did not meet the strict rule")] += 1
    rep = {k: (dict(v) if isinstance(v, Counter) else v) for k, v in rep.items()}
    return pe, rep
