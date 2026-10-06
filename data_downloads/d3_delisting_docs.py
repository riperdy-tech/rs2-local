"""D3: 8-K main documents and exhibits (Items 2.01, 1.03, 3.01, 5.01) for delisting events found by the harness classifier
(rebuild_harness/delistings.py, branch review-2026-10/rebuild-int) over the full submissions.zip.

Input : data/sec_bulk/index/event_8k.csv.gz (index_submissions.py: the 8-Ks with those items near each classified event)
Output: data/sec_bulk/delisting_docs/<cik>/<accession>/<document files>  +  delisting_docs/_manifest.jsonl (resumable)
Per filing: one index.json request, then every .htm/.html/.txt document in the filing (main + exhibits; not the -index pages, the complete-submission
.txt, XBRL R-files, images or archives).  Global <= RATE req/s with the SEC UA.
"""
import argparse, csv, gzip, json, re, threading, time
from concurrent.futures import ThreadPoolExecutor
from sec_common import SEC_BULK, RateLimiter, http_get, make_logger, check_disk

ap = argparse.ArgumentParser()
ap.add_argument("--rate", type=float, default=2.5)
ap.add_argument("--workers", type=int, default=3)
ap.add_argument("--limit", type=int, default=0)
a = ap.parse_args()

OUT = SEC_BULK / "delisting_docs"
MAN = OUT / "_manifest.jsonl"
log = make_logger(SEC_BULK / "_logs" / "d3_delisting_docs.log")
limiter = RateLimiter(a.rate)
lock = threading.Lock()
MAX_BYTES = 30_000_000
DOC = re.compile(r"\.(htm|html|txt)$", re.I)


def wanted(name, acc):
    n = name.lower()
    if not DOC.search(n):
        return False
    if n.startswith(acc.lower()):  # {acc}.txt (complete submission), {acc}-index.html, {acc}-index-headers.html
        return False
    if re.match(r"r\d+\.htm", n) or n in ("filingsummary.xml",):
        return False
    return True


def fetch_filing(row):
    cik, acc = row["cik"], row["accession"]
    nd = acc.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nd}/"
    s, b = http_get(base + "index.json", limiter)
    rec = {k: row[k] for k in ("cik", "event_class", "event_date", "accession", "form", "filed", "accepted", "items")}
    if s != 200:
        rec.update(status=f"index_{s}", files=[])
        return rec
    items = json.loads(b)["directory"]["item"]
    d = OUT / cik / acc
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for it in items:
        name = it["name"]
        if not wanted(name, acc):
            continue
        size = it.get("size")
        if size and size.isdigit() and int(size) > MAX_BYTES:
            files.append({"name": name, "status": "skipped_large", "bytes": int(size)}); continue
        p = d / name
        if p.exists() and p.stat().st_size > 0:
            files.append({"name": name, "status": "ok", "bytes": p.stat().st_size, "cached": True}); continue
        s2, b2 = http_get(base + name, limiter)
        if s2 == 200:
            p.write_bytes(b2)
            files.append({"name": name, "status": "ok", "bytes": len(b2)})
        else:
            files.append({"name": name, "status": f"http_{s2}", "bytes": 0})
    ok = all(f["status"] in ("ok", "skipped_large") for f in files)
    rec.update(status="ok" if ok else "partial", files=files)
    return rec


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(SEC_BULK / "index" / "event_8k.csv.gz", "rt", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    done = set()
    if MAN.exists():
        for line in open(MAN, encoding="utf-8"):
            try:
                r = json.loads(line)
                if r["status"] in ("ok", "index_404"):
                    done.add(r["accession"])
            except Exception:
                pass
    # one filing may serve several events -> dedupe by accession
    seen, todo = set(), []
    for r in rows:
        if r["accession"] not in done and r["accession"] not in seen:
            seen.add(r["accession"]); todo.append(r)
    if a.limit:
        todo = todo[:a.limit]
    log(f"event 8-K rows {len(rows)}; filings to do {len(todo)} (done {len(done)})")
    n = [0]; t0 = time.time()
    fh = open(MAN, "a", encoding="utf-8")

    def job(r):
        rec = fetch_filing(r)
        with lock:
            fh.write(json.dumps(rec) + "\n"); fh.flush(); n[0] += 1
            if n[0] % 250 == 0:
                log(f"{n[0]}/{len(todo)} {time.time()-t0:.0f}s free={check_disk():.0f}GB")
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(job, todo))
    log("DONE")


main()
