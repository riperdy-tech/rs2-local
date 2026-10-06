"""D1: SEC bulk submissions.zip -> data/sec_bulk/submissions.zip (resumable). Records sha256."""
import hashlib, json, sys
from sec_common import *

URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
log = make_logger(SEC_BULK / "_logs" / "d1_submissions.log")
check_disk()
dest = SEC_BULK / "submissions.zip"
req = urllib.request.Request(URL, headers=UA, method="HEAD")
with urllib.request.urlopen(req, timeout=60) as r:
    size = int(r.headers["Content-Length"]); log(f"HEAD ok size={size} lm={r.headers.get('Last-Modified')}")
n = resumable_download(URL, dest, log, expected=size)
assert n == size, (n, size)
h = hashlib.sha256()
with open(dest, "rb") as f:
    for b in iter(lambda: f.read(1 << 22), b""):
        h.update(b)
rec = {"url": URL, "bytes": n, "sha256": h.hexdigest()}
(SEC_BULK / "submissions.zip.sha256.json").write_text(json.dumps(rec, indent=1))
log(f"DONE {rec}")
