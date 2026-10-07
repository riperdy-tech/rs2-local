"""The all-events D1 index (Addendum P4): EVERY exit event of each company, built from the local SEC submissions archive (`data/sec_bulk/submissions.zip`); nothing is downloaded.

THE GAP.  D1's `events.json` holds ONE event per company, the first.  A company whose first Form 25 / Form 15 was for another security (notes, preferred shares, a move between exchanges) and whose
common stock left later is dated at the first event: before T it hides the later delisting from the census (the company is absent), after T it dates the event too early.  Addendum P4: the census
uses, for each company, the first qualifying exit event dated after T, from all of the company's events.

THE INDEX.  `build_all_events_index(submissions_zip, d1_dir, out_dir)` writes a NEW folder (an existing non-empty one is refused; nothing is overwritten or deleted):
  events.json        a byte copy of D1's (the first event per company: the price source of the survivors reads it, unchanged)
  event_8k.csv.gz    D1's rows (kept first and unchanged) plus the 8-K rows of the events D1 does not hold, by the rule that built D1's (an 8-K with an Item 1.03 up to 540 days before the event, or
                     an Item 2.01 / 3.01 / 5.01 from 45 days before to 30 days after it); a row keeps the first event that asked for it
  events_all.json    every exit event of every company that has an exit record or an Item 1.03 8-K, sorted by (cik, date): `delistings.classify_exit_events`
  manifest.json      what it was built from (the archive's size and sha256, D1's events.json sha256), the counts, and how many of D1's first events the all-events list reproduces
The companies are those of D1's events.json: a company with no exit record and no Item 1.03 8-K has no event in either.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import shutil
import zipfile
from collections import Counter
from multiprocessing import Pool
from pathlib import Path
from typing import Dict, List

from valuation.common import DataNotPresent
from . import delisting_inputs as di, delistings as D

ITEMS = {"2.01", "1.03", "3.01", "5.01"}
COLUMNS = ["cik", "event_class", "event_date", "accession", "form", "filed", "accepted", "items", "primary_doc"]
_Z = {}


def _rows_of(blocks):
    """(accession, form, filed, accepted, items, primary document) of every filing in the blocks (the main file's `recent` and the older pages)."""
    for b in blocks:
        r = (b.get("filings") or {}).get("recent") if "filings" in b else b
        r = r or {}
        n = len(r.get("form") or [])

        def g(k):
            return r.get(k) or [""] * n
        acc, form, fd, ad, it, pd_ = g("accessionNumber"), g("form"), g("filingDate"), g("acceptanceDateTime"), g("items"), g("primaryDocument")
        for i in range(n):
            yield (acc[i], form[i], fd[i], ad[i], str(it[i] or ""), pd_[i])


def eight_k_rows(rows, ev) -> List[tuple]:
    """The 8-K rows an event keeps (the rule that built D1's `event_8k.csv.gz`)."""
    d0 = D._d(ev["date"])
    out = []
    for acc, form, filed, accepted, items, primary in rows:
        if form in ("8-K", "8-K/A") and items:
            its = {x.strip() for x in items.split(",")}
            if its & ITEMS:
                dd = (D._d(filed) - d0).days
                if -540 <= dd <= 30 and ((its & {"1.03"}) or -45 <= dd <= 30):
                    out.append((ev["cik"], ev["class"], ev["date"], acc, form, filed, accepted, items, primary))
    return out


def _work(args):
    zip_path, files_of = args
    if _Z.get("path") != zip_path:
        _Z["path"], _Z["z"] = zip_path, zipfile.ZipFile(zip_path)
    z = _Z["z"]
    out = []
    for cik, files in files_of:
        blocks = [json.loads(z.read(n)) for n in sorted(files, key=lambda n: ("-submissions-" in n, n))]          # the main file first, as D1 was built
        main = next((b for b in blocks if "filings" in b), blocks[0])
        filings = D.filings_of(blocks)
        evs = D.classify_exit_events(cik, filings)
        rows = sorted(_rows_of(blocks), key=lambda x: x[2])
        for ev in evs:
            ev["name"] = main.get("name")
        out.append((cik, evs, [r for ev in evs for r in eight_k_rows(rows, ev)]))
    return out


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def build_all_events_index(submissions_zip, d1_dir, out_dir, workers: int = 3) -> dict:
    submissions_zip, d1_dir, out_dir = Path(submissions_zip), Path(d1_dir), Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise DataNotPresent(f"{out_dir} exists and is not empty: the all-events index goes into a new folder")
    d1 = di.EventIndex(d1_dir)
    ciks = sorted({str(e["cik"]).zfill(10) for e in d1.events})
    want = set(ciks)
    with zipfile.ZipFile(submissions_zip) as z:
        files: Dict[str, List[str]] = {}
        for n in z.namelist():
            if n.startswith("CIK") and n.endswith(".json") and n[3:13] in want:
                files.setdefault(n[3:13], []).append(n)
    missing = sorted(want - set(files))
    if missing:
        raise DataNotPresent(f"{len(missing)} companies of D1 are not in {submissions_zip} (first: {missing[:3]})")
    items = [(c, files[c]) for c in ciks]
    chunks = [items[i::workers * 16] for i in range(workers * 16)]
    got: Dict[str, tuple] = {}
    with Pool(workers) as pool:
        for part in pool.imap_unordered(_work, [(str(submissions_zip), c) for c in chunks if c]):
            for cik, evs, rows in part:
                got[cik] = (evs, rows)
    all_events = [e for c in ciks for e in sorted(got[c][0], key=lambda e: e["date"])]            # clusters are at least the cluster gap apart: no two events share a date
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(d1_dir / di.EVENTS_FILE, out_dir / di.EVENTS_FILE)
    d1_keys, d1_rows = set(), []
    with gzip.open(d1_dir / di.EVENT_8K_FILE, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            d1_rows.append(r)
            d1_keys.add((str(r["cik"]).zfill(10), r["accession"]))
    added = []
    for c in ciks:
        for r in got[c][1]:
            k = (str(r[0]).zfill(10), r[3])
            if k not in d1_keys:
                d1_keys.add(k)
                added.append(dict(zip(COLUMNS, r)))
    with gzip.open(out_dir / di.EVENT_8K_FILE, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(d1_rows)
        w.writerows(sorted(added, key=lambda r: (r["cik"], r["filed"], r["accession"])))
    (out_dir / di.ALL_EVENTS_FILE).write_text(json.dumps(all_events), encoding="utf-8")
    first = {}
    for e in all_events:
        first.setdefault(e["cik"], e)
    d1_first = {str(e["cik"]).zfill(10): e for e in d1.events}
    same = sum(1 for c, e in d1_first.items() if c in first and (first[c]["date"], first[c]["class"]) == (e["date"], e["class"]))
    same_evidence = sum(1 for c, e in d1_first.items() if c in first and first[c]["evidence"] == e["evidence"])
    per_co = Counter(Counter(e["cik"] for e in all_events).values())
    man = {"source_zip": str(submissions_zip), "source_zip_bytes": submissions_zip.stat().st_size, "source_zip_sha256": _sha256(submissions_zip), "d1_dir": str(d1_dir),
           "d1_events_sha256": d1.events_sha256, "d1_companies": len(ciks), "all_events": len(all_events), "events_per_company": {str(k): v for k, v in sorted(per_co.items())},
           "classes": dict(Counter(e["class"] for e in all_events)), "cluster_days": D.EVENT_CLUSTER_DAYS, "d1_event_8k_rows": len(d1_rows), "added_event_8k_rows": len(added),
           "d1_first_event_reproduced_by_date_and_class": same, "d1_first_event_reproduced_with_identical_evidence": same_evidence, "d1_first_event_differs": len(d1_first) - same}
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man
