"""sec_store.py - the raw SEC store of qwen_c (SPEC_m3m_qwen_pipeline.md §2).

Every SEC document a packet uses is kept as the exact bytes SEC served, under cache/m3m/raw/<sha256>, with one line per fetch in
cache/m3m/raw/receipts.jsonl: url, sha256, bytes, HTTP status, fetched_at (a self-claim of this machine's clock) and the User-Agent.

- `get(url, online=...)` serves the latest receipt of `url` from disk, its sha256 rechecked (a mismatch raises StoreCorrupt). A miss
  offline raises NotInStore. Online, a miss is fetched; a SUBMISSIONS url (it changes daily) is fetched again on every online call, and
  each fetch is a new receipt. Only https sec.gov / www.sec.gov / data.sec.gov, sec_guidance's User-Agent, at least THROTTLE_S between
  requests; only HTTP 200 is stored, anything else raises FetchFailed(status).
- `get_pinned(url, sha256)` returns exactly the bytes a packet pinned, or raises. Replay reads only through it.
- Writes are atomic (a temporary file, then a rename) and append-only: an existing sha256 file is never rewritten.
"""
import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from sec_guidance import UA

REPO = Path(__file__).resolve().parent.parent
RAW_DIR = REPO / "cache" / "m3m" / "raw"
RECEIPTS = "receipts.jsonl"

ALLOWED_HOSTS = ("sec.gov", "www.sec.gov", "data.sec.gov")
MUTABLE_PREFIXES = ("https://data.sec.gov/submissions/", "https://data.sec.gov/api/xbrl/companyfacts/")   # rewritten in place by SEC: each online get is a new fetch (companyfacts: CROSS_CHECK_Q 8)
THROTTLE_S = 0.15
TIMEOUT_S = 60
MAX_BYTES = 80_000_000

_lock = threading.Lock()
_last_request = [0.0]


class StoreError(Exception):
    pass


class NotInStore(StoreError):
    pass


class StoreCorrupt(StoreError):
    pass


class FetchFailed(StoreError):
    def __init__(self, status, detail=""):
        super().__init__(f"fetch failed: status={status} {detail}".strip())
        self.status = status
        self.detail = detail


def _root(root):
    return Path(root) if root is not None else RAW_DIR


def _check_url(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or (u.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError(f"sec_store fetches only https sec.gov and data.sec.gov, not {url[:80]}")


def _receipts(root):
    p = root / RECEIPTS
    if not p.exists():
        return []
    out = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                raise StoreCorrupt(f"{p} line {n} is not a receipt (a torn append?)") from None
    return out


def _read_checked(root, sha256):
    p = root / sha256
    if not p.is_file():
        raise NotInStore(f"no stored bytes for sha256 {sha256}")
    data = p.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        raise StoreCorrupt(f"stored bytes of {sha256} hash to {got}")
    return data


def _write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _store(root, url, data, status, user_agent):
    root.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    p = root / sha
    if p.exists():
        _read_checked(root, sha)            # never overwritten; a corrupt existing copy is an error, not something to repair silently
    else:
        _write_atomic(p, data)
    receipt = {"url": url, "sha256": sha, "bytes": len(data), "status": status,
               "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "user_agent": user_agent}
    line = (json.dumps(receipt, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    with open(root / RECEIPTS, "ab") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return sha


def _fetch(url):
    """(status, bytes) of one request, after the throttle. Any status other than 200, and any transport failure, raises FetchFailed."""
    _check_url(url)
    with _lock:
        wait = THROTTLE_S - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers=dict(UA))
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                final = r.geturl()
                status = r.status
                data = r.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            raise FetchFailed(e.code, url) from None
        except (urllib.error.URLError, OSError) as e:
            raise FetchFailed(None, f"{url} {type(e).__name__}: {str(e)[:120]}") from None
        finally:
            _last_request[0] = time.monotonic()
    if final != url:
        _check_url(final)
    if status != 200:
        raise FetchFailed(status, url)
    if len(data) > MAX_BYTES:
        raise FetchFailed(status, f"{url} larger than {MAX_BYTES} bytes")
    return status, data


def latest_receipt(url, *, root=None):
    """The last receipt of `url` in the store, or None."""
    hit = None
    for r in _receipts(_root(root)):
        if r.get("url") == url:
            hit = r
    return hit


def get(url, *, online, root=None):
    """The bytes of `url`: the store's latest copy, or (online) a fresh fetch. See the module docstring."""
    root = _root(root)
    _check_url(url)
    mutable = url.startswith(MUTABLE_PREFIXES)
    if not (online and mutable):
        rec = latest_receipt(url, root=root)
        if rec is not None:
            return _read_checked(root, rec["sha256"])
        if not online:
            raise NotInStore(url)
    status, data = _fetch(url)
    _store(root, url, data, status, UA["User-Agent"])
    return data


def get_pinned(url, sha256, *, root=None):
    """Exactly the bytes of (url, sha256): a receipt must bind that url to that sha256, and the stored bytes must hash to it."""
    root = _root(root)
    if not any(r.get("url") == url and r.get("sha256") == sha256 for r in _receipts(root)):
        raise NotInStore(f"{url} with sha256 {sha256}")
    return _read_checked(root, sha256)
