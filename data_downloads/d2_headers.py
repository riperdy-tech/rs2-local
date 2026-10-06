"""D2: EDGAR filing headers (.hdr.sgml; fallback -index-headers.html) for every annual-report filing in the D1 index.

Input : data/sec_bulk/index/annual.csv.gz (built from submissions.zip by index_submissions.py)
Output: data/sec_bulk/headers/headers_raw.csv (append-only, resumable; one row per accession, status ok/404/error)
        data/sec_bulk/headers/headers.csv.gz  (final table: cik, accession, form, filed, accepted, sic, name [+ status, source, accepted_index])
Order : filings filed 2009+ first (newest first within year is irrelevant; sorted by filed), then pre-2009.
Rate  : global <= RATE req/s (default 8), same SEC UA.   --max-requests N caps this run.
"""
import argparse, csv, gzip, re, threading, time
from concurrent.futures import ThreadPoolExecutor
from sec_common import SEC_BULK, RateLimiter, http_get, make_logger, check_disk

ap = argparse.ArgumentParser()
ap.add_argument("--rate", type=float, default=8.0)
ap.add_argument("--workers", type=int, default=8)
ap.add_argument("--max-requests", type=int, default=0)
ap.add_argument("--from-year", type=int, default=0, help="only filings filed in/after this year (0 = all)")
ap.add_argument("--to-year", type=int, default=9999)
ap.add_argument("--finalize-only", action="store_true")
a = ap.parse_args()

IDX = SEC_BULK / "index" / "annual.csv.gz"
OUT = SEC_BULK / "headers"
RAW = OUT / "headers_raw.csv"
log = make_logger(SEC_BULK / "_logs" / "d2_headers.log")
FIELDS = ["cik", "accession", "form", "filed", "accepted_index", "accepted_header", "sic", "name", "status", "source"]
limiter = RateLimiter(a.rate)
lock = threading.Lock()
reqs = [0]


def parse(text, cik):
    """Pick the <COMPANY-DATA> block whose <CIK> equals the filer; fall back to the first."""
    acc = re.search(r"<ACCEPTANCE-DATETIME>(\d+)", text)
    blocks = re.findall(r"<COMPANY-DATA>(.*?)</COMPANY-DATA>", text, re.S)
    pick = None
    for b in blocks:
        m = re.search(r"<CIK>(\d+)", b)
        if m and m.group(1).zfill(10) == cik:
            pick = b; break
    if pick is None and blocks:
        pick = blocks[0]
    sic = name = ""
    if pick:
        m = re.search(r"<ASSIGNED-SIC>\s*(\d+)", pick); sic = m.group(1) if m else ""
        m = re.search(r"<CONFORMED-NAME>([^\r\n<]*)", pick); name = m.group(1).strip() if m else ""
    return (acc.group(1) if acc else ""), sic, name


def fetch(row):
    cik, acc = row["cik"], row["accession"]
    nd = acc.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nd}/{acc}"
    for src, url in (("hdr.sgml", base + ".hdr.sgml"), ("index-headers.html", base + "-index-headers.html")):
        if a.max_requests and reqs[0] >= a.max_requests:
            return None
        with lock:
            reqs[0] += 1
        s, b = http_get(url, limiter)
        if s == 200:
            acc_h, sic, name = parse(b.decode("latin-1"), cik)
            return [cik, acc, row["form"], row["filed"], row["accepted"], acc_h, sic, name, "ok", src]
        if s not in (404, 403):
            return [cik, acc, row["form"], row["filed"], row["accepted"], "", "", "", "error:" + str(s), src]
    return [cik, acc, row["form"], row["filed"], row["accepted"], "", "", "", "404", ""]


def load_done():
    done = set()
    if RAW.exists():
        with open(RAW, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["status"] == "ok" or r["status"] == "404":
                    done.add(r["accession"])
    return done


def finalize():
    best = {}
    with open(RAW, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["accession"] not in best or r["status"] in ("ok", "404"):
                best[r["accession"]] = r
    rows = sorted(best.values(), key=lambda r: (r["cik"], r["filed"], r["accession"]))
    with gzip.open(OUT / "headers.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cik", "accession", "form", "filed", "accepted", "sic", "name", "status", "source", "accepted_index"])
        for r in rows:
            w.writerow([r["cik"], r["accession"], r["form"], r["filed"], r["accepted_header"], r["sic"], r["name"], r["status"], r["source"], r["accepted_index"]])
    from collections import Counter
    log(f"finalized {len(rows)} rows; status {dict(Counter(r['status'] for r in rows))}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if a.finalize_only:
        return finalize()
    with gzip.open(IDX, "rt", encoding="utf-8", newline="") as f:
        allrows = list(csv.DictReader(f))
    allrows = [r for r in allrows if a.from_year <= int(r["filed"][:4]) <= a.to_year]
    allrows.sort(key=lambda r: (int(r["filed"][:4]) < 2009, r["filed"]))
    done = load_done()
    todo = [r for r in allrows if r["accession"] not in done]
    log(f"annual filings in scope {len(allrows)}; done {len(done)}; to do {len(todo)}; rate {a.rate}/s")
    new = not RAW.exists()
    fh = open(RAW, "a", newline="", encoding="utf-8")
    w = csv.writer(fh)
    if new:
        w.writerow(FIELDS)
    n = [0]; t0 = time.time()

    def job(r):
        res = fetch(r)
        if res is None:
            return
        with lock:
            w.writerow(res); n[0] += 1
            if n[0] % 500 == 0:
                fh.flush()
            if n[0] % 5000 == 0:
                log(f"{n[0]}/{len(todo)} {n[0]/(time.time()-t0):.1f}/s requests={reqs[0]} free={check_disk():.0f}GB")
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(job, todo))
    fh.close()
    log(f"run complete: {n[0]} rows this run; requests {reqs[0]}")
    finalize()


main()
