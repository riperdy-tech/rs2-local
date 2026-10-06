"""Shared bits for the rev23 free-data downloads (D1-D5). Stdlib only.

UA is the repo's SEC User-Agent (rs2-local/sec_guidance.py, UA constant) - imported, not re-typed,
when that module is importable; the literal below is a verbatim copy used only as a fallback.
"""
import os, sys, time, threading, shutil
import urllib.request, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
try:
    from sec_guidance import UA as _UA
    UA = dict(_UA)
except Exception:  # pragma: no cover
    UA = {"User-Agent": "RS2-Local research riperdy@gmail.com"}

STOCKS = Path(os.environ.get("STOCKS_ROOT", r"C:\Users\riper\stocks"))
DATA = STOCKS / "stocks-workspace" / "data"
SEC_BULK = DATA / "sec_bulk"
PRICES = DATA / "prices_daily"
MIN_FREE_GB = 30.0


class RateLimiter:
    """Global <=N requests/second across threads."""
    def __init__(self, per_sec=8.0):
        self.gap = 1.0 / per_sec
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        if t > now:
            time.sleep(t - now)


def free_gb(path=r"C:\\"):
    return shutil.disk_usage(path).free / 1e9


def check_disk():
    g = free_gb()
    if g < MIN_FREE_GB:
        raise SystemExit(f"STOP: free disk {g:.1f} GB < {MIN_FREE_GB} GB")
    return g


def http_get(url, limiter=None, retries=5, timeout=60, extra=None):
    """Return (status, bytes). 404/403 returned as status, not raised. Retries 429/5xx/network."""
    hdr = dict(UA)
    if extra:
        hdr.update(extra)
    last = None
    for i in range(retries):
        if limiter:
            limiter.wait()
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 403, 400):
                return e.code, b""
            last = f"HTTP {e.code}"
            time.sleep(min(60, 2 ** i * (5 if e.code == 429 else 1)))
        except Exception as e:
            last = repr(e)
            time.sleep(min(60, 2 ** i))
    return -1, (last or "").encode()


def resumable_download(url, dest: Path, log, expected=None, chunk=1 << 20, max_attempts=50):
    """Range-resumable download into dest+'.part'; renames on completion. Returns final size."""
    dest = Path(dest)
    part = Path(str(dest) + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (expected is None or dest.stat().st_size == expected):
        log(f"already complete: {dest} {dest.stat().st_size}")
        return dest.stat().st_size
    for attempt in range(max_attempts):
        have = part.stat().st_size if part.exists() else 0
        hdr = dict(UA)
        if have:
            hdr["Range"] = f"bytes={have}-"
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=120) as r:
                code = r.status
                total = None
                cr = r.headers.get("Content-Range")
                if code == 206 and cr:
                    total = int(cr.split("/")[-1])
                elif code == 200:
                    total = int(r.headers.get("Content-Length") or 0) or None
                    if have:  # server ignored Range -> restart
                        have = 0
                        part.unlink()
                if expected is None:
                    expected = total
                mode = "ab" if have else "wb"
                t0 = time.time(); last = t0; got0 = have
                with open(part, mode) as f:
                    while True:
                        b = r.read(chunk)
                        if not b:
                            break
                        f.write(b)
                        have += len(b)
                        if time.time() - last > 30:
                            last = time.time()
                            mbs = (have - got0) / 1e6 / max(1e-9, last - t0)
                            log(f"progress {have/1e6:.0f}/{(expected or 0)/1e6:.0f} MB  {mbs:.1f} MB/s  free {free_gb():.0f} GB")
                            check_disk()
            if expected is None or part.stat().st_size == expected:
                os.replace(part, dest)
                log(f"complete {dest} {dest.stat().st_size}")
                return dest.stat().st_size
            log(f"short read {part.stat().st_size}/{expected}; retrying")
        except urllib.error.HTTPError as e:
            if e.code == 416:  # already have it all
                if expected is None or part.stat().st_size == expected:
                    os.replace(part, dest)
                    return dest.stat().st_size
                part.unlink()
            elif e.code in (404, 403):
                log(f"HTTP {e.code} for {url}")
                return -e.code
            else:
                log(f"HTTP {e.code}; retry {attempt}")
        except SystemExit:
            raise
        except Exception as e:
            log(f"error {e!r}; retry {attempt}")
        time.sleep(min(60, 3 * (attempt + 1)))
    raise RuntimeError(f"gave up on {url}")


def make_logger(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lk = threading.Lock()
    def log(msg):
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg)
        with lk:
            print(line, flush=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    return log
