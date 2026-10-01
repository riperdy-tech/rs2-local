"""closure_enrich_batch.py - the ONE networked step of the reference closure (revision 18, brief section 2 step 3).

Runs enrich_ticker.enrich (Yahoo Finance via yfinance) over a list of tickers - the closure aggregate's names - and caches
the raw output under <repo>/cache/closure_enrich/<vintage date>/<TICKER>.json, one file per name. It writes nothing else: not
the live enrich/ directory (enrich_ticker's own CLI does that; this script never calls it), not the main checkout.

    python tools/closure_enrich_batch.py --names names.txt [--workers 3] [--date YYYY-MM-DD]

Resumable (a name whose file exists is skipped, and counted as such) and recorded: manifest.json beside the files holds the start and
end time, the ticker count, a sha256 per file, the manifest's own hash (over the sorted file hashes), and the failure counts. A
name whose enrich() raised is retried once and both attempts are counted. A record that is entirely null (no estimates, no ownership,
no targets) is the signature of a broken Yahoo session (an "Invalid Crumb" 401 that enrich() swallows): it is retried once after the
session's cookie and crumb are reset, and counted as `suspect_retried`; a name that is still null is kept as it is. enrich() itself swallows vendor errors and returns nulls,
so "estimates null" is counted separately and is not a failure of this script.
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

    def one(t):
        path = out_dir / f"{t}.json"
        if path.exists():
            with lock:
                stats["skipped_existing"] += 1
                stats["done"] += 1
            return
        data, err = None, None
        for attempt in (1, 2):
            try:
                data = enrich_ticker.enrich(t)
                err = None
                break
            except Exception as e:  # noqa: BLE001 - recorded by type, never hidden
                err = type(e).__name__
                if attempt == 1:
                    with lock:
                        stats["retried"] += 1
                    time.sleep(3.0)
        if data is not None and not data.get("estimates") and data.get("institutional_pct") is None and data.get("analyst_target_mean") is None:
            with lock:
                stats["suspect_retried"] += 1
            try:
                from yfinance.data import YfData
                YfData()._crumb = None
                YfData()._cookie = None
            except Exception:  # noqa: BLE001 - the retry below still runs; the counts say what happened
                pass
            time.sleep(5.0)
            try:
                again = enrich_ticker.enrich(t)
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
    files = {p.name: sha256_file(p) for p in sorted(out_dir.glob("*.json")) if p.name != "manifest.json"}
    manifest = {"vintage": vintage, "source": "Yahoo Finance via yfinance (enrich_ticker.enrich)", "started_utc": started,
                "ended_utc": ended, "tickers_requested": len(names), "files": len(files), "stats": stats,
                "failure_types": failures, "file_sha256": files,
                "manifest_sha256": hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(files.items())).encode()).hexdigest()}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("done", {k: v for k, v in manifest.items() if k != "file_sha256"}, flush=True)


if __name__ == "__main__":
    main()
