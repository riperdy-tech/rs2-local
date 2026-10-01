"""closure_enrich_batch.py - the ONE networked step of the reference closure (revision 18, brief section 2 step 3).

Runs enrich_ticker.enrich (Yahoo Finance via yfinance) over a list of tickers - the closure aggregate's names - and caches
the raw output under <repo>/cache/closure_enrich/<vintage date>/<TICKER>.json, one file per name. It writes nothing else: not
the live enrich/ directory (enrich_ticker's own CLI does that; this script never calls it), not the main checkout.

    python tools/closure_enrich_batch.py --names names.txt [--workers 3] [--date YYYY-MM-DD]

Resumable (a name whose file exists is skipped, and counted as such) and recorded: manifest.json beside the files holds the start and
end time, the ticker count, a sha256 per file, the manifest's own hash (over the sorted file hashes), and the failure counts. A
name whose enrich() raised is retried once and both attempts are counted.

A VENDOR HTTP ERROR (401 "Invalid Crumb", 429, 5xx) comes back from enrich() as an error record (`_status: "error"`, no `estimates`
key) - a failed fetch, never "no consensus". It is retried once after the session's cookie and crumb are reset; if the retry fails
too, the name's file is NOT written, the batch STOPS (the names not yet fetched are not attempted), the manifest records
`stopped_on` (the status, the request and the count of names left), and the script exits 3. Run it again later: it resumes.
A record that is entirely null (no estimates, no ownership, no targets) without an error status is still suspect: it is retried
once after a session reset and counted as `suspect_retried`; a name that is still null is kept as it is, and "estimates null" is
counted separately (a name the vendor answered for and has no consensus on is not a failure of this script).
"""
import argparse
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import enrich_ticker  # noqa: E402  (yfinance: the only network client this script uses)


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _reset_session():
    try:
        from yfinance.data import YfData
        YfData()._crumb = None
        YfData()._cookie = None
    except Exception:  # noqa: BLE001 - the retry still runs; the counts say what happened
        pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--date", default=None, help="vintage date; default today (UTC)")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)
    vintage = a.date or datetime.now(timezone.utc).date().isoformat()
    out_dir = HERE / "cache" / "closure_enrich" / vintage
    out_dir.mkdir(parents=True, exist_ok=True)
    names = [l.strip().upper() for l in a.names.read_text().splitlines() if l.strip()]
    if a.limit is not None:
        names = names[: a.limit]
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lock = threading.Lock()
    stats = {"skipped_existing": 0, "fetched": 0, "retried": 0, "suspect_retried": 0, "failed_after_retry": 0, "estimates_null": 0,
             "done": 0}
    failures = {}
    stop = threading.Event()
    stopped = {}

    def error_stop(t, rec):
        """Count a name whose record is still an error record after its retry, and stop the batch."""
        err = rec["_error"]
        with lock:
            stats["done"] += 1
            stats["failed_after_retry"] += 1
            key = f"http_{err['http_status']}"
            failures[key] = failures.get(key, 0) + 1
            stopped.setdefault("http_status", err["http_status"])
            stopped.setdefault("where", err["where"])
        stop.set()

    def one(t):
        if stop.is_set():
            return
        path = out_dir / f"{t}.json"
        if path.exists():
            with lock:
                stats["skipped_existing"] += 1
                stats["done"] += 1
            return
        data, err = None, None
        for attempt in (1, 2):
            try:
                data = enrich_ticker.enrich_with_retry(t, retries=1, cooloff=5.0, before_retry=_reset_session)
                err = None
                break
            except Exception as e:  # noqa: BLE001 - recorded by type, never hidden
                err = type(e).__name__
                if attempt == 1:
                    with lock:
                        stats["retried"] += 1
                    time.sleep(3.0)
        if data is not None and enrich_ticker.is_error_record(data):
            error_stop(t, data)
            return
        if data is not None and not data.get("estimates") and data.get("institutional_pct") is None and data.get("analyst_target_mean") is None:
            with lock:
                stats["suspect_retried"] += 1
            _reset_session()
            time.sleep(5.0)
            try:
                again = enrich_ticker.enrich_with_retry(t, retries=1, cooloff=5.0, before_retry=_reset_session)
                if enrich_ticker.is_error_record(again):
                    error_stop(t, again)
                    return
                data = again
            except Exception as e:  # noqa: BLE001
                err = type(e).__name__
        with lock:
            stats["done"] += 1
            if data is None:
                stats["failed_after_retry"] += 1
                failures[err] = failures.get(err, 0) + 1
            else:
                stats["fetched"] += 1
                if not data.get("estimates"):
                    stats["estimates_null"] += 1
            n = stats["done"]
        if data is not None:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if n % 25 == 0 or n == len(names):
            print(f"[{n}/{len(names)}] {datetime.now(timezone.utc).strftime('%H:%M:%S')} {dict(stats)}", flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, names))
    ended = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if stopped:
        stopped["names_left"] = len(names) - stats["done"]
    files = {p.name: sha256_file(p) for p in sorted(out_dir.glob("*.json")) if p.name != "manifest.json"}
    manifest = {"vintage": vintage, "source": "Yahoo Finance via yfinance (enrich_ticker.enrich)", "started_utc": started,
                "ended_utc": ended, "tickers_requested": len(names), "files": len(files), "stats": stats,
                "failure_types": failures, "stopped_on": stopped or None, "file_sha256": files,
                "manifest_sha256": hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(files.items())).encode()).hexdigest()}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("done", {k: v for k, v in manifest.items() if k != "file_sha256"}, flush=True)
    if stopped:
        print(f"STOPPED: the vendor answered HTTP {stopped['http_status']} at {stopped['where']} after a retry; "
              f"{stopped['names_left']} name(s) were not fetched. Nothing was written for the failing name. Run again to resume.",
              file=sys.stderr, flush=True)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
