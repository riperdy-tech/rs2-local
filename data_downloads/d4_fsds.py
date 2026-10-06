"""D4: SEC Financial Statement Data Sets 2009q2..2026q3 -> data/sec_bulk/fsds/. Sequential (<<10 req/s). Resumable; 404s recorded."""
import hashlib, json
from sec_common import *

log = make_logger(SEC_BULK / "_logs" / "d4_fsds.log")
OUT = SEC_BULK / "fsds"
MAN = OUT / "_manifest.json"
man = json.loads(MAN.read_text()) if MAN.exists() else {}
quarters = [(y, q) for y in range(2009, 2027) for q in range(1, 5) if (y, q) >= (2009, 2) and (y, q) <= (2026, 3)]
for y, q in quarters:
    name = f"{y}q{q}"
    if man.get(name, {}).get("status") == "ok" and (OUT / f"{name}.zip").exists():
        continue
    if man.get(name, {}).get("status") == "404":
        continue
    check_disk()
    url = f"https://www.sec.gov/files/dera/data/financial-statement-data-sets/{name}.zip"
    n = resumable_download(url, OUT / f"{name}.zip", log)
    if n < 0:
        man[name] = {"status": str(-n), "url": url}
        log(f"{name}: HTTP {-n}")
    else:
        h = hashlib.sha256()
        with open(OUT / f"{name}.zip", "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""):
                h.update(b)
        man[name] = {"status": "ok", "bytes": n, "sha256": h.hexdigest(), "url": url}
        log(f"{name}: ok {n}")
    MAN.write_text(json.dumps(man, indent=1))
    time.sleep(1.0)
log("DONE " + json.dumps({k: v["status"] for k, v in man.items() if v["status"] != "ok"}))
