"""Index submissions.zip (D1) into compact tables used by D2/D3 (derived artifact; no network).

Outputs in data/sec_bulk/index/:
  companies.csv.gz   cik,name,sic,tickers,exchanges,n_filings
  annual.csv.gz      cik,accession,form,filed,accepted,report_date,primary_doc   (annual-report forms incl. amendments)
  events.json        harness delisting events (rebuild_harness.delistings.classify_company over the full archive)
  event_8k.csv.gz    cik,event_class,event_date,accession,form,filed,accepted,items,primary_doc  (8-Ks with items 2.01/1.03/3.01/5.01 near an event)
"""
import csv, gzip, json, sys, zipfile, time
from multiprocessing import Pool
from pathlib import Path
from sec_common import SEC_BULK, STOCKS, make_logger

WT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WT))
from rebuild_harness import delistings as D  # branch review-2026-10/rebuild-int

ZIP = SEC_BULK / "submissions.zip"
OUT = SEC_BULK / "index"
ANNUAL = {"10-K", "10-K405", "10-KSB", "10-KSB40", "10KSB", "10KSB40", "10-KT", "10KT405", "10-K405T", "10-KT405", "20-F", "40-F"}
ANNUAL |= {f + "/A" for f in list(ANNUAL)}
ITEMS = {"2.01", "1.03", "3.01", "5.01"}
_z = None


def blocks_of(name_main):
    global _z
    if _z is None:
        _z = zipfile.ZipFile(ZIP)
    doc = json.loads(_z.read(name_main))
    blocks = [doc]
    for f in (doc.get("filings") or {}).get("files") or []:
        try:
            blocks.append(json.loads(_z.read(f["name"])))
        except KeyError:
            pass
    return doc, blocks


def rows_of(blocks):
    """Full rows (all fields we keep) from every block."""
    for b in blocks:
        r = (b.get("filings") or {}).get("recent") if "filings" in b else b
        r = r or {}
        n = len(r.get("form") or [])
        g = lambda k: r.get(k) or [""] * n
        acc, form, fd, ad, rd, it, pd_ = g("accessionNumber"), g("form"), g("filingDate"), g("acceptanceDateTime"), g("reportDate"), g("items"), g("primaryDocument")
        for i in range(n):
            yield (acc[i], form[i], fd[i], ad[i], rd[i], str(it[i] or ""), pd_[i])


def work(name):
    try:
        return _work(name)
    except Exception as e:
        return ((name, repr(e)), [], None, [])


def _work(name):
    doc, blocks = blocks_of(name)
    cik = name[3:13]
    rows = sorted(rows_of(blocks), key=lambda x: x[2])
    filings = D.filings_of(blocks)
    ev = D.classify_company(cik, filings)
    comp = (cik, doc.get("name"), doc.get("sic"), "|".join(doc.get("tickers") or []), "|".join(x or "" for x in (doc.get("exchanges") or [])), len(rows))
    annual = [(cik,) + (r[0], r[1], r[2], r[3], r[4], r[6]) for r in rows if r[1] in ANNUAL]
    e8 = []
    if ev:
        ev["name"] = doc.get("name")
        d0 = D._d(ev["date"])
        for r in rows:
            if r[1] in ("8-K", "8-K/A") and r[5]:
                its = {x.strip() for x in r[5].split(",")}
                if its & ITEMS and -540 <= (D._d(r[2]) - d0).days <= 30:
                    # keep: bankruptcy items up to 540d before; 2.01/3.01/5.01 within 45d before .. 30d after (the classifier's window plus slack)
                    dd = (D._d(r[2]) - d0).days
                    if (its & {"1.03"}) or -45 <= dd <= 30:
                        e8.append((cik, ev["class"], ev["date"], r[0], r[1], r[2], r[3], r[5], r[6]))
    return comp, annual, ev, e8


def main():
    log = make_logger(SEC_BULK / "_logs" / "index_submissions.log")
    OUT.mkdir(exist_ok=True)
    z = zipfile.ZipFile(ZIP)
    names = [n for n in z.namelist() if "-submissions-" not in n]
    log(f"{len(names)} company files")
    comps, annual, events, e8, bad = [], [], [], [], []
    t0 = time.time()
    with Pool(8) as p:
        for i, (c, a, ev, e) in enumerate(p.imap_unordered(work, names, chunksize=200)):
            if len(c) == 2:
                bad.append(c); log(f'BAD FILE {c}'); continue
            comps.append(c); annual += a; e8 += e
            if ev: events.append(ev)
            if i % 50000 == 0:
                log(f"{i}/{len(names)} {time.time()-t0:.0f}s annual={len(annual)} events={len(events)}")
    comps.sort(); annual.sort(key=lambda r: (r[0], r[3], r[1])); events.sort(key=lambda e: e["cik"]); e8.sort()
    def w(path, header, rows):
        with gzip.open(OUT / path, "wt", encoding="utf-8", newline="") as f:
            cw = csv.writer(f); cw.writerow(header); cw.writerows(rows)
    w("companies.csv.gz", ["cik", "name", "sic", "tickers", "exchanges", "n_filings"], comps)
    w("annual.csv.gz", ["cik", "accession", "form", "filed", "accepted", "report_date", "primary_doc"], annual)
    w("event_8k.csv.gz", ["cik", "event_class", "event_date", "accession", "form", "filed", "accepted", "items", "primary_doc"], e8)
    (OUT / "bad_files.json").write_text(json.dumps(bad))
    (OUT / "events.json").write_text(json.dumps(events))
    from collections import Counter
    log("DONE companies=%d annual=%d events=%d event_8k=%d" % (len(comps), len(annual), len(events), len(e8)))
    log("event classes: " + json.dumps(Counter(e["class"] for e in events)))


if __name__ == "__main__":
    main()
