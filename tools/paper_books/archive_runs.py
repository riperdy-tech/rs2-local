"""WO_L1: archive GitHub Actions run metadata, jobs and logs for riperdy-tech/stock-screener.

Read-only against GitHub (gh CLI, signed in on this PC). Resumable and compatible with the first, partial pass
(2026-10-29 00:00-00:14 KST): each run folder holds run.json, jobs.json, logs.zip when available and
logs_status.json ({"logs_status": SAVED | LOGS_EXPIRED | INVALID_ZIP | ERROR, ...}). A run already SAVED with a
valid zip, or LOGS_EXPIRED, is skipped; everything else is retried. Oldest runs first, since they expire first.
Secret-pattern scan: counts only, never the matched text.
"""
import csv, hashlib, io, json, re, subprocess, sys, time, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_paths  # noqa: E402

REPO = "riperdy-tech/stock-screener"
HERE = book_paths.witness_archive()     # the archive (paths.py gh_witness_dir), not this file's folder
MIN_INTERVAL = 0.5  # seconds between API calls (about 2 per second)
SECRET = re.compile(rb"ghp_|github_pat_|gho_|AKIA|-----BEGIN|sk-[A-Za-z0-9]{20,}")
_last = [0.0]


def gh(path, paginate=False):
    wait = MIN_INTERVAL - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    p = subprocess.run(["gh", "api", path] + (["--paginate"] if paginate else []), capture_output=True)
    return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")


def json_objects(text):
    """--paginate concatenates JSON objects; yield each."""
    dec, i = json.JSONDecoder(), 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        obj, i = dec.raw_decode(text, i)
        yield obj


def zip_ok(path):
    try:
        with zipfile.ZipFile(path) as z:
            return z.testzip() is None
    except Exception:
        return False


def secret_matches(path):
    n = 0
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            n += len(SECRET.findall(z.read(name)))
    return n


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def status_of(d):
    f = d / "logs_status.json"
    if not f.exists():
        return {"logs_status": "PENDING"}
    return json.loads(f.read_text(encoding="utf-8"))


def listing():
    rc, body, err = gh(f"repos/{REPO}/actions/runs?per_page=100", paginate=True)
    if rc != 0:
        sys.exit(f"listing failed: {err}")
    runs, total = [], None
    for obj in json_objects(body.decode("utf-8")):
        total = obj.get("total_count", total)
        runs.extend(obj["workflow_runs"])
    (HERE / "runs_listing.json").write_text(json.dumps({"total_count": total, "workflow_runs": runs}, indent=1),
                                           encoding="utf-8")
    return total, runs


def archive(run):
    d = HERE / str(run["id"])
    st = status_of(d)["logs_status"]
    done = run.get("status") == "completed"
    if (st == "LOGS_EXPIRED" and done) or (st == "SAVED" and zip_ok(d / "logs.zip")):
        return
    d.mkdir(exist_ok=True)
    if not done:
        # A queued or running run has no logs yet; a 404 then means "not finished", not "expired".
        (d / "logs_status.json").write_text(json.dumps({"logs_status": "NOT_COMPLETED", "run_status": run.get("status")},
                                                       indent=2), encoding="utf-8")
        for name, path in (("run.json", f"repos/{REPO}/actions/runs/{run['id']}"),):
            rc, body, err = gh(path)
            if rc == 0:
                (d / name).write_bytes(body)
        return
    for name, path, pag in (("run.json", f"repos/{REPO}/actions/runs/{run['id']}", False),
                            ("jobs.json", f"repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100", True)):
        for _ in range(3):
            rc, body, err = gh(path, paginate=pag)
            if rc == 0:
                (d / name).write_bytes(body)
                break
    status = {"logs_status": "ERROR"}
    for _ in range(3):
        rc, body, err = gh(f"repos/{REPO}/actions/runs/{run['id']}/logs")
        if rc == 0:
            (d / "logs.zip").write_bytes(body)
            if zip_ok(d / "logs.zip"):
                status = {"logs_status": "SAVED", "secret_pattern_matches": secret_matches(d / "logs.zip")}
                break
            status = {"logs_status": "INVALID_ZIP"}
        elif "HTTP 410" in err or "HTTP 404" in err:
            status = {"logs_status": "LOGS_EXPIRED", "http_status": "HTTP_410" if "410" in err else "HTTP_404"}
            break
        else:
            status = {"logs_status": "ERROR", "error": (err.strip().splitlines() or [""])[-1][:200]}
    (d / "logs_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")


def runner_names(d):
    try:
        names = set()
        for obj in json_objects((d / "jobs.json").read_text(encoding="utf-8")):
            names |= {j.get("runner_name") or "" for j in obj.get("jobs", [])}
        return ";".join(sorted(n for n in names if n))
    except Exception:
        return ""


def write_index(runs):
    with open(HERE / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "workflow_name", "event", "head_sha", "created_at", "updated_at", "conclusion",
                    "logs_status", "logs_zip_bytes", "logs_zip_sha256", "runner_names"])
        for r in runs:
            d = HERE / str(r["id"])
            st = status_of(d)["logs_status"]
            z = d / "logs.zip"
            saved = st == "SAVED" and z.exists()
            w.writerow([r["id"], r["name"], r["event"], r["head_sha"], r["created_at"], r["updated_at"],
                        r["conclusion"], st, z.stat().st_size if saved else 0, sha256(z) if saved else "",
                        runner_names(d)])
    # run_log.txt is this script's own stdout, still open while the sums are written; it is not evidence.
    files = sorted(p for p in HERE.rglob("*") if p.is_file() and p.name not in ("SHA256SUMS.txt", "run_log.txt"))
    with open(HERE / "SHA256SUMS.txt", "w", newline="\n", encoding="utf-8") as f:
        for p in files:
            f.write(f"{sha256(p)}  {p.relative_to(HERE).as_posix()}\n")


def main():
    total, runs = listing()
    runs.sort(key=lambda r: r["created_at"])
    print(f"total_count={total} listed={len(runs)}", flush=True)
    for n, r in enumerate(runs, 1):
        archive(r)
        if n % 25 == 0:
            print(f"{n}/{len(runs)} {r['id']} {r['created_at']}", flush=True)
    write_index(runs)
    print("done", flush=True)


if __name__ == "__main__":
    main()
